"""Deterministic Autonomy scenario construction and TEA preparation.

This module deliberately owns no persistence and no execution authority.  It
normalizes the existing strict TEA request, compares immutable inputs, verifies
accepted evidence through injected durable-store/blob callbacks, and prepares
the exact bundle already consumed by the standalone TEA store and worker.

The Decision Agent may describe the returned validation objects, but must never
be given any function in this module as a mutation or queueing tool.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from decimal import Decimal
import hashlib
import hmac
import json
import re
from typing import Any

from pydantic import ValidationError

from sbepv.api import schemas as api_schemas
from sbepv.api import technoeconomic as technoeconomic_api


SCENARIO_VALIDATION_VERSION = "autonomy-scenario-validation-v1"
SCENARIO_COMPARISON_VERSION = "autonomy-scenario-comparison-v1"
STRUCTURAL_CAUSAL_WARNING = {
    "code": "structural_comparison_causal_attribution_limited",
    "message": (
        "This structural comparison changes request structure; baseline-relative "
        "differences cannot isolate a single causal effect."
    ),
    "acknowledgement_required": True,
}
CREATE_NEW_CASE_ALTERNATIVE = {
    "action": "create_new_case",
    "label": "Create a new decision case",
    "detail": (
        "A different Annual source or TEA analysis basis requires its own immutable "
        "case lock."
    ),
}
OPEN_EXPERT_TEA_ALTERNATIVE = {
    "action": "open_expert_tea_form",
    "label": "Open the expert TEA form",
    "detail": (
        "Use the existing standalone TEA workflow for a request structure that the "
        "guided scenario contract does not support."
    ),
}

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_JSON_POINTER_RE = re.compile(r"^/(?:[^~/]|~0|~1)+(?:/(?:[^~/]|~0|~1)+)*$")
_MISSING = object()
_STANDALONE_OMIT_IF_NONE = (
    "capacity_normalization",
    "commercial_scaling",
)
_STRUCTURAL_PATH_RE = re.compile(
    r"^(?:"
    r"/cost_stack_completeness$|"
    r"/capacity_normalization$|"
    r"/commercial_reference_design(?:/|$)|"
    r"/commercial_transfer(?:/|$)|"
    r"/commercial_scaling(?:/|$)|"
    r"/finance/treatment_key$|"
    r"/shared_degradation/degradation_model$|"
    r"/cost_lines/\d+/(?:"
    r"input_id|ownership|cost_type|coverage_include_ids|coverage_exclude_ids|"
    r"original_unit|normalized_unit|normalization_method|quantity_unit|"
    r"constant_dollar_cost_year"
    r")(?:/|$)|"
    r"/cost_lines/\d+/distribution/family$|"
    r"/cost_lines/\d+/currency_year_normalization/method$"
    r")"
)


class ScenarioContractError(ValueError):
    """A deterministic, API-safe scenario contract failure."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        field_errors: Sequence[Mapping[str, Any]] = (),
        violated_rules: Sequence[Mapping[str, Any]] = (),
        closest_supported_alternatives: Sequence[Mapping[str, Any]] = (),
    ) -> None:
        super().__init__(message)
        self.code = str(code)
        self.message = str(message)
        self.field_errors = [dict(item) for item in field_errors]
        self.violated_rules = [dict(item) for item in violated_rules]
        self.closest_supported_alternatives = [
            dict(item) for item in closest_supported_alternatives
        ]

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "field_errors": deepcopy(self.field_errors),
            "violated_rules": deepcopy(self.violated_rules),
            "closest_supported_alternatives": deepcopy(
                self.closest_supported_alternatives
            ),
        }


def _escape_pointer_token(value: object) -> str:
    return str(value).replace("~", "~0").replace("/", "~1")


def _pointer_from_location(location: Sequence[object]) -> str:
    useful = [item for item in location if not str(item).startswith("tagged-union[")]
    if not useful:
        return "/request"
    return "/" + "/".join(_escape_pointer_token(item) for item in useful)


def _schema_error(exc: ValidationError) -> ScenarioContractError:
    field_errors: list[dict[str, Any]] = []
    contains_unsupported = False
    for item in exc.errors(include_url=False, include_context=False):
        unsupported = item.get("type") == "extra_forbidden"
        contains_unsupported = contains_unsupported or unsupported
        field_errors.append(
            {
                "path": _pointer_from_location(item.get("loc", ())),
                "code": "unsupported_field" if unsupported else "invalid_tea_field",
                "message": str(item.get("msg") or "Invalid TEA request field."),
            }
        )
    field_errors.sort(key=lambda item: (item["path"], item["code"], item["message"]))
    alternatives: list[dict[str, Any]] = []
    if contains_unsupported:
        alternatives.append(deepcopy(OPEN_EXPERT_TEA_ALTERNATIVE))
    alternatives.append(
        {
            "action": "correct_request_fields",
            "label": "Correct the highlighted TEA inputs",
            "detail": "Submit only values accepted by the strict standalone TEA schema.",
        }
    )
    return ScenarioContractError(
        "scenario_request_invalid",
        "The scenario request does not satisfy the standalone TEA request schema.",
        field_errors=field_errors,
        violated_rules=(
            {
                "code": "tea.request.strict_schema",
                "message": (
                    "Scenario requests must validate against the strict standalone "
                    "TEA submission schema."
                ),
            },
        ),
        closest_supported_alternatives=alternatives,
    )


