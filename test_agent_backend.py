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
from agent_store import AgentStore
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
    ) -> dict:
        if request is None:
            request = self.validation_config()
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
        created = app.AGENT_STORE.create_job(
            job_id=job_id,
            kind="baseline",
            mode=mode,
            request=canonical,
        )
        claimed = app.AGENT_STORE.claim_next_queued_job()
        self.assertEqual(created["id"], claimed["id"])
        completed = app.AGENT_STORE.update_job(
            job_id,
            state="done",
            progress=100,
            stage="Done",
            source_path=str(source.resolve()),
            source_hash=sha256_file(source),
            result={"mode": mode, "stats": {}},
            artifacts={},
        )
        app.AGENT_STORE.promote_job(job_id)
        return completed

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

    def test_strict_tool_schema_and_two_step_function_output_loop(self) -> None:
        baseline = self.completed_baseline()
        call = {
            "type": "function_call",
            "name": "propose_model_scenario",
            "call_id": "call-scenario-1",
            "arguments": json.dumps(self.tool_arguments(backtrack=False)),
        }
        responses = [
            types.SimpleNamespace(output=[call], output_text=""),
            types.SimpleNamespace(output=[], output_text="Scenario queued from verified data."),
        ]
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

        self.assertEqual(len(api_calls), 2)
        self.assertIn(app.SCENARIO_TOOL, api_calls[0]["tools"])
        self.assertNotIn("tools", api_calls[1])
        function_outputs = [
            item
            for item in api_calls[1]["input"]
            if isinstance(item, dict) and item.get("type") == "function_call_output"
        ]
        self.assertEqual(len(function_outputs), 1)
        self.assertEqual(function_outputs[0]["call_id"], "call-scenario-1")
        deterministic_output = json.loads(function_outputs[0]["output"])
        self.assertEqual(deterministic_output["status"], "started")

        self.assertEqual(result["reply"], "Scenario queued from verified data.")
        self.assertEqual(result["action"]["type"], "job_started")
        candidate = app.AGENT_STORE.get_job(result["action"]["job"]["job_id"])
        self.assertEqual(candidate["baseline_id"], baseline["id"])
        self.assertEqual(candidate["request"]["backtrack"], False)

    def test_missing_baseline_creates_run_baseline_proposal_not_scenario(self) -> None:
        tool_result, action = app._handle_scenario_tool(
            app.ChatRequest(
                message="Use Martin-Ruiz a_r 0.80",
                active_mode="validation",
                current_config=self.validation_config(),
            ),
            self.tool_arguments(iam_model="martin_ruiz", iam_a_r=0.8),
        )

        proposal = action["proposal"]
        durable = app.AGENT_STORE.get_proposal(proposal["proposal_id"])
        self.assertEqual(tool_result["status"], "baseline_required")
        self.assertEqual(action["type"], "proposal")
        self.assertEqual(proposal["kind"], "baseline")
        self.assertTrue(proposal["confirmation_required"])
        self.assertEqual(proposal["changes"], [])
        self.assertEqual(proposal["effective_request"]["iam_model"], "physical")
        self.assertIsNone(proposal["effective_request"]["iam_a_r"])
        self.assertEqual(
            durable["confirmation_metadata"]["deferred_scenario_overrides"],
            {"iam_model": "martin_ruiz", "iam_a_r": 0.8},
        )
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
            )

        historian_call.assert_not_called()
        self.assertEqual(
            Path(model_call.call_args.kwargs["input_csv"]).resolve(),
            Path(baseline["source_path"]).resolve(),
        )
        finish_call.assert_called_once()

    def test_fresh_validation_window_auto_starts_and_is_cancelable_and_promotable(
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

        self.assertEqual(tool_result["status"], "started")
        self.assertIn("pull fresh data from Bazefield", tool_result["message"])
        self.assertEqual(action["type"], "job_started")
        first = action["job"]
        candidates = app.AGENT_STORE.list_jobs(kind="candidate")
        self.assertEqual(len(candidates), 1)
        self.assertIsNone(candidates[0]["source_path"])
        self.assertIsNone(candidates[0]["source_hash"])
        self.assertEqual(candidates[0]["baseline_id"], baseline["id"])
        self.assertEqual(candidates[0]["request"]["from_date"], "2026-06-01")
        self.assertEqual(candidates[0]["request"]["to_date"], "2026-06-08")
        self.assertEqual(candidates[0]["request"]["iam_model"], "physical")
        self.assertIsNone(candidates[0]["request"]["iam_a_r"])
        proposal = app.AGENT_STORE.get_proposal(candidates[0]["proposal_id"])
        self.assertEqual(proposal["state"], "confirmed")
        self.assertEqual(proposal["comparison_kind"], "cross_run")
        self.assertFalse(proposal["confirmation_required"])
        self.assertIn(
            "fresh bazefield data", proposal["confirmation_reason"].lower()
        )

        cancelled = json.loads(
            app.cancel_model_job(first["job_id"]).body.decode("utf-8")
        )["job"]
        self.assertEqual(cancelled["state"], "cancelled")
        self.assertTrue(cancelled["cancel_requested"])
        with self.assertRaises(HTTPException) as context:
            app.promote_model_job(first["job_id"])
        self.assertEqual(context.exception.status_code, 409)

        app.retry_model_job(first["job_id"])
        claimed = app.AGENT_STORE.claim_next_queued_job()
        self.assertEqual(claimed["id"], first["job_id"])
        app.AGENT_STORE.update_job(
            first["job_id"],
            state="done",
            progress=100,
            stage="Done",
            result={"mode": "validation", "stats": {"marker": "candidate"}},
            comparison={"comparison_type": "cross_run"},
            provenance={"warning": "non-like-for-like"},
            artifacts={"comparison_workbook": {"url": "/outputs/compare.xlsx"}},
        )
        promoted = json.loads(
            app.promote_model_job(first["job_id"]).body.decode("utf-8")
        )
        self.assertEqual(promoted["job_id"], first["job_id"])
        self.assertEqual(
            app.AGENT_STORE.get_current_baseline("validation")["job_id"],
            first["job_id"],
        )

    def test_fresh_validation_window_queues_behind_active_job_without_confirmation(
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

        self.assertEqual(tool_result["status"], "started")
        self.assertEqual(action["type"], "job_started")
        queued = app.AGENT_STORE.get_job(action["job"]["job_id"])
        self.assertEqual(queued["state"], "queued")
        proposal = app.AGENT_STORE.get_proposal(queued["proposal_id"])
        self.assertFalse(proposal["confirmation_required"])
        self.assertIn("remain queued", proposal["confirmation_reason"])

    def test_fresh_validation_worker_pulls_bazefield_and_builds_comparison(
        self,
    ) -> None:
        baseline = self.completed_baseline()
        _, action = app._handle_scenario_tool(
            app.ChatRequest(
                message="Run June 1-7 using Bazefield with physical IAM.",
                job_id=baseline["id"],
                active_mode="validation",
                current_config=self.validation_config(),
            ),
            self.tool_arguments(
                from_date="2026-06-01",
                from_time="00:00",
                to_date="2026-06-08",
                to_time="00:00",
                iam_model="physical",
            ),
        )
        job_id = action["job"]["job_id"]
        claimed = app.AGENT_STORE.claim_next_queued_job()
        self.assertEqual(claimed["id"], job_id)

        output_root = app.OUTPUT_DIR
        source_csv = output_root / f"{job_id}.csv"
        self.generated_files.append(source_csv)
        baseline_workbook = output_root / f"{job_id}-baseline.xlsx"
        app.AGENT_STORE.update_job(
            baseline["id"],
            result={
                "mode": "validation",
                "stats": {"excel": str(baseline_workbook)},
            },
        )

        def fake_historian(**kwargs):
            Path(kwargs["output_csv"]).write_text(
                "timestamp,solaredge_measured_power,solectria_measured_power,"
                "dni,ghi,dhi,temp_air,wind_speed\n"
                "2026-06-01 06:00:00,1000,900,700,500,100,25,2\n",
                encoding="utf-8",
            )
            return 168

        model_result = {
            "ac_png": str(output_root / "candidate_ac.png"),
            "energy_png": str(output_root / "candidate_energy.png"),
            "excel": str(output_root / "candidate.xlsx"),
        }
        generated_comparison = {
            "comparison": {
                "comparison_type": "cross_run",
                "attribution": {"scope": "descriptive_only"},
            },
            "provenance": {"comparability": "non-like-for-like"},
            "artifacts": {
                "comparison_workbook": {"url": "/outputs/comparison.xlsx"}
            },
        }

        with (
            patch.object(
                app.historian, "run_historian", side_effect=fake_historian
            ) as historian_call,
            patch.object(app, "_render_input_data_plots", return_value={}),
            patch.object(
                app.model, "run_model", return_value=model_result
            ) as model_call,
            patch.object(
                app,
                "generate_comparison_artifacts",
                return_value=generated_comparison,
            ) as comparison_call,
        ):
            app._run_job(job_id, app.RunRequest(**claimed["request"]))

        historian_call.assert_called_once_with(
            from_time="2026-06-01T06:00:00",
            to_time="2026-06-08T06:00:00",
            interval="3600",
            output_csv=str(source_csv),
        )
        self.assertEqual(model_call.call_args.kwargs["iam_model"], "physical")
        self.assertIsNone(model_call.call_args.kwargs["iam_a_r"])
        self.assertEqual(
            Path(model_call.call_args.kwargs["input_csv"]),
            source_csv,
        )

        comparison_call.assert_called_once()
        comparison_kwargs = comparison_call.call_args.kwargs
        self.assertEqual(comparison_kwargs["comparison_type"], "cross_run")
        self.assertEqual(comparison_kwargs["baseline_job_id"], baseline["id"])
        self.assertEqual(comparison_kwargs["candidate_job_id"], job_id)
        self.assertEqual(
            Path(comparison_kwargs["candidate_source_path"]),
            source_csv,
        )
        self.assertTrue(comparison_kwargs["candidate_source_sha256"])
        self.assertNotEqual(
            comparison_kwargs["candidate_source_sha256"],
            comparison_kwargs["baseline_source_sha256"],
        )

        finished = app.AGENT_STORE.get_job(job_id)
        self.assertEqual(finished["state"], "done")
        self.assertEqual(
            finished["comparison"]["comparison_type"], "cross_run"
        )
        self.assertEqual(
            finished["comparison"]["attribution"]["scope"],
            "descriptive_only",
        )
        self.assertEqual(
            finished["provenance"]["comparability"], "non-like-for-like"
        )

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
