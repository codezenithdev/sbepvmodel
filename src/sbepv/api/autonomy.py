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
from sbepv.api.autonomy_schemas import (
    DecisionCaseArchiveRequest,
    DecisionCaseCreateRequest,
    DecisionCaseUpdateRequest,
    DecisionMessageCreateRequest,
    EvidenceDeleteRequest,
    EvidenceReviewRequest,
)
from sbepv.autonomy import decision_agent as decision_agent_module
from sbepv.autonomy import evidence, lifecycle, readiness, serializers
from sbepv.store import (
    AgentStoreError,
    EvidenceLimitExceeded,
    InvalidStateTransition,
    LeaseOwnershipLost,
    RecordNotFound,
    StoreConflict,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/autonomy", tags=["autonomy"])

_CASE_ID_RE = re.compile(r"^case_[A-Za-z0-9]+$")
_TURN_ID_RE = re.compile(r"^dturn_[A-Za-z0-9]+$")
_EVIDENCE_ID_RE = re.compile(r"^evi_[A-Za-z0-9]+$")
_CANDIDATE_ID_RE = re.compile(r"^evc_[A-Za-z0-9]+$")
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
        result = readiness.evaluate_decision_case_readiness(case_id)
        case_record = state.AGENT_STORE.get_decision_case(case_id)
        if not case_record:
            return
        requested = result.get("suggested_case_status")
        current = case_record.get("status")
        if (
            requested in {"evidence_needed", "blocked"}
            and current in {"draft", "evidence_needed", "blocked"}
            and requested != current
            and lifecycle.transition_is_allowed(current, requested)
        ):
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
