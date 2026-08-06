from __future__ import annotations

from copy import deepcopy
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pandas as pd

import calibration_workflow as calibration
import sbe_pv_model as model


def resolved_profile() -> dict:
    return {
        "schema_version": 1,
        "origin_job_id": "reviewed-calibration-job",
        "origin_source_sha256": "a" * 64,
        "origin_review_id": "review-receipt",
        "seasonal_factors": {
            "winter": {"solaredge": 1.1, "solectria": 0.9},
            "spring": {"solaredge": 2.0, "solectria": 0.5},
            "summer": {"solaredge": 1.2, "solectria": 0.8},
            # The API resolves this copy only after explicit user consent.
            "fall": {"solaredge": 2.0, "solectria": 0.5},
        },
        "seasonal_substitution": {
            "from_season": "spring",
            "to_season": "fall",
            "acknowledged": True,
            "context_hash": "context-123",
        },
    }


def application_context() -> dict:
    return {
        "baseline_job_id": "reviewed-calibration-job",
        "origin_profile_sha256": "origin-fingerprint",
        "resolved_profile_sha256": "resolved-fingerprint",
        "server_timestamp": "2026-08-04T18:00:00+00:00",
        "settings_deltas": [
            {
                "field": "backtrack",
                "calibrated_value": True,
                "annual_value": False,
            }
        ],
        "seasonal_substitution": {
            "from_season": "spring",
            "to_season": "fall",
            "acknowledged": True,
            "context_hash": "context-123",
        },
    }


class FrozenAnnualProfileTests(unittest.TestCase):
    def test_factors_repeat_by_denver_season_and_source_profile_is_immutable(self):
        index = pd.DatetimeIndex(
            [
                "2025-01-15 12:00",
                "2025-04-15 12:00",
                "2025-07-15 12:00",
                "2025-10-15 12:00",
                "2026-01-15 12:00",
                "2026-04-15 12:00",
                "2026-07-15 12:00",
                "2026-10-15 12:00",
            ],
            tz="America/Denver",
        )
        frame = pd.DataFrame(
            {
                "se_predicted_power_w": [100.0] * len(index),
                "sol_predicted_power_w": [200.0] * len(index),
            },
            index=index,
        )
        profile = resolved_profile()
        before = deepcopy(profile)

        output, factors, _ = calibration.apply_frozen_seasonal_calibration(
            frame,
            calibration_profile=profile,
        )

        self.assertEqual(profile, before)
        self.assertEqual(
            output["se_calibration_factor"].tolist(),
            [1.1, 2.0, 1.2, 2.0, 1.1, 2.0, 1.2, 2.0],
        )
        self.assertEqual(
            output["sol_calibration_factor"].tolist(),
            [0.9, 0.5, 0.8, 0.5, 0.9, 0.5, 0.8, 0.5],
        )
        fall = next(
            item for item in factors["seasons"] if item["season"] == "fall"
        )
        self.assertEqual(
            fall["systems"]["solaredge"]["factor_source_season"],
            "spring",
        )
        self.assertIn("Fall used", factors["warnings"][0])

    def test_substitution_annotation_requires_exact_spring_copy(self):
        profile = resolved_profile()
        profile["seasonal_factors"]["fall"]["solaredge"] = 1.999

        with self.assertRaisesRegex(ValueError, "exact Spring"):
            calibration.validate_seasonal_calibration_profile(profile)


class AnnualRunModelTests(unittest.TestCase):
    def test_frozen_profile_applies_before_curtailment_without_refitting(self):
        index = pd.date_range(
            "2025-10-01 12:00",
            periods=2,
            freq="h",
            tz="America/Denver",
        )
        parsed = pd.DataFrame(
            {
                "timestamp_utc": index.tz_convert("UTC"),
                "se_measured_power_w": [0.0, 0.0],
                "sol_measured_power_w": [0.0, 0.0],
            },
            index=index,
        )

        def fake_predict(frame, **_kwargs):
            output = frame.copy()
            output["se_predicted_power_w"] = [80_000.0, 80_000.0]
            output["sol_predicted_power_w"] = [80_000.0, 80_000.0]
            return output, "measured"

        captured: dict = {}
        progress_messages: list[str] = []
        profile = resolved_profile()
        # Production provenance stores the resolved profile and substitution
        # audit separately. run_model joins deep copies for application only.
        profile.pop("seasonal_substitution")
        profile_before = deepcopy(profile)
        context = application_context()

        def capture_excel(frame, _path, meta, annual_mode=False):
            captured["frame"] = frame.copy()
            captured["meta"] = deepcopy(meta)
            captured["annual_mode"] = annual_mode

        with (
            patch.object(model, "parse_midc_csv", return_value=(parsed, [])),
            patch.object(model, "predict_ac_power", side_effect=fake_predict),
            patch.object(model, "apply_seasonal_calibration") as fit,
            patch.object(model, "plot_results"),
            patch.object(model, "plot_monthly_energy"),
            patch.object(model, "write_excel", side_effect=capture_excel),
        ):
            stats = model.run_model(
                input_csv="ignored.csv",
                output_base="ignored",
                input_kind="midc",
                annual_mode=True,
                expected_interval_seconds=3_600,
                curtailment_enabled=True,
                curtailment_limit_kw=100.0,
                calibration_profile=profile,
                calibration_application_context=context,
                progress_cb=lambda _fraction, message: progress_messages.append(
                    message
                ),
            )

        fit.assert_not_called()
        self.assertEqual(profile, profile_before)
        self.assertTrue(captured["annual_mode"])
        frame = captured["frame"]
        self.assertEqual(frame["se_predicted_power_w"].tolist(), [100_000.0] * 2)
        self.assertEqual(frame["se_uncalibrated_power_w"].tolist(), [80_000.0] * 2)
        self.assertEqual(stats["se_predicted_kwh"], 200.0)
        self.assertEqual(stats["physics_only"]["se_predicted_kwh"], 160.0)
        self.assertEqual(stats["sol_predicted_kwh"], 80.0)
        self.assertEqual(stats["physics_only"]["sol_predicted_kwh"], 160.0)
        self.assertEqual(stats["calibration_kind"], "frozen_profile")
        self.assertEqual(stats["calibration_application"], context)
        self.assertEqual(
            stats["calibration_profile_fingerprint"],
            "resolved-fingerprint",
        )
        self.assertEqual(
            stats["seasonal_substitution_warning"],
            "Fall used Spring substitute",
        )
        self.assertTrue(
            any(
                warning.startswith(
                    "Fall used the explicitly approved Spring seasonal factors"
                )
                for warning in stats["data_quality_warnings"]
            )
        )
        self.assertEqual(
            captured["meta"]["_calibration_application_context"],
            context,
        )
        self.assertEqual(
            progress_messages[-1],
            "Calibrated annual model predictions ready",
        )


