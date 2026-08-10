import base64
from datetime import datetime
import os
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient
from sbepv.api import config, job_store, plots, state
from sbepv.agent import chat
from sbepv.api import main as app


class ChatBackendTests(unittest.TestCase):
    def setUp(self):
        os.environ["OPENAI_API_KEY"] = "test-placeholder"
        state.JOBS.clear()
        self.calls = []

        fake_client = types.SimpleNamespace(
            responses=types.SimpleNamespace(
                create=lambda **kwargs: (
                    self.calls.append(kwargs)
                    or types.SimpleNamespace(output_text="mock reply")
                )
            )
        )
        sys.modules["openai"] = types.SimpleNamespace(OpenAI=lambda: fake_client)

    def assert_chat_timing_contract(self, timing):
        self.assertIsInstance(timing, dict)
        parsed_timestamp = datetime.fromisoformat(
            timing["response_timestamp"].replace("Z", "+00:00")
        )
        self.assertIsNotNone(parsed_timestamp.tzinfo)
        self.assertIsInstance(timing["gpt_seconds"], (int, float))
        self.assertGreaterEqual(timing["gpt_seconds"], 0)
        self.assertIn("model_run_seconds", timing)
        self.assertIn("model_run_status", timing)

    def test_completed_run_context_is_sent_without_secrets(self):
        state.JOBS["job123"] = {
            "state": "done",
            "progress": 100,
            "stage": "Done",
            "request": {"from_date": "2026-06-20"},
            "result": {
                "stats": {
                    "se_predicted_kwh": 1.0,
                    "sol_predicted_kwh": 2.0,
                    "se_pct": 3.0,
                    "sol_pct": 4.0,
                },
                "window": {"from": "2026-06-20T00:00:00"},
                "ac_png": "/outputs/ac.png",
                "energy_png": "/outputs/energy.png",
                "excel": "/outputs/run.xlsx",
            },
        }

        reply, job_id, web_enabled = chat._openai_chat_response(
            app.ChatRequest(message="Summarize this run.", job_id="job123")
        )

        self.assertEqual(reply, "mock reply")
        self.assertEqual(job_id, "job123")
        self.assertFalse(web_enabled)
        input_text = self.calls[0]["input"][0]["content"]
        self.assertIn("dashboard_run_context", input_text)
        self.assertIn("se_predicted_kwh", input_text)
        self.assertNotIn("OPENAI_API_KEY", input_text)
        self.assertIn("Performance Summary", self.calls[0]["instructions"])
        self.assertIn("SolarEdge", self.calls[0]["instructions"])
        self.assertIn("Solectria", self.calls[0]["instructions"])
        self.assertIn("stay under 90 words", self.calls[0]["instructions"])
        self.assertEqual(1_200, self.calls[0]["max_output_tokens"])

    def test_reference_question_enables_web_search(self):
        state.JOBS["job123"] = {"state": "done", "result": {"stats": {}}}

        _, _, web_enabled = chat._openai_chat_response(
            app.ChatRequest(message="Give me references for this prediction.", job_id="job123")
        )

        self.assertTrue(web_enabled)
        self.assertIn({"type": "web_search"}, self.calls[0]["tools"])
        self.assertIn(app.SCENARIO_TOOL, self.calls[0]["tools"])

    def test_dashboard_prediction_wording_does_not_enable_web_search(self):
        state.JOBS["job123"] = {"state": "done", "result": {"stats": {}}}

        for message in (
            "Summarize the current run.",
            "Why did this prediction differ from measured energy?",
            "Predict the effect of backtracking from this dashboard result.",
        ):
            with self.subTest(message=message):
                self.calls.clear()
                _, _, web_enabled = chat._openai_chat_response(
                    app.ChatRequest(message=message, job_id="job123")
                )
                self.assertFalse(web_enabled)
                self.assertNotIn({"type": "web_search"}, self.calls[0]["tools"])

    def test_missing_run_still_returns_answerable_context(self):
        reply, job_id, web_enabled = chat._openai_chat_response(
            app.ChatRequest(message="What does the model do?", job_id="missing")
        )

        self.assertEqual(reply, "mock reply")
        self.assertEqual(job_id, "missing")
        self.assertFalse(web_enabled)
        self.assertIn('"state": "missing"', self.calls[0]["input"][0]["content"])

    def test_chat_response_reports_timestamp_gpt_and_completed_model_runtime(self):
        job_id = f"chat-timing-{uuid4().hex}"
        state.JOBS[job_id] = {
            "state": "done",
            "progress": 100,
            "stage": "Done",
            "mode": "validation",
            "started_at": "2026-07-28T12:00:00+00:00",
            "completed_at": "2026-07-28T12:00:12.500000+00:00",
            "request": {"from_date": "2026-06-20"},
            "result": {"stats": {}},
        }

        response = TestClient(app.app).post(
            "/api/chat",
            json={"message": "Summarize this completed run.", "job_id": job_id},
        )

        self.assertEqual(response.status_code, 200)
        timing = response.json()["timing"]
        self.assert_chat_timing_contract(timing)
        self.assertAlmostEqual(timing["model_run_seconds"], 12.5)
        self.assertEqual(timing["model_run_status"], "completed")

    def test_chat_response_without_model_run_reports_null_runtime(self):
        with patch.object(job_store, "_latest_completed_job_id", return_value=None):
            response = TestClient(app.app).post(
                "/api/chat",
                json={"message": "What does the model do?"},
            )

        self.assertEqual(response.status_code, 200)
        timing = response.json()["timing"]
        self.assert_chat_timing_contract(timing)
        self.assertIsNone(timing["model_run_seconds"])
        self.assertEqual(timing["model_run_status"], "not_run")

    def test_physical_iam_is_explicit_even_when_martin_ruiz_coefficient_is_null(self):
        chat._openai_chat_response(
            app.ChatRequest(
                message="Which IAM model is selected?",
                current_config={"iam_model": "physical", "iam_a_r": None},
            )
        )

        input_text = self.calls[0]["input"][0]["content"]
        self.assertIn('"visible_iam_selection"', input_text)
        self.assertIn('"label": "Physical IAM"', input_text)
        self.assertIn('"selected": true', input_text)
        self.assertIn('"iam_a_r_status": "not applicable to Physical IAM"', input_text)
        self.assertIn("Never describe Physical IAM as disabled", self.calls[0]["instructions"])

    def test_current_question_is_not_duplicated_in_recent_history(self):
        chat._openai_chat_response(
            app.ChatRequest(
                message="Summarize this run.",
                history=[
                    app.ChatMessage(role="user", content="Summarize this run.")
                ],
            )
        )

        input_text = self.calls[0]["input"][0]["content"]
        self.assertEqual(1, input_text.count("Summarize this run."))

    def test_input_data_plots_are_rendered_from_historian_csv(self):
        csv_path = config.OUTPUT_DIR / "_test_input_plot.csv"
        measured_path = config.OUTPUT_DIR / "_test_job123_measured_power.png"
        irradiance_path = config.OUTPUT_DIR / "_test_job123_irradiance.png"
        for generated_path in (csv_path, measured_path, irradiance_path):
            self.addCleanup(generated_path.unlink, missing_ok=True)
        csv_path.write_text(
            "\n".join(
                [
                    "timestamp,solaredge_measured_power,solectria_measured_power,dni,ghi,dhi,temp_air,wind_speed",
                    "2026-06-20 00:00:00,1000,2000,700,500,100,25,2",
                    "2026-06-20 01:00:00,1500,2300,800,600,120,26,3",
                ]
            ),
            encoding="utf-8",
        )

        rendered = plots._render_input_data_plots(
            csv_path, config.OUTPUT_DIR / "_test_job123"
        )

        self.assertEqual(rendered["measured_power_png"], "/outputs/_test_job123_measured_power.png")
        self.assertEqual(rendered["irradiance_png"], "/outputs/_test_job123_irradiance.png")
        self.assertTrue(measured_path.is_file())
        self.assertTrue(irradiance_path.is_file())


