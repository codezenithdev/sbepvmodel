from __future__ import annotations

import unittest

from sbepv.autonomy import serializers


class AutonomySerializerTests(unittest.TestCase):
    def test_safe_public_value_normalizes_secret_like_key_names(self) -> None:
        public = serializers.safe_public_value(
            {
                "apiKey": "do-not-return",
                "Lease.Token": "do-not-return",
                "source-path": r"C:\private\annual.json",
                "nested": {
                    "Authorization": "Bearer do-not-return",
                    "client_secret": "do-not-return",
                },
                "request_path": "/cost_lines/0/distribution/value",
                "monkey": "safe value",
            }
        )

        self.assertEqual(
            public,
            {
                "nested": {},
                "request_path": "/cost_lines/0/distribution/value",
                "monkey": "safe value",
            },
        )

    def test_safe_public_value_redacts_private_paths_and_credentials(self) -> None:
        public = serializers.safe_public_value(
            {
                "windows": r"C:\server\private\annual.json",
                "posix": "/tmp/private/annual.json",
                "file_uri": "file:///var/private/annual.json",
                "header_value": "Authorization: Bearer abcdefghijklmnop",
                "bearer": "Use Bearer abcdefghijklmnop for the request",
                "provider_value": "sk-proj-abcdefghijklmno",
                "connection": "postgresql://private-user:private-pass@db.test/data",
                "path_with_spaces": r"loaded C:\private\case files\annual.json",
                "url": "https://example.test/autonomy/cases/case-1",
                "json_pointer": "/cost_lines/0/distribution/value",
            }
        )

        self.assertEqual(public["windows"], "[redacted path]")
        self.assertEqual(public["posix"], "[redacted path]")
        self.assertEqual(public["file_uri"], "[redacted path]")
        self.assertEqual(public["header_value"], "[redacted credential]")
        self.assertEqual(
            public["bearer"], "Use [redacted credential] for the request"
        )
        self.assertEqual(public["provider_value"], "[redacted secret]")
        self.assertEqual(public["connection"], "[redacted credential URI]")
        self.assertEqual(public["path_with_spaces"], "loaded [redacted path]")
        self.assertEqual(
            public["url"], "https://example.test/autonomy/cases/case-1"
        )
        self.assertEqual(
            public["json_pointer"], "/cost_lines/0/distribution/value"
        )

    def test_public_record_projections_share_the_redactor(self) -> None:
        event = serializers.public_decision_event(
            {
                "payload": {
                    "apiKey": "do-not-return",
                    "detail": r"loaded C:\private\source.json",
                }
            }
        )
        scenario = serializers.public_decision_scenario(
            {
                "request": {
                    "note": "source is /var/private/source.json",
                    "request_path": "/cost_lines/0/distribution/value",
                },
                "validation": {"access-token": "do-not-return"},
            }
        )
        confirmation = serializers.public_scenario_confirmation(
            {
                "receipt": {
                    "note": "Authorization=Bearer abcdefghijklmnop",
                    "serverPath": "/srv/private/receipt.json",
                }
            }
        )

        self.assertEqual(
            event["payload"], {"detail": "loaded [redacted path]"}
        )
        self.assertEqual(
            scenario["request"],
            {
                "note": "source is [redacted path]",
                "request_path": "/cost_lines/0/distribution/value",
            },
        )
        self.assertEqual(scenario["validation"], {})
        self.assertEqual(
            confirmation["receipt"], {"note": "[redacted credential]"}
        )


if __name__ == "__main__":
    unittest.main()
