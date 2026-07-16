import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
from fastapi.testclient import TestClient

import app
import midc_stac_hourly as midc
import sbe_pv_model as model


RAW_HEADER = ["Year", "DOY", "MST", *midc.MEASUREMENT_COLUMNS]


def raw_csv(rows):
    return pd.DataFrame(rows, columns=RAW_HEADER).to_csv(index=False)


def raw_row(day_of_year, mst, value):
    return [2025, day_of_year, mst, value, value, value, value, value]


class MidcReferenceHourTests(unittest.TestCase):
    def test_right_closed_right_labeled_hour_boundaries(self):
        csv_text = raw_csv(
            [
                raw_row(1, 0, 10.0),
                raw_row(1, 1, 20.0),
                raw_row(1, 100, 40.0),
                raw_row(1, 101, 100.0),
            ]
        )

        hourly, _, _, _ = midc.aggregate_hourly(
            csv_text, date(2025, 1, 1), date(2025, 1, 1)
        )

        self.assertEqual(len(hourly), 24)
        self.assertEqual(hourly.loc[0, midc.HOUR_COLUMN], 0)
        self.assertEqual(hourly.loc[0, "Avg Global Horizontal [W/m^2]"], 10.0)
        self.assertEqual(hourly.loc[1, "Avg Global Horizontal [W/m^2]"], 30.0)
        self.assertEqual(hourly.loc[2, "Avg Global Horizontal [W/m^2]"], 100.0)

    def test_sequential_chunks_are_aggregated_across_midnight_once(self):
        responses = {
            date(2025, 1, 1): raw_csv([raw_row(1, 2359, 10.0)]),
            date(2025, 1, 2): raw_csv([raw_row(2, 0, 30.0)]),
        }

        with patch.object(
            midc,
            "download_api_csv",
            side_effect=lambda start, end: responses[start],
        ):
            result = midc.fetch_hourly_data(
                date(2025, 1, 1), date(2025, 1, 2), chunk_days=1
            )

        midnight = result.hourly[
            (result.hourly[midc.DATE_COLUMN] == "01/02/2025")
            & (result.hourly[midc.HOUR_COLUMN] == 0)
        ].iloc[0]
        self.assertEqual(result.chunk_count, 2)
        self.assertEqual(midnight["Avg Global Horizontal [W/m^2]"], 20.0)
        self.assertFalse(result.hourly.duplicated([midc.DATE_COLUMN, midc.HOUR_COLUMN]).any())

    def test_2025_generated_keys_match_reference_with_known_tolerance(self):
        reference_path = Path("2025_MIDC_hourly.csv")
        generated_path = Path("MIDC_STAC_hourly_20250101_to_20251231.csv")
        if not reference_path.is_file() or not generated_path.is_file():
            self.skipTest("2025 MIDC reconciliation fixtures are not present")

        reference = pd.read_csv(reference_path)
        generated = pd.read_csv(generated_path)
        keys = [midc.DATE_COLUMN, midc.HOUR_COLUMN]
        reference[midc.DATE_COLUMN] = pd.to_datetime(
            reference[midc.DATE_COLUMN], format="%m/%d/%Y"
        ).dt.strftime("%m/%d/%Y")
        merged = reference.merge(
            generated,
            on=keys,
            how="outer",
            suffixes=("_ref", "_generated"),
            indicator=True,
            validate="one_to_one",
        )
        self.assertEqual(len(merged), 8760)
        self.assertTrue((merged["_merge"] == "both").all())

        first_key = (merged[midc.DATE_COLUMN] == "01/01/2025") & (
            merged[midc.HOUR_COLUMN] == 0
        )
        for column in midc.MEASUREMENT_COLUMNS.values():
            difference = (
                pd.to_numeric(merged[f"{column}_ref"], errors="coerce")
                - pd.to_numeric(merged[f"{column}_generated"], errors="coerce")
            ).abs()
            unexpected = difference.gt(0.00011) & ~first_key
            self.assertFalse(unexpected.any(), f"Unexpected 2025 difference in {column}")


