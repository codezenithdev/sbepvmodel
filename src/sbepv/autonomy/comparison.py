"""Pure deterministic Autonomy comparison-bundle assembly.

This module accepts immutable confirmation/scenario/job records plus successful
read-only verification outcomes.  It does not read files, query a store, call a
model, or run/recalculate TEA.  Missing and non-successful attempts are retained
as explicit comparison rows, while only a reverified ``done`` attempt may supply
numeric result content.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
import hashlib
import json
import re
import secrets
from typing import TYPE_CHECKING, Any

from sbepv import technoeconomic as technoeconomic_kernel
from sbepv.autonomy import serializers as autonomy_serializers

if TYPE_CHECKING:
    from sbepv.autonomy.result_verification import ResultVerificationOutcome


COMPARISON_BUNDLE_SCHEMA_VERSION = "autonomy-comparison-bundle-v1"
ATTEMPT_SELECTION_CONTRACT_VERSION = "confirmed-scenario-retry-chain-v1"
CANONICALIZATION_VERSION = "canonical-json-sha256-v1"
CLASSIFICATION_PENDING_CONTRACT = "classification_pending_contract"

_SHA256_RE = re.compile(r"[0-9a-f]{64}", re.ASCII)
_DURABLE_STATES = frozenset(
    {"queued", "running", "done", "error", "cancelled", "interrupted"}
)
_TERMINAL_STATES = frozenset({"done", "error", "cancelled", "interrupted"})
_MISSING = object()


class ComparisonContractError(ValueError):
    """Raised when supplied durable records contradict immutable authority."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _canonical_json_text(value: Any) -> str:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError, OverflowError) as exc:
        raise ComparisonContractError(
            "comparison_value_not_canonical",
            "Comparison values must be finite canonical JSON.",
        ) from exc


def canonical_comparison_bundle_sha256(
    bundle_without_hash: Mapping[str, Any],
) -> str:
    """Hash canonical bundle content, always excluding ``bundle_hash`` itself."""

    payload = deepcopy(dict(bundle_without_hash))
    payload.pop("bundle_hash", None)
    return hashlib.sha256(_canonical_json_text(payload).encode("utf-8")).hexdigest()


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json_text(value).encode("utf-8")).hexdigest()


def _escape_pointer_token(value: object) -> str:
    return str(value).replace("~", "~0").replace("/", "~1")


def _json_pointer_leaf_diff(baseline: Any, scenario: Any) -> list[dict[str, Any]]:
    """Pure lossless leaf diff with explicit missing-versus-null identity."""

    rows: list[dict[str, Any]] = []

    def equal(left: Any, right: Any) -> bool:
        try:
            return _canonical_json_text(left) == _canonical_json_text(right)
        except ComparisonContractError:
            return type(left) is type(right) and left == right

    def add(path: str, left: Any, right: Any) -> None:
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
        if left is not _MISSING and right is not _MISSING and equal(left, right):
            return
        if (
            left is not _MISSING
            and right is not _MISSING
            and isinstance(left, Mapping)
            and isinstance(right, Mapping)
        ):
            keys = sorted(set(left) | set(right), key=str)
            if not keys:
                add(path, left, right)
            for key in keys:
                walk(
                    left.get(key, _MISSING),
                    right.get(key, _MISSING),
                    f"{path}/{_escape_pointer_token(key)}",
                )
            return
        if (
            left is not _MISSING
            and right is not _MISSING
            and isinstance(left, list)
            and isinstance(right, list)
        ):
            if not left and not right:
                add(path, left, right)
            for index in range(max(len(left), len(right))):
                walk(
                    left[index] if index < len(left) else _MISSING,
                    right[index] if index < len(right) else _MISSING,
                    f"{path}/{index}",
                )
            return
        if left is _MISSING and isinstance(right, Mapping) and right:
            for key in sorted(right, key=str):
                walk(
                    _MISSING,
                    right[key],
                    f"{path}/{_escape_pointer_token(key)}",
                )
            return
        if right is _MISSING and isinstance(left, Mapping) and left:
            for key in sorted(left, key=str):
                walk(
                    left[key],
                    _MISSING,
                    f"{path}/{_escape_pointer_token(key)}",
                )
            return
        if left is _MISSING and isinstance(right, list) and right:
            for index, value in enumerate(right):
                walk(_MISSING, value, f"{path}/{index}")
            return
        if right is _MISSING and isinstance(left, list) and left:
            for index, value in enumerate(left):
                walk(value, _MISSING, f"{path}/{index}")
            return
        add(path, left, right)

    walk(baseline, scenario, "")
    rows.sort(key=lambda item: item["path"])
    return rows


def _record_id(record: Mapping[str, Any], *names: str) -> str:
    for name in names:
        value = record.get(name)
        if isinstance(value, str) and value:
            return value
    return ""


