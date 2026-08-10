"""Recording the outcome of a model job, successful or not.

Both paths are lease-fenced: a worker whose lease was revoked mid-run must not
overwrite whatever claimed the job next, so a lost lease is logged and the
partial artifacts are cleaned up instead of published.
"""

from __future__ import annotations

import logging
import traceback
from pathlib import Path
from typing import Any

from sbepv.api import config, state
from sbepv.api.artifacts import _delete_job_attempt_artifacts, _job_attempt_prefix
from sbepv.api.job_store import (
    _JobCancelled,
    _check_job_cancelled,
    _get_job_record,
    _job_cancel_requested,
    _update_job,
)
from sbepv.reporting import generate_comparison_artifacts
from sbepv.store import AgentStoreError, LeaseOwnershipLost

logger = logging.getLogger(__name__)


def _artifact_file(result: dict[str, Any], key: str) -> Path:
    stats = result.get("stats") or {}
    raw = stats.get(key) or result.get(key)
    if not raw:
        raise ValueError(f"Model result is missing the {key} artifact")
    raw_path = Path(str(raw))
    if raw_path.is_absolute():
        return raw_path
    return config.OUTPUT_DIR / raw_path.name


def _finish_model_job(
    job_id: str,
    result: dict[str, Any],
    *,
    worker_id: str | None = None,
    lease_token: str | None = None,
) -> None:
    record = _get_job_record(job_id) or {"id": job_id, **state.JOBS.get(job_id, {})}
    artifacts = dict(record.get("artifacts") or {})
    if state.JOBS.get(job_id, {}).get("input_plots"):
        artifacts["input_plots"] = state.JOBS[job_id]["input_plots"]
    artifacts.setdefault(
        "model_workbook",
        {
            "path": str(_artifact_file(result, "excel")),
            "url": result.get("excel"),
            "filename": result.get("excel_filename"),
        },
    )

    comparison = None
    provenance = record.get("provenance")
    baseline_id = record.get("baseline_id")
    if baseline_id:
        _update_job(
            job_id,
            worker_id=worker_id,
            lease_token=lease_token,
            progress=97,
            stage="Calculating trusted comparison",
        )
        _check_job_cancelled(
            job_id, worker_id=worker_id, lease_token=lease_token
        )
        baseline = _get_job_record(str(baseline_id))
        if baseline is None or baseline.get("state") != "done":
            raise ValueError("The bound baseline is not available as a completed job")
        baseline_result = baseline.get("result") or {}
        comparison_type = "cross_run"
        if record.get("proposal_id"):
            proposal = state.AGENT_STORE.get_proposal(str(record["proposal_id"]))
            if proposal:
                comparison_type = proposal["comparison_kind"]
        generated = generate_comparison_artifacts(
            _artifact_file(baseline_result, "excel"),
            _artifact_file(result, "excel"),
            config.OUTPUT_DIR / _job_attempt_prefix(job_id, lease_token),
            baseline_job_id=str(baseline_id),
            candidate_job_id=job_id,
            baseline_request=baseline.get("request") or {},
            candidate_request=record.get("request") or {},
            baseline_source_path=baseline.get("source_path"),
            candidate_source_path=record.get("source_path"),
            baseline_source_sha256=baseline.get("source_hash"),
            candidate_source_sha256=record.get("source_hash"),
            comparison_type=comparison_type,
            mode=record.get("mode"),
            extra_warnings=tuple(result.get("warnings") or ()),
        )
        comparison = generated["comparison"]
        provenance = {
            **dict(provenance or {}),
            **dict(generated["provenance"] or {}),
        }
        artifacts.update(generated["artifacts"])

    _check_job_cancelled(job_id, worker_id=worker_id, lease_token=lease_token)
    _update_job(
        job_id,
        worker_id=worker_id,
        lease_token=lease_token,
        state="done",
        progress=100,
        stage="Done",
        result=result,
        comparison=comparison,
        provenance=provenance,
        artifacts=artifacts,
        error=None,
    )
    completed = _get_job_record(job_id)
    if (
        completed
        and completed.get("kind") in {"baseline", "manual"}
    ):
        try:
            with state._ORCHESTRATION_LOCK:
                state.AGENT_STORE.promote_job(job_id)
        except AgentStoreError:
            logger.exception("Completed baseline %s could not be promoted", job_id)


def _handle_model_failure(
    job_id: str,
    exc: Exception,
    *,
    worker_id: str | None = None,
    lease_token: str | None = None,
) -> None:
    if isinstance(exc, LeaseOwnershipLost):
        removed = _delete_job_attempt_artifacts(job_id, lease_token)
        logger.warning(
            "Ignoring model job %s after its lease was lost; removed %s "
            "expired attempt artifact(s)",
            job_id,
            removed,
        )
        return
    try:
        cancelled = _job_cancel_requested(
            job_id, worker_id=worker_id, lease_token=lease_token
        )
    except LeaseOwnershipLost:
        removed = _delete_job_attempt_artifacts(job_id, lease_token)
        logger.warning(
            "Ignoring model job %s after its lease was lost; removed %s "
            "expired attempt artifact(s)",
            job_id,
            removed,
        )
        return
    if isinstance(exc, _JobCancelled) or cancelled:
        current = _get_job_record(job_id)
        if current and current.get("state") == "running":
            try:
                _update_job(
                    job_id,
                    worker_id=worker_id,
                    lease_token=lease_token,
                    state="cancelled",
                    stage="Cancelled",
                    error=None,
                )
            except LeaseOwnershipLost:
                logger.warning(
                    "Ignored cancellation transition for %s after lease loss", job_id
                )
        return
    logger.error("Model job %s failed\n%s", job_id, traceback.format_exc())
    state.JOBS.setdefault(job_id, {})["traceback"] = traceback.format_exc()
    current = _get_job_record(job_id)
    if current and current.get("state") == "running":
        try:
            _update_job(
                job_id,
                worker_id=worker_id,
                lease_token=lease_token,
                state="error",
                stage="Failed",
                error="The model run failed. Review server logs and retry.",
            )
        except LeaseOwnershipLost:
            logger.warning(
                "Ignored failure transition for %s after lease loss", job_id
            )
    else:
        state.JOBS[job_id]["state"] = "error"
        state.JOBS[job_id]["error"] = str(exc) or exc.__class__.__name__
