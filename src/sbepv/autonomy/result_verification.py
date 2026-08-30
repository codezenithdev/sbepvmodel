"""Read-only admission verification for completed Autonomy TEA attempts.

The TEA worker already seals a complete calculation payload and proves its public
exports before a job may become ``done``.  A Decision Brief is a later consumer of
those immutable bytes, so it must repeat the proof without running the numerical
kernel and without writing a second export set.  This module deliberately keeps
that I/O-bound verification separate from the pure comparison projection in
``sbepv.autonomy.comparison``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
import re
import secrets
from typing import Any, Literal

from sbepv import technoeconomic as technoeconomic_kernel
from sbepv import technoeconomic_reporting
from sbepv.api import config
from sbepv.api import technoeconomic as technoeconomic_api
from sbepv.autonomy import scenarios as autonomy_scenarios
from sbepv.worker import run_technoeconomic


RESULT_VERIFICATION_SCHEMA_VERSION = "autonomy-result-verification-v1"

_SHA256_RE = re.compile(r"[0-9a-f]{64}", re.ASCII)
_TERMINAL_STATES = frozenset({"done", "error", "cancelled", "interrupted"})


@dataclass(frozen=True)
class VerifiedTechnoeconomicResult:
    """Private verified authority passed to pure bundle assembly."""

    tea_job_id: str
    result: Mapping[str, Any]
    result_provenance: Mapping[str, Any]
    sealed_metadata: Mapping[str, Any]
    reporting_checks: tuple[Mapping[str, Any], ...]
    evidence_receipts: tuple[Mapping[str, Any], ...]
    evidence_set_sha256: str
    reporting_tieout_sha256: str


@dataclass(frozen=True)
class ResultVerificationOutcome:
    """Structured fail-closed outcome for one selected completed attempt."""

    status: Literal["verified", "verification_failed"]
    tea_job_id: str
    checks: tuple[Mapping[str, Any], ...]
    failures: tuple[Mapping[str, Any], ...]
    verified_result: VerifiedTechnoeconomicResult | None

    @property
    def valid(self) -> bool:
        return self.status == "verified" and self.verified_result is not None


class _VerificationFailure(ValueError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: Sequence[Mapping[str, Any]] = (),
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = tuple(deepcopy(list(details)))


def _record_id(record: Mapping[str, Any], *names: str) -> str:
    for name in names:
        value = record.get(name)
        if isinstance(value, str) and value:
            return value
    return ""


def _digest(value: Any) -> str:
    return technoeconomic_api.canonical_json_sha256(value)


def _require_digest(value: Any, *, code: str, message: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise _VerificationFailure(code, message)
    return value


def _require_equal(
    actual: Any,
    expected: Any,
    *,
    code: str,
    message: str,
    digest: bool = False,
) -> None:
    matches = actual == expected
    if digest and isinstance(actual, str) and isinstance(expected, str):
        matches = secrets.compare_digest(actual, expected)
    if not matches:
        raise _VerificationFailure(code, message)


def _failure_outcome(
    *,
    tea_job_id: str,
    checks: list[dict[str, Any]],
    failure: _VerificationFailure,
) -> ResultVerificationOutcome:
    checks.append({"code": failure.code, "status": "failed"})
    item: dict[str, Any] = {
        "code": failure.code,
        "message": failure.message,
    }
    if failure.details:
        item["details"] = [deepcopy(dict(detail)) for detail in failure.details]
    return ResultVerificationOutcome(
        status="verification_failed",
        tea_job_id=tea_job_id,
        checks=tuple(checks),
        failures=(item,),
        verified_result=None,
    )


def _pass(checks: list[dict[str, Any]], code: str) -> None:
    checks.append({"code": code, "status": "passed"})


def _confirmation_authority(
    *,
    case_record: Mapping[str, Any],
    confirmation_record: Mapping[str, Any],
    confirmation_item: Mapping[str, Any],
    scenario_record: Mapping[str, Any],
    job_record: Mapping[str, Any],
) -> tuple[str, str, str]:
    case_id = _record_id(case_record, "id", "case_id")
    confirmation_id = _record_id(
        confirmation_record, "id", "confirmation_id"
    )
    scenario_revision_id = _record_id(
        scenario_record, "scenario_revision_id"
    )
    tea_job_id = _record_id(job_record, "id", "tea_job_id")
    if not all((case_id, confirmation_id, scenario_revision_id, tea_job_id)):
        raise _VerificationFailure(
            "comparison_identity_missing",
            "The comparison authority is missing a durable identity.",
        )
    request_payload = confirmation_record.get("confirmation_request")
    request_sha256 = _require_digest(
        confirmation_record.get("confirmation_request_sha256"),
        code="confirmation_request_digest_invalid",
        message="The confirmation request SHA-256 is invalid.",
    )
    if not isinstance(request_payload, Mapping) or not secrets.compare_digest(
        _digest(request_payload), request_sha256
    ):
        raise _VerificationFailure(
            "confirmation_request_digest_mismatch",
            "The confirmation request does not match its immutable SHA-256.",
        )

    receipt = confirmation_record.get("receipt")
    receipt_sha256 = _require_digest(
        confirmation_record.get("receipt_sha256"),
        code="confirmation_receipt_digest_invalid",
        message="The confirmation receipt SHA-256 is invalid.",
    )
    if not isinstance(receipt, Mapping) or not secrets.compare_digest(
        _digest(receipt), receipt_sha256
    ):
        raise _VerificationFailure(
            "confirmation_receipt_digest_mismatch",
            "The confirmation receipt does not match its immutable SHA-256.",
        )

    raw_items = confirmation_record.get("items")
    if not isinstance(raw_items, Sequence) or isinstance(
        raw_items, (str, bytes, bytearray)
    ):
        raise _VerificationFailure(
            "confirmation_item_mismatch",
            "The confirmation does not contain durable scenario items.",
        )
    items = [item for item in raw_items if isinstance(item, Mapping)]
    if not items or len(items) != len(raw_items):
        raise _VerificationFailure(
            "confirmation_item_mismatch",
            "The confirmation does not contain durable scenario items.",
        )
    try:
        ordered_items = sorted(items, key=lambda item: int(item.get("item_index")))
    except (TypeError, ValueError):
        ordered_items = []
    if [item.get("item_index") for item in ordered_items] != list(
        range(len(items))
    ):
        raise _VerificationFailure(
            "confirmation_item_mismatch",
            "The confirmation scenario item identities are invalid.",
        )

    def _item_identity(item: Mapping[str, Any]) -> tuple[Any, ...]:
        return (
            item.get("item_index"),
            item.get("scenario_id"),
            item.get("scenario_revision_id"),
            item.get("scenario_revision"),
            item.get("request_sha256"),
            item.get("tea_job_id") or item.get("job_id"),
        )

    selected_identity = _item_identity(confirmation_item)
    matching_items = [
        item for item in ordered_items if _item_identity(item) == selected_identity
    ]
    if len(matching_items) != 1:
        raise _VerificationFailure(
            "confirmation_item_mismatch",
            "The selected scenario does not have one exact confirmation item.",
        )
    durable_item = matching_items[0]
    durable_request_sha256 = _require_digest(
        durable_item.get("request_sha256"),
        code="confirmation_item_mismatch",
        message="The selected confirmation item request identity is invalid.",
    )
    scenario_revision = scenario_record.get("revision")
    if scenario_revision is None:
        scenario_revision = scenario_record.get("scenario_revision")
    if (
        confirmation_record.get("case_id") != case_id
        or scenario_record.get("case_id") != case_id
        or scenario_record.get("confirmation_id") != confirmation_id
        or _record_id(scenario_record, "scenario_id", "id")
        != durable_item.get("scenario_id")
        or scenario_revision != durable_item.get("scenario_revision")
        or scenario_revision_id != durable_item.get("scenario_revision_id")
        or scenario_record.get("request_sha256") != durable_request_sha256
    ):
        raise _VerificationFailure(
            "confirmation_scope_mismatch",
            "The completed result is outside the immutable confirmation scope.",
        )

    scenario_jobs = scenario_record.get("jobs")
    if not isinstance(scenario_jobs, Sequence) or isinstance(
        scenario_jobs, (str, bytes, bytearray)
    ):
        raise _VerificationFailure(
            "confirmation_scope_mismatch",
            "The confirmed retry history is unavailable.",
        )
    jobs = [job for job in scenario_jobs if isinstance(job, Mapping)]
    job_ids = [_record_id(job, "id", "tea_job_id") for job in jobs]
    initial_job_id = str(
        durable_item.get("tea_job_id") or durable_item.get("job_id") or ""
    )
    if (
        len(jobs) != len(scenario_jobs)
        or not jobs
        or not all(job_ids)
        or len(set(job_ids)) != len(job_ids)
        or job_ids[0] != initial_job_id
        or tea_job_id not in job_ids
    ):
        raise _VerificationFailure(
            "confirmation_scope_mismatch",
            "The completed result is outside the confirmed retry history.",
        )

    request_scenarios = request_payload.get("scenarios")
    if not isinstance(request_scenarios, Sequence) or isinstance(
        request_scenarios, (str, bytes, bytearray)
    ):
        request_scenarios = ()
    if (
        request_payload.get("schema_version") != 1
        or request_payload.get("case_id") != case_id
        or request_payload.get("expected_case_revision")
        != confirmation_record.get("expected_case_revision")
        or len(request_scenarios) != len(ordered_items)
    ):
        raise _VerificationFailure(
            "confirmation_request_identity_mismatch",
            "The confirmation request does not identify its durable confirmation.",
        )
    for request_scenario, item in zip(
        request_scenarios, ordered_items, strict=True
    ):
        item_job = item.get("job")
        if not isinstance(request_scenario, Mapping) or not isinstance(
            item_job, Mapping
        ):
            raise _VerificationFailure(
                "confirmation_request_identity_mismatch",
                "The confirmation request scenario authority is incomplete.",
            )
        for actual, expected in (
            (request_scenario.get("scenario_revision_id"), item.get("scenario_revision_id")),
            (request_scenario.get("expected_revision"), item.get("scenario_revision")),
            (request_scenario.get("request_sha256"), item.get("request_sha256")),
            (request_scenario.get("source_annual_job_id"), item_job.get("source_annual_job_id")),
            (
                request_scenario.get("source_artifact_sha256"),
                item_job.get("source_artifact_sha256"),
            ),
            (request_scenario.get("source_artifact_bytes"), item_job.get("source_artifact_bytes")),
            (
                request_scenario.get("source_snapshot_sha256"),
                item_job.get("source_snapshot_sha256"),
            ),
            (
                request_scenario.get("submission_provenance_sha256"),
                item_job.get("submission_provenance_sha256"),
            ),
        ):
            if actual != expected:
                raise _VerificationFailure(
                    "confirmation_request_identity_mismatch",
                    "The confirmation request scenario identities do not match its durable items.",
                )

    receipt_scenarios = receipt.get("scenarios")
    if not isinstance(receipt_scenarios, Sequence) or isinstance(
        receipt_scenarios, (str, bytes, bytearray)
    ):
        receipt_scenarios = ()
    if (
        receipt.get("schema_version") != 1
        or receipt.get("confirmation_id") != confirmation_id
        or receipt.get("case_id") != case_id
        or receipt.get("case_revision_before")
        != confirmation_record.get("expected_case_revision")
        or receipt.get("case_revision_after")
        != confirmation_record.get("case_revision_after")
    ):
        raise _VerificationFailure(
            "confirmation_receipt_identity_mismatch",
            "The confirmation receipt does not identify its durable confirmation.",
        )
    source_lock = receipt.get("source_lock")
    selected_item_job = durable_item.get("job")
    job_request = job_record.get("request")
    job_analysis_basis = (
        job_request.get("analysis_basis", job_request.get("basis"))
        if isinstance(job_request, Mapping)
        else None
    )
    if not isinstance(source_lock, Mapping) or not isinstance(
        selected_item_job, Mapping
    ):
        raise _VerificationFailure(
            "confirmation_receipt_source_lock_mismatch",
            "The confirmation receipt source lock is incomplete.",
        )
    selected_request_scenario = request_scenarios[
        int(durable_item["item_index"])
    ]
    if not isinstance(selected_request_scenario, Mapping):
        raise _VerificationFailure(
            "confirmation_request_identity_mismatch",
            "The selected confirmation request scenario is invalid.",
        )
    for field in (
        "source_annual_job_id",
        "source_artifact_sha256",
        "source_artifact_bytes",
        "source_snapshot_sha256",
        "submission_provenance_sha256",
    ):
        expected = selected_request_scenario.get(field)
        if selected_item_job.get(field) != expected or job_record.get(field) != expected:
            raise _VerificationFailure(
                "confirmation_selected_job_identity_mismatch",
                (
                    "The selected TEA attempt differs from the immutable "
                    "confirmation request."
                ),
            )
    for actual, expected in (
        (source_lock.get("source_annual_job_id"), case_record.get("source_annual_job_id")),
        (source_lock.get("source_annual_job_id"), scenario_record.get("source_annual_job_id")),
        (source_lock.get("source_annual_job_id"), job_record.get("source_annual_job_id")),
        (source_lock.get("source_annual_job_id"), selected_item_job.get("source_annual_job_id")),
        (source_lock.get("source_snapshot_sha256"), case_record.get("source_snapshot_sha256")),
        (source_lock.get("source_snapshot_sha256"), scenario_record.get("source_snapshot_sha256")),
        (source_lock.get("source_snapshot_sha256"), job_record.get("source_snapshot_sha256")),
        (
            source_lock.get("source_snapshot_sha256"),
            selected_item_job.get("source_snapshot_sha256"),
        ),
        (source_lock.get("analysis_basis"), case_record.get("analysis_basis")),
        (source_lock.get("analysis_basis"), scenario_record.get("analysis_basis")),
        (source_lock.get("analysis_basis"), job_analysis_basis),
    ):
        if actual != expected:
            raise _VerificationFailure(
                "confirmation_receipt_source_lock_mismatch",
                "The confirmation receipt source lock differs from frozen authority.",
            )
    for request_scenario in request_scenarios:
        if not isinstance(request_scenario, Mapping):
            raise _VerificationFailure(
                "confirmation_receipt_source_lock_mismatch",
                "The confirmation request source identity is invalid.",
            )
        if (
            request_scenario.get("source_annual_job_id")
            != source_lock.get("source_annual_job_id")
            or request_scenario.get("source_snapshot_sha256")
            != source_lock.get("source_snapshot_sha256")
        ):
            raise _VerificationFailure(
                "confirmation_receipt_source_lock_mismatch",
                "The confirmation receipt source lock differs from its request.",
            )
    if len(receipt_scenarios) != len(ordered_items):
        raise _VerificationFailure(
            "confirmation_receipt_items_mismatch",
            "The confirmation receipt scenario membership is incomplete.",
        )
    for receipt_scenario, item in zip(
        receipt_scenarios, ordered_items, strict=True
    ):
        if not isinstance(receipt_scenario, Mapping):
            raise _VerificationFailure(
                "confirmation_receipt_items_mismatch",
                "The confirmation receipt scenario membership is invalid.",
            )
        for actual, expected in (
            (receipt_scenario.get("scenario_id"), item.get("scenario_id")),
            (receipt_scenario.get("scenario_revision_id"), item.get("scenario_revision_id")),
            (receipt_scenario.get("scenario_revision"), item.get("scenario_revision")),
            (receipt_scenario.get("request_sha256"), item.get("request_sha256")),
            (receipt_scenario.get("tea_job_id"), item.get("tea_job_id")),
        ):
            if actual != expected:
                raise _VerificationFailure(
                    "confirmation_receipt_items_mismatch",
                    "The confirmation receipt scenario membership differs from durable items.",
                )

    receipt_selected = receipt_scenarios[int(durable_item["item_index"])]
    scenario_evidence_refs = scenario_record.get("evidence_receipt_refs") or []
    if not isinstance(scenario_evidence_refs, Sequence) or isinstance(
        scenario_evidence_refs, (str, bytes, bytearray)
    ):
        scenario_evidence_refs = ()
    normalized_scenario_evidence_refs = [
        {
            "request_path": reference.get("request_path"),
            "evidence_receipt_id": reference.get("evidence_receipt_id"),
        }
        for reference in scenario_evidence_refs
        if isinstance(reference, Mapping)
    ]
    if (
        receipt_selected.get("kind") != scenario_record.get("kind")
        or receipt_selected.get("evidence_receipt_refs")
        != normalized_scenario_evidence_refs
        or len(normalized_scenario_evidence_refs) != len(scenario_evidence_refs)
    ):
        raise _VerificationFailure(
            "confirmation_receipt_items_mismatch",
            "The selected receipt scenario differs from its immutable scenario revision.",
        )
    return case_id, confirmation_id, tea_job_id


def _evidence_set_payload(
    receipts: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    return [
        {
            "request_path": item.get("request_path"),
            "evidence_receipt_id": item.get("evidence_receipt_id"),
            "receipt_sha256": item.get("receipt_sha256"),
            "content_sha256": item.get("content_sha256"),
        }
        for item in sorted(
            receipts,
            key=lambda item: (
                str(item.get("request_path") or ""),
                str(item.get("evidence_receipt_id") or ""),
            ),
        )
    ]


def _attempt_directory(
    tea_job_id: str,
    artifact: Mapping[str, Any],
) -> tuple[Path, Path, str]:
    storage_key = artifact.get("storage_key")
    if (
        not isinstance(storage_key, str)
        or not storage_key
        or "\\" in storage_key
    ):
        raise _VerificationFailure(
            "sealed_calculation_identity_invalid",
            "The sealed calculation storage identity is invalid.",
        )
    candidate = config.OUTPUT_DIR / Path(storage_key)
    try:
        sealed_path = candidate.resolve(strict=True)
        output_directory = config.OUTPUT_DIR.resolve(strict=True)
        relative = sealed_path.relative_to(output_directory)
    except (FileNotFoundError, OSError, RuntimeError, ValueError) as exc:
        raise _VerificationFailure(
            "sealed_calculation_unavailable",
            "The sealed calculation payload is unavailable.",
        ) from exc
    if (
        len(relative.parts) < 4
        or sealed_path.name != run_technoeconomic.SEALED_CALCULATION_FILENAME
    ):
        raise _VerificationFailure(
            "sealed_calculation_identity_invalid",
            "The sealed calculation storage identity is invalid.",
        )
    attempt_directory = sealed_path.parent
    if attempt_directory.parent.name != tea_job_id:
        raise _VerificationFailure(
            "sealed_calculation_job_mismatch",
            "The sealed calculation belongs to a different TEA job.",
        )
    return attempt_directory, sealed_path, attempt_directory.name


def _verify_numerical_provenance(
    kernel_provenance: Mapping[str, Any],
    *,
    calculation_contract_version: Any,
    sampling_version: Any,
) -> None:
    _require_equal(
        kernel_provenance.get("calculation_contract_version"),
        calculation_contract_version,
        code="kernel_contract_provenance_mismatch",
        message="Kernel provenance names a different calculation contract.",
    )
    _require_equal(
        kernel_provenance.get("sampling_version"),
        sampling_version,
        code="kernel_sampling_provenance_mismatch",
        message="Kernel provenance names a different sampling contract.",
    )
    numerics = kernel_provenance.get("numerics")
    if not isinstance(numerics, Mapping):
        raise _VerificationFailure(
            "numerical_provenance_missing",
            "The completed result has no numerical provenance.",
        )
    _require_equal(
        numerics.get("contract_version"),
        technoeconomic_kernel.NUMERICAL_CONTRACT_VERSION,
        code="numerical_contract_mismatch",
        message="The completed result names an unsupported numerical contract.",
    )
    _require_equal(
        numerics.get("probe_digests"),
        technoeconomic_kernel.NUMERICAL_PROBE_DIGESTS,
        code="numerical_probe_digest_mismatch",
        message="The completed result did not pass the approved numerical probes.",
    )
    for field in (
        "exactness_digest",
        "reference_exactness_digest",
    ):
        _require_digest(
            numerics.get(field),
            code="numerical_exactness_digest_invalid",
            message="The numerical exactness provenance is invalid.",
        )
    if not isinstance(numerics.get("bit_identical_to_reference"), bool):
        raise _VerificationFailure(
            "numerical_exactness_status_invalid",
            "The numerical exactness status is invalid.",
        )


def verify_completed_technoeconomic_result(
    *,
    case_record: Mapping[str, Any],
    confirmation_record: Mapping[str, Any],
    confirmation_item: Mapping[str, Any],
    scenario_record: Mapping[str, Any],
    job_record: Mapping[str, Any],
    evidence_receipt_loader: Callable[[str], Mapping[str, Any] | None],
    evidence_snapshot_loader: Callable[
        [str, str], tuple[bytes, Mapping[str, Any]]
    ],
) -> ResultVerificationOutcome:
    """Reverify one explicitly selected ``done`` result without recalculation.

    All expected verification failures are returned as stable structured status;
    no source snapshot, path, lease, or raw artifact identity is included in that
    public-safe status.  The successful ``verified_result`` remains an internal
    authority object for :func:`sbepv.autonomy.comparison.build_comparison_bundle`.
    """

    tea_job_id = _record_id(job_record, "id", "tea_job_id")
    checks: list[dict[str, Any]] = []
    try:
        case_id, confirmation_id, tea_job_id = _confirmation_authority(
            case_record=case_record,
            confirmation_record=confirmation_record,
            confirmation_item=confirmation_item,
            scenario_record=scenario_record,
            job_record=job_record,
        )
        _pass(checks, "confirmation_scope_verified")

        if job_record.get("state") != "done":
            state = str(job_record.get("state") or "missing")
            if state not in _TERMINAL_STATES | {"queued", "running"}:
                state = "missing"
            raise _VerificationFailure(
                "completed_result_required",
                f"A {state} attempt cannot be admitted as a completed result.",
            )

        request_payload = job_record.get("request")
        source_snapshot = job_record.get("source_snapshot")
        submission_provenance = job_record.get("submission_provenance")
        result = job_record.get("result")
        result_provenance = job_record.get("result_provenance")
        artifacts = job_record.get("artifacts")
        if not all(
            isinstance(value, Mapping)
            for value in (
                request_payload,
                source_snapshot,
                submission_provenance,
                result,
                result_provenance,
                artifacts,
            )
        ):
            raise _VerificationFailure(
                "completed_result_payload_incomplete",
                "The completed result is missing immutable authority fields.",
            )

        request_sha256 = _digest(request_payload)
        expected_request_sha256 = _require_digest(
            confirmation_item.get("request_sha256"),
            code="request_digest_invalid",
            message="The confirmed request SHA-256 is invalid.",
        )
        for actual in (
            scenario_record.get("request_sha256"),
            submission_provenance.get("request_sha256"),
            result_provenance.get("request_sha256"),
        ):
            _require_equal(
                actual,
                expected_request_sha256,
                code="request_digest_mismatch",
                message="The completed result request differs from confirmation.",
                digest=True,
            )
        _require_equal(
            request_sha256,
            expected_request_sha256,
            code="request_digest_mismatch",
            message="The completed result request differs from confirmation.",
            digest=True,
        )
        _pass(checks, "request_identity_verified")

        evidence_result = autonomy_scenarios.verify_accepted_evidence_references(
            case_id=case_id,
            request_payload=request_payload,
            evidence_references=scenario_record.get("evidence_receipt_refs") or [],
            receipt_loader=evidence_receipt_loader,
            evidence_snapshot_loader=evidence_snapshot_loader,
        )
        if not evidence_result.get("valid"):
            details = evidence_result.get("field_errors") or []
            raise _VerificationFailure(
                "accepted_evidence_verification_failed",
                "The accepted evidence set failed immutable verification.",
                details=[
                    {
                        "path": item.get("path"),
                        "code": item.get("code"),
                        "message": item.get("message"),
                    }
                    for item in details
                    if isinstance(item, Mapping)
                ],
            )
        verified_evidence = tuple(
            deepcopy(list(evidence_result.get("receipts") or []))
        )
        evidence_set_sha256 = _digest(_evidence_set_payload(verified_evidence))
        _pass(checks, "accepted_evidence_verified")

        source_snapshot_sha256 = _require_digest(
            job_record.get("source_snapshot_sha256"),
            code="source_snapshot_digest_invalid",
            message="The frozen source snapshot SHA-256 is invalid.",
        )
        submission_provenance_sha256 = _require_digest(
            job_record.get("submission_provenance_sha256"),
            code="submission_provenance_digest_invalid",
            message="The frozen submission provenance SHA-256 is invalid.",
        )
        verified_request_sha256, verified_source_artifact = (
            run_technoeconomic._verify_frozen_inputs(
                request_payload=request_payload,
                source_snapshot=source_snapshot,
                source_snapshot_sha256=source_snapshot_sha256,
                submission_provenance=submission_provenance,
                submission_provenance_sha256=submission_provenance_sha256,
                source_annual_job_id=str(
                    job_record.get("source_annual_job_id") or ""
                ),
                source_artifact_storage_key=str(
                    job_record.get("source_artifact_storage_key") or ""
                ),
                source_artifact_sha256=str(
                    job_record.get("source_artifact_sha256") or ""
                ),
                source_artifact_bytes=job_record.get("source_artifact_bytes"),
            )
        )
        _require_equal(
            verified_request_sha256,
            expected_request_sha256,
            code="request_digest_mismatch",
            message="The verified frozen request differs from confirmation.",
            digest=True,
        )
        for actual, expected, code, message in (
            (
                scenario_record.get("source_snapshot_sha256"),
                source_snapshot_sha256,
                "scenario_source_lock_mismatch",
                "The scenario source lock differs from the completed result.",
            ),
            (
                case_record.get("source_snapshot_sha256"),
                source_snapshot_sha256,
                "case_source_lock_mismatch",
                "The case source lock differs from the completed result.",
            ),
            (
                scenario_record.get("source_annual_job_id"),
                job_record.get("source_annual_job_id"),
                "scenario_source_identity_mismatch",
                "The scenario Annual source differs from the completed result.",
            ),
            (
                case_record.get("source_annual_job_id"),
                job_record.get("source_annual_job_id"),
                "case_source_identity_mismatch",
                "The case Annual source differs from the completed result.",
            ),
            (
                scenario_record.get("analysis_basis"),
                request_payload.get("basis"),
                "scenario_basis_lock_mismatch",
                "The scenario analysis basis differs from the completed result.",
            ),
            (
                case_record.get("analysis_basis"),
                request_payload.get("basis"),
                "case_basis_lock_mismatch",
                "The case analysis basis differs from the completed result.",
            ),
        ):
            _require_equal(actual, expected, code=code, message=message)
        _pass(checks, "frozen_source_verified")

        kernel_request = technoeconomic_api.build_technoeconomic_kernel_request(
            request_payload,
            source_snapshot,
        )
        kernel_request = technoeconomic_kernel.validate_request(kernel_request)
        validated_kernel_request_sha256 = _digest(
            technoeconomic_kernel.canonical_request_payload(kernel_request)
        )
        _require_equal(
            validated_kernel_request_sha256,
            submission_provenance.get("validated_kernel_request_sha256"),
            code="validated_kernel_request_digest_mismatch",
            message="The rebuilt kernel request differs from submission provenance.",
            digest=True,
        )
        _require_equal(
            validated_kernel_request_sha256,
            result_provenance.get("validated_kernel_request_sha256"),
            code="validated_kernel_request_digest_mismatch",
            message="The completed result names a different kernel request.",
            digest=True,
        )
        rebuilt_submission = run_technoeconomic._verify_rebuilt_submission_provenance(
            request_payload=request_payload,
            source_snapshot=source_snapshot,
            source_snapshot_sha256=source_snapshot_sha256,
            request=kernel_request,
            submission_provenance=submission_provenance,
            submission_provenance_sha256=submission_provenance_sha256,
        )
        _pass(checks, "submission_receipts_verified")

        sealed_artifact = artifacts.get("sealed_calculation")
        export_manifest = artifacts.get("exports")
        if not isinstance(sealed_artifact, Mapping) or not isinstance(
            export_manifest, Mapping
        ):
            raise _VerificationFailure(
                "completed_result_artifacts_missing",
                "The completed result is missing sealed or reporting artifacts.",
            )
        attempt_directory, sealed_path, lease_token = _attempt_directory(
            tea_job_id,
            sealed_artifact,
        )
        run_technoeconomic._verify_sealed_calculation_artifact(
            tea_job_id,
            lease_token,
            sealed_artifact,
        )
        sealed = technoeconomic_reporting._load_sealed_calculation(
            attempt_directory=attempt_directory,
            sealed_calculation_path=sealed_path,
            sealed_calculation_artifact=sealed_artifact,
            request_payload=request_payload,
            source_snapshot=source_snapshot,
            submission_provenance=rebuilt_submission,
        )
        routine_without_exports = dict(result)
        routine_without_exports.pop("exports", None)
        technoeconomic_reporting._verify_routine_result(
            metadata=sealed.metadata,
            routine_result=routine_without_exports,
            request_payload=request_payload,
            source_snapshot=source_snapshot,
            submission_provenance=rebuilt_submission,
            sealed_calculation_artifact=sealed_artifact,
        )
        _pass(checks, "sealed_result_verified")

        if result_provenance.get("schema_version") != (
            run_technoeconomic.RESULT_PROVENANCE_SCHEMA_VERSION
        ):
            raise _VerificationFailure(
                "result_provenance_schema_unsupported",
                "The completed result provenance schema is unsupported.",
            )
        expected_result_sha256 = _digest(result)
        for actual, expected, code, message in (
            (
                result_provenance.get("request_sha256"),
                expected_request_sha256,
                "result_request_digest_mismatch",
                "Result provenance names a different request.",
            ),
            (
                result_provenance.get("source_snapshot_sha256"),
                source_snapshot_sha256,
                "result_source_digest_mismatch",
                "Result provenance names a different source snapshot.",
            ),
            (
                result_provenance.get("submission_provenance_sha256"),
                submission_provenance_sha256,
                "result_submission_digest_mismatch",
                "Result provenance names different submission receipts.",
            ),
            (
                result_provenance.get("routine_result_sha256"),
                expected_result_sha256,
                "routine_result_digest_mismatch",
                "The durable result differs from its provenance SHA-256.",
            ),
        ):
            _require_equal(
                actual,
                expected,
                code=code,
                message=message,
                digest=True,
            )
        _require_equal(
            result_provenance.get("source_annual_job_id"),
            job_record.get("source_annual_job_id"),
            code="result_source_identity_mismatch",
            message="Result provenance names a different Annual source.",
        )
        _require_equal(
            result_provenance.get("source_artifact"),
            {
                key: verified_source_artifact[key]
                for key in ("sha256", "byte_count", "media_type", "immutable")
            },
            code="result_source_artifact_mismatch",
            message="Result provenance names a different immutable source artifact.",
        )
        _require_equal(
            result_provenance.get("sealed_calculation"),
            run_technoeconomic._public_calculation_identity(sealed_artifact),
            code="result_sealed_identity_mismatch",
            message="Result provenance names a different sealed calculation.",
        )
        kernel_provenance = sealed.metadata.get("kernel_provenance")
        if not isinstance(kernel_provenance, Mapping):
            raise _VerificationFailure(
                "kernel_provenance_missing",
                "The sealed result has no kernel provenance.",
            )
        _require_equal(
            result_provenance.get("kernel"),
            kernel_provenance,
            code="kernel_provenance_mismatch",
            message="Result provenance differs from the sealed kernel provenance.",
        )
        _verify_numerical_provenance(
            kernel_provenance,
            calculation_contract_version=result.get(
                "calculation_contract_version"
            ),
            sampling_version=result.get("sampling_version"),
        )
        _pass(checks, "result_and_numerical_provenance_verified")

        run_technoeconomic._verify_export_manifest(
            tea_job_id,
            lease_token,
            export_manifest,
            request_sha256=expected_request_sha256,
            source_snapshot_sha256=source_snapshot_sha256,
            submission_provenance_sha256=submission_provenance_sha256,
            calculation_contract_version=str(
                result.get("calculation_contract_version") or ""
            ),
            sampling_version=str(result.get("sampling_version") or ""),
            sealed_calculation_sha256=str(sealed_artifact.get("sha256") or ""),
        )
        public_manifest = run_technoeconomic._public_export_manifest(
            export_manifest
        )
        _require_equal(
            result.get("exports"),
            public_manifest,
            code="result_export_manifest_mismatch",
            message="The durable result differs from the immutable export manifest.",
        )
        _require_equal(
            result_provenance.get("exports"),
            {
                "schema_version": export_manifest.get("schema_version"),
                "manifest_sha256": export_manifest.get("manifest_sha256"),
                "artifact_count": export_manifest.get("artifact_count"),
            },
            code="result_export_provenance_mismatch",
            message="Result provenance names a different export manifest.",
        )
        tie_outs = export_manifest.get("tie_outs")
        if (
            not isinstance(tie_outs, Mapping)
            or tie_outs.get("status") != "passed"
            or tie_outs.get("failed_check_ids") != []
        ):
            raise _VerificationFailure(
                "reporting_tie_out_not_passed",
                "The completed result has no passing reporting tie-out.",
            )
        check_rows = technoeconomic_reporting._build_checks(
            sealed,
            source_snapshot,
            rebuilt_submission,
            result,
        )
        reporting_checks = tuple(
            {
                key: deepcopy(value)
                for key, value in zip(
                    technoeconomic_reporting.CHECK_COLUMNS,
                    row,
                    strict=True,
                )
            }
            for row in check_rows
        )
        failed_check_ids = [
            str(row.get("check_id"))
            for row in reporting_checks
            if row.get("status_authority") != "OK"
        ]
        if failed_check_ids:
            raise _VerificationFailure(
                "reporting_tie_out_failed",
                "The sealed result failed reporting tie-out verification.",
                details=[{"check_id": value} for value in failed_check_ids],
            )
        _require_equal(
            tie_outs.get("check_count"),
            len(reporting_checks),
            code="reporting_tie_out_count_mismatch",
            message="The reporting tie-out count differs from sealed verification.",
        )
        _require_equal(
            tie_outs.get("realization_row_count"),
            sealed.row_count,
            code="reporting_realization_count_mismatch",
            message="The reporting realization count differs from the sealed result.",
        )
        reporting_tieout_sha256 = _digest(
            {
                "manifest_sha256": export_manifest.get("manifest_sha256"),
                "tie_outs": tie_outs,
            }
        )
        _pass(checks, "reporting_tie_out_verified")

        return ResultVerificationOutcome(
            status="verified",
            tea_job_id=tea_job_id,
            checks=tuple(checks),
            failures=(),
            verified_result=VerifiedTechnoeconomicResult(
                tea_job_id=tea_job_id,
                result=deepcopy(dict(result)),
                result_provenance=deepcopy(dict(result_provenance)),
                sealed_metadata=deepcopy(dict(sealed.metadata)),
                reporting_checks=reporting_checks,
                evidence_receipts=verified_evidence,
                evidence_set_sha256=evidence_set_sha256,
                reporting_tieout_sha256=reporting_tieout_sha256,
            ),
        )
    except _VerificationFailure as exc:
        return _failure_outcome(
            tea_job_id=tea_job_id,
            checks=checks,
            failure=exc,
        )
    except Exception:
        # Verifiers fail closed.  Do not surface filesystem paths, private source
        # values, lease tokens, or third-party exception text to comparison APIs.
        return _failure_outcome(
            tea_job_id=tea_job_id,
            checks=checks,
            failure=_VerificationFailure(
                "result_verification_failed",
                "The completed result could not be reverified safely.",
            ),
        )


__all__ = [
    "RESULT_VERIFICATION_SCHEMA_VERSION",
    "ResultVerificationOutcome",
    "VerifiedTechnoeconomicResult",
    "verify_completed_technoeconomic_result",
]
