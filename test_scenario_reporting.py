import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from uuid import uuid4

import pandas as pd

import sbe_pv_model as model
import scenario_reporting as reporting


TEST_TEMP_ROOT = Path(__file__).resolve().parent / "outputs"


def unique_output_path(suffix):
    return TEST_TEMP_ROOT / f"_test_scenario_reporting_{uuid4().hex}{suffix}"


def make_time_series(
    *,
    start="2026-06-20 06:00",
    se_predicted=(30000.0, 30000.0, 40000.0),
    sol_predicted=(20000.0, 30000.0, 30000.0),
    se_measured=(30000.0, 30000.0, 30000.0),
    sol_measured=(30000.0, 30000.0, 40000.0),
):
    timestamps = pd.date_range(start, periods=3, freq="h")
    frame = pd.DataFrame(
        {
            "timestamp_local_naive": timestamps,
            "timestamp_utc_naive": timestamps + pd.Timedelta(hours=6),
            "se_measured_power_w": se_measured,
            "se_predicted_power_w": se_predicted,
            "sol_measured_power_w": sol_measured,
            "sol_predicted_power_w": sol_predicted,
            "dt_hours": 1.0,
        }
    )
    for system in ("se", "sol"):
        for kind in ("measured", "predicted"):
            frame[f"{system}_{kind}_energy_kwh"] = (
                frame[f"{system}_{kind}_power_w"] / 1000.0
            ).cumsum()
    return frame


def workbook_value(frame, *, annual=False):
    return reporting.ModelWorkbook(
        path=None,
        time_series=frame,
        run_info={
            "annual_mode": annual,
            "version": "1",
            "dhi_source": "measured",
            "curtailment_scope": "predicted_only",
        },
        monthly_energy=None,
        mode="annual" if annual else "validation",
    )


def write_model_workbook(path, frame, *, annual=False):
    run_info = pd.DataFrame(
        [
            ("annual_mode", annual),
            ("version", "1"),
            ("run_timestamp_utc", "2026-07-20T12:00:00+00:00"),
            ("dhi_source", "measured"),
            ("curtailment_scope", "predicted_only"),
            ("data_quality_warnings", "None"),
        ],
        columns=["parameter", "value"],
    )
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        frame.to_excel(writer, sheet_name="time_series", index=False)
        run_info.to_excel(writer, sheet_name="run_info", index=False)


class CurtailmentSafetyTests(unittest.TestCase):
    def test_curtailment_caps_only_predicted_power_and_does_not_mutate_input(self):
        frame = pd.DataFrame(
            {
                "se_measured_power_w": [150000.0, 90000.0],
                "sol_measured_power_w": [170000.0, 80000.0],
                "se_predicted_power_w": [160000.0, 70000.0],
                "sol_predicted_power_w": [180000.0, 60000.0],
            }
        )
        original = frame.copy(deep=True)

        curtailed = model.apply_curtailment(frame, 100.0)

        pd.testing.assert_series_equal(
            curtailed["se_measured_power_w"], original["se_measured_power_w"]
        )
        pd.testing.assert_series_equal(
            curtailed["sol_measured_power_w"], original["sol_measured_power_w"]
        )
        self.assertEqual(curtailed["se_predicted_power_w"].tolist(), [100000.0, 70000.0])
        self.assertEqual(curtailed["sol_predicted_power_w"].tolist(), [100000.0, 60000.0])
        pd.testing.assert_frame_equal(frame, original)

    def test_run_metadata_and_result_declare_predicted_only_scope(self):
        index = pd.date_range("2026-06-20 06:00", periods=2, freq="h", tz=model.TIMEZONE)
        parsed = pd.DataFrame(
            {
                "timestamp_utc": index.tz_convert("UTC"),
                "se_measured_power_w": [2000.0, 2500.0],
                "sol_measured_power_w": [2100.0, 2600.0],
                "dni_wm2": [500.0, 600.0],
                "ghi_wm2": [400.0, 500.0],
                "dhi_wm2": [100.0, 110.0],
                "temp_air_c": [20.0, 21.0],
                "wind_speed_ms": [2.0, 2.0],
            },
            index=index,
        )

        def fake_predict(frame, **_kwargs):
            output = frame.copy()
            output["se_predicted_power_w"] = [2000.0, 3000.0]
            output["sol_predicted_power_w"] = [1800.0, 2800.0]
            return output, "measured"

        captured = {}

        def fake_write(_frame, _path, meta, annual_mode=False):
            captured.update(meta)

        with (
            patch.object(model, "parse_input_csv", return_value=parsed),
            patch.object(model, "predict_ac_power", side_effect=fake_predict),
            patch.object(model, "plot_results"),
            patch.object(model, "write_excel", side_effect=fake_write),
        ):
            result = model.run_model(
                input_csv="ignored.csv",
                output_base="ignored",
                curtailment_enabled=True,
                curtailment_limit_kw=1.5,
            )

        self.assertEqual(result["curtailment_scope"], "predicted_only")
        self.assertEqual(captured["curtailment_scope"], "predicted_only")
        self.assertEqual(result["se_measured_kwh"], 4.5)
        self.assertEqual(result["se_predicted_kwh"], 3.0)


