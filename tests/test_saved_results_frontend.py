from __future__ import annotations

import shutil
import subprocess
import unittest
from pathlib import Path

from sbepv import dashboard


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class SavedResultsFrontendTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.html = dashboard.assemble_dashboard_html(PROJECT_ROOT)
        cls.script_path = PROJECT_ROOT / "frontend" / "js" / "20-saved-results.js"
        cls.script = cls.script_path.read_text(encoding="utf-8")
        cls.styles = (
            PROJECT_ROOT / "frontend" / "css" / "15-saved-results-drawer.css"
        ).read_text(encoding="utf-8")
        cls.api_route = (
            PROJECT_ROOT / "app" / "api" / "[...path]" / "route.ts"
        ).read_text(encoding="utf-8")
        cls.render_proxy = (
            PROJECT_ROOT / "lib" / "render-proxy.ts"
        ).read_text(encoding="utf-8")

    def test_launchers_and_drawer_contract_are_assembled_once(self) -> None:
        for element_id in (
            "savedResultsNavBtn",
            "saveValidationResultBtn",
            "saveAnnualResultBtn",
            "savedResultsBackdrop",
            "savedResultsDrawer",
            "savedResultsCloseBtn",
            "savedResultsCount",
            "savedResultsList",
            "savedResultsLive",
        ):
            self.assertEqual(self.html.count(f'id="{element_id}"'), 1, element_id)
        self.assertIn('role="dialog" aria-modal="true"', self.html)
        self.assertIn('role="tablist" aria-label="Filter saved results"', self.html)
        self.assertIn('data-saved-results-filter="validation"', self.html)
        self.assertIn('data-saved-results-filter="annual"', self.html)

    def test_save_actions_follow_export_and_precede_run(self) -> None:
        validation_actions = self.html.split(
            '<div class="control-actions">', 2
        )[-1].split("</div>", 1)[0]
        self.assertLess(validation_actions.index('id="excelLink"'), validation_actions.index('id="saveValidationResultBtn"'))
        self.assertLess(validation_actions.index('id="saveValidationResultBtn"'), validation_actions.index('id="runBtn"'))

        annual_actions = self.html.split('id="annualActionCopy"', 1)[1].split("</section>", 1)[0]
        self.assertLess(annual_actions.index('id="annualExcelLink"'), annual_actions.index('id="saveAnnualResultBtn"'))
        self.assertLess(annual_actions.index('id="saveAnnualResultBtn"'), annual_actions.index('id="annualRunBtn"'))

    def test_saved_results_use_durable_rest_contract_and_get_only_restore(self) -> None:
        self.assertIn("'/api/saved-results'", self.script)
        self.assertIn("'/api/saved-results/' + encodeURIComponent", self.script)
        self.assertIn("method: 'POST'", self.script)
        self.assertIn("method: 'PUT'", self.script)
        self.assertIn("method: 'DELETE'", self.script)
        self.assertIn("body: JSON.stringify({ name: defaultName })", self.script)
        self.assertIn("body: JSON.stringify({ name: name.slice(0, 120) })", self.script)
        self.assertIn("const loaded = await viewAgentJobResults(item.job_id, mode)", self.script)
        self.assertNotIn("/api/run", self.script)
        self.assertNotIn("/api/annual-run", self.script)

    def test_cloudflare_proxy_supports_saved_results_methods_and_paths(self) -> None:
        for method in ("GET", "POST", "PUT", "DELETE"):
            self.assertIn(f"export const {method} = proxy;", self.api_route)
        self.assertIn('"saved-results",', self.render_proxy)
        self.assertIn(
            '(path[0] === "saved-results" && isSafeId(path[1]))',
            self.render_proxy,
        )

    def test_default_titles_and_maximum_are_user_facing(self) -> None:
        self.assertIn("const MAX_SAVED_RESULTS = 10", self.script)
        self.assertIn("'Annual · '", self.script)
        self.assertIn("request.calibrate_model === false ? 'Model' : 'Calibration'", self.script)
        self.assertIn("workflow + ' · ' + windowLabel", self.script)
        self.assertNotIn("return job.job_id", self.script)
        self.assertIn("0 of 10 saved", self.html)

    def test_modal_focus_and_agent_mutual_exclusion_are_wired(self) -> None:
        for hook in (
            "setChatOpen(false, { focus: false, persist: false })",
            "dashboardShell.toggleAttribute('inert', open)",
            "document.body.classList.toggle('saved-results-open', open)",
            "if (event.key === 'Escape')",
            "if (event.key !== 'Tab') return",
            "savedResultsReturnFocus",
            "window.savedResultsDrawerReady = true",
        ):
            self.assertIn(hook, self.script)
        self.assertIn("width: 100vw", self.styles)
        self.assertIn("@media (max-width: 560px)", self.styles)
        self.assertIn("@media (prefers-reduced-motion: reduce)", self.styles)
        mobile = self.styles.split("@media (max-width: 560px)", 1)[1].split(
            "@media (prefers-reduced-motion: reduce)", 1
        )[0]
        for selector in (
            ".saved-results-nav-btn",
            ".save-results-btn",
            ".saved-result-menu-action",
            ".saved-result-export",
        ):
            self.assertIn(selector, mobile)
        self.assertIn("min-height: 44px", mobile)

    def test_selection_refresh_and_mutations_are_race_safe(self) -> None:
        self.assertIn("function reconcileSavedResultsSelection()", self.script)
        self.assertIn("card.classList.toggle('selected', selected)", self.script)
        self.assertIn("savedResultsRefreshPromise", self.script)
        self.assertIn("savedResultsMutationRevision", self.script)
        self.assertIn("mutationRevisionAtStart !== savedResultsMutationRevision", self.script)
        self.assertIn("await refreshSavedResults({ force: true })", self.script)
        self.assertIn("focusSavedResultControl", self.script)
        self.assertIn("focusSavedResultsFallback", self.script)
        self.assertGreaterEqual(
            self.script.count(
                "savedResultsBusyJobId = null;\n                renderSavedResults();"
            ),
            3,
        )

    def test_opening_saved_history_does_not_reorder_recent_run_history(self) -> None:
        restore_source = (
            PROJECT_ROOT / "frontend" / "js" / "18-agent-actions.js"
        ).read_text(encoding="utf-8").split(
            "async function viewAgentJobResults", 1
        )[1].split("function handleAgentAction", 1)[0]
        self.assertIn("putAgentJob(job, { recordTerminal: false })", restore_source)
        self.assertIn("return true", restore_source)
        self.assertGreaterEqual(restore_source.count("return false"), 3)
        cache_restore_source = (
            PROJECT_ROOT / "frontend" / "js" / "19-chat-send-and-cache.js"
        ).read_text(encoding="utf-8").split(
            "async function revalidateCachedCompletedRun", 1
        )[1].split("async function restoreDashboardState", 1)[0]
        self.assertIn("putAgentJob(data, { recordTerminal: false })", cache_restore_source)

    def test_legacy_annual_saved_result_keeps_displayed_selection_context(self) -> None:
        self.assertIn(
            "const savedResultsViewedJobIds = { validation: null, annual: null }",
            self.script,
        )
        self.assertIn("const readOnlyJobId = savedResultsViewedJobIds.annual", self.script)
        self.assertIn("!annualLatestJobId && !annualRunState", self.script)
        self.assertIn("savedResultsViewedJobIds[mode] = item.job_id", self.script)
        self.assertIn("const savedResultsRestoredJobs = { validation: null, annual: null }", self.script)
        self.assertIn("function getSavedResultsDisplayedContext()", self.script)
        self.assertIn("function restoreSavedResultsDisplayedContext(context)", self.script)
        self.assertIn("applyAnnualResult(legacyAnnual.result, false)", self.script)
        restored_block = self.script.split(
            "function restoreSavedResultsDisplayedContext(context)", 1
        )[1].split("function resetSavedResultsDisplayedJobs", 1)[0]
        apply_guard = restored_block.split("applyAnnualResult(legacyAnnual.result, false)", 1)[0]
        self.assertNotIn("activeView === 'annual'", apply_guard)
        self.assertIn(
            "window.clearSavedResultsDisplayedJob = clearSavedResultsDisplayedJob",
            self.script,
        )
        dashboard_state = (PROJECT_ROOT / "frontend" / "js" / "08-dashboard-state.js").read_text(encoding="utf-8")
        cache_restore = (PROJECT_ROOT / "frontend" / "js" / "19-chat-send-and-cache.js").read_text(encoding="utf-8")
        self.assertIn("savedResultsDisplayedContext: window.getSavedResultsDisplayedContext?.()", dashboard_state)
        self.assertIn("window.resetSavedResultsDisplayedJobs?.()", dashboard_state)
        self.assertIn("window.restoreSavedResultsDisplayedContext?.(saved.savedResultsDisplayedContext)", cache_restore)
        annual_run = (PROJECT_ROOT / "frontend" / "js" / "10-annual-run.js").read_text(encoding="utf-8")
        validation_run = (PROJECT_ROOT / "frontend" / "js" / "09-validation-run.js").read_text(encoding="utf-8")
        self.assertIn("window.clearSavedResultsDisplayedJob?.('annual')", annual_run)
        self.assertIn("window.clearSavedResultsDisplayedJob?.('validation')", validation_run)

    def test_saved_run_delete_is_suppressed_and_conflicts_render_in_runs(self) -> None:
        cards = (
            PROJECT_ROOT / "frontend" / "js" / "16-proposal-and-job-cards.js"
        ).read_text(encoding="utf-8")
        actions = (
            PROJECT_ROOT / "frontend" / "js" / "18-agent-actions.js"
        ).read_text(encoding="utf-8")
        self.assertIn("window.savedResultsDrawerReady === true", cards)
        self.assertIn("savedResultByJobId(job.job_id)", cards)
        self.assertIn("savedNotice.textContent = 'Saved result'", cards)
        self.assertIn("client_action_error", cards)
        self.assertIn("client_action_error: message", actions)

    @unittest.skipUnless(shutil.which("node"), "Node.js is required")
    def test_saved_results_script_parses_in_node(self) -> None:
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
