from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import unittest

from sbepv import technoeconomic as tea
from sbepv.autonomy import comparison
from sbepv.autonomy import recommendation


_EXPECTED_CONTRACT_DIGEST = (
    "b5eed8f630cdeb934b1cf5292077be19cf16f14771d4a596975c59c4b614041a"
)
_NUMERICAL_PROVENANCE = tea.numerical_fingerprint()


def _sha(value: object) -> str:
    encoded = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _evidence_set_sha256(receipts: list[dict]) -> str:
    identities = [
        {
            "request_path": receipt.get("request_path"),
            "evidence_receipt_id": receipt.get("evidence_receipt_id"),
            "receipt_sha256": receipt.get("receipt_sha256"),
            "content_sha256": receipt.get("content_sha256"),
        }
        for receipt in sorted(
            receipts,
            key=lambda item: (
                str(item.get("request_path") or ""),
                str(item.get("evidence_receipt_id") or ""),
            ),
        )
    ]
    return _sha(identities)


def _reporting_tieout_sha256(
    manifest_sha256: str,
    tie_outs: dict,
) -> str:
    return _sha(
        {
            "manifest_sha256": manifest_sha256,
            "tie_outs": tie_outs,
        }
    )


def _tradeoff_summary(
    *,
    solaredge_probability: float = 0.0,
    solectria_probability: float = 0.0,
    hurdle_probability: float = 0.0,
) -> dict:
    denominator = 1_000_000
    solaredge_count = round(solaredge_probability * denominator)
    solectria_count = round(solectria_probability * denominator)
    hurdle_count = round(hurdle_probability * denominator)
    remainder = denominator - solaredge_count - solectria_count - hurdle_count
    if remainder < 0:
        raise AssertionError("test probabilities exceed one")
    counts = {class_id: 0 for class_id in tea.TRADEOFF_CLASSES}
    counts["cost_saving_energy_gain"] = solaredge_count
    counts["cost_increase_energy_loss"] = solectria_count
    counts["cost_increase_energy_gain"] = hurdle_count
    counts["cost_neutral_zero_energy_change"] = remainder
    return {
        "denominator": denominator,
        "counts": counts,
        "probabilities": {
            class_id: count / denominator
            for class_id, count in counts.items()
        },
    }


def _sensitivity() -> dict:
    return {
        "lifecycle_cost_delta_se_minus_sol": {
            "status": "available",
            "reason": None,
            "sample_count": 40,
            "minimum_sample_count": 20,
            "candidate_predictor_count": 1,
            "entered_predictor_count": 1,
            "steps": [
                {
                    "entry_order": 1,
                    "predictor_id": "cost.solaredge.capex",
                    "incremental_r_squared": 0.4,
                    "cumulative_r_squared": 0.4,
                    "standardized_beta": 0.7,
                    "sign": "positive",
                }
            ],
            "exclusions": {},
            "warnings": [],
            "final_r_squared": 0.4,
            "minimum_entry_improvement": 1e-6,
            "r_squared_tie_absolute_tolerance": 1e-12,
        }
    }


