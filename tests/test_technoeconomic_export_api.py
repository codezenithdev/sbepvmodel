from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import unittest
import uuid
from unittest.mock import patch

from fastapi.testclient import TestClient

from sbepv.api import config, state
from sbepv.api import main as app
from sbepv.api.artifacts import (
    TECHNOECONOMIC_PUBLIC_ARTIFACT_CONTRACT,
    _canonical_manifest_sha256,
    _technoeconomic_attempt_directory,
)


_XLSX_MEDIA_TYPE = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)
_ARTIFACT_SPECS = {
    "csv_bundle": (
        "technoeconomic-results-csv-v1.zip",
        "application/zip",
        b"synthetic csv zip bytes",
    ),
    "xlsx_workbook": (
        "technoeconomic-results-v1.xlsx",
        _XLSX_MEDIA_TYPE,
        b"synthetic xlsx bytes",
    ),
    "cdf_plot": (
        "technoeconomic-cdf-v1.png",
        "image/png",
        b"synthetic cdf png bytes",
    ),
    "sensitivity_plot": (
        "technoeconomic-sensitivity-v1.png",
        "image/png",
        b"synthetic sensitivity png bytes",
    ),
    "convergence_plot": (
        "technoeconomic-convergence-v1.png",
        "image/png",
        b"synthetic convergence png bytes",
    ),
}
_PUBLIC_CONTRACT_BY_ID = {
    specification["artifact_id"]: specification
    for specification in TECHNOECONOMIC_PUBLIC_ARTIFACT_CONTRACT.values()
}


class _FixtureStore:
    def __init__(self, job: dict) -> None:
        self.job: dict | None = job

    def get_technoeconomic_job(self, job_id: str):
        return self.job if self.job is not None and job_id == self.job["id"] else None

    def delete_technoeconomic_job(self, job_id: str, *, before_delete=None) -> None:
        if self.job is None or job_id != self.job["id"]:
            raise AssertionError("unexpected fixture job id")
        if before_delete is not None:
            before_delete(deepcopy(self.job))
        self.job = None


class TechnoeconomicExportApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.test_root = (
            Path(__file__).resolve().parent / f".tea-export-api-{uuid.uuid4().hex}"
        )
        self.output = self.test_root / "outputs"
        self.output.mkdir(parents=True)
        self.output_patch = patch.object(config, "OUTPUT_DIR", self.output)
        self.output_patch.start()
        self.job_id = "tea_export_fixture"
        self.lease_token = "lease_fixture"
        self.attempt = _technoeconomic_attempt_directory(
            self.job_id,
            self.lease_token,
            create=True,
        )
        entries: dict[str, dict] = {}
        for artifact_id, (filename, media_type, content) in _ARTIFACT_SPECS.items():
            artifact_path = self.attempt / filename
            artifact_path.write_bytes(content)
            entries[artifact_id] = {
                "artifact_id": artifact_id,
                "schema_version": 1,
                "artifact_kind": _PUBLIC_CONTRACT_BY_ID[artifact_id][
                    "artifact_kind"
                ],
                "owner_workflow": "technoeconomic",
                "owner_job_id": self.job_id,
                "storage_key": artifact_path.relative_to(self.output).as_posix(),
                "filename": filename,
                "media_type": media_type,
                "sha256": hashlib.sha256(content).hexdigest(),
                "byte_count": len(content),
                "public": True,
                "row_count": 8,
            }
        manifest = {
            "schema_version": 1,
            "csv_format_version": 1,
            "owner_workflow": "technoeconomic",
            "owner_job_id": self.job_id,
            "source_snapshot_sha256": "a" * 64,
            "request_sha256": "c" * 64,
            "submission_provenance_sha256": "d" * 64,
            "sealed_calculation_sha256": "b" * 64,
            "calculation_contract_version": "phase1-v1",
            "sampling_version": "lhs-v1",
            "artifact_count": len(entries),
            "artifacts": entries,
            "tie_outs": {"realization_count": 8, "passed": True},
            "chart_contracts": {"cdf": "cdf-v1"},
        }
        manifest["manifest_sha256"] = _canonical_manifest_sha256(manifest)
        self.job = {
            "id": self.job_id,
            "state": "done",
            "progress": 100,
            "stage": "Done",
            "source_snapshot_sha256": "a" * 64,
            "submission_provenance_sha256": "d" * 64,
            "result_provenance": {"request_sha256": "c" * 64},
            "artifacts": {
                "sealed_calculation": {
                    "schema_version": 1,
                    "artifact_kind": "sealed_technoeconomic_calculation",
                    "storage_key": (
                        ".technoeconomic_attempts/private/secret.npz"
                    ),
                    "sha256": "b" * 64,
                    "byte_count": 100,
                    "row_count": 8,
                    "public": False,
                },
                "exports": manifest,
            },
        }
        self.original_store = state.AGENT_STORE
        state.AGENT_STORE = _FixtureStore(self.job)
        self.client = TestClient(app.app)
        self.addCleanup(self._cleanup)

    def _cleanup(self) -> None:
        self.client.close()
        state.AGENT_STORE = self.original_store
        self.output_patch.stop()
        shutil.rmtree(self.test_root, ignore_errors=True)

    def _refresh_manifest_sha256(self) -> None:
        manifest = self.job["artifacts"]["exports"]
        manifest["manifest_sha256"] = _canonical_manifest_sha256(manifest)

    def test_status_exposes_only_whitelisted_metadata_and_safe_urls(self) -> None:
        response = self.client.get(f"/api/technoeconomic/jobs/{self.job_id}")
        self.assertEqual(200, response.status_code, response.text)
        payload = response.json()
        exports = payload["artifacts"]["exports"]
        self.assertEqual(set(_ARTIFACT_SPECS), set(exports["artifacts"]))
        self.assertEqual(
            f"/api/technoeconomic/jobs/{self.job_id}/exports/csv",
            exports["artifacts"]["csv_bundle"]["url"],
        )
        self.assertEqual(
            (
                f"/api/technoeconomic/jobs/{self.job_id}/"
                "artifacts/convergence_plot"
            ),
            exports["artifacts"]["convergence_plot"]["url"],
        )
        encoded = json.dumps(payload)
        self.assertNotIn("storage_key", encoded)
        self.assertNotIn(str(self.output), encoded)
        self.assertNotIn("secret.npz", encoded)

    def test_completed_downloads_revalidate_and_serve_exact_media_types(self) -> None:
        cases = {
            "exports/csv": ("csv_bundle", "application/zip"),
            "exports/xlsx": ("xlsx_workbook", _XLSX_MEDIA_TYPE),
            "artifacts/cdf_plot": ("cdf_plot", "image/png"),
            "artifacts/sensitivity_plot": ("sensitivity_plot", "image/png"),
            "artifacts/convergence_plot": ("convergence_plot", "image/png"),
        }
        for route, (artifact_id, media_type) in cases.items():
            with self.subTest(route=route):
                response = self.client.get(
                    f"/api/technoeconomic/jobs/{self.job_id}/{route}"
                )
                self.assertEqual(200, response.status_code, response.text)
                self.assertEqual(media_type, response.headers["content-type"])
                self.assertEqual(
                    _ARTIFACT_SPECS[artifact_id][2],
                    response.content,
                )
                self.assertIn(
                    _ARTIFACT_SPECS[artifact_id][0],
                    response.headers["content-disposition"],
                )
                expected_disposition = (
                    "inline" if media_type == "image/png" else "attachment"
                )
                self.assertTrue(
                    response.headers["content-disposition"].startswith(
                        expected_disposition
                    )
                )
                self.assertEqual("nosniff", response.headers["x-content-type-options"])

    def test_missing_incomplete_and_unknown_public_artifact_errors(self) -> None:
        missing = self.client.get(
            "/api/technoeconomic/jobs/tea_missing/exports/csv"
        )
        self.assertEqual(404, missing.status_code)

        self.job["state"] = "running"
        incomplete = self.client.get(
            f"/api/technoeconomic/jobs/{self.job_id}/exports/csv"
        )
        self.assertEqual(409, incomplete.status_code)
        self.job["state"] = "done"

        unknown = self.client.get(
            f"/api/technoeconomic/jobs/{self.job_id}/artifacts/sealed_calculation"
        )
        self.assertEqual(404, unknown.status_code)

    def test_tampered_bytes_manifest_or_storage_identity_fail_closed(self) -> None:
        manifest = self.job["artifacts"]["exports"]
        csv_entry = manifest["artifacts"]["csv_bundle"]
        csv_path = self.attempt / csv_entry["filename"]
        original_bytes = csv_path.read_bytes()

        csv_path.write_bytes(b"tampered")
        response = self.client.get(
            f"/api/technoeconomic/jobs/{self.job_id}/exports/csv"
        )
        self.assertEqual(409, response.status_code, response.text)
        self.assertNotIn(str(self.output), response.text)
        csv_path.write_bytes(original_bytes)

        original_manifest_sha256 = manifest["manifest_sha256"]
        manifest["manifest_sha256"] = "0" * 64
        response = self.client.get(
            f"/api/technoeconomic/jobs/{self.job_id}/exports/csv"
        )
        self.assertEqual(409, response.status_code, response.text)
        manifest["manifest_sha256"] = original_manifest_sha256

        original_storage_key = csv_entry["storage_key"]
        csv_entry["storage_key"] = "../outside.zip"
        self._refresh_manifest_sha256()
        response = self.client.get(
            f"/api/technoeconomic/jobs/{self.job_id}/exports/csv"
        )
        self.assertEqual(409, response.status_code, response.text)
        csv_entry["storage_key"] = original_storage_key
        self._refresh_manifest_sha256()

        csv_entry["public"] = False
        self._refresh_manifest_sha256()
        response = self.client.get(
            f"/api/technoeconomic/jobs/{self.job_id}/exports/csv"
        )
        self.assertEqual(409, response.status_code, response.text)

    def test_job_cleanup_removes_every_published_artifact(self) -> None:
        response = self.client.delete(
            f"/api/technoeconomic/jobs/{self.job_id}"
        )
        self.assertEqual(200, response.status_code, response.text)
        self.assertEqual(len(_ARTIFACT_SPECS), response.json()["artifacts_deleted"])
        self.assertFalse(self.attempt.exists())
        self.assertFalse((self.output / ".technoeconomic_attempts" / self.job_id).exists())


if __name__ == "__main__":
    unittest.main()
