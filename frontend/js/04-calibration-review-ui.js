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

        function calibrationReviewIsExpired(reviewPayload) {
            const expiresAt = Date.parse(String(reviewPayload?.expires_at || ''));
            return Number.isFinite(expiresAt) && expiresAt <= Date.now();
        }

        function calibrationReviewExpiryText(reviewPayload) {
            const expiresAt = Date.parse(String(reviewPayload?.expires_at || ''));
            if (!Number.isFinite(expiresAt)) return '';
            return new Date(expiresAt).toLocaleString();
        }

        function calibrationRowColumnLabel(column) {
            const labels = {
                source_row: 'CSV row',
                timestamp: 'Timestamp',
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

        function calibrationRowCellText(value) {
            if (value === null || value === undefined || value === '') return '—';
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
            panel.append(note, wrap, loadMore);

            let nextOffset = 0;
            let totalRows = Number(issue.row_count || 0);
            let loading = false;
            let initialized = false;

            const loadPage = async () => {
                if (loading || nextOffset === null || !pendingCalibrationReview?.review_id) return;
                loading = true;
                toggle.disabled = true;
                loadMore.disabled = true;
                note.textContent = 'Loading affected rows…';
                try {
                    const query = new URLSearchParams({
                        issue_id: issueId,
                        offset: String(nextOffset),
                        limit: '50',
                    });
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
                    const page = await response.json();
                    const rows = Array.isArray(page.rows) ? page.rows : [];
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
                    rows.forEach((rowData) => {
                        const row = document.createElement('tr');
                        Object.values(rowData).forEach((value) => {
                            const cell = document.createElement('td');
                            cell.textContent = calibrationRowCellText(value);
                            row.appendChild(cell);
                        });
                        body.appendChild(row);
                    });
                    initialized = true;
                    totalRows = Number(page.total_rows || totalRows);
                    nextOffset = page.next_offset === null || page.next_offset === undefined
                        ? null
                        : Number(page.next_offset);
                    note.textContent = 'Showing ' + body.children.length.toLocaleString() + ' of ' + totalRows.toLocaleString() +
                        ' affected source rows. The decision applies to every affected row.';
                    loadMore.hidden = nextOffset === null;
                } catch (error) {
                    note.textContent = error.message || 'Could not load affected rows.';
                    loadMore.hidden = false;
                    loadMore.textContent = 'Retry loading rows';
                } finally {
                    loading = false;
                    toggle.disabled = false;
                    loadMore.disabled = false;
                }
            };

            toggle.addEventListener('click', async () => {
                const expanded = toggle.getAttribute('aria-expanded') !== 'true';
                toggle.setAttribute('aria-expanded', String(expanded));
                toggle.textContent = (expanded ? 'Hide' : 'Show') + ' affected rows (' + totalRows.toLocaleString() + ')';
                panel.classList.toggle('hidden', !expanded);
                if (expanded && !initialized) await loadPage();
            });
            loadMore.addEventListener('click', loadPage);
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
                clean.textContent = 'No discrepancies, missing values, outliers, gaps, or irregular patterns were detected. Continue to calculate the calibration factors.';
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
                    evidence.textContent = 'Examples: ' + samples.slice(0, 3).join(', ');
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
                    actions.forEach((action) => {
                        const option = document.createElement('option');
                        option.value = String(action);
                        option.textContent = action === 'exclude'
                            ? 'Exclude affected rows'
                            : 'Retain affected rows';
                        option.selected = action === selectedDecision;
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
            const blocked = !!summary.blocking || expired;
            const expiresText = calibrationReviewExpiryText(pendingCalibrationReview);
            applyCalibrationReviewBtn.disabled = blocked;
            applyCalibrationReviewBtn.textContent = expired
                ? 'Review expired'
                : summary.blocking
                    ? 'Calibration blocked'
                    : 'Apply decisions & calibrate';
            calibrationReviewActionNote.textContent = expired
                ? 'This private review snapshot expired. Start a new review before calibrating.'
                : summary.blocking
                    ? 'A critical source issue prevents calibration. Change the date range or repair the Bazefield export.'
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

