"""In-memory view over the durable job registry, plus cancellation signalling.

SQLite (``state.AGENT_STORE``) is authoritative and survives restarts; ``state.JOBS``
is a read-through cache that also carries two fields SQLite never stores --
``input_plots`` and ``traceback`` -- which is why the merge in ``_cache_job_record``
preserves them explicitly rather than overwriting wholesale.
"""

from __future__ import annotations

import logging
from typing import Any

from sbepv.api import state
from sbepv.store import AgentStoreError, LeaseOwnershipLost

logger = logging.getLogger(__name__)


def _cache_job_record(record: dict[str, Any]) -> dict[str, Any]:
    """Mirror a durable job into the legacy process cache."""
    job_id = str(record["id"])
    cached = state.JOBS.setdefault(job_id, {})
    runtime_fields = {
        key: cached[key]
        for key in ("input_plots", "traceback")
        if key in cached
    }
    cached.update({key: value for key, value in record.items() if key != "id"})
    cached.update(runtime_fields)
    input_plots = (record.get("artifacts") or {}).get("input_plots")
    if input_plots:
        cached["input_plots"] = input_plots
    return cached


def _get_job_record(job_id: str) -> dict[str, Any] | None:
    try:
        record = state.AGENT_STORE.get_job(job_id)
    except AgentStoreError:
        logger.exception("Could not read durable job %s", job_id)
        record = None
    if record is not None:
        _cache_job_record(record)
        return record
    cached = state.JOBS.get(job_id)
    if cached is None:
        return None
    return {"id": job_id, **cached}


def _update_job(
    job_id: str,
    *,
    worker_id: str | None = None,
    lease_token: str | None = None,
    **fields: Any,
) -> dict[str, Any]:
    """Update SQLite when present and always keep the compatibility cache fresh."""
    try:
        if state.AGENT_STORE.get_job(job_id) is not None:
            record = state.AGENT_STORE.update_job(
                job_id,
                expected_worker_id=worker_id,
                expected_lease_token=lease_token,
                **fields,
            )
            _cache_job_record(record)
            return record
    except LeaseOwnershipLost:
        raise
    except AgentStoreError:
        logger.exception("Could not update durable job %s", job_id)
        raise
    cached = state.JOBS.setdefault(job_id, {})
    cached.update(fields)
    artifacts = fields.get("artifacts")
    if isinstance(artifacts, dict) and artifacts.get("input_plots"):
        cached["input_plots"] = artifacts["input_plots"]
    return {"id": job_id, **cached}


def _job_cancel_requested(
    job_id: str,
    *,
    worker_id: str | None = None,
    lease_token: str | None = None,
) -> bool:
    if worker_id is not None or lease_token is not None:
        return state.AGENT_STORE.is_cancel_requested(
            job_id,
            expected_worker_id=worker_id,
            expected_lease_token=lease_token,
        )
    record = _get_job_record(job_id)
    if record is None:
        return False
    if record.get("cancel_requested"):
        return True
    return bool(state.JOBS.get(job_id, {}).get("cancel_requested"))


class _JobCancelled(RuntimeError):
    pass


def _check_job_cancelled(
    job_id: str,
    *,
    worker_id: str | None = None,
    lease_token: str | None = None,
) -> None:
    if _job_cancel_requested(
        job_id, worker_id=worker_id, lease_token=lease_token
    ):
        raise _JobCancelled("Cancellation requested")


def _latest_completed_job_id(mode: str | None = None) -> str | None:
    modes = (mode,) if mode in {"validation", "annual"} else ("validation", "annual")
    for selected_mode in modes:
        promoted = state.AGENT_STORE.get_current_baseline(selected_mode)
        if promoted and promoted.get("job_id"):
            return str(promoted["job_id"])
    completed = state.AGENT_STORE.list_jobs(states=["done"], mode=mode, limit=1)
    if completed:
        return str(completed[0]["id"])
    for job_id, job in reversed(state.JOBS.items()):
        if job.get("state") == "done" and (
            mode is None or job.get("mode", "validation") == mode
        ):
            return job_id
    return None