class MidcModelInputTests(unittest.TestCase):
    def test_missing_weather_uses_documented_fallbacks_and_warning(self):
        frame = pd.DataFrame(
            {
                midc.DATE_COLUMN: ["01/01/2025"] * 3,
                midc.HOUR_COLUMN: [0, 1, 2],
                "Avg Global Horizontal [W/m^2]": [-1.0, np.nan, 100.0],
                "Avg Direct Normal [W/m^2]": [np.nan, 20.0, 40.0],
                "Avg Diffuse Horizontal [W/m^2]": [5.0, np.nan, 30.0],
                "Avg Air Temperature [deg C]": [10.0, np.nan, 14.0],
                "Avg Avg Wind Speed @ 10m [m/s]": [1.0, np.nan, 3.0],
            }
        )
        path = app.OUTPUT_DIR / "_test_midc_missing.csv"
        try:
            frame.to_csv(path, index=False)
            parsed, warnings = model.parse_midc_csv(str(path))
        finally:
            path.unlink(missing_ok=True)

        self.assertTrue(warnings)
        self.assertEqual(parsed["ghi_wm2"].tolist(), [0.0, 0.0, 100.0])
        self.assertEqual(parsed["dni_wm2"].tolist(), [0.0, 20.0, 40.0])
        self.assertTrue(np.isnan(parsed["dhi_wm2"].iloc[1]))
        self.assertEqual(parsed["temp_air_c"].tolist(), [10.0, 12.0, 14.0])
        self.assertEqual(parsed["wind_speed_ms"].tolist(), [1.0, 2.0, 3.0])

    def test_monthly_labels_remain_year_qualified_for_multi_year_runs(self):
        index = pd.DatetimeIndex(
            ["2025-12-31 23:00", "2026-01-01 00:00"], tz="America/Denver"
        )
        frame = pd.DataFrame(
            {
                "se_predicted_energy_step_kwh": [1.0, 2.0],
                "sol_predicted_energy_step_kwh": [0.5, 1.5],
            },
            index=index,
        )

        monthly = model.monthly_energy_table(frame)

        self.assertEqual(monthly["month"].tolist(), ["Dec 2025", "Jan 2026"])

    def test_annual_model_writes_three_charts_and_monthly_workbook_sheet(self):
        index = pd.date_range("2025-01-01", periods=4, freq="h", tz="America/Denver")
        parsed = pd.DataFrame(
            {
                "timestamp_utc": index.tz_convert("UTC"),
                "se_measured_power_w": 0.0,
                "sol_measured_power_w": 0.0,
                "dni_wm2": [0.0, 300.0, 500.0, 0.0],
                "ghi_wm2": [0.0, 250.0, 400.0, 0.0],
                "dhi_wm2": [0.0, 50.0, 80.0, 0.0],
                "temp_air_c": [5.0, 6.0, 8.0, 7.0],
                "wind_speed_ms": [1.0, 2.0, 2.0, 1.0],
            },
            index=index,
        )

        def fake_predict(frame, **kwargs):
            out = frame.copy()
            out["se_predicted_power_w"] = [0.0, 1000.0, 2000.0, 0.0]
            out["sol_predicted_power_w"] = [0.0, 800.0, 1600.0, 0.0]
            return out, "measured"

        base = app.OUTPUT_DIR / "_test_annual_artifacts"
        paths = [
            Path(str(base) + "_ac_power.png"),
            Path(str(base) + "_cumulative_energy.png"),
            Path(str(base) + "_monthly_energy.png"),
            Path(str(base) + ".xlsx"),
        ]
        try:
            with (
                patch.object(model, "parse_midc_csv", return_value=(parsed, [])),
                patch.object(model, "predict_ac_power", side_effect=fake_predict),
            ):
                stats = model.run_model(
                    input_csv="ignored.csv",
                    output_base=str(base),
                    input_kind="midc",
                    annual_mode=True,
                )

            self.assertEqual(stats["mode"], "annual")
            self.assertTrue(all(path.is_file() for path in paths))
            with pd.ExcelFile(paths[-1]) as workbook:
                self.assertIn("monthly_energy", workbook.sheet_names)
        finally:
            for path in paths:
                path.unlink(missing_ok=True)


