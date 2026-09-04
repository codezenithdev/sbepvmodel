"""Execute one lease-fenced probabilistic technoeconomic job.

The calculation consumes only the immutable TEA request and Annual source
snapshot carried by the claimed record. Scenario-linked attempts additionally
reverify their immutable accepted-evidence bindings before calculation; evidence
never changes kernel inputs. The runner never resolves the live Annual job and
never places TEA state in the legacy in-memory model cache.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import hashlib
import json
import logging
import math
import os
from pathlib import Path
import secrets
import stat
from typing import Any, Callable

import numpy as np

from sbepv import technoeconomic as kernel
from sbepv import technoeconomic_reporting
from sbepv.api import artifacts as artifact_api
from sbepv.api import config, job_store, state
from sbepv.api import technoeconomic as technoeconomic_api
from sbepv.api.artifacts import (
    _delete_technoeconomic_attempt_artifacts,
    _technoeconomic_attempt_directory,
)
from sbepv.store import AgentStoreError, LeaseOwnershipLost


logger = logging.getLogger(__name__)

SEALED_CALCULATION_SCHEMA_VERSION = 1
ROUTINE_RESULT_SCHEMA_VERSION = 1
APPLIED_CAPACITY_ROUTINE_RESULT_SCHEMA_VERSION = 2
COMMERCIAL_SCALING_ROUTINE_RESULT_SCHEMA_VERSION = 3
STANDALONE_COMMERCIAL_ROUTINE_RESULT_SCHEMA_VERSION = 4
PAIRED_COMMERCIAL_ROUTINE_RESULT_SCHEMA_VERSION = 5
LIFECYCLE_ROUTINE_RESULT_SCHEMA_VERSION = 6
RESULT_PROVENANCE_SCHEMA_VERSION = 1
SEALED_CALCULATION_FILENAME = "calculation_payload_v1.npz"
_REQUIRED_EXPORT_ARTIFACT_IDS = frozenset(
    {
        "csv_bundle",
        "xlsx_workbook",
        "cdf_plot",
        "sensitivity_plot",
        "convergence_plot",
    }
)


def _json_safe(value: Any) -> Any:
    """Return finite, ordinary Python data suitable for canonical JSON."""

    if isinstance(value, np.generic):
        return _json_safe(value.item())
    if isinstance(value, np.ndarray):
        raise ValueError("NumPy arrays must be stored in the sealed calculation payload")
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_json_safe(item) for item in value]
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("Routine technoeconomic results must not contain NaN or Infinity")
        return value
    if value is None or isinstance(value, (str, int, bool)):
        return value
    raise ValueError(
        f"Unsupported technoeconomic result value: {value.__class__.__name__}"
    )


def _compact_cdf_points(value: Any) -> Any:
    """Remove point arrays from routine polls while retaining their identity."""

    if isinstance(value, Mapping):
        compacted: dict[str, Any] = {}
        for raw_key, item in value.items():
            key = str(raw_key)
            if key == "cdf" and isinstance(item, Mapping):
                compacted[key] = {
                    "population_count": _json_safe(item.get("population_count")),
                    "point_count": len(item.get("values") or []),
                    "storage": "sealed_calculation_payload",
                }
            else:
                compacted[key] = _compact_cdf_points(item)
        return compacted
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_compact_cdf_points(item) for item in value]
    return _json_safe(value)


def _headline_cdf_display(
    summary: Mapping[str, Any],
    *,
    maximum_points: int = 1200,
) -> dict[str, Any]:
    """Return a deterministic bounded ECDF projection for routine UI polling."""

    cdf = summary.get("cdf")
    if not isinstance(cdf, Mapping):
        raise ValueError("The standalone commercial headline CDF is unavailable")
    values = list(cdf.get("values") or [])
    probabilities = list(cdf.get("cumulative_probability") or [])
    if not values or len(values) != len(probabilities):
        raise ValueError("The standalone commercial headline CDF is invalid")
    count = len(values)
    if count <= maximum_points:
        indexes = np.arange(count, dtype=np.int64)
    else:
        required = {0, count - 1}
        probability_vector = np.asarray(probabilities, dtype=np.float64)
        for quantile in (0.10, 0.50, 0.90):
            index = int(np.searchsorted(probability_vector, quantile, side="left"))
            for neighbor in (index - 1, index, index + 1):
                if 0 <= neighbor < count:
                    required.add(neighbor)
        if len(required) > maximum_points:
            raise ValueError("The standalone commercial CDF display cap is too small")
        selected = set(required)
        remaining = maximum_points - len(required)
        if remaining:
            selected.update(
                np.linspace(0, count - 1, remaining, dtype=np.int64).tolist()
            )
        indexes = np.asarray(sorted(selected), dtype=np.int64)
    full_identity = {
        "values": values,
        "cumulative_count": list(cdf.get("cumulative_count") or []),
        "cumulative_probability": probabilities,
        "population_count": cdf.get("population_count"),
    }
    return {
        "population_count": _json_safe(cdf.get("population_count")),
        "source_point_count": count,
        "display_point_count": int(len(indexes)),
        "values": [_json_safe(values[int(index)]) for index in indexes],
        "cumulative_probability": [
            _json_safe(probabilities[int(index)]) for index in indexes
        ],
        "full_cdf_sha256": hashlib.sha256(
            _canonical_json_text(full_identity).encode("utf-8")
        ).hexdigest(),
        "full_storage": "sealed_calculation_payload",
    }


def _canonical_json_text(value: Any) -> str:
    return json.dumps(
        _json_safe(value),
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def _sha256_file(path: Path) -> str:
    before = path.lstat()
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
        raise ValueError("The technoeconomic artifact is not a regular file")
    digest = hashlib.sha256()
    byte_count = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
            byte_count += len(chunk)
    after = path.lstat()
    if (
        stat.S_ISLNK(after.st_mode)
        or not stat.S_ISREG(after.st_mode)
        or before.st_dev != after.st_dev
        or before.st_ino != after.st_ino
        or before.st_size != after.st_size
        or before.st_mtime_ns != after.st_mtime_ns
        or byte_count != after.st_size
    ):
        raise ValueError("The technoeconomic artifact changed during verification")
    return digest.hexdigest()


def _no_pickle_array(
    raw_values: Any,
    *,
    storage_name: str,
) -> tuple[np.ndarray, np.ndarray | None, str]:
    values = np.asarray(raw_values)
    if values.ndim != 1:
        raise ValueError(f"Sealed calculation array {storage_name!r} must be one-dimensional")
    if values.dtype.hasobject:
        normalized: list[str] = []
        null_mask = np.zeros(len(values), dtype=np.bool_)
        for index, item in enumerate(values.tolist()):
            if item is None:
                normalized.append("")
                null_mask[index] = True
            elif isinstance(item, str):
                normalized.append(item)
            else:
                raise ValueError(
                    f"Sealed calculation array {storage_name!r} contains an "
                    "unsupported object value"
                )
        return np.asarray(normalized, dtype=np.str_), null_mask if null_mask.any() else None, "unicode"
    if values.dtype.kind not in "biufUS":
        raise ValueError(
            f"Sealed calculation array {storage_name!r} has unsupported dtype "
            f"{values.dtype}"
        )
    return values, None, str(values.dtype)


def _sealed_metadata(
    result: kernel.TechnoeconomicResult,
    *,
    request_sha256: str,
    source_snapshot_sha256: str,
    submission_provenance_sha256: str,
) -> dict[str, Any]:
    sampled_columns = {
        input_id: f"SampledInput::{input_id}"
        for input_id in sorted(result.sampled_inputs)
    }
    return {
        "schema_version": SEALED_CALCULATION_SCHEMA_VERSION,
        "request_sha256": request_sha256,
        "source_snapshot_sha256": source_snapshot_sha256,
        "submission_provenance_sha256": submission_provenance_sha256,
        "energy_available": result.energy_available,
        "realization_columns": list(result.realization_table),
        "sampled_input_columns": sampled_columns,
        "common_cost_audit": _json_safe(result.common_cost_audit),
        "summaries": _json_safe(result.summaries),
        "per_weather_year": _json_safe(result.per_weather_year),
        "sensitivity": _json_safe(result.sensitivity),
        "convergence": _json_safe(result.convergence),
        "kernel_provenance": _json_safe(result.provenance),
    }


def _write_sealed_calculation_payload(
    job_id: str,
    lease_token: str,
    result: kernel.TechnoeconomicResult,
    *,
    request_sha256: str,
    source_snapshot_sha256: str,
    submission_provenance_sha256: str,
    publish_check: Callable[[], None],
) -> dict[str, Any]:
    """Write one private attempt payload using only no-pickle NPZ arrays."""

    attempt_directory = _technoeconomic_attempt_directory(
        job_id, lease_token, create=True
    )
    target = attempt_directory / SEALED_CALCULATION_FILENAME
    if target.exists() or target.is_symlink():
        raise ValueError("The sealed calculation target already exists")
    # The lease-specific directory already makes this name unique.  Keep the
    # temporary basename short so Windows workspaces do not cross MAX_PATH.
    temporary = attempt_directory / ".pending.npz"

    arrays: dict[str, np.ndarray] = {}
    column_metadata: list[dict[str, Any]] = []
    row_count: int | None = None
    for index, (column_name, raw_values) in enumerate(result.realization_table.items()):
        storage_name = f"realization_{index:04d}"
        values, null_mask, dtype_name = _no_pickle_array(
            raw_values,
            storage_name=storage_name,
        )
        if row_count is None:
            row_count = len(values)
        elif len(values) != row_count:
            raise ValueError("Sealed realization columns have inconsistent row counts")
        arrays[storage_name] = values
        null_storage_name = None
        if null_mask is not None:
            null_storage_name = f"{storage_name}__is_null"
            arrays[null_storage_name] = null_mask
        column_metadata.append(
            {
                "column_name": str(column_name),
                "storage_name": storage_name,
                "null_storage_name": null_storage_name,
                "dtype": dtype_name,
            }
        )
    if row_count is None or row_count <= 0:
        raise ValueError("The sealed calculation payload has no realization rows")

    metadata = _sealed_metadata(
        result,
        request_sha256=request_sha256,
        source_snapshot_sha256=source_snapshot_sha256,
        submission_provenance_sha256=submission_provenance_sha256,
    )
    metadata["realization_column_storage"] = column_metadata
    metadata_bytes = _canonical_json_text(metadata).encode("utf-8")
    arrays["metadata_json_utf8"] = np.frombuffer(metadata_bytes, dtype=np.uint8)

    published = False
    try:
        with temporary.open("xb") as handle:
            np.savez_compressed(handle, **arrays)
            handle.flush()
            os.fsync(handle.fileno())
        artifact_sha256 = _sha256_file(temporary)
        byte_count = int(temporary.stat().st_size)
        if byte_count <= 0:
            raise ValueError("The sealed calculation payload is empty")
        publish_check()
        temporary.replace(target)
        published = True
        if (
            int(target.stat().st_size) != byte_count
            or not secrets.compare_digest(_sha256_file(target), artifact_sha256)
        ):
            raise ValueError(
                "The sealed calculation payload changed during publication"
            )
    except Exception:
        temporary.unlink(missing_ok=True)
        if published:
            target.unlink(missing_ok=True)
        raise

    storage_key = target.resolve().relative_to(config.OUTPUT_DIR.resolve()).as_posix()
    return {
        "schema_version": SEALED_CALCULATION_SCHEMA_VERSION,
        "artifact_kind": "sealed_technoeconomic_calculation",
        "owner_workflow": "technoeconomic",
        "owner_job_id": job_id,
        "storage_key": storage_key,
        "filename": SEALED_CALCULATION_FILENAME,
        "media_type": "application/x-npz",
        "sha256": artifact_sha256,
        "byte_count": byte_count,
        "row_count": row_count,
        "column_count": len(result.realization_table),
        "array_count": len(arrays),
        "pickle_allowed": False,
        "public": False,
    }


def _public_calculation_identity(artifact: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: _json_safe(artifact[key])
        for key in (
            "schema_version",
            "artifact_kind",
            "media_type",
            "sha256",
            "byte_count",
            "row_count",
            "column_count",
            "pickle_allowed",
            "public",
        )
    }


def _verify_sealed_calculation_artifact(
    job_id: str,
    lease_token: str,
    artifact: Mapping[str, Any],
) -> None:
    """Revalidate the private calculation bytes before terminal completion."""

    if not isinstance(artifact, Mapping):
        raise ValueError("The sealed calculation artifact is not an object")
    if (
        artifact.get("schema_version") != SEALED_CALCULATION_SCHEMA_VERSION
        or artifact.get("artifact_kind") != "sealed_technoeconomic_calculation"
        or artifact.get("owner_workflow") != "technoeconomic"
        or artifact.get("owner_job_id") != job_id
        or artifact.get("filename") != SEALED_CALCULATION_FILENAME
        or artifact.get("media_type") != "application/x-npz"
        or artifact.get("public") is not False
        or artifact.get("pickle_allowed") is not False
    ):
        raise ValueError("The sealed calculation artifact has an invalid identity")

    attempt_directory = _technoeconomic_attempt_directory(
        job_id,
        lease_token,
        create=False,
    ).resolve(strict=True)
    candidate = attempt_directory / SEALED_CALCULATION_FILENAME
    try:
        details = candidate.lstat()
        resolved = candidate.resolve(strict=True)
        output_directory = config.OUTPUT_DIR.resolve(strict=True)
        expected_storage_key = resolved.relative_to(output_directory).as_posix()
    except (FileNotFoundError, OSError, RuntimeError, ValueError) as exc:
        raise ValueError("The sealed calculation artifact is unavailable") from exc
    if (
        stat.S_ISLNK(details.st_mode)
        or not stat.S_ISREG(details.st_mode)
        or resolved.parent != attempt_directory
        or artifact.get("storage_key") != expected_storage_key
    ):
        raise ValueError("The sealed calculation artifact escapes its attempt directory")

    byte_count = artifact.get("byte_count")
    digest = artifact.get("sha256")
    if (
        isinstance(byte_count, bool)
        or not isinstance(byte_count, int)
        or byte_count <= 0
        or details.st_size != byte_count
        or not isinstance(digest, str)
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
        or not secrets.compare_digest(_sha256_file(candidate), digest)
    ):
        raise ValueError("The sealed calculation artifact no longer matches its identity")


def _positive_int(value: Any, *, field: str, allow_zero: bool = False) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"Export manifest {field} must be an integer")
    invalid = value < 0 if allow_zero else value <= 0
    if invalid:
        qualifier = "nonnegative" if allow_zero else "positive"
        raise ValueError(f"Export manifest {field} must be {qualifier}")
    return value


def _verify_export_manifest(
    job_id: str,
    lease_token: str,
    manifest: Mapping[str, Any],
    *,
    request_sha256: str,
    source_snapshot_sha256: str,
    submission_provenance_sha256: str,
    calculation_contract_version: str,
    sampling_version: str,
    sealed_calculation_sha256: str,
) -> None:
    """Fail closed unless every published export matches its manifest identity."""

    if not isinstance(manifest, Mapping):
        raise ValueError("The technoeconomic export manifest is not an object")
    try:
        schema_versions = technoeconomic_reporting.export_contract_versions(
            calculation_contract_version
        )
    except technoeconomic_reporting.TechnoeconomicExportError as exc:
        raise ValueError("The technoeconomic export contract is unsupported") from exc
    if (
        manifest.get("schema_version")
        != schema_versions["manifest"]
        or manifest.get("csv_format_version")
        != schema_versions["csv_format"]
    ):
        raise ValueError("The technoeconomic export manifest has the wrong schema")
    expected_manifest_sha256 = manifest.get("manifest_sha256")
    if (
        not isinstance(expected_manifest_sha256, str)
        or len(expected_manifest_sha256) != 64
        or any(character not in "0123456789abcdef" for character in expected_manifest_sha256)
    ):
        raise ValueError("The technoeconomic export manifest has an invalid SHA-256")
    digest_payload = dict(manifest)
    digest_payload.pop("manifest_sha256", None)
    calculated_manifest_sha256 = hashlib.sha256(
        _canonical_json_text(digest_payload).encode("utf-8")
    ).hexdigest()
    if not secrets.compare_digest(
        calculated_manifest_sha256,
        expected_manifest_sha256,
    ):
        raise ValueError("The technoeconomic export manifest SHA-256 does not match")

    expected_bindings = {
        "owner_workflow": "technoeconomic",
        "owner_job_id": job_id,
        "request_sha256": request_sha256,
        "source_snapshot_sha256": source_snapshot_sha256,
        "submission_provenance_sha256": submission_provenance_sha256,
        "sealed_calculation_sha256": sealed_calculation_sha256,
        "calculation_contract_version": calculation_contract_version,
        "sampling_version": sampling_version,
    }
    for field, expected in expected_bindings.items():
        actual = manifest.get(field)
        matches = actual == expected
        if field.endswith("_sha256") and isinstance(actual, str):
            matches = secrets.compare_digest(actual, expected)
        if not matches:
            raise ValueError(
                f"The technoeconomic export manifest has the wrong {field}"
            )

    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, Mapping):
        raise ValueError("The technoeconomic export manifest has no artifact map")
    artifact_ids = {str(key) for key in artifacts}
    if artifact_ids != _REQUIRED_EXPORT_ARTIFACT_IDS:
        raise ValueError("The technoeconomic export manifest is incomplete")
    if _positive_int(manifest.get("artifact_count"), field="artifact_count") != len(
        artifacts
    ):
        raise ValueError("The technoeconomic export artifact count does not match")

    attempt_directory = _technoeconomic_attempt_directory(
        job_id,
        lease_token,
        create=False,
    )
    output_directory = config.OUTPUT_DIR.resolve()
    seen_filenames: set[str] = set()
    seen_storage_keys: set[str] = set()
    public_contracts = {
        str(contract["artifact_id"]): contract
        for contract in artifact_api.TECHNOECONOMIC_PUBLIC_ARTIFACT_CONTRACT.values()
    }
    for artifact_id in sorted(_REQUIRED_EXPORT_ARTIFACT_IDS):
        entry = artifacts.get(artifact_id)
        if not isinstance(entry, Mapping) or entry.get("artifact_id") != artifact_id:
            raise ValueError(
                f"The technoeconomic export entry {artifact_id!r} has the wrong identity"
            )
        if entry.get("owner_workflow") != "technoeconomic":
            raise ValueError("A technoeconomic export has the wrong workflow owner")
        if entry.get("owner_job_id") != job_id:
            raise ValueError("A technoeconomic export has the wrong job owner")
        if entry.get("public") is not True:
            raise ValueError("A published technoeconomic export is not public")
        expected_schema_version = (
            schema_versions["csv_bundle"]
            if artifact_id == "csv_bundle"
            else schema_versions["xlsx"]
            if artifact_id == "xlsx_workbook"
            else schema_versions["png"]
        )
        if entry.get("schema_version") != expected_schema_version:
            raise ValueError(
                f"The technoeconomic export {artifact_id!r} has the wrong schema"
            )
        public_contract = public_contracts.get(artifact_id)
        if public_contract is None or any(
            entry.get(field) != public_contract.get(field)
            for field in ("artifact_kind", "media_type", "filename")
        ):
            raise ValueError(
                f"The technoeconomic export {artifact_id!r} violates its public contract"
            )

        filename = entry.get("filename")
        if (
            not isinstance(filename, str)
            or not filename
            or len(filename) > 128
            or filename.startswith(".")
            or any(
                character
                not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-"
                for character in filename
            )
            or filename in seen_filenames
        ):
            raise ValueError("A technoeconomic export has an unsafe filename")
        seen_filenames.add(filename)

        storage_key = entry.get("storage_key")
        if (
            not isinstance(storage_key, str)
            or not storage_key
            or "\\" in storage_key
            or storage_key in seen_storage_keys
        ):
            raise ValueError("A technoeconomic export has an invalid storage key")
        seen_storage_keys.add(storage_key)
        try:
            artifact_candidate = config.OUTPUT_DIR / Path(storage_key)
            artifact_stat = artifact_candidate.lstat()
            artifact_path = artifact_candidate.resolve()
        except (FileNotFoundError, OSError, RuntimeError, ValueError) as exc:
            raise ValueError("A technoeconomic export is unavailable") from exc
        if (
            artifact_path.parent != attempt_directory
            or artifact_path.name != filename
            or not artifact_path.is_relative_to(output_directory)
            or not stat.S_ISREG(artifact_stat.st_mode)
            or artifact_candidate.is_symlink()
        ):
            raise ValueError("A technoeconomic export escapes its attempt directory")

        byte_count = _positive_int(
            entry.get("byte_count"),
            field=f"{artifact_id}.byte_count",
        )
        artifact_sha256 = entry.get("sha256")
        if (
            not isinstance(artifact_sha256, str)
            or len(artifact_sha256) != 64
            or any(character not in "0123456789abcdef" for character in artifact_sha256)
            or artifact_stat.st_size != byte_count
            or not secrets.compare_digest(_sha256_file(artifact_path), artifact_sha256)
        ):
            raise ValueError("A technoeconomic export does not match its file identity")

        if artifact_id == "csv_bundle":
            table_count = _positive_int(
                entry.get("table_count"), field="csv_bundle.table_count"
            )
            _positive_int(
                entry.get("row_count"),
                field="csv_bundle.row_count",
                allow_zero=True,
            )
            tables = entry.get("tables")
            if not isinstance(tables, list) or len(tables) != table_count:
                raise ValueError("The CSV table count does not match its manifest")
            table_rows = 0
            table_filenames: set[str] = set()
            for table in tables:
                if not isinstance(table, Mapping):
                    raise ValueError("The CSV table manifest is invalid")
                table_rows += _positive_int(
                    table.get("row_count"),
                    field="csv_bundle.tables.row_count",
                    allow_zero=True,
                )
                _positive_int(
                    table.get("column_count"),
                    field="csv_bundle.tables.column_count",
                )
                table_filename = table.get("filename")
                table_sha256 = table.get("sha256")
                if (
                    not isinstance(table_filename, str)
                    or not table_filename.endswith(".csv")
                    or Path(table_filename).name != table_filename
                    or table_filename in table_filenames
                    or not isinstance(table_sha256, str)
                    or len(table_sha256) != 64
                    or any(
                        character not in "0123456789abcdef"
                        for character in table_sha256
                    )
                ):
                    raise ValueError("A CSV table identity is invalid")
                table_filenames.add(table_filename)
            if table_rows != entry.get("row_count"):
                raise ValueError("The CSV aggregate row count does not match")
        elif artifact_id == "xlsx_workbook":
            sheet_count = _positive_int(
                entry.get("sheet_count"), field="xlsx_workbook.sheet_count"
            )
            _positive_int(
                entry.get("row_count"),
                field="xlsx_workbook.row_count",
                allow_zero=True,
            )
            sheets = entry.get("sheets")
            if not isinstance(sheets, list) or len(sheets) != sheet_count:
                raise ValueError("The workbook sheet count does not match its manifest")
            sheet_rows = 0
            sheet_names: set[str] = set()
            for sheet in sheets:
                if not isinstance(sheet, Mapping):
                    raise ValueError("The workbook sheet manifest is invalid")
                sheet_rows += _positive_int(
                    sheet.get("row_count"),
                    field="xlsx_workbook.sheets.row_count",
                    allow_zero=True,
                )
                _positive_int(
                    sheet.get("column_count"),
                    field="xlsx_workbook.sheets.column_count",
                )
                sheet_name = sheet.get("sheet_name")
                logical_sha256 = sheet.get("logical_sha256")
                if (
                    not isinstance(sheet_name, str)
                    or not sheet_name
                    or len(sheet_name) > 31
                    or sheet_name in sheet_names
                    or sheet.get("logical_hash_version")
                    != schema_versions["xlsx_logical_hash"]
                    or not isinstance(logical_sha256, str)
                    or len(logical_sha256) != 64
                    or any(
                        character not in "0123456789abcdef"
                        for character in logical_sha256
                    )
                ):
                    raise ValueError("A workbook sheet identity is invalid")
                sheet_names.add(sheet_name)
            if sheet_rows != entry.get("row_count"):
                raise ValueError("The workbook aggregate row count does not match")
        else:
            _positive_int(
                entry.get("row_count"),
                field=f"{artifact_id}.row_count",
                allow_zero=True,
            )
            _positive_int(entry.get("width_px"), field=f"{artifact_id}.width_px")
            _positive_int(entry.get("height_px"), field=f"{artifact_id}.height_px")
            if not isinstance(entry.get("chart_contract_id"), str) or not entry[
                "chart_contract_id"
            ].strip():
                raise ValueError("A technoeconomic chart has no contract identity")


def _public_export_manifest(manifest: Mapping[str, Any]) -> dict[str, Any]:
    """Return the immutable manifest without private storage locations."""

    public_manifest = _json_safe(manifest)
    artifacts = public_manifest.get("artifacts")
    if isinstance(artifacts, dict):
        for entry in artifacts.values():
            if isinstance(entry, dict):
                entry.pop("storage_key", None)
    return public_manifest


def _routine_result(
    request: kernel.TechnoeconomicRequest,
    calculation: kernel.TechnoeconomicResult,
    artifact: Mapping[str, Any],
    submission_provenance: Mapping[str, Any],
) -> dict[str, Any]:
    capacity_map = {capacity.system: capacity for capacity in request.capacities}
    applied_capacity_map = {
        capacity.system: capacity for capacity in (request.applied_capacities or ())
    }
    commercial_scaling_contract = (
        request.calculation_contract_version
        == kernel.COMMERCIAL_SCALING_CALCULATION_CONTRACT_VERSION
    )
    standalone_commercial_contract = (
        request.calculation_contract_version
        == kernel.STANDALONE_COMMERCIAL_CALCULATION_CONTRACT_VERSION
    )
    paired_commercial_contract = (
        request.calculation_contract_version
        == kernel.PAIRED_COMMERCIAL_CALCULATION_CONTRACT_VERSION
    )
    lifecycle_contract = (
        request.calculation_contract_version
        == kernel.LIFECYCLE_CALCULATION_CONTRACT_VERSION
    )
    applied_capacity_contract = request.calculation_contract_version in {
        kernel.CALCULATION_CONTRACT_VERSION,
        kernel.COMMERCIAL_SCALING_CALCULATION_CONTRACT_VERSION,
        kernel.STANDALONE_COMMERCIAL_CALCULATION_CONTRACT_VERSION,
        kernel.PAIRED_COMMERCIAL_CALCULATION_CONTRACT_VERSION,
        kernel.LIFECYCLE_CALCULATION_CONTRACT_VERSION,
    }
    if request.basis == "solartac_site":
        transfer_status = "not_applicable"
    elif request.transfer is None:
        transfer_status = "cost_only"
    else:
        transfer_status = request.transfer.mechanism_status
    evidence_receipt = submission_provenance.get("evidence_receipt")
    if not isinstance(evidence_receipt, Mapping):
        evidence_receipt = {}
    commercial_reference = submission_provenance.get(
        "commercial_reference_design"
    )
    if not isinstance(commercial_reference, Mapping):
        commercial_reference = None
    result = {
        "schema_version": (
            LIFECYCLE_ROUTINE_RESULT_SCHEMA_VERSION
            if lifecycle_contract
            else PAIRED_COMMERCIAL_ROUTINE_RESULT_SCHEMA_VERSION
            if paired_commercial_contract
            else STANDALONE_COMMERCIAL_ROUTINE_RESULT_SCHEMA_VERSION
            if standalone_commercial_contract
            else COMMERCIAL_SCALING_ROUTINE_RESULT_SCHEMA_VERSION
            if commercial_scaling_contract
            else (
                APPLIED_CAPACITY_ROUTINE_RESULT_SCHEMA_VERSION
                if applied_capacity_contract
                else ROUTINE_RESULT_SCHEMA_VERSION
            )
        ),
        "calculation_contract_version": request.calculation_contract_version,
        "sampling_version": request.sampling_version,
        "analysis_basis": request.basis,
        "realization_count": request.n,
        "seed": request.seed,
        "project_life_years": request.project_life_years,
        "cost_stack_completeness": request.cost_stack_completeness,
        "energy_available": calculation.energy_available,
        "commercial_transfer_status": transfer_status,
        "commercial_reference_design": _json_safe(commercial_reference),
        "source_snapshot_sha256": _json_safe(
            submission_provenance.get("source_snapshot_sha256")
        ),
        "eligible_weather_years": [row.year for row in request.paired_energy_rows],
        "capacity_basis": (
            "frozen_annual_applied_capacity_w"
            if applied_capacity_contract
            else "frozen_annual_module_dc_stc_wdc"
        ),
        "capacities": {
            system: {
                "module_model": capacity.module_model,
                "installed_wdc": capacity.installed_wdc,
                "physics_version": capacity.physics_version,
                "physics_fingerprint": capacity.physics_fingerprint,
            }
            for system, capacity in sorted(capacity_map.items())
        },
        "input_status": _json_safe(evidence_receipt.get("status")),
        "evidence_class_counts": _json_safe(
            evidence_receipt.get("evidence_class_counts") or {}
        ),
        "common_cost_audit": _json_safe(calculation.common_cost_audit),
        "summaries": _compact_cdf_points(calculation.summaries),
        "per_weather_year": _compact_cdf_points(calculation.per_weather_year),
        "sensitivity": _json_safe(calculation.sensitivity),
        "convergence": _json_safe(calculation.convergence),
        "sealed_calculation": _public_calculation_identity(artifact),
    }
    if applied_capacity_contract:
        if set(applied_capacity_map) != {"solectria", "solaredge"}:
            raise ValueError(
                "The applied-capacity result is missing a system normalization basis"
            )
        result["applied_capacities"] = {
            system: {
                "applied_capacity_w": capacity.applied_capacity_w,
                "rating_basis": capacity.rating_basis,
            }
            for system, capacity in sorted(applied_capacity_map.items())
        }
    if commercial_scaling_contract:
        scaling = request.commercial_scaling
        if scaling is None:
            raise ValueError(
                "The commercial-scaling result is missing its frozen scaling inputs"
            )
        result["commercial_scaling"] = {
            "target_capacity_w": scaling.target_capacity_w,
            "target_rating_basis": scaling.target_rating_basis,
            "marginal_cost_input_id": scaling.marginal_cost_difference.input_id,
            "marginal_cost_timing": scaling.marginal_cost_timing,
            "transfer_method": scaling.transfer_method,
        }
    if standalone_commercial_contract:
        standalone = request.standalone_commercial
        source = applied_capacity_map.get("solaredge")
        if standalone is None or source is None:
            raise ValueError(
                "The standalone-commercial result is missing its frozen inputs"
            )
        headline_metric_id = kernel.COMMERCIAL_STANDALONE_FIELD_LCOE
        headline = calculation.summaries.get(headline_metric_id)
        if not isinstance(headline, Mapping):
            raise ValueError(
                "The standalone-commercial result has no headline LCOE summary"
            )
        percentiles = headline.get("percentiles")
        if not isinstance(percentiles, Mapping) or set(percentiles) != {
            "p10",
            "p50",
            "p90",
        }:
            raise ValueError(
                "The standalone-commercial headline percentiles are invalid"
            )
        capacity_scale_factor = (
            standalone.target_capacity_w / source.applied_capacity_w
        )
        scale_values = calculation.realization_table.get(
            kernel.COMMERCIAL_STANDALONE_FIELD_CAPACITY_SCALE_FACTOR
        )
        if scale_values is None or not np.all(
            np.asarray(scale_values, dtype=np.float64) == capacity_scale_factor
        ):
            raise ValueError(
                "The standalone-commercial capacity-scale realizations do not "
                "match the frozen source/target bridge"
            )
        result["standalone_commercial"] = {
            "technology": "solaredge",
            "target_capacity_w": standalone.target_capacity_w,
            "target_rating_basis": standalone.target_rating_basis,
            "source_applied_capacity_w": source.applied_capacity_w,
            "source_rating_basis": source.rating_basis,
            "capacity_scale_factor": capacity_scale_factor,
            "transfer_method": standalone.transfer_method,
            "constant_dollar_cost_year": request.constant_dollar_cost_year,
            "headline_metric_id": headline_metric_id,
            "unit": "constant_usd_per_kwh_ac",
            "percentiles": _json_safe(percentiles),
            "cdf": _headline_cdf_display(headline),
            "commercial_cost_line_summaries": _json_safe(
                calculation.summaries.get("commercial_cost_line_summaries") or []
            ),
        }
    if paired_commercial_contract:
        paired = request.paired_commercial
        if paired is None or set(applied_capacity_map) != {"solectria", "solaredge"}:
            raise ValueError(
                "The paired-commercial result is missing its frozen inputs"
            )
        system_specs = {system.technology: system for system in paired.systems}
        if set(system_specs) != {"solectria", "solaredge"}:
            raise ValueError(
                "The paired-commercial result must contain Solectria and SolarEdge"
            )
        field_contracts = {
            "solectria": (
                kernel.COMMERCIAL_PAIRED_SOLECTRIA_FIELD_CAPACITY_SCALE_FACTOR,
                kernel.COMMERCIAL_PAIRED_SOLECTRIA_FIELD_LCOE,
            ),
            "solaredge": (
                kernel.COMMERCIAL_STANDALONE_FIELD_CAPACITY_SCALE_FACTOR,
                kernel.COMMERCIAL_STANDALONE_FIELD_LCOE,
            ),
        }
        cost_line_summaries = calculation.summaries.get(
            "paired_commercial_cost_line_summaries"
        ) or []
        if not isinstance(cost_line_summaries, Sequence) or isinstance(
            cost_line_summaries, (str, bytes, bytearray)
        ):
            raise ValueError(
                "The paired-commercial cost-line summaries are invalid"
            )
        systems: dict[str, Any] = {}
        for technology in ("solectria", "solaredge"):
            scale_field, headline_metric_id = field_contracts[technology]
            source = applied_capacity_map[technology]
            headline = calculation.summaries.get(headline_metric_id)
            if not isinstance(headline, Mapping):
                raise ValueError(
                    f"The paired-commercial {technology} result has no headline "
                    "LCOE summary"
                )
            percentiles = headline.get("percentiles")
            if not isinstance(percentiles, Mapping) or set(percentiles) != {
                "p10",
                "p50",
                "p90",
            }:
                raise ValueError(
                    f"The paired-commercial {technology} headline percentiles "
                    "are invalid"
                )
            capacity_scale_factor = (
                paired.target_capacity_w / source.applied_capacity_w
            )
            scale_values = calculation.realization_table.get(scale_field)
            if scale_values is None or not np.all(
                np.asarray(scale_values, dtype=np.float64)
                == capacity_scale_factor
            ):
                raise ValueError(
                    f"The paired-commercial {technology} capacity-scale "
                    "realizations do not match the frozen source/target bridge"
                )
            system_cost_summaries = [
                item
                for item in cost_line_summaries
                if isinstance(item, Mapping)
                and item.get("technology") == technology
            ]
            expected_line_count = len(system_specs[technology].cost_lines)
            if len(system_cost_summaries) != expected_line_count:
                raise ValueError(
                    f"The paired-commercial {technology} cost-line summaries "
                    "are incomplete"
                )
            systems[technology] = {
                "technology": technology,
                "source_applied_capacity_w": source.applied_capacity_w,
                "source_rating_basis": source.rating_basis,
                "capacity_scale_factor": capacity_scale_factor,
                "headline_metric_id": headline_metric_id,
                "unit": "constant_usd_per_kwh_ac",
                "percentiles": _json_safe(percentiles),
                "cdf": _headline_cdf_display(headline),
                "commercial_cost_line_summaries": _json_safe(
                    system_cost_summaries
                ),
            }
        result["paired_commercial"] = {
            "target_capacity_w": paired.target_capacity_w,
            "target_rating_basis": paired.target_rating_basis,
            "transfer_method": paired.transfer_method,
            "constant_dollar_cost_year": request.constant_dollar_cost_year,
            "systems": systems,
        }
        delta_metric_id = kernel.COMMERCIAL_PAIRED_FIELD_LCOE_DELTA
        delta_headline = calculation.summaries.get(delta_metric_id)
        if not isinstance(delta_headline, Mapping):
            raise ValueError(
                "The paired-commercial result has no LCOE-delta summary"
            )
        delta_percentiles = delta_headline.get("percentiles")
        if not isinstance(delta_percentiles, Mapping) or set(
            delta_percentiles
        ) != {"p10", "p50", "p90"}:
            raise ValueError(
                "The paired-commercial LCOE-delta percentiles are invalid"
            )
        result["paired_commercial"]["lcoe_delta_se_minus_sol"] = {
            "headline_metric_id": delta_metric_id,
            "unit": "constant_usd_per_kwh_ac",
            "percentiles": _json_safe(delta_percentiles),
            "cdf": _headline_cdf_display(delta_headline),
        }
    if lifecycle_contract:
        lifecycle = request.paired_lifecycle
        if lifecycle is None:
            raise ValueError("The version-6 result is missing its lifecycle inputs")
        result_version = calculation.provenance.get("result_version")
        if result_version != kernel.LIFECYCLE_RESULT_VERSION:
            raise ValueError("The version-6 calculation has an invalid result identity")
        required_summary_keys = {
            "headline_decision",
            "probability_counts",
            "upgrade_npv",
            "delta_lcoe",
            "lcoo",
            "annual_lifecycle",
            "reliability_summary",
            "representative_event_traces",
            "cost_coverage_audit",
            "warnings",
            "formula_registry",
        }
        missing = sorted(required_summary_keys - set(calculation.summaries))
        if missing:
            raise ValueError(
                f"The version-6 calculation is missing summaries: {missing!r}"
            )
        headline = calculation.summaries["headline_decision"]
        probabilities = calculation.summaries["probability_counts"]
        if not isinstance(headline, Mapping) or not isinstance(probabilities, Mapping):
            raise ValueError("The version-6 decision summaries are invalid")
        reason_codes = list(headline.get("reason_codes") or ())
        lcoo_summary = calculation.summaries["lcoo"]
        if isinstance(lcoo_summary, Mapping) and lcoo_summary.get("status") != "available":
            reason = lcoo_summary.get("reason")
            if isinstance(reason, str) and reason and reason not in reason_codes:
                reason_codes.append(reason)
        result["result_version"] = kernel.LIFECYCLE_RESULT_VERSION
        result["paired_lifecycle"] = {
            "target_capacity_w": lifecycle.target_capacity_w,
            "target_rating_basis": lifecycle.target_rating_basis,
            "source_energy_basis": lifecycle.source_energy_basis,
            "reliability_mode": lifecycle.reliability_mode,
            "constant_dollar_cost_year": request.constant_dollar_cost_year,
            "headline_metric_id": "upgrade_npv",
            "headline_decision": _json_safe(headline),
            "probability_counts": _json_safe(probabilities),
            "upgrade_npv": _compact_cdf_points(
                calculation.summaries["upgrade_npv"]
            ),
            "delta_lcoe": _compact_cdf_points(
                calculation.summaries["delta_lcoe"]
            ),
            "lcoo": _compact_cdf_points(lcoo_summary),
            "reason_codes": _json_safe(reason_codes),
            "annual_lifecycle": _json_safe(
                calculation.summaries["annual_lifecycle"]
            ),
            "reliability_summary": _json_safe(
                calculation.summaries["reliability_summary"]
            ),
            "representative_event_traces": _json_safe(
                calculation.summaries["representative_event_traces"]
            ),
            "cost_coverage_audit": _json_safe(
                calculation.summaries["cost_coverage_audit"]
            ),
            "warnings": _json_safe(calculation.summaries["warnings"]),
            "formula_registry": _json_safe(
                calculation.provenance.get("formula_registry") or {}
            ),
            "formula_catalog_endpoint": "/api/technoeconomic/formulas/v6",
            "admission": _json_safe(
                calculation.provenance.get("admission") or {}
            ),
        }
    return result


def _verify_frozen_inputs(
    *,
    request_payload: Mapping[str, Any],
    source_snapshot: Mapping[str, Any],
    source_snapshot_sha256: str,
    submission_provenance: Mapping[str, Any],
    submission_provenance_sha256: str,
    source_annual_job_id: str,
    source_artifact_storage_key: str,
    source_artifact_sha256: str,
    source_artifact_bytes: int,
) -> tuple[str, dict[str, Any]]:
    calculated_snapshot_sha256 = technoeconomic_api.canonical_json_sha256(
        source_snapshot
    )
    if not secrets.compare_digest(
        calculated_snapshot_sha256, str(source_snapshot_sha256)
    ):
        raise ValueError("The frozen source snapshot does not match its SHA-256")
    calculated_submission_sha256 = technoeconomic_api.canonical_json_sha256(
        submission_provenance
    )
    if not secrets.compare_digest(
        calculated_submission_sha256, str(submission_provenance_sha256)
    ):
        raise ValueError("The frozen submission provenance does not match its SHA-256")
    request_sha256 = technoeconomic_api.canonical_json_sha256(request_payload)
    if not secrets.compare_digest(
        request_sha256, str(submission_provenance.get("request_sha256") or "")
    ):
        raise ValueError("The frozen request does not match submission provenance")
    if not secrets.compare_digest(
        calculated_snapshot_sha256,
        str(submission_provenance.get("source_snapshot_sha256") or ""),
    ):
        raise ValueError(
            "The frozen source snapshot does not match submission provenance"
        )
    if source_snapshot.get("source_annual_job_id") != source_annual_job_id:
        raise ValueError("The frozen source snapshot names a different Annual job")
    if submission_provenance.get("source_annual_job_id") != source_annual_job_id:
        raise ValueError("Submission provenance names a different Annual job")
    artifact = source_snapshot.get("midc_source_artifact")
    if not isinstance(artifact, Mapping):
        raise ValueError("The frozen source snapshot has no immutable MIDC artifact")
    expected_identity = {
        "owner_annual_job_id": source_annual_job_id,
        "storage_key": source_artifact_storage_key,
        "sha256": source_artifact_sha256,
        "byte_count": source_artifact_bytes,
    }
    for key, expected in expected_identity.items():
        if artifact.get(key) != expected:
            raise ValueError(
                f"The frozen MIDC artifact {key} differs from the durable identity"
            )
    verified_artifact = technoeconomic_api.verify_annual_source_artifact(
        artifact,
        annual_job_id=source_annual_job_id,
        expected_sha256=source_artifact_sha256,
        expected_bytes=source_artifact_bytes,
    )
    return request_sha256, verified_artifact


def _verify_decision_scenario_evidence(
    job_id: str,
    request_payload: Mapping[str, Any],
) -> None:
    """Reverify a linked scenario's immutable evidence before kernel execution."""

    context = state.AGENT_STORE.get_decision_scenario_job_context(job_id)
    if context is None:
        return
    scenario_record = context.get("scenario")
    if not isinstance(scenario_record, Mapping):
        raise ValueError("The decision scenario execution binding is invalid")
    request_sha256 = technoeconomic_api.canonical_json_sha256(request_payload)
    if not secrets.compare_digest(
        request_sha256,
        str(scenario_record.get("request_sha256") or ""),
    ):
        raise ValueError("The TEA request no longer matches its confirmed scenario")

    # Function-local imports keep the standalone TEA worker independent unless
    # this exact job carries an immutable decision-scenario link.
    from sbepv.autonomy import evidence as autonomy_evidence
    from sbepv.autonomy import scenarios as autonomy_scenarios

    case_id = str(scenario_record.get("case_id") or "")
    verification = autonomy_scenarios.verify_accepted_evidence_references(
        case_id=case_id,
        request_payload=request_payload,
        evidence_references=scenario_record.get("evidence_receipt_refs") or [],
        receipt_loader=state.AGENT_STORE.get_decision_evidence_receipt,
        evidence_snapshot_loader=lambda verified_case_id, asset_id: (
            autonomy_evidence.verified_evidence_snapshot(
                state.AGENT_STORE,
                verified_case_id,
                asset_id,
            )
        ),
    )
    if not verification.get("valid"):
        raise ValueError(
            "The confirmed decision scenario evidence failed immutable preflight"
        )


