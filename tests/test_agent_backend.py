from __future__ import annotations

import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

import app
from agent_store import AgentStore, LeaseOwnershipLost
from scenario_reporting import sha256_file


class SemiAutomaticAgentBackendTests(unittest.TestCase):
    """Focused contract tests for the application-controlled scenario loop."""

    def setUp(self) -> None:
        handle = tempfile.NamedTemporaryFile(
            prefix="agent-backend-test-",
            suffix=".sqlite3",
            dir=Path(__file__).resolve().parent,
            delete=False,
        )
        handle.close()
        self.db_path = Path(handle.name)
        self.root = Path(__file__).resolve().parent
        self.addCleanup(self._remove_database_files, self.db_path)
        self.generated_files: list[Path] = []
        self.addCleanup(self._remove_generated_files)

        self.original_store = app.AGENT_STORE
        app.AGENT_STORE = AgentStore(self.db_path)
        self.addCleanup(setattr, app, "AGENT_STORE", self.original_store)

        app.JOBS.clear()
        self.addCleanup(app.JOBS.clear)
        self.environment = patch.dict(
            os.environ,
            {"OPENAI_API_KEY": "unit-test-placeholder"},
        )
        self.environment.start()
        self.addCleanup(self.environment.stop)

    @staticmethod
    def _remove_database_files(path: Path) -> None:
        for candidate in (path, Path(f"{path}-wal"), Path(f"{path}-shm")):
            candidate.unlink(missing_ok=True)

    def _remove_generated_files(self) -> None:
        for candidate in self.generated_files:
            candidate.unlink(missing_ok=True)

    @staticmethod
    def tool_arguments(**overrides):
        arguments = {field: None for field in app.SCENARIO_OVERRIDE_FIELDS}
        arguments.update(overrides)
        return arguments

    @staticmethod
    def validation_config(**overrides):
        values = {
            "from_date": "2026-06-20",
            "from_time": "08:00",
            "to_date": "2026-06-21",
            "to_time": "18:00",
            "interval_value": 1,
            "interval_unit": "hours",
            "backtrack": True,
            "solaredge_inverter_efficiency": 1.0,
            "solaredge_bos_efficiency": 1.0,
            "solectria_inverter_efficiency": 1.0,
            "solectria_bos_efficiency": 1.0,
            "iam_model": "physical",
            "iam_a_r": None,
            "curtailment_enabled": False,
            "curtailment_limit_kw": None,
        }
        values.update(overrides)
        return values

    def completed_baseline(
        self,
        *,
        job_id: str = "baseline-validation",
        mode: str = "validation",
        request: dict | None = None,
        reviewed: bool | None = None,
    ) -> dict:
        if request is None:
            request = self.validation_config()
        if reviewed is None:
            reviewed = mode == "validation"
        _, canonical = app._canonical_request(mode, request)

        source_handle = tempfile.NamedTemporaryFile(
            prefix=f"{job_id}-",
            suffix=".csv",
            dir=self.root,
            delete=False,
        )
        source_handle.close()
        source = Path(source_handle.name)
        self.generated_files.append(source)
        source.write_text(
            "timestamp,solaredge_measured_power,solectria_measured_power,dni,ghi,dhi,temp_air,wind_speed\n"
            "2026-06-20 14:00:00,1000,900,700,500,100,25,2\n",
            encoding="utf-8",
        )
        source_hash = sha256_file(source)
        provenance = (
            {
                "data_quality": {
                    "review_id": f"review-{job_id}",
                    "reviewed_source_sha256": source_hash,
                    "reviewed_at": "2026-07-28T12:00:00+00:00",
                    "report": {"issues": []},
                    "cleaning": {"decisions": []},
                }
            }
            if reviewed and mode == "validation"
            else None
        )
        calibration_factors = {
            "method": "measured_energy_divided_by_uncalibrated_modeled_energy",
            "seasons": [
                {
                    "season": season,
                    "systems": {
                        "solaredge": {
                            "factor": 1.1234567890123,
                            "source": "season",
                        },
                        "solectria": {
                            "factor": 0.9876543210987,
                            "source": "season",
                        },
                    },
                }
                for season in ("winter", "spring", "summer", "fall")
            ],
        }
        result = {"mode": mode, "stats": {}}
        if mode == "validation":
            result.update(
                {
                    "calibration_factors": calibration_factors,
                    "factor_driver_diagnostics": {
                        "method": "baseline diagnostics",
                        "systems": {},
                    },
                }
            )
        created = app.AGENT_STORE.create_job(
            job_id=job_id,
            kind="baseline",
            mode=mode,
            request=canonical,
            provenance=provenance,
        )
        claimed = app.AGENT_STORE.claim_next_queued_job()
        self.assertEqual(created["id"], claimed["id"])
        completed = app.AGENT_STORE.update_job(
            job_id,
            state="done",
            progress=100,
            stage="Done",
            source_path=str(source.resolve()),
            source_hash=source_hash,
            result=result,
            artifacts={},
        )
        app.AGENT_STORE.promote_job(job_id)
        return completed

    def completed_physics_baseline(self, *, job_id: str) -> dict:
        _, canonical = app._canonical_request(
            "validation",
            self.validation_config(calibrate_model=False),
        )
        source = self.root / f"{job_id}.csv"
        self.generated_files.append(source)
        source.write_text(
            "timestamp,solaredge_measured_power,solectria_measured_power,dni,ghi,dhi,temp_air,wind_speed\n"
            "2026-06-20 14:00:00,1000,900,700,500,100,25,2\n",
            encoding="utf-8",
        )
        source_hash = sha256_file(source)
        created = app.AGENT_STORE.create_job(
            job_id=job_id,
            kind="baseline",
            mode="validation",
            request=canonical,
        )
        claimed = app.AGENT_STORE.claim_next_queued_job()
        self.assertEqual(created["id"], claimed["id"])
        return app.AGENT_STORE.update_job(
            job_id,
            state="done",
            source_path=str(source.resolve()),
            source_hash=source_hash,
            result={
                "mode": "validation",
                "stats": {"calibration_enabled": False},
            },
        )

    @staticmethod
    def annual_calibration_provenance(calibration_baseline: dict) -> dict:
        profile = {
            "schema_version": app.CALIBRATION_PROFILE_SCHEMA_VERSION,
            "origin_job_id": calibration_baseline["id"],
            "origin_source_sha256": calibration_baseline["source_hash"],
            "origin_review_id": f"review-{calibration_baseline['id']}",
            "seasonal_factors": {
                season: {"solaredge": 1.02, "solectria": 0.98}
                for season in ("winter", "spring", "summer", "fall")
            },
            "fit_metadata": {"method": "unit-test-reviewed-fit"},
            "factor_driver_diagnostics": {"systems": {}},
        }
        profile_sha256 = app._json_sha256(profile)
        return {
            "calibration_profile": profile,
            "calibration_application": {
                "baseline_job_id": calibration_baseline["id"],
                "baseline_review_id": f"review-{calibration_baseline['id']}",
                "origin_profile_sha256": profile_sha256,
                "resolved_profile_sha256": profile_sha256,
                "origin_profile": profile,
                "resolved_profile": profile,
                "required_seasons": ["summer"],
                "seasonal_substitution": None,
                "server_confirmation": None,
                "settings_deltas": [],
            },
        }

    def test_delete_scenario_endpoint_removes_record_and_output_files(self) -> None:
        job_id = "candidate-delete"
        job = app.AGENT_STORE.create_job(
            job_id=job_id,
            kind="candidate",
            mode="validation",
            baseline_id="baseline-validation",
            request=self.validation_config(),
        )
        app.AGENT_STORE.claim_next_queued_job()

        files = []
        for suffix in (".csv", ".xlsx", "_comparison.png"):
            handle = tempfile.NamedTemporaryFile(
                prefix=f"{job_id}_", suffix=suffix, dir=self.root, delete=False
            )
            handle.close()
            path = Path(handle.name)
            path.write_text("generated", encoding="utf-8")
            files.append(path)
            self.generated_files.append(path)
        source, workbook, comparison = files
        app.AGENT_STORE.update_job(
            job_id,
            state="done",
            source_path=str(source),
            result={"excel": f"/outputs/{workbook.name}"},
            artifacts={"comparison": {"path": str(comparison)}},
        )
        with patch.object(app, "OUTPUT_DIR", self.root):
            response = app.delete_model_job(job_id)

        self.assertEqual(200, response.status_code)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertTrue(payload["deleted"])
        self.assertEqual(3, payload["artifacts_deleted"])
        self.assertIsNone(app.AGENT_STORE.get_job(job_id))
        self.assertFalse(source.exists())
        self.assertFalse(workbook.exists())
        self.assertFalse(comparison.exists())

    def test_expired_runner_stops_before_mutating_reclaimed_job(self) -> None:
        _, canonical = app._canonical_request(
            "validation", self.validation_config(calibrate_model=False)
        )
        app.AGENT_STORE.create_job(
            job_id="lease-race",
            kind="manual",
            mode="validation",
            request=canonical,
        )
        first = app.AGENT_STORE.claim_next_queued_job(
            worker_id=app.SERVER_SESSION_ID
        )
        first_token = first["lease_token"]
        app.AGENT_STORE.mark_stale_running_jobs_interrupted()
        app.AGENT_STORE.retry_job("lease-race")
        second = app.AGENT_STORE.claim_next_queued_job(
            worker_id=app.SERVER_SESSION_ID
        )
        app._cache_job_record(second)

        with (
            patch.object(app.historian, "run_historian") as historian_call,
            patch.object(app.model, "run_model") as model_call,
        ):
            app._run_job(
                "lease-race",
                app.RunRequest(**canonical),
                worker_id=app.SERVER_SESSION_ID,
                lease_token=first_token,
            )

        historian_call.assert_not_called()
        model_call.assert_not_called()
        current = app.AGENT_STORE.get_job("lease-race")
        self.assertEqual("running", current["state"])
        self.assertEqual(second["lease_token"], current["lease_token"])
        self.assertEqual(0, current["progress"])
        self.assertEqual(0, app.JOBS["lease-race"]["progress"])

    def test_owned_attempt_uses_lease_token_specific_output_prefix(self) -> None:
        _, canonical = app._canonical_request(
            "validation", self.validation_config(calibrate_model=False)
        )
        source = self.root / "lease-output-source.csv"
        source.write_text(
            "timestamp,dni,ghi,dhi,temp_air,wind_speed\n"
            "2026-06-20 14:00:00,700,500,100,25,2\n",
            encoding="utf-8",
        )
        self.generated_files.append(source)
        source_hash = sha256_file(source)
        app.AGENT_STORE.create_job(
            job_id="lease-output",
            kind="manual",
            mode="validation",
            request=canonical,
            source_path=str(source.resolve()),
            source_hash=source_hash,
        )
        claimed = app.AGENT_STORE.claim_next_queued_job(worker_id="worker-a")

        with (
            patch.object(app, "_render_input_data_plots", return_value={}),
            patch.object(
                app.model,
                "run_model",
                return_value={
                    "ac_png": str(self.root / "lease-output-ac.png"),
                    "energy_png": str(self.root / "lease-output-energy.png"),
                    "excel": str(self.root / "lease-output.xlsx"),
                },
            ) as model_call,
            patch.object(app, "_finish_model_job") as finish_call,
        ):
            app._run_job(
                "lease-output",
                app.RunRequest(**canonical),
                source_path=str(source.resolve()),
                expected_source_hash=source_hash,
                worker_id="worker-a",
                lease_token=claimed["lease_token"],
            )

        expected_prefix = app._job_attempt_prefix(
            "lease-output", claimed["lease_token"]
        )
        self.assertEqual(
            expected_prefix,
            Path(model_call.call_args.kwargs["output_base"]).name,
        )
        self.assertEqual("worker-a", finish_call.call_args.kwargs["worker_id"])
        self.assertEqual(
            claimed["lease_token"], finish_call.call_args.kwargs["lease_token"]
        )

    def test_delete_removes_artifacts_from_every_lease_attempt(self) -> None:
        job_id = "candidate-attempt-cleanup"
        app.AGENT_STORE.create_job(
            job_id=job_id,
            kind="candidate",
            mode="validation",
            baseline_id="baseline-validation",
            request=self.validation_config(),
        )
        first = app.AGENT_STORE.claim_next_queued_job(worker_id="worker-a")
        first_prefix = app._job_attempt_prefix(job_id, first["lease_token"])
        stale_artifact = self.root / f"{first_prefix}_stale.xlsx"
        stale_artifact.write_text("stale attempt", encoding="utf-8")
        self.generated_files.append(stale_artifact)

        app.AGENT_STORE.mark_stale_running_jobs_interrupted()
        app.AGENT_STORE.retry_job(job_id)
        second = app.AGENT_STORE.claim_next_queued_job(worker_id="worker-a")
        second_prefix = app._job_attempt_prefix(job_id, second["lease_token"])
        accepted_artifact = self.root / f"{second_prefix}.xlsx"
        accepted_artifact.write_text("accepted attempt", encoding="utf-8")
        self.generated_files.append(accepted_artifact)
        self.assertNotEqual(first_prefix, second_prefix)
        app.AGENT_STORE.update_job(
            job_id,
            expected_worker_id="worker-a",
            expected_lease_token=second["lease_token"],
            state="done",
            result={"excel": f"/outputs/{accepted_artifact.name}"},
        )

        with patch.object(app, "OUTPUT_DIR", self.root):
            response = app.delete_model_job(job_id)

        self.assertEqual(200, response.status_code)
        self.assertFalse(stale_artifact.exists())
        self.assertFalse(accepted_artifact.exists())

    def test_lost_attempt_cleanup_preserves_source_reused_by_retry(self) -> None:
        job_id = "attempt-source-reuse"
        app.AGENT_STORE.create_job(
            job_id=job_id,
            kind="manual",
            mode="validation",
            request=self.validation_config(),
        )
        first = app.AGENT_STORE.claim_next_queued_job(worker_id="worker-a")
        first_prefix = app._job_attempt_prefix(job_id, first["lease_token"])
        source = self.root / f"{first_prefix}.csv"
        stale_plot = self.root / f"{first_prefix}_ac.png"
        source.write_text("timestamp,dni\n2026-06-20,700\n", encoding="utf-8")
        stale_plot.write_text("stale plot", encoding="utf-8")
        self.generated_files.extend([source, stale_plot])
        app.AGENT_STORE.update_job(
            job_id,
            expected_worker_id="worker-a",
            expected_lease_token=first["lease_token"],
            source_path=str(source.resolve()),
            source_hash=sha256_file(source),
        )

        app.AGENT_STORE.mark_stale_running_jobs_interrupted()
        app.AGENT_STORE.retry_job(job_id)
        app.AGENT_STORE.claim_next_queued_job(worker_id="worker-a")
        with patch.object(app, "OUTPUT_DIR", self.root):
            removed = app._delete_job_attempt_artifacts(
                job_id, first["lease_token"]
            )

        self.assertEqual(1, removed)
        self.assertTrue(source.exists())
        self.assertFalse(stale_plot.exists())

    def test_delete_same_input_scenario_preserves_baseline_source(self) -> None:
        baseline = self.completed_physics_baseline(job_id="baseline-shared-source")
        baseline_source = Path(baseline["source_path"])
        baseline_hash = str(baseline["source_hash"])
        candidate_id = "candidate-shared-source"
        workbook = self.root / f"{candidate_id}.xlsx"
        workbook.write_text("candidate workbook", encoding="utf-8")
        self.generated_files.append(workbook)

        app.AGENT_STORE.create_job(
            job_id=candidate_id,
            kind="candidate",
            mode="validation",
            baseline_id=baseline["id"],
            request=self.validation_config(calibrate_model=False),
            source_path=str(baseline_source),
            source_hash=baseline_hash,
        )
        claimed = app.AGENT_STORE.claim_next_queued_job()
        self.assertEqual(candidate_id, claimed["id"])
        app.AGENT_STORE.update_job(
            candidate_id,
            state="done",
            result={
                "source_csv": f"/outputs/{baseline_source.name}",
                "excel": f"/outputs/{workbook.name}",
            },
            artifacts={"model_workbook": {"path": str(workbook)}},
        )

        with patch.object(app, "OUTPUT_DIR", self.root):
            response = app.delete_model_job(candidate_id)

        self.assertEqual(200, response.status_code)
        self.assertIsNone(app.AGENT_STORE.get_job(candidate_id))
        self.assertFalse(workbook.exists())
        self.assertTrue(baseline_source.exists())
        self.assertEqual(baseline_hash, sha256_file(baseline_source))
        verified_path, verified_hash = app._verified_baseline_source(
            app.AGENT_STORE.get_job(baseline["id"])
        )
        self.assertEqual(str(baseline_source.resolve()), verified_path)
        self.assertEqual(baseline_hash, verified_hash)

    def test_chat_fallback_prefers_promoted_baseline_over_newer_scenario(self) -> None:
        baseline = self.completed_physics_baseline(job_id="promoted-chat-baseline")
        app.AGENT_STORE.promote_job(baseline["id"])
        candidate = app.AGENT_STORE.create_job(
            job_id="newer-unpromoted-scenario",
            kind="candidate",
            mode="validation",
            baseline_id=baseline["id"],
            request=self.validation_config(calibrate_model=False),
            source_path=baseline["source_path"],
            source_hash=baseline["source_hash"],
        )
        claimed = app.AGENT_STORE.claim_next_queued_job()
        self.assertEqual(candidate["id"], claimed["id"])
        app.AGENT_STORE.update_job(
            candidate["id"],
            state="done",
            result={"mode": "validation", "stats": {"calibration_enabled": False}},
        )

        resolved_job_id, context = app._chat_run_context(None, "validation")

        self.assertEqual(baseline["id"], resolved_job_id)
        self.assertEqual(baseline["id"], context["job_id"])

    def test_numeric_iam_is_clarified_without_openai_or_state_change(self) -> None:
        fake_openai = types.ModuleType("openai")

        def forbidden_client():
            self.fail("ambiguous IAM must be rejected before calling OpenAI")

        fake_openai.OpenAI = forbidden_client
        with patch.dict(sys.modules, {"openai": fake_openai}):
            response = app._openai_agent_response(
                app.ChatRequest(
                    message="Run a comparison with IAM at .80",
                    active_mode="validation",
                    current_config=self.validation_config(),
                )
            )

        self.assertIsNone(response["action"])
        self.assertFalse(response["web_search_enabled"])
        self.assertIn("Martin-Ruiz", response["reply"])
        self.assertIn("`a_r`", response["reply"])
        self.assertEqual(app.AGENT_STORE.list_proposals(), [])
        self.assertEqual(app.AGENT_STORE.list_jobs(), [])

    def test_iam_dates_years_and_percentages_are_not_numeric_iam_values(self) -> None:
        self.assertFalse(app._ambiguous_numeric_iam("Explain IAM results for 2026."))
        self.assertFalse(
            app._ambiguous_numeric_iam("Compare IAM on 2026-06-20 at 97% efficiency.")
        )
        self.assertTrue(app._ambiguous_numeric_iam("Set IAM to 0.8 and run it."))

    def test_visible_physics_run_is_used_instead_of_older_promoted_calibration(self) -> None:
        self.completed_baseline(job_id="older-calibrated")
        physics = self.completed_physics_baseline(job_id="visible-physics")

        _, action = app._handle_scenario_tool(
            app.ChatRequest(
                message="Run this physics model with backtracking off.",
                job_id=physics["id"],
                active_mode="validation",
                current_config=physics["request"],
            ),
            self.tool_arguments(backtrack=False),
        )

        candidate = app.AGENT_STORE.get_job(action["job"]["job_id"])
        self.assertEqual("visible-physics", candidate["baseline_id"])
        self.assertFalse(candidate["request"]["calibrate_model"])
        self.assertIsNone(
            (candidate.get("provenance") or {}).get("calibration_profile")
        )

    def test_physics_baseline_can_be_promoted_without_calibration_review(self) -> None:
        physics = self.completed_physics_baseline(job_id="physics-promote")

        response = app.promote_model_job(physics["id"])

        self.assertEqual(200, response.status_code)
        self.assertEqual(
            physics["id"],
            app.AGENT_STORE.get_current_baseline("validation")["job_id"],
        )

    def test_physics_worker_passes_exact_request_boundaries_to_model(self) -> None:
        physics = self.completed_physics_baseline(job_id="physics-boundaries")
        proposal = app._create_candidate_proposal(
            mode="validation",
            baseline=physics,
            candidate={**physics["request"], "backtrack": False},
            changes=[
                {
                    "field": "backtrack",
                    "label": "Backtracking",
                    "from": True,
                    "to": False,
                }
            ],
        )
        candidate = app._confirm_durable_proposal(proposal, automatic=True)
        claimed = app.AGENT_STORE.claim_next_queued_job()
        self.assertEqual(candidate["id"], claimed["id"])

        with (
            patch.object(app, "_render_input_data_plots", return_value={}),
            patch.object(
                app.model,
                "run_model",
                return_value={
                    "ac_png": str(self.root / "physics_ac.png"),
                    "energy_png": str(self.root / "physics_energy.png"),
                    "excel": str(self.root / "physics.xlsx"),
                },
            ) as model_call,
            patch.object(app, "_finish_model_job"),
        ):
            request = app.RunRequest(**candidate["request"])
            app._run_job(
                candidate["id"],
                request,
                source_path=candidate["source_path"],
                expected_source_hash=candidate["source_hash"],
            )

        self.assertEqual(
            app._iso(request.from_date, request.from_time),
            model_call.call_args.kwargs["requested_start"],
        )
        self.assertEqual(
            app._iso(request.to_date, request.to_time),
            model_call.call_args.kwargs["requested_end"],
        )

    def test_multiple_model_actions_are_rejected_without_mutating_state(self) -> None:
        baseline = self.completed_baseline()
        calls = [
            {
                "type": "function_call",
                "name": "propose_model_scenario",
                "call_id": f"call-{index}",
                "arguments": json.dumps(self.tool_arguments(backtrack=False)),
            }
            for index in (1, 2)
        ]
        api_calls = []
        constructor_calls = []

        def create_response(**kwargs):
            api_calls.append(kwargs)
            return types.SimpleNamespace(output=calls, output_text="")

        fake_client = types.SimpleNamespace(
            responses=types.SimpleNamespace(create=create_response)
        )
        fake_openai = types.ModuleType("openai")
        fake_openai.OpenAI = lambda **kwargs: (
            constructor_calls.append(kwargs) or fake_client
        )

        with patch.dict(sys.modules, {"openai": fake_openai}):
            result = app._openai_agent_response(
                app.ChatRequest(
                    message="Run one scenario.",
                    job_id=baseline["id"],
                    active_mode="validation",
                    current_config=baseline["request"],
                )
            )

        self.assertIn("did not start", result["reply"])
        self.assertIsNone(result["action"])
        self.assertEqual([], app.AGENT_STORE.list_jobs(kind="candidate"))
        self.assertEqual([], app.AGENT_STORE.list_proposals())
        self.assertEqual(app.OPENAI_TIMEOUT_SECONDS, constructor_calls[0]["timeout"])
        self.assertEqual(app.OPENAI_MAX_RETRIES, constructor_calls[0]["max_retries"])
        self.assertEqual(1, api_calls[0]["max_tool_calls"])
        self.assertFalse(api_calls[0]["parallel_tool_calls"])

    def test_run_ranges_and_active_queue_are_bounded(self) -> None:
        with self.assertRaises(HTTPException) as validation_error:
            app._validate_run_request(
                app.RunRequest(
                    from_date="2020-01-01",
                    to_date="2022-01-01",
                    calibrate_model=False,
                )
            )
        self.assertEqual(422, validation_error.exception.status_code)

        with self.assertRaises(HTTPException) as annual_error:
            app._annual_dates(
                app.AnnualRunRequest(
                    from_date="2000-01-01",
                    to_date="2020-01-01",
                )
            )
        self.assertEqual(422, annual_error.exception.status_code)

        with patch.object(app, "MAX_ACTIVE_MODEL_JOBS", 1):
            app._enqueue_baseline_job(
                "validation",
                self.validation_config(calibrate_model=False),
                job_id="queue-first",
            )
            with self.assertRaises(HTTPException) as queue_error:
                app._enqueue_baseline_job(
                    "validation",
                    self.validation_config(calibrate_model=False),
                    job_id="queue-overflow",
                )
        self.assertEqual(429, queue_error.exception.status_code)
        self.assertIsNone(app.AGENT_STORE.get_job("queue-overflow"))

    def test_strict_tool_schema_and_single_step_deterministic_action_response(self) -> None:
        baseline = self.completed_baseline()
        call = {
            "type": "function_call",
            "name": "propose_model_scenario",
            "call_id": "call-scenario-1",
            "arguments": json.dumps(self.tool_arguments(backtrack=False)),
        }
        responses = [types.SimpleNamespace(output=[call], output_text="")]
        api_calls = []

        def create_response(**kwargs):
            api_calls.append(kwargs)
            return responses.pop(0)

        fake_client = types.SimpleNamespace(
            responses=types.SimpleNamespace(create=create_response)
        )
        fake_openai = types.ModuleType("openai")
        fake_openai.OpenAI = lambda: fake_client

        with patch.dict(sys.modules, {"openai": fake_openai}):
            result = app._openai_agent_response(
                app.ChatRequest(
                    message="Run the same data with backtracking disabled.",
                    job_id=baseline["id"],
                    active_mode="validation",
                    current_config=self.validation_config(),
                )
            )

        schema = app.SCENARIO_TOOL["parameters"]
        self.assertTrue(app.SCENARIO_TOOL["strict"])
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(set(schema["required"]), set(app.SCENARIO_OVERRIDE_FIELDS))
        self.assertEqual(set(schema["properties"]), set(app.SCENARIO_OVERRIDE_FIELDS))

        self.assertEqual(len(api_calls), 1)
        self.assertIn(app.SCENARIO_TOOL, api_calls[0]["tools"])
        self.assertIn("queued automatically", result["reply"])
        self.assertIn("same interval and source data", result["reply"])
        self.assertEqual(result["action"]["type"], "job_started")
        candidate = app.AGENT_STORE.get_job(result["action"]["job"]["job_id"])
        self.assertEqual(candidate["baseline_id"], baseline["id"])
        self.assertEqual(candidate["request"]["backtrack"], False)

    def test_iam_ar_sweep_queues_exact_controlled_values(self) -> None:
        baseline = self.completed_baseline()

        with patch.object(
            app.AGENT_STORE,
            "confirm_proposals_batch",
            wraps=app.AGENT_STORE.confirm_proposals_batch,
        ) as batch_confirm:
            tool_result, action = app._handle_iam_ar_sweep_tool(
                app.ChatRequest(
                    message=(
                        "Run the model with different iam a_r values from 0.1 to "
                        "0.5 with an increment of 0.1 and show me the comparison."
                    ),
                    job_id=baseline["id"],
                    active_mode="validation",
                    current_config=self.validation_config(),
                ),
                {
                    "mode": None,
                    "start_a_r": 0.1,
                    "stop_a_r": 0.5,
                    "increment": 0.1,
                },
            )

        self.assertEqual("batch_started", tool_result["status"])
        self.assertEqual("job_batch_started", action["type"])
        batch_confirm.assert_called_once()
        self.assertEqual(5, len(batch_confirm.call_args.args[0]))
        self.assertEqual([0.1, 0.2, 0.3, 0.4, 0.5], action["sweep"]["values"])
        self.assertEqual(5, len(action["jobs"]))
        jobs = sorted(
            (app.AGENT_STORE.get_job(item["job_id"]) for item in action["jobs"]),
            key=lambda item: item["provenance"]["scenario_sweep"]["index"],
        )
        self.assertEqual(
            [0.1, 0.2, 0.3, 0.4, 0.5],
            [job["request"]["iam_a_r"] for job in jobs],
        )
        for index, job in enumerate(jobs):
            self.assertEqual("martin_ruiz", job["request"]["iam_model"])
            self.assertEqual(baseline["id"], job["baseline_id"])
            self.assertEqual(baseline["source_path"], job["source_path"])
            self.assertEqual(baseline["source_hash"], job["source_hash"])
            self.assertEqual(
                action["sweep"]["sweep_id"],
                job["provenance"]["scenario_sweep"]["sweep_id"],
            )
            self.assertEqual(index, job["provenance"]["scenario_sweep"]["index"])
            self.assertEqual(
                f"review-{baseline['id']}",
                job["provenance"]["data_quality"]["review_id"],
            )
            self.assertEqual(
                baseline["id"],
                job["provenance"]["calibration_profile"]["origin_job_id"],
            )

    def test_iam_ar_sweep_tool_dispatches_once_through_openai_loop(self) -> None:
        baseline = self.completed_baseline()
        call = {
            "type": "function_call",
            "name": "run_model_parameter_sweep",
            "call_id": "call-sweep-1",
            "arguments": json.dumps(
                {
                    "mode": None,
                    "parameter": "iam_a_r",
                    "start": 0.1,
                    "stop": 0.5,
                    "increment": 0.1,
                }
            ),
        }
        responses = [types.SimpleNamespace(output=[call], output_text="")]
        api_calls = []

        def create_response(**kwargs):
            api_calls.append(kwargs)
            return responses.pop(0)

        fake_client = types.SimpleNamespace(
            responses=types.SimpleNamespace(create=create_response)
        )
        fake_openai = types.ModuleType("openai")
        fake_openai.OpenAI = lambda: fake_client

        with patch.dict(sys.modules, {"openai": fake_openai}):
            result = app._openai_agent_response(
                app.ChatRequest(
                    message=(
                        "Run the model with iam a_r from 0.1 to 0.5 by 0.1 "
                        "and compare them."
                    ),
                    job_id=baseline["id"],
                    active_mode="validation",
                    current_config=self.validation_config(),
                )
            )

        schema = app.PARAMETER_SWEEP_TOOL["parameters"]
        self.assertTrue(app.PARAMETER_SWEEP_TOOL["strict"])
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(set(app.PARAMETER_SWEEP_FIELDS), set(schema["required"]))
        self.assertEqual(
            set(app.SWEEPABLE_PARAMETER_CONFIG),
            set(schema["properties"]["parameter"]["enum"]),
        )
        self.assertIn(app.PARAMETER_SWEEP_TOOL, api_calls[0]["tools"])
        self.assertEqual(1, len(api_calls))
        self.assertIn("Queued 5 controlled Martin-Ruiz a_r scenario runs", result["reply"])
        self.assertIn("hash-verified baseline source", result["reply"])
        self.assertEqual("job_batch_started", result["action"]["type"])
        self.assertEqual(5, len(result["action"]["jobs"]))

    def test_efficiency_sweep_changes_only_selected_numeric_parameter(self) -> None:
        baseline = self.completed_baseline()

        _, action = app._handle_parameter_sweep_tool(
            app.ChatRequest(
                message=(
                    "Compare SolarEdge inverter efficiency from 0.96 to 1.0 "
                    "with an increment of 0.01."
                ),
                job_id=baseline["id"],
                active_mode="validation",
                current_config=self.validation_config(),
            ),
            {
                "mode": None,
                "parameter": "solaredge_inverter_efficiency",
                "start": 0.96,
                "stop": 1.0,
                "increment": 0.01,
            },
        )

        self.assertEqual("job_batch_started", action["type"])
        self.assertEqual("SolarEdge inverter efficiency", action["sweep"]["label"])
        self.assertEqual(4, len(action["jobs"]))
        self.assertEqual(4, action["sweep"]["baseline_index"])
        jobs = sorted(
            action["jobs"],
            key=lambda item: item["provenance"]["scenario_sweep"]["index"],
        )
        self.assertEqual(
            [0.96, 0.97, 0.98, 0.99],
            [job["request"]["solaredge_inverter_efficiency"] for job in jobs],
        )
        for job in jobs:
            self.assertEqual("physical", job["request"]["iam_model"])
            self.assertEqual(1.0, job["request"]["solectria_inverter_efficiency"])
            self.assertFalse(job["request"]["curtailment_enabled"])

    def test_curtailment_limit_sweep_enables_curtailment_for_every_value(self) -> None:
        baseline = self.completed_baseline()

        _, action = app._handle_parameter_sweep_tool(
            app.ChatRequest(
                message="Compare curtailment limits from 100 to 125 kW by 25 kW.",
                job_id=baseline["id"],
                active_mode="validation",
                current_config=self.validation_config(),
            ),
            {
                "mode": "validation",
                "parameter": "curtailment_limit_kw",
                "start": 100,
                "stop": 125,
                "increment": 25,
            },
        )

        self.assertEqual("Curtailment limit", action["sweep"]["label"])
        self.assertEqual("kW", action["sweep"]["unit"])
        self.assertEqual(2, len(action["jobs"]))
        self.assertEqual(
            [100.0, 125.0],
            [job["request"]["curtailment_limit_kw"] for job in action["jobs"]],
        )
        self.assertTrue(
            all(job["request"]["curtailment_enabled"] for job in action["jobs"])
        )

    def test_iam_ar_sweep_reuses_matching_baseline_value(self) -> None:
        baseline = self.completed_baseline(
            request=self.validation_config(
                iam_model="martin_ruiz",
                iam_a_r=0.2,
            )
        )

        tool_result, action = app._handle_iam_ar_sweep_tool(
            app.ChatRequest(
                message="Compare Martin-Ruiz a_r values 0.1 through 0.5 by 0.1.",
                job_id=baseline["id"],
                active_mode="validation",
                current_config=baseline["request"],
            ),
            {
                "mode": "validation",
                "start_a_r": 0.1,
                "stop_a_r": 0.5,
                "increment": 0.1,
            },
        )

        self.assertEqual("batch_started", tool_result["status"])
        self.assertEqual(4, len(action["jobs"]))
        self.assertEqual(1, action["sweep"]["baseline_index"])
        self.assertEqual(0.2, action["sweep"]["baseline_value"])
        self.assertNotIn(
            0.2,
            [item["request"]["iam_a_r"] for item in action["jobs"]],
        )

    def test_annual_iam_ar_sweep_is_one_grouped_confirmation(self) -> None:
        baseline = self.completed_baseline(mode="annual", reviewed=False)

        tool_result, action = app._handle_iam_ar_sweep_tool(
            app.ChatRequest(
                message="Compare annual Martin-Ruiz a_r 0.1 to 0.3 by 0.1.",
                job_id=baseline["id"],
                active_mode="annual",
                current_config=baseline["request"],
            ),
            {
                "mode": "annual",
                "start_a_r": 0.1,
                "stop_a_r": 0.3,
                "increment": 0.1,
            },
        )

        self.assertEqual("confirmation_required", tool_result["status"])
        self.assertEqual("proposal_batch", action["type"])
        self.assertEqual(3, len(action["proposals"]))
        self.assertEqual([], app.AGENT_STORE.list_jobs(kind="candidate"))
        self.assertEqual(
            1,
            len(
                {
                    proposal["scenario_sweep"]["sweep_id"]
                    for proposal in action["proposals"]
                }
            ),
        )

    def test_annual_sweep_confirmation_preserves_calibration_provenance(self) -> None:
        calibration_baseline = self.completed_baseline(
            job_id="annual-sweep-calibration"
        )
        baseline = self.completed_baseline(mode="annual", reviewed=False)
        calibration = self.annual_calibration_provenance(calibration_baseline)
        baseline = app.AGENT_STORE.update_job(
            baseline["id"],
            provenance=calibration,
        )

        _, action = app._handle_iam_ar_sweep_tool(
            app.ChatRequest(
                message="Compare annual Martin-Ruiz a_r 0.1 to 0.3 by 0.1.",
                job_id=baseline["id"],
                active_mode="annual",
                current_config=baseline["request"],
            ),
            {
                "mode": "annual",
                "start_a_r": 0.1,
                "stop_a_r": 0.3,
                "increment": 0.1,
            },
        )
        proposal_ids = [item["proposal_id"] for item in action["proposals"]]
        response = app.confirm_agent_sweep(
            action["sweep"]["sweep_id"],
            app.ProposalSweepConfirmRequest(proposal_ids=proposal_ids),
        )

        payload = json.loads(response.body)
        self.assertEqual("job_batch_started", payload["action"]["type"])
        for item in payload["action"]["jobs"]:
            candidate = app.AGENT_STORE.get_job(item["job_id"])
            self.assertEqual(
                calibration["calibration_profile"],
                candidate["provenance"]["calibration_profile"],
            )
            expected_deltas = app._calibration_setting_deltas(
                app._baseline_transferable_settings(calibration_baseline),
                candidate["request"],
            )
            self.assertEqual(
                expected_deltas,
                candidate["provenance"]["calibration_application"][
                    "settings_deltas"
                ],
            )
            self.assertEqual(
                ["summer"],
                candidate["provenance"]["calibration_application"][
                    "required_seasons"
                ],
            )

    def test_tampered_annual_calibration_provenance_blocks_confirmation(self) -> None:
        calibration_baseline = self.completed_baseline(
            job_id="tampered-annual-calibration"
        )
        baseline = self.completed_baseline(mode="annual", reviewed=False)
        calibration = self.annual_calibration_provenance(calibration_baseline)
        calibration["calibration_application"]["resolved_profile_sha256"] = "0" * 64
        baseline = app.AGENT_STORE.update_job(
            baseline["id"],
            provenance=calibration,
        )

        _, action = app._handle_scenario_tool(
            app.ChatRequest(
                message="Turn annual backtracking off.",
                job_id=baseline["id"],
                active_mode="annual",
                current_config=baseline["request"],
            ),
            self.tool_arguments(backtrack=False),
        )

        with self.assertRaises(HTTPException) as context:
            app.confirm_agent_proposal(action["proposal"]["proposal_id"])
        self.assertEqual(409, context.exception.status_code)
        self.assertIn("provenance is invalid", str(context.exception.detail))
        self.assertEqual([], app.AGENT_STORE.list_jobs(kind="candidate"))

    def test_annual_fallback_consent_is_not_reused_for_scenarios(self) -> None:
        calibration_baseline = self.completed_baseline(
            job_id="substituted-annual-calibration"
        )
        baseline = self.completed_baseline(mode="annual", reviewed=False)
        calibration = self.annual_calibration_provenance(calibration_baseline)
        calibration["calibration_application"]["seasonal_substitution"] = {
            "source_season": "spring",
            "target_season": "fall",
            "explicitly_accepted": True,
        }
        calibration["calibration_application"]["server_confirmation"] = {
            "accepted": True,
            "confirmation_context_sha256": "1" * 64,
        }
        baseline = app.AGENT_STORE.update_job(
            baseline["id"],
            provenance=calibration,
        )

        _, action = app._handle_scenario_tool(
            app.ChatRequest(
                message="Turn annual backtracking off.",
                job_id=baseline["id"],
                active_mode="annual",
                current_config=baseline["request"],
            ),
            self.tool_arguments(backtrack=False),
        )

        with self.assertRaises(HTTPException) as context:
            app.confirm_agent_proposal(action["proposal"]["proposal_id"])
        self.assertEqual(409, context.exception.status_code)
        self.assertIn("fresh confirmation", str(context.exception.detail))
        self.assertEqual([], app.AGENT_STORE.list_jobs(kind="candidate"))

    def test_embedded_annual_fallback_requires_fresh_confirmation(self) -> None:
        calibration_baseline = self.completed_baseline(
            job_id="embedded-substitution-calibration"
        )
        baseline = self.completed_baseline(mode="annual", reviewed=False)
        calibration = self.annual_calibration_provenance(calibration_baseline)
        calibration["calibration_profile"]["seasonal_substitution"] = {
            "source_season": "spring",
            "target_season": "fall",
        }
        baseline = app.AGENT_STORE.update_job(
            baseline["id"],
            provenance=calibration,
        )

        _, action = app._handle_scenario_tool(
            app.ChatRequest(
                message="Turn annual backtracking off.",
                job_id=baseline["id"],
                active_mode="annual",
                current_config=baseline["request"],
            ),
            self.tool_arguments(backtrack=False),
        )

        with self.assertRaises(HTTPException) as context:
            app.confirm_agent_proposal(action["proposal"]["proposal_id"])
        self.assertEqual(409, context.exception.status_code)
        self.assertIn("fresh confirmation", str(context.exception.detail))
        self.assertEqual([], app.AGENT_STORE.list_jobs(kind="candidate"))

    def test_annual_sweep_confirmation_is_all_or_nothing_near_capacity(self) -> None:
        baseline = self.completed_baseline(mode="annual", reviewed=False)
        _, action = app._handle_iam_ar_sweep_tool(
            app.ChatRequest(
                message="Compare annual Martin-Ruiz a_r 0.1 to 0.3 by 0.1.",
                job_id=baseline["id"],
                active_mode="annual",
                current_config=baseline["request"],
            ),
            {
                "mode": "annual",
                "start_a_r": 0.1,
                "stop_a_r": 0.3,
                "increment": 0.1,
            },
        )
        sweep_id = action["sweep"]["sweep_id"]
        proposal_ids = [item["proposal_id"] for item in action["proposals"]]
        active = app.AGENT_STORE.create_job(
            job_id="annual-sweep-active",
            kind="manual",
            mode="annual",
            request=baseline["request"],
        )
        request = app.ProposalSweepConfirmRequest(proposal_ids=proposal_ids)

        with patch.object(app, "MAX_ACTIVE_MODEL_JOBS", 3):
            with self.assertRaises(HTTPException) as capacity_error:
                app.confirm_agent_sweep(sweep_id, request)
        self.assertEqual(429, capacity_error.exception.status_code)
        self.assertEqual([], app.AGENT_STORE.list_jobs(kind="candidate"))
        self.assertTrue(
            all(
                app.AGENT_STORE.get_proposal(proposal_id)["state"] == "pending"
                for proposal_id in proposal_ids
            )
        )

        with self.assertRaises(HTTPException) as single_error:
            app.confirm_agent_proposal(proposal_ids[0])
        self.assertEqual(409, single_error.exception.status_code)
        self.assertEqual([], app.AGENT_STORE.list_jobs(kind="candidate"))

        app.AGENT_STORE.cancel_job(active["id"])
        with patch.object(app, "MAX_ACTIVE_MODEL_JOBS", 3):
            response = app.confirm_agent_sweep(sweep_id, request)
        payload = json.loads(response.body)
        self.assertEqual("job_batch_started", payload["action"]["type"])
        self.assertEqual(3, len(payload["action"]["jobs"]))
        self.assertTrue(
            all(
                app.AGENT_STORE.get_proposal(proposal_id)["state"] == "confirmed"
                for proposal_id in proposal_ids
            )
        )

    def test_missing_validation_baseline_requires_visible_data_review(self) -> None:
        tool_result, action = app._handle_scenario_tool(
            app.ChatRequest(
                message="Use Martin-Ruiz a_r 0.80",
                active_mode="validation",
                current_config=self.validation_config(),
            ),
            self.tool_arguments(iam_model="martin_ruiz", iam_a_r=0.8),
        )

        self.assertEqual(tool_result["status"], "data_review_required")
        self.assertEqual(action["type"], "data_review_required")
        self.assertIn("visible Bazefield data-quality review", tool_result["message"])
        self.assertIn("No Solar Agent proposal or model job", tool_result["message"])
        self.assertEqual(
            tool_result["effective_request"]["iam_model"], "martin_ruiz"
        )
        self.assertEqual(tool_result["effective_request"]["iam_a_r"], 0.8)
        self.assertEqual(app.AGENT_STORE.list_proposals(), [])
        self.assertEqual(app.AGENT_STORE.list_jobs(), [])

    def test_verified_same_input_auto_start_reuses_hash_and_never_fetches(self) -> None:
        baseline = self.completed_baseline()
        _, action = app._handle_scenario_tool(
            app.ChatRequest(
                message="Turn backtracking off.",
                job_id=baseline["id"],
                active_mode="validation",
                current_config=self.validation_config(),
            ),
            self.tool_arguments(backtrack=False),
        )

        self.assertEqual(action["type"], "job_started")
        job_id = action["job"]["job_id"]
        candidate = app.AGENT_STORE.get_job(job_id)
        self.assertEqual(candidate["state"], "queued")
        self.assertEqual(candidate["baseline_id"], baseline["id"])
        self.assertEqual(candidate["source_path"], baseline["source_path"])
        self.assertEqual(candidate["source_hash"], baseline["source_hash"])
        profile = candidate["provenance"]["calibration_profile"]
        self.assertEqual(profile["origin_job_id"], baseline["id"])
        self.assertEqual(
            profile["seasonal_factors"]["summer"]["solaredge"],
            1.1234567890123,
        )
        self.assertEqual(
            candidate["provenance"]["data_quality"]["review_id"],
            f"review-{baseline['id']}",
        )

        claimed = app.AGENT_STORE.claim_next_queued_job()
        self.assertEqual(claimed["id"], job_id)
        with (
            patch.object(
                app.historian,
                "run_historian",
                side_effect=AssertionError("cached scenarios must not fetch Bazefield"),
            ) as historian_call,
            patch.object(app, "_render_input_data_plots", return_value={}),
            patch.object(
                app.model,
                "run_model",
                return_value={
                    "ac_png": str(self.root / "candidate_ac.png"),
                    "energy_png": str(self.root / "candidate_energy.png"),
                    "excel": str(self.root / "candidate.xlsx"),
                },
            ) as model_call,
            patch.object(app, "_finish_model_job") as finish_call,
        ):
            app._run_job(
                job_id,
                app.RunRequest(**candidate["request"]),
                source_path=candidate["source_path"],
                expected_source_hash=candidate["source_hash"],
                data_quality_context=candidate["provenance"]["data_quality"],
                calibration_profile=profile,
            )

        historian_call.assert_not_called()
        self.assertEqual(
            Path(model_call.call_args.kwargs["input_csv"]).resolve(),
            Path(baseline["source_path"]).resolve(),
        )
        self.assertIs(
            model_call.call_args.kwargs["calibration_profile"],
            profile,
        )
        self.assertEqual(
            model_call.call_args.kwargs["data_quality_context"]["review_id"],
            f"review-{baseline['id']}",
        )
        finish_call.assert_called_once()
        result = finish_call.call_args.args[1]
        window = result["window"]
        self.assertTrue(window["from_local"].startswith("2026-06-20T08:00"))
        self.assertTrue(window["to_local"].startswith("2026-06-21T18:00"))
        self.assertTrue(window["from_local"].endswith("-06:00"))
        self.assertTrue(window["to_local"].endswith("-06:00"))
        self.assertEqual(window["from_utc"], window["from"] + "Z")
        self.assertEqual(window["to_utc"], window["to"] + "Z")
        self.assertEqual(window["timezone"], "America/Denver")
        self.assertTrue(window["end_exclusive"])
        for system in ("solaredge", "solectria"):
            inverter = window[f"{system}_inverter_efficiency"]
            bos = window[f"{system}_bos_efficiency"]
            self.assertEqual(
                inverter,
                candidate["request"][f"{system}_inverter_efficiency"],
            )
            self.assertEqual(
                bos,
                candidate["request"][f"{system}_bos_efficiency"],
            )
            self.assertAlmostEqual(
                window[f"{system}_total_efficiency"],
                inverter * bos,
            )

    def test_fresh_validation_window_requires_review_without_state_change(
        self,
    ) -> None:
        baseline = self.completed_baseline()
        tool_result, action = app._handle_scenario_tool(
            app.ChatRequest(
                message="Run June 1-7 using Bazefield with physical IAM.",
                job_id=baseline["id"],
                active_mode="validation",
                current_config=self.validation_config(),
            ),
            self.tool_arguments(
                from_date="2026-06-01",
                to_date="2026-06-08",
                iam_model="physical",
            ),
        )

        self.assertEqual(tool_result["status"], "data_review_required")
        self.assertEqual(action["type"], "data_review_required")
        self.assertEqual(
            action["effective_request"]["from_date"], "2026-06-01"
        )
        self.assertEqual(action["effective_request"]["to_date"], "2026-06-08")
        self.assertIn("Retain or Exclude", action["message"])
        self.assertEqual(app.AGENT_STORE.list_jobs(kind="candidate"), [])
        self.assertEqual(app.AGENT_STORE.list_proposals(), [])
        self.assertEqual(
            app.AGENT_STORE.get_current_baseline("validation")["job_id"],
            baseline["id"],
        )

    def test_same_input_unreviewed_baseline_requires_visible_review(self) -> None:
        baseline = self.completed_baseline(reviewed=False)

        tool_result, action = app._handle_scenario_tool(
            app.ChatRequest(
                message="Turn backtracking off.",
                job_id=baseline["id"],
                active_mode="validation",
                current_config=self.validation_config(),
            ),
            self.tool_arguments(backtrack=False),
        )

        self.assertEqual(tool_result["status"], "data_review_required")
        self.assertEqual(action["type"], "data_review_required")
        self.assertEqual(app.AGENT_STORE.list_jobs(kind="candidate"), [])
        self.assertEqual(app.AGENT_STORE.list_proposals(), [])

    def test_promoted_same_input_scenario_reuses_original_profile(self) -> None:
        original = self.completed_baseline()
        _, first_action = app._handle_scenario_tool(
            app.ChatRequest(
                message="Turn backtracking off.",
                job_id=original["id"],
                active_mode="validation",
                current_config=self.validation_config(),
            ),
            self.tool_arguments(backtrack=False),
        )
        first_id = first_action["job"]["job_id"]
        claimed = app.AGENT_STORE.claim_next_queued_job()
        self.assertEqual(claimed["id"], first_id)
        app.AGENT_STORE.update_job(
            first_id,
            state="done",
            progress=100,
            stage="Done",
            result={
                "calibration_factors": {
                    "seasons": [
                        {
                            "season": "summer",
                            "systems": {
                                "solaredge": {"factor": 9.0},
                                "solectria": {"factor": 9.0},
                            },
                        }
                    ]
                }
            },
        )
        promoted_payload = json.loads(
            app.promote_model_job(first_id).body.decode("utf-8")
        )
        self.assertEqual(promoted_payload["job_id"], first_id)

        promoted = app.AGENT_STORE.get_job(first_id)
        _, second_action = app._handle_scenario_tool(
            app.ChatRequest(
                message="Use 95 percent SolarEdge inverter efficiency.",
                job_id=first_id,
                active_mode="validation",
                current_config=promoted["request"],
            ),
            self.tool_arguments(solaredge_inverter_efficiency=0.95),
        )
        second = app.AGENT_STORE.get_job(
            second_action["job"]["job_id"]
        )
        profile = second["provenance"]["calibration_profile"]
        self.assertEqual(profile["origin_job_id"], original["id"])
        self.assertEqual(
            profile["seasonal_factors"]["summer"]["solaredge"],
            1.1234567890123,
        )

    def test_reviewed_profile_missing_candidate_season_is_rejected(self) -> None:
        multi_season_request = self.validation_config(
            from_date="2026-01-01",
            from_time="00:00",
            to_date="2026-07-01",
            to_time="00:00",
        )
        baseline = self.completed_baseline(request=multi_season_request)
        result = baseline["result"]
        summer_only = {
            **result["calibration_factors"],
            "seasons": [
                record
                for record in result["calibration_factors"]["seasons"]
                if record["season"] == "summer"
            ],
        }
        app.AGENT_STORE.update_job(
            baseline["id"],
            result={
                **result,
                "calibration_factors": summer_only,
            },
        )

        with self.assertRaises(HTTPException) as context:
            app._handle_scenario_tool(
                app.ChatRequest(
                    message="Turn backtracking off.",
                    job_id=baseline["id"],
                    active_mode="validation",
                    current_config=multi_season_request,
                ),
                self.tool_arguments(backtrack=False),
            )

        self.assertEqual(context.exception.status_code, 409)
        self.assertIn("winter", str(context.exception.detail).lower())
        self.assertEqual(
            app.AGENT_STORE.list_jobs(kind="candidate"),
            [],
        )

    def test_fresh_validation_window_does_not_queue_behind_active_job(
        self,
    ) -> None:
        baseline = self.completed_baseline()
        active = app.AGENT_STORE.create_job(
            job_id="already-running",
            kind="candidate",
            mode="validation",
            request=self.validation_config(backtrack=False),
            baseline_id=baseline["id"],
        )
        claimed = app.AGENT_STORE.claim_next_queued_job()
        self.assertEqual(claimed["id"], active["id"])

        tool_result, action = app._handle_scenario_tool(
            app.ChatRequest(
                message="Run June 1-7 using Bazefield with physical IAM.",
                job_id=baseline["id"],
                active_mode="validation",
                current_config=self.validation_config(),
            ),
            self.tool_arguments(
                from_date="2026-06-01",
                to_date="2026-06-08",
                iam_model="physical",
            ),
        )

        self.assertEqual(tool_result["status"], "data_review_required")
        self.assertEqual(action["type"], "data_review_required")
        self.assertEqual(
            [job["id"] for job in app.AGENT_STORE.list_jobs(kind="candidate")],
            [active["id"]],
        )
        self.assertEqual(app.AGENT_STORE.list_proposals(), [])

    def test_cross_run_validation_proposal_cannot_be_confirmed(
        self,
    ) -> None:
        baseline = self.completed_baseline()
        _, candidate = app._canonical_request(
            "validation",
            self.validation_config(
                from_date="2026-06-01",
                from_time="00:00",
                to_date="2026-06-08",
                to_time="00:00",
            ),
        )
        proposal = app.AGENT_STORE.create_proposal(
            mode="validation",
            effective_request=candidate,
            changes=[
                {
                    "field": "from_date",
                    "label": "Start date",
                    "from": baseline["request"]["from_date"],
                    "to": candidate["from_date"],
                }
            ],
            baseline_id=baseline["id"],
            comparison_kind="cross_run",
            confirmation_required=True,
            confirmation_reason="legacy cross-run proposal",
            confirmation_metadata={"job_kind": "candidate"},
        )

        with self.assertRaises(HTTPException) as context:
            app._confirm_durable_proposal(proposal)

        self.assertEqual(context.exception.status_code, 409)
        self.assertIn("visible Calibration", str(context.exception.detail))
        self.assertEqual(app.AGENT_STORE.list_jobs(kind="candidate"), [])

    def test_unreviewed_validation_candidate_cannot_be_promoted(self) -> None:
        baseline = self.completed_baseline()
        candidate = app.AGENT_STORE.create_job(
            job_id="unreviewed-candidate",
            kind="candidate",
            mode="validation",
            request=self.validation_config(backtrack=False),
            baseline_id=baseline["id"],
            source_path=baseline["source_path"],
            source_hash=baseline["source_hash"],
            provenance={"calibration_profile": {"schema_version": 1}},
        )
        claimed = app.AGENT_STORE.claim_next_queued_job()
        self.assertEqual(claimed["id"], candidate["id"])
        app.AGENT_STORE.update_job(
            candidate["id"],
            state="done",
            result={"mode": "validation", "stats": {}},
        )

        with self.assertRaises(HTTPException) as context:
            app.promote_model_job(candidate["id"])

        self.assertEqual(context.exception.status_code, 409)
        self.assertIn("hash-verified data-quality review", context.exception.detail)
        self.assertEqual(
            app.AGENT_STORE.get_current_baseline("validation")["job_id"],
            baseline["id"],
        )

    def test_tampered_reviewed_source_cannot_be_promoted(self) -> None:
        baseline = self.completed_baseline()
        Path(baseline["source_path"]).write_text(
            "tampered after completion",
            encoding="utf-8",
        )

        with self.assertRaises(HTTPException) as context:
            app.promote_model_job(baseline["id"])

        self.assertEqual(context.exception.status_code, 409)
        self.assertIn("hash-verified", context.exception.detail)

    def test_mode_change_clones_active_mode_baseline_and_is_cross_run(self) -> None:
        validation = self.completed_baseline(job_id="validation-selected")
        annual_request = {
            **self.validation_config(),
            "from_date": "2025-01-01",
            "to_date": "2025-12-31",
        }
        annual = self.completed_baseline(
            job_id="annual-other",
            mode="annual",
            request=annual_request,
        )

        _, action = app._handle_scenario_tool(
            app.ChatRequest(
                message="Switch this validation setup to an annual run.",
                job_id=validation["id"],
                active_mode="validation",
                current_config=self.validation_config(),
            ),
            self.tool_arguments(mode="annual"),
        )

        proposal = action["proposal"]
        self.assertEqual(proposal["baseline_job_id"], validation["id"])
        self.assertNotEqual(proposal["baseline_job_id"], annual["id"])
        self.assertEqual(proposal["mode"], "annual")
        self.assertEqual(proposal["comparison_kind"], "cross_run")
        self.assertEqual(proposal["changes"][0]["field"], "mode")
        self.assertEqual(proposal["changes"][0]["from"], "validation")
        self.assertEqual(proposal["changes"][0]["to"], "annual")
        self.assertTrue(proposal["confirmation_required"])

    def test_chat_context_uses_active_mode_and_includes_trusted_comparison(self) -> None:
        self.completed_baseline(job_id="validation-context")
        annual = self.completed_baseline(
            job_id="annual-context",
            mode="annual",
            request={
                **self.validation_config(),
                "from_date": "2025-01-01",
                "to_date": "2025-12-31",
            },
        )
        app.AGENT_STORE.update_job(
            annual["id"],
            comparison={
                "comparison_type": "cross_run",
                "systems": {"solaredge": {"delta_kwh": 12.5}},
            },
            provenance={"comparability": "non-like-for-like"},
            artifacts={"comparison_workbook": {"url": "/outputs/annual-compare.xlsx"}},
        )

        resolved, context = app._chat_run_context(None, "annual")

        self.assertEqual(resolved, annual["id"])
        self.assertEqual(context["mode"], "annual")
        self.assertEqual(context["comparison"]["comparison_type"], "cross_run")
        self.assertEqual(
            context["comparison"]["systems"]["solaredge"]["delta_kwh"],
            12.5,
        )
        self.assertEqual(context["provenance"]["comparability"], "non-like-for-like")
        self.assertEqual(
            context["artifacts"]["comparison_workbook"]["url"],
            "/outputs/annual-compare.xlsx",
        )

    def test_disabled_scenario_actions_omit_tool_and_ignore_fabricated_call(self) -> None:
        fabricated = {
            "type": "function_call",
            "name": "propose_model_scenario",
            "call_id": "fabricated-call",
            "arguments": json.dumps(self.tool_arguments(backtrack=False)),
        }
        api_calls = []

        def create_response(**kwargs):
            api_calls.append(kwargs)
            return types.SimpleNamespace(
                output=[fabricated],
                output_text="The trusted comparison is explained without taking action.",
            )

        fake_client = types.SimpleNamespace(
            responses=types.SimpleNamespace(create=create_response)
        )
        fake_openai = types.ModuleType("openai")
        fake_openai.OpenAI = lambda: fake_client

        with patch.dict(sys.modules, {"openai": fake_openai}):
            result = app._openai_agent_response(
                app.ChatRequest(
                    message="Explain these completed results only.",
                    active_mode="validation",
                    current_config=self.validation_config(),
                    allow_scenario_actions=False,
                )
            )

        self.assertEqual(len(api_calls), 1)
        self.assertNotIn(app.SCENARIO_TOOL, api_calls[0]["tools"])
        self.assertEqual(api_calls[0]["tools"], [])
        self.assertIsNone(result["action"])
        self.assertEqual(app.AGENT_STORE.list_proposals(), [])
        self.assertEqual(app.AGENT_STORE.list_jobs(), [])


if __name__ == "__main__":
    unittest.main()
