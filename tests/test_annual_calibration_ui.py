from __future__ import annotations

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
            '<option value="minutes">minutes</option>',
            '<option value="hours" selected>hours</option>',
            '<option value="days">days</option>',
        ):
            self.assertIn(marker, self.html)

        form_state = self.html.split("function getAnnualFormState()", 1)[1].split(
            "\n        function ", 1
        )[0]
        self.assertIn("annualIntervalValue", form_state)
        self.assertIn("annualIntervalUnit", form_state)

        apply_state = self.html.split("function applyAnnualFormState(form)", 1)[
            1
        ].split("\n        function ", 1)[0]
        self.assertIn("setValue('annualIntervalValue', form.intervalValue)", apply_state)
        self.assertIn("setValue('annualIntervalUnit', form.intervalUnit)", apply_state)

        request_builder = self.html.split("function buildAnnualRequest()", 1)[
            1
        ].split("\n        async function ", 1)[0]
        self.assertIn("interval_value:", request_builder)
        self.assertIn("interval_unit:", request_builder)

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
            "annualFallbackElements.backdrop",
            "document.body.classList.toggle('annual-fallback-open'",
            "drawer.inert",
            "event.key !== 'Tab'",
            "querySelectorAll('button:not([disabled])",
        ):
            self.assertNotIn(removed, self.html)
        self.assertNotIn("backdrop", fallback_visibility)

        submit = self.html.split("async function submitAnnualRequest(body", 1)[1].split(
            "\n        function ", 1
        )[0]
        self.assertLess(
            submit.index("code === 'seasonal_fallback_confirmation_required'"),
            submit.index("annualLatestJobId = job_id"),
        )

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
            "<!-- Functional contract: every original form id", 1
        )[0]

        self.assertNotIn("—", technoeconomic_panel)
        self.assertNotIn(
            "financing assumptions are intentionally left to the user for this placeholder.",
            technoeconomic_panel,
        )


if __name__ == "__main__":
    unittest.main()
