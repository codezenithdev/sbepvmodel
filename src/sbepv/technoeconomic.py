"""Pure probabilistic technoeconomic calculation kernel.

The module intentionally has no API, persistence, worker, filesystem, plotting, or
dashboard dependencies.  It implements the approved Phase-0 calculation contract so
later phases can freeze an immutable request, run it durably, and export the returned
tables without duplicating any economic or statistical arithmetic.

All marginal fields use the explicit SolarEdge-minus-Solectria sign convention.
Costs are constant-real-dollar intensities.  Version 1 normalizes SolarTAC cost and
energy by installed module DC-STC Wdc.  Version 2 can instead freeze the applied
Annual Simulation capacity (an AC operating limit when clipping is enabled, otherwise
the installed DC nameplate) and normalizes both systems on that explicit basis.
Version 3 additionally scales the source-specific energy difference to an explicitly
rated commercial target and evaluates a separately supplied, consistently timed
commercial marginal-cost difference without changing the site-cost LCOO.  Version 4
adds a separate standalone commercial SolarEdge LCOE whose energy comes only from the
SolarEdge Annual realization and whose lifecycle costs come from a dedicated,
probabilistic commercial cost stack.  Version 5 adds the matching standalone
Solectria calculation while preserving the same paired weather-year draw.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field, replace
from decimal import Decimal, InvalidOperation, localcontext
from hashlib import sha256
import math
import re
from typing import Any, Callable, Literal

import numpy as np
import scipy
from scipy.stats import truncnorm


LEGACY_CALCULATION_CONTRACT_VERSION = "tea-calculation-v1"
CALCULATION_CONTRACT_VERSION = "tea-calculation-v2"
COMMERCIAL_SCALING_CALCULATION_CONTRACT_VERSION = "tea-calculation-v3"
STANDALONE_COMMERCIAL_CALCULATION_CONTRACT_VERSION = "tea-calculation-v4"
PAIRED_COMMERCIAL_CALCULATION_CONTRACT_VERSION = "tea-calculation-v5"
SAMPLING_VERSION = "tea-lhs-v1"
NUMERICAL_CONTRACT_VERSION = "tea-numerics-v1"
# The versions this contract was authored and hand-verified against.  They are
# recorded in provenance and named in diagnostics; they are not the gate.  The
# gate is the behavioural fingerprint below, which checks the properties the
# contract actually depends on instead of a version string that changes for
# thousands of unrelated reasons.
CONTRACT_NUMPY_VERSION = "2.5.0"
CONTRACT_SCIPY_VERSION = "1.18.0"
SUPPORTED_COST_TREATMENT = "constant-real-v1"

LHS_JITTER_PURPOSE = "lhs-jitter"
LHS_PERMUTATION_PURPOSE = "lhs-permutation"
WEATHER_EXTRA_PURPOSE = "weather-extra-permutation"
WEATHER_ASSIGNMENT_PURPOSE = "weather-assignment-permutation"
WEATHER_STABLE_ID = "weather.year"
SENSITIVITY_SOURCE_INPUT_IDS = frozenset(
    {
        "energy.source.solectria_specific",
        "energy.source.solaredge_specific",
    }
)
RESERVED_INPUT_IDS = frozenset({WEATHER_STABLE_ID}) | SENSITIVITY_SOURCE_INPUT_IDS
COMMERCIAL_MARGINAL_COST_DIFFERENCE_INPUT_ID = (
    "commercial.marginal-cost-difference"
)
COMMERCIAL_SCALING_TRANSFER_METHOD = "direct_capacity_scaling"
RNG_DOMAIN = b"sbepv-tea-lhs-v1\0"

R2_ENTRY_THRESHOLD = 1e-6
R2_TIE_ABSOLUTE_TOLERANCE = 1e-12
HIGH_RANK_CORRELATION_WARNING = 0.97
MAX_REALIZATIONS = 100_000
UINT64_MODULUS = 1 << 64

STABLE_ID_RE = re.compile(r"[a-z0-9._:-]+", re.ASCII)

DistributionFamily = Literal["fixed", "uniform", "triangular", "bounded_normal"]
DistributionRole = Literal[
    "generic",
    "cost",
    "discount_rate",
    "degradation",
    "transfer_baseline",
    "transfer_incremental",
]
AnalysisBasis = Literal["solartac_site", "commercial_representative"]
SystemName = Literal["solectria", "solaredge"]
AppliedCapacityRatingBasis = Literal[
    "ac_operating_limit",
    "dc_installed_nameplate",
]
CostOwnership = Literal["solectria_only", "solaredge_only", "paired_shared"]
CostType = Literal[
    "initial_capex",
    "initial_installation_labor",
    "recurring_labor",
    "recurring_om",
    "recurring_maintenance",
]
MarginalCostTiming = Literal["lifecycle_present_value", "equivalent_annual"]
CommercialScalingTransferMethod = Literal["direct_capacity_scaling"]
CommercialCostTiming = Literal[
    "initial_t0",
    "annual_year_end",
    "scheduled_year_end",
]
CommercialCostCategory = Literal[
    "full_initial_capex",
    "full_annual_om",
    "scheduled_replacement",
]

INITIAL_COST_TYPES = frozenset({"initial_capex", "initial_installation_labor"})
RECURRING_COST_TYPES = frozenset(
    {"recurring_labor", "recurring_om", "recurring_maintenance"}
)
ENERGY_CLASSES = (
    "positive_lifecycle_gain",
    "zero_lifecycle_gain",
    "negative_lifecycle_gain",
)
COST_CLASSES = ("cost_increase", "cost_neutral", "cost_saving")
TRADEOFF_CLASSES = (
    "cost_increase_energy_gain",
    "cost_neutral_energy_gain",
    "cost_saving_energy_gain",
    "cost_increase_energy_loss",
    "cost_neutral_energy_loss",
    "cost_saving_energy_loss",
    "cost_increase_zero_energy_change",
    "cost_neutral_zero_energy_change",
    "cost_saving_zero_energy_change",
)

FIELD_YEAR1_SOL = "Year1SpecificEnergy_SOL_kWh_AC_per_Wdc_year"
FIELD_YEAR1_SE = "Year1SpecificEnergy_SE_kWh_AC_per_Wdc_year"
FIELD_YEAR1_DELTA = "Year1DeltaSpecificEnergy_se_minus_sol_kWh_AC_per_Wdc_year"
FIELD_PV_COST_SOL = "PVCostIntensity_SOL_USD_per_Wdc"
FIELD_PV_COST_SE = "PVCostIntensity_SE_USD_per_Wdc"
FIELD_EA_COST_SOL = "EquivalentAnnualCostIntensity_SOL_USD_per_Wdc_year"
FIELD_EA_COST_SE = "EquivalentAnnualCostIntensity_SE_USD_per_Wdc_year"
FIELD_PV_ENERGY_SOL = "PVEnergyIntensity_SOL_kWh_AC_per_Wdc"
FIELD_PV_ENERGY_SE = "PVEnergyIntensity_SE_kWh_AC_per_Wdc"
FIELD_EA_ENERGY_SOL = "EquivalentAnnualEnergyIntensity_SOL_kWh_AC_per_Wdc_year"
FIELD_EA_ENERGY_SE = "EquivalentAnnualEnergyIntensity_SE_kWh_AC_per_Wdc_year"
FIELD_LCOE_SOL = "LifecycleLCOE_SOL_USD_per_kWh_AC"
FIELD_LCOE_SE = "LifecycleLCOE_SE_USD_per_kWh_AC"
FIELD_DELTA_COST = "DeltaLifecycleCostPerWdc_se_minus_sol_USD_per_Wdc"
FIELD_DELTA_ENERGY = (
    "DeltaLifecycleEnergyPerWdc_se_minus_sol_kWh_AC_per_Wdc"
)
FIELD_DELTA_EA_COST = (
    "DeltaEquivalentAnnualCostPerWdcYear_se_minus_sol_USD_per_Wdc_year"
)
FIELD_DELTA_EA_ENERGY = (
    "DeltaEquivalentAnnualEnergyPerWdcYear_se_minus_sol_kWh_AC_per_Wdc_year"
)
FIELD_LCOO = "AllInLCOO_se_minus_sol_USD_per_kWh_AC"

APPLIED_FIELD_YEAR1_SOL = "Year1SpecificEnergy_SOL_kWh_AC_per_applied_W_year"
APPLIED_FIELD_YEAR1_SE = "Year1SpecificEnergy_SE_kWh_AC_per_applied_W_year"
APPLIED_FIELD_YEAR1_DELTA = (
    "Year1DeltaSpecificEnergy_se_minus_sol_kWh_AC_per_applied_W_year"
)
APPLIED_FIELD_PV_COST_SOL = "PVCostIntensity_SOL_USD_per_applied_W"
APPLIED_FIELD_PV_COST_SE = "PVCostIntensity_SE_USD_per_applied_W"
APPLIED_FIELD_EA_COST_SOL = (
    "EquivalentAnnualCostIntensity_SOL_USD_per_applied_W_year"
)
APPLIED_FIELD_EA_COST_SE = (
    "EquivalentAnnualCostIntensity_SE_USD_per_applied_W_year"
)
APPLIED_FIELD_PV_ENERGY_SOL = "PVEnergyIntensity_SOL_kWh_AC_per_applied_W"
APPLIED_FIELD_PV_ENERGY_SE = "PVEnergyIntensity_SE_kWh_AC_per_applied_W"
APPLIED_FIELD_EA_ENERGY_SOL = (
    "EquivalentAnnualEnergyIntensity_SOL_kWh_AC_per_applied_W_year"
)
APPLIED_FIELD_EA_ENERGY_SE = (
    "EquivalentAnnualEnergyIntensity_SE_kWh_AC_per_applied_W_year"
)
APPLIED_FIELD_DELTA_COST = (
    "DeltaLifecycleCostPerAppliedW_se_minus_sol_USD_per_applied_W"
)
APPLIED_FIELD_DELTA_ENERGY = (
    "DeltaLifecycleEnergyPerAppliedW_se_minus_sol_kWh_AC_per_applied_W"
)
APPLIED_FIELD_DELTA_EA_COST = (
    "DeltaEquivalentAnnualCostPerAppliedWYear_se_minus_sol_USD_per_applied_W_year"
)
APPLIED_FIELD_DELTA_EA_ENERGY = (
    "DeltaEquivalentAnnualEnergyPerAppliedWYear_se_minus_sol_kWh_AC_per_applied_W_year"
)

COMMERCIAL_FIELD_TARGET_CAPACITY = "CommercialTargetCapacity_W"
COMMERCIAL_FIELD_YEAR1_DELTA_ENERGY = (
    "CommercialYear1DeltaEnergy_se_minus_sol_kWh_AC"
)
COMMERCIAL_FIELD_LIFECYCLE_DELTA_ENERGY = (
    "CommercialLifecycleDeltaEnergy_se_minus_sol_kWh_AC"
)
COMMERCIAL_FIELD_EA_DELTA_ENERGY = (
    "CommercialEquivalentAnnualDeltaEnergy_se_minus_sol_kWh_AC_per_year"
)
COMMERCIAL_FIELD_LIFECYCLE_MARGINAL_COST = (
    "CommercialLifecycleMarginalCostDelta_se_minus_sol_USD"
)
COMMERCIAL_FIELD_EA_MARGINAL_COST = (
    "CommercialEquivalentAnnualMarginalCostDelta_se_minus_sol_USD_per_year"
)
COMMERCIAL_FIELD_MARGINAL_LCOO = (
    "CommercialMarginalLCOO_se_minus_sol_USD_per_kWh_AC"
)
COMMERCIAL_FIELD_MARGINAL_LCOO_REASON = (
    "commercial_marginal_lcoo_unavailable_reason"
)
COMMERCIAL_ZERO_ENERGY_REASON = "zero_commercial_lifecycle_delta_energy"

COMMERCIAL_STANDALONE_FIELD_TARGET_CAPACITY = (
    "CommercialSolarEdgeTargetCapacity_W"
)
COMMERCIAL_STANDALONE_FIELD_CAPACITY_SCALE_FACTOR = (
    "CommercialSolarEdgeCapacityScaleFactor_target_W_per_source_W"
)
COMMERCIAL_STANDALONE_FIELD_YEAR1_ENERGY = (
    "CommercialSolarEdgeYear1Energy_kWh_AC"
)
COMMERCIAL_STANDALONE_FIELD_LIFECYCLE_ENERGY = (
    "CommercialSolarEdgeLifecycleEnergy_kWh_AC"
)
COMMERCIAL_STANDALONE_FIELD_EA_ENERGY = (
    "CommercialSolarEdgeEquivalentAnnualEnergy_kWh_AC_per_year"
)
COMMERCIAL_STANDALONE_FIELD_INITIAL_COST = (
    "CommercialSolarEdgeInitialCost_USD"
)
COMMERCIAL_STANDALONE_FIELD_RECURRING_PV_COST = (
    "CommercialSolarEdgeRecurringLifecycleCost_USD"
)
COMMERCIAL_STANDALONE_FIELD_SCHEDULED_PV_COST = (
    "CommercialSolarEdgeScheduledLifecycleCost_USD"
)
COMMERCIAL_STANDALONE_FIELD_LIFECYCLE_COST = (
    "CommercialSolarEdgeLifecycleCost_USD"
)
COMMERCIAL_STANDALONE_FIELD_EA_COST = (
    "CommercialSolarEdgeEquivalentAnnualCost_USD_per_year"
)
COMMERCIAL_STANDALONE_FIELD_LCOE = (
    "CommercialSolarEdgeLifecycleLCOE_USD_per_kWh_AC"
)

COMMERCIAL_PAIRED_SOLECTRIA_FIELD_TARGET_CAPACITY = (
    "CommercialSolectriaTargetCapacity_W"
)
COMMERCIAL_PAIRED_SOLECTRIA_FIELD_CAPACITY_SCALE_FACTOR = (
    "CommercialSolectriaCapacityScaleFactor_target_W_per_source_W"
)
COMMERCIAL_PAIRED_SOLECTRIA_FIELD_YEAR1_ENERGY = (
    "CommercialSolectriaYear1Energy_kWh_AC"
)
COMMERCIAL_PAIRED_SOLECTRIA_FIELD_LIFECYCLE_ENERGY = (
    "CommercialSolectriaLifecycleEnergy_kWh_AC"
)
COMMERCIAL_PAIRED_SOLECTRIA_FIELD_EA_ENERGY = (
    "CommercialSolectriaEquivalentAnnualEnergy_kWh_AC_per_year"
)
COMMERCIAL_PAIRED_SOLECTRIA_FIELD_INITIAL_COST = (
    "CommercialSolectriaInitialCost_USD"
)
COMMERCIAL_PAIRED_SOLECTRIA_FIELD_RECURRING_PV_COST = (
    "CommercialSolectriaRecurringLifecycleCost_USD"
)
COMMERCIAL_PAIRED_SOLECTRIA_FIELD_SCHEDULED_PV_COST = (
    "CommercialSolectriaScheduledLifecycleCost_USD"
)
COMMERCIAL_PAIRED_SOLECTRIA_FIELD_LIFECYCLE_COST = (
    "CommercialSolectriaLifecycleCost_USD"
)
COMMERCIAL_PAIRED_SOLECTRIA_FIELD_EA_COST = (
    "CommercialSolectriaEquivalentAnnualCost_USD_per_year"
)
COMMERCIAL_PAIRED_SOLECTRIA_FIELD_LCOE = (
    "CommercialSolectriaLifecycleLCOE_USD_per_kWh_AC"
)
COMMERCIAL_PAIRED_FIELD_LCOE_DELTA = (
    "CommercialLifecycleLCOEDelta_se_minus_sol_USD_per_kWh_AC"
)


@dataclass(frozen=True)
class _MetricFields:
    year1_sol: str
    year1_se: str
    year1_delta: str
    pv_cost_sol: str
    pv_cost_se: str
    ea_cost_sol: str
    ea_cost_se: str
    pv_energy_sol: str
    pv_energy_se: str
    ea_energy_sol: str
    ea_energy_se: str
    lcoe_sol: str
    lcoe_se: str
    delta_cost: str
    delta_energy: str
    delta_ea_cost: str
    delta_ea_energy: str
    lcoo: str


LEGACY_METRIC_FIELDS = _MetricFields(
    FIELD_YEAR1_SOL,
    FIELD_YEAR1_SE,
    FIELD_YEAR1_DELTA,
    FIELD_PV_COST_SOL,
    FIELD_PV_COST_SE,
    FIELD_EA_COST_SOL,
    FIELD_EA_COST_SE,
    FIELD_PV_ENERGY_SOL,
    FIELD_PV_ENERGY_SE,
    FIELD_EA_ENERGY_SOL,
    FIELD_EA_ENERGY_SE,
    FIELD_LCOE_SOL,
    FIELD_LCOE_SE,
    FIELD_DELTA_COST,
    FIELD_DELTA_ENERGY,
    FIELD_DELTA_EA_COST,
    FIELD_DELTA_EA_ENERGY,
    FIELD_LCOO,
)
APPLIED_METRIC_FIELDS = _MetricFields(
    APPLIED_FIELD_YEAR1_SOL,
    APPLIED_FIELD_YEAR1_SE,
    APPLIED_FIELD_YEAR1_DELTA,
    APPLIED_FIELD_PV_COST_SOL,
    APPLIED_FIELD_PV_COST_SE,
    APPLIED_FIELD_EA_COST_SOL,
    APPLIED_FIELD_EA_COST_SE,
    APPLIED_FIELD_PV_ENERGY_SOL,
    APPLIED_FIELD_PV_ENERGY_SE,
    APPLIED_FIELD_EA_ENERGY_SOL,
    APPLIED_FIELD_EA_ENERGY_SE,
    FIELD_LCOE_SOL,
    FIELD_LCOE_SE,
    APPLIED_FIELD_DELTA_COST,
    APPLIED_FIELD_DELTA_ENERGY,
    APPLIED_FIELD_DELTA_EA_COST,
    APPLIED_FIELD_DELTA_EA_ENERGY,
    FIELD_LCOO,
)


class TechnoeconomicValidationError(ValueError):
    """Raised when a request violates the approved calculation contract."""


class TechnoeconomicInvariantError(RuntimeError):
    """Raised when validated inputs produce an impossible numerical state."""


@dataclass(frozen=True)
class DistributionSpec:
    """One version-1 scalar input distribution."""

    input_id: str
    family: DistributionFamily
    value: float | None = None
    low: float | None = None
    high: float | None = None
    mode: float | None = None
    mean: float | None = None
    sd: float | None = None


@dataclass(frozen=True)
class CapacitySpec:
    """Frozen module DC-STC capacity for one modeled system."""

    system: SystemName
    module_model: str
    module_stc_wdc: float
    strings: int
    bays_per_string: int
    modules_per_bay: int
    module_count: int
    installed_wdc: float
    physics_version: str
    physics_fingerprint: str


@dataclass(frozen=True)
class AppliedCapacitySpec:
    """Frozen normalization capacity for one SolarTAC system.

    ``applied_capacity_w`` is expressed in watts even when its rating basis is the
    Annual Simulation's AC operating limit.  Keeping the rating basis explicit
    prevents an AC limit from being mislabeled as module DC nameplate capacity.
    """

    system: SystemName
    applied_capacity_w: float
    rating_basis: AppliedCapacityRatingBasis


@dataclass(frozen=True)
class PairedEnergyRow:
    """One eligible paired Annual Simulation weather-year row."""

    year: int
    sol_predicted_kwh_ac: float
    se_predicted_kwh_ac: float
    provenance: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CostLineSpec:
    """A source-normalized cost line consumed by the pure kernel.

    A sampled value is multiplied by each system multiplier to obtain USD/Wdc for
    initial types or USD/Wdc-year for recurring types.  Phase 2 will derive and
    freeze these multipliers from source units, quantities, and capacity evidence.
    """

    input_id: str
    label: str
    basis: AnalysisBasis
    ownership: CostOwnership
    cost_type: CostType
    distribution: DistributionSpec
    solectria_multiplier_to_intensity: float
    solaredge_multiplier_to_intensity: float
    coverage_ids: tuple[str, ...]
    solectria_treatment_key: str = SUPPORTED_COST_TREATMENT
    solaredge_treatment_key: str = SUPPORTED_COST_TREATMENT


@dataclass(frozen=True)
class TransferSpec:
    """Explicit baseline-plus-incremental commercial energy transfer."""

    baseline: DistributionSpec
    incremental: DistributionSpec
    mechanism_status: str = "approved"


@dataclass(frozen=True)
class CommercialScalingSpec:
    """Direct source-specific scaling and separate commercial marginal cost.

    The target and both frozen source capacities use the same explicit rating
    basis.  ``marginal_cost_difference`` is signed SolarEdge minus Solectria and
    may therefore have negative, zero, or positive support.
    """

    target_capacity_w: float
    target_rating_basis: AppliedCapacityRatingBasis
    marginal_cost_difference: DistributionSpec
    marginal_cost_timing: MarginalCostTiming
    transfer_method: CommercialScalingTransferMethod = (
        COMMERCIAL_SCALING_TRANSFER_METHOD
    )


@dataclass(frozen=True)
class CommercialCostLineSpec:
    """One standalone commercial SolarEdge cost-intensity input.

    Initial and scheduled distributions are in constant-real USD per target W.
    Annual distributions are in constant-real USD per target W-year.  A scheduled
    draw applies at every listed year end.
    """

    input_id: str
    label: str
    cost_category: CommercialCostCategory
    coverage_ids: tuple[str, ...]
    timing: CommercialCostTiming
    distribution: DistributionSpec
    constant_dollar_cost_year: int
    occurrence_years: tuple[int, ...] = ()


@dataclass(frozen=True)
class StandaloneCommercialSpec:
    """Standalone commercial SolarEdge energy scaling and lifecycle cost stack."""

    target_capacity_w: float
    target_rating_basis: AppliedCapacityRatingBasis
    cost_lines: tuple[CommercialCostLineSpec, ...]
    transfer_method: CommercialScalingTransferMethod = (
        COMMERCIAL_SCALING_TRANSFER_METHOD
    )


@dataclass(frozen=True)
class PairedCommercialSystemSpec:
    """One complete commercial cost stack tied to one frozen system energy."""

    technology: SystemName
    cost_lines: tuple[CommercialCostLineSpec, ...]


@dataclass(frozen=True)
class PairedCommercialSpec:
    """Paired standalone commercial LCOEs at one common target capacity."""

    target_capacity_w: float
    target_rating_basis: AppliedCapacityRatingBasis
    systems: tuple[PairedCommercialSystemSpec, PairedCommercialSystemSpec]
    transfer_method: CommercialScalingTransferMethod = (
        COMMERCIAL_SCALING_TRANSFER_METHOD
    )


@dataclass(frozen=True)
class TechnoeconomicRequest:
    """Canonical semantic input to the Phase-1 pure kernel."""

    basis: AnalysisBasis
    n: int
    seed: int
    project_life_years: int
    capacities: tuple[CapacitySpec, CapacitySpec]
    paired_energy_rows: tuple[PairedEnergyRow, ...]
    cost_lines: tuple[CostLineSpec, ...]
    discount_rate: DistributionSpec
    shared_degradation: DistributionSpec
    applied_capacities: tuple[AppliedCapacitySpec, AppliedCapacitySpec] | None = None
    transfer: TransferSpec | None = None
    commercial_reference_wdc: float | None = None
    commercial_scaling: CommercialScalingSpec | None = None
    cost_stack_completeness: Literal["full_system"] = "full_system"
    calculation_contract_version: str = LEGACY_CALCULATION_CONTRACT_VERSION
    sampling_version: str = SAMPLING_VERSION
    standalone_commercial: StandaloneCommercialSpec | None = None
    constant_dollar_cost_year: int | None = None
    paired_commercial: PairedCommercialSpec | None = None


@dataclass(frozen=True)
class TechnoeconomicResult:
    """Pure calculation output; later phases persist and export this structure."""

    realization_table: Mapping[str, np.ndarray]
    sampled_inputs: Mapping[str, np.ndarray]
    common_cost_audit: tuple[Mapping[str, Any], ...]
    summaries: Mapping[str, Any]
    per_weather_year: tuple[Mapping[str, Any], ...]
    sensitivity: Mapping[str, Any]
    convergence: Mapping[str, Any]
    provenance: Mapping[str, Any]
    energy_available: bool


def canonical_request_payload(request: TechnoeconomicRequest) -> dict[str, Any]:
    """Return the stable dataclass payload used for kernel request hashing.

    ``applied_capacities`` did not exist in the version-1 dataclass, and
    ``commercial_scaling`` did not exist before version 3, and
    ``standalone_commercial`` did not exist before version 4, and
    ``paired_commercial`` did not exist before version 5.  Omitting those
    defaulted fields from the older literal contracts preserves their exact
    historical hashes and immutable retry comparisons.
    """

    if not isinstance(request, TechnoeconomicRequest):
        raise TechnoeconomicValidationError("Request must be a TechnoeconomicRequest.")
    payload = asdict(request)
    if request.calculation_contract_version == LEGACY_CALCULATION_CONTRACT_VERSION:
        payload.pop("applied_capacities", None)
    if (
        request.calculation_contract_version
        != COMMERCIAL_SCALING_CALCULATION_CONTRACT_VERSION
    ):
        payload.pop("commercial_scaling", None)
    if request.calculation_contract_version != STANDALONE_COMMERCIAL_CALCULATION_CONTRACT_VERSION:
        payload.pop("standalone_commercial", None)
    if request.calculation_contract_version not in {
        STANDALONE_COMMERCIAL_CALCULATION_CONTRACT_VERSION,
        PAIRED_COMMERCIAL_CALCULATION_CONTRACT_VERSION,
    }:
        payload.pop("constant_dollar_cost_year", None)
    if request.calculation_contract_version != PAIRED_COMMERCIAL_CALCULATION_CONTRACT_VERSION:
        payload.pop("paired_commercial", None)
    return payload


def _is_int(value: Any) -> bool:
    return isinstance(value, (int, np.integer)) and not isinstance(value, (bool, np.bool_))


def _finite_float(value: Any, label: str) -> float:
    if isinstance(value, (bool, np.bool_)):
        raise TechnoeconomicValidationError(f"{label} must be a finite number.")
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise TechnoeconomicValidationError(
            f"{label} must be a finite number."
        ) from exc
    if not math.isfinite(result):
        raise TechnoeconomicValidationError(f"{label} must be finite.")
    return result


def _validate_stable_id(value: Any, label: str = "input ID") -> str:
    if not isinstance(value, str) or not STABLE_ID_RE.fullmatch(value):
        raise TechnoeconomicValidationError(
            f"{label} must match [a-z0-9._:-]+ using ASCII characters."
        )
    if "\0" in value:
        raise TechnoeconomicValidationError(f"{label} must not contain NUL.")
    return value


def _probe_pcg64dxsm_stream() -> tuple[int | float, ...]:
    """Draw from the exact SeedSequence/PCG64DXSM path the LHS sampler uses."""

    words: list[int] = []
    for entropy in ([0] * 8, list(range(1, 9))):
        generator = np.random.PCG64DXSM(np.random.SeedSequence(entropy=entropy))
        words.extend(int(generator.random_raw()) for _ in range(4))
    return tuple(words)


def _probe_truncnorm_ppf() -> tuple[int | float, ...]:
    """Exercise the far-tail inversion binary64 CDF subtraction cannot perform.

    The 10-11 and 37-38 standard-deviation intervals are exactly the cases
    Section 5.6 of the calculation contract relies on: an ordinary
    ``Phi(b) - Phi(a)`` collapses both to zero probability, so a regression here
    would silently turn a legitimate bounded-normal input into a degenerate or
    nonfinite draw rather than raising.
    """

    cases = (
        (-1.0, 1.0, 0.25),
        (-3.0, 3.0, 0.975),
        (-0.5, 4.0, 1e-9),
        (10.0, 11.0, 0.5),
        (10.0, 11.0, 1e-9),
        (10.0, 11.0, 1.0 - 1e-9),
        (37.0, 38.0, 0.5),
    )
    return tuple(
        float(truncnorm.ppf(probability, low, high))
        for low, high, probability in cases
    )


def _probe_type7_quantile() -> tuple[int | float, ...]:
    """Pin the Hyndman-Fan type-7 interpolation behind every reported Pxx."""

    population = np.asarray(
        [0.1, 2.5, 3.7, 4.2, 9.9, 11.3, 15.0, -2.25, 0.0, 7.5],
        dtype=np.float64,
    )
    return tuple(
        float(value)
        for value in np.quantile(population, [0.05, 0.5, 0.95], method="linear")
    )


def _probe_binary64_growth() -> tuple[int | float, ...]:
    """Pin log1p/expm1, which carry the annuity and lifecycle-energy factors."""

    log_growth = float(np.log1p(0.07))
    log_ratio = float(np.log1p(-0.005) - np.log1p(0.07))
    return (
        log_growth,
        float(np.expm1(-25.0 * log_growth)),
        log_ratio,
        float(np.expm1(25.0 * log_ratio)),
    )


_NUMERICAL_PROBES: dict[str, Callable[[], tuple[int | float, ...]]] = {
    "binary64_growth": _probe_binary64_growth,
    "pcg64dxsm_stream": _probe_pcg64dxsm_stream,
    "truncnorm_ppf": _probe_truncnorm_ppf,
    "type7_quantile": _probe_type7_quantile,
}

# The gate compares probe values to this many significant decimal digits.
# Binary64 carries roughly 16, so 12 absorbs last-bit refinement between
# releases while still catching every failure mode the contract cares about --
# a collapsed far-tail interval, a clamped bound, a changed quantile rule, and
# a reseeded bit generator all move far more than one part in 1e12.
NUMERICAL_PROBE_SIGNIFICANT_DIGITS = 12


def _serialize_probe(values: Sequence[int | float], *, exact: bool) -> str:
    parts: list[str] = []
    for value in values:
        if isinstance(value, int) and not isinstance(value, bool):
            parts.append(str(value))
            continue
        # ``+ 0.0`` normalizes -0.0 so a sign-only artifact cannot trip the gate.
        number = float(value) + 0.0
        parts.append(
            number.hex()
            if exact
            else f"{number:.{NUMERICAL_PROBE_SIGNIFICANT_DIGITS - 1}e}"
        )
    return "|".join(parts)


def _probe_digest(name: str, *, exact: bool) -> str:
    return sha256(
        _serialize_probe(_NUMERICAL_PROBES[name](), exact=exact).encode("ascii")
    ).hexdigest()


# Tolerance-scoped digests under the authored contract versions.  These are the
# gate: a runtime that reproduces all four is permitted to run.  Confirmed
# identical on CPython 3.11 / NumPy 2.4.6 / SciPy 1.17.1 and CPython 3.13 /
# NumPy 2.5.0 / SciPy 1.18.0.
#
# Deliberately not probed: np.linalg.matrix_rank and np.linalg.lstsq reach
# LAPACK, so their trailing bits track the local BLAS build rather than the
# NumPy release.  Gating on them would fail closed on an innocent BLAS swap
# while proving nothing about the release.  Those paths already guard
# themselves -- stepwise_rank_regression treats a singular design as an
# exclusion, not as a silent result.
NUMERICAL_PROBE_DIGESTS: dict[str, str] = {
    "binary64_growth": "14cc27d71cbbb17ac1369c382a7fd0413aa14c3542750f6e1516624bd764e16b",
    "pcg64dxsm_stream": "6916080426e3ee51b5c81d1856ea1649e0570b0eec5bd7f614b6a74d6cdb49c9",
    "truncnorm_ppf": "77516b8d1730543e54cb8b8449e6cb274ab5a514777b4da1a37266cacf246839",
    "type7_quantile": "14c57ad434b4fa3c4138c8f6d933b325f5edf32fd92d7f38835292dba6979b67",
}

# Bit-exact digest over every probe under the authored contract versions.  This
# is NOT a gate.  It answers a different and narrower question than the one
# above -- "would this runtime reproduce the reference realization tables bit
# for bit?" -- and is recorded in provenance so a reviewer comparing two
# completed jobs can tell at a glance whether they are bit-comparable or merely
# both within contract tolerance.  SciPy 1.17.1 and 1.18.0 differ here by three
# ULP on one near-bound truncnorm case while agreeing to every digit the
# contract depends on, which is precisely the distinction being drawn.
NUMERICAL_EXACTNESS_DIGEST = (
    "f8949ae833e1a7ccf484a015396084dec1fc183c8eccf3c839aec46824cd3a8d"
)


def numerical_fingerprint() -> dict[str, Any]:
    """Describe this runtime's numerical behaviour for provenance and audit."""

    exactness = sha256(
        "|".join(
            _serialize_probe(_NUMERICAL_PROBES[name](), exact=True)
            for name in sorted(_NUMERICAL_PROBES)
        ).encode("ascii")
    ).hexdigest()
    return {
        "contract_version": NUMERICAL_CONTRACT_VERSION,
        "significant_digits": NUMERICAL_PROBE_SIGNIFICANT_DIGITS,
        "probe_digests": {
            name: _probe_digest(name, exact=False)
            for name in sorted(_NUMERICAL_PROBES)
        },
        "exactness_digest": exactness,
        "reference_exactness_digest": NUMERICAL_EXACTNESS_DIGEST,
        "bit_identical_to_reference": exactness == NUMERICAL_EXACTNESS_DIGEST,
        "reference_numpy_version": CONTRACT_NUMPY_VERSION,
        "reference_scipy_version": CONTRACT_SCIPY_VERSION,
    }


