"""Strict request schemas for the live Autonomy foundation API."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    field_validator,
    model_validator,
)

from sbepv.autonomy.readiness import SUPPORTED_ANALYSIS_BASES


ShortText = Annotated[str, Field(min_length=1, max_length=300)]
QuestionText = Annotated[str, Field(min_length=1, max_length=4_000)]
OperatorText = Annotated[str, Field(min_length=1, max_length=300)]
RationaleText = Annotated[str, Field(min_length=1, max_length=2_000)]
IdentifierText = Annotated[str, Field(min_length=1, max_length=128)]
ScenarioLabelText = Annotated[str, Field(min_length=1, max_length=120)]
JsonPointerText = Annotated[
    str,
    Field(
        min_length=1,
        max_length=500,
        pattern=r"^/(?:[^~/]|~0|~1)+(?:/(?:[^~/]|~0|~1)+)*$",
    ),
]


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


class ScenarioEvidenceReferenceRequest(StrictAutonomyRequest):
    """Bind one immutable accepted-evidence receipt to a request field."""

    request_path: JsonPointerText
    receipt_id: Annotated[
        str,
        Field(min_length=5, max_length=128, pattern=r"^evr_[A-Za-z0-9]+$"),
    ]


class DecisionScenarioCreateRequest(StrictAutonomyRequest):
    expected_case_revision: Annotated[StrictInt, Field(ge=1)]
    operator_name: OperatorText
    label: ScenarioLabelText
    kind: Literal["baseline", "alternative"]
    request: dict[str, Any]
    changed_fields: list[JsonPointerText] = Field(default_factory=list, max_length=500)
    evidence_references: list[ScenarioEvidenceReferenceRequest] = Field(
        default_factory=list,
        max_length=500,
    )

    @model_validator(mode="after")
    def validate_unique_declarations(self) -> "DecisionScenarioCreateRequest":
        if len(set(self.changed_fields)) != len(self.changed_fields):
            raise ValueError("changed_fields must be unique")
        request_paths = [item.request_path for item in self.evidence_references]
        if len(set(request_paths)) != len(request_paths):
            raise ValueError(
                "evidence_references must use unique request_path values"
            )
        return self


class DecisionScenarioRevisionRequest(DecisionScenarioCreateRequest):
    expected_scenario_revision: Annotated[StrictInt, Field(ge=1)]


class DecisionScenarioValidateRequest(StrictAutonomyRequest):
    expected_case_revision: Annotated[StrictInt, Field(ge=1)]
    expected_scenario_revision: Annotated[StrictInt, Field(ge=1)]
    expected_request_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    operator_name: OperatorText


class DecisionScenarioExpireRequest(StrictAutonomyRequest):
    expected_case_revision: Annotated[StrictInt, Field(ge=1)]
    expected_scenario_revision: Annotated[StrictInt, Field(ge=1)]
    operator_name: OperatorText
    reason: RationaleText


class DecisionScenarioConfirmationSelection(StrictAutonomyRequest):
    scenario_id: Annotated[
        str,
        Field(min_length=5, max_length=128, pattern=r"^dsc_[A-Za-z0-9]+$"),
    ]
    revision: Annotated[StrictInt, Field(ge=1)]
    request_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class DecisionScenarioConfirmRequest(StrictAutonomyRequest):
    expected_case_revision: Annotated[StrictInt, Field(ge=1)]
    selections: list[DecisionScenarioConfirmationSelection] = Field(
        min_length=1,
        max_length=4,
    )
    operator_name: OperatorText
    rationale: RationaleText
    acknowledgement_accepted: Literal[True]
    idempotency_key: Annotated[
        str,
        Field(min_length=8, max_length=200, pattern=r"^[A-Za-z0-9_.:-]+$"),
    ]

    @model_validator(mode="after")
    def validate_unique_scenarios(self) -> "DecisionScenarioConfirmRequest":
        scenario_ids = [item.scenario_id for item in self.selections]
        if len(set(scenario_ids)) != len(scenario_ids):
            raise ValueError("confirmation selections must use unique scenario IDs")
        return self


class DecisionScenarioJobActionRequest(StrictAutonomyRequest):
    expected_case_revision: Annotated[StrictInt, Field(ge=1)]
    operator_name: OperatorText
    rationale: RationaleText


class DecisionComparisonBundleCreateRequest(StrictAutonomyRequest):
    """Request an exact, confirmation-scoped comparison snapshot.

    Result values, selected attempts, and recommendation fields are deliberately
    absent.  The server resolves them only through immutable confirmation and retry
    links, then re-verifies every admitted completed result.
    """

    expected_case_revision: Annotated[StrictInt, Field(ge=1)]
    confirmation_id: Annotated[
        str,
        Field(min_length=6, max_length=128, pattern=r"^dconf_[A-Za-z0-9]+$"),
    ]
    operator_name: OperatorText


class DecisionBriefCreateRequest(StrictAutonomyRequest):
    """Create or replay an immutable brief from one exact bundle identity."""

    expected_case_revision: Annotated[StrictInt, Field(ge=1)]
    comparison_bundle_id: Annotated[
        str,
        Field(min_length=6, max_length=128, pattern=r"^dcmp_[A-Za-z0-9]+$"),
    ]
    bundle_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    operator_name: OperatorText
    idempotency_key: Annotated[
        str,
        Field(min_length=8, max_length=200, pattern=r"^[A-Za-z0-9_.:-]+$"),
    ]


class DecisionSignoffCreateRequest(StrictAutonomyRequest):
    expected_case_revision: Annotated[StrictInt, Field(ge=1)]
    disposition: Literal["accept", "reject", "defer"]
    decision_owner_name: Annotated[str, Field(min_length=1, max_length=200)]
    rationale: Annotated[str, Field(min_length=1, max_length=4_000)]
    acknowledgement_text: Annotated[str, Field(min_length=1, max_length=4_000)]
    acknowledgement_version: Annotated[str, Field(min_length=1, max_length=100)]
    provisional_warning_acknowledgements: list[
        Annotated[str, Field(min_length=1, max_length=200)]
    ] = Field(default_factory=list, max_length=100)
    idempotency_key: Annotated[
        str,
        Field(min_length=8, max_length=200, pattern=r"^[A-Za-z0-9_.:-]+$"),
    ]

    @field_validator("provisional_warning_acknowledgements")
    @classmethod
    def validate_unique_warning_acknowledgements(
        cls, value: list[str]
    ) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("provisional warning acknowledgements must be unique")
        return value


class DecisionReportCreateRequest(StrictAutonomyRequest):
    expected_case_revision: Annotated[StrictInt, Field(ge=1)]
    report_kind: Literal["draft", "final"]
    brief_revision_id: Annotated[
        str,
        Field(min_length=5, max_length=128, pattern=r"^dbr_[A-Za-z0-9]+$"),
    ]
    signoff_id: Annotated[
        str,
        Field(min_length=6, max_length=128, pattern=r"^dsgn_[A-Za-z0-9]+$"),
    ] | None = None
    idempotency_key: Annotated[
        str,
        Field(min_length=8, max_length=200, pattern=r"^[A-Za-z0-9_.:-]+$"),
    ]

    @model_validator(mode="after")
    def validate_report_authority(self) -> "DecisionReportCreateRequest":
        if (self.report_kind == "final") != (self.signoff_id is not None):
            raise ValueError("final reports require signoff_id; drafts must omit it")
        return self


class DecisionShadowReviewChecklist(StrictAutonomyRequest):
    unauthorized_execution_observed: StrictBool
    numeric_citations_verified: StrictBool
    result_tie_out_verified: StrictBool
    report_tie_out_verified: StrictBool
    observations: Annotated[str, Field(max_length=4_000)] | None = None


class DecisionShadowReviewCreateRequest(StrictAutonomyRequest):
    case_id: Annotated[
        str,
        Field(min_length=6, max_length=128, pattern=r"^case_[A-Za-z0-9]+$"),
    ]
    brief_revision_id: Annotated[
        str,
        Field(min_length=5, max_length=128, pattern=r"^dbr_[A-Za-z0-9]+$"),
    ]
    report_id: Annotated[
        str,
        Field(min_length=6, max_length=128, pattern=r"^drpt_[A-Za-z0-9]+$"),
    ]
    report_snapshot_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    pdf_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    report_identity_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    review_case_key: Annotated[
        str, Field(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9_.:-]+$")
    ]
    checklist_version: Annotated[str, Field(min_length=1, max_length=100)]
    reviewer_name: Annotated[str, Field(min_length=1, max_length=200)]
    outcome: Literal["passed", "failed", "needs_followup"]
    review: DecisionShadowReviewChecklist
