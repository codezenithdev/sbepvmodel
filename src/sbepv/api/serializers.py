"""Shaping internal proposal and job records for the HTTP response body.

These are the only place that decides what the dashboard is allowed to see, so
internal fields such as absolute source paths and lease tokens are dropped here
rather than at each call site.
"""

from __future__ import annotations

import math
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from sbepv.agent.tool_schemas import SCENARIO_FIELD_LABELS, SCENARIO_OVERRIDE_FIELDS
from sbepv.api import config
from sbepv.api.job_store import _get_job_record


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
    artifacts = job.get("artifacts") or {}
    input_plots = artifacts.get("input_plots") or job.get("input_plots")
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
        "result": job.get("result"),
        "comparison": job.get("comparison"),
        "provenance": job.get("provenance"),
        "artifacts": artifacts,
        "request": job.get("request"),
    }
    if input_plots:
        payload["input_plots"] = input_plots
    if job.get("error"):
        payload["error"] = job["error"]
    return payload


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