def validate_runtime_versions() -> None:
    """Fail closed if the runtime's numerical behaviour left the contract.

    Version 1 originally compared ``numpy.__version__`` and ``scipy.__version__``
    against exact strings.  That gate was simultaneously too strict and too
    weak: it rejected runtimes whose numbers satisfied the contract, and it
    would equally have accepted a same-version rebuild whose behaviour had
    changed underneath it.  This checks the behaviour the contract actually
    depends on; the version strings remain in provenance.

    The function name is retained because it is called at the top of
    ``generate_lhs``, ``allocate_weather_years``, and ``validate_request``.
    """

    divergent: list[str] = []
    for name in sorted(NUMERICAL_PROBE_DIGESTS):
        try:
            observed = _probe_digest(name, exact=False)
        except Exception as exc:  # A probe that cannot even run is a failed gate.
            raise TechnoeconomicValidationError(
                f"{NUMERICAL_CONTRACT_VERSION} could not evaluate the {name!r} "
                f"numerical probe on NumPy {np.__version__} / SciPy "
                f"{scipy.__version__}: {exc}"
            ) from exc
        if observed != NUMERICAL_PROBE_DIGESTS[name]:
            divergent.append(name)
    if divergent:
        raise TechnoeconomicValidationError(
            f"{NUMERICAL_CONTRACT_VERSION} numerical probes diverged on NumPy "
            f"{np.__version__} / SciPy {scipy.__version__}: "
            f"{', '.join(divergent)}. The contract was authored against NumPy "
            f"{CONTRACT_NUMPY_VERSION} / SciPy {CONTRACT_SCIPY_VERSION}. "
            "Seeded reproducibility cannot be promised until the divergence is "
            "reviewed and the contract digests are re-approved."
        )


def _provided_distribution_fields(spec: DistributionSpec) -> set[str]:
    return {
        name
        for name in ("value", "low", "high", "mode", "mean", "sd")
        if getattr(spec, name) is not None
    }


def validate_distribution(
    spec: DistributionSpec,
    role: DistributionRole = "generic",
) -> DistributionSpec:
    """Validate and canonicalize one distribution and its role-wide support."""

    if not isinstance(spec, DistributionSpec):
        raise TechnoeconomicValidationError("Distribution must be a DistributionSpec.")
    _validate_stable_id(spec.input_id)
    if role not in {
        "generic",
        "cost",
        "discount_rate",
        "degradation",
        "transfer_baseline",
        "transfer_incremental",
    }:
        raise TechnoeconomicValidationError(f"Unsupported distribution role: {role!r}.")

    family = spec.family
    supplied = _provided_distribution_fields(spec)
    if family == "fixed":
        if supplied != {"value"}:
            raise TechnoeconomicValidationError(
                f"Fixed distribution {spec.input_id!r} requires only value."
            )
        normalized = DistributionSpec(
            input_id=spec.input_id,
            family="fixed",
            value=_finite_float(spec.value, f"{spec.input_id}.value"),
        )
    elif family == "uniform":
        if supplied != {"low", "high"}:
            raise TechnoeconomicValidationError(
                f"Uniform distribution {spec.input_id!r} requires only low and high."
            )
        low = _finite_float(spec.low, f"{spec.input_id}.low")
        high = _finite_float(spec.high, f"{spec.input_id}.high")
        if low > high:
            raise TechnoeconomicValidationError(
                f"Uniform distribution {spec.input_id!r} requires low <= high."
            )
        if low < high and math.nextafter(low, high) >= high:
            raise TechnoeconomicValidationError(
                f"Uniform distribution {spec.input_id!r} has no representable binary64 interior."
            )
        normalized = (
            DistributionSpec(spec.input_id, "fixed", value=low)
            if low == high
            else DistributionSpec(spec.input_id, "uniform", low=low, high=high)
        )
    elif family == "triangular":
        if supplied != {"low", "mode", "high"}:
            raise TechnoeconomicValidationError(
                f"Triangular distribution {spec.input_id!r} requires only low, mode, and high."
            )
        low = _finite_float(spec.low, f"{spec.input_id}.low")
        mode = _finite_float(spec.mode, f"{spec.input_id}.mode")
        high = _finite_float(spec.high, f"{spec.input_id}.high")
        if not low <= mode <= high:
            raise TechnoeconomicValidationError(
                f"Triangular distribution {spec.input_id!r} requires low <= mode <= high."
            )
        if low < high and math.nextafter(low, high) >= high:
            raise TechnoeconomicValidationError(
                f"Triangular distribution {spec.input_id!r} has no representable binary64 interior."
            )
        normalized = (
            DistributionSpec(spec.input_id, "fixed", value=low)
            if low == high
            else DistributionSpec(
                spec.input_id,
                "triangular",
                low=low,
                mode=mode,
                high=high,
            )
        )
    elif family == "bounded_normal":
        if supplied != {"low", "high", "mean", "sd"}:
            raise TechnoeconomicValidationError(
                f"Bounded-normal distribution {spec.input_id!r} requires only low, high, mean, and sd."
            )
        low = _finite_float(spec.low, f"{spec.input_id}.low")
        high = _finite_float(spec.high, f"{spec.input_id}.high")
        mean = _finite_float(spec.mean, f"{spec.input_id}.mean")
        sd = _finite_float(spec.sd, f"{spec.input_id}.sd")
        if not low < high:
            raise TechnoeconomicValidationError(
                f"Bounded-normal distribution {spec.input_id!r} requires low < high."
            )
        if sd <= 0:
            raise TechnoeconomicValidationError(
                f"Bounded-normal distribution {spec.input_id!r} requires sd > 0."
            )
        if math.nextafter(low, high) >= high:
            raise TechnoeconomicValidationError(
                f"Bounded-normal distribution {spec.input_id!r} has no representable binary64 interior."
            )
        a = (low - mean) / sd
        b = (high - mean) / sd
        if not math.isfinite(a) or not math.isfinite(b) or not a < b:
            raise TechnoeconomicValidationError(
                f"Bounded-normal distribution {spec.input_id!r} has an unrepresentable truncated interval."
            )
        probe = float(truncnorm.ppf(0.5, a, b, loc=mean, scale=sd))
        if not math.isfinite(probe):
            raise TechnoeconomicValidationError(
                f"Bounded-normal distribution {spec.input_id!r} has an empty numerical probability interval."
            )
        normalized = DistributionSpec(
            spec.input_id,
            "bounded_normal",
            low=low,
            high=high,
            mean=mean,
            sd=sd,
        )
    else:
        raise TechnoeconomicValidationError(
            f"Unsupported distribution family for {spec.input_id!r}: {family!r}."
        )

    support_low, support_high = distribution_support(normalized)
    if role == "cost" and support_low < 0:
        raise TechnoeconomicValidationError(
            f"Cost distribution {spec.input_id!r} must have nonnegative support."
        )
    if role == "discount_rate" and support_low <= -1:
        raise TechnoeconomicValidationError(
            f"Discount-rate distribution {spec.input_id!r} must have support greater than -1."
        )
    if role == "degradation" and (support_low < 0 or support_high >= 1):
        raise TechnoeconomicValidationError(
            f"Degradation distribution {spec.input_id!r} must satisfy 0 <= g < 1 across its support."
        )
    if role == "transfer_baseline" and support_low <= 0:
        raise TechnoeconomicValidationError(
            f"Baseline-transfer distribution {spec.input_id!r} must have strictly positive support."
        )
    if role == "transfer_incremental" and support_low < 0:
        raise TechnoeconomicValidationError(
            f"Incremental-transfer distribution {spec.input_id!r} must have nonnegative support."
        )
    return normalized


def distribution_support(spec: DistributionSpec) -> tuple[float, float]:
    """Return the finite closed support of a validated distribution."""

    if spec.family == "fixed":
        value = _finite_float(spec.value, f"{spec.input_id}.value")
        return value, value
    if spec.family in {"uniform", "triangular", "bounded_normal"}:
        return (
            _finite_float(spec.low, f"{spec.input_id}.low"),
            _finite_float(spec.high, f"{spec.input_id}.high"),
        )
    raise TechnoeconomicValidationError(
        f"Unsupported distribution family for {spec.input_id!r}: {spec.family!r}."
    )


def inverse_cdf(spec: DistributionSpec, probabilities: Sequence[float] | np.ndarray) -> np.ndarray:
    """Transform open-interval probabilities through a version-1 inverse CDF."""

    normalized = validate_distribution(spec)
    probabilities_array = np.asarray(probabilities, dtype=np.float64)
    if not np.isfinite(probabilities_array).all() or np.any(probabilities_array <= 0) or np.any(probabilities_array >= 1):
        raise TechnoeconomicValidationError(
            "Inverse-CDF probabilities must be finite and strictly inside (0, 1)."
        )
    if normalized.family == "fixed":
        return np.full(probabilities_array.shape, normalized.value, dtype=np.float64)

    low = float(normalized.low)
    high = float(normalized.high)
    if normalized.family == "uniform":
        # Convex form avoids overflowing ``high - low`` on valid signed supports.
        result = (1.0 - probabilities_array) * low + probabilities_array * high
    elif normalized.family == "triangular":
        mode = float(normalized.mode)
        low_decimal = Decimal(str(low))
        high_decimal = Decimal(str(high))
        mode_decimal = Decimal(str(mode))
        split = float(
            (mode_decimal - low_decimal) / (high_decimal - low_decimal)
        )
        lower_weight = np.sqrt(probabilities_array * split)
        upper_low_weight = np.sqrt(
            (1.0 - probabilities_array) * (1.0 - split)
        )
        result = np.where(
            probabilities_array < split,
            (1.0 - lower_weight) * low + lower_weight * high,
            upper_low_weight * low + (1.0 - upper_low_weight) * high,
        )
    else:
        mean = float(normalized.mean)
        sd = float(normalized.sd)
        a = (low - mean) / sd
        b = (high - mean) / sd
        result = np.asarray(
            truncnorm.ppf(probabilities_array, a, b, loc=mean, scale=sd),
            dtype=np.float64,
        )

    lower_interior = math.nextafter(low, high)
    upper_interior = math.nextafter(high, low)
    result = np.where(result <= low, lower_interior, result)
    result = np.where(result >= high, upper_interior, result)
    if (
        not np.isfinite(result).all()
        or np.any(result <= low)
        or np.any(result >= high)
    ):
        raise TechnoeconomicInvariantError(
            f"Inverse CDF for {normalized.input_id!r} did not produce finite interior values."
        )
    return result


def _validate_n_seed(n: Any, seed: Any) -> tuple[int, int]:
    if not _is_int(n) or not 1 <= int(n) <= MAX_REALIZATIONS:
        raise TechnoeconomicValidationError(
            f"n must be an integer from 1 through {MAX_REALIZATIONS}."
        )
    if not _is_int(seed) or not 0 <= int(seed) < UINT64_MODULUS:
        raise TechnoeconomicValidationError(
            "seed must be an integer from 0 through 2^64-1."
        )
    return int(n), int(seed)


def _substream(seed: int, purpose: str, stable_id: str) -> np.random.PCG64DXSM:
    if not isinstance(purpose, str) or not purpose or "\0" in purpose:
        raise TechnoeconomicValidationError(
            "RNG purpose must be a nonempty string without NUL."
        )
    _validate_stable_id(stable_id, "RNG stable ID")
    domain = (
        RNG_DOMAIN
        + seed.to_bytes(8, "big", signed=False)
        + b"\0"
        + purpose.encode("utf-8")
        + b"\0"
        + stable_id.encode("utf-8")
    )
    digest = sha256(domain).digest()
    entropy = [int.from_bytes(digest[offset : offset + 4], "big") for offset in range(0, 32, 4)]
    return np.random.PCG64DXSM(np.random.SeedSequence(entropy=entropy))


def _open_interval_jitter(bit_generator: Any) -> float:
    while True:
        word = int(bit_generator.random_raw())
        if not 0 <= word < UINT64_MODULUS:
            raise TechnoeconomicInvariantError("Bit generator returned a non-uint64 word.")
        significand = word >> 11
        if significand != 0:
            return significand / float(1 << 53)


def _random_below(bit_generator: Any, modulus: int) -> int:
    if not _is_int(modulus) or int(modulus) <= 0:
        raise TechnoeconomicValidationError("Permutation modulus must be positive.")
    modulus = int(modulus)
    limit = UINT64_MODULUS - (UINT64_MODULUS % modulus)
    while True:
        word = int(bit_generator.random_raw())
        if not 0 <= word < UINT64_MODULUS:
            raise TechnoeconomicInvariantError("Bit generator returned a non-uint64 word.")
        if word < limit:
            return word % modulus


def _fisher_yates(values: Sequence[Any], bit_generator: Any) -> list[Any]:
    shuffled = list(values)
    for index in range(len(shuffled) - 1, 0, -1):
        swap_index = _random_below(bit_generator, index + 1)
        shuffled[index], shuffled[swap_index] = shuffled[swap_index], shuffled[index]
    return shuffled


def _jittered_strata(n: int, bit_generator: Any) -> np.ndarray:
    result = np.empty(n, dtype=np.float64)
    for stratum in range(n):
        jitter = _open_interval_jitter(bit_generator)
        lower = stratum / n
        upper = (stratum + 1) / n
        value = (stratum + jitter) / n
        if value <= lower:
            value = math.nextafter(lower, upper)
        if value >= upper:
            value = math.nextafter(upper, lower)
        if not lower < value < upper:
            raise TechnoeconomicInvariantError(
                f"No representable interior LHS value for stratum {stratum} of {n}."
            )
        result[stratum] = value
    return result


def generate_lhs(
    n: int,
    seed: int,
    distributions: Sequence[DistributionSpec],
) -> dict[str, np.ndarray]:
    """Generate canonical independent LHS draws, including fixed columns."""

    validate_runtime_versions()
    n, seed = _validate_n_seed(n, seed)
    normalized = [validate_distribution(spec) for spec in distributions]
    identifiers = [spec.input_id for spec in normalized]
    if len(set(identifiers)) != len(identifiers):
        raise TechnoeconomicValidationError("Distribution input IDs must be unique.")
    reserved = RESERVED_INPUT_IDS & set(identifiers)
    if reserved:
        raise TechnoeconomicValidationError(
            f"Input IDs {sorted(reserved)!r} are reserved for weather allocation "
            "or sensitivity source predictors."
        )

    sampled: dict[str, np.ndarray] = {}
    for spec in sorted(normalized, key=lambda item: item.input_id.encode("ascii")):
        if spec.family == "fixed":
            sampled[spec.input_id] = np.full(n, spec.value, dtype=np.float64)
            continue
        jitter_generator = _substream(seed, LHS_JITTER_PURPOSE, spec.input_id)
        permutation_generator = _substream(seed, LHS_PERMUTATION_PURPOSE, spec.input_id)
        probabilities = _jittered_strata(n, jitter_generator)
        permutation = _fisher_yates(range(n), permutation_generator)
        sampled[spec.input_id] = inverse_cdf(spec, probabilities[permutation])
    return sampled


def allocate_weather_years(
    n: int,
    seed: int,
    years: Sequence[int],
) -> np.ndarray:
    """Return a balanced, seeded assignment of paired weather-year IDs."""

    validate_runtime_versions()
    n, seed = _validate_n_seed(n, seed)
    normalized_years: list[int] = []
    for year in years:
        if not _is_int(year):
            raise TechnoeconomicValidationError("Weather years must be integers.")
        normalized_years.append(int(year))
    if not normalized_years:
        raise TechnoeconomicValidationError("At least one weather year is required.")
    if len(set(normalized_years)) != len(normalized_years):
        raise TechnoeconomicValidationError("Weather years must be unique.")
    normalized_years.sort()

    quotient, remainder = divmod(n, len(normalized_years))
    extra_order = _fisher_yates(
        normalized_years,
        _substream(seed, WEATHER_EXTRA_PURPOSE, WEATHER_STABLE_ID),
    )
    extras = set(extra_order[:remainder])
    grouped: list[int] = []
    for year in normalized_years:
        grouped.extend([year] * (quotient + (1 if year in extras else 0)))
    assigned = _fisher_yates(
        grouped,
        _substream(seed, WEATHER_ASSIGNMENT_PURPOSE, WEATHER_STABLE_ID),
    )
    if len(assigned) != n:
        raise TechnoeconomicInvariantError("Balanced weather allocation changed row count.")
    return np.asarray(assigned, dtype=np.int64)


def validate_capacity(spec: CapacitySpec) -> CapacitySpec:
    """Validate a frozen Wdc manifest without consulting mutable model globals."""

    if not isinstance(spec, CapacitySpec):
        raise TechnoeconomicValidationError("Capacity must be a CapacitySpec.")
    if spec.system not in {"solectria", "solaredge"}:
        raise TechnoeconomicValidationError(f"Unsupported capacity system: {spec.system!r}.")
    if not isinstance(spec.module_model, str) or not spec.module_model.strip():
        raise TechnoeconomicValidationError("Capacity module_model must be nonempty.")
    module_stc_wdc = _finite_float(spec.module_stc_wdc, "module_stc_wdc")
    installed_wdc = _finite_float(spec.installed_wdc, "installed_wdc")
    if module_stc_wdc <= 0 or installed_wdc <= 0:
        raise TechnoeconomicValidationError("Capacity power values must be positive.")
    integer_fields = {
        "strings": spec.strings,
        "bays_per_string": spec.bays_per_string,
        "modules_per_bay": spec.modules_per_bay,
        "module_count": spec.module_count,
    }
    for label, value in integer_fields.items():
        if not _is_int(value) or int(value) <= 0:
            raise TechnoeconomicValidationError(
                f"Capacity {label} must be a positive integer."
            )
    topology_count = int(spec.strings) * int(spec.bays_per_string) * int(spec.modules_per_bay)
    if topology_count != int(spec.module_count):
        raise TechnoeconomicValidationError(
            "Capacity topology product must equal module_count."
        )
    try:
        derived_wdc_decimal = Decimal(int(spec.module_count)) * Decimal(
            str(spec.module_stc_wdc)
        )
        installed_wdc_decimal = Decimal(str(spec.installed_wdc))
    except InvalidOperation as exc:
        raise TechnoeconomicValidationError(
            "Capacity values must have canonical decimal representations."
        ) from exc
    if derived_wdc_decimal != installed_wdc_decimal:
        raise TechnoeconomicValidationError(
            "Capacity module_count * module_stc_wdc must equal installed_wdc."
        )
    for label, value in (
        ("physics_version", spec.physics_version),
        ("physics_fingerprint", spec.physics_fingerprint),
    ):
        if not isinstance(value, str) or not value.strip() or "\0" in value:
            raise TechnoeconomicValidationError(f"Capacity {label} must be nonempty and contain no NUL.")
    return replace(
        spec,
        module_stc_wdc=module_stc_wdc,
        installed_wdc=installed_wdc,
        strings=int(spec.strings),
        bays_per_string=int(spec.bays_per_string),
        modules_per_bay=int(spec.modules_per_bay),
        module_count=int(spec.module_count),
        module_model=spec.module_model.strip(),
        physics_version=spec.physics_version.strip(),
        physics_fingerprint=spec.physics_fingerprint.strip(),
    )


def _validate_applied_capacities(
    specs: Sequence[AppliedCapacitySpec],
    capacities: Mapping[SystemName, CapacitySpec],
) -> tuple[AppliedCapacitySpec, AppliedCapacitySpec]:
    """Validate one auditable applied-capacity record per SolarTAC system."""

    normalized: list[AppliedCapacitySpec] = []
    for spec in specs:
        if not isinstance(spec, AppliedCapacitySpec):
            raise TechnoeconomicValidationError(
                "Every applied capacity must be an AppliedCapacitySpec."
            )
        if spec.system not in {"solectria", "solaredge"}:
            raise TechnoeconomicValidationError(
                f"Unsupported applied-capacity system: {spec.system!r}."
            )
        applied_w = _finite_float(
            spec.applied_capacity_w,
            f"{spec.system}.applied_capacity_w",
        )
        if applied_w <= 0:
            raise TechnoeconomicValidationError(
                "Applied capacity values must be strictly positive."
            )
        if spec.rating_basis not in {
            "ac_operating_limit",
            "dc_installed_nameplate",
        }:
            raise TechnoeconomicValidationError(
                f"Unsupported applied-capacity rating basis: {spec.rating_basis!r}."
            )
        normalized.append(replace(spec, applied_capacity_w=applied_w))

    by_system = {spec.system: spec for spec in normalized}
    if len(normalized) != 2 or set(by_system) != {"solectria", "solaredge"}:
        raise TechnoeconomicValidationError(
            "Exactly one Solectria and one SolarEdge applied capacity are required."
        )
    sol = by_system["solectria"]
    se = by_system["solaredge"]
    if sol.rating_basis != se.rating_basis:
        raise TechnoeconomicValidationError(
            "SolarTAC applied capacities must use one shared rating basis."
        )
    if sol.rating_basis == "ac_operating_limit":
        if Decimal(str(sol.applied_capacity_w)) != Decimal(str(se.applied_capacity_w)):
            raise TechnoeconomicValidationError(
                "A SolarTAC AC operating limit must be identical for both systems."
            )
    else:
        for system, spec in (("solectria", sol), ("solaredge", se)):
            if Decimal(str(spec.applied_capacity_w)) != Decimal(
                str(capacities[system].installed_wdc)
            ):
                raise TechnoeconomicValidationError(
                    "A dc_installed_nameplate applied capacity must exactly match "
                    "the frozen installed_wdc manifest."
                )
    return sol, se


def _validate_commercial_scaling(
    spec: CommercialScalingSpec,
    applied_capacities: Sequence[AppliedCapacitySpec],
) -> CommercialScalingSpec:
    """Validate the version-3 direct-capacity scaling contract."""

    if not isinstance(spec, CommercialScalingSpec):
        raise TechnoeconomicValidationError(
            "tea-calculation-v3 requires a CommercialScalingSpec."
        )
    target_capacity_w = _finite_float(
        spec.target_capacity_w,
        "commercial_scaling.target_capacity_w",
    )
    if target_capacity_w <= 0:
        raise TechnoeconomicValidationError(
            "commercial_scaling.target_capacity_w must be strictly positive."
        )
    if spec.target_rating_basis not in {
        "ac_operating_limit",
        "dc_installed_nameplate",
    }:
        raise TechnoeconomicValidationError(
            "commercial_scaling.target_rating_basis is unsupported."
        )
    source_rating_bases = {capacity.rating_basis for capacity in applied_capacities}
    if source_rating_bases != {spec.target_rating_basis}:
        raise TechnoeconomicValidationError(
            "The commercial target rating basis must match the frozen source "
            "applied-capacity rating basis."
        )
    if spec.transfer_method != COMMERCIAL_SCALING_TRANSFER_METHOD:
        raise TechnoeconomicValidationError(
            "tea-calculation-v3 supports only transfer_method "
            f"{COMMERCIAL_SCALING_TRANSFER_METHOD!r}."
        )
    if spec.marginal_cost_timing not in {
        "lifecycle_present_value",
        "equivalent_annual",
    }:
        raise TechnoeconomicValidationError(
            "commercial_scaling.marginal_cost_timing must be "
            "'lifecycle_present_value' or 'equivalent_annual'."
        )
    marginal_cost = validate_distribution(spec.marginal_cost_difference)
    if marginal_cost.input_id != COMMERCIAL_MARGINAL_COST_DIFFERENCE_INPUT_ID:
        raise TechnoeconomicValidationError(
            "The commercial marginal-cost distribution must use stable input ID "
            f"{COMMERCIAL_MARGINAL_COST_DIFFERENCE_INPUT_ID!r}."
        )
    return replace(
        spec,
        target_capacity_w=target_capacity_w,
        marginal_cost_difference=marginal_cost,
    )


