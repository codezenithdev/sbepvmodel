from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import threading
import unittest
import uuid
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient
from pydantic import ValidationError

from sbepv import model
from sbepv.api import config, state
from sbepv.api import main as app
from sbepv.api import technoeconomic as tea_api
from sbepv.api.artifacts import _technoeconomic_attempt_directory
from sbepv.api.schemas import (
    COMMERCIAL_TRANSFER_MECHANISMS,
    TechnoeconomicSubmissionRequest,
)
from sbepv.store import AgentStore


def _evidence(*, evidence_class: str = "direct_quote_or_primary_document") -> dict:
    value = {
        "evidence_class": evidence_class,
        "citation": {
            "title": "Synthetic Phase 3 test evidence",
            "organization": "Test laboratory",
            "url": "https://example.com/tea-evidence",
            "stable_reference": None,
            "publication_or_as_of_date": "2026-01-01",
            "accessed_date": "2026-08-13",
            "excerpt_or_derivation_note": "Synthetic values used only by tests.",
            "preservation_mode": "metadata_excerpt_only",
            "user_supplied_content_sha256": None,
            "metadata_only_rationale": (
                "The synthetic test source has no separately preserved evidence bytes."
            ),
        },
        "explicit_acceptance": None,
        "acceptance_rationale": None,
    }
    if evidence_class in {"engineering_judgment", "secondary_synthesis"}:
        value["explicit_acceptance"] = True
        value["acceptance_rationale"] = "Accepted explicitly for this test run."
    return value


def _currency_year_normalization(
    *,
    source_year: int = 2026,
    target_year: int = 2026,
    index_factor: float = 1.0,
) -> dict:
    if source_year == target_year:
        return {
            "method": "same_year_no_adjustment",
            "source_cost_year": source_year,
            "target_constant_dollar_cost_year": target_year,
            "submitted_distribution_basis": "target_constant_dollar_year",
            "index_identity": "not_applicable_same_year",
            "index_factor": index_factor,
            "derivation": "Source and target use the same constant-dollar year.",
        }
    return {
        "method": "price_index_adjustment",
        "source_cost_year": source_year,
        "target_constant_dollar_cost_year": target_year,
        "submitted_distribution_basis": "target_constant_dollar_year",
        "index_identity": "Synthetic construction cost index",
        "index_factor": index_factor,
        "derivation": "Multiply source-year dollars by the documented index factor.",
        "index_source_evidence": _evidence(),
    }


def _site_request_payload(*, source_id: str = "annual-source", n: int = 8) -> dict:
    return {
        "source_annual_job_id": source_id,
        "basis": "solartac_site",
        "n": n,
        "seed": 42,
        "cost_stack_completeness": "full_system",
        "cost_lines": [
            {
                "input_id": "cost.sol.capex",
                "label": "Solectria installed CAPEX",
                "ownership": "solectria_only",
                "cost_type": "initial_capex",
                "distribution": {"family": "fixed", "value": 100_000.0},
                "coverage_include_ids": ["equipment.solectria"],
                "coverage_exclude_ids": [],
                "original_unit": "usd_total",
                "normalized_unit": "usd_per_wdc",
                "normalization_method": "divide_by_frozen_source_wdc",
                "solectria_quantity": 1.0,
                "solaredge_quantity": 0.0,
                "quantity_unit": None,
                "normalization_derivation": "Divide the project total by frozen SOL Wdc.",
                "constant_dollar_cost_year": 2026,
                "currency_year_normalization": _currency_year_normalization(),
                "evidence": _evidence(),
            },
            {
                "input_id": "cost.se.capex",
                "label": "SolarEdge installed CAPEX",
                "ownership": "solaredge_only",
                "cost_type": "initial_capex",
                "distribution": {"family": "fixed", "value": 130_000.0},
                "coverage_include_ids": ["equipment.solaredge"],
                "coverage_exclude_ids": [],
                "original_unit": "usd_total",
                "normalized_unit": "usd_per_wdc",
                "normalization_method": "divide_by_frozen_source_wdc",
                "solectria_quantity": 0.0,
                "solaredge_quantity": 1.0,
                "quantity_unit": None,
                "normalization_derivation": "Divide the project total by frozen SE Wdc.",
                "constant_dollar_cost_year": 2026,
                "currency_year_normalization": _currency_year_normalization(),
                "evidence": _evidence(),
            },
        ],
        "finance": {
            "treatment_key": "constant-real-v1",
            "constant_dollar_cost_year": 2026,
            "project_life_years": 20,
            "project_life_evidence": _evidence(),
            "real_discount_rate": {
                "unit": "real_fraction_per_year",
                "distribution": {"family": "fixed", "value": 0.05},
                "evidence": _evidence(),
            },
        },
        "shared_degradation": {
            "degradation_model": "shared_module_v1",
            "annual_rate": {
                "unit": "real_fraction_per_year",
                "distribution": {"family": "fixed", "value": 0.005},
                "evidence": _evidence(),
            },
        },
        "commercial_reference_design": None,
        "commercial_transfer": None,
    }


def _applied_site_request_payload(
    *, source_id: str = "annual-source", n: int = 8
) -> dict:
    payload = _site_request_payload(source_id=source_id, n=n)
    payload["capacity_normalization"] = "annual_applied_capacity_v1"
    for line in payload["cost_lines"]:
        recurring = line["cost_type"].startswith("recurring_")
        line["normalized_unit"] = (
            "usd_per_applied_w_year" if recurring else "usd_per_applied_w"
        )
        line["normalization_method"] = (
            "divide_by_frozen_applied_capacity_w"
        )
        line["normalization_derivation"] = (
            "Divide the project total by the frozen Annual applied capacity."
        )
    return payload


def _commercial_scaling_request_payload(
    *,
    target_capacity: float = 100.0,
    target_capacity_unit: str = "mw",
    target_rating_basis: str = "ac_operating_limit",
    marginal_cost_timing: str = "lifecycle_present_value",
    marginal_cost_value: float = -2_500_000.0,
) -> dict:
    payload = _applied_site_request_payload()
    payload["commercial_scaling"] = {
        "target_capacity": target_capacity,
        "target_capacity_unit": target_capacity_unit,
        "target_rating_basis": target_rating_basis,
        "marginal_cost_difference": {
            "family": "fixed",
            "value": marginal_cost_value,
        },
        "marginal_cost_timing": marginal_cost_timing,
        "marginal_cost_unit": (
            "constant_usd"
            if marginal_cost_timing == "lifecycle_present_value"
            else "constant_usd_per_year"
        ),
        "transfer_method": "direct_capacity_scaling",
        "transfer_rationale": (
            "Scale the frozen SolarEdge-minus-Solectria specific energy delta "
            "directly to the submitted same-rating-basis target capacity."
        ),
        "evidence": _evidence(),
    }
    return payload


def _standalone_commercial_request_payload(
    *,
    target_capacity: float = 100.0,
    target_capacity_unit: str = "mw",
    target_rating_basis: str = "ac_operating_limit",
    n: int = 8,
) -> dict:
    payload = _applied_site_request_payload(n=n)
    payload["cost_lines"] = []
    payload["standalone_commercial"] = {
        "technology": "solaredge",
        "target_capacity": target_capacity,
        "target_capacity_unit": target_capacity_unit,
        "target_rating_basis": target_rating_basis,
        "transfer_method": "direct_capacity_scaling",
        "transfer_rationale": (
            "Scale verified SolarEdge specific energy from the frozen Annual "
            "capacity basis directly to the same-basis commercial target."
        ),
        "evidence": _evidence(),
        "cost_lines": [
            {
                "input_id": "commercial.solaredge.capex",
                "label": "SolarEdge installed CAPEX",
                "cost_category": "full_initial_capex",
                "coverage_ids": [
                    "commercial.solaredge.full-initial-system"
                ],
                "timing": "initial_t0",
                "unit": "constant_usd_per_target_w",
                "constant_dollar_cost_year": payload["finance"][
                    "constant_dollar_cost_year"
                ],
                "distribution": {
                    "family": "triangular",
                    "low": 1.0,
                    "mode": 1.1,
                    "high": 1.2,
                },
                "occurrence_years": [],
                "evidence": _evidence(),
            },
            {
                "input_id": "commercial.solaredge.om",
                "label": "SolarEdge annual O&M",
                "cost_category": "full_annual_om",
                "coverage_ids": [
                    "commercial.solaredge.full-annual-operations-maintenance"
                ],
                "timing": "annual_year_end",
                "unit": "constant_usd_per_target_w_year",
                "constant_dollar_cost_year": payload["finance"][
                    "constant_dollar_cost_year"
                ],
                "distribution": {"family": "fixed", "value": 0.02},
                "occurrence_years": [],
                "evidence": _evidence(),
            },
            {
                "input_id": "commercial.solaredge.replacement",
                "label": "SolarEdge scheduled replacement",
                "cost_category": "scheduled_replacement",
                "coverage_ids": [
                    "commercial.solaredge.inverter-replacement"
                ],
                "timing": "scheduled_year_end",
                "unit": "constant_usd_per_target_w",
                "constant_dollar_cost_year": payload["finance"][
                    "constant_dollar_cost_year"
                ],
                "distribution": {"family": "fixed", "value": 0.08},
                "occurrence_years": [10, 20],
                "evidence": _evidence(),
            },
        ],
    }
    return payload


def _paired_commercial_request_payload(
    *,
    target_capacity: float = 100.0,
    target_capacity_unit: str = "mw",
    target_rating_basis: str = "ac_operating_limit",
    n: int = 8,
) -> dict:
    payload = _standalone_commercial_request_payload(
        target_capacity=target_capacity,
        target_capacity_unit=target_capacity_unit,
        target_rating_basis=target_rating_basis,
        n=n,
    )
    standalone = payload.pop("standalone_commercial")
    solaredge_lines = standalone["cost_lines"]
    solectria_lines = deepcopy(solaredge_lines)
    for line in solectria_lines:
        line["input_id"] = line["input_id"].replace("solaredge", "solectria")
        line["label"] = line["label"].replace("SolarEdge", "Solectria")
        line["coverage_ids"] = [
            coverage.replace("solaredge", "solectria")
            for coverage in line["coverage_ids"]
        ]
    payload["paired_commercial"] = {
        "target_capacity": standalone["target_capacity"],
        "target_capacity_unit": standalone["target_capacity_unit"],
        "target_rating_basis": standalone["target_rating_basis"],
        "transfer_method": standalone["transfer_method"],
        "transfer_rationale": (
            "Scale each verified system's specific energy from its own frozen "
            "Annual capacity to one same-basis commercial target."
        ),
        "evidence": _evidence(),
        "systems": [
            {
                "technology": "solectria",
                "evidence": _evidence(),
                "cost_lines": solectria_lines,
            },
            {
                "technology": "solaredge",
                "evidence": _evidence(),
                "cost_lines": solaredge_lines,
            },
        ],
    }
    return payload