def _scenario(
    index: int,
    *,
    solaredge_probability: float = 0.0,
    solectria_probability: float = 0.0,
    hurdle_probability: float = 0.0,
    comparison_classification: str | None = None,
    input_status: str = "documented_inputs",
    convergence_status: str = "stable",
    convergence_reasons: list[str] | None = None,
    sensitivity: dict | None = None,
) -> tuple[dict, dict]:
    revision_id = f"dscr_scenario_{index}_r1"
    scenario_id = f"dsc_scenario_{index}"
    tea_job_id = f"tea_scenario_{index}"
    tradeoff_summary = _tradeoff_summary(
        solaredge_probability=solaredge_probability,
        solectria_probability=solectria_probability,
        hurdle_probability=hurdle_probability,
    )
    request = {
        "basis": "solartac_site",
        "scenario": index,
        "n": tradeoff_summary["denominator"],
    }
    request_sha256 = _sha(request)
    source_sha256 = "2" * 64
    receipts: list[dict] = []
    evidence_sha256 = _evidence_set_sha256(receipts)
    result_sha256 = f"{index + 5:x}" * 64
    result_provenance_sha256 = f"{index + 8:x}" * 64
    export_manifest_sha256 = "8" * 64
    reporting_tie_outs = {
        "status": "passed",
        "failed_check_ids": [],
        "check_count": 1,
        "realization_row_count": tradeoff_summary["denominator"],
    }
    tieout_sha256 = _reporting_tieout_sha256(
        export_manifest_sha256,
        reporting_tie_outs,
    )
    numerical_provenance = deepcopy(_NUMERICAL_PROVENANCE)
    attempt_history = [
        {
            "tea_job_id": tea_job_id,
            "attempt_number": 1,
            "retry_of_job_id": None,
            "state": "done",
            "selected_for_comparison": True,
            "request_sha256": request_sha256,
            "source_snapshot_sha256": source_sha256,
            "result_sha256": result_sha256,
            "result_provenance_sha256": result_provenance_sha256,
        }
    ]
    comparison_classification = comparison_classification or (
        "baseline" if index == 0 else "controlled"
    )
    result = {
        "calculation_contract_version": tea.CALCULATION_CONTRACT_VERSION,
        "sampling_version": tea.SAMPLING_VERSION,
        "energy_available": True,
        "input_status": input_status,
        "joint_outcomes": {
            "tradeoff_classes": tradeoff_summary,
        },
        "convergence": {
            "status": convergence_status,
            "reasons": (
                [] if convergence_reasons is None else convergence_reasons
            ),
            "checkpoints": [
                {
                    "realization_count": tradeoff_summary["denominator"],
                    "tradeoff_probabilities": deepcopy(
                        tradeoff_summary["probabilities"]
                    ),
                }
            ],
        },
        "quality": {
            "reporting_tie_outs": deepcopy(reporting_tie_outs),
            "reporting_checks": [
                {
                    "check_id": "class_count_total::tradeoff_classes",
                    "actual_authority": tradeoff_summary["denominator"],
                    "expected_authority": tradeoff_summary["denominator"],
                    "difference_authority": 0,
                    "tolerance": 0.0,
                    "status_authority": "OK",
                    "notes": "Every realization has one tradeoff class.",
                }
            ],
            "numerical_provenance": deepcopy(numerical_provenance),
        },
        "sensitivity": sensitivity or {},
        "warnings": [],
    }
    scenario = {
        "scenario_id": scenario_id,
        "scenario_revision_id": revision_id,
        "ordinal": index,
        "label": f"Scenario {index}",
        "kind": "baseline" if index == 0 else "alternative",
        "comparison_classification": comparison_classification,
        "structural_warning": (
            "This scenario changes request structure; baseline-relative causal "
            "attribution is limited."
            if comparison_classification == "structural"
            else None
        ),
        "request_sha256": request_sha256,
        "attempt": {
            "tea_job_id": tea_job_id,
            "attempt_number": 1,
            "retry_of_job_id": None,
            "durable_state": "done",
            "display_status": "done",
            "terminal": True,
            "selected_by_explicit_link": True,
        },
        "attempt_history": attempt_history,
        "verification": {
            "status": "verified",
            "checks": [{"code": "all_verified", "status": "passed"}],
            "failures": [],
        },
        "request": request,
        "source": {
            "analysis_basis": "solartac_site",
            "source_annual_job_id": "annual-source",
            "source_snapshot_sha256": source_sha256,
        },
        "evidence": {
            "status": input_status,
            "receipts": receipts,
            "evidence_set_sha256": evidence_sha256,
            "evidence_class_counts": {},
            "gaps": [],
        },
        "result": result,
        "provenance": {
            "request_sha256": request_sha256,
            "source_snapshot_sha256": source_sha256,
            "submission_provenance_sha256": "3" * 64,
            "validated_kernel_request_sha256": "4" * 64,
            "routine_result_sha256": result_sha256,
            "sealed_calculation_sha256": "5" * 64,
            "export_manifest_sha256": export_manifest_sha256,
            "exports": {"manifest_sha256": export_manifest_sha256},
            "source_annual_job_id": "annual-source",
            "kernel": {
                "calculation_contract_version": tea.CALCULATION_CONTRACT_VERSION,
                "sampling_version": tea.SAMPLING_VERSION,
                "analysis_basis": "solartac_site",
                "realization_count": tradeoff_summary["denominator"],
                "energy_status": "available",
                "numerics": deepcopy(numerical_provenance),
            },
            "kernel_numerics": deepcopy(numerical_provenance),
            "reporting_tie_outs": deepcopy(reporting_tie_outs),
            "reporting_tieout_sha256": tieout_sha256,
            "evidence_set_sha256": evidence_sha256,
        },
    }
    proof = {
        "item_index": index,
        "scenario_revision_id": revision_id,
        "scenario_id": scenario_id,
        "scenario_revision": 1,
        "attempt_number": 1,
        "tea_job_id": tea_job_id,
        "retry_of_job_id": None,
        "selected_for_comparison": True,
        "state": "done",
        "verification_status": "verified",
        "request_sha256": request_sha256,
        "source_snapshot_sha256": source_sha256,
        "result_sha256": result_sha256,
        "result_provenance_sha256": result_provenance_sha256,
        "result_projection_sha256": (
            comparison.result_projection_commitment_sha256(
                durable_result_sha256=result_sha256,
                result_projection=result,
            )
        ),
        "evidence_set_sha256": evidence_sha256,
        "reporting_tieout_sha256": tieout_sha256,
    }
    return scenario, proof


