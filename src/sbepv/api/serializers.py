"""Shaping internal proposal and job records for the HTTP response body.

These are the only place that decides what the dashboard is allowed to see, so
internal fields such as absolute source paths and lease tokens are dropped here
rather than at each call site.
"""

from __future__ import annotations

import math
import re
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any

from sbepv.agent.tool_schemas import SCENARIO_FIELD_LABELS, SCENARIO_OVERRIDE_FIELDS
from sbepv.api import config
from sbepv.api.job_store import _get_job_record


_PRIVATE_PATH_KEYS = {
    "path",
    "source_path",
    "cleaned_source_path",
    "input_csv",
    "storage_key",
    "source_artifact_storage_key",
}
_PRIVATE_METADATA_KEYS = {
    "annual_source_audit",
    "heartbeat_at",
    "lease_token",
    "source_snapshot",
    "worker_id",
}
_PRIVATE_PATH_FRAGMENT = re.compile(
    r"(?i)(?:\\\\[^\\/\s]+[\\/][^\s]+|\b[a-z]:[\\/]|file:(?:/{0,3})|"
    r"(?<![:/\w])/(?!/?(?:outputs|api)(?:/|$)))"
)


def _looks_like_private_path(value: str) -> bool:
    text = value.strip()
    if not text or text.startswith(("https://", "http://", "/outputs/", "/api/")):
        return False
    if text.lower().startswith("file:"):
        return True
    return PurePosixPath(text).is_absolute() or PureWindowsPath(text).is_absolute()


def _contains_private_path(value: str) -> bool:
    """Detect standalone or embedded server-local path text."""

    return _looks_like_private_path(value) or bool(_PRIVATE_PATH_FRAGMENT.search(value))


def _public_value(value: Any) -> Any:
    """Recursively remove server-local filesystem details from a JSON value."""

    if isinstance(value, dict):
        public: dict[str, Any] = {}
        for raw_key, item in value.items():
            key = str(raw_key)
            normalized_key = key.strip().lower()
            if normalized_key in _PRIVATE_METADATA_KEYS:
                continue
            if (
                normalized_key in _PRIVATE_PATH_KEYS
                or normalized_key.endswith("_path")
                or normalized_key.endswith("_storage_key")
            ):
                continue
            if isinstance(item, str) and _contains_private_path(item):
                continue
            public[key] = _public_value(item)
        return public
    if isinstance(value, (list, tuple)):
        return [
            _public_value(item)
            for item in value
            if not (isinstance(item, str) and _contains_private_path(item))
        ]
    if isinstance(value, str) and _contains_private_path(value):
        return None
    return deepcopy(value)


def _public_error(value: Any) -> str:
    """Return useful error text without exposing a server-local path."""

    public_error = _public_value(str(value or "Unknown error"))
    return public_error or (
        "The run could not be completed. Check the server logs for details."
    )


def _public_proposal(proposal: dict[str, Any]) -> dict[str, Any]:
    metadata = proposal.get("confirmation_metadata") or {}
    unchanged_fields: list[dict[str, Any]] = []
    if proposal.get("baseline_id"):
        baseline = _get_job_record(str(proposal["baseline_id"]))
        baseline_request = (baseline or {}).get("request") or {}
        candidate_request = proposal.get("effective_request") or {}
        changed_names = {
            str(item.get("field"))
            for item in (proposal.get("changes") or [])
            if isinstance(item, dict)
        }
        for field in SCENARIO_OVERRIDE_FIELDS:
            if field == "mode" or field in changed_names or field not in candidate_request:
                continue
            unchanged_fields.append(
                {
                    "field": field,
                    "label": SCENARIO_FIELD_LABELS[field],
                    "value": baseline_request.get(field, candidate_request.get(field)),
                }
            )
    return {
        "proposal_id": proposal["id"],
        "kind": metadata.get("job_kind", "candidate"),
        "status": proposal["state"],
        "baseline_job_id": proposal.get("baseline_id"),
        "mode": proposal["mode"],
        "comparison_kind": proposal["comparison_kind"],
        "confirmation_required": proposal["confirmation_required"],
        "confirmation_reason": proposal.get("confirmation_reason"),
        "changes": proposal.get("changes") or [],
        "unchanged_fields": unchanged_fields,
        "effective_request": proposal.get("effective_request") or {},
        "scenario_sweep": (
            deepcopy(metadata.get("scenario_sweep"))
            if isinstance(metadata.get("scenario_sweep"), dict)
            else None
        ),
        "expires_at": proposal.get("expires_at"),
        "created_at": proposal.get("created_at"),
        "confirmed_job_id": proposal.get("confirmed_job_id"),
    }