def normalize_submission_request(
    payload: Mapping[str, Any],
    *,
    baseline_request: Mapping[str, Any] | None = None,
    kind: str = "baseline",
) -> tuple[dict[str, Any], str]:
    """Return the canonical standalone TEA request and its SHA-256.

    Alternatives inherit ``n`` and ``seed`` from the current baseline only when
    those fields are omitted.  The output uses the standalone POST route's exact
    historical omission rules: null ``capacity_normalization`` and
    ``commercial_scaling`` are omitted; other schema-defaulted nulls remain.
    """

    if kind not in {"baseline", "alternative"}:
        raise ScenarioContractError(
            "scenario_kind_invalid",
            "Scenario kind must be baseline or alternative.",
            field_errors=(
                {
                    "path": "/kind",
                    "code": "unsupported_value",
                    "message": "Use 'baseline' or 'alternative'.",
                },
            ),
            violated_rules=(
                {
                    "code": "scenario.kind",
                    "message": "A decision scenario has exactly one supported kind.",
                },
            ),
        )
    if not isinstance(payload, Mapping):
        raise ScenarioContractError(
            "scenario_request_invalid",
            "The scenario request must be a JSON object.",
            field_errors=(
                {
                    "path": "/request",
                    "code": "invalid_type",
                    "message": "Expected a JSON object.",
                },
            ),
        )

    candidate = deepcopy(dict(payload))
    if kind == "alternative" and baseline_request is not None:
        for field in ("n", "seed"):
            if field not in candidate and field in baseline_request:
                candidate[field] = deepcopy(baseline_request[field])
    try:
        parsed = api_schemas.TechnoeconomicSubmissionRequest.model_validate(candidate)
    except ValidationError as exc:
        raise _schema_error(exc) from exc

    canonical = parsed.model_dump(mode="json", exclude_none=False)
    for field in _STANDALONE_OMIT_IF_NONE:
        if getattr(parsed, field) is None:
            canonical.pop(field, None)
    canonical_text = technoeconomic_api.canonical_json_text(canonical)
    canonical_hash = hashlib.sha256(canonical_text.encode("utf-8")).hexdigest()
    return canonical, canonical_hash


def _json_equal(left: Any, right: Any) -> bool:
    try:
        return technoeconomic_api.canonical_json_text(left) == (
            technoeconomic_api.canonical_json_text(right)
        )
    except (TypeError, ValueError):
        return type(left) is type(right) and left == right


def json_pointer_leaf_diff(
    baseline: Any,
    scenario: Any,
) -> list[dict[str, Any]]:
    """Return an ordered, lossless JSON-pointer leaf diff.

    Presence flags distinguish a missing member from an explicit JSON null.  An
    added/removed empty object or array is represented at that container path so
    structural changes can never disappear from the review.
    """

    rows: list[dict[str, Any]] = []

    def add_row(path: str, left: Any, right: Any) -> None:
        rows.append(
            {
                "path": path or "/",
                "baseline_present": left is not _MISSING,
                "baseline_value": None if left is _MISSING else deepcopy(left),
                "scenario_present": right is not _MISSING,
                "scenario_value": None if right is _MISSING else deepcopy(right),
            }
        )

    def walk(left: Any, right: Any, path: str) -> None:
        if left is not _MISSING and right is not _MISSING and _json_equal(left, right):
            return
        if (
            left is not _MISSING
            and right is not _MISSING
            and isinstance(left, Mapping)
            and isinstance(right, Mapping)
        ):
            keys = sorted(set(left) | set(right), key=str)
            if not keys:
                add_row(path, left, right)
                return
            for key in keys:
                child = f"{path}/{_escape_pointer_token(key)}"
                walk(left.get(key, _MISSING), right.get(key, _MISSING), child)
            return
        if (
            left is not _MISSING
            and right is not _MISSING
            and isinstance(left, list)
            and isinstance(right, list)
        ):
            if not left and not right:
                add_row(path, left, right)
                return
            for index in range(max(len(left), len(right))):
                child = f"{path}/{index}"
                walk(
                    left[index] if index < len(left) else _MISSING,
                    right[index] if index < len(right) else _MISSING,
                    child,
                )
            return
        if left is _MISSING and isinstance(right, Mapping) and right:
            for key in sorted(right, key=str):
                walk(_MISSING, right[key], f"{path}/{_escape_pointer_token(key)}")
            return
        if right is _MISSING and isinstance(left, Mapping) and left:
            for key in sorted(left, key=str):
                walk(left[key], _MISSING, f"{path}/{_escape_pointer_token(key)}")
            return
        if left is _MISSING and isinstance(right, list) and right:
            for index, value in enumerate(right):
                walk(_MISSING, value, f"{path}/{index}")
            return
        if right is _MISSING and isinstance(left, list) and left:
            for index, value in enumerate(left):
                walk(value, _MISSING, f"{path}/{index}")
            return
        add_row(path, left, right)

    walk(baseline, scenario, "")
    rows.sort(key=lambda item: item["path"])
    return rows


def _shape_changed(left: Any, right: Any) -> bool:
    if isinstance(left, Mapping) and isinstance(right, Mapping):
        if set(left) != set(right):
            return True
        return any(_shape_changed(left[key], right[key]) for key in left)
    if isinstance(left, list) and isinstance(right, list):
        if len(left) != len(right):
            return True
        return any(_shape_changed(a, b) for a, b in zip(left, right, strict=True))
    return isinstance(left, (Mapping, list)) != isinstance(right, (Mapping, list))


def classify_comparison(
    baseline: Mapping[str, Any],
    scenario: Mapping[str, Any],
    differences: Sequence[Mapping[str, Any]] | None = None,
) -> str:
    """Classify a baseline-relative request as controlled or structural."""

    rows = list(differences or json_pointer_leaf_diff(baseline, scenario))
    if _shape_changed(baseline, scenario):
        return "structural"
    if any(_STRUCTURAL_PATH_RE.match(str(item.get("path") or "")) for item in rows):
        return "structural"
    return "controlled"


