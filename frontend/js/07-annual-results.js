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
                if (result) clearAnnualSeasonalFallbackDisplay();
                document.getElementById('annualStatSePhysicsCard').hidden = true;
                document.getElementById('annualStatSolPhysicsCard').hidden = true;
                elements.basis.textContent = 'Physics-only';
                elements.source.textContent = 'No calibration attached';
                elements.settings.textContent = 'Not applicable';
                elements.seasonal.textContent = 'Not applied';
                elements.factors.textContent = 'No seasonal calibration factors applied.';
                elements.settingDetails.textContent = 'No calibration settings were inherited.';
                elements.note.textContent = result ? 'Physics-only annual prediction' : 'Annual predictions appear after the model run';
                return;
            }
            const deltas = Array.isArray(application.settings_deltas) ? application.settings_deltas : [];
            const substitution = application.seasonal_substitution || null;
            const sourceSeason = String(substitution?.from_season || substitution?.source_season || '').toLowerCase();
            const targetSeason = String(substitution?.to_season || substitution?.target_season || '').toLowerCase();
            const fallbackUsed = sourceSeason === 'spring' && targetSeason === 'fall';
            if (fallbackUsed) {
                setAnnualSeasonalFallbackDisplay({
                    ...substitution,
                    factors: substitution?.factors || application.seasonal_factors?.fall,
                    baseline_job_id: application.baseline_job_id,
                    profile_sha256: application.origin_profile_sha256,
                    confirmation_context_sha256: application.server_confirmation?.confirmation_context_sha256,
                });
            } else {
                clearAnnualSeasonalFallbackDisplay();
            }
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
            const sourceCompletenessProvided = Object.prototype.hasOwnProperty.call(row, 'source_complete');
            const sourceComplete = sourceCompletenessProvided ? row.source_complete === true : null;
            return {
                year: Number(row.year),
                periodStart: row.period_start || row.from_date || null,
                periodEnd: row.period_end || row.to_date || null,
                coverageStatus: String(row.coverage_status || row.coverage || (complete ? 'complete' : 'partial')),
                complete,
                cdfEligible: sourceComplete === true &&
                    (cdfEligibilityProvided ? row.cdf_eligible === true : complete),
                sourceComplete,
                sourceCoveragePct: annualRowNumber(row, ['source_coverage_pct']),
                annualCoveragePct: annualRowNumber(row, ['annual_coverage_pct']),
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
            if (row.coverageStatus === 'incomplete_source' || (row.complete && row.sourceComplete === false)) {
                const coverage = Number.isFinite(row.sourceCoveragePct)
                    ? row.sourceCoveragePct.toLocaleString(undefined, { maximumFractionDigits: 1 }) + '% source coverage'
                    : 'Incomplete MIDC source coverage';
                return { label: 'Partial source', detail: coverage + ' - ' + dateRange };
            }
            if (row.complete && row.sourceComplete === null) {
                return {
                    label: 'Coverage unknown',
                    detail: 'Re-run to verify MIDC source coverage - ' + dateRange,
                };
            }
            if (row.coverageStatus === 'year_to_date') return { label: 'Year to date', detail: dateRange };
            if (row.coverageStatus === 'partial_start') return { label: 'Partial start', detail: dateRange };
            return { label: 'Partial', detail: dateRange };
        }

        const ANNUAL_DISTRIBUTION_MIN_PERCENTILE_YEARS = 5;
        const ANNUAL_DISTRIBUTION_MIN_EXCEEDANCE_YEARS = 10;
        const ANNUAL_DISTRIBUTION_SERIES = Object.freeze({
            combined: { label: 'Combined', color: '#b45309' },
            solarEdge: { label: 'SolarEdge', color: '#0f766e' },
            solectria: { label: 'Solectria', color: '#2563eb' },
        });
        let annualDistributionRows = [];
        let annualDistributionSeriesKey = 'combined';
        let annualDistributionView = 'ranked';

        function annualEnergyQuantile(values, probability) {
            const ordered = values.filter(Number.isFinite).slice().sort((left, right) => left - right);
            if (!ordered.length || !Number.isFinite(probability)) return null;
            const boundedProbability = Math.min(1, Math.max(0, probability));
            const position = (ordered.length - 1) * boundedProbability;
            const lowerIndex = Math.floor(position);
            const upperIndex = Math.ceil(position);
            if (lowerIndex === upperIndex) return ordered[lowerIndex];
            const fraction = position - lowerIndex;
            return ordered[lowerIndex] + (ordered[upperIndex] - ordered[lowerIndex]) * fraction;
        }

        function annualDistributionPoints(rows, seriesKey) {
            if (!Object.prototype.hasOwnProperty.call(ANNUAL_DISTRIBUTION_SERIES, seriesKey)) return [];
            return rows
                .filter((row) => row.complete && row.cdfEligible && Number.isFinite(row[seriesKey]))
                .map((row) => ({ year: row.year, value: row[seriesKey] }))
                .sort((left, right) => left.value - right.value || left.year - right.year);
        }

        function annualDistributionPolicy(sampleCount) {
            return {
                showPercentiles: sampleCount >= ANNUAL_DISTRIBUTION_MIN_PERCENTILE_YEARS,
                p90Provisional: sampleCount >= ANNUAL_DISTRIBUTION_MIN_PERCENTILE_YEARS &&
                    sampleCount < ANNUAL_DISTRIBUTION_MIN_EXCEEDANCE_YEARS,
                showP90Reference: sampleCount >= ANNUAL_DISTRIBUTION_MIN_EXCEEDANCE_YEARS,
                allowExceedance: sampleCount >= ANNUAL_DISTRIBUTION_MIN_EXCEEDANCE_YEARS,
            };
        }

        function annualDistributionSummary(points) {
            const values = points.map((point) => point.value);
            const policy = annualDistributionPolicy(values.length);
            return {
                sampleCount: values.length,
                minimum: values.length ? Math.min(...values) : null,
                maximum: values.length ? Math.max(...values) : null,
                p90: policy.showPercentiles ? annualEnergyQuantile(values, 0.10) : null,
                p50: policy.showPercentiles ? annualEnergyQuantile(values, 0.50) : null,
                ...policy,
            };
        }

        function annualDistributionDomain(values) {
            let minimum = Math.min(...values);
            let maximum = Math.max(...values);
            const padding = minimum === maximum
                ? Math.max(1, Math.abs(minimum) * 0.04)
                : (maximum - minimum) * 0.08;
            minimum = Math.max(0, minimum - padding);
            maximum += padding;
            if (minimum === maximum) maximum = minimum + 1;
            return [minimum, maximum];
        }

        function annualExceedancePoints(points) {
            const result = [];
            points.forEach((point, index) => {
                const last = result[result.length - 1];
                if (last && last.value === point.value) {
                    last.years.push(point.year);
                } else {
                    result.push({
                        value: point.value,
                        years: [point.year],
                        probability: (points.length - index) / points.length,
                    });
                }
            });
            return result;
        }

        function annualExceedanceStepPath(exceedancePoints, domain, x, y) {
            if (!exceedancePoints.length) return '';
            let path = 'M ' + x(domain[0]) + ' ' + y(1);
            exceedancePoints.forEach((point, index) => {
                const nextProbability = index + 1 < exceedancePoints.length
                    ? exceedancePoints[index + 1].probability
                    : 0;
                path += ' H ' + x(point.value) + ' V ' + y(nextProbability);
            });
            return path + ' H ' + x(domain[1]);
        }

        function formatAnnualDistributionMwh(value, maximumFractionDigits = 1) {
            if (!Number.isFinite(value)) return '--';
            return (value / 1000).toLocaleString(undefined, {
                minimumFractionDigits: 1,
                maximumFractionDigits,
            }) + ' MWh';
        }

        function annualDistributionTickDigits(domain) {
            const stepMwh = Math.abs(domain[1] - domain[0]) / 4000;
            if (!Number.isFinite(stepMwh) || stepMwh <= 0) return 1;
            return Math.min(4, Math.max(0, Math.ceil(-Math.log10(stepMwh)) + 1));
        }

        function formatAnnualDistributionTick(value, fractionDigits) {
            return (value / 1000).toLocaleString(undefined, { maximumFractionDigits: fractionDigits });
        }

        function clearAnnualDistributionChart() {
            const chart = annualYearResultElements.distributionChart;
            Array.from(chart.children).forEach((child) => {
                if (!['title', 'desc'].includes(child.tagName.toLowerCase())) child.remove();
            });
        }

        function appendAnnualDistributionSvgElement(name, attributes = {}, text = '', parent = null) {
            const element = document.createElementNS('http://www.w3.org/2000/svg', name);
            Object.entries(attributes).forEach(([key, value]) => element.setAttribute(key, String(value)));
            if (text) element.textContent = text;
            (parent || annualYearResultElements.distributionChart).appendChild(element);
            return element;
        }

        function renderAnnualDistributionKpis(summary) {
            const elements = annualYearResultElements;
            elements.distributionSampleValue.textContent = summary.sampleCount.toLocaleString();
            elements.distributionSampleMeta.textContent = summary.sampleCount === 1
                ? 'Complete MIDC weather year'
                : 'Complete MIDC weather years';
            if (summary.showPercentiles) {
                elements.distributionP90Value.textContent = formatAnnualDistributionMwh(summary.p90);
                elements.distributionP90Meta.textContent = summary.p90Provisional
                    ? 'Provisional - 10th percentile'
                    : '10th percentile - PERCENTILE.INC';
                elements.distributionP50Value.textContent = formatAnnualDistributionMwh(summary.p50);
                elements.distributionP50Meta.textContent = 'Median - PERCENTILE.INC';
            } else {
                elements.distributionP90Value.textContent = 'Not reported';
                elements.distributionP90Meta.textContent = 'Requires at least 5 years';
                elements.distributionP50Value.textContent = 'Not reported';
                elements.distributionP50Meta.textContent = 'Requires at least 5 years';
            }
            if (!summary.sampleCount) {
                elements.distributionRangeValue.textContent = '--';
            } else if (summary.minimum === summary.maximum) {
                elements.distributionRangeValue.textContent = formatAnnualDistributionMwh(summary.minimum);
            } else {
                elements.distributionRangeValue.textContent = formatAnnualDistributionMwh(summary.minimum) +
                    ' to ' + formatAnnualDistributionMwh(summary.maximum);
            }
            elements.distributionRangeMeta.textContent = 'Complete, source-verified years';
        }

        function setAnnualDistributionViewControls(summary) {
            const elements = annualYearResultElements;
            const hasAnySeries = Object.keys(ANNUAL_DISTRIBUTION_SERIES).some(
                (key) => annualDistributionPoints(annualDistributionRows, key).length > 0
            );
            elements.distributionSeries.disabled = !hasAnySeries;
            Array.from(elements.distributionSeries.options).forEach((option) => {
                option.disabled = annualDistributionPoints(annualDistributionRows, option.value).length === 0;
            });
            elements.distributionRankedButton.disabled = summary.sampleCount === 0;
            elements.distributionExceedanceButton.disabled = !summary.allowExceedance;
            elements.distributionExceedanceButton.title = summary.allowExceedance
                ? 'Show the empirical probability that annual energy is met or exceeded.'
                : 'Requires at least 10 complete numeric weather years for the selected system.';
            if (!summary.allowExceedance && annualDistributionView === 'exceedance') {
                annualDistributionView = 'ranked';
            }
            const ranked = annualDistributionView === 'ranked';
            elements.distributionRankedButton.setAttribute('aria-pressed', String(ranked));
            elements.distributionExceedanceButton.setAttribute('aria-pressed', String(!ranked));
            elements.distributionRankedButton.classList.toggle('active', ranked);
            elements.distributionExceedanceButton.classList.toggle('active', !ranked);
            if (!summary.sampleCount) {
                elements.distributionViewNote.textContent = 'No numeric complete-year energy values are available for this system.';
            } else if (summary.sampleCount < ANNUAL_DISTRIBUTION_MIN_PERCENTILE_YEARS) {
                elements.distributionViewNote.textContent = 'Every eligible year is shown. P50 and P90 require at least 5 complete years.';
            } else if (!summary.allowExceedance) {
                elements.distributionViewNote.textContent = 'P90 is provisional. Exceedance view requires 10 complete years (N = ' + summary.sampleCount + ').';
            } else if (ranked) {
                elements.distributionViewNote.textContent = 'Lowest-production weather year appears first. Exceedance view is available.';
            } else {
                elements.distributionViewNote.textContent = 'Empirical steps and points are shown without smoothing.';
            }
        }

        function appendAnnualDistributionXAxis({ domain, x, plotTop, plotBottom, width, height }) {
            const tickFractionDigits = annualDistributionTickDigits(domain);
            for (let index = 0; index <= 4; index += 1) {
                const value = domain[0] + ((domain[1] - domain[0]) * index / 4);
                appendAnnualDistributionSvgElement('line', {
                    x1: x(value),
                    x2: x(value),
                    y1: plotTop,
                    y2: plotBottom,
                    class: 'annual-distribution-grid-line',
                });
                appendAnnualDistributionSvgElement('text', {
                    x: x(value),
                    y: plotBottom + 24,
                    class: 'annual-distribution-axis-label',
                    'text-anchor': 'middle',
                }, formatAnnualDistributionTick(value, tickFractionDigits));
            }
            appendAnnualDistributionSvgElement('line', {
                x1: x(domain[0]),
                x2: x(domain[1]),
                y1: plotBottom,
                y2: plotBottom,
                class: 'annual-distribution-axis-line',
            });
            appendAnnualDistributionSvgElement('text', {
                x: width / 2,
                y: height - 9,
                class: 'annual-distribution-axis-title',
                'text-anchor': 'middle',
            }, 'Predicted annual energy (MWh)');
        }

        function appendAnnualDistributionReference(value, label, x, plotTop, plotBottom, variant, labelY) {
            if (!Number.isFinite(value)) return;
            appendAnnualDistributionSvgElement('line', {
                x1: x(value),
                x2: x(value),
                y1: plotTop,
                y2: plotBottom,
                class: 'annual-distribution-reference ' + variant,
            });
            appendAnnualDistributionSvgElement('text', {
                x: x(value),
                y: labelY,
                class: 'annual-distribution-reference-label ' + variant,
                'text-anchor': x(value) > 570 ? 'end' : 'start',
                dx: x(value) > 570 ? -5 : 5,
            }, label + ' ' + formatAnnualDistributionMwh(value));
        }

        function renderAnnualRankedEnergyChart(points, summary, series) {
            const width = 720;
            const margin = { top: 50, right: 108, bottom: 52, left: 68 };
            const rowHeight = 29;
            const plotTop = margin.top;
            const plotHeight = Math.max(72, (points.length - 1) * rowHeight);
            const plotBottom = plotTop + plotHeight;
            const height = plotBottom + margin.bottom;
            const plotWidth = width - margin.left - margin.right;
            const domain = annualDistributionDomain(points.map((point) => point.value));
            const x = (value) => margin.left + ((value - domain[0]) / (domain[1] - domain[0])) * plotWidth;
            const chart = annualYearResultElements.distributionChart;
            chart.setAttribute('viewBox', '0 0 ' + width + ' ' + height);
            appendAnnualDistributionXAxis({ domain, x, plotTop, plotBottom, width, height });
            if (summary.showPercentiles) {
                appendAnnualDistributionReference(summary.p50, 'P50', x, plotTop - 8, plotBottom, 'p50', 32);
            }
            if (summary.showP90Reference) {
                appendAnnualDistributionReference(summary.p90, 'P90', x, plotTop - 8, plotBottom, 'p90', 15);
            }
            points.forEach((point, index) => {
                const rowY = points.length === 1
                    ? plotTop + plotHeight / 2
                    : plotTop + index * (plotHeight / (points.length - 1));
                appendAnnualDistributionSvgElement('line', {
                    x1: margin.left,
                    x2: margin.left + plotWidth,
                    y1: rowY,
                    y2: rowY,
                    class: 'annual-distribution-row-guide',
                });
                appendAnnualDistributionSvgElement('text', {
                    x: margin.left - 12,
                    y: rowY + 4,
                    class: 'annual-distribution-year-label',
                    'text-anchor': 'end',
                }, String(point.year));
                const pointGroup = appendAnnualDistributionSvgElement('g', {
                    class: 'annual-distribution-point',
                    tabindex: 0,
                    role: 'img',
                    'aria-label': point.year + ': ' + formatAnnualDistributionMwh(point.value) +
                        ', rank ' + (index + 1) + ' of ' + points.length + ' from lowest production',
                });
                appendAnnualDistributionSvgElement('title', {}, point.year + ': ' + formatAnnualDistributionMwh(point.value), pointGroup);
                appendAnnualDistributionSvgElement('circle', {
                    cx: x(point.value),
                    cy: rowY,
                    r: 6,
                    fill: series.color,
                    class: 'annual-distribution-dot',
                }, '', pointGroup);
                const nearRightEdge = x(point.value) > margin.left + plotWidth * 0.78;
                appendAnnualDistributionSvgElement('text', {
                    x: x(point.value) + (nearRightEdge ? -10 : 10),
                    y: rowY + 4,
                    class: 'annual-distribution-value-label',
                    'text-anchor': nearRightEdge ? 'end' : 'start',
                }, formatAnnualDistributionMwh(point.value));
            });
        }

        function renderAnnualExceedanceChart(points, summary, series) {
            const width = 720;
            const height = 360;
            const margin = { top: 28, right: 40, bottom: 58, left: 82 };
            const plotWidth = width - margin.left - margin.right;
            const plotHeight = height - margin.top - margin.bottom;
            const plotBottom = margin.top + plotHeight;
            const domain = annualDistributionDomain(points.map((point) => point.value));
            const x = (value) => margin.left + ((value - domain[0]) / (domain[1] - domain[0])) * plotWidth;
            const y = (probability) => margin.top + (1 - probability) * plotHeight;
            const chart = annualYearResultElements.distributionChart;
            chart.setAttribute('viewBox', '0 0 ' + width + ' ' + height);
            appendAnnualDistributionXAxis({ domain, x, plotTop: margin.top, plotBottom, width, height });
            [0, 0.25, 0.5, 0.75, 1].forEach((probability) => {
                appendAnnualDistributionSvgElement('line', {
                    x1: margin.left,
                    x2: margin.left + plotWidth,
                    y1: y(probability),
                    y2: y(probability),
                    class: 'annual-distribution-grid-line',
                });
                appendAnnualDistributionSvgElement('text', {
                    x: margin.left - 12,
                    y: y(probability) + 4,
                    class: 'annual-distribution-axis-label',
                    'text-anchor': 'end',
                }, Math.round(probability * 100) + '%');
            });
            appendAnnualDistributionSvgElement('text', {
                x: 18,
                y: margin.top + plotHeight / 2,
                class: 'annual-distribution-axis-title',
                'text-anchor': 'middle',
                transform: 'rotate(-90 18 ' + (margin.top + plotHeight / 2) + ')',
            }, 'Probability energy is met or exceeded');
            appendAnnualDistributionReference(summary.p90, 'P90', x, margin.top, plotBottom, 'p90', 15);
            appendAnnualDistributionReference(summary.p50, 'P50', x, margin.top, plotBottom, 'p50', 32);
            const exceedancePoints = annualExceedancePoints(points);
            appendAnnualDistributionSvgElement('path', {
                d: annualExceedanceStepPath(exceedancePoints, domain, x, y),
                fill: 'none',
                stroke: series.color,
                'stroke-width': 3,
                'stroke-linejoin': 'round',
                class: 'annual-distribution-step',
            });
            exceedancePoints.forEach((point) => {
                const pointGroup = appendAnnualDistributionSvgElement('g', {
                    class: 'annual-distribution-point',
                    tabindex: 0,
                    role: 'img',
                    'aria-label': point.years.join(', ') + ': ' + formatAnnualDistributionMwh(point.value) +
                        ', ' + Math.round(point.probability * 100) + '% empirical probability of exceedance',
                });
                appendAnnualDistributionSvgElement('title', {}, point.years.join(', ') + ': ' +
                    formatAnnualDistributionMwh(point.value) + ' at ' +
                    Math.round(point.probability * 100) + '% exceedance', pointGroup);
                appendAnnualDistributionSvgElement('circle', {
                    cx: x(point.value),
                    cy: y(point.probability),
                    r: 5,
                    fill: '#ffffff',
                    stroke: series.color,
                    'stroke-width': 3,
                    class: 'annual-distribution-dot',
                }, '', pointGroup);
            });
        }

        function renderAnnualEnergyDistribution(rows = annualDistributionRows) {
            annualDistributionRows = Array.isArray(rows) ? rows : [];
            const elements = annualYearResultElements;
            clearAnnualDistributionChart();
            let points = annualDistributionPoints(annualDistributionRows, annualDistributionSeriesKey);
            if (!points.length) {
                const fallbackSeriesKey = Object.keys(ANNUAL_DISTRIBUTION_SERIES).find(
                    (key) => annualDistributionPoints(annualDistributionRows, key).length > 0
                );
                if (fallbackSeriesKey) {
                    annualDistributionSeriesKey = fallbackSeriesKey;
                    elements.distributionSeries.value = fallbackSeriesKey;
                    points = annualDistributionPoints(annualDistributionRows, annualDistributionSeriesKey);
                }
            }
            const summary = annualDistributionSummary(points);
            const series = ANNUAL_DISTRIBUTION_SERIES[annualDistributionSeriesKey];
            renderAnnualDistributionKpis(summary);
            setAnnualDistributionViewControls(summary);
            if (!summary.sampleCount) {
                elements.distributionChart.toggleAttribute('hidden', true);
                elements.distributionChartWrap.hidden = true;
                elements.distributionFallback.hidden = false;
                elements.distributionSubtitle.textContent = 'Complete, source-verified calendar years only';
                elements.distributionFallback.textContent = 'No complete, source-verified calendar year has a numeric ' +
                    series.label + ' energy result. Partial years remain available in the table.';
                elements.distributionTitle.textContent = series.label + ' annual predicted energy across weather years';
                elements.distributionDescription.textContent = 'No complete-year ' + series.label + ' energy observations are available.';
                return;
            }
            elements.distributionFallback.hidden = true;
            elements.distributionChartWrap.hidden = false;
            elements.distributionChart.toggleAttribute('hidden', false);
            elements.distributionTitle.textContent = series.label + ' annual predicted energy across weather years';
            elements.distributionSubtitle.textContent = annualDistributionView === 'exceedance'
                ? 'Empirical exceedance across ' + summary.sampleCount + ' complete weather years'
                : 'Ranked complete weather years - focused MWh scale';
            if (annualDistributionView === 'exceedance' && summary.allowExceedance) {
                renderAnnualExceedanceChart(points, summary, series);
            } else {
                renderAnnualRankedEnergyChart(points, summary, series);
            }
            const includedYears = points.map((point) => point.year).join(', ');
            const includedYearSet = new Set(points.map((point) => point.year));
            const excludedYears = annualDistributionRows
                .filter((row) => !includedYearSet.has(row.year))
                .map((row) => row.year);
            const percentileDescription = summary.showPercentiles
                ? ' P50 is ' + formatAnnualDistributionMwh(summary.p50) + '; P90 is ' +
                    formatAnnualDistributionMwh(summary.p90) + (summary.p90Provisional ? ' and is provisional.' : '.')
                : ' P50 and P90 are not reported because fewer than 5 years are available.';
            elements.distributionDescription.textContent =
                (annualDistributionView === 'exceedance' ? 'Empirical probability-of-exceedance' : 'Ranked dot plot') +
                ' for ' + series.label + ' predicted energy across ' + summary.sampleCount +
                ' complete MIDC weather years: ' + includedYears + '.' + percentileDescription +
                (excludedYears.length ? ' Excluded years: ' + excludedYears.join(', ') + '.' : '') +
                ' This describes weather-year variability only, not model or measurement uncertainty.';
        }

        function clearAnnualYearResults() {
            annualDistributionRows = [];
            annualDistributionSeriesKey = 'combined';
            annualDistributionView = 'ranked';
            annualYearResultElements.panel.hidden = true;
            annualYearResultElements.rows.replaceChildren();
            annualYearResultElements.distributionSeries.value = annualDistributionSeriesKey;
            annualYearResultElements.distributionSeries.disabled = true;
            annualYearResultElements.distributionRankedButton.disabled = true;
            annualYearResultElements.distributionExceedanceButton.disabled = true;
            annualYearResultElements.distributionChart.toggleAttribute('hidden', true);
            annualYearResultElements.distributionChartWrap.hidden = true;
            annualYearResultElements.distributionFallback.hidden = false;
            annualYearResultElements.distributionFallback.textContent = 'Run at least one complete calendar year to compare annual energy.';
            annualYearResultElements.distributionDescription.textContent = 'No complete-year energy observations are available.';
            clearAnnualDistributionChart();
            renderAnnualDistributionKpis(annualDistributionSummary([]));
            setAnnualDistributionViewControls(annualDistributionSummary([]));
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
            const excludedCount = rows.length - eligibleCount;
            annualYearResultElements.summary.textContent = rows.length + (rows.length === 1 ? ' selected year' : ' selected years') +
                ' - ' + (eligibleCount
                    ? eligibleCount + (eligibleCount === 1
                        ? ' source-verified complete year'
                        : ' source-verified complete years')
                    : 'no source-verified complete years') +
                (excludedCount ? '; ' + excludedCount + (excludedCount === 1
                    ? ' year excluded from the distribution'
                    : ' years excluded from the distribution') : '');
            annualYearResultElements.panel.hidden = false;
            annualDistributionRows = rows;
            annualDistributionSeriesKey = 'combined';
            annualDistributionView = 'ranked';
            annualYearResultElements.distributionSeries.value = annualDistributionSeriesKey;
            renderAnnualEnergyDistribution(rows);
        }

        annualYearResultElements.distributionSeries.addEventListener('change', () => {
            annualDistributionSeriesKey = annualYearResultElements.distributionSeries.value;
            renderAnnualEnergyDistribution();
        });
        annualYearResultElements.distributionRankedButton.addEventListener('click', () => {
            annualDistributionView = 'ranked';
            renderAnnualEnergyDistribution();
        });
        annualYearResultElements.distributionExceedanceButton.addEventListener('click', () => {
            const points = annualDistributionPoints(annualDistributionRows, annualDistributionSeriesKey);
            if (!annualDistributionPolicy(points.length).allowExceedance) return;
            annualDistributionView = 'exceedance';
            renderAnnualEnergyDistribution();
        });

        function applyAnnualResult(result, cacheBust = true) {
            void refreshTechnoeconomicSources();
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
            if (result.ac_png) showImage('annualAcImg', 'annualAcIcon', 'annualAcChartBox', result.ac_png, cacheBust);
            if (result.energy_png) showImage('annualEnergyImg', 'annualEnergyIcon', 'annualEnergyChartBox', result.energy_png, cacheBust);
            if (result.monthly_png) showImage('annualMonthlyImg', 'annualMonthlyIcon', 'annualMonthlyChartBox', result.monthly_png, cacheBust);
            setAnnualExcelLink(result.excel, result.excel_filename);
        }

