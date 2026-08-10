        function captureAgentEditorState() {
            const active = document.activeElement;
            const editors = [];
            agentActivityList.querySelectorAll('[data-proposal-id]').forEach((card) => {
                const form = card.querySelector('.agent-edit-form:not(.hidden)');
                if (!form) return;
                const values = {};
                form.querySelectorAll('[data-override-field]').forEach((input) => {
                    values[input.dataset.overrideField] = input.value;
                });
                const focusedField = form.contains(active) ? active.dataset?.overrideField || null : null;
                editors.push({
                    proposalId: card.dataset.proposalId,
                    values,
                    focusedField,
                    selectionStart: focusedField && typeof active.selectionStart === 'number' ? active.selectionStart : null,
                    selectionEnd: focusedField && typeof active.selectionEnd === 'number' ? active.selectionEnd : null,
                });
            });
            return editors;
        }

        function restoreAgentEditorState(editors) {
            editors.forEach((editor) => {
                const card = Array.from(agentActivityList.querySelectorAll('[data-proposal-id]'))
                    .find((element) => element.dataset.proposalId === editor.proposalId);
                const form = card?.querySelector('.agent-edit-form');
                if (!form) return;
                form.classList.remove('hidden');
                card.querySelector('[aria-controls="' + form.id + '"]')?.setAttribute('aria-expanded', 'true');
                Object.entries(editor.values).forEach(([field, value]) => {
                    const input = Array.from(form.querySelectorAll('[data-override-field]'))
                        .find((element) => element.dataset.overrideField === field);
                    if (input) input.value = value;
                });
                if (editor.focusedField) {
                    const focusTarget = Array.from(form.querySelectorAll('[data-override-field]'))
                        .find((element) => element.dataset.overrideField === editor.focusedField);
                    focusTarget?.focus({ preventScroll: true });
                    if (focusTarget && editor.selectionStart !== null && typeof focusTarget.setSelectionRange === 'function') {
                        focusTarget.setSelectionRange(editor.selectionStart, editor.selectionEnd);
                    }
                }
            });
        }

        function buildAgentRunSummary(entry) {
            const selected = agentActivitySelection === entry.key;
            const summaryData = summarizeAgentRequest(entry);
            const record = document.createElement('article');
            record.className = 'agent-run-record' + (selected ? ' selected' : '');
            record.dataset.agentActivityKey = entry.key;
            const detailId = 'agent-run-detail-' + entry.key.replace(/[^a-z0-9_-]/gi, '-');

            const summary = document.createElement('button');
            summary.type = 'button';
            summary.className = 'agent-run-summary';
            summary.dataset.agentRunRow = entry.key;
            summary.setAttribute('aria-expanded', String(selected));
            summary.setAttribute('aria-controls', detailId);
            const head = document.createElement('span');
            head.className = 'agent-run-summary-head';
            const type = document.createElement('span');
            type.className = 'agent-run-type';
            type.textContent = entry.type === 'proposal'
                ? (entry.item.kind === 'baseline' ? 'Baseline proposal' : 'Scenario proposal')
                : (['baseline', 'manual'].includes(entry.item.kind) ? 'Baseline run' : 'Scenario run');
            const state = entry.type === 'proposal'
                ? 'Needs review'
                : (entry.item.cancel_requested ? 'Cancel requested' : entry.item.state);
            head.append(type, makeStatePill(state));

            const windowLabel = document.createElement('span');
            windowLabel.className = 'agent-run-window';
            windowLabel.textContent = summaryData.window;
            const chips = document.createElement('span');
            chips.className = 'agent-run-chips';
            const isPromoted = entry.type === 'job' && agentServerState.promoted_baselines?.[entry.item.mode] === entry.item.job_id;
            const highlights = [...summaryData.highlights];
            if (isPromoted) highlights.unshift('Current baseline');
            highlights.slice(0, 2).forEach((value) => {
                const chip = document.createElement('span');
                chip.className = 'agent-run-chip';
                chip.textContent = value;
                chips.appendChild(chip);
            });
            if (highlights.length > 2) {
                const more = document.createElement('span');
                more.className = 'agent-run-chip';
                more.textContent = '+' + (highlights.length - 2) + ' more';
                chips.appendChild(more);
            }

            const foot = document.createElement('span');
            foot.className = 'agent-run-summary-foot';
            const meta = document.createElement('span');
            meta.className = 'agent-run-meta';
            meta.textContent = (summaryData.mode === 'annual' ? 'Annual' : 'Calibration') + ' · ' +
                (entry.type === 'proposal' ? 'Proposal ' + shortAgentId(entry.item.proposal_id) : 'Job ' + shortAgentId(entry.item.job_id));
            const expand = document.createElement('span');
            expand.className = 'agent-run-expand';
            expand.textContent = selected ? 'Hide details' : 'View details';
            foot.append(meta, expand);
            summary.append(head, windowLabel);
            if (chips.childElementCount) summary.appendChild(chips);
            summary.appendChild(foot);

            if (entry.type === 'job' && isAgentJobActive(entry.item)) {
                const progress = Math.min(100, Math.max(0, Number(entry.item.progress) || 0));
                const track = document.createElement('span');
                track.className = 'agent-run-mini-progress';
                track.setAttribute('role', 'progressbar');
                track.setAttribute('aria-label', type.textContent + ' ' + summaryData.window + ' progress');
                track.setAttribute('aria-valuemin', '0');
                track.setAttribute('aria-valuemax', '100');
                track.setAttribute('aria-valuenow', String(progress));
                const fill = document.createElement('span');
                fill.style.width = progress + '%';
                track.appendChild(fill);
                summary.appendChild(track);
            }

            summary.addEventListener('click', () => {
                agentActivitySelection = selected ? null : entry.key;
                renderAgentActivity();
                saveDashboardState();
            });
            record.appendChild(summary);

            const detail = document.createElement('div');
            detail.className = 'agent-run-detail';
            detail.id = detailId;
            detail.hidden = !selected;
            if (selected) {
                detail.appendChild(entry.type === 'proposal' ? buildProposalCard(entry.item) : buildJobCard(entry.item));
            }
            record.appendChild(detail);
            return record;
        }

        function setAgentActivityFilter(filter) {
            agentActivityFilter = ['all', 'review', 'active', 'complete'].includes(filter) ? filter : 'all';
            const selectedEntry = getAgentActivityItems().find((entry) => entry.key === agentActivitySelection);
            if (selectedEntry && !agentActivityMatchesFilter(selectedEntry)) agentActivitySelection = null;
            renderAgentActivity();
            saveDashboardState();
        }

        function captureAgentActivityViewState() {
            const openDetails = new Set();
            agentActivityList.querySelectorAll('details[open]').forEach((details) => {
                const jobId = details.closest('[data-job-id]')?.dataset.jobId;
                if (!jobId) return;
                const kind = details.classList.contains('agent-downloads') ? 'downloads' : 'provenance';
                openDetails.add(jobId + ':' + kind);
            });
            const sweepScrollLeft = new Map();
            agentActivityList.querySelectorAll('[data-sweep-id] .parameter-sweep-table-wrap').forEach((wrap) => {
                const sweepId = wrap.closest('[data-sweep-id]')?.dataset.sweepId;
                if (sweepId) sweepScrollLeft.set(sweepId, wrap.scrollLeft);
            });
            return { openDetails, sweepScrollLeft };
        }

        function restoreAgentActivityViewState(viewState) {
            agentActivityList.querySelectorAll('details').forEach((details) => {
                const jobId = details.closest('[data-job-id]')?.dataset.jobId;
                if (!jobId) return;
                const kind = details.classList.contains('agent-downloads') ? 'downloads' : 'provenance';
                details.open = viewState.openDetails.has(jobId + ':' + kind);
            });
            agentActivityList.querySelectorAll('[data-sweep-id] .parameter-sweep-table-wrap').forEach((wrap) => {
                const sweepId = wrap.closest('[data-sweep-id]')?.dataset.sweepId;
                const scrollLeft = sweepId ? viewState.sweepScrollLeft.get(sweepId) : undefined;
                if (Number.isFinite(scrollLeft)) wrap.scrollLeft = scrollLeft;
            });
        }

        function renderAgentActivityWhenIdle() {
            if (agentActivityInteractionPointerId !== null) {
                agentActivityRenderQueued = true;
                return;
            }
            renderAgentActivity();
        }

        agentActivityList.addEventListener('pointerdown', (event) => {
            if (!event.target.closest?.('.parameter-sweep-table-wrap')) return;
            agentActivityInteractionPointerId = event.pointerId;
        });

        function finishAgentActivityInteraction(event) {
            if (event.pointerId !== agentActivityInteractionPointerId) return;
            agentActivityInteractionPointerId = null;
            if (agentActivityRenderQueued) {
                agentActivityRenderQueued = false;
                renderAgentActivity();
            }
        }

        window.addEventListener('pointerup', finishAgentActivityInteraction);
        window.addEventListener('pointercancel', finishAgentActivityInteraction);

        function syncAgentActivityControls(items = getAgentActivityItems()) {
            const pendingCount = items.filter((entry) => entry.type === 'proposal').length;
            const runningCount = items.filter((entry) => entry.type === 'job' && entry.item.state === 'running' && !entry.item.cancel_requested).length;
            const queuedCount = items.filter((entry) => entry.type === 'job' && entry.item.state === 'queued' && !entry.item.cancel_requested).length;
            const activeCount = runningCount + queuedCount;
            const completeCount = items.filter((entry) => entry.type === 'job' && !isAgentJobActive(entry.item)).length;
            const totalCount = items.length;
            const hasActivity = totalCount > 0;
            const summaryParts = [];
            if (pendingCount) summaryParts.push(pendingCount + (pendingCount === 1 ? ' awaiting review' : ' awaiting review'));
            if (runningCount) summaryParts.push(runningCount + ' running');
            if (queuedCount) summaryParts.push(queuedCount + ' queued');
            summaryParts.push(items.filter((entry) => entry.type === 'job').length + ' recent runs');
            agentActivitySummary.textContent = summaryParts.join(' · ');
            agentActivity.classList.toggle('hidden', !hasActivity);
            agentActivityToggle.classList.toggle('hidden', !hasActivity);
            agentActivityCount.textContent = String(totalCount);
            agentActivityToggleLabel.textContent = 'Runs';
            const filterCounts = { all: totalCount, review: pendingCount, active: activeCount, complete: completeCount };
            agentActivity.querySelectorAll('[data-agent-activity-filter]').forEach((button) => {
                const filter = button.dataset.agentActivityFilter;
                const selected = filter === agentActivityFilter;
                button.classList.toggle('selected', selected);
                button.setAttribute('aria-pressed', String(selected));
                const count = button.querySelector('[data-agent-filter-count]');
                if (count) count.textContent = String(filterCounts[filter] || 0);
            });
            if (!hasActivity) {
                agentActivityExpanded = false;
                agentActivitySelection = null;
            }
            setAgentActivityOpen(agentActivityExpanded, false);
            const actionable = summaryParts.slice(0, -1).join(', ') || totalCount + ' completed runs';
            agentActivityToggle.setAttribute('aria-label', (agentActivityExpanded ? 'Close' : 'Open') + ' scenario runs, ' + actionable);
        }

        function renderAgentActivity() {
            const editorState = captureAgentEditorState();
            const viewState = captureAgentActivityViewState();
            const activityScrollTop = agentActivityBody.scrollTop;
            const focusedKey = document.activeElement?.closest?.('[data-agent-run-row]')?.dataset.agentRunRow || null;
            const items = getAgentActivityItems();
            if (agentActivitySelection && !items.some((entry) => entry.key === agentActivitySelection)) {
                agentActivitySelection = null;
            }
            const visibleItems = items.filter((entry) => agentActivityMatchesFilter(entry));
            const visibleSweeps = getAgentParameterSweepGroups()
                .filter((group) => agentParameterSweepMatchesFilter(group));
            agentActivityList.innerHTML = '';
            if (!visibleItems.length && !visibleSweeps.length) {
                const empty = document.createElement('div');
                empty.className = 'agent-activity-empty';
                empty.textContent = agentActivityFilter === 'all'
                    ? 'Ask Solar Agent to run a scenario. Each time window and model configuration will appear here.'
                    : 'No runs match this filter.';
                agentActivityList.appendChild(empty);
            } else {
                visibleSweeps.forEach((group) => agentActivityList.appendChild(buildParameterSweepComparisonCard(group)));
                visibleItems.forEach((entry) => agentActivityList.appendChild(buildAgentRunSummary(entry)));
            }
            restoreAgentEditorState(editorState);
            restoreAgentActivityViewState(viewState);
            agentActivityBody.scrollTop = activityScrollTop;
            if (!editorState.some((editor) => editor.focusedField) && focusedKey) {
                Array.from(agentActivityList.querySelectorAll('[data-agent-run-row]'))
                    .find((element) => element.dataset.agentRunRow === focusedKey)
                    ?.focus({ preventScroll: true });
            }
            syncAgentActivityControls(items);
            updateAgentElapsedLabels();
            updateAgentContext();
        }

        function renderAgentJobUpdate(job) {
            if (!job || !job.job_id) return;
            renderAgentActivityWhenIdle();
        }

        function formatElapsed(milliseconds) {
            const seconds = Math.max(0, Math.floor(milliseconds / 1000));
            if (seconds < 60) return seconds + 's';
            const minutes = Math.floor(seconds / 60);
            if (minutes < 60) return minutes + 'm ' + (seconds % 60) + 's';
            return Math.floor(minutes / 60) + 'h ' + (minutes % 60) + 'm';
        }

        function updateAgentElapsedLabels() {
            document.querySelectorAll('.agent-elapsed[data-started-at]').forEach((element) => {
                const card = element.closest('[data-job-id]');
                const job = card ? agentJobSnapshots.get(card.dataset.jobId) : null;
                const start = Number(element.dataset.startedAt) || Date.now();
                const end = Number(element.dataset.endedAt) || Date.now();
                const progress = Math.min(100, Math.max(0, Number(job?.progress) || 0));
                element.textContent = Math.round(progress) + '% · ' + formatElapsed(end - start) + ' elapsed';
            });
        }

        function syncTrackedMainRunFromAgentJob(job) {
            if (!job || !isAgentJobTerminal(job)) return;
            if (job.job_id === latestJobId) {
                invalidateValidationStatusPoll();
                currentRunState = { state: job.state, progress: job.progress || 0, stage: job.stage || '' };
                if (job.state === 'done' && job.result) {
                    latestResult = job.result;
                    latestInputPlots = job.input_plots || job.result.input_plots || null;
                    applyResult(job.result);
                } else {
                    showError(job.error || (job.state === 'cancelled' ? 'Run was cancelled.' : 'Run did not complete.'));
                    progressWrap.classList.remove('visible');
                }
                resetRunBtn();
                saveDashboardState();
            }
            if (job.job_id === annualLatestJobId) {
                invalidateAnnualStatusPoll();
                annualRunState = { state: job.state, progress: job.progress || 0, stage: job.stage || '' };
                if (job.state === 'done' && job.result) {
                    annualLatestResult = job.result;
                    applyAnnualResult(job.result);
                } else {
                    showAnnualError(job.error || (job.state === 'cancelled' ? 'Annual run was cancelled.' : 'Annual run did not complete.'));
                    annualProgressWrap.classList.remove('visible');
                }
                resetAnnualRunBtn();
                saveDashboardState();
            }
        }

        function scheduleAgentJobPoll(jobId, delay = 800, failureCount = 0) {
            const current = agentJobSnapshots.get(jobId);
            if (!jobId || isAgentJobTerminal(current)) return;
            const existing = agentJobPollTimers.get(jobId);
            if (existing) clearTimeout(existing);
            agentJobPollTimers.set(jobId, setTimeout(() => pollAgentJob(jobId, failureCount), delay));
        }

        function forgetUnavailableAgentJob(jobId) {
            const timer = agentJobPollTimers.get(jobId);
            if (timer) clearTimeout(timer);
            agentJobPollTimers.delete(jobId);
            agentJobSnapshots.delete(jobId);
            agentJobStartedAt.delete(jobId);
            updateStoredChatActionCardStatus({ job_id: jobId }, 'unavailable');
            if (latestJobId === jobId) {
                invalidateValidationStatusPoll();
                latestJobId = null;
                latestInputPlots = null;
                latestResult = null;
                currentRunState = null;
                clearRunImages();
                setExcelLink(null);
                renderValidationRunContext(null);
                resetRunBtn();
            }
            if (annualLatestJobId === jobId) {
                invalidateAnnualStatusPoll();
                annualLatestJobId = null;
                annualLatestResult = null;
                annualRunState = null;
                clearAnnualImages();
                setAnnualExcelLink(null);
                resetAnnualRunBtn();
            }
            renderAgentActivity();
            saveDashboardState();
        }

        async function pollAgentJob(jobId, failureCount = 0) {
            agentJobPollTimers.delete(jobId);
            try {
                const response = await fetch('/api/status/' + encodeURIComponent(jobId), { cache: 'no-store' });
                if (response.status === 404) {
                    forgetUnavailableAgentJob(jobId);
                    return;
                }
                const data = await readAgentResponse(response, 'Scenario status is temporarily unavailable.');
                const previous = agentJobSnapshots.get(jobId);
                putAgentJob(data);
                syncTrackedMainRunFromAgentJob(data);
                if (isAgentParameterSweepJob(data) && agentActivityFilter === 'active') {
                    const sweepId = agentParameterSweepMetadata(data)?.sweep_id;
                    const group = getAgentParameterSweepGroups().find((item) => item.sweep_id === sweepId);
                    const expected = Number(group?.metadata?.candidate_count || 0);
                    if (group && !group.proposals.length && group.jobs.length >= expected && group.jobs.every(isAgentJobTerminal)) {
                        agentActivityFilter = 'complete';
                    }
                }
                renderAgentJobUpdate(data);
                if (isAgentJobTerminal(data) && (
                    !isAgentJobTerminal(previous) || previous?.state !== data.state
                )) {
                    announceAgentCompletion(data);
                }
                if (isAgentJobTerminal(data)) await refreshAgentState(false);
                else scheduleAgentJobPoll(jobId, 800, 0);
            } catch (error) {
                const current = agentJobSnapshots.get(jobId) || { job_id: jobId };
                const nextFailureCount = failureCount + 1;
                const reconnecting = nextFailureCount <= AGENT_POLL_MAX_FAILURES;
                putAgentJob({
                    ...current,
                    stage: reconnecting
                        ? 'Reconnecting to model worker (' + nextFailureCount + '/' + AGENT_POLL_MAX_FAILURES + ')...'
                        : 'Status unavailable after repeated attempts',
                });
                renderAgentJobUpdate(agentJobSnapshots.get(jobId));
                if (reconnecting) {
                    scheduleAgentJobPoll(
                        jobId,
                        Math.min(STATUS_POLL_MAX_DELAY_MS, 900 * (2 ** Math.max(0, nextFailureCount - 1))),
                        nextFailureCount
                    );
                }
            }
        }

        function trackedChatCardForJob(job) {
            syncActiveChatConversation();
            const sweepId = agentParameterSweepMetadata(job)?.sweep_id;
            return chatConversations.some((conversation) => (
                conversation.messages.some((message) => {
                    const card = normalizeChatActionCard(message.action_card);
                    if (!card) return false;
                    if (sweepId && card.sweep_id === sweepId) return true;
                    return card.job_id === job.job_id ||
                        card.job_ids?.includes(job.job_id) ||
                        (!!job.proposal_id && (
                            card.proposal_id === job.proposal_id ||
                            card.proposal_ids?.includes(job.proposal_id)
                        ));
                })
            ));
        }

        function reconcileTerminalAgentCards() {
            Array.from(agentJobSnapshots.values()).forEach((job) => {
                if (job.proposal_id) {
                    updateStoredChatActionCardStatus(
                        { proposal_id: job.proposal_id },
                        job.state || 'queued'
                    );
                }
                if (agentParameterSweepMetadata(job) || !trackedChatCardForJob(job)) return;
                updateStoredChatActionCardStatus({ job_id: job.job_id }, job.state || 'queued');
                if (!isAgentJobTerminal(job)) return;
                const completionKey = 'job:' + job.job_id;
                if (agentCompletionCards.has(completionKey)) {
                    return;
                }
                announceAgentCompletion(job);
            });
            getAgentParameterSweepGroups().forEach((group) => {
                const tracked = group.jobs.some(trackedChatCardForJob);
                if (!tracked || !group.jobs.length) return;
                const expected = Number(group.metadata?.candidate_count || 0);
                const complete = !group.proposals.length && expected > 0 &&
                    group.jobs.length >= expected && group.jobs.every(isAgentJobTerminal);
                const status = complete
                    ? (group.jobs.some((job) => job.state !== 'done') ? 'error' : 'done')
                    : (group.jobs.some((job) => job.state === 'running') ? 'running' : 'queued');
                updateStoredChatActionCardStatus({ sweep_id: group.sweep_id }, status);
                const completionKey = 'sweep:' + group.sweep_id;
                if (complete && !agentCompletionCards.has(completionKey)) {
                    announceAgentCompletion(group.jobs[0]);
                }
            });
        }

        async function recoverSavedNonterminalActionJobs() {
            const missingJobIds = savedNonterminalActionJobIds()
                .filter((jobId) => !agentJobSnapshots.has(jobId));
            await Promise.all(missingJobIds.map(async (jobId) => {
                try {
                    const response = await fetchWithDashboardTimeout(
                        '/api/status/' + encodeURIComponent(jobId),
                        { cache: 'no-store' }
                    );
                    if (response.status === 404) {
                        forgetUnavailableAgentJob(jobId);
                        return;
                    }
                    putAgentJob(await readAgentResponse(response, 'Could not restore this scenario run.'));
                } catch (_) {
                    // Preserve the saved card so a later manual refresh can retry it.
                }
            }));
        }