def _validate_commercial_cost_line(
    line: CommercialCostLineSpec,
    project_life_years: int,
    constant_dollar_cost_year: int,
) -> CommercialCostLineSpec:
    """Validate one version-4 standalone cost line and its timing."""

    if not isinstance(line, CommercialCostLineSpec):
        raise TechnoeconomicValidationError(
            "Every standalone commercial cost line must be a "
            "CommercialCostLineSpec."
        )
    input_id = _validate_stable_id(line.input_id, "Commercial cost input ID")
    if line.distribution.input_id != input_id:
        raise TechnoeconomicValidationError(
            f"Commercial cost line {input_id!r} must use a distribution with "
            "the same input ID."
        )
    if not isinstance(line.label, str) or not line.label.strip():
        raise TechnoeconomicValidationError(
            f"Commercial cost line {input_id!r} requires a label."
        )
    category_contract = {
        "full_initial_capex": "initial_t0",
        "full_annual_om": "annual_year_end",
        "scheduled_replacement": "scheduled_year_end",
    }
    expected_timing = category_contract.get(line.cost_category)
    if expected_timing is None:
        raise TechnoeconomicValidationError(
            f"Commercial cost line {input_id!r} has unsupported cost category."
        )
    if line.timing != expected_timing:
        raise TechnoeconomicValidationError(
            f"Commercial cost category {line.cost_category!r} requires timing "
            f"{expected_timing!r}."
        )
    if (
        not _is_int(line.constant_dollar_cost_year)
        or int(line.constant_dollar_cost_year) < 1900
        or int(line.constant_dollar_cost_year) > 3000
    ):
        raise TechnoeconomicValidationError(
            f"Commercial cost line {input_id!r} constant-dollar cost year "
            "must be an integer from 1900 through 3000."
        )
    if int(line.constant_dollar_cost_year) != constant_dollar_cost_year:
        raise TechnoeconomicValidationError(
            f"Commercial cost line {input_id!r} must use the request "
            "constant-dollar cost year."
        )
    if isinstance(line.coverage_ids, (str, bytes)):
        raise TechnoeconomicValidationError(
            f"Commercial cost line {input_id!r} coverage IDs must be a sequence."
        )
    try:
        coverage_ids = tuple(
            _validate_stable_id(value, "Commercial cost coverage ID")
            for value in line.coverage_ids
        )
    except TypeError as exc:
        raise TechnoeconomicValidationError(
            f"Commercial cost line {input_id!r} coverage IDs must be a sequence."
        ) from exc
    if not coverage_ids:
        raise TechnoeconomicValidationError(
            f"Commercial cost line {input_id!r} requires coverage IDs."
        )
    if len(set(coverage_ids)) != len(coverage_ids):
        raise TechnoeconomicValidationError(
            f"Commercial cost line {input_id!r} coverage IDs must be unique."
        )
    distribution = validate_distribution(line.distribution, "cost")
    occurrence_years = tuple(line.occurrence_years)
    if line.timing == "scheduled_year_end":
        if not occurrence_years:
            raise TechnoeconomicValidationError(
                f"Scheduled commercial cost line {input_id!r} requires at least "
                "one occurrence year."
            )
        if any(
            not _is_int(year) or int(year) < 1 or int(year) > project_life_years
            for year in occurrence_years
        ):
            raise TechnoeconomicValidationError(
                "Scheduled commercial cost occurrence years must be integers "
                "within project years 1..L."
            )
        normalized_years = tuple(int(year) for year in occurrence_years)
        if normalized_years != tuple(sorted(set(normalized_years))):
            raise TechnoeconomicValidationError(
                "Scheduled commercial cost occurrence years must be unique and "
                "strictly increasing."
            )
    else:
        if occurrence_years:
            raise TechnoeconomicValidationError(
                "Only scheduled_year_end commercial costs may define occurrence "
                "years."
            )
        normalized_years = ()
    return replace(
        line,
        input_id=input_id,
        label=line.label.strip(),
        constant_dollar_cost_year=int(line.constant_dollar_cost_year),
        coverage_ids=tuple(sorted(coverage_ids, key=lambda value: value.encode("ascii"))),
        distribution=distribution,
        occurrence_years=normalized_years,
    )


def _validate_standalone_commercial(
    spec: StandaloneCommercialSpec,
    applied_capacities: Sequence[AppliedCapacitySpec],
    project_life_years: int,
    constant_dollar_cost_year: int,
) -> StandaloneCommercialSpec:
    """Validate the version-4 standalone commercial SolarEdge contract."""

    if not isinstance(spec, StandaloneCommercialSpec):
        raise TechnoeconomicValidationError(
            "tea-calculation-v4 requires a StandaloneCommercialSpec."
        )
    target_capacity_w = _finite_float(
        spec.target_capacity_w,
        "standalone_commercial.target_capacity_w",
    )
    if target_capacity_w <= 0:
        raise TechnoeconomicValidationError(
            "standalone_commercial.target_capacity_w must be strictly positive."
        )
    if spec.target_rating_basis not in {
        "ac_operating_limit",
        "dc_installed_nameplate",
    }:
        raise TechnoeconomicValidationError(
            "standalone_commercial.target_rating_basis is unsupported."
        )
    applied_map = {capacity.system: capacity for capacity in applied_capacities}
    if applied_map["solaredge"].rating_basis != spec.target_rating_basis:
        raise TechnoeconomicValidationError(
            "The standalone commercial target rating basis must match the frozen "
            "SolarEdge source applied-capacity rating basis."
        )
    if spec.transfer_method != COMMERCIAL_SCALING_TRANSFER_METHOD:
        raise TechnoeconomicValidationError(
            "tea-calculation-v4 supports only transfer_method "
            f"{COMMERCIAL_SCALING_TRANSFER_METHOD!r}."
        )
    if not spec.cost_lines:
        raise TechnoeconomicValidationError(
            "tea-calculation-v4 requires at least one standalone commercial cost "
            "line."
        )
    lines = tuple(
        _validate_commercial_cost_line(
            line,
            project_life_years,
            constant_dollar_cost_year,
        )
        for line in spec.cost_lines
    )
    lines = tuple(sorted(lines, key=lambda line: line.input_id.encode("ascii")))
    identifiers = [line.input_id for line in lines]
    if len(set(identifiers)) != len(identifiers):
        raise TechnoeconomicValidationError(
            "Standalone commercial cost input IDs must be unique."
        )
    categories = [line.cost_category for line in lines]
    for required in ("full_initial_capex", "full_annual_om"):
        if categories.count(required) != 1:
            raise TechnoeconomicValidationError(
                "Standalone commercial full-system costs require exactly one "
                f"{required} line."
            )
    scheduled = [
        line for line in lines if line.cost_category == "scheduled_replacement"
    ]
    for index, left in enumerate(scheduled):
        for right in scheduled[index + 1 :]:
            if set(left.coverage_ids) & set(right.coverage_ids) and set(
                left.occurrence_years
            ) & set(right.occurrence_years):
                raise TechnoeconomicValidationError(
                    "Scheduled commercial replacement coverage must not overlap "
                    "at the same occurrence year."
                )
    return replace(
        spec,
        target_capacity_w=target_capacity_w,
        cost_lines=lines,
    )


def _validate_paired_commercial(
    spec: PairedCommercialSpec,
    applied_capacities: Sequence[AppliedCapacitySpec],
    project_life_years: int,
    constant_dollar_cost_year: int,
) -> PairedCommercialSpec:
    """Validate the version-5 paired standalone commercial contract."""

    if not isinstance(spec, PairedCommercialSpec):
        raise TechnoeconomicValidationError(
            "tea-calculation-v5 requires a PairedCommercialSpec."
        )
    target_capacity_w = _finite_float(
        spec.target_capacity_w,
        "paired_commercial.target_capacity_w",
    )
    if target_capacity_w <= 0:
        raise TechnoeconomicValidationError(
            "paired_commercial.target_capacity_w must be strictly positive."
        )
    if spec.target_rating_basis not in {
        "ac_operating_limit",
        "dc_installed_nameplate",
    }:
        raise TechnoeconomicValidationError(
            "paired_commercial.target_rating_basis is unsupported."
        )
    applied_map = {capacity.system: capacity for capacity in applied_capacities}
    if any(
        applied_map[system].rating_basis != spec.target_rating_basis
        for system in ("solectria", "solaredge")
    ):
        raise TechnoeconomicValidationError(
            "The paired commercial target rating basis must match both frozen "
            "source applied-capacity rating bases."
        )
    if spec.transfer_method != COMMERCIAL_SCALING_TRANSFER_METHOD:
        raise TechnoeconomicValidationError(
            "tea-calculation-v5 supports only transfer_method "
            f"{COMMERCIAL_SCALING_TRANSFER_METHOD!r}."
        )
    if len(spec.systems) != 2 or {
        system.technology
        for system in spec.systems
        if isinstance(system, PairedCommercialSystemSpec)
    } != {"solectria", "solaredge"}:
        raise TechnoeconomicValidationError(
            "tea-calculation-v5 requires exactly one Solectria and one SolarEdge "
            "commercial system specification."
        )

    normalized_systems: list[PairedCommercialSystemSpec] = []
    all_identifiers: list[str] = []
    for technology in ("solectria", "solaredge"):
        system = next(item for item in spec.systems if item.technology == technology)
        if not system.cost_lines:
            raise TechnoeconomicValidationError(
                f"tea-calculation-v5 requires at least one {technology} commercial "
                "cost line."
            )
        lines = tuple(
            sorted(
                (
                    _validate_commercial_cost_line(
                        line,
                        project_life_years,
                        constant_dollar_cost_year,
                    )
                    for line in system.cost_lines
                ),
                key=lambda line: line.input_id.encode("ascii"),
            )
        )
        identifiers = [line.input_id for line in lines]
        if len(set(identifiers)) != len(identifiers):
            raise TechnoeconomicValidationError(
                "Paired commercial cost input IDs must be unique per system."
            )
        all_identifiers.extend(identifiers)
        categories = [line.cost_category for line in lines]
        for required in ("full_initial_capex", "full_annual_om"):
            if categories.count(required) != 1:
                raise TechnoeconomicValidationError(
                    "Paired commercial full-system costs require exactly one "
                    f"{required} line per system."
                )
        for index, left in enumerate(lines):
            for right in lines[index + 1 :]:
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
                    raise TechnoeconomicValidationError(
                        "Scheduled paired commercial replacement coverage must not "
                        "overlap at the same occurrence year within one system."
                    )
                raise TechnoeconomicValidationError(
                    "Paired commercial coverage IDs must be disjoint between cost "
                    "lines unless both are scheduled replacements at disjoint years."
                )
        normalized_systems.append(replace(system, cost_lines=lines))
    if len(set(all_identifiers)) != len(all_identifiers):
        raise TechnoeconomicValidationError(
            "Paired commercial cost input IDs must be globally unique."
        )
    return replace(
        spec,
        target_capacity_w=target_capacity_w,
        systems=(normalized_systems[0], normalized_systems[1]),
    )


def _normalization_capacity_map(
    request: TechnoeconomicRequest,
) -> dict[SystemName, float]:
    if request.calculation_contract_version in {
        CALCULATION_CONTRACT_VERSION,
        COMMERCIAL_SCALING_CALCULATION_CONTRACT_VERSION,
        STANDALONE_COMMERCIAL_CALCULATION_CONTRACT_VERSION,
        PAIRED_COMMERCIAL_CALCULATION_CONTRACT_VERSION,
    }:
        assert request.applied_capacities is not None
        return {spec.system: spec.applied_capacity_w for spec in request.applied_capacities}
    return {spec.system: spec.installed_wdc for spec in request.capacities}


def _metric_fields(request: TechnoeconomicRequest) -> _MetricFields:
    if request.calculation_contract_version in {
        CALCULATION_CONTRACT_VERSION,
        COMMERCIAL_SCALING_CALCULATION_CONTRACT_VERSION,
        STANDALONE_COMMERCIAL_CALCULATION_CONTRACT_VERSION,
        PAIRED_COMMERCIAL_CALCULATION_CONTRACT_VERSION,
    }:
        return APPLIED_METRIC_FIELDS
    return LEGACY_METRIC_FIELDS


def _validate_life(project_life_years: Any) -> int:
    if not _is_int(project_life_years) or int(project_life_years) < 1:
        raise TechnoeconomicValidationError(
            "project_life_years must be a fixed positive integer."
        )
    return int(project_life_years)


def _return_scalar_if_scalar(
    original: Any,
    first: np.ndarray,
    second: np.ndarray,
) -> tuple[float, float] | tuple[np.ndarray, np.ndarray]:
    if np.asarray(original).ndim == 0:
        return float(first), float(second)
    return first, second


def annuity_factor_and_crf(
    discount_rate: float | Sequence[float] | np.ndarray,
    project_life_years: int,
) -> tuple[float, float] | tuple[np.ndarray, np.ndarray]:
    """Return the year-end annuity factor and capital-recovery factor."""

    life = _validate_life(project_life_years)
    try:
        life_as_float = float(life)
    except OverflowError as exc:
        raise TechnoeconomicValidationError(
            "project_life_years is not representable by the version-1 numerical contract."
        ) from exc
    if not math.isfinite(life_as_float):
        raise TechnoeconomicValidationError(
            "project_life_years is not representable by the version-1 numerical contract."
        )
    rates = np.asarray(discount_rate, dtype=np.float64)
    if not np.isfinite(rates).all() or np.any(rates <= -1):
        raise TechnoeconomicValidationError(
            "Every discount rate must be finite and greater than -1."
        )
    with np.errstate(over="ignore", under="ignore", divide="ignore", invalid="ignore"):
        log_growth = np.log1p(rates)
        factors = np.where(
            rates == 0,
            life_as_float,
            -np.expm1(-life_as_float * log_growth) / rates,
        )
        crf = 1.0 / factors
    if (
        not np.isfinite(factors).all()
        or not np.isfinite(crf).all()
        or np.any(factors <= 0)
        or np.any(crf <= 0)
    ):
        raise TechnoeconomicValidationError(
            "Discount-rate support and project life must produce finite positive AF and CRF."
        )
    return _return_scalar_if_scalar(discount_rate, factors, crf)


def lifecycle_energy_factor(
    discount_rate: float | Sequence[float] | np.ndarray,
    degradation: float | Sequence[float] | np.ndarray,
    project_life_years: int,
) -> float | np.ndarray:
    """Return ``sum((1-g)^(t-1)/(1+r)^t)`` for years 1 through L."""

    life = _validate_life(project_life_years)
    try:
        life_as_float = float(life)
    except OverflowError as exc:
        raise TechnoeconomicValidationError(
            "project_life_years is not representable by the version-1 numerical contract."
        ) from exc
    if not math.isfinite(life_as_float):
        raise TechnoeconomicValidationError(
            "project_life_years is not representable by the version-1 numerical contract."
        )
    rates, degradations = np.broadcast_arrays(
        np.asarray(discount_rate, dtype=np.float64),
        np.asarray(degradation, dtype=np.float64),
    )
    if not np.isfinite(rates).all() or np.any(rates <= -1):
        raise TechnoeconomicValidationError(
            "Every discount rate must be finite and greater than -1."
        )
    if (
        not np.isfinite(degradations).all()
        or np.any(degradations < 0)
        or np.any(degradations >= 1)
    ):
        raise TechnoeconomicValidationError(
            "Every degradation rate must satisfy 0 <= g < 1."
        )
    with np.errstate(over="ignore", under="ignore", divide="ignore", invalid="ignore"):
        log_ratio = np.log1p(-degradations) - np.log1p(rates)
        geometric_sum = np.where(
            log_ratio == 0,
            life_as_float,
            np.expm1(life_as_float * log_ratio) / np.expm1(log_ratio),
        )
        factors = geometric_sum / (1.0 + rates)
    if not np.isfinite(factors).all() or np.any(factors <= 0):
        raise TechnoeconomicValidationError(
            "Discount, degradation, and project life must produce finite positive lifecycle energy factors."
        )
    if np.asarray(discount_rate).ndim == 0 and np.asarray(degradation).ndim == 0:
        return float(factors)
    return np.asarray(factors, dtype=np.float64)


def _scheduled_discount_factor(
    discount_rate: float | Sequence[float] | np.ndarray,
    occurrence_year: int,
) -> float | np.ndarray:
    """Return one year-end discount factor through one canonical v4 path.

    Support-wide validation and realization execution must call this same helper.
    Using a distinct, mathematically equivalent ``power`` expression can differ by
    several binary64 ULPs and invalidate the proof at the finite range boundary.
    """

    rates = np.asarray(discount_rate, dtype=np.float64)
    with np.errstate(over="ignore", under="ignore", invalid="ignore"):
        factors = np.exp(-float(occurrence_year) * np.log1p(rates))
    if np.asarray(discount_rate).ndim == 0:
        return float(factors)
    return np.asarray(factors, dtype=np.float64)


def _validate_cost_line(line: CostLineSpec, basis: AnalysisBasis) -> CostLineSpec:
    if not isinstance(line, CostLineSpec):
        raise TechnoeconomicValidationError("Every cost line must be a CostLineSpec.")
    _validate_stable_id(line.input_id, "Cost input ID")
    if line.distribution.input_id != line.input_id:
        raise TechnoeconomicValidationError(
            f"Cost line {line.input_id!r} must use a distribution with the same input ID."
        )
    if not isinstance(line.label, str) or not line.label.strip():
        raise TechnoeconomicValidationError(f"Cost line {line.input_id!r} requires a label.")
    if line.basis != basis:
        raise TechnoeconomicValidationError(
            f"Cost line {line.input_id!r} mixes analysis bases."
        )
    if line.ownership not in {"solectria_only", "solaredge_only", "paired_shared"}:
        raise TechnoeconomicValidationError(
            f"Cost line {line.input_id!r} has unsupported ownership."
        )
    if line.cost_type not in INITIAL_COST_TYPES | RECURRING_COST_TYPES:
        raise TechnoeconomicValidationError(
            f"Cost line {line.input_id!r} has unsupported cost type."
        )
    distribution = validate_distribution(line.distribution, "cost")
    sol_multiplier = _finite_float(
        line.solectria_multiplier_to_intensity,
        f"{line.input_id}.solectria_multiplier_to_intensity",
    )
    se_multiplier = _finite_float(
        line.solaredge_multiplier_to_intensity,
        f"{line.input_id}.solaredge_multiplier_to_intensity",
    )
    if sol_multiplier < 0 or se_multiplier < 0:
        raise TechnoeconomicValidationError("Cost intensity multipliers must be nonnegative.")
    if line.ownership == "solectria_only" and not (sol_multiplier > 0 and se_multiplier == 0):
        raise TechnoeconomicValidationError(
            f"Solectria-only cost {line.input_id!r} requires positive SOL and zero SE multipliers."
        )
    if line.ownership == "solaredge_only" and not (se_multiplier > 0 and sol_multiplier == 0):
        raise TechnoeconomicValidationError(
            f"SolarEdge-only cost {line.input_id!r} requires zero SOL and positive SE multipliers."
        )
    if line.ownership == "paired_shared" and not (sol_multiplier > 0 and se_multiplier > 0):
        raise TechnoeconomicValidationError(
            f"Paired cost {line.input_id!r} requires positive multipliers for both systems."
        )
    if not line.coverage_ids:
        raise TechnoeconomicValidationError(
            f"Cost line {line.input_id!r} requires at least one coverage ID."
        )
    coverage_ids = tuple(_validate_stable_id(value, "Cost coverage ID") for value in line.coverage_ids)
    if len(set(coverage_ids)) != len(coverage_ids):
        raise TechnoeconomicValidationError(
            f"Cost line {line.input_id!r} repeats a coverage ID."
        )
    treatment_values: list[str] = []
    for label, value in (
        ("solectria_treatment_key", line.solectria_treatment_key),
        ("solaredge_treatment_key", line.solaredge_treatment_key),
    ):
        if not isinstance(value, str) or not value.strip() or "\0" in value:
            raise TechnoeconomicValidationError(
                f"Cost line {line.input_id!r} {label} must be nonempty and contain no NUL."
            )
        treatment_values.append(value.strip())
    for label, value in zip(
        ("solectria_treatment_key", "solaredge_treatment_key"),
        treatment_values,
    ):
        if value != SUPPORTED_COST_TREATMENT:
            raise TechnoeconomicValidationError(
                f"Cost line {line.input_id!r} {label} has unsupported treatment "
                f"{value!r}; version 1 supports only {SUPPORTED_COST_TREATMENT!r}."
            )
    return replace(
        line,
        label=line.label.strip(),
        distribution=distribution,
        solectria_multiplier_to_intensity=sol_multiplier,
        solaredge_multiplier_to_intensity=se_multiplier,
        coverage_ids=coverage_ids,
        solectria_treatment_key=treatment_values[0],
        solaredge_treatment_key=treatment_values[1],
    )


def _line_systems(line: CostLineSpec) -> tuple[SystemName, ...]:
    if line.ownership == "solectria_only":
        return ("solectria",)
    if line.ownership == "solaredge_only":
        return ("solaredge",)
    return ("solectria", "solaredge")


def _validate_cost_overlaps(lines: Sequence[CostLineSpec]) -> None:
    coverage: dict[tuple[str, str, str], str] = {}
    for line in lines:
        timing_group = (
            "initial_t0" if line.cost_type in INITIAL_COST_TYPES else "recurring_year_end"
        )
        for system in _line_systems(line):
            for coverage_id in line.coverage_ids:
                key = (system, timing_group, coverage_id)
                prior = coverage.get(key)
                if prior is not None:
                    raise TechnoeconomicValidationError(
                        "Cost scope overlap: "
                        f"{prior!r} and {line.input_id!r} both cover "
                        f"{system}/{timing_group}/{coverage_id}."
                    )
                coverage[key] = line.input_id


def _common_treatment(line: CostLineSpec) -> tuple[str, tuple[str, ...]]:
    if line.ownership != "paired_shared":
        return "not_shared", ()
    reasons: list[str] = []
    if line.solectria_multiplier_to_intensity != line.solaredge_multiplier_to_intensity:
        reasons.append("normalized_intensity_multiplier_differs")
    if line.solectria_treatment_key != line.solaredge_treatment_key:
        reasons.append("calculation_treatment_differs")
    if reasons:
        return "shared_non_cancelling", tuple(reasons)
    return "common_cancelled", ()


def _validate_energy_rows(rows: Sequence[PairedEnergyRow]) -> tuple[PairedEnergyRow, ...]:
    if not rows:
        raise TechnoeconomicValidationError("At least one eligible paired energy row is required.")
    normalized: list[PairedEnergyRow] = []
    years: set[int] = set()
    for row in rows:
        if not isinstance(row, PairedEnergyRow):
            raise TechnoeconomicValidationError("Every energy row must be a PairedEnergyRow.")
        if not _is_int(row.year):
            raise TechnoeconomicValidationError("Paired energy year must be an integer.")
        year = int(row.year)
        if year in years:
            raise TechnoeconomicValidationError("Paired energy years must be unique.")
        years.add(year)
        sol = _finite_float(row.sol_predicted_kwh_ac, f"{year}.sol_predicted_kwh_ac")
        se = _finite_float(row.se_predicted_kwh_ac, f"{year}.se_predicted_kwh_ac")
        if sol <= 0 or se <= 0:
            raise TechnoeconomicValidationError(
                "Every paired annual energy value must be strictly positive."
            )
        normalized.append(replace(row, year=year, sol_predicted_kwh_ac=sol, se_predicted_kwh_ac=se))
    return tuple(sorted(normalized, key=lambda item: item.year))


def _validate_transfer_support(
    transfer: TransferSpec,
    rows: Sequence[PairedEnergyRow],
    capacities: Mapping[SystemName, CapacitySpec],
) -> TransferSpec:
    if not isinstance(transfer, TransferSpec):
        raise TechnoeconomicValidationError("Commercial transfer must be a TransferSpec.")
    baseline = validate_distribution(transfer.baseline, "transfer_baseline")
    incremental = validate_distribution(transfer.incremental, "transfer_incremental")
    if baseline.input_id == incremental.input_id:
        raise TechnoeconomicValidationError("Transfer input IDs must be distinct.")
    if transfer.mechanism_status != "approved":
        raise TechnoeconomicValidationError(
            "Commercial energy transfer requires an approved mechanism record."
        )
    baseline_low, baseline_high = distribution_support(baseline)
    incremental_low, incremental_high = distribution_support(incremental)
    for row in rows:
        source_sol = row.sol_predicted_kwh_ac / capacities["solectria"].installed_wdc
        source_se = row.se_predicted_kwh_ac / capacities["solaredge"].installed_wdc
        source_delta = source_se - source_sol
        minimum_sol = baseline_low * source_sol
        minimum_se = minimum_sol + (
            incremental_low * source_delta
            if source_delta >= 0
            else incremental_high * source_delta
        )
        maximum_sol = baseline_high * source_sol
        maximum_se = maximum_sol + (
            incremental_high * source_delta
            if source_delta >= 0
            else incremental_low * source_delta
        )
        if (
            not all(
                math.isfinite(value)
                for value in (minimum_sol, minimum_se, maximum_sol, maximum_se)
            )
            or minimum_sol <= 0
            or minimum_se <= 0
            or maximum_sol <= 0
            or maximum_se <= 0
        ):
            raise TechnoeconomicValidationError(
                "Commercial transfer support cannot prove positive absolute SOL and SE yields "
                f"for source year {row.year}."
            )
    return replace(transfer, baseline=baseline, incremental=incremental)


def _require_supported_binary64(
    label: str,
    value: Decimal,
    *,
    strictly_positive: bool = False,
) -> None:
    """Reject a closed-support bound that cannot be represented by the kernel."""

    maximum = Decimal.from_float(float(np.finfo(np.float64).max))
    if not value.is_finite() or abs(value) > maximum:
        raise TechnoeconomicValidationError(
            f"Support-wide validation requires {label} to remain finite in binary64."
        )
    converted = float(value)
    if not math.isfinite(converted) or (strictly_positive and converted <= 0):
        qualifier = "finite and strictly positive" if strictly_positive else "finite"
        raise TechnoeconomicValidationError(
            f"Support-wide validation requires {label} to remain {qualifier} in binary64."
        )


