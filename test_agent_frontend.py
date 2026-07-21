import re
import unittest
from pathlib import Path


class AgentFrontendContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = Path("sb_energy_dashboard_modern.html").read_text(encoding="utf-8")
        cls.proxy = Path("lib/render-proxy.ts").read_text(encoding="utf-8")

    def test_chat_sends_mode_and_canonical_visible_configuration(self):
        self.assertIn("active_mode: activeMode", self.html)
        self.assertIn("current_config: getCanonicalCurrentConfig(activeMode)", self.html)
        for field in (
            "from_date",
            "to_date",
            "backtrack",
            "curtailment_enabled",
            "curtailment_limit_kw",
            "solaredge_inverter_efficiency",
            "solaredge_bos_efficiency",
            "solectria_inverter_efficiency",
            "solectria_bos_efficiency",
            "iam_model",
            "iam_a_r",
            "interval_value",
            "interval_unit",
        ):
            self.assertIn(field, self.html)

    def test_agent_cards_and_accessible_context_are_present(self):
        for element_id in (
            "agentContextBadge",
            "agentContextText",
            "agentActivity",
            "agentActivityList",
            "agentActivityBody",
            "agentActivitySummary",
            "agentActivityBack",
            "agentRefreshBtn",
        ):
            self.assertIn(f'id="{element_id}"', self.html)
        self.assertIn('role="dialog"', self.html)
        self.assertIn('role="log" aria-live="polite"', self.html)
        self.assertIn('for="chatInput"', self.html)
        self.assertRegex(self.html, r'<textarea[^>]+id="chatInput"')
        self.assertIn("e.key === 'Enter' && !e.shiftKey", self.html)
        self.assertIn("event.key === 'Escape'", self.html)

    def test_proposal_lifecycle_and_job_controls_use_public_endpoints(self):
        expected_fragments = (
            "/api/agent/state",
            "/api/agent/proposals/",
            "/confirm",
            "/edit",
            "/dismiss",
            "/api/jobs/",
            "/cancel",
            "/retry",
            "/promote",
        )
        for fragment in expected_fragments:
            self.assertIn(fragment, self.html)
        self.assertIn("{ overrides }", self.html)
        self.assertIn("Promote to baseline", self.html)

    def test_errors_are_system_notices_and_are_not_saved_as_assistant_history(self):
        catch_block = re.search(
            r"catch \(e\) \{\s*const msg = e\.message.*?\n\s*\} finally",
            self.html,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(catch_block)
        self.assertIn("loadingBubble.parentElement.remove()", catch_block.group(0))
        self.assertIn("appendSystemNotice(msg, 'error')", catch_block.group(0))
        self.assertNotIn("chatMessages.push", catch_block.group(0))

    def test_agent_state_restores_and_active_jobs_resume_polling(self):
        self.assertIn("await refreshAgentState(false)", self.html)
        self.assertIn("scheduleAgentJobPoll(job.job_id", self.html)
        self.assertIn("setInterval(updateAgentElapsedLabels, 1000)", self.html)
        self.assertIn("captureAgentEditorState", self.html)
        self.assertIn("restoreAgentEditorState", self.html)
        self.assertIn("renderAgentJobUpdate(data)", self.html)
        self.assertNotIn("ETA", self.html)

    def test_completed_candidate_gets_one_time_engineering_explanation(self):
        self.assertIn("requestAgentCompletionExplanation(data, false)", self.html)
        self.assertIn("Explain results", self.html)
        self.assertIn("agentExplainedJobs", self.html)
        self.assertIn("suggest one or two useful follow-up experiments without running them", self.html)
        self.assertIn("Do not call any tools or create a proposal", self.html)
        self.assertIn("allow_scenario_actions: false", self.html)

    def test_comparison_reports_and_promotion_render_without_mutating_forms_first(self):
        for hook in (
            "buildComparisonCard",
            "comparison_type",
            "cross_system_gap",
            "absolute_error_improvement_pp",
            "Comparison integrity checks",
            "buildProvenanceDetails",
            "collectArtifactLinks",
            "Promote to baseline",
            "applyPromotedRequest",
        ):
            self.assertIn(hook, self.html)
        promote_function = re.search(
            r"async function promoteAgentJob\(jobId\) \{(.*?)\n\s*\}",
            self.html,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(promote_function)
        body = promote_function.group(1)
        self.assertLess(body.index("await postAgentAction"), body.index("applyPromotedRequest"))

    def test_customer_facing_chat_shell_and_trust_copy_are_present(self):
        for element_id in (
            "newChatBtn",
            "minimizeChat",
            "agentActivityToggle",
            "agentActivityCount",
            "chatComposerStatus",
        ):
            self.assertIn(f'id="{element_id}"', self.html)
        self.assertIn('aria-controls="chatSidebar"', self.html)
        self.assertIn('aria-haspopup="dialog"', self.html)
        self.assertIn("Ask Solar Agent", self.html)
        self.assertIn("Performance insights &amp; guided scenarios", self.html)
        self.assertIn("Turn solar data into clear decisions", self.html)
        self.assertIn("Scenario results stay separate until you promote them.", self.html)
        self.assertNotIn("Model runs always need your approval", self.html)

    def test_minimize_collapses_chat_without_clearing_conversation(self):
        self.assertIn(
            'aria-label="Minimize Solar Agent to view dashboard charts"', self.html
        )
        self.assertIn(
            "minimizeChat.addEventListener('click', () => setChatOpen(false))",
            self.html,
        )
        self.assertIn("chatToggle.classList.toggle('hidden', open)", self.html)
        self.assertIn("saveDashboardState()", self.html)

    def test_visible_context_names_physical_iam_explicitly(self):
        self.assertIn("const visibleIamModel = getCanonicalCurrentConfig(activeMode).iam_model", self.html)
        self.assertIn("'Physical IAM'", self.html)
        self.assertIn("'Martin–Ruiz IAM'", self.html)

    def test_guided_prompts_new_conversation_and_draft_persistence_are_wired(self):
        self.assertIn("data-chat-prompt", self.html)
        self.assertIn("prefillChatPrompt", self.html)
        self.assertIn("function startNewChat()", self.html)
        self.assertIn("function autoResizeChatInput()", self.html)
        self.assertIn("chatDraft,", self.html)
        self.assertIn("saved.chatDraft", self.html)
        self.assertIn("e.isComposing", self.html)
        self.assertRegex(self.html, r'<textarea[^>]+id="chatInput"[^>]+maxlength="4000"')

        start_new = re.search(
            r"function startNewChat\(\) \{(.*?)\n\s*\}",
            self.html,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(start_new)
        body = start_new.group(1)
        self.assertIn("chatMessages = [{ role: 'assistant'", body)
        self.assertNotIn("agentProposalSnapshots.clear", body)
        self.assertNotIn("agentJobSnapshots.clear", body)

    def test_run_workspace_and_accessible_loading_state_are_wired(self):
        self.assertIn('aria-controls="agentActivity"', self.html)
        self.assertIn("function setAgentActivityOpen(open, persist = true)", self.html)
        self.assertIn("agentActivityExpanded", self.html)
        self.assertIn("chatSidebar.classList.toggle('activity-view'", self.html)
        self.assertIn('data-agent-activity-filter="review"', self.html)
        self.assertIn("syncAgentActivityControls", self.html)
        self.assertIn("setAgentActivityOpen(true)", self.html)
        self.assertIn("{ loading: true }", self.html)
        self.assertIn("messagesContainer.setAttribute('aria-busy'", self.html)
        self.assertNotIn("chatInput.disabled = isSending", self.html)

    def test_run_history_uses_compact_rows_and_one_on_demand_detail(self):
        for hook in (
            "function summarizeAgentRequest(entry)",
            "function sortAgentActivityItems(items)",
            "function buildAgentRunSummary(entry)",
            "summary.dataset.agentRunRow = entry.key",
            "agent-run-mini-progress",
            "agent-run-detail",
            "if (selected)",
        ):
            self.assertIn(hook, self.html)
        self.assertIn("summary.setAttribute('aria-expanded', String(selected))", self.html)
        self.assertIn("summary.setAttribute('aria-controls', detailId)", self.html)
        self.assertIn("detail.appendChild(entry.type === 'proposal' ? buildProposalCard(entry.item) : buildJobCard(entry.item))", self.html)
        self.assertIn("if (agentActivitySelection)", self.html)

    def test_run_summaries_surface_windows_values_and_deterministic_priority(self):
        self.assertIn("function compactAgentRunWindow(request, mode)", self.html)
        self.assertIn("mode === 'validation' && config.from_time && config.to_time", self.html)
        self.assertIn("agentRunChangedValues(entry, request)", self.html)
        self.assertIn("Backtracking ", self.html)
        self.assertIn("Curtailment ", self.html)
        self.assertIn("IAM ", self.html)
        self.assertIn("if (entry.type === 'proposal') return 0", self.html)
        self.assertIn("if (entry.item?.state === 'running') return 1", self.html)
        self.assertIn("if (entry.item?.state === 'queued') return 2", self.html)

    def test_run_counts_come_from_state_and_job_start_does_not_force_workspace_open(self):
        sync_block = re.search(
            r"function syncAgentActivityControls\(.*?\) \{(.*?)\n\s*\}\n\n\s*function renderAgentActivity",
            self.html,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(sync_block)
        self.assertNotIn("childElementCount", sync_block.group(1))
        self.assertIn("runningCount", sync_block.group(1))
        self.assertIn("queuedCount", sync_block.group(1))

        job_started = self.html.index("if (action.type === 'job_started' && action.job)")
        next_function = self.html.index("async function confirmAgentProposal", job_started)
        self.assertNotIn("setAgentActivityOpen(true)", self.html[job_started:next_function])

    def test_run_workspace_state_and_scroll_survive_refreshes(self):
        for hook in (
            "agentActivityFilter,",
            "agentActivitySelection,",
            "saved.agentActivityFilter",
            "saved.agentActivitySelection",
            "const activityScrollTop = agentActivityBody.scrollTop",
            "agentActivityBody.scrollTop = activityScrollTop",
        ):
            self.assertIn(hook, self.html)

    def test_mobile_chat_uses_full_screen_layout_and_modal_focus_management(self):
        self.assertIn("height: 100dvh", self.html)
        self.assertIn("body.chat-open", self.html)
        self.assertIn("chatSidebar.setAttribute('aria-modal', 'true')", self.html)
        self.assertIn("dashboardShell.toggleAttribute('inert', modal)", self.html)
        self.assertIn("dashboardShell.inert = modal", self.html)
        self.assertIn("dashboardShell.setAttribute('aria-hidden', 'true')", self.html)
        self.assertIn("event.key === 'Tab' && isChatMobile()", self.html)
        self.assertIn("font-size: 16px", self.html)

    def test_header_icons_share_the_visible_svg_treatment(self):
        self.assertIn(".header-icon-btn svg,\n        .close-btn svg,", self.html)

    def test_proxy_allows_only_the_new_nested_agent_routes(self):
        for route in (
            'path[0] === "agent" && path[1] === "state"',
            'path[0] === "jobs"',
            '["cancel", "promote", "retry"]',
            'path[1] === "proposals"',
            '["confirm", "edit", "dismiss"]',
        ):
            self.assertIn(route, self.proxy)
        self.assertIn("isSafeId(path[1])", self.proxy)
        self.assertIn("isSafeId(path[2])", self.proxy)


if __name__ == "__main__":
    unittest.main()
