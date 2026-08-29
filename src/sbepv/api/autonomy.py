"""Narrow live APIs for durable Autonomy cases, readiness, evidence, and chat."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import json
import logging
from pathlib import Path
import re
from urllib.parse import quote
import uuid
from typing import Any

from fastapi import (
    APIRouter,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
)
from fastapi.responses import Response, StreamingResponse

from sbepv.api import config, state
from sbepv.api import serializers as api_serializers
from sbepv.api import technoeconomic as technoeconomic_api
from sbepv.api.autonomy_schemas import (
    DecisionCaseArchiveRequest,
    DecisionCaseCreateRequest,
    DecisionCaseUpdateRequest,
    DecisionMessageCreateRequest,
    DecisionScenarioConfirmRequest,
    DecisionScenarioCreateRequest,
    DecisionScenarioExpireRequest,
    DecisionScenarioJobActionRequest,
    DecisionScenarioRevisionRequest,
    DecisionScenarioValidateRequest,
    EvidenceDeleteRequest,
    EvidenceReviewRequest,
)
from sbepv.autonomy import decision_agent as decision_agent_module
from sbepv.autonomy import evidence, lifecycle, readiness, scenarios, serializers
from sbepv.store import (
    AgentStoreError,
    EvidenceLimitExceeded,
    InvalidStateTransition,
    LeaseOwnershipLost,
    QueueCapacityExceeded,
    RecordNotFound,
    StoreConflict,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/autonomy", tags=["autonomy"])

_CASE_ID_RE = re.compile(r"^case_[A-Za-z0-9]+$")
_TURN_ID_RE = re.compile(r"^dturn_[A-Za-z0-9]+$")
_EVIDENCE_ID_RE = re.compile(r"^evi_[A-Za-z0-9]+$")
_CANDIDATE_ID_RE = re.compile(r"^evc_[A-Za-z0-9]+$")
_SCENARIO_ID_RE = re.compile(r"^dsc_[A-Za-z0-9]+$")
_TEA_JOB_ID_RE = re.compile(r"^tea_[A-Za-z0-9_-]+$")
_GROUPED_TEA_ACKNOWLEDGEMENT = (
    "I confirm the selected scenarios, source and basis lock, evidence status, "
    "realization count, seed, and exact request hashes shown here. I understand "
    "the production action would create immutable TEA jobs for sequential worker "
    "execution."
)
_SAFE_AGENT_FAILURE_CODES = frozenset(
    {"agent_disabled", "agent_unavailable", "timeout", "agent_interrupted"}
)


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="Not found.")


def _validate_identifier(value: str, pattern: re.Pattern[str]) -> str:
    normalized = str(value or "").strip()
    if not pattern.fullmatch(normalized):
        raise _not_found()
    return normalized


def _store_failure(exc: Exception) -> HTTPException:
    if isinstance(exc, RecordNotFound):
        return _not_found()
    if isinstance(exc, EvidenceLimitExceeded):
        return HTTPException(
            status_code=413,
            detail={"code": "evidence_case_limit", "message": str(exc)},
        )
    if isinstance(
        exc, (InvalidStateTransition, StoreConflict, LeaseOwnershipLost)
    ):
        return HTTPException(
            status_code=409,
            detail={"code": "durable_state_conflict", "message": str(exc)},
        )
    if isinstance(exc, ValueError):
        return HTTPException(
            status_code=422,
            detail={"code": "invalid_request", "message": str(exc)},
        )
    return HTTPException(status_code=500, detail="Durable state is unavailable.")


def _case_or_404(case_id: str) -> dict[str, Any]:
    canonical = _validate_identifier(case_id, _CASE_ID_RE)
    case_record = state.AGENT_STORE.get_decision_case(canonical)
    if case_record is None:
        raise _not_found()
    return case_record


def _scenario_contract_failure(exc: scenarios.ScenarioContractError) -> HTTPException:
    return HTTPException(status_code=422, detail=exc.as_dict())


def _scenario_evidence_references(raw_references: Any) -> list[dict[str, str]]:
    return [
        {
            "request_path": str(reference.request_path),
            "evidence_receipt_id": str(reference.receipt_id),
        }
        for reference in raw_references
    ]


def _evidence_snapshot_loader(
    case_id: str,
    evidence_asset_id: str,
) -> tuple[bytes, dict[str, Any]]:
    return evidence.verified_evidence_snapshot(
        state.AGENT_STORE,
        case_id,
        evidence_asset_id,
    )


def _current_scenarios(case_id: str) -> list[dict[str, Any]]:
    return state.AGENT_STORE.list_decision_scenarios(
        case_id,
        include_history=False,
        include_expired=False,
        limit=10,
    )


def _current_scenario_or_404(
    case_id: str,
    scenario_id: str,
) -> dict[str, Any]:
    canonical_scenario = _validate_identifier(scenario_id, _SCENARIO_ID_RE)
    try:
        records = _current_scenarios(case_id)
    except (AgentStoreError, ValueError) as exc:
        raise _store_failure(exc) from exc
    record = next(
        (
            item
            for item in records
            if str(item.get("scenario_id") or item.get("id")) == canonical_scenario
        ),
        None,
    )
    if record is None:
        raise _not_found()
    return record


def _baseline_scenario(
    case_id: str,
    *,
    records: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    candidates = records if records is not None else _current_scenarios(case_id)
    return next(
        (item for item in candidates if item.get("kind") == "baseline"),
        None,
    )


def _validate_scenario_record(
    case_record: dict[str, Any],
    scenario_record: dict[str, Any],
    *,
    current_records: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    records = current_records if current_records is not None else _current_scenarios(
        str(case_record["id"])
    )
    baseline = _baseline_scenario(str(case_record["id"]), records=records)
    baseline_request = None
    if scenario_record.get("kind") == "alternative" and baseline is not None:
        baseline_request = baseline.get("request")
    return scenarios.validate_scenario_draft(
        case_record=case_record,
        kind=str(scenario_record.get("kind") or ""),
        request_payload=scenario_record.get("request") or {},
        baseline_request=baseline_request,
        declared_changed_fields=scenario_record.get("changed_fields") or [],
        evidence_references=scenario_record.get("evidence_receipt_refs") or [],
        receipt_loader=state.AGENT_STORE.get_decision_evidence_receipt,
        evidence_snapshot_loader=_evidence_snapshot_loader,
    )


def _expire_due_scenario_drafts(case_record: dict[str, Any]) -> None:
    if case_record.get("status") in {"signed", "archived"}:
        return
    try:
        state.AGENT_STORE.expire_decision_scenario_drafts(
            str(case_record["id"]),
            operator_name="system:scenario-expiry",
        )
    except (AgentStoreError, ValueError) as exc:
        raise _store_failure(exc) from exc


def _scenario_response_context(case_id: str) -> dict[str, Any]:
    case_record = _case_or_404(case_id)
    readiness_record = _readiness_or_503(case_id)
    return {
        "case": serializers.public_decision_case(case_record),
        "readiness": readiness_record,
        "allowed_actions": readiness_record.get("allowed_case_actions") or [],
        "blockers": readiness_record.get("blockers") or [],
    }


def _public_scenario(
    record: dict[str, Any],
    case_record: dict[str, Any],
) -> dict[str, Any]:
    public = serializers.public_decision_scenario(record)
    status = str(record.get("status") or "")
    case_status = str(case_record.get("status") or "")
    current = bool(record.get("is_current", True))
    case_mutable = case_status not in {"signed", "archived"}
    definitions = (
        (
            "revise_scenario",
            current and case_mutable and status != "expired",
            "Only the current, unexpired scenario revision can be revised.",
        ),
        (
            "validate_scenario",
            current and case_mutable and status == "draft",
            "Only a current draft can receive a deterministic validation receipt.",
        ),
        (
            "expire_scenario",
            current
            and case_mutable
            and status in {"draft", "invalid", "validated"},
            "Only an unconfirmed current scenario can be expired.",
        ),
        (
            "select_for_confirmation",
            current and status == "validated" and case_status == "ready_to_run",
            "Selection requires a current validated scenario in a ready case.",
        ),
    )
    public["allowed_actions"] = [
        {
            "id": action_id,
            "enabled": enabled,
            "disabled_reason": None if enabled else reason,
        }
        for action_id, enabled, reason in definitions
    ]
    return public


def _public_scenario_job_link(record: dict[str, Any]) -> dict[str, Any]:
    job = record.get("job")
    if not isinstance(job, dict):
        job = {}
    return {
        "case_id": str(record.get("case_id") or ""),
        "scenario_id": str(record.get("scenario_id") or ""),
        "scenario_revision_id": str(record.get("scenario_revision_id") or ""),
        "scenario_revision": int(record.get("scenario_revision") or 0),
        "attempt_number": int(record.get("attempt_number") or 0),
        "retry_of_job_id": record.get("retry_of_job_id"),
        "confirmation_id": record.get("confirmation_id"),
        "job": api_serializers._public_technoeconomic_job(job),
    }


def _scenario_request_template(
    case_record: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return a source-matched prior request or an explicit locked-field skeleton."""

    source_id = str(case_record.get("source_annual_job_id") or "")
    basis = str(case_record.get("analysis_basis") or "")
    if source_id:
        try:
            jobs = state.AGENT_STORE.list_technoeconomic_jobs(
                source_annual_job_id=source_id,
                limit=25,
            )
        except (AgentStoreError, ValueError):
            jobs = []
        for job in jobs:
            request_payload = job.get("request")
            if (
                isinstance(request_payload, dict)
                and request_payload.get("basis") == basis
                and job.get("source_snapshot_sha256")
                == case_record.get("source_snapshot_sha256")
            ):
                return dict(request_payload), {
                    "kind": "verified_prior_tea_request",
                    "source_tea_job_id": str(job.get("id") or ""),
                    "pre_run_value_semantics": "inputs_or_hypotheses_not_outcomes",
                    "requires_operator_review": True,
                }
    skeleton: dict[str, Any] = {
        "source_annual_job_id": source_id,
        "basis": basis,
        "n": 10_000,
        "seed": 42,
        "cost_stack_completeness": "full_system",
        "cost_lines": [],
        "finance": {},
        "shared_degradation": {},
    }
    if basis == "solartac_site":
        skeleton["capacity_normalization"] = "annual_applied_capacity_v1"
    return skeleton, {
        "kind": "locked_fields_only",
        "pre_run_value_semantics": "inputs_or_hypotheses_not_outcomes",
        "requires_operator_completion": True,
        "message": (
            "Complete the evidence-backed cost, finance, and degradation inputs, "
            "or use the existing expert TEA form to create a reusable request."
        ),
        "supported_action": {
            "id": "open_expert_tea",
            "label": "Open expert TEA",
            "deep_link": "#technoeconomic",
        },
    }