def _require_digest(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise ComparisonContractError(
            "comparison_identity_invalid",
            f"{field} must be a canonical SHA-256.",
        )
    return value


def _require_sequence(value: Any, *, field: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(
        value, (str, bytes, bytearray)
    ):
        raise ComparisonContractError(
            "comparison_record_invalid",
            f"{field} must be an array.",
        )
    return value


def _job_id(job: Mapping[str, Any]) -> str:
    return _record_id(job, "id", "tea_job_id")


def _attempt_number(job: Mapping[str, Any]) -> int:
    value = job.get("attempt_number")
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ComparisonContractError(
            "attempt_number_invalid",
            "Every confirmed TEA attempt requires a positive attempt number.",
        )
    return value


def _job_request_sha256(job: Mapping[str, Any]) -> str:
    request = job.get("request")
    if not isinstance(request, Mapping):
        raise ComparisonContractError(
            "attempt_request_missing",
            "A confirmed TEA attempt is missing its immutable request.",
        )
    return _canonical_sha256(request)


def _normalized_evidence_references(value: Any) -> list[dict[str, Any]]:
    references = _require_sequence(value or [], field="scenario evidence references")
    normalized: list[dict[str, Any]] = []
    for reference in references:
        if not isinstance(reference, Mapping):
            raise ComparisonContractError(
                "confirmation_evidence_identity_invalid",
                "A confirmed evidence reference is invalid.",
            )
        normalized.append(
            {
                "request_path": reference.get("request_path"),
                "evidence_receipt_id": (
                    reference.get("evidence_receipt_id")
                    or reference.get("receipt_id")
                ),
            }
        )
    return normalized


def _validate_embedded_evidence_receipt(
    reference: Mapping[str, Any],
    *,
    case_id: str,
) -> None:
    """Prove the durable receipt envelope without reading preserved bytes."""

    receipt_row = reference.get("receipt")
    if not isinstance(receipt_row, Mapping):
        raise ComparisonContractError(
            "confirmation_evidence_receipt_missing",
            "A confirmed evidence reference is missing its durable receipt.",
        )
    receipt_payload = receipt_row.get("receipt")
    if not isinstance(receipt_payload, Mapping):
        raise ComparisonContractError(
            "confirmation_evidence_receipt_invalid",
            "A confirmed evidence receipt payload is invalid.",
        )
    receipt_id = str(
        reference.get("evidence_receipt_id")
        or reference.get("receipt_id")
        or ""
    )
    stored_receipt_id = _record_id(
        receipt_row, "id", "evidence_receipt_id"
    )
    receipt_sha256 = _require_digest(
        receipt_row.get("receipt_sha256"),
        field="evidence receipt_sha256",
    )
    if (
        not receipt_id
        or stored_receipt_id != receipt_id
        or receipt_payload.get("evidence_receipt_id") != receipt_id
        or receipt_row.get("case_id") != case_id
        or receipt_payload.get("case_id") != case_id
        or receipt_row.get("decision") != "accepted"
        or receipt_payload.get("decision") != "accepted"
        or receipt_row.get("preservation_mode") != "server_managed_content_v1"
        or receipt_payload.get("preservation_mode")
        != "server_managed_content_v1"
        or not secrets.compare_digest(
            _canonical_sha256(receipt_payload), receipt_sha256
        )
    ):
        raise ComparisonContractError(
            "confirmation_evidence_receipt_mismatch",
            "A confirmed evidence receipt differs from immutable authority.",
        )
    content = receipt_payload.get("content")
    if not isinstance(content, Mapping):
        raise ComparisonContractError(
            "confirmation_evidence_content_identity_invalid",
            "A confirmed evidence receipt has no preserved-content identity.",
        )
    content_sha256 = _require_digest(
        content.get("sha256"),
        field="evidence content sha256",
    )
    content_bytes = content.get("byte_count")
    if (
        isinstance(content_bytes, bool)
        or not isinstance(content_bytes, int)
        or content_bytes < 0
        or (
            receipt_row.get("asset_sha256") is not None
            and receipt_row.get("asset_sha256") != content_sha256
        )
        or (
            receipt_row.get("asset_byte_count") is not None
            and receipt_row.get("asset_byte_count") != content_bytes
        )
    ):
        raise ComparisonContractError(
            "confirmation_evidence_content_identity_invalid",
            "A confirmed evidence receipt content identity is invalid.",
        )


def _validate_confirmation_authority(
    *,
    case_record: Mapping[str, Any],
    confirmation_record: Mapping[str, Any],
    scenario_records: Sequence[Mapping[str, Any]],
) -> None:
    """Validate one immutable confirmation envelope for complete or partial views.

    This proof is intentionally mapping-only.  Completed attempts additionally
    re-read preserved evidence and result artifacts in ``result_verification``.
    """

    case_id = _record_id(case_record, "id", "case_id")
    confirmation_id = _record_id(
        confirmation_record, "id", "confirmation_id"
    )
    if not case_id or confirmation_record.get("case_id") != case_id:
        raise ComparisonContractError(
            "comparison_case_mismatch",
            "The confirmation does not belong to the selected decision case.",
        )
    request_payload = confirmation_record.get("confirmation_request")
    receipt = confirmation_record.get("receipt")
    if not isinstance(request_payload, Mapping) or not isinstance(receipt, Mapping):
        raise ComparisonContractError(
            "confirmation_authority_missing",
            "The immutable confirmation request or receipt is unavailable.",
        )
    request_sha256 = _require_digest(
        confirmation_record.get("confirmation_request_sha256"),
        field="confirmation_request_sha256",
    )
    receipt_sha256 = _require_digest(
        confirmation_record.get("receipt_sha256"),
        field="confirmation receipt_sha256",
    )
    if not secrets.compare_digest(
        _canonical_sha256(request_payload), request_sha256
    ):
        raise ComparisonContractError(
            "confirmation_request_digest_mismatch",
            "The confirmation request differs from its immutable SHA-256.",
        )
    if not secrets.compare_digest(_canonical_sha256(receipt), receipt_sha256):
        raise ComparisonContractError(
            "confirmation_receipt_digest_mismatch",
            "The confirmation receipt differs from its immutable SHA-256.",
        )

    raw_items = _require_sequence(
        confirmation_record.get("items") or [], field="confirmation items"
    )
    items = [item for item in raw_items if isinstance(item, Mapping)]
    try:
        ordered_items = sorted(items, key=lambda item: int(item.get("item_index")))
    except (TypeError, ValueError):
        ordered_items = []
    request_scenarios = _require_sequence(
        request_payload.get("scenarios") or [],
        field="confirmation request scenarios",
    )
    receipt_scenarios = _require_sequence(
        receipt.get("scenarios") or [],
        field="confirmation receipt scenarios",
    )
    if (
        not items
        or len(items) != len(raw_items)
        or [item.get("item_index") for item in ordered_items]
        != list(range(len(items)))
        or len(request_scenarios) != len(items)
        or len(receipt_scenarios) != len(items)
        or request_payload.get("schema_version") != 1
        or request_payload.get("case_id") != case_id
        or request_payload.get("expected_case_revision")
        != confirmation_record.get("expected_case_revision")
        or receipt.get("schema_version") != 1
        or receipt.get("confirmation_id") != confirmation_id
        or receipt.get("case_id") != case_id
        or receipt.get("case_revision_before")
        != confirmation_record.get("expected_case_revision")
        or receipt.get("case_revision_after")
        != confirmation_record.get("case_revision_after")
    ):
        raise ComparisonContractError(
            "confirmation_identity_mismatch",
            "The confirmation envelope has inconsistent durable identities.",
        )

    source_lock = receipt.get("source_lock")
    if not isinstance(source_lock, Mapping):
        raise ComparisonContractError(
            "confirmation_source_lock_missing",
            "The confirmation receipt has no immutable source lock.",
        )
    for actual, expected in (
        (source_lock.get("source_annual_job_id"), case_record.get("source_annual_job_id")),
        (source_lock.get("source_snapshot_sha256"), case_record.get("source_snapshot_sha256")),
        (source_lock.get("analysis_basis"), case_record.get("analysis_basis")),
    ):
        if actual != expected:
            raise ComparisonContractError(
                "confirmation_source_lock_mismatch",
                "The confirmation source lock differs from the decision case.",
            )

    scenario_by_revision = {
        _record_id(scenario, "scenario_revision_id"): scenario
        for scenario in scenario_records
        if isinstance(scenario, Mapping)
    }
    for item, request_scenario, receipt_scenario in zip(
        ordered_items, request_scenarios, receipt_scenarios, strict=True
    ):
        if not isinstance(request_scenario, Mapping) or not isinstance(
            receipt_scenario, Mapping
        ):
            raise ComparisonContractError(
                "confirmation_item_identity_mismatch",
                "A confirmation scenario identity is invalid.",
            )
        root_job = item.get("job")
        if not isinstance(root_job, Mapping):
            raise ComparisonContractError(
                "confirmation_root_attempt_missing",
                "A confirmation item is missing its root TEA attempt.",
            )
        request_digest = _require_digest(
            item.get("request_sha256"), field="confirmation item request_sha256"
        )
        root_request = root_job.get("request")
        root_job_id = _job_id(root_job)
        item_job_id = str(item.get("tea_job_id") or item.get("job_id") or "")
        if (
            request_scenario.get("scenario_revision_id")
            != item.get("scenario_revision_id")
            or request_scenario.get("expected_revision")
            != item.get("scenario_revision")
            or request_scenario.get("request_sha256") != request_digest
            or receipt_scenario.get("scenario_id") != item.get("scenario_id")
            or receipt_scenario.get("scenario_revision_id")
            != item.get("scenario_revision_id")
            or receipt_scenario.get("scenario_revision")
            != item.get("scenario_revision")
            or receipt_scenario.get("request_sha256") != request_digest
            or receipt_scenario.get("tea_job_id") != item_job_id
            or root_job_id != item_job_id
            or not isinstance(root_request, Mapping)
            or not secrets.compare_digest(_canonical_sha256(root_request), request_digest)
        ):
            raise ComparisonContractError(
                "confirmation_item_identity_mismatch",
                "A confirmation item differs from its request or receipt authority.",
            )
        for field in (
            "source_annual_job_id",
            "source_artifact_sha256",
            "source_artifact_bytes",
            "source_snapshot_sha256",
            "submission_provenance_sha256",
        ):
            if root_job.get(field) != request_scenario.get(field):
                raise ComparisonContractError(
                    "confirmation_root_attempt_identity_mismatch",
                    "The confirmed root TEA attempt changed its frozen identity.",
                )
        root_basis = root_request.get("basis", root_request.get("analysis_basis"))
        if any(
            (
                request_scenario.get("source_annual_job_id")
                != source_lock.get("source_annual_job_id"),
                request_scenario.get("source_snapshot_sha256")
                != source_lock.get("source_snapshot_sha256"),
                root_basis != source_lock.get("analysis_basis"),
            )
        ):
            raise ComparisonContractError(
                "confirmation_source_lock_mismatch",
                "A confirmed scenario differs from the immutable source lock.",
            )

        revision_id = str(item.get("scenario_revision_id") or "")
        scenario = scenario_by_revision.get(revision_id)
        if scenario is None:
            continue
        scenario_revision = scenario.get("revision")
        if scenario_revision is None:
            scenario_revision = scenario.get("scenario_revision")
        if any(
            (
                scenario.get("case_id") != case_id,
                scenario.get("confirmation_id") != confirmation_id,
                _record_id(scenario, "scenario_id", "id")
                != item.get("scenario_id"),
                scenario_revision != item.get("scenario_revision"),
                scenario.get("kind") != receipt_scenario.get("kind"),
                scenario.get("request_sha256") != request_digest,
                scenario.get("source_annual_job_id")
                != source_lock.get("source_annual_job_id"),
                scenario.get("source_snapshot_sha256")
                != source_lock.get("source_snapshot_sha256"),
                scenario.get("analysis_basis") != source_lock.get("analysis_basis"),
            )
        ):
            raise ComparisonContractError(
                "scenario_confirmation_scope_mismatch",
                "A scenario differs from its immutable confirmation authority.",
            )
        scenario_request = scenario.get("request")
        if not isinstance(scenario_request, Mapping) or not secrets.compare_digest(
            _canonical_sha256(scenario_request), request_digest
        ):
            raise ComparisonContractError(
                "scenario_request_digest_mismatch",
                "The confirmed scenario request identity changed.",
            )
        scenario_jobs = _require_sequence(
            scenario.get("jobs") or [], field="scenario jobs"
        )
        for scenario_job in scenario_jobs:
            if not isinstance(scenario_job, Mapping):
                raise ComparisonContractError(
                    "attempt_record_invalid",
                    "A confirmed scenario has an invalid TEA attempt record.",
                )
            for field in (
                "source_annual_job_id",
                "source_artifact_sha256",
                "source_artifact_bytes",
                "source_snapshot_sha256",
                "submission_provenance_sha256",
            ):
                if scenario_job.get(field) != request_scenario.get(field):
                    raise ComparisonContractError(
                        "confirmation_selected_job_identity_mismatch",
                        (
                            "A confirmed TEA attempt differs from the immutable "
                            "confirmation request."
                        ),
                    )
        scenario_evidence = _normalized_evidence_references(
            scenario.get("evidence_receipt_refs") or []
        )
        if receipt_scenario.get("evidence_receipt_refs") != scenario_evidence:
            raise ComparisonContractError(
                "confirmation_evidence_membership_mismatch",
                "The confirmed evidence membership changed.",
            )
        for reference in scenario.get("evidence_receipt_refs") or []:
            _validate_embedded_evidence_receipt(reference, case_id=case_id)


def _chain_identity(job: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        job.get("source_annual_job_id"),
        job.get("source_artifact_storage_key"),
        job.get("source_artifact_sha256"),
        job.get("source_artifact_bytes"),
        job.get("source_snapshot_sha256"),
        job.get("submission_provenance_sha256"),
    )


def _validate_attempt_chain(
    *,
    confirmation_id: str,
    confirmation_item: Mapping[str, Any],
    scenario_record: Mapping[str, Any],
) -> tuple[Mapping[str, Any], ...]:
    raw_jobs = _require_sequence(
        scenario_record.get("jobs") or [],
        field="scenario jobs",
    )
    jobs = [job for job in raw_jobs if isinstance(job, Mapping)]
    if len(jobs) != len(raw_jobs):
        raise ComparisonContractError(
            "attempt_record_invalid",
            "A confirmed scenario has an invalid TEA attempt record.",
        )
    if not jobs:
        return ()
    ordered = sorted(jobs, key=_attempt_number)
    expected_numbers = list(range(1, len(ordered) + 1))
    if [_attempt_number(job) for job in ordered] != expected_numbers:
        raise ComparisonContractError(
            "attempt_chain_not_contiguous",
            "The confirmed scenario retry history is not contiguous.",
        )
    identifiers = [_job_id(job) for job in ordered]
    if any(not value for value in identifiers) or len(set(identifiers)) != len(
        identifiers
    ):
        raise ComparisonContractError(
            "attempt_identity_invalid",
            "The confirmed scenario retry history has duplicate or missing jobs.",
        )
    initial_job_id = str(
        confirmation_item.get("tea_job_id")
        or confirmation_item.get("job_id")
        or ""
    )
    if identifiers[0] != initial_job_id or ordered[0].get("retry_of_job_id") is not None:
        raise ComparisonContractError(
            "attempt_confirmation_root_mismatch",
            "The retry chain does not start at the confirmed TEA attempt.",
        )
    request_sha256 = _require_digest(
        confirmation_item.get("request_sha256"),
        field="confirmation item request_sha256",
    )
    scenario_sha256 = _require_digest(
        scenario_record.get("request_sha256"),
        field="scenario request_sha256",
    )
    if not secrets.compare_digest(request_sha256, scenario_sha256):
        raise ComparisonContractError(
            "scenario_request_digest_mismatch",
            "The confirmed scenario request identity changed.",
        )
    chain_identity = _chain_identity(ordered[0])
    for index, job in enumerate(ordered):
        state = job.get("state")
        if state not in _DURABLE_STATES:
            raise ComparisonContractError(
                "attempt_state_invalid",
                "A confirmed TEA attempt has an unsupported durable state.",
            )
        expected_parent = None if index == 0 else identifiers[index - 1]
        expected_confirmation = confirmation_id if index == 0 else None
        if job.get("scenario_confirmation_id") != expected_confirmation:
            raise ComparisonContractError(
                "attempt_confirmation_mismatch",
                (
                    "The initial TEA attempt is not linked to its confirmation "
                    "receipt."
                    if index == 0
                    else "A retry incorrectly claims a new confirmation receipt."
                ),
            )
        if job.get("retry_of_job_id") != expected_parent:
            raise ComparisonContractError(
                "attempt_retry_link_mismatch",
                "The confirmed scenario retry chain has an invalid parent link.",
            )
        if _chain_identity(job) != chain_identity:
            raise ComparisonContractError(
                "attempt_frozen_identity_mismatch",
                "A retry changed the frozen source or submission authority.",
            )
        calculated_request_sha256 = _job_request_sha256(job)
        provenance = job.get("submission_provenance")
        provenance_request_sha256 = (
            provenance.get("request_sha256")
            if isinstance(provenance, Mapping)
            else None
        )
        for actual in (calculated_request_sha256, provenance_request_sha256):
            if not isinstance(actual, str) or not secrets.compare_digest(
                actual, request_sha256
            ):
                raise ComparisonContractError(
                    "attempt_request_digest_mismatch",
                    "A retry changed the confirmed immutable TEA request.",
                )
    return tuple(ordered)


def select_confirmation_attempts(
    *,
    confirmation_record: Mapping[str, Any],
    scenario_records: Sequence[Mapping[str, Any]],
) -> tuple[Mapping[str, Any], ...]:
    """Select only explicit confirmation-scoped retry-chain endpoints.

    The durable link's monotonically increasing ``attempt_number`` and exact
    ``retry_of_job_id`` chain are authoritative.  No latest-job lookup, timestamp,
    or unrelated successful result participates in selection.
    """

    confirmation_id = _record_id(
        confirmation_record, "id", "confirmation_id"
    )
    case_id = _record_id(confirmation_record, "case_id")
    if not confirmation_id or not case_id:
        raise ComparisonContractError(
            "confirmation_identity_missing",
            "A comparison requires one immutable confirmation receipt.",
        )
    raw_items = _require_sequence(
        confirmation_record.get("items") or [],
        field="confirmation items",
    )
    items = [item for item in raw_items if isinstance(item, Mapping)]
    if not items or len(items) != len(raw_items):
        raise ComparisonContractError(
            "confirmation_items_invalid",
            "A comparison requires valid immutable confirmation items.",
        )
    ordered_items = sorted(items, key=lambda item: item.get("item_index", -1))
    indices = [item.get("item_index") for item in ordered_items]
    if indices != list(range(len(ordered_items))):
        raise ComparisonContractError(
            "confirmation_item_order_invalid",
            "Confirmation item indices must be contiguous and ordered.",
        )
    scenario_by_revision: dict[str, Mapping[str, Any]] = {}
    for scenario in scenario_records:
        if not isinstance(scenario, Mapping):
            raise ComparisonContractError(
                "scenario_record_invalid",
                "A comparison scenario record is invalid.",
            )
        revision_id = _record_id(scenario, "scenario_revision_id")
        if not revision_id or revision_id in scenario_by_revision:
            raise ComparisonContractError(
                "scenario_identity_invalid",
                "Comparison scenarios have duplicate or missing revision identities.",
            )
        scenario_by_revision[revision_id] = scenario

    selections: list[Mapping[str, Any]] = []
    selected_job_ids: set[str] = set()
    for item in ordered_items:
        revision_id = _record_id(item, "scenario_revision_id")
        scenario_id = _record_id(item, "scenario_id")
        request_sha256 = _require_digest(
            item.get("request_sha256"),
            field="confirmation item request_sha256",
        )
        if not revision_id or not scenario_id:
            raise ComparisonContractError(
                "confirmation_item_identity_invalid",
                "A confirmation item is missing its immutable scenario identity.",
            )
        scenario = scenario_by_revision.get(revision_id)
        if scenario is None:
            selections.append(
                {
                    "item_index": int(item["item_index"]),
                    "confirmation_id": confirmation_id,
                    "case_id": case_id,
                    "scenario_id": scenario_id,
                    "scenario_revision_id": revision_id,
                    "scenario_revision": int(
                        item.get("scenario_revision") or item.get("revision") or 0
                    ),
                    "request_sha256": request_sha256,
                    "selection_status": "missing",
                    "display_status": "missing",
                    "selected_job_id": None,
                    "selected_attempt_number": None,
                    "selected_job": None,
                    "scenario_record": None,
                    "confirmation_item": item,
                    # The confirmation item proves the root identity but does not
                    # carry the link-table attempt number/evidence binding needed
                    # for an attempt proof.  Retain it as missing; never fabricate
                    # the absent durable link.
                    "attempt_history": (),
                }
            )
            continue
        if (
            scenario.get("case_id") != case_id
            or scenario.get("confirmation_id") != confirmation_id
            or _record_id(scenario, "scenario_id", "id") != scenario_id
        ):
            raise ComparisonContractError(
                "scenario_confirmation_scope_mismatch",
                "A scenario is outside the immutable confirmation scope.",
            )
        chain = _validate_attempt_chain(
            confirmation_id=confirmation_id,
            confirmation_item=item,
            scenario_record=scenario,
        )
        if not chain:
            selection_status = "missing"
            display_status = "missing"
            selected_job = None
            selected_job_id = None
            selected_attempt_number = None
        else:
            selected_job = chain[-1]
            selected_job_id = _job_id(selected_job)
            if selected_job_id in selected_job_ids:
                raise ComparisonContractError(
                    "duplicate_attempt_selection",
                    "A TEA attempt cannot satisfy multiple confirmation items.",
                )
            selected_job_ids.add(selected_job_id)
            selection_status = "selected"
            display_status = str(selected_job.get("state"))
            selected_attempt_number = _attempt_number(selected_job)
        selections.append(
            {
                "item_index": int(item["item_index"]),
                "confirmation_id": confirmation_id,
                "case_id": case_id,
                "scenario_id": scenario_id,
                "scenario_revision_id": revision_id,
                "scenario_revision": int(
                    item.get("scenario_revision")
                    or item.get("revision")
                    or scenario.get("revision")
                    or 0
                ),
                "request_sha256": request_sha256,
                "selection_status": selection_status,
                "display_status": display_status,
                "selected_job_id": selected_job_id,
                "selected_attempt_number": selected_attempt_number,
                "selected_job": selected_job,
                "scenario_record": scenario,
                "confirmation_item": item,
                "attempt_history": chain,
            }
        )
    return tuple(selections)


def _metric_registry(contract_version: str) -> dict[str, tuple[str, str]]:
    if contract_version == technoeconomic_kernel.LEGACY_CALCULATION_CONTRACT_VERSION:
        normalized = {
            technoeconomic_kernel.FIELD_DELTA_COST: (
                "USD/Wdc",
                "all_finite_realizations",
            ),
            technoeconomic_kernel.FIELD_DELTA_EA_COST: (
                "USD/Wdc-year",
                "all_finite_realizations",
            ),
            technoeconomic_kernel.FIELD_DELTA_ENERGY: (
                "kWh_AC/Wdc",
                "all_finite_realizations",
            ),
            technoeconomic_kernel.FIELD_DELTA_EA_ENERGY: (
                "kWh_AC/Wdc-year",
                "all_finite_realizations",
            ),
        }
    elif contract_version in {
        technoeconomic_kernel.CALCULATION_CONTRACT_VERSION,
        technoeconomic_kernel.COMMERCIAL_SCALING_CALCULATION_CONTRACT_VERSION,
    }:
        normalized = {
            technoeconomic_kernel.APPLIED_FIELD_DELTA_COST: (
                "USD/applied_W",
                "all_finite_realizations",
            ),
            technoeconomic_kernel.APPLIED_FIELD_DELTA_EA_COST: (
                "USD/applied_W-year",
                "all_finite_realizations",
            ),
            technoeconomic_kernel.APPLIED_FIELD_DELTA_ENERGY: (
                "kWh_AC/applied_W",
                "all_finite_realizations",
            ),
            technoeconomic_kernel.APPLIED_FIELD_DELTA_EA_ENERGY: (
                "kWh_AC/applied_W-year",
                "all_finite_realizations",
            ),
        }
    else:
        raise ComparisonContractError(
            "calculation_contract_unsupported",
            "The completed result uses an unsupported TEA calculation contract.",
        )
    registry = {
        **normalized,
        technoeconomic_kernel.FIELD_LCOE_SOL: (
            "USD/kWh_AC",
            "all_finite_realizations_solectria",
        ),
        technoeconomic_kernel.FIELD_LCOE_SE: (
            "USD/kWh_AC",
            "all_finite_realizations_solaredge",
        ),
        "headline_positive_gain_lcoo": (
            "USD/kWh_AC",
            "positive_lifecycle_gain_realizations_only",
        ),
        "signed_nonzero_lcoo": (
            "USD/kWh_AC",
            "all_nonzero_lifecycle_energy_realizations",
        ),
    }
    if (
        contract_version
        == technoeconomic_kernel.COMMERCIAL_SCALING_CALCULATION_CONTRACT_VERSION
    ):
        registry.update(
            {
                technoeconomic_kernel.COMMERCIAL_FIELD_TARGET_CAPACITY: (
                    "W",
                    "all_finite_realizations",
                ),
                technoeconomic_kernel.COMMERCIAL_FIELD_YEAR1_DELTA_ENERGY: (
                    "kWh_AC",
                    "all_finite_realizations",
                ),
                technoeconomic_kernel.COMMERCIAL_FIELD_LIFECYCLE_DELTA_ENERGY: (
                    "kWh_AC",
                    "all_finite_realizations",
                ),
                technoeconomic_kernel.COMMERCIAL_FIELD_EA_DELTA_ENERGY: (
                    "kWh_AC/year",
                    "all_finite_realizations",
                ),
                technoeconomic_kernel.COMMERCIAL_FIELD_LIFECYCLE_MARGINAL_COST: (
                    "constant USD",
                    "all_finite_realizations",
                ),
                technoeconomic_kernel.COMMERCIAL_FIELD_EA_MARGINAL_COST: (
                    "constant USD/year",
                    "all_finite_realizations",
                ),
                technoeconomic_kernel.COMMERCIAL_FIELD_MARGINAL_LCOO: (
                    "constant USD/kWh_AC",
                    "all_nonzero_commercial_lifecycle_energy_realizations",
                ),
            }
        )
    return registry


def _project_metrics(
    *,
    result: Mapping[str, Any],
    result_provenance: Mapping[str, Any],
    sealed_metadata: Mapping[str, Any],
    selection: Mapping[str, Any],
) -> dict[str, Any]:
    contract_version = str(result.get("calculation_contract_version") or "")
    registry = _metric_registry(contract_version)
    summaries = result.get("summaries")
    sealed_summaries = sealed_metadata.get("summaries")
    if not isinstance(summaries, Mapping) or not isinstance(
        sealed_summaries, Mapping
    ):
        raise ComparisonContractError(
            "verified_summary_missing",
            "A verified TEA result is missing its metric summaries.",
        )
    metric_ids = set(summaries) - {"energy_classes", "tradeoff_classes"}
    if metric_ids != set(registry):
        raise ComparisonContractError(
            "verified_metric_schema_mismatch",
            "A verified TEA result differs from its versioned metric schema.",
        )
    metrics: dict[str, Any] = {}
    for metric_id, (unit, population_semantics) in registry.items():
        routine_summary = summaries.get(metric_id)
        sealed_summary = sealed_summaries.get(metric_id)
        if not isinstance(routine_summary, Mapping) or not isinstance(
            sealed_summary, Mapping
        ):
            raise ComparisonContractError(
                "verified_metric_summary_invalid",
                "A verified TEA metric summary is invalid.",
            )
        status = routine_summary.get("status")
        if status not in {"available", "unavailable"}:
            raise ComparisonContractError(
                "verified_metric_status_invalid",
                "A verified TEA metric has an unsupported availability status.",
            )
        percentiles = routine_summary.get("percentiles")
        if not isinstance(percentiles, Mapping) or set(percentiles) != {
            "p5",
            "p50",
            "p95",
        }:
            raise ComparisonContractError(
                "verified_metric_percentiles_invalid",
                "A verified TEA metric has an invalid percentile structure.",
            )
        full_cdf = sealed_summary.get("cdf")
        if status == "available" and not isinstance(full_cdf, Mapping):
            raise ComparisonContractError(
                "verified_metric_cdf_missing",
                "An available verified TEA metric is missing its sealed CDF.",
            )
        if status == "unavailable" and full_cdf is not None:
            raise ComparisonContractError(
                "verified_metric_cdf_invalid",
                "An unavailable verified TEA metric unexpectedly has a CDF.",
            )
        metrics[metric_id] = {
            "metric_id": metric_id,
            "unit": unit,
            "population_semantics": population_semantics,
            "percentile_definition": "hyndman-fan-type-7",
            "cdf_definition": "right-continuous-ties-collapsed",
            "status": status,
            "reason": deepcopy(routine_summary.get("reason")),
            "count": deepcopy(routine_summary.get("count")),
            "percentiles": deepcopy(dict(percentiles)),
            "cdf": deepcopy(dict(full_cdf)) if isinstance(full_cdf, Mapping) else None,
            "traceability": {
                "scenario_revision_id": selection["scenario_revision_id"],
                "tea_job_id": selection["selected_job_id"],
                "attempt_number": selection["selected_attempt_number"],
                "request_sha256": selection["request_sha256"],
                "source_annual_job_id": result_provenance.get(
                    "source_annual_job_id"
                ),
                "source_snapshot_sha256": result.get("source_snapshot_sha256"),
                "routine_result_sha256": result_provenance.get(
                    "routine_result_sha256"
                ),
                "export_manifest_sha256": (
                    (result_provenance.get("exports") or {}).get(
                        "manifest_sha256"
                    )
                    if isinstance(result_provenance.get("exports"), Mapping)
                    else None
                ),
            },
        }
    return metrics


def _project_warnings(result: Mapping[str, Any]) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    if result.get("input_status") == "provisional_inputs":
        warnings.append(
            {
                "code": "provisional_inputs",
                "source": "evidence",
            }
        )
    sensitivity = result.get("sensitivity")
    if isinstance(sensitivity, Mapping):
        for response_id, model in sorted(sensitivity.items()):
            if not isinstance(model, Mapping):
                continue
            for warning in model.get("warnings") or []:
                if isinstance(warning, Mapping):
                    warnings.append(
                        {
                            "code": warning.get("code"),
                            "source": "sensitivity",
                            "response_id": str(response_id),
                            "detail": deepcopy(dict(warning)),
                        }
                    )
    convergence = result.get("convergence")
    if isinstance(convergence, Mapping):
        for reason in convergence.get("reasons") or []:
            warnings.append(
                {
                    "code": str(reason),
                    "source": "convergence",
                }
            )
    return warnings


def _receipt_identity(reference: Mapping[str, Any]) -> dict[str, Any]:
    receipt = reference.get("receipt")
    receipt = receipt if isinstance(receipt, Mapping) else {}
    payload = receipt.get("receipt")
    payload = payload if isinstance(payload, Mapping) else {}
    content = payload.get("content")
    content = content if isinstance(content, Mapping) else {}
    return {
        "request_path": reference.get("request_path"),
        "evidence_receipt_id": (
            reference.get("evidence_receipt_id")
            or reference.get("receipt_id")
        ),
        "receipt_sha256": receipt.get("receipt_sha256"),
        "content_sha256": content.get("sha256"),
    }


def _scenario_evidence_set_sha256(
    scenario_record: Mapping[str, Any] | None,
) -> str:
    references = (
        scenario_record.get("evidence_receipt_refs") or []
        if isinstance(scenario_record, Mapping)
        else []
    )
    identities = [
        _receipt_identity(reference)
        for reference in references
        if isinstance(reference, Mapping)
    ]
    identities.sort(
        key=lambda item: (
            str(item.get("request_path") or ""),
            str(item.get("evidence_receipt_id") or ""),
        )
    )
    return _canonical_sha256(identities)


def _attempt_history_projection(
    selection: Mapping[str, Any],
) -> list[dict[str, Any]]:
    selected_job_id = selection.get("selected_job_id")
    return [
        {
            "tea_job_id": _job_id(job),
            "attempt_number": _attempt_number(job),
            "retry_of_job_id": job.get("retry_of_job_id"),
            "state": job.get("state"),
            "selected_for_comparison": _job_id(job) == selected_job_id,
            "request_sha256": _job_request_sha256(job),
            "source_snapshot_sha256": job.get("source_snapshot_sha256"),
            "result_sha256": (
                _canonical_sha256(job["result"])
                if isinstance(job.get("result"), Mapping)
                else None
            ),
            "result_provenance_sha256": (
                _canonical_sha256(job["result_provenance"])
                if isinstance(job.get("result_provenance"), Mapping)
                else None
            ),
        }
        for job in selection.get("attempt_history") or ()
        if isinstance(job, Mapping)
    ]


def _verification_projection(
    *,
    selection: Mapping[str, Any],
    outcome: ResultVerificationOutcome | None,
) -> dict[str, Any]:
    if selection.get("selection_status") == "missing":
        return {
            "status": "not_applicable",
            "checks": [],
            "failures": [
                {
                    "code": "selected_attempt_missing",
                    "message": "The confirmed scenario has no selected TEA attempt.",
                }
            ],
        }
    state = selection.get("display_status")
    if state != "done":
        return {"status": "not_applicable", "checks": [], "failures": []}
    if outcome is None:
        return {
            "status": "failed",
            "checks": [],
            "failures": [
                {
                    "code": "result_verification_missing",
                    "message": "The completed result was not reverified.",
                }
            ],
        }
    if outcome.tea_job_id != selection.get("selected_job_id"):
        raise ComparisonContractError(
            "verification_attempt_mismatch",
            "A verification outcome belongs to a different TEA attempt.",
        )
    return {
        "status": "verified" if outcome.valid else "failed",
        "checks": deepcopy(list(outcome.checks)),
        "failures": deepcopy(list(outcome.failures)),
    }


def _proof_verification_status(
    *,
    selected: bool,
    state: str,
    outcome: ResultVerificationOutcome | None,
) -> str:
    if not selected:
        return "not_applicable"
    if state in {"queued", "running"}:
        return "pending"
    if state != "done":
        return "not_applicable"
    return "verified" if outcome is not None and outcome.valid else "verification_failed"


def _attempt_proofs(
    *,
    selections: Sequence[Mapping[str, Any]],
    verification_outcomes: Mapping[str, ResultVerificationOutcome],
) -> list[dict[str, Any]]:
    proofs: list[dict[str, Any]] = []
    for selection in selections:
        scenario = selection.get("scenario_record")
        scenario = scenario if isinstance(scenario, Mapping) else None
        evidence_set_sha256 = _scenario_evidence_set_sha256(scenario)
        selected_job_id = selection.get("selected_job_id")
        outcome = (
            verification_outcomes.get(str(selected_job_id))
            if selected_job_id
            else None
        )
        if outcome is not None and outcome.valid:
            assert outcome.verified_result is not None
            if not secrets.compare_digest(
                evidence_set_sha256,
                outcome.verified_result.evidence_set_sha256,
            ):
                raise ComparisonContractError(
                    "verified_evidence_set_digest_mismatch",
                    "The verified evidence set differs from the scenario lock.",
                )
        for history in _attempt_history_projection(selection):
            selected = bool(history["selected_for_comparison"])
            state = str(history["state"])
            if selected and outcome is not None and outcome.valid:
                assert outcome.verified_result is not None
                expected_result_sha256 = _canonical_sha256(
                    outcome.verified_result.result
                )
                expected_provenance_sha256 = _canonical_sha256(
                    outcome.verified_result.result_provenance
                )
                if (
                    history["result_sha256"] != expected_result_sha256
                    or history["result_provenance_sha256"]
                    != expected_provenance_sha256
                ):
                    raise ComparisonContractError(
                        "verified_attempt_payload_digest_mismatch",
                        "The verified payload differs from the selected durable attempt.",
                    )
            proofs.append(
                {
                    "item_index": selection["item_index"],
                    "scenario_revision_id": selection["scenario_revision_id"],
                    "scenario_id": selection["scenario_id"],
                    "scenario_revision": selection["scenario_revision"],
                    "attempt_number": history["attempt_number"],
                    "tea_job_id": history["tea_job_id"],
                    "retry_of_job_id": history["retry_of_job_id"],
                    "selected_for_comparison": selected,
                    "state": state,
                    "verification_status": _proof_verification_status(
                        selected=selected,
                        state=state,
                        outcome=outcome if selected else None,
                    ),
                    "request_sha256": history["request_sha256"],
                    "source_snapshot_sha256": history[
                        "source_snapshot_sha256"
                    ],
                    "result_sha256": history["result_sha256"],
                    "result_provenance_sha256": history[
                        "result_provenance_sha256"
                    ],
                    "evidence_set_sha256": evidence_set_sha256,
                    "reporting_tieout_sha256": (
                        outcome.verified_result.reporting_tieout_sha256
                        if selected and outcome is not None and outcome.valid
                        else None
                    ),
                }
            )
    return proofs


def _project_verified_result(
    *,
    selection: Mapping[str, Any],
    outcome: ResultVerificationOutcome,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    verified = outcome.verified_result
    if not outcome.valid or verified is None:
        raise ComparisonContractError(
            "unverified_result_projection",
            "Only a reverified completed result may supply comparison metrics.",
        )
    result = verified.result
    result_provenance = verified.result_provenance
    metrics = _project_metrics(
        result=result,
        result_provenance=result_provenance,
        sealed_metadata=verified.sealed_metadata,
        selection=selection,
    )
    energy_classes = (result.get("summaries") or {}).get("energy_classes")
    tradeoff_classes = (result.get("summaries") or {}).get("tradeoff_classes")
    result_exports = result.get("exports")
    result_exports = result_exports if isinstance(result_exports, Mapping) else {}
    result_kernel = result_provenance.get("kernel")
    result_kernel = result_kernel if isinstance(result_kernel, Mapping) else {}
    result_projection = {
        "schema_version": result.get("schema_version"),
        "calculation_contract_version": result.get(
            "calculation_contract_version"
        ),
        "sampling_version": result.get("sampling_version"),
        "energy_available": result.get("energy_available"),
        "input_status": result.get("input_status"),
        "metrics": metrics,
        "joint_outcomes": {
            "energy_classes": deepcopy(energy_classes),
            "tradeoff_classes": deepcopy(tradeoff_classes),
        },
        "per_weather_year": deepcopy(result.get("per_weather_year") or []),
        "sensitivity": deepcopy(result.get("sensitivity") or {}),
        "convergence": deepcopy(result.get("convergence") or {}),
        "quality": {
            "reporting_tie_outs": deepcopy(result_exports.get("tie_outs")),
            "reporting_checks": deepcopy(list(verified.reporting_checks)),
            "numerical_provenance": deepcopy(result_kernel.get("numerics")),
        },
        "common_cost_audit": deepcopy(result.get("common_cost_audit") or []),
        "warnings": _project_warnings(result),
    }
    source_projection = {
        "analysis_basis": result.get("analysis_basis"),
        "source_annual_job_id": result_provenance.get("source_annual_job_id"),
        "source_snapshot_sha256": result_provenance.get(
            "source_snapshot_sha256"
        ),
        "source_artifact": deepcopy(result_provenance.get("source_artifact")),
        "capacity_basis": result.get("capacity_basis"),
        "capacities": deepcopy(result.get("capacities") or {}),
        "applied_capacities": deepcopy(result.get("applied_capacities")),
        "commercial_scaling": deepcopy(result.get("commercial_scaling")),
    }
    provenance_projection = {
        "schema_version": result_provenance.get("schema_version"),
        "request_sha256": result_provenance.get("request_sha256"),
        "source_snapshot_sha256": result_provenance.get(
            "source_snapshot_sha256"
        ),
        "submission_provenance_sha256": result_provenance.get(
            "submission_provenance_sha256"
        ),
        "validated_kernel_request_sha256": result_provenance.get(
            "validated_kernel_request_sha256"
        ),
        "routine_result_sha256": result_provenance.get("routine_result_sha256"),
        "sealed_calculation_sha256": (
            (result_provenance.get("sealed_calculation") or {}).get("sha256")
            if isinstance(result_provenance.get("sealed_calculation"), Mapping)
            else None
        ),
        "export_manifest_sha256": (
            (result_provenance.get("exports") or {}).get("manifest_sha256")
            if isinstance(result_provenance.get("exports"), Mapping)
            else None
        ),
        "source_artifact": deepcopy(result_provenance.get("source_artifact")),
        "source_annual_job_id": result_provenance.get(
            "source_annual_job_id"
        ),
        "sealed_calculation": deepcopy(
            result_provenance.get("sealed_calculation")
        ),
        "exports": deepcopy(result_provenance.get("exports")),
        "kernel": deepcopy(result_provenance.get("kernel")),
        "kernel_numerics": deepcopy(
            (result_provenance.get("kernel") or {}).get("numerics")
            if isinstance(result_provenance.get("kernel"), Mapping)
            else None
        ),
        "reporting_tie_outs": deepcopy(result_exports.get("tie_outs")),
        "reporting_tieout_sha256": verified.reporting_tieout_sha256,
        "evidence_set_sha256": verified.evidence_set_sha256,
    }
    return result_projection, source_projection, provenance_projection


def _pointer_lookup(payload: Any, pointer: str) -> tuple[bool, Any]:
    if pointer == "/":
        return True, deepcopy(payload)
    current = payload
    for raw in pointer.split("/")[1:]:
        token = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(current, Mapping):
            if token not in current:
                return False, None
            current = current[token]
        elif isinstance(current, list):
            try:
                index = int(token)
            except ValueError:
                return False, None
            if index < 0 or index >= len(current):
                return False, None
            current = current[index]
        else:
            return False, None
    return True, deepcopy(current)


def _request_matrix(
    selections: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    available = [
        selection
        for selection in selections
        if isinstance(selection.get("scenario_record"), Mapping)
        and isinstance(selection["scenario_record"].get("request"), Mapping)
    ]
    if not available:
        return []
    baseline = next(
        (
            selection
            for selection in available
            if selection["scenario_record"].get("kind") == "baseline"
        ),
        available[0],
    )
    public_requests: dict[str, Mapping[str, Any]] = {}
    for selection in available:
        raw_request = selection["scenario_record"]["request"]
        public_request = autonomy_serializers.exact_public_value(
            deepcopy(raw_request)
        )
        if not isinstance(public_request, Mapping):
            raise ComparisonContractError(
                "comparison_request_projection_invalid",
                "A scenario request could not be projected as public JSON.",
            )
        public_requests[str(selection["scenario_revision_id"])] = public_request
    baseline_request = public_requests[str(baseline["scenario_revision_id"])]
    paths: set[str] = set()
    for selection in available:
        if selection is baseline:
            continue
        paths.update(
            row["path"]
            for row in _json_pointer_leaf_diff(
                baseline_request,
                public_requests[str(selection["scenario_revision_id"])],
            )
        )
    rows: list[dict[str, Any]] = []
    for path in sorted(paths):
        values: list[dict[str, Any]] = []
        canonical_values: set[str] = set()
        for selection in selections:
            request = public_requests.get(str(selection["scenario_revision_id"]))
            present, value = (
                _pointer_lookup(request, path)
                if isinstance(request, Mapping)
                else (False, None)
            )
            values.append(
                {
                    "scenario_revision_id": selection["scenario_revision_id"],
                    "present": present,
                    "value": value,
                }
            )
            canonical_values.add(
                _canonical_json_text({"present": present, "value": value})
            )
        rows.append(
            {
                "json_pointer": path,
                "values": values,
                "distinct_canonical_values": len(canonical_values),
            }
        )
    return rows


def _metric_matrix(scenarios: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    metric_ids = sorted(
        {
            metric_id
            for scenario in scenarios
            for metric_id in (
                (scenario.get("result") or {}).get("metrics") or {}
            )
        }
    )
    rows: list[dict[str, Any]] = []
    for metric_id in metric_ids:
        units = {
            metric.get("unit")
            for scenario in scenarios
            for candidate_id, metric in (
                ((scenario.get("result") or {}).get("metrics") or {}).items()
            )
            if candidate_id == metric_id and isinstance(metric, Mapping)
        }
        semantics = {
            metric.get("population_semantics")
            for scenario in scenarios
            for candidate_id, metric in (
                ((scenario.get("result") or {}).get("metrics") or {}).items()
            )
            if candidate_id == metric_id and isinstance(metric, Mapping)
        }
        values: list[dict[str, Any]] = []
        for scenario in scenarios:
            metric = (
                ((scenario.get("result") or {}).get("metrics") or {}).get(metric_id)
            )
            if isinstance(metric, Mapping):
                values.append(
                    {
                        "scenario_revision_id": scenario["scenario_revision_id"],
                        "status": metric.get("status"),
                        "reason": metric.get("reason"),
                        "count": metric.get("count"),
                        "percentiles": deepcopy(metric.get("percentiles")),
                    }
                )
            else:
                values.append(
                    {
                        "scenario_revision_id": scenario["scenario_revision_id"],
                        "status": "unavailable",
                        "reason": scenario["attempt"]["display_status"],
                        "count": None,
                        "percentiles": {"p5": None, "p50": None, "p95": None},
                    }
                )
        rows.append(
            {
                "metric_id": metric_id,
                "unit": next(iter(units)) if len(units) == 1 else None,
                "population_semantics": (
                    next(iter(semantics)) if len(semantics) == 1 else None
                ),
                "values": values,
            }
        )
    return rows


def _compatibility(scenarios: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    verified = [scenario for scenario in scenarios if scenario.get("result")]
    for field, values in (
        (
            "analysis_basis",
            {scenario["source"].get("analysis_basis") for scenario in verified},
        ),
        (
            "source_snapshot_sha256",
            {
                scenario["source"].get("source_snapshot_sha256")
                for scenario in verified
            },
        ),
        (
            "calculation_contract_version",
            {
                scenario["result"].get("calculation_contract_version")
                for scenario in verified
            },
        ),
        (
            "sampling_version",
            {scenario["result"].get("sampling_version") for scenario in verified},
        ),
    ):
        if len(values) > 1:
            blockers.append(
                {
                    "code": f"incompatible_{field}",
                    "field": field,
                }
            )
    return {
        "status": "compatible" if not blockers else "blocked",
        "blockers": blockers,
    }


def build_comparison_bundle(
    *,
    case_record: Mapping[str, Any],
    confirmation_record: Mapping[str, Any],
    scenario_records: Sequence[Mapping[str, Any]],
    verification_outcomes: Mapping[str, ResultVerificationOutcome],
) -> dict[str, Any]:
    """Build one canonical, deterministic, decision-safe comparison snapshot."""

    case_id = _record_id(case_record, "id", "case_id")
    confirmation_id = _record_id(
        confirmation_record, "id", "confirmation_id"
    )
    if not case_id or confirmation_record.get("case_id") != case_id:
        raise ComparisonContractError(
            "comparison_case_mismatch",
            "The confirmation does not belong to the selected decision case.",
        )
    _validate_confirmation_authority(
        case_record=case_record,
        confirmation_record=confirmation_record,
        scenario_records=scenario_records,
    )
    selections = select_confirmation_attempts(
        confirmation_record=confirmation_record,
        scenario_records=scenario_records,
    )
    scenarios: list[dict[str, Any]] = []
    blockers: list[dict[str, Any]] = []
    verified_count = 0
    for selection in selections:
        selected_job_id = selection.get("selected_job_id")
        outcome = (
            verification_outcomes.get(str(selected_job_id))
            if selected_job_id
            else None
        )
        verification = _verification_projection(
            selection=selection,
            outcome=outcome,
        )
        display_status = str(selection.get("display_status"))
        if display_status == "done" and verification["status"] != "verified":
            display_status = "verification_failed"
        scenario = selection.get("scenario_record")
        scenario = scenario if isinstance(scenario, Mapping) else {}
        selected_job = selection.get("selected_job")
        selected_job = selected_job if isinstance(selected_job, Mapping) else {}
        result_projection = None
        source_projection = {
            "analysis_basis": scenario.get("analysis_basis"),
            "source_annual_job_id": scenario.get("source_annual_job_id"),
            "source_snapshot_sha256": scenario.get("source_snapshot_sha256"),
            "source_artifact": None,
            "capacity_basis": None,
            "capacities": {},
            "applied_capacities": None,
            "commercial_scaling": None,
        }
        provenance_projection = None
        verified_evidence: list[dict[str, Any]] = []
        evidence_set_sha256 = _scenario_evidence_set_sha256(
            scenario if scenario else None
        )
        if outcome is not None and outcome.valid:
            result_projection, source_projection, provenance_projection = (
                _project_verified_result(selection=selection, outcome=outcome)
            )
            verified_count += 1
            assert outcome.verified_result is not None
            evidence_set_sha256 = outcome.verified_result.evidence_set_sha256
            verified_evidence = [
                {
                    "request_path": receipt.get("request_path"),
                    "evidence_receipt_id": receipt.get("evidence_receipt_id"),
                    "receipt_sha256": receipt.get("receipt_sha256"),
                    "content_sha256": receipt.get("content_sha256"),
                    "evidence_class": receipt.get("evidence_class"),
                }
                for receipt in outcome.verified_result.evidence_receipts
            ]
        else:
            verified_evidence = [
                _receipt_identity(reference)
                for reference in scenario.get("evidence_receipt_refs") or []
                if isinstance(reference, Mapping)
            ]
        scenario_projection = {
            "scenario_id": selection["scenario_id"],
            "scenario_revision_id": selection["scenario_revision_id"],
            "ordinal": selection["item_index"],
            "label": autonomy_serializers.scrub_public_text(
                scenario.get("label"), limit=200
            ),
            "kind": scenario.get("kind"),
            "request_sha256": selection["request_sha256"],
            "attempt": {
                "tea_job_id": selection.get("selected_job_id"),
                "attempt_number": selection.get("selected_attempt_number"),
                "retry_of_job_id": selected_job.get("retry_of_job_id"),
                "durable_state": selected_job.get("state"),
                "display_status": display_status,
                "terminal": selected_job.get("state") in _TERMINAL_STATES,
                "selected_by_explicit_link": bool(
                    selection.get("selection_status") == "selected"
                ),
            },
            "attempt_history": _attempt_history_projection(selection),
            "verification": verification,
            "request": autonomy_serializers.exact_public_value(
                deepcopy(scenario.get("request") or selected_job.get("request") or {})
            ),
            "source": source_projection,
            "evidence": {
                "status": (
                    result_projection.get("input_status")
                    if isinstance(result_projection, Mapping)
                    else "unverified"
                ),
                "receipts": verified_evidence,
                "evidence_set_sha256": evidence_set_sha256,
                "evidence_class_counts": (
                    deepcopy(
                        (outcome.verified_result.result or {}).get(
                            "evidence_class_counts"
                        )
                    )
                    if outcome is not None and outcome.valid
                    else {}
                ),
                "gaps": deepcopy(verification.get("failures") or []),
            },
            "result": result_projection,
            "provenance": provenance_projection,
        }
        scenarios.append(scenario_projection)
        if result_projection is None:
            blockers.append(
                {
                    "code": f"scenario_{display_status}",
                    "scenario_revision_id": selection["scenario_revision_id"],
                }
            )

    compatibility = _compatibility(scenarios)
    blockers.extend(deepcopy(compatibility["blockers"]))
    is_complete = bool(scenarios) and verified_count == len(scenarios) and not blockers
    attempt_proofs = _attempt_proofs(
        selections=selections,
        verification_outcomes=verification_outcomes,
    )
    bundle: dict[str, Any] = {
        "schema_version": COMPARISON_BUNDLE_SCHEMA_VERSION,
        "is_complete": is_complete,
        # No approved contract maps existing TEA outputs to a winner/confidence.
        "recommendation_eligible": False,
        "case": {
            "case_id": case_id,
            "expected_case_revision": case_record.get("revision"),
        },
        "confirmation": {
            "confirmation_id": confirmation_id,
            "receipt_sha256": confirmation_record.get("receipt_sha256"),
            "confirmation_request_sha256": confirmation_record.get(
                "confirmation_request_sha256"
            ),
            "case_revision_before": confirmation_record.get(
                "expected_case_revision"
            ),
            "case_revision_after": confirmation_record.get(
                "case_revision_after"
            ),
            "confirmed_at": confirmation_record.get("confirmed_at"),
            "ordered_scenario_revision_ids": [
                selection["scenario_revision_id"] for selection in selections
            ],
        },
        "selection_contract": ATTEMPT_SELECTION_CONTRACT_VERSION,
        "completeness": {
            "status": "complete" if is_complete else "partial",
            "selected_count": len(scenarios),
            "verified_done_count": verified_count,
            "blockers": blockers,
        },
        "attempt_proofs": attempt_proofs,
        "scenarios": scenarios,
        "comparison": {
            "request_matrix": _request_matrix(selections),
            "metric_matrix": _metric_matrix(scenarios),
            "compatibility": compatibility,
        },
        "recommendation": {
            "state": CLASSIFICATION_PENDING_CONTRACT,
            "classification": None,
            "confidence": None,
            "contract_version": None,
            "blockers": ["recommendation_threshold_contract_missing"],
            "decisive_evidence": [],
            "major_drivers": [],
            "important_uncertainty": [],
            "evidence_gaps": [],
            "model_limitations": [],
            "reversal_conditions": [],
        },
        "canonicalization": {
            "version": CANONICALIZATION_VERSION,
            "algorithm": "sha256",
            "encoding": "utf-8",
            "json": "sort_keys-compact-no_nan-ascii",
            "excluded_fields": ["bundle_hash"],
        },
    }
    # The public-safety projection is part of the versioned snapshot contract,
    # not a lossy serializer pass performed after hashing.  This makes the exact
    # browser-visible CDFs, provenance, missingness, and metric values hash-tied.
    bundle = autonomy_serializers.exact_public_comparison_bundle(bundle)
    bundle["bundle_hash"] = canonical_comparison_bundle_sha256(bundle)
    return bundle


__all__ = [
    "ATTEMPT_SELECTION_CONTRACT_VERSION",
    "CANONICALIZATION_VERSION",
    "CLASSIFICATION_PENDING_CONTRACT",
    "COMPARISON_BUNDLE_SCHEMA_VERSION",
    "ComparisonContractError",
    "build_comparison_bundle",
    "canonical_comparison_bundle_sha256",
    "select_confirmation_attempts",
]
