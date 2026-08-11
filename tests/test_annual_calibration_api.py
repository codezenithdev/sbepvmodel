from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from fastapi.testclient import TestClient

from sbepv import model
from sbepv.api import config, state
from sbepv.worker import run_annual
from sbepv.api import baselines
from sbepv.api import main as app
from sbepv.ingest import midc
from sbepv.store import AgentStore
from sbepv.calibration import CALIBRATION_PROFILE_SCHEMA_VERSION
from sbepv.reporting import sha256_file


class AnnualCalibrationApiTests(unittest.TestCase):
    def setUp(self) -> None:
        handle = tempfile.NamedTemporaryFile(
            prefix="annual-calibration-api-",
            suffix=".sqlite3",
            dir=Path(__file__).resolve().parent,
            delete=False,
        )
        handle.close()
        self.database = Path(handle.name)
        self.generated_files: list[Path] = []
        self.original_store = state.AGENT_STORE
        state.AGENT_STORE = AgentStore(self.database)
        state.JOBS.clear()
        self.client = TestClient(app.app)
        self.addCleanup(setattr, state, "AGENT_STORE", self.original_store)
        self.addCleanup(state.JOBS.clear)
        self.addCleanup(self._cleanup)

    def _cleanup(self) -> None:
        for path in self.generated_files:
            path.unlink(missing_ok=True)
        for path in (
            self.database,
            Path(f"{self.database}-wal"),
            Path(f"{self.database}-shm"),
        ):
            path.unlink(missing_ok=True)

    @staticmethod
    def _settings(**overrides):
        values = {
            "backtrack": False,
            "solaredge_inverter_efficiency": 0.961,
            "solaredge_bos_efficiency": 0.972,
            "solectria_inverter_efficiency": 0.953,
            "solectria_bos_efficiency": 0.964,
            "iam_model": "martin_ruiz",
            "iam_a_r": 0.17,
            "curtailment_enabled": True,
            "curtailment_limit_kw": 121.5,
        }
        values.update(overrides)
        return values

    def _completed_reviewed_baseline(
        self,
        *,
        job_id: str = "reviewed-calibration",
        seasons: tuple[str, ...] = ("winter", "spring", "summer"),
        from_date: str = "2025-01-01",
        to_date: str = "2025-09-01",
        settings: dict | None = None,
        include_physics_identity: bool = True,
    ) -> dict:
        source_handle = tempfile.NamedTemporaryFile(
            prefix=f"{job_id}-",
            suffix=".csv",
            dir=Path(__file__).resolve().parent,
            delete=False,
        )
        source_handle.close()
        source_path = Path(source_handle.name)
        self.generated_files.append(source_path)
        source_path.write_text(
            "timestamp,solaredge_measured_power,solectria_measured_power,dni,ghi,dhi,temp_air,wind_speed\n"
            "2025-01-01 08:00:00,1000,900,700,500,100,20,2\n",
            encoding="utf-8",
        )
        source_hash = sha256_file(source_path)
        review_id = f"review-{job_id}"
        factors = {
            season: {
                "solaredge": round(1.01 + index * 0.01, 4),
                "solectria": round(0.97 + index * 0.01, 4),
            }
            for index, season in enumerate(seasons)
        }
        profile = {
            "schema_version": CALIBRATION_PROFILE_SCHEMA_VERSION,
            "origin_job_id": job_id,
            "origin_source_sha256": source_hash,
            "origin_review_id": review_id,
            "seasonal_factors": factors,
            "fit_metadata": {"method": "unit-test-reviewed-fit"},
            "factor_driver_diagnostics": {"systems": {}},
        }
        if include_physics_identity:
            profile.update(
                {
                    "calibration_physics_version": (
                        model.CALIBRATION_PHYSICS_VERSION
                    ),
                    "calibration_physics_fingerprint": (
                        model.CALIBRATION_PHYSICS_FINGERPRINT
                    ),
                    "solectria_physics_version": (
                        model.SOLECTRIA_PHYSICS_VERSION
                    ),
                    "solectria_physics_fingerprint": (
                        model.SOLECTRIA_PHYSICS_FINGERPRINT
                    ),
                }
            )
        request_model = app.RunRequest(
            from_date=from_date,
            from_time="00:00",
            to_date=to_date,
            to_time="00:00",
            **(settings or self._settings()),
        )
        app._validate_run_request(request_model)
        app._validate_curtailment(request_model)
        request = app._run_request_context(request_model)
        provenance = {
            "data_quality": {
                "review_id": review_id,
                "reviewed_source_sha256": source_hash,
                "reviewed_at": "2026-08-01T12:00:00+00:00",
            },
            "calibration_profile": profile,
        }
        state.AGENT_STORE.create_job(
            job_id=job_id,
            kind="baseline",
            mode="validation",
            request=request,
            provenance=provenance,
        )
        claimed = state.AGENT_STORE.claim_next_queued_job()
        self.assertEqual(claimed["id"], job_id)
        completed = state.AGENT_STORE.update_job(
            job_id,
            state="done",
            progress=100,
            stage="Done",
            source_path=str(source_path.resolve()),
            source_hash=source_hash,
            result={"mode": "validation", "stats": {"calibration_enabled": True}},
            artifacts={},
        )
        state.AGENT_STORE.promote_job(job_id)
        return completed

    @staticmethod
    def _annual_payload(job_id: str, **overrides) -> dict:
        payload = {
            "from_date": "2026-01-01",
            "to_date": "2026-12-31",
            "calibration_baseline_job_id": job_id,
        }
        payload.update(overrides)
        return payload

    def _request_confirmation(self, job_id: str, **overrides):
        response = self.client.post(
            "/api/annual-run",
            json=self._annual_payload(job_id, **overrides),
        )
        self.assertEqual(response.status_code, 409, response.text)
        detail = response.json()["detail"]
        self.assertEqual(
            detail["code"], "seasonal_fallback_confirmation_required"
        )
        return detail

    @staticmethod
    def _acknowledgement(context_sha256: str) -> dict:
        return {
            "accepted": True,
            "source_season": "spring",
            "target_season": "fall",
            "confirmation_context_sha256": context_sha256,
        }

    def test_current_calibration_returns_sanitized_summary_and_exact_settings(self):
        baseline = self._completed_reviewed_baseline()

        response = self.client.get("/api/current-calibration")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["available"])
        self.assertTrue(payload["verified"])
        self.assertEqual(payload["job_id"], baseline["id"])
        self.assertEqual(payload["review_id"], "review-reviewed-calibration")
        self.assertEqual(
            payload["calibration_physics_version"],
            model.CALIBRATION_PHYSICS_VERSION,
        )
        self.assertEqual(
            payload["calibration_physics_fingerprint"],
            model.CALIBRATION_PHYSICS_FINGERPRINT,
        )
        self.assertEqual(
            payload["solectria_physics_version"],
            model.SOLECTRIA_PHYSICS_VERSION,
        )
        self.assertEqual(
            payload["solectria_physics_fingerprint"],
            model.SOLECTRIA_PHYSICS_FINGERPRINT,
        )
        self.assertEqual(payload["settings"], self._settings())
        self.assertEqual(
            payload["factor_coverage"],
            {"winter": True, "spring": True, "summer": True, "fall": False},
        )
        self.assertEqual(payload["seasonal_factors"]["spring"]["solaredge"], 1.02)
        self.assertNotIn("source_path", payload)
        self.assertNotIn("origin_source_sha256", payload)
        self.assertEqual(len(payload["profile_sha256"]), 64)

    def test_current_calibration_is_unavailable_without_reviewed_promotion(self):
        response = self.client.get("/api/current-calibration")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"available": False})

    def test_legacy_promoted_profile_is_unavailable_after_physics_repair(self):
        self._completed_reviewed_baseline(include_physics_identity=False)

        response = self.client.get("/api/current-calibration")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"available": False})

    def test_missing_fall_requires_consent_before_job_and_confirmed_run_is_audited(self):
        baseline = self._completed_reviewed_baseline()
        detail = self._request_confirmation(
            baseline["id"],
            solaredge_bos_efficiency=0.95,
        )

        self.assertEqual(state.AGENT_STORE.list_jobs(mode="annual"), [])
        self.assertEqual(
            detail["mapping"],
            {"target_season": "fall", "source_season": "spring"},
        )
        self.assertEqual(
            detail["spring_factors"],
            {"solaredge": 1.02, "solectria": 0.98},
        )
        self.assertEqual(
            detail["modified_settings"],
            [
                {
                    "field": "solaredge_bos_efficiency",
                    "calibrated_value": 0.972,
                    "annual_value": 0.95,
                }
            ],
        )

        response = self.client.post(
            "/api/annual-run",
            json=self._annual_payload(
                baseline["id"],
                solaredge_bos_efficiency=0.95,
                seasonal_fallback_acknowledgement=self._acknowledgement(
                    detail["confirmation_context_sha256"]
                ),
            ),
        )

        self.assertEqual(response.status_code, 200, response.text)
        job = state.AGENT_STORE.get_job(response.json()["job_id"])
        self.assertIsNotNone(job)
        self.assertNotIn("calibration_baseline_job_id", job["request"])
        self.assertNotIn("seasonal_fallback_acknowledgement", job["request"])
        self.assertEqual(job["request"]["backtrack"], False)
        self.assertEqual(job["request"]["iam_a_r"], 0.17)
        self.assertEqual(job["request"]["solaredge_bos_efficiency"], 0.95)
        application = job["provenance"]["calibration_application"]
        self.assertNotIn("fall", application["origin_profile"]["seasonal_factors"])
        self.assertEqual(
            application["resolved_profile"]["seasonal_factors"]["fall"],
            application["origin_profile"]["seasonal_factors"]["spring"],
        )
        self.assertTrue(application["seasonal_substitution"]["explicitly_accepted"])
        self.assertTrue(application["server_confirmation"]["accepted"])
        self.assertEqual(
            application["server_timestamp"],
            application["server_confirmation"]["recorded_at"],
        )
        self.assertEqual(
            application["server_confirmation"]["confirmation_context_sha256"],
            detail["confirmation_context_sha256"],
        )

    def test_changed_request_rejects_stale_confirmation_without_enqueuing(self):
        baseline = self._completed_reviewed_baseline()
        detail = self._request_confirmation(baseline["id"])

        response = self.client.post(
            "/api/annual-run",
            json=self._annual_payload(
                baseline["id"],
                backtrack=True,
                seasonal_fallback_acknowledgement=self._acknowledgement(
                    detail["confirmation_context_sha256"]
                ),
            ),
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            response.json()["detail"]["code"],
            "seasonal_fallback_confirmation_context_changed",
        )
        self.assertEqual(state.AGENT_STORE.list_jobs(mode="annual"), [])

    def test_changed_promotion_rejects_old_baseline_and_context(self):
        first = self._completed_reviewed_baseline(job_id="first-calibration")
        detail = self._request_confirmation(first["id"])
        second = self._completed_reviewed_baseline(job_id="second-calibration")

        response = self.client.post(
            "/api/annual-run",
            json=self._annual_payload(
                first["id"],
                seasonal_fallback_acknowledgement=self._acknowledgement(
                    detail["confirmation_context_sha256"]
                ),
            ),
        )

        self.assertEqual(response.status_code, 409)
        conflict = response.json()["detail"]
        self.assertEqual(conflict["code"], "calibration_baseline_changed")
        self.assertEqual(conflict["current_baseline_job_id"], second["id"])
        self.assertEqual(state.AGENT_STORE.list_jobs(mode="annual"), [])

    def test_promotion_race_is_rechecked_immediately_before_enqueue(self):
        first = self._completed_reviewed_baseline(
            job_id="race-first",
            seasons=("winter", "spring", "summer", "fall"),
            to_date="2025-12-01",
        )
        first_bundle = baselines._current_calibration_bundle()
        self._completed_reviewed_baseline(
            job_id="race-second",
            seasons=("winter", "spring", "summer", "fall"),
            to_date="2025-12-01",
        )
        second_bundle = baselines._current_calibration_bundle()

        with patch.object(
            baselines,
            "_current_calibration_bundle",
            side_effect=[first_bundle, second_bundle],
        ):
            response = self.client.post(
                "/api/annual-run", json=self._annual_payload(first["id"])
            )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            response.json()["detail"]["code"], "calibration_baseline_changed"
        )
        self.assertEqual(state.AGENT_STORE.list_jobs(mode="annual"), [])

    def test_missing_unsupported_seasons_block_without_fall_prompt(self):
        baseline = self._completed_reviewed_baseline(
            seasons=("summer",),
            from_date="2025-06-01",
            to_date="2025-09-01",
        )

        response = self.client.post(
            "/api/annual-run", json=self._annual_payload(baseline["id"])
        )

        self.assertEqual(response.status_code, 409)
        detail = response.json()["detail"]
        self.assertEqual(detail["code"], "seasonal_calibration_coverage_missing")
        self.assertIn("spring", detail["missing_seasons"])
        self.assertIn("fall", detail["missing_seasons"])
        self.assertEqual(state.AGENT_STORE.list_jobs(mode="annual"), [])

    def test_actual_fall_factor_takes_precedence_and_needs_no_acknowledgement(self):
        baseline = self._completed_reviewed_baseline(
            seasons=("winter", "spring", "summer", "fall"),
            to_date="2025-12-01",
        )

        response = self.client.post(
            "/api/annual-run", json=self._annual_payload(baseline["id"])
        )

        self.assertEqual(response.status_code, 200, response.text)
        job = state.AGENT_STORE.get_job(response.json()["job_id"])
        application = job["provenance"]["calibration_application"]
        self.assertIsNone(application["seasonal_substitution"])
        self.assertIsNone(application["server_confirmation"])
        self.assertIn("T", application["server_timestamp"])
        self.assertEqual(
            application["resolved_profile"]["seasonal_factors"]["fall"],
            {"solaredge": 1.04, "solectria": 1.0},
        )

    def test_legacy_annual_request_remains_physics_only(self):
        response = self.client.post(
            "/api/annual-run",
            json={"from_date": "2026-06-01", "to_date": "2026-06-02"},
        )

        self.assertEqual(response.status_code, 200, response.text)
        job = state.AGENT_STORE.get_job(response.json()["job_id"])
        self.assertIsNone(job["provenance"])
        self.assertEqual(job["request"]["from_date"], "2026-06-01")
        self.assertEqual(job["request"]["interval_value"], 1)
        self.assertEqual(job["request"]["interval_unit"], "hours")

    def test_annual_interval_is_persisted_and_bound_to_fallback_confirmation(self):
        baseline = self._completed_reviewed_baseline()
        six_hour_detail = self._request_confirmation(
            baseline["id"],
            interval_value=6,
            interval_unit="hours",
        )
        three_hour_detail = self._request_confirmation(
            baseline["id"],
            interval_value=3,
            interval_unit="hours",
        )
        self.assertNotEqual(
            six_hour_detail["confirmation_context_sha256"],
            three_hour_detail["confirmation_context_sha256"],
        )

        stale_response = self.client.post(
            "/api/annual-run",
            json=self._annual_payload(
                baseline["id"],
                interval_value=3,
                interval_unit="hours",
                seasonal_fallback_acknowledgement=self._acknowledgement(
                    six_hour_detail["confirmation_context_sha256"]
                ),
            ),
        )
        self.assertEqual(stale_response.status_code, 409, stale_response.text)
        self.assertEqual(
            stale_response.json()["detail"]["code"],
            "seasonal_fallback_confirmation_context_changed",
        )

        response = self.client.post(
            "/api/annual-run",
            json=self._annual_payload(
                baseline["id"],
                interval_value=6,
                interval_unit="hours",
                seasonal_fallback_acknowledgement=self._acknowledgement(
                    six_hour_detail["confirmation_context_sha256"]
                ),
            ),
        )
        self.assertEqual(response.status_code, 200, response.text)
        job = state.AGENT_STORE.get_job(response.json()["job_id"])
        self.assertEqual(job["request"]["interval_value"], 6)
        self.assertEqual(job["request"]["interval_unit"], "hours")

    def test_annual_interval_accepts_equivalent_supported_units(self):
        for interval_value, interval_unit in ((60, "minutes"), (12, "hours"), (1, "days")):
            with self.subTest(interval_value=interval_value, interval_unit=interval_unit):
                response = self.client.post(
                    "/api/annual-run",
                    json={
                        "from_date": "2026-06-01",
                        "to_date": "2026-06-02",
                        "interval_value": interval_value,
                        "interval_unit": interval_unit,
                    },
                )
                self.assertEqual(response.status_code, 200, response.text)
                job = state.AGENT_STORE.get_job(response.json()["job_id"])
                self.assertEqual(job["request"]["interval_value"], interval_value)
                self.assertEqual(job["request"]["interval_unit"], interval_unit)

    def test_annual_interval_rejects_sub_hour_non_divisor_and_over_day_values(self):
        invalid_intervals = (
            (30, "minutes"),
            (5, "hours"),
            (25, "hours"),
            (2, "days"),
        )
        for interval_value, interval_unit in invalid_intervals:
            with self.subTest(interval_value=interval_value, interval_unit=interval_unit):
                response = self.client.post(
                    "/api/annual-run",
                    json={
                        "from_date": "2026-06-01",
                        "to_date": "2026-06-02",
                        "interval_value": interval_value,
                        "interval_unit": interval_unit,
                    },
                )
                self.assertEqual(response.status_code, 422, response.text)

    def test_worker_passes_resolved_profile_and_exposes_sanitized_application(self):
        baseline = self._completed_reviewed_baseline(
            seasons=("winter", "spring", "summer", "fall"),
            to_date="2025-12-01",
        )
        queued = self.client.post(
            "/api/annual-run", json=self._annual_payload(baseline["id"])
        )
        self.assertEqual(queued.status_code, 200, queued.text)
        job_id = queued.json()["job_id"]
        claimed = state.AGENT_STORE.claim_next_queued_job()
        self.assertEqual(claimed["id"], job_id)
        request = app.AnnualRunRequest(**claimed["request"])
        provenance = claimed["provenance"]
        hourly = pd.DataFrame(
            {
                midc.DATE_COLUMN: ["01/01/2026"],
                midc.HOUR_COLUMN: [0],
                **{
                    column: [1.0]
                    for column in midc.MEASUREMENT_COLUMNS.values()
                },
            }
        )
        source = midc.MidcFetchResult(hourly, 1, 1, 0, 1, 1)
        base = config.OUTPUT_DIR / job_id
        source_path = config.OUTPUT_DIR / f"{job_id}_midc_hourly.csv"
        irradiance_path = config.OUTPUT_DIR / f"{job_id}_irradiance.png"
        self.generated_files.extend((source_path, irradiance_path))
        captured: dict = {}

        def fake_run_model(**kwargs):
            captured.update(kwargs)
            return {
                "se_predicted_kwh": 10.0,
                "sol_predicted_kwh": 8.0,
                "n_rows": 1,
                "data_quality_warnings": [],
                "ac_png": str(base) + "_ac_power.png",
                "energy_png": str(base) + "_cumulative_energy.png",
                "monthly_png": str(base) + "_monthly_energy.png",
                "excel": str(base) + ".xlsx",
                "physics_only": {
                    "se_predicted_kwh": 9.0,
                    "sol_predicted_kwh": 7.0,
                },
                "calibration_adjusted": {
                    "se_predicted_kwh": 10.0,
                    "sol_predicted_kwh": 8.0,
                },
                "calibration_application": provenance[
                    "calibration_application"
                ],
            }

        with (
            patch.object(app.midc, "fetch_hourly_data", return_value=source),
            patch.object(app.model, "run_model", side_effect=fake_run_model),
        ):
            run_annual._run_annual_job(
                job_id,
                request,
                calibration_profile=provenance["calibration_profile"],
                calibration_application_context=provenance[
                    "calibration_application"
                ],
            )

        self.assertEqual(
            captured["calibration_profile"], provenance["calibration_profile"]
        )
        self.assertEqual(
            captured["calibration_application_context"],
            provenance["calibration_application"],
        )
        completed = state.AGENT_STORE.get_job(job_id)
        result = completed["result"]
        self.assertTrue(result["calibration_application"]["applied"])
        self.assertEqual(
            result["calibration_application"]["baseline_job_id"], baseline["id"]
        )
        self.assertNotIn("origin_profile", result["calibration_application"])
        self.assertNotIn("resolved_profile", result["calibration_application"])
        self.assertNotIn(
            "origin_profile", result["stats"]["calibration_application"]
        )

    def test_fallback_mapping_is_structurally_restricted(self):
        baseline = self._completed_reviewed_baseline()
        detail = self._request_confirmation(baseline["id"])
        acknowledgement = self._acknowledgement(
            detail["confirmation_context_sha256"]
        )
        acknowledgement["source_season"] = "summer"

        response = self.client.post(
            "/api/annual-run",
            json=self._annual_payload(
                baseline["id"],
                seasonal_fallback_acknowledgement=acknowledgement,
            ),
        )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(state.AGENT_STORE.list_jobs(mode="annual"), [])


if __name__ == "__main__":
    unittest.main()