def _scenario_comparison_payload(
    case_record: dict[str, Any],
    current_records: list[dict[str, Any]],
) -> dict[str, Any]:
    request_template, request_template_metadata = _scenario_request_template(
        case_record
    )
    baseline = _baseline_scenario(str(case_record["id"]), records=current_records)
    if baseline is None:
        return {
            "comparison_version": scenarios.SCENARIO_COMPARISON_VERSION,
            "available": False,
            "pre_run_value_semantics": "inputs_or_hypotheses_not_outcomes",
            "outcomes_available": False,
            "baseline": None,
            "alternatives": [],
            "difference_matrix": [],
            "warnings": [],
            "request_template": request_template,
            "request_template_metadata": request_template_metadata,
            "blockers": [
                {
                    "code": "baseline_required",
                    "message": "Create a baseline scenario before comparing alternatives.",
                    "supported_action": "create_baseline",
                }
            ],
        }
    alternatives = [
        item for item in current_records if item.get("kind") == "alternative"
    ]
    try:
        result = scenarios.build_scenario_comparison(
            case_record=case_record,
            baseline=baseline,
            alternatives=alternatives,
        )
    except scenarios.ScenarioContractError as exc:
        return {
            "comparison_version": scenarios.SCENARIO_COMPARISON_VERSION,
            "available": False,
            "pre_run_value_semantics": "inputs_or_hypotheses_not_outcomes",
            "outcomes_available": False,
            "baseline": _public_scenario(baseline, case_record),
            "alternatives": [
                _public_scenario(item, case_record) for item in alternatives
            ],
            "difference_matrix": [],
            "warnings": [],
            "request_template": request_template,
            "request_template_metadata": request_template_metadata,
            "blockers": [exc.as_dict()],
        }
    result["available"] = True
    result["request_template"] = request_template
    result["request_template_metadata"] = request_template_metadata
    return result


def _scenario_execution_payload(case_id: str) -> dict[str, Any]:
    try:
        execution = state.AGENT_STORE.reconcile_decision_case_execution(case_id)
    except (AgentStoreError, ValueError) as exc:
        raise _store_failure(exc) from exc
    latest_links = execution.get("latest_links") or []
    all_links = execution.get("links") or []
    states = [
        str((item.get("job") or {}).get("state") or "unknown")
        for item in latest_links
        if isinstance(item, dict)
    ]
    if not states:
        display_state = "idle"
    elif execution.get("all_successful"):
        display_state = "completed"
    elif execution.get("partial_results"):
        display_state = "partial_results"
    elif "running" in states:
        display_state = "running"
    elif "queued" in states:
        display_state = "queued"
    elif all(
        job_state in {"error", "interrupted", "cancelled"}
        for job_state in states
    ):
        display_state = "failed"
    else:
        display_state = "needs_attention"
    cancellable_job_ids = [
        str(item.get("tea_job_id"))
        for item in latest_links
        if isinstance(item, dict)
        and (item.get("job") or {}).get("state") in {"queued", "running"}
    ]
    confirmation_ids: list[str] = []
    for item in all_links:
        if not isinstance(item, dict):
            continue
        confirmation_id = str(item.get("confirmation_id") or "")
        if confirmation_id and confirmation_id not in confirmation_ids:
            confirmation_ids.append(confirmation_id)
    confirmations: list[dict[str, Any]] = []
    for confirmation_id in confirmation_ids:
        confirmation = state.AGENT_STORE.get_decision_scenario_confirmation(
            confirmation_id
        )
        if confirmation is not None:
            confirmations.append(
                serializers.public_scenario_confirmation(confirmation)
            )
    return {
        "state": display_state,
        "queue_behavior": {
            "policy": "shared_leased_sequential_worker",
            "selected_jobs_are_enqueued_atomically": True,
            "execution_order": "durable_queue_order",
            "max_active_jobs": int(config.MAX_ACTIVE_MODEL_JOBS),
        },
        "job_count": int(execution.get("job_count") or 0),
        "state_counts": serializers.safe_public_value(
            execution.get("state_counts") or {}
        ),
        "all_terminal": bool(execution.get("all_terminal")),
        "all_successful": bool(execution.get("all_successful")),
        "results_available": bool(execution.get("results_available")),
        "partial_results": bool(execution.get("partial_results")),
        "retryable_job_ids": [
            str(item) for item in execution.get("retryable_job_ids") or []
        ],
        "cancellable_job_ids": cancellable_job_ids,
        "jobs": [
            _public_scenario_job_link(item)
            for item in all_links
            if isinstance(item, dict)
        ],
        "latest_jobs": [
            _public_scenario_job_link(item)
            for item in latest_links
            if isinstance(item, dict)
        ],
        "confirmations": confirmations,
        "case_transitioned": bool(execution.get("case_transitioned")),
        "decision_brief_available": False,
        "recommendation_available": False,
        "signoff_available": False,
        "report_generation_available": False,
    }


def _confirmation_replay_matches(
    replay: dict[str, Any],
    request_payload: DecisionScenarioConfirmRequest,
) -> bool:
    confirmation_request = replay.get("confirmation_request") or {}
    items = replay.get("items") or []
    submitted = [
        {
            "scenario_id": item.scenario_id,
            "revision": item.revision,
            "request_sha256": item.request_sha256,
        }
        for item in request_payload.selections
    ]
    stored = [
        {
            "scenario_id": str(item.get("scenario_id") or ""),
            "revision": int(item.get("scenario_revision") or 0),
            "request_sha256": str(item.get("request_sha256") or ""),
        }
        for item in items
        if isinstance(item, dict)
    ]
    return bool(
        int(confirmation_request.get("expected_case_revision") or 0)
        == request_payload.expected_case_revision
        and str(confirmation_request.get("operator_name") or "")
        == request_payload.operator_name
        and str(confirmation_request.get("rationale") or "")
        == request_payload.rationale
        and str(confirmation_request.get("acknowledgement") or "")
        == _GROUPED_TEA_ACKNOWLEDGEMENT
        and submitted == stored
    )


