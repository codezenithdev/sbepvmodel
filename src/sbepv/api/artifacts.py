"""Naming, URLs, and cleanup for files generated under the output directory.

Every path here is confined to ``config.OUTPUT_DIR``: a recorded artifact that
resolves outside it, or to a directory rather than a file, is treated as absent
rather than followed. That is what keeps job deletion from reaching shared
source data or anything outside the served tree.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from sbepv.api import config
from sbepv.api.job_store import _get_job_record
from sbepv.api.schemas import AnnualRunRequest, RunRequest

logger = logging.getLogger(__name__)


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