def _append_unique(items: list[dict[str, Any]], item: Mapping[str, Any]) -> None:
    candidate = dict(item)
    if candidate not in items:
        items.append(candidate)


def _pointer_value(payload: Any, pointer: str) -> Any:
    if not _JSON_POINTER_RE.fullmatch(pointer):
        raise KeyError(pointer)
    current = payload
    for encoded in pointer[1:].split("/"):
        token = encoded.replace("~1", "/").replace("~0", "~")
        if isinstance(current, Mapping):
            if token not in current:
                raise KeyError(pointer)
            current = current[token]
        elif isinstance(current, list):
            if not token.isdigit() or int(token) >= len(current):
                raise KeyError(pointer)
            current = current[int(token)]
        else:
            raise KeyError(pointer)
    return current


def _json_values_equal(left: Any, right: Any) -> bool:
    """Compare JSON values while treating equivalent finite numerics alike."""

    if isinstance(left, bool) or isinstance(right, bool):
        return isinstance(left, bool) and isinstance(right, bool) and left == right
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return Decimal(str(left)) == Decimal(str(right))
    if isinstance(left, Mapping) and isinstance(right, Mapping):
        return set(left) == set(right) and all(
            _json_values_equal(left[key], right[key]) for key in left
        )
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(
            _json_values_equal(a, b) for a, b in zip(left, right, strict=True)
        )
    return type(left) is type(right) and left == right


