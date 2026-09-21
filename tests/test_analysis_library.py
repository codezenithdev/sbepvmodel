from __future__ import annotations

import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from sbepv.api import analysis_library, state


class AnalysisLibraryTests(unittest.TestCase):
    def setUp(self):
        from tests.test_technoeconomic_store import TechnoeconomicStoreTests
        self.fixture = TechnoeconomicStoreTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.store = self.fixture.store
        self.fixture._create_tea(job_id="tea_visible")
        self.store.save_result("annual-source", name="Reviewed June annual")

    def test_search_pages_and_metadata_do_not_mix_store_payloads(self):
        before = self.store.get_job("annual-source")
        first = self.store.list_analysis_library(limit=1)
        second = self.store.list_analysis_library(limit=1, offset=first["next_offset"])
        self.assertEqual(first["items"][0]["id"], "technoeconomic:tea_visible")
        self.assertEqual(second["items"][0]["id"], "annual:annual-source")
        self.assertIsNone(second["next_offset"])
        match = self.store.list_analysis_library(query="reviewed JUNE", status="done")
        self.assertEqual([x["job_id"] for x in match["items"]], ["annual-source"])
        self.assertTrue(match["items"][0]["saved"])
        self.assertNotIn("request_json", match["items"][0])
        self.assertNotIn("result", match["items"][0])
        self.assertEqual(self.store.get_job("annual-source"), before)
        self.assertEqual(len(self.store.list_saved_results()), 1)
        self.assertEqual(self.store.list_analysis_library(query="%' OR 1=1 --")["items"], [])

    def test_retired_tea_is_filtered_using_existing_guard(self):
        # This fixture exercises the existing archive protection, without changing it.
        from sbepv.store import RetiredWorkflow
        original = self.store._ensure_technoeconomic_row_supported
        def reject(connection, row):
            if row["tea_job_id"] == "tea_visible":
                raise RetiredWorkflow("retired fixture")
            return original(connection, row)
        with patch.object(self.store, "_ensure_technoeconomic_row_supported", side_effect=reject):
            page = self.store.list_analysis_library(limit=1)
        self.assertEqual([x["job_id"] for x in page["items"]], ["annual-source"])
        self.assertIsNone(page["next_offset"])

    def test_promoted_baseline_is_distinct_from_bookmark(self):
        with self.store._transaction(write=True) as connection:
            connection.execute(
                "INSERT INTO current_baselines(mode, job_id, promoted_at) VALUES (?, ?, ?)",
                ("annual", "annual-source", "2026-09-21T12:00:00Z"),
            )
        records = self.store.list_analysis_library()["items"]
        annual = next(item for item in records if item["workflow"] == "annual")
        tea = next(item for item in records if item["workflow"] == "technoeconomic")
        self.assertTrue(annual["promoted_baseline"])
        self.assertTrue(annual["saved"])
        self.assertFalse(tea["promoted_baseline"])
        self.assertFalse(tea["saved"])

    def test_api_validation_cache_policy_and_workflow_filter(self):
        app = FastAPI()
        app.include_router(analysis_library.router)
        client = TestClient(app)
        with patch.object(state, "AGENT_STORE", self.store):
            response = client.get("/api/analysis-library?workflow=technoeconomic")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers["cache-control"], "private, no-store")
            self.assertEqual([x["job_id"] for x in response.json()["items"]], ["tea_visible"])
            for query in ("limit=101", "offset=-1", "workflow=autonomy", "q=" + "x" * 201):
                self.assertEqual(client.get("/api/analysis-library?" + query).status_code, 422)
            self.assertEqual(client.post("/api/analysis-library").status_code, 405)


if __name__ == "__main__":
    unittest.main()
