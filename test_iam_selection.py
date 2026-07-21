import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
from fastapi.testclient import TestClient

import app
import sbe_pv_model as model
from agent_store import AgentStore


class IamModelTests(unittest.TestCase):
    def test_default_is_physical_and_martin_ruiz_validates_a_r(self):
        self.assertEqual(
            model.resolve_iam_settings(),
            (model.IAM_MODEL_PHYSICAL, None),
        )
        self.assertEqual(
            model.resolve_iam_settings(
                iam_model=model.IAM_MODEL_MARTIN_RUIZ,
                iam_a_r=0.2,
            ),
            (model.IAM_MODEL_MARTIN_RUIZ, 0.2),
        )
        self.assertEqual(
            model.resolve_iam_settings(
                iam_model=model.IAM_MODEL_PHYSICAL,
                iam_a_r=float("nan"),
            ),
            (model.IAM_MODEL_PHYSICAL, None),
        )

        for invalid in (0, -0.1, float("nan"), float("inf"), None):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    model.resolve_iam_settings(
                        iam_model=model.IAM_MODEL_MARTIN_RUIZ,
                        iam_a_r=invalid,
                    )

        with self.assertRaises(ValueError):
            model.resolve_iam_settings(iam_model="unknown", iam_a_r=0.2)

    def test_reference_parity_physical_and_martin_ruiz_outputs(self):
        location = model.pvl.location.Location(
            model.LAT,
            model.LON,
            tz=model.TIMEZONE,
        )
        times = pd.DatetimeIndex(["2026-06-21 06:00"], tz=model.TIMEZONE)
        weather = pd.DataFrame(
            {
                "dni": [1000.0],
                "ghi": [800.0],
                "dhi": [100.0],
                "temp_air": [25.0],
                "wind_speed": [1.0],
            },
            index=times,
        )

        physical = model.run_modelchain_for_axis_tilt(
            0.0,
            weather,
            location,
            iam_model=model.IAM_MODEL_PHYSICAL,
            iam_a_r=None,
        )
        martin_ruiz_default = model.run_modelchain_for_axis_tilt(
            0.0,
            weather,
            location,
            iam_model=model.IAM_MODEL_MARTIN_RUIZ,
            iam_a_r=0.2,
        )
        martin_ruiz_custom = model.run_modelchain_for_axis_tilt(
            0.0,
            weather,
            location,
            iam_model=model.IAM_MODEL_MARTIN_RUIZ,
            iam_a_r=0.4,
        )

        np.testing.assert_allclose(physical["Ee_suns"], [0.3342818591], rtol=1e-6)
        np.testing.assert_allclose(physical["p_mp_w"], [185.9361699], rtol=1e-6)
        np.testing.assert_allclose(
            martin_ruiz_default["Ee_suns"], [0.2405553640], rtol=1e-6
        )
        np.testing.assert_allclose(
            martin_ruiz_custom["Ee_suns"], [0.1595056972], rtol=1e-6
        )
        np.testing.assert_allclose(
            martin_ruiz_default["p_mp_w"], [222.0529305], rtol=1e-6
        )
        np.testing.assert_allclose(
            martin_ruiz_custom["p_mp_w"], martin_ruiz_default["p_mp_w"]
        )