def _v6_lifecycle_request_payload(*, n: int = 8) -> dict:
    """Return a compact fully evidenced public V6 lifecycle request fixture."""

    payload = _paired_commercial_request_payload(n=n)
    payload["calculation_contract_version"] = "tea-calculation-v6"
    payload.pop("shared_degradation")
    for system in payload["paired_commercial"]["systems"]:
        system["cost_lines"] = []

    def documented(value: float, unit: str) -> dict:
        return {
            "unit": unit,
            "distribution": {"family": "fixed", "value": value},
            "evidence": _evidence(),
        }

    lifecycle_systems = []
    for technology in ("solectria", "solaredge"):
        prefix = f"lifecycle.{technology}"
        lifecycle_systems.append(
            {
                "technology": technology,
                "degradation": documented(0.005, "real_fraction_per_year"),
                "base_availability": documented(0.995, "dimensionless_fraction"),
                "base_om_cost_per_w_year": documented(
                    0.02,
                    "constant_usd_per_target_w_year",
                ),
                "base_om_real_growth": documented(0.0, "real_fraction_per_year"),
                "initial_cost_lines": [
                    {
                        "input_id": f"{prefix}.initial-capex",
                        "label": f"{technology.title()} initial installed cost",
                        "cost_per_w": documented(
                            0.80,
                            "constant_usd_per_target_w",
                        ),
                        "coverage_ids": [f"{prefix}.initial-scope"],
                        "evidence": _evidence(),
                    }
                ],
                "scheduled_costs": [],
                "components": [
                    {
                        "component_id": "generic-inverter",
                        "category": "inverter",
                        "count": 10,
                        "capacity_impact": 0.1,
                        "weibull_beta": documented(2.0, "dimensionless"),
                        "weibull_eta_years": documented(20.0, "years"),
                        "repair_hours": documented(8.0, "hours"),
                        "logistics_hours": documented(24.0, "hours"),
                        "emergency_unit_cost": documented(50_000.0, "constant_usd"),
                        "restock_unit_cost": documented(40_000.0, "constant_usd"),
                        "labor_cost": documented(2_000.0, "constant_usd"),
                        "mobilization_cost": documented(5_000.0, "constant_usd"),
                        "real_cost_growth": documented(0.0, "real_fraction_per_year"),
                        "batch_size": 2,
                        "initial_spares": 1,
                        "spare_target": 1,
                        "warranty": {
                            "age_limit_years": 10,
                            "fraction": 1.0,
                            "covered_cost_categories": ["hardware"],
                            "coverage_ids": [f"{prefix}.component-warranty"],
                            "evidence": _evidence(),
                        },
                        "preventive_replacements": [],
                        "coverage_ids": [f"{prefix}.component-corrective"],
                        "evidence": _evidence(),
                    }
                ],
                "decommissioning_cost": documented(100_000.0, "constant_usd"),
                "salvage_value": documented(100_000.0, "constant_usd"),
                "source_availability_by_year": [],
                "base_om_coverage_ids": [f"{prefix}.base-om"],
                "evidence": _evidence(),
            }
        )
    payload["paired_commercial"]["lifecycle"] = {
        "weather_path_method": (
            "paired-yearwise-balanced-across-realizations-"
            "independent-across-project-years-v1"
        ),
        "source_energy_basis": "gross",
        "reliability_mode": "event",
        "electricity_value": documented(0.07, "constant_usd_per_kwh_ac"),
        "electricity_value_real_growth": documented(
            0.0,
            "real_fraction_per_year",
        ),
        "systems": lifecycle_systems,
        "common_cause_events": [
            {
                "event_id": "shared-grid-outage",
                "annual_probability": documented(0.02, "dimensionless_fraction"),
                "downtime_hours": documented(24.0, "hours"),
                "capacity_impact": 1.0,
                "cost_per_event": documented(10_000.0, "constant_usd"),
                "real_cost_growth": documented(0.0, "real_fraction_per_year"),
                "affected_systems": ["solectria", "solaredge"],
                "coverage_ids": ["lifecycle.shared.grid-outage"],
                "evidence": _evidence(),
            }
        ],
        "decision_probability_threshold": 0.75,
        "decision_npv_tolerance_usd_per_target_w": 0.01,
    }
    return payload


def _commercial_request_payload(*, include_transfer: bool) -> dict:
    payload = _site_request_payload()
    payload["basis"] = "commercial_representative"
    payload["cost_lines"][0].update(
        {
            # The source-year value was 0.75 USD/Wdc.  This submitted value is
            # already 2026 dollars (0.75 * the documented 1.1 index factor).
            "distribution": {"family": "fixed", "value": 0.825},
            "original_unit": "usd_per_wdc",
            "normalized_unit": "usd_per_wdc",
            "normalization_method": "already_normalized_per_wdc",
            "normalization_derivation": (
                "Apply the documented currency index to the sourced commercial per-Wdc value."
            ),
            "currency_year_normalization": _currency_year_normalization(
                source_year=2024,
                target_year=2026,
                index_factor=1.1,
            ),
        }
    )
    payload["cost_lines"][1].update(
        {
            "distribution": {"family": "fixed", "value": 0.82},
            "original_unit": "usd_per_wdc",
            "normalized_unit": "usd_per_wdc",
            "normalization_method": "already_normalized_per_wdc",
            "normalization_derivation": (
                "The sourced commercial per-Wdc value already uses the target cost year."
            ),
        }
    )
    technology_design = {
        "optimizer_count": 0,
        "inverter_count": 10,
        "transformer_count": 1,
        "dc_ac_ratio": 1.25,
        "inverter_loading_ratio": 1.0,
        "inverter_topology": "Ten central inverters.",
        "transformer_topology": "One medium-voltage transformer.",
        "bos_scope": "Complete representative DC and AC BOS.",
        "labor_productivity_and_rates": "Documented representative crew rates.",
        "commissioning_scope": "Complete commissioning scope.",
    }
    solaredge_design = deepcopy(technology_design)
    solaredge_design.update(
        {
            "optimizer_count": 1000,
            "inverter_topology": "Ten SolarEdge inverters with module optimizers.",
        }
    )
    payload["commercial_reference_design"] = {
        "design_id": "commercial.fixture.v1",
        "reference_wdc": 420_000.0,
        "module_model": "Synthetic 420 W module",
        "module_stc_wdc": 420.0,
        "module_count": 1000,
        "constant_dollar_cost_year": 2026,
        "solectria": technology_design,
        "solaredge": solaredge_design,
        "normalization_derivation": (
            "Reference Wdc equals 1000 modules times 420 Wdc per module."
        ),
        "evidence": _evidence(),
    }
    if include_transfer:
        payload["commercial_transfer"] = {
            "status": "approved",
            "explicit_attestation": True,
            "attested_by": "Phase 3 test reviewer",
            "attested_at": "2026-08-13T12:00:00-06:00",
            "attestation_rationale": (
                "Every transfer mechanism was reviewed for the synthetic design."
            ),
            "baseline_factor": {
                "unit": "dimensionless_multiplier",
                "distribution": {"family": "fixed", "value": 0.9},
                "evidence": _evidence(),
            },
            "incremental_factor": {
                "unit": "dimensionless_multiplier",
                "distribution": {"family": "fixed", "value": 0.5},
                "evidence": _evidence(),
            },
            "mechanisms": [
                {
                    "mechanism": mechanism,
                    "status": "supported",
                    "rationale": f"Synthetic support for {mechanism}.",
                    "evidence": _evidence(),
                }
                for mechanism in sorted(COMMERCIAL_TRANSFER_MECHANISMS)
            ],
        }
    return payload


