        function readSavedState() {
            try {
                return JSON.parse(localStorage.getItem(STORAGE_KEY) || 'null');
            } catch (_) {
                return null;
            }
        }

        function clearSavedState() {
            try {
                localStorage.removeItem(STORAGE_KEY);
            } catch (_) {
                // localStorage may be unavailable in private or restricted contexts.
            }
        }

        async function fetchWithDashboardTimeout(resource, options = {}, timeoutMs = 8000) {
            const controller = new AbortController();
            const timeout = window.setTimeout(() => controller.abort(), timeoutMs);
            try {
                return await fetch(resource, { ...options, signal: controller.signal });
            } finally {
                window.clearTimeout(timeout);
            }
        }

        async function loadServerSessionId() {
            try {
                const res = await fetchWithDashboardTimeout(
                    '/api/session',
                    { cache: 'no-store' },
                    4000
                );
                if (!res.ok) return null;
                const data = await res.json();
                return data.session_id || null;
            } catch (_) {
                return null;
            }
        }

        function resetClientState() {
            calibrationWorkflowRevision += 1;
            invalidateValidationStatusPoll();
            invalidateAnnualStatusPoll();
            abortCalibrationReviewRequests();
            setCalibrationControlsLocked(false);
            latestJobId = null;
            latestInputPlots = null;
            latestResult = null;
            currentRunState = null;
            pendingCalibrationReview = null;
            calibrationReviewCollapsed = false;
            setCalibrationReviewCollapsed(false, { persist: false });
            annualLatestJobId = null;
            annualLatestResult = null;
            annualRunState = null;
            window.resetSavedResultsDisplayedJobs?.();
            annualCalibrationBaseline = null;
            annualCalibrationBaselineJobId = null;
            annualCalibrationProfileSha256 = null;
            annualRequestRevision += 1;
            clearAnnualFallbackConfirmation();
            let preservedConversation = activeChatConversation();
            if (!preservedConversation) {
                preservedConversation = createChatConversation(chatMessages, chatDraft);
                chatConversations = [preservedConversation];
                activeChatConversationId = preservedConversation.id;
            }
            chatMessages = preservedConversation.messages;
            chatDraft = preservedConversation.draft;
            chatInput.value = chatDraft;
            autoResizeChatInput();
            syncChatComposerState();
            chatHistoryOpen = false;
            chatSidebar.classList.remove('history-view');
            chatHistoryPanel.classList.add('hidden');
            agentActivityExpanded = false;
            agentActivityFilter = 'all';
            agentActivitySelection = null;
            agentServerState = {
                proposals: [],
                jobs: [],
                recent_job_ids: [],
                recent_activity_count: 0,
                history_limit: MAX_RECENT_AGENT_RUNS,
                promoted_baselines: { validation: null, annual: null },
            };
            agentProposalSnapshots.clear();
            agentJobSnapshots.clear();
            rebuildAgentCompletionCardIndex();
            agentJobPollTimers.forEach((timer) => clearTimeout(timer));
            agentJobPollTimers.clear();
            progressWrap.classList.remove('visible');
            errorBanner.classList.remove('visible');
            calibrationReviewPanel.classList.add('hidden');
            calibrationFactorPanel.classList.add('hidden');
            renderUncalibratedComparison(null, false);
            renderValidationRunContext(null);
            clearRunImages();
            clearAnnualImages();
            applyTechnoeconomicFormState(null);
            setExcelLink(null);
            setAnnualExcelLink(null);
            renderAnnualQuality([]);
            renderAnnualResultCalibration(null);
            renderAnnualCalibrationBaseline(null, { state: 'loading' });
            applyValidationDateDefaults();
            renderAgentActivity();
            renderChatMessages();
            renderChatHistory();
            setChatOpen(false);
            switchMode('validation', false);
        }

        function saveDashboardState(options = {}) {
            if (chatHydrationPending && options.allowDuringHydration !== true) return false;
            syncActiveChatConversation();
            const historySaved = saveChatConversationHistory(false);
            syncChatHistoryControls();
            try {
                localStorage.setItem(STORAGE_KEY, JSON.stringify({
                    serverSessionId,
                    activeView,
                    activeMode,
                    latestJobId,
                    latestInputPlots,
                    latestResult,
                    currentRunState,
                    pendingCalibrationReview,
                    calibrationReviewCollapsed,
                    form: getFormState(),
                    annualLatestJobId,
                    annualLatestResult,
                    annualRunState,
                    savedResultsDisplayedContext: window.getSavedResultsDisplayedContext?.() || null,
                    annualCalibrationBaselineJobId,
                    annualCalibrationProfileSha256,
                    annualForm: getAnnualFormState(),
                    technoeconomicForm: getTechnoeconomicFormState(),
                    activeChatConversationId,
                    chatMessages,
                    chatDraft,
                    chatHistoryRevision,
                    chatHistoryPersistenceState,
                    agentActivityExpanded,
                    agentActivityFilter,
                    agentActivitySelection,
                    chatHistoryOpen,
                    agentExplainedJobs: Array.from(agentExplainedJobs).slice(-50),
                    chatOpen: !chatSidebar.classList.contains('hidden'),
                }));
            } catch (_) {
                // localStorage may be unavailable in private or restricted contexts.
            }
            return historySaved;
        }

        function invalidateValidationStatusPoll() {
            validationPollRevision += 1;
            if (pollTimer) {
                clearTimeout(pollTimer);
                pollTimer = null;
            }
            return validationPollRevision;
        }

        function invalidateAnnualStatusPoll() {
            annualPollRevision += 1;
            if (annualPollTimer) {
                clearTimeout(annualPollTimer);
                annualPollTimer = null;
            }
            return annualPollRevision;
        }

        function statusPollRetryDelay(failureCount) {
            return Math.min(STATUS_POLL_MAX_DELAY_MS, 600 * (2 ** Math.max(0, failureCount - 1)));
        }

        function registerDirectRun(jobId, mode, request, progress, stage) {
            if (!jobId) return;
            putAgentJob({
                job_id: jobId,
                kind: 'baseline',
                mode,
                state: 'queued',
                progress,
                stage,
                cancel_requested: false,
                request: { ...request },
                origin: 'dashboard',
                created_at: new Date().toISOString(),
            });
            agentActivityFilter = 'active';
            agentActivitySelection = 'job:' + jobId;
            renderAgentActivity();
        }

