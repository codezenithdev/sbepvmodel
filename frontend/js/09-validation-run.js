        async function runAnalysis() {
            errorBanner.classList.remove('visible');
            const fromTime = read24HourTime('fromTime', 'Start time');
            if (fromTime === null) return;
            const toTime = read24HourTime('toTime', 'End time');
            if (toTime === null) return;
            const validationWindow = readValidationWindow(fromTime, toTime);
            if (validationWindow === null) return;
            const intervalValue = readPositiveInteger('intervalValue', 'Time interval');
            if (intervalValue === null) return;
            const calibrationRequested = calibrateModel.checked;
            const curtailmentOn = curtailmentEnabled.checked;
            const curtailmentLimit = parseFloat(curtailmentLimitKw.value);
            if (curtailmentOn && (!Number.isFinite(curtailmentLimit) || curtailmentLimit <= 0)) {
                showError('Enter a positive curtailment limit in kW.');
                curtailmentLimitKw.focus();
                return;
            }
            const solaredgeInverterEfficiency = readEfficiency('solaredgeInverterEfficiency', 'SolarEdge inverter efficiency');
            if (solaredgeInverterEfficiency === null) return;
            const solaredgeBosEfficiency = readEfficiency('solaredgeBosEfficiency', 'SolarEdge BOS efficiency');
            if (solaredgeBosEfficiency === null) return;
            const solectriaInverterEfficiency = readEfficiency('solectriaInverterEfficiency', 'Solectria inverter efficiency');
            if (solectriaInverterEfficiency === null) return;
            const solectriaBosEfficiency = readEfficiency('solectriaBosEfficiency', 'Solectria BOS efficiency');
            if (solectriaBosEfficiency === null) return;
            const iamModel = getSelectedIamModel(iamModelRadios);
            const iamArValue = parseFloat(iamAr.value);
            if (iamModel === 'martin_ruiz' && (!Number.isFinite(iamArValue) || iamArValue <= 0)) {
                showError('Martin–Ruiz a_r must be positive.');
                iamAr.focus();
                return;
            }

            const statusPollRevision = invalidateValidationStatusPoll();
            latestJobId = null;
            abortCalibrationReviewRequests();
            calibrationWorkflowRevision += 1;
            const workflowRevision = calibrationWorkflowRevision;
            const reviewController = new AbortController();
            calibrationReviewAbortController = reviewController;
            runBtn.disabled = true;
            runBtn.textContent = calibrationRequested ? 'Reviewing data...' : 'Starting model...';
            setProgress(
                5,
                calibrationRequested
                    ? 'Retrieving Bazefield data for quality review...'
                    : 'Queuing uncalibrated physics-model run...'
            );
            clearCalibrationReview();
            calibrationFactorPanel.classList.add('hidden');
            renderUncalibratedComparison(null, false);
            renderValidationRunContext(null);
            syncValidationResultsMode(calibrationRequested);
            latestInputPlots = null;
            latestResult = null;
            currentRunState = {
                state: calibrationRequested ? 'reviewing' : 'starting',
                progress: 5,
                stage: calibrationRequested ? 'Retrieving Bazefield data...' : 'Queuing model run...',
            };
            clearRunImages();
            ['statSeMeasured', 'statSolMeasured', 'statMeasuredDiff', 'statMeasuredDiffPct',
                'statSePred', 'statSolPred', 'statSePct', 'statSolPct'].forEach((id) => {
                document.getElementById(id).textContent = '--';
            });
            setExcelLink(null);
            saveDashboardState();

            const body = {
                from_date: validationWindow.fromDate,
                from_time: fromTime,
                to_date: validationWindow.toDate,
                to_time: toTime,
                interval_value: intervalValue,
                interval_unit: document.getElementById('intervalUnit').value,
                backtrack: document.getElementById('backtrack').checked,
                solaredge_inverter_efficiency: solaredgeInverterEfficiency,
                solaredge_bos_efficiency: solaredgeBosEfficiency,
                solectria_inverter_efficiency: solectriaInverterEfficiency,
                solectria_bos_efficiency: solectriaBosEfficiency,
                iam_model: iamModel,
                curtailment_enabled: curtailmentOn,
                curtailment_limit_kw: curtailmentOn ? curtailmentLimit : null,
                calibrate_model: calibrationRequested,
            };
            if (iamModel === 'martin_ruiz') body.iam_a_r = iamArValue;

            try {
                const endpoint = calibrationRequested ? '/api/calibration-reviews' : '/api/run';
                const res = await fetch(endpoint, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(body),
                    signal: reviewController.signal,
                });
                if (!res.ok) {
                    let msg = (calibrationRequested
                        ? 'Failed to review Bazefield data ('
                        : 'Failed to start model run (') + res.status + ')';
                    try {
                        const err = await res.json();
                        if (err.detail) {
                            msg = Array.isArray(err.detail) ? err.detail[0].msg : err.detail;
                        }
                    } catch (_) {
                        // Keep the status-based message if the response body is not JSON.
                    }
                    throw new Error(msg);
                }
                const payload = await res.json();
                if (
                    workflowRevision !== calibrationWorkflowRevision ||
                    statusPollRevision !== validationPollRevision
                ) return;
                if (calibrationRequested) {
                    renderCalibrationReview(payload);
                } else {
                    latestJobId = payload.job_id;
                    currentRunState = { state: 'queued', progress: 5, stage: 'Uncalibrated model queued' };
                    runBtn.textContent = 'Running...';
                    registerDirectRun(payload.job_id, 'validation', body, 5, 'Uncalibrated model queued');
                    saveDashboardState();
                    progressWrap.focus({ preventScroll: true });
                    pollStatus(payload.job_id, statusPollRevision);
                }
            } catch (e) {
                if (e?.name === 'AbortError' || workflowRevision !== calibrationWorkflowRevision) {
                    return;
                }
                showError(e.message || (calibrationRequested
                    ? 'Could not review Bazefield data.'
                    : 'Could not start the model run.'));
                currentRunState = null;
                resetRunBtn();
                progressWrap.classList.remove('visible');
                saveDashboardState();
            } finally {
                if (calibrationReviewAbortController === reviewController) {
                    calibrationReviewAbortController = null;
                }
            }
        }

        async function applyCalibrationReview() {
            if (!pendingCalibrationReview?.review_id) {
                showError('Start a new Bazefield data review before calibrating.');
                return;
            }
            if (calibrationReviewIsExpired(pendingCalibrationReview)) {
                showError('This data review expired. Start a new review before calibrating.');
                cancelCalibrationReview({ focusRunButton: true });
                return;
            }
            if (!sourceDecisionAcknowledgement.checked) {
                showError('Confirm that you reviewed the flagged rows and decisions before calibrating.');
                sourceDecisionAcknowledgement.focus();
                return;
            }
            const submittedDecisions = { ...calibrationReviewDecisions() };
            pendingCalibrationReview.decisions = { ...submittedDecisions };
            const reviewedRequest = getCanonicalCurrentConfig('validation');
            reviewedRequest.calibrate_model = true;
            const statusPollRevision = invalidateValidationStatusPoll();
            latestJobId = null;
            calibrationIssueList.querySelectorAll('.calibration-decision-select').forEach((select) => {
                select.disabled = true;
            });
            backToCalibrationDecisionsBtn.disabled = true;
            sourceDecisionAcknowledgement.disabled = true;
            if (reviewedCalibrationAbortController) {
                reviewedCalibrationAbortController.abort();
            }
            const workflowRevision = calibrationWorkflowRevision;
            const runController = new AbortController();
            reviewedCalibrationAbortController = runController;
            let responseStatus = null;
            applyCalibrationReviewBtn.disabled = true;
            confirmCalibrationReviewBtn.disabled = true;
            confirmCalibrationReviewBtn.textContent = 'Queuing calibration...';
            setProgress(22, 'Applying data-quality decisions...');
            currentRunState = {
                state: 'applying_review',
                progress: 22,
                stage: 'Applying data-quality decisions',
            };
            setCalibrationControlsLocked(true);
            cancelCalibrationReviewBtn.disabled = true;
            saveDashboardState();
            try {
                const res = await fetch(
                    '/api/calibration-reviews/' + encodeURIComponent(pendingCalibrationReview.review_id) + '/run',
                    {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ decisions: submittedDecisions }),
                        signal: runController.signal,
                    }
                );
                responseStatus = res.status;
                if (!res.ok) {
                    let message = 'Could not start reviewed calibration (' + res.status + ')';
                    try {
                        const error = await res.json();
                        if (error.detail) message = Array.isArray(error.detail) ? error.detail[0].msg : error.detail;
                    } catch (_) {
                        // Keep the status-based message.
                    }
                    throw new Error(message);
                }
                const data = await res.json();
                if (
                    workflowRevision !== calibrationWorkflowRevision ||
                    statusPollRevision !== validationPollRevision
                ) return;
                latestJobId = data.job_id;
                currentRunState = { state: 'queued', progress: 22, stage: 'Reviewed calibration queued' };
                setCalibrationControlsLocked(false);
                cancelCalibrationReviewBtn.disabled = false;
                pendingCalibrationReview = {
                    ...pendingCalibrationReview,
                    decisions: { ...submittedDecisions },
                    applied: true,
                    applied_at: new Date().toISOString(),
                    job_id: data.job_id,
                    data_quality: data.data_quality || null,
                };
                renderCalibrationReview(pendingCalibrationReview, { focusPanel: false });
                runBtn.textContent = 'Running...';
                registerDirectRun(data.job_id, 'validation', reviewedRequest, 22, 'Reviewed calibration queued');
                saveDashboardState();
                progressWrap.focus({ preventScroll: true });
                pollStatus(data.job_id, statusPollRevision);
            } catch (error) {
                if (error?.name === 'AbortError' || workflowRevision !== calibrationWorkflowRevision) {
                    return;
                }
                showError(error.message || 'Could not start reviewed calibration.');
                if (responseStatus === 410) {
                    cancelCalibrationReview({ focusRunButton: true });
                    return;
                }
                setCalibrationControlsLocked(false);
                cancelCalibrationReviewBtn.disabled = false;
                calibrationIssueList.querySelectorAll('.calibration-decision-select').forEach((select) => {
                    select.disabled = false;
                });
                backToCalibrationDecisionsBtn.disabled = false;
                sourceDecisionAcknowledgement.disabled = false;
                currentRunState = {
                    state: 'review_required',
                    progress: 20,
                    stage: 'Data-quality decision required',
                };
                progressWrap.classList.remove('visible');
                applyCalibrationReviewBtn.disabled = false;
                applyCalibrationReviewBtn.textContent = 'Apply decisions & calibrate';
                confirmCalibrationReviewBtn.disabled = false;
                confirmCalibrationReviewBtn.textContent = 'Confirm decisions & calibrate';
                saveDashboardState();
                confirmCalibrationReviewBtn.focus();
            } finally {
                if (reviewedCalibrationAbortController === runController) {
                    reviewedCalibrationAbortController = null;
                }
            }
        }

        function cancelCalibrationReview({ focusRunButton = false } = {}) {
            calibrationWorkflowRevision += 1;
            abortCalibrationReviewRequests();
            setCalibrationControlsLocked(false);
            cancelCalibrationReviewBtn.disabled = false;
            clearCalibrationReview();
            progressWrap.classList.remove('visible');
            currentRunState = null;
            resetRunBtn();
            saveDashboardState();
            if (focusRunButton) {
                runBtn.focus();
            }
        }

        function resetRunBtn() {
            runBtn.disabled = false;
            runBtn.textContent = calibrateModel.checked ? 'Run calibration' : 'Run model';
        }

        async function pollStatus(jobId, pollRevision = validationPollRevision, failureCount = 0) {
            if (pollRevision !== validationPollRevision || jobId !== latestJobId) return;
            if (pollTimer) {
                clearTimeout(pollTimer);
                pollTimer = null;
            }
            try {
                const res = await fetch('/api/status/' + encodeURIComponent(jobId), { cache: 'no-store' });
                if (pollRevision !== validationPollRevision || jobId !== latestJobId) return;
                if (!res.ok) {
                    if (res.status === 404) {
                        currentRunState = { state: 'missing', progress: 0, stage: 'Run is no longer available' };
                        latestJobId = null;
                        latestResult = null;
                        latestInputPlots = null;
                        agentJobSnapshots.delete(jobId);
                        updateStoredChatActionCardStatus({ job_id: jobId }, 'unavailable');
                        renderAgentActivity();
                        progressWrap.classList.remove('visible');
                        showError('This run is no longer available on the server.');
                        resetRunBtn();
                        saveDashboardState();
                        return;
                    }
                    const statusError = new Error('Status request failed (' + res.status + ')');
                    statusError.retryable = res.status === 408 || res.status === 429 || res.status >= 500;
                    throw statusError;
                }
                const data = await res.json();
                if (pollRevision !== validationPollRevision || jobId !== latestJobId) return;
                setProgress(data.progress, data.stage);
                currentRunState = {
                    state: data.state,
                    progress: data.progress,
                    stage: data.stage || '',
                };
                putAgentJob(data);
                renderAgentJobUpdate(data);
                if (data.input_plots) {
                    latestInputPlots = data.input_plots;
                    applyInputPlots(data.input_plots);
                }
                saveDashboardState();

                if (data.state === 'done') {
                    latestResult = data.result;
                    if (data.result && data.result.input_plots) {
                        latestInputPlots = data.result.input_plots;
                    }
                    applyResult(data.result);
                    currentRunState = { state: 'done', progress: 100, stage: 'Done' };
                    saveDashboardState();
                    resetRunBtn();
                    await refreshAgentState(false);
                    return;
                }
                if (data.state === 'error') {
                    showError(data.error || 'Run failed.');
                    progressWrap.classList.remove('visible');
                    saveDashboardState();
                    resetRunBtn();
                    await refreshAgentState(false);
                    return;
                }
                if (data.state === 'cancelled' || data.state === 'interrupted') {
                    showError(data.state === 'interrupted' ? 'Run was interrupted and can be started again.' : 'Run was cancelled.');
                    progressWrap.classList.remove('visible');
                    saveDashboardState();
                    resetRunBtn();
                    await refreshAgentState(false);
                    return;
                }
                pollTimer = setTimeout(() => pollStatus(jobId, pollRevision, 0), 600);
            } catch (e) {
                if (pollRevision !== validationPollRevision || jobId !== latestJobId) return;
                const nextFailureCount = failureCount + 1;
                const retryable = e?.retryable !== false;
                if (retryable && nextFailureCount <= STATUS_POLL_MAX_FAILURES) {
                    const retryDelay = statusPollRetryDelay(nextFailureCount);
                    const reconnectStage = 'Status unavailable; retrying (' + nextFailureCount + '/' + STATUS_POLL_MAX_FAILURES + ')...';
                    currentRunState = {
                        state: currentRunState?.state || 'running',
                        progress: currentRunState?.progress || 0,
                        stage: reconnectStage,
                    };
                    setProgress(currentRunState.progress, reconnectStage);
                    putAgentJob({
                        ...(agentJobSnapshots.get(jobId) || { job_id: jobId }),
                        stage: reconnectStage,
                    });
                    renderAgentJobUpdate(agentJobSnapshots.get(jobId));
                    saveDashboardState();
                    pollTimer = setTimeout(
                        () => pollStatus(jobId, pollRevision, nextFailureCount),
                        retryDelay
                    );
                    return;
                }
                const message = retryable
                    ? 'Status monitoring paused after repeated connection failures. Open Solar Agent Runs to refresh or cancel this job.'
                    : (e.message || 'The server rejected the status request.');
                showError(message);
                currentRunState = {
                    state: 'monitoring_error',
                    progress: currentRunState?.progress || 0,
                    stage: 'Status monitoring paused',
                };
                setProgress(currentRunState.progress, currentRunState.stage);
                runBtn.disabled = true;
                runBtn.textContent = 'Monitoring paused';
                saveDashboardState();
                await refreshAgentState(false);
            }
        }

