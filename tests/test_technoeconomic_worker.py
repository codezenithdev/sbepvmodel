from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import threading
import unittest
import uuid
from unittest.mock import Mock, patch

import numpy as np

from sbepv import model
from sbepv.api import config, state
from sbepv.api import technoeconomic as tea_api
from sbepv.api.schemas import TechnoeconomicSubmissionRequest
from sbepv.autonomy import scenarios as autonomy_scenarios
from sbepv.store import AgentStore
from sbepv.worker import loop as worker_loop
from sbepv.worker import run_technoeconomic
from tests.test_technoeconomic_api import (
    _applied_site_request_payload,
    _commercial_scaling_request_payload,
    _paired_commercial_request_payload,
    _site_request_payload,
    _standalone_commercial_request_payload,
)


class TechnoeconomicWorkerPhase3Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.test_root = Path(__file__).resolve().parent / f".tea-worker-{uuid.uuid4().hex}"
        self.output = self.test_root / "outputs"
        self.output.mkdir(parents=True)
        self.db_path = self.test_root / "agent.sqlite3"
        self.store = AgentStore(self.db_path)

        self.original_store = state.AGENT_STORE
        state.AGENT_STORE = self.store
        state.JOBS.clear()
        state._WORKER_STOP.clear()
        state._WORKER_WAKE.clear()
        self.output_patch = patch.object(config, "OUTPUT_DIR", self.output)
        self.source_patch = patch.object(
            config,
            "ANNUAL_SOURCE_ARTIFACT_DIR",
            self.output / ".annual_sources",
        )
        self.output_patch.start()
        self.source_patch.start()
        self.addCleanup(self._cleanup)

        self.source_id = "annual-source"
        self._completed_annual_source()
        raw_source = self.output / "annual-source.csv"
        raw_source.write_bytes(b"date,dni\n2024-01-01,1\n")
        raw_bytes = raw_source.read_bytes()
        raw_hash = hashlib.sha256(raw_bytes).hexdigest()
        storage_key = f"sha256/{raw_hash[:2]}/{raw_hash}.csv"
        self.source_artifact = {
            "schema_version": 1,
            "owner_workflow": "annual_simulation",
            "owner_annual_job_id": self.source_id,
            "content_address_algorithm": "sha256",
            "storage_key": storage_key,
            "sha256": raw_hash,
            "byte_count": len(raw_bytes),
            "media_type": "text/csv",
            "immutable": True,
        }
        self.source_artifact_path = (
            config.ANNUAL_SOURCE_ARTIFACT_DIR
            / Path(self.source_artifact["storage_key"])
        )
        self.source_artifact_path.parent.mkdir(parents=True, exist_ok=True)
        self.source_artifact_path.write_bytes(raw_bytes)
        self.snapshot = {
            "schema_version": 1,
            "eligibility_version": tea_api.ANNUAL_SOURCE_ELIGIBILITY_VERSION,
            "source_annual_job_id": self.source_id,
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
            "midc_source_artifact": deepcopy(self.source_artifact),
        }
        self.snapshot_sha256 = tea_api.canonical_json_sha256(self.snapshot)
        parsed = TechnoeconomicSubmissionRequest.model_validate(
            _site_request_payload(source_id=self.source_id, n=8)
        )
        self.request_payload = parsed.model_dump(mode="json", exclude_none=False)
        # The discriminator did not exist in durable v1 requests.  Keep this
        # fixture byte-for-byte representative of that historical shape.
        self.request_payload.pop("capacity_normalization", None)
        self.request_payload.pop("commercial_scaling", None)
        self.request_payload.pop("standalone_commercial", None)
        self.request_payload.pop("paired_commercial", None)
        kernel_request = tea_api.build_technoeconomic_kernel_request(
            self.request_payload,
            self.snapshot,
        )
        self.submission_provenance = (
            tea_api.build_technoeconomic_submission_provenance(
                self.request_payload,
                {
                    "source_snapshot": self.snapshot,
                    "source_snapshot_sha256": self.snapshot_sha256,
                },
                kernel_request,
            )
        )
        self.job_id = "tea_worker_fixture"
        self._create_tea(self.job_id)

    def _cleanup(self) -> None:
        self.source_patch.stop()
        self.output_patch.stop()
        state.AGENT_STORE = self.original_store
        state.JOBS.clear()
        state._WORKER_STOP.clear()
        state._WORKER_WAKE.clear()
        shutil.rmtree(self.test_root, ignore_errors=True)

    def test_linked_scenario_evidence_preflight_uses_existing_worker_path(self) -> None:
        scenario_record = {
            "case_id": "dcase_worker_evidence",
            "request_sha256": tea_api.canonical_json_sha256(self.request_payload),
            "evidence_receipt_refs": [
                {
                    "request_path": "/cost_lines/0/distribution/value",
                    "evidence_receipt_id": "evr_worker_evidence",
                }
            ],
        }
        with (
            patch.object(
                self.store,
                "get_decision_scenario_job_context",
                return_value={"link": {}, "scenario": scenario_record},
            ),
            patch.object(
                autonomy_scenarios,
                "verify_accepted_evidence_references",
                return_value={"valid": True, "field_errors": [], "receipts": []},
            ) as verify_evidence,
        ):
            run_technoeconomic._verify_decision_scenario_evidence(
                self.job_id,
                self.request_payload,
            )
        verify_evidence.assert_called_once()
        self.assertEqual(
            "dcase_worker_evidence",
            verify_evidence.call_args.kwargs["case_id"],
        )

        with (
            patch.object(
                self.store,
                "get_decision_scenario_job_context",
                return_value={"link": {}, "scenario": scenario_record},
            ),
            patch.object(
                autonomy_scenarios,
                "verify_accepted_evidence_references",
                return_value={
                    "valid": False,
                    "field_errors": [{"code": "evidence_content_digest_mismatch"}],
                    "receipts": [],
                },
            ),
        ):
            with self.assertRaisesRegex(ValueError, "evidence failed immutable preflight"):
                run_technoeconomic._verify_decision_scenario_evidence(
                    self.job_id,
                    self.request_payload,
                )

    def _completed_annual_source(self) -> None:
        self.store.create_job(
            job_id=self.source_id,
            kind="manual",
            mode="annual",
            request={"years": [2024]},
        )
        claimed = self.store.claim_next_queued_job()
        self.assertEqual(self.source_id, claimed["id"])
        self.store.update_job(
            self.source_id,
            state="done",
            result={"mode": "annual", "fixture": True},
        )

    def _create_tea(self, job_id: str) -> dict:
        artifact = self.source_artifact
        return self.store.create_technoeconomic_job(
            job_id=job_id,
            request=self.request_payload,
            source_annual_job_id=self.source_id,
            source_artifact_storage_key=artifact["storage_key"],
            source_artifact_sha256=artifact["sha256"],
            source_artifact_bytes=artifact["byte_count"],
            source_snapshot=self.snapshot,
            submission_provenance=self.submission_provenance,
            atomic_source_check=lambda _connection: self.snapshot_sha256,
        )

    def _claim(self, *, worker_id: str = "tea-worker") -> dict:
        record = self.store.claim_next_queued_work(worker_id=worker_id)
        self.assertIsNotNone(record)
        self.assertEqual("technoeconomic", record["workflow"])
        return record

    @staticmethod
    def _runner_kwargs(record: dict) -> dict:
        return {
            "source_snapshot_sha256": record["source_snapshot_sha256"],
            "submission_provenance": record["submission_provenance"],
            "submission_provenance_sha256": record[
                "submission_provenance_sha256"
            ],
            "source_annual_job_id": record["source_annual_job_id"],
            "source_artifact_storage_key": record[
                "source_artifact_storage_key"
            ],
            "source_artifact_sha256": record["source_artifact_sha256"],
            "source_artifact_bytes": record["source_artifact_bytes"],
            "worker_id": record["worker_id"],
            "lease_token": record["lease_token"],
        }

    def _run(self, record: dict, *, snapshot: dict | None = None) -> None:
        run_technoeconomic._run_technoeconomic_job(
            record["id"],
            record["request"],
            snapshot if snapshot is not None else record["source_snapshot"],
            **self._runner_kwargs(record),
        )

    def test_success_uses_frozen_inputs_and_seals_every_realization(self) -> None:
        record = self._claim()
        observed_stages: list[str] = []
        update_job = self.store.update_technoeconomic_job

        def capture_stages(job_id: str, **kwargs):
            stage = kwargs.get("stage")
            if isinstance(stage, str):
                observed_stages.append(stage)
            return update_job(job_id, **kwargs)

        with patch.object(
            self.store,
            "get_job",
            side_effect=AssertionError("worker must not read the live Annual job"),
        ), patch.object(
            self.store,
            "update_technoeconomic_job",
            side_effect=capture_stages,
        ):
            self._run(record)

        completed = self.store.get_technoeconomic_job(self.job_id)
        self.assertEqual("done", completed["state"])
        self.assertEqual(100.0, completed["progress"])
        self.assertNotIn("realization_table", completed["result"])
        self.assertNotIn("sampled_inputs", completed["result"])
        self.assertEqual(
            run_technoeconomic.kernel.LEGACY_CALCULATION_CONTRACT_VERSION,
            completed["result"]["calculation_contract_version"],
        )
        self.assertEqual(
            self.snapshot_sha256,
            completed["result"]["source_snapshot_sha256"],
        )
        self.assertEqual(
            "frozen_annual_module_dc_stc_wdc",
            completed["result"]["capacity_basis"],
        )
        self.assertNotIn(self.job_id, state.JOBS)

        artifact = completed["artifacts"]["sealed_calculation"]
        payload_path = self.output / Path(artifact["storage_key"])
        self.assertTrue(payload_path.is_file())
        self.assertEqual(8, artifact["row_count"])
        self.assertEqual(
            artifact["sha256"],
            hashlib.sha256(payload_path.read_bytes()).hexdigest(),
        )
        with np.load(payload_path, allow_pickle=False) as payload:
            metadata = json.loads(
                payload["metadata_json_utf8"].tobytes().decode("utf-8")
            )
            self.assertEqual(8, len(payload["realization_0000"]))
        self.assertEqual(self.snapshot_sha256, metadata["source_snapshot_sha256"])
        cdf = next(iter(completed["result"]["summaries"].values()))["cdf"]
        self.assertEqual("sealed_calculation_payload", cdf["storage"])
        self.assertNotIn("values", cdf)

        exports = completed["artifacts"]["exports"]
        self.assertEqual(
            {
                "csv_bundle",
                "xlsx_workbook",
                "cdf_plot",
                "sensitivity_plot",
                "convergence_plot",
            },
            set(exports["artifacts"]),
        )
        manifest_payload = deepcopy(exports)
        manifest_sha256 = manifest_payload.pop("manifest_sha256")
        self.assertEqual(
            manifest_sha256,
            hashlib.sha256(
                run_technoeconomic._canonical_json_text(manifest_payload).encode(
                    "utf-8"
                )
            ).hexdigest(),
        )
        for export in exports["artifacts"].values():
            export_path = self.output / Path(export["storage_key"])
            self.assertTrue(export_path.is_file())
            self.assertEqual(export["byte_count"], export_path.stat().st_size)
            self.assertEqual(
                export["sha256"],
                hashlib.sha256(export_path.read_bytes()).hexdigest(),
            )
        public_exports = completed["result"]["exports"]
        self.assertNotIn("storage_key", json.dumps(public_exports, sort_keys=True))
        self.assertEqual(
            exports["manifest_sha256"],
            completed["result_provenance"]["exports"]["manifest_sha256"],
        )
        for expected_stage in (
            "Sealing the private calculation payload",
            "Generating CSV, workbook, and diagnostic plots",
            "Verifying the immutable export manifest",
            "Finalizing technoeconomic results",
        ):
            self.assertIn(expected_stage, observed_stages)

    def test_v2_routine_result_separates_installed_and_applied_capacities(self) -> None:
        snapshot = deepcopy(self.snapshot)
        snapshot["source_annual_job"] = {
            "request": {
                "curtailment_enabled": True,
                "curtailment_limit_kw": 125.0,
            }
        }
        request_payload = TechnoeconomicSubmissionRequest.model_validate(
            _applied_site_request_payload(
                source_id=self.source_id,
                n=8,
            )
        ).model_dump(mode="json", exclude_none=False)
        request_payload.pop("standalone_commercial", None)
        request_payload.pop("paired_commercial", None)
        request = tea_api.build_technoeconomic_kernel_request(
            request_payload,
            snapshot,
        )
        provenance = tea_api.build_technoeconomic_submission_provenance(
            request_payload,
            {
                "source_snapshot": snapshot,
                "source_snapshot_sha256": tea_api.canonical_json_sha256(snapshot),
            },
            request,
        )
        calculation = run_technoeconomic.kernel.run_technoeconomic(request)
        artifact = {
            "schema_version": 1,
            "artifact_kind": "sealed_technoeconomic_calculation",
            "media_type": "application/x-npz",
            "sha256": "a" * 64,
            "byte_count": 1,
            "row_count": 8,
            "column_count": len(calculation.realization_table),
            "pickle_allowed": False,
            "public": False,
        }

        result = run_technoeconomic._routine_result(
            request,
            calculation,
            artifact,
            provenance,
        )

        self.assertEqual(2, result["schema_version"])
        self.assertEqual(
            "frozen_annual_applied_capacity_w",
            result["capacity_basis"],
        )
        self.assertEqual(
            125_000.0,
            result["applied_capacities"]["solaredge"]["applied_capacity_w"],
        )
        self.assertEqual(
            "ac_operating_limit",
            result["applied_capacities"]["solectria"]["rating_basis"],
        )
        self.assertEqual(
            139_180.8,
            result["capacities"]["solaredge"]["installed_wdc"],
        )

    def test_v3_routine_result_freezes_commercial_scaling_authority(self) -> None:
        snapshot = deepcopy(self.snapshot)
        snapshot["source_annual_job"] = {
            "request": {
                "curtailment_enabled": True,
                "curtailment_limit_kw": 125.0,
            }
        }
        payload = _commercial_scaling_request_payload(
            target_capacity=87.5,
            target_capacity_unit="mw",
            marginal_cost_timing="equivalent_annual",
            marginal_cost_value=625_000.0,
        )
        payload["source_annual_job_id"] = self.source_id
        payload["n"] = 8
        request_payload = TechnoeconomicSubmissionRequest.model_validate(
            payload
        ).model_dump(mode="json", exclude_none=False)
        request_payload.pop("standalone_commercial", None)
        request_payload.pop("paired_commercial", None)
        request = tea_api.build_technoeconomic_kernel_request(
            request_payload,
            snapshot,
        )
        provenance = tea_api.build_technoeconomic_submission_provenance(
            request_payload,
            {
                "source_snapshot": snapshot,
                "source_snapshot_sha256": tea_api.canonical_json_sha256(snapshot),
            },
            request,
        )
        calculation = run_technoeconomic.kernel.run_technoeconomic(request)
        artifact = {
            "schema_version": 1,
            "artifact_kind": "sealed_technoeconomic_calculation",
            "media_type": "application/x-npz",
            "sha256": "a" * 64,
            "byte_count": 1,
            "row_count": 8,
            "column_count": len(calculation.realization_table),
            "pickle_allowed": False,
            "public": False,
        }

        result = run_technoeconomic._routine_result(
            request,
            calculation,
            artifact,
            provenance,
        )

        self.assertEqual(3, result["schema_version"])
        self.assertEqual(
            run_technoeconomic.kernel.COMMERCIAL_SCALING_CALCULATION_CONTRACT_VERSION,
            result["calculation_contract_version"],
        )
        self.assertEqual(
            {
                "target_capacity_w": 87_500_000.0,
                "target_rating_basis": "ac_operating_limit",
                "marginal_cost_input_id": (
                    run_technoeconomic.kernel.COMMERCIAL_MARGINAL_COST_DIFFERENCE_INPUT_ID
                ),
                "marginal_cost_timing": "equivalent_annual",
                "transfer_method": "direct_capacity_scaling",
            },
            result["commercial_scaling"],
        )

    def test_v4_routine_result_exposes_capacity_bridge_percentiles_and_cdf(self) -> None:
        snapshot = deepcopy(self.snapshot)
        snapshot["source_annual_job"] = {
            "request": {
                "curtailment_enabled": True,
                "curtailment_limit_kw": 125.0,
            }
        }
        payload = _standalone_commercial_request_payload(n=16)
        payload["source_annual_job_id"] = self.source_id
        request_payload = TechnoeconomicSubmissionRequest.model_validate(
            payload
        ).model_dump(mode="json", exclude_none=False)
        request_payload.pop("paired_commercial", None)
        request = tea_api.build_technoeconomic_kernel_request(
            request_payload,
            snapshot,
        )
        provenance = tea_api.build_technoeconomic_submission_provenance(
            request_payload,
            {
                "source_snapshot": snapshot,
                "source_snapshot_sha256": tea_api.canonical_json_sha256(snapshot),
            },
            request,
        )
        calculation = run_technoeconomic.kernel.run_technoeconomic(request)
        artifact = {
            "schema_version": 1,
            "artifact_kind": "sealed_technoeconomic_calculation",
            "media_type": "application/x-npz",
            "sha256": "a" * 64,
            "byte_count": 1,
            "row_count": 16,
            "column_count": len(calculation.realization_table),
            "pickle_allowed": False,
            "public": False,
        }

        result = run_technoeconomic._routine_result(
            request,
            calculation,
            artifact,
            provenance,
        )

        self.assertEqual(4, result["schema_version"])
        standalone = result["standalone_commercial"]
        self.assertEqual("solaredge", standalone["technology"])
        self.assertEqual(100_000_000.0, standalone["target_capacity_w"])
        self.assertEqual(125_000.0, standalone["source_applied_capacity_w"])
        self.assertEqual("ac_operating_limit", standalone["target_rating_basis"])
        self.assertEqual("ac_operating_limit", standalone["source_rating_basis"])
        self.assertEqual(800.0, standalone["capacity_scale_factor"])
        self.assertEqual(2026, standalone["constant_dollar_cost_year"])
        self.assertEqual({"p10", "p50", "p90"}, set(standalone["percentiles"]))
        self.assertEqual(3, len(standalone["commercial_cost_line_summaries"]))
        capex_summary = next(
            line
            for line in standalone["commercial_cost_line_summaries"]
            if line["input_id"] == "commercial.solaredge.capex"
        )
        self.assertEqual("full_initial_capex", capex_summary["cost_category"])
        self.assertEqual(
            ["commercial.solaredge.full-initial-system"],
            capex_summary["coverage_ids"],
        )
        self.assertEqual(2026, capex_summary["constant_dollar_cost_year"])
        cdf = standalone["cdf"]
        self.assertEqual(16, cdf["population_count"])
        self.assertEqual(16, cdf["source_point_count"])
        self.assertEqual(16, cdf["display_point_count"])
        self.assertEqual("sealed_calculation_payload", cdf["full_storage"])
        self.assertEqual(64, len(cdf["full_cdf_sha256"]))
        np.testing.assert_array_equal(
            calculation.realization_table[
                run_technoeconomic.kernel.COMMERCIAL_STANDALONE_FIELD_CAPACITY_SCALE_FACTOR
            ],
            np.full(16, 800.0),
        )

    def test_v5_routine_result_exposes_both_commercial_headlines(self) -> None:
        snapshot = deepcopy(self.snapshot)
        snapshot["source_annual_job"] = {
            "request": {
                "curtailment_enabled": True,
                "curtailment_limit_kw": 125.0,
            }
        }
        payload = _paired_commercial_request_payload(n=16)
        payload["source_annual_job_id"] = self.source_id
        request_payload = TechnoeconomicSubmissionRequest.model_validate(
            payload
        ).model_dump(mode="json", exclude_none=False)
        request = tea_api.build_technoeconomic_kernel_request(
            request_payload,
            snapshot,
        )
        provenance = tea_api.build_technoeconomic_submission_provenance(
            request_payload,
            {
                "source_snapshot": snapshot,
                "source_snapshot_sha256": tea_api.canonical_json_sha256(snapshot),
            },
            request,
        )
        calculation = run_technoeconomic.kernel.run_technoeconomic(request)
        artifact = {
            "schema_version": 1,
            "artifact_kind": "sealed_technoeconomic_calculation",
            "media_type": "application/x-npz",
            "sha256": "a" * 64,
            "byte_count": 1,
            "row_count": 16,
            "column_count": len(calculation.realization_table),
            "pickle_allowed": False,
            "public": False,
        }

        result = run_technoeconomic._routine_result(
            request,
            calculation,
            artifact,
            provenance,
        )

        self.assertEqual(5, result["schema_version"])
        paired = result["paired_commercial"]
        self.assertEqual(100_000_000.0, paired["target_capacity_w"])
        self.assertEqual("ac_operating_limit", paired["target_rating_basis"])
        self.assertEqual("direct_capacity_scaling", paired["transfer_method"])
        self.assertEqual(2026, paired["constant_dollar_cost_year"])
        self.assertEqual({"solectria", "solaredge"}, set(paired["systems"]))
        for technology in ("solectria", "solaredge"):
            system = paired["systems"][technology]
            self.assertEqual(125_000.0, system["source_applied_capacity_w"])
            self.assertEqual("ac_operating_limit", system["source_rating_basis"])
            self.assertEqual(800.0, system["capacity_scale_factor"])
            self.assertEqual({"p10", "p50", "p90"}, set(system["percentiles"]))
            self.assertEqual(16, system["cdf"]["population_count"])
            self.assertEqual(16, system["cdf"]["source_point_count"])
            self.assertEqual(3, len(system["commercial_cost_line_summaries"]))
            self.assertEqual(
                {technology},
                {
                    line["technology"]
                    for line in system["commercial_cost_line_summaries"]
                },
            )
        delta = paired["lcoe_delta_se_minus_sol"]
        self.assertEqual(
            run_technoeconomic.kernel.COMMERCIAL_PAIRED_FIELD_LCOE_DELTA,
            delta["headline_metric_id"],
        )
        self.assertEqual({"p10", "p50", "p90"}, set(delta["percentiles"]))
        self.assertEqual(16, delta["cdf"]["population_count"])
        for field_name in (
            run_technoeconomic.kernel.COMMERCIAL_PAIRED_SOLECTRIA_FIELD_CAPACITY_SCALE_FACTOR,
            run_technoeconomic.kernel.COMMERCIAL_STANDALONE_FIELD_CAPACITY_SCALE_FACTOR,
        ):
            np.testing.assert_array_equal(
                calculation.realization_table[field_name],
                np.full(16, 800.0),
            )

        point_count = 1_500
        full_summary = {
            "cdf": {
                "values": list(range(point_count)),
                "cumulative_count": list(range(1, point_count + 1)),
                "cumulative_probability": [
                    (index + 1) / point_count for index in range(point_count)
                ],
                "population_count": point_count,
            }
        }
        capped = run_technoeconomic._headline_cdf_display(full_summary)
        self.assertLessEqual(capped["display_point_count"], 1_200)
        self.assertEqual(point_count, capped["source_point_count"])
        self.assertEqual(0, capped["values"][0])
        self.assertEqual(point_count - 1, capped["values"][-1])
        self.assertEqual(capped, run_technoeconomic._headline_cdf_display(full_summary))

    def test_v2_retry_replays_frozen_request_through_complete_worker(self) -> None:
        self.store.cancel_technoeconomic_job(self.job_id)
        snapshot = deepcopy(self.snapshot)
        snapshot["source_annual_job"] = {
            "request": {
                "curtailment_enabled": True,
                "curtailment_limit_kw": 125.0,
            }
        }
        snapshot_sha256 = tea_api.canonical_json_sha256(snapshot)
        request_payload = TechnoeconomicSubmissionRequest.model_validate(
            _applied_site_request_payload(source_id=self.source_id, n=8)
        ).model_dump(mode="json", exclude_none=False)
        request_payload.pop("commercial_scaling", None)
        request_payload.pop("standalone_commercial", None)
        request_payload.pop("paired_commercial", None)
        kernel_request = tea_api.build_technoeconomic_kernel_request(
            request_payload,
            snapshot,
        )
        provenance = tea_api.build_technoeconomic_submission_provenance(
            request_payload,
            {
                "source_snapshot": snapshot,
                "source_snapshot_sha256": snapshot_sha256,
            },
            kernel_request,
        )
        original_id = "tea_worker_v2_original"
        artifact = self.source_artifact
        self.store.create_technoeconomic_job(
            job_id=original_id,
            request=request_payload,
            source_annual_job_id=self.source_id,
            source_artifact_storage_key=artifact["storage_key"],
            source_artifact_sha256=artifact["sha256"],
            source_artifact_bytes=artifact["byte_count"],
            source_snapshot=snapshot,
            submission_provenance=provenance,
            atomic_source_check=lambda _connection: snapshot_sha256,
        )
        self.store.cancel_technoeconomic_job(original_id)
        retried = self.store.retry_technoeconomic_job(
            original_id,
            new_job_id="tea_worker_v2_retry",
        )
        self.assertEqual(original_id, retried["retry_of_job_id"])

        record = self._claim()
        self._run(record)

        completed = self.store.get_technoeconomic_job(record["id"])
        self.assertEqual("done", completed["state"])
        self.assertEqual(2, completed["result"]["schema_version"])
        self.assertEqual(
            "tea-calculation-v2",
            completed["result"]["calculation_contract_version"],
        )
        self.assertEqual(
            125_000.0,
            completed["result"]["applied_capacities"]["solectria"][
                "applied_capacity_w"
            ],
        )
        self.assertEqual(request_payload, completed["request"])
        self.assertEqual(provenance, completed["submission_provenance"])

    def test_v3_retry_replays_frozen_commercial_job_through_exports(self) -> None:
        self.store.cancel_technoeconomic_job(self.job_id)
        snapshot = deepcopy(self.snapshot)
        snapshot["eligible_paired_energy_rows"] = [
            {
                "year": 2024,
                "period_start": "2024-01-01",
                "period_end": "2024-12-31",
                "sol_predicted_kwh": 172_263.0,
                "se_predicted_kwh": 174_227.0,
            }
        ]
        snapshot["source_annual_job"] = {
            "request": {
                "curtailment_enabled": True,
                "curtailment_limit_kw": 125.0,
            }
        }
        snapshot_sha256 = tea_api.canonical_json_sha256(snapshot)
        payload = _commercial_scaling_request_payload(
            target_capacity=100.0,
            target_capacity_unit="mw",
            marginal_cost_timing="lifecycle_present_value",
            marginal_cost_value=-2_500_000.0,
        )
        payload["source_annual_job_id"] = self.source_id
        payload["n"] = 8
        request_payload = TechnoeconomicSubmissionRequest.model_validate(
            payload
        ).model_dump(mode="json", exclude_none=False)
        request_payload.pop("standalone_commercial", None)
        request_payload.pop("paired_commercial", None)
        request_sha256 = tea_api.canonical_json_sha256(request_payload)
        kernel_request = tea_api.build_technoeconomic_kernel_request(
            request_payload,
            snapshot,
        )
        kernel_request_sha256 = tea_api.canonical_json_sha256(
            run_technoeconomic.kernel.canonical_request_payload(kernel_request)
        )
        provenance = tea_api.build_technoeconomic_submission_provenance(
            request_payload,
            {
                "source_snapshot": snapshot,
                "source_snapshot_sha256": snapshot_sha256,
            },
            kernel_request,
        )
        provenance_sha256 = tea_api.canonical_json_sha256(provenance)
        self.assertEqual(request_sha256, provenance["request_sha256"])
        self.assertEqual(
            kernel_request_sha256,
            provenance["validated_kernel_request_sha256"],
        )

        original_id = "tea_worker_v3_original"
        artifact = self.source_artifact
        original = self.store.create_technoeconomic_job(
            job_id=original_id,
            request=request_payload,
            source_annual_job_id=self.source_id,
            source_artifact_storage_key=artifact["storage_key"],
            source_artifact_sha256=artifact["sha256"],
            source_artifact_bytes=artifact["byte_count"],
            source_snapshot=snapshot,
            submission_provenance=provenance,
            atomic_source_check=lambda _connection: snapshot_sha256,
        )
        self.assertEqual(provenance_sha256, original["submission_provenance_sha256"])
        self.store.cancel_technoeconomic_job(original_id)
        retried = self.store.retry_technoeconomic_job(
            original_id,
            new_job_id="tea_worker_v3_retry",
        )

        self.assertEqual(original_id, retried["retry_of_job_id"])
        self.assertEqual(request_payload, retried["request"])
        self.assertEqual(snapshot, retried["source_snapshot"])
        self.assertEqual(snapshot_sha256, retried["source_snapshot_sha256"])
        self.assertEqual(provenance, retried["submission_provenance"])
        self.assertEqual(
            provenance_sha256,
            retried["submission_provenance_sha256"],
        )

        record = self._claim()
        with patch.object(
            self.store,
            "get_job",
            side_effect=AssertionError("worker must use the frozen Annual snapshot"),
        ):
            self._run(record)

        completed = self.store.get_technoeconomic_job(record["id"])
        self.assertEqual("done", completed["state"])
        self.assertEqual(100.0, completed["progress"])
        self.assertEqual(original_id, completed["retry_of_job_id"])
        self.assertEqual(request_payload, completed["request"])
        self.assertEqual(provenance, completed["submission_provenance"])
        self.assertEqual(3, completed["result"]["schema_version"])
        self.assertEqual(
            run_technoeconomic.kernel.COMMERCIAL_SCALING_CALCULATION_CONTRACT_VERSION,
            completed["result"]["calculation_contract_version"],
        )
        self.assertEqual(
            {
                "target_capacity_w": 100_000_000.0,
                "target_rating_basis": "ac_operating_limit",
                "marginal_cost_input_id": (
                    run_technoeconomic.kernel.COMMERCIAL_MARGINAL_COST_DIFFERENCE_INPUT_ID
                ),
                "marginal_cost_timing": "lifecycle_present_value",
                "transfer_method": "direct_capacity_scaling",
            },
            completed["result"]["commercial_scaling"],
        )

        sealed = completed["artifacts"]["sealed_calculation"]
        sealed_path = self.output / Path(sealed["storage_key"])
        with np.load(sealed_path, allow_pickle=False) as sealed_payload:
            metadata = json.loads(
                sealed_payload["metadata_json_utf8"].tobytes().decode("utf-8")
            )
            column_storage = {
                item["column_name"]: item["storage_name"]
                for item in metadata["realization_column_storage"]
            }
            commercial_year1_energy = sealed_payload[
                column_storage[
                    run_technoeconomic.kernel.COMMERCIAL_FIELD_YEAR1_DELTA_ENERGY
                ]
            ]
        self.assertEqual(request_sha256, metadata["request_sha256"])
        self.assertEqual(snapshot_sha256, metadata["source_snapshot_sha256"])
        self.assertEqual(
            provenance_sha256,
            metadata["submission_provenance_sha256"],
        )
        np.testing.assert_allclose(commercial_year1_energy, 1_571_200.0)

        exports = completed["artifacts"]["exports"]
        self.assertEqual(
            run_technoeconomic.technoeconomic_reporting.COMMERCIAL_SCALING_EXPORT_MANIFEST_SCHEMA_VERSION,
            exports["schema_version"],
        )
        self.assertEqual("passed", exports["tie_outs"]["status"])
        self.assertEqual(request_sha256, exports["request_sha256"])
        self.assertEqual(snapshot_sha256, exports["source_snapshot_sha256"])
        self.assertEqual(
            provenance_sha256,
            exports["submission_provenance_sha256"],
        )
        self.assertEqual(
            exports["manifest_sha256"],
            completed["result_provenance"]["exports"]["manifest_sha256"],
        )
        for exported in exports["artifacts"].values():
            export_path = self.output / Path(exported["storage_key"])
            self.assertTrue(export_path.is_file())
            self.assertEqual(
                exported["sha256"],
                hashlib.sha256(export_path.read_bytes()).hexdigest(),
            )

        frozen_original = self.store.get_technoeconomic_job(original_id)
        self.assertEqual("cancelled", frozen_original["state"])
        self.assertEqual(request_payload, frozen_original["request"])
        self.assertEqual(provenance, frozen_original["submission_provenance"])

    def test_snapshot_digest_tampering_fails_before_calculation(self) -> None:
        record = self._claim()
        tampered = deepcopy(record["source_snapshot"])
        tampered["eligible_paired_energy_rows"][0]["se_predicted_kwh"] = 999_999.0
        with patch.object(
            run_technoeconomic.kernel,
            "run_technoeconomic",
        ) as calculation:
            self._run(record, snapshot=tampered)
        calculation.assert_not_called()
        failed = self.store.get_technoeconomic_job(self.job_id)
        self.assertEqual("error", failed["state"])
        self.assertNotIn(str(self.output), failed["error"])

    def test_forged_evidence_receipt_with_new_outer_hash_fails_closed(self) -> None:
        record = self._claim()
        forged = deepcopy(record["submission_provenance"])
        forged["evidence_receipt"]["subject_count"] += 1
        forged["evidence_receipt_sha256"] = tea_api.canonical_json_sha256(
            forged["evidence_receipt"]
        )
        forged["validation_receipts_sha256"] = tea_api.canonical_json_sha256(
            {
                "normalization": forged["normalization_receipt"],
                "overlap": forged["overlap_receipt"],
                "evidence": forged["evidence_receipt"],
                "commercial_transfer": forged[
                    "commercial_transfer_receipt"
                ],
            }
        )
        record["submission_provenance"] = forged
        record["submission_provenance_sha256"] = (
            tea_api.canonical_json_sha256(forged)
        )

        with patch.object(
            run_technoeconomic.kernel,
            "run_technoeconomic",
        ) as calculation:
            self._run(record)

        calculation.assert_not_called()
        failed = self.store.get_technoeconomic_job(self.job_id)
        self.assertEqual("error", failed["state"])
        self.assertIsNone(failed["result"])
        self.assertIsNone(failed["artifacts"])

    def test_immutable_source_byte_tampering_fails_closed(self) -> None:
        record = self._claim()
        self.source_artifact_path.write_bytes(b"tampered")
        with patch.object(
            run_technoeconomic.kernel,
            "run_technoeconomic",
        ) as calculation:
            self._run(record)
        calculation.assert_not_called()
        self.assertEqual(
            "error",
            self.store.get_technoeconomic_job(self.job_id)["state"],
        )

    def test_cancellation_before_calculation_is_terminal_and_clean(self) -> None:
        record = self._claim()
        self.store.cancel_technoeconomic_job(self.job_id)
        with patch.object(
            run_technoeconomic.kernel,
            "run_technoeconomic",
        ) as calculation:
            self._run(record)
        calculation.assert_not_called()
        cancelled = self.store.get_technoeconomic_job(self.job_id)
        self.assertEqual("cancelled", cancelled["state"])
        self.assertIsNone(cancelled["artifacts"])

    def test_mid_calculation_cancellation_uses_kernel_hook(self) -> None:
        record = self._claim()

        def cancel_during_run(_request, *, progress_cb, cancel_check):
            progress_cb(0.25, "Synthetic calculation checkpoint")
            self.store.cancel_technoeconomic_job(self.job_id)
            cancel_check()
            self.fail("cancel_check must raise")

        with patch.object(
            run_technoeconomic.kernel,
            "run_technoeconomic",
            side_effect=cancel_during_run,
        ):
            self._run(record)
        cancelled = self.store.get_technoeconomic_job(self.job_id)
        self.assertEqual("cancelled", cancelled["state"])
        self.assertGreater(cancelled["progress"], 20)

    def test_cancellation_before_atomic_publish_leaves_no_sealed_artifact(self) -> None:
        record = self._claim()
        write_payload = run_technoeconomic._write_sealed_calculation_payload

        def cancel_at_publish(*args, publish_check, **kwargs):
            def request_cancel_then_check() -> None:
                self.store.cancel_technoeconomic_job(self.job_id)
                publish_check()

            return write_payload(
                *args,
                publish_check=request_cancel_then_check,
                **kwargs,
            )

        with patch.object(
            run_technoeconomic,
            "_write_sealed_calculation_payload",
            side_effect=cancel_at_publish,
        ):
            self._run(record)

        cancelled = self.store.get_technoeconomic_job(self.job_id)
        self.assertEqual("cancelled", cancelled["state"])
        self.assertIsNone(cancelled["result"])
        self.assertIsNone(cancelled["artifacts"])
        self.assertEqual(
            [],
            list(
                self.output.rglob(
                    run_technoeconomic.SEALED_CALCULATION_FILENAME
                )
            ),
        )
        self.assertFalse(
            (
                self.output
                / ".technoeconomic_attempts"
                / self.job_id
                / record["lease_token"]
            ).exists()
        )

    def test_sealed_payload_tampering_between_check_and_rename_fails_cleanly(
        self,
    ) -> None:
        record = self._claim()
        write_payload = run_technoeconomic._write_sealed_calculation_payload

        def tamper_at_publish(*args, publish_check, **kwargs):
            def check_then_tamper() -> None:
                publish_check()
                pending = (
                    self.output
                    / ".technoeconomic_attempts"
                    / self.job_id
                    / record["lease_token"]
                    / ".pending.npz"
                )
                with pending.open("ab") as handle:
                    handle.write(b"tampered-after-prepublication-hash")

            return write_payload(
                *args,
                publish_check=check_then_tamper,
                **kwargs,
            )

        with patch.object(
            run_technoeconomic,
            "_write_sealed_calculation_payload",
            side_effect=tamper_at_publish,
        ):
            self._run(record)

        failed = self.store.get_technoeconomic_job(self.job_id)
        self.assertEqual("error", failed["state"])
        self.assertIsNone(failed["result"])
        self.assertIsNone(failed["artifacts"])
        self.assertEqual([], list(self.output.rglob("*.npz")))

    def test_cancellation_during_streaming_export_generation_cleans_attempt(
        self,
    ) -> None:
        record = self._claim()

        def cancel_while_streaming(**kwargs):
            kwargs["cancellation_check"]()
            self.store.cancel_technoeconomic_job(self.job_id)
            kwargs["cancellation_check"]()
            self.fail("the credentialed cancellation check must raise")

        with patch.object(
            run_technoeconomic.technoeconomic_reporting,
            "generate_technoeconomic_exports",
            side_effect=cancel_while_streaming,
        ):
            self._run(record)

        cancelled = self.store.get_technoeconomic_job(self.job_id)
        self.assertEqual("cancelled", cancelled["state"])
        self.assertIsNone(cancelled["result"])
        self.assertIsNone(cancelled["artifacts"])
        self.assertFalse(
            (
                self.output
                / ".technoeconomic_attempts"
                / self.job_id
                / record["lease_token"]
            ).exists()
        )

    def test_cancellation_before_later_export_rename_removes_earlier_exports(
        self,
    ) -> None:
        record = self._claim()
        generate_exports = (
            run_technoeconomic.technoeconomic_reporting.generate_technoeconomic_exports
        )
        publication_checks = 0

        def cancel_later(**kwargs):
            original_publish_check = kwargs["publish_check"]

            def cancel_before_third_rename() -> None:
                nonlocal publication_checks
                publication_checks += 1
                if publication_checks == 3:
                    self.store.cancel_technoeconomic_job(self.job_id)
                original_publish_check()

            kwargs["publish_check"] = cancel_before_third_rename
            return generate_exports(**kwargs)

        with patch.object(
            run_technoeconomic.technoeconomic_reporting,
            "generate_technoeconomic_exports",
            side_effect=cancel_later,
        ):
            self._run(record)

        cancelled = self.store.get_technoeconomic_job(self.job_id)
        self.assertEqual(3, publication_checks)
        self.assertEqual("cancelled", cancelled["state"])
        self.assertIsNone(cancelled["result"])
        self.assertIsNone(cancelled["artifacts"])
        self.assertFalse(
            (
                self.output
                / ".technoeconomic_attempts"
                / self.job_id
                / record["lease_token"]
            ).exists()
        )

    def test_lease_loss_after_an_export_publish_cleans_the_attempt(self) -> None:
        record = self._claim()
        generate_exports = (
            run_technoeconomic.technoeconomic_reporting.generate_technoeconomic_exports
        )
        publication_checks = 0

        def lose_lease_later(**kwargs):
            original_publish_check = kwargs["publish_check"]

            def interrupt_before_second_rename() -> None:
                nonlocal publication_checks
                publication_checks += 1
                if publication_checks == 2:
                    self.store.mark_stale_running_technoeconomic_jobs_interrupted()
                original_publish_check()

            kwargs["publish_check"] = interrupt_before_second_rename
            return generate_exports(**kwargs)

        with patch.object(
            run_technoeconomic.technoeconomic_reporting,
            "generate_technoeconomic_exports",
            side_effect=lose_lease_later,
        ):
            self._run(record)

        interrupted = self.store.get_technoeconomic_job(self.job_id)
        self.assertEqual(2, publication_checks)
        self.assertEqual("interrupted", interrupted["state"])
        self.assertIsNone(interrupted["result"])
        self.assertIsNone(interrupted["artifacts"])
        self.assertFalse(
            (
                self.output
                / ".technoeconomic_attempts"
                / self.job_id
                / record["lease_token"]
            ).exists()
        )

    def test_forged_rehashed_export_provenance_fails_and_cleans_attempt(
        self,
    ) -> None:
        record = self._claim()
        generate_exports = (
            run_technoeconomic.technoeconomic_reporting.generate_technoeconomic_exports
        )

        def forge_manifest(**kwargs):
            manifest = generate_exports(**kwargs)
            manifest["source_snapshot_sha256"] = "0" * 64
            digest_payload = deepcopy(manifest)
            digest_payload.pop("manifest_sha256", None)
            manifest["manifest_sha256"] = hashlib.sha256(
                run_technoeconomic._canonical_json_text(digest_payload).encode("utf-8")
            ).hexdigest()
            return manifest

        with patch.object(
            run_technoeconomic.technoeconomic_reporting,
            "generate_technoeconomic_exports",
            side_effect=forge_manifest,
        ):
            self._run(record)

        failed = self.store.get_technoeconomic_job(self.job_id)
        self.assertEqual("error", failed["state"])
        self.assertIsNone(failed["result"])
        self.assertIsNone(failed["artifacts"])
        self.assertFalse(
            (
                self.output
                / ".technoeconomic_attempts"
                / self.job_id
                / record["lease_token"]
            ).exists()
        )

    def test_export_file_tampering_before_terminal_publication_fails_cleanly(
        self,
    ) -> None:
        record = self._claim()
        generate_exports = (
            run_technoeconomic.technoeconomic_reporting.generate_technoeconomic_exports
        )

        def tamper_with_published_export(**kwargs):
            manifest = generate_exports(**kwargs)
            csv_entry = manifest["artifacts"]["csv_bundle"]
            csv_path = self.output / Path(csv_entry["storage_key"])
            with csv_path.open("ab") as handle:
                handle.write(b"tampered-before-terminal-publication")
            return manifest

        with patch.object(
            run_technoeconomic.technoeconomic_reporting,
            "generate_technoeconomic_exports",
            side_effect=tamper_with_published_export,
        ):
            self._run(record)

        failed = self.store.get_technoeconomic_job(self.job_id)
        self.assertEqual("error", failed["state"])
        self.assertIsNone(failed["result"])
        self.assertIsNone(failed["artifacts"])
        self.assertFalse(
            (
                self.output
                / ".technoeconomic_attempts"
                / self.job_id
                / record["lease_token"]
            ).exists()
        )

    def test_sealed_payload_tampering_after_export_generation_fails_cleanly(
        self,
    ) -> None:
        record = self._claim()
        generate_exports = (
            run_technoeconomic.technoeconomic_reporting.generate_technoeconomic_exports
        )

        def tamper_with_sealed_payload(**kwargs):
            manifest = generate_exports(**kwargs)
            with kwargs["sealed_calculation_path"].open("ab") as handle:
                handle.write(b"tampered-after-export-generation")
            return manifest

        with patch.object(
            run_technoeconomic.technoeconomic_reporting,
            "generate_technoeconomic_exports",
            side_effect=tamper_with_sealed_payload,
        ):
            self._run(record)

        failed = self.store.get_technoeconomic_job(self.job_id)
        self.assertEqual("error", failed["state"])
        self.assertIsNone(failed["result"])
        self.assertIsNone(failed["artifacts"])
        self.assertFalse(
            (
                self.output
                / ".technoeconomic_attempts"
                / self.job_id
                / record["lease_token"]
            ).exists()
        )

    def test_cancellation_wins_the_final_done_transition_and_cleans_artifact(
        self,
    ) -> None:
        record = self._claim()
        update_job = self.store.update_technoeconomic_job
        cancellation_injected = False

        def cancel_immediately_before_done(job_id: str, **kwargs):
            nonlocal cancellation_injected
            if kwargs.get("state") == "done" and not cancellation_injected:
                cancellation_injected = True
                self.store.cancel_technoeconomic_job(job_id)
            return update_job(job_id, **kwargs)

        with patch.object(
            self.store,
            "update_technoeconomic_job",
            side_effect=cancel_immediately_before_done,
        ):
            self._run(record)

        terminal = self.store.get_technoeconomic_job(self.job_id)
        self.assertTrue(cancellation_injected)
        self.assertEqual("cancelled", terminal["state"])
        self.assertIsNone(terminal["result"])
        self.assertIsNone(terminal["result_provenance"])
        self.assertIsNone(terminal["artifacts"])
        self.assertEqual(
            [],
            list(
                self.output.rglob(
                    run_technoeconomic.SEALED_CALCULATION_FILENAME
                )
            ),
        )
        self.assertFalse(
            (
                self.output
                / ".technoeconomic_attempts"
                / self.job_id
                / record["lease_token"]
            ).exists()
        )

    def test_lease_loss_prevents_publication(self) -> None:
        record = self._claim()

        def lose_lease(_request, *, progress_cb, cancel_check):
            progress_cb(0.1, "Before lease loss")
            self.store.mark_stale_running_technoeconomic_jobs_interrupted()
            cancel_check()
            self.fail("lost lease must raise")

        with patch.object(
            run_technoeconomic.kernel,
            "run_technoeconomic",
            side_effect=lose_lease,
        ):
            self._run(record)
        interrupted = self.store.get_technoeconomic_job(self.job_id)
        self.assertEqual("interrupted", interrupted["state"])
        self.assertIsNone(interrupted["result"])
        self.assertIsNone(interrupted["artifacts"])

    def test_deleted_interrupted_row_is_treated_as_lost_lease(self) -> None:
        record = self._claim()
        self.store.mark_stale_running_technoeconomic_jobs_interrupted()
        self.store.delete_technoeconomic_job(self.job_id)

        with patch.object(
            run_technoeconomic.kernel,
            "run_technoeconomic",
        ) as calculation:
            self._run(record)

        calculation.assert_not_called()
        self.assertIsNone(self.store.get_technoeconomic_job(self.job_id))

    def test_explicit_dispatch_rejects_unknown_work(self) -> None:
        with (
            patch.object(worker_loop, "_dispatch_model_job") as model_dispatch,
            patch.object(
                worker_loop.run_technoeconomic,
                "_run_technoeconomic_job",
            ) as tea_dispatch,
        ):
            worker_loop._dispatch_claimed_work(
                {"workflow": "model"},
                job_id="model-fixture",
                lease_token="lease",
            )
            model_dispatch.assert_called_once()
            with self.assertRaises(ValueError):
                worker_loop._dispatch_claimed_work(
                    {"workflow": "unknown"},
                    job_id="unknown-fixture",
                    lease_token="lease",
                )
            tea_dispatch.assert_not_called()

        with self.assertRaises(ValueError):
            worker_loop._dispatch_model_job(
                {"mode": "unknown"},
                job_id="model-fixture",
                lease_token="lease",
            )

    def test_worker_loop_does_not_cache_technoeconomic_claims(self) -> None:
        record = self._claim(worker_id=config.SERVER_SESSION_ID)

        def dispatch_and_stop(*_args, **_kwargs):
            state._WORKER_STOP.set()

        with (
            patch.object(
                self.store,
                "claim_next_queued_work",
                return_value=record,
            ),
            patch.object(
                worker_loop,
                "_mark_stale_running_work_interrupted",
                return_value={"model": 0, "technoeconomic": 0},
            ),
            patch.object(
                worker_loop,
                "_dispatch_claimed_work",
                side_effect=dispatch_and_stop,
            ) as dispatch,
            patch.object(worker_loop, "_cache_job_record") as cache,
        ):
            worker_loop._model_worker_loop()
        dispatch.assert_called_once()
        cache.assert_not_called()

    def test_technoeconomic_heartbeat_uses_dedicated_store_method(self) -> None:
        stop = threading.Event()
        fake_store = Mock()
        fake_store.heartbeat_technoeconomic_job.return_value = False
        with (
            patch.object(state, "AGENT_STORE", fake_store),
            patch.object(config, "JOB_HEARTBEAT_SECONDS", 0.001),
        ):
            worker_loop._heartbeat_technoeconomic_job("tea_x", "lease", stop)
        fake_store.heartbeat_technoeconomic_job.assert_called_once_with(
            "tea_x",
            worker_id=config.SERVER_SESSION_ID,
            lease_token="lease",
        )

    def test_stale_recovery_uses_one_cutoff_for_both_workflows(self) -> None:
        before = datetime(2026, 8, 13, tzinfo=timezone.utc)
        fake_store = Mock()
        fake_store.mark_stale_running_jobs_interrupted.return_value = 1
        fake_store.mark_stale_running_technoeconomic_jobs_interrupted.return_value = 2
        with patch.object(state, "AGENT_STORE", fake_store):
            counts = worker_loop._mark_stale_running_work_interrupted(before=before)
        self.assertEqual({"model": 1, "technoeconomic": 2}, counts)
        fake_store.mark_stale_running_jobs_interrupted.assert_called_once_with(
            before=before
        )
        fake_store.mark_stale_running_technoeconomic_jobs_interrupted.assert_called_once_with(
            before=before
        )


if __name__ == "__main__":
    unittest.main()
