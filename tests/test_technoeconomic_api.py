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
                json=payload or _site_request_payload(),
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

        for payload in invalid_payloads:
            with self.assertRaises(ValidationError):
                TechnoeconomicSubmissionRequest.model_validate(payload)
            response = self._create_via_api(payload)
            self.assertEqual(422, response.status_code, response.text)
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
                json=_site_request_payload(),
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
