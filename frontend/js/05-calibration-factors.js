        function renderCalibrationFactors(result) {
            const stats = result?.stats || {};
            const calibration = stats.calibration_factors || result?.calibration_factors;
            const seasons = calibration?.seasons;
            if (!Array.isArray(seasons) || !seasons.length) {
                calibrationFactorPanel.classList.add('hidden');
                return;
            }

            calibrationFactorRows.replaceChildren();
            seasons.forEach((season) => {
                const solarEdge = season.systems?.solaredge || {};
                const solectria = season.systems?.solectria || {};
                const row = document.createElement('tr');
                const seasonCell = document.createElement('td');
                seasonCell.textContent = String(season.season || '').replace(/^./, (value) => value.toUpperCase());
                const coverage = document.createElement('td');
                appendFactorEvidence(coverage, 'SE', solarEdge);
                appendFactorEvidence(coverage, 'Sol', solectria);
                const seFactor = document.createElement('td');
                seFactor.className = 'calibration-factor-value';
                appendFactorValue(seFactor, solarEdge);
                const solFactor = document.createElement('td');
                solFactor.className = 'calibration-factor-value';
                appendFactorValue(solFactor, solectria);
                const confidence = document.createElement('td');
                confidence.textContent = 'SE ' + String(solarEdge.confidence || 'low') +
                    ' · Sol ' + String(solectria.confidence || 'low');
                row.append(seasonCell, coverage, seFactor, solFactor, confidence);
                calibrationFactorRows.appendChild(row);
            });

            const quality = result?.data_quality || stats.data_quality_review || {};
            const cleaning = quality.cleaning || {};
            const uncalibrated = stats.uncalibrated || {};
            calibrationAuditLine.textContent =
                'Rows: ' + Number(cleaning.excluded_rows || 0).toLocaleString() + ' excluded · ' +
                Number(cleaning.final_rows || stats.n_rows || 0).toLocaleString() + ' modeled · ' +
                'Before calibration: SolarEdge ' + fmtPct(uncalibrated.se_pct) +
                ', Solectria ' + fmtPct(uncalibrated.sol_pct) +
                ' (+ above measured, - below measured)';

            calibrationDriverInsights.replaceChildren();
            /*
             * Physical-driver diagnostic sentences are intentionally hidden
             * from the dashboard. The diagnostic calculations remain in the
             * result payload for future analysis.
            const diagnostics = stats.factor_driver_diagnostics || result?.factor_driver_diagnostics;
            Object.entries(diagnostics?.systems || {}).forEach(([system, diagnostic]) => {
                const line = document.createElement('p');
                const label = system === 'solaredge' ? 'SolarEdge' : 'Solectria';
                const topDriver = diagnostic?.drivers?.[0];
                line.textContent = topDriver
                    ? label + ' diagnostic: ' + String(topDriver.label) + ' has the strongest association with the residual factor (' +
                        String(topDriver.direction) + ', ' +
                        Number(topDriver.factor_change_pct_per_standard_deviation || 0).toFixed(1) + '% per observed standard deviation; R² ' +
                        Number(diagnostic.r_squared || 0).toFixed(2) + ').'
                    : label + ' driver diagnostic: ' + String(diagnostic?.message || 'insufficient data for a stable physical-driver model.');
                calibrationDriverInsights.appendChild(line);
            });
            const caveat = document.createElement('p');
            // caveat.textContent = 'Driver findings are diagnostic associations, not causal effects. Soiling needs a dedicated sensor, rainfall history, or cleaning records.';
            calibrationDriverInsights.appendChild(caveat);
            */
            calibrationFactorPanel.classList.remove('hidden');
        }

        function renderUncalibratedComparison(stats, calibrated) {
            const uncalibrated = stats?.uncalibrated;
            const available = calibrated && !!uncalibrated &&
                typeof uncalibrated === 'object' && !Array.isArray(uncalibrated);
            const solarEdgeComparison = document.getElementById('seUncalibratedComparison');
            const solectriaComparison = document.getElementById('solUncalibratedComparison');
            solarEdgeComparison.hidden = !available;
            solectriaComparison.hidden = !available;
            [solarEdgeComparison, solectriaComparison].forEach((comparison) => {
                comparison.closest('.validation-system-summary')?.classList.toggle('has-calibration-baseline', available);
            });

            const finiteNumber = (value) => {
                if (value === null || value === undefined || value === '') return null;
                const number = Number(value);
                return Number.isFinite(number) ? number : null;
            };
            const formatEnergy = (value) => {
                const number = finiteNumber(value);
                return number === null ? 'n/a' : number.toLocaleString();
            };
            const formatDelta = (value) => fmtPct(finiteNumber(value));

            document.getElementById('statSeUncalibratedPred').textContent =
                formatEnergy(available ? uncalibrated.se_predicted_kwh : null);
            document.getElementById('statSolUncalibratedPred').textContent =
                formatEnergy(available ? uncalibrated.sol_predicted_kwh : null);
            document.getElementById('statSeUncalibratedPct').textContent =
                formatDelta(available ? uncalibrated.se_pct : null);
            document.getElementById('statSolUncalibratedPct').textContent =
                formatDelta(available ? uncalibrated.sol_pct : null);
        }

        function formatValidationRunTimestamp(value, timezone) {
            if (!value) return 'n/a';
            const text = String(value).trim();
            const explicitTimestamp = /(?:Z|[+-]\d{2}:\d{2})$/i.test(text)
                ? text
                : text + 'Z';
            const date = new Date(explicitTimestamp);
            if (Number.isNaN(date.getTime())) return text.replace('T', ' ');
            let parts;
            try {
                parts = new Intl.DateTimeFormat('en-US', {
                    timeZone: timezone || 'America/Denver',
                    month: 'short',
                    day: 'numeric',
                    year: 'numeric',
                    hour: '2-digit',
                    minute: '2-digit',
                    hourCycle: 'h23',
                }).formatToParts(date);
            } catch (_) {
                parts = new Intl.DateTimeFormat('en-US', {
                    timeZone: 'America/Denver',
                    month: 'short',
                    day: 'numeric',
                    year: 'numeric',
                    hour: '2-digit',
                    minute: '2-digit',
                    hourCycle: 'h23',
                }).formatToParts(date);
            }
            const values = Object.fromEntries(
                parts.filter((part) => part.type !== 'literal')
                    .map((part) => [part.type, part.value])
            );
            const hour = values.hour === '24' ? '00' : values.hour;
            return values.month + ' ' + values.day + ', ' + values.year +
                ' ' + hour + ':' + values.minute;
        }

        function formatValidationRunEfficiency(value) {
            if (value === null || value === undefined || value === '') return 'n/a';
            const number = Number(value);
            return Number.isFinite(number) ? (number * 100).toFixed(1) + '%' : 'n/a';
        }

        function validationPreflightCopy(summary) {
            if (!summary || typeof summary !== 'object' || Array.isArray(summary)) return null;
            const finiteCount = (value) => {
                const number = Number(value);
                return Number.isFinite(number) && number >= 0 ? Math.round(number) : 0;
            };
            const inputRows = finiteCount(summary.input_row_count);
            const usableRows = finiteCount(summary.usable_row_count);
            const omittedRows = finiteCount(summary.omitted_row_count);
            const interpolatedCells = finiteCount(summary.wind_interpolated_count) +
                finiteCount(summary.temperature_interpolated_count);
            const clampedCells = finiteCount(summary.wind_clamped_count);
            const suppliedCoverage = Number(summary.coverage_pct);
            const coverage = Number.isFinite(suppliedCoverage)
                ? suppliedCoverage
                : (inputRows ? usableRows / inputRows * 100 : null);
            const coverageText = Number.isFinite(coverage)
                ? coverage.toLocaleString(undefined, { maximumFractionDigits: 1 }) + '% usable coverage'
                : 'Usable coverage unavailable';
            const changed = omittedRows + interpolatedCells + clampedCells;
            const details = [];
            if (inputRows) {
                details.push(usableRows.toLocaleString() + ' of ' + inputRows.toLocaleString() + ' intervals modeled');
            }
            if (omittedRows) details.push(omittedRows.toLocaleString() + ' omitted');
            if (interpolatedCells) details.push(interpolatedCells.toLocaleString() + ' weather cells interpolated');
            if (clampedCells) details.push(clampedCells.toLocaleString() + ' tiny negative wind values clamped to zero');
            if (!changed) details.push('no weather correction was required');
            return {
                ok: changed === 0,
                title: changed ? 'Validation completed with ' + coverageText : 'Validation weather preflight passed',
                detail: details.join('; ') + '. Measured and predicted totals use the same usable intervals.',
            };
        }

        function renderValidationPreflight(result) {
            const stats = result?.stats || {};
            const summary = result?.historian_preflight || stats.historian_preflight;
            const copy = validationPreflightCopy(summary);
            if (!copy) {
                const uncalibrated = result && (
                    result?.window?.calibrate_model === false ||
                    stats.calibration_enabled === false
                );
                if (!uncalibrated) {
                    validationPreflightPanel.hidden = true;
                    return;
                }
                validationPreflightPanel.classList.remove('ok');
                validationPreflightPanel.textContent =
                    'Weather preflight audit is unavailable for this older result. Re-run validation to verify usable coverage.';
                validationPreflightPanel.hidden = false;
                return;
            }
            validationPreflightPanel.classList.toggle('ok', copy.ok);
            const title = document.createElement('strong');
            title.textContent = copy.title + ': ';
            const detail = document.createElement('span');
            detail.textContent = copy.detail;
            validationPreflightPanel.replaceChildren(title, detail);
            validationPreflightPanel.hidden = false;
        }

        function renderValidationRunContext(result) {
            const windowData = result?.window;
            if (!windowData) {
                validationRunContextRange.textContent = '--';
                validationRunContextTimezone.textContent = '--';
                Object.values(validationRunContextEfficiencyValues).forEach((node) => {
                    node.textContent = '--';
                });
                validationRunContextRange.removeAttribute('title');
                validationRunContext.hidden = true;
                return;
            }

            const stats = result?.stats || {};
            const fromValue = windowData.from_local ?? windowData.from;
            const toValue = windowData.to_local ?? windowData.to;
            const timezone = windowData.timezone || 'America/Denver';
            const fromLabel = formatValidationRunTimestamp(fromValue, timezone);
            const toLabel = formatValidationRunTimestamp(toValue, timezone);
            validationRunContextRange.textContent = fromLabel + ' – ' + toLabel;
            validationRunContextRange.title = windowData.end_exclusive === false
                ? 'The ending boundary is included.'
                : 'The ending boundary is excluded.';
            validationRunContextTimezone.textContent = timezone;

            const efficiencyValues = {
                solaredge_inverter_efficiency: windowData.solaredge_inverter_efficiency ?? stats.solaredge_inverter_efficiency,
                solaredge_bos_efficiency: windowData.solaredge_bos_efficiency ?? stats.solaredge_bos_efficiency,
                solaredge_total_efficiency: windowData.solaredge_total_efficiency ?? stats.solaredge_total_efficiency,
                solectria_inverter_efficiency: windowData.solectria_inverter_efficiency ?? stats.solectria_inverter_efficiency,
                solectria_bos_efficiency: windowData.solectria_bos_efficiency ?? stats.solectria_bos_efficiency,
                solectria_total_efficiency: windowData.solectria_total_efficiency ?? stats.solectria_total_efficiency,
            };
            Object.entries(efficiencyValues).forEach(([field, value]) => {
                validationRunContextEfficiencyValues[field].textContent =
                    formatValidationRunEfficiency(value);
            });
            validationRunContext.hidden = false;
        }

        function applyResult(result, cacheBust = true) {
            renderValidationRunContext(result);
            renderValidationPreflight(result);
            if (!result || !result.stats) return;
            const s = result.stats;
            const calibrated = s.calibration_enabled === true || !!s.calibration_factors;
            syncValidationResultsMode(calibrated);
            const fmtNum = (v) => (v === null || v === undefined) ? 'n/a' : v.toLocaleString();
            const finiteNumber = (v) => {
                if (v === null || v === undefined || v === '') return null;
                const number = Number(v);
                return Number.isFinite(number) ? number : null;
            };
            const seMeasured = finiteNumber(s.se_measured_kwh);
            const solMeasured = finiteNumber(s.sol_measured_kwh);
            const measuredDifference = seMeasured === null || solMeasured === null
                ? null
                : seMeasured - solMeasured;
            const measuredDifferencePct = measuredDifference === null || !solMeasured
                ? null
                : measuredDifference / solMeasured * 100;
            document.getElementById('statSeMeasured').textContent = fmtNum(seMeasured);
            document.getElementById('statSolMeasured').textContent = fmtNum(solMeasured);
            document.getElementById('statMeasuredDiff').textContent = fmtNum(measuredDifference);
            document.getElementById('statMeasuredDiffPct').textContent = fmtPct(measuredDifferencePct);
            document.getElementById('statSePred').textContent = fmtNum(s.se_predicted_kwh);
            document.getElementById('statSolPred').textContent = fmtNum(s.sol_predicted_kwh);
            document.getElementById('statSePct').textContent = fmtPct(s.se_pct);
            document.getElementById('statSolPct').textContent = fmtPct(s.sol_pct);
            renderUncalibratedComparison(s, calibrated);
            renderCalibrationFactors(result);
            if (result.input_plots) applyInputPlots(result.input_plots, cacheBust);
            if (result.ac_png) showImage('acImg', 'acIcon', 'acChartBox', result.ac_png, cacheBust);
            if (result.energy_png) showImage('energyImg', 'energyIcon', 'energyChartBox', result.energy_png, cacheBust);
            renderUncalibratedPlots(result, calibrated, cacheBust);
            setExcelLink(result.excel, result.excel_filename);
        }

        function renderAnnualQuality(warnings) {
            const panel = document.getElementById('annualQualityPanel');
            const quality = document.getElementById('annualStatQuality');
            const items = Array.isArray(warnings) ? warnings.filter(Boolean) : [];
            panel.classList.toggle('ok', items.length === 0);
            quality.classList.toggle('positive', items.length === 0);
            quality.classList.toggle('warning', items.length > 0);
            quality.textContent = items.length ? items.length + ' warning' + (items.length === 1 ? '' : 's') : 'Complete';
            if (!items.length) {
                panel.textContent = 'Complete weather coverage; no fallback warnings were reported.';
                return;
            }
            panel.innerHTML = '<strong>Run completed with documented fallbacks:</strong><ul>' +
                items.map((item) => '<li>' + escapeHtml(String(item)) + '</li>').join('') + '</ul>';
        }

