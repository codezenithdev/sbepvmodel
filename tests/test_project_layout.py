"""Structural invariants that the restructure must not break.

These are deliberately about *layout* rather than behaviour. They fail loudly if
a file move breaks how the backend locates the repository root, how matplotlib is
configured for headless rendering, or how the rest of the suite intercepts module
attributes with ``patch.object``.
"""

from __future__ import annotations

import ast
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

import matplotlib

import sbepv
from sbepv.api import config, state, validation
from sbepv.api import main as app
from sbepv.ingest import midc


DASHBOARD_FILENAME = "sb_energy_dashboard_modern.html"


def discovered_project_root() -> Path:
    """Walk up from the backend module to the directory holding the dashboard.

    Derived independently of any ``PROJECT_ROOT`` constant so the assertions below
    compare two separately-computed answers instead of restating one of them.
    """

    start = Path(app.__file__).resolve()
    for candidate in start.parents:
        if (candidate / DASHBOARD_FILENAME).is_file():
            return candidate
    raise AssertionError(
        f"no ancestor of {start} contains {DASHBOARD_FILENAME}"
    )


class ProjectRootTests(unittest.TestCase):
    def test_root_holds_every_landmark_the_backend_serves(self):
        root = discovered_project_root()

        self.assertTrue((root / DASHBOARD_FILENAME).is_file())
        self.assertTrue((root / "public" / "annual-warning.png").is_file())
        self.assertTrue((root / "requirements.txt").is_file())
        self.assertTrue((root / "tests").is_dir())

    def test_backend_resolves_the_same_root(self):
        self.assertEqual(app.PROJECT_ROOT, discovered_project_root())

    def test_midc_cli_writes_to_the_repository_root(self):
        # The generated CSV location must not follow the module into a package.
        generated = midc.output_path_for(date(2025, 1, 1), date(2025, 12, 31))
        self.assertEqual(generated.parent, discovered_project_root())

    def test_output_directories_exist_after_import(self):
        # app.py mkdirs both at import time; the values themselves are
        # environment-dependent (PV_DASHBOARD_OUTPUT_DIR), so only existence is
        # asserted here.
        self.assertTrue(config.OUTPUT_DIR.is_dir())
        self.assertTrue(config.CALIBRATION_REVIEW_DIR.is_dir())


class ModuleShadowingTests(unittest.TestCase):
    """No module import may be shadowed by a local name in the same file.

    Late binding through a module (``tools._handle_scenario_tool``) is how patched
    symbols stay patchable, but it breaks the moment something else in the file
    binds that name -- a route named ``chat``, a local list named ``tools``. Python
    then treats the name as local for the whole function and raises
    ``UnboundLocalError`` or ``AttributeError`` at runtime, not at import.
    """

    def test_no_module_import_is_shadowed(self):
        package_root = Path(sbepv.__file__).resolve().parent
        offenders: list[str] = []

        for path in sorted(package_root.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            imported = set()
            for node in ast.walk(tree):
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    for alias in node.names:
                        imported.add(alias.asname or alias.name.split(".")[0])

            for node in ast.walk(tree):
                name = None
                if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
                    name = node.id
                elif isinstance(
                    node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
                ):
                    name = node.name
                elif isinstance(node, ast.arg):
                    name = node.arg
                if name in imported:
                    offenders.append(
                        f"{path.relative_to(package_root)}:{node.lineno} "
                        f"rebinds imported name {name!r}"
                    )

        self.assertEqual(offenders, [])


class MatplotlibBackendTests(unittest.TestCase):
    def test_importing_the_backend_pins_agg(self):
        """The job worker renders on a background thread and needs a headless backend.

        app.py never calls matplotlib.use() itself -- it inherits Agg from
        sbe_pv_model / scenario_reporting. If that import chain is broken during a
        refactor, pyplot falls back to a GUI backend and the worker hangs.
        """

        self.assertEqual(matplotlib.get_backend().lower(), "agg")


class PatchInterceptionTests(unittest.TestCase):
    """The whole suite mocks via ``patch.object(<module>, "name")``.

    That only works while callers resolve the name through the module namespace at
    call time. A ``from x import y`` binding anywhere in the chain silently defeats
    the patch and the affected tests pass without asserting anything.
    """

    def test_module_attribute_patches_reach_internal_callers(self):
        request = app.RunRequest(from_date="2025-06-01", to_date="2025-06-02")
        calls: list[tuple[str, str]] = []
        real_iso = validation._iso

        def spy(date_str: str, time_str: str) -> str:
            calls.append((date_str, time_str))
            return real_iso(date_str, time_str)

        with patch.object(validation, "_iso", spy):
            validation._validate_run_request(request)

        self.assertEqual(
            calls,
            [("2025-06-01", "00:00"), ("2025-06-02", "00:00")],
        )

    def test_config_patches_cross_the_module_boundary(self):
        """Settings must be read as ``config.X``, not bound with a from-import.

        Most of the suite redirects OUTPUT_DIR at a temp directory this way. If a
        caller ever captures the value instead, the patch stops applying and those
        tests silently exercise -- and write to -- the real outputs directory.
        """

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshot = root / "snapshot.csv"
            snapshot.write_text("x", encoding="utf-8")

            with patch.object(config, "OUTPUT_DIR", root):
                self.assertEqual(
                    app._public_source_url(snapshot), "/outputs/snapshot.csv"
                )

            # Same path, unpatched: it is outside the real output directory.
            self.assertIsNone(app._public_source_url(snapshot))

    def test_state_reassignment_crosses_the_module_boundary(self):
        """``state.AGENT_STORE`` is swapped for a temp database by six test files."""

        sentinel = object()
        original = state.AGENT_STORE
        state.AGENT_STORE = sentinel
        try:
            self.assertIs(app.state.AGENT_STORE, sentinel)
        finally:
            state.AGENT_STORE = original


if __name__ == "__main__":
    unittest.main()