def _readiness_or_503(case_id: str) -> dict[str, Any]:
    try:
        return readiness.evaluate_decision_case_readiness(case_id)
    except KeyError as exc:
        raise _not_found() from exc
    except (AgentStoreError, OSError, TypeError, ValueError) as exc:
        logger.warning("Autonomy readiness evaluation failed for %s", case_id, exc_info=True)
        raise HTTPException(
            status_code=503,
            detail={
                "code": "readiness_unavailable",
                "message": "Deterministic readiness could not be evaluated.",
            },
        ) from exc


def _reconcile_case_state(case_id: str, operator_name: str) -> None:
    """Apply only current-phase readiness states after a relevant mutation."""

    try:
        # A new fully-ready case must traverse the approved graph through
        # evidence_needed before ready_to_run. Two bounded passes preserve that
        # state history without letting reconciliation wander into later phases.
        for _pass in range(2):
            result = readiness.evaluate_decision_case_readiness(case_id)
            case_record = state.AGENT_STORE.get_decision_case(case_id)
            if not case_record:
                return
            requested = result.get("suggested_case_status")
            current = case_record.get("status")
            if not (
                requested in {"evidence_needed", "blocked", "ready_to_run"}
                and current in {"draft", "evidence_needed", "blocked"}
                and requested != current
                and lifecycle.transition_is_allowed(current, requested)
            ):
                return
            state.AGENT_STORE.transition_decision_case(
                case_id,
                expected_revision=int(case_record["revision"]),
                status=str(requested),
                operator_name=operator_name,
                reason="Deterministic readiness reconciliation.",
            )
    except (AgentStoreError, KeyError, OSError, TypeError, ValueError):
        # The primary mutation already committed. Readiness is explicitly
        # retryable and must not be allowed to roll back a human evidence action.
        logger.warning("Could not reconcile decision case %s", case_id, exc_info=True)


@router.get("/cases")
def list_decision_cases(
    include_archived: bool = Query(default=False),
    limit: int = Query(default=100, ge=1, le=500),
) -> dict[str, Any]:
    try:
        records = state.AGENT_STORE.list_decision_cases(
            include_archived=include_archived,
            limit=limit,
        )
    except (AgentStoreError, ValueError) as exc:
        raise _store_failure(exc) from exc
    return {"cases": [serializers.public_decision_case(item) for item in records]}


@router.post("/cases", status_code=201)
def create_decision_case(request_payload: DecisionCaseCreateRequest) -> dict[str, Any]:
    try:
        case_record = state.AGENT_STORE.create_decision_case(
            title=request_payload.title,
            question=request_payload.question,
            operator_name=request_payload.operator_name,
        )
    except (AgentStoreError, ValueError) as exc:
        raise _store_failure(exc) from exc
    return {"case": serializers.public_decision_case(case_record)}


@router.get("/cases/{case_id}")
def get_decision_case(case_id: str) -> dict[str, Any]:
    case_record = _case_or_404(case_id)
    return {
        "case": serializers.public_decision_case(case_record),
        "readiness": _readiness_or_503(str(case_record["id"])),
    }


@router.put("/cases/{case_id}")
def update_decision_case(
    case_id: str,
    request_payload: DecisionCaseUpdateRequest,
) -> dict[str, Any]:
    canonical = _validate_identifier(case_id, _CASE_ID_RE)
    _case_or_404(canonical)
    lock_requested = request_payload.source_annual_job_id is not None
    editable_fields = {"title", "question", "decision_owner"}
    if lock_requested and editable_fields.intersection(request_payload.model_fields_set):
        raise HTTPException(
            status_code=422,
            detail={
                "code": "mixed_case_mutation",
                "message": "Update case metadata and lock the source/basis in separate requests.",
            },
        )
    try:
        if lock_requested:
            eligible_sources = readiness.list_eligible_annual_sources()
            selected = next(
                (
                    item
                    for item in eligible_sources
                    if item.get("annual_job_id") == request_payload.source_annual_job_id
                ),
                None,
            )
            if selected is None:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "annual_source_ineligible",
                        "message": "The selected Annual source does not pass strict verification.",
                    },
                )
            if selected.get("source_snapshot_sha256") != request_payload.source_snapshot_sha256:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "annual_source_hash_mismatch",
                        "message": "The selected Annual source hash changed before it was locked.",
                    },
                )
            case_record = state.AGENT_STORE.lock_decision_case(
                canonical,
                expected_revision=request_payload.expected_revision,
                source_annual_job_id=str(request_payload.source_annual_job_id),
                source_snapshot_sha256=str(request_payload.source_snapshot_sha256),
                analysis_basis=str(request_payload.analysis_basis),
                operator_name=request_payload.operator_name,
            )
        else:
            changes: dict[str, Any] = {}
            if "title" in request_payload.model_fields_set:
                changes["title"] = request_payload.title
            if "question" in request_payload.model_fields_set:
                changes["question"] = request_payload.question
            if "decision_owner" in request_payload.model_fields_set:
                changes["decision_owner"] = request_payload.decision_owner
            if changes:
                case_record = state.AGENT_STORE.update_decision_case(
                    canonical,
                    expected_revision=request_payload.expected_revision,
                    operator_name=request_payload.operator_name,
                    **changes,
                )
            else:
                case_record = _case_or_404(canonical)
    except HTTPException:
        raise
    except (AgentStoreError, ValueError) as exc:
        raise _store_failure(exc) from exc
    _reconcile_case_state(canonical, request_payload.operator_name)
    case_record = _case_or_404(canonical)
    return {
        "case": serializers.public_decision_case(case_record),
        "readiness": _readiness_or_503(canonical),
    }


@router.post("/cases/{case_id}/archive")
def archive_decision_case(
    case_id: str,
    request_payload: DecisionCaseArchiveRequest,
) -> dict[str, Any]:
    canonical = _validate_identifier(case_id, _CASE_ID_RE)
    try:
        archived = state.AGENT_STORE.archive_decision_case(
            canonical,
            expected_revision=request_payload.expected_revision,
            operator_name=request_payload.operator_name,
            reason=request_payload.reason,
        )
    except (AgentStoreError, ValueError) as exc:
        raise _store_failure(exc) from exc
    return {"case": serializers.public_decision_case(archived)}


@router.post("/cases/{case_id}/readiness/evaluate")
def evaluate_case_readiness(case_id: str) -> dict[str, Any]:
    canonical = _validate_identifier(case_id, _CASE_ID_RE)
    _case_or_404(canonical)
    return _readiness_or_503(canonical)


@router.get("/sources")
def list_autonomy_annual_sources() -> dict[str, Any]:
    try:
        sources = readiness.list_eligible_annual_sources()
    except (AgentStoreError, OSError, TypeError, ValueError) as exc:
        logger.warning("Could not list Autonomy Annual sources", exc_info=True)
        raise HTTPException(status_code=503, detail="Annual source verification is unavailable.") from exc
    return {
        "sources": sources,
        "analysis_bases": list(readiness.SUPPORTED_ANALYSIS_BASES),
    }


@router.get("/cases/{case_id}/scenarios")
def list_case_scenarios(
    case_id: str,
    include_history: bool = Query(default=True),
    include_expired: bool = Query(default=True),
) -> dict[str, Any]:
    canonical_case = _validate_identifier(case_id, _CASE_ID_RE)
    case_record = _case_or_404(canonical_case)
    _expire_due_scenario_drafts(case_record)
    _reconcile_case_state(canonical_case, "system:scenario-expiry")
    case_record = _case_or_404(canonical_case)
    try:
        records = state.AGENT_STORE.list_decision_scenarios(
            canonical_case,
            include_history=include_history,
            include_expired=include_expired,
            limit=100,
        )
        current = _current_scenarios(canonical_case)
    except (AgentStoreError, ValueError) as exc:
        raise _store_failure(exc) from exc
    return {
        "scenarios": [
            _public_scenario(item, case_record) for item in records
        ],
        "current_scenarios": [
            _public_scenario(item, case_record) for item in current
        ],
        "comparison": _scenario_comparison_payload(case_record, current),
        **_scenario_response_context(canonical_case),
    }