class IamApiTests(unittest.TestCase):
    def setUp(self):
        app.JOBS.clear()
        handle = tempfile.NamedTemporaryFile(
            prefix="iam-api-test-",
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

    def _start_validation(self, payload):
        with patch.object(app, "_run_job", return_value=None):
            response = TestClient(app.app).post(
                "/api/run",
                json={
                    "from_date": "2026-06-20",
                    "to_date": "2026-06-21",
                    **payload,
                },
            )
        request = None
        if response.status_code == 200:
            request = app.JOBS[response.json()["job_id"]]["request"]
        return response, request

    def test_new_requests_default_to_physical(self):
        response, request = self._start_validation({})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(request["iam_model"], model.IAM_MODEL_PHYSICAL)
        self.assertIsNone(request["iam_a_r"])
        self.assertNotIn("include_iam", request)

    def test_martin_ruiz_default_and_custom_values(self):
        for coefficient in (0.2, 0.15):
            with self.subTest(coefficient=coefficient):
                response, request = self._start_validation(
                    {
                        "iam_model": model.IAM_MODEL_MARTIN_RUIZ,
                        "iam_a_r": coefficient,
                    }
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(request["iam_model"], model.IAM_MODEL_MARTIN_RUIZ)
                self.assertEqual(request["iam_a_r"], coefficient)

    def test_martin_ruiz_rejects_invalid_values_and_physical_ignores_them(self):
        for coefficient in (0, -0.1):
            with self.subTest(coefficient=coefficient):
                response, _ = self._start_validation(
                    {
                        "iam_model": model.IAM_MODEL_MARTIN_RUIZ,
                        "iam_a_r": coefficient,
                    }
                )
                self.assertEqual(response.status_code, 422)

        response, request = self._start_validation(
            {"iam_model": model.IAM_MODEL_PHYSICAL, "iam_a_r": -1}
        )
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(request["iam_a_r"])

        for coefficient in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(coefficient=coefficient):
                request_model = app.RunRequest(
                    from_date="2026-06-20",
                    to_date="2026-06-21",
                    iam_model=model.IAM_MODEL_MARTIN_RUIZ,
                    iam_a_r=coefficient,
                )
                with self.assertRaises(app.HTTPException) as raised:
                    app._validate_run_request(request_model)
                self.assertEqual(raised.exception.status_code, 422)

    def test_unknown_model_is_rejected(self):
        response, _ = self._start_validation(
            {"iam_model": "not-a-model", "iam_a_r": 0.2}
        )
        self.assertEqual(response.status_code, 422)

    def test_explicit_model_wins_over_legacy_flag(self):
        response, request = self._start_validation(
            {
                "iam_model": model.IAM_MODEL_PHYSICAL,
                "iam_a_r": 0.9,
                "include_iam": True,
            }
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(request["iam_model"], model.IAM_MODEL_PHYSICAL)
        self.assertIsNone(request["iam_a_r"])

    def test_legacy_payloads_keep_deployed_martin_ruiz_semantics(self):
        response, request = self._start_validation(
            {"include_iam": False, "iam_a_r": 0.9}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(request["iam_model"], model.IAM_MODEL_MARTIN_RUIZ)
        self.assertEqual(request["iam_a_r"], 0.2)

        response, request = self._start_validation(
            {"include_iam": True, "iam_a_r": 0.15}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(request["iam_model"], model.IAM_MODEL_MARTIN_RUIZ)
        self.assertEqual(request["iam_a_r"], 0.15)

    def test_annual_endpoint_propagates_martin_ruiz_selection(self):
        with patch.object(app, "_run_annual_job", return_value=None):
            response = TestClient(app.app).post(
                "/api/annual-run",
                json={
                    "from_date": "2025-01-01",
                    "to_date": "2025-01-02",
                    "iam_model": model.IAM_MODEL_MARTIN_RUIZ,
                    "iam_a_r": 0.18,
                },
            )

        self.assertEqual(response.status_code, 200)
        request = app.JOBS[response.json()["job_id"]]["request"]
        self.assertEqual(request["iam_model"], model.IAM_MODEL_MARTIN_RUIZ)
        self.assertEqual(request["iam_a_r"], 0.18)


class IamDashboardMarkupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = Path("sb_energy_dashboard_modern.html").read_text(encoding="utf-8")

    def test_both_forms_offer_physical_default_and_martin_ruiz(self):
        for element_id in (
            "iamModelPhysical",
            "iamModelMartinRuiz",
            "annualIamModelPhysical",
            "annualIamModelMartinRuiz",
        ):
            self.assertIn(f'id="{element_id}"', self.html)
        for element_id in ("iamModelPhysical", "annualIamModelPhysical"):
            self.assertRegex(
                self.html,
                rf'<input[^>]*id="{re.escape(element_id)}"[^>]*value="physical"[^>]*checked',
            )
        self.assertGreaterEqual(self.html.count('value="martin_ruiz"'), 2)

    def test_reference_links_and_parity_disclosure_are_present(self):
        self.assertIn(
            "https://pvlib-python.readthedocs.io/en/stable/reference/generated/pvlib.iam.physical.html",
            self.html,
        )
        self.assertIn(
            "https://pvlib-python.readthedocs.io/en/stable/reference/generated/pvlib.iam.martin_ruiz.html",
            self.html,
        )
        self.assertGreaterEqual(self.html.count('target="_blank"'), 4)
        self.assertGreaterEqual(self.html.count('rel="noopener noreferrer"'), 4)
        self.assertGreaterEqual(
            self.html.count(
                "Reference parity: If Martin-Ruiz is selected, no IAM loss will be applied to the Physical model in ModelChain to avoid double-counting."
            ),
            2,
        )

    def test_requests_and_saved_state_use_explicit_model_selection(self):
        self.assertGreaterEqual(self.html.count("iam_model: iamModel"), 2)
        self.assertGreaterEqual(
            self.html.count(
                "if (iamModel === 'martin_ruiz') body.iam_a_r = iamArValue;"
            ),
            2,
        )
        self.assertIn("iamModel: getSelectedIamModel(iamModelRadios)", self.html)
        self.assertIn(
            "iamModel: getSelectedIamModel(annualIamModelRadios)", self.html
        )
        self.assertIn("Legacy dashboards always used Martin", self.html)
        for element_id in ("iamAr", "annualIamAr"):
            self.assertRegex(
                self.html,
                rf'<input[^>]*id="{element_id}"[^>]*value="0\.2"[^>]*disabled',
            )


if __name__ == "__main__":
    unittest.main()
