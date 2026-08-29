"""Phase 0/1 contract tests for the fixture-backed Autonomy frontend.

These tests intentionally inspect the canonical ``frontend/`` sources.  They do
not prescribe one renderer function, card hierarchy, or JavaScript namespace;
they protect the approved states, authority boundary, deterministic view model,
and accessibility/responsive contracts that must survive visual iteration.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import unittest
from pathlib import Path

from sbepv import dashboard


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FRONTEND_ROOT = PROJECT_ROOT / "frontend"

FIXTURE_DEFAULTS = {
    "no-case": ("ask", "investigation"),
    "new-case": ("ask", "investigation"),
    "calibration-blocked": ("verify", "investigation"),
    "annual-unavailable": ("verify", "investigation"),
    "annual-incomplete": ("verify", "investigation"),
    "annual-stale": ("verify", "investigation"),
    "evidence-needed": ("verify", "investigation"),
    "evidence-conflict": ("verify", "investigation"),
    "agent-unavailable": ("ask", "investigation"),
    "scenario-invalid": ("compare", "investigation"),
    "ready-to-confirm": ("run", "investigation"),
    "queued": ("run", "investigation"),
    "running": ("run", "investigation"),
    "failed": ("run", "investigation"),
    "partial-results": ("run", "investigation"),
    "results-ready": ("decide", "investigation"),
    "recommendation-provisional": ("decide", "brief"),
    "decision-ready": ("decide", "brief"),
    "signed": ("decide", "brief"),
    "signed-superseded": ("compare", "investigation"),
    "network-reconnecting": ("ask", "investigation"),
    "shared-case-stale": ("verify", "investigation"),
}

STAGE_SPELLINGS = {
    "ask": ("ask",),
    "verify": ("verify", "verify-evidence", "verify evidence"),
    "compare": ("compare", "compare-scenarios", "compare scenarios"),
    "run": ("run", "run-tea", "run tea"),
    "decide": ("decide",),
}

VIEW_SPELLINGS = {
    "investigation": ("investigation",),
    "brief": ("brief", "decision-brief", "decision brief"),
}


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8").replace("\r\n", "\n").replace(
        "\r", "\n"
    )


def _source_group(directory: str, pattern: str) -> tuple[Path, ...]:
    return tuple(sorted((FRONTEND_ROOT / directory).glob(pattern)))


def _fixture_entry(source: str, fixture_id: str) -> str:
    """Return one factory call without fixing whitespace or property order."""

    match = re.search(
        rf"(['\"]){re.escape(fixture_id)}\1\s*:\s*"
        rf"[A-Za-z0-9_$]*fixture\s*\(\s*\{{(?P<body>[\s\S]*?)\n\s*\}}\s*\)\s*,?",
        source,
        flags=re.IGNORECASE,
    )
    if match is None:
        raise AssertionError(f"fixture {fixture_id!r} has no structured catalog entry")
    return match.group("body").lower()


class AutonomyFrontendSources(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.markup_paths = _source_group("html", "*autonomy*.html")
        cls.style_paths = _source_group("css", "*autonomy*.css")
        cls.script_paths = _source_group("js", "*autonomy*.js")
        cls.markup = "\n".join(_read(path) for path in cls.markup_paths)
        cls.styles = "\n".join(_read(path) for path in cls.style_paths)
        cls.script = "\n".join(_read(path) for path in cls.script_paths)
        cls.all_markup = "\n".join(
            _read(path)
            for path in sorted((FRONTEND_ROOT / "html").glob("[0-9]*.html"))
        )
        cls.all_styles = "\n".join(
            _read(path) for path in sorted((FRONTEND_ROOT / "css").glob("*.css"))
        )
        cls.all_scripts = "\n".join(
            _read(path) for path in sorted((FRONTEND_ROOT / "js").glob("*.js"))
        )
        cls.combined = "\n".join((cls.markup, cls.styles, cls.script))
        cls.assembled = dashboard.assemble_dashboard_html(PROJECT_ROOT)

    def test_canonical_autonomy_source_groups_exist(self):
        self.assertTrue(self.markup_paths, "missing canonical Autonomy HTML partial")
        self.assertTrue(self.style_paths, "missing canonical Autonomy CSS partial")
        self.assertTrue(self.script_paths, "missing canonical Autonomy JS partial")

    def test_all_twenty_two_fixture_ids_are_catalogued(self):
        self.assertEqual(len(FIXTURE_DEFAULTS), 22)
        catalog = self.script.split("const AUTONOMY_FIXTURE_CATALOG", 1)[1].split(
            "const autonomyPanel", 1
        )[0]
        discovered = set(
            re.findall(
                r"(?m)^\s*['\"]([^'\"]+)['\"]\s*:\s*[A-Za-z0-9_$]*Fixture\s*\(",
                catalog,
            )
        )
        self.assertEqual(discovered, set(FIXTURE_DEFAULTS))
        fixture_select = self.markup.split('id="autonomyFixtureSelect"', 1)[1].split(
            "</select>", 1
        )[0]
        selector_options = set(
            re.findall(
                r"(?is)<option(?=[^>]*\bvalue=['\"]([^'\"]+)['\"])[^>]*>",
                fixture_select,
            )
        )
        self.assertEqual(selector_options, set(FIXTURE_DEFAULTS))
        for fixture_id in FIXTURE_DEFAULTS:
            with self.subTest(fixture=fixture_id):
                self.assertRegex(
                    self.script,
                    rf"(['\"]){re.escape(fixture_id)}\1",
                )

    def test_fixture_default_stage_and_view_mapping_is_deterministic(self):
        factory = self.script.split("function autonomyFixture(config)", 1)[1].split(
            "const AUTONOMY_FIXTURE_CATALOG", 1
        )[0]
        self.assertRegex(factory, r"defaultView\s*:\s*['\"]investigation['\"]")
        self.assertRegex(
            self.script,
            r"return\s*\{\s*stage\s*:\s*fixture\.stage\s*,\s*view\s*:\s*fixture\.defaultView\s*\}",
        )
        for fixture_id, (stage, view) in FIXTURE_DEFAULTS.items():
            with self.subTest(fixture=fixture_id):
                entry = _fixture_entry(self.script, fixture_id)
                stage_values = "|".join(
                    re.escape(spelling) for spelling in STAGE_SPELLINGS[stage]
                )
                self.assertRegex(
                    entry,
                    rf"stage\s*:\s*['\"](?:{stage_values})['\"]",
                )
                if view == "brief":
                    self.assertRegex(
                        entry,
                        r"defaultview\s*:\s*['\"]decision-brief['\"]",
                    )
                elif "defaultview" in entry:
                    self.assertTrue(
                        any(spelling in entry for spelling in VIEW_SPELLINGS[view]),
                        f"{fixture_id} overrides the default with the wrong view",
                    )

    def test_every_fixture_has_one_supported_primary_recovery_or_progress_action(self):
        for fixture_id in FIXTURE_DEFAULTS:
            with self.subTest(fixture=fixture_id):
                entry = _fixture_entry(self.script, fixture_id)
                self.assertEqual(len(re.findall(r"\baction\s*:", entry)), 1)
                self.assertEqual(len(re.findall(r"\bactionlabel\s*:", entry)), 1)
                self.assertRegex(entry, r"\baction\s*:\s*['\"][^'\"]+['\"]")
                self.assertRegex(
                    entry,
                    r"\bactionlabel\s*:\s*['\"][^'\"]+['\"]",
                )

    def test_shared_case_identity_and_revision_are_single_source_values(self):
        # One literal prevents the two views from drifting to copied identities.
        self.assertEqual(self.script.count("case_sbe_hybrid_001"), 1)
        self.assertRegex(
            self.script,
            r"(?i)\b[A-Z0-9_]*CASE_ID\s*=\s*['\"]case_sbe_hybrid_001['\"]",
        )
        self.assertRegex(
            self.script,
            r"(?i)\b[A-Z0-9_]*CASE_REVISION\s*=\s*['\"]revision_[^'\"]+['\"]",
        )
        self.assertIn("dataset.autonomyCaseId", self.script)
        self.assertIn("dataset.autonomyCaseRevision", self.script)
        self.assertRegex(
            self.script,
            r"dataset\.autonomyCaseRevision\s*=\s*fixture\.superseded\s*\?\s*['\"]revision_004['\"]\s*:\s*AUTONOMY_CASE_REVISION",
        )
        for concept in ("case", "revision", "source lock", "basis lock"):
            self.assertIn(concept, self.combined.lower())

    def test_view_and_stage_navigation_cannot_mutate_case_or_fixture_state(self):
        view_navigation = self.script.split("function autonomySetView", 1)[1].split(
            "\n        function ", 1
        )[0]
        stage_navigation = self.script.split("function autonomySelectStage", 1)[1].split(
            "\n        function ", 1
        )[0]
        for block in (view_navigation, stage_navigation):
            self.assertNotIn("autonomySelectFixture", block)
            self.assertNotIn("dataset.autonomyCaseId", block)
            self.assertNotIn("dataset.autonomyCaseRevision", block)
            self.assertNotRegex(block, r"fixture\.(?:caseState|stage)\s*=")
        self.assertIn("autonomyCurrentFixture()", view_navigation)
        self.assertIn("autonomySelectedView = 'investigation'", stage_navigation)

    def test_results_partial_completed_and_signed_transitions_are_distinct(self):
        expected = {
            "partial-results": ("run", "investigation"),
            "results-ready": ("decide", "investigation"),
            "recommendation-provisional": ("decide", "brief"),
            "decision-ready": ("decide", "brief"),
            "signed": ("decide", "brief"),
            "signed-superseded": ("compare", "investigation"),
        }
        for fixture_id, defaults in expected.items():
            self.assertEqual(FIXTURE_DEFAULTS[fixture_id], defaults)
            _fixture_entry(self.script, fixture_id)

        copy = self.combined.lower()
        self.assertIn("partial", copy)
        self.assertIn("open decision brief", copy)
        self.assertIn("sign-off", copy)
        self.assertIn("superseded", copy)
        self.assertIn("immutable", copy)
        self.assertRegex(
            copy,
            r"partial[\s\S]{0,700}(?:no final recommendation or sign-off is available|(?:sign-off|signoff)[\s\S]{0,160}(?:unavailable|disabled|cannot|not available))",
        )
        factory = self.script.split("function autonomyFixture(config)", 1)[1].split(
            "const AUTONOMY_FIXTURE_CATALOG", 1
        )[0]
        self.assertRegex(factory, r"signoffAllowed\s*:\s*false")
        self.assertNotIn("signoffallowed", _fixture_entry(self.script, "partial-results"))
        self.assertRegex(
            _fixture_entry(self.script, "decision-ready"),
            r"signoffallowed\s*:\s*true",
        )
        self.assertIn(
            "autonomyPrepareSignoffBtn.disabled = !fixture.signoffAllowed",
            self.script,
        )
        for action, target in (
            ("advance-running", "running"),
            ("advance-partial", "partial-results"),
            ("preview-retry", "queued"),
        ):
            self.assertRegex(
                self.script,
                rf"(?i)action\s*===\s*['\"]{re.escape(action)}['\"][\s\S]{{0,100}}selectfixture\s*\(\s*['\"]{re.escape(target)}['\"]",
            )
        self.assertRegex(
            self.script,
            r"(?i)SignoffSubmitBtn[\s\S]{0,1800}selectfixture\s*\(\s*['\"]signed['\"]",
        )
        self.assertRegex(
            self.script,
            r"(?i)CreateRevisionBtn[\s\S]{0,220}selectfixture\s*\(\s*['\"]signed-superseded['\"]",
        )

    def test_required_lifecycle_states_have_text_and_style_hooks(self):
        copy = self.combined.lower()
        for visible_state in (
            "no decision cases",
            "blocked",
            "running",
            "partial results",
            "completed",
            "signed",
        ):
            with self.subTest(state=visible_state):
                self.assertIn(visible_state, copy)

        compact_styles = re.sub(r"\s+", " ", self.styles)
        for style_hook in (
            "autonomy-empty-case",
            'data-status="blocked"',
            'data-state^="running"',
            'data-status="partial"',
            'data-state="completed"',
            "signed-revision",
        ):
            with self.subTest(style_hook=style_hook):
                self.assertIn(style_hook, compact_styles)

    def test_fixture_actions_are_local_and_do_not_cross_backend_authority(self):
        forbidden = {
            "network fetch": r"\bfetch\s*\(",
            "XHR": r"\bXMLHttpRequest\b",
            "web socket": r"\bWebSocket\b",
            "dashboard API": r"/api/",
            "OpenAI client": r"(?:\bnew\s+OpenAI\b|\bopenai\s*\.)",
            "Calibration execution": r"\brunAnalysis\s*\(",
            "Annual execution": r"\brunAnnualAnalysis\s*\(",
            "TEA submit": r"\b(?:submit|confirm|create|queue|retry)Technoeconomic\w*\s*\(",
            "TEA submit control": r"technoeconomicSubmitBtn\s*\.\s*(?:click|dispatchEvent)",
        }
        for authority, pattern in forbidden.items():
            with self.subTest(authority=authority):
                self.assertNotRegex(self.script, pattern)

        for boundary_copy in (
            "Fixture preview",
            "no jobs will be created",
            "Preview queued state",
            "fixture-only",
        ):
            self.assertIn(boundary_copy.lower(), self.combined.lower())

    def test_solar_agent_is_visually_isolated_without_state_mutation(self):
        mode_source = _read(FRONTEND_ROOT / "js" / "01-progress-and-mode.js")
        self.assertIn("dashboard-mode-autonomy", mode_source)
        self.assertIn("autonomyTab", mode_source)
        self.assertIn("autonomyRenderWorkspace", mode_source)
        self.assertNotIn("renderAutonomyWorkspace()", mode_source)
        self.assertIn("agentSurface.setAttribute('aria-hidden', 'true')", mode_source)
        self.assertIn("agentSurface.setAttribute('inert', '')", mode_source)
        self.assertIn("agentSurface.removeAttribute('aria-hidden')", mode_source)
        self.assertIn("agentSurface.removeAttribute('inert')", mode_source)

        solar_controls = {
            ".floating-chat-btn": "#chatToggle",
            ".sidebar": "#chatSidebar",
        }
        for class_selector, id_selector in solar_controls.items():
            class_name = class_selector.removeprefix(".")
            element_id = id_selector.removeprefix("#")
            self.assertRegex(
                self.all_markup,
                rf"(?is)<[^>]*(?=[^>]*\bclass=['\"][^'\"]*\b{re.escape(class_name)}\b)(?=[^>]*\bid=['\"]{re.escape(element_id)}['\"])[^>]*>",
            )
            self.assertRegex(
                self.all_styles,
                rf"dashboard-mode-autonomy\s+(?:{re.escape(class_selector)}|{re.escape(id_selector)})",
            )
        self.assertRegex(
            self.all_styles,
            r"(?s)dashboard-mode-autonomy[^\{]*(?:floating-chat-btn|sidebar|chatToggle|chatSidebar)[^\{]*\{[^}]*display\s*:\s*none",
        )
        for solar_state in (
            "chatMessages",
            "chatConversations",
            "activeChatConversationId",
            "CHAT_HISTORY_STORAGE_KEY",
        ):
            self.assertNotIn(solar_state, self.script)

    def test_investigation_workspace_contains_the_full_manager_path(self):
        copy = self.combined.lower()
        for element_id in (
            "autonomyPanel",
            "autonomyCaseHeader",
            "autonomyInvestigationView",
            "autonomyEvidenceRail",
        ):
            self.assertEqual(self.assembled.count(f'id="{element_id}"'), 1)
        for label in (
            "investigation workspace",
            "decision agent",
            "ask",
            "verify evidence",
            "compare scenarios",
            "run tea",
            "decide",
            "calibration",
            "annual source",
            "weather coverage",
            "tea evidence",
            "evidence",
            "assumptions",
            "readiness",
            "provenance",
            "measured fact",
            "model result",
            "accepted assumption",
            "public evidence",
            "agent interpretation",
        ):
            with self.subTest(label=label):
                self.assertIn(label, copy)

    def test_decision_brief_contains_outcomes_reversals_and_signoff(self):
        copy = self.combined.lower()
        self.assertEqual(self.assembled.count('id="autonomyDecisionBrief"'), 1)
        self.assertEqual(self.assembled.count('id="autonomySignoffDialog"'), 1)
        for label in (
            "decision brief",
            "recommendation",
            "confidence",
            "p5",
            "p50",
            "p95",
            "lifecycle cost",
            "lifecycle energy",
            "sensitivity",
            "reversal",
            "evidence completeness",
            "caveats",
            "decision timeline",
            "accept",
            "reject",
            "defer",
            "rationale",
        ):
            with self.subTest(label=label):
                self.assertIn(label, copy)

    def test_fixture_selector_and_live_status_are_accessibly_described(self):
        self.assertRegex(
            self.markup,
            r"(?is)<select(?=[^>]*(?:fixture|state))(?=[^>]*(?:aria-describedby|aria-label|id=))[^>]*>",
        )
        self.assertRegex(
            self.combined,
            r"(?is)aria-live\s*=\s*['\"]polite['\"]",
        )
        self.assertEqual(
            len(re.findall(r"(?is)aria-live\s*=\s*['\"]polite['\"]", self.markup)),
            1,
        )
        self.assertIn("local preview", self.combined.lower())

    def test_tabs_steps_tables_and_dialogs_have_screen_reader_semantics(self):
        for pattern in (
            r"role\s*=\s*['\"]tablist['\"]",
            r"role\s*=\s*['\"]tab['\"]",
            r"role\s*=\s*['\"]tabpanel['\"]",
            r"aria-current['\"\s,=(]+step",
            r"<table\b",
            r"<th(?=[^>]*scope\s*=\s*['\"]col['\"])[^>]*>",
            r"(?:<dialog\b|role\s*=\s*['\"]dialog['\"])",
            r"(?:\.showModal\s*\(|aria-modal['\"\s,=(]+true)",
        ):
            with self.subTest(pattern=pattern):
                self.assertRegex(self.combined, rf"(?is){pattern}")
        self.assertGreaterEqual(len(re.findall(r"(?is)<table\b", self.combined)), 5)

    def test_keyboard_tabs_modal_focus_trap_and_restore_are_implemented(self):
        for key in ("ArrowLeft", "ArrowRight", "Home", "End", "Enter", "Escape"):
            self.assertIn(key, self.script)
        self.assertRegex(self.script, r"(?i)(?:['\"] ['\"]|space)")
        self.assertRegex(
            self.script,
            r"(?i)(?:key\s*(?:===?|!==?)\s*['\"]Tab['\"]|case\s+['\"]Tab['\"])",
        )
        self.assertIn("document.activeElement", self.script)
        self.assertRegex(self.script, r"\.focus\s*\(")
        self.assertIn("dialog?.open", self.script)
        self.assertIn("autonomyCloseDialog(autonomyOpenModal)", self.script)
        self.assertIn(
            "autonomyCloseRailBtn?.focus({preventScroll: true})",
            self.script,
        )
        self.assertRegex(
            self.script,
            r"(?i)(?:return|restore)[A-Za-z0-9_$]*(?:focus|trigger)|(?:focus|trigger)[A-Za-z0-9_$]*(?:return|restore)",
        )
        self.assertRegex(
            self.markup,
            r"(?is)<textarea(?=[^>]*\bid=['\"]autonomyAgentComposer['\"])[^>]*>",
        )
        self.assertRegex(
            self.markup,
            r"(?is)<button(?=[^>]*\bid=['\"]autonomyAgentSendBtn['\"])(?=[^>]*\btype=['\"]button['\"])[^>]*>",
        )
        stage_panels = re.findall(
            r"(?is)<section(?=[^>]*\bdata-autonomy-stage-panel=)(?=[^>]*\btabindex=['\"]-1['\"])[^>]*>",
            self.markup,
        )
        self.assertEqual(len(stage_panels), 5)

    def test_desktop_tablet_and_mobile_layout_contracts_are_present(self):
        compact = re.sub(r"\s+", " ", self.styles)
        self.assertRegex(
            compact,
            r"grid-template-columns:\s*320px\s+minmax\(0,\s*1fr\)\s+320px",
        )
        self.assertRegex(compact, r"@media[^\{]*max-width:\s*1279px")
        self.assertRegex(compact, r"@media[^\{]*max-width:\s*767px")
        self.assertRegex(
            compact,
            r"(?i)(?:evidence|rail)[^\{]*\{[^}]*(?:position:\s*fixed|display:\s*none)",
        )
        self.assertRegex(compact, r"min-(?:height|width):\s*44px")
        self.assertRegex(compact, r"font-size:\s*16px")
        self.assertIn("overflow-x", compact)
        self.assertRegex(
            compact,
            r"\.autonomy-shell\s*\{[^}]*min-width:\s*0",
        )
        self.assertIn("max-width: 100%", compact)
        for mobile_section in ("ask", "scenarios", "evidence", "decision"):
            self.assertIn(f'data-mobile-section="{mobile_section}"', self.combined)
        self.assertIn(
            "section === 'decision' && !autonomyCanOpenBrief",
            self.script,
        )

    def test_reduced_motion_and_forced_colors_are_honored(self):
        compact = re.sub(r"\s+", " ", self.styles)
        self.assertRegex(
            compact,
            r"@media\s*\(prefers-reduced-motion:\s*reduce\)",
        )
        self.assertRegex(compact, r"@media\s*\(forced-colors:\s*active\)")

    def test_confirmation_and_signoff_preserve_the_human_authority_boundary(self):
        self.assertIn("autonomyFixtureId !== 'ready-to-confirm'", self.script)
        self.assertIn("[data-autonomy-confirm-scenario]:checked", self.script)
        self.assertIn("selectedScenarios === 0", self.script)
        self.assertIn("autonomyCurrentFixture().signoffAllowed", self.script)
        self.assertIn(
            "autonomySignedDecision = {disposition: disposition.value, owner, rationale}",
            self.script,
        )
        self.assertIn("autonomySignedDecisionSummary()", self.script)
        self.assertIn("data-autonomy-confirm-scenario", self.all_markup)

    def test_empty_partial_and_signed_states_do_not_expose_contradictory_controls(self):
        self.assertIn("data-autonomy-case-workspace", self.all_markup)
        self.assertIn(
            "element.hidden = !fixture.caseExists",
            self.script,
        )
        self.assertIn("data-autonomy-partial-only", self.all_markup)
        self.assertIn("data-autonomy-complete-results", self.all_markup)
        for class_name in (
            "autonomy-recommendation-hero",
            "autonomy-brief-lower-grid",
        ):
            self.assertRegex(
                self.all_markup,
                rf'<section class="{class_name}"[^>]*data-autonomy-complete-results',
            )
        self.assertIn("fixture.briefState === 'partial'", self.script)
        self.assertIn("autonomyCaseTitle.disabled", self.script)
        self.assertIn("autonomyEvidenceRationale.disabled", self.script)
        self.assertIn("Unavailable — no value displayed", self.all_markup)

    def test_fixture_controls_have_local_handlers_and_mobile_state_stays_synchronized(self):
        for hook in (
            "data-autonomy-case-action",
            "data-autonomy-source",
            "data-autonomy-prompt",
            "data-autonomy-proposal-action",
            "data-autonomy-attach-evidence",
            "autonomyEvidenceReviewBtn",
        ):
            self.assertIn(hook, self.script)
        self.assertIn("autonomySyncMobileTabs", self.script)
        self.assertIn("autonomyMobileSectionForStage", self.script)
        self.assertIn("candidate.getAttribute('aria-disabled') !== 'true'", self.script)
        self.assertIn('aria-controls="autonomyDecisionBrief"', self.all_markup)

    def test_shared_source_and_revision_are_consistent_across_both_views(self):
        self.assertNotIn("annual_7f31", self.combined)
        self.assertIn("AUTONOMY_ANNUAL_SOURCE_ID", self.script)
        self.assertIn('data-autonomy-case-revision="revision_003"', self.all_markup)
        self.assertIn("Revision 3 · shared fixture identity", self.combined)
        self.assertIn("revision 3 · ann_2024_verified_017", self.combined.lower())
        self.assertIn("autonomyCaseRevision.textContent", self.script)

    @unittest.skipUnless(shutil.which("node"), "Node.js is required")
    def test_complete_classic_script_parses_in_node(self):
        self.assertNotRegex(self.script, r"(?m)^\s*(?:import|export)\b")
        completed = subprocess.run(
            [shutil.which("node"), "--check", "-"],
            input=self.all_scripts,
            encoding="utf-8",
            capture_output=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)


class AutonomyProductContractDocs(unittest.TestCase):
    def test_versioned_product_contracts_are_preserved_under_docs(self):
        contracts = {
            "UNIFIED_AUTONOMY_TEA_PRODUCT_CONTRACT_V1.md": (
                "approved unified autonomy/tea plan",
                "architecture and end-state product boundary",
            ),
            "HYBRID_AUTONOMY_WORKSPACE_PRODUCT_CONTRACT_V1.md": (
                "approved hybrid autonomy workspace plan",
                "controlling interaction and frontend-phase contract",
            ),
        }
        for filename, (source, authority) in contracts.items():
            with self.subTest(contract=filename):
                path = PROJECT_ROOT / "docs" / filename
                self.assertTrue(path.is_file())
                content = _read(path).lower()
                self.assertIn("status: approved", content)
                self.assertIn("contract version: 1.0", content)
                self.assertIn("preserved in repository: 2026-08-27", content)
                self.assertIn(source, content)
                self.assertIn(authority, content)

    def test_frontend_foundation_contract_fixes_phase_and_authority_boundaries(self):
        path = PROJECT_ROOT / "docs" / "HYBRID_AUTONOMY_FRONTEND_FOUNDATION_V1.md"
        self.assertTrue(path.is_file())
        content = _read(path).lower()
        normalized = re.sub(r"\s+", " ", content)
        for marker in (
            "status: **approved implementation contract**",
            "version: **1.0**",
            "phase 0 and phase 1 only",
            "all autonomy data in phase 1 is deterministic local fixture data",
            "never calls `fetch`",
            "no decision agent",
            "decision-case persistence",
            "evidence storage",
            "scenario execution api",
            "tea calculation change",
            "explicit phase 2 handoff boundary",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, normalized)
        self.assertIn("or tea calculation change is authorized", normalized)

    def test_written_hybrid_contract_wins_and_existing_systems_stay_unchanged(self):
        foundation = _read(
            PROJECT_ROOT / "docs" / "HYBRID_AUTONOMY_FRONTEND_FOUNDATION_V1.md"
        ).lower()
        normalized = re.sub(r"\s+", " ", foundation)
        self.assertIn("written hybrid plan and existing dashboard visual language win", normalized)
        for protected in (
            "calibration",
            "annual simulation",
            "existing tea",
            "exports",
            "workers",
            "saved results",
            "solar agent",
        ):
            with self.subTest(protected=protected):
                self.assertIn(protected, normalized)


if __name__ == "__main__":
    unittest.main()
