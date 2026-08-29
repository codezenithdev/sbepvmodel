"""Secure, content-addressed evidence ingestion and verified retrieval."""

from __future__ import annotations

import csv
from dataclasses import dataclass
import hashlib
import io
import os
from pathlib import Path, PurePosixPath
import re
import stat
import tempfile
import threading
import unicodedata
import zipfile
from typing import Any
from collections.abc import Mapping

from sbepv.api import config
from sbepv.autonomy import lifecycle


_XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_ALLOWED_EXTENSIONS: dict[str, str] = {
    ".pdf": "application/pdf",
    ".xlsx": _XLSX_MEDIA_TYPE,
    ".csv": "text/csv",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}
_MIME_TO_EXTENSIONS: dict[str, frozenset[str]] = {
    media_type: frozenset(
        extension
        for extension, candidate_type in _ALLOWED_EXTENSIONS.items()
        if candidate_type == media_type
    )
    for media_type in frozenset(_ALLOWED_EXTENSIONS.values())
}
_WINDOWS_RESERVED = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{index}" for index in range(1, 10)}
    | {f"lpt{index}" for index in range(1, 10)}
)
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
_FIELD_VALUE_RE = re.compile(
    r"^\s*([A-Za-z][A-Za-z0-9 _./%()\[\]-]{1,100}?)\s*[:=]\s*"
    r"([-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)"
    r"(?:\s+([A-Za-z$%][A-Za-z0-9$%_./·^\-]{0,39}))?\s*$"
)
_HEADER_UNIT_RE = re.compile(r"^\s*(.*?)\s*[\[(]\s*([^\])]{1,30})\s*[\])]\s*$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_STORAGE_KEY_RE = re.compile(
    r"^sha256/[0-9a-f]{2}/[0-9a-f]{64}(?:\.pdf|\.xlsx|\.csv|\.png|\.jpg|\.webp)$"
)
_PDF_ACTIVE_TOKENS = (
    b"/JavaScript",
    b"/JS ",
    b"/Launch",
    b"/EmbeddedFile",
    b"/OpenAction",
    b"/AA ",
    b"/RichMedia",
)
_PDF_DANGEROUS_KEYS = frozenset(
    {
        "/AA",
        "/AF",
        "/EF",
        "/EmbeddedFiles",
        "/JavaScript",
        "/JS",
        "/Launch",
        "/OpenAction",
        "/RichMedia",
        "/XFA",
    }
)
_PDF_DANGEROUS_TYPES = frozenset(
    {
        "/EmbeddedFile",
        "/Filespec",
        "/ObjStm",
        "/RichMedia",
    }
)
_PDF_ACTION_TYPES = frozenset(
    {
        "/GoTo",
        "/GoTo3DView",
        "/GoToE",
        "/GoToR",
        "/Hide",
        "/ImportData",
        "/JavaScript",
        "/Launch",
        "/Movie",
        "/Named",
        "/Rendition",
        "/ResetForm",
        "/SetOCGState",
        "/Sound",
        "/SubmitForm",
        "/Thread",
        "/Trans",
        "/URI",
    }
)
_ARCHIVE_SIGNATURES = (
    b"Rar!\x1a\x07",
    b"7z\xbc\xaf\x27\x1c",
    b"\x1f\x8b",
    b"BZh",
)
_EXECUTABLE_SIGNATURES = (
    b"MZ",
    b"\x7fELF",
    b"\xfe\xed\xfa\xce",
    b"\xce\xfa\xed\xfe",
    b"\xfe\xed\xfa\xcf",
    b"\xcf\xfa\xed\xfe",
)
_OLE_SIGNATURE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_MAX_ARCHIVE_ENTRIES = 5_000
_MAX_ARCHIVE_EXPANDED_BYTES = 100 * 1024 * 1024
_MAX_ARCHIVE_RATIO = 250
_MAX_PDF_PAGES = 500
_MAX_EXTRACTED_TEXT = 2 * 1024 * 1024
_MAX_IMAGE_PIXELS = 50_000_000
_MAX_PDF_OBJECTS = 100_000
_MAX_VERIFIED_SNAPSHOT_BYTES = 10 * 1024 * 1024

# File and SQLite state must move together for each content identity. A fixed
# stripe set avoids an attacker growing an unbounded lock registry; unrelated
# digests can still proceed concurrently and a collision only adds serialization.
_DIGEST_LOCKS = tuple(threading.RLock() for _ in range(64))


class EvidencePolicyError(ValueError):
    """A stable, safe evidence-policy failure suitable for an API response."""

    def __init__(self, code: str, detail: str, *, status_code: int = 400):
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.status_code = status_code


@dataclass(frozen=True)
class ValidatedEvidence:
    media_type: str
    canonical_extension: str
    candidates: tuple[dict[str, Any], ...]
    extraction_status: str
    extraction_metadata: dict[str, Any]


def _fail(code: str, detail: str, *, status_code: int = 400) -> None:
    raise EvidencePolicyError(code, detail, status_code=status_code)