def _bundle(*scenario_specs: dict) -> dict:
    scenarios: list[dict] = []
    proofs: list[dict] = []
    for index, spec in enumerate(scenario_specs):
        scenario, proof = _scenario(index, **spec)
        scenarios.append(scenario)
        proofs.append(proof)
    bundle = {
        "schema_version": comparison.COMPARISON_BUNDLE_SCHEMA_VERSION,
        "is_complete": True,
        "recommendation_eligible": False,
        "case": {"case_id": "dc_case", "expected_case_revision": 6},
        "confirmation": {
            "confirmation_id": "dsc_confirm",
            "receipt_sha256": "a" * 64,
            "confirmation_request_sha256": "b" * 64,
            "case_revision_before": 5,
            "case_revision_after": 6,
            "confirmed_at": "2026-08-29T12:00:00+00:00",
            "ordered_scenario_revision_ids": [
                scenario["scenario_revision_id"] for scenario in scenarios
            ],
        },
        "selection_contract": comparison.ATTEMPT_SELECTION_CONTRACT_VERSION,
        "completeness": {
            "status": "complete",
            "selected_count": len(scenarios),
            "verified_done_count": len(scenarios),
            "blockers": [],
        },
        "attempt_proofs": proofs,
        "scenarios": scenarios,
        "comparison": {
            "request_matrix": [],
            "metric_matrix": [],
            "compatibility": {"status": "compatible", "blockers": []},
        },
        "recommendation": {
            "state": comparison.CLASSIFICATION_PENDING_CONTRACT,
            "classification": None,
            "confidence": None,
            "contract_version": None,
            "blockers": ["recommendation_threshold_contract_missing"],
            "decisive_evidence": [],
            "major_drivers": [],
            "important_uncertainty": [],
            "evidence_gaps": [],
            "model_limitations": [],
            "reversal_conditions": [],
        },
        "canonicalization": {
            "version": comparison.CANONICALIZATION_VERSION,
            "algorithm": "sha256",
            "encoding": "utf-8",
            "json": "sort_keys-compact-no_nan-ascii",
            "excluded_fields": ["bundle_hash"],
        },
    }
    bundle["bundle_hash"] = comparison.canonical_comparison_bundle_sha256(bundle)
    return bundle


def _reseal(bundle: dict) -> dict:
    bundle["bundle_hash"] = comparison.canonical_comparison_bundle_sha256(bundle)
    return bundle


