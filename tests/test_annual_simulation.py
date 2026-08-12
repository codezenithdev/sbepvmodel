import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
from fastapi import HTTPException
from fastapi.testclient import TestClient

from sbepv.api import config, state, validation
from sbepv.worker import run_annual
from sbepv.api import main as app
from sbepv.ingest import midc
from sbepv import model
from sbepv.store import AgentStore


RAW_HEADER = ["Year", "DOY", "MST", *midc.MEASUREMENT_COLUMNS]


def raw_csv(rows):
    return pd.DataFrame(rows, columns=RAW_HEADER).to_csv(index=False)


def raw_row(day_of_year, mst, value, year=2025):
    return [year, day_of_year, mst, value, value, value, value, value]


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

    def test_two_hour_intervals_keep_integer_right_edge_labels_and_means(self):
        csv_text = raw_csv(
            [
                raw_row(1, 0, 10.0),
                raw_row(1, 100, 30.0),
                raw_row(1, 101, 50.0),
                raw_row(1, 300, 70.0),
            ]
        )

        intervals, _, _, _ = midc.aggregate_interval(
            csv_text,
            date(2025, 1, 1),
            date(2025, 1, 1),
            7_200,
        )

        self.assertEqual(len(intervals), 12)
        self.assertEqual(intervals[midc.HOUR_COLUMN].tolist(), list(range(1, 24, 2)))
        self.assertEqual(
            intervals.loc[0, "Avg Global Horizontal [W/m^2]"], 20.0
        )
        self.assertEqual(
            intervals.loc[1, "Avg Global Horizontal [W/m^2]"], 60.0
        )

    def test_fifteen_minute_intervals_keep_distinct_right_edge_keys_and_means(self):
        csv_text = raw_csv(
            [
                raw_row(1, 0, 10.0),
                raw_row(1, 1, 20.0),
                raw_row(1, 15, 40.0),
                raw_row(1, 16, 50.0),
                raw_row(1, 30, 70.0),
            ]
        )

        intervals, _, _, _ = midc.aggregate_interval(
            csv_text,
            date(2025, 1, 1),
            date(2025, 1, 1),
            15 * 60,
        )

        self.assertEqual(len(intervals), 96)
        self.assertEqual(
            intervals.loc[:2, [midc.HOUR_COLUMN, midc.MINUTE_COLUMN]].values.tolist(),
            [[0, 0], [0, 15], [0, 30]],
        )
        self.assertEqual(
            intervals.loc[1, "Avg Global Horizontal [W/m^2]"], 30.0
        )
        self.assertEqual(
            intervals.loc[2, "Avg Global Horizontal [W/m^2]"], 60.0
        )
        self.assertFalse(
            intervals.duplicated(
                [midc.DATE_COLUMN, midc.HOUR_COLUMN, midc.MINUTE_COLUMN]
            ).any()
        )

    def test_partial_interval_count_excludes_completely_empty_bins(self):
        intervals, _, missing_values, affected = midc.aggregate_interval(
            raw_csv(
                [
                    raw_row(1, 0, 10.0),
                    raw_row(1, 1, 20.0),
                    raw_row(1, 5, 30.0),
                ]
            ),
            date(2025, 1, 1),
            date(2025, 1, 1),
            15 * 60,
        )

        self.assertEqual(intervals.attrs["partial_interval_count"], 2)
        self.assertEqual(intervals.attrs["expected_samples_per_interval"], 15)
        self.assertEqual(affected, 94)
        self.assertEqual(missing_values, 94 * len(midc.MEASUREMENT_COLUMNS))

    def test_partial_interval_count_uses_valid_samples_per_measurement(self):
        timestamps = pd.date_range(
            "2024-12-31 23:46",
            "2025-01-01 23:59",
            freq="1min",
        )
        rows = []
        for timestamp in timestamps:
            row = raw_row(
                timestamp.dayofyear,
                int(timestamp.strftime("%H%M")),
                10.0,
                year=timestamp.year,
            )
            if (
                timestamp.date() == date(2025, 1, 1)
                and timestamp.hour == 0
                and 1 <= timestamp.minute <= 14
            ):
                row[3] = midc.MISSING_SENTINEL_MAX
            rows.append(row)
        # Repeated valid rows at one minute must not masquerade as the fourteen
        # distinct GHI minutes whose values are missing from this interval.
        rows.extend([raw_row(1, 15, 10.0)] * 14)

        with patch.object(midc, "download_api_csv", return_value=raw_csv(rows)):
            result = midc.fetch_interval_data(
                date(2025, 1, 1),
                date(2025, 1, 1),
                15 * 60,
            )

        self.assertEqual(
            result.interval_data.loc[1, "Avg Global Horizontal [W/m^2]"],
            10.0,
        )
        self.assertEqual(result.partial_interval_count, 1)
        self.assertEqual(result.missing_value_count, 0)
        self.assertEqual(result.affected_interval_count, 0)
        self.assertTrue(any("fewer than" in warning for warning in result.warnings))

    def test_first_available_date_does_not_request_prior_day_and_marks_boundary(self):
        timestamps = pd.date_range(
            "2011-02-11 00:00",
            "2011-02-11 23:45",
            freq="1min",
        )
        response = raw_csv(
            [
                raw_row(
                    timestamp.dayofyear,
                    int(timestamp.strftime("%H%M")),
                    10.0,
                    year=timestamp.year,
                )
                for timestamp in timestamps
            ]
        )

        with patch.object(midc, "download_api_csv", return_value=response) as download:
            result = midc.fetch_interval_data(
                midc.FIRST_AVAILABLE_DATE,
                midc.FIRST_AVAILABLE_DATE,
                15 * 60,
            )

        download.assert_called_once_with(
            midc.FIRST_AVAILABLE_DATE,
            midc.FIRST_AVAILABLE_DATE,
        )
        self.assertEqual(result.partial_interval_count, 1)
        self.assertEqual(result.affected_interval_count, 0)
        self.assertTrue(any("fewer than" in warning for warning in result.warnings))

    def test_sequential_chunks_are_aggregated_across_midnight_once(self):
        responses = {
            date(2024, 12, 31): raw_csv(
                [raw_row(366, 2359, 5.0, year=2024)]
            ),
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
        first_midnight = result.hourly[
            (result.hourly[midc.DATE_COLUMN] == "01/01/2025")
            & (result.hourly[midc.HOUR_COLUMN] == 0)
        ].iloc[0]
        self.assertEqual(result.chunk_count, 3)
        self.assertEqual(result.raw_rows, 3)
        self.assertEqual(first_midnight["Avg Global Horizontal [W/m^2]"], 5.0)
        self.assertEqual(midnight["Avg Global Horizontal [W/m^2]"], 20.0)
        self.assertFalse(result.hourly.duplicated([midc.DATE_COLUMN, midc.HOUR_COLUMN]).any())

    def test_interval_must_be_at_least_one_minute_and_divide_a_day(self):
        csv_text = raw_csv([raw_row(1, 0, 10.0)])

        for interval_seconds in (0, 30, 7 * 60, 5 * 3_600):
            with self.subTest(interval_seconds=interval_seconds):
                with self.assertRaises(midc.MidcError):
                    midc.aggregate_interval(
                        csv_text,
                        date(2025, 1, 1),
                        date(2025, 1, 1),
                        interval_seconds,
                    )

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
    def test_sub_hour_midc_keys_parse_as_distinct_fixed_mst_timestamps(self):
        frame = pd.DataFrame(
            {
                midc.DATE_COLUMN: ["01/01/2025", "01/01/2025"],
                midc.HOUR_COLUMN: [0, 0],
                midc.MINUTE_COLUMN: [0, 15],
                **{
                    column: [1.0, 2.0]
                    for column in midc.MEASUREMENT_COLUMNS.values()
                },
            }
        )
        path = config.OUTPUT_DIR / "_test_midc_minutes.csv"
        try:
            frame.to_csv(path, index=False)
            parsed, warnings = model.parse_midc_csv(str(path))
        finally:
            path.unlink(missing_ok=True)

        self.assertEqual(warnings, [])
        fixed_mst = parsed.index.tz_convert("Etc/GMT+7")
        self.assertEqual(fixed_mst.minute.tolist(), [0, 15])
        self.assertFalse(parsed.index.has_duplicates)

    def test_default_martin_ruiz_coefficient_is_applied_when_custom_iam_is_off(self):
        self.assertEqual(model.resolve_iam_a_r(False, 0.9), 0.2)
        self.assertEqual(model.resolve_iam_a_r(True, 0.15), 0.15)

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
        path = config.OUTPUT_DIR / "_test_midc_missing.csv"
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

    def test_monthly_table_omits_unselected_gap_years(self):
        index = pd.DatetimeIndex(
            ["2012-01-01 00:00", "2025-03-01 00:00"],
            tz="America/Denver",
        )
        frame = pd.DataFrame(
            {
                "se_predicted_energy_step_kwh": [1.0, 2.0],
                "sol_predicted_energy_step_kwh": [0.5, 1.5],
            },
            index=index,
        )

        monthly = model.monthly_energy_table(frame)

        self.assertEqual(monthly["month"].tolist(), ["Jan 2012", "Mar 2025"])
        self.assertEqual(monthly["SolarEdge_predicted_kWh"].tolist(), [1.0, 2.0])

    def test_monthly_table_uses_fixed_mst_source_date_at_summer_boundary(self):
        fixed_mst = pd.DatetimeIndex(
            ["2025-07-31 23:00", "2025-08-01 00:00"], tz="Etc/GMT+7"
        )
        frame = pd.DataFrame(
            {
                "se_predicted_energy_step_kwh": [1.0, 2.0],
                "sol_predicted_energy_step_kwh": [0.5, 1.5],
            },
            index=fixed_mst.tz_convert("America/Denver"),
        )

        monthly = model.monthly_energy_table(frame)

        self.assertEqual(monthly["month"].tolist(), ["Jul 2025", "Aug 2025"])
        self.assertEqual(monthly["SolarEdge_predicted_kWh"].tolist(), [1.0, 2.0])

    def test_annual_energy_cdf_uses_complete_years_only(self):
        fixed_mst = pd.DatetimeIndex(
            [
                "2011-02-11 00:00",
                "2024-01-01 00:00",
                "2024-12-31 23:00",
                "2026-08-10 23:00",
            ],
            tz="Etc/GMT+7",
        )
        frame = pd.DataFrame(
            {
                "se_predicted_energy_step_kwh": [1.0, 10.0, 20.0, 100.0],
                "sol_predicted_energy_step_kwh": [2.0, 5.0, 7.0, 50.0],
            },
            index=fixed_mst.tz_convert("America/Denver"),
        )
        periods = [
            validation._annual_period_record(
                2011, date(2011, 2, 11), date(2011, 12, 31)
            ),
            validation._annual_period_record(
                2024, date(2024, 1, 1), date(2024, 12, 31)
            ),
            validation._annual_period_record(
                2026, date(2026, 1, 1), date(2026, 8, 10)
            ),
        ]

        rows, cdf = model.annual_energy_by_year(frame, periods)

        self.assertEqual([row["year"] for row in rows], [2011, 2024, 2026])
        self.assertEqual(rows[1]["combined_predicted_kwh"], 42.0)
        self.assertEqual(rows[2]["row_count"], 1)
        self.assertEqual(cdf["eligible_years"], [2024])
        self.assertEqual(
            [row["year"] for row in cdf["excluded_years"]], [2011, 2026]
        )
        self.assertEqual(
            cdf["series"]["combined"],
            [{"year": 2024, "energy_kwh": 42.0, "cumulative_probability": 1.0}],
        )

    def test_annual_energy_cdf_assigns_equal_values_equal_probability(self):
        frame = pd.DataFrame(
            {
                "se_predicted_energy_step_kwh": [10.0, 10.0, 20.0],
                "sol_predicted_energy_step_kwh": [5.0, 5.0, 10.0],
            },
            index=pd.DatetimeIndex(
                [
                    "2022-01-01 00:00",
                    "2023-01-01 00:00",
                    "2024-01-01 00:00",
                ],
                tz="Etc/GMT+7",
            ).tz_convert("America/Denver"),
        )
        periods = [
            validation._annual_period_record(
                year, date(year, 1, 1), date(year, 12, 31)
            )
            for year in (2022, 2023, 2024)
        ]

        _, cdf = model.annual_energy_by_year(frame, periods)

        points = cdf["series"]["combined"]
        self.assertEqual(
            [point["cumulative_probability"] for point in points],
            [0.666667, 0.666667, 1.0],
        )

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

        base = config.OUTPUT_DIR / "_test_annual_artifacts"
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
            self.assertEqual(stats["iam_model"], model.IAM_MODEL_PHYSICAL)
            self.assertIsNone(stats["iam_a_r"])
            self.assertTrue(all(path.is_file() for path in paths))
            with pd.ExcelFile(paths[-1]) as workbook:
                self.assertIn("monthly_energy", workbook.sheet_names)
                self.assertIn("annual_energy_by_year", workbook.sheet_names)
                self.assertIn("annual_energy_cdf", workbook.sheet_names)
                headers = list(
                    pd.read_excel(
                        workbook, sheet_name="time_series", nrows=0
                    ).columns
                )
                self.assertIn("se_predicted_power_w", headers)
                self.assertIn("sol_predicted_energy_kwh", headers)
                self.assertNotIn("se_calibrated_power_w", headers)
                self.assertNotIn("sol_calibrated_energy_kwh", headers)
            self.assertEqual(len(stats["annual_energy_by_year"]), 1)
            self.assertEqual(stats["annual_energy_cdf"]["eligible_years"], [])
        finally:
            for path in paths:
                path.unlink(missing_ok=True)


class AnnualApiTests(unittest.TestCase):
    def setUp(self):
        legacy_run = patch.object(
            app,
            "_legacy_unreviewed_run_enabled",
            return_value=True,
        )
        legacy_run.start()
        self.addCleanup(legacy_run.stop)
        state.JOBS.clear()
        handle = tempfile.NamedTemporaryFile(
            prefix="annual-api-test-",
            suffix=".sqlite3",
            dir=Path(__file__).resolve().parent,
            delete=False,
        )
        handle.close()
        database = Path(handle.name)
        original_store = state.AGENT_STORE
        state.AGENT_STORE = AgentStore(database)
        self.addCleanup(setattr, state, "AGENT_STORE", original_store)
        self.addCleanup(
            lambda: [
                path.unlink(missing_ok=True)
                for path in (database, Path(f"{database}-wal"), Path(f"{database}-shm"))
            ]
        )

    def test_annual_endpoint_starts_independent_job(self):
        response = TestClient(app.app).post(
            "/api/annual-run",
            json={"from_date": "2025-01-01", "to_date": "2025-12-31"},
        )

        self.assertEqual(response.status_code, 200)
        job_id = response.json()["job_id"]
        self.assertEqual(state.JOBS[job_id]["mode"], "annual")
        self.assertEqual(state.JOBS[job_id]["state"], "queued")
        self.assertEqual(state.AGENT_STORE.get_job(job_id)["kind"], "baseline")

    def test_selected_years_are_sorted_resolved_and_persisted(self):
        response = TestClient(app.app).post(
            "/api/annual-run",
            json={"years": [2024, 2011], "interval_value": 6, "interval_unit": "hours"},
        )

        self.assertEqual(response.status_code, 200, response.text)
        request = state.AGENT_STORE.get_job(response.json()["job_id"])["request"]
        self.assertEqual(request["years"], [2011, 2024])
        self.assertEqual(request["from_date"], "2011-02-11")
        self.assertEqual(request["to_date"], "2024-12-31")

    def test_selected_year_endpoint_cannot_queue_custom_partial_bounds(self):
        response = TestClient(app.app).post(
            "/api/annual-run",
            json={
                "years": [2024],
                "from_date": "2024-01-01",
                "to_date": "2024-01-02",
            },
        )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(state.JOBS, {})
        self.assertEqual(state.AGENT_STORE.list_jobs(), [])

    def test_selected_year_periods_mark_partial_and_current_year(self):
        request = app.AnnualRunRequest(years=[2026, 2011, 2024])

        periods = validation._annual_periods(request, today=date(2026, 8, 11))

        self.assertEqual(request.years, [2011, 2024, 2026])
        self.assertEqual(request.from_date, "2011-02-11")
        self.assertEqual(request.to_date, "2026-08-10")
        self.assertEqual(
            [period["coverage_status"] for period in periods],
            ["partial_start", "complete", "year_to_date"],
        )
        self.assertEqual(
            [period["cdf_eligible"] for period in periods],
            [False, True, False],
        )

    def test_selected_years_reject_duplicates_and_out_of_range_values(self):
        for years in ([2024, 2024], [2010], [2027]):
            with self.subTest(years=years), self.assertRaises(HTTPException):
                validation._annual_periods(
                    app.AnnualRunRequest(years=years),
                    today=date(2026, 8, 11),
                )

    def test_one_minute_row_budget_allows_one_year_and_rejects_multiple_years(self):
        one_year = app.AnnualRunRequest(
            years=[2024], interval_value=1, interval_unit="minutes"
        )
        periods = validation._annual_periods(one_year, today=date(2026, 8, 11))
        self.assertEqual([period["year"] for period in periods], [2024])

        multiple_years = app.AnnualRunRequest(
            years=[2024, 2025], interval_value=1, interval_unit="minutes"
        )
        with self.assertRaises(HTTPException) as context:
            validation._annual_periods(
                multiple_years,
                today=date(2026, 8, 11),
            )
        self.assertIn("1,048,575 rows", str(context.exception.detail))
        self.assertIn("exportable to Excel", str(context.exception.detail))

    def test_legacy_one_minute_row_budget_is_enforced_before_work(self):
        request = app.AnnualRunRequest(
            from_date="2023-01-01",
            to_date="2025-12-31",
            interval_value=1,
            interval_unit="minutes",
        )
        with self.assertRaises(HTTPException) as context:
            validation._annual_periods(request)

        self.assertIn("Select fewer years or a longer interval", str(context.exception.detail))

    def test_initial_selected_year_request_rejects_custom_partial_bounds(self):
        request = app.AnnualRunRequest(
            years=[2024],
            from_date="2024-01-01",
            to_date="2024-01-02",
        )

        with self.assertRaises(HTTPException) as context:
            validation._annual_periods(request, today=date(2026, 8, 11))

        self.assertIn("complete available periods", str(context.exception.detail))

    def test_legacy_annual_periods_observe_runtime_max_days_setting(self):
        request = app.AnnualRunRequest(
            from_date="2025-01-01", to_date="2025-01-02"
        )

        with (
            patch.object(config, "ANNUAL_RUN_MAX_DAYS", 1),
            self.assertRaises(HTTPException) as context,
        ):
            validation._annual_periods(request)

        self.assertIn("limited to 1 days", str(context.exception.detail))

    def test_current_year_cutoff_remains_immutable_after_new_year(self):
        queued_request = app.AnnualRunRequest(years=[2026])
        original_periods = validation._annual_periods(
            queued_request, today=date(2026, 12, 31)
        )
        stored_request = app.AnnualRunRequest(
            **queued_request.model_dump()
        )

        revalidated_periods = validation._annual_periods(
            stored_request,
            today=date(2027, 1, 1),
            allow_resolved_partial=True,
        )

        self.assertEqual(queued_request.to_date, "2026-12-30")
        self.assertEqual(revalidated_periods, original_periods)
        self.assertEqual(revalidated_periods[0]["period_end"], "2026-12-30")
        self.assertFalse(revalidated_periods[0]["cdf_eligible"])
        with self.assertRaises(HTTPException):
            validation._annual_periods(
                stored_request,
                today=date(2027, 1, 1),
            )

    def test_current_year_cutoff_uses_fixed_mst_at_dst_midnight(self):
        class FrozenDateTime:
            instant = datetime(2026, 8, 11, 6, 30, tzinfo=timezone.utc)

            @classmethod
            def now(cls, tz):
                return cls.instant.astimezone(tz)

        cases = (
            (datetime(2026, 8, 11, 6, 30, tzinfo=timezone.utc), "2026-08-09"),
            (datetime(2026, 8, 11, 7, 0, tzinfo=timezone.utc), "2026-08-10"),
        )
        for instant, expected_cutoff in cases:
            with self.subTest(instant=instant):
                FrozenDateTime.instant = instant
                request = app.AnnualRunRequest(years=[2026])
                with patch.object(validation, "datetime", FrozenDateTime):
                    validation._annual_periods(request)
                self.assertEqual(expected_cutoff, request.to_date)

    def test_new_requests_default_to_physical_in_both_run_modes(self):
        validation = app.RunRequest(
            from_date="2026-06-20",
            to_date="2026-06-21",
        )
        annual = app.AnnualRunRequest(
            from_date="2025-01-01",
            to_date="2025-12-31",
        )

        for request in (validation, annual):
            request.iam_a_r = 0.9
            app._validate_run_request(request)
            self.assertEqual(request.iam_model, model.IAM_MODEL_PHYSICAL)
            self.assertEqual(
                app._iam_metadata(request),
                {"iam_model": model.IAM_MODEL_PHYSICAL, "iam_a_r": None},
            )

    def test_annual_endpoint_rejects_reversed_dates_without_creating_job(self):
        response = TestClient(app.app).post(
            "/api/annual-run",
            json={"from_date": "2025-02-01", "to_date": "2025-01-01"},
        )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(state.JOBS, {})

    def test_status_exposes_annual_irradiance_before_model_completion(self):
        state.JOBS["annual-weather-ready"] = {
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
        response = TestClient(app.app).post(
            "/api/run",
            json={
                "from_date": "2026-06-20",
                "to_date": "2026-06-21",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(state.JOBS[response.json()["job_id"]]["mode"], "validation")
        self.assertEqual(state.JOBS[response.json()["job_id"]]["state"], "queued")

    def test_annual_worker_returns_all_artifacts_and_context(self):
        hourly = pd.DataFrame(
            {
                midc.DATE_COLUMN: ["01/01/2025"],
                midc.HOUR_COLUMN: [0],
                midc.MINUTE_COLUMN: [0],
                **{column: [1.0] for column in midc.MEASUREMENT_COLUMNS.values()},
            }
        )
        source = midc.MidcFetchResult(hourly, 1, 1, 0, 1, 1, 15 * 60)
        req = app.AnnualRunRequest(
            from_date="2025-01-01",
            to_date="2025-01-01",
            interval_value=15,
            interval_unit="minutes",
            iam_model=model.IAM_MODEL_MARTIN_RUIZ,
            iam_a_r=0.18,
        )

        job_id = "_test_annualjob"
        base = config.OUTPUT_DIR / job_id
        source_path = config.OUTPUT_DIR / f"{job_id}_midc_hourly.csv"
        irradiance_path = config.OUTPUT_DIR / f"{job_id}_irradiance.png"
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
            self.assertIn("input_plots", state.JOBS[job_id])
            self.assertTrue(irradiance_path.is_file())
            self.assertEqual(kwargs["iam_model"], model.IAM_MODEL_MARTIN_RUIZ)
            self.assertEqual(kwargs["iam_a_r"], 0.18)
            self.assertEqual(kwargs["expected_interval_seconds"], 15 * 60)
            return stats

        state.JOBS[job_id] = {"mode": "annual", "state": "running"}
        try:
            with (
                patch.object(app.midc, "fetch_hourly_data", return_value=source),
                patch.object(app.model, "run_model", side_effect=fake_run_model),
            ):
                run_annual._run_annual_job(job_id, req)

            self.assertEqual(state.JOBS[job_id]["state"], "done", state.JOBS[job_id])
            result = state.JOBS[job_id]["result"]
            self.assertEqual(result["mode"], "annual")
            self.assertTrue(source_path.is_file())
            self.assertTrue(irradiance_path.is_file())
            self.assertIn("irradiance_png", result["input_plots"])
            self.assertIn("monthly_png", result)
            self.assertIn("source_csv", result)
            self.assertIn("model fallback", result["warnings"])
            self.assertEqual(
                result["excel_filename"],
                "SB_Energy_Annual_Simulation_2025-01-01_to_2025-01-01.xlsx",
            )
            self.assertEqual(result["window"]["hour_convention"], "right-closed, right-labeled")
            self.assertEqual(result["window"]["interval_minutes"], 15)
            self.assertEqual(result["window"]["interval_hours"], 0.25)
            self.assertEqual(result["window"]["interval_unit"], "minutes")
            self.assertEqual(
                result["window"]["iam_model"], model.IAM_MODEL_MARTIN_RUIZ
            )
            self.assertEqual(result["window"]["iam_a_r"], 0.18)
        finally:
            source_path.unlink(missing_ok=True)
            irradiance_path.unlink(missing_ok=True)

    def test_annual_worker_fetches_only_selected_year_periods(self):
        calls = []

        def source_for(start_date, end_date, **kwargs):
            calls.append((start_date, end_date, kwargs["interval_seconds"]))
            frame = pd.DataFrame(
                {
                    midc.DATE_COLUMN: [start_date.strftime("%m/%d/%Y")],
                    midc.HOUR_COLUMN: [0],
                    **{
                        column: [1.0]
                        for column in midc.MEASUREMENT_COLUMNS.values()
                    },
                }
            )
            return midc.MidcFetchResult(frame, 1, 1, 0, 0, 0, kwargs["interval_seconds"])

        req = app.AnnualRunRequest(
            years=[2024, 2011], interval_value=6, interval_unit="hours"
        )
        job_id = "_test_selected_years"
        base = config.OUTPUT_DIR / job_id
        source_path = config.OUTPUT_DIR / f"{job_id}_midc_hourly.csv"
        annual_rows = [{"year": 2011}, {"year": 2024}]
        annual_cdf = {"eligible_years": [2024], "series": {}}
        stats = {
            "data_quality_warnings": [],
            "annual_energy_by_year": annual_rows,
            "annual_energy_cdf": annual_cdf,
            "ac_png": str(base) + "_ac_power.png",
            "energy_png": str(base) + "_cumulative_energy.png",
            "monthly_png": str(base) + "_monthly_energy.png",
            "excel": str(base) + ".xlsx",
        }

        def fake_run_model(**kwargs):
            self.assertEqual(
                [period["year"] for period in kwargs["annual_periods"]],
                [2011, 2024],
            )
            return stats

        state.JOBS[job_id] = {"mode": "annual", "state": "running"}
        try:
            with (
                patch.object(midc, "fetch_hourly_data", side_effect=source_for),
                patch.object(model, "run_model", side_effect=fake_run_model),
                patch.object(
                    run_annual, "_render_midc_input_data_plots", return_value={}
                ),
            ):
                run_annual._run_annual_job(job_id, req)

            self.assertEqual(
                calls,
                [
                    (date(2011, 2, 11), date(2011, 12, 31), 21_600),
                    (date(2024, 1, 1), date(2024, 12, 31), 21_600),
                ],
            )
            result = state.JOBS[job_id]["result"]
            self.assertEqual(result["annual_energy_by_year"], annual_rows)
            self.assertEqual(result["annual_energy_cdf"], annual_cdf)
            self.assertEqual(result["window"]["years"], [2011, 2024])
            self.assertEqual(result["source_quality"]["data_request_count"], 2)
            self.assertNotIn("chunk_count", result["source_quality"])
        finally:
            source_path.unlink(missing_ok=True)

    def test_cached_retry_retains_source_coverage_audit_without_refetch(self):
        req = app.AnnualRunRequest(
            from_date="2025-01-01",
            to_date="2025-01-01",
            interval_value=15,
            interval_unit="minutes",
        )
        job_id = "_test_annual_source_audit_retry"
        created = state.AGENT_STORE.create_job(
            job_id=job_id,
            kind="baseline",
            mode="annual",
            request=req.model_dump(),
        )
        self.assertEqual(created["id"], state.AGENT_STORE.claim_next_queued_job()["id"])
        frame = pd.DataFrame(
            {
                midc.DATE_COLUMN: ["01/01/2025"],
                midc.HOUR_COLUMN: [0],
                midc.MINUTE_COLUMN: [0],
                **{column: [1.0] for column in midc.MEASUREMENT_COLUMNS.values()},
            }
        )
        source = midc.MidcFetchResult(
            frame,
            raw_rows=1,
            data_request_count=1,
            dropped_timestamp_rows=0,
            missing_value_count=0,
            affected_interval_count=0,
            interval_seconds=15 * 60,
            partial_interval_count=1,
        )
        source_path: Path | None = None
        try:
            with (
                patch.object(midc, "fetch_hourly_data", return_value=source),
                patch.object(
                    run_annual, "_render_midc_input_data_plots", return_value={}
                ),
                patch.object(model, "run_model", side_effect=RuntimeError("after source")),
            ):
                run_annual._run_annual_job(job_id, req)

            failed = state.AGENT_STORE.get_job(job_id)
            self.assertEqual(failed["state"], "error")
            source_path = Path(failed["source_path"])
            audit = failed["provenance"]["annual_source_audit"]
            self.assertEqual(audit["source_quality"]["partial_interval_count"], 1)
            self.assertTrue(any("fewer than" in item for item in audit["warnings"]))

            state.AGENT_STORE.retry_job(job_id)
            retry = state.AGENT_STORE.claim_next_queued_job()
            stats = {
                "data_quality_warnings": [],
                "ac_png": str(config.OUTPUT_DIR / f"{job_id}_ac_power.png"),
                "energy_png": str(config.OUTPUT_DIR / f"{job_id}_cumulative_energy.png"),
                "monthly_png": str(config.OUTPUT_DIR / f"{job_id}_monthly_energy.png"),
                "excel": str(config.OUTPUT_DIR / f"{job_id}.xlsx"),
            }
            with (
                patch.object(midc, "fetch_hourly_data") as refetch,
                patch.object(
                    run_annual, "_render_midc_input_data_plots", return_value={}
                ),
                patch.object(model, "run_model", return_value=stats),
            ):
                run_annual._run_annual_job(
                    job_id,
                    app.AnnualRunRequest(**retry["request"]),
                    source_path=retry["source_path"],
                    expected_source_hash=retry["source_hash"],
                )

            refetch.assert_not_called()
            completed = state.AGENT_STORE.get_job(job_id)
            self.assertEqual(completed["state"], "done")
            self.assertEqual(
                completed["result"]["source_quality"]["partial_interval_count"],
                1,
            )
            self.assertTrue(
                any("fewer than" in item for item in completed["result"]["warnings"])
            )
            self.assertNotIn(
                "annual_source_audit",
                app._public_job(completed)["provenance"],
            )
        finally:
            if source_path is not None:
                source_path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