@router.post("/cases/{case_id}/scenarios", status_code=201)
def create_case_scenario(
    case_id: str,
    request_payload: DecisionScenarioCreateRequest,
) -> dict[str, Any]:
    canonical_case = _validate_identifier(case_id, _CASE_ID_RE)
    case_record = _case_or_404(canonical_case)
    _expire_due_scenario_drafts(case_record)
    case_record = _case_or_404(canonical_case)
    if case_record.get("status") not in {
        "draft",
        "evidence_needed",
        "blocked",
        "ready_to_run",
    }:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "scenario_creation_not_allowed",
                "message": "New scenario drafts are available only before execution.",
            },
        )
    try:
        current = _current_scenarios(canonical_case)
        baseline = _baseline_scenario(canonical_case, records=current)
        validation = scenarios.validate_scenario_draft(
            case_record=case_record,
            kind=request_payload.kind,
            request_payload=request_payload.request,
            baseline_request=(
                baseline.get("request")
                if request_payload.kind == "alternative" and baseline is not None
                else None
            ),
            declared_changed_fields=request_payload.changed_fields,
            evidence_references=[
                item.model_dump(mode="json")
                for item in request_payload.evidence_references
            ],
            receipt_loader=state.AGENT_STORE.get_decision_evidence_receipt,
            evidence_snapshot_loader=_evidence_snapshot_loader,
        )
        canonical_request = validation.get("request")
        request_sha256 = validation.get("request_sha256")
        if not isinstance(canonical_request, dict) or not isinstance(
            request_sha256, str
        ):
            raise HTTPException(
                status_code=422,
                detail={"code": "scenario_draft_invalid", **validation},
            )
        if not validation.get("valid"):
            raise HTTPException(
                status_code=422,
                detail={"code": "scenario_draft_invalid", **validation},
            )
        scenario_record = state.AGENT_STORE.create_decision_scenario(
            canonical_case,
            expected_case_revision=request_payload.expected_case_revision,
            label=request_payload.label,
            kind=request_payload.kind,
            request=canonical_request,
            request_sha256=request_sha256,
            changed_fields=request_payload.changed_fields,
            comparison_classification=str(
                validation.get("comparison_classification") or "controlled"
            ),
            evidence_receipt_refs=_scenario_evidence_references(
                request_payload.evidence_references
            ),
            operator_name=request_payload.operator_name,
        )
    except HTTPException:
        raise
    except scenarios.ScenarioContractError as exc:
        raise _scenario_contract_failure(exc) from exc
    except (AgentStoreError, ValueError) as exc:
        raise _store_failure(exc) from exc
    _reconcile_case_state(canonical_case, request_payload.operator_name)
    response_case = _case_or_404(canonical_case)
    return {
        "scenario": _public_scenario(scenario_record, response_case),
        "validation_preview": serializers.safe_public_value(validation),
        **_scenario_response_context(canonical_case),
    }


@router.post("/cases/{case_id}/scenarios/{scenario_id}/revisions", status_code=201)
def revise_case_scenario(
    case_id: str,
    scenario_id: str,
    request_payload: DecisionScenarioRevisionRequest,
) -> dict[str, Any]:
    canonical_case = _validate_identifier(case_id, _CASE_ID_RE)
    case_record = _case_or_404(canonical_case)
    _expire_due_scenario_drafts(case_record)
    case_record = _case_or_404(canonical_case)
    scenario_record = _current_scenario_or_404(canonical_case, scenario_id)
    if request_payload.kind != scenario_record.get("kind"):
        raise HTTPException(
            status_code=422,
            detail={
                "code": "scenario_kind_immutable",
                "message": "A scenario revision cannot change baseline or alternative kind.",
            },
        )
    try:
        current = _current_scenarios(canonical_case)
        baseline = _baseline_scenario(canonical_case, records=current)
        validation = scenarios.validate_scenario_draft(
            case_record=case_record,
            kind=request_payload.kind,
            request_payload=request_payload.request,
            baseline_request=(
                baseline.get("request")
                if request_payload.kind == "alternative" and baseline is not None
                else None
            ),
            declared_changed_fields=request_payload.changed_fields,
            evidence_references=[
                item.model_dump(mode="json")
                for item in request_payload.evidence_references
            ],
            receipt_loader=state.AGENT_STORE.get_decision_evidence_receipt,
            evidence_snapshot_loader=_evidence_snapshot_loader,
        )
        canonical_request = validation.get("request")
        request_sha256 = validation.get("request_sha256")
        if not isinstance(canonical_request, dict) or not isinstance(
            request_sha256, str
        ):
            raise HTTPException(
                status_code=422,
                detail={"code": "scenario_revision_invalid", **validation},
            )
        if not validation.get("valid"):
            raise HTTPException(
                status_code=422,
                detail={"code": "scenario_revision_invalid", **validation},
            )
        revised = state.AGENT_STORE.revise_decision_scenario(
            str(scenario_record["scenario_id"]),
            expected_case_revision=request_payload.expected_case_revision,
            expected_revision=request_payload.expected_scenario_revision,
            label=request_payload.label,
            request=canonical_request,
            request_sha256=request_sha256,
            changed_fields=request_payload.changed_fields,
            comparison_classification=str(
                validation.get("comparison_classification") or "controlled"
            ),
            evidence_receipt_refs=_scenario_evidence_references(
                request_payload.evidence_references
            ),
            operator_name=request_payload.operator_name,
        )
    except HTTPException:
        raise
    except scenarios.ScenarioContractError as exc:
        raise _scenario_contract_failure(exc) from exc
    except (AgentStoreError, ValueError) as exc:
        raise _store_failure(exc) from exc
    _reconcile_case_state(canonical_case, request_payload.operator_name)
    response_case = _case_or_404(canonical_case)
    return {
        "scenario": _public_scenario(revised, response_case),
        "validation_preview": serializers.safe_public_value(validation),
        **_scenario_response_context(canonical_case),
    }


@router.post("/cases/{case_id}/scenarios/{scenario_id}/validate")
def validate_case_scenario(
    case_id: str,
    scenario_id: str,
    request_payload: DecisionScenarioValidateRequest,
) -> dict[str, Any]:
    canonical_case = _validate_identifier(case_id, _CASE_ID_RE)
    case_record = _case_or_404(canonical_case)
    _expire_due_scenario_drafts(case_record)
    case_record = _case_or_404(canonical_case)
    scenario_record = _current_scenario_or_404(canonical_case, scenario_id)
    if scenario_record.get("request_sha256") != request_payload.expected_request_sha256:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "scenario_request_changed",
                "message": "The scenario request hash changed; reload before validating.",
            },
        )
    try:
        validation = _validate_scenario_record(case_record, scenario_record)
        validated = state.AGENT_STORE.record_decision_scenario_validation(
            str(scenario_record["scenario_revision_id"]),
            expected_case_revision=request_payload.expected_case_revision,
            expected_revision=request_payload.expected_scenario_revision,
            request_sha256=request_payload.expected_request_sha256,
            validation=validation,
            valid=bool(validation.get("valid")),
            operator_name=request_payload.operator_name,
        )
    except scenarios.ScenarioContractError as exc:
        raise _scenario_contract_failure(exc) from exc
    except (AgentStoreError, ValueError) as exc:
        raise _store_failure(exc) from exc
    _reconcile_case_state(canonical_case, request_payload.operator_name)
    response_case = _case_or_404(canonical_case)
    return {
        "scenario": _public_scenario(validated, response_case),
        "validation": serializers.safe_public_value(validation),
        **_scenario_response_context(canonical_case),
    }


