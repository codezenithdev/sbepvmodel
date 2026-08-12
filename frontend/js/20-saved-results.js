        // ---- Durable saved results ----
        const MAX_SAVED_RESULTS = 10;
        const savedResultsElements = {
            navButton: document.getElementById('savedResultsNavBtn'),
            navCount: document.getElementById('savedResultsNavCount'),
            validationButton: document.getElementById('saveValidationResultBtn'),
            annualButton: document.getElementById('saveAnnualResultBtn'),
            backdrop: document.getElementById('savedResultsBackdrop'),
            drawer: document.getElementById('savedResultsDrawer'),
            closeButton: document.getElementById('savedResultsCloseBtn'),
            count: document.getElementById('savedResultsCount'),
            body: document.getElementById('savedResultsBody'),
            list: document.getElementById('savedResultsList'),
            live: document.getElementById('savedResultsLive'),
            tabs: Array.from(document.querySelectorAll('[data-saved-results-filter]')),
        };
        let savedResultsItems = [];
        let savedResultsLimit = MAX_SAVED_RESULTS;
        let savedResultsFilter = 'all';
        let savedResultsLoaded = false;
        let savedResultsLoading = false;
        let savedResultsError = '';
        let savedResultsBusyJobId = null;
        let savedResultsRenamingJobId = null;
        let savedResultsSelectedJobId = null;
        const savedResultsViewedJobIds = { validation: null, annual: null };
        const savedResultsRestoredJobs = { validation: null, annual: null };
        let savedResultsReturnFocus = null;
        let savedResultsDrawerOpen = false;
        let savedResultsVisibilityRevision = 0;
        let savedResultsMutationRevision = 0;
        let savedResultsRefreshPromise = null;

        function normalizeSavedResultItem(raw) {
            if (!raw || typeof raw !== 'object') return null;
            const job = raw.job && typeof raw.job === 'object' ? raw.job : {};
            const jobId = String(raw.job_id || job.job_id || '').trim();
            if (!jobId) return null;
            return {
                job_id: jobId,
                name: typeof raw.name === 'string' ? raw.name.trim() : '',
                saved_at: raw.saved_at || null,
                updated_at: raw.updated_at || null,
                job: { ...job, job_id: jobId },
            };
        }

        function normalizeSavedResultsPayload(data) {
            const requestedLimit = Number(data?.limit);
            const limit = Number.isInteger(requestedLimit) && requestedLimit > 0
                ? Math.min(requestedLimit, MAX_SAVED_RESULTS)
                : MAX_SAVED_RESULTS;
            const items = (Array.isArray(data?.saved_results) ? data.saved_results : [])
                .map(normalizeSavedResultItem)
                .filter(Boolean)
                .slice(0, limit);
            return { items, limit };
        }

        function savedResultMode(item) {
            return item?.job?.mode === 'annual' ? 'annual' : 'validation';
        }

        function savedResultRequest(itemOrJob) {
            const job = itemOrJob?.job && typeof itemOrJob.job === 'object'
                ? itemOrJob.job
                : itemOrJob;
            return job?.request || job?.provenance?.request || {};
        }

        function savedResultResult(itemOrJob) {
            const job = itemOrJob?.job && typeof itemOrJob.job === 'object'
                ? itemOrJob.job
                : itemOrJob;
            return job?.result || {};
        }

        function finiteSavedResultNumber(value) {
            if (value === null || value === undefined || value === '') return null;
            const number = Number(value);
            return Number.isFinite(number) ? number : null;
        }

        function formatSavedResultDate(value) {
            if (!value) return '';
            const date = new Date(String(value).slice(0, 10) + 'T00:00:00Z');
            if (Number.isNaN(date.getTime())) return String(value);
            return date.toLocaleDateString(undefined, {
                year: 'numeric',
                month: 'short',
                day: 'numeric',
                timeZone: 'UTC',
            });
        }

        function formatSavedResultTimestamp(value) {
            if (!value) return 'Saved time unavailable';
            const date = new Date(value);
            if (Number.isNaN(date.getTime())) return 'Saved time unavailable';
            return 'Saved ' + date.toLocaleString(undefined, {
                year: 'numeric',
                month: 'short',
                day: 'numeric',
                hour: 'numeric',
                minute: '2-digit',
                timeZone: 'America/Denver',
                timeZoneName: 'short',
            });
        }

        function savedResultYears(itemOrJob) {
            const requestYears = savedResultRequest(itemOrJob).years;
            const result = savedResultResult(itemOrJob);
            const resultRows = result.annual_energy_by_year || result.stats?.annual_energy_by_year;
            const candidates = Array.isArray(requestYears)
                ? requestYears
                : (Array.isArray(resultRows) ? resultRows.map((row) => row?.year) : []);
            return Array.from(new Set(candidates.map(Number).filter(Number.isInteger))).sort((left, right) => left - right);
        }

        function formatSavedResultYears(years) {
            if (!years.length) return '';
            if (years.length === 1) return String(years[0]);
            const consecutive = years.every((year, index) => index === 0 || year === years[index - 1] + 1);
            if (consecutive) return years[0] + '–' + years[years.length - 1];
            if (years.length === 2) return years[0] + ' & ' + years[1];
            return years.slice(0, -1).join(', ') + ' & ' + years[years.length - 1];
        }

        function savedResultWindow(itemOrJob) {
            const request = savedResultRequest(itemOrJob);
            const resultWindow = savedResultResult(itemOrJob).window || {};
            const years = savedResultYears(itemOrJob);
            if (years.length) return 'MIDC years ' + formatSavedResultYears(years);
            const fromDate = request.from_date || resultWindow.from;
            const toDate = request.to_date || resultWindow.to;
            const fromLabel = formatSavedResultDate(fromDate);
            const toLabel = formatSavedResultDate(toDate);
            if (fromLabel && toLabel) return fromLabel + '–' + toLabel;
            return fromLabel || toLabel || 'Run window unavailable';
        }

        function defaultSavedResultName(itemOrJob) {
            const job = itemOrJob?.job && typeof itemOrJob.job === 'object'
                ? itemOrJob.job
                : itemOrJob;
            if (job?.mode === 'annual') {
                const years = formatSavedResultYears(savedResultYears(job));
                return ('Annual · ' + (years || 'completed simulation')).slice(0, 120);
            }
            const request = savedResultRequest(job);
            const workflow = request.calibrate_model === false ? 'Model' : 'Calibration';
            const windowLabel = savedResultWindow(job);
            return (workflow + ' · ' + windowLabel).slice(0, 120);
        }

        function savedResultWorkflowLabel(item) {
            if (savedResultMode(item) === 'annual') return 'Annual';
            return savedResultRequest(item).calibrate_model === false ? 'Model' : 'Calibration';
        }

        function savedResultEnergyKwh(item) {
            const result = savedResultResult(item);
            const stats = result.stats || {};
            const adjusted = stats.calibration_adjusted && typeof stats.calibration_adjusted === 'object'
                ? stats.calibration_adjusted
                : stats;
            const solarEdge = finiteSavedResultNumber(adjusted.se_predicted_kwh);
            const solectria = finiteSavedResultNumber(adjusted.sol_predicted_kwh);
            if (solarEdge !== null || solectria !== null) return (solarEdge || 0) + (solectria || 0);
            const rows = result.annual_energy_by_year || stats.annual_energy_by_year;
            if (!Array.isArray(rows)) return null;
            const totals = rows.map((row) => {
                const combined = finiteSavedResultNumber(row?.combined_predicted_kwh ?? row?.total_predicted_kwh);
                if (combined !== null) return combined;
                const se = finiteSavedResultNumber(row?.se_predicted_kwh);
                const sol = finiteSavedResultNumber(row?.sol_predicted_kwh);
                return se === null && sol === null ? null : (se || 0) + (sol || 0);
            }).filter((value) => value !== null);
            return totals.length ? totals.reduce((total, value) => total + value, 0) : null;
        }

        function savedResultExport(item) {
            const result = savedResultResult(item);
            return {
                href: typeof result.excel === 'string' ? result.excel : '',
                filename: typeof result.excel_filename === 'string' ? result.excel_filename : '',
            };
        }

        function displayedSavedResultJobId(mode) {
            if (mode === 'annual') {
                if (annualLatestJobId && annualLatestResult && annualRunState?.state === 'done') {
                    return annualLatestJobId;
                }
                const readOnlyJobId = savedResultsViewedJobIds.annual;
                const readOnlyLegacyResultIsDisplayed = activeView === 'annual' &&
                    !annualLatestJobId && !annualRunState && !!readOnlyJobId &&
                    !!savedResultByJobId(readOnlyJobId);
                return readOnlyLegacyResultIsDisplayed ? readOnlyJobId : null;
            }
            return latestJobId && latestResult && currentRunState?.state === 'done'
                ? latestJobId
                : null;
        }

        function displayedSavedResultJob(mode) {
            const jobId = displayedSavedResultJobId(mode);
            if (!jobId) return null;
            const savedJob = savedResultByJobId(jobId)?.job || savedResultsRestoredJobs[mode] || {};
            const snapshot = agentJobSnapshots.get(jobId) || {};
            return {
                ...savedJob,
                ...snapshot,
                job_id: jobId,
                mode,
                result: mode === 'annual'
                    ? (annualLatestResult || snapshot.result || savedJob.result)
                    : latestResult,
            };
        }

        function clearSavedResultsDisplayedJob(mode) {
            const normalizedMode = mode === 'annual' ? 'annual' : 'validation';
            savedResultsViewedJobIds[normalizedMode] = null;
            savedResultsRestoredJobs[normalizedMode] = null;
            if (savedResultsDrawerOpen) renderSavedResults();
            else syncSavedResultsControls();
        }

        function getSavedResultsDisplayedContext() {
            const context = {};
            for (const mode of ['validation', 'annual']) {
                const jobId = savedResultsViewedJobIds[mode];
                const job = jobId
                    ? (savedResultByJobId(jobId)?.job || savedResultsRestoredJobs[mode])
                    : null;
                if (jobId && job?.result) context[mode] = { job_id: jobId, job };
            }
            return Object.keys(context).length ? context : null;
        }

        function restoreSavedResultsDisplayedContext(context) {
            if (!context || typeof context !== 'object') return;
            for (const mode of ['validation', 'annual']) {
                const restored = context[mode];
                const jobId = String(restored?.job_id || '').trim();
                const job = restored?.job && typeof restored.job === 'object' ? restored.job : null;
                if (!jobId || !job?.result || (job.mode === 'annual' ? 'annual' : 'validation') !== mode) continue;
                savedResultsViewedJobIds[mode] = jobId;
                savedResultsRestoredJobs[mode] = { ...job, job_id: jobId };
            }
            const legacyAnnual = savedResultsRestoredJobs.annual;
            if (
                legacyAnnual?.result &&
                !annualLatestJobId && !annualLatestResult && !annualRunState
            ) {
                applyAnnualResult(legacyAnnual.result, false);
                if (activeView === 'annual') {
                    showAnnualError('This legacy date-range result is read-only. Select MIDC years before starting a new simulation.');
                }
            }
            syncSavedResultsControls();
        }

        function resetSavedResultsDisplayedJobs() {
            for (const mode of ['validation', 'annual']) {
                savedResultsViewedJobIds[mode] = null;
                savedResultsRestoredJobs[mode] = null;
            }
            savedResultsSelectedJobId = null;
        }

        function savedResultByJobId(jobId) {
            return savedResultsItems.find((item) => item.job_id === jobId) || null;
        }

        function reconcileSavedResultsSelection() {
            const displayedJobId = activeView === 'annual'
                ? displayedSavedResultJobId('annual')
                : (activeView === 'validation' ? displayedSavedResultJobId('validation') : null);
            const nextSelectedJobId = displayedJobId && savedResultByJobId(displayedJobId)
                ? displayedJobId
                : null;
            if (savedResultsSelectedJobId === nextSelectedJobId) return;
            savedResultsSelectedJobId = nextSelectedJobId;
            if (!savedResultsDrawerOpen) return;
            savedResultsElements.list.querySelectorAll('.saved-result-card').forEach((card) => {
                const selected = card.dataset.savedResultJobId === savedResultsSelectedJobId;
                card.classList.toggle('selected', selected);
                if (selected) card.setAttribute('aria-current', 'true');
                else card.removeAttribute('aria-current');
            });
        }

        function announceSavedResults(message) {
            savedResultsElements.live.textContent = '';
            window.requestAnimationFrame(() => {
                savedResultsElements.live.textContent = message || '';
            });
        }

        function filteredSavedResultsItems() {
            return savedResultsItems.filter((item) => (
                savedResultsFilter === 'all' || savedResultMode(item) === savedResultsFilter
            ));
        }

        function focusSavedResultControl(jobId, selector) {
            window.requestAnimationFrame(() => {
                if (!savedResultsDrawerOpen) return;
                const card = Array.from(savedResultsElements.list.querySelectorAll('.saved-result-card'))
                    .find((element) => element.dataset.savedResultJobId === jobId);
                const target = card?.querySelector(selector);
                (target || card)?.focus?.();
            });
        }

        function focusSavedResultsFallback() {
            window.requestAnimationFrame(() => {
                if (!savedResultsDrawerOpen) return;
                const target = savedResultsElements.list.querySelector('.saved-results-retry') ||
                    savedResultsElements.tabs.find((tab) => tab.getAttribute('aria-selected') === 'true') ||
                    savedResultsElements.closeButton;
                target?.focus();
            });
        }

        function syncSavedResultsControls() {
            reconcileSavedResultsSelection();
            const count = savedResultsItems.length;
            const drawerOpen = savedResultsDrawerOpen;
            savedResultsElements.navCount.textContent = String(count);
            savedResultsElements.navButton.setAttribute('aria-label', 'Open saved results, ' + count + ' of ' + savedResultsLimit + ' saved');
            savedResultsElements.navButton.setAttribute('aria-expanded', String(drawerOpen));
            savedResultsElements.navButton.disabled = false;

            const syncWorkflowButton = (button, mode) => {
                const jobId = displayedSavedResultJobId(mode);
                const saved = !!jobId && !!savedResultByJobId(jobId);
                const busy = !!jobId && savedResultsBusyJobId === jobId;
                const full = !!jobId && !saved && count >= savedResultsLimit;
                button.classList.toggle('is-saved', saved);
                button.setAttribute('aria-expanded', String(drawerOpen));
                button.disabled = busy || full || (!jobId && count === 0) || (!savedResultsLoaded && !savedResultsError);
                if (busy) {
                    button.textContent = 'Saving…';
                    button.title = 'Saving this completed result.';
                } else if (saved || (!jobId && count > 0)) {
                    button.textContent = 'Saved results (' + count + ')';
                    button.title = 'Open saved results.';
                } else if (full) {
                    button.textContent = 'Saved results full';
                    button.title = 'Remove a saved result before saving another.';
                } else {
                    button.textContent = 'Save results';
                    button.title = jobId
                        ? 'Keep this completed result without running it again.'
                        : 'Complete a run before saving its results.';
                }
            };

            syncWorkflowButton(savedResultsElements.validationButton, 'validation');
            syncWorkflowButton(savedResultsElements.annualButton, 'annual');
        }

        function setSavedResultsFilter(filter, options = {}) {
            savedResultsFilter = ['all', 'validation', 'annual'].includes(filter) ? filter : 'all';
            savedResultsElements.tabs.forEach((tab) => {
                const selected = tab.dataset.savedResultsFilter === savedResultsFilter;
                tab.classList.toggle('selected', selected);
                tab.setAttribute('aria-selected', String(selected));
                tab.tabIndex = selected ? 0 : -1;
            });
            const activeTab = savedResultsElements.tabs.find((tab) => tab.dataset.savedResultsFilter === savedResultsFilter);
            if (activeTab) savedResultsElements.list.setAttribute('aria-labelledby', activeTab.id);
            renderSavedResults();
            if (options.focus === true) activeTab?.focus();
        }

        function appendSavedResultsState(kind, title, copy) {
            savedResultsElements.list.classList.add('state-only');
            const state = document.createElement('div');
            state.className = 'saved-results-state' + (kind === 'error' ? ' error' : '');
            const heading = document.createElement('strong');
            heading.textContent = title;
            const description = document.createElement('span');
            description.textContent = copy;
            state.append(heading, description);
            if (kind === 'loading') {
                const line = document.createElement('span');
                line.className = 'saved-results-loading-line';
                const shortLine = document.createElement('span');
                shortLine.className = 'saved-results-loading-line short';
                state.append(line, shortLine);
            }
            if (kind === 'error') {
                const retry = document.createElement('button');
                retry.type = 'button';
                retry.className = 'saved-results-retry';
                retry.textContent = 'Retry';
                retry.addEventListener('click', () => refreshSavedResults({ announce: true }));
                state.appendChild(retry);
            }
            savedResultsElements.list.appendChild(state);
        }

        function buildSavedResultRenameForm(item) {
            const form = document.createElement('form');
            form.className = 'saved-result-rename-form';
            const label = document.createElement('label');
            label.className = 'sr-only';
            label.htmlFor = 'saved-result-name-' + item.job_id;
            label.textContent = 'Saved result name';
            const input = document.createElement('input');
            input.className = 'saved-result-rename-input';
            input.id = label.htmlFor;
            input.name = 'name';
            input.type = 'text';
            input.maxLength = 120;
            input.required = true;
            input.value = item.name || defaultSavedResultName(item);
            input.disabled = savedResultsBusyJobId === item.job_id;
            const submit = document.createElement('button');
            submit.className = 'saved-result-rename-submit';
            submit.type = 'submit';
            submit.disabled = savedResultsBusyJobId === item.job_id;
            submit.textContent = savedResultsBusyJobId === item.job_id ? 'Saving…' : 'Save';
            const cancel = document.createElement('button');
            cancel.className = 'saved-result-rename-cancel';
            cancel.type = 'button';
            cancel.textContent = 'Cancel';
            cancel.disabled = savedResultsBusyJobId === item.job_id;
            cancel.addEventListener('click', () => {
                savedResultsRenamingJobId = null;
                renderSavedResults();
                focusSavedResultControl(item.job_id, '.saved-result-menu summary');
            });
            form.addEventListener('submit', (event) => {
                event.preventDefault();
                input.disabled = true;
                submit.disabled = true;
                submit.textContent = 'Saving…';
                cancel.disabled = true;
                renameSavedResult(item, input.value);
            });
            form.append(label, input, submit, cancel);
            window.requestAnimationFrame(() => input.focus());
            return form;
        }

        function buildSavedResultCard(item) {
            const card = document.createElement('article');
            const selected = savedResultsSelectedJobId === item.job_id;
            card.className = 'saved-result-card' + (selected ? ' selected' : '');
            card.dataset.savedResultJobId = item.job_id;
            if (selected) card.setAttribute('aria-current', 'true');

            if (savedResultsRenamingJobId === item.job_id) {
                card.appendChild(buildSavedResultRenameForm(item));
            } else {
                const head = document.createElement('div');
                head.className = 'saved-result-card-head';
                const title = document.createElement('h3');
                title.className = 'saved-result-title';
                title.textContent = item.name || defaultSavedResultName(item);
                const actions = document.createElement('div');
                actions.className = 'saved-result-card-actions';
                const view = document.createElement('button');
                view.type = 'button';
                view.className = 'saved-result-view';
                view.textContent = savedResultsBusyJobId === item.job_id ? 'Opening…' : 'View result';
                view.disabled = savedResultsLoading || savedResultsBusyJobId === item.job_id || dashboardModeHasBlockingRun(savedResultMode(item), item.job_id);
                if (view.disabled && savedResultsBusyJobId !== item.job_id) {
                    view.title = savedResultsLoading
                        ? 'Wait for saved results to refresh.'
                        : 'Finish or cancel the active run in this workflow first.';
                }
                view.addEventListener('click', () => viewSavedResult(item, view));

                const menu = document.createElement('details');
                menu.className = 'saved-result-menu';
                const menuSummary = document.createElement('summary');
                menuSummary.textContent = 'More';
                menuSummary.setAttribute('aria-label', 'More actions for ' + title.textContent);
                if (savedResultsLoading) {
                    menuSummary.setAttribute('aria-disabled', 'true');
                    menuSummary.tabIndex = -1;
                    menuSummary.addEventListener('click', (event) => event.preventDefault());
                }
                const menuPanel = document.createElement('div');
                menuPanel.className = 'saved-result-menu-panel';
                const exported = savedResultExport(item);
                if (exported.href) {
                    const exportLink = document.createElement('a');
                    exportLink.className = 'saved-result-export';
                    exportLink.href = exported.href;
                    exportLink.textContent = 'Export workbook';
                    if (exported.filename) exportLink.download = exported.filename;
                    menuPanel.appendChild(exportLink);
                }
                const rename = document.createElement('button');
                rename.type = 'button';
                rename.className = 'saved-result-menu-action';
                rename.textContent = 'Rename';
                rename.disabled = savedResultsLoading || !!savedResultsBusyJobId;
                rename.addEventListener('click', () => {
                    if (savedResultsLoading || savedResultsBusyJobId) return;
                    savedResultsRenamingJobId = item.job_id;
                    renderSavedResults();
                });
                const remove = document.createElement('button');
                remove.type = 'button';
                remove.className = 'saved-result-menu-action danger';
                remove.textContent = 'Remove';
                remove.disabled = savedResultsLoading || !!savedResultsBusyJobId;
                remove.addEventListener('click', () => removeSavedResult(item, remove));
                menuPanel.append(rename, remove);
                menu.append(menuSummary, menuPanel);
                actions.append(view, menu);
                head.append(title, actions);
                card.appendChild(head);
            }

            const workflow = document.createElement('p');
            workflow.className = 'saved-result-meta';
            workflow.textContent = savedResultWorkflowLabel(item);
            const savedAt = document.createElement('p');
            savedAt.className = 'saved-result-saved-at';
            savedAt.textContent = formatSavedResultTimestamp(item.saved_at);
            const windowLabel = document.createElement('p');
            windowLabel.className = 'saved-result-window';
            windowLabel.textContent = savedResultWindow(item);
            card.append(workflow, savedAt, windowLabel);

            const energyValue = savedResultEnergyKwh(item);
            if (energyValue !== null) {
                const energy = document.createElement('p');
                energy.className = 'saved-result-energy';
                energy.setAttribute('aria-label', 'Combined predicted energy ' + energyValue.toLocaleString(undefined, { maximumFractionDigits: 1 }) + ' kilowatt-hours');
                const number = document.createElement('strong');
                number.textContent = energyValue.toLocaleString(undefined, { minimumFractionDigits: 1, maximumFractionDigits: 1 });
                const unit = document.createElement('span');
                unit.textContent = 'kWh';
                energy.append(number, unit);
                card.appendChild(energy);
            }
            return card;
        }

        function renderSavedResults() {
            reconcileSavedResultsSelection();
            savedResultsElements.count.textContent = savedResultsItems.length + ' of ' + savedResultsLimit + ' saved';
            savedResultsElements.list.innerHTML = '';
            savedResultsElements.list.classList.remove('state-only');
            savedResultsElements.list.setAttribute('aria-busy', String(savedResultsLoading));
            if (savedResultsLoading && !savedResultsLoaded) {
                appendSavedResultsState('loading', 'Loading saved results', 'Restoring the results you chose to keep.');
                syncSavedResultsControls();
                return;
            }
            if (savedResultsError) {
                appendSavedResultsState('error', 'Saved results are unavailable', savedResultsError);
                syncSavedResultsControls();
                return;
            }
            const visible = filteredSavedResultsItems();
            if (!visible.length) {
                const filtered = savedResultsFilter !== 'all';
                const workflow = savedResultsFilter === 'annual' ? 'annual' : 'calibration';
                appendSavedResultsState(
                    'empty',
                    filtered ? 'No saved ' + workflow + ' results' : 'No saved results yet',
                    filtered
                        ? 'Choose another filter or save a completed ' + workflow + ' result.'
                        : 'Complete a calibration or annual simulation, then choose Save results.'
                );
                syncSavedResultsControls();
                return;
            }
            visible.forEach((item) => savedResultsElements.list.appendChild(buildSavedResultCard(item)));
            syncSavedResultsControls();
        }

        async function refreshSavedResults(options = {}) {
            if (savedResultsRefreshPromise) {
                const pending = savedResultsRefreshPromise;
                if (options.force === true) {
                    await pending;
                    return refreshSavedResults({ ...options, force: false });
                }
                return pending;
            }
            const mutationRevisionAtStart = savedResultsMutationRevision;
            savedResultsLoading = true;
            savedResultsError = '';
            renderSavedResults();
            const request = (async () => {
                try {
                    const response = await fetchWithDashboardTimeout('/api/saved-results', { cache: 'no-store' });
                    const data = await readAgentResponse(response, 'Could not load saved results.');
                    if (mutationRevisionAtStart !== savedResultsMutationRevision) return;
                    const normalized = normalizeSavedResultsPayload(data);
                    savedResultsItems = normalized.items;
                    savedResultsLimit = normalized.limit;
                    for (const mode of ['validation', 'annual']) {
                        const restoredId = savedResultsViewedJobIds[mode];
                        const refreshed = restoredId ? savedResultByJobId(restoredId) : null;
                        if (refreshed) savedResultsRestoredJobs[mode] = refreshed.job;
                    }
                    savedResultsLoaded = true;
                    if (options.announce === true) announceSavedResults('Saved results refreshed.');
                } catch (error) {
                    if (mutationRevisionAtStart !== savedResultsMutationRevision) return;
                    savedResultsError = error?.name === 'AbortError'
                        ? 'The request timed out. Check the local API and try again.'
                        : (error.message || 'Could not load saved results.');
                }
            })();
            savedResultsRefreshPromise = request;
            try {
                return await request;
            } finally {
                if (savedResultsRefreshPromise === request) savedResultsRefreshPromise = null;
                savedResultsLoading = false;
                renderSavedResults();
                if (typeof renderAgentActivityWhenIdle === 'function') renderAgentActivityWhenIdle();
            }
        }

        async function saveDisplayedResult(mode) {
            if (savedResultsBusyJobId) return;
            const job = displayedSavedResultJob(mode);
            if (!job) {
                setSavedResultsOpen(true);
                announceSavedResults('Complete a run before saving its results.');
                return;
            }
            if (savedResultByJobId(job.job_id)) {
                savedResultsSelectedJobId = job.job_id;
                setSavedResultsOpen(true);
                renderSavedResults();
                return;
            }
            if (savedResultsItems.length >= savedResultsLimit) {
                setSavedResultsOpen(true);
                announceSavedResults('Saved results is full. Remove one result before saving another.');
                return;
            }
            savedResultsBusyJobId = job.job_id;
            savedResultsMutationRevision += 1;
            syncSavedResultsControls();
            try {
                const defaultName = defaultSavedResultName(job);
                const response = await fetchWithDashboardTimeout('/api/saved-results/' + encodeURIComponent(job.job_id), {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ name: defaultName }),
                });
                await readAgentResponse(response, 'Could not save this result.');
                savedResultsSelectedJobId = job.job_id;
                await refreshSavedResults({ force: true });
                setSavedResultsOpen(true);
                announceSavedResults(defaultName + ' saved.');
            } catch (error) {
                savedResultsError = error.message || 'Could not save this result.';
                setSavedResultsOpen(true);
                renderSavedResults();
            } finally {
                savedResultsBusyJobId = null;
                renderSavedResults();
            }
        }

        async function renameSavedResult(item, requestedName) {
            if (savedResultsBusyJobId) return;
            const name = String(requestedName || '').trim();
            if (!name) {
                announceSavedResults('Enter a name for this saved result.');
                return;
            }
            savedResultsBusyJobId = item.job_id;
            savedResultsMutationRevision += 1;
            try {
                const response = await fetchWithDashboardTimeout('/api/saved-results/' + encodeURIComponent(item.job_id), {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ name: name.slice(0, 120) }),
                });
                await readAgentResponse(response, 'Could not rename this saved result.');
                savedResultsItems = savedResultsItems.map((entry) => entry.job_id === item.job_id
                    ? { ...entry, name: name.slice(0, 120) }
                    : entry);
                savedResultsRenamingJobId = null;
                renderSavedResults();
                await refreshSavedResults({ force: true });
                announceSavedResults('Saved result renamed to ' + name.slice(0, 120) + '.');
                focusSavedResultControl(item.job_id, '.saved-result-menu summary');
            } catch (error) {
                savedResultsError = error.message || 'Could not rename this saved result.';
                renderSavedResults();
                focusSavedResultsFallback();
            } finally {
                savedResultsBusyJobId = null;
                renderSavedResults();
            }
        }

        async function removeSavedResult(item, trigger = null) {
            if (savedResultsBusyJobId) return;
            const name = item.name || defaultSavedResultName(item);
            if (!window.confirm('Remove “' + name + '” from saved results? The underlying completed run will remain in workspace history.')) return;
            const visibleBefore = filteredSavedResultsItems();
            const removedIndex = visibleBefore.findIndex((entry) => entry.job_id === item.job_id);
            savedResultsBusyJobId = item.job_id;
            savedResultsMutationRevision += 1;
            if (trigger) {
                trigger.textContent = 'Removing…';
                trigger.setAttribute('aria-disabled', 'true');
            }
            try {
                const response = await fetchWithDashboardTimeout('/api/saved-results/' + encodeURIComponent(item.job_id), {
                    method: 'DELETE',
                });
                await readAgentResponse(response, 'Could not remove this saved result.');
                savedResultsItems = savedResultsItems.filter((entry) => entry.job_id !== item.job_id);
                if (savedResultsViewedJobIds[savedResultMode(item)] === item.job_id) {
                    savedResultsViewedJobIds[savedResultMode(item)] = null;
                    savedResultsRestoredJobs[savedResultMode(item)] = null;
                }
                if (savedResultsSelectedJobId === item.job_id) savedResultsSelectedJobId = null;
                if (savedResultsRenamingJobId === item.job_id) savedResultsRenamingJobId = null;
                renderSavedResults();
                await refreshSavedResults({ force: true });
                announceSavedResults(name + ' removed from saved results.');
                const visibleAfter = filteredSavedResultsItems();
                const focusItem = visibleAfter[Math.min(Math.max(removedIndex, 0), visibleAfter.length - 1)];
                if (focusItem) focusSavedResultControl(focusItem.job_id, '.saved-result-menu summary');
                else focusSavedResultsFallback();
            } catch (error) {
                savedResultsError = error.message || 'Could not remove this saved result.';
                renderSavedResults();
                focusSavedResultsFallback();
            } finally {
                savedResultsBusyJobId = null;
                renderSavedResults();
            }
        }

        async function viewSavedResult(item, trigger = null) {
            if (savedResultsBusyJobId || savedResultsLoading) return;
            const mode = savedResultMode(item);
            if (dashboardModeHasBlockingRun(mode, item.job_id)) {
                announceSavedResults('Finish or cancel the active ' + (mode === 'annual' ? 'annual' : 'calibration') + ' run first.');
                return;
            }
            savedResultsBusyJobId = item.job_id;
            if (trigger) {
                trigger.textContent = 'Opening…';
                trigger.setAttribute('aria-disabled', 'true');
            }
            const loaded = await viewAgentJobResults(item.job_id, mode);
            savedResultsBusyJobId = null;
            if (!loaded) {
                if (trigger) {
                    trigger.textContent = 'View result';
                    trigger.removeAttribute('aria-disabled');
                    trigger.focus();
                }
                announceSavedResults('This result could not be opened. Try again after refreshing.');
                return;
            }
            savedResultsViewedJobIds[mode] = item.job_id;
            savedResultsRestoredJobs[mode] = item.job;
            savedResultsSelectedJobId = item.job_id;
            syncSavedResultsControls();
            setSavedResultsOpen(false, { focus: false });
            saveDashboardState();
        }

        function syncSavedResultsModalState(open) {
            document.body.classList.toggle('saved-results-open', open);
            if (!dashboardShell) return;
            dashboardShell.toggleAttribute('inert', open);
            dashboardShell.inert = open;
            if (open) dashboardShell.setAttribute('aria-hidden', 'true');
            else dashboardShell.removeAttribute('aria-hidden');
        }

        function setSavedResultsOpen(open, options = {}) {
            const focus = options.focus !== false;
            const nextOpen = !!open;
            const revision = ++savedResultsVisibilityRevision;
            if (nextOpen && focus) savedResultsReturnFocus = document.activeElement;
            if (nextOpen) {
                setChatOpen(false, { focus: false, persist: false });
                savedResultsDrawerOpen = true;
                savedResultsElements.backdrop.hidden = false;
                savedResultsElements.drawer.hidden = false;
                savedResultsElements.drawer.setAttribute('aria-modal', 'true');
                syncSavedResultsModalState(true);
                window.requestAnimationFrame(() => {
                    if (!savedResultsDrawerOpen || revision !== savedResultsVisibilityRevision) return;
                    savedResultsElements.backdrop.classList.add('visible');
                    savedResultsElements.drawer.classList.add('visible');
                    if (focus) savedResultsElements.closeButton.focus();
                });
                reconcileSavedResultsSelection();
                renderSavedResults();
                if (savedResultsLoaded) void refreshSavedResults();
            } else {
                savedResultsDrawerOpen = false;
                savedResultsRenamingJobId = null;
                savedResultsElements.backdrop.classList.remove('visible');
                savedResultsElements.drawer.classList.remove('visible');
                savedResultsElements.drawer.removeAttribute('aria-modal');
                syncSavedResultsModalState(false);
                window.setTimeout(() => {
                    if (savedResultsDrawerOpen || revision !== savedResultsVisibilityRevision) return;
                    savedResultsElements.backdrop.hidden = true;
                    savedResultsElements.drawer.hidden = true;
                }, 220);
                if (focus) {
                    const focusTarget = savedResultsReturnFocus && document.contains(savedResultsReturnFocus)
                        ? savedResultsReturnFocus
                        : savedResultsElements.navButton;
                    window.setTimeout(() => focusTarget.focus?.(), 0);
                }
            }
            syncSavedResultsControls();
        }

        function handleSavedResultsKeydown(event) {
            if (!savedResultsDrawerOpen) return;
            if (event.key === 'Escape') {
                event.preventDefault();
                setSavedResultsOpen(false);
                return;
            }
            if (event.key !== 'Tab') return;
            const focusable = Array.from(savedResultsElements.drawer.querySelectorAll(
                'button:not([disabled]), a[href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), details > summary'
            )).filter((element) => element.getClientRects().length > 0);
            if (!focusable.length) return;
            const first = focusable[0];
            const last = focusable[focusable.length - 1];
            if (event.shiftKey && document.activeElement === first) {
                event.preventDefault();
                last.focus();
            } else if (!event.shiftKey && document.activeElement === last) {
                event.preventDefault();
                first.focus();
            }
        }

        function handleSavedResultsTabKeydown(event) {
            if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
            event.preventDefault();
            const currentIndex = savedResultsElements.tabs.indexOf(event.currentTarget);
            let nextIndex = currentIndex;
            if (event.key === 'Home') nextIndex = 0;
            else if (event.key === 'End') nextIndex = savedResultsElements.tabs.length - 1;
            else if (event.key === 'ArrowLeft') nextIndex = (currentIndex - 1 + savedResultsElements.tabs.length) % savedResultsElements.tabs.length;
            else nextIndex = (currentIndex + 1) % savedResultsElements.tabs.length;
            setSavedResultsFilter(savedResultsElements.tabs[nextIndex].dataset.savedResultsFilter, { focus: true });
        }

        savedResultsElements.navButton.addEventListener('click', () => setSavedResultsOpen(true));
        savedResultsElements.validationButton.addEventListener('click', () => saveDisplayedResult('validation'));
        savedResultsElements.annualButton.addEventListener('click', () => saveDisplayedResult('annual'));
        savedResultsElements.closeButton.addEventListener('click', () => setSavedResultsOpen(false));
        savedResultsElements.backdrop.addEventListener('click', () => setSavedResultsOpen(false));
        savedResultsElements.tabs.forEach((tab) => {
            tab.addEventListener('click', () => setSavedResultsFilter(tab.dataset.savedResultsFilter));
            tab.addEventListener('keydown', handleSavedResultsTabKeydown);
        });
        document.addEventListener('keydown', handleSavedResultsKeydown);
        window.savedResultsDrawerReady = true;
        window.setSavedResultsOpen = setSavedResultsOpen;
        window.clearSavedResultsDisplayedJob = clearSavedResultsDisplayedJob;
        window.getSavedResultsDisplayedContext = getSavedResultsDisplayedContext;
        window.restoreSavedResultsDisplayedContext = restoreSavedResultsDisplayedContext;
        window.resetSavedResultsDisplayedJobs = resetSavedResultsDisplayedJobs;
        renderSavedResults();
        void refreshSavedResults();
