"""Prepare independently confirmable calibration reviews with MIDC weather."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import uuid
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from sbepv import calibration, reporting, weather_evidence
from sbepv.api import config, review_store, state
from sbepv.api.schemas import CalibrationWeatherRequest
from sbepv.api.timewindows import _iso
from sbepv.ingest import calibration_weather, midc


def _add_unavailable_issues(report: dict[str, Any], audit: dict[str, Any]) -> None:
    """A failed manual replacement needs review even for plausible source values."""
    for field in audit["fields"]:
        events = [event for event in audit["events"] if event["column"] == field and event["status"] == "unavailable"]
        if not events:
            continue
        report["issues"].append({
            "id": f"midc.unavailable.{field}",
            "category": "weather_replacement",
            "severity": "high",
            "title": f"MIDC replacement unavailable: {calibration.COLUMN_LABELS[field]}",
            "description": (
                "A verified MIDC replacement could not be matched because source "
                "coverage or interval alignment was unsuitable. Explicitly retain "
                "the original values (the existing model fallback may apply) or "
                "exclude these rows. No MIDC substitution was made for these cells."
            ),
            "columns": [field],
            "row_count": len(events),
            "_row_positions": sorted({event["row_position"] for event in events}),
            "sample_timestamps": [event["timestamp_utc"] for event in events[:8]],
            "allowed_actions": ["retain", "exclude"],
            "recommended_action": "exclude",
            "requires_explicit_decision": True,
            "evidence": {"unavailable_cells": len(events)},
        })
    issues = report["issues"]
    summary = report["summary"]
    affected = {position for issue in issues for position in issue.get("_row_positions", [])}
    summary.update({
        "issue_count": len(issues),
        "actionable_issue_count": sum(len(issue.get("allowed_actions", [])) > 1 for issue in issues),
        "affected_rows": len(affected),
        "affected_row_pct": round(len(affected) / max(report["source"]["row_count"], 1) * 100, 3),
        "severity_counts": {severity: sum(issue["severity"] == severity for issue in issues) for severity in ("critical", "high", "medium", "low")},
    })
    summary["blocking"] = any(issue["severity"] == "critical" for issue in issues)
    summary["status"] = "blocked" if summary["blocking"] else "action_required" if issues else "clean"


def public_weather_preview(record: dict[str, Any], *, offset: int = 0, limit: int = 50) -> dict[str, Any]:
    if offset < 0 or not 1 <= limit <= 200:
        raise HTTPException(status_code=422, detail="Preview offset must be nonnegative and limit must be 1–200.")
    metadata = record.get("weather_replacement")
    if not metadata:
        raise HTTPException(status_code=404, detail="This review has no MIDC replacement preview.")
    evidence = weather_evidence.load_weather_evidence(metadata)
    events = evidence["audit"]["events"]
    public = {key: deepcopy(value) for key, value in metadata.items() if key not in {"evidence_path"}}
    public.update({
        "events": [{**{key: value for key, value in event.items() if key not in {"row_position", "column", "timestamp_utc"}}, "timestamp": event["timestamp_utc"], "field": event["column"], "source_row": event["row_position"] + 2} for event in events[offset:offset + limit]],
        "offset": offset,
        "limit": limit,
        "total_events": len(events),
        "has_more": offset + limit < len(events),
    })
    return public


def prepare_weather_review(review_id: str, request: CalibrationWeatherRequest) -> dict[str, Any]:
    # Take an immutable snapshot under the lock; network work must not hold it.
    with state._ORCHESTRATION_LOCK:
        original = review_store._load_calibration_review(review_id)
        if original.get("state") != "pending":
            raise HTTPException(status_code=409, detail="Start a new review before changing weather for a consumed review.")
        if original.get("weather_replacement"):
            raise HTTPException(status_code=422, detail="Prepare replacement choices from the original review, not a previous MIDC preview.")
        original = deepcopy(original)
    fields = list(request.fields)
    if len(set(fields)) != len(fields):
        raise HTTPException(status_code=422, detail="Choose each weather field only once.")
    selected = {key: getattr(request, key) for key in ("from_date", "from_time", "to_date", "to_time")}
    try:
        if request.mode == "period":
            if not all(selected.values()):
                raise ValueError("A known-bad period requires both local start and end dates/times.")
            start_utc = _iso(request.from_date, request.from_time) + "+00:00"
            end_utc = _iso(request.to_date, request.to_time) + "+00:00"
        else:
            if any(value is not None for value in selected.values()):
                raise ValueError("Dates are only accepted for known-bad period replacement.")
            start_utc = end_utc = None
        run_request = original["request"]
        requested_start = _iso(run_request["from_date"], run_request["from_time"]) + "+00:00"
        requested_end = _iso(run_request["to_date"], run_request["to_time"]) + "+00:00"
        interval_seconds = int(run_request["interval_value"]) * config.UNIT_SECONDS[run_request["interval_unit"]]
        frame, audit = calibration_weather.prepare_weather_replacement(
            original["source_path"], original["report"], fields=fields,
            mode=request.mode, start_utc=start_utc, end_utc=end_utc,
            interval_seconds=interval_seconds, requested_start=requested_start,
            requested_end=requested_end,
        )
    except midc.MidcError as exc:
        raise HTTPException(status_code=502, detail=f"MIDC retrieval failed: {exc}") from exc
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    child_id = uuid.uuid4().hex
    source = review_store._calibration_review_path(child_id, ".raw.csv")
    evidence_path = review_store._calibration_review_path(child_id, ".weather.json")
    try:
        # Build private files outside the orchestration lock. They are unpublished
        # until the atomic review receipt is committed after the parent recheck.
        original_hash = reporting.verify_source_sha256(original["source_path"], original["source_hash"])
        original_text = Path(original["source_path"]).read_bytes().decode("utf-8")
        frame.to_csv(source, index=False)
        source_hash = reporting.sha256_file(source)
        report = calibration.inspect_historian_csv(
            source, expected_interval_seconds=interval_seconds,
            requested_start=requested_start, requested_end=requested_end,
        )
        _add_unavailable_issues(report, audit)
        report["source"]["sha256"] = source_hash
        evidence = {
            "schema_version": 1,
            "original_review_id": review_id,
            "original_source_sha256": original_hash,
            "original_csv_text": original_text,
            "original_report": original["report"],
            "prepared_source_sha256": source_hash,
            "audit": audit,
        }
        evidence_bytes = json.dumps(evidence, allow_nan=False, sort_keys=True).encode("utf-8")
        evidence_path.write_bytes(evidence_bytes)
        metadata = {
            "policy": audit["policy"], "station": "STAC",
            "original_review_id": review_id, "original_source_sha256": original_hash,
            "fields": fields, "mode": request.mode,
            "selection": selected if request.mode == "period" else {},
            **audit["counts"], "source_warnings": audit.get("source_warnings", []),
            "source_timezone": audit["source_timezone"], "wind_height_m": audit["wind_height_m"],
            "interval_seconds": interval_seconds,
            "evidence_path": str(evidence_path.resolve()),
            "evidence_sha256": hashlib.sha256(evidence_bytes).hexdigest(),
            "prepared_at": datetime.now(timezone.utc).isoformat(),
        }
        child = {
            "review_id": child_id, "state": "pending",
            "created_at": metadata["prepared_at"], "expires_at": original["expires_at"],
            "request": run_request, "source_path": str(source.resolve()),
            "source_hash": source_hash, "source_row_count": len(frame),
            "report": report, "weather_replacement": metadata,
        }
        preview = public_weather_preview(child)
        # Expired/tampered/consumed parents cannot publish a new preview.
        with state._ORCHESTRATION_LOCK:
            current = review_store._load_calibration_review(review_id)
            if current.get("state") != "pending" or current["source_hash"] != original["source_hash"]:
                raise HTTPException(status_code=409, detail="The original review changed while preparing MIDC weather.")
            review_store._save_calibration_review(child)
        return {
            "review_id": child_id, "state": review_store._calibration_review_state(report),
            "created_at": child["created_at"], "expires_at": child["expires_at"],
            "report": calibration.public_quality_report(report),
            "weather_replacement": preview,
        }
    except Exception:
        review_store._delete_calibration_review_artifacts(child_id)
        raise
