from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import subprocess
import unittest

from sbepv import dashboard


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class TechnoeconomicFrontendTests(unittest.TestCase):
    """Contract tests for the server-authoritative Phase 5 TEA workspace."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.html = dashboard.assemble_dashboard_html(PROJECT_ROOT)
        cls.markup = (
            PROJECT_ROOT / "frontend" / "html" / "50-technoeconomic.html"
        ).read_text(encoding="utf-8")
        cls.script_path = (
            PROJECT_ROOT / "frontend" / "js" / "06-technoeconomic.js"
        )
        cls.script = cls.script_path.read_text(encoding="utf-8")
        cls.styles = (
            PROJECT_ROOT / "frontend" / "css" / "04-technoeconomic.css"
        ).read_text(encoding="utf-8")
        cls.bindings = (
            PROJECT_ROOT / "frontend" / "js" / "00-help-tips-and-elements.js"
        ).read_text(encoding="utf-8")
        cls.mode_script = (
            PROJECT_ROOT / "frontend" / "js" / "01-progress-and-mode.js"
        ).read_text(encoding="utf-8")
        cls.form_script = (
            PROJECT_ROOT / "frontend" / "js" / "03-form-reading-and-plots.js"
        ).read_text(encoding="utf-8")
        cls.state_script = (
            PROJECT_ROOT / "frontend" / "js" / "08-dashboard-state.js"
        ).read_text(encoding="utf-8")
        cls.restore_script = (
            PROJECT_ROOT / "frontend" / "js" / "19-chat-send-and-cache.js"
        ).read_text(encoding="utf-8")
        cls.annual_run_script = (
            PROJECT_ROOT / "frontend" / "js" / "10-annual-run.js"
        ).read_text(encoding="utf-8")
        cls.agent_actions = (
            PROJECT_ROOT / "frontend" / "js" / "18-agent-actions.js"
        ).read_text(encoding="utf-8")
        cls.chat_rendering = (
            PROJECT_ROOT / "frontend" / "js" / "13-chat-message-rendering.js"
        ).read_text(encoding="utf-8")
        cls.agent_state = (
            PROJECT_ROOT / "frontend" / "js" / "14-agent-state.js"
        ).read_text(encoding="utf-8")
        cls.saved_results = (
            PROJECT_ROOT / "frontend" / "js" / "20-saved-results.js"
        ).read_text(encoding="utf-8")
        cls.proxy = (PROJECT_ROOT / "lib" / "render-proxy.ts").read_text(
            encoding="utf-8"
        )

    def run_node(self, assertions: str) -> dict:
        node = shutil.which("node")
        if not node:
            self.skipTest("Node.js is required")
        completed = subprocess.run(
            [node, "-"],
            cwd=PROJECT_ROOT,
            check=False,
            capture_output=True,
            text=True,
            input=self.script + "\n" + assertions,
            timeout=30,
        )
        self.assertEqual(0, completed.returncode, completed.stderr)
        return json.loads(completed.stdout)

    @staticmethod
    def tea_fixture_helpers() -> str:
        return r"""
function teaEvidence(ref) {
  return {
    evidence_class: 'direct_quote_or_primary_document',
    citation: {
      title: 'Primary source', organization: 'Source organization', url: '',
      stable_reference: ref, publication_or_as_of_date: '2025-01-02',
      accessed_date: '2026-08-14',
      excerpt_or_derivation_note: 'Documented fixture input.',
      preservation_mode: 'metadata_excerpt_only',
      user_supplied_content_sha256: '',
      metadata_only_rationale: 'Metadata and excerpt are sufficient for this fixture.',
    },
    explicit_acceptance: false, acceptance_rationale: '',
  };
}

function teaBase(sourceId, basis) {
  const draft = technoeconomicDefaultDraft();
  Object.assign(draft, {
    source_annual_job_id: sourceId, basis, n: '1000',
    seed: '9007199254740991', cost_year: '2025', project_life_years: '25',
  });
  draft.project_life_evidence = teaEvidence('LIFE');
  draft.discount_rate = {
    unit: 'real_fraction_per_year',
    distribution: {family: 'fixed', value: '0.05'}, evidence: teaEvidence('RATE'),
  };
  draft.shared_degradation = {
    unit: 'real_fraction_per_year',
    distribution: {family: 'fixed', value: '0.005'}, evidence: teaEvidence('DEG'),
  };
  draft.cost_lines.forEach((line, index) => {
    line.distribution = {family: 'fixed', value: index ? '1.30' : '1.20'};
    line.original_unit = basis === 'solartac_site' ? 'usd_total' : 'usd_per_wdc';
    line.normalized_unit = basis === 'solartac_site'
      ? (line.cost_type.startsWith('recurring_')
        ? 'usd_per_applied_w_year' : 'usd_per_applied_w')
      : (line.cost_type.startsWith('recurring_') ? 'usd_per_wdc_year' : 'usd_per_wdc');
    line.normalization_method = basis === 'solartac_site'
      ? 'divide_by_frozen_applied_capacity_w' : 'already_normalized_per_wdc';
    line.normalization_derivation = basis === 'solartac_site'
      ? 'Source total divided by frozen Annual applied capacity.'
      : 'Commercial source already reports constant-dollar USD per Wdc.';
    line.constant_dollar_cost_year = '2025';
    line.currency_year_normalization = {
      method: 'same_year_no_adjustment', source_cost_year: '2025',
      target_constant_dollar_cost_year: '2025',
      submitted_distribution_basis: 'target_constant_dollar_year',
      index_identity: 'not_applicable_same_year', index_factor: '1',
      derivation: 'No price adjustment because source and target years match.',
      index_source_evidence: teaEvidence(`INDEX-${index}`),
    };
    line.evidence = teaEvidence(`COST-${index}`);
  });
  return draft;
}

function solarTacDraft() {
  const draft = teaBase('annual-source-1', 'solartac_site');
  draft.cost_lines[0].distribution = {family: 'fixed', value: '1000'};
  draft.cost_lines[1].distribution = {family: 'uniform', low: '900', high: '1100'};
  draft.discount_rate = {
    unit: 'real_fraction_per_year',
    distribution: {family: 'triangular', low: '0.03', mode: '0.05', high: '0.07'},
    evidence: teaEvidence('RATE'),
  };
  draft.shared_degradation = {
    unit: 'real_fraction_per_year',
    distribution: {
      family: 'bounded_normal', low: '0.002', high: '0.008',
      mean: '0.005', sd: '0.001',
    },
    evidence: teaEvidence('DEG'),
  };
  draft.transfer_enabled = false;
  return draft;
}

