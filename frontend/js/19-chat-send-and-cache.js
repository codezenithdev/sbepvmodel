        function renderChatMessages() {
            messagesContainer.innerHTML = '';
            if (isInitialChatState()) {
                renderChatWelcome();
                return;
            }
            const messages = chatMessages.length ? chatMessages : [{ role: 'assistant', content: DEFAULT_ASSISTANT_MESSAGE }];
            messages.forEach((item) => appendMessage(
                item.role === 'user' ? 'user' : 'assistant',
                item.content,
                item
            ));
            renderChatFollowups();
            scrollChatToBottom(true);
        }

        function setChatOpen(open, options = {}) {
            const focus = options.focus !== false;
            const persist = options.persist !== false;
            if (open && focus) lastChatTrigger = document.activeElement;
            chatSidebar.classList.toggle('hidden', !open);
            chatToggle.classList.toggle('hidden', open);
            chatToggle.setAttribute('aria-expanded', String(open));
            syncChatModalState(open);
            if (open) {
                syncChatWindowPosition();
                if (focus) {
                    window.setTimeout(() => {
                        if (chatHistoryOpen) chatHistoryBack.focus();
                        else if (isChatMobile()) closeChat.focus();
                        else chatInput.focus();
                    }, 0);
                }
            } else if (focus) {
                const focusTarget = lastChatTrigger && document.contains(lastChatTrigger) ? lastChatTrigger : chatToggle;
                window.setTimeout(() => focusTarget.focus?.(), 0);
            }
            if (persist) saveDashboardState();
        }

        function setSending(isSending) {
            chatIsSending = !!isSending;
            sendBtn.classList.toggle('is-sending', chatIsSending);
            sendBtn.querySelector('.send-label').textContent = chatIsSending ? 'Cancel' : 'Send';
            syncChatComposerState();
        }

        function cancelChatRequest() {
            if (!activeChatAbortController) return;
            activeChatAbortController.abort();
        }

        async function sendMessage() {
            const text = chatInput.value.trim();
            if (!text || chatIsSending || chatHydrationPending) return;

            chatInput.value = '';
            chatDraft = '';
            autoResizeChatInput();
            syncChatComposerState();
            const userMessage = {
                role: 'user',
                content: text,
                created_at: new Date().toISOString(),
            };
            appendMessage('user', text, userMessage);
            chatMessages.push(userMessage);
            chatMessages = trimChatMessages(chatMessages);
            saveDashboardState();

            const loadingBubble = appendMessage('assistant', '', { loading: true });
            const chatController = new AbortController();
            activeChatAbortController = chatController;
            let chatRequestTimedOut = false;
            const chatTimeout = window.setTimeout(() => {
                chatRequestTimedOut = true;
                chatController.abort();
            }, CHAT_REQUEST_TIMEOUT_MS);
            setSending(true);
            try {
                const history = chatMessages.slice(-10, -1).map((item) => ({
                    role: item.role,
                    content: item.content,
                }));
                const res = await fetch('/api/chat', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        message: text,
                        job_id: activeMode === 'annual' ? annualLatestJobId : latestJobId,
                        history,
                        active_mode: activeMode,
                        current_config: getCanonicalCurrentConfig(activeMode),
                    }),
                    signal: chatController.signal,
                });
                let data = {};
                try {
                    data = await res.json();
                } catch (_) {
                    // Keep a status-based error below if the body is not JSON.
                }
                if (!res.ok) {
                    const detail = data.detail || 'Chat request failed (' + res.status + ')';
                    throw new Error(Array.isArray(detail) ? detail[0].msg : detail);
                }
                const action = normalizeAgentAction(data);
                const modelReply = data.reply || 'I could not generate a response for that question.';
                const reply = action ? agentActionSummary(action) : modelReply;
                const actionCard = action ? buildChatActionCard(action) : null;
                loadingBubble.parentElement.classList.remove('is-loading');
                loadingBubble.parentElement.removeAttribute('role');
                renderMessageBubbleContent(loadingBubble, reply, { action_card: actionCard });
                loadingBubble.parentElement.classList.toggle('clarification', !action && isClarificationReply(reply, data));
                const assistantMessage = assistantMessageFromResponse(reply, {
                    ...data,
                    action_card: actionCard,
                });
                applyMessageMeta(loadingBubble.parentElement, 'assistant', assistantMessage);
                chatMessages.push(assistantMessage);
                handleAgentAction(data);
                if (!action) renderExternalEvidence(reply, data);
                const startedJob = action?.type === 'job_started' ? action.job : null;
                if (startedJob?.job_id) {
                    if (startedJob.mode === 'annual') {
                        annualLatestJobId = startedJob.job_id;
                    } else {
                        latestJobId = startedJob.job_id;
                    }
                }
                chatMessages = trimChatMessages(chatMessages);
                saveDashboardState();
                scrollChatToBottom();
            } catch (e) {
                const msg = e?.name === 'AbortError'
                    ? (chatRequestTimedOut
                        ? 'Solar Agent took too long to respond. The wait was stopped after 60 seconds; you can retry.'
                        : 'Solar Agent response canceled.')
                    : (e.message || 'The solar agent could not answer right now.');
                loadingBubble.parentElement.remove();
                appendSystemNotice(msg, 'error');
            } finally {
                clearTimeout(chatTimeout);
                if (activeChatAbortController === chatController) {
                    activeChatAbortController = null;
                }
                setSending(false);
                renderChatFollowups();
                if (!isChatMobile() && (document.activeElement === chatInput || document.activeElement === document.body)) {
                    chatInput.focus();
                }
            }
        }

        function clearCachedCompletedRun(mode) {
            if (mode === 'annual') {
                annualLatestJobId = null;
                annualLatestResult = null;
                annualRunState = null;
                setAnnualExcelLink(null);
                clearAnnualImages();
                return;
            }
            latestJobId = null;
            latestInputPlots = null;
            latestResult = null;
            currentRunState = null;
            setExcelLink(null);
            clearRunImages();
            renderValidationRunContext(null);
        }

        function markCachedRunUnverified(mode) {
            if (mode === 'annual') {
                annualLatestResult = null;
                annualRunState = {
                    state: 'monitoring_error',
                    progress: annualRunState?.progress || 0,
                    stage: 'Revalidating cached annual run',
                };
                setAnnualExcelLink(null);
                clearAnnualImages();
                return;
            }
            latestInputPlots = null;
            latestResult = null;
            currentRunState = {
                state: 'monitoring_error',
                progress: currentRunState?.progress || 0,
                stage: 'Revalidating cached run',
            };
            setExcelLink(null);
            clearRunImages();
            renderValidationRunContext(null);
        }

        async function revalidateCachedCompletedRun(mode) {
            const annual = mode === 'annual';
            const jobId = annual ? annualLatestJobId : latestJobId;
            const cachedResult = annual ? annualLatestResult : latestResult;
            if (!jobId || !cachedResult) return;
            try {
                const response = await fetchWithDashboardTimeout(
                    '/api/status/' + encodeURIComponent(jobId),
                    { cache: 'no-store' },
                    6000
                );
                if (response.status === 404) {
                    clearCachedCompletedRun(mode);
                    updateStoredChatActionCardStatus({ job_id: jobId }, 'unavailable');
                    if (annual) showAnnualError('The cached annual run was deleted or is no longer available.');
                    else showError('The cached run was deleted or is no longer available.');
                    return;
                }
                const data = await readAgentResponse(response, 'Could not verify the cached run.');
                putAgentJob(data);
                if (data.state === 'done' && data.result) {
                    if (annual) {
                        annualLatestResult = data.result;
                        annualRunState = { state: 'done', progress: 100, stage: data.stage || 'Done' };
                    } else {
                        latestResult = data.result;
                        latestInputPlots = data.input_plots || data.result.input_plots || null;
                        currentRunState = { state: 'done', progress: 100, stage: data.stage || 'Done' };
                    }
                    return;
                }

                if (annual) {
                    annualLatestResult = null;
                    annualRunState = { state: data.state, progress: data.progress || 0, stage: data.stage || '' };
                } else {
                    latestResult = null;
                    latestInputPlots = data.input_plots || null;
                    currentRunState = { state: data.state, progress: data.progress || 0, stage: data.stage || '' };
                }
            } catch (error) {
                markCachedRunUnverified(mode);
                if (annual) {
                    showAnnualError(error.message || 'The cached annual run could not be verified yet; status monitoring will retry.');
                } else {
                    showError(error.message || 'The cached run could not be verified yet; status monitoring will retry.');
                }
            }
        }

        async function restoreDashboardState() {
            const saved = readSavedState();
            const legacyChatMessages = saved ? saved.chatMessages : null;
            const legacyChatDraft = saved ? saved.chatDraft : '';
            const legacyPersistenceState = ['degraded', 'failed', 'possible_loss'].includes(saved?.chatHistoryPersistenceState)
                ? saved.chatHistoryPersistenceState
                : saved?.chatHistoryPersistenceFailed === true ? 'failed' : 'ok';
            restoreChatConversationHistory(
                legacyChatMessages,
                legacyChatDraft,
                saved?.activeChatConversationId,
                saved?.chatHistoryRevision,
                legacyPersistenceState
            );
            chatInput.value = chatDraft;
            if (Array.isArray(saved?.agentExplainedJobs)) {
                saved.agentExplainedJobs.filter(Boolean).slice(-50).forEach((jobId) => agentExplainedJobs.add(String(jobId)));
            }
            autoResizeChatInput();
            syncChatComposerState();
            renderChatMessages();
            setChatHistoryOpen(saved?.chatHistoryOpen === true, false);
            setChatOpen(!!saved?.chatOpen, { focus: false, persist: false });
            serverSessionId = await loadServerSessionId();
            if (!saved) {
                autoResizeChatInput();
                syncChatComposerState();
                renderChatMessages();
                await loadCurrentCalibration({ forceSettings: true });
                renderChatHistory();
                saveDashboardState({ allowDuringHydration: true });
                releaseChatHydration();
                await refreshAgentState(false);
                saveDashboardState();
                return;
            }

            if (serverSessionId && saved.serverSessionId !== serverSessionId) {
                clearSavedState();
                resetClientState();
                await loadCurrentCalibration({ forceSettings: true });
                saveDashboardState({ allowDuringHydration: true });
                releaseChatHydration();
                await refreshAgentState(false);
                saveDashboardState();
                return;
            }

            latestJobId = saved.latestJobId || null;
            latestInputPlots = saved.latestInputPlots || null;
            latestResult = saved.latestResult || null;
            currentRunState = saved.currentRunState || null;
            pendingCalibrationReview = saved.pendingCalibrationReview || null;
            calibrationReviewCollapsed = saved.calibrationReviewCollapsed === true;
            annualLatestJobId = saved.annualLatestJobId || null;
            annualLatestResult = saved.annualLatestResult || null;
            annualRunState = saved.annualRunState || null;
            if (annualRunState?.state === 'confirmation_required') annualRunState = null;
            annualCalibrationBaselineJobId = saved.annualCalibrationBaselineJobId || null;
            annualCalibrationProfileSha256 = saved.annualCalibrationProfileSha256 || null;
            agentActivityExpanded = saved.agentActivityExpanded === true;
            agentActivityFilter = ['all', 'review', 'active', 'complete'].includes(saved.agentActivityFilter)
                ? saved.agentActivityFilter
                : 'all';
            agentActivitySelection = typeof saved.agentActivitySelection === 'string'
                ? saved.agentActivitySelection
                : null;
            autoResizeChatInput();
            syncChatComposerState();
            await Promise.all([
                revalidateCachedCompletedRun('validation'),
                revalidateCachedCompletedRun('annual'),
            ]);

            applyFormState(saved.form);
            applyAnnualFormState(saved.annualForm);
            applyTechnoeconomicFormState(saved.technoeconomicForm);
            await loadCurrentCalibration();
            switchMode(saved.activeView || saved.activeMode || 'validation', false);
            if (latestInputPlots) {
                applyInputPlots(latestInputPlots, false);
            }
            if (latestResult) {
                applyResult(latestResult, false);
            }
            if (annualLatestResult) {
                applyAnnualResult(annualLatestResult, false);
            }
            if (
                pendingCalibrationReview &&
                (
                    pendingCalibrationReview.applied ||
                    ['review_required', 'applying_review'].includes(currentRunState?.state)
                )
            ) {
                if (!pendingCalibrationReview.applied) {
                    runBtn.disabled = true;
                    currentRunState = {
                        state: 'review_required',
                        progress: 20,
                        stage: 'Data-quality decision required',
                    };
                }
                renderCalibrationReview(pendingCalibrationReview, { focusPanel: false });
            } else if (['reviewing', 'starting'].includes(currentRunState?.state)) {
                currentRunState = null;
                resetRunBtn();
            }
            renderChatMessages();
            setChatHistoryOpen(saved.chatHistoryOpen === true, false);
            setChatOpen(!!saved.chatOpen, { focus: false, persist: false });

            if (currentRunState && ['queued', 'running', 'monitoring_error'].includes(currentRunState.state) && latestJobId) {
                runBtn.disabled = true;
                runBtn.textContent = 'Running...';
                setProgress(currentRunState.progress || 0, currentRunState.stage || 'Restoring run...');
                pollStatus(latestJobId);
            }
            if (annualRunState && ['queued', 'running', 'monitoring_error'].includes(annualRunState.state) && annualLatestJobId) {
                annualRunBtn.disabled = true;
                annualRunBtn.textContent = 'Running...';
                setAnnualProgress(annualRunState.progress || 0, annualRunState.stage || 'Restoring annual run...');
                pollAnnualStatus(annualLatestJobId);
            }
            saveDashboardState({ allowDuringHydration: true });
            releaseChatHydration();
            await refreshAgentState(false);
            saveDashboardState();
        }

        document.querySelectorAll('#analysisControls input, #analysisControls select').forEach((el) => {
            el.addEventListener('input', () => {
                if (calibrationReviewWorkflowIsActive()) {
                    cancelCalibrationReview();
                }
                if (el.classList.contains('annual-input')) {
                    annualRequestRevision += 1;
                    clearAnnualFallbackConfirmation();
                    if (['starting', 'confirmation_required'].includes(annualRunState?.state)) {
                        annualRunState = null;
                        annualProgressWrap.classList.remove('visible');
                        resetAnnualRunBtn();
                    }
                    renderAnnualSettingDiffs();
                }
                saveDashboardState();
                updateAgentContext();
            });
            el.addEventListener('change', () => {
                if (calibrationReviewWorkflowIsActive()) {
                    cancelCalibrationReview();
                }
                if (el.classList.contains('annual-input')) {
                    annualRequestRevision += 1;
                    clearAnnualFallbackConfirmation();
                    if (['starting', 'confirmation_required'].includes(annualRunState?.state)) {
                        annualRunState = null;
                        annualProgressWrap.classList.remove('visible');
                        resetAnnualRunBtn();
                    }
                    renderAnnualSettingDiffs();
                }
                saveDashboardState();
                updateAgentContext();
            });
        });
        document.querySelectorAll('#annualControls input, #annualControls select').forEach((el) => {
            el.addEventListener('input', () => {
                saveDashboardState();
                updateAgentContext();
            });
            el.addEventListener('change', () => {
                saveDashboardState();
                updateAgentContext();
            });
        });
        restoreDashboardState()
            .catch((error) => {
                appendSystemNotice(
                    error?.message || 'The saved dashboard context could not be fully restored.',
                    'error'
                );
            })
            .finally(releaseChatHydration);
