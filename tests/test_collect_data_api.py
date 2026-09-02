from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from sbepv.api import collect_data, config, state
from sbepv.api import main as app
from sbepv.api.schemas import DataCollectionRequest
from sbepv.ingest import bazefield


class CollectDataApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = Path(tempfile.mkdtemp(prefix="sbepv-collect-data-"))
        self.addCleanup(shutil.rmtree, self.temporary, True)
        self.output_patch = patch.object(config, "OUTPUT_DIR", self.temporary)
        self.output_patch.start()
        self.addCleanup(self.output_patch.stop)
        self.auth_patch = patch.dict(
            os.environ,
            {"DASHBOARD_BASIC_USER": "", "DASHBOARD_BASIC_PASSWORD": ""},
        )
        self.auth_patch.start()
        self.addCleanup(self.auth_patch.stop)
        self.jobs_before = dict(state.JOBS)
        self.client = TestClient(app.app)
        self.addCleanup(self.client.close)

    @staticmethod
    def _fake_collection(**kwargs):
        destination = Path(kwargs["output_csv"])
        destination.write_text(
            "timestamp,solaredge_measured_power\n2026-06-01 06:00:00,10000.0\n",
            encoding="utf-8",
        )
        return {
            "row_count": 1,
            "column_count": 2,
            "data_groups": [{"id": "solaredge", "label": "SolarEdge power"}],
            "series": [{
                "name": "solaredge_measured_power",
                "label": "SolarEdge measured power",
                "unit": "W",
                "group": "solaredge",
            }],
            "quality": {
                "status": "clean",
                "issue_count": 0,
                "summary": {
                    "expected_timestamp_count": 1,
                    "observed_timestamp_count": 1,
                    "missing_timestamp_count": 0,
                    "timestamp_coverage_percent": 100.0,
                    "sample_presence_percent": 100.0,
                    "usable_value_completeness_percent": 100.0,
                },
                "issues": [],
            },
        }

    def _request(self, **overrides):
        payload = {
            "from_date": "2026-06-01",
            "from_time": "00:00",
            "to_date": "2026-06-01",
            "to_time": "01:00",
            "interval_value": 1,
            "interval_unit": "hours",
            "data_groups": ["weather", "solaredge"],
        }
        payload.update(overrides)
        return payload

    def _store_record(
        self,
        collection_id: str,
        *,
        state_name: str,
        request_overrides: dict | None = None,
        updated_at: str | None = None,
    ) -> dict:
        request_model = DataCollectionRequest(
            **self._request(**(request_overrides or {}))
        )
        request, internal = collect_data._validated_request(request_model)
        timestamp = updated_at or collect_data._utc_now()
        record = {
            "collection_id": collection_id,
            "state": state_name,
            "progress": 15 if state_name in {"queued", "collecting"} else 100,
            "stage": "Fixture collection",
            "created_at": timestamp,
            "updated_at": timestamp,
            "request": request,
            "request_sha256": collect_data._request_sha256(request),
            "internal_request": internal,
            "result": None,
            "error": None,
        }
        with collect_data._COLLECTION_LOCK:
            collect_data._save_record(record)
        return record

    def _store_completed_record(
        self,
        collection_id: str,
        *,
        updated_at: str | None = None,
    ) -> tuple[dict, Path]:
        record = self._store_record(
            collection_id,
            state_name="completed",
            updated_at=updated_at,
        )
        output = collect_data._output_path(collection_id)
        output.write_text(
            "timestamp,value\n2026-06-01 06:00:00,1\n",
            encoding="utf-8",
        )
        record["result"] = {
            "filename": "sbe-collected-data-test.csv",
            "sha256": collect_data._sha256_file(output),
        }
        with collect_data._COLLECTION_LOCK:
            collect_data._save_record(record)
        return record, output

    def test_collection_status_and_verified_download_are_isolated(self) -> None:
        with patch.object(
            collect_data.historian_collection,
            "collect_historian_data",
            side_effect=self._fake_collection,
        ) as historian_call:
            created = self.client.post("/api/data-collections", json=self._request())

        self.assertEqual(created.status_code, 202, created.text)
        collection_id = created.json()["collection_id"]
        self.assertRegex(collection_id, r"^collect_[a-f0-9]{24}$")
        historian_call.assert_called_once()
        call = historian_call.call_args.kwargs
        self.assertEqual(call["from_time"], "2026-06-01T06:00:00")
        self.assertEqual(call["to_time"], "2026-06-01T07:00:00")
        self.assertEqual(call["data_groups"], ["solaredge", "weather"])
        self.assertEqual(dict(state.JOBS), self.jobs_before)

        status = self.client.get(f"/api/data-collections/{collection_id}")
        self.assertEqual(status.status_code, 200, status.text)
        payload = status.json()
        self.assertEqual(payload["state"], "completed")
        self.assertEqual(payload["result"]["quality"]["status"], "clean")
        self.assertEqual(
            payload["result"]["download_url"],
            f"/api/data-collections/{collection_id}/download",
        )
        encoded = status.text
        self.assertNotIn(str(self.temporary), encoded)
        self.assertNotIn("internal_request", encoded)

        download = self.client.get(
            f"/api/data-collections/{collection_id}/download"
        )
        self.assertEqual(download.status_code, 200, download.text)
        self.assertTrue(download.headers["content-type"].startswith("text/csv"))
        self.assertIn("attachment", download.headers["content-disposition"])
        self.assertIn("sbe-collected-data", download.headers["content-disposition"])
        self.assertEqual(download.headers["x-content-type-options"], "nosniff")
        self.assertIn("solaredge_measured_power", download.text)
        self.assertNotIn(collection_id, collect_data._DOWNLOAD_PINS)

        malformed_range = self.client.get(
            f"/api/data-collections/{collection_id}/download",
            headers={"Range": "not-a-byte-range"},
        )
        self.assertEqual(malformed_range.status_code, 400, malformed_range.text)
        self.assertNotIn(collection_id, collect_data._DOWNLOAD_PINS)

        unsatisfiable_range = self.client.get(
            f"/api/data-collections/{collection_id}/download",
            headers={"Range": "bytes=999999999-"},
        )
        self.assertEqual(
            unsatisfiable_range.status_code, 416, unsatisfiable_range.text
        )
        self.assertNotIn(collection_id, collect_data._DOWNLOAD_PINS)

        output = self.temporary / ".data_collections" / f"{collection_id}.csv"
        output.write_text("tampered", encoding="utf-8")
        tampered = self.client.get(
            f"/api/data-collections/{collection_id}/download"
        )
        self.assertEqual(tampered.status_code, 409, tampered.text)
        self.assertNotIn(str(self.temporary), tampered.text)

    def test_invalid_selection_and_window_fail_before_collection(self) -> None:
        with patch.object(
            collect_data.historian_collection, "collect_historian_data"
        ) as historian_call:
            empty = self.client.post(
                "/api/data-collections",
                json=self._request(data_groups=[]),
            )
            reversed_window = self.client.post(
                "/api/data-collections",
                json=self._request(from_time="02:00", to_time="01:00"),
            )

        self.assertEqual(empty.status_code, 422, empty.text)
        self.assertEqual(reversed_window.status_code, 422, reversed_window.text)
        historian_call.assert_not_called()

    def test_bazefield_failure_is_reported_without_a_download(self) -> None:
        with patch.object(
            collect_data.historian_collection,
            "collect_historian_data",
            side_effect=bazefield.BazefieldError("source unavailable"),
        ):
            created = self.client.post(
                "/api/data-collections",
                json=self._request(data_groups=["solaredge"]),
            )

        collection_id = created.json()["collection_id"]
        status = self.client.get(f"/api/data-collections/{collection_id}")
        self.assertEqual(status.status_code, 200, status.text)
        self.assertEqual(status.json()["state"], "failed")
        self.assertEqual(status.json()["error"]["code"], "bazefield_error")
        self.assertNotIn("source unavailable", status.text)
        self.assertIn("historian connection", status.json()["error"]["message"])
        unavailable = self.client.get(
            f"/api/data-collections/{collection_id}/download"
        )
        self.assertEqual(unavailable.status_code, 409, unavailable.text)

    def test_active_request_is_deduplicated_and_queue_is_bounded(self) -> None:
        duplicate_id = "collect_111111111111111111111111"
        self._store_record(duplicate_id, state_name="collecting")
        with patch.object(
            collect_data.historian_collection, "collect_historian_data"
        ) as historian_call:
            duplicate = self.client.post(
                "/api/data-collections", json=self._request()
            )
        self.assertEqual(duplicate.status_code, 202, duplicate.text)
        self.assertEqual(duplicate.json()["collection_id"], duplicate_id)
        historian_call.assert_not_called()

        with patch.object(config, "DATA_COLLECTION_MAX_ACTIVE", 1):
            full = self.client.post(
                "/api/data-collections",
                json=self._request(from_date="2026-05-31"),
            )
        self.assertEqual(full.status_code, 429, full.text)
        self.assertEqual(full.headers["retry-after"], "15")

    def test_rejected_full_queue_does_not_evict_retained_collection(self) -> None:
        retained_id = "collect_999999999999999999999999"
        active_id = "collect_aaaaaaaaaaaaaaaaaaaaaaaa"
        self._store_record(retained_id, state_name="completed")
        self._store_record(active_id, state_name="collecting")

        with (
            patch.object(config, "DATA_COLLECTION_MAX_RECORDS", 2),
            patch.object(config, "DATA_COLLECTION_MAX_ACTIVE", 1),
        ):
            rejected = self.client.post(
                "/api/data-collections",
                json=self._request(from_date="2026-05-31"),
            )

        self.assertEqual(rejected.status_code, 429, rejected.text)
        self.assertIsNotNone(collect_data._load_record(retained_id))
        self.assertIsNotNone(collect_data._load_record(active_id))

    def test_queue_record_write_failure_does_not_evict_retained_data(self) -> None:
        retained_id = "collect_bbbbbbbbbbbbbbbbbbbbbbbb"
        self._store_record(retained_id, state_name="completed")

        with (
            patch.object(config, "DATA_COLLECTION_MAX_RECORDS", 1),
            patch.object(
                collect_data,
                "_save_record",
                side_effect=OSError("simulated write failure"),
            ),
        ):
            rejected = self.client.post(
                "/api/data-collections",
                json=self._request(from_date="2026-05-31"),
            )

        self.assertEqual(rejected.status_code, 500, rejected.text)
        self.assertIsNotNone(collect_data._load_record(retained_id))

    def test_restart_reconciliation_and_retention_are_collection_only(self) -> None:
        interrupted_id = "collect_222222222222222222222222"
        interrupted = self._store_record(interrupted_id, state_name="collecting")
        partial = collect_data._output_path(interrupted_id)
        partial.write_text("partial", encoding="utf-8")

        self.assertEqual(collect_data.reconcile_interrupted_collections(), 1)
        recovered = collect_data._load_record(interrupted_id)
        self.assertEqual(recovered["state"], "failed")
        self.assertEqual(recovered["error"]["code"], "collection_interrupted")
        self.assertFalse(partial.exists())
        self.assertEqual(dict(state.JOBS), self.jobs_before)

        old_id = "collect_333333333333333333333333"
        old_time = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
        self._store_record(
            old_id,
            state_name="completed",
            updated_at=old_time,
        )
        collect_data._output_path(old_id).write_text("old", encoding="utf-8")
        with patch.object(config, "DATA_COLLECTION_RETENTION", timedelta(days=7)):
            removed = collect_data.prune_data_collections()
        self.assertGreaterEqual(removed, 1)
        self.assertIsNone(collect_data._load_record(old_id))

    def test_metadata_only_records_count_toward_storage_quota(self) -> None:
        collection_id = "collect_444444444444444444444444"
        self._store_record(collection_id, state_name="failed")
        record_path = collect_data._record_path(collection_id)
        self.assertGreater(record_path.stat().st_size, 1)

        with patch.object(config, "DATA_COLLECTION_MAX_STORAGE_BYTES", 1):
            removed = collect_data.prune_data_collections()

        self.assertEqual(removed, 1)
        self.assertFalse(record_path.exists())

    def test_retained_record_cap_prunes_oldest_terminal_record(self) -> None:
        older_id = "collect_555555555555555555555555"
        newer_id = "collect_666666666666666666666666"
        older_time = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        newer_time = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        self._store_record(older_id, state_name="failed", updated_at=older_time)
        self._store_record(newer_id, state_name="failed", updated_at=newer_time)

        with patch.object(config, "DATA_COLLECTION_MAX_RECORDS", 1):
            removed = collect_data.prune_data_collections()

        self.assertEqual(removed, 1)
        self.assertIsNone(collect_data._load_record(older_id))
        self.assertIsNotNone(collect_data._load_record(newer_id))

    def test_pruning_does_not_remove_a_streaming_download(self) -> None:
        collection_id = "collect_777777777777777777777777"
        old_time = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
        _record, output = self._store_completed_record(
            collection_id,
            updated_at=old_time,
        )

        response = collect_data.download_data_collection(collection_id)
        try:
            with patch.object(
                config, "DATA_COLLECTION_RETENTION", timedelta(days=7)
            ):
                removed_while_streaming = collect_data.prune_data_collections()
            self.assertEqual(removed_while_streaming, 0)
            self.assertTrue(output.exists())
            self.assertIsNotNone(collect_data._load_record(collection_id))
            self.assertIsInstance(response, collect_data._PinnedFileResponse)
        finally:
            collect_data._release_download_pin(collection_id)

        with patch.object(config, "DATA_COLLECTION_RETENTION", timedelta(days=7)):
            removed_after_streaming = collect_data.prune_data_collections()
        self.assertEqual(removed_after_streaming, 1)
        self.assertFalse(output.exists())
        self.assertIsNone(collect_data._load_record(collection_id))

    def test_interrupted_download_send_releases_pin(self) -> None:
        collection_id = "collect_888888888888888888888888"
        self._store_completed_record(collection_id)
        response = collect_data.download_data_collection(collection_id)

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def interrupted_send(_message):
            raise RuntimeError("client disconnected")

        scope = {
            "type": "http",
            "method": "GET",
            "path": f"/api/data-collections/{collection_id}/download",
            "headers": [],
            "extensions": {},
        }
        with self.assertRaisesRegex(RuntimeError, "client disconnected"):
            asyncio.run(response(scope, receive, interrupted_send))
        self.assertNotIn(collection_id, collect_data._DOWNLOAD_PINS)

    def test_unknown_and_malformed_ids_are_not_disclosed(self) -> None:
        for collection_id in (
            "collect_" + "0" * 24,
            "../private",
            "collection-not-safe",
        ):
            with self.subTest(collection_id=collection_id):
                response = self.client.get(
                    f"/api/data-collections/{collection_id}"
                )
                self.assertEqual(response.status_code, 404, response.text)


if __name__ == "__main__":
    unittest.main()
