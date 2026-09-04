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
    """Contract tests for the server-authoritative TEA workspace."""

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

    def test_guided_commercial_scaling_is_optional_explicit_and_accessible(self) -> None:
        commercial_ids = (
            "technoeconomicGuidedCommercial",
            "technoeconomicGuidedCommercialHeading",
            "technoeconomicGuidedCommercialEnabled",
            "technoeconomicGuidedCommercialFields",
            "technoeconomicGuidedCommercialTargetCapacity",
            "technoeconomicGuidedCommercialTargetUnit",
            "technoeconomicGuidedCommercialRatingBasis",
            "technoeconomicGuidedCommercialSourceBasis",
            "technoeconomicGuidedCommercialCostTiming",
            "technoeconomicGuidedCommercialCost",
            "technoeconomicGuidedCommercialCostLow",
            "technoeconomicGuidedCommercialCostHigh",
            "technoeconomicGuidedCommercialRationale",
            "technoeconomicGuidedCommercialAccept",
            "technoeconomicCommercialResults",
            "technoeconomicCommercialResultsHeading",
            "technoeconomicCommercialResultStatus",
            "technoeconomicCommercialResultMetrics",
        )
        for element_id in commercial_ids:
            self.assertEqual(self.markup.count(f'id="{element_id}"'), 1, element_id)

        self.assertRegex(
            self.markup,
            r'<input[^>]*id="technoeconomicGuidedCommercialEnabled"[^>]*'
            r'type="checkbox"[^>]*aria-controls="technoeconomicGuidedCommercialFields"',
        )
        self.assertRegex(
            self.markup,
            r'id="technoeconomicGuidedCommercialFields"[^>]*\bhidden\b',
        )
        self.assertRegex(
            self.markup,
            r'id="technoeconomicCommercialResults"[^>]*'
            r'aria-labelledby="technoeconomicCommercialResultsHeading"[^>]*\bhidden\b',
        )
        self.assertIn('value="ac_operating_limit">AC operating limit', self.markup)
        self.assertIn('value="dc_installed_nameplate">DC installed nameplate', self.markup)
        self.assertIn('value="lifecycle_present_value">Lifecycle present value', self.markup)
        self.assertIn('value="equivalent_annual">Equivalent annual', self.markup)
        self.assertIn("Negative, zero, and positive values are supported", self.markup)
        self.assertIn("never inferred from an example", self.markup)
        self.assertIn("direct applied-capacity scaling", self.markup)
        self.assertIn('role="status" aria-live="polite"', self.markup)
        for cost_id in (
            "technoeconomicGuidedCommercialCost",
            "technoeconomicGuidedCommercialCostLow",
            "technoeconomicGuidedCommercialCostHigh",
        ):
            tag = re.search(rf'<input[^>]*id="{cost_id}"[^>]*>', self.markup)
            self.assertIsNotNone(tag)
            assert tag is not None
            self.assertNotRegex(tag.group(0), r'\bmin=')

        self.assertIn(".tea-guided-commercial-fields[hidden]", self.styles)
        self.assertIn(".tea-guided-commercial-grid", self.styles)
        self.assertIn(".tea-commercial-result-status[data-state=\"unavailable\"]", self.styles)

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
            '<form class="tea-form tea-standalone-workspace" id="technoeconomicForm" novalidate>',
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
            'id="technoeconomicConfirmCloseBtn"',
            'class="tea-confirm-review-grid"',
            'class="tea-confirm-scroll" role="region" aria-labelledby="technoeconomicConfirmReviewHeading" tabindex="0"',
            'id="technoeconomicConfirmReadiness"',
            'id="technoeconomicConfirmSummary"',
            'class="tea-action-row tea-confirm-actions tea-confirm-footer"',
            'LHS realizations',
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

        for marker in (
            'id="technoeconomicStandaloneResults"',
            'id="technoeconomicStandaloneCdfPlot"',
            'id="technoeconomicLcoePercentileTable"',
            '<caption>Commercial Solectria and SolarEdge lifecycle LCOE percentiles (P10, P50, and P90).',
            'role="region" aria-labelledby="technoeconomicLcoePercentilesHeading" tabindex="0"',
            '<dialog class="tea-assumptions-dialog" id="technoeconomicAssumptionsDialog"',
            'aria-labelledby="technoeconomicAssumptionsHeading"',
            'aria-describedby="technoeconomicAssumptionsDescription"',
            'aria-controls="technoeconomicAssumptionsDialog" aria-haspopup="dialog"',
            'id="technoeconomicAssumptionsCloseBtn"',
            'id="technoeconomicAssumptionsReviewBtn" type="submit" hidden>Review &amp; calculate',
        ):
            self.assertIn(marker, self.markup)

        self.assertNotIn('id="technoeconomicAssumptionsFooterCloseBtn"', self.markup)
        self.assertNotIn('id="technoeconomicAssumptionsDetails"', self.markup)
        self.assertNotIn('<details class="tea-standalone-assumptions"', self.markup)

    def test_scenario_builder_is_guided_persistent_and_contract_aware(self) -> None:
        dialog = self.markup.split(
            '<dialog class="tea-assumptions-dialog" id="technoeconomicAssumptionsDialog"',
            1,
        )[1].split("</dialog>", 1)[0]
        self.assertIn('aria-label="Scenario Builder sections"', dialog)
        self.assertEqual(6, dialog.count('data-tea-builder-step='))
        for label in (
            "Source &amp; Scale", "Finance", "Lifecycle", "Reliability", "Value",
            "Evidence &amp; Review",
        ):
            self.assertIn(label, dialog)
        for summary_id in (
            "technoeconomicBuilderTarget", "technoeconomicBuilderLife",
            "technoeconomicBuilderTrials", "technoeconomicBuilderContract",
            "technoeconomicBuilderSource", "technoeconomicBuilderCompletion",
            "technoeconomicBuilderIssues",
        ):
            self.assertIn(f'id="{summary_id}"', dialog)
        for control_id in (
            "technoeconomicBuilderSaveBtn", "technoeconomicBuilderBackBtn",
            "technoeconomicBuilderContinueBtn", "technoeconomicBuilderReviewSummary",
        ):
            self.assertIn(f'id="{control_id}"', dialog)
        self.assertIn('data-tea-builder-v5-section="reliability"', dialog)
        self.assertIn('data-tea-builder-v5-section="value"', dialog)
        self.assertIn("function technoeconomicBuilderIssueTarget", self.script)
        self.assertIn("function technoeconomicBuilderRenderInlineErrors", self.script)
        self.assertIn("function technoeconomicBuilderGoTo", self.script)
        self.assertIn("scrollIntoView", self.script)
        self.assertIn("aria-invalid", self.script)
        self.assertIn("path.includes(`.${prefix}.`)", self.script)
        self.assertNotIn("path.includes(prefix)", self.script)
        self.assertIn("'Review & calculate'", self.script)
        self.assertIn('role="status" aria-live="polite"', dialog)
        self.assertIn("Calculation blocked —", self.script)
        self.assertNotIn("remaining.slice(0, 3)", self.script)
        self.assertIn(
            ".tea-builder-stage .tea-assumptions-table {", self.html
        )
        self.assertRegex(
            self.html,
            r"\.tea-builder-stage\s*\{[^}]*overflow:\s*visible;",
        )
        self.assertRegex(
            self.html,
            r"\.tea-assumptions-table-region\s*\{[^}]*overflow:\s*clip;",
        )
        self.assertRegex(
            self.script,
            r"if \(event\.target === technoeconomicElements\.calculationContract\) \{\s*"
            r"technoeconomicRenderContractMode\(\);[\s\S]*?"
            r"standaloneAssumptionsDialog\?\.open[\s\S]*?"
            r"technoeconomicBuilderUpdate\(\);",
        )
        self.assertRegex(
            self.styles,
            r"\.tea-builder-summary-sticky\s*\{[^}]*position:\s*sticky;",
        )
        self.assertRegex(
            self.styles,
            r"\.tea-assumptions-dialog :is\([^}]*focus-visible",
        )
        self.assertIn(".tea-assumptions-table > thead", self.styles)
        self.assertNotIn(".tea-assumptions-table thead", self.styles)

    @unittest.skipUnless(shutil.which("node"), "Node.js is required")
    def test_scenario_builder_routes_evidence_and_distribution_issues(self) -> None:
        payload = self.run_node(
            r"""
const assert = require('node:assert/strict');
const accept = {id: 'accept'};
const note = {id: 'note'};
const discountValue = {id: 'discount-value'};
const degradationValue = {id: 'degradation-value'};
const fieldContainer = (field) => ({
  querySelector(selector) {
    return selector === '[data-tea-v4-param="value"]' ? field : null;
  },
});
technoeconomicElements = {
  calculationContract: {value: TECHNOECONOMIC_PAIRED_CONTRACT_VERSION},
  standaloneAccept: accept,
  standaloneAssumptionNote: note,
  standaloneDiscountFamily: {id: 'discount-family'},
  standaloneDegradationFamily: {id: 'degradation-family'},
  standaloneDiscountParameters: fieldContainer(discountValue),
  standaloneDegradationParameters: fieldContainer(degradationValue),
};
for (const path of [
  'evidence.explicit_acceptance',
  'finance.real_discount_rate.evidence.explicit_acceptance',
  'shared_degradation.annual_rate.evidence.explicit_acceptance',
]) {
  const target = technoeconomicBuilderIssueTarget({path});
  assert.equal(target.section, 'review');
  assert.equal(target.element, accept);
}
for (const path of [
  'evidence.assumption_note',
  'finance.real_discount_rate.evidence.acceptance_rationale',
  'finance.real_discount_rate.evidence.citation.excerpt_or_derivation_note',
  'shared_degradation.annual_rate.evidence.citation.stable_reference',
]) {
  const target = technoeconomicBuilderIssueTarget({path});
  assert.equal(target.section, 'review');
  assert.equal(target.element, note);
}
assert.equal(technoeconomicBuilderIssueTarget({
  path: 'finance.real_discount_rate.distribution.value',
}).element, discountValue);
assert.equal(technoeconomicBuilderIssueTarget({
  path: 'shared_degradation.annual_rate.distribution.value',
}).element, degradationValue);
console.log(JSON.stringify({ok: true}));
"""
        )
        self.assertTrue(payload["ok"])

    def test_table_first_assumptions_are_accessible_shared_and_editable(self) -> None:
        dialog = self.markup.split(
            '<dialog class="tea-assumptions-dialog" id="technoeconomicAssumptionsDialog"',
            1,
        )[1].split("</dialog>", 1)[0]

        self.assertEqual(1, dialog.count('class="tea-assumptions-table"'))
        self.assertIn(
            "<caption>Editable shared and paired assumptions for the probabilistic "
            "technoeconomic analysis.</caption>",
            dialog,
        )
        primary_header = dialog.split("<thead>", 1)[1].split("</thead>", 1)[0]
        self.assertEqual(5, primary_header.count('scope="col"'))
        self.assertEqual(5, dialog.count('scope="rowgroup"'))
        for heading in (
            "Assumption",
            "Distribution",
            "Solectria",
            "SolarEdge",
            "Unit / status",
        ):
            self.assertRegex(
                primary_header,
                rf'<th[^>]*scope="col"[^>]*>{re.escape(heading)}</th>',
            )

        self.assertIn('id="technoeconomicFormulaRegistryBody"', dialog)
        self.assertIn("/api/technoeconomic/formulas/v6", self.script)
        self.assertIn("formula_registry_sha256", self.script)

        self.assertEqual(
            1, dialog.count('id="technoeconomicStandaloneSourceSelect"')
        )
        self.assertIn("Previous Annual Simulation source", dialog)
        self.assertIn(
            "One completed, verified run supplies paired energy and capacity for both systems.",
            dialog,
        )
        self.assertIn(
            "Only currently eligible runs are listed and each selection is "
            "re-verified when the job is queued.",
            dialog,
        )
        self.assertIn('class="tea-assumption-cost-distribution-cell"', dialog)
        for distribution_guide_copy in (
            "Choose each distribution in its Solectria or SolarEdge column.",
            "Initial installed cost",
            "Annual operations and maintenance",
            "Scheduled replacement",
        ):
            self.assertIn(distribution_guide_copy, dialog)
        self.assertEqual(
            1, dialog.count('id="technoeconomicStandaloneSolectriaCostLines"')
        )
        self.assertEqual(
            1, dialog.count('id="technoeconomicStandaloneSolarEdgeCostLines"')
        )

        self.assertRegex(
            self.styles,
            r"\.tea-standalone-assumptions-body\s*\{[^}]*overflow:\s*auto;",
        )
        self.assertRegex(
            self.styles,
            r"\.tea-assumptions-table-region\s*\{[^}]*overflow:\s*visible;",
        )
        self.assertRegex(
            self.styles,
            r"\.tea-assumptions-table > thead th\s*\{[^}]*position:\s*sticky;"
            r"[^}]*top:\s*0;",
        )

        editable_control_ids = (
            "technoeconomicStandaloneSourceSelect",
            "technoeconomicStandaloneTargetCapacityInput",
            "technoeconomicStandaloneRealizations",
            "technoeconomicCalculationContract",
            "technoeconomicLifecycleJson",
            "technoeconomicStandaloneSeed",
            "technoeconomicStandaloneProjectLife",
            "technoeconomicStandaloneDiscountFamily",
            "technoeconomicStandaloneDegradationFamily",
            "technoeconomicStandaloneSolectriaReplacementEnabled",
            "technoeconomicStandaloneSolarEdgeReplacementEnabled",
            "technoeconomicStandaloneAssumptionNote",
            "technoeconomicStandaloneAccept",
        )
        for control_id in editable_control_ids:
            tag = re.search(
                rf'<(?:input|select|textarea)\b[^>]*\bid="{control_id}"[^>]*>',
                dialog,
            )
            self.assertIsNotNone(tag, control_id)
            self.assertNotRegex(tag.group(0), r"\b(?:disabled|readonly)\b")

        locked_year = re.search(
            r'<input\b[^>]*\bid="technoeconomicStandaloneCostYear"[^>]*>',
            dialog,
        )
        self.assertIsNotNone(locked_year)
        self.assertRegex(locked_year.group(0), r"\breadonly\b")
        self.assertEqual(1, len(re.findall(r"\breadonly\b", dialog)))

        cost_factory = self.script.split(
            "function technoeconomicStandaloneCreateCostLine", 1
        )[1].split("function technoeconomicStandaloneCostDefinitions", 1)[0]
        self.assertNotRegex(cost_factory, r"\b(?:disabled|readonly):\s*true\b")
        parameter_factory = self.script.split(
            "function technoeconomicStandaloneRenderDistributionParameters", 1
        )[1].split("function technoeconomicStandaloneNrelEvidence", 1)[0]
        self.assertIn("type: 'number'", parameter_factory)
        self.assertIn("input.dataset.teaV4Param = key", parameter_factory)
        self.assertNotRegex(
            parameter_factory, r"\b(?:disabled|readonly):\s*true\b"
        )

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

    def test_option_two_standalone_workspace_is_results_first_and_source_backed(self) -> None:
        standalone = self.markup.split(
            '<form class="tea-form tea-standalone-workspace"', 1
        )[1].split('class="tea-panel tea-core-panel tea-legacy-v3-workspace"', 1)[0]
        for marker in (
            'id="technoeconomicCalculationBridge"',
            'Calculation bridge',
            'id="technoeconomicStandaloneResults"',
            'id="technoeconomicScenarioInputs"',
            'id="technoeconomicEditAssumptionsBtn"',
            'id="technoeconomicStandaloneSubmitBtn"',
            'id="technoeconomicStandaloneSourceSelect"',
            'id="technoeconomicStandaloneTargetCapacityInput"',
            'id="technoeconomicCalculationContract"',
            'value="tea-calculation-v6" selected',
            'id="technoeconomicLifecycleJson"',
            'id="technoeconomicUseLifecycleTemplateBtn"',
            'Use approved template values',
            'Versioned provisional planning template',
            'These are not approved vendor inputs.',
            'Advanced methodology &amp; lifecycle data',
            'Calculation methodology (advanced)',
            'Generic 100-kW power-electronics equivalent',
            'Generic 1-MW balance-of-system equivalent',
            'Restock to target yearly',
            'No scheduled costs or preventive replacements are included',
            'id="technoeconomicStandaloneDiscountParameters"',
            'id="technoeconomicStandaloneDegradationParameters"',
            'id="technoeconomicStandaloneSolectriaCostLines"',
            'id="technoeconomicStandaloneSolarEdgeCostLines"',
            'id="technoeconomicStandaloneSolectriaReplacementEnabled"',
            'id="technoeconomicStandaloneSolarEdgeReplacementEnabled"',
            'NREL 2024 ATB utility-scale PV benchmark preset',
            'Preset (real 2022 USD)',
            '$1.56/Wac',
            '$22/kWac-year',
            '$1.17/Wdc',
            '$16.58/kWdc-year',
            'https://data.openei.org/submissions/6006',
            'not a vendor quote',
            'not a validated forecast',
            'Not included until a sourced line is added',
            'The same generic benchmark starts both systems.',
            'id="technoeconomicStandaloneCostYear" type="number" value="2022"',
            'readonly',
            'no currency conversion is applied',
            'id="technoeconomicStandaloneCsvLink"',
            'id="technoeconomicStandaloneXlsxLink"',
            'id="technoeconomicStandaloneProvenance"',
        ):
            self.assertIn(marker, standalone)

        advanced = re.search(
            r'<details\b(?P<open>[^>]*)id="technoeconomicLifecycleAdvancedDetails"'
            r'(?P<body>.*?)</details>',
            standalone,
            re.DOTALL,
        )
        self.assertIsNotNone(advanced)
        self.assertNotRegex(advanced.group("open"), r"\bopen\b")
        lifecycle_textarea = re.search(
            r'<textarea\b[^>]*id="technoeconomicLifecycleJson"[^>]*>',
            advanced.group("body"),
        )
        self.assertIsNotNone(lifecycle_textarea)
        self.assertNotRegex(lifecycle_textarea.group(0), r"\brequired\b")
        self.assertLess(
            standalone.index('id="technoeconomicUseLifecycleTemplateBtn"'),
            standalone.index('id="technoeconomicLifecycleAdvancedDetails"'),
        )
        self.assertIn("Reset to approved template values", self.script)

        self.assertLess(
            standalone.index('id="technoeconomicStandaloneResults"'),
            standalone.index('id="technoeconomicAssumptionsDialog"'),
        )
        self.assertNotIn("125 kW", standalone)
        self.assertNotIn("125000", standalone)
        self.assertNotIn("139180.8", standalone)
        self.assertNotRegex(standalone.lower(), r"\bcentral\b")
        self.assertGreaterEqual(self.markup.count("tea-legacy-v3-workspace"), 3)
        legacy_panels = re.findall(
            r'<section\b[^>]*class="[^"]*tea-legacy-v3-workspace[^"]*"[^>]*>',
            self.markup,
        )
        self.assertEqual(3, len(legacy_panels))
        for panel in legacy_panels:
            self.assertRegex(panel, r"\bhidden\b")
            self.assertRegex(panel, r"\binert\b")
        standalone_results = re.search(
            r'<section\b[^>]*id="technoeconomicStandaloneResults"[^>]*>',
            self.markup,
        )
        self.assertIsNotNone(standalone_results)
        self.assertNotRegex(standalone_results.group(0), r"\bhidden\b")

    @unittest.skipUnless(shutil.which("node"), "Node.js is required")
    def test_standalone_entry_mode_keeps_every_legacy_input_panel_hidden(self) -> None:
        payload = self.run_node(
            r"""
const assert = require('node:assert/strict');
function legacyPanel() {
  return {
    hidden: false,
    inert: false,
    setAttribute(name) { if (name === 'inert') this.inert = true; },
  };
}
const sourcePanel = legacyPanel();
const guidedPanel = legacyPanel();
const submitPanel = legacyPanel();
globalThis.document = {
  querySelectorAll(selector) {
    assert.equal(selector, '.tea-legacy-v3-workspace');
    return [sourcePanel, guidedPanel, submitPanel];
  },
};
globalThis.technoeconomicElements = {
  standaloneResults: {hidden: false},
  guidedPanel,
  advancedDetails: {hidden: false, open: true},
  entryModeRow: {hidden: false},
  submitPanel,
  useGuidedButton: {hidden: false},
  entryModeStatus: {textContent: ''},
};

technoeconomicEntryMode = TECHNOECONOMIC_GUIDED_ENTRY_MODE;
technoeconomicRenderEntryMode();
assert.equal(technoeconomicElements.standaloneResults.hidden, false);
for (const panel of [sourcePanel, guidedPanel, submitPanel]) {
  assert.equal(panel.hidden, true);
  assert.equal(panel.inert, true);
}

technoeconomicEntryMode = TECHNOECONOMIC_ADVANCED_ENTRY_MODE;
technoeconomicRenderEntryMode();
for (const panel of [sourcePanel, guidedPanel, submitPanel]) {
  assert.equal(panel.hidden, true);
  assert.equal(panel.inert, true);
}

console.log(JSON.stringify({
  standaloneVisible: !technoeconomicElements.standaloneResults.hidden,
  legacyHidden: [sourcePanel, guidedPanel, submitPanel].every((panel) => panel.hidden),
  legacyInert: [sourcePanel, guidedPanel, submitPanel].every((panel) => panel.inert),
}));
"""
        )
        self.assertTrue(payload["standaloneVisible"])
        self.assertTrue(payload["legacyHidden"])
        self.assertTrue(payload["legacyInert"])

    def test_option_two_layout_has_responsive_and_forced_color_fallbacks(self) -> None:
        for marker in (
            ".tea-bridge-steps",
            ".tea-standalone-primary",
            ".tea-standalone-percentile-table",
            '.tea-standalone-primary[data-presentation="lifecycle"]',
            ".tea-table.tea-v6-decision-table",
            "content: attr(data-label);",
            ".tea-paired-system-cost-grid",
            ".tea-assumptions-table",
            "@media (max-width: 1080px)",
            "@media (max-width: 900px)",
            "@media (max-width: 760px)",
            "@media (max-width: 560px)",
            "@media (forced-colors: active)",
        ):
            self.assertIn(marker, self.styles)
        option_two = self.styles.split(".tea-standalone-workspace", 1)[1]
        self.assertRegex(
            option_two,
            r"\.tea-standalone-primary\s*\{[^}]*order:\s*2;",
        )
        self.assertRegex(
            option_two,
            r"\.tea-job-panel\s*\{[^}]*order:\s*3;",
        )

    def test_calculation_bridge_keeps_each_system_in_its_own_column(self) -> None:
        bridge = self.markup.split(
            'id="technoeconomicCalculationBridge"', 1
        )[1].split('class="tea-bridge-footer"', 1)[0]

        self.assertEqual(6, bridge.count('class="tea-bridge-system-column"'))
        self.assertNotIn("tea-bridge-system-values", bridge)
        for marker in (
            'id="technoeconomicStandaloneSolectriaSourceCapacity"',
            'id="technoeconomicStandaloneSolarEdgeSourceCapacity"',
            'id="technoeconomicStandaloneSolectriaSpecificEnergy"',
            'id="technoeconomicStandaloneSolarEdgeSpecificEnergy"',
            'id="technoeconomicStandaloneSolectriaTargetEnergy"',
            'id="technoeconomicStandaloneSolarEdgeTargetEnergy"',
        ):
            self.assertIn(marker, bridge)

        for marker in (
            "grid-template-columns: repeat(2, minmax(0, 1fr));",
            ".tea-bridge-system-column dd",
            "overflow-wrap: anywhere;",
            "minmax(0, 1.55fr)",
            "minmax(0, 0.85fr)",
            ".tea-bridge-card:last-child",
        ):
            self.assertIn(marker, self.styles)

    def test_option_two_density_adjustment_is_scoped_to_tea_mode(self) -> None:
        for marker in (
            "body.dashboard-mode-technoeconomic .workspace",
            "body.dashboard-mode-technoeconomic .top-nav",
            "body.dashboard-mode-technoeconomic .header-copy",
            "body.dashboard-mode-technoeconomic .header-title",
            "body.dashboard-mode-technoeconomic .mode-tabs",
            "body.dashboard-mode-technoeconomic .mode-tab",
            "body.dashboard-mode-technoeconomic .controls-bar.tea-workspace",
            ".tea-calculation-bridge > .tea-section-heading",
        ):
            self.assertIn(marker, self.styles)
        self.assertIn(
            '<p class="tea-step-label" hidden>Calculation bridge</p>', self.markup
        )

    @unittest.skipUnless(shutil.which("node"), "Node.js is required")
    def test_standalone_capacity_authority_is_dynamic_and_preserves_rating_basis(self) -> None:
        payload = self.run_node(
            r"""
const assert = require('node:assert/strict');
const appliedAc = technoeconomicStandaloneSourceCapacityInfo({
  applied_capacity: {solaredge: {
    applied_capacity_w: 127500, rating_basis: 'ac_operating_limit',
  }},
  solaredge_installed_wdc: 142321,
});
assert.deepEqual(appliedAc, {
  watts: 127500, ratingBasis: 'ac_operating_limit', source: 'verified_applied_capacity',
});
const solectriaApplied = technoeconomicStandaloneSourceCapacityInfo({
  applied_capacity: {solectria: {
    applied_capacity_w: 126000, rating_basis: 'ac_operating_limit',
  }},
  solectria_installed_wdc: 139181,
}, 'solectria');
assert.deepEqual(solectriaApplied, {
  watts: 126000, ratingBasis: 'ac_operating_limit', source: 'verified_applied_capacity',
});
const appliedDc = technoeconomicStandaloneSourceCapacityInfo({
  applied_capacity: {solaredge: {
    applied_capacity_w: 142321, rating_basis: 'dc_installed_nameplate',
  }},
});
assert.deepEqual(appliedDc, {
  watts: 142321, ratingBasis: 'dc_installed_nameplate', source: 'verified_applied_capacity',
});
const limitFallback = technoeconomicStandaloneSourceCapacityInfo({
  provenance: {operating_limit: {
    curtailment_enabled: true, curtailment_limit_kw: 113.75,
  }},
  solaredge_installed_wdc: 142321,
});
assert.deepEqual(limitFallback, {
  watts: 113750, ratingBasis: 'ac_operating_limit', source: 'verified_operating_limit',
});
const nameplateFallback = technoeconomicStandaloneSourceCapacityInfo({
  provenance: {operating_limit: {
    curtailment_enabled: false, curtailment_limit_kw: 113.75,
  }},
  solaredge_installed_wdc: 142321,
});
assert.deepEqual(nameplateFallback, {
  watts: 142321, ratingBasis: 'dc_installed_nameplate', source: 'verified_installed_nameplate',
});
const solectriaNameplate = technoeconomicStandaloneSourceCapacityInfo({
  provenance: {operating_limit: {curtailment_enabled: false}},
  solectria_installed_wdc: 139181,
}, 'solectria');
assert.deepEqual(solectriaNameplate, {
  watts: 139181, ratingBasis: 'dc_installed_nameplate', source: 'verified_installed_nameplate',
});
console.log(JSON.stringify({
  ac: appliedAc.watts, dc: appliedDc.watts,
  solectriaAc: solectriaApplied.watts, solectriaDc: solectriaNameplate.watts,
  fallbackAc: limitFallback.watts, fallbackDc: nameplateFallback.watts,
}));
"""
        )
        self.assertEqual(127500, payload["ac"])
        self.assertEqual(142321, payload["dc"])
        self.assertEqual(126000, payload["solectriaAc"])
        self.assertEqual(139181, payload["solectriaDc"])
        self.assertEqual(113750, payload["fallbackAc"])
        self.assertEqual(142321, payload["fallbackDc"])

    @unittest.skipUnless(shutil.which("node"), "Node.js is required")
    def test_untouched_atb_cost_preset_serializes_a_valid_paired_v5_after_one_acceptance(self) -> None:
        payload = self.run_node(
            r"""
const assert = require('node:assert/strict');
const control = (value, checked = false) => ({value, checked});
const parameters = (values) => ({
  querySelectorAll(selector) {
    assert.equal(selector, '[data-tea-v4-param]');
    return Object.entries(values).map(([key, value]) => ({
      dataset: {teaV4Param: key}, value,
    }));
  },
});
function costCard({system, key, inputId, label, timing, unit, value}) {
  const family = control('fixed');
  const params = parameters({value});
  return {
    dataset: {teaV4System: system, teaV4CostLine: key, inputId, timing, unit},
    querySelector(selector) {
      if (selector === 'h5') return {textContent: label};
      if (selector === '[data-tea-v4-family]') return family;
      return null;
    },
    querySelectorAll: params.querySelectorAll,
  };
}
const systemCards = (system) => [
  costCard({
    system, key: 'Capex', inputId: `commercial.${system}.atb-capex`,
    label: 'Initial installed cost', timing: 'initial_t0',
    unit: 'constant_usd_per_target_w', value: '1.56',
  }),
  costCard({
    system, key: 'Om', inputId: `commercial.${system}.atb-om`,
    label: 'Annual operations and maintenance', timing: 'annual_year_end',
    unit: 'constant_usd_per_target_w_year', value: '22',
  }),
];
const cards = {solectria: systemCards('solectria'), solaredge: systemCards('solaredge')};
const replacements = Object.fromEntries(['solectria', 'solaredge'].map((system) => [
  system,
  costCard({
    system, key: 'Replacement', inputId: `commercial.${system}.scheduled-replacement`,
    label: 'Scheduled replacement', timing: 'scheduled_year_end',
    unit: 'constant_usd_per_target_w', value: '0.20',
  }),
]));
globalThis.document = {
  getElementById(id) {
    return id === 'technoeconomicStandaloneSolectriaReplacementYears'
      || id === 'technoeconomicStandaloneSolarEdgeReplacementYears'
      ? control('15') : null;
  },
};
technoeconomicElements = {
  standaloneSourceSelect: control('annual-v5-fixture'),
  standaloneTargetCapacityInput: control('100'),
  standaloneRealizations: control('10000'),
  standaloneSeed: control('42'),
  standaloneCostYear: control('2035'),
  standaloneProjectLife: control('30'),
  standaloneAccept: control('', true),
  standaloneAssumptionNote: control(
    'Reviewed the ATB benchmark limitations and approved a 5% real discount rate and 0.5% degradation assumption.'
  ),
  standaloneDiscountFamily: control('fixed'),
  standaloneDiscountParameters: parameters({value: '5'}),
  standaloneDegradationFamily: control('fixed'),
  standaloneDegradationParameters: parameters({value: '0.5'}),
  standaloneSolectriaCostLines: {querySelectorAll: () => cards.solectria},
  standaloneSolarEdgeCostLines: {querySelectorAll: () => cards.solaredge},
  standaloneSolectriaReplacementEnabled: control('', false),
  standaloneSolarEdgeReplacementEnabled: control('', false),
  standaloneSolectriaReplacementFields: {
    querySelectorAll: () => [replacements.solectria],
  },
  standaloneSolarEdgeReplacementFields: {
    querySelectorAll: () => [replacements.solaredge],
  },
};
const sources = [{
  source_annual_job_id: 'annual-v5-fixture', eligible: true,
  applied_capacity: {
    solectria: {applied_capacity_w: 127500, rating_basis: 'ac_operating_limit'},
    solaredge: {applied_capacity_w: 127500, rating_basis: 'ac_operating_limit'},
  },
}];
const serialized = technoeconomicSerializeStandaloneRequest({sources});
assert.equal(serialized.valid, true, JSON.stringify(serialized.errors));
assert.deepEqual(serialized.errors, []);
assert.equal(serialized.payload.basis, 'solartac_site');
assert.equal(serialized.payload.capacity_normalization, 'annual_applied_capacity_v1');
assert.equal(serialized.payload.finance.constant_dollar_cost_year, 2022);
assert.equal(technoeconomicElements.standaloneCostYear.value, '2022');
assert.deepEqual(serialized.payload.cost_lines, []);
assert.equal(Object.hasOwn(serialized.payload, 'commercial_scaling'), false);
assert.equal(Object.hasOwn(serialized.payload, 'commercial_reference_design'), false);
assert.equal(Object.hasOwn(serialized.payload, 'commercial_transfer'), false);
const paired = serialized.payload.paired_commercial;
assert.equal(Object.hasOwn(serialized.payload, 'standalone_commercial'), false);
assert.equal(paired.target_capacity, 100);
assert.equal(paired.target_capacity_unit, 'mw');
assert.equal(paired.target_rating_basis, 'ac_operating_limit');
assert.equal(paired.transfer_method, 'direct_capacity_scaling');
assert.deepEqual(paired.systems.map((system) => system.technology), [
  'solectria', 'solaredge',
]);
for (const system of paired.systems) {
  assert.equal(system.cost_lines.length, 2);
  assert.deepEqual(system.cost_lines.map((line) => line.distribution), [
    {family: 'fixed', value: 1.56}, {family: 'fixed', value: 0.022},
  ]);
  assert.deepEqual(system.cost_lines.map((line) => line.unit), [
    'constant_usd_per_target_w', 'constant_usd_per_target_w_year',
  ]);
  assert.deepEqual(system.cost_lines.map((line) => line.cost_category), [
    'full_initial_capex', 'full_annual_om',
  ]);
  assert.deepEqual(system.cost_lines.map((line) => line.coverage_ids), [
    [`commercial.${system.technology}.full-initial-system`],
    [`commercial.${system.technology}.full-annual-operations-maintenance`],
  ]);
  assert.deepEqual(system.cost_lines.map((line) => line.constant_dollar_cost_year), [
    2022, 2022,
  ]);
  assert.equal(system.evidence.explicit_acceptance, true);
}
assert.equal(paired.evidence.explicit_acceptance, true);
assert.deepEqual(TECHNOECONOMIC_STANDALONE_COST_COVERAGE.solaredge.Replacement, {
  costCategory: 'scheduled_replacement',
  coverageIds: ['commercial.solaredge.inverter-replacement'],
});
assert.deepEqual(TECHNOECONOMIC_STANDALONE_COST_COVERAGE.solectria.Replacement, {
  costCategory: 'scheduled_replacement',
  coverageIds: ['commercial.solectria.inverter-replacement'],
});
const nrelEvidence = [
  serialized.payload.finance.project_life_evidence,
  ...paired.systems.flatMap((system) => system.cost_lines.map((line) => line.evidence)),
];
for (const evidence of nrelEvidence) {
  assert.equal(evidence.evidence_class, 'public_market_proxy_or_benchmark');
  assert.equal(evidence.citation.organization, 'National Renewable Energy Laboratory');
  assert.equal(evidence.citation.url,
    'https://data.openei.org/submissions/6006');
  assert.equal(evidence.citation.stable_reference, 'doi:10.25984/2377191');
  assert.equal(evidence.citation.publication_or_as_of_date, '2024-06-24');
  assert.equal(evidence.explicit_acceptance, true);
  assert.ok(evidence.acceptance_rationale.includes('Reviewed the ATB benchmark'));
}
assert.equal(serialized.payload.finance.real_discount_rate.distribution.value, 0.05);
assert.equal(serialized.payload.shared_degradation.annual_rate.distribution.value, 0.005);
technoeconomicElements.standaloneSolectriaReplacementEnabled.checked = true;
const withReplacement = technoeconomicSerializeStandaloneRequest({sources});
assert.equal(withReplacement.valid, true, JSON.stringify(withReplacement.errors));
const scheduled = withReplacement.payload.paired_commercial.systems[0].cost_lines[2];
assert.equal(scheduled.cost_category, 'scheduled_replacement');
assert.deepEqual(scheduled.coverage_ids, ['commercial.solectria.inverter-replacement']);
assert.equal(scheduled.constant_dollar_cost_year, 2022);
assert.deepEqual(scheduled.occurrence_years, [15]);
console.log(JSON.stringify({
  valid: serialized.valid, evidence: serialized.evidenceCount,
  ratingBasis: paired.target_rating_basis,
  costValues: paired.systems[0].cost_lines.map((line) => line.distribution.value),
  request: serialized.payload,
  replacementRequest: withReplacement.payload,
}));
"""
        )
        from sbepv.api.schemas import TechnoeconomicSubmissionRequest

        validated = TechnoeconomicSubmissionRequest.model_validate(payload["request"])
        replacement_validated = TechnoeconomicSubmissionRequest.model_validate(
            payload["replacementRequest"]
        )
        self.assertTrue(payload["valid"])
        self.assertEqual("ac_operating_limit", payload["ratingBasis"])
        self.assertEqual([1.56, 0.022], payload["costValues"])
        self.assertGreaterEqual(payload["evidence"], 6)
        self.assertIsNotNone(validated.paired_commercial)
        self.assertEqual([], validated.cost_lines)
        self.assertEqual(
            "scheduled_replacement",
            replacement_validated.paired_commercial.systems[0].cost_lines[2].cost_category,
        )

    @unittest.skipUnless(shutil.which("node"), "Node.js is required")
    def test_paired_om_display_units_convert_every_distribution_value(self) -> None:
        payload = self.run_node(
            r"""
const assert = require('node:assert/strict');
const om = (distribution) => technoeconomicStandaloneKernelCostDistribution({
  timing: 'annual_year_end', unit: 'constant_usd_per_target_w_year', distribution,
});
assert.deepEqual(om({family: 'fixed', value: '22'}), {
  family: 'fixed', value: '0.022',
});
assert.deepEqual(om({family: 'uniform', low: '10', high: '30'}), {
  family: 'uniform', low: '0.01', high: '0.03',
});
assert.deepEqual(om({family: 'triangular', low: '12', mode: '22', high: '32'}), {
  family: 'triangular', low: '0.012', mode: '0.022', high: '0.032',
});
assert.deepEqual(om({
  family: 'bounded_normal', low: '5', mean: '22', high: '45', sd: '6',
}), {
  family: 'bounded_normal', low: '0.005', mean: '0.022', high: '0.045', sd: '0.006',
});
const capex = {family: 'fixed', value: '1.56'};
assert.deepEqual(technoeconomicStandaloneKernelCostDistribution({
  timing: 'initial_t0', unit: 'constant_usd_per_target_w', distribution: capex,
}), capex);
console.log(JSON.stringify({
  acPreset: TECHNOECONOMIC_STANDALONE_ATB_PRESETS.ac_operating_limit,
  dcPreset: TECHNOECONOMIC_STANDALONE_ATB_PRESETS.dc_installed_nameplate,
  bounded: om({family: 'bounded_normal', low: '5', mean: '22', high: '45', sd: '6'}),
}));
"""
        )
        self.assertEqual({"capex": "1.56", "om": "22"}, payload["acPreset"])
        self.assertEqual({"capex": "1.17", "om": "16.58"}, payload["dcPreset"])
        self.assertEqual("0.022", payload["bounded"]["mean"])

    @unittest.skipUnless(shutil.which("node"), "Node.js is required")
    def test_dashboard_submits_v6_explicitly_and_keeps_v5_compatibility(self) -> None:
        payload = self.run_node(
            r"""
const assert = require('node:assert/strict');
const provisionalEvidence = {
  evidence_class: 'engineering_judgment',
  citation: {title: 'User lifecycle basis', stable_reference: 'project-note-1'},
  explicit_acceptance: true,
  acceptance_rationale: 'This stale JSON acceptance must not be trusted.',
};
const lifecycle = {
  source_energy_basis: 'gross', reliability_mode: 'event',
  decision_npv_tolerance_usd_per_target_w: 0.01,
  electricity_value: {}, electricity_value_real_growth: {},
  systems: [
    {technology: 'solectria', evidence: provisionalEvidence,
      components: [{component_id: 'so-a'}]},
    {technology: 'solaredge', components: [{component_id: 'se-a'}]},
  ],
  common_cause_events: [],
};
const basePayload = {
  shared_degradation: {annual_rate: {}},
  paired_commercial: {
    systems: [
      {technology: 'solectria', cost_lines: [{input_id: 'legacy-so'}]},
      {technology: 'solaredge', cost_lines: [{input_id: 'legacy-se'}]},
    ],
  },
};
technoeconomicSerializeStandaloneRequest = () => ({
  payload: basePayload,
  errors: [
    {path: 'shared_degradation.annual_rate.distribution.value', message: 'legacy only'},
    {path: 'paired_commercial.systems.0.cost_lines', message: 'legacy only'},
  ],
  valid: false, evidenceCount: 0,
  provisionalEvidenceCount: 0, nonfixedPredictorCount: 0,
});
technoeconomicElements = {
  calculationContract: {value: TECHNOECONOMIC_LIFECYCLE_CONTRACT_VERSION},
  lifecycleJson: {value: JSON.stringify(lifecycle)},
  standaloneAccept: {checked: true},
  standaloneAssumptionNote: {value: 'Accepted for this specific submitted run.'},
};
const v6 = technoeconomicSerializeCurrentRequest();
assert.equal(v6.valid, true, JSON.stringify(v6.errors));
assert.deepEqual(v6.errors, []);
assert.equal(v6.provisionalEvidenceCount, 1);
assert.equal(v6.payload.calculation_contract_version, 'tea-calculation-v6');
assert.equal(Object.hasOwn(v6.payload, 'shared_degradation'), false);
assert.equal(v6.payload.paired_commercial.lifecycle.weather_path_method,
  TECHNOECONOMIC_LIFECYCLE_WEATHER_METHOD);
assert.equal(v6.payload.paired_commercial.lifecycle.decision_probability_threshold, 0.75);
assert.equal(v6.payload.paired_commercial.lifecycle.systems[0]
  .evidence.explicit_acceptance, true);
assert.equal(v6.payload.paired_commercial.lifecycle.systems[0]
  .evidence.acceptance_rationale, 'Accepted for this specific submitted run.');
assert.deepEqual(v6.payload.paired_commercial.systems.map((system) => system.cost_lines),
  [[], []]);
technoeconomicElements.calculationContract.value = TECHNOECONOMIC_PAIRED_CONTRACT_VERSION;
const v5 = technoeconomicSerializeCurrentRequest();
assert.equal(Object.hasOwn(v5.payload, 'calculation_contract_version'), false);
assert.equal(Object.hasOwn(v5.payload, 'shared_degradation'), true);
console.log(JSON.stringify({
  v6Version: v6.payload.calculation_contract_version,
  weather: v6.payload.paired_commercial.lifecycle.weather_path_method,
  v5VersionPresent: Object.hasOwn(v5.payload, 'calculation_contract_version'),
}));
"""
        )
        self.assertEqual("tea-calculation-v6", payload["v6Version"])
        self.assertFalse(payload["v5VersionPresent"])

    @unittest.skipUnless(shutil.which("node"), "Node.js is required")
    def test_v6_guided_template_builds_internal_contract_and_rejects_blanks(self) -> None:
        payload = self.run_node(
            r"""
const assert = require('node:assert/strict');
function control(value = '') {
  return {
    value, disabled: false, validationMessage: '',
    setCustomValidity(message) { this.validationMessage = message; },
  };
}
function textNode() { return {textContent: ''}; }
const discountValue = control('5');
discountValue.dataset = {teaV4Param: 'value'};
const discountParameters = {
  querySelectorAll(selector) {
    return selector === '[data-tea-v4-param]' ? [discountValue] : [];
  },
};
const fields = Object.fromEntries(Object.entries(
  TECHNOECONOMIC_LIFECYCLE_TEMPLATE_DEFAULTS
).map(([key, value]) => [key, control(value)]));
Object.assign(fields, {
  standaloneTargetCapacityInput: control('100'),
  standaloneSourceSelect: control('annual-dc'),
  standaloneDiscountFamily: control('fixed'),
  standaloneDiscountParameters: discountParameters,
  lifecycleJson: control(''),
  lifecycleTemplateStatusPanel: {dataset: {}},
  lifecycleTemplateStatus: textNode(), lifecycleTemplateStatusDetail: textNode(),
  useLifecycleTemplateButton: textNode(),
  lifecycleComponentACount: textNode(), lifecycleComponentBCount: textNode(),
  lifecycleComponentAImpact: textNode(), lifecycleComponentBImpact: textNode(),
  lifecycleComponentASpares: textNode(), lifecycleComponentBSpares: textNode(),
  lifecycleScalingNote: textNode(), lifecycleInitialCostUnit: textNode(),
  lifecycleBaseOmUnit: textNode(),
});
technoeconomicElements = fields;
technoeconomicSources = [{
  source_annual_job_id: 'annual-dc',
  applied_capacity: {
    solectria: {applied_capacity_w: 125000, rating_basis: 'dc_installed_nameplate'},
    solaredge: {applied_capacity_w: 125000, rating_basis: 'dc_installed_nameplate'},
  },
}];
technoeconomicResetLifecycleTemplateFields();
assert.equal(fields.lifecycleSolectriaInitialCost.value, '1.17');
assert.equal(fields.lifecycleSolarEdgeBaseOm.value, '16.58');
assert.equal(fields.lifecycleInitialCostUnit.textContent, 'real 2022 USD/Wdc');
assert.equal(technoeconomicSyncLifecycleTemplate(), true);
assert.equal(fields.useLifecycleTemplateButton.textContent,
  'Reset to approved template values');
const lifecycle = JSON.parse(fields.lifecycleJson.value);
assert.equal(lifecycle.source_energy_basis, 'gross');
assert.equal(lifecycle.reliability_mode, 'event');
assert.equal(lifecycle.systems.length, 2);
assert.equal(lifecycle.systems[0].components.length, 2);
assert.equal(lifecycle.systems[0].components[0].count, 1000);
assert.equal(lifecycle.systems[0].components[0].initial_spares, 10);
assert.equal(lifecycle.systems[0].components[0].spare_target, 10);
assert.equal(lifecycle.systems[0].components[0].batch_size, 5);
assert.equal(lifecycle.systems[0].scheduled_costs.length, 0);
assert.equal(lifecycle.systems[0].components[0].preventive_replacements.length, 0);
assert.equal(lifecycle.systems[0].initial_cost_lines[0].cost_per_w
  .evidence.evidence_class, 'public_market_proxy_or_benchmark');
assert.equal(lifecycle.systems[0].degradation.evidence.evidence_class,
  'engineering_judgment');
assert.equal(lifecycle.common_cause_events[0].annual_probability.distribution.value, 0.02);
assert.equal(technoeconomicLifecycleMatchesTemplateShape(lifecycle), true);
const spoofed = JSON.parse(JSON.stringify(lifecycle));
spoofed.systems[0].components[0].component_id = 'vendor-inverter';
assert.equal(technoeconomicLifecycleMatchesTemplateShape(spoofed), false);
const hiddenCostTamper = JSON.parse(JSON.stringify(lifecycle));
hiddenCostTamper.systems[0].components[0]
  .emergency_unit_cost.distribution.value += 1;
assert.equal(technoeconomicLifecycleMatchesTemplateShape(hiddenCostTamper), false);
const thresholdTamper = JSON.parse(JSON.stringify(lifecycle));
thresholdTamper.decision_probability_threshold = 0.5;
assert.equal(technoeconomicLifecycleMatchesTemplateShape(thresholdTamper), false);
fields.lifecycleSolectriaInitialCost.value = '1.23';
fields.lifecycleSolectriaBaseOm.value = '17.50';
assert.equal(technoeconomicSyncLifecycleTemplate(), true);
const edited = JSON.parse(fields.lifecycleJson.value);
assert.equal(edited.systems[0].initial_cost_lines[0].cost_per_w
  .evidence.evidence_class, 'engineering_judgment');
assert.equal(edited.systems[0].base_om_cost_per_w_year
  .evidence.evidence_class, 'engineering_judgment');
assert.equal(technoeconomicLifecycleMatchesTemplateShape(edited), true);
fields.lifecycleCommonCost.value = '';
const blank = technoeconomicBuildLifecycleTemplate();
assert.equal(blank.lifecycle, null);
assert.match(blank.errors[0], /Common-event cost/);
assert.notEqual(fields.lifecycleCommonCost.validationMessage, '');
console.log(JSON.stringify({
  capex: lifecycle.systems[0].initial_cost_lines[0].cost_per_w.distribution.value,
  om: lifecycle.systems[0].base_om_cost_per_w_year.distribution.value,
  componentCount: lifecycle.systems[0].components[0].count,
  editedEvidence: edited.systems[0].initial_cost_lines[0].cost_per_w
    .evidence.evidence_class,
  blankRejected: blank.lifecycle === null,
}));
"""
        )
        self.assertEqual(1.17, payload["capex"])
        self.assertAlmostEqual(0.01658, payload["om"])
        self.assertEqual(1000, payload["componentCount"])
        self.assertEqual("engineering_judgment", payload["editedEvidence"])
        self.assertTrue(payload["blankRejected"])

    @unittest.skipUnless(shutil.which("node"), "Node.js is required")
    def test_commercial_target_scales_from_the_frozen_source(self) -> None:
        payload = self.run_node(
            r"""
const assert = require('node:assert/strict');
const clipped = {
  applied_capacity: {
    solectria: {applied_capacity_w: 125000, rating_basis: 'ac_operating_limit'},
    solaredge: {applied_capacity_w: 125000, rating_basis: 'ac_operating_limit'},
  },
};
const at100 = technoeconomicStandaloneScaleText(clipped, 100000000);
const at75 = technoeconomicStandaloneScaleText(clipped, 75000000);
assert.equal(at100, '125 kWac to 100 MWac (800x)');
assert.equal(at75, '125 kWac to 75 MWac (600x)');
const nameplate = {
  solectria_installed_wdc: 139180.8,
  solaredge_installed_wdc: 139180.8,
};
const fallback = technoeconomicStandaloneScaleText(nameplate, 100000000);
assert.ok(fallback.startsWith('139.1808 kWdc to 100 MWdc'));
console.log(JSON.stringify({at100, at75, fallback}));
"""
        )
        self.assertEqual("125 kWac to 100 MWac (800x)", payload["at100"])
        self.assertEqual("125 kWac to 75 MWac (600x)", payload["at75"])
        self.assertTrue(payload["fallback"].startswith("139.1808 kWdc to 100 MWdc"))

    def test_v4_results_route_by_exact_contract_and_keep_v1_v3_rendering(self) -> None:
        route = self.script.split(
            "function renderTechnoeconomicJobResult", 1
        )[1].split("function technoeconomicRenderJob", 1)[0]
        self.assertIn(
            "contractVersion === TECHNOECONOMIC_STANDALONE_CONTRACT_VERSION",
            route,
        )
        self.assertIn(
            "contractVersion === TECHNOECONOMIC_PAIRED_CONTRACT_VERSION",
            route,
        )
        self.assertIn(
            "contractVersion === TECHNOECONOMIC_LIFECYCLE_CONTRACT_VERSION",
            route,
        )
        self.assertIn("technoeconomicRenderStandaloneResult(job, result)", route)
        self.assertIn("technoeconomicRenderPairedResult(job, result)", route)
        self.assertIn("technoeconomicRenderLifecycleResult(job, result)", route)
        self.assertIn("technoeconomicRenderDecision(result)", route)
        self.assertIn("technoeconomicRenderResultSummary(job, result)", route)
        self.assertNotIn("result.standalone_commercial", route)
        self.assertNotIn("result.commercial_scaling", route)

        renderer = self.script.split(
            "function technoeconomicRenderStandaloneResult", 1
        )[1].split("function technoeconomicClearStandaloneResult", 1)[0]
        for marker in (
            "TECHNOECONOMIC_STANDALONE_LCOE_METRIC",
            "['p10', 'P10', p10]",
            "['p50', 'P50 (median)', p50]",
            "['p90', 'P90', p90]",
            "'cdf_plot'",
            "technoeconomicSafeArtifactUrl",
            "technoeconomicRenderStandaloneScenario(job, result)",
            "safe('csv_bundle')",
            "safe('xlsx_workbook')",
            "standaloneProvenance",
        ):
            self.assertIn(marker, renderer)
        self.assertNotIn("canvas", renderer.lower())

        paired_renderer = self.script.split(
            "function technoeconomicRenderPairedResult", 1
        )[1].split("function technoeconomicClearStandaloneResult", 1)[0]
        for marker in (
            "TECHNOECONOMIC_PAIRED_METRICS",
            "TECHNOECONOMIC_PAIRED_LCOE_DELTA_METRIC",
            "pairedResult.lcoe_delta_se_minus_sol",
            "values.solectria[key]",
            "values.solaredge[key]",
            "technoeconomicRenderStandaloneScenario(job, result)",
            "safe('csv_bundle')",
            "safe('xlsx_workbook')",
        ):
            self.assertIn(marker, paired_renderer)

        for marker in (
            "standaloneCsvLink: document.getElementById('technoeconomicStandaloneCsvLink')",
            "standaloneXlsxLink: document.getElementById('technoeconomicStandaloneXlsxLink')",
            "standaloneProvenance: document.getElementById('technoeconomicStandaloneProvenance')",
        ):
            self.assertIn(marker, self.bindings)

    @unittest.skipUnless(shutil.which("node"), "Node.js is required")
    def test_paired_v5_renderer_reads_exact_nested_worker_result(self) -> None:
        payload = self.run_node(
            r"""
const assert = require('node:assert/strict');
const node = (tag, options = {}) => ({
  tag, textContent: options.text || '', dataset: {}, children: [],
  append(...children) { this.children.push(...children); },
  appendChild(child) { this.children.push(child); },
});
const body = {
  children: [],
  replaceChildren(...children) { this.children = children; },
  appendChild(child) { this.children.push(child); },
};
const resultRoot = {dataset: {}};
const interpretation = {textContent: ''};
technoeconomicNode = node;
technoeconomicElements = {
  standaloneResults: resultRoot,
  standaloneResultStatus: {textContent: ''},
  standaloneInterpretation: interpretation,
  standalonePercentileBody: body,
  standaloneRunContext: {textContent: ''},
  standaloneProvenance: null,
  standaloneCdfPlot: null,
  standaloneCdfFallback: null,
  standaloneCdfLink: null,
  standaloneCsvLink: null,
  standaloneXlsxLink: null,
  standaloneSubmitButton: {textContent: ''},
};
technoeconomicRenderStandaloneScenario = () => {};
technoeconomicRenderStandaloneBridge = () => {};
technoeconomicSetPlot = () => {};
technoeconomicSetDownload = () => {};
technoeconomicSources = [];
const job = {
  job_id: 'tea-paired-v5', source_annual_job_id: 'annual-source', artifacts: {},
  request: {
    n: 1000, source_annual_job_id: 'annual-source',
    finance: {constant_dollar_cost_year: 2022, project_life_years: 30},
  },
};
const result = {
  calculation_contract_version: 'tea-calculation-v5', realization_count: 1000,
  paired_commercial: {
    systems: {
      solectria: {percentiles: {p10: 0.04, p50: 0.05, p90: 0.06}},
      solaredge: {percentiles: {p10: 0.045, p50: 0.055, p90: 0.065}},
    },
    lcoe_delta_se_minus_sol: {percentiles: {p10: 0.004, p50: 0.005, p90: 0.006}},
  },
};
technoeconomicRenderPairedResult(job, result);
assert.equal(resultRoot.dataset.state, 'done');
assert.equal(body.children.length, 3);
assert.deepEqual(body.children[1].children.map((child) => child.textContent), [
  'P50 (median)', '50 USD/MWh', '55 USD/MWh',
]);
assert.ok(interpretation.textContent.includes('Solectria 50 USD/MWh'));
assert.ok(interpretation.textContent.includes('SolarEdge 55 USD/MWh'));
assert.ok(interpretation.textContent.includes('SolarEdge minus Solectria 5 USD/MWh'));
console.log(JSON.stringify({
  state: resultRoot.dataset.state,
  p50: body.children[1].children.map((child) => child.textContent),
}));
"""
        )
        self.assertEqual("done", payload["state"])
        self.assertEqual(
            ["P50 (median)", "50 USD/MWh", "55 USD/MWh"], payload["p50"]
        )

    @unittest.skipUnless(shutil.which("node"), "Node.js is required")
    def test_v6_renderer_prioritizes_upgrade_npv_without_v5_shape(self) -> None:
        payload = self.run_node(
            r"""
const assert = require('node:assert/strict');
const node = (tag, options = {}) => ({
  tag, textContent: options.text || '', dataset: {}, children: [], hidden: false,
  append(...children) { this.children.push(...children); },
  appendChild(child) { this.children.push(child); },
  replaceChildren(...children) { this.children = children; },
});
const container = () => node('div');
const resultRoot = {dataset: {}};
const interpretation = {textContent: ''};
const decisionBody = container();
const probabilities = container();
const provenance = container();
technoeconomicNode = node;
technoeconomicElements = {
  standaloneResults: resultRoot,
  standaloneResultEyebrow: {textContent: ''},
  standaloneResultsHeading: {textContent: ''},
  standaloneResultStatus: {textContent: ''},
  standaloneInterpretation: interpretation,
  legacyPercentilePanel: {hidden: false},
  v6DecisionPanel: {hidden: true},
  v6ProbabilitySummary: probabilities,
  v6PercentileBody: decisionBody,
  standaloneRunContext: {textContent: ''},
  standaloneScenarioSummary: container(),
  standaloneSolectriaCostSummary: container(),
  standaloneSolarEdgeCostSummary: container(),
  standaloneProvenance: provenance,
  standaloneCdfPlot: {alt: ''},
  standaloneCdfCaption: {textContent: ''},
  standaloneCdfFallback: null,
  standaloneCdfLink: null,
  standaloneCsvLink: null,
  standaloneXlsxLink: null,
  standaloneSubmitButton: {textContent: ''},
};
technoeconomicRenderStandaloneBridge = () => {};
let renderedPlotUrl = null;
let renderedPlotFallback = '';
technoeconomicSetPlot = (_image, _fallback, url, fallbackText) => {
  renderedPlotUrl = url;
  renderedPlotFallback = fallbackText;
};
technoeconomicSetDownload = () => {};
technoeconomicSources = [];
const available = (p10, p50, p90) => ({
  status: 'available', percentiles: {p10, p50, p90},
});
const job = {
  job_id: 'tea_lifecycle_v6', source_annual_job_id: 'annual-source',
  artifacts: {exports: {artifacts: {cdf_plot: {
    url: '/api/technoeconomic/jobs/tea_lifecycle_v6/artifacts/cdf_plot',
    chart_contract_id: 'lifecycle_system_lcoe_cdf_v2',
  }}}},
  request: {
    n: 1000, source_annual_job_id: 'annual-source',
    finance: {constant_dollar_cost_year: 2022, project_life_years: 30},
  },
};
const result = {
  calculation_contract_version: 'tea-calculation-v6',
  result_version: 'tea-result-v6', sampling_version: 'tea-lhs-v2',
  realization_count: 1000,
  summaries: {
    headline_decision: {
      status: 'available', decision: 'solaredge_preferred',
      preferred_system: 'solaredge', probability_threshold: 0.75,
      reason_codes: [],
    },
    probability_counts: {upgrade_npv: {
      positive: 800, negative: 150, tie: 50, denominator: 1000,
      p_positive: 0.8, p_negative: 0.15, p_tie: 0.05,
    }},
    upgrade_npv: available(1000, 2000, 3000),
    lcoe_solectria: available(0.04, 0.05, 0.06),
    lcoe_solaredge: available(0.045, 0.055, 0.065),
    delta_lcoe: available(0.004, 0.005, 0.006),
    lcoo: available(0.01, 0.02, 0.03),
    lifecycle_cost_solectria: available(1000000, 1200000, 1400000),
    lifecycle_cost_solaredge: available(1100000, 1300000, 1500000),
    lifecycle_energy_solectria: available(10000000, 11000000, 12000000),
    lifecycle_energy_solaredge: available(10500000, 11500000, 12500000),
  },
  paired_lifecycle: {
    target_capacity_w: 100000000, target_rating_basis: 'ac_operating_limit',
    source_energy_basis: 'gross', reliability_mode: 'event',
    constant_dollar_cost_year: 2022, warnings: [], reason_codes: [],
    formula_registry: {
      formula_registry_version: 'tea-formulas-v6',
      formula_registry_sha256: 'a'.repeat(64),
    },
  },
};
assert.equal(Object.hasOwn(result, 'paired_commercial'), false);
technoeconomicRenderLifecycleResult(job, result);
assert.equal(resultRoot.dataset.state, 'done');
assert.equal(resultRoot.dataset.presentation, 'lifecycle');
assert.equal(technoeconomicElements.legacyPercentilePanel.hidden, true);
assert.equal(technoeconomicElements.v6DecisionPanel.hidden, false);
assert.equal(decisionBody.children.length, 3);
assert.deepEqual(decisionBody.children[1].children.map((child) => child.textContent), [
  'P50 (median)', '$2,000', '50', '55', '5', '20',
]);
assert.deepEqual(decisionBody.children[1].children.slice(1).map(
  (child) => child.dataset.label
), [
  'Upgrade NPV (USD)', 'Solectria LCOE (USD/MWh)',
  'SolarEdge LCOE (USD/MWh)', 'Delta LCOE, SE minus SO (USD/MWh)',
  'LCOO, SE minus SO (USD/MWh)',
]);
assert.ok(interpretation.textContent.includes('Upgrade NPV P50 is $2,000'));
assert.ok(interpretation.textContent.includes('Positive upgrade NPV favors SolarEdge'));
assert.equal(probabilities.children.length, 4);
assert.equal(
  renderedPlotUrl,
  '/api/technoeconomic/jobs/tea_lifecycle_v6/artifacts/cdf_plot'
);
job.artifacts.exports.artifacts.cdf_plot.chart_contract_id =
  'lifecycle_upgrade_npv_and_lcoe_cdf_v1';
technoeconomicRenderLifecycleResult(job, result);
assert.equal(renderedPlotUrl, null);
assert.ok(renderedPlotFallback.includes('Recalculate'));
console.log(JSON.stringify({
  state: resultRoot.dataset.state,
  p50: decisionBody.children[1].children.map((child) => child.textContent),
  interpretation: interpretation.textContent,
}));
"""
        )
        self.assertEqual("done", payload["state"])
        self.assertEqual("$2,000", payload["p50"][1])
        self.assertIn("Positive upgrade NPV", payload["interpretation"])

    @unittest.skipUnless(shutil.which("node"), "Node.js is required")
    def test_standalone_unavailable_formatters_and_annual_cost_aggregation(self) -> None:
        payload = self.run_node(
            r"""
const assert = require('node:assert/strict');
for (const missing of [null, undefined, '', '   ']) {
  assert.equal(technoeconomicStandaloneFormatUsd(missing), 'Unavailable');
  assert.equal(technoeconomicStandaloneFormatLcoePerMwh(missing), 'Unavailable');
}
assert.equal(technoeconomicStandaloneFormatUsd(0), '$0');
assert.equal(technoeconomicStandaloneFormatLcoePerMwh(0), '0 USD/MWh');
assert.equal(technoeconomicStandaloneFormatLcoeTableValue(0), '0');
const annual = [
  {timing: 'annual_year_end', percentiles: {p50: 2200000}},
  {timing: 'annual_year_end', percentiles: {p50: '3300000'}},
  {timing: 'initial_t0', percentiles: {p50: 100000000}},
];
assert.equal(
  technoeconomicStandaloneAggregateLinePercentile(annual, 'annual_year_end', 'p50'),
  5500000
);
assert.equal(
  technoeconomicStandaloneAggregateLinePercentile(
    [...annual, {timing: 'annual_year_end', percentiles: {p50: null}}],
    'annual_year_end', 'p50'
  ),
  null
);
assert.equal(
  technoeconomicStandaloneAggregateLinePercentile([], 'annual_year_end', 'p50'),
  null
);
console.log(JSON.stringify({
  usdMissing: technoeconomicStandaloneFormatUsd(null),
  lcoeMissing: technoeconomicStandaloneFormatLcoePerMwh(''),
  annualP50: technoeconomicStandaloneAggregateLinePercentile(
    annual, 'annual_year_end', 'p50'
  ),
}));
"""
        )
        self.assertEqual("Unavailable", payload["usdMissing"])
        self.assertEqual("Unavailable", payload["lcoeMissing"])
        self.assertEqual(5500000, payload["annualP50"])

    @unittest.skipUnless(shutil.which("node"), "Node.js is required")
    def test_paired_draft_round_trip_excludes_acceptance(self) -> None:
        payload = self.run_node(
            r"""
const assert = require('node:assert/strict');
const memory = new Map();
globalThis.localStorage = {
  getItem(key) { return memory.has(key) ? memory.get(key) : null; },
  setItem(key, value) { memory.set(key, String(value)); },
  removeItem(key) { memory.delete(key); },
};
assert.equal(TECHNOECONOMIC_STANDALONE_DRAFT_SCHEMA_VERSION,
  'technoeconomic-paired-draft-v3');
assert.equal(TECHNOECONOMIC_STANDALONE_DRAFT_STORAGE_KEY,
  'sbepv.technoeconomic.paired-draft.v3');
const staleDraft = technoeconomicStandaloneDefaultDraft();
staleDraft.schema_version = 'technoeconomic-paired-draft-v2';
staleDraft.systems.solectria.cost_lines.find((line) => line.key === 'Om')
  .distribution.value = '0.022';
memory.set(TECHNOECONOMIC_STANDALONE_PREVIOUS_DRAFT_STORAGE_KEY,
  JSON.stringify(staleDraft));
assert.equal(technoeconomicLoadStandaloneDraft(), null);
const preV6Draft = technoeconomicStandaloneDefaultDraft();
delete preV6Draft.calculation_contract_version;
delete preV6Draft.lifecycle_json;
memory.set(TECHNOECONOMIC_STANDALONE_DRAFT_STORAGE_KEY,
  JSON.stringify(preV6Draft));
const preV6Loaded = technoeconomicLoadStandaloneDraft();
assert.equal(preV6Loaded.calculation_contract_version,
  TECHNOECONOMIC_PAIRED_CONTRACT_VERSION);
assert.equal(technoeconomicStandaloneDefaultDraft().calculation_contract_version,
  TECHNOECONOMIC_LIFECYCLE_CONTRACT_VERSION);
memory.delete(TECHNOECONOMIC_STANDALONE_DRAFT_STORAGE_KEY);
const control = (value, checked = false) => ({value, checked});
const parameters = (values) => ({
  querySelectorAll() {
    return Object.entries(values).map(([key, value]) => ({
      dataset: {teaV4Param: key}, value,
    }));
  },
});
function card(system, key, timing, unit, family, values, occurrenceYears = '') {
  const familyControl = control(family);
  const params = parameters(values);
  return {
    dataset: {
      teaV4System: system, teaV4CostLine: key,
      inputId: `commercial.${system}.${key.toLowerCase()}`,
      timing, unit,
    },
    querySelector(selector) {
      if (selector === 'h5') return {textContent: key};
      if (selector === '[data-tea-v4-family]') return familyControl;
      if (selector === '.tea-v4-distribution-parameters') return params;
      return null;
    },
    querySelectorAll: params.querySelectorAll,
    occurrenceYears,
  };
}
const cards = Object.fromEntries(['solectria', 'solaredge'].map((system) => [system, {
  capex: card(system, 'Capex', 'initial_t0', 'constant_usd_per_target_w',
    'triangular', {low: '1.1', mode: '1.2', high: '1.3'}),
  om: card(system, 'Om', 'annual_year_end', 'constant_usd_per_target_w_year',
    'fixed', {value: '18'}),
  replacement: card(system, 'Replacement', 'scheduled_year_end',
    'constant_usd_per_target_w', 'fixed', {value: '0.2'}, '12, 24'),
}]));
globalThis.document = {
  getElementById(id) {
    if (id === 'technoeconomicStandaloneSolectriaReplacementYears') {
      return {value: cards.solectria.replacement.occurrenceYears};
    }
    if (id === 'technoeconomicStandaloneSolarEdgeReplacementYears') {
      return {value: cards.solaredge.replacement.occurrenceYears};
    }
    return null;
  },
};
technoeconomicElements = {
  standaloneResults: {},
  calculationContract: control(TECHNOECONOMIC_PAIRED_CONTRACT_VERSION),
  lifecycleJson: control(''),
  standaloneSourceSelect: control('annual-saved-v4'),
  standaloneTargetCapacityInput: control('85.05'),
  standaloneRealizations: control('24000'),
  standaloneSeed: control('77'),
  standaloneCostYear: control('2022'),
  standaloneProjectLife: control('35'),
  standaloneDiscountFamily: control('uniform'),
  standaloneDiscountParameters: parameters({low: '4', high: '7'}),
  standaloneDegradationFamily: control('fixed'),
  standaloneDegradationParameters: parameters({value: '0.45'}),
  standaloneSolectriaCostLines: {
    dataset: {ratingBasis: 'dc_installed_nameplate'},
    querySelectorAll: () => [cards.solectria.capex, cards.solectria.om],
  },
  standaloneSolarEdgeCostLines: {
    dataset: {ratingBasis: 'dc_installed_nameplate'},
    querySelectorAll: () => [cards.solaredge.capex, cards.solaredge.om],
  },
  standaloneSolectriaReplacementEnabled: control('', true),
  standaloneSolarEdgeReplacementEnabled: control('', true),
  standaloneSolectriaReplacementFields: {
    querySelectorAll: () => [cards.solectria.replacement],
  },
  standaloneSolarEdgeReplacementFields: {
    querySelectorAll: () => [cards.solaredge.replacement],
  },
  standaloneAssumptionNote: control('Saved evidence note.'),
  standaloneAccept: control('', true),
};
assert.equal(TECHNOECONOMIC_STANDALONE_DRAFT_SCHEMA_VERSION,
  'technoeconomic-paired-draft-v3');
assert.equal(technoeconomicPersistStandaloneDraft(), true);
const stored = JSON.parse(memory.get(TECHNOECONOMIC_STANDALONE_DRAFT_STORAGE_KEY));
assert.equal(stored.calculation_contract_version,
  TECHNOECONOMIC_PAIRED_CONTRACT_VERSION);
assert.equal(stored.source_annual_job_id, 'annual-saved-v4');
assert.equal(stored.target_capacity, '85.05');
assert.equal(stored.n, '24000');
assert.equal(stored.seed, '77');
assert.equal(stored.project_life_years, '35');
assert.equal(stored.rating_basis, 'dc_installed_nameplate');
assert.deepEqual(stored.discount_distribution, {
  family: 'uniform', low: '4', high: '7',
});
assert.equal(stored.systems.solectria.cost_lines.length, 3);
assert.equal(stored.systems.solaredge.cost_lines.length, 3);
assert.equal(stored.systems.solectria.cost_lines[2].occurrence_years, '12, 24');
assert.equal(stored.systems.solectria.replacement_enabled, true);
assert.equal(stored.systems.solaredge.replacement_enabled, true);
assert.equal(stored.assumption_note, 'Saved evidence note.');
assert.equal(Object.hasOwn(stored, 'acceptance'), false);
assert.equal(JSON.stringify(stored).includes('explicit_acceptance'), false);

memory.set(TECHNOECONOMIC_STANDALONE_DRAFT_STORAGE_KEY, JSON.stringify({
  ...stored, acceptance: true, explicit_acceptance: true,
}));
const loaded = technoeconomicLoadStandaloneDraft();
assert.equal(Object.hasOwn(loaded, 'acceptance'), false);
assert.equal(Object.hasOwn(loaded, 'explicit_acceptance'), false);

technoeconomicStandaloneEnsureSourceOption = () => {};
technoeconomicStandaloneRenderCostLines = (system, basis) => {
  technoeconomicPairedSystemElements(system).costLines.dataset.ratingBasis = basis;
};
technoeconomicStandaloneRenderReplacement = () => {};
technoeconomicStandaloneApplyDistributionDraft = (family, root, prefix, value) => {
  family.value = value.family;
  root.restored = value;
};
technoeconomicStandaloneApplyCostDraft = (root, line) => {
  root.restoredLines = [...(root.restoredLines || []), line];
};
technoeconomicRenderStandaloneDraft = () => {};
const hydrationSnapshots = [];
technoeconomicHydrateLifecycleTemplate = () => {
  const targetMw = Number(technoeconomicElements.standaloneTargetCapacityInput.value);
  hydrationSnapshots.push({
    targetMw,
    componentA: Math.ceil(targetMw * 10),
    componentB: Math.ceil(targetMw),
    ratingBasis: technoeconomicElements.standaloneSolarEdgeCostLines.dataset.ratingBasis,
  });
};
technoeconomicElements.standaloneSourceSelect.value = '';
technoeconomicElements.standaloneTargetCapacityInput.value = '';
technoeconomicElements.standaloneAccept.checked = true;
assert.equal(technoeconomicStandaloneApplyDraft(loaded), true);
assert.equal(technoeconomicElements.standaloneSourceSelect.value, 'annual-saved-v4');
assert.equal(technoeconomicElements.standaloneTargetCapacityInput.value, '85.05');
assert.deepEqual(hydrationSnapshots[0], {
  targetMw: 85.05, componentA: 851, componentB: 86,
  ratingBasis: 'dc_installed_nameplate',
});
assert.equal(technoeconomicElements.standaloneSolectriaCostLines.dataset.ratingBasis,
  'dc_installed_nameplate');
assert.equal(technoeconomicElements.standaloneSolarEdgeCostLines.dataset.ratingBasis,
  'dc_installed_nameplate');
assert.equal(technoeconomicElements.standaloneRealizations.value, '24000');
assert.equal(technoeconomicElements.standaloneSeed.value, '77');
assert.equal(technoeconomicElements.standaloneProjectLife.value, '35');
assert.equal(technoeconomicElements.standaloneCostYear.value, '2022');
assert.equal(technoeconomicElements.standaloneDiscountFamily.value, 'uniform');
assert.equal(technoeconomicElements.standaloneSolectriaReplacementEnabled.checked, true);
assert.equal(technoeconomicElements.standaloneSolarEdgeReplacementEnabled.checked, true);
assert.equal(technoeconomicElements.standaloneAssumptionNote.value,
  'Saved evidence note.');
assert.equal(technoeconomicElements.standaloneAccept.checked, false);
console.log(JSON.stringify({
  source: loaded.source_annual_job_id,
  costLines: loaded.systems.solectria.cost_lines.length
    + loaded.systems.solaredge.cost_lines.length,
  acceptanceStored: JSON.stringify(stored).includes('accept'),
  acceptanceAfterRestore: technoeconomicElements.standaloneAccept.checked,
}));
"""
        )
        self.assertEqual("annual-saved-v4", payload["source"])
        self.assertEqual(6, payload["costLines"])
        self.assertFalse(payload["acceptanceStored"])
        self.assertFalse(payload["acceptanceAfterRestore"])

    @unittest.skipUnless(shutil.which("node"), "Node.js is required")
    def test_standalone_acceptance_clears_only_for_dependent_edits(self) -> None:
        payload = self.run_node(
            r"""
const assert = require('node:assert/strict');
const acceptance = {checked: true};
const dependent = {};
const unrelated = {};
technoeconomicElements = {
  standaloneAccept: acceptance,
  standaloneAssumptionsDialog: {
    contains(target) { return target === acceptance || target === dependent; },
  },
};
assert.equal(technoeconomicClearStandaloneAcceptance(unrelated), false);
assert.equal(acceptance.checked, true);
assert.equal(technoeconomicClearStandaloneAcceptance(acceptance), false);
assert.equal(acceptance.checked, true);
assert.equal(technoeconomicClearStandaloneAcceptance(dependent), true);
assert.equal(acceptance.checked, false);
acceptance.checked = true;
technoeconomicApplyingDraft = true;
assert.equal(technoeconomicClearStandaloneAcceptance(dependent), false);
assert.equal(acceptance.checked, true);
technoeconomicApplyingDraft = false;
console.log(JSON.stringify({cleared: true, applyingPreserved: acceptance.checked}));
"""
        )
        self.assertTrue(payload["cleared"])
        self.assertTrue(payload["applyingPreserved"])

        initializer = self.script.split(
            "function initializeTechnoeconomicWorkspace", 1
        )[1]
        self.assertGreaterEqual(
            initializer.count("technoeconomicClearStandaloneAcceptance(event.target)"),
            2,
        )

    @unittest.skipUnless(shutil.which("node"), "Node.js is required")
    def test_standalone_assumptions_use_one_accessible_modal(self) -> None:
        payload = self.run_node(
            r"""
const assert = require('node:assert/strict');
const calls = {show: 0, close: 0, sourceFocus: 0, triggerFocus: 0};
const trigger = {focus() { calls.triggerFocus += 1; }};
const source = {focus() { calls.sourceFocus += 1; }};
const dialog = {
  open: false,
  showModal() { calls.show += 1; this.open = true; },
  close() {
    calls.close += 1;
    this.open = false;
    technoeconomicFinishAssumptionsClose();
  },
  setAttribute(name) { if (name === 'open') this.open = true; },
  removeAttribute(name) { if (name === 'open') this.open = false; },
};
technoeconomicElements = {
  standaloneAssumptionsDialog: dialog,
  standaloneEditAssumptionsButton: trigger,
  standaloneSourceSelect: source,
};
assert.equal(technoeconomicOpenAssumptionsDialog(trigger), true);
assert.equal(technoeconomicOpenAssumptionsDialog(trigger), true);
assert.equal(calls.show, 1);
assert.equal(calls.sourceFocus, 2);
assert.equal(technoeconomicCloseAssumptionsDialog(), true);
assert.equal(calls.close, 1);
assert.equal(calls.triggerFocus, 1);
assert.equal(technoeconomicOpenAssumptionsDialog(trigger), true);
assert.equal(technoeconomicCloseAssumptionsDialog({restoreFocus: false}), true);
assert.equal(calls.triggerFocus, 1);
console.log(JSON.stringify(calls));
"""
        )
        self.assertEqual(2, payload["show"])
        self.assertEqual(2, payload["close"])
        self.assertEqual(1, payload["triggerFocus"])

    def test_v4_navigation_targets_the_visible_result_and_uses_concise_copy(self) -> None:
        self.assertIn("? '#technoeconomicStandaloneResults'", self.mode_script)
        self.assertNotIn("? '#technoeconomicResults'", self.mode_script)
        self.assertIn(
            "Compare commercial Solectria and SolarEdge LCOE distributions.",
            self.mode_script,
        )

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
        self.assertIn(".tea-confirm-review-grid", tablet)
        self.assertIn(".tea-confirm-system-grid", tablet)
        self.assertIn("grid-template-columns: 1fr", tablet)
        self.assertIn(".tea-figure-grid", tablet)

        mobile = self.styles.split("@media (max-width: 560px)", 1)[1].split(
            "@media (prefers-reduced-motion: reduce)", 1
        )[0]
        self.assertIn(".tea-metric-grid", mobile)
        self.assertIn(".tea-tradeoff-grid", mobile)
        self.assertIn(".tea-confirm-summary", mobile)
        self.assertIn(".tea-confirm-footer", mobile)
        self.assertIn(".tea-confirm-readiness-list", mobile)
        self.assertIn(".tea-system-financial-fields", mobile)
        self.assertIn(".tea-system-estimate dl", mobile)
        self.assertIn(".tea-source-system-card", mobile)
        self.assertIn("grid-template-columns: 1fr", mobile)
        self.assertIn("min-height: 44px", mobile)
        self.assertIn("font-size: 16px", mobile)
        self.assertIn(".tea-download-link", mobile)
        self.assertIn("width: 100%", mobile)
        for marker in (
            ".tea-confirm-dialog {",
            "position: fixed",
            "top: 50%",
            "left: 50%",
            "transform: translate(-50%, -50%)",
            "grid-template-rows: auto minmax(0, 1fr) auto",
            ".tea-confirm-scroll {",
            "overflow-y: auto",
        ):
            self.assertIn(marker, self.styles)

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
            'path[1] === "formulas"',
            'path[2] === "v6"',
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
    def test_annual_source_selectors_only_render_eligible_runs(self) -> None:
        payload = self.run_node(
            r"""
const assert = require('node:assert/strict');
const node = (tag, options = {}) => ({
  tag, value: options.value === undefined ? '' : String(options.value),
  textContent: options.text === undefined ? '' : String(options.text),
  disabled: Boolean(options.disabled),
});
const select = () => ({
  children: [], value: '',
  get options() { return this.children; },
  replaceChildren(...children) { this.children = children; },
  appendChild(child) { this.children.push(child); },
});
const guidedSelect = select();
const lifecycleSelect = select();
technoeconomicNode = node;
technoeconomicElements = {
  sourceSelect: guidedSelect,
  standaloneSourceSelect: lifecycleSelect,
};
technoeconomicRenderSelectedSource = () => {};
technoeconomicRenderStandaloneDraft = () => {};
technoeconomicSources = [
  {
    source_annual_job_id: 'annual-eligible-old', eligible: true,
    eligible_years: [2023, 2024], provenance: {completed_at: '2026-01-01'},
  },
  {
    source_annual_job_id: 'annual-ineligible', eligible: false,
    reason_code: 'annual_temporal_semantics_obsolete',
    provenance: {completed_at: '2026-09-01'},
  },
  {
    source_annual_job_id: 'annual-eligible-new', eligible: true,
    eligible_years: [2024, 2025], provenance: {completed_at: '2026-08-01'},
  },
];

technoeconomicStandaloneEnsureSourceOption('annual-ineligible');
technoeconomicEnsureSourceOption('annual-ineligible');
assert.equal(lifecycleSelect.options.length, 0);
assert.equal(guidedSelect.options.length, 0);
technoeconomicRenderSourceOptions('annual-ineligible');
for (const target of [guidedSelect, lifecycleSelect]) {
  assert.deepEqual(target.options.map((option) => option.value), [
    '', 'annual-eligible-new', 'annual-eligible-old',
  ]);
  assert.equal(target.value, 'annual-eligible-new');
  assert.equal(target.options.some((option) => option.disabled), false);
  assert.equal(target.options.some(
    (option) => option.textContent.toLowerCase().includes('ineligible')
  ), false);
}

technoeconomicEnsureSourceOption('annual-eligible-old');
technoeconomicRenderSourceOptions();
assert.equal(guidedSelect.value, 'annual-eligible-old');
assert.equal(lifecycleSelect.value, 'annual-eligible-old');
console.log(JSON.stringify({
  options: lifecycleSelect.options.map((option) => option.textContent),
  selected: lifecycleSelect.value,
}));
"""
        )
        self.assertEqual("annual-eligible-old", payload["selected"])
        self.assertEqual(3, len(payload["options"]))
        self.assertFalse(any("ineligible" in item.lower() for item in payload["options"]))

    @unittest.skipUnless(shutil.which("node"), "Node.js is required")
    def test_source_refresh_stays_retryable_while_verification_is_pending(self) -> None:
        payload = self.run_node(
            r"""
const assert = require('node:assert/strict');
(async () => {
const optionNode = (tag, options = {}) => ({
  tag, value: options.value === undefined ? '' : String(options.value),
  textContent: options.text === undefined ? '' : String(options.text),
});
const select = () => ({
  children: [{tag: 'option', value: '', textContent: 'Select a source'}],
  value: '', attributes: {},
  get options() { return this.children; },
  replaceChildren(...children) { this.children = children; },
  appendChild(child) { this.children.push(child); },
  setAttribute(name, value) { this.attributes[name] = String(value); },
});
const button = () => ({
  disabled: true, textContent: 'Refresh sources', attributes: {},
  setAttribute(name, value) { this.attributes[name] = String(value); },
});
const guidedSelect = select();
const lifecycleSelect = select();
const guidedRefresh = button();
const lifecycleRefresh = button();
const sourceStatusPanel = {dataset: {}};
const lifecycleStatusPanel = {dataset: {}};
const sourceStatus = {textContent: ''};
const sourceDetail = {textContent: ''};
const lifecycleStatus = {textContent: ''};
const lifecycleHelp = {textContent: ''};
technoeconomicNode = optionNode;
technoeconomicElements = {
  sourceSelect: guidedSelect,
  standaloneSourceSelect: lifecycleSelect,
  refreshSourcesButton: guidedRefresh,
  standaloneRefreshSourcesButton: lifecycleRefresh,
  sourceStatusPanel,
  standaloneSourceStatusPanel: lifecycleStatusPanel,
  sourceStatus,
  sourceDetail,
  standaloneSourceStatus: lifecycleStatus,
  standaloneSourceHelp: lifecycleHelp,
};
technoeconomicCloseStaleAdvancedPreview = () => {};
technoeconomicRenderSelectedSource = () => technoeconomicSetSourceState(
  'ready', 'Calibrated annual energy is ready', 'Selection verified.'
);
technoeconomicRenderStandaloneDraft = () => {};
technoeconomicJob = null;
let resolveSources;
technoeconomicFetchJson = () => new Promise((resolve) => { resolveSources = resolve; });

const pending = refreshTechnoeconomicSources();
for (const control of [guidedRefresh, lifecycleRefresh]) {
  assert.equal(control.disabled, false);
  assert.equal(control.textContent, 'Retry source check');
  assert.equal(control.attributes['aria-busy'], 'true');
}
assert.equal(
  lifecycleSelect.options[0].textContent,
  'Checking verified Annual Simulations…'
);
assert.equal(lifecycleStatus.textContent, 'Checking Annual Simulation sources');
resolveSources({sources: [
  {source_annual_job_id: 'annual-eligible', eligible: true, eligible_years: [2025]},
  {source_annual_job_id: 'annual-obsolete', eligible: false},
]});
await pending;
assert.deepEqual(lifecycleSelect.options.map((option) => option.value), [
  '', 'annual-eligible',
]);
assert.equal(lifecycleSelect.value, 'annual-eligible');
for (const control of [guidedRefresh, lifecycleRefresh]) {
  assert.equal(control.disabled, false);
  assert.equal(control.textContent, 'Refresh sources');
  assert.equal(control.attributes['aria-busy'], 'false');
}
assert.equal(lifecycleStatusPanel.dataset.state, 'ready');
assert.equal(lifecycleStatus.textContent, 'Calibrated annual energy is ready');
console.log(JSON.stringify({
  options: lifecycleSelect.options.map((option) => option.textContent),
  refreshLabel: lifecycleRefresh.textContent,
  status: lifecycleStatus.textContent,
}));
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
"""
        )
        self.assertEqual("Refresh sources", payload["refreshLabel"])
        self.assertEqual("Calibrated annual energy is ready", payload["status"])
        self.assertEqual(2, len(payload["options"]))

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
    def test_guided_commercial_scaling_serializes_dynamic_signed_inputs(self) -> None:
        payload = self.run_node(
            r"""
const assert = require('node:assert/strict');
const base = technoeconomicDefaultDraft();
base.source_annual_job_id = 'annual-commercial-scaling';
const guided = {
  cost_year: '2026', project_life_years: '30',
  discount: '4.5', discount_low: '', discount_high: '',
  degradation: '0.4', degradation_low: '', degradation_high: '',
  solectria_capex: '90000', solectria_capex_low: '', solectria_capex_high: '',
  solectria_om: '4000', solectria_om_low: '', solectria_om_high: '',
  solaredge_capex: '110000', solaredge_capex_low: '', solaredge_capex_high: '',
  solaredge_om: '4500', solaredge_om_low: '', solaredge_om_high: '',
  assumption_note: 'Documented independent lifecycle inputs.', accepted: true,
  commercial_enabled: true,
  commercial_target_capacity: '87.5', commercial_target_unit: 'mw',
  commercial_rating_basis: 'ac_operating_limit',
  commercial_cost: '-2500000', commercial_cost_low: '-3000000',
  commercial_cost_high: '-2000000', commercial_cost_timing: 'equivalent_annual',
  commercial_rationale: 'The target uses the same AC operating-limit rating basis; direct scaling is accepted for this scenario.',
  commercial_accepted: true,
};
const draft = technoeconomicBuildGuidedDraft(base, guided, {
  seed: '314159', date: '2026-08-26',
});
assert.equal(draft.commercial_scaling.target_capacity, '87.5');
assert.equal(draft.commercial_scaling.target_capacity_unit, 'mw');
assert.equal(draft.commercial_scaling.target_rating_basis, 'ac_operating_limit');
assert.equal(draft.commercial_scaling.marginal_cost_timing, 'equivalent_annual');
assert.equal(draft.commercial_scaling.marginal_cost_unit, 'constant_usd_per_year');
assert.deepEqual(draft.commercial_scaling.marginal_cost_difference, {
  family: 'triangular', value: '', low: '-3000000', mode: '-2500000',
  high: '-2000000', mean: '', sd: '',
});
assert.equal(draft.commercial_scaling.evidence.explicit_acceptance, true);

const source = {
  source_annual_job_id: 'annual-commercial-scaling', eligible: true,
  applied_capacity: {
    solectria: {applied_capacity_w: 94000, rating_basis: 'ac_operating_limit'},
    solaredge: {applied_capacity_w: 94000, rating_basis: 'ac_operating_limit'},
  },
};
const serialized = serializeTechnoeconomicRequest(draft, {sources: [source]});
assert.equal(serialized.valid, true, JSON.stringify(serialized.errors));
assert.deepEqual(serialized.payload.commercial_scaling, {
  target_capacity: 87.5,
  target_capacity_unit: 'mw',
  target_rating_basis: 'ac_operating_limit',
  marginal_cost_difference: {
    family: 'triangular', low: -3000000, mode: -2500000, high: -2000000,
  },
  marginal_cost_timing: 'equivalent_annual',
  marginal_cost_unit: 'constant_usd_per_year',
  transfer_method: 'direct_capacity_scaling',
  transfer_rationale: guided.commercial_rationale,
  evidence: serialized.payload.commercial_scaling.evidence,
});
assert.equal(serialized.payload.commercial_scaling.evidence.evidence_class,
  'engineering_judgment');
assert.equal(serialized.payload.commercial_reference_design, null);
assert.equal(serialized.payload.commercial_transfer, null);

const mismatch = structuredClone(draft);
mismatch.commercial_scaling.target_rating_basis = 'dc_installed_nameplate';
const rejectedBasis = serializeTechnoeconomicRequest(mismatch, {sources: [source]});
assert.equal(rejectedBasis.valid, false);
assert.ok(rejectedBasis.errors.some((item) =>
  item.path === 'commercial_scaling.target_rating_basis'));

const invalidRange = structuredClone(draft);
invalidRange.commercial_scaling.marginal_cost_difference = {
  family: 'triangular', low: '4', mode: '3', high: '2',
};
const rejectedRange = serializeTechnoeconomicRequest(invalidRange, {sources: [source]});
assert.equal(rejectedRange.valid, false);
assert.ok(rejectedRange.errors.some((item) =>
  item.path === 'commercial_scaling.marginal_cost_difference'));

const disabled = technoeconomicBuildGuidedDraft(base, {
  ...guided, commercial_enabled: false,
}, {seed: '2718', date: '2026-08-26'});
const withoutScaling = serializeTechnoeconomicRequest(disabled, {sources: [source]});
assert.equal(withoutScaling.valid, true, JSON.stringify(withoutScaling.errors));
assert.equal(withoutScaling.payload.commercial_scaling, null);

console.log(JSON.stringify({
  scaling: serialized.payload.commercial_scaling,
  basisErrorCount: rejectedBasis.errors.length,
  rangeErrorCount: rejectedRange.errors.length,
  disabled: withoutScaling.payload.commercial_scaling,
}));
"""
        )
        self.assertEqual(87.5, payload["scaling"]["target_capacity"])
        self.assertEqual("mw", payload["scaling"]["target_capacity_unit"])
        self.assertEqual(
            "constant_usd_per_year", payload["scaling"]["marginal_cost_unit"]
        )
        self.assertGreater(payload["basisErrorCount"], 0)
        self.assertGreater(payload["rangeErrorCount"], 0)
        self.assertIsNone(payload["disabled"])

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
        self.assertIn("technoeconomicSerializeCurrentRequest", open_confirmation)
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

    @unittest.skipUnless(shutil.which("node"), "Node.js is required")
    def test_completed_commercial_scaling_results_render_all_metrics_and_reason(self) -> None:
        payload = self.run_node(
            r"""
const assert = require('node:assert/strict');
const elements = {
  technoeconomicCommercialResults: {hidden: true},
  technoeconomicCommercialResultMetrics: {
    children: [], replaceChildren() { this.children = []; },
    appendChild(child) { this.children.push(child); },
  },
  technoeconomicCommercialResultStatus: {textContent: '', dataset: {}},
};
globalThis.document = {getElementById(id) { return elements[id] || null; }};
technoeconomicMetricCard = (metricName, summary) => ({metricName, summary});
const available = (p5, p50, p95) => ({
  status: 'available', count: 500, percentiles: {p5, p50, p95},
});
const result = {
  realization_count: 500,
  commercial_scaling: {
    target_capacity_w: 87500000,
    target_rating_basis: 'ac_operating_limit',
    marginal_cost_timing: 'equivalent_annual',
    transfer_method: 'direct_capacity_scaling',
  },
  summaries: {
    CommercialTargetCapacity_W: available(87500000, 87500000, 87500000),
    CommercialYear1DeltaEnergy_se_minus_sol_kWh_AC: available(900000, 1100000, 1300000),
    CommercialLifecycleDeltaEnergy_se_minus_sol_kWh_AC: available(12000000, 14000000, 16000000),
    CommercialEquivalentAnnualDeltaEnergy_se_minus_sol_kWh_AC_per_year: available(800000, 1000000, 1200000),
    CommercialLifecycleMarginalCostDelta_se_minus_sol_USD: available(-5000000, -4000000, -3000000),
    CommercialEquivalentAnnualMarginalCostDelta_se_minus_sol_USD_per_year: available(-350000, -300000, -250000),
    CommercialMarginalLCOO_se_minus_sol_USD_per_kWh_AC: available(-0.4, -0.3, -0.2),
  },
};
technoeconomicRenderCommercialScaling(result);
assert.equal(elements.technoeconomicCommercialResults.hidden, false);
assert.equal(elements.technoeconomicCommercialResultMetrics.children.length, 7);
assert.deepEqual(
  elements.technoeconomicCommercialResultMetrics.children.map((item) => item.metricName),
  TECHNOECONOMIC_COMMERCIAL_METRICS.map(([name]) => name),
);
assert.equal(elements.technoeconomicCommercialResultStatus.dataset.state, 'available');
assert.ok(elements.technoeconomicCommercialResultStatus.textContent.includes(
  'equivalent annual'));
assert.ok(elements.technoeconomicCommercialResultStatus.textContent.includes(
  'AC operating limit'));

result.summaries.CommercialMarginalLCOO_se_minus_sol_USD_per_kWh_AC = {
  status: 'unavailable', reason: 'zero_commercial_lifecycle_delta_energy',
  count: 0, percentiles: {p5: null, p50: null, p95: null},
};
technoeconomicRenderCommercialScaling(result);
assert.equal(elements.technoeconomicCommercialResultStatus.dataset.state, 'unavailable');
assert.ok(elements.technoeconomicCommercialResultStatus.textContent.includes(
  'zero commercial lifecycle delta energy'));
assert.equal(
  elements.technoeconomicCommercialResultMetrics.children.at(-1).summary.reason,
  'zero_commercial_lifecycle_delta_energy',
);

technoeconomicRenderCommercialScaling({summaries: {}});
assert.equal(elements.technoeconomicCommercialResults.hidden, true);
assert.equal(elements.technoeconomicCommercialResultMetrics.children.length, 0);
console.log(JSON.stringify({
  metricCount: TECHNOECONOMIC_COMMERCIAL_METRICS.length,
  unavailableStatus: 'zero commercial lifecycle delta energy',
}));
"""
        )
        self.assertEqual(7, payload["metricCount"])
        self.assertEqual(
            "zero commercial lifecycle delta energy", payload["unavailableStatus"]
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
            "technoeconomicRenderCommercialScaling(result)",
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
  confirmCancelButton: {disabled: false}, confirmCloseButton: {disabled: false},
  submitButton: {disabled: false},
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
  assert.equal(technoeconomicElements.confirmCloseButton.disabled, true);
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
  assert.equal(technoeconomicElements.confirmCloseButton.disabled, false);
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
const groupTitles = [];
technoeconomicSummaryItem = (label, value) => ({label, value: String(value)});
technoeconomicConfirmationGroup = (title, items) => ({title, items});
globalThis.technoeconomicElements = {
  confirmSummary: {replaceChildren(...groups) {
    for (const group of groups) {
      groupTitles.push(group.title);
      rendered.push(...group.items);
    }
  }},
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
  'Seeded Latin Hypercube Sampling (LHS)', 'tea-lhs-v1',
  'Balanced seeded paired-year allocation',
]) assert.ok(disclosure.includes(materialValue), materialValue);
assert.deepEqual(groupTitles, ['Request details']);
assert.equal(Object.isFrozen(serialized.payload), true);
assert.equal(Object.isFrozen(serialized.payload.cost_lines[0].distribution), true);
console.log(JSON.stringify({itemCount: rendered.length, disclosure, groupTitles}));
"""
        )
        self.assertGreater(payload["itemCount"], 13)
        self.assertIn("TRANSFER-INCREMENT", payload["disclosure"])
        self.assertEqual(["Request details"], payload["groupTitles"])

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
