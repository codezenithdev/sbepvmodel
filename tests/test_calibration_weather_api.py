from __future__ import annotations

import shutil
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from sbepv import model, weather_evidence
from sbepv.api import review_store
from sbepv.ingest import midc
from tests import test_calibration_api as review_tests


class CalibrationWeatherApiTests(unittest.TestCase):
    # Reuse the existing safe API fixture, without rerunning inherited test cases.
    setUp = review_tests.CalibrationReviewApiTests.setUp
    _start_patch = review_tests.CalibrationReviewApiTests._start_patch
    _restore_jobs = review_tests.CalibrationReviewApiTests._restore_jobs
    _write_synthetic_historian_csv = review_tests.CalibrationReviewApiTests._write_synthetic_historian_csv
    _review_request = staticmethod(review_tests.CalibrationReviewApiTests._review_request)
    _recommended_decisions = staticmethod(review_tests.CalibrationReviewApiTests._recommended_decisions)
    _create_review = review_tests.CalibrationReviewApiTests._create_review

    def _remove_temporary_root(self):
        # Windows scanners may briefly hold a just-written CSV. Keep cleanup
        # bounded and fail if it still cannot remove this test's isolated root.
        resolved = self.root.resolve()
        self.assertEqual(resolved.parent, Path(__file__).resolve().parent)
        self.assertTrue(resolved.name.startswith("_calibration_api_tmp_"))
        for attempt in range(5):
            try:
                if resolved.exists():
                    shutil.rmtree(resolved)
                return
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.2 * (attempt + 1))

    def _midc_csv(self, *, missing_temperature=False):
        timestamps = pd.date_range("2026-06-01 08:01", periods=360, freq="min")
        source = pd.DataFrame({"Year": timestamps.year, "DOY": timestamps.dayofyear, "MST": timestamps.hour * 100 + timestamps.minute})
        for column in midc.MEASUREMENT_COLUMNS:
            source[column] = 500.0
        source["Air Temperature [deg C]"] = 23.0
        source["Avg Wind Speed @ 10m [m/s]"] = 3.0
        if missing_temperature:
            source.loc[180, "Air Temperature [deg C]"] = -6999
        return source.to_csv(index=False)

    def _preview(self, parent, request=None, *, missing_temperature=False):
        with patch.object(midc, "download_api_csv", return_value=self._midc_csv(missing_temperature=missing_temperature)) as download:
            response = self.client.post(f"/api/calibration-reviews/{parent['review_id']}/weather-preview", json=request or {"fields": ["temp_air"], "mode": "flagged"})
        return response, download

    def test_preview_repairs_only_flagged_weather_and_freezes_all_sources(self):
        parent = self._create_review().json()
        parent_path = self.review_dir / f"{parent['review_id']}.raw.csv"
        before = parent_path.read_bytes()
        response, download = self._preview(parent)
        self.assertEqual(response.status_code, 200, response.text)
        child = response.json()
        self.assertNotEqual(parent["review_id"], child["review_id"])
        self.assertEqual(parent_path.read_bytes(), before)
        self.assertNotIn("range.temp_air", {issue["id"] for issue in child["report"]["issues"]})
        self.assertEqual(child["weather_replacement"]["replaced_cells"], 1)
        self.assertEqual(child["weather_replacement"]["events"][0]["replacement_value"], 23)
        self.assertNotIn("evidence_path", child["weather_replacement"])
        record = review_store._load_calibration_review(child["review_id"])
        effective = pd.read_csv(record["source_path"])
        original = pd.read_csv(parent_path)
        pd.testing.assert_frame_equal(effective.drop(columns="temp_air"), original.drop(columns="temp_air"))
        evidence = weather_evidence.load_weather_evidence(record["weather_replacement"])
        self.assertEqual(evidence["original_csv_text"].encode(), before)
        self.assertEqual(len(evidence["audit"]["source_snapshots"]), 1)
        self.assertEqual(self.store.list_jobs(limit=10), [])
        self.model_run.assert_not_called()
        download.assert_called_once()

    def test_known_bad_period_replaces_plausible_values_and_pages_preview(self):
        parent = self._create_review().json()
        response, _ = self._preview(parent, {"fields": ["temp_air", "wind_speed"], "mode": "period", "from_date": "2026-06-01", "from_time": "09:00", "to_date": "2026-06-01", "to_time": "11:00"})
        self.assertEqual(response.status_code, 200, response.text)
        child = response.json()
        self.assertEqual(child["weather_replacement"]["replaced_cells"], 4)
        page = self.client.get(f"/api/calibration-reviews/{child['review_id']}/weather-preview", params={"offset": 1, "limit": 2})
        self.assertEqual(page.status_code, 200)
        self.assertEqual(len(page.json()["events"]), 2)
        self.assertEqual(page.json()["total_events"], 4)
        self.assertEqual(page.json()["offset"], 1)

    def test_missing_midc_requires_explicit_decision_without_changing_original(self):
        parent = self._create_review().json()
        response, _ = self._preview(parent, missing_temperature=True)
        self.assertEqual(response.status_code, 200, response.text)
        child = response.json()
        self.assertEqual(child["weather_replacement"]["unavailable_cells"], 1)
        issue = next(issue for issue in child["report"]["issues"] if issue["id"] == "midc.unavailable.temp_air")
        self.assertTrue(issue["requires_explicit_decision"])
        decisions = self._recommended_decisions(child["report"])
        del decisions["midc.unavailable.temp_air"]
        run = self.client.post(f"/api/calibration-reviews/{child['review_id']}/run", json={"decisions": decisions})
        self.assertEqual(run.status_code, 422)
        self.assertIn("midc.unavailable.temp_air", run.text)
        self.assertEqual(self.store.list_jobs(limit=10), [])

    def test_missing_entire_temperature_series_becomes_reviewable_after_replacement(self):
        original_writer = self.historian_run.side_effect
        def missing_source(**kwargs):
            count = original_writer(**kwargs)
            path = Path(kwargs["output_csv"])
            frame = pd.read_csv(path)
            frame["temp_air"] = float("nan")
            frame.to_csv(path, index=False)
            return count
        self.historian_run.side_effect = missing_source
        parent = self._create_review().json()
        self.assertEqual(parent["state"], "blocked")
        response, _ = self._preview(parent)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertNotEqual(response.json()["state"], "blocked")
        self.assertEqual(response.json()["weather_replacement"]["replaced_cells"], 6)

    def test_confirmation_is_idempotent_and_durable_evidence_survives_cleanup(self):
        parent = self._create_review().json()
        response, _ = self._preview(parent)
        child = response.json()
        decisions = self._recommended_decisions(child["report"])
        endpoint = f"/api/calibration-reviews/{child['review_id']}/run"
        with patch.object(midc, "download_api_csv", side_effect=AssertionError("confirmation must never refetch")):
            first = self.client.post(endpoint, json={"decisions": decisions})
            second = self.client.post(endpoint, json={"decisions": decisions})
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(first.json(), second.json())
        quality = first.json()["data_quality"]
        self.assertNotIn("evidence_path", quality["weather_replacement"])
        self.assertEqual(quality["weather_replacement"]["used_replaced_cells"], 1)
        self.assertEqual(quality["weather_replacement"]["replacement_cells_by_season"], {"summer": 1})
        record = review_store._load_calibration_review(child["review_id"])
        quality = record["quality_context"]
        parsed = model.parse_input_csv(record["cleaned_source_path"])
        self.assertEqual(parsed.loc[pd.Timestamp("2026-06-01T18:00:00Z"), "temp_air_c"], 23)
        review_store._cleanup_expired_calibration_reviews(now=datetime.now(timezone.utc) + timedelta(days=2))
        self.assertTrue(Path(record["cleaned_source_path"]).is_file())
        self.assertTrue(Path(quality["weather_replacement"]["evidence_path"]).is_file())
        weather_evidence.load_weather_evidence(quality["weather_replacement"])

    def test_tampered_evidence_blocks_preview_paging_and_confirmation(self):
        parent = self._create_review().json()
        response, _ = self._preview(parent)
        child = response.json()
        record = review_store._load_calibration_review(child["review_id"])
        Path(record["weather_replacement"]["evidence_path"]).write_text("{}")
        for method, suffix, kwargs in [("get", "weather-preview", {}), ("post", "run", {"json": {"decisions": self._recommended_decisions(child["report"])}})]:
            result = getattr(self.client, method)(f"/api/calibration-reviews/{child['review_id']}/{suffix}", **kwargs)
            self.assertEqual(result.status_code, 409, result.text)

    def test_period_boundaries_and_preview_chaining_are_rejected(self):
        parent = self._create_review().json()
        for request in [
            {"fields": ["dni"], "mode": "flagged"},
            {"fields": ["temp_air", "temp_air"], "mode": "flagged"},
            {"fields": ["temp_air"], "mode": "period"},
            {"fields": ["temp_air"], "mode": "period", "from_date": "2026-06-01", "from_time": "08:00", "to_date": "2026-06-01", "to_time": "10:00"},
        ]:
            result, _ = self._preview(parent, request)
            self.assertEqual(result.status_code, 422, result.text)
        response, _ = self._preview(parent)
        chained, _ = self._preview(response.json())
        self.assertEqual(chained.status_code, 422)

    def test_consuming_parent_during_fetch_rejects_child_publication(self):
        parent = self._create_review().json()
        def download(*args, **kwargs):
            response = self.client.post(f"/api/calibration-reviews/{parent['review_id']}/run", json={"decisions": self._recommended_decisions(parent["report"])})
            self.assertEqual(response.status_code, 200, response.text)
            return self._midc_csv()
        with patch.object(midc, "download_api_csv", side_effect=download):
            response = self.client.post(f"/api/calibration-reviews/{parent['review_id']}/weather-preview", json={"fields": ["temp_air"]})
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(list(self.review_dir.glob("*.weather.json")), [])

    def test_preview_is_independent_after_parent_consumed_and_exclusions_are_audited(self):
        parent = self._create_review().json()
        response, _ = self._preview(parent, {"fields": ["wind_speed"], "mode": "period", "from_date": "2026-06-01", "from_time": "09:00", "to_date": "2026-06-01", "to_time": "11:00"})
        child = response.json()
        first = self.client.post(f"/api/calibration-reviews/{parent['review_id']}/run", json={"decisions": self._recommended_decisions(parent["report"])})
        self.assertEqual(first.status_code, 200, first.text)
        second = self.client.post(f"/api/calibration-reviews/{child['review_id']}/run", json={"decisions": self._recommended_decisions(child["report"])})
        self.assertEqual(second.status_code, 200, second.text)
        audit = second.json()["data_quality"]["weather_replacement"]
        self.assertEqual(audit["replaced_cells"], 2)
        self.assertEqual(audit["used_replaced_cells"], 1)
        self.assertEqual(audit["excluded_replaced_cells"], 1)

    def test_retry_recovers_same_job_and_weather_after_receipt_write_failure(self):
        parent = self._create_review().json()
        response, _ = self._preview(parent)
        child = response.json()
        endpoint = f"/api/calibration-reviews/{child['review_id']}/run"
        decisions = self._recommended_decisions(child["report"])
        with patch.object(review_store, "_save_calibration_review", side_effect=OSError("simulated receipt failure")):
            first = self.client.post(endpoint, json={"decisions": decisions})
        self.assertEqual(first.status_code, 500, first.text)
        job = self.store.get_job(f"review-{child['review_id']}")
        self.assertIsNotNone(job)
        with patch.object(midc, "download_api_csv", side_effect=AssertionError("retry must not refetch")):
            recovered = self.client.post(endpoint, json={"decisions": decisions})
        self.assertEqual(recovered.status_code, 200, recovered.text)
        self.assertEqual(recovered.json()["job_id"], job["id"])
        self.assertEqual(recovered.json()["data_quality"]["weather_replacement"]["evidence_sha256"], job["provenance"]["data_quality"]["weather_replacement"]["evidence_sha256"])
        self.assertEqual(len(self.store.list_jobs(limit=10)), 1)

    def test_worker_rejects_modified_weather_evidence_before_model_execution(self):
        from sbepv.worker import completion, run_validation
        from sbepv.api.schemas import RunRequest
        parent = self._create_review().json()
        response, _ = self._preview(parent)
        child = response.json()
        self.client.post(f"/api/calibration-reviews/{child['review_id']}/run", json={"decisions": self._recommended_decisions(child["report"])})
        record = review_store._load_calibration_review(child["review_id"])
        Path(record["weather_replacement"]["evidence_path"]).write_text("{}")
        with patch.object(completion, "_handle_model_failure") as failure:
            run_validation._run_job(record["job_id"], RunRequest(**record["request"]), source_path=record["cleaned_source_path"], expected_source_hash=record["cleaned_source_hash"], data_quality_context=record["quality_context"])
        self.assertIsInstance(failure.call_args.args[1], ValueError)
        self.model_run.assert_not_called()

    def test_export_carries_substitution_ledger_and_source_hashes(self):
        parent = self._create_review().json()
        response, _ = self._preview(parent)
        child = response.json()
        run = self.client.post(f"/api/calibration-reviews/{child['review_id']}/run", json={"decisions": self._recommended_decisions(child["report"])})
        self.assertEqual(run.status_code, 200, run.text)
        quality = review_store._load_calibration_review(child["review_id"])["quality_context"]
        timestamps = pd.to_datetime(["2026-06-01T18:00:00Z"])
        frame = pd.DataFrame({"timestamp_utc": timestamps, "temp_air_c": [23.]}, index=timestamps.tz_convert("America/Denver"))
        output = self.root / "weather-audit.xlsx"
        model.write_excel(frame, str(output), {}, data_quality_context=quality)
        ledger = pd.read_excel(output, sheet_name="weather_replacements")
        self.assertEqual(ledger.loc[0, "original_value"], 100)
        self.assertEqual(ledger.loc[0, "replacement_value"], 23)
        self.assertTrue(ledger.loc[0, "used_in_run"])
        source = pd.read_excel(output, sheet_name="weather_source")
        self.assertIn("evidence_sha256", source["parameter"].tolist())


if __name__ == "__main__":
    unittest.main()
