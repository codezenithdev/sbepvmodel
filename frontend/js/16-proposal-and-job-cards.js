        function makeAgentButton(label, className, onClick) {
            const button = document.createElement('button');
            button.type = 'button';
            button.className = 'agent-action-btn' + (className ? ' ' + className : '');
            button.textContent = label;
            button.addEventListener('click', onClick);
            return button;
        }

        function makeStatePill(state) {
            const pill = document.createElement('span');
            const normalized = String(state || 'pending').toLowerCase().replace(/\s+/g, '-');
            pill.className = 'agent-state-pill ' + normalized;
            pill.textContent = humanizeAgentField(state || 'pending');
            return pill;
        }

        function labelAgentTable(table) {
            if (!table) return;
            const headers = Array.from(table.querySelectorAll('thead th')).map((header) => header.textContent.trim());
            table.querySelectorAll('tbody tr').forEach((row) => {
                Array.from(row.children).forEach((cell, index) => {
                    cell.dataset.label = headers[index] || headers.at(-1) || 'Value';
                });
            });
        }

        function makeAgentEditInput(change) {
            const field = String(change.field || '');
            const current = change.to;
            let input;
            if (typeof current === 'boolean' || /(?:backtrack|enabled)$/.test(field)) {
                input = document.createElement('select');
                [{ value: 'true', label: 'Enabled' }, { value: 'false', label: 'Disabled' }].forEach((optionData) => {
                    const option = document.createElement('option');
                    option.value = optionData.value;
                    option.textContent = optionData.label;
                    input.appendChild(option);
                });
                input.value = String(current === true || current === 'true');
                input.dataset.valueType = 'boolean';
            } else if (field === 'iam_model' || field === 'iam_method') {
                input = document.createElement('select');
                [{ value: 'physical', label: 'Physical' }, { value: 'martin_ruiz', label: 'Martin–Ruiz' }].forEach((optionData) => {
                    const option = document.createElement('option');
                    option.value = optionData.value;
                    option.textContent = optionData.label;
                    input.appendChild(option);
                });
                input.value = String(current || 'physical');
                input.dataset.valueType = 'string';
            } else if (field === 'interval_unit') {
                input = document.createElement('select');
                ['minutes', 'hours', 'days'].forEach((value) => {
                    const option = document.createElement('option');
                    option.value = value;
                    option.textContent = value;
                    input.appendChild(option);
                });
                input.value = String(current || 'hours');
                input.dataset.valueType = 'string';
            } else {
                input = document.createElement('input');
                if (/_date$/.test(field)) input.type = 'date';
                else if (/_time$/.test(field)) input.type = 'time';
                else if (typeof current === 'number' || /(?:efficiency|limit_kw|iam_a_r|interval_value)$/.test(field)) {
                    input.type = 'number';
                    input.step = 'any';
                    input.dataset.valueType = 'number';
                } else {
                    input.type = 'text';
                    input.dataset.valueType = 'string';
                }
                input.value = current === null || current === undefined ? '' : String(current);
            }
            input.className = 'agent-edit-input';
            input.dataset.overrideField = field;
            input.setAttribute('aria-label', change.label || humanizeAgentField(field));
            return input;
        }

        function readAgentEditOverrides(form) {
            const overrides = {};
            form.querySelectorAll('[data-override-field]').forEach((input) => {
                const field = input.dataset.overrideField;
                if (input.dataset.valueType === 'boolean') overrides[field] = input.value === 'true';
                else if (input.dataset.valueType === 'number') overrides[field] = Number(input.value);
                else overrides[field] = input.value;
            });
            return overrides;
        }

        function buildProposalCard(proposal) {
            const card = document.createElement('article');
            card.className = 'agent-card proposal-card';
            card.dataset.proposalId = proposal.proposal_id;
            const head = document.createElement('div');
            head.className = 'agent-card-head';
            const heading = document.createElement('div');
            const title = document.createElement('div');
            title.className = 'agent-card-title';
            title.textContent = proposal.kind === 'baseline' ? 'Baseline run proposal' : 'Scenario proposal';
            const meta = document.createElement('div');
            meta.className = 'agent-card-meta';
            const runSummary = summarizeAgentRequest({ type: 'proposal', item: proposal });
            meta.textContent = (proposal.mode === 'annual' ? 'Annual' : 'Calibration') + ' · ' + runSummary.window +
                (proposal.baseline_job_id ? ' · Baseline ' + shortAgentId(proposal.baseline_job_id) : '');
            heading.append(title, meta);
            const expiresAt = proposal.expires_at ? Date.parse(proposal.expires_at) : NaN;
            const isExpired = Number.isFinite(expiresAt) && expiresAt <= Date.now();
            head.append(heading, makeStatePill(isExpired ? 'expired' : proposal.status));
            card.appendChild(head);

            const configuration = buildAgentRunConfiguration(proposal.effective_request, proposal.mode);
            if (configuration) card.appendChild(configuration);

            const changes = Array.isArray(proposal.changes) ? proposal.changes : [];
            if (changes.length) {
                const table = document.createElement('table');
                table.className = 'agent-change-table';
                table.innerHTML = '<thead><tr><th>Parameter</th><th>Baseline</th><th>Scenario</th></tr></thead>';
                const body = document.createElement('tbody');
                changes.forEach((change) => {
                    const row = document.createElement('tr');
                    [change.label || humanizeAgentField(change.field), formatAgentValue(change.from, change.unit), formatAgentValue(change.to, change.unit)].forEach((value) => {
                        const cell = document.createElement('td');
                        cell.textContent = value;
                        row.appendChild(cell);
                    });
                    body.appendChild(row);
                });
                table.appendChild(body);
                labelAgentTable(table);
                card.appendChild(table);
            }

            const comparisonKind = proposal.comparison_kind || 'same_input';
            const reason = document.createElement('div');
            reason.className = 'agent-card-note' + (comparisonKind === 'cross_run' ? ' cross-run' : '');
            reason.textContent = comparisonKind === 'cross_run'
                ? 'Different interval or source data: ' + (proposal.confirmation_reason || 'results are descriptive only and must not be attributed to one parameter. Run the same interval with different parameters for a controlled comparison.')
                : (proposal.confirmation_reason || (proposal.confirmation_required ? 'Confirmation is required before this run starts.' : 'Same interval and source data; only the requested parameters change.'));
            card.appendChild(reason);

            const effective = proposal.effective_request;
            if (effective && typeof effective === 'object') {
                const changedFields = new Set(changes.map((change) => change.field));
                const unchanged = Object.entries(effective).filter(([field]) => !changedFields.has(field));
                if (unchanged.length) {
                    const details = document.createElement('details');
                    details.className = 'agent-details';
                    const summary = document.createElement('summary');
                    summary.textContent = 'Unchanged configuration (' + unchanged.length + ')';
                    const grid = document.createElement('div');
                    grid.className = 'agent-details-grid';
                    unchanged.forEach(([field, value]) => {
                        const item = document.createElement('div');
                        const label = document.createElement('strong');
                        label.textContent = humanizeAgentField(field);
                        item.append(label, document.createTextNode(formatAgentValue(value)));
                        grid.appendChild(item);
                    });
                    details.append(summary, grid);
                    card.appendChild(details);
                }
            }

            const editForm = document.createElement('form');
            editForm.className = 'agent-edit-form hidden';
            editForm.id = 'agent-edit-' + proposal.proposal_id;
            editForm.setAttribute('aria-label', 'Edit scenario overrides');
            changes.forEach((change) => {
                const label = document.createElement('label');
                label.className = 'agent-edit-field';
                const text = document.createElement('span');
                text.textContent = change.label || humanizeAgentField(change.field);
                label.append(text, makeAgentEditInput(change));
                editForm.appendChild(label);
            });
            let editButton = null;
            const saveEditButton = makeAgentButton('Save changes', 'primary', async () => {
                const overrides = readAgentEditOverrides(editForm);
                if (Object.prototype.hasOwnProperty.call(overrides, 'interval_value') && !overrides.interval_unit) {
                    overrides.interval_unit = proposal.effective_request?.interval_unit;
                }
                await editAgentProposal(proposal.proposal_id, overrides);
            });
            const cancelEditButton = makeAgentButton('Cancel edit', '', () => {
                editForm.classList.add('hidden');
                editButton?.setAttribute('aria-expanded', 'false');
                editButton?.focus();
            });
            const editActions = document.createElement('div');
            editActions.className = 'agent-card-actions';
            editActions.append(saveEditButton, cancelEditButton);
            editForm.appendChild(editActions);
            editForm.addEventListener('submit', (event) => {
                event.preventDefault();
                saveEditButton.click();
            });
            card.appendChild(editForm);

            if (!isExpired && (proposal.status === 'pending' || !proposal.status)) {
                const actions = document.createElement('div');
                actions.className = 'agent-card-actions';
                editButton = makeAgentButton('Edit changes', '', () => {
                    const opening = editForm.classList.contains('hidden');
                    editForm.classList.toggle('hidden', !opening);
                    editButton.setAttribute('aria-expanded', String(opening));
                    if (opening) editForm.querySelector('[data-override-field]')?.focus();
                });
                editButton.setAttribute('aria-controls', editForm.id);
                editButton.setAttribute('aria-expanded', 'false');
                actions.append(
                    makeAgentButton(proposal.kind === 'baseline' ? 'Approve & run baseline' : 'Approve & run', 'primary', () => confirmAgentProposal(proposal.proposal_id)),
                    editButton,
                    makeAgentButton('Dismiss', 'danger', () => dismissAgentProposal(proposal.proposal_id))
                );
                card.appendChild(actions);
            }
            if (proposal.expires_at) {
                const expiry = document.createElement('div');
                expiry.className = 'agent-card-meta';
                const date = new Date(proposal.expires_at);
                expiry.textContent = Number.isNaN(date.getTime()) ? '' : 'Expires ' + date.toLocaleString();
                if (expiry.textContent) card.appendChild(expiry);
            }
            return card;
        }

        function firstDefined(object, names) {
            for (const name of names) {
                if (object && object[name] !== undefined && object[name] !== null) return object[name];
            }
            return null;
        }

        function comparisonPercent(value) {
            if (value === null || value === undefined || !Number.isFinite(Number(value))) return '—';
            const number = Number(value);
            return (number >= 0 ? '+' : '') + number.toFixed(2) + '%';
        }

        function agentParameterSweepMetadata(item) {
            const metadata = item?.scenario_sweep || item?.provenance?.scenario_sweep;
            if (!metadata || metadata.type !== 'parameter_sweep' || !metadata.parameter || !metadata.sweep_id) return null;
            return metadata;
        }

        function isAgentParameterSweepJob(job) {
            return !!agentParameterSweepMetadata(job);
        }

        function getAgentParameterSweepGroups() {
            const groups = new Map();
            const addMember = (item, collection) => {
                const metadata = agentParameterSweepMetadata(item);
                if (!metadata) return;
                const sweepId = String(metadata.sweep_id);
                if (!groups.has(sweepId)) {
                    groups.set(sweepId, {
                        sweep_id: sweepId,
                        metadata: { ...metadata },
                        jobs: [],
                        proposals: [],
                        created_at: item.created_at || null,
                    });
                }
                const group = groups.get(sweepId);
                group.metadata = { ...group.metadata, ...metadata };
                group[collection].push(item);
                const timestamp = item.created_at ? Date.parse(item.created_at) : NaN;
                const currentTimestamp = group.created_at ? Date.parse(group.created_at) : NaN;
                if (Number.isFinite(timestamp) && (!Number.isFinite(currentTimestamp) || timestamp < currentTimestamp)) {
                    group.created_at = item.created_at;
                }
            };
            agentProposalSnapshots.forEach((proposal) => addMember(proposal, 'proposals'));
            agentJobSnapshots.forEach((job) => {
                if (isAgentJobInActivityWorkspace(job)) addMember(job, 'jobs');
            });
            return Array.from(groups.values())
                .map((group) => {
                    const latestJobsByIndex = new Map();
                    group.jobs.forEach((job) => {
                        const index = Number(agentParameterSweepMetadata(job)?.index);
                        const existing = latestJobsByIndex.get(index);
                        const jobTime = job.created_at ? Date.parse(job.created_at) : 0;
                        const existingTime = existing?.created_at ? Date.parse(existing.created_at) : 0;
                        if (!existing || jobTime >= existingTime) latestJobsByIndex.set(index, job);
                    });
                    group.jobs = Array.from(latestJobsByIndex.values());
                    group.jobs.sort((left, right) => Number(agentParameterSweepMetadata(left)?.index) - Number(agentParameterSweepMetadata(right)?.index));
                    group.proposals.sort((left, right) => Number(agentParameterSweepMetadata(left)?.index) - Number(agentParameterSweepMetadata(right)?.index));
                    return group;
                })
                .sort((left, right) => {
                    const leftTime = left.created_at ? Date.parse(left.created_at) : 0;
                    const rightTime = right.created_at ? Date.parse(right.created_at) : 0;
                    return rightTime - leftTime;
                });
        }

        function agentParameterSweepState(group) {
            if (group.proposals.length) return 'needs review';
            if (group.jobs.some((job) => job.state === 'running')) return 'running';
            if (group.jobs.some((job) => job.state === 'queued')) return 'queued';
            const expected = Number(group.metadata?.candidate_count || 0);
            if (expected > 0 && group.jobs.length < expected) return 'incomplete';
            if (group.jobs.some((job) => ['error', 'cancelled', 'interrupted'].includes(job.state))) return 'error';
            if (expected > 0 && group.jobs.length >= expected && group.jobs.every((job) => job.state === 'done')) return 'done';
            return group.jobs.length ? 'incomplete' : 'pending';
        }

        function agentParameterSweepMatchesFilter(group, filter = agentActivityFilter) {
            if (filter === 'all') return true;
            if (filter === 'review') return group.proposals.length > 0;
            const active = group.jobs.some((job) => !isAgentJobTerminal(job));
            if (filter === 'active') return active;
            return filter === 'complete' && !group.proposals.length && !active;
        }

        function parameterSweepSystemValues(comparison, systemName) {
            const systems = comparison?.systems || comparison?.per_system || {};
            if (Array.isArray(systems)) {
                return systems.find((item) => String(item?.system || item?.name || '').toLowerCase() === systemName) || null;
            }
            return systems[systemName]
                || systems[systemName === 'solaredge' ? 'SolarEdge' : 'Solectria']
                || null;
        }

        function compactChatComparisonSystems(comparison) {
            const systems = comparison?.systems || comparison?.per_system || {};
            const entries = Array.isArray(systems)
                ? systems.map((item) => [item?.system || item?.name || 'System', item])
                : Object.entries(systems);
            return entries
                .filter(([, values]) => values && typeof values === 'object')
                .slice(0, 4)
                .map(([name, values]) => {
                    const normalizedName = String(name || '').toLowerCase();
                    return {
                        name: normalizedName === 'solaredge'
                            ? 'SolarEdge'
                            : normalizedName === 'solectria'
                                ? 'Solectria'
                                : humanizeAgentField(name),
                        baseline_kwh: firstDefined(values, ['baseline_predicted_kwh', 'baseline_kwh', 'baseline']),
                        predicted_kwh: firstDefined(values, ['candidate_predicted_kwh', 'scenario_predicted_kwh', 'candidate_kwh', 'candidate']),
                        delta_pct: firstDefined(values, ['delta_pct', 'change_pct', 'percent_change']),
                    };
                });
        }

        function buildRunCompletionChatCard(job) {
            const baseline = ['baseline', 'manual'].includes(job.kind);
            const successful = job.state === 'done';
            return normalizeChatActionCard({
                kind: 'run_complete',
                title: baseline
                    ? (successful ? 'Baseline model run complete' : 'Baseline model run stopped')
                    : (successful ? 'Scenario comparison complete' : 'Scenario model run stopped'),
                status: job.state,
                mode: job.mode,
                job_id: job.job_id,
                baseline_job_id: job.baseline_job_id,
                run_kind: job.kind,
                window: compactAgentRunWindow(job.request || {}, job.mode),
                systems: compactChatComparisonSystems(job.comparison),
                error: successful ? null : (job.error || job.stage || 'The model run did not complete.'),
                elapsed_seconds: job.elapsed_seconds,
            });
        }

        function buildSweepCompletionChatCard(group) {
            const metadata = group.metadata || {};
            const values = Array.isArray(metadata.values) ? metadata.values.map(Number) : [];
            const referenceComparison = group.jobs.find((job) => job.state === 'done' && job.comparison)?.comparison || null;
            const rows = values.map((value, index) => {
                const job = group.jobs.find((item) => Number(agentParameterSweepMetadata(item)?.index) === index);
                const isBaselineValue = Number(metadata.baseline_index) === index &&
                    metadata.baseline_index !== null && metadata.baseline_index !== undefined;
                const comparison = job?.comparison || null;
                const solarEdge = parameterSweepSystemValues(comparison, 'solaredge');
                const solectria = parameterSweepSystemValues(comparison, 'solectria');
                const referenceSolarEdge = parameterSweepSystemValues(referenceComparison, 'solaredge');
                const referenceSolectria = parameterSweepSystemValues(referenceComparison, 'solectria');
                return {
                    value,
                    state: isBaselineValue && !job ? 'baseline' : (job?.state || 'unavailable'),
                    job_id: job?.job_id,
                    solaredge_kwh: isBaselineValue && !job
                        ? firstDefined(referenceSolarEdge, ['baseline_predicted_kwh', 'baseline_kwh', 'baseline'])
                        : firstDefined(solarEdge, ['candidate_predicted_kwh', 'scenario_predicted_kwh', 'candidate_kwh', 'candidate']),
                    solaredge_delta_pct: isBaselineValue && !job
                        ? 0
                        : firstDefined(solarEdge, ['delta_pct', 'change_pct', 'percent_change']),
                    solectria_kwh: isBaselineValue && !job
                        ? firstDefined(referenceSolectria, ['baseline_predicted_kwh', 'baseline_kwh', 'baseline'])
                        : firstDefined(solectria, ['candidate_predicted_kwh', 'scenario_predicted_kwh', 'candidate_kwh', 'candidate']),
                    solectria_delta_pct: isBaselineValue && !job
                        ? 0
                        : firstDefined(solectria, ['delta_pct', 'change_pct', 'percent_change']),
                };
            });
            const errorCount = group.jobs.filter((job) => job.state !== 'done').length;
            const expectedCount = Number(metadata.candidate_count || group.jobs.length);
            const missingCount = Math.max(0, expectedCount - group.jobs.length);
            return normalizeChatActionCard({
                kind: 'sweep_complete',
                title: String(metadata.label || 'Parameter') + ' sweep comparison',
                status: errorCount ? 'error' : 'done',
                mode: metadata.mode,
                sweep_id: group.sweep_id,
                job_ids: group.jobs.map((job) => job.job_id),
                baseline_job_id: metadata.baseline_job_id,
                label: metadata.label,
                unit: metadata.unit,
                parameter: metadata.parameter,
                values,
                count: values.length,
                candidate_count: expectedCount,
                error_count: errorCount + missingCount,
                rows,
            });
        }

        function appendAutomatedChatCardMessage(content, actionCard, options = {}) {
            const assistantMessage = assistantMessageFromResponse(content, {
                automated: true,
                action_card: actionCard,
                timing: {
                    response_timestamp: new Date().toISOString(),
                    model_run_seconds: options.model_run_seconds,
                    model_run_status: options.model_run_status || 'completed',
                },
            });
            const targetConversation = (
                options.origin_conversation ||
                (options.origin_conversation_id
                    ? chatConversations.find((conversation) => conversation.id === options.origin_conversation_id)
                    : null)
            ) || chatConversationForActionCard(actionCard);
            if (targetConversation && targetConversation.id !== activeChatConversationId) {
                targetConversation.messages.push(assistantMessage);
                targetConversation.messages = trimChatMessages(targetConversation.messages);
                targetConversation.title = chatConversationTitle(
                    targetConversation.messages,
                    targetConversation.draft
                );
                targetConversation.updated_at = assistantMessage.created_at;
                targetConversation.unread = true;
                renderChatHistory();
                return saveDashboardState();
            }
            appendMessage('assistant', content, assistantMessage);
            chatMessages.push(assistantMessage);
            chatMessages = trimChatMessages(chatMessages);
            renderChatFollowups();
            const historySaved = saveDashboardState();
            scrollChatToBottom();
            return historySaved;
        }

        function rememberAgentCompletionCard(key) {
            agentCompletionCards.add(key);
            while (agentCompletionCards.size > 100) {
                const oldest = agentCompletionCards.values().next().value;
                if (!oldest) break;
                agentCompletionCards.delete(oldest);
            }
        }

        function announceAgentCompletion(job) {
            if (!isAgentJobTerminal(job)) return;
            const sweepMetadata = agentParameterSweepMetadata(job);
            if (sweepMetadata) {
                const group = getAgentParameterSweepGroups().find((item) => item.sweep_id === sweepMetadata.sweep_id);
                const expected = Number(group?.metadata?.candidate_count || 0);
                if (!group || group.proposals.length || expected <= 0 ||
                    group.jobs.length < expected || !group.jobs.every(isAgentJobTerminal)) return;
                const completionKey = 'sweep:' + group.sweep_id;
                if (agentCompletionCards.has(completionKey)) return;
                const card = buildSweepCompletionChatCard(group);
                const errorCount = card?.error_count || 0;
                const label = String(card?.label || 'parameter');
                const originConversation = chatConversationForActionCard({ sweep_id: group.sweep_id });
                if (originConversation) transientProtectedConversationIds.add(originConversation.id);
                try {
                    updateStoredChatActionCardStatus(
                        { sweep_id: group.sweep_id },
                        errorCount ? 'error' : 'done',
                        { persist: false }
                    );
                    appendAutomatedChatCardMessage(
                        errorCount
                            ? `The ${label} sweep finished with ${errorCount} run issue${errorCount === 1 ? '' : 's'}.`
                            : `The ${label} sweep is complete, and the comparison is ready.`,
                        card,
                        {
                            model_run_status: errorCount ? 'failed' : 'completed',
                            origin_conversation: originConversation,
                        }
                    );
                    rememberAgentCompletionCard(completionKey);
                } finally {
                    if (originConversation) transientProtectedConversationIds.delete(originConversation.id);
                }
                return;
            }

            const completionKey = 'job:' + job.job_id;
            if (agentCompletionCards.has(completionKey)) return;
            const card = buildRunCompletionChatCard(job);
            const baseline = ['baseline', 'manual'].includes(job.kind);
            const successful = job.state === 'done';
            const originConversation = chatConversationForActionCard({ job_id: job.job_id });
            if (originConversation) transientProtectedConversationIds.add(originConversation.id);
            try {
                updateStoredChatActionCardStatus(
                    { job_id: job.job_id },
                    job.state,
                    { persist: false }
                );
                appendAutomatedChatCardMessage(
                    successful
                        ? (baseline ? 'The baseline model run is complete.' : 'The scenario comparison is complete.')
                        : (baseline ? 'The baseline model run stopped before completion.' : 'The scenario model run stopped before completion.'),
                    card,
                    {
                        model_run_seconds: job.elapsed_seconds,
                        model_run_status: successful ? 'completed' : 'failed',
                        origin_conversation: originConversation,
                    }
                );
                rememberAgentCompletionCard(completionKey);
            } finally {
                if (originConversation) transientProtectedConversationIds.delete(originConversation.id);
            }
        }

        function buildParameterSweepComparisonCard(group) {
            const metadata = group.metadata || {};
            const values = Array.isArray(metadata.values) ? metadata.values.map(Number) : [];
            const section = document.createElement('section');
            section.className = 'agent-card parameter-sweep-card';
            section.dataset.sweepId = group.sweep_id;
            section.setAttribute('aria-label', String(metadata.label || 'Model parameter') + ' sweep comparison');

            const head = document.createElement('div');
            head.className = 'agent-card-head';
            const heading = document.createElement('div');
            const title = document.createElement('div');
            title.className = 'agent-card-title';
            title.textContent = String(metadata.label || humanizeAgentField(metadata.parameter)) + ' sweep comparison';
            const completedJobs = group.jobs.filter((job) => job.state === 'done').length;
            const expectedJobs = Number(metadata.candidate_count || group.jobs.length);
            const availableJobs = group.jobs.length;
            const meta = document.createElement('div');
            meta.className = 'agent-card-meta';
            meta.textContent = (metadata.mode === 'annual' ? 'Annual' : 'Calibration') + ' · ' +
                values.length + ' values · ' + completedJobs + '/' + expectedJobs +
                ' scenario runs complete · ' + availableJobs + '/' + expectedJobs +
                ' available · Baseline ' + shortAgentId(metadata.baseline_job_id);
            heading.append(title, meta);
            head.append(heading, makeStatePill(agentParameterSweepState(group)));
            section.appendChild(head);

            const note = document.createElement('div');
            note.className = 'agent-card-note';
            note.textContent = 'Across the sweep rows, all other model inputs and source data stay fixed. Predicted energy and deltas are compared with the ' +
                String(metadata.baseline_label || 'selected') + ' baseline; positive delta means more predicted energy.';
            section.appendChild(note);
            if (agentParameterSweepState(group) === 'incomplete') {
                const incomplete = document.createElement('div');
                incomplete.className = 'agent-card-note cross-run';
                incomplete.textContent = 'Incomplete sweep history: expected ' + expectedJobs +
                    ' scenario runs; ' + availableJobs + ' are available.';
                section.appendChild(incomplete);
            }

            const referenceComparison = group.jobs.find((job) => job.state === 'done' && job.comparison)?.comparison || null;
            const table = document.createElement('table');
            table.className = 'comparison-table parameter-sweep-table';
            table.innerHTML = '<thead><tr><th>Value</th><th>Status</th><th>SolarEdge kWh</th><th>SE Δ vs baseline</th><th>Solectria kWh</th><th>Solectria Δ vs baseline</th></tr></thead>';
            const body = document.createElement('tbody');
            values.forEach((value, index) => {
                const job = group.jobs.find((item) => Number(agentParameterSweepMetadata(item)?.index) === index);
                const proposal = group.proposals.find((item) => Number(agentParameterSweepMetadata(item)?.index) === index);
                const isBaselineValue = Number(metadata.baseline_index) === index && metadata.baseline_index !== null && metadata.baseline_index !== undefined;
                const comparison = job?.comparison || null;
                const solarEdge = parameterSweepSystemValues(comparison, 'solaredge');
                const solectria = parameterSweepSystemValues(comparison, 'solectria');
                const referenceSolarEdge = parameterSweepSystemValues(referenceComparison, 'solaredge');
                const referenceSolectria = parameterSweepSystemValues(referenceComparison, 'solectria');
                let status = 'Not available';
                if (isBaselineValue && !job) status = 'Baseline';
                else if (proposal) status = 'Needs review';
                else if (job?.state === 'running') status = 'Running ' + Math.round(Number(job.progress) || 0) + '%';
                else if (job?.state === 'queued') status = 'Queued';
                else if (job?.state === 'done') status = 'Done';
                else if (job?.state) status = humanizeAgentField(job.state);

                const solarEdgeKwh = isBaselineValue && !job
                    ? firstDefined(referenceSolarEdge, ['baseline_predicted_kwh', 'baseline_kwh', 'baseline'])
                    : firstDefined(solarEdge, ['candidate_predicted_kwh', 'scenario_predicted_kwh', 'candidate_kwh', 'candidate']);
                const solectriaKwh = isBaselineValue && !job
                    ? firstDefined(referenceSolectria, ['baseline_predicted_kwh', 'baseline_kwh', 'baseline'])
                    : firstDefined(solectria, ['candidate_predicted_kwh', 'scenario_predicted_kwh', 'candidate_kwh', 'candidate']);
                const solarEdgeDelta = isBaselineValue && !job
                    ? 0
                    : firstDefined(solarEdge, ['delta_pct', 'change_pct', 'percent_change']);
                const solectriaDelta = isBaselineValue && !job
                    ? 0
                    : firstDefined(solectria, ['delta_pct', 'change_pct', 'percent_change']);
                const row = document.createElement('tr');
                [
                    formatAgentValue(value, metadata.unit || undefined),
                    status,
                    formatAgentValue(solarEdgeKwh),
                    comparisonPercent(solarEdgeDelta),
                    formatAgentValue(solectriaKwh),
                    comparisonPercent(solectriaDelta),
                ].forEach((cellValue) => {
                    const cell = document.createElement('td');
                    cell.textContent = cellValue;
                    row.appendChild(cell);
                });
                body.appendChild(row);
            });
            table.appendChild(body);
            labelAgentTable(table);
            const tableWrap = document.createElement('div');
            tableWrap.className = 'parameter-sweep-table-wrap';
            tableWrap.appendChild(table);
            section.appendChild(tableWrap);

            if (group.proposals.length) {
                const actions = document.createElement('div');
                actions.className = 'agent-card-actions';
                actions.appendChild(makeAgentButton('Run sweep', 'primary', () => confirmAgentSweep(group.sweep_id)));
                actions.appendChild(makeAgentButton('Dismiss sweep', '', () => dismissAgentSweep(group.sweep_id)));
                section.appendChild(actions);
            }
            return section;
        }

        function buildComparisonCard(comparison) {
            if (!comparison || typeof comparison !== 'object') return null;
            const section = document.createElement('section');
            section.className = 'agent-card';
            section.setAttribute('aria-label', 'Deterministic scenario comparison');
            const head = document.createElement('div');
            head.className = 'agent-card-head';
            const title = document.createElement('div');
            title.className = 'agent-card-title';
            title.textContent = 'Deterministic comparison';
            const classification = comparison.comparison_type || comparison.comparison_kind || comparison.classification || 'same_input';
            head.append(title, makeStatePill(classification));
            section.appendChild(head);
            if (classification === 'cross_run') {
                const warning = document.createElement('div');
                warning.className = 'agent-card-note cross-run';
                warning.textContent = comparison.caveat || 'Different interval or source data; results are descriptive only and must not be attributed to one parameter. Run the same interval with different parameters for a controlled comparison.';
                section.appendChild(warning);
            }

            const systems = comparison.systems || comparison.per_system || comparison.predicted_energy || {};
            const systemEntries = Array.isArray(systems)
                ? systems.map((item) => [item.system || item.name || 'System', item])
                : Object.entries(systems || {});
            const rows = [];
            systemEntries.forEach(([name, values]) => {
                if (!values || typeof values !== 'object') return;
                rows.push({
                    label: humanizeAgentField(name),
                    baseline: firstDefined(values, ['baseline_predicted_kwh', 'baseline_kwh', 'baseline']),
                    candidate: firstDefined(values, ['candidate_predicted_kwh', 'scenario_predicted_kwh', 'candidate_kwh', 'candidate', 'scenario']),
                    delta: firstDefined(values, ['delta_kwh', 'change_kwh', 'delta']),
                    pct: firstDefined(values, ['delta_pct', 'change_pct', 'percent_change']),
                    validation: values.validation,
                });
            });
            if (rows.length) {
                const table = document.createElement('table');
                table.className = 'comparison-table';
                table.innerHTML = '<thead><tr><th>System</th><th>Baseline kWh</th><th>Scenario kWh</th><th>Delta</th></tr></thead>';
                const body = document.createElement('tbody');
                rows.forEach((item) => {
                    const row = document.createElement('tr');
                    const delta = formatAgentValue(item.delta, 'kWh') + (item.pct === null ? '' : ' (' + comparisonPercent(item.pct) + ')');
                    [item.label, formatAgentValue(item.baseline), formatAgentValue(item.candidate), delta].forEach((value) => {
                        const cell = document.createElement('td');
                        cell.textContent = value;
                        row.appendChild(cell);
                    });
                    body.appendChild(row);
                });
                table.appendChild(body);
                section.appendChild(table);
            }

            const fitEntries = rows.filter((item) => item.validation).map((item) => [item.label, item.validation]);
            const topLevelFit = comparison.validation || comparison.fit || comparison.model_fit;
            if (topLevelFit && typeof topLevelFit === 'object') fitEntries.push(['Combined', topLevelFit]);
            fitEntries.forEach(([systemLabel, fit]) => {
                const note = document.createElement('div');
                note.className = 'agent-card-note';
                const baselineResidual = firstDefined(fit, ['baseline_residual_pct', 'baseline_error_pct', 'baseline_pct']);
                const candidateResidual = firstDefined(fit, ['candidate_residual_pct', 'candidate_error_pct', 'scenario_pct']);
                const improvement = firstDefined(fit, ['absolute_error_improvement_pp', 'fit_improvement_pp', 'improvement_pp']);
                note.textContent = systemLabel + ' model fit · baseline residual ' + comparisonPercent(baselineResidual) +
                    ' · scenario residual ' + comparisonPercent(candidateResidual) +
                    ' · improvement ' + formatAgentValue(improvement, 'pp') + ' (positive is better)';
                section.appendChild(note);
            });

            const gap = comparison.cross_system_gap || comparison.predicted_gap || comparison.gap || comparison.system_gap;
            if (gap && typeof gap === 'object') {
                const note = document.createElement('div');
                note.className = 'agent-card-note';
                note.textContent = 'SolarEdge–Solectria predicted gap · before ' + formatAgentValue(firstDefined(gap, ['baseline_kwh', 'before_kwh', 'baseline']), 'kWh') +
                    ' · after ' + formatAgentValue(firstDefined(gap, ['candidate_kwh', 'after_kwh', 'candidate']), 'kWh') +
                    ' · change ' + formatAgentValue(firstDefined(gap, ['change_kwh', 'delta_kwh', 'change']), 'kWh');
                section.appendChild(note);
            }

            const attribution = comparison.attribution;
            if (attribution && attribution.scope === 'combined_configuration') {
                const note = document.createElement('div');
                note.className = 'agent-card-note cross-run';
                note.textContent = 'Combined configuration result: this run changed multiple fields, so no individual parameter is credited with the total delta.';
                section.appendChild(note);
            }

            if (comparison.invariants && typeof comparison.invariants === 'object') {
                const details = document.createElement('details');
                details.className = 'agent-details';
                const summary = document.createElement('summary');
                summary.textContent = 'Comparison integrity checks';
                const grid = document.createElement('div');
                grid.className = 'agent-details-grid';
                Object.entries(comparison.invariants).forEach(([field, value]) => {
                    const item = document.createElement('div');
                    const label = document.createElement('strong');
                    label.textContent = humanizeAgentField(field);
                    item.append(label, document.createTextNode(value === true ? 'Confirmed' : value === false ? 'Not confirmed' : formatAgentValue(value)));
                    grid.appendChild(item);
                });
                details.append(summary, grid);
                section.appendChild(details);
            }

            if (!rows.length && !fitEntries.length && !gap) {
                const scalars = [];
                Object.entries(comparison).forEach(([field, value]) => {
                    if (['comparison_kind', 'classification', 'warnings'].includes(field)) return;
                    if (value === null || ['string', 'number', 'boolean'].includes(typeof value)) {
                        scalars.push([humanizeAgentField(field), formatAgentValue(value)]);
                    }
                });
                if (scalars.length) {
                    const table = document.createElement('table');
                    table.className = 'comparison-table';
                    table.innerHTML = '<thead><tr><th>Metric</th><th>Value</th></tr></thead>';
                    const body = document.createElement('tbody');
                    scalars.forEach(([label, value]) => {
                        const row = document.createElement('tr');
                        [label, value].forEach((text) => {
                            const cell = document.createElement('td');
                            cell.textContent = text;
                            row.appendChild(cell);
                        });
                        body.appendChild(row);
                    });
                    table.appendChild(body);
                    section.appendChild(table);
                }
            }

            const warnings = Array.isArray(comparison.warnings) ? comparison.warnings : [];
            warnings.filter(Boolean).forEach((text) => {
                const warning = document.createElement('div');
                warning.className = 'agent-card-note cross-run';
                warning.textContent = String(text);
                section.appendChild(warning);
            });
            section.querySelectorAll('table').forEach(labelAgentTable);
            return section;
        }

        function collectArtifactLinks(value, prefix = '') {
            const links = [];
            if (!value) return links;
            if (typeof value === 'string') {
                if (/^(?:https?:\/\/|\/)/i.test(value)) links.push({ label: prefix || 'Report', url: value });
                return links;
            }
            if (Array.isArray(value)) {
                value.forEach((item, index) => links.push(...collectArtifactLinks(item, prefix || ('Report ' + (index + 1)))));
                return links;
            }
            if (typeof value === 'object') {
                if (typeof value.url === 'string') {
                    links.push({
                        label: prefix || 'Report',
                        url: value.url,
                        filename: typeof value.filename === 'string' ? value.filename : null,
                    });
                    return links;
                }
                Object.entries(value).forEach(([name, item]) => links.push(...collectArtifactLinks(item, humanizeAgentField(name))));
            }
            return links;
        }

        function buildProvenanceDetails(provenance) {
            if (!provenance || typeof provenance !== 'object') return null;
            const details = document.createElement('details');
            details.className = 'agent-details';
            const summary = document.createElement('summary');
            summary.textContent = 'Evidence and provenance';
            const grid = document.createElement('div');
            grid.className = 'agent-details-grid';
            const baseline = provenance.baseline || {};
            const candidate = provenance.candidate || {};
            const fields = [
                ['Comparison', provenance.comparison_type],
                ['Generated', provenance.generated_at_utc],
                ['Baseline source SHA-256', baseline.source_sha256 ? shortAgentId(baseline.source_sha256) : null],
                ['Scenario source SHA-256', candidate.source_sha256 ? shortAgentId(candidate.source_sha256) : null],
                ['Baseline model', baseline.model_version],
                ['Scenario model', candidate.model_version],
                ['Baseline DHI', baseline.dhi_source],
                ['Scenario DHI', candidate.dhi_source],
            ];
            fields.forEach(([labelText, value]) => {
                if (value === null || value === undefined || value === '') return;
                const item = document.createElement('div');
                const label = document.createElement('strong');
                label.textContent = labelText;
                item.append(label, document.createTextNode(formatAgentValue(value)));
                grid.appendChild(item);
            });
            details.append(summary, grid);
            const warnings = Array.isArray(provenance.warnings) ? provenance.warnings.filter(Boolean) : [];
            warnings.forEach((warningText) => {
                const warning = document.createElement('div');
                warning.className = 'agent-card-note cross-run';
                warning.textContent = String(warningText);
                details.appendChild(warning);
            });
            return details;
        }

        function safeArtifactHref(url) {
            try {
                const parsed = new URL(String(url), window.location.origin);
                if (!['http:', 'https:'].includes(parsed.protocol)) return null;
                return parsed.href;
            } catch (_) {
                return null;
            }
        }

        function buildJobCard(job) {
            const card = document.createElement('article');
            card.className = 'agent-card job-card';
            card.dataset.jobId = job.job_id;
            const head = document.createElement('div');
            head.className = 'agent-card-head';
            const heading = document.createElement('div');
            const title = document.createElement('div');
            title.className = 'agent-card-title';
            title.textContent = ['baseline', 'manual'].includes(job.kind) ? 'Baseline model run' : 'Scenario model run';
            const meta = document.createElement('div');
            meta.className = 'agent-card-meta';
            const runSummary = summarizeAgentRequest({ type: 'job', item: job });
            meta.textContent = (job.mode === 'annual' ? 'Annual' : 'Calibration') + ' · ' + runSummary.window +
                ' · Job ' + shortAgentId(job.job_id) + (job.baseline_job_id ? ' · Baseline ' + shortAgentId(job.baseline_job_id) : '');
            heading.append(title, meta);
            head.append(heading, makeStatePill(job.cancel_requested ? 'cancel requested' : job.state));
            card.appendChild(head);

            const configuration = buildAgentRunConfiguration(job.request, job.mode);
            if (configuration) card.appendChild(configuration);

            const progress = Math.min(100, Math.max(0, Number(job.progress) || 0));
            const progressMeta = document.createElement('div');
            progressMeta.className = 'agent-progress-meta';
            const stage = document.createElement('span');
            stage.textContent = job.mode === 'annual'
                ? annualUserFacingText(job.stage || humanizeAgentField(job.state || 'queued'))
                : (job.stage || humanizeAgentField(job.state || 'queued'));
            const elapsed = document.createElement('span');
            elapsed.className = 'agent-elapsed';
            elapsed.dataset.startedAt = String(agentJobStartedAt.get(job.job_id) || Date.now());
            const completedAt = job.completed_at ? Date.parse(job.completed_at) : NaN;
            if (Number.isFinite(completedAt)) elapsed.dataset.endedAt = String(completedAt);
            elapsed.textContent = Math.round(progress) + '% · 0s elapsed';
            progressMeta.append(stage, elapsed);
            const track = document.createElement('div');
            track.className = 'agent-progress-track';
            track.setAttribute('role', 'progressbar');
            track.setAttribute('aria-label', title.textContent + ' ' + runSummary.window + ' progress');
            track.setAttribute('aria-valuemin', '0');
            track.setAttribute('aria-valuemax', '100');
            track.setAttribute('aria-valuenow', String(progress));
            const fill = document.createElement('div');
            fill.className = 'agent-progress-fill';
            fill.style.width = progress + '%';
            track.appendChild(fill);
            card.append(progressMeta, track);

            if (job.error) {
                const error = document.createElement('div');
                error.className = 'agent-card-note cross-run';
                error.textContent = String(job.error);
                card.appendChild(error);
            }
            if (job.client_action_error) {
                const actionError = document.createElement('div');
                actionError.className = 'agent-card-note cross-run';
                actionError.setAttribute('role', 'alert');
                actionError.textContent = String(job.client_action_error);
                card.appendChild(actionError);
            }
            if (job.state === 'done' && job.comparison) {
                const comparisonCard = buildComparisonCard(job.comparison);
                if (comparisonCard) card.appendChild(comparisonCard);
            }
            const provenanceDetails = buildProvenanceDetails(job.provenance);
            if (provenanceDetails) card.appendChild(provenanceDetails);

            const links = collectArtifactLinks(job.artifacts);
            if (links.length) {
                const downloads = document.createElement('details');
                downloads.className = 'agent-downloads';
                const downloadsSummary = document.createElement('summary');
                downloadsSummary.textContent = 'Downloads (' + links.length + ')';
                const linkWrap = document.createElement('div');
                linkWrap.className = 'agent-artifact-links';
                links.forEach((item) => {
                    const href = safeArtifactHref(item.url);
                    if (!href) return;
                    const link = document.createElement('a');
                    link.className = 'agent-artifact-link';
                    link.href = href;
                    link.target = '_blank';
                    link.rel = 'noopener noreferrer';
                    if (item.filename) link.download = item.filename;
                    link.textContent = item.label;
                    linkWrap.appendChild(link);
                });
                if (linkWrap.childElementCount) {
                    downloads.append(downloadsSummary, linkWrap);
                    card.appendChild(downloads);
                }
            }

            const actions = document.createElement('div');
            actions.className = 'agent-card-actions';
            if (isAgentJobActive(job)) {
                actions.appendChild(makeAgentButton('Cancel run', 'danger', () => cancelAgentJob(job.job_id)));
            }
            if (['error', 'cancelled', 'interrupted'].includes(job.state)) {
                actions.appendChild(makeAgentButton('Retry', '', () => retryAgentJob(job)));
            }
            if (job.state === 'done') {
                const viewResultsButton = makeAgentButton('View results', '', () => viewAgentJobResults(job.job_id, job.mode));
                if (dashboardModeHasBlockingRun(job.mode, job.job_id)) {
                    viewResultsButton.disabled = true;
                    viewResultsButton.title = 'Finish or cancel the active run in this mode first.';
                }
                actions.appendChild(viewResultsButton);
            }
            const isPromoted = agentServerState.promoted_baselines?.[job.mode] === job.job_id;
            const canPromote = job.mode === 'annual' || job.request?.calibrate_model !== false;
            if (job.state === 'done' && job.comparison) {
                const explainButton = makeAgentButton('Explain results', '', () => requestAgentCompletionExplanation(job));
                if (agentExplainedJobs.has(job.job_id)) {
                    explainButton.disabled = true;
                    explainButton.textContent = 'Explanation added';
                }
                actions.appendChild(explainButton);
            }
            if (job.state === 'done' && !isPromoted && canPromote) {
                actions.appendChild(makeAgentButton('Promote to baseline', 'primary', () => promoteAgentJob(job.job_id)));
            }
            if (isPromoted) {
                const promoted = document.createElement('span');
                promoted.className = 'agent-state-pill done';
                promoted.textContent = 'Current baseline';
                actions.appendChild(promoted);
            }
            const isScenarioRun = job.kind === 'candidate' && job.baseline_job_id;
            const isBaselineRun = ['baseline', 'manual'].includes(job.kind);
            if (((isScenarioRun && !isPromoted) || isBaselineRun) && !isAgentJobActive(job)) {
                const isSavedResult = window.savedResultsDrawerReady === true && !!savedResultByJobId(job.job_id);
                if (isSavedResult) {
                    const savedNotice = document.createElement('span');
                    savedNotice.className = 'agent-state-pill done';
                    savedNotice.textContent = 'Saved result';
                    savedNotice.title = 'Remove this item from Saved results before deleting the run.';
                    actions.appendChild(savedNotice);
                } else {
                    actions.appendChild(makeAgentButton('Delete run', 'danger', () => deleteAgentJob(job.job_id)));
                }
            }
            if (actions.childElementCount) card.appendChild(actions);
            return card;
        }

