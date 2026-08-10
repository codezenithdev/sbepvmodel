"""On-disk persistence for pending calibration reviews.

A review is a short-lived bundle -- a JSON report plus the reviewed CSV -- written
under a private subdirectory of the output root and reclaimed after
``CALIBRATION_REVIEW_TTL``. Writes go through a temp file and an atomic replace so
a crash mid-write cannot leave a half-parsed review behind.
"""

from __future__ import annotations

import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from sbepv.api import config
from sbepv.api.config import CALIBRATION_REVIEW_TTL
from sbepv.api.job_store import _get_job_record
from sbepv.calibration import public_quality_report
from sbepv import reporting
from sbepv.reporting import SourceFingerprintMismatch

logger = logging.getLogger(__name__)


def _calibration_review_path(review_id: str, suffix: str) -> Path:
    candidate = str(review_id).strip().lower()
    if len(candidate) != 32 or any(
        character not in "0123456789abcdef" for character in candidate
    ):
        raise HTTPException(status_code=404, detail="Unknown calibration review.")
    return config.CALIBRATION_REVIEW_DIR / f"{candidate}{suffix}"


_CALIBRATION_REVIEW_SUFFIXES = (
    ".json",
    ".json.tmp",
    ".raw.csv",
    ".reviewed.csv",
)


def _delete_calibration_review_artifacts(
    review_id: str,
    *,
    preserve_reviewed: bool = False,
) -> int:
    """Delete the private files for one validated review identifier."""

    review_root = config.CALIBRATION_REVIEW_DIR.resolve()
    removed = 0
    candidates = {
        _calibration_review_path(review_id, suffix)
        for suffix in _CALIBRATION_REVIEW_SUFFIXES
    }
    candidates.update(config.CALIBRATION_REVIEW_DIR.glob(f"{review_id}.*.json.tmp"))
    candidates.update(
        config.CALIBRATION_REVIEW_DIR.glob(f"{review_id}.*.reviewed.csv")
    )
    for candidate in candidates:
        if preserve_reviewed and candidate.name.endswith(".reviewed.csv"):
            continue
        try:
            resolved = candidate.resolve()
            if resolved.parent != review_root:
                continue
            if candidate.is_file():
                candidate.unlink()
                removed += 1
        except OSError:
            logger.warning(
                "Could not remove expired calibration review artifact %s",
                candidate,
                exc_info=True,
            )
    return removed


def _reviewed_source_is_job_bound(
    record: dict[str, Any],
    *,
    review_id: str | None = None,
) -> bool:
    """Return whether a review snapshot is still bound to its durable job."""

    bound_review_id = str(review_id or record.get("review_id") or "").strip()
    if not bound_review_id:
        return False
    job_id = str(
        record.get("job_id") or f"review-{bound_review_id}"
    ).strip()
    job = _get_job_record(job_id)
    if not job or not job.get("source_path"):
        return False
    quality = (job.get("provenance") or {}).get("data_quality")
    if (
        not isinstance(quality, dict)
        or quality.get("review_id") != bound_review_id
        or quality.get("reviewed_source_sha256") != job.get("source_hash")
    ):
        return False
    cleaned_source = record.get("cleaned_source_path") or job.get("source_path")
    try:
        source_path = Path(str(job["source_path"])).resolve()
        return (
            Path(str(cleaned_source)).resolve() == source_path
            and source_path.parent == config.CALIBRATION_REVIEW_DIR.resolve()
            and source_path.name.startswith(f"{bound_review_id}.")
            and source_path.name.endswith(".reviewed.csv")
        )
    except (OSError, RuntimeError, ValueError):
        return False


