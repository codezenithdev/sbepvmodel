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
            const jobs = Array.isArray(data?.jobs) ? data.jobs.filter(Boolean) : [];
            const requestedHistoryLimit = Number(data?.history_limit);
            const historyLimit = Number.isInteger(requestedHistoryLimit) && requestedHistoryLimit > 0
                ? Math.min(MAX_RECENT_AGENT_RUNS, requestedHistoryLimit)
                : MAX_RECENT_AGENT_RUNS;
            const hasRecentJobIds = Object.prototype.hasOwnProperty.call(data || {}, 'recent_job_ids');
            const fallbackRecentJobIds = jobs
                .filter(isAgentJobTerminal)
                .sort((left, right) => agentActivityTimestamp(right) - agentActivityTimestamp(left))
                .map((job) => String(job.job_id || ''))
                .filter(Boolean);
            const recentJobIds = (hasRecentJobIds && Array.isArray(data?.recent_job_ids)
                ? data.recent_job_ids
                : fallbackRecentJobIds)
                .map((jobId) => String(jobId || ''))
                .filter(Boolean);
            const reportedActivityCount = Number(data?.recent_activity_count);
            const jobsById = new Map(jobs.map((job) => [String(job.job_id || ''), job]));
            const inferredActivityCount = new Set(recentJobIds.map((jobId) => {
                const job = jobsById.get(String(jobId));
                return job ? agentJobActivityKey(job) : 'job:' + String(jobId);
            })).size;
            return {
                proposals: Array.isArray(data?.proposals) ? data.proposals.filter(Boolean) : [],
                jobs,
                recent_job_ids: [...new Set(recentJobIds)],
                recent_activity_count: Number.isInteger(reportedActivityCount) && reportedActivityCount >= 0
                    ? Math.min(historyLimit, reportedActivityCount)
                    : Math.min(historyLimit, inferredActivityCount),
                history_limit: historyLimit,
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

        function normalizedAgentRequestYears(request) {
            if (!Array.isArray(request?.years)) return [];
            return [...new Set(request.years.map(Number).filter(Number.isInteger))]
                .sort((left, right) => left - right);
        }

        function compactAgentResolvedDateWindow(request, mode) {
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

        function compactAgentRunWindow(request, mode) {
            const years = mode === 'annual' ? normalizedAgentRequestYears(request) : [];
            if (years.length) {
                return years.join(', ') + ' · ' + years.length + (years.length === 1 ? ' year' : ' years');
            }
            return compactAgentResolvedDateWindow(request, mode);
        }

        function agentActivityTimestamp(item) {
            const value = isAgentJobTerminal(item)
                ? item?.completed_at || item?.interrupted_at || item?.updated_at || item?.created_at
                : item?.started_at || item?.created_at || item?.updated_at;
            const parsed = value ? Date.parse(value) : NaN;
            return Number.isFinite(parsed) ? parsed : 0;
        }

        function agentActivityPriority(entry) {
            if (Number.isInteger(entry.activityPriority)) return entry.activityPriority;
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
                const leftTime = Number.isFinite(left.activityTimestamp)
                    ? left.activityTimestamp
                    : agentActivityTimestamp(left.item);
                const rightTime = Number.isFinite(right.activityTimestamp)
                    ? right.activityTimestamp
                    : agentActivityTimestamp(right.item);
                if ([1, 2].includes(agentActivityPriority(left))) return leftTime - rightTime;
                return rightTime - leftTime;
            });
        }

        function getAgentActivityItems() {
            const proposals = Array.from(agentProposalSnapshots.values())
                .filter((proposal) => !proposal.status || proposal.status === 'pending')
                .filter((proposal) => !agentParameterSweepMetadata(proposal))
                .map((proposal) => ({
                    type: 'proposal',
                    key: 'proposal:' + proposal.proposal_id,
                    item: proposal,
                }));
            const jobs = Array.from(agentJobSnapshots.values())
                .filter(isAgentJobInActivityWorkspace)
                .filter((job) => !isAgentParameterSweepJob(job))
                .map((job) => ({
                    type: 'job',
                    key: 'job:' + job.job_id,
                    item: job,
                }));
            return sortAgentActivityItems([...proposals, ...jobs]);
        }

        function agentHistoryLimit() {
            const value = Number(agentServerState?.history_limit);
            return Number.isInteger(value) && value > 0
                ? Math.min(MAX_RECENT_AGENT_RUNS, value)
                : MAX_RECENT_AGENT_RUNS;
        }

        function isAgentJobInActivityWorkspace(job) {
            if (!job?.job_id) return false;
            if (!isAgentJobTerminal(job)) return true;
            const metadata = agentParameterSweepMetadata(job);
            if (metadata) {
                const activeMemberExists = Array.from(agentJobSnapshots.values()).some((item) => {
                    const itemMetadata = agentParameterSweepMetadata(item);
                    return itemMetadata?.sweep_id === metadata.sweep_id && !isAgentJobTerminal(item);
                });
                const pendingProposalExists = Array.from(agentProposalSnapshots.values()).some((proposal) => (
                    agentParameterSweepMetadata(proposal)?.sweep_id === metadata.sweep_id &&
                    (!proposal.status || proposal.status === 'pending')
                ));
                if (activeMemberExists || pendingProposalExists) return true;
            }
            const recentIds = new Set((agentServerState.recent_job_ids || []).map(String));
            if (!recentIds.has(String(job.job_id))) return false;
            return recentAgentActivityKeys().has(agentJobActivityKey(job));
        }

        function agentJobActivityKey(job) {
            const metadata = agentParameterSweepMetadata(job);
            return metadata?.sweep_id
                ? 'sweep:' + String(metadata.sweep_id)
                : 'job:' + String(job?.job_id || '');
        }

        function recentAgentActivityKeys() {
            const keys = [];
            const seen = new Set();
            (agentServerState.recent_job_ids || []).forEach((jobId) => {
                const job = agentJobSnapshots.get(String(jobId));
                if (!job) return;
                const key = agentJobActivityKey(job);
                if (!key || seen.has(key)) return;
                seen.add(key);
                keys.push(key);
            });
            return new Set(keys.slice(0, agentHistoryLimit()));
        }

        function rememberTerminalAgentJob(job) {
            if (!isAgentJobTerminal(job) || !job?.job_id) return;
            const jobId = String(job.job_id);
            const current = Array.isArray(agentServerState.recent_job_ids)
                ? agentServerState.recent_job_ids.map(String)
                : [];
            agentServerState.recent_job_ids = [jobId, ...current.filter((item) => item !== jobId)];
            agentServerState.recent_activity_count = recentAgentActivityKeys().size;
        }

        function moveAgentActivityToHistory(job = null) {
            if (agentActivityFilter !== 'active') return false;
            const terminalJob = isAgentJobTerminal(job) ? job : null;
            const sweepMetadata = terminalJob ? agentParameterSweepMetadata(terminalJob) : null;
            const sweepHasActiveMembers = sweepMetadata && Array.from(agentJobSnapshots.values()).some((item) => {
                const metadata = agentParameterSweepMetadata(item);
                return metadata?.sweep_id === sweepMetadata.sweep_id && !isAgentJobTerminal(item);
            });
            if (sweepHasActiveMembers) return false;
            const activeJobsRemain = Array.from(agentJobSnapshots.values())
                .filter(isAgentJobInActivityWorkspace)
                .some((item) => !isAgentJobTerminal(item));
            if (activeJobsRemain) return false;
            agentActivityFilter = 'complete';
            if (terminalJob) agentActivitySelection = 'job:' + terminalJob.job_id;
            return true;
        }

        function reconcileAgentActivityFilterAfterRefresh() {
            if (agentActivityFilter !== 'active') return;
            const selectedJobId = agentActivitySelection?.startsWith('job:')
                ? agentActivitySelection.slice(4)
                : null;
            const selectedJob = selectedJobId ? agentJobSnapshots.get(selectedJobId) : null;
            if (isAgentJobTerminal(selectedJob) && isAgentJobInActivityWorkspace(selectedJob)) {
                moveAgentActivityToHistory(selectedJob);
                return;
            }
            const activeJobsRemain = Array.from(agentJobSnapshots.values())
                .filter(isAgentJobInActivityWorkspace)
                .some((item) => !isAgentJobTerminal(item));
            if (activeJobsRemain) return;
            const latestTerminal = (agentServerState.recent_job_ids || [])
                .map((jobId) => agentJobSnapshots.get(String(jobId)))
                .find(isAgentJobTerminal);
            if (latestTerminal) moveAgentActivityToHistory(latestTerminal);
        }

        function agentActivityCategory(entry) {
            if (entry.type === 'proposal') return 'review';
            return isAgentJobTerminal(entry.item) ? 'complete' : 'active';
        }

        function agentActivityMatchesFilter(entry, filter = agentActivityFilter) {
            return filter === 'all' || agentActivityCategory(entry) === filter;
        }

        function formatAgentRunHighlight(field, value, request = {}) {
            if (field === 'years') {
                const years = normalizedAgentRequestYears({ years: value });
                return years.length ? 'MIDC years ' + years.join(', ') : 'MIDC years not set';
            }
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
                'years',
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
                if (normalizedAgentRequestYears(request).length) {
                    highlights.push(formatAgentRunHighlight('years', request.years, request));
                }
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
            const annualYears = mode === 'annual' ? normalizedAgentRequestYears(request) : [];
            const rows = [
                [annualYears.length ? 'MIDC years' : 'Window', compactAgentRunWindow(request, mode)],
                ['Interval', formatAgentValue(request.interval_value) + ' ' + String(request.interval_unit || '').trim()],
                ['Backtracking', request.backtrack ? 'On' : 'Off'],
                ['IAM', request.iam_model === 'martin_ruiz' ? 'Martin–Ruiz' : humanizeAgentField(request.iam_model || 'physical')],
            ];
            if (annualYears.length && request.from_date && request.to_date) {
                rows.splice(1, 0, ['Resolved coverage', compactAgentResolvedDateWindow(request, mode)]);
            }
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
            if (activeView === 'technoeconomic') {
                const context = getTechnoeconomicChatContext();
                const jobState = context.job_state || 'draft';
                const basis = context.analysis_basis === 'commercial_representative'
                    ? 'Commercial representative'
                    : context.analysis_basis === 'solartac_site'
                        ? 'SolarTAC site'
                        : 'Basis not selected';
                const source = context.source_annual_job_id
                    ? 'Source ' + shortAgentId(context.source_annual_job_id)
                    : 'No source selected';
                agentContextBadge.classList.toggle('ready', jobState === 'done');
                agentContextText.textContent = 'Technoeconomic read-only context · ' + basis + ' · ' + source + ' · ' + humanizeAgentField(jobState);
                agentContextBadge.title = 'Solar Agent can explain this TEA context, but its actions remain Annual or Calibration model workflows.';
                return;
            }
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

        function putAgentJob(job, options = {}) {
            if (!job || !job.job_id) return;
            const hadPrevious = agentJobSnapshots.has(job.job_id);
            const previous = agentJobSnapshots.get(job.job_id) || {};
            const merged = { ...previous, ...job };
            agentJobSnapshots.set(job.job_id, merged);
            const startValue = merged.started_at || merged.created_at;
            const parsed = startValue ? Date.parse(startValue) : NaN;
            if (!agentJobStartedAt.has(job.job_id)) {
                agentJobStartedAt.set(job.job_id, Number.isFinite(parsed) ? parsed : Date.now());
            }
            const becameTerminal = isAgentJobTerminal(merged) && (!hadPrevious || !isAgentJobTerminal(previous));
            if (becameTerminal && options?.recordTerminal !== false) {
                rememberTerminalAgentJob(merged);
                moveAgentActivityToHistory(merged);
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

