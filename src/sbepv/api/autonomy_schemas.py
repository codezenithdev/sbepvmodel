"""Strict request schemas for the live Autonomy foundation API."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator

from sbepv.autonomy.readiness import SUPPORTED_ANALYSIS_BASES


ShortText = Annotated[str, Field(min_length=1, max_length=300)]
QuestionText = Annotated[str, Field(min_length=1, max_length=4_000)]
OperatorText = Annotated[str, Field(min_length=1, max_length=300)]
RationaleText = Annotated[str, Field(min_length=1, max_length=2_000)]
IdentifierText = Annotated[str, Field(min_length=1, max_length=128)]


class StrictAutonomyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)


class DecisionCaseCreateRequest(StrictAutonomyRequest):
    title: ShortText
    question: QuestionText
    operator_name: OperatorText


class DecisionCaseUpdateRequest(StrictAutonomyRequest):
    expected_revision: Annotated[StrictInt, Field(ge=0)]
    operator_name: OperatorText
    title: ShortText | None = None
    question: QuestionText | None = None
    decision_owner: ShortText | None = None
    source_annual_job_id: IdentifierText | None = None
    source_snapshot_sha256: Annotated[
        str, Field(pattern=r"^[0-9a-f]{64}$")
    ] | None = None
    analysis_basis: Literal["solartac_site", "commercial_representative"] | None = None

    @model_validator(mode="after")
    def validate_source_lock_tuple(self) -> "DecisionCaseUpdateRequest":
        values = (
            self.source_annual_job_id,
            self.source_snapshot_sha256,
            self.analysis_basis,
        )
        supplied = sum(value is not None for value in values)
        if supplied not in {0, 3}:
            raise ValueError(
                "source_annual_job_id, source_snapshot_sha256, and analysis_basis must be supplied together"
            )
        if self.analysis_basis is not None and self.analysis_basis not in {
            item["id"] for item in SUPPORTED_ANALYSIS_BASES
        }:
            raise ValueError("unsupported analysis basis")
        return self


class DecisionCaseArchiveRequest(StrictAutonomyRequest):
    expected_revision: Annotated[StrictInt, Field(ge=0)]
    operator_name: OperatorText
    reason: RationaleText


class DecisionMessageCreateRequest(StrictAutonomyRequest):
    message: Annotated[str, Field(min_length=1, max_length=8_000)]
    client_message_id: Annotated[
        str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")
    ]
    operator_name: OperatorText
    expected_revision: Annotated[StrictInt, Field(ge=0)] | None = None


class EvidenceReviewRequest(StrictAutonomyRequest):
    decision: Literal["accepted", "rejected"]
    operator_name: OperatorText
    rationale: Annotated[str, Field(min_length=1, max_length=2_000)] | None = None
    expected_revision: Annotated[StrictInt, Field(ge=0)] | None = None

    @field_validator("rationale")
    @classmethod
    def normalize_rationale(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class EvidenceDeleteRequest(StrictAutonomyRequest):
    operator_name: OperatorText
    reason: RationaleText
    expected_revision: Annotated[StrictInt, Field(ge=0)] | None = None
