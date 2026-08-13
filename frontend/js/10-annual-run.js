        function resetAnnualRunBtn() {
            const loadingBaseline = annualCalibrationElements.strip.classList.contains('loading');
            annualRunBtn.disabled = loadingBaseline;
            annualRunBtn.textContent = loadingBaseline
                ? 'Checking calibration...'
                : (annualCalibrationBaseline
                    ? 'Review & run annual simulation'
                    : 'Run physics-only annual simulation');
        }

        function readAnnualEfficiency(id, label) {
            const input = document.getElementById(id);
            const value = parseFloat(input.value);
            if (!Number.isFinite(value) || value < 0 || value > 1) {
                showAnnualError(label + ' must be a decimal between 0 and 1.');
                input.focus();
                return null;
            }
            return value;
        }

        function buildAnnualRequest() {
            annualErrorBanner.classList.remove('visible');
            const years = readAnnualSelectedYears();
            if (!years.length) {
                showAnnualError('Select at least one MIDC year.');
                (annualYearElements.grid.querySelector('input:not(:disabled)') || annualYearElements.selectAllButton).focus();
                return null;
            }
            const intervalInput = document.getElementById('annualIntervalValue');
            const intervalUnitInput = document.getElementById('annualIntervalUnit');
            const intervalValue = Number(intervalInput.value);
            const intervalUnit = intervalUnitInput.value;
            if (!isSupportedAnnualInterval(intervalValue, intervalUnit)) {
                showAnnualError('Choose a whole-minute interval from 1 to 60 that divides evenly into 24 hours, or exactly 1 hour.');
                intervalInput.focus();
                return null;
            }
            const estimatedRows = estimateAnnualModelRows(years, intervalValue, intervalUnit);
            if (estimatedRows > MAX_ANNUAL_MODEL_ROWS) {
                showAnnualError(
                    'This selection would produce approximately ' + estimatedRows.toLocaleString() +
                    ' rows. Select fewer years or a longer interval to stay within the ' +
                    MAX_ANNUAL_MODEL_ROWS.toLocaleString() + '-row Excel export limit.'
                );
                intervalInput.focus();
                return null;
            }
            const curtailmentOn = annualCurtailmentEnabled.checked;
            const curtailmentLimit = parseFloat(annualCurtailmentLimitKw.value);
            if (curtailmentOn && (!Number.isFinite(curtailmentLimit) || curtailmentLimit <= 0)) {
                showAnnualError('Enter a positive curtailment limit in kW.');
                annualCurtailmentLimitKw.focus();
                return null;
            }
            const solaredgeInverterEfficiency = readAnnualEfficiency('annualSolaredgeInverterEfficiency', 'SolarEdge inverter efficiency');
            if (solaredgeInverterEfficiency === null) return null;
            const solaredgeBosEfficiency = readAnnualEfficiency('annualSolaredgeBosEfficiency', 'SolarEdge BOS efficiency');
            if (solaredgeBosEfficiency === null) return null;
            const solectriaInverterEfficiency = readAnnualEfficiency('annualSolectriaInverterEfficiency', 'Solectria inverter efficiency');
            if (solectriaInverterEfficiency === null) return null;
            const solectriaBosEfficiency = readAnnualEfficiency('annualSolectriaBosEfficiency', 'Solectria BOS efficiency');
            if (solectriaBosEfficiency === null) return null;
            const iamModel = getSelectedIamModel(annualIamModelRadios);
            const iamArValue = parseFloat(annualIamAr.value);
            if (iamModel === 'martin_ruiz' && (!Number.isFinite(iamArValue) || iamArValue <= 0)) {
                showAnnualError('Martin–Ruiz a_r must be positive.');
                annualIamAr.focus();
                return null;
            }
            const body = {
                years,
                interval_value: intervalValue,
                interval_unit: intervalUnit,
                backtrack: document.getElementById('annualBacktrack').checked,
                solaredge_inverter_efficiency: solaredgeInverterEfficiency,
                solaredge_bos_efficiency: solaredgeBosEfficiency,
                solectria_inverter_efficiency: solectriaInverterEfficiency,
                solectria_bos_efficiency: solectriaBosEfficiency,
                iam_model: iamModel,
                curtailment_enabled: curtailmentOn,
                curtailment_limit_kw: curtailmentOn ? curtailmentLimit : null,
            };
            if (iamModel === 'martin_ruiz') body.iam_a_r = iamArValue;
            if (annualCalibrationBaseline?.job_id) {
                body.calibration_baseline_job_id = annualCalibrationBaseline.job_id;
            }
            return body;
        }

        function annualResponseMessage(detail, fallback) {
            if (typeof detail === 'string') return detail;
            if (Array.isArray(detail) && detail[0]?.msg) return detail[0].msg;
            if (detail && typeof detail === 'object' && detail.message) return String(detail.message);
            return fallback;
        }

        async function submitAnnualRequest(body, { acknowledgement = null, requestRevision = annualRequestRevision } = {}) {
            const statusPollRevision = invalidateAnnualStatusPoll();
            annualRunBtn.disabled = true;
            annualRunBtn.textContent = acknowledgement ? 'Queuing confirmed run...' : 'Reviewing request...';
            setAnnualProgress(0, acknowledgement ? 'Validating confirmation...' : 'Checking calibration coverage...');
            annualRunState = { state: 'starting', progress: 0, stage: acknowledgement ? 'Validating confirmation' : 'Checking calibration coverage' };
            saveDashboardState();

            const payload = JSON.parse(JSON.stringify(body));
            if (acknowledgement) payload.seasonal_fallback_acknowledgement = acknowledgement;

            try {
                const res = await fetch('/api/annual-run', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload),
                });
                let responseBody = null;
                try {
                    responseBody = await res.json();
                } catch (_) {
                    responseBody = null;
                }
                if (requestRevision !== annualRequestRevision) return;
                if (statusPollRevision !== annualPollRevision) return;
                if (!res.ok) {
                    const detail = responseBody?.detail;
                    const code = detail && typeof detail === 'object' ? detail.code : null;
                    if (res.status === 409 && code === 'seasonal_fallback_confirmation_required') {
                        openAnnualFallbackConfirmation(body, detail, requestRevision);
                        return;
                    }
                    const message = annualResponseMessage(detail, 'Failed to start annual simulation (' + res.status + ')');
                    if (res.status === 409 && body.calibration_baseline_job_id) {
                        annualProgressWrap.classList.remove('visible');
                        annualRunState = null;
                        clearAnnualFallbackConfirmation();
                        clearAnnualSeasonalFallbackDisplay();
                        showAnnualError(message + ' No annual job was started.');
                        await loadCurrentCalibration({
                            forceSettings: true,
                            conflictMessage: 'The promoted calibration changed before this annual run could be queued. The new shared settings are loaded below; review them and run again.',
                        });
                        return;
                    }
                    throw new Error(message);
                }
                const job_id = responseBody?.job_id;
                if (!job_id) throw new Error('The server did not return an annual job identifier.');
                clearAnnualFallbackConfirmation();
                annualLatestJobId = job_id;
                annualLatestResult = null;
                annualRunState = { state: 'queued', progress: 0, stage: 'Queued...' };
                renderTechnoeconomicAnalysis(null);
                renderAnnualResultCalibration(null);
                clearAnnualImages();
                setAnnualExcelLink(null);
                setAnnualProgress(0, 'Queued...');
                annualRunBtn.textContent = 'Running...';
                registerDirectRun(job_id, 'annual', {
                    ...body,
                    from_date: annualYearElements.fromDate.value,
                    to_date: annualYearElements.toDate.value,
                }, 0, 'Annual simulation queued');
                saveDashboardState();
                pollAnnualStatus(job_id, statusPollRevision);
            } catch (e) {
                if (requestRevision !== annualRequestRevision) return;
                clearAnnualFallbackConfirmation();
                clearAnnualSeasonalFallbackDisplay();
                annualProgressWrap.classList.remove('visible');
                annualRunState = null;
                showAnnualError(e.message || 'Could not start annual simulation.');
                resetAnnualRunBtn();
                saveDashboardState();
            }
        }

        async function runAnnualAnalysis() {
            const body = buildAnnualRequest();
            if (!body) return;
            window.clearSavedResultsDisplayedJob?.('annual');
            annualRequestRevision += 1;
            clearAnnualFallbackConfirmation();
            clearAnnualSeasonalFallbackDisplay();
            annualLatestJobId = null;
            annualLatestResult = null;
            clearAnnualImages();
            setAnnualExcelLink(null);
            await submitAnnualRequest(body, { requestRevision: annualRequestRevision });
        }

        async function confirmAnnualFallback() {
            const pending = annualPendingFallback;
            if (!pending || pending.requestRevision !== annualRequestRevision) {
                cancelAnnualFallbackConfirmation();
                showAnnualError('The annual form or calibration changed. Review the current values and run again.');
                return;
            }
            annualFallbackElements.confirmButton.disabled = true;
            annualFallbackElements.confirmButton.textContent = 'Queuing...';
            setAnnualSeasonalFallbackDisplay(pending);
            setAnnualFallbackVisible(false, { focus: false });
            document.querySelector('[data-annual-season="fall"]')?.focus?.();
            await submitAnnualRequest(pending.body, {
                requestRevision: pending.requestRevision,
                acknowledgement: {
                    accepted: true,
                    source_season: 'spring',
                    target_season: 'fall',
                    confirmation_context_sha256: pending.confirmation_context_sha256,
                },
            });
        }

        async function pollAnnualStatus(jobId, pollRevision = annualPollRevision, failureCount = 0) {
            if (pollRevision !== annualPollRevision || jobId !== annualLatestJobId) return;
            if (annualPollTimer) {
                clearTimeout(annualPollTimer);
                annualPollTimer = null;
            }
            try {
                const res = await fetch('/api/status/' + encodeURIComponent(jobId), { cache: 'no-store' });
                if (pollRevision !== annualPollRevision || jobId !== annualLatestJobId) return;
                if (!res.ok) {
                    if (res.status === 404) {
                        annualRunState = { state: 'missing', progress: 0, stage: 'Run is no longer available' };
                        annualLatestJobId = null;
                        annualLatestResult = null;
                        clearAnnualSeasonalFallbackDisplay();
                        agentJobSnapshots.delete(jobId);
                        updateStoredChatActionCardStatus({ job_id: jobId }, 'unavailable');
                        renderAgentActivity();
                        annualProgressWrap.classList.remove('visible');
                        showAnnualError('This annual run is no longer available on the server.');
                        resetAnnualRunBtn();
                        saveDashboardState();
                        return;
                    }
                    const statusError = new Error('Annual status request failed (' + res.status + ')');
                    statusError.retryable = res.status === 408 || res.status === 429 || res.status >= 500;
                    throw statusError;
                }
                const data = await res.json();
                if (pollRevision !== annualPollRevision || jobId !== annualLatestJobId) return;
                setAnnualProgress(data.progress, data.stage);
                annualRunState = { state: data.state, progress: data.progress, stage: data.stage || '' };
                putAgentJob(data);
                renderAgentJobUpdate(data);
                if (data.input_plots) applyAnnualInputPlots(data.input_plots);
                saveDashboardState();
                if (data.state === 'done') {
                    annualLatestResult = data.result;
                    applyAnnualResult(data.result);
                    annualRunState = { state: 'done', progress: 100, stage: 'Done' };
                    saveDashboardState();
                    resetAnnualRunBtn();
                    await refreshAgentState(false);
                    return;
                }
                if (data.state === 'error') {
                    clearAnnualSeasonalFallbackDisplay();
                    showAnnualError(data.error || 'Annual simulation failed.');
                    annualProgressWrap.classList.remove('visible');
                    saveDashboardState();
                    resetAnnualRunBtn();
                    await refreshAgentState(false);
                    return;
                }
                if (data.state === 'cancelled' || data.state === 'interrupted') {
                    clearAnnualSeasonalFallbackDisplay();
                    showAnnualError(data.state === 'interrupted' ? 'Annual run was interrupted and can be started again.' : 'Annual run was cancelled.');
                    annualProgressWrap.classList.remove('visible');
                    saveDashboardState();
                    resetAnnualRunBtn();
                    await refreshAgentState(false);
                    return;
                }
                annualPollTimer = setTimeout(() => pollAnnualStatus(jobId, pollRevision, 0), 600);
            } catch (e) {
                if (pollRevision !== annualPollRevision || jobId !== annualLatestJobId) return;
                const nextFailureCount = failureCount + 1;
                const retryable = e?.retryable !== false;
                if (retryable && nextFailureCount <= STATUS_POLL_MAX_FAILURES) {
                    const retryDelay = statusPollRetryDelay(nextFailureCount);
                    const reconnectStage = 'Status unavailable; retrying (' + nextFailureCount + '/' + STATUS_POLL_MAX_FAILURES + ')...';
                    annualRunState = {
                        state: annualRunState?.state || 'running',
                        progress: annualRunState?.progress || 0,
                        stage: reconnectStage,
                    };
                    setAnnualProgress(annualRunState.progress, reconnectStage);
                    putAgentJob({
                        ...(agentJobSnapshots.get(jobId) || { job_id: jobId }),
                        stage: reconnectStage,
                    });
                    renderAgentJobUpdate(agentJobSnapshots.get(jobId));
                    saveDashboardState();
                    annualPollTimer = setTimeout(
                        () => pollAnnualStatus(jobId, pollRevision, nextFailureCount),
                        retryDelay
                    );
                    return;
                }
                const message = retryable
                    ? 'Annual status monitoring paused after repeated connection failures. Open Solar Agent Runs to refresh or cancel this job.'
                    : (e.message || 'The server rejected the annual status request.');
                showAnnualError(message);
                annualRunState = {
                    state: 'monitoring_error',
                    progress: annualRunState?.progress || 0,
                    stage: 'Status monitoring paused',
                };
                setAnnualProgress(annualRunState.progress, annualRunState.stage);
                annualRunBtn.disabled = true;
                annualRunBtn.textContent = 'Monitoring paused';
                saveDashboardState();
                await refreshAgentState(false);
            }
        }

        runBtn.addEventListener('click', runAnalysis);
        calibrationReviewToggle.addEventListener('click', () => {
            setCalibrationReviewCollapsed(!calibrationReviewCollapsed);
        });
        applyCalibrationReviewBtn.addEventListener('click', openCalibrationDecisionGate);
        confirmCalibrationReviewBtn.addEventListener('click', applyCalibrationReview);
        backToCalibrationDecisionsBtn.addEventListener('click', () => {
            closeCalibrationDecisionGate();
            applyCalibrationReviewBtn.focus();
        });
        sourceDecisionAcknowledgement.addEventListener('change', () => {
            confirmCalibrationReviewBtn.disabled = !sourceDecisionAcknowledgement.checked;
        });
        cancelCalibrationReviewBtn.addEventListener('click', () => {
            cancelCalibrationReview({ focusRunButton: true });
        });
        curtailmentEnabled.addEventListener('change', syncCurtailmentLimit);
        calibrateModel.addEventListener('change', syncCalibrationMode);
        iamModelRadios.forEach((radio) => radio.addEventListener('change', syncIamAr));
        annualRunBtn.addEventListener('click', runAnnualAnalysis);
        annualYearElements.selectAllButton.addEventListener('click', () => {
            const years = Array.from(annualYearElements.grid.querySelectorAll('input[type="checkbox"]:not(:disabled)'))
                .map((input) => Number(input.value))
                .filter(Number.isInteger);
            setAnnualSelectedYears(years);
            invalidateAnnualRequestFromFormEdit();
            saveDashboardState();
            updateAgentContext();
        });
        annualYearElements.clearButton.addEventListener('click', () => {
            setAnnualSelectedYears([]);
            invalidateAnnualRequestFromFormEdit();
            saveDashboardState();
            updateAgentContext();
        });
        annualCalibrationElements.restoreButton.addEventListener('click', restoreAnnualCalibrationSettings);
        annualFallbackElements.confirmButton.addEventListener('click', confirmAnnualFallback);
        annualFallbackElements.cancelButton.addEventListener('click', cancelAnnualFallbackConfirmation);
        annualFallbackElements.closeButton.addEventListener('click', cancelAnnualFallbackConfirmation);
        document.addEventListener('keydown', handleAnnualFallbackKeydown);
        validationTab.addEventListener('click', () => switchMode('validation'));
        annualTab.addEventListener('click', () => {
            switchMode('annual');
            void loadCurrentCalibration();
        });
        technoeconomicTab.addEventListener('click', () => switchMode('technoeconomic'));
        openAnnualSimulationBtn.addEventListener('click', () => {
            switchMode('annual');
            void loadCurrentCalibration();
            const annualControls = document.getElementById('annualControls');
            annualControls.focus({ preventScroll: true });
            annualControls.scrollIntoView({ block: 'start' });
        });
        [baselineAnnualizedCost, optimizedAnnualizedCost].forEach((input) => {
            input.addEventListener('input', () => {
                renderTechnoeconomicAnalysis();
                saveDashboardState();
            });
            input.addEventListener('change', () => {
                renderTechnoeconomicAnalysis();
                saveDashboardState();
            });
        });
        operationsNavLink.addEventListener('click', () => setActiveNav(operationsNavLink));
        pvModelNavLink.addEventListener('click', () => setActiveNav(pvModelNavLink));
        annualCurtailmentEnabled.addEventListener('change', syncAnnualCurtailmentLimit);
        annualIamModelRadios.forEach((radio) => radio.addEventListener('change', syncAnnualIamAr));
        document.getElementById('annualFromDate').addEventListener('change', updateAnnualRuntimeWarning);
        document.getElementById('annualToDate').addEventListener('change', updateAnnualRuntimeWarning);
        document.getElementById('annualIntervalValue').addEventListener('input', updateAnnualRuntimeWarning);
        document.getElementById('annualIntervalUnit').addEventListener('change', () => {
            normalizeAnnualIntervalControls();
            updateAnnualRuntimeWarning();
        });
        syncCurtailmentLimit();
        syncCalibrationMode();
        syncIamAr();
        syncAnnualCurtailmentLimit();
        syncAnnualIamAr();
        syncAnnualIntervalConstraints();
        updateAnnualRuntimeWarning();
        renderAnnualCalibrationBaseline(null, { state: 'loading' });
        renderAnnualResultCalibration(null);