def verify_accepted_evidence_references(
    *,
    case_id: str,
    request_payload: Mapping[str, Any],
    evidence_references: Sequence[Mapping[str, Any]],
    receipt_loader: Callable[[str], Mapping[str, Any] | None] | None,
    evidence_snapshot_loader: (
        Callable[[str, str], tuple[bytes, Mapping[str, Any]]] | None
    ),
) -> dict[str, Any]:
    """Verify receipt canonical hashes and server-managed evidence bytes.

    ``receipt_loader`` must return the durable receipt row/public domain object,
    including its parsed ``receipt`` payload and ``receipt_sha256``.
    ``evidence_snapshot_loader`` must return immutable bytes plus the durable asset
    metadata for ``(case_id, evidence_asset_id)``.  The existing
    :func:`sbepv.autonomy.evidence.verified_evidence_snapshot` has this shape.
    """

    errors: list[dict[str, Any]] = []
    verified: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    for raw_reference in evidence_references:
        reference = dict(raw_reference)
        path = str(reference.get("request_path") or "")
        receipt_id = str(
            reference.get("receipt_id")
            or reference.get("evidence_receipt_id")
            or ""
        )
        if path in seen_paths:
            errors.append(
                {
                    "path": path or "/evidence_references",
                    "code": "duplicate_evidence_reference",
                    "message": (
                        "Each request path may reference exactly one accepted-evidence "
                        "receipt."
                    ),
                }
            )
            continue
        seen_paths.add(path)
        try:
            request_value = _pointer_value(request_payload, path)
        except KeyError:
            errors.append(
                {
                    "path": path or "/evidence_references",
                    "code": "evidence_request_path_missing",
                    "message": "The evidence reference does not identify a request value.",
                }
            )
            continue
        if receipt_loader is None or evidence_snapshot_loader is None:
            errors.append(
                {
                    "path": path,
                    "code": "evidence_verifier_unavailable",
                    "message": (
                        "Accepted evidence must be verified from durable receipts and "
                        "server-managed content before the scenario is runnable."
                    ),
                }
            )
            continue
        try:
            receipt_row = receipt_loader(receipt_id)
        except Exception:
            receipt_row = None
        if not isinstance(receipt_row, Mapping):
            errors.append(
                {
                    "path": path,
                    "code": "evidence_receipt_not_found",
                    "message": "The referenced accepted-evidence receipt was not found.",
                }
            )
            continue
        receipt_payload = receipt_row.get("receipt")
        if receipt_payload is None and isinstance(receipt_row.get("receipt_json"), str):
            try:
                receipt_payload = json.loads(str(receipt_row["receipt_json"]))
            except (TypeError, ValueError):
                receipt_payload = None
        if not isinstance(receipt_payload, Mapping):
            errors.append(
                {
                    "path": path,
                    "code": "evidence_receipt_invalid",
                    "message": "The durable evidence receipt payload is invalid.",
                }
            )
            continue
        stored_receipt_id = str(
            receipt_row.get("id")
            or receipt_row.get("evidence_receipt_id")
            or ""
        )
        payload_receipt_id = str(receipt_payload.get("evidence_receipt_id") or "")
        stored_digest = str(receipt_row.get("receipt_sha256") or "")
        actual_digest = technoeconomic_api.canonical_json_sha256(receipt_payload)
        row_case_id = str(receipt_row.get("case_id") or "")
        payload_case_id = str(receipt_payload.get("case_id") or "")
        row_decision = str(receipt_row.get("decision") or "")
        payload_decision = str(receipt_payload.get("decision") or "")
        row_preservation_mode = str(receipt_row.get("preservation_mode") or "")
        payload_preservation_mode = str(
            receipt_payload.get("preservation_mode") or ""
        )
        if (
            stored_receipt_id != receipt_id
            or payload_receipt_id != receipt_id
            or row_case_id != payload_case_id
            or row_decision != payload_decision
            or row_preservation_mode != payload_preservation_mode
        ):
            errors.append(
                {
                    "path": path,
                    "code": "evidence_receipt_snapshot_mismatch",
                    "message": (
                        "The durable evidence receipt row does not match its "
                        "canonical receipt snapshot."
                    ),
                }
            )
            continue
        if not _SHA256_RE.fullmatch(stored_digest) or not hmac.compare_digest(
            stored_digest, actual_digest
        ):
            errors.append(
                {
                    "path": path,
                    "code": "evidence_receipt_digest_mismatch",
                    "message": "The evidence receipt does not match its canonical SHA-256.",
                }
            )
            continue
        if row_case_id != str(case_id):
            errors.append(
                {
                    "path": path,
                    "code": "cross_case_evidence_receipt",
                    "message": "Evidence receipts must belong to the same decision case.",
                }
            )
            continue
        if row_decision != "accepted":
            errors.append(
                {
                    "path": path,
                    "code": "evidence_receipt_not_accepted",
                    "message": "Only explicitly accepted evidence receipts are runnable.",
                }
            )
            continue
        if row_preservation_mode != "server_managed_content_v1":
            errors.append(
                {
                    "path": path,
                    "code": "evidence_content_not_server_managed",
                    "message": "Runnable evidence must use server-managed preserved content.",
                }
            )
            continue
        candidate = receipt_payload.get("candidate")
        if not isinstance(candidate, Mapping) or "value" not in candidate:
            errors.append(
                {
                    "path": path,
                    "code": "evidence_receipt_invalid",
                    "message": "The receipt is missing its accepted candidate value.",
                }
            )
            continue
        row_value = receipt_row.get("value")
        row_field_name = str(receipt_row.get("field_name") or "")
        row_unit = receipt_row.get("unit")
        if (
            (row_value is not None and not _json_values_equal(row_value, candidate["value"]))
            or (row_field_name and row_field_name != str(candidate.get("field_name") or ""))
            or (row_unit is not None and row_unit != candidate.get("unit"))
        ):
            errors.append(
                {
                    "path": path,
                    "code": "evidence_receipt_snapshot_mismatch",
                    "message": (
                        "The durable evidence row does not match its accepted "
                        "candidate snapshot."
                    ),
                }
            )
            continue
        if not _json_values_equal(request_value, candidate["value"]):
            errors.append(
                {
                    "path": path,
                    "code": "evidence_candidate_value_mismatch",
                    "message": (
                        "The runnable request value does not match the explicitly "
                        "accepted evidence candidate."
                    ),
                }
            )
            continue
        row_asset_id = str(receipt_row.get("evidence_asset_id") or "")
        payload_asset_id = str(receipt_payload.get("evidence_asset_id") or "")
        asset_id = row_asset_id
        content = receipt_payload.get("content")
        if (
            not asset_id
            or asset_id != payload_asset_id
            or not isinstance(content, Mapping)
        ):
            errors.append(
                {
                    "path": path,
                    "code": "evidence_receipt_invalid",
                    "message": "The receipt is missing its preserved-content identity.",
                }
            )
            continue
        expected_sha = str(content.get("sha256") or "")
        expected_bytes = content.get("byte_count")
        row_asset_sha = receipt_row.get("asset_sha256")
        row_asset_bytes = receipt_row.get("asset_byte_count")
        if (
            (row_asset_sha is not None and str(row_asset_sha) != expected_sha)
            or (row_asset_bytes is not None and row_asset_bytes != expected_bytes)
        ):
            errors.append(
                {
                    "path": path,
                    "code": "evidence_receipt_snapshot_mismatch",
                    "message": (
                        "The durable evidence receipt row does not match its "
                        "canonical receipt snapshot."
                    ),
                }
            )
            continue
        try:
            snapshot_bytes, asset = evidence_snapshot_loader(str(case_id), asset_id)
        except Exception:
            errors.append(
                {
                    "path": path,
                    "code": "evidence_content_verification_failed",
                    "message": "The server-managed evidence bytes could not be verified.",
                }
            )
            continue
        actual_sha = hashlib.sha256(bytes(snapshot_bytes)).hexdigest()
        asset_sha = str(asset.get("sha256") or "")
        asset_bytes = asset.get("byte_count")
        asset_case = str(asset.get("case_id") or case_id)
        returned_asset_id = str(
            asset.get("id") or asset.get("evidence_asset_id") or ""
        )
        expected_media_type = str(content.get("media_type") or "")
        actual_media_type = str(
            asset.get("detected_media_type") or asset.get("media_type") or ""
        )
        if (
            not _SHA256_RE.fullmatch(expected_sha)
            or expected_sha != actual_sha
            or asset_sha != expected_sha
            or expected_bytes != len(snapshot_bytes)
            or asset_bytes != expected_bytes
            or asset_case != str(case_id)
            or returned_asset_id != asset_id
            or actual_media_type != expected_media_type
            or asset.get("removed_at") is not None
        ):
            errors.append(
                {
                    "path": path,
                    "code": "evidence_content_digest_mismatch",
                    "message": "The preserved evidence bytes do not match the accepted receipt.",
                }
            )
            continue
        verified.append(
            {
                "request_path": path,
                "evidence_receipt_id": receipt_id,
                "receipt_sha256": stored_digest,
                "evidence_asset_id": asset_id,
                "content_sha256": expected_sha,
                "content_bytes": int(expected_bytes),
                "evidence_class": str(
                    receipt_row.get("evidence_class")
                    or receipt_payload.get("evidence_class")
                    or ""
                ),
                "candidate_field": str(candidate.get("field_name") or ""),
                "candidate_value": deepcopy(candidate["value"]),
                "candidate_unit": candidate.get("unit"),
                "preservation_mode": row_preservation_mode,
            }
        )
    errors.sort(key=lambda item: (item["path"], item["code"], item["message"]))
    verified.sort(
        key=lambda item: (item["request_path"], item["evidence_receipt_id"])
    )
    return {"valid": not errors, "field_errors": errors, "receipts": verified}


