import base64
import os
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
import app


class ChatBackendTests(unittest.TestCase):
    def setUp(self):
        os.environ["OPENAI_API_KEY"] = "test-placeholder"
        app.JOBS.clear()
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

    def test_completed_run_context_is_sent_without_secrets(self):
        app.JOBS["job123"] = {
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

        reply, job_id, web_enabled = app._openai_chat_response(
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

    def test_reference_question_enables_web_search(self):
        app.JOBS["job123"] = {"state": "done", "result": {"stats": {}}}

        _, _, web_enabled = app._openai_chat_response(
            app.ChatRequest(message="Give me references for this prediction.", job_id="job123")
        )

        self.assertTrue(web_enabled)
        self.assertIn({"type": "web_search"}, self.calls[0]["tools"])
        self.assertIn(app.SCENARIO_TOOL, self.calls[0]["tools"])

    def test_missing_run_still_returns_answerable_context(self):
        reply, job_id, web_enabled = app._openai_chat_response(
            app.ChatRequest(message="What does the model do?", job_id="missing")
        )

        self.assertEqual(reply, "mock reply")
        self.assertEqual(job_id, "missing")
        self.assertFalse(web_enabled)
        self.assertIn('"state": "missing"', self.calls[0]["input"][0]["content"])

    def test_physical_iam_is_explicit_even_when_martin_ruiz_coefficient_is_null(self):
        app._openai_chat_response(
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

    def test_input_data_plots_are_rendered_from_historian_csv(self):
        csv_path = app.OUTPUT_DIR / "_test_input_plot.csv"
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

        plots = app._render_input_data_plots(csv_path, app.OUTPUT_DIR / "_test_job123")

        self.assertEqual(plots["measured_power_png"], "/outputs/_test_job123_measured_power.png")
        self.assertEqual(plots["irradiance_png"], "/outputs/_test_job123_irradiance.png")
        self.assertTrue((app.OUTPUT_DIR / "_test_job123_measured_power.png").is_file())
        self.assertTrue((app.OUTPUT_DIR / "_test_job123_irradiance.png").is_file())


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


if __name__ == "__main__":
    unittest.main()