function commercialDraft(transferEnabled = true) {
  const draft = teaBase('annual-source-2', 'commercial_representative');
  draft.seed = '7';
  draft.commercial_reference_design = {
    design_id: 'commercial-reference-550kw', reference_wdc: '550000',
    module_model: 'Example 550 W module', module_stc_wdc: '550', module_count: '1000',
    constant_dollar_cost_year: '2025',
    solectria: {
      optimizer_count: '0', inverter_count: '5', transformer_count: '1',
      dc_ac_ratio: '1.25', inverter_loading_ratio: '1.10',
      inverter_topology: 'Five central inverters',
      transformer_topology: 'One shared transformer', bos_scope: 'Complete DC and AC BOS',
      labor_productivity_and_rates: 'Documented commercial crew rates',
      commissioning_scope: 'Standard acceptance testing',
    },
    solaredge: {
      optimizer_count: '1000', inverter_count: '10', transformer_count: '1',
      dc_ac_ratio: '1.25', inverter_loading_ratio: '1.10',
      inverter_topology: 'Ten string inverters with module optimizers',
      transformer_topology: 'One shared transformer', bos_scope: 'Complete DC and AC BOS',
      labor_productivity_and_rates: 'Documented commercial crew rates',
      commissioning_scope: 'Standard acceptance testing',
    },
    normalization_derivation: 'Reference Wdc equals 1,000 modules times 550 Wdc.',
    evidence: teaEvidence('DESIGN'),
  };
  draft.transfer_enabled = transferEnabled;
  if (transferEnabled) {
    draft.commercial_transfer = technoeconomicDefaultCommercialTransfer();
    Object.assign(draft.commercial_transfer, {
      explicit_attestation: true, attested_by: 'Test analyst',
      attested_at: '2026-08-14T12:00:00-06:00',
      attestation_rationale: 'All listed mechanisms were reviewed against the commercial design.',
    });
    draft.commercial_transfer.baseline_factor = {
      unit: 'dimensionless_multiplier',
      distribution: {family: 'fixed', value: '1'},
      evidence: teaEvidence('TRANSFER-BASE'),
    };
    draft.commercial_transfer.incremental_factor = {
      unit: 'dimensionless_multiplier',
      distribution: {family: 'uniform', low: '0.9', high: '1.1'},
      evidence: teaEvidence('TRANSFER-INCREMENT'),
    };
    draft.commercial_transfer.mechanisms.forEach((item, index) => {
      item.status = 'supported';
      item.rationale = 'Mechanism reviewed and supported for the commercial design.';
      item.evidence = teaEvidence(`MECH-${index}`);
    });
  }
  return draft;
}
"""

    def test_probabilistic_workspace_replaces_legacy_browser_calculator(self) -> None:
        combined = self.markup + "\n" + self.script
        for legacy in (
            "baselineAnnualizedCost",
            "optimizedAnnualizedCost",
            "calculateTechnoeconomicMetrics",
            "technoeconomicIsFullYear",
            "technoeconomicSourceCoverageIssue",
            "Enter annualized totals directly",
        ):
            self.assertNotIn(legacy, combined)

        for source_coupling in (
            "annualLatestResult?.stats",
            "result?.annual_energy_by_year || result?.stats?.annual_energy_by_year",
        ):
            self.assertNotIn(source_coupling, self.script)

        compatibility_renderer = self.script.split(
            "function renderTechnoeconomicAnalysis", 1
        )[1].split("function technoeconomicSafeMetricContext", 1)[0]
        self.assertIn("_legacyResultIgnored", compatibility_renderer)
        self.assertIn("technoeconomicJob?.state === 'done'", compatibility_renderer)
        self.assertNotIn("annualLatestResult", compatibility_renderer)
        self.assertNotIn("_legacyResultIgnored.", compatibility_renderer)

        for element_id in (
            "technoeconomicForm",
            "technoeconomicSourceSelect",
            "technoeconomicBasis",
            "technoeconomicRealizations",
            "technoeconomicSeed",
            "technoeconomicCostLines",
            "technoeconomicSubmitBtn",
            "technoeconomicJobPanel",
            "technoeconomicResults",
            "technoeconomicConfirmDialog",
        ):
            self.assertEqual(self.html.count(f'id="{element_id}"'), 1, element_id)

    def test_shared_bootstrap_has_no_removed_deterministic_input_listeners(self) -> None:
        for legacy in (
            "baselineAnnualizedCost",
            "optimizedAnnualizedCost",
            "calculateTechnoeconomicMetrics",
            "technoeconomicSourceCoverageIssue",
        ):
            self.assertNotIn(legacy, self.annual_run_script)
            self.assertNotIn(legacy, self.bindings)

        self.assertIn("initializeTechnoeconomicWorkspace();", self.annual_run_script)
        self.assertLess(
            self.annual_run_script.index("initializeTechnoeconomicWorkspace();"),
            self.annual_run_script.index("technoeconomicTab.addEventListener"),
        )

    def test_guided_solartac_controls_separate_system_financials_and_hide_internal_editor(
        self,
    ) -> None:
        self.assertRegex(
            self.markup,
            r'<select id="technoeconomicSourceSelect"[^>]*\brequired\b',
        )
        self.assertIn(
            'aria-describedby="technoeconomicSourceHelp technoeconomicSourceStatus"',
            self.markup,
        )
        self.assertIn("Selection is explicit", self.markup)
        self.assertIn("Modeled AC operating limit", self.markup)
        self.assertIn("operating settings are already reflected", self.markup)
        self.assertIn("Applied capacity", self.markup)
        self.assertNotIn("<dt>Installed DC capacity</dt>", self.markup)
        self.assertNotIn("<dt>DC nameplate</dt>", self.markup)
        self.assertIn("Typical annual energy", self.markup)
        self.assertIn("Yearly modeled energy", self.markup)
        self.assertIn("Solectria (MWh AC)", self.markup)
        self.assertIn("SolarEdge (MWh AC)", self.markup)
        self.assertIn("SolarTAC site", self.markup)
        self.assertIn("Commercial representative", self.markup)
        self.assertIn("SolarTAC and commercial assumptions are never blended", self.markup)

        source_ids = (
            "technoeconomicSourceDetails",
            "technoeconomicSourceOperatingLimit",
            "technoeconomicSourceCapacityNote",
            "technoeconomicSourceSolectriaHeading",
            "technoeconomicSourceSolectriaCapacity",
            "technoeconomicSourceSolectriaEnergy",
            "technoeconomicSourceSolarEdgeHeading",
            "technoeconomicSourceSolarEdgeCapacity",
            "technoeconomicSourceSolarEdgeEnergy",
            "technoeconomicSourceEnergyRows",
        )
        for element_id in source_ids:
            self.assertEqual(self.markup.count(f'id="{element_id}"'), 1, element_id)

        source_summary = self.markup.split(
            'id="technoeconomicSourceDetails"', 1
        )[1].split('id="technoeconomicGuidedPanel"', 1)[0]
        for internal_label in (
            "Annual job",
            "Capacity manifest",
            "Source snapshot SHA-256",
            "Calibration baseline",
            "Completed",
        ):
            self.assertNotIn(internal_label, source_summary)

        guided_ids = (
            "technoeconomicGuidedPanel",
            "technoeconomicGuidedCommonHeading",
            "technoeconomicGuidedCostYear",
            "technoeconomicGuidedProjectLife",
            "technoeconomicGuidedDiscount",
            "technoeconomicGuidedDegradation",
            "technoeconomicGuidedSolectriaHeading",
            "technoeconomicGuidedSolectriaCapex",
            "technoeconomicGuidedSolectriaOm",
            "technoeconomicGuidedSolectriaCapacity",
            "technoeconomicGuidedSolectriaEnergy",
            "technoeconomicGuidedSolectriaEstimate",
            "technoeconomicGuidedSolectriaLifecycleCost",
            "technoeconomicGuidedSolectriaAnnualizedCost",
            "technoeconomicGuidedSolectriaLcoeRange",
            "technoeconomicGuidedSolarEdgeHeading",
            "technoeconomicGuidedSolarEdgeCapex",
            "technoeconomicGuidedSolarEdgeOm",
            "technoeconomicGuidedSolarEdgeCapacity",
            "technoeconomicGuidedSolarEdgeEnergy",
            "technoeconomicGuidedSolarEdgeEstimate",
            "technoeconomicGuidedSolarEdgeLifecycleCost",
            "technoeconomicGuidedSolarEdgeAnnualizedCost",
            "technoeconomicGuidedSolarEdgeLcoeRange",
            "technoeconomicGuidedAssumptionNote",
            "technoeconomicGuidedAccept",
            "technoeconomicGuidedRanges",
            "technoeconomicAdvancedDetails",
            "technoeconomicUseGuidedBtn",
            "technoeconomicLegacyDraftNotice",
            "technoeconomicEntryModeStatus",
            "technoeconomicSubmitPanel",
        )
        for element_id in guided_ids:
            self.assertEqual(self.markup.count(f'id="{element_id}"'), 1, element_id)

        for stem in (
            "Discount",
            "Degradation",
            "SolectriaCapex",
            "SolectriaOm",
            "SolarEdgeCapex",
            "SolarEdgeOm",
        ):
            for suffix in ("Low", "High"):
                element_id = f"technoeconomicGuided{stem}{suffix}"
                self.assertEqual(self.markup.count(f'id="{element_id}"'), 1, element_id)

        guided_ranges = re.search(
            r'<details\b(?=[^>]*\bid="technoeconomicGuidedRanges")[^>]*>',
            self.markup,
        )
        self.assertIsNotNone(guided_ranges)
        assert guided_ranges is not None
        self.assertNotRegex(guided_ranges.group(0), r"\sopen(?:\s|=|>)")

        internal_editor = re.search(
            r'<details\b(?=[^>]*\bid="technoeconomicAdvancedDetails")[^>]*>',
            self.markup,
        )
        self.assertIsNotNone(internal_editor)
        assert internal_editor is not None
        self.assertRegex(internal_editor.group(0), r"\shidden(?:\s|=|>)")
        self.assertRegex(internal_editor.group(0), r"\sinert(?:\s|=|>)")
        self.assertNotRegex(internal_editor.group(0), r"\sopen(?:\s|=|>)")

        self.assertRegex(
            self.markup,
            r'<input[^>]*\bid="technoeconomicGuidedAccept"[^>]*\btype="checkbox"',
        )
        self.assertRegex(
            self.markup,
            r'<button[^>]*\bid="technoeconomicUseGuidedBtn"[^>]*\btype="button"',
        )
        self.assertIn("Start new Guided SolarTAC form", self.markup)
        self.assertRegex(
            self.markup,
            r'id="technoeconomicLegacyDraftNotice"[^>]*\bhidden\b',
        )
        self.assertRegex(
            self.markup,
            r'id="technoeconomicEntryModeStatus"[^>]*\brole="status"',
        )
        self.assertRegex(
            self.markup,
            r'<textarea[^>]*\bid="technoeconomicGuidedAssumptionNote"'
            r'[^>]*\bmaxlength="4000"[^>]*\brequired\b',
        )
        for element_id in (
            "technoeconomicGuidedCostYear",
            "technoeconomicGuidedProjectLife",
            "technoeconomicGuidedDiscount",
            "technoeconomicGuidedSolectriaCapex",
            "technoeconomicGuidedSolectriaOm",
            "technoeconomicGuidedSolarEdgeCapex",
            "technoeconomicGuidedSolarEdgeOm",
        ):
            self.assertRegex(
                self.markup,
                rf'<input[^>]*\bid="{element_id}"[^>]*\brequired\b',
                element_id,
            )
        degradation_input = re.search(
            r'<input[^>]*\bid="technoeconomicGuidedDegradation"[^>]*>',
            self.markup,
        )
        self.assertIsNotNone(degradation_input)
        assert degradation_input is not None
        self.assertNotRegex(degradation_input.group(0), r"\brequired\b")
        for element_id in (
            "technoeconomicGuidedSolectriaCapex",
            "technoeconomicGuidedSolectriaOm",
            "technoeconomicGuidedSolarEdgeCapex",
            "technoeconomicGuidedSolarEdgeOm",
        ):
            self.assertRegex(
                self.markup,
                rf'<input[^>]*\bid="{element_id}"[^>]*\bmin="0"',
                element_id,
            )
        self.assertIn("Enter 5 for a 5% real annual rate", self.markup)
        self.assertIn("Leave blank to use 0%", self.markup)
        self.assertIn("$ total", self.markup)
        self.assertIn("$/year", self.markup)
        self.assertIn("Typical annualized cost", self.markup)
        self.assertIn("Estimated LCOE range", self.markup)
        self.assertIn("final P5/P50/P95 results come only from the server run", self.markup)
        for removed_id in (
            "technoeconomicGuidedBaseCapex",
            "technoeconomicGuidedBaseOm",
            "technoeconomicGuidedIncrementalCapex",
            "technoeconomicGuidedIncrementalOm",
            "technoeconomicApplyReferenceBtn",
            "technoeconomicReferenceStatus",
        ):
            self.assertNotIn(f'id="{removed_id}"', self.markup)
        advanced_index = self.markup.index('id="technoeconomicAdvancedDetails"')
        for advanced_id in (
            "technoeconomicBasis",
            "technoeconomicRealizations",
            "technoeconomicSeed",
            "technoeconomicAssumptionEditors",
        ):
            self.assertGreater(
                self.markup.index(f'id="{advanced_id}"'),
                advanced_index,
                advanced_id,
            )

        # Sampling remains in the hidden internal request editor for strict
        # serialization and legacy-draft preservation, not end-user editing.
        self.assertRegex(
            self.markup,
            r'<input id="technoeconomicRealizations"[^>]*\bmin="1"'
            r'[^>]*\bmax="100000"[^>]*\bstep="1"[^>]*\bvalue="10000"',
        )
        self.assertRegex(
            self.markup,
            r'<input id="technoeconomicSeed"[^>]*\btype="text"'
            r'[^>]*\bpattern="\[0-9\]\+"[^>]*\bmaxlength="20"',
        )
        self.assertIn("9,007,199,254,740,991", self.markup)
        self.assertIn("browser never rounds the reproducibility seed", self.markup)

    def test_personal_attribution_is_absent_from_tea_code(self) -> None:
        prohibited = "cli" + "ff"
        for label, content in (
            ("markup", self.markup),
            ("script", self.script),
            ("styles", self.styles),
            ("bindings", self.bindings),
        ):
            self.assertNotIn(prohibited, content.lower(), label)

    def test_markup_ids_references_and_dom_bindings_resolve(self) -> None:
        element_ids = re.findall(r'\bid="([^"]+)"', self.markup)
        self.assertEqual(len(element_ids), len(set(element_ids)))
        known_ids = set(element_ids)

        references: set[str] = set()
        for value in re.findall(
            r'\b(?:for|aria-labelledby|aria-describedby)="([^"]+)"',
            self.markup,
        ):
            references.update(value.split())
        self.assertEqual(set(), references - known_ids)

        binding_block = self.bindings.split(
            "const technoeconomicPanel =", 1
        )[1].split("const annualRunBtn =", 1)[0]
        bound_ids = set(re.findall(r"getElementById\('([^']+)'\)", binding_block))
        assembled_ids = set(re.findall(r'\bid="([^"]+)"', self.html))
        self.assertGreaterEqual(len(bound_ids), 60)
        self.assertEqual(set(), bound_ids - assembled_ids)

    def test_accessible_results_tables_figures_progress_and_confirmation(self) -> None:
        for marker in (
            '<form class="tea-form" id="technoeconomicForm" novalidate>',
            "<fieldset",
            "Guided SolarTAC setup",
            '<details class="tea-advanced-workspace" id="technoeconomicAdvancedDetails" hidden inert>',
            "<legend>Basis and reproducibility controls</legend>",
            '<progress id="technoeconomicProgress" max="100" value="0">',
            'role="status" aria-live="polite" aria-atomic="true"',
            'id="technoeconomicFormErrors" role="alert" aria-live="assertive"',
            '<dialog class="tea-confirm-dialog" id="technoeconomicConfirmDialog"',
            'aria-labelledby="technoeconomicConfirmHeading"',
            'aria-describedby="technoeconomicConfirmDescription"',
            '<caption>Per-weather-year technoeconomic summary</caption>',
            '<caption>Sensitivity model entries and exclusions</caption>',
            '<caption>Realization checkpoint percentile evidence</caption>',
            'role="region" aria-labelledby="technoeconomicPerYearHeading" tabindex="0"',
            'role="region" aria-labelledby="technoeconomicSensitivityHeading" tabindex="0"',
            'role="region" aria-labelledby="technoeconomicConvergenceHeading" tabindex="0"',
            "<figure",
            "<figcaption>",
        ):
            self.assertIn(marker, self.markup)

        for image_id in (
            "technoeconomicCdfPlot",
            "technoeconomicSensitivityPlot",
            "technoeconomicConvergencePlot",
        ):
            self.assertRegex(
                self.markup,
                rf'<img id="{image_id}"[^>]+\balt="[^"]+"',
            )

        for table_id in (
            "technoeconomicPerYearTable",
            "technoeconomicSensitivityTable",
            "technoeconomicConvergenceTable",
        ):
            table = self.markup.split(f'id="{table_id}"', 1)[1].split(
                "</table>", 1
            )[0]
            self.assertIn('scope="col"', table)

        self.assertIn("Population and denominator details", self.markup)
        self.assertIn("accessible table records", self.markup)
        self.assertIn("No Annual baseline, model promotion, or comparison", self.markup)

    def test_results_prioritize_decision_and_keep_formulas_last(self) -> None:
        decision_index = self.markup.index('id="technoeconomicDecision"')
        detail_index = self.markup.index(
            "Detailed percentile and outcome evidence"
        )
        audit_index = self.markup.index(
            "Methodology, diagnostics, and audit trail"
        )
        formula_index = self.markup.index('id="technoeconomicFormulaHeading"')
        export_index = self.markup.index('id="technoeconomicXlsxLink"')
        results_end = self.markup.index(
            'id="technoeconomicLegacyDraftNotice"'
        )
        self.assertLess(decision_index, detail_index)
        self.assertLess(detail_index, audit_index)
        self.assertLess(audit_index, export_index)
        self.assertLess(export_index, formula_index)
        self.assertLess(audit_index, formula_index)
        self.assertLess(formula_index, results_end)
        self.assertIn("Lifecycle cost difference · P50", self.script)
        self.assertIn("Lifecycle energy difference · P50", self.script)
        self.assertIn("Joint cost-and-energy advantage", self.script)
        self.assertIn("Decision confidence", self.script)
        self.assertIn("discounted lifecycle cost / discounted lifecycle AC energy", self.markup)
        self.assertIn("SolarEdge lifecycle cost − Solectria lifecycle cost", self.markup)
        audit_close = self.markup.index("</details>", audit_index)
        self.assertGreater(export_index, audit_close)
        self.assertIn("Export workbook", self.markup)

    def test_responsive_reduced_motion_and_high_contrast_styles(self) -> None:
        for marker in (
            ".tea-table-region {",
            "overflow-x: auto",
            "overscroll-behavior-inline: contain",
            ".tea-source-summary {",
            ".tea-source-system-grid,",
            ".tea-system-cost-grid {",
            ".tea-system-estimate[data-state=\"ready\"]",
            ".tea-figure-card img {",
            "max-width: 100%",
            "overflow-wrap: anywhere",
            ".tea-button:focus-visible",
            ".tea-table-region:focus-visible",
            "@media (max-width: 760px)",
            "@media (max-width: 560px)",
            "@media (prefers-reduced-motion: reduce)",
            "@media (forced-colors: active)",
        ):
            self.assertIn(marker, self.styles)

        tablet = self.styles.split("@media (max-width: 760px)", 1)[1].split(
            "@media (max-width: 560px)", 1
        )[0]
        self.assertIn(".tea-control-grid", tablet)
        self.assertIn(".tea-distribution-grid", tablet)
        self.assertIn(".tea-evidence-grid", tablet)
        self.assertIn(".tea-design-grid", tablet)
        self.assertIn(".tea-transfer-grid", tablet)
        self.assertIn(".tea-source-basis-row", tablet)
        self.assertIn(".tea-source-system-grid", tablet)
        self.assertIn(".tea-system-cost-grid", tablet)
        self.assertIn("grid-template-columns: 1fr", tablet)
        self.assertIn(".tea-figure-grid", tablet)

        mobile = self.styles.split("@media (max-width: 560px)", 1)[1].split(
            "@media (prefers-reduced-motion: reduce)", 1
        )[0]
        self.assertIn(".tea-metric-grid", mobile)
        self.assertIn(".tea-tradeoff-grid", mobile)
        self.assertIn(".tea-confirm-summary", mobile)
        self.assertIn(".tea-system-financial-fields", mobile)
        self.assertIn(".tea-system-estimate dl", mobile)
        self.assertIn(".tea-source-system-card", mobile)
        self.assertIn("grid-template-columns: 1fr", mobile)
        self.assertIn("min-height: 44px", mobile)
        self.assertIn("font-size: 16px", mobile)
        self.assertIn(".tea-download-link", mobile)
        self.assertIn("width: 100%", mobile)

        reduced_motion = self.styles.split(
            "@media (prefers-reduced-motion: reduce)", 1
        )[1].split("@media (forced-colors: active)", 1)[0]
        self.assertIn("animation-duration: 0.01ms !important", reduced_motion)
        self.assertIn("animation-iteration-count: 1 !important", reduced_motion)

    def test_solar_agent_model_jobs_and_saved_results_remain_isolated(self) -> None:
        self.assertIn(
            "activeMode = activeView === 'validation' ? 'validation' : 'annual'",
            self.mode_script,
        )
        self.assertIn("Technoeconomic read-only context", self.agent_state)
        self.assertIn("without changing the job", self.chat_rendering)
        self.assertIn("server-authoritative", self.chat_rendering)
        self.assertNotIn("data-saved-results-filter=\"technoeconomic\"", self.html)
        self.assertNotIn("technoeconomic", self.saved_results.lower())

        for forbidden in (
            "/api/jobs/",
            "/promote",
            "/comparison",
            "/api/saved-results",
        ):
            self.assertNotIn(forbidden, self.script)

    @unittest.skipUnless(shutil.which("node"), "Node.js is required")
    def test_solar_agent_receives_only_read_only_public_result_context(self) -> None:
        payload = self.run_node(
            r"""
const assert = require('node:assert/strict');
technoeconomicJob = {
  job_id: 'tea_context', workflow: 'technoeconomic', state: 'done', progress: 100,
  stage: 'Complete', source_annual_job_id: 'annual-source-1',
  request: {private_cost_lines: true}, artifacts: {sealed_calculation: {path: 'private'}},
  result: {
    analysis_basis: 'solartac_site', realization_count: 1000, energy_available: true,
    commercial_transfer_status: 'not_applicable', convergence: {status: 'stable'},
    summaries: {
      DeltaLifecycleCostPerWdc_se_minus_sol_USD_per_Wdc: {
        status: 'available', count: 1000, percentiles: {p5: -2, p50: 1, p95: 3},
        private_realizations: [1, 2, 3],
      },
      energy_classes: {
        status: 'available', probabilities: {
          positive_lifecycle_gain: 0.7, invalid_key_1: 0.3,
        },
      },
      tradeoff_classes: {
        status: 'available', probabilities: {cost_saving_energy_loss: 0.1},
      },
    },
  },
};
const context = getTechnoeconomicChatContext();
assert.equal(context.read_only, true);
assert.equal(context.server_authoritative, true);
assert.equal(context.job_id, 'tea_context');
assert.equal(context.job_state, 'done');
assert.equal(context.realization_count, 1000);
assert.equal(context.summaries.DeltaLifecycleCostPerWdc_se_minus_sol_USD_per_Wdc.p50, 1);
assert.equal('private_realizations' in
  context.summaries.DeltaLifecycleCostPerWdc_se_minus_sol_USD_per_Wdc, false);
