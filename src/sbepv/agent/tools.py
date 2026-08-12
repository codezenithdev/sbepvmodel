"""Handlers for the tools the Solar Agent is allowed to call.

Each returns a status the agent must not contradict: a run is only ``started``
when this layer actually queued one. ``data_review_required`` means the request
needs the visible calibration review first and nothing was created.
"""

from __future__ import annotations

import logging
from copy import deepcopy
from typing import Any

from fastapi import HTTPException

from sbepv import model
import uuid
from typing import Literal

from sbepv.agent.scenario_math import (
    _apply_dependent_scenario_overrides,
    _canonical_request,
    _explicit_overrides,
    _parameter_sweep_values,
    _same_input_context,
    _scenario_changes,
)
from sbepv.agent.tool_schemas import SCENARIO_FIELD_LABELS
from sbepv.api import config, job_store, state
from sbepv.api.baselines import (
    _active_model_jobs,
    _baseline_calibration_profile,
    _reviewed_baseline_data_quality,
    _verified_baseline_source,
    _visible_baseline,
)
from sbepv.api.proposals import (
    _calibration_review_required,
    _confirm_durable_proposal,
    _confirm_durable_proposals,
    _create_baseline_proposal,
    _create_candidate_proposal,
)
from sbepv.api.schemas import ChatRequest
from sbepv.api.serializers import _public_job, _public_proposal
from sbepv.store import QueueCapacityExceeded

logger = logging.getLogger(__name__)


