"""HTTP policy checks use mocked lookups and never start the model worker."""
import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sbepv.api import main, state


class HttpCachePolicyTests(unittest.TestCase):
    def setUp(self):
        credentials = patch.dict(os.environ, {
            "DASHBOARD_BASIC_USER": "cache-test", "DASHBOARD_BASIC_PASSWORD": "fixture-password",
        })
        credentials.start()
        self.addCleanup(credentials.stop)
        self.client = TestClient(main.app)
        self.addCleanup(self.client.close)
        self.auth = ("cache-test", "fixture-password")

    def assert_private(self, response, status):
        self.assertEqual(response.status_code, status, response.text[:200])
        self.assertEqual(response.headers.get("cache-control"), "private, no-store")

    def test_mutable_successes_and_errors_are_not_cached(self):
        with patch.object(state.AGENT_STORE, "get_current_baseline", return_value=None):
            self.assert_private(self.client.get("/api/session", auth=self.auth), 200)
        with patch.object(main, "_get_job_record", return_value={
            "id": "fixture-job", "state": "running", "progress": 20, "stage": "Testing",
        }):
            self.assert_private(self.client.get("/api/status/fixture-job", auth=self.auth), 200)
        with patch.object(main, "_get_job_record", return_value=None):
            self.assert_private(self.client.get("/api/status/missing", auth=self.auth), 404)
        self.assert_private(self.client.post("/api/run", json={}, auth=self.auth), 422)

    def test_authentication_and_retired_routes_keep_their_denials(self):
        response = self.client.get("/api/session")
        self.assert_private(response, 401)
        self.assertIn("Basic", response.headers["www-authenticate"])
        self.assert_private(self.client.get("/api/autonomy/cases", auth=self.auth), 404)
        response = self.client.get("/outputs/.agent_state/solar_agent.sqlite3", auth=self.auth)
        self.assertEqual(response.status_code, 404)

    def test_html_and_file_cache_policies_remain_independent(self):
        self.assertEqual(self.client.get("/", auth=self.auth).headers["cache-control"], "no-store")
        response = self.client.get("/annual-warning.png", auth=self.auth)
        self.assertEqual(response.status_code, 200)
        self.assertIn("etag", response.headers)
        self.assertNotIn("cache-control", response.headers)
