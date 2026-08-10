"""The background thread that claims and executes queued model jobs.

One worker thread per process. It leases a job from SQLite, heartbeats while the
job runs so another process can detect a dead worker, and dispatches to the
validation or annual runner. Lease tokens fence the work: if a lease is lost
mid-run the result is discarded rather than written over a newer attempt.
"""

from __future__ import annotations

import logging
import threading
import traceback
from datetime import datetime, timedelta, timezone
from typing import Any

from time import perf_counter

from sbepv.api import config, state
from sbepv.api.artifacts import _delete_job_attempt_artifacts
from sbepv.api.config import SERVER_SESSION_ID
from sbepv.api.job_store import _cache_job_record, _get_job_record, _update_job
from sbepv.api.schemas import AnnualRunRequest, RunRequest
from sbepv.api.validation import (
    _annual_dates,
    _validate_curtailment,
    _validate_run_request,
)
from sbepv.store import AgentStoreError, LeaseOwnershipLost
from sbepv.worker import run_annual, run_validation
from sbepv.api.config import JOB_HEARTBEAT_SECONDS, JOB_STALE_SECONDS

logger = logging.getLogger(__name__)


def _start_model_worker() -> None:
    with state._WORKER_LOCK:
        if state._WORKER_THREAD is not None and state._WORKER_THREAD.is_alive():
            return
        state._WORKER_STOP.clear()
        state._WORKER_THREAD = threading.Thread(
            target=_model_worker_loop,
            name="solar-model-worker",
            daemon=True,
        )
        state._WORKER_THREAD.start()


def _stop_model_worker() -> None:
    with state._WORKER_LOCK:
        worker = state._WORKER_THREAD
        if worker is None:
            return
        state._WORKER_STOP.set()
        state._WORKER_WAKE.set()
    worker.join(timeout=5)
    with state._WORKER_LOCK:
        if not worker.is_alive():
            state._WORKER_THREAD = None


def _heartbeat_model_job(
    job_id: str, lease_token: str, stop: threading.Event
) -> None:
    while not stop.wait(JOB_HEARTBEAT_SECONDS):
        try:
            if not state.AGENT_STORE.heartbeat_job(
                job_id,
                worker_id=SERVER_SESSION_ID,
                lease_token=lease_token,
            ):
                return
        except Exception:
            logger.exception("Could not renew the lease for model job %s", job_id)


def _model_worker_loop() -> None:
    next_stale_check = 0.0
    while not state._WORKER_STOP.is_set():
        try:
            now = perf_counter()
            if now >= next_stale_check:
                interrupted = state.AGENT_STORE.mark_stale_running_jobs_interrupted(
                    before=datetime.now(timezone.utc)
                    - timedelta(seconds=JOB_STALE_SECONDS)
                )
                if interrupted:
                    logger.warning(
                        "Marked %s expired model job lease(s) interrupted",
                        interrupted,
                    )
                next_stale_check = now + min(JOB_STALE_SECONDS / 2, 30)
            record = state.AGENT_STORE.claim_next_queued_job(
                worker_id=SERVER_SESSION_ID
            )
        except AgentStoreError:
            logger.exception("The durable model queue could not claim a job")
            state._WORKER_WAKE.wait(1.0)
            state._WORKER_WAKE.clear()
            continue
        if record is None:
            state._WORKER_WAKE.wait(0.5)
            state._WORKER_WAKE.clear()
            continue
        _cache_job_record(record)
        job_id = str(record["id"])
        lease_token = str(record.get("lease_token") or "")
        if not lease_token:
            logger.error("Claimed model job %s without a lease token", job_id)
            continue
        heartbeat_stop = threading.Event()
        heartbeat = threading.Thread(
            target=_heartbeat_model_job,
            args=(job_id, lease_token, heartbeat_stop),
            name=f"solar-model-heartbeat-{job_id[:12]}",
            daemon=True,
        )
        heartbeat.start()
        try:
            if record["mode"] == "annual":
                req = AnnualRunRequest(**record["request"])
                _validate_run_request(req)
                _validate_curtailment(req)
                _annual_dates(req)
                provenance = record.get("provenance") or {}
                run_annual._run_annual_job(
                    job_id,
                    req,
                    source_path=record.get("source_path"),
                    expected_source_hash=record.get("source_hash"),
                    calibration_profile=provenance.get(
                        "calibration_profile"
                    ),
                    calibration_application_context=provenance.get(
                        "calibration_application"
                    ),
                    worker_id=SERVER_SESSION_ID,
                    lease_token=lease_token,
                )
            else:
                req = RunRequest(**record["request"])
                _validate_run_request(req)
                _validate_curtailment(req)
                provenance = record.get("provenance") or {}
                run_validation._run_job(
                    job_id,
                    req,
                    source_path=record.get("source_path"),
                    expected_source_hash=record.get("source_hash"),
                    data_quality_context=provenance.get("data_quality"),
                    calibration_profile=provenance.get(
                        "calibration_profile"
                    ),
                    worker_id=SERVER_SESSION_ID,
                    lease_token=lease_token,
                )
        except LeaseOwnershipLost:
            removed = _delete_job_attempt_artifacts(job_id, lease_token)
            logger.warning(
                "Stopped model job %s after its lease was lost; removed %s "
                "expired attempt artifact(s)",
                job_id,
                removed,
            )
        except Exception:
            logger.exception("Unhandled model worker failure for %s", job_id)
            current = _get_job_record(job_id)
            if current and current.get("state") == "running":
                try:
                    _update_job(
                        job_id,
                        worker_id=SERVER_SESSION_ID,
                        lease_token=lease_token,
                        state="error",
                        stage="Failed",
                        error="The model run failed. Review server logs and retry.",
                    )
                except LeaseOwnershipLost:
                    logger.warning(
                        "Ignored failure transition for %s after lease loss", job_id
                    )
        finally:
            heartbeat_stop.set()
            heartbeat.join(timeout=1)