def validate_upload_filename(filename: object) -> tuple[str, str]:
    if not isinstance(filename, str):
        _fail("unsafe_filename", "The upload filename is missing or unsafe.")
    normalized = unicodedata.normalize("NFC", filename).strip()
    if (
        not normalized
        or len(normalized) > 255
        or _CONTROL_RE.search(normalized)
        or "/" in normalized
        or "\\" in normalized
        or ":" in normalized
        or normalized in {".", ".."}
        or normalized.startswith(".")
        or normalized.endswith((".", " "))
        or any(character in normalized for character in '<>"|?*')
    ):
        _fail("unsafe_filename", "The upload filename is missing or unsafe.")
    path = Path(normalized)
    if path.name != normalized or path.stem.casefold() in _WINDOWS_RESERVED:
        _fail("unsafe_filename", "The upload filename is missing or unsafe.")
    extension = path.suffix.casefold()
    if extension not in _ALLOWED_EXTENSIONS:
        _fail(
            "unsupported_file_type",
            "Evidence must be PDF, XLSX, CSV, PNG, JPEG, or WebP.",
        )
    return normalized, extension


def validate_declared_media_type(extension: str, declared_media_type: object) -> str:
    if not isinstance(declared_media_type, str):
        _fail("mime_type_missing", "The upload must include a supported MIME type.")
    canonical = declared_media_type.split(";", 1)[0].strip().casefold()
    expected = _ALLOWED_EXTENSIONS[extension]
    if canonical != expected or extension not in _MIME_TO_EXTENSIONS.get(canonical, ()):
        _fail(
            "mime_type_mismatch",
            "The declared MIME type does not match the file extension.",
        )
    return canonical


def _bounded_candidates(candidates: list[dict[str, Any]]) -> tuple[dict[str, Any], ...]:
    maximum = int(config.DECISION_EVIDENCE_MAX_EXTRACTED_CANDIDATES)
    return tuple(candidates[:maximum])


def _document_metadata_candidate(
    description: str,
    *,
    source_location: Mapping[str, Any],
) -> dict[str, Any]:
    """Return an exact structural fact for human review when fields are absent.

    This fallback deliberately says only what the parser proved about the whole
    document. It is not presented as an extracted project value, but it gives
    every accepted asset the same explicit accept/reject receipt path.
    """

    return {
        "field_name": "Document metadata",
        "value": description[:2_000],
        "unit": None,
        "confidence": 1.0,
        "source_location": {
            "kind": "document_metadata",
            **dict(source_location),
        },
    }


def _digest_lock(sha256: str) -> threading.RLock:
    identity = str(sha256).casefold()
    if not _SHA256_RE.fullmatch(identity):
        _fail(
            "evidence_integrity_failed",
            "Evidence integrity verification failed.",
            status_code=409,
        )
    return _DIGEST_LOCKS[int(identity[:16], 16) % len(_DIGEST_LOCKS)]


def _candidate(
    field_name: object,
    value: object,
    *,
    unit: object = None,
    confidence: float,
    source_location: Mapping[str, Any],
) -> dict[str, Any] | None:
    field = str(field_name or "").strip()
    rendered = str(value or "").strip()
    rendered_unit = str(unit or "").strip() or None
    signed_number = re.fullmatch(r"[-+]?\d+(?:\.\d+)?", rendered.replace(",", ""))
    if (
        not field
        or not rendered
        or rendered.startswith(("=", "@"))
        or (rendered.startswith(("+", "-")) and not signed_number)
    ):
        return None
    return {
        "field_name": field[:300],
        "value": rendered[:2_000],
        "unit": rendered_unit[:100] if rendered_unit else None,
        "confidence": confidence,
        "source_location": dict(source_location),
    }


def _split_header_unit(header: object) -> tuple[str, str | None]:
    text = str(header or "").strip()
    match = _HEADER_UNIT_RE.fullmatch(text)
    if match:
        return match.group(1).strip(), match.group(2).strip()
    return text, None


def _reject_obvious_binary(prefix: bytes) -> None:
    if any(prefix.startswith(signature) for signature in _EXECUTABLE_SIGNATURES):
        _fail("executable_content_rejected", "Executable evidence content is not allowed.")
    if prefix.startswith(_OLE_SIGNATURE):
        _fail("legacy_xls_rejected", "Legacy XLS and OLE content are not allowed.")
    if any(prefix.startswith(signature) for signature in _ARCHIVE_SIGNATURES):
        _fail("archive_content_rejected", "Archive evidence content is not allowed.")
    lowered = prefix.lstrip().lower()
    if lowered.startswith((b"<svg", b"<?xml")) and b"<svg" in lowered[:4_096]:
        _fail("svg_content_rejected", "SVG evidence content is not allowed.")


