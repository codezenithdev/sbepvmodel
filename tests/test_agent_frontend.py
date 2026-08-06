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
            "calibrate_model",
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
            "/delete",
            "/promote",
        )
        for fragment in expected_fragments:
            self.assertIn(fragment, self.html)
        self.assertIn("{ overrides }", self.html)
        self.assertIn("Promote to baseline", self.html)
        self.assertIn("Delete run", self.html)
        self.assertIn("deleteAgentJob", self.html)
        self.assertIn("const isBaselineRun = ['baseline', 'manual'].includes(job.kind)", self.html)

    def test_direct_run_and_lazy_review_rows_are_allowed_by_render_proxy(self):
        route = re.search(
            r"function isAllowedApiPath\(path: string\[\]\): boolean \{(.*?)\n\}",
            self.proxy,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(route)
        assert route is not None
        route_source = route.group(1)
        self.assertRegex(
            route_source,
            r'path\.length === 1[\s\S]*?"run"[\s\S]*?"calibration-reviews"',
        )
        self.assertIn(
            'path[0] === "calibration-reviews"',
            route_source,
        )
        self.assertIn('["run", "rows"].includes(path[2])', route_source)
        self.assertIn("isSafeId(path[1])", route_source)
        self.assertIn("/api/calibration-reviews", self.html)
        self.assertIn("+ '/rows?' + query.toString()", self.html)

    def test_bazefield_review_collapse_state_and_receipt_survive_restore(self):
        self.assertIn("let calibrationReviewCollapsed", self.html)
        save_block = self.html.split("function saveDashboardState(options = {})", 1)[1].split(
            "\n        async function ",
            1,
        )[0]
        self.assertIn("calibrationReviewCollapsed", save_block)
        restore_block = self.html.split(
            "async function restoreDashboardState()",
            1,
        )[1].split("\n        document.querySelectorAll", 1)[0]
        self.assertIn("saved.calibrationReviewCollapsed", restore_block)
        self.assertIn(
            "pendingCalibrationReview = saved.pendingCalibrationReview || null",
            restore_block,
        )
        self.assertIn(
            "renderCalibrationReview(pendingCalibrationReview, { focusPanel: false })",
            restore_block,
        )
        self.assertIn("pendingCalibrationReview.applied", restore_block)
        self.assertIn(
            "setCalibrationReviewCollapsed(calibrationReviewCollapsed, { persist: false })",
            self.html,
        )

    def test_errors_are_system_notices_and_are_not_saved_as_assistant_history(self):
        send_message = self.html.split(
            "async function sendMessage()",
            1,
        )[1].split("\n        function clearCachedCompletedRun", 1)[0]
        catch_block = re.search(
            r"catch \(e\) \{.*?\n\s*\} finally",
            send_message,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(catch_block)
        self.assertIn("loadingBubble.parentElement.remove()", catch_block.group(0))
        self.assertIn("appendSystemNotice(msg, 'error')", catch_block.group(0))
        self.assertIn("e?.name === 'AbortError'", catch_block.group(0))
        self.assertIn("chatRequestTimedOut", catch_block.group(0))
        self.assertNotIn("chatMessages.push", catch_block.group(0))

    def test_ordinary_chat_job_context_is_not_misclassified_as_an_action(self):
        normalizer = self.html.split(
            "function normalizeAgentAction(data)",
            1,
        )[1].split("\n        function boundedChatCardString", 1)[0]
        for public_job_field in ("'state'", "'kind'", "'request'"):
            self.assertIn(
                f"Object.prototype.hasOwnProperty.call(data, {public_job_field})",
                normalizer,
            )
        self.assertNotRegex(
            normalizer,
            r"if\s*\(\s*data\.job_id\s*\)\s*return",
        )
        send_message = self.html.split(
            "async function sendMessage()",
            1,
        )[1].split("\n        function clearCachedCompletedRun", 1)[0]
        self.assertIn(
            "const startedJob = action?.type === 'job_started' ? action.job : null",
            send_message,
        )
        self.assertIn("if (startedJob?.job_id)", send_message)
        self.assertNotIn("if (data.job_id)", send_message)

    def test_direct_runs_register_immediately_and_poll_with_bounded_retries(self):
        for registration in (
            "registerDirectRun(payload.job_id, 'validation'",
            "registerDirectRun(data.job_id, 'validation'",
            "registerDirectRun(job_id, 'annual'",
        ):
            self.assertIn(registration, self.html)

        validation_poll = self.html.split(
            "async function pollStatus(jobId",
            1,
        )[1].split("\n        function resetAnnualRunBtn", 1)[0]
        annual_poll = self.html.split(
            "async function pollAnnualStatus(jobId",
            1,
        )[1].split("\n        runBtn.addEventListener", 1)[0]
        for poll, revision_name, current_id in (
            (validation_poll, "validationPollRevision", "latestJobId"),
            (annual_poll, "annualPollRevision", "annualLatestJobId"),
        ):
            self.assertIn(f"pollRevision !== {revision_name}", poll)
            self.assertIn(f"jobId !== {current_id}", poll)
            self.assertIn("res.status === 404", poll)
            self.assertIn("STATUS_POLL_MAX_FAILURES", poll)
            self.assertIn("statusPollRetryDelay(nextFailureCount)", poll)
            self.assertIn("cache: 'no-store'", poll)

    def test_agent_polling_stops_ghost_jobs_and_reconciles_restored_cards(self):
        poll = self.html.split(
            "async function pollAgentJob(jobId",
            1,
        )[1].split("\n        function trackedChatCardForJob", 1)[0]
        not_found = poll.split("if (response.status === 404)", 1)[1].split(
            "const data = await readAgentResponse",
            1,
        )[0]
        self.assertIn("forgetUnavailableAgentJob(jobId)", not_found)
        self.assertNotIn("scheduleAgentJobPoll", not_found)
        self.assertIn("AGENT_POLL_MAX_FAILURES", poll)

        reconcile = self.html.split(
            "function reconcileTerminalAgentCards()",
            1,
        )[1].split("\n        async function refreshAgentState", 1)[0]
        self.assertIn("updateStoredChatActionCardStatus", reconcile)
        self.assertIn("announceAgentCompletion", reconcile)
        self.assertIn("getAgentParameterSweepGroups()", reconcile)
        refresh = self.html.split(
            "async function refreshAgentState",
            1,
        )[1].split("\n        function handleAgentAction", 1)[0]
        self.assertIn("reconcileTerminalAgentCards()", refresh)

    def test_saved_nonterminal_action_cards_outside_recent_state_are_recovered(self):
        collector = self.html.split(
            "function savedNonterminalActionJobIds()",
            1,
        )[1].split("\n        function chatActionSweepMetadata", 1)[0]
        self.assertIn("['job_started', 'sweep_started'].includes(card.kind)", collector)
        self.assertIn("TERMINAL_CHAT_ACTION_STATUSES.has", collector)
        self.assertIn("card.job_id", collector)
        self.assertIn("...(card.job_ids || [])", collector)
        self.assertNotIn("baseline_job_id", collector)

        recovery = self.html.split(
            "async function recoverSavedNonterminalActionJobs()",
            1,
        )[1].split("\n        async function refreshAgentState", 1)[0]
        self.assertIn("!agentJobSnapshots.has(jobId)", recovery)
        self.assertIn("/api/status/", recovery)
        self.assertIn("response.status === 404", recovery)
        self.assertIn("forgetUnavailableAgentJob(jobId)", recovery)
        self.assertIn("putAgentJob", recovery)

        forget = self.html.split(
            "function forgetUnavailableAgentJob(jobId)",
            1,
        )[1].split("\n        async function pollAgentJob", 1)[0]
        self.assertIn("agentJobPollTimers.delete(jobId)", forget)
        self.assertIn("agentJobSnapshots.delete(jobId)", forget)
        self.assertIn("agentJobStartedAt.delete(jobId)", forget)
        self.assertIn(
            "updateStoredChatActionCardStatus({ job_id: jobId }, 'unavailable')",
            forget,
        )

        refresh = self.html.split(
            "async function refreshAgentState",
            1,
        )[1].split("\n        function handleAgentAction", 1)[0]
        self.assertLess(
            refresh.index("await recoverSavedNonterminalActionJobs()"),
            refresh.index("reconcileTerminalAgentCards()"),
        )
        self.assertIn("Array.from(agentJobSnapshots.values())", refresh)

    def test_cached_results_are_revalidated_before_restore(self):
        restore = self.html.split(
            "async function restoreDashboardState()",
            1,
        )[1].split("\n        document.querySelectorAll", 1)[0]
        validation_check = "revalidateCachedCompletedRun('validation')"
        annual_check = "revalidateCachedCompletedRun('annual')"
        self.assertIn(validation_check, restore)
        self.assertIn(annual_check, restore)
        self.assertLess(restore.index(validation_check), restore.index("applyResult(latestResult, false)"))
        self.assertLess(restore.index(annual_check), restore.index("applyAnnualResult(annualLatestResult, false)"))
        self.assertIn("['queued', 'running', 'monitoring_error']", restore)
        self.assertIn("markCachedRunUnverified(mode)", self.html)
        self.assertIn("saveDashboardState({ allowDuringHydration: true });", restore)

    def test_chat_requests_are_cancelable_and_external_sources_persist(self):
        send_message = self.html.split(
            "async function sendMessage()",
            1,
        )[1].split("\n        function clearCachedCompletedRun", 1)[0]
        for marker in (
            "new AbortController()",
            "CHAT_REQUEST_TIMEOUT_MS",
            "signal: chatController.signal",
            "activeChatAbortController",
            "chatController.abort()",
        ):
            self.assertIn(marker, send_message)
        self.assertIn("function cancelChatRequest()", self.html)
        self.assertIn("chatIsSending ? 'Cancel' : 'Send'", self.html)
        self.assertIn("collectExternalEvidence(content, data)", self.html)
        self.assertIn("message.web_sources = webSources", self.html)
        self.assertIn("restored.web_sources = restoredSources", self.html)
        self.assertIn("renderExternalEvidence(content, options)", self.html)

    def test_validation_happens_before_results_are_cleared_and_modes_are_isolated(self):
        for element_id in ("fromDate", "toDate", "annualFromDate", "annualToDate"):
            self.assertRegex(
                self.html,
                rf'<input(?=[^>]*\bid="{element_id}")(?=[^>]*\brequired\b)[^>]*>',
            )
        self.assertRegex(
            self.html,
            r'<input(?=[^>]*\bid="intervalValue")(?=[^>]*\bstep="1")'
            r'(?=[^>]*\binputmode="numeric")[^>]*>',
        )
        validation_run = self.html.split(
            "async function runAnalysis()",
            1,
        )[1].split("\n        async function applyCalibrationReview", 1)[0]
        self.assertLess(
            validation_run.index("readValidationWindow(fromTime, toTime)"),
            validation_run.index("latestResult = null"),
        )
        self.assertLess(
            validation_run.index("readPositiveInteger('intervalValue'"),
            validation_run.index("latestResult = null"),
        )
        annual_run = self.html.split(
            "async function runAnnualAnalysis()",
            1,
        )[1].split("\n        async function pollAnnualStatus", 1)[0]
        self.assertLess(
            annual_run.index("if (!fromDate || !toDate)"),
            annual_run.index("annualLatestResult = null"),
        )
        self.assertNotIn("parseInt(document.getElementById('intervalValue')", self.html)

        annual_controls = self.html.split(
            "document.querySelectorAll('#annualControls input, #annualControls select')",
            1,
        )[1].split("\n        restoreDashboardState();", 1)[0]
        self.assertNotIn("cancelCalibrationReview", annual_controls)

    def test_promotion_invalidates_stale_polls_and_retry_resets_elapsed_clock(self):
        promotion = self.html.split(
            "async function promoteAgentJob(jobId)",
            1,
        )[1].split("\n        function setChatOpen", 1)[0]
        self.assertLess(
            promotion.index("invalidateAnnualStatusPoll()"),
            promotion.index("applyPromotedRequest"),
        )
        self.assertLess(
            promotion.index("invalidateValidationStatusPoll()"),
            promotion.index("applyPromotedRequest"),
        )
        retry = self.html.split(
            "async function retryAgentJob(job)",
            1,
        )[1].split("\n        async function requestAgentCompletionExplanation", 1)[0]
        self.assertIn("agentJobStartedAt.set(retried.job_id, Date.now())", retry)

    def test_agent_state_restores_and_active_jobs_resume_polling(self):
        self.assertIn("await refreshAgentState(false)", self.html)
        self.assertIn("scheduleAgentJobPoll(job.job_id", self.html)
        self.assertIn("setInterval(updateAgentElapsedLabels, 1000)", self.html)
        self.assertIn("captureAgentEditorState", self.html)
        self.assertIn("restoreAgentEditorState", self.html)
        self.assertIn("renderAgentJobUpdate(data)", self.html)
        self.assertNotIn("ETA", self.html)

    def test_completed_runs_use_cards_and_engineering_explanation_is_opt_in(self):
        self.assertNotIn("requestAgentCompletionExplanation(data, false)", self.html)
        self.assertIn("announceAgentCompletion(data)", self.html)
        self.assertIn("buildRunCompletionChatCard", self.html)
        self.assertIn("appendAutomatedChatCardMessage", self.html)
        self.assertIn("Explain results", self.html)
        self.assertIn("agentExplainedJobs", self.html)
        self.assertIn("suggest one or two useful follow-up experiments without running them", self.html)
        self.assertIn("Do not call any tools or create a proposal", self.html)
        self.assertIn("allow_scenario_actions: false", self.html)

    def test_parameter_sweeps_render_one_live_comparison_and_grouped_actions(self):
        for hook in (
            "job_batch_started",
            "proposal_batch",
            "agentParameterSweepMetadata",
            "getAgentParameterSweepGroups",
            "buildParameterSweepComparisonCard",
            "sweep comparison",
            "SolarEdge kWh",
            "Solectria kWh",
            "Run sweep",
            "Dismiss sweep",
            "confirmAgentSweep",
            "buildSweepCompletionChatCard",
            "buildChatSweepChart",
            "Predicted energy by ",
            "Engineering details",
            "Open full comparison",
        ):
            self.assertIn(hook, self.html)
        self.assertIn("const completionKey = 'sweep:' + group.sweep_id", self.html)
        self.assertIn("agentCompletionCards.has(completionKey)", self.html)
        confirm_sweep = self.html.split(
            "async function confirmAgentSweep",
            1,
        )[1].split("\n        async function dismissAgentSweep", 1)[0]
        self.assertIn("'/api/agent/sweeps/'", confirm_sweep)
        self.assertIn("{ proposal_ids: proposalIds }", confirm_sweep)
        self.assertNotIn("for (const proposalId of proposalIds)", confirm_sweep)

    def test_action_replies_are_deterministic_compact_cards(self):
        for hook in (
            "function agentActionSummary(action)",
            "function buildChatActionCard(action)",
            "function renderChatActionCard(rawCard)",
            "const modelReply = data.reply",
            "const reply = action ? agentActionSummary(action) : modelReply",
            "renderMessageBubbleContent(loadingBubble, reply, { action_card: actionCard })",
            "if (!action) renderExternalEvidence(reply, data)",
            "data_review_required",
            "Open calibration form",
            "Open live comparison",
            "function updateStoredChatActionCardStatus(match, status, options = {})",
        ):
            self.assertIn(hook, self.html)
        self.assertIn("action_card: actionCard", self.html)
        self.assertIn("item.action_card", self.html)
        self.assertIn("rebuildAgentCompletionCardIndex()", self.html)
        self.assertIn("Live model update", self.html)

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
            (
                r"async function promoteAgentJob\(jobId\) \{(.*?)"
                r"\n\s*(?:async\s+)?function\s+\w+\("
            ),
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

    def test_solar_agent_prompt_uses_exact_new_copy(self):
        self.assertIn('placeholder="Ask Solar Agent…"', self.html)
        self.assertIn('title="Ask Solar Agent. Drag to move."', self.html)
        self.assertNotIn("Ask about this dashboard", self.html)

    def test_customer_copy_supports_optional_calibration_while_mode_stays_validation(self):
        for customer_copy in (
            ">Model Calibration</button>",
            ">Measured-data window</h3>",
            "calibrated ? 'Calibration results' : 'Model results'",
            'aria-label="Calibration efficiencies"',
            ">Calibration IAM model</legend>",
            'aria-label="System calibration summary"',
            "'Calibration'",
        ):
            self.assertIn(customer_copy, self.html)

        for retired_copy in (
            ">Model Validation</button>",
            ">Validation window</h3>",
            ">Validation results</h2>",
            'aria-label="Validation efficiencies"',
            ">Validation IAM model</legend>",
            'aria-label="System validation summary"',
            "'Validation'",
        ):
            self.assertNotIn(retired_copy, self.html)

        for internal_contract in (
            'id="validationTab"',
            "let activeMode = 'validation'",
            "switchMode('validation')",
            "activeMode === 'validation'",
            "validation: promoted.validation || null",
        ):
            self.assertIn(internal_contract, self.html)

    def test_help_tooltips_are_focusable_described_and_keyboard_visible(self):
        tooltip_ids = (
            "dashboardHelpTooltip",
            "calibrationHelpTooltip",
            "calibrationEfficiencyHelpTooltip",
            "solarAgentHelpTooltip",
        )
        for tooltip_id in tooltip_ids:
            with self.subTest(tooltip_id=tooltip_id):
                self.assertRegex(
                    self.html,
                    (
                        rf'<button\b'
                        rf'(?=[^>]*\bclass="help-tip")'
                        rf'(?=[^>]*\btype="button")'
                        rf'(?=[^>]*\baria-describedby="{tooltip_id}")'
                        rf'(?=[^>]*\baria-expanded="false")[^>]*>'
                    ),
                )
                self.assertRegex(
                    self.html,
                    (
                        rf'<span\b'
                        rf'(?=[^>]*\bclass="help-tooltip")'
                        rf'(?=[^>]*\bid="{tooltip_id}")'
                        rf'(?=[^>]*\brole="tooltip")[^>]*>'
                    ),
                )

        for interaction_hook in (
            ".help-tip-wrap:hover .help-tooltip",
            ".help-tip:focus-visible + .help-tooltip",
            '.help-tip[aria-expanded="true"] + .help-tooltip',
            "helpTipButtons.forEach((button) => {",
            "event.key !== 'Escape'",
        ):
            self.assertIn(interaction_hook, self.html)

    def test_card_help_controls_are_anchored_to_the_right_corner(self):
        self.assertEqual(
            self.html.count('class="annual-card-heading has-corner-help"'),
            3,
        )
        self.assertEqual(
            self.html.count('class="help-tip-wrap card-corner-help"'),
            3,
        )
        for layout_hook in (
            ".annual-card-heading.has-corner-help",
            ".annual-card-heading .card-corner-help",
            "right: 18px",
            ".card-corner-help .help-tooltip",
            "right: 0",
            "left: auto",
        ):
            self.assertIn(layout_hook, self.html)

    def test_chat_timestamp_and_timing_metadata_render_and_persist(self):
        for rendering_hook in (
            "function formatDashboardTimestamp(value)",
            "timeZone: 'America/Denver'",
            ".formatToParts(normalizeChatTimestamp(value))",
            "return `${values.month}-${values.day}-${values.year} ${values.hour}:${values.minute}`",
            "meta.className = 'message-meta'",
            "timestamp.dateTime = createdAt",
            "timestamp.textContent = formatDashboardTimestamp(createdAt)",
            "gpt_seconds: finiteElapsedSeconds(timing.gpt_seconds)",
            "model_run_seconds: finiteElapsedSeconds(timing.model_run_seconds)",
            "modelTimingText(",
            "applyMessageMeta(loadingBubble.parentElement, 'assistant', assistantMessage)",
        ):
            self.assertIn(rendering_hook, self.html)

        self.assertRegex(
            self.html,
            r"const userMessage = \{\s*role: 'user',\s*content: text,\s*"
            r"created_at: new Date\(\)\.toISOString\(\),\s*\};",
        )
        for persistence_hook in (
            "chatMessages,",
            "saved.chatMessages",
            "item.created_at || item.createdAt",
            "item.gpt_seconds ?? item.gptSeconds",
            "item.model_run_seconds ?? item.modelSeconds",
            "item.model_run_status || item.modelStatus || 'not_run'",
        ):
            self.assertIn(persistence_hook, self.html)

    def test_calibrated_predictions_and_comparison_wording_are_customer_facing(self):
        self.assertIn(
            "calibrated ? 'Calibrated AC Power' : 'Physics-Model AC Power'",
            self.html,
        )
        self.assertIn("'Calibrated Cumulative Energy'", self.html)
        self.assertLess(
            self.html.index('id="uncalibratedEnergyChartCard"'),
            self.html.index('id="energyChartBox"'),
        )
        self.assertLess(
            self.html.index('id="uncalibratedAcChartCard"'),
            self.html.index('id="acChartBox"'),
        )
        self.assertNotRegex(self.html, re.compile(r"\bmodel outputs?\b", re.IGNORECASE))
        for comparison_copy in (
            "Run the same interval with different parameters",
            "Different interval or source data",
            "Same interval and source data; only the requested parameters change.",
        ):
            self.assertIn(comparison_copy, self.html)
        self.assertNotRegex(
            self.html,
            re.compile(r"\b(?:non-)?like[- ]for[- ]like\b", re.IGNORECASE),
        )

    def test_workbook_downloads_use_server_supplied_readable_filenames(self):
        for marker in (
            "setExcelLink(result.excel, result.excel_filename)",
            "setAnnualExcelLink(result.excel, result.excel_filename)",
            "excelLink.download = filename || 'SB_Energy_Model_Results.xlsx'",
            "annualExcelLink.download = filename || 'SB_Energy_Annual_Simulation.xlsx'",
            "excelLink.removeAttribute('download')",
            "annualExcelLink.removeAttribute('download')",
            "if (item.filename) link.download = item.filename",
        ):
            self.assertIn(marker, self.html)

    def test_calibrated_result_cards_distinguish_applied_and_uncalibrated_predictions(self):
        for marker in (
            'id="statSePred"',
            'id="statSolPred"',
            'id="statSeUncalibratedPred"',
            'id="statSolUncalibratedPred"',
            'id="statSeUncalibratedPct"',
            'id="statSolUncalibratedPct"',
        ):
            self.assertIn(marker, self.html)
        helper = self.html.split(
            "function renderUncalibratedComparison(stats, calibrated)",
            1,
        )[1].split("\n        function ", 1)[0]
        for field in (
            "uncalibrated.se_predicted_kwh",
            "uncalibrated.sol_predicted_kwh",
            "uncalibrated.se_pct",
            "uncalibrated.sol_pct",
        ):
            self.assertIn(field, helper)
        self.assertIn("fmtPct", helper)
        self.assertIn("toLocaleString", helper)
        self.assertRegex(
            helper,
            r"calibrated\s*&&[\s\S]{0,240}typeof\s+[^;]+===\s*'object'",
        )
        self.assertIn(
            "const calibrated = s.calibration_enabled === true || !!s.calibration_factors",
            self.html,
        )
        self.assertIn(
            "renderUncalibratedComparison(s, calibrated)",
            self.html,
        )

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
        context = self.html.split(
            "function updateAgentContext()",
            1,
        )[1].split("\n        function putAgentProposal", 1)[0]
        self.assertIn("const currentRequest = getCanonicalCurrentConfig(activeMode)", context)
        self.assertIn(
            "const contextIamModel = baselineId ? baselineRequest?.iam_model : currentRequest.iam_model",
            context,
        )
        self.assertNotIn("baselineId ? baselineRequest?.iam_model : getCanonicalCurrentConfig", context)
        self.assertIn("'Physical IAM'", self.html)
        self.assertIn("'Martin–Ruiz IAM'", self.html)
        self.assertIn("'IAM not loaded'", context)

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
        self.assertIn("chatMessages = [{", body)
        self.assertIn("role: 'assistant'", body)
        self.assertIn("content: DEFAULT_ASSISTANT_MESSAGE", body)
        self.assertIn("created_at: new Date().toISOString()", body)
        self.assertNotIn("agentProposalSnapshots.clear", body)
        self.assertNotIn("agentJobSnapshots.clear", body)

    def test_conversation_history_archives_reopens_and_restores_chats(self):
        for element_id in (
            "chatHistoryBtn",
            "chatHistoryCount",
            "chatHistory",
            "chatHistoryList",
            "chatHistoryBack",
            "chatHistoryStorageStatus",
        ):
            self.assertIn(f'id="{element_id}"', self.html)

        for persistence_hook in (
            "CHAT_HISTORY_STORAGE_KEY = 'sb-energy-solar-agent-conversations-v1'",
            "MAX_SAVED_CHAT_CONVERSATIONS = 20",
            "function saveChatConversationHistory(syncActive = true)",
            "function restoreChatConversationHistory(",
            "active_conversation_id: activeChatConversationId",
            "conversations: compactionLevel",
            "restoreChatConversationHistory(",
            "chatConversationHasNonterminalAction(conversation)",
            "function chatConversationIsProtected(conversation)",
            "compactChatConversationForStorage(conversation, compactionLevel)",
            "chatHistoryPersistenceState",
            "chatHistoryRevision",
            "rebuildAgentCompletionCardIndex()",
        ):
            self.assertIn(persistence_hook, self.html)

        restore = self.html.split("async function restoreDashboardState()", 1)[1].split(
            "document.querySelectorAll('#analysisControls", 1
        )[0]
        self.assertLess(
            restore.index("restoreChatConversationHistory("),
            restore.index("serverSessionId = await loadServerSessionId()"),
        )
        for immediate_render in (
            "renderChatMessages()",
            "setChatHistoryOpen(saved?.chatHistoryOpen === true, false)",
            "setChatOpen(!!saved?.chatOpen, { focus: false, persist: false })",
        ):
            self.assertLess(
                restore.index(immediate_render),
                restore.index("serverSessionId = await loadServerSessionId()"),
            )

        save_history = self.html.split(
            "function saveChatConversationHistory(syncActive = true)", 1
        )[1].split("function restoreChatConversationHistory", 1)[0]
        self.assertIn("!chatConversationIsProtected(conversation)", save_history)
        self.assertIn("return false", save_history)
        self.assertIn("persistence_state: persistenceState", save_history)
        self.assertIn("revision: chatHistoryRevision", save_history)
        self.assertNotIn("chatConversations = candidates", save_history)
        self.assertNotIn(
            "conversation.id !== activeChatConversationId\n                        );",
            save_history,
        )

        save_dashboard = self.html.split("function saveDashboardState(options = {})", 1)[1].split(
            "function invalidateValidationStatusPoll", 1
        )[0]
        self.assertIn("options.allowDuringHydration !== true", save_dashboard)
        self.assertIn("const historySaved = saveChatConversationHistory(false)", save_dashboard)
        self.assertIn("activeChatConversationId,", save_dashboard)
        self.assertIn("chatHistoryRevision,", save_dashboard)
        self.assertIn("chatHistoryPersistenceState,", save_dashboard)
        self.assertIn("return historySaved", save_dashboard)

        self.assertIn("savedRevision > storedRevision", self.html)
        self.assertIn("legacyFailedWithoutRevision", self.html)
        self.assertIn("stored?.persistence_state === 'possible_loss'", self.html)
        self.assertIn("chatHistoryStickyIssue === 'possible_loss'", save_history)
        self.assertIn("Some recent conversation updates may be missing", self.html)
        self.assertIn('id="chatHistoryStorageStatus" role="status" hidden', self.html)
        self.assertLess(
            self.html.index('id="chatHistoryStorageStatus"'),
            self.html.index('id="chatHistory"'),
        )
        self.assertIn("chatHistoryStorageStatus.hidden = !storageMessage", self.html)

        self.assertIn("let chatHydrationPending = true", self.html)
        self.assertIn("chatHydrationPending || (!chatIsSending", self.html)
        self.assertIn("if (chatHydrationPending) return", self.html)
        self.assertIn("chatHydrationPending = false", self.html)
        self.assertIn("Restoring the saved dashboard context", self.html)
        self.assertIn("function releaseChatHydration()", self.html)
        self.assertIn("function fetchWithDashboardTimeout", self.html)
        self.assertIn(".finally(releaseChatHydration)", self.html)
        self.assertLess(
            restore.index("releaseChatHydration()"),
            restore.index("await refreshAgentState(false)"),
        )

        start_new = self.html.split("function startNewChat()", 1)[1].split(
            "function prefillChatPrompt", 1
        )[0]
        self.assertLess(
            start_new.index("syncActiveChatConversation()"),
            start_new.index("chatMessages = [{"),
        )
        self.assertIn("chatConversationHasContent(currentConversation)", start_new)
        self.assertIn("chatConversations.unshift(conversation)", start_new)
        self.assertIn("setChatHistoryOpen(false, false)", start_new)

        open_conversation = self.html.split(
            "function openChatConversation(conversationId)", 1
        )[1].split("function isChatMobile", 1)[0]
        for hook in (
            "syncActiveChatConversation()",
            "activeChatConversationId = conversation.id",
            "chatMessages = conversation.messages",
            "chatDraft = conversation.draft",
            "renderChatMessages()",
            "saveDashboardState()",
        ):
            self.assertIn(hook, open_conversation)

        clear_saved = self.html.split("function clearSavedState()", 1)[1].split(
            "async function loadServerSessionId", 1
        )[0]
        self.assertIn("localStorage.removeItem(STORAGE_KEY)", clear_saved)
        self.assertNotIn("CHAT_HISTORY_STORAGE_KEY", clear_saved)

    def test_archived_conversation_action_cards_are_tracked_and_updated(self):
        nonterminal = self.html.split(
            "function savedNonterminalActionJobIds()", 1
        )[1].split("function chatActionSweepMetadata", 1)[0]
        updater = self.html.split(
            "function updateStoredChatActionCardStatus(match, status, options = {})", 1
        )[1].split("function appendChatCardActions", 1)[0]
        tracker = self.html.split("function trackedChatCardForJob(job)", 1)[1].split(
            "function reconcileTerminalAgentCards", 1
        )[0]
        automated = self.html.split(
            "function appendAutomatedChatCardMessage(content, actionCard, options = {})", 1
        )[1].split("function rememberAgentCompletionCard", 1)[0]

        self.assertIn("chatConversations.forEach", nonterminal)
        self.assertIn("chatConversations.forEach", updater)
        self.assertIn("chatConversations.some", tracker)
        self.assertIn("chatConversationForActionCard(actionCard)", automated)
        self.assertIn("targetConversation.unread = true", automated)
        self.assertIn("options.origin_conversation", automated)
        self.assertIn("return saveDashboardState()", automated)
        self.assertIn("const persist = options.persist !== false", updater)
        self.assertIn("if (persist) saveDashboardState()", updater)
        completion = self.html.split("function announceAgentCompletion(job)", 1)[1].split(
            "function buildParameterSweepComparisonCard", 1
        )[0]
        self.assertIn("transientProtectedConversationIds.add", completion)
        self.assertIn("{ persist: false }", completion)
        self.assertIn("origin_conversation: originConversation", completion)
        self.assertIn("rememberAgentCompletionCard(completionKey)", completion)
        completion_rebuild = self.html.split(
            "function rebuildAgentCompletionCardIndex()", 1
        )[1].split("function syncChatHistoryControls", 1)[0]
        self.assertIn("isRecordedCompletion", completion_rebuild)
        self.assertIn("['done', 'error', 'cancelled', 'interrupted']", completion_rebuild)
        self.assertIn("async function openAgentActivityFromChat(card)", self.html)
        self.assertIn("'/api/status/' + encodeURIComponent(jobId)", self.html)

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

        handler = re.search(
            r"function handleAgentAction\(data\) \{(.*?)\n\s*\}\n\n\s*async function confirmAgentSweep",
            self.html,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(handler)
        job_started = handler.group(1).index("if (action.type === 'job_started' && action.job)")
        self.assertNotIn("setAgentActivityOpen(true)", handler.group(1)[job_started:])

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

    def test_live_updates_preserve_downloads_and_sweep_scroll_interaction(self):
        for hook in (
            "function captureAgentActivityViewState()",
            "details[open]",
            "details.open = viewState.openDetails.has",
            "parameter-sweep-table-wrap",
            "wrap.scrollLeft = scrollLeft",
            "function renderAgentActivityWhenIdle()",
            "window.addEventListener('pointerup', finishAgentActivityInteraction)",
            "renderAgentActivityWhenIdle();",
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
            '["cancel", "delete", "promote", "retry"]',
            'path[1] === "proposals"',
            '["confirm", "edit", "dismiss"]',
        ):
            self.assertIn(route, self.proxy)
        self.assertIn("isSafeId(path[1])", self.proxy)
        self.assertIn("isSafeId(path[2])", self.proxy)


if __name__ == "__main__":
    unittest.main()
