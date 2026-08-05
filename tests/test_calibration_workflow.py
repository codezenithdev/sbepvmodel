from __future__ import annotations

import json
import unittest
import uuid
from pathlib import Path

import numpy as np
import pandas as pd

from calibration_workflow import (
    HISTORIAN_COLUMNS,
    apply_frozen_seasonal_calibration,
    apply_quality_decisions,
    apply_seasonal_calibration,
    inspect_historian_csv,
    season_name,
    validate_seasonal_calibration_profile,
)
from sbe_pv_model import (
    MAX_TEMPERATURE_INTERPOLATION_GAP_ROWS,
    add_energy,
    apply_curtailment,
    calibrated_energy_balance_summary,
    parse_input_csv,
)


class CalibrationWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = (
            Path(__file__).resolve().parent
            / f"_calibration_tmp_{uuid.uuid4().hex}"
        )
        self.root.mkdir()
        self.addCleanup(self._remove_temporary_directory)

    def _remove_temporary_directory(self) -> None:
        for child in self.root.iterdir():
            child.unlink(missing_ok=True)
        self.root.rmdir()

    def _write_historian_csv(
        self, frame: pd.DataFrame, name: str = "historian.csv"
    ) -> Path:
        path = self.root / name
        frame.to_csv(path, index=False)
        return path

    @staticmethod
    def _valid_historian_frame(timestamps: list[str]) -> pd.DataFrame:
        progression = np.arange(len(timestamps), dtype=float)
        return pd.DataFrame(
            {
                "timestamp": timestamps,
                "solaredge_measured_power": 50_000.0 + progression * 1_000.0,
                "solectria_measured_power": 45_000.0 + progression * 900.0,
                "dni": 500.0 + progression * 5.0,
                "ghi": 400.0 + progression * 4.0,
                "dhi": 100.0 + progression,
                "temp_air": 20.0 + progression * 0.2,
                "wind_speed": 2.0 + progression * 0.1,
            }
        )

    def test_inspect_historian_csv_finds_core_calibration_risks(self) -> None:
        source = self._write_historian_csv(
            pd.DataFrame(
                {
                    "timestamp": [
                        "2026-06-01 15:00:00",
                        "2026-06-01 16:00:00",
                        "2026-06-01 16:00:00",
                        "2026-06-01 18:00:00",
                        "2026-06-01 19:00:00",
                    ],
                    "solaredge_measured_power": [
                        100_000.0,
                        500.0,
                        100_000.0,
                        100_000.0,
                        100_000.0,
                    ],
                    "solectria_measured_power": [95_000.0] * 5,
                    "dni": [700.0] * 5,
                    "ghi": [600.0] * 5,
                    "dhi": [100.0, None, 100.0, 100.0, 100.0],
                    "temp_air": [25.0, 25.0, 25.0, 100.0, 25.0],
                    "wind_speed": [3.0] * 5,
                }
            )
        )

        report = inspect_historian_csv(
            source,
            expected_interval_seconds=3_600,
        )
        issues = {issue["id"]: issue for issue in report["issues"]}

        expected_issue_ids = {
            "missing.dhi",
            "timestamp.duplicate",
            "timestamp.gaps",
            "range.temp_air",
            (
                "pattern.low_power_high_irradiance."
                "solaredge_measured_power"
            ),
        }
        self.assertTrue(expected_issue_ids.issubset(issues))
        self.assertEqual(issues["missing.dhi"]["row_count"], 1)
        self.assertEqual(issues["timestamp.duplicate"]["row_count"], 1)
        self.assertEqual(issues["timestamp.gaps"]["row_count"], 1)
        self.assertEqual(
            issues["range.temp_air"]["evidence"]["maximum_observed"],
            100.0,
        )
        self.assertEqual(
            issues[
                "pattern.low_power_high_irradiance."
                "solaredge_measured_power"
            ]["row_count"],
            1,
        )
        self.assertEqual(report["summary"]["missing_intervals"], 1)
        self.assertEqual(report["summary"]["status"], "action_required")
        self.assertFalse(report["summary"]["blocking"])

    def test_requested_window_detects_incomplete_edge_coverage(self) -> None:
        cases = {
            "leading": (
                [
                    "2026-06-01 01:00:00",
                    "2026-06-01 02:00:00",
                    "2026-06-01 03:00:00",
                    "2026-06-01 04:00:00",
                    "2026-06-01 05:00:00",
                ],
                1,
                0,
            ),
            "trailing": (
                [
                    "2026-06-01 00:00:00",
                    "2026-06-01 01:00:00",
                    "2026-06-01 02:00:00",
                    "2026-06-01 03:00:00",
                    "2026-06-01 04:00:00",
                ],
                0,
                1,
            ),
            "one_row": (
                ["2026-06-01 02:00:00"],
                2,
                3,
            ),
        }

        for name, (timestamps, leading, trailing) in cases.items():
            with self.subTest(name=name):
                source = self._write_historian_csv(
                    self._valid_historian_frame(timestamps),
                    f"{name}.csv",
                )
                report = inspect_historian_csv(
                    source,
                    expected_interval_seconds=3_600,
                    requested_start="2026-06-01T00:00:00Z",
                    requested_end="2026-06-01T06:00:00Z",
                )
                issues = {issue["id"]: issue for issue in report["issues"]}
                coverage = issues["timestamp.incomplete_coverage"]

                self.assertEqual(
                    coverage["evidence"]["leading_missing_intervals"],
                    leading,
                )
                self.assertEqual(
                    coverage["evidence"]["trailing_missing_intervals"],
                    trailing,
                )
                self.assertEqual(coverage["row_count"], leading + trailing)
                self.assertEqual(
                    report["summary"]["missing_intervals"],
                    leading + trailing,
                )
                self.assertNotEqual(report["summary"]["status"], "clean")

    def test_rows_outside_end_exclusive_window_are_forced_out(self) -> None:
        source = self._write_historian_csv(
            self._valid_historian_frame(
                [
                    "2026-06-01 00:00:00",
                    "2026-06-01 01:00:00",
                    "2026-06-01 02:00:00",
                    "2026-06-01 03:00:00",
                ]
            )
        )
        report = inspect_historian_csv(
            source,
            expected_interval_seconds=3_600,
            requested_start="2026-06-01T01:00:00Z",
            requested_end="2026-06-01T03:00:00Z",
        )
        issue = {
            item["id"]: item for item in report["issues"]
        }["timestamp.outside_requested_window"]
        destination = self.root / "reviewed.csv"

        cleaning = apply_quality_decisions(
            source,
            destination,
            report,
            {},
        )
        reviewed = pd.read_csv(destination)

        self.assertEqual(issue["allowed_actions"], ["exclude"])
        self.assertEqual(issue["row_count"], 2)
        self.assertEqual(cleaning["excluded_rows"], 2)
        self.assertEqual(
            reviewed["timestamp"].tolist(),
            [
                "2026-06-01 01:00:00",
                "2026-06-01 02:00:00",
            ],
        )

    def test_forced_exclusion_is_affected_and_prevents_clean_status(self) -> None:
        frame = self._valid_historian_frame(
            ["2026-06-01 00:00:00", "not-a-timestamp"]
        )
        source = self._write_historian_csv(frame)

        report = inspect_historian_csv(
            source,
            expected_interval_seconds=3_600,
        )

        self.assertEqual(
            {issue["id"] for issue in report["issues"]},
            {"timestamp.invalid"},
        )
        self.assertEqual(report["summary"]["status"], "action_required")
        self.assertEqual(report["summary"]["affected_rows"], 1)
        self.assertEqual(report["summary"]["affected_row_pct"], 50.0)

    def test_required_weather_without_usable_values_is_blocking(self) -> None:
        unusable_values = {
            "dni": [None, None],
            "ghi": ["bad", "also-bad"],
            "temp_air": [None, "bad"],
        }
        for column, values in unusable_values.items():
            with self.subTest(column=column):
                frame = self._valid_historian_frame(
                    [
                        "2026-06-01 00:00:00",
                        "2026-06-01 01:00:00",
                    ]
                )
                frame[column] = values
                source = self._write_historian_csv(
                    frame,
                    f"unusable-{column}.csv",
                )

                report = inspect_historian_csv(
                    source,
                    expected_interval_seconds=3_600,
                )

                self.assertTrue(report["summary"]["blocking"])
                self.assertIn(
                    f"data.no_usable_values.{column}",
                    {issue["id"] for issue in report["issues"]},
                )

        fallback_frame = self._valid_historian_frame(
            [
                "2026-06-01 00:00:00",
                "2026-06-01 01:00:00",
            ]
        )
        fallback_frame["dhi"] = None
        fallback_frame["wind_speed"] = None
        fallback_source = self._write_historian_csv(
            fallback_frame,
            "fallback-weather.csv",
        )
        fallback_report = inspect_historian_csv(
            fallback_source,
            expected_interval_seconds=3_600,
        )
        self.assertFalse(fallback_report["summary"]["blocking"])

    def test_historian_parser_bounds_temperature_fallback(
        self,
    ) -> None:
        frame = self._valid_historian_frame(
            [
                "2026-06-01 15:00:00",
                "2026-06-01 16:00:00",
                "2026-06-01 17:00:00",
                "2026-06-01 18:00:00",
            ]
        )
        frame.loc[1, "temp_air"] = np.nan

        parsed = parse_input_csv(
            str(self._write_historian_csv(frame, "bounded-temperature.csv"))
        )

        self.assertAlmostEqual(float(parsed["temp_air_c"].iloc[1]), 20.2)
        self.assertNotIn("calibration_fit_eligible", parsed.columns)

    def test_historian_parser_rejects_unbounded_or_all_missing_weather(
        self,
    ) -> None:
        row_count = MAX_TEMPERATURE_INTERPOLATION_GAP_ROWS + 3
        timestamps = pd.date_range(
            "2026-06-01 15:00:00",
            periods=row_count,
            freq="h",
        ).strftime("%Y-%m-%d %H:%M:%S").tolist()
        long_gap = self._valid_historian_frame(timestamps)
        long_gap.loc[
            1 : MAX_TEMPERATURE_INTERPOLATION_GAP_ROWS + 1,
            "temp_air",
        ] = np.nan
        with self.assertRaisesRegex(ValueError, "bounded fallback"):
            parse_input_csv(
                str(
                    self._write_historian_csv(
                        long_gap,
                        "unbounded-temperature.csv",
                    )
                )
            )

        for column, label in (
            ("dni", "DNI"),
            ("ghi", "GHI"),
            ("temp_air", "air temperature"),
        ):
            with self.subTest(column=column):
                all_missing = self._valid_historian_frame(timestamps)
                all_missing[column] = np.nan
                with self.assertRaisesRegex(ValueError, label):
                    parse_input_csv(
                        str(
                            self._write_historian_csv(
                                all_missing,
                                f"all-missing-{column}.csv",
                            )
                        )
                    )

    def test_empty_or_all_invalid_timestamp_source_is_blocking(self) -> None:
        invalid_rows = pd.DataFrame(
            {
                "timestamp": ["not-a-timestamp", ""],
                "solaredge_measured_power": [10_000.0, 11_000.0],
                "solectria_measured_power": [9_000.0, 10_000.0],
                "dni": [500.0, 550.0],
                "ghi": [400.0, 450.0],
                "dhi": [100.0, 110.0],
                "temp_air": [20.0, 21.0],
                "wind_speed": [2.0, 2.5],
            }
        )
        cases = {
            "header_only": pd.DataFrame(columns=HISTORIAN_COLUMNS),
            "all_invalid_timestamps": invalid_rows,
        }

        for name, frame in cases.items():
            with self.subTest(name=name):
                source = self._write_historian_csv(frame, f"{name}.csv")
                report = inspect_historian_csv(
                    source,
                    expected_interval_seconds=3_600,
                )
                issue_ids = {issue["id"] for issue in report["issues"]}

                self.assertTrue(report["summary"]["blocking"])
                self.assertEqual(report["summary"]["status"], "blocked")
                self.assertIn("data.no_valid_timestamps", issue_ids)

    def test_apply_quality_decisions_retains_and_excludes_requested_rows(
        self,
    ) -> None:
        source_frame = pd.DataFrame(
            {
                "timestamp": [
                    "2026-06-01 15:00:00",
                    "2026-06-01 16:00:00",
                    "2026-06-01 17:00:00",
                    "not-a-timestamp",
                ],
                "value": [10.0, None, 100.0, 20.0],
            }
        )
        source = self._write_historian_csv(source_frame)
        destination = self.root / "reviewed.csv"
        report = {
            "summary": {"blocking": False},
            "issues": [
                {
                    "id": "missing.value",
                    "allowed_actions": ["retain", "exclude"],
                    "recommended_action": "exclude",
                    "_row_positions": [1],
                },
                {
                    "id": "range.value",
                    "allowed_actions": ["retain", "exclude"],
                    "recommended_action": "exclude",
                    "_row_positions": [2],
                },
                {
                    "id": "timestamp.invalid",
                    "allowed_actions": ["exclude"],
                    "recommended_action": "exclude",
                    "_row_positions": [3],
                },
                {
                    "id": "timestamp.gaps",
                    "allowed_actions": [],
                    "recommended_action": "retain",
                    "_row_positions": [],
                },
            ],
        }

        with self.assertRaisesRegex(
            ValueError,
            "Unknown data-quality decision ID",
        ):
            apply_quality_decisions(
                source,
                self.root / "unknown-decision.csv",
                report,
                {"unknown.issue": "exclude"},
            )

        for fixed_issue_id in ("timestamp.invalid", "timestamp.gaps"):
            with self.subTest(fixed_issue_id=fixed_issue_id):
                with self.assertRaisesRegex(
                    ValueError,
                    "actionable issue ID",
                ):
                    apply_quality_decisions(
                        source,
                        self.root / f"{fixed_issue_id}.csv",
                        report,
                        {fixed_issue_id: "exclude"},
                    )

        with self.assertRaisesRegex(
            ValueError,
            "decision is required",
        ):
            apply_quality_decisions(
                source,
                self.root / "missing-decision.csv",
                report,
                {},
            )

        result = apply_quality_decisions(
            source,
            destination,
            report,
            {
                "missing.value": "retain",
                "range.value": "exclude",
            },
        )
        reviewed = pd.read_csv(destination)

        self.assertEqual(result["original_rows"], 4)
        self.assertEqual(result["final_rows"], 2)
        self.assertEqual(result["excluded_rows"], 2)
        self.assertIn("missing.value", result["retained_issue_ids"])
        self.assertIn("range.value", result["excluded_issue_ids"])
        self.assertIn("timestamp.invalid", result["excluded_issue_ids"])
        self.assertEqual(
            reviewed["timestamp"].tolist(),
            [
                "2026-06-01 15:00:00",
                "2026-06-01 16:00:00",
            ],
        )

    def test_add_energy_bounds_a_missing_timestamp_to_one_nominal_interval(
        self,
    ) -> None:
        index = pd.DatetimeIndex(
            [
                "2026-06-01T00:00:00Z",
                "2026-06-01T01:00:00Z",
                "2026-06-01T02:00:00Z",
                "2026-06-01T05:00:00Z",
            ]
        )
        frame = pd.DataFrame(
            {
                "se_measured_power_w": [1_000.0] * 4,
                "se_predicted_power_w": [1_000.0] * 4,
                "se_uncalibrated_power_w": [1_000.0] * 4,
                "sol_measured_power_w": [1_000.0] * 4,
                "sol_predicted_power_w": [1_000.0] * 4,
                "sol_uncalibrated_power_w": [1_000.0] * 4,
            },
            index=index,
        )

        result = add_energy(frame)

        self.assertEqual(result["dt_hours"].tolist(), [1.0, 1.0, 1.0, 1.0])
        for system in ("se", "sol"):
            for kind in ("measured", "predicted", "uncalibrated"):
                with self.subTest(system=system, kind=kind):
                    self.assertEqual(
                        result[f"{system}_{kind}_energy_kwh"].iloc[-1],
                        4.0,
                    )

    def test_season_name_uses_exact_meteorological_boundaries(self) -> None:
        expected = {
            "2026-02-28T23:59:59-07:00": "winter",
            "2026-03-01T00:00:00-07:00": "spring",
            "2026-05-31T23:59:59-06:00": "spring",
            "2026-06-01T00:00:00-06:00": "summer",
            "2026-08-31T23:59:59-06:00": "summer",
            "2026-09-01T00:00:00-06:00": "fall",
            "2026-11-30T23:59:59-07:00": "fall",
            "2026-12-01T00:00:00-07:00": "winter",
        }

        for timestamp, season in expected.items():
            with self.subTest(timestamp=timestamp):
                self.assertEqual(season_name(pd.Timestamp(timestamp)), season)

    def test_multi_season_calibration_applies_independent_system_factors(
        self,
    ) -> None:
        index = pd.DatetimeIndex(
            [
                "2026-05-31 12:00:00",
                "2026-05-31 13:00:00",
                "2026-06-01 12:00:00",
                "2026-06-01 13:00:00",
            ],
            tz="America/Denver",
        )
        frame = pd.DataFrame(
            {
                "se_measured_power_w": [
                    12_000.0,
                    12_000.0,
                    16_000.0,
                    16_000.0,
                ],
                "sol_measured_power_w": [
                    18_000.0,
                    18_000.0,
                    22_000.0,
                    22_000.0,
                ],
                "se_predicted_power_w": [10_000.0] * 4,
                "sol_predicted_power_w": [20_000.0] * 4,
                "ghi_wm2": [600.0] * 4,
            },
            index=index,
        )

        calibrated, calibration, diagnostics = apply_seasonal_calibration(
            frame,
            minimum_season_samples=2,
        )
        seasons = {
            record["season"]: record for record in calibration["seasons"]
        }

        self.assertEqual(calibration["season_count"], 2)
        self.assertEqual(set(seasons), {"spring", "summer"})
        self.assertAlmostEqual(
            seasons["spring"]["systems"]["solaredge"]["factor"],
            1.2,
        )
        self.assertAlmostEqual(
            seasons["spring"]["systems"]["solectria"]["factor"],
            0.9,
        )
        self.assertAlmostEqual(
            seasons["summer"]["systems"]["solaredge"]["factor"],
            1.6,
        )
        self.assertGreater(
            seasons["summer"]["systems"]["solaredge"]["factor"],
            1.0,
        )
        self.assertAlmostEqual(
            seasons["summer"]["systems"]["solectria"]["factor"],
            1.1,
        )
        self.assertEqual(
            calibrated["se_calibration_factor"].tolist(),
            [1.2, 1.2, 1.6, 1.6],
        )
        self.assertEqual(
            calibrated["sol_calibration_factor"].tolist(),
            [0.9, 0.9, 1.1, 1.1],
        )
        self.assertEqual(
            calibrated["se_uncalibrated_power_w"].tolist(),
            [10_000.0] * 4,
        )
        self.assertEqual(
            calibrated["se_predicted_power_w"].tolist(),
            [12_000.0, 12_000.0, 16_000.0, 16_000.0],
        )
        self.assertEqual(
            calibrated["sol_predicted_power_w"].tolist(),
            [18_000.0, 18_000.0, 22_000.0, 22_000.0],
        )
        self.assertFalse(diagnostics["applied_to_prediction"])

    def test_calibration_normalizes_utc_index_before_season_labels(self) -> None:
        index = pd.DatetimeIndex(
            [
                "2026-06-01T00:30:00Z",
                "2026-06-01T01:30:00Z",
            ]
        )
        frame = pd.DataFrame(
            {
                "se_measured_power_w": [2_000.0, 2_000.0],
                "sol_measured_power_w": [2_000.0, 2_000.0],
                "se_predicted_power_w": [2_000.0, 2_000.0],
                "sol_predicted_power_w": [2_000.0, 2_000.0],
                "ghi_wm2": [500.0, 500.0],
            },
            index=index,
        )

        calibrated, calibration, _ = apply_seasonal_calibration(
            frame,
            minimum_season_samples=1,
            expected_interval_seconds=3_600,
        )

        self.assertEqual(str(calibrated.index.tz), "America/Denver")
        self.assertEqual(calibrated.index[0].month, 5)
        self.assertEqual(
            [record["season"] for record in calibration["seasons"]],
            ["spring"],
        )

        naive = frame.copy()
        naive.index = naive.index.tz_localize(None)
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            apply_seasonal_calibration(
                naive,
                minimum_season_samples=1,
                expected_interval_seconds=3_600,
            )

    def test_curtailment_calibration_uses_all_reviewed_rows(self) -> None:
        index = pd.date_range(
            "2026-06-01 12:00:00",
            periods=2,
            freq="h",
            tz="America/Denver",
        )
        frame = pd.DataFrame(
            {
                "se_measured_power_w": [5_000.0, 10_000.0],
                "sol_measured_power_w": [5_000.0, 10_000.0],
                "se_predicted_power_w": [5_000.0, 5_000.0],
                "sol_predicted_power_w": [5_000.0, 5_000.0],
                "ghi_wm2": [500.0, 500.0],
            },
            index=index,
        )

        calibrated, calibration, _ = apply_seasonal_calibration(
            frame,
            minimum_season_samples=1,
            expected_interval_seconds=3_600,
            maximum_uncurtailed_power_w=10_000.0,
        )

        for system, factor_column in (
            ("solaredge", "se_calibration_factor"),
            ("solectria", "sol_calibration_factor"),
        ):
            with self.subTest(system=system):
                applied = calibration["seasons"][0]["systems"][system]
                self.assertEqual(applied["sample_count"], 2)
                self.assertEqual(applied["factor"], 1.5)
                self.assertEqual(applied["energy_balance_status"], "balanced")
                self.assertEqual(calibrated[factor_column].tolist(), [1.5, 1.5])

    def test_legacy_fit_eligibility_does_not_exclude_reviewed_rows(self) -> None:
        index = pd.date_range(
            "2026-06-01 12:00:00",
            periods=2,
            freq="h",
            tz="America/Denver",
        )
        frame = pd.DataFrame(
            {
                "se_measured_power_w": [5_000.0, 10_000.0],
                "sol_measured_power_w": [5_000.0, 10_000.0],
                "se_predicted_power_w": [5_000.0, 5_000.0],
                "sol_predicted_power_w": [5_000.0, 5_000.0],
                "ghi_wm2": [500.0, 500.0],
                "calibration_fit_eligible": [True, False],
            },
            index=index,
        )

        _, calibration, _ = apply_seasonal_calibration(
            frame,
            minimum_season_samples=1,
            expected_interval_seconds=3_600,
        )

        for system in ("solaredge", "solectria"):
            with self.subTest(system=system):
                observation = calibration["seasons"][0]["systems"][system]
                self.assertEqual(observation["sample_count"], 2)
                self.assertEqual(observation["factor"], 1.5)

    def test_final_factor_balances_all_reviewed_rows_not_only_fit_rows(self) -> None:
        index = pd.date_range(
            "2026-06-01 12:00:00",
            periods=2,
            freq="h",
            tz="America/Denver",
        )
        frame = pd.DataFrame(
            {
                "se_measured_power_w": [5_000.0, 5_000.0],
                "sol_measured_power_w": [5_000.0, 5_000.0],
                "se_predicted_power_w": [5_000.0, 500.0],
                "sol_predicted_power_w": [5_000.0, 500.0],
                "ghi_wm2": [500.0, 0.0],
            },
            index=index,
        )

        calibrated, calibration, _ = apply_seasonal_calibration(
            frame,
            minimum_season_samples=1,
            expected_interval_seconds=3_600,
        )
        integrated = add_energy(calibrated, expected_interval_seconds=3_600)
        summary = calibrated_energy_balance_summary(integrated)

        for system, short_name in (("solaredge", "se"), ("solectria", "sol")):
            with self.subTest(system=system):
                observation = calibration["seasons"][0]["systems"][system]
                self.assertAlmostEqual(observation["factor"], 10_000.0 / 5_500.0)
                self.assertEqual(
                    observation["source"],
                    "all_reviewed_rows_in_season",
                )
                self.assertNotIn("fit_factor", observation)
                self.assertNotIn("energy_balance_factor", observation)
                self.assertAlmostEqual(
                    integrated[f"{short_name}_predicted_energy_kwh"].iloc[-1],
                    integrated[f"{short_name}_measured_energy_kwh"].iloc[-1],
                )
                self.assertEqual(summary["systems"][system]["status"], "balanced")

        self.assertNotIn("daylight_filter", calibration)
        self.assertNotIn("overall_period", calibration)
        self.assertEqual(
            calibration["application_method"],
            "curtailment_aware_all_reviewed_row_energy_ratio",
        )

    def test_factor_does_not_require_a_daylight_column(self) -> None:
        index = pd.date_range(
            "2026-06-01 00:00:00",
            periods=2,
            freq="h",
            tz="America/Denver",
        )
        frame = pd.DataFrame(
            {
                "se_measured_power_w": [1_000.0, 3_000.0],
                "sol_measured_power_w": [2_000.0, 6_000.0],
                "se_predicted_power_w": [1_000.0, 1_000.0],
                "sol_predicted_power_w": [2_000.0, 2_000.0],
            },
            index=index,
        )

        calibrated, calibration, _ = apply_seasonal_calibration(
            frame,
            expected_interval_seconds=3_600,
        )

        systems = calibration["seasons"][0]["systems"]
        self.assertEqual(systems["solaredge"]["factor"], 2.0)
        self.assertEqual(systems["solectria"]["factor"], 2.0)
        self.assertEqual(
            calibrated["se_predicted_power_w"].tolist(),
            [2_000.0, 2_000.0],
        )
        self.assertEqual(
            calibrated["sol_predicted_power_w"].tolist(),
            [4_000.0, 4_000.0],
        )

    def test_energy_balance_solves_through_curtailment_and_rejects_infeasible_target(self) -> None:
        index = pd.date_range(
            "2026-06-01 12:00:00",
            periods=2,
            freq="h",
            tz="America/Denver",
        )
        base = {
            "se_predicted_power_w": [10_000.0, 1_000.0],
            "sol_predicted_power_w": [10_000.0, 1_000.0],
            "ghi_wm2": [500.0, 500.0],
        }
        feasible = pd.DataFrame(
            {
                **base,
                "se_measured_power_w": [6_000.0, 6_000.0],
                "sol_measured_power_w": [6_000.0, 6_000.0],
            },
            index=index,
        )
        calibrated, calibration, _ = apply_seasonal_calibration(
            feasible,
            minimum_season_samples=1,
            expected_interval_seconds=3_600,
            maximum_uncurtailed_power_w=10_000.0,
        )
        integrated = add_energy(
            apply_curtailment(calibrated, 10.0),
            expected_interval_seconds=3_600,
        )
        self.assertAlmostEqual(
            integrated["se_predicted_energy_kwh"].iloc[-1],
            integrated["se_measured_energy_kwh"].iloc[-1],
        )
        self.assertAlmostEqual(
            calibration["seasons"][0]["systems"]["solaredge"]["factor"],
            2.0,
        )

        infeasible = feasible.copy()
        infeasible["se_measured_power_w"] = [11_000.0, 11_000.0]
        infeasible["sol_measured_power_w"] = [11_000.0, 11_000.0]
        with self.assertRaisesRegex(ValueError, "cannot be matched"):
            apply_seasonal_calibration(
                infeasible,
                minimum_season_samples=1,
                expected_interval_seconds=3_600,
                maximum_uncurtailed_power_w=10_000.0,
            )

    def test_driver_diagnostics_uses_available_features_when_dhi_is_all_nan(
        self,
    ) -> None:
        sample_count = 48
        index = pd.date_range(
            "2026-06-01 00:00:00",
            periods=sample_count,
            freq="h",
            tz="America/Denver",
        )
        rng = np.random.default_rng(20260728)
        predicted = rng.uniform(10_000.0, 15_000.0, sample_count)
        temperature = rng.uniform(15.0, 35.0, sample_count)
        wind_speed = rng.uniform(1.0, 7.0, sample_count)
        ghi = rng.uniform(300.0, 800.0, sample_count)
        dni = rng.uniform(400.0, 1_000.0, sample_count)
        ratio = np.exp(
            0.02 * (temperature - temperature.mean()) / temperature.std()
            - 0.01 * (wind_speed - wind_speed.mean()) / wind_speed.std()
        )
        frame = pd.DataFrame(
            {
                "se_measured_power_w": predicted * ratio,
                "sol_measured_power_w": predicted * (ratio + 0.03),
                "se_predicted_power_w": predicted,
                "sol_predicted_power_w": predicted,
                "ghi_wm2": ghi,
                "dni_wm2": dni,
                "dhi_wm2": np.nan,
                "temp_air_c": temperature,
                "wind_speed_ms": wind_speed,
            },
            index=index,
        )

        _, _, diagnostics = apply_seasonal_calibration(
            frame,
            expected_interval_seconds=3_600,
        )

        for system in ("solaredge", "solectria"):
            with self.subTest(system=system):
                diagnostic = diagnostics["systems"][system]
                self.assertEqual(diagnostic["status"], "available")
                self.assertEqual(diagnostic["sample_count"], sample_count)
                self.assertTrue(diagnostic["drivers"])
                self.assertNotIn(
                    "dhi_wm2",
                    {driver["variable"] for driver in diagnostic["drivers"]},
                )

    def test_nearly_collinear_driver_features_remain_strict_json_safe(
        self,
    ) -> None:
        sample_count = 40
        index = pd.date_range(
            "2026-06-01 00:00:00",
            periods=sample_count,
            freq="h",
            tz="America/Denver",
        )
        progression = np.linspace(-1.0, 1.0, sample_count)
        alternating = np.resize(np.array([-1.0, 1.0]), sample_count)
        ratio = np.exp(0.1 * alternating)
        frame = pd.DataFrame(
            {
                "se_measured_power_w": 2_000.0 * ratio,
                "sol_measured_power_w": 2_000.0 * ratio,
                "se_predicted_power_w": 2_000.0,
                "sol_predicted_power_w": 2_000.0,
                "ghi_wm2": 500.0,
                "dni_wm2": 600.0,
                "dhi_wm2": 100.0,
                "temp_air_c": 25.0 + progression * 5.0,
                "wind_speed_ms": (
                    5.0 + progression + 1e-8 * alternating
                ),
            },
            index=index,
        )

        _, calibration, diagnostics = apply_seasonal_calibration(
            frame,
            expected_interval_seconds=3_600,
        )

        encoded = json.dumps(
            {
                "calibration": calibration,
                "diagnostics": diagnostics,
            },
            allow_nan=False,
        )
        self.assertTrue(encoded)

    def test_frozen_profile_applies_exact_denver_season_factors_without_fit(
        self,
    ) -> None:
        index = pd.DatetimeIndex(
            [
                "2026-06-01T00:30:00Z",  # May 31 in Denver: spring
                "2026-06-01T18:00:00Z",  # June 1 in Denver: summer
            ]
        )
        frame = pd.DataFrame(
            {
                "se_predicted_power_w": [10_000.0, 10_000.0],
                "sol_predicted_power_w": [20_000.0, 20_000.0],
                # Deliberately contradictory measurements must not affect reuse.
                "se_measured_power_w": [1.0, 1_000_000.0],
                "sol_measured_power_w": [1_000_000.0, 1.0],
            },
            index=index,
        )
        se_spring = 1.1234567890123
        profile = {
            "schema_version": 1,
            "origin_job_id": "reviewed-baseline",
            "origin_source_sha256": "a" * 64,
            "origin_review_id": "review-1",
            "seasonal_factors": {
                "spring": {
                    "solaredge": se_spring,
                    "solectria": 0.8,
                },
                "summer": {
                    "solaredge": 1.4,
                    "solectria": 0.9,
                },
            },
            "fit_metadata": {"seasons": []},
            "factor_driver_diagnostics": {
                "method": "baseline-only",
                "systems": {},
            },
        }

        calibrated, calibration, diagnostics = (
            apply_frozen_seasonal_calibration(
                frame,
                calibration_profile=profile,
            )
        )

        self.assertEqual(str(calibrated.index.tz), "America/Denver")
        self.assertEqual(
            calibrated["se_calibration_factor"].tolist(),
            [se_spring, 1.4],
        )
        self.assertEqual(
            calibrated["se_predicted_power_w"].tolist(),
            [10_000.0 * se_spring, 14_000.0],
        )
        self.assertEqual(
            calibrated["sol_predicted_power_w"].tolist(),
            [16_000.0, 18_000.0],
        )
        self.assertEqual(
            calibration["application_mode"],
            "frozen_baseline_profile",
        )
        self.assertEqual(diagnostics["method"], "baseline-only")
        json.dumps(
            {"calibration": calibration, "diagnostics": diagnostics},
            allow_nan=False,
        )

    def test_frozen_profile_rejects_missing_season_and_invalid_factor(
        self,
    ) -> None:
        base = {
            "schema_version": 1,
            "origin_job_id": "reviewed-baseline",
            "origin_source_sha256": "b" * 64,
            "origin_review_id": "review-2",
            "seasonal_factors": {
                "summer": {"solaredge": 1.0, "solectria": 1.0}
            },
        }
        frame = pd.DataFrame(
            {
                "se_predicted_power_w": [1_000.0],
                "sol_predicted_power_w": [1_000.0],
            },
            index=pd.DatetimeIndex(
                ["2026-01-15T12:00:00Z"]
            ),
        )
        with self.assertRaisesRegex(ValueError, "winter"):
            apply_frozen_seasonal_calibration(
                frame,
                calibration_profile=base,
            )

        for invalid in (True, "1.0", float("nan"), float("inf"), -0.1):
            with self.subTest(invalid=invalid):
                profile = {
                    **base,
                    "seasonal_factors": {
                        "summer": {
                            "solaredge": invalid,
                            "solectria": 1.0,
                        }
                    },
                }
                with self.assertRaisesRegex(
                    ValueError, "finite non-negative"
                ):
                    validate_seasonal_calibration_profile(profile)

    def test_fitted_factor_metadata_keeps_exact_applied_value(self) -> None:
        frame = pd.DataFrame(
            {
                "se_measured_power_w": [12_345.678901234],
                "sol_measured_power_w": [9_876.543210987],
                "se_predicted_power_w": [10_000.0],
                "sol_predicted_power_w": [10_000.0],
                "ghi_wm2": [500.0],
            },
            index=pd.date_range(
                "2026-06-01 12:00:00",
                periods=1,
                freq="h",
                tz="America/Denver",
            ),
        )
        calibrated, calibration, _ = apply_seasonal_calibration(
            frame,
            minimum_season_samples=1,
            expected_interval_seconds=3_600,
        )
        record = calibration["seasons"][0]["systems"]
        self.assertEqual(
            record["solaredge"]["factor"],
            calibrated["se_calibration_factor"].iloc[0],
        )
        self.assertEqual(
            record["solectria"]["factor"],
            calibrated["sol_calibration_factor"].iloc[0],
        )


if __name__ == "__main__":
    unittest.main()
