"""Pydantic request bodies for the dashboard API.

Every model forbids unknown fields (``StrictRequest``) so a typo in a client
payload is a 422 rather than a silently ignored setting.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import math
import re
from typing import Annotated, Any, Literal

from pydantic import (
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StringConstraints,
    field_validator,
    model_validator,
)

from sbepv import model
from sbepv.agent.tool_schemas import MAX_PARAMETER_SWEEP_VALUES


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DataCollectionRequest(StrictRequest):
    """Standalone Bazefield source-data collection request."""

    from_date: str
    from_time: str = "00:00"
    to_date: str
    to_time: str = "00:00"
    interval_value: int = Field(default=1, ge=1)
    interval_unit: Literal["minutes", "hours", "days"] = "hours"
    data_groups: list[Literal["solaredge", "solectria", "weather"]] = Field(
        default_factory=lambda: ["solaredge", "solectria", "weather"],
        min_length=1,
        max_length=3,
    )

    @field_validator("data_groups")
    @classmethod
    def data_groups_are_unique(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("Data groups must not contain duplicates.")
        order = {
            name: index
            for index, name in enumerate(("solaredge", "solectria", "weather"))
        }
        return sorted(value, key=order.__getitem__)


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
    # Legacy callers may still submit one inclusive fixed-MST date range.  The
    # dashboard's multi-year workflow submits ``years`` instead; validation
    # resolves that selection to immutable from/to bounds before the job is
    # stored so a queued current-year run cannot grow after midnight.
    from_date: str | None = None  # YYYY-MM-DD, inclusive fixed MST date
    to_date: str | None = None
    years: list[int] | None = None
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


class SavedResultCreateRequest(StrictRequest):
    name: str | None = Field(default=None, min_length=1, max_length=120)


class SavedResultRenameRequest(StrictRequest):
    name: str = Field(min_length=1, max_length=120)


class ProposalSweepConfirmRequest(StrictRequest):
    proposal_ids: list[str] = Field(
        min_length=1, max_length=MAX_PARAMETER_SWEEP_VALUES
    )


# Technoeconomic requests deliberately use a stricter model family than the
# historical dashboard bodies above.  Changing ``StrictRequest`` itself to
# ``strict=True`` would be a compatibility change for the existing API.
def _reject_xml_10_illegal_text(value: Any) -> None:
    if isinstance(value, str):
        for character in value:
            codepoint = ord(character)
            if (
                (codepoint < 0x20 and codepoint not in {0x09, 0x0A, 0x0D})
                or 0xD800 <= codepoint <= 0xDFFF
                or codepoint in {0xFFFE, 0xFFFF}
            ):
                raise ValueError(
                    "technoeconomic text contains a character that is not valid "
                    "in XML 1.0"
                )
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            _reject_xml_10_illegal_text(key)
            _reject_xml_10_illegal_text(item)
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            _reject_xml_10_illegal_text(item)


ANNUAL_APPLIED_CAPACITY_NORMALIZATION = "annual_applied_capacity_v1"


class StrictTechnoeconomicRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    @model_validator(mode="before")
    @classmethod
    def reject_xml_10_illegal_text(cls, value: Any) -> Any:
        """Reject text that cannot be represented in the required XLSX export."""

        _reject_xml_10_illegal_text(value)
        return value


StableTechnoeconomicId = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=160,
        pattern=r"^[a-z0-9._:-]+$",
    ),
]
NonemptyTechnoeconomicText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=4000),
]
Sha256Text = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
FiniteNonnegativeFloat = Annotated[float, Field(ge=0, allow_inf_nan=False)]
FinitePositiveFloat = Annotated[float, Field(gt=0, allow_inf_nan=False)]

# The realization table has 43 fixed identity/result columns today.  Budget 48
# so a version-1 request remains safe if a few audit columns are added without
# weakening the pre-enqueue resource gate.  Every declared distribution is also
# exported as a realization column, including fixed inputs.
TECHNOECONOMIC_REALIZATION_COLUMN_OVERHEAD = 48
# V3 emits eight additional fixed commercial-scaling result/audit columns.  Keep
# this incremental so v1/v2 admission behavior remains byte-for-byte compatible.
TECHNOECONOMIC_COMMERCIAL_SCALING_REALIZATION_COLUMN_OVERHEAD = 8
# V4 adds eleven fixed standalone-commercial result columns while its sampled
# commercial cost inputs are counted individually below.  Keep this separate so
# admission behavior for every v1-v3 payload is unchanged.
TECHNOECONOMIC_STANDALONE_COMMERCIAL_REALIZATION_COLUMN_OVERHEAD = 11
# V5 retains all eleven SolarEdge columns, adds their eleven Solectria mirrors,
# and adds the paired per-realization LCOE delta.
TECHNOECONOMIC_PAIRED_COMMERCIAL_REALIZATION_COLUMN_OVERHEAD = 23
# V6 retains only realization-level totals in the public table.  Annual and
# component traces are exported for the three Upgrade-NPV representatives, so
# they do not scale the realization-cell budget by project life.
TECHNOECONOMIC_LIFECYCLE_REALIZATION_COLUMN_OVERHEAD = 64
TECHNOECONOMIC_MAX_REALIZATION_EXPORT_CELLS = 8_000_000
# Forward stepwise rank regression repeatedly fits expanding predictor sets.  The
# deterministic n*p^2 gate is a conservative lower-bound proxy for that work.
TECHNOECONOMIC_MAX_SENSITIVITY_WORK_UNITS = 25_000_000


class FixedDistributionRequest(StrictTechnoeconomicRequest):
    family: Literal["fixed"]
    value: Annotated[float, Field(allow_inf_nan=False)]


class UniformDistributionRequest(StrictTechnoeconomicRequest):
    family: Literal["uniform"]
    low: Annotated[float, Field(allow_inf_nan=False)]
    high: Annotated[float, Field(allow_inf_nan=False)]

    @model_validator(mode="after")
    def validate_bounds(self) -> "UniformDistributionRequest":
        if self.low > self.high:
            raise ValueError("uniform distributions require low <= high")
        return self


class TriangularDistributionRequest(StrictTechnoeconomicRequest):
    family: Literal["triangular"]
    low: Annotated[float, Field(allow_inf_nan=False)]
    mode: Annotated[float, Field(allow_inf_nan=False)]
    high: Annotated[float, Field(allow_inf_nan=False)]

    @model_validator(mode="after")
    def validate_bounds(self) -> "TriangularDistributionRequest":
        if not self.low <= self.mode <= self.high:
            raise ValueError("triangular distributions require low <= mode <= high")
        return self


class BoundedNormalDistributionRequest(StrictTechnoeconomicRequest):
    family: Literal["bounded_normal"]
    low: Annotated[float, Field(allow_inf_nan=False)]
    high: Annotated[float, Field(allow_inf_nan=False)]
    mean: Annotated[float, Field(allow_inf_nan=False)]
    sd: FinitePositiveFloat

    @model_validator(mode="after")
    def validate_bounds(self) -> "BoundedNormalDistributionRequest":
        if self.low >= self.high:
            raise ValueError("bounded-normal distributions require low < high")
        return self


TechnoeconomicDistributionRequest = Annotated[
    FixedDistributionRequest
    | UniformDistributionRequest
    | TriangularDistributionRequest
    | BoundedNormalDistributionRequest,
    Field(discriminator="family"),
]


class EvidenceCitationRequest(StrictTechnoeconomicRequest):
    title: NonemptyTechnoeconomicText
    organization: NonemptyTechnoeconomicText
    url: AnyHttpUrl | None = None
    stable_reference: NonemptyTechnoeconomicText | None = None
    publication_or_as_of_date: str
    accessed_date: str
    excerpt_or_derivation_note: NonemptyTechnoeconomicText
    # Phase 3 has no server-owned evidence-blob resolver.  A client therefore
    # cannot claim that arbitrary hashes identify bytes preserved by this service.
    preservation_mode: Literal["metadata_excerpt_only"]
    user_supplied_content_sha256: Sha256Text | None = None
    metadata_only_rationale: NonemptyTechnoeconomicText

    @field_validator("publication_or_as_of_date", "accessed_date")
    @classmethod
    def validate_iso_date(cls, value: str) -> str:
        if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise ValueError("evidence dates must use YYYY-MM-DD")
        try:
            date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("evidence dates must be valid calendar dates") from exc
        return value

    @model_validator(mode="after")
    def validate_source_locator(self) -> "EvidenceCitationRequest":
        if self.url is None and self.stable_reference is None:
            raise ValueError("a citation requires a URL or stable reference")
        return self


class TechnoeconomicEvidenceRequest(StrictTechnoeconomicRequest):
    evidence_class: Literal[
        "project_actual",
        "direct_quote_or_primary_document",
        "public_market_proxy_or_benchmark",
        "engineering_judgment",
        "secondary_synthesis",
    ]
    citation: EvidenceCitationRequest
    explicit_acceptance: StrictBool | None = None
    acceptance_rationale: NonemptyTechnoeconomicText | None = None

    @model_validator(mode="after")
    def validate_provisional_acceptance(self) -> "TechnoeconomicEvidenceRequest":
        provisional = self.evidence_class in {
            "engineering_judgment",
            "secondary_synthesis",
        }
        if provisional and (
            self.explicit_acceptance is not True
            or self.acceptance_rationale is None
        ):
            raise ValueError(
                "engineering_judgment and secondary_synthesis require explicit "
                "acceptance and a nonempty rationale"
            )
        if self.explicit_acceptance is False:
            raise ValueError("an explicitly rejected evidence value is not runnable")
        if self.explicit_acceptance is None and self.acceptance_rationale is not None:
            raise ValueError("an acceptance rationale requires explicit_acceptance=true")
        return self


class DocumentedDistributionRequest(StrictTechnoeconomicRequest):
    unit: Literal[
        "real_fraction_per_year",
        "dimensionless_multiplier",
    ]
    distribution: TechnoeconomicDistributionRequest
    evidence: TechnoeconomicEvidenceRequest


class SameYearCurrencyNormalizationRequest(StrictTechnoeconomicRequest):
    method: Literal["same_year_no_adjustment"]
    source_cost_year: Annotated[int, Field(ge=1900, le=3000)]
    target_constant_dollar_cost_year: Annotated[int, Field(ge=1900, le=3000)]
    submitted_distribution_basis: Literal["target_constant_dollar_year"]
    index_identity: Literal["not_applicable_same_year"]
    index_factor: FinitePositiveFloat
    derivation: NonemptyTechnoeconomicText

    @model_validator(mode="after")
    def validate_same_year(self) -> "SameYearCurrencyNormalizationRequest":
        if self.source_cost_year != self.target_constant_dollar_cost_year:
            raise ValueError("same-year normalization requires identical source and target years")
        if self.index_factor != 1.0:
            raise ValueError("same-year normalization requires index_factor=1")
        return self


class PriceIndexCurrencyNormalizationRequest(StrictTechnoeconomicRequest):
    method: Literal["price_index_adjustment"]
    source_cost_year: Annotated[int, Field(ge=1900, le=3000)]
    target_constant_dollar_cost_year: Annotated[int, Field(ge=1900, le=3000)]
    submitted_distribution_basis: Literal["target_constant_dollar_year"]
    index_identity: NonemptyTechnoeconomicText
    index_factor: FinitePositiveFloat
    derivation: NonemptyTechnoeconomicText
    index_source_evidence: TechnoeconomicEvidenceRequest

    @model_validator(mode="after")
    def validate_indexed_years(self) -> "PriceIndexCurrencyNormalizationRequest":
        if self.source_cost_year == self.target_constant_dollar_cost_year:
            raise ValueError(
                "price-index normalization requires different source and target years"
            )
        return self


CurrencyYearNormalizationRequest = Annotated[
    SameYearCurrencyNormalizationRequest | PriceIndexCurrencyNormalizationRequest,
    Field(discriminator="method"),
]


class TechnoeconomicCostLineRequest(StrictTechnoeconomicRequest):
    input_id: StableTechnoeconomicId
    label: NonemptyTechnoeconomicText
    ownership: Literal["solectria_only", "solaredge_only", "paired_shared"]
    cost_type: Literal[
        "initial_capex",
        "initial_installation_labor",
        "recurring_labor",
        "recurring_om",
        "recurring_maintenance",
    ]
    distribution: TechnoeconomicDistributionRequest
    coverage_include_ids: list[StableTechnoeconomicId] = Field(min_length=1, max_length=256)
    coverage_exclude_ids: list[StableTechnoeconomicId] = Field(default_factory=list, max_length=256)
    original_unit: Literal[
        "usd_total",
        "usd_total_per_year",
        "usd_per_unit",
        "usd_per_unit_year",
        "usd_per_wdc",
        "usd_per_wdc_year",
    ]
    normalized_unit: Literal[
        "usd_per_wdc",
        "usd_per_wdc_year",
        "usd_per_applied_w",
        "usd_per_applied_w_year",
    ]
    normalization_method: Literal[
        "divide_by_frozen_source_wdc",
        "multiply_quantity_then_divide_by_frozen_source_wdc",
        "divide_by_frozen_applied_capacity_w",
        "multiply_quantity_then_divide_by_frozen_applied_capacity_w",
        "already_normalized_per_wdc",
    ]
    solectria_quantity: FiniteNonnegativeFloat
    solaredge_quantity: FiniteNonnegativeFloat
    quantity_unit: NonemptyTechnoeconomicText | None = None
    normalization_derivation: NonemptyTechnoeconomicText
    constant_dollar_cost_year: Annotated[int, Field(ge=1900, le=3000)]
    currency_year_normalization: CurrencyYearNormalizationRequest
    evidence: TechnoeconomicEvidenceRequest

    @model_validator(mode="after")
    def validate_cost_line_contract(self) -> "TechnoeconomicCostLineRequest":
        includes = self.coverage_include_ids
        excludes = self.coverage_exclude_ids
        if len(set(includes)) != len(includes):
            raise ValueError("coverage_include_ids must be unique")
        if len(set(excludes)) != len(excludes):
            raise ValueError("coverage_exclude_ids must be unique")
        if set(includes) & set(excludes):
            raise ValueError("included and excluded coverage IDs must be disjoint")

        recurring = self.cost_type.startswith("recurring_")
        expected_normalized = (
            {"usd_per_wdc_year", "usd_per_applied_w_year"}
            if recurring
            else {"usd_per_wdc", "usd_per_applied_w"}
        )
        if self.normalized_unit not in expected_normalized:
            raise ValueError(
                f"{self.cost_type} requires one of normalized_unit="
                f"{sorted(expected_normalized)!r}"
            )
        annual_originals = {
            "usd_total_per_year",
            "usd_per_unit_year",
            "usd_per_wdc_year",
        }
        if (self.original_unit in annual_originals) != recurring:
            raise ValueError("original-unit timing must match the cost type")

        if self.normalization_method in {
            "divide_by_frozen_source_wdc",
            "divide_by_frozen_applied_capacity_w",
        }:
            if self.original_unit not in {"usd_total", "usd_total_per_year"}:
                raise ValueError("total-Wdc normalization requires a total-USD unit")
            if self.quantity_unit is not None:
                raise ValueError("total-Wdc normalization must not declare quantity_unit")
        elif self.normalization_method in {
            "multiply_quantity_then_divide_by_frozen_source_wdc",
            "multiply_quantity_then_divide_by_frozen_applied_capacity_w",
        }:
            if self.original_unit not in {"usd_per_unit", "usd_per_unit_year"}:
                raise ValueError("quantity normalization requires a per-unit USD unit")
            if self.quantity_unit is None:
                raise ValueError("quantity normalization requires quantity_unit")
        else:
            if self.original_unit not in {"usd_per_wdc", "usd_per_wdc_year"}:
                raise ValueError("already-normalized costs require a per-Wdc unit")
            if self.quantity_unit is not None:
                raise ValueError("already-normalized costs must not declare quantity_unit")

        sol = self.solectria_quantity
        se = self.solaredge_quantity
        if self.ownership == "solectria_only" and not (sol > 0 and se == 0):
            raise ValueError("solectria_only requires positive SOL and zero SE quantity")
        if self.ownership == "solaredge_only" and not (se > 0 and sol == 0):
            raise ValueError("solaredge_only requires zero SOL and positive SE quantity")
        if self.ownership == "paired_shared" and not (sol > 0 and se > 0):
            raise ValueError("paired_shared requires positive quantities for both systems")
        if self.normalization_method in {
            "divide_by_frozen_source_wdc",
            "divide_by_frozen_applied_capacity_w",
            "already_normalized_per_wdc",
        }:
            for value in (sol, se):
                if value not in {0.0, 1.0}:
                    raise ValueError(
                        "total or already-normalized lines use quantity 1 for each "
                        "applicable system and 0 otherwise"
                    )
        if (
            self.currency_year_normalization.target_constant_dollar_cost_year
            != self.constant_dollar_cost_year
        ):
            raise ValueError(
                "currency normalization target must equal the line constant-dollar cost year"
            )
        return self


class TechnoeconomicFinanceRequest(StrictTechnoeconomicRequest):
    treatment_key: Literal["constant-real-v1"]
    constant_dollar_cost_year: Annotated[int, Field(ge=1900, le=3000)]
    project_life_years: Annotated[int, Field(ge=1)]
    project_life_evidence: TechnoeconomicEvidenceRequest
    real_discount_rate: DocumentedDistributionRequest


class SharedDegradationRequest(StrictTechnoeconomicRequest):
    degradation_model: Literal["shared_module_v1"]
    annual_rate: DocumentedDistributionRequest


class CommercialTechnologyDesignRequest(StrictTechnoeconomicRequest):
    optimizer_count: Annotated[int, Field(ge=0)]
    inverter_count: Annotated[int, Field(ge=1)]
    transformer_count: Annotated[int, Field(ge=0)]
    dc_ac_ratio: FinitePositiveFloat
    inverter_loading_ratio: FinitePositiveFloat
    inverter_topology: NonemptyTechnoeconomicText
    transformer_topology: NonemptyTechnoeconomicText
    bos_scope: NonemptyTechnoeconomicText
    labor_productivity_and_rates: NonemptyTechnoeconomicText
    commissioning_scope: NonemptyTechnoeconomicText


class CommercialReferenceDesignRequest(StrictTechnoeconomicRequest):
    design_id: StableTechnoeconomicId
    reference_wdc: FinitePositiveFloat
    module_model: NonemptyTechnoeconomicText
    module_stc_wdc: FinitePositiveFloat
    module_count: Annotated[int, Field(ge=1)]
    constant_dollar_cost_year: Annotated[int, Field(ge=1900, le=3000)]
    solectria: CommercialTechnologyDesignRequest
    solaredge: CommercialTechnologyDesignRequest
    normalization_derivation: NonemptyTechnoeconomicText
    evidence: TechnoeconomicEvidenceRequest

    @model_validator(mode="after")
    def validate_reference_wdc(self) -> "CommercialReferenceDesignRequest":
        try:
            derived = Decimal(self.module_count) * Decimal(str(self.module_stc_wdc))
            recorded = Decimal(str(self.reference_wdc))
        except InvalidOperation as exc:
            raise ValueError("commercial reference Wdc is not a canonical decimal") from exc
        if derived != recorded:
            raise ValueError(
                "commercial module_count * module_stc_wdc must equal reference_wdc"
            )
        return self


CommercialTransferMechanism = Literal[
    "climate_and_irradiance",
    "module_string_optimizer_topology",
    "mismatch_mechanism",
    "shading",
    "row_and_tracker_geometry",
    "conversion_and_temperature",
    "dc_ac_ratio_and_clipping",
    "availability_and_outages",
    "curtailment",
    "soiling",
    "weather_representativeness",
    "degradation",
    "size_independence",
]

COMMERCIAL_TRANSFER_MECHANISMS = frozenset(
    {
        "climate_and_irradiance",
        "module_string_optimizer_topology",
        "mismatch_mechanism",
        "shading",
        "row_and_tracker_geometry",
        "conversion_and_temperature",
        "dc_ac_ratio_and_clipping",
        "availability_and_outages",
        "curtailment",
        "soiling",
        "weather_representativeness",
        "degradation",
        "size_independence",
    }
)


class CommercialTransferMechanismRequest(StrictTechnoeconomicRequest):
    mechanism: CommercialTransferMechanism
    status: Literal["supported", "not_applicable", "not_transferred"]
    rationale: NonemptyTechnoeconomicText
    evidence: TechnoeconomicEvidenceRequest


class CommercialEnergyTransferRequest(StrictTechnoeconomicRequest):
    status: Literal["approved"]
    explicit_attestation: Literal[True]
    attested_by: NonemptyTechnoeconomicText
    attested_at: str
    attestation_rationale: NonemptyTechnoeconomicText
    baseline_factor: DocumentedDistributionRequest
    incremental_factor: DocumentedDistributionRequest
    mechanisms: list[CommercialTransferMechanismRequest] = Field(
        min_length=len(COMMERCIAL_TRANSFER_MECHANISMS),
        max_length=len(COMMERCIAL_TRANSFER_MECHANISMS),
    )

    @model_validator(mode="after")
    def validate_complete_attestation(self) -> "CommercialEnergyTransferRequest":
        mechanisms = [item.mechanism for item in self.mechanisms]
        if len(set(mechanisms)) != len(mechanisms):
            raise ValueError("commercial transfer mechanisms must be unique")
        if set(mechanisms) != COMMERCIAL_TRANSFER_MECHANISMS:
            raise ValueError("commercial transfer requires the complete mechanism checklist")
        not_transferred = sorted(
            item.mechanism for item in self.mechanisms if item.status == "not_transferred"
        )
        if not_transferred:
            raise ValueError(
                "an approved commercial transfer cannot contain not_transferred "
                f"mechanisms: {not_transferred}; omit commercial_transfer for a cost-only request"
            )
        if not any(item.status == "supported" for item in self.mechanisms):
            raise ValueError(
                "an approved commercial transfer requires at least one supported mechanism"
            )
        try:
            attested = datetime.fromisoformat(self.attested_at.replace("Z", "+00:00"))
        except (AttributeError, ValueError) as exc:
            raise ValueError("attested_at must be an ISO-8601 timestamp") from exc
        if attested.tzinfo is None or attested.utcoffset() is None:
            raise ValueError("attested_at must include an explicit UTC offset")
        if self.baseline_factor.unit != "dimensionless_multiplier":
            raise ValueError("baseline transfer factor must be dimensionless")
        if self.incremental_factor.unit != "dimensionless_multiplier":
            raise ValueError("incremental transfer factor must be dimensionless")
        return self


class CommercialScalingRequest(StrictTechnoeconomicRequest):
    """Directly scale the frozen SolarTAC marginal energy to a target size."""

    target_capacity: FinitePositiveFloat
    target_capacity_unit: Literal["kw", "mw"]
    target_rating_basis: Literal[
        "ac_operating_limit",
        "dc_installed_nameplate",
    ]
    marginal_cost_difference: TechnoeconomicDistributionRequest
    marginal_cost_timing: Literal[
        "lifecycle_present_value",
        "equivalent_annual",
    ]
    marginal_cost_unit: Literal[
        "constant_usd",
        "constant_usd_per_year",
    ]
    transfer_method: Literal["direct_capacity_scaling"]
    transfer_rationale: NonemptyTechnoeconomicText
    evidence: TechnoeconomicEvidenceRequest

    @model_validator(mode="after")
    def validate_commercial_scaling_contract(self) -> "CommercialScalingRequest":
        expected_unit = (
            "constant_usd"
            if self.marginal_cost_timing == "lifecycle_present_value"
            else "constant_usd_per_year"
        )
        if self.marginal_cost_unit != expected_unit:
            raise ValueError(
                f"{self.marginal_cost_timing} marginal cost requires "
                f"marginal_cost_unit={expected_unit!r}"
            )
        multiplier = 1_000.0 if self.target_capacity_unit == "kw" else 1_000_000.0
        if not math.isfinite(self.target_capacity * multiplier):
            raise ValueError("commercial target capacity is not representable in watts")
        return self


class StandaloneCommercialCostLineRequest(StrictTechnoeconomicRequest):
    """One sourced commercial SolarEdge cost intensity and payment timing."""

    input_id: StableTechnoeconomicId
    label: NonemptyTechnoeconomicText
    cost_category: Literal[
        "full_initial_capex",
        "full_annual_om",
        "scheduled_replacement",
    ]
    coverage_ids: list[StableTechnoeconomicId] = Field(
        min_length=1,
        max_length=256,
    )
    timing: Literal[
        "initial_t0",
        "annual_year_end",
        "scheduled_year_end",
    ]
    unit: Literal[
        "constant_usd_per_target_w",
        "constant_usd_per_target_w_year",
    ]
    distribution: TechnoeconomicDistributionRequest
    constant_dollar_cost_year: Annotated[int, Field(ge=1900, le=3000)]
    occurrence_years: list[Annotated[int, Field(ge=1)]] = Field(
        default_factory=list,
        max_length=256,
    )
    evidence: TechnoeconomicEvidenceRequest

    @model_validator(mode="after")
    def validate_cost_timing(self) -> "StandaloneCommercialCostLineRequest":
        category_contract = {
            "full_initial_capex": (
                "initial_t0",
                "constant_usd_per_target_w",
            ),
            "full_annual_om": (
                "annual_year_end",
                "constant_usd_per_target_w_year",
            ),
            "scheduled_replacement": (
                "scheduled_year_end",
                "constant_usd_per_target_w",
            ),
        }
        expected_timing, expected_unit = category_contract[self.cost_category]
        if self.timing != expected_timing or self.unit != expected_unit:
            raise ValueError(
                f"{self.cost_category} requires timing={expected_timing!r} and "
                f"unit={expected_unit!r}"
            )
        if len(set(self.coverage_ids)) != len(self.coverage_ids):
            raise ValueError("commercial cost coverage IDs must be unique per line")
        if self.timing == "scheduled_year_end":
            if not self.occurrence_years:
                raise ValueError(
                    "scheduled commercial costs require at least one occurrence year"
                )
            if self.occurrence_years != sorted(set(self.occurrence_years)):
                raise ValueError(
                    "scheduled commercial occurrence years must be unique and "
                    "strictly increasing"
                )
        elif self.occurrence_years:
            raise ValueError(
                "only scheduled commercial costs may define occurrence years"
            )
        return self


class StandaloneCommercialRequest(StrictTechnoeconomicRequest):
    """Scale verified SolarEdge energy and a commercial cost stack to one size."""

    technology: Literal["solaredge"]
    target_capacity: FinitePositiveFloat
    target_capacity_unit: Literal["kw", "mw"]
    target_rating_basis: Literal[
        "ac_operating_limit",
        "dc_installed_nameplate",
    ]
    transfer_method: Literal["direct_capacity_scaling"]
    transfer_rationale: NonemptyTechnoeconomicText
    evidence: TechnoeconomicEvidenceRequest
    cost_lines: list[StandaloneCommercialCostLineRequest] = Field(
        min_length=1,
        max_length=1000,
    )

    @model_validator(mode="after")
    def validate_standalone_contract(self) -> "StandaloneCommercialRequest":
        multiplier = 1_000.0 if self.target_capacity_unit == "kw" else 1_000_000.0
        if not math.isfinite(self.target_capacity * multiplier):
            raise ValueError("commercial target capacity is not representable in watts")
        identifiers = [line.input_id for line in self.cost_lines]
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("standalone commercial cost input IDs must be unique")
        categories = [line.cost_category for line in self.cost_lines]
        for required in ("full_initial_capex", "full_annual_om"):
            if categories.count(required) != 1:
                raise ValueError(
                    "standalone commercial full-system costs require exactly one "
                    f"{required} line"
                )
        scheduled = [
            line
            for line in self.cost_lines
            if line.cost_category == "scheduled_replacement"
        ]
        for index, left in enumerate(scheduled):
            for right in scheduled[index + 1 :]:
                if set(left.coverage_ids) & set(right.coverage_ids) and set(
                    left.occurrence_years
                ) & set(right.occurrence_years):
                    raise ValueError(
                        "scheduled commercial replacement coverage must not "
                        "overlap at the same occurrence year"
                    )
        return self


class PairedCommercialSystemRequest(StrictTechnoeconomicRequest):
    """One complete commercial system cost stack and its energy evidence."""

    technology: Literal["solectria", "solaredge"]
    evidence: TechnoeconomicEvidenceRequest
    # V5 owns this cost stack.  V6 deliberately leaves it empty because the
    # lifecycle object below owns every initial, recurring, scheduled, and
    # reliability cost.  The parent validator enforces the version-specific
    # choice so an omitted list cannot silently weaken a V5 request.
    cost_lines: list[StandaloneCommercialCostLineRequest] = Field(
        default_factory=list,
        max_length=1000,
    )

    @model_validator(mode="after")
    def validate_system_cost_stack(self) -> "PairedCommercialSystemRequest":
        if not self.cost_lines:
            return self
        identifiers = [line.input_id for line in self.cost_lines]
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("paired commercial cost input IDs must be unique per system")
        categories = [line.cost_category for line in self.cost_lines]
        for required in ("full_initial_capex", "full_annual_om"):
            if categories.count(required) != 1:
                raise ValueError(
                    "paired commercial full-system costs require exactly one "
                    f"{required} line per system"
                )
        for index, left in enumerate(self.cost_lines):
            for right in self.cost_lines[index + 1 :]:
                if not set(left.coverage_ids) & set(right.coverage_ids):
                    continue
                both_scheduled = (
                    left.cost_category == "scheduled_replacement"
                    and right.cost_category == "scheduled_replacement"
                )
                if both_scheduled and not (
                    set(left.occurrence_years) & set(right.occurrence_years)
                ):
                    continue
                if both_scheduled:
                    raise ValueError(
                        "scheduled paired commercial replacement coverage must not "
                        "overlap at the same occurrence year within one system"
                    )
                raise ValueError(
                    "paired commercial coverage IDs must be disjoint between cost "
                    "lines unless both are scheduled replacements at disjoint years"
                )
        return self


LifecycleDistributionUnit = Literal[
    "constant_usd",
    "constant_usd_per_kwh_ac",
    "constant_usd_per_target_w",
    "constant_usd_per_target_w_year",
    "dimensionless",
    "dimensionless_fraction",
    "hours",
    "real_fraction_per_year",
    "years",
]


class LifecycleDocumentedDistributionRequest(StrictTechnoeconomicRequest):
    """One evidenced stochastic scalar in the V6 lifecycle contract."""

    unit: LifecycleDistributionUnit
    distribution: TechnoeconomicDistributionRequest
    evidence: TechnoeconomicEvidenceRequest


class LifecycleSourceAvailabilityRequest(StrictTechnoeconomicRequest):
    year: Annotated[int, Field(ge=1900, le=3000)]
    availability: Annotated[float, Field(gt=0, le=1, allow_inf_nan=False)]
    evidence: TechnoeconomicEvidenceRequest


class LifecycleInitialCostLineRequest(StrictTechnoeconomicRequest):
    input_id: StableTechnoeconomicId
    label: NonemptyTechnoeconomicText
    cost_per_w: LifecycleDocumentedDistributionRequest
    coverage_ids: list[StableTechnoeconomicId] = Field(min_length=1, max_length=256)
    evidence: TechnoeconomicEvidenceRequest

    @model_validator(mode="after")
    def validate_initial_cost_line(self) -> "LifecycleInitialCostLineRequest":
        if self.cost_per_w.unit != "constant_usd_per_target_w":
            raise ValueError("lifecycle initial cost must use constant_usd_per_target_w")
        if len(set(self.coverage_ids)) != len(self.coverage_ids):
            raise ValueError("lifecycle initial-cost coverage IDs must be unique")
        return self


class LifecycleScheduledCostRequest(StrictTechnoeconomicRequest):
    input_id: StableTechnoeconomicId
    label: NonemptyTechnoeconomicText
    cost: LifecycleDocumentedDistributionRequest
    real_cost_growth: LifecycleDocumentedDistributionRequest
    occurrence_years: list[Annotated[int, Field(ge=1)]] = Field(
        min_length=1,
        max_length=1000,
    )
    coverage_ids: list[StableTechnoeconomicId] = Field(min_length=1, max_length=256)
    evidence: TechnoeconomicEvidenceRequest

    @model_validator(mode="after")
    def validate_scheduled_cost(self) -> "LifecycleScheduledCostRequest":
        if self.cost.unit != "constant_usd":
            raise ValueError("lifecycle scheduled cost must use constant_usd")
        if self.real_cost_growth.unit != "real_fraction_per_year":
            raise ValueError("lifecycle scheduled cost growth must be a real annual fraction")
        if self.occurrence_years != sorted(set(self.occurrence_years)):
            raise ValueError("lifecycle scheduled occurrence years must be unique and increasing")
        if len(set(self.coverage_ids)) != len(self.coverage_ids):
            raise ValueError("lifecycle scheduled-cost coverage IDs must be unique")
        return self


class LifecyclePreventiveReplacementRequest(StrictTechnoeconomicRequest):
    year: Annotated[int, Field(ge=1)]
    quantity: Annotated[int, Field(ge=1)]
    coverage_ids: list[StableTechnoeconomicId] = Field(min_length=1, max_length=256)
    evidence: TechnoeconomicEvidenceRequest

    @model_validator(mode="after")
    def validate_preventive_replacement(self) -> "LifecyclePreventiveReplacementRequest":
        if len(set(self.coverage_ids)) != len(self.coverage_ids):
            raise ValueError("preventive-replacement coverage IDs must be unique")
        return self


class LifecycleWarrantyRequest(StrictTechnoeconomicRequest):
    age_limit_years: Annotated[int, Field(ge=0)]
    fraction: Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]
    covered_cost_categories: list[Literal["hardware", "labor", "mobilization"]] = Field(
        min_length=1,
        max_length=3,
    )
    coverage_ids: list[StableTechnoeconomicId] = Field(min_length=1, max_length=256)
    evidence: TechnoeconomicEvidenceRequest

    @model_validator(mode="after")
    def validate_warranty(self) -> "LifecycleWarrantyRequest":
        if len(set(self.covered_cost_categories)) != len(self.covered_cost_categories):
            raise ValueError("warranty covered-cost categories must be unique")
        if len(set(self.coverage_ids)) != len(self.coverage_ids):
            raise ValueError("warranty coverage IDs must be unique")
        return self


class LifecycleComponentRequest(StrictTechnoeconomicRequest):
    component_id: StableTechnoeconomicId
    category: StableTechnoeconomicId
    count: Annotated[int, Field(ge=1)]
    capacity_impact: Annotated[float, Field(gt=0, le=1, allow_inf_nan=False)]
    weibull_beta: LifecycleDocumentedDistributionRequest
    weibull_eta_years: LifecycleDocumentedDistributionRequest
    repair_hours: LifecycleDocumentedDistributionRequest
    logistics_hours: LifecycleDocumentedDistributionRequest
    emergency_unit_cost: LifecycleDocumentedDistributionRequest
    restock_unit_cost: LifecycleDocumentedDistributionRequest
    labor_cost: LifecycleDocumentedDistributionRequest
    mobilization_cost: LifecycleDocumentedDistributionRequest
    real_cost_growth: LifecycleDocumentedDistributionRequest
    batch_size: Annotated[int, Field(ge=1)]
    initial_spares: Annotated[int, Field(ge=0)]
    spare_target: Annotated[int, Field(ge=0)]
    warranty: LifecycleWarrantyRequest | None = None
    preventive_replacements: list[LifecyclePreventiveReplacementRequest] = Field(
        default_factory=list,
        max_length=1000,
    )
    coverage_ids: list[StableTechnoeconomicId] = Field(min_length=1, max_length=256)
    evidence: TechnoeconomicEvidenceRequest

    @model_validator(mode="after")
    def validate_component(self) -> "LifecycleComponentRequest":
        expected_units = {
            "weibull_beta": "dimensionless",
            "weibull_eta_years": "years",
            "repair_hours": "hours",
            "logistics_hours": "hours",
            "emergency_unit_cost": "constant_usd",
            "restock_unit_cost": "constant_usd",
            "labor_cost": "constant_usd",
            "mobilization_cost": "constant_usd",
            "real_cost_growth": "real_fraction_per_year",
        }
        for field_name, expected_unit in expected_units.items():
            if getattr(self, field_name).unit != expected_unit:
                raise ValueError(
                    f"lifecycle component {field_name} must use {expected_unit}"
                )
        years = [item.year for item in self.preventive_replacements]
        if years != sorted(set(years)):
            raise ValueError("preventive replacement years must be unique and increasing")
        if len(set(self.coverage_ids)) != len(self.coverage_ids):
            raise ValueError("component coverage IDs must be unique")
        return self


class LifecycleSystemRequest(StrictTechnoeconomicRequest):
    technology: Literal["solectria", "solaredge"]
    degradation: LifecycleDocumentedDistributionRequest
    base_availability: LifecycleDocumentedDistributionRequest
    base_om_cost_per_w_year: LifecycleDocumentedDistributionRequest
    base_om_real_growth: LifecycleDocumentedDistributionRequest
    initial_cost_lines: list[LifecycleInitialCostLineRequest] = Field(
        min_length=1,
        max_length=1000,
    )
    scheduled_costs: list[LifecycleScheduledCostRequest] = Field(
        default_factory=list,
        max_length=1000,
    )
    components: list[LifecycleComponentRequest] = Field(min_length=1, max_length=256)
    decommissioning_cost: LifecycleDocumentedDistributionRequest
    salvage_value: LifecycleDocumentedDistributionRequest
    source_availability_by_year: list[LifecycleSourceAvailabilityRequest] = Field(
        default_factory=list,
        max_length=200,
    )
    base_om_coverage_ids: list[StableTechnoeconomicId] = Field(
        min_length=1,
        max_length=256,
    )
    evidence: TechnoeconomicEvidenceRequest

    @model_validator(mode="after")
    def validate_lifecycle_system(self) -> "LifecycleSystemRequest":
        expected_units = {
            "degradation": "real_fraction_per_year",
            "base_availability": "dimensionless_fraction",
            "base_om_cost_per_w_year": "constant_usd_per_target_w_year",
            "base_om_real_growth": "real_fraction_per_year",
            "decommissioning_cost": "constant_usd",
            "salvage_value": "constant_usd",
        }
        for field_name, expected_unit in expected_units.items():
            if getattr(self, field_name).unit != expected_unit:
                raise ValueError(
                    f"lifecycle system {field_name} must use {expected_unit}"
                )
        initial_ids = [item.input_id for item in self.initial_cost_lines]
        scheduled_ids = [item.input_id for item in self.scheduled_costs]
        component_ids = [item.component_id for item in self.components]
        if len(set(initial_ids + scheduled_ids)) != len(initial_ids) + len(scheduled_ids):
            raise ValueError("lifecycle system cost input IDs must be unique")
        if len(set(component_ids)) != len(component_ids):
            raise ValueError("lifecycle component IDs must be unique per system")
        weather_years = [item.year for item in self.source_availability_by_year]
        if weather_years != sorted(set(weather_years)):
            raise ValueError("source availability years must be unique and increasing")
        if len(set(self.base_om_coverage_ids)) != len(self.base_om_coverage_ids):
            raise ValueError("base-O&M coverage IDs must be unique")
        return self


class LifecycleCommonCauseRequest(StrictTechnoeconomicRequest):
    event_id: StableTechnoeconomicId
    annual_probability: LifecycleDocumentedDistributionRequest
    downtime_hours: LifecycleDocumentedDistributionRequest
    capacity_impact: Annotated[float, Field(gt=0, le=1, allow_inf_nan=False)]
    cost_per_event: LifecycleDocumentedDistributionRequest
    real_cost_growth: LifecycleDocumentedDistributionRequest
    affected_systems: list[Literal["solectria", "solaredge"]] = Field(
        min_length=1,
        max_length=2,
    )
    coverage_ids: list[StableTechnoeconomicId] = Field(min_length=1, max_length=256)
    evidence: TechnoeconomicEvidenceRequest

    @model_validator(mode="after")
    def validate_common_cause(self) -> "LifecycleCommonCauseRequest":
        expected_units = {
            "annual_probability": "dimensionless_fraction",
            "downtime_hours": "hours",
            "cost_per_event": "constant_usd",
            "real_cost_growth": "real_fraction_per_year",
        }
        for field_name, expected_unit in expected_units.items():
            if getattr(self, field_name).unit != expected_unit:
                raise ValueError(
                    f"lifecycle common-cause {field_name} must use {expected_unit}"
                )
        if len(set(self.affected_systems)) != len(self.affected_systems):
            raise ValueError("common-cause affected systems must be unique")
        if len(set(self.coverage_ids)) != len(self.coverage_ids):
            raise ValueError("common-cause coverage IDs must be unique")
        return self


class PairedLifecycleRequest(StrictTechnoeconomicRequest):
    weather_path_method: Literal[
        "paired-yearwise-balanced-across-realizations-independent-across-project-years-v1"
    ]
    source_energy_basis: Literal["gross", "net"]
    reliability_mode: Literal["event", "expected"]
    electricity_value: LifecycleDocumentedDistributionRequest
    electricity_value_real_growth: LifecycleDocumentedDistributionRequest
    systems: list[LifecycleSystemRequest] = Field(min_length=2, max_length=2)
    common_cause_events: list[LifecycleCommonCauseRequest] = Field(
        default_factory=list,
        max_length=256,
    )
    decision_probability_threshold: Annotated[
        float,
        Field(gt=0.5, le=1, allow_inf_nan=False),
    ] = 0.75
    decision_npv_tolerance_usd_per_target_w: FinitePositiveFloat

    @model_validator(mode="after")
    def validate_paired_lifecycle(self) -> "PairedLifecycleRequest":
        if self.electricity_value.unit != "constant_usd_per_kwh_ac":
            raise ValueError("lifecycle electricity value must use constant_usd_per_kwh_ac")
        if self.electricity_value_real_growth.unit != "real_fraction_per_year":
            raise ValueError("lifecycle electricity-value growth must be a real annual fraction")
        technologies = [system.technology for system in self.systems]
        if len(set(technologies)) != 2 or set(technologies) != {
            "solectria",
            "solaredge",
        }:
            raise ValueError(
                "paired lifecycle systems require exactly one Solectria and one SolarEdge"
            )
        event_ids = [event.event_id for event in self.common_cause_events]
        if len(set(event_ids)) != len(event_ids):
            raise ValueError("common-cause event IDs must be unique")
        lifecycle_cost_ids = [
            line.input_id
            for system in self.systems
            for line in (*system.initial_cost_lines, *system.scheduled_costs)
        ]
        if len(set(lifecycle_cost_ids)) != len(lifecycle_cost_ids):
            raise ValueError("lifecycle cost input IDs must be globally unique")
        if self.source_energy_basis == "gross" and any(
            system.source_availability_by_year for system in self.systems
        ):
            raise ValueError(
                "gross source energy must not declare source availability corrections"
            )
        if self.source_energy_basis == "net" and any(
            not system.source_availability_by_year for system in self.systems
        ):
            raise ValueError(
                "net source energy requires source availability evidence for both systems"
            )
        return self


class PairedCommercialRequest(StrictTechnoeconomicRequest):
    """Scale both verified systems to one common commercial target."""

    target_capacity: FinitePositiveFloat
    target_capacity_unit: Literal["kw", "mw"]
    target_rating_basis: Literal[
        "ac_operating_limit",
        "dc_installed_nameplate",
    ]
    transfer_method: Literal["direct_capacity_scaling"]
    transfer_rationale: NonemptyTechnoeconomicText
    evidence: TechnoeconomicEvidenceRequest
    systems: list[PairedCommercialSystemRequest] = Field(
        min_length=2,
        max_length=2,
    )
    lifecycle: PairedLifecycleRequest | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )

    @model_validator(mode="after")
    def validate_paired_contract(self) -> "PairedCommercialRequest":
        multiplier = 1_000.0 if self.target_capacity_unit == "kw" else 1_000_000.0
        if not math.isfinite(self.target_capacity * multiplier):
            raise ValueError("paired commercial target capacity is not representable in watts")
        technologies = [system.technology for system in self.systems]
        if len(set(technologies)) != 2 or set(technologies) != {
            "solectria",
            "solaredge",
        }:
            raise ValueError(
                "paired commercial systems require exactly one Solectria and one SolarEdge"
            )
        identifiers = [
            line.input_id
            for system in self.systems
            for line in system.cost_lines
        ]
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("paired commercial cost input IDs must be globally unique")
        if self.lifecycle is None and any(not system.cost_lines for system in self.systems):
            raise ValueError("v5 paired commercial requires a complete cost stack per system")
        if self.lifecycle is not None and any(system.cost_lines for system in self.systems):
            raise ValueError(
                "v6 lifecycle owns all system costs; paired commercial cost_lines must be empty"
            )
        if self.lifecycle is not None and {
            system.technology for system in self.lifecycle.systems
        } != set(technologies):
            raise ValueError("paired commercial and lifecycle technologies must match")
        return self


class TechnoeconomicSubmissionRequest(StrictTechnoeconomicRequest):
    source_annual_job_id: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=200),
    ]
    basis: Literal["solartac_site", "commercial_representative"]
    capacity_normalization: Literal["annual_applied_capacity_v1"] | None = None
    n: Annotated[int, Field(ge=1, le=100_000)]
    seed: Annotated[int, Field(ge=0, le=(1 << 64) - 1)]
    cost_stack_completeness: Literal["full_system"]
    # V4 owns a separate commercial cost stack.  Defaulting the legacy stack to
    # empty lets that request omit it, while the validator below continues to
    # require at least one legacy line for v1-v3.
    cost_lines: list[TechnoeconomicCostLineRequest] = Field(
        default_factory=list,
        max_length=1000,
    )
    finance: TechnoeconomicFinanceRequest
    calculation_contract_version: Literal[
        "tea-calculation-v1",
        "tea-calculation-v2",
        "tea-calculation-v3",
        "tea-calculation-v4",
        "tea-calculation-v5",
        "tea-calculation-v6",
    ] | None = Field(default=None, exclude_if=lambda value: value is None)
    shared_degradation: SharedDegradationRequest | None = None
    commercial_reference_design: CommercialReferenceDesignRequest | None = None
    commercial_transfer: CommercialEnergyTransferRequest | None = None
    commercial_scaling: CommercialScalingRequest | None = None
    standalone_commercial: StandaloneCommercialRequest | None = None
    paired_commercial: PairedCommercialRequest | None = None

    @model_validator(mode="after")
    def validate_submission_contract(self) -> "TechnoeconomicSubmissionRequest":
        lifecycle = (
            self.paired_commercial.lifecycle
            if self.paired_commercial is not None
            else None
        )
        if lifecycle is not None and self.calculation_contract_version is None:
            raise ValueError(
                "paired_commercial.lifecycle requires explicit "
                "calculation_contract_version='tea-calculation-v6'"
            )
        if self.calculation_contract_version == "tea-calculation-v6" and lifecycle is None:
            raise ValueError(
                "tea-calculation-v6 requires paired_commercial.lifecycle"
            )
        if lifecycle is not None and self.calculation_contract_version != "tea-calculation-v6":
            raise ValueError(
                "paired_commercial.lifecycle is only valid for tea-calculation-v6"
            )
        if lifecycle is not None and self.shared_degradation is not None:
            raise ValueError(
                "tea-calculation-v6 uses separate lifecycle degradation; "
                "shared_degradation must be omitted"
            )
        if lifecycle is None and self.shared_degradation is None:
            raise ValueError("tea-calculation-v1 through v5 require shared_degradation")
        inferred_contract_version = (
            "tea-calculation-v6"
            if lifecycle is not None
            else "tea-calculation-v5"
            if self.paired_commercial is not None
            else "tea-calculation-v4"
            if self.standalone_commercial is not None
            else "tea-calculation-v3"
            if self.commercial_scaling is not None
            else "tea-calculation-v2"
            if self.capacity_normalization == ANNUAL_APPLIED_CAPACITY_NORMALIZATION
            else "tea-calculation-v1"
        )
        if (
            self.calculation_contract_version is not None
            and self.calculation_contract_version != inferred_contract_version
        ):
            raise ValueError(
                "calculation_contract_version does not match the submitted request shape: "
                f"expected {inferred_contract_version}"
            )
        input_ids = [line.input_id for line in self.cost_lines]
        standalone_lines = (
            self.standalone_commercial.cost_lines
            if self.standalone_commercial is not None
            else []
        )
        paired_lines = [
            line
            for system in (
                self.paired_commercial.systems
                if self.paired_commercial is not None
                else []
            )
            for line in system.cost_lines
        ]
        commercial_lines = standalone_lines + paired_lines
        commercial_input_ids = [line.input_id for line in commercial_lines]
        if (
            self.standalone_commercial is not None
            and self.paired_commercial is not None
        ):
            raise ValueError(
                "standalone_commercial and paired_commercial are mutually exclusive"
            )
        if (
            self.standalone_commercial is None
            and self.paired_commercial is None
            and not self.cost_lines
        ):
            raise ValueError("v1-v3 technoeconomic requests require legacy cost lines")
        if self.standalone_commercial is not None and self.cost_lines:
            raise ValueError(
                "standalone_commercial owns its commercial cost lines; legacy "
                "top-level cost_lines must be empty"
            )
        if self.paired_commercial is not None and self.cost_lines:
            raise ValueError(
                "paired_commercial owns its system cost lines; legacy top-level "
                "cost_lines must be empty"
            )
        if len(set(input_ids)) != len(input_ids):
            raise ValueError("cost input IDs must be unique")
        reserved = {
            "finance.discount-rate",
            "energy.shared-degradation",
            "energy.source.solectria_specific",
            "energy.source.solaredge_specific",
            "transfer.baseline",
            "transfer.incremental",
            "commercial.marginal-cost-difference",
            "weather.year",
        }
        collision = reserved & set(input_ids)
        if collision:
            raise ValueError(f"cost input IDs use reserved identifiers: {sorted(collision)}")
        standalone_input_ids = [line.input_id for line in standalone_lines]
        standalone_collision = reserved & set(standalone_input_ids)
        if standalone_collision:
            raise ValueError(
                "standalone commercial cost input IDs use reserved identifiers: "
                f"{sorted(standalone_collision)}"
            )
        paired_input_ids = [line.input_id for line in paired_lines]
        paired_collision = reserved & set(paired_input_ids)
        if paired_collision:
            raise ValueError(
                "paired commercial cost input IDs use reserved identifiers: "
                f"{sorted(paired_collision)}"
            )
        if set(input_ids) & set(standalone_input_ids):
            raise ValueError("legacy and standalone commercial input IDs must be disjoint")
        if set(input_ids) & set(paired_input_ids):
            raise ValueError("legacy and paired commercial input IDs must be disjoint")
        if any(
            line.constant_dollar_cost_year != self.finance.constant_dollar_cost_year
            for line in self.cost_lines
        ):
            raise ValueError(
                "every cost line must use the finance constant-dollar cost year"
            )
        if any(
            line.constant_dollar_cost_year != self.finance.constant_dollar_cost_year
            for line in commercial_lines
        ):
            raise ValueError(
                "every standalone commercial cost line must use the finance "
                "constant-dollar cost year"
            )
        if self.finance.real_discount_rate.unit != "real_fraction_per_year":
            raise ValueError("real discount rate must use real_fraction_per_year")
        if (
            self.shared_degradation is not None
            and self.shared_degradation.annual_rate.unit != "real_fraction_per_year"
        ):
            raise ValueError("shared degradation must use real_fraction_per_year")
        if any(
            year > self.finance.project_life_years
            for line in commercial_lines
            for year in line.occurrence_years
        ):
            raise ValueError(
                "scheduled commercial occurrence years must fall within project life"
            )
        if lifecycle is not None:
            if any(
                year > self.finance.project_life_years
                for system in lifecycle.systems
                for line in system.scheduled_costs
                for year in line.occurrence_years
            ):
                raise ValueError(
                    "lifecycle scheduled occurrence years must fall within project life"
                )
            if any(
                replacement.year > self.finance.project_life_years
                for system in lifecycle.systems
                for component in system.components
                for replacement in component.preventive_replacements
            ):
                raise ValueError(
                    "preventive replacement years must fall within project life"
                )

        if self.basis == "solartac_site":
            if self.commercial_reference_design is not None or self.commercial_transfer is not None:
                raise ValueError(
                    "SolarTAC site requests must not include commercial design or transfer"
                )
            if self.capacity_normalization == ANNUAL_APPLIED_CAPACITY_NORMALIZATION:
                expected_units = {
                    "usd_per_applied_w",
                    "usd_per_applied_w_year",
                }
                expected_methods = {
                    "divide_by_frozen_applied_capacity_w",
                    "multiply_quantity_then_divide_by_frozen_applied_capacity_w",
                }
                if any(
                    line.normalized_unit not in expected_units
                    or line.normalization_method not in expected_methods
                    for line in self.cost_lines
                ):
                    raise ValueError(
                        "annual_applied_capacity_v1 SolarTAC costs must be source "
                        "totals normalized by frozen applied-capacity watts"
                    )
            elif any(
                line.normalized_unit not in {"usd_per_wdc", "usd_per_wdc_year"}
                or line.normalization_method == "already_normalized_per_wdc"
                or "applied_capacity" in line.normalization_method
                for line in self.cost_lines
            ):
                raise ValueError(
                    "legacy SolarTAC site costs must be source totals normalized "
                    "by frozen Wdc"
                )
            if self.commercial_scaling is not None and (
                self.capacity_normalization
                != ANNUAL_APPLIED_CAPACITY_NORMALIZATION
            ):
                raise ValueError(
                    "commercial_scaling requires SolarTAC "
                    "capacity_normalization='annual_applied_capacity_v1'"
                )
            if self.standalone_commercial is not None:
                if self.commercial_scaling is not None:
                    raise ValueError(
                        "commercial_scaling and standalone_commercial are mutually exclusive"
                    )
                if (
                    self.capacity_normalization
                    != ANNUAL_APPLIED_CAPACITY_NORMALIZATION
                ):
                    raise ValueError(
                        "standalone_commercial requires SolarTAC "
                        "capacity_normalization='annual_applied_capacity_v1'"
                    )
            if self.paired_commercial is not None:
                if self.commercial_scaling is not None:
                    raise ValueError(
                        "commercial_scaling and paired_commercial are mutually exclusive"
                    )
                if (
                    self.capacity_normalization
                    != ANNUAL_APPLIED_CAPACITY_NORMALIZATION
                ):
                    raise ValueError(
                        "paired_commercial requires SolarTAC "
                        "capacity_normalization='annual_applied_capacity_v1'"
                    )
        else:
            if self.standalone_commercial is not None:
                raise ValueError(
                    "standalone_commercial is only valid for the SolarTAC site basis"
                )
            if self.commercial_scaling is not None:
                raise ValueError(
                    "commercial_scaling is only valid for the SolarTAC site basis"
                )
            if self.paired_commercial is not None:
                raise ValueError(
                    "paired_commercial is only valid for the SolarTAC site basis"
                )
            if self.capacity_normalization is not None:
                raise ValueError(
                    "commercial_representative must not declare SolarTAC capacity normalization"
                )
            if self.commercial_reference_design is None:
                raise ValueError(
                    "commercial_representative requires a commercial reference design"
                )
            if (
                self.commercial_reference_design.constant_dollar_cost_year
                != self.finance.constant_dollar_cost_year
            ):
                raise ValueError(
                    "commercial design and finance must use the same constant-dollar cost year"
                )
            if any(
                line.normalization_method != "already_normalized_per_wdc"
                or line.normalized_unit
                not in {"usd_per_wdc", "usd_per_wdc_year"}
                for line in self.cost_lines
            ):
                raise ValueError(
                    "commercial representative costs must declare a sourced per-Wdc basis"
                )

        lifecycle_distributions: list[TechnoeconomicDistributionRequest] = []
        if lifecycle is not None:
            lifecycle_distributions.extend(
                (
                    lifecycle.electricity_value.distribution,
                    lifecycle.electricity_value_real_growth.distribution,
                )
            )
            for system in lifecycle.systems:
                lifecycle_distributions.extend(
                    (
                        system.degradation.distribution,
                        system.base_availability.distribution,
                        system.base_om_cost_per_w_year.distribution,
                        system.base_om_real_growth.distribution,
                        system.decommissioning_cost.distribution,
                        system.salvage_value.distribution,
                    )
                )
                lifecycle_distributions.extend(
                    line.cost_per_w.distribution for line in system.initial_cost_lines
                )
                for line in system.scheduled_costs:
                    lifecycle_distributions.extend(
                        (line.cost.distribution, line.real_cost_growth.distribution)
                    )
                for component in system.components:
                    lifecycle_distributions.extend(
                        getattr(component, field_name).distribution
                        for field_name in (
                            "weibull_beta",
                            "weibull_eta_years",
                            "repair_hours",
                            "logistics_hours",
                            "emergency_unit_cost",
                            "restock_unit_cost",
                            "labor_cost",
                            "mobilization_cost",
                            "real_cost_growth",
                        )
                    )
            for event in lifecycle.common_cause_events:
                lifecycle_distributions.extend(
                    getattr(event, field_name).distribution
                    for field_name in (
                        "annual_probability",
                        "downtime_hours",
                        "cost_per_event",
                        "real_cost_growth",
                    )
                )

        declared_input_count = len(self.cost_lines) + len(commercial_lines) + 2
        if self.commercial_transfer is not None:
            declared_input_count += 2
        if self.commercial_scaling is not None:
            declared_input_count += 1
        estimated_realization_columns = (
            TECHNOECONOMIC_REALIZATION_COLUMN_OVERHEAD + declared_input_count
        )
        if self.commercial_scaling is not None:
            estimated_realization_columns += (
                TECHNOECONOMIC_COMMERCIAL_SCALING_REALIZATION_COLUMN_OVERHEAD
            )
        if self.standalone_commercial is not None:
            estimated_realization_columns += (
                TECHNOECONOMIC_STANDALONE_COMMERCIAL_REALIZATION_COLUMN_OVERHEAD
            )
        if lifecycle is not None:
            estimated_realization_columns = (
                TECHNOECONOMIC_LIFECYCLE_REALIZATION_COLUMN_OVERHEAD
                + 1  # shared discount-rate realization
                + len(lifecycle_distributions)
            )
        elif self.paired_commercial is not None:
            estimated_realization_columns += (
                TECHNOECONOMIC_PAIRED_COMMERCIAL_REALIZATION_COLUMN_OVERHEAD
            )
        realization_export_cells = self.n * estimated_realization_columns
        if realization_export_cells > TECHNOECONOMIC_MAX_REALIZATION_EXPORT_CELLS:
            if lifecycle is None:
                raise ValueError(
                    "technoeconomic realization export cell budget exceeded: "
                    f"{realization_export_cells} > "
                    f"{TECHNOECONOMIC_MAX_REALIZATION_EXPORT_CELLS}"
                )

        distributions = [line.distribution for line in self.cost_lines]
        distributions.append(self.finance.real_discount_rate.distribution)
        if self.shared_degradation is not None:
            distributions.append(self.shared_degradation.annual_rate.distribution)
        if self.commercial_transfer is not None:
            distributions.extend(
                (
                    self.commercial_transfer.baseline_factor.distribution,
                    self.commercial_transfer.incremental_factor.distribution,
                )
            )
        if self.commercial_scaling is not None:
            distributions.append(self.commercial_scaling.marginal_cost_difference)
        distributions.extend(line.distribution for line in commercial_lines)
        distributions.extend(lifecycle_distributions)
        nonfixed_predictor_count = sum(
            distribution.family != "fixed"
            and not (
                distribution.family in {"uniform", "triangular"}
                and distribution.low == distribution.high
            )
            for distribution in distributions
        )
        sensitivity_work_units = self.n * nonfixed_predictor_count**2
        if (
            lifecycle is None
            and sensitivity_work_units > TECHNOECONOMIC_MAX_SENSITIVITY_WORK_UNITS
        ):
            raise ValueError(
                "technoeconomic sensitivity work budget exceeded: "
                f"{sensitivity_work_units} > "
                f"{TECHNOECONOMIC_MAX_SENSITIVITY_WORK_UNITS}"
            )
        return self


__all__ = [
    "ANNUAL_APPLIED_CAPACITY_NORMALIZATION",
    "AnnualRunRequest",
    "AnnualRunSubmission",
    "BoundedNormalDistributionRequest",
    "CalibrationDecisionRequest",
    "ChatMessage",
    "ChatRequest",
    "COMMERCIAL_TRANSFER_MECHANISMS",
    "CommercialEnergyTransferRequest",
    "CommercialReferenceDesignRequest",
    "CommercialScalingRequest",
    "CommercialTechnologyDesignRequest",
    "CommercialTransferMechanismRequest",
    "CurrencyYearNormalizationRequest",
    "DocumentedDistributionRequest",
    "EvidenceCitationRequest",
    "FixedDistributionRequest",
    "LifecycleCommonCauseRequest",
    "LifecycleComponentRequest",
    "LifecycleDocumentedDistributionRequest",
    "LifecycleInitialCostLineRequest",
    "LifecyclePreventiveReplacementRequest",
    "LifecycleScheduledCostRequest",
    "LifecycleSourceAvailabilityRequest",
    "LifecycleSystemRequest",
    "LifecycleWarrantyRequest",
    "PairedLifecycleRequest",
    "PriceIndexCurrencyNormalizationRequest",
    "ProposalEditRequest",
    "ProposalSweepConfirmRequest",
    "RunRequest",
    "SavedResultCreateRequest",
    "SavedResultRenameRequest",
    "SeasonalFallbackAcknowledgement",
    "SharedDegradationRequest",
    "SameYearCurrencyNormalizationRequest",
    "StrictRequest",
    "StrictTechnoeconomicRequest",
    "StandaloneCommercialCostLineRequest",
    "StandaloneCommercialRequest",
    "PairedCommercialRequest",
    "PairedCommercialSystemRequest",
    "TechnoeconomicCostLineRequest",
    "TechnoeconomicDistributionRequest",
    "TechnoeconomicEvidenceRequest",
    "TechnoeconomicFinanceRequest",
    "TechnoeconomicSubmissionRequest",
    "TriangularDistributionRequest",
    "UniformDistributionRequest",
]
