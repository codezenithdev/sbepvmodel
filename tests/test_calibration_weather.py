import hashlib
import json
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np
import pandas as pd

from sbepv.ingest import calibration_weather as weather
from sbepv.ingest import midc


def minute_source(start, count=15, *, temperatures=None, winds=None):
    stamps = pd.date_range(start, periods=count, freq="min", tz="Etc/GMT+7")
    frame = pd.DataFrame({
        "Year": stamps.year, "DOY": stamps.dayofyear,
        "MST": stamps.hour * 100 + stamps.minute,
    })
    for column in midc.MEASUREMENT_COLUMNS:
        frame[column] = 500.0
    frame[weather.FIELD_COLUMNS["temp_air"]] = list(range(1, count + 1)) if temperatures is None else temperatures
    frame[weather.FIELD_COLUMNS["wind_speed"]] = [2.0] * count if winds is None else winds
    return frame


class CalibrationWeatherTests(unittest.TestCase):
    def setUp(self):
        self.raw = pd.DataFrame({
            "timestamp": ["2025-06-01 19:00:00", "2025-06-01 19:15:00"],
            "temp_air": [-999.0, 22.0], "wind_speed": [3.0, 4.0],
            "dni": [500.0, 600.0], "solaredge_measured_power": [12000.0, 15000.0],
        })
        self.report = {"issues": [{"id": "range.temp_air", "_row_positions": [0]}]}
        self.kwargs = dict(fields=["temp_air"], mode="flagged", start_utc=None, end_utc=None,
                           interval_seconds=900, requested_start="2025-06-01T19:00:00Z",
                           requested_end="2025-06-01T19:30:00Z")

    def apply(self, source, **kwargs):
        return weather.apply_weather_replacement(self.raw, self.report, source, **(self.kwargs | kwargs))

    def test_start_labeled_historian_uses_following_right_edge_minutes_only(self):
        source = minute_source("2025-06-01 12:00", 17,
                               temperatures=[60] + list(range(1, 16)) + [60])
        result, audit = self.apply(source)
        self.assertEqual(result.at[0, "temp_air"], 8.0)
        self.assertEqual(result.at[1, "temp_air"], 22.0)
        pd.testing.assert_frame_equal(result.drop(columns="temp_air"), self.raw.drop(columns="temp_air"))
        self.assertEqual(audit["events"][0]["valid_samples"], 15)
        self.assertEqual(audit["events"][0]["interval_end_utc"], "2025-06-01T19:15:00+00:00")
        self.assertEqual(self.raw.at[0, "temp_air"], -999.0)

    def test_flagged_selection_is_cell_specific_and_unions_overlapping_issues(self):
        self.report["issues"] += [{"id": "missing.temp_air", "_row_positions": [0]},
                                  {"id": "range.wind_speed", "_row_positions": [1]},
                                  {"id": "pattern.flatline.temp_air", "_row_positions": [1]}]
        result, audit = self.apply(minute_source("2025-06-01 12:01", 30), fields=["temp_air", "wind_speed"])
        self.assertEqual(audit["counts"]["selected_cells"], 2)
        self.assertEqual(result["temp_air"].tolist(), [8.0, 22.0])
        self.assertEqual(result["wind_speed"].tolist(), [3.0, 2.0])

    def test_period_selection_includes_unflagged_cells_and_excludes_end(self):
        result, audit = self.apply(minute_source("2025-06-01 12:01", 30),
                                   mode="period", start_utc="2025-06-01T19:15Z", end_utc="2025-06-01T19:30Z")
        self.assertEqual(result["temp_air"].tolist(), [-999.0, 23.0])
        self.assertEqual(audit["events"][0]["row_position"], 1)

    def test_incomplete_coverage_is_per_field_and_never_interpolates(self):
        temperatures = [20.0] * 15
        temperatures[7] = np.nan
        source = minute_source("2025-06-01 12:01", temperatures=temperatures)
        self.report["issues"].append({"id": "missing.wind_speed", "_row_positions": [0]})
        result, audit = self.apply(source, fields=["temp_air", "wind_speed"])
        self.assertEqual(result.at[0, "temp_air"], -999.0)
        self.assertEqual(result.at[0, "wind_speed"], 2.0)
        self.assertEqual(audit["counts"]["unavailable_cells"], 1)
        self.assertEqual(audit["events"][0]["valid_samples"], 14)

    def test_invalid_values_never_enter_replacement(self):
        for invalid in [float("inf"), -6999, "malformed", 61, -41]:
            with self.subTest(invalid=invalid):
                values = [20] * 15
                values[0] = invalid
                result, audit = self.apply(minute_source("2025-06-01 12:01", temperatures=values))
                self.assertEqual(result.at[0, "temp_air"], -999)
                self.assertEqual(audit["events"][0]["status"], "unavailable")

    def test_malformed_original_is_preserved_in_json_safe_audit(self):
        self.raw["temp_air"] = ["broken", "22"]
        result, audit = self.apply(minute_source("2025-06-01 12:01"))
        self.assertEqual(audit["events"][0]["original_value"], "broken")
        self.assertEqual(result.at[1, "temp_air"], "22")
        json.dumps(audit, allow_nan=False)

    def test_fixed_mst_stays_seven_hours_behind_utc_across_dst_dates(self):
        for day in ["2025-03-09", "2025-11-02"]:
            with self.subTest(day=day):
                self.raw = self.raw.iloc[:1].copy()
                self.raw["timestamp"] = [day + " 08:00:00"]
                result, audit = self.apply(minute_source(day + " 01:01"),
                                           requested_start=day + "T08:00Z", requested_end=day + "T08:15Z")
                self.assertEqual(result.at[0, "temp_air"], 8.0)
                self.assertEqual(audit["counts"]["unavailable_cells"], 0)

    def test_midnight_and_partial_request_end_use_exact_minute_overlap(self):
        self.raw = self.raw.iloc[:1].copy()
        self.raw["timestamp"] = ["2025-06-02 06:55:00"]
        result, audit = self.apply(minute_source("2025-06-01 23:56", 10),
                                   requested_start="2025-06-02T06:55Z", requested_end="2025-06-02T07:05Z")
        self.assertEqual(result.at[0, "temp_air"], 5.5)
        self.assertEqual(audit["events"][0]["expected_samples"], 10)

    def test_duplicate_midc_minutes_cannot_inflate_coverage_or_weight(self):
        source = minute_source("2025-06-01 12:01")
        duplicate = pd.concat([source, source.iloc[:1]], ignore_index=True)
        result, _ = self.apply(duplicate)
        self.assertEqual(result.at[0, "temp_air"], 8.0)
        duplicate.loc[len(duplicate) - 1, weather.FIELD_COLUMNS["temp_air"]] = 30
        with self.assertRaisesRegex(ValueError, "conflicting"):
            self.apply(duplicate)

    def test_structurally_excluded_and_duplicate_rows_are_skipped(self):
        self.raw = pd.concat([self.raw, self.raw.iloc[:1], self.raw.iloc[:1]], ignore_index=True)
        self.raw.loc[3, "timestamp"] = "invalid"
        self.report["issues"].append({"id": "timestamp.invalid", "allowed_actions": ["exclude"], "_row_positions": [3]})
        result, audit = self.apply(minute_source("2025-06-01 12:01", 30), mode="period",
                                   start_utc="2025-06-01T19:00Z", end_utc="2025-06-01T19:30Z")
        self.assertEqual(audit["selection"]["skipped_duplicate_rows"], 2)
        self.assertEqual(audit["selection"]["structurally_excluded_rows"], 1)
        self.assertEqual(result["temp_air"].tolist(), [-999, 23, -999, -999])

    def test_invalid_period_interval_fields_and_subminute_timestamps_rejected(self):
        cases = [dict(fields=["dni"]), dict(fields=["temp_air", "temp_air"]),
                 dict(interval_seconds=30), dict(interval_seconds=60.5),
                 dict(requested_start="2025-06-01T19:00:01Z"),
                 dict(mode="period", start_utc="2025-06-01T18:00Z", end_utc="2025-06-01T19:15Z"),
                 dict(mode="period", start_utc="2025-06-01T19:00Z", end_utc=None)]
        for case in cases:
            with self.subTest(case=case), self.assertRaises(ValueError):
                self.apply(minute_source("2025-06-01 12:01"), **case)

    def test_period_boundaries_require_request_grid_but_allow_clipped_final_end(self):
        for start, end in [("19:05", "19:30"), ("19:00", "19:20")]:
            with self.subTest(start=start, end=end), self.assertRaisesRegex(ValueError, "interval grid"):
                self.apply(minute_source("2025-06-01 12:01", 30), mode="period",
                           start_utc=f"2025-06-01T{start}Z", end_utc=f"2025-06-01T{end}Z")
        result, audit = self.apply(minute_source("2025-06-01 12:16", 5), mode="period",
                                   start_utc="2025-06-01T19:15Z", end_utc="2025-06-01T19:20Z",
                                   requested_end="2025-06-01T19:20Z")
        self.assertEqual(result.at[1, "temp_air"], 3.0)
        self.assertEqual(audit["events"][0]["expected_samples"], 5)

    def test_empty_selection_is_explicit_before_download(self):
        with self.assertRaisesRegex(ValueError, "No matching weather cells"):
            self.apply(minute_source("2025-06-01 12:01"), fields=["wind_speed"])

    def test_irregular_historian_rows_cannot_repair_with_overlapping_means(self):
        self.raw["timestamp"] = ["2025-06-01 19:00:00", "2025-06-01 19:05:00"]
        result, audit = self.apply(minute_source("2025-06-01 12:01", 30), mode="period",
                                   start_utc="2025-06-01T19:00Z", end_utc="2025-06-01T19:30Z")
        self.assertEqual(result["temp_air"].tolist(), self.raw["temp_air"].tolist())
        self.assertEqual([event["reason"] for event in audit["events"]],
                         ["historian_interval_overlap", "historian_interval_grid_mismatch"])

    def test_vectorized_means_match_direct_interval_means_without_rounding(self):
        count = 10000
        stamps = pd.date_range("2025-06-01T07:00Z", periods=count, freq="min")
        values = np.random.default_rng(29).uniform(-30, 50, count)
        series = pd.Series(values, index=stamps)
        starts = stamps[::15][1:-1].as_unit("ns").asi8
        ends = starts + 15 * 60 * 1_000_000_000
        counts, expected, means = weather._interval_statistics(series, starts, ends, 900)
        source_ns = series.index.as_unit("ns").asi8
        direct = [series.loc[(source_ns > start) & (source_ns <= end)].mean()
                  for start, end in zip(starts, ends)]
        np.testing.assert_allclose(means, direct, rtol=1e-13, atol=1e-13)
        self.assertTrue(np.all(counts == 15))
        self.assertTrue(np.all(expected == 15))

    def test_invalid_midc_date_does_not_roll_into_next_year(self):
        source = minute_source("2025-06-01 12:01")
        source.loc[0, "DOY"] = 366
        _, audit = self.apply(source)
        self.assertEqual(audit["counts"]["dropped_midc_timestamp_rows"], 1)
        self.assertEqual(audit["counts"]["unavailable_cells"], 1)

    def test_preparation_preserves_source_text_hash_and_caps_timeout(self):
        text = minute_source("2025-06-01 12:01").to_csv(index=False)
        with tempfile.TemporaryDirectory() as directory:
            source_path = Path(directory) / "source.csv"
            self.raw.to_csv(source_path, index=False)
            with patch.object(midc, "download_api_csv", return_value=text) as download:
                result, audit = weather.prepare_weather_replacement(source_path, self.report, **self.kwargs)
        self.assertEqual(result.at[0, "temp_air"], 8.0)
        self.assertLessEqual(download.call_args.kwargs["timeout_seconds"], 12)
        snapshot = audit["source_snapshots"][0]
        self.assertEqual(snapshot["csv_text"], text)
        self.assertEqual(snapshot["sha256"], hashlib.sha256(text.encode()).hexdigest())
        json.dumps(audit, allow_nan=False)

    def test_future_minutes_are_unavailable_without_discarding_archived_candidates(self):
        self.raw["timestamp"] = ["2025-06-01 19:00:00", "2025-06-02 19:00:00"]
        self.report["issues"][0]["_row_positions"] = [0, 1]
        self.kwargs["requested_end"] = "2025-06-02T19:15Z"
        text = minute_source("2025-06-01 12:01").to_csv(index=False)
        with tempfile.TemporaryDirectory() as directory:
            source_path = Path(directory) / "source.csv"
            self.raw.to_csv(source_path, index=False)
            with patch.object(weather, "datetime") as clock, patch.object(midc, "download_api_csv", return_value=text) as download:
                clock.now.return_value = datetime(2025, 6, 2, 20, tzinfo=timezone.utc)
                result, audit = weather.prepare_weather_replacement(source_path, self.report, **self.kwargs)
        self.assertEqual(result["temp_air"].tolist(), [8.0, 22.0])
        self.assertEqual(download.call_args.args[1], date(2025, 6, 1))
        self.assertEqual(audit["counts"]["unavailable_cells"], 1)
        self.assertTrue(audit["source_warnings"])

    def test_missing_daily_response_recovery_preserves_responses_and_later_data(self):
        error = "No data found for begin date of 20250601. Closest date: 06/02/2025"
        text = minute_source("2025-06-02 12:01").to_csv(index=False)
        with patch.object(midc, "download_api_csv", side_effect=[error, text]) as download:
            source, snapshots, warnings = weather._download_sources(date(2025, 6, 1), date(2025, 6, 2))
        self.assertEqual(download.call_count, 2)
        self.assertEqual(len(source), 15)
        self.assertEqual(len(snapshots), 2)
        self.assertTrue(warnings)

    def test_network_failure_and_budget_are_explicit_not_zero_weather(self):
        with patch.object(midc, "download_api_csv", side_effect=midc.MidcError("offline")):
            source, _, warnings = weather._download_sources(date(2025, 6, 1), date(2025, 6, 1))
        _, audit = self.apply(source)
        self.assertEqual(audit["counts"]["unavailable_cells"], 1)
        self.assertIn("offline", warnings[0])
        with patch.object(weather.time, "monotonic", side_effect=[0, 61]), patch.object(midc, "download_api_csv") as download:
            _, _, warnings = weather._download_sources(date(2025, 6, 1), date(2025, 6, 1))
        download.assert_not_called()
        self.assertIn("budget", warnings[0])

    def test_midc_download_default_timeout_remains_annual_compatible(self):
        response = Mock()
        response.read.return_value = b"csv"
        context = Mock()
        context.__enter__ = Mock(return_value=response)
        context.__exit__ = Mock(return_value=False)
        with patch.object(midc, "urlopen", return_value=context) as opened:
            self.assertEqual(midc.download_api_csv(date(2025, 1, 1), date(2025, 1, 1)), "csv")
            self.assertEqual(opened.call_args.kwargs["timeout"], midc.REQUEST_TIMEOUT_SECONDS)
            response.read1.side_effect = [b"csv", b""]
            midc.download_api_csv(date(2025, 1, 1), date(2025, 1, 1), timeout_seconds=7.5)
            self.assertEqual(opened.call_args.kwargs["timeout"], 7.5)

    def test_midc_download_deadline_stops_continuously_streaming_response(self):
        response = Mock()
        response.read1.return_value = b"data"
        context = Mock()
        context.__enter__ = Mock(return_value=response)
        context.__exit__ = Mock(return_value=False)
        with patch.object(midc, "urlopen", return_value=context), \
                patch.object(midc.time, "monotonic", side_effect=[0, 0, 0.5, 1.01]):
            with self.assertRaisesRegex(midc.MidcError, "time limit"):
                midc.download_api_csv(date(2025, 1, 1), date(2025, 1, 1), timeout_seconds=1)
        self.assertEqual(response.read1.call_count, 2)
        self.assertEqual(response.fp.raw._sock.settimeout.call_args.args, (0.5,))


if __name__ == "__main__":
    unittest.main()