def _check_cancelled(job_id: str, *, worker_id: str, lease_token: str) -> None:
    if state.AGENT_STORE.is_technoeconomic_cancel_requested(
        job_id,
        expected_worker_id=worker_id,
        expected_lease_token=lease_token,
    ):
        raise job_store._JobCancelled("Cancellation requested")


def _verify_rebuilt_submission_provenance(
    *,
    request_payload: Mapping[str, Any],
    source_snapshot: Mapping[str, Any],
    source_snapshot_sha256: str,
    request: kernel.TechnoeconomicRequest,
    submission_provenance: Mapping[str, Any],
    submission_provenance_sha256: str,
) -> dict[str, Any]:
    """Rebuild every validation receipt instead of trusting stored receipt JSON."""

    rebuilt = technoeconomic_api.build_technoeconomic_submission_provenance(
        request_payload,
        {
            "source_snapshot": source_snapshot,
            "source_snapshot_sha256": source_snapshot_sha256,
        },
        request,
    )
    rebuilt_sha256 = technoeconomic_api.canonical_json_sha256(rebuilt)
    if (
        not secrets.compare_digest(
            rebuilt_sha256,
            str(submission_provenance_sha256),
        )
        or _canonical_json_text(rebuilt)
        != _canonical_json_text(submission_provenance)
    ):
        raise ValueError(
            "The frozen submission provenance does not match the rebuilt "
            "validation receipts"
        )
    return rebuilt