def _reject_pdf_structure(reader: Any) -> None:
    """Reject parsed active/attached content, including escaped PDF names."""

    from pypdf.generic import ArrayObject, DictionaryObject, IndirectObject

    if getattr(reader, "xref_objStm", None):
        _fail(
            "pdf_object_stream_rejected",
            "PDF object streams are not supported for evidence review.",
        )

    roots: list[Any] = [reader.trailer]
    for generation, entries in getattr(reader, "xref", {}).items():
        if int(generation) == 65535:
            continue
        for object_id in entries:
            if int(object_id) > 0:
                roots.append(IndirectObject(int(object_id), int(generation), reader))

    visited_indirect: set[tuple[int, int]] = set()
    visited_containers: set[int] = set()
    inspected = 0

    def inspect(value: Any) -> None:
        nonlocal inspected
        if isinstance(value, IndirectObject):
            identity = (int(value.idnum), int(value.generation))
            if identity in visited_indirect:
                return
            visited_indirect.add(identity)
            inspected += 1
            if inspected > _MAX_PDF_OBJECTS:
                _fail(
                    "pdf_object_limit",
                    "The PDF object graph exceeds the supported limit.",
                )
            inspect(value.get_object())
            return
        if isinstance(value, DictionaryObject):
            container_id = id(value)
            if container_id in visited_containers:
                return
            visited_containers.add(container_id)
            inspected += 1
            if inspected > _MAX_PDF_OBJECTS:
                _fail(
                    "pdf_object_limit",
                    "The PDF object graph exceeds the supported limit.",
                )
            keys = {str(key) for key in value.keys()}
            dangerous_keys = keys & _PDF_DANGEROUS_KEYS
            if dangerous_keys:
                if dangerous_keys & {"/AF", "/EF", "/EmbeddedFiles"}:
                    _fail(
                        "pdf_attachment_rejected",
                        "PDF attachments and associated files are not allowed.",
                    )
                _fail(
                    "active_pdf_content_rejected",
                    "PDFs containing scripts, launches, attachments, or active actions are not allowed.",
                )
            object_type = str(value.get("/Type") or "")
            subtype = str(value.get("/Subtype") or "")
            if object_type == "/ObjStm":
                _fail(
                    "pdf_object_stream_rejected",
                    "PDF object streams are not supported for evidence review.",
                )
            if object_type in _PDF_DANGEROUS_TYPES or subtype in {
                "/FileAttachment",
                "/RichMedia",
            }:
                _fail(
                    "pdf_attachment_rejected",
                    "PDF attachments and associated files are not allowed.",
                )
            if str(value.get("/S") or "") in _PDF_ACTION_TYPES:
                _fail(
                    "active_pdf_content_rejected",
                    "PDFs containing scripts, launches, attachments, or active actions are not allowed.",
                )
            for child in value.values():
                inspect(child)
            return
        if isinstance(value, (ArrayObject, list, tuple)):
            container_id = id(value)
            if container_id in visited_containers:
                return
            visited_containers.add(container_id)
            inspected += 1
            if inspected > _MAX_PDF_OBJECTS:
                _fail(
                    "pdf_object_limit",
                    "The PDF object graph exceeds the supported limit.",
                )
            for child in value:
                inspect(child)

    for root in roots:
        inspect(root)


def _validate_pdf(path: Path) -> ValidatedEvidence:
    with path.open("rb") as handle:
        prefix = handle.read(8)
        if not prefix.startswith(b"%PDF-"):
            _fail("mime_type_mismatch", "The file is not a valid PDF.")
        handle.seek(0)
        payload = handle.read(config.DECISION_EVIDENCE_MAX_FILE_BYTES + 1)
    final_eof = payload.rfind(b"%%EOF")
    if final_eof < 0:
        _fail("malformed_pdf", "The PDF could not be safely parsed.")
    trailing = payload[final_eof + len(b"%%EOF") :]
    if trailing.strip(b"\x00\t\n\x0c\r "):
        _fail(
            "pdf_appended_content_rejected",
            "PDF evidence may not contain content after the final PDF terminator.",
        )
    if any(token in payload for token in _PDF_ACTIVE_TOKENS):
        _fail(
            "active_pdf_content_rejected",
            "PDFs containing scripts, launches, attachments, or active actions are not allowed.",
        )
    if b"/ObjStm" in payload:
        _fail(
            "pdf_object_stream_rejected",
            "PDF object streams are not supported for evidence review.",
        )
    try:
        from pypdf import PdfReader

        reader = PdfReader(str(path), strict=True)
        if reader.is_encrypted:
            _fail("encrypted_pdf_rejected", "Encrypted PDFs are not supported.")
        _reject_pdf_structure(reader)
        if len(reader.pages) > _MAX_PDF_PAGES:
            _fail("pdf_page_limit", "The PDF exceeds the supported page limit.")
        candidates: list[dict[str, Any]] = []
        extracted_characters = 0
        for page_index, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""
            extracted_characters += len(text)
            if extracted_characters > _MAX_EXTRACTED_TEXT:
                _fail("pdf_text_limit", "The PDF contains too much extractable text.")
            for line_index, line in enumerate(text.splitlines(), start=1):
                match = _FIELD_VALUE_RE.fullmatch(line)
                if not match:
                    continue
                item = _candidate(
                    match.group(1),
                    match.group(2).replace(",", ""),
                    unit=match.group(3),
                    confidence=0.62,
                    source_location={
                        "kind": "pdf_text",
                        "page": page_index,
                        "line": line_index,
                    },
                )
                if item:
                    candidates.append(item)
                if len(candidates) >= config.DECISION_EVIDENCE_MAX_EXTRACTED_CANDIDATES:
                    break
        page_count = len(reader.pages)
        if not candidates:
            candidates.append(
                _document_metadata_candidate(
                    f"PDF document; {page_count} page{'s' if page_count != 1 else ''}",
                    source_location={
                        "format": "PDF",
                        "page_count": page_count,
                    },
                )
            )
    except EvidencePolicyError:
        raise
    except Exception as exc:
        raise EvidencePolicyError(
            "malformed_pdf", "The PDF could not be safely parsed."
        ) from exc
    return ValidatedEvidence(
        media_type="application/pdf",
        canonical_extension=".pdf",
        candidates=_bounded_candidates(candidates),
        extraction_status="complete",
        extraction_metadata={
            "extractor": "pypdf_text_v1",
            "page_count": page_count,
            "candidate_count": min(
                len(candidates), config.DECISION_EVIDENCE_MAX_EXTRACTED_CANDIDATES
            ),
            "untrusted_content": True,
        },
    )


