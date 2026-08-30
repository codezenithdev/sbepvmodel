from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
from io import BytesIO
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pypdf import PdfReader

from sbepv.autonomy import reporting


_DIGEST = "a" * 64


def _scenario(
    index: int,
    *,
    solaredge_dominant: float,
    solectria_dominant: float,
) -> dict:
    scenario_revision_id = f"dscr_report_scenario_{index}_r1"
    tea_job_id = f"tea_report_scenario_{index}"
    neutral = 1.0 - solaredge_dominant - solectria_dominant
    return {
        "scenario_id": f"dsc_report_scenario_{index}",
        "scenario_revision_id": scenario_revision_id,
        "label": "Current baseline" if index == 0 else "Controlled inverter case",
        "kind": "baseline" if index == 0 else "alternative",
        "request_sha256": f"{index + 1:x}" * 64,
        "attempt": {
            "tea_job_id": tea_job_id,
            "attempt_number": 1,
            "retry_of_job_id": None,
        },
        "result": {
            "metrics": {
                "LifecycleLCOE_SE": {
                    "percentiles": {"p5": 0.081, "p50": 0.094, "p95": 0.112},
                    "unit": "USD/kWh",
                    "population_semantics": "all durable TEA realizations",
                    "count": 10_000,
                },
                "LifecycleLCOE_SOL": {
                    "percentiles": {"p5": 0.087, "p50": 0.103, "p95": 0.121},
                    "unit": "USD/kWh",
                    "population_semantics": "all durable TEA realizations",
                    "count": 10_000,
                },
            },
            "joint_outcomes": {
                "tradeoff_classes": {
                    "denominator": 10_000,
                    "probabilities": {
                        "cost_saving_energy_gain": solaredge_dominant,
                        "cost_neutral_energy_gain": 0.0,
                        "cost_increase_energy_loss": solectria_dominant,
                        "cost_increase_energy_gain": neutral,
                    },
                }
            },
            "sensitivity": {
                "lifecycle_cost_delta_se_minus_sol": {
                    "steps": [
                        {
                            "predictor_id": "cost.solaredge.capex",
                            "incremental_r_squared": 0.41,
                            "standardized_beta": 0.68,
                            "sign": "positive",
                        }
                    ]
                }
            },
            "convergence": {"status": "stable", "reasons": []},
        },
        "provenance": {
            "routine_result_sha256": f"{index + 3:x}" * 64,
            "sealed_calculation_sha256": f"{index + 5:x}" * 64,
            "reporting_tieout_sha256": f"{index + 7:x}" * 64,
        },
        "evidence": {"evidence_set_sha256": f"{index + 9:x}" * 64},
    }


def _sources() -> tuple[dict, dict, dict, dict]:
    case = {
        "case_id": "case_reporting_fixture",
        "revision": 12,
        "question": (
            "Should the site retain the SolarEdge design for the next approved "
            "capital plan?"
        ),
        "basis_lock": {
            "calibration_job_id": "calibration-promoted-17",
            "calibration_promoted_at": "2026-08-29T16:00:00Z",
            "source_annual_job_id": "annual-source-42",
            "source_snapshot_sha256": "1" * 64,
        },
    }
    brief = {
        "brief_revision_id": "dbr_case_reporting_fixture_r3",
        "revision": 3,
        "comparison_bundle_id": "dcmp_reporting_fixture",
        "comparison_bundle_sha256": "2" * 64,
        "provenance_sha256": "3" * 64,
        "caveats": [
            "This is a model-informed capital decision, not a plant-control command."
        ],
        "reversal_conditions": [
            {
                "code": "capex_quote_change",
                "label": "A verified capital quote changes the modeled cost ordering",
                "next_action": "Create a controlled case revision.",
            }
        ],
        "comparison_bundle": {
            "confirmation": {
                "confirmation_id": "dconf_reporting_fixture",
                "receipt_sha256": "4" * 64,
            },
            "scenarios": [
                _scenario(
                    0,
                    solaredge_dominant=0.64,
                    solectria_dominant=0.11,
                ),
                _scenario(
                    1,
                    solaredge_dominant=0.71,
                    solectria_dominant=0.08,
                ),
            ],
        },
    }
    recommendation = {
        "recommendation_id": "drec_reporting_fixture",
        "classification": "solaredge_preferred",
        "confidence": "strong",
        "contract_version": "autonomy-conservative-dominance-v1",
        "contract_digest": _DIGEST,
        "reasons": [
            "The approved directional classes favor SolarEdge in both scenarios.",
            "The stored convergence gates are stable.",
        ],
        "warnings": [
            {
                "code": "capital_quote_age",
                "detail": "Refresh the capital quote before procurement.",
            }
        ],
        "model_limitations": ["Sensitivity coefficients are associative, not causal."],
        "evidence_gaps": ["No post-award procurement quote is stored."],
        "reversal_conditions": deepcopy(brief["reversal_conditions"]),
        "next_actions": ["Refresh the capital quote and retain the immutable receipt."],
        "further_questions": ["Has the procurement quote changed by a material amount?"],
    }
    signoff = {
        "signoff_id": "dsgn_reporting_fixture",
        "disposition": "accept",
        "decision_owner_name": "Morgan Manager",
        "rationale": "Proceed subject to the recorded procurement warning.",
        "acknowledgement_version": "autonomy-signoff-ack-v1",
        "signed_at": "2026-08-30T17:00:00Z",
        "decision_snapshot_sha256": "5" * 64,
    }
    return case, brief, recommendation, signoff