def _case_lock_errors(case_record: Mapping[str, Any]) -> list[dict[str, Any]]:
    source_id = str(case_record.get("source_annual_job_id") or "")
    source_hash = str(case_record.get("source_snapshot_sha256") or "")
    basis = str(case_record.get("analysis_basis") or "")
    if (
        source_id
        and _SHA256_RE.fullmatch(source_hash)
        and basis in {"solartac_site", "commercial_representative"}
    ):
        return []
    return [
        {
            "path": "/case/basis_lock",
            "code": "case_source_basis_not_locked",
            "message": (
                "Lock one eligible Annual source and TEA analysis basis before "
                "creating runnable scenarios."
            ),
        }
    ]


def validate_scenario_draft(
    *,
    case_record: Mapping[str, Any],
    kind: str,
    request_payload: Mapping[str, Any],
    baseline_request: Mapping[str, Any] | None = None,
    declared_changed_fields: Sequence[str] = (),
    evidence_references: Sequence[Mapping[str, Any]] = (),
    receipt_loader: Callable[[str], Mapping[str, Any] | None] | None = None,
    evidence_snapshot_loader: (
        Callable[[str, str], tuple[bytes, Mapping[str, Any]]] | None
    ) = None,
) -> dict[str, Any]:
    """Validate one draft without mutating durable state or running TEA."""

    errors: list[dict[str, Any]] = []
    rules: list[dict[str, Any]] = []
    alternatives: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    canonical: dict[str, Any] | None = None
    request_hash: str | None = None
    baseline_canonical: dict[str, Any] | None = None
    baseline_request_sha256: str | None = None

    if kind == "alternative" and baseline_request is None:
        errors.append(
            {
                "path": "/baseline",
                "code": "baseline_required",
                "message": "An alternative must compare against the current baseline.",
            }
        )
        _append_unique(
            rules,
            {
                "code": "scenario.one_current_baseline",
                "message": "A case must have one current baseline before alternatives.",
            },
        )
        _append_unique(
            alternatives,
            {
                "action": "create_baseline",
                "label": "Create the baseline scenario",
                "detail": "Validate the case baseline before adding alternatives.",
            },
        )
    if baseline_request is not None:
        try:
            baseline_canonical, _ = normalize_submission_request(
                baseline_request, kind="baseline"
            )
            baseline_request_sha256 = technoeconomic_api.canonical_json_sha256(
                baseline_canonical
            )
        except ScenarioContractError as exc:
            errors.extend(
                {
                    **item,
                    "path": f"/baseline{item['path']}",
                }
                for item in exc.field_errors
            )
            for item in exc.violated_rules:
                _append_unique(rules, item)
            for item in exc.closest_supported_alternatives:
                _append_unique(alternatives, item)
    try:
        canonical, request_hash = normalize_submission_request(
            request_payload,
            baseline_request=baseline_canonical,
            kind=kind,
        )
    except ScenarioContractError as exc:
        errors.extend(exc.field_errors)
        for item in exc.violated_rules:
            _append_unique(rules, item)
        for item in exc.closest_supported_alternatives:
            _append_unique(alternatives, item)

    lock_errors = _case_lock_errors(case_record)
    if lock_errors:
        errors.extend(lock_errors)
        _append_unique(
            rules,
            {
                "code": "scenario.case_lock_required",
                "message": "Every scenario is bound to one immutable case source and basis.",
            },
        )
        _append_unique(
            alternatives,
            {
                "action": "lock_case_source_basis",
                "label": "Lock an eligible source and basis",
                "detail": "Complete the case basis lock before validating scenarios.",
            },
        )

    differences: list[dict[str, Any]] = []
    classification = "baseline" if kind == "baseline" else "controlled"
    if canonical is not None and not lock_errors:
        locked_source = str(case_record["source_annual_job_id"])
        locked_basis = str(case_record["analysis_basis"])
        if canonical["source_annual_job_id"] != locked_source:
            errors.append(
                {
                    "path": "/source_annual_job_id",
                    "code": "cross_source_comparison",
                    "message": (
                        "The scenario Annual source does not match the immutable case lock."
                    ),
                }
            )
            _append_unique(
                rules,
                {
                    "code": "scenario.same_annual_source",
                    "message": "All scenarios in a case must share one Annual source.",
                },
            )
            _append_unique(alternatives, CREATE_NEW_CASE_ALTERNATIVE)
        if canonical["basis"] != locked_basis:
            errors.append(
                {
                    "path": "/basis",
                    "code": "cross_basis_comparison",
                    "message": (
                        "The scenario TEA analysis basis does not match the immutable case lock."
                    ),
                }
            )
            _append_unique(
                rules,
                {
                    "code": "scenario.same_analysis_basis",
                    "message": "All scenarios in a case must share one TEA analysis basis.",
                },
            )
            _append_unique(alternatives, CREATE_NEW_CASE_ALTERNATIVE)
        if (
            canonical["basis"] == "solartac_site"
            and canonical.get("capacity_normalization")
            != api_schemas.ANNUAL_APPLIED_CAPACITY_NORMALIZATION
        ):
            errors.append(
                {
                    "path": "/capacity_normalization",
                    "code": "unsupported_new_solartac_normalization",
                    "message": (
                        "New SolarTAC scenarios must use annual_applied_capacity_v1."
                    ),
                }
            )
            _append_unique(
                rules,
                {
                    "code": "tea.new_solartac.applied_capacity_v1",
                    "message": (
                        "New SolarTAC jobs must declare "
                        "capacity_normalization='annual_applied_capacity_v1'."
                    ),
                },
            )
            _append_unique(
                alternatives,
                {
                    "action": "use_annual_applied_capacity_v1",
                    "label": "Use the supported applied-capacity basis",
                    "detail": (
                        "Set capacity_normalization to annual_applied_capacity_v1 "
                        "and use the matching cost units and normalization methods."
                    ),
                },
            )

        if kind == "alternative" and baseline_canonical is not None:
            for field in ("n", "seed"):
                if canonical[field] != baseline_canonical[field]:
                    errors.append(
                        {
                            "path": f"/{field}",
                            "code": f"{field}_must_match_baseline",
                            "message": (
                                f"Alternative {field} must match the current baseline "
                                f"value {baseline_canonical[field]}."
                            ),
                        }
                    )
                    _append_unique(
                        rules,
                        {
                            "code": "scenario.same_realizations_and_seed",
                            "message": (
                                "Scenarios in one case use the same realization count "
                                "and seed."
                            ),
                        },
                    )
                    _append_unique(
                        alternatives,
                        {
                            "action": f"use_baseline_{field}",
                            "label": f"Use baseline {field}",
                            "detail": f"Set {field} to {baseline_canonical[field]}.",
                            "value": baseline_canonical[field],
                        },
                    )
            differences = json_pointer_leaf_diff(baseline_canonical, canonical)
            classification = classify_comparison(
                baseline_canonical, canonical, differences
            )
            if classification == "structural":
                warnings.append(deepcopy(STRUCTURAL_CAUSAL_WARNING))

    declarations = [str(item) for item in declared_changed_fields]
    declaration_set = set(declarations)
    if len(declaration_set) != len(declarations):
        errors.append(
            {
                "path": "/changed_fields",
                "code": "duplicate_changed_field",
                "message": "Changed-field declarations must be unique.",
            }
        )
    for pointer in sorted(declaration_set):
        if not _JSON_POINTER_RE.fullmatch(pointer):
            errors.append(
                {
                    "path": "/changed_fields",
                    "code": "invalid_json_pointer",
                    "message": f"{pointer!r} is not a supported JSON pointer.",
                }
            )
    actual_paths = {str(item["path"]) for item in differences}
    for pointer in sorted(actual_paths - declaration_set):
        errors.append(
            {
                "path": pointer,
                "code": "undeclared_change",
                "message": "This baseline-relative input change was not declared.",
            }
        )
    for pointer in sorted(declaration_set - actual_paths):
        errors.append(
            {
                "path": pointer,
                "code": "declared_field_unchanged",
                "message": "This declared field does not differ from the baseline.",
            }
        )
    if actual_paths != declaration_set:
        _append_unique(
            rules,
            {
                "code": "scenario.changed_fields_exact",
                "message": (
                    "The changed-field declaration must exactly equal the "
                    "baseline-relative leaf differences."
                ),
            },
        )
        _append_unique(
            alternatives,
            {
                "action": "use_exact_changed_fields",
                "label": "Use the exact detected change list",
                "detail": "Replace changed_fields with the server-detected JSON pointers.",
                "changed_fields": sorted(actual_paths),
            },
        )

    evidence_result = {"valid": True, "field_errors": [], "receipts": []}
    if canonical is not None:
        evidence_result = verify_accepted_evidence_references(
            case_id=str(case_record.get("case_id") or case_record.get("id") or ""),
            request_payload=canonical,
            evidence_references=evidence_references,
            receipt_loader=receipt_loader,
            evidence_snapshot_loader=evidence_snapshot_loader,
        )
        if not evidence_result["valid"]:
            errors.extend(evidence_result["field_errors"])
            _append_unique(
                rules,
                {
                    "code": "scenario.accepted_evidence_verified",
                    "message": (
                        "Every referenced receipt must be accepted, canonically "
                        "intact, same-case, and backed by verified server-managed bytes."
                    ),
                },
            )
            _append_unique(
                alternatives,
                {
                    "action": "review_or_replace_evidence",
                    "label": "Review or replace the evidence reference",
                    "detail": (
                        "Use an accepted same-case receipt whose preserved content "
                        "still verifies."
                    ),
                },
            )

    errors.sort(key=lambda item: (item["path"], item["code"], item["message"]))
    return {
        "validation_version": SCENARIO_VALIDATION_VERSION,
        "valid": not errors,
        "request": deepcopy(canonical),
        "request_sha256": request_hash,
        "baseline_request_sha256": baseline_request_sha256,
        "kind": kind,
        "comparison_classification": classification,
        "changed_fields": sorted(actual_paths),
        "declared_changed_fields": sorted(declaration_set),
        "differences": differences,
        "warnings": warnings,
        "evidence_receipts": evidence_result["receipts"],
        "field_errors": errors,
        "violated_rules": rules,
        "closest_supported_alternatives": alternatives,
        "pre_run_value_semantics": "inputs_or_hypotheses_not_outcomes",
    }


