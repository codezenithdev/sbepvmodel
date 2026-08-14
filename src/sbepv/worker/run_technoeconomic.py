"""Execute one lease-fenced probabilistic technoeconomic job.

The runner consumes only the immutable TEA request and Annual source snapshot
carried by the claimed record.  It never resolves the live Annual job and never
places TEA state in the legacy in-memory model cache.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict
import hashlib
import json
import logging
import math
import os
from pathlib import Path
import secrets
from typing import Any, Callable

import numpy as np

from sbepv import technoeconomic as kernel
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
RESULT_PROVENANCE_SCHEMA_VERSION = 1
SEALED_CALCULATION_FILENAME = "calculation_payload_v1.npz"


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


def _canonical_json_text(value: Any) -> str:
    return json.dumps(
        _json_safe(value),
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
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

    try:
        with temporary.open("xb") as handle:
            np.savez_compressed(handle, **arrays)
            handle.flush()
            os.fsync(handle.fileno())
        publish_check()
        temporary.replace(target)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise

    artifact_sha256 = _sha256_file(target)
    byte_count = int(target.stat().st_size)
    if byte_count <= 0:
        raise ValueError("The sealed calculation payload is empty")
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


def _routine_result(
    request: kernel.TechnoeconomicRequest,
    calculation: kernel.TechnoeconomicResult,
    artifact: Mapping[str, Any],
    submission_provenance: Mapping[str, Any],
) -> dict[str, Any]:
    capacity_map = {capacity.system: capacity for capacity in request.capacities}
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
    return {
        "schema_version": ROUTINE_RESULT_SCHEMA_VERSION,
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
        "capacity_basis": "frozen_annual_module_dc_stc_wdc",
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
            asdict(request)
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
            "kernel": _json_safe(calculation.provenance),
        }
        set_progress(97, "Finalizing technoeconomic results")
        _check_cancelled(job_id, worker_id=worker_id, lease_token=lease_token)
        state.AGENT_STORE.update_technoeconomic_job(
            job_id,
            expected_worker_id=worker_id,
            expected_lease_token=lease_token,
            state="done",
            progress=100,
            stage="Done",
            result=routine_result,
            result_provenance=result_provenance,
            artifacts={"sealed_calculation": artifact},
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
    "RESULT_PROVENANCE_SCHEMA_VERSION",
    "ROUTINE_RESULT_SCHEMA_VERSION",
    "SEALED_CALCULATION_SCHEMA_VERSION",
    "_run_technoeconomic_job",
]
