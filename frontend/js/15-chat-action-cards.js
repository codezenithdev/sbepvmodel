        function boundedChatCardString(value, maximum = 180) {
            if (value === null || value === undefined) return null;
            const text = String(value).trim();
            return text ? text.slice(0, maximum) : null;
        }

        function finiteChatCardNumber(value) {
            if (value === null || value === undefined || value === '') return null;
            const number = Number(value);
            return Number.isFinite(number) ? number : null;
        }

        function chatCardScalar(value) {
            if (typeof value === 'boolean') return value;
            const number = finiteChatCardNumber(value);
            if (number !== null && value !== '') return number;
            return boundedChatCardString(value, 120);
        }

        function normalizeChatActionCard(card) {
            if (!card || typeof card !== 'object') return null;
            const allowedKinds = [
                'proposal_review',
                'sweep_review',
                'job_started',
                'sweep_started',
                'data_review_required',
                'run_complete',
                'sweep_complete',
            ];
            const kind = boundedChatCardString(card.kind, 40);
            if (!allowedKinds.includes(kind)) return null;
            const normalized = { kind };
            [
                'title',
                'status',
                'mode',
                'sweep_id',
                'job_id',
                'proposal_id',
                'baseline_job_id',
                'label',
                'unit',
                'parameter',
                'window',
                'run_kind',
                'error',
                'expires_at',
            ].forEach((field) => {
                const value = boundedChatCardString(card[field], field === 'error' ? 300 : 180);
                if (value !== null) normalized[field] = value;
            });
            ['count', 'candidate_count', 'error_count', 'elapsed_seconds'].forEach((field) => {
                const value = finiteChatCardNumber(card[field]);
                if (value !== null) normalized[field] = value;
            });
            ['job_ids', 'proposal_ids'].forEach((field) => {
                if (!Array.isArray(card[field])) return;
                normalized[field] = card[field]
                    .map((value) => boundedChatCardString(value, 160))
                    .filter(Boolean)
                    .slice(0, 12);
            });
            if (Array.isArray(card.values)) {
                normalized.values = card.values
                    .map(finiteChatCardNumber)
                    .filter((value) => value !== null)
                    .slice(0, 12);
            }
            if (Array.isArray(card.changes)) {
                normalized.changes = card.changes
                    .filter((item) => item && typeof item === 'object')
                    .slice(0, 12)
                    .map((item) => ({
                        field: boundedChatCardString(item.field, 100),
                        label: boundedChatCardString(item.label, 120),
                        from: chatCardScalar(item.from),
                        to: chatCardScalar(item.to),
                        unit: boundedChatCardString(item.unit, 30),
                    }));
            }
            if (Array.isArray(card.systems)) {
                normalized.systems = card.systems
                    .filter((item) => item && typeof item === 'object')
                    .slice(0, 4)
                    .map((item) => ({
                        name: boundedChatCardString(item.name, 80) || 'System',
                        baseline_kwh: finiteChatCardNumber(item.baseline_kwh),
                        predicted_kwh: finiteChatCardNumber(item.predicted_kwh),
                        delta_pct: finiteChatCardNumber(item.delta_pct),
                    }));
            }
            if (Array.isArray(card.rows)) {
                normalized.rows = card.rows
                    .filter((item) => item && typeof item === 'object')
                    .slice(0, 12)
                    .map((item) => ({
                        value: finiteChatCardNumber(item.value),
                        state: boundedChatCardString(item.state, 40) || 'unknown',
                        job_id: boundedChatCardString(item.job_id, 160),
                        solaredge_kwh: finiteChatCardNumber(item.solaredge_kwh),
                        solaredge_delta_pct: finiteChatCardNumber(item.solaredge_delta_pct),
                        solectria_kwh: finiteChatCardNumber(item.solectria_kwh),
                        solectria_delta_pct: finiteChatCardNumber(item.solectria_delta_pct),
                    }));
            }
            return normalized;
        }

        function chatActionCardMatches(card, match) {
            if (!card || !match) return false;
            const cardJobIds = [card.job_id, ...(card.job_ids || [])].filter(Boolean).map(String);
            const matchJobIds = [match.job_id, ...(match.job_ids || [])].filter(Boolean).map(String);
            const cardProposalIds = [card.proposal_id, ...(card.proposal_ids || [])].filter(Boolean).map(String);
            const matchProposalIds = [match.proposal_id, ...(match.proposal_ids || [])].filter(Boolean).map(String);
            return (
                (!!match.sweep_id && card.sweep_id === match.sweep_id) ||
                matchJobIds.some((jobId) => cardJobIds.includes(jobId)) ||
                matchProposalIds.some((proposalId) => cardProposalIds.includes(proposalId))
            );
        }

        function chatConversationForActionCard(match) {
            syncActiveChatConversation();
            return chatConversations.find((conversation) => (
                conversation.messages.some((message) => (
                    chatActionCardMatches(normalizeChatActionCard(message.action_card), match)
                ))
            )) || null;
        }

        function savedNonterminalActionJobIds() {
            syncActiveChatConversation();
            const jobIds = new Set();
            chatConversations.forEach((conversation) => {
                conversation.messages.forEach((message) => {
                    const card = normalizeChatActionCard(message.action_card);
                    if (!card || !['job_started', 'sweep_started'].includes(card.kind)) return;
                    if (TERMINAL_CHAT_ACTION_STATUSES.has(String(card.status || '').toLowerCase())) return;
                    [card.job_id, ...(card.job_ids || [])].filter(Boolean).forEach((jobId) => {
                        jobIds.add(String(jobId));
                    });
                });
            });
            return Array.from(jobIds);
        }

        function chatActionSweepMetadata(action) {
            if (action?.sweep && typeof action.sweep === 'object') return action.sweep;
            const member = action?.jobs?.[0] || action?.proposals?.[0] || action?.job || action?.proposal;
            return agentParameterSweepMetadata(member);
        }

        function buildChatActionCard(action) {
            if (!action || typeof action !== 'object') return null;
            if (action.type === 'data_review_required') {
                const request = action.effective_request || {};
                return normalizeChatActionCard({
                    kind: 'data_review_required',
                    title: 'Calibration data review required',
                    status: 'action required',
                    mode: 'validation',
                    window: compactAgentRunWindow(request, 'validation'),
                });
            }
            if (action.type === 'proposal_batch') {
                const sweep = chatActionSweepMetadata(action) || {};
                return normalizeChatActionCard({
                    kind: 'sweep_review',
                    title: String(sweep.label || 'Parameter') + ' sweep',
                    status: 'needs review',
                    mode: sweep.mode,
                    sweep_id: sweep.sweep_id,
                    proposal_ids: (action.proposals || []).map((item) => item?.proposal_id),
                    baseline_job_id: sweep.baseline_job_id,
                    label: sweep.label,
                    unit: sweep.unit,
                    parameter: sweep.parameter,
                    values: sweep.values,
                    count: sweep.count,
                    candidate_count: sweep.candidate_count,
                    expires_at: action.proposals?.[0]?.expires_at,
                });
            }
            if (action.type === 'job_batch_started') {
                const sweep = chatActionSweepMetadata(action) || {};
                return normalizeChatActionCard({
                    kind: 'sweep_started',
                    title: String(sweep.label || 'Parameter') + ' sweep',
                    status: 'queued',
                    mode: sweep.mode,
                    sweep_id: sweep.sweep_id,
                    job_ids: (action.jobs || []).map((item) => item?.job_id),
                    baseline_job_id: sweep.baseline_job_id,
                    label: sweep.label,
                    unit: sweep.unit,
                    parameter: sweep.parameter,
                    values: sweep.values,
                    count: sweep.count,
                    candidate_count: sweep.candidate_count,
                });
            }
            if (action.type === 'proposal' && action.proposal) {
                const proposal = action.proposal;
                const request = proposal.effective_request || {};
                const baseline = proposal.kind === 'baseline';
                return normalizeChatActionCard({
                    kind: 'proposal_review',
                    title: baseline ? 'Baseline model run' : 'Scenario model run',
                    status: 'needs review',
                    mode: proposal.mode,
                    proposal_id: proposal.proposal_id,
                    baseline_job_id: proposal.baseline_job_id,
                    run_kind: proposal.kind,
                    window: compactAgentRunWindow(request, proposal.mode),
                    changes: proposal.changes,
                    expires_at: proposal.expires_at,
                });
            }
            if (action.type === 'job_started' && action.job) {
                const job = action.job;
                const baseline = ['baseline', 'manual'].includes(job.kind);
                return normalizeChatActionCard({
                    kind: 'job_started',
                    title: baseline ? 'Baseline model run' : 'Scenario model run',
                    status: job.state || 'queued',
                    mode: job.mode,
                    job_id: job.job_id,
                    baseline_job_id: job.baseline_job_id,
                    run_kind: job.kind,
                    window: compactAgentRunWindow(job.request || {}, job.mode),
                });
            }
            return null;
        }

        function agentActionSummary(action) {
            const sweep = chatActionSweepMetadata(action) || {};
            const label = String(sweep.label || 'parameter');
            if (action?.type === 'data_review_required') {
                return 'This scenario needs a calibration data review before a model run can start.';
            }
            if (action?.type === 'proposal_batch') {
                return `The ${label} sweep is ready for review before its runs are queued.`;
            }
            if (action?.type === 'job_batch_started') {
                return `The ${label} sweep is queued, and its live comparison is ready to track.`;
            }
            if (action?.type === 'proposal') {
                return action.proposal?.kind === 'baseline'
                    ? 'The baseline model run is ready for review.'
                    : 'The scenario model run is ready for review.';
            }
            if (action?.type === 'job_started') {
                return ['baseline', 'manual'].includes(action.job?.kind)
                    ? 'The baseline model run is queued.'
                    : 'The scenario model run is queued against the selected baseline.';
            }
            return 'The requested model action is ready.';
        }

        function chatCardModeLabel(mode) {
            return mode === 'annual' ? 'Annual' : 'Calibration';
        }

        function chatCardValueRange(card) {
            const values = Array.isArray(card.values) ? card.values : [];
            if (!values.length) return null;
            if (values.length === 1) return formatAgentValue(values[0], card.unit);
            return formatAgentValue(values[0], card.unit) + ' to ' +
                formatAgentValue(values[values.length - 1], card.unit);
        }

        function appendChatActionChip(container, text) {
            if (!text) return;
            const chip = document.createElement('span');
            chip.className = 'chat-action-chip';
            chip.textContent = text;
            container.appendChild(chip);
        }

        function appendChatActionMetric(container, label, value, note) {
            const metric = document.createElement('div');
            metric.className = 'chat-action-metric';
            const labelNode = document.createElement('span');
            labelNode.textContent = label;
            const valueNode = document.createElement('strong');
            valueNode.textContent = value;
            metric.append(labelNode, valueNode);
            if (note) {
                const noteNode = document.createElement('small');
                noteNode.textContent = note;
                metric.appendChild(noteNode);
            }
            container.appendChild(metric);
        }

        function formatChatEnergy(value) {
            const number = finiteChatCardNumber(value);
            return number === null
                ? 'Unavailable'
                : number.toLocaleString(undefined, { maximumFractionDigits: 1 }) + ' kWh';
        }

        function makeChatActionDetails(summaryText) {
            const details = document.createElement('details');
            details.className = 'chat-action-details';
            const summary = document.createElement('summary');
            summary.textContent = summaryText;
            details.appendChild(summary);
            return details;
        }

        function appendChatDetailRow(container, label, value) {
            if (value === null || value === undefined || value === '') return;
            const row = document.createElement('div');
            row.className = 'chat-action-detail-row';
            const key = document.createElement('strong');
            key.textContent = label;
            const content = document.createElement('span');
            content.textContent = String(value);
            row.append(key, content);
            container.appendChild(row);
        }

        function createChatSvgNode(name, attributes = {}) {
            const node = document.createElementNS('http://www.w3.org/2000/svg', name);
            Object.entries(attributes).forEach(([key, value]) => node.setAttribute(key, String(value)));
            return node;
        }

        function buildChatSweepChart(card) {
            const rows = (card.rows || [])
                .filter((row) => row.value !== null && (
                    row.solaredge_kwh !== null || row.solectria_kwh !== null
                ))
                .sort((left, right) => left.value - right.value);
            const yValues = rows.flatMap((row) => [row.solaredge_kwh, row.solectria_kwh])
                .filter((value) => value !== null && Number.isFinite(value));
            if (rows.length < 2 || yValues.length < 2) return null;

            const width = 320;
            const height = 130;
            const margin = { top: 10, right: 9, bottom: 28, left: 46 };
            const plotWidth = width - margin.left - margin.right;
            const plotHeight = height - margin.top - margin.bottom;
            const xMin = Math.min(...rows.map((row) => row.value));
            const xMax = Math.max(...rows.map((row) => row.value));
            const rawYMin = Math.min(...yValues);
            const rawYMax = Math.max(...yValues);
            const yPadding = rawYMax === rawYMin ? Math.max(Math.abs(rawYMax) * 0.02, 1) : (rawYMax - rawYMin) * 0.08;
            const yMin = rawYMin - yPadding;
            const yMax = rawYMax + yPadding;
            const xPosition = (value, index) => xMax === xMin
                ? margin.left + (plotWidth * index / Math.max(rows.length - 1, 1))
                : margin.left + ((value - xMin) / (xMax - xMin)) * plotWidth;
            const yPosition = (value) => margin.top + (1 - ((value - yMin) / (yMax - yMin))) * plotHeight;

            const figure = document.createElement('figure');
            figure.className = 'chat-sweep-chart';
            const caption = document.createElement('figcaption');
            caption.textContent = 'Predicted energy by ' + String(card.label || 'parameter');
            const svg = createChatSvgNode('svg', {
                viewBox: `0 0 ${width} ${height}`,
                role: 'img',
                'aria-label': caption.textContent + ' for SolarEdge and Solectria',
            });
            const title = createChatSvgNode('title');
            title.textContent = caption.textContent;
            svg.appendChild(title);

            [0, 0.5, 1].forEach((fraction) => {
                const y = margin.top + fraction * plotHeight;
                svg.appendChild(createChatSvgNode('line', {
                    x1: margin.left,
                    x2: width - margin.right,
                    y1: y,
                    y2: y,
                    stroke: '#dfe8e5',
                    'stroke-width': 1,
                }));
                const value = yMax - fraction * (yMax - yMin);
                const label = createChatSvgNode('text', {
                    x: margin.left - 5,
                    y: y + 3,
                    fill: '#64736d',
                    'font-size': 8,
                    'text-anchor': 'end',
                });
                label.textContent = Math.round(value).toLocaleString();
                svg.appendChild(label);
            });

            const xLabelIndexes = [...new Set([0, Math.floor((rows.length - 1) / 2), rows.length - 1])];
            xLabelIndexes.forEach((index) => {
                const row = rows[index];
                const label = createChatSvgNode('text', {
                    x: xPosition(row.value, index),
                    y: height - 9,
                    fill: '#64736d',
                    'font-size': 8,
                    'text-anchor': 'middle',
                });
                label.textContent = formatAgentValue(row.value, card.unit);
                svg.appendChild(label);
            });

            [
                { field: 'solaredge_kwh', color: '#0f766e' },
                { field: 'solectria_kwh', color: '#2563eb' },
            ].forEach((series) => {
                const points = rows
                    .map((row, index) => row[series.field] === null ? null : {
                        x: xPosition(row.value, index),
                        y: yPosition(row[series.field]),
                    })
                    .filter(Boolean);
                if (points.length < 2) return;
                svg.appendChild(createChatSvgNode('polyline', {
                    points: points.map((point) => `${point.x},${point.y}`).join(' '),
                    fill: 'none',
                    stroke: series.color,
                    'stroke-width': 2.4,
                    'stroke-linecap': 'round',
                    'stroke-linejoin': 'round',
                }));
                points.forEach((point) => {
                    svg.appendChild(createChatSvgNode('circle', {
                        cx: point.x,
                        cy: point.y,
                        r: 2.8,
                        fill: '#ffffff',
                        stroke: series.color,
                        'stroke-width': 1.8,
                    }));
                });
            });

            const legend = document.createElement('div');
            legend.className = 'chat-chart-legend';
            const solarEdge = document.createElement('span');
            solarEdge.textContent = 'SolarEdge';
            const solectria = document.createElement('span');
            solectria.textContent = 'Solectria';
            legend.append(solarEdge, solectria);
            figure.append(caption, svg, legend);
            return figure;
        }

        function renderChatCompletionDetails(card) {
            if (card.kind === 'sweep_complete' && Array.isArray(card.rows)) {
                const details = makeChatActionDetails('Engineering details');
                const wrap = document.createElement('div');
                wrap.className = 'chat-action-table-wrap';
                const table = document.createElement('table');
                table.className = 'chat-action-table';
                table.innerHTML = '<thead><tr><th>Value</th><th>Status</th><th>SolarEdge</th><th>SE delta</th><th>Solectria</th><th>Solectria delta</th></tr></thead>';
                const body = document.createElement('tbody');
                card.rows.forEach((item) => {
                    const row = document.createElement('tr');
                    [
                        formatAgentValue(item.value, card.unit),
                        humanizeAgentField(item.state),
                        formatChatEnergy(item.solaredge_kwh),
                        comparisonPercent(item.solaredge_delta_pct),
                        formatChatEnergy(item.solectria_kwh),
                        comparisonPercent(item.solectria_delta_pct),
                    ].forEach((value) => {
                        const cell = document.createElement('td');
                        cell.textContent = value;
                        row.appendChild(cell);
                    });
                    body.appendChild(row);
                });
                table.appendChild(body);
                wrap.appendChild(table);
                details.appendChild(wrap);
                return details;
            }
            if (card.kind === 'run_complete' && Array.isArray(card.systems) && card.systems.length) {
                const details = makeChatActionDetails('Engineering details');
                const list = document.createElement('div');
                list.className = 'chat-action-detail-list';
                card.systems.forEach((system) => {
                    appendChatDetailRow(
                        list,
                        system.name,
                        'Baseline ' + formatChatEnergy(system.baseline_kwh) +
                        ' | Run ' + formatChatEnergy(system.predicted_kwh) +
                        ' | Delta ' + comparisonPercent(system.delta_pct)
                    );
                });
                details.appendChild(list);
                return details;
            }
            return null;
        }

        async function openAgentActivityFromChat(card) {
            const jobIds = Array.from(new Set(
                [card.job_id, ...(card.job_ids || [])].filter(Boolean).map(String)
            ));
            const missingJobIds = jobIds.filter((jobId) => !agentJobSnapshots.has(jobId));
            if (missingJobIds.length) {
                const unavailableJobIds = new Set();
                await Promise.all(missingJobIds.map(async (jobId) => {
                    try {
                        const response = await fetch('/api/status/' + encodeURIComponent(jobId), { cache: 'no-store' });
                        if (response.ok) putAgentJob(await response.json());
                        else if (response.status === 404) unavailableJobIds.add(jobId);
                    } catch (_) {
                        // The card remains readable even if its durable run cannot be loaded right now.
                    }
                }));
                if (jobIds.length && !jobIds.some((jobId) => agentJobSnapshots.has(jobId))) {
                    if (unavailableJobIds.size === jobIds.length) {
                        updateStoredChatActionCardStatus(
                            card.sweep_id ? { sweep_id: card.sweep_id } : { job_id: card.job_id },
                            'unavailable'
                        );
                        appendSystemNotice('This saved run is no longer available in the scenario workspace.', 'error');
                    } else {
                        appendSystemNotice('The saved run could not be loaded yet. Please try again.', 'error');
                    }
                    return;
                }
            }
            if (['proposal_review', 'sweep_review'].includes(card.kind) && card.status === 'needs review') {
                agentActivityFilter = 'review';
            } else if (['run_complete', 'sweep_complete'].includes(card.kind)) {
                agentActivityFilter = 'complete';
            } else {
                agentActivityFilter = 'all';
            }
            if (card.proposal_id) agentActivitySelection = 'proposal:' + card.proposal_id;
            else if (card.job_id) agentActivitySelection = 'job:' + card.job_id;
            else agentActivitySelection = null;
            renderAgentActivity();
            setAgentActivityOpen(true);
        }

        function openCalibrationFromChat() {
            switchMode('validation');
            setChatOpen(false);
            window.setTimeout(() => {
                fromDate.scrollIntoView({ behavior: 'smooth', block: 'center' });
                fromDate.focus({ preventScroll: true });
            }, 0);
        }

        async function explainChatCardJob(jobId) {
            let job = agentJobSnapshots.get(jobId);
            if (!job) {
                try {
                    const response = await fetch('/api/status/' + encodeURIComponent(jobId), { cache: 'no-store' });
                    job = await readAgentResponse(response, 'Could not load this completed run.');
                    putAgentJob(job);
                    renderAgentActivity();
                } catch (error) {
                    appendSystemNotice(error.message || 'Could not load this completed run.', 'error');
                    return;
                }
            }
            requestAgentCompletionExplanation(job);
        }

        function updateStoredChatActionCardStatus(match, status, options = {}) {
            syncActiveChatConversation();
            const persist = options.persist !== false;
            let changed = false;
            let activeChanged = false;
            chatConversations.forEach((conversation) => {
                conversation.messages.forEach((message) => {
                    const card = normalizeChatActionCard(message.action_card);
                    if (!chatActionCardMatches(card, match) || card.status === status) return;
                    if (['deleted', 'unavailable'].includes(card.status) && !['deleted', 'unavailable'].includes(status)) return;
                    message.action_card = { ...card, status };
                    changed = true;
                    if (conversation.id === activeChatConversationId) activeChanged = true;
                });
            });
            if (!changed) return false;
            if (activeChanged) renderChatMessages();
            if (chatHistoryOpen) renderChatHistory();
            if (persist) saveDashboardState();
            return true;
        }

        function appendChatCardActions(section, card) {
            const actions = document.createElement('div');
            actions.className = 'chat-action-actions';
            if (card.status === 'unavailable') return;
            if (card.kind === 'proposal_review' && card.proposal_id && card.status === 'needs review') {
                actions.append(
                    makeAgentButton(card.run_kind === 'baseline' ? 'Approve baseline' : 'Approve & run', 'primary', () => confirmAgentProposal(card.proposal_id)),
                    makeAgentButton('Open review', '', () => openAgentActivityFromChat(card)),
                    makeAgentButton('Dismiss', 'danger', () => dismissAgentProposal(card.proposal_id))
                );
            } else if (card.kind === 'sweep_review' && card.sweep_id && card.status === 'needs review') {
                actions.append(
                    makeAgentButton('Run sweep', 'primary', () => confirmAgentSweep(card.sweep_id, card.proposal_ids)),
                    makeAgentButton('Open review', '', () => openAgentActivityFromChat(card)),
                    makeAgentButton('Dismiss', 'danger', () => dismissAgentSweep(card.sweep_id, card.proposal_ids))
                );
            } else if (
                ['proposal_review', 'sweep_review'].includes(card.kind) &&
                !['dismissed', 'expired', 'unavailable'].includes(card.status)
            ) {
                actions.appendChild(makeAgentButton('Open runs', 'primary', () => openAgentActivityFromChat(card)));
            } else if (card.kind === 'data_review_required') {
                actions.appendChild(makeAgentButton('Open calibration form', 'primary', openCalibrationFromChat));
            } else if (card.kind === 'run_complete') {
                if (card.status !== 'deleted') {
                    actions.appendChild(makeAgentButton('Open run', 'primary', () => openAgentActivityFromChat(card)));
                }
                if (card.status === 'done' && card.job_id && card.systems?.length) {
                    const explainButton = makeAgentButton('Explain results', '', () => explainChatCardJob(card.job_id));
                    if (agentExplainedJobs.has(card.job_id)) {
                        explainButton.disabled = true;
                        explainButton.textContent = 'Explanation added';
                    }
                    actions.appendChild(explainButton);
                }
            } else if (card.kind === 'sweep_complete') {
                actions.appendChild(makeAgentButton('Open full comparison', 'primary', () => openAgentActivityFromChat(card)));
            } else if ((card.kind === 'job_started' || card.kind === 'sweep_started') && card.status !== 'deleted') {
                actions.appendChild(makeAgentButton(
                    card.kind === 'sweep_started' ? 'Open live comparison' : 'Open run',
                    'primary',
                    () => openAgentActivityFromChat(card)
                ));
                if (card.kind === 'job_started' && card.job_id && ['queued', 'running'].includes(card.status)) {
                    actions.appendChild(makeAgentButton('Cancel run', 'danger', () => cancelAgentJob(card.job_id)));
                }
            }
            if (actions.childElementCount) section.appendChild(actions);
        }

        function renderChatActionCard(rawCard) {
            let card = normalizeChatActionCard(rawCard);
            if (!card) return null;
            const expiresAt = card.expires_at ? Date.parse(card.expires_at) : NaN;
            if (
                card.status === 'needs review' &&
                Number.isFinite(expiresAt) &&
                expiresAt <= Date.now()
            ) {
                card = { ...card, status: 'expired' };
            }
            const section = document.createElement('section');
            section.className = 'chat-action-card';
            section.dataset.chatCardKind = card.kind;
            if (card.job_id) section.dataset.jobId = card.job_id;
            if (card.sweep_id) section.dataset.sweepId = card.sweep_id;
            section.setAttribute('aria-label', card.title || 'Solar Agent action');

            const head = document.createElement('div');
            head.className = 'chat-action-card-head';
            const heading = document.createElement('div');
            const kicker = document.createElement('div');
            kicker.className = 'chat-action-card-kicker';
            kicker.textContent = ['run_complete', 'sweep_complete'].includes(card.kind)
                ? 'Model results'
                : card.kind === 'data_review_required'
                    ? 'Next step'
                    : 'Model action';
            const title = document.createElement('div');
            title.className = 'chat-action-card-title';
            title.textContent = card.title || 'Solar Agent action';
            heading.append(kicker, title);
            head.append(heading, makeStatePill(card.status || 'ready'));
            section.appendChild(head);

            const metaParts = [];
            if (card.mode) metaParts.push(chatCardModeLabel(card.mode));
            if (card.window && card.window !== 'Window unavailable') metaParts.push(card.window);
            if (card.baseline_job_id) metaParts.push('Baseline ' + shortAgentId(card.baseline_job_id));
            if (card.job_id) metaParts.push('Run ' + shortAgentId(card.job_id));
            if (metaParts.length) {
                const meta = document.createElement('div');
                meta.className = 'chat-action-card-meta';
                meta.textContent = metaParts.join(' | ');
                section.appendChild(meta);
            }

            const chips = document.createElement('div');
            chips.className = 'chat-action-chips';
            const range = chatCardValueRange(card);
            if (range) appendChatActionChip(chips, range);
            if (card.count) appendChatActionChip(chips, card.count + ' values');
            if (card.candidate_count !== undefined) appendChatActionChip(chips, card.candidate_count + ' scenario runs');
            if (card.changes?.length) appendChatActionChip(chips, card.changes.length + ' changed field' + (card.changes.length === 1 ? '' : 's'));
            if (card.error_count) appendChatActionChip(chips, card.error_count + ' issue' + (card.error_count === 1 ? '' : 's'));
            if (chips.childElementCount) section.appendChild(chips);

            if (card.kind === 'run_complete' && card.systems?.length) {
                const results = document.createElement('div');
                results.className = 'chat-action-results';
                card.systems.forEach((system) => {
                    appendChatActionMetric(
                        results,
                        system.name,
                        formatChatEnergy(system.predicted_kwh),
                        comparisonPercent(system.delta_pct) + ' vs baseline'
                    );
                });
                section.appendChild(results);
            }

            if (card.kind === 'sweep_complete' && card.rows?.length) {
                const results = document.createElement('div');
                results.className = 'chat-action-results';
                [
                    { name: 'SolarEdge highest', field: 'solaredge_kwh', delta: 'solaredge_delta_pct' },
                    { name: 'Solectria highest', field: 'solectria_kwh', delta: 'solectria_delta_pct' },
                ].forEach((definition) => {
                    const candidates = card.rows.filter((row) => row[definition.field] !== null);
                    if (!candidates.length) return;
                    const highest = candidates.reduce((best, row) => (
                        row[definition.field] > best[definition.field] ? row : best
                    ));
                    appendChatActionMetric(
                        results,
                        definition.name,
                        formatChatEnergy(highest[definition.field]),
                        'at ' + formatAgentValue(highest.value, card.unit) +
                        ' | ' + comparisonPercent(highest[definition.delta])
                    );
                });
                if (results.childElementCount) section.appendChild(results);
                const chart = buildChatSweepChart(card);
                if (chart) section.appendChild(chart);
            }

            if (card.error) {
                const error = document.createElement('div');
                error.className = 'agent-card-note cross-run';
                error.textContent = card.error;
                section.appendChild(error);
            }

            if (card.changes?.length) {
                const details = makeChatActionDetails('Review changed fields');
                const list = document.createElement('div');
                list.className = 'chat-action-detail-list';
                card.changes.forEach((change) => {
                    appendChatDetailRow(
                        list,
                        change.label || humanizeAgentField(change.field),
                        formatAgentValue(change.from, change.unit) + ' to ' +
                        formatAgentValue(change.to, change.unit)
                    );
                });
                details.appendChild(list);
                section.appendChild(details);
            }
            const completionDetails = renderChatCompletionDetails(card);
            if (completionDetails) section.appendChild(completionDetails);
            appendChatCardActions(section, card);
            return section;
        }

