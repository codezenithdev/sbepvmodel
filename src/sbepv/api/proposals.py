"""Proposal lifecycle: what the agent may run, and what needs confirmation.

``_proposal_policy`` is the gate. A scenario that reuses a hash-verified reviewed
baseline can execute directly; anything that changes the input context needs either
explicit user confirmation or a fresh trip through the visible calibration review.
The agent never makes that decision -- it only reports the status returned here.
"""

from __future__ import annotations

import logging
import secrets
from copy import deepcopy
from typing import Any

from fastapi import HTTPException

from typing import Literal

from sbepv.agent.scenario_math import _canonical_request, _same_input_context
from sbepv.api import config, state, validation
from sbepv.api.baselines import (
    _active_model_jobs,
    _baseline_calibration_profile,
    _has_current_annual_temporal_semantics,
    _inherited_annual_calibration_provenance,
    _reviewed_baseline_data_quality,
    _verified_baseline_source,
)
from sbepv.api.job_store import _cache_job_record, _get_job_record
from sbepv.api.schemas import AnnualRunRequest, ChatRequest
from sbepv.store import QueueCapacityExceeded

logger = logging.getLogger(__name__)


def _proposal_policy(
    *,
    mode: str,
    comparison_kind: str,
    source_available: bool,
    baseline_missing: bool = False,
) -> tuple[bool, str]:
    confirmation_reasons: list[str] = []
    informational_reasons: list[str] = []
    if baseline_missing:
        confirmation_reasons.append("A completed baseline must be run first")
    if mode == "annual":
        confirmation_reasons.append("Annual scenarios always require confirmation")
    if comparison_kind == "cross_run":
        informational_reasons.append(
            "Fresh Bazefield data will be fetched; the interval or source data will differ, so results are descriptive only"
        )
    if comparison_kind == "same_input" and not source_available and not baseline_missing:
        confirmation_reasons.append(
            "The baseline source file or SHA-256 fingerprint is unavailable"
        )
    if _active_model_jobs():
        informational_reasons.append(
            "Another model job is active; this run will remain queued"
        )
    required = bool(confirmation_reasons)
    reasons = confirmation_reasons + informational_reasons
    return required, "; ".join(reasons) if reasons else (
        "Same interval and source data; only the requested parameters change"
    )


def _create_baseline_proposal(
    req: ChatRequest,
    mode: Literal["validation", "annual"],
    requested_overrides: dict[str, Any],
) -> dict[str, Any]:
    if not req.current_config:
        raise HTTPException(
            status_code=422,
            detail="No completed baseline exists. Use the visible dashboard form to run a baseline first.",
        )
    _, effective = _canonical_request(mode, req.current_config)
    proposal = state.AGENT_STORE.create_proposal(
        mode=mode,
        effective_request=effective,
        changes=[],
        baseline_id=None,
        comparison_kind="same_input",
        confirmation_required=True,
        confirmation_reason="No completed baseline exists for this mode",
        confirmation_metadata={
            "job_kind": "baseline",
            "deferred_scenario_overrides": requested_overrides,
        },
    )
    return proposal


