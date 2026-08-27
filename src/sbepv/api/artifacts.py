"""Naming, URLs, and cleanup for files generated under the output directory.

Every path here is confined to ``config.OUTPUT_DIR``: a recorded artifact that
resolves outside it, or to a directory rather than a file, is treated as absent
rather than followed. That is what keeps job deletion from reaching shared
source data or anything outside the served tree.
"""

from __future__ import annotations

import hashlib
import json
import logging
import secrets
import stat
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from sbepv.api import config
from sbepv.api.job_store import _get_job_record
from sbepv.api.schemas import AnnualRunRequest, RunRequest

logger = logging.getLogger(__name__)

_TECHNOECONOMIC_ATTEMPT_ROOT_NAME = ".technoeconomic_attempts"
_SAFE_ARTIFACT_COMPONENT_CHARACTERS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
)
_SAFE_EXPORT_FILENAME_CHARACTERS = (
    _SAFE_ARTIFACT_COMPONENT_CHARACTERS | frozenset(".-")
)
TECHNOECONOMIC_PUBLIC_ARTIFACT_CONTRACT = {
    "csv": {
        "artifact_id": "csv_bundle",
        "artifact_kind": "technoeconomic_csv_bundle",
        "media_type": "application/zip",
        "filename": "technoeconomic-results-csv-v1.zip",
    },
    "xlsx": {
        "artifact_id": "xlsx_workbook",
        "artifact_kind": "technoeconomic_xlsx_workbook",
        "media_type": (
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
        "filename": "technoeconomic-results-v1.xlsx",
    },
    "cdf_plot": {
        "artifact_id": "cdf_plot",
        "artifact_kind": "technoeconomic_cdf_plot",
        "media_type": "image/png",
        "filename": "technoeconomic-cdf-v1.png",
    },
    "sensitivity_plot": {
        "artifact_id": "sensitivity_plot",
        "artifact_kind": "technoeconomic_sensitivity_plot",
        "media_type": "image/png",
        "filename": "technoeconomic-sensitivity-v1.png",
    },
    "convergence_plot": {
        "artifact_id": "convergence_plot",
        "artifact_kind": "technoeconomic_convergence_plot",
        "media_type": "image/png",
        "filename": "technoeconomic-convergence-v1.png",
    },
}


class ArtifactCleanupError(RuntimeError):
    """Raised when confined TEA artifacts cannot be completely removed."""


class ArtifactIntegrityError(RuntimeError):
    """Raised when a published TEA artifact cannot be verified for download."""


def _strict_lstat(path: Path) -> Any | None:
    """Return ``lstat`` data, distinguishing absence from access failures."""

    try:
        return path.lstat()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise ArtifactCleanupError(
            "The confined technoeconomic artifact path could not be inspected."
        ) from exc


def _output_url(path: Path) -> str:
    return f"/outputs/{path.name}"


def _workbook_download_name(
    req: RunRequest | AnnualRunRequest,
    *,
    calibrated: bool = False,
) -> str:
    """Return a readable, filesystem-safe name for a model workbook download."""

    def safe_part(value: Any) -> str:
        normalized = "".join(
            character if character.isalnum() or character in "-_" else "-"
            for character in str(value).strip()
        )
        return normalized.strip("-_") or "unknown"

    if isinstance(req, AnnualRunRequest):
        run_label = "Annual_Simulation"
        start = safe_part(req.from_date)
        end = safe_part(req.to_date)
    else:
        run_label = "Calibrated_Model" if calibrated else "Physics_Model"
        start = safe_part(f"{req.from_date}_{req.from_time}")
        end = safe_part(f"{req.to_date}_{req.to_time}")
    return f"SB_Energy_{run_label}_{start}_to_{end}.xlsx"


def _public_source_url(path: Path) -> str | None:
    """Return a URL only for source snapshots directly served from config.OUTPUT_DIR."""

    try:
        relative = path.resolve().relative_to(config.OUTPUT_DIR.resolve())
    except (OSError, ValueError):
        return None
    if relative.parent != Path("."):
        return None
    return _output_url(path)


def _job_attempt_prefix(job_id: str, lease_token: str | None) -> str:
    """Return a collision-free output prefix for one claimed execution attempt."""

    return f"{job_id}_{lease_token}" if lease_token else job_id


def _safe_technoeconomic_artifact_component(
    raw: Any,
    *,
    field: str,
    required_prefix: str | None = None,
) -> str:
    value = raw.strip() if isinstance(raw, str) else ""
    if (
        not value
        or len(value) > 128
        or any(
            character not in _SAFE_ARTIFACT_COMPONENT_CHARACTERS
            for character in value
        )
        or (required_prefix is not None and not value.startswith(required_prefix))
    ):
        raise ValueError(f"invalid {field} for a technoeconomic artifact path")
    return value


def _technoeconomic_attempt_root(*, create: bool = False) -> Path:
    output_root = config.OUTPUT_DIR.resolve()
    candidate = config.OUTPUT_DIR / _TECHNOECONOMIC_ATTEMPT_ROOT_NAME
    if create:
        candidate.mkdir(parents=True, exist_ok=True)
    try:
        resolved = candidate.resolve()
    except (OSError, RuntimeError, ValueError) as exc:
        raise ValueError("invalid technoeconomic artifact root") from exc
    if (
        resolved.parent != output_root
        or resolved.name != _TECHNOECONOMIC_ATTEMPT_ROOT_NAME
    ):
        raise ValueError("technoeconomic artifact root escapes the output directory")
    return resolved


def _technoeconomic_job_directory(
    job_id: str,
    *,
    create: bool = False,
) -> Path:
    normalized_job_id = _safe_technoeconomic_artifact_component(
        job_id,
        field="job_id",
        required_prefix="tea_",
    )
    root = _technoeconomic_attempt_root(create=create)
    candidate = root / normalized_job_id
    if create:
        candidate.mkdir(exist_ok=True)
    try:
        resolved = candidate.resolve()
    except (OSError, RuntimeError, ValueError) as exc:
        raise ValueError("invalid technoeconomic job artifact directory") from exc
    if resolved.parent != root or resolved.name != normalized_job_id:
        raise ValueError(
            "technoeconomic job artifact directory escapes its private root"
        )
    return resolved


def _technoeconomic_attempt_directory(
    job_id: str,
    lease_token: str,
    *,
    create: bool = False,
) -> Path:
    """Return one lease-specific hidden TEA artifact directory.

    Both path components are restricted to portable ASCII identifier characters,
    and every resolved ancestor is checked before a directory is returned.  This
    makes the path safe for worker writes without exposing it through ``/outputs``.
    """

    normalized_lease_token = _safe_technoeconomic_artifact_component(
        lease_token,
        field="lease_token",
    )
    job_directory = _technoeconomic_job_directory(job_id, create=create)
    candidate = job_directory / normalized_lease_token
    if create:
        candidate.mkdir(exist_ok=True)
    try:
        resolved = candidate.resolve()
    except (OSError, RuntimeError, ValueError) as exc:
        raise ValueError("invalid technoeconomic attempt artifact directory") from exc
    if resolved.parent != job_directory or resolved.name != normalized_lease_token:
        raise ValueError(
            "technoeconomic attempt artifact directory escapes its job directory"
        )
    return resolved


def _canonical_manifest_sha256(manifest: Mapping[str, Any]) -> str:
    """Hash a published export manifest without its self-referential digest."""

    payload = dict(manifest)
    payload.pop("manifest_sha256", None)
    try:
        encoded = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ArtifactIntegrityError(
            "The technoeconomic export manifest is invalid."
        ) from exc
    return hashlib.sha256(encoded).hexdigest()


def _safe_technoeconomic_export_filename(raw: Any) -> str:
    filename = raw.strip() if isinstance(raw, str) else ""
    if (
        not filename
        or len(filename) > 160
        or filename.startswith(".")
        or filename.endswith(".")
        or any(
            character not in _SAFE_EXPORT_FILENAME_CHARACTERS
            for character in filename
        )
        or Path(filename).name != filename
    ):
        raise ArtifactIntegrityError(
            "The technoeconomic export filename is invalid."
        )
    return filename


def _sha256_regular_file(path: Path) -> tuple[str, int]:
    """Return the digest and bytes for one non-symlink regular file."""

    try:
        before = path.lstat()
        if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
            raise ArtifactIntegrityError(
                "The technoeconomic export is not a regular file."
            )
        digest = hashlib.sha256()
        byte_count = 0
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
                byte_count += len(chunk)
        after = path.lstat()
    except ArtifactIntegrityError:
        raise
    except (FileNotFoundError, OSError) as exc:
        raise ArtifactIntegrityError(
            "The technoeconomic export could not be verified."
        ) from exc
    if (
        stat.S_ISLNK(after.st_mode)
        or not stat.S_ISREG(after.st_mode)
        or before.st_dev != after.st_dev
        or before.st_ino != after.st_ino
        or before.st_size != after.st_size
        or before.st_mtime_ns != after.st_mtime_ns
        or byte_count != after.st_size
    ):
        raise ArtifactIntegrityError(
            "The technoeconomic export changed during verification."
        )
    return digest.hexdigest(), byte_count


def _verified_technoeconomic_artifact(
    job: Mapping[str, Any],
    artifact_selector: str,
) -> tuple[Path, dict[str, Any]]:
    """Resolve and re-hash one public export from a completed TEA manifest.

    The storage key is private database state.  It must identify a regular file
    directly beneath this job's lease-specific hidden attempt directory; neither
    callers nor a recorded manifest can widen that boundary.
    """

    contract = TECHNOECONOMIC_PUBLIC_ARTIFACT_CONTRACT.get(artifact_selector)
    if contract is None:
        raise ValueError("unknown technoeconomic public artifact")
    if job.get("state") != "done":
        raise ArtifactIntegrityError(
            "Technoeconomic exports are available only after completion."
        )
    job_id = _safe_technoeconomic_artifact_component(
        job.get("id"),
        field="job_id",
        required_prefix="tea_",
    )
    artifacts = job.get("artifacts")
    manifest = artifacts.get("exports") if isinstance(artifacts, Mapping) else None
    if not isinstance(manifest, Mapping):
        raise ArtifactIntegrityError(
            "The completed technoeconomic job has no verified export manifest."
        )
    recorded_manifest_sha256 = manifest.get("manifest_sha256")
    if (
        not isinstance(recorded_manifest_sha256, str)
        or len(recorded_manifest_sha256) != 64
        or any(
            character not in "0123456789abcdef"
            for character in recorded_manifest_sha256
        )
        or not secrets.compare_digest(
            recorded_manifest_sha256,
            _canonical_manifest_sha256(manifest),
        )
    ):
        raise ArtifactIntegrityError(
            "The technoeconomic export manifest failed its integrity check."
        )
    entries = manifest.get("artifacts")
    if not isinstance(entries, Mapping):
        raise ArtifactIntegrityError(
            "The technoeconomic export manifest is invalid."
        )
    expected_artifact_ids = {
        str(specification["artifact_id"])
        for specification in TECHNOECONOMIC_PUBLIC_ARTIFACT_CONTRACT.values()
    }
    result_provenance = job.get("result_provenance")
    sealed_calculation = (
        artifacts.get("sealed_calculation")
        if isinstance(artifacts, Mapping)
        else None
    )
    artifact_count = manifest.get("artifact_count")
    if (
        isinstance(artifact_count, bool)
        or not isinstance(artifact_count, int)
        or artifact_count != len(entries)
        or set(entries) != expected_artifact_ids
        or manifest.get("owner_workflow") != "technoeconomic"
        or manifest.get("owner_job_id") != job_id
        or manifest.get("source_snapshot_sha256")
        != job.get("source_snapshot_sha256")
        or not isinstance(result_provenance, Mapping)
        or manifest.get("request_sha256")
        != result_provenance.get("request_sha256")
        or manifest.get("submission_provenance_sha256")
        != job.get("submission_provenance_sha256")
        or not isinstance(sealed_calculation, Mapping)
        or manifest.get("sealed_calculation_sha256")
        != sealed_calculation.get("sha256")
    ):
        raise ArtifactIntegrityError(
            "The technoeconomic export manifest ownership or count is invalid."
        )
    selected = entries.get(contract["artifact_id"])
    if (
        not isinstance(selected, Mapping)
        or selected.get("artifact_id") != contract["artifact_id"]
    ):
        raise ArtifactIntegrityError(
            "The requested technoeconomic export is unavailable."
        )
    entry = dict(selected)
    filename = _safe_technoeconomic_export_filename(entry.get("filename"))
    if (
        entry.get("public") is not True
        or entry.get("owner_workflow") != "technoeconomic"
        or entry.get("owner_job_id") != job_id
        or entry.get("artifact_kind") != contract["artifact_kind"]
        or entry.get("media_type") != contract["media_type"]
        or filename != contract["filename"]
    ):
        raise ArtifactIntegrityError(
            "The requested technoeconomic export metadata is invalid."
        )
    storage_key = entry.get("storage_key")
    if not isinstance(storage_key, str) or "\\" in storage_key:
        raise ArtifactIntegrityError(
            "The requested technoeconomic export storage identity is invalid."
        )
    parts = PurePosixPath(storage_key).parts
    if (
        len(parts) != 4
        or parts[0] != _TECHNOECONOMIC_ATTEMPT_ROOT_NAME
        or parts[1] != job_id
        or parts[3] != filename
    ):
        raise ArtifactIntegrityError(
            "The requested technoeconomic export storage identity is invalid."
        )
    try:
        lease_token = _safe_technoeconomic_artifact_component(
            parts[2],
            field="lease_token",
        )
        attempt_directory = _technoeconomic_attempt_directory(
            job_id,
            lease_token,
            create=False,
        )
        candidate = attempt_directory / filename
        resolved = candidate.resolve(strict=True)
    except (OSError, RuntimeError, ValueError) as exc:
        raise ArtifactIntegrityError(
            "The requested technoeconomic export could not be resolved."
        ) from exc
    if resolved.parent != attempt_directory or resolved.name != filename:
        raise ArtifactIntegrityError(
            "The requested technoeconomic export escapes its confined directory."
        )
    recorded_sha256 = entry.get("sha256")
    recorded_byte_count = entry.get("byte_count")
    if (
        not isinstance(recorded_sha256, str)
        or len(recorded_sha256) != 64
        or any(
            character not in "0123456789abcdef"
            for character in recorded_sha256
        )
        or isinstance(recorded_byte_count, bool)
        or not isinstance(recorded_byte_count, int)
        or recorded_byte_count <= 0
    ):
        raise ArtifactIntegrityError(
            "The requested technoeconomic export identity is invalid."
        )
    actual_sha256, actual_byte_count = _sha256_regular_file(resolved)
    if actual_byte_count != recorded_byte_count or not secrets.compare_digest(
        actual_sha256,
        recorded_sha256,
    ):
        raise ArtifactIntegrityError(
            "The requested technoeconomic export failed its integrity check."
        )
    return resolved, entry


def _delete_confined_directory_contents(directory: Path) -> int:
    """Delete regular files/symlinks below one already-validated directory."""

    removed = 0
    try:
        children = list(directory.iterdir())
    except OSError:
        logger.warning(
            "Could not enumerate technoeconomic artifacts in %s",
            directory,
            exc_info=True,
        )
        return 0
    for child in children:
        try:
            if child.is_symlink():
                child.unlink()
                removed += 1
                continue
            resolved = child.resolve()
            if resolved.parent != directory:
                logger.warning(
                    "Ignored technoeconomic artifact outside attempt directory: %s",
                    child,
                )
                continue
            if resolved.is_dir():
                removed += _delete_confined_directory_contents(resolved)
                try:
                    resolved.rmdir()
                except OSError:
                    # Preserve unknown/special entries rather than widening cleanup.
                    pass
            elif resolved.is_file():
                resolved.unlink()
                removed += 1
        except OSError:
            logger.warning(
                "Could not remove technoeconomic artifact %s",
                child,
                exc_info=True,
            )
    return removed


def _delete_technoeconomic_attempt_artifacts(
    job_id: str,
    lease_token: str,
) -> int:
    """Remove artifacts owned by one fenced TEA execution attempt only."""

    try:
        attempt = _technoeconomic_attempt_directory(
            job_id,
            lease_token,
            create=False,
        )
    except (OSError, ValueError):
        return 0
    if attempt.is_symlink() or not attempt.is_dir():
        return 0
    removed = _delete_confined_directory_contents(attempt)
    try:
        attempt.rmdir()
    except OSError:
        pass
    job_directory = attempt.parent
    root = job_directory.parent
    for directory in (job_directory, root):
        try:
            directory.rmdir()
        except OSError:
            break
    return removed


def _delete_technoeconomic_job_artifacts(
    job: dict[str, Any],
    *,
    require_complete: bool = False,
) -> int:
    """Remove all confined attempt artifacts for one deleted TEA job.

    The immutable Annual-owned source artifact and every file outside the hidden
    job directory are deliberately outside the cleanup search space.
    """

    try:
        job_id = _safe_technoeconomic_artifact_component(
            job.get("id"),
            field="job_id",
            required_prefix="tea_",
        )
        job_directory = _technoeconomic_job_directory(job_id, create=False)
    except (OSError, ValueError) as exc:
        if require_complete:
            raise ArtifactCleanupError(
                "The confined technoeconomic artifact directory could not be validated."
            ) from exc
        return 0

    if require_complete:
        path_stat = _strict_lstat(job_directory)
        if path_stat is None:
            return 0
        if stat.S_ISLNK(path_stat.st_mode) or not stat.S_ISDIR(path_stat.st_mode):
            raise ArtifactCleanupError(
                "The confined technoeconomic artifact path is not a directory."
            )
    elif job_directory.is_symlink() or not job_directory.is_dir():
        return 0
    try:
        attempts = list(job_directory.iterdir())
    except OSError:
        logger.warning(
            "Could not enumerate technoeconomic attempts for %s",
            job_id,
            exc_info=True,
        )
        if require_complete:
            raise ArtifactCleanupError(
                "The confined technoeconomic artifacts could not be enumerated."
            )
        return 0
    removed = 0
    for attempt in attempts:
        try:
            _safe_technoeconomic_artifact_component(
                attempt.name,
                field="lease_token",
            )
        except ValueError:
            continue
        removed += _delete_technoeconomic_attempt_artifacts(job_id, attempt.name)
    try:
        job_directory.rmdir()
    except OSError:
        pass
    try:
        job_directory.parent.rmdir()
    except OSError:
        pass
    if require_complete and _strict_lstat(job_directory) is not None:
        raise ArtifactCleanupError(
            "The confined technoeconomic artifacts could not be completely removed."
        )
    return removed


def _job_output_file(raw: Any) -> Path | None:
    """Resolve one recorded job artifact only when it is a direct output file."""

    if not isinstance(raw, str) or not raw:
        return None
    value = raw.split("?", 1)[0].split("#", 1)[0]
    if value.startswith("/outputs/"):
        candidate = config.OUTPUT_DIR / value.removeprefix("/outputs/")
    else:
        candidate = Path(value)
        if not candidate.is_absolute():
            candidate = config.OUTPUT_DIR / candidate
    try:
        resolved = candidate.resolve()
        if resolved.parent != config.OUTPUT_DIR.resolve() or not resolved.is_file():
            return None
    except (OSError, RuntimeError, ValueError):
        return None
    return resolved


def _delete_job_artifacts(job: dict[str, Any]) -> int:
    """Remove files generated for one job without touching shared sources."""

    job_id = str(job.get("id") or "").strip()
    if not job_id or any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for character in job_id):
        return 0
    output_root = config.OUTPUT_DIR.resolve()
    candidates: set[Path] = set()
    protected_shared_sources: set[Path] = set()

    # Same-input scenarios deliberately reuse their baseline's immutable source
    # snapshot. That path can appear both as ``source_path`` and inside the
    # public result payload, so protect it before recursively collecting files.
    baseline_id = job.get("baseline_id")
    if baseline_id:
        baseline = _get_job_record(str(baseline_id))
        baseline_source = _job_output_file((baseline or {}).get("source_path"))
        job_source = _job_output_file(job.get("source_path"))
        if baseline_source is not None and baseline_source == job_source:
            protected_shared_sources.add(baseline_source)

    def collect(value: Any) -> None:
        if isinstance(value, dict):
            for item in value.values():
                collect(item)
        elif isinstance(value, (list, tuple, set)):
            for item in value:
                collect(item)
        else:
            path = _job_output_file(value)
            if path is not None:
                candidates.add(path)

    collect(job.get("result"))
    collect(job.get("artifacts"))
    source_path = job.get("source_path")
    source_file = _job_output_file(source_path)
    if source_file is not None:
        candidates.add(source_file)

    try:
        generated = [output_root / job_id, *output_root.glob(f"{job_id}_*")]
        candidates.update(
            path.resolve()
            for path in generated
            if path.is_file() and path.resolve().parent == output_root
        )
    except OSError:
        logger.warning("Could not enumerate output artifacts for job %s", job_id, exc_info=True)

    candidates.difference_update(protected_shared_sources)

    removed = 0
    for candidate in candidates:
        try:
            if candidate.parent != output_root or not candidate.is_file():
                continue
            candidate.unlink()
            removed += 1
        except OSError:
            logger.warning("Could not remove deleted job artifact %s", candidate, exc_info=True)
    return removed


def _delete_job_attempt_artifacts(job_id: str, lease_token: str | None) -> int:
    """Remove files from a fenced-off attempt after it loses ownership."""

    if not lease_token:
        return 0
    attempt_prefix = _job_attempt_prefix(job_id, lease_token)
    if any(
        character
        not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
        for character in attempt_prefix
    ):
        return 0
    output_root = config.OUTPUT_DIR.resolve()
    protected_source: Path | None = None
    current = _get_job_record(job_id)
    if current is not None:
        protected_source = _job_output_file(current.get("source_path"))
    try:
        candidates = [
            output_root / attempt_prefix,
            *output_root.glob(f"{attempt_prefix}*"),
        ]
    except OSError:
        logger.warning(
            "Could not enumerate expired attempt artifacts for job %s",
            job_id,
            exc_info=True,
        )
        return 0

    removed = 0
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
            if (
                resolved.parent != output_root
                or not resolved.is_file()
                or resolved == protected_source
            ):
                continue
            resolved.unlink()
            removed += 1
        except OSError:
            logger.warning(
                "Could not remove expired attempt artifact %s",
                candidate,
                exc_info=True,
            )
    return removed
