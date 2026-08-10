        function shortAgentId(value) {
            const text = String(value || '');
            return text.length > 12 ? text.slice(0, 8) + '…' : text || 'None';
        }

        function humanizeAgentField(value) {
            return String(value || '')
                .replace(/_/g, ' ')
                .replace(/\b\w/g, (letter) => letter.toUpperCase());
        }

        function formatAgentValue(value, unit) {
            if (value === null || value === undefined || value === '') return '—';
            if (typeof value === 'boolean') return value ? 'Enabled' : 'Disabled';
            if (typeof value === 'number') {
                const formatted = value.toLocaleString(undefined, { maximumFractionDigits: 4 });
                return unit ? formatted + ' ' + unit : formatted;
            }
            const text = String(value);
            return unit ? text + ' ' + unit : text;
        }

        function isAgentJobActive(job) {
            return !!job && ['queued', 'running'].includes(job.state) && !job.cancel_requested;
        }

        function isAgentJobTerminal(job) {
            return !!job && ['done', 'error', 'cancelled', 'interrupted'].includes(job.state);
        }

        async function readAgentResponse(response, fallbackMessage) {
            let data = {};
            try {
                data = await response.json();
            } catch (_) {
                // A status-based message is safer than exposing an upstream body.
            }
            if (!response.ok) {
                const detail = data.detail;
                const message = Array.isArray(detail) ? detail[0]?.msg : detail;
                throw new Error(message || fallbackMessage || ('Request failed (' + response.status + ')'));
            }
            return data;
        }

        async function postAgentAction(path, body) {
            const response = await fetch(path, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: body === undefined ? undefined : JSON.stringify(body),
            });
            return readAgentResponse(response, 'The scenario action could not be completed.');
        }

        function normalizeAgentState(data) {
            const promoted = data && data.promoted_baselines && typeof data.promoted_baselines === 'object'
                ? data.promoted_baselines
                : {};
            return {
                proposals: Array.isArray(data?.proposals) ? data.proposals.filter(Boolean) : [],
                jobs: Array.isArray(data?.jobs) ? data.jobs.filter(Boolean) : [],
                promoted_baselines: {
                    validation: promoted.validation || null,
                    annual: promoted.annual || null,
                },
            };
        }

        function activeContextWindow(request) {
            const config = request || getCanonicalCurrentConfig(activeMode);
            if (!config.from_date || !config.to_date) return 'Window not set';
            const from = config.from_date;
            const to = config.to_date;
            const times = activeMode === 'validation' && config.from_time && config.to_time
                ? ' ' + config.from_time + '–' + config.to_time
                : '';
            return from + ' to ' + to + times;
        }

        function compactAgentContextWindow(request) {
            const config = request || getCanonicalCurrentConfig(activeMode);
            if (!config.from_date || !config.to_date) return 'Window not set';
            try {
                const from = new Date(config.from_date + 'T00:00:00Z');
                const to = new Date(config.to_date + 'T00:00:00Z');
                const month = new Intl.DateTimeFormat('en-US', { month: 'short', timeZone: 'UTC' });
                const sameMonth = from.getUTCFullYear() === to.getUTCFullYear() && from.getUTCMonth() === to.getUTCMonth();
                return sameMonth
                    ? month.format(from) + ' ' + from.getUTCDate() + '–' + to.getUTCDate()
                    : month.format(from) + ' ' + from.getUTCDate() + ' – ' + month.format(to) + ' ' + to.getUTCDate();
            } catch (_) {
                return activeContextWindow(request);
            }
        }

        function compactAgentRunWindow(request, mode) {
            const config = request || {};
            if (!config.from_date || !config.to_date) return 'Window unavailable';
            let dates;
            try {
                const from = new Date(config.from_date + 'T00:00:00Z');
                const to = new Date(config.to_date + 'T00:00:00Z');
                const month = new Intl.DateTimeFormat('en-US', { month: 'short', timeZone: 'UTC' });
                const sameMonth = from.getUTCFullYear() === to.getUTCFullYear() && from.getUTCMonth() === to.getUTCMonth();
                dates = sameMonth
                    ? month.format(from) + ' ' + from.getUTCDate() + '–' + to.getUTCDate()
                    : month.format(from) + ' ' + from.getUTCDate() + ' – ' + month.format(to) + ' ' + to.getUTCDate();
            } catch (_) {
                dates = config.from_date + ' to ' + config.to_date;
            }
            const timeRange = mode === 'validation' && config.from_time && config.to_time
                ? ' · ' + config.from_time + '–' + config.to_time
                : '';
            return dates + timeRange;
        }

        function agentActivityTimestamp(item) {
            const value = item?.created_at || item?.started_at || item?.completed_at;
            const parsed = value ? Date.parse(value) : NaN;
            return Number.isFinite(parsed) ? parsed : 0;
        }

        function agentActivityPriority(entry) {
            if (entry.type === 'proposal') return 0;
            if (entry.item?.state === 'running') return 1;
            if (entry.item?.state === 'queued') return 2;
            if (['error', 'cancelled', 'interrupted'].includes(entry.item?.state)) return 3;
            return 4;
        }

        function sortAgentActivityItems(items) {
            return [...items].sort((left, right) => {
                const priorityDifference = agentActivityPriority(left) - agentActivityPriority(right);
                if (priorityDifference) return priorityDifference;
                const leftTime = agentActivityTimestamp(left.item);
                const rightTime = agentActivityTimestamp(right.item);
                if ([1, 2].includes(agentActivityPriority(left))) return leftTime - rightTime;
                return rightTime - leftTime;
            });
        }

        function getAgentActivityItems() {
            const proposals = Array.from(agentProposalSnapshots.values())
                .filter((proposal) => !proposal.status || proposal.status === 'pending')
                .map((proposal) => ({
                    type: 'proposal',
                    key: 'proposal:' + proposal.proposal_id,
                    item: proposal,
                }));
            const jobs = Array.from(agentJobSnapshots.values()).map((job) => ({
                type: 'job',
                key: 'job:' + job.job_id,
                item: job,
            }));
            return sortAgentActivityItems([...proposals, ...jobs]);
        }

        function agentActivityCategory(entry) {
            if (entry.type === 'proposal') return 'review';
            return isAgentJobActive(entry.item) ? 'active' : 'complete';
        }

        function agentActivityMatchesFilter(entry, filter = agentActivityFilter) {
            return filter === 'all' || agentActivityCategory(entry) === filter;
        }

        function formatAgentRunHighlight(field, value, request = {}) {
            if (field === 'backtrack') return 'Backtracking ' + (value ? 'on' : 'off');
            if (field === 'curtailment_enabled') return value ? 'Curtailment on' : 'Curtailment off';
            if (field === 'curtailment_limit_kw') return 'Curtailment ' + formatAgentValue(value, 'kW');
            if (field === 'iam_model') return 'IAM ' + (value === 'martin_ruiz' ? 'Martin–Ruiz' : humanizeAgentField(value));
            if (field === 'iam_a_r') return 'IAM a_r ' + formatAgentValue(value);
            if (field === 'interval_value' || field === 'interval_unit') {
                return 'Interval ' + formatAgentValue(request.interval_value) + ' ' + String(request.interval_unit || '').trim();
            }
            return humanizeAgentField(field) + ' ' + formatAgentValue(value);
        }

        function agentRunChangedValues(entry, request) {
            if (entry.type === 'proposal') {
                const changes = Array.isArray(entry.item.changes) ? entry.item.changes : [];
                const windowChanged = changes.some((change) => ['from_date', 'to_date', 'from_time', 'to_time'].includes(change.field));
                const highlights = changes
                    .filter((change) => !['from_date', 'to_date', 'from_time', 'to_time'].includes(change.field))
                    .map((change) => formatAgentRunHighlight(change.field, change.to, request));
                if (windowChanged) highlights.unshift('Window changed');
                return [...new Set(highlights)];
            }

            const baseline = entry.item.baseline_job_id
                ? agentJobSnapshots.get(entry.item.baseline_job_id)
                : null;
            const baselineRequest = baseline?.request;
            if (!baselineRequest || !request) return [];
            const fields = [
                'backtrack',
                'curtailment_enabled',
                'curtailment_limit_kw',
                'iam_model',
                'iam_a_r',
                'interval_value',
                'interval_unit',
                'solaredge_inverter_efficiency',
                'solaredge_bos_efficiency',
                'solectria_inverter_efficiency',
                'solectria_bos_efficiency',
            ];
            return [...new Set(fields
                .filter((field) => String(request[field] ?? '') !== String(baselineRequest[field] ?? ''))
                .map((field) => formatAgentRunHighlight(field, request[field], request)))];
        }

        function summarizeAgentRequest(entry) {
            const request = entry.type === 'proposal' ? entry.item.effective_request : entry.item.request;
            const mode = entry.item.mode === 'annual' ? 'annual' : 'validation';
            let highlights = agentRunChangedValues(entry, request || {});
            if (!highlights.length && request) {
                highlights = [];
                if (request.interval_value !== undefined || request.interval_unit) {
                    highlights.push(formatAgentRunHighlight('interval_value', request.interval_value, request));
                }
                if (Object.prototype.hasOwnProperty.call(request, 'backtrack')) {
                    highlights.push(formatAgentRunHighlight('backtrack', !!request.backtrack, request));
                }
                if (request.iam_model) highlights.push(formatAgentRunHighlight('iam_model', request.iam_model, request));
            }
            return {
                mode,
                window: compactAgentRunWindow(request, mode),
                highlights: highlights.filter((value) => value && !value.includes('—')),
                request: request || null,
            };
        }

        function agentRunConfigurationRows(request, mode) {
            if (!request || typeof request !== 'object') return [];
            const rows = [
                ['Window', compactAgentRunWindow(request, mode)],
                ['Interval', formatAgentValue(request.interval_value) + ' ' + String(request.interval_unit || '').trim()],
                ['Backtracking', request.backtrack ? 'On' : 'Off'],
                ['IAM', request.iam_model === 'martin_ruiz' ? 'Martin–Ruiz' : humanizeAgentField(request.iam_model || 'physical')],
            ];
            if (request.curtailment_enabled) rows.push(['Curtailment', formatAgentValue(request.curtailment_limit_kw, 'kW')]);
            else rows.push(['Curtailment', 'Off']);
            if (request.iam_model === 'martin_ruiz' && request.iam_a_r !== null && request.iam_a_r !== undefined) {
                rows.push(['IAM a_r', formatAgentValue(request.iam_a_r)]);
            }
            [
                ['SolarEdge inverter', request.solaredge_inverter_efficiency],
                ['SolarEdge BOS', request.solaredge_bos_efficiency],
                ['Solectria inverter', request.solectria_inverter_efficiency],
                ['Solectria BOS', request.solectria_bos_efficiency],
            ].forEach(([label, value]) => {
                if (value !== null && value !== undefined && value !== '') rows.push([label, formatAgentValue(value)]);
            });
            return rows.filter(([, value]) => value && value !== '— ');
        }

        function buildAgentRunConfiguration(request, mode) {
            const rows = agentRunConfigurationRows(request, mode);
            if (!rows.length) return null;
            const section = document.createElement('section');
            section.className = 'agent-run-configuration';
            const title = document.createElement('div');
            title.className = 'agent-run-configuration-title';
            title.textContent = 'Run configuration';
            const chips = document.createElement('div');
            chips.className = 'agent-run-configuration-chips';
            rows.slice(0, 5).forEach(([label, value]) => {
                const chip = document.createElement('span');
                chip.className = 'agent-run-chip';
                chip.textContent = label + ': ' + value;
                chips.appendChild(chip);
            });
            section.append(title, chips);
            if (rows.length > 5) {
                const details = document.createElement('details');
                details.className = 'agent-details';
                const summary = document.createElement('summary');
                summary.textContent = 'All model inputs (' + rows.length + ')';
                const grid = document.createElement('div');
                grid.className = 'agent-details-grid';
                rows.forEach(([labelText, value]) => {
                    const item = document.createElement('div');
                    const label = document.createElement('strong');
                    label.textContent = labelText;
                    item.append(label, document.createTextNode(value));
                    grid.appendChild(item);
                });
                details.append(summary, grid);
                section.appendChild(details);
            }
            return section;
        }

        function updateAgentContext() {
            if (!agentContextText || !agentContextBadge) return;
            const modeLabel = activeView === 'technoeconomic'
                ? 'Technoeconomic · Annual production'
                : (activeMode === 'annual' ? 'Annual' : 'Calibration');
            const baselineId = agentServerState.promoted_baselines?.[activeMode] || null;
            const baselineJob = baselineId ? agentJobSnapshots.get(baselineId) : null;
            const state = baselineJob?.state || (baselineId ? 'done' : 'not run');
            const stateLabel = state === 'done' ? 'ready' : humanizeAgentField(state);
            const baselineRequest = baselineJob?.request || baselineJob?.provenance?.request || baselineJob?.provenance?.request_snapshot || baselineJob?.provenance?.candidate_request || null;
            const currentRequest = getCanonicalCurrentConfig(activeMode);
            const contextIamModel = baselineId ? baselineRequest?.iam_model : currentRequest.iam_model;
            const iamLabel = contextIamModel === 'martin_ruiz'
                ? 'Martin–Ruiz IAM'
                : (contextIamModel === 'physical' ? 'Physical IAM' : 'IAM not loaded');
            agentContextBadge.classList.toggle('ready', !!baselineId);
            agentContextText.textContent = baselineId
                ? modeLabel + ' · ' + iamLabel + ' · ' + compactAgentContextWindow(baselineRequest) + ' · Baseline ' + shortAgentId(baselineId) + ' ' + stateLabel
                : modeLabel + ' · ' + iamLabel + ' · ' + compactAgentContextWindow() + ' · No baseline yet';
            agentContextBadge.title = baselineId
                ? modeLabel + ' with ' + iamLabel + '; baseline job ' + baselineId + ' (' + state + ')'
                : modeLabel + ' with ' + iamLabel + ' has no promoted baseline';
        }

        function putAgentProposal(proposal) {
            if (!proposal || !proposal.proposal_id) return;
            agentProposalSnapshots.set(proposal.proposal_id, proposal);
        }

        function putAgentJob(job) {
            if (!job || !job.job_id) return;
            const previous = agentJobSnapshots.get(job.job_id) || {};
            const merged = { ...previous, ...job };
            agentJobSnapshots.set(job.job_id, merged);
            const startValue = merged.started_at || merged.created_at;
            const parsed = startValue ? Date.parse(startValue) : NaN;
            if (!agentJobStartedAt.has(job.job_id)) {
                agentJobStartedAt.set(job.job_id, Number.isFinite(parsed) ? parsed : Date.now());
            }
        }

        function normalizeAgentAction(data) {
            if (!data) return null;
            const actionTypes = ['proposal', 'proposal_batch', 'job_started', 'job_batch_started', 'data_review_required'];
            if (data.action && actionTypes.includes(data.action.type)) return data.action;
            if (actionTypes.includes(data.type)) return data;
            if (data.job) return { type: 'job_started', job: data.job };
            if (Array.isArray(data.jobs)) return { type: 'job_batch_started', jobs: data.jobs, sweep: data.sweep };
            if (Array.isArray(data.proposals)) return { type: 'proposal_batch', proposals: data.proposals, sweep: data.sweep };
            if (data.proposal) return { type: 'proposal', proposal: data.proposal };
            if (data.proposal_id) return { type: 'proposal', proposal: data };
            if (
                data.job_id &&
                Object.prototype.hasOwnProperty.call(data, 'state') &&
                Object.prototype.hasOwnProperty.call(data, 'kind') &&
                Object.prototype.hasOwnProperty.call(data, 'request')
            ) return { type: 'job_started', job: data };
            return null;
        }