def _snapshot(kind: str) -> dict:
    case, brief, recommendation, signoff = _sources()
    return reporting.prepare_report_snapshot(
        report_kind=kind,
        case=case,
        brief=brief,
        recommendation=recommendation,
        signoff=signoff if kind == "final" else None,
    )


def _pdf_text(payload: bytes) -> str:
    reader = PdfReader(BytesIO(payload), strict=True)
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def _record(
    snapshot: dict,
    rendered: reporting.RenderedDecisionReport,
    storage_key: str,
) -> dict:
    return {
        "snapshot": deepcopy(snapshot),
        "snapshot_sha256": reporting.canonical_sha256(snapshot),
        "storage_key": storage_key,
        "pdf_sha256": rendered.pdf_sha256,
        "byte_count": rendered.byte_count,
        "page_count": rendered.page_count,
    }


class AutonomyReportingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.draft_snapshot = _snapshot("draft")
        cls.final_snapshot = _snapshot("final")
        cls.draft_rendered = reporting.render_manager_pdf(cls.draft_snapshot)
        cls.final_rendered = reporting.render_manager_pdf(cls.final_snapshot)

    def assert_report_error(self, expected_code: str, callback) -> None:
        with self.assertRaises(reporting.DecisionReportError) as caught:
            callback()
        self.assertEqual(expected_code, caught.exception.code)

    def test_repeated_render_is_byte_identical(self) -> None:
        repeated = reporting.render_manager_pdf(self.draft_snapshot)

        self.assertEqual(self.draft_rendered.pdf_bytes, repeated.pdf_bytes)
        self.assertEqual(self.draft_rendered.pdf_sha256, repeated.pdf_sha256)
        self.assertEqual(self.draft_rendered.byte_count, repeated.byte_count)
        self.assertEqual(self.draft_rendered.page_count, repeated.page_count)
        self.assertEqual(
            self.draft_rendered.renderer_fingerprint,
            repeated.renderer_fingerprint,
        )

    def test_draft_report_identity_binds_exact_case_revision(self) -> None:
        case, brief, recommendation, _signoff = _sources()
        first = reporting.prepare_report_snapshot(
            report_kind="draft",
            case=case,
            brief=brief,
            recommendation=recommendation,
            signoff=None,
        )
        revised_case = deepcopy(case)
        revised_case["revision"] += 1
        second = reporting.prepare_report_snapshot(
            report_kind="draft",
            case=revised_case,
            brief=brief,
            recommendation=recommendation,
            signoff=None,
        )
        self.assertNotEqual(
            first["report"]["report_identity_sha256"],
            second["report"]["report_identity_sha256"],
        )
        self.assertNotEqual(
            first["report"]["report_id"], second["report"]["report_id"]
        )

    def test_draft_watermark_final_authority_and_required_sections(self) -> None:
        draft_text = _pdf_text(self.draft_rendered.pdf_bytes)
        final_text = _pdf_text(self.final_rendered.pdf_bytes)

        self.assertIn("DRAFT - UNSIGNED", draft_text)
        self.assertNotIn("DRAFT - UNSIGNED", final_text)
        self.assertIn("Morgan Manager", final_text)
        self.assertIn("Authenticated application sign-off", final_text)
        for section in (
            "PV Decision Report",
            "Executive Summary",
            "Decision authority",
            "Baseline and alternatives",
            "Directional outcome probabilities",
            "Sensitivity and convergence quality",
            "What could change the decision",
            "Evidence, warnings, caveats, and limitations",
            "Recommended next step",
            "Further questions",
            "Readable audit trail",
            "Technical export references",
        ):
            with self.subTest(section=section):
                self.assertIn(section, draft_text)
                self.assertIn(section, final_text)

    def test_snapshot_and_pdf_include_chart_contract_and_technical_exports(self) -> None:
        chart_contracts = self.draft_snapshot["report"]["chart_contracts"]
        exports = self.draft_snapshot["technical_exports"]
        text = _pdf_text(self.draft_rendered.pdf_bytes)

        self.assertEqual("directional-outcome-probabilities", chart_contracts[0]["id"])
        self.assertEqual("direct_labels_and_table_fallback", chart_contracts[0]["non_color_encoding"])
        self.assertEqual(4, len(exports))
        self.assertEqual({"csv", "xlsx"}, {item["url"].rsplit("/", 1)[-1] for item in exports})
        self.assertIn("SolarEdge dominant", text)
        self.assertIn("Solectria dominant", text)
        self.assertIn("0.64", text)
        self.assertIn("0.71", text)
        self.assertIn(
            "/api/technoeconomic/jobs/tea_report_scenario_0/exports/csv",
            text,
        )

    def test_renderer_fingerprint_tampering_fails_closed(self) -> None:
        tampered = deepcopy(self.draft_snapshot)
        tampered["report"]["renderer_fingerprint"] = "forged-renderer"

        self.assert_report_error(
            "report_renderer_identity_mismatch",
            lambda: reporting.render_manager_pdf(tampered),
        )

    def test_publish_is_idempotent_and_verify_rechecks_all_identities(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "private-reports"
            storage_key = reporting.publish_report_pdf(root, self.draft_rendered)
            self.assertEqual(
                reporting.report_storage_key(self.draft_rendered.pdf_sha256),
                storage_key,
            )
            self.assertEqual(
                storage_key,
                reporting.publish_report_pdf(root, self.draft_rendered),
            )

            payload, verification = reporting.verified_report_pdf(
                root,
                _record(self.draft_snapshot, self.draft_rendered, storage_key),
            )

            self.assertEqual(self.draft_rendered.pdf_bytes, payload)
            self.assertEqual("verified", verification["status"])
            self.assertEqual("application/pdf", verification["media_type"])
            self.assertEqual(self.draft_rendered.pdf_sha256, verification["pdf_sha256"])
            self.assertEqual(self.draft_rendered.page_count, verification["page_count"])
            self.assertEqual("PV Decision Report", verification["metadata"]["/Title"])
            self.assertEqual(
                "Immutable Autonomy decision snapshot",
                verification["metadata"]["/Subject"],
            )
            self.assertEqual(
                reporting.REPORT_GENERATION_CONTRACT_VERSION,
                verification["metadata"]["/Creator"],
            )

    def test_inconsistent_rendered_artifacts_are_rejected_without_writing(self) -> None:
        malformed_pdf = b"%PDF-1.4\nnot a parseable PDF\n%%EOF\n"
        variants = {
            "bytes": replace(self.draft_rendered, pdf_bytes=b"not-a-pdf"),
            "self_consistent_malformed_pdf": replace(
                self.draft_rendered,
                pdf_bytes=malformed_pdf,
                pdf_sha256=sha256(malformed_pdf).hexdigest(),
                byte_count=len(malformed_pdf),
                page_count=1,
            ),
            "digest": replace(self.draft_rendered, pdf_sha256="0" * 64),
            "byte_count": replace(
                self.draft_rendered,
                byte_count=self.draft_rendered.byte_count + 1,
            ),
            "page_count": replace(self.draft_rendered, page_count=0),
            "renderer": replace(
                self.draft_rendered,
                renderer_fingerprint="forged-renderer",
            ),
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            for label, rendered in variants.items():
                with self.subTest(label=label):
                    root = Path(temp_dir) / label
                    self.assert_report_error(
                        "report_rendered_artifact_invalid",
                        lambda rendered=rendered, root=root: reporting.publish_report_pdf(
                            root, rendered
                        ),
                    )
                    self.assertFalse(root.exists())

    def test_wrong_but_well_formed_storage_key_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "private-reports"
            correct_key = reporting.publish_report_pdf(root, self.draft_rendered)
            wrong_key = reporting.report_storage_key("0" * 64)
            wrong_path = root.joinpath(*wrong_key.split("/"))
            wrong_path.parent.mkdir(parents=True)
            wrong_path.write_bytes(self.draft_rendered.pdf_bytes)
            record = _record(self.draft_snapshot, self.draft_rendered, correct_key)
            record["storage_key"] = wrong_key

            self.assert_report_error(
                "report_storage_identity_mismatch",
                lambda: reporting.verified_report_pdf(root, record),
            )

    def test_tampered_stored_bytes_and_snapshot_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "private-reports"
            storage_key = reporting.publish_report_pdf(root, self.draft_rendered)
            record = _record(self.draft_snapshot, self.draft_rendered, storage_key)
            artifact = root.joinpath(*storage_key.split("/"))
            tampered_payload = bytearray(artifact.read_bytes())
            tampered_payload[12] ^= 1
            artifact.write_bytes(bytes(tampered_payload))

            self.assert_report_error(
                "report_artifact_tampered",
                lambda: reporting.verified_report_pdf(root, record),
            )

            record["snapshot"]["case"]["question"] = "A forged question"
            self.assert_report_error(
                "report_snapshot_tampered",
                lambda: reporting.verified_report_pdf(root, record),
            )

    def test_traversal_storage_key_is_rejected(self) -> None:
        record = _record(
            self.draft_snapshot,
            self.draft_rendered,
            "../../sha256/aa/" + "a" * 64 + ".pdf",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            self.assert_report_error(
                "report_storage_key_invalid",
                lambda: reporting.verified_report_pdf(Path(temp_dir), record),
            )

    def test_symlinked_root_is_rejected_when_supported(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            target = base / "real-root"
            target.mkdir()
            link = base / "linked-root"
            try:
                os.symlink(target, link, target_is_directory=True)
            except (NotImplementedError, OSError) as exc:
                self.skipTest(f"directory symlinks unavailable: {exc}")

            self.assert_report_error(
                "report_root_symlink",
                lambda: reporting.publish_report_pdf(link, self.draft_rendered),
            )

    def test_symlinked_content_address_component_is_rejected_when_supported(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "private-reports"
            outside = base / "outside"
            root.mkdir()
            outside.mkdir()
            try:
                os.symlink(outside, root / "sha256", target_is_directory=True)
            except (NotImplementedError, OSError) as exc:
                self.skipTest(f"directory symlinks unavailable: {exc}")

            self.assert_report_error(
                "report_path_symlink",
                lambda: reporting.publish_report_pdf(root, self.draft_rendered),
            )

    def test_render_and_publish_enforce_size_and_page_bounds(self) -> None:
        with patch.object(
            reporting,
            "REPORT_MAX_BYTES",
            self.draft_rendered.byte_count - 1,
        ):
            self.assert_report_error(
                "report_pdf_invalid",
                lambda: reporting.render_manager_pdf(self.draft_snapshot),
            )
            with tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir) / "too-large"
                self.assert_report_error(
                    "report_rendered_artifact_invalid",
                    lambda: reporting.publish_report_pdf(root, self.draft_rendered),
                )
                self.assertFalse(root.exists())

        with patch.object(reporting, "REPORT_MAX_PAGES", 0):
            self.assert_report_error(
                "report_page_count_invalid",
                lambda: reporting.render_manager_pdf(self.draft_snapshot),
            )
            with tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir) / "too-many-pages"
                self.assert_report_error(
                    "report_rendered_artifact_invalid",
                    lambda: reporting.publish_report_pdf(root, self.draft_rendered),
                )
                self.assertFalse(root.exists())


if __name__ == "__main__":
    unittest.main()