def _handle_failure(
    job_id: str,
    exc: Exception,
    *,
    worker_id: str,
    lease_token: str,
) -> None:
    if isinstance(exc, LeaseOwnershipLost):
        removed = _delete_technoeconomic_attempt_artifacts(job_id, lease_token)
        logger.warning(
            "Ignoring technoeconomic job %s after lease loss; removed %s "
            "expired attempt artifact(s)",
            job_id,
            removed,
        )
        return
    try:
        cancelled = state.AGENT_STORE.is_technoeconomic_cancel_requested(
            job_id,
            expected_worker_id=worker_id,
            expected_lease_token=lease_token,
        )
    except LeaseOwnershipLost:
        removed = _delete_technoeconomic_attempt_artifacts(job_id, lease_token)
        logger.warning(
            "Ignoring technoeconomic job %s after lease loss; removed %s "
            "expired attempt artifact(s)",
            job_id,
            removed,
        )
        return

    _delete_technoeconomic_attempt_artifacts(job_id, lease_token)
    if isinstance(exc, job_store._JobCancelled) or cancelled:
        try:
            state.AGENT_STORE.update_technoeconomic_job(
                job_id,
                expected_worker_id=worker_id,
                expected_lease_token=lease_token,
                state="cancelled",
                stage="Cancelled",
                error=None,
            )
        except LeaseOwnershipLost:
            logger.warning(
                "Ignored cancellation transition for technoeconomic job %s after "
                "lease loss",
                job_id,
            )
        return

    logger.exception("Technoeconomic job %s failed", job_id)
    try:
        state.AGENT_STORE.update_technoeconomic_job(
            job_id,
            expected_worker_id=worker_id,
            expected_lease_token=lease_token,
            state="error",
            stage="Failed",
            error=(
                "The technoeconomic analysis failed. Review server logs and retry."
            ),
        )
    except LeaseOwnershipLost:
        logger.warning(
            "Ignored failure transition for technoeconomic job %s after lease loss",
            job_id,
        )
    except AgentStoreError:
        logger.exception(
            "Could not persist the failure state for technoeconomic job %s", job_id
        )


