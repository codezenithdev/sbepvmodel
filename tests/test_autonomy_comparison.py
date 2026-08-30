from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from sbepv import technoeconomic as tea
from sbepv import technoeconomic_reporting as reporting
from sbepv.api import config
from sbepv.api import technoeconomic as tea_api
from sbepv.autonomy import comparison
from sbepv.autonomy import recommendation
from sbepv.autonomy import result_verification
from sbepv.worker import run_technoeconomic


def _sha(value: object) -> str:
    return tea_api.canonical_json_sha256(value)


def _available_summary(
    *,
    p5: float = 1.0,
    p50: float = 2.0,
    p95: float = 3.0,
) -> tuple[dict, dict]:
    compact = {
        "status": "available",
        "reason": None,
        "count": 3,
        "percentiles": {"p5": p5, "p50": p50, "p95": p95},
        "cdf": {
            "population_count": 3,
            "point_count": 3,
            "storage": "sealed_calculation_payload",
        },
    }
    sealed = deepcopy(compact)
    sealed["cdf"] = {
        "values": [p5, p50, p95],
        "cumulative_count": [1, 2, 3],
        "cumulative_probability": [1 / 3, 2 / 3, 1.0],
        "population_count": 3,
    }
    return compact, sealed


def _unavailable_summary(
    reason: str = "commercial_energy_transfer_unavailable",
) -> tuple[dict, dict]:
    value = {
        "status": "unavailable",
        "reason": reason,
        "count": 0,
        "percentiles": {"p5": None, "p50": None, "p95": None},
        "cdf": None,
    }
    return deepcopy(value), deepcopy(value)


def _metric_ids(contract_version: str) -> list[str]:
    if contract_version == tea.LEGACY_CALCULATION_CONTRACT_VERSION:
        normalized = [
            tea.FIELD_DELTA_COST,
            tea.FIELD_DELTA_EA_COST,
            tea.FIELD_DELTA_ENERGY,
            tea.FIELD_DELTA_EA_ENERGY,
        ]
    else:
        normalized = [
            tea.APPLIED_FIELD_DELTA_COST,
            tea.APPLIED_FIELD_DELTA_EA_COST,
            tea.APPLIED_FIELD_DELTA_ENERGY,
            tea.APPLIED_FIELD_DELTA_EA_ENERGY,
        ]
    result = [
        *normalized,
        tea.FIELD_LCOE_SOL,
        tea.FIELD_LCOE_SE,
        "headline_positive_gain_lcoo",
        "signed_nonzero_lcoo",
    ]
    if contract_version == tea.COMMERCIAL_SCALING_CALCULATION_CONTRACT_VERSION:
        result.extend(
            [
                tea.COMMERCIAL_FIELD_TARGET_CAPACITY,
                tea.COMMERCIAL_FIELD_YEAR1_DELTA_ENERGY,
                tea.COMMERCIAL_FIELD_LIFECYCLE_DELTA_ENERGY,
                tea.COMMERCIAL_FIELD_EA_DELTA_ENERGY,
                tea.COMMERCIAL_FIELD_LIFECYCLE_MARGINAL_COST,
                tea.COMMERCIAL_FIELD_EA_MARGINAL_COST,
                tea.COMMERCIAL_FIELD_MARGINAL_LCOO,
            ]
        )
    return result


def _verified_outcome(
    job_id: str,
    *,
    contract_version: str = tea.CALCULATION_CONTRACT_VERSION,
    source_snapshot_sha256: str = "2" * 64,
    request: dict | None = None,
) -> result_verification.ResultVerificationOutcome:
    request = request or {"basis": "solartac_site", "value": 1.0}
    summaries: dict[str, object] = {}
    sealed_summaries: dict[str, object] = {}
    for index, metric_id in enumerate(_metric_ids(contract_version)):
        if metric_id == tea.FIELD_LCOE_SE:
            routine, sealed = _unavailable_summary()
        elif metric_id == "signed_nonzero_lcoo":
            routine, sealed = _available_summary(p5=-3.0, p50=-2.0, p95=-1.0)
        else:
            routine, sealed = _available_summary(
                p5=float(index + 1),
                p50=float(index + 2),
                p95=float(index + 3),
            )
        summaries[metric_id] = routine
        sealed_summaries[metric_id] = sealed
    summaries["energy_classes"] = {
        "denominator": 3,
        "counts": {
            "positive_lifecycle_gain": 1,
            "zero_lifecycle_gain": 1,
            "negative_lifecycle_gain": 1,
        },
        "probabilities": {
            "positive_lifecycle_gain": 1 / 3,
            "zero_lifecycle_gain": 1 / 3,
            "negative_lifecycle_gain": 1 / 3,
        },
    }
    summaries["tradeoff_classes"] = {
        "denominator": 3,
        "counts": {
            value: (1 if index < 3 else 0)
            for index, value in enumerate(tea.TRADEOFF_CLASSES)
        },
        "probabilities": {
            value: (1 / 3 if index < 3 else 0.0)
            for index, value in enumerate(tea.TRADEOFF_CLASSES)
        },
    }
    sensitivity = {
        "lifecycle_cost_delta_se_minus_sol": {
            "status": "available",
            "reason": None,
            "sample_count": 40,
            "minimum_sample_count": 20,
            "candidate_predictor_count": 2,
            "entered_predictor_count": 2,
            "steps": [
                {
                    "entry_order": 1,
                    "predictor_id": "cost.first",
                    "incremental_r_squared": 0.4,
                    "cumulative_r_squared": 0.4,
                    "standardized_beta": 0.6,
                    "sign": "positive",
                },
                {
                    "entry_order": 2,
                    "predictor_id": "cost.second",
                    "incremental_r_squared": 0.2,
                    "cumulative_r_squared": 0.6,
                    "standardized_beta": -0.3,
                    "sign": "negative",
                },
            ],
            "exclusions": {"fixed.input": {"reason": "fixed_input"}},
            "warnings": [
                {
                    "code": "high_pairwise_rank_correlation",
                    "left_predictor": "cost.first",
                    "right_predictor": "cost.second",
                    "correlation": 0.98,
                }
            ],
            "final_r_squared": 0.6,
            "minimum_entry_improvement": 1e-6,
            "r_squared_tie_absolute_tolerance": 1e-12,
        }
    }
    convergence = {
        "status": "not_demonstrated",
        "reasons": ["relative_quantile_change:metric:p50"],
        "checkpoints": [
            {
                "realization_count": 3,
                "metrics": {
                    "metric": {
                        "population_count": 3,
                        "percentiles": {"p5": 1.0, "p50": 2.0, "p95": 3.0},
                        "change_from_previous": {
                            value: {"absolute": None, "relative": None}
                            for value in ("p5", "p50", "p95")
                        },
                    }
                },
                "energy_class_probabilities": None,
                "tradeoff_probabilities": None,
                "weather_year_counts": {"2024": 3},
                "weather_year_shares": {"2024": 1.0},
            }
        ],
        "relative_change_threshold": 0.01,
        "class_probability_change_threshold": 0.001,
        "metric_absolute_tolerances": {"metric": 0.0001},
    }
    reporting_tie_outs = {
        "status": "passed",
        "failed_check_ids": [],
        "check_count": 0,
        "realization_row_count": 3,
    }
    result = {
        "schema_version": (
            3
            if contract_version
            == tea.COMMERCIAL_SCALING_CALCULATION_CONTRACT_VERSION
            else 2
            if contract_version == tea.CALCULATION_CONTRACT_VERSION
            else 1
        ),
        "calculation_contract_version": contract_version,
        "sampling_version": tea.SAMPLING_VERSION,
        "analysis_basis": "solartac_site",
        "energy_available": True,
        "input_status": "documented_inputs",
        "evidence_class_counts": {"direct_quote": 1},
        "source_snapshot_sha256": source_snapshot_sha256,
        "capacity_basis": "frozen_annual_applied_capacity_w",
        "capacities": {},
        "summaries": summaries,
        "per_weather_year": [
            {
                "year": 2024,
                "realization_count": 0,
                "reason": "no_realizations_assigned",
                "metrics": {},
            }
        ],
        "sensitivity": sensitivity,
        "convergence": convergence,
        "common_cost_audit": [],
        "exports": {
            "manifest_sha256": "8" * 64,
            "tie_outs": reporting_tie_outs,
        },
    }
    if contract_version != tea.LEGACY_CALCULATION_CONTRACT_VERSION:
        result["applied_capacities"] = {}
    if contract_version == tea.COMMERCIAL_SCALING_CALCULATION_CONTRACT_VERSION:
        result["commercial_scaling"] = {
            "target_capacity_w": 1_000_000.0,
            "target_rating_basis": "dc_installed_nameplate",
        }
    result_provenance = {
        "request_sha256": _sha(request),
        "source_snapshot_sha256": source_snapshot_sha256,
        "submission_provenance_sha256": "3" * 64,
        "validated_kernel_request_sha256": "4" * 64,
        "routine_result_sha256": _sha(result),
        "sealed_calculation": {"sha256": "5" * 64},
        "exports": {"manifest_sha256": "8" * 64},
        "source_annual_job_id": "annual-source",
        "source_artifact": {
            "sha256": "6" * 64,
            "byte_count": 100,
            "media_type": "text/csv",
            "immutable": True,
        },
        "kernel": {
            "calculation_contract_version": contract_version,
            "sampling_version": tea.SAMPLING_VERSION,
            "analysis_basis": "solartac_site",
            "realization_count": 3,
            "energy_status": "available",
            "numerics": {
                "contract_version": tea.NUMERICAL_CONTRACT_VERSION,
                "probe_digests": deepcopy(tea.NUMERICAL_PROBE_DIGESTS),
            }
        },
    }
    verified = result_verification.VerifiedTechnoeconomicResult(
        tea_job_id=job_id,
        result=result,
        result_provenance=result_provenance,
        sealed_metadata={"summaries": sealed_summaries},
        reporting_checks=(),
        evidence_receipts=(),
        evidence_set_sha256=_sha([]),
        reporting_tieout_sha256=_sha(
            {
                "manifest_sha256": "8" * 64,
                "tie_outs": reporting_tie_outs,
            }
        ),
    )
    return result_verification.ResultVerificationOutcome(
        status="verified",
        tea_job_id=job_id,
        checks=({"code": "all_verified", "status": "passed"},),
        failures=(),
        verified_result=verified,
    )