assert.equal('request' in context, false);
assert.equal('artifacts' in context, false);
assert.equal('result' in context, false);
assert.equal('invalid_key_1' in context.summaries.energy_classes.probabilities, false);
console.log(JSON.stringify(context));
"""
        )
        self.assertTrue(payload["read_only"])
        self.assertTrue(payload["server_authoritative"])
        self.assertEqual("technoeconomic-chat-context-v1", payload["schema_version"])
        self.assertNotIn("request", payload)
        self.assertNotIn("artifacts", payload)

    def test_proxy_allows_only_the_dedicated_technoeconomic_routes(self) -> None:
        route = re.search(
            r"function isAllowedApiPath\(path: string\[\]\): boolean \{(.*?)\n\}",
            self.proxy,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(route)
        assert route is not None
        source = route.group(1)
        for marker in (
            'path[0] === "technoeconomic"',
            '["sources", "jobs"].includes(path[1])',
            'path[1] === "jobs"',
            'isSafeId(path[2])',
            '["cancel", "retry"].includes(path[3])',
            'path[3] === "exports"',
            '["csv", "xlsx"].includes(path[4])',
            'path[3] === "artifacts"',
            '"cdf_plot"',
            '"sensitivity_plot"',
            '"convergence_plot"',
        ):
            self.assertIn(marker, source)
        self.assertNotIn("sealed_calculation", source)

    @unittest.skipUnless(shutil.which("node"), "Node.js is required")
    def test_default_draft_never_silently_prefills_financial_values(self) -> None:
        payload = self.run_node(
            r"""
const assert = require('node:assert/strict');
const draft = technoeconomicDefaultDraft();
assert.equal(draft.n, '10000');
assert.equal(draft.project_life_years, '');
assert.equal(draft.discount_rate.distribution.value, '');
assert.equal(draft.shared_degradation.distribution.value, '');
assert.ok(draft.cost_lines.length >= 2);
assert.ok(draft.cost_lines.every((line) => line.distribution.value === ''));
const frozenDefault = JSON.stringify(draft);
for (const referenceValue of ['0.02', '0.035', '0.046', '0.05', '0.08', '6500']) {
  assert.equal(frozenDefault.includes(referenceValue), false, referenceValue);
}
assert.equal(frozenDefault.includes('secondary_synthesis'), false);
const serialized = serializeTechnoeconomicRequest(draft, {sources: []});
assert.equal(serialized.valid, false);
assert.ok(serialized.errors.length > 0);
console.log(JSON.stringify({
  valid: serialized.valid,
  errorCount: serialized.errors.length,
  projectLife: draft.project_life_years,
  costValues: draft.cost_lines.map((line) => line.distribution.value),
}));
"""
        )
        self.assertFalse(payload["valid"])
        self.assertGreater(payload["errorCount"], 0)
        self.assertEqual("", payload["projectLife"])
        self.assertTrue(all(value == "" for value in payload["costValues"]))

    @unittest.skipUnless(shutil.which("node"), "Node.js is required")
    def test_guided_helpers_expand_ranges_and_document_evidence(self) -> None:
        payload = self.run_node(
            r"""
const assert = require('node:assert/strict');

const fixed = technoeconomicGuidedDistribution('0.05');
assert.deepEqual(fixed, {
  family: 'fixed', value: '0.05', low: '', mode: '', high: '', mean: '', sd: '',
});
const triangular = technoeconomicGuidedDistribution('0.05', '0.03', '0.07');
assert.deepEqual(triangular, {
  family: 'triangular', value: '', low: '0.03', mode: '0.05', high: '0.07',
  mean: '', sd: '',
});
const percent = technoeconomicGuidedDistribution('5', '3', '7', 100);
assert.deepEqual(percent, {
  family: 'triangular', value: '', low: '0.03', mode: '0.05', high: '0.07',
  mean: '', sd: '',
});

const evidence = technoeconomicGuidedEvidence(
  'Accepted as an analyst-provided provisional assumption for this run.',
  true,
  {date: '2026-08-16', seed: '123', subject: 'Guided fixture'},
);
assert.equal(evidence.evidence_class, 'engineering_judgment');
assert.equal(evidence.explicit_acceptance, true);
assert.equal(evidence.acceptance_rationale,
  'Accepted as an analyst-provided provisional assumption for this run.');
assert.equal(evidence.citation.stable_reference, 'guided-solartac-assumptions-123');
assert.equal(evidence.citation.publication_or_as_of_date, '2026-08-16');
assert.equal(evidence.citation.accessed_date, '2026-08-16');
assert.equal(evidence.citation.title, 'Guided fixture');
assert.equal(evidence.citation.organization, 'User-supplied guided TEA assumptions');

const rejected = technoeconomicGuidedEvidence('Not accepted.', false, {
  date: '2026-08-16', seed: '123',
});
assert.equal(rejected.explicit_acceptance, false);

console.log(JSON.stringify({fixed, triangular, percent, evidence, rejected}));
"""
        )
        self.assertEqual("fixed", payload["fixed"]["family"])
        self.assertEqual("triangular", payload["triangular"]["family"])
        self.assertEqual("0.05", payload["percent"]["mode"])
        self.assertTrue(payload["evidence"]["explicit_acceptance"])
        self.assertFalse(payload["rejected"]["explicit_acceptance"])
        self.assertNotIn("TECHNOECONOMIC_SOLARTAC_CAPEX_REFERENCE_RANGE", self.script)
        self.assertNotIn("technoeconomicApplyProvisionalReferenceValues", self.script)

    @unittest.skipUnless(shutil.which("node"), "Node.js is required")
    def test_internal_detailed_editor_is_never_exposed(self) -> None:
        payload = self.run_node(
            r"""
const assert = require('node:assert/strict');
globalThis.technoeconomicElements = {
  guidedPanel: {hidden: true},
  advancedDetails: {hidden: false, open: true},
  entryModeRow: {hidden: false},
  submitPanel: {hidden: false},
  useGuidedButton: {hidden: false},
  entryModeStatus: {textContent: ''},
};

technoeconomicEntryMode = TECHNOECONOMIC_GUIDED_ENTRY_MODE;
technoeconomicRenderEntryMode();
assert.equal(technoeconomicElements.guidedPanel.hidden, false);
assert.equal(technoeconomicElements.advancedDetails.hidden, true);
assert.equal(technoeconomicElements.advancedDetails.open, false);
assert.equal(technoeconomicElements.entryModeRow.hidden, true);
assert.equal(technoeconomicElements.submitPanel.hidden, false);
assert.equal(technoeconomicElements.useGuidedButton.hidden, true);
assert.ok(technoeconomicElements.entryModeStatus.textContent.includes('generated automatically'));

technoeconomicElements.advancedDetails.open = true;
technoeconomicEntryMode = TECHNOECONOMIC_ADVANCED_ENTRY_MODE;
technoeconomicRenderEntryMode();
assert.equal(technoeconomicElements.guidedPanel.hidden, true);
assert.equal(technoeconomicElements.advancedDetails.hidden, true);
assert.equal(technoeconomicElements.advancedDetails.open, false);
assert.equal(technoeconomicElements.entryModeRow.hidden, false);
assert.equal(technoeconomicElements.submitPanel.hidden, true);
assert.equal(technoeconomicElements.useGuidedButton.hidden, false);
assert.ok(technoeconomicElements.entryModeStatus.textContent.includes('saved custom TEA draft'));
const errors = technoeconomicGuidedFormErrors();
assert.equal(errors.length, 1);
assert.ok(errors[0].message.includes('minimum-entry interface'));

console.log(JSON.stringify({
  guidedHidden: technoeconomicElements.guidedPanel.hidden,
  internalHidden: technoeconomicElements.advancedDetails.hidden,
  internalOpen: technoeconomicElements.advancedDetails.open,
  legacyNoticeHidden: technoeconomicElements.entryModeRow.hidden,
  submitHidden: technoeconomicElements.submitPanel.hidden,
  blocked: errors.length === 1,
}));
"""
        )
        self.assertTrue(payload["guidedHidden"])
        self.assertTrue(payload["internalHidden"])
        self.assertFalse(payload["internalOpen"])
        self.assertFalse(payload["legacyNoticeHidden"])
        self.assertTrue(payload["submitHidden"])
        self.assertTrue(payload["blocked"])

    @unittest.skipUnless(shutil.which("node"), "Node.js is required")
    def test_guided_estimate_helper_is_pure_separate_and_fails_closed(self) -> None:
        payload = self.run_node(
            r"""
const assert = require('node:assert/strict');
const close = (actual, expected, tolerance = 1e-12) => {
  assert.ok(Math.abs(actual - expected) <= tolerance, `${actual} != ${expected}`);
};
const solectriaInput = {
  capex: '100000', annualOm: '5000', projectLifeYears: '1',
  discountPercent: '0', degradationPercent: '',
  annualEnergies: [250000, 200000],
};
const frozenInput = JSON.stringify(solectriaInput);
const solectria = technoeconomicGuidedEstimate(solectriaInput);
assert.ok(solectria);
assert.equal(JSON.stringify(solectriaInput), frozenInput);
assert.equal(solectria.lifecycleCost, 105000);
assert.equal(solectria.annualizedCost, 105000);
assert.equal(solectria.typicalEnergy, 225000);
close(solectria.lcoeLow, 0.42);
close(solectria.lcoeCentral, 105000 / 225000);
close(solectria.lcoeHigh, 0.525);

const solaredge = technoeconomicGuidedEstimate({
  capex: '130000', annualOm: '6000', projectLifeYears: '1',
  discountPercent: '0', degradationPercent: '0',
  annualEnergies: [215000, 260000],
});
assert.ok(solaredge);
assert.equal(solaredge.lifecycleCost, 136000);
close(solaredge.lcoeLow, 136000 / 260000);
close(solaredge.lcoeCentral, 136000 / 237500);
close(solaredge.lcoeHigh, 136000 / 215000);
assert.equal(solectria.lifecycleCost, 105000);

const ranged = technoeconomicGuidedEstimate({
  ...solectriaInput,
  capexLow: '90000', capexHigh: '110000', omLow: '4000', omHigh: '6000',
});
assert.ok(ranged);
close(ranged.lcoeLow, 94000 / 250000);
close(ranged.lcoeCentral, 105000 / 225000);
close(ranged.lcoeHigh, 116000 / 200000);
const centralLifecycle = technoeconomicGuidedEstimate({
  ...solectriaInput,
  projectLifeYears: '25', discountPercent: '5', degradationPercent: '0.5',
});
const lifecycleRange = technoeconomicGuidedEstimate({
  ...solectriaInput,
  projectLifeYears: '25', discountPercent: '5',
  discountLowPercent: '3', discountHighPercent: '7',
  degradationPercent: '0.5',
  degradationLowPercent: '0.2', degradationHighPercent: '0.8',
});
assert.ok(centralLifecycle);
assert.ok(lifecycleRange);
assert.ok(lifecycleRange.lcoeLow < centralLifecycle.lcoeLow);
assert.ok(lifecycleRange.lcoeHigh > centralLifecycle.lcoeHigh);
assert.ok(technoeconomicGuidedEstimate({
  ...solectriaInput, projectLifeYears: '1001', discountPercent: '5',
}));
assert.deepEqual(
  technoeconomicGuidedEstimate({...solectriaInput, degradationPercent: '0'}),
  solectria,
);

for (const invalid of [
  {...solectriaInput, capex: ''},
  {...solectriaInput, annualOm: ''},
  {...solectriaInput, projectLifeYears: '0'},
  {...solectriaInput, discountPercent: '-100'},
  {...solectriaInput, degradationPercent: '100'},
  {...solectriaInput, discountLowPercent: '1', discountHighPercent: '-1'},
  {...solectriaInput, degradationLowPercent: '1', degradationHighPercent: '0.5'},
  {...solectriaInput, annualEnergies: []},
]) assert.equal(technoeconomicGuidedEstimate(invalid), null);

assert.equal(technoeconomicFormatCapacity(139180.8), '139.18 kWdc');
assert.equal(technoeconomicFormatEnergy(200000), '200 MWh/year');
const clippedSource = {
  eligible: true,
  solectria_installed_wdc: 139180.8,
  solaredge_installed_wdc: 139180.8,
  annual_energy_by_year: [
    {year: 2024, solectria_kwh: 200000, solaredge_kwh: 215000},
  ],
  provenance: {
    operating_limit: {curtailment_enabled: true, curtailment_limit_kw: 125},
  },
};
assert.equal(technoeconomicAppliedCapacity(clippedSource, 'solectria'), '125 kWac');
assert.equal(technoeconomicAppliedCapacity(clippedSource, 'solaredge'), '125 kWac');
const unclippedSource = {
  ...clippedSource,
  provenance: {operating_limit: {curtailment_enabled: false}},
};
assert.equal(technoeconomicAppliedCapacity(unclippedSource, 'solectria'), '139.18 kWdc');
assert.equal(technoeconomicAppliedCapacity(unclippedSource, 'solaredge'), '139.18 kWdc');
for (const invalidLimit of [undefined, null, 0, -1, 'not-a-number']) {
  const invalidClippedSource = {
    ...clippedSource,
    provenance: {
      operating_limit: {
        curtailment_enabled: true,
        curtailment_limit_kw: invalidLimit,
      },
    },
  };
  assert.equal(
    technoeconomicAppliedCapacity(invalidClippedSource, 'solectria'),
    '139.18 kWdc',
  );
  assert.equal(
    technoeconomicAppliedCapacity(invalidClippedSource, 'solaredge'),
    '139.18 kWdc',
  );
}
const screenshotInputs = {
  project_life_years: '', discount: '',
  solectria_capex: '25000', solectria_om: '5000',
  solaredge_capex: '27000', solaredge_om: '7000',
};
assert.equal(
  technoeconomicGuidedEstimatePrompt('solectria', clippedSource, screenshotInputs),
  'Enter project life and discount rate',
);
assert.equal(
  technoeconomicGuidedEstimatePrompt('solaredge', clippedSource, screenshotInputs),
  'Enter project life and discount rate',
);
console.log(JSON.stringify({solectria, solaredge, ranged, lifecycleRange}));
"""
        )
        self.assertEqual(105000, payload["solectria"]["lifecycleCost"])
        self.assertEqual(136000, payload["solaredge"]["lifecycleCost"])
        self.assertLess(
            payload["solectria"]["lcoeLow"],
            payload["solectria"]["lcoeHigh"],
        )

    @unittest.skipUnless(shutil.which("node"), "Node.js is required")
    def test_selected_source_renders_only_energy_capacity_and_actual_operating_limit(
        self,
    ) -> None:
        payload = self.run_node(
            r"""
