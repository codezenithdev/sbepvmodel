"""Isolated API for standalone Bazefield data collections."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import logging
import os
from pathlib import Path
import re
import threading
from typing import Any
import uuid

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from starlette.types import Receive, Scope, Send

from sbepv.api import config, timewindows, validation
from sbepv.api.schemas import DataCollectionRequest
from sbepv.ingest import bazefield
from sbepv.ingest import collection as historian_collection


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/data-collections", tags=["data collection"])

_COLLECTION_ID_PATTERN = re.compile(r"^collect_[a-f0-9]{24}$")
_COLLECTION_LOCK = threading.RLock()
_ACTIVE_STATES = frozenset({"queued", "collecting"})
_TERMINAL_STATES = frozenset({"completed", "failed"})
_TEMP_RECORD_PATTERN = re.compile(
    r"^\.(collect_[a-f0-9]{24})\.json\.[a-f0-9]{32}\.tmp$"
)
_TEMP_RECORD_GRACE = timedelta(minutes=5)
_DOWNLOAD_PINS: dict[str, int] = {}


def _collection_dir() -> Path:
    return config.OUTPUT_DIR / ".data_collections"


def _validated_collection_id(collection_id: str) -> str:
    if not _COLLECTION_ID_PATTERN.fullmatch(str(collection_id)):
        raise HTTPException(status_code=404, detail="Unknown data collection id")
    return collection_id


def _record_path(collection_id: str) -> Path:
    return _collection_dir() / f"{_validated_collection_id(collection_id)}.json"


def _output_path(collection_id: str) -> Path:
    return _collection_dir() / f"{_validated_collection_id(collection_id)}.csv"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _save_record(record: dict[str, Any]) -> None:
    directory = _collection_dir()
    directory.mkdir(parents=True, exist_ok=True)
    path = _record_path(str(record["collection_id"]))
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(record, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            logger.warning(
                "Could not remove temporary data collection record %s",
                temporary.name,
            )


def _load_record(collection_id: str) -> dict[str, Any] | None:
    path = _record_path(collection_id)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        logger.error("Could not read data collection %s: %s", collection_id, exc)
        raise HTTPException(
            status_code=500,
            detail="The data collection record could not be read.",
        ) from exc
    if not isinstance(payload, dict) or payload.get("collection_id") != collection_id:
        raise HTTPException(
            status_code=500,
            detail="The data collection record is invalid.",
        )
    return payload


def _update_record(collection_id: str, **changes: Any) -> dict[str, Any]:
    with _COLLECTION_LOCK:
        record = _load_record(collection_id)
        if record is None:
            raise RuntimeError("The data collection record no longer exists.")
        record.update(changes)
        record["updated_at"] = _utc_now()
        _save_record(record)
        return record


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _remove_partial_output(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        logger.warning("Could not remove partial data collection output %s", path.name)


def _request_sha256(request: dict[str, Any]) -> str:
    encoded = json.dumps(
        request,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _record_time(record: dict[str, Any]) -> datetime | None:
    for key in ("updated_at", "created_at"):
        try:
            parsed = datetime.fromisoformat(str(record.get(key) or ""))
        except (TypeError, ValueError):
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    return None


def _stored_records_locked() -> list[dict[str, Any]]:
    directory = _collection_dir()
    if not directory.exists():
        return []
    try:
        paths = sorted(directory.glob("collect_*.json"))
    except OSError as exc:
        logger.warning("Could not inspect stored data collections: %s", exc)
        return []
    records: list[dict[str, Any]] = []
    for path in paths:
        collection_id = path.stem
        if not _COLLECTION_ID_PATTERN.fullmatch(collection_id):
            continue
        try:
            record = _load_record(collection_id)
        except HTTPException:
            continue
        if record is not None:
            records.append(record)
    return records


def _delete_collection_locked(collection_id: str) -> bool:
    if _DOWNLOAD_PINS.get(collection_id, 0):
        return False
    output = _output_path(collection_id)
    record_path = _record_path(collection_id)
    try:
        output.unlink(missing_ok=True)
    except OSError as exc:
        logger.warning("Could not prune data collection %s: %s", collection_id, exc)
        return False
    try:
        record_path.unlink(missing_ok=True)
    except OSError as exc:
        logger.warning(
            "Could not prune data collection record %s: %s", collection_id, exc
        )
        return False
    return True


def _collection_storage_sizes_locked() -> dict[str, int]:
    directory = _collection_dir()
    if not directory.exists():
        return {}
    sizes: dict[str, int] = {}
    try:
        for suffix in ("json", "csv"):
            for path in directory.glob(f"collect_*.{suffix}"):
                collection_id = path.stem
                if not _COLLECTION_ID_PATTERN.fullmatch(collection_id):
                    continue
                try:
                    sizes[collection_id] = (
                        sizes.get(collection_id, 0) + path.stat().st_size
                    )
                except OSError:
                    continue
    except OSError as exc:
        logger.warning("Could not inspect data collection storage: %s", exc)
    return sizes


def _temporary_record_files_locked() -> list[Path]:
    directory = _collection_dir()
    if not directory.exists():
        return []
    try:
        return [
            path
            for path in directory.glob(".*.json.*.tmp")
            if _TEMP_RECORD_PATTERN.fullmatch(path.name)
        ]
    except OSError as exc:
        logger.warning("Could not inspect temporary collection records: %s", exc)
        return []


def _temporary_storage_bytes_locked() -> int:
    total = 0
    for path in _temporary_record_files_locked():
        try:
            total += path.stat().st_size
        except OSError:
            continue
    return total


def _prune_stale_temporary_records_locked(*, cutoff: datetime) -> int:
    removed = 0
    for path in _temporary_record_files_locked():
        try:
            modified = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
            if modified > cutoff:
                continue
            path.unlink(missing_ok=True)
            removed += 1
        except OSError as exc:
            logger.warning(
                "Could not remove temporary collection record %s: %s",
                path.name,
                exc,
            )
    return removed


def _enforce_record_limit_locked(*, reserve: int = 0) -> tuple[bool, int]:
    target = max(0, int(config.DATA_COLLECTION_MAX_RECORDS) - max(0, reserve))
    records = _stored_records_locked()
    if len(records) <= target:
        return True, 0
    candidates = [
        record for record in records if record.get("state") in _TERMINAL_STATES
    ]
    candidates.sort(
        key=lambda record: _record_time(record)
        or datetime.max.replace(tzinfo=timezone.utc)
    )
    removed = 0
    remaining = len(records)
    for record in candidates:
        if remaining <= target:
            break
        if _delete_collection_locked(str(record["collection_id"])):
            remaining -= 1
            removed += 1
    return remaining <= target, removed


def _enforce_storage_quota_locked(
    *, protected_collection_id: str | None = None
) -> tuple[bool, int]:
    limit = max(1, int(config.DATA_COLLECTION_MAX_STORAGE_BYTES))
    sizes = _collection_storage_sizes_locked()
    total = sum(sizes.values()) + _temporary_storage_bytes_locked()
    if total <= limit:
        return True, 0

    records = {
        str(record["collection_id"]): record
        for record in _stored_records_locked()
    }
    candidates = [
        record
        for collection_id, record in records.items()
        if collection_id != protected_collection_id
        and collection_id in sizes
        and record.get("state") in _TERMINAL_STATES
    ]
    candidates.sort(
        key=lambda record: _record_time(record)
        or datetime.max.replace(tzinfo=timezone.utc)
    )
    removed = 0
    for record in candidates:
        if total <= limit:
            break
        collection_id = str(record["collection_id"])
        size = sizes.get(collection_id, 0)
        if _delete_collection_locked(collection_id):
            total -= size
            removed += 1
    return total <= limit, removed


def prune_data_collections(*, now: datetime | None = None) -> int:
    """Remove expired/orphaned artifacts and enforce the collection-only quota."""

    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    cutoff = current.astimezone(timezone.utc) - config.DATA_COLLECTION_RETENTION
    removed = 0
    with _COLLECTION_LOCK:
        removed += _prune_stale_temporary_records_locked(
            cutoff=current.astimezone(timezone.utc) - _TEMP_RECORD_GRACE
        )
        records = _stored_records_locked()
        record_ids = {str(record["collection_id"]) for record in records}
        for record in records:
            record_time = _record_time(record)
            if (
                record.get("state") in _TERMINAL_STATES
                and record_time is not None
                and record_time <= cutoff
                and _delete_collection_locked(str(record["collection_id"]))
            ):
                removed += 1

        for collection_id in set(_collection_storage_sizes_locked()).difference(
            record_ids
        ):
            if _delete_collection_locked(collection_id):
                removed += 1

        _within_record_limit, record_removed = _enforce_record_limit_locked()
        removed += record_removed
        _within_quota, quota_removed = _enforce_storage_quota_locked()
        removed += quota_removed
    if removed:
        logger.info("Pruned %d standalone data collection(s)", removed)
    return removed


def reconcile_interrupted_collections() -> int:
    """Fail active records left behind by a stopped API process."""

    reconciled = 0
    with _COLLECTION_LOCK:
        for record in _stored_records_locked():
            if record.get("state") not in _ACTIVE_STATES:
                continue
            collection_id = str(record["collection_id"])
            _remove_partial_output(_output_path(collection_id))
            record.update(
                {
                    "state": "failed",
                    "progress": 100,
                    "stage": "Collection interrupted",
                    "updated_at": _utc_now(),
                    "result": None,
                    "error": {
                        "code": "collection_interrupted",
                        "message": (
                            "The data collection was interrupted by a service "
                            "restart. Submit it again."
                        ),
                    },
                }
            )
            _save_record(record)
            reconciled += 1
    if reconciled:
        logger.warning(
            "Marked %d interrupted standalone data collection(s) failed",
            reconciled,
        )
    return reconciled


def _pin_download_locked(collection_id: str) -> None:
    _DOWNLOAD_PINS[collection_id] = _DOWNLOAD_PINS.get(collection_id, 0) + 1


def _release_download_pin(collection_id: str) -> None:
    with _COLLECTION_LOCK:
        remaining = _DOWNLOAD_PINS.get(collection_id, 0) - 1
        if remaining > 0:
            _DOWNLOAD_PINS[collection_id] = remaining
        else:
            _DOWNLOAD_PINS.pop(collection_id, None)


class _PinnedFileResponse(FileResponse):
    """Release a collection pin on every ASGI response exit path."""

    def __init__(self, *args: Any, collection_id: str, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._collection_id = collection_id

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            _release_download_pin(self._collection_id)


def _public_record(record: dict[str, Any]) -> dict[str, Any]:
    public = {
        "collection_id": record["collection_id"],
        "state": record["state"],
        "progress": record["progress"],
        "stage": record["stage"],
        "created_at": record["created_at"],
        "updated_at": record["updated_at"],
        "request": deepcopy(record["request"]),
    }
    error = record.get("error")
    if isinstance(error, dict):
        public["error"] = deepcopy(error)
    result = record.get("result")
    if isinstance(result, dict):
        public_result = deepcopy(result)
        if record.get("state") == "completed":
            public_result["download_url"] = (
                f"/api/data-collections/{record['collection_id']}/download"
            )
        public["result"] = public_result
    return public


def _validated_request(
    req: DataCollectionRequest,
) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        from_iso = timewindows._iso(req.from_date, req.from_time)
        to_iso = timewindows._iso(req.to_date, req.to_time)
        start = datetime.fromisoformat(from_iso).replace(tzinfo=timezone.utc)
        end = datetime.fromisoformat(to_iso).replace(tzinfo=timezone.utc)
    except (TypeError, ValueError) as exc:
        detail = (
            str(exc)
            if str(exc).startswith("The selected local time")
            else "Collection dates and times must use YYYY-MM-DD and HH:MM."
        )
        raise HTTPException(status_code=422, detail=detail) from exc
    if start >= end:
        raise HTTPException(
            status_code=422,
            detail="Collection start date/time must be before end date/time.",
        )
    interval_seconds = (
        int(req.interval_value) * config.UNIT_SECONDS[req.interval_unit]
    )
    validation._validate_requested_window(
        start=start,
        end=end,
        interval_seconds=interval_seconds,
        max_range=config.DATA_COLLECTION_MAX_RANGE,
        max_rows=config.DATA_COLLECTION_MAX_ROWS,
        label="Data collections",
    )
    request = req.model_dump()
    request.update(
        {
            "from_utc": from_iso + "Z",
            "to_utc": to_iso + "Z",
            "timezone": str(config.LOCAL_TZ),
            "end_exclusive": True,
        }
    )
    internal = {
        "from_iso": from_iso,
        "to_iso": to_iso,
        "interval_seconds": interval_seconds,
        "data_groups": list(req.data_groups),
    }
    return request, internal


def _download_filename(record: dict[str, Any]) -> str:
    request = record["request"]
    suffix = str(record["collection_id"]).removeprefix("collect_")[-8:]
    return (
        f"sbe-collected-data-{request['from_date']}-to-"
        f"{request['to_date']}-{suffix}.csv"
    )


def _run_collection(collection_id: str) -> None:
    output = _output_path(collection_id)
    try:
        record = _update_record(
            collection_id,
            state="collecting",
            progress=15,
            stage="Requesting selected data from Bazefield",
        )
        internal = record["internal_request"]
        result = historian_collection.collect_historian_data(
            from_time=internal["from_iso"],
            to_time=internal["to_iso"],
            interval_seconds=internal["interval_seconds"],
            data_groups=internal["data_groups"],
            output_csv=output,
        )
        with _COLLECTION_LOCK:
            within_quota, removed = _enforce_storage_quota_locked(
                protected_collection_id=collection_id
            )
        if removed:
            logger.info(
                "Pruned %d older data collection(s) before publishing %s",
                removed,
                collection_id,
            )
        if not within_quota:
            _remove_partial_output(output)
            _update_record(
                collection_id,
                state="failed",
                progress=100,
                stage="Collection storage limit reached",
                result=None,
                error={
                    "code": "collection_storage_limit",
                    "message": (
                        "The collected CSV exceeded the storage reserved for "
                        "standalone data collections. Try a shorter window."
                    ),
                },
            )
            return
        _update_record(
            collection_id,
            state="completed",
            progress=100,
            stage="Collection complete",
            result={
                **result,
                "filename": _download_filename(record),
                "sha256": _sha256_file(output),
            },
            error=None,
        )
    except bazefield.BazefieldError as exc:
        _remove_partial_output(output)
        logger.warning(
            "Bazefield retrieval failed for standalone collection %s: %s",
            collection_id,
            exc,
        )
        _update_record(
            collection_id,
            state="failed",
            progress=100,
            stage="Collection failed",
            error={
                "code": "bazefield_error",
                "message": (
                    "Bazefield could not complete the data request. Check the "
                    "historian connection and try again."
                ),
            },
        )
    except Exception:
        _remove_partial_output(output)
        logger.exception("Standalone data collection %s failed", collection_id)
        try:
            _update_record(
                collection_id,
                state="failed",
                progress=100,
                stage="Collection failed",
                error={
                    "code": "collection_error",
                    "message": "The data collection could not be completed. Try again.",
                },
            )
        except Exception:
            logger.exception(
                "Could not persist failure for data collection %s", collection_id
            )


@router.post("", status_code=202)
def create_data_collection(
    req: DataCollectionRequest,
    background_tasks: BackgroundTasks,
) -> JSONResponse:
    request, internal = _validated_request(req)
    request_digest = _request_sha256(request)
    collection_id = f"collect_{uuid.uuid4().hex[:24]}"
    now = _utc_now()
    record = {
        "collection_id": collection_id,
        "state": "queued",
        "progress": 0,
        "stage": "Collection queued",
        "created_at": now,
        "updated_at": now,
        "request": request,
        "request_sha256": request_digest,
        "internal_request": internal,
        "result": None,
        "error": None,
    }
    prune_data_collections()
    try:
        with _COLLECTION_LOCK:
            stored_records = _stored_records_locked()
            duplicate = next(
                (
                    stored_record
                    for stored_record in stored_records
                    if stored_record.get("state") in _ACTIVE_STATES
                    and (
                        stored_record.get("request_sha256") == request_digest
                        or stored_record.get("request") == request
                    )
                ),
                None,
            )
            if duplicate is not None:
                return JSONResponse(_public_record(duplicate), status_code=202)
            active_count = sum(
                stored_record.get("state") in _ACTIVE_STATES
                for stored_record in stored_records
            )
            if active_count >= config.DATA_COLLECTION_MAX_ACTIVE:
                raise HTTPException(
                    status_code=429,
                    detail=(
                        "The standalone data collection queue is full. Wait for an "
                        "active collection to finish and try again."
                    ),
                    headers={"Retry-After": "15"},
                )
            within_quota, _removed = _enforce_storage_quota_locked()
            if not within_quota:
                raise HTTPException(
                    status_code=507,
                    detail=(
                        "The storage reserved for standalone data collections is "
                        "currently full."
                    ),
                )
            _save_record(record)
            within_quota, _removed = _enforce_storage_quota_locked(
                protected_collection_id=collection_id
            )
            if not within_quota:
                _delete_collection_locked(collection_id)
                raise HTTPException(
                    status_code=507,
                    detail=(
                        "The storage reserved for standalone data collections is "
                        "currently full."
                    ),
                )
            within_record_limit, _record_removed = _enforce_record_limit_locked()
            if not within_record_limit:
                _delete_collection_locked(collection_id)
                raise HTTPException(
                    status_code=507,
                    detail=(
                        "The retained standalone data collection limit is "
                        "currently full."
                    ),
                )
    except OSError as exc:
        raise HTTPException(
            status_code=500,
            detail="The data collection could not be queued.",
        ) from exc
    background_tasks.add_task(_run_collection, collection_id)
    return JSONResponse(_public_record(record), status_code=202)


@router.get("/{collection_id}")
def get_data_collection(collection_id: str) -> JSONResponse:
    with _COLLECTION_LOCK:
        record = _load_record(collection_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Unknown data collection id")
    return JSONResponse(
        _public_record(record),
        headers={"Cache-Control": "private, no-store"},
    )


@router.get("/{collection_id}/download", response_class=FileResponse)
def download_data_collection(collection_id: str) -> FileResponse:
    with _COLLECTION_LOCK:
        record = _load_record(collection_id)
        if record is None:
            raise HTTPException(status_code=404, detail="Unknown data collection id")
        if record.get("state") != "completed":
            raise HTTPException(
                status_code=409,
                detail="The data collection is not available for download.",
            )
        result = record.get("result") or {}
        expected_sha256 = str(result.get("sha256") or "")
        path = _output_path(collection_id)
        try:
            resolved = path.resolve(strict=True)
            root = _collection_dir().resolve(strict=True)
        except OSError as exc:
            raise HTTPException(
                status_code=409,
                detail="The collected data file is unavailable.",
            ) from exc
        if root not in resolved.parents or not resolved.is_file():
            raise HTTPException(
                status_code=409,
                detail="The collected data file is unavailable.",
            )
        try:
            actual_sha256 = _sha256_file(resolved)
        except OSError as exc:
            raise HTTPException(
                status_code=409,
                detail="The collected data file could not be verified.",
            ) from exc
        if not expected_sha256 or not hmac.compare_digest(
            actual_sha256, expected_sha256
        ):
            raise HTTPException(
                status_code=409,
                detail="The collected data file failed integrity verification.",
            )
        _pin_download_locked(collection_id)
        filename = str(result.get("filename") or _download_filename(record))
    try:
        return _PinnedFileResponse(
            str(resolved),
            collection_id=collection_id,
            media_type="text/csv",
            filename=filename,
            headers={
                "Cache-Control": "private, no-store",
                "ETag": f'"{actual_sha256}"',
                "X-Content-Type-Options": "nosniff",
            },
        )
    except Exception:
        _release_download_pin(collection_id)
        raise