class TechnoeconomicApiPhase3Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.test_root = Path(__file__).resolve().parent / f".tea-api-{uuid.uuid4().hex}"
        self.output = self.test_root / "outputs"
        self.output.mkdir(parents=True)
        self.db_path = self.test_root / "agent.sqlite3"
        self.store = AgentStore(self.db_path)

        self.original_store = state.AGENT_STORE
        self.original_wake = state._WORKER_WAKE
        state.AGENT_STORE = self.store
        state._WORKER_WAKE = Mock()
        state.JOBS.clear()

        self.output_patch = patch.object(config, "OUTPUT_DIR", self.output)
        self.source_patch = patch.object(
            config,
            "ANNUAL_SOURCE_ARTIFACT_DIR",
            self.output / ".annual_sources",
        )
        self.output_patch.start()
        self.source_patch.start()
        self.addCleanup(self._cleanup)
        self.client = TestClient(app.app)

        self.annual = self._completed_annual("annual-source", calibrated=True)
        self.snapshot = self._snapshot("annual-source")
        self.envelope = {
            "source_snapshot": self.snapshot,
            "source_snapshot_sha256": tea_api.canonical_json_sha256(self.snapshot),
        }

    def _cleanup(self) -> None:
        self.client.close()
        self.source_patch.stop()
        self.output_patch.stop()
        state.AGENT_STORE = self.original_store
        state._WORKER_WAKE = self.original_wake
        state.JOBS.clear()
        shutil.rmtree(self.test_root, ignore_errors=True)

    def _completed_annual(self, job_id: str, *, calibrated: bool) -> dict:
        self.store.create_job(
            job_id=job_id,
            kind="manual",
            mode="annual",
            request={
                "from_date": "2024-01-01",
                "to_date": "2024-12-31",
                "years": [2024],
                "interval_value": 1,
                "interval_unit": "hours",
                "curtailment_enabled": True,
                "curtailment_limit_kw": 125.0,
            },
            provenance={
                "calibration_application": {
                    "baseline_job_id": "validation-origin",
                    "baseline_promoted_at": "2026-08-01T00:00:00+00:00",
                }
            },
        )
        claimed = self.store.claim_next_queued_job()
        self.assertEqual(job_id, claimed["id"])
        return self.store.update_job(
            job_id,
            state="done",
            result={
                "mode": "annual",
                "stats": {
                    "mode": "annual",
                    "calibration_enabled": calibrated,
                },
                "calibration_application": {
                    "applied": calibrated,
                    "baseline_job_id": "validation-origin",
                    "baseline_review_id": "review-origin",
                    "baseline_promoted_at": "2026-08-01T00:00:00+00:00",
                    "origin_profile_sha256": "1" * 64,
                    "resolved_profile_sha256": "1" * 64,
                },
            },
        )

    @staticmethod
    def _snapshot(source_id: str) -> dict:
        raw_source = b"date,dni\n2024-01-01,1\n"
        digest = hashlib.sha256(raw_source).hexdigest()
        return {
            "schema_version": 1,
            "eligibility_version": tea_api.ANNUAL_SOURCE_ELIGIBILITY_VERSION,
            "source_annual_job_id": source_id,
            "source_annual_job": {
                "request": {
                    "curtailment_enabled": True,
                    "curtailment_limit_kw": 125.0,
                }
            },
            "capacity_manifest": model.capacity_manifest(),
            "eligible_paired_energy_rows": [
                {
                    "year": 2024,
                    "period_start": "2024-01-01",
                    "period_end": "2024-12-31",
                    "sol_predicted_kwh": 200_000.0,
                    "se_predicted_kwh": 215_000.0,
                }
            ],
            "midc_source_artifact": {
                "schema_version": 1,
                "owner_workflow": "annual_simulation",
                "owner_annual_job_id": source_id,
                "content_address_algorithm": "sha256",
                "storage_key": f"sha256/{digest[:2]}/{digest}.csv",
                "sha256": digest,
                "byte_count": len(raw_source),
                "media_type": "text/csv",
                "immutable": True,
            },
        }

    def _source_fields(self) -> dict:
        artifact = self.snapshot["midc_source_artifact"]
        digest = self.envelope["source_snapshot_sha256"]
        return {
            "source_annual_job_id": "annual-source",
            "source_artifact_storage_key": artifact["storage_key"],
            "source_artifact_sha256": artifact["sha256"],
            "source_artifact_bytes": artifact["byte_count"],
            "source_snapshot": deepcopy(self.snapshot),
            "atomic_source_check": lambda _connection: digest,
        }

    def _create_via_api(self, payload: dict | None = None):
        dependencies = {
            "annual_job": self.annual,
            "origin_validation_job": {},
            "promotion_record": {},
        }
        submitted = deepcopy(payload) if payload is not None else _applied_site_request_payload()
        if (
            submitted.get("basis") == "solartac_site"
            and "capacity_normalization" not in submitted
        ):
            submitted["capacity_normalization"] = "annual_applied_capacity_v1"
            for line in submitted["cost_lines"]:
                recurring = line["cost_type"].startswith("recurring_")
                line["normalized_unit"] = (
                    "usd_per_applied_w_year" if recurring else "usd_per_applied_w"
                )
                line["normalization_method"] = (
                    "divide_by_frozen_applied_capacity_w"
                    if line["normalization_method"]
                    == "divide_by_frozen_source_wdc"
                    else "multiply_quantity_then_divide_by_frozen_applied_capacity_w"
                )
        with (
            patch.object(
                tea_api,
                "resolve_annual_source_dependencies",
                return_value=dependencies,
            ),
            patch.object(
                tea_api,
                "build_annual_source_snapshot",
                return_value=deepcopy(self.envelope),
            ),
            patch.object(
                tea_api,
                "technoeconomic_source_store_fields",
                return_value=self._source_fields(),
            ),
        ):
            return self.client.post(
                "/api/technoeconomic/jobs",
                json=submitted,
            )

    def test_strict_schema_rejects_derived_duplicates_and_coercion(self) -> None:
        valid = _site_request_payload()
        parsed = TechnoeconomicSubmissionRequest.model_validate(valid)
        self.assertEqual(8, parsed.n)

        invalid_payloads = [
            {**valid, "paired_energy_rows": [{"year": 2024}]},
            {**valid, "n": "8"},
        ]
        provisional = deepcopy(valid)
        provisional["cost_lines"][0]["evidence"] = _evidence(
            evidence_class="secondary_synthesis"
        )
        provisional["cost_lines"][0]["evidence"]["explicit_acceptance"] = None
        invalid_payloads.append(provisional)

        metadata_without_rationale = deepcopy(valid)
        metadata_without_rationale["cost_lines"][0]["evidence"]["citation"][
            "metadata_only_rationale"
        ] = None
        invalid_payloads.append(metadata_without_rationale)

        bad_currency_year = deepcopy(valid)
        bad_currency_year["cost_lines"][0]["currency_year_normalization"][
            "target_constant_dollar_cost_year"
        ] = 2025
        invalid_payloads.append(bad_currency_year)

        forged_content_address = deepcopy(valid)
        forged_citation = forged_content_address["cost_lines"][0]["evidence"][
            "citation"
        ]
        forged_citation.update(
            {
                "preservation_mode": "content_addressed_bytes",
                "user_supplied_content_sha256": "a" * 64,
                "content_byte_count": 123,
                "content_media_type": "application/pdf",
                "metadata_only_rationale": None,
            }
        )
        invalid_payloads.append(forged_content_address)

        for reserved_id in (
            "energy.source.solectria_specific",
            "energy.source.solaredge_specific",
        ):
            reserved_source = deepcopy(valid)
            reserved_source["cost_lines"][0]["input_id"] = reserved_id
            invalid_payloads.append(reserved_source)

        for payload in invalid_payloads:
            with self.assertRaises(ValidationError):
                TechnoeconomicSubmissionRequest.model_validate(payload)
            response = self._create_via_api(payload)
            self.assertEqual(422, response.status_code, response.text)
        self.assertEqual([], self.store.list_technoeconomic_jobs())
        state._WORKER_WAKE.set.assert_not_called()

    def test_new_site_route_requires_explicit_applied_capacity_contract(self) -> None:
        response = self.client.post(
            "/api/technoeconomic/jobs",
            json=_site_request_payload(),
        )

        self.assertEqual(422, response.status_code, response.text)
        self.assertIn("annual_applied_capacity_v1", response.text)
        self.assertEqual([], self.store.list_technoeconomic_jobs())

    def test_v2_site_request_derives_clipped_capacity_from_frozen_annual(self) -> None:
        payload = _applied_site_request_payload()
        parsed = TechnoeconomicSubmissionRequest.model_validate(payload)
        kernel_request = tea_api.build_technoeconomic_kernel_request(
            parsed,
            self.snapshot,
        )

        self.assertEqual(
            "tea-calculation-v2",
            kernel_request.calculation_contract_version,
        )
        self.assertEqual(
            [
                ("solectria", 125_000.0, "ac_operating_limit"),
                ("solaredge", 125_000.0, "ac_operating_limit"),
            ],
            [
                (item.system, item.applied_capacity_w, item.rating_basis)
                for item in kernel_request.applied_capacities or ()
            ],
        )
        lines = {line.input_id: line for line in kernel_request.cost_lines}
        self.assertAlmostEqual(
            1.0 / 125_000.0,
            lines["cost.sol.capex"].solectria_multiplier_to_intensity,
        )
        self.assertAlmostEqual(
            1.0 / 125_000.0,
            lines["cost.se.capex"].solaredge_multiplier_to_intensity,
        )

        provenance = tea_api.build_technoeconomic_submission_provenance(
            parsed,
            self.envelope,
            kernel_request,
        )
        self.assertEqual(2, provenance["schema_version"])
        self.assertEqual(
            "annual_applied_capacity_v1",
            provenance["capacity_normalization"],
        )
        applied = provenance["normalization_receipt"]["applied_capacities"]
        self.assertEqual(125_000.0, applied["solectria"]["applied_capacity_w"])
        self.assertEqual(
            "ac_operating_limit",
            applied["solaredge"]["rating_basis"],
        )
        self.assertNotIn("commercial_scaling_receipt", provenance)

    def test_v3_commercial_scaling_converts_dynamic_capacity_and_signed_cost(self) -> None:
        cases = (
            (100.0, "mw", 100_000_000.0),
            (250.5, "kw", 250_500.0),
        )
        for target, unit, expected_w in cases:
            with self.subTest(target=target, unit=unit):
                payload = _commercial_scaling_request_payload(
                    target_capacity=target,
                    target_capacity_unit=unit,
                    marginal_cost_value=-1_234_567.0,
                )
                parsed = TechnoeconomicSubmissionRequest.model_validate(payload)
                self.assertEqual(
                    -1_234_567.0,
                    parsed.commercial_scaling.marginal_cost_difference.value,
                )

                kernel_request = tea_api.build_technoeconomic_kernel_request(
                    parsed,
                    self.snapshot,
                )

                self.assertEqual(
                    "tea-calculation-v3",
                    kernel_request.calculation_contract_version,
                )
                scaling = kernel_request.commercial_scaling
                self.assertIsNotNone(scaling)
                self.assertEqual(expected_w, scaling.target_capacity_w)
                self.assertEqual("ac_operating_limit", scaling.target_rating_basis)
                self.assertEqual(
                    "commercial.marginal-cost-difference",
                    scaling.marginal_cost_difference.input_id,
                )
                self.assertEqual(
                    -1_234_567.0,
                    scaling.marginal_cost_difference.value,
                )

    def test_v3_commercial_scaling_supports_both_cost_timings_and_units(self) -> None:
        cases = (
            ("lifecycle_present_value", "constant_usd"),
            ("equivalent_annual", "constant_usd_per_year"),
        )
        for timing, expected_unit in cases:
            with self.subTest(timing=timing):
                payload = _commercial_scaling_request_payload(
                    marginal_cost_timing=timing,
                )
                parsed = TechnoeconomicSubmissionRequest.model_validate(payload)
                scaling = parsed.commercial_scaling
                self.assertEqual(timing, scaling.marginal_cost_timing)
                self.assertEqual(expected_unit, scaling.marginal_cost_unit)
                kernel_request = tea_api.build_technoeconomic_kernel_request(
                    parsed,
                    self.snapshot,
                )
                self.assertEqual(
                    timing,
                    kernel_request.commercial_scaling.marginal_cost_timing,
                )

    def test_v3_commercial_scaling_forbids_wrong_basis_contract_and_units(self) -> None:
        legacy_site = _commercial_scaling_request_payload()
        legacy_site.pop("capacity_normalization")
        for line in legacy_site["cost_lines"]:
            line["normalized_unit"] = "usd_per_wdc"
            line["normalization_method"] = "divide_by_frozen_source_wdc"

        commercial_basis = _commercial_request_payload(include_transfer=False)
        commercial_basis["commercial_scaling"] = deepcopy(
            _commercial_scaling_request_payload()["commercial_scaling"]
        )

        mistimed_unit = _commercial_scaling_request_payload()
        mistimed_unit["commercial_scaling"]["marginal_cost_unit"] = (
            "constant_usd_per_year"
        )

        reserved_id = _commercial_scaling_request_payload()
        reserved_id["cost_lines"][0]["input_id"] = (
            "commercial.marginal-cost-difference"
        )

        for payload in (legacy_site, commercial_basis, mistimed_unit, reserved_id):
            with self.subTest(payload=payload):
                with self.assertRaises(ValidationError):
                    TechnoeconomicSubmissionRequest.model_validate(payload)

    def test_v3_rating_basis_mismatch_is_a_clean_api_rejection(self) -> None:
        payload = _commercial_scaling_request_payload(
            target_rating_basis="dc_installed_nameplate",
        )

        response = self._create_via_api(payload)

        self.assertEqual(422, response.status_code, response.text)
        self.assertIn("rating basis", response.text.lower())
        self.assertEqual([], self.store.list_technoeconomic_jobs())
        state._WORKER_WAKE.set.assert_not_called()

    def test_v3_dc_target_matches_unclipped_installed_nameplate_source(self) -> None:
        snapshot = deepcopy(self.snapshot)
        snapshot["source_annual_job"]["request"] = {
            "curtailment_enabled": False,
            "curtailment_limit_kw": 125.0,
        }
        payload = _commercial_scaling_request_payload(
            target_rating_basis="dc_installed_nameplate",
        )

        kernel_request = tea_api.build_technoeconomic_kernel_request(
            payload,
            snapshot,
        )

        self.assertEqual(
            "dc_installed_nameplate",
            kernel_request.commercial_scaling.target_rating_basis,
        )
        self.assertEqual(
            {"dc_installed_nameplate"},
            {item.rating_basis for item in kernel_request.applied_capacities or ()},
        )

    def test_v3_commercial_scaling_provenance_freezes_units_and_evidence(self) -> None:
        payload = _commercial_scaling_request_payload(
            target_capacity=87.25,
            target_capacity_unit="mw",
            marginal_cost_timing="equivalent_annual",
            marginal_cost_value=425_000.0,
        )
        kernel_request = tea_api.build_technoeconomic_kernel_request(
            payload,
            self.snapshot,
        )

        provenance = tea_api.build_technoeconomic_submission_provenance(
            payload,
            self.envelope,
            kernel_request,
        )

        self.assertEqual(3, provenance["schema_version"])
        self.assertEqual("technoeconomic-submission-v3", provenance["request_schema"])
        self.assertEqual("tea-calculation-v3", provenance["calculation_contract_version"])
        receipt = provenance["commercial_scaling_receipt"]
        self.assertEqual(
            {"value": 87.25, "unit": "mw"},
            receipt["submitted_target_capacity"],
        )
        self.assertEqual(87_250_000.0, receipt["target_capacity_w"])
        self.assertEqual("ac_operating_limit", receipt["target_rating_basis"])
        self.assertEqual("equivalent_annual", receipt["marginal_cost_timing"])
        self.assertEqual("constant_usd_per_year", receipt["marginal_cost_unit"])
        self.assertEqual(425_000.0, receipt["marginal_cost_difference"]["value"])
        self.assertEqual(
            tea_api.canonical_json_sha256(receipt),
            provenance["commercial_scaling_receipt_sha256"],
        )
        self.assertIn(
            "commercial-scaling:marginal-cost-difference",
            {
                item["subject"]
                for item in provenance["evidence_receipt"]["preservation"]
            },
        )

    def test_v3_commercial_scaling_enqueues_immutable_request_and_receipt(self) -> None:
        payload = _commercial_scaling_request_payload(
            target_capacity=50_000.0,
            target_capacity_unit="kw",
            marginal_cost_value=800_000.0,
        )

        response = self._create_via_api(payload)

        self.assertEqual(202, response.status_code, response.text)
        stored = self.store.get_technoeconomic_job(response.json()["job"]["job_id"])
        self.assertEqual(
            50_000.0,
            stored["request"]["commercial_scaling"]["target_capacity"],
        )
        self.assertEqual(
            "kw",
            stored["request"]["commercial_scaling"]["target_capacity_unit"],
        )
        receipt = stored["submission_provenance"]["commercial_scaling_receipt"]
        self.assertEqual(50_000_000.0, receipt["target_capacity_w"])
        self.assertEqual(
            "commercial.marginal-cost-difference",
            receipt["marginal_cost_difference_input_id"],
        )
        state._WORKER_WAKE.set.assert_called_once_with()

    def test_v6_lifecycle_requires_explicit_matching_version(self) -> None:
        v5 = _paired_commercial_request_payload()
        parsed_v5 = TechnoeconomicSubmissionRequest.model_validate(v5)
        canonical_v5 = tea_api.canonical_submission_request_payload(parsed_v5)
        self.assertNotIn("calculation_contract_version", canonical_v5)
        self.assertNotIn("lifecycle", canonical_v5["paired_commercial"])

        lifecycle_without_version = _v6_lifecycle_request_payload()
        lifecycle_without_version.pop("calculation_contract_version")
        with self.assertRaisesRegex(ValidationError, "requires explicit"):
            TechnoeconomicSubmissionRequest.model_validate(lifecycle_without_version)

        v6_without_lifecycle = _paired_commercial_request_payload()
        v6_without_lifecycle["calculation_contract_version"] = "tea-calculation-v6"
        with self.assertRaisesRegex(ValidationError, "requires paired_commercial.lifecycle"):
            TechnoeconomicSubmissionRequest.model_validate(v6_without_lifecycle)

        mismatched_v5 = _paired_commercial_request_payload()
        mismatched_v5["calculation_contract_version"] = "tea-calculation-v4"
        with self.assertRaisesRegex(ValidationError, "does not match"):
            TechnoeconomicSubmissionRequest.model_validate(mismatched_v5)

    def test_v6_lifecycle_maps_to_isolated_kernel_contract_and_receipt(self) -> None:
        payload = _v6_lifecycle_request_payload()
        parsed = TechnoeconomicSubmissionRequest.model_validate(payload)
        request = tea_api.build_technoeconomic_kernel_request(parsed, self.snapshot)

        self.assertEqual(
            tea_api.technoeconomic_kernel.LIFECYCLE_CALCULATION_CONTRACT_VERSION,
            request.calculation_contract_version,
        )
        self.assertEqual(
            tea_api.technoeconomic_kernel.LIFECYCLE_SAMPLING_VERSION,
            request.sampling_version,
        )
        self.assertIsNone(request.shared_degradation)
        self.assertIsNone(request.paired_commercial)
        self.assertIsNotNone(request.paired_lifecycle)
        lifecycle = request.paired_lifecycle
        self.assertEqual(100_000_000.0, lifecycle.target_capacity_w)
        self.assertEqual(
            ["solectria", "solaredge"],
            [system.technology for system in lifecycle.systems],
        )
        self.assertEqual(0.01, lifecycle.npv_absolute_tolerance_usd_per_w)
        self.assertEqual(
            "lifecycle.solectria.component.generic-inverter.weibull-beta",
            lifecycle.systems[0].components[0].weibull_beta.input_id,
        )

        provenance = tea_api.build_technoeconomic_submission_provenance(
            parsed,
            self.envelope,
            request,
        )
        self.assertEqual(6, provenance["schema_version"])
        self.assertEqual("technoeconomic-submission-v6", provenance["request_schema"])
        receipt = provenance["paired_lifecycle_receipt"]
        self.assertEqual("paired_lifecycle", receipt["shape_discriminator"])
        self.assertEqual("event", receipt["reliability_mode"])
        self.assertEqual(
            tea_api.technoeconomic_kernel.formula_registry_hash(),
            receipt["formula_registry_sha256"],
        )
        self.assertEqual(
            tea_api.canonical_json_sha256(
                tea_api.canonical_submission_request_payload(parsed)
            ),
            provenance["request_sha256"],
        )

        response = self._create_via_api(payload)
        self.assertEqual(202, response.status_code, response.text)
        stored = self.store.get_technoeconomic_job(response.json()["job"]["job_id"])
        self.assertEqual(
            "tea-calculation-v6",
            stored["request"]["calculation_contract_version"],
        )
        self.assertIn("lifecycle", stored["request"]["paired_commercial"])
        self.assertEqual(
            "tea-lhs-v2",
            stored["submission_provenance"]["sampling_version"],
        )

    def test_v6_formula_catalog_route_uses_kernel_registry(self) -> None:
        response = self.client.get("/api/technoeconomic/formulas/v6")
        self.assertEqual(200, response.status_code, response.text)
        body = response.json()
        self.assertEqual("tea-calculation-v6", body["calculation_contract_version"])
        self.assertEqual("tea-formulas-v6", body["formula_registry_version"])
        self.assertEqual(len(body["formulas"]), body["formula_registry_count"])
        self.assertEqual(
            tea_api.technoeconomic_kernel.formula_registry_hash(),
            body["formula_registry_sha256"],
        )

    def test_v6_create_feature_flag_blocks_only_new_v6_submissions(self) -> None:
        with patch.object(config, "TECHNOECONOMIC_V6_SUBMISSIONS_ENABLED", False):
            blocked = self._create_via_api(_v6_lifecycle_request_payload())
            formula_catalog = self.client.get("/api/technoeconomic/formulas/v6")

        self.assertEqual(503, blocked.status_code, blocked.text)
        self.assertIn("temporarily disabled", blocked.json()["detail"])
        self.assertEqual([], self.store.list_technoeconomic_jobs())
        state._WORKER_WAKE.set.assert_not_called()
        self.assertEqual(200, formula_catalog.status_code, formula_catalog.text)

        with patch.object(config, "TECHNOECONOMIC_V6_SUBMISSIONS_ENABLED", False):
            v5_response = self._create_via_api(_paired_commercial_request_payload())
        self.assertEqual(202, v5_response.status_code, v5_response.text)
        self.assertNotIn(
            "calculation_contract_version",
            v5_response.json()["job"]["request"],
        )

    def test_v6_create_feature_flag_preserves_existing_job_status_and_retry(self) -> None:
        created = self._create_via_api(_v6_lifecycle_request_payload())
        self.assertEqual(202, created.status_code, created.text)
        job_id = created.json()["job"]["job_id"]
        cancelled = self.client.post(f"/api/technoeconomic/jobs/{job_id}/cancel")
        self.assertEqual(200, cancelled.status_code, cancelled.text)
        self.assertEqual("cancelled", cancelled.json()["job"]["state"])
        state._WORKER_WAKE.set.reset_mock()

        with (
            patch.object(config, "TECHNOECONOMIC_V6_SUBMISSIONS_ENABLED", False),
            patch.object(
                app,
                "_technoeconomic_export_response",
                return_value=app.JSONResponse({"verified": True}),
            ) as export_response,
        ):
            status = self.client.get(f"/api/technoeconomic/jobs/{job_id}")
            download = self.client.get(
                f"/api/technoeconomic/jobs/{job_id}/exports/xlsx"
            )
            retried = self.client.post(f"/api/technoeconomic/jobs/{job_id}/retry")

        self.assertEqual(200, status.status_code, status.text)
        self.assertEqual("tea-calculation-v6", status.json()["request"][
            "calculation_contract_version"
        ])
        self.assertEqual(200, download.status_code, download.text)
        export_response.assert_called_once_with(job_id, "xlsx")
        self.assertEqual(202, retried.status_code, retried.text)
        self.assertEqual(job_id, retried.json()["job"]["retry_of_job_id"])
        state._WORKER_WAKE.set.assert_called_once_with()

    def test_v6_admission_returns_safe_maximum_and_limiting_dimension(self) -> None:
        cases = (
            (30, "estimated_peak_memory"),
            (1, "realization_export_cells"),
        )
        for project_life, limiter in cases:
            with self.subTest(project_life=project_life):
                payload = _v6_lifecycle_request_payload(n=100_000)
                payload["finance"]["project_life_years"] = project_life
                parsed = TechnoeconomicSubmissionRequest.model_validate(payload)
                with self.assertRaisesRegex(
                    tea_api.technoeconomic_kernel.TechnoeconomicValidationError,
                    rf"safe maximum .* limited by {limiter}",
                ):
                    tea_api.build_technoeconomic_kernel_request(parsed, self.snapshot)

        response = self._create_via_api(_v6_lifecycle_request_payload(n=100_000))
        self.assertEqual(422, response.status_code, response.text)
        self.assertIn("safe maximum", response.text)
        self.assertIn("estimated_peak_memory", response.text)
        self.assertEqual([], self.store.list_technoeconomic_jobs())

    def test_v5_paired_commercial_builds_both_systems_and_frozen_receipt(self) -> None:
        payload = _paired_commercial_request_payload()
        parsed = TechnoeconomicSubmissionRequest.model_validate(payload)
        request = tea_api.build_technoeconomic_kernel_request(parsed, self.snapshot)

        self.assertEqual(
            tea_api.technoeconomic_kernel.PAIRED_COMMERCIAL_CALCULATION_CONTRACT_VERSION,
            request.calculation_contract_version,
        )
        self.assertEqual((), request.cost_lines)
        paired = request.paired_commercial
        self.assertIsNotNone(paired)
        self.assertEqual(100_000_000.0, paired.target_capacity_w)
        self.assertEqual(
            ["solectria", "solaredge"],
            [system.technology for system in paired.systems],
        )
        self.assertTrue(
            all(len(system.cost_lines) == 3 for system in paired.systems)
        )

        provenance = tea_api.build_technoeconomic_submission_provenance(
            parsed,
            self.envelope,
            request,
        )
        self.assertEqual(5, provenance["schema_version"])
        self.assertEqual("technoeconomic-submission-v5", provenance["request_schema"])
        receipt = provenance["paired_commercial_receipt"]
        self.assertEqual(100_000_000.0, receipt["target_capacity_w"])
        self.assertEqual(
            {"solectria", "solaredge"},
            set(receipt["systems"]),
        )
        for technology in ("solectria", "solaredge"):
            system = receipt["systems"][technology]
            self.assertEqual(
                125_000.0,
                system["source_capacity"]["applied_capacity_w"],
            )
            self.assertEqual(800.0, system["capacity_scale_factor"])
            self.assertEqual(
                {
                    "full_initial_capex": 1,
                    "full_annual_om": 1,
                    "scheduled_replacement": 1,
                },
                system["cost_category_counts"],
            )
        self.assertEqual(
            tea_api.canonical_json_sha256(receipt),
            provenance["paired_commercial_receipt_sha256"],
        )
        self.assertEqual(
            "coverage IDs must be disjoint between lines within one system unless "
            "both lines are scheduled replacements at disjoint occurrence years",
            receipt["coverage_overlap_rule"],
        )
        evidence_subjects = {
            item["subject"]
            for item in provenance["evidence_receipt"]["preservation"]
        }
        self.assertIn("paired-commercial:energy-scaling", evidence_subjects)
        self.assertIn("paired-commercial-system:solectria", evidence_subjects)
        self.assertIn(
            "paired-commercial-cost:solaredge:commercial.solaredge.capex",
            evidence_subjects,
        )

        response = self._create_via_api(payload)
        self.assertEqual(202, response.status_code, response.text)
        stored = self.store.get_technoeconomic_job(response.json()["job"]["job_id"])
        self.assertEqual(
            100.0,
            stored["request"]["paired_commercial"]["target_capacity"],
        )
        self.assertEqual(
            800.0,
            stored["submission_provenance"]["paired_commercial_receipt"]
            ["systems"]["solectria"]["capacity_scale_factor"],
        )

    def test_v5_paired_commercial_keeps_the_user_target_capacity(self) -> None:
        cases = (
            (100.0, 100_000_000.0, 800.0),
            (75.0, 75_000_000.0, 600.0),
        )
        for target_mw, expected_target_w, expected_scale in cases:
            with self.subTest(target_mw=target_mw):
                payload = _paired_commercial_request_payload(
                    target_capacity=target_mw,
                    target_capacity_unit="mw",
                )
                request = tea_api.build_technoeconomic_kernel_request(
                    payload,
                    self.snapshot,
                )
                provenance = tea_api.build_technoeconomic_submission_provenance(
                    payload,
                    self.envelope,
                    request,
                )

                self.assertEqual(
                    expected_target_w,
                    request.paired_commercial.target_capacity_w,
                )
                receipt = provenance["paired_commercial_receipt"]
                self.assertEqual(expected_target_w, receipt["target_capacity_w"])
                for technology in ("solectria", "solaredge"):
                    system = receipt["systems"][technology]
                    self.assertEqual(
                        125_000.0,
                        system["source_capacity"]["applied_capacity_w"],
                    )
                    self.assertEqual(
                        "ac_operating_limit",
                        system["source_capacity"]["rating_basis"],
                    )
                    self.assertEqual(
                        expected_scale,
                        system["capacity_scale_factor"],
                    )

    def test_v5_paired_commercial_uses_nameplate_when_clipping_is_off(self) -> None:
        snapshot = deepcopy(self.snapshot)
        snapshot["source_annual_job"]["request"] = {
            "curtailment_enabled": False,
            "curtailment_limit_kw": 125.0,
        }
        payload = _paired_commercial_request_payload(
            target_capacity=75.0,
            target_capacity_unit="mw",
            target_rating_basis="dc_installed_nameplate",
        )

        request = tea_api.build_technoeconomic_kernel_request(payload, snapshot)
        envelope = {
            "source_snapshot": snapshot,
            "source_snapshot_sha256": tea_api.canonical_json_sha256(snapshot),
        }
        provenance = tea_api.build_technoeconomic_submission_provenance(
            payload,
            envelope,
            request,
        )

        self.assertEqual(75_000_000.0, request.paired_commercial.target_capacity_w)
        receipt = provenance["paired_commercial_receipt"]
        for technology in ("solectria", "solaredge"):
            source = receipt["systems"][technology]["source_capacity"]
            installed_wdc = snapshot["capacity_manifest"]["systems"][technology][
                "installed_wdc"
            ]
            self.assertEqual(installed_wdc, source["applied_capacity_w"])
            self.assertEqual("dc_installed_nameplate", source["rating_basis"])
            self.assertAlmostEqual(
                75_000_000.0 / installed_wdc,
                receipt["systems"][technology]["capacity_scale_factor"],
            )

    def test_v5_paired_schema_rejects_duplicate_systems_and_cost_ids(self) -> None:
        duplicate_system = _paired_commercial_request_payload()
        duplicate_system["paired_commercial"]["systems"][1]["technology"] = (
            "solectria"
        )
        duplicate_id = _paired_commercial_request_payload()
        duplicate_id["paired_commercial"]["systems"][1]["cost_lines"][0][
            "input_id"
        ] = duplicate_id["paired_commercial"]["systems"][0]["cost_lines"][0][
            "input_id"
        ]
        missing_om = _paired_commercial_request_payload()
        missing_om["paired_commercial"]["systems"][0]["cost_lines"] = [
            line
            for line in missing_om["paired_commercial"]["systems"][0][
                "cost_lines"
            ]
            if line["cost_category"] != "full_annual_om"
        ]
        for invalid in (duplicate_system, duplicate_id, missing_om):
            with self.subTest(invalid=invalid), self.assertRaises(ValidationError):
                TechnoeconomicSubmissionRequest.model_validate(invalid)

        overlapping_om_replacement = _paired_commercial_request_payload()
        solectria_lines = overlapping_om_replacement["paired_commercial"][
            "systems"
        ][0]["cost_lines"]
        annual_om = next(
            line
            for line in solectria_lines
            if line["cost_category"] == "full_annual_om"
        )
        replacement = next(
            line
            for line in solectria_lines
            if line["cost_category"] == "scheduled_replacement"
        )
        replacement["coverage_ids"] = list(annual_om["coverage_ids"])
        with self.assertRaisesRegex(ValidationError, "coverage IDs must be disjoint"):
            TechnoeconomicSubmissionRequest.model_validate(
                overlapping_om_replacement
            )

    def test_v1_through_v4_durable_requests_omit_null_paired_commercial(self) -> None:
        payloads = (
            _site_request_payload(),
            _applied_site_request_payload(),
            _commercial_scaling_request_payload(),
            _standalone_commercial_request_payload(),
        )
        for payload in payloads:
            with self.subTest(payload=payload):
                response = self._create_via_api(payload)
                self.assertEqual(202, response.status_code, response.text)
                stored = self.store.get_technoeconomic_job(
                    response.json()["job"]["job_id"]
                )
                self.assertNotIn("paired_commercial", stored["request"])
                self.assertEqual(
                    stored["submission_provenance"]["request_sha256"],
                    tea_api.canonical_json_sha256(stored["request"]),
                )

    def test_v1_through_v5_historical_golden_vectors_are_stable(self) -> None:
        vectors = (
            (
                "v1",
                _site_request_payload(),
                (
                    "7691800ee1792bd4b31f163b6320d0c5787a845e5e531cbac1804c768e57d5fc",
                    "a64a2daa1499935ba469e270a5ad5b571aa409f207c06dccbb77b1c35d1e57cd",
                    "9ec5429afaa911fd43bb14f5971c6fe236bc4f26a0cf85cd4e5fc1a4be7f005c",
                ),
            ),
            (
                "v2",
                _applied_site_request_payload(),
                (
                    "d273a1bf5ab3f696b365dd0a9fc56a6c949e366398cc5c648ce25a6a7c4f0135",
                    "fc32603b46dc719338e89373e378a6a04eb1882808c35368b1776c459386e58c",
                    "f535056336d59c27bb4e2abba48a3929681259e02c1503f25049c74c7b364f7e",
                ),
            ),
            (
                "v3",
                _commercial_scaling_request_payload(),
                (
                    "3a9ffbfddacfa1f33ef25d3c27d6db222de9cd4c586c5cbcc5a8b2b4ef2865ae",
                    "bb3bb4ec1ec64266e718fc886b9812b5bfeace46efc2f7423ae8a3e52ed1a7d5",
                    "ce66f2ad78c3ff28743a95fad3e225e6bb0c311ae0968787bed07a2fdb769853",
                ),
            ),
            (
                "v4",
                _standalone_commercial_request_payload(),
                (
                    "e1a8d94b5914be0423e3e4e233554a352534686e058292d35b64644206fcdcc7",
                    "2cc6045a2666c8b4105b1095311f61d6dda74caeae7d402addcc581aefe60810",
                    "ccecf09f51f0d1cdb4758d1b80c708beed42ef00f53dbef9f9a96e8eaa4b67d1",
                ),
            ),
            (
                "v5",
                _paired_commercial_request_payload(),
                (
                    "82ba548de85c209b46a4a2ccb080f978903ad337547963a2a78d8b9e077889a9",
                    "f1ec14f571fe61cf233885e058dc480ea556909b27608cb58a7a0840b1f9dfe8",
                    "16978bbe1c799fed55a4714c3e377cd55760eb3b43aee1642854543da81b4a8c",
                ),
            ),
        )
        for version, payload, expected_hashes in vectors:
            with self.subTest(version=version):
                parsed = TechnoeconomicSubmissionRequest.model_validate(payload)
                request_payload = tea_api.canonical_submission_request_payload(parsed)
                kernel_request = tea_api.build_technoeconomic_kernel_request(
                    request_payload,
                    self.snapshot,
                )
                provenance = tea_api.build_technoeconomic_submission_provenance(
                    request_payload,
                    self.envelope,
                    kernel_request,
                )
                actual_hashes = (
                    tea_api.canonical_json_sha256(request_payload),
                    tea_api.canonical_json_sha256(
                        tea_api.technoeconomic_kernel.canonical_request_payload(
                            kernel_request
                        )
                    ),
                    tea_api.canonical_json_sha256(provenance),
                )

                self.assertEqual(expected_hashes, actual_hashes)
                self.assertEqual(actual_hashes[0], provenance["request_sha256"])
                self.assertEqual(
                    actual_hashes[1],
                    provenance["validated_kernel_request_sha256"],
                )

    def test_v4_standalone_commercial_clipped_capacity_provenance_and_enqueue(self) -> None:
        payload = _standalone_commercial_request_payload()
        parsed = TechnoeconomicSubmissionRequest.model_validate(payload)
        request = tea_api.build_technoeconomic_kernel_request(parsed, self.snapshot)

        self.assertEqual(
            tea_api.technoeconomic_kernel.STANDALONE_COMMERCIAL_CALCULATION_CONTRACT_VERSION,
            request.calculation_contract_version,
        )
        self.assertEqual((), request.cost_lines)
        self.assertEqual(
            [
                ("solectria", 125_000.0, "ac_operating_limit"),
                ("solaredge", 125_000.0, "ac_operating_limit"),
            ],
            [
                (item.system, item.applied_capacity_w, item.rating_basis)
                for item in request.applied_capacities or ()
            ],
        )
        standalone = request.standalone_commercial
        self.assertIsNotNone(standalone)
        self.assertEqual(100_000_000.0, standalone.target_capacity_w)
        self.assertEqual("ac_operating_limit", standalone.target_rating_basis)
        self.assertEqual(
            ["initial_t0", "annual_year_end", "scheduled_year_end"],
            [line.timing for line in standalone.cost_lines],
        )
        self.assertEqual((10, 20), standalone.cost_lines[2].occurrence_years)
        self.assertEqual(2026, request.constant_dollar_cost_year)
        self.assertTrue(
            all(
                line.constant_dollar_cost_year == 2026
                for line in standalone.cost_lines
            )
        )

        provenance = tea_api.build_technoeconomic_submission_provenance(
            parsed,
            self.envelope,
            request,
        )
        self.assertEqual(4, provenance["schema_version"])
        self.assertEqual("technoeconomic-submission-v4", provenance["request_schema"])
        receipt = provenance["standalone_commercial_receipt"]
        self.assertEqual(100_000_000.0, receipt["target_capacity_w"])
        self.assertEqual(125_000.0, receipt["source_capacity"]["applied_capacity_w"])
        self.assertEqual("ac_operating_limit", receipt["source_capacity"]["rating_basis"])
        self.assertEqual(800.0, receipt["capacity_scale_factor"])
        self.assertEqual("full_system", receipt["cost_stack_completeness"])
        self.assertEqual(
            {
                "full_initial_capex": 1,
                "full_annual_om": 1,
                "scheduled_replacement": 1,
            },
            receipt["cost_category_counts"],
        )
        self.assertEqual(
            "full_initial_capex",
            receipt["cost_lines"][0]["cost_category"],
        )
        self.assertEqual(
            ["commercial.solaredge.full-initial-system"],
            receipt["cost_lines"][0]["coverage_ids"],
        )
        self.assertEqual(2026, receipt["cost_lines"][0]["constant_dollar_cost_year"])
        self.assertEqual(
            tea_api.canonical_json_sha256(receipt),
            provenance["standalone_commercial_receipt_sha256"],
        )
        evidence_subjects = {
            item["subject"]
            for item in provenance["evidence_receipt"]["preservation"]
        }
        self.assertIn("standalone-commercial:energy-scaling", evidence_subjects)
        self.assertIn(
            "standalone-commercial-cost:commercial.solaredge.capex",
            evidence_subjects,
        )

        response = self._create_via_api(payload)
        self.assertEqual(202, response.status_code, response.text)
        stored = self.store.get_technoeconomic_job(response.json()["job"]["job_id"])
        self.assertEqual([], stored["request"]["cost_lines"])
        self.assertEqual(
            100.0,
            stored["request"]["standalone_commercial"]["target_capacity"],
        )
        self.assertEqual(
            800.0,
            stored["submission_provenance"]["standalone_commercial_receipt"]
            ["capacity_scale_factor"],
        )

    def test_v4_capacity_fallback_and_rating_basis_mismatch_fail_closed(self) -> None:
        snapshot = deepcopy(self.snapshot)
        snapshot["source_annual_job"]["request"] = {
            "curtailment_enabled": False,
            "curtailment_limit_kw": 125.0,
        }
        payload = _standalone_commercial_request_payload(
            target_rating_basis="dc_installed_nameplate"
        )
        request = tea_api.build_technoeconomic_kernel_request(payload, snapshot)
        source = next(
            item
            for item in request.applied_capacities or ()
            if item.system == "solaredge"
        )
        expected_wdc = snapshot["capacity_manifest"]["systems"]["solaredge"][
            "installed_wdc"
        ]
        self.assertEqual(expected_wdc, source.applied_capacity_w)
        self.assertEqual("dc_installed_nameplate", source.rating_basis)

        mismatched = _standalone_commercial_request_payload(
            target_rating_basis="dc_installed_nameplate"
        )
        response = self._create_via_api(mismatched)
        self.assertEqual(422, response.status_code, response.text)
        self.assertIn("rating basis", response.text.lower())

    def test_v4_standalone_schema_rejects_mixed_and_mistimed_cost_stacks(self) -> None:
        mixed = _standalone_commercial_request_payload()
        mixed["cost_lines"] = deepcopy(_applied_site_request_payload()["cost_lines"])
        mixed_v3 = _standalone_commercial_request_payload()
        mixed_v3["commercial_scaling"] = deepcopy(
            _commercial_scaling_request_payload()["commercial_scaling"]
        )
        mistimed = _standalone_commercial_request_payload()
        mistimed["standalone_commercial"]["cost_lines"][1]["unit"] = (
            "constant_usd_per_target_w"
        )
        unscheduled = _standalone_commercial_request_payload()
        unscheduled["standalone_commercial"]["cost_lines"][2][
            "occurrence_years"
        ] = []
        out_of_life = _standalone_commercial_request_payload()
        out_of_life["standalone_commercial"]["cost_lines"][2][
            "occurrence_years"
        ] = [21]

        duplicate_capex = _standalone_commercial_request_payload()
        second_capex = deepcopy(
            duplicate_capex["standalone_commercial"]["cost_lines"][0]
        )
        second_capex["input_id"] = "commercial.solaredge.capex.duplicate"
        second_capex["coverage_ids"] = [
            "commercial.solaredge.full-initial-system.duplicate"
        ]
        duplicate_capex["standalone_commercial"]["cost_lines"].append(
            second_capex
        )

        missing_capex = _standalone_commercial_request_payload()
        missing_capex["standalone_commercial"]["cost_lines"] = [
            line
            for line in missing_capex["standalone_commercial"]["cost_lines"]
            if line["cost_category"] != "full_initial_capex"
        ]
        missing_om = _standalone_commercial_request_payload()
        missing_om["standalone_commercial"]["cost_lines"] = [
            line
            for line in missing_om["standalone_commercial"]["cost_lines"]
            if line["cost_category"] != "full_annual_om"
        ]

        overlapping_replacement = _standalone_commercial_request_payload()
        second_replacement = deepcopy(
            overlapping_replacement["standalone_commercial"]["cost_lines"][2]
        )
        second_replacement["input_id"] = (
            "commercial.solaredge.replacement.duplicate"
        )
        second_replacement["occurrence_years"] = [20]
        overlapping_replacement["standalone_commercial"]["cost_lines"].append(
            second_replacement
        )
        mismatched_cost_year = _standalone_commercial_request_payload()
        mismatched_cost_year["standalone_commercial"]["cost_lines"][0][
            "constant_dollar_cost_year"
        ] = 2025

        for invalid in (
            mixed,
            mixed_v3,
            mistimed,
            unscheduled,
            out_of_life,
            duplicate_capex,
            missing_capex,
            missing_om,
            overlapping_replacement,
            mismatched_cost_year,
        ):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValidationError):
                    TechnoeconomicSubmissionRequest.model_validate(invalid)

    def test_v2_site_request_falls_back_to_installed_dc_without_clipping(self) -> None:
        cases = (
            (False, 125.0),
            (True, None),
            (True, "invalid"),
            (True, 0.0),
            (True, -1.0),
            (True, float("inf")),
            (True, float("nan")),
            (True, True),
        )
        for enabled, raw_limit in cases:
            with self.subTest(enabled=enabled, raw_limit=raw_limit):
                snapshot = deepcopy(self.snapshot)
                snapshot["source_annual_job"]["request"] = {
                    "curtailment_enabled": enabled,
                    "curtailment_limit_kw": raw_limit,
                }
                kernel_request = tea_api.build_technoeconomic_kernel_request(
                    _applied_site_request_payload(),
                    snapshot,
                )
                installed = snapshot["capacity_manifest"]["systems"]

                self.assertEqual(
                    [
                        (
                            system,
                            installed[system]["installed_wdc"],
                            "dc_installed_nameplate",
                        )
                        for system in ("solectria", "solaredge")
                    ],
                    [
                        (item.system, item.applied_capacity_w, item.rating_basis)
                        for item in kernel_request.applied_capacities or ()
                    ],
                )

    def test_missing_discriminator_preserves_legacy_kernel_payload(self) -> None:
        kernel_request = tea_api.build_technoeconomic_kernel_request(
            _site_request_payload(),
            self.snapshot,
        )

        self.assertEqual(
            "tea-calculation-v1",
            kernel_request.calculation_contract_version,
        )
        self.assertIsNone(kernel_request.applied_capacities)
        self.assertNotIn(
            "applied_capacities",
            tea_api.technoeconomic_kernel.canonical_request_payload(kernel_request),
        )

    def test_commercial_request_rejects_applied_watt_unit_labels(self) -> None:
        payload = _commercial_request_payload(include_transfer=False)
        payload["cost_lines"][0]["normalized_unit"] = "usd_per_applied_w"

        with self.assertRaises(ValidationError) as raised:
            TechnoeconomicSubmissionRequest.model_validate(payload)

        self.assertIn("sourced per-Wdc basis", str(raised.exception))

    def test_strict_schema_rejects_xml_illegal_text_before_enqueue(self) -> None:
        valid = _site_request_payload()
        allowed_whitespace = deepcopy(valid)
        allowed_whitespace["cost_lines"][0]["label"] = (
            "Embedded tab\tline feed\nand carriage return\rremain valid"
        )
        parsed = TechnoeconomicSubmissionRequest.model_validate(allowed_whitespace)
        self.assertIn("\t", parsed.cost_lines[0].label)
        self.assertIn("\n", parsed.cost_lines[0].label)
        self.assertIn("\r", parsed.cost_lines[0].label)

        for illegal_character in ("\x00", "\x0b", "\x1f", "\ud800", "\ufffe", "\uffff"):
            invalid = deepcopy(valid)
            invalid["cost_lines"][0]["evidence"]["citation"][
                "excerpt_or_derivation_note"
            ] = f"Invalid export text {illegal_character} must be rejected"
            with self.assertRaises(ValidationError) as raised:
                TechnoeconomicSubmissionRequest.model_validate(invalid)
            if illegal_character != "\ud800":
                self.assertIn("not valid in XML 1.0", str(raised.exception))

        http_invalid = deepcopy(valid)
        http_invalid["cost_lines"][0]["label"] = "Invalid vertical tab\x0b"
        response = self._create_via_api(http_invalid)
        self.assertEqual(422, response.status_code, response.text)
        self.assertEqual([], self.store.list_technoeconomic_jobs())
        state._WORKER_WAKE.set.assert_not_called()

    def test_strict_schema_enforces_pre_enqueue_resource_budgets(self) -> None:
        normal_maximum_n = _site_request_payload(n=100_000)
        parsed = TechnoeconomicSubmissionRequest.model_validate(normal_maximum_n)
        self.assertEqual(100_000, parsed.n)

        def expanded_payload(line_count: int, *, uncertain: bool) -> dict:
            payload = _site_request_payload(n=100_000)
            while len(payload["cost_lines"]) < line_count:
                index = len(payload["cost_lines"])
                line = deepcopy(payload["cost_lines"][0])
                line["input_id"] = f"cost.sol.extra-{index:03d}"
                line["label"] = f"Additional Solectria cost {index}"
                line["coverage_include_ids"] = [f"equipment.sol.extra-{index:03d}"]
                payload["cost_lines"].append(line)
            if uncertain:
                for line in payload["cost_lines"]:
                    line["distribution"] = {
                        "family": "uniform",
                        "low": 1.0,
                        "high": 2.0,
                    }
            return payload

        excessive_cells = expanded_payload(31, uncertain=False)
        excessive_sensitivity = expanded_payload(16, uncertain=True)
        invalid_payloads = (
            (excessive_cells, "realization export cell budget exceeded"),
            (excessive_sensitivity, "sensitivity work budget exceeded"),
        )
        for payload, message in invalid_payloads:
            with self.assertRaisesRegex(ValidationError, message):
                TechnoeconomicSubmissionRequest.model_validate(payload)
            response = self._create_via_api(payload)
            self.assertEqual(422, response.status_code, response.text)

        v3_fixed_output_overhead = _commercial_scaling_request_payload()
        v3_fixed_output_overhead["n"] = 100_000
        while len(v3_fixed_output_overhead["cost_lines"]) < 22:
            index = len(v3_fixed_output_overhead["cost_lines"])
            line = deepcopy(v3_fixed_output_overhead["cost_lines"][0])
            line["input_id"] = f"cost.sol.v3-extra-{index:03d}"
            line["label"] = f"Additional V3 Solectria cost {index}"
            line["coverage_include_ids"] = [f"equipment.sol.v3-extra-{index:03d}"]
            v3_fixed_output_overhead["cost_lines"].append(line)
        with self.assertRaisesRegex(
            ValidationError,
            "realization export cell budget exceeded",
        ):
            TechnoeconomicSubmissionRequest.model_validate(v3_fixed_output_overhead)

        self.assertEqual([], self.store.list_technoeconomic_jobs())
        state._WORKER_WAKE.set.assert_not_called()

    def test_site_receipts_freeze_denominators_currency_and_pair_decisions(self) -> None:
        payload = _site_request_payload()
        shared = deepcopy(payload["cost_lines"][0])
        shared.update(
            {
                "input_id": "cost.shared.capex",
                "label": "Disjoint shared site scope",
                "ownership": "paired_shared",
                "distribution": {"family": "fixed", "value": 10_000.0},
                "coverage_include_ids": ["equipment.shared"],
                "coverage_exclude_ids": [
                    "equipment.solectria",
                    "equipment.solaredge",
                ],
                "solectria_quantity": 1.0,
                "solaredge_quantity": 1.0,
                "normalization_derivation": (
                    "Divide the disjoint shared total by each frozen system Wdc."
                ),
            }
        )
        payload["cost_lines"].append(shared)
        kernel_request = tea_api.build_technoeconomic_kernel_request(
            payload,
            self.snapshot,
        )
        provenance = tea_api.build_technoeconomic_submission_provenance(
            payload,
            self.envelope,
            kernel_request,
        )

        normalization = {
            line["input_id"]: line
            for line in provenance["normalization_receipt"]["lines"]
        }
        sol_receipt = normalization["cost.sol.capex"]
        self.assertEqual(
            model.capacity_manifest()["systems"]["solectria"]["installed_wdc"],
            sol_receipt["wdc_denominator"]["solectria"]["installed_wdc"],
        )
        self.assertTrue(sol_receipt["wdc_denominator"]["solectria"]["applied"])
        self.assertEqual(
            1.0,
            sol_receipt["documented_pre_submission_index_factor"],
        )

        overlap = provenance["overlap_receipt"]
        pair = next(
            decision
            for decision in overlap["pairwise_decisions"]
            if {
                decision["left_input_id"],
                decision["right_input_id"],
            }
            == {"cost.sol.capex", "cost.shared.capex"}
        )
        self.assertTrue(pair["potentially_overlapping"])
        self.assertEqual("disjoint_by_declared_exclusion", pair["decision"])
        self.assertFalse(pair["overlap_detected"])

    def test_guided_separate_system_totals_normalize_through_frozen_wdc(self) -> None:
        payload = _site_request_payload()
        systems = self.snapshot["capacity_manifest"]["systems"]
        sol_wdc = systems["solectria"]["installed_wdc"]
        se_wdc = systems["solaredge"]["installed_wdc"]

        def guided_line(
            *,
            input_id: str,
            label: str,
            ownership: str,
            cost_type: str,
            value: float,
            coverage_id: str,
        ) -> dict:
            recurring = cost_type.startswith("recurring_")
            solaredge = ownership == "solaredge_only"
            return {
                "input_id": input_id,
                "label": label,
                "ownership": ownership,
                "cost_type": cost_type,
                "distribution": {"family": "fixed", "value": value},
                "coverage_include_ids": [coverage_id],
                "coverage_exclude_ids": [],
                "original_unit": "usd_total_per_year" if recurring else "usd_total",
                "normalized_unit": (
                    "usd_per_wdc_year" if recurring else "usd_per_wdc"
                ),
                "normalization_method": "divide_by_frozen_source_wdc",
                "solectria_quantity": 0.0 if solaredge else 1.0,
                "solaredge_quantity": 1.0 if solaredge else 0.0,
                "quantity_unit": None,
                "normalization_derivation": (
                    "Divide the submitted system total by the applicable system's "
                    "verified frozen Annual Simulation Wdc nameplate."
                ),
                "constant_dollar_cost_year": 2026,
                "currency_year_normalization": _currency_year_normalization(),
                "evidence": _evidence(),
            }

        payload["cost_lines"] = [
            guided_line(
                input_id="cost.guided.solectria-capex",
                label="Solectria total installed CAPEX",
                ownership="solectria_only",
                cost_type="initial_capex",
                value=200_000.0,
                coverage_id="scope.guided.solectria.initial",
            ),
            guided_line(
                input_id="cost.guided.solectria-recurring-om",
                label="Solectria annual O&M",
                ownership="solectria_only",
                cost_type="recurring_om",
                value=5_000.0,
                coverage_id="scope.guided.solectria.recurring",
            ),
            guided_line(
                input_id="cost.guided.solaredge-capex",
                label="SolarEdge total installed CAPEX",
                ownership="solaredge_only",
                cost_type="initial_capex",
                value=215_000.0,
                coverage_id="scope.guided.solaredge.initial",
            ),
            guided_line(
                input_id="cost.guided.solaredge-recurring-om",
                label="SolarEdge annual O&M",
                ownership="solaredge_only",
                cost_type="recurring_om",
                value=4_500.0,
                coverage_id="scope.guided.solaredge.recurring",
            ),
        ]

        parsed = TechnoeconomicSubmissionRequest.model_validate(payload)
        kernel_request = tea_api.build_technoeconomic_kernel_request(
            parsed,
            self.snapshot,
        )
        lines = {line.input_id: line for line in kernel_request.cost_lines}

        for input_id in (
            "cost.guided.solectria-capex",
            "cost.guided.solectria-recurring-om",
        ):
            self.assertAlmostEqual(
                1.0 / sol_wdc,
                lines[input_id].solectria_multiplier_to_intensity,
            )
            self.assertEqual(0.0, lines[input_id].solaredge_multiplier_to_intensity)
        for input_id in (
            "cost.guided.solaredge-capex",
            "cost.guided.solaredge-recurring-om",
        ):
            self.assertEqual(0.0, lines[input_id].solectria_multiplier_to_intensity)
            self.assertAlmostEqual(
                1.0 / se_wdc,
                lines[input_id].solaredge_multiplier_to_intensity,
            )

        provenance = tea_api.build_technoeconomic_submission_provenance(
            parsed,
            self.envelope,
            kernel_request,
        )
        receipts = {
            line["input_id"]: line
            for line in provenance["normalization_receipt"]["lines"]
        }
        sol_capex = receipts["cost.guided.solectria-capex"]
        se_capex = receipts["cost.guided.solaredge-capex"]
        self.assertIsNone(sol_capex["quantity_unit"])
        self.assertEqual(1.0, sol_capex["solectria_quantity"])
        self.assertEqual(0.0, sol_capex["solaredge_quantity"])
        self.assertTrue(sol_capex["wdc_denominator"]["solectria"]["applied"])
        self.assertFalse(sol_capex["wdc_denominator"]["solaredge"]["applied"])
        self.assertEqual(0.0, se_capex["solectria_quantity"])
        self.assertEqual(1.0, se_capex["solaredge_quantity"])
        self.assertFalse(se_capex["wdc_denominator"]["solectria"]["applied"])
        self.assertTrue(se_capex["wdc_denominator"]["solaredge"]["applied"])
        self.assertEqual(
            "divide_by_frozen_source_wdc",
            se_capex["normalization_method"],
        )

    def test_commercial_cost_only_and_indexed_normalization_are_explicit(self) -> None:
        payload = _commercial_request_payload(include_transfer=False)
        parsed = TechnoeconomicSubmissionRequest.model_validate(payload)
        self.assertIsNone(parsed.commercial_transfer)
        kernel_request = tea_api.build_technoeconomic_kernel_request(
            payload,
            self.snapshot,
        )
        self.assertIsNone(kernel_request.transfer)
        sol_line = next(
            line for line in kernel_request.cost_lines if line.input_id == "cost.sol.capex"
        )
        self.assertAlmostEqual(1.0, sol_line.solectria_multiplier_to_intensity)
        self.assertAlmostEqual(0.825, sol_line.distribution.value)

        provenance = tea_api.build_technoeconomic_submission_provenance(
            payload,
            self.envelope,
            kernel_request,
        )
        self.assertEqual("cost_only", provenance["commercial_transfer_status"])
        self.assertEqual(
            "cost_only",
            provenance["commercial_transfer_receipt"]["status"],
        )
        reference = provenance["commercial_reference_design"]
        self.assertEqual("commercial.fixture.v1", reference["design_id"])
        self.assertEqual(420_000.0, reference["reference_wdc"])
        self.assertEqual(
            reference["design_sha256"],
            provenance["commercial_reference_design_sha256"],
        )
        indexed_receipt = next(
            line
            for line in provenance["normalization_receipt"]["lines"]
            if line["input_id"] == "cost.sol.capex"
        )
        self.assertEqual(
            "price_index_adjustment",
            indexed_receipt["currency_year_normalization"]["method"],
        )
        self.assertEqual(
            1.1,
            indexed_receipt["documented_pre_submission_index_factor"],
        )
        self.assertEqual(
            "declared_commercial_per_wdc_basis",
            indexed_receipt["wdc_denominator"]["method"],
        )
        self.assertIn(
            "cost-currency-index:cost.sol.capex",
            {
                item["subject"]
                for item in provenance["evidence_receipt"]["preservation"]
            },
        )

    def test_commercial_transfer_requires_resolved_mechanisms(self) -> None:
        valid = _commercial_request_payload(include_transfer=True)
        kernel_request = tea_api.build_technoeconomic_kernel_request(
            valid,
            self.snapshot,
        )
        self.assertIsNotNone(kernel_request.transfer)
        provenance = tea_api.build_technoeconomic_submission_provenance(
            valid,
            self.envelope,
            kernel_request,
        )
        transfer = provenance["commercial_transfer_receipt"]
        self.assertEqual("approved", transfer["status"])
        self.assertTrue(transfer["all_mechanisms_resolved"])
        self.assertEqual(
            "commercial.fixture.v1",
            transfer["commercial_reference_design"]["design_id"],
        )

        unresolved = deepcopy(valid)
        unresolved["commercial_transfer"]["mechanisms"][0]["status"] = (
            "not_transferred"
        )
        with self.assertRaises(ValidationError):
            TechnoeconomicSubmissionRequest.model_validate(unresolved)
        response = self._create_via_api(unresolved)
        self.assertEqual(422, response.status_code, response.text)
        self.assertEqual([], self.store.list_technoeconomic_jobs())
        state._WORKER_WAKE.set.assert_not_called()

    def test_create_derives_kernel_inputs_enqueues_and_wakes_after_insert(self) -> None:
        response = self._create_via_api()
        self.assertEqual(202, response.status_code, response.text)
        public = response.json()["job"]
        job_id = public["job_id"]
        stored = self.store.get_technoeconomic_job(job_id)
        self.assertEqual("queued", stored["state"])
        self.assertNotIn("paired_energy_rows", stored["request"])
        self.assertNotIn("capacities", stored["request"])
        self.assertNotIn("commercial_scaling", stored["request"])
        self.assertNotIn(job_id, state.JOBS)
        state._WORKER_WAKE.set.assert_called_once_with()

        self.assertEqual(404, self.client.get(f"/api/status/{job_id}").status_code)
        self.assertEqual(
            404,
            self.client.post(f"/api/jobs/{job_id}/promote").status_code,
        )

    def test_source_tampering_fails_without_insert_or_wake(self) -> None:
        error = tea_api.AnnualSourceValidationError(
            "annual_source_artifact_hash_mismatch",
            "The immutable Annual source changed.",
        )
        dependencies = {
            "annual_job": self.annual,
            "origin_validation_job": {},
            "promotion_record": {},
        }
        with (
            patch.object(
                tea_api,
                "resolve_annual_source_dependencies",
                return_value=dependencies,
            ),
            patch.object(
                tea_api,
                "build_annual_source_snapshot",
                side_effect=error,
            ),
        ):
            response = self.client.post(
                "/api/technoeconomic/jobs",
                json=_applied_site_request_payload(),
            )
        self.assertEqual(409, response.status_code)
        self.assertEqual([], self.store.list_technoeconomic_jobs())
        state._WORKER_WAKE.set.assert_not_called()

    def test_kernel_validation_error_is_422(self) -> None:
        payload = _site_request_payload()
        payload["cost_lines"][0]["distribution"]["value"] = -1.0
        response = self._create_via_api(payload)
        self.assertEqual(422, response.status_code, response.text)
        self.assertEqual([], self.store.list_technoeconomic_jobs())
        state._WORKER_WAKE.set.assert_not_called()

    def test_global_queue_capacity_is_enforced(self) -> None:
        self.store.create_job(
            job_id="queued-model",
            kind="manual",
            mode="validation",
            request={"fixture": True},
        )
        with patch.object(config, "MAX_ACTIVE_MODEL_JOBS", 1):
            response = self._create_via_api()
        self.assertEqual(429, response.status_code, response.text)
        state._WORKER_WAKE.set.assert_not_called()

    def test_eligible_sources_are_calibrated_and_public_safe(self) -> None:
        self.store.cancel_job("queued-model") if self.store.get_job("queued-model") else None
        self._completed_annual("annual-physics", calibrated=False)
        dependencies = {
            "annual_job": self.annual,
            "origin_validation_job": {},
            "promotion_record": {},
        }
        eligibility = {
            "eligible": True,
            "reason_code": None,
            "detail": None,
            "source_annual_job_id": "annual-source",
            "eligible_years": [2024],
            "solectria_installed_wdc": 139_180.8,
            "solaredge_installed_wdc": 139_180.8,
            "annual_energy_by_year": [
                {
                    "year": 2024,
                    "solectria_kwh": 200_000.0,
                    "solaredge_kwh": 215_000.0,
                }
            ],
            "capacity_manifest_source": "explicit_annual_manifest",
            "source_snapshot_sha256": "2" * 64,
            "source_artifact_storage_key": "private/secret.csv",
            "path": str(self.test_root / "private.csv"),
        }
        with (
            patch.object(
                tea_api,
                "resolve_annual_source_dependencies",
                return_value=dependencies,
            ),
            patch.object(
                tea_api,
                "inspect_annual_source_eligibility",
                return_value=eligibility,
            ),
        ):
            response = self.client.get("/api/technoeconomic/sources")
        self.assertEqual(200, response.status_code, response.text)
        body = response.json()
        self.assertEqual(["annual-source"], [row["source_annual_job_id"] for row in body["sources"]])
        source = body["sources"][0]
        self.assertEqual(
            [
                {
                    "year": 2024,
                    "solectria_kwh": 200_000.0,
                    "solaredge_kwh": 215_000.0,
                }
            ],
            source["annual_energy_by_year"],
        )
        self.assertEqual(
            {
                "curtailment_enabled": True,
                "curtailment_limit_kw": 125.0,
                "unit": "kWac",
            },
            source["provenance"]["operating_limit"],
        )
        encoded = json.dumps(body)
        self.assertNotIn("storage_key", encoded)
        self.assertNotIn(str(self.test_root), encoded)
        self.assertNotIn("annual-physics", encoded)

    def test_status_cancel_retry_delete_and_confined_cleanup(self) -> None:
        created = self._create_via_api().json()["job"]
        job_id = created["job_id"]
        status = self.client.get(f"/api/technoeconomic/jobs/{job_id}")
        self.assertEqual(200, status.status_code)
        self.assertNotIn("source_snapshot", status.json())
        self.assertNotIn("storage_key", status.text)

        cancelled = self.client.post(
            f"/api/technoeconomic/jobs/{job_id}/cancel"
        )
        self.assertEqual("cancelled", cancelled.json()["job"]["state"])
        retried = self.client.post(
            f"/api/technoeconomic/jobs/{job_id}/retry"
        )
        self.assertEqual(202, retried.status_code)
        retry_id = retried.json()["job"]["job_id"]
        self.client.post(f"/api/technoeconomic/jobs/{retry_id}/cancel")
        self.assertEqual(
            200,
            self.client.delete(f"/api/technoeconomic/jobs/{retry_id}").status_code,
        )

        attempt = _technoeconomic_attempt_directory(
            job_id,
            "lease_fixture",
            create=True,
        )
        (attempt / "owned.bin").write_bytes(b"owned")
        unrelated = self.output / "unrelated.bin"
        unrelated.write_bytes(b"keep")
        deleted = self.client.delete(f"/api/technoeconomic/jobs/{job_id}")
        self.assertEqual(200, deleted.status_code, deleted.text)
        self.assertEqual(1, deleted.json()["artifacts_deleted"])
        self.assertTrue(unrelated.is_file())
        self.assertIsNone(self.store.get_technoeconomic_job(job_id))

    def test_running_status_excludes_lease_snapshot_storage_and_paths(self) -> None:
        created = self._create_via_api().json()["job"]
        job_id = created["job_id"]
        claimed = self.store.claim_next_queued_work(worker_id="private-worker")
        self.assertEqual(job_id, claimed["id"])
        self.store.update_technoeconomic_job(
            job_id,
            expected_worker_id="private-worker",
            expected_lease_token=claimed["lease_token"],
            result={
                "safe_summary": {"row_count": 8},
                "storage_key": "private/secret.npz",
                "source_snapshot": {"private_marker": "never-public"},
                "path": str(self.test_root / "private.npz"),
            },
            artifacts={
                "sealed_calculation": {
                    "sha256": "a" * 64,
                    "row_count": 8,
                    "storage_key": "private/secret.npz",
                }
            },
        )

        response = self.client.get(f"/api/technoeconomic/jobs/{job_id}")
        self.assertEqual(200, response.status_code, response.text)
        payload = response.json()
        encoded = response.text
        self.assertEqual(8, payload["result"]["safe_summary"]["row_count"])
        self.assertNotIn("source_snapshot", payload)
        for secret in (
            claimed["lease_token"],
            "private-worker",
            "private/secret.npz",
            "never-public",
            str(self.test_root),
        ):
            self.assertNotIn(secret, encoded)

    def test_lifecycle_routes_map_missing_active_and_retry_conflicts(self) -> None:
        missing = "tea_missing_fixture"
        self.assertEqual(
            404,
            self.client.get(f"/api/technoeconomic/jobs/{missing}").status_code,
        )
        self.assertEqual(
            404,
            self.client.post(
                f"/api/technoeconomic/jobs/{missing}/cancel"
            ).status_code,
        )
        self.assertEqual(
            404,
            self.client.post(
                f"/api/technoeconomic/jobs/{missing}/retry"
            ).status_code,
        )
        self.assertEqual(
            404,
            self.client.delete(f"/api/technoeconomic/jobs/{missing}").status_code,
        )
        state._WORKER_WAKE.set.assert_not_called()

        created = self._create_via_api().json()["job"]
        job_id = created["job_id"]
        self.assertEqual(
            409,
            self.client.post(
                f"/api/technoeconomic/jobs/{job_id}/retry"
            ).status_code,
        )
        self.assertEqual(
            409,
            self.client.delete(f"/api/technoeconomic/jobs/{job_id}").status_code,
        )

        self.client.post(f"/api/technoeconomic/jobs/{job_id}/cancel")
        retried = self.client.post(
            f"/api/technoeconomic/jobs/{job_id}/retry"
        )
        self.assertEqual(202, retried.status_code, retried.text)
        retry_id = retried.json()["job"]["job_id"]
        self.client.post(f"/api/technoeconomic/jobs/{retry_id}/cancel")

        dependent = self.client.delete(
            f"/api/technoeconomic/jobs/{job_id}"
        )
        self.assertEqual(409, dependent.status_code, dependent.text)
        self.assertIsNotNone(self.store.get_technoeconomic_job(job_id))
        self.assertEqual(
            200,
            self.client.delete(
                f"/api/technoeconomic/jobs/{retry_id}"
            ).status_code,
        )
        self.assertEqual(
            200,
            self.client.delete(f"/api/technoeconomic/jobs/{job_id}").status_code,
        )


if __name__ == "__main__":
    unittest.main()