const assert = require('node:assert/strict');
globalThis.document = {
  createElement(tag) {
    return {
      tag, textContent: '', children: [], dataset: {},
      append(...children) { this.children.push(...children); },
    };
  },
};
const energyRows = {
  children: [],
  replaceChildren() { this.children = []; },
  append(...children) { this.children.push(...children); },
};
globalThis.technoeconomicElements = {
  sourceSelect: {value: 'annual-guided-source'},
  sourceDetails: {hidden: true},
  sourceEnergyRows: energyRows,
  sourceStatusPanel: {dataset: {}},
  sourceStatus: {textContent: ''},
  sourceDetail: {textContent: ''},
  sourceOperatingLimit: {textContent: ''},
  sourceCapacityNote: {textContent: ''},
  sourceSolectriaCapacity: {textContent: ''},
  sourceSolectriaEnergy: {textContent: ''},
  sourceSolarEdgeCapacity: {textContent: ''},
  sourceSolarEdgeEnergy: {textContent: ''},
};
technoeconomicRenderGuidedEstimates = () => {};
technoeconomicSources = [{
  eligible: true,
  source_annual_job_id: 'annual-guided-source',
  solectria_installed_wdc: 139180.8,
  solaredge_installed_wdc: 139180.8,
  capacity_manifest_source: 'secret-manifest-detail',
  source_snapshot_sha256: 'f'.repeat(64),
  annual_energy_by_year: [
    {year: 2024, solectria_kwh: 200000, solaredge_kwh: 215000},
    {year: 2023, solectria_kwh: 180000, solaredge_kwh: 195000},
  ],
  provenance: {
    completed_at: 'private-timestamp',
    calibration: {baseline_job_id: 'private-baseline'},
    operating_limit: {curtailment_enabled: true, curtailment_limit_kw: 125},
  },
}];

technoeconomicRenderSelectedSource();
assert.equal(technoeconomicElements.sourceDetails.hidden, false);
assert.equal(technoeconomicElements.sourceStatusPanel.dataset.state, 'ready');
assert.equal(technoeconomicElements.sourceStatus.textContent,
  'Calibrated annual energy is ready');
assert.ok(technoeconomicElements.sourceDetail.textContent.includes('2 eligible weather years'));
assert.equal(technoeconomicElements.sourceOperatingLimit.textContent, '125 kWac');
assert.ok(technoeconomicElements.sourceCapacityNote.textContent.includes(
  'applied capacity used for cost and energy normalization'
));
assert.equal(technoeconomicElements.sourceCapacityNote.textContent.includes(
  'Installed DC nameplate remains separate and is used'
), false);
assert.equal(technoeconomicElements.sourceSolectriaCapacity.textContent, '125 kWac');
assert.equal(technoeconomicElements.sourceSolarEdgeCapacity.textContent, '125 kWac');
assert.equal(technoeconomicElements.sourceSolectriaEnergy.textContent, '190 MWh/year');
assert.equal(technoeconomicElements.sourceSolarEdgeEnergy.textContent, '205 MWh/year');
assert.deepEqual(
  energyRows.children.map((row) => row.children.map((cell) => cell.textContent)),
  [
    ['2023', '180 MWh/year', '195 MWh/year'],
    ['2024', '200 MWh/year', '215 MWh/year'],
  ],
);
const renderedText = JSON.stringify(technoeconomicElements) + JSON.stringify(energyRows);
for (const internal of [
  'secret-manifest-detail', 'private-timestamp', 'private-baseline', 'ffffffff',
]) assert.equal(renderedText.includes(internal), false, internal);

technoeconomicSources[0].provenance.operating_limit = {curtailment_enabled: false};
technoeconomicRenderSelectedSource();
assert.equal(technoeconomicElements.sourceOperatingLimit.textContent, 'No AC limit enabled');
assert.equal(technoeconomicElements.sourceSolectriaCapacity.textContent, '139.18 kWdc');
assert.equal(technoeconomicElements.sourceSolarEdgeCapacity.textContent, '139.18 kWdc');
assert.ok(technoeconomicElements.sourceCapacityNote.textContent.includes(
  'did not enable an AC operating limit'
));
assert.ok(technoeconomicElements.sourceCapacityNote.textContent.includes(
  'installed DC nameplate is the applied capacity'
));
assert.equal(technoeconomicElements.sourceCapacityNote.textContent.includes(
  'already reflected in energy'
), false);
technoeconomicSources[0].provenance.operating_limit = {
  curtailment_enabled: true,
  curtailment_limit_kw: null,
};
technoeconomicRenderSelectedSource();
assert.equal(technoeconomicElements.sourceOperatingLimit.textContent, 'Unavailable');
assert.equal(technoeconomicElements.sourceSolectriaCapacity.textContent, '139.18 kWdc');
assert.equal(technoeconomicElements.sourceSolarEdgeCapacity.textContent, '139.18 kWdc');
assert.equal(technoeconomicElements.sourceCapacityNote.textContent.includes(
  'already reflected in energy'
), false);
assert.ok(technoeconomicElements.sourceCapacityNote.textContent.includes(
  'valid AC operating limit is unavailable'
));
assert.ok(technoeconomicElements.sourceCapacityNote.textContent.includes(
  'installed DC nameplate is the applied capacity'
));
technoeconomicSources[0].provenance.operating_limit = {curtailment_enabled: false};
technoeconomicRenderSelectedSource();
console.log(JSON.stringify({
  operatingLimit: technoeconomicElements.sourceOperatingLimit.textContent,
  capacity: technoeconomicElements.sourceSolectriaCapacity.textContent,
  typicalEnergy: technoeconomicElements.sourceSolectriaEnergy.textContent,
  rowCount: energyRows.children.length,
}));
"""
        )
        self.assertEqual("No AC limit enabled", payload["operatingLimit"])
        self.assertEqual("139.18 kWdc", payload["capacity"])
        self.assertEqual("190 MWh/year", payload["typicalEnergy"])
        self.assertEqual(2, payload["rowCount"])

    @unittest.skipUnless(shutil.which("node"), "Node.js is required")
    def test_legacy_custom_draft_is_preserved_without_exposing_detailed_editor(self) -> None:
        payload = self.run_node(
            r"""
const assert = require('node:assert/strict');
const memory = new Map();
globalThis.localStorage = {
  getItem(key) { return memory.has(key) ? memory.get(key) : null; },
  setItem(key, value) { memory.set(key, String(value)); },
  removeItem(key) { memory.delete(key); },
};
const legacy = technoeconomicDefaultDraft();
delete legacy.entry_mode;
legacy.source_annual_job_id = 'annual-legacy-source';
memory.set(TECHNOECONOMIC_DRAFT_STORAGE_KEY, JSON.stringify(legacy));

const loaded = technoeconomicLoadLocalDraft();
assert.equal(loaded.entry_mode, TECHNOECONOMIC_ADVANCED_ENTRY_MODE);
globalThis.technoeconomicElements = {
  guidedPanel: {hidden: false},
  advancedDetails: {hidden: false, open: true},
  entryModeRow: {hidden: true},
  submitPanel: {hidden: false},
  useGuidedButton: {hidden: true},
  entryModeStatus: {textContent: ''},
};
technoeconomicEntryMode = loaded.entry_mode;
technoeconomicRenderEntryMode();
assert.equal(technoeconomicElements.guidedPanel.hidden, true);
assert.equal(technoeconomicElements.advancedDetails.hidden, true);
assert.equal(technoeconomicElements.advancedDetails.open, false);
assert.equal(technoeconomicElements.entryModeRow.hidden, false);
assert.equal(technoeconomicElements.submitPanel.hidden, true);
assert.equal(technoeconomicElements.useGuidedButton.hidden, false);
assert.ok(technoeconomicElements.entryModeStatus.textContent.includes('saved custom TEA draft'));
const errors = technoeconomicGuidedFormErrors();
assert.equal(errors.length, 1);

console.log(JSON.stringify({
  mode: loaded.entry_mode,
  guidedHidden: technoeconomicElements.guidedPanel.hidden,
  internalHidden: technoeconomicElements.advancedDetails.hidden,
  advancedOpen: technoeconomicElements.advancedDetails.open,
  legacyNoticeHidden: technoeconomicElements.entryModeRow.hidden,
  submitHidden: technoeconomicElements.submitPanel.hidden,
  blocked: errors.length === 1,
}));
"""
        )
        self.assertEqual("advanced", payload["mode"])
        self.assertTrue(payload["guidedHidden"])
        self.assertTrue(payload["internalHidden"])
        self.assertFalse(payload["advancedOpen"])
        self.assertFalse(payload["legacyNoticeHidden"])
        self.assertTrue(payload["submitHidden"])
        self.assertTrue(payload["blocked"])

    @unittest.skipUnless(shutil.which("node"), "Node.js is required")
    def test_legacy_custom_reset_requires_confirmation_and_preserves_source_seed(self) -> None:
        payload = self.run_node(
            r"""
const assert = require('node:assert/strict');
const current = technoeconomicDefaultDraft();
current.entry_mode = TECHNOECONOMIC_ADVANCED_ENTRY_MODE;
current.source_annual_job_id = 'annual-legacy-source';
current.seed = '8675309';
current.project_life_years = '31';
let applied = null;
let marked = '';
let confirmation = false;
globalThis.window = {confirm() { return confirmation; }};
globalThis.technoeconomicElements = {advancedDetails: {open: true}};
getTechnoeconomicFormState = () => current;
applyTechnoeconomicFormState = (value) => {
  applied = JSON.parse(JSON.stringify(value));
  return true;
};
technoeconomicMarkDraftChanged = (action) => { marked = action; };

const beforeRevision = technoeconomicDraftRevision;
technoeconomicUseGuidedSolarTac();
assert.equal(applied, null);
assert.equal(marked, '');
assert.equal(technoeconomicDraftRevision, beforeRevision);
assert.equal(current.entry_mode, TECHNOECONOMIC_ADVANCED_ENTRY_MODE);
assert.equal(current.project_life_years, '31');

confirmation = true;
technoeconomicUseGuidedSolarTac();
assert.equal(applied.entry_mode, TECHNOECONOMIC_GUIDED_ENTRY_MODE);
assert.equal(applied.source_annual_job_id, 'annual-legacy-source');
assert.equal(applied.seed, '8675309');
assert.equal(applied.project_life_years, '');
assert.equal(technoeconomicElements.advancedDetails.open, false);
assert.ok(technoeconomicDraftRevision > beforeRevision);
assert.equal(marked, 'Guided SolarTAC setup restored.');

console.log(JSON.stringify({
  source: applied.source_annual_job_id,
  seed: applied.seed,
  projectLife: applied.project_life_years,
  advancedOpen: technoeconomicElements.advancedDetails.open,
  resetMarked: marked,
}));
"""
        )
        self.assertEqual("annual-legacy-source", payload["source"])
        self.assertEqual("8675309", payload["seed"])
        self.assertEqual("", payload["projectLife"])
        self.assertFalse(payload["advancedOpen"])
        self.assertEqual("Guided SolarTAC setup restored.", payload["resetMarked"])

    @unittest.skipUnless(shutil.which("node"), "Node.js is required")
    def test_guided_draft_expands_separate_system_totals_to_the_strict_contract(
        self,
    ) -> None:
        payload = self.run_node(
            r"""
const assert = require('node:assert/strict');
const base = technoeconomicDefaultDraft();
base.source_annual_job_id = 'annual-guided-source';
const inputs = {
  cost_year: '2025',
  project_life_years: '25',
  discount: '5', discount_low: '3', discount_high: '7',
  degradation: '', degradation_low: '', degradation_high: '',
  solectria_capex: '100000', solectria_capex_low: '90000',
  solectria_capex_high: '110000',
  solectria_om: '5000', solectria_om_low: '', solectria_om_high: '',
  solaredge_capex: '130000', solaredge_capex_low: '120000',
  solaredge_capex_high: '140000',
  solaredge_om: '6000', solaredge_om_low: '', solaredge_om_high: '',
  assumption_note: 'Analyst reviewed the separate system financial assumptions.',
  accepted: true,
};
const draft = technoeconomicBuildGuidedDraft(base, inputs, {
  seed: '42', date: '2026-08-16',
});
assert.equal(draft.schema_version, 'technoeconomic-draft-v3');
assert.equal(draft.entry_mode, 'guided_solartac');
assert.equal(draft.basis, 'solartac_site');
assert.equal(draft.capacity_normalization, 'annual_applied_capacity_v1');
assert.equal(draft.n, '10000');
assert.equal(draft.seed, '42');
assert.equal(draft.cost_year, '2025');
assert.equal(draft.project_life_years, '25');
assert.deepEqual(draft.discount_rate.distribution, {
  family: 'triangular', value: '', low: '0.03', mode: '0.05', high: '0.07',
  mean: '', sd: '',
});
assert.deepEqual(draft.shared_degradation.distribution, {
  family: 'fixed', value: '0', low: '', mode: '', high: '', mean: '', sd: '',
});
assert.deepEqual(draft.cost_lines.map((line) => line.input_id), [
  'cost.guided.solectria-capex',
  'cost.guided.solectria-recurring-om',
  'cost.guided.solaredge-capex',
  'cost.guided.solaredge-recurring-om',
]);
assert.deepEqual(draft.cost_lines.map((line) => line.ownership), [
  'solectria_only', 'solectria_only', 'solaredge_only', 'solaredge_only',
]);
assert.deepEqual(draft.cost_lines.map((line) => line.cost_type), [
  'initial_capex', 'recurring_om', 'initial_capex', 'recurring_om',
]);
assert.deepEqual(draft.cost_lines.map((line) => line.original_unit), [
  'usd_total', 'usd_total_per_year', 'usd_total', 'usd_total_per_year',
]);
assert.deepEqual(draft.cost_lines.map((line) => line.normalized_unit), [
  'usd_per_applied_w', 'usd_per_applied_w_year',
  'usd_per_applied_w', 'usd_per_applied_w_year',
]);
assert.deepEqual(draft.cost_lines.map((line) => line.solectria_quantity), [
  '1', '1', '0', '0',
]);
assert.deepEqual(draft.cost_lines.map((line) => line.solaredge_quantity), [
  '0', '0', '1', '1',
]);
assert.ok(draft.cost_lines.every((line) =>
  line.constant_dollar_cost_year === '2025'
  && line.normalization_method === 'divide_by_frozen_applied_capacity_w'
  && line.quantity_unit === ''
  && line.coverage_exclude_ids.length === 0
  && line.evidence.explicit_acceptance === true
  && line.evidence.acceptance_rationale === inputs.assumption_note));
assert.ok(draft.cost_lines.every((line) =>
  line.evidence.evidence_class === 'engineering_judgment'));
assert.deepEqual(
  [draft.project_life_evidence, draft.discount_rate.evidence,
    draft.shared_degradation.evidence].map((item) => item.explicit_acceptance),
  [true, true, true],
);
assert.equal(draft.transfer_enabled, false);

const roundTrip = technoeconomicGuidedInputsFromDraft(draft);
assert.equal(roundTrip.discount, '5');
assert.equal(roundTrip.discount_low, '3');
assert.ok(Math.abs(Number(roundTrip.discount_high) - 7) < 1e-12);
assert.equal(roundTrip.degradation, '0');
assert.equal(roundTrip.degradation_low, '');
assert.equal(roundTrip.degradation_high, '');
assert.equal(roundTrip.solectria_capex, '100000');
assert.equal(roundTrip.solectria_capex_low, '90000');
assert.equal(roundTrip.solectria_capex_high, '110000');
assert.equal(roundTrip.solectria_om, '5000');
assert.equal(roundTrip.solaredge_capex, '130000');
assert.equal(roundTrip.solaredge_om, '6000');
assert.equal(roundTrip.accepted, true);

