from __future__ import annotations

from pathlib import Path
import unittest

from sbepv import dashboard


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class CollectDataFrontendTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.markup = (
            PROJECT_ROOT / "frontend" / "html" / "85-collect-data.html"
        ).read_text(encoding="utf-8")
        cls.script = (
            PROJECT_ROOT / "frontend" / "js" / "07-collect-data.js"
        ).read_text(encoding="utf-8")
        cls.styles = (
            PROJECT_ROOT / "frontend" / "css" / "17-collect-data.css"
        ).read_text(encoding="utf-8")
        cls.assembled = dashboard.assemble_dashboard_html(PROJECT_ROOT)

    def test_standalone_collection_surface_assembles_once(self) -> None:
        for element_id in (
            "collectDataTab",
            "collectDataPanel",
            "collectDataForm",
            "collectDataStatus",
            "collectDataCollapseToggle",
            "collectDataStatusContent",
            "collectDataPlots",
            "collectDataAcPowerPlot",
            "collectDataEnergyPlot",
            "collectDataSolarEdgeStatus",
            "collectDataSolectriaStatus",
            "collectDataDownloads",
            "collectDataCsvDownload",
            "collectDataXlsxDownload",
        ):
            with self.subTest(element_id=element_id):
                self.assertEqual(self.assembled.count(f'id="{element_id}"'), 1)
        self.assertIn("America/Denver", self.markup)
        self.assertIn('name="collectDataGroup"', self.markup)
        self.assertIn('role="status"', self.markup)
        self.assertIn('role="alert"', self.markup)
        self.assertIn(
            'id="collectDataTab" type="button" aria-pressed="false" aria-controls="collectDataPanel">Data Collection</button>',
            self.assembled,
        )
        self.assertNotIn('id="collectDataNavLink"', self.assembled)
        self.assertLess(
            self.assembled.index('id="collectDataTab"'),
            self.assembled.index('id="validationTab"'),
        )
        for workflow_tab in (
            "validationTab",
            "annualTab",
            "technoeconomicTab",
            "autonomyTab",
        ):
            self.assertEqual(self.assembled.count(f'id="{workflow_tab}"'), 1)

    def test_requested_defaults_plots_and_collapse_are_wired(self) -> None:
        self.assertIn("fromDate.value = '2025-12-12'", self.script)
        self.assertIn("toDate.value = today", self.script)
        self.assertIn("'/plots/'", self.script)
        self.assertIn("measured-ac-power", self.script)
        self.assertIn("cumulative-energy", self.script)
        self.assertIn("collectDataSetCollapsed", self.script)
        self.assertIn('aria-expanded="true"', self.markup)
        self.assertIn(".collect-data-collapse-toggle", self.styles)
        self.assertIn(".collect-data-plot-grid", self.styles)
        self.assertIn('class="run-btn" id="collectDataSubmit"', self.markup)
        self.assertIn("'/download-xlsx'", self.script)
        self.assertIn("Download CSV", self.markup)
        self.assertIn("Download XLSX with charts", self.markup)
        self.assertIn("SolarEdge measured", self.markup)
        self.assertIn("Solectria measured", self.markup)
        self.assertNotIn("Read-only screening", self.markup)
        self.assertNotIn("Data-quality report", self.markup)
        self.assertNotIn("collectDataRenderQuality", self.script)

    def test_script_uses_only_collection_endpoints_and_safe_rendering(self) -> None:
        self.assertIn("'/api/data-collections'", self.script)
        self.assertIn("'/api/data-collections/'", self.script)
        self.assertIn("encodeURIComponent(collectionId)", self.script)
        self.assertIn("textContent", self.script)
        self.assertIn("collectDataRevision", self.script)
        for forbidden in (
            "/api/run",
            "/api/annual-run",
            "/api/technoeconomic",
            "/api/chat",
            "/api/agent",
            "registerDirectRun",
            "pendingCalibrationReview",
            "saveDashboardState",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, self.script)

    def test_collection_view_preserves_workflow_state_without_style_leaks(self) -> None:
        for mode_class in (
            "dashboard-mode-validation",
            "dashboard-mode-annual",
            "dashboard-mode-technoeconomic",
            "dashboard-mode-autonomy",
        ):
            self.assertIn(f"'{mode_class}'", self.script)
        self.assertIn("querySelectorAll('input, select')", self.script)
        self.assertIn(
            "addEventListener('input', collectDataInvalidateResult)", self.script
        )
        self.assertIn(
            "addEventListener('change', collectDataInvalidateResult)", self.script
        )
        self.assertNotIn("collectDataSetAgentIsolation", self.script)
        self.assertNotIn("chatToggle", self.script)
        self.assertNotIn("chatSidebar", self.script)

    def test_collection_styles_are_isolated_from_workflow_layout(self) -> None:
        self.assertIn("body.dashboard-mode-collect-data", self.styles)
        self.assertIn(".collect-data-page", self.styles)
        self.assertNotIn("#analysisControls", self.styles)
        self.assertNotIn("#annualControls", self.styles)
        self.assertNotIn("#technoeconomicPanel", self.styles)


if __name__ == "__main__":
    unittest.main()
