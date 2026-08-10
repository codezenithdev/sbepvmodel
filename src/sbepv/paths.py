"""Repository-root discovery shared by the backend and the ingestion CLIs.

Several paths are served or written relative to the repository root:
``frontend/``, ``public/annual-warning.png``, the default ``outputs/``
directory, ``.env``, and the MIDC CLI's generated CSVs. Anchoring those on
stable project landmarks rather than on any one module's own directory depth
keeps them correct when modules move into a package.
"""

from __future__ import annotations

from pathlib import Path

PROJECT_FILE = "pyproject.toml"
PACKAGE_SOURCE = Path("src") / "sbepv"


class ProjectRootNotFoundError(RuntimeError):
    """Raised when an anchor is not inside a complete source checkout."""


def discover_project_root(anchor: Path) -> Path:
    """Return the nearest ancestor of ``anchor`` that holds this project.

    ``anchor`` is normally the calling module's ``__file__``. Both landmarks are
    required because these call sites need repository assets and writable paths;
    silently guessing a package directory would misplace those resources.
    """

    origin = Path(anchor).resolve()
    start = origin if origin.is_dir() else origin.parent
    for candidate in (start, *start.parents):
        if (candidate / PROJECT_FILE).is_file() and (
            candidate / PACKAGE_SOURCE
        ).is_dir():
            return candidate
    raise ProjectRootNotFoundError(
        f"could not find project root above {origin}; expected both "
        f"{PROJECT_FILE} and {PACKAGE_SOURCE.as_posix()}"
    )
