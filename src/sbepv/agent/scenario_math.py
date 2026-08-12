"""Turning agent tool arguments into a concrete, comparable model request.

The agent proposes only the fields the user actually mentioned; everything else
is inherited from the selected baseline. These helpers do that merge, apply the
dependent selectors a change implies (asking for an a_r value also selects
Martin-Ruiz IAM), and expand a sweep range into exact decimal steps.
"""

from __future__ import annotations

import math
from copy import deepcopy
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from fastapi import HTTPException

from sbepv import model
from sbepv.agent.tool_schemas import (
    MAX_PARAMETER_SWEEP_VALUES,
    PARAMETER_SWEEP_FIELDS,
    SCENARIO_FIELD_LABELS,
    SCENARIO_OVERRIDE_FIELDS,
    SWEEPABLE_PARAMETER_CONFIG,
)
from sbepv.api.request_context import _run_request_context
from sbepv.api.schemas import AnnualRunRequest, RunRequest
from sbepv.api.validation import (
    _annual_dates,
    _validate_curtailment,
    _validate_run_request,
)


_CAMEL_CONFIG_FIELDS = {
    "fromDate": "from_date",
    "fromTime": "from_time",
    "toDate": "to_date",
    "toTime": "to_time",
    "intervalValue": "interval_value",
    "intervalUnit": "interval_unit",
    "solaredgeInverterEfficiency": "solaredge_inverter_efficiency",
    "solaredgeBosEfficiency": "solaredge_bos_efficiency",
    "solectriaInverterEfficiency": "solectria_inverter_efficiency",
    "solectriaBosEfficiency": "solectria_bos_efficiency",
    "iamModel": "iam_model",
    "iamAr": "iam_a_r",
    "curtailmentEnabled": "curtailment_enabled",
    "curtailmentLimitKw": "curtailment_limit_kw",
}


def _normalise_config_keys(config: dict[str, Any] | None) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in (config or {}).items():
        canonical = _CAMEL_CONFIG_FIELDS.get(key, key)
        if (
            canonical in SCENARIO_OVERRIDE_FIELDS and canonical != "mode"
        ) or canonical == "calibrate_model":
            out[canonical] = value
    return out


def _canonical_request(
    mode: Literal["validation", "annual"],
    config: dict[str, Any],
    *,
    allow_resolved_partial: bool = False,
) -> tuple[RunRequest | AnnualRunRequest, dict[str, Any]]:
    values = _normalise_config_keys(config)
    try:
        request_model: RunRequest | AnnualRunRequest
        if mode == "annual":
            for unsupported in ("from_time", "to_time"):
                values.pop(unsupported, None)
            values.pop("calibrate_model", None)
            request_model = AnnualRunRequest(**values)
        else:
            # A cross-mode proposal may inherit this annual-only selector from
            # the visible baseline; validation keeps the resolved date window.
            values.pop("years", None)
            request_model = RunRequest(**values)
        _validate_run_request(request_model)
        _validate_curtailment(request_model)
        if isinstance(request_model, AnnualRunRequest):
            _annual_dates(
                request_model,
                allow_resolved_partial=allow_resolved_partial,
            )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=422, detail="Invalid model configuration.") from exc
    return request_model, _run_request_context(request_model)


def _explicit_overrides(arguments: dict[str, Any]) -> dict[str, Any]:
    unknown = set(arguments) - set(SCENARIO_OVERRIDE_FIELDS)
    if unknown:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported scenario field: {sorted(unknown)[0]}",
        )
    return {
        field: arguments.get(field)
        for field in SCENARIO_OVERRIDE_FIELDS
        if field in arguments and arguments.get(field) is not None
    }