def _validate_support_wide_outputs(
    *,
    basis: AnalysisBasis,
    life: int,
    normalization_capacities_w: Mapping[SystemName, float],
    rows: Sequence[PairedEnergyRow],
    lines: Sequence[CostLineSpec],
    discount: DistributionSpec,
    degradation: DistributionSpec,
    transfer: TransferSpec | None,
    reference_wdc: float | None,
    commercial_scaling: CommercialScalingSpec | None,
    standalone_commercial: StandaloneCommercialSpec | None,
    paired_commercial: PairedCommercialSpec | None,
) -> None:
    """Prove closed input supports cannot overflow required realization fields.

    Validation uses exact binary64-to-Decimal conversion and conservative endpoint
    bounds.  Runtime invariant guards remain as defense in depth, but a request that
    is guaranteed to overflow must never be accepted for durable execution.
    """

    def decimal_value(value: float) -> Decimal:
        return Decimal.from_float(float(value))

    with localcontext() as context:
        context.prec = 100
        zero = Decimal(0)
        cost_bounds = {
            "initial_sol": zero,
            "initial_se": zero,
            "recurring_sol": zero,
            "recurring_se": zero,
            "initial_delta_abs": zero,
            "recurring_delta_abs": zero,
            "raw_initial_delta_abs": zero,
            "raw_recurring_delta_abs": zero,
        }
        sol_normalization_w = decimal_value(normalization_capacities_w["solectria"])
        se_normalization_w = decimal_value(normalization_capacities_w["solaredge"])

        for line in lines:
            high = decimal_value(distribution_support(line.distribution)[1])
            sol_multiplier = decimal_value(line.solectria_multiplier_to_intensity)
            se_multiplier = decimal_value(line.solaredge_multiplier_to_intensity)
            sol_contribution = high * sol_multiplier
            se_contribution = high * se_multiplier
            prefix = "initial" if line.cost_type in INITIAL_COST_TYPES else "recurring"
            cost_bounds[f"{prefix}_sol"] += sol_contribution
            cost_bounds[f"{prefix}_se"] += se_contribution
            if _common_treatment(line)[0] != "common_cancelled":
                cost_bounds[f"{prefix}_delta_abs"] += abs(
                    se_contribution - sol_contribution
                )
            cost_bounds[f"raw_{prefix}_delta_abs"] += abs(
                se_contribution * se_normalization_w
                - sol_contribution * sol_normalization_w
            )

        discount_endpoints = distribution_support(discount)
        degradation_endpoints = distribution_support(degradation)
        annuity_factors: list[Decimal] = []
        crfs: list[Decimal] = []
        energy_factors: list[Decimal] = []
        finance_energy_cases: list[tuple[Decimal, Decimal, Decimal]] = []
        for rate in discount_endpoints:
            annuity_factor, crf = annuity_factor_and_crf(rate, life)
            annuity_decimal = decimal_value(float(annuity_factor))
            crf_decimal = decimal_value(float(crf))
            annuity_factors.append(annuity_decimal)
            crfs.append(crf_decimal)
            for degradation_rate in degradation_endpoints:
                energy_factor = decimal_value(
                    float(lifecycle_energy_factor(rate, degradation_rate, life))
                )
                energy_factors.append(energy_factor)
                finance_energy_cases.append(
                    (annuity_decimal, crf_decimal, energy_factor)
                )

        annuity_max = max(annuity_factors)
        crf_max = max(crfs)
        energy_factor_min = min(energy_factors)
        energy_factor_max = max(energy_factors)
        equivalent_energy_factor_max = max(
            crf * energy_factor
            for _, crf, energy_factor in finance_energy_cases
        )
        maximum_annuity_over_energy = max(
            annuity_factor / energy_factor
            for annuity_factor, _, energy_factor in finance_energy_cases
        )

        pv_cost_bounds = {
            "SOL": cost_bounds["initial_sol"]
            + cost_bounds["recurring_sol"] * annuity_max,
            "SE": cost_bounds["initial_se"]
            + cost_bounds["recurring_se"] * annuity_max,
        }
        ea_cost_bounds = {
            "SOL": cost_bounds["initial_sol"] * crf_max
            + cost_bounds["recurring_sol"],
            "SE": cost_bounds["initial_se"] * crf_max
            + cost_bounds["recurring_se"],
        }
        delta_pv_cost_bound = (
            cost_bounds["initial_delta_abs"]
            + cost_bounds["recurring_delta_abs"] * annuity_max
        )
        delta_ea_cost_bound = (
            cost_bounds["initial_delta_abs"] * crf_max
            + cost_bounds["recurring_delta_abs"]
        )
        for name, value in cost_bounds.items():
            _require_supported_binary64(f"{name} cost intensity", value)
        for system in ("SOL", "SE"):
            _require_supported_binary64(
                f"PV cost intensity for {system}", pv_cost_bounds[system]
            )
            _require_supported_binary64(
                f"equivalent-annual cost intensity for {system}",
                ea_cost_bounds[system],
            )
        _require_supported_binary64(
            "absolute SE-minus-SOL PV cost intensity", delta_pv_cost_bound
        )
        _require_supported_binary64(
            "absolute SE-minus-SOL equivalent-annual cost intensity",
            delta_ea_cost_bound,
        )

        if basis == "solartac_site":
            _require_supported_binary64(
                "raw SolarTAC SOL PV cost",
                pv_cost_bounds["SOL"] * sol_normalization_w,
            )
            _require_supported_binary64(
                "raw SolarTAC SE PV cost",
                pv_cost_bounds["SE"] * se_normalization_w,
            )
            raw_delta_bound = (
                cost_bounds["raw_initial_delta_abs"]
                + cost_bounds["raw_recurring_delta_abs"] * annuity_max
            )
            _require_supported_binary64(
                "absolute raw SolarTAC SE-minus-SOL PV cost", raw_delta_bound
            )
        elif reference_wdc is not None:
            reference = decimal_value(reference_wdc)
            for system in ("SOL", "SE"):
                _require_supported_binary64(
                    f"commercial-reference {system} PV cost",
                    pv_cost_bounds[system] * reference,
                )
            _require_supported_binary64(
                "absolute commercial-reference SE-minus-SOL PV cost",
                delta_pv_cost_bound * reference,
            )

        source_specific: dict[str, list[Decimal]] = {"SOL": [], "SE": []}
        raw_source: dict[str, list[Decimal]] = {"SOL": [], "SE": []}
        for row in rows:
            sol_energy = decimal_value(row.sol_predicted_kwh_ac)
            se_energy = decimal_value(row.se_predicted_kwh_ac)
            raw_source["SOL"].append(sol_energy)
            raw_source["SE"].append(se_energy)
            source_specific["SOL"].append(sol_energy / sol_normalization_w)
            source_specific["SE"].append(se_energy / se_normalization_w)
        for system in ("SOL", "SE"):
            for value in source_specific[system]:
                _require_supported_binary64(
                    f"source-year {system} specific energy", value, strictly_positive=True
                )

        if basis == "commercial_representative" and transfer is None:
            return

        year1_specific: dict[str, list[Decimal]] = {"SOL": [], "SE": []}
        delta_year1_abs: list[Decimal] = []
        lcoo_support: list[tuple[Decimal, Decimal, Decimal]] = []
        if basis == "solartac_site":
            year1_specific = source_specific
            for source_sol, source_se in zip(
                source_specific["SOL"], source_specific["SE"]
            ):
                delta_abs = abs(source_se - source_sol)
                delta_year1_abs.append(delta_abs)
                lcoo_support.append(
                    (max(source_sol, source_se), delta_abs, delta_abs)
                )
        else:
            assert transfer is not None
            baseline_endpoints = tuple(
                decimal_value(value) for value in distribution_support(transfer.baseline)
            )
            incremental_endpoints = tuple(
                decimal_value(value) for value in distribution_support(transfer.incremental)
            )
            for source_sol, source_se in zip(
                source_specific["SOL"], source_specific["SE"]
            ):
                source_delta = source_se - source_sol
                row_delta_values: list[Decimal] = []
                row_max_system_values: list[Decimal] = []
                for baseline_value in baseline_endpoints:
                    sol_value = baseline_value * source_sol
                    year1_specific["SOL"].append(sol_value)
                    for incremental_value in incremental_endpoints:
                        delta_value = incremental_value * source_delta
                        se_value = sol_value + delta_value
                        row_delta_values.append(abs(delta_value))
                        row_max_system_values.append(max(sol_value, se_value))
                        year1_specific["SE"].append(se_value)
                        delta_year1_abs.append(abs(delta_value))
                lcoo_support.append(
                    (
                        min(row_max_system_values),
                        min(row_delta_values),
                        max(row_delta_values),
                    )
                )

        pv_energy_bounds: dict[str, tuple[Decimal, Decimal]] = {}
        for system in ("SOL", "SE"):
            minimum_year1 = min(year1_specific[system])
            maximum_year1 = max(year1_specific[system])
            _require_supported_binary64(
                f"year-one {system} specific energy",
                minimum_year1,
                strictly_positive=True,
            )
            _require_supported_binary64(
                f"year-one {system} specific energy", maximum_year1
            )
            minimum_pv = minimum_year1 * energy_factor_min
            maximum_pv = maximum_year1 * energy_factor_max
            pv_energy_bounds[system] = (minimum_pv, maximum_pv)
            _require_supported_binary64(
                f"PV {system} specific energy", minimum_pv, strictly_positive=True
            )
            _require_supported_binary64(
                f"PV {system} specific energy", maximum_pv
            )
            _require_supported_binary64(
                f"equivalent-annual {system} specific energy",
                maximum_year1 * equivalent_energy_factor_max,
            )
            lcoe_bound = (
                cost_bounds[f"initial_{system.lower()}"]
                / (minimum_year1 * energy_factor_min)
                + cost_bounds[f"recurring_{system.lower()}"]
                * maximum_annuity_over_energy
                / minimum_year1
            )
            _require_supported_binary64(
                f"{system} LCOE",
                lcoe_bound,
            )

        maximum_delta_year1 = max(delta_year1_abs, default=zero)
        _require_supported_binary64(
            "absolute SE-minus-SOL PV specific energy",
            maximum_delta_year1 * energy_factor_max,
        )
        _require_supported_binary64(
            "absolute SE-minus-SOL equivalent-annual specific energy",
            maximum_delta_year1 * equivalent_energy_factor_max,
        )

        if commercial_scaling is not None:
            target_capacity = decimal_value(commercial_scaling.target_capacity_w)
            maximum_commercial_year1_delta = (
                maximum_delta_year1 * target_capacity
            )
            _require_supported_binary64(
                "absolute commercial year-one SE-minus-SOL energy",
                maximum_commercial_year1_delta,
                strictly_positive=maximum_delta_year1 > zero,
            )
            _require_supported_binary64(
                "absolute commercial lifecycle SE-minus-SOL energy",
                maximum_commercial_year1_delta * energy_factor_max,
                strictly_positive=maximum_delta_year1 > zero,
            )
            _require_supported_binary64(
                "absolute commercial equivalent-annual SE-minus-SOL energy",
                maximum_commercial_year1_delta * equivalent_energy_factor_max,
                strictly_positive=maximum_delta_year1 > zero,
            )

            marginal_cost_support = tuple(
                decimal_value(value)
                for value in distribution_support(
                    commercial_scaling.marginal_cost_difference
                )
            )
            maximum_marginal_cost = max(
                abs(value) for value in marginal_cost_support
            )
            if commercial_scaling.marginal_cost_timing == "lifecycle_present_value":
                maximum_marginal_pv_cost = maximum_marginal_cost
                maximum_marginal_ea_cost = maximum_marginal_cost * crf_max
            else:
                minimum_crf = min(crfs)
                maximum_marginal_ea_cost = maximum_marginal_cost
                maximum_marginal_pv_cost = maximum_marginal_cost / minimum_crf
            _require_supported_binary64(
                "absolute commercial marginal lifecycle cost difference",
                maximum_marginal_pv_cost,
            )
            _require_supported_binary64(
                "absolute commercial marginal equivalent-annual cost difference",
                maximum_marginal_ea_cost,
            )

            commercial_lcoo_bounds: list[Decimal] = []
            for minimum_max_system, minimum_delta, maximum_delta in lcoo_support:
                relative_tolerance_coefficient = (
                    Decimal("1e-12") * minimum_max_system
                )
                if (
                    maximum_delta <= relative_tolerance_coefficient
                    or maximum_delta * energy_factor_max <= Decimal("1e-9")
                ):
                    continue
                proportional_denominator_coefficient = max(
                    minimum_delta,
                    relative_tolerance_coefficient,
                )
                minimum_specific_denominator = max(
                    Decimal("1e-9"),
                    proportional_denominator_coefficient * energy_factor_min,
                )
                minimum_commercial_denominator = (
                    minimum_specific_denominator * target_capacity
                )
                _require_supported_binary64(
                    "minimum reportable commercial lifecycle energy difference",
                    minimum_commercial_denominator,
                    strictly_positive=True,
                )
                commercial_lcoo_bounds.append(
                    maximum_marginal_pv_cost / minimum_commercial_denominator
                )
            if commercial_lcoo_bounds:
                _require_supported_binary64(
                    "absolute commercial marginal LCOO",
                    max(commercial_lcoo_bounds),
                )

        if standalone_commercial is not None:
            target_capacity = decimal_value(
                standalone_commercial.target_capacity_w
            )
            capacity_scale_factor = (
                target_capacity / se_normalization_w
            )
            _require_supported_binary64(
                "standalone commercial SolarEdge capacity scale factor",
                capacity_scale_factor,
                strictly_positive=True,
            )
            minimum_commercial_year1_energy = (
                min(source_specific["SE"]) * target_capacity
            )
            maximum_commercial_year1_energy = (
                max(source_specific["SE"]) * target_capacity
            )
            minimum_commercial_pv_energy = (
                minimum_commercial_year1_energy * energy_factor_min
            )
            maximum_commercial_pv_energy = (
                maximum_commercial_year1_energy * energy_factor_max
            )
            maximum_commercial_ea_energy = (
                maximum_commercial_year1_energy * equivalent_energy_factor_max
            )
            _require_supported_binary64(
                "standalone commercial SolarEdge year-one energy",
                minimum_commercial_year1_energy,
                strictly_positive=True,
            )
            _require_supported_binary64(
                "standalone commercial SolarEdge year-one energy",
                maximum_commercial_year1_energy,
            )
            _require_supported_binary64(
                "standalone commercial SolarEdge lifecycle energy",
                minimum_commercial_pv_energy,
                strictly_positive=True,
            )
            _require_supported_binary64(
                "standalone commercial SolarEdge lifecycle energy",
                maximum_commercial_pv_energy,
            )
            _require_supported_binary64(
                "standalone commercial SolarEdge equivalent-annual energy",
                maximum_commercial_ea_energy,
            )

            initial_cost_bound = zero
            recurring_pv_cost_bound = zero
            scheduled_pv_cost_bound = zero
            for line in standalone_commercial.cost_lines:
                maximum_intensity = decimal_value(
                    distribution_support(line.distribution)[1]
                )
                target_cost = maximum_intensity * target_capacity
                if line.timing == "initial_t0":
                    initial_cost_bound += target_cost
                elif line.timing == "annual_year_end":
                    recurring_pv_cost_bound += target_cost * annuity_max
                else:
                    with np.errstate(over="ignore", under="ignore", invalid="ignore"):
                        scheduled_factor = max(
                            sum(
                                (
                                    decimal_value(
                                        float(
                                            _scheduled_discount_factor(
                                                float(rate),
                                                year,
                                            )
                                        )
                                    )
                                )
                                for year in line.occurrence_years
                            )
                            for rate in discount_endpoints
                        )
                    scheduled_pv_cost_bound += target_cost * scheduled_factor
            lifecycle_cost_bound = (
                initial_cost_bound
                + recurring_pv_cost_bound
                + scheduled_pv_cost_bound
            )
            equivalent_annual_cost_bound = lifecycle_cost_bound * crf_max
            for label, value in (
                ("initial cost", initial_cost_bound),
                ("recurring lifecycle cost", recurring_pv_cost_bound),
                ("scheduled lifecycle cost", scheduled_pv_cost_bound),
                ("lifecycle cost", lifecycle_cost_bound),
                ("equivalent-annual cost", equivalent_annual_cost_bound),
            ):
                _require_supported_binary64(
                    f"standalone commercial SolarEdge {label}",
                    value,
                )
            _require_supported_binary64(
                "standalone commercial SolarEdge lifecycle LCOE",
                lifecycle_cost_bound / minimum_commercial_pv_energy,
            )
        if paired_commercial is not None:
            target_capacity = decimal_value(paired_commercial.target_capacity_w)
            system_map = {
                system.technology: system for system in paired_commercial.systems
            }
            lcoe_bounds: dict[SystemName, Decimal] = {}
            for technology, source_key, normalization_w in (
                ("solectria", "SOL", sol_normalization_w),
                ("solaredge", "SE", se_normalization_w),
            ):
                capacity_scale_factor = target_capacity / normalization_w
                label = "Solectria" if technology == "solectria" else "SolarEdge"
                _require_supported_binary64(
                    f"paired commercial {label} capacity scale factor",
                    capacity_scale_factor,
                    strictly_positive=True,
                )
                minimum_year1_energy = (
                    min(source_specific[source_key]) * target_capacity
                )
                maximum_year1_energy = (
                    max(source_specific[source_key]) * target_capacity
                )
                minimum_pv_energy = minimum_year1_energy * energy_factor_min
                maximum_pv_energy = maximum_year1_energy * energy_factor_max
                maximum_ea_energy = (
                    maximum_year1_energy * equivalent_energy_factor_max
                )
                for energy_label, value, positive in (
                    ("year-one energy", minimum_year1_energy, True),
                    ("year-one energy", maximum_year1_energy, False),
                    ("lifecycle energy", minimum_pv_energy, True),
                    ("lifecycle energy", maximum_pv_energy, False),
                    ("equivalent-annual energy", maximum_ea_energy, False),
                ):
                    _require_supported_binary64(
                        f"paired commercial {label} {energy_label}",
                        value,
                        strictly_positive=positive,
                    )

                initial_cost_bound = zero
                recurring_pv_cost_bound = zero
                scheduled_pv_cost_bound = zero
                for line in system_map[technology].cost_lines:
                    maximum_intensity = decimal_value(
                        distribution_support(line.distribution)[1]
                    )
                    target_cost = maximum_intensity * target_capacity
                    if line.timing == "initial_t0":
                        initial_cost_bound += target_cost
                    elif line.timing == "annual_year_end":
                        recurring_pv_cost_bound += target_cost * annuity_max
                    else:
                        with np.errstate(
                            over="ignore", under="ignore", invalid="ignore"
                        ):
                            scheduled_factor = max(
                                sum(
                                    decimal_value(
                                        float(
                                            _scheduled_discount_factor(
                                                float(rate), year
                                            )
                                        )
                                    )
                                    for year in line.occurrence_years
                                )
                                for rate in discount_endpoints
                            )
                        scheduled_pv_cost_bound += target_cost * scheduled_factor
                lifecycle_cost_bound = (
                    initial_cost_bound
                    + recurring_pv_cost_bound
                    + scheduled_pv_cost_bound
                )
                equivalent_annual_cost_bound = lifecycle_cost_bound * crf_max
                for cost_label, value in (
                    ("initial cost", initial_cost_bound),
                    ("recurring lifecycle cost", recurring_pv_cost_bound),
                    ("scheduled lifecycle cost", scheduled_pv_cost_bound),
                    ("lifecycle cost", lifecycle_cost_bound),
                    ("equivalent-annual cost", equivalent_annual_cost_bound),
                ):
                    _require_supported_binary64(
                        f"paired commercial {label} {cost_label}", value
                    )
                lcoe_bounds[technology] = (
                    lifecycle_cost_bound / minimum_pv_energy
                )
                _require_supported_binary64(
                    f"paired commercial {label} lifecycle LCOE",
                    lcoe_bounds[technology],
                )
            _require_supported_binary64(
                "absolute paired commercial lifecycle LCOE delta",
                lcoe_bounds["solectria"] + lcoe_bounds["solaredge"],
            )
        # A ratio is calculated only when |delta energy| exceeds its absolute/relative
        # classification tolerance.  Bound the smallest reportable denominator for
        # each discrete weather row from that tolerance and the row's actual support;
        # this rejects true overflow without excluding a ratio whose delta energy is
        # provably far from zero.
        lcoo_bounds: list[Decimal] = []
        for minimum_max_system, minimum_delta, maximum_delta in lcoo_support:
            relative_tolerance_coefficient = (
                Decimal("1e-12") * minimum_max_system
            )
            # A reportable delta can exist only if its largest supported year-one
            # magnitude beats both the relative tolerance coefficient and the
            # absolute tolerance at the largest lifecycle factor.
            if (
                maximum_delta <= relative_tolerance_coefficient
                or maximum_delta * energy_factor_max <= Decimal("1e-9")
            ):
                continue
            proportional_denominator_coefficient = max(
                minimum_delta,
                relative_tolerance_coefficient,
            )
            minimum_denominator = max(
                Decimal("1e-9"),
                proportional_denominator_coefficient * energy_factor_min,
            )
            initial_ratio_bound = (
                cost_bounds["initial_delta_abs"] / minimum_denominator
            )
            # For the recurring term, the denominator is simultaneously at least
            # the absolute floor and B*energy_factor.  The minimum of those two
            # independent upper bounds preserves the AF/energy-factor cancellation
            # (notably L=1, g=0) while covering interior tolerance crossovers.
            recurring_ratio_bound = min(
                cost_bounds["recurring_delta_abs"]
                * annuity_max
                / Decimal("1e-9"),
                cost_bounds["recurring_delta_abs"]
                * maximum_annuity_over_energy
                / proportional_denominator_coefficient,
            )
            lcoo_bounds.append(initial_ratio_bound + recurring_ratio_bound)
        if lcoo_bounds:
            _require_supported_binary64(
                "absolute signed LCOO",
                max(lcoo_bounds),
            )

        if basis == "solartac_site":
            for system in ("SOL", "SE"):
                _require_supported_binary64(
                    f"raw SolarTAC {system} PV energy",
                    max(raw_source[system]) * energy_factor_max,
                )
            maximum_raw_delta = max(
                (
                    abs(se - sol)
                    for sol, se in zip(raw_source["SOL"], raw_source["SE"])
                ),
                default=zero,
            )
            _require_supported_binary64(
                "absolute raw SolarTAC SE-minus-SOL PV energy",
                maximum_raw_delta * energy_factor_max,
            )
        elif reference_wdc is not None:
            reference = decimal_value(reference_wdc)
            for system in ("SOL", "SE"):
                _require_supported_binary64(
                    f"commercial-reference {system} PV energy",
                    pv_energy_bounds[system][1] * reference,
                )
            _require_supported_binary64(
                "absolute commercial-reference SE-minus-SOL PV energy",
                maximum_delta_year1 * energy_factor_max * reference,
            )


def validate_request(request: TechnoeconomicRequest) -> TechnoeconomicRequest:
    """Return a deterministically ordered, fully validated kernel request."""

    validate_runtime_versions()
    if not isinstance(request, TechnoeconomicRequest):
        raise TechnoeconomicValidationError("Request must be a TechnoeconomicRequest.")
    if request.calculation_contract_version not in {
        LEGACY_CALCULATION_CONTRACT_VERSION,
        CALCULATION_CONTRACT_VERSION,
        COMMERCIAL_SCALING_CALCULATION_CONTRACT_VERSION,
        STANDALONE_COMMERCIAL_CALCULATION_CONTRACT_VERSION,
        PAIRED_COMMERCIAL_CALCULATION_CONTRACT_VERSION,
    }:
        raise TechnoeconomicValidationError(
            f"Unsupported calculation contract: {request.calculation_contract_version!r}."
        )
    if request.sampling_version != SAMPLING_VERSION:
        raise TechnoeconomicValidationError(
            f"Unsupported sampling version: {request.sampling_version!r}."
        )
    if request.basis not in {"solartac_site", "commercial_representative"}:
        raise TechnoeconomicValidationError(f"Unsupported analysis basis: {request.basis!r}.")
    if request.cost_stack_completeness != "full_system":
        raise TechnoeconomicValidationError(
            "Version 1 production calculations require a full_system cost stack."
        )
    n, seed = _validate_n_seed(request.n, request.seed)
    life = _validate_life(request.project_life_years)

    capacities = tuple(validate_capacity(spec) for spec in request.capacities)
    capacity_map = {spec.system: spec for spec in capacities}
    if len(capacities) != 2 or set(capacity_map) != {"solectria", "solaredge"}:
        raise TechnoeconomicValidationError(
            "Exactly one Solectria and one SolarEdge capacity manifest are required."
        )
    capacities = (capacity_map["solectria"], capacity_map["solaredge"])
    rows = _validate_energy_rows(request.paired_energy_rows)

    applied_capacities: tuple[AppliedCapacitySpec, AppliedCapacitySpec] | None = None
    if request.calculation_contract_version == LEGACY_CALCULATION_CONTRACT_VERSION:
        if request.applied_capacities is not None:
            raise TechnoeconomicValidationError(
                "tea-calculation-v1 must not define applied_capacities."
            )
    else:
        if request.basis != "solartac_site":
            raise TechnoeconomicValidationError(
                f"{request.calculation_contract_version} applied-capacity normalization "
                "is supported only for the SolarTAC site basis."
            )
        if request.applied_capacities is None:
            raise TechnoeconomicValidationError(
                f"{request.calculation_contract_version} SolarTAC requests require "
                "applied_capacities."
            )
        applied_capacities = _validate_applied_capacities(
            request.applied_capacities,
            capacity_map,
        )

    commercial_only = request.calculation_contract_version in {
        STANDALONE_COMMERCIAL_CALCULATION_CONTRACT_VERSION,
        PAIRED_COMMERCIAL_CALCULATION_CONTRACT_VERSION,
    }
    if commercial_only and request.cost_lines:
        if (
            request.calculation_contract_version
            == STANDALONE_COMMERCIAL_CALCULATION_CONTRACT_VERSION
        ):
            detail = (
                "tea-calculation-v4 must not define legacy site cost_lines; use "
                "standalone_commercial.cost_lines."
            )
        else:
            detail = (
                "tea-calculation-v5 must not define legacy site cost_lines; use "
                "paired_commercial.systems[].cost_lines."
            )
        raise TechnoeconomicValidationError(
            detail
        )
    if not request.cost_lines and not commercial_only:
        raise TechnoeconomicValidationError("At least one cost line is required.")
    lines = tuple(_validate_cost_line(line, request.basis) for line in request.cost_lines)
    lines = tuple(sorted(lines, key=lambda line: line.input_id.encode("ascii")))
    _validate_cost_overlaps(lines)
    if not commercial_only:
        for system in ("solectria", "solaredge"):
            if not any(system in _line_systems(line) for line in lines):
                raise TechnoeconomicValidationError(
                    f"A full_system cost stack requires at least one {system} cost stream."
                )

    discount = validate_distribution(request.discount_rate, "discount_rate")
    degradation = validate_distribution(request.shared_degradation, "degradation")
    all_distributions = [line.distribution for line in lines] + [discount, degradation]

    commercial_scaling: CommercialScalingSpec | None = None
    if (
        request.calculation_contract_version
        == COMMERCIAL_SCALING_CALCULATION_CONTRACT_VERSION
    ):
        if request.commercial_scaling is None:
            raise TechnoeconomicValidationError(
                "tea-calculation-v3 requires commercial_scaling."
            )
        assert applied_capacities is not None
        commercial_scaling = _validate_commercial_scaling(
            request.commercial_scaling,
            applied_capacities,
        )
        all_distributions.append(commercial_scaling.marginal_cost_difference)
    elif request.commercial_scaling is not None:
        if request.calculation_contract_version in {
            LEGACY_CALCULATION_CONTRACT_VERSION,
            CALCULATION_CONTRACT_VERSION,
        }:
            raise TechnoeconomicValidationError(
                "tea-calculation-v1 and tea-calculation-v2 must not define "
                "commercial_scaling."
            )
        raise TechnoeconomicValidationError(
            "Only tea-calculation-v3 may define commercial_scaling."
        )

    standalone_commercial: StandaloneCommercialSpec | None = None
    if (
        request.calculation_contract_version
        == STANDALONE_COMMERCIAL_CALCULATION_CONTRACT_VERSION
    ):
        if request.standalone_commercial is None:
            raise TechnoeconomicValidationError(
                "tea-calculation-v4 requires standalone_commercial."
            )
        if (
            not _is_int(request.constant_dollar_cost_year)
            or int(request.constant_dollar_cost_year) < 1900
            or int(request.constant_dollar_cost_year) > 3000
        ):
            raise TechnoeconomicValidationError(
                "tea-calculation-v4 requires a constant-dollar cost year from "
                "1900 through 3000."
            )
        constant_dollar_cost_year = int(request.constant_dollar_cost_year)
        assert applied_capacities is not None
        standalone_commercial = _validate_standalone_commercial(
            request.standalone_commercial,
            applied_capacities,
            life,
            constant_dollar_cost_year,
        )
        all_distributions.extend(
            line.distribution for line in standalone_commercial.cost_lines
        )
    elif request.standalone_commercial is not None:
        raise TechnoeconomicValidationError(
            "Only tea-calculation-v4 may define standalone_commercial."
        )

    paired_commercial: PairedCommercialSpec | None = None
    if (
        request.calculation_contract_version
        == PAIRED_COMMERCIAL_CALCULATION_CONTRACT_VERSION
    ):
        if request.paired_commercial is None:
            raise TechnoeconomicValidationError(
                "tea-calculation-v5 requires paired_commercial."
            )
        if (
            not _is_int(request.constant_dollar_cost_year)
            or int(request.constant_dollar_cost_year) < 1900
            or int(request.constant_dollar_cost_year) > 3000
        ):
            raise TechnoeconomicValidationError(
                "tea-calculation-v5 requires a constant-dollar cost year from "
                "1900 through 3000."
            )
        constant_dollar_cost_year = int(request.constant_dollar_cost_year)
        assert applied_capacities is not None
        paired_commercial = _validate_paired_commercial(
            request.paired_commercial,
            applied_capacities,
            life,
            constant_dollar_cost_year,
        )
        all_distributions.extend(
            line.distribution
            for system in paired_commercial.systems
            for line in system.cost_lines
        )
    elif request.paired_commercial is not None:
        raise TechnoeconomicValidationError(
            "Only tea-calculation-v5 may define paired_commercial."
        )

    transfer: TransferSpec | None = None
    reference_wdc: float | None = None
    if request.basis == "solartac_site":
        if request.transfer is not None:
            raise TechnoeconomicValidationError(
                "SolarTAC site calculations must not include a commercial transfer."
            )
        if request.commercial_reference_wdc is not None:
            raise TechnoeconomicValidationError(
                "SolarTAC site calculations must not define commercial_reference_wdc."
            )
    else:
        if request.transfer is not None:
            transfer = _validate_transfer_support(request.transfer, rows, capacity_map)
            all_distributions.extend([transfer.baseline, transfer.incremental])
        if request.commercial_reference_wdc is not None:
            reference_wdc = _finite_float(
                request.commercial_reference_wdc,
                "commercial_reference_wdc",
            )
            if reference_wdc <= 0:
                raise TechnoeconomicValidationError(
                    "commercial_reference_wdc must be positive when supplied."
                )
        else:
            reference_wdc = None

    identifiers = [spec.input_id for spec in all_distributions]
    if len(set(identifiers)) != len(identifiers):
        raise TechnoeconomicValidationError(
            "Every cost, finance, degradation, and transfer input ID must be unique."
        )
    reserved = RESERVED_INPUT_IDS & set(identifiers)
    if reserved:
        raise TechnoeconomicValidationError(
            f"Input IDs {sorted(reserved)!r} are reserved for weather allocation "
            "or sensitivity source predictors."
        )

    # Validate support-wide finance/energy arithmetic before any realization runs.
    discount_support = distribution_support(discount)
    degradation_support = distribution_support(degradation)
    for rate in discount_support:
        annuity_factor_and_crf(rate, life)
        for degradation_rate in degradation_support:
            lifecycle_energy_factor(rate, degradation_rate, life)

    normalized_request = replace(
        request,
        capacities=capacities,
        applied_capacities=applied_capacities,
        commercial_scaling=commercial_scaling,
        standalone_commercial=standalone_commercial,
        paired_commercial=paired_commercial,
        constant_dollar_cost_year=(
            int(request.constant_dollar_cost_year)
            if standalone_commercial is not None or paired_commercial is not None
            else request.constant_dollar_cost_year
        ),
    )
    normalization_capacities_w = _normalization_capacity_map(normalized_request)
    _validate_support_wide_outputs(
        basis=request.basis,
        life=life,
        normalization_capacities_w=normalization_capacities_w,
        rows=rows,
        lines=lines,
        discount=discount,
        degradation=degradation,
        transfer=transfer,
        reference_wdc=reference_wdc,
        commercial_scaling=commercial_scaling,
        standalone_commercial=standalone_commercial,
        paired_commercial=paired_commercial,
    )

    return replace(
        request,
        n=n,
        seed=seed,
        project_life_years=life,
        capacities=capacities,
        applied_capacities=applied_capacities,
        paired_energy_rows=rows,
        cost_lines=lines,
        discount_rate=discount,
        shared_degradation=degradation,
        transfer=transfer,
        commercial_scaling=commercial_scaling,
        standalone_commercial=standalone_commercial,
        paired_commercial=paired_commercial,
        commercial_reference_wdc=(
            None
            if request.basis == "solartac_site"
            else reference_wdc
        ),
    )


