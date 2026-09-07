from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
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
        cls.form_script = (
            PROJECT_ROOT / "frontend" / "js" / "03-form-reading-and-plots.js"
        ).read_text(encoding="utf-8")
        cls.globals_script = (
            PROJECT_ROOT / "frontend" / "js" / "00-help-tips-and-elements.js"
        ).read_text(encoding="utf-8")
        cls.assembled = dashboard.assemble_dashboard_html(PROJECT_ROOT)

    def test_standalone_collection_surface_assembles_once(self) -> None:
        for element_id in (
            "collectDataTab",
            "collectDataPanel",
            "collectDataForm",
            "collectDataStatus",
            "collectDataCollectionId",
            "collectDataCollapseToggle",
            "collectDataStatusContent",
            "collectDataPlots",
            "collectDataAcPowerPlot",
            "collectDataEnergyPlot",
            "collectDataSolarEdgeEnergy",
            "collectDataSolectriaEnergy",
            "collectDataQualityNote",
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
        self.assertIn("fromDate.value = bazefieldDefaultStartDate()", self.script)
        self.assertIn("fromInput.value = bazefieldDefaultStartDate()", self.form_script)
        self.assertIn("const BAZEFIELD_SITE_FIRST_DATE = '2025-12-12'", self.globals_script)
        self.assertIn("shiftIsoDate(dateIsoInTimeZone(value), -365)", self.form_script)
        self.assertNotIn('value="2025-12-12"', self.markup)
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
        self.assertIn("SolarEdge measured energy", self.markup)
        self.assertIn("Solectria measured energy", self.markup)
        self.assertIn("collectDataFormatEnergy", self.script)
        self.assertIn("measured_energy_kwh", self.script)
        self.assertIn("collectDataQualitySummaryText", self.script)
        self.assertIn("usable_value_completeness_percent", self.script)
        self.assertIn("timestamp_coverage_percent", self.script)
        self.assertIn("non_good_quality_count", self.script)
        self.assertIn("gaps are not counted as zero", self.script)
        self.assertNotIn("'Included'", self.script)
        self.assertNotIn("'Not selected'", self.script)
        self.assertNotIn("Read-only screening", self.markup)
        self.assertNotIn("Data-quality report", self.markup)
        self.assertIn("collectDataElements.qualityNote.textContent", self.script)

    def test_latest_collection_is_restored_without_joining_dashboard_state(self) -> None:
        self.assertIn(
            "const COLLECT_DATA_ACTIVE_ID_STORAGE_KEY = "
            "'sb-energy-data-collection-active-id-v1'",
            self.script,
        )
        self.assertIn("function collectDataValidatedId(value)", self.script)
        self.assertIn("function collectDataRestoreStoredCollection", self.script)
        self.assertIn("collectDataApplyRequest(payload.request)", self.script)
        self.assertIn("void collectDataRestoreStoredCollection({ force: true })", self.script)
        self.assertIn("void collectDataRestoreStoredCollection()", self.script)
        self.assertIn("if (response.status === 404)", self.script)
        self.assertIn("collectDataClearPersistedId(collectionId)", self.script)
        self.assertIn(
            "document.body.classList.contains('dashboard-mode-collect-data')",
            self.script,
        )
        # Polling an older collection in another tab must not replace the newer
        # collection ID written by its successful POST.
        self.assertEqual(2, self.script.count("collectDataPersistId("))
        self.assertNotIn("localStorage.setItem(STORAGE_KEY", self.script)

    @unittest.skipUnless(shutil.which("node"), "Node.js is required")
    def test_collection_id_storage_accepts_only_canonical_ids(self) -> None:
        helpers = "const COLLECT_DATA_ACTIVE_ID_STORAGE_KEY" + self.script.split(
            "const COLLECT_DATA_ACTIVE_ID_STORAGE_KEY", 1
        )[1].split("\n        function openCollectDataView", 1)[0]
        script = f"""
const assert = require('node:assert/strict');
const values = new Map();
globalThis.localStorage = {{
  getItem: (key) => values.has(key) ? values.get(key) : null,
  setItem: (key, value) => values.set(key, String(value)),
  removeItem: (key) => values.delete(key),
}};
{helpers}
const key = COLLECT_DATA_ACTIVE_ID_STORAGE_KEY;
values.set(key, '../../invalid');
assert.equal(collectDataReadStoredId(), null);
assert.equal(values.has(key), false);
const valid = 'collect_0123456789abcdef01234567';
assert.equal(collectDataPersistId(valid), true);
assert.equal(collectDataReadStoredId(), valid);
collectDataClearPersistedId('collect_aaaaaaaaaaaaaaaaaaaaaaaa');
assert.equal(values.get(key), valid);
collectDataClearPersistedId(null);
assert.equal(values.get(key), valid);
collectDataClearPersistedId(valid);
assert.equal(values.has(key), false);
assert.equal(collectDataPersistId('collect_NOT_VALID'), false);
"""
        completed = subprocess.run(
            [shutil.which("node"), "-e", script],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(0, completed.returncode, completed.stderr)

    @unittest.skipUnless(shutil.which("node"), "Node.js is required")
    def test_rolling_bazefield_default_respects_site_start_and_365_days(self) -> None:
        helpers = "function dateIsoInTimeZone" + self.form_script.split(
            "function dateIsoInTimeZone", 1
        )[1].split("\n        function applyValidationDateDefaults", 1)[0]
        script = f"""
const assert = require('node:assert/strict');
const BAZEFIELD_SITE_FIRST_DATE = '2025-12-12';
{helpers}
assert.equal(bazefieldDefaultStartDate(new Date('2026-01-15T19:00:00Z')), '2025-12-12');
assert.equal(bazefieldDefaultStartDate(new Date('2027-01-15T19:00:00Z')), '2026-01-15');
"""
        completed = subprocess.run(
            [shutil.which("node"), "-e", script],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(0, completed.returncode, completed.stderr)

    @unittest.skipUnless(shutil.which("node"), "Node.js is required")
    def test_quality_summary_reports_completeness_without_trusting_issue_text(self) -> None:
        helper = "function collectDataQualitySummaryText" + self.script.split(
            "function collectDataQualitySummaryText", 1
        )[1].split("\n        function collectDataRenderPlots", 1)[0]
        script = f"""
const assert = require('node:assert/strict');
{helper}
const clean = collectDataQualitySummaryText({{
  status: 'clean', issue_count: 0,
  summary: {{usable_value_completeness_percent: 100, timestamp_coverage_percent: 100}},
}});
assert.match(clean, /Source check clean/);
assert.match(clean, /Usable completeness 100%/);
const attention = collectDataQualitySummaryText({{
  status: 'issues_detected', issue_count: 2,
  issues: [{{message: '<img src=x onerror=alert(1)>'}}],
  summary: {{
    usable_value_completeness_percent: 97.5,
    timestamp_coverage_percent: 99,
    non_good_quality_count: 3,
  }},
}});
assert.match(attention, /2 screened issues/);
assert.match(attention, /Usable completeness 97.5%/);
assert.match(attention, /3 non-good Bazefield flags/);
assert.equal(attention.includes('<img'), false);
"""
        completed = subprocess.run(
            [shutil.which("node"), "-e", script],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(0, completed.returncode, completed.stderr)

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
