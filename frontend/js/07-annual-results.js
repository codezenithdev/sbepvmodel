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

        function annualEnergyRows(result) {
            const rows = result?.annual_energy_by_year || result?.stats?.annual_energy_by_year;
            return Array.isArray(rows) ? rows.filter((row) => row && typeof row === 'object') : [];
        }

        function annualRowNumber(row, names) {
            for (const name of names) {
                const raw = row?.[name];
                if (raw === null || raw === undefined || raw === '') continue;
                const value = Number(raw);
                if (Number.isFinite(value)) return value;
            }
            return null;
        }

        function normalizedAnnualEnergyRow(row) {
            const complete = row.complete_calendar_year === true;
            const cdfEligibilityProvided = Object.prototype.hasOwnProperty.call(row, 'cdf_eligible');
            return {
                year: Number(row.year),
                periodStart: row.period_start || row.from_date || null,
                periodEnd: row.period_end || row.to_date || null,
                coverageStatus: String(row.coverage_status || row.coverage || (complete ? 'complete' : 'partial')),
                complete,
                cdfEligible: cdfEligibilityProvided ? row.cdf_eligible === true : complete,
                rowCount: annualRowNumber(row, ['row_count', 'interval_rows', 'coverage_rows']),
                solarEdge: annualRowNumber(row, ['se_predicted_kwh', 'solaredge_predicted_kwh', 'solar_edge_predicted_kwh']),
                solectria: annualRowNumber(row, ['sol_predicted_kwh', 'solectria_predicted_kwh']),
                combined: annualRowNumber(row, ['combined_predicted_kwh', 'total_predicted_kwh']),
            };
        }

        function formatAnnualEnergy(value) {
            return Number.isFinite(value)
                ? value.toLocaleString(undefined, { maximumFractionDigits: 1 }) + ' kWh'
                : 'Not available';
        }

        function formatAnnualResultDate(value) {
            if (!value) return 'Date unavailable';
            const parsed = new Date(String(value) + 'T00:00:00Z');
            if (!Number.isFinite(parsed.getTime())) return String(value);
            return new Intl.DateTimeFormat('en-US', {
                month: 'short',
                day: 'numeric',
                timeZone: 'UTC',
            }).format(parsed);
        }

        function annualCoverageCopy(row) {
            const dateRange = row.periodStart && row.periodEnd
                ? formatAnnualResultDate(row.periodStart) + ' - ' + formatAnnualResultDate(row.periodEnd)
                : 'Dates unavailable';
            if (row.complete && row.cdfEligible) return { label: 'Complete', detail: dateRange };
            if (row.coverageStatus === 'year_to_date') return { label: 'Year to date', detail: dateRange };
            if (row.coverageStatus === 'partial_start') return { label: 'Partial start', detail: dateRange };
            return { label: 'Partial', detail: dateRange };
        }

        function clearAnnualYearResults() {
            annualYearResultElements.panel.hidden = true;
            annualYearResultElements.rows.replaceChildren();
            annualYearResultElements.cdfChart.hidden = true;
            annualYearResultElements.cdfFallback.hidden = false;
            annualYearResultElements.cdfFallback.textContent = 'Run at least two complete calendar years to view a distribution.';
            Array.from(annualYearResultElements.cdfChart.children).forEach((child) => {
                if (!['title', 'desc'].includes(child.tagName.toLowerCase())) child.remove();
            });
            annualYearResultElements.cdfDescription.textContent = 'No complete-year distribution is available.';
        }

        function appendAnnualCdfSvgElement(name, attributes = {}, text = '') {
            const element = document.createElementNS('http://www.w3.org/2000/svg', name);
            Object.entries(attributes).forEach(([key, value]) => element.setAttribute(key, String(value)));
            if (text) element.textContent = text;
            annualYearResultElements.cdfChart.appendChild(element);
            return element;
        }

        function renderAnnualEnergyCdf(rows) {
            const eligible = rows.filter((row) => row.cdfEligible && row.complete);
            const chart = annualYearResultElements.cdfChart;
            const fallback = annualYearResultElements.cdfFallback;
            Array.from(chart.children).forEach((child) => {
                if (!['title', 'desc'].includes(child.tagName.toLowerCase())) child.remove();
            });
            if (eligible.length < 2) {
                chart.hidden = true;
                fallback.hidden = false;
                if (!eligible.length) {
                    fallback.textContent = 'No complete calendar years were returned. Partial years remain in the table and are excluded from the CDF.';
                    annualYearResultElements.cdfDescription.textContent = 'No complete calendar years are available for a distribution.';
                } else {
                    fallback.textContent = eligible[0].year + ' is the only complete calendar year. A distribution requires at least two complete years.';
                    annualYearResultElements.cdfDescription.textContent = 'Only one complete calendar year is available, so no distribution is drawn.';
                }
                return;
            }

            const series = [
                { name: 'SolarEdge', key: 'solarEdge', color: '#0f766e', dash: null, style: 'solid' },
                { name: 'Solectria', key: 'solectria', color: '#2563eb', dash: '10 6', style: 'dashed' },
                { name: 'Combined', key: 'combined', color: '#b45309', dash: '2 6', style: 'dotted' },
            ].map((item) => {
                const rankedValues = eligible
                    .filter((row) => Number.isFinite(row[item.key]))
                    .map((row) => ({ year: row.year, value: row[item.key] }))
                    .sort((left, right) => left.value - right.value);
                const values = [];
                rankedValues.forEach((point, index) => {
                    const probability = (index + 1) / rankedValues.length;
                    const last = values[values.length - 1];
                    if (last && last.value === point.value) {
                        last.years.push(point.year);
                        last.probability = probability;
                    } else {
                        values.push({ ...point, years: [point.year], probability });
                    }
                });
                return { ...item, values, sampleCount: rankedValues.length };
            }).filter((item) => item.sampleCount >= 2);
            const allValues = series.flatMap((item) => item.values.map((point) => point.value));
            if (!series.length || allValues.length < 2) {
                chart.hidden = true;
                fallback.hidden = false;
                fallback.textContent = 'Complete years were returned, but at least two numeric energy values are required to draw the CDF.';
                annualYearResultElements.cdfDescription.textContent = 'Complete-year energy values are insufficient for a distribution.';
                return;
            }

            const width = 720;
            const height = 360;
            const margin = { top: 18, right: 22, bottom: 54, left: 72 };
            const plotWidth = width - margin.left - margin.right;
            const plotHeight = height - margin.top - margin.bottom;
            let minimum = Math.min(...allValues);
            let maximum = Math.max(...allValues);
            if (minimum === maximum) {
                const padding = Math.max(1, Math.abs(minimum) * 0.05);
                minimum -= padding;
                maximum += padding;
            }
            const x = (value) => margin.left + ((value - minimum) / (maximum - minimum)) * plotWidth;
            const y = (probability) => margin.top + (1 - probability) * plotHeight;
            const compactNumber = new Intl.NumberFormat('en-US', { notation: 'compact', maximumFractionDigits: 1 });

            [0, 0.25, 0.5, 0.75, 1].forEach((probability) => {
                appendAnnualCdfSvgElement('line', {
                    x1: margin.left,
                    x2: margin.left + plotWidth,
                    y1: y(probability),
                    y2: y(probability),
                    stroke: '#dfe7e3',
                    'stroke-width': 1,
                });
                appendAnnualCdfSvgElement('text', {
                    x: margin.left - 12,
                    y: y(probability) + 4,
                    fill: '#61706a',
                    'font-size': 11,
                    'text-anchor': 'end',
                }, Math.round(probability * 100) + '%');
            });
            for (let index = 0; index <= 4; index += 1) {
                const value = minimum + ((maximum - minimum) * index / 4);
                appendAnnualCdfSvgElement('line', {
                    x1: x(value),
                    x2: x(value),
                    y1: margin.top,
                    y2: margin.top + plotHeight,
                    stroke: '#edf2ef',
                    'stroke-width': 1,
                });
                appendAnnualCdfSvgElement('text', {
                    x: x(value),
                    y: margin.top + plotHeight + 22,
                    fill: '#61706a',
                    'font-size': 11,
                    'text-anchor': 'middle',
                }, compactNumber.format(value));
            }
            appendAnnualCdfSvgElement('text', {
                x: margin.left + plotWidth / 2,
                y: height - 10,
                fill: '#3e4d47',
                'font-size': 12,
                'font-weight': 700,
                'text-anchor': 'middle',
            }, 'Predicted energy (kWh)');
            appendAnnualCdfSvgElement('text', {
                x: 18,
                y: margin.top + plotHeight / 2,
                fill: '#3e4d47',
                'font-size': 12,
                'font-weight': 700,
                'text-anchor': 'middle',
                transform: 'rotate(-90 18 ' + (margin.top + plotHeight / 2) + ')',
            }, 'Cumulative probability');

            series.forEach((item) => {
                let path = 'M ' + x(item.values[0].value) + ' ' + y(0);
                item.values.forEach((point) => {
                    path += ' H ' + x(point.value) + ' V ' + y(point.probability);
                });
                const pathAttributes = {
                    d: path,
                    fill: 'none',
                    stroke: item.color,
                    'stroke-width': 3,
                    'stroke-linejoin': 'round',
                    'stroke-linecap': item.style === 'dotted' ? 'round' : 'butt',
                };
                if (item.dash) pathAttributes['stroke-dasharray'] = item.dash;
                appendAnnualCdfSvgElement('path', pathAttributes);
            });
            const includedYears = eligible.map((row) => row.year).join(', ');
            const excludedYears = rows.filter((row) => !row.cdfEligible || !row.complete).map((row) => row.year);
            annualYearResultElements.cdfDescription.textContent =
                'Empirical cumulative distributions for SolarEdge (solid), Solectria (dashed), and combined (dotted) predicted energy across complete years ' + includedYears + '.' +
                (excludedYears.length ? ' Partial years excluded: ' + excludedYears.join(', ') + '.' : '');
            chart.hidden = false;
            fallback.hidden = true;
        }

        function renderAnnualYearResults(result) {
            const rows = annualEnergyRows(result)
                .map(normalizedAnnualEnergyRow)
                .filter((row) => Number.isInteger(row.year))
                .sort((left, right) => left.year - right.year);
            if (!rows.length) {
                clearAnnualYearResults();
                return;
            }
            annualYearResultElements.rows.replaceChildren();
            rows.forEach((row) => {
                const coverage = annualCoverageCopy(row);
                const tr = document.createElement('tr');
                tr.classList.toggle('partial', !row.complete || !row.cdfEligible);
                const yearCell = document.createElement('th');
                yearCell.scope = 'row';
                const yearWrap = document.createElement('span');
                yearWrap.className = 'annual-year-cell';
                const yearText = document.createElement('strong');
                yearText.textContent = String(row.year);
                yearWrap.appendChild(yearText);
                yearCell.appendChild(yearWrap);
                const coverageCell = document.createElement('td');
                const coverageWrap = document.createElement('span');
                coverageWrap.className = 'annual-coverage-label' + (row.complete && row.cdfEligible ? '' : ' partial');
                const coverageLabel = document.createElement('strong');
                coverageLabel.textContent = coverage.label;
                const coverageDetail = document.createElement('span');
                coverageDetail.textContent = coverage.detail;
                coverageWrap.append(coverageLabel, coverageDetail);
                coverageCell.appendChild(coverageWrap);
                const values = [row.solarEdge, row.solectria, row.combined, row.rowCount];
                const valueCells = values.map((value, index) => {
                    const cell = document.createElement('td');
                    cell.textContent = index === 3
                        ? (Number.isFinite(value) ? value.toLocaleString() : 'Not available')
                        : formatAnnualEnergy(value);
                    return cell;
                });
                tr.append(yearCell, coverageCell, ...valueCells);
                annualYearResultElements.rows.appendChild(tr);
            });
            const eligibleCount = rows.filter((row) => row.complete && row.cdfEligible).length;
            const partialCount = rows.length - eligibleCount;
            const cdfSummary = eligibleCount >= 2
                ? eligibleCount + ' complete years in the CDF'
                : (eligibleCount === 1
                    ? '1 CDF-eligible year; at least 2 required'
                    : 'no CDF-eligible complete years');
            annualYearResultElements.summary.textContent = rows.length + (rows.length === 1 ? ' selected year' : ' selected years') +
                ' - ' + cdfSummary +
                (partialCount ? '; ' + partialCount + (partialCount === 1 ? ' partial year excluded' : ' partial years excluded') : '');
            annualYearResultElements.panel.hidden = false;
            renderAnnualEnergyCdf(rows);
        }

        function applyAnnualResult(result, cacheBust = true) {
            renderTechnoeconomicAnalysis(result);
            renderAnnualResultCalibration(result);
            renderAnnualYearResults(result);
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

