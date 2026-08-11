"""Pydantic request bodies for the dashboard API.

Every model forbids unknown fields (``StrictRequest``) so a typo in a client
payload is a 422 rather than a silently ignored setting.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool

from sbepv import model
from sbepv.agent.tool_schemas import MAX_PARAMETER_SWEEP_VALUES


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RunRequest(StrictRequest):
    from_date: str  # YYYY-MM-DD
    from_time: str = "00:00"  # HH:MM
    to_date: str
    to_time: str = "00:00"
    interval_value: int = 1
    interval_unit: Literal["minutes", "hours", "days"] = "hours"
    backtrack: bool = model.BACKTRACK
    solaredge_inverter_efficiency: float = 1.0
    solaredge_bos_efficiency: float = 1.0
    solectria_inverter_efficiency: float = model.SOL_EFF
    solectria_bos_efficiency: float = 1.0
    iam_model: Literal["physical", "martin_ruiz"] = "physical"
    include_iam: bool | None = Field(
        default=model.INCLUDE_IAM,
        exclude=True,
        deprecated="Use iam_model and iam_a_r instead.",
    )
    iam_a_r: float | None = model.A_R
    curtailment_enabled: bool = False
    curtailment_limit_kw: float | None = None
    calibrate_model: bool = True


class CalibrationDecisionRequest(StrictRequest):
    decisions: dict[str, Literal["retain", "exclude"]] = Field(
        default_factory=dict
    )


class AnnualRunRequest(StrictRequest):
    from_date: str  # YYYY-MM-DD, inclusive fixed MST date
    to_date: str
    interval_value: int = 1
    interval_unit: Literal["minutes", "hours", "days"] = "hours"
    backtrack: bool = model.BACKTRACK
    solaredge_inverter_efficiency: float = 1.0
    solaredge_bos_efficiency: float = 1.0
    solectria_inverter_efficiency: float = model.SOL_EFF
    solectria_bos_efficiency: float = 1.0
    iam_model: Literal["physical", "martin_ruiz"] = "physical"
    include_iam: bool | None = Field(
        default=model.INCLUDE_IAM,
        exclude=True,
        deprecated="Use iam_model and iam_a_r instead.",
    )
    iam_a_r: float | None = model.A_R
    curtailment_enabled: bool = False
    curtailment_limit_kw: float | None = None


class SeasonalFallbackAcknowledgement(StrictRequest):
    """Explicit consent for the one supported annual cross-season fallback."""

    accepted: StrictBool
    source_season: Literal["spring"]
    target_season: Literal["fall"]
    confirmation_context_sha256: str


class AnnualRunSubmission(AnnualRunRequest):
    """Annual request plus API-only calibration selection and consent fields."""

    calibration_baseline_job_id: str | None = None
    seasonal_fallback_acknowledgement: SeasonalFallbackAcknowledgement | None = None


class ChatMessage(StrictRequest):
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(StrictRequest):
    message: str
    job_id: str | None = None
    history: list[ChatMessage] = Field(default_factory=list)
    active_mode: Literal["validation", "annual"] = "validation"
    current_config: dict[str, Any] | None = None
    allow_scenario_actions: bool = True


class ProposalEditRequest(StrictRequest):
    overrides: dict[str, Any]
class ProposalSweepConfirmRequest(StrictRequest):
    proposal_ids: list[str] = Field(
        min_length=1, max_length=MAX_PARAMETER_SWEEP_VALUES
    )
