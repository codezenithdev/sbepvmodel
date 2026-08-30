from __future__ import annotations

import unittest

from sbepv.autonomy import comparison, serializers


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

    def test_comparison_and_brief_projections_are_traceable_and_sanitized(self) -> None:
        bundle = {
            "schema_version": "autonomy-comparison-bundle-v1",
            "scenarios": [
                {
                    "scenario_revision_id": "dsr_exact",
                    "result": {
                        "metrics": {
                            "cost": {
                                "unit": "USD/Wdc",
                                "percentiles": {
                                    "p5": None,
                                    "p50": 1.25,
                                    "p95": 2.5,
                                },
                                "serverPath": r"C:\private\sealed.npz",
                            }
                        }
                    },
                }
            ],
        }
        bundle = serializers.exact_public_comparison_bundle(bundle)
        bundle["bundle_hash"] = comparison.canonical_comparison_bundle_sha256(
            bundle
        )
        public_bundle = serializers.public_decision_comparison_bundle(
            {
                "comparison_bundle_id": "dcmp_exact",
                "case_id": "case_exact",
                "source_confirmation_id": "dconf_exact",
                "expected_case_revision": 7,
                "bundle_schema_version": "autonomy-comparison-bundle-v1",
                "bundle_sha256": bundle["bundle_hash"],
                "is_complete": True,
                "recommendation_eligible": False,
                "bundle": bundle,
            }
        )
        metric = public_bundle["bundle"]["scenarios"][0]["result"]["metrics"][
            "cost"
        ]
        self.assertEqual("USD/Wdc", metric["unit"])
        self.assertIsNone(metric["percentiles"]["p5"])
        self.assertNotIn("serverPath", metric)

        public_brief = serializers.public_decision_brief(
            {
                "brief_id": "dbf_exact",
                "brief_revision_id": "dbr_exact",
                "revision": 1,
                "case_id": "case_exact",
                "source_confirmation_id": "dconf_exact",
                "comparison_bundle_id": "dcmp_exact",
                "comparison_bundle_sha256": bundle["bundle_hash"],
                "comparison_bundle": bundle,
                "recommendation_classification": (
                    "classification_pending_contract"
                ),
                "confidence_state": "classification_pending_contract",
                "provenance": {},
            }
        )
        self.assertFalse(public_brief["signed"])
        self.assertEqual({}, public_brief["provenance"])
        self.assertEqual(
            "classification_pending_contract",
            public_brief["recommendation_classification"],
        )

    def test_hashed_comparison_publication_is_exact_and_never_truncated(self) -> None:
        deep: dict = {"leaf": "kept"}
        for index in range(12):
            deep = {f"level_{index}": deep}
        bundle = serializers.exact_public_comparison_bundle(
            {
                "schema_version": "autonomy-comparison-bundle-v1",
                "is_complete": True,
                "recommendation_eligible": False,
                "scenarios": [
                    {
                        "scenario_revision_id": "dsr_exact",
                        "result": {
                            "metrics": {
                                "cost": {
                                    "cdf": list(range(1_205)),
                                }
                            },
                            "convergence": deep,
                        },
                    }
                ],
            }
        )
        bundle["bundle_hash"] = comparison.canonical_comparison_bundle_sha256(
            bundle
        )
        public = serializers.public_decision_comparison_bundle(
            {
                "comparison_bundle_id": "dcmp_exact",
                "bundle_sha256": bundle["bundle_hash"],
                "bundle": bundle,
            }
        )

        self.assertEqual(bundle, public["bundle"])
        self.assertEqual(
            public["bundle_sha256"],
            comparison.canonical_comparison_bundle_sha256(public["bundle"]),
        )
        self.assertEqual(1_205, len(public["bundle"]["scenarios"][0]["result"]["metrics"]["cost"]["cdf"]))

    def test_non_public_hashed_bundle_fails_closed_instead_of_changing_digest(self) -> None:
        with self.assertRaisesRegex(ValueError, "canonical public projection"):
            serializers.public_decision_comparison_bundle(
                {
                    "comparison_bundle_id": "dcmp_private",
                    "bundle_sha256": "a" * 64,
                    "bundle": {
                        "schema_version": "autonomy-comparison-bundle-v1",
                        "storage_key": "private/source.csv",
                    },
                }
            )
        with self.assertRaisesRegex(ValueError, "canonical public projection"):
            serializers.public_decision_brief(
                {
                    "brief_revision_id": "dbr_private",
                    "comparison_bundle": {"schema_version": "safe"},
                    "provenance": {"lease_token": "never-public"},
                }
            )


if __name__ == "__main__":
    unittest.main()
