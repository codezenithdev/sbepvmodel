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
from sbepv.store import AgentStore
from sbepv.worker import loop as worker_loop
from sbepv.worker import run_technoeconomic
from tests.test_technoeconomic_api import _site_request_payload


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
        with patch.object(
            self.store,
            "get_job",
            side_effect=AssertionError("worker must not read the live Annual job"),
        ):
            self._run(record)

        completed = self.store.get_technoeconomic_job(self.job_id)
        self.assertEqual("done", completed["state"])
        self.assertEqual(100.0, completed["progress"])
        self.assertNotIn("realization_table", completed["result"])
        self.assertNotIn("sampled_inputs", completed["result"])
        self.assertEqual(
            run_technoeconomic.kernel.CALCULATION_CONTRACT_VERSION,
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
