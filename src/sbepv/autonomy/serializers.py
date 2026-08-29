"""Safe public projections for durable Autonomy records."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
import math
import re
from typing import Any

_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_PRIVATE_KEY_PARTS = (
    "api_key",
    "authorization",
    "secret",
    "claim_token",
    "lease_token",
    "worker_id",
    "storage_key",
    "storage_path",
    "filesystem",
    "server_path",
    "temp_path",
    "raw_content",
)


def _safe_text(value: object, *, limit: int = 20_000) -> str | None:
    if value is None:
        return None
    text = _CONTROL_RE.sub("", str(value)).strip()
    return text[:limit]


def safe_public_value(value: Any, *, depth: int = 0) -> Any:
    """Copy JSON-like data while stripping secrets, paths, and invalid numbers."""

    if depth > 8:
        return None
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, str):
        return _safe_text(value)
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for raw_key, item in value.items():
            key = _safe_text(raw_key, limit=128)
            if not key:
                continue
            normalized = key.casefold()
            if any(part in normalized for part in _PRIVATE_KEY_PARTS):
                continue
            result[key] = safe_public_value(item, depth=depth + 1)
        return result
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        return [safe_public_value(item, depth=depth + 1) for item in value[:1_000]]
    return _safe_text(value)


def _pick(record: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in record:
            return record.get(key)
    return None


def public_decision_case(record: Mapping[str, Any]) -> dict[str, Any]:
    source_job_id = _pick(record, "source_annual_job_id", "annual_source_job_id")
    source_sha = _pick(record, "source_snapshot_sha256", "annual_source_snapshot_sha256")
    basis_job_id = _pick(record, "basis_calibration_job_id", "calibration_job_id")
    basis_promoted_at = _pick(
        record, "basis_calibration_promoted_at", "calibration_promoted_at"
    )
    locked_at = _pick(
        record, "source_basis_locked_at", "source_locked_at", "basis_locked_at"
    )
    locked_by = _pick(
        record, "source_basis_locked_by", "source_locked_by", "basis_locked_by"
    )
    basis_lock = {
        "locked": bool(source_job_id or source_sha or basis_job_id),
        "source_annual_job_id": _safe_text(source_job_id, limit=128),
        "source_snapshot_sha256": _safe_text(source_sha, limit=64),
        "calibration_job_id": _safe_text(basis_job_id, limit=128),
        "calibration_promoted_at": _safe_text(basis_promoted_at, limit=64),
        "analysis_basis": _safe_text(record.get("analysis_basis"), limit=300),
        "locked_at": _safe_text(locked_at, limit=64),
        "locked_by": _safe_text(locked_by, limit=300),
    }
    return {
        "case_id": _safe_text(_pick(record, "case_id", "id"), limit=128),
        "title": _safe_text(record.get("title"), limit=300),
        "original_question": _safe_text(record.get("original_question"), limit=4_000),
        "question": _safe_text(record.get("question"), limit=4_000),
        "status": _safe_text(record.get("status"), limit=64),
        "owner": _safe_text(
            _pick(record, "decision_owner", "owner"), limit=300
        ),
        "created_by": _safe_text(record.get("created_by"), limit=300),
        "updated_by": _safe_text(record.get("updated_by"), limit=300),
        "active_recommendation_revision": record.get("active_recommendation_revision"),
        "revision": int(record.get("revision") or 0),
        "created_at": _safe_text(record.get("created_at"), limit=64),
        "updated_at": _safe_text(record.get("updated_at"), limit=64),
        "archived_at": _safe_text(record.get("archived_at"), limit=64),
        "basis_lock": basis_lock,
        "source_lock": {
            **basis_lock,
            "annual_job_id": basis_lock["source_annual_job_id"],
        },
    }


def public_decision_message(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "message_id": _safe_text(_pick(record, "message_id", "id"), limit=128),
        "case_id": _safe_text(record.get("case_id"), limit=128),
        "turn_id": _safe_text(record.get("turn_id"), limit=128),
        "message_sequence": int(record.get("message_sequence") or 0),
        "role": _safe_text(record.get("role"), limit=32),
        "status": _safe_text(record.get("status"), limit=32),
        "content": _safe_text(
            _pick(record, "content_text", "content"), limit=20_000
        ),
        "basis_label": _safe_text(record.get("basis_label"), limit=100),
        "structured_output": safe_public_value(record.get("structured_output")),
        "citations": safe_public_value(record.get("citations") or []),
        "trace_id": _safe_text(record.get("trace_id"), limit=128),
        "operator_name": _safe_text(record.get("operator_name"), limit=300),
        "error_code": _safe_text(record.get("error_code"), limit=64),
        "created_at": _safe_text(record.get("created_at"), limit=64),
    }


def public_decision_turn(record: Mapping[str, Any]) -> dict[str, Any]:
    user_message = record.get("user_message")
    assistant_message = record.get("assistant_message")
    if not isinstance(user_message, Mapping):
        user_message = {}
    if not isinstance(assistant_message, Mapping):
        assistant_message = {}
    return {
        "turn_id": _safe_text(_pick(record, "turn_id", "id"), limit=128),
        "case_id": _safe_text(record.get("case_id"), limit=128),
        "state": _safe_text(record.get("state"), limit=32),
        "client_message_id": _safe_text(record.get("client_message_id"), limit=128),
        "user_message_id": _safe_text(
            _pick(record, "user_message_id") or user_message.get("id"), limit=128
        ),
        "assistant_message_id": _safe_text(
            _pick(record, "assistant_message_id") or assistant_message.get("id"),
            limit=128,
        ),
        "trace_id": _safe_text(record.get("trace_id"), limit=128),
        "error_code": _safe_text(record.get("error_code"), limit=64),
        "created_at": _safe_text(record.get("created_at"), limit=64),
        "started_at": _safe_text(
            _pick(record, "claimed_at", "started_at"), limit=64
        ),
        "completed_at": _safe_text(record.get("completed_at"), limit=64),
        "failed_at": _safe_text(record.get("failed_at"), limit=64),
        "user_message": public_decision_message(user_message) if user_message else None,
        "assistant_message": (
            public_decision_message(assistant_message) if assistant_message else None
        ),
    }


def public_evidence_candidate(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "candidate_id": _safe_text(
            _pick(record, "candidate_id", "id"), limit=128
        ),
        "evidence_id": _safe_text(
            _pick(record, "evidence_asset_id", "evidence_id"), limit=128
        ),
        "field": _safe_text(_pick(record, "field_name", "field"), limit=300),
        "value": safe_public_value(_pick(record, "field_value", "value")),
        "unit": _safe_text(record.get("unit"), limit=100),
        "confidence": (
            float(record["confidence"])
            if isinstance(record.get("confidence"), (int, float))
            and math.isfinite(float(record["confidence"]))
            else None
        ),
        "source_location": safe_public_value(record.get("source_location")),
        "review_state": _safe_text(
            _pick(record, "review_state", "status"), limit=32
        ),
        "evidence_class": _safe_text(record.get("evidence_class"), limit=100),
        "review_rationale": _safe_text(record.get("review_rationale"), limit=2_000),
        "reviewed_by": _safe_text(
            _pick(record, "reviewed_by", "operator_name"), limit=300
        ),
        "reviewed_at": _safe_text(record.get("reviewed_at"), limit=64),
        "receipt": public_evidence_receipt(record.get("receipt")),
    }


def public_evidence_receipt(record: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not record:
        return None
    return {
        "receipt_id": _safe_text(_pick(record, "receipt_id", "id"), limit=128),
        "case_id": _safe_text(record.get("case_id"), limit=128),
        "evidence_id": _safe_text(
            _pick(record, "evidence_asset_id", "evidence_id"), limit=128
        ),
        "candidate_id": _safe_text(
            _pick(record, "evidence_candidate_id", "candidate_id"), limit=128
        ),
        "decision": _safe_text(record.get("decision"), limit=32),
        "evidence_class": _safe_text(record.get("evidence_class"), limit=100),
        "field": _safe_text(_pick(record, "field_name", "field"), limit=300),
        "value": safe_public_value(_pick(record, "field_value", "value")),
        "unit": _safe_text(record.get("unit"), limit=100),
        "source_location": safe_public_value(record.get("source_location")),
        "content_sha256": _safe_text(
            _pick(record, "asset_sha256", "content_sha256"), limit=64
        ),
        "byte_count": int(record.get("asset_byte_count") or 0),
        "preservation_mode": _safe_text(record.get("preservation_mode"), limit=64)
        or "server_managed_content_v1",
        "accepted_by": _safe_text(
            _pick(record, "operator_name", "accepted_by"), limit=300
        ),
        "accepted_at": _safe_text(
            _pick(record, "reviewed_at", "accepted_at"), limit=64
        ),
        "acceptance_rationale": _safe_text(
            _pick(record, "rationale", "acceptance_rationale"), limit=2_000
        ),
        "receipt_sha256": _safe_text(record.get("receipt_sha256"), limit=64),
    }


def public_evidence_asset(record: Mapping[str, Any]) -> dict[str, Any]:
    evidence_id = _safe_text(_pick(record, "evidence_id", "id"), limit=128)
    candidates = record.get("candidates") or []
    receipt = record.get("receipt")
    return {
        "evidence_id": evidence_id,
        "case_id": _safe_text(record.get("case_id"), limit=128),
        "filename": _safe_text(
            _pick(record, "original_filename", "filename"), limit=255
        ),
        "media_type": _safe_text(
            _pick(record, "detected_media_type", "media_type"), limit=128
        ),
        "declared_media_type": _safe_text(record.get("declared_media_type"), limit=128),
        "extension": _safe_text(record.get("canonical_extension"), limit=16),
        "byte_count": int(record.get("byte_count") or 0),
        "content_sha256": _safe_text(
            _pick(record, "content_sha256", "sha256"), limit=64
        ),
        "review_state": _safe_text(
            _pick(record, "review_state", "status"), limit=32
        ),
        "evidence_class": _safe_text(record.get("evidence_class"), limit=100),
        "uploaded_by": _safe_text(record.get("uploaded_by"), limit=300),
        "uploaded_at": _safe_text(
            _pick(record, "uploaded_at", "created_at"), limit=64
        ),
        "reviewed_by": _safe_text(record.get("reviewed_by"), limit=300),
        "reviewed_at": _safe_text(record.get("reviewed_at"), limit=64),
        "review_rationale": _safe_text(record.get("review_rationale"), limit=2_000),
        "deleted_at": _safe_text(
            _pick(record, "removed_at", "deleted_at"), limit=64
        ),
        "extraction_status": _safe_text(record.get("extraction_status"), limit=32),
        "preservation_mode": "server_managed_content_v1",
        "download_url": (
            f"/api/autonomy/cases/{record.get('case_id')}/evidence/{evidence_id}/download"
            if evidence_id and not _pick(record, "removed_at", "deleted_at")
            else None
        ),
        "candidates": [public_evidence_candidate(item) for item in candidates],
        "receipt": public_evidence_receipt(receipt),
    }


def public_decision_event(record: Mapping[str, Any]) -> dict[str, Any]:
    payload = record.get("payload")
    if payload is None:
        payload = record.get("event_payload")
    return {
        "event_id": _safe_text(_pick(record, "id", "event_id"), limit=128),
        "event_sequence": int(
            _pick(record, "event_sequence", "sequence") or 0
        ),
        "case_id": _safe_text(record.get("case_id"), limit=128),
        "turn_id": _safe_text(record.get("turn_id"), limit=128),
        "event_type": _safe_text(record.get("event_type"), limit=100),
        "actor": _safe_text(_pick(record, "actor", "operator"), limit=300),
        "actor_kind": _safe_text(record.get("actor_kind"), limit=32),
        "operator_name": _safe_text(record.get("operator_name"), limit=300),
        "trace_id": _safe_text(record.get("trace_id"), limit=128),
        "occurred_at": _safe_text(
            _pick(record, "occurred_at", "created_at"), limit=64
        ),
        "payload": safe_public_value(deepcopy(payload or {})),
    }
