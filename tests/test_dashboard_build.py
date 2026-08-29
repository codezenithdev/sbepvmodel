"""The two dashboard front doors assemble the canonical frontend sources."""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from sbepv import dashboard


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class DashboardBuildTests(unittest.TestCase):
    def tearDown(self):
        dashboard.clear_dashboard_cache()

    def test_sources_assemble_deterministically_without_unfilled_slots(self):
        first = dashboard.assemble_dashboard_html(PROJECT_ROOT)
        second = dashboard.assemble_dashboard_html(PROJECT_ROOT)

        self.assertEqual(first, second)
        self.assertTrue(first.startswith("<!DOCTYPE html>"))
        self.assertIn('id="annualPanel"', first)
        for slot in ("{{CSS}}", "{{MARKUP}}", "{{JS}}"):
            self.assertNotIn(slot, first)

    def test_every_source_group_uses_lexical_filename_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            frontend = root / "frontend"
            for directory in ("css", "html", "js"):
                (frontend / directory).mkdir(parents=True, exist_ok=True)

            (frontend / "html" / "document.template.html").write_text(
                "{{CSS}}\n{{MARKUP}}\n{{JS}}",
                encoding="utf-8",
            )
            sources = (
                ("css", "20-second.css", "css-20"),
                ("css", "10-first.css", "css-10"),
                ("html", "20-second.html", "html-20"),
                ("html", "10-first.html", "html-10"),
                ("js", "20-second.js", "js-20"),
                ("js", "10-first.js", "js-10"),
            )
            for directory, filename, content in sources:
                (frontend / directory / filename).write_text(content, encoding="utf-8")

            assembled = dashboard.assemble_dashboard_html(root)

        self.assertEqual(
            assembled,
            "css-10\ncss-20\nhtml-10\nhtml-20\njs-10\njs-20",
        )

    def test_render_cache_invalidates_when_a_source_changes_or_is_added(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shutil.copytree(PROJECT_ROOT / "frontend", root / "frontend")

            initial = dashboard.render_dashboard(root)
            source = root / "frontend" / "css" / "01-tokens-and-base.css"
            source.write_text(
                source.read_text(encoding="utf-8") + "\n/* cache refresh */\n",
                encoding="utf-8",
            )
            edited = dashboard.render_dashboard(root)

            added_source = root / "frontend" / "css" / "99-cache-refresh.css"
            added_source.write_text(
                ".cache-refresh { display: block; }\n",
                encoding="utf-8",
            )
            added = dashboard.render_dashboard(root)

        self.assertNotEqual(initial, edited)
        self.assertIn("/* cache refresh */", edited)
        self.assertNotEqual(edited, added)
        self.assertIn(".cache-refresh { display: block; }", added)

    def test_missing_template_fails_clearly_without_misresolving_the_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shutil.copytree(PROJECT_ROOT / "frontend", root / "frontend")
            (root / "frontend" / "html" / "document.template.html").unlink()

            with self.assertRaisesRegex(
                dashboard.DashboardBuildError,
                "dashboard template is missing",
            ):
                dashboard.assemble_dashboard_html(root)

    def test_removed_generated_dashboard_is_not_reintroduced(self):
        self.assertFalse(
            (PROJECT_ROOT / "sb_energy_dashboard_modern.html").exists()
        )

    def test_agent_drawer_override_layer_loads_last(self):
        """The redesign layer overrides the base drawer at equal specificity.

        Reversing these two is a silent visual regression: no error, no failing
        assertion elsewhere, because all the text is still present.
        """

        names = sorted(
            p.name for p in (PROJECT_ROOT / "frontend" / "css").glob("*.css")
        )
        base = [n for n in names if n.endswith("agent-drawer-base.css")]
        redesign = [n for n in names if n.endswith("agent-drawer-redesign.css")]

        self.assertEqual(len(base), 1, names)
        self.assertEqual(len(redesign), 1, names)
        self.assertLess(names.index(base[0]), names.index(redesign[0]))

    def test_autonomy_sources_assemble_exactly_once_and_preserve_existing_tabs(self):
        """The fourth mode is additive and every canonical partial has one copy."""

        assembled = dashboard.assemble_dashboard_html(PROJECT_ROOT)
        frontend = PROJECT_ROOT / "frontend"
        autonomy_sources = sorted(
            path
            for directory, pattern in (
                (frontend / "css", "*autonomy*.css"),
                (frontend / "html", "*autonomy*.html"),
                (frontend / "js", "*autonomy*.js"),
            )
            for path in directory.glob(pattern)
        )

        self.assertGreaterEqual(len(autonomy_sources), 3)
        for path in autonomy_sources:
            source = (
                path.read_text(encoding="utf-8")
                .replace("\r\n", "\n")
                .replace("\r", "\n")
                .removesuffix("\n")
            )
            with self.subTest(source=path.relative_to(PROJECT_ROOT)):
                self.assertTrue(source.strip())
                self.assertEqual(assembled.count(source), 1)

        tab_ids = (
            "validationTab",
            "annualTab",
            "technoeconomicTab",
            "autonomyTab",
        )
        positions = []
        for tab_id in tab_ids:
            marker = f'id="{tab_id}"'
            self.assertEqual(assembled.count(marker), 1)
            positions.append(assembled.index(marker))
        self.assertEqual(positions, sorted(positions))

        for label in (
            "Model Calibration",
            "Annual Simulation",
            "Technoeconomic Analysis",
            "Autonomy",
        ):
            self.assertIn(label, assembled)
        self.assertEqual(assembled.count('id="autonomyPanel"'), 1)

        script_names = sorted(
            path.name for path in (frontend / "js").glob("*.js")
        )
        autonomy_scripts = [name for name in script_names if "autonomy" in name]
        self.assertEqual(len(autonomy_scripts), 1, script_names)
        self.assertLess(
            script_names.index("01-progress-and-mode.js"),
            script_names.index(autonomy_scripts[0]),
        )
        self.assertLess(
            script_names.index(autonomy_scripts[0]),
            script_names.index("08-dashboard-state.js"),
        )


if __name__ == "__main__":
    unittest.main()