class AnnualCalibrationWorkbookTests(unittest.TestCase):
    def test_workbook_retains_both_energy_paths_and_audit_sheets(self):
        index = pd.date_range(
            "2025-10-01 12:00",
            periods=2,
            freq="h",
            tz="America/Denver",
        )
        frame = pd.DataFrame(
            {
                "timestamp_utc": index.tz_convert("UTC"),
                "se_measured_power_w": [0.0, 0.0],
                "sol_measured_power_w": [0.0, 0.0],
                "se_uncalibrated_power_w": [80_000.0, 80_000.0],
                "se_predicted_power_w": [100_000.0, 100_000.0],
                "se_calibration_factor": [2.0, 2.0],
                "sol_uncalibrated_power_w": [80_000.0, 80_000.0],
                "sol_predicted_power_w": [40_000.0, 40_000.0],
                "sol_calibration_factor": [0.5, 0.5],
            },
            index=index,
        )
        frame = model.add_energy(frame, expected_interval_seconds=3_600)
        factors = {
            "method": "frozen_baseline_seasonal_factors",
            "application_mode": "frozen_baseline_profile",
            "origin_job_id": "reviewed-calibration-job",
            "origin_review_id": "review-receipt",
            "origin_source_sha256": "a" * 64,
            "seasonal_substitution": resolved_profile()[
                "seasonal_substitution"
            ],
            "seasons": [
                {
                    "season": "fall",
                    "months": "Sep-Nov",
                    "systems": {
                        "solaredge": {"factor": 2.0},
                        "solectria": {"factor": 0.5},
                    },
                }
            ],
        }
        context = application_context()
        meta = {
            "annual_mode": True,
            "calibration_enabled": True,
            "calibration_method": factors["method"],
            "_calibration_factors": factors,
            "_calibration_application_context": context,
        }

        workbook_path = (
            Path(__file__).resolve().parent
            / f"_annual_calibration_{uuid4().hex}.xlsx"
        )
        try:
            model.write_excel(
                frame,
                str(workbook_path),
                meta,
                annual_mode=True,
            )

            with pd.ExcelFile(workbook_path) as workbook:
                self.assertTrue(
                    {
                        "time_series",
                        "monthly_energy",
                        "calibration_factors",
                        "calibration_lineage",
                        "settings_delta",
                        "substitution_audit",
                    }.issubset(workbook.sheet_names)
                )
                time_series = pd.read_excel(workbook, sheet_name="time_series")
                self.assertIn("se_calibrated_power_w", time_series)
                self.assertIn("se_uncalibrated_power_w", time_series)
                self.assertIn("se_calibrated_energy_kwh", time_series)
                self.assertIn("se_uncalibrated_energy_kwh", time_series)
                monthly = pd.read_excel(workbook, sheet_name="monthly_energy")
                self.assertIn("SolarEdge_calibrated_kWh", monthly)
                self.assertIn("SolarEdge_physics_only_kWh", monthly)
                lineage = pd.read_excel(
                    workbook, sheet_name="calibration_lineage"
                ).set_index("parameter")["value"]
                self.assertEqual(
                    lineage["resolved_profile_sha256"],
                    "resolved-fingerprint",
                )
                settings = pd.read_excel(workbook, sheet_name="settings_delta")
                self.assertEqual(settings.loc[0, "setting"], "backtrack")
                self.assertTrue(bool(settings.loc[0, "changed"]))
                substitution = pd.read_excel(
                    workbook, sheet_name="substitution_audit"
                )
                self.assertEqual(substitution.loc[0, "status"], "used")
                self.assertEqual(
                    substitution.loc[0, "from_season"], "spring"
                )
                self.assertEqual(substitution.loc[0, "to_season"], "fall")
        finally:
            workbook_path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
