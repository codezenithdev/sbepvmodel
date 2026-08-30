"""Safe public projections for durable Autonomy records."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
import math
import re
from typing import Any

_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_SECRET_RE = re.compile(r"\b(?:sk|rk|sess)-(?:proj-)?[A-Za-z0-9_-]{10,}\b")
_NAMED_CREDENTIAL_RE = re.compile(
    r"(?i)\b(?:authorization|api[\s_-]?key|access[\s_-]?token|"
    r"refresh[\s_-]?token|client[\s_-]?secret|password|passwd|secret)\b"
    r"\s*[:=]\s*(?:bearer\s+)?[^\s,;]+"
)
_BEARER_RE = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}")
_CREDENTIAL_URI_RE = re.compile(
    r"(?i)\b(?:https?|postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis)://"
    r"[^\s/@:]+:[^\s/@]+@[^\s,;<>\"']+"
)
_WINDOWS_PATH_RE = re.compile(
    r"(?i)(?<![A-Za-z0-9])(?:[A-Z]:[\\/]|\\\\)[^\r\n,;<>\"']+"
)
_FILE_URI_RE = re.compile(r"(?i)\bfile://[^\r\n,;<>\"']+")
_SERVER_PATH_RE = re.compile(
    r"(?i)(?<![A-Za-z0-9])/(?:Users|home|tmp|var|srv|opt|private|root|etc|mnt|run)"
    r"(?:/[^\r\n,;<>\"']*)?"
)
_PRIVATE_PATH_VALUE_RE = re.compile(
    r"(?i)^(?:[A-Z]:[\\/]|\\\\|file://|"
    r"/(?:Users|home|tmp|var|srv|opt|private|root|etc|mnt|run)(?:/|$))"
)
_PRIVATE_KEY_PARTS = (
    "apikey",
    "authorization",
    "credential",
    "secret",
    "password",
    "passwd",
    "token",
    "cookie",
    "idempotencykey",
    "workerid",
    "storagekey",
    "storagepath",
    "sourcepath",
    "filesystem",
    "serverpath",
    "temppath",
    "localpath",
    "filepath",
    "traceback",
    "rawcontent",
    "rawtext",
)


def scrub_public_text(value: object, *, limit: int = 20_000) -> str | None:
    """Bound text and redact credential material and private server paths."""

    if value is None:
        return None
    text = _CONTROL_RE.sub("", str(value)).strip()
    if _PRIVATE_PATH_VALUE_RE.match(text):
        return "[redacted path]"
    text = _SECRET_RE.sub("[redacted secret]", text)
    text = _NAMED_CREDENTIAL_RE.sub("[redacted credential]", text)
    text = _BEARER_RE.sub("[redacted credential]", text)
    text = _CREDENTIAL_URI_RE.sub("[redacted credential URI]", text)
    text = _FILE_URI_RE.sub("[redacted path]", text)
    text = _WINDOWS_PATH_RE.sub("[redacted path]", text)
    text = _SERVER_PATH_RE.sub("[redacted path]", text)
    return text[:limit]


def _safe_text(value: object, *, limit: int = 20_000) -> str | None:
    return scrub_public_text(value, limit=limit)


def _normalized_public_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


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
            normalized = _normalized_public_key(key)
            if any(part in normalized for part in _PRIVATE_KEY_PARTS):
                continue
            result[key] = safe_public_value(item, depth=depth + 1)
        return result
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        return [safe_public_value(item, depth=depth + 1) for item in value[:1_000]]
    return _safe_text(value)


def exact_public_value(value: Any) -> Any:
    """Return a lossless public JSON projection without depth/list truncation.

    Decision comparison snapshots are hashed after this projection and must be
    returned byte-for-byte (under canonical JSON) by every later consumer.  The
    ordinary ``safe_public_value`` remains deliberately bounded for untrusted UI
    payloads; using it after a snapshot is hashed would silently truncate long CDF
    arrays or deep convergence provenance and invalidate the advertised digest.
    """

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
            normalized = _normalized_public_key(key)
            if any(part in normalized for part in _PRIVATE_KEY_PARTS):
                continue
            result[key] = exact_public_value(item)
        return result
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        return [exact_public_value(item) for item in value]
    return _safe_text(value)


def exact_public_comparison_bundle(value: Mapping[str, Any]) -> dict[str, Any]:
    """Project one full comparison bundle before its canonical hash is computed."""

    projected = exact_public_value(deepcopy(dict(value)))
    if not isinstance(projected, dict):  # pragma: no cover - mapping guarantees it
        raise ValueError("comparison bundle public projection must be an object")
    return projected


def _stored_public_comparison_bundle(value: Mapping[str, Any]) -> dict[str, Any]:
    """Fail closed if a stored hashed bundle would change during publication."""

    source = deepcopy(dict(value))
    projected = exact_public_comparison_bundle(source)
    if projected != source:
        raise ValueError(
            "stored comparison bundle is not the canonical public projection"
        )
    return source


def _stored_exact_public_value(value: Any, *, field: str) -> Any:
    """Return immutable public data unchanged, or reject a lossy projection."""

    source = deepcopy(value)
    projected = exact_public_value(source)
    if projected != source:
        raise ValueError(f"stored {field} is not the canonical public projection")
    return source


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


def public_decision_scenario(record: Mapping[str, Any]) -> dict[str, Any]:
    """Project one immutable scenario revision without private TEA source fields."""

    evidence_references: list[dict[str, Any]] = []
    raw_references = record.get("evidence_receipt_refs") or record.get(
        "evidence_references"
    ) or []
    if isinstance(raw_references, Sequence) and not isinstance(
        raw_references, (str, bytes, bytearray)
    ):
        for raw_reference in raw_references:
            if not isinstance(raw_reference, Mapping):
                continue
            receipt = raw_reference.get("receipt")
            evidence_references.append(
                {
                    "request_path": _safe_text(
                        raw_reference.get("request_path"), limit=500
                    ),
                    "receipt_id": _safe_text(
                        _pick(
                            raw_reference,
                            "evidence_receipt_id",
                            "receipt_id",
                        ),
                        limit=128,
                    ),
                    "receipt": public_evidence_receipt(
                        receipt if isinstance(receipt, Mapping) else None
                    ),
                }
            )

    validation = record.get("validation")
    jobs = record.get("jobs") or []
    tea_job_ids = record.get("tea_job_ids") or []
    if isinstance(jobs, Sequence) and not isinstance(jobs, (str, bytes, bytearray)):
        for job in jobs:
            if isinstance(job, Mapping) and job.get("id"):
                tea_job_ids = [*tea_job_ids, job.get("id")]
    canonical_job_ids: list[str] = []
    for job_id in tea_job_ids:
        safe_id = _safe_text(job_id, limit=128)
        if safe_id and safe_id not in canonical_job_ids:
            canonical_job_ids.append(safe_id)

    return {
        "scenario_id": _safe_text(
            _pick(record, "scenario_id", "id"), limit=128
        ),
        "scenario_revision_id": _safe_text(
            record.get("scenario_revision_id"), limit=128
        ),
        "case_id": _safe_text(record.get("case_id"), limit=128),
        "label": _safe_text(record.get("label"), limit=200),
        "kind": _safe_text(record.get("kind"), limit=32),
        "revision": int(record.get("revision") or 0),
        "parent_revision_id": _safe_text(
            record.get("parent_revision_id"), limit=128
        ),
        "superseded_by_revision_id": _safe_text(
            record.get("superseded_by_revision_id"), limit=128
        ),
        "draft_status": _safe_text(
            _pick(record, "draft_status", "status"), limit=32
        ),
        "request": safe_public_value(deepcopy(record.get("request") or {})),
        "request_sha256": _safe_text(record.get("request_sha256"), limit=64),
        "changed_fields": safe_public_value(record.get("changed_fields") or []),
        "comparison_classification": _safe_text(
            record.get("comparison_classification"), limit=32
        ),
        "structural_warning": (
            "This scenario changes request structure; baseline-relative causal "
            "attribution is limited."
            if record.get("comparison_classification") == "structural"
            else None
        ),
        "validation": safe_public_value(validation),
        "validation_sha256": _safe_text(
            record.get("validation_sha256"), limit=64
        ),
        "source_lock": {
            "source_annual_job_id": _safe_text(
                record.get("source_annual_job_id"), limit=128
            ),
            "source_snapshot_sha256": _safe_text(
                record.get("source_snapshot_sha256"), limit=64
            ),
            "analysis_basis": _safe_text(record.get("analysis_basis"), limit=64),
        },
        "evidence_references": evidence_references,
        "evidence_receipt_ids": [
            item["receipt_id"] for item in evidence_references if item["receipt_id"]
        ],
        "created_by": _safe_text(record.get("created_by"), limit=300),
        "updated_by": _safe_text(record.get("updated_by"), limit=300),
        "created_at": _safe_text(record.get("created_at"), limit=64),
        "updated_at": _safe_text(record.get("updated_at"), limit=64),
        "expires_at": _safe_text(record.get("expires_at"), limit=64),
        "validated_at": _safe_text(record.get("validated_at"), limit=64),
        "confirmed_at": _safe_text(record.get("confirmed_at"), limit=64),
        "expired_at": _safe_text(record.get("expired_at"), limit=64),
        "confirmation_id": _safe_text(record.get("confirmation_id"), limit=128),
        "tea_job_ids": canonical_job_ids,
        "linked_tea_job_id": _safe_text(
            record.get("linked_tea_job_id"), limit=128
        ),
        "latest_tea_job_id": _safe_text(
            _pick(record, "latest_tea_job_id", "linked_tea_job_id"), limit=128
        ),
    }


def public_scenario_confirmation(record: Mapping[str, Any]) -> dict[str, Any]:
    """Return the immutable named-human batch receipt and linked TEA identities."""

    raw_items = record.get("items") or []
    items: list[dict[str, Any]] = []
    if isinstance(raw_items, Sequence) and not isinstance(
        raw_items, (str, bytes, bytearray)
    ):
        for raw_item in raw_items:
            if not isinstance(raw_item, Mapping):
                continue
            items.append(
                {
                    "item_index": int(raw_item.get("item_index") or 0),
                    "scenario_id": _safe_text(
                        raw_item.get("scenario_id"), limit=128
                    ),
                    "scenario_revision_id": _safe_text(
                        raw_item.get("scenario_revision_id"), limit=128
                    ),
                    "revision": int(
                        _pick(raw_item, "scenario_revision", "revision") or 0
                    ),
                    "request_sha256": _safe_text(
                        raw_item.get("request_sha256"), limit=64
                    ),
                    "tea_job_id": _safe_text(
                        _pick(raw_item, "tea_job_id", "job_id"), limit=128
                    ),
                }
            )
    return {
        "confirmation_id": _safe_text(
            _pick(record, "confirmation_id", "id"), limit=128
        ),
        "case_id": _safe_text(record.get("case_id"), limit=128),
        "case_revision_before": int(
            _pick(record, "expected_case_revision", "case_revision_before") or 0
        ),
        "case_revision_after": int(record.get("case_revision_after") or 0),
        "operator_name": _safe_text(record.get("operator_name"), limit=300),
        "rationale": _safe_text(record.get("rationale"), limit=4_000),
        "acknowledgement": _safe_text(
            record.get("acknowledgement"), limit=4_000
        ),
        "confirmation_request_sha256": _safe_text(
            record.get("confirmation_request_sha256"), limit=64
        ),
        "receipt": safe_public_value(deepcopy(record.get("receipt") or {})),
        "receipt_sha256": _safe_text(record.get("receipt_sha256"), limit=64),
        "confirmed_at": _safe_text(record.get("confirmed_at"), limit=64),
        "items": items,
    }


def public_decision_comparison_bundle(
    record: Mapping[str, Any],
) -> dict[str, Any]:
    """Project one immutable comparison snapshot without durable private fields."""

    bundle = record.get("bundle")
    if not isinstance(bundle, Mapping):
        bundle = record.get("comparison_bundle")
    if not isinstance(bundle, Mapping):
        bundle = {}
    stale_reason = record.get("stale_reason")
    if stale_reason is None:
        stale_reason = record.get("stale_reason_json")
    return {
        "comparison_bundle_id": _safe_text(
            _pick(record, "comparison_bundle_id", "id"), limit=128
        ),
        "case_id": _safe_text(record.get("case_id"), limit=128),
        "source_confirmation_id": _safe_text(
            _pick(record, "source_confirmation_id", "confirmation_id"), limit=128
        ),
        "expected_case_revision": int(
            _pick(record, "expected_case_revision", "case_revision") or 0
        ),
        "case_revision_after": int(
            record.get("case_revision_after")
            or int(_pick(record, "expected_case_revision", "case_revision") or 0)
            + 1
        ),
        "schema_version": _safe_text(
            _pick(record, "bundle_schema_version", "schema_version"), limit=100
        ),
        "bundle_sha256": _safe_text(record.get("bundle_sha256"), limit=64),
        "is_complete": bool(record.get("is_complete")),
        "recommendation_eligible": bool(record.get("recommendation_eligible")),
        "bundle": _stored_public_comparison_bundle(bundle),
        "created_by": _safe_text(record.get("created_by"), limit=300),
        "created_at": _safe_text(record.get("created_at"), limit=64),
        "stale": bool(record.get("stale_at")),
        "stale_at": _safe_text(record.get("stale_at"), limit=64),
        "stale_reason": safe_public_value(deepcopy(stale_reason)),
        "superseded_by_bundle_id": _safe_text(
            record.get("superseded_by_bundle_id"), limit=128
        ),
        "superseded_at": _safe_text(record.get("superseded_at"), limit=64),
        "is_current": bool(record.get("is_current")),
    }


def public_decision_brief(record: Mapping[str, Any]) -> dict[str, Any]:
    """Project an immutable unsigned Decision Brief revision."""

    bundle = record.get("comparison_bundle")
    if not isinstance(bundle, Mapping):
        bundle = record.get("bundle")
    if not isinstance(bundle, Mapping):
        bundle = {}
    stale_reason = record.get("stale_reason")
    if stale_reason is None:
        stale_reason = record.get("stale_reason_json")
    recommendation_record = record.get("recommendation")
    recommendation = (
        public_decision_recommendation(recommendation_record)
        if isinstance(recommendation_record, Mapping)
        else None
    )
    signoff_record = record.get("signoff")
    signoff = (
        public_decision_signoff(signoff_record)
        if isinstance(signoff_record, Mapping)
        else None
    )
    return {
        "brief_id": _safe_text(record.get("brief_id"), limit=128),
        "brief_revision_id": _safe_text(
            _pick(record, "brief_revision_id", "id"), limit=128
        ),
        "revision": int(record.get("revision") or 0),
        "case_id": _safe_text(record.get("case_id"), limit=128),
        "parent_revision_id": _safe_text(
            record.get("parent_revision_id"), limit=128
        ),
        "superseded_by_revision_id": _safe_text(
            record.get("superseded_by_revision_id"), limit=128
        ),
        "source_confirmation_id": _safe_text(
            record.get("source_confirmation_id"), limit=128
        ),
        "comparison_bundle_id": _safe_text(
            record.get("comparison_bundle_id"), limit=128
        ),
        "comparison_bundle_sha256": _safe_text(
            _pick(
                record,
                "comparison_bundle_sha256",
                "bundle_sha256",
            ),
            limit=64,
        ),
        "comparison_bundle": _stored_public_comparison_bundle(bundle),
        "expected_case_revision": int(
            _pick(record, "expected_case_revision", "case_revision_before") or 0
        ),
        "case_revision_after": int(record.get("case_revision_after") or 0),
        "recommendation_classification": _safe_text(
            record.get("recommendation_classification"), limit=64
        ),
        "confidence_state": _safe_text(record.get("confidence_state"), limit=64),
        "caveats": _stored_exact_public_value(
            record.get("caveats") or [], field="Decision Brief caveats"
        ),
        "reversal_conditions": _stored_exact_public_value(
            record.get("reversal_conditions") or [],
            field="Decision Brief reversal conditions",
        ),
        "provenance": _stored_exact_public_value(
            record.get("provenance") or {}, field="Decision Brief provenance"
        ),
        "provenance_sha256": _safe_text(
            record.get("provenance_sha256"), limit=64
        ),
        "created_by": _safe_text(record.get("created_by"), limit=300),
        "created_at": _safe_text(record.get("created_at"), limit=64),
        "stale": bool(record.get("stale_at")),
        "stale_at": _safe_text(record.get("stale_at"), limit=64),
        "stale_reason": safe_public_value(deepcopy(stale_reason)),
        "superseded": bool(record.get("superseded_by_revision_id")),
        "superseded_at": _safe_text(record.get("superseded_at"), limit=64),
        "is_current": bool(record.get("is_current")),
        "recommendation": recommendation,
        "recommendation_id": (
            recommendation.get("recommendation_id") if recommendation else None
        ),
        "recommendation_contract_version": (
            recommendation.get("contract_version") if recommendation else None
        ),
        "recommendation_contract_digest": (
            recommendation.get("contract_digest") if recommendation else None
        ),
        "signoff": signoff,
        "signed": signoff is not None,
    }


def public_decision_recommendation(record: Mapping[str, Any]) -> dict[str, Any]:
    payload = record.get("recommendation")
    payload = payload if isinstance(payload, Mapping) else {}
    exact_payload = _stored_exact_public_value(
        payload, field="Decision Brief recommendation"
    )
    return {
        **exact_payload,
        "recommendation_id": _safe_text(
            _pick(record, "recommendation_id", "id"), limit=128
        ),
        "case_id": _safe_text(record.get("case_id"), limit=128),
        "brief_revision_id": _safe_text(
            record.get("brief_revision_id"), limit=128
        ),
        "comparison_bundle_id": _safe_text(
            record.get("comparison_bundle_id"), limit=128
        ),
        "comparison_bundle_sha256": _safe_text(
            record.get("comparison_bundle_sha256"), limit=64
        ),
        "classification": _safe_text(record.get("classification"), limit=64),
        "confidence": _safe_text(record.get("confidence"), limit=64),
        "contract_version": _safe_text(record.get("contract_version"), limit=100),
        "contract_digest": _safe_text(record.get("contract_digest"), limit=64),
        "recommendation_sha256": _safe_text(
            record.get("recommendation_sha256"), limit=64
        ),
        "required_acknowledgements": safe_public_value(
            payload.get("required_acknowledgements") or []
        ),
        "created_at": _safe_text(record.get("created_at"), limit=64),
    }


def public_decision_signoff(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "signoff_id": _safe_text(_pick(record, "signoff_id", "id"), limit=128),
        "case_id": _safe_text(record.get("case_id"), limit=128),
        "brief_revision_id": _safe_text(
            record.get("brief_revision_id"), limit=128
        ),
        "recommendation_id": _safe_text(
            record.get("recommendation_id"), limit=128
        ),
        "disposition": _safe_text(record.get("disposition"), limit=32),
        "decision_owner_name": _safe_text(
            record.get("decision_owner_name"), limit=200
        ),
        "authenticated_principal": _safe_text(
            record.get("authenticated_principal"), limit=200
        ),
        "rationale": _safe_text(record.get("rationale"), limit=4_000),
        "acknowledgement_text": _safe_text(
            record.get("acknowledgement_text"), limit=4_000
        ),
        "acknowledgement_version": _safe_text(
            record.get("acknowledgement_version"), limit=100
        ),
        "provisional_warnings": safe_public_value(
            record.get("provisional_warnings") or []
        ),
        "provisional_acknowledgements": safe_public_value(
            record.get("provisional_acknowledgements") or []
        ),
        "decision_snapshot_sha256": _safe_text(
            record.get("decision_snapshot_sha256"), limit=64
        ),
        "case_revision_before": int(
            _pick(record, "case_revision_before", "expected_case_revision") or 0
        ),
        "case_revision_after": int(record.get("case_revision_after") or 0),
        "signed_at": _safe_text(record.get("signed_at"), limit=64),
    }


def public_decision_report(record: Mapping[str, Any]) -> dict[str, Any]:
    report_id = _safe_text(_pick(record, "report_id", "id"), limit=128)
    case_id = _safe_text(record.get("case_id"), limit=128)
    return {
        "report_id": report_id,
        "case_id": case_id,
        "report_revision": int(record.get("report_revision") or 0),
        "report_kind": _safe_text(record.get("report_kind"), limit=32),
        "case_revision": int(record.get("case_revision") or 0),
        "brief_revision_id": _safe_text(
            record.get("brief_revision_id"), limit=128
        ),
        "signoff_id": _safe_text(record.get("signoff_id"), limit=128),
        "recommendation_contract_version": _safe_text(
            record.get("recommendation_contract_version"), limit=100
        ),
        "recommendation_contract_digest": _safe_text(
            record.get("recommendation_contract_digest"), limit=64
        ),
        "snapshot_sha256": _safe_text(record.get("snapshot_sha256"), limit=64),
        "pdf_sha256": _safe_text(record.get("pdf_sha256"), limit=64),
        "byte_count": int(record.get("byte_count") or 0),
        "page_count": int(record.get("page_count") or 0),
        "generation_contract_version": _safe_text(
            record.get("generation_contract_version"), limit=100
        ),
        "renderer_fingerprint": _safe_text(
            record.get("renderer_fingerprint"), limit=1_000
        ),
        "report_identity_sha256": _safe_text(
            record.get("report_identity_sha256"), limit=64
        ),
        "created_by": _safe_text(record.get("created_by"), limit=200),
        "created_at": _safe_text(record.get("created_at"), limit=64),
        "download_url": (
            f"/api/autonomy/cases/{case_id}/reports/{report_id}/download"
            if case_id and report_id
            else None
        ),
        "verify_url": (
            f"/api/autonomy/cases/{case_id}/reports/{report_id}/verify"
            if case_id and report_id
            else None
        ),
    }


def public_decision_shadow_review(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "shadow_review_id": _safe_text(
            _pick(record, "shadow_review_id", "id"), limit=128
        ),
        "case_id": _safe_text(record.get("case_id"), limit=128),
        "brief_revision_id": _safe_text(
            record.get("brief_revision_id"), limit=128
        ),
        "report_id": _safe_text(record.get("report_id"), limit=128),
        "report_snapshot_sha256": _safe_text(
            record.get("report_snapshot_sha256"), limit=64
        ),
        "pdf_sha256": _safe_text(record.get("pdf_sha256"), limit=64),
        "report_identity_sha256": _safe_text(
            record.get("report_identity_sha256"), limit=64
        ),
        "recommendation_contract_version": _safe_text(
            record.get("recommendation_contract_version"), limit=100
        ),
        "recommendation_contract_digest": _safe_text(
            record.get("recommendation_contract_digest"), limit=64
        ),
        "generation_contract_version": _safe_text(
            record.get("generation_contract_version"), limit=100
        ),
        "renderer_fingerprint": _safe_text(
            record.get("renderer_fingerprint"), limit=500
        ),
        "review_case_key": _safe_text(record.get("review_case_key"), limit=200),
        "checklist_version": _safe_text(
            record.get("checklist_version"), limit=100
        ),
        "reviewer_name": _safe_text(record.get("reviewer_name"), limit=200),
        "outcome": _safe_text(record.get("outcome"), limit=32),
        "review": safe_public_value(record.get("review") or {}),
        "review_sha256": _safe_text(record.get("review_sha256"), limit=64),
        "reviewed_at": _safe_text(record.get("reviewed_at"), limit=64),
    }