def prepare_technoeconomic_bundle(
    *,
    agent_store: Any,
    case_record: Mapping[str, Any],
    request_payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Build the exact standalone TEA submission bundle without enqueueing it.

    The returned request, source fields, kernel request, and provenance contain no
    Autonomy keys.  A caller may pass them directly to the transactional grouped
    insertion method while holding the existing global orchestration lock.
    """

    lock_errors = _case_lock_errors(case_record)
    if lock_errors:
        raise ScenarioContractError(
            "case_source_basis_not_locked",
            lock_errors[0]["message"],
            field_errors=lock_errors,
        )
    canonical, request_hash = normalize_submission_request(request_payload)
    if canonical["source_annual_job_id"] != str(case_record["source_annual_job_id"]):
        raise ScenarioContractError(
            "cross_source_comparison",
            "The scenario Annual source does not match the immutable case lock.",
            field_errors=(
                {
                    "path": "/source_annual_job_id",
                    "code": "cross_source_comparison",
                    "message": (
                        "The scenario Annual source does not match the immutable case lock."
                    ),
                },
            ),
            violated_rules=(
                {
                    "code": "scenario.same_annual_source",
                    "message": "All scenarios in a case must share one Annual source.",
                },
            ),
            closest_supported_alternatives=(CREATE_NEW_CASE_ALTERNATIVE,),
        )
    if canonical["basis"] != str(case_record["analysis_basis"]):
        raise ScenarioContractError(
            "cross_basis_comparison",
            "The scenario TEA analysis basis does not match the immutable case lock.",
            field_errors=(
                {
                    "path": "/basis",
                    "code": "cross_basis_comparison",
                    "message": (
                        "The scenario TEA analysis basis does not match the immutable case lock."
                    ),
                },
            ),
            violated_rules=(
                {
                    "code": "scenario.same_analysis_basis",
                    "message": "All scenarios in a case must share one TEA analysis basis.",
                },
            ),
            closest_supported_alternatives=(CREATE_NEW_CASE_ALTERNATIVE,),
        )
    if (
        canonical["basis"] == "solartac_site"
        and canonical.get("capacity_normalization")
        != api_schemas.ANNUAL_APPLIED_CAPACITY_NORMALIZATION
    ):
        raise ScenarioContractError(
            "unsupported_new_solartac_normalization",
            "New SolarTAC scenarios must use annual_applied_capacity_v1.",
            field_errors=(
                {
                    "path": "/capacity_normalization",
                    "code": "unsupported_new_solartac_normalization",
                    "message": (
                        "New SolarTAC scenarios must use annual_applied_capacity_v1."
                    ),
                },
            ),
        )

    dependencies = technoeconomic_api.resolve_annual_source_dependencies(
        agent_store,
        canonical["source_annual_job_id"],
    )
    snapshot_envelope = technoeconomic_api.build_annual_source_snapshot(
        dependencies["annual_job"],
        origin_validation_job=dependencies["origin_validation_job"],
        promotion_record=dependencies["promotion_record"],
    )
    if snapshot_envelope["source_snapshot_sha256"] != str(
        case_record["source_snapshot_sha256"]
    ):
        raise ScenarioContractError(
            "case_source_snapshot_mismatch",
            "The reverified Annual source snapshot no longer matches the case lock.",
            field_errors=(
                {
                    "path": "/case/source_snapshot_sha256",
                    "code": "case_source_snapshot_mismatch",
                    "message": (
                        "The reverified Annual source snapshot no longer matches the case lock."
                    ),
                },
            ),
            violated_rules=(
                {
                    "code": "scenario.frozen_source_snapshot",
                    "message": (
                        "Execution must use the exact Annual snapshot frozen into the case."
                    ),
                },
            ),
            closest_supported_alternatives=(CREATE_NEW_CASE_ALTERNATIVE,),
        )
    kernel_request = technoeconomic_api.build_technoeconomic_kernel_request(
        canonical,
        snapshot_envelope["source_snapshot"],
    )
    submission_provenance = (
        technoeconomic_api.build_technoeconomic_submission_provenance(
            canonical,
            snapshot_envelope,
            kernel_request,
        )
    )
    source_store_fields = technoeconomic_api.technoeconomic_source_store_fields(
        snapshot_envelope
    )
    if submission_provenance.get("request_sha256") != request_hash:
        raise ScenarioContractError(
            "scenario_provenance_request_mismatch",
            "The standalone TEA provenance did not bind the canonical scenario request.",
        )
    return {
        "request": canonical,
        "request_sha256": request_hash,
        "source_snapshot_envelope": snapshot_envelope,
        "validated_kernel_request": kernel_request,
        "submission_provenance": submission_provenance,
        "source_store_fields": source_store_fields,
    }


def _scenario_request(record: Mapping[str, Any]) -> Mapping[str, Any]:
    request = record.get("request")
    if not isinstance(request, Mapping):
        request = record.get("request_payload")
    if not isinstance(request, Mapping):
        raise ScenarioContractError(
            "scenario_record_invalid",
            "A comparison scenario is missing its immutable TEA request.",
        )
    return request


def build_scenario_comparison(
    *,
    case_record: Mapping[str, Any],
    baseline: Mapping[str, Any],
    alternatives: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Build an exact pre-run input/hypothesis comparison and table alternative."""

    if len(alternatives) > 3:
        raise ScenarioContractError(
            "scenario_alternative_limit_exceeded",
            "A decision case supports at most three current alternatives.",
        )
    baseline_request, baseline_hash = normalize_submission_request(
        _scenario_request(baseline), kind="baseline"
    )
    stored_baseline_hash = baseline.get("request_sha256")
    if stored_baseline_hash is not None and stored_baseline_hash != baseline_hash:
        raise ScenarioContractError(
            "scenario_request_hash_mismatch",
            "The baseline request does not match its immutable canonical SHA-256.",
        )
    if (
        baseline_request["source_annual_job_id"]
        != str(case_record.get("source_annual_job_id") or "")
        or baseline_request["basis"]
        != str(case_record.get("analysis_basis") or "")
    ):
        raise ScenarioContractError(
            "scenario_comparison_lock_mismatch",
            "The baseline does not match the immutable case source and basis.",
            closest_supported_alternatives=(CREATE_NEW_CASE_ALTERNATIVE,),
        )

    scenario_columns: list[dict[str, Any]] = []
    diff_by_scenario: dict[str, dict[str, dict[str, Any]]] = {}
    all_paths: set[str] = set()
    warnings: list[dict[str, Any]] = []
    seen_scenario_ids: set[str] = set()
    for index, record in enumerate(alternatives):
        request, request_hash = normalize_submission_request(
            _scenario_request(record),
            baseline_request=baseline_request,
            kind="alternative",
        )
        stored_hash = record.get("request_sha256")
        if stored_hash is not None and stored_hash != request_hash:
            raise ScenarioContractError(
                "scenario_request_hash_mismatch",
                "An alternative request does not match its immutable canonical SHA-256.",
            )
        if (
            request["source_annual_job_id"] != baseline_request["source_annual_job_id"]
            or request["basis"] != baseline_request["basis"]
            or request["n"] != baseline_request["n"]
            or request["seed"] != baseline_request["seed"]
        ):
            raise ScenarioContractError(
                "scenario_comparison_lock_mismatch",
                "Comparison scenarios must share source, basis, realizations, and seed.",
                closest_supported_alternatives=(CREATE_NEW_CASE_ALTERNATIVE,),
            )
        rows = json_pointer_leaf_diff(baseline_request, request)
        classification = classify_comparison(baseline_request, request, rows)
        if classification == "structural":
            _append_unique(warnings, STRUCTURAL_CAUSAL_WARNING)
        key = str(record.get("scenario_id") or record.get("id") or f"alternative-{index + 1}")
        if key in seen_scenario_ids:
            raise ScenarioContractError(
                "duplicate_scenario_selection",
                "A comparison may include each alternative scenario only once.",
            )
        seen_scenario_ids.add(key)
        diff_by_scenario[key] = {str(item["path"]): item for item in rows}
        all_paths.update(diff_by_scenario[key])
        scenario_columns.append(
            {
                "scenario_id": key,
                "revision": record.get("revision"),
                "label": str(record.get("label") or f"Alternative {index + 1}"),
                "request_sha256": request_hash,
                "comparison_classification": classification,
                "evidence_state": deepcopy(
                    record.get("evidence_state") or record.get("evidence_receipts") or []
                ),
                "status": record.get("status"),
                "expires_at": record.get("expires_at"),
            }
        )

    matrix: list[dict[str, Any]] = []
    for path in sorted(all_paths):
        first = next(
            diff_by_scenario[item["scenario_id"]][path]
            for item in scenario_columns
            if path in diff_by_scenario[item["scenario_id"]]
        )
        cells: list[dict[str, Any]] = []
        for column in scenario_columns:
            row = diff_by_scenario[column["scenario_id"]].get(path)
            cells.append(
                {
                    "scenario_id": column["scenario_id"],
                    "changed": row is not None,
                    "present": (
                        bool(row["scenario_present"])
                        if row is not None
                        else bool(first["baseline_present"])
                    ),
                    "value": (
                        deepcopy(row["scenario_value"])
                        if row is not None
                        else deepcopy(first["baseline_value"])
                    ),
                    "value_kind": "hypothesis",
                }
            )
        matrix.append(
            {
                "path": path,
                "baseline": {
                    "present": bool(first["baseline_present"]),
                    "value": deepcopy(first["baseline_value"]),
                    "value_kind": "input",
                },
                "alternatives": cells,
            }
        )

    baseline_column = {
        "scenario_id": str(baseline.get("scenario_id") or baseline.get("id") or "baseline"),
        "revision": baseline.get("revision"),
        "label": str(baseline.get("label") or "Baseline"),
        "request_sha256": baseline_hash,
        "comparison_classification": "baseline",
        "evidence_state": deepcopy(
            baseline.get("evidence_state") or baseline.get("evidence_receipts") or []
        ),
        "status": baseline.get("status"),
        "expires_at": baseline.get("expires_at"),
    }
    return {
        "comparison_version": SCENARIO_COMPARISON_VERSION,
        "pre_run_value_semantics": "inputs_or_hypotheses_not_outcomes",
        "outcomes_available": False,
        "source_basis_lock": {
            "source_annual_job_id": case_record.get("source_annual_job_id"),
            "source_snapshot_sha256": case_record.get("source_snapshot_sha256"),
            "analysis_basis": case_record.get("analysis_basis"),
            "value_kind": "input",
        },
        "realization_count": baseline_request["n"],
        "seed": baseline_request["seed"],
        "run_controls": {
            "realization_count": {
                "value": baseline_request["n"],
                "value_kind": "input",
            },
            "seed": {
                "value": baseline_request["seed"],
                "value_kind": "input",
            },
        },
        "baseline": baseline_column,
        "alternatives": scenario_columns,
        "difference_matrix": matrix,
        "table_alternative": {
            "caption": "Exact baseline-relative TEA input and hypothesis differences",
            "columns": [baseline_column, *scenario_columns],
            "rows": deepcopy(matrix),
        },
        "warnings": warnings,
    }


__all__ = [
    "CREATE_NEW_CASE_ALTERNATIVE",
    "OPEN_EXPERT_TEA_ALTERNATIVE",
    "SCENARIO_COMPARISON_VERSION",
    "SCENARIO_VALIDATION_VERSION",
    "STRUCTURAL_CAUSAL_WARNING",
    "ScenarioContractError",
    "build_scenario_comparison",
    "classify_comparison",
    "json_pointer_leaf_diff",
    "normalize_submission_request",
    "prepare_technoeconomic_bundle",
    "validate_scenario_draft",
    "verify_accepted_evidence_references",
]