def _validated_xlsx_members(path: Path) -> list[zipfile.ZipInfo]:
    try:
        with zipfile.ZipFile(path) as archive:
            members = archive.infolist()
            if not members or len(members) > _MAX_ARCHIVE_ENTRIES:
                _fail("xlsx_archive_limit", "The XLSX archive structure is not supported.")
            total_expanded = 0
            for member in members:
                name = member.filename.replace("\\", "/")
                pure = PurePosixPath(name)
                if pure.is_absolute() or ".." in pure.parts or "\x00" in name:
                    _fail("xlsx_unsafe_path", "The XLSX contains an unsafe internal path.")
                lowered = name.casefold()
                if (
                    "vbaproject" in lowered
                    or lowered.endswith(".bin")
                    or lowered.startswith("xl/externallinks/")
                    or lowered.startswith("customui/")
                    or lowered.startswith("embeddings/")
                    or "/embeddings/" in lowered
                ):
                    _fail(
                        "xlsx_active_content_rejected",
                        "Macros, external links, and embedded objects are not allowed.",
                    )
                total_expanded += member.file_size
                if total_expanded > _MAX_ARCHIVE_EXPANDED_BYTES:
                    _fail("xlsx_archive_limit", "The XLSX expands beyond the safe limit.")
                compressed = max(member.compress_size, 1)
                if member.file_size > 1_000_000 and member.file_size / compressed > _MAX_ARCHIVE_RATIO:
                    _fail("xlsx_archive_bomb", "The XLSX compression ratio is unsafe.")
            names = {item.filename.replace("\\", "/") for item in members}
            if "[Content_Types].xml" not in names or "xl/workbook.xml" not in names:
                _fail("mime_type_mismatch", "The file is not a valid XLSX workbook.")
            content_types = archive.read("[Content_Types].xml").lower()
            if b"macroenabled" in content_types or b"vba" in content_types:
                _fail("xlsx_macro_rejected", "Macro-enabled workbooks are not allowed.")
            return members
    except EvidencePolicyError:
        raise
    except (OSError, zipfile.BadZipFile, KeyError) as exc:
        raise EvidencePolicyError(
            "malformed_xlsx", "The XLSX workbook could not be safely parsed."
        ) from exc