def _calibration_review_required(
    *,
    effective_request: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return a non-mutating handoff to the visible calibration review flow."""

    message = (
        "This calibration request needs a visible Bazefield data-quality review "
        "before a model job can start. Select the requested range and settings in "
        "the Calibration form, retrieve the data, review every irregularity, choose "
        "Retain or Exclude where offered, and then apply the reviewed run. No Solar "
        "Agent proposal or model job was created."
    )
    request = deepcopy(effective_request) if effective_request else None
    result: dict[str, Any] = {
        "status": "data_review_required",
        "message": message,
    }
    action: dict[str, Any] = {
        "type": "data_review_required",
        "mode": "validation",
        "message": message,
    }
    if request is not None:
        result["effective_request"] = request
        action["effective_request"] = request
    return result, action


def _create_candidate_proposal(
    *,
    mode: Literal["validation", "annual"],
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    changes: list[dict[str, Any]],
    supersedes_id: str | None = None,
    scenario_sweep: dict[str, Any] | None = None,
) -> dict[str, Any]:
    baseline_mode = str(baseline.get("mode", "validation"))
    if (
        mode == "annual"
        and baseline_mode == "annual"
        and not _has_current_annual_temporal_semantics(baseline)
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                "The selected Annual baseline uses legacy or incompatible "
                "weather timestamp semantics. Run a fresh Annual baseline "
                "before creating a scenario."
            ),
        )
    baseline_request = baseline.get("request") or {}
    source_path, source_hash = _verified_baseline_source(baseline)
    same_window = mode == baseline_mode and _same_input_context(
        mode, baseline_request, candidate
    )
    reusable = same_window and bool(source_path and source_hash)
    # A fresh fetch is not scientifically same-input even when the requested
    # timestamps match: only an identical verified source earns that label.
    comparison_kind = "same_input" if reusable else "cross_run"
    confirmation_required, confirmation_reason = _proposal_policy(
        mode=mode,
        comparison_kind=comparison_kind,
        source_available=bool(source_path and source_hash),
    )
    confirmation_metadata: dict[str, Any] = {
        "job_kind": "candidate",
        "source_reusable": reusable,
        "baseline_source_path": source_path if reusable else None,
        "baseline_source_hash": source_hash if reusable else None,
    }
    if scenario_sweep:
        confirmation_metadata["scenario_sweep"] = deepcopy(scenario_sweep)
    return state.AGENT_STORE.create_proposal(
        mode=mode,
        effective_request=candidate,
        changes=changes,
        baseline_id=str(baseline["id"]),
        comparison_kind=comparison_kind,
        confirmation_required=confirmation_required,
        confirmation_reason=confirmation_reason,
        confirmation_metadata=confirmation_metadata,
        supersedes_id=supersedes_id,
    )


def _proposal_confirmation_spec(
    proposal: dict[str, Any], *, automatic: bool = False
) -> dict[str, Any]:
    """Validate one proposal and build its immutable store confirmation input."""

    if proposal.get("confirmed_job_id"):
        existing = _get_job_record(str(proposal["confirmed_job_id"]))
        if existing is None:
            raise HTTPException(
                status_code=409,
                detail="The confirmed proposal references an unavailable job.",
            )
        return {"proposal_id": str(proposal["id"])}
    metadata = proposal.get("confirmation_metadata") or {}
    job_kind = str(metadata.get("job_kind", "candidate"))
    source_path: str | None = None
    source_hash: str | None = None
    provenance: dict[str, Any] = {}
    scenario_sweep = metadata.get("scenario_sweep")
    if isinstance(scenario_sweep, dict):
        provenance["scenario_sweep"] = deepcopy(scenario_sweep)
    baseline: dict[str, Any] | None = None
    if proposal.get("baseline_id"):
        baseline = _get_job_record(str(proposal["baseline_id"]))
    if (
        proposal.get("mode") == "annual"
        and job_kind == "candidate"
        and baseline is not None
        and baseline.get("mode") == "annual"
        and not _has_current_annual_temporal_semantics(baseline)
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                "The Annual baseline bound to this proposal uses legacy or "
                "incompatible weather timestamp semantics. Run a fresh Annual "
                "baseline before confirming a scenario."
            ),
        )
    validation_quality: dict[str, Any] | None = None
    effective_request = dict(proposal.get("effective_request") or {})
    annual_interval_seconds: int | None = None
    if proposal.get("mode") == "annual":
        # Revalidate the immutable proposal at confirmation time. This keeps
        # legacy or directly persisted coarse requests from bypassing the
        # current annual physics safety contract and reaching the job queue.
        annual_interval_seconds = validation._annual_interval_seconds(
            AnnualRunRequest(**effective_request)
        )
    calibration_requested = bool(effective_request.get("calibrate_model", True))
    if proposal.get("mode") == "validation" and calibration_requested:
        if (
            job_kind != "candidate"
            or proposal.get("comparison_kind") != "same_input"
            or baseline is None
            or baseline.get("state") != "done"
        ):
            raise HTTPException(
                status_code=409,
                detail=(
                    "Calibration jobs that do not reuse a completed reviewed baseline "
                    "must start from the visible Calibration data-quality review."
                ),
            )
        validation_quality = _reviewed_baseline_data_quality(baseline)
        if validation_quality is None:
            raise HTTPException(
                status_code=409,
                detail=(
                    "The calibration baseline is not bound to a hash-verified "
                    "data-quality review. Use the visible Calibration form to review "
                    "the requested data before running this scenario."
                ),
            )
    if (
        proposal.get("baseline_id")
        and proposal.get("comparison_kind") == "same_input"
    ):
        source_path, source_hash = _verified_baseline_source(baseline)
        if not source_path or not source_hash:
            raise HTTPException(
                status_code=409,
                detail="The baseline source fingerprint is no longer valid. Confirm a fresh baseline run.",
            )
    if (
        proposal.get("mode") == "annual"
        and job_kind == "candidate"
        and proposal.get("comparison_kind") == "same_input"
        and baseline is not None
        and source_hash is not None
    ):
        baseline_audit = (baseline.get("provenance") or {}).get(
            "annual_source_audit"
        )
        if isinstance(baseline_audit, dict):
            recorded_hash = baseline_audit.get("source_sha256")
            recorded_interval = baseline_audit.get("interval_seconds")
            audit_is_verified = (
                isinstance(recorded_hash, str)
                and secrets.compare_digest(
                    recorded_hash.strip().lower(), source_hash.strip().lower()
                )
                and recorded_interval == annual_interval_seconds
                and isinstance(baseline_audit.get("source_quality"), dict)
                and isinstance(baseline_audit.get("warnings"), list)
            )
            if audit_is_verified:
                provenance["annual_source_audit"] = deepcopy(baseline_audit)
    if (
        proposal.get("mode") == "annual"
        and job_kind == "candidate"
        and baseline is not None
        and baseline.get("mode") == "annual"
    ):
        baseline_provenance = baseline.get("provenance") or {}
        has_calibration_provenance = any(
            baseline_provenance.get(field) is not None
            for field in ("calibration_profile", "calibration_application")
        )
        if has_calibration_provenance:
            if (
                baseline.get("state") != "done"
                or proposal.get("comparison_kind") != "same_input"
            ):
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "A calibrated annual baseline can only be reused for a "
                        "same-input scenario. Run the current Annual form to "
                        "resolve and confirm calibration for this request."
                    ),
                )
            try:
                inherited = _inherited_annual_calibration_provenance(
                    baseline,
                    candidate_request=effective_request,
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "The calibrated annual baseline provenance is invalid. "
                        f"Run the current Annual form again: {exc}"
                    ),
                ) from exc
            if inherited is not None:
                provenance.update(inherited)
    if (
        proposal.get("mode") == "validation"
        and calibration_requested
        and job_kind == "candidate"
        and proposal.get("baseline_id")
    ):
        if baseline is None or baseline.get("state") != "done":
            raise HTTPException(
                status_code=409,
                detail="The completed baseline bound to this proposal is unavailable.",
            )
        try:
            profile = _baseline_calibration_profile(
                baseline,
                candidate_request=dict(proposal.get("effective_request") or {}),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=409,
                detail=(
                    "The reviewed baseline calibration profile is invalid or "
                    f"does not cover this date range: {exc}"
                ),
            ) from exc
        if profile is None:
            raise HTTPException(
                status_code=409,
                detail=(
                    "The reviewed baseline does not contain a frozen seasonal "
                    "calibration profile. Re-run it through the visible Calibration "
                    "data-quality review."
                ),
            )
        provenance["calibration_profile"] = profile
        provenance["data_quality"] = validation_quality
    return {
        "proposal_id": str(proposal["id"]),
        "job_kind": job_kind,
        "confirmation_metadata": {"automatic": automatic},
        "source_path": source_path,
        "source_hash": source_hash,
        "provenance": provenance or None,
    }


def _confirm_durable_proposals(
    proposals: list[dict[str, Any]], *, automatic: bool = False
) -> list[dict[str, Any]]:
    """Validate and enqueue a proposal group in one durable transaction."""

    if not proposals:
        raise ValueError("proposals must not be empty")
    confirmations = [
        _proposal_confirmation_spec(proposal, automatic=automatic)
        for proposal in proposals
    ]
    try:
        jobs = state.AGENT_STORE.confirm_proposals_batch(
            confirmations,
            max_active_jobs=config.MAX_ACTIVE_MODEL_JOBS,
        )
    except QueueCapacityExceeded as exc:
        raise HTTPException(
            status_code=429,
            detail="The model queue is full. Wait for an active run to finish and retry.",
        ) from exc
    for job in jobs:
        _cache_job_record(job)
    state._WORKER_WAKE.set()
    return jobs


def _confirm_durable_proposal(
    proposal: dict[str, Any], *, automatic: bool = False
) -> dict[str, Any]:
    return _confirm_durable_proposals([proposal], automatic=automatic)[0]
