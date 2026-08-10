"""Repository-root discovery shared by the backend and the ingestion CLIs.

Several paths are served or written relative to the repository root: the
dashboard HTML, ``public/annual-warning.png``, the default ``outputs/``
directory, ``.env``, and the MIDC CLI's generated CSVs. Anchoring those on a
landmark file rather than on any one module's own directory depth keeps them
correct when modules move into a package.
"""

from __future__ import annotations

from pathlib import Path

DASHBOARD_FILENAME = "sb_energy_dashboard_modern.html"


def discover_project_root(anchor: Path) -> Path:
    """Return the nearest ancestor of ``anchor`` that holds the dashboard file.

    ``anchor`` is normally the calling module's ``__file__``. If no ancestor
    carries the landmark -- an installed copy without the repository around it --
    fall back to the anchor's own directory, which is what these call sites used
    before the root was resolved explicitly.
    """

    origin = Path(anchor).resolve()
    for candidate in origin.parents:
        if (candidate / DASHBOARD_FILENAME).is_file():
            return candidate
    return origin.parent