def _job(
    job_id: str,
    request: dict,
    *,
    attempt_number: int,
    state: str,
    retry_of_job_id: str | None = None,
) -> dict:
    request_sha256 = _sha(request)
    return {
        "id": job_id,
        "attempt_number": attempt_number,
        # The immutable batch confirmation binds only attempt 1.  Durable retry
        # links carry NULL confirmation_id and are authorized by retry_of_job_id.
        "scenario_confirmation_id": (
            "dsc_confirm" if attempt_number == 1 else None
        ),
        "retry_of_job_id": retry_of_job_id,
        "state": state,
        "request": deepcopy(request),
        "source_annual_job_id": "annual-source",
        "source_artifact_storage_key": "source.csv",
        "source_artifact_sha256": "6" * 64,
        "source_artifact_bytes": 100,
        "source_snapshot_sha256": "2" * 64,
        "submission_provenance_sha256": "3" * 64,
        "submission_provenance": {"request_sha256": request_sha256},
        "result": None,
        "result_provenance": None,
    }


def _scenario(
    scenario_id: str,
    revision_id: str,
    request: dict,
    jobs: list[dict],
    *,
    kind: str,
    confirmation_id: str = "dsc_confirm",
    comparison_classification: str | None = None,
) -> dict:
    return {
        "id": scenario_id,
        "scenario_id": scenario_id,
        "scenario_revision_id": revision_id,
        "case_id": "dc_case",
        "revision": 1,
        "confirmation_id": confirmation_id,
        "label": scenario_id,
        "kind": kind,
        "comparison_classification": comparison_classification or (
            "baseline" if kind == "baseline" else "controlled"
        ),
        "request": deepcopy(request),
        "request_sha256": _sha(request),
        "source_annual_job_id": "annual-source",
        "source_snapshot_sha256": "2" * 64,
        "analysis_basis": "solartac_site",
        "evidence_receipt_refs": [],
        "jobs": jobs,
    }


def _confirmation(scenarios: list[dict]) -> dict:
    items = []
    for index, scenario in enumerate(scenarios):
        initial = scenario["jobs"][0]
        items.append(
            {
                "item_index": index,
                "scenario_id": scenario["scenario_id"],
                "scenario_revision_id": scenario["scenario_revision_id"],
                "scenario_revision": scenario["revision"],
                "request_sha256": scenario["request_sha256"],
                "tea_job_id": initial["id"],
                "job": deepcopy(initial),
            }
        )
    confirmation_request = {
        "schema_version": 1,
        "case_id": "dc_case",
        "expected_case_revision": 5,
        "idempotency_key": "comparison-confirmation",
        "operator_name": "Comparison verifier",
        "rationale": "Freeze exact scenarios for deterministic comparison.",
        "acknowledgement": "The selected scenarios and source are immutable.",
        "confirmation_review": {},
        "scenarios": [
            {
                "scenario_revision_id": item["scenario_revision_id"],
                "expected_revision": item["scenario_revision"],
                "request_sha256": item["request_sha256"],
                "source_annual_job_id": item["job"]["source_annual_job_id"],
                "source_artifact_sha256": item["job"]["source_artifact_sha256"],
                "source_artifact_bytes": item["job"]["source_artifact_bytes"],
                "source_snapshot_sha256": item["job"]["source_snapshot_sha256"],
                "submission_provenance_sha256": item["job"][
                    "submission_provenance_sha256"
                ],
            }
            for item in items
        ],
    }
    receipt = {
        "schema_version": 1,
        "confirmation_id": "dsc_confirm",
        "case_id": "dc_case",
        "case_revision_before": 5,
        "case_revision_after": 6,
        "source_lock": {
            "source_annual_job_id": "annual-source",
            "source_snapshot_sha256": "2" * 64,
            "analysis_basis": "solartac_site",
        },
        "operator": {
            "name": "Comparison verifier",
            "rationale": "Freeze exact scenarios for deterministic comparison.",
            "acknowledgement": "The selected scenarios and source are immutable.",
        },
        "confirmation_review": {},
        "scenarios": [
            {
                "scenario_id": item["scenario_id"],
                "scenario_revision_id": item["scenario_revision_id"],
                "scenario_revision": item["scenario_revision"],
                "kind": scenarios[item["item_index"]]["kind"],
                "request_sha256": item["request_sha256"],
                "evidence_receipt_refs": [],
                "tea_job_id": item["tea_job_id"],
            }
            for item in items
        ],
        "confirmed_at": "2026-08-29T12:00:00+00:00",
    }
    return {
        "id": "dsc_confirm",
        "case_id": "dc_case",
        "expected_case_revision": 5,
        "case_revision_after": 6,
        "confirmation_request": confirmation_request,
        "confirmation_request_sha256": _sha(confirmation_request),
        "receipt": receipt,
        "receipt_sha256": _sha(receipt),
        "confirmed_at": "2026-08-29T12:00:00+00:00",
        "items": items,
    }