def _finite_vector(values: Sequence[float] | np.ndarray, label: str) -> np.ndarray:
    result = np.asarray(values, dtype=np.float64)
    if result.ndim != 1:
        raise TechnoeconomicValidationError(f"{label} must be one-dimensional.")
    if not np.isfinite(result).all():
        raise TechnoeconomicValidationError(f"{label} must contain only finite values.")
    return result


def empirical_cdf(values: Sequence[float] | np.ndarray) -> dict[str, Any]:
    """Return a right-continuous ECDF with ties collapsed to unique x values."""

    vector = _finite_vector(values, "ECDF population")
    if vector.size == 0:
        raise TechnoeconomicValidationError("ECDF population must not be empty.")
    ordered = np.sort(vector, kind="stable")
    unique, counts = np.unique(ordered, return_counts=True)
    cumulative = np.cumsum(counts, dtype=np.int64)
    return {
        "values": unique.tolist(),
        "cumulative_count": cumulative.tolist(),
        "cumulative_probability": (cumulative / vector.size).tolist(),
        "population_count": int(vector.size),
    }


def type7_percentiles(values: Sequence[float] | np.ndarray) -> dict[str, float]:
    """Return P5/P50/P95 using NumPy's Hyndman-Fan type-7 method."""

    vector = _finite_vector(values, "Percentile population")
    if vector.size == 0:
        raise TechnoeconomicValidationError("Percentile population must not be empty.")
    quantiles = np.quantile(vector, [0.05, 0.5, 0.95], method="linear")
    return {
        "p5": float(quantiles[0]),
        "p50": float(quantiles[1]),
        "p95": float(quantiles[2]),
    }


def _metric_summary(
    values: Sequence[float] | np.ndarray,
    *,
    empty_reason: str = "no_finite_values",
    include_cdf: bool = True,
) -> dict[str, Any]:
    vector = np.asarray(values, dtype=np.float64)
    if vector.ndim != 1:
        raise TechnoeconomicInvariantError("Metric summary values must be one-dimensional.")
    finite = vector[np.isfinite(vector)]
    if finite.size == 0:
        return {
            "status": "unavailable",
            "reason": empty_reason,
            "count": 0,
            "percentiles": {"p5": None, "p50": None, "p95": None},
            "cdf": None,
        }
    result: dict[str, Any] = {
        "status": "available",
        "reason": None,
        "count": int(finite.size),
        "percentiles": type7_percentiles(finite),
    }
    result["cdf"] = empirical_cdf(finite) if include_cdf else None
    return result


def _commercial_v4_metric_summary(
    values: Sequence[float] | np.ndarray,
    *,
    empty_reason: str = "no_finite_values",
    include_cdf: bool = True,
) -> dict[str, Any]:
    """Return the version-4 P10/P50/P90 summary without changing older schemas."""

    vector = np.asarray(values, dtype=np.float64)
    if vector.ndim != 1:
        raise TechnoeconomicInvariantError(
            "Commercial metric summary values must be one-dimensional."
        )
    finite = vector[np.isfinite(vector)]
    if finite.size == 0:
        return {
            "status": "unavailable",
            "reason": empty_reason,
            "count": 0,
            "percentiles": {"p10": None, "p50": None, "p90": None},
            "cdf": None,
        }
    quantiles = np.quantile(finite, [0.10, 0.50, 0.90], method="linear")
    result: dict[str, Any] = {
        "status": "available",
        "reason": None,
        "count": int(finite.size),
        "percentiles": {
            "p10": float(quantiles[0]),
            "p50": float(quantiles[1]),
            "p90": float(quantiles[2]),
        },
    }
    result["cdf"] = empirical_cdf(finite) if include_cdf else None
    return result


def _midranks(values: np.ndarray) -> np.ndarray:
    order = np.argsort(values, kind="stable")
    ordered = values[order]
    ranks = np.empty(len(values), dtype=np.float64)
    start = 0
    while start < len(values):
        end = start + 1
        while end < len(values) and ordered[end] == ordered[start]:
            end += 1
        average_rank = ((start + 1) + end) / 2.0
        ranks[order[start:end]] = average_rank
        start = end
    return ranks


def _standardize_ranks(values: np.ndarray) -> np.ndarray | None:
    ranks = _midranks(values)
    standard_deviation = float(np.std(ranks, ddof=1)) if len(ranks) > 1 else 0.0
    if not math.isfinite(standard_deviation) or standard_deviation == 0:
        return None
    return (ranks - float(np.mean(ranks))) / standard_deviation


def _fit_rank_model(response: np.ndarray, columns: Sequence[np.ndarray]) -> tuple[float, np.ndarray, int]:
    matrix = np.column_stack([np.ones(len(response), dtype=np.float64), *columns])
    rank = int(np.linalg.matrix_rank(matrix))
    if rank != matrix.shape[1]:
        raise np.linalg.LinAlgError("Rank-regression design is singular.")
    coefficients, _, fitted_rank, _ = np.linalg.lstsq(matrix, response, rcond=None)
    if int(fitted_rank) != matrix.shape[1] or not np.isfinite(coefficients).all():
        raise np.linalg.LinAlgError("Rank-regression fit is singular.")
    fitted = matrix @ coefficients
    total_sum = float(np.square(response - float(np.mean(response))).sum())
    residual_sum = float(np.square(response - fitted).sum())
    if total_sum <= 0 or not math.isfinite(total_sum) or not math.isfinite(residual_sum):
        raise np.linalg.LinAlgError("Rank-regression response is numerically invalid.")
    r_squared = 1.0 - residual_sum / total_sum
    r_squared = min(1.0, max(0.0, float(r_squared)))
    return r_squared, coefficients, rank


def _select_stepwise_candidate(
    candidates: Sequence[tuple[str, float, float]],
    minimum_improvement: float,
    tie_absolute_tolerance: float,
) -> tuple[str, float, float] | None:
    """Select a stable eligible candidate without letting tie tolerance weaken entry."""

    if not candidates:
        return None
    maximum_improvement = max(item[1] for item in candidates)
    if maximum_improvement < minimum_improvement:
        return None
    tied_eligible = [
        item
        for item in candidates
        if item[1] >= minimum_improvement
        and maximum_improvement - item[1] <= tie_absolute_tolerance
    ]
    return min(tied_eligible, key=lambda item: item[0].encode("ascii"))


def stepwise_rank_regression(
    response: Sequence[float] | np.ndarray,
    predictors: Mapping[str, Sequence[float] | np.ndarray],
    *,
    exclusions: Mapping[str, Mapping[str, Any] | str] | None = None,
    minimum_improvement: float = R2_ENTRY_THRESHOLD,
    tie_absolute_tolerance: float = R2_TIE_ABSOLUTE_TOLERANCE,
) -> dict[str, Any]:
    """Fit the approved deterministic Ho-style forward rank regression."""

    response_array = np.asarray(response, dtype=np.float64)
    if response_array.ndim != 1:
        raise TechnoeconomicValidationError("Sensitivity response must be one-dimensional.")
    if not math.isfinite(minimum_improvement) or minimum_improvement <= 0:
        raise TechnoeconomicValidationError("minimum_improvement must be finite and positive.")
    if not math.isfinite(tie_absolute_tolerance) or tie_absolute_tolerance < 0:
        raise TechnoeconomicValidationError("tie_absolute_tolerance must be finite and nonnegative.")

    normalized_predictors: dict[str, np.ndarray] = {}
    for identifier, values in predictors.items():
        _validate_stable_id(identifier, "Sensitivity predictor ID")
        vector = np.asarray(values, dtype=np.float64)
        if vector.ndim != 1 or len(vector) != len(response_array):
            raise TechnoeconomicValidationError(
                f"Sensitivity predictor {identifier!r} must be one-dimensional and match response length."
            )
        normalized_predictors[identifier] = vector

    exclusion_records: dict[str, dict[str, Any]] = {}
    for identifier, detail in (exclusions or {}).items():
        _validate_stable_id(identifier, "Sensitivity exclusion ID")
        if isinstance(detail, str):
            exclusion_records[identifier] = {"reason": detail}
        else:
            exclusion_records[identifier] = dict(detail)

    finite_mask = np.isfinite(response_array)
    for vector in normalized_predictors.values():
        finite_mask &= np.isfinite(vector)
    filtered_response = response_array[finite_mask]
    filtered_predictors = {
        identifier: vector[finite_mask]
        for identifier, vector in normalized_predictors.items()
    }
    sample_count = int(len(filtered_response))
    if sample_count < 2:
        return {
            "status": "unavailable",
            "reason": "insufficient_finite_observations",
            "sample_count": sample_count,
            "minimum_sample_count": 20,
            "steps": [],
            "exclusions": exclusion_records,
            "warnings": [],
            "final_r_squared": None,
        }

    ranked_response = _standardize_ranks(filtered_response)
    if ranked_response is None:
        return {
            "status": "unavailable",
            "reason": "constant_response",
            "sample_count": sample_count,
            "minimum_sample_count": 20,
            "steps": [],
            "exclusions": exclusion_records,
            "warnings": [],
            "final_r_squared": None,
        }

    ranked_predictors: dict[str, np.ndarray] = {}
    retained_rank_vectors: list[tuple[str, np.ndarray]] = []
    for identifier in sorted(filtered_predictors, key=lambda value: value.encode("ascii")):
        ranked = _standardize_ranks(filtered_predictors[identifier])
        if ranked is None:
            exclusion_records[identifier] = {"reason": "constant_predictor"}
            continue
        duplicate_of = next(
            (
                prior_id
                for prior_id, prior in retained_rank_vectors
                if np.array_equal(ranked, prior)
            ),
            None,
        )
        if duplicate_of is not None:
            exclusion_records[identifier] = {
                "reason": "duplicate_rank",
                "duplicate_of": duplicate_of,
            }
            continue
        retained_rank_vectors.append((identifier, ranked))
        ranked_predictors[identifier] = ranked

    predictor_count = len(ranked_predictors)
    minimum_sample_count = max(20, 2 * predictor_count + 2)
    if predictor_count == 0:
        return {
            "status": "unavailable",
            "reason": "no_usable_predictors",
            "sample_count": sample_count,
            "minimum_sample_count": minimum_sample_count,
            "steps": [],
            "exclusions": exclusion_records,
            "warnings": [],
            "final_r_squared": None,
        }
    if sample_count < minimum_sample_count:
        return {
            "status": "unavailable",
            "reason": "insufficient_observations",
            "sample_count": sample_count,
            "minimum_sample_count": minimum_sample_count,
            "steps": [],
            "exclusions": exclusion_records,
            "warnings": [],
            "final_r_squared": None,
        }

    warnings: list[dict[str, Any]] = []
    predictor_ids = sorted(ranked_predictors, key=lambda value: value.encode("ascii"))
    for left_index, left_id in enumerate(predictor_ids):
        for right_id in predictor_ids[left_index + 1 :]:
            correlation = float(
                np.corrcoef(ranked_predictors[left_id], ranked_predictors[right_id])[0, 1]
            )
            if math.isfinite(correlation) and abs(correlation) > HIGH_RANK_CORRELATION_WARNING:
                warnings.append(
                    {
                        "code": "high_pairwise_rank_correlation",
                        "left_predictor": left_id,
                        "right_predictor": right_id,
                        "correlation": correlation,
                    }
                )

    selected: list[str] = []
    remaining = set(predictor_ids)
    current_r_squared = 0.0
    steps: list[dict[str, Any]] = []
    while remaining:
        if sample_count - (len(selected) + 2) < 1:
            for identifier in sorted(remaining):
                exclusion_records[identifier] = {"reason": "insufficient_residual_degrees_of_freedom"}
            break
        candidates: list[tuple[str, float, float]] = []
        newly_singular: list[str] = []
        for identifier in sorted(remaining, key=lambda value: value.encode("ascii")):
            columns = [ranked_predictors[value] for value in selected] + [ranked_predictors[identifier]]
            try:
                candidate_r_squared, _, _ = _fit_rank_model(ranked_response, columns)
            except (np.linalg.LinAlgError, FloatingPointError, ValueError):
                newly_singular.append(identifier)
                continue
            improvement = max(0.0, candidate_r_squared - current_r_squared)
            candidates.append((identifier, improvement, candidate_r_squared))
        for identifier in newly_singular:
            remaining.remove(identifier)
            exclusion_records[identifier] = {"reason": "rank_singular"}
        if not candidates:
            break
        chosen = _select_stepwise_candidate(
            candidates,
            minimum_improvement,
            tie_absolute_tolerance,
        )
        if chosen is None:
            for identifier in sorted(remaining):
                exclusion_records.setdefault(identifier, {"reason": "below_entry_threshold"})
            break
        chosen_id, improvement, new_r_squared = chosen
        selected.append(chosen_id)
        remaining.remove(chosen_id)
        current_r_squared = new_r_squared
        steps.append(
            {
                "entry_order": len(selected),
                "predictor_id": chosen_id,
                "incremental_r_squared": float(improvement),
                "cumulative_r_squared": float(current_r_squared),
                "standardized_beta": None,
                "sign": None,
            }
        )

    final_r_squared = 0.0
    if selected:
        try:
            final_r_squared, final_coefficients, _ = _fit_rank_model(
                ranked_response,
                [ranked_predictors[identifier] for identifier in selected],
            )
        except (np.linalg.LinAlgError, FloatingPointError, ValueError):
            return {
                "status": "unavailable",
                "reason": "final_rank_singular",
                "sample_count": sample_count,
                "minimum_sample_count": minimum_sample_count,
                "steps": [],
                "exclusions": exclusion_records,
                "warnings": warnings,
                "final_r_squared": None,
            }
        for index, step in enumerate(steps, start=1):
            beta = float(final_coefficients[index])
            step["standardized_beta"] = beta
            step["sign"] = "positive" if beta > 0 else "negative" if beta < 0 else "zero"

    return {
        "status": "available",
        "reason": None,
        "sample_count": sample_count,
        "minimum_sample_count": minimum_sample_count,
        "candidate_predictor_count": predictor_count,
        "entered_predictor_count": len(selected),
        "steps": steps,
        "exclusions": {
            identifier: exclusion_records[identifier]
            for identifier in sorted(exclusion_records)
        },
        "warnings": warnings,
        "final_r_squared": float(final_r_squared),
        "minimum_entry_improvement": float(minimum_improvement),
        "r_squared_tie_absolute_tolerance": float(tie_absolute_tolerance),
    }


def convergence_checkpoints(n: int) -> tuple[int, ...]:
    """Return canonical ascending unique cumulative realization checkpoints."""

    n, _ = _validate_n_seed(n, 0)
    candidates = {
        min(n, 20),
        (n + 9) // 10,
        (n + 3) // 4,
        (n + 1) // 2,
        (3 * n + 3) // 4,
        n,
    }
    return tuple(sorted(max(1, min(n, value)) for value in candidates))


def _category_probabilities(values: np.ndarray, categories: Sequence[str]) -> dict[str, float]:
    counts = Counter(str(value) for value in values)
    denominator = len(values)
    return {
        category: (counts.get(category, 0) / denominator if denominator else 0.0)
        for category in categories
    }


def convergence_diagnostics(
    metrics: Mapping[str, Sequence[float] | np.ndarray],
    metric_absolute_tolerances: Mapping[str, float],
    weather_years: Sequence[int] | np.ndarray,
    eligible_years: Sequence[int],
    *,
    energy_classes: Sequence[str] | np.ndarray | None = None,
    tradeoff_classes: Sequence[str] | np.ndarray | None = None,
) -> dict[str, Any]:
    """Evaluate deterministic prefix convergence evidence for applicable metrics."""

    weather = np.asarray(weather_years)
    if weather.ndim != 1 or len(weather) == 0:
        raise TechnoeconomicValidationError("Convergence weather years must be a nonempty vector.")
    n = len(weather)
    normalized_metrics: dict[str, np.ndarray] = {}
    for name, values in metrics.items():
        vector = np.asarray(values, dtype=np.float64)
        if vector.ndim != 1 or len(vector) != n:
            raise TechnoeconomicValidationError(
                f"Convergence metric {name!r} must be one-dimensional and match row count."
            )
        tolerance = _finite_float(metric_absolute_tolerances.get(name), f"{name} absolute tolerance")
        if tolerance <= 0:
            raise TechnoeconomicValidationError("Convergence absolute tolerances must be positive.")
        normalized_metrics[name] = vector
    if not normalized_metrics:
        raise TechnoeconomicValidationError("At least one applicable convergence metric is required.")

    eligible: list[int] = []
    for year in eligible_years:
        if not _is_int(year):
            raise TechnoeconomicValidationError("Eligible convergence years must be integers.")
        eligible.append(int(year))
    if len(set(eligible)) != len(eligible) or not eligible:
        raise TechnoeconomicValidationError("Eligible convergence years must be nonempty and unique.")
    eligible.sort()
    if any(not _is_int(value) for value in weather.tolist()):
        raise TechnoeconomicValidationError("Assigned convergence weather years must be integers.")
    weather = weather.astype(np.int64, copy=False)
    unexpected_years = sorted(set(weather.tolist()) - set(eligible))
    if unexpected_years:
        raise TechnoeconomicValidationError(
            f"Assigned weather years are not eligible: {unexpected_years}."
        )

    energy_array = None if energy_classes is None else np.asarray(energy_classes, dtype=object)
    tradeoff_array = None if tradeoff_classes is None else np.asarray(tradeoff_classes, dtype=object)
    for label, vector in (("energy classes", energy_array), ("tradeoff classes", tradeoff_array)):
        if vector is not None and (vector.ndim != 1 or len(vector) != n):
            raise TechnoeconomicValidationError(
                f"Convergence {label} must be one-dimensional and match row count."
            )
    if energy_array is not None:
        unexpected = sorted(set(str(value) for value in energy_array) - set(ENERGY_CLASSES))
        if unexpected:
            raise TechnoeconomicValidationError(
                f"Unsupported convergence energy classes: {unexpected}."
            )
    if tradeoff_array is not None:
        unexpected = sorted(set(str(value) for value in tradeoff_array) - set(TRADEOFF_CLASSES))
        if unexpected:
            raise TechnoeconomicValidationError(
                f"Unsupported convergence tradeoff classes: {unexpected}."
            )

    checkpoint_rows: list[dict[str, Any]] = []
    previous_metric_percentiles: dict[str, dict[str, float | None]] | None = None
    for checkpoint in convergence_checkpoints(n):
        metric_rows: dict[str, Any] = {}
        current_percentiles: dict[str, dict[str, float | None]] = {}
        for name in sorted(normalized_metrics):
            population = normalized_metrics[name][:checkpoint]
            finite = population[np.isfinite(population)]
            if len(finite):
                percentile_values: dict[str, float | None] = type7_percentiles(finite)
            else:
                percentile_values = {"p5": None, "p50": None, "p95": None}
            current_percentiles[name] = percentile_values
            changes: dict[str, Any] = {}
            for quantile in ("p5", "p50", "p95"):
                old = None if previous_metric_percentiles is None else previous_metric_percentiles[name][quantile]
                new = percentile_values[quantile]
                if old is None or new is None:
                    changes[quantile] = {"absolute": None, "relative": None}
                    continue
                absolute = abs(float(new) - float(old))
                denominator = max(abs(float(new)), abs(float(old)))
                changes[quantile] = {
                    "absolute": absolute,
                    "relative": absolute / denominator if denominator > 0 else None,
                }
            metric_rows[name] = {
                "population_count": int(len(finite)),
                "percentiles": percentile_values,
                "change_from_previous": changes,
            }
        year_counts = {year: int(np.count_nonzero(weather[:checkpoint] == year)) for year in eligible}
        checkpoint_rows.append(
            {
                "realization_count": checkpoint,
                "metrics": metric_rows,
                "energy_class_probabilities": (
                    None
                    if energy_array is None
                    else _category_probabilities(energy_array[:checkpoint], ENERGY_CLASSES)
                ),
                "tradeoff_probabilities": (
                    None
                    if tradeoff_array is None
                    else _category_probabilities(tradeoff_array[:checkpoint], TRADEOFF_CLASSES)
                ),
                "weather_year_counts": year_counts,
                "weather_year_shares": {
                    year: count / checkpoint for year, count in year_counts.items()
                },
            }
        )
        previous_metric_percentiles = current_percentiles

    reasons: list[str] = []
    if len(checkpoint_rows) < 2:
        reasons.append("insufficient_unique_checkpoints")
    else:
        prior = checkpoint_rows[-2]
        final = checkpoint_rows[-1]
        for name in sorted(normalized_metrics):
            tolerance = float(metric_absolute_tolerances[name])
            for quantile in ("p5", "p50", "p95"):
                old = prior["metrics"][name]["percentiles"][quantile]
                new = final["metrics"][name]["percentiles"][quantile]
                if old is None or new is None:
                    reasons.append(f"undefined_quantile:{name}:{quantile}")
                    continue
                absolute = abs(float(new) - float(old))
                scale = max(abs(float(new)), abs(float(old)))
                if scale >= 100.0 * tolerance:
                    relative = absolute / scale
                    if relative > 0.01:
                        reasons.append(f"relative_quantile_change:{name}:{quantile}")
                elif absolute > tolerance:
                    reasons.append(f"absolute_quantile_change:{name}:{quantile}")
        for key, categories in (
            ("energy_class_probabilities", ENERGY_CLASSES),
            ("tradeoff_probabilities", TRADEOFF_CLASSES),
        ):
            if prior[key] is None:
                continue
            for category in categories:
                if abs(final[key][category] - prior[key][category]) > 0.001:
                    reasons.append(f"class_probability_change:{category}")
        for year in eligible:
            if prior["weather_year_counts"][year] == 0 or final["weather_year_counts"][year] == 0:
                reasons.append(f"weather_year_unrepresented:{year}")

    reasons = sorted(set(reasons))
    return {
        "status": "stable" if not reasons else "not_demonstrated",
        "reasons": reasons,
        "checkpoints": checkpoint_rows,
        "relative_change_threshold": 0.01,
        "class_probability_change_threshold": 0.001,
        "metric_absolute_tolerances": {
            name: float(metric_absolute_tolerances[name])
            for name in sorted(normalized_metrics)
        },
    }


def _classify_outcomes(
    pv_cost_sol: np.ndarray,
    pv_cost_se: np.ndarray,
    pv_energy_sol: np.ndarray,
    pv_energy_se: np.ndarray,
    *,
    delta_cost: np.ndarray | None = None,
    delta_energy: np.ndarray | None = None,
) -> dict[str, np.ndarray]:
    if delta_cost is None:
        delta_cost = pv_cost_se - pv_cost_sol
    else:
        delta_cost = np.asarray(delta_cost, dtype=np.float64)
    if delta_energy is None:
        delta_energy = pv_energy_se - pv_energy_sol
    else:
        delta_energy = np.asarray(delta_energy, dtype=np.float64)
    cost_tolerance = np.maximum(
        1e-12,
        1e-12 * np.maximum(np.abs(pv_cost_se), np.abs(pv_cost_sol)),
    )
    energy_tolerance = np.maximum(
        1e-9,
        1e-12 * np.maximum(np.abs(pv_energy_se), np.abs(pv_energy_sol)),
    )
    cost_class = np.where(
        delta_cost > cost_tolerance,
        "cost_increase",
        np.where(delta_cost < -cost_tolerance, "cost_saving", "cost_neutral"),
    ).astype(object)
    energy_class = np.where(
        delta_energy > energy_tolerance,
        "positive_lifecycle_gain",
        np.where(
            delta_energy < -energy_tolerance,
            "negative_lifecycle_gain",
            "zero_lifecycle_gain",
        ),
    ).astype(object)
    suffix = {
        "positive_lifecycle_gain": "energy_gain",
        "negative_lifecycle_gain": "energy_loss",
        "zero_lifecycle_gain": "zero_energy_change",
    }
    tradeoff = np.asarray(
        [f"{cost}_{suffix[str(energy)]}" for cost, energy in zip(cost_class, energy_class)],
        dtype=object,
    )
    lcoo = np.full(len(delta_energy), np.nan, dtype=np.float64)
    nonzero = energy_class != "zero_lifecycle_gain"
    with np.errstate(over="ignore", divide="ignore", invalid="ignore"):
        lcoo[nonzero] = delta_cost[nonzero] / delta_energy[nonzero]
    reason = np.where(
        nonzero,
        None,
        "zero_lifecycle_delta_energy",
    ).astype(object)
    return {
        "delta_cost": delta_cost,
        "delta_energy": delta_energy,
        "cost_tolerance": cost_tolerance,
        "energy_tolerance": energy_tolerance,
        "cost_class": cost_class,
        "energy_class": energy_class,
        "tradeoff_class": tradeoff,
        "lcoo": lcoo,
        "lcoo_reason": reason,
    }


