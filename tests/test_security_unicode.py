"""Basic credentials accepted as UTF-8 must be compared without server errors."""

import base64
import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from sbepv.api import main, security


def authorization(username, password):
    payload = f"{username}:{password}".encode("utf-8")
    return "Basic " + base64.b64encode(payload).decode("ascii")


class UnicodeBasicAuthenticationTests(unittest.TestCase):
    def test_unicode_in_unmatched_credentials_returns_401(self):
        with patch.dict(os.environ, {
            "DASHBOARD_BASIC_USER": "tester",
            "DASHBOARD_BASIC_PASSWORD": "secret",
        }):
            client = TestClient(main.app)
            self.addCleanup(client.close)
            for username, password in (("téstér", "secret"), ("tester", "sëcret")):
                with self.subTest(username=username):
                    response = client.get("/api/session", headers={
                        "Authorization": authorization(username, password),
                    })
                    self.assertEqual(response.status_code, 401)
                    self.assertIn("Basic", response.headers["www-authenticate"])

    def test_configured_unicode_credentials_match_exactly(self):
        with patch.dict(os.environ, {
            "DASHBOARD_BASIC_USER": "téstér",
            "DASHBOARD_BASIC_PASSWORD": "sëcret:with:colon",
        }):
            self.assertEqual(
                security._basic_auth_result(authorization("téstér", "sëcret:with:colon")),
                (True, "téstér"),
            )
            self.assertEqual(
                security._basic_auth_result(authorization("tester", "sëcret:with:colon")),
                (False, None),
            )

    def test_malformed_encoding_stays_unauthenticated(self):
        with patch.dict(os.environ, {
            "DASHBOARD_BASIC_USER": "tester",
            "DASHBOARD_BASIC_PASSWORD": "secret",
        }):
            for header in ("Basic !!!", "Basic /zpwYXNzd29yZA==", authorization("tester", "wrong")):
                with self.subTest(header=header):
                    self.assertEqual(security._basic_auth_result(header), (False, None))