class AutonomyAttemptSelectionTests(unittest.TestCase):
    def test_confirmation_retry_chain_endpoint_is_selected_exactly(self) -> None:
        request = {"basis": "solartac_site", "value": 1.0}
        original = _job("tea_original", request, attempt_number=1, state="error")
        retry = _job(
            "tea_retry",
            request,
            attempt_number=2,
            state="done",
            retry_of_job_id="tea_original",
        )
        scenario = _scenario(
            "ds_baseline",
            "dscr_baseline_r1",
            request,
            [original, retry],
            kind="baseline",
        )
        confirmation = _confirmation([scenario])
        unrelated = _scenario(
            "ds_unrelated",
            "dscr_unrelated_r1",
            request,
            [_job("tea_latest_unrelated", request, attempt_number=1, state="done")],
            kind="alternative",
            confirmation_id="dsc_other",
        )

        selected = comparison.select_confirmation_attempts(
            confirmation_record=confirmation,
            scenario_records=[unrelated, scenario],
        )

        self.assertEqual("tea_retry", selected[0]["selected_job_id"])
        self.assertEqual(2, selected[0]["selected_attempt_number"])
        self.assertEqual(
            ["tea_original", "tea_retry"],
            [job["id"] for job in selected[0]["attempt_history"]],
        )

    def test_tampered_retry_parent_or_request_fails_closed(self) -> None:
        request = {"basis": "solartac_site", "value": 1.0}
        original = _job("tea_original", request, attempt_number=1, state="error")
        retry = _job(
            "tea_retry",
            request,
            attempt_number=2,
            state="done",
            retry_of_job_id="tea_wrong_parent",
        )
        scenario = _scenario(
            "ds_baseline",
            "dscr_baseline_r1",
            request,
            [original, retry],
            kind="baseline",
        )
        with self.assertRaisesRegex(
            comparison.ComparisonContractError,
            "parent link",
        ):
            comparison.select_confirmation_attempts(
                confirmation_record=_confirmation([scenario]),
                scenario_records=[scenario],
            )

        retry["retry_of_job_id"] = original["id"]
        retry["request"]["value"] = 9.0
        with self.assertRaisesRegex(
            comparison.ComparisonContractError,
            "immutable TEA request",
        ):
            comparison.select_confirmation_attempts(
                confirmation_record=_confirmation([scenario]),
                scenario_records=[scenario],
            )

    def test_missing_scenario_is_retained_without_substitution(self) -> None:
        request = {"basis": "solartac_site", "value": 1.0}
        scenario = _scenario(
            "ds_baseline",
            "dscr_baseline_r1",
            request,
            [_job("tea_original", request, attempt_number=1, state="queued")],
            kind="baseline",
        )
        selected = comparison.select_confirmation_attempts(
            confirmation_record=_confirmation([scenario]),
            scenario_records=[],
        )
        self.assertEqual("missing", selected[0]["selection_status"])
        self.assertIsNone(selected[0]["selected_job_id"])