def _build_common_cost_audit(
    lines: Sequence[CostLineSpec],
    samples: Mapping[str, np.ndarray],
    *,
    applied_capacity_normalization: bool = False,
) -> tuple[Mapping[str, Any], ...]:
    rows: list[Mapping[str, Any]] = []
    for line in lines:
        if line.ownership != "paired_shared":
            continue
        treatment, reasons = _common_treatment(line)
        values = samples[line.input_id]
        sol = values * line.solectria_multiplier_to_intensity
        if treatment == "common_cancelled":
            se = sol.copy()
            delta = np.zeros(len(values), dtype=np.float64)
        else:
            se = values * line.solaredge_multiplier_to_intensity
            delta = se - sol
        rows.append(
            {
                "input_id": line.input_id,
                "label": line.label,
                "cost_type": line.cost_type,
                "comparison_treatment": treatment,
                "reasons": list(reasons),
                "solectria_multiplier_to_intensity": line.solectria_multiplier_to_intensity,
                "solaredge_multiplier_to_intensity": line.solaredge_multiplier_to_intensity,
                "solectria_treatment_key": line.solectria_treatment_key,
                "solaredge_treatment_key": line.solaredge_treatment_key,
                "solectria_contribution_min": float(np.min(sol)),
                "solectria_contribution_max": float(np.max(sol)),
                "solaredge_contribution_min": float(np.min(se)),
                "solaredge_contribution_max": float(np.max(se)),
                "contribution_units": (
                    (
                        "USD_per_applied_W"
                        if applied_capacity_normalization
                        else "USD_per_Wdc"
                    )
                    if line.cost_type in INITIAL_COST_TYPES
                    else (
                        "USD_per_applied_W_year"
                        if applied_capacity_normalization
                        else "USD_per_Wdc_year"
                    )
                ),
                "delta_contribution_min_se_minus_sol": float(np.min(delta)),
                "delta_contribution_max_se_minus_sol": float(np.max(delta)),
                "delta_contribution_se_minus_sol_exactly_zero": bool(
                    np.all(delta == 0.0)
                ),
            }
        )
    return tuple(rows)


def _cost_arrays(
    request: TechnoeconomicRequest,
    samples: Mapping[str, np.ndarray],
) -> dict[str, np.ndarray]:
    arrays = {
        "initial_sol": np.zeros(request.n, dtype=np.float64),
        "initial_se": np.zeros(request.n, dtype=np.float64),
        "recurring_sol": np.zeros(request.n, dtype=np.float64),
        "recurring_se": np.zeros(request.n, dtype=np.float64),
        "initial_delta": np.zeros(request.n, dtype=np.float64),
        "recurring_delta": np.zeros(request.n, dtype=np.float64),
    }
    for line in request.cost_lines:
        values = samples[line.input_id]
        with np.errstate(over="ignore", invalid="ignore"):
            sol = values * line.solectria_multiplier_to_intensity
            if _common_treatment(line)[0] == "common_cancelled":
                se = sol
            else:
                se = values * line.solaredge_multiplier_to_intensity
            prefix = "initial" if line.cost_type in INITIAL_COST_TYPES else "recurring"
            arrays[f"{prefix}_sol"] += sol
            arrays[f"{prefix}_se"] += se
            if _common_treatment(line)[0] != "common_cancelled":
                arrays[f"{prefix}_delta"] += se - sol
    system_total_names = ("initial_sol", "initial_se", "recurring_sol", "recurring_se")
    if not all(
        np.isfinite(arrays[name]).all() and np.all(arrays[name] >= 0)
        for name in system_total_names
    ) or not all(
        np.isfinite(arrays[name]).all()
        for name in ("initial_delta", "recurring_delta")
    ):
        raise TechnoeconomicInvariantError("Validated costs produced nonfinite or negative intensities.")
    return arrays


def _standalone_commercial_cost_arrays(
    spec: StandaloneCommercialSpec,
    samples: Mapping[str, np.ndarray],
    discount_rates: np.ndarray,
    annuity_factor: np.ndarray,
    crf: np.ndarray,
) -> dict[str, np.ndarray]:
    """Return target-total standalone SolarEdge lifecycle cost arrays."""

    n = len(discount_rates)
    arrays = {
        "initial": np.zeros(n, dtype=np.float64),
        "recurring_pv": np.zeros(n, dtype=np.float64),
        "scheduled_pv": np.zeros(n, dtype=np.float64),
    }
    for line in spec.cost_lines:
        target_total = samples[line.input_id] * spec.target_capacity_w
        with np.errstate(over="ignore", invalid="ignore"):
            if line.timing == "initial_t0":
                arrays["initial"] += target_total
            elif line.timing == "annual_year_end":
                arrays["recurring_pv"] += target_total * annuity_factor
            else:
                discount_sum = np.zeros(n, dtype=np.float64)
                for year in line.occurrence_years:
                    discount_sum += np.asarray(
                        _scheduled_discount_factor(discount_rates, year),
                        dtype=np.float64,
                    )
                arrays["scheduled_pv"] += target_total * discount_sum
    arrays["lifecycle"] = (
        arrays["initial"] + arrays["recurring_pv"] + arrays["scheduled_pv"]
    )
    arrays["equivalent_annual"] = crf * arrays["lifecycle"]
    if not all(
        np.isfinite(values).all() and np.all(values >= 0)
        for values in arrays.values()
    ):
        raise TechnoeconomicInvariantError(
            "Validated standalone commercial costs produced nonfinite or negative "
            "totals."
        )
    return arrays


def _require_finite_arrays(label: str, arrays: Mapping[str, np.ndarray]) -> None:
    failures = [name for name, values in arrays.items() if not np.isfinite(values).all()]
    if failures:
        raise TechnoeconomicInvariantError(
            f"{label} produced nonfinite values in: {', '.join(sorted(failures))}."
        )


def _site_raw_lifecycle_cost_delta(
    request: TechnoeconomicRequest,
    samples: Mapping[str, np.ndarray],
    annuity_factor: np.ndarray,
    normalization_capacities_w: Mapping[SystemName, float],
) -> np.ndarray:
    """Accumulate raw SE-minus-SOL site cost without subtracting huge totals."""

    initial_delta = np.zeros(request.n, dtype=np.float64)
    recurring_delta = np.zeros(request.n, dtype=np.float64)
    sol_applied_w = normalization_capacities_w["solectria"]
    se_applied_w = normalization_capacities_w["solaredge"]
    with np.errstate(over="ignore", invalid="ignore"):
        for line in request.cost_lines:
            values = samples[line.input_id]
            sol_normalized = values * line.solectria_multiplier_to_intensity
            if _common_treatment(line)[0] == "common_cancelled":
                se_normalized = sol_normalized
            else:
                se_normalized = values * line.solaredge_multiplier_to_intensity
            if (
                _common_treatment(line)[0] == "common_cancelled"
                and sol_applied_w == se_applied_w
            ):
                contribution_delta = np.zeros(request.n, dtype=np.float64)
            else:
                contribution_delta = (
                    se_normalized * se_applied_w
                    - sol_normalized * sol_applied_w
                )
            if line.cost_type in INITIAL_COST_TYPES:
                initial_delta += contribution_delta
            else:
                recurring_delta += contribution_delta
        result = initial_delta + recurring_delta * annuity_factor
    _require_finite_arrays("SolarTAC raw cost delta", {"delta": result})
    return result


def _summaries_from_table(
    table: Mapping[str, np.ndarray],
    energy_available: bool,
    fields: _MetricFields = LEGACY_METRIC_FIELDS,
    *,
    standalone_commercial: bool = False,
    paired_commercial: bool = False,
) -> dict[str, Any]:
    if paired_commercial:
        metric_fields = (
            COMMERCIAL_PAIRED_SOLECTRIA_FIELD_TARGET_CAPACITY,
            COMMERCIAL_PAIRED_SOLECTRIA_FIELD_CAPACITY_SCALE_FACTOR,
            COMMERCIAL_PAIRED_SOLECTRIA_FIELD_YEAR1_ENERGY,
            COMMERCIAL_PAIRED_SOLECTRIA_FIELD_LIFECYCLE_ENERGY,
            COMMERCIAL_PAIRED_SOLECTRIA_FIELD_EA_ENERGY,
            COMMERCIAL_PAIRED_SOLECTRIA_FIELD_INITIAL_COST,
            COMMERCIAL_PAIRED_SOLECTRIA_FIELD_RECURRING_PV_COST,
            COMMERCIAL_PAIRED_SOLECTRIA_FIELD_SCHEDULED_PV_COST,
            COMMERCIAL_PAIRED_SOLECTRIA_FIELD_LIFECYCLE_COST,
            COMMERCIAL_PAIRED_SOLECTRIA_FIELD_EA_COST,
            COMMERCIAL_PAIRED_SOLECTRIA_FIELD_LCOE,
            COMMERCIAL_STANDALONE_FIELD_TARGET_CAPACITY,
            COMMERCIAL_STANDALONE_FIELD_CAPACITY_SCALE_FACTOR,
            COMMERCIAL_STANDALONE_FIELD_YEAR1_ENERGY,
            COMMERCIAL_STANDALONE_FIELD_LIFECYCLE_ENERGY,
            COMMERCIAL_STANDALONE_FIELD_EA_ENERGY,
            COMMERCIAL_STANDALONE_FIELD_INITIAL_COST,
            COMMERCIAL_STANDALONE_FIELD_RECURRING_PV_COST,
            COMMERCIAL_STANDALONE_FIELD_SCHEDULED_PV_COST,
            COMMERCIAL_STANDALONE_FIELD_LIFECYCLE_COST,
            COMMERCIAL_STANDALONE_FIELD_EA_COST,
            COMMERCIAL_STANDALONE_FIELD_LCOE,
            COMMERCIAL_PAIRED_FIELD_LCOE_DELTA,
        )
        return {
            field_name: _commercial_v4_metric_summary(table[field_name])
            for field_name in metric_fields
        }
    if standalone_commercial:
        metric_fields = (
            COMMERCIAL_STANDALONE_FIELD_TARGET_CAPACITY,
            COMMERCIAL_STANDALONE_FIELD_CAPACITY_SCALE_FACTOR,
            COMMERCIAL_STANDALONE_FIELD_YEAR1_ENERGY,
            COMMERCIAL_STANDALONE_FIELD_LIFECYCLE_ENERGY,
            COMMERCIAL_STANDALONE_FIELD_EA_ENERGY,
            COMMERCIAL_STANDALONE_FIELD_INITIAL_COST,
            COMMERCIAL_STANDALONE_FIELD_RECURRING_PV_COST,
            COMMERCIAL_STANDALONE_FIELD_SCHEDULED_PV_COST,
            COMMERCIAL_STANDALONE_FIELD_LIFECYCLE_COST,
            COMMERCIAL_STANDALONE_FIELD_EA_COST,
            COMMERCIAL_STANDALONE_FIELD_LCOE,
        )
        return {
            field_name: _commercial_v4_metric_summary(table[field_name])
            for field_name in metric_fields
        }
    summaries: dict[str, Any] = {
        fields.delta_cost: _metric_summary(table[fields.delta_cost]),
        fields.delta_ea_cost: _metric_summary(table[fields.delta_ea_cost]),
    }
    energy_fields = (
        fields.lcoe_sol,
        fields.lcoe_se,
        fields.delta_energy,
        fields.delta_ea_energy,
    )
    if energy_available:
        for field_name in energy_fields:
            summaries[field_name] = _metric_summary(table[field_name])
        positive = table["energy_class"] == "positive_lifecycle_gain"
        summaries["headline_positive_gain_lcoo"] = _metric_summary(
            table[fields.lcoo][positive],
            empty_reason="no_positive_lifecycle_gain",
        )
        summaries["signed_nonzero_lcoo"] = _metric_summary(
            table[fields.lcoo][np.isfinite(table[fields.lcoo])],
            empty_reason="no_nonzero_lifecycle_energy",
        )
        energy_counts = Counter(str(value) for value in table["energy_class"])
        tradeoff_counts = Counter(str(value) for value in table["tradeoff_class"])
        summaries["energy_classes"] = {
            "denominator": len(table["energy_class"]),
            "counts": {name: energy_counts.get(name, 0) for name in ENERGY_CLASSES},
            "probabilities": _category_probabilities(table["energy_class"], ENERGY_CLASSES),
        }
        summaries["tradeoff_classes"] = {
            "denominator": len(table["tradeoff_class"]),
            "counts": {name: tradeoff_counts.get(name, 0) for name in TRADEOFF_CLASSES},
            "probabilities": _category_probabilities(table["tradeoff_class"], TRADEOFF_CLASSES),
        }
    else:
        unavailable = {
            "status": "unavailable",
            "reason": "commercial_energy_transfer_unavailable",
            "count": 0,
            "percentiles": {"p5": None, "p50": None, "p95": None},
            "cdf": None,
        }
        for field_name in energy_fields:
            summaries[field_name] = dict(unavailable)
        summaries["headline_positive_gain_lcoo"] = dict(unavailable)
        summaries["signed_nonzero_lcoo"] = dict(unavailable)
        summaries["energy_classes"] = {
            "status": "unavailable",
            "reason": "commercial_energy_transfer_unavailable",
        }
        summaries["tradeoff_classes"] = {
            "status": "unavailable",
            "reason": "commercial_energy_transfer_unavailable",
        }
    if COMMERCIAL_FIELD_TARGET_CAPACITY in table:
        commercial_metric_fields = (
            COMMERCIAL_FIELD_TARGET_CAPACITY,
            COMMERCIAL_FIELD_YEAR1_DELTA_ENERGY,
            COMMERCIAL_FIELD_LIFECYCLE_DELTA_ENERGY,
            COMMERCIAL_FIELD_EA_DELTA_ENERGY,
            COMMERCIAL_FIELD_LIFECYCLE_MARGINAL_COST,
            COMMERCIAL_FIELD_EA_MARGINAL_COST,
        )
        for field_name in commercial_metric_fields:
            summaries[field_name] = _metric_summary(table[field_name])
        summaries[COMMERCIAL_FIELD_MARGINAL_LCOO] = _metric_summary(
            table[COMMERCIAL_FIELD_MARGINAL_LCOO][
                np.isfinite(table[COMMERCIAL_FIELD_MARGINAL_LCOO])
            ],
            empty_reason=COMMERCIAL_ZERO_ENERGY_REASON,
        )
    return summaries


def _per_weather_year_summaries(
    request: TechnoeconomicRequest,
    table: Mapping[str, np.ndarray],
    capacity_map: Mapping[SystemName, CapacitySpec],
    normalization_capacities_w: Mapping[SystemName, float],
    energy_available: bool,
    fields: _MetricFields = LEGACY_METRIC_FIELDS,
) -> tuple[Mapping[str, Any], ...]:
    if request.paired_commercial is not None:
        paired_spec = request.paired_commercial
        applied_map = {
            capacity.system: capacity
            for capacity in (request.applied_capacities or ())
        }
        paired_metric_names = (
            COMMERCIAL_PAIRED_SOLECTRIA_FIELD_CAPACITY_SCALE_FACTOR,
            COMMERCIAL_PAIRED_SOLECTRIA_FIELD_YEAR1_ENERGY,
            COMMERCIAL_PAIRED_SOLECTRIA_FIELD_LIFECYCLE_ENERGY,
            COMMERCIAL_PAIRED_SOLECTRIA_FIELD_EA_ENERGY,
            COMMERCIAL_PAIRED_SOLECTRIA_FIELD_INITIAL_COST,
            COMMERCIAL_PAIRED_SOLECTRIA_FIELD_RECURRING_PV_COST,
            COMMERCIAL_PAIRED_SOLECTRIA_FIELD_SCHEDULED_PV_COST,
            COMMERCIAL_PAIRED_SOLECTRIA_FIELD_LIFECYCLE_COST,
            COMMERCIAL_PAIRED_SOLECTRIA_FIELD_EA_COST,
            COMMERCIAL_PAIRED_SOLECTRIA_FIELD_LCOE,
            COMMERCIAL_STANDALONE_FIELD_CAPACITY_SCALE_FACTOR,
            COMMERCIAL_STANDALONE_FIELD_YEAR1_ENERGY,
            COMMERCIAL_STANDALONE_FIELD_LIFECYCLE_ENERGY,
            COMMERCIAL_STANDALONE_FIELD_EA_ENERGY,
            COMMERCIAL_STANDALONE_FIELD_INITIAL_COST,
            COMMERCIAL_STANDALONE_FIELD_RECURRING_PV_COST,
            COMMERCIAL_STANDALONE_FIELD_SCHEDULED_PV_COST,
            COMMERCIAL_STANDALONE_FIELD_LIFECYCLE_COST,
            COMMERCIAL_STANDALONE_FIELD_EA_COST,
            COMMERCIAL_STANDALONE_FIELD_LCOE,
            COMMERCIAL_PAIRED_FIELD_LCOE_DELTA,
        )
        paired_results: list[Mapping[str, Any]] = []
        for source_row in request.paired_energy_rows:
            mask = table["weather_year"] == source_row.year
            count = int(np.count_nonzero(mask))
            no_rows = count == 0
            systems: dict[SystemName, Mapping[str, Any]] = {}
            for technology, source_energy in (
                ("solectria", source_row.sol_predicted_kwh_ac),
                ("solaredge", source_row.se_predicted_kwh_ac),
            ):
                source_capacity_w = normalization_capacities_w[technology]
                systems[technology] = {
                    "source_predicted_kwh_ac": source_energy,
                    "installed_wdc": capacity_map[technology].installed_wdc,
                    "source_applied_capacity_w": source_capacity_w,
                    "source_rating_basis": applied_map[technology].rating_basis,
                    "source_specific_kwh_ac_per_applied_w_year": (
                        source_energy / source_capacity_w
                    ),
                    "capacity_scale_factor_target_w_per_source_w": (
                        paired_spec.target_capacity_w / source_capacity_w
                    ),
                    "target_year1_energy_kwh_ac": (
                        source_energy
                        / source_capacity_w
                        * paired_spec.target_capacity_w
                    ),
                }
            paired_results.append(
                {
                    "year": source_row.year,
                    "commercial_target_capacity_w": paired_spec.target_capacity_w,
                    "commercial_target_rating_basis": (
                        paired_spec.target_rating_basis
                    ),
                    "commercial_transfer_method": paired_spec.transfer_method,
                    "systems": systems,
                    "realization_count": count,
                    "realization_share": count / request.n,
                    "reason": "no_realizations_assigned" if no_rows else None,
                    "metrics": {
                        field_name: _commercial_v4_metric_summary(
                            table[field_name][mask],
                            empty_reason=(
                                "no_realizations_assigned"
                                if no_rows
                                else "no_finite_values"
                            ),
                            include_cdf=False,
                        )
                        for field_name in paired_metric_names
                    },
                }
            )
        return tuple(paired_results)
    if request.standalone_commercial is not None:
        standalone_spec = request.standalone_commercial
        se_normalization_w = normalization_capacities_w["solaredge"]
        applied_map = {
            capacity.system: capacity
            for capacity in (request.applied_capacities or ())
        }
        source_rating_basis = applied_map["solaredge"].rating_basis
        standalone_metric_names = (
            COMMERCIAL_STANDALONE_FIELD_CAPACITY_SCALE_FACTOR,
            COMMERCIAL_STANDALONE_FIELD_YEAR1_ENERGY,
            COMMERCIAL_STANDALONE_FIELD_LIFECYCLE_ENERGY,
            COMMERCIAL_STANDALONE_FIELD_EA_ENERGY,
            COMMERCIAL_STANDALONE_FIELD_INITIAL_COST,
            COMMERCIAL_STANDALONE_FIELD_RECURRING_PV_COST,
            COMMERCIAL_STANDALONE_FIELD_SCHEDULED_PV_COST,
            COMMERCIAL_STANDALONE_FIELD_LIFECYCLE_COST,
            COMMERCIAL_STANDALONE_FIELD_EA_COST,
            COMMERCIAL_STANDALONE_FIELD_LCOE,
        )
        standalone_results: list[Mapping[str, Any]] = []
        for source_row in request.paired_energy_rows:
            mask = table["weather_year"] == source_row.year
            count = int(np.count_nonzero(mask))
            no_rows = count == 0
            standalone_results.append(
                {
                    "year": source_row.year,
                    "source_se_predicted_kwh_ac": source_row.se_predicted_kwh_ac,
                    "solaredge_installed_wdc": capacity_map[
                        "solaredge"
                    ].installed_wdc,
                    "solaredge_applied_w": se_normalization_w,
                    "solaredge_source_rating_basis": source_rating_basis,
                    "source_se_specific_kwh_ac_per_applied_w_year": (
                        source_row.se_predicted_kwh_ac / se_normalization_w
                    ),
                    "commercial_target_capacity_w": (
                        standalone_spec.target_capacity_w
                    ),
                    "commercial_capacity_scale_factor_target_w_per_source_w": (
                        standalone_spec.target_capacity_w / se_normalization_w
                    ),
                    "commercial_target_rating_basis": (
                        standalone_spec.target_rating_basis
                    ),
                    "commercial_transfer_method": standalone_spec.transfer_method,
                    "commercial_source_year1_energy_solaredge_kwh_ac": (
                        source_row.se_predicted_kwh_ac
                        / se_normalization_w
                        * standalone_spec.target_capacity_w
                    ),
                    "realization_count": count,
                    "realization_share": count / request.n,
                    "reason": "no_realizations_assigned" if no_rows else None,
                    "metrics": {
                        field_name: _commercial_v4_metric_summary(
                            table[field_name][mask],
                            empty_reason=(
                                "no_realizations_assigned"
                                if no_rows
                                else "no_finite_values"
                            ),
                            include_cdf=False,
                        )
                        for field_name in standalone_metric_names
                    },
                }
            )
        return tuple(standalone_results)

    metric_names = (
        fields.lcoe_sol,
        fields.lcoe_se,
        fields.delta_cost,
        fields.delta_energy,
        fields.delta_ea_cost,
        fields.delta_ea_energy,
    )
    if request.commercial_scaling is not None:
        metric_names += (
            COMMERCIAL_FIELD_YEAR1_DELTA_ENERGY,
            COMMERCIAL_FIELD_LIFECYCLE_DELTA_ENERGY,
            COMMERCIAL_FIELD_EA_DELTA_ENERGY,
            COMMERCIAL_FIELD_LIFECYCLE_MARGINAL_COST,
            COMMERCIAL_FIELD_EA_MARGINAL_COST,
        )
    results: list[Mapping[str, Any]] = []
    for source_row in request.paired_energy_rows:
        mask = table["weather_year"] == source_row.year
        count = int(np.count_nonzero(mask))
        no_rows = count == 0
        applied = fields is APPLIED_METRIC_FIELDS
        sol_normalization_w = normalization_capacities_w["solectria"]
        se_normalization_w = normalization_capacities_w["solaredge"]
        row: dict[str, Any] = {
            "year": source_row.year,
            "source_sol_predicted_kwh_ac": source_row.sol_predicted_kwh_ac,
            "source_se_predicted_kwh_ac": source_row.se_predicted_kwh_ac,
            "solectria_installed_wdc": capacity_map["solectria"].installed_wdc,
            "solaredge_installed_wdc": capacity_map["solaredge"].installed_wdc,
            "realization_count": count,
            "realization_share": count / request.n,
            "reason": "no_realizations_assigned" if no_rows else None,
            "metrics": {},
        }
        if applied:
            row.update(
                {
                    "solectria_applied_w": sol_normalization_w,
                    "solaredge_applied_w": se_normalization_w,
                    "source_sol_specific_kwh_ac_per_applied_w_year": (
                        source_row.sol_predicted_kwh_ac / sol_normalization_w
                    ),
                    "source_se_specific_kwh_ac_per_applied_w_year": (
                        source_row.se_predicted_kwh_ac / se_normalization_w
                    ),
                    "source_delta_specific_se_minus_sol_kwh_ac_per_applied_w_year": (
                        source_row.se_predicted_kwh_ac / se_normalization_w
                        - source_row.sol_predicted_kwh_ac / sol_normalization_w
                    ),
                }
            )
            if request.commercial_scaling is not None:
                row.update(
                    {
                        "commercial_target_capacity_w": (
                            request.commercial_scaling.target_capacity_w
                        ),
                        "commercial_target_rating_basis": (
                            request.commercial_scaling.target_rating_basis
                        ),
                        "commercial_transfer_method": (
                            request.commercial_scaling.transfer_method
                        ),
                        "commercial_source_year1_delta_energy_se_minus_sol_kwh_ac": (
                            (
                                (source_row.se_predicted_kwh_ac - source_row.sol_predicted_kwh_ac)
                                / se_normalization_w
                                if sol_normalization_w == se_normalization_w
                                else (
                                    source_row.se_predicted_kwh_ac / se_normalization_w
                                    - source_row.sol_predicted_kwh_ac / sol_normalization_w
                                )
                            )
                            * request.commercial_scaling.target_capacity_w
                        ),
                    }
                )
        else:
            row.update(
                {
                    "source_sol_specific_kwh_ac_per_wdc_year": (
                        source_row.sol_predicted_kwh_ac / sol_normalization_w
                    ),
                    "source_se_specific_kwh_ac_per_wdc_year": (
                        source_row.se_predicted_kwh_ac / se_normalization_w
                    ),
                    "source_delta_specific_se_minus_sol_kwh_ac_per_wdc_year": (
                        source_row.se_predicted_kwh_ac / se_normalization_w
                        - source_row.sol_predicted_kwh_ac / sol_normalization_w
                    ),
                }
            )
        for field_name in metric_names:
            if field_name in {
                fields.lcoe_sol,
                fields.lcoe_se,
                fields.delta_energy,
                fields.delta_ea_energy,
            } and not energy_available:
                row["metrics"][field_name] = {
                    "status": "unavailable",
                    "reason": "commercial_energy_transfer_unavailable",
                    "count": 0,
                    "percentiles": {"p5": None, "p50": None, "p95": None},
                    "cdf": None,
                }
            else:
                row["metrics"][field_name] = _metric_summary(
                    table[field_name][mask],
                    empty_reason="no_realizations_assigned" if no_rows else "no_finite_values",
                    include_cdf=False,
                )
        if energy_available:
            positive = mask & (table["energy_class"] == "positive_lifecycle_gain")
            nonzero = mask & np.isfinite(table[fields.lcoo])
            row["metrics"]["headline_positive_gain_lcoo"] = _metric_summary(
                table[fields.lcoo][positive],
                empty_reason=(
                    "no_realizations_assigned" if no_rows else "no_positive_lifecycle_gain"
                ),
                include_cdf=False,
            )
            row["metrics"]["signed_nonzero_lcoo"] = _metric_summary(
                table[fields.lcoo][nonzero],
                empty_reason=(
                    "no_realizations_assigned" if no_rows else "no_nonzero_lifecycle_energy"
                ),
                include_cdf=False,
            )
            class_values = table["energy_class"][mask]
            row["energy_class_counts"] = {
                name: int(np.count_nonzero(class_values == name)) for name in ENERGY_CLASSES
            }
            row["energy_class_probabilities"] = (
                None if no_rows else _category_probabilities(class_values, ENERGY_CLASSES)
            )
            if request.commercial_scaling is not None:
                commercial_nonzero = mask & np.isfinite(
                    table[COMMERCIAL_FIELD_MARGINAL_LCOO]
                )
                row["metrics"][COMMERCIAL_FIELD_MARGINAL_LCOO] = _metric_summary(
                    table[COMMERCIAL_FIELD_MARGINAL_LCOO][commercial_nonzero],
                    empty_reason=(
                        "no_realizations_assigned"
                        if no_rows
                        else COMMERCIAL_ZERO_ENERGY_REASON
                    ),
                    include_cdf=False,
                )
        else:
            row["metrics"]["headline_positive_gain_lcoo"] = {
                "status": "unavailable",
                "reason": "commercial_energy_transfer_unavailable",
                "count": 0,
                "percentiles": {"p5": None, "p50": None, "p95": None},
                "cdf": None,
            }
            row["metrics"]["signed_nonzero_lcoo"] = dict(
                row["metrics"]["headline_positive_gain_lcoo"]
            )
            row["energy_class_counts"] = None
            row["energy_class_probabilities"] = None
        results.append(row)
    return tuple(results)


