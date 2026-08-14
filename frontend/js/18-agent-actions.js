        async function refreshAgentState(showFeedback = false) {
            agentRefreshBtn.disabled = true;
            try {
                const response = await fetchWithDashboardTimeout(
                    '/api/agent/state',
                    { cache: 'no-store' }
                );
                const data = await readAgentResponse(response, 'Could not restore scenario activity.');
                agentServerState = normalizeAgentState(data);
                agentProposalSnapshots.clear();
                agentJobSnapshots.clear();
                agentServerState.proposals.forEach(putAgentProposal);
                agentServerState.jobs.forEach((job) => putAgentJob(job, { recordTerminal: false }));
                const missingBaselineIds = Object.values(agentServerState.promoted_baselines)
                    .filter((jobId) => jobId && !agentJobSnapshots.has(jobId));
                await Promise.all(missingBaselineIds.map(async (jobId) => {
                    try {
                        const baselineResponse = await fetchWithDashboardTimeout(
                            '/api/status/' + encodeURIComponent(jobId),
                            { cache: 'no-store' }
                        );
                        if (baselineResponse.ok) putAgentJob(await baselineResponse.json(), { recordTerminal: false });
                    } catch (_) {
                        // The context badge falls back gracefully if an old baseline is unavailable.
                    }
                }));
                await recoverSavedNonterminalActionJobs();
                reconcileTerminalAgentCards();
                reconcileAgentActivityFilterAfterRefresh();
                renderAgentActivity();
                Array.from(agentJobSnapshots.values()).forEach((job) => {
                    if (!isAgentJobTerminal(job)) scheduleAgentJobPoll(job.job_id, 250);
                });
                if (activeView === 'annual') await loadCurrentCalibration();
                if (showFeedback) appendSystemNotice('Scenario runs refreshed.');
            } catch (error) {
                if (showFeedback) appendSystemNotice(error.message || 'Could not refresh scenario runs.', 'error');
                updateAgentContext();
            } finally {
                agentRefreshBtn.disabled = false;
            }
        }

        function dashboardModeHasBlockingRun(mode, targetJobId) {
            const normalizedMode = mode === 'annual' ? 'annual' : 'validation';
            const snapshotIsActive = Array.from(agentJobSnapshots.values()).some((job) => (
                job.job_id !== targetJobId &&
                (job.mode === 'annual' ? 'annual' : 'validation') === normalizedMode &&
                !isAgentJobTerminal(job)
            ));
            if (snapshotIsActive) return true;
            if (normalizedMode === 'annual') {
                return !!annualLatestJobId && annualLatestJobId !== targetJobId &&
                    ['starting', 'queued', 'running', 'monitoring_error', 'confirmation_required'].includes(annualRunState?.state);
            }
            return calibrationReviewWorkflowIsActive() || (
                !!latestJobId && latestJobId !== targetJobId &&
                ['queued', 'running', 'monitoring_error'].includes(currentRunState?.state)
            );
        }

        function legacyAnnualRequestYear(request) {
            if (!request || !isRecognizedAnnualInterval(
                Number(request.interval_value), request.interval_unit
            )) return null;
            for (let year = ANNUAL_FIRST_YEAR; year <= annualCurrentYear(); year += 1) {
                const range = annualYearDateRange(year);
                if (range && request.from_date === range.periodStart && request.to_date === range.periodEnd) {
                    return year;
                }
            }
            return null;
        }

        async function viewAgentJobResults(jobId, requestedMode = null) {
            const snapshotMode = requestedMode || agentJobSnapshots.get(jobId)?.mode;
            if (snapshotMode && dashboardModeHasBlockingRun(snapshotMode, jobId)) {
                appendSystemNotice('Finish or cancel the active ' + (snapshotMode === 'annual' ? 'annual' : 'calibration') + ' run before viewing older results.');
                return false;
            }
            try {
                const response = await fetchWithDashboardTimeout(
                    '/api/status/' + encodeURIComponent(jobId),
                    { cache: 'no-store' }
                );
                const status = await readAgentResponse(response, 'Could not load this run.');
                const job = { ...(agentJobSnapshots.get(jobId) || {}), ...status };
                if (job.state !== 'done' || !job.result) {
                    throw new Error('Results are not available for this run.');
                }
                if (dashboardModeHasBlockingRun(job.mode, jobId)) {
                    appendSystemNotice('Finish or cancel the active ' + (job.mode === 'annual' ? 'annual' : 'calibration') + ' run before viewing older results.');
                    return false;
                }
                // Loading an existing result is read-only. It must not promote an
                // older saved/history item into the server-authoritative recent list.
                putAgentJob(job, { recordTerminal: false });
                const annual = job.mode === 'annual';
                const hasCanonicalAnnualYears = annual && normalizedAgentRequestYears(job.request).length > 0;
                const mappedLegacyAnnualYear = annual && !hasCanonicalAnnualYears
                    ? legacyAnnualRequestYear(job.request)
                    : null;
                const annualRequestCanBeLoaded = hasCanonicalAnnualYears || mappedLegacyAnnualYear !== null;
                if (!annual || annualRequestCanBeLoaded) {
                    applyPromotedRequest(annual ? 'annual' : 'validation', mappedLegacyAnnualYear === null
                        ? (job.request || {})
                        : { ...(job.request || {}), years: [mappedLegacyAnnualYear] });
                }
                if (annual) {
                    switchMode('annual', false);
                    invalidateAnnualStatusPoll();
                    annualLatestJobId = annualRequestCanBeLoaded ? jobId : null;
                    annualLatestResult = annualRequestCanBeLoaded ? job.result : null;
                    annualRunState = annualRequestCanBeLoaded
                        ? { state: 'done', progress: 100, stage: job.stage || 'Done' }
                        : null;
                    annualProgressWrap.classList.remove('visible');
                    resetAnnualRunBtn();
                    applyAnnualResult(job.result);
                    if (!annualRequestCanBeLoaded) {
                        showAnnualError('This legacy date-range result is read-only. Select MIDC years before starting a new simulation.');
                    }
                } else {
                    switchMode('validation', false);
                    invalidateValidationStatusPoll();
                    latestJobId = jobId;
                    latestInputPlots = job.input_plots || job.result.input_plots || null;
                    latestResult = job.result;
                    currentRunState = { state: 'done', progress: 100, stage: job.stage || 'Done' };
                    progressWrap.classList.remove('visible');
                    resetRunBtn();
                    const inputPlots = job.input_plots || job.result.input_plots;
                    if (inputPlots) applyInputPlots(inputPlots);
                    applyResult(job.result);
                }
                renderAgentActivity();
                setAgentActivityOpen(false, false);
                setChatOpen(false, { focus: false, persist: false });
                saveDashboardState();
                const heading = document.getElementById(annual ? 'annualResultsHeading' : 'validationResultsHeading');
                window.requestAnimationFrame(() => {
                    heading?.focus({ preventScroll: true });
                    heading?.scrollIntoView({ behavior: 'smooth', block: 'start' });
                });
                return true;
            } catch (error) {
                appendSystemNotice(error.message || 'Could not load this run.', 'error');
                return false;
            }
        }

        function handleAgentAction(data) {
            const action = normalizeAgentAction(data);
            if (!action) return;
            if (action.type === 'proposal_batch' && Array.isArray(action.proposals)) {
                action.proposals.forEach(putAgentProposal);
                agentActivityFilter = 'review';
                const firstProposal = action.proposals[0];
                if (firstProposal) agentActivitySelection = 'proposal:' + firstProposal.proposal_id;
                renderAgentActivity();
                setAgentActivityOpen(true);
                return;
            }
            if (action.type === 'proposal' && action.proposal) {
                putAgentProposal(action.proposal);
                agentActivityFilter = 'review';
                agentActivitySelection = 'proposal:' + action.proposal.proposal_id;
                renderAgentActivity();
                setAgentActivityOpen(true);
                return;
            }
            if (action.type === 'job_batch_started' && Array.isArray(action.jobs)) {
                action.jobs.forEach((job) => {
                    putAgentJob(job);
                    if (job.proposal_id) {
                        agentProposalSnapshots.delete(job.proposal_id);
                        updateStoredChatActionCardStatus({ proposal_id: job.proposal_id }, job.state || 'queued');
                    }
                });
                agentActivityFilter = 'active';
                if (agentActivityExpanded) {
                    const firstJob = action.jobs[0];
                    if (firstJob) agentActivitySelection = 'job:' + firstJob.job_id;
                }
                renderAgentActivity();
                action.jobs.forEach((job) => {
                    if (isAgentJobTerminal(job)) announceAgentCompletion(job);
                    else scheduleAgentJobPoll(job.job_id, 150);
                });
                return;
            }
            if (action.type === 'job_started' && action.job) {
                putAgentJob(action.job);
                if (action.job.proposal_id) {
                    agentProposalSnapshots.delete(action.job.proposal_id);
                    updateStoredChatActionCardStatus(
                        { proposal_id: action.job.proposal_id },
                        action.job.state || 'queued'
                    );
                }
                if (agentActivityExpanded) {
                    agentActivityFilter = 'active';
                    agentActivitySelection = 'job:' + action.job.job_id;
                }
                renderAgentActivity();
                if (isAgentJobTerminal(action.job)) announceAgentCompletion(action.job);
                else scheduleAgentJobPoll(action.job.job_id, 150);
            }
        }

        async function confirmAgentSweep(sweepId, fallbackProposalIds = []) {
            const group = getAgentParameterSweepGroups().find((item) => item.sweep_id === sweepId);
            const proposalIds = (group?.proposals || []).map((proposal) => proposal.proposal_id);
            if (!proposalIds.length && Array.isArray(fallbackProposalIds)) {
                proposalIds.push(...fallbackProposalIds.filter(Boolean));
            }
            if (!proposalIds.length) return;
            try {
                const data = await postAgentAction(
                    '/api/agent/sweeps/' + encodeURIComponent(sweepId) + '/confirm',
                    { proposal_ids: proposalIds }
                );
                proposalIds.forEach((proposalId) => agentProposalSnapshots.delete(proposalId));
                handleAgentAction(data);
                const cardUpdated = updateStoredChatActionCardStatus({ sweep_id: sweepId }, 'queued');
                if (!cardUpdated) appendSystemNotice('Parameter sweep queued against the selected baseline.', 'success');
            } catch (error) {
                appendSystemNotice(error.message || 'The parameter sweep could not be queued.', 'error');
            }
            await refreshAgentState(false);
        }

        async function dismissAgentSweep(sweepId, fallbackProposalIds = []) {
            const group = getAgentParameterSweepGroups().find((item) => item.sweep_id === sweepId);
            const proposalIds = (group?.proposals || []).map((proposal) => proposal.proposal_id);
            if (!proposalIds.length && Array.isArray(fallbackProposalIds)) {
                proposalIds.push(...fallbackProposalIds.filter(Boolean));
            }
            if (!proposalIds.length) return;
            let failures = 0;
            for (const proposalId of proposalIds) {
                try {
                    await postAgentAction('/api/agent/proposals/' + encodeURIComponent(proposalId) + '/dismiss');
                    agentProposalSnapshots.delete(proposalId);
                } catch (_) {
                    failures += 1;
                }
            }
            await refreshAgentState(false);
            if (failures) appendSystemNotice('Some parameter sweep proposals could not be dismissed.', 'error');
            else {
                const cardUpdated = updateStoredChatActionCardStatus({ sweep_id: sweepId }, 'dismissed');
                if (!cardUpdated) appendSystemNotice('Parameter sweep dismissed.');
            }
        }

        async function confirmAgentProposal(proposalId) {
            try {
                const data = await postAgentAction('/api/agent/proposals/' + encodeURIComponent(proposalId) + '/confirm');
                agentProposalSnapshots.delete(proposalId);
                handleAgentAction(data);
                await refreshAgentState(false);
            } catch (error) {
                appendSystemNotice(error.message || 'Could not start the proposed run.', 'error');
                await refreshAgentState(false);
            }
        }

        async function editAgentProposal(proposalId, overrides) {
            try {
                const data = await postAgentAction('/api/agent/proposals/' + encodeURIComponent(proposalId) + '/edit', { overrides });
                agentProposalSnapshots.delete(proposalId);
                handleAgentAction(data);
                await refreshAgentState(false);
                appendSystemNotice('A new immutable proposal was created from your edits.');
            } catch (error) {
                appendSystemNotice(error.message || 'Could not edit this proposal.', 'error');
            }
        }

        async function dismissAgentProposal(proposalId) {
            try {
                await postAgentAction('/api/agent/proposals/' + encodeURIComponent(proposalId) + '/dismiss');
                agentProposalSnapshots.delete(proposalId);
                const cardUpdated = updateStoredChatActionCardStatus({ proposal_id: proposalId }, 'dismissed');
                renderAgentActivity();
                if (!cardUpdated) appendSystemNotice('Scenario proposal dismissed.');
            } catch (error) {
                appendSystemNotice(error.message || 'Could not dismiss this proposal.', 'error');
            }
        }

        async function cancelAgentJob(jobId) {
            try {
                const data = await postAgentAction('/api/jobs/' + encodeURIComponent(jobId) + '/cancel');
                const current = agentJobSnapshots.get(jobId) || { job_id: jobId };
                const returned = data.job || data;
                const cancelRequested = returned.cancel_requested !== undefined
                    ? !!returned.cancel_requested
                    : !isAgentJobTerminal(returned);
                putAgentJob({
                    ...current,
                    ...returned,
                    cancel_requested: cancelRequested,
                    stage: returned.stage || (cancelRequested ? 'Cancellation requested…' : current.stage),
                });
                updateStoredChatActionCardStatus({ job_id: jobId }, 'cancel requested');
                renderAgentJobUpdate(agentJobSnapshots.get(jobId));
                scheduleAgentJobPoll(jobId, 150);
            } catch (error) {
                appendSystemNotice(error.message || 'Could not cancel this run.', 'error');
            }
        }

        async function deleteAgentJob(jobId) {
            const job = agentJobSnapshots.get(jobId);
            const isScenarioRun = job?.kind === 'candidate' && job?.baseline_job_id;
            const isBaselineRun = ['baseline', 'manual'].includes(job?.kind);
            if (!job || (!isScenarioRun && !isBaselineRun) || isAgentJobActive(job)) return;
            const runLabel = isBaselineRun ? 'baseline' : 'scenario';
            if (!window.confirm('Delete this ' + runLabel + ' run and its generated files? This cannot be undone.')) return;
            if (job.client_action_error) {
                putAgentJob({ ...job, client_action_error: null }, { recordTerminal: false });
                renderAgentActivity();
            }
            try {
                await postAgentAction('/api/jobs/' + encodeURIComponent(jobId) + '/delete');
                const timer = agentJobPollTimers.get(jobId);
                if (timer) clearTimeout(timer);
                agentJobPollTimers.delete(jobId);
                agentJobStartedAt.delete(jobId);
                agentJobSnapshots.delete(jobId);
                agentExplainedJobs.delete(jobId);
                agentCompletionCards.delete('job:' + jobId);
                updateStoredChatActionCardStatus({ job_id: jobId }, 'deleted');
                if (job.mode === 'annual' && annualLatestJobId === jobId) {
                    invalidateAnnualStatusPoll();
                    annualLatestJobId = null;
                    annualLatestResult = null;
                    annualRunState = null;
                    clearAnnualSeasonalFallbackDisplay();
                    void refreshTechnoeconomicSources();
                    clearAnnualImages();
                    renderAnnualQuality([]);
                    setAnnualExcelLink(null);
                }
                if (job.mode !== 'annual' && latestJobId === jobId) {
                    invalidateValidationStatusPoll();
                    latestJobId = null;
                    latestInputPlots = null;
                    latestResult = null;
                    currentRunState = null;
                    clearRunImages();
                    calibrationFactorPanel.classList.add('hidden');
                    renderUncalibratedComparison(null, false);
                    renderValidationRunContext(null);
                    setExcelLink(null);
                }
                if (agentActivitySelection === 'job:' + jobId) agentActivitySelection = null;
                renderAgentActivity();
                appendSystemNotice('The ' + runLabel + ' run was deleted, including its generated files.');
                saveDashboardState();
                await refreshAgentState(false);
            } catch (error) {
                const message = error.message || 'Could not delete this scenario run.';
                const current = agentJobSnapshots.get(jobId);
                if (current) {
                    putAgentJob({ ...current, client_action_error: message }, { recordTerminal: false });
                    renderAgentActivity();
                }
                appendSystemNotice(message, 'error');
            }
        }

        async function retryAgentJob(job) {
            try {
                const data = await postAgentAction('/api/jobs/' + encodeURIComponent(job.job_id) + '/retry');
                const action = normalizeAgentAction(data);
                const retried = action?.job || data.job || data;
                const sweepId = agentParameterSweepMetadata(retried)?.sweep_id;
                const completionKey = sweepId ? 'sweep:' + sweepId : 'job:' + retried.job_id;
                agentCompletionCards.delete(completionKey);
                const cardUpdated = updateStoredChatActionCardStatus(
                    sweepId ? { sweep_id: sweepId } : { job_id: retried.job_id },
                    retried.state || 'queued'
                );
                agentJobStartedAt.set(retried.job_id, Date.now());
                putAgentJob(retried);
                renderAgentJobUpdate(agentJobSnapshots.get(retried.job_id));
                scheduleAgentJobPoll(retried.job_id, 150);
                if (!cardUpdated) appendSystemNotice('Retry queued with the same immutable request snapshot.');
            } catch (error) {
                appendSystemNotice(error.message || 'Could not retry this run.', 'error');
            }
        }

        async function requestAgentCompletionExplanation(job) {
            if (!job || job.state !== 'done' || !job.comparison) return;
            if (agentExplainedJobs.has(job.job_id)) return;
            const originConversation = chatConversationForActionCard({ job_id: job.job_id })
                || activeChatConversation();
            const originConversationId = originConversation?.id || activeChatConversationId;
            agentExplainedJobs.add(job.job_id);
            saveDashboardState();
            const loadingBubble = originConversationId === activeChatConversationId
                ? appendMessage('assistant', '', { loading: true })
                : null;
            const loadingLabel = loadingBubble?.querySelector('.chat-loading-label');
            if (loadingLabel) loadingLabel.textContent = 'Preparing engineering explanation';
            try {
                const history = (originConversation?.messages || chatMessages)
                    .slice(-8)
                    .map((item) => ({ role: item.role, content: item.content }));
                const response = await fetch('/api/chat', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        message: 'Explain the completed deterministic comparison for this job. Do not call any tools or create a proposal. Highlight the engineering meaning, the comparability caveat, and suggest one or two useful follow-up experiments without running them.',
                        job_id: job.job_id,
                        history,
                        active_mode: job.mode === 'annual' ? 'annual' : 'validation',
                        current_config: job.request || getCanonicalCurrentConfig(job.mode),
                        allow_scenario_actions: false,
                    }),
                });
                const data = await readAgentResponse(response, 'The engineering explanation is temporarily unavailable.');
                const reply = data.reply || 'The comparison is complete, but no engineering explanation was returned.';
                const assistantMessage = assistantMessageFromResponse(reply, data);
                loadingBubble?.parentElement?.remove();
                const targetConversation = chatConversations.find(
                    (conversation) => conversation.id === originConversationId
                ) || activeChatConversation();
                if (targetConversation?.id === activeChatConversationId) {
                    chatMessages.push(assistantMessage);
                    chatMessages = trimChatMessages(chatMessages);
                    renderChatMessages();
                    renderChatFollowups();
                } else if (targetConversation) {
                    targetConversation.messages.push(assistantMessage);
                    targetConversation.messages = trimChatMessages(targetConversation.messages);
                    targetConversation.updated_at = assistantMessage.created_at;
                    targetConversation.unread = true;
                    renderChatHistory();
                }
                renderAgentActivity();
                saveDashboardState();
            } catch (error) {
                loadingBubble?.parentElement?.remove();
                agentExplainedJobs.delete(job.job_id);
                saveDashboardState();
                const errorMessage = error.message || 'The comparison completed, but its explanation could not be generated.';
                appendSystemNotice(
                    activeChatConversationId === originConversationId
                        ? errorMessage
                        : 'Could not add an explanation to "' + (originConversation?.title || 'the original conversation') + '": ' + errorMessage,
                    'error'
                );
            }
        }

        async function promoteAgentJob(jobId) {
            if (currentRunState?.state === 'applying_review') {
                appendSystemNotice(
                    'Wait for the reviewed calibration to enter the queue before promoting another calibration result.',
                    'error'
                );
                return;
            }
            try {
                const data = await postAgentAction('/api/jobs/' + encodeURIComponent(jobId) + '/promote');
                const previous = agentJobSnapshots.get(jobId) || {};
                const mode = data.mode === 'annual' ? 'annual' : (previous.mode === 'annual' ? 'annual' : 'validation');
                const promoted = { ...previous, ...data, job_id: jobId, mode, state: 'done', progress: 100 };
                if (mode === 'annual') invalidateAnnualStatusPoll();
                else invalidateValidationStatusPoll();
                putAgentJob(promoted);
                agentServerState.promoted_baselines[mode] = jobId;
                if (mode === 'validation' && calibrationReviewWorkflowIsActive()) {
                    cancelCalibrationReview();
                }
                applyPromotedRequest(mode, data.request || promoted.request || promoted.provenance?.request);
                if (mode === 'annual') {
                    annualLatestJobId = jobId;
                    annualLatestResult = data.result || promoted.result || null;
                    annualRunState = { state: 'done', progress: 100, stage: 'Promoted baseline' };
                    if (annualLatestResult) applyAnnualResult(annualLatestResult);
                } else {
                    latestJobId = jobId;
                    latestResult = data.result || promoted.result || null;
                    currentRunState = { state: 'done', progress: 100, stage: 'Promoted baseline' };
                    if (latestResult) applyResult(latestResult);
                }
                saveDashboardState();
                renderAgentActivity();
                appendSystemNotice('Scenario promoted to the ' + (mode === 'annual' ? 'annual' : 'calibration') + ' baseline. Dashboard controls and results now reflect it.');
                await refreshAgentState(false);
            } catch (error) {
                appendSystemNotice(error.message || 'Could not promote this scenario.', 'error');
            }
        }

        setInterval(updateAgentElapsedLabels, 1000);
        setInterval(() => {
            const hasExpired = Array.from(agentProposalSnapshots.values()).some((proposal) => {
                const expiresAt = proposal.expires_at ? Date.parse(proposal.expires_at) : NaN;
                return (!proposal.status || proposal.status === 'pending') && Number.isFinite(expiresAt) && expiresAt <= Date.now();
            });
            if (hasExpired) refreshAgentState(false);
        }, 60000);