const serialized = serializeTechnoeconomicRequest(draft, {
  sources: [{source_annual_job_id: 'annual-guided-source', eligible: true}],
});
assert.equal(serialized.valid, true, JSON.stringify(serialized.errors));
assert.equal(serialized.payload.n, 10000);
assert.equal(serialized.payload.seed, 42);
assert.equal(serialized.payload.capacity_normalization, 'annual_applied_capacity_v1');
assert.equal(serialized.payload.finance.real_discount_rate.distribution.mode, 0.05);
assert.deepEqual(serialized.payload.shared_degradation.annual_rate.distribution, {
  family: 'fixed', value: 0,
});
assert.equal(serialized.payload.cost_lines.length, 4);
assert.deepEqual(serialized.payload.cost_lines[0].distribution, {
  family: 'triangular', low: 90000, mode: 100000, high: 110000,
});
assert.equal(serialized.payload.cost_lines[0].solectria_quantity, 1);
assert.equal(serialized.payload.cost_lines[0].solaredge_quantity, 0);
assert.equal(serialized.payload.cost_lines[0].quantity_unit, null);
assert.equal(serialized.payload.cost_lines[2].solectria_quantity, 0);
assert.equal(serialized.payload.cost_lines[2].solaredge_quantity, 1);
assert.equal(serialized.payload.commercial_reference_design, null);
assert.equal(serialized.payload.commercial_transfer, null);
const sourceSummary = technoeconomicConfirmationSource({
  source_annual_job_id: 'annual-guided-source',
  applied_capacity: {
    solectria: {applied_capacity_w: 125000, rating_basis: 'ac_operating_limit'},
    solaredge: {applied_capacity_w: 125000, rating_basis: 'ac_operating_limit'},
  },
});
assert.equal(
  technoeconomicConfirmationCapacity(sourceSummary, 'solectria', true),
  '125,000 W (AC operating limit)'
);
for (const derived of [
  'capacities', 'annual_energy_by_year', 'lifecycle_cost', 'annualized_cost',
  'estimated_lcoe',
]) assert.equal(derived in serialized.payload, false, derived);

const rejectedDraft = technoeconomicBuildGuidedDraft(
  base, {...inputs, accepted: false}, {seed: '42', date: '2026-08-16'}
);
const rejected = serializeTechnoeconomicRequest(rejectedDraft, {
  sources: [{source_annual_job_id: 'annual-guided-source', eligible: true}],
});
assert.equal(rejected.valid, false);
assert.ok(rejected.errors.some((item) =>
  item.path === 'finance.project_life_evidence.explicit_acceptance'));
assert.ok(rejected.errors.some((item) =>
  item.path === 'finance.real_discount_rate.evidence.explicit_acceptance'));
assert.ok(rejected.errors.some((item) =>
  item.path === 'shared_degradation.annual_rate.evidence.explicit_acceptance'));
for (let index = 0; index < 4; index += 1) {
  assert.ok(rejected.errors.some((item) =>
    item.path === `cost_lines[${index}].evidence.explicit_acceptance`));
}

console.log(JSON.stringify({
  valid: serialized.valid,
  costLineCount: serialized.payload.cost_lines.length,
  discountMode: serialized.payload.finance.real_discount_rate.distribution.mode,
  degradationValue: serialized.payload.shared_degradation.annual_rate.distribution.value,
  roundTrip,
  rejectionCount: rejected.errors.length,
}));
"""
        )
        self.assertTrue(payload["valid"])
        self.assertEqual(4, payload["costLineCount"])
        self.assertEqual(0.05, payload["discountMode"])
        self.assertEqual(0, payload["degradationValue"])
        self.assertEqual("5", payload["roundTrip"]["discount"])
        self.assertEqual("0", payload["roundTrip"]["degradation"])
        self.assertEqual("100000", payload["roundTrip"]["solectria_capex"])
        self.assertEqual("130000", payload["roundTrip"]["solaredge_capex"])
        self.assertGreaterEqual(payload["rejectionCount"], 7)

    @unittest.skipUnless(shutil.which("node"), "Node.js is required")
    def test_site_request_serialization_matches_the_strict_api_contract(self) -> None:
        payload = self.run_node(
            self.tea_fixture_helpers()
            + r"""
const assert = require('node:assert/strict');
const result = serializeTechnoeconomicRequest(solarTacDraft(), {
  sources: [{source_annual_job_id: 'annual-source-1', eligible: true}],
});
assert.equal(result.valid, true);
assert.deepEqual(result.errors, []);
assert.equal(result.payload.basis, 'solartac_site');
assert.equal(result.payload.capacity_normalization, 'annual_applied_capacity_v1');
assert.equal(result.payload.n, 1000);
assert.equal(result.payload.seed, Number.MAX_SAFE_INTEGER);
assert.deepEqual(result.payload.cost_lines[0].distribution, {family: 'fixed', value: 1000});
assert.deepEqual(result.payload.cost_lines[1].distribution, {
  family: 'uniform', low: 900, high: 1100,
});
assert.deepEqual(result.payload.finance.real_discount_rate.distribution, {
  family: 'triangular', low: 0.03, mode: 0.05, high: 0.07,
});
assert.deepEqual(result.payload.shared_degradation.annual_rate.distribution, {
  family: 'bounded_normal', low: 0.002, high: 0.008, mean: 0.005, sd: 0.001,
});
assert.equal(result.nonfixedPredictorCount, 3);
assert.equal(result.payload.commercial_reference_design, null);
assert.equal(result.payload.commercial_transfer, null);
assert.ok(result.payload.cost_lines.every((line) =>
  line.normalized_unit === 'usd_per_applied_w'
  && line.normalization_method === 'divide_by_frozen_applied_capacity_w'));
assert.equal('capacities' in result.payload, false);
assert.equal('annual_energy_by_year' in result.payload, false);
assert.equal('transfer_enabled' in result.payload, false);
const evidence = result.payload.finance.project_life_evidence;
assert.equal(evidence.evidence_class, 'direct_quote_or_primary_document');
assert.equal(evidence.citation.url, null);
assert.equal(evidence.citation.stable_reference, 'LIFE');
assert.equal(evidence.citation.preservation_mode, 'metadata_excerpt_only');
assert.equal(evidence.citation.user_supplied_content_sha256, null);
assert.equal(evidence.explicit_acceptance, null);
assert.equal(evidence.acceptance_rationale, null);
console.log(JSON.stringify({
  families: [
    result.payload.cost_lines[0].distribution.family,
    result.payload.cost_lines[1].distribution.family,
    result.payload.finance.real_discount_rate.distribution.family,
    result.payload.shared_degradation.annual_rate.distribution.family,
  ],
  inputCount: result.payload.cost_lines.length,
}));
"""
        )
        self.assertEqual(
            ["fixed", "uniform", "triangular", "bounded_normal"],
            payload["families"],
        )
        self.assertEqual(2, payload["inputCount"])

    @unittest.skipUnless(shutil.which("node"), "Node.js is required")
    def test_provisional_evidence_seed_and_corrupt_drafts_fail_closed(self) -> None:
        payload = self.run_node(
            self.tea_fixture_helpers()
            + r"""
const assert = require('node:assert/strict');
const sources = [{source_annual_job_id: 'annual-source-1', eligible: true}];

const provisional = solarTacDraft();
provisional.project_life_evidence = {
  ...teaEvidence('LIFE-PROVISIONAL'), evidence_class: 'engineering_judgment',
  explicit_acceptance: true,
  acceptance_rationale: 'Accepted for this explicitly provisional scenario.',
};
const accepted = serializeTechnoeconomicRequest(provisional, {sources});
assert.equal(accepted.valid, true);
assert.equal(accepted.provisionalEvidenceCount, 1);
assert.equal(accepted.payload.finance.project_life_evidence.explicit_acceptance, true);

provisional.project_life_evidence.explicit_acceptance = false;
provisional.project_life_evidence.acceptance_rationale = '';
const rejectedEvidence = serializeTechnoeconomicRequest(provisional, {sources});
assert.equal(rejectedEvidence.valid, false);
assert.ok(rejectedEvidence.errors.some((item) =>
  item.path === 'finance.project_life_evidence.explicit_acceptance'));
assert.ok(rejectedEvidence.errors.some((item) =>
  item.path === 'finance.project_life_evidence.acceptance_rationale'));

const unsafe = solarTacDraft();
unsafe.seed = '9007199254740992';
const rejectedSeed = serializeTechnoeconomicRequest(unsafe, {sources});
assert.equal(rejectedSeed.valid, false);
assert.equal(rejectedSeed.payload.seed, null);
assert.ok(rejectedSeed.errors.some((item) => item.path === 'seed'
  && item.message.includes('9,007,199,254,740,991')));

const corrupt = solarTacDraft();
corrupt.cost_lines[0].distribution = {family: 'made_up', value: '5'};
corrupt.cost_lines[1].evidence.evidence_class = 'made_up';
corrupt.project_life_evidence.citation.publication_or_as_of_date = '2025-02-30';
const rejectedCorrupt = serializeTechnoeconomicRequest(corrupt, {sources});
assert.equal(rejectedCorrupt.valid, false);
for (const path of [
  'cost_lines[0].distribution.family',
  'cost_lines[1].evidence.evidence_class',
  'finance.project_life_evidence.citation.publication_or_as_of_date',
]) assert.ok(rejectedCorrupt.errors.some((item) => item.path === path), path);

const cleared = solarTacDraft();
Object.assign(cleared, {n: '', seed: '', cost_year: '', project_life_years: ''});
const rejectedCleared = serializeTechnoeconomicRequest(cleared, {sources});
assert.equal(rejectedCleared.valid, false);
for (const path of ['n', 'seed', 'finance.constant_dollar_cost_year', 'finance.project_life_years']) {
  assert.ok(rejectedCleared.errors.some((item) => item.path === path), path);
}
console.log(JSON.stringify({
  provisionalErrors: rejectedEvidence.errors.length,
  corruptErrors: rejectedCorrupt.errors.length,
  clearedErrors: rejectedCleared.errors.length,
}));
"""
        )
        self.assertGreaterEqual(payload["provisionalErrors"], 2)
        self.assertGreaterEqual(payload["corruptErrors"], 3)
        self.assertGreaterEqual(payload["clearedErrors"], 4)

    @unittest.skipUnless(shutil.which("node"), "Node.js is required")
    def test_commercial_transfer_and_cost_only_requests_are_unambiguous(self) -> None:
        payload = self.run_node(
            self.tea_fixture_helpers()
            + r"""
const assert = require('node:assert/strict');
const sources = [{source_annual_job_id: 'annual-source-2', eligible: true}];
const commercial = serializeTechnoeconomicRequest(commercialDraft(true), {sources});
assert.equal(commercial.valid, true);
assert.deepEqual(commercial.errors, []);
assert.equal(commercial.payload.basis, 'commercial_representative');
assert.equal(commercial.payload.capacity_normalization, null);
assert.equal(commercial.payload.commercial_reference_design.reference_wdc, 550000);
assert.equal(commercial.payload.commercial_transfer.status, 'approved');
assert.equal(commercial.payload.commercial_transfer.explicit_attestation, true);
assert.deepEqual(commercial.payload.commercial_transfer.baseline_factor.distribution, {
  family: 'fixed', value: 1,
});
assert.deepEqual(commercial.payload.commercial_transfer.incremental_factor.distribution, {
  family: 'uniform', low: 0.9, high: 1.1,
});
const mechanisms = commercial.payload.commercial_transfer.mechanisms;
assert.deepEqual(mechanisms.map((item) => item.mechanism),
  TECHNOECONOMIC_TRANSFER_MECHANISMS);
assert.equal(mechanisms.length, 13);
assert.ok(mechanisms.every((item) => item.status === 'supported'
  && item.rationale && item.evidence.citation.stable_reference));

const costOnly = serializeTechnoeconomicRequest(commercialDraft(false), {sources});
assert.equal(costOnly.valid, true);
assert.equal(costOnly.payload.commercial_transfer, null);
assert.ok(costOnly.payload.commercial_reference_design);

const silentTransfer = commercialDraft(true);
silentTransfer.commercial_transfer.explicit_attestation = false;
silentTransfer.commercial_transfer.attestation_rationale = '';
silentTransfer.commercial_transfer.mechanisms[0].rationale = '';
const rejectedTransfer = serializeTechnoeconomicRequest(silentTransfer, {sources});
assert.equal(rejectedTransfer.valid, false);
assert.ok(rejectedTransfer.errors.some((item) =>
  item.path === 'commercial_transfer.explicit_attestation'));
assert.ok(rejectedTransfer.errors.some((item) =>
  item.path === 'commercial_transfer.attestation_rationale'));
assert.ok(rejectedTransfer.errors.some((item) =>
  item.path === 'commercial_transfer.mechanisms[0].rationale'));
console.log(JSON.stringify({mechanisms: mechanisms.length, costOnlyValid: costOnly.valid}));
"""
        )
        self.assertEqual(13, payload["mechanisms"])
        self.assertTrue(payload["costOnlyValid"])

    @unittest.skipUnless(shutil.which("node"), "Node.js is required")
    def test_api_error_normalization_keeps_field_paths_and_retry_classes(self) -> None:
        payload = self.run_node(
            r"""
const assert = require('node:assert/strict');
const conflict = normalizeTechnoeconomicApiError(409, {
  detail: {code: 'immutable_request', message: 'The request is immutable.'},
});
assert.deepEqual(conflict, {
  status: 409, code: 'immutable_request', message: 'The request is immutable.', fields: [],
});
const invalid = normalizeTechnoeconomicApiError(422, {detail: [
  {loc: ['body', 'cost_lines', 0, 'distribution'], msg: 'Invalid bounds.'},
]});
assert.equal(invalid.code, 'validation_error');
assert.deepEqual(invalid.fields, [
  {path: 'cost_lines.0.distribution', message: 'Invalid bounds.'},
]);
assert.ok(invalid.message.includes('cost_lines.0.distribution'));
const queued = normalizeTechnoeconomicApiError(429, {detail: 'Queue is full.'});
assert.equal(queued.code, 'queue_full');
assert.equal(queued.message, 'Queue is full.');
const network = normalizeTechnoeconomicApiError(new TypeError('fetch failed'));
assert.equal(network.status, null);
assert.equal(network.code, 'network_error');
assert.ok(network.message.includes('could not be reached'));
const aborted = new Error('cancelled');
aborted.name = 'AbortError';
assert.equal(normalizeTechnoeconomicApiError(aborted).code, 'request_aborted');
console.log(JSON.stringify({
  conflict: conflict.code, field: invalid.fields[0].path,
  queue: queued.code, network: network.code,
}));
"""
        )
        self.assertEqual("immutable_request", payload["conflict"])
        self.assertEqual("cost_lines.0.distribution", payload["field"])
        self.assertEqual("queue_full", payload["queue"])
        self.assertEqual("network_error", payload["network"])

    def test_confirmation_and_job_lifecycle_are_revision_fenced(self) -> None:
        open_confirmation = self.script.split(
            "function technoeconomicOpenConfirmation", 1
        )[1].split("function technoeconomicCloseConfirmation", 1)[0]
        self.assertIn("serializeTechnoeconomicRequest", open_confirmation)
        self.assertIn("technoeconomicDeepFreeze", open_confirmation)
        self.assertIn("technoeconomicPendingSubmission", open_confirmation)
        self.assertIn("dialog.showModal()", open_confirmation)
        self.assertNotIn("technoeconomicFetchJson", open_confirmation)
        self.assertNotIn("method: 'POST'", open_confirmation)

        confirmation = self.script.split(
            "async function technoeconomicConfirmSubmission", 1
        )[1].split("async function technoeconomicLifecycleRequest", 1)[0]
        self.assertLess(
            confirmation.index("pending.draftRevision !== technoeconomicDraftRevision"),
            confirmation.index("'/api/technoeconomic/jobs'"),
        )
        self.assertIn("method: 'POST', body: pending.payload", confirmation)

        poll = self.script.split(
            "async function technoeconomicPollJob", 1
        )[1].split("async function restoreTechnoeconomicActiveJob", 1)[0]
        for marker in (
            "revision !== technoeconomicStatusRequestRevision",
            "jobId !== technoeconomicActiveJobId",
            "technoeconomicStatusAbortController.abort()",
            "technoeconomicAdoptJob(body)",
            "!technoeconomicIsTerminalState(job.state)",
            "Math.min(10000",
            "Retrying without changing the server job",
        ):
            self.assertIn(marker, poll)
        self.assertLess(
            poll.index("jobId !== technoeconomicActiveJobId"),
            poll.index("technoeconomicAdoptJob(body)"),
        )

        for endpoint in (
            "'/api/technoeconomic/sources'",
            "'/api/technoeconomic/jobs'",
            "technoeconomicLifecycleRequest('cancel')",
            "technoeconomicLifecycleRequest('retry')",
            "technoeconomicLifecycleRequest('', 'DELETE')",
        ):
            self.assertIn(endpoint, self.script)

    @unittest.skipUnless(shutil.which("node"), "Node.js is required")
    def test_terminal_and_se_minus_sol_display_helpers_are_deterministic(self) -> None:
        payload = self.run_node(
            r"""
