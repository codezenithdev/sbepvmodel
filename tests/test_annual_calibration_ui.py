from __future__ import annotations

import json
import shutil
import subprocess
import unittest

from sbepv import dashboard


class AnnualCalibrationUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.html = dashboard.render_dashboard()

    def test_inherits_exactly_nine_settings_without_dates(self) -> None:
        for marker in (
            'id="annualCalibrationStrip"',
            'id="annualCalibrationWindow"',
            'id="annualModifiedCount"',
            'id="annualRestoreSettingsBtn"',
            "fetch('/api/current-calibration', { cache: 'no-store' })",
            "body.calibration_baseline_job_id = annualCalibrationBaseline.job_id",
            "function applyAnnualCalibrationSettings(settings)",
            "function renderAnnualSettingDiffs()",
        ):
            self.assertIn(marker, self.html)

        for setting in (
            "backtrack",
            "curtailment_enabled",
            "curtailment_limit_kw",
            "solaredge_inverter_efficiency",
            "solaredge_bos_efficiency",
            "solectria_inverter_efficiency",
            "solectria_bos_efficiency",
            "iam_model",
            "iam_a_r",
        ):
            self.assertIn(f'data-annual-setting-origin="{setting}"', self.html)

        inherited_apply = self.html.split(
            "function applyAnnualCalibrationSettings(settings)", 1
        )[1].split("\n        function ", 1)[0]
        self.assertNotIn("annualFromDate", inherited_apply)
        self.assertNotIn("annualToDate", inherited_apply)

        for removed in (
            'id="annualCalibrationLineage"',
            'id="annualCalibrationReceiptLink"',
            "View calibration receipt",
            "SolarEdge and Solectria settings and seasonal factors below come from "
            "this reviewed calibration. Annual dates remain independent.",
        ):
            self.assertNotIn(removed, self.html)

    def test_coverage_and_factors_are_server_driven(self) -> None:
        for season in ("winter", "spring", "summer", "fall"):
            self.assertIn(f'data-annual-season="{season}"', self.html)
        for marker in (
            'id="annualSeasonalFactorRows"',
            "baseline?.seasonal_factors",
            "baseline?.factor_coverage",
            "annualFactorValue(baseline, key, system)",
            "Frozen per-system factors from the promoted calibration.",
            "will not be refit against annual MIDC data",
        ):
            self.assertIn(marker, self.html)

    def test_calibration_factors_are_displayed_with_four_decimal_places(self) -> None:
        factor_formatter = self.html.split(
            "function formatAnnualFactor(value)", 1
        )[1].split("\n        function ", 1)[0]
        compact_formatter = self.html.split(
            "function formatAnnualFactorCompact(value)", 1
        )[1].split("\n        function ", 1)[0]

        self.assertIn("Number(value).toFixed(4)", factor_formatter)
        self.assertIn("Number(value).toFixed(4)", compact_formatter)
        self.assertNotIn("String(value)", factor_formatter)
        self.assertNotIn("toFixed(6)", compact_formatter)

    def test_annual_interval_is_visible_saved_and_sent(self) -> None:
        for marker in (
            'id="annualIntervalValue"',
            'id="annualIntervalUnit"',
            'id="annualIntervalValue" value="1" min="1" max="1" step="1"',
            '<option value="minutes">minutes</option>',
            '<option value="hours" selected>hours</option>',
            "hours: new Set([1])",
            "const RECOGNIZED_LEGACY_ANNUAL_INTERVALS",
            "hours: new Set([1, 2, 3, 4, 6, 8, 12, 24])",
            "days: new Set([1])",
            "function isSupportedAnnualInterval(value, unit)",
            "function isRecognizedAnnualInterval(value, unit)",
            "1440 % value === 0",
            "const MAX_ANNUAL_MODEL_ROWS = 1048575",
            "function estimateAnnualModelRows(years, intervalValue, intervalUnit)",
            "Use a whole-minute interval from 1 to 60 that divides evenly into 24 hours, or exactly 1 hour.",
            "function applyAnnualIntervalFormState(value, unit)",
            "function normalizeAnnualIntervalControls()",
        ):
            self.assertIn(marker, self.html)
        self.assertNotIn("Minute options:", self.html)
        self.assertNotIn("One-minute resolution is about 525,600 rows", self.html)
        self.assertNotIn("Hour options:", self.html)
        self.assertNotIn("Day option:", self.html)
        annual_window = self.html.split(
            '<section class="annual-config-card annual-window-card"', 1
        )[1].split('<section class="annual-config-card annual-settings-card"', 1)[0]
        self.assertIn('<option value="minutes">', annual_window)
        self.assertNotIn('<option value="days">', annual_window)

        form_state = self.html.split("function getAnnualFormState()", 1)[1].split(
            "\n        function ", 1
        )[0]
        self.assertIn("annualIntervalValue", form_state)
        self.assertIn("annualIntervalUnit", form_state)

        apply_state = self.html.split("function applyAnnualFormState(form)", 1)[
            1
        ].split("\n        function ", 1)[0]
        self.assertIn(
            "applyAnnualIntervalFormState(form.intervalValue, form.intervalUnit)",
            apply_state,
        )
        self.assertNotIn("setValue('annualIntervalValue'", apply_state)
        self.assertNotIn("setValue('annualIntervalUnit'", apply_state)

        request_builder = self.html.split("function buildAnnualRequest()", 1)[
            1
        ].split("\n        async function ", 1)[0]
        self.assertIn("interval_value:", request_builder)
        self.assertIn("interval_unit:", request_builder)
        self.assertIn(
            "isSupportedAnnualInterval(intervalValue, intervalUnit)",
            request_builder,
        )
        self.assertIn(
            "Choose a whole-minute interval from 1 to 60 that divides evenly into 24 hours, or exactly 1 hour.",
            request_builder,
        )
        self.assertIn(
            "estimatedRows > MAX_ANNUAL_MODEL_ROWS",
            request_builder,
        )
        self.assertIn("Select fewer years or a longer interval", request_builder)
        self.assertIn("const years = readAnnualSelectedYears()", request_builder)
        self.assertIn("years,", request_builder)
        self.assertNotIn("from_date:", request_builder)
        self.assertNotIn("to_date:", request_builder)

    @unittest.skipUnless(shutil.which("node"), "Node.js is required")
    def test_annual_interval_policy_and_cached_state_migration_in_node(self) -> None:
        policy = "const SUPPORTED_ANNUAL_INTERVALS" + self.html.split(
            "const SUPPORTED_ANNUAL_INTERVALS", 1
        )[1].split("const DEFAULT_ASSISTANT_MESSAGE", 1)[0]
        constraints = "function syncAnnualIntervalConstraints()" + self.html.split(
            "function syncAnnualIntervalConstraints()", 1
        )[1].split("\n        function ", 1)[0]
        apply_state = "function applyAnnualIntervalFormState(value, unit)" + self.html.split(
            "function applyAnnualIntervalFormState(value, unit)", 1
        )[1].split("\n        function ", 1)[0]
        normalize_controls = "function normalizeAnnualIntervalControls()" + self.html.split(
            "function normalizeAnnualIntervalControls()", 1
        )[1].split("\n        function ", 1)[0]
        script = f"""
{policy}
const elements = {{
    annualIntervalValue: {{value: '1', max: '1'}},
    annualIntervalUnit: {{value: 'hours'}},
}};
const document = {{getElementById: (id) => elements[id]}};
{constraints}
{apply_state}
{normalize_controls}
const snapshot = () => ({{
    value: elements.annualIntervalValue.value,
    unit: elements.annualIntervalUnit.value,
    max: elements.annualIntervalValue.max,
}});
applyAnnualIntervalFormState('45', 'minutes');
const validCached = snapshot();
applyAnnualIntervalFormState('24', 'hours');
const coarseCached = snapshot();
applyAnnualIntervalFormState('1', 'days');
const dayCached = snapshot();
elements.annualIntervalValue.value = '15';
elements.annualIntervalUnit.value = 'hours';
normalizeAnnualIntervalControls();
const switchedToHours = snapshot();
console.log(JSON.stringify({{
    supportedMinutes: [1, 5, 7, 45, 60, 61].map((value) => isSupportedAnnualInterval(value, 'minutes')),
    supportedHours: [1, 2, 6, 8, 12, 24].map((value) => isSupportedAnnualInterval(value, 'hours')),
    supportedDay: isSupportedAnnualInterval(1, 'days'),
    recognizedLegacyHours: [8, 12, 24].map((value) => isRecognizedAnnualInterval(value, 'hours')),
    recognizedLegacyDay: isRecognizedAnnualInterval(1, 'days'),
    validCached,
    coarseCached,
    dayCached,
    switchedToHours,
}}));
"""
        completed = subprocess.run(
            [shutil.which("node"), "-e", script],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            {
                "supportedMinutes": [True, True, False, True, True, False],
                "supportedHours": [True, False, False, False, False, False],
                "supportedDay": False,
                "recognizedLegacyHours": [True, True, True],
                "recognizedLegacyDay": True,
                "validCached": {"value": "45", "unit": "minutes", "max": "60"},
                "coarseCached": {"value": "1", "unit": "hours", "max": "1"},
                "dayCached": {"value": "1", "unit": "hours", "max": "1"},
                "switchedToHours": {"value": "1", "unit": "hours", "max": "1"},
            },
            json.loads(completed.stdout),
        )

    def test_midc_year_selector_uses_runtime_years_and_exact_reference(self) -> None:
        for marker in (
            'id="annualYearGrid"',
            'id="annualSelectAllYearsBtn"',
            'id="annualClearYearsBtn"',
            "const ANNUAL_FIRST_YEAR = 2011",
            "const ANNUAL_FIRST_DATE = '2011-02-11'",
            "const ANNUAL_KNOWN_PARTIAL_YEAR_NOTES = Object.freeze({",
            "2022: 'known source gaps'",
            "2023: 'known source gaps'",
            "function initializeAnnualYearSelector()",
            "for (let year = currentYear; year >= ANNUAL_FIRST_YEAR; year -= 1)",
            "knownPartialNote ? 'incomplete_source' : 'complete'",
            "coverageStatus = 'year_to_date'",
            "? 'Partial - starts '",
            "? 'Partial - ' + range.coverageNote",
            "Years 2022 and 2023 have known MIDC source gaps and are marked partial, but remain selectable.",
            "annualYearElements.selectAllButton.addEventListener('click'",
            "annualYearElements.clearButton.addEventListener('click'",
            "https://midcdmz.nlr.gov/apps/daily.pl?site=STAC&amp;start=20110211&amp;yr=2026&amp;mo=7&amp;dy=12",
        ):
            self.assertIn(marker, self.html)

    def test_multi_year_results_table_and_accessible_distribution_are_client_rendered(self) -> None:
        for marker in (
            'id="annualYearResults"',
            'id="annualYearResultRows"',
            'id="annualDistributionChart"',
            'aria-labelledby="annualDistributionTitle annualDistributionDescription"',
            'id="annualDistributionSeries"',
            '<option value="combined" selected>Combined</option>',
            '<option value="solarEdge">SolarEdge</option>',
            '<option value="solectria">Solectria</option>',
            'id="annualDistributionRankedBtn"',
            'id="annualDistributionExceedanceBtn"',
            'id="annualDistributionSampleValue"',
            'id="annualDistributionP90Value"',
            'id="annualDistributionP50Value"',
            'id="annualDistributionRangeValue"',
            'Weather-year variability only; model and measurement uncertainty are not included.',
            "function renderAnnualYearResults(result)",
            "function renderAnnualEnergyDistribution(rows = annualDistributionRows)",
            "function renderAnnualRankedEnergyChart(points, summary, series)",
            "function renderAnnualExceedanceChart(points, summary, series)",
            "const ANNUAL_DISTRIBUTION_MIN_PERCENTILE_YEARS = 5",
            "const ANNUAL_DISTRIBUTION_MIN_EXCEEDANCE_YEARS = 10",
            "annualEnergyQuantile(values, 0.10)",
            "row.complete && row.cdfEligible && Number.isFinite(row[seriesKey])",
            "sourceCoveragePct: annualRowNumber(row, ['source_coverage_pct'])",
            "row.coverageStatus === 'incomplete_source' || (row.complete && row.sourceComplete === false)",
            "label: 'Partial source'",
            "'% source coverage'",
            "tabindex: 0",
            "Empirical steps and points are shown without smoothing.",
        ):
            self.assertIn(marker, self.html)

        for removed in (
            'id="annualCdfChart"',
            "function renderAnnualEnergyCdf(rows)",
            "SolarEdge (solid)",
            "Solectria (dashed)",
            "combined (dotted)",
            "annualIrradiance",
            "applyAnnualInputPlots",
        ):
            self.assertNotIn(removed, self.html)

    @unittest.skipUnless(shutil.which("node"), "Node.js is required")
    def test_known_midc_gap_years_are_prelabelled_partial_in_node(self) -> None:
        helpers = "function dateIsoInTimeZone" + self.html.split(
            "function dateIsoInTimeZone", 1
        )[1].split("\n        function formatAnnualPickerDate", 1)[0]
        script = f"""
const ANNUAL_FIRST_YEAR = 2011;
const ANNUAL_FIRST_DATE = '2011-02-11';
const ANNUAL_KNOWN_PARTIAL_YEAR_NOTES = Object.freeze({{
    2022: 'known source gaps',
    2023: 'known source gaps',
}});
{helpers}
const currentDate = new Date('2026-08-11T12:00:00Z');
console.log(JSON.stringify([2011, 2022, 2023, 2024, 2026].map((year) =>
    annualYearDateRange(year, currentDate)
).concat([2022, 2023].map(annualYearDateRange))));
"""
        completed = subprocess.run(
            [shutil.which("node"), "-e", script],
            check=True,
            capture_output=True,
            text=True,
        )
        ranges = json.loads(completed.stdout)
        self.assertEqual(
            [item["coverageStatus"] for item in ranges[:5]],
            ["partial_start", "incomplete_source", "incomplete_source", "complete", "year_to_date"],
        )
        self.assertEqual(ranges[1]["coverageNote"], "known source gaps")
        self.assertEqual(ranges[2]["coverageNote"], "known source gaps")
        self.assertEqual(ranges[1]["periodStart"], "2022-01-01")
        self.assertEqual(ranges[1]["periodEnd"], "2022-12-31")
        self.assertFalse(ranges[1]["completeCalendarYear"])
        self.assertTrue(ranges[3]["completeCalendarYear"])
        self.assertEqual(ranges[4]["periodEnd"], "2026-08-10")
        self.assertEqual(
            [item["coverageStatus"] for item in ranges[5:]],
            ["incomplete_source", "incomplete_source"],
        )

    @unittest.skipUnless(shutil.which("node"), "Node.js is required")
    def test_annual_distribution_math_and_sample_policy_in_node(self) -> None:
        helpers = "const ANNUAL_DISTRIBUTION_MIN_PERCENTILE_YEARS" + self.html.split(
            "const ANNUAL_DISTRIBUTION_MIN_PERCENTILE_YEARS", 1
        )[1].split("\n        function clearAnnualDistributionChart", 1)[0]
        script = f"""
{helpers}
const values = [100, 200, 300, 400, 500, 600, 700, 800, 900, 1000];
const rows = values.map((value, index) => ({{
    year: 2012 + index,
    complete: true,
    cdfEligible: true,
    combined: value,
    solarEdge: value / 2,
    solectria: value / 2,
}}));
rows.push({{year: 2011, complete: false, cdfEligible: false, combined: 50}});
rows.push({{year: 2022, complete: true, cdfEligible: false, combined: 1100}});
rows.push({{year: 2023, complete: true, cdfEligible: true, combined: NaN}});
const ties = annualDistributionPoints([
    {{year: 2020, complete: true, cdfEligible: true, combined: 500}},
    {{year: 2019, complete: true, cdfEligible: true, combined: 500}},
], 'combined');
const equalDomain = annualDistributionDomain([500, 500]);
const exceedancePoints = annualExceedancePoints(annualDistributionPoints(rows, 'combined'));
const exceedancePath = annualExceedanceStepPath(exceedancePoints, [0, 1100], (value) => value, (probability) => probability);
console.log(JSON.stringify({{
    p90: annualEnergyQuantile(values, 0.10),
    p50: annualEnergyQuantile(values, 0.50),
    includedYears: annualDistributionPoints(rows, 'combined').map((point) => point.year),
    selectedSeriesValue: annualDistributionPoints(rows, 'solarEdge')[0].value,
    tieYears: ties.map((point) => point.year),
    policies: [4, 5, 9, 10].map(annualDistributionPolicy),
    equalDomainExpands: equalDomain[0] < 500 && equalDomain[1] > 500,
    narrowDomainTickDigits: annualDistributionTickDigits([499980, 500020]),
    exceedancePathStarts: exceedancePath.startsWith('M 0 1 H 100 V 0.9 H 200 V 0.8'),
    exceedancePathEnds: exceedancePath.endsWith('H 1000 V 0 H 1100'),
}}));
"""
        completed = subprocess.run(
            [shutil.which("node"), "-e", script],
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["p90"], 190)
        self.assertEqual(payload["p50"], 550)
        self.assertEqual(payload["includedYears"], list(range(2012, 2022)))
        self.assertEqual(payload["selectedSeriesValue"], 50)
        self.assertEqual(payload["tieYears"], [2019, 2020])
        self.assertEqual(
            payload["policies"],
            [
                {
                    "showPercentiles": False,
                    "p90Provisional": False,
                    "showP90Reference": False,
                    "allowExceedance": False,
                },
                {
                    "showPercentiles": True,
                    "p90Provisional": True,
                    "showP90Reference": False,
                    "allowExceedance": False,
                },
                {
                    "showPercentiles": True,
                    "p90Provisional": True,
                    "showP90Reference": False,
                    "allowExceedance": False,
                },
                {
                    "showPercentiles": True,
                    "p90Provisional": False,
                    "showP90Reference": True,
                    "allowExceedance": True,
                },
            ],
        )
        self.assertTrue(payload["equalDomainExpands"])
        self.assertGreaterEqual(payload["narrowDomainTickDigits"], 2)
        self.assertTrue(payload["exceedancePathStarts"])
        self.assertTrue(payload["exceedancePathEnds"])

    def test_validation_dates_reset_after_cached_form_restore(self) -> None:
        for marker in (
            "function applyValidationDateDefaults()",
            "fromInput.value = '2025-12-12'",
            "dateIsoInTimeZone()",
            "timeZone = 'America/Denver'",
            "toInput.max = today",
        ):
            self.assertIn(marker, self.html)
        restore = self.html.split("async function restoreDashboardState()", 1)[1].split(
            "function invalidateAnnualRequestFromFormEdit", 1
        )[0]
        defaults = restore.index("applyValidationDateDefaults()")
        self.assertLess(restore.index("applyFormState(saved.form)"), defaults)
        self.assertIn(
            "const hasRestoredValidationContext = !!latestJobId || !!latestResult || !!pendingCalibrationReview",
            restore,
        )
        self.assertIn("if (!hasRestoredValidationContext)", restore)

    def test_annual_latest_day_uses_fixed_mst_not_daylight_time(self) -> None:
        self.assertIn("function annualCurrentYear(value = new Date())", self.html)
        self.assertIn("function annualLatestAvailableDate(value = new Date())", self.html)
        self.assertGreaterEqual(self.html.count("dateIsoInTimeZone(value, 'Etc/GMT+7')"), 2)

    def test_missing_fall_uses_inline_server_bound_confirmation(self) -> None:
        for marker in (
            'id="annualFallbackDrawer"',
            'role="region"',
            'id="annualFallbackSolarEdgeFactor"',
            'id="annualFallbackSolectriaFactor"',
            'id="annualFallbackModifiedSettings"',
            ">Use Spring for Fall</button>",
            ">Cancel run</button>",
            "code === 'seasonal_fallback_confirmation_required'",
            "No annual job or MIDC download has started.",
            "accepted: true",
            "source_season: 'spring'",
            "target_season: 'fall'",
            "confirmation_context_sha256: pending.confirmation_context_sha256",
            "function cancelAnnualFallbackConfirmation()",
            "event.key === 'Escape'",
            "clearAnnualFallbackConfirmation();",
        ):
            self.assertIn(marker, self.html)

        annual_configuration = self.html.split(
            '<div class="annual-config-grid">', 1
        )[1].split('<div class="configuration-actions">', 1)[0]
        self.assertLess(
            annual_configuration.index('id="annualSeasonalFactorRows"'),
            annual_configuration.index('id="annualFallbackDrawer"'),
        )

        fallback_visibility = self.html.split(
            "function setAnnualFallbackVisible", 1
        )[1].split("\n        function ", 1)[0]
        for removed in (
            'id="annualFallbackBackdrop"',
            'aria-modal="true"',
        ):
            self.assertNotIn(removed, annual_configuration)
        for removed in (
            "annualFallbackElements.backdrop",
            "document.body.classList.toggle('annual-fallback-open'",
            "drawer.inert",
        ):
            self.assertNotIn(removed, self.html)
        for removed in (
            "event.key !== 'Tab'",
            "querySelectorAll('button:not([disabled])",
        ):
            self.assertNotIn(removed, fallback_visibility)
        self.assertNotIn("backdrop", fallback_visibility)

        submit = self.html.split("async function submitAnnualRequest(body", 1)[1].split(
            "\n        function ", 1
        )[0]
        self.assertLess(
            submit.index("code === 'seasonal_fallback_confirmation_required'"),
            submit.index("annualLatestJobId = job_id"),
        )

    def test_confirmed_fall_substitution_updates_coverage_and_factors(self) -> None:
        for marker in (
            "let annualSeasonalFallbackDisplay = null",
            "function normalizeAnnualSeasonalFallbackDisplay(value)",
            "function activeAnnualSeasonalFallback(baseline)",
            "factors: { solaredge: solarEdge, solectria }",
            "state.classList.toggle('substituted', substituted)",
            "substituted ? 'Spring copied'",
            "Fall now uses the exact Spring factors shown above for this annual run.",
            'id="annualFactorCoverage" aria-label="Calibration season coverage" aria-live="polite"',
            'data-annual-season="fall" tabindex="-1"',
            "annualSeasonalFallbackDisplay,",
            "saved.annualSeasonalFallbackDisplay",
            ".annual-season-state.substituted",
        ):
            self.assertIn(marker, self.html)

        factor_value = self.html.split(
            "function annualFactorValue", 1
        )[1].split("\n        function ", 1)[0]
        self.assertIn("activeAnnualSeasonalFallback(baseline)", factor_value)
        self.assertIn("fallback.factors[system]", factor_value)

        coverage = self.html.split(
            "function annualSeasonCovered", 1
        )[1].split("\n        function ", 1)[0]
        self.assertIn("fallback?.target_season === season", coverage)
        self.assertIn("return true", coverage)

        confirmation = self.html.split(
            "async function confirmAnnualFallback()", 1
        )[1].split("\n        function ", 1)[0]
        self.assertLess(
            confirmation.index("setAnnualSeasonalFallbackDisplay(pending)"),
            confirmation.index("await submitAnnualRequest(pending.body"),
        )
        self.assertIn(
            "document.querySelector('[data-annual-season=\"fall\"]')?.focus?.()",
            confirmation,
        )

        invalidation = self.html.split(
            "function invalidateAnnualRequestFromFormEdit()", 1
        )[1].split("\n        document.querySelectorAll", 1)[0]
        self.assertIn("clearAnnualSeasonalFallbackDisplay()", invalidation)

        restore = self.html.split(
            "function restoreAnnualCalibrationSettings()", 1
        )[1].split("\n        function ", 1)[0]
        self.assertIn("clearAnnualSeasonalFallbackDisplay()", restore)

        poll = self.html.split(
            "async function pollAnnualStatus", 1
        )[1].split("\n        runBtn.addEventListener", 1)[0]
        self.assertIn("if (data.state === 'error') {\n                    clearAnnualSeasonalFallbackDisplay();", poll)
        self.assertIn("if (data.state === 'cancelled' || data.state === 'interrupted') {\n                    clearAnnualSeasonalFallbackDisplay();", poll)

    def test_results_expose_both_outputs_and_application_audit(self) -> None:
        for marker in (
            'id="annualStatSePhysics"',
            'id="annualStatSolPhysics"',
            'id="annualResultCalibration"',
            'id="annualResultAppliedFactors"',
            'id="annualResultSettingDetails"',
            "s.calibration_adjusted",
            "s.physics_only",
            "result?.calibration_application",
            "application.settings_deltas",
            "application.seasonal_factors",
            "application.baseline_job_id",
            "'Fall used Spring substitute'",
            "setAnnualExcelLink(result.excel, result.excel_filename)",
        ):
            self.assertIn(marker, self.html)

    def test_layout_and_confirmation_are_responsive(self) -> None:
        for marker in (
            "grid-template-areas:",
            '"window seasonal"',
            '"settings seasonal"',
            '"settings fallback"',
            ".annual-fallback-drawer",
            "grid-area: fallback",
            "@media (max-width: 560px)",
        ):
            self.assertIn(marker, self.html)

        fallback_css = self.html.split(".annual-fallback-drawer {", 1)[1].split(
            "}", 1
        )[0]
        self.assertNotIn("position: fixed", fallback_css)
        self.assertNotIn("height: 100dvh", fallback_css)
        self.assertNotIn("transform:", fallback_css)

    def test_technoeconomic_copy_has_no_em_dash_or_placeholder_financing_note(self) -> None:
        technoeconomic_panel = self.html.split(
            '<div class="technoeconomic-only" id="technoeconomicPanel">', 1
        )[1].split(
            "<!-- Technoeconomic controls are canonical source markup", 1
        )[0]

        self.assertNotIn("—", technoeconomic_panel)
        self.assertNotIn(
            "financing assumptions are intentionally left to the user for this placeholder.",
            technoeconomic_panel,
        )

    @unittest.skipUnless(shutil.which("node"), "Node.js is required")
    def test_annual_source_coverage_helpers_fail_closed_in_node(self) -> None:
        normalization = self.html.split("function annualRowNumber(row, names)", 1)[
            1
        ].split("\n        function formatAnnualEnergy", 1)[0]
        coverage = self.html.split("function formatAnnualResultDate(value)", 1)[
            1
        ].split("\n        function clearAnnualYearResults", 1)[0]
        script = f"""
function annualRowNumber(row, names){normalization}
function formatAnnualResultDate(value){coverage}
const base = {{
    year: 2022,
    period_start: '2022-01-01',
    period_end: '2022-12-31',
    complete_calendar_year: true,
    coverage_status: 'complete',
    cdf_eligible: true,
}};
const complete = normalizedAnnualEnergyRow({{...base, source_complete: true}});
const partial = normalizedAnnualEnergyRow({{
    ...base,
    source_complete: false,
    source_coverage_pct: 97.785,
    coverage_status: 'incomplete_source',
    cdf_eligible: false,
}});
const legacy = normalizedAnnualEnergyRow(base);
console.log(JSON.stringify({{
    completeEligible: complete.cdfEligible,
    partialEligible: partial.cdfEligible,
    partialCopy: annualCoverageCopy(partial),
    legacyEligible: legacy.cdfEligible,
    legacyCopy: annualCoverageCopy(legacy),
}}));
"""
        completed = subprocess.run(
            [shutil.which("node"), "-e", script],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            {
                "completeEligible": True,
                "partialEligible": False,
                "partialCopy": {
                    "label": "Partial source",
                    "detail": "97.8% source coverage - Jan 1 - Dec 31",
                },
                "legacyEligible": False,
                "legacyCopy": {
                    "label": "Coverage unknown",
                    "detail": "Re-run to verify MIDC source coverage - Jan 1 - Dec 31",
                },
            },
            json.loads(completed.stdout),
        )

if __name__ == "__main__":
    unittest.main()