class SourceHashTests(unittest.TestCase):
    def test_sha256_and_verification_are_deterministic(self):
        source = unique_output_path(".csv")
        try:
            source.write_bytes(b"abc")
            expected = hashlib.sha256(b"abc").hexdigest()

            self.assertEqual(reporting.sha256_file(source, chunk_size=1), expected)
            self.assertEqual(reporting.verify_source_sha256(source, expected.upper()), expected)
            with self.assertRaises(reporting.SourceFingerprintMismatch):
                reporting.verify_source_sha256(source, "0" * 64)
        finally:
            source.unlink(missing_ok=True)


class ComparisonMetricTests(unittest.TestCase):
    def test_same_input_metrics_residuals_gap_and_attribution(self):
        baseline = workbook_value(make_time_series())
        candidate = workbook_value(
            make_time_series(
                se_predicted=(30000.0, 30000.0, 35000.0),
                sol_predicted=(30000.0, 30000.0, 30000.0),
            )
        )

        result = reporting.compute_comparison(
            baseline,
            candidate,
            comparison_type="same_input",
            baseline_source_sha256="a" * 64,
            candidate_source_sha256="a" * 64,
            baseline_request={"backtrack": True, "iam_model": "physical"},
            candidate_request={"backtrack": False, "iam_model": "physical"},
        )

        solar_edge = result["systems"]["solaredge"]
        solectria = result["systems"]["solectria"]
        self.assertEqual(solar_edge["baseline_predicted_kwh"], 100.0)
        self.assertEqual(solar_edge["candidate_predicted_kwh"], 95.0)
        self.assertEqual(solar_edge["delta_kwh"], -5.0)
        self.assertEqual(solar_edge["delta_pct"], -5.0)
        self.assertAlmostEqual(
            solar_edge["validation"]["absolute_error_improvement_pp"],
            5.55555556,
        )
        self.assertEqual(solectria["delta_kwh"], 10.0)
        self.assertEqual(solectria["delta_pct"], 12.5)
        self.assertEqual(
            solectria["validation"]["absolute_error_improvement_pp"], 10.0
        )
        self.assertEqual(result["cross_system_gap"]["baseline_kwh"], 20.0)
        self.assertEqual(result["cross_system_gap"]["candidate_kwh"], 5.0)
        self.assertEqual(result["cross_system_gap"]["change_kwh"], -15.0)
        self.assertTrue(result["invariants"]["measured_series_match"])
        self.assertEqual(result["attribution"]["scope"], "single_parameter")
        self.assertTrue(result["attribution"]["individual_parameter_attribution_allowed"])
        json.dumps(result, allow_nan=False)

    def test_zero_denominators_return_null(self):
        zero_baseline = make_time_series(
            se_predicted=(0.0, 0.0, 0.0),
            se_measured=(0.0, 0.0, 0.0),
        )
        zero_candidate = make_time_series(
            se_predicted=(1000.0, 0.0, 0.0),
            se_measured=(0.0, 0.0, 0.0),
        )

        result = reporting.compute_comparison(
            workbook_value(zero_baseline),
            workbook_value(zero_candidate),
            comparison_type="same_input",
            baseline_source_sha256="b" * 64,
            candidate_source_sha256="b" * 64,
        )

        solar_edge = result["systems"]["solaredge"]
        self.assertIsNone(solar_edge["delta_pct"])
        self.assertIsNone(solar_edge["validation"]["baseline_residual_pct"])
        self.assertIsNone(solar_edge["validation"]["candidate_residual_pct"])
        self.assertIsNone(
            solar_edge["validation"]["absolute_error_improvement_pp"]
        )
        json.dumps(result, allow_nan=False)

    def test_same_input_rejects_source_or_measured_mismatch(self):
        baseline = workbook_value(make_time_series())
        candidate = workbook_value(make_time_series())

        with self.assertRaises(reporting.ComparisonInvariantError):
            reporting.compute_comparison(
                baseline,
                candidate,
                comparison_type="same_input",
                baseline_source_sha256="a" * 64,
                candidate_source_sha256="b" * 64,
            )

        changed_measured = make_time_series()
        changed_measured.loc[0, "se_measured_power_w"] += 1.0
        changed_measured["se_measured_energy_kwh"] = (
            changed_measured["se_measured_power_w"] / 1000.0
        ).cumsum()
        with self.assertRaises(reporting.ComparisonInvariantError):
            reporting.compute_comparison(
                baseline,
                workbook_value(changed_measured),
                comparison_type="same_input",
                baseline_source_sha256="a" * 64,
                candidate_source_sha256="a" * 64,
            )

    def test_cross_run_is_labeled_non_causal(self):
        result = reporting.compute_comparison(
            workbook_value(make_time_series()),
            workbook_value(make_time_series(start="2026-07-20 06:00")),
            comparison_type="cross_run",
            baseline_source_sha256="a" * 64,
            candidate_source_sha256="b" * 64,
            baseline_request={"from_date": "2026-06-20"},
            candidate_request={"from_date": "2026-07-20"},
        )

        self.assertFalse(result["like_for_like"])
        self.assertIn("Non-like-for-like", result["caveat"])
        self.assertEqual(result["attribution"]["scope"], "descriptive_only")
        self.assertFalse(result["attribution"]["causal_attribution_allowed"])
        self.assertFalse(result["invariants"]["timestamps_aligned"])


