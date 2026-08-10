"""Tool definitions the Solar Agent may call, and the fields they may set.

Pure data plus one schema helper. Nothing here touches application state, so the
contract the model sees can be read in one place.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any


SCENARIO_OVERRIDE_FIELDS = (
    "mode",
    "from_date",
    "from_time",
    "to_date",
    "to_time",
    "interval_value",
    "interval_unit",
    "backtrack",
    "solaredge_inverter_efficiency",
    "solaredge_bos_efficiency",
    "solectria_inverter_efficiency",
    "solectria_bos_efficiency",
    "iam_model",
    "iam_a_r",
    "curtailment_enabled",
    "curtailment_limit_kw",
)

SCENARIO_FIELD_LABELS = {
    "mode": "Analysis mode",
    "from_date": "Start date",
    "from_time": "Start time",
    "to_date": "End date",
    "to_time": "End time",
    "interval_value": "Interval value",
    "interval_unit": "Interval unit",
    "backtrack": "Backtracking",
    "solaredge_inverter_efficiency": "SolarEdge inverter efficiency",
    "solaredge_bos_efficiency": "SolarEdge BOS efficiency",
    "solectria_inverter_efficiency": "Solectria inverter efficiency",
    "solectria_bos_efficiency": "Solectria BOS efficiency",
    "iam_model": "IAM model",
    "iam_a_r": "Martin-Ruiz a_r",
    "curtailment_enabled": "Clipping / curtailment",
    "curtailment_limit_kw": "Clipping / curtailment limit",
}


def _nullable_schema(base_type: str, **extra: Any) -> dict[str, Any]:
    schema: dict[str, Any] = {"type": [base_type, "null"]}
    schema.update(extra)
    return schema


SCENARIO_TOOL = {
    "type": "function",
    "name": "propose_model_scenario",
    "description": (
        "Propose one solar model scenario containing only settings the user explicitly "
        "asked to change. Use null for all unchanged settings. The application validates, "
        "approves, executes, and compares the run. A calibration scenario can execute only "
        "from the exact reviewed baseline source. A new calibration window is handed back "
        "to the visible data-quality review flow and is never fetched automatically. Do not "
        "use this tool for multiple values or ranges; use run_model_parameter_sweep."
    ),
    "strict": True,
    "parameters": {
        "type": "object",
        "properties": {
            "mode": _nullable_schema(
                "string", enum=["validation", "annual", None]
            ),
            "from_date": _nullable_schema("string"),
            "from_time": _nullable_schema("string"),
            "to_date": _nullable_schema("string"),
            "to_time": _nullable_schema("string"),
            "interval_value": _nullable_schema("integer", minimum=1),
            "interval_unit": _nullable_schema(
                "string", enum=["minutes", "hours", "days", None]
            ),
            "backtrack": _nullable_schema("boolean"),
            "solaredge_inverter_efficiency": _nullable_schema(
                "number", minimum=0, maximum=1
            ),
            "solaredge_bos_efficiency": _nullable_schema(
                "number", minimum=0, maximum=1
            ),
            "solectria_inverter_efficiency": _nullable_schema(
                "number", minimum=0, maximum=1
            ),
            "solectria_bos_efficiency": _nullable_schema(
                "number", minimum=0, maximum=1
            ),
            "iam_model": _nullable_schema(
                "string", enum=["physical", "martin_ruiz", None]
            ),
            "iam_a_r": _nullable_schema("number", exclusiveMinimum=0),
            "curtailment_enabled": _nullable_schema("boolean"),
            "curtailment_limit_kw": _nullable_schema(
                "number", exclusiveMinimum=0
            ),
        },
        "required": list(SCENARIO_OVERRIDE_FIELDS),
        "additionalProperties": False,
    },
}

SWEEPABLE_PARAMETER_CONFIG: dict[str, dict[str, Any]] = {
    "solaredge_inverter_efficiency": {
        "label": "SolarEdge inverter efficiency",
        "minimum": Decimal("0"),
        "maximum": Decimal("1"),
    },
    "solaredge_bos_efficiency": {
        "label": "SolarEdge BOS efficiency",
        "minimum": Decimal("0"),
        "maximum": Decimal("1"),
    },
    "solectria_inverter_efficiency": {
        "label": "Solectria inverter efficiency",
        "minimum": Decimal("0"),
        "maximum": Decimal("1"),
    },
    "solectria_bos_efficiency": {
        "label": "Solectria BOS efficiency",
        "minimum": Decimal("0"),
        "maximum": Decimal("1"),
    },
    "iam_a_r": {
        "label": "Martin-Ruiz a_r",
        "exclusive_minimum": Decimal("0"),
    },
    "curtailment_limit_kw": {
        "label": "Curtailment limit",
        "unit": "kW",
        "exclusive_minimum": Decimal("0"),
    },
}
PARAMETER_SWEEP_FIELDS = ("mode", "parameter", "start", "stop", "increment")
MAX_PARAMETER_SWEEP_VALUES = 12
PARAMETER_SWEEP_TOOL = {
    "type": "function",
    "name": "run_model_parameter_sweep",
    "description": (
        "Run a controlled numeric model-parameter sweep against the selected baseline. "
        "Supported parameters are IAM a_r, SolarEdge/Solectria inverter efficiency, "
        "SolarEdge/Solectria BOS efficiency, and curtailment limit kW. Efficiency "
        "values are decimal ratios from 0 to 1. The inclusive start, stop, and "
        f"increment must produce between 2 and {MAX_PARAMETER_SWEEP_VALUES} values. "
        "Every unrelated model input and the verified source data stay fixed; "
        "required dependent selectors are applied consistently to every sweep row."
    ),
    "strict": True,
    "parameters": {
        "type": "object",
        "properties": {
            "mode": _nullable_schema(
                "string", enum=["validation", "annual", None]
            ),
            "parameter": {
                "type": "string",
                "enum": list(SWEEPABLE_PARAMETER_CONFIG),
            },
            "start": {
                "type": "number",
            },
            "stop": {
                "type": "number",
            },
            "increment": {
                "type": "number",
                "exclusiveMinimum": 0,
            },
        },
        "required": list(PARAMETER_SWEEP_FIELDS),
        "additionalProperties": False,
    },
}
