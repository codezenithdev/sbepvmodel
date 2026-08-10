"""Assemble the dashboard directly from the canonical ``frontend/`` sources.

FastAPI and the Vinext frontend both consume the same template and ordered
CSS/markup/JavaScript partials.  This module is the Python implementation used
by the Render fallback.  It intentionally tracks source metadata so edits made
while the development server is running invalidate the small render cache.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from sbepv.paths import discover_project_root


class DashboardBuildError(RuntimeError):
    """Raised when the canonical frontend sources cannot be assembled."""


_TEMPLATE = Path("html") / "document.template.html"
_SLOTS = (
    ("{{CSS}}", "CSS", Path("css"), "*.css"),
    ("{{MARKUP}}", "markup", Path("html"), "[0-9]*.html"),
    ("{{JS}}", "JavaScript", Path("js"), "*.js"),
)


def _frontend_directory(project_root: Path | None) -> Path:
    root = (
        discover_project_root(Path(__file__))
        if project_root is None
        else Path(project_root).resolve()
    )
    return root / "frontend"


def _source_groups(
    frontend: Path,
) -> tuple[Path, tuple[tuple[str, str, tuple[Path, ...]], ...]]:
    template = frontend / _TEMPLATE
    if not template.is_file():
        raise DashboardBuildError(f"dashboard template is missing: {template}")

    groups: list[tuple[str, str, tuple[Path, ...]]] = []
    for slot, label, relative_directory, pattern in _SLOTS:
        directory = frontend / relative_directory
        paths = tuple(sorted(directory.glob(pattern)))
        if not paths:
            raise DashboardBuildError(
                f"no {label} dashboard partials matched {directory / pattern}"
            )
        groups.append((slot, label, paths))
    return template, tuple(groups)


def dashboard_source_paths(project_root: Path | None = None) -> tuple[Path, ...]:
    """Return every dashboard input in deterministic assembly order."""

    frontend = _frontend_directory(project_root)
    template, groups = _source_groups(frontend)
    return (template, *(path for _slot, _label, paths in groups for path in paths))


def _normalise_newlines(source: str) -> str:
    return source.replace("\r\n", "\n").replace("\r", "\n")


def _read_source(path: Path) -> str:
    try:
        return _normalise_newlines(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError) as exc:
        raise DashboardBuildError(f"could not read dashboard source: {path}") from exc


def _assemble_frontend(frontend: Path) -> str:
    template, groups = _source_groups(frontend)
    document = _read_source(template)

    for slot, _label, paths in groups:
        occurrences = document.count(slot)
        if occurrences != 1:
            raise DashboardBuildError(
                f"dashboard template must contain {slot} exactly once; "
                f"found {occurrences}"
            )
        content = "\n".join(_read_source(path).removesuffix("\n") for path in paths)
        document = document.replace(slot, content)

    return document


def assemble_dashboard_html(project_root: Path | None = None) -> str:
    """Build the dashboard without caching, primarily for validation and tests."""

    return _assemble_frontend(_frontend_directory(project_root))


def _source_signature(frontend: Path) -> tuple[tuple[str, int, int, int], ...]:
    template, groups = _source_groups(frontend)
    paths = (template, *(path for _slot, _label, paths in groups for path in paths))
    signature: list[tuple[str, int, int, int]] = []
    for path in paths:
        try:
            stat_result = path.stat()
        except OSError as exc:
            raise DashboardBuildError(
                f"could not inspect dashboard source: {path}"
            ) from exc
        signature.append(
            (
                path.relative_to(frontend).as_posix(),
                stat_result.st_mtime_ns,
                stat_result.st_ctime_ns,
                stat_result.st_size,
            )
        )
    return tuple(signature)


@lru_cache(maxsize=2)
def _render_cached(
    frontend_path: str,
    _signature: tuple[tuple[str, int, int, int], ...],
) -> str:
    return _assemble_frontend(Path(frontend_path))


def render_dashboard(project_root: Path | None = None) -> str:
    """Return cached HTML, rebuilding whenever any frontend source changes."""

    frontend = _frontend_directory(project_root).resolve()
    return _render_cached(str(frontend), _source_signature(frontend))


def clear_dashboard_cache() -> None:
    """Clear the render cache for isolated tests and long-running tooling."""

    _render_cached.cache_clear()