def _validate_xlsx(path: Path) -> ValidatedEvidence:
    _validated_xlsx_members(path)
    try:
        import openpyxl

        # openpyxl rejects our deliberately extensionless .part staging path;
        # a bounded in-memory stream avoids filename heuristics without ever
        # exposing or renaming the private incoming file.
        workbook = openpyxl.load_workbook(
            filename=io.BytesIO(path.read_bytes()),
            read_only=True,
            data_only=False,
            keep_links=False,
        )
        candidates: list[dict[str, Any]] = []
        sheet_count = 0
        for worksheet in workbook.worksheets:
            sheet_count += 1
            rows = worksheet.iter_rows(max_row=5_000, max_col=200)
            header_cells = next(rows, ())
            headers = [_split_header_unit(cell.value) for cell in header_cells]
            for row_index, cells in enumerate(rows, start=2):
                for column_index, cell in enumerate(cells, start=1):
                    if column_index > len(headers):
                        break
                    header, unit = headers[column_index - 1]
                    if not header or cell.value is None:
                        continue
                    item = _candidate(
                        header,
                        cell.value,
                        unit=unit,
                        confidence=0.82,
                        source_location={
                            "kind": "xlsx_cell",
                            "sheet": str(worksheet.title)[:200],
                            "cell": str(cell.coordinate)[:32],
                        },
                    )
                    if item:
                        candidates.append(item)
                    if len(candidates) >= config.DECISION_EVIDENCE_MAX_EXTRACTED_CANDIDATES:
                        break
                if len(candidates) >= config.DECISION_EVIDENCE_MAX_EXTRACTED_CANDIDATES:
                    break
            if len(candidates) >= config.DECISION_EVIDENCE_MAX_EXTRACTED_CANDIDATES:
                break
        workbook.close()
    except Exception as exc:
        raise EvidencePolicyError(
            "malformed_xlsx", "The XLSX workbook could not be safely parsed."
        ) from exc
    if not candidates:
        candidates.append(
            _document_metadata_candidate(
                f"XLSX workbook; {sheet_count} sheet{'s' if sheet_count != 1 else ''}",
                source_location={
                    "format": "XLSX",
                    "sheet_count": sheet_count,
                },
            )
        )
    return ValidatedEvidence(
        media_type=_XLSX_MEDIA_TYPE,
        canonical_extension=".xlsx",
        candidates=_bounded_candidates(candidates),
        extraction_status="complete",
        extraction_metadata={
            "extractor": "openpyxl_cells_v1",
            "sheet_count": sheet_count,
            "candidate_count": len(candidates),
            "untrusted_content": True,
        },
    )


def _validate_csv(path: Path) -> ValidatedEvidence:
    try:
        payload = path.read_bytes()
        if b"\x00" in payload:
            _fail("binary_csv_rejected", "CSV evidence must contain UTF-8 text.")
        text = payload.decode("utf-8-sig", errors="strict")
        if any(ord(character) < 32 and character not in "\r\n\t" for character in text):
            _fail("binary_csv_rejected", "CSV evidence contains unsafe control bytes.")
        sample = text[:16_384]
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        except csv.Error:
            dialect = csv.excel
        rows = csv.reader(io.StringIO(text, newline=""), dialect=dialect)
        header_row = next(rows, None)
        if not header_row or len(header_row) > 500:
            _fail("malformed_csv", "The CSV is missing a supported header row.")
        headers = [_split_header_unit(item) for item in header_row]
        column_count = len(header_row)
        candidates: list[dict[str, Any]] = []
        row_count = 1
        for row_count, row in enumerate(rows, start=2):
            if row_count > 100_000 or len(row) > 500:
                _fail("csv_shape_limit", "The CSV exceeds the supported row or column limit.")
            for column_index, value in enumerate(row, start=1):
                if column_index > len(headers):
                    break
                header, unit = headers[column_index - 1]
                item = _candidate(
                    header,
                    value,
                    unit=unit,
                    confidence=0.78,
                    source_location={
                        "kind": "csv_cell",
                        "row": row_count,
                        "column": column_index,
                    },
                )
                if item:
                    candidates.append(item)
                if len(candidates) >= config.DECISION_EVIDENCE_MAX_EXTRACTED_CANDIDATES:
                    break
            if len(candidates) >= config.DECISION_EVIDENCE_MAX_EXTRACTED_CANDIDATES:
                break
    except EvidencePolicyError:
        raise
    except (OSError, UnicodeDecodeError, csv.Error) as exc:
        raise EvidencePolicyError(
            "malformed_csv", "The CSV could not be safely parsed as UTF-8 text."
        ) from exc
    if not candidates:
        candidates.append(
            _document_metadata_candidate(
                f"CSV document; {row_count} row{'s' if row_count != 1 else ''}, "
                f"{column_count} column{'s' if column_count != 1 else ''}",
                source_location={
                    "format": "CSV",
                    "row_count": row_count,
                    "column_count": column_count,
                },
            )
        )
    return ValidatedEvidence(
        media_type="text/csv",
        canonical_extension=".csv",
        candidates=_bounded_candidates(candidates),
        extraction_status="complete",
        extraction_metadata={
            "extractor": "csv_cells_v1",
            "row_count": row_count,
            "candidate_count": len(candidates),
            "untrusted_content": True,
        },
    )


def _validate_png_terminal(payload: bytes) -> None:
    if not payload.startswith(b"\x89PNG\r\n\x1a\n"):
        _fail("malformed_image", "The image could not be safely decoded.")
    offset = 8
    saw_iend = False
    while offset < len(payload):
        if offset + 12 > len(payload):
            _fail("malformed_image", "The image could not be safely decoded.")
        data_length = int.from_bytes(payload[offset : offset + 4], "big")
        chunk_type = payload[offset + 4 : offset + 8]
        offset += 12 + data_length
        if offset > len(payload):
            _fail("malformed_image", "The image could not be safely decoded.")
        if chunk_type == b"IEND":
            if data_length != 0:
                _fail("malformed_image", "The image could not be safely decoded.")
            saw_iend = True
            break
    if not saw_iend:
        _fail("malformed_image", "The image could not be safely decoded.")
    if offset != len(payload):
        _fail(
            "image_appended_content_rejected",
            "Image evidence may not contain content after the image terminator.",
        )


