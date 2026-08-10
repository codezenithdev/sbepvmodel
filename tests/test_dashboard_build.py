"""The committed dashboard must match what frontend/ builds.

sb_energy_dashboard_modern.html is generated but stays committed, because two
consumers read it directly: FastAPI serves it with FileResponse, and the Vite
build inlines it with a `?raw` import. That makes drift easy -- someone edits the
700 KB generated file instead of the sources and the next build silently reverts
them. This test is the tripwire.
"""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BUILD_SCRIPT = PROJECT_ROOT / "tools" / "build_dashboard.py"


def load_builder():
    spec = importlib.util.spec_from_file_location("build_dashboard", BUILD_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DashboardBuildTests(unittest.TestCase):
    def test_committed_dashboard_matches_frontend_sources(self):
        builder = load_builder()
        built = builder.build()
        committed = builder.OUTPUT.read_text(encoding="utf-8")

        if built == committed:
            return

        # Point at the first divergence rather than dumping 700 KB.
        built_lines = built.splitlines()
        committed_lines = committed.splitlines()
        for number, (a, b) in enumerate(zip(built_lines, committed_lines), start=1):
            if a != b:
                self.fail(
                    f"{builder.OUTPUT.name} is stale at line {number}.\n"
                    f"  committed: {b[:120]!r}\n"
                    f"  rebuilt  : {a[:120]!r}\n"
                    "Run: python tools/build_dashboard.py"
                )
        self.fail(
            f"{builder.OUTPUT.name} is stale: rebuilt has "
            f"{len(built_lines)} lines, committed has {len(committed_lines)}.\n"
            "Run: python tools/build_dashboard.py"
        )

    def test_agent_drawer_override_layer_loads_last(self):
        """The redesign layer overrides the base drawer at equal specificity.

        Reversing these two is a silent visual regression: no error, no failing
        assertion elsewhere, because all the text is still present.
        """

        names = sorted(p.name for p in (PROJECT_ROOT / "frontend" / "css").glob("*.css"))
        base = [n for n in names if n.endswith("agent-drawer-base.css")]
        redesign = [n for n in names if n.endswith("agent-drawer-redesign.css")]

        self.assertEqual(len(base), 1, names)
        self.assertEqual(len(redesign), 1, names)
        self.assertLess(names.index(base[0]), names.index(redesign[0]))


if __name__ == "__main__":
    unittest.main()