class DashboardDeploymentTests(unittest.TestCase):
    def test_healthz_remains_public_when_basic_auth_is_configured(self):
        with patch.dict(
            os.environ,
            {
                "DASHBOARD_BASIC_USER": "cliff",
                "DASHBOARD_BASIC_PASSWORD": "secret",
            },
        ):
            response = TestClient(app.app).get("/healthz")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_root_requires_basic_auth_when_configured(self):
        with patch.dict(
            os.environ,
            {
                "DASHBOARD_BASIC_USER": "cliff",
                "DASHBOARD_BASIC_PASSWORD": "secret",
            },
        ):
            client = TestClient(app.app)
            unauthorized = client.get("/")
            token = base64.b64encode(b"cliff:secret").decode("ascii")
            authorized = client.get("/", headers={"Authorization": f"Basic {token}"})

        self.assertEqual(unauthorized.status_code, 401)
        self.assertIn("Basic", unauthorized.headers["www-authenticate"])
        self.assertEqual(authorized.status_code, 200)
        self.assertIn("text/html", authorized.headers["content-type"])

    def test_basic_auth_is_disabled_without_credentials(self):
        with patch.dict(
            os.environ,
            {
                "DASHBOARD_BASIC_USER": "",
                "DASHBOARD_BASIC_PASSWORD": "",
            },
        ):
            response = TestClient(app.app).get("/")

        self.assertEqual(response.status_code, 200)

    def test_partial_basic_auth_configuration_fails_closed(self):
        with patch.dict(
            os.environ,
            {
                "DASHBOARD_BASIC_USER": "cliff",
                "DASHBOARD_BASIC_PASSWORD": "",
            },
        ):
            root = TestClient(app.app).get("/")
            health = TestClient(app.app).get("/healthz")

        self.assertEqual(root.status_code, 503)
        self.assertEqual(health.status_code, 503)
        self.assertIn("authentication configuration", health.json()["failed_checks"])

    def test_private_output_directories_are_blocked_case_insensitively(self):
        marker = config.OUTPUT_DIR / ".agent_state" / "private-case-test.txt"
        private_root_marker = config.OUTPUT_DIR / "private-root-test.sqlite3"
        public_marker = config.OUTPUT_DIR / "public-output-test.csv"
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("private", encoding="utf-8")
        private_root_marker.write_text("private-root", encoding="utf-8")
        public_marker.write_text("timestamp,value\n2025-01-01,1\n", encoding="utf-8")
        self.addCleanup(marker.unlink, missing_ok=True)
        self.addCleanup(private_root_marker.unlink, missing_ok=True)
        self.addCleanup(public_marker.unlink, missing_ok=True)
        with patch.dict(
            os.environ,
            {
                "DASHBOARD_BASIC_USER": "",
                "DASHBOARD_BASIC_PASSWORD": "",
            },
        ):
            client = TestClient(app.app)
            responses = [
                client.get("/outputs/.AGENT_STATE/private-case-test.txt"),
                client.get("/outputs/.AGENT_STATE./private-case-test.txt"),
                client.get("/outputs//.AGENT_STATE/private-case-test.txt"),
                client.get("/outputs/public/../.AGENT_STATE/private-case-test.txt"),
                client.get("/outputs/AGENT_~1/solar_agent.sqlite3"),
                client.get("/outputs/CALIBR~1/"),
                client.get("/outputs/private-root-test.sqlite3"),
            ]
            public_response = client.get("/outputs/public-output-test.csv")

        for response in responses:
            self.assertEqual(response.status_code, 404)
            self.assertNotIn("private", response.text)

        self.assertEqual(public_response.status_code, 200)
        self.assertIn("timestamp,value", public_response.text)

        static_route = next(
            route for route in app.app.routes if getattr(route, "name", None) == "outputs"
        )
        resolved_path, stat_result = static_route.app.lookup_path(
            ".agent_state/private-case-test.txt"
        )
        self.assertEqual("", resolved_path)
        self.assertIsNone(stat_result)


if __name__ == "__main__":
    unittest.main()