class RecommendationPolicyContractTests(unittest.TestCase):
    def test_policy_version_and_digest_are_fixed(self) -> None:
        self.assertEqual(
            "autonomy-conservative-dominance-v1",
            recommendation.RECOMMENDATION_CONTRACT_VERSION,
        )
        self.assertEqual(
            _EXPECTED_CONTRACT_DIGEST,
            recommendation.RECOMMENDATION_CONTRACT_DIGEST,
        )
        self.assertEqual(
            _EXPECTED_CONTRACT_DIGEST,
            recommendation._canonical_sha256(  # type: ignore[attr-defined]
                recommendation.recommendation_contract_payload()
            ),
        )
        repository_root = Path(__file__).resolve().parents[1]
        addendum = (
            repository_root
            / "docs"
            / "AUTONOMY_CONSERVATIVE_RECOMMENDATION_CONTRACT_V1.md"
        ).read_text(encoding="utf-8")
        self.assertIn(recommendation.RECOMMENDATION_CONTRACT_VERSION, addendum)
        self.assertIn(_EXPECTED_CONTRACT_DIGEST, addendum)
        for name in (
            "HYBRID_AUTONOMY_FRONTEND_FOUNDATION_V1.md",
            "HYBRID_AUTONOMY_WORKSPACE_PRODUCT_CONTRACT_V1.md",
            "UNIFIED_AUTONOMY_TEA_PRODUCT_CONTRACT_V1.md",
            "TECHNOECONOMIC_CALCULATION_CONTRACT.md",
        ):
            self.assertIn(
                "AUTONOMY_CONSERVATIVE_RECOMMENDATION_CONTRACT_V1.md",
                (repository_root / "docs" / name).read_text(encoding="utf-8"),
            )

    def test_solaredge_boundaries_are_exact(self) -> None:
        cases = (
            (0.899999, "no_decisive_winner", "not_applicable"),
            (0.90, "solaredge", "mixed"),
            (0.949999, "solaredge", "mixed"),
            (0.95, "solaredge", "strong"),
        )
        for probability, classification, confidence in cases:
            with self.subTest(probability=probability):
                result = recommendation.classify_comparison_bundle(
                    _bundle({"solaredge_probability": probability})
                )
                self.assertEqual("available", result["state"])
                self.assertEqual(classification, result["classification"])
                self.assertEqual(confidence, result["confidence"])

    def test_solectria_boundaries_are_exact(self) -> None:
        cases = (
            (0.899999, "no_decisive_winner", "not_applicable"),
            (0.90, "solectria", "mixed"),
            (0.949999, "solectria", "mixed"),
            (0.95, "solectria", "strong"),
        )
        for probability, classification, confidence in cases:
            with self.subTest(probability=probability):
                result = recommendation.classify_comparison_bundle(
                    _bundle({"solectria_probability": probability})
                )
                self.assertEqual(classification, result["classification"])
                self.assertEqual(confidence, result["confidence"])

    def test_every_selected_scenario_participates_and_conflict_has_no_winner(
        self,
    ) -> None:
        result = recommendation.classify_comparison_bundle(
            _bundle(
                {"solaredge_probability": 0.95},
                {"solectria_probability": 0.95},
            )
        )
        self.assertEqual("no_decisive_winner", result["classification"])
        self.assertEqual("not_applicable", result["confidence"])
        self.assertEqual(2, len(result["scenario_evidence"]))
        self.assertIn(
            "cross_scenario_direction_conflict",
            {row["code"] for row in result["reasons"]},
        )
        self.assertEqual(
            {"completed_scenario_comparison"},
            {
                row["source"]
                for row in result["reversal_conditions"]
            },
        )
        self.assertTrue(
            all(
                row["break_even_threshold"] is None
                for row in result["reversal_conditions"]
            )
        )

    def test_one_unfavorable_scenario_cannot_be_omitted(self) -> None:
        bundle = _bundle(
            {"solaredge_probability": 0.95},
            {"solectria_probability": 0.95},
        )
        bundle["scenarios"].pop()
        bundle["attempt_proofs"].pop()
        bundle["completeness"]["selected_count"] = 1
        bundle["completeness"]["verified_done_count"] = 1

        result = recommendation.classify_comparison_bundle(_reseal(bundle))

        self.assertEqual("unavailable", result["state"])
        self.assertIn(
            "confirmation_scenario_membership_mismatch",
            {row["code"] for row in result["blockers"]},
        )

    def test_confirmation_scenario_order_is_exact(self) -> None:
        bundle = _bundle(
            {"solaredge_probability": 0.95},
            {"solaredge_probability": 0.95},
        )
        bundle["scenarios"].reverse()
        bundle["attempt_proofs"].reverse()
        for index, (scenario, proof) in enumerate(
            zip(bundle["scenarios"], bundle["attempt_proofs"], strict=True)
        ):
            scenario["ordinal"] = index
            proof["item_index"] = index

        result = recommendation.classify_comparison_bundle(_reseal(bundle))

        self.assertEqual("unavailable", result["state"])
        self.assertIn(
            "confirmation_scenario_order_mismatch",
            {row["code"] for row in result["blockers"]},
        )

    def test_tradeoff_probability_never_becomes_a_directional_winner(self) -> None:
        result = recommendation.classify_comparison_bundle(
            _bundle({"hurdle_probability": 0.90})
        )
        self.assertEqual("no_decisive_winner", result["classification"])
        self.assertEqual("not_applicable", result["confidence"])
        self.assertIn(
            "cost_energy_tradeoff_requires_unapproved_hurdle",
            {row["code"] for row in result["reasons"]},
        )
        evidence = result["scenario_evidence"][0]
        self.assertEqual(0.90, evidence["unapproved_hurdle_tradeoff_probability"])

    def test_provisional_evidence_requires_explicit_warning_acknowledgement(
        self,
    ) -> None:
        result = recommendation.classify_comparison_bundle(
            _bundle(
                {
                    "solaredge_probability": 0.95,
                    "input_status": "provisional_inputs",
                }
            )
        )
        self.assertEqual("solaredge", result["classification"])
        self.assertEqual("provisional", result["confidence"])
        self.assertEqual(1, len(result["warnings"]))
        self.assertEqual(1, len(result["required_acknowledgements"]))
        self.assertEqual("provisional_inputs", result["warnings"][0]["code"])

    def test_not_demonstrated_convergence_is_a_permitted_provisional_warning(
        self,
    ) -> None:
        result = recommendation.classify_comparison_bundle(
            _bundle(
                {
                    "solectria_probability": 0.95,
                    "convergence_status": "not_demonstrated",
                    "convergence_reasons": [
                        "relative_quantile_change:metric:p50"
                    ],
                }
            )
        )
        self.assertEqual("solectria", result["classification"])
        self.assertEqual("provisional", result["confidence"])
        self.assertEqual(
            "convergence_not_demonstrated", result["warnings"][0]["code"]
        )

    def test_failed_hard_convergence_gate_makes_recommendation_unavailable(
        self,
    ) -> None:
        result = recommendation.classify_comparison_bundle(
            _bundle(
                {
                    "solaredge_probability": 0.99,
                    "convergence_status": "failed",
                    "convergence_reasons": ["invalid_checkpoint"],
                }
            )
        )
        self.assertEqual("unavailable", result["state"])
        self.assertFalse(result["recommendation_eligible"])
        self.assertIsNone(result["classification"])
        self.assertIn(
            "hard_convergence_gate_failed",
            {row["code"] for row in result["blockers"]},
        )

    def test_missing_required_evidence_makes_recommendation_unavailable(self) -> None:
        bundle = _bundle({"solaredge_probability": 0.99})
        bundle["scenarios"][0]["evidence"]["gaps"] = [
            {"code": "required_receipt_missing"}
        ]
        result = recommendation.classify_comparison_bundle(_reseal(bundle))
        self.assertEqual("unavailable", result["state"])
        self.assertIn(
            "required_evidence_gap",
            {row["code"] for row in result["blockers"]},
        )
        self.assertEqual(1, len(result["evidence_gaps"]))

    def test_verification_failure_makes_recommendation_unavailable(self) -> None:
        bundle = _bundle({"solaredge_probability": 0.99})
        bundle["scenarios"][0]["verification"] = {
            "status": "failed",
            "checks": [{"code": "result_hash", "status": "failed"}],
            "failures": [{"code": "result_hash_mismatch"}],
        }
        result = recommendation.classify_comparison_bundle(_reseal(bundle))
        self.assertEqual("unavailable", result["state"])
        self.assertIn(
            "selected_attempt_not_reverified_done",
            {row["code"] for row in result["blockers"]},
        )

    def test_canonical_request_digest_is_bound_to_selected_attempt(self) -> None:
        bundle = _bundle({"solaredge_probability": 0.95})
        bundle["scenarios"][0]["request"]["scenario"] = 999

        result = recommendation.classify_comparison_bundle(_reseal(bundle))

        self.assertEqual("unavailable", result["state"])
        self.assertIn(
            "scenario_request_digest_mismatch",
            {row["code"] for row in result["blockers"]},
        )

    def test_evidence_digest_is_bound_to_receipt_identities(self) -> None:
        bundle = _bundle({"solaredge_probability": 0.95})
        bundle["scenarios"][0]["evidence"]["receipts"].append(
            {
                "request_path": "cost_lines[0].value",
                "evidence_receipt_id": "der_added_after_confirmation",
                "receipt_sha256": "c" * 64,
                "content_sha256": "d" * 64,
            }
        )
        bundle["scenarios"][0]["evidence"]["evidence_class_counts"] = {
            "direct_quote": 1
        }

        result = recommendation.classify_comparison_bundle(_reseal(bundle))

        self.assertEqual("unavailable", result["state"])
        self.assertIn(
            "evidence_set_digest_mismatch",
            {row["code"] for row in result["blockers"]},
        )

    def test_reporting_tieout_digest_is_bound_across_result_proof_and_provenance(
        self,
    ) -> None:
        cases: list[tuple[str, dict]] = []

        changed_result = _bundle({"solaredge_probability": 0.95})
        changed_result["scenarios"][0]["result"]["quality"][
            "reporting_tie_outs"
        ]["check_count"] = 2
        changed_result_proof = changed_result["attempt_proofs"][0]
        changed_result_proof["result_projection_sha256"] = (
            comparison.result_projection_commitment_sha256(
                durable_result_sha256=changed_result_proof["result_sha256"],
                result_projection=changed_result["scenarios"][0]["result"],
            )
        )
        cases.append(("result_tieout_changed", changed_result))

        changed_proof = _bundle({"solaredge_probability": 0.95})
        changed_proof["attempt_proofs"][0]["reporting_tieout_sha256"] = "f" * 64
        cases.append(("proof_digest_changed", changed_proof))

        for case_name, bundle in cases:
            with self.subTest(case=case_name):
                result = recommendation.classify_comparison_bundle(_reseal(bundle))
                self.assertEqual("unavailable", result["state"])
                self.assertIn(
                    "reporting_tieout_digest_mismatch",
                    {row["code"] for row in result["blockers"]},
                )

    def test_projected_tradeoff_population_is_bound_to_durable_result(self) -> None:
        bundle = _bundle({"solectria_probability": 0.95})
        scenario = bundle["scenarios"][0]
        replacement = _tradeoff_summary(solaredge_probability=0.95)
        scenario["result"]["joint_outcomes"]["tradeoff_classes"] = replacement
        scenario["result"]["convergence"]["checkpoints"][-1][
            "tradeoff_probabilities"
        ] = deepcopy(replacement["probabilities"])

        result = recommendation.classify_comparison_bundle(_reseal(bundle))

        self.assertEqual("unavailable", result["state"])
        self.assertIn(
            "result_projection_digest_mismatch",
            {row["code"] for row in result["blockers"]},
        )

    def test_malformed_tradeoff_population_fails_closed(self) -> None:
        bundle = _bundle({"solaredge_probability": 0.95})
        probabilities = bundle["scenarios"][0]["result"]["joint_outcomes"][
            "tradeoff_classes"
        ]["probabilities"]
        probabilities["cost_saving_energy_gain"] = 0.96
        proof = bundle["attempt_proofs"][0]
        proof["result_projection_sha256"] = (
            comparison.result_projection_commitment_sha256(
                durable_result_sha256=proof["result_sha256"],
                result_projection=bundle["scenarios"][0]["result"],
            )
        )
        result = recommendation.classify_comparison_bundle(_reseal(bundle))
        self.assertEqual("unavailable", result["state"])
        self.assertIn(
            "tradeoff_probability_count_mismatch",
            {row["code"] for row in result["blockers"]},
        )

    def test_retry_history_and_attempt_proofs_must_be_complete(self) -> None:
        bundle = _bundle({"solaredge_probability": 0.95})
        selected = bundle["scenarios"][0]["attempt_history"][0]
        failed = {
            **deepcopy(selected),
            "tea_job_id": "tea_failed_original",
            "attempt_number": 1,
            "state": "error",
            "selected_for_comparison": False,
            "result_sha256": None,
            "result_provenance_sha256": None,
        }
        selected["attempt_number"] = 2
        selected["retry_of_job_id"] = "tea_failed_original"
        bundle["scenarios"][0]["attempt"]["attempt_number"] = 2
        bundle["scenarios"][0]["attempt"]["retry_of_job_id"] = (
            "tea_failed_original"
        )
        bundle["scenarios"][0]["attempt_history"].insert(0, failed)
        selected_proof = bundle["attempt_proofs"][0]
        selected_proof["attempt_number"] = 2
        selected_proof["retry_of_job_id"] = "tea_failed_original"
        failed_proof = {
            **deepcopy(selected_proof),
            "tea_job_id": "tea_failed_original",
            "attempt_number": 1,
            "retry_of_job_id": None,
            "selected_for_comparison": False,
            "state": "error",
            "verification_status": "not_applicable",
            "result_sha256": None,
            "result_provenance_sha256": None,
            "result_projection_sha256": None,
            "reporting_tieout_sha256": None,
        }
        bundle["attempt_proofs"].insert(0, failed_proof)
        valid = recommendation.classify_comparison_bundle(_reseal(bundle))
        self.assertEqual("solaredge", valid["classification"])

        omitted = deepcopy(bundle)
        omitted["attempt_proofs"].pop(0)
        unavailable = recommendation.classify_comparison_bundle(_reseal(omitted))
        self.assertEqual("unavailable", unavailable["state"])
        self.assertIn(
            "attempt_proof_missing",
            {row["code"] for row in unavailable["blockers"]},
        )

    def test_retry_chain_must_be_contiguous_and_select_its_final_attempt(
        self,
    ) -> None:
        discontinuous = _bundle({"solaredge_probability": 0.95})
        discontinuous_scenario = discontinuous["scenarios"][0]
        discontinuous_history = discontinuous_scenario["attempt_history"][0]
        discontinuous_proof = discontinuous["attempt_proofs"][0]
        discontinuous_history["attempt_number"] = 2
        discontinuous_history["retry_of_job_id"] = "tea_missing_parent"
        discontinuous_scenario["attempt"]["attempt_number"] = 2
        discontinuous_scenario["attempt"]["retry_of_job_id"] = (
            "tea_missing_parent"
        )
        discontinuous_proof["attempt_number"] = 2
        discontinuous_proof["retry_of_job_id"] = "tea_missing_parent"

        nonfinal = _bundle({"solaredge_probability": 0.95})
        nonfinal_scenario = nonfinal["scenarios"][0]
        first_history = nonfinal_scenario["attempt_history"][0]
        retry_history = {
            **deepcopy(first_history),
            "tea_job_id": "tea_retry_error",
            "attempt_number": 2,
            "retry_of_job_id": first_history["tea_job_id"],
            "state": "error",
            "selected_for_comparison": False,
            "result_sha256": None,
            "result_provenance_sha256": None,
        }
        nonfinal_scenario["attempt_history"].append(retry_history)
        first_proof = nonfinal["attempt_proofs"][0]
        retry_proof = {
            **deepcopy(first_proof),
            "tea_job_id": "tea_retry_error",
            "attempt_number": 2,
            "retry_of_job_id": first_history["tea_job_id"],
            "state": "error",
            "selected_for_comparison": False,
            "verification_status": "not_applicable",
            "result_sha256": None,
            "result_provenance_sha256": None,
            "result_projection_sha256": None,
            "reporting_tieout_sha256": None,
        }
        nonfinal["attempt_proofs"].append(retry_proof)

        cases = (
            (
                "discontinuous",
                discontinuous,
                "attempt_chain_not_contiguous",
            ),
            (
                "selected_not_final",
                nonfinal,
                "selected_attempt_not_chain_endpoint",
            ),
        )
        for case_name, bundle, expected_blocker in cases:
            with self.subTest(case=case_name):
                result = recommendation.classify_comparison_bundle(_reseal(bundle))
                self.assertEqual("unavailable", result["state"])
                self.assertIn(
                    expected_blocker,
                    {row["code"] for row in result["blockers"]},
                )

    def test_structural_comparison_uses_same_policy_and_retains_warning(self) -> None:
        result = recommendation.classify_comparison_bundle(
            _bundle(
                {"solaredge_probability": 0.95},
                {
                    "solaredge_probability": 0.95,
                    "comparison_classification": "structural",
                },
            )
        )
        self.assertEqual("solaredge", result["classification"])
        self.assertEqual("strong", result["confidence"])
        self.assertIn(
            "structural_comparison_causal_attribution_limited",
            {row["code"] for row in result["model_limitations"]},
        )
        self.assertTrue(result["model_limitations"][0]["acknowledgement_required"])
        self.assertEqual(1, len(result["required_acknowledgements"]))
        self.assertEqual(
            "acknowledge_model_limitation",
            result["required_acknowledgements"][0]["code"],
        )

    def test_historical_v8_bundle_rederives_missing_comparison_classification(
        self,
    ) -> None:
        bundle = _bundle(
            {"solaredge_probability": 0.95},
            {"solaredge_probability": 0.95},
        )
        for scenario in bundle["scenarios"]:
            scenario.pop("comparison_classification")
            scenario.pop("structural_warning")
        result = recommendation.classify_comparison_bundle(_reseal(bundle))

        self.assertEqual("solaredge", result["classification"])
        self.assertEqual(
            ["baseline", "controlled"],
            [
                row["comparison_classification"]
                for row in result["scenario_evidence"]
            ],
        )

    def test_historical_structural_bundle_rederives_and_retains_warning(self) -> None:
        bundle = _bundle(
            {"solaredge_probability": 0.95},
            {"solaredge_probability": 0.95},
        )
        for scenario in bundle["scenarios"]:
            scenario.pop("comparison_classification")
            scenario.pop("structural_warning")
        bundle["scenarios"][1]["request"]["cost_lines"] = [
            {"input_id": "cost.new-structure"}
        ]
        structural = bundle["scenarios"][1]
        structural_request_sha256 = _sha(structural["request"])
        structural["request_sha256"] = structural_request_sha256
        structural["provenance"]["request_sha256"] = structural_request_sha256
        for history in structural["attempt_history"]:
            history["request_sha256"] = structural_request_sha256
        for proof in bundle["attempt_proofs"]:
            if (
                proof["scenario_revision_id"]
                == structural["scenario_revision_id"]
            ):
                proof["request_sha256"] = structural_request_sha256
        result = recommendation.classify_comparison_bundle(_reseal(bundle))

        self.assertEqual("solaredge", result["classification"])
        self.assertEqual(
            "structural",
            result["scenario_evidence"][1]["comparison_classification"],
        )
        self.assertIn(
            "structural_comparison_causal_attribution_limited",
            {row["code"] for row in result["model_limitations"]},
        )

    def test_historical_comparison_fails_closed_when_baseline_is_ambiguous(
        self,
    ) -> None:
        bundle = _bundle({"solaredge_probability": 0.95})
        bundle["scenarios"][0]["kind"] = "alternative"
        bundle["scenarios"][0].pop("comparison_classification")
        bundle["scenarios"][0].pop("structural_warning")
        result = recommendation.classify_comparison_bundle(_reseal(bundle))

        self.assertEqual("unavailable", result["state"])
        self.assertIn(
            "historical_comparison_classification_unprovable",
            {row["code"] for row in result["blockers"]},
        )

    def test_reversal_candidates_use_only_validated_sensitivity_and_never_execute(
        self,
    ) -> None:
        result = recommendation.classify_comparison_bundle(
            _bundle(
                {
                    "solaredge_probability": 0.95,
                    "sensitivity": _sensitivity(),
                }
            )
        )
        self.assertEqual(1, len(result["reversal_conditions"]))
        reversal = result["reversal_conditions"][0]
        self.assertEqual("validated_sensitivity", reversal["source"])
        self.assertIsNone(reversal["break_even_threshold"])
        self.assertEqual("not_calculated", reversal["threshold_status"])
        self.assertFalse(reversal["draft_deep_link"]["mutates_from_brief"])
        self.assertFalse(reversal["draft_deep_link"]["executes"])
        self.assertEqual(
            "create_controlled_scenario_draft",
            reversal["draft_deep_link"]["action"],
        )

    def test_unavailable_sensitivity_does_not_fabricate_a_reversal(self) -> None:
        result = recommendation.classify_comparison_bundle(
            _bundle(
                {
                    "solaredge_probability": 0.95,
                    "sensitivity": {
                        "metric": {
                            "status": "unavailable",
                            "reason": "insufficient_rows",
                        }
                    },
                }
            )
        )
        self.assertEqual([], result["reversal_conditions"])

    def test_bundle_hash_and_expected_identity_are_fail_closed(self) -> None:
        bundle = _bundle({"solaredge_probability": 0.95})
        expected = bundle["bundle_hash"]
        result = recommendation.classify_comparison_bundle(
            bundle, expected_bundle_sha256=expected
        )
        self.assertEqual(expected, result["comparison_bundle_sha256"])

        bundle["case"]["case_id"] = "dc_tampered"
        with self.assertRaises(recommendation.RecommendationContractError) as caught:
            recommendation.classify_comparison_bundle(bundle)
        self.assertEqual("comparison_bundle_hash_mismatch", caught.exception.code)

        different = _bundle({"solaredge_probability": 0.90})
        with self.assertRaises(recommendation.RecommendationContractError) as caught:
            recommendation.classify_comparison_bundle(
                different, expected_bundle_sha256=expected
            )
        self.assertEqual("comparison_bundle_identity_mismatch", caught.exception.code)


if __name__ == "__main__":
    unittest.main()