class AnnualApiTests(unittest.TestCase):
    def setUp(self):
        app.JOBS.clear()

    def test_annual_endpoint_starts_independent_job(self):
        with patch.object(app.threading, "Thread") as thread:
            response = TestClient(app.app).post(
                "/api/annual-run",
                json={"from_date": "2025-01-01", "to_date": "2025-12-31"},
            )

        self.assertEqual(response.status_code, 200)
        job_id = response.json()["job_id"]
        self.assertEqual(app.JOBS[job_id]["mode"], "annual")
        thread.return_value.start.assert_called_once_with()

    def test_unchecked_iam_defaults_to_point_two_in_both_run_modes(self):
        validation = app.RunRequest(
            from_date="2026-06-20",
            to_date="2026-06-21",
        )
        annual = app.AnnualRunRequest(
            from_date="2025-01-01",
            to_date="2025-12-31",
        )

        for request in (validation, annual):
            self.assertFalse(request.include_iam)
            self.assertEqual(request.iam_a_r, 0.2)

    def test_annual_endpoint_rejects_reversed_dates_without_creating_job(self):
        response = TestClient(app.app).post(
            "/api/annual-run",
            json={"from_date": "2025-02-01", "to_date": "2025-01-01"},
        )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(app.JOBS, {})

    def test_status_exposes_annual_irradiance_before_model_completion(self):
        app.JOBS["annual-weather-ready"] = {
            "mode": "annual",
            "state": "running",
            "progress": 28,
            "stage": "Rendering annual irradiance inputs",
            "input_plots": {
                "irradiance_png": "/outputs/annual-weather-ready_irradiance.png"
            },
        }

        response = TestClient(app.app).get("/api/status/annual-weather-ready")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["state"], "running")
        self.assertIn("irradiance_png", payload["input_plots"])

    def test_validation_endpoint_remains_separate(self):
        with patch.object(app.threading, "Thread") as thread:
            response = TestClient(app.app).post(
                "/api/run",
                json={
                    "from_date": "2026-06-20",
                    "to_date": "2026-06-21",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(app.JOBS[response.json()["job_id"]]["mode"], "validation")
        thread.return_value.start.assert_called_once_with()

    def test_annual_worker_returns_all_artifacts_and_context(self):
        hourly = pd.DataFrame(
            {
                midc.DATE_COLUMN: ["01/01/2025"],
                midc.HOUR_COLUMN: [0],
                **{column: [1.0] for column in midc.MEASUREMENT_COLUMNS.values()},
            }
        )
        source = midc.MidcFetchResult(hourly, 1, 1, 0, 1, 1)
        req = app.AnnualRunRequest(from_date="2025-01-01", to_date="2025-01-01")

        job_id = "_test_annualjob"
        base = app.OUTPUT_DIR / job_id
        source_path = app.OUTPUT_DIR / f"{job_id}_midc_hourly.csv"
        irradiance_path = app.OUTPUT_DIR / f"{job_id}_irradiance.png"
        stats = {
            "se_predicted_kwh": 10.0,
            "sol_predicted_kwh": 8.0,
            "predicted_difference_kwh": 2.0,
            "predicted_difference_pct": 25.0,
            "n_rows": 1,
            "data_quality_warnings": ["model fallback"],
            "ac_png": str(base) + "_ac_power.png",
            "energy_png": str(base) + "_cumulative_energy.png",
            "monthly_png": str(base) + "_monthly_energy.png",
            "excel": str(base) + ".xlsx",
        }

        def fake_run_model(**kwargs):
            self.assertIn("input_plots", app.JOBS[job_id])
            self.assertTrue(irradiance_path.is_file())
            return stats

        app.JOBS[job_id] = {"mode": "annual", "state": "running"}
        try:
            with (
                patch.object(app.midc, "fetch_hourly_data", return_value=source),
                patch.object(app.model, "run_model", side_effect=fake_run_model),
            ):
                app._run_annual_job(job_id, req)

            self.assertEqual(app.JOBS[job_id]["state"], "done", app.JOBS[job_id])
            result = app.JOBS[job_id]["result"]
            self.assertEqual(result["mode"], "annual")
            self.assertTrue(source_path.is_file())
            self.assertTrue(irradiance_path.is_file())
            self.assertIn("irradiance_png", result["input_plots"])
            self.assertIn("monthly_png", result)
            self.assertIn("source_csv", result)
            self.assertIn("model fallback", result["warnings"])
            self.assertEqual(result["window"]["hour_convention"], "right-closed, right-labeled")
            self.assertEqual(result["window"]["iam_a_r"], 0.2)
        finally:
            source_path.unlink(missing_ok=True)
            irradiance_path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