@router.post("/cases/{case_id}/scenarios/{scenario_id}/expire")
def expire_case_scenario(
    case_id: str,
    scenario_id: str,
    request_payload: DecisionScenarioExpireRequest,
) -> dict[str, Any]:
    canonical_case = _validate_identifier(case_id, _CASE_ID_RE)
    canonical_scenario = _validate_identifier(scenario_id, _SCENARIO_ID_RE)
    _case_or_404(canonical_case)
    scenario_record = _current_scenario_or_404(canonical_case, canonical_scenario)
    try:
        expired = state.AGENT_STORE.expire_decision_scenario(
            canonical_scenario,
            expected_case_revision=request_payload.expected_case_revision,
            expected_revision=request_payload.expected_scenario_revision,
            operator_name=request_payload.operator_name,
            reason=request_payload.reason,
        )
    except (AgentStoreError, ValueError) as exc:
        raise _store_failure(exc) from exc
    if str(expired.get("case_id")) != canonical_case or str(
        scenario_record.get("case_id")
    ) != canonical_case:
        raise _not_found()
    _reconcile_case_state(canonical_case, request_payload.operator_name)
    response_case = _case_or_404(canonical_case)
    return {
        "scenario": _public_scenario(expired, response_case),
        **_scenario_response_context(canonical_case),
    }


@router.get("/cases/{case_id}/scenarios/compare")
def compare_case_scenarios(case_id: str) -> dict[str, Any]:
    canonical_case = _validate_identifier(case_id, _CASE_ID_RE)
    case_record = _case_or_404(canonical_case)
    _expire_due_scenario_drafts(case_record)
    case_record = _case_or_404(canonical_case)
    try:
        current = _current_scenarios(canonical_case)
    except (AgentStoreError, ValueError) as exc:
        raise _store_failure(exc) from exc
    return {
        "comparison": _scenario_comparison_payload(case_record, current),
        "scenarios": [
            _public_scenario(item, case_record) for item in current
        ],
        **_scenario_response_context(canonical_case),
    }


@router.post("/cases/{case_id}/scenarios/confirm", status_code=202)
def confirm_case_scenarios(
    case_id: str,
    request_payload: DecisionScenarioConfirmRequest,
) -> dict[str, Any]:
    canonical_case = _validate_identifier(case_id, _CASE_ID_RE)
    case_record = _case_or_404(canonical_case)
    try:
        replay = state.AGENT_STORE.get_decision_scenario_confirmation_by_idempotency(
            canonical_case,
            request_payload.idempotency_key,
        )
    except (AgentStoreError, ValueError) as exc:
        raise _store_failure(exc) from exc
    if replay is not None:
        if not _confirmation_replay_matches(replay, request_payload):
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "idempotency_key_reused",
                    "message": (
                        "The idempotency key was already used for a different "
                        "scenario confirmation."
                    ),
                },
            )
        return {
            "confirmation": serializers.public_scenario_confirmation(replay),
            "jobs": [
                api_serializers._public_technoeconomic_job(job)
                for job in replay.get("jobs") or []
                if isinstance(job, dict)
            ],
            "idempotent_replay": True,
            "execution": _scenario_execution_payload(canonical_case),
            **_scenario_response_context(canonical_case),
        }

    _expire_due_scenario_drafts(case_record)
    case_record = _case_or_404(canonical_case)
    if case_record.get("status") != "ready_to_run":
        raise HTTPException(
            status_code=409,
            detail={
                "code": "case_not_ready_to_run",
                "message": "The decision case is not ready for grouped confirmation.",
                "readiness": _readiness_or_503(canonical_case),
            },
        )
    try:
        with state._ORCHESTRATION_LOCK:
            locked_replay = (
                state.AGENT_STORE.get_decision_scenario_confirmation_by_idempotency(
                    canonical_case,
                    request_payload.idempotency_key,
                )
            )
            if locked_replay is not None:
                if not _confirmation_replay_matches(locked_replay, request_payload):
                    raise HTTPException(
                        status_code=409,
                        detail={
                            "code": "idempotency_key_reused",
                            "message": (
                                "The idempotency key was already used for a different "
                                "scenario confirmation."
                            ),
                        },
                    )
                return {
                    "confirmation": serializers.public_scenario_confirmation(
                        locked_replay
                    ),
                    "jobs": [
                        api_serializers._public_technoeconomic_job(job)
                        for job in locked_replay.get("jobs") or []
                        if isinstance(job, dict)
                    ],
                    "idempotent_replay": True,
                    "execution": _scenario_execution_payload(canonical_case),
                    **_scenario_response_context(canonical_case),
                }
            current = _current_scenarios(canonical_case)
            selected: list[dict[str, Any]] = []
            for selection in request_payload.selections:
                scenario_record = next(
                    (
                        item
                        for item in current
                        if str(item.get("scenario_id") or item.get("id"))
                        == selection.scenario_id
                    ),
                    None,
                )
                if scenario_record is None:
                    raise RecordNotFound(
                        f"unknown current decision scenario: {selection.scenario_id}"
                    )
                if int(scenario_record.get("revision") or 0) != selection.revision:
                    raise StoreConflict(
                        "decision scenario revision changed before confirmation"
                    )
                if scenario_record.get("request_sha256") != selection.request_sha256:
                    raise StoreConflict(
                        "decision scenario request changed before confirmation"
                    )
                if scenario_record.get("status") != "validated":
                    raise InvalidStateTransition(
                        "only current validated scenarios may be confirmed"
                    )
                validation = _validate_scenario_record(
                    case_record,
                    scenario_record,
                    current_records=current,
                )
                if not validation.get("valid"):
                    raise HTTPException(
                        status_code=422,
                        detail={
                            "code": "scenario_revalidation_failed",
                            "scenario_id": selection.scenario_id,
                            **validation,
                        },
                    )
                selected.append(scenario_record)
            if sum(item.get("kind") == "baseline" for item in selected) != 1:
                raise HTTPException(
                    status_code=422,
                    detail={
                        "code": "grouped_confirmation_baseline_required",
                        "message": (
                            "Grouped confirmation must include exactly one validated "
                            "baseline."
                        ),
                    },
                )
            selected_baseline = next(
                item for item in selected if item.get("kind") == "baseline"
            )
            selected_alternatives = [
                item for item in selected if item.get("kind") == "alternative"
            ]
            comparison = scenarios.build_scenario_comparison(
                case_record=case_record,
                baseline=selected_baseline,
                alternatives=selected_alternatives,
            )
            confirmation_items: list[dict[str, Any]] = []
            atomic_source_check: Any = None
            frozen_source_identity: tuple[Any, ...] | None = None
            for scenario_record in selected:
                bundle = scenarios.prepare_technoeconomic_bundle(
                    agent_store=state.AGENT_STORE,
                    case_record=case_record,
                    request_payload=scenario_record.get("request") or {},
                )
                if bundle["request_sha256"] != scenario_record["request_sha256"]:
                    raise StoreConflict(
                        "prepared TEA request differs from the validated scenario"
                    )
                source_fields = bundle["source_store_fields"]
                source_identity = (
                    source_fields["source_annual_job_id"],
                    source_fields["source_artifact_storage_key"],
                    source_fields["source_artifact_sha256"],
                    source_fields["source_artifact_bytes"],
                    bundle["source_snapshot_envelope"]["source_snapshot_sha256"],
                )
                if frozen_source_identity is None:
                    frozen_source_identity = source_identity
                    atomic_source_check = source_fields["atomic_source_check"]
                elif source_identity != frozen_source_identity:
                    raise StoreConflict(
                        "selected scenarios did not resolve to one frozen Annual source"
                    )
                confirmation_items.append(
                    {
                        "scenario_revision_id": scenario_record[
                            "scenario_revision_id"
                        ],
                        "expected_revision": int(scenario_record["revision"]),
                        "request": bundle["request"],
                        "request_sha256": bundle["request_sha256"],
                        "submission_provenance": bundle[
                            "submission_provenance"
                        ],
                        "source_annual_job_id": source_fields[
                            "source_annual_job_id"
                        ],
                        "source_artifact_storage_key": source_fields[
                            "source_artifact_storage_key"
                        ],
                        "source_artifact_sha256": source_fields[
                            "source_artifact_sha256"
                        ],
                        "source_artifact_bytes": source_fields[
                            "source_artifact_bytes"
                        ],
                        "source_snapshot": source_fields["source_snapshot"],
                    }
                )
            confirmation_review = {
                "schema_version": 1,
                "pre_run_value_semantics": "inputs_or_hypotheses_not_outcomes",
                "selected_scenarios": [
                    _public_scenario(item, case_record) for item in selected
                ],
                "comparison": comparison,
                "source_basis_lock": comparison["source_basis_lock"],
                "realization_count": comparison["realization_count"],
                "seed": comparison["seed"],
                "request_hashes": [
                    {
                        "scenario_id": item["scenario_id"],
                        "scenario_revision_id": item["scenario_revision_id"],
                        "request_sha256": item["request_sha256"],
                    }
                    for item in selected
                ],
                "queue_behavior": {
                    "policy": "shared_leased_sequential_worker",
                    "selected_job_count": len(selected),
                    "all_or_none_enqueue": True,
                    "max_active_jobs": int(config.MAX_ACTIVE_MODEL_JOBS),
                },
                "warnings": comparison.get("warnings") or [],
                "acknowledgement_copy": _GROUPED_TEA_ACKNOWLEDGEMENT,
            }
            result = state.AGENT_STORE.confirm_decision_scenarios_batch(
                canonical_case,
                confirmation_items,
                expected_case_revision=request_payload.expected_case_revision,
                idempotency_key=request_payload.idempotency_key,
                operator_name=request_payload.operator_name,
                rationale=request_payload.rationale,
                acknowledgement=_GROUPED_TEA_ACKNOWLEDGEMENT,
                confirmation_review=confirmation_review,
                atomic_source_check=atomic_source_check,
                max_active_jobs=config.MAX_ACTIVE_MODEL_JOBS,
            )
    except HTTPException:
        raise
    except scenarios.ScenarioContractError as exc:
        raise _scenario_contract_failure(exc) from exc
    except technoeconomic_api.AnnualSourceValidationError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": exc.code, "message": exc.detail},
        ) from exc
    except QueueCapacityExceeded as exc:
        raise HTTPException(
            status_code=429,
            detail={
                "code": "shared_queue_full",
                "message": "Wait for active work to finish before confirming this batch.",
            },
        ) from exc
    except (AgentStoreError, ValueError) as exc:
        raise _store_failure(exc) from exc
    if not result.get("idempotent_replay"):
        state._WORKER_WAKE.set()
    return {
        "confirmation": serializers.public_scenario_confirmation(
            result["confirmation"]
        ),
        "jobs": [
            api_serializers._public_technoeconomic_job(job)
            for job in result.get("jobs") or []
        ],
        "idempotent_replay": bool(result.get("idempotent_replay")),
        "execution": _scenario_execution_payload(canonical_case),
        **_scenario_response_context(canonical_case),
    }


