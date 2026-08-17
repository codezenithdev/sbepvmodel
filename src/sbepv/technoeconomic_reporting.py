"""Deterministic Phase-4 exports for probabilistic technoeconomic results.

The worker calls :func:`generate_technoeconomic_exports` only after it has sealed
the Phase-3 calculation payload.  This module treats that no-pickle NPZ as the
authoritative realization table, re-verifies its durable identity, streams the
complete CSV/XLSX tables, renders static diagnostics on the non-GUI backend, and
returns an integrity manifest suitable for the terminal job record.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from datetime import datetime
import csv
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import shutil
import stat
import struct
from typing import Any
import zipfile

import matplotlib

matplotlib.use("Agg")

import numpy as np
import openpyxl
from openpyxl.cell import WriteOnlyCell
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

from sbepv import technoeconomic as technoeconomic_kernel
from sbepv.api import config
from sbepv.api import artifacts as api_artifacts
from sbepv.api import technoeconomic as technoeconomic_api
from sbepv.api import serializers


EXPORT_MANIFEST_SCHEMA_VERSION = "technoeconomic-exports-manifest-v1"
CSV_FORMAT_VERSION = "technoeconomic-csv-v1"
CSV_BUNDLE_SCHEMA_VERSION = "technoeconomic-csv-bundle-v1"
XLSX_SCHEMA_VERSION = "technoeconomic-xlsx-v1"
PNG_SCHEMA_VERSION = "technoeconomic-plot-v1"
XLSX_LOGICAL_HASH_VERSION = "technoeconomic-xlsx-logical-row-v1"

APPLIED_EXPORT_MANIFEST_SCHEMA_VERSION = "technoeconomic-exports-manifest-v2"
APPLIED_CSV_FORMAT_VERSION = "technoeconomic-csv-v2"
APPLIED_CSV_BUNDLE_SCHEMA_VERSION = "technoeconomic-csv-bundle-v2"
APPLIED_XLSX_SCHEMA_VERSION = "technoeconomic-xlsx-v2"

CSV_BUNDLE_FILENAME = "technoeconomic-results-csv-v1.zip"
XLSX_FILENAME = "technoeconomic-results-v1.xlsx"
CDF_PLOT_FILENAME = "technoeconomic-cdf-v1.png"
SENSITIVITY_PLOT_FILENAME = "technoeconomic-sensitivity-v1.png"
CONVERGENCE_PLOT_FILENAME = "technoeconomic-convergence-v1.png"


def export_contract_versions(calculation_contract_version: str) -> dict[str, str]:
    """Return the export schema family pinned to one calculation contract."""

    if calculation_contract_version == technoeconomic_kernel.LEGACY_CALCULATION_CONTRACT_VERSION:
        return {
            "manifest": EXPORT_MANIFEST_SCHEMA_VERSION,
            "csv_format": CSV_FORMAT_VERSION,
            "csv_bundle": CSV_BUNDLE_SCHEMA_VERSION,
            "csv_bundle_manifest_filename": "csv-bundle-manifest-v1.json",
            "xlsx": XLSX_SCHEMA_VERSION,
            "png": PNG_SCHEMA_VERSION,
            "xlsx_logical_hash": XLSX_LOGICAL_HASH_VERSION,
        }
    if calculation_contract_version == technoeconomic_kernel.CALCULATION_CONTRACT_VERSION:
        return {
            "manifest": APPLIED_EXPORT_MANIFEST_SCHEMA_VERSION,
            "csv_format": APPLIED_CSV_FORMAT_VERSION,
            "csv_bundle": APPLIED_CSV_BUNDLE_SCHEMA_VERSION,
            "csv_bundle_manifest_filename": "csv-bundle-manifest-v2.json",
            "xlsx": APPLIED_XLSX_SCHEMA_VERSION,
            # The PNG rendering contract and logical-row hash algorithm are
            # unchanged.  The v2 manifest/calculation binding and XLSX schema
            # carry the applied-capacity semantics without mis-versioning either
            # byte-format algorithm.
            "png": PNG_SCHEMA_VERSION,
            "xlsx_logical_hash": XLSX_LOGICAL_HASH_VERSION,
        }
    raise TechnoeconomicExportError(
        f"Unsupported calculation contract for export: {calculation_contract_version!r}"
    )

_SAFE_FILENAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)
_CANCEL_INTERVAL = 1024

_BLUE = "#32679D"
_BLUE_LIGHT = "#B9CEE2"
_GOLD = "#C4932D"
_INK = "#26323D"
_GRID = "#D8DEE5"


CHART_CONTRACTS: dict[str, dict[str, Any]] = {
    "cdf_v1": {
        "question": "What is the empirical distribution of each reportable output?",
        "family": "distribution",
        "variant": "right_continuous_empirical_cdf_small_multiples",
        "fields": ["metric_id", "value", "cumulative_probability"],
        "population": "finite metric-specific realization population",
        "denominator": "shown separately in every panel subtitle",
        "palette_policy": "single-root preferred",
        "palette": [_BLUE, _INK, _GRID],
        "non_color_cues": ["direct metric titles", "shared probability scale"],
        "render_point_cap_per_metric": 1200,
        "render_point_selection": "even-index grid plus endpoints and P5/P50/P95 neighbors",
        "filename": CDF_PLOT_FILENAME,
    },
    "sensitivity_v1": {
        "question": "Which entered predictors contribute most to each rank model?",
        "family": "comparison_and_ranking",
        "variant": "horizontal_incremental_r_squared_small_multiples",
        "fields": ["response_id", "predictor_id", "incremental_r_squared"],
        "population": "finite response-specific sensitivity population",
        "denominator": "sample count shown in each panel subtitle",
        "palette_policy": "hard two-root cap",
        "palette": [_BLUE, _GOLD, _INK, _GRID],
        "non_color_cues": ["signed beta glyph", "direct predictor labels"],
        "display_top_n_per_response": 15,
        "display_order": "incremental R-squared descending; entry order and stable ID ties",
        "filename": SENSITIVITY_PLOT_FILENAME,
    },
    "convergence_v1": {
        "question": "How do cumulative percentile estimates change with sample size?",
        "family": "uncertainty_and_benchmark",
        "variant": "p50_checkpoint_small_multiples_with_p5_p95_band",
        "fields": ["realization_count", "p5", "p50", "p95"],
        "population": "deterministic cumulative LHS prefixes",
        "denominator": "checkpoint realization count on the horizontal axis",
        "palette_policy": "single-root preferred",
        "palette": [_BLUE, _BLUE_LIGHT, _INK, _GRID],
        "non_color_cues": ["median line", "open percentile band"],
        "filename": CONVERGENCE_PLOT_FILENAME,
    },
}


class TechnoeconomicExportError(ValueError):
    """A sealed calculation or generated export failed validation."""


class _SealedCalculation:
    def __init__(
        self,
        *,
        metadata: Mapping[str, Any],
        column_names: Sequence[str],
        columns: Sequence[np.ndarray],
        row_count: int,
    ) -> None:
        self.metadata = dict(metadata)
        self.column_names = tuple(column_names)
        self.columns = tuple(columns)
        self.row_count = row_count
        self.by_name = dict(zip(self.column_names, self.columns))

    def rows(self) -> Iterator[tuple[Any, ...]]:
        for row_index in range(self.row_count):
            yield tuple(_numpy_scalar(column[row_index]) for column in self.columns)


class _Table:
    def __init__(
        self,
        filename: str,
        sheet_name: str,
        columns: Sequence[str],
        rows_factory: Callable[[], Iterable[Sequence[Any]]],
    ) -> None:
        self.filename = filename
        self.sheet_name = sheet_name
        self.columns = tuple(columns)
        self.rows_factory = rows_factory


def _canonical_json_text(value: Any) -> str:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError, OverflowError) as exc:
        raise TechnoeconomicExportError(
            "Export metadata is not finite canonical JSON"
        ) from exc


def _canonical_json_sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json_text(value).encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _numpy_scalar(value: Any) -> Any:
    if isinstance(value, np.generic):
        return value.item()
    return value


def _safe_filename(value: str) -> str:
    if not isinstance(value, str) or not _SAFE_FILENAME.fullmatch(value):
        raise TechnoeconomicExportError("Unsafe export filename")
    return value


def _require_digest(value: Any, label: str) -> str:
    if not isinstance(value, str) or not _HASH_RE.fullmatch(value):
        raise TechnoeconomicExportError(f"{label} is not a SHA-256 digest")
    return value


def _strict_regular_file(path: Path, *, label: str) -> os.stat_result:
    try:
        details = path.lstat()
    except OSError as exc:
        raise TechnoeconomicExportError(f"{label} cannot be inspected") from exc
    if stat.S_ISLNK(details.st_mode) or not stat.S_ISREG(details.st_mode):
        raise TechnoeconomicExportError(f"{label} is not a regular file")
    return details


def _confined(path: Path, root: Path, *, label: str) -> Path:
    try:
        resolved_root = root.resolve(strict=True)
        resolved = path.resolve(strict=False)
        resolved.relative_to(resolved_root)
    except (OSError, ValueError) as exc:
        raise TechnoeconomicExportError(f"{label} is outside the attempt directory") from exc
    return resolved


def _storage_key(path: Path) -> str:
    try:
        return path.resolve(strict=True).relative_to(
            config.OUTPUT_DIR.resolve(strict=True)
        ).as_posix()
    except (OSError, ValueError) as exc:
        raise TechnoeconomicExportError(
            "Published export is outside the configured output directory"
        ) from exc


def _safe_public_value(value: Any) -> Any:
    value = serializers._public_value(value)

    def normalize(item: Any) -> Any:
        if isinstance(item, Mapping):
            return {
                str(key): normalize(child)
                for key, child in sorted(item.items(), key=lambda pair: str(pair[0]))
            }
        if isinstance(item, (list, tuple)):
            return [normalize(child) for child in item]
        if isinstance(item, float) and not math.isfinite(item):
            return None
        return _numpy_scalar(item)

    return normalize(value)


def _load_sealed_calculation(
    *,
    attempt_directory: Path,
    sealed_calculation_path: Path,
    sealed_calculation_artifact: Mapping[str, Any],
    request_payload: Mapping[str, Any],
    source_snapshot: Mapping[str, Any],
    submission_provenance: Mapping[str, Any],
) -> _SealedCalculation:
    attempt_directory = attempt_directory.resolve(strict=True)
    path = _confined(
        sealed_calculation_path,
        attempt_directory,
        label="Sealed calculation payload",
    )
    details = _strict_regular_file(path, label="Sealed calculation payload")
    expected_bytes = sealed_calculation_artifact.get("byte_count")
    if not isinstance(expected_bytes, int) or isinstance(expected_bytes, bool):
        raise TechnoeconomicExportError("Sealed calculation byte count is invalid")
    if details.st_size != expected_bytes:
        raise TechnoeconomicExportError("Sealed calculation byte count changed")
    expected_sha256 = _require_digest(
        sealed_calculation_artifact.get("sha256"),
        "Sealed calculation digest",
    )
    if not secrets.compare_digest(_sha256_file(path), expected_sha256):
        raise TechnoeconomicExportError("Sealed calculation digest changed")

    try:
        with np.load(path, allow_pickle=False) as payload:
            metadata_bytes = payload["metadata_json_utf8"]
            if metadata_bytes.dtype != np.uint8 or metadata_bytes.ndim != 1:
                raise TechnoeconomicExportError(
                    "Sealed calculation metadata encoding is invalid"
                )
            metadata = json.loads(metadata_bytes.tobytes().decode("utf-8"))
            if not isinstance(metadata, Mapping):
                raise TechnoeconomicExportError(
                    "Sealed calculation metadata is not an object"
                )
            storage = metadata.get("realization_column_storage")
            names = metadata.get("realization_columns")
            if not isinstance(storage, list) or not isinstance(names, list):
                raise TechnoeconomicExportError(
                    "Sealed calculation column metadata is invalid"
                )
            if len(storage) != len(names) or not storage:
                raise TechnoeconomicExportError(
                    "Sealed calculation column metadata is inconsistent"
                )
            columns: list[np.ndarray] = []
            column_names: list[str] = []
            row_count: int | None = None
            for index, record in enumerate(storage):
                if not isinstance(record, Mapping):
                    raise TechnoeconomicExportError(
                        "Sealed calculation column record is invalid"
                    )
                column_name = record.get("column_name")
                storage_name = record.get("storage_name")
                if column_name != names[index] or not isinstance(storage_name, str):
                    raise TechnoeconomicExportError(
                        "Sealed calculation column identity is inconsistent"
                    )
                values = np.asarray(payload[storage_name])
                if values.ndim != 1 or values.dtype.kind not in "biufUS":
                    raise TechnoeconomicExportError(
                        "Sealed calculation contains an unsupported realization column"
                    )
                null_storage = record.get("null_storage_name")
                if null_storage is not None:
                    if not isinstance(null_storage, str):
                        raise TechnoeconomicExportError(
                            "Sealed calculation null-mask identity is invalid"
                        )
                    mask = np.asarray(payload[null_storage])
                    if mask.dtype != np.bool_ or mask.ndim != 1 or len(mask) != len(values):
                        raise TechnoeconomicExportError(
                            "Sealed calculation null mask is invalid"
                        )
                    restored = values.astype(object)
                    restored[mask] = None
                    values = restored
                if row_count is None:
                    row_count = len(values)
                elif len(values) != row_count:
                    raise TechnoeconomicExportError(
                        "Sealed calculation columns have inconsistent row counts"
                    )
                column_names.append(str(column_name))
                columns.append(values)
    except TechnoeconomicExportError:
        raise
    except (KeyError, OSError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TechnoeconomicExportError(
            "Sealed calculation payload cannot be decoded safely"
        ) from exc

    if row_count is None or row_count <= 0:
        raise TechnoeconomicExportError("Sealed calculation has no realization rows")
    expected_rows = sealed_calculation_artifact.get("row_count")
    expected_columns = sealed_calculation_artifact.get("column_count")
    if row_count != expected_rows or len(column_names) != expected_columns:
        raise TechnoeconomicExportError(
            "Sealed calculation dimensions differ from its durable identity"
        )
    expected_hashes = {
        "request_sha256": technoeconomic_api.canonical_json_sha256(request_payload),
        "source_snapshot_sha256": technoeconomic_api.canonical_json_sha256(source_snapshot),
        "submission_provenance_sha256": technoeconomic_api.canonical_json_sha256(
            submission_provenance
        ),
    }
    for key, expected in expected_hashes.items():
        actual = _require_digest(metadata.get(key), f"Sealed metadata {key}")
        if not secrets.compare_digest(actual, expected):
            raise TechnoeconomicExportError(
                f"Sealed calculation {key} does not match the frozen export input"
            )
    return _SealedCalculation(
        metadata=metadata,
        column_names=column_names,
        columns=columns,
        row_count=row_count,
    )


def _compact_cdf_points_for_binding(value: Any) -> Any:
    """Reproduce the durable routine-result projection of sealed CDF blocks."""

    if isinstance(value, Mapping):
        compacted: dict[str, Any] = {}
        for raw_key, item in value.items():
            key = str(raw_key)
            if key == "cdf" and isinstance(item, Mapping):
                values = item.get("values")
                compacted[key] = {
                    "population_count": item.get("population_count"),
                    "point_count": len(values) if isinstance(values, list) else 0,
                    "storage": "sealed_calculation_payload",
                }
            else:
                compacted[key] = _compact_cdf_points_for_binding(item)
        return compacted
    if isinstance(value, list):
        return [_compact_cdf_points_for_binding(item) for item in value]
    return value


def _applied_capacity_authority(
    submission_provenance: Mapping[str, Any],
) -> dict[str, Mapping[str, Any]]:
    """Return the immutable v2 applied-capacity receipt, failing closed."""

    receipt = submission_provenance.get("normalization_receipt")
    if not isinstance(receipt, Mapping):
        raise TechnoeconomicExportError(
            "Applied-capacity normalization receipt is missing"
        )
    if receipt.get("capacity_normalization") != "annual_applied_capacity_v1":
        raise TechnoeconomicExportError(
            "Applied-capacity normalization receipt has the wrong method"
        )
    records = receipt.get("applied_capacities")
    if not isinstance(records, Mapping) or set(records) != {
        "solectria",
        "solaredge",
    }:
        raise TechnoeconomicExportError(
            "Applied-capacity normalization receipt is incomplete"
        )
    result: dict[str, Mapping[str, Any]] = {}
    for system in ("solectria", "solaredge"):
        record = records.get(system)
        if not isinstance(record, Mapping):
            raise TechnoeconomicExportError(
                "Applied-capacity normalization record is invalid"
            )
        applied_w = record.get("applied_capacity_w")
        if (
            isinstance(applied_w, bool)
            or not isinstance(applied_w, (int, float))
            or not math.isfinite(float(applied_w))
            or float(applied_w) <= 0
            or record.get("rating_basis")
            not in {"ac_operating_limit", "dc_installed_nameplate"}
            or record.get("selection_method")
            != "enabled_positive_annual_curtailment_else_installed_dc"
            or not isinstance(record.get("source_field"), str)
            or not record.get("source_field")
        ):
            raise TechnoeconomicExportError(
                "Applied-capacity normalization record is invalid"
            )
        result[system] = record
    return result


def _verify_routine_result(
    *,
    metadata: Mapping[str, Any],
    routine_result: Mapping[str, Any],
    request_payload: Mapping[str, Any],
    source_snapshot: Mapping[str, Any],
    submission_provenance: Mapping[str, Any],
    sealed_calculation_artifact: Mapping[str, Any],
) -> None:
    """Bind the complete durable worker projection to frozen export authority."""

    finance = request_payload.get("finance") or {}
    manifest = source_snapshot.get("capacity_manifest") or {}
    systems = manifest.get("systems") or {}
    capacities: dict[str, Any] = {}
    for system, record in sorted(systems.items()):
        if not isinstance(record, Mapping):
            raise TechnoeconomicExportError("Frozen capacity manifest is invalid")
        capacities[str(system)] = {
            "module_model": record.get("module_model"),
            "installed_wdc": record.get("installed_wdc"),
            "physics_version": record.get("calibration_physics_version"),
            "physics_fingerprint": record.get("calibration_physics_fingerprint"),
        }
    evidence_receipt = submission_provenance.get("evidence_receipt") or {}
    if not isinstance(evidence_receipt, Mapping):
        raise TechnoeconomicExportError("Frozen evidence receipt is invalid")
    eligible_rows = source_snapshot.get("eligible_paired_energy_rows") or []
    if not isinstance(eligible_rows, list):
        raise TechnoeconomicExportError("Frozen eligible energy rows are invalid")
    public_identity_fields = (
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
    try:
        sealed_identity = {
            key: sealed_calculation_artifact[key] for key in public_identity_fields
        }
        eligible_years = [row["year"] for row in eligible_rows]
    except (KeyError, TypeError) as exc:
        raise TechnoeconomicExportError(
            "Frozen routine-result authority is incomplete"
        ) from exc
    calculation_contract_version = submission_provenance.get(
        "calculation_contract_version"
    )
    applied_capacity_contract = (
        calculation_contract_version
        == technoeconomic_kernel.CALCULATION_CONTRACT_VERSION
    )
    expected = {
        "schema_version": 2 if applied_capacity_contract else 1,
        "calculation_contract_version": submission_provenance.get(
            "calculation_contract_version"
        ),
        "sampling_version": submission_provenance.get("sampling_version"),
        "analysis_basis": request_payload.get("basis"),
        "realization_count": request_payload.get("n"),
        "seed": request_payload.get("seed"),
        "project_life_years": finance.get("project_life_years"),
        "cost_stack_completeness": request_payload.get("cost_stack_completeness"),
        "energy_available": metadata.get("energy_available"),
        "commercial_transfer_status": submission_provenance.get(
            "commercial_transfer_status"
        ),
        "commercial_reference_design": submission_provenance.get(
            "commercial_reference_design"
        ),
        "source_snapshot_sha256": submission_provenance.get(
            "source_snapshot_sha256"
        ),
        "eligible_weather_years": eligible_years,
        "capacity_basis": (
            "frozen_annual_applied_capacity_w"
            if applied_capacity_contract
            else "frozen_annual_module_dc_stc_wdc"
        ),
        "capacities": capacities,
        "input_status": evidence_receipt.get("status"),
        "evidence_class_counts": evidence_receipt.get("evidence_class_counts") or {},
        "common_cost_audit": metadata.get("common_cost_audit"),
        "summaries": _compact_cdf_points_for_binding(metadata.get("summaries")),
        "per_weather_year": _compact_cdf_points_for_binding(
            metadata.get("per_weather_year")
        ),
        "sensitivity": metadata.get("sensitivity"),
        "convergence": metadata.get("convergence"),
        "sealed_calculation": sealed_identity,
    }
    if applied_capacity_contract:
        authority = _applied_capacity_authority(submission_provenance)
        expected["applied_capacities"] = {
            system: {
                "applied_capacity_w": authority[system].get(
                    "applied_capacity_w"
                ),
                "rating_basis": authority[system].get("rating_basis"),
            }
            for system in ("solaredge", "solectria")
        }
    for key in expected:
        if key not in routine_result:
            raise TechnoeconomicExportError(
                f"Durable routine-result field {key} is missing"
            )
    actual_digest = _canonical_json_sha256(routine_result)
    expected_digest = _canonical_json_sha256(expected)
    if not secrets.compare_digest(actual_digest, expected_digest):
        raise TechnoeconomicExportError(
            "Durable routine result differs from frozen or sealed authority"
        )


def _distribution_columns(distribution: Mapping[str, Any]) -> tuple[Any, ...]:
    return tuple(
        distribution.get(key)
        for key in ("family", "value", "low", "mode", "high", "mean", "sd")
    )


def _evidence_columns(evidence: Mapping[str, Any] | None) -> tuple[Any, ...]:
    evidence = evidence if isinstance(evidence, Mapping) else {}
    citation = evidence.get("citation")
    citation = citation if isinstance(citation, Mapping) else {}
    return (
        evidence.get("evidence_class"),
        _safe_public_value(citation.get("title")),
        _safe_public_value(citation.get("organization")),
        _safe_public_value(citation.get("url")),
        _safe_public_value(citation.get("stable_reference")),
        citation.get("publication_or_as_of_date"),
        citation.get("accessed_date"),
        _safe_public_value(citation.get("excerpt_or_derivation_note")),
        citation.get("preservation_mode"),
        citation.get("user_supplied_content_sha256"),
        _safe_public_value(citation.get("metadata_only_rationale")),
        evidence.get("explicit_acceptance"),
        _safe_public_value(evidence.get("acceptance_rationale")),
    )


INPUT_COLUMNS = (
    "input_id",
    "input_category",
    "label",
    "ownership",
    "cost_type",
    "unit",
    "distribution_family",
    "fixed_value",
    "low",
    "mode",
    "high",
    "mean",
    "standard_deviation",
    "original_unit",
    "normalized_unit",
    "normalization_method",
    "constant_dollar_cost_year",
    "currency_normalization_method",
    "currency_source_cost_year",
    "currency_target_constant_dollar_cost_year",
    "currency_submitted_distribution_basis",
    "currency_index_identity",
    "currency_index_factor",
    "currency_derivation",
    "coverage_include_ids_json_part_1",
    "coverage_include_ids_json_part_2",
    "coverage_exclude_ids_json_part_1",
    "coverage_exclude_ids_json_part_2",
    "evidence_class",
    "citation_title",
    "citation_organization",
    "citation_url",
    "citation_stable_reference",
    "citation_publication_or_as_of_date",
    "citation_accessed_date",
    "citation_excerpt_or_derivation_note",
    "citation_preservation_mode",
    "citation_user_supplied_content_sha256",
    "citation_metadata_only_rationale",
    "evidence_explicit_acceptance",
    "evidence_acceptance_rationale",
    "analysis_basis",
    "cost_stack_completeness",
    "solectria_quantity",
    "solaredge_quantity",
    "quantity_unit",
    "normalization_derivation",
    "wdc_denominator_method",
    "solectria_wdc_denominator_applied",
    "solectria_wdc_denominator",
    "solectria_wdc_source_field",
    "solaredge_wdc_denominator_applied",
    "solaredge_wdc_denominator",
    "solaredge_wdc_source_field",
    "solectria_multiplier_to_intensity",
    "solaredge_multiplier_to_intensity",
)

APPLIED_INPUT_COLUMNS = INPUT_COLUMNS[:-9] + (
    "capacity_denominator_method",
    "solectria_capacity_denominator_applied",
    "solectria_applied_capacity_w",
    "solectria_applied_capacity_rating_basis",
    "solectria_applied_capacity_source_field",
    "solaredge_capacity_denominator_applied",
    "solaredge_applied_capacity_w",
    "solaredge_applied_capacity_rating_basis",
    "solaredge_applied_capacity_source_field",
    "solectria_multiplier_to_intensity",
    "solaredge_multiplier_to_intensity",
)


def _currency_normalization_columns(
    normalization: Mapping[str, Any] | None,
) -> tuple[Any, ...]:
    normalization = normalization if isinstance(normalization, Mapping) else {}
    return (
        normalization.get("method"),
        normalization.get("source_cost_year"),
        normalization.get("target_constant_dollar_cost_year"),
        normalization.get("submitted_distribution_basis"),
        _safe_public_value(normalization.get("index_identity")),
        normalization.get("index_factor"),
        _safe_public_value(normalization.get("derivation")),
    )


def _coverage_columns(values: Any) -> tuple[str, str]:
    encoded = _canonical_json_text(values if isinstance(values, list) else [])
    chunk_size = 30_000
    if len(encoded) > chunk_size * 2:
        raise TechnoeconomicExportError(
            "Frozen input coverage exceeds the lossless workbook schema"
        )
    return encoded[:chunk_size], encoded[chunk_size:]


def _input_contract_columns(
    request: Mapping[str, Any],
    line: Mapping[str, Any] | None = None,
) -> tuple[Any, ...]:
    line = line if isinstance(line, Mapping) else {}
    return (
        request.get("basis"),
        request.get("cost_stack_completeness"),
        line.get("solectria_quantity"),
        line.get("solaredge_quantity"),
        line.get("quantity_unit"),
        line.get("normalization_derivation"),
    )


def _input_normalization_receipt_columns(
    receipt_line: Mapping[str, Any] | None,
    *,
    applied_capacity_contract: bool = False,
) -> tuple[Any, ...]:
    receipt_line = receipt_line if isinstance(receipt_line, Mapping) else {}
    if applied_capacity_contract:
        denominator = receipt_line.get("capacity_denominator") or {}
        denominator = denominator if isinstance(denominator, Mapping) else {}
        solectria = denominator.get("solectria") or {}
        solaredge = denominator.get("solaredge") or {}
        solectria = solectria if isinstance(solectria, Mapping) else {}
        solaredge = solaredge if isinstance(solaredge, Mapping) else {}
        return (
            denominator.get("method"),
            solectria.get("applied"),
            solectria.get("applied_capacity_w"),
            solectria.get("rating_basis"),
            _safe_public_value(solectria.get("source_field")),
            solaredge.get("applied"),
            solaredge.get("applied_capacity_w"),
            solaredge.get("rating_basis"),
            _safe_public_value(solaredge.get("source_field")),
            receipt_line.get("solectria_multiplier_to_intensity"),
            receipt_line.get("solaredge_multiplier_to_intensity"),
        )
    denominator = receipt_line.get("wdc_denominator") or {}
    denominator = denominator if isinstance(denominator, Mapping) else {}
    solectria = denominator.get("solectria") or {}
    solaredge = denominator.get("solaredge") or {}
    solectria = solectria if isinstance(solectria, Mapping) else {}
    solaredge = solaredge if isinstance(solaredge, Mapping) else {}
    return (
        denominator.get("method"),
        solectria.get("applied"),
        solectria.get("installed_wdc"),
        _safe_public_value(solectria.get("source_field")),
        solaredge.get("applied"),
        solaredge.get("installed_wdc"),
        _safe_public_value(solaredge.get("source_field")),
        receipt_line.get("solectria_multiplier_to_intensity"),
        receipt_line.get("solaredge_multiplier_to_intensity"),
    )


def _input_rows(
    request: Mapping[str, Any],
    submission_provenance: Mapping[str, Any],
    *,
    applied_capacity_contract: bool = False,
) -> Iterator[tuple[Any, ...]]:
    cost_lines = request.get("cost_lines")
    if not isinstance(cost_lines, list):
        raise TechnoeconomicExportError("Frozen request cost lines are invalid")
    normalization_receipt = submission_provenance.get("normalization_receipt") or {}
    receipt_lines = normalization_receipt.get("lines") or []
    if not isinstance(receipt_lines, list):
        raise TechnoeconomicExportError("Frozen normalization receipt is invalid")
    receipts_by_input = {
        str(record.get("input_id")): record
        for record in receipt_lines
        if isinstance(record, Mapping)
    }
    for line in sorted(cost_lines, key=lambda item: str(item.get("input_id"))):
        distribution = line.get("distribution") or {}
        normalization = line.get("currency_year_normalization") or {}
        receipt_line = receipts_by_input.get(str(line.get("input_id")))
        yield (
            line.get("input_id"),
            "cost",
            line.get("label"),
            line.get("ownership"),
            line.get("cost_type"),
            line.get("normalized_unit"),
            *_distribution_columns(distribution),
            line.get("original_unit"),
            line.get("normalized_unit"),
            line.get("normalization_method"),
            line.get("constant_dollar_cost_year"),
            *_currency_normalization_columns(normalization),
            *_coverage_columns(line.get("coverage_include_ids") or []),
            *_coverage_columns(line.get("coverage_exclude_ids") or []),
            *_evidence_columns(line.get("evidence")),
            *_input_contract_columns(request, line),
            *_input_normalization_receipt_columns(
                receipt_line,
                applied_capacity_contract=applied_capacity_contract,
            ),
        )
        if normalization.get("method") == "price_index_adjustment":
            yield (
                f"currency-index::{line.get('input_id')}",
                "currency_year_normalization",
                normalization.get("index_identity"),
                "shared",
                None,
                "dimensionless_multiplier",
                "fixed",
                normalization.get("index_factor"),
                None,
                None,
                None,
                None,
                None,
                line.get("original_unit"),
                line.get("normalized_unit"),
                normalization.get("method"),
                normalization.get("target_constant_dollar_cost_year"),
                *_currency_normalization_columns(normalization),
                *_coverage_columns([]),
                *_coverage_columns([]),
                *_evidence_columns(normalization.get("index_source_evidence")),
                *_input_contract_columns(request, line),
                *_input_normalization_receipt_columns(
                    receipt_line,
                    applied_capacity_contract=applied_capacity_contract,
                ),
            )
    finance = request.get("finance") or {}
    discount = finance.get("real_discount_rate") or {}
    yield (
        "finance.discount-rate",
        "finance",
        "Real discount rate",
        "shared",
        None,
        discount.get("unit"),
        *_distribution_columns(discount.get("distribution") or {}),
        None,
        None,
        None,
        finance.get("constant_dollar_cost_year"),
        *_currency_normalization_columns(None),
        *_coverage_columns([]),
        *_coverage_columns([]),
        *_evidence_columns(discount.get("evidence")),
        *_input_contract_columns(request),
        *_input_normalization_receipt_columns(
            None,
            applied_capacity_contract=applied_capacity_contract,
        ),
    )
    yield (
        "finance.project-life",
        "finance",
        "Project life",
        "shared",
        None,
        "years",
        "fixed",
        finance.get("project_life_years"),
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        finance.get("treatment_key"),
        finance.get("constant_dollar_cost_year"),
        *_currency_normalization_columns(None),
        *_coverage_columns([]),
        *_coverage_columns([]),
        *_evidence_columns(finance.get("project_life_evidence")),
        *_input_contract_columns(request),
        *_input_normalization_receipt_columns(
            None,
            applied_capacity_contract=applied_capacity_contract,
        ),
    )
    degradation = request.get("shared_degradation") or {}
    annual_rate = degradation.get("annual_rate") or {}
    yield (
        "energy.shared-degradation",
        "degradation",
        "Shared annual module degradation",
        "shared",
        None,
        annual_rate.get("unit"),
        *_distribution_columns(annual_rate.get("distribution") or {}),
        None,
        None,
        degradation.get("degradation_model"),
        finance.get("constant_dollar_cost_year"),
        *_currency_normalization_columns(None),
        *_coverage_columns([]),
        *_coverage_columns([]),
        *_evidence_columns(annual_rate.get("evidence")),
        *_input_contract_columns(request),
        *_input_normalization_receipt_columns(
            None,
            applied_capacity_contract=applied_capacity_contract,
        ),
    )
    transfer = request.get("commercial_transfer")
    reference_design = request.get("commercial_reference_design")
    if isinstance(reference_design, Mapping):
        yield (
            "commercial.reference-design",
            "commercial_reference_design",
            reference_design.get("design_id"),
            "shared",
            None,
            "Wdc",
            "fixed",
            reference_design.get("reference_wdc"),
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            "module_count_times_module_stc_wdc",
            reference_design.get("constant_dollar_cost_year"),
            *_currency_normalization_columns(None),
            *_coverage_columns([]),
            *_coverage_columns([]),
            *_evidence_columns(reference_design.get("evidence")),
            *_input_contract_columns(request),
            *_input_normalization_receipt_columns(
                None,
                applied_capacity_contract=applied_capacity_contract,
            ),
        )
    if isinstance(transfer, Mapping):
        for input_id, label, field in (
            ("transfer.baseline", "Commercial baseline transfer factor", "baseline_factor"),
            ("transfer.incremental", "Commercial incremental transfer factor", "incremental_factor"),
        ):
            record = transfer.get(field) or {}
            yield (
                input_id,
                "commercial_transfer",
                label,
                "shared",
                None,
                record.get("unit"),
                *_distribution_columns(record.get("distribution") or {}),
                None,
                None,
                "commercial_transfer_attestation",
                finance.get("constant_dollar_cost_year"),
                *_currency_normalization_columns(None),
                *_coverage_columns([]),
                *_coverage_columns([]),
                *_evidence_columns(record.get("evidence")),
                *_input_contract_columns(request),
                *_input_normalization_receipt_columns(
                    None,
                    applied_capacity_contract=applied_capacity_contract,
                ),
            )
        for mechanism in sorted(
            transfer.get("mechanisms") or [],
            key=lambda item: str(item.get("mechanism")),
        ):
            yield (
                f"transfer-mechanism::{mechanism.get('mechanism')}",
                "commercial_transfer_mechanism",
                mechanism.get("mechanism"),
                "shared",
                None,
                "categorical_attestation",
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                mechanism.get("status"),
                finance.get("constant_dollar_cost_year"),
                *_currency_normalization_columns(None),
                *_coverage_columns([]),
                *_coverage_columns([]),
                *_evidence_columns(mechanism.get("evidence")),
                *_input_contract_columns(request),
                *_input_normalization_receipt_columns(
                    None,
                    applied_capacity_contract=applied_capacity_contract,
                ),
            )


ENERGY_COLUMNS = (
    "eligibility_status",
    "year",
    "period_start",
    "period_end",
    "solectria_predicted_kwh_ac",
    "solaredge_predicted_kwh_ac",
    "exclusion_reason",
    "source_record_sha256",
    "source_record_provenance_path",
    "source_annual_job_id",
    "source_snapshot_sha256",
    "source_artifact_sha256",
    "source_artifact_bytes",
    "source_artifact_media_type",
)


def _first_present(record: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in record and record[key] is not None:
            return record[key]
    return None


def _energy_rows(
    source_snapshot: Mapping[str, Any],
    source_snapshot_sha256: str,
) -> Iterator[tuple[Any, ...]]:
    artifact = source_snapshot.get("midc_source_artifact") or {}
    source_id = source_snapshot.get("source_annual_job_id")
    groups = (
        (
            "eligible",
            "eligible_paired_energy_rows",
            source_snapshot.get("eligible_paired_energy_rows") or [],
        ),
        (
            "excluded",
            "excluded_annual_energy_rows",
            source_snapshot.get("excluded_annual_energy_rows") or [],
        ),
    )
    for status_name, source_field, records in groups:
        if not isinstance(records, list):
            raise TechnoeconomicExportError("Frozen energy snapshot rows are invalid")

        def source_row(record: Mapping[str, Any]) -> Mapping[str, Any]:
            nested = record.get("row") if status_name == "excluded" else None
            return nested if isinstance(nested, Mapping) else record

        for source_index, record in sorted(
            enumerate(records),
            key=lambda pair: (
                int(source_row(pair[1]).get("year") or 0),
                _canonical_json_text(_safe_public_value(pair[1])),
            ),
        ):
            row = source_row(record)
            reasons = record.get("reasons") if status_name == "excluded" else None
            if isinstance(reasons, list):
                exclusion_reason = _canonical_json_text(reasons)
            else:
                exclusion_reason = row.get("reason") or row.get("exclusion_reason")
            yield (
                status_name,
                row.get("year"),
                row.get("period_start"),
                row.get("period_end"),
                _first_present(row, "sol_predicted_kwh", "sol_predicted_kwh_ac"),
                _first_present(row, "se_predicted_kwh", "se_predicted_kwh_ac"),
                exclusion_reason,
                _canonical_json_sha256(_safe_public_value(record)),
                f"source_snapshot.{source_field}[{source_index}]",
                source_id,
                source_snapshot_sha256,
                artifact.get("sha256"),
                artifact.get("byte_count"),
                artifact.get("media_type"),
            )


CAPACITY_COLUMNS = (
    "record_type",
    "system",
    "analysis_basis",
    "capacity_basis",
    "module_model",
    "module_stc_wdc",
    "module_count",
    "installed_wdc",
    "rating_basis",
    "strings",
    "bays_per_string",
    "modules_per_bay",
    "calibration_physics_version",
    "calibration_physics_fingerprint",
    "capacity_manifest_sha256",
    "capacity_manifest_source_json",
    "commercial_reference_design_id",
    "commercial_reference_wdc",
    "commercial_reference_module_model",
    "commercial_reference_module_stc_wdc",
    "commercial_reference_module_count",
    "commercial_reference_constant_dollar_cost_year",
    "commercial_reference_design_sha256",
    "commercial_transfer_status",
    "source_snapshot_sha256",
)

APPLIED_CAPACITY_COLUMNS = CAPACITY_COLUMNS[:8] + (
    "applied_capacity_w",
    "applied_capacity_rating_basis",
    "applied_capacity_selection_method",
    "applied_capacity_source_field",
) + CAPACITY_COLUMNS[8:]


def _capacity_rows(
    source_snapshot: Mapping[str, Any],
    submission_provenance: Mapping[str, Any],
    routine_result: Mapping[str, Any],
    *,
    applied_capacity_contract: bool = False,
) -> Iterator[tuple[Any, ...]]:
    manifest = source_snapshot.get("capacity_manifest") or {}
    systems = manifest.get("systems") or {}
    reference_design = submission_provenance.get("commercial_reference_design")
    reference_design = (
        reference_design if isinstance(reference_design, Mapping) else {}
    )
    applied_authority = (
        _applied_capacity_authority(submission_provenance)
        if applied_capacity_contract
        else {}
    )
    for system in ("solectria", "solaredge"):
        record = systems.get(system) or {}
        base = (
            "frozen_annual_capacity",
            system,
            routine_result.get("analysis_basis"),
            routine_result.get("capacity_basis"),
            record.get("module_model"),
            record.get("module_stc_wdc"),
            record.get("module_count"),
            record.get("installed_wdc"),
        )
        if applied_capacity_contract:
            applied = applied_authority[system]
            base += (
                applied.get("applied_capacity_w"),
                applied.get("rating_basis"),
                applied.get("selection_method"),
                _safe_public_value(applied.get("source_field")),
            )
        yield base + (
            record.get("rating_basis") or manifest.get("rating_basis"),
            record.get("strings"),
            record.get("bays_per_string"),
            record.get("modules_per_bay"),
            record.get("calibration_physics_version"),
            record.get("calibration_physics_fingerprint"),
            manifest.get("capacity_manifest_sha256"),
            _canonical_json_text(
                _safe_public_value(source_snapshot.get("capacity_manifest_source"))
            ),
            reference_design.get("design_id"),
            reference_design.get("reference_wdc"),
            reference_design.get("module_model"),
            reference_design.get("module_stc_wdc"),
            reference_design.get("module_count"),
            reference_design.get("constant_dollar_cost_year"),
            reference_design.get("design_sha256"),
            submission_provenance.get("commercial_transfer_status"),
            submission_provenance.get("source_snapshot_sha256"),
        )


COMMON_COST_COLUMNS = (
    "input_id",
    "label",
    "cost_type",
    "comparison_treatment",
    "reasons_json",
    "solectria_multiplier_to_intensity",
    "solaredge_multiplier_to_intensity",
    "solectria_treatment_key",
    "solaredge_treatment_key",
    "solectria_contribution_min",
    "solectria_contribution_max",
    "solaredge_contribution_min",
    "solaredge_contribution_max",
    "contribution_units",
    "delta_contribution_min_se_minus_sol",
    "delta_contribution_max_se_minus_sol",
    "delta_contribution_se_minus_sol_exactly_zero",
)


def _common_cost_rows(records: Sequence[Mapping[str, Any]]) -> Iterator[tuple[Any, ...]]:
    for record in sorted(records, key=lambda row: str(row.get("input_id"))):
        yield (
            record.get("input_id"),
            record.get("label"),
            record.get("cost_type"),
            record.get("comparison_treatment"),
            _canonical_json_text(record.get("reasons") or []),
            record.get("solectria_multiplier_to_intensity"),
            record.get("solaredge_multiplier_to_intensity"),
            record.get("solectria_treatment_key"),
            record.get("solaredge_treatment_key"),
            record.get("solectria_contribution_min"),
            record.get("solectria_contribution_max"),
            record.get("solaredge_contribution_min"),
            record.get("solaredge_contribution_max"),
            record.get("contribution_units"),
            record.get("delta_contribution_min_se_minus_sol"),
            record.get("delta_contribution_max_se_minus_sol"),
            record.get("delta_contribution_se_minus_sol_exactly_zero"),
        )


TRANSFER_COLUMNS = (
    "record_type",
    "status",
    "energy_available",
    "mechanism",
    "mechanism_status",
    "rationale_sha256",
    "mechanism_rationale",
    "mechanism_evidence_sha256",
    "mechanism_evidence_field_path",
    "mechanism_evidence_value_json",
    "explicit_attestation",
    "attested_by",
    "attested_at",
    "attestation_rationale_sha256",
    "baseline_factor_input_id",
    "incremental_factor_input_id",
    "all_mechanisms_resolved",
    "commercial_reference_design_sha256",
    "commercial_reference_design_field_path",
    "commercial_reference_design_value_json",
    "transfer_receipt_sha256",
)


def _transfer_rows(
    request_payload: Mapping[str, Any],
    submission_provenance: Mapping[str, Any],
) -> Iterator[tuple[Any, ...]]:
    receipt = submission_provenance.get("commercial_transfer_receipt") or {}
    common = {
        "status": receipt.get("status"),
        "energy_available": receipt.get("energy_available"),
        "explicit_attestation": receipt.get("explicit_attestation"),
        "attested_by": receipt.get("attested_by"),
        "attested_at": receipt.get("attested_at"),
        "attestation_rationale_sha256": receipt.get(
            "attestation_rationale_sha256"
        ),
        "baseline_factor_input_id": receipt.get("baseline_factor_input_id"),
        "incremental_factor_input_id": receipt.get("incremental_factor_input_id"),
        "all_mechanisms_resolved": receipt.get("all_mechanisms_resolved"),
        "commercial_reference_design_sha256": submission_provenance.get(
            "commercial_reference_design_sha256"
        ),
        "transfer_receipt_sha256": submission_provenance.get(
            "commercial_transfer_receipt_sha256"
        ),
    }

    def values(**updates: Any) -> tuple[Any, ...]:
        record = {column: None for column in TRANSFER_COLUMNS}
        record.update(common)
        record.update(updates)
        return tuple(record[column] for column in TRANSFER_COLUMNS)

    yield values(record_type="transfer_summary")
    transfer_request = request_payload.get("commercial_transfer") or {}
    request_mechanisms = transfer_request.get("mechanisms") or []
    request_by_mechanism = {
        str(record.get("mechanism")): record
        for record in request_mechanisms
        if isinstance(record, Mapping)
    }
    mechanisms = receipt.get("mechanisms") or []
    for record in sorted(mechanisms, key=lambda row: str(row.get("mechanism"))):
        mechanism = str(record.get("mechanism"))
        request_record = request_by_mechanism.get(mechanism) or {}
        evidence = request_record.get("evidence")
        evidence_sha256 = (
            _canonical_json_sha256(evidence) if isinstance(evidence, Mapping) else None
        )
        yield values(
            record_type="mechanism",
            mechanism=mechanism,
            mechanism_status=record.get("status"),
            rationale_sha256=record.get("rationale_sha256"),
            mechanism_rationale=_safe_public_value(request_record.get("rationale")),
            mechanism_evidence_sha256=evidence_sha256,
        )
        if isinstance(evidence, Mapping):
            for field_path, encoded in _flatten_leaves("", evidence):
                yield values(
                    record_type="mechanism_evidence_field",
                    mechanism=mechanism,
                    mechanism_status=record.get("status"),
                    rationale_sha256=record.get("rationale_sha256"),
                    mechanism_rationale=_safe_public_value(
                        request_record.get("rationale")
                    ),
                    mechanism_evidence_sha256=evidence_sha256,
                    mechanism_evidence_field_path=field_path,
                    mechanism_evidence_value_json=encoded,
                )
    reference_design = request_payload.get("commercial_reference_design")
    if isinstance(reference_design, Mapping):
        for field_path, encoded in _flatten_leaves("", reference_design):
            yield values(
                record_type="commercial_reference_design_field",
                commercial_reference_design_field_path=field_path,
                commercial_reference_design_value_json=encoded,
            )


CDF_COLUMNS = (
    "metric_id",
    "status",
    "reason",
    "population_count",
    "point_index",
    "value",
    "cumulative_count",
    "cumulative_probability",
    "p5",
    "p50",
    "p95",
)


def _metric_summaries(metadata: Mapping[str, Any]) -> Mapping[str, Any]:
    summaries = metadata.get("summaries")
    if not isinstance(summaries, Mapping):
        raise TechnoeconomicExportError("Sealed metric summaries are invalid")
    return summaries


def _cdf_rows(metadata: Mapping[str, Any]) -> Iterator[tuple[Any, ...]]:
    for metric_id, summary in sorted(_metric_summaries(metadata).items()):
        if not isinstance(summary, Mapping) or "percentiles" not in summary:
            continue
        percentiles = summary.get("percentiles") or {}
        cdf = summary.get("cdf")
        if not isinstance(cdf, Mapping):
            yield (
                metric_id,
                summary.get("status"),
                summary.get("reason"),
                summary.get("count", 0),
                None,
                None,
                None,
                None,
                percentiles.get("p5"),
                percentiles.get("p50"),
                percentiles.get("p95"),
            )
            continue
        values = cdf.get("values") or []
        counts = cdf.get("cumulative_count") or []
        probabilities = cdf.get("cumulative_probability") or []
        if not (len(values) == len(counts) == len(probabilities)):
            raise TechnoeconomicExportError("Sealed CDF arrays are inconsistent")
        for index, (value, count, probability) in enumerate(
            zip(values, counts, probabilities),
            start=1,
        ):
            yield (
                metric_id,
                summary.get("status"),
                summary.get("reason"),
                cdf.get("population_count"),
                index,
                value,
                count,
                probability,
                percentiles.get("p5"),
                percentiles.get("p50"),
                percentiles.get("p95"),
            )


def _per_year_base_columns(metadata: Mapping[str, Any]) -> tuple[str, ...]:
    rows = metadata.get("per_weather_year") or []
    applied_capacity_contract = any(
        isinstance(row, Mapping) and "solectria_applied_w" in row
        for row in rows
    )
    if applied_capacity_contract:
        return (
            "year",
            "source_sol_predicted_kwh_ac",
            "source_se_predicted_kwh_ac",
            "solectria_installed_wdc",
            "solaredge_installed_wdc",
            "solectria_applied_w",
            "solaredge_applied_w",
            "source_sol_specific_kwh_ac_per_applied_w_year",
            "source_se_specific_kwh_ac_per_applied_w_year",
            "source_delta_specific_se_minus_sol_kwh_ac_per_applied_w_year",
            "realization_count",
            "realization_share",
            "reason",
            "energy_class_counts_json",
            "energy_class_probabilities_json",
        )
    return (
        "year",
        "source_sol_predicted_kwh_ac",
        "source_se_predicted_kwh_ac",
        "solectria_installed_wdc",
        "solaredge_installed_wdc",
        "source_sol_specific_kwh_ac_per_wdc_year",
        "source_se_specific_kwh_ac_per_wdc_year",
        "source_delta_specific_se_minus_sol_kwh_ac_per_wdc_year",
        "realization_count",
        "realization_share",
        "reason",
        "energy_class_counts_json",
        "energy_class_probabilities_json",
    )


def _per_year_columns(metadata: Mapping[str, Any]) -> tuple[str, ...]:
    base = _per_year_base_columns(metadata)
    rows = metadata.get("per_weather_year") or []
    metric_ids = sorted(
        {
            str(metric_id)
            for row in rows
            if isinstance(row, Mapping)
            for metric_id in (row.get("metrics") or {})
        }
    )
    suffixes = ("status", "reason", "count", "p5", "p50", "p95")
    return base + tuple(
        f"{metric_id}::{suffix}" for metric_id in metric_ids for suffix in suffixes
    )


def _per_year_rows(metadata: Mapping[str, Any]) -> Iterator[tuple[Any, ...]]:
    base_columns = _per_year_base_columns(metadata)
    columns = _per_year_columns(metadata)
    metric_columns = columns[len(base_columns):]
    applied_capacity_contract = "solectria_applied_w" in base_columns
    rows = metadata.get("per_weather_year") or []
    for record in sorted(rows, key=lambda row: int(row.get("year"))):
        metrics = record.get("metrics") or {}
        flattened: dict[str, Any] = {}
        for metric_id, summary in metrics.items():
            percentiles = summary.get("percentiles") or {}
            flattened.update(
                {
                    f"{metric_id}::status": summary.get("status"),
                    f"{metric_id}::reason": summary.get("reason"),
                    f"{metric_id}::count": summary.get("count"),
                    f"{metric_id}::p5": percentiles.get("p5"),
                    f"{metric_id}::p50": percentiles.get("p50"),
                    f"{metric_id}::p95": percentiles.get("p95"),
                }
            )
        base = (
            record.get("year"),
            record.get("source_sol_predicted_kwh_ac"),
            record.get("source_se_predicted_kwh_ac"),
            record.get("solectria_installed_wdc"),
            record.get("solaredge_installed_wdc"),
        )
        if applied_capacity_contract:
            base += (
                record.get("solectria_applied_w"),
                record.get("solaredge_applied_w"),
                record.get("source_sol_specific_kwh_ac_per_applied_w_year"),
                record.get("source_se_specific_kwh_ac_per_applied_w_year"),
                record.get(
                    "source_delta_specific_se_minus_sol_kwh_ac_per_applied_w_year"
                ),
            )
        else:
            base += (
                record.get("source_sol_specific_kwh_ac_per_wdc_year"),
                record.get("source_se_specific_kwh_ac_per_wdc_year"),
                record.get(
                    "source_delta_specific_se_minus_sol_kwh_ac_per_wdc_year"
                ),
            )
        yield base + (
            record.get("realization_count"),
            record.get("realization_share"),
            record.get("reason"),
            _canonical_json_text(record.get("energy_class_counts") or {}),
            _canonical_json_text(record.get("energy_class_probabilities") or {}),
            *(flattened.get(name) for name in metric_columns),
        )


SENSITIVITY_COLUMNS = (
    "response_id",
    "record_type",
    "status",
    "reason",
    "sample_count",
    "minimum_sample_count",
    "candidate_predictor_count",
    "entered_predictor_count",
    "entry_order",
    "predictor_id",
    "incremental_r_squared",
    "cumulative_r_squared",
    "standardized_beta",
    "sign",
    "exclusion_reason",
    "exclusion_detail_json",
    "final_r_squared",
    "warnings_json",
)


def _sensitivity_rows(metadata: Mapping[str, Any]) -> Iterator[tuple[Any, ...]]:
    models = metadata.get("sensitivity") or {}
    for response_id, model in sorted(models.items()):
        common = (
            response_id,
            model.get("status"),
            model.get("reason"),
            model.get("sample_count"),
            model.get("minimum_sample_count"),
            model.get("candidate_predictor_count"),
            model.get("entered_predictor_count"),
            model.get("final_r_squared"),
            _canonical_json_text(model.get("warnings") or []),
        )
        yield (
            common[0],
            "model_summary",
            *common[1:7],
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            "{}",
            common[7],
            common[8],
        )
        for step in model.get("steps") or []:
            yield (
                common[0],
                "entered_step",
                *common[1:7],
                step.get("entry_order"),
                step.get("predictor_id"),
                step.get("incremental_r_squared"),
                step.get("cumulative_r_squared"),
                step.get("standardized_beta"),
                step.get("sign"),
                None,
                "{}",
                common[7],
                common[8],
            )
        exclusions = model.get("exclusions") or {}
        for predictor_id, detail in sorted(exclusions.items()):
            if isinstance(detail, Mapping):
                reason = detail.get("reason")
                detail_json = _canonical_json_text(detail)
            else:
                reason = detail
                detail_json = _canonical_json_text({"reason": detail})
            yield (
                common[0],
                "exclusion",
                *common[1:7],
                None,
                predictor_id,
                None,
                None,
                None,
                None,
                reason,
                detail_json,
                common[7],
                common[8],
            )


CONVERGENCE_COLUMNS = (
    "record_type",
    "checkpoint_index",
    "realization_count",
    "metric_id",
    "category_or_year",
    "population_count",
    "p5",
    "p50",
    "p95",
    "p5_absolute_change",
    "p5_relative_change",
    "p50_absolute_change",
    "p50_relative_change",
    "p95_absolute_change",
    "p95_relative_change",
    "count",
    "share_or_probability",
    "convergence_status",
    "reasons_json",
    "metric_absolute_tolerance",
    "relative_change_threshold",
    "class_probability_change_threshold",
)


def _convergence_rows(metadata: Mapping[str, Any]) -> Iterator[tuple[Any, ...]]:
    convergence = metadata.get("convergence") or {}
    tolerances = convergence.get("metric_absolute_tolerances") or {}
    common_tail = (
        convergence.get("status"),
        _canonical_json_text(convergence.get("reasons") or []),
        convergence.get("relative_change_threshold"),
        convergence.get("class_probability_change_threshold"),
    )
    for checkpoint_index, checkpoint in enumerate(
        convergence.get("checkpoints") or [],
        start=1,
    ):
        count = checkpoint.get("realization_count")
        for metric_id, metric in sorted((checkpoint.get("metrics") or {}).items()):
            percentiles = metric.get("percentiles") or {}
            changes = metric.get("change_from_previous") or {}
            yield (
                "metric",
                checkpoint_index,
                count,
                metric_id,
                None,
                metric.get("population_count"),
                percentiles.get("p5"),
                percentiles.get("p50"),
                percentiles.get("p95"),
                (changes.get("p5") or {}).get("absolute"),
                (changes.get("p5") or {}).get("relative"),
                (changes.get("p50") or {}).get("absolute"),
                (changes.get("p50") or {}).get("relative"),
                (changes.get("p95") or {}).get("absolute"),
                (changes.get("p95") or {}).get("relative"),
                None,
                None,
                common_tail[0],
                common_tail[1],
                tolerances.get(metric_id),
                common_tail[2],
                common_tail[3],
            )
        for record_type, probabilities in (
            ("energy_class", checkpoint.get("energy_class_probabilities")),
            ("tradeoff_class", checkpoint.get("tradeoff_probabilities")),
        ):
            for category, probability in sorted((probabilities or {}).items()):
                yield (
                    record_type,
                    checkpoint_index,
                    count,
                    None,
                    category,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    probability,
                    common_tail[0],
                    common_tail[1],
                    None,
                    common_tail[2],
                    common_tail[3],
                )
        year_counts = checkpoint.get("weather_year_counts") or {}
        year_shares = checkpoint.get("weather_year_shares") or {}
        for year, year_count in sorted(year_counts.items(), key=lambda pair: int(pair[0])):
            yield (
                "weather_year",
                checkpoint_index,
                count,
                None,
                year,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                year_count,
                year_shares.get(year, year_shares.get(str(year))),
                common_tail[0],
                common_tail[1],
                None,
                common_tail[2],
                common_tail[3],
            )


PROVENANCE_COLUMNS = ("section", "field_path", "value_json")

_LONG_TEXT_CHUNK_SIZE = 30_000
_LONG_TEXT_CHUNK_MARKER = ".__json_chunk__"


def _chunked_leaf_rows(prefix: str, encoded: str) -> Iterator[tuple[str, str]]:
    if len(encoded) <= _LONG_TEXT_CHUNK_SIZE:
        yield prefix, encoded
        return
    count = math.ceil(len(encoded) / _LONG_TEXT_CHUNK_SIZE)
    for index in range(count):
        start = index * _LONG_TEXT_CHUNK_SIZE
        suffix = f"{_LONG_TEXT_CHUNK_MARKER}[{index + 1:04d}-of-{count:04d}]"
        yield f"{prefix}{suffix}", encoded[start : start + _LONG_TEXT_CHUNK_SIZE]


def _flatten_leaves(prefix: str, value: Any) -> Iterator[tuple[str, str]]:
    value = _safe_public_value(value)
    if isinstance(value, Mapping):
        if not value:
            yield prefix, "{}"
        for key, item in sorted(value.items()):
            next_prefix = f"{prefix}.{key}" if prefix else str(key)
            yield from _flatten_leaves(next_prefix, item)
    elif isinstance(value, list):
        if not value:
            yield prefix, "[]"
        for index, item in enumerate(value):
            yield from _flatten_leaves(f"{prefix}[{index}]", item)
    else:
        yield from _chunked_leaf_rows(prefix, _canonical_json_text(value))


def _provenance_rows(
    request_payload: Mapping[str, Any],
    source_snapshot: Mapping[str, Any],
    submission_provenance: Mapping[str, Any],
    routine_result: Mapping[str, Any],
    metadata: Mapping[str, Any],
) -> Iterator[tuple[str, str, str]]:
    sections = {
        "request": request_payload,
        "source_snapshot": source_snapshot,
        "submission": submission_provenance,
        "routine_result": routine_result,
        "kernel": metadata.get("kernel_provenance") or {},
    }
    for section, value in sections.items():
        for field_path, encoded in _flatten_leaves("", value):
            yield section, field_path, encoded


CHECK_COLUMNS = (
    "check_id",
    "actual_authority",
    "expected_authority",
    "difference_authority",
    "tolerance",
    "status_authority",
    "notes",
)


def _finite_values(values: np.ndarray) -> np.ndarray:
    try:
        vector = np.asarray(values, dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise TechnoeconomicExportError("A numeric tie-out column is invalid") from exc
    return vector[np.isfinite(vector)]


def _metric_population(
    metric_id: str,
    calculation: _SealedCalculation,
) -> np.ndarray | None:
    if metric_id in calculation.by_name:
        return _finite_values(calculation.by_name[metric_id])
    lcoo_column = technoeconomic_kernel.FIELD_LCOO
    if metric_id == "headline_positive_gain_lcoo":
        if lcoo_column not in calculation.by_name or "energy_class" not in calculation.by_name:
            return None
        values = np.asarray(calculation.by_name[lcoo_column], dtype=np.float64)
        classes = np.asarray(calculation.by_name["energy_class"])
        return values[(classes == "positive_lifecycle_gain") & np.isfinite(values)]
    if metric_id == "signed_nonzero_lcoo":
        if lcoo_column not in calculation.by_name:
            return None
        return _finite_values(calculation.by_name[lcoo_column])
    return None


def _numeric_check(
    check_id: str,
    actual: float | int,
    expected: float | int,
    *,
    tolerance: float,
    notes: str,
) -> tuple[Any, ...]:
    difference = float(actual) - float(expected)
    return (
        check_id,
        actual,
        expected,
        difference,
        tolerance,
        "OK" if abs(difference) <= tolerance else "FAIL",
        notes,
    )


def _binary64_tie_out_tolerance(*values: np.ndarray) -> float:
    scale = 1.0
    for values_array in values:
        finite = np.asarray(values_array, dtype=np.float64)
        finite = finite[np.isfinite(finite)]
        if finite.size:
            scale = max(scale, float(np.max(np.abs(finite))))
    return float(16.0 * np.finfo(np.float64).eps * scale)


def _metric_fields_for_result(
    routine_result: Mapping[str, Any],
) -> Any:
    contract_version = routine_result.get("calculation_contract_version")
    if contract_version == technoeconomic_kernel.LEGACY_CALCULATION_CONTRACT_VERSION:
        return technoeconomic_kernel.LEGACY_METRIC_FIELDS
    if contract_version == technoeconomic_kernel.CALCULATION_CONTRACT_VERSION:
        return technoeconomic_kernel.APPLIED_METRIC_FIELDS
    raise TechnoeconomicExportError(
        f"Unsupported calculation contract in routine result: {contract_version!r}"
    )


def _build_checks(
    calculation: _SealedCalculation,
    source_snapshot: Mapping[str, Any],
    submission_provenance: Mapping[str, Any],
    routine_result: Mapping[str, Any],
) -> list[tuple[Any, ...]]:
    checks: list[tuple[Any, ...]] = []
    fields = _metric_fields_for_result(routine_result)
    applied_capacity_contract = (
        routine_result.get("calculation_contract_version")
        == technoeconomic_kernel.CALCULATION_CONTRACT_VERSION
    )
    expected_rows = routine_result.get("realization_count")
    if not isinstance(expected_rows, int) or isinstance(expected_rows, bool):
        raise TechnoeconomicExportError("Routine result realization count is invalid")
    checks.append(
        _numeric_check(
            "realization_count",
            calculation.row_count,
            expected_rows,
            tolerance=0.0,
            notes="Sealed realization rows equal the durable routine-result count.",
        )
    )
    summaries = _metric_summaries(calculation.metadata)
    for metric_id, summary in sorted(summaries.items()):
        if not isinstance(summary, Mapping) or "percentiles" not in summary:
            continue
        population = _metric_population(metric_id, calculation)
        if population is None:
            continue
        checks.append(
            _numeric_check(
                f"summary_count::{metric_id}",
                len(population),
                int(summary.get("count") or 0),
                tolerance=0.0,
                notes="Finite realization population equals the frozen summary count.",
            )
        )
        if len(population):
            calculated = np.quantile(population, [0.05, 0.5, 0.95], method="linear")
            percentiles = summary.get("percentiles") or {}
            for index, quantile in enumerate(("p5", "p50", "p95")):
                expected = percentiles.get(quantile)
                if expected is None:
                    checks.append(
                        (
                            f"percentile::{metric_id}::{quantile}",
                            float(calculated[index]),
                            None,
                            None,
                            1e-12,
                            "FAIL",
                            "Available finite population has a missing frozen percentile.",
                        )
                    )
                else:
                    scale = max(1.0, abs(float(expected)))
                    checks.append(
                        _numeric_check(
                            f"percentile::{metric_id}::{quantile}",
                            float(calculated[index]),
                            float(expected),
                            tolerance=1e-12 * scale,
                            notes="Type-7 percentile recomputed from sealed realization values.",
                        )
                    )
            cdf = summary.get("cdf")
            if isinstance(cdf, Mapping):
                unique_values, duplicate_counts = np.unique(
                    np.sort(population),
                    return_counts=True,
                )
                cumulative_count = np.cumsum(duplicate_counts, dtype=np.int64)
                recomputed_cdf = {
                    "values": [float(value) for value in unique_values],
                    "cumulative_count": [int(value) for value in cumulative_count],
                    "cumulative_probability": [
                        float(value / len(population)) for value in cumulative_count
                    ],
                    "population_count": int(len(population)),
                }
                actual_digest = _canonical_json_sha256(recomputed_cdf)
                expected_digest = _canonical_json_sha256(cdf)
                checks.append(
                    (
                        f"cdf_full_identity::{metric_id}",
                        actual_digest,
                        expected_digest,
                        None,
                        None,
                        "OK"
                        if secrets.compare_digest(actual_digest, expected_digest)
                        else "FAIL",
                        "Full right-continuous ECDF values, duplicate counts, and probabilities are recomputed from sealed realizations.",
                    )
                )
                terminal = (cdf.get("cumulative_probability") or [None])[-1]
                checks.append(
                    _numeric_check(
                        f"cdf_terminal_probability::{metric_id}",
                        float(terminal),
                        1.0,
                        tolerance=0.0,
                        notes="Right-continuous ECDF terminates at probability one.",
                    )
                )

    capacities = routine_result.get("capacities") or {}
    snapshot_systems = (source_snapshot.get("capacity_manifest") or {}).get("systems") or {}
    for system in ("solectria", "solaredge"):
        actual = (capacities.get(system) or {}).get("installed_wdc")
        expected = (snapshot_systems.get(system) or {}).get("installed_wdc")
        if actual is None or expected is None:
            raise TechnoeconomicExportError("Capacity tie-out evidence is missing")
        checks.append(
            _numeric_check(
                f"capacity_wdc::{system}",
                float(actual),
                float(expected),
                tolerance=0.0,
                notes="Durable result capacity equals the frozen Annual capacity manifest.",
            )
        )

    applied_capacity_authority: dict[str, Mapping[str, Any]] = {}
    if applied_capacity_contract:
        applied_capacity_authority = _applied_capacity_authority(
            submission_provenance
        )
        result_applied = routine_result.get("applied_capacities") or {}
        if not isinstance(result_applied, Mapping):
            raise TechnoeconomicExportError(
                "Durable applied-capacity result is invalid"
            )
        for system in ("solectria", "solaredge"):
            actual = result_applied.get(system) or {}
            expected = applied_capacity_authority[system]
            if not isinstance(actual, Mapping):
                raise TechnoeconomicExportError(
                    "Durable applied-capacity result is incomplete"
                )
            checks.append(
                _numeric_check(
                    f"applied_capacity_w::{system}",
                    float(actual.get("applied_capacity_w")),
                    float(expected.get("applied_capacity_w")),
                    tolerance=0.0,
                    notes=(
                        "Durable applied capacity equals the immutable "
                        "normalization receipt."
                    ),
                )
            )
            actual_basis = actual.get("rating_basis")
            expected_basis = expected.get("rating_basis")
            checks.append(
                (
                    f"applied_capacity_rating_basis::{system}",
                    actual_basis,
                    expected_basis,
                    None,
                    None,
                    "OK" if actual_basis == expected_basis else "FAIL",
                    "Durable applied-capacity rating basis matches its receipt.",
                )
            )

    source_hash_actual = routine_result.get("source_snapshot_sha256")
    source_hash_expected = submission_provenance.get("source_snapshot_sha256")
    checks.append(
        (
            "source_snapshot_sha256",
            source_hash_actual,
            source_hash_expected,
            None,
            None,
            "OK"
            if isinstance(source_hash_actual, str)
            and isinstance(source_hash_expected, str)
            and secrets.compare_digest(source_hash_actual, source_hash_expected)
            else "FAIL",
            "Durable result is bound to the submission's frozen source snapshot.",
        )
    )
    transfer_actual = routine_result.get("commercial_transfer_status")
    transfer_expected = submission_provenance.get("commercial_transfer_status")
    checks.append(
        (
            "commercial_transfer_status",
            transfer_actual,
            transfer_expected,
            None,
            None,
            "OK" if transfer_actual == transfer_expected else "FAIL",
            "Result and immutable transfer receipt use the same status.",
        )
    )

    common_records = calculation.metadata.get("common_cost_audit") or []
    for record in common_records:
        if record.get("comparison_treatment") != "common_cancelled":
            continue
        actual = bool(record.get("delta_contribution_se_minus_sol_exactly_zero"))
        checks.append(
            (
                f"common_cost_exact_cancellation::{record.get('input_id')}",
                actual,
                True,
                None,
                None,
                "OK" if actual else "FAIL",
                "Approved common-cost cancellation is exactly zero in the paired delta.",
            )
        )

    normalized_pairs = (
        (
            "lifecycle_cost_delta",
            fields.pv_cost_se,
            fields.pv_cost_sol,
            fields.delta_cost,
        ),
        (
            "equivalent_annual_cost_delta",
            fields.ea_cost_se,
            fields.ea_cost_sol,
            fields.delta_ea_cost,
        ),
        (
            "lifecycle_energy_delta",
            fields.pv_energy_se,
            fields.pv_energy_sol,
            fields.delta_energy,
        ),
        (
            "equivalent_annual_energy_delta",
            fields.ea_energy_se,
            fields.ea_energy_sol,
            fields.delta_ea_energy,
        ),
    )
    for check_name, se_name, sol_name, delta_name in normalized_pairs:
        if not all(name in calculation.by_name for name in (se_name, sol_name, delta_name)):
            continue
        se_values = np.asarray(calculation.by_name[se_name], dtype=np.float64)
        sol_values = np.asarray(calculation.by_name[sol_name], dtype=np.float64)
        delta_values = np.asarray(calculation.by_name[delta_name], dtype=np.float64)
        finite = np.isfinite(se_values) & np.isfinite(sol_values) & np.isfinite(delta_values)
        maximum = float(
            np.max(np.abs((se_values[finite] - sol_values[finite]) - delta_values[finite]))
        ) if finite.any() else 0.0
        checks.append(
            _numeric_check(
                check_name,
                maximum,
                0.0,
                tolerance=1e-12,
                notes="Signed SE-minus-SOL normalized delta ties to component columns.",
            )
        )

    delta_cost = np.asarray(
        calculation.by_name[fields.delta_cost],
        dtype=np.float64,
    )
    delta_energy = np.asarray(
        calculation.by_name[fields.delta_energy],
        dtype=np.float64,
    )
    delta_ea_cost = np.asarray(
        calculation.by_name[fields.delta_ea_cost],
        dtype=np.float64,
    )
    delta_ea_energy = np.asarray(
        calculation.by_name[fields.delta_ea_energy],
        dtype=np.float64,
    )
    lcoo = np.asarray(
        calculation.by_name[fields.lcoo],
        dtype=np.float64,
    )
    crf = np.asarray(
        calculation.by_name["CapitalRecoveryFactor_per_year"],
        dtype=np.float64,
    )
    lifecycle_ratio_mask = (
        np.isfinite(lcoo)
        & np.isfinite(delta_cost)
        & np.isfinite(delta_energy)
        & (delta_energy != 0)
    )
    lifecycle_ratio_error = (
        float(np.max(np.abs(lcoo[lifecycle_ratio_mask] - delta_cost[lifecycle_ratio_mask] / delta_energy[lifecycle_ratio_mask])))
        if lifecycle_ratio_mask.any()
        else 0.0
    )
    checks.append(
        _numeric_check(
            "lcoo_lifecycle_ratio",
            lifecycle_ratio_error,
            0.0,
            tolerance=1e-12,
            notes="Every finite LCOO equals lifecycle cost delta divided by lifecycle energy delta.",
        )
    )
    annual_ratio_mask = (
        np.isfinite(lcoo)
        & np.isfinite(delta_ea_cost)
        & np.isfinite(delta_ea_energy)
        & (delta_ea_energy != 0)
    )
    annual_ratio_error = (
        float(np.max(np.abs(lcoo[annual_ratio_mask] - delta_ea_cost[annual_ratio_mask] / delta_ea_energy[annual_ratio_mask])))
        if annual_ratio_mask.any()
        else 0.0
    )
    checks.append(
        _numeric_check(
            "lcoo_equivalent_annual_ratio",
            annual_ratio_error,
            0.0,
            tolerance=1e-12,
            notes="Every finite LCOO also equals the equivalent-annual cost/energy ratio.",
        )
    )
    for check_name, annual_values, lifecycle_values in (
        ("crf_cost_delta_transform", delta_ea_cost, delta_cost),
        ("crf_energy_delta_transform", delta_ea_energy, delta_energy),
    ):
        finite = np.isfinite(annual_values) & np.isfinite(lifecycle_values) & np.isfinite(crf)
        maximum = (
            float(np.max(np.abs(annual_values[finite] - crf[finite] * lifecycle_values[finite])))
            if finite.any()
            else 0.0
        )
        checks.append(
            _numeric_check(
                check_name,
                maximum,
                0.0,
                tolerance=1e-12,
                notes="Equivalent-annual signed delta equals CRF times its lifecycle delta.",
            )
        )

    for system, cost_name, energy_name, lcoe_name in (
        (
            "solectria",
            fields.pv_cost_sol,
            fields.pv_energy_sol,
            fields.lcoe_sol,
        ),
        (
            "solaredge",
            fields.pv_cost_se,
            fields.pv_energy_se,
            fields.lcoe_se,
        ),
    ):
        lifecycle_cost = np.asarray(calculation.by_name[cost_name], dtype=np.float64)
        lifecycle_energy = np.asarray(calculation.by_name[energy_name], dtype=np.float64)
        lcoe_values = np.asarray(calculation.by_name[lcoe_name], dtype=np.float64)
        ratio_mask = (
            np.isfinite(lifecycle_cost)
            & np.isfinite(lifecycle_energy)
            & np.isfinite(lcoe_values)
            & (lifecycle_energy != 0)
        )
        ratio_error = (
            float(
                np.max(
                    np.abs(
                        lcoe_values[ratio_mask]
                        - lifecycle_cost[ratio_mask] / lifecycle_energy[ratio_mask]
                    )
                )
            )
            if ratio_mask.any()
            else 0.0
        )
        checks.append(
            _numeric_check(
                f"lcoe_lifecycle_ratio::{system}",
                ratio_error,
                0.0,
                tolerance=_binary64_tie_out_tolerance(lcoe_values),
                notes="Standalone lifecycle LCOE equals lifecycle cost divided by lifecycle energy.",
            )
        )

    for check_name, annual_name, lifecycle_name in (
        (
            "crf_cost_transform::solectria",
            fields.ea_cost_sol,
            fields.pv_cost_sol,
        ),
        (
            "crf_cost_transform::solaredge",
            fields.ea_cost_se,
            fields.pv_cost_se,
        ),
        (
            "crf_energy_transform::solectria",
            fields.ea_energy_sol,
            fields.pv_energy_sol,
        ),
        (
            "crf_energy_transform::solaredge",
            fields.ea_energy_se,
            fields.pv_energy_se,
        ),
    ):
        annual_values = np.asarray(calculation.by_name[annual_name], dtype=np.float64)
        lifecycle_values = np.asarray(
            calculation.by_name[lifecycle_name], dtype=np.float64
        )
        finite = (
            np.isfinite(annual_values)
            & np.isfinite(lifecycle_values)
            & np.isfinite(crf)
        )
        maximum = (
            float(
                np.max(
                    np.abs(
                        annual_values[finite]
                        - crf[finite] * lifecycle_values[finite]
                    )
                )
            )
            if finite.any()
            else 0.0
        )
        checks.append(
            _numeric_check(
                check_name,
                maximum,
                0.0,
                tolerance=_binary64_tie_out_tolerance(annual_values),
                notes="Standalone equivalent-annual authority equals CRF times lifecycle authority.",
            )
        )

    energy_class = np.asarray(calculation.by_name["energy_class"])
    lcoo_reason = np.asarray(calculation.by_name["lcoo_unavailable_reason"])
    zero_mask = energy_class == "zero_lifecycle_gain"
    zero_violations = int(
        np.count_nonzero(
            zero_mask
            & (
                np.isfinite(lcoo)
                | (lcoo_reason != "zero_lifecycle_delta_energy")
            )
        )
    )
    checks.append(
        _numeric_check(
            "zero_energy_lcoo_null_and_reason",
            zero_violations,
            0,
            tolerance=0.0,
            notes="Every zero-energy-change row retains null LCOO and the explicit zero-delta reason.",
        )
    )
    negative_mask = energy_class == "negative_lifecycle_gain"
    retained_negative = int(
        np.count_nonzero(
            negative_mask & np.isfinite(lcoo) & (lcoo_reason == None)  # noqa: E711
        )
    )
    checks.append(
        _numeric_check(
            "negative_energy_signed_lcoo_retention",
            retained_negative,
            int(np.count_nonzero(negative_mask)),
            tolerance=0.0,
            notes="Every negative lifecycle-energy row retains its finite signed LCOO with no unavailable reason.",
        )
    )

    for summary_name in ("energy_classes", "tradeoff_classes"):
        class_summary = summaries.get(summary_name)
        if not isinstance(class_summary, Mapping) or "counts" not in class_summary:
            continue
        total = sum(int(value) for value in (class_summary.get("counts") or {}).values())
        checks.append(
            _numeric_check(
                f"class_count_total::{summary_name}",
                total,
                calculation.row_count,
                tolerance=0.0,
                notes="Every realization is retained in exactly one reported outcome class.",
            )
        )

    raw_pairs = (
        ("site_raw_cost_sol", "PVCost_SOL_USD", fields.pv_cost_sol, "solectria"),
        ("site_raw_cost_se", "PVCost_SE_USD", fields.pv_cost_se, "solaredge"),
        ("site_raw_energy_sol", "PVEnergy_SOL_kWh_AC", fields.pv_energy_sol, "solectria"),
        ("site_raw_energy_se", "PVEnergy_SE_kWh_AC", fields.pv_energy_se, "solaredge"),
    )
    for check_name, raw_name, normalized_name, system in raw_pairs:
        if raw_name not in calculation.by_name:
            continue
        denominator_w = float(
            applied_capacity_authority[system].get("applied_capacity_w")
            if applied_capacity_contract
            else (snapshot_systems.get(system) or {}).get("installed_wdc")
        )
        raw_values = np.asarray(calculation.by_name[raw_name], dtype=np.float64)
        normalized_values = np.asarray(calculation.by_name[normalized_name], dtype=np.float64)
        maximum = float(
            np.max(np.abs(raw_values / denominator_w - normalized_values))
        )
        checks.append(
            _numeric_check(
                check_name,
                maximum,
                0.0,
                tolerance=1e-12,
                notes=(
                    "Raw site total divided by the frozen applied capacity ties "
                    "to normalized authority."
                    if applied_capacity_contract
                    else "Raw site total divided by frozen system Wdc ties to normalized authority."
                ),
            )
        )

    for check_name, delta_name, se_name, sol_name in (
        (
            "site_raw_lifecycle_cost_delta",
            "DeltaPVCostUSD_se_minus_sol",
            "PVCost_SE_USD",
            "PVCost_SOL_USD",
        ),
        (
            "site_raw_lifecycle_energy_delta",
            "DeltaPVEnergyKWhAC_se_minus_sol",
            "PVEnergy_SE_kWh_AC",
            "PVEnergy_SOL_kWh_AC",
        ),
        (
            "reference_raw_lifecycle_cost_delta",
            "ReferenceDeltaPVCostUSD_se_minus_sol",
            "ReferencePVCost_SE_USD",
            "ReferencePVCost_SOL_USD",
        ),
        (
            "reference_raw_lifecycle_energy_delta",
            "ReferenceDeltaPVEnergyKWhAC_se_minus_sol",
            "ReferencePVEnergy_SE_kWh_AC",
            "ReferencePVEnergy_SOL_kWh_AC",
        ),
    ):
        if not all(name in calculation.by_name for name in (delta_name, se_name, sol_name)):
            continue
        delta_values = np.asarray(calculation.by_name[delta_name], dtype=np.float64)
        se_values = np.asarray(calculation.by_name[se_name], dtype=np.float64)
        sol_values = np.asarray(calculation.by_name[sol_name], dtype=np.float64)
        finite = np.isfinite(delta_values) & np.isfinite(se_values) & np.isfinite(sol_values)
        maximum = (
            float(np.max(np.abs(delta_values[finite] - (se_values[finite] - sol_values[finite]))))
            if finite.any()
            else 0.0
        )
        tolerance = _binary64_tie_out_tolerance(
            delta_values[finite],
            se_values[finite],
            sol_values[finite],
        )
        checks.append(
            _numeric_check(
                check_name,
                maximum,
                0.0,
                tolerance=tolerance,
                notes="Explicit raw SE-minus-SOL delta ties within a scale-aware binary64 roundoff bound.",
            )
        )

    reference_wdc = (submission_provenance.get("commercial_reference_design") or {}).get(
        "reference_wdc"
    )
    if reference_wdc is not None:
        for check_name, raw_name, normalized_name in (
            ("reference_raw_cost_sol", "ReferencePVCost_SOL_USD", fields.pv_cost_sol),
            ("reference_raw_cost_se", "ReferencePVCost_SE_USD", fields.pv_cost_se),
            ("reference_raw_energy_sol", "ReferencePVEnergy_SOL_kWh_AC", fields.pv_energy_sol),
            ("reference_raw_energy_se", "ReferencePVEnergy_SE_kWh_AC", fields.pv_energy_se),
        ):
            if raw_name not in calculation.by_name:
                continue
            raw_values = np.asarray(calculation.by_name[raw_name], dtype=np.float64)
            normalized_values = np.asarray(calculation.by_name[normalized_name], dtype=np.float64)
            maximum = float(
                np.max(np.abs(raw_values / float(reference_wdc) - normalized_values))
            )
            checks.append(
                _numeric_check(
                    check_name,
                    maximum,
                    0.0,
                    tolerance=1e-12,
                    notes="Commercial reference total divided by declared reference Wdc ties out.",
                )
            )
    return checks


def _build_tables(
    calculation: _SealedCalculation,
    request_payload: Mapping[str, Any],
    source_snapshot: Mapping[str, Any],
    submission_provenance: Mapping[str, Any],
    routine_result: Mapping[str, Any],
    checks: Sequence[Sequence[Any]],
) -> tuple[_Table, ...]:
    source_snapshot_sha256 = str(submission_provenance.get("source_snapshot_sha256"))
    common_records = calculation.metadata.get("common_cost_audit") or []
    applied_capacity_contract = (
        routine_result.get("calculation_contract_version")
        == technoeconomic_kernel.CALCULATION_CONTRACT_VERSION
    )
    return (
        _Table(
            "realizations.csv",
            "Realizations",
            calculation.column_names,
            calculation.rows,
        ),
        _Table(
            "input-specifications.csv",
            "Input Specifications",
            APPLIED_INPUT_COLUMNS if applied_capacity_contract else INPUT_COLUMNS,
            lambda: _input_rows(
                request_payload,
                submission_provenance,
                applied_capacity_contract=applied_capacity_contract,
            ),
        ),
        _Table(
            "energy-snapshot.csv",
            "Energy Snapshot",
            ENERGY_COLUMNS,
            lambda: _energy_rows(source_snapshot, source_snapshot_sha256),
        ),
        _Table(
            "capacity-and-basis.csv",
            "Capacity and Basis",
            (
                APPLIED_CAPACITY_COLUMNS
                if applied_capacity_contract
                else CAPACITY_COLUMNS
            ),
            lambda: _capacity_rows(
                source_snapshot,
                submission_provenance,
                routine_result,
                applied_capacity_contract=applied_capacity_contract,
            ),
        ),
        _Table(
            "common-cost-audit.csv",
            "Common-Cost Audit",
            COMMON_COST_COLUMNS,
            lambda: _common_cost_rows(common_records),
        ),
        _Table(
            "commercial-transfer.csv",
            "Commercial Transfer",
            TRANSFER_COLUMNS,
            lambda: _transfer_rows(request_payload, submission_provenance),
        ),
        _Table(
            "metric-cdfs.csv",
            "Metric CDFs",
            CDF_COLUMNS,
            lambda: _cdf_rows(calculation.metadata),
        ),
        _Table(
            "per-year-summary.csv",
            "Per-Year Summary",
            _per_year_columns(calculation.metadata),
            lambda: _per_year_rows(calculation.metadata),
        ),
        _Table(
            "sensitivity.csv",
            "Sensitivity",
            SENSITIVITY_COLUMNS,
            lambda: _sensitivity_rows(calculation.metadata),
        ),
        _Table(
            "convergence.csv",
            "Convergence",
            CONVERGENCE_COLUMNS,
            lambda: _convergence_rows(calculation.metadata),
        ),
        _Table(
            "provenance.csv",
            "Provenance",
            PROVENANCE_COLUMNS,
            lambda: _provenance_rows(
                request_payload,
                source_snapshot,
                submission_provenance,
                routine_result,
                calculation.metadata,
            ),
        ),
        _Table(
            "checks.csv",
            "Checks",
            CHECK_COLUMNS,
            lambda: iter(checks),
        ),
    )


def _csv_scalar(value: Any) -> str:
    value = _numpy_scalar(value)
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            return ""
        return repr(value)
    if isinstance(value, (Mapping, list, tuple)):
        return _canonical_json_text(_safe_public_value(value))
    text = str(value)
    if text.startswith(("=", "+", "-", "@")):
        return "'" + text
    return text


def _write_csv_table(
    path: Path,
    table: _Table,
    cancellation_check: Callable[[], None],
) -> dict[str, Any]:
    row_count = 0
    with path.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n", quoting=csv.QUOTE_MINIMAL)
        writer.writerow(table.columns)
        for row_count, row in enumerate(table.rows_factory(), start=1):
            if len(row) != len(table.columns):
                raise TechnoeconomicExportError(
                    f"Export table {table.filename} produced an inconsistent row width"
                )
            if row_count % _CANCEL_INTERVAL == 0:
                cancellation_check()
            writer.writerow([_csv_scalar(value) for value in row])
        handle.flush()
        os.fsync(handle.fileno())
    return {
        "filename": table.filename,
        "row_count": row_count,
        "column_count": len(table.columns),
        "sha256": _sha256_file(path),
    }


def _zip_info(filename: str, *, nested: bool = False) -> zipfile.ZipInfo:
    if nested:
        member = PurePosixPath(filename)
        if (
            member.is_absolute()
            or not member.parts
            or any(part in {"", ".", ".."} for part in member.parts)
            or "\\" in filename
            or ":" in filename
        ):
            raise TechnoeconomicExportError("Unsafe archive member name")
        safe_name = member.as_posix()
    else:
        safe_name = _safe_filename(filename)
    info = zipfile.ZipInfo(safe_name, date_time=_FIXED_ZIP_TIME)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = 0o600 << 16
    info.flag_bits |= 0x800
    return info


def _copy_with_cancellation(
    source: Any,
    destination: Any,
    cancellation_check: Callable[[], None],
    *,
    block_size: int = 1024 * 1024,
) -> None:
    while True:
        block = source.read(block_size)
        if not block:
            return
        destination.write(block)
        cancellation_check()


def _write_csv_bundle(
    target: Path,
    staging_directory: Path,
    tables: Sequence[_Table],
    cancellation_check: Callable[[], None],
    *,
    schema_versions: Mapping[str, str] | None = None,
) -> tuple[list[dict[str, Any]], int]:
    schema_versions = schema_versions or export_contract_versions(
        technoeconomic_kernel.LEGACY_CALCULATION_CONTRACT_VERSION
    )
    staging_directory.mkdir(parents=False, exist_ok=False)
    metadata: list[dict[str, Any]] = []
    try:
        for table in tables:
            cancellation_check()
            metadata.append(
                _write_csv_table(
                    staging_directory / _safe_filename(table.filename),
                    table,
                    cancellation_check,
                )
            )
        bundle_metadata = {
            "schema_version": schema_versions["csv_bundle"],
            "csv_format_version": schema_versions["csv_format"],
            "encoding": "UTF-8",
            "line_terminator": "LF",
            "float_format": "Python finite-float repr (shortest round-trip binary64)",
            "null_format": "empty field",
            "table_count": len(metadata),
            "tables": metadata,
        }
        manifest_bytes = (
            _canonical_json_text(bundle_metadata) + "\n"
        ).encode("utf-8")
        with zipfile.ZipFile(
            target,
            mode="x",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=9,
            strict_timestamps=True,
        ) as archive:
            archive.writestr(
                _zip_info(schema_versions["csv_bundle_manifest_filename"]),
                manifest_bytes,
            )
            for table_metadata in metadata:
                cancellation_check()
                source = staging_directory / table_metadata["filename"]
                with source.open("rb") as source_handle, archive.open(
                    _zip_info(table_metadata["filename"]), "w"
                ) as destination:
                    _copy_with_cancellation(
                        source_handle,
                        destination,
                        cancellation_check,
                    )
    finally:
        shutil.rmtree(staging_directory, ignore_errors=True)
    return metadata, sum(int(record["row_count"]) for record in metadata)


_THIN_GREY = Side(style="thin", color="D8DEE5")
_HEADER_FILL = PatternFill("solid", fgColor="1F4E78")
_SECTION_FILL = PatternFill("solid", fgColor="D9EAF7")
_PASS_FILL = PatternFill("solid", fgColor="DDEBF7")
_FAIL_FILL = PatternFill("solid", fgColor="FCE4D6")
_FAST_STREAMING_SHEETS = frozenset({"Realizations", "Metric CDFs"})


def _excel_value(value: Any) -> Any:
    value = _numpy_scalar(value)
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, (Mapping, list, tuple)):
        return _canonical_json_text(_safe_public_value(value))
    return value


def _write_only_cell(
    sheet: Any,
    value: Any,
    *,
    header: bool = False,
    section: bool = False,
    status: str | None = None,
    number_format: str | None = None,
) -> WriteOnlyCell:
    excel_value = _excel_value(value)
    if isinstance(excel_value, str) and len(excel_value) > 32_767:
        raise TechnoeconomicExportError(
            "An export value exceeds the lossless XLSX cell limit"
        )
    cell = WriteOnlyCell(sheet, value=excel_value)
    cell.alignment = Alignment(
        vertical="top",
        wrap_text=isinstance(value, str) and len(value) > 35,
    )
    if header:
        cell.fill = _HEADER_FILL
        cell.font = Font(name="Aptos", size=10, bold=True, color="FFFFFF")
        cell.alignment = Alignment(vertical="center", wrap_text=True)
        cell.border = Border(bottom=_THIN_GREY)
    elif section:
        cell.fill = _SECTION_FILL
        cell.font = Font(name="Aptos", size=10, bold=True, color="1F1F1F")
    else:
        cell.font = Font(name="Aptos", size=10, color="000000")
        cell.border = Border(bottom=Side(style="hair", color="E7EBEF"))
    if status == "OK":
        cell.fill = _PASS_FILL
        cell.font = Font(name="Aptos", size=10, bold=True, color="1F1F1F")
    elif status == "FAIL":
        cell.fill = _FAIL_FILL
        cell.font = Font(name="Aptos", size=10, bold=True, color="9C0006")
    if number_format:
        cell.number_format = number_format
    if isinstance(value, str) and value.startswith(("=", "+", "-", "@")):
        cell.data_type = "s"
    return cell


def _fast_streaming_value(sheet: Any, value: Any) -> Any:
    """Return an allocation-light value for very large write-only sheets."""

    excel_value = _excel_value(value)
    if isinstance(excel_value, str) and len(excel_value) > 32_767:
        raise TechnoeconomicExportError(
            "An export value exceeds the lossless XLSX cell limit"
        )
    if isinstance(excel_value, str) and excel_value.startswith(("=", "+", "-", "@")):
        cell = WriteOnlyCell(sheet, value=excel_value)
        cell.data_type = "s"
        return cell
    return excel_value


def _apply_fast_streaming_formats(sheet: Any, columns: Sequence[str]) -> None:
    """Apply numeric display formats once per column, not once per body cell."""

    sheet.sheet_view.showGridLines = True
    for index, header in enumerate(columns, start=1):
        number_format = _number_format_for_header(str(header), 0.0)
        if number_format:
            letter = openpyxl.utils.get_column_letter(index)
            sheet.column_dimensions[letter].number_format = number_format


def _number_format_for_header(header: str, value: Any) -> str | None:
    if not isinstance(value, (int, float, np.integer, np.floating)) or isinstance(
        value, (bool, np.bool_)
    ):
        return None
    lowered = header.lower()
    if (
        lowered.endswith(("probability", "share", "rate"))
        or "_probability" in lowered
        or "_share" in lowered
        or "_relative_change" in lowered
        or "discount-rate" in lowered
        or "degradation" in lowered
    ):
        return "0.0000%"
    if "count" in lowered or header in {"year", "realization_index", "entry_order"}:
        return "#,##0"
    return "0.###############"


def _set_sheet_layout(sheet: Any, columns: Sequence[str]) -> None:
    sheet.sheet_view.showGridLines = False
    sheet.freeze_panes = "A2"
    for index, header in enumerate(columns, start=1):
        letter = openpyxl.utils.get_column_letter(index)
        normalized = str(header).lower()
        if normalized == "check_id" or normalized.endswith("field_path"):
            width = 60.0
        elif normalized.endswith("_provenance_path"):
            width = 58.0
        elif normalized in {"value_json", "notes"} or normalized.endswith(
            "value_json"
        ):
            width = 58.0
        elif normalized == "metric_id":
            width = 54.0
        elif normalized in {"label", "response_id", "predictor_id"}:
            width = 42.0
        elif normalized in {"reason", "exclusion_reason"}:
            width = 36.0
        elif normalized.endswith("_sha256"):
            width = 68.0
        elif normalized == "record_type":
            width = 34.0
        elif normalized in {"analysis_basis", "module_model"}:
            width = 28.0
        elif normalized in {"capacity_basis", "rating_basis"}:
            width = 34.0
        elif normalized.endswith("_json"):
            width = 45.0
        elif normalized in {
            "value",
            "p5",
            "p50",
            "p95",
            "p5_absolute_change",
            "p5_relative_change",
            "p50_absolute_change",
            "p50_relative_change",
            "p95_absolute_change",
            "p95_relative_change",
        }:
            width = 22.0
        elif normalized in {
            "actual_authority",
            "expected_authority",
            "difference_authority",
        }:
            width = 34.0
        elif normalized == "display_formula_status":
            width = 24.0
        else:
            width = min(42.0, max(16.0, len(str(header)) * 0.9 + 2.0))
        sheet.column_dimensions[letter].width = width


def _append_header(sheet: Any, columns: Sequence[str]) -> None:
    sheet.append([_write_only_cell(sheet, value, header=True) for value in columns])


def _update_logical_sheet_hash(
    digest: Any,
    values: Sequence[Any],
    *,
    formula_indexes: frozenset[int] = frozenset(),
) -> None:
    row = {
        "values": [_excel_value(value) for value in values],
        "formula_indexes": sorted(formula_indexes),
    }
    digest.update((_canonical_json_text(row) + "\n").encode("utf-8"))


def _new_logical_sheet_hash() -> Any:
    digest = hashlib.sha256()
    digest.update((XLSX_LOGICAL_HASH_VERSION + "\n").encode("ascii"))
    return digest


def _write_summary_sheet(
    workbook: openpyxl.Workbook,
    routine_result: Mapping[str, Any],
    metadata: Mapping[str, Any],
    checks: Sequence[Sequence[Any]],
) -> tuple[int, int, str]:
    sheet = workbook.create_sheet("Summary")
    logical_digest = _new_logical_sheet_hash()
    sheet.sheet_view.showGridLines = False
    sheet.freeze_panes = "A5"
    for letter, width in {"A": 68, "B": 68, "C": 28, "D": 58}.items():
        sheet.column_dimensions[letter].width = width
    title = _write_only_cell(sheet, "Probabilistic Technoeconomic Analysis", section=True)
    title.font = Font(name="Aptos Display", size=18, bold=True, color="FFFFFF")
    title.fill = _HEADER_FILL
    sheet.append([title, _write_only_cell(sheet, None), _write_only_cell(sheet, None), _write_only_cell(sheet, None)])
    _update_logical_sheet_hash(
        logical_digest,
        ("Probabilistic Technoeconomic Analysis", None, None, None),
    )
    sheet.append(
        [
            _write_only_cell(sheet, "Frozen numeric values are authoritative; formulas are display aids."),
            _write_only_cell(sheet, None),
            _write_only_cell(sheet, None),
            _write_only_cell(sheet, "All signed metrics use SolarEdge minus Solectria."),
        ]
    )
    _update_logical_sheet_hash(
        logical_digest,
        (
            "Frozen numeric values are authoritative; formulas are display aids.",
            None,
            None,
            "All signed metrics use SolarEdge minus Solectria.",
        ),
    )
    sheet.append([_write_only_cell(sheet, None) for _ in range(4)])
    _update_logical_sheet_hash(logical_digest, (None, None, None, None))
    _append_header(sheet, ("Frozen authority", "Value", "Display formula/status", "Notes"))
    _update_logical_sheet_hash(
        logical_digest,
        ("Frozen authority", "Value", "Display formula/status", "Notes"),
    )
    all_passed = all(row[5] == "OK" for row in checks)
    check_end_row = len(checks) + 1
    realization_end_row = int(routine_result.get("realization_count") or 0) + 1
    summary_rows = [
        ("Model status", "OK" if all_passed else "FAIL", f"=IF(COUNTIF('Checks'!F2:F{check_end_row},\"FAIL\")=0,\"OK\",\"FAIL\")", "Formula recalculates visible check status."),
        ("Analysis basis", routine_result.get("analysis_basis"), None, "Cost/energy interpretation basis."),
        ("Realizations", routine_result.get("realization_count"), f"=ROWS('Realizations'!A2:A{realization_end_row})", "Sealed LHS realization count."),
        ("Seed", routine_result.get("seed"), None, "Unsigned deterministic seed."),
        ("Project life (years)", routine_result.get("project_life_years"), None, "Constant-real lifecycle horizon."),
        ("Energy status", "available" if routine_result.get("energy_available") else "cost_only", None, "Commercial energy requires approved transfer."),
        ("Commercial transfer status", routine_result.get("commercial_transfer_status"), None, "Bound to immutable submission provenance."),
        ("Source snapshot SHA-256", routine_result.get("source_snapshot_sha256"), None, "Frozen Annual Simulation evidence identity."),
        ("Calculation contract", routine_result.get("calculation_contract_version"), None, "Pinned calculation semantics."),
        ("Sampling version", routine_result.get("sampling_version"), None, "Pinned LHS and weather allocation semantics."),
    ]
    for label, value, formula, notes in summary_rows:
        status = value if label == "Model status" else None
        row = [
            _write_only_cell(sheet, label),
            _write_only_cell(sheet, value, status=status),
            _write_only_cell(sheet, formula),
            _write_only_cell(sheet, notes),
        ]
        if isinstance(formula, str) and formula.startswith("="):
            row[2].data_type = "f"
        sheet.append(row)
        _update_logical_sheet_hash(
            logical_digest,
            (label, value, formula, notes),
            formula_indexes=frozenset({2}) if formula else frozenset(),
        )
    sheet.append([_write_only_cell(sheet, None) for _ in range(4)])
    _update_logical_sheet_hash(logical_digest, (None, None, None, None))
    section = _write_only_cell(sheet, "Metric percentiles (frozen authority)", section=True)
    sheet.append([section, _write_only_cell(sheet, None), _write_only_cell(sheet, None), _write_only_cell(sheet, None)])
    _update_logical_sheet_hash(
        logical_digest,
        ("Metric percentiles (frozen authority)", None, None, None),
    )
    _append_header(sheet, ("Metric", "P5", "P50", "P95"))
    _update_logical_sheet_hash(logical_digest, ("Metric", "P5", "P50", "P95"))
    metric_rows = 0
    for metric_id, summary in sorted(_metric_summaries(metadata).items()):
        if not isinstance(summary, Mapping) or "percentiles" not in summary:
            continue
        percentiles = summary.get("percentiles") or {}
        values = (
            _human_metric(metric_id),
            percentiles.get("p5"),
            percentiles.get("p50"),
            percentiles.get("p95"),
        )
        sheet.append(
            [
                _write_only_cell(
                    sheet,
                    value,
                    number_format=_number_format_for_header(header, value),
                )
                for header, value in zip(("Metric", "P5", "P50", "P95"), values)
            ]
        )
        _update_logical_sheet_hash(logical_digest, values)
        metric_rows += 1
    return len(summary_rows) + metric_rows, 4, logical_digest.hexdigest()


def _write_workbook(
    raw_path: Path,
    tables: Sequence[_Table],
    routine_result: Mapping[str, Any],
    metadata: Mapping[str, Any],
    checks: Sequence[Sequence[Any]],
    cancellation_check: Callable[[], None],
) -> tuple[list[dict[str, Any]], int]:
    workbook = openpyxl.Workbook(write_only=True)
    workbook.properties.creator = "SBE PV technoeconomic reporting"
    workbook.properties.title = "Probabilistic Technoeconomic Analysis"
    workbook.properties.subject = "Frozen simulation results and export tie-outs"
    fixed_time = datetime(1980, 1, 1)
    workbook.properties.created = fixed_time
    workbook.properties.modified = fixed_time
    workbook.calculation.fullCalcOnLoad = True
    workbook.calculation.forceFullCalc = True
    workbook.calculation.calcMode = "auto"

    sheets: list[dict[str, Any]] = []
    summary_rows, summary_columns, summary_logical_sha256 = _write_summary_sheet(
        workbook,
        routine_result,
        metadata,
        checks,
    )
    sheets.append(
        {
            "sheet_name": "Summary",
            "row_count": summary_rows,
            "column_count": summary_columns,
            "logical_sha256": summary_logical_sha256,
            "logical_hash_version": XLSX_LOGICAL_HASH_VERSION,
        }
    )
    for table in tables:
        cancellation_check()
        sheet = workbook.create_sheet(table.sheet_name)
        workbook_columns = (
            table.columns + ("display_formula_status",)
            if table.sheet_name == "Checks"
            else table.columns
        )
        _set_sheet_layout(sheet, workbook_columns)
        fast_streaming = table.sheet_name in _FAST_STREAMING_SHEETS
        if fast_streaming:
            _apply_fast_streaming_formats(sheet, workbook_columns)
        _append_header(sheet, workbook_columns)
        logical_digest = _new_logical_sheet_hash()
        _update_logical_sheet_hash(logical_digest, workbook_columns)
        row_count = 0
        for row_count, raw_row in enumerate(table.rows_factory(), start=1):
            if len(raw_row) != len(table.columns):
                raise TechnoeconomicExportError(
                    f"Workbook table {table.sheet_name} produced an inconsistent row width"
                )
            if row_count % _CANCEL_INTERVAL == 0:
                cancellation_check()
            if fast_streaming:
                cells = [
                    _fast_streaming_value(sheet, value) for value in raw_row
                ]
            else:
                cells = [
                    _write_only_cell(
                        sheet,
                        value,
                        status=(value if header == "status_authority" else None),
                        number_format=_number_format_for_header(header, value),
                    )
                    for header, value in zip(table.columns, raw_row)
                ]
            if table.sheet_name == "Checks":
                excel_row = row_count + 1
                formula = (
                    f'=IF(OR(ISTEXT(B{excel_row}),ISTEXT(C{excel_row})),'
                    f'IF(B{excel_row}=C{excel_row},"OK","FAIL"),'
                    f'IF(ABS(B{excel_row}-C{excel_row})<=E{excel_row},"OK","FAIL"))'
                )
                formula_cell = _write_only_cell(sheet, formula)
                formula_cell.data_type = "f"
                cells.append(formula_cell)
            sheet.append(cells)
            logical_values = list(raw_row)
            formula_indexes = frozenset()
            if table.sheet_name == "Checks":
                logical_values.append(formula)
                formula_indexes = frozenset({len(logical_values) - 1})
            _update_logical_sheet_hash(
                logical_digest,
                logical_values,
                formula_indexes=formula_indexes,
            )
        if len(workbook_columns) <= 200:
            sheet.auto_filter.ref = (
                f"A1:{openpyxl.utils.get_column_letter(len(workbook_columns))}{row_count + 1}"
            )
        sheets.append(
            {
                "sheet_name": table.sheet_name,
                "row_count": row_count,
                "column_count": len(workbook_columns),
                "logical_sha256": logical_digest.hexdigest(),
                "logical_hash_version": XLSX_LOGICAL_HASH_VERSION,
            }
        )
    workbook.save(raw_path)
    return sheets, sum(int(record["row_count"]) for record in sheets)


def _normalize_xlsx_archive(
    source: Path,
    target: Path,
    cancellation_check: Callable[[], None],
) -> None:
    with zipfile.ZipFile(source, "r") as incoming, zipfile.ZipFile(
        target,
        "x",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
        strict_timestamps=True,
    ) as outgoing:
        for name in sorted(incoming.namelist()):
            info = _zip_info(name, nested=True)
            with incoming.open(name, "r") as source_handle, outgoing.open(
                info, "w"
            ) as target_handle:
                _copy_with_cancellation(
                    source_handle,
                    target_handle,
                    cancellation_check,
                )


def _human_metric(
    value: str,
    *,
    applied_capacity_contract: bool = False,
) -> str:
    normalized_capacity_label = (
        "applied W" if applied_capacity_contract else "Wdc"
    )
    replacements = {
        technoeconomic_kernel.FIELD_LCOE_SOL: "Solectria lifecycle LCOE (USD/kWh_AC)",
        technoeconomic_kernel.FIELD_LCOE_SE: "SolarEdge lifecycle LCOE (USD/kWh_AC)",
        technoeconomic_kernel.FIELD_DELTA_COST: "Lifecycle cost delta, SE − SOL (USD/Wdc)",
        technoeconomic_kernel.FIELD_DELTA_ENERGY: "Lifecycle energy delta, SE − SOL (kWh_AC/Wdc)",
        technoeconomic_kernel.FIELD_DELTA_EA_COST: "Equivalent-annual cost delta, SE − SOL (USD/Wdc-year)",
        technoeconomic_kernel.FIELD_DELTA_EA_ENERGY: "Equivalent-annual energy delta, SE − SOL (kWh_AC/Wdc-year)",
        technoeconomic_kernel.APPLIED_FIELD_DELTA_COST: "Lifecycle cost delta, SE − SOL (USD/applied W)",
        technoeconomic_kernel.APPLIED_FIELD_DELTA_ENERGY: "Lifecycle energy delta, SE − SOL (kWh_AC/applied W)",
        technoeconomic_kernel.APPLIED_FIELD_DELTA_EA_COST: "Equivalent-annual cost delta, SE − SOL (USD/applied W-year)",
        technoeconomic_kernel.APPLIED_FIELD_DELTA_EA_ENERGY: "Equivalent-annual energy delta, SE − SOL (kWh_AC/applied W-year)",
        "headline_positive_gain_lcoo": "Headline LCOO, SE − SOL (USD/kWh_AC; positive gain)",
        "signed_nonzero_lcoo": "Signed LCOO diagnostic, SE − SOL (USD/kWh_AC)",
        "lifecycle_lcoe_solectria": "Solectria lifecycle LCOE (USD/kWh_AC)",
        "lifecycle_lcoe_solaredge": "SolarEdge lifecycle LCOE (USD/kWh_AC)",
        "lifecycle_cost_delta_se_minus_sol": (
            "Lifecycle cost delta, SE − SOL "
            f"(USD/{normalized_capacity_label})"
        ),
        "lifecycle_energy_delta_se_minus_sol": (
            "Lifecycle energy delta, SE − SOL "
            f"(kWh_AC/{normalized_capacity_label})"
        ),
        "headline_positive_gain_lcoo_se_minus_sol": "Headline LCOO, SE − SOL (USD/kWh_AC)",
    }
    return replacements.get(value, value.replace("_", " "))


def _plot_grid(count: int) -> tuple[int, int]:
    columns = 2 if count <= 6 else 3
    rows = max(1, math.ceil(max(1, count) / columns))
    return rows, columns


def _figure_axes(count: int, *, title: str, subtitle: str) -> tuple[Any, list[Any]]:
    from matplotlib import pyplot as plt

    rows, columns = _plot_grid(count)
    figure, axes = plt.subplots(rows, columns, figsize=(16, 10), squeeze=False)
    figure.patch.set_facecolor("white")
    figure.suptitle(title, x=0.04, y=0.98, ha="left", fontsize=17, fontweight="bold", color=_INK)
    figure.text(0.04, 0.945, subtitle, ha="left", va="top", fontsize=10, color="#55616D")
    flattened = list(axes.flat)
    for axis in flattened:
        axis.set_facecolor("white")
        axis.grid(axis="y", color=_GRID, linewidth=0.8)
        axis.spines[["top", "right"]].set_visible(False)
        axis.spines[["left", "bottom"]].set_color("#8B96A1")
        axis.tick_params(labelsize=8, colors=_INK)
    return figure, flattened


def _save_figure(figure: Any, path: Path) -> tuple[int, int]:
    from matplotlib import pyplot as plt

    figure.tight_layout(rect=(0.035, 0.035, 0.98, 0.91), h_pad=2.4, w_pad=1.8)
    figure.savefig(
        path,
        dpi=100,
        facecolor="white",
        metadata={"Software": "SBE PV technoeconomic reporting v1"},
    )
    plt.close(figure)
    return _png_dimensions(path)


def _cdf_display_indices(
    probabilities: np.ndarray,
    *,
    maximum: int = 1200,
) -> np.ndarray:
    count = len(probabilities)
    if count <= maximum:
        return np.arange(count, dtype=np.int64)
    selected = set(np.linspace(0, count - 1, maximum, dtype=np.int64).tolist())
    selected.update({0, count - 1})
    for quantile in (0.05, 0.5, 0.95):
        index = int(np.searchsorted(probabilities, quantile, side="left"))
        for neighbor in (index - 1, index, index + 1):
            if 0 <= neighbor < count:
                selected.add(neighbor)
    return np.asarray(sorted(selected), dtype=np.int64)


def _render_cdf_plot(
    metadata: Mapping[str, Any],
    path: Path,
) -> tuple[int, int, int, int]:
    available: list[tuple[str, Mapping[str, Any]]] = []
    for metric_id, summary in sorted(_metric_summaries(metadata).items()):
        if isinstance(summary, Mapping) and isinstance(summary.get("cdf"), Mapping):
            available.append((metric_id, summary))
    figure, axes = _figure_axes(
        len(available),
        title="Technoeconomic metric empirical CDFs",
        subtitle="Finite metric-specific populations; each panel states its denominator. Signed zero and negative values are retained.",
    )
    point_count = 0
    display_point_count = 0
    if not available:
        axes[0].text(0.5, 0.5, "No finite CDF populations", ha="center", va="center", color=_INK)
        axes[0].set_axis_off()
    for axis, (metric_id, summary) in zip(axes, available):
        cdf = summary["cdf"]
        values = np.asarray(cdf.get("values") or [], dtype=np.float64)
        probability = np.asarray(cdf.get("cumulative_probability") or [], dtype=np.float64)
        point_count += len(values)
        display_indices = _cdf_display_indices(probability)
        display_values = values[display_indices]
        display_probability = probability[display_indices]
        display_point_count += len(display_indices)
        axis.step(display_values, display_probability, where="post", color=_BLUE, linewidth=1.8)
        if len(display_values) <= 100:
            axis.scatter(
                display_values,
                display_probability,
                s=12,
                color="white",
                edgecolor=_BLUE,
                linewidth=0.8,
                zorder=3,
            )
        axis.axhline(0.5, color=_INK, linewidth=0.8, linestyle="--", alpha=0.7)
        axis.set_ylim(0, 1.02)
        axis.set_title(
            f"{_human_metric(metric_id)}\nRight-continuous ECDF • n={cdf.get('population_count')} • plotted {len(display_indices):,} points",
            loc="left",
            fontsize=9.5,
            color=_INK,
        )
        axis.set_xlabel("Metric value", fontsize=8, color=_INK)
        axis.set_ylabel("P(X ≤ x)", fontsize=8, color=_INK)
    for axis in axes[len(available):]:
        axis.set_visible(False)
    width, height = _save_figure(figure, path)
    return width, height, point_count, display_point_count


def _render_sensitivity_plot(
    metadata: Mapping[str, Any],
    path: Path,
) -> tuple[int, int, int, int]:
    models = metadata.get("sensitivity") or {}
    kernel_provenance = metadata.get("kernel_provenance") or {}
    applied_capacity_contract = (
        isinstance(kernel_provenance, Mapping)
        and isinstance(kernel_provenance.get("capacity_normalization"), Mapping)
    )
    entries = list(sorted(models.items()))
    figure, axes = _figure_axes(
        len(entries),
        title="Forward stepwise rank sensitivity",
        subtitle="Incremental R² by entered predictor; panel subtitles state the response-specific sample denominator.",
    )
    step_count = 0
    display_step_count = 0
    for axis, (response_id, model) in zip(axes, entries):
        steps = model.get("steps") or []
        step_count += len(steps)
        display_steps = sorted(
            steps,
            key=lambda step: (
                -float(step.get("incremental_r_squared") or 0.0),
                int(step.get("entry_order") or 0),
                str(step.get("predictor_id")),
            ),
        )[:15]
        display_step_count += len(display_steps)
        axis.set_title(
            f"{_human_metric(response_id, applied_capacity_contract=applied_capacity_contract)}\nstatus={model.get('status')} • n={model.get('sample_count', 0)} • shown {len(display_steps)} of {len(steps)}",
            loc="left",
            fontsize=9.5,
            color=_INK,
        )
        if not display_steps:
            axis.text(
                0.5,
                0.5,
                f"Unavailable: {model.get('reason') or 'no predictors entered'}",
                ha="center",
                va="center",
                fontsize=9,
                color="#55616D",
                wrap=True,
            )
            axis.set_axis_off()
            continue
        labels = [str(step.get("predictor_id")) for step in display_steps]
        values = [float(step.get("incremental_r_squared") or 0.0) for step in display_steps]
        signs = [step.get("sign") for step in display_steps]
        positions = np.arange(len(labels))
        bars = axis.barh(positions, values, color=_BLUE_LIGHT, edgecolor=_BLUE, linewidth=1.0)
        axis.set_yticks(positions, labels=labels)
        axis.invert_yaxis()
        axis.set_xlabel("Incremental R²", fontsize=8, color=_INK)
        axis.set_xlim(left=0)
        for bar, value, sign in zip(bars, values, signs):
            glyph = "+" if sign == "positive" else "−" if sign == "negative" else "0"
            axis.text(
                bar.get_width(),
                bar.get_y() + bar.get_height() / 2,
                f" {value:.4f} ({glyph}β)",
                va="center",
                fontsize=7.5,
                color=_INK,
            )
    for axis in axes[len(entries):]:
        axis.set_visible(False)
    width, height = _save_figure(figure, path)
    return width, height, step_count, display_step_count


def _render_convergence_plot(metadata: Mapping[str, Any], path: Path) -> tuple[int, int, int]:
    convergence = metadata.get("convergence") or {}
    checkpoints = convergence.get("checkpoints") or []
    metric_ids = sorted(
        {
            metric_id
            for checkpoint in checkpoints
            for metric_id in (checkpoint.get("metrics") or {})
        }
    )
    figure, axes = _figure_axes(
        len(metric_ids),
        title="Cumulative convergence diagnostics",
        subtitle=f"Deterministic LHS prefixes; final status={convergence.get('status')}. Bands show cumulative P5–P95.",
    )
    point_count = 0
    for axis, metric_id in zip(axes, metric_ids):
        x_values: list[int] = []
        p5_values: list[float] = []
        p50_values: list[float] = []
        p95_values: list[float] = []
        for checkpoint in checkpoints:
            metric = (checkpoint.get("metrics") or {}).get(metric_id) or {}
            percentiles = metric.get("percentiles") or {}
            if any(percentiles.get(name) is None for name in ("p5", "p50", "p95")):
                continue
            x_values.append(int(checkpoint.get("realization_count")))
            p5_values.append(float(percentiles["p5"]))
            p50_values.append(float(percentiles["p50"]))
            p95_values.append(float(percentiles["p95"]))
        point_count += len(x_values)
        axis.set_title(
            f"{_human_metric(metric_id)}\nfinite population at each cumulative checkpoint",
            loc="left",
            fontsize=9.5,
            color=_INK,
        )
        if x_values:
            axis.fill_between(x_values, p5_values, p95_values, color=_BLUE_LIGHT, alpha=0.45, label="P5–P95")
            axis.plot(x_values, p50_values, color=_BLUE, linewidth=1.8, marker="o", markersize=4, label="P50")
            axis.legend(frameon=False, fontsize=7.5, loc="best")
        else:
            axis.text(0.5, 0.5, "No finite checkpoints", ha="center", va="center", color=_INK)
        axis.set_xlabel("Cumulative realizations", fontsize=8, color=_INK)
        axis.set_ylabel("Metric value", fontsize=8, color=_INK)
    for axis in axes[len(metric_ids):]:
        axis.set_visible(False)
    width, height = _save_figure(figure, path)
    return width, height, point_count


def _png_dimensions(path: Path) -> tuple[int, int]:
    with path.open("rb") as handle:
        header = handle.read(24)
    if len(header) != 24 or header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
        raise TechnoeconomicExportError("Generated plot is not a valid PNG")
    return struct.unpack(">II", header[16:24])


def _artifact_contract_by_id(artifact_id: str) -> Mapping[str, Any]:
    matches = [
        specification
        for specification in api_artifacts.TECHNOECONOMIC_PUBLIC_ARTIFACT_CONTRACT.values()
        if specification.get("artifact_id") == artifact_id
    ]
    if len(matches) != 1:
        raise TechnoeconomicExportError(
            f"Public artifact contract is missing {artifact_id!r}"
        )
    return matches[0]


def _publish_artifact(
    *,
    artifact_id: str,
    pending_path: Path,
    attempt_directory: Path,
    job_id: str,
    cancellation_check: Callable[[], None],
    publish_check: Callable[[], None],
    extra: Mapping[str, Any],
) -> dict[str, Any]:
    contract = _artifact_contract_by_id(artifact_id)
    filename = _safe_filename(str(contract.get("filename")))
    target = attempt_directory / filename
    if target.exists() or target.is_symlink():
        raise TechnoeconomicExportError("An export target already exists")
    with pending_path.open("r+b") as pending_handle:
        pending_handle.flush()
        os.fsync(pending_handle.fileno())
    details = _strict_regular_file(pending_path, label=f"Pending {artifact_id} export")
    byte_count = int(details.st_size)
    if byte_count <= 0:
        raise TechnoeconomicExportError(f"Generated {artifact_id} export is empty")
    digest = _sha256_file(pending_path)
    cancellation_check()
    publish_check()
    pending_path.replace(target)
    published = _strict_regular_file(target, label=f"Published {artifact_id} export")
    if published.st_size != byte_count or not secrets.compare_digest(
        _sha256_file(target), digest
    ):
        target.unlink(missing_ok=True)
        raise TechnoeconomicExportError(
            f"Published {artifact_id} export changed during publication"
        )
    return {
        "schema_version": extra.get("schema_version"),
        "artifact_id": artifact_id,
        "artifact_kind": contract.get("artifact_kind"),
        "owner_workflow": "technoeconomic",
        "owner_job_id": job_id,
        "storage_key": _storage_key(target),
        "filename": filename,
        "media_type": contract.get("media_type"),
        "sha256": digest,
        "byte_count": byte_count,
        "public": True,
        **{key: value for key, value in extra.items() if key != "schema_version"},
    }


def _signed_metric_counts(calculation: _SealedCalculation) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for column_name, raw_values in zip(calculation.column_names, calculation.columns):
        if "Delta" not in column_name and column_name != technoeconomic_kernel.FIELD_LCOO:
            continue
        try:
            values = np.asarray(raw_values, dtype=np.float64)
        except (TypeError, ValueError):
            continue
        finite = values[np.isfinite(values)]
        result[column_name] = {
            "negative_count": int(np.count_nonzero(finite < 0)),
            "zero_count": int(np.count_nonzero(finite == 0)),
            "positive_count": int(np.count_nonzero(finite > 0)),
            "null_count": int(len(values) - len(finite)),
            "row_count": int(len(values)),
        }
    return result


def generate_technoeconomic_exports(
    *,
    job_id: str,
    attempt_directory: Path,
    sealed_calculation_path: Path,
    sealed_calculation_artifact: Mapping[str, Any],
    request_payload: Mapping[str, Any],
    source_snapshot: Mapping[str, Any],
    submission_provenance: Mapping[str, Any],
    routine_result: Mapping[str, Any],
    cancellation_check: Callable[[], None],
    publish_check: Callable[[], None],
) -> dict[str, Any]:
    """Generate, verify, and lease-fence the complete Phase-4 artifact set.

    All filenames are server-owned constants from ``api.artifacts``.  Long tables
    are streamed, and the XLSX ``Realizations`` sheet uses openpyxl write-only mode
    so the allowed 100,000-realization job size does not materialize worksheet
    objects per cell.
    """

    if not isinstance(job_id, str) or not job_id:
        raise TechnoeconomicExportError("Export owner job ID is invalid")
    if not callable(cancellation_check) or not callable(publish_check):
        raise TechnoeconomicExportError("Export lease callbacks are required")
    schema_versions = export_contract_versions(
        str(routine_result.get("calculation_contract_version"))
    )
    cancellation_check()
    attempt_directory = attempt_directory.resolve(strict=True)
    _confined(attempt_directory, config.OUTPUT_DIR.resolve(strict=True), label="Attempt directory")
    calculation = _load_sealed_calculation(
        attempt_directory=attempt_directory,
        sealed_calculation_path=sealed_calculation_path,
        sealed_calculation_artifact=sealed_calculation_artifact,
        request_payload=request_payload,
        source_snapshot=source_snapshot,
        submission_provenance=submission_provenance,
    )
    _verify_routine_result(
        metadata=calculation.metadata,
        routine_result=routine_result,
        request_payload=request_payload,
        source_snapshot=source_snapshot,
        submission_provenance=submission_provenance,
        sealed_calculation_artifact=sealed_calculation_artifact,
    )
    checks = _build_checks(
        calculation,
        source_snapshot,
        submission_provenance,
        routine_result,
    )
    failed_checks = [str(row[0]) for row in checks if row[5] != "OK"]
    if failed_checks:
        raise TechnoeconomicExportError(
            "Export tie-outs failed: " + ", ".join(failed_checks[:5])
        )
    tables = _build_tables(
        calculation,
        request_payload,
        source_snapshot,
        submission_provenance,
        routine_result,
        checks,
    )

    artifacts: dict[str, dict[str, Any]] = {}
    csv_pending = attempt_directory / ".pending-csv.zip"
    workbook_raw = attempt_directory / ".raw-workbook.xlsx"
    workbook_pending = attempt_directory / ".pending-workbook.xlsx"
    cdf_pending = attempt_directory / ".pending-cdf.png"
    sensitivity_pending = attempt_directory / ".pending-sensitivity.png"
    convergence_pending = attempt_directory / ".pending-convergence.png"
    staging = attempt_directory / ".csv-staging"
    temporary_paths = (
        csv_pending,
        workbook_raw,
        workbook_pending,
        cdf_pending,
        sensitivity_pending,
        convergence_pending,
    )
    if any(path.exists() or path.is_symlink() for path in (*temporary_paths, staging)):
        raise TechnoeconomicExportError("The export staging area is not empty")
    try:
        csv_tables, csv_row_count = _write_csv_bundle(
            csv_pending,
            staging,
            tables,
            cancellation_check,
            schema_versions=schema_versions,
        )
        artifacts["csv_bundle"] = _publish_artifact(
            artifact_id="csv_bundle",
            pending_path=csv_pending,
            attempt_directory=attempt_directory,
            job_id=job_id,
            cancellation_check=cancellation_check,
            publish_check=publish_check,
            extra={
                "schema_version": schema_versions["csv_bundle"],
                "table_count": len(csv_tables),
                "row_count": csv_row_count,
                "tables": csv_tables,
            },
        )

        workbook_sheets, workbook_row_count = _write_workbook(
            workbook_raw,
            tables,
            routine_result,
            calculation.metadata,
            checks,
            cancellation_check,
        )
        cancellation_check()
        _normalize_xlsx_archive(
            workbook_raw,
            workbook_pending,
            cancellation_check,
        )
        workbook_raw.unlink(missing_ok=True)
        artifacts["xlsx_workbook"] = _publish_artifact(
            artifact_id="xlsx_workbook",
            pending_path=workbook_pending,
            attempt_directory=attempt_directory,
            job_id=job_id,
            cancellation_check=cancellation_check,
            publish_check=publish_check,
            extra={
                "schema_version": schema_versions["xlsx"],
                "sheet_count": len(workbook_sheets),
                "row_count": workbook_row_count,
                "sheets": workbook_sheets,
                "write_only_streaming": True,
            },
        )

        width, height, row_count, display_count = _render_cdf_plot(
            calculation.metadata,
            cdf_pending,
        )
        artifacts["cdf_plot"] = _publish_artifact(
            artifact_id="cdf_plot",
            pending_path=cdf_pending,
            attempt_directory=attempt_directory,
            job_id=job_id,
            cancellation_check=cancellation_check,
            publish_check=publish_check,
            extra={
                "schema_version": schema_versions["png"],
                "row_count": row_count,
                "source_point_count": row_count,
                "display_point_count": display_count,
                "width_px": width,
                "height_px": height,
                "chart_contract_id": "cdf_v1",
            },
        )
        width, height, row_count, display_count = _render_sensitivity_plot(
            calculation.metadata,
            sensitivity_pending,
        )
        artifacts["sensitivity_plot"] = _publish_artifact(
            artifact_id="sensitivity_plot",
            pending_path=sensitivity_pending,
            attempt_directory=attempt_directory,
            job_id=job_id,
            cancellation_check=cancellation_check,
            publish_check=publish_check,
            extra={
                "schema_version": schema_versions["png"],
                "row_count": row_count,
                "source_step_count": row_count,
                "display_step_count": display_count,
                "width_px": width,
                "height_px": height,
                "chart_contract_id": "sensitivity_v1",
            },
        )
        width, height, row_count = _render_convergence_plot(
            calculation.metadata,
            convergence_pending,
        )
        artifacts["convergence_plot"] = _publish_artifact(
            artifact_id="convergence_plot",
            pending_path=convergence_pending,
            attempt_directory=attempt_directory,
            job_id=job_id,
            cancellation_check=cancellation_check,
            publish_check=publish_check,
            extra={
                "schema_version": schema_versions["png"],
                "row_count": row_count,
                "width_px": width,
                "height_px": height,
                "chart_contract_id": "convergence_v1",
            },
        )
    finally:
        shutil.rmtree(staging, ignore_errors=True)
        for path in temporary_paths:
            path.unlink(missing_ok=True)

    expected_order = (
        "csv_bundle",
        "xlsx_workbook",
        "cdf_plot",
        "sensitivity_plot",
        "convergence_plot",
    )
    artifacts = {artifact_id: artifacts[artifact_id] for artifact_id in expected_order}
    request_sha256 = technoeconomic_api.canonical_json_sha256(request_payload)
    source_snapshot_sha256 = technoeconomic_api.canonical_json_sha256(source_snapshot)
    submission_provenance_sha256 = technoeconomic_api.canonical_json_sha256(
        submission_provenance
    )
    manifest: dict[str, Any] = {
        "schema_version": schema_versions["manifest"],
        "csv_format_version": schema_versions["csv_format"],
        "owner_workflow": "technoeconomic",
        "owner_job_id": job_id,
        "request_sha256": request_sha256,
        "source_snapshot_sha256": source_snapshot_sha256,
        "submission_provenance_sha256": submission_provenance_sha256,
        "sealed_calculation_sha256": sealed_calculation_artifact["sha256"],
        "calculation_contract_version": routine_result.get(
            "calculation_contract_version"
        ),
        "sampling_version": routine_result.get("sampling_version"),
        "artifact_count": len(artifacts),
        "artifacts": artifacts,
        "tie_outs": {
            "status": "passed",
            "check_count": len(checks),
            "failed_check_ids": [],
            "realization_row_count": calculation.row_count,
            "csv_table_row_counts": {
                record["filename"]: record["row_count"] for record in csv_tables
            },
            "xlsx_sheet_row_counts": {
                record["sheet_name"]: record["row_count"]
                for record in workbook_sheets
            },
            "signed_metric_value_counts": _signed_metric_counts(calculation),
        },
        "chart_contracts": CHART_CONTRACTS,
    }
    manifest["manifest_sha256"] = _canonical_json_sha256(manifest)
    return manifest


__all__ = [
    "APPLIED_CSV_BUNDLE_SCHEMA_VERSION",
    "APPLIED_CSV_FORMAT_VERSION",
    "APPLIED_EXPORT_MANIFEST_SCHEMA_VERSION",
    "APPLIED_XLSX_SCHEMA_VERSION",
    "CHART_CONTRACTS",
    "CSV_FORMAT_VERSION",
    "EXPORT_MANIFEST_SCHEMA_VERSION",
    "TechnoeconomicExportError",
    "XLSX_LOGICAL_HASH_VERSION",
    "export_contract_versions",
    "generate_technoeconomic_exports",
]
