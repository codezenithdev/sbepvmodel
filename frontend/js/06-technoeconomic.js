        function readAnnualizedCost(input, errorElement) {
            const raw = input.value.trim();
            const parsed = finiteOrNull(raw);
            const invalid = raw !== '' && (parsed === null || parsed < 0);
            input.setAttribute('aria-invalid', String(invalid));
            errorElement.textContent = invalid
                ? 'Enter an annualized cost of zero or greater in USD per year.'
                : '';
            return {
                value: invalid ? null : parsed,
                missing: raw === '',
                invalid,
            };
        }

        function calculateTechnoeconomicMetrics(
            baselineCost,
            optimizedCost,
            baselineEnergyKwh,
            optimizedEnergyKwh
        ) {
            const hasBaselineCost = Number.isFinite(baselineCost) && baselineCost >= 0;
            const hasOptimizedCost = Number.isFinite(optimizedCost) && optimizedCost >= 0;
            const hasBaselineEnergy = Number.isFinite(baselineEnergyKwh);
            const hasOptimizedEnergy = Number.isFinite(optimizedEnergyKwh);
            const annualEnergyIncreaseKwh = hasBaselineEnergy && hasOptimizedEnergy
                ? optimizedEnergyKwh - baselineEnergyKwh
                : null;
            const marginalAnnualizedCost = hasBaselineCost && hasOptimizedCost
                ? optimizedCost - baselineCost
                : null;
            return {
                annualEnergyIncreaseKwh,
                marginalAnnualizedCost,
                lcoe: hasBaselineCost && baselineEnergyKwh > 0
                    ? baselineCost / baselineEnergyKwh
                    : null,
                lcoo: marginalAnnualizedCost !== null && annualEnergyIncreaseKwh > 0
                    ? marginalAnnualizedCost / annualEnergyIncreaseKwh
                    : null,
            };
        }

        function getTechnoeconomicChatContext() {
            const baselineCostValue = finiteOrNull(baselineAnnualizedCost.value);
            const optimizedCostValue = finiteOrNull(optimizedAnnualizedCost.value);
            const baselineCost = baselineCostValue !== null && baselineCostValue >= 0
                ? baselineCostValue
                : null;
            const optimizedCost = optimizedCostValue !== null && optimizedCostValue >= 0
                ? optimizedCostValue
                : null;
            const stats = annualLatestResult?.stats || {};
            const baselineEnergy = finiteOrNull(stats.sol_predicted_kwh);
            const optimizedEnergy = finiteOrNull(stats.se_predicted_kwh);
            const fullYear = technoeconomicIsFullYear(annualLatestResult);
            const metrics = calculateTechnoeconomicMetrics(
                baselineCost,
                optimizedCost,
                baselineEnergy,
                optimizedEnergy
            );
            return {
                baseline_system: 'Solectria',
                optimized_system: 'SolarEdge',
                baseline_annualized_cost_usd_per_year: baselineCost,
                optimized_annualized_cost_usd_per_year: optimizedCost,
                baseline_annual_energy_kwh: fullYear ? baselineEnergy : null,
                optimized_annual_energy_kwh: fullYear ? optimizedEnergy : null,
                annual_energy_increase_kwh: fullYear ? metrics.annualEnergyIncreaseKwh : null,
                marginal_annualized_cost_usd_per_year: metrics.marginalAnnualizedCost,
                lcoe_usd_per_kwh: fullYear ? metrics.lcoe : null,
                lcoo_usd_per_kwh: fullYear ? metrics.lcoo : null,
                annual_period_from: annualLatestResult?.window?.from || null,
                annual_period_to: annualLatestResult?.window?.to || null,
                annual_period_is_full_year: fullYear,
            };
        }

        function technoeconomicSimulationDayCount(result) {
            const from = result?.window?.from;
            const to = result?.window?.to;
            if (!from || !to) return null;
            const start = Date.parse(String(from) + 'T00:00:00Z');
            const end = Date.parse(String(to) + 'T00:00:00Z');
            if (!Number.isFinite(start) || !Number.isFinite(end) || end < start) return null;
            const days = Math.round((end - start) / 86400000) + 1;
            return days > 0 ? days : null;
        }

        function technoeconomicIsFullYear(result) {
            const annualRows = result?.annual_energy_by_year || result?.stats?.annual_energy_by_year;
            if (!Array.isArray(annualRows) || annualRows.length !== 1 ||
                !annualRows[0] || typeof annualRows[0] !== 'object') return false;
            const annualRow = annualRows[0];
            return annualRow.complete_calendar_year === true &&
                annualRow.source_complete === true &&
                annualRow.cdf_eligible === true;
        }

        function technoeconomicSourceCoverageIssue(result) {
            const annualRows = result?.annual_energy_by_year || result?.stats?.annual_energy_by_year;
            if (!Array.isArray(annualRows) || annualRows.length !== 1 ||
                !annualRows[0] || typeof annualRows[0] !== 'object') return null;
            const annualRow = annualRows[0];
            if (annualRow.complete_calendar_year !== true) return null;
            if (!Object.prototype.hasOwnProperty.call(annualRow, 'source_complete')) {
                return {
                    title: 'Source coverage verification required',
                    detail: 'This saved result predates MIDC source-coverage tracking. Re-run it before using annualized cost metrics.',
                };
            }
            if (annualRow.source_complete === false) {
                const coverageValue = Number(annualRow.source_coverage_pct);
                const coverage = Number.isFinite(coverageValue)
                    ? coverageValue.toLocaleString(undefined, { maximumFractionDigits: 1 }) + '% source coverage. '
                    : '';
                return {
                    title: 'Incomplete MIDC source coverage',
                    detail: coverage + 'The calendar-year result remains visible, but annualized cost metrics require a complete-source year.',
                };
            }
            return null;
        }

        function formatTechnoeconomicEnergy(value) {
            return Number.isFinite(value)
                ? Number(value).toLocaleString(undefined, { minimumFractionDigits: 1, maximumFractionDigits: 1 })
                : '--';
        }

        function formatTechnoeconomicCost(value) {
            return Number.isFinite(value)
                ? new Intl.NumberFormat(undefined, {
                    style: 'currency',
                    currency: 'USD',
                    minimumFractionDigits: 0,
                    maximumFractionDigits: 2,
                }).format(value) + ' / year'
                : '--';
        }

        function formatLevelizedCost(value) {
            return Number.isFinite(value)
                ? new Intl.NumberFormat(undefined, {
                    style: 'currency',
                    currency: 'USD',
                    minimumFractionDigits: 4,
                    maximumFractionDigits: 4,
                }).format(value) + ' / kWh'
                : '--';
        }

        function setTechnoeconomicSourceState(state, title, detail) {
            technoeconomicElements.sourceCard.classList.remove('ready', 'running', 'warning');
            if (state) technoeconomicElements.sourceCard.classList.add(state);
            technoeconomicElements.sourceStatus.textContent = title;
            technoeconomicElements.sourceDetail.textContent = detail;
        }

        function renderTechnoeconomicAnalysis(result = annualLatestResult) {
            const stats = result?.stats || {};
            const baselineEnergy = finiteOrNull(stats.sol_predicted_kwh);
            const optimizedEnergy = finiteOrNull(stats.se_predicted_kwh);
            const baselineCostState = readAnnualizedCost(
                baselineAnnualizedCost,
                technoeconomicElements.baselineCostError
            );
            const optimizedCostState = readAnnualizedCost(
                optimizedAnnualizedCost,
                technoeconomicElements.optimizedCostError
            );
            const metrics = calculateTechnoeconomicMetrics(
                baselineCostState.value,
                optimizedCostState.value,
                baselineEnergy,
                optimizedEnergy
            );
            const dayCount = technoeconomicSimulationDayCount(result);
            const fullYear = technoeconomicIsFullYear(result);
            const range = result?.window?.from && result?.window?.to
                ? result.window.from + ' to ' + result.window.to
                : null;

            technoeconomicElements.baselineEnergy.textContent = '--';
            technoeconomicElements.optimizedEnergy.textContent = '--';
            technoeconomicElements.energyIncrease.textContent = '--';
            technoeconomicElements.baselineCost.textContent = formatTechnoeconomicCost(baselineCostState.value);
            technoeconomicElements.optimizedCost.textContent = formatTechnoeconomicCost(optimizedCostState.value);
            technoeconomicElements.marginalCost.textContent = formatTechnoeconomicCost(metrics.marginalAnnualizedCost);
            technoeconomicElements.lcoe.textContent = '--';
            technoeconomicElements.lcoo.textContent = '--';

            if (!result || baselineEnergy === null || optimizedEnergy === null) {
                const running = ['queued', 'running'].includes(annualRunState?.state);
                setTechnoeconomicSourceState(
                    running ? 'running' : '',
                    running ? 'Annual Simulation in progress' : 'Annual Simulation result required',
                    running
                        ? (annualRunState.stage || 'The levelized-cost outputs will update when the run completes.')
                        : 'Run an inclusive one-calendar-year Annual Simulation to supply annual energy production.'
                );
                technoeconomicElements.lcoeStatus.textContent = 'A completed full-year Annual Simulation result is required.';
                technoeconomicElements.lcooStatus.textContent = 'A completed full-year Annual Simulation result is required.';
                return;
            }

            if (!fullYear) {
                const sourceCoverageIssue = technoeconomicSourceCoverageIssue(result);
                const periodLabel = dayCount === null ? 'an unverified period' : dayCount + ' days';
                setTechnoeconomicSourceState(
                    'warning',
                    sourceCoverageIssue?.title || 'Full-year simulation required',
                    sourceCoverageIssue?.detail ||
                        ((range ? range + ' covers ' : 'The latest result covers ') + periodLabel +
                        '. Run an inclusive one-calendar-year window before combining production with annualized costs.')
                );
                const unavailableReason = sourceCoverageIssue
                    ? 'Unavailable because complete MIDC source coverage was not verified.'
                    : 'Unavailable because the latest production result is not a verified full year.';
                technoeconomicElements.lcoeStatus.textContent = unavailableReason;
                technoeconomicElements.lcooStatus.textContent = unavailableReason;
                return;
            }

            technoeconomicElements.baselineEnergy.textContent = formatTechnoeconomicEnergy(baselineEnergy);
            technoeconomicElements.optimizedEnergy.textContent = formatTechnoeconomicEnergy(optimizedEnergy);
            technoeconomicElements.energyIncrease.textContent = formatTechnoeconomicEnergy(metrics.annualEnergyIncreaseKwh);
            setTechnoeconomicSourceState(
                'ready',
                'Annual Simulation production connected',
                range + ' · ' + dayCount + ' days · baseline Solectria and optimized SolarEdge predictions'
            );

            if (baselineCostState.invalid) {
                technoeconomicElements.lcoeStatus.textContent = 'Baseline annualized cost must be zero or greater.';
            } else if (baselineCostState.missing) {
                technoeconomicElements.lcoeStatus.textContent = 'Enter the baseline Solectria annualized cost.';
            } else if (!(baselineEnergy > 0)) {
                technoeconomicElements.lcoeStatus.textContent = 'Unavailable because baseline annual energy is not positive.';
            } else {
                technoeconomicElements.lcoe.textContent = formatLevelizedCost(metrics.lcoe);
                technoeconomicElements.lcoeStatus.textContent = 'Baseline annualized cost divided by baseline Solectria annual energy.';
            }

            if (baselineCostState.invalid || optimizedCostState.invalid) {
                technoeconomicElements.lcooStatus.textContent = 'Both annualized costs must be zero or greater.';
            } else if (baselineCostState.missing || optimizedCostState.missing) {
                technoeconomicElements.lcooStatus.textContent = 'Enter both baseline and optimized annualized costs.';
            } else if (!(metrics.annualEnergyIncreaseKwh > 0)) {
                technoeconomicElements.lcooStatus.textContent = 'Unavailable because SolarEdge does not increase annual production over Solectria.';
            } else {
                technoeconomicElements.lcoo.textContent = formatLevelizedCost(metrics.lcoo);
                technoeconomicElements.lcooStatus.textContent = 'Marginal annualized cost divided by the annual energy increase.';
            }
        }