@router.get("/cases/{case_id}/execution")
def get_case_execution(case_id: str) -> dict[str, Any]:
    canonical_case = _validate_identifier(case_id, _CASE_ID_RE)
    _case_or_404(canonical_case)
    return {
        "execution": _scenario_execution_payload(canonical_case),
        **_scenario_response_context(canonical_case),
    }


@router.post("/cases/{case_id}/execution/{job_id}/cancel")
def cancel_case_execution_job(
    case_id: str,
    job_id: str,
    request_payload: DecisionScenarioJobActionRequest,
) -> dict[str, Any]:
    canonical_case = _validate_identifier(case_id, _CASE_ID_RE)
    canonical_job = _validate_identifier(job_id, _TEA_JOB_ID_RE)
    _case_or_404(canonical_case)
    try:
        result = state.AGENT_STORE.cancel_decision_scenario_job(
            canonical_case,
            canonical_job,
            expected_case_revision=request_payload.expected_case_revision,
            operator_name=request_payload.operator_name,
            reason=request_payload.rationale,
        )
    except (AgentStoreError, ValueError) as exc:
        raise _store_failure(exc) from exc
    state._WORKER_WAKE.set()
    return {
        "cancelled": bool(result.get("changed")),
        "job": _public_scenario_job_link(result["link"]),
        "execution": _scenario_execution_payload(canonical_case),
        **_scenario_response_context(canonical_case),
    }


@router.post("/cases/{case_id}/execution/{job_id}/retry", status_code=202)
def retry_case_execution_job(
    case_id: str,
    job_id: str,
    request_payload: DecisionScenarioJobActionRequest,
) -> dict[str, Any]:
    canonical_case = _validate_identifier(case_id, _CASE_ID_RE)
    canonical_job = _validate_identifier(job_id, _TEA_JOB_ID_RE)
    case_record = _case_or_404(canonical_case)
    try:
        with state._ORCHESTRATION_LOCK:
            link = state.AGENT_STORE.get_decision_scenario_job(
                canonical_case,
                canonical_job,
            )
            if link is None:
                raise RecordNotFound(
                    "TEA job is not linked to that decision case"
                )
            scenario_record = state.AGENT_STORE.get_decision_scenario(
                str(link["scenario_revision_id"])
            )
            if scenario_record is None:
                raise RecordNotFound("linked decision scenario was not found")
            confirmation_id = str(
                scenario_record.get("confirmation_id")
                or link.get("confirmation_id")
                or link.get("scenario_confirmation_id")
                or ""
            )
            frozen_records: list[dict[str, Any]] = []
            if confirmation_id:
                confirmation = (
                    state.AGENT_STORE.get_decision_scenario_confirmation(
                        confirmation_id
                    )
                )
                if confirmation is not None:
                    for item in confirmation.get("items") or []:
                        if not isinstance(item, dict):
                            continue
                        frozen_record = state.AGENT_STORE.get_decision_scenario(
                            str(item.get("scenario_revision_id") or "")
                        )
                        if frozen_record is not None:
                            frozen_records.append(frozen_record)
            validation = _validate_scenario_record(
                case_record,
                scenario_record,
                current_records=frozen_records or None,
            )
            if not validation.get("valid"):
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "retry_evidence_revalidation_failed",
                        "message": (
                            "The frozen scenario evidence no longer verifies; the "
                            "prior attempt was retained and no retry was created."
                        ),
                        "validation": validation,
                    },
                )
            result = state.AGENT_STORE.retry_decision_scenario_job(
                canonical_case,
                str(link["scenario_revision_id"]),
                canonical_job,
                expected_case_revision=request_payload.expected_case_revision,
                operator_name=request_payload.operator_name,
                reason=request_payload.rationale,
                max_active_jobs=config.MAX_ACTIVE_MODEL_JOBS,
            )
    except HTTPException:
        raise
    except QueueCapacityExceeded as exc:
        raise HTTPException(
            status_code=429,
            detail={
                "code": "shared_queue_full",
                "message": "Wait for active work to finish before retrying.",
            },
        ) from exc
    except (AgentStoreError, ValueError) as exc:
        raise _store_failure(exc) from exc
    if not result.get("idempotent_replay"):
        state._WORKER_WAKE.set()
    response_case = _case_or_404(canonical_case)
    return {
        "job": _public_scenario_job_link(result["link"]),
        "scenario": _public_scenario(result["scenario"], response_case),
        "idempotent_replay": bool(result.get("idempotent_replay")),
        "execution": _scenario_execution_payload(canonical_case),
        **_scenario_response_context(canonical_case),
    }


@router.get("/cases/{case_id}/events")
def list_case_events(
    case_id: str,
    after_event_id: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1, le=1_000),
) -> dict[str, Any]:
    canonical = _validate_identifier(case_id, _CASE_ID_RE)
    try:
        records = state.AGENT_STORE.list_decision_events(
            canonical,
            after_event_sequence=after_event_id,
            limit=limit,
        )
    except (AgentStoreError, ValueError) as exc:
        raise _store_failure(exc) from exc
    events = [serializers.public_decision_event(item) for item in records]
    return {
        "events": events,
        "next_event_id": events[-1]["event_sequence"] if events else after_event_id,
        "next_cursor": events[-1]["event_sequence"] if events else after_event_id,
    }


@router.get("/cases/{case_id}/messages")
def list_case_messages(
    case_id: str,
    limit: int = Query(default=20, ge=1, le=100),
    before_message_sequence: int | None = Query(default=None, ge=1),
) -> dict[str, Any]:
    canonical = _validate_identifier(case_id, _CASE_ID_RE)
    try:
        records = state.AGENT_STORE.list_decision_messages(
            canonical,
            limit=limit,
            before_message_sequence=before_message_sequence,
        )
    except (AgentStoreError, ValueError) as exc:
        raise _store_failure(exc) from exc
    return {"messages": [serializers.public_decision_message(item) for item in records]}