const assert = require('node:assert/strict');
assert.equal(technoeconomicIsTerminalState('done'), true);
assert.equal(technoeconomicIsTerminalState('error'), true);
assert.equal(technoeconomicIsTerminalState('cancelled'), true);
assert.equal(technoeconomicIsTerminalState('interrupted'), true);
assert.equal(technoeconomicIsTerminalState('queued'), false);
assert.equal(technoeconomicIsTerminalState('running'), false);
assert.equal(technoeconomicDifferenceLabel(1, 'SE greater', 'SE lower'), 'SE greater');
assert.equal(technoeconomicDifferenceLabel(-1, 'SE greater', 'SE lower'), 'SE lower');
assert.equal(technoeconomicDifferenceLabel(0, 'SE greater', 'SE lower'), 'Within tolerance');
assert.equal(technoeconomicFormatMetric(
  'DeltaLifecycleCostPerWdc_se_minus_sol_USD_per_Wdc', -1.25
), '-1.25 USD/Wdc');
assert.equal(technoeconomicFormatMetric(
  'DeltaLifecycleCostPerAppliedW_se_minus_sol_USD_per_applied_W', -1.25
), '-1.25 USD/applied W');
let legacyArgumentRead = false;
const legacyAnnualResult = new Proxy({}, {get() {
  legacyArgumentRead = true;
  throw new Error('compatibility renderer inspected an Annual result');
}});
renderTechnoeconomicAnalysis(legacyAnnualResult);
assert.equal(legacyArgumentRead, false);
console.log(JSON.stringify({
  signed: technoeconomicFormatMetric(
    'DeltaLifecycleEnergyPerWdc_se_minus_sol_kWh_AC_per_Wdc', -0.25
  ),
  signedApplied: technoeconomicFormatMetric(
    'DeltaLifecycleEnergyPerAppliedW_se_minus_sol_kWh_AC_per_applied_W', -0.25
  ),
  terminal: ['done', 'error', 'cancelled', 'interrupted'].filter(
    technoeconomicIsTerminalState
  ),
}));
"""
        )
        self.assertEqual("-0.25 kWh AC/Wdc", payload["signed"])
        self.assertEqual("-0.25 kWh AC/applied W", payload["signedApplied"])
        self.assertEqual(
            ["done", "error", "cancelled", "interrupted"],
            payload["terminal"],
        )

    def test_server_authoritative_result_surface_covers_every_diagnostic(self) -> None:
        for metric_key, label in (
            (
                "DeltaLifecycleCostPerWdc_se_minus_sol_USD_per_Wdc",
                "Lifecycle cost delta (SolarEdge minus Solectria)",
            ),
            (
                "DeltaLifecycleEnergyPerWdc_se_minus_sol_kWh_AC_per_Wdc",
                "Lifecycle energy delta (SolarEdge minus Solectria)",
            ),
            (
                "DeltaEquivalentAnnualCostPerWdcYear_se_minus_sol_USD_per_Wdc_year",
                "Equivalent annual cost delta (SolarEdge minus Solectria)",
            ),
            (
                "DeltaEquivalentAnnualEnergyPerWdcYear_se_minus_sol_kWh_AC_per_Wdc_year",
                "Equivalent annual energy delta (SolarEdge minus Solectria)",
            ),
            (
                "DeltaLifecycleCostPerAppliedW_se_minus_sol_USD_per_applied_W",
                "Lifecycle cost delta (SolarEdge minus Solectria)",
            ),
            (
                "DeltaLifecycleEnergyPerAppliedW_se_minus_sol_kWh_AC_per_applied_W",
                "Lifecycle energy delta (SolarEdge minus Solectria)",
            ),
            (
                "DeltaEquivalentAnnualCostPerAppliedWYear_se_minus_sol_USD_per_applied_W_year",
                "Equivalent annual cost delta (SolarEdge minus Solectria)",
            ),
            (
                "DeltaEquivalentAnnualEnergyPerAppliedWYear_se_minus_sol_kWh_AC_per_applied_W_year",
                "Equivalent annual energy delta (SolarEdge minus Solectria)",
            ),
        ):
            self.assertIn(f"{metric_key}: '{label}'", self.script)

        result_renderer = self.script.split(
            "function renderTechnoeconomicJobResult", 1
        )[1].split("function renderTechnoeconomicAnalysis", 1)[0]
        self.assertIn("job.state !== 'done'", result_renderer)
        self.assertIn("job?.result", result_renderer)
        self.assertNotIn("annualLatestResult", result_renderer)
        for render_call in (
            "technoeconomicRenderResultSummary(job, result)",
            "technoeconomicRenderMetrics(result)",
            "technoeconomicRenderTradeoffs(result)",
            "technoeconomicRenderPerYear(result)",
            "technoeconomicRenderSensitivity(result)",
            "technoeconomicRenderConvergence(result)",
            "technoeconomicRenderProvenance(job, result)",
            "technoeconomicRenderArtifacts(job)",
        ):
            self.assertIn(render_call, result_renderer)

        provenance_renderer = self.script.split(
            "function technoeconomicRenderProvenance", 1
        )[1].split("function technoeconomicSetPlot", 1)[0]
        self.assertIn("result.applied_capacities", provenance_renderer)
        self.assertIn("applied capacity", provenance_renderer)
        self.assertIn("installed DC provenance", provenance_renderer)

        tradeoffs = self.script.split(
            "function technoeconomicRenderTradeoffs", 1
        )[1].split("function technoeconomicTableCell", 1)[0]
        energy_classes = {
            "positive_lifecycle_gain",
            "zero_lifecycle_gain",
            "negative_lifecycle_gain",
        }
        tradeoff_classes = {
            "cost_increase_energy_gain",
            "cost_neutral_energy_gain",
            "cost_saving_energy_gain",
            "cost_increase_energy_loss",
            "cost_neutral_energy_loss",
            "cost_saving_energy_loss",
            "cost_increase_zero_energy_change",
            "cost_neutral_zero_energy_change",
            "cost_saving_zero_energy_change",
        }
        for key in energy_classes:
            self.assertEqual(tradeoffs.count(f"'{key}'"), 1, key)
        label_block = self.script.split(
            "const TECHNOECONOMIC_TRADEOFF_LABELS", 1
        )[1].split("};", 1)[0]
        for key in tradeoff_classes:
            self.assertEqual(label_block.count(f"{key}:"), 1, key)
            self.assertEqual(tradeoffs.count(f"'{key}'"), 1, key)
        for key in (
            "cost_increase_energy_loss",
            "cost_neutral_energy_loss",
            "cost_saving_energy_loss",
        ):
            label_line = next(
                line for line in label_block.splitlines() if f"{key}:" in line
            )
            self.assertIn("lower energy", label_line.lower())
            self.assertNotIn("favorable", label_line.lower())
        self.assertIn("summaries.energy_classes", tradeoffs)
        self.assertIn("summaries.tradeoff_classes", tradeoffs)
        self.assertIn("technoeconomicTradeoffLabel(key)", tradeoffs)
        self.assertNotIn("technoeconomicDifferenceLabel", tradeoffs)

        per_year = self.script.split(
            "function technoeconomicRenderPerYear", 1
        )[1].split("function technoeconomicRenderSensitivity", 1)[0]
        self.assertIn("result.per_weather_year", per_year)
        self.assertIn("item.realization_share", per_year)
        self.assertIn("source_sol_specific_kwh_ac_per_wdc_year", per_year)
        self.assertIn("source_se_specific_kwh_ac_per_wdc_year", per_year)
        self.assertIn("source_sol_specific_kwh_ac_per_applied_w_year", per_year)
        self.assertIn("source_se_specific_kwh_ac_per_applied_w_year", per_year)
        self.assertIn("DeltaLifecycleCostPerAppliedW_se_minus_sol_USD_per_applied_W", per_year)

        sensitivity = self.script.split(
            "function technoeconomicRenderSensitivity", 1
        )[1].split("function technoeconomicConvergenceChange", 1)[0]
        self.assertIn("model.status !== 'available'", sensitivity)
        self.assertIn("model.reason", sensitivity)
        self.assertIn("model.exclusions", sensitivity)
        self.assertIn("No predictor met the entry threshold", sensitivity)

        convergence = self.script.split(
            "function technoeconomicRenderConvergence", 1
        )[1].split("function technoeconomicRenderResultSummary", 1)[0]
        self.assertIn("convergence.status === 'stable'", convergence)
        self.assertIn("convergence.reasons", convergence)
        self.assertIn("convergence.checkpoints", convergence)
        self.assertIn("not demonstrated", convergence)

        artifacts = self.script.split(
            "function technoeconomicRenderArtifacts", 1
        )[1].split("function renderTechnoeconomicJobResult", 1)[0]
        self.assertIn("job.artifacts", artifacts)
        self.assertIn("manifest.artifacts", artifacts)
        for artifact_id in (
            "cdf_plot",
            "sensitivity_plot",
            "convergence_plot",
            "csv_bundle",
            "xlsx_workbook",
        ):
            self.assertIn(f"safe('{artifact_id}')", artifacts)
        self.assertNotIn("sealed_calculation", artifacts)
        self.assertNotIn("canvas", artifacts.lower())

    @unittest.skipUnless(shutil.which("node"), "Node.js is required")
    def test_versioned_draft_and_job_id_persistence_never_cache_results(self) -> None:
        payload = self.run_node(
            r"""
const assert = require('node:assert/strict');
const memory = new Map();
globalThis.localStorage = {
  getItem(key) { return memory.has(key) ? memory.get(key) : null; },
  setItem(key, value) { memory.set(key, String(value)); },
  removeItem(key) { memory.delete(key); },
};
assert.equal(TECHNOECONOMIC_DRAFT_SCHEMA_VERSION, 'technoeconomic-draft-v3');
assert.equal(TECHNOECONOMIC_DRAFT_STORAGE_KEY, 'sbepv.technoeconomic.draft.v3');
const previous = technoeconomicDefaultDraft();
previous.schema_version = 'technoeconomic-draft-v2';
previous.source_annual_job_id = 'annual-v2-preserved';
previous.project_life_years = '31';
previous.cost_lines[0].normalized_unit = 'usd_per_wdc';
previous.cost_lines[0].normalization_method = 'divide_by_frozen_source_wdc';
memory.set(TECHNOECONOMIC_PREVIOUS_DRAFT_STORAGE_KEY, JSON.stringify(previous));
const previousDraft = technoeconomicLoadLocalDraft();
assert.equal(previousDraft.schema_version, TECHNOECONOMIC_DRAFT_SCHEMA_VERSION);
assert.equal(previousDraft.source_annual_job_id, 'annual-v2-preserved');
assert.equal(previousDraft.project_life_years, '31');
assert.equal(previousDraft.capacity_normalization, 'annual_applied_capacity_v1');
assert.equal(previousDraft.cost_lines[0].normalized_unit, 'usd_per_applied_w');
assert.equal(previousDraft.cost_lines[0].normalization_method,
  'divide_by_frozen_applied_capacity_w');
memory.delete(TECHNOECONOMIC_PREVIOUS_DRAFT_STORAGE_KEY);
memory.set('sbepv.technoeconomic.draft.v1', JSON.stringify({
  schema_version: 'technoeconomic-draft-v1',
  source_annual_job_id: 'annual-obsolete-guided',
  cost_lines: [{input_id: 'cost.guided.base-capex'}],
}));
const legacyDraft = technoeconomicLoadLocalDraft();
assert.equal(legacyDraft.schema_version, TECHNOECONOMIC_DRAFT_SCHEMA_VERSION);
assert.equal(legacyDraft.entry_mode, TECHNOECONOMIC_ADVANCED_ENTRY_MODE);
assert.equal(legacyDraft.source_annual_job_id, 'annual-obsolete-guided');
assert.equal(memory.has(TECHNOECONOMIC_DRAFT_STORAGE_KEY), false);
memory.delete(TECHNOECONOMIC_LEGACY_DRAFT_STORAGE_KEY);
memory.set(TECHNOECONOMIC_DRAFT_STORAGE_KEY, JSON.stringify({
  schema_version: 'obsolete-draft-v0', source_annual_job_id: 'annual-old',
}));
assert.equal(technoeconomicLoadLocalDraft(), null);

const draft = technoeconomicDefaultDraft();
Object.assign(draft, {
  schema_version: TECHNOECONOMIC_DRAFT_SCHEMA_VERSION,
  source_annual_job_id: 'annual-source-1', basis: 'solartac_site',
  result: {private_realizations: [1, 2, 3]},
  artifacts: {sealed_calculation: {path: 'private'}},
});
memory.set(TECHNOECONOMIC_DRAFT_STORAGE_KEY, JSON.stringify(draft));
const loaded = technoeconomicLoadLocalDraft();
assert.equal(loaded.source_annual_job_id, 'annual-source-1');
assert.equal('result' in loaded, false);
assert.equal('artifacts' in loaded, false);

technoeconomicPersistActiveJobId('tea_fixture');
assert.equal(memory.get(TECHNOECONOMIC_ACTIVE_JOB_STORAGE_KEY), 'tea_fixture');
assert.equal(technoeconomicLoadActiveJobId(), 'tea_fixture');
memory.set(TECHNOECONOMIC_ACTIVE_JOB_STORAGE_KEY, 'tea_bad/path');
assert.equal(technoeconomicLoadActiveJobId(), null);