def _sensitivity_models(
    request: TechnoeconomicRequest,
    table: Mapping[str, np.ndarray],
    samples: Mapping[str, np.ndarray],
    common_treatments: Mapping[str, str],
    energy_available: bool,
    fields: _MetricFields = LEGACY_METRIC_FIELDS,
) -> dict[str, Any]:
    all_specs: dict[str, DistributionSpec] = {
        line.input_id: line.distribution for line in request.cost_lines
    }
    all_specs[request.discount_rate.input_id] = request.discount_rate
    all_specs[request.shared_degradation.input_id] = request.shared_degradation
    if request.transfer is not None:
        all_specs[request.transfer.baseline.input_id] = request.transfer.baseline
        all_specs[request.transfer.incremental.input_id] = request.transfer.incremental
    if request.commercial_scaling is not None:
        commercial_cost_id = (
            request.commercial_scaling.marginal_cost_difference.input_id
        )
        all_specs[commercial_cost_id] = (
            request.commercial_scaling.marginal_cost_difference
        )
    if request.standalone_commercial is not None:
        for line in request.standalone_commercial.cost_lines:
            all_specs[line.input_id] = line.distribution
    if request.paired_commercial is not None:
        for system in request.paired_commercial.systems:
            for line in system.cost_lines:
                all_specs[line.input_id] = line.distribution

    source_sol_id = "energy.source.solectria_specific"
    source_se_id = "energy.source.solaredge_specific"
    universe = set(all_specs) | {source_sol_id, source_se_id}
    predictors: dict[str, np.ndarray] = {
        identifier: samples[identifier] for identifier in all_specs
    }
    source_unit = "applied_W" if fields is APPLIED_METRIC_FIELDS else "Wdc"
    predictors[source_sol_id] = table[
        f"SourceYear1SpecificEnergy_SOL_kWh_AC_per_{source_unit}_year"
    ]
    predictors[source_se_id] = table[
        f"SourceYear1SpecificEnergy_SE_kWh_AC_per_{source_unit}_year"
    ]

    cost_sol = {
        line.input_id
        for line in request.cost_lines
        if line.ownership in {"solectria_only", "paired_shared"}
    }
    cost_se = {
        line.input_id
        for line in request.cost_lines
        if line.ownership in {"solaredge_only", "paired_shared"}
    }
    noncancelled_cost = {
        line.input_id
        for line in request.cost_lines
        if common_treatments.get(line.input_id) != "common_cancelled"
    }
    finance_id = request.discount_rate.input_id
    degradation_id = request.shared_degradation.input_id
    has_noncancelled_recurring_cost = any(
        line.cost_type in RECURRING_COST_TYPES
        and common_treatments.get(line.input_id) != "common_cancelled"
        for line in request.cost_lines
    )

    def has_positive_cost_support(system: SystemName, cost_types: frozenset[str]) -> bool:
        return any(
            system in _line_systems(line)
            and line.cost_type in cost_types
            and distribution_support(line.distribution)[1]
            * (
                line.solectria_multiplier_to_intensity
                if system == "solectria"
                else line.solaredge_multiplier_to_intensity
            )
            > 0
            for line in request.cost_lines
        )

    degradation_can_be_positive = (
        request.project_life_years > 1
        and distribution_support(request.shared_degradation)[1] > 0
    )
    sol_has_initial = has_positive_cost_support("solectria", INITIAL_COST_TYPES)
    se_has_initial = has_positive_cost_support("solaredge", INITIAL_COST_TYPES)
    sol_has_recurring = has_positive_cost_support("solectria", RECURRING_COST_TYPES)
    se_has_recurring = has_positive_cost_support("solaredge", RECURRING_COST_TYPES)

    lcoe_sol_set = cost_sol | {source_sol_id}
    lcoe_se_set = cost_se | {source_se_id}
    # With recurring-only constant-real costs and zero degradation, AF appears in
    # both cost and energy and cancels algebraically.  Finance has a standalone
    # LCOE path only through initial cost, or through recurring cost when a
    # multi-year degradation effect makes the two lifecycle factors differ.
    if sol_has_initial or (sol_has_recurring and degradation_can_be_positive):
        lcoe_sol_set.add(finance_id)
    if se_has_initial or (se_has_recurring and degradation_can_be_positive):
        lcoe_se_set.add(finance_id)
    if request.project_life_years > 1 and (sol_has_initial or sol_has_recurring):
        lcoe_sol_set.add(degradation_id)
    if request.project_life_years > 1 and (se_has_initial or se_has_recurring):
        lcoe_se_set.add(degradation_id)
    delta_cost_set = set(noncancelled_cost)
    if has_noncancelled_recurring_cost:
        delta_cost_set.add(finance_id)
    delta_energy_set = {source_sol_id, source_se_id}
    if request.project_life_years > 1:
        delta_energy_set.add(degradation_id)
    # The discount rate changes the lifecycle factor, so it affects the energy
    # delta for every positive project life.  It also changes standalone LCOEs
    # even with initial-only costs through discounted energy.
    delta_energy_set.add(finance_id)
    if request.transfer is not None:
        baseline_id = request.transfer.baseline.input_id
        incremental_id = request.transfer.incremental.input_id
        lcoe_sol_set.add(baseline_id)
        lcoe_se_set |= {baseline_id, incremental_id, source_sol_id}
        # Baseline transfer is common to both systems and cancels from the delta.
        delta_energy_set.add(incremental_id)
    lcoo_set = delta_cost_set | delta_energy_set

    if request.standalone_commercial is not None:
        commercial_lines = request.standalone_commercial.cost_lines
        commercial_cost_ids = {line.input_id for line in commercial_lines}
        commercial_lcoe_set = commercial_cost_ids | {source_se_id}
        commercial_has_initial_or_scheduled = any(
            line.timing in {"initial_t0", "scheduled_year_end"}
            and distribution_support(line.distribution)[1] > 0
            for line in commercial_lines
        )
        commercial_has_annual = any(
            line.timing == "annual_year_end"
            and distribution_support(line.distribution)[1] > 0
            for line in commercial_lines
        )
        commercial_has_cost = commercial_has_initial_or_scheduled or commercial_has_annual
        if commercial_has_initial_or_scheduled or (
            commercial_has_annual and degradation_can_be_positive
        ):
            commercial_lcoe_set.add(finance_id)
        if request.project_life_years > 1 and commercial_has_cost:
            commercial_lcoe_set.add(degradation_id)
        response_definitions = {
            "commercial_solaredge_lifecycle_lcoe": (
                COMMERCIAL_STANDALONE_FIELD_LCOE,
                commercial_lcoe_set,
                None,
            )
        }
    elif request.paired_commercial is not None:
        system_sets: dict[SystemName, set[str]] = {}
        paired_systems = {
            system.technology: system
            for system in request.paired_commercial.systems
        }
        for technology, source_id in (
            ("solectria", source_sol_id),
            ("solaredge", source_se_id),
        ):
            commercial_lines = paired_systems[technology].cost_lines
            applicable = {line.input_id for line in commercial_lines} | {source_id}
            has_initial_or_scheduled = any(
                line.timing in {"initial_t0", "scheduled_year_end"}
                and distribution_support(line.distribution)[1] > 0
                for line in commercial_lines
            )
            has_annual = any(
                line.timing == "annual_year_end"
                and distribution_support(line.distribution)[1] > 0
                for line in commercial_lines
            )
            has_cost = has_initial_or_scheduled or has_annual
            if has_initial_or_scheduled or (
                has_annual and degradation_can_be_positive
            ):
                applicable.add(finance_id)
            if request.project_life_years > 1 and has_cost:
                applicable.add(degradation_id)
            system_sets[technology] = applicable
        response_definitions = {
            "commercial_solectria_lifecycle_lcoe": (
                COMMERCIAL_PAIRED_SOLECTRIA_FIELD_LCOE,
                system_sets["solectria"],
                None,
            ),
            "commercial_solaredge_lifecycle_lcoe": (
                COMMERCIAL_STANDALONE_FIELD_LCOE,
                system_sets["solaredge"],
                None,
            ),
            "commercial_lifecycle_lcoe_delta_se_minus_sol": (
                COMMERCIAL_PAIRED_FIELD_LCOE_DELTA,
                system_sets["solectria"] | system_sets["solaredge"],
                None,
            ),
        }
    else:
        response_definitions = {
            "lifecycle_lcoe_solectria": (fields.lcoe_sol, lcoe_sol_set, None),
            "lifecycle_lcoe_solaredge": (fields.lcoe_se, lcoe_se_set, None),
            "lifecycle_cost_delta_se_minus_sol": (fields.delta_cost, delta_cost_set, None),
            "lifecycle_energy_delta_se_minus_sol": (fields.delta_energy, delta_energy_set, None),
            "headline_positive_gain_lcoo_se_minus_sol": (
                fields.lcoo,
                lcoo_set,
                table["energy_class"] == "positive_lifecycle_gain" if energy_available else None,
            ),
        }
        if request.commercial_scaling is not None:
            response_definitions["commercial_marginal_lcoo_se_minus_sol"] = (
                COMMERCIAL_FIELD_MARGINAL_LCOO,
                delta_energy_set
                | {request.commercial_scaling.marginal_cost_difference.input_id},
                np.isfinite(table[COMMERCIAL_FIELD_MARGINAL_LCOO]),
            )
    results: dict[str, Any] = {}
    for response_name, (field_name, applicable, selection) in response_definitions.items():
        if not energy_available and response_name != "lifecycle_cost_delta_se_minus_sol":
            results[response_name] = {
                "status": "unavailable",
                "reason": "commercial_energy_transfer_unavailable",
                "sample_count": 0,
                "steps": [],
                "exclusions": {},
                "warnings": [],
                "final_r_squared": None,
            }
            continue
        selected_mask = np.ones(request.n, dtype=bool) if selection is None else selection
        response_values = table[field_name][selected_mask]
        candidate_values: dict[str, np.ndarray] = {}
        exclusions: dict[str, Mapping[str, Any] | str] = {}
        for identifier in sorted(universe):
            if identifier not in applicable:
                exclusions[identifier] = "no_structural_effect"
            elif identifier in all_specs and all_specs[identifier].family == "fixed":
                exclusions[identifier] = "fixed_input"
            else:
                candidate_values[identifier] = predictors[identifier][selected_mask]
        results[response_name] = stepwise_rank_regression(
            response_values,
            candidate_values,
            exclusions=exclusions,
        )
    return results