@router.post("/cases/{case_id}/messages", status_code=202)
def create_case_message(
    case_id: str,
    request_payload: DecisionMessageCreateRequest,
) -> dict[str, Any]:
    canonical = _validate_identifier(case_id, _CASE_ID_RE)
    before = _case_or_404(canonical)
    try:
        turn = state.AGENT_STORE.create_decision_turn(
            canonical,
            client_message_id=request_payload.client_message_id,
            user_message=request_payload.message,
            operator_name=request_payload.operator_name,
            expected_revision=request_payload.expected_revision,
        )
    except (AgentStoreError, ValueError) as exc:
        raise _store_failure(exc) from exc
    after = _case_or_404(canonical)
    created = int(after.get("revision") or 0) > int(before.get("revision") or 0)
    return {"turn": serializers.public_decision_turn(turn), "created": created}


def _decision_worker_id() -> str:
    return f"decision-agent:{config.SERVER_SESSION_ID}"[:200]


def _safe_failure(code: object) -> tuple[str, str, str]:
    canonical = str(code or "agent_unavailable")
    if canonical not in _SAFE_AGENT_FAILURE_CODES:
        canonical = "agent_unavailable"
    if canonical == "timeout":
        return (
            canonical,
            "The Decision Agent did not finish within the bounded response time.",
            "The Decision Agent timed out. Your message is preserved; deterministic readiness remains available.",
        )
    if canonical == "agent_interrupted":
        return (
            canonical,
            "The Decision Agent process stopped before completing the response.",
            "The prior Decision Agent response was interrupted. Your message is preserved; please try again.",
        )
    return (
        canonical,
        "The Decision Agent is unavailable.",
        "The Decision Agent is unavailable. Deterministic readiness and existing manual workflows remain available.",
    )


async def _execute_claimed_turn(
    turn: dict[str, Any],
    *,
    worker_id: str,
    trace_id: str,
) -> None:
    turn_id = str(turn["id"])
    case_id = str(turn["case_id"])
    claim_token = str(turn.get("claim_token") or "")
    user_message = turn.get("user_message") or {}
    message_text = str(user_message.get("content_text") or "")
    try:
        result = await asyncio.wait_for(
            decision_agent_module.run_decision_agent_turn(
                case_id,
                message_text,
                agent_store=state.AGENT_STORE,
                trace_id=trace_id,
            ),
            timeout=float(config.DECISION_AGENT_TIMEOUT_SECONDS) + 1.0,
        )
        result_trace_id = str(result.get("trace_id") or trace_id)
        if result_trace_id != trace_id:
            logger.warning("Decision Agent returned a mismatched trace identity")
            result_trace_id = trace_id
        state.AGENT_STORE.complete_decision_turn(
            turn_id,
            worker_id=worker_id,
            claim_token=claim_token,
            assistant_message=str(result.get("assistant_message") or ""),
            structured_output=result.get("structured_output"),
            citations=result.get("citations") or (),
            tool_outcomes=result.get("tool_outcomes") or (),
            trace_id=result_trace_id,
        )
    except asyncio.CancelledError:
        raise
    except TimeoutError as exc:
        code, detail, assistant_message = _safe_failure("timeout")
        try:
            state.AGENT_STORE.fail_decision_turn(
                turn_id,
                worker_id=worker_id,
                claim_token=claim_token,
                assistant_message=assistant_message,
                error_code=code,
                error_detail=detail,
                structured_output={
                    "answer": assistant_message,
                    "basis": ["Deterministic timeout fallback"],
                    "limits": ["No model response was used."],
                    "next_actions": ["Inspect deterministic readiness or retry later."],
                    "non_runnable": True,
                },
                trace_id=trace_id,
            )
        except (AgentStoreError, ValueError):
            logger.error("Could not persist Decision Agent timeout", exc_info=True)
    except Exception as exc:
        code, detail, assistant_message = _safe_failure(getattr(exc, "code", None))
        exc_trace_id = str(getattr(exc, "trace_id", None) or trace_id)
        try:
            state.AGENT_STORE.fail_decision_turn(
                turn_id,
                worker_id=worker_id,
                claim_token=claim_token,
                assistant_message=assistant_message,
                error_code=code,
                error_detail=detail,
                structured_output={
                    "answer": assistant_message,
                    "basis": ["Deterministic agent-unavailable fallback"],
                    "limits": ["No model response was used."],
                    "next_actions": ["Inspect deterministic readiness or retry later."],
                    "non_runnable": True,
                },
                trace_id=exc_trace_id,
            )
        except (AgentStoreError, ValueError):
            logger.error("Could not persist terminal Decision Agent failure", exc_info=True)


def _task_finished(turn_id: str, task: asyncio.Task[None]) -> None:
    if state.DECISION_AGENT_TASKS.get(turn_id) is task:
        state.DECISION_AGENT_TASKS.pop(turn_id, None)
    if not task.cancelled():
        try:
            task.exception()
        except Exception:
            logger.error("Decision Agent task terminated unexpectedly", exc_info=True)


def _ensure_turn_task(case_id: str, turn_id: str) -> dict[str, Any]:
    turn = state.AGENT_STORE.get_decision_turn(turn_id)
    if turn is None or str(turn.get("case_id")) != case_id:
        raise _not_found()
    existing = state.DECISION_AGENT_TASKS.get(turn_id)
    if isinstance(existing, asyncio.Task) and not existing.done():
        return turn
    worker_id = _decision_worker_id()
    if turn.get("state") == "claimed" and turn.get("worker_id") != worker_id:
        state.AGENT_STORE.mark_stale_claimed_decision_turns_failed(
            before=datetime.now(timezone.utc)
            - timedelta(seconds=config.DECISION_AGENT_TURN_STALE_SECONDS),
            error_code="agent_interrupted",
            error_detail=(
                "The Decision Agent process stopped before the response completed."
            ),
        )
        turn = state.AGENT_STORE.get_decision_turn(turn_id) or turn
    trace_id = str(turn.get("trace_id") or f"trace_{uuid.uuid4().hex}")
    if turn.get("state") == "pending":
        try:
            turn = state.AGENT_STORE.claim_decision_turn(
                turn_id,
                worker_id=worker_id,
                trace_id=trace_id,
            )
        except (InvalidStateTransition, StoreConflict):
            turn = state.AGENT_STORE.get_decision_turn(turn_id) or turn
    if turn.get("state") == "claimed" and turn.get("worker_id") == worker_id:
        task = asyncio.create_task(
            _execute_claimed_turn(turn, worker_id=worker_id, trace_id=trace_id),
            name=f"decision-agent-{turn_id}",
        )
        state.DECISION_AGENT_TASKS[turn_id] = task
        task.add_done_callback(lambda completed: _task_finished(turn_id, completed))
    return turn


def _sse_event(record: dict[str, Any]) -> str:
    event_type = record.get("event_type")
    if event_type == "decision_turn_completed":
        name = "final"
    elif event_type == "decision_turn_failed":
        name = "error"
    else:
        name = "status"
    payload = {
        "event": record,
        **(record.get("payload") if isinstance(record.get("payload"), dict) else {}),
    }
    if event_type == "decision_turn_failed":
        error = payload.get("error") if isinstance(payload.get("error"), dict) else {}
        message_record = (
            payload.get("message") if isinstance(payload.get("message"), dict) else {}
        )
        payload["code"] = error.get("code") or "agent_unavailable"
        payload["message"] = message_record.get("content") or "The Decision Agent is unavailable."
        payload["recovery_action"] = {
            "id": "continue_without_agent",
            "label": "Continue with deterministic readiness",
            "deep_link": "#autonomy-readiness",
        }
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return (
        f"id: {int(record['event_sequence'])}\n"
        f"event: {name}\n"
        f"data: {encoded}\n\n"
    )


