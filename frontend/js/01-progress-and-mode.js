        function setProgress(pct, stage) {
            const bounded = Math.min(100, Math.max(0, Number(pct) || 0));
            progressWrap.classList.add('visible');
            progressWrap.setAttribute('aria-valuenow', String(Math.round(bounded)));
            progressFill.style.width = bounded + '%';
            progressPct.textContent = Math.round(bounded) + '%';
            progressStage.textContent = stage || '';
        }

        function annualUserFacingText(value) {
            return String(value || '').replace(/\bchunks?\b/gi, 'data');
        }

        function setAnnualProgress(pct, stage) {
            const bounded = Math.min(100, Math.max(0, Number(pct) || 0));
            annualProgressWrap.classList.add('visible');
            annualProgressFill.style.width = bounded + '%';
            annualProgressPct.textContent = Math.round(bounded) + '%';
            annualProgressStage.textContent = annualUserFacingText(stage);
        }

        function showError(msg) {
            errorBanner.textContent = 'Warning: ' + msg;
            errorBanner.classList.add('visible');
        }

        function showAnnualError(msg) {
            annualErrorBanner.textContent = 'Warning: ' + annualUserFacingText(msg);
            annualErrorBanner.classList.add('visible');
        }

        function switchMode(mode, persist = true) {
            activeView = ['annual', 'technoeconomic'].includes(mode) ? mode : 'validation';
            activeMode = activeView === 'validation' ? 'validation' : 'annual';
            const annual = activeView === 'annual';
            const technoeconomic = activeView === 'technoeconomic';
            const validation = activeView === 'validation';
            dashboardTitle.textContent = annual
                ? 'SolarEdge & Solectria Annual Simulation'
                : 'SolarEdge & Solectria Performance Analysis';
            dashboardSubtitle.textContent = annual
                ? 'Carry the reviewed calibration into a long-range forecast of energy and performance.'
                : 'Compare measured power, irradiance, physics-model predictions, and export-ready run artifacts for the SBE Innovation Site.';
            document.body.classList.toggle('dashboard-mode-annual', annual);
            document.body.classList.toggle('dashboard-mode-technoeconomic', technoeconomic);
            document.body.classList.toggle('dashboard-mode-validation', validation);
            validationTab.classList.toggle('active', validation);
            annualTab.classList.toggle('active', annual);
            technoeconomicTab.classList.toggle('active', technoeconomic);
            validationTab.setAttribute('aria-pressed', String(validation));
            annualTab.setAttribute('aria-pressed', String(annual));
            technoeconomicTab.setAttribute('aria-pressed', String(technoeconomic));
            operationsNavLink.href = technoeconomic
                ? '#technoeconomicInputs'
                : (annual ? '#annualControls' : '#analysisControls');
            pvModelNavLink.href = technoeconomic
                ? '#technoeconomicResults'
                : (annual ? '#annualChartGrid' : '#chartGrid');
            setActiveNav(operationsNavLink);
            if (technoeconomic) renderTechnoeconomicAnalysis();
            updateAgentContext();
            if (isInitialChatState()) renderChatWelcome();
            else renderChatFollowups();
            syncChatComposerState();
            if (persist) saveDashboardState();
        }

        function setActiveNav(activeLink) {
            [operationsNavLink, pvModelNavLink].forEach((link) => {
                const active = link === activeLink;
                link.classList.toggle('active', active);
                if (active) {
                    link.setAttribute('aria-current', 'location');
                } else {
                    link.removeAttribute('aria-current');
                }
            });
        }
        function syncCurtailmentLimit() {
            const enabled = curtailmentEnabled.checked;
            curtailmentLimitKw.disabled = !enabled;
            curtailmentLimitGroup.classList.toggle('visible', enabled);
            if (enabled && !curtailmentLimitKw.value.trim()) curtailmentLimitKw.value = '125';
        }

        function syncValidationResultsMode(calibrated) {
            validationResultsHeading.textContent = calibrated ? 'Calibration results' : 'Model results';
            validationResultsDescription.textContent = calibrated
                ? 'Measured energy, seasonally calibrated predictions, and model deltas over the selected window.'
                : 'Measured energy, uncalibrated physics-model performance, and deltas over the selected window.';
            validationResultsNote.textContent = calibrated ? 'Seasonally calibrated' : 'Physics model';
            validationEnergyChartTitle.textContent = calibrated
                ? 'Calibrated Cumulative Energy'
                : 'Physics-Model Cumulative Energy';
            validationAcChartTitle.textContent = calibrated ? 'Calibrated AC Power' : 'Physics-Model AC Power';
            document.querySelectorAll('.validation-prediction-stage-label').forEach((label) => {
                label.textContent = calibrated ? 'Calibrated prediction' : 'Physics-model prediction';
            });
        }

        function syncCalibrationMode() {
            const enabled = calibrateModel.checked;
            calibrationSeasonNote.classList.toggle('visible', enabled);
            validationActionTitle.textContent = enabled ? 'Ready to calibrate?' : 'Ready to run?';
            validationActionCopy.textContent = enabled
                ? 'Retrieve and review Bazefield quality first; calibration begins only after your retain/exclude decisions pass the source-data gate.'
                : 'Run the physics model with the selected Bazefield data without fitting calibration factors.';
            if (!currentRunState || !['reviewing', 'starting', 'applying_review', 'queued', 'running'].includes(currentRunState.state)) {
                runBtn.textContent = enabled ? 'Run calibration' : 'Run model';
            }
        }

        function getSelectedIamModel(radios) {
            const selected = Array.from(radios).find((radio) => radio.checked);
            return selected && selected.value === 'martin_ruiz' ? 'martin_ruiz' : 'physical';
        }

        function setSelectedIamModel(radios, model) {
            const normalized = model === 'martin_ruiz' ? 'martin_ruiz' : 'physical';
            radios.forEach((radio) => {
                radio.checked = radio.value === normalized;
            });
        }

        function resolveSavedIamModel(form) {
            if (form.iamModel === 'physical' || form.iamModel === 'martin_ruiz') {
                return form.iamModel;
            }
            // Legacy dashboards always used Martin–Ruiz; includeIam only controlled whether a_r was customized.
            if (Object.prototype.hasOwnProperty.call(form, 'includeIam')) {
                return 'martin_ruiz';
            }
            return 'physical';
        }

        function syncIamAr() {
            const enabled = getSelectedIamModel(iamModelRadios) === 'martin_ruiz';
            iamAr.disabled = !enabled;
            iamArGroup.classList.toggle('visible', enabled);
            if (!iamAr.value) iamAr.value = '0.2';
        }

        function syncAnnualCurtailmentLimit() {
            const enabled = annualCurtailmentEnabled.checked;
            annualCurtailmentLimitKw.disabled = !enabled;
            annualCurtailmentLimitGroup.classList.toggle('visible', enabled);
            if (enabled && !annualCurtailmentLimitKw.value.trim()) annualCurtailmentLimitKw.value = '125';
        }

        function syncAnnualIamAr() {
            const enabled = getSelectedIamModel(annualIamModelRadios) === 'martin_ruiz';
            annualIamAr.disabled = !enabled;
            annualIamArGroup.classList.toggle('visible', enabled);
            if (!annualIamAr.value) annualIamAr.value = '0.2';
        }