assert.throws(() => technoeconomicNormalizeJob({
  job_id: 'tea_fixture', workflow: 'annual', state: 'done', result: {private: true},
}), (error) => error.code === 'invalid_job_response');
console.log(JSON.stringify({
  version: loaded.schema_version,
  storageKey: TECHNOECONOMIC_DRAFT_STORAGE_KEY,
  draftKeys: Object.keys(loaded).sort(),
  storedJob: memory.get(TECHNOECONOMIC_ACTIVE_JOB_STORAGE_KEY),
}));
"""
        )
        self.assertEqual("technoeconomic-draft-v3", payload["version"])
        self.assertEqual("sbepv.technoeconomic.draft.v3", payload["storageKey"])
        self.assertNotIn("result", payload["draftKeys"])
        self.assertNotIn("artifacts", payload["draftKeys"])

        save_block = self.state_script.split(
            "localStorage.setItem(STORAGE_KEY", 1
        )[1].split("));", 1)[0]
        self.assertIn("technoeconomicForm: getTechnoeconomicFormState()", save_block)
        self.assertIn("technoeconomicActiveJobId", save_block)
        self.assertNotIn("technoeconomicJob", save_block)
        self.assertNotIn("technoeconomicResult", save_block)

        self.assertIn(
            "saved.technoeconomicForm?.schema_version === "
            "TECHNOECONOMIC_DRAFT_SCHEMA_VERSION",
            self.restore_script,
        )
        self.assertIn(
            "if (!dedicatedTechnoeconomicForm && savedTechnoeconomicForm)",
            self.restore_script,
        )
        self.assertNotIn(
            "applyTechnoeconomicFormState(savedTechnoeconomicForm);\n"
            "            await loadCurrentCalibration()",
            self.restore_script,
        )
        self.assertIn("restoreTechnoeconomicActiveJob()", self.restore_script)

    @unittest.skipUnless(shutil.which("node"), "Node.js is required")
    def test_draft_sanitizer_preserves_only_versioned_form_and_job_identity(self) -> None:
        payload = self.run_node(
            r"""
const baseLine = {
  input_id: 'cost.sol.fixture', label: 'Fixture cost', ownership: 'solectria_only',
  cost_type: 'initial_capex', coverage_include_ids: ['equipment.sol'],
  coverage_exclude_ids: [], original_unit: 'usd_total',
  normalized_unit: 'usd_per_wdc', normalization_method: 'divide_by_frozen_source_wdc',
  solectria_quantity: '1', solaredge_quantity: '0', quantity_unit: '',
  normalization_derivation: 'Divide by frozen Wdc.', extra_private: 'drop-me',
};
const families = [
  {family: 'fixed', value: '10'},
  {family: 'uniform', low: '1', high: '2'},
  {family: 'triangular', low: '1', mode: '2', high: '3'},
  {family: 'bounded_normal', low: '1', high: '3', mean: '2', sd: '0.2'},
];
const draft = sanitizeTechnoeconomicDraft({
  schema_version: 'untrusted-old-version',
  source_annual_job_id: 'annual_fixture', basis: 'solartac_site', n: '2000',
  seed: '9007199254740991', cost_year: '2026', project_life_years: '20',
  cost_lines: families.map((distribution, index) => ({
    ...baseLine, input_id: `cost.sol.fixture-${index}`, distribution,
  })),
  active_job_id: 'tea_fixture', result: {private: true}, artifacts: {path: 'secret'},
  unexpected: 'drop-me',
});
console.log(JSON.stringify({
  version: draft.schema_version,
  source: draft.source_annual_job_id,
  basis: draft.basis,
  n: draft.n,
  seed: draft.seed,
  activeJob: draft.active_job_id,
  families: draft.cost_lines.map((line) => line.distribution.family),
  hasResult: Object.prototype.hasOwnProperty.call(draft, 'result'),
  hasArtifacts: Object.prototype.hasOwnProperty.call(draft, 'artifacts'),
  hasUnexpected: Object.prototype.hasOwnProperty.call(draft, 'unexpected'),
  lineHasPrivate: Object.prototype.hasOwnProperty.call(draft.cost_lines[0], 'extra_private'),
  transferMechanisms: draft.commercial_transfer.mechanisms.map((item) => item.mechanism),
}));
"""
        )
        self.assertEqual("technoeconomic-draft-v3", payload["version"])
        self.assertEqual("annual_fixture", payload["source"])
        self.assertEqual("solartac_site", payload["basis"])
        self.assertEqual("2000", payload["n"])
        self.assertEqual("9007199254740991", payload["seed"])
        self.assertEqual("tea_fixture", payload["activeJob"])
        self.assertEqual(
            ["fixed", "uniform", "triangular", "bounded_normal"],
            payload["families"],
        )
        self.assertFalse(payload["hasResult"])
        self.assertFalse(payload["hasArtifacts"])
        self.assertFalse(payload["hasUnexpected"])
        self.assertFalse(payload["lineHasPrivate"])
        self.assertEqual(13, len(payload["transferMechanisms"]))
        self.assertEqual(13, len(set(payload["transferMechanisms"])))

    @unittest.skipUnless(shutil.which("node"), "Node.js is required")
    def test_draft_sanitizer_never_silently_truncates_api_bounded_values(self) -> None:
        payload = self.run_node(
            self.tea_fixture_helpers()
            + r"""
const assert = require('node:assert/strict');
const longLabel = 'L'.repeat(4001);
const longActiveJobId = `tea_${'a'.repeat(240)}`;
const coverageIds = Array.from({length: 257}, (_, index) =>
  `equipment.sol.part-${String(index).padStart(3, '0')}`);
const manyCostLines = Array.from({length: 1001}, (_, index) => ({
  ...technoeconomicDefaultCostLine(index % 2 ? 'solaredge' : 'solectria', index),
  input_id: `cost.${index % 2 ? 'se' : 'sol'}.line-${index}`,
  label: index === 0 ? longLabel : `Cost line ${index}`,
  coverage_include_ids: index === 0 ? coverageIds : [`equipment.unique-${index}`],
}));
const sanitized = sanitizeTechnoeconomicDraft({
  source_annual_job_id: 'annual-source-1', basis: 'solartac_site',
  cost_year: '2025', cost_lines: manyCostLines, active_job_id: longActiveJobId,
});

// The API bounds are 4,000 text characters, 256 coverage IDs, and 1,000
// cost lines. The browser must preserve an over-limit draft so validation can
// reject it explicitly; slicing would silently submit a different request.
assert.equal(sanitized.cost_lines[0].label.length, 4001);
assert.equal(sanitized.cost_lines[0].coverage_include_ids.length, 257);
assert.equal(sanitized.cost_lines.length, 1001);
assert.equal(sanitized.active_job_id, null);

const textDraft = solarTacDraft();
textDraft.cost_lines[0].label = longLabel;
const rejectedText = serializeTechnoeconomicRequest(textDraft, {
  sources: [{source_annual_job_id: 'annual-source-1', eligible: true}],
});
assert.equal(rejectedText.valid, false);
assert.ok(rejectedText.errors.some((item) =>
  item.path === 'cost_lines[0].label' && item.message.includes('4000')));

const listDraft = solarTacDraft();
listDraft.cost_lines[0].coverage_include_ids = coverageIds;
const rejectedList = serializeTechnoeconomicRequest(listDraft, {
  sources: [{source_annual_job_id: 'annual-source-1', eligible: true}],
});
assert.equal(rejectedList.valid, false);
assert.ok(rejectedList.errors.some((item) =>
  item.path === 'cost_lines[0].coverage_include_ids' && item.message.includes('256')));

const lineDraft = solarTacDraft();
lineDraft.n = '1';
lineDraft.cost_lines = manyCostLines.map((line, index) => ({
  ...line,
  label: `Cost line ${index}`,
  distribution: {family: 'fixed', value: '1'},
  normalization_derivation: 'Source total divided by frozen source Wdc.',
  constant_dollar_cost_year: '2025',
  currency_year_normalization: {
    method: 'same_year_no_adjustment', source_cost_year: '2025',
    target_constant_dollar_cost_year: '2025',
    submitted_distribution_basis: 'target_constant_dollar_year',
    index_identity: 'not_applicable_same_year', index_factor: '1',
    derivation: 'No price adjustment because source and target years match.',
    index_source_evidence: teaEvidence(`INDEX-${index}`),
  },
  evidence: teaEvidence(`COST-${index}`),
}));
const rejectedLines = serializeTechnoeconomicRequest(lineDraft, {
  sources: [{source_annual_job_id: 'annual-source-1', eligible: true}],
});
assert.equal(rejectedLines.valid, false);
assert.ok(rejectedLines.errors.some((item) =>
  item.path === 'cost_lines' && item.message.replaceAll(',', '').includes('1000')));

const memory = new Map();
globalThis.localStorage = {
  getItem(key) { return memory.has(key) ? memory.get(key) : null; },
  setItem(key, value) { memory.set(key, String(value)); },
  removeItem(key) { memory.delete(key); },
};
technoeconomicPersistActiveJobId(longActiveJobId);
assert.equal(technoeconomicLoadActiveJobId(), null);
assert.equal(memory.has(TECHNOECONOMIC_ACTIVE_JOB_STORAGE_KEY), false);
const maximumActiveJobId = `tea_${'b'.repeat(196)}`;
technoeconomicPersistActiveJobId(maximumActiveJobId);
assert.equal(technoeconomicLoadActiveJobId(), maximumActiveJobId);
console.log(JSON.stringify({
  labelLength: sanitized.cost_lines[0].label.length,
  coverageCount: sanitized.cost_lines[0].coverage_include_ids.length,
  costLineCount: sanitized.cost_lines.length,
  activeJobLength: technoeconomicLoadActiveJobId().length,
}));
"""
        )
        self.assertEqual(4001, payload["labelLength"])
        self.assertEqual(257, payload["coverageCount"])
        self.assertEqual(1001, payload["costLineCount"])
        self.assertEqual(200, payload["activeJobLength"])

    @unittest.skipUnless(shutil.which("node"), "Node.js is required")
    def test_server_session_mismatch_preserves_dedicated_draft_and_job(self) -> None:
        restore_function = (
            "async function restoreDashboardState"
            + self.restore_script.split(
                "async function restoreDashboardState", 1
            )[1].split("function invalidateAnnualRequestFromFormEdit", 1)[0]
        )
        payload = self.run_node(
            restore_function
            + r"""
const assert = require('node:assert/strict');
const memory = new Map();
const dedicatedDraft = technoeconomicDefaultDraft();
Object.assign(dedicatedDraft, {
  source_annual_job_id: 'annual-newer-dedicated', basis: 'solartac_site',
});
memory.set(TECHNOECONOMIC_DRAFT_STORAGE_KEY, JSON.stringify(dedicatedDraft));
memory.set(TECHNOECONOMIC_ACTIVE_JOB_STORAGE_KEY, 'tea_newer_dedicated');
globalThis.localStorage = {
  getItem(key) { return memory.has(key) ? memory.get(key) : null; },
  setItem(key, value) { memory.set(key, String(value)); },
  removeItem(key) { memory.delete(key); },
};
const saved = {
  serverSessionId: 'server-session-before-restart',
  technoeconomicForm: {
    ...dedicatedDraft, source_annual_job_id: 'annual-stale-generic',
  },
  technoeconomicActiveJobId: 'tea_stale_generic',
};
let resetOptions = null;
Object.assign(globalThis, {
  chatDraft: '', chatInput: {}, agentExplainedJobs: new Set(),
  readSavedState: () => saved,
  restoreChatConversationHistory() {}, autoResizeChatInput() {},
  syncChatComposerState() {}, renderChatMessages() {},
  setChatHistoryOpen() {}, setChatOpen() {},
  loadServerSessionId: async () => 'server-session-after-restart',
  clearSavedState() {},
  resetClientState(options = {}) {
    resetOptions = options;
    if (options.preserveTechnoeconomic !== true) {
      memory.delete(TECHNOECONOMIC_DRAFT_STORAGE_KEY);
      memory.delete(TECHNOECONOMIC_ACTIVE_JOB_STORAGE_KEY);
      technoeconomicActiveJobId = null;
    }
  },
  loadCurrentCalibration: async () => {}, saveDashboardState() {},
  releaseChatHydration() {}, refreshAgentState: async () => {},
});
refreshTechnoeconomicSources = async () => [];
restoreTechnoeconomicActiveJob = async () => null;
(async () => {
  await restoreDashboardState();
  assert.equal(resetOptions?.preserveTechnoeconomic, true);
  assert.equal(
    JSON.parse(memory.get(TECHNOECONOMIC_DRAFT_STORAGE_KEY)).source_annual_job_id,
    'annual-newer-dedicated'
  );
  assert.equal(
    memory.get(TECHNOECONOMIC_ACTIVE_JOB_STORAGE_KEY), 'tea_newer_dedicated'
  );
  console.log(JSON.stringify({preserved: true, resetOptions}));
})().catch((error) => { console.error(error); process.exitCode = 1; });
"""
        )
        self.assertTrue(payload["preserved"])
        self.assertTrue(payload["resetOptions"]["preserveTechnoeconomic"])
        self.assertIn("await reconnectTechnoeconomicWorkspace()", self.restore_script)

    @unittest.skipUnless(shutil.which("node"), "Node.js is required")
    def test_lifecycle_requests_are_deduplicated_and_revision_fenced(self) -> None:
        payload = self.run_node(
            r"""
const assert = require('node:assert/strict');
function deferred() {
  let resolve;
  const promise = new Promise((done) => { resolve = done; });
  return {promise, resolve};
}
const confirmationDialog = {
  open: true,
  close() { this.open = false; },
  removeAttribute() { this.open = false; },
};
globalThis.technoeconomicElements = {
  jobError: null, confirmError: null,
  confirmSubmitButton: {disabled: false, textContent: 'Confirm and queue'},
  confirmCancelButton: {disabled: false}, submitButton: {disabled: false},
  confirmDialog: confirmationDialog,
};
let adopted = [];
technoeconomicAdoptJob = (value) => {
  const job = value.job || value;
  adopted.push(job.job_id);
  technoeconomicActiveJobId = job.job_id;
  return job;
};

