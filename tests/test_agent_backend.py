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

from sbepv import model
from sbepv.api import config, plots, state
from sbepv.worker import completion
from sbepv.worker import run_validation
from sbepv.agent import chat
from sbepv.agent import message_guards
from sbepv.agent import scenario_math
from sbepv.agent import tools
from sbepv.api import proposals
from sbepv.api import baselines
from sbepv.api import main as app
from sbepv.store import AgentStore, LeaseOwnershipLost
from sbepv.reporting import sha256_file


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

        self.original_store = state.AGENT_STORE
        state.AGENT_STORE = AgentStore(self.db_path)
        self.addCleanup(setattr, state, "AGENT_STORE", self.original_store)

        state.JOBS.clear()
        self.addCleanup(state.JOBS.clear)
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
        include_annual_temporal_semantics: bool = True,
    ) -> dict:
        if request is None:
            request = self.validation_config()
        if reviewed is None:
            reviewed = mode == "validation"
        _, canonical = scenario_math._canonical_request(mode, request)

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
        result = {
            "mode": mode,
            "stats": {
                "calibration_physics_version": (
                    model.CALIBRATION_PHYSICS_VERSION
                ),
                "calibration_physics_fingerprint": (
                    model.CALIBRATION_PHYSICS_FINGERPRINT
                ),
                "solectria_physics_version": model.SOLECTRIA_PHYSICS_VERSION,
                "solectria_physics_fingerprint": (
                    model.SOLECTRIA_PHYSICS_FINGERPRINT
                ),
            },
        }
        if mode == "annual" and include_annual_temporal_semantics:
            result["stats"].update(
                {
                    "annual_temporal_semantics_version": (
                        model.ANNUAL_TEMPORAL_SEMANTICS_VERSION
                    ),
                    "annual_temporal_semantics_fingerprint": (
                        model.ANNUAL_TEMPORAL_SEMANTICS_FINGERPRINT
                    ),
                }
            )
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
        created = state.AGENT_STORE.create_job(
            job_id=job_id,
            kind="baseline",
            mode=mode,
            request=canonical,
            provenance=provenance,
        )
        claimed = state.AGENT_STORE.claim_next_queued_job()
        self.assertEqual(created["id"], claimed["id"])
        completed = state.AGENT_STORE.update_job(
            job_id,
            state="done",
            progress=100,
            stage="Done",
            source_path=str(source.resolve()),
            source_hash=source_hash,
            result=result,
            artifacts={},
        )
        state.AGENT_STORE.promote_job(job_id)
        return completed

    def completed_physics_baseline(self, *, job_id: str) -> dict:
        _, canonical = scenario_math._canonical_request(
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
        created = state.AGENT_STORE.create_job(
            job_id=job_id,
            kind="baseline",
            mode="validation",
            request=canonical,
        )
        claimed = state.AGENT_STORE.claim_next_queued_job()
        self.assertEqual(created["id"], claimed["id"])
        return state.AGENT_STORE.update_job(
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
            "calibration_physics_version": model.CALIBRATION_PHYSICS_VERSION,
            "calibration_physics_fingerprint": (
                model.CALIBRATION_PHYSICS_FINGERPRINT
            ),
            "solectria_physics_version": model.SOLECTRIA_PHYSICS_VERSION,
            "solectria_physics_fingerprint": (
                model.SOLECTRIA_PHYSICS_FINGERPRINT
            ),
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
        job = state.AGENT_STORE.create_job(
            job_id=job_id,
            kind="candidate",
            mode="validation",
            baseline_id="baseline-validation",
            request=self.validation_config(),
        )
        state.AGENT_STORE.claim_next_queued_job()

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
        state.AGENT_STORE.update_job(
            job_id,
            state="done",
            source_path=str(source),
            result={"excel": f"/outputs/{workbook.name}"},
            artifacts={"comparison": {"path": str(comparison)}},
        )
        with patch.object(config, "OUTPUT_DIR", self.root):
            response = app.delete_model_job(job_id)

        self.assertEqual(200, response.status_code)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertTrue(payload["deleted"])
        self.assertEqual(3, payload["artifacts_deleted"])
        self.assertIsNone(state.AGENT_STORE.get_job(job_id))
        self.assertFalse(source.exists())
        self.assertFalse(workbook.exists())
        self.assertFalse(comparison.exists())

    def test_expired_runner_stops_before_mutating_reclaimed_job(self) -> None:
        _, canonical = scenario_math._canonical_request(
            "validation", self.validation_config(calibrate_model=False)
        )
        state.AGENT_STORE.create_job(
            job_id="lease-race",
            kind="manual",
            mode="validation",
            request=canonical,
        )
        first = state.AGENT_STORE.claim_next_queued_job(
            worker_id=app.SERVER_SESSION_ID
        )
        first_token = first["lease_token"]
        state.AGENT_STORE.mark_stale_running_jobs_interrupted()
        state.AGENT_STORE.retry_job("lease-race")
        second = state.AGENT_STORE.claim_next_queued_job(
            worker_id=app.SERVER_SESSION_ID
        )
        app._cache_job_record(second)

        with (
            patch.object(app.historian, "run_historian") as historian_call,
            patch.object(app.model, "run_model") as model_call,
        ):
            run_validation._run_job(
                "lease-race",
                app.RunRequest(**canonical),
                worker_id=app.SERVER_SESSION_ID,
                lease_token=first_token,
            )

        historian_call.assert_not_called()
        model_call.assert_not_called()
        current = state.AGENT_STORE.get_job("lease-race")
        self.assertEqual("running", current["state"])
        self.assertEqual(second["lease_token"], current["lease_token"])
        self.assertEqual(0, current["progress"])
        self.assertEqual(0, state.JOBS["lease-race"]["progress"])

    def test_owned_attempt_uses_lease_token_specific_output_prefix(self) -> None:
        _, canonical = scenario_math._canonical_request(
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
        state.AGENT_STORE.create_job(
            job_id="lease-output",
            kind="manual",
            mode="validation",
            request=canonical,
            source_path=str(source.resolve()),
            source_hash=source_hash,
        )
        claimed = state.AGENT_STORE.claim_next_queued_job(worker_id="worker-a")

        with (
            patch.object(plots, "_render_input_data_plots", return_value={}),
            patch.object(
                app.model,
                "run_model",
                return_value={
                    "ac_png": str(self.root / "lease-output-ac.png"),
                    "energy_png": str(self.root / "lease-output-energy.png"),
                    "excel": str(self.root / "lease-output.xlsx"),
                    "historian_preflight": {
                        "policy": "validation_weather_preflight_v1",
                        "coverage_pct": 99.0,
                        "omitted_row_count": 1,
                    },
                    "data_quality_warnings": [
                        "Validation omitted 1 unusable weather interval."
                    ],
                },
            ) as model_call,
            patch.object(completion, "_finish_model_job") as finish_call,
        ):
            run_validation._run_job(
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
        completed_result = finish_call.call_args.args[1]
        self.assertEqual(
            99.0, completed_result["historian_preflight"]["coverage_pct"]
        )
        self.assertEqual(
            ["Validation omitted 1 unusable weather interval."],
            completed_result["warnings"],
        )

    def test_delete_removes_artifacts_from_every_lease_attempt(self) -> None:
        job_id = "candidate-attempt-cleanup"
        state.AGENT_STORE.create_job(
            job_id=job_id,
            kind="candidate",
            mode="validation",
            baseline_id="baseline-validation",
            request=self.validation_config(),
        )
        first = state.AGENT_STORE.claim_next_queued_job(worker_id="worker-a")
        first_prefix = app._job_attempt_prefix(job_id, first["lease_token"])
        stale_artifact = self.root / f"{first_prefix}_stale.xlsx"
        stale_artifact.write_text("stale attempt", encoding="utf-8")
        self.generated_files.append(stale_artifact)

        state.AGENT_STORE.mark_stale_running_jobs_interrupted()
        state.AGENT_STORE.retry_job(job_id)
        second = state.AGENT_STORE.claim_next_queued_job(worker_id="worker-a")
        second_prefix = app._job_attempt_prefix(job_id, second["lease_token"])
        accepted_artifact = self.root / f"{second_prefix}.xlsx"
        accepted_artifact.write_text("accepted attempt", encoding="utf-8")
        self.generated_files.append(accepted_artifact)
        self.assertNotEqual(first_prefix, second_prefix)
        state.AGENT_STORE.update_job(
            job_id,
            expected_worker_id="worker-a",
            expected_lease_token=second["lease_token"],
            state="done",
            result={"excel": f"/outputs/{accepted_artifact.name}"},
        )

        with patch.object(config, "OUTPUT_DIR", self.root):
            response = app.delete_model_job(job_id)

        self.assertEqual(200, response.status_code)
        self.assertFalse(stale_artifact.exists())
        self.assertFalse(accepted_artifact.exists())

    def test_lost_attempt_cleanup_preserves_source_reused_by_retry(self) -> None:
        job_id = "attempt-source-reuse"
        state.AGENT_STORE.create_job(
            job_id=job_id,
            kind="manual",
            mode="validation",
            request=self.validation_config(),
        )
        first = state.AGENT_STORE.claim_next_queued_job(worker_id="worker-a")
        first_prefix = app._job_attempt_prefix(job_id, first["lease_token"])
        source = self.root / f"{first_prefix}.csv"
        stale_plot = self.root / f"{first_prefix}_ac.png"
        source.write_text("timestamp,dni\n2026-06-20,700\n", encoding="utf-8")
        stale_plot.write_text("stale plot", encoding="utf-8")
        self.generated_files.extend([source, stale_plot])
        state.AGENT_STORE.update_job(
            job_id,
            expected_worker_id="worker-a",
            expected_lease_token=first["lease_token"],
            source_path=str(source.resolve()),
            source_hash=sha256_file(source),
        )

        state.AGENT_STORE.mark_stale_running_jobs_interrupted()
        state.AGENT_STORE.retry_job(job_id)
        state.AGENT_STORE.claim_next_queued_job(worker_id="worker-a")
        with patch.object(config, "OUTPUT_DIR", self.root):
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

        state.AGENT_STORE.create_job(
            job_id=candidate_id,
            kind="candidate",
            mode="validation",
            baseline_id=baseline["id"],
            request=self.validation_config(calibrate_model=False),
            source_path=str(baseline_source),
            source_hash=baseline_hash,
        )
        claimed = state.AGENT_STORE.claim_next_queued_job()
        self.assertEqual(candidate_id, claimed["id"])
        state.AGENT_STORE.update_job(
            candidate_id,
            state="done",
            result={
                "source_csv": f"/outputs/{baseline_source.name}",
                "excel": f"/outputs/{workbook.name}",
            },
            artifacts={"model_workbook": {"path": str(workbook)}},
        )

        with patch.object(config, "OUTPUT_DIR", self.root):
            response = app.delete_model_job(candidate_id)

        self.assertEqual(200, response.status_code)
        self.assertIsNone(state.AGENT_STORE.get_job(candidate_id))
        self.assertFalse(workbook.exists())
        self.assertTrue(baseline_source.exists())
        self.assertEqual(baseline_hash, sha256_file(baseline_source))
        verified_path, verified_hash = app._verified_baseline_source(
            state.AGENT_STORE.get_job(baseline["id"])
        )
        self.assertEqual(str(baseline_source.resolve()), verified_path)
        self.assertEqual(baseline_hash, verified_hash)

    def test_chat_fallback_prefers_promoted_baseline_over_newer_scenario(self) -> None:
        baseline = self.completed_physics_baseline(job_id="promoted-chat-baseline")
        state.AGENT_STORE.promote_job(baseline["id"])
        candidate = state.AGENT_STORE.create_job(
            job_id="newer-unpromoted-scenario",
            kind="candidate",
            mode="validation",
            baseline_id=baseline["id"],
            request=self.validation_config(calibrate_model=False),
            source_path=baseline["source_path"],
            source_hash=baseline["source_hash"],
        )
        claimed = state.AGENT_STORE.claim_next_queued_job()
        self.assertEqual(candidate["id"], claimed["id"])
        state.AGENT_STORE.update_job(
            candidate["id"],
            state="done",
            result={"mode": "validation", "stats": {"calibration_enabled": False}},
        )

        resolved_job_id, context = chat._chat_run_context(None, "validation")

        self.assertEqual(baseline["id"], resolved_job_id)
        self.assertEqual(baseline["id"], context["job_id"])

    def test_numeric_iam_is_clarified_without_openai_or_state_change(self) -> None:
        fake_openai = types.ModuleType("openai")

        def forbidden_client():
            self.fail("ambiguous IAM must be rejected before calling OpenAI")

        fake_openai.OpenAI = forbidden_client
        with patch.dict(sys.modules, {"openai": fake_openai}):
            response = chat._openai_agent_response(
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
        self.assertEqual(state.AGENT_STORE.list_proposals(), [])
        self.assertEqual(state.AGENT_STORE.list_jobs(), [])

    def test_iam_dates_years_and_percentages_are_not_numeric_iam_values(self) -> None:
        self.assertFalse(message_guards._ambiguous_numeric_iam("Explain IAM results for 2026."))
        self.assertFalse(
            message_guards._ambiguous_numeric_iam("Compare IAM on 2026-06-20 at 97% efficiency.")
        )
        self.assertTrue(message_guards._ambiguous_numeric_iam("Set IAM to 0.8 and run it."))

    def test_visible_physics_run_is_used_instead_of_older_promoted_calibration(self) -> None:
        self.completed_baseline(job_id="older-calibrated")
        physics = self.completed_physics_baseline(job_id="visible-physics")

        _, action = tools._handle_scenario_tool(
            app.ChatRequest(
                message="Run this physics model with backtracking off.",
                job_id=physics["id"],
                active_mode="validation",
                current_config=physics["request"],
            ),
            self.tool_arguments(backtrack=False),
        )

        candidate = state.AGENT_STORE.get_job(action["job"]["job_id"])
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
            state.AGENT_STORE.get_current_baseline("validation")["job_id"],
        )

    def test_physics_worker_passes_exact_request_boundaries_to_model(self) -> None:
        physics = self.completed_physics_baseline(job_id="physics-boundaries")
        proposal = proposals._create_candidate_proposal(
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
        candidate = proposals._confirm_durable_proposal(proposal, automatic=True)
        claimed = state.AGENT_STORE.claim_next_queued_job()
        self.assertEqual(candidate["id"], claimed["id"])

        with (
            patch.object(plots, "_render_input_data_plots", return_value={}),
            patch.object(
                app.model,
                "run_model",
                return_value={
                    "ac_png": str(self.root / "physics_ac.png"),
                    "energy_png": str(self.root / "physics_energy.png"),
                    "excel": str(self.root / "physics.xlsx"),
                },
            ) as model_call,
            patch.object(completion, "_finish_model_job"),
        ):
            request = app.RunRequest(**candidate["request"])
            run_validation._run_job(
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
            result = chat._openai_agent_response(
                app.ChatRequest(
                    message="Run one scenario.",
                    job_id=baseline["id"],
                    active_mode="validation",
                    current_config=baseline["request"],
                )
            )

        self.assertIn("did not start", result["reply"])
        self.assertIsNone(result["action"])
        self.assertEqual([], state.AGENT_STORE.list_jobs(kind="candidate"))
        self.assertEqual([], state.AGENT_STORE.list_proposals())
        self.assertEqual(app.OPENAI_TIMEOUT_SECONDS, constructor_calls[0]["timeout"])
        self.assertEqual(app.OPENAI_MAX_RETRIES, constructor_calls[0]["max_retries"])
        self.assertEqual(config.OPENAI_MODEL, api_calls[0]["model"])
        self.assertEqual(
            {"effort": config.OPENAI_REASONING_EFFORT},
            api_calls[0]["reasoning"],
        )
        self.assertIn("max", config.OPENAI_REASONING_EFFORTS)
        self.assertNotIn("minimal", config.OPENAI_REASONING_EFFORTS)
        self.assertEqual(1, api_calls[0]["max_tool_calls"])
        self.assertFalse(api_calls[0]["parallel_tool_calls"])

    def test_recent_run_context_is_terminal_durable_and_capped_at_ten(self) -> None:
        for index in range(11):
            job_id = f"recent-{index:02d}"
            state.AGENT_STORE.create_job(
                job_id=job_id,
                kind="baseline",
                mode="annual",
                request={
                    "years": [2012 + index],
                    "interval_value": 1,
                    "interval_unit": "hours",
                    "private_internal_value": "must-not-enter-agent-context",
                },
            )
            claimed = state.AGENT_STORE.claim_next_queued_job()
            self.assertEqual(job_id, claimed["id"])
            state.AGENT_STORE.update_job(
                job_id,
                state="done",
                result={
                    "stats": {
                        "annual_energy_by_year": [
                            {
                                "year": 2012 + index,
                                "coverage_status": "complete",
                                "complete_calendar_year": True,
                                "cdf_eligible": True,
                            }
                        ]
                    }
                },
            )
        state.AGENT_STORE.create_job(
            job_id="still-queued",
            kind="baseline",
            mode="annual",
            request={"years": [2026]},
        )

        summaries = chat._recent_run_context("annual", limit=999)

        self.assertEqual(10, len(summaries))
        self.assertNotIn("still-queued", {row["job_id"] for row in summaries})
        self.assertNotIn("recent-00", {row["job_id"] for row in summaries})
        self.assertTrue(all(row["state"] == "done" for row in summaries))
        self.assertTrue(all(row["origin"] == "Dashboard" for row in summaries))
        self.assertEqual(1, summaries[0]["metrics"]["full_year_count"])
        self.assertNotIn(
            "private_internal_value", summaries[0]["request"]
        )

    def test_recent_run_context_prefers_explicit_source_coverage_eligibility(self) -> None:
        state.AGENT_STORE.create_job(
            job_id="source-partial-year",
            kind="baseline",
            mode="annual",
            request={"years": [2023], "interval_value": 1, "interval_unit": "hours"},
        )
        claimed = state.AGENT_STORE.claim_next_queued_job()
        self.assertEqual("source-partial-year", claimed["id"])
        state.AGENT_STORE.update_job(
            "source-partial-year",
            state="done",
            result={
                "stats": {
                    "annual_energy_by_year": [
                        {
                            "year": 2023,
                            "coverage_status": "incomplete_source",
                            "complete_calendar_year": True,
                            "cdf_eligible": False,
                        }
                    ]
                }
            },
        )

        summaries = chat._recent_run_context("annual")

        self.assertEqual(0, summaries[0]["metrics"]["full_year_count"])

    def test_recent_run_context_keeps_a_twelve_member_sweep_atomic(self) -> None:
        for index in range(12):
            job_id = f"sweep-member-{index:02d}"
            state.AGENT_STORE.create_job(
                job_id=job_id,
                kind="scenario",
                mode="annual",
                request={"years": [2024], "interval_value": 1, "interval_unit": "hours"},
                provenance={
                    "scenario_sweep": {
                        "type": "parameter_sweep",
                        "sweep_id": "sweep-twelve",
                        "parameter": "curtailment_limit_kw",
                        "candidate_count": 12,
                        "index": index,
                        "value": 100 + index,
                    }
                },
            )
            claimed = state.AGENT_STORE.claim_next_queued_job()
            self.assertEqual(job_id, claimed["id"])
            state.AGENT_STORE.update_job(
                job_id,
                state="done",
                result={"stats": {"se_predicted_kwh": 1_000 + index}},
            )

        only_recent_member = state.AGENT_STORE.get_job("sweep-member-00")
        with patch.object(
            state.AGENT_STORE,
            "snapshot_state",
            return_value={"recent_jobs": [only_recent_member]},
        ):
            summaries = chat._recent_run_context("annual")

        self.assertEqual(1, len(summaries))
        sweep = summaries[0]
        self.assertEqual("parameter_sweep", sweep["activity_type"])
        self.assertEqual("done", sweep["state"])
        self.assertEqual(12, sweep["candidate_count"])
        self.assertEqual(12, sweep["loaded_member_count"])
        self.assertEqual(list(range(12)), [row["index"] for row in sweep["members"]])

    def test_recent_run_context_includes_both_dashboard_workflows(self) -> None:
        for mode in ("validation", "annual"):
            job_id = f"recent-{mode}"
            request = (
                self.validation_config()
                if mode == "validation"
                else {"years": [2024], "from_date": "2024-01-01", "to_date": "2024-12-31"}
            )
            state.AGENT_STORE.create_job(
                job_id=job_id,
                kind="baseline",
                mode=mode,
                request=request,
            )
            state.AGENT_STORE.claim_next_queued_job()
            state.AGENT_STORE.update_job(job_id, state="done", result={"stats": {}})

        summaries = chat._recent_run_context("annual")

        self.assertEqual({"validation", "annual"}, {row["mode"] for row in summaries})

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

        with patch.object(config, "MAX_ACTIVE_MODEL_JOBS", 1):
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
        self.assertIsNone(state.AGENT_STORE.get_job("queue-overflow"))

    def test_annual_year_override_is_canonical_and_changes_input_identity(self) -> None:
        baseline = {
            "from_date": "2025-01-01",
            "to_date": "2025-12-31",
            "years": None,
            "interval_value": 1,
            "interval_unit": "hours",
        }
        overrides = scenario_math._apply_dependent_scenario_overrides(
            {"years": [2024, 2011]}, baseline
        )
        candidate_values = {**baseline, **overrides}

        _, candidate = scenario_math._canonical_request("annual", candidate_values)

        self.assertEqual(candidate["years"], [2011, 2024])
        self.assertEqual(candidate["from_date"], "2011-02-11")
        self.assertEqual(candidate["to_date"], "2024-12-31")
        self.assertFalse(
            scenario_math._same_input_context("annual", baseline, candidate)
        )

    def test_coarse_annual_interval_is_rejected_before_agent_proposal(self) -> None:
        baseline = self.completed_baseline(mode="annual", reviewed=False)

        with self.assertRaises(HTTPException) as error:
            tools._handle_scenario_tool(
                app.ChatRequest(
                    message="Run annual simulation at 24-hour resolution.",
                    job_id=baseline["id"],
                    active_mode="annual",
                    current_config=baseline["request"],
                ),
                self.tool_arguments(interval_value=24, interval_unit="hours"),
            )

        self.assertEqual(error.exception.status_code, 422)
        self.assertIn("1 hour", str(error.exception.detail))
        self.assertEqual(state.AGENT_STORE.list_proposals(), [])
        self.assertEqual(state.AGENT_STORE.list_jobs(), [baseline])

    def test_coarse_annual_interval_is_revalidated_at_agent_confirmation(self) -> None:
        baseline = self.completed_baseline(mode="annual", reviewed=False)
        proposal = state.AGENT_STORE.create_proposal(
            mode="annual",
            effective_request={
                **baseline["request"],
                "interval_value": 24,
                "interval_unit": "hours",
            },
            changes=[
                {
                    "field": "interval_value",
                    "label": "Interval value",
                    "from": 1,
                    "to": 24,
                }
            ],
            baseline_id=baseline["id"],
            comparison_kind="cross_run",
            confirmation_required=True,
            confirmation_reason="Annual scenarios always require confirmation",
        )

        with self.assertRaises(HTTPException) as error:
            app.confirm_agent_proposal(proposal["id"])

        self.assertEqual(error.exception.status_code, 422)
        self.assertIn("1 hour", str(error.exception.detail))
        self.assertEqual(
            state.AGENT_STORE.get_proposal(proposal["id"])["state"],
            "pending",
        )
        self.assertEqual(state.AGENT_STORE.list_jobs(), [baseline])

    def test_legacy_annual_baseline_cannot_create_agent_scenario(self) -> None:
        baseline = self.completed_baseline(
            mode="annual",
            reviewed=False,
            include_annual_temporal_semantics=False,
        )

        with self.assertRaises(HTTPException) as error:
            tools._handle_scenario_tool(
                app.ChatRequest(
                    message="Turn annual backtracking off.",
                    job_id=baseline["id"],
                    active_mode="annual",
                    current_config=baseline["request"],
                ),
                self.tool_arguments(backtrack=False),
            )

        self.assertEqual(error.exception.status_code, 409)
        self.assertIn("fresh Annual baseline", str(error.exception.detail))
        self.assertEqual(state.AGENT_STORE.list_proposals(), [])
        self.assertEqual(state.AGENT_STORE.list_jobs(), [baseline])

    def test_mismatched_annual_semantics_cannot_create_agent_scenario(self) -> None:
        baseline = self.completed_baseline(mode="annual", reviewed=False)
        stale_result = dict(baseline["result"])
        stale_result["stats"] = {
            **dict(stale_result["stats"]),
            "annual_temporal_semantics_fingerprint": "0" * 64,
        }
        baseline = state.AGENT_STORE.update_job(
            baseline["id"],
            result=stale_result,
        )

        with self.assertRaises(HTTPException) as error:
            tools._handle_scenario_tool(
                app.ChatRequest(
                    message="Turn annual backtracking off.",
                    job_id=baseline["id"],
                    active_mode="annual",
                    current_config=baseline["request"],
                ),
                self.tool_arguments(backtrack=False),
            )

        self.assertEqual(error.exception.status_code, 409)
        self.assertIn("incompatible", str(error.exception.detail))
        self.assertEqual(state.AGENT_STORE.list_proposals(), [])
        self.assertEqual(state.AGENT_STORE.list_jobs(), [baseline])

    def test_legacy_annual_proposal_is_revalidated_at_confirmation(self) -> None:
        baseline = self.completed_baseline(
            mode="annual",
            reviewed=False,
            include_annual_temporal_semantics=False,
        )
        proposal = state.AGENT_STORE.create_proposal(
            mode="annual",
            effective_request={**baseline["request"], "backtrack": False},
            changes=[
                {
                    "field": "backtrack",
                    "label": "Backtracking",
                    "from": True,
                    "to": False,
                }
            ],
            baseline_id=baseline["id"],
            comparison_kind="same_input",
            confirmation_required=True,
            confirmation_reason="Annual scenarios always require confirmation",
        )

        with self.assertRaises(HTTPException) as error:
            app.confirm_agent_proposal(proposal["id"])

        self.assertEqual(error.exception.status_code, 409)
        self.assertIn("fresh Annual baseline", str(error.exception.detail))
        self.assertEqual(
            state.AGENT_STORE.get_proposal(proposal["id"])["state"],
            "pending",
        )
        self.assertEqual(state.AGENT_STORE.list_jobs(), [baseline])

    def test_annual_canonicalization_rejects_forged_partial_selected_year(self) -> None:
        forged = {
            "years": [2024],
            "from_date": "2024-01-01",
            "to_date": "2024-01-02",
        }

        with self.assertRaises(HTTPException):
            scenario_math._canonical_request("annual", forged)

        _, durable = scenario_math._canonical_request(
            "annual",
            forged,
            allow_resolved_partial=True,
        )
        self.assertEqual(durable["to_date"], "2024-01-02")

    def test_missing_baseline_cannot_defer_forged_partial_selected_year(self) -> None:
        with self.assertRaises(HTTPException):
            tools._handle_scenario_tool(
                app.ChatRequest(
                    message="Turn backtracking off.",
                    active_mode="annual",
                    current_config={
                        "years": [2024],
                        "from_date": "2024-01-01",
                        "to_date": "2024-01-02",
                    },
                ),
                self.tool_arguments(backtrack=False),
            )

        self.assertEqual(state.AGENT_STORE.list_proposals(), [])
        self.assertEqual(state.AGENT_STORE.list_jobs(), [])

    def test_annual_year_and_date_overrides_are_mutually_exclusive(self) -> None:
        with self.assertRaises(HTTPException) as context:
            scenario_math._apply_dependent_scenario_overrides(
                {"years": [2024], "from_date": "2024-01-01"},
                {"from_date": "2025-01-01", "to_date": "2025-12-31"},
            )

        self.assertEqual(context.exception.status_code, 422)
        self.assertIn("cannot be combined", str(context.exception.detail))

    def test_legacy_annual_date_override_clears_selected_years(self) -> None:
        baseline = {
            "years": [2024],
            "from_date": "2024-01-01",
            "to_date": "2024-12-31",
        }

        overrides = scenario_math._apply_dependent_scenario_overrides(
            {"from_date": "2025-01-01", "to_date": "2025-12-31"}, baseline
        )

        self.assertIsNone(overrides["years"])

    def test_validation_canonicalization_drops_inherited_annual_years(self) -> None:
        request, candidate = scenario_math._canonical_request(
            "validation",
            self.validation_config(years=[2024]),
        )

        self.assertIsInstance(request, app.RunRequest)
        self.assertNotIn("years", candidate)
        self.assertEqual(candidate["from_date"], "2026-06-20")

    def test_validation_scenario_rejects_explicit_midc_years(self) -> None:
        baseline = self.completed_baseline()

        with self.assertRaises(HTTPException) as context:
            tools._handle_scenario_tool(
                app.ChatRequest(
                    message="Use MIDC year 2024 for validation.",
                    job_id=baseline["id"],
                    active_mode="validation",
                    current_config=self.validation_config(),
                ),
                self.tool_arguments(years=[2024]),
            )

        self.assertEqual(context.exception.status_code, 422)
        self.assertIn("only be changed for annual", str(context.exception.detail))

    def test_scenario_tool_years_schema_is_strict_compatible_integer_array(self) -> None:
        years = app.SCENARIO_TOOL["parameters"]["properties"]["years"]

        self.assertEqual(years["type"], ["array", "null"])
        self.assertEqual(years["items"], {"type": "integer", "minimum": 2011})
        self.assertNotIn("uniqueItems", years)
        self.assertEqual(app.SCENARIO_FIELD_LABELS["years"], "MIDC years")

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
            result = chat._openai_agent_response(
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
        candidate = state.AGENT_STORE.get_job(result["action"]["job"]["job_id"])
        self.assertEqual(candidate["baseline_id"], baseline["id"])
        self.assertEqual(candidate["request"]["backtrack"], False)

    def test_iam_ar_sweep_queues_exact_controlled_values(self) -> None:
        baseline = self.completed_baseline()

        with patch.object(
            state.AGENT_STORE,
            "confirm_proposals_batch",
            wraps=state.AGENT_STORE.confirm_proposals_batch,
        ) as batch_confirm:
            tool_result, action = tools._handle_iam_ar_sweep_tool(
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
            (state.AGENT_STORE.get_job(item["job_id"]) for item in action["jobs"]),
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
            result = chat._openai_agent_response(
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

        _, action = tools._handle_parameter_sweep_tool(
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

        _, action = tools._handle_parameter_sweep_tool(
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

        tool_result, action = tools._handle_iam_ar_sweep_tool(
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

        tool_result, action = tools._handle_iam_ar_sweep_tool(
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
        self.assertEqual([], state.AGENT_STORE.list_jobs(kind="candidate"))
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
        baseline = state.AGENT_STORE.update_job(
            baseline["id"],
            provenance=calibration,
        )

        _, action = tools._handle_iam_ar_sweep_tool(
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
            candidate = state.AGENT_STORE.get_job(item["job_id"])
            self.assertEqual(
                calibration["calibration_profile"],
                candidate["provenance"]["calibration_profile"],
            )
            expected_deltas = app._calibration_setting_deltas(
                baselines._baseline_transferable_settings(calibration_baseline),
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

    def test_same_input_annual_candidate_inherits_verified_source_audit(self) -> None:
        baseline = self.completed_baseline(mode="annual", reviewed=False)
        audit = {
            "schema_version": 2,
            "source_sha256": baseline["source_hash"],
            "interval_seconds": 3_600,
            "source_quality": {
                "interval_seconds": 3_600,
                "partial_interval_count": 2,
                "periods": [],
            },
            "warnings": ["MIDC source contains two partial intervals."],
        }
        baseline = state.AGENT_STORE.update_job(
            baseline["id"],
            provenance={"annual_source_audit": audit},
        )

        _, action = tools._handle_scenario_tool(
            app.ChatRequest(
                message="Turn annual backtracking off.",
                job_id=baseline["id"],
                active_mode="annual",
                current_config=baseline["request"],
            ),
            self.tool_arguments(backtrack=False),
        )
        response = app.confirm_agent_proposal(
            action["proposal"]["proposal_id"]
        )

        payload = json.loads(response.body)
        candidate = state.AGENT_STORE.get_job(payload["job"]["job_id"])
        self.assertEqual(
            audit,
            candidate["provenance"]["annual_source_audit"],
        )

    def test_same_input_annual_candidate_rejects_unbound_source_audit(self) -> None:
        baseline = self.completed_baseline(mode="annual", reviewed=False)
        baseline = state.AGENT_STORE.update_job(
            baseline["id"],
            provenance={
                "annual_source_audit": {
                    "schema_version": 2,
                    "source_sha256": "0" * 64,
                    "interval_seconds": 3_600,
                    "source_quality": {"periods": []},
                    "warnings": ["This warning belongs to different bytes."],
                }
            },
        )

        _, action = tools._handle_scenario_tool(
            app.ChatRequest(
                message="Turn annual backtracking off.",
                job_id=baseline["id"],
                active_mode="annual",
                current_config=baseline["request"],
            ),
            self.tool_arguments(backtrack=False),
        )
        response = app.confirm_agent_proposal(
            action["proposal"]["proposal_id"]
        )

        payload = json.loads(response.body)
        candidate = state.AGENT_STORE.get_job(payload["job"]["job_id"])
        self.assertNotIn("annual_source_audit", candidate["provenance"] or {})

    def test_tampered_annual_calibration_provenance_blocks_confirmation(self) -> None:
        calibration_baseline = self.completed_baseline(
            job_id="tampered-annual-calibration"
        )
        baseline = self.completed_baseline(mode="annual", reviewed=False)
        calibration = self.annual_calibration_provenance(calibration_baseline)
        calibration["calibration_application"]["resolved_profile_sha256"] = "0" * 64
        baseline = state.AGENT_STORE.update_job(
            baseline["id"],
            provenance=calibration,
        )

        _, action = tools._handle_scenario_tool(
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
        self.assertEqual([], state.AGENT_STORE.list_jobs(kind="candidate"))

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
        baseline = state.AGENT_STORE.update_job(
            baseline["id"],
            provenance=calibration,
        )

        _, action = tools._handle_scenario_tool(
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
        self.assertEqual([], state.AGENT_STORE.list_jobs(kind="candidate"))

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
        baseline = state.AGENT_STORE.update_job(
            baseline["id"],
            provenance=calibration,
        )

        _, action = tools._handle_scenario_tool(
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
        self.assertEqual([], state.AGENT_STORE.list_jobs(kind="candidate"))

    def test_annual_sweep_confirmation_is_all_or_nothing_near_capacity(self) -> None:
        baseline = self.completed_baseline(mode="annual", reviewed=False)
        _, action = tools._handle_iam_ar_sweep_tool(
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
        active = state.AGENT_STORE.create_job(
            job_id="annual-sweep-active",
            kind="manual",
            mode="annual",
            request=baseline["request"],
        )
        request = app.ProposalSweepConfirmRequest(proposal_ids=proposal_ids)

        with patch.object(config, "MAX_ACTIVE_MODEL_JOBS", 3):
            with self.assertRaises(HTTPException) as capacity_error:
                app.confirm_agent_sweep(sweep_id, request)
        self.assertEqual(429, capacity_error.exception.status_code)
        self.assertEqual([], state.AGENT_STORE.list_jobs(kind="candidate"))
        self.assertTrue(
            all(
                state.AGENT_STORE.get_proposal(proposal_id)["state"] == "pending"
                for proposal_id in proposal_ids
            )
        )

        with self.assertRaises(HTTPException) as single_error:
            app.confirm_agent_proposal(proposal_ids[0])
        self.assertEqual(409, single_error.exception.status_code)
        self.assertEqual([], state.AGENT_STORE.list_jobs(kind="candidate"))

        state.AGENT_STORE.cancel_job(active["id"])
        with patch.object(config, "MAX_ACTIVE_MODEL_JOBS", 3):
            response = app.confirm_agent_sweep(sweep_id, request)
        payload = json.loads(response.body)
        self.assertEqual("job_batch_started", payload["action"]["type"])
        self.assertEqual(3, len(payload["action"]["jobs"]))
        self.assertTrue(
            all(
                state.AGENT_STORE.get_proposal(proposal_id)["state"] == "confirmed"
                for proposal_id in proposal_ids
            )
        )

    def test_missing_validation_baseline_requires_visible_data_review(self) -> None:
        tool_result, action = tools._handle_scenario_tool(
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
        self.assertEqual(state.AGENT_STORE.list_proposals(), [])
        self.assertEqual(state.AGENT_STORE.list_jobs(), [])

    def test_verified_same_input_auto_start_reuses_hash_and_never_fetches(self) -> None:
        baseline = self.completed_baseline()
        _, action = tools._handle_scenario_tool(
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
        candidate = state.AGENT_STORE.get_job(job_id)
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

        claimed = state.AGENT_STORE.claim_next_queued_job()
        self.assertEqual(claimed["id"], job_id)
        with (
            patch.object(
                app.historian,
                "run_historian",
                side_effect=AssertionError("cached scenarios must not fetch Bazefield"),
            ) as historian_call,
            patch.object(plots, "_render_input_data_plots", return_value={}),
            patch.object(
                app.model,
                "run_model",
                return_value={
                    "ac_png": str(self.root / "candidate_ac.png"),
                    "energy_png": str(self.root / "candidate_energy.png"),
                    "excel": str(self.root / "candidate.xlsx"),
                },
            ) as model_call,
            patch.object(completion, "_finish_model_job") as finish_call,
        ):
            run_validation._run_job(
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
        tool_result, action = tools._handle_scenario_tool(
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
        self.assertEqual(state.AGENT_STORE.list_jobs(kind="candidate"), [])
        self.assertEqual(state.AGENT_STORE.list_proposals(), [])
        self.assertEqual(
            state.AGENT_STORE.get_current_baseline("validation")["job_id"],
            baseline["id"],
        )

    def test_same_input_unreviewed_baseline_requires_visible_review(self) -> None:
        baseline = self.completed_baseline(reviewed=False)

        tool_result, action = tools._handle_scenario_tool(
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
        self.assertEqual(state.AGENT_STORE.list_jobs(kind="candidate"), [])
        self.assertEqual(state.AGENT_STORE.list_proposals(), [])

    def test_promoted_same_input_scenario_reuses_original_profile(self) -> None:
        original = self.completed_baseline()
        _, first_action = tools._handle_scenario_tool(
            app.ChatRequest(
                message="Turn backtracking off.",
                job_id=original["id"],
                active_mode="validation",
                current_config=self.validation_config(),
            ),
            self.tool_arguments(backtrack=False),
        )
        first_id = first_action["job"]["job_id"]
        claimed = state.AGENT_STORE.claim_next_queued_job()
        self.assertEqual(claimed["id"], first_id)
        state.AGENT_STORE.update_job(
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

        promoted = state.AGENT_STORE.get_job(first_id)
        _, second_action = tools._handle_scenario_tool(
            app.ChatRequest(
                message="Use 95 percent SolarEdge inverter efficiency.",
                job_id=first_id,
                active_mode="validation",
                current_config=promoted["request"],
            ),
            self.tool_arguments(solaredge_inverter_efficiency=0.95),
        )
        second = state.AGENT_STORE.get_job(
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
        state.AGENT_STORE.update_job(
            baseline["id"],
            result={
                **result,
                "calibration_factors": summer_only,
            },
        )

        with self.assertRaises(HTTPException) as context:
            tools._handle_scenario_tool(
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
            state.AGENT_STORE.list_jobs(kind="candidate"),
            [],
        )

    def test_fresh_validation_window_does_not_queue_behind_active_job(
        self,
    ) -> None:
        baseline = self.completed_baseline()
        active = state.AGENT_STORE.create_job(
            job_id="already-running",
            kind="candidate",
            mode="validation",
            request=self.validation_config(backtrack=False),
            baseline_id=baseline["id"],
        )
        claimed = state.AGENT_STORE.claim_next_queued_job()
        self.assertEqual(claimed["id"], active["id"])

        tool_result, action = tools._handle_scenario_tool(
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
            [job["id"] for job in state.AGENT_STORE.list_jobs(kind="candidate")],
            [active["id"]],
        )
        self.assertEqual(state.AGENT_STORE.list_proposals(), [])

    def test_cross_run_validation_proposal_cannot_be_confirmed(
        self,
    ) -> None:
        baseline = self.completed_baseline()
        _, candidate = scenario_math._canonical_request(
            "validation",
            self.validation_config(
                from_date="2026-06-01",
                from_time="00:00",
                to_date="2026-06-08",
                to_time="00:00",
            ),
        )
        proposal = state.AGENT_STORE.create_proposal(
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
            proposals._confirm_durable_proposal(proposal)

        self.assertEqual(context.exception.status_code, 409)
        self.assertIn("visible Calibration", str(context.exception.detail))
        self.assertEqual(state.AGENT_STORE.list_jobs(kind="candidate"), [])

    def test_unreviewed_validation_candidate_cannot_be_promoted(self) -> None:
        baseline = self.completed_baseline()
        candidate = state.AGENT_STORE.create_job(
            job_id="unreviewed-candidate",
            kind="candidate",
            mode="validation",
            request=self.validation_config(backtrack=False),
            baseline_id=baseline["id"],
            source_path=baseline["source_path"],
            source_hash=baseline["source_hash"],
            provenance={"calibration_profile": {"schema_version": 1}},
        )
        claimed = state.AGENT_STORE.claim_next_queued_job()
        self.assertEqual(claimed["id"], candidate["id"])
        state.AGENT_STORE.update_job(
            candidate["id"],
            state="done",
            result={"mode": "validation", "stats": {}},
        )

        with self.assertRaises(HTTPException) as context:
            app.promote_model_job(candidate["id"])

        self.assertEqual(context.exception.status_code, 409)
        self.assertIn("hash-verified data-quality review", context.exception.detail)
        self.assertEqual(
            state.AGENT_STORE.get_current_baseline("validation")["job_id"],
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

        _, action = tools._handle_scenario_tool(
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
        state.AGENT_STORE.update_job(
            annual["id"],
            comparison={
                "comparison_type": "cross_run",
                "systems": {"solaredge": {"delta_kwh": 12.5}},
            },
            provenance={
                "comparability": "non-like-for-like",
                "baseline": {
                    "workbook": str(self.root / "private-baseline.xlsx")
                },
            },
            artifacts={
                "comparison_workbook": {
                    "path": str(self.root / "private-annual-compare.xlsx"),
                    "url": "/outputs/annual-compare.xlsx",
                }
            },
        )

        resolved, context = chat._chat_run_context(None, "annual")

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
        self.assertNotIn("path", context["artifacts"]["comparison_workbook"])
        self.assertNotIn("workbook", context["provenance"]["baseline"])

    def test_failed_chat_context_never_sends_local_paths_to_openai(self) -> None:
        private_errors = (
            r"Failed opening C:\Users\Alice\private.csv",
            "Failed opening /var/data/outputs/private.csv",
            r"Failed opening \\fileserver\pv\private.csv",
        )
        for index, private_error in enumerate(private_errors):
            job_id = f"private-error-{index}"
            state.AGENT_STORE.create_job(
                job_id=job_id,
                kind="baseline",
                mode="validation",
                request=self.validation_config(),
            )
            state.AGENT_STORE.claim_next_queued_job()
            state.AGENT_STORE.update_job(job_id, state="error", error=private_error)

            resolved, context = chat._chat_run_context(job_id, "validation")

            self.assertEqual(job_id, resolved)
            self.assertEqual(
                "The run could not be completed. Check the server logs for details.",
                context["error"],
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
            result = chat._openai_agent_response(
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
        self.assertEqual(state.AGENT_STORE.list_proposals(), [])
        self.assertEqual(state.AGENT_STORE.list_jobs(), [])


if __name__ == "__main__":
    unittest.main()
