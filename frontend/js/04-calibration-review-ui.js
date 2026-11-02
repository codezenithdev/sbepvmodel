        const calibrationWeatherElements = Object.fromEntries([
            'Options', 'Temperature', 'Wind', 'Mode', 'Period', 'From', 'To',
            'Actions', 'PreviewBtn', 'DiscardBtn', 'Status', 'Evidence', 'EvidenceNote',
            'Rows', 'PreviousBtn', 'NextBtn',
        ].map((name) => [name, document.getElementById('calibrationWeather' + name)]));
        let calibrationWeatherAbortController = null;
        let calibrationWeatherEvidenceOffset = 0;
        let calibrationWeatherEvidenceTotal = 0;

        function calibrationWeatherSelection() {
            const fields = [];
            if (calibrationWeatherElements.Temperature.checked) fields.push('temp_air');
            if (calibrationWeatherElements.Wind.checked) fields.push('wind_speed');
            const selection = { fields, mode: calibrationWeatherElements.Mode.value };
            if (selection.mode === 'period') {
                const [fromDate = '', fromTime = ''] = calibrationWeatherElements.From.value.split('T');
                const [toDate = '', toTime = ''] = calibrationWeatherElements.To.value.split('T');
                Object.assign(selection, { from_date: fromDate, from_time: fromTime, to_date: toDate, to_time: toTime });
            }
            return selection;
        }

        function calibrationWeatherSelectionKey(selection) {
            return JSON.stringify({
                fields: [...(selection?.fields || [])].sort(),
                mode: selection?.mode || 'flagged',
                ...(selection?.mode === 'period' ? {
                    from_date: selection.from_date || '', from_time: selection.from_time || '',
                    to_date: selection.to_date || '', to_time: selection.to_time || '',
                } : {}),
            });
        }

        function calibrationWeatherNeedsPreview() {
            if (!pendingCalibrationReview || pendingCalibrationReview.applied) return false;
            const selection = calibrationWeatherSelection();
            const replacement = pendingCalibrationReview.weather_replacement;
            if (!replacement) return selection.fields.length > 0;
            const previewed = pendingCalibrationReview.weather_preview_key || calibrationWeatherSelectionKey({
                ...replacement.selection, fields: replacement.fields, mode: replacement.mode,
            });
            return calibrationWeatherSelectionKey(selection) !== previewed;
        }

        function calibrationWeatherSummaryText(replacement = pendingCalibrationReview?.weather_replacement) {
            if (!replacement) return '';
            if (Number.isInteger(replacement.used_replaced_cells) && Number.isInteger(replacement.excluded_replaced_cells)) {
                return replacement.used_replaced_cells.toLocaleString() + ' MIDC weather value(s) sent to calibration · ' +
                    replacement.excluded_replaced_cells.toLocaleString() + ' replacement value(s) excluded by review decisions.';
            }
            return Number(replacement.replaced_cells || 0).toLocaleString() + ' weather value(s) replaced with SolarTAC MIDC · ' +
                Number(replacement.unavailable_cells || 0).toLocaleString() + ' value(s) without a usable replacement.';
        }

        function updateCalibrationWeatherControls() {
            if (!pendingCalibrationReview) return;
            const selection = calibrationWeatherSelection();
            const busy = !!calibrationWeatherAbortController;
            const locked = busy || !!pendingCalibrationReview.applied ||
                calibrationReviewIsExpired(pendingCalibrationReview) || currentRunState?.state === 'applying_review';
            calibrationWeatherElements.Options.disabled = locked;
            calibrationWeatherElements.Period.hidden = selection.mode !== 'period';
            calibrationWeatherElements.Actions.hidden = !!pendingCalibrationReview.applied;
            calibrationWeatherElements.PreviewBtn.disabled = locked || !selection.fields.length ||
                (selection.mode === 'period' && (!selection.from_date || !selection.from_time || !selection.to_date || !selection.to_time));
            calibrationWeatherElements.PreviewBtn.textContent = busy ? 'Loading MIDC evidence...' : 'Preview MIDC replacements';
            calibrationWeatherElements.DiscardBtn.hidden = !pendingCalibrationReview.weather_replacement && !selection.fields.length;
            calibrationWeatherElements.DiscardBtn.disabled = locked;
            calibrationWeatherElements.PreviousBtn.disabled = busy;
            calibrationWeatherElements.NextBtn.disabled = busy;
            if (!pendingCalibrationReview.applied) {
                sourceDecisionAcknowledgement.disabled = busy || currentRunState?.state === 'applying_review';
                confirmCalibrationReviewBtn.disabled = locked || calibrationWeatherNeedsPreview() || !sourceDecisionAcknowledgement.checked;
            }
        }

        function renderCalibrationWeatherEvidence(events, offset = 0, total = 0) {
            const rows = Array.isArray(events) ? events.slice(0, 50) : [];
            calibrationWeatherEvidenceOffset = offset;
            calibrationWeatherEvidenceTotal = Math.max(Number(total) || 0, offset + rows.length);
            calibrationWeatherElements.Rows.replaceChildren();
            rows.forEach((event) => {
                const row = document.createElement('tr');
                const field = event.field === 'temp_air' ? 'Ambient temperature (°C)' : 'Wind speed (m/s)';
                const replacement = event.replacement_value;
                const values = [formatCalibrationReviewTimestamp(event.timestamp), field,
                    event.original_value == null ? 'Missing' : String(event.original_value),
                    replacement == null ? 'Unavailable' : String(replacement),
                    replacement == null ? 'Unchanged — review required' : 'Replaced'];
                values.forEach((value) => {
                    const cell = document.createElement('td');
                    cell.textContent = value;
                    row.appendChild(cell);
                });
                calibrationWeatherElements.Rows.appendChild(row);
            });
            calibrationWeatherElements.Evidence.hidden = !pendingCalibrationReview?.weather_replacement;
            calibrationWeatherElements.EvidenceNote.textContent = rows.length
                ? 'Showing values ' + (offset + 1).toLocaleString() + '–' + (offset + rows.length).toLocaleString() +
                    ' of ' + calibrationWeatherEvidenceTotal.toLocaleString() + '. Review remaining issues below before calibration.'
                : 'No weather values were selected for replacement.';
            calibrationWeatherElements.PreviousBtn.hidden = offset === 0;
            calibrationWeatherElements.NextBtn.hidden = offset + rows.length >= calibrationWeatherEvidenceTotal;
        }

        function renderCalibrationWeatherReplacement() {
            const replacement = pendingCalibrationReview?.weather_replacement;
            const config = getCanonicalCurrentConfig('validation');
            const draft = pendingCalibrationReview?.weather_replacement_ui?.draft || {
                ...(replacement?.selection || {}), fields: replacement?.fields || [], mode: replacement?.mode || 'flagged',
            };
            calibrationWeatherElements.Temperature.checked = (draft.fields || []).includes('temp_air');
            calibrationWeatherElements.Wind.checked = (draft.fields || []).includes('wind_speed');
            calibrationWeatherElements.Mode.value = draft.mode || 'flagged';
            calibrationWeatherElements.From.value = (draft.from_date || config.from_date || '') + 'T' + (draft.from_time || config.from_time || '00:00');
            calibrationWeatherElements.To.value = (draft.to_date || config.to_date || '') + 'T' + (draft.to_time || config.to_time || '00:00');
            calibrationWeatherElements.Status.dataset.error = 'false';
            const warnings = Array.isArray(replacement?.source_warnings) ? replacement.source_warnings.join(' ') : '';
            calibrationWeatherElements.Status.textContent = replacement
                ? calibrationWeatherSummaryText(replacement) + (warnings ? ' ' + warnings : '')
                : 'Select a weather field to preview replacements.';
            if (calibrationWeatherNeedsPreview()) {
                calibrationWeatherElements.Status.textContent = 'Selection changed. Preview these replacements or use original Bazefield data before calibration.';
            }
            renderCalibrationWeatherEvidence(replacement?.events, 0, replacement?.total_events ?? replacement?.selected_cells);
            updateCalibrationWeatherControls();
        }

        function changeCalibrationWeatherSelection() {
            if (!pendingCalibrationReview || pendingCalibrationReview.applied) return;
            pendingCalibrationReview.weather_replacement_ui = { draft: calibrationWeatherSelection() };
            closeCalibrationDecisionGate();
            calibrationWeatherElements.Status.dataset.error = 'false';
            calibrationWeatherElements.Status.textContent = calibrationWeatherNeedsPreview()
                ? 'Selection changed. Preview these replacements or use original Bazefield data before calibration.'
                : calibrationWeatherSummaryText() || 'Select a weather field to preview replacements.';
            updateCalibrationWeatherControls();
            updateCalibrationReviewActionState();
            saveDashboardState();
        }

        async function previewCalibrationWeatherReplacement() {
            if (!pendingCalibrationReview || pendingCalibrationReview.applied || calibrationWeatherAbortController) return;
            const selection = calibrationWeatherSelection();
            if (!selection.fields.length || calibrationReviewIsExpired(pendingCalibrationReview)) return;
            if (selection.mode === 'period' && (!selection.from_date || !selection.to_date ||
                !selection.from_time || !selection.to_time || calibrationWeatherElements.From.value >= calibrationWeatherElements.To.value)) {
                calibrationWeatherElements.Status.textContent = 'Choose a valid known-bad period with the end after the start.';
                calibrationWeatherElements.Status.dataset.error = 'true';
                return;
            }
            const original = pendingCalibrationReview.weather_original_review || {
                ...pendingCalibrationReview, weather_replacement_ui: undefined,
            };
            const originId = pendingCalibrationReview.weather_replacement?.original_review_id || original.review_id;
            const workflowRevision = calibrationWorkflowRevision;
            const controller = new AbortController();
            calibrationWeatherAbortController = controller;
            const timeout = setTimeout(() => controller.abort(), 120000);
            closeCalibrationDecisionGate();
            updateCalibrationWeatherControls();
            updateCalibrationReviewActionState();
            calibrationWeatherElements.Status.dataset.error = 'false';
            calibrationWeatherElements.Status.textContent = 'Retrieving SolarTAC MIDC values and checking interval coverage...';
            try {
                const response = await fetch('/api/calibration-reviews/' + encodeURIComponent(originId) + '/weather-preview', {
                    method: 'POST', headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(selection), signal: controller.signal,
                });
                const payload = await response.json();
                if (!response.ok) throw new Error(typeof payload.detail === 'string' ? payload.detail : 'MIDC replacement preview could not be prepared.');
                if (controller.signal.aborted || workflowRevision !== calibrationWorkflowRevision) return;
                if (!payload.review_id || !payload.report || !payload.weather_replacement) throw new Error('The MIDC preview response is incomplete. Try again.');
                calibrationWeatherAbortController = null;
                renderCalibrationReview({
                    ...payload, weather_original_review: original,
                    weather_replacement_ui: { draft: selection },
                    weather_preview_key: calibrationWeatherSelectionKey(selection),
                }, { focusPanel: false });
            } catch (error) {
                if (workflowRevision !== calibrationWorkflowRevision || !pendingCalibrationReview) return;
                calibrationWeatherElements.Status.dataset.error = 'true';
                calibrationWeatherElements.Status.textContent = error?.name === 'AbortError'
                    ? 'MIDC preview timed out. Your review is unchanged; retry or use original Bazefield data.'
                    : error.message || 'MIDC preview failed. Your review is unchanged.';
            } finally {
                clearTimeout(timeout);
                if (calibrationWeatherAbortController === controller) calibrationWeatherAbortController = null;
                updateCalibrationWeatherControls();
                updateCalibrationReviewActionState();
            }
        }

        async function loadCalibrationWeatherEvidence(offset) {
            if (!pendingCalibrationReview?.weather_replacement || calibrationWeatherAbortController) return;
            const reviewId = pendingCalibrationReview.review_id;
            const controller = new AbortController();
            calibrationWeatherAbortController = controller;
            const timeout = setTimeout(() => controller.abort(), 30000);
            updateCalibrationWeatherControls();
            updateCalibrationReviewActionState();
            try {
                const response = await fetch('/api/calibration-reviews/' + encodeURIComponent(reviewId) +
                    '/weather-preview?offset=' + offset + '&limit=50', { signal: controller.signal });
                const payload = await response.json();
                if (!response.ok) throw new Error(typeof payload.detail === 'string' ? payload.detail : 'Weather evidence could not be loaded.');
                if (controller.signal.aborted || pendingCalibrationReview?.review_id !== reviewId) return;
                renderCalibrationWeatherEvidence(payload.events, offset, payload.total_events ?? calibrationWeatherEvidenceTotal);
            } catch (error) {
                if (pendingCalibrationReview?.review_id !== reviewId) return;
                calibrationWeatherElements.Status.dataset.error = 'true';
                calibrationWeatherElements.Status.textContent = error?.name === 'AbortError' ? 'Weather evidence timed out. Try again.' : error.message;
            } finally {
                clearTimeout(timeout);
                if (calibrationWeatherAbortController === controller) calibrationWeatherAbortController = null;
                updateCalibrationWeatherControls();
                updateCalibrationReviewActionState();
            }
        }

        function discardCalibrationWeatherReplacement() {
            if (!pendingCalibrationReview || pendingCalibrationReview.applied || calibrationWeatherAbortController) return;
            const original = pendingCalibrationReview.weather_original_review;
            if (pendingCalibrationReview.weather_replacement && !original) {
                showError('The original review is unavailable in this session. Change configuration to start a new review.');
                return;
            }
            renderCalibrationReview({ ...(original || pendingCalibrationReview), weather_replacement_ui: undefined }, { focusPanel: false });
        }

        ['Temperature', 'Wind', 'Mode', 'From', 'To'].forEach((name) => {
            calibrationWeatherElements[name].addEventListener('change', changeCalibrationWeatherSelection);
        });
        calibrationWeatherElements.PreviewBtn.addEventListener('click', previewCalibrationWeatherReplacement);
        calibrationWeatherElements.DiscardBtn.addEventListener('click', discardCalibrationWeatherReplacement);
        calibrationWeatherElements.PreviousBtn.addEventListener('click', () => loadCalibrationWeatherEvidence(Math.max(0, calibrationWeatherEvidenceOffset - 50)));
        calibrationWeatherElements.NextBtn.addEventListener('click', () => loadCalibrationWeatherEvidence(calibrationWeatherEvidenceOffset + 50));

        function reviewStat(label, value) {
            const card = document.createElement('div');
            card.className = 'calibration-review-stat';
            const name = document.createElement('span');
            name.textContent = label;
            const amount = document.createElement('strong');
            amount.textContent = value;
            card.append(name, amount);
            return card;
        }

        const CALIBRATION_REVIEW_TIMEZONE = 'America/Denver';
        const calibrationReviewTimestampFormatter = new Intl.DateTimeFormat('en-US', {
            timeZone: CALIBRATION_REVIEW_TIMEZONE,
            month: 'short',
            day: 'numeric',
            year: 'numeric',
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit',
            hourCycle: 'h23',
            timeZoneName: 'short',
        });

        function formatCalibrationReviewTimestamp(value) {
            if (value === null || value === undefined || value === '') return 'n/a';
            const text = String(value).trim();
            const components = text.match(
                /^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})(?::(\d{2})(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?$/i
            );
            if (!components) return text;
            const expected = components.slice(1, 7).map((part) => Number(part || 0));
            const [year, month, day, hour, minute, second] = expected;
            const calendarCheck = new Date(Date.UTC(
                year,
                month - 1,
                day,
                hour,
                minute,
                second
            ));
            if (year < 100) calendarCheck.setUTCFullYear(year);
            const actual = [
                calendarCheck.getUTCFullYear(),
                calendarCheck.getUTCMonth() + 1,
                calendarCheck.getUTCDate(),
                calendarCheck.getUTCHours(),
                calendarCheck.getUTCMinutes(),
                calendarCheck.getUTCSeconds(),
            ];
            if (actual.some((part, index) => part !== expected[index])) return text;
            const normalized = text.replace(' ', 'T');
            const explicitTimestamp = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(normalized)
                ? normalized
                : normalized + 'Z';
            const timestamp = new Date(explicitTimestamp);
            if (Number.isNaN(timestamp.getTime())) return text;
            return calibrationReviewTimestampFormatter.format(timestamp);
        }

        function calibrationReviewIsExpired(reviewPayload) {
            const expiresAt = Date.parse(String(reviewPayload?.expires_at || ''));
            return Number.isFinite(expiresAt) && expiresAt <= Date.now();
        }

        function calibrationReviewExpiryText(reviewPayload) {
            const expiresAt = Date.parse(String(reviewPayload?.expires_at || ''));
            if (!Number.isFinite(expiresAt)) return '';
            return formatCalibrationReviewTimestamp(reviewPayload.expires_at);
        }

        function calibrationRowColumnLabel(column) {
            const labels = {
                source_row: 'CSV row',
                timestamp: 'Timestamp (Mountain)',
                solaredge_measured_power: 'SolarEdge power',
                solectria_measured_power: 'Solectria power',
                dni: 'DNI',
                ghi: 'GHI',
                dhi: 'DHI',
                temp_air: 'Temperature',
                wind_speed: 'Wind speed',
            };
            return labels[column] || String(column).replaceAll('_', ' ');
        }

        function calibrationRowCellText(column, value) {
            if (value === null || value === undefined || value === '') return '—';
            if (column === 'timestamp') return formatCalibrationReviewTimestamp(value);
            if (typeof value === 'number') return value.toLocaleString();
            return String(value);
        }

        function buildCalibrationRowDisclosure(issue, issueIndex) {
            const issueId = String(issue.id || 'issue-' + issueIndex);
            const disclosureId = 'calibrationIssueRows-' + issueIndex;
            const toggle = document.createElement('button');
            toggle.type = 'button';
            toggle.className = 'calibration-row-toggle';
            toggle.textContent = 'Show affected rows (' + Number(issue.row_count || 0).toLocaleString() + ')';
            toggle.setAttribute('aria-expanded', 'false');
            toggle.setAttribute('aria-controls', disclosureId);

            const panel = document.createElement('div');
            panel.className = 'calibration-row-preview hidden';
            panel.id = disclosureId;
            const note = document.createElement('p');
            note.className = 'calibration-row-preview-note';
            note.textContent = 'Rows load from the private, hash-verified review snapshot.';
            const wrap = document.createElement('div');
            wrap.className = 'calibration-row-table-wrap';
            const table = document.createElement('table');
            table.className = 'calibration-row-table';
            const head = document.createElement('thead');
            const body = document.createElement('tbody');
            table.append(head, body);
            wrap.appendChild(table);
            const loadMore = document.createElement('button');
            loadMore.type = 'button';
            loadMore.className = 'calibration-row-toggle';
            loadMore.textContent = 'Load more rows';
            loadMore.hidden = true;
            const showLast = document.createElement('button');
            showLast.type = 'button';
            showLast.className = 'calibration-row-toggle';
            showLast.textContent = 'Last 50 rows';
            showLast.hidden = true;
            const loadAll = document.createElement('button');
            loadAll.type = 'button';
            loadAll.className = 'calibration-row-toggle';
            loadAll.textContent = 'Load all rows';
            loadAll.hidden = true;
            const rowActions = document.createElement('div');
            rowActions.className = 'calibration-row-actions';
            rowActions.append(loadMore, showLast, loadAll);
            panel.append(note, wrap, rowActions);

            let nextOffset = 0;
            let totalRows = Number(issue.row_count || 0);
            let loading = false;
            let initialized = false;
            let viewMode = 'first';
            const rowPageSize = 50;
            const rowActionButtons = [loadMore, showLast, loadAll];

            const setRowLoading = (isLoading, message = '') => {
                loading = isLoading;
                rowActionButtons.forEach((button) => {
                    button.disabled = isLoading;
                });
                if (message) note.textContent = message;
            };

            const updateRowActions = () => {
                const displayedRows = body.children.length;
                const allDisplayed = displayedRows >= totalRows;
                loadMore.hidden = viewMode !== 'first' || nextOffset === null;
                showLast.hidden = totalRows <= rowPageSize;
                showLast.textContent = viewMode === 'last'
                    ? 'Show first 50 rows'
                    : 'Last 50 rows';
                loadAll.hidden = viewMode === 'all' || allDisplayed;
            };

            const updateRowNote = () => {
                const displayedRows = body.children.length.toLocaleString();
                const total = totalRows.toLocaleString();
                const prefix = viewMode === 'last'
                    ? 'Showing the last ' + displayedRows + ' of ' + total
                    : viewMode === 'all'
                        ? 'Showing all ' + displayedRows + ' of ' + total
                        : 'Showing ' + displayedRows + ' of ' + total;
                note.textContent = prefix +
                    ' affected source rows. Timestamps use Mountain Time. ' +
                    'The decision applies to every affected row.';
            };

            const requestRows = async ({ offset, limit = rowPageSize, allRows = false }) => {
                const query = new URLSearchParams({
                    issue_id: issueId,
                    offset: String(offset),
                });
                if (allRows) query.set('all_rows', 'true');
                else query.set('limit', String(limit));
                const response = await fetch(
                    '/api/calibration-reviews/' + encodeURIComponent(pendingCalibrationReview.review_id) + '/rows?' + query.toString()
                );
                if (!response.ok) {
                    let message = 'Could not load affected rows (' + response.status + ')';
                    try {
                        const error = await response.json();
                        if (error.detail) message = String(error.detail);
                    } catch (_) {}
                    throw new Error(message);
                }
                return response.json();
            };

            const renderRowPage = async (page, { replace = false, mode = 'first' } = {}) => {
                const rows = Array.isArray(page.rows) ? page.rows : [];
                if (replace) {
                    head.replaceChildren();
                    body.replaceChildren();
                    initialized = false;
                }
                if (!initialized && rows.length) {
                    const headerRow = document.createElement('tr');
                    Object.keys(rows[0]).forEach((column) => {
                        const cell = document.createElement('th');
                        cell.scope = 'col';
                        cell.textContent = calibrationRowColumnLabel(column);
                        headerRow.appendChild(cell);
                    });
                    head.appendChild(headerRow);
                }
                const renderBatchSize = mode === 'all' ? 250 : Math.max(rows.length, 1);
                for (let start = 0; start < rows.length; start += renderBatchSize) {
                    const fragment = document.createDocumentFragment();
                    rows.slice(start, start + renderBatchSize).forEach((rowData) => {
                        const row = document.createElement('tr');
                        Object.entries(rowData).forEach(([column, value]) => {
                            const cell = document.createElement('td');
                            cell.textContent = calibrationRowCellText(column, value);
                            row.appendChild(cell);
                        });
                        fragment.appendChild(row);
                    });
                    body.appendChild(fragment);
                    const rendered = Math.min(start + renderBatchSize, rows.length);
                    if (mode === 'all' && rendered < rows.length) {
                        note.textContent = 'Rendering ' + rendered.toLocaleString() +
                            ' of ' + rows.length.toLocaleString() + ' affected rows…';
                        await new Promise((resolve) => setTimeout(resolve, 0));
                    }
                }
                initialized = true;
                viewMode = mode;
                totalRows = Number(page.total_rows ?? totalRows);
                nextOffset = mode === 'first' && page.next_offset !== null && page.next_offset !== undefined
                    ? Number(page.next_offset)
                    : null;
                loadMore.textContent = 'Load more rows';
                updateRowNote();
                updateRowActions();
            };

            const loadRows = async ({
                offset,
                limit = rowPageSize,
                replace = false,
                mode = 'first',
                allRows = false,
                message = 'Loading affected rows…',
            }) => {
                if (loading || !pendingCalibrationReview?.review_id) return;
                setRowLoading(true, message);
                try {
                    const page = await requestRows({ offset, limit, allRows });
                    await renderRowPage(page, { replace, mode });
                } catch (error) {
                    note.textContent = error.message || 'Could not load affected rows.';
                    if (mode === 'first') loadMore.textContent = 'Retry loading rows';
                    updateRowActions();
                } finally {
                    setRowLoading(false);
                }
            };

            const loadPage = async () => {
                if (nextOffset === null) return;
                await loadRows({ offset: nextOffset });
            };

            toggle.addEventListener('click', async () => {
                const expanded = toggle.getAttribute('aria-expanded') !== 'true';
                toggle.setAttribute('aria-expanded', String(expanded));
                toggle.textContent = (expanded ? 'Hide' : 'Show') + ' affected rows (' + totalRows.toLocaleString() + ')';
                panel.classList.toggle('hidden', !expanded);
                if (expanded && !initialized) await loadPage();
            });
            loadMore.addEventListener('click', loadPage);
            showLast.addEventListener('click', async () => {
                const showFirst = viewMode === 'last';
                await loadRows({
                    offset: showFirst ? 0 : Math.max(totalRows - rowPageSize, 0),
                    replace: true,
                    mode: showFirst ? 'first' : 'last',
                    message: showFirst
                        ? 'Loading the first 50 affected rows…'
                        : 'Loading the last 50 affected rows…',
                });
            });
            loadAll.addEventListener('click', async () => {
                await loadRows({
                    offset: 0,
                    replace: true,
                    mode: 'all',
                    allRows: true,
                    message: 'Loading all affected rows…',
                });
            });
            return { toggle, panel };
        }

        function setCalibrationReviewCollapsed(collapsed, { persist = true } = {}) {
            calibrationReviewCollapsed = !!collapsed;
            if (
                calibrationReviewCollapsed &&
                calibrationReviewContent.contains(document.activeElement)
            ) {
                calibrationReviewToggle.focus({ preventScroll: true });
            }
            calibrationReviewContent.hidden = calibrationReviewCollapsed;
            calibrationReviewPanel.classList.toggle('collapsed', calibrationReviewCollapsed);
            calibrationReviewToggle.setAttribute('aria-expanded', String(!calibrationReviewCollapsed));
            const action = calibrationReviewCollapsed ? 'Expand' : 'Collapse';
            const label = action + ' Bazefield data review';
            calibrationReviewToggle.setAttribute('aria-label', label);
            calibrationReviewToggle.title = label;
            if (persist) saveDashboardState();
        }

        function renderCalibrationReview(reviewPayload, { focusPanel = true } = {}) {
            pendingCalibrationReview = {
                ...reviewPayload,
                decisions: { ...(reviewPayload?.decisions || {}) },
            };
            const report = reviewPayload?.report || {};
            const summary = report.summary || {};
            const source = report.source || {};
            calibrationReviewSummary.replaceChildren(
                reviewStat('Source rows', Number(source.row_count || 0).toLocaleString()),
                reviewStat('Affected rows', Number(summary.affected_rows || 0).toLocaleString()),
                reviewStat('Missing intervals', Number(summary.missing_intervals || 0).toLocaleString()),
                reviewStat('Issues', Number(summary.issue_count || 0).toLocaleString())
            );

            calibrationReviewSeasons.replaceChildren();
            (report.seasons || []).forEach((season) => {
                const chip = document.createElement('span');
                chip.className = 'calibration-season-chip';
                chip.textContent = String(season.name || 'season') + ' · ' +
                    String(season.months || '') + ' · ' +
                    Number(season.row_count || 0).toLocaleString() + ' rows';
                calibrationReviewSeasons.appendChild(chip);
            });

            calibrationIssueList.replaceChildren();
            const issues = Array.isArray(report.issues) ? report.issues : [];
            if (!issues.length) {
                const clean = document.createElement('div');
                clean.className = 'quality-panel ok';
                clean.textContent = 'No discrepancies, missing values, gaps, or irregular patterns were detected. Continue to calculate the calibration factors.';
                calibrationIssueList.appendChild(clean);
            }
            issues.forEach((issue, issueIndex) => {
                const card = document.createElement('article');
                card.className = 'calibration-issue';

                const copy = document.createElement('div');
                const titleRow = document.createElement('div');
                titleRow.className = 'calibration-issue-title-row';
                const title = document.createElement('span');
                title.className = 'calibration-issue-title';
                title.textContent = String(issue.title || issue.id || 'Data issue');
                const severity = document.createElement('span');
                severity.className = 'calibration-severity ' + String(issue.severity || 'low').toLowerCase();
                severity.textContent = String(issue.severity || 'low');
                const count = document.createElement('span');
                count.className = 'calibration-decision-note';
                count.textContent = Number(issue.row_count || 0).toLocaleString() + ' affected';
                titleRow.append(title, severity, count);
                const description = document.createElement('p');
                description.className = 'calibration-issue-description';
                description.textContent = String(issue.description || '');
                copy.append(titleRow, description);
                const samples = Array.isArray(issue.sample_timestamps) ? issue.sample_timestamps : [];
                if (samples.length) {
                    const evidence = document.createElement('p');
                    evidence.className = 'calibration-issue-evidence';
                    evidence.textContent = 'Examples (Mountain): ' + samples.slice(0, 3)
                        .map(formatCalibrationReviewTimestamp)
                        .join(', ');
                    copy.appendChild(evidence);
                }
                const rowDisclosure = issue.affected_rows_available
                    ? buildCalibrationRowDisclosure(issue, issueIndex)
                    : null;
                if (rowDisclosure) copy.appendChild(rowDisclosure.toggle);

                const decision = document.createElement('div');
                const actions = Array.isArray(issue.allowed_actions) ? issue.allowed_actions : [];
                if (actions.length > 1) {
                    const issueId = String(issue.id);
                    const issueTitle = String(issue.title || issue.id || 'data issue');
                    const savedDecision = pendingCalibrationReview.decisions[issueId];
                    const selectedDecision = actions.includes(savedDecision)
                        ? savedDecision
                        : issue.recommended_action;
                    const label = document.createElement('label');
                    label.className = 'calibration-decision-label';
                    label.textContent = 'Decision for ' + issueTitle;
                    const select = document.createElement('select');
                    select.className = 'calibration-decision-select';
                    select.dataset.issueId = issueId;
                    select.setAttribute('aria-label', 'Decision for ' + issueTitle);
                    if (issue.requires_explicit_decision) {
                        const placeholder = document.createElement('option');
                        placeholder.value = '';
                        placeholder.textContent = 'Choose how to handle unavailable MIDC values';
                        placeholder.selected = !actions.includes(savedDecision);
                        select.appendChild(placeholder);
                    }
                    actions.forEach((action) => {
                        const option = document.createElement('option');
                        option.value = String(action);
                        option.textContent = action === 'exclude'
                            ? 'Exclude affected rows'
                            : 'Retain affected rows';
                        option.selected = action === (issue.requires_explicit_decision ? savedDecision : selectedDecision);
                        select.appendChild(option);
                    });
                    pendingCalibrationReview.decisions[issueId] = select.value;
                    select.disabled = !!pendingCalibrationReview.applied;
                    select.addEventListener('change', () => {
                        if (!pendingCalibrationReview) return;
                        pendingCalibrationReview.decisions[issueId] = select.value;
                        closeCalibrationDecisionGate();
                        updateCalibrationReviewActionState();
                        saveDashboardState();
                    });
                    label.appendChild(select);
                    const recommendation = document.createElement('span');
                    recommendation.className = 'calibration-decision-note';
                    recommendation.textContent = 'Recommended: ' + String(issue.recommended_action || 'review');
                    decision.append(label, recommendation);
                } else {
                    const fixed = document.createElement('span');
                    fixed.className = 'calibration-decision-note';
                    fixed.textContent = actions[0] === 'exclude'
                        ? 'Required cleanup · excluded'
                        : 'Informational · no row decision';
                    decision.appendChild(fixed);
                }
                card.append(copy, decision);
                if (rowDisclosure) card.appendChild(rowDisclosure.panel);
                calibrationIssueList.appendChild(card);
            });

            const expired = calibrationReviewIsExpired(pendingCalibrationReview);
            const applied = !!pendingCalibrationReview.applied;
            renderCalibrationWeatherReplacement();
            calibrationReviewActions.hidden = applied;
            cancelCalibrationReviewBtn.hidden = applied;
            applyCalibrationReviewBtn.hidden = applied;
            if (applied) {
                renderAppliedCalibrationDecisionGate(pendingCalibrationReview);
                calibrationReviewActionNote.textContent = 'Source-data decisions were applied to the hash-verified snapshot. The receipt remains visible with this run.';
            } else {
                closeCalibrationDecisionGate();
                cancelCalibrationReviewBtn.disabled = false;
                updateCalibrationReviewActionState();
            }
            calibrationReviewPanel.classList.remove('hidden');
            if (focusPanel && calibrationReviewCollapsed) {
                setCalibrationReviewCollapsed(false, { persist: false });
            } else {
                setCalibrationReviewCollapsed(calibrationReviewCollapsed, { persist: false });
            }
            if (!applied) {
                progressWrap.classList.remove('visible');
                runBtn.textContent = expired ? 'Review expired' : 'Review ready';
                currentRunState = {
                    state: 'review_required',
                    progress: 20,
                    stage: expired ? 'Data-quality review expired' : 'Data-quality decision required',
                };
            }
            saveDashboardState();
            if (focusPanel) {
                requestAnimationFrame(() => {
                    (applied ? calibrationDecisionGateHeading : document.getElementById('calibrationReviewHeading')).focus({ preventScroll: true });
                    calibrationReviewPanel.scrollIntoView({ behavior: 'smooth', block: 'start' });
                });
            }
        }

        function clearCalibrationReview() {
            pendingCalibrationReview = null;
            setCalibrationReviewCollapsed(false, { persist: false });
            calibrationReviewPanel.classList.add('hidden');
            calibrationReviewSummary.replaceChildren();
            calibrationReviewSeasons.replaceChildren();
            calibrationIssueList.replaceChildren();
            closeCalibrationDecisionGate();
            calibrationReviewActions.hidden = false;
            cancelCalibrationReviewBtn.hidden = false;
            applyCalibrationReviewBtn.hidden = false;
        }

        function calibrationReviewWorkflowIsActive() {
            return ['reviewing', 'starting', 'review_required', 'applying_review'].includes(
                currentRunState?.state
            );
        }

        function abortCalibrationReviewRequests() {
            if (calibrationWeatherAbortController) {
                calibrationWeatherAbortController.abort();
                calibrationWeatherAbortController = null;
            }
            if (calibrationReviewAbortController) {
                calibrationReviewAbortController.abort();
                calibrationReviewAbortController = null;
            }
            if (reviewedCalibrationAbortController) {
                reviewedCalibrationAbortController.abort();
                reviewedCalibrationAbortController = null;
            }
        }

        function setCalibrationControlsLocked(locked) {
            const controls = Array.from(
                document.querySelectorAll('#analysisControls input, #analysisControls select, #analysisControls button')
            );
            if (locked) {
                if (calibrationControlDisabledState) return;
                calibrationControlDisabledState = new Map(
                    controls.map((control) => [control, control.disabled])
                );
                controls.forEach((control) => {
                    control.disabled = true;
                });
                return;
            }
            if (!calibrationControlDisabledState) return;
            calibrationControlDisabledState.forEach((wasDisabled, control) => {
                control.disabled = wasDisabled;
            });
            calibrationControlDisabledState = null;
        }

        function calibrationReviewDecisions() {
            const decisions = {};
            calibrationIssueList.querySelectorAll('.calibration-decision-select').forEach((select) => {
                decisions[select.dataset.issueId] = select.value;
            });
            return decisions;
        }

        function updateCalibrationReviewActionState() {
            if (!pendingCalibrationReview || pendingCalibrationReview.applied) return;
            const summary = pendingCalibrationReview?.report?.summary || {};
            const expired = calibrationReviewIsExpired(pendingCalibrationReview);
            const weatherPending = !!calibrationWeatherAbortController || calibrationWeatherNeedsPreview();
            const decisionsPending = Array.from(calibrationIssueList.querySelectorAll('.calibration-decision-select')).some((select) => !select.value);
            const blocked = !!summary.blocking || expired || weatherPending || decisionsPending;
            const expiresText = calibrationReviewExpiryText(pendingCalibrationReview);
            applyCalibrationReviewBtn.disabled = blocked;
            applyCalibrationReviewBtn.textContent = expired
                ? 'Review expired'
                : weatherPending
                    ? 'Preview weather selection first'
                    : decisionsPending
                        ? 'Review unresolved weather values'
                        : summary.blocking
                            ? 'Calibration blocked'
                            : 'Apply decisions & calibrate';
            calibrationReviewActionNote.textContent = expired
                ? 'This private review snapshot expired. Start a new review before calibrating.'
                : weatherPending
                    ? 'Finish the MIDC preview or use original Bazefield data before confirming calibration.'
                    : decisionsPending
                        ? 'Choose retain or exclude for each issue with unavailable MIDC replacement values.'
                        : summary.blocking
                            ? 'A critical source issue prevents calibration. Preview weather replacements if applicable, or change the date range.'
                            : summary.actionable_issue_count
                                ? 'Recommended decisions are selected by default. Open the affected rows, change any choice, then continue.'
                                : 'No retain/exclude choices are needed. Continue to apply any required cleanup and calculate seasonal factors.';
            if (!expired && expiresText) {
                calibrationReviewActionNote.textContent += ' Review expires ' + expiresText + '.';
            }
        }

        function calibrationDecisionBreakdown(decisions = calibrationReviewDecisions()) {
            const issues = pendingCalibrationReview?.report?.issues || [];
            let retainedIssues = 0;
            let excludedIssues = 0;
            let requiredExclusions = 0;
            issues.forEach((issue) => {
                const actions = Array.isArray(issue.allowed_actions) ? issue.allowed_actions : [];
                const action = actions.length > 1
                    ? decisions[String(issue.id)]
                    : actions[0] || issue.recommended_action;
                if (action === 'exclude') {
                    if (actions.length > 1) excludedIssues += 1;
                    else requiredExclusions += 1;
                } else if (action === 'retain' && actions.length > 1) {
                    retainedIssues += 1;
                }
            });
            return { retainedIssues, excludedIssues, requiredExclusions };
        }

        function closeCalibrationDecisionGate() {
            calibrationDecisionGate.classList.add('hidden');
            calibrationDecisionGate.classList.remove('applied');
            calibrationDecisionGateHeading.textContent = 'Confirm the source rows used for calibration';
            calibrationDecisionGateSummary.textContent = '';
            sourceDecisionAcknowledgement.checked = false;
            sourceDecisionAcknowledgement.disabled = false;
            backToCalibrationDecisionsBtn.disabled = false;
            sourceDecisionAcknowledgementLabel.hidden = false;
            calibrationDecisionGateActions.hidden = false;
            confirmCalibrationReviewBtn.disabled = true;
            confirmCalibrationReviewBtn.textContent = 'Confirm decisions & calibrate';
        }

        function openCalibrationDecisionGate() {
            if (!pendingCalibrationReview?.review_id) {
                showError('Start a new Bazefield data review before calibrating.');
                return;
            }
            if (calibrationReviewIsExpired(pendingCalibrationReview)) {
                showError('This data review expired. Start a new review before calibrating.');
                cancelCalibrationReview({ focusRunButton: true });
                return;
            }
            if (calibrationWeatherAbortController || calibrationWeatherNeedsPreview()) {
                showError('Preview the selected MIDC replacements or use original Bazefield data before calibrating.');
                return;
            }
            if (Array.from(calibrationIssueList.querySelectorAll('.calibration-decision-select')).some((select) => !select.value)) {
                showError('Choose retain or exclude for every unresolved weather issue before calibrating.');
                return;
            }
            const summary = pendingCalibrationReview?.report?.summary || {};
            if (summary.blocking) {
                showError('A critical source issue blocks calibration.');
                return;
            }
            const decisions = calibrationReviewDecisions();
            pendingCalibrationReview.decisions = { ...decisions };
            const breakdown = calibrationDecisionBreakdown(decisions);
            calibrationDecisionGate.classList.remove('hidden', 'applied');
            calibrationDecisionGateHeading.textContent = 'Confirm the source rows used for calibration';
            calibrationDecisionGateSummary.textContent =
                breakdown.retainedIssues.toLocaleString() + ' issue decision(s) retain affected rows · ' +
                breakdown.excludedIssues.toLocaleString() + ' issue decision(s) exclude affected rows · ' +
                breakdown.requiredExclusions.toLocaleString() + ' required exclusion(s). ' +
                (pendingCalibrationReview.weather_replacement ? calibrationWeatherSummaryText() + ' ' : '') +
                'Confirm before the reviewed snapshot is queued for meteorological-season calibration.';
            sourceDecisionAcknowledgementLabel.hidden = false;
            calibrationDecisionGateActions.hidden = false;
            sourceDecisionAcknowledgement.checked = false;
            confirmCalibrationReviewBtn.disabled = true;
            calibrationDecisionGateHeading.focus({ preventScroll: true });
            calibrationDecisionGate.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
            saveDashboardState();
        }

        function renderAppliedCalibrationDecisionGate(receipt) {
            const quality = receipt?.data_quality || {};
            const cleaning = quality.cleaning || {};
            const breakdown = calibrationDecisionBreakdown(receipt?.decisions || {});
            const excludedRows = Number(cleaning.excluded_rows || 0);
            const finalRows = Number(cleaning.final_rows || 0);
            calibrationDecisionGate.classList.remove('hidden');
            calibrationDecisionGate.classList.add('applied');
            calibrationDecisionGateHeading.textContent = 'Source-data decision gate passed';
            calibrationDecisionGateSummary.textContent =
                excludedRows.toLocaleString() + ' source row(s) excluded · ' +
                finalRows.toLocaleString() + ' reviewed row(s) sent to the model · ' +
                breakdown.retainedIssues.toLocaleString() + ' retained issue decision(s). ' +
                (quality.weather_replacement || receipt?.weather_replacement
                    ? calibrationWeatherSummaryText(quality.weather_replacement || receipt.weather_replacement) + ' ' : '') +
                (receipt?.job_id ? 'Calibration job ' + String(receipt.job_id) + ' is bound to this decision receipt.' : 'This decision receipt is bound to the reviewed calibration run.');
            sourceDecisionAcknowledgementLabel.hidden = true;
            calibrationDecisionGateActions.hidden = true;
        }

        function factorValue(value) {
            if (value === null || value === undefined || String(value).trim() === '') {
                return 'n/a';
            }
            const number = Number(value);
            return Number.isFinite(number) ? number.toFixed(4) : 'n/a';
        }

        function appendFactorValue(cell, observation) {
            const value = document.createElement('span');
            value.textContent = factorValue(observation?.factor);
            cell.appendChild(value);
        }

        function appendFactorEvidence(cell, label, observation) {
            const line = document.createElement('span');
            line.className = 'calibration-factor-evidence';
            const samples = Number(observation?.sample_count || 0).toLocaleString();
            const hours = Number(observation?.valid_hours || 0).toLocaleString(
                undefined,
                { maximumFractionDigits: 1 }
            );
            line.textContent = label + ': ' + samples + ' samples · ' + hours + ' h';
            cell.appendChild(line);
        }

