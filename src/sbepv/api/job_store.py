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
from sbepv.store import (
    TECHNOECONOMIC_ID_PREFIX,
    AgentStoreError,
    JobCompletionCancelled,
    LeaseOwnershipLost,
    RecordNotFound,
)

logger = logging.getLogger(__name__)
_DURABLE_CACHE_MARKER = "_durable_model_job"


def _is_legacy_cached_model_job(job_id: str, cached: dict[str, Any]) -> bool:
    """Identify compatibility-only rows, never mirrors or isolated TEA jobs."""
    return (
        not str(job_id).startswith(TECHNOECONOMIC_ID_PREFIX)
        and not cached.get(_DURABLE_CACHE_MARKER)
    )


def _legacy_cached_model_jobs() -> list[tuple[str, dict[str, Any]]]:
    """Snapshot legacy rows in insertion order without using durable mirrors."""
    return [
        (job_id, cached)
        for job_id, cached in list(state.JOBS.items())
        if _is_legacy_cached_model_job(job_id, cached)
    ]


def _discard_durable_job_mirror(job_id: str) -> None:
    cached = state.JOBS.get(job_id)
    if cached is not None and cached.get(_DURABLE_CACHE_MARKER):
        state.JOBS.pop(job_id, None)


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
    cached[_DURABLE_CACHE_MARKER] = True
    input_plots = (record.get("artifacts") or {}).get("input_plots")
    if input_plots:
        cached["input_plots"] = input_plots
    return cached


def _get_durable_model_job_record(job_id: str) -> dict[str, Any] | None:
    """Return only a durable model job, never TEA work or a cache-only row.

    Promotion, model completion, and comparison publication use this stricter
    lookup.  Those workflows mutate durable model state and therefore must not
    inherit the legacy cache fallback provided by :func:`_get_job_record`.
    """

    normalized_job_id = str(job_id)
    if normalized_job_id.startswith(TECHNOECONOMIC_ID_PREFIX):
        return None
    record = state.AGENT_STORE.get_job(normalized_job_id)
    if record is not None:
        _cache_job_record(record)
    else:
        _discard_durable_job_mirror(normalized_job_id)
    return record


def _get_job_record(job_id: str) -> dict[str, Any] | None:
    normalized_job_id = str(job_id)
    # TEA has its own durable registry and API surface.  In particular, never
    # let a stale or adversarial compatibility-cache entry make a ``tea_`` id
    # look like a model job after the authoritative model lookup misses it.
    if normalized_job_id.startswith(TECHNOECONOMIC_ID_PREFIX):
        return None
    try:
        record = _get_durable_model_job_record(normalized_job_id)
    except AgentStoreError:
        logger.exception("Could not read durable job %s", normalized_job_id)
        raise
    if record is not None:
        return record
    cached = state.JOBS.get(normalized_job_id)
    if cached is None or not _is_legacy_cached_model_job(normalized_job_id, cached):
        return None
    return {"id": normalized_job_id, **cached}


class _JobCancelled(RuntimeError):
    pass


def _update_job(
    job_id: str,
    *,
    worker_id: str | None = None,
    lease_token: str | None = None,
    **fields: Any,
) -> dict[str, Any]:
    """Update durable work or an existing unleased compatibility-only row."""
    if (worker_id is None) != (lease_token is None):
        raise ValueError("worker_id and lease_token must be supplied together")
    if worker_id is not None and (
        not worker_id.strip() or not lease_token.strip()
    ):
        raise ValueError("job lease owner and token must not be blank")
    if str(job_id).startswith(TECHNOECONOMIC_ID_PREFIX):
        raise RecordNotFound(f"unknown model job: {job_id}")
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
    except JobCompletionCancelled:
        if fields.get("state") == "done":
            raise _JobCancelled("Cancellation requested") from None
        logger.exception("Could not update durable job %s", job_id)
        raise
    except LeaseOwnershipLost:
        raise
    except RecordNotFound as exc:
        _discard_durable_job_mirror(job_id)
        if worker_id is not None:
            raise LeaseOwnershipLost(
                f"runner no longer owns the active lease for missing job {job_id}"
            ) from exc
        raise
    except AgentStoreError:
        logger.exception("Could not update durable job %s", job_id)
        raise
    _discard_durable_job_mirror(job_id)
    if worker_id is not None:
        raise LeaseOwnershipLost(
            f"runner no longer owns the active lease for missing job {job_id}"
        )
    cached = state.JOBS.get(job_id)
    if cached is None or not _is_legacy_cached_model_job(job_id, cached):
        raise RecordNotFound(f"unknown job: {job_id}")
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
    for job_id, job in reversed(_legacy_cached_model_jobs()):
        if job.get("state") == "done" and (
            mode is None or job.get("mode", "validation") == mode
        ):
            return job_id
    return None