def _parameter_sweep_values(
    arguments: dict[str, Any],
) -> tuple[
    Literal["validation", "annual"] | None,
    str,
    dict[str, Any],
    list[float],
]:
    unknown = set(arguments) - set(PARAMETER_SWEEP_FIELDS)
    if unknown:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported parameter sweep field: {sorted(unknown)[0]}",
        )
    target_mode = arguments.get("mode")
    if target_mode not in {None, "validation", "annual"}:
        raise HTTPException(status_code=422, detail="Unsupported analysis mode.")

    parameter = arguments.get("parameter")
    parameter_config = SWEEPABLE_PARAMETER_CONFIG.get(str(parameter))
    if parameter_config is None:
        raise HTTPException(
            status_code=422,
            detail=(
                "This field cannot be swept as a controlled same-input model "
                "parameter."
            ),
        )

    decimals: dict[str, Decimal] = {}
    labels = {
        "start": "Parameter sweep start",
        "stop": "Parameter sweep stop",
        "increment": "Parameter sweep increment",
    }
    for field, label in labels.items():
        value = arguments.get(field)
        if isinstance(value, bool):
            raise HTTPException(status_code=422, detail=f"{label} must be a number.")
        try:
            parsed = Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=422, detail=f"{label} must be a number."
            ) from exc
        if not parsed.is_finite():
            raise HTTPException(
                status_code=422, detail=f"{label} must be a finite number."
            )
        if field == "increment" and parsed <= 0:
            raise HTTPException(
                status_code=422, detail=f"{label} must be greater than zero."
            )
        decimals[field] = parsed

    start = decimals["start"]
    stop = decimals["stop"]
    increment = decimals["increment"]
    if stop < start:
        raise HTTPException(
            status_code=422,
            detail="Parameter sweep stop must be greater than or equal to its start.",
        )
    minimum = parameter_config.get("minimum")
    exclusive_minimum = parameter_config.get("exclusive_minimum")
    maximum = parameter_config.get("maximum")
    if minimum is not None and start < minimum:
        raise HTTPException(
            status_code=422,
            detail=f"{parameter_config['label']} must be at least {minimum}.",
        )
    if exclusive_minimum is not None and start <= exclusive_minimum:
        raise HTTPException(
            status_code=422,
            detail=(
                f"{parameter_config['label']} must be greater than "
                f"{exclusive_minimum}."
            ),
        )
    if maximum is not None and stop > maximum:
        raise HTTPException(
            status_code=422,
            detail=f"{parameter_config['label']} must not exceed {maximum}.",
        )
    step_count = (stop - start) / increment
    whole_steps = step_count.to_integral_value()
    if step_count != whole_steps:
        raise HTTPException(
            status_code=422,
            detail=(
                "Parameter sweep increment must land exactly on the inclusive stop "
                "value."
            ),
        )
    if whole_steps >= MAX_PARAMETER_SWEEP_VALUES:
        raise HTTPException(
            status_code=422,
            detail=(
                f"A parameter sweep can contain at most "
                f"{MAX_PARAMETER_SWEEP_VALUES} values."
            ),
        )
    count = int(whole_steps) + 1
    if count < 2:
        raise HTTPException(
            status_code=422,
            detail="A parameter sweep must contain at least two values.",
        )
    values = [float(start + increment * index) for index in range(count)]
    if not all(math.isfinite(value) for value in values):
        raise HTTPException(
            status_code=422,
            detail="Parameter sweep values must be finite numbers.",
        )
    return target_mode, str(parameter), parameter_config, values


def _scenario_changes(
    baseline: dict[str, Any], candidate: dict[str, Any]
) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    for field in SCENARIO_OVERRIDE_FIELDS:
        if field == "mode":
            continue
        before = baseline.get(field)
        after = candidate.get(field)
        if before == after:
            continue
        item = {
            "field": field,
            "label": SCENARIO_FIELD_LABELS[field],
            "from": before,
            "to": after,
        }
        if field == "curtailment_limit_kw":
            item["unit"] = "kW"
        changes.append(item)
    return changes


def _apply_dependent_scenario_overrides(
    overrides: dict[str, Any], baseline: dict[str, Any]
) -> dict[str, Any]:
    normalized = dict(overrides)
    date_fields = {"from_date", "to_date"}
    if "years" in normalized and date_fields.intersection(normalized):
        raise HTTPException(
            status_code=422,
            detail=(
                "MIDC year selection cannot be combined with custom annual dates. "
                "Use years or a legacy date range."
            ),
        )
    if "years" in normalized:
        # Selected years are authoritative.  Clear a legacy baseline's resolved
        # bounds so annual validation can resolve the new immutable periods.
        normalized["from_date"] = None
        normalized["to_date"] = None
    elif date_fields.intersection(normalized) and "years" in baseline:
        # Retain legacy date overrides even when the visible baseline was made
        # with the newer years selector.
        normalized["years"] = None
    if normalized.get("iam_model") == "physical" and normalized.get("iam_a_r") is not None:
        raise HTTPException(
            status_code=422,
            detail="Martin-Ruiz a_r cannot be combined with Physical IAM.",
        )
    if "iam_a_r" in normalized and "iam_model" not in normalized:
        normalized["iam_model"] = "martin_ruiz"
    selected_iam = normalized.get("iam_model", baseline.get("iam_model"))
    if selected_iam == "martin_ruiz" and normalized.get(
        "iam_a_r", baseline.get("iam_a_r")
    ) is None:
        normalized["iam_a_r"] = model.A_R
    if "curtailment_limit_kw" in normalized and "curtailment_enabled" not in normalized:
        normalized["curtailment_enabled"] = True
    return normalized


def _same_input_context(
    mode: str, baseline: dict[str, Any], candidate: dict[str, Any]
) -> bool:
    if mode == "annual":
        keys = (
            "from_date",
            "to_date",
            "years",
            "interval_value",
            "interval_unit",
        )
    else:
        keys = (
            "from_date",
            "from_time",
            "to_date",
            "to_time",
            "interval_value",
            "interval_unit",
        )
    return all(baseline.get(key) == candidate.get(key) for key in keys)