(async () => {
  const staleResponse = deferred();
  let fetchCalls = 0;
  technoeconomicFetchJson = async () => {
    fetchCalls += 1;
    return staleResponse.promise;
  };
  technoeconomicActiveJobId = 'tea_old';
  const staleRequest = technoeconomicLifecycleRequest('cancel');
  technoeconomicPersistActiveJobId('tea_new');
  staleResponse.resolve({job: {
    job_id: 'tea_old', workflow: 'technoeconomic', state: 'cancelled',
  }});
  assert.equal(await staleRequest, null);
  assert.deepEqual(adopted, []);
  assert.equal(technoeconomicActiveJobId, 'tea_new');

  const oneResponse = deferred();
  fetchCalls = 0;
  technoeconomicFetchJson = async () => {
    fetchCalls += 1;
    return oneResponse.promise;
  };
  technoeconomicActiveJobId = 'tea_same';
  const first = technoeconomicLifecycleRequest('cancel');
  const duplicate = technoeconomicLifecycleRequest('cancel');
  await Promise.resolve();
  assert.equal(fetchCalls, 1);
  oneResponse.resolve({job: {
    job_id: 'tea_same', workflow: 'technoeconomic', state: 'cancelled',
  }});
  await Promise.all([first, duplicate]);
  assert.deepEqual(adopted, ['tea_same']);

  const actionResponse = deferred();
  fetchCalls = 0;
  technoeconomicFetchJson = async () => {
    fetchCalls += 1;
    return actionResponse.promise;
  };
  technoeconomicActiveJobId = 'tea_cross_action';
  technoeconomicPendingSubmission = null;
  const action = technoeconomicLifecycleRequest('retry');
  technoeconomicPendingSubmission = {draftRevision: technoeconomicDraftRevision, payload: {}};
  technoeconomicRenderApiError = () => {};
  await technoeconomicConfirmSubmission();
  assert.equal(fetchCalls, 1);
  actionResponse.resolve({job: {
    job_id: 'tea_retry', workflow: 'technoeconomic', state: 'queued',
  }});
  await action;
  technoeconomicPendingSubmission = null;

  technoeconomicSubmissionRequestInFlight = true;
  const blockedLifecycle = await technoeconomicLifecycleRequest('cancel');
  technoeconomicSubmissionRequestInFlight = false;
  assert.equal(blockedLifecycle, null);
  assert.equal(fetchCalls, 1);

  const submissionResponse = deferred();
  let submissionFetchCalls = 0;
  technoeconomicFetchJson = async () => {
    submissionFetchCalls += 1;
    return submissionResponse.promise;
  };
  technoeconomicPendingSubmission = {
    draftRevision: technoeconomicDraftRevision, payload: {fixture: true},
  };
  confirmationDialog.open = true;
  const submission = technoeconomicConfirmSubmission();
  await Promise.resolve();
  assert.equal(technoeconomicElements.confirmCancelButton.disabled, true);
  const frozenPending = technoeconomicPendingSubmission;
  technoeconomicCloseConfirmation();
  assert.equal(confirmationDialog.open, true);
  assert.equal(technoeconomicPendingSubmission, frozenPending);
  submissionResponse.resolve({job: {
    job_id: 'tea_created', workflow: 'technoeconomic', state: 'done',
  }});
  await submission;
  assert.equal(submissionFetchCalls, 1);
  assert.equal(technoeconomicActiveJobId, 'tea_created');
  assert.equal(technoeconomicElements.confirmCancelButton.disabled, false);
  console.log(JSON.stringify({
    fetchCalls, active: technoeconomicActiveJobId, submissionFetchCalls,
  }));
})().catch((error) => { console.error(error); process.exitCode = 1; });
"""
        )
        self.assertEqual(1, payload["fetchCalls"])
        self.assertEqual("tea_created", payload["active"])
        self.assertEqual(1, payload["submissionFetchCalls"])
        self.assertIn(
            "if (technoeconomicSubmissionRequestInFlight) {\n"
            "                    event.preventDefault();",
            self.script,
        )

    @unittest.skipUnless(shutil.which("node"), "Node.js is required")
    def test_decimal_equivalent_commercial_reference_wdc_is_accepted(self) -> None:
        payload = self.run_node(
            self.tea_fixture_helpers()
            + r"""
const assert = require('node:assert/strict');
const draft = commercialDraft(false);
Object.assign(draft.commercial_reference_design, {
  reference_wdc: '0.3', module_stc_wdc: '0.1', module_count: '3',
  normalization_derivation: 'Three modules at 0.1 Wdc equal 0.3 Wdc.',
});
const result = serializeTechnoeconomicRequest(draft, {
  sources: [{source_annual_job_id: 'annual-source-2', eligible: true}],
});
assert.equal(result.valid, true, JSON.stringify(result.errors));
assert.equal(result.payload.commercial_reference_design.reference_wdc, 0.3);
assert.equal(result.payload.commercial_reference_design.module_stc_wdc, 0.1);
assert.equal(result.payload.commercial_reference_design.module_count, 3);
const floatNormalizedDraft = commercialDraft(false);
Object.assign(floatNormalizedDraft.commercial_reference_design, {
  reference_wdc: '0.3', module_stc_wdc: '0.10000000000000001', module_count: '3',
  normalization_derivation: 'The API number normalizes this module rating to 0.1 Wdc.',
});
const floatNormalized = serializeTechnoeconomicRequest(floatNormalizedDraft, {
  sources: [{source_annual_job_id: 'annual-source-2', eligible: true}],
});
assert.equal(floatNormalized.valid, true, JSON.stringify(floatNormalized.errors));
assert.equal(floatNormalized.payload.commercial_reference_design.module_stc_wdc, 0.1);
console.log(JSON.stringify({
  valid: result.valid, errors: result.errors, floatNormalized: floatNormalized.valid,
}));
"""
        )
        self.assertTrue(payload["valid"])
        self.assertTrue(payload["floatNormalized"])
        self.assertEqual([], payload["errors"])

    @unittest.skipUnless(shutil.which("node"), "Node.js is required")
    def test_missing_active_job_remains_a_visible_recoverable_state(self) -> None:
        payload = self.run_node(
            r"""
const assert = require('node:assert/strict');
const jobPanel = {hidden: false, dataset: {}};
const jobError = {
  hidden: true, dataset: {}, lastError: null,
  replaceChildren() {}, focus() {},
};
globalThis.technoeconomicElements = {
  jobPanel, jobError,
  jobState: {textContent: ''}, progress: {value: 40},
  progressValue: {textContent: '40%'}, progressStage: {textContent: 'Restoring'},
};
technoeconomicRenderApiError = (element, error) => {
  element.hidden = false;
  element.lastError = error;
};
technoeconomicFetchJson = async () => {
  throw {status: 404, code: 'not_found', message: 'Unknown technoeconomic job id', fields: []};
};
(async () => {
  technoeconomicActiveJobId = 'tea_missing';
  const revision = technoeconomicStatusRequestRevision;
  await technoeconomicPollJob('tea_missing', revision);
  assert.equal(technoeconomicActiveJobId, null);
  assert.equal(jobPanel.hidden, false);
  assert.equal(jobError.hidden, false);
  assert.equal(jobError.lastError.code, 'not_found');
  console.log(JSON.stringify({
    panelVisible: !jobPanel.hidden, errorVisible: !jobError.hidden,
    errorCode: jobError.lastError.code,
  }));
})().catch((error) => { console.error(error); process.exitCode = 1; });
"""
        )
        self.assertTrue(payload["panelVisible"])
        self.assertTrue(payload["errorVisible"])
        self.assertEqual("not_found", payload["errorCode"])

    @unittest.skipUnless(shutil.which("node"), "Node.js is required")
    def test_confirmation_discloses_materially_frozen_request_details(self) -> None:
        payload = self.run_node(
            self.tea_fixture_helpers()
            + r"""
const assert = require('node:assert/strict');
const draft = commercialDraft(true);
draft.discount_rate.distribution = {
  family: 'triangular', low: '0.03', mode: '0.05', high: '0.07',
};
draft.cost_lines[1].distribution = {family: 'uniform', low: '1.1', high: '1.5'};
const serialized = serializeTechnoeconomicRequest(draft, {
  sources: [{source_annual_job_id: 'annual-source-2', eligible: true}],
});
assert.equal(serialized.valid, true, JSON.stringify(serialized.errors));
serialized.payload = technoeconomicDeepFreeze(
  JSON.parse(JSON.stringify(serialized.payload))
);
const rendered = [];
technoeconomicSummaryItem = (label, value) => ({label, value: String(value)});
globalThis.technoeconomicElements = {
  confirmSummary: {replaceChildren(...items) { rendered.push(...items); }},
  confirmProvisional: {hidden: true, textContent: ''}, confirmError: null,
};
technoeconomicRenderConfirmation(serialized, {
  source_annual_job_id: 'annual-source-2', source_snapshot_sha256: 'f'.repeat(64),
  eligible_years: [2023, 2024], solectria_installed_wdc: 1000,
  solaredge_installed_wdc: 1000,
});
const disclosure = rendered.map((item) => `${item.label}: ${item.value}`).join('\n');
for (const materialValue of [
  'triangular', '0.03', '0.05', '0.07',
  'uniform', '1.1', '1.5',
  'RATE', 'COST-0', 'COST-1', 'DESIGN',
  'commercial-reference-550kw', 'Example 550 W module',
  'Five central inverters', 'Ten string inverters with module optimizers',
  'Test analyst', 'TRANSFER-BASE', 'TRANSFER-INCREMENT',
  'climate_and_irradiance', 'MECH-0',
]) assert.ok(disclosure.includes(materialValue), materialValue);
assert.equal(Object.isFrozen(serialized.payload), true);
assert.equal(Object.isFrozen(serialized.payload.cost_lines[0].distribution), true);
console.log(JSON.stringify({itemCount: rendered.length, disclosure}));
"""
        )
        self.assertGreater(payload["itemCount"], 13)
        self.assertIn("TRANSFER-INCREMENT", payload["disclosure"])

    @unittest.skipUnless(shutil.which("node"), "Node.js is required")
    def test_persistence_failure_is_reported_and_generic_state_is_fallback_only(self) -> None:
        persistence = self.run_node(
            r"""
const assert = require('node:assert/strict');
globalThis.technoeconomicElements = {draftStatus: {textContent: ''}};
globalThis.localStorage = {
  getItem() { return null; },
  setItem() { throw new Error('quota exceeded'); },
  removeItem() { throw new Error('storage unavailable'); },
};
const draftSaved = technoeconomicPersistDraft();
const activeJobSaved = technoeconomicPersistActiveJobId('tea_fixture');
console.log(JSON.stringify({
  draftSaved: draftSaved ?? null, activeJobSaved: activeJobSaved ?? null,
  status: technoeconomicElements.draftStatus.textContent,
}));
"""
        )

        restore_function = (
            "async function restoreDashboardState"
            + self.restore_script.split(
                "async function restoreDashboardState", 1
            )[1].split("function invalidateAnnualRequestFromFormEdit", 1)[0]
        )
        restored = self.run_node(
            restore_function
            + r"""
const assert = require('node:assert/strict');
const memory = new Map();
const dedicatedDraft = technoeconomicDefaultDraft();
Object.assign(dedicatedDraft, {
  source_annual_job_id: 'annual-newer-dedicated', basis: 'solartac_site',
});
memory.set(TECHNOECONOMIC_DRAFT_STORAGE_KEY, JSON.stringify(dedicatedDraft));
memory.set(TECHNOECONOMIC_ACTIVE_JOB_STORAGE_KEY, 'tea_newer_dedicated');
globalThis.localStorage = {
  getItem(key) { return memory.has(key) ? memory.get(key) : null; },
  setItem(key, value) { memory.set(key, String(value)); },
  removeItem(key) { memory.delete(key); },
};
technoeconomicActiveJobId = 'tea_newer_dedicated';
const saved = {
  serverSessionId: 'same-session',
  technoeconomicForm: {
    ...dedicatedDraft, source_annual_job_id: 'annual-stale-generic',
  },
  technoeconomicActiveJobId: 'tea_stale_generic',
};
const appliedSources = [];
Object.assign(globalThis, {
  chatDraft: '', chatInput: {}, agentExplainedJobs: new Set(),
  readSavedState: () => saved,
  restoreChatConversationHistory() {}, autoResizeChatInput() {},
  syncChatComposerState() {}, renderChatMessages() {},
  setChatHistoryOpen() {}, setChatOpen() {},
  loadServerSessionId: async () => 'same-session',
  revalidateCachedCompletedRun: async () => {},
  normalizeAnnualSeasonalFallbackDisplay: () => null,
  applyFormState() {}, applyValidationDateDefaults() {}, applyAnnualFormState() {},
  loadCurrentCalibration: async () => {}, refreshTechnoeconomicSources: async () => {},
  restoreTechnoeconomicActiveJob: async () => null,
  switchMode() {}, renderChatHistory() {}, saveDashboardState() {},
  releaseChatHydration() {}, refreshAgentState: async () => {},
  clearSavedState() {},
});
refreshTechnoeconomicSources = async () => [];
restoreTechnoeconomicActiveJob = async () => null;
applyTechnoeconomicFormState = (draft) => {
  appliedSources.push(draft.source_annual_job_id);
  return true;
};
globalThis.window = {restoreSavedResultsDisplayedContext() {}};
(async () => {
  await restoreDashboardState();
  assert.equal(appliedSources.includes('annual-stale-generic'), false);
  assert.equal(technoeconomicActiveJobId, 'tea_newer_dedicated');
  assert.equal(
    JSON.parse(memory.get(TECHNOECONOMIC_DRAFT_STORAGE_KEY)).source_annual_job_id,
    'annual-newer-dedicated'
  );
  console.log(JSON.stringify({appliedSources, activeJob: technoeconomicActiveJobId}));
})().catch((error) => { console.error(error); process.exitCode = 1; });
"""
        )
        self.assertIs(persistence["draftSaved"], False)
        self.assertIs(persistence["activeJobSaved"], False)
        self.assertRegex(
            persistence["status"],
            r"(?i)(?:not saved|could not save|storage (?:is )?unavailable)",
        )
        self.assertNotIn("annual-stale-generic", restored["appliedSources"])
        self.assertEqual("tea_newer_dedicated", restored["activeJob"])

    @unittest.skipUnless(shutil.which("node"), "Node.js is required")
    def test_artifact_urls_fail_closed_to_the_exact_public_job_routes(self) -> None:
        payload = self.run_node(
            r"""
const job = 'tea_fixture';
const base = '/api/technoeconomic/jobs/' + job + '/';
console.log(JSON.stringify({
  csv: technoeconomicSafeArtifactUrl(job, 'csv_bundle', base + 'exports/csv'),
  xlsx: technoeconomicSafeArtifactUrl(job, 'xlsx_workbook', base + 'exports/xlsx'),
  cdf: technoeconomicSafeArtifactUrl(job, 'cdf_plot', base + 'artifacts/cdf_plot'),
  sensitivity: technoeconomicSafeArtifactUrl(job, 'sensitivity_plot', base + 'artifacts/sensitivity_plot'),
  convergence: technoeconomicSafeArtifactUrl(job, 'convergence_plot', base + 'artifacts/convergence_plot'),
  privateArtifact: technoeconomicSafeArtifactUrl(job, 'sealed_calculation', base + 'artifacts/sealed_calculation'),
  wrongJob: technoeconomicSafeArtifactUrl(job, 'cdf_plot', '/api/technoeconomic/jobs/tea_other/artifacts/cdf_plot'),
  query: technoeconomicSafeArtifactUrl(job, 'cdf_plot', base + 'artifacts/cdf_plot?download=1'),
  crossOrigin: technoeconomicSafeArtifactUrl(job, 'cdf_plot', 'https://evil.example/cdf.png'),
  encodedSlash: technoeconomicSafeArtifactUrl(job, 'cdf_plot', '/api/technoeconomic/jobs/tea_fixture%2Fother/artifacts/cdf_plot'),
  modelJob: technoeconomicSafeArtifactUrl('job_fixture', 'cdf_plot', '/api/technoeconomic/jobs/job_fixture/artifacts/cdf_plot'),
}));
"""
        )
        prefix = "/api/technoeconomic/jobs/tea_fixture/"
        self.assertEqual(prefix + "exports/csv", payload["csv"])
        self.assertEqual(prefix + "exports/xlsx", payload["xlsx"])
        self.assertEqual(prefix + "artifacts/cdf_plot", payload["cdf"])
        self.assertEqual(
            prefix + "artifacts/sensitivity_plot", payload["sensitivity"]
        )
        self.assertEqual(
            prefix + "artifacts/convergence_plot", payload["convergence"]
        )
        for field in (
            "privateArtifact",
            "wrongJob",
            "query",
            "crossOrigin",
            "encodedSlash",
            "modelJob",
        ):
            self.assertIsNone(payload[field], field)

    @unittest.skipUnless(shutil.which("node"), "Node.js is required")
    def test_technoeconomic_script_parses_in_node(self) -> None:
        completed = subprocess.run(
            [shutil.which("node"), "--check", str(self.script_path)],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(0, completed.returncode, completed.stderr)


if __name__ == "__main__":
    unittest.main()