def _validate_jpeg_terminal(payload: bytes) -> None:
    if not payload.startswith(b"\xff\xd8"):
        _fail("malformed_image", "The image could not be safely decoded.")
    offset = 2
    scanning = False
    while offset < len(payload):
        if scanning:
            marker_start = payload.find(b"\xff", offset)
            if marker_start < 0:
                break
            offset = marker_start
        elif payload[offset] != 0xFF:
            _fail("malformed_image", "The image could not be safely decoded.")
        while offset < len(payload) and payload[offset] == 0xFF:
            offset += 1
        if offset >= len(payload):
            break
        marker = payload[offset]
        offset += 1
        if scanning and (marker == 0x00 or 0xD0 <= marker <= 0xD7):
            continue
        scanning = False
        if marker == 0xD9:
            if offset != len(payload):
                _fail(
                    "image_appended_content_rejected",
                    "Image evidence may not contain content after the image terminator.",
                )
            return
        if marker in {0x01, *range(0xD0, 0xD8)}:
            continue
        if marker == 0xD8 or offset + 2 > len(payload):
            _fail("malformed_image", "The image could not be safely decoded.")
        segment_length = int.from_bytes(payload[offset : offset + 2], "big")
        if segment_length < 2 or offset + segment_length > len(payload):
            _fail("malformed_image", "The image could not be safely decoded.")
        offset += segment_length
        scanning = marker == 0xDA
    _fail("malformed_image", "The image could not be safely decoded.")


def _validate_webp_terminal(payload: bytes) -> None:
    if len(payload) < 12 or payload[:4] != b"RIFF" or payload[8:12] != b"WEBP":
        _fail("malformed_image", "The image could not be safely decoded.")
    declared_end = int.from_bytes(payload[4:8], "little") + 8
    if declared_end > len(payload):
        _fail("malformed_image", "The image could not be safely decoded.")
    if declared_end != len(payload):
        _fail(
            "image_appended_content_rejected",
            "Image evidence may not contain content after the image terminator.",
        )


def _validate_image(path: Path, extension: str) -> ValidatedEvidence:
    expected_format = {
        ".png": "PNG",
        ".jpg": "JPEG",
        ".jpeg": "JPEG",
        ".webp": "WEBP",
    }[extension]
    try:
        from PIL import Image

        payload = path.read_bytes()
        header_format = (
            "PNG"
            if payload.startswith(b"\x89PNG\r\n\x1a\n")
            else "JPEG"
            if payload.startswith(b"\xff\xd8")
            else "WEBP"
            if len(payload) >= 12
            and payload[:4] == b"RIFF"
            and payload[8:12] == b"WEBP"
            else None
        )
        if header_format is None:
            _fail("malformed_image", "The image could not be safely decoded.")
        if header_format != expected_format:
            _fail("mime_type_mismatch", "The image bytes do not match the upload type.")
        if expected_format == "PNG":
            _validate_png_terminal(payload)
        elif expected_format == "JPEG":
            _validate_jpeg_terminal(payload)
        else:
            _validate_webp_terminal(payload)
        with Image.open(path) as image:
            detected_format = str(image.format or "").upper()
            width, height = image.size
            if detected_format != expected_format:
                _fail("mime_type_mismatch", "The image bytes do not match the upload type.")
            if width <= 0 or height <= 0 or width * height > _MAX_IMAGE_PIXELS:
                _fail("image_pixel_limit", "The image dimensions exceed the safe limit.")
            image.verify()
    except EvidencePolicyError:
        raise
    except Exception as exc:
        raise EvidencePolicyError(
            "malformed_image", "The image could not be safely decoded."
        ) from exc
    media_type = _ALLOWED_EXTENSIONS[extension]
    candidates = (
        _document_metadata_candidate(
            f"{detected_format} image; {width} x {height} pixels",
            source_location={
                "format": detected_format,
                "width": width,
                "height": height,
            },
        ),
    )
    return ValidatedEvidence(
        media_type=media_type,
        canonical_extension=".jpg" if extension == ".jpeg" else extension,
        candidates=candidates,
        extraction_status="complete",
        extraction_metadata={
            "extractor": "pillow_metadata_v1",
            "width": width,
            "height": height,
            "candidate_count": 1,
            "untrusted_content": True,
        },
    )


def validate_evidence_file(path: Path, extension: str) -> ValidatedEvidence:
    with path.open("rb") as handle:
        prefix = handle.read(8_192)
    _reject_obvious_binary(prefix)
    if extension == ".pdf":
        result = _validate_pdf(path)
    elif extension == ".xlsx":
        if not prefix.startswith(b"PK"):
            _fail("mime_type_mismatch", "The file is not a valid XLSX workbook.")
        result = _validate_xlsx(path)
    elif extension == ".csv":
        result = _validate_csv(path)
    else:
        result = _validate_image(path, extension)
    expected_media_type = _ALLOWED_EXTENSIONS[extension]
    if result.media_type != expected_media_type:
        _fail("mime_type_mismatch", "The file content does not match its MIME type.")
    return result


