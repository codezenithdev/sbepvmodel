from __future__ import annotations

import json
import shutil
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

import pandas as pd
from fastapi.testclient import TestClient

from sbepv.api import config, review_store, state
from sbepv.worker import loop as worker_loop
from sbepv import reporting
from sbepv.api import main as app
from sbepv.store import AgentStore
from sbepv.reporting import sha256_file


class CalibrationReviewApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = (
            Path(__file__).resolve().parent
            / f"_calibration_api_tmp_{uuid.uuid4().hex}"
        )
        self.review_dir = self.root / "reviews"
        self.review_dir.mkdir(parents=True)
        self.addCleanup(self._remove_temporary_root)

        self.store = AgentStore(self.root / "agent.sqlite3")
        self._start_patch(patch.object(state, "AGENT_STORE", self.store))
        self._start_patch(
            patch.object(config, "CALIBRATION_REVIEW_DIR", self.review_dir)
        )

        self.worker_wake = Mock()
        self._start_patch(patch.object(state, "_WORKER_WAKE", self.worker_wake))
        self.start_worker = self._start_patch(
            patch.object(worker_loop, "_start_model_worker")
        )
        self.stop_worker = self._start_patch(
            patch.object(worker_loop, "_stop_model_worker")
        )
        self.model_run = self._start_patch(
            patch.object(
                app.model,
                "run_model",
                side_effect=AssertionError(
                    "API review tests must not execute the PV model"
                ),
            )
        )
        self.historian_run = self._start_patch(
            patch.object(
                app.historian,
                "run_historian",
                side_effect=self._write_synthetic_historian_csv,
            )
        )

        self.saved_jobs = dict(state.JOBS)
        state.JOBS.clear()
        self.addCleanup(self._restore_jobs)

        self.client = TestClient(app.app)
        self.addCleanup(self.client.close)

    def _start_patch(self, patcher):
        mocked = patcher.start()
        self.addCleanup(patcher.stop)
        return mocked

    def _remove_temporary_root(self) -> None:
        shutil.rmtree(self.root, ignore_errors=False)

    def _restore_jobs(self) -> None:
        state.JOBS.clear()
        state.JOBS.update(self.saved_jobs)

    def _write_synthetic_historian_csv(self, **kwargs) -> int:
        destination = Path(kwargs["output_csv"])
        self.assertEqual(destination.parent.resolve(), self.review_dir.resolve())
        frame = pd.DataFrame(
            {
                "timestamp": [
                    "2026-06-01 15:00:00",
                    "2026-06-01 16:00:00",
                    "2026-06-01 17:00:00",
                    "2026-06-01 18:00:00",
                    "2026-06-01 19:00:00",
                    "2026-06-01 20:00:00",
                ],
                "solaredge_measured_power": [
                    80_000.0,
                    500.0,
                    90_000.0,
                    95_000.0,
                    100_000.0,
                    105_000.0,
                ],
                "solectria_measured_power": [
                    75_000.0,
                    80_000.0,
                    85_000.0,
                    90_000.0,
                    95_000.0,
                    100_000.0,
                ],
                "dni": [500.0, 600.0, 700.0, 750.0, 650.0, 550.0],
                "ghi": [400.0, 500.0, 600.0, 650.0, 550.0, 450.0],
                "dhi": [100.0, None, 110.0, 115.0, 105.0, 95.0],
                "temp_air": [20.0, 21.0, 22.0, 100.0, 24.0, 25.0],
                "wind_speed": [2.0, 2.5, 3.0, 3.5, 4.0, 4.5],
            }
        )
        frame.to_csv(destination, index=False)
        return len(frame)

    @staticmethod
    def _review_request() -> dict:
        return {
            "from_date": "2026-06-01",
            "from_time": "09:00",
            "to_date": "2026-06-01",
            "to_time": "15:00",
            "interval_value": 1,
            "interval_unit": "hours",
        }

    @staticmethod
    def _recommended_decisions(report: dict) -> dict[str, str]:
        return {
            issue["id"]: issue["recommended_action"]
            for issue in report["issues"]
            if set(issue["allowed_actions"]) == {"retain", "exclude"}
        }

    def _create_review(self):
        return self.client.post(
            "/api/calibration-reviews",
            json=self._review_request(),
        )

    def test_create_review_returns_actionable_report_without_running_model(
        self,
    ) -> None:
        response = self._create_review()

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["state"], "decision_required")
        self.assertEqual(len(payload["review_id"]), 32)
        self.assertEqual(payload["report"]["summary"]["status"], "action_required")
        self.assertGreater(
            payload["report"]["summary"]["actionable_issue_count"],
            0,
        )
        issue_ids = {
            issue["id"] for issue in payload["report"]["issues"]
        }
        self.assertIn("missing.dhi", issue_ids)
        self.assertIn("range.temp_air", issue_ids)
        self.assertIn(
            (
                "pattern.low_power_high_irradiance."
                "solaredge_measured_power"
            ),
            issue_ids,
        )
        self.historian_run.assert_called_once_with(
            from_time="2026-06-01T15:00:00",
            to_time="2026-06-01T21:00:00",
            interval="3600",
            output_csv=str(
                self.review_dir / f"{payload['review_id']}.raw.csv"
            ),
        )
        self.assertEqual(self.store.list_jobs(limit=10), [])
        self.model_run.assert_not_called()
        self.worker_wake.set.assert_not_called()

    def test_review_exposes_hash_verified_affected_rows_on_demand(self) -> None:
        with (
            patch.object(
                app,
                "quality_issue_rows",
                wraps=app.quality_issue_rows,
            ) as rows_loader,
            patch.object(
                reporting,
                "verify_source_sha256",
                wraps=reporting.verify_source_sha256,
            ) as source_verifier,
        ):
            response = self._create_review()
            self.assertEqual(response.status_code, 200, response.text)
            review = response.json()
            missing_dhi = next(
                issue
                for issue in review["report"]["issues"]
                if issue["id"] == "missing.dhi"
            )
            self.assertTrue(missing_dhi["affected_rows_available"])
            self.assertNotIn("_row_positions", missing_dhi)
            self.assertNotIn("rows", missing_dhi)
            rows_loader.assert_not_called()
            source_verifier.assert_not_called()

            rows_response = self.client.get(
                f"/api/calibration-reviews/{review['review_id']}/rows",
                params={"issue_id": "missing.dhi", "offset": 0, "limit": 1},
            )
            rows_loader.assert_called_once()
            self.assertGreaterEqual(source_verifier.call_count, 1)

        self.assertEqual(rows_response.status_code, 200, rows_response.text)
        page = rows_response.json()
        self.assertEqual(page["issue_id"], "missing.dhi")
        self.assertEqual(page["total_rows"], 1)
        self.assertIsNone(page["next_offset"])
        self.assertEqual(page["rows"][0]["source_row"], 3)
        self.assertIsNone(page["rows"][0]["dhi"])
        self.assertEqual(page["rows"][0]["timestamp"], "2026-06-01 16:00:00")

    def test_affected_row_endpoint_rejects_a_tampered_review_snapshot(self) -> None:
        response = self._create_review()
        self.assertEqual(response.status_code, 200, response.text)
        review_id = response.json()["review_id"]
        (self.review_dir / f"{review_id}.raw.csv").write_text(
            "tampered source",
            encoding="utf-8",
        )

        rows_response = self.client.get(
            f"/api/calibration-reviews/{review_id}/rows",
            params={"issue_id": "missing.dhi"},
        )

        self.assertEqual(rows_response.status_code, 409, rows_response.text)
        self.assertIn("source changed", rows_response.json()["detail"])

    def test_affected_row_endpoint_loads_all_rows_only_when_requested(self) -> None:
        response = self._create_review()
        self.assertEqual(response.status_code, 200, response.text)
        review_id = response.json()["review_id"]
        record_path = self.review_dir / f"{review_id}.json"
        record = json.loads(record_path.read_text(encoding="utf-8"))
        source_path = Path(record["source_path"])
        source_rows = pd.read_csv(source_path)
        expanded_rows = pd.concat(
            [source_rows.iloc[[1]]] * 205,
            ignore_index=True,
        )
        expanded_rows.to_csv(source_path, index=False)
        record["source_hash"] = sha256_file(source_path)
        missing_dhi = next(
            issue
            for issue in record["report"]["issues"]
            if issue["id"] == "missing.dhi"
        )
        missing_dhi["_row_positions"] = list(range(len(expanded_rows)))
        missing_dhi["row_count"] = len(expanded_rows)
        record_path.write_text(
            json.dumps(record, allow_nan=False),
            encoding="utf-8",
        )

        paged_response = self.client.get(
            f"/api/calibration-reviews/{review_id}/rows",
            params={"issue_id": "missing.dhi", "limit": 200},
        )
        self.assertEqual(paged_response.status_code, 200, paged_response.text)
        self.assertEqual(len(paged_response.json()["rows"]), 200)
        self.assertEqual(paged_response.json()["next_offset"], 200)

        with patch.object(
            app,
            "quality_issue_rows",
            wraps=app.quality_issue_rows,
        ) as rows_loader:
            rows_response = self.client.get(
                f"/api/calibration-reviews/{review_id}/rows",
                params={"issue_id": "missing.dhi", "all_rows": True},
            )

        self.assertEqual(rows_response.status_code, 200, rows_response.text)
        self.assertIsNone(rows_loader.call_args.kwargs["limit"])
        self.assertEqual(len(rows_response.json()["rows"]), 205)
        self.assertIsNone(rows_response.json()["next_offset"])

    def test_uncalibrated_direct_run_is_available_without_legacy_flag(self) -> None:
        with patch.object(
            app,
            "_legacy_unreviewed_run_enabled",
            side_effect=AssertionError(
                "Uncalibrated runs must not consult the legacy calibration bypass."
            ),
        ):
            response = self.client.post(
                "/api/run",
                json={
                    "from_date": "2026-06-01",
                    "to_date": "2026-06-02",
                    "calibrate_model": False,
                },
            )

        self.assertEqual(response.status_code, 200, response.text)
        job = self.store.get_job(response.json()["job_id"])
        self.assertIsNotNone(job)
        assert job is not None
        self.assertFalse(job["request"]["calibrate_model"])
        self.assertEqual(job["state"], "queued")
        self.historian_run.assert_not_called()
        self.worker_wake.set.assert_called_once_with()

    def test_review_endpoint_rejects_uncalibrated_request(self) -> None:
        response = self.client.post(
            "/api/calibration-reviews",
            json={**self._review_request(), "calibrate_model": False},
        )

        self.assertEqual(response.status_code, 422, response.text)
        self.assertIn("only required when", response.json()["detail"])
        self.assertEqual(self.store.list_jobs(limit=10), [])
        self.historian_run.assert_not_called()
        self.worker_wake.set.assert_not_called()

    def test_run_review_is_hash_bound_and_decision_idempotent(self) -> None:
        review_response = self._create_review()
        self.assertEqual(review_response.status_code, 200, review_response.text)
        review = review_response.json()
        review_id = review["review_id"]
        decisions = self._recommended_decisions(review["report"])
        self.assertTrue(decisions)

        first_response = self.client.post(
            f"/api/calibration-reviews/{review_id}/run",
            json={"decisions": decisions},
        )

        self.assertEqual(first_response.status_code, 200, first_response.text)
        first = first_response.json()
        self.assertEqual(first["state"], "queued")
        self.assertEqual(first["review_id"], review_id)
        job = self.store.get_job(first["job_id"])
        self.assertIsNotNone(job)
        assert job is not None
        self.assertEqual(job["state"], "queued")
        self.assertEqual(job["mode"], "validation")
        reviewed_path = Path(job["source_path"])
        self.assertEqual(reviewed_path.parent.resolve(), self.review_dir.resolve())
        self.assertTrue(reviewed_path.name.startswith(f"{review_id}."))
        self.assertTrue(reviewed_path.name.endswith(".reviewed.csv"))
        self.assertTrue(reviewed_path.is_file())
        self.assertEqual(job["source_hash"], sha256_file(reviewed_path))
        self.assertEqual(
            job["source_hash"],
            first["data_quality"]["reviewed_source_sha256"],
        )
        self.assertEqual(
            job["provenance"]["data_quality"]["review_id"],
            review_id,
        )
        self.assertEqual(
            job["provenance"]["data_quality"]["reviewed_source_sha256"],
            job["source_hash"],
        )
        self.assertEqual(len(self.store.list_jobs(limit=10)), 1)

        identical_response = self.client.post(
            f"/api/calibration-reviews/{review_id}/run",
            json={"decisions": dict(reversed(list(decisions.items())))},
        )

        self.assertEqual(
            identical_response.status_code,
            200,
            identical_response.text,
        )
        identical = identical_response.json()
        self.assertEqual(identical["job_id"], first["job_id"])
        self.assertEqual(identical["state"], "queued")
        self.assertEqual(identical["data_quality"], first["data_quality"])
        self.assertEqual(len(self.store.list_jobs(limit=10)), 1)

        self.store.update_job(first["job_id"], state="running")
        running_response = self.client.post(
            f"/api/calibration-reviews/{review_id}/run",
            json={"decisions": decisions},
        )
        self.assertEqual(running_response.status_code, 200, running_response.text)
        self.assertEqual(running_response.json()["state"], "running")

        different_decisions = dict(decisions)
        changed_issue = next(iter(different_decisions))
        different_decisions[changed_issue] = (
            "retain"
            if different_decisions[changed_issue] == "exclude"
            else "exclude"
        )
        conflicting_response = self.client.post(
            f"/api/calibration-reviews/{review_id}/run",
            json={"decisions": different_decisions},
        )

        self.assertEqual(conflicting_response.status_code, 409)
        self.assertIn(
            "already started with different decisions",
            conflicting_response.json()["detail"],
        )
        self.assertEqual(len(self.store.list_jobs(limit=10)), 1)
        self.historian_run.assert_called_once()
        self.model_run.assert_not_called()
        self.worker_wake.set.assert_called_once_with()

    def test_retry_recovers_job_after_review_receipt_write_failure(self) -> None:
        review_response = self._create_review()
        self.assertEqual(review_response.status_code, 200, review_response.text)
        review = review_response.json()
        decisions = self._recommended_decisions(review["report"])

        with patch.object(
            review_store,
            "_save_calibration_review",
            side_effect=OSError("simulated receipt write failure"),
        ):
            failed = self.client.post(
                f"/api/calibration-reviews/{review['review_id']}/run",
                json={"decisions": decisions},
            )

        self.assertEqual(failed.status_code, 500, failed.text)
        first_jobs = self.store.list_jobs(limit=10)
        self.assertEqual(len(first_jobs), 1)
        expected_job_id = f"review-{review['review_id']}"
        self.assertEqual(first_jobs[0]["id"], expected_job_id)

        recovered = self.client.post(
            f"/api/calibration-reviews/{review['review_id']}/run",
            json={"decisions": decisions},
        )

        self.assertEqual(recovered.status_code, 200, recovered.text)
        self.assertEqual(recovered.json()["job_id"], expected_job_id)
        self.assertEqual(len(self.store.list_jobs(limit=10)), 1)
        self.worker_wake.set.assert_called_once_with()

    def test_cleanup_preserves_source_after_review_receipt_write_failure(
        self,
    ) -> None:
        review_response = self._create_review()
        review = review_response.json()
        decisions = self._recommended_decisions(review["report"])

        with patch.object(
            review_store,
            "_save_calibration_review",
            side_effect=OSError("simulated receipt write failure"),
        ):
            failed = self.client.post(
                f"/api/calibration-reviews/{review['review_id']}/run",
                json={"decisions": decisions},
            )

        self.assertEqual(failed.status_code, 500, failed.text)
        job = self.store.get_job(f"review-{review['review_id']}")
        assert job is not None
        reviewed_source = Path(job["source_path"])
        record_path = self.review_dir / f"{review['review_id']}.json"
        record = json.loads(record_path.read_text(encoding="utf-8"))
        record["expires_at"] = (
            datetime.now(timezone.utc) - timedelta(minutes=1)
        ).isoformat()
        record_path.write_text(json.dumps(record), encoding="utf-8")

        app._cleanup_expired_calibration_reviews()

        self.assertTrue(reviewed_source.is_file())
        self.assertFalse(record_path.exists())

    def test_review_state_is_derived_from_report_summary(self) -> None:
        self.assertEqual(
            app._calibration_review_state({"summary": {"status": "clean"}}),
            "ready",
        )
        self.assertEqual(
            app._calibration_review_state(
                {"summary": {"status": "action_required"}}
            ),
            "decision_required",
        )
        self.assertEqual(
            app._calibration_review_state({"summary": {"status": "blocked"}}),
            "blocked",
        )

    def test_review_rejects_excessive_range_before_fetch(self) -> None:
        request = self._review_request()
        request["to_date"] = "2027-06-03"

        response = self.client.post("/api/calibration-reviews", json=request)

        self.assertEqual(response.status_code, 422, response.text)
        self.assertIn("limited to", response.json()["detail"])
        self.historian_run.assert_not_called()

    def test_review_rejects_nonexistent_or_ambiguous_dst_boundary(
        self,
    ) -> None:
        cases = (
            ("2026-03-08", "02:30", "does not exist"),
            ("2026-11-01", "01:30", "occurs twice"),
        )
        for selected_date, selected_time, expected_detail in cases:
            with self.subTest(
                selected_date=selected_date,
                selected_time=selected_time,
            ):
                response = self.client.post(
                    "/api/calibration-reviews",
                    json={
                        **self._review_request(),
                        "from_date": selected_date,
                        "from_time": selected_time,
                        "to_date": selected_date,
                        "to_time": "03:30",
                    },
                )

                self.assertEqual(response.status_code, 422, response.text)
                self.assertIn(expected_detail, response.json()["detail"])
        self.historian_run.assert_not_called()

    def test_legacy_unreviewed_run_is_disabled_by_default(self) -> None:
        response = self.client.post(
            "/api/run",
            json={
                "from_date": "2026-06-01",
                "to_date": "2026-06-02",
            },
        )

        self.assertEqual(response.status_code, 410, response.text)
        self.assertIn("calibration-reviews", response.json()["detail"])
        self.assertEqual(self.store.list_jobs(limit=10), [])
        self.historian_run.assert_not_called()
        self.worker_wake.set.assert_not_called()

    def test_review_rejects_expected_and_returned_row_overflow(self) -> None:
        with patch.object(config, "CALIBRATION_REVIEW_MAX_ROWS", 5):
            expected_response = self._create_review()
        self.assertEqual(expected_response.status_code, 422, expected_response.text)
        self.historian_run.assert_not_called()

        def overreported_rows(**kwargs) -> int:
            self._write_synthetic_historian_csv(**kwargs)
            return 7

        self.historian_run.side_effect = overreported_rows
        with patch.object(config, "CALIBRATION_REVIEW_MAX_ROWS", 6):
            returned_response = self._create_review()
        self.assertEqual(returned_response.status_code, 422, returned_response.text)
        self.assertFalse(list(self.review_dir.iterdir()))

    def test_unknown_decision_id_is_rejected(self) -> None:
        review_response = self._create_review()
        self.assertEqual(review_response.status_code, 200, review_response.text)
        review = review_response.json()
        decisions = self._recommended_decisions(review["report"])
        decisions["typo.issue"] = "exclude"

        response = self.client.post(
            f"/api/calibration-reviews/{review['review_id']}/run",
            json={"decisions": decisions},
        )

        self.assertEqual(response.status_code, 422, response.text)
        self.assertIn("Unknown data-quality decision", response.json()["detail"])
        self.assertEqual(self.store.list_jobs(limit=10), [])

    def test_malformed_review_hash_returns_conflict(self) -> None:
        review_response = self._create_review()
        self.assertEqual(review_response.status_code, 200, review_response.text)
        review = review_response.json()
        record_path = self.review_dir / f"{review['review_id']}.json"
        record = json.loads(record_path.read_text(encoding="utf-8"))
        record["source_hash"] = "not-a-sha256"
        record_path.write_text(json.dumps(record), encoding="utf-8")

        response = self.client.post(
            f"/api/calibration-reviews/{review['review_id']}/run",
            json={"decisions": self._recommended_decisions(review["report"])},
        )

        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn("source changed", response.json()["detail"])
        self.assertEqual(self.store.list_jobs(limit=10), [])

    def test_expired_review_cleanup_removes_only_private_review_artifacts(
        self,
    ) -> None:
        review_id = uuid.uuid4().hex
        expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        artifacts = [
            self.review_dir / f"{review_id}.json",
            self.review_dir / f"{review_id}.raw.csv",
            self.review_dir / f"{review_id}.reviewed.csv",
        ]
        artifacts[0].write_text(
            json.dumps({"review_id": review_id, "expires_at": expires_at.isoformat()}),
            encoding="utf-8",
        )
        artifacts[1].write_text("raw", encoding="utf-8")
        artifacts[2].write_text("reviewed", encoding="utf-8")
        unrelated = self.review_dir / "unrelated.txt"
        unrelated.write_text("keep", encoding="utf-8")

        removed = app._cleanup_expired_calibration_reviews()

        self.assertEqual(removed, 3)
        self.assertTrue(unrelated.is_file())
        self.assertTrue(all(not artifact.exists() for artifact in artifacts))

    def test_cleanup_preserves_reviewed_source_bound_to_job(self) -> None:
        review_response = self._create_review()
        review = review_response.json()
        decisions = self._recommended_decisions(review["report"])
        run_response = self.client.post(
            f"/api/calibration-reviews/{review['review_id']}/run",
            json={"decisions": decisions},
        )
        self.assertEqual(run_response.status_code, 200, run_response.text)
        job = self.store.get_job(run_response.json()["job_id"])
        assert job is not None
        reviewed_source = Path(job["source_path"])
        record_path = self.review_dir / f"{review['review_id']}.json"
        record = json.loads(record_path.read_text(encoding="utf-8"))
        record["expires_at"] = (
            datetime.now(timezone.utc) - timedelta(minutes=1)
        ).isoformat()
        record_path.write_text(json.dumps(record), encoding="utf-8")

        app._cleanup_expired_calibration_reviews()

        self.assertTrue(reviewed_source.is_file())
        self.assertFalse(record_path.exists())
        self.assertFalse(
            (self.review_dir / f"{review['review_id']}.raw.csv").exists()
        )

    def test_cleanup_removes_unbound_reviewed_source_orphan(self) -> None:
        review_id = uuid.uuid4().hex
        orphan = self.review_dir / f"{review_id}.deadbeef.reviewed.csv"
        orphan.write_text("orphan", encoding="utf-8")

        removed = app._cleanup_expired_calibration_reviews(
            now=(
                datetime.now(timezone.utc)
                + app.CALIBRATION_REVIEW_TTL
                + timedelta(minutes=1)
            )
        )

        self.assertEqual(removed, 1)
        self.assertFalse(orphan.exists())

    def test_private_review_snapshot_has_no_public_source_url(self) -> None:
        with patch.object(config, "OUTPUT_DIR", self.root):
            public_source = self.root / "source.csv"
            private_source = self.root / ".calibration_reviews" / "source.csv"
            self.assertEqual(
                app._public_source_url(public_source),
                "/outputs/source.csv",
            )
            self.assertIsNone(app._public_source_url(private_source))


if __name__ == "__main__":
    unittest.main()