class AutonomyComparisonBundleTests(unittest.TestCase):
    def _complete_bundle(
        self,
        *,
        contract_version: str = tea.CALCULATION_CONTRACT_VERSION,
        request: dict | None = None,
    ) -> dict:
        request = request or {"basis": "solartac_site", "value": 1.0}
        job = _job("tea_done", request, attempt_number=1, state="done")
        outcome = _verified_outcome(
            "tea_done", contract_version=contract_version, request=request
        )
        assert outcome.verified_result is not None
        job["result"] = deepcopy(outcome.verified_result.result)
        job["result_provenance"] = deepcopy(
            outcome.verified_result.result_provenance
        )
        scenario = _scenario(
            "ds_baseline",
            "dscr_baseline_r1",
            request,
            [job],
            kind="baseline",
        )
        return comparison.build_comparison_bundle(
            case_record={
                "id": "dc_case",
                "revision": 6,
                "source_annual_job_id": "annual-source",
                "source_snapshot_sha256": "2" * 64,
                "analysis_basis": "solartac_site",
            },
            confirmation_record=_confirmation([scenario]),
            scenario_records=[scenario],
            verification_outcomes={"tea_done": outcome},
        )

    def test_complete_bundle_preserves_metrics_cdf_nulls_and_quality(self) -> None:
        bundle = self._complete_bundle()
        scenario = bundle["scenarios"][0]
        metrics = scenario["result"]["metrics"]

        self.assertTrue(bundle["is_complete"])
        self.assertFalse(bundle["recommendation_eligible"])
        self.assertEqual("verified", scenario["verification"]["status"])
        self.assertEqual("baseline", scenario["comparison_classification"])
        self.assertEqual(
            "USD/applied_W",
            metrics[tea.APPLIED_FIELD_DELTA_COST]["unit"],
        )
        self.assertEqual(
            [1.0, 2.0, 3.0],
            metrics[tea.APPLIED_FIELD_DELTA_COST]["cdf"]["values"],
        )
        self.assertEqual(
            {"p5": None, "p50": None, "p95": None},
            metrics[tea.FIELD_LCOE_SE]["percentiles"],
        )
        self.assertIsNone(metrics[tea.FIELD_LCOE_SE]["cdf"])
        self.assertEqual(
            [-3.0, -2.0, -1.0],
            metrics["signed_nonzero_lcoo"]["cdf"]["values"],
        )
        self.assertEqual(
            "not_demonstrated",
            scenario["result"]["convergence"]["status"],
        )
        self.assertEqual(
            "passed",
            scenario["result"]["quality"]["reporting_tie_outs"]["status"],
        )
        self.assertEqual(
            tea.NUMERICAL_CONTRACT_VERSION,
            scenario["result"]["quality"]["numerical_provenance"][
                "contract_version"
            ],
        )
        self.assertEqual(
            ["cost.first", "cost.second"],
            [
                row["predictor_id"]
                for row in scenario["result"]["sensitivity"][
                    "lifecycle_cost_delta_se_minus_sol"
                ]["steps"]
            ],
        )
        self.assertEqual(
            "classification_pending_contract",
            bundle["recommendation"]["state"],
        )
        self.assertIsNone(bundle["recommendation"]["classification"])
        self.assertIsNone(bundle["recommendation"]["confidence"])
        classified = recommendation.classify_comparison_bundle(
            bundle, expected_bundle_sha256=bundle["bundle_hash"]
        )
        self.assertEqual("available", classified["state"])
        self.assertEqual("no_decisive_winner", classified["classification"])
        self.assertEqual("not_applicable", classified["confidence"])
        self.assertEqual(
            bundle["bundle_hash"],
            comparison.canonical_comparison_bundle_sha256(bundle),
        )

    def test_projection_commitment_requires_exact_durable_tradeoff_population(
        self,
    ) -> None:
        outcome = _verified_outcome("tea_projection_commitment")
        assert outcome.verified_result is not None
        durable_result = outcome.verified_result.result
        projection = {
            "joint_outcomes": {
                "tradeoff_classes": deepcopy(
                    durable_result["summaries"]["tradeoff_classes"]
                )
            }
        }
        verified_digest = (
            comparison.verified_result_projection_commitment_sha256(
                durable_result=durable_result,
                result_projection=projection,
            )
        )
        self.assertEqual(
            comparison.result_projection_commitment_sha256(
                durable_result_sha256=_sha(durable_result),
                result_projection=projection,
            ),
            verified_digest,
        )
        projection["joint_outcomes"]["tradeoff_classes"]["counts"] = {
            "forged": 3
        }
        with self.assertRaisesRegex(
            comparison.ComparisonContractError,
            "differs from the durable result",
        ):
            comparison.verified_result_projection_commitment_sha256(
                durable_result=durable_result,
                result_projection=projection,
            )

    def test_bundle_preserves_structural_comparison_warning(self) -> None:
        request = {"basis": "solartac_site", "value": 1.0}
        job = _job("tea_structural", request, attempt_number=1, state="done")
        outcome = _verified_outcome("tea_structural", request=request)
        assert outcome.verified_result is not None
        job["result"] = deepcopy(outcome.verified_result.result)
        job["result_provenance"] = deepcopy(
            outcome.verified_result.result_provenance
        )
        scenario = _scenario(
            "ds_structural",
            "dscr_structural_r1",
            request,
            [job],
            kind="alternative",
            comparison_classification="structural",
        )
        bundle = comparison.build_comparison_bundle(
            case_record={
                "id": "dc_case",
                "revision": 6,
                "source_annual_job_id": "annual-source",
                "source_snapshot_sha256": "2" * 64,
                "analysis_basis": "solartac_site",
            },
            confirmation_record=_confirmation([scenario]),
            scenario_records=[scenario],
            verification_outcomes={"tea_structural": outcome},
        )

        projected = bundle["scenarios"][0]
        self.assertEqual("structural", projected["comparison_classification"])
        self.assertEqual(
            "This scenario changes request structure; baseline-relative causal "
            "attribution is limited.",
            projected["structural_warning"],
        )

    def test_metric_registry_preserves_v1_v2_v3_units(self) -> None:
        v1 = self._complete_bundle(
            contract_version=tea.LEGACY_CALCULATION_CONTRACT_VERSION
        )
        v2 = self._complete_bundle(contract_version=tea.CALCULATION_CONTRACT_VERSION)
        v3 = self._complete_bundle(
            contract_version=tea.COMMERCIAL_SCALING_CALCULATION_CONTRACT_VERSION
        )

        self.assertEqual(
            "USD/Wdc",
            v1["scenarios"][0]["result"]["metrics"][tea.FIELD_DELTA_COST][
                "unit"
            ],
        )
        self.assertEqual(
            "kWh_AC/applied_W",
            v2["scenarios"][0]["result"]["metrics"][
                tea.APPLIED_FIELD_DELTA_ENERGY
            ]["unit"],
        )
        self.assertEqual(
            "constant USD/kWh_AC",
            v3["scenarios"][0]["result"]["metrics"][
                tea.COMMERCIAL_FIELD_MARGINAL_LCOO
            ]["unit"],
        )
        self.assertEqual(
            "constant USD",
            v3["scenarios"][0]["result"]["metrics"][
                tea.COMMERCIAL_FIELD_LIFECYCLE_MARGINAL_COST
            ]["unit"],
        )
        self.assertEqual(
            "constant USD/year",
            v3["scenarios"][0]["result"]["metrics"][
                tea.COMMERCIAL_FIELD_EA_MARGINAL_COST
            ]["unit"],
        )

    def test_partial_bundle_retains_failed_and_queued_scenarios_and_attempts(self) -> None:
        baseline_request = {"basis": "solartac_site", "value": 1.0, "nullable": None}
        alternative_request = {"basis": "solartac_site", "value": 2.0}
        baseline_original = _job(
            "tea_base_error",
            baseline_request,
            attempt_number=1,
            state="error",
        )
        baseline_retry = _job(
            "tea_base_done",
            baseline_request,
            attempt_number=2,
            state="done",
            retry_of_job_id="tea_base_error",
        )
        baseline_outcome = _verified_outcome(
            "tea_base_done", request=baseline_request
        )
        assert baseline_outcome.verified_result is not None
        baseline_retry["result"] = deepcopy(
            baseline_outcome.verified_result.result
        )
        baseline_retry["result_provenance"] = deepcopy(
            baseline_outcome.verified_result.result_provenance
        )
        alternative_job = _job(
            "tea_alt_queued",
            alternative_request,
            attempt_number=1,
            state="queued",
        )
        baseline = _scenario(
            "ds_baseline",
            "dscr_baseline_r1",
            baseline_request,
            [baseline_original, baseline_retry],
            kind="baseline",
        )
        alternative = _scenario(
            "ds_alternative",
            "dscr_alternative_r1",
            alternative_request,
            [alternative_job],
            kind="alternative",
        )
        bundle = comparison.build_comparison_bundle(
            case_record={
                "id": "dc_case",
                "revision": 6,
                "source_annual_job_id": "annual-source",
                "source_snapshot_sha256": "2" * 64,
                "analysis_basis": "solartac_site",
            },
            confirmation_record=_confirmation([baseline, alternative]),
            scenario_records=[baseline, alternative],
            verification_outcomes={"tea_base_done": baseline_outcome},
        )

        self.assertFalse(bundle["is_complete"])
        self.assertEqual("partial", bundle["completeness"]["status"])
        self.assertEqual(1, bundle["completeness"]["verified_done_count"])
        self.assertEqual("queued", bundle["scenarios"][1]["attempt"]["display_status"])
        self.assertIsNone(bundle["scenarios"][1]["result"])
        self.assertEqual(3, len(bundle["attempt_proofs"]))
        self.assertEqual(
            [False, True, True],
            [row["selected_for_comparison"] for row in bundle["attempt_proofs"]],
        )
        self.assertEqual(
            ["not_applicable", "verified", "pending"],
            [row["verification_status"] for row in bundle["attempt_proofs"]],
        )
        matrix = {
            row["json_pointer"]: row for row in bundle["comparison"]["request_matrix"]
        }
        self.assertEqual(
            [True, False],
            [value["present"] for value in matrix["/nullable"]["values"]],
        )
        self.assertIsNone(matrix["/nullable"]["values"][0]["value"])

    def test_done_result_without_verification_is_explicit_failure(self) -> None:
        request = {"basis": "solartac_site", "value": 1.0}
        job = _job("tea_done", request, attempt_number=1, state="done")
        scenario = _scenario(
            "ds_baseline",
            "dscr_baseline_r1",
            request,
            [job],
            kind="baseline",
        )
        bundle = comparison.build_comparison_bundle(
            case_record={
                "id": "dc_case",
                "revision": 6,
                "source_annual_job_id": "annual-source",
                "source_snapshot_sha256": "2" * 64,
                "analysis_basis": "solartac_site",
            },
            confirmation_record=_confirmation([scenario]),
            scenario_records=[scenario],
            verification_outcomes={},
        )
        projected = bundle["scenarios"][0]
        self.assertEqual("verification_failed", projected["attempt"]["display_status"])
        self.assertEqual("failed", projected["verification"]["status"])
        self.assertIsNone(projected["result"])
        self.assertFalse(bundle["is_complete"])

    def test_partial_bundle_reverifies_confirmation_and_frozen_attempt_authority(
        self,
    ) -> None:
        request = {"basis": "solartac_site", "value": 1.0}
        job = _job("tea_queued", request, attempt_number=1, state="queued")
        scenario = _scenario(
            "ds_baseline",
            "dscr_baseline_r1",
            request,
            [job],
            kind="baseline",
        )
        case = {
            "id": "dc_case",
            "revision": 6,
            "source_annual_job_id": "annual-source",
            "source_snapshot_sha256": "2" * 64,
            "analysis_basis": "solartac_site",
        }

        tampered_receipt = _confirmation([scenario])
        tampered_receipt["receipt"]["scenarios"][0]["request_sha256"] = "0" * 64
        tampered_receipt["receipt_sha256"] = _sha(tampered_receipt["receipt"])
        with self.assertRaises(comparison.ComparisonContractError) as receipt_error:
            comparison.build_comparison_bundle(
                case_record=case,
                confirmation_record=tampered_receipt,
                scenario_records=[scenario],
                verification_outcomes={},
            )
        self.assertEqual(
            "confirmation_item_identity_mismatch", receipt_error.exception.code
        )

        frozen_identity = _confirmation([scenario])
        scenario["jobs"][0]["submission_provenance_sha256"] = "0" * 64
        with self.assertRaises(comparison.ComparisonContractError) as job_error:
            comparison.build_comparison_bundle(
                case_record=case,
                confirmation_record=frozen_identity,
                scenario_records=[scenario],
                verification_outcomes={},
            )
        self.assertEqual(
            "confirmation_selected_job_identity_mismatch",
            job_error.exception.code,
        )

    def test_partial_bundle_rejects_changed_evidence_membership(self) -> None:
        request = {"basis": "solartac_site", "value": 1.0}
        scenario = _scenario(
            "ds_baseline",
            "dscr_baseline_r1",
            request,
            [_job("tea_queued", request, attempt_number=1, state="queued")],
            kind="baseline",
        )
        confirmation = _confirmation([scenario])
        confirmation["receipt"]["scenarios"][0]["evidence_receipt_refs"] = [
            {
                "request_path": "/value",
                "evidence_receipt_id": "evr_changed",
            }
        ]
        confirmation["receipt_sha256"] = _sha(confirmation["receipt"])

        with self.assertRaises(comparison.ComparisonContractError) as caught:
            comparison.build_comparison_bundle(
                case_record={
                    "id": "dc_case",
                    "revision": 6,
                    "source_annual_job_id": "annual-source",
                    "source_snapshot_sha256": "2" * 64,
                    "analysis_basis": "solartac_site",
                },
                confirmation_record=confirmation,
                scenario_records=[scenario],
                verification_outcomes={},
            )
        self.assertEqual(
            "confirmation_evidence_membership_mismatch", caught.exception.code
        )

    def test_canonical_hash_is_repeatable_and_key_order_independent(self) -> None:
        first = self._complete_bundle(
            request={"basis": "solartac_site", "nested": {"a": 1, "b": 2}}
        )
        second = self._complete_bundle(
            request={"nested": {"b": 2, "a": 1}, "basis": "solartac_site"}
        )
        repeated = deepcopy(first)
        repeated["bundle_hash"] = "0" * 64

        self.assertEqual(first["bundle_hash"], second["bundle_hash"])
        self.assertEqual(
            first["bundle_hash"],
            comparison.canonical_comparison_bundle_sha256(repeated),
        )