def _public_job(job: dict[str, Any]) -> dict[str, Any]:
    internal_artifacts = job.get("artifacts") or {}
    input_plots = internal_artifacts.get("input_plots") or job.get("input_plots")
    artifacts = _public_value(internal_artifacts)
    elapsed_seconds: float | None = None
    started_at = job.get("started_at") or job.get("created_at")
    if started_at:
        try:
            started = datetime.fromisoformat(str(started_at))
            if started.tzinfo is None:
                started = started.replace(tzinfo=timezone.utc)
            ended_raw = job.get("completed_at")
            ended = (
                datetime.fromisoformat(str(ended_raw))
                if ended_raw
                else datetime.now(timezone.utc)
            )
            if ended.tzinfo is None:
                ended = ended.replace(tzinfo=timezone.utc)
            elapsed_seconds = max((ended - started).total_seconds(), 0.0)
        except (TypeError, ValueError):
            pass
    payload = {
        "job_id": job["id"],
        "kind": job.get("kind", "manual"),
        "origin": "solar_agent" if job.get("proposal_id") else "dashboard",
        "proposal_id": job.get("proposal_id"),
        "baseline_job_id": job.get("baseline_id"),
        "mode": job.get("mode", "validation"),
        "state": job.get("state", "queued"),
        "progress": job.get("progress", 0),
        "stage": job.get("stage", ""),
        "cancel_requested": bool(job.get("cancel_requested")),
        "created_at": job.get("created_at"),
        "started_at": job.get("started_at"),
        "completed_at": job.get("completed_at"),
        "elapsed_seconds": elapsed_seconds,
        "result": _public_value(job.get("result")),
        "comparison": _public_value(job.get("comparison")),
        "provenance": _public_value(job.get("provenance")),
        "artifacts": artifacts,
        "request": _public_value(job.get("request")),
    }
    if input_plots:
        payload["input_plots"] = _public_value(input_plots)
    if job.get("error"):
        payload["error"] = _public_error(job["error"])
    return payload


def _public_technoeconomic_job(job: dict[str, Any]) -> dict[str, Any]:
    """Return the strict public projection of one durable TEA job.

    The durable row intentionally contains a complete source snapshot, private
    content-addressed storage identity, and active lease fields.  Status callers
    need none of those.  Keep this as an explicit allowlist and apply the recursive
    path scrubber only to the user/result values that are intentionally public.
    """

    elapsed_seconds: float | None = None
    started_at = job.get("started_at") or job.get("created_at")
    if started_at:
        try:
            started = datetime.fromisoformat(str(started_at))
            if started.tzinfo is None:
                started = started.replace(tzinfo=timezone.utc)
            ended_raw = job.get("completed_at")
            ended = (
                datetime.fromisoformat(str(ended_raw))
                if ended_raw
                else datetime.now(timezone.utc)
            )
            if ended.tzinfo is None:
                ended = ended.replace(tzinfo=timezone.utc)
            elapsed_seconds = max((ended - started).total_seconds(), 0.0)
        except (TypeError, ValueError):
            pass

    payload = {
        "job_id": job["id"],
        "workflow": "technoeconomic",
        "state": job.get("state", "queued"),
        "progress": job.get("progress", 0),
        "stage": job.get("stage", ""),
        "cancel_requested": bool(job.get("cancel_requested")),
        "retry_of_job_id": job.get("retry_of_job_id"),
        "source_annual_job_id": job.get("source_annual_job_id"),
        "source_artifact_sha256": job.get("source_artifact_sha256"),
        "source_artifact_bytes": job.get("source_artifact_bytes"),
        "source_snapshot_sha256": job.get("source_snapshot_sha256"),
        "submission_provenance_sha256": job.get(
            "submission_provenance_sha256"
        ),
        "created_at": job.get("created_at"),
        "queued_at": job.get("queued_at"),
        "started_at": job.get("started_at"),
        "completed_at": job.get("completed_at"),
        "updated_at": job.get("updated_at"),
        "elapsed_seconds": elapsed_seconds,
        "request": _public_value(job.get("request")),
        "result": _public_value(job.get("result")),
        "result_provenance": _public_value(job.get("result_provenance")),
        "artifacts": _public_value(job.get("artifacts")),
    }
    if job.get("error"):
        payload["error"] = _public_error(job["error"])
    return payload


def _public_saved_result(saved_result: dict[str, Any]) -> dict[str, Any]:
    """Return saved metadata plus the same path-safe job used by status APIs."""

    return {
        "job_id": str(saved_result["job_id"]),
        "name": str(saved_result["name"]),
        "saved_at": saved_result.get("saved_at"),
        "updated_at": saved_result.get("updated_at"),
        "job": _public_job(saved_result["job"]),
    }


def _chat_timing(
    *, gpt_seconds: float, model_job_id: str | None
) -> dict[str, Any]:
    """Build timing metadata for one Solar Agent response."""

    model_run_seconds: float | None = None
    model_run_status = "not_run"
    if model_job_id:
        job = _get_job_record(model_job_id)
        if job is not None:
            public_job = _public_job(job)
            state = str(public_job.get("state") or "not_run")
            model_run_status = "completed" if state == "done" else state
            elapsed = public_job.get("elapsed_seconds")
            if (
                state == "done"
                and isinstance(elapsed, (int, float))
                and math.isfinite(float(elapsed))
            ):
                model_run_seconds = round(max(float(elapsed), 0.0), 3)

    return {
        "response_timestamp": datetime.now(timezone.utc).isoformat(),
        "gpt_seconds": round(max(float(gpt_seconds), 0.0), 3),
        "model_run_seconds": model_run_seconds,
        "model_run_status": model_run_status,
    }