@router.get("/cases/{case_id}/message-stream/{turn_id}")
async def stream_case_message(
    request: Request,
    case_id: str,
    turn_id: str,
    after_event_id: int = Query(default=0, ge=0),
) -> StreamingResponse:
    canonical_case_id = _validate_identifier(case_id, _CASE_ID_RE)
    canonical_turn_id = _validate_identifier(turn_id, _TURN_ID_RE)
    try:
        _ensure_turn_task(canonical_case_id, canonical_turn_id)
    except HTTPException:
        raise
    except (AgentStoreError, ValueError) as exc:
        raise _store_failure(exc) from exc

    async def event_stream():
        cursor = after_event_id
        idle_iterations = 0
        while True:
            if await request.is_disconnected():
                return
            try:
                events = state.AGENT_STORE.list_decision_events(
                    canonical_case_id,
                    after_event_sequence=cursor,
                    turn_id=canonical_turn_id,
                    limit=100,
                )
            except (AgentStoreError, ValueError):
                logger.warning("Decision Agent event replay failed", exc_info=True)
                return
            if events:
                idle_iterations = 0
                for event_record in events:
                    public_event = serializers.public_decision_event(event_record)
                    cursor = int(public_event["event_sequence"])
                    yield _sse_event(public_event)
            else:
                idle_iterations += 1
            turn = state.AGENT_STORE.get_decision_turn(canonical_turn_id)
            if turn is None or turn.get("state") in {"completed", "failed"}:
                return
            if idle_iterations >= 60:
                idle_iterations = 0
                yield ": keepalive\n\n"
            await asyncio.sleep(0.25)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-store",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/cases/{case_id}/evidence")
def list_case_evidence(case_id: str) -> dict[str, Any]:
    canonical = _validate_identifier(case_id, _CASE_ID_RE)
    try:
        records = state.AGENT_STORE.list_decision_evidence_assets(
            canonical,
            include_removed=False,
            limit=100,
        )
    except (AgentStoreError, ValueError) as exc:
        raise _store_failure(exc) from exc
    return {"evidence": [serializers.public_evidence_asset(item) for item in records]}


@router.post("/cases/{case_id}/evidence", status_code=201)
async def upload_case_evidence(
    case_id: str,
    file: UploadFile = File(...),
    evidence_class: str = Form(..., min_length=1, max_length=100),
    operator_name: str = Form(..., min_length=1, max_length=300),
    expected_revision: int | None = Form(default=None, ge=0),
) -> dict[str, Any]:
    canonical = _validate_identifier(case_id, _CASE_ID_RE)
    _case_or_404(canonical)
    operator = operator_name.strip()
    try:
        asset = await evidence.ingest_evidence_upload(
            state.AGENT_STORE,
            canonical,
            file,
            evidence_class=evidence_class.strip(),
            operator_name=operator,
            expected_revision=expected_revision,
        )
    except evidence.EvidencePolicyError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"code": exc.code, "message": exc.detail},
        ) from exc
    except (AgentStoreError, ValueError) as exc:
        raise _store_failure(exc) from exc
    _reconcile_case_state(canonical, operator)
    refreshed = state.AGENT_STORE.get_decision_evidence_asset(str(asset["id"])) or asset
    return {
        "evidence": serializers.public_evidence_asset(refreshed),
        "readiness": _readiness_or_503(canonical),
    }


@router.get("/cases/{case_id}/evidence/{evidence_id}")
def get_case_evidence(case_id: str, evidence_id: str) -> dict[str, Any]:
    canonical_case = _validate_identifier(case_id, _CASE_ID_RE)
    canonical_evidence = _validate_identifier(evidence_id, _EVIDENCE_ID_RE)
    asset = state.AGENT_STORE.get_decision_evidence_asset(canonical_evidence)
    if not asset or str(asset.get("case_id")) != canonical_case or asset.get("removed_at"):
        raise _not_found()
    return {"evidence": serializers.public_evidence_asset(asset)}


@router.post(
    "/cases/{case_id}/evidence/{evidence_id}/candidates/{candidate_id}/review"
)
def review_evidence_candidate(
    case_id: str,
    evidence_id: str,
    candidate_id: str,
    request_payload: EvidenceReviewRequest,
) -> dict[str, Any]:
    canonical_case = _validate_identifier(case_id, _CASE_ID_RE)
    canonical_evidence = _validate_identifier(evidence_id, _EVIDENCE_ID_RE)
    canonical_candidate = _validate_identifier(candidate_id, _CANDIDATE_ID_RE)
    asset = state.AGENT_STORE.get_decision_evidence_asset(canonical_evidence)
    if not asset or str(asset.get("case_id")) != canonical_case or asset.get("removed_at"):
        raise _not_found()
    candidate = next(
        (
            item
            for item in asset.get("candidates") or ()
            if item.get("id") == canonical_candidate
        ),
        None,
    )
    if candidate is None:
        raise _not_found()
    if (
        request_payload.decision == "accepted"
        and asset.get("evidence_class") in lifecycle.PROVISIONAL_EVIDENCE_CLASSES
        and not request_payload.rationale
    ):
        raise HTTPException(
            status_code=422,
            detail={
                "code": "provisional_rationale_required",
                "message": "Accepting provisional evidence requires a rationale.",
            },
        )
    try:
        receipt = state.AGENT_STORE.record_decision_evidence_review(
            canonical_candidate,
            decision=request_payload.decision,
            operator_name=request_payload.operator_name,
            rationale=request_payload.rationale,
            expected_revision=request_payload.expected_revision,
        )
    except (AgentStoreError, ValueError) as exc:
        raise _store_failure(exc) from exc
    _reconcile_case_state(canonical_case, request_payload.operator_name)
    refreshed = state.AGENT_STORE.get_decision_evidence_asset(canonical_evidence)
    assert refreshed is not None
    return {
        "receipt": serializers.public_evidence_receipt(receipt),
        "evidence": serializers.public_evidence_asset(refreshed),
        "readiness": _readiness_or_503(canonical_case),
    }


@router.delete("/cases/{case_id}/evidence/{evidence_id}")
def delete_case_evidence(
    case_id: str,
    evidence_id: str,
    request_payload: EvidenceDeleteRequest,
) -> dict[str, Any]:
    canonical_case = _validate_identifier(case_id, _CASE_ID_RE)
    canonical_evidence = _validate_identifier(evidence_id, _EVIDENCE_ID_RE)
    try:
        removed = evidence.tombstone_evidence_asset(
            state.AGENT_STORE,
            canonical_case,
            canonical_evidence,
            operator_name=request_payload.operator_name,
            reason=request_payload.reason,
            expected_revision=request_payload.expected_revision,
        )
    except evidence.EvidencePolicyError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"code": exc.code, "message": exc.detail},
        ) from exc
    except (AgentStoreError, ValueError) as exc:
        raise _store_failure(exc) from exc
    _reconcile_case_state(canonical_case, request_payload.operator_name)
    return {
        "removed": True,
        "evidence": serializers.public_evidence_asset(removed),
        "readiness": _readiness_or_503(canonical_case),
    }


@router.get("/cases/{case_id}/evidence/{evidence_id}/download")
def download_case_evidence(case_id: str, evidence_id: str) -> Response:
    canonical_case = _validate_identifier(case_id, _CASE_ID_RE)
    canonical_evidence = _validate_identifier(evidence_id, _EVIDENCE_ID_RE)
    try:
        payload, asset = evidence.verified_evidence_snapshot(
            state.AGENT_STORE,
            canonical_case,
            canonical_evidence,
        )
    except evidence.EvidencePolicyError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"code": exc.code, "message": exc.detail},
        ) from exc
    filename = Path(str(asset.get("display_filename") or "evidence")).name
    return Response(
        content=payload,
        media_type=str(asset.get("detected_media_type") or "application/octet-stream"),
        headers={
            "Cache-Control": "private, no-store",
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename, safe='')}",
            "ETag": f'"{asset["sha256"]}"',
            "X-Content-Type-Options": "nosniff",
        },
    )


async def shutdown_decision_agent_tasks() -> None:
    """Cancel local tasks and persist terminal interruption events on shutdown."""

    tasks = [
        task
        for task in state.DECISION_AGENT_TASKS.values()
        if isinstance(task, asyncio.Task) and not task.done()
    ]
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    state.DECISION_AGENT_TASKS.clear()
    recovery = getattr(state.AGENT_STORE, "mark_stale_claimed_decision_turns_failed", None)
    if callable(recovery):
        recovery(
            before=datetime.now(timezone.utc) + timedelta(seconds=1),
            worker_id=_decision_worker_id(),
            recovery_reason="worker_shutdown",
            error_code="agent_interrupted",
            error_detail="The Decision Agent process stopped before the response completed.",
        )
