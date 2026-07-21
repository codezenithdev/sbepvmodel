import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import matplotlib.figure
import pandas as pd
from fastapi.testclient import TestClient

import app
import sbe_pv_model as model
from agent_store import AgentStore


class CurtailmentDefaultTests(unittest.TestCase):
    def setUp(self):
        app.JOBS.clear()
        handle = tempfile.NamedTemporaryFile(
            prefix="dashboard-api-test-",
            suffix=".sqlite3",
            dir=Path(__file__).resolve().parent,
            delete=False,
        )
        handle.close()
        database = Path(handle.name)
        original_store = app.AGENT_STORE
        app.AGENT_STORE = AgentStore(database)
        self.addCleanup(setattr, app, "AGENT_STORE", original_store)
        self.addCleanup(
            lambda: [
                path.unlink(missing_ok=True)
                for path in (database, Path(f"{database}-wal"), Path(f"{database}-shm"))
            ]
        )

    def test_validation_and_annual_requests_default_enabled_curtailment_to_125(self):
        cases = (
            (
                "/api/run",
                {"from_date": "2026-06-20", "to_date": "2026-06-21"},
                "_run_job",
            ),
            (
                "/api/annual-run",
                {"from_date": "2025-01-01", "to_date": "2025-01-02"},
                "_run_annual_job",
            ),
        )

        for endpoint, base_payload, worker_name in cases:
            with self.subTest(endpoint=endpoint):
                with patch.object(app, worker_name, return_value=None):
                    response = TestClient(app.app).post(
                        endpoint,
                        json={**base_payload, "curtailment_enabled": True},
                    )

                self.assertEqual(response.status_code, 200)
                request = app.JOBS[response.json()["job_id"]]["request"]
                self.assertTrue(request["curtailment_enabled"])
                self.assertEqual(
                    request["curtailment_limit_kw"],
                    model.DEFAULT_CURTAILMENT_LIMIT_KW,
                )

    def test_custom_value_is_kept_and_disabled_value_is_canonicalized_to_none(self):
        enabled = app.RunRequest(
            from_date="2026-06-20",
            to_date="2026-06-21",
            curtailment_enabled=True,
            curtailment_limit_kw=140,
        )
        app._validate_curtailment(enabled)
        self.assertEqual(enabled.curtailment_limit_kw, 140.0)

        disabled = app.RunRequest(
            from_date="2026-06-20",
            to_date="2026-06-21",
            curtailment_enabled=False,
            curtailment_limit_kw=140,
        )
        app._validate_curtailment(disabled)
        self.assertIsNone(disabled.curtailment_limit_kw)

    def test_non_positive_enabled_values_are_rejected(self):
        for value in (0, -1):
            with self.subTest(value=value):
                request = app.RunRequest(
                    from_date="2026-06-20",
                    to_date="2026-06-21",
                    curtailment_enabled=True,
                    curtailment_limit_kw=value,
                )
                with self.assertRaises(app.HTTPException):
                    app._validate_curtailment(request)


class DashboardInteractionMarkupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = Path("sb_energy_dashboard_modern.html").read_text(
            encoding="utf-8"
        )

    def test_both_curtailment_fields_start_at_125_and_preserve_edits(self):
        for element_id in ("curtailmentLimitKw", "annualCurtailmentLimitKw"):
            self.assertRegex(
                self.html,
                rf'<input[^>]*id="{re.escape(element_id)}"[^>]*value="125"[^>]*disabled',
            )
        self.assertIn(
            "if (enabled && !curtailmentLimitKw.value.trim()) curtailmentLimitKw.value = '125';",
            self.html,
        )
        self.assertIn(
            "if (enabled && !annualCurtailmentLimitKw.value.trim()) annualCurtailmentLimitKw.value = '125';",
            self.html,
        )
        self.assertNotIn("curtailmentLimitKw.value = '';", self.html)

    def test_validation_action_uses_run_configuration_copy(self):
        self.assertIn("<strong>Ready to run configuration?</strong>", self.html)
        self.assertNotIn("<strong>Ready to validate?</strong>", self.html)

    def test_chat_window_has_a_persistent_drag_handle(self):
        self.assertIn('id="chatDragHandle"', self.html)
        self.assertIn("CHAT_WINDOW_POSITION_KEY", self.html)
        self.assertIn("setChatWindowPosition", self.html)
        self.assertIn(
            "chatDragHandle.addEventListener('pointerdown'", self.html
        )
        self.assertIn(
            "chatDragHandle.addEventListener('pointermove'", self.html
        )
        self.assertIn(
            "chatDragHandle.addEventListener('pointerup'", self.html
        )
        self.assertIn("syncChatWindowPosition();", self.html)


class AcChartLayoutTests(unittest.TestCase):
    def test_summary_and_legend_are_outside_ac_data_axes(self):
        index = pd.date_range(
            "2026-06-20", periods=3, freq="h", tz="America/Denver"
        )
        frame = pd.DataFrame(
            {
                "se_predicted_power_w": [0.0, 100_000.0, 0.0],
                "sol_predicted_power_w": [0.0, 90_000.0, 0.0],
                "se_measured_power_w": [0.0, 95_000.0, 0.0],
                "sol_measured_power_w": [0.0, 85_000.0, 0.0],
                "se_predicted_energy_kwh": [0.0, 50.0, 100.0],
                "sol_predicted_energy_kwh": [0.0, 45.0, 90.0],
                "se_measured_energy_kwh": [0.0, 47.5, 95.0],
                "sol_measured_energy_kwh": [0.0, 42.5, 85.0],
            },
            index=index,
        )
        saved_figures = []

        def capture(figure, *_args, **_kwargs):
            saved_figures.append(figure)

        with patch.object(
            matplotlib.figure.Figure,
            "savefig",
            autospec=True,
            side_effect=capture,
        ):
            model.plot_results(frame, "ignored")

        ac_figure = saved_figures[0]
        ac_axes = ac_figure.axes[0]
        self.assertEqual(len(ac_axes.texts), 0)
        self.assertEqual(len(ac_figure.texts), 1)
        self.assertEqual(len(ac_figure.legends), 1)
        self.assertLessEqual(ac_axes.get_position().y1, 0.781)


if __name__ == "__main__":
    unittest.main()
