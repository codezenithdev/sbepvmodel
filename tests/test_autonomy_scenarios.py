from __future__ import annotations

from copy import deepcopy
import hashlib
import unittest
from unittest.mock import patch

from pydantic import ValidationError

from sbepv.api.autonomy_schemas import DecisionScenarioCreateRequest
from sbepv.api import technoeconomic as tea_api
from sbepv.autonomy import scenarios


def _evidence() -> dict:
    return {
        "evidence_class": "direct_quote_or_primary_document",
        "citation": {
            "title": "Scenario service test evidence",
            "organization": "Test laboratory",
            "url": "https://example.com/scenario-evidence",
            "stable_reference": None,
            "publication_or_as_of_date": "2026-01-01",
            "accessed_date": "2026-08-29",
            "excerpt_or_derivation_note": "Synthetic value used only in tests.",
            "preservation_mode": "metadata_excerpt_only",
            "user_supplied_content_sha256": None,
            "metadata_only_rationale": "The strict TEA schema requires this metadata.",
        },
        "explicit_acceptance": None,
        "acceptance_rationale": None,
    }


def _request(*, source_id: str = "annual-source", value: float = 10.0) -> dict:
    return {
        "source_annual_job_id": source_id,
        "basis": "solartac_site",
        "capacity_normalization": "annual_applied_capacity_v1",
        "n": 32,
        "seed": 42,
        "cost_stack_completeness": "full_system",
        "cost_lines": [
            {
                "input_id": "cost.shared.capex",
                "label": "Shared installed CAPEX",
                "ownership": "paired_shared",
                "cost_type": "initial_capex",
                "distribution": {"family": "fixed", "value": value},
                "coverage_include_ids": ["equipment.shared"],
                "coverage_exclude_ids": [],
                "original_unit": "usd_total",
                "normalized_unit": "usd_per_applied_w",
                "normalization_method": "divide_by_frozen_applied_capacity_w",
                "solectria_quantity": 1.0,
                "solaredge_quantity": 1.0,
                "quantity_unit": None,
                "normalization_derivation": (
                    "Divide each project total by its frozen applied capacity."
                ),
                "constant_dollar_cost_year": 2026,
                "currency_year_normalization": {
                    "method": "same_year_no_adjustment",
                    "source_cost_year": 2026,
                    "target_constant_dollar_cost_year": 2026,
                    "submitted_distribution_basis": "target_constant_dollar_year",
                    "index_identity": "not_applicable_same_year",
                    "index_factor": 1.0,
                    "derivation": "Source and target use the same dollar year.",
                },
                "evidence": _evidence(),
            }
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
        "commercial_scaling": None,
    }


def _case(*, basis: str = "solartac_site") -> dict:
    return {
        "case_id": "dcase_test",
        "source_annual_job_id": "annual-source",
        "source_snapshot_sha256": "a" * 64,
        "analysis_basis": basis,
    }


def _legacy_request() -> dict:
    payload = _request()
    payload.pop("capacity_normalization")
    for line in payload["cost_lines"]:
        line["normalized_unit"] = "usd_per_wdc"
        line["normalization_method"] = "divide_by_frozen_source_wdc"
    return payload


class AutonomyScenarioContractTests(unittest.TestCase):
    def test_normalization_matches_standalone_omissions_and_hashing(self) -> None:
        canonical, digest = scenarios.normalize_submission_request(_legacy_request())

        self.assertNotIn("capacity_normalization", canonical)
        self.assertNotIn("commercial_scaling", canonical)
        self.assertIn("commercial_reference_design", canonical)
        self.assertIsNone(canonical["commercial_reference_design"])
        self.assertIn("commercial_transfer", canonical)
        self.assertIsNone(canonical["commercial_transfer"])
        self.assertEqual(tea_api.canonical_json_sha256(canonical), digest)

        reordered = dict(reversed(list(_legacy_request().items())))
        reordered_canonical, reordered_digest = scenarios.normalize_submission_request(
            reordered
        )
        self.assertEqual(canonical, reordered_canonical)
        self.assertEqual(digest, reordered_digest)

    def test_alternative_defaults_to_baseline_realizations_and_seed(self) -> None:
        baseline = _request(value=10.0)
        alternative = _request(value=12.0)
        alternative.pop("n")
        alternative.pop("seed")
        changed = ["/cost_lines/0/distribution/value"]

        result = scenarios.validate_scenario_draft(
            case_record=_case(),
            kind="alternative",
            request_payload=alternative,
            baseline_request=baseline,
            declared_changed_fields=changed,
        )

        self.assertTrue(result["valid"], result)
        self.assertEqual(32, result["request"]["n"])
        self.assertEqual(42, result["request"]["seed"])
        self.assertEqual("controlled", result["comparison_classification"])
        self.assertEqual(changed, result["changed_fields"])

    def test_different_realizations_or_seed_are_rejected_with_exact_values(self) -> None:
        baseline = _request()
        alternative = _request(value=11.0)
        alternative["n"] = 16
        alternative["seed"] = 99
        canonical_baseline, _ = scenarios.normalize_submission_request(baseline)
        canonical_alternative, _ = scenarios.normalize_submission_request(alternative)
        changed = [
            row["path"]
            for row in scenarios.json_pointer_leaf_diff(
                canonical_baseline, canonical_alternative
            )
        ]

        result = scenarios.validate_scenario_draft(
            case_record=_case(),
            kind="alternative",
            request_payload=alternative,
            baseline_request=baseline,
            declared_changed_fields=changed,
        )

        self.assertFalse(result["valid"])
        codes = {item["code"] for item in result["field_errors"]}
        self.assertIn("n_must_match_baseline", codes)
        self.assertIn("seed_must_match_baseline", codes)
        alternatives = {
            item["action"]: item for item in result["closest_supported_alternatives"]
        }
        self.assertEqual(32, alternatives["use_baseline_n"]["value"])
        self.assertEqual(42, alternatives["use_baseline_seed"]["value"])

    def test_cost_value_change_is_controlled_and_structure_change_warns(self) -> None:
        baseline = _request()
        controlled = _request(value=12.0)
        controlled_result = scenarios.validate_scenario_draft(
            case_record=_case(),
            kind="alternative",
            request_payload=controlled,
            baseline_request=baseline,
            declared_changed_fields=["/cost_lines/0/distribution/value"],
        )
        self.assertTrue(controlled_result["valid"], controlled_result)
        self.assertEqual("controlled", controlled_result["comparison_classification"])
        self.assertEqual([], controlled_result["warnings"])

        structural = deepcopy(controlled)
        second_line = deepcopy(structural["cost_lines"][0])
        second_line["input_id"] = "cost.shared.installation"
        second_line["label"] = "Shared installation labor"
        second_line["cost_type"] = "initial_installation_labor"
        second_line["coverage_include_ids"] = ["labor.shared"]
        structural["cost_lines"].append(second_line)
        base_request, _ = scenarios.normalize_submission_request(baseline)
        structural_request, _ = scenarios.normalize_submission_request(structural)
        changed = [
            row["path"]
            for row in scenarios.json_pointer_leaf_diff(base_request, structural_request)
        ]
        structural_result = scenarios.validate_scenario_draft(
            case_record=_case(),
            kind="alternative",
            request_payload=structural,
            baseline_request=baseline,
            declared_changed_fields=changed,
        )
        self.assertTrue(structural_result["valid"], structural_result)
        self.assertEqual("structural", structural_result["comparison_classification"])
        self.assertEqual(
            [scenarios.STRUCTURAL_CAUSAL_WARNING], structural_result["warnings"]
        )

    def test_unsupported_field_returns_field_error_and_exact_expert_alternative(self) -> None:
        payload = _request()
        payload["agent_guess"] = "do not infer this"

        result = scenarios.validate_scenario_draft(
            case_record=_case(),
            kind="baseline",
            request_payload=payload,
        )

        self.assertFalse(result["valid"])
        self.assertIn(
            {"path": "/agent_guess", "code": "unsupported_field", "message": "Extra inputs are not permitted"},
            result["field_errors"],
        )
        self.assertEqual(
            scenarios.OPEN_EXPERT_TEA_ALTERNATIVE,
            result["closest_supported_alternatives"][0],
        )

    def test_cross_source_and_cross_basis_require_exact_new_case_action(self) -> None:
        cross_source = _request(source_id="other-annual")
        source_result = scenarios.validate_scenario_draft(
            case_record=_case(),
            kind="baseline",
            request_payload=cross_source,
        )
        self.assertFalse(source_result["valid"])
        self.assertIn(
            "cross_source_comparison",
            {item["code"] for item in source_result["field_errors"]},
        )
        self.assertIn(
            scenarios.CREATE_NEW_CASE_ALTERNATIVE,
            source_result["closest_supported_alternatives"],
        )

        basis_result = scenarios.validate_scenario_draft(
            case_record=_case(basis="commercial_representative"),
            kind="baseline",
            request_payload=_request(),
        )
        self.assertFalse(basis_result["valid"])
        self.assertIn(
            "cross_basis_comparison",
            {item["code"] for item in basis_result["field_errors"]},
        )
        self.assertIn(
            scenarios.CREATE_NEW_CASE_ALTERNATIVE,
            basis_result["closest_supported_alternatives"],
        )

    def test_changed_field_declaration_must_exactly_match_leaf_diff(self) -> None:
        result = scenarios.validate_scenario_draft(
            case_record=_case(),
            kind="alternative",
            request_payload=_request(value=11.0),
            baseline_request=_request(value=10.0),
            declared_changed_fields=["/finance/project_life_years"],
        )

        self.assertFalse(result["valid"])
        errors = {(item["path"], item["code"]) for item in result["field_errors"]}
        self.assertIn(
            ("/cost_lines/0/distribution/value", "undeclared_change"), errors
        )
        self.assertIn(
            ("/finance/project_life_years", "declared_field_unchanged"), errors
        )
        alternative = next(
            item
            for item in result["closest_supported_alternatives"]
            if item["action"] == "use_exact_changed_fields"
        )
        self.assertEqual(
            ["/cost_lines/0/distribution/value"], alternative["changed_fields"]
        )

    def test_evidence_callbacks_verify_receipt_digest_and_preserved_bytes(self) -> None:
        content = b"server-managed scenario evidence"
        content_hash = hashlib.sha256(content).hexdigest()
        receipt_payload = {
            "schema_version": 1,
            "preservation_mode": "server_managed_content_v1",
            "evidence_receipt_id": "evr_receipt1",
            "case_id": "dcase_test",
            "evidence_asset_id": "deva_asset1",
            "evidence_candidate_id": "devc_candidate1",
            "decision": "accepted",
            "evidence_class": "project_actual",
            "candidate": {
                "field_name": "shared_capex",
                "value": 12.0,
                "unit": "usd_total",
                "confidence": 1.0,
                "source_location": {"sheet": "Costs", "cell": "B2"},
            },
            "content": {
                "sha256": content_hash,
                "byte_count": len(content),
                "media_type": "text/csv",
            },
            "review": {
                "operator_name": "Operator",
                "rationale": None,
                "reviewed_at": "2026-08-29T12:00:00+00:00",
            },
        }
        receipt = {
            "id": "evr_receipt1",
            "case_id": "dcase_test",
            "decision": "accepted",
            "evidence_class": "project_actual",
            "evidence_asset_id": "deva_asset1",
            "preservation_mode": "server_managed_content_v1",
            "receipt": receipt_payload,
            "receipt_sha256": tea_api.canonical_json_sha256(receipt_payload),
        }
        callback_calls: list[tuple[str, str]] = []

        def receipt_loader(receipt_id: str):
            self.assertEqual("evr_receipt1", receipt_id)
            return deepcopy(receipt)

        def snapshot_loader(case_id: str, asset_id: str):
            callback_calls.append((case_id, asset_id))
            return content, {
                "id": asset_id,
                "case_id": case_id,
                "sha256": content_hash,
                "byte_count": len(content),
                "detected_media_type": "text/csv",
            }

        result = scenarios.validate_scenario_draft(
            case_record=_case(),
            kind="alternative",
            request_payload=_request(value=12.0),
            baseline_request=_request(value=10.0),
            declared_changed_fields=["/cost_lines/0/distribution/value"],
            evidence_references=[
                {
                    "request_path": "/cost_lines/0/distribution/value",
                    "receipt_id": "evr_receipt1",
                }
            ],
            receipt_loader=receipt_loader,
            evidence_snapshot_loader=snapshot_loader,
        )

        self.assertTrue(result["valid"], result)
        self.assertEqual([("dcase_test", "deva_asset1")], callback_calls)
        self.assertEqual(content_hash, result["evidence_receipts"][0]["content_sha256"])
        self.assertEqual(
            receipt["receipt_sha256"],
            result["evidence_receipts"][0]["receipt_sha256"],
        )

        value_mismatch = scenarios.validate_scenario_draft(
            case_record=_case(),
            kind="alternative",
            request_payload=_request(value=13.0),
            baseline_request=_request(value=10.0),
            declared_changed_fields=["/cost_lines/0/distribution/value"],
            evidence_references=[
                {
                    "request_path": "/cost_lines/0/distribution/value",
                    "receipt_id": "evr_receipt1",
                }
            ],
            receipt_loader=receipt_loader,
            evidence_snapshot_loader=snapshot_loader,
        )
        self.assertFalse(value_mismatch["valid"])
        self.assertIn(
            "evidence_candidate_value_mismatch",
            {item["code"] for item in value_mismatch["field_errors"]},
        )

        tampered = deepcopy(receipt)
        tampered["receipt_sha256"] = "0" * 64
        rejected = scenarios.validate_scenario_draft(
            case_record=_case(),
            kind="alternative",
            request_payload=_request(value=12.0),
            baseline_request=_request(value=10.0),
            declared_changed_fields=["/cost_lines/0/distribution/value"],
            evidence_references=[
                {
                    "request_path": "/cost_lines/0/distribution/value",
                    "receipt_id": "evr_receipt1",
                }
            ],
            receipt_loader=lambda _receipt_id: tampered,
            evidence_snapshot_loader=snapshot_loader,
        )
        self.assertFalse(rejected["valid"])
        self.assertIn(
            "evidence_receipt_digest_mismatch",
            {item["code"] for item in rejected["field_errors"]},
        )

    def test_one_request_path_cannot_reference_multiple_evidence_receipts(self) -> None:
        result = scenarios.validate_scenario_draft(
            case_record=_case(),
            kind="baseline",
            request_payload=_request(),
            evidence_references=[
                {
                    "request_path": "/cost_lines/0/distribution/value",
                    "receipt_id": "evr_receipt1",
                },
                {
                    "request_path": "/cost_lines/0/distribution/value",
                    "receipt_id": "evr_receipt2",
                },
            ],
            receipt_loader=lambda _receipt_id: None,
            evidence_snapshot_loader=lambda _case_id, _asset_id: (b"", {}),
        )

        self.assertFalse(result["valid"])
        duplicate = next(
            item
            for item in result["field_errors"]
            if item["code"] == "duplicate_evidence_reference"
        )
        self.assertEqual("/cost_lines/0/distribution/value", duplicate["path"])
        self.assertIn(
            "review_or_replace_evidence",
            {
                item["action"]
                for item in result["closest_supported_alternatives"]
            },
        )

        with self.assertRaisesRegex(ValidationError, "unique request_path"):
            DecisionScenarioCreateRequest.model_validate(
                {
                    "expected_case_revision": 1,
                    "operator_name": "Scenario editor",
                    "label": "Duplicate evidence path",
                    "kind": "baseline",
                    "request": {},
                    "changed_fields": [],
                    "evidence_references": [
                        {
                            "request_path": "/cost_lines/0/distribution/value",
                            "receipt_id": "evr_receipt1",
                        },
                        {
                            "request_path": "/cost_lines/0/distribution/value",
                            "receipt_id": "evr_receipt2",
                        },
                    ],
                }
            )

    def test_leaf_diff_preserves_missing_versus_null(self) -> None:
        rows = scenarios.json_pointer_leaf_diff(
            {"a": None, "removed": {"x": 1}},
            {"a": None, "added": {"x": None}},
        )
        self.assertEqual(
            [
                {
                    "path": "/added/x",
                    "baseline_present": False,
                    "baseline_value": None,
                    "scenario_present": True,
                    "scenario_value": None,
                },
                {
                    "path": "/removed/x",
                    "baseline_present": True,
                    "baseline_value": 1,
                    "scenario_present": False,
                    "scenario_value": None,
                },
            ],
            rows,
        )

    def test_comparison_labels_all_pre_run_values_as_inputs_or_hypotheses(self) -> None:
        baseline_request, baseline_hash = scenarios.normalize_submission_request(
            _request(value=10.0)
        )
        alternative_request, alternative_hash = scenarios.normalize_submission_request(
            _request(value=12.0),
            baseline_request=baseline_request,
            kind="alternative",
        )
        comparison = scenarios.build_scenario_comparison(
            case_record=_case(),
            baseline={
                "scenario_id": "dsc_baseline",
                "revision": 1,
                "label": "Baseline",
                "request": baseline_request,
                "request_sha256": baseline_hash,
                "status": "validated",
            },
            alternatives=[
                {
                    "scenario_id": "dsc_alternative",
                    "revision": 1,
                    "label": "Alternative",
                    "request": alternative_request,
                    "request_sha256": alternative_hash,
                    "status": "validated",
                }
            ],
        )

        self.assertFalse(comparison["outcomes_available"])
        self.assertEqual(
            "inputs_or_hypotheses_not_outcomes",
            comparison["pre_run_value_semantics"],
        )
        row = next(
            item
            for item in comparison["difference_matrix"]
            if item["path"] == "/cost_lines/0/distribution/value"
        )
        self.assertEqual("input", row["baseline"]["value_kind"])
        self.assertEqual("hypothesis", row["alternatives"][0]["value_kind"])

    def test_tea_bundle_uses_only_the_existing_source_kernel_and_provenance_path(self) -> None:
        payload = _request()
        canonical, digest = scenarios.normalize_submission_request(payload)
        envelope = {
            "source_snapshot": {"source_annual_job_id": "annual-source"},
            "source_snapshot_sha256": "a" * 64,
        }
        dependencies = {
            "annual_job": {"id": "annual-source"},
            "origin_validation_job": {"id": "validation-source"},
            "promotion_record": {"promotion_id": 1},
        }
        kernel_request = object()
        provenance = {"request_sha256": digest}
        source_fields = {
            "source_annual_job_id": "annual-source",
            "source_snapshot": envelope["source_snapshot"],
            "atomic_source_check": object(),
        }
        with (
            patch.object(
                tea_api,
                "resolve_annual_source_dependencies",
                return_value=dependencies,
            ) as resolve,
            patch.object(
                tea_api,
                "build_annual_source_snapshot",
                return_value=envelope,
            ) as snapshot,
            patch.object(
                tea_api,
                "build_technoeconomic_kernel_request",
                return_value=kernel_request,
            ) as build_kernel,
            patch.object(
                tea_api,
                "build_technoeconomic_submission_provenance",
                return_value=provenance,
            ) as build_provenance,
            patch.object(
                tea_api,
                "technoeconomic_source_store_fields",
                return_value=source_fields,
            ) as store_fields,
        ):
            bundle = scenarios.prepare_technoeconomic_bundle(
                agent_store=object(),
                case_record=_case(),
                request_payload=payload,
            )

        self.assertEqual(canonical, bundle["request"])
        self.assertEqual(digest, bundle["request_sha256"])
        self.assertIs(kernel_request, bundle["validated_kernel_request"])
        self.assertEqual(provenance, bundle["submission_provenance"])
        self.assertEqual(source_fields, bundle["source_store_fields"])
        self.assertFalse(
            {
                "scenario_id",
                "scenario_revision_id",
                "case_id",
                "confirmation_id",
                "evidence_receipt_ids",
            }
            & set(bundle["request"])
        )
        resolve.assert_called_once()
        snapshot.assert_called_once_with(
            dependencies["annual_job"],
            origin_validation_job=dependencies["origin_validation_job"],
            promotion_record=dependencies["promotion_record"],
        )
        build_kernel.assert_called_once_with(canonical, envelope["source_snapshot"])
        build_provenance.assert_called_once_with(canonical, envelope, kernel_request)
        store_fields.assert_called_once_with(envelope)


if __name__ == "__main__":
    unittest.main()
