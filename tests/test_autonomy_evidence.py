from __future__ import annotations

import asyncio
import hashlib
import io
import shutil
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
import uuid
import zipfile

from PIL import Image

from sbepv.api import config
from sbepv.autonomy import evidence
from sbepv.store import AgentStore, EvidenceLimitExceeded


class FakeUpload:
    def __init__(self, filename: str, content_type: str, payload: bytes) -> None:
        self.filename = filename
        self.content_type = content_type
        self._stream = io.BytesIO(payload)
        self.closed = False

    async def read(self, size: int = -1) -> bytes:
        return self._stream.read(size)

    async def close(self) -> None:
        self.closed = True
        self._stream.close()


class AutonomyEvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = (
            Path(__file__).resolve().parent
            / f".autonomy-evidence-test-{uuid.uuid4().hex}"
        )
        self.root.mkdir()
        self.addCleanup(shutil.rmtree, self.root, True)
        self.evidence_dir = self.root / "private-evidence"
        self.evidence_dir.mkdir()
        directory_patch = patch.object(
            config, "DECISION_EVIDENCE_DIR", self.evidence_dir
        )
        directory_patch.start()
        self.addCleanup(directory_patch.stop)
        self.store = AgentStore(self.root / "state.sqlite3")

    def _case(self, title: str = "Evidence decision") -> dict:
        return self.store.create_decision_case(
            title=title,
            question="What does the project evidence support?",
            operator_name="Evidence Operator",
        )

    @staticmethod
    def _png_payload(color: tuple[int, int, int] = (12, 34, 56)) -> bytes:
        stream = io.BytesIO()
        with Image.new("RGB", (2, 2), color=color) as image:
            image.save(stream, format="PNG")
        return stream.getvalue()

    @staticmethod
    def _image_payload(image_format: str) -> bytes:
        stream = io.BytesIO()
        with Image.new("RGB", (3, 2), color=(23, 45, 67)) as image:
            image.save(stream, format=image_format)
        return stream.getvalue()

    @staticmethod
    def _blank_pdf_payload(*, extra_catalog: bytes = b"", extra_objects: tuple[bytes, ...] = ()) -> bytes:
        objects = [
            b"<< /Type /Catalog /Pages 2 0 R " + extra_catalog + b" >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 100 100] >>",
            *extra_objects,
        ]
        payload = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets = [0]
        for object_id, body in enumerate(objects, start=1):
            offsets.append(len(payload))
            payload.extend(f"{object_id} 0 obj\n".encode("ascii"))
            payload.extend(body)
            payload.extend(b"\nendobj\n")
        xref_offset = len(payload)
        payload.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
        payload.extend(b"0000000000 65535 f \n")
        for offset in offsets[1:]:
            payload.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
        payload.extend(
            (
                f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
                f"startxref\n{xref_offset}\n%%EOF\n"
            ).encode("ascii")
        )
        return bytes(payload)

    @staticmethod
    def _empty_xlsx_payload() -> bytes:
        import openpyxl

        stream = io.BytesIO()
        workbook = openpyxl.Workbook()
        workbook.active["A1"] = "Header only"
        workbook.save(stream)
        workbook.close()
        return stream.getvalue()

    @staticmethod
    def _zip_payload(members: dict[str, bytes]) -> bytes:
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, payload in members.items():
                archive.writestr(name, payload)
        return stream.getvalue()

    def _ingest(
        self,
        case_id: str,
        *,
        filename: str,
        content_type: str,
        payload: bytes,
        evidence_class: str = "project_actual",
    ) -> tuple[dict, FakeUpload]:
        upload = FakeUpload(filename, content_type, payload)
        asset = asyncio.run(
            evidence.ingest_evidence_upload(
                self.store,
                case_id,
                upload,
                evidence_class=evidence_class,
                operator_name="Evidence Operator",
            )
        )
        return asset, upload

    def _assert_ingest_error(
        self,
        case_id: str,
        *,
        filename: str,
        content_type: str,
        payload: bytes,
        code: str,
    ) -> evidence.EvidencePolicyError:
        upload = FakeUpload(filename, content_type, payload)
        with self.assertRaises(evidence.EvidencePolicyError) as raised:
            asyncio.run(
                evidence.ingest_evidence_upload(
                    self.store,
                    case_id,
                    upload,
                    evidence_class="project_actual",
                    operator_name="Evidence Operator",
                )
            )
        self.assertEqual(code, raised.exception.code)
        self.assertTrue(upload.closed)
        return raised.exception

    def test_valid_csv_registration_candidates_and_verified_download(self) -> None:
        case = self._case()
        payload = (
            b"Initial cost (USD/kWdc),Annual service (USD/year),Instruction\n"
            b"1250,42,=DELETE_ALL_FILES()\n"
        )
        asset, upload = self._ingest(
            case["id"],
            filename="project-costs.csv",
            content_type="text/csv; charset=utf-8",
            payload=payload,
        )

        self.assertTrue(upload.closed)
        self.assertEqual("text/csv", asset["detected_media_type"])
        self.assertEqual(".csv", asset["canonical_extension"])
        self.assertEqual(hashlib.sha256(payload).hexdigest(), asset["sha256"])
        self.assertEqual(2, len(asset["candidates"]))
        self.assertEqual(
            {"Initial cost", "Annual service"},
            {item["field_name"] for item in asset["candidates"]},
        )
        self.assertTrue(
            all(isinstance(item["source_location"], dict) for item in asset["candidates"])
        )
        path, verified = evidence.verified_evidence_download(
            self.store, case["id"], asset["id"]
        )
        self.assertEqual(asset["id"], verified["id"])
        self.assertEqual(payload, path.read_bytes())
        self.assertEqual(self.evidence_dir.resolve(), path.parents[2])
        snapshot, snapshot_asset = evidence.verified_evidence_snapshot(
            self.store, case["id"], asset["id"]
        )
        self.assertEqual(payload, snapshot)
        self.assertIsInstance(snapshot, bytes)
        self.assertEqual(asset["id"], snapshot_asset["id"])

    def test_valid_png_registration_and_verified_download(self) -> None:
        case = self._case()
        payload = self._png_payload()
        asset, upload = self._ingest(
            case["id"],
            filename="inspection.png",
            content_type="image/png",
            payload=payload,
        )

        self.assertTrue(upload.closed)
        self.assertEqual("complete", asset["extraction_status"])
        self.assertEqual(1, len(asset["candidates"]))
        self.assertEqual("Document metadata", asset["candidates"][0]["field_name"])
        self.assertEqual(
            "document_metadata",
            asset["candidates"][0]["source_location"]["kind"],
        )
        self.assertTrue(asset["storage_key"].endswith(f"{asset['sha256']}.png"))
        path, _record = evidence.verified_evidence_download(
            self.store, case["id"], asset["id"]
        )
        self.assertEqual(payload, path.read_bytes())

    def test_every_accepted_file_type_has_a_reviewable_receipt_path(self) -> None:
        uploads = (
            ("blank.pdf", "application/pdf", self._blank_pdf_payload()),
            (
                "headers.xlsx",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                self._empty_xlsx_payload(),
            ),
            ("headers.csv", "text/csv", b"Header only\n"),
            ("inspection.png", "image/png", self._image_payload("PNG")),
            ("inspection.jpg", "image/jpeg", self._image_payload("JPEG")),
            ("inspection.webp", "image/webp", self._image_payload("WEBP")),
        )
        for filename, media_type, payload in uploads:
            with self.subTest(filename=filename):
                case = self._case(filename)
                asset, _upload = self._ingest(
                    case["id"],
                    filename=filename,
                    content_type=media_type,
                    payload=payload,
                )
                self.assertGreaterEqual(len(asset["candidates"]), 1)
                candidate = asset["candidates"][0]
                self.assertEqual("Document metadata", candidate["field_name"])
                self.assertEqual(
                    "document_metadata", candidate["source_location"]["kind"]
                )
                receipt = self.store.record_decision_evidence_review(
                    candidate["id"],
                    decision="accepted",
                    operator_name="Human Reviewer",
                )
                self.assertEqual("accepted", receipt["decision"])
                self.assertEqual(asset["sha256"], receipt["asset_sha256"])

    def test_stream_size_limit_closes_upload_and_removes_partial_file(self) -> None:
        case = self._case()
        upload = FakeUpload("large.csv", "text/csv", b"header\n" + b"1" * 40)
        with patch.object(config, "DECISION_EVIDENCE_MAX_FILE_BYTES", 16):
            with self.assertRaises(evidence.EvidencePolicyError) as raised:
                asyncio.run(
                    evidence.ingest_evidence_upload(
                        self.store,
                        case["id"],
                        upload,
                        evidence_class="project_actual",
                        operator_name="Evidence Operator",
                    )
                )
        self.assertEqual("evidence_file_too_large", raised.exception.code)
        self.assertEqual(413, raised.exception.status_code)
        self.assertTrue(upload.closed)
        self.assertEqual([], list((self.evidence_dir / ".incoming").glob("*.part")))
        self.assertEqual([], self.store.list_decision_evidence_assets(case["id"]))

    def test_count_limit_does_not_leave_an_unreferenced_blob(self) -> None:
        case = self._case()
        first_payload = self._png_payload((1, 2, 3))
        second_payload = self._png_payload((4, 5, 6))
        with patch.object(config, "DECISION_EVIDENCE_MAX_FILES_PER_CASE", 1):
            first, _upload = self._ingest(
                case["id"],
                filename="first.png",
                content_type="image/png",
                payload=first_payload,
            )
            with self.assertRaises(EvidenceLimitExceeded):
                self._ingest(
                    case["id"],
                    filename="second.png",
                    content_type="image/png",
                    payload=second_payload,
                )

        second_hash = hashlib.sha256(second_payload).hexdigest()
        second_key = f"sha256/{second_hash[:2]}/{second_hash}.png"
        self.assertFalse(evidence._storage_path(second_key).exists())
        self.assertTrue(evidence._storage_path(first["storage_key"]).is_file())
        self.assertEqual(1, len(self.store.list_decision_evidence_assets(case["id"])))

    def test_filename_mime_and_storage_path_guards(self) -> None:
        unsafe_names = (
            "../escape.csv",
            r"..\escape.csv",
            r"C:\escape.csv",
            ".hidden.csv",
            "CON.csv",
            "trailing.csv.",
            "bad:name.csv",
            "bad\x00name.csv",
        )
        for filename in unsafe_names:
            with self.subTest(filename=filename):
                with self.assertRaises(evidence.EvidencePolicyError) as raised:
                    evidence.validate_upload_filename(filename)
                self.assertEqual("unsafe_filename", raised.exception.code)

        with self.assertRaises(evidence.EvidencePolicyError) as legacy_extension:
            evidence.validate_upload_filename("legacy.xls")
        self.assertEqual("unsupported_file_type", legacy_extension.exception.code)

        case = self._case()
        self._assert_ingest_error(
            case["id"],
            filename="mismatch.png",
            content_type="text/csv",
            payload=self._png_payload(),
            code="mime_type_mismatch",
        )
        with self.assertRaises(evidence.EvidencePolicyError) as storage_error:
            evidence._storage_path("sha256/../../outside.csv")
        self.assertEqual("evidence_storage_invalid", storage_error.exception.code)
        self.assertFalse((self.root / "outside.csv").exists())

    def test_malformed_legacy_svg_executable_and_archive_content_is_rejected(self) -> None:
        case = self._case()
        cases = (
            (
                "legacy.xlsx",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1legacy",
                "legacy_xls_rejected",
            ),
            (
                "vector.png",
                "image/png",
                b"<?xml version='1.0'?><svg xmlns='http://www.w3.org/2000/svg'/>",
                "svg_content_rejected",
            ),
            (
                "program.pdf",
                "application/pdf",
                b"MZ" + b"\x00" * 30,
                "executable_content_rejected",
            ),
            (
                "archive.csv",
                "text/csv",
                b"Rar!\x1a\x07\x01\x00" + b"\x00" * 20,
                "archive_content_rejected",
            ),
            (
                "not-an-image.png",
                "image/png",
                b"plain UTF-8 text",
                "malformed_image",
            ),
        )
        for filename, media_type, payload, code in cases:
            with self.subTest(filename=filename):
                self._assert_ingest_error(
                    case["id"],
                    filename=filename,
                    content_type=media_type,
                    payload=payload,
                    code=code,
                )
        self.assertEqual([], self.store.list_decision_evidence_assets(case["id"]))

    def test_images_with_appended_polyglot_payloads_are_rejected(self) -> None:
        case = self._case()
        uploads = (
            ("polyglot.png", "image/png", self._image_payload("PNG")),
            ("polyglot.jpg", "image/jpeg", self._image_payload("JPEG")),
            ("polyglot.webp", "image/webp", self._image_payload("WEBP")),
        )
        appended = b"PK\x03\x04untrusted-archive-payload"
        for filename, media_type, payload in uploads:
            with self.subTest(filename=filename):
                self._assert_ingest_error(
                    case["id"],
                    filename=filename,
                    content_type=media_type,
                    payload=payload + appended,
                    code="image_appended_content_rejected",
                )
        self.assertEqual([], self.store.list_decision_evidence_assets(case["id"]))

    def test_pdf_with_appended_polyglot_payload_is_rejected(self) -> None:
        case = self._case()
        self._assert_ingest_error(
            case["id"],
            filename="polyglot.pdf",
            content_type="application/pdf",
            payload=self._blank_pdf_payload() + b"PK\x03\x04untrusted-archive-payload",
            code="pdf_appended_content_rejected",
        )
        self.assertEqual([], self.store.list_decision_evidence_assets(case["id"]))

    def test_pdf_escaped_actions_attachments_and_object_streams_are_rejected(self) -> None:
        case = self._case()
        uploads = (
            (
                "escaped-action.pdf",
                self._blank_pdf_payload(
                    extra_catalog=b"/Open#41ction 4 0 R",
                    extra_objects=(b"<< /S /Java#53cript /JS (ignored) >>",),
                ),
                "active_pdf_content_rejected",
            ),
            (
                "escaped-attachment.pdf",
                self._blank_pdf_payload(
                    extra_catalog=b"/AF [4 0 R]",
                    extra_objects=(b"<< /Type /Filespec /F (payload.bin) >>",),
                ),
                "pdf_attachment_rejected",
            ),
            (
                "escaped-object-stream.pdf",
                self._blank_pdf_payload(
                    extra_objects=(
                        b"<< /Type /Obj#53tm /N 0 /First 0 /Length 0 >>\n"
                        b"stream\n\nendstream",
                    ),
                ),
                "pdf_object_stream_rejected",
            ),
        )
        for filename, payload, code in uploads:
            with self.subTest(filename=filename):
                self._assert_ingest_error(
                    case["id"],
                    filename=filename,
                    content_type="application/pdf",
                    payload=payload,
                    code=code,
                )
        self.assertEqual([], self.store.list_decision_evidence_assets(case["id"]))

    def test_xlsx_macro_active_content_and_zip_traversal_are_rejected(self) -> None:
        case = self._case()
        media_type = (
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        base_members = {
            "[Content_Types].xml": b"<Types/>",
            "xl/workbook.xml": b"<workbook/>",
        }
        traversal = self._zip_payload(
            {**base_members, "../outside.xml": b"should never be extracted"}
        )
        self._assert_ingest_error(
            case["id"],
            filename="traversal.xlsx",
            content_type=media_type,
            payload=traversal,
            code="xlsx_unsafe_path",
        )

        active = self._zip_payload(
            {**base_members, "xl/vbaProject.bin": b"macro"}
        )
        self._assert_ingest_error(
            case["id"],
            filename="macro.xlsx",
            content_type=media_type,
            payload=active,
            code="xlsx_active_content_rejected",
        )

        macro_types = self._zip_payload(
            {
                "[Content_Types].xml": b"<Types>macroEnabled VBA</Types>",
                "xl/workbook.xml": b"<workbook/>",
            }
        )
        self._assert_ingest_error(
            case["id"],
            filename="macro-types.xlsx",
            content_type=media_type,
            payload=macro_types,
            code="xlsx_macro_rejected",
        )
        self.assertFalse((self.root / "outside.xml").exists())

    def test_verified_download_detects_content_tampering_and_missing_bytes(self) -> None:
        case = self._case()
        asset, _upload = self._ingest(
            case["id"],
            filename="tamper.png",
            content_type="image/png",
            payload=self._png_payload(),
        )
        path = evidence._storage_path(asset["storage_key"])
        path.write_bytes(b"tampered")
        with self.assertRaises(evidence.EvidencePolicyError) as tampered:
            evidence.verified_evidence_download(self.store, case["id"], asset["id"])
        self.assertEqual("evidence_integrity_failed", tampered.exception.code)
        self.assertEqual(409, tampered.exception.status_code)

        path.unlink()
        with self.assertRaises(evidence.EvidencePolicyError) as missing:
            evidence.verified_evidence_download(self.store, case["id"], asset["id"])
        self.assertEqual("evidence_content_missing", missing.exception.code)
        self.assertEqual(410, missing.exception.status_code)

    def test_accepted_receipt_blocks_deletion_and_preserves_content(self) -> None:
        case = self._case()
        payload = b"Initial cost (USD/kWdc)\n1250\n"
        asset, _upload = self._ingest(
            case["id"],
            filename="accepted.csv",
            content_type="text/csv",
            payload=payload,
        )
        candidate = asset["candidates"][0]
        self.store.record_decision_evidence_review(
            candidate["id"],
            decision="accepted",
            operator_name="Human Reviewer",
        )
        path = evidence._storage_path(asset["storage_key"])

        with self.assertRaises(evidence.EvidencePolicyError) as in_use:
            evidence.tombstone_evidence_asset(
                self.store,
                case["id"],
                asset["id"],
                operator_name="Human Reviewer",
                reason="Attempted removal",
            )
        self.assertEqual("evidence_in_use", in_use.exception.code)
        self.assertEqual(409, in_use.exception.status_code)
        self.assertIsNone(self.store.get_decision_evidence_asset(asset["id"])["removed_at"])
        self.assertTrue(path.is_file())

    def test_tombstone_removes_only_the_last_unreferenced_private_blob(self) -> None:
        first_case = self._case("First shared evidence case")
        second_case = self._case("Second shared evidence case")
        payload = self._png_payload((90, 80, 70))
        first, _first_upload = self._ingest(
            first_case["id"],
            filename="shared-one.png",
            content_type="image/png",
            payload=payload,
        )
        second, _second_upload = self._ingest(
            second_case["id"],
            filename="shared-two.png",
            content_type="image/png",
            payload=payload,
        )
        self.assertEqual(first["storage_key"], second["storage_key"])
        path = evidence._storage_path(first["storage_key"])

        evidence.tombstone_evidence_asset(
            self.store,
            first_case["id"],
            first["id"],
            operator_name="Evidence Operator",
            reason="Superseded upload",
        )
        self.assertTrue(path.is_file())
        evidence.tombstone_evidence_asset(
            self.store,
            second_case["id"],
            second["id"],
            operator_name="Evidence Operator",
            reason="No longer needed",
        )
        self.assertFalse(path.exists())

    def test_same_digest_ingest_and_deletion_are_serialized(self) -> None:
        first_case = self._case("Concurrent existing evidence")
        second_case = self._case("Concurrent replacement evidence")
        payload = self._png_payload((101, 102, 103))
        first, _first_upload = self._ingest(
            first_case["id"],
            filename="existing.png",
            content_type="image/png",
            payload=payload,
        )
        path = evidence._storage_path(first["storage_key"])
        entered_create = threading.Event()
        release_create = threading.Event()
        deletion_finished = threading.Event()
        errors: list[BaseException] = []
        results: dict[str, dict] = {}
        original_create = self.store.create_decision_evidence_asset

        def blocking_create(*args, **kwargs):
            entered_create.set()
            if not release_create.wait(5):
                raise TimeoutError("test did not release evidence creation")
            return original_create(*args, **kwargs)

        def ingest_worker() -> None:
            try:
                asset, _upload = self._ingest(
                    second_case["id"],
                    filename="replacement.png",
                    content_type="image/png",
                    payload=payload,
                )
                results["ingested"] = asset
            except BaseException as exc:  # pragma: no cover - asserted below
                errors.append(exc)

        def delete_worker() -> None:
            try:
                results["removed"] = evidence.tombstone_evidence_asset(
                    self.store,
                    first_case["id"],
                    first["id"],
                    operator_name="Evidence Operator",
                    reason="Concurrent replacement",
                )
            except BaseException as exc:  # pragma: no cover - asserted below
                errors.append(exc)
            finally:
                deletion_finished.set()

        with patch.object(
            self.store,
            "create_decision_evidence_asset",
            side_effect=blocking_create,
        ):
            ingest_thread = threading.Thread(target=ingest_worker)
            ingest_thread.start()
            self.assertTrue(entered_create.wait(5))
            delete_thread = threading.Thread(target=delete_worker)
            delete_thread.start()
            self.assertFalse(deletion_finished.wait(0.1))
            release_create.set()
            ingest_thread.join(5)
            delete_thread.join(5)

        self.assertFalse(ingest_thread.is_alive())
        self.assertFalse(delete_thread.is_alive())
        self.assertEqual([], errors)
        self.assertIsNotNone(results["removed"]["removed_at"])
        self.assertIsNone(results["ingested"]["removed_at"])
        self.assertTrue(path.is_file())
        snapshot, asset = evidence.verified_evidence_snapshot(
            self.store,
            second_case["id"],
            results["ingested"]["id"],
        )
        self.assertEqual(payload, snapshot)
        self.assertEqual(results["ingested"]["id"], asset["id"])


if __name__ == "__main__":
    unittest.main()
