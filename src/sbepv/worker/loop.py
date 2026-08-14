"""The background thread that claims and executes queued durable work.

One worker thread per process. It leases a job from SQLite, heartbeats while the
job runs so another process can detect a dead worker, and dispatches to the
validation, annual, or technoeconomic runner. Lease tokens fence the work: if a
lease is lost mid-run the result is discarded rather than written over a newer
attempt.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta, timezone

from time import perf_counter

from sbepv.api import config, job_store, state
from sbepv.api.artifacts import (
    _delete_job_attempt_artifacts,
    _delete_technoeconomic_attempt_artifacts,
)
from sbepv.api.job_store import _cache_job_record, _get_job_record, _update_job
from sbepv.api.schemas import AnnualRunRequest, RunRequest
from sbepv.api.validation import (
    _annual_dates,
    _validate_curtailment,
    _validate_run_request,
)
from sbepv.store import AgentStoreError, LeaseOwnershipLost
from sbepv.worker import run_annual, run_technoeconomic, run_validation

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
    while not stop.wait(config.JOB_HEARTBEAT_SECONDS):
        try:
            if not state.AGENT_STORE.heartbeat_job(
                job_id,
                worker_id=config.SERVER_SESSION_ID,
                lease_token=lease_token,
            ):
                return
        except Exception:
            logger.exception("Could not renew the lease for model job %s", job_id)


def _heartbeat_technoeconomic_job(
    job_id: str, lease_token: str, stop: threading.Event
) -> None:
    while not stop.wait(config.JOB_HEARTBEAT_SECONDS):
        try:
            if not state.AGENT_STORE.heartbeat_technoeconomic_job(
                job_id,
                worker_id=config.SERVER_SESSION_ID,
                lease_token=lease_token,
            ):
                return
        except Exception:
            logger.exception(
                "Could not renew the lease for technoeconomic job %s", job_id
            )


def _mark_stale_running_work_interrupted(*, before: datetime) -> dict[str, int]:
    """Recover expired leases in both durable workflow registries."""

    model_count = state.AGENT_STORE.mark_stale_running_jobs_interrupted(before=before)
    technoeconomic_count = (
        state.AGENT_STORE.mark_stale_running_technoeconomic_jobs_interrupted(
            before=before
        )
    )
    if model_count:
        logger.warning(
            "Marked %s expired model job lease(s) interrupted", model_count
        )
    if technoeconomic_count:
        logger.warning(
            "Marked %s expired technoeconomic job lease(s) interrupted",
            technoeconomic_count,
        )
    return {"model": model_count, "technoeconomic": technoeconomic_count}


def _dispatch_model_job(
    record: dict,
    *,
    job_id: str,
    lease_token: str,
) -> None:
    mode = record.get("mode")
    if mode == "annual":
        req = AnnualRunRequest(**record["request"])
        _validate_run_request(req)
        _validate_curtailment(req)
        _annual_dates(req, allow_resolved_partial=True)
        provenance = record.get("provenance") or {}
        run_annual._run_annual_job(
            job_id,
            req,
            source_path=record.get("source_path"),
            expected_source_hash=record.get("source_hash"),
            calibration_profile=provenance.get("calibration_profile"),
            calibration_application_context=provenance.get(
                "calibration_application"
            ),
            worker_id=config.SERVER_SESSION_ID,
            lease_token=lease_token,
        )
        return
    if mode == "validation":
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
            calibration_profile=provenance.get("calibration_profile"),
            worker_id=config.SERVER_SESSION_ID,
            lease_token=lease_token,
        )
        return
    raise ValueError(f"Unsupported claimed model workflow mode: {mode!r}")


def _dispatch_claimed_work(
    record: dict,
    *,
    job_id: str,
    lease_token: str,
) -> None:
    workflow = record.get("workflow")
    if workflow == "model":
        _dispatch_model_job(record, job_id=job_id, lease_token=lease_token)
        return
    if workflow == "technoeconomic":
        run_technoeconomic._run_technoeconomic_job(
            job_id,
            record["request"],
            record["source_snapshot"],
            source_snapshot_sha256=record["source_snapshot_sha256"],
            submission_provenance=record["submission_provenance"],
            submission_provenance_sha256=record[
                "submission_provenance_sha256"
            ],
            source_annual_job_id=record["source_annual_job_id"],
            source_artifact_storage_key=record[
                "source_artifact_storage_key"
            ],
            source_artifact_sha256=record["source_artifact_sha256"],
            source_artifact_bytes=record["source_artifact_bytes"],
            worker_id=config.SERVER_SESSION_ID,
            lease_token=lease_token,
        )
        return
    raise ValueError(f"Unsupported claimed work discriminator: {workflow!r}")


def _handle_unexpected_worker_failure(
    workflow: str,
    job_id: str,
    lease_token: str,
    exc: Exception,
) -> None:
    if workflow == "model":
        logger.exception("Unhandled model worker failure for %s", job_id)
        current = _get_job_record(job_id)
        if current and current.get("state") == "running":
            try:
                _update_job(
                    job_id,
                    worker_id=config.SERVER_SESSION_ID,
                    lease_token=lease_token,
                    state="error",
                    stage="Failed",
                    error="The model run failed. Review server logs and retry.",
                )
            except LeaseOwnershipLost:
                logger.warning(
                    "Ignored failure transition for %s after lease loss", job_id
                )
        return

    if workflow != "technoeconomic":
        logger.exception(
            "Unhandled worker failure for unknown workflow %r and job %s",
            workflow,
            job_id,
        )
        return

    try:
        cancelled = state.AGENT_STORE.is_technoeconomic_cancel_requested(
            job_id,
            expected_worker_id=config.SERVER_SESSION_ID,
            expected_lease_token=lease_token,
        )
    except LeaseOwnershipLost:
        _delete_technoeconomic_attempt_artifacts(job_id, lease_token)
        logger.warning(
            "Ignored technoeconomic worker failure for %s after lease loss", job_id
        )
        return
    _delete_technoeconomic_attempt_artifacts(job_id, lease_token)
    try:
        if isinstance(exc, job_store._JobCancelled) or cancelled:
            state.AGENT_STORE.update_technoeconomic_job(
                job_id,
                expected_worker_id=config.SERVER_SESSION_ID,
                expected_lease_token=lease_token,
                state="cancelled",
                stage="Cancelled",
                error=None,
            )
        else:
            logger.exception(
                "Unhandled technoeconomic worker failure for %s", job_id
            )
            state.AGENT_STORE.update_technoeconomic_job(
                job_id,
                expected_worker_id=config.SERVER_SESSION_ID,
                expected_lease_token=lease_token,
                state="error",
                stage="Failed",
                error=(
                    "The technoeconomic analysis failed. Review server logs and "
                    "retry."
                ),
            )
    except LeaseOwnershipLost:
        logger.warning(
            "Ignored technoeconomic failure transition for %s after lease loss",
            job_id,
        )


def _model_worker_loop() -> None:
    next_stale_check = 0.0
    while not state._WORKER_STOP.is_set():
        try:
            now = perf_counter()
            if now >= next_stale_check:
                _mark_stale_running_work_interrupted(
                    before=datetime.now(timezone.utc)
                    - timedelta(seconds=config.JOB_STALE_SECONDS)
                )
                next_stale_check = now + min(
                    config.JOB_STALE_SECONDS / 2, 30
                )
            record = state.AGENT_STORE.claim_next_queued_work(
                worker_id=config.SERVER_SESSION_ID
            )
        except AgentStoreError:
            logger.exception("The durable work queue could not claim a job")
            state._WORKER_WAKE.wait(1.0)
            state._WORKER_WAKE.clear()
            continue
        if record is None:
            state._WORKER_WAKE.wait(0.5)
            state._WORKER_WAKE.clear()
            continue
        workflow = str(record.get("workflow") or "")
        if workflow not in {"model", "technoeconomic"}:
            logger.error(
                "Claimed work %s with unsupported workflow discriminator %r",
                record.get("id"),
                workflow,
            )
            continue
        if workflow == "model":
            _cache_job_record(record)
        job_id = str(record["id"])
        lease_token = str(record.get("lease_token") or "")
        if not lease_token:
            logger.error("Claimed %s job %s without a lease token", workflow, job_id)
            continue
        heartbeat_stop = threading.Event()
        heartbeat_target = (
            _heartbeat_model_job
            if workflow == "model"
            else _heartbeat_technoeconomic_job
        )
        heartbeat = threading.Thread(
            target=heartbeat_target,
            args=(job_id, lease_token, heartbeat_stop),
            name=f"solar-{workflow}-heartbeat-{job_id[:12]}",
            daemon=True,
        )
        heartbeat.start()
        try:
            _dispatch_claimed_work(
                record,
                job_id=job_id,
                lease_token=lease_token,
            )
        except LeaseOwnershipLost:
            if workflow == "model":
                removed = _delete_job_attempt_artifacts(job_id, lease_token)
            else:
                removed = _delete_technoeconomic_attempt_artifacts(
                    job_id, lease_token
                )
            logger.warning(
                "Stopped %s job %s after its lease was lost; removed %s "
                "expired attempt artifact(s)",
                workflow,
                job_id,
                removed,
            )
        except Exception as exc:
            _handle_unexpected_worker_failure(
                workflow,
                job_id,
                lease_token,
                exc,
            )
        finally:
            heartbeat_stop.set()
            heartbeat.join(timeout=1)