def _storage_path(storage_key: str) -> Path:
    if not _STORAGE_KEY_RE.fullmatch(storage_key):
        _fail("evidence_storage_invalid", "The evidence storage identity is invalid.", status_code=500)
    root = config.DECISION_EVIDENCE_DIR.resolve()
    target = (root / Path(*storage_key.split("/"))).resolve()
    if root not in target.parents:
        _fail("evidence_storage_invalid", "The evidence storage identity is invalid.", status_code=500)
    return target


def _sha256_and_size(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    byte_count = 0
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
            byte_count += len(chunk)
    return digest.hexdigest(), byte_count


async def ingest_evidence_upload(
    agent_store: Any,
    case_id: str,
    upload: Any,
    *,
    evidence_class: str,
    operator_name: str,
    expected_revision: int | None = None,
) -> dict[str, Any]:
    """Stream, validate, persist, and durably register one untrusted upload."""

    temp_path: Path | None = None
    created_blob = False
    digest = hashlib.sha256()
    byte_count = 0
    try:
        lifecycle.evidence_class_requires_rationale(evidence_class)
        filename, extension = validate_upload_filename(
            getattr(upload, "filename", None)
        )
        declared_media_type = validate_declared_media_type(
            extension, getattr(upload, "content_type", None)
        )
        incoming_dir = config.DECISION_EVIDENCE_DIR / ".incoming"
        incoming_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w+b", prefix="upload-", suffix=".part", dir=incoming_dir, delete=False
        ) as temporary:
            temp_path = Path(temporary.name)
            while True:
                chunk = await upload.read(1024 * 1024)
                if not chunk:
                    break
                if not isinstance(chunk, bytes):
                    _fail("malformed_upload", "The upload stream returned invalid content.")
                byte_count += len(chunk)
                if byte_count > int(config.DECISION_EVIDENCE_MAX_FILE_BYTES):
                    _fail("evidence_file_too_large", "Evidence files may not exceed 10 MB.", status_code=413)
                digest.update(chunk)
                temporary.write(chunk)
            if byte_count <= 0:
                _fail("empty_evidence_file", "Empty evidence files are not supported.")
            temporary.flush()
            os.fsync(temporary.fileno())
        validated = validate_evidence_file(temp_path, extension)
        if validated.media_type != declared_media_type:
            _fail("mime_type_mismatch", "The declared MIME type does not match the file content.")
        sha256 = digest.hexdigest()
        storage_key = (
            f"sha256/{sha256[:2]}/{sha256}{validated.canonical_extension}"
        )
        final_path = _storage_path(storage_key)
        with _digest_lock(sha256):
            final_path.parent.mkdir(parents=True, exist_ok=True)
            if final_path.exists():
                if final_path.is_symlink() or not final_path.is_file():
                    _fail("evidence_storage_collision", "The evidence storage target is unsafe.", status_code=500)
                existing_sha, existing_bytes = _sha256_and_size(final_path)
                if existing_sha != sha256 or existing_bytes != byte_count:
                    _fail("evidence_storage_collision", "The evidence storage target failed integrity verification.", status_code=500)
                temp_path.unlink(missing_ok=True)
                temp_path = None
            else:
                os.replace(temp_path, final_path)
                temp_path = None
                created_blob = True
            try:
                return agent_store.create_decision_evidence_asset(
                    case_id,
                    original_filename=filename,
                    display_filename=filename,
                    media_type=validated.media_type,
                    declared_media_type=declared_media_type,
                    sha256=sha256,
                    byte_count=byte_count,
                    storage_key=storage_key,
                    evidence_class=evidence_class,
                    operator_name=operator_name,
                    candidates=validated.candidates,
                    extraction_status=validated.extraction_status,
                    extraction_metadata={
                        **validated.extraction_metadata,
                        "canonical_extension": validated.canonical_extension,
                    },
                    source_metadata={
                        "origin": "operator_upload",
                        "untrusted_content": True,
                    },
                    expected_revision=expected_revision,
                    max_file_bytes=int(config.DECISION_EVIDENCE_MAX_FILE_BYTES),
                    max_files_per_case=int(config.DECISION_EVIDENCE_MAX_FILES_PER_CASE),
                    max_case_bytes=int(config.DECISION_EVIDENCE_MAX_BYTES_PER_CASE),
                )
            except Exception:
                if created_blob:
                    reference_check = getattr(
                        agent_store, "decision_evidence_storage_is_referenced", None
                    )
                    try:
                        referenced = bool(reference_check(storage_key)) if callable(reference_check) else True
                        if not referenced and final_path.is_file() and not final_path.is_symlink():
                            final_path.unlink()
                    except Exception:
                        pass
                raise
    finally:
        try:
            await upload.close()
        except Exception:
            pass
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def _evidence_asset_identity(
    agent_store: Any,
    case_id: str,
    evidence_id: str,
) -> tuple[dict[str, Any], str, Path]:
    asset = agent_store.get_decision_evidence_asset(evidence_id)
    if not asset or str(asset.get("case_id")) != str(case_id) or asset.get("removed_at"):
        _fail("evidence_not_found", "Evidence was not found.", status_code=404)
    sha256 = str(asset.get("sha256") or "").casefold()
    storage_key = str(asset.get("storage_key") or "")
    canonical_extension = str(asset.get("canonical_extension") or "")
    if (
        not _SHA256_RE.fullmatch(sha256)
        or canonical_extension not in _ALLOWED_EXTENSIONS
        or storage_key
        != f"sha256/{sha256[:2]}/{sha256}{canonical_extension}"
    ):
        _fail("evidence_integrity_failed", "Evidence integrity verification failed.", status_code=409)
    return asset, sha256, _storage_path(storage_key)


