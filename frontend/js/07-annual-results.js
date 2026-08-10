        function annualCalibrationApplication(result) {
            const stats = result?.stats || {};
            const application = result?.calibration_application || stats.calibration_application;
            return application && typeof application === 'object' ? application : null;
        }

        function annualSettingsDeltaDescription(deltas) {
            if (!Array.isArray(deltas) || !deltas.length) return 'No changes; all shared settings matched calibration.';
            return deltas.map((item) => {
                const key = String(item?.field || item?.key || 'setting');
                const label = ANNUAL_SETTING_LABELS[key] || key.replaceAll('_', ' ');
                const calibrated = item?.calibrated_value ?? item?.baseline_value;
                const annual = item?.annual_value ?? item?.current_value;
                return label + ': ' + formatAnnualSettingValue(key, calibrated) + ' → ' + formatAnnualSettingValue(key, annual);
            }).join('; ') + '.';
        }

        function annualAppliedFactorDescription(factors) {
            if (!factors || typeof factors !== 'object') return 'No seasonal calibration factors applied.';
            const names = { winter: 'Winter', spring: 'Spring', summer: 'Summer', fall: 'Fall' };
            return ['winter', 'spring', 'summer', 'fall'].filter((season) => factors[season]).map((season) => {
                const record = factors[season] || {};
                const solarEdge = Number(record.solaredge);
                const solectria = Number(record.solectria);
                return names[season] + ': SolarEdge ' + formatAnnualFactor(Number.isFinite(solarEdge) ? solarEdge : null) +
                    ' / Solectria ' + formatAnnualFactor(Number.isFinite(solectria) ? solectria : null);
            }).join('; ') || 'No seasonal calibration factors applied.';
        }

        function renderAnnualResultCalibration(result) {
            const elements = annualResultCalibrationElements;
            const application = annualCalibrationApplication(result);
            const applied = application?.applied === true;
            elements.panel.classList.toggle('visible', applied);
            elements.panel.classList.remove('fallback-used');
            if (!applied) {
                document.getElementById('annualStatSePhysicsCard').hidden = true;
                document.getElementById('annualStatSolPhysicsCard').hidden = true;
                elements.basis.textContent = 'Physics-only';
                elements.source.textContent = 'No calibration attached';
                elements.settings.textContent = 'Not applicable';
                elements.seasonal.textContent = 'Not applied';
                elements.factors.textContent = 'No seasonal calibration factors applied.';
                elements.settingDetails.textContent = 'No calibration settings were inherited.';
                elements.note.textContent = result ? 'Physics-only annual prediction' : 'Weather inputs render before annual predictions';
                return;
            }
            const deltas = Array.isArray(application.settings_deltas) ? application.settings_deltas : [];
            const substitution = application.seasonal_substitution || null;
            const sourceSeason = String(substitution?.from_season || substitution?.source_season || '').toLowerCase();
            const targetSeason = String(substitution?.to_season || substitution?.target_season || '').toLowerCase();
            const fallbackUsed = sourceSeason === 'spring' && targetSeason === 'fall';
            elements.panel.classList.toggle('fallback-used', fallbackUsed);
            elements.basis.textContent = 'Calibration-adjusted + physics-only';
            elements.source.textContent = [application.baseline_job_id, application.baseline_review_id].filter(Boolean).join(' · ') || '--';
            elements.source.title = application.origin_profile_sha256
                ? 'Origin profile SHA-256: ' + application.origin_profile_sha256
                : '';
            elements.settings.textContent = deltas.length
                ? deltas.length + ' modified setting' + (deltas.length === 1 ? '' : 's')
                : 'Matches calibration';
            elements.seasonal.textContent = fallbackUsed
                ? 'Fall used Spring substitute'
                : ((application.required_seasons || []).length + ' season' + ((application.required_seasons || []).length === 1 ? '' : 's') + ' · frozen factors');
            elements.factors.textContent = annualAppliedFactorDescription(application.seasonal_factors);
            elements.settingDetails.textContent = annualSettingsDeltaDescription(deltas);
            elements.note.textContent = fallbackUsed
                ? 'Calibration-adjusted · Fall used Spring substitute'
                : 'Calibration-adjusted with frozen seasonal factors';
        }

        function applyAnnualResult(result, cacheBust = true) {
            renderTechnoeconomicAnalysis(result);
            renderAnnualResultCalibration(result);
            if (!result || !result.stats) return;
            const s = result.stats;
            const application = annualCalibrationApplication(result);
            const calibrated = application?.applied === true;
            const adjusted = calibrated && s.calibration_adjusted && typeof s.calibration_adjusted === 'object'
                ? s.calibration_adjusted
                : s;
            const physics = calibrated && s.physics_only && typeof s.physics_only === 'object'
                ? s.physics_only
                : null;
            const fmtNum = (v, digits = 1) => (v === null || v === undefined)
                ? 'n/a'
                : Number(v).toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits });
            document.getElementById('annualStatSePredLabel').textContent = calibrated
                ? 'Calibrated SolarEdge energy'
                : 'Uncalibrated SolarEdge energy';
            document.getElementById('annualStatSolPredLabel').textContent = calibrated
                ? 'Calibrated Solectria energy'
                : 'Uncalibrated Solectria energy';
            document.getElementById('annualStatSePred').textContent = fmtNum(adjusted.se_predicted_kwh);
            document.getElementById('annualStatSolPred').textContent = fmtNum(adjusted.sol_predicted_kwh);
            const sePhysicsCard = document.getElementById('annualStatSePhysicsCard');
            const solPhysicsCard = document.getElementById('annualStatSolPhysicsCard');
            sePhysicsCard.hidden = !physics;
            solPhysicsCard.hidden = !physics;
            document.getElementById('annualStatSePhysics').textContent = fmtNum(physics?.se_predicted_kwh);
            document.getElementById('annualStatSolPhysics').textContent = fmtNum(physics?.sol_predicted_kwh);
            document.getElementById('annualStatDiff').textContent = fmtNum(s.predicted_difference_kwh);
            document.getElementById('annualStatDiffPct').textContent = fmtPct(s.predicted_difference_pct);
            document.getElementById('annualStatRows').textContent = Number(s.n_rows || 0).toLocaleString();
            const windowData = result.window || {};
            document.getElementById('annualResultRange').textContent = windowData.from && windowData.to
                ? windowData.from + ' to ' + windowData.to
                : '--';
            const intervalValue = Number(windowData.interval_value);
            const intervalUnit = String(windowData.interval_unit || '').trim();
            document.getElementById('annualResultInterval').textContent = Number.isFinite(intervalValue) && intervalUnit
                ? intervalValue.toLocaleString() + ' ' + intervalUnit
                : '--';
            renderAnnualQuality(result.warnings || s.data_quality_warnings || []);
            if (result.input_plots) applyAnnualInputPlots(result.input_plots, cacheBust);
            if (result.ac_png) showImage('annualAcImg', 'annualAcIcon', 'annualAcChartBox', result.ac_png, cacheBust);
            if (result.energy_png) showImage('annualEnergyImg', 'annualEnergyIcon', 'annualEnergyChartBox', result.energy_png, cacheBust);
            if (result.monthly_png) showImage('annualMonthlyImg', 'annualMonthlyIcon', 'annualMonthlyChartBox', result.monthly_png, cacheBust);
            setAnnualExcelLink(result.excel, result.excel_filename);
        }