def _handle_scenario_tool(
    req: ChatRequest, arguments: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    overrides = _explicit_overrides(arguments)
    target_mode = overrides.pop("mode", req.active_mode)
    if target_mode not in {"validation", "annual"}:
        raise HTTPException(status_code=422, detail="Unsupported analysis mode.")
    if target_mode == "validation" and "years" in overrides:
        raise HTTPException(
            status_code=422,
            detail="MIDC year selection can only be changed for annual runs.",
        )
    validation_only = {"from_time", "to_time"}
    if target_mode == "annual" and validation_only.intersection(overrides):
        raise HTTPException(
            status_code=422,
            detail="Start and end times can only be changed for calibration runs.",
        )
    if "interval_value" in overrides and "interval_unit" not in overrides:
        raise HTTPException(
            status_code=422,
            detail="An interval change must explicitly include minutes, hours, or days.",
        )

    with state._ORCHESTRATION_LOCK:
        baseline = _visible_baseline(
            req,
            target_mode,
            allow_mode_change=target_mode != req.active_mode,
        )
        if baseline is None:
            if target_mode == "validation":
                effective_request: dict[str, Any] | None = None
                if req.current_config:
                    candidate_values = dict(req.current_config)
                    candidate_values.update(overrides)
                    try:
                        _, effective_request = _canonical_request(
                            "validation", candidate_values
                        )
                    except HTTPException:
                        effective_request = None
                return _calibration_review_required(
                    effective_request=effective_request
                )
            active_baseline = next(
                (
                    job
                    for job in _active_model_jobs()
                    if job.get("mode") == req.active_mode
                    and job.get("kind") in {"baseline", "manual"}
                ),
                None,
            )
            if active_baseline:
                raise HTTPException(
                    status_code=409,
                    detail="A baseline for the visible mode is already queued or running.",
                )
            deferred = dict(overrides)
            if target_mode != req.active_mode:
                deferred["mode"] = target_mode
            proposal = _create_baseline_proposal(req, req.active_mode, deferred)
            public = _public_proposal(proposal)
            return (
                {
                    "status": "baseline_required",
                    "message": "Run the visible dashboard configuration as a baseline before the requested scenario.",
                    "proposal": public,
                },
                {"type": "proposal", "proposal": public},
            )

        baseline_request = dict(baseline.get("request") or {})
        overrides = _apply_dependent_scenario_overrides(overrides, baseline_request)
        candidate_values = dict(baseline_request)
        candidate_values.update(overrides)
        _, candidate = _canonical_request(
            target_mode,
            candidate_values,
            allow_resolved_partial=(
                target_mode == "annual" and "years" not in overrides
            ),
        )
        changes = _scenario_changes(baseline_request, candidate)
        baseline_mode = str(baseline.get("mode", req.active_mode))
        if baseline_mode != target_mode:
            changes.insert(
                0,
                {
                    "field": "mode",
                    "label": SCENARIO_FIELD_LABELS["mode"],
                    "from": baseline_mode,
                    "to": target_mode,
                },
            )
        if not changes:
            raise HTTPException(
                status_code=422,
                detail="The requested settings are already active in the selected baseline.",
            )
        if target_mode == "validation":
            source_path, source_hash = _verified_baseline_source(baseline)
            same_verified_input = (
                baseline_mode == "validation"
                and _same_input_context("validation", baseline_request, candidate)
                and bool(source_path and source_hash)
            )
            calibration_requested = bool(candidate.get("calibrate_model", True))
            reusable_calibration = (
                same_verified_input
                and _reviewed_baseline_data_quality(baseline) is not None
            )
            if calibration_requested and not reusable_calibration:
                return _calibration_review_required(
                    effective_request=candidate
                )
        proposal = _create_candidate_proposal(
            mode=target_mode,
            baseline=baseline,
            candidate=candidate,
            changes=changes,
        )
        if not proposal["confirmation_required"]:
            job = _confirm_durable_proposal(proposal, automatic=True)
            public_job = _public_job(job)
            if proposal["comparison_kind"] == "cross_run":
                scenario_label = (
                    "calibration"
                    if bool(candidate.get("calibrate_model", True))
                    else "physics-model"
                )
                started_message = (
                    f"The {scenario_label} scenario was queued automatically. It will pull fresh "
                    "data from Bazefield. The interval or source data will differ, so the "
                    "comparison is descriptive only."
                )
            else:
                source_label = (
                    "source data"
                    if bool(candidate.get("calibrate_model", True))
                    else "verified physics-model source data"
                )
                started_message = (
                    "The scenario was queued automatically with the same interval and "
                    f"{source_label}; only the requested parameters will change."
                )
            return (
                {
                    "status": "started",
                    "message": started_message,
                    "job": public_job,
                },
                {"type": "job_started", "job": public_job},
            )
        public = _public_proposal(proposal)
        return (
            {
                "status": "confirmation_required",
                "message": proposal.get("confirmation_reason"),
                "proposal": public,
            },
            {"type": "proposal", "proposal": public},
        )


def _handle_parameter_sweep_tool(
    req: ChatRequest, arguments: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    requested_mode, parameter, parameter_config, values = (
        _parameter_sweep_values(arguments)
    )
    target_mode: Literal["validation", "annual"] = (
        requested_mode or req.active_mode
    )

    with state._ORCHESTRATION_LOCK:
        baseline = _visible_baseline(req, target_mode)
        if baseline is None:
            if target_mode == "validation":
                effective_request: dict[str, Any] | None = None
                if req.current_config:
                    candidate_values = dict(req.current_config)
                    candidate_values.update(
                        _apply_dependent_scenario_overrides(
                            {parameter: values[0]}, candidate_values
                        )
                    )
                    try:
                        _, effective_request = _canonical_request(
                            "validation", candidate_values
                        )
                    except HTTPException:
                        effective_request = None
                return _calibration_review_required(
                    effective_request=effective_request
                )
            active_baseline = next(
                (
                    job
                    for job in _active_model_jobs()
                    if job.get("mode") == target_mode
                    and job.get("kind") in {"baseline", "manual"}
                ),
                None,
            )
            if active_baseline:
                raise HTTPException(
                    status_code=409,
                    detail="A baseline for the visible mode is already queued or running.",
                )
            proposal = _create_baseline_proposal(req, target_mode, {})
            public = _public_proposal(proposal)
            return (
                {
                    "status": "baseline_required",
                    "message": (
                        "Run the visible dashboard configuration as a baseline, "
                        "then request the parameter sweep again."
                    ),
                    "proposal": public,
                },
                {"type": "proposal", "proposal": public},
            )

        baseline_request = dict(baseline.get("request") or {})
        candidate_specs: list[dict[str, Any]] = []
        baseline_index: int | None = None
        for index, value in enumerate(values):
            candidate_values = dict(baseline_request)
            candidate_values.update(
                _apply_dependent_scenario_overrides(
                    {parameter: value}, baseline_request
                )
            )
            _, candidate = _canonical_request(
                target_mode,
                candidate_values,
                allow_resolved_partial=target_mode == "annual",
            )
            changes = _scenario_changes(baseline_request, candidate)
            if not changes:
                baseline_index = index
                continue
            candidate_specs.append(
                {
                    "index": index,
                    "value": value,
                    "candidate": candidate,
                    "changes": changes,
                }
            )

        if not candidate_specs:
            raise HTTPException(
                status_code=422,
                detail=(
                    "The selected baseline already represents every requested "
                    "sweep value."
                ),
            )

        if target_mode == "validation":
            source_path, source_hash = _verified_baseline_source(baseline)
            same_verified_input = (
                str(baseline.get("mode")) == "validation"
                and bool(source_path and source_hash)
            )
            calibration_requested = bool(
                candidate_specs[0]["candidate"].get("calibrate_model", True)
            )
            reusable_calibration = (
                same_verified_input
                and _reviewed_baseline_data_quality(baseline) is not None
            )
            if calibration_requested and not reusable_calibration:
                return _calibration_review_required(
                    effective_request=candidate_specs[0]["candidate"]
                )
            if calibration_requested:
                try:
                    profile = _baseline_calibration_profile(
                        baseline,
                        candidate_request=candidate_specs[0]["candidate"],
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
                            "calibration profile. Re-run it through the visible "
                            "Calibration data-quality review."
                        ),
                    )
            try:
                state.AGENT_STORE.ensure_job_capacity(
                    max_active_jobs=config.MAX_ACTIVE_MODEL_JOBS,
                    required=len(candidate_specs),
                )
            except QueueCapacityExceeded as exc:
                raise HTTPException(
                    status_code=429,
                    detail=(
                        "The model queue does not have room for this sweep. "
                        "Wait for active runs to finish and retry."
                    ),
                ) from exc

        baseline_parameter_value = baseline_request.get(parameter)
        if parameter == "iam_a_r" and baseline_request.get("iam_model") != "martin_ruiz":
            baseline_label = "Physical IAM"
            baseline_parameter_value = None
        elif (
            parameter == "curtailment_limit_kw"
            and not baseline_request.get("curtailment_enabled")
        ):
            baseline_label = "Curtailment off"
        else:
            unit = parameter_config.get("unit")
            baseline_label = (
                f"{parameter_config['label']} "
                f"{baseline_parameter_value}"
                + (f" {unit}" if unit else "")
            )

        sweep_id = f"parameter-{uuid.uuid4().hex[:12]}"
        sweep_common: dict[str, Any] = {
            "type": "parameter_sweep",
            "sweep_id": sweep_id,
            "parameter": parameter,
            "label": parameter_config["label"],
            "unit": parameter_config.get("unit"),
            "mode": target_mode,
            "values": values,
            "count": len(values),
            "candidate_count": len(candidate_specs),
            "baseline_job_id": str(baseline["id"]),
            "baseline_index": baseline_index,
            "baseline_value": (
                values[baseline_index] if baseline_index is not None else None
            ),
            "baseline_parameter_value": baseline_parameter_value,
            "baseline_label": baseline_label,
        }
        proposals: list[dict[str, Any]] = []
        for spec in candidate_specs:
            scenario_sweep = {
                **sweep_common,
                "index": spec["index"],
                "value": spec["value"],
            }
            proposal = _create_candidate_proposal(
                mode=target_mode,
                baseline=baseline,
                candidate=spec["candidate"],
                changes=spec["changes"],
                scenario_sweep=scenario_sweep,
            )
            proposals.append(proposal)

        jobs: list[dict[str, Any]] = []
        if proposals and not proposals[0]["confirmation_required"]:
            jobs = _confirm_durable_proposals(proposals, automatic=True)

        public_sweep = deepcopy(sweep_common)
        if jobs:
            public_jobs = [_public_job(job) for job in jobs]
            public_sweep["job_ids"] = [job["job_id"] for job in public_jobs]
            baseline_note = (
                f" The baseline already represents "
                f"{parameter_config['label']} "
                f"{values[baseline_index]:g}"
                + (
                    f" {parameter_config['unit']}"
                    if parameter_config.get("unit")
                    else ""
                )
                + ", so it is reused as that row."
                if baseline_index is not None
                else ""
            )
            source_description = (
                "reviewed, hash-verified baseline source"
                if bool(baseline_request.get("calibrate_model", True))
                else "hash-verified physics-model baseline source"
            )
            message = (
                f"Queued {len(public_jobs)} controlled "
                f"{parameter_config['label']} scenario runs "
                f"from the same {source_description}. The "
                "comparison table will update as each value completes."
                + baseline_note
            )
            return (
                {
                    "status": "batch_started",
                    "message": message,
                    "sweep": public_sweep,
                    "job_ids": public_sweep["job_ids"],
                },
                {
                    "type": "job_batch_started",
                    "sweep": public_sweep,
                    "jobs": public_jobs,
                },
            )

        public_proposals = [_public_proposal(item) for item in proposals]
        public_sweep["proposal_ids"] = [
            item["proposal_id"] for item in public_proposals
        ]
        message = (
            f"The annual {parameter_config['label']} sweep is ready for one "
            "grouped confirmation. "
            f"Confirm it in Scenario Runs to queue {len(public_proposals)} "
            "controlled runs against the same baseline."
        )
        return (
            {
                "status": "confirmation_required",
                "message": message,
                "sweep": public_sweep,
                "proposal_ids": public_sweep["proposal_ids"],
            },
            {
                "type": "proposal_batch",
                "sweep": public_sweep,
                "proposals": public_proposals,
            },
        )


def _handle_iam_ar_sweep_tool(
    req: ChatRequest, arguments: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Backward-compatible adapter for pre-generalization IAM sweep calls."""

    return _handle_parameter_sweep_tool(
        req,
        {
            "mode": arguments.get("mode"),
            "parameter": "iam_a_r",
            "start": arguments.get("start_a_r"),
            "stop": arguments.get("stop_a_r"),
            "increment": arguments.get("increment"),
        },
    )