def _verify_regular_evidence_path(path: Path) -> None:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise EvidencePolicyError(
            "evidence_content_missing", "Evidence content is unavailable.", status_code=410
        ) from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        _fail("evidence_integrity_failed", "Evidence integrity verification failed.", status_code=409)


def verified_evidence_download(
    agent_store: Any,
    case_id: str,
    evidence_id: str,
) -> tuple[Path, dict[str, Any]]:
    """Verify a private blob and return its path for compatibility callers.

    New response paths should use :func:`verified_evidence_snapshot`, whose
    immutable bytes cannot change between verification and transmission.
    """

    asset, sha256, path = _evidence_asset_identity(
        agent_store, case_id, evidence_id
    )
    with _digest_lock(sha256):
        asset, sha256, path = _evidence_asset_identity(
            agent_store, case_id, evidence_id
        )
        _verify_regular_evidence_path(path)
        actual_sha256, byte_count = _sha256_and_size(path)
        if actual_sha256 != sha256 or byte_count != int(asset.get("byte_count") or -1):
            _fail("evidence_integrity_failed", "Evidence integrity verification failed.", status_code=409)
        return path, asset


def verified_evidence_snapshot(
    agent_store: Any,
    case_id: str,
    evidence_id: str,
) -> tuple[bytes, dict[str, Any]]:
    """Return one bounded, hash-verified immutable byte snapshot and its asset."""

    asset, sha256, _path = _evidence_asset_identity(
        agent_store, case_id, evidence_id
    )
    with _digest_lock(sha256):
        asset, sha256, path = _evidence_asset_identity(
            agent_store, case_id, evidence_id
        )
        _verify_regular_evidence_path(path)
        expected_bytes = int(asset.get("byte_count") or -1)
        configured_limit = int(config.DECISION_EVIDENCE_MAX_FILE_BYTES)
        byte_limit = min(configured_limit, _MAX_VERIFIED_SNAPSHOT_BYTES)
        if expected_bytes <= 0 or expected_bytes > byte_limit:
            _fail("evidence_integrity_failed", "Evidence integrity verification failed.", status_code=409)
        with path.open("rb") as handle:
            payload = handle.read(byte_limit + 1)
        if (
            len(payload) != expected_bytes
            or len(payload) > byte_limit
            or hashlib.sha256(payload).hexdigest() != sha256
        ):
            _fail("evidence_integrity_failed", "Evidence integrity verification failed.", status_code=409)
        return bytes(payload), dict(asset)


def tombstone_evidence_asset(
    agent_store: Any,
    case_id: str,
    evidence_id: str,
    *,
    operator_name: str,
    reason: str,
    expected_revision: int | None = None,
) -> dict[str, Any]:
    _asset, sha256, _path = _evidence_asset_identity(
        agent_store, case_id, evidence_id
    )
    with _digest_lock(sha256):
        asset, _sha256, path = _evidence_asset_identity(
            agent_store, case_id, evidence_id
        )
        if any(
            isinstance(candidate.get("receipt"), dict)
            and candidate["receipt"].get("decision") == "accepted"
            for candidate in asset.get("candidates") or ()
        ):
            _fail(
                "evidence_in_use",
                "Accepted evidence cannot be removed while its immutable receipt is referenced.",
                status_code=409,
            )
        removed = agent_store.tombstone_decision_evidence_asset(
            evidence_id,
            operator_name=operator_name,
            reason=reason,
            expected_revision=expected_revision,
        )
        storage_key = str(asset.get("storage_key") or "")
        reference_check = getattr(
            agent_store, "decision_evidence_storage_is_referenced", None
        )
        if callable(reference_check) and not reference_check(
            storage_key, exclude_evidence_asset_id=evidence_id
        ):
            try:
                if path.exists() and not path.is_symlink() and path.is_file():
                    path.unlink()
            except OSError:
                # The durable tombstone is authoritative. A private orphan is safer
                # than rolling back the audit record after a filesystem race.
                pass
        return removed