class CompletedResultVerificationTests(unittest.TestCase):
    def _authority(self, output: Path) -> tuple[dict, dict, dict, dict, dict, SimpleNamespace]:
        request = {"basis": "solartac_site", "value": 1.0}
        request_sha256 = _sha(request)
        source_snapshot = {"source": "frozen"}
        source_snapshot_sha256 = _sha(source_snapshot)
        kernel_payload = {"kernel": "request"}
        kernel_sha256 = _sha(kernel_payload)
        submission = {
            "request_sha256": request_sha256,
            "source_snapshot_sha256": source_snapshot_sha256,
            "validated_kernel_request_sha256": kernel_sha256,
        }
        submission_sha256 = _sha(submission)
        confirmation_request = {
            "schema_version": 1,
            "case_id": "dc_case",
            "expected_case_revision": 1,
            "idempotency_key": "comparison-verification",
            "operator_name": "Verifier",
            "rationale": "Verify the frozen comparison result.",
            "acknowledgement": "The selected scenarios and source are immutable.",
            "confirmation_review": {},
            "scenarios": [
                {
                    "scenario_revision_id": "dscr_baseline_r1",
                    "expected_revision": 1,
                    "request_sha256": request_sha256,
                    "source_annual_job_id": "annual-source",
                    "source_artifact_sha256": "6" * 64,
                    "source_artifact_bytes": 100,
                    "source_snapshot_sha256": source_snapshot_sha256,
                    "submission_provenance_sha256": submission_sha256,
                }
            ],
        }
        confirmed_at = "2026-08-29T12:00:00+00:00"
        receipt = {
            "schema_version": 1,
            "confirmation_id": "dsc_confirm",
            "case_id": "dc_case",
            "case_revision_before": 1,
            "case_revision_after": 2,
            "source_lock": {
                "source_annual_job_id": "annual-source",
                "source_snapshot_sha256": source_snapshot_sha256,
                "analysis_basis": "solartac_site",
            },
            "operator": {
                "name": "Verifier",
                "rationale": "Verify the frozen comparison result.",
                "acknowledgement": "The selected scenarios and source are immutable.",
            },
            "confirmation_review": {},
            "scenarios": [
                {
                    "scenario_id": "ds_baseline",
                    "scenario_revision_id": "dscr_baseline_r1",
                    "scenario_revision": 1,
                    "kind": "baseline",
                    "request_sha256": request_sha256,
                    "evidence_receipt_refs": [],
                    "tea_job_id": "tea_verified",
                }
            ],
            "confirmed_at": confirmed_at,
        }
        confirmation = {
            "id": "dsc_confirm",
            "case_id": "dc_case",
            "expected_case_revision": 1,
            "case_revision_after": 2,
            "confirmation_request": confirmation_request,
            "confirmation_request_sha256": _sha(confirmation_request),
            "receipt": receipt,
            "receipt_sha256": _sha(receipt),
            "operator_name": "Verifier",
            "rationale": "Verify the frozen comparison result.",
            "acknowledgement": "The selected scenarios and source are immutable.",
            "confirmed_at": confirmed_at,
            "items": [
                {
                    "item_index": 0,
                    "scenario_id": "ds_baseline",
                    "scenario_revision_id": "dscr_baseline_r1",
                    "scenario_revision": 1,
                    "request_sha256": request_sha256,
                    "tea_job_id": "tea_verified",
                }
            ],
        }
        attempt = output / ".technoeconomic_attempts" / "tea_verified" / "lease1"
        attempt.mkdir(parents=True)
        sealed_path = attempt / run_technoeconomic.SEALED_CALCULATION_FILENAME
        sealed_path.write_bytes(b"sealed")
        storage_key = sealed_path.relative_to(output).as_posix()
        sealed_artifact = {
            "schema_version": run_technoeconomic.SEALED_CALCULATION_SCHEMA_VERSION,
            "artifact_kind": "sealed_technoeconomic_calculation",
            "owner_workflow": "technoeconomic",
            "owner_job_id": "tea_verified",
            "storage_key": storage_key,
            "filename": run_technoeconomic.SEALED_CALCULATION_FILENAME,
            "media_type": "application/x-npz",
            "sha256": "5" * 64,
            "byte_count": 6,
            "row_count": 1,
            "column_count": 1,
            "array_count": 2,
            "pickle_allowed": False,
            "public": False,
        }
        tie_outs = {
            "status": "passed",
            "check_count": 1,
            "failed_check_ids": [],
            "realization_row_count": 1,
        }
        manifest = {
            "schema_version": "technoeconomic-exports-manifest-v2",
            "csv_format_version": "technoeconomic-csv-v2",
            "owner_workflow": "technoeconomic",
            "owner_job_id": "tea_verified",
            "request_sha256": request_sha256,
            "source_snapshot_sha256": source_snapshot_sha256,
            "submission_provenance_sha256": submission_sha256,
            "sealed_calculation_sha256": sealed_artifact["sha256"],
            "calculation_contract_version": tea.CALCULATION_CONTRACT_VERSION,
            "sampling_version": tea.SAMPLING_VERSION,
            "artifact_count": 0,
            "artifacts": {},
            "tie_outs": tie_outs,
            "chart_contracts": {},
            "manifest_sha256": "8" * 64,
        }
        public_manifest = run_technoeconomic._public_export_manifest(manifest)
        result = {
            "schema_version": 2,
            "calculation_contract_version": tea.CALCULATION_CONTRACT_VERSION,
            "sampling_version": tea.SAMPLING_VERSION,
            "analysis_basis": "solartac_site",
            "source_snapshot_sha256": source_snapshot_sha256,
            "exports": public_manifest,
        }
        kernel_provenance = {
            "calculation_contract_version": tea.CALCULATION_CONTRACT_VERSION,
            "sampling_version": tea.SAMPLING_VERSION,
            "numerics": {
                "contract_version": tea.NUMERICAL_CONTRACT_VERSION,
                "probe_digests": deepcopy(tea.NUMERICAL_PROBE_DIGESTS),
                "exactness_digest": "a" * 64,
                "reference_exactness_digest": "b" * 64,
                "bit_identical_to_reference": False,
            },
        }
        verified_source = {
            "sha256": "6" * 64,
            "byte_count": 100,
            "media_type": "text/csv",
            "immutable": True,
        }
        result_provenance = {
            "schema_version": run_technoeconomic.RESULT_PROVENANCE_SCHEMA_VERSION,
            "request_sha256": request_sha256,
            "source_snapshot_sha256": source_snapshot_sha256,
            "submission_provenance_sha256": submission_sha256,
            "validated_kernel_request_sha256": kernel_sha256,
            "source_annual_job_id": "annual-source",
            "source_artifact": verified_source,
            "routine_result_sha256": _sha(result),
            "sealed_calculation": run_technoeconomic._public_calculation_identity(
                sealed_artifact
            ),
            "exports": {
                "schema_version": manifest["schema_version"],
                "manifest_sha256": manifest["manifest_sha256"],
                "artifact_count": manifest["artifact_count"],
            },
            "kernel": kernel_provenance,
        }
        job = {
            "id": "tea_verified",
            "state": "done",
            "request": request,
            "source_snapshot": source_snapshot,
            "source_snapshot_sha256": source_snapshot_sha256,
            "submission_provenance": submission,
            "submission_provenance_sha256": submission_sha256,
            "source_annual_job_id": "annual-source",
            "source_artifact_storage_key": "source.csv",
            "source_artifact_sha256": verified_source["sha256"],
            "source_artifact_bytes": verified_source["byte_count"],
            "result": result,
            "result_provenance": result_provenance,
            "artifacts": {
                "sealed_calculation": sealed_artifact,
                "exports": manifest,
            },
        }
        confirmation["items"][0]["job"] = deepcopy(job)
        scenario = {
            "scenario_id": "ds_baseline",
            "scenario_revision_id": "dscr_baseline_r1",
            "case_id": "dc_case",
            "revision": 1,
            "confirmation_id": "dsc_confirm",
            "kind": "baseline",
            "request_sha256": request_sha256,
            "source_annual_job_id": "annual-source",
            "source_snapshot_sha256": source_snapshot_sha256,
            "analysis_basis": "solartac_site",
            "evidence_receipt_refs": [],
            "jobs": [
                {
                    "id": "tea_verified",
                    "attempt_number": 1,
                    "retry_of_job_id": None,
                }
            ],
        }
        case = {
            "id": "dc_case",
            "source_annual_job_id": "annual-source",
            "source_snapshot_sha256": source_snapshot_sha256,
            "analysis_basis": "solartac_site",
        }
        sealed = SimpleNamespace(
            metadata={"kernel_provenance": kernel_provenance},
            row_count=1,
        )
        return case, confirmation, scenario, job, verified_source, sealed

    def test_verifier_uses_read_only_contracts_and_never_runs_kernel(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            case, confirmation, scenario, job, verified_source, sealed = self._authority(output)
            item = confirmation["items"][0]
            check_row = (
                "realization_count",
                1,
                1,
                0,
                0,
                "OK",
                "exact",
            )
            with (
                patch.object(config, "OUTPUT_DIR", output),
                patch.object(
                    run_technoeconomic,
                    "_verify_frozen_inputs",
                    return_value=(item["request_sha256"], verified_source),
                ) as frozen,
                patch.object(
                    tea_api,
                    "build_technoeconomic_kernel_request",
                    return_value=object(),
                ),
                patch.object(tea, "validate_request", side_effect=lambda value: value),
                patch.object(
                    tea,
                    "canonical_request_payload",
                    return_value={"kernel": "request"},
                ),
                patch.object(
                    run_technoeconomic,
                    "_verify_rebuilt_submission_provenance",
                    return_value=job["submission_provenance"],
                ),
                patch.object(run_technoeconomic, "_verify_sealed_calculation_artifact"),
                patch.object(reporting, "_load_sealed_calculation", return_value=sealed),
                patch.object(reporting, "_verify_routine_result"),
                patch.object(run_technoeconomic, "_verify_export_manifest") as exports,
                patch.object(reporting, "_build_checks", return_value=[check_row]),
                patch.object(
                    tea,
                    "run_technoeconomic",
                    side_effect=AssertionError("kernel must not run"),
                ),
            ):
                outcome = result_verification.verify_completed_technoeconomic_result(
                    case_record=case,
                    confirmation_record=confirmation,
                    confirmation_item=item,
                    scenario_record=scenario,
                    job_record=job,
                    evidence_receipt_loader=lambda _receipt_id: None,
                    evidence_snapshot_loader=lambda _case_id, _asset_id: ({}, {}),
                )

            self.assertTrue(outcome.valid, outcome.failures)
            self.assertEqual("verified", outcome.status)
            self.assertEqual(_sha([]), outcome.verified_result.evidence_set_sha256)
            self.assertEqual(1, len(outcome.verified_result.reporting_checks))
            frozen.assert_called_once()
            exports.assert_called_once()

    def test_verifier_rejects_tampered_confirmation_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            case, confirmation, scenario, job, _verified_source, _sealed = self._authority(output)
            confirmation["receipt"]["tampered"] = True
            outcome = result_verification.verify_completed_technoeconomic_result(
                case_record=case,
                confirmation_record=confirmation,
                confirmation_item=confirmation["items"][0],
                scenario_record=scenario,
                job_record=job,
                evidence_receipt_loader=lambda _receipt_id: None,
                evidence_snapshot_loader=lambda _case_id, _asset_id: ({}, {}),
            )
            self.assertFalse(outcome.valid)
            self.assertEqual(
                "confirmation_receipt_digest_mismatch",
                outcome.failures[0]["code"],
            )

    def test_verifier_rejects_tampered_confirmation_request_digest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            case, confirmation, scenario, job, _verified_source, _sealed = self._authority(output)
            confirmation["confirmation_request"]["scenarios"][0][
                "request_sha256"
            ] = "0" * 64
            outcome = result_verification.verify_completed_technoeconomic_result(
                case_record=case,
                confirmation_record=confirmation,
                confirmation_item=confirmation["items"][0],
                scenario_record=scenario,
                job_record=job,
                evidence_receipt_loader=lambda _receipt_id: None,
                evidence_snapshot_loader=lambda _case_id, _asset_id: ({}, {}),
            )
            self.assertFalse(outcome.valid)
            self.assertEqual(
                "confirmation_request_digest_mismatch",
                outcome.failures[0]["code"],
            )

    def test_verifier_rejects_rehashed_confirmation_request_identity_tamper(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            case, confirmation, scenario, job, _verified_source, _sealed = self._authority(output)
            confirmation["confirmation_request"]["scenarios"][0][
                "expected_revision"
            ] = 2
            confirmation["confirmation_request_sha256"] = _sha(
                confirmation["confirmation_request"]
            )
            outcome = result_verification.verify_completed_technoeconomic_result(
                case_record=case,
                confirmation_record=confirmation,
                confirmation_item=confirmation["items"][0],
                scenario_record=scenario,
                job_record=job,
                evidence_receipt_loader=lambda _receipt_id: None,
                evidence_snapshot_loader=lambda _case_id, _asset_id: ({}, {}),
            )
            self.assertFalse(outcome.valid)
            self.assertEqual(
                "confirmation_request_identity_mismatch",
                outcome.failures[0]["code"],
            )

    def test_verifier_rejects_rehashed_receipt_identity_and_item_tamper(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            case, confirmation, scenario, job, _verified_source, _sealed = self._authority(output)
            confirmation["receipt"]["confirmation_id"] = "dsc_other"
            confirmation["receipt_sha256"] = _sha(confirmation["receipt"])
            identity_outcome = result_verification.verify_completed_technoeconomic_result(
                case_record=case,
                confirmation_record=confirmation,
                confirmation_item=confirmation["items"][0],
                scenario_record=scenario,
                job_record=job,
                evidence_receipt_loader=lambda _receipt_id: None,
                evidence_snapshot_loader=lambda _case_id, _asset_id: ({}, {}),
            )
            self.assertFalse(identity_outcome.valid)
            self.assertEqual(
                "confirmation_receipt_identity_mismatch",
                identity_outcome.failures[0]["code"],
            )

            confirmation["receipt"]["confirmation_id"] = "dsc_confirm"
            confirmation["receipt"]["scenarios"][0]["tea_job_id"] = "tea_other"
            confirmation["receipt_sha256"] = _sha(confirmation["receipt"])
            item_outcome = result_verification.verify_completed_technoeconomic_result(
                case_record=case,
                confirmation_record=confirmation,
                confirmation_item=confirmation["items"][0],
                scenario_record=scenario,
                job_record=job,
                evidence_receipt_loader=lambda _receipt_id: None,
                evidence_snapshot_loader=lambda _case_id, _asset_id: ({}, {}),
            )
            self.assertFalse(item_outcome.valid)
            self.assertEqual(
                "confirmation_receipt_items_mismatch",
                item_outcome.failures[0]["code"],
            )

            confirmation["receipt"]["scenarios"][0]["tea_job_id"] = "tea_verified"
            confirmation["receipt"]["source_lock"][
                "source_snapshot_sha256"
            ] = "0" * 64
            confirmation["receipt_sha256"] = _sha(confirmation["receipt"])
            source_outcome = result_verification.verify_completed_technoeconomic_result(
                case_record=case,
                confirmation_record=confirmation,
                confirmation_item=confirmation["items"][0],
                scenario_record=scenario,
                job_record=job,
                evidence_receipt_loader=lambda _receipt_id: None,
                evidence_snapshot_loader=lambda _case_id, _asset_id: ({}, {}),
            )
            self.assertFalse(source_outcome.valid)
            self.assertEqual(
                "confirmation_receipt_source_lock_mismatch",
                source_outcome.failures[0]["code"],
            )

    def test_receipt_evidence_membership_accepts_store_nested_metadata(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            case, confirmation, scenario, job, _verified_source, _sealed = self._authority(output)
            identity = {
                "request_path": "/cost_lines/0/distribution/value",
                "evidence_receipt_id": "evr_accepted",
            }
            confirmation["receipt"]["scenarios"][0][
                "evidence_receipt_refs"
            ] = [deepcopy(identity)]
            confirmation["receipt_sha256"] = _sha(confirmation["receipt"])
            scenario["evidence_receipt_refs"] = [
                {
                    **identity,
                    "receipt": {
                        "id": "evr_accepted",
                        "receipt_sha256": "a" * 64,
                    },
                }
            ]

            authority = result_verification._confirmation_authority(
                case_record=case,
                confirmation_record=confirmation,
                confirmation_item=confirmation["items"][0],
                scenario_record=scenario,
                job_record=job,
            )

            self.assertEqual(("dc_case", "dsc_confirm", "tea_verified"), authority)

    def test_verifier_requires_exact_selected_confirmation_item_membership(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            case, confirmation, scenario, job, _verified_source, _sealed = self._authority(output)
            selected_item = deepcopy(confirmation["items"][0])
            selected_item["scenario_id"] = "ds_unrelated"
            outcome = result_verification.verify_completed_technoeconomic_result(
                case_record=case,
                confirmation_record=confirmation,
                confirmation_item=selected_item,
                scenario_record=scenario,
                job_record=job,
                evidence_receipt_loader=lambda _receipt_id: None,
                evidence_snapshot_loader=lambda _case_id, _asset_id: ({}, {}),
            )
            self.assertFalse(outcome.valid)
            self.assertEqual(
                "confirmation_item_mismatch",
                outcome.failures[0]["code"],
            )

    def test_verifier_rejects_selected_attempt_frozen_identity_drift(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            case, confirmation, scenario, job, _verified_source, _sealed = self._authority(output)
            job["submission_provenance_sha256"] = "0" * 64

            outcome = result_verification.verify_completed_technoeconomic_result(
                case_record=case,
                confirmation_record=confirmation,
                confirmation_item=confirmation["items"][0],
                scenario_record=scenario,
                job_record=job,
                evidence_receipt_loader=lambda _receipt_id: None,
                evidence_snapshot_loader=lambda _case_id, _asset_id: ({}, {}),
            )

            self.assertFalse(outcome.valid)
            self.assertEqual(
                "confirmation_selected_job_identity_mismatch",
                outcome.failures[0]["code"],
            )

    def test_real_worker_result_reverifies_without_regeneration(self) -> None:
        # Reuse the established worker fixture so this test exercises the actual
        # sealed NPZ, reporting checks, export manifest, and source artifact.
        from tests.test_technoeconomic_worker import (
            TechnoeconomicWorkerPhase3Tests,
        )

        fixture = TechnoeconomicWorkerPhase3Tests(
            "test_success_uses_frozen_inputs_and_seals_every_realization"
        )
        fixture.setUp()
        try:
            claimed = fixture._claim(worker_id="comparison-verifier-worker")
            fixture._run(claimed)
            job = fixture.store.get_technoeconomic_job(fixture.job_id)
            self.assertEqual("done", job["state"])
            request_sha256 = _sha(job["request"])
            confirmation_request = {
                "schema_version": 1,
                "case_id": "dc_real_worker",
                "expected_case_revision": 1,
                "idempotency_key": "real-worker-verification",
                "operator_name": "Verifier",
                "rationale": "Verify the completed worker result.",
                "acknowledgement": "The selected scenario and source are immutable.",
                "confirmation_review": {},
                "scenarios": [
                    {
                        "scenario_revision_id": "dscr_real_worker_r1",
                        "expected_revision": 1,
                        "request_sha256": request_sha256,
                        "source_annual_job_id": fixture.source_id,
                        "source_artifact_sha256": job["source_artifact_sha256"],
                        "source_artifact_bytes": job["source_artifact_bytes"],
                        "source_snapshot_sha256": fixture.snapshot_sha256,
                        "submission_provenance_sha256": job[
                            "submission_provenance_sha256"
                        ],
                    }
                ],
            }
            confirmed_at = "2026-08-29T12:00:00+00:00"
            receipt = {
                "schema_version": 1,
                "confirmation_id": "dsc_real_worker",
                "case_id": "dc_real_worker",
                "case_revision_before": 1,
                "case_revision_after": 2,
                "source_lock": {
                    "source_annual_job_id": fixture.source_id,
                    "source_snapshot_sha256": fixture.snapshot_sha256,
                    "analysis_basis": "solartac_site",
                },
                "operator": {
                    "name": "Verifier",
                    "rationale": "Verify the completed worker result.",
                    "acknowledgement": "The selected scenario and source are immutable.",
                },
                "confirmation_review": {},
                "scenarios": [
                    {
                        "scenario_id": "ds_real_worker",
                        "scenario_revision_id": "dscr_real_worker_r1",
                        "scenario_revision": 1,
                        "kind": "baseline",
                        "request_sha256": request_sha256,
                        "evidence_receipt_refs": [],
                        "tea_job_id": fixture.job_id,
                    }
                ],
                "confirmed_at": confirmed_at,
            }
            confirmation = {
                "id": "dsc_real_worker",
                "case_id": "dc_real_worker",
                "expected_case_revision": 1,
                "case_revision_after": 2,
                "confirmation_request": confirmation_request,
                "confirmation_request_sha256": _sha(confirmation_request),
                "receipt": receipt,
                "receipt_sha256": _sha(receipt),
                "operator_name": "Verifier",
                "rationale": "Verify the completed worker result.",
                "acknowledgement": "The selected scenario and source are immutable.",
                "confirmed_at": confirmed_at,
                "items": [
                    {
                        "item_index": 0,
                        "scenario_id": "ds_real_worker",
                        "scenario_revision_id": "dscr_real_worker_r1",
                        "scenario_revision": 1,
                        "request_sha256": request_sha256,
                        "tea_job_id": fixture.job_id,
                        "job": deepcopy(job),
                    }
                ],
            }
            scenario_job = deepcopy(job)
            scenario_job["attempt_number"] = 1
            scenario_job["scenario_confirmation_id"] = confirmation["id"]
            scenario = {
                "id": "ds_real_worker",
                "scenario_id": "ds_real_worker",
                "scenario_revision_id": "dscr_real_worker_r1",
                "case_id": "dc_real_worker",
                "revision": 1,
                "confirmation_id": confirmation["id"],
                "label": "Real worker baseline",
                "kind": "baseline",
                "request": deepcopy(job["request"]),
                "request_sha256": request_sha256,
                "source_annual_job_id": fixture.source_id,
                "source_snapshot_sha256": fixture.snapshot_sha256,
                "analysis_basis": "solartac_site",
                "evidence_receipt_refs": [],
                "jobs": [scenario_job],
            }
            case = {
                "id": "dc_real_worker",
                "revision": 1,
                "source_annual_job_id": fixture.source_id,
                "source_snapshot_sha256": fixture.snapshot_sha256,
                "analysis_basis": "solartac_site",
            }

            with patch.object(
                run_technoeconomic.kernel,
                "run_technoeconomic",
                side_effect=AssertionError("comparison verification must not run TEA"),
            ):
                outcome = result_verification.verify_completed_technoeconomic_result(
                    case_record=case,
                    confirmation_record=confirmation,
                    confirmation_item=confirmation["items"][0],
                    scenario_record=scenario,
                    job_record=job,
                    evidence_receipt_loader=lambda _receipt_id: None,
                    evidence_snapshot_loader=lambda _case_id, _asset_id: ({}, {}),
                )

            self.assertTrue(outcome.valid, outcome.failures)
            self.assertEqual(
                "passed",
                outcome.verified_result.result["exports"]["tie_outs"]["status"],
            )
            self.assertTrue(outcome.verified_result.reporting_checks)
            bundle = comparison.build_comparison_bundle(
                case_record=case,
                confirmation_record=confirmation,
                scenario_records=[scenario],
                verification_outcomes={fixture.job_id: outcome},
            )
            self.assertTrue(bundle["is_complete"])
            self.assertEqual(
                "USD/Wdc",
                bundle["scenarios"][0]["result"]["metrics"][
                    tea.FIELD_DELTA_COST
                ]["unit"],
            )
        finally:
            fixture.doCleanups()


if __name__ == "__main__":
    unittest.main()