def _cleanup_expired_calibration_reviews(
    *, now: datetime | None = None
) -> int:
    """Opportunistically remove expired or stale orphaned private review files."""

    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    else:
        current = current.astimezone(timezone.utc)
    stale_before = current - CALIBRATION_REVIEW_TTL
    removed = 0
    review_root = config.CALIBRATION_REVIEW_DIR
    try:
        records = list(review_root.glob("*.json"))
    except OSError:
        logger.warning(
            "Could not enumerate calibration review records", exc_info=True
        )
        return 0

    for path in records:
        review_id = path.name[: -len(".json")]
        try:
            _calibration_review_path(review_id, ".json")
        except HTTPException:
            continue
        expired = False
        record: dict[str, Any] = {}
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            expires_at = datetime.fromisoformat(str(record["expires_at"]))
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            expired = expires_at.astimezone(timezone.utc) <= current
        except (KeyError, TypeError, ValueError, OSError, json.JSONDecodeError):
            try:
                modified = datetime.fromtimestamp(
                    path.stat().st_mtime, tz=timezone.utc
                )
                expired = modified <= stale_before
            except OSError:
                continue
        if expired:
            removed += _delete_calibration_review_artifacts(
                review_id,
                preserve_reviewed=_reviewed_source_is_job_bound(
                    record,
                    review_id=review_id,
                ),
            )

    # Reviewed CSVs can remain the immutable source for a queued/completed job
    # and its same-input scenarios. Orphans are removed only after confirming
    # that the deterministic review job no longer references them.
    for pattern in ("*.json.tmp", "*.raw.csv", "*.reviewed.csv"):
        try:
            orphan_candidates = list(review_root.glob(pattern))
        except OSError:
            continue
        for path in orphan_candidates:
            review_id = path.name.split(".", 1)[0]
            try:
                record_path = _calibration_review_path(review_id, ".json")
                _calibration_review_path(review_id, path.name[len(review_id) :])
                modified = datetime.fromtimestamp(
                    path.stat().st_mtime, tz=timezone.utc
                )
            except (HTTPException, OSError):
                continue
            if not record_path.is_file() and modified <= stale_before:
                if path.name.endswith(".reviewed.csv") and (
                    _reviewed_source_is_job_bound(
                        {"review_id": review_id},
                        review_id=review_id,
                    )
                ):
                    continue
                try:
                    path.unlink()
                    removed += 1
                except OSError:
                    logger.warning(
                        "Could not remove orphaned calibration review artifact %s",
                        path,
                        exc_info=True,
                    )
    return removed


def _save_calibration_review(record: dict[str, Any]) -> None:
    review_id = str(record["review_id"])
    destination = _calibration_review_path(review_id, ".json")
    temporary = _calibration_review_path(
        review_id,
        f".{uuid.uuid4().hex}.json.tmp",
    )
    try:
        temporary.write_text(
            json.dumps(record, allow_nan=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        os.replace(temporary, destination)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            logger.warning(
                "Could not remove temporary calibration review record %s",
                temporary,
                exc_info=True,
            )


def _load_calibration_review(review_id: str) -> dict[str, Any]:
    path = _calibration_review_path(review_id, ".json")
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Unknown calibration review.")
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
        expires_at = datetime.fromisoformat(str(record["expires_at"]))
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=409,
            detail="The calibration review record is invalid; start a new review.",
        ) from exc
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= datetime.now(timezone.utc):
        _delete_calibration_review_artifacts(
            review_id,
            preserve_reviewed=_reviewed_source_is_job_bound(
                record,
                review_id=review_id,
            ),
        )
        raise HTTPException(
            status_code=410,
            detail="This calibration review expired; retrieve the data again.",
        )
    try:
        source_path = Path(str(record.get("source_path", ""))).resolve()
        review_root = config.CALIBRATION_REVIEW_DIR.resolve()
        source_is_available = (
            review_root in source_path.parents and source_path.is_file()
        )
    except (OSError, RuntimeError, ValueError):
        source_is_available = False
    if not source_is_available:
        raise HTTPException(
            status_code=409,
            detail="The reviewed Bazefield source is unavailable; start a new review.",
        )
    try:
        reporting.verify_source_sha256(source_path, str(record["source_hash"]))
    except (
        KeyError,
        OSError,
        TypeError,
        ValueError,
        SourceFingerprintMismatch,
    ) as exc:
        raise HTTPException(
            status_code=409,
            detail="The reviewed Bazefield source changed; start a new review.",
        ) from exc
    return record


def _quality_context(
    record: dict[str, Any],
    *,
    cleaning: dict[str, Any],
    reviewed_source_hash: str,
    submitted_decisions: dict[str, str],
) -> dict[str, Any]:
    return {
        "review_id": record["review_id"],
        "source_sha256": record["source_hash"],
        "reviewed_source_sha256": reviewed_source_hash,
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
        "submitted_decisions": dict(submitted_decisions),
        "report": public_quality_report(record["report"]),
        "cleaning": cleaning,
    }


def _calibration_review_state(report: dict[str, Any]) -> str:
    status = str((report.get("summary") or {}).get("status") or "").strip()
    if status == "blocked":
        return "blocked"
    if status == "clean":
        return "ready"
    return "decision_required"