class ArtifactTests(unittest.TestCase):
    def test_same_input_report_contains_required_sheets_and_artifacts(self):
        token = uuid4().hex
        source = TEST_TEMP_ROOT / f"_test_scenario_reporting_{token}_source.csv"
        baseline_path = TEST_TEMP_ROOT / f"_test_scenario_reporting_{token}_baseline.xlsx"
        candidate_path = TEST_TEMP_ROOT / f"_test_scenario_reporting_{token}_candidate.xlsx"
        output_base = TEST_TEMP_ROOT / f"_test_scenario_reporting_{token}_scenario"
        generated = [
            Path(f"{output_base}_comparison.xlsx"),
            Path(f"{output_base}_comparison_power.png"),
            Path(f"{output_base}_comparison_energy.png"),
            Path(f"{output_base}_comparison_monthly.png"),
        ]
        try:
            source.write_text("timestamp,value\n2026-06-20,1\n", encoding="utf-8")
            write_model_workbook(baseline_path, make_time_series())
            write_model_workbook(
                candidate_path,
                make_time_series(
                    se_predicted=(30000.0, 30000.0, 35000.0),
                    sol_predicted=(30000.0, 30000.0, 30000.0),
                ),
            )

            result = reporting.generate_comparison_artifacts(
                baseline_path,
                candidate_path,
                output_base,
                baseline_job_id="baseline-job",
                candidate_job_id="candidate-job",
                baseline_request={"backtrack": True},
                candidate_request={"backtrack": False},
                baseline_source_path=source,
                candidate_source_path=source,
                comparison_type="same_input",
            )

            for key in ("workbook", "power_png", "energy_png"):
                artifact = result["artifacts"][key]
                self.assertTrue(Path(artifact["path"]).is_file())
                self.assertTrue(artifact["url"].startswith("/outputs/"))
            with pd.ExcelFile(result["artifacts"]["workbook"]["path"]) as workbook:
                self.assertEqual(
                    workbook.sheet_names[:5],
                    [
                        "summary",
                        "parameter_changes",
                        "baseline_time_series",
                        "scenario_time_series",
                        "provenance",
                    ],
                )
                self.assertIn("aligned_delta", workbook.sheet_names)
                self.assertNotIn("monthly_comparison", workbook.sheet_names)
            self.assertEqual(
                result["provenance"]["candidate"]["curtailment_scope"],
                "predicted_only",
            )
            json.dumps(result, allow_nan=False)
        finally:
            for path in [source, baseline_path, candidate_path, *generated]:
                path.unlink(missing_ok=True)

    def test_cross_run_annual_report_uses_monthly_sheet_without_aligned_delta(self):
        token = uuid4().hex
        source_a = TEST_TEMP_ROOT / f"_test_scenario_reporting_{token}_baseline.csv"
        source_b = TEST_TEMP_ROOT / f"_test_scenario_reporting_{token}_candidate.csv"
        baseline_path = TEST_TEMP_ROOT / f"_test_scenario_reporting_{token}_baseline.xlsx"
        candidate_path = TEST_TEMP_ROOT / f"_test_scenario_reporting_{token}_candidate.xlsx"
        output_base = TEST_TEMP_ROOT / f"_test_scenario_reporting_{token}_annual"
        generated = [
            Path(f"{output_base}_comparison.xlsx"),
            Path(f"{output_base}_comparison_power.png"),
            Path(f"{output_base}_comparison_energy.png"),
            Path(f"{output_base}_comparison_monthly.png"),
        ]
        try:
            source_a.write_text("baseline", encoding="utf-8")
            source_b.write_text("candidate", encoding="utf-8")
            write_model_workbook(
                baseline_path, make_time_series(start="2025-01-01"), annual=True
            )
            write_model_workbook(
                candidate_path, make_time_series(start="2025-02-01"), annual=True
            )

            result = reporting.generate_comparison_artifacts(
                baseline_path,
                candidate_path,
                output_base,
                baseline_job_id="annual-baseline",
                candidate_job_id="annual-candidate",
                baseline_request={"from_date": "2025-01-01"},
                candidate_request={"from_date": "2025-02-01"},
                baseline_source_path=source_a,
                candidate_source_path=source_b,
                comparison_type="cross_run",
                mode="annual",
            )

            self.assertIsNotNone(result["artifacts"]["monthly_png"])
            self.assertTrue(Path(result["artifacts"]["monthly_png"]["path"]).is_file())
            with pd.ExcelFile(result["artifacts"]["workbook"]["path"]) as workbook:
                self.assertIn("monthly_comparison", workbook.sheet_names)
                self.assertNotIn("aligned_delta", workbook.sheet_names)
            self.assertEqual(result["comparison"]["comparison_type"], "cross_run")
            self.assertFalse(result["comparison"]["like_for_like"])
        finally:
            for path in [source_a, source_b, baseline_path, candidate_path, *generated]:
                path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
