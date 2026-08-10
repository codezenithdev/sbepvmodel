"""Static serving for generated run artifacts.

The ``/outputs`` mount is public, but the directory also holds the agent SQLite
database and pending calibration reviews. This allowlist is what keeps those
private: only regular files sitting directly in the output root, with an expected
suffix and no leading dot, are ever resolved.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.staticfiles import StaticFiles

from sbepv.api import config
from sbepv.api.config import PRIVATE_OUTPUT_DIRS, PUBLIC_OUTPUT_SUFFIXES


class PublicOutputStaticFiles(StaticFiles):
    """Serve only root-level generated artifacts from an explicit allowlist."""

    def lookup_path(self, path: str):
        full_path, stat_result = super().lookup_path(path)
        if not full_path:
            return full_path, stat_result
        try:
            resolved = Path(full_path).resolve()
        except OSError:
            return "", None
        if any(
            resolved == private_root or private_root in resolved.parents
            for private_root in PRIVATE_OUTPUT_DIRS
        ):
            return "", None
        if (
            resolved.parent != config.OUTPUT_DIR.resolve()
            or resolved.name.startswith(".")
            or resolved.suffix.casefold() not in PUBLIC_OUTPUT_SUFFIXES
            or (stat_result is not None and not resolved.is_file())
        ):
            return "", None
        return full_path, stat_result