def run_technoeconomic(
    request: TechnoeconomicRequest,
    *,
    progress_cb: Callable[[float, str], None] | None = None,
    cancel_check: Callable[[], None] | None = None,
) -> TechnoeconomicResult:
    """Run one complete in-memory probabilistic technoeconomic calculation.

    The optional callbacks keep the pure kernel independent of persistence while
    allowing a durable worker to report coarse progress and cooperatively stop at
    deterministic stage boundaries.  Omitting them preserves the Phase-1 calling
    contract and calculation behavior.
    """

    def checkpoint(fraction: float, stage: str) -> None:
        if cancel_check is not None:
            cancel_check()
        if progress_cb is not None:
            progress_cb(fraction, stage)

    checkpoint(0.0, "Validating technoeconomic inputs")
    request = validate_request(request)
    checkpoint(0.05, "Generating probabilistic samples")
    capacity_map = {spec.system: spec for spec in request.capacities}
    normalization_capacities_w = _normalization_capacity_map(request)
    fields = _metric_fields(request)
    applied_capacity_normalization = fields is APPLIED_METRIC_FIELDS
    distributions = [line.distribution for line in request.cost_lines]
    distributions.extend([request.discount_rate, request.shared_degradation])
    if request.transfer is not None:
        distributions.extend([request.transfer.baseline, request.transfer.incremental])
    if request.commercial_scaling is not None:
        distributions.append(request.commercial_scaling.marginal_cost_difference)
    if request.standalone_commercial is not None:
        distributions.extend(
            line.distribution for line in request.standalone_commercial.cost_lines
        )
    if request.paired_commercial is not None:
        distributions.extend(
            line.distribution
            for system in request.paired_commercial.systems
            for line in system.cost_lines
        )
    samples = generate_lhs(request.n, request.seed, distributions)
    weather_years = allocate_weather_years(
        request.n,
        request.seed,
        [row.year for row in request.paired_energy_rows],
    )
    checkpoint(0.18, "Allocating paired weather years")
    energy_by_year = {row.year: row for row in request.paired_energy_rows}
    source_sol_kwh = np.asarray(
        [energy_by_year[int(year)].sol_predicted_kwh_ac for year in weather_years],
        dtype=np.float64,
    )
    source_se_kwh = np.asarray(
        [energy_by_year[int(year)].se_predicted_kwh_ac for year in weather_years],
        dtype=np.float64,
    )
    source_sol_specific = (
        source_sol_kwh / normalization_capacities_w["solectria"]
    )
    source_se_specific = (
        source_se_kwh / normalization_capacities_w["solaredge"]
    )

    discount_rates = samples[request.discount_rate.input_id]
    degradation = samples[request.shared_degradation.input_id]
    annuity_factor, crf = annuity_factor_and_crf(
        discount_rates,
        request.project_life_years,
    )
    annuity_factor = np.asarray(annuity_factor, dtype=np.float64)
    crf = np.asarray(crf, dtype=np.float64)
    costs = _cost_arrays(request, samples)
    pv_cost_sol = costs["initial_sol"] + costs["recurring_sol"] * annuity_factor
    pv_cost_se = costs["initial_se"] + costs["recurring_se"] * annuity_factor
    ea_cost_sol = crf * costs["initial_sol"] + costs["recurring_sol"]
    ea_cost_se = crf * costs["initial_se"] + costs["recurring_se"]
    delta_cost = costs["initial_delta"] + costs["recurring_delta"] * annuity_factor
    delta_ea_cost = crf * delta_cost
    _require_finite_arrays(
        "Lifecycle cost calculation",
        {
            "pv_cost_sol": pv_cost_sol,
            "pv_cost_se": pv_cost_se,
            "ea_cost_sol": ea_cost_sol,
            "ea_cost_se": ea_cost_se,
            "delta_cost": delta_cost,
            "delta_ea_cost": delta_ea_cost,
        },
    )
    checkpoint(0.38, "Calculating lifecycle cost and energy")

    energy_available = request.basis == "solartac_site" or request.transfer is not None
    if request.basis == "solartac_site":
        year1_sol = source_sol_specific
        year1_se = source_se_specific
        year1_delta = source_se_specific - source_sol_specific
    elif request.transfer is not None:
        baseline_factor = samples[request.transfer.baseline.input_id]
        incremental_factor = samples[request.transfer.incremental.input_id]
        year1_sol = baseline_factor * source_sol_specific
        year1_delta = incremental_factor * (source_se_specific - source_sol_specific)
        year1_se = year1_sol + year1_delta
        if not np.isfinite(year1_sol).all() or not np.isfinite(year1_se).all() or np.any(year1_sol <= 0) or np.any(year1_se <= 0):
            raise TechnoeconomicInvariantError(
                "Validated commercial transfer produced a nonpositive absolute yield."
            )
    else:
        year1_sol = np.full(request.n, np.nan, dtype=np.float64)
        year1_se = np.full(request.n, np.nan, dtype=np.float64)
        year1_delta = np.full(request.n, np.nan, dtype=np.float64)

    if energy_available:
        energy_factor = np.asarray(
            lifecycle_energy_factor(
                discount_rates,
                degradation,
                request.project_life_years,
            ),
            dtype=np.float64,
        )
        pv_energy_sol = year1_sol * energy_factor
        pv_energy_se = year1_se * energy_factor
        delta_energy = year1_delta * energy_factor
        ea_energy_sol = crf * pv_energy_sol
        ea_energy_se = crf * pv_energy_se
        lcoe_sol = pv_cost_sol / pv_energy_sol
        lcoe_se = pv_cost_se / pv_energy_se
        outcomes = _classify_outcomes(
            pv_cost_sol,
            pv_cost_se,
            pv_energy_sol,
            pv_energy_se,
            delta_cost=delta_cost,
            delta_energy=delta_energy,
        )
        delta_energy = outcomes["delta_energy"]
        delta_ea_energy = crf * delta_energy
        _require_finite_arrays(
            "Lifecycle energy calculation",
            {
                "year1_sol": year1_sol,
                "year1_se": year1_se,
                "pv_energy_sol": pv_energy_sol,
                "pv_energy_se": pv_energy_se,
                "ea_energy_sol": ea_energy_sol,
                "ea_energy_se": ea_energy_se,
                "lcoe_sol": lcoe_sol,
                "lcoe_se": lcoe_se,
                "delta_energy": delta_energy,
                "delta_ea_energy": delta_ea_energy,
                "nonzero_lcoo": outcomes["lcoo"][
                    outcomes["energy_class"] != "zero_lifecycle_gain"
                ],
            },
        )
    else:
        energy_factor = np.full(request.n, np.nan, dtype=np.float64)
        pv_energy_sol = np.full(request.n, np.nan, dtype=np.float64)
        pv_energy_se = np.full(request.n, np.nan, dtype=np.float64)
        ea_energy_sol = np.full(request.n, np.nan, dtype=np.float64)
        ea_energy_se = np.full(request.n, np.nan, dtype=np.float64)
        lcoe_sol = np.full(request.n, np.nan, dtype=np.float64)
        lcoe_se = np.full(request.n, np.nan, dtype=np.float64)
        delta_energy = np.full(request.n, np.nan, dtype=np.float64)
        delta_ea_energy = np.full(request.n, np.nan, dtype=np.float64)
        outcomes = {
            "cost_tolerance": np.maximum(
                1e-12,
                1e-12 * np.maximum(np.abs(pv_cost_se), np.abs(pv_cost_sol)),
            ),
            "energy_tolerance": np.full(request.n, np.nan, dtype=np.float64),
            "cost_class": np.where(
                delta_cost > np.maximum(1e-12, 1e-12 * np.maximum(np.abs(pv_cost_se), np.abs(pv_cost_sol))),
                "cost_increase",
                np.where(
                    delta_cost < -np.maximum(1e-12, 1e-12 * np.maximum(np.abs(pv_cost_se), np.abs(pv_cost_sol))),
                    "cost_saving",
                    "cost_neutral",
                ),
            ).astype(object),
            "energy_class": np.full(request.n, "energy_unavailable", dtype=object),
            "tradeoff_class": np.full(request.n, "unavailable", dtype=object),
            "lcoo": np.full(request.n, np.nan, dtype=np.float64),
            "lcoo_reason": np.full(
                request.n,
                "commercial_energy_transfer_unavailable",
                dtype=object,
            ),
        }

    commercial_fields: dict[str, np.ndarray] = {}
    if request.commercial_scaling is not None:
        commercial_spec = request.commercial_scaling
        marginal_cost_input = samples[
            commercial_spec.marginal_cost_difference.input_id
        ]
        with np.errstate(over="ignore", divide="ignore", invalid="ignore"):
            if commercial_spec.marginal_cost_timing == "lifecycle_present_value":
                commercial_lifecycle_cost = marginal_cost_input
                commercial_ea_cost = crf * marginal_cost_input
            else:
                commercial_ea_cost = marginal_cost_input
                commercial_lifecycle_cost = marginal_cost_input / crf
            if (
                normalization_capacities_w["solectria"]
                == normalization_capacities_w["solaredge"]
            ):
                commercial_year1_delta_energy = (
                    (source_se_kwh - source_sol_kwh)
                    / normalization_capacities_w["solaredge"]
                    * commercial_spec.target_capacity_w
                )
            else:
                commercial_year1_delta_energy = (
                    year1_delta * commercial_spec.target_capacity_w
                )
            commercial_lifecycle_delta_energy = (
                commercial_year1_delta_energy * energy_factor
            )
            commercial_ea_delta_energy = (
                commercial_lifecycle_delta_energy * crf
            )
            commercial_lcoo = np.full(request.n, np.nan, dtype=np.float64)
            commercial_nonzero = (
                outcomes["energy_class"] != "zero_lifecycle_gain"
            )
            commercial_lcoo[commercial_nonzero] = (
                commercial_lifecycle_cost[commercial_nonzero]
                / commercial_lifecycle_delta_energy[commercial_nonzero]
            )
        _require_finite_arrays(
            "Commercial scaling calculation",
            {
                "commercial_lifecycle_cost": commercial_lifecycle_cost,
                "commercial_ea_cost": commercial_ea_cost,
                "commercial_year1_delta_energy": commercial_year1_delta_energy,
                "commercial_lifecycle_delta_energy": commercial_lifecycle_delta_energy,
                "commercial_ea_delta_energy": commercial_ea_delta_energy,
                "commercial_nonzero_lcoo": commercial_lcoo[commercial_nonzero],
            },
        )
        commercial_fields = {
            COMMERCIAL_FIELD_TARGET_CAPACITY: np.full(
                request.n,
                commercial_spec.target_capacity_w,
                dtype=np.float64,
            ),
            COMMERCIAL_FIELD_YEAR1_DELTA_ENERGY: commercial_year1_delta_energy,
            COMMERCIAL_FIELD_LIFECYCLE_DELTA_ENERGY: (
                commercial_lifecycle_delta_energy
            ),
            COMMERCIAL_FIELD_EA_DELTA_ENERGY: commercial_ea_delta_energy,
            COMMERCIAL_FIELD_LIFECYCLE_MARGINAL_COST: commercial_lifecycle_cost,
            COMMERCIAL_FIELD_EA_MARGINAL_COST: commercial_ea_cost,
            COMMERCIAL_FIELD_MARGINAL_LCOO: commercial_lcoo,
            COMMERCIAL_FIELD_MARGINAL_LCOO_REASON: np.where(
                commercial_nonzero,
                None,
                COMMERCIAL_ZERO_ENERGY_REASON,
            ).astype(object),
        }

    standalone_commercial_fields: dict[str, np.ndarray] = {}
    if request.standalone_commercial is not None:
        standalone_spec = request.standalone_commercial
        standalone_capacity_scale_factor = (
            standalone_spec.target_capacity_w
            / normalization_capacities_w["solaredge"]
        )
        if (
            not math.isfinite(standalone_capacity_scale_factor)
            or standalone_capacity_scale_factor <= 0
        ):
            raise TechnoeconomicInvariantError(
                "Validated standalone commercial SolarEdge capacity scale factor "
                "was nonfinite or nonpositive."
            )
        standalone_costs = _standalone_commercial_cost_arrays(
            standalone_spec,
            samples,
            discount_rates,
            annuity_factor,
            crf,
        )
        with np.errstate(over="ignore", divide="ignore", invalid="ignore"):
            standalone_year1_energy = (
                source_se_kwh
                / normalization_capacities_w["solaredge"]
                * standalone_spec.target_capacity_w
            )
            standalone_lifecycle_energy = standalone_year1_energy * energy_factor
            standalone_ea_energy = standalone_lifecycle_energy * crf
            standalone_lcoe = (
                standalone_costs["lifecycle"] / standalone_lifecycle_energy
            )
        _require_finite_arrays(
            "Standalone commercial SolarEdge calculation",
            {
                "year1_energy": standalone_year1_energy,
                "lifecycle_energy": standalone_lifecycle_energy,
                "equivalent_annual_energy": standalone_ea_energy,
                "initial_cost": standalone_costs["initial"],
                "recurring_lifecycle_cost": standalone_costs["recurring_pv"],
                "scheduled_lifecycle_cost": standalone_costs["scheduled_pv"],
                "lifecycle_cost": standalone_costs["lifecycle"],
                "equivalent_annual_cost": standalone_costs["equivalent_annual"],
                "lcoe": standalone_lcoe,
            },
        )
        if np.any(standalone_year1_energy <= 0) or np.any(
            standalone_lifecycle_energy <= 0
        ):
            raise TechnoeconomicInvariantError(
                "Validated standalone commercial SolarEdge energy was nonpositive."
            )
        standalone_commercial_fields = {
            COMMERCIAL_STANDALONE_FIELD_TARGET_CAPACITY: np.full(
                request.n,
                standalone_spec.target_capacity_w,
                dtype=np.float64,
            ),
            COMMERCIAL_STANDALONE_FIELD_CAPACITY_SCALE_FACTOR: np.full(
                request.n,
                standalone_capacity_scale_factor,
                dtype=np.float64,
            ),
            COMMERCIAL_STANDALONE_FIELD_YEAR1_ENERGY: standalone_year1_energy,
            COMMERCIAL_STANDALONE_FIELD_LIFECYCLE_ENERGY: (
                standalone_lifecycle_energy
            ),
            COMMERCIAL_STANDALONE_FIELD_EA_ENERGY: standalone_ea_energy,
            COMMERCIAL_STANDALONE_FIELD_INITIAL_COST: standalone_costs["initial"],
            COMMERCIAL_STANDALONE_FIELD_RECURRING_PV_COST: (
                standalone_costs["recurring_pv"]
            ),
            COMMERCIAL_STANDALONE_FIELD_SCHEDULED_PV_COST: (
                standalone_costs["scheduled_pv"]
            ),
            COMMERCIAL_STANDALONE_FIELD_LIFECYCLE_COST: (
                standalone_costs["lifecycle"]
            ),
            COMMERCIAL_STANDALONE_FIELD_EA_COST: (
                standalone_costs["equivalent_annual"]
            ),
            COMMERCIAL_STANDALONE_FIELD_LCOE: standalone_lcoe,
        }

    paired_commercial_fields: dict[str, np.ndarray] = {}
    if request.paired_commercial is not None:
        paired_spec = request.paired_commercial
        paired_systems = {
            system.technology: system for system in paired_spec.systems
        }
        paired_lcoes: dict[SystemName, np.ndarray] = {}
        for technology, source_kwh, field_names in (
            (
                "solectria",
                source_sol_kwh,
                (
                    COMMERCIAL_PAIRED_SOLECTRIA_FIELD_TARGET_CAPACITY,
                    COMMERCIAL_PAIRED_SOLECTRIA_FIELD_CAPACITY_SCALE_FACTOR,
                    COMMERCIAL_PAIRED_SOLECTRIA_FIELD_YEAR1_ENERGY,
                    COMMERCIAL_PAIRED_SOLECTRIA_FIELD_LIFECYCLE_ENERGY,
                    COMMERCIAL_PAIRED_SOLECTRIA_FIELD_EA_ENERGY,
                    COMMERCIAL_PAIRED_SOLECTRIA_FIELD_INITIAL_COST,
                    COMMERCIAL_PAIRED_SOLECTRIA_FIELD_RECURRING_PV_COST,
                    COMMERCIAL_PAIRED_SOLECTRIA_FIELD_SCHEDULED_PV_COST,
                    COMMERCIAL_PAIRED_SOLECTRIA_FIELD_LIFECYCLE_COST,
                    COMMERCIAL_PAIRED_SOLECTRIA_FIELD_EA_COST,
                    COMMERCIAL_PAIRED_SOLECTRIA_FIELD_LCOE,
                ),
            ),
            (
                "solaredge",
                source_se_kwh,
                (
                    COMMERCIAL_STANDALONE_FIELD_TARGET_CAPACITY,
                    COMMERCIAL_STANDALONE_FIELD_CAPACITY_SCALE_FACTOR,
                    COMMERCIAL_STANDALONE_FIELD_YEAR1_ENERGY,
                    COMMERCIAL_STANDALONE_FIELD_LIFECYCLE_ENERGY,
                    COMMERCIAL_STANDALONE_FIELD_EA_ENERGY,
                    COMMERCIAL_STANDALONE_FIELD_INITIAL_COST,
                    COMMERCIAL_STANDALONE_FIELD_RECURRING_PV_COST,
                    COMMERCIAL_STANDALONE_FIELD_SCHEDULED_PV_COST,
                    COMMERCIAL_STANDALONE_FIELD_LIFECYCLE_COST,
                    COMMERCIAL_STANDALONE_FIELD_EA_COST,
                    COMMERCIAL_STANDALONE_FIELD_LCOE,
                ),
            ),
        ):
            source_capacity_w = normalization_capacities_w[technology]
            scale_factor = paired_spec.target_capacity_w / source_capacity_w
            if not math.isfinite(scale_factor) or scale_factor <= 0:
                raise TechnoeconomicInvariantError(
                    f"Validated paired commercial {technology} capacity scale "
                    "factor was nonfinite or nonpositive."
                )
            system_spec = paired_systems[technology]
            cost_spec = StandaloneCommercialSpec(
                target_capacity_w=paired_spec.target_capacity_w,
                target_rating_basis=paired_spec.target_rating_basis,
                cost_lines=system_spec.cost_lines,
                transfer_method=paired_spec.transfer_method,
            )
            system_costs = _standalone_commercial_cost_arrays(
                cost_spec,
                samples,
                discount_rates,
                annuity_factor,
                crf,
            )
            with np.errstate(over="ignore", divide="ignore", invalid="ignore"):
                year1_energy = (
                    source_kwh / source_capacity_w * paired_spec.target_capacity_w
                )
                lifecycle_energy = year1_energy * energy_factor
                ea_energy = lifecycle_energy * crf
                lcoe = system_costs["lifecycle"] / lifecycle_energy
            _require_finite_arrays(
                f"Paired commercial {technology} calculation",
                {
                    "year1_energy": year1_energy,
                    "lifecycle_energy": lifecycle_energy,
                    "equivalent_annual_energy": ea_energy,
                    "initial_cost": system_costs["initial"],
                    "recurring_lifecycle_cost": system_costs["recurring_pv"],
                    "scheduled_lifecycle_cost": system_costs["scheduled_pv"],
                    "lifecycle_cost": system_costs["lifecycle"],
                    "equivalent_annual_cost": system_costs["equivalent_annual"],
                    "lcoe": lcoe,
                },
            )
            if np.any(year1_energy <= 0) or np.any(lifecycle_energy <= 0):
                raise TechnoeconomicInvariantError(
                    f"Validated paired commercial {technology} energy was nonpositive."
                )
            (
                target_field,
                scale_field,
                year1_field,
                lifecycle_energy_field,
                ea_energy_field,
                initial_field,
                recurring_field,
                scheduled_field,
                lifecycle_cost_field,
                ea_cost_field,
                lcoe_field,
            ) = field_names
            paired_commercial_fields.update(
                {
                    target_field: np.full(
                        request.n, paired_spec.target_capacity_w, dtype=np.float64
                    ),
                    scale_field: np.full(
                        request.n, scale_factor, dtype=np.float64
                    ),
                    year1_field: year1_energy,
                    lifecycle_energy_field: lifecycle_energy,
                    ea_energy_field: ea_energy,
                    initial_field: system_costs["initial"],
                    recurring_field: system_costs["recurring_pv"],
                    scheduled_field: system_costs["scheduled_pv"],
                    lifecycle_cost_field: system_costs["lifecycle"],
                    ea_cost_field: system_costs["equivalent_annual"],
                    lcoe_field: lcoe,
                }
            )
            paired_lcoes[technology] = lcoe
        paired_commercial_fields[COMMERCIAL_PAIRED_FIELD_LCOE_DELTA] = (
            paired_lcoes["solaredge"] - paired_lcoes["solectria"]
        )
        _require_finite_arrays(
            "Paired commercial LCOE comparison",
            {
                "lcoe_delta_se_minus_sol": paired_commercial_fields[
                    COMMERCIAL_PAIRED_FIELD_LCOE_DELTA
                ]
            },
        )

    table: dict[str, np.ndarray] = {
        "realization_index": np.arange(1, request.n + 1, dtype=np.int64),
        "weather_year": weather_years,
        "SourceYear1Energy_SOL_kWh_AC": source_sol_kwh,
        "SourceYear1Energy_SE_kWh_AC": source_se_kwh,
        (
            "SourceYear1SpecificEnergy_SOL_kWh_AC_per_applied_W_year"
            if applied_capacity_normalization
            else "SourceYear1SpecificEnergy_SOL_kWh_AC_per_Wdc_year"
        ): source_sol_specific,
        (
            "SourceYear1SpecificEnergy_SE_kWh_AC_per_applied_W_year"
            if applied_capacity_normalization
            else "SourceYear1SpecificEnergy_SE_kWh_AC_per_Wdc_year"
        ): source_se_specific,
    }
    for identifier in sorted(samples, key=lambda value: value.encode("ascii")):
        table[f"SampledInput::{identifier}"] = samples[identifier]
    table.update(
        {
            "AnnuityFactor_years": annuity_factor,
            "CapitalRecoveryFactor_per_year": crf,
            "LifecycleEnergyFactor_years": energy_factor,
            (
                "InitialCostIntensity_SOL_USD_per_applied_W"
                if applied_capacity_normalization
                else "InitialCostIntensity_SOL_USD_per_Wdc"
            ): costs["initial_sol"],
            (
                "InitialCostIntensity_SE_USD_per_applied_W"
                if applied_capacity_normalization
                else "InitialCostIntensity_SE_USD_per_Wdc"
            ): costs["initial_se"],
            (
                "RecurringCostIntensity_SOL_USD_per_applied_W_year"
                if applied_capacity_normalization
                else "RecurringCostIntensity_SOL_USD_per_Wdc_year"
            ): costs["recurring_sol"],
            (
                "RecurringCostIntensity_SE_USD_per_applied_W_year"
                if applied_capacity_normalization
                else "RecurringCostIntensity_SE_USD_per_Wdc_year"
            ): costs["recurring_se"],
            fields.pv_cost_sol: pv_cost_sol,
            fields.pv_cost_se: pv_cost_se,
            fields.ea_cost_sol: ea_cost_sol,
            fields.ea_cost_se: ea_cost_se,
            fields.delta_cost: delta_cost,
            fields.delta_ea_cost: delta_ea_cost,
            fields.year1_sol: year1_sol,
            fields.year1_se: year1_se,
            fields.year1_delta: year1_delta,
            fields.pv_energy_sol: pv_energy_sol,
            fields.pv_energy_se: pv_energy_se,
            fields.ea_energy_sol: ea_energy_sol,
            fields.ea_energy_se: ea_energy_se,
            fields.lcoe_sol: lcoe_sol,
            fields.lcoe_se: lcoe_se,
            fields.delta_energy: delta_energy,
            fields.delta_ea_energy: delta_ea_energy,
            fields.lcoo: outcomes["lcoo"],
            (
                "energy_zero_tolerance_kWh_AC_per_applied_W"
                if applied_capacity_normalization
                else "energy_zero_tolerance_kWh_AC_per_Wdc"
            ): outcomes["energy_tolerance"],
            (
                "cost_zero_tolerance_USD_per_applied_W"
                if applied_capacity_normalization
                else "cost_zero_tolerance_USD_per_Wdc"
            ): outcomes["cost_tolerance"],
            "energy_class": outcomes["energy_class"],
            "cost_class": outcomes["cost_class"],
            "tradeoff_class": outcomes["tradeoff_class"],
            "lcoo_unavailable_reason": outcomes["lcoo_reason"],
        }
    )
    table.update(commercial_fields)
    table.update(standalone_commercial_fields)
    table.update(paired_commercial_fields)

    if request.basis == "solartac_site":
        sol_applied_w = normalization_capacities_w["solectria"]
        se_applied_w = normalization_capacities_w["solaredge"]
        with np.errstate(over="ignore", invalid="ignore"):
            raw_fields = {
                "PVCost_SOL_USD": pv_cost_sol * sol_applied_w,
                "PVCost_SE_USD": pv_cost_se * se_applied_w,
                "DeltaPVCostUSD_se_minus_sol": _site_raw_lifecycle_cost_delta(
                    request,
                    samples,
                    annuity_factor,
                    normalization_capacities_w,
                ),
                "PVEnergy_SOL_kWh_AC": pv_energy_sol * sol_applied_w,
                "PVEnergy_SE_kWh_AC": pv_energy_se * se_applied_w,
                "DeltaPVEnergyKWhAC_se_minus_sol": (
                    (source_se_kwh - source_sol_kwh) * energy_factor
                ),
            }
        _require_finite_arrays("SolarTAC raw-total diagnostics", raw_fields)
        table.update(raw_fields)
    elif request.commercial_reference_wdc is not None:
        reference_wdc = request.commercial_reference_wdc
        with np.errstate(over="ignore", invalid="ignore"):
            reference_fields = {
                "ReferencePVCost_SOL_USD": pv_cost_sol * reference_wdc,
                "ReferencePVCost_SE_USD": pv_cost_se * reference_wdc,
                "ReferenceDeltaPVCostUSD_se_minus_sol": delta_cost * reference_wdc,
            }
            if energy_available:
                reference_fields.update(
                    {
                        "ReferencePVEnergy_SOL_kWh_AC": pv_energy_sol * reference_wdc,
                        "ReferencePVEnergy_SE_kWh_AC": pv_energy_se * reference_wdc,
                        "ReferenceDeltaPVEnergyKWhAC_se_minus_sol": (
                            delta_energy * reference_wdc
                        ),
                    }
                )
        _require_finite_arrays("Commercial reference diagnostics", reference_fields)
        table.update(reference_fields)

    checkpoint(0.62, "Summarizing realization outcomes")
    common_audit = _build_common_cost_audit(
        request.cost_lines,
        samples,
        applied_capacity_normalization=applied_capacity_normalization,
    )
    common_treatments = {
        row["input_id"]: row["comparison_treatment"] for row in common_audit
    }
    summaries = _summaries_from_table(
        table,
        energy_available,
        fields,
        standalone_commercial=request.standalone_commercial is not None,
        paired_commercial=request.paired_commercial is not None,
    )
    if request.standalone_commercial is not None:
        standalone_spec = request.standalone_commercial
        cost_line_summaries: list[Mapping[str, Any]] = []
        for line in standalone_spec.cost_lines:
            line_summary = _commercial_v4_metric_summary(
                samples[line.input_id] * standalone_spec.target_capacity_w,
                include_cdf=False,
            )
            cost_line_summaries.append(
                {
                    "input_id": line.input_id,
                    "label": line.label,
                    "cost_category": line.cost_category,
                    "coverage_ids": line.coverage_ids,
                    "timing": line.timing,
                    "constant_dollar_cost_year": line.constant_dollar_cost_year,
                    "occurrence_years": line.occurrence_years,
                    "total_unit": (
                        "USD/year" if line.timing == "annual_year_end" else "USD"
                    ),
                    "status": line_summary["status"],
                    "reason": line_summary["reason"],
                    "count": line_summary["count"],
                    "percentiles": line_summary["percentiles"],
                }
            )
        summaries["commercial_cost_line_summaries"] = tuple(
            cost_line_summaries
        )
    if request.paired_commercial is not None:
        paired_cost_line_summaries: list[Mapping[str, Any]] = []
        for system in request.paired_commercial.systems:
            for line in system.cost_lines:
                line_summary = _commercial_v4_metric_summary(
                    samples[line.input_id]
                    * request.paired_commercial.target_capacity_w,
                    include_cdf=False,
                )
                paired_cost_line_summaries.append(
                    {
                        "technology": system.technology,
                        "input_id": line.input_id,
                        "label": line.label,
                        "cost_category": line.cost_category,
                        "coverage_ids": line.coverage_ids,
                        "timing": line.timing,
                        "constant_dollar_cost_year": line.constant_dollar_cost_year,
                        "occurrence_years": line.occurrence_years,
                        "total_unit": (
                            "USD/year"
                            if line.timing == "annual_year_end"
                            else "USD"
                        ),
                        "status": line_summary["status"],
                        "reason": line_summary["reason"],
                        "count": line_summary["count"],
                        "percentiles": line_summary["percentiles"],
                    }
                )
        summaries["paired_commercial_cost_line_summaries"] = tuple(
            paired_cost_line_summaries
        )
    per_year = _per_weather_year_summaries(
        request,
        table,
        capacity_map,
        normalization_capacities_w,
        energy_available,
        fields,
    )
    checkpoint(0.74, "Calculating sensitivity diagnostics")
    sensitivity = _sensitivity_models(
        request,
        table,
        samples,
        common_treatments,
        energy_available,
        fields,
    )

    checkpoint(0.88, "Calculating convergence diagnostics")
    if request.paired_commercial is not None:
        convergence_metrics = {
            COMMERCIAL_PAIRED_SOLECTRIA_FIELD_LIFECYCLE_COST: table[
                COMMERCIAL_PAIRED_SOLECTRIA_FIELD_LIFECYCLE_COST
            ],
            COMMERCIAL_PAIRED_SOLECTRIA_FIELD_LIFECYCLE_ENERGY: table[
                COMMERCIAL_PAIRED_SOLECTRIA_FIELD_LIFECYCLE_ENERGY
            ],
            COMMERCIAL_PAIRED_SOLECTRIA_FIELD_LCOE: table[
                COMMERCIAL_PAIRED_SOLECTRIA_FIELD_LCOE
            ],
            COMMERCIAL_STANDALONE_FIELD_LIFECYCLE_COST: table[
                COMMERCIAL_STANDALONE_FIELD_LIFECYCLE_COST
            ],
            COMMERCIAL_STANDALONE_FIELD_LIFECYCLE_ENERGY: table[
                COMMERCIAL_STANDALONE_FIELD_LIFECYCLE_ENERGY
            ],
            COMMERCIAL_STANDALONE_FIELD_LCOE: table[
                COMMERCIAL_STANDALONE_FIELD_LCOE
            ],
            COMMERCIAL_PAIRED_FIELD_LCOE_DELTA: table[
                COMMERCIAL_PAIRED_FIELD_LCOE_DELTA
            ],
        }
        convergence_tolerances = {
            COMMERCIAL_PAIRED_SOLECTRIA_FIELD_LIFECYCLE_COST: 0.01,
            COMMERCIAL_PAIRED_SOLECTRIA_FIELD_LIFECYCLE_ENERGY: 0.001,
            COMMERCIAL_PAIRED_SOLECTRIA_FIELD_LCOE: 0.0001,
            COMMERCIAL_STANDALONE_FIELD_LIFECYCLE_COST: 0.01,
            COMMERCIAL_STANDALONE_FIELD_LIFECYCLE_ENERGY: 0.001,
            COMMERCIAL_STANDALONE_FIELD_LCOE: 0.0001,
            COMMERCIAL_PAIRED_FIELD_LCOE_DELTA: 0.0001,
        }
    elif request.standalone_commercial is not None:
        convergence_metrics = {
            COMMERCIAL_STANDALONE_FIELD_LIFECYCLE_COST: table[
                COMMERCIAL_STANDALONE_FIELD_LIFECYCLE_COST
            ],
            COMMERCIAL_STANDALONE_FIELD_LIFECYCLE_ENERGY: table[
                COMMERCIAL_STANDALONE_FIELD_LIFECYCLE_ENERGY
            ],
            COMMERCIAL_STANDALONE_FIELD_LCOE: table[
                COMMERCIAL_STANDALONE_FIELD_LCOE
            ],
        }
        convergence_tolerances = {
            COMMERCIAL_STANDALONE_FIELD_LIFECYCLE_COST: 0.01,
            COMMERCIAL_STANDALONE_FIELD_LIFECYCLE_ENERGY: 0.001,
            COMMERCIAL_STANDALONE_FIELD_LCOE: 0.0001,
        }
    else:
        convergence_metrics = {
            fields.delta_cost: table[fields.delta_cost],
        }
        convergence_tolerances = {fields.delta_cost: 0.0001}
        if energy_available:
            convergence_metrics.update(
                {
                    fields.lcoe_sol: table[fields.lcoe_sol],
                    fields.lcoe_se: table[fields.lcoe_se],
                    fields.delta_energy: table[fields.delta_energy],
                    "headline_positive_gain_lcoo": np.where(
                        table["energy_class"] == "positive_lifecycle_gain",
                        table[fields.lcoo],
                        np.nan,
                    ),
                }
            )
            convergence_tolerances.update(
                {
                    fields.lcoe_sol: 0.0001,
                    fields.lcoe_se: 0.0001,
                    fields.delta_energy: 0.0001,
                    "headline_positive_gain_lcoo": 0.0001,
                }
            )
        if request.commercial_scaling is not None:
            convergence_metrics.update(
                {
                    COMMERCIAL_FIELD_LIFECYCLE_DELTA_ENERGY: table[
                        COMMERCIAL_FIELD_LIFECYCLE_DELTA_ENERGY
                    ],
                    COMMERCIAL_FIELD_MARGINAL_LCOO: table[
                        COMMERCIAL_FIELD_MARGINAL_LCOO
                    ],
                }
            )
            convergence_tolerances.update(
                {
                    COMMERCIAL_FIELD_LIFECYCLE_DELTA_ENERGY: 0.001,
                    COMMERCIAL_FIELD_MARGINAL_LCOO: 0.0001,
                }
            )
    convergence = convergence_diagnostics(
        convergence_metrics,
        convergence_tolerances,
        weather_years,
        [row.year for row in request.paired_energy_rows],
        energy_classes=(
            table["energy_class"]
            if energy_available
            and request.standalone_commercial is None
            and request.paired_commercial is None
            else None
        ),
        tradeoff_classes=(
            table["tradeoff_class"]
            if energy_available
            and request.standalone_commercial is None
            and request.paired_commercial is None
            else None
        ),
    )

    provenance = {
        "calculation_contract_version": request.calculation_contract_version,
        "sampling_version": SAMPLING_VERSION,
        "numpy_version": np.__version__,
        "scipy_version": scipy.__version__,
        "numerics": numerical_fingerprint(),
        "analysis_basis": request.basis,
        "realization_count": request.n,
        "seed": request.seed,
        "project_life_years": request.project_life_years,
        "energy_status": "available" if energy_available else "cost_only",
        "rng": {
            "bit_generator": "PCG64DXSM",
            "seed_domain": "sbepv-tea-lhs-v1",
            "purpose_strings": [
                LHS_JITTER_PURPOSE,
                LHS_PERMUTATION_PURPOSE,
                WEATHER_EXTRA_PURPOSE,
                WEATHER_ASSIGNMENT_PURPOSE,
            ],
            "weather_stable_id": WEATHER_STABLE_ID,
            "open_interval_repair": "binary64-nextafter-v1",
            "permutation": "fisher-yates-uint64-rejection-v1",
            "weather_multiset_order": "ascending-year-count-blocks",
        },
        "statistics": {
            "quantiles": "hyndman-fan-type-7",
            "ecdf": "right-continuous-ties-collapsed",
            "rank_regression": "forward-stepwise-midranks-v1",
            "rank_regression_entry_threshold": R2_ENTRY_THRESHOLD,
            "rank_regression_tie_absolute_tolerance": R2_TIE_ABSOLUTE_TOLERANCE,
        },
        "convergence_contract": {
            "checkpoint_rule": [
                "min(n,20)",
                "ceil(0.10*n)",
                "ceil(0.25*n)",
                "ceil(0.50*n)",
                "ceil(0.75*n)",
                "n",
            ],
            "relative_quantile_change_threshold": 0.01,
            "relative_scale_floor_multiplier": 100.0,
            "absolute_quantile_tolerances": (
                {
                    COMMERCIAL_PAIRED_SOLECTRIA_FIELD_LIFECYCLE_COST: 0.01,
                    COMMERCIAL_PAIRED_SOLECTRIA_FIELD_LIFECYCLE_ENERGY: 0.001,
                    COMMERCIAL_PAIRED_SOLECTRIA_FIELD_LCOE: 0.0001,
                    COMMERCIAL_STANDALONE_FIELD_LIFECYCLE_COST: 0.01,
                    COMMERCIAL_STANDALONE_FIELD_LIFECYCLE_ENERGY: 0.001,
                    COMMERCIAL_STANDALONE_FIELD_LCOE: 0.0001,
                    COMMERCIAL_PAIRED_FIELD_LCOE_DELTA: 0.0001,
                }
                if request.paired_commercial is not None
                else
                {
                    COMMERCIAL_STANDALONE_FIELD_LIFECYCLE_COST: 0.01,
                    COMMERCIAL_STANDALONE_FIELD_LIFECYCLE_ENERGY: 0.001,
                    COMMERCIAL_STANDALONE_FIELD_LCOE: 0.0001,
                }
                if request.standalone_commercial is not None
                else {
                    "lcoe_and_lcoo_USD_per_kWh_AC": 0.0001,
                    (
                        "lifecycle_cost_USD_per_applied_W"
                        if applied_capacity_normalization
                        else "lifecycle_cost_USD_per_Wdc"
                    ): 0.0001,
                    (
                        "lifecycle_energy_kWh_AC_per_applied_W"
                        if applied_capacity_normalization
                        else "lifecycle_energy_kWh_AC_per_Wdc"
                    ): 0.0001,
                }
            ),
            "class_probability_change_threshold": 0.001,
        },
    }
    if applied_capacity_normalization:
        applied_map = {spec.system: spec for spec in request.applied_capacities or ()}
        provenance["capacity_normalization"] = {
            "method": "annual_applied_capacity_v1",
            "systems": {
                system: {
                    "applied_capacity_w": applied_map[system].applied_capacity_w,
                    "rating_basis": applied_map[system].rating_basis,
                    "installed_wdc": capacity_map[system].installed_wdc,
                }
                for system in ("solectria", "solaredge")
            },
        }
    if request.commercial_scaling is not None:
        commercial_spec = request.commercial_scaling
        provenance["commercial_scaling"] = {
            "method": commercial_spec.transfer_method,
            "source_specific_energy_formula": (
                "(SE_kWh_AC / SE_applied_W) - "
                "(SOL_kWh_AC / SOL_applied_W)"
            ),
            "target_energy_formula": (
                "source_specific_energy_delta_kWh_AC_per_applied_W "
                "* target_capacity_W"
            ),
            "target_capacity_w": commercial_spec.target_capacity_w,
            "target_rating_basis": commercial_spec.target_rating_basis,
            "source_applied_capacities_w": {
                system: applied_map[system].applied_capacity_w
                for system in ("solectria", "solaredge")
            },
            "source_rating_basis": applied_map["solectria"].rating_basis,
            "marginal_cost_difference_input_id": (
                commercial_spec.marginal_cost_difference.input_id
            ),
            "marginal_cost_difference_distribution": asdict(
                commercial_spec.marginal_cost_difference
            ),
            "marginal_cost_timing": commercial_spec.marginal_cost_timing,
            "timing_conversion": (
                "EA=CRF*PV"
                if commercial_spec.marginal_cost_timing
                == "lifecycle_present_value"
                else "PV=EA/CRF"
            ),
            "marginal_lcoo_formula": (
                "commercial_lifecycle_marginal_cost_delta_USD / "
                "commercial_lifecycle_energy_delta_kWh_AC"
            ),
            "sign_convention": "SolarEdge minus Solectria",
            "zero_energy_rule": {
                "comparison": (
                    "source_normalized_lifecycle_energy_class != "
                    "zero_lifecycle_gain"
                ),
                "absolute_tolerance_kWh_AC_per_applied_W": 1e-9,
                "relative_tolerance": 1e-12,
                "lcoo": None,
                "reason": COMMERCIAL_ZERO_ENERGY_REASON,
            },
            "units": {
                "source_specific_energy_delta": "kWh_AC/applied_W-year",
                "target_capacity": "W",
                "year1_energy_delta": "kWh_AC",
                "lifecycle_energy_delta": "kWh_AC",
                "equivalent_annual_energy_delta": "kWh_AC/year",
                "lifecycle_marginal_cost_delta": "USD",
                "equivalent_annual_marginal_cost_delta": "USD/year",
                "marginal_lcoo": "USD/kWh_AC",
            },
        }
    if request.paired_commercial is not None:
        paired_spec = request.paired_commercial
        paired_systems = {
            system.technology: system for system in paired_spec.systems
        }
        provenance["commercial_paired"] = {
            "systems": {
                technology: {
                    "source_specific_energy_formula": (
                        f"{technology}_kWh_AC / {technology}_applied_W"
                    ),
                    "target_energy_formula": (
                        f"source_{technology}_specific_energy_kWh_AC_per_"
                        "applied_W_year * target_capacity_W"
                    ),
                    "source_applied_capacity_w": applied_map[
                        technology
                    ].applied_capacity_w,
                    "capacity_scale_factor_target_w_per_source_w": (
                        paired_spec.target_capacity_w
                        / applied_map[technology].applied_capacity_w
                    ),
                    "source_rating_basis": applied_map[technology].rating_basis,
                    "source_installed_wdc": capacity_map[technology].installed_wdc,
                    "cost_lines": tuple(
                        asdict(line)
                        for line in paired_systems[technology].cost_lines
                    ),
                    "lcoe_formula": (
                        f"commercial_{technology}_lifecycle_cost_USD / "
                        f"commercial_{technology}_lifecycle_energy_kWh_AC"
                    ),
                }
                for technology in ("solectria", "solaredge")
            },
            "method": paired_spec.transfer_method,
            "weather_pairing": "same_frozen_weather_year_per_realization",
            "target_capacity_w": paired_spec.target_capacity_w,
            "target_rating_basis": paired_spec.target_rating_basis,
            "constant_dollar_cost_year": request.constant_dollar_cost_year,
            "cost_stack_completeness": request.cost_stack_completeness,
            "required_cost_categories": (
                "full_initial_capex",
                "full_annual_om",
            ),
            "coverage_overlap_rule": (
                "same_scheduled_coverage_id_and_occurrence_year_forbidden_"
                "within_system"
            ),
            "lcoe_delta_formula": (
                "commercial_solaredge_lifecycle_lcoe_USD_per_kWh_AC - "
                "commercial_solectria_lifecycle_lcoe_USD_per_kWh_AC"
            ),
            "cost_timing": {
                "initial_t0": "undiscounted at t=0",
                "annual_year_end": "level real stream at t=1..L",
                "scheduled_year_end": "discounted at each occurrence year",
            },
            "finance_input_id": request.discount_rate.input_id,
            "degradation_input_id": request.shared_degradation.input_id,
            "headline_percentiles": "hyndman-fan-type-7-p10-p50-p90",
            "cdf": "right-continuous-ties-collapsed",
            "sign_convention": "SolarEdge minus Solectria",
            "units": {
                "source_specific_energy": "kWh_AC/applied_W-year",
                "target_capacity": "W",
                "capacity_scale_factor": "target_W/source_W",
                "year1_energy": "kWh_AC",
                "lifecycle_energy": "kWh_AC",
                "equivalent_annual_energy": "kWh_AC/year",
                "initial_and_scheduled_input": "USD/target_W",
                "annual_input": "USD/target_W-year",
                "lifecycle_cost": "USD",
                "equivalent_annual_cost": "USD/year",
                "lcoe_and_lcoe_delta": "USD/kWh_AC",
            },
        }
    if request.standalone_commercial is not None:
        standalone_spec = request.standalone_commercial
        provenance["commercial_standalone"] = {
            "system": "solaredge",
            "method": standalone_spec.transfer_method,
            "source_specific_energy_formula": (
                "SE_kWh_AC / SE_applied_W"
            ),
            "target_energy_formula": (
                "source_SE_specific_energy_kWh_AC_per_applied_W_year "
                "* target_capacity_W"
            ),
            "lifecycle_energy_formula": (
                "commercial_SE_year1_energy_kWh_AC * lifecycle_energy_factor"
            ),
            "lifecycle_cost_formula": (
                "initial_t0 + annual_year_end*annuity_factor + "
                "sum(scheduled_year_end*discount_factor_at_occurrence)"
            ),
            "lcoe_formula": (
                "commercial_SE_lifecycle_cost_USD / "
                "commercial_SE_lifecycle_energy_kWh_AC"
            ),
            "target_capacity_w": standalone_spec.target_capacity_w,
            "target_rating_basis": standalone_spec.target_rating_basis,
            "source_applied_capacity_w": applied_map[
                "solaredge"
            ].applied_capacity_w,
            "capacity_scale_factor_target_w_per_source_w": (
                standalone_spec.target_capacity_w
                / applied_map["solaredge"].applied_capacity_w
            ),
            "source_rating_basis": applied_map["solaredge"].rating_basis,
            "source_installed_wdc": capacity_map["solaredge"].installed_wdc,
            "constant_dollar_cost_year": request.constant_dollar_cost_year,
            "cost_stack_completeness": request.cost_stack_completeness,
            "required_cost_categories": (
                "full_initial_capex",
                "full_annual_om",
            ),
            "coverage_overlap_rule": (
                "same_scheduled_coverage_id_and_occurrence_year_forbidden"
            ),
            "cost_lines": tuple(asdict(line) for line in standalone_spec.cost_lines),
            "cost_timing": {
                "initial_t0": "undiscounted at t=0",
                "annual_year_end": "level real stream at t=1..L",
                "scheduled_year_end": "discounted at each occurrence year",
            },
            "finance_input_id": request.discount_rate.input_id,
            "degradation_input_id": request.shared_degradation.input_id,
            "headline_percentiles": "hyndman-fan-type-7-p10-p50-p90",
            "cdf": "right-continuous-ties-collapsed",
            "units": {
                "source_specific_energy": "kWh_AC/applied_W-year",
                "target_capacity": "W",
                "capacity_scale_factor": "target_W/source_W",
                "year1_energy": "kWh_AC",
                "lifecycle_energy": "kWh_AC",
                "equivalent_annual_energy": "kWh_AC/year",
                "initial_and_scheduled_input": "USD/target_W",
                "annual_input": "USD/target_W-year",
                "lifecycle_cost": "USD",
                "equivalent_annual_cost": "USD/year",
                "lcoe": "USD/kWh_AC",
            },
        }
    checkpoint(1.0, "Technoeconomic calculation complete")
    return TechnoeconomicResult(
        realization_table=table,
        sampled_inputs={identifier: values.copy() for identifier, values in samples.items()},
        common_cost_audit=common_audit,
        summaries=summaries,
        per_weather_year=per_year,
        sensitivity=sensitivity,
        convergence=convergence,
        provenance=provenance,
        energy_available=energy_available,
    )