def _run_technoeconomic_job(
    job_id: str,
    request_payload: Mapping[str, Any],
    source_snapshot: Mapping[str, Any],
    *,
    source_snapshot_sha256: str,
    submission_provenance: Mapping[str, Any],
    submission_provenance_sha256: str,
    source_annual_job_id: str,
    source_artifact_storage_key: str,
    source_artifact_sha256: str,
    source_artifact_bytes: int,
    worker_id: str,
    lease_token: str,
) -> None:
    """Validate, calculate, seal, and fenced-complete one TEA attempt."""

    def set_progress(progress: int, stage: str) -> None:
        _check_cancelled(job_id, worker_id=worker_id, lease_token=lease_token)
        state.AGENT_STORE.update_technoeconomic_job(
            job_id,
            expected_worker_id=worker_id,
            expected_lease_token=lease_token,
            progress=progress,
            stage=stage,
        )

    try:
        set_progress(3, "Verifying frozen technoeconomic inputs")
        _verify_decision_scenario_evidence(job_id, request_payload)
        request_sha256, verified_source_artifact = _verify_frozen_inputs(
            request_payload=request_payload,
            source_snapshot=source_snapshot,
            source_snapshot_sha256=source_snapshot_sha256,
            submission_provenance=submission_provenance,
            submission_provenance_sha256=submission_provenance_sha256,
            source_annual_job_id=source_annual_job_id,
            source_artifact_storage_key=source_artifact_storage_key,
            source_artifact_sha256=source_artifact_sha256,
            source_artifact_bytes=source_artifact_bytes,
        )
        set_progress(12, "Building the frozen calculation request")
        request = technoeconomic_api.build_technoeconomic_kernel_request(
            request_payload,
            source_snapshot,
        )
        request = kernel.validate_request(request)
        kernel_request_sha256 = technoeconomic_api.canonical_json_sha256(
            kernel.canonical_request_payload(request)
        )
        if not secrets.compare_digest(
            kernel_request_sha256,
            str(
                submission_provenance.get("validated_kernel_request_sha256")
                or ""
            ),
        ):
            raise ValueError(
                "The rebuilt kernel request does not match submission provenance"
            )
        verified_submission_provenance = (
            _verify_rebuilt_submission_provenance(
                request_payload=request_payload,
                source_snapshot=source_snapshot,
                source_snapshot_sha256=source_snapshot_sha256,
                request=request,
                submission_provenance=submission_provenance,
                submission_provenance_sha256=submission_provenance_sha256,
            )
        )
        set_progress(20, "Running probabilistic technoeconomic analysis")

        def kernel_progress(fraction: float, stage: str) -> None:
            bounded = max(0.0, min(1.0, float(fraction)))
            set_progress(20 + int(65 * bounded), stage)

        calculation = kernel.run_technoeconomic(
            request,
            progress_cb=kernel_progress,
            cancel_check=lambda: _check_cancelled(
                job_id,
                worker_id=worker_id,
                lease_token=lease_token,
            ),
        )
        set_progress(88, "Preparing compact technoeconomic summaries")
        set_progress(92, "Sealing the private calculation payload")
        artifact = _write_sealed_calculation_payload(
            job_id,
            lease_token,
            calculation,
            request_sha256=request_sha256,
            source_snapshot_sha256=source_snapshot_sha256,
            submission_provenance_sha256=submission_provenance_sha256,
            publish_check=lambda: _check_cancelled(
                job_id,
                worker_id=worker_id,
                lease_token=lease_token,
            ),
        )
        routine_result = _routine_result(
            request,
            calculation,
            artifact,
            verified_submission_provenance,
        )
        kernel_provenance = _json_safe(calculation.provenance)
        # Reporting reloads the sealed payload so exports are derived from the
        # immutable bytes, not the live kernel object.  Release the large kernel
        # arrays before that reload to avoid holding two realization matrices.
        del calculation
        attempt_directory = _technoeconomic_attempt_directory(
            job_id,
            lease_token,
            create=False,
        )
        sealed_calculation_path = attempt_directory / artifact["filename"]

        def fenced_check() -> None:
            _check_cancelled(
                job_id,
                worker_id=worker_id,
                lease_token=lease_token,
            )

        set_progress(94, "Generating CSV, workbook, and diagnostic plots")
        export_manifest = technoeconomic_reporting.generate_technoeconomic_exports(
            job_id=job_id,
            attempt_directory=attempt_directory,
            sealed_calculation_path=sealed_calculation_path,
            sealed_calculation_artifact=artifact,
            request_payload=request_payload,
            source_snapshot=source_snapshot,
            submission_provenance=verified_submission_provenance,
            routine_result=routine_result,
            cancellation_check=fenced_check,
            publish_check=fenced_check,
        )
        _verify_sealed_calculation_artifact(job_id, lease_token, artifact)
        set_progress(97, "Verifying the immutable export manifest")
        export_verification = {
            "request_sha256": request_sha256,
            "source_snapshot_sha256": source_snapshot_sha256,
            "submission_provenance_sha256": submission_provenance_sha256,
            "calculation_contract_version": request.calculation_contract_version,
            "sampling_version": request.sampling_version,
            "sealed_calculation_sha256": artifact["sha256"],
        }
        _verify_export_manifest(
            job_id,
            lease_token,
            export_manifest,
            **export_verification,
        )
        public_export_manifest = _public_export_manifest(export_manifest)
        routine_result["exports"] = public_export_manifest
        routine_result_sha256 = technoeconomic_api.canonical_json_sha256(
            routine_result
        )
        result_provenance = {
            "schema_version": RESULT_PROVENANCE_SCHEMA_VERSION,
            "request_sha256": request_sha256,
            "source_snapshot_sha256": source_snapshot_sha256,
            "submission_provenance_sha256": submission_provenance_sha256,
            "validated_kernel_request_sha256": kernel_request_sha256,
            "source_annual_job_id": source_annual_job_id,
            "source_artifact": {
                "sha256": verified_source_artifact["sha256"],
                "byte_count": verified_source_artifact["byte_count"],
                "media_type": verified_source_artifact["media_type"],
                "immutable": verified_source_artifact["immutable"],
            },
            "routine_result_sha256": routine_result_sha256,
            "sealed_calculation": _public_calculation_identity(artifact),
            "exports": {
                "schema_version": export_manifest["schema_version"],
                "manifest_sha256": export_manifest["manifest_sha256"],
                "artifact_count": export_manifest["artifact_count"],
            },
            "kernel": kernel_provenance,
        }
        if (
            request.calculation_contract_version
            == kernel.LIFECYCLE_CALCULATION_CONTRACT_VERSION
        ):
            result_provenance.update(
                {
                    "result_version": kernel.LIFECYCLE_RESULT_VERSION,
                    "calculation_contract_version": (
                        kernel.LIFECYCLE_CALCULATION_CONTRACT_VERSION
                    ),
                    "sampling_version": kernel.LIFECYCLE_SAMPLING_VERSION,
                    "formula_registry": _json_safe(
                        kernel_provenance.get("formula_registry") or {}
                    ),
                }
            )
        set_progress(99, "Finalizing technoeconomic results")
        _verify_export_manifest(
            job_id,
            lease_token,
            export_manifest,
            **export_verification,
        )
        _check_cancelled(job_id, worker_id=worker_id, lease_token=lease_token)
        _verify_sealed_calculation_artifact(job_id, lease_token, artifact)
        state.AGENT_STORE.update_technoeconomic_job(
            job_id,
            expected_worker_id=worker_id,
            expected_lease_token=lease_token,
            state="done",
            progress=100,
            stage="Done",
            result=routine_result,
            result_provenance=result_provenance,
            artifacts={
                "sealed_calculation": artifact,
                "exports": export_manifest,
            },
            error=None,
        )
    except Exception as exc:
        _handle_failure(
            job_id,
            exc,
            worker_id=worker_id,
            lease_token=lease_token,
        )


__all__ = [
    "APPLIED_CAPACITY_ROUTINE_RESULT_SCHEMA_VERSION",
    "COMMERCIAL_SCALING_ROUTINE_RESULT_SCHEMA_VERSION",
    "PAIRED_COMMERCIAL_ROUTINE_RESULT_SCHEMA_VERSION",
    "RESULT_PROVENANCE_SCHEMA_VERSION",
    "ROUTINE_RESULT_SCHEMA_VERSION",
    "SEALED_CALCULATION_SCHEMA_VERSION",
    "_run_technoeconomic_job",
]
