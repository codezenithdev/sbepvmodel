from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

from sbepv.api import baselines, job_store, state
from sbepv.api import main as app
from sbepv.store import AgentStore
from sbepv.worker import completion


class TechnoeconomicCrossWorkflowIsolationTests(unittest.TestCase):
    """TEA identifiers cannot cross legacy model-job compatibility paths."""

    def setUp(self) -> None:
        handle = tempfile.NamedTemporaryFile(
            prefix="technoeconomic-isolation-test-",
            suffix=".sqlite3",
            dir=Path(__file__).resolve().parent,
            delete=False,
        )
        handle.close()
        self.db_path = Path(handle.name)
        self.addCleanup(self._remove_database_files, self.db_path)

        self.original_store = state.AGENT_STORE
        state.AGENT_STORE = AgentStore(self.db_path)
        self.addCleanup(setattr, state, "AGENT_STORE", self.original_store)
        state.JOBS.clear()
        self.addCleanup(state.JOBS.clear)

        self.annual = self._completed_annual_source()
        source_snapshot = {
            "schema_version": 1,
            "source_annual_job_id": self.annual["id"],
            "midc_source_artifact": {
                "owner_annual_job_id": self.annual["id"],
                "storage_key": "sha256/11/" + "1" * 64 + ".csv",
                "sha256": "1" * 64,
                "byte_count": 123,
            },
            "energy_rows": [
                {
                    "weather_year": 2024,
                    "solectria_kwh": 1000.0,
                    "solaredge_kwh": 1010.0,
                }
            ],
        }
        snapshot_text = json.dumps(
            source_snapshot,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        snapshot_hash = hashlib.sha256(snapshot_text.encode("utf-8")).hexdigest()
        self.tea = state.AGENT_STORE.create_technoeconomic_job(
            job_id="tea_isolation_probe",
            request={"n": 20, "seed": 42, "project_life_years": 20},
            source_annual_job_id=self.annual["id"],
            source_artifact_storage_key=(
                "sha256/11/" + "1" * 64 + ".csv"
            ),
            source_artifact_sha256="1" * 64,
            source_artifact_bytes=123,
            source_snapshot=source_snapshot,
            submission_provenance={
                "schema_version": 1,
                "analysis_basis": "solartac_site",
            },
            atomic_source_check=lambda _connection: snapshot_hash,
        )
        # Simulate the exact legacy-cache collision that structural isolation
        # must withstand.  Durable TEA workers must never use this cache.
        state.JOBS[self.tea["id"]] = {
            "state": "done",
            "kind": "baseline",
            "mode": "annual",
            "progress": 100,
            "stage": "Done",
            "request": {"mode": "annual"},
            "result": {"stats": {"excel": "tea-must-not-be-model.xlsx"}},
        }

    @staticmethod
    def _remove_database_files(path: Path) -> None:
        for candidate in (path, Path(f"{path}-wal"), Path(f"{path}-shm")):
            candidate.unlink(missing_ok=True)

    def _completed_annual_source(self) -> dict:
        created = state.AGENT_STORE.create_job(
            job_id="annual-source-for-tea-isolation",
            kind="manual",
            mode="annual",
            request={"mode": "annual", "years": [2024]},
            source_path="artifacts/annual-source/midc.csv",
            source_hash="1" * 64,
        )
        claimed = state.AGENT_STORE.claim_next_queued_job(
            worker_id="annual-source-worker"
        )
        self.assertEqual(created["id"], claimed["id"])
        return state.AGENT_STORE.update_job(
            created["id"],
            expected_worker_id="annual-source-worker",
            expected_lease_token=claimed["lease_token"],
            state="done",
            progress=100,
            stage="Done",
            result={
                "annual_energy_kwh": 1000.0,
                "annual_source_artifact": {
                    "owner_annual_job_id": created["id"],
                    "storage_key": "sha256/11/" + "1" * 64 + ".csv",
                    "sha256": "1" * 64,
                    "byte_count": 123,
                    "immutable": True,
                },
            },
        )

    def assert_http_status(self, expected: int, operation) -> None:
        with self.assertRaises(HTTPException) as raised:
            operation()
        self.assertEqual(expected, raised.exception.status_code)

    def test_tea_cache_entry_is_invisible_to_generic_status(self) -> None:
        self.assertIsNone(job_store._get_job_record(self.tea["id"]))
        self.assert_http_status(404, lambda: app.status(self.tea["id"]))

    def test_tea_cache_entry_is_invisible_to_model_baseline_selection(self) -> None:
        self.assertIsNone(baselines._selected_baseline("annual"))

        state.JOBS[self.tea["id"]]["state"] = "running"
        self.assertNotIn(
            self.tea["id"],
            {job["id"] for job in baselines._active_model_jobs()},
        )

    def test_model_status_hides_private_source_storage_key(self) -> None:
        payload = json.loads(app.status(self.annual["id"]).body)
        artifact = payload["result"]["annual_source_artifact"]
        self.assertNotIn("storage_key", artifact)
        self.assertEqual("1" * 64, artifact["sha256"])
        self.assertEqual(123, artifact["byte_count"])
        self.assertIs(artifact["immutable"], True)

    def test_tea_and_cache_only_rows_are_ineligible_for_model_promotion(self) -> None:
        state.JOBS["cache-only-model"] = {
            "state": "done",
            "kind": "baseline",
            "mode": "annual",
            "result": {"stats": {}},
        }
        for job_id in (self.tea["id"], "cache-only-model"):
            with self.subTest(job_id=job_id):
                self.assert_http_status(
                    404,
                    lambda job_id=job_id: app.promote_model_job(job_id),
                )

        self.assertIsNone(state.AGENT_STORE.get_current_baseline("annual"))

    def test_tea_result_is_ineligible_for_generic_saved_results(self) -> None:
        self.assert_http_status(404, lambda: app.save_result(self.tea["id"]))
        self.assert_http_status(
            404,
            lambda: app.remove_saved_result(self.tea["id"]),
        )
        self.assertEqual([], state.AGENT_STORE.list_saved_results())
        saved_payload = json.loads(app.list_saved_results().body)
        self.assertNotIn(self.tea["id"], json.dumps(saved_payload))

    def test_generic_model_mutations_cannot_target_tea(self) -> None:
        before = state.AGENT_STORE.get_technoeconomic_job(self.tea["id"])
        for operation in (
            lambda: app.cancel_model_job(self.tea["id"]),
            lambda: app.retry_model_job(self.tea["id"]),
            lambda: app.delete_model_job(self.tea["id"]),
        ):
            with self.subTest(operation=operation):
                self.assert_http_status(404, operation)
                self.assertEqual(
                    before,
                    state.AGENT_STORE.get_technoeconomic_job(self.tea["id"]),
                )
        self.assertIn(self.tea["id"], state.JOBS)

    def test_tea_is_absent_from_generic_agent_history(self) -> None:
        payload = json.loads(app.agent_state().body)
        self.assertNotIn(self.tea["id"], json.dumps(payload))

    def test_model_completion_rejects_tea_even_when_cache_looks_complete(self) -> None:
        with patch.object(completion, "generate_comparison_artifacts") as generate:
            with self.assertRaisesRegex(ValueError, "durable model job"):
                completion._finish_model_job(
                    self.tea["id"],
                    {"stats": {"excel": "tea-must-not-be-model.xlsx"}},
                )
        generate.assert_not_called()
        self.assertEqual(
            "queued",
            state.AGENT_STORE.get_technoeconomic_job(self.tea["id"])["state"],
        )

    def test_comparison_rejects_cache_only_baseline(self) -> None:
        # The legacy model-only claim API intentionally yields while older TEA
        # work is queued, so remove that unrelated queue item for this test.
        state.AGENT_STORE.cancel_technoeconomic_job(self.tea["id"])
        candidate = state.AGENT_STORE.create_job(
            job_id="durable-comparison-candidate",
            kind="candidate",
            mode="annual",
            baseline_id="cache-only-comparison-baseline",
            request={"mode": "annual", "years": [2024]},
        )
        claimed = state.AGENT_STORE.claim_next_queued_job(
            worker_id="comparison-worker"
        )
        self.assertEqual(candidate["id"], claimed["id"])
        state.JOBS["cache-only-comparison-baseline"] = {
            "state": "done",
            "kind": "baseline",
            "mode": "annual",
            "request": {"mode": "annual", "years": [2024]},
            "result": {"stats": {"excel": "fake-baseline.xlsx"}},
        }

        with patch.object(completion, "generate_comparison_artifacts") as generate:
            with self.assertRaisesRegex(ValueError, "bound baseline"):
                completion._finish_model_job(
                    candidate["id"],
                    {"stats": {"excel": "candidate.xlsx"}},
                    worker_id="comparison-worker",
                    lease_token=claimed["lease_token"],
                )
        generate.assert_not_called()
        durable = state.AGENT_STORE.get_job(candidate["id"])
        self.assertEqual("running", durable["state"])
        self.assertIsNone(durable["comparison"])

    def test_comparison_rejects_tea_id_as_bound_baseline(self) -> None:
        state.AGENT_STORE.cancel_technoeconomic_job(self.tea["id"])
        candidate = state.AGENT_STORE.create_job(
            job_id="candidate-with-adversarial-tea-baseline",
            kind="candidate",
            mode="annual",
            baseline_id="placeholder-model-baseline",
            request={"mode": "annual", "years": [2024]},
        )
        claimed = state.AGENT_STORE.claim_next_queued_job(
            worker_id="adversarial-comparison-worker"
        )
        self.assertEqual(candidate["id"], claimed["id"])

        # Current SQLite triggers reject this state at write time.  Supply the
        # equivalent legacy row at the read boundary to prove the completion
        # publisher independently rejects it too.
        legacy_candidate = dict(state.AGENT_STORE.get_job(candidate["id"]))
        legacy_candidate["baseline_id"] = self.tea["id"]
        durable_lookup = job_store._get_durable_model_job_record

        def resolve_legacy_model(job_id: str):
            if job_id == candidate["id"]:
                return legacy_candidate
            return durable_lookup(job_id)

        with (
            patch.object(
                job_store,
                "_get_durable_model_job_record",
                side_effect=resolve_legacy_model,
            ),
            patch.object(completion, "generate_comparison_artifacts") as generate,
        ):
            with self.assertRaisesRegex(ValueError, "bound baseline"):
                completion._finish_model_job(
                    candidate["id"],
                    {"stats": {"excel": "candidate.xlsx"}},
                    worker_id="adversarial-comparison-worker",
                    lease_token=claimed["lease_token"],
                )
        generate.assert_not_called()
        self.assertIsNone(state.AGENT_STORE.get_job(self.tea["id"]))
        self.assertEqual(
            "cancelled",
            state.AGENT_STORE.get_technoeconomic_job(self.tea["id"])["state"],
        )


if __name__ == "__main__":
    unittest.main()
