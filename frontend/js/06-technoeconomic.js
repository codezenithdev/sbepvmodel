        // The browser collects evidence and provides clearly labeled setup estimates;
        // authoritative probabilistic calculations and artifact verification happen
        // on the server.
        const TECHNOECONOMIC_DRAFT_SCHEMA_VERSION = 'technoeconomic-draft-v3';
        const TECHNOECONOMIC_DRAFT_STORAGE_KEY = 'sbepv.technoeconomic.draft.v3';
        const TECHNOECONOMIC_PREVIOUS_DRAFT_SCHEMA_VERSION = 'technoeconomic-draft-v2';
        const TECHNOECONOMIC_PREVIOUS_DRAFT_STORAGE_KEY = 'sbepv.technoeconomic.draft.v2';
        const TECHNOECONOMIC_LEGACY_DRAFT_SCHEMA_VERSION = 'technoeconomic-draft-v1';
        const TECHNOECONOMIC_LEGACY_DRAFT_STORAGE_KEY = 'sbepv.technoeconomic.draft.v1';
        const TECHNOECONOMIC_APPLIED_CAPACITY_NORMALIZATION = 'annual_applied_capacity_v1';
        const TECHNOECONOMIC_ACTIVE_JOB_STORAGE_KEY = 'sbepv.technoeconomic.active-job.v1';
        const TECHNOECONOMIC_STANDALONE_CONTRACT_VERSION = 'tea-calculation-v4';
        const TECHNOECONOMIC_PAIRED_CONTRACT_VERSION = 'tea-calculation-v5';
        const TECHNOECONOMIC_LIFECYCLE_CONTRACT_VERSION = 'tea-calculation-v6';
        const TECHNOECONOMIC_SAMPLING_VERSION = 'tea-lhs-v1';
        const TECHNOECONOMIC_LIFECYCLE_SAMPLING_VERSION = 'tea-lhs-v2';
        const TECHNOECONOMIC_LIFECYCLE_WEATHER_METHOD =
            'paired-yearwise-balanced-across-realizations-independent-across-project-years-v1';
        const TECHNOECONOMIC_LIFECYCLE_TEMPLATE_REFERENCE =
            'tea-v6-provisional-template-v1';
        const TECHNOECONOMIC_LIFECYCLE_LCOE_CDF_CHART_CONTRACT =
            'lifecycle_system_lcoe_cdf_v2';
        const TECHNOECONOMIC_SOURCE_REFRESH_TIMEOUT_MS = 15000;
        const TECHNOECONOMIC_LIFECYCLE_TEMPLATE_DEFAULTS = Object.freeze({
            lifecycleSourceBasis: 'gross', lifecycleReliabilityMode: 'event',
            lifecycleElectricityValue: '0.07', lifecycleElectricityGrowth: '0',
            lifecycleNpvTolerance: '0.01',
            lifecycleSolectriaDegradation: '0.50',
            lifecycleSolarEdgeDegradation: '0.50',
            lifecycleSolectriaAvailability: '99.50',
            lifecycleSolarEdgeAvailability: '99.50',
            lifecycleSolectriaInitialCost: '1.56',
            lifecycleSolarEdgeInitialCost: '1.56',
            lifecycleSolectriaBaseOm: '22.00', lifecycleSolarEdgeBaseOm: '22.00',
            lifecycleSolectriaDecommissioning: '3000000',
            lifecycleSolarEdgeDecommissioning: '3000000',
            lifecycleSolectriaSalvage: '2000000', lifecycleSolarEdgeSalvage: '2000000',
            lifecycleCommonProbability: '2.00', lifecycleCommonDowntime: '48',
            lifecycleCommonImpact: '20', lifecycleCommonCost: '100000',
        });
        const TECHNOECONOMIC_PAIRED_SYSTEMS = Object.freeze([
            Object.freeze({key: 'solectria', label: 'Solectria'}),
            Object.freeze({key: 'solaredge', label: 'SolarEdge'}),
        ]);
        const TECHNOECONOMIC_PAIRED_METRICS = Object.freeze({
            solectria: Object.freeze({
                year1Energy: 'CommercialSolectriaYear1Energy_kWh_AC',
                initialCost: 'CommercialSolectriaInitialCost_USD',
                recurringCost: 'CommercialSolectriaRecurringLifecycleCost_USD',
                scheduledCost: 'CommercialSolectriaScheduledLifecycleCost_USD',
                lifecycleCost: 'CommercialSolectriaLifecycleCost_USD',
                lcoe: 'CommercialSolectriaLifecycleLCOE_USD_per_kWh_AC',
            }),
            solaredge: Object.freeze({
                year1Energy: 'CommercialSolarEdgeYear1Energy_kWh_AC',
                initialCost: 'CommercialSolarEdgeInitialCost_USD',
                recurringCost: 'CommercialSolarEdgeRecurringLifecycleCost_USD',
                scheduledCost: 'CommercialSolarEdgeScheduledLifecycleCost_USD',
                lifecycleCost: 'CommercialSolarEdgeLifecycleCost_USD',
                lcoe: 'CommercialSolarEdgeLifecycleLCOE_USD_per_kWh_AC',
            }),
        });
        const TECHNOECONOMIC_PAIRED_LCOE_DELTA_METRIC =
            'CommercialLifecycleLCOEDelta_se_minus_sol_USD_per_kWh_AC';
        const TECHNOECONOMIC_STANDALONE_LCOE_METRIC =
            TECHNOECONOMIC_PAIRED_METRICS.solaredge.lcoe;
        const TECHNOECONOMIC_STANDALONE_TARGET_MW = 100;
        const TECHNOECONOMIC_STANDALONE_ATB_URL =
            'https://data.openei.org/submissions/6006';
        const TECHNOECONOMIC_STANDALONE_PREVIOUS_DRAFT_STORAGE_KEY =
            'sbepv.technoeconomic.paired-draft.v2';
        const TECHNOECONOMIC_STANDALONE_LEGACY_DRAFT_STORAGE_KEY =
            'sbepv.technoeconomic.standalone-draft.v1';
        const TECHNOECONOMIC_STANDALONE_DRAFT_SCHEMA_VERSION =
            'technoeconomic-paired-draft-v3';
        const TECHNOECONOMIC_STANDALONE_DRAFT_STORAGE_KEY =
            'sbepv.technoeconomic.paired-draft.v3';
        const TECHNOECONOMIC_STANDALONE_ATB_PRESETS = Object.freeze({
            ac_operating_limit: Object.freeze({capex: '1.56', om: '22'}),
            dc_installed_nameplate: Object.freeze({capex: '1.17', om: '16.58'}),
        });
        const TECHNOECONOMIC_STANDALONE_COST_COVERAGE = Object.freeze(
            Object.fromEntries(TECHNOECONOMIC_PAIRED_SYSTEMS.map(({key}) => [key, Object.freeze({
                Capex: Object.freeze({
                    costCategory: 'full_initial_capex',
                    coverageIds: Object.freeze([`commercial.${key}.full-initial-system`]),
                }),
                Om: Object.freeze({
                    costCategory: 'full_annual_om',
                    coverageIds: Object.freeze([
                        `commercial.${key}.full-annual-operations-maintenance`,
                    ]),
                }),
                Replacement: Object.freeze({
                    costCategory: 'scheduled_replacement',
                    coverageIds: Object.freeze([`commercial.${key}.inverter-replacement`]),
                }),
            })]))
        );
        const TECHNOECONOMIC_MAX_SAFE_SEED = Number.MAX_SAFE_INTEGER;
        const TECHNOECONOMIC_MAX_REALIZATION_EXPORT_CELLS = 8000000;
        const TECHNOECONOMIC_MAX_SENSITIVITY_WORK_UNITS = 25000000;
        const TECHNOECONOMIC_GUIDED_ENTRY_MODE = 'guided_solartac';
        const TECHNOECONOMIC_ADVANCED_ENTRY_MODE = 'advanced';
        const TECHNOECONOMIC_GUIDED_COST_IDS = Object.freeze({
            solectria_capex: 'cost.guided.solectria-capex',
            solectria_om: 'cost.guided.solectria-recurring-om',
            solaredge_capex: 'cost.guided.solaredge-capex',
            solaredge_om: 'cost.guided.solaredge-recurring-om',
        });
        const TECHNOECONOMIC_RESERVED_INPUT_IDS = new Set([
            'finance.discount-rate', 'energy.shared-degradation', 'transfer.baseline',
            'transfer.incremental', 'commercial.marginal-cost-difference', 'weather.year',
        ]);
        const TECHNOECONOMIC_TERMINAL_STATES = new Set([
            'done', 'error', 'cancelled', 'interrupted',
        ]);
        const TECHNOECONOMIC_RETRYABLE_STATES = new Set([
            'error', 'cancelled', 'interrupted',
        ]);
        const TECHNOECONOMIC_EVIDENCE_CLASSES = [
            ['project_actual', 'Project actual'],
            ['direct_quote_or_primary_document', 'Direct quote or primary document'],
            ['public_market_proxy_or_benchmark', 'Public market proxy or benchmark'],
            ['engineering_judgment', 'Engineering judgment (provisional)'],
            ['secondary_synthesis', 'Secondary synthesis (provisional)'],
        ];
        const TECHNOECONOMIC_DISTRIBUTION_FAMILIES = [
            ['fixed', 'Fixed'], ['uniform', 'Uniform'],
            ['triangular', 'Triangular'], ['bounded_normal', 'Bounded normal'],
        ];
        const TECHNOECONOMIC_TRANSFER_MECHANISMS = [
            'climate_and_irradiance', 'module_string_optimizer_topology',
            'mismatch_mechanism', 'shading', 'row_and_tracker_geometry',
            'conversion_and_temperature', 'dc_ac_ratio_and_clipping',
            'availability_and_outages', 'curtailment', 'soiling',
            'weather_representativeness', 'degradation', 'size_independence',
        ];
        const TECHNOECONOMIC_COMMERCIAL_METRICS = Object.freeze([
            ['CommercialTargetCapacity_W', 'Commercial target capacity'],
            [
                'CommercialYear1DeltaEnergy_se_minus_sol_kWh_AC',
                'Year-one energy difference (SolarEdge minus Solectria)',
            ],
            [
                'CommercialLifecycleDeltaEnergy_se_minus_sol_kWh_AC',
                'Lifecycle energy difference (SolarEdge minus Solectria)',
            ],
            [
                'CommercialEquivalentAnnualDeltaEnergy_se_minus_sol_kWh_AC_per_year',
                'Equivalent annual energy difference (SolarEdge minus Solectria)',
            ],
            [
                'CommercialLifecycleMarginalCostDelta_se_minus_sol_USD',
                'Lifecycle marginal cost difference (SolarEdge minus Solectria)',
            ],
            [
                'CommercialEquivalentAnnualMarginalCostDelta_se_minus_sol_USD_per_year',
                'Equivalent annual marginal cost difference (SolarEdge minus Solectria)',
            ],
            [
                'CommercialMarginalLCOO_se_minus_sol_USD_per_kWh_AC',
                'Commercial marginal LCOO (SolarEdge minus Solectria)',
            ],
        ]);
        const TECHNOECONOMIC_COMMERCIAL_METRIC_ALIASES = Object.freeze({
            CommercialLifecycleMarginalCostDelta_se_minus_sol_USD: [
                'CommercialLifecycleDeltaCost_se_minus_sol_USD',
            ],
            CommercialEquivalentAnnualMarginalCostDelta_se_minus_sol_USD_per_year: [
                'CommercialEquivalentAnnualDeltaCost_se_minus_sol_USD_per_year',
            ],
        });
        const TECHNOECONOMIC_METRIC_LABELS = {
            LifecycleLCOE_SOL_USD_per_kWh_AC: 'Solectria lifecycle LCOE',
            LifecycleLCOE_SE_USD_per_kWh_AC: 'SolarEdge lifecycle LCOE',
            DeltaLifecycleCostPerWdc_se_minus_sol_USD_per_Wdc: 'Lifecycle cost delta (SolarEdge minus Solectria)',
            DeltaLifecycleEnergyPerWdc_se_minus_sol_kWh_AC_per_Wdc: 'Lifecycle energy delta (SolarEdge minus Solectria)',
            DeltaEquivalentAnnualCostPerWdcYear_se_minus_sol_USD_per_Wdc_year: 'Equivalent annual cost delta (SolarEdge minus Solectria)',
            DeltaEquivalentAnnualEnergyPerWdcYear_se_minus_sol_kWh_AC_per_Wdc_year: 'Equivalent annual energy delta (SolarEdge minus Solectria)',
            DeltaLifecycleCostPerAppliedW_se_minus_sol_USD_per_applied_W: 'Lifecycle cost delta (SolarEdge minus Solectria)',
            DeltaLifecycleEnergyPerAppliedW_se_minus_sol_kWh_AC_per_applied_W: 'Lifecycle energy delta (SolarEdge minus Solectria)',
            DeltaEquivalentAnnualCostPerAppliedWYear_se_minus_sol_USD_per_applied_W_year: 'Equivalent annual cost delta (SolarEdge minus Solectria)',
            DeltaEquivalentAnnualEnergyPerAppliedWYear_se_minus_sol_kWh_AC_per_applied_W_year: 'Equivalent annual energy delta (SolarEdge minus Solectria)',
            headline_positive_gain_lcoo: 'Headline LCOO, positive lifecycle gain',
            signed_nonzero_lcoo: 'Signed LCOO, nonzero lifecycle energy',
        };
        const TECHNOECONOMIC_SENSITIVITY_LABELS = {
            lifecycle_lcoe_solectria: 'Solectria lifecycle LCOE',
            lifecycle_lcoe_solaredge: 'SolarEdge lifecycle LCOE',
            lifecycle_cost_delta_se_minus_sol: 'Lifecycle cost delta (SolarEdge minus Solectria)',
            lifecycle_energy_delta_se_minus_sol: 'Lifecycle energy delta (SolarEdge minus Solectria)',
            headline_positive_gain_lcoo_se_minus_sol: 'Headline LCOO (SolarEdge minus Solectria)',
        };
        const TECHNOECONOMIC_TRADEOFF_LABELS = {
            cost_increase_energy_gain: 'Higher cost, higher energy',
            cost_neutral_energy_gain: 'Cost-neutral, higher energy',
            cost_saving_energy_gain: 'Lower cost, higher energy',
            cost_increase_energy_loss: 'Higher cost, lower energy',
            cost_neutral_energy_loss: 'Cost-neutral, lower energy',
            cost_saving_energy_loss: 'Lower cost, lower energy',
            cost_increase_zero_energy_change: 'Higher cost, zero energy change',
            cost_neutral_zero_energy_change: 'Cost-neutral, zero energy change',
            cost_saving_zero_energy_change: 'Lower cost, zero energy change',
        };

        let technoeconomicActiveJobId = null;
        let technoeconomicJob = null;
        let technoeconomicSources = [];
        let technoeconomicDraftRevision = 0;
        let technoeconomicPendingSubmission = null;
        let technoeconomicPendingSourceId = '';
        let technoeconomicSourceRequestRevision = 0;
        let technoeconomicStatusRequestRevision = 0;
        let technoeconomicSourceAbortController = null;
        let technoeconomicStatusAbortController = null;
        let technoeconomicLifecycleAbortController = null;
        let technoeconomicSubmissionAbortController = null;
        let technoeconomicStatusTimer = null;
        let technoeconomicPollFailureCount = 0;
        let technoeconomicLifecycleRequestRevision = 0;
        let technoeconomicLifecycleRequestInFlight = false;
        let technoeconomicSubmissionRequestRevision = 0;
        let technoeconomicSubmissionRequestInFlight = false;
        let technoeconomicWorkspaceInitialized = false;
        let technoeconomicApplyingDraft = false;
        let technoeconomicEntryMode = TECHNOECONOMIC_GUIDED_ENTRY_MODE;
        let technoeconomicLifecycleEntryMode = 'empty';
        let technoeconomicLifecycleTemplateModified = false;
        let technoeconomicAssumptionsTrigger = null;
        let technoeconomicAssumptionsReturnFocus = true;
        let technoeconomicFormulaRegistryPayload = null;
        let technoeconomicFormulaRegistryPromise = null;

        function technoeconomicPlainObject(value) {
            return value && typeof value === 'object' && !Array.isArray(value) ? value : {};
        }

        function technoeconomicText(value) {
            if (typeof value === 'string') return value;
            if (typeof value === 'number' && Number.isFinite(value)) return String(value);
            if (typeof value === 'bigint') return String(value);
            return '';
        }

        function technoeconomicChoice(value, allowed, fallback) {
            if (value === undefined || value === null) return fallback;
            return allowed.includes(value) ? value : '';
        }

        function technoeconomicToday() {
            return new Date().toISOString().slice(0, 10);
        }

        function technoeconomicDefaultEvidence() {
            return {
                evidence_class: 'direct_quote_or_primary_document',
                citation: {
                    title: '', organization: '', url: '', stable_reference: '',
                    publication_or_as_of_date: '', accessed_date: '',
                    excerpt_or_derivation_note: '',
                    preservation_mode: 'metadata_excerpt_only',
                    user_supplied_content_sha256: '', metadata_only_rationale: '',
                },
                explicit_acceptance: false,
                acceptance_rationale: '',
            };
        }

        function technoeconomicDefaultDistribution(value = '') {
            return {
                family: 'fixed', value: String(value), low: '', mode: '', high: '', mean: '', sd: '',
            };
        }

        function technoeconomicDefaultDocumented(unit, value = '') {
            return {
                unit,
                distribution: technoeconomicDefaultDistribution(value),
                evidence: technoeconomicDefaultEvidence(),
            };
        }

        function technoeconomicDefaultCurrencyYear(costYear = '') {
            return {
                method: 'same_year_no_adjustment',
                source_cost_year: String(costYear),
                target_constant_dollar_cost_year: String(costYear),
                submitted_distribution_basis: 'target_constant_dollar_year',
                index_identity: 'not_applicable_same_year', index_factor: '1',
                derivation: '', index_source_evidence: technoeconomicDefaultEvidence(),
            };
        }

        function technoeconomicDefaultCostLine(system = 'solectria', index = 0) {
            const solaredge = system === 'solaredge';
            return {
                input_id: solaredge ? `cost.se.line-${index + 1}` : `cost.sol.line-${index + 1}`,
                label: solaredge ? 'SolarEdge installed CAPEX' : 'Solectria installed CAPEX',
                ownership: solaredge ? 'solaredge_only' : 'solectria_only',
                cost_type: 'initial_capex', distribution: technoeconomicDefaultDistribution(''),
                coverage_include_ids: [solaredge ? 'equipment.solaredge' : 'equipment.solectria'],
                coverage_exclude_ids: [], original_unit: 'usd_total',
                normalized_unit: 'usd_per_applied_w',
                normalization_method: 'divide_by_frozen_applied_capacity_w',
                solectria_quantity: solaredge ? '0' : '1',
                solaredge_quantity: solaredge ? '1' : '0', quantity_unit: '',
                normalization_derivation: '', constant_dollar_cost_year: '',
                currency_year_normalization: technoeconomicDefaultCurrencyYear(''),
                evidence: technoeconomicDefaultEvidence(),
            };
        }

        function technoeconomicGuidedScaleValue(value, divisor = 1) {
            const text = technoeconomicText(value).trim();
            if (!text || divisor === 1) return text;
            const number = Number(text);
            return Number.isFinite(number) ? String(number / divisor) : text;
        }

        function technoeconomicGuidedDistribution(central, low = '', high = '', divisor = 1) {
            const scaledCentral = technoeconomicGuidedScaleValue(central, divisor);
            const scaledLow = technoeconomicGuidedScaleValue(low, divisor);
            const scaledHigh = technoeconomicGuidedScaleValue(high, divisor);
            if (!scaledLow && !scaledHigh) {
                return technoeconomicDefaultDistribution(scaledCentral);
            }
            return {
                family: 'triangular', value: '', low: scaledLow,
                mode: scaledCentral, high: scaledHigh, mean: '', sd: '',
            };
        }

        function technoeconomicGuidedDisplayDistribution(value, multiplier = 1) {
            const distribution = technoeconomicSanitizeDistribution(value);
            const display = (candidate) => {
                const text = technoeconomicText(candidate).trim();
                const number = Number(text);
                return text && Number.isFinite(number) ? String(number * multiplier) : text;
            };
            if (distribution.family === 'triangular') {
                return {
                    central: display(distribution.mode),
                    low: display(distribution.low),
                    high: display(distribution.high),
                };
            }
            return {central: display(distribution.value), low: '', high: ''};
        }

        function technoeconomicGuidedEvidence(note, accepted, options = {}) {
            const today = technoeconomicText(options.date) || technoeconomicToday();
            const subject = technoeconomicText(options.subject) || 'Guided SolarTAC TEA assumption';
            const seed = technoeconomicText(options.seed) || 'unseeded-draft';
            const rationale = technoeconomicText(note).trim();
            return {
                evidence_class: 'engineering_judgment',
                citation: {
                    title: subject,
                    organization: 'User-supplied guided TEA assumptions',
                    url: '',
                    stable_reference: `guided-solartac-assumptions-${seed}`,
                    publication_or_as_of_date: today,
                    accessed_date: today,
                    excerpt_or_derivation_note: rationale,
                    preservation_mode: 'metadata_excerpt_only',
                    user_supplied_content_sha256: '',
                    metadata_only_rationale: 'The guided form preserves the user-entered '
                        + 'assumption statement and explicit acceptance; no source document '
                        + 'bytes are uploaded by this interface.',
                },
                explicit_acceptance: accepted === true,
                acceptance_rationale: rationale,
            };
        }

        function technoeconomicGuidedCostLine(options) {
            const recurring = options.costType === 'recurring_om';
            const year = technoeconomicText(options.costYear);
            const line = technoeconomicDefaultCostLine(
                options.ownership === 'solaredge_only' ? 'solaredge' : 'solectria', 0
            );
            line.input_id = options.inputId;
            line.label = options.label;
            line.ownership = options.ownership;
            line.cost_type = options.costType;
            line.distribution = technoeconomicSanitizeDistribution(options.distribution);
            line.coverage_include_ids = [options.coverageId];
            line.coverage_exclude_ids = [];
            line.original_unit = recurring ? 'usd_total_per_year' : 'usd_total';
            line.normalized_unit = recurring ? 'usd_per_applied_w_year' : 'usd_per_applied_w';
            line.normalization_method = 'divide_by_frozen_applied_capacity_w';
            line.solectria_quantity = options.ownership === 'solectria_only' ? '1' : '0';
            line.solaredge_quantity = options.ownership === 'solaredge_only' ? '1' : '0';
            line.quantity_unit = '';
            line.normalization_derivation = 'Guided SolarTAC total-dollar input divided by '
                + 'the applicable system\'s verified frozen Annual applied capacity in watts. '
                + 'When clipping is enabled this is the AC operating limit; otherwise it is '
                + 'the installed DC nameplate.';
            line.constant_dollar_cost_year = year;
            line.currency_year_normalization = technoeconomicDefaultCurrencyYear(year);
            line.currency_year_normalization.derivation = `Submitted directly in ${year || 'the selected'} `
                + 'constant-dollar year; no price-index adjustment is applied.';
            line.evidence = technoeconomicSanitizeEvidence(options.evidence);
            return line;
        }

        function technoeconomicGenerateSafeSeed() {
            if (typeof crypto === 'object' && typeof crypto.getRandomValues === 'function') {
                const words = new Uint32Array(2);
                crypto.getRandomValues(words);
                const safe = (BigInt(words[0] & 0x001fffff) << 32n) | BigInt(words[1]);
                return safe.toString();
            }
            const timestamp = BigInt(Date.now() & 0x1fffffff);
            const random = BigInt(Math.floor(Math.random() * 0x1000000));
            return ((timestamp << 24n) | random).toString();
        }

        function technoeconomicDefaultTechnologyDesign(_solaredge = false) {
            return {
                optimizer_count: '', inverter_count: '', transformer_count: '',
                dc_ac_ratio: '', inverter_loading_ratio: '',
                inverter_topology: '', transformer_topology: '', bos_scope: '',
                labor_productivity_and_rates: '', commissioning_scope: '',
            };
        }

        function technoeconomicDefaultCommercialDesign() {
            return {
                design_id: '', reference_wdc: '', module_model: '', module_stc_wdc: '',
                module_count: '', constant_dollar_cost_year: '',
                solectria: technoeconomicDefaultTechnologyDesign(false),
                solaredge: technoeconomicDefaultTechnologyDesign(true),
                normalization_derivation: '', evidence: technoeconomicDefaultEvidence(),
            };
        }

        function technoeconomicDefaultCommercialTransfer() {
            return {
                status: 'approved', explicit_attestation: false, attested_by: '',
                attested_at: '', attestation_rationale: '',
                baseline_factor: technoeconomicDefaultDocumented('dimensionless_multiplier', ''),
                incremental_factor: technoeconomicDefaultDocumented('dimensionless_multiplier', ''),
                mechanisms: TECHNOECONOMIC_TRANSFER_MECHANISMS.map((mechanism) => ({
                    mechanism, status: 'not_applicable', rationale: '',
                    evidence: technoeconomicDefaultEvidence(),
                })),
            };
        }

        function technoeconomicDefaultCommercialScaling() {
            return {
                target_capacity: '', target_capacity_unit: 'mw', target_rating_basis: '',
                marginal_cost_difference: technoeconomicDefaultDistribution(''),
                marginal_cost_timing: 'lifecycle_present_value',
                marginal_cost_unit: 'constant_usd',
                transfer_method: 'direct_capacity_scaling', transfer_rationale: '',
                evidence: technoeconomicDefaultEvidence(),
            };
        }

        function technoeconomicDefaultDraft() {
            const year = '';
            const sol = technoeconomicDefaultCostLine('solectria', 0);
            const se = technoeconomicDefaultCostLine('solaredge', 1);
            for (const line of [sol, se]) {
                line.constant_dollar_cost_year = year;
                line.currency_year_normalization = technoeconomicDefaultCurrencyYear(year);
            }
            return {
                schema_version: TECHNOECONOMIC_DRAFT_SCHEMA_VERSION,
                entry_mode: TECHNOECONOMIC_GUIDED_ENTRY_MODE,
                provisional_reference_applied: false,
                source_annual_job_id: '', basis: 'solartac_site',
                capacity_normalization: TECHNOECONOMIC_APPLIED_CAPACITY_NORMALIZATION,
                n: '10000', seed: '',
                cost_year: year, project_life_years: '',
                project_life_evidence: technoeconomicDefaultEvidence(),
                discount_rate: technoeconomicDefaultDocumented('real_fraction_per_year', ''),
                shared_degradation: technoeconomicDefaultDocumented('real_fraction_per_year', ''),
                cost_lines: [sol, se],
                commercial_reference_design: technoeconomicDefaultCommercialDesign(),
                transfer_enabled: false,
                commercial_transfer: technoeconomicDefaultCommercialTransfer(),
                commercial_scaling: null,
                active_job_id: null,
            };
        }

        function technoeconomicSanitizeEvidence(value) {
            const source = technoeconomicPlainObject(value);
            const citation = technoeconomicPlainObject(source.citation);
            const output = technoeconomicDefaultEvidence();
            output.evidence_class = technoeconomicChoice(
                source.evidence_class,
                TECHNOECONOMIC_EVIDENCE_CLASSES.map((item) => item[0]), output.evidence_class
            );
            for (const key of [
                'title', 'organization', 'url', 'stable_reference',
                'publication_or_as_of_date', 'accessed_date',
                'excerpt_or_derivation_note', 'user_supplied_content_sha256',
                'metadata_only_rationale',
            ]) output.citation[key] = technoeconomicText(citation[key]);
            output.explicit_acceptance = source.explicit_acceptance === true;
            output.acceptance_rationale = technoeconomicText(source.acceptance_rationale);
            return output;
        }

        function technoeconomicSanitizeDistribution(value, fallbackValue = '') {
            const source = technoeconomicPlainObject(value);
            const output = technoeconomicDefaultDistribution(fallbackValue);
            output.family = technoeconomicChoice(
                source.family,
                TECHNOECONOMIC_DISTRIBUTION_FAMILIES.map((item) => item[0]), 'fixed'
            );
            for (const key of ['value', 'low', 'mode', 'high', 'mean', 'sd']) {
                output[key] = technoeconomicText(source[key], 80);
            }
            return output;
        }

        function technoeconomicSanitizeDocumented(value, unit, fallbackValue = '') {
            const source = technoeconomicPlainObject(value);
            return {
                unit,
                distribution: technoeconomicSanitizeDistribution(source.distribution, fallbackValue),
                evidence: technoeconomicSanitizeEvidence(source.evidence),
            };
        }

        function technoeconomicSanitizeCurrencyYear(value, targetYear) {
            const source = technoeconomicPlainObject(value);
            const output = technoeconomicDefaultCurrencyYear(targetYear);
            output.method = technoeconomicChoice(
                source.method, ['same_year_no_adjustment', 'price_index_adjustment'], output.method
            );
            for (const key of [
                'source_cost_year', 'target_constant_dollar_cost_year', 'index_identity',
                'index_factor', 'derivation',
            ]) output[key] = technoeconomicText(source[key], key === 'derivation' ? 4000 : 200);
            output.target_constant_dollar_cost_year = technoeconomicText(targetYear, 10);
            output.index_source_evidence = technoeconomicSanitizeEvidence(source.index_source_evidence);
            return output;
        }

        function technoeconomicSanitizeIdList(value) {
            const values = Array.isArray(value)
                ? value : typeof value === 'string' ? value.split(/[\s,]+/) : [];
            return values.map((item) => technoeconomicText(item)).filter(Boolean);
        }

        function technoeconomicSanitizeCostLine(value, index, costYear, basis) {
            const source = technoeconomicPlainObject(value);
            const output = technoeconomicDefaultCostLine(index % 2 ? 'solaredge' : 'solectria', index);
            output.input_id = technoeconomicText(source.input_id, 160);
            output.label = technoeconomicText(source.label);
            output.ownership = technoeconomicChoice(
                source.ownership, ['solectria_only', 'solaredge_only', 'paired_shared'], output.ownership
            );
            output.cost_type = technoeconomicChoice(source.cost_type, [
                'initial_capex', 'initial_installation_labor', 'recurring_labor',
                'recurring_om', 'recurring_maintenance',
            ], output.cost_type);
            output.distribution = technoeconomicSanitizeDistribution(source.distribution);
            output.coverage_include_ids = technoeconomicSanitizeIdList(source.coverage_include_ids);
            output.coverage_exclude_ids = technoeconomicSanitizeIdList(source.coverage_exclude_ids);
            output.original_unit = technoeconomicChoice(source.original_unit, [
                'usd_total', 'usd_total_per_year', 'usd_per_unit', 'usd_per_unit_year',
                'usd_per_wdc', 'usd_per_wdc_year',
            ], output.original_unit);
            output.normalized_unit = technoeconomicChoice(source.normalized_unit, [
                'usd_per_wdc', 'usd_per_wdc_year',
                'usd_per_applied_w', 'usd_per_applied_w_year',
            ], output.normalized_unit);
            output.normalization_method = technoeconomicChoice(source.normalization_method, [
                'divide_by_frozen_source_wdc',
                'multiply_quantity_then_divide_by_frozen_source_wdc',
                'divide_by_frozen_applied_capacity_w',
                'multiply_quantity_then_divide_by_frozen_applied_capacity_w',
                'already_normalized_per_wdc',
            ], output.normalization_method);
            const recurring = output.cost_type.startsWith('recurring_');
            if (basis === 'solartac_site') {
                output.normalized_unit = recurring
                    ? 'usd_per_applied_w_year' : 'usd_per_applied_w';
                output.normalization_method = source.normalization_method ===
                    'multiply_quantity_then_divide_by_frozen_source_wdc'
                    || source.normalization_method ===
                    'multiply_quantity_then_divide_by_frozen_applied_capacity_w'
                    ? 'multiply_quantity_then_divide_by_frozen_applied_capacity_w'
                    : 'divide_by_frozen_applied_capacity_w';
            } else if (basis === 'commercial_representative') {
                output.normalized_unit = recurring ? 'usd_per_wdc_year' : 'usd_per_wdc';
                output.normalization_method = 'already_normalized_per_wdc';
            }
            for (const key of [
                'solectria_quantity', 'solaredge_quantity', 'quantity_unit',
                'normalization_derivation',
            ]) output[key] = technoeconomicText(
                source[key], key === 'normalization_derivation' ? 4000 : 200
            );
            output.constant_dollar_cost_year = technoeconomicText(costYear, 10);
            output.currency_year_normalization = technoeconomicSanitizeCurrencyYear(
                source.currency_year_normalization, costYear
            );
            output.evidence = technoeconomicSanitizeEvidence(source.evidence);
            return output;
        }

        function technoeconomicSanitizeTechnology(value, solaredge) {
            const source = technoeconomicPlainObject(value);
            const output = technoeconomicDefaultTechnologyDesign(solaredge);
            for (const key of Object.keys(output)) output[key] = technoeconomicText(source[key]);
            return output;
        }

        function technoeconomicSanitizeCommercialDesign(value, costYear) {
            const source = technoeconomicPlainObject(value);
            const output = technoeconomicDefaultCommercialDesign();
            for (const key of [
                'design_id', 'reference_wdc', 'module_model', 'module_stc_wdc',
                'module_count', 'normalization_derivation',
            ]) output[key] = technoeconomicText(source[key]);
            output.constant_dollar_cost_year = technoeconomicText(costYear, 10);
            output.solectria = technoeconomicSanitizeTechnology(source.solectria, false);
            output.solaredge = technoeconomicSanitizeTechnology(source.solaredge, true);
            output.evidence = technoeconomicSanitizeEvidence(source.evidence);
            return output;
        }

        function technoeconomicSanitizeTransfer(value) {
            const source = technoeconomicPlainObject(value);
            const output = technoeconomicDefaultCommercialTransfer();
            output.explicit_attestation = source.explicit_attestation === true;
            for (const key of ['attested_by', 'attested_at', 'attestation_rationale']) {
                output[key] = technoeconomicText(source[key]);
            }
            output.baseline_factor = technoeconomicSanitizeDocumented(
                source.baseline_factor, 'dimensionless_multiplier', ''
            );
            output.incremental_factor = technoeconomicSanitizeDocumented(
                source.incremental_factor, 'dimensionless_multiplier', ''
            );
            const mechanisms = Array.isArray(source.mechanisms) ? source.mechanisms : [];
            const byName = new Map(mechanisms.map((item) => [item && item.mechanism, item]));
            output.mechanisms = TECHNOECONOMIC_TRANSFER_MECHANISMS.map((mechanism) => {
                const item = technoeconomicPlainObject(byName.get(mechanism));
                return {
                    mechanism,
                    status: technoeconomicChoice(
                        item.status, ['supported', 'not_applicable', 'not_transferred'], 'not_applicable'
                    ),
                    rationale: technoeconomicText(item.rationale),
                    evidence: technoeconomicSanitizeEvidence(item.evidence),
                };
            });
            return output;
        }

        function technoeconomicSanitizeCommercialScaling(value) {
            if (value === null || value === undefined || value === false) return null;
            const source = technoeconomicPlainObject(value);
            const output = technoeconomicDefaultCommercialScaling();
            output.target_capacity = technoeconomicText(source.target_capacity);
            output.target_capacity_unit = technoeconomicChoice(
                source.target_capacity_unit, ['kw', 'mw'], output.target_capacity_unit
            );
            output.target_rating_basis = technoeconomicChoice(
                source.target_rating_basis,
                ['', 'ac_operating_limit', 'dc_installed_nameplate'], ''
            );
            output.marginal_cost_difference = technoeconomicSanitizeDistribution(
                source.marginal_cost_difference
            );
            output.marginal_cost_timing = technoeconomicChoice(
                source.marginal_cost_timing,
                ['lifecycle_present_value', 'equivalent_annual'],
                output.marginal_cost_timing
            );
            output.marginal_cost_unit = output.marginal_cost_timing === 'equivalent_annual'
                ? 'constant_usd_per_year' : 'constant_usd';
            output.transfer_method = 'direct_capacity_scaling';
            output.transfer_rationale = technoeconomicText(source.transfer_rationale);
            output.evidence = technoeconomicSanitizeEvidence(source.evidence);
            return output;
        }

        function sanitizeTechnoeconomicDraft(value) {
            const source = technoeconomicPlainObject(value);
            const fallback = technoeconomicDefaultDraft();
            const basis = technoeconomicChoice(
                source.basis, ['', 'solartac_site', 'commercial_representative'], ''
            );
            const output = {
                schema_version: TECHNOECONOMIC_DRAFT_SCHEMA_VERSION,
                entry_mode: technoeconomicChoice(
                    source.entry_mode,
                    [TECHNOECONOMIC_GUIDED_ENTRY_MODE, TECHNOECONOMIC_ADVANCED_ENTRY_MODE],
                    TECHNOECONOMIC_ADVANCED_ENTRY_MODE
                ),
                provisional_reference_applied: source.provisional_reference_applied === true,
                source_annual_job_id: technoeconomicText(source.source_annual_job_id, 200),
                basis,
                capacity_normalization: basis === 'solartac_site'
                    ? TECHNOECONOMIC_APPLIED_CAPACITY_NORMALIZATION : null,
                n: source.n !== undefined
                    ? technoeconomicText(source.n, 12)
                    : source.realizations !== undefined
                        ? technoeconomicText(source.realizations, 12) : fallback.n,
                seed: source.seed !== undefined
                    ? technoeconomicText(source.seed, 20) : fallback.seed,
                cost_year: source.cost_year !== undefined
                    ? technoeconomicText(source.cost_year, 10) : fallback.cost_year,
                project_life_years: source.project_life_years !== undefined
                    ? technoeconomicText(source.project_life_years, 12)
                    : fallback.project_life_years,
                project_life_evidence: technoeconomicSanitizeEvidence(source.project_life_evidence),
                discount_rate: technoeconomicSanitizeDocumented(
                    source.discount_rate, 'real_fraction_per_year', ''
                ),
                shared_degradation: technoeconomicSanitizeDocumented(
                    source.shared_degradation, 'real_fraction_per_year', ''
                ),
                cost_lines: [], commercial_reference_design: {},
                transfer_enabled: source.transfer_enabled === true,
                commercial_transfer: technoeconomicSanitizeTransfer(source.commercial_transfer),
                commercial_scaling: technoeconomicSanitizeCommercialScaling(
                    source.commercial_scaling
                ),
                active_job_id: typeof source.active_job_id === 'string'
                    && source.active_job_id.length <= 200
                    && /^tea_[A-Za-z0-9._:-]+$/.test(source.active_job_id)
                    ? source.active_job_id : null,
            };
            const lines = Array.isArray(source.cost_lines)
                ? source.cost_lines : fallback.cost_lines;
            output.cost_lines = lines.map((line, index) => technoeconomicSanitizeCostLine(
                line, index, output.cost_year, output.basis
            ));
            output.commercial_reference_design = technoeconomicSanitizeCommercialDesign(
                source.commercial_reference_design, output.cost_year
            );
            return output;
        }

        function technoeconomicGuidedLine(draft, key) {
            const inputId = TECHNOECONOMIC_GUIDED_COST_IDS[key];
            return (draft.cost_lines || []).find((line) => line.input_id === inputId) || null;
        }

        function technoeconomicGuidedInputsFromDraft(value) {
            const draft = sanitizeTechnoeconomicDraft(value);
            const discount = technoeconomicGuidedDisplayDistribution(
                draft.discount_rate.distribution, 100
            );
            const degradation = technoeconomicGuidedDisplayDistribution(
                draft.shared_degradation.distribution, 100
            );
            const solectriaCapex = technoeconomicGuidedDisplayDistribution(
                technoeconomicGuidedLine(draft, 'solectria_capex')?.distribution
            );
            const solectriaOm = technoeconomicGuidedDisplayDistribution(
                technoeconomicGuidedLine(draft, 'solectria_om')?.distribution
            );
            const solaredgeCapex = technoeconomicGuidedDisplayDistribution(
                technoeconomicGuidedLine(draft, 'solaredge_capex')?.distribution
            );
            const solaredgeOm = technoeconomicGuidedDisplayDistribution(
                technoeconomicGuidedLine(draft, 'solaredge_om')?.distribution
            );
            const evidence = technoeconomicSanitizeEvidence(draft.project_life_evidence);
            const commercial = technoeconomicSanitizeCommercialScaling(
                draft.commercial_scaling
            ) || technoeconomicDefaultCommercialScaling();
            const commercialCost = technoeconomicGuidedDisplayDistribution(
                commercial.marginal_cost_difference
            );
            const commercialEvidence = technoeconomicSanitizeEvidence(commercial.evidence);
            return {
                cost_year: draft.cost_year,
                project_life_years: draft.project_life_years,
                discount: discount.central,
                discount_low: discount.low,
                discount_high: discount.high,
                degradation: degradation.central,
                degradation_low: degradation.low,
                degradation_high: degradation.high,
                solectria_capex: solectriaCapex.central,
                solectria_capex_low: solectriaCapex.low,
                solectria_capex_high: solectriaCapex.high,
                solectria_om: solectriaOm.central,
                solectria_om_low: solectriaOm.low,
                solectria_om_high: solectriaOm.high,
                solaredge_capex: solaredgeCapex.central,
                solaredge_capex_low: solaredgeCapex.low,
                solaredge_capex_high: solaredgeCapex.high,
                solaredge_om: solaredgeOm.central,
                solaredge_om_low: solaredgeOm.low,
                solaredge_om_high: solaredgeOm.high,
                assumption_note: evidence.acceptance_rationale
                    || evidence.citation.excerpt_or_derivation_note || '',
                accepted: evidence.explicit_acceptance === true,
                commercial_enabled: draft.commercial_scaling !== null,
                commercial_target_capacity: commercial.target_capacity,
                commercial_target_unit: commercial.target_capacity_unit,
                commercial_rating_basis: commercial.target_rating_basis,
                commercial_cost: commercialCost.central,
                commercial_cost_low: commercialCost.low,
                commercial_cost_high: commercialCost.high,
                commercial_cost_timing: commercial.marginal_cost_timing,
                commercial_rationale: commercial.transfer_rationale
                    || commercialEvidence.acceptance_rationale
                    || commercialEvidence.citation.excerpt_or_derivation_note || '',
                commercial_accepted: commercialEvidence.explicit_acceptance === true,
            };
        }

        function technoeconomicBuildGuidedDraft(value, guidedValue, options = {}) {
            const draft = sanitizeTechnoeconomicDraft(value);
            const guided = technoeconomicPlainObject(guidedValue);
            const seed = technoeconomicText(options.seed || draft.seed);
            const note = technoeconomicText(guided.assumption_note);
            const accepted = guided.accepted === true;
            const costYear = technoeconomicText(guided.cost_year);
            const evidenceFor = (subject) => technoeconomicGuidedEvidence(
                note, accepted, {subject, seed, date: options.date}
            );
            const solectriaCapexEvidence = evidenceFor('Solectria total installed CAPEX assumption');
            const solectriaOmEvidence = evidenceFor('Solectria annual O&M assumption');
            const solaredgeCapexEvidence = evidenceFor('SolarEdge total installed CAPEX assumption');
            const solaredgeOmEvidence = evidenceFor('SolarEdge annual O&M assumption');
            draft.entry_mode = TECHNOECONOMIC_GUIDED_ENTRY_MODE;
            draft.provisional_reference_applied = false;
            draft.basis = 'solartac_site';
            draft.n = '10000';
            draft.seed = seed;
            draft.cost_year = costYear;
            draft.project_life_years = technoeconomicText(guided.project_life_years);
            draft.project_life_evidence = evidenceFor('Project-life assumption');
            draft.discount_rate = {
                unit: 'real_fraction_per_year',
                distribution: technoeconomicGuidedDistribution(
                    guided.discount, guided.discount_low, guided.discount_high, 100
                ),
                evidence: evidenceFor('Real discount-rate assumption'),
            };
            draft.shared_degradation = {
                unit: 'real_fraction_per_year',
                distribution: technoeconomicGuidedDistribution(
                    guided.degradation || '0',
                    guided.degradation_low,
                    guided.degradation_high,
                    100
                ),
                evidence: evidenceFor('Shared annual module-degradation assumption'),
            };
            draft.cost_lines = [
                technoeconomicGuidedCostLine({
                    inputId: TECHNOECONOMIC_GUIDED_COST_IDS.solectria_capex,
                    label: 'Solectria total installed CAPEX', ownership: 'solectria_only',
                    costType: 'initial_capex',
                    distribution: technoeconomicGuidedDistribution(
                        guided.solectria_capex,
                        guided.solectria_capex_low,
                        guided.solectria_capex_high
                    ),
                    coverageId: 'scope.guided.solectria.initial',
                    costYear, evidence: solectriaCapexEvidence,
                }),
                technoeconomicGuidedCostLine({
                    inputId: TECHNOECONOMIC_GUIDED_COST_IDS.solectria_om,
                    label: 'Solectria annual O&M', ownership: 'solectria_only',
                    costType: 'recurring_om',
                    distribution: technoeconomicGuidedDistribution(
                        guided.solectria_om,
                        guided.solectria_om_low,
                        guided.solectria_om_high
                    ),
                    coverageId: 'scope.guided.solectria.recurring',
                    costYear, evidence: solectriaOmEvidence,
                }),
                technoeconomicGuidedCostLine({
                    inputId: TECHNOECONOMIC_GUIDED_COST_IDS.solaredge_capex,
                    label: 'SolarEdge total installed CAPEX', ownership: 'solaredge_only',
                    costType: 'initial_capex',
                    distribution: technoeconomicGuidedDistribution(
                        guided.solaredge_capex,
                        guided.solaredge_capex_low,
                        guided.solaredge_capex_high
                    ),
                    coverageId: 'scope.guided.solaredge.initial',
                    costYear, evidence: solaredgeCapexEvidence,
                }),
                technoeconomicGuidedCostLine({
                    inputId: TECHNOECONOMIC_GUIDED_COST_IDS.solaredge_om,
                    label: 'SolarEdge annual O&M', ownership: 'solaredge_only',
                    costType: 'recurring_om',
                    distribution: technoeconomicGuidedDistribution(
                        guided.solaredge_om,
                        guided.solaredge_om_low,
                        guided.solaredge_om_high
                    ),
                    coverageId: 'scope.guided.solaredge.recurring',
                    costYear, evidence: solaredgeOmEvidence,
                }),
            ];
            draft.commercial_reference_design = technoeconomicDefaultCommercialDesign();
            draft.transfer_enabled = false;
            draft.commercial_transfer = technoeconomicDefaultCommercialTransfer();
            if (guided.commercial_enabled === true) {
                const commercialRationale = technoeconomicText(guided.commercial_rationale);
                const commercialAccepted = guided.commercial_accepted === true;
                const timing = technoeconomicChoice(
                    guided.commercial_cost_timing,
                    ['lifecycle_present_value', 'equivalent_annual'],
                    'lifecycle_present_value'
                );
                draft.commercial_scaling = {
                    target_capacity: technoeconomicText(guided.commercial_target_capacity),
                    target_capacity_unit: technoeconomicChoice(
                        guided.commercial_target_unit, ['kw', 'mw'], 'mw'
                    ),
                    target_rating_basis: technoeconomicChoice(
                        guided.commercial_rating_basis,
                        ['', 'ac_operating_limit', 'dc_installed_nameplate'], ''
                    ),
                    marginal_cost_difference: technoeconomicGuidedDistribution(
                        guided.commercial_cost,
                        guided.commercial_cost_low,
                        guided.commercial_cost_high
                    ),
                    marginal_cost_timing: timing,
                    marginal_cost_unit: timing === 'equivalent_annual'
                        ? 'constant_usd_per_year' : 'constant_usd',
                    transfer_method: 'direct_capacity_scaling',
                    transfer_rationale: commercialRationale,
                    evidence: technoeconomicGuidedEvidence(
                        commercialRationale, commercialAccepted, {
                            subject: 'Commercial direct-capacity scaling and marginal-cost assumption',
                            seed, date: options.date,
                        }
                    ),
                };
            } else {
                draft.commercial_scaling = null;
            }
            return sanitizeTechnoeconomicDraft(draft);
        }

        function technoeconomicDomElement(id) {
            return typeof document === 'object' && typeof document.getElementById === 'function'
                ? document.getElementById(id) : null;
        }

        function technoeconomicStandaloneSelectedSource() {
            const sourceId = technoeconomicElements.standaloneSourceSelect?.value || '';
            return technoeconomicSources.find(
                (item) => item?.source_annual_job_id === sourceId
            ) || null;
        }

        function technoeconomicPairedSystem(system) {
            return TECHNOECONOMIC_PAIRED_SYSTEMS.find((item) => item.key === system) || null;
        }

        function technoeconomicPairedSystemElements(system) {
            if (system === 'solectria') return {
                costLines: technoeconomicElements.standaloneSolectriaCostLines,
                replacementEnabled: technoeconomicElements.standaloneSolectriaReplacementEnabled,
                replacementFields: technoeconomicElements.standaloneSolectriaReplacementFields,
                costSummary: technoeconomicElements.standaloneSolectriaCostSummary,
                sourceCapacity: technoeconomicElements.standaloneSolectriaSourceCapacity,
                sourceEnergy: technoeconomicElements.standaloneSolectriaSourceEnergy,
                specificEnergy: technoeconomicElements.standaloneSolectriaSpecificEnergy,
                targetEnergy: technoeconomicElements.standaloneSolectriaTargetEnergy,
            };
            return {
                costLines: technoeconomicElements.standaloneSolarEdgeCostLines,
                replacementEnabled: technoeconomicElements.standaloneSolarEdgeReplacementEnabled,
                replacementFields: technoeconomicElements.standaloneSolarEdgeReplacementFields,
                costSummary: technoeconomicElements.standaloneSolarEdgeCostSummary,
                sourceCapacity: technoeconomicElements.standaloneSolarEdgeSourceCapacity,
                sourceEnergy: technoeconomicElements.standaloneSolarEdgeSourceEnergy,
                specificEnergy: technoeconomicElements.standaloneSolarEdgeSpecificEnergy,
                targetEnergy: technoeconomicElements.standaloneSolarEdgeTargetEnergy,
            };
        }

        function technoeconomicStandaloneSourceCapacityInfo(source, system = 'solaredge') {
            if (!source) return null;
            if (!technoeconomicPairedSystem(system)) return null;
            const applied = technoeconomicPlainObject(
                technoeconomicPlainObject(source.applied_capacity)[system]
            );
            const appliedWatts = Number(applied.applied_capacity_w);
            if (Number.isFinite(appliedWatts) && appliedWatts > 0
                && ['ac_operating_limit', 'dc_installed_nameplate'].includes(
                    applied.rating_basis
                )) {
                return {
                    watts: appliedWatts,
                    ratingBasis: applied.rating_basis,
                    source: 'verified_applied_capacity',
                };
            }
            const provenance = technoeconomicPlainObject(source.provenance);
            const operating = technoeconomicPlainObject(provenance.operating_limit);
            const limitKw = Number(operating.curtailment_limit_kw);
            if (operating.curtailment_enabled === true
                && Number.isFinite(limitKw) && limitKw > 0) {
                return {
                    watts: limitKw * 1000,
                    ratingBasis: 'ac_operating_limit',
                    source: 'verified_operating_limit',
                };
            }
            const installedWdc = Number(source[`${system}_installed_wdc`]);
            return Number.isFinite(installedWdc) && installedWdc > 0 ? {
                watts: installedWdc,
                ratingBasis: 'dc_installed_nameplate',
                source: 'verified_installed_nameplate',
            } : null;
        }

        function technoeconomicStandaloneRatingSuffix(ratingBasis) {
            return ratingBasis === 'ac_operating_limit' ? 'ac'
                : ratingBasis === 'dc_installed_nameplate' ? 'dc' : '';
        }

        function technoeconomicStandaloneFormatCapacity(watts, ratingBasis, options = {}) {
            const value = Number(watts);
            if (!Number.isFinite(value) || value <= 0) return 'Unavailable';
            const suffix = technoeconomicStandaloneRatingSuffix(ratingBasis);
            const useMw = options.forceMw === true || value >= 1000000;
            return `${technoeconomicFormatNumber(value / (useMw ? 1000000 : 1000), 4)} `
                + `${useMw ? 'MW' : 'kW'}${suffix}`;
        }

        function technoeconomicStandaloneDistributionFields(family) {
            return ({
                fixed: [['value', 'Value']],
                uniform: [['low', 'Low'], ['high', 'High']],
                triangular: [['low', 'Low'], ['mode', 'Most likely'], ['high', 'High']],
                bounded_normal: [
                    ['low', 'Low bound'], ['mean', 'Mean'],
                    ['high', 'High bound'], ['sd', 'Standard deviation'],
                ],
            })[family] || [['value', 'Value']];
        }

        function technoeconomicStandaloneReadParameterValues(container) {
            const values = {};
            container?.querySelectorAll?.('[data-tea-v4-param]').forEach((input) => {
                values[input.dataset.teaV4Param] = input.value;
            });
            return values;
        }

        function technoeconomicStandaloneRenderDistributionParameters(
            container, family, prefix, defaults = {}
        ) {
            if (!container) return;
            const previous = technoeconomicStandaloneReadParameterValues(container);
            const fields = technoeconomicStandaloneDistributionFields(family);
            const nodes = fields.map(([key, label]) => {
                const id = `${prefix}${key[0].toUpperCase()}${key.slice(1)}`;
                const input = technoeconomicNode('input', {
                    id,
                    type: 'number',
                    step: 'any',
                    inputmode: 'decimal',
                    value: previous[key] ?? defaults[key] ?? '',
                });
                input.dataset.teaV4Param = key;
                const field = technoeconomicNode('div', {className: 'tea-field'});
                field.append(
                    technoeconomicNode('label', {text: label, htmlFor: id}),
                    input
                );
                return field;
            });
            container.replaceChildren(...nodes);
        }

        function technoeconomicStandaloneNrelEvidence(
            subject, note, accepted = false, acceptanceRationale = ''
        ) {
            const reviewRationale = technoeconomicText(acceptanceRationale).trim();
            return {
                evidence_class: 'public_market_proxy_or_benchmark',
                citation: {
                    title: subject,
                    organization: 'National Renewable Energy Laboratory',
                    url: TECHNOECONOMIC_STANDALONE_ATB_URL,
                    stable_reference: 'doi:10.25984/2377191',
                    publication_or_as_of_date: '2024-06-24',
                    accessed_date: technoeconomicToday(),
                    excerpt_or_derivation_note: note,
                    preservation_mode: 'metadata_excerpt_only',
                    user_supplied_content_sha256: '',
                    metadata_only_rationale: 'The official NREL/OEDI dataset record, DOI, '
                        + 'and benchmark derivation are saved; source files are not uploaded.',
                },
                explicit_acceptance: accepted === true,
                acceptance_rationale: accepted === true ? reviewRationale : '',
            };
        }

        function technoeconomicStandaloneSourceEvidence(source, accepted, note) {
            const sourceId = technoeconomicText(source?.source_annual_job_id);
            return {
                evidence_class: 'project_actual',
                citation: {
                    title: 'Verified SolarTAC Annual Simulation capacity and energy source',
                    organization: 'SBE Innovation Center',
                    url: '',
                    stable_reference: sourceId || 'unselected-annual-source',
                    publication_or_as_of_date: technoeconomicToday(),
                    accessed_date: technoeconomicToday(),
                    excerpt_or_derivation_note: note,
                    preservation_mode: 'metadata_excerpt_only',
                    user_supplied_content_sha256: '',
                    metadata_only_rationale: 'The immutable Annual source identity is '
                        + 're-verified by the server at submission.',
                },
                explicit_acceptance: accepted === true,
                acceptance_rationale: technoeconomicText(note),
            };
        }

        function technoeconomicStandaloneCreateCostLine(options) {
            const card = technoeconomicNode('section', {className: 'tea-v4-cost-line'});
            const system = technoeconomicPairedSystem(options.system) || TECHNOECONOMIC_PAIRED_SYSTEMS[1];
            const coverage = TECHNOECONOMIC_STANDALONE_COST_COVERAGE[system.key][options.key] || {
                costCategory: '', coverageIds: [],
            };
            card.dataset.teaV4CostLine = options.key;
            card.dataset.teaV4System = system.key;
            card.dataset.inputId = options.inputId;
            card.dataset.timing = options.timing;
            card.dataset.unit = options.unit;
            card.dataset.costCategory = coverage.costCategory;
            card.dataset.coverageIds = coverage.coverageIds.join(',');
            const heading = technoeconomicNode('div', {className: 'tea-v4-cost-line-heading'});
            const copy = technoeconomicNode('div');
            copy.append(
                technoeconomicNode('h5', {text: options.label}),
                technoeconomicNode('p', {text: options.description})
            );
            heading.append(copy, technoeconomicNode('span', {
                className: 'tea-contract-badge', text: options.badge,
            }));
            const systemPrefix = `${system.label}${options.key}`;
            const familyId = `technoeconomicStandaloneCost${systemPrefix}Family`;
            const family = technoeconomicNode('select', {id: familyId});
            family.dataset.teaV4Family = '';
            for (const [value, label] of TECHNOECONOMIC_DISTRIBUTION_FAMILIES) {
                family.appendChild(technoeconomicNode('option', {value, text: label === 'Bounded normal'
                    ? 'Normal (bounded)' : label}));
            }
            family.value = 'fixed';
            const familyField = technoeconomicNode('div', {className: 'tea-field'});
            familyField.append(
                technoeconomicNode('label', {text: 'Distribution', htmlFor: familyId}),
                family
            );
            const parameters = technoeconomicNode('div', {
                className: 'tea-v4-distribution-parameters',
                id: `technoeconomicStandaloneCost${systemPrefix}Parameters`,
            });
            card.append(heading, familyField, parameters);
            technoeconomicStandaloneRenderDistributionParameters(
                parameters, 'fixed', `technoeconomicStandaloneCost${systemPrefix}`,
                {value: options.value || ''}
            );
            family.addEventListener('change', () => {
                technoeconomicStandaloneRenderDistributionParameters(
                    parameters, family.value,
                    `technoeconomicStandaloneCost${systemPrefix}`
                );
            });
            return card;
        }

        function technoeconomicStandaloneCostDefinitions(ratingBasis, system = 'solaredge') {
            const systemMeta = technoeconomicPairedSystem(system) || TECHNOECONOMIC_PAIRED_SYSTEMS[1];
            const preset = TECHNOECONOMIC_STANDALONE_ATB_PRESETS[ratingBasis]
                || TECHNOECONOMIC_STANDALONE_ATB_PRESETS.ac_operating_limit;
            const suffix = ratingBasis === 'dc_installed_nameplate' ? 'Wdc' : 'Wac';
            return [
                {
                    system: systemMeta.key,
                    key: 'Capex', inputId: `commercial.${systemMeta.key}.atb-capex`,
                    label: 'Initial installed cost', timing: 'initial_t0',
                    unit: 'constant_usd_per_target_w', value: preset.capex,
                    badge: `real 2022 USD/${suffix}`,
                    description: `Generic NREL 2024 ATB benchmark for ${systemMeta.label}; not a vendor quote.`,
                },
                {
                    system: systemMeta.key,
                    key: 'Om', inputId: `commercial.${systemMeta.key}.atb-om`,
                    label: 'Annual operations and maintenance', timing: 'annual_year_end',
                    unit: 'constant_usd_per_target_w_year', value: preset.om,
                    badge: `real 2022 USD/k${suffix}-year`,
                    description: `NREL 2024 ATB benchmark for ${systemMeta.label}. Enter USD/k${suffix}-year.`,
                },
            ];
        }

        function technoeconomicStandaloneRenderCostLines(system, ratingBasis, options = {}) {
            const root = technoeconomicPairedSystemElements(system).costLines;
            if (!root) return;
            const current = new Map();
            root.querySelectorAll?.('[data-tea-v4-cost-line]').forEach((card) => {
                current.set(card.dataset.teaV4CostLine, {
                    family: card.querySelector?.('[data-tea-v4-family]')?.value || 'fixed',
                    values: technoeconomicStandaloneReadParameterValues(card),
                });
            });
            const cards = technoeconomicStandaloneCostDefinitions(ratingBasis, system).map((definition) => {
                const prior = current.get(definition.key);
                const card = technoeconomicStandaloneCreateCostLine({
                    ...definition,
                    value: options.forcePreset === true || !prior ? definition.value
                        : prior.values.value || definition.value,
                });
                if (prior && options.forcePreset !== true) {
                    const family = card.querySelector('[data-tea-v4-family]');
                    const parameters = card.querySelector('.tea-v4-distribution-parameters');
                    family.value = prior.family;
                    technoeconomicStandaloneRenderDistributionParameters(
                        parameters, prior.family,
                        `technoeconomicStandaloneCost${definition.key}`,
                        prior.values
                    );
                }
                return card;
            });
            root.replaceChildren(...cards);
            root.dataset.ratingBasis = ratingBasis || '';
        }

        function technoeconomicStandaloneRenderReplacement(system) {
            const systemMeta = technoeconomicPairedSystem(system);
            if (!systemMeta) return;
            const elements = technoeconomicPairedSystemElements(system);
            const enabled = elements.replacementEnabled?.checked === true;
            const root = elements.replacementFields;
            if (elements.replacementEnabled) {
                elements.replacementEnabled.setAttribute(
                    'aria-expanded', String(enabled)
                );
            }
            if (!root) return;
            root.hidden = !enabled;
            if (!enabled || root.childElementCount) return;
            const card = technoeconomicStandaloneCreateCostLine({
                system,
                key: 'Replacement', inputId: `commercial.${system}.scheduled-replacement`,
                label: 'Scheduled replacement', timing: 'scheduled_year_end',
                unit: 'constant_usd_per_target_w', value: '',
                badge: 'real USD/target W',
                description: 'Enter a sourced cost and schedule.',
            });
            const schedule = technoeconomicNode('div', {className: 'tea-field'});
            const id = `technoeconomicStandalone${systemMeta.label}ReplacementYears`;
            schedule.append(
                technoeconomicNode('label', {text: 'Occurrence years', htmlFor: id}),
                technoeconomicNode('input', {
                    id, type: 'text', inputmode: 'numeric',
                    placeholder: 'e.g. 15 or 10, 20',
                }),
                technoeconomicNode('p', {
                    className: 'tea-field-help',
                    text: 'Enter project years in order, separated by commas.',
                })
            );
            card.appendChild(schedule);
            root.replaceChildren(card);
        }

        function technoeconomicStandaloneInitializeEditors() {
            if (!technoeconomicElements.standaloneResults) return;
            if (technoeconomicElements.standaloneSeed
                && !technoeconomicElements.standaloneSeed.value) {
                technoeconomicElements.standaloneSeed.value = technoeconomicGenerateSafeSeed();
            }
            for (const [family, parameters, prefix] of [
                [technoeconomicElements.standaloneDiscountFamily,
                    technoeconomicElements.standaloneDiscountParameters,
                    'technoeconomicStandaloneDiscount'],
                [technoeconomicElements.standaloneDegradationFamily,
                    technoeconomicElements.standaloneDegradationParameters,
                    'technoeconomicStandaloneDegradation'],
            ]) {
                if (!family || !parameters) continue;
                technoeconomicStandaloneRenderDistributionParameters(
                    parameters, family.value || 'fixed', prefix
                );
                family.addEventListener('change', () => {
                    technoeconomicStandaloneRenderDistributionParameters(
                        parameters, family.value, prefix
                    );
                    technoeconomicRenderStandaloneDraft();
                });
            }
            for (const {key} of TECHNOECONOMIC_PAIRED_SYSTEMS) {
                technoeconomicStandaloneRenderCostLines(
                    key, 'ac_operating_limit', {forcePreset: true}
                );
                technoeconomicStandaloneRenderReplacement(key);
            }
        }

        function technoeconomicStandaloneDistributionDraft(familyElement, parameters) {
            return {
                family: familyElement?.value || 'fixed',
                ...technoeconomicStandaloneReadParameterValues(parameters),
            };
        }

        function technoeconomicStandaloneScaleDistribution(distribution, divisor) {
            const output = {...distribution};
            for (const key of ['value', 'low', 'mode', 'high', 'mean', 'sd']) {
                if (output[key] === undefined || output[key] === '') continue;
                const number = Number(output[key]);
                output[key] = Number.isFinite(number) ? String(number / divisor) : output[key];
            }
            return output;
        }

        function technoeconomicStandaloneKernelCostDistribution(line) {
            const distribution = technoeconomicPlainObject(line?.distribution);
            if (line?.timing === 'annual_year_end'
                && line?.unit === 'constant_usd_per_target_w_year') {
                return technoeconomicStandaloneScaleDistribution(distribution, 1000);
            }
            return {...distribution};
        }

        function technoeconomicStandaloneDistributionDisplay(distribution, multiplier = 1) {
            const value = technoeconomicPlainObject(distribution);
            const format = (candidate) => {
                const number = Number(candidate);
                return Number.isFinite(number)
                    ? technoeconomicFormatNumber(number * multiplier, 4) : 'Unavailable';
            };
            if (value.family === 'uniform') {
                return `Uniform ${format(value.low)} to ${format(value.high)}`;
            }
            if (value.family === 'triangular') {
                return `Triangular ${format(value.low)} / most likely ${format(value.mode)} / ${format(value.high)}`;
            }
            if (value.family === 'bounded_normal') {
                return `Normal mean ${format(value.mean)}, SD ${format(value.sd)}, bounded ${format(value.low)} to ${format(value.high)}`;
            }
            return `Fixed ${format(value.value)}`;
        }

        function technoeconomicStandaloneCostReview(line, ratingBasis, costYear) {
            const annualOm = line?.timing === 'annual_year_end'
                && line?.unit === 'constant_usd_per_target_w_year';
            const suffix = technoeconomicStandaloneRatingSuffix(ratingBasis);
            const unit = annualOm ? `real ${costYear} USD/kW${suffix}-year`
                : line?.unit === 'constant_usd_per_target_w'
                    ? `real ${costYear} USD/W${suffix}` : technoeconomicText(line?.unit);
            const distribution = annualOm
                ? technoeconomicStandaloneDistributionDisplay(line.distribution, 1000)
                : technoeconomicReviewDistribution(line.distribution);
            return `${unit}; ${distribution}`;
        }

        function technoeconomicStandaloneParseYears(value, path, errors, projectLife) {
            const text = technoeconomicText(value).trim();
            if (!text) {
                technoeconomicPushError(errors, path, 'Enter at least one occurrence year.');
                return [];
            }
            const values = text.split(/[\s,]+/).filter(Boolean).map(Number);
            if (!values.length || values.some((year) => !Number.isSafeInteger(year)
                || year < 1 || (projectLife !== null && year > projectLife))) {
                technoeconomicPushError(
                    errors, path,
                    `Use whole-number project years from 1 through ${projectLife || 'the project life'}.`
                );
                return [];
            }
            if (new Set(values).size !== values.length
                || values.some((year, index) => index > 0 && year <= values[index - 1])) {
                technoeconomicPushError(
                    errors, path, 'Occurrence years must be unique and strictly increasing.'
                );
            }
            return values;
        }

        function technoeconomicStandaloneReadCostCards(system = 'solaredge') {
            const systemMeta = technoeconomicPairedSystem(system);
            if (!systemMeta) return [];
            const elements = technoeconomicPairedSystemElements(system);
            const cards = [
                ...Array.from(elements.costLines?.querySelectorAll?.(
                    '[data-tea-v4-cost-line]'
                ) || []),
            ];
            if (elements.replacementEnabled?.checked === true) {
                cards.push(...Array.from(
                    elements.replacementFields?.querySelectorAll?.(
                        '[data-tea-v4-cost-line]'
                    ) || []
                ));
            }
            return cards.map((card) => ({
                key: card.dataset.teaV4CostLine,
                inputId: card.dataset.inputId,
                timing: card.dataset.timing,
                unit: card.dataset.unit,
                costCategory: card.dataset.costCategory
                    || TECHNOECONOMIC_STANDALONE_COST_COVERAGE[system][
                        card.dataset.teaV4CostLine
                    ]?.costCategory || '',
                coverageIds: technoeconomicText(card.dataset.coverageIds).split(',')
                    .map((value) => value.trim()).filter(Boolean).length
                    ? technoeconomicText(card.dataset.coverageIds).split(',')
                        .map((value) => value.trim()).filter(Boolean)
                    : [...(TECHNOECONOMIC_STANDALONE_COST_COVERAGE[system][
                        card.dataset.teaV4CostLine
                    ]?.coverageIds || [])],
                label: card.querySelector('h5')?.textContent || card.dataset.inputId,
                distribution: technoeconomicStandaloneDistributionDraft(
                    card.querySelector('[data-tea-v4-family]'), card
                ),
                occurrenceYears: card.dataset.timing === 'scheduled_year_end'
                    ? technoeconomicDomElement(
                        `technoeconomicStandalone${systemMeta.label}ReplacementYears`
                    )?.value || ''
                    : '',
            }));
        }

        function technoeconomicStandaloneSanitizeDistributionDraft(value) {
            const source = technoeconomicPlainObject(value);
            const family = TECHNOECONOMIC_DISTRIBUTION_FAMILIES.some(
                ([candidate]) => candidate === source.family
            ) ? source.family : 'fixed';
            const output = {family};
            for (const key of ['value', 'low', 'mode', 'high', 'mean', 'sd']) {
                if (source[key] !== undefined && source[key] !== null) {
                    output[key] = technoeconomicText(source[key]);
                }
            }
            return output;
        }

        function technoeconomicLifecycleEvidenceCopy(value, acceptance = null) {
            if (Array.isArray(value)) {
                return value.map((item) => technoeconomicLifecycleEvidenceCopy(
                    item, acceptance
                ));
            }
            if (!value || typeof value !== 'object') return value;
            const output = {};
            for (const [key, item] of Object.entries(value)) {
                if (key === 'explicit_acceptance' || key === 'acceptance_rationale') continue;
                output[key] = technoeconomicLifecycleEvidenceCopy(item, acceptance);
            }
            if (Object.hasOwn(output, 'evidence_class')
                && Object.hasOwn(output, 'citation') && acceptance) {
                output.explicit_acceptance = acceptance.accepted === true;
                output.acceptance_rationale = acceptance.accepted === true
                    ? acceptance.rationale : '';
            }
            return output;
        }

        function technoeconomicSanitizeLifecycleJsonDraft(value) {
            const raw = technoeconomicText(value);
            if (!raw.trim()) return '';
            try {
                return JSON.stringify(
                    technoeconomicLifecycleEvidenceCopy(JSON.parse(raw)), null, 2
                );
            } catch (_error) {
                return raw;
            }
        }

        function technoeconomicStandaloneSanitizeDraft(value) {
            const source = technoeconomicPlainObject(value);
            if (source.schema_version !== TECHNOECONOMIC_STANDALONE_DRAFT_SCHEMA_VERSION) {
                return null;
            }
            const systemDrafts = technoeconomicPlainObject(source.systems);
            const systems = {};
            for (const {key} of TECHNOECONOMIC_PAIRED_SYSTEMS) {
                const seen = new Set();
                const systemDraft = technoeconomicPlainObject(systemDrafts[key]);
                systems[key] = {
                    cost_lines: (Array.isArray(systemDraft.cost_lines)
                        ? systemDraft.cost_lines : [])
                        .filter((line) => {
                            const lineKey = technoeconomicText(line?.key);
                            if (!['Capex', 'Om', 'Replacement'].includes(lineKey)
                                || seen.has(lineKey)) return false;
                            seen.add(lineKey);
                            return true;
                        })
                        .map((line) => ({
                            key: technoeconomicText(line.key),
                            distribution: technoeconomicStandaloneSanitizeDistributionDraft(
                                line.distribution
                            ),
                            occurrence_years: technoeconomicText(line.occurrence_years),
                        })),
                    replacement_enabled: systemDraft.replacement_enabled === true,
                };
            }
            const ratingBasis = ['ac_operating_limit', 'dc_installed_nameplate'].includes(
                source.rating_basis
            ) ? source.rating_basis : 'ac_operating_limit';
            // The existing paired-draft-v3 key predates the discriminator. A
            // missing value therefore identifies a saved V5 draft, while new
            // defaults below opt into V6 explicitly.
            const calculationContract = [
                TECHNOECONOMIC_LIFECYCLE_CONTRACT_VERSION,
                TECHNOECONOMIC_PAIRED_CONTRACT_VERSION,
            ].includes(source.calculation_contract_version)
                ? source.calculation_contract_version
                : TECHNOECONOMIC_PAIRED_CONTRACT_VERSION;
            return {
                schema_version: TECHNOECONOMIC_STANDALONE_DRAFT_SCHEMA_VERSION,
                calculation_contract_version: calculationContract,
                lifecycle_json: technoeconomicSanitizeLifecycleJsonDraft(
                    source.lifecycle_json
                ),
                source_annual_job_id: technoeconomicText(source.source_annual_job_id),
                target_capacity: technoeconomicText(source.target_capacity) || '100',
                n: technoeconomicText(source.n) || '10000',
                seed: technoeconomicText(source.seed),
                project_life_years: technoeconomicText(source.project_life_years) || '30',
                rating_basis: ratingBasis,
                discount_distribution: technoeconomicStandaloneSanitizeDistributionDraft(
                    source.discount_distribution
                ),
                degradation_distribution: technoeconomicStandaloneSanitizeDistributionDraft(
                    source.degradation_distribution
                ),
                systems,
                assumption_note: technoeconomicText(source.assumption_note),
            };
        }

        function technoeconomicStandaloneDefaultDraft() {
            return technoeconomicStandaloneSanitizeDraft({
                schema_version: TECHNOECONOMIC_STANDALONE_DRAFT_SCHEMA_VERSION,
                calculation_contract_version: TECHNOECONOMIC_LIFECYCLE_CONTRACT_VERSION,
                lifecycle_json: '',
                source_annual_job_id: '', target_capacity: '100', n: '10000',
                seed: '', project_life_years: '30', rating_basis: 'ac_operating_limit',
                discount_distribution: {family: 'fixed', value: ''},
                degradation_distribution: {family: 'fixed', value: ''},
                systems: Object.fromEntries(TECHNOECONOMIC_PAIRED_SYSTEMS.map(({key}) => [key, {
                    cost_lines: technoeconomicStandaloneCostDefinitions(
                        'ac_operating_limit', key
                    ).map((line) => ({
                        key: line.key,
                        distribution: {family: 'fixed', value: line.value},
                        occurrence_years: '',
                    })),
                    replacement_enabled: false,
                }])),
                assumption_note: '',
            });
        }

        function technoeconomicStandaloneDraftSnapshot() {
            const systems = Object.fromEntries(TECHNOECONOMIC_PAIRED_SYSTEMS.map(({key}) => {
                const elements = technoeconomicPairedSystemElements(key);
                return [key, {
                    cost_lines: technoeconomicStandaloneReadCostCards(key).map((line) => ({
                        key: line.key,
                        distribution: line.distribution,
                        occurrence_years: line.occurrenceYears,
                    })),
                    replacement_enabled: elements.replacementEnabled?.checked === true,
                }];
            }));
            return technoeconomicStandaloneSanitizeDraft({
                schema_version: TECHNOECONOMIC_STANDALONE_DRAFT_SCHEMA_VERSION,
                calculation_contract_version: technoeconomicElements.calculationContract?.value,
                lifecycle_json: technoeconomicElements.lifecycleJson?.value || '',
                source_annual_job_id: technoeconomicElements.standaloneSourceSelect?.value || '',
                target_capacity: technoeconomicElements.standaloneTargetCapacityInput?.value || '',
                n: technoeconomicElements.standaloneRealizations?.value || '',
                seed: technoeconomicElements.standaloneSeed?.value || '',
                project_life_years: technoeconomicElements.standaloneProjectLife?.value || '',
                rating_basis: technoeconomicElements.standaloneSolarEdgeCostLines
                    ?.dataset?.ratingBasis,
                discount_distribution: technoeconomicStandaloneDistributionDraft(
                    technoeconomicElements.standaloneDiscountFamily,
                    technoeconomicElements.standaloneDiscountParameters
                ),
                degradation_distribution: technoeconomicStandaloneDistributionDraft(
                    technoeconomicElements.standaloneDegradationFamily,
                    technoeconomicElements.standaloneDegradationParameters
                ),
                systems,
                assumption_note: technoeconomicElements.standaloneAssumptionNote?.value || '',
            });
        }

        function technoeconomicStandaloneEnsureSourceOption(sourceId) {
            if (!sourceId) return;
            technoeconomicPendingSourceId = sourceId;
        }

        function technoeconomicStandaloneApplyDistributionDraft(
            familyElement, parameterRoot, prefix, distribution
        ) {
            if (!familyElement || !parameterRoot) return;
            const sanitized = technoeconomicStandaloneSanitizeDistributionDraft(distribution);
            familyElement.value = sanitized.family;
            parameterRoot.replaceChildren();
            technoeconomicStandaloneRenderDistributionParameters(
                parameterRoot, sanitized.family, prefix, sanitized
            );
        }

        function technoeconomicStandaloneApplyCostDraft(root, line) {
            if (!root || !line) return;
            const card = Array.from(root.querySelectorAll?.('[data-tea-v4-cost-line]') || [])
                .find((candidate) => candidate.dataset.teaV4CostLine === line.key);
            if (!card) return;
            const system = technoeconomicPairedSystem(card.dataset.teaV4System)
                || TECHNOECONOMIC_PAIRED_SYSTEMS[1];
            technoeconomicStandaloneApplyDistributionDraft(
                card.querySelector('[data-tea-v4-family]'),
                card.querySelector('.tea-v4-distribution-parameters'),
                `technoeconomicStandaloneCost${system.label}${line.key}`,
                line.distribution
            );
            if (line.key === 'Replacement') {
                const years = technoeconomicDomElement(
                    `technoeconomicStandalone${system.label}ReplacementYears`
                );
                if (years) years.value = line.occurrence_years;
            }
        }

        function technoeconomicStandaloneApplyDraft(value) {
            const draft = technoeconomicStandaloneSanitizeDraft(value);
            if (!draft || !technoeconomicElements?.standaloneResults) return false;
            technoeconomicApplyingDraft = true;
            try {
                technoeconomicStandaloneEnsureSourceOption(draft.source_annual_job_id);
                if (technoeconomicElements.standaloneSourceSelect) {
                    technoeconomicElements.standaloneSourceSelect.value =
                        draft.source_annual_job_id;
                }
                if (technoeconomicElements.calculationContract) {
                    technoeconomicElements.calculationContract.value =
                        draft.calculation_contract_version;
                }
                if (technoeconomicElements.standaloneTargetCapacityInput) {
                    technoeconomicElements.standaloneTargetCapacityInput.value =
                        draft.target_capacity;
                }
                for (const root of [
                    technoeconomicElements.standaloneSolectriaCostLines,
                    technoeconomicElements.standaloneSolarEdgeCostLines,
                ]) {
                    if (root?.dataset) root.dataset.ratingBasis = draft.rating_basis;
                }
                if (technoeconomicElements.lifecycleJson) {
                    technoeconomicElements.lifecycleJson.value = draft.lifecycle_json;
                }
                technoeconomicHydrateLifecycleTemplate(draft.lifecycle_json);
                if (technoeconomicElements.standaloneRealizations) {
                    technoeconomicElements.standaloneRealizations.value = draft.n;
                }
                if (technoeconomicElements.standaloneSeed) {
                    technoeconomicElements.standaloneSeed.value = draft.seed
                        || technoeconomicGenerateSafeSeed();
                }
                if (technoeconomicElements.standaloneCostYear) {
                    technoeconomicElements.standaloneCostYear.value = '2022';
                }
                if (technoeconomicElements.standaloneProjectLife) {
                    technoeconomicElements.standaloneProjectLife.value = draft.project_life_years;
                }
                technoeconomicStandaloneApplyDistributionDraft(
                    technoeconomicElements.standaloneDiscountFamily,
                    technoeconomicElements.standaloneDiscountParameters,
                    'technoeconomicStandaloneDiscount', draft.discount_distribution
                );
                technoeconomicStandaloneApplyDistributionDraft(
                    technoeconomicElements.standaloneDegradationFamily,
                    technoeconomicElements.standaloneDegradationParameters,
                    'technoeconomicStandaloneDegradation', draft.degradation_distribution
                );
                for (const {key} of TECHNOECONOMIC_PAIRED_SYSTEMS) {
                    const elements = technoeconomicPairedSystemElements(key);
                    const systemDraft = draft.systems[key];
                    technoeconomicStandaloneRenderCostLines(
                        key, draft.rating_basis, {forcePreset: true}
                    );
                    for (const line of systemDraft.cost_lines.filter(
                        (candidate) => candidate.key !== 'Replacement'
                    )) {
                        technoeconomicStandaloneApplyCostDraft(elements.costLines, line);
                    }
                    if (elements.replacementEnabled) {
                        elements.replacementEnabled.checked = systemDraft.replacement_enabled;
                    }
                    technoeconomicStandaloneRenderReplacement(key);
                    const replacement = systemDraft.cost_lines.find(
                        (line) => line.key === 'Replacement'
                    );
                    if (systemDraft.replacement_enabled && replacement) {
                        technoeconomicStandaloneApplyCostDraft(
                            elements.replacementFields, replacement
                        );
                    }
                }
                if (technoeconomicElements.standaloneAssumptionNote) {
                    technoeconomicElements.standaloneAssumptionNote.value = draft.assumption_note;
                }
                if (technoeconomicElements.standaloneAccept) {
                    technoeconomicElements.standaloneAccept.checked = false;
                }
            } finally {
                technoeconomicApplyingDraft = false;
            }
            technoeconomicRenderContractMode();
            technoeconomicRenderStandaloneDraft();
            return true;
        }

        function technoeconomicPersistStandaloneDraft() {
            if (!technoeconomicElements?.standaloneResults) return true;
            if (typeof localStorage !== 'object') return false;
            try {
                localStorage.setItem(
                    TECHNOECONOMIC_STANDALONE_DRAFT_STORAGE_KEY,
                    JSON.stringify(technoeconomicStandaloneDraftSnapshot())
                );
                return true;
            } catch (_error) {
                return false;
            }
        }

        function technoeconomicLoadStandaloneDraft() {
            if (typeof localStorage !== 'object') return null;
            try {
                return technoeconomicStandaloneSanitizeDraft(JSON.parse(
                    localStorage.getItem(TECHNOECONOMIC_STANDALONE_DRAFT_STORAGE_KEY) || 'null'
                ));
            } catch (_error) {
                return null;
            }
        }

        function technoeconomicClearStandaloneAcceptance(target) {
            const acceptance = technoeconomicElements.standaloneAccept;
            const assumptions = technoeconomicElements.standaloneAssumptionsDialog;
            if (technoeconomicApplyingDraft || !acceptance?.checked
                || target === acceptance || !assumptions?.contains?.(target)) return false;
            acceptance.checked = false;
            return true;
        }

        function technoeconomicSerializeStandaloneRequest(options = {}) {
            const errors = [];
            const context = {
                evidenceCount: 0, provisionalEvidenceCount: 0, nonfixedPredictorCount: 0,
            };
            const sourceId = technoeconomicStrictText(
                technoeconomicElements.standaloneSourceSelect?.value,
                'source_annual_job_id', errors, {maximum: 200}
            );
            const source = (Array.isArray(options.sources) ? options.sources : technoeconomicSources)
                .find((item) => item?.source_annual_job_id === sourceId);
            if (!source) technoeconomicPushError(
                errors, 'source_annual_job_id',
                'Refresh sources and select a verified Annual Simulation.'
            );
            else if (source.eligible !== true) technoeconomicPushError(
                errors, 'source_annual_job_id',
                source.detail || 'The selected Annual Simulation is not eligible.'
            );
            const capacities = Object.fromEntries(TECHNOECONOMIC_PAIRED_SYSTEMS.map(
                ({key}) => [key, technoeconomicStandaloneSourceCapacityInfo(source, key)]
            ));
            for (const {key, label} of TECHNOECONOMIC_PAIRED_SYSTEMS) {
                if (!capacities[key]) technoeconomicPushError(
                    errors, 'paired_commercial.target_rating_basis',
                    `The selected source has no verified ${label} applied capacity.`
                );
            }
            const ratingBases = new Set(Object.values(capacities).filter(Boolean).map(
                (capacity) => capacity.ratingBasis
            ));
            if (ratingBases.size > 1) technoeconomicPushError(
                errors, 'paired_commercial.target_rating_basis',
                'Solectria and SolarEdge must use the same AC or DC capacity basis.'
            );
            const ratingBasis = ratingBases.size === 1 ? [...ratingBases][0] : null;
            const targetCapacity = technoeconomicFiniteNumber(
                technoeconomicElements.standaloneTargetCapacityInput?.value,
                'paired_commercial.target_capacity', errors, {positive: true}
            );
            const n = technoeconomicFiniteNumber(
                technoeconomicElements.standaloneRealizations?.value, 'n', errors,
                {integer: true, min: 1, max: 100000}
            );
            let seed = null;
            const seedText = technoeconomicText(
                technoeconomicElements.standaloneSeed?.value
            ).trim();
            if (!/^\d+$/.test(seedText)) {
                technoeconomicPushError(errors, 'seed', 'Enter a nonnegative whole-number seed.');
            } else {
                try {
                    const exactSeed = BigInt(seedText);
                    if (exactSeed > BigInt(TECHNOECONOMIC_MAX_SAFE_SEED)) {
                        technoeconomicPushError(
                            errors, 'seed',
                            `Use a seed no greater than ${TECHNOECONOMIC_MAX_SAFE_SEED.toLocaleString('en-US')}.`
                        );
                    } else seed = Number(exactSeed);
                } catch (_error) {
                    technoeconomicPushError(errors, 'seed', 'The sampling seed is invalid.');
                }
            }
            const costYear = 2022;
            if (technoeconomicElements.standaloneCostYear) {
                technoeconomicElements.standaloneCostYear.value = String(costYear);
            }
            const projectLife = technoeconomicFiniteNumber(
                technoeconomicElements.standaloneProjectLife?.value,
                'finance.project_life_years', errors, {integer: true, min: 1}
            );
            const accepted = technoeconomicElements.standaloneAccept?.checked === true;
            const note = technoeconomicText(
                technoeconomicElements.standaloneAssumptionNote?.value
            ).trim();
            if (!note) technoeconomicPushError(
                errors, 'evidence.assumption_note',
                'Document the discount-rate and degradation source or justification.'
            );
            if (!accepted) technoeconomicPushError(
                errors, 'evidence.explicit_acceptance',
                'Confirm both system cost stacks, capacity scaling, benchmark limits, and financial assumptions.'
            );
            const userEvidence = technoeconomicGuidedEvidence(note, accepted, {
                seed: seedText || 'paired-draft',
                subject: 'Paired commercial Solectria and SolarEdge financial assumptions',
            });
            const discountDraft = technoeconomicStandaloneScaleDistribution(
                technoeconomicStandaloneDistributionDraft(
                    technoeconomicElements.standaloneDiscountFamily,
                    technoeconomicElements.standaloneDiscountParameters
                ), 100
            );
            const degradationDraft = technoeconomicStandaloneScaleDistribution(
                technoeconomicStandaloneDistributionDraft(
                    technoeconomicElements.standaloneDegradationFamily,
                    technoeconomicElements.standaloneDegradationParameters
                ), 100
            );
            const discount = technoeconomicSerializeDistribution(
                discountDraft, 'finance.real_discount_rate.distribution', errors,
                'discount_rate'
            );
            const degradation = technoeconomicSerializeDistribution(
                degradationDraft, 'shared_degradation.annual_rate.distribution', errors,
                'degradation'
            );
            if (discount.nonfixed) context.nonfixedPredictorCount += 1;
            if (degradation.nonfixed) context.nonfixedPredictorCount += 1;
            const userEvidencePayload = technoeconomicSerializeEvidence(
                userEvidence, 'finance.real_discount_rate.evidence', errors, context
            );
            const degradationEvidencePayload = technoeconomicSerializeEvidence(
                userEvidence, 'shared_degradation.annual_rate.evidence', errors, context
            );
            const projectLifeUsesAtb = costYear === 2022 && projectLife === 30;
            const projectEvidence = projectLifeUsesAtb
                ? technoeconomicStandaloneNrelEvidence(
                    'NREL 2024 ATB utility-scale PV financial lifetime',
                    'The interface uses the ATB 30-year utility-scale PV financial lifetime.',
                    accepted,
                    note
                ) : userEvidence;
            const projectEvidencePayload = technoeconomicSerializeEvidence(
                projectEvidence, 'finance.project_life_evidence', errors, context
            );
            const preset = ratingBasis
                ? TECHNOECONOMIC_STANDALONE_ATB_PRESETS[ratingBasis] : null;
            const pairedSystems = TECHNOECONOMIC_PAIRED_SYSTEMS.map(
                ({key, label}, systemIndex) => {
                    const systemPath = `paired_commercial.systems.${systemIndex}`;
                    const systemRationale = capacities[key]
                        ? `Divide verified ${label} annual energy by its frozen ${
                            technoeconomicRatingBasisLabel(capacities[key].ratingBasis)
                        }, then multiply by the same-rated target capacity.`
                        : `A verified ${label} source capacity is required.`;
                    const systemEvidence = technoeconomicSerializeEvidence(
                        technoeconomicStandaloneSourceEvidence(
                            source, accepted, systemRationale
                        ), `${systemPath}.evidence`, errors, context
                    );
                    const costLines = technoeconomicStandaloneReadCostCards(key).map(
                        (line, lineIndex) => {
                            const linePath = `${systemPath}.cost_lines.${lineIndex}`;
                            const kernelDistribution =
                                technoeconomicStandaloneKernelCostDistribution(line);
                            const distribution = technoeconomicSerializeDistribution(
                                kernelDistribution, `${linePath}.distribution`, errors, 'cost'
                            );
                            if (distribution.nonfixed) context.nonfixedPredictorCount += 1;
                            const occurrenceYears = line.timing === 'scheduled_year_end'
                                ? technoeconomicStandaloneParseYears(
                                    line.occurrenceYears, `${linePath}.occurrence_years`,
                                    errors, projectLife
                                ) : [];
                            const expected = line.key === 'Capex' ? preset?.capex
                                : line.key === 'Om' ? preset?.om : null;
                            const isAtbPreset = expected !== null && expected !== undefined
                                && line.distribution.family === 'fixed'
                                && Number(line.distribution.value) === Number(expected)
                                && costYear === 2022;
                            const evidence = isAtbPreset
                                ? technoeconomicStandaloneNrelEvidence(
                                    `NREL 2024 ATB utility-scale PV ${
                                        line.key === 'Capex' ? 'CAPEX' : 'O&M'
                                    } benchmark for ${label}`,
                                    `${line.label}: ${expected} ${line.key === 'Om'
                                        ? `USD/kW${technoeconomicStandaloneRatingSuffix(ratingBasis)}-year`
                                        : `USD/${ratingBasis === 'dc_installed_nameplate' ? 'Wdc' : 'Wac'}`
                                    } in real 2022 USD; generic utility-scale benchmark, not a vendor quote.`,
                                    accepted, note
                                ) : userEvidence;
                            const evidencePayload = technoeconomicSerializeEvidence(
                                evidence, `${linePath}.evidence`, errors, context
                            );
                            return {
                                input_id: line.inputId,
                                label: line.label,
                                cost_category: line.costCategory,
                                coverage_ids: line.coverageIds,
                                constant_dollar_cost_year: Number(costYear),
                                timing: line.timing,
                                unit: line.unit,
                                distribution: distribution.payload,
                                occurrence_years: occurrenceYears,
                                evidence: evidencePayload,
                            };
                        }
                    );
                    if (!costLines.some((line) => line.timing === 'initial_t0')) {
                        technoeconomicPushError(
                            errors, `${systemPath}.cost_lines`,
                            `Add an initial ${label} cost line.`
                        );
                    }
                    if (!costLines.some((line) => line.timing === 'annual_year_end')) {
                        technoeconomicPushError(
                            errors, `${systemPath}.cost_lines`,
                            `Add an annual ${label} cost line.`
                        );
                    }
                    return {technology: key, evidence: systemEvidence, cost_lines: costLines};
                }
            );
            const transferRationale = ratingBasis
                ? `Scale verified Solectria and SolarEdge energy from each system's frozen ${
                    technoeconomicRatingBasisLabel(ratingBasis)
                } to one same-rated target capacity.`
                : 'Verified Solectria and SolarEdge source capacities are required.';
            const transferEvidence = technoeconomicSerializeEvidence(
                technoeconomicStandaloneSourceEvidence(source, accepted, transferRationale),
                'paired_commercial.evidence', errors, context
            );
            const payload = {
                source_annual_job_id: sourceId,
                basis: 'solartac_site',
                capacity_normalization: TECHNOECONOMIC_APPLIED_CAPACITY_NORMALIZATION,
                n,
                seed,
                cost_stack_completeness: 'full_system',
                cost_lines: [],
                finance: {
                    treatment_key: 'constant-real-v1',
                    constant_dollar_cost_year: costYear,
                    project_life_years: projectLife,
                    project_life_evidence: projectEvidencePayload,
                    real_discount_rate: {
                        unit: 'real_fraction_per_year',
                        distribution: discount.payload,
                        evidence: userEvidencePayload,
                    },
                },
                shared_degradation: {
                    degradation_model: 'shared_module_v1',
                    annual_rate: {
                        unit: 'real_fraction_per_year',
                        distribution: degradation.payload,
                        evidence: degradationEvidencePayload,
                    },
                },
                paired_commercial: {
                    target_capacity: targetCapacity,
                    target_capacity_unit: 'mw',
                    target_rating_basis: ratingBasis,
                    transfer_method: 'direct_capacity_scaling',
                    transfer_rationale: transferRationale,
                    evidence: transferEvidence,
                    systems: pairedSystems,
                },
            };
            return {
                payload,
                errors,
                valid: errors.length === 0,
                evidenceCount: context.evidenceCount,
                provisionalEvidenceCount: context.provisionalEvidenceCount,
                nonfixedPredictorCount: context.nonfixedPredictorCount,
            };
        }

        function technoeconomicSelectedContractVersion() {
            const selected = technoeconomicElements?.calculationContract?.value;
            return selected === TECHNOECONOMIC_PAIRED_CONTRACT_VERSION
                ? TECHNOECONOMIC_PAIRED_CONTRACT_VERSION
                : TECHNOECONOMIC_LIFECYCLE_CONTRACT_VERSION;
        }

        function technoeconomicLifecycleTemplateControls() {
            return [
                'lifecycleSourceBasis', 'lifecycleReliabilityMode',
                'lifecycleElectricityValue', 'lifecycleElectricityGrowth',
                'lifecycleNpvTolerance', 'lifecycleSolectriaDegradation',
                'lifecycleSolarEdgeDegradation', 'lifecycleSolectriaAvailability',
                'lifecycleSolarEdgeAvailability', 'lifecycleSolectriaInitialCost',
                'lifecycleSolarEdgeInitialCost', 'lifecycleSolectriaBaseOm',
                'lifecycleSolarEdgeBaseOm', 'lifecycleSolectriaDecommissioning',
                'lifecycleSolarEdgeDecommissioning', 'lifecycleSolectriaSalvage',
                'lifecycleSolarEdgeSalvage', 'lifecycleCommonProbability',
                'lifecycleCommonDowntime', 'lifecycleCommonImpact',
                'lifecycleCommonCost',
            ].map((key) => technoeconomicElements?.[key]).filter(Boolean);
        }

        function technoeconomicSetLifecycleTemplateStatus(state, title, detail) {
            if (technoeconomicElements?.lifecycleTemplateStatusPanel) {
                technoeconomicElements.lifecycleTemplateStatusPanel.dataset.state = state;
            }
            if (technoeconomicElements?.lifecycleTemplateStatus) {
                technoeconomicElements.lifecycleTemplateStatus.textContent = title;
            }
            if (technoeconomicElements?.lifecycleTemplateStatusDetail) {
                technoeconomicElements.lifecycleTemplateStatusDetail.textContent = detail;
            }
        }

        function technoeconomicSetLifecycleTemplateButtonMode(applied) {
            if (!technoeconomicElements?.useLifecycleTemplateButton) return;
            const button = technoeconomicElements.useLifecycleTemplateButton;
            button.textContent = applied
                ? 'Reset to approved template values'
                : 'Use approved template values';
            const statusPanel = technoeconomicElements.lifecycleTemplateStatusPanel;
            const heading = statusPanel?.parentElement?.querySelector?.(
                '.tea-v6-template-heading'
            );
            if (applied && typeof statusPanel?.appendChild === 'function'
                && button.parentElement !== statusPanel) {
                statusPanel.appendChild(button);
            } else if (!applied && typeof heading?.appendChild === 'function'
                && button.parentElement !== heading) {
                heading.appendChild(button);
            }
        }

        function technoeconomicSetLifecycleTemplateControlsEnabled(enabled) {
            for (const control of technoeconomicLifecycleTemplateControls()) {
                control.disabled = !enabled;
            }
        }

        function technoeconomicLifecycleTemplateRatingBasis() {
            const source = technoeconomicStandaloneSelectedSource();
            const ratingBases = new Set(TECHNOECONOMIC_PAIRED_SYSTEMS.map(({key}) => (
                technoeconomicStandaloneSourceCapacityInfo(source, key)?.ratingBasis
            )).filter(Boolean));
            if (ratingBases.size === 1) return [...ratingBases][0];
            const renderedBasis = technoeconomicElements?.standaloneSolarEdgeCostLines
                ?.dataset?.ratingBasis;
            return ['ac_operating_limit', 'dc_installed_nameplate'].includes(renderedBasis)
                ? renderedBasis : 'ac_operating_limit';
        }

        function technoeconomicRenderLifecycleTemplateCostBasis(ratingBasis) {
            const suffix = ratingBasis === 'dc_installed_nameplate' ? 'dc' : 'ac';
            if (technoeconomicElements?.lifecycleInitialCostUnit) {
                technoeconomicElements.lifecycleInitialCostUnit.textContent =
                    `real 2022 USD/W${suffix}`;
            }
            if (technoeconomicElements?.lifecycleBaseOmUnit) {
                technoeconomicElements.lifecycleBaseOmUnit.textContent =
                    `real 2022 USD/kW${suffix}-year`;
            }
        }

        function technoeconomicResetLifecycleTemplateFields() {
            technoeconomicLifecycleTemplateModified = false;
            for (const [key, value] of Object.entries(
                TECHNOECONOMIC_LIFECYCLE_TEMPLATE_DEFAULTS
            )) {
                if (technoeconomicElements?.[key]) {
                    technoeconomicElements[key].value = value;
                }
            }
            const ratingBasis = technoeconomicLifecycleTemplateRatingBasis();
            const preset = TECHNOECONOMIC_STANDALONE_ATB_PRESETS[ratingBasis]
                || TECHNOECONOMIC_STANDALONE_ATB_PRESETS.ac_operating_limit;
            for (const key of [
                'lifecycleSolectriaInitialCost', 'lifecycleSolarEdgeInitialCost',
            ]) {
                if (technoeconomicElements?.[key]) technoeconomicElements[key].value = preset.capex;
            }
            for (const key of [
                'lifecycleSolectriaBaseOm', 'lifecycleSolarEdgeBaseOm',
            ]) {
                if (technoeconomicElements?.[key]) technoeconomicElements[key].value = preset.om;
            }
            technoeconomicRenderLifecycleTemplateCostBasis(ratingBasis);
        }

        function technoeconomicLifecycleTemplateNumber(
            key, label, errors, {minimum = null, maximum = null, divisor = 1} = {}
        ) {
            const control = technoeconomicElements?.[key];
            const raw = technoeconomicText(control?.value).trim();
            const number = raw ? Number(raw) : Number.NaN;
            const invalid = !raw || !Number.isFinite(number)
                || (minimum !== null && number < minimum)
                || (maximum !== null && number > maximum);
            const range = minimum !== null && maximum !== null
                ? `between ${minimum} and ${maximum}`
                : minimum !== null ? `at least ${minimum}`
                    : maximum !== null ? `no greater than ${maximum}` : 'a finite number';
            const message = invalid
                ? `${label} must be ${range}.`
                : '';
            control?.setCustomValidity?.(message);
            if (invalid) {
                errors.push(message);
                return null;
            }
            return number / divisor;
        }

        function technoeconomicLifecycleTemplateEvidence(label) {
            return {
                evidence_class: 'engineering_judgment',
                citation: {
                    title: 'TEA v6 provisional lifecycle planning template v1',
                    organization: 'Application-provided TEA template',
                    url: null,
                    stable_reference: TECHNOECONOMIC_LIFECYCLE_TEMPLATE_REFERENCE,
                    publication_or_as_of_date: '2026-09-03',
                    accessed_date: '2026-09-03',
                    excerpt_or_derivation_note:
                        `${label}. User-selected neutral planning value derived from the `
                        + 'synthetic TEA v6 review fixture; it is not vendor evidence and must be '
                        + 'accepted by the analyst for this run or replaced with project evidence.'
                        + (technoeconomicLifecycleTemplateModified
                            ? ' [analyst-modified] One or more editable planning values differ from the template defaults.'
                            : ''),
                    preservation_mode: 'metadata_excerpt_only',
                    user_supplied_content_sha256: null,
                    metadata_only_rationale:
                        'The versioned provisional template is embedded in the dashboard and has no separate evidence file.',
                },
                explicit_acceptance: null,
                acceptance_rationale: null,
            };
        }

        function technoeconomicLifecycleTemplateDocumented(value, unit, label, evidence = null) {
            return {
                unit,
                distribution: {family: 'fixed', value},
                evidence: evidence || technoeconomicLifecycleTemplateEvidence(label),
            };
        }

        function technoeconomicLifecycleTemplateNrelEvidence(subject, note) {
            const evidence = technoeconomicStandaloneNrelEvidence(subject, note);
            evidence.citation.user_supplied_content_sha256 = null;
            evidence.explicit_acceptance = null;
            evidence.acceptance_rationale = null;
            return evidence;
        }

        function technoeconomicLifecycleTemplateComponent(
            technology, componentKey, count, capacityImpact
        ) {
            const prefix = `template.${technology}.${componentKey}`;
            const componentA = componentKey === 'component-a';
            const label = componentA
                ? 'Generic 100-kW power-electronics equivalent'
                : 'Generic 1-MW balance-of-system equivalent';
            const spareTarget = Math.max(1, Math.ceil(count * 0.01));
            const documented = (value, unit, field, evidence = null) => (
                technoeconomicLifecycleTemplateDocumented(
                    value, unit, `${label}: ${field}`, evidence
                )
            );
            return {
                component_id: componentA
                    ? 'template-power-electronics-100kw'
                    : 'template-balance-of-system-1mw',
                category: componentA
                    ? 'power-electronics-equivalent' : 'balance-of-system-equivalent',
                count,
                capacity_impact: capacityImpact,
                weibull_beta: documented(componentA ? 1.5 : 2.5, 'dimensionless', 'Weibull beta'),
                weibull_eta_years: documented(componentA ? 15 : 30, 'years', 'Weibull eta'),
                repair_hours: documented(componentA ? 8 : 24, 'hours', 'repair time'),
                logistics_hours: documented(componentA ? 72 : 168, 'hours', 'logistics time'),
                emergency_unit_cost: documented(
                    componentA ? 15750 : 52500, 'constant_usd', 'emergency hardware cost'
                ),
                restock_unit_cost: documented(
                    componentA ? 15000 : 50000, 'constant_usd', 'stock replenishment cost'
                ),
                labor_cost: documented(
                    componentA ? 1000 : 5000, 'constant_usd', 'labor cost per failure'
                ),
                mobilization_cost: documented(
                    componentA ? 500 : 2000, 'constant_usd', 'mobilization cost per batch'
                ),
                real_cost_growth: documented(0, 'real_fraction_per_year', 'real cost growth'),
                batch_size: componentA ? 5 : 1,
                initial_spares: spareTarget,
                spare_target: spareTarget,
                warranty: {
                    age_limit_years: componentA ? 10 : 5,
                    fraction: componentA ? 0.8 : 0.5,
                    covered_cost_categories: ['hardware'],
                    coverage_ids: [`${prefix}.warranty`],
                    evidence: technoeconomicLifecycleTemplateEvidence(`${label}: warranty scope`),
                },
                preventive_replacements: [],
                coverage_ids: [`${prefix}.corrective-and-availability`],
                evidence: technoeconomicLifecycleTemplateEvidence(`${label}: target BOM entry`),
            };
        }

        function technoeconomicLifecycleTemplateSystem(
            technology, values, targetMw, componentCounts, ratingBasis
        ) {
            const label = technology === 'solectria' ? 'Solectria' : 'SolarEdge';
            const prefix = `template.${technology}`;
            const preset = TECHNOECONOMIC_STANDALONE_ATB_PRESETS[ratingBasis]
                || TECHNOECONOMIC_STANDALONE_ATB_PRESETS.ac_operating_limit;
            const usesNrelCapex = Math.abs(Number(values.initialCost) - Number(preset.capex))
                <= 1e-12;
            const usesNrelOm = Math.abs(Number(values.baseOm) - Number(preset.om) / 1000)
                <= 1e-12;
            const documented = (value, unit, field, evidence = null) => (
                technoeconomicLifecycleTemplateDocumented(
                    value, unit, `${label}: ${field}`, evidence
                )
            );
            return {
                technology,
                degradation: documented(
                    values.degradation, 'real_fraction_per_year', 'annual degradation'
                ),
                base_availability: documented(
                    values.availability, 'dimensionless_fraction', 'base availability'
                ),
                base_om_cost_per_w_year: documented(
                    values.baseOm, 'constant_usd_per_target_w_year', 'base O&M',
                    usesNrelOm
                        ? technoeconomicLifecycleTemplateNrelEvidence(
                            `NREL 2024 ATB utility-scale PV O&M benchmark for ${label}`,
                            `${label} uses the rating-basis-specific generic ATB O&M preset in real 2022 USD; not a vendor quote.`
                        )
                        : technoeconomicLifecycleTemplateEvidence(
                            `${label}: analyst-edited base O&M; no longer the NREL ATB preset`
                        )
                ),
                base_om_real_growth: documented(
                    0, 'real_fraction_per_year', 'base O&M real growth'
                ),
                initial_cost_lines: [{
                    input_id: `${prefix}.initial-installed-cost`,
                    label: `${label} initial installed cost`,
                    cost_per_w: documented(
                        values.initialCost, 'constant_usd_per_target_w',
                        'initial installed cost',
                        usesNrelCapex
                            ? technoeconomicLifecycleTemplateNrelEvidence(
                                `NREL 2024 ATB utility-scale PV CAPEX benchmark for ${label}`,
                                `${label} uses the rating-basis-specific generic ATB CAPEX preset in real 2022 USD; not a vendor quote.`
                            )
                            : technoeconomicLifecycleTemplateEvidence(
                                `${label}: analyst-edited initial cost; no longer the NREL ATB preset`
                            )
                    ),
                    coverage_ids: [`${prefix}.initial-system`],
                    evidence: technoeconomicLifecycleTemplateEvidence(
                        `${label}: initial installed-cost coverage`
                    ),
                }],
                scheduled_costs: [],
                components: [
                    technoeconomicLifecycleTemplateComponent(
                        technology, 'component-a', componentCounts.componentA,
                        Math.min(1, 0.1 / targetMw)
                    ),
                    technoeconomicLifecycleTemplateComponent(
                        technology, 'component-b', componentCounts.componentB,
                        Math.min(1, 1 / targetMw)
                    ),
                ],
                decommissioning_cost: documented(
                    values.decommissioning, 'constant_usd', 'decommissioning cost'
                ),
                salvage_value: documented(values.salvage, 'constant_usd', 'salvage value'),
                source_availability_by_year: [],
                base_om_coverage_ids: [`${prefix}.base-om`],
                evidence: technoeconomicLifecycleTemplateEvidence(
                    `${label}: neutral lifecycle system template`
                ),
            };
        }

        function technoeconomicBuildLifecycleTemplate() {
            const errors = [];
            const number = (key, label, options) => (
                technoeconomicLifecycleTemplateNumber(key, label, errors, options)
            );
            const targetMw = Number(technoeconomicElements?.standaloneTargetCapacityInput?.value);
            if (!Number.isFinite(targetMw) || targetMw <= 0) {
                errors.push('Target capacity must be greater than zero before applying the template.');
            }
            const electricityValue = number(
                'lifecycleElectricityValue', 'Electricity value', {minimum: 0}
            );
            const electricityGrowth = number(
                'lifecycleElectricityGrowth', 'Electricity-value growth',
                {minimum: -99.99, divisor: 100}
            );
            const tolerance = number(
                'lifecycleNpvTolerance', 'NPV tie tolerance', {minimum: 0.000001}
            );
            const systemValues = {};
            for (const {key, label} of TECHNOECONOMIC_PAIRED_SYSTEMS) {
                const elementPrefix = key === 'solectria' ? 'Solectria' : 'SolarEdge';
                systemValues[key] = {
                    degradation: number(
                        `lifecycle${elementPrefix}Degradation`, `${label} degradation`,
                        {minimum: 0, maximum: 99.99, divisor: 100}
                    ),
                    availability: number(
                        `lifecycle${elementPrefix}Availability`, `${label} availability`,
                        {minimum: 0.01, maximum: 100, divisor: 100}
                    ),
                    initialCost: number(
                        `lifecycle${elementPrefix}InitialCost`, `${label} initial cost`,
                        {minimum: 0}
                    ),
                    baseOm: number(
                        `lifecycle${elementPrefix}BaseOm`, `${label} base O&M`,
                        {minimum: 0, divisor: 1000}
                    ),
                    decommissioning: number(
                        `lifecycle${elementPrefix}Decommissioning`,
                        `${label} decommissioning cost`, {minimum: 0}
                    ),
                    salvage: number(
                        `lifecycle${elementPrefix}Salvage`, `${label} salvage value`,
                        {minimum: 0}
                    ),
                };
            }
            const commonProbability = number(
                'lifecycleCommonProbability', 'Common-event probability',
                {minimum: 0, maximum: 100, divisor: 100}
            );
            const commonDowntime = number(
                'lifecycleCommonDowntime', 'Common-event downtime', {minimum: 0}
            );
            const commonImpact = number(
                'lifecycleCommonImpact', 'Common-event capacity impact',
                {minimum: 0.01, maximum: 100, divisor: 100}
            );
            const commonCost = number(
                'lifecycleCommonCost', 'Common-event cost', {minimum: 0}
            );
            if (errors.length) return {lifecycle: null, errors};
            const componentCounts = {
                componentA: Math.max(1, Math.ceil(targetMw * 10)),
                componentB: Math.max(1, Math.ceil(targetMw)),
            };
            const ratingBasis = technoeconomicLifecycleTemplateRatingBasis();
            const lifecycle = {
                weather_path_method: TECHNOECONOMIC_LIFECYCLE_WEATHER_METHOD,
                source_energy_basis: technoeconomicElements?.lifecycleSourceBasis?.value
                    || 'gross',
                reliability_mode: technoeconomicElements?.lifecycleReliabilityMode?.value
                    || 'event',
                electricity_value: technoeconomicLifecycleTemplateDocumented(
                    electricityValue, 'constant_usd_per_kwh_ac', 'Year-one electricity value'
                ),
                electricity_value_real_growth: technoeconomicLifecycleTemplateDocumented(
                    electricityGrowth, 'real_fraction_per_year',
                    'Electricity-value real growth'
                ),
                systems: TECHNOECONOMIC_PAIRED_SYSTEMS.map(({key}) => (
                    technoeconomicLifecycleTemplateSystem(
                        key, systemValues[key], targetMw, componentCounts, ratingBasis
                    )
                )),
                common_cause_events: [{
                    event_id: 'shared-site-event',
                    annual_probability: technoeconomicLifecycleTemplateDocumented(
                        commonProbability, 'dimensionless_fraction',
                        'Shared site-event annual probability'
                    ),
                    downtime_hours: technoeconomicLifecycleTemplateDocumented(
                        commonDowntime, 'hours', 'Shared site-event downtime'
                    ),
                    capacity_impact: commonImpact,
                    cost_per_event: technoeconomicLifecycleTemplateDocumented(
                        commonCost, 'constant_usd', 'Shared site-event cost'
                    ),
                    real_cost_growth: technoeconomicLifecycleTemplateDocumented(
                        0, 'real_fraction_per_year', 'Shared site-event real cost growth'
                    ),
                    affected_systems: ['solectria', 'solaredge'],
                    coverage_ids: ['template.shared.site-event'],
                    evidence: technoeconomicLifecycleTemplateEvidence(
                        'Shared site-event affecting both systems'
                    ),
                }],
                decision_probability_threshold: 0.75,
                decision_npv_tolerance_usd_per_target_w: tolerance,
            };
            return {lifecycle, errors: []};
        }

        function technoeconomicRenderLifecycleTemplateScaling() {
            const targetMwValue = Number(
                technoeconomicElements?.standaloneTargetCapacityInput?.value
            );
            const targetMw = Number.isFinite(targetMwValue) && targetMwValue > 0
                ? targetMwValue : 100;
            const countA = Math.max(1, Math.ceil(targetMw * 10));
            const countB = Math.max(1, Math.ceil(targetMw));
            const spareA = Math.max(1, Math.ceil(countA * 0.01));
            const spareB = Math.max(1, Math.ceil(countB * 0.01));
            if (technoeconomicElements?.lifecycleComponentACount) {
                technoeconomicElements.lifecycleComponentACount.textContent =
                    countA.toLocaleString('en-US');
            }
            if (technoeconomicElements?.lifecycleComponentBCount) {
                technoeconomicElements.lifecycleComponentBCount.textContent =
                    countB.toLocaleString('en-US');
            }
            if (technoeconomicElements?.lifecycleComponentAImpact) {
                technoeconomicElements.lifecycleComponentAImpact.textContent =
                    `${technoeconomicFormatNumber(Math.min(1, 0.1 / targetMw) * 100, 4)}% capacity/unit`;
            }
            if (technoeconomicElements?.lifecycleComponentBImpact) {
                technoeconomicElements.lifecycleComponentBImpact.textContent =
                    `${technoeconomicFormatNumber(Math.min(1, 1 / targetMw) * 100, 4)}% capacity/unit`;
            }
            if (technoeconomicElements?.lifecycleComponentASpares) {
                technoeconomicElements.lifecycleComponentASpares.textContent =
                    `${spareA.toLocaleString('en-US')} ${spareA === 1 ? 'unit' : 'units'}`;
            }
            if (technoeconomicElements?.lifecycleComponentBSpares) {
                technoeconomicElements.lifecycleComponentBSpares.textContent =
                    `${spareB.toLocaleString('en-US')} ${spareB === 1 ? 'unit' : 'units'}`;
            }
            if (technoeconomicElements?.lifecycleScalingNote) {
                const targetKw = targetMw * 1000;
                technoeconomicElements.lifecycleScalingNote.textContent =
                    `At the ${technoeconomicFormatNumber(targetMw, 4)} MW target: `
                    + `ceil(${technoeconomicFormatNumber(targetKw, 2)} kW ÷ 100 kW) `
                    + `and ceil(${technoeconomicFormatNumber(targetKw, 2)} kW ÷ 1,000 kW). `
                    + 'No scheduled costs or preventive replacements are included; base O&M '
                    + 'and corrective-cost growth are 0% real.';
            }
            return {countA, countB, spareA, spareB};
        }

        function technoeconomicSyncLifecycleTemplate() {
            technoeconomicRenderLifecycleTemplateScaling();
            const built = technoeconomicBuildLifecycleTemplate();
            if (!built.lifecycle) {
                if (technoeconomicElements?.lifecycleJson) {
                    technoeconomicElements.lifecycleJson.value = '';
                }
                technoeconomicSetLifecycleTemplateStatus(
                    'invalid', 'Complete the highlighted template value',
                    built.errors[0] || 'One or more template values are incomplete.'
                );
                return false;
            }
            if (technoeconomicElements?.lifecycleJson) {
                technoeconomicElements.lifecycleJson.value = JSON.stringify(
                    built.lifecycle, null, 2
                );
            }
            technoeconomicLifecycleEntryMode = 'template';
            technoeconomicSetLifecycleTemplateControlsEnabled(true);
            technoeconomicSetLifecycleTemplateButtonMode(true);
            const counts = technoeconomicRenderLifecycleTemplateScaling();
            const discount = technoeconomicStandaloneDistributionDraft(
                technoeconomicElements?.standaloneDiscountFamily,
                technoeconomicElements?.standaloneDiscountParameters
            );
            technoeconomicSetLifecycleTemplateStatus(
                'applied', technoeconomicLifecycleTemplateModified
                    ? 'Modified provisional template values applied'
                    : 'Provisional template values applied',
                `Review and confirm below. Each system uses ${counts.countA.toLocaleString('en-US')} `
                + `generic 100-kW equivalents and ${counts.countB.toLocaleString('en-US')} `
                + `generic 1-MW equivalents; ${technoeconomicLifecycleTemplateModified
                    ? 'edited and unedited reliability values' : 'all reliability values'} `
                + `remain visibly provisional. Real discount rate: ${
                    technoeconomicStandaloneDistributionDisplay(discount)
                }%.`
            );
            return true;
        }

        function technoeconomicEnsureLifecycleTemplateDiscount() {
            const draft = technoeconomicStandaloneDistributionDraft(
                technoeconomicElements?.standaloneDiscountFamily,
                technoeconomicElements?.standaloneDiscountParameters
            );
            const hasValue = Object.entries(draft).some(([key, value]) => (
                key !== 'family' && technoeconomicText(value).trim()
            ));
            if (hasValue) return false;
            technoeconomicStandaloneApplyDistributionDraft(
                technoeconomicElements?.standaloneDiscountFamily,
                technoeconomicElements?.standaloneDiscountParameters,
                'technoeconomicStandaloneDiscount',
                {family: 'fixed', value: '5'}
            );
            return true;
        }

        function technoeconomicApplyLifecycleTemplate() {
            technoeconomicResetLifecycleTemplateFields();
            technoeconomicEnsureLifecycleTemplateDiscount();
            if (!technoeconomicSyncLifecycleTemplate()) return false;
            if (technoeconomicElements?.lifecycleAdvancedDetails) {
                technoeconomicElements.lifecycleAdvancedDetails.open = false;
            }
            if (technoeconomicElements?.standaloneAccept) {
                technoeconomicElements.standaloneAccept.checked = false;
            }
            technoeconomicRenderStandaloneDraft();
            technoeconomicMarkDraftChanged('Provisional lifecycle template applied.');
            return true;
        }

        function technoeconomicLifecycleTemplateFixedValue(value) {
            const distribution = technoeconomicPlainObject(value?.distribution);
            return distribution.family === 'fixed' && Number.isFinite(Number(distribution.value))
                ? Number(distribution.value) : null;
        }

        function technoeconomicLifecycleTemplateComparable(value, parentKey = '') {
            if (Array.isArray(value)) {
                const result = value.map((item) => (
                    technoeconomicLifecycleTemplateComparable(item, parentKey)
                ));
                if (parentKey === 'systems') {
                    result.sort((left, right) => technoeconomicText(left?.technology)
                        .localeCompare(technoeconomicText(right?.technology)));
                } else if (parentKey === 'components') {
                    result.sort((left, right) => technoeconomicText(left?.component_id)
                        .localeCompare(technoeconomicText(right?.component_id)));
                } else if (['affected_systems', 'coverage_ids',
                    'covered_cost_categories'].includes(parentKey)) {
                    result.sort((left, right) => technoeconomicText(left)
                        .localeCompare(technoeconomicText(right)));
                }
                return result;
            }
            if (!value || typeof value !== 'object') return value;
            if (parentKey === 'evidence') {
                return {
                    evidence_class: technoeconomicText(value.evidence_class),
                    organization: technoeconomicText(value?.citation?.organization),
                    stable_reference: technoeconomicText(value?.citation?.stable_reference),
                    url: technoeconomicText(value?.citation?.url),
                    preservation_mode: technoeconomicText(value?.citation?.preservation_mode),
                };
            }
            return Object.fromEntries(Object.keys(value).sort().map((key) => [
                key, technoeconomicLifecycleTemplateComparable(value[key], key),
            ]));
        }

        function technoeconomicLifecycleTemplateExpectedValues() {
            const preset = TECHNOECONOMIC_STANDALONE_ATB_PRESETS[
                technoeconomicLifecycleTemplateRatingBasis()
            ] || TECHNOECONOMIC_STANDALONE_ATB_PRESETS.ac_operating_limit;
            return {
                ...TECHNOECONOMIC_LIFECYCLE_TEMPLATE_DEFAULTS,
                lifecycleSolectriaInitialCost: preset.capex,
                lifecycleSolarEdgeInitialCost: preset.capex,
                lifecycleSolectriaBaseOm: preset.om,
                lifecycleSolarEdgeBaseOm: preset.om,
            };
        }

        function technoeconomicLifecycleTemplateDifferences() {
            const labels = {
                lifecycleSourceBasis: 'Source energy basis',
                lifecycleReliabilityMode: 'Reliability calculation',
                lifecycleElectricityValue: 'Electricity value',
                lifecycleElectricityGrowth: 'Electricity-value real growth',
                lifecycleNpvTolerance: 'Decision NPV tolerance',
                lifecycleSolectriaDegradation: 'Solectria annual degradation',
                lifecycleSolarEdgeDegradation: 'SolarEdge annual degradation',
                lifecycleSolectriaAvailability: 'Solectria base availability',
                lifecycleSolarEdgeAvailability: 'SolarEdge base availability',
                lifecycleSolectriaInitialCost: 'Solectria initial installed cost',
                lifecycleSolarEdgeInitialCost: 'SolarEdge initial installed cost',
                lifecycleSolectriaBaseOm: 'Solectria base O&M',
                lifecycleSolarEdgeBaseOm: 'SolarEdge base O&M',
                lifecycleSolectriaDecommissioning: 'Solectria decommissioning cost',
                lifecycleSolarEdgeDecommissioning: 'SolarEdge decommissioning cost',
                lifecycleSolectriaSalvage: 'Solectria salvage value',
                lifecycleSolarEdgeSalvage: 'SolarEdge salvage value',
                lifecycleCommonProbability: 'Shared-event annual probability',
                lifecycleCommonDowntime: 'Shared-event downtime',
                lifecycleCommonImpact: 'Shared-event capacity impact',
                lifecycleCommonCost: 'Shared-event cost',
            };
            return Object.entries(technoeconomicLifecycleTemplateExpectedValues()).flatMap(
                ([key, expected]) => {
                const actual = technoeconomicText(technoeconomicElements?.[key]?.value).trim();
                const actualNumber = Number(actual);
                const expectedNumber = Number(expected);
                let differs;
                if (actual && Number.isFinite(actualNumber) && Number.isFinite(expectedNumber)) {
                    differs = Math.abs(actualNumber - expectedNumber) > 1e-12;
                } else {
                    differs = actual !== technoeconomicText(expected);
                }
                return differs
                    ? [`${labels[key] || key}: ${actual || 'Not entered'} (template ${expected})`]
                    : [];
                }
            );
        }

        function technoeconomicLifecycleTemplateVisibleValuesModified() {
            return technoeconomicLifecycleTemplateDifferences().length > 0;
        }

        function technoeconomicLifecycleMatchesTemplateShape(lifecycle) {
            const targetMw = Number(
                technoeconomicElements?.standaloneTargetCapacityInput?.value
            );
            if (!lifecycle || !Number.isFinite(targetMw) || targetMw <= 0
                || lifecycle.weather_path_method !== TECHNOECONOMIC_LIFECYCLE_WEATHER_METHOD
                || lifecycle.source_energy_basis !== 'gross'
                || lifecycle.reliability_mode !== 'event') return false;
            const systems = Array.isArray(lifecycle.systems) ? lifecycle.systems : [];
            if (systems.length !== 2 || new Set(
                systems.map((system) => system?.technology)
            ).size !== 2) return false;
            const events = Array.isArray(lifecycle.common_cause_events)
                ? lifecycle.common_cause_events : [];
            if (events.length !== 1) return false;
            const fixed = technoeconomicLifecycleTemplateFixedValue;
            const editableValues = {
                electricityValue: fixed(lifecycle.electricity_value),
                electricityGrowth: fixed(lifecycle.electricity_value_real_growth),
                tolerance: Number(lifecycle.decision_npv_tolerance_usd_per_target_w),
                commonProbability: fixed(events[0].annual_probability),
                commonDowntime: fixed(events[0].downtime_hours),
                commonImpact: Number(events[0].capacity_impact),
                commonCost: fixed(events[0].cost_per_event),
            };
            if (Object.values(editableValues).some((value) => !Number.isFinite(value))) {
                return false;
            }
            const componentCounts = {
                componentA: Math.max(1, Math.ceil(targetMw * 10)),
                componentB: Math.max(1, Math.ceil(targetMw)),
            };
            const ratingBasis = technoeconomicLifecycleTemplateRatingBasis();
            const expectedSystems = [];
            for (const {key} of TECHNOECONOMIC_PAIRED_SYSTEMS) {
                const system = systems.find((candidate) => candidate?.technology === key);
                if (!system) return false;
                const values = {
                    degradation: fixed(system.degradation),
                    availability: fixed(system.base_availability),
                    initialCost: fixed(system.initial_cost_lines?.[0]?.cost_per_w),
                    baseOm: fixed(system.base_om_cost_per_w_year),
                    decommissioning: fixed(system.decommissioning_cost),
                    salvage: fixed(system.salvage_value),
                };
                if (Object.values(values).some((value) => !Number.isFinite(value))) {
                    return false;
                }
                expectedSystems.push(technoeconomicLifecycleTemplateSystem(
                    key, values, targetMw, componentCounts, ratingBasis
                ));
            }
            const expected = {
                weather_path_method: TECHNOECONOMIC_LIFECYCLE_WEATHER_METHOD,
                source_energy_basis: 'gross',
                reliability_mode: 'event',
                electricity_value: technoeconomicLifecycleTemplateDocumented(
                    editableValues.electricityValue, 'constant_usd_per_kwh_ac',
                    'Year-one electricity value'
                ),
                electricity_value_real_growth: technoeconomicLifecycleTemplateDocumented(
                    editableValues.electricityGrowth, 'real_fraction_per_year',
                    'Electricity-value real growth'
                ),
                systems: expectedSystems,
                common_cause_events: [{
                    event_id: 'shared-site-event',
                    annual_probability: technoeconomicLifecycleTemplateDocumented(
                        editableValues.commonProbability, 'dimensionless_fraction',
                        'Shared site-event annual probability'
                    ),
                    downtime_hours: technoeconomicLifecycleTemplateDocumented(
                        editableValues.commonDowntime, 'hours',
                        'Shared site-event downtime'
                    ),
                    capacity_impact: editableValues.commonImpact,
                    cost_per_event: technoeconomicLifecycleTemplateDocumented(
                        editableValues.commonCost, 'constant_usd',
                        'Shared site-event cost'
                    ),
                    real_cost_growth: technoeconomicLifecycleTemplateDocumented(
                        0, 'real_fraction_per_year', 'Shared site-event real cost growth'
                    ),
                    affected_systems: ['solectria', 'solaredge'],
                    coverage_ids: ['template.shared.site-event'],
                    evidence: technoeconomicLifecycleTemplateEvidence(
                        'Shared site-event affecting both systems'
                    ),
                }],
                decision_probability_threshold: 0.75,
                decision_npv_tolerance_usd_per_target_w: editableValues.tolerance,
            };
            return JSON.stringify(technoeconomicLifecycleTemplateComparable(lifecycle))
                === JSON.stringify(technoeconomicLifecycleTemplateComparable(expected));
        }

        function technoeconomicHydrateLifecycleTemplate(raw) {
            technoeconomicRenderLifecycleTemplateScaling();
            const text = technoeconomicText(raw).trim();
            if (!text) {
                technoeconomicLifecycleEntryMode = 'empty';
                technoeconomicSetLifecycleTemplateControlsEnabled(false);
                technoeconomicSetLifecycleTemplateButtonMode(false);
                technoeconomicRenderLifecycleTemplateCostBasis(
                    technoeconomicLifecycleTemplateRatingBasis()
                );
                technoeconomicSetLifecycleTemplateStatus(
                    'ready', 'Ready to apply',
                    'The values shown are provisional planning assumptions. Select “Use approved template values,” review them, and provide the confirmation below.'
                );
                return false;
            }
            let lifecycle;
            try {
                lifecycle = JSON.parse(text);
            } catch (_error) {
                technoeconomicLifecycleEntryMode = 'advanced';
                technoeconomicSetLifecycleTemplateControlsEnabled(false);
                technoeconomicSetLifecycleTemplateButtonMode(false);
                technoeconomicSetLifecycleTemplateStatus(
                    'invalid', 'Custom lifecycle data needs attention',
                    'Open the Advanced section and correct the technical lifecycle data.'
                );
                return false;
            }
            if (!technoeconomicLifecycleMatchesTemplateShape(lifecycle)) {
                technoeconomicLifecycleEntryMode = 'advanced';
                technoeconomicSetLifecycleTemplateControlsEnabled(false);
                technoeconomicSetLifecycleTemplateButtonMode(false);
                technoeconomicSetLifecycleTemplateStatus(
                    'custom', 'Custom lifecycle specification loaded',
                    'The calculation will use the data in the Advanced section, not the versioned provisional template shown above.'
                );
                return true;
            }
            const setValue = (key, value, multiplier = 1) => {
                if (technoeconomicElements?.[key] && Number.isFinite(value)) {
                    technoeconomicElements[key].value = String(value * multiplier);
                }
            };
            if (technoeconomicElements?.lifecycleSourceBasis) {
                technoeconomicElements.lifecycleSourceBasis.value =
                    lifecycle.source_energy_basis || 'gross';
            }
            if (technoeconomicElements?.lifecycleReliabilityMode) {
                technoeconomicElements.lifecycleReliabilityMode.value =
                    lifecycle.reliability_mode || 'event';
            }
            setValue(
                'lifecycleElectricityValue',
                technoeconomicLifecycleTemplateFixedValue(lifecycle.electricity_value)
            );
            setValue(
                'lifecycleElectricityGrowth',
                technoeconomicLifecycleTemplateFixedValue(
                    lifecycle.electricity_value_real_growth
                ), 100
            );
            setValue(
                'lifecycleNpvTolerance',
                Number(lifecycle.decision_npv_tolerance_usd_per_target_w)
            );
            for (const system of Array.isArray(lifecycle.systems) ? lifecycle.systems : []) {
                const elementPrefix = system?.technology === 'solectria'
                    ? 'Solectria' : system?.technology === 'solaredge' ? 'SolarEdge' : '';
                if (!elementPrefix) continue;
                setValue(
                    `lifecycle${elementPrefix}Degradation`,
                    technoeconomicLifecycleTemplateFixedValue(system.degradation), 100
                );
                setValue(
                    `lifecycle${elementPrefix}Availability`,
                    technoeconomicLifecycleTemplateFixedValue(system.base_availability), 100
                );
                setValue(
                    `lifecycle${elementPrefix}InitialCost`,
                    technoeconomicLifecycleTemplateFixedValue(system.initial_cost_lines?.[0]?.cost_per_w)
                );
                setValue(
                    `lifecycle${elementPrefix}BaseOm`,
                    technoeconomicLifecycleTemplateFixedValue(system.base_om_cost_per_w_year),
                    1000
                );
                setValue(
                    `lifecycle${elementPrefix}Decommissioning`,
                    technoeconomicLifecycleTemplateFixedValue(system.decommissioning_cost)
                );
                setValue(
                    `lifecycle${elementPrefix}Salvage`,
                    technoeconomicLifecycleTemplateFixedValue(system.salvage_value)
                );
            }
            const commonEvent = Array.isArray(lifecycle.common_cause_events)
                ? lifecycle.common_cause_events[0] : null;
            if (commonEvent) {
                setValue(
                    'lifecycleCommonProbability',
                    technoeconomicLifecycleTemplateFixedValue(commonEvent.annual_probability), 100
                );
                setValue(
                    'lifecycleCommonDowntime',
                    technoeconomicLifecycleTemplateFixedValue(commonEvent.downtime_hours)
                );
                setValue('lifecycleCommonImpact', Number(commonEvent.capacity_impact), 100);
                setValue(
                    'lifecycleCommonCost',
                    technoeconomicLifecycleTemplateFixedValue(commonEvent.cost_per_event)
                );
            }
            technoeconomicLifecycleTemplateModified = text.includes('[analyst-modified]')
                || technoeconomicLifecycleTemplateVisibleValuesModified();
            technoeconomicLifecycleEntryMode = 'template';
            technoeconomicSetLifecycleTemplateControlsEnabled(true);
            technoeconomicSetLifecycleTemplateButtonMode(true);
            technoeconomicRenderLifecycleTemplateCostBasis(
                technoeconomicLifecycleTemplateRatingBasis()
            );
            technoeconomicRenderLifecycleTemplateScaling();
            technoeconomicSetLifecycleTemplateStatus(
                'applied', technoeconomicLifecycleTemplateModified
                    ? 'Modified provisional template values restored'
                    : 'Provisional template values restored',
                'These saved planning values will be prepared automatically. Review them and confirm again before calculation.'
            );
            return true;
        }

        function technoeconomicHandleLifecycleTemplateInput(target) {
            if (target === technoeconomicElements?.lifecycleJson) {
                technoeconomicHydrateLifecycleTemplate(target.value);
                return;
            }
            const guided = technoeconomicLifecycleTemplateControls().includes(target);
            const capacity = target === technoeconomicElements?.standaloneTargetCapacityInput;
            if (!guided && !capacity) return;
            technoeconomicRenderLifecycleTemplateScaling();
            if (technoeconomicLifecycleEntryMode === 'template') {
                technoeconomicLifecycleTemplateModified = true;
                technoeconomicSyncLifecycleTemplate();
                return;
            }
            if (guided) {
                technoeconomicSetLifecycleTemplateStatus(
                    'ready', 'Template values changed but not yet applied',
                    'Select “Use approved template values” to reset to the approved set, or open Advanced to use custom technical data.'
                );
            }
        }

        function technoeconomicRenderContractMode() {
            const lifecycle = technoeconomicSelectedContractVersion()
                === TECHNOECONOMIC_LIFECYCLE_CONTRACT_VERSION;
            if (technoeconomicElements?.lifecycleInputGroup) {
                technoeconomicElements.lifecycleInputGroup.hidden = !lifecycle;
            }
            if (technoeconomicElements?.legacyDegradationRow) {
                technoeconomicElements.legacyDegradationRow.hidden = lifecycle;
            }
            if (technoeconomicElements?.legacyCostGroup) {
                technoeconomicElements.legacyCostGroup.hidden = lifecycle;
            }
            if (technoeconomicElements?.legacyFormulaPanel) {
                technoeconomicElements.legacyFormulaPanel.hidden = lifecycle;
            }
            if (technoeconomicElements?.lifecycleJson) {
                // The Advanced editor is optional. Readiness is enforced by the
                // generated lifecycle object, not browser validation on a closed disclosure.
                technoeconomicElements.lifecycleJson.required = false;
                technoeconomicElements.lifecycleJson.setAttribute?.(
                    'aria-required', 'false'
                );
            }
            if (technoeconomicElements?.standaloneSubmitButton) {
                technoeconomicElements.standaloneSubmitButton.textContent = lifecycle
                    ? 'Calculate upgrade NPV' : 'Calculate LCOE';
            }
            if (technoeconomicElements?.standaloneAssumptionsReviewButton) {
                technoeconomicElements.standaloneAssumptionsReviewButton.textContent = lifecycle
                    ? 'Review lifecycle analysis' : 'Review paired LCOE';
            }
            if (lifecycle) {
                if (technoeconomicLifecycleEntryMode === 'empty') {
                    technoeconomicHydrateLifecycleTemplate(
                        technoeconomicElements?.lifecycleJson?.value || ''
                    );
                }
                void technoeconomicLoadFormulaRegistry();
            }
        }

        function technoeconomicFormulaRegistryText(value) {
            if (Array.isArray(value)) return value.map(String).join('; ');
            if (value === null || value === undefined) return '';
            return String(value);
        }

        function technoeconomicRenderFormulaRegistry(payload) {
            const formulas = Array.isArray(payload?.formulas) ? payload.formulas : [];
            if (technoeconomicElements?.formulaRegistryStatus) {
                technoeconomicElements.formulaRegistryStatus.textContent =
                    `${payload.formula_registry_version} · ${formulas.length} formulas`;
            }
            if (technoeconomicElements?.formulaRegistryHash) {
                technoeconomicElements.formulaRegistryHash.textContent =
                    `Kernel registry SHA-256: ${payload.formula_registry_sha256}`;
            }
            const body = technoeconomicElements?.formulaRegistryBody;
            if (!body) return;
            body.replaceChildren();
            for (const formula of formulas) {
                const row = technoeconomicNode('tr');
                row.append(
                    technoeconomicNode('th', {
                        scope: 'row',
                        text: technoeconomicFormulaRegistryText(formula.formula_id),
                    }),
                    technoeconomicNode('td', {
                        text: technoeconomicFormulaRegistryText(formula.equation),
                    }),
                    technoeconomicNode('td', {
                        text: technoeconomicFormulaRegistryText(formula.units),
                    }),
                    technoeconomicNode('td', {
                        text: technoeconomicFormulaRegistryText(formula.guards),
                    })
                );
                body.appendChild(row);
            }
        }

        async function technoeconomicLoadFormulaRegistry() {
            if (technoeconomicFormulaRegistryPayload) {
                technoeconomicRenderFormulaRegistry(technoeconomicFormulaRegistryPayload);
                return technoeconomicFormulaRegistryPayload;
            }
            if (technoeconomicFormulaRegistryPromise) {
                return technoeconomicFormulaRegistryPromise;
            }
            if (technoeconomicElements?.formulaRegistryStatus) {
                technoeconomicElements.formulaRegistryStatus.textContent =
                    'Loading the v6 formula catalog…';
            }
            technoeconomicFormulaRegistryPromise = (async () => {
                try {
                    const payload = await technoeconomicFetchJson(
                        '/api/technoeconomic/formulas/v6'
                    );
                    const formulas = Array.isArray(payload?.formulas) ? payload.formulas : [];
                    const declaredCount = Number(payload?.formula_registry_count);
                    if (payload?.calculation_contract_version
                            !== TECHNOECONOMIC_LIFECYCLE_CONTRACT_VERSION
                        || payload?.formula_registry_version !== 'tea-formulas-v6'
                        || !Number.isInteger(declaredCount)
                        || declaredCount !== formulas.length
                        || !/^[a-f0-9]{64}$/i.test(
                            technoeconomicText(payload?.formula_registry_sha256)
                        )) {
                        throw new Error('The server returned an invalid v6 formula registry.');
                    }
                    technoeconomicFormulaRegistryPayload = payload;
                    technoeconomicRenderFormulaRegistry(payload);
                    return payload;
                } catch (error) {
                    if (technoeconomicElements?.formulaRegistryStatus) {
                        technoeconomicElements.formulaRegistryStatus.textContent =
                            'Formula catalog unavailable';
                    }
                    if (technoeconomicElements?.formulaRegistryHash) {
                        technoeconomicElements.formulaRegistryHash.textContent =
                            technoeconomicText(error?.message)
                            || 'The v6 formula registry could not be verified.';
                    }
                    return null;
                } finally {
                    technoeconomicFormulaRegistryPromise = null;
                }
            })();
            return technoeconomicFormulaRegistryPromise;
        }

        function technoeconomicLifecycleUnsafeKey(value) {
            if (Array.isArray(value)) return value.some(technoeconomicLifecycleUnsafeKey);
            if (!value || typeof value !== 'object') return false;
            return Object.keys(value).some((key) => (
                ['__proto__', 'prototype', 'constructor'].includes(key)
                || technoeconomicLifecycleUnsafeKey(value[key])
            ));
        }

        function technoeconomicParseLifecycleSpecification(errors) {
            const raw = technoeconomicText(technoeconomicElements?.lifecycleJson?.value).trim();
            if (!raw) {
                technoeconomicPushError(
                    errors, 'Lifecycle setup',
                    'Select “Use approved template values,” or provide a complete custom specification under Advanced.'
                );
                return null;
            }
            let lifecycle;
            try {
                lifecycle = JSON.parse(raw);
            } catch (error) {
                technoeconomicPushError(
                    errors, 'paired_commercial.lifecycle',
                    `The Advanced lifecycle data could not be read: ${error?.message || 'parse failed'}.`
                );
                return null;
            }
            if (!lifecycle || Array.isArray(lifecycle) || typeof lifecycle !== 'object') {
                technoeconomicPushError(
                    errors, 'paired_commercial.lifecycle',
                    'Advanced lifecycle data must contain one complete specification.'
                );
                return null;
            }
            if (technoeconomicLifecycleUnsafeKey(lifecycle)) {
                technoeconomicPushError(
                    errors, 'paired_commercial.lifecycle',
                    'Advanced lifecycle data contains a prohibited object key.'
                );
                return null;
            }
            if (!['gross', 'net'].includes(lifecycle.source_energy_basis)) {
                technoeconomicPushError(
                    errors, 'paired_commercial.lifecycle.source_energy_basis',
                    'Choose gross or net source energy.'
                );
            }
            if (!['event', 'expected'].includes(lifecycle.reliability_mode)) {
                technoeconomicPushError(
                    errors, 'paired_commercial.lifecycle.reliability_mode',
                    'Choose event or expected reliability mode.'
                );
            }
            const tolerance = Number(lifecycle.decision_npv_tolerance_usd_per_target_w);
            if (!Number.isFinite(tolerance) || tolerance <= 0) {
                technoeconomicPushError(
                    errors, 'paired_commercial.lifecycle.decision_npv_tolerance_usd_per_target_w',
                    'Enter a positive economic NPV decision tolerance in USD per target W.'
                );
            }
            const systems = Array.isArray(lifecycle.systems) ? lifecycle.systems : [];
            const technologies = systems.map((system) => system?.technology).sort();
            if (technologies.length !== 2
                || technologies[0] !== 'solaredge'
                || technologies[1] !== 'solectria') {
                technoeconomicPushError(
                    errors, 'paired_commercial.lifecycle.systems',
                    'Provide exactly one Solectria and one SolarEdge lifecycle system.'
                );
            }
            systems.forEach((system, index) => {
                if (!Array.isArray(system?.components) || system.components.length === 0) {
                    technoeconomicPushError(
                        errors, `paired_commercial.lifecycle.systems.${index}.components`,
                        'An explicit evidenced target BOM with at least one component is required.'
                    );
                }
            });
            const acceptedLifecycle = technoeconomicLifecycleEvidenceCopy(lifecycle, {
                accepted: technoeconomicElements?.standaloneAccept?.checked === true,
                rationale: technoeconomicText(
                    technoeconomicElements?.standaloneAssumptionNote?.value
                ).trim(),
            });
            return {
                ...acceptedLifecycle,
                weather_path_method: TECHNOECONOMIC_LIFECYCLE_WEATHER_METHOD,
                decision_probability_threshold: 0.75,
                decision_npv_tolerance_usd_per_target_w: tolerance,
            };
        }

        function technoeconomicLifecycleSpecificationStats(value) {
            const stats = {
                evidenceCount: 0,
                provisionalEvidenceCount: 0,
                nonfixedPredictorCount: 0,
            };
            const visit = (item) => {
                if (Array.isArray(item)) {
                    item.forEach(visit);
                    return;
                }
                if (!item || typeof item !== 'object') return;
                if (Object.hasOwn(item, 'evidence_class')
                    && Object.hasOwn(item, 'citation')) {
                    stats.evidenceCount += 1;
                    if (['engineering_judgment', 'secondary_synthesis'].includes(
                        item.evidence_class
                    )) stats.provisionalEvidenceCount += 1;
                }
                if (Object.hasOwn(item, 'unit')
                    && item.distribution && typeof item.distribution === 'object'
                    && item.distribution.family !== 'fixed') {
                    stats.nonfixedPredictorCount += 1;
                }
                Object.values(item).forEach(visit);
            };
            visit(value);
            return stats;
        }

        function technoeconomicV6IgnoresLegacyOnlyError(error) {
            const path = technoeconomicText(error?.path);
            return path === 'shared_degradation'
                || path.startsWith('shared_degradation.')
                || /^paired_commercial\.systems\.\d+\.cost_lines(?:\.|$)/.test(path);
        }

        function technoeconomicSerializeLifecycleRequest(options = {}) {
            const serialized = technoeconomicSerializeStandaloneRequest(options);
            const errors = serialized.errors.filter(
                (error) => !technoeconomicV6IgnoresLegacyOnlyError(error)
            );
            const lifecycle = technoeconomicParseLifecycleSpecification(errors);
            const payload = JSON.parse(JSON.stringify(serialized.payload));
            payload.calculation_contract_version =
                TECHNOECONOMIC_LIFECYCLE_CONTRACT_VERSION;
            delete payload.shared_degradation;
            if (payload.paired_commercial) {
                payload.paired_commercial.lifecycle = lifecycle;
                for (const system of payload.paired_commercial.systems || []) {
                    system.cost_lines = [];
                }
            }
            const stats = lifecycle
                ? technoeconomicLifecycleSpecificationStats(lifecycle)
                : {
                    evidenceCount: 0,
                    provisionalEvidenceCount: 0,
                    nonfixedPredictorCount: 0,
                };
            return {
                ...serialized,
                payload,
                errors,
                valid: errors.length === 0 && lifecycle !== null,
                ...stats,
            };
        }

        function technoeconomicSerializeCurrentRequest(options = {}) {
            if (technoeconomicSelectedContractVersion()
                === TECHNOECONOMIC_LIFECYCLE_CONTRACT_VERSION) {
                return technoeconomicSerializeLifecycleRequest(options);
            }
            return technoeconomicSerializeStandaloneRequest(options);
        }

        function technoeconomicStandaloneAppendDefinition(root, term, description) {
            if (!root) return;
            const row = technoeconomicNode('div');
            row.append(
                technoeconomicNode('dt', {text: term}),
                technoeconomicNode('dd', {text: description})
            );
            root.appendChild(row);
        }

        function technoeconomicStandaloneScaleText(source, targetWatts) {
            const target = Number(targetWatts);
            if (!Number.isFinite(target) || target <= 0) return 'Enter a target';
            const capacities = TECHNOECONOMIC_PAIRED_SYSTEMS.map(({key, label}) => ({
                key, label, capacity: technoeconomicStandaloneSourceCapacityInfo(source, key),
            }));
            if (capacities.some((item) => !item.capacity)) return 'Select a frozen Annual source';
            const first = capacities[0].capacity;
            const sameCapacity = capacities.every((item) =>
                item.capacity.watts === first.watts
                && item.capacity.ratingBasis === first.ratingBasis
            );
            const targetText = technoeconomicStandaloneFormatCapacity(
                target, first.ratingBasis, {forceMw: true}
            );
            if (sameCapacity) {
                return `${technoeconomicStandaloneFormatCapacity(
                    first.watts, first.ratingBasis
                )} to ${targetText} (${technoeconomicFormatNumber(
                    target / first.watts, 4
                )}x)`;
            }
            return capacities.map(({label, capacity}) => `${label} ${
                technoeconomicStandaloneFormatCapacity(capacity.watts, capacity.ratingBasis)
            } to ${technoeconomicStandaloneFormatCapacity(
                target, capacity.ratingBasis, {forceMw: true}
            )} (${technoeconomicFormatNumber(target / capacity.watts, 4)}x)`).join('; ');
        }

        function technoeconomicRenderStandaloneBridge(source, result = null, options = {}) {
            const capacities = Object.fromEntries(TECHNOECONOMIC_PAIRED_SYSTEMS.map(
                ({key}) => [key, technoeconomicStandaloneSourceCapacityInfo(source, key)]
            ));
            const availableCapacities = Object.values(capacities).filter(Boolean);
            const ratingBases = new Set(availableCapacities.map((item) => item.ratingBasis));
            const ratingBasis = ratingBases.size === 1 ? [...ratingBases][0] : null;
            const targetMw = Number(technoeconomicElements.standaloneTargetCapacityInput?.value);
            const targetWatts = Number.isFinite(targetMw) && targetMw > 0
                ? targetMw * 1000000 : null;
            const suffix = technoeconomicStandaloneRatingSuffix(ratingBasis);
            const targetUnit = suffix ? `MW${suffix}` : 'MW';
            if (technoeconomicElements.standaloneTargetCapacityUnit) {
                technoeconomicElements.standaloneTargetCapacityUnit.textContent = targetUnit;
            }
            if (technoeconomicElements.standaloneTargetCapacity) {
                technoeconomicElements.standaloneTargetCapacity.textContent = targetWatts
                    ? technoeconomicStandaloneFormatCapacity(
                        targetWatts, ratingBasis, {forceMw: true}
                    ) : `100 ${targetUnit}`;
            }
            const completeSource = source && TECHNOECONOMIC_PAIRED_SYSTEMS.every(
                ({key}) => capacities[key]
            ) && ratingBasis;
            if (!completeSource) {
                if (technoeconomicElements.standaloneBridgeStatus) {
                    technoeconomicElements.standaloneBridgeStatus.textContent = 'Select a source';
                }
                if (technoeconomicElements.standaloneSourceVerification) {
                    technoeconomicElements.standaloneSourceVerification.textContent =
                        'Choose a verified Annual Simulation';
                }
                if (technoeconomicElements.standaloneSourceYears) {
                    technoeconomicElements.standaloneSourceYears.textContent =
                        'Weather-year sample unavailable';
                }
                for (const {key} of TECHNOECONOMIC_PAIRED_SYSTEMS) {
                    const elements = technoeconomicPairedSystemElements(key);
                    for (const element of [
                        elements.sourceCapacity, elements.sourceEnergy,
                        elements.specificEnergy, elements.targetEnergy,
                    ]) if (element) element.textContent = 'Unavailable';
                }
                return;
            }
            if (options.preserveCostLines !== true) {
                for (const {key} of TECHNOECONOMIC_PAIRED_SYSTEMS) {
                    const costRoot = technoeconomicPairedSystemElements(key).costLines;
                    if (costRoot && costRoot.dataset.ratingBasis !== ratingBasis) {
                        technoeconomicStandaloneRenderCostLines(
                            key, ratingBasis, {forcePreset: true}
                        );
                    }
                }
            }
            const years = Array.isArray(source.eligible_years) ? source.eligible_years : [];
            if (technoeconomicElements.standaloneBridgeStatus) {
                technoeconomicElements.standaloneBridgeStatus.textContent =
                    source.eligible === true ? 'Verified source' : 'Source unavailable';
            }
            if (technoeconomicElements.standaloneSourceVerification) {
                technoeconomicElements.standaloneSourceVerification.textContent =
                    source.eligible === true ? 'Verified Annual Simulation source'
                        : 'Annual source is not eligible';
            }
            if (technoeconomicElements.standaloneSourceYears) {
                technoeconomicElements.standaloneSourceYears.textContent = years.length
                    ? `${years.join(', ')} (${years.length} weather years)`
                    : 'Weather-year sample unavailable';
            }
            for (const {key} of TECHNOECONOMIC_PAIRED_SYSTEMS) {
                const capacity = capacities[key];
                const elements = technoeconomicPairedSystemElements(key);
                const energies = technoeconomicAnnualEnergies(source, key).sort(
                    (left, right) => left - right
                );
                const capacityText = technoeconomicStandaloneFormatCapacity(
                    capacity.watts, capacity.ratingBasis
                );
                const energyText = energies.length
                    ? `${technoeconomicFormatNumber(energies[0], 0)}–${
                        technoeconomicFormatNumber(energies.at(-1), 0)
                    } kWh/year` : 'Unavailable';
                const specificLow = energies.length
                    ? energies[0] / (capacity.watts / 1000) : null;
                const specificHigh = energies.length
                    ? energies.at(-1) / (capacity.watts / 1000) : null;
                const specificText = specificLow !== null
                    ? `${technoeconomicFormatNumber(specificLow, 0)}–${
                        technoeconomicFormatNumber(specificHigh, 0)
                    } kWh/kW${suffix}-year` : 'Unavailable';
                let targetEnergyText = specificLow !== null && targetWatts
                    ? `${technoeconomicFormatNumber(
                        specificLow * targetWatts / 1000000000, 2
                    )}–${technoeconomicFormatNumber(
                        specificHigh * targetWatts / 1000000000, 2
                    )} GWh/year` : 'Unavailable';
                const resultSummary = technoeconomicStandaloneMetricSummary(
                    result, TECHNOECONOMIC_PAIRED_METRICS[key].year1Energy
                );
                const resultPercentiles = technoeconomicPlainObject(resultSummary.percentiles);
                if (resultSummary.status === 'available'
                    && Number.isFinite(Number(resultPercentiles.p10))
                    && Number.isFinite(Number(resultPercentiles.p90))) {
                    targetEnergyText = `${technoeconomicFormatNumber(
                        Number(resultPercentiles.p10) / 1000000, 2
                    )}–${technoeconomicFormatNumber(
                        Number(resultPercentiles.p90) / 1000000, 2
                    )} GWh/year (P10–P90)`;
                }
                if (elements.sourceCapacity) elements.sourceCapacity.textContent = capacityText;
                if (elements.sourceEnergy) elements.sourceEnergy.textContent = energyText;
                if (elements.specificEnergy) elements.specificEnergy.textContent = specificText;
                if (elements.targetEnergy) elements.targetEnergy.textContent = targetEnergyText;
            }
            if (technoeconomicElements.standaloneSourceBasis) {
                const authority = ratingBasis === 'ac_operating_limit'
                    ? 'enabled clipping/curtailment limit'
                    : "each system's verified installed DC nameplate fallback";
                technoeconomicElements.standaloneSourceBasis.textContent =
                    `Frozen source scale: ${technoeconomicStandaloneScaleText(
                        source, targetWatts
                    )}. Basis: ${authority}.`;
            }
        }

        function technoeconomicRenderStandaloneDraft() {
            const source = technoeconomicStandaloneSelectedSource();
            technoeconomicRenderStandaloneBridge(source);
            const root = technoeconomicElements.standaloneScenarioSummary;
            if (!root) return;
            const capacity = technoeconomicStandaloneSourceCapacityInfo(source, 'solaredge');
            const targetMw = Number(technoeconomicElements.standaloneTargetCapacityInput?.value);
            const projectLife = technoeconomicElements.standaloneProjectLife?.value || '30';
            const costYear = '2022';
            const discountDraft = technoeconomicStandaloneDistributionDraft(
                technoeconomicElements.standaloneDiscountFamily,
                technoeconomicElements.standaloneDiscountParameters
            );
            root.replaceChildren();
            technoeconomicStandaloneAppendDefinition(
                root, 'Target capacity', Number.isFinite(targetMw) && targetMw > 0
                    ? `${technoeconomicFormatNumber(targetMw, 4)} MW${
                        technoeconomicStandaloneRatingSuffix(capacity?.ratingBasis)
                    }` : 'Enter a target'
            );
            technoeconomicStandaloneAppendDefinition(
                root, 'Frozen source scale', technoeconomicStandaloneScaleText(
                    source, Number.isFinite(targetMw) && targetMw > 0
                        ? targetMw * 1000000 : null
                )
            );
            technoeconomicStandaloneAppendDefinition(root, 'Project life', `${projectLife} years`);
            technoeconomicStandaloneAppendDefinition(
                root, 'Systems', 'Solectria and SolarEdge'
            );
            technoeconomicStandaloneAppendDefinition(root, 'Currency', `USD (real ${costYear})`);
            const discountHasValue = Object.values(discountDraft).some(
                (value, index) => index > 0 && technoeconomicText(value).trim()
            );
            technoeconomicStandaloneAppendDefinition(
                root, 'Discount rate (real)', discountHasValue
                    ? `${technoeconomicStandaloneDistributionDisplay(discountDraft)}%`
                    : 'Enter an evidenced real rate'
            );
            if (technoeconomicElements?.standaloneAssumptionsDialog?.open) {
                technoeconomicBuilderUpdate();
            }
        }

        function technoeconomicStandaloneMetricSummary(result, metricName) {
            return technoeconomicPlainObject(
                technoeconomicPlainObject(result?.summaries)[metricName]
            );
        }

        function technoeconomicStandalonePercentile(summary, key) {
            const value = technoeconomicPlainObject(summary.percentiles)[key];
            const number = technoeconomicStandaloneOptionalNumber(value);
            return summary.status === 'available' ? number : null;
        }

        function technoeconomicStandaloneOptionalNumber(value) {
            if (value === null || value === undefined) return null;
            if (typeof value === 'string' && !value.trim()) return null;
            const number = Number(value);
            return Number.isFinite(number) ? number : null;
        }

        function technoeconomicStandaloneFormatLcoePerMwh(value) {
            const number = technoeconomicStandaloneOptionalNumber(value);
            return number !== null
                ? `${technoeconomicFormatNumber(number * 1000, 1)} USD/MWh`
                : 'Unavailable';
        }

        function technoeconomicStandaloneFormatLcoeTableValue(value) {
            const number = technoeconomicStandaloneOptionalNumber(value);
            return number !== null
                ? technoeconomicFormatNumber(number * 1000, 1)
                : 'Unavailable';
        }

        function technoeconomicStandaloneFormatUsd(value, suffix = '') {
            const number = technoeconomicStandaloneOptionalNumber(value);
            if (number === null) return 'Unavailable';
            const formatted = number.toLocaleString('en-US', {
                style: 'currency', currency: 'USD', maximumFractionDigits: 0,
            });
            return `${formatted}${suffix}`;
        }

        function technoeconomicStandaloneAggregateLinePercentile(lines, timing, key) {
            const matching = (Array.isArray(lines) ? lines : []).filter(
                (line) => line?.timing === timing
            );
            if (!matching.length) return null;
            const values = matching.map((line) =>
                technoeconomicStandaloneOptionalNumber(line?.percentiles?.[key])
            );
            if (values.some((value) => value === null)) return null;
            return values.reduce((total, value) => total + value, 0);
        }

        function technoeconomicSetStandaloneResultPresentation(kind) {
            const lifecycle = kind === 'lifecycle';
            const standalone = kind === 'standalone';
            if (technoeconomicElements.standaloneResults) {
                technoeconomicElements.standaloneResults.dataset.presentation = kind;
            }
            if (technoeconomicElements.legacyPercentilePanel) {
                technoeconomicElements.legacyPercentilePanel.hidden = lifecycle;
            }
            if (technoeconomicElements.v6DecisionPanel) {
                technoeconomicElements.v6DecisionPanel.hidden = !lifecycle;
            }
            if (technoeconomicElements.legacyFormulaPanel) {
                technoeconomicElements.legacyFormulaPanel.hidden = lifecycle;
            }
            if (technoeconomicElements.standaloneResultEyebrow) {
                technoeconomicElements.standaloneResultEyebrow.textContent = lifecycle
                    ? 'Result: upgrade NPV decision'
                    : standalone
                        ? 'Result: standalone commercial LCOE CDF'
                        : 'Result: paired commercial LCOE CDF';
            }
            if (technoeconomicElements.standaloneResultsHeading) {
                technoeconomicElements.standaloneResultsHeading.textContent = lifecycle
                    ? 'SolarEdge upgrade relative to Solectria'
                    : standalone ? 'SolarEdge LCOE' : 'Solectria and SolarEdge LCOE';
            }
            if (technoeconomicElements.standaloneCdfCaption) {
                technoeconomicElements.standaloneCdfCaption.textContent = lifecycle
                    ? 'The curves show the probability that modeled lifecycle LCOE is at or below each real-USD value for Solectria and SolarEdge.'
                    : 'The curve shows the probability that modeled LCOE is at or below each real-USD value.';
            }
            if (technoeconomicElements.standaloneCdfPlot) {
                technoeconomicElements.standaloneCdfPlot.alt = lifecycle
                    ? 'Empirical cumulative distributions of modeled Solectria and SolarEdge lifecycle LCOE'
                    : standalone
                        ? 'Empirical cumulative distribution of modeled commercial SolarEdge lifecycle LCOE'
                        : 'Empirical cumulative distributions of modeled commercial Solectria and SolarEdge lifecycle LCOE';
            }
        }

        function technoeconomicRenderStandaloneScenario(job, result) {
            const request = technoeconomicPlainObject(job?.request);
            const standaloneRequest = technoeconomicPlainObject(request.standalone_commercial);
            const pairedRequest = technoeconomicPlainObject(request.paired_commercial);
            const standaloneResult = technoeconomicPlainObject(result.standalone_commercial);
            const pairedResult = technoeconomicPlainObject(result.paired_commercial);
            const commercialRequest = Object.keys(pairedRequest).length
                ? pairedRequest : standaloneRequest;
            const commercialResult = Object.keys(pairedResult).length
                ? pairedResult : standaloneResult;
            const paired = Object.keys(pairedRequest).length > 0
                || result.calculation_contract_version === TECHNOECONOMIC_PAIRED_CONTRACT_VERSION;
            const root = technoeconomicElements.standaloneScenarioSummary;
            if (root) {
                root.replaceChildren();
                const targetWatts = Number(
                    commercialResult.target_capacity_w
                        ?? (Number(commercialRequest.target_capacity)
                            * (commercialRequest.target_capacity_unit === 'mw' ? 1000000 : 1000))
                );
                const ratingBasis = commercialResult.target_rating_basis
                    || commercialRequest.target_rating_basis;
                technoeconomicStandaloneAppendDefinition(
                    root, 'Target capacity',
                    technoeconomicStandaloneFormatCapacity(
                        targetWatts, ratingBasis, {forceMw: targetWatts >= 1000000}
                    )
                );
                technoeconomicStandaloneAppendDefinition(
                    root, 'Project life', `${request.finance?.project_life_years
                        ?? result.project_life_years ?? 'Unavailable'} years`
                );
                technoeconomicStandaloneAppendDefinition(
                    root, paired ? 'Systems' : 'Model', paired
                        ? 'Solectria and SolarEdge'
                        : 'SolarEdge (saved v4 job)'
                );
                technoeconomicStandaloneAppendDefinition(
                    root, 'Currency', `USD (real ${request.finance?.constant_dollar_cost_year
                        ?? result.constant_dollar_cost_year ?? 'unavailable'})`
                );
                const discount = technoeconomicPlainObject(
                    request.finance?.real_discount_rate?.distribution
                );
                technoeconomicStandaloneAppendDefinition(
                    root, 'Discount rate (real)',
                    Object.keys(discount).length
                        ? `${technoeconomicStandaloneDistributionDisplay(discount, 100)}%`
                        : 'Unavailable'
                );
            }
            for (const {key} of TECHNOECONOMIC_PAIRED_SYSTEMS) {
                const costRoot = technoeconomicPairedSystemElements(key).costSummary;
                if (!costRoot) continue;
                costRoot.replaceChildren();
                if (!paired && key === 'solectria') {
                    technoeconomicStandaloneAppendDefinition(
                        costRoot, 'Saved result', 'Not part of this v4 job'
                    );
                    continue;
                }
                const metrics = TECHNOECONOMIC_PAIRED_METRICS[key];
                const initial = technoeconomicStandaloneMetricSummary(
                    result, metrics.initialCost
                );
                const recurring = technoeconomicStandaloneMetricSummary(
                    result, metrics.recurringCost
                );
                const scheduled = technoeconomicStandaloneMetricSummary(
                    result, metrics.scheduledCost
                );
                const lifecycle = technoeconomicStandaloneMetricSummary(
                    result, metrics.lifecycleCost
                );
                technoeconomicStandaloneAppendDefinition(
                    costRoot, 'Initial cost',
                    technoeconomicStandaloneFormatUsd(
                        technoeconomicStandalonePercentile(initial, 'p50')
                    )
                );
                technoeconomicStandaloneAppendDefinition(
                    costRoot, 'Recurring lifecycle cost',
                    technoeconomicStandaloneFormatUsd(
                        technoeconomicStandalonePercentile(recurring, 'p50')
                    )
                );
                technoeconomicStandaloneAppendDefinition(
                    costRoot, 'Scheduled replacement',
                    technoeconomicStandalonePercentile(scheduled, 'p50') === 0
                        ? 'Not included'
                        : technoeconomicStandaloneFormatUsd(
                            technoeconomicStandalonePercentile(scheduled, 'p50')
                        )
                );
                technoeconomicStandaloneAppendDefinition(
                    costRoot, 'Total lifecycle cost',
                    technoeconomicStandaloneFormatUsd(
                        technoeconomicStandalonePercentile(lifecycle, 'p50')
                    )
                );
            }
        }

        function technoeconomicRenderStandaloneResult(job, result) {
            technoeconomicSetStandaloneResultPresentation('standalone');
            const summary = technoeconomicStandaloneMetricSummary(
                result, TECHNOECONOMIC_STANDALONE_LCOE_METRIC
            );
            const p10 = technoeconomicStandalonePercentile(summary, 'p10');
            const p50 = technoeconomicStandalonePercentile(summary, 'p50');
            const p90 = technoeconomicStandalonePercentile(summary, 'p90');
            if (technoeconomicElements.standaloneResults) {
                technoeconomicElements.standaloneResults.dataset.state =
                    summary.status === 'available' ? 'done' : 'unavailable';
            }
            if (technoeconomicElements.standaloneResultStatus) {
                technoeconomicElements.standaloneResultStatus.textContent =
                    'Completed server calculation. Modeled result, not a validated forecast.';
            }
            if (technoeconomicElements.standaloneInterpretation) {
                technoeconomicElements.standaloneInterpretation.textContent = p50 === null
                    ? `SolarEdge LCOE is unavailable: ${
                        technoeconomicHumanize(summary.reason || 'no completed population')}.`
                    : `SolarEdge P50 is ${technoeconomicStandaloneFormatLcoePerMwh(
                        p50
                    )} (real USD): half of modeled outcomes are at or below this value.`;
            }
            const body = technoeconomicElements.standalonePercentileBody;
            if (body) {
                body.replaceChildren();
                for (const [key, label, value] of [
                    ['p10', 'P10', p10], ['p50', 'P50 (median)', p50], ['p90', 'P90', p90],
                ]) {
                    const row = technoeconomicNode('tr');
                    row.dataset.percentile = key;
                    row.append(
                        technoeconomicNode('th', {text: label, scope: 'row'}),
                        technoeconomicNode('td', {text: 'Unavailable'}),
                        technoeconomicNode('td', {
                            text: technoeconomicStandaloneFormatLcoePerMwh(value),
                        })
                    );
                    body.appendChild(row);
                }
            }
            const request = technoeconomicPlainObject(job.request);
            if (technoeconomicElements.standaloneRunContext) {
                technoeconomicElements.standaloneRunContext.textContent =
                    `${technoeconomicFormatNumber(
                        result.realization_count ?? request.n, 0
                    )} trials · Real discount rate · Real ${
                        request.finance?.constant_dollar_cost_year ?? 'unavailable'
                    } USD · ${
                        request.finance?.project_life_years ?? result.project_life_years ?? 'unavailable'
                    } years`;
            }
            technoeconomicRenderStandaloneScenario(job, result);
            const provenance = technoeconomicElements.standaloneProvenance;
            if (provenance) {
                provenance.replaceChildren();
                for (const [label, value] of [
                    ['Annual source', job.source_annual_job_id
                        || request.source_annual_job_id],
                    ['TEA job', job.job_id],
                    ['Contract', result.calculation_contract_version],
                    ['Source snapshot SHA-256', result.source_snapshot_sha256],
                ]) {
                    if (value !== null && value !== undefined && String(value).trim()) {
                        technoeconomicStandaloneAppendDefinition(provenance, label, String(value));
                    }
                }
            }
            const source = technoeconomicSources.find(
                (item) => item?.source_annual_job_id === job.source_annual_job_id
            ) || technoeconomicStandaloneSelectedSource();
            technoeconomicRenderStandaloneBridge(source, result, {preserveCostLines: true});
            const manifest = technoeconomicPlainObject(
                technoeconomicPlainObject(job.artifacts).exports
            );
            const entries = technoeconomicPlainObject(manifest.artifacts);
            const safe = (artifactId) => technoeconomicSafeArtifactUrl(
                job.job_id, artifactId, technoeconomicPlainObject(entries[artifactId]).url
            );
            const cdfUrl = safe('cdf_plot');
            technoeconomicSetPlot(
                technoeconomicElements.standaloneCdfPlot,
                technoeconomicElements.standaloneCdfFallback,
                cdfUrl,
                'The verified standalone commercial LCOE CDF chart is not available.'
            );
            technoeconomicSetDownload(technoeconomicElements.standaloneCdfLink, cdfUrl);
            technoeconomicSetDownload(
                technoeconomicElements.standaloneCsvLink, safe('csv_bundle')
            );
            technoeconomicSetDownload(
                technoeconomicElements.standaloneXlsxLink, safe('xlsx_workbook')
            );
            if (technoeconomicElements.standaloneSubmitButton) {
                technoeconomicElements.standaloneSubmitButton.textContent = 'Recalculate';
            }
        }

        function technoeconomicRenderPairedResult(job, result) {
            technoeconomicSetStandaloneResultPresentation('paired');
            const pairedResult = technoeconomicPlainObject(result.paired_commercial);
            const pairedSystems = technoeconomicPlainObject(pairedResult.systems);
            const summaries = Object.fromEntries(TECHNOECONOMIC_PAIRED_SYSTEMS.map(
                ({key}) => {
                    const rootSummary = technoeconomicStandaloneMetricSummary(
                        result, TECHNOECONOMIC_PAIRED_METRICS[key].lcoe
                    );
                    const nested = technoeconomicPlainObject(pairedSystems[key]);
                    return [key, rootSummary.status
                        ? rootSummary
                        : Object.keys(technoeconomicPlainObject(nested.percentiles)).length
                            ? {status: 'available', percentiles: nested.percentiles}
                            : rootSummary];
                }
            ));
            const values = Object.fromEntries(TECHNOECONOMIC_PAIRED_SYSTEMS.map(({key}) => [
                key,
                Object.fromEntries(['p10', 'p50', 'p90'].map((percentile) => [
                    percentile,
                    technoeconomicStandalonePercentile(summaries[key], percentile),
                ])),
            ]));
            const available = TECHNOECONOMIC_PAIRED_SYSTEMS.every(
                ({key}) => summaries[key].status === 'available'
            );
            if (technoeconomicElements.standaloneResults) {
                technoeconomicElements.standaloneResults.dataset.state = available
                    ? 'done' : 'unavailable';
            }
            if (technoeconomicElements.standaloneResultStatus) {
                technoeconomicElements.standaloneResultStatus.textContent =
                    'Completed paired server calculation. Modeled result, not a validated forecast.';
            }
            if (technoeconomicElements.standaloneInterpretation) {
                const solectriaP50 = values.solectria.p50;
                const solarEdgeP50 = values.solaredge.p50;
                const rootDeltaSummary = technoeconomicStandaloneMetricSummary(
                    result, TECHNOECONOMIC_PAIRED_LCOE_DELTA_METRIC
                );
                const nestedDelta = technoeconomicPlainObject(
                    pairedResult.lcoe_delta_se_minus_sol
                );
                const deltaSummary = rootDeltaSummary.status
                    ? rootDeltaSummary
                    : Object.keys(technoeconomicPlainObject(nestedDelta.percentiles)).length
                        ? {status: 'available', percentiles: nestedDelta.percentiles}
                        : rootDeltaSummary;
                const deltaP50 = technoeconomicStandalonePercentile(deltaSummary, 'p50');
                technoeconomicElements.standaloneInterpretation.textContent =
                    solectriaP50 === null || solarEdgeP50 === null
                        ? 'Both system LCOE populations are required for comparison.'
                        : `P50: Solectria ${
                            technoeconomicStandaloneFormatLcoePerMwh(solectriaP50)
                        }; SolarEdge ${
                            technoeconomicStandaloneFormatLcoePerMwh(solarEdgeP50)
                        }${deltaP50 === null ? '.' : `; SolarEdge minus Solectria ${
                            technoeconomicStandaloneFormatLcoePerMwh(deltaP50)
                        }.`}`;
            }
            const body = technoeconomicElements.standalonePercentileBody;
            if (body) {
                body.replaceChildren();
                for (const [key, label] of [
                    ['p10', 'P10'], ['p50', 'P50 (median)'], ['p90', 'P90'],
                ]) {
                    const row = technoeconomicNode('tr');
                    row.dataset.percentile = key;
                    row.append(
                        technoeconomicNode('th', {text: label, scope: 'row'}),
                        technoeconomicNode('td', {
                            text: technoeconomicStandaloneFormatLcoePerMwh(
                                values.solectria[key]
                            ),
                        }),
                        technoeconomicNode('td', {
                            text: technoeconomicStandaloneFormatLcoePerMwh(
                                values.solaredge[key]
                            ),
                        })
                    );
                    body.appendChild(row);
                }
            }
            const request = technoeconomicPlainObject(job.request);
            if (technoeconomicElements.standaloneRunContext) {
                technoeconomicElements.standaloneRunContext.textContent =
                    `${technoeconomicFormatNumber(
                        result.realization_count ?? request.n, 0
                    )} trials · Real discount rate · Real ${
                        request.finance?.constant_dollar_cost_year ?? 'unavailable'
                    } USD · ${
                        request.finance?.project_life_years ?? result.project_life_years
                            ?? 'unavailable'
                    } years`;
            }
            technoeconomicRenderStandaloneScenario(job, result);
            const provenance = technoeconomicElements.standaloneProvenance;
            if (provenance) {
                provenance.replaceChildren();
                for (const [label, value] of [
                    ['Annual source', job.source_annual_job_id
                        || request.source_annual_job_id],
                    ['TEA job', job.job_id],
                    ['Contract', result.calculation_contract_version],
                    ['Source snapshot SHA-256', result.source_snapshot_sha256],
                ]) {
                    if (value !== null && value !== undefined && String(value).trim()) {
                        technoeconomicStandaloneAppendDefinition(provenance, label, String(value));
                    }
                }
            }
            const source = technoeconomicSources.find(
                (item) => item?.source_annual_job_id === job.source_annual_job_id
            ) || technoeconomicStandaloneSelectedSource();
            technoeconomicRenderStandaloneBridge(source, result, {preserveCostLines: true});
            const manifest = technoeconomicPlainObject(
                technoeconomicPlainObject(job.artifacts).exports
            );
            const entries = technoeconomicPlainObject(manifest.artifacts);
            const safe = (artifactId) => technoeconomicSafeArtifactUrl(
                job.job_id, artifactId, technoeconomicPlainObject(entries[artifactId]).url
            );
            const cdfUrl = safe('cdf_plot');
            technoeconomicSetPlot(
                technoeconomicElements.standaloneCdfPlot,
                technoeconomicElements.standaloneCdfFallback,
                cdfUrl,
                'The verified paired commercial LCOE CDF chart is not available.'
            );
            technoeconomicSetDownload(technoeconomicElements.standaloneCdfLink, cdfUrl);
            technoeconomicSetDownload(
                technoeconomicElements.standaloneCsvLink, safe('csv_bundle')
            );
            technoeconomicSetDownload(
                technoeconomicElements.standaloneXlsxLink, safe('xlsx_workbook')
            );
            if (technoeconomicElements.standaloneSubmitButton) {
                technoeconomicElements.standaloneSubmitButton.textContent = 'Recalculate';
            }
        }

        function technoeconomicRenderLifecycleResult(job, result) {
            technoeconomicSetStandaloneResultPresentation('lifecycle');
            const summaries = technoeconomicPlainObject(result.summaries);
            const lifecycle = technoeconomicPlainObject(result.paired_lifecycle);
            const decision = technoeconomicPlainObject(
                Object.keys(technoeconomicPlainObject(summaries.headline_decision)).length
                    ? summaries.headline_decision : lifecycle.headline_decision
            );
            const upgradeNpv = technoeconomicPlainObject(
                Object.keys(technoeconomicPlainObject(summaries.upgrade_npv)).length
                    ? summaries.upgrade_npv : lifecycle.upgrade_npv
            );
            const deltaLcoe = technoeconomicPlainObject(
                Object.keys(technoeconomicPlainObject(summaries.delta_lcoe)).length
                    ? summaries.delta_lcoe : lifecycle.delta_lcoe
            );
            const lcoo = technoeconomicPlainObject(
                Object.keys(technoeconomicPlainObject(summaries.lcoo)).length
                    ? summaries.lcoo : lifecycle.lcoo
            );
            const lcoeSolectria = technoeconomicPlainObject(summaries.lcoe_solectria);
            const lcoeSolarEdge = technoeconomicPlainObject(summaries.lcoe_solaredge);
            const probabilityRoot = technoeconomicPlainObject(
                Object.keys(technoeconomicPlainObject(summaries.probability_counts)).length
                    ? summaries.probability_counts : lifecycle.probability_counts
            );
            const probabilityCounts = technoeconomicPlainObject(probabilityRoot.upgrade_npv);
            const percentiles = technoeconomicPlainObject(upgradeNpv.percentiles);
            const preferred = technoeconomicText(decision.decision).trim()
                || (decision.preferred_system === 'solaredge'
                    ? 'SolarEdge preferred'
                    : decision.preferred_system === 'solectria'
                        ? 'Solectria preferred' : 'No decisive winner');
            const reasonCodes = Array.isArray(decision.reason_codes)
                ? decision.reason_codes
                : Array.isArray(lifecycle.reason_codes) ? lifecycle.reason_codes : [];
            const warnings = Array.isArray(lifecycle.warnings) ? lifecycle.warnings : [];
            const available = upgradeNpv.status === 'available';
            if (technoeconomicElements.standaloneResults) {
                technoeconomicElements.standaloneResults.dataset.state = available
                    ? 'done' : 'unavailable';
            }
            if (technoeconomicElements.standaloneResultStatus) {
                technoeconomicElements.standaloneResultStatus.textContent =
                    decision.status === 'suppressed'
                        ? `V6 decision suppressed: ${(
                            reasonCodes.length ? reasonCodes : ['failed decision gate']
                        ).map(technoeconomicHumanize).join(', ')}.`
                        : `Completed v6 ${technoeconomicHumanize(
                            lifecycle.reliability_mode || 'event'
                        )}-mode lifecycle calculation · ${preferred}.`;
            }
            if (technoeconomicElements.standaloneInterpretation) {
                const p10 = technoeconomicStandaloneOptionalNumber(percentiles.p10);
                const p50 = technoeconomicStandaloneOptionalNumber(percentiles.p50);
                const p90 = technoeconomicStandaloneOptionalNumber(percentiles.p90);
                const probability = decision.preferred_system === 'solaredge'
                    ? probabilityCounts.p_positive
                    : decision.preferred_system === 'solectria'
                        ? probabilityCounts.p_negative : null;
                const probabilityText = technoeconomicStandaloneOptionalNumber(probability);
                technoeconomicElements.standaloneInterpretation.textContent = p50 === null
                    ? `Upgrade NPV is unavailable: ${technoeconomicHumanize(
                        upgradeNpv.reason || 'no completed population'
                    )}.`
                    : `${preferred}. Upgrade NPV P50 is ${
                        technoeconomicStandaloneFormatUsd(p50)
                    }; P10–P90 is ${technoeconomicStandaloneFormatUsd(p10)} to ${
                        technoeconomicStandaloneFormatUsd(p90)
                    }${probabilityText === null ? '' : `; decision probability ${
                        technoeconomicFormatNumber(probabilityText * 100, 1)
                    }%`}. Positive upgrade NPV favors SolarEdge.${
                        warnings.length ? ` Warnings: ${warnings.map((warning) =>
                            technoeconomicHumanize(
                                typeof warning === 'string' ? warning : warning?.code
                            )
                        ).join(', ')}.` : ''
                    }`;
            }
            const probabilitySummary = technoeconomicElements.v6ProbabilitySummary;
            if (probabilitySummary) {
                probabilitySummary.replaceChildren();
                const denominator = technoeconomicStandaloneOptionalNumber(
                    probabilityCounts.denominator
                );
                const probabilityText = (probability, count) => {
                    const number = technoeconomicStandaloneOptionalNumber(probability);
                    const countNumber = technoeconomicStandaloneOptionalNumber(count);
                    if (number === null || countNumber === null || denominator === null) {
                        return 'Unavailable';
                    }
                    return `${technoeconomicFormatNumber(number * 100, 1)}% · ${
                        technoeconomicFormatNumber(countNumber, 0)
                    }/${technoeconomicFormatNumber(denominator, 0)}`;
                };
                for (const [label, value] of [
                    ['NPV positive', probabilityText(
                        probabilityCounts.p_positive, probabilityCounts.positive
                    )],
                    ['NPV negative', probabilityText(
                        probabilityCounts.p_negative, probabilityCounts.negative
                    )],
                    ['NPV tie', probabilityText(
                        probabilityCounts.p_tie, probabilityCounts.tie
                    )],
                    ['Decision threshold', `${technoeconomicFormatNumber(
                        Number(decision.probability_threshold
                            ?? lifecycle.headline_decision?.probability_threshold
                            ?? 0.75) * 100,
                        0
                    )}%`],
                ]) {
                    technoeconomicStandaloneAppendDefinition(
                        probabilitySummary, label, value
                    );
                }
            }
            const body = technoeconomicElements.v6PercentileBody;
            if (body) {
                body.replaceChildren();
                const summariesByColumn = [
                    [upgradeNpv, technoeconomicStandaloneFormatUsd, 'Upgrade NPV (USD)'],
                    [lcoeSolectria, technoeconomicStandaloneFormatLcoeTableValue,
                        'Solectria LCOE (USD/MWh)'],
                    [lcoeSolarEdge, technoeconomicStandaloneFormatLcoeTableValue,
                        'SolarEdge LCOE (USD/MWh)'],
                    [deltaLcoe, technoeconomicStandaloneFormatLcoeTableValue,
                        'Delta LCOE, SE minus SO (USD/MWh)'],
                    [lcoo, technoeconomicStandaloneFormatLcoeTableValue,
                        'LCOO, SE minus SO (USD/MWh)'],
                ];
                for (const [key, label] of [
                    ['p10', 'P10'], ['p50', 'P50 (median)'], ['p90', 'P90'],
                ]) {
                    const row = technoeconomicNode('tr');
                    row.dataset.percentile = key;
                    row.append(technoeconomicNode('th', {text: label, scope: 'row'}));
                    for (const [summary, formatter, columnLabel] of summariesByColumn) {
                        const cell = technoeconomicNode('td', {
                            text: formatter(technoeconomicStandalonePercentile(summary, key)),
                        });
                        cell.dataset.label = columnLabel;
                        row.append(cell);
                    }
                    body.appendChild(row);
                }
            }
            const request = technoeconomicPlainObject(job?.request);
            if (technoeconomicElements.standaloneRunContext) {
                technoeconomicElements.standaloneRunContext.textContent = `${
                    technoeconomicFormatNumber(result.realization_count ?? request.n, 0)
                } trials · ${result.sampling_version || TECHNOECONOMIC_LIFECYCLE_SAMPLING_VERSION
                } · ${request.finance?.project_life_years ?? result.project_life_years
                    ?? 'Unavailable'} years · Upgrade NPV primary`;
            }
            const scenario = technoeconomicElements.standaloneScenarioSummary;
            if (scenario) {
                scenario.replaceChildren();
                for (const [label, value] of [
                    ['Target capacity', technoeconomicStandaloneFormatCapacity(
                        lifecycle.target_capacity_w,
                        lifecycle.target_rating_basis,
                        {forceMw: true}
                    )],
                    ['Project life', `${request.finance?.project_life_years
                        ?? result.project_life_years ?? 'Unavailable'} years`],
                    ['Systems', 'Solectria and SolarEdge'],
                    ['Currency', `USD (real ${lifecycle.constant_dollar_cost_year
                        ?? request.finance?.constant_dollar_cost_year ?? 'unavailable'})`],
                    ['Source energy', technoeconomicHumanize(
                        lifecycle.source_energy_basis || 'unavailable'
                    )],
                    ['Reliability', `${technoeconomicHumanize(
                        lifecycle.reliability_mode || 'event'
                    )} mode · event mode is headline`],
                ]) technoeconomicStandaloneAppendDefinition(scenario, label, value);
            }
            for (const {key} of TECHNOECONOMIC_PAIRED_SYSTEMS) {
                const costRoot = technoeconomicPairedSystemElements(key).costSummary;
                if (!costRoot) continue;
                costRoot.replaceChildren();
                const suffix = key === 'solectria' ? 'solectria' : 'solaredge';
                const costSummary = technoeconomicPlainObject(
                    summaries[`lifecycle_cost_${suffix}`]
                );
                const energySummary = technoeconomicPlainObject(
                    summaries[`lifecycle_energy_${suffix}`]
                );
                const lcoeSummary = suffix === 'solectria'
                    ? lcoeSolectria : lcoeSolarEdge;
                for (const [label, value] of [
                    ['PV lifecycle cost', technoeconomicStandaloneFormatUsd(
                        technoeconomicStandalonePercentile(costSummary, 'p50')
                    )],
                    ['PV lifecycle energy', (() => {
                        const energy = technoeconomicStandalonePercentile(
                            energySummary, 'p50'
                        );
                        return energy === null ? 'Unavailable'
                            : `${technoeconomicFormatNumber(energy / 1000000, 2)} GWh`;
                    })()],
                    ['Lifecycle LCOE', technoeconomicStandaloneFormatLcoePerMwh(
                        technoeconomicStandalonePercentile(lcoeSummary, 'p50')
                    )],
                ]) technoeconomicStandaloneAppendDefinition(costRoot, label, value);
            }
            const provenance = technoeconomicElements.standaloneProvenance;
            if (provenance) {
                provenance.replaceChildren();
                const registry = technoeconomicPlainObject(lifecycle.formula_registry);
                technoeconomicStandaloneAppendDefinition(
                    provenance, 'Annual source', job.source_annual_job_id
                        || request.source_annual_job_id || 'Unavailable'
                );
                for (const [label, value] of [
                    ['TEA job', job.job_id],
                    ['Calculation contract', result.calculation_contract_version],
                    ['Sampling contract', result.sampling_version],
                    ['Result schema', result.result_version || 'tea-result-v6'],
                    ['Formula registry', registry.formula_registry_version
                        || registry.version || 'tea-formulas-v6'],
                    ['Formula registry SHA-256', registry.formula_registry_sha256
                        || registry.sha256],
                    ['Weather allocation', TECHNOECONOMIC_LIFECYCLE_WEATHER_METHOD],
                ]) {
                    if (value !== null && value !== undefined && String(value).trim()) {
                        technoeconomicStandaloneAppendDefinition(
                            provenance, label, String(value)
                        );
                    }
                }
            }
            const source = technoeconomicSources.find(
                (item) => item?.source_annual_job_id === job.source_annual_job_id
            ) || technoeconomicStandaloneSelectedSource();
            technoeconomicRenderStandaloneBridge(source, result, {preserveCostLines: true});
            const manifest = technoeconomicPlainObject(
                technoeconomicPlainObject(job.artifacts).exports
            );
            const entries = technoeconomicPlainObject(manifest.artifacts);
            const safe = (artifactId) => technoeconomicSafeArtifactUrl(
                job.job_id, artifactId, technoeconomicPlainObject(entries[artifactId]).url
            );
            const cdfArtifact = technoeconomicPlainObject(entries.cdf_plot);
            const hasLegacyCdf = Boolean(cdfArtifact.url)
                && cdfArtifact.chart_contract_id
                    !== TECHNOECONOMIC_LIFECYCLE_LCOE_CDF_CHART_CONTRACT;
            const cdfUrl = cdfArtifact.chart_contract_id
                === TECHNOECONOMIC_LIFECYCLE_LCOE_CDF_CHART_CONTRACT
                ? safe('cdf_plot') : null;
            technoeconomicSetPlot(
                technoeconomicElements.standaloneCdfPlot,
                technoeconomicElements.standaloneCdfFallback,
                cdfUrl,
                hasLegacyCdf
                    ? 'This saved v6 result uses the earlier multi-metric diagnostic chart. Recalculate to generate the focused Solectria and SolarEdge lifecycle LCOE cumulative distributions.'
                    : 'The verified Solectria and SolarEdge lifecycle LCOE CDF chart is not available.'
            );
            technoeconomicSetDownload(technoeconomicElements.standaloneCdfLink, cdfUrl);
            technoeconomicSetDownload(
                technoeconomicElements.standaloneCsvLink, safe('csv_bundle')
            );
            technoeconomicSetDownload(
                technoeconomicElements.standaloneXlsxLink, safe('xlsx_workbook')
            );
            if (technoeconomicElements.standaloneSubmitButton) {
                technoeconomicElements.standaloneSubmitButton.textContent =
                    'Recalculate upgrade NPV';
            }
        }

        function technoeconomicClearStandaloneResult() {
            technoeconomicSetStandaloneResultPresentation(
                technoeconomicSelectedContractVersion()
                    === TECHNOECONOMIC_LIFECYCLE_CONTRACT_VERSION
                    ? 'lifecycle' : 'paired'
            );
            if (technoeconomicElements.standaloneResults) {
                technoeconomicElements.standaloneResults.dataset.state = 'empty';
            }
            if (technoeconomicElements.standaloneResultStatus) {
                technoeconomicElements.standaloneResultStatus.textContent =
                    'Complete the assumptions, then calculate. Results are modeled, not a validated forecast.';
            }
            if (technoeconomicElements.standaloneInterpretation) {
                technoeconomicElements.standaloneInterpretation.textContent =
                    'A completed server result is required before the probability distribution can be interpreted.';
            }
            technoeconomicElements.standalonePercentileBody?.replaceChildren();
            technoeconomicElements.v6ProbabilitySummary?.replaceChildren();
            technoeconomicElements.v6PercentileBody?.replaceChildren();
            technoeconomicSetPlot(
                technoeconomicElements.standaloneCdfPlot,
                technoeconomicElements.standaloneCdfFallback,
                null,
                'The verified CDF chart will appear after a completed calculation.'
            );
            technoeconomicSetDownload(technoeconomicElements.standaloneCdfLink, null);
            technoeconomicSetDownload(technoeconomicElements.standaloneCsvLink, null);
            technoeconomicSetDownload(technoeconomicElements.standaloneXlsxLink, null);
            technoeconomicElements.standaloneProvenance?.replaceChildren();
            if (technoeconomicElements.standaloneSubmitButton) {
                technoeconomicElements.standaloneSubmitButton.textContent =
                    technoeconomicSelectedContractVersion()
                        === TECHNOECONOMIC_LIFECYCLE_CONTRACT_VERSION
                        ? 'Calculate upgrade NPV' : 'Calculate LCOE';
            }
            technoeconomicRenderStandaloneDraft();
        }

        function technoeconomicReadGuidedForm() {
            const read = (element) => element?.value || '';
            const commercialEnabled = technoeconomicDomElement(
                'technoeconomicGuidedCommercialEnabled'
            );
            const commercialAccept = technoeconomicDomElement(
                'technoeconomicGuidedCommercialAccept'
            );
            return {
                cost_year: read(technoeconomicElements.guidedCostYear),
                project_life_years: read(technoeconomicElements.guidedProjectLife),
                discount: read(technoeconomicElements.guidedDiscount),
                discount_low: read(technoeconomicElements.guidedDiscountLow),
                discount_high: read(technoeconomicElements.guidedDiscountHigh),
                degradation: read(technoeconomicElements.guidedDegradation),
                degradation_low: read(technoeconomicElements.guidedDegradationLow),
                degradation_high: read(technoeconomicElements.guidedDegradationHigh),
                solectria_capex: read(technoeconomicElements.guidedSolectriaCapex),
                solectria_capex_low: read(technoeconomicElements.guidedSolectriaCapexLow),
                solectria_capex_high: read(technoeconomicElements.guidedSolectriaCapexHigh),
                solectria_om: read(technoeconomicElements.guidedSolectriaOm),
                solectria_om_low: read(technoeconomicElements.guidedSolectriaOmLow),
                solectria_om_high: read(technoeconomicElements.guidedSolectriaOmHigh),
                solaredge_capex: read(technoeconomicElements.guidedSolarEdgeCapex),
                solaredge_capex_low: read(technoeconomicElements.guidedSolarEdgeCapexLow),
                solaredge_capex_high: read(technoeconomicElements.guidedSolarEdgeCapexHigh),
                solaredge_om: read(technoeconomicElements.guidedSolarEdgeOm),
                solaredge_om_low: read(technoeconomicElements.guidedSolarEdgeOmLow),
                solaredge_om_high: read(technoeconomicElements.guidedSolarEdgeOmHigh),
                assumption_note: read(technoeconomicElements.guidedAssumptionNote),
                accepted: technoeconomicElements.guidedAccept?.checked === true,
                commercial_enabled: commercialEnabled?.checked === true,
                commercial_target_capacity: read(technoeconomicDomElement(
                    'technoeconomicGuidedCommercialTargetCapacity'
                )),
                commercial_target_unit: read(technoeconomicDomElement(
                    'technoeconomicGuidedCommercialTargetUnit'
                )),
                commercial_rating_basis: read(technoeconomicDomElement(
                    'technoeconomicGuidedCommercialRatingBasis'
                )),
                commercial_cost: read(technoeconomicDomElement(
                    'technoeconomicGuidedCommercialCost'
                )),
                commercial_cost_low: read(technoeconomicDomElement(
                    'technoeconomicGuidedCommercialCostLow'
                )),
                commercial_cost_high: read(technoeconomicDomElement(
                    'technoeconomicGuidedCommercialCostHigh'
                )),
                commercial_cost_timing: read(technoeconomicDomElement(
                    'technoeconomicGuidedCommercialCostTiming'
                )),
                commercial_rationale: read(technoeconomicDomElement(
                    'technoeconomicGuidedCommercialRationale'
                )),
                commercial_accepted: commercialAccept?.checked === true,
            };
        }

        function technoeconomicGuidedFormErrors() {
            if (technoeconomicEntryMode !== TECHNOECONOMIC_GUIDED_ENTRY_MODE) {
                return [{
                    path: 'Saved custom TEA draft',
                    message: 'Detailed editing is unavailable in the minimum-entry interface. '
                        + 'Start a new Guided SolarTAC form to continue.',
                }];
            }
            const guided = technoeconomicReadGuidedForm();
            const errors = [];
            const required = [
                ['cost_year', 'Constant-dollar cost year'],
                ['project_life_years', 'Project life'],
                ['discount', 'Central real discount rate'],
                ['solectria_capex', 'Solectria installed CAPEX'],
                ['solectria_om', 'Solectria annual O&M'],
                ['solaredge_capex', 'SolarEdge installed CAPEX'],
                ['solaredge_om', 'SolarEdge annual O&M'],
                ['assumption_note', 'Financial assumption source or justification'],
            ];
            required.forEach(([key, label]) => {
                if (!technoeconomicText(guided[key]).trim()) {
                    errors.push({path: label, message: 'Enter a value.'});
                }
            });
            for (const [key, label] of [
                ['discount', 'Real discount rate'],
                ['degradation', 'Annual module degradation'],
                ['solectria_capex', 'Solectria installed CAPEX'],
                ['solectria_om', 'Solectria annual O&M'],
                ['solaredge_capex', 'SolarEdge installed CAPEX'],
                ['solaredge_om', 'SolarEdge annual O&M'],
            ]) {
                const hasLow = Boolean(technoeconomicText(guided[`${key}_low`]).trim());
                const hasHigh = Boolean(technoeconomicText(guided[`${key}_high`]).trim());
                if (hasLow !== hasHigh) {
                    errors.push({
                        path: `${label} uncertainty`,
                        message: 'Provide both low and high, or leave both blank.',
                    });
                    continue;
                }
                if (hasLow && hasHigh) {
                    const centralText = key === 'degradation' && !technoeconomicText(guided[key]).trim()
                        ? '0' : guided[key];
                    const low = Number(guided[`${key}_low`]);
                    const central = Number(centralText);
                    const high = Number(guided[`${key}_high`]);
                    if (Number.isFinite(low) && Number.isFinite(central) && Number.isFinite(high)
                        && (low > central || central > high)) {
                        errors.push({
                            path: `${label} uncertainty`,
                            message: 'Use low <= central <= high.',
                        });
                    }
                }
            }
            if (!guided.accepted) {
                errors.push({
                    path: 'Guided assumption confirmation',
                    message: 'Confirm the financial and lifecycle assumptions.',
                });
            }
            if (guided.commercial_enabled) {
                for (const [key, label] of [
                    ['commercial_target_capacity', 'Commercial target capacity'],
                    ['commercial_target_unit', 'Commercial target capacity unit'],
                    ['commercial_rating_basis', 'Commercial target rating basis'],
                    ['commercial_cost', 'Commercial marginal cost difference'],
                    ['commercial_cost_timing', 'Commercial marginal cost timing'],
                    ['commercial_rationale', 'Commercial direct-scaling rationale'],
                ]) {
                    if (!technoeconomicText(guided[key]).trim()) {
                        errors.push({path: label, message: 'Enter a value.'});
                    }
                }
                const target = Number(guided.commercial_target_capacity);
                if (technoeconomicText(guided.commercial_target_capacity).trim()
                    && (!Number.isFinite(target) || !(target > 0))) {
                    errors.push({
                        path: 'Commercial target capacity',
                        message: 'Enter a finite capacity greater than zero.',
                    });
                }
                const hasLow = Boolean(technoeconomicText(guided.commercial_cost_low).trim());
                const hasHigh = Boolean(technoeconomicText(guided.commercial_cost_high).trim());
                if (hasLow !== hasHigh) {
                    errors.push({
                        path: 'Commercial marginal cost uncertainty',
                        message: 'Provide both low and high, or leave both blank.',
                    });
                } else if (hasLow && hasHigh) {
                    const low = Number(guided.commercial_cost_low);
                    const central = Number(guided.commercial_cost);
                    const high = Number(guided.commercial_cost_high);
                    if ([low, central, high].every(Number.isFinite)
                        && !(low <= central && central <= high)) {
                        errors.push({
                            path: 'Commercial marginal cost uncertainty',
                            message: 'Use low <= central <= high.',
                        });
                    }
                }
                const sourceId = technoeconomicElements.sourceSelect?.value || '';
                const source = technoeconomicSources.find(
                    (item) => item?.source_annual_job_id === sourceId
                );
                const sourceBasis = technoeconomicSourceRatingBasis(source);
                if (sourceBasis && guided.commercial_rating_basis !== sourceBasis) {
                    errors.push({
                        path: 'Commercial target rating basis',
                        message: 'Match the selected Annual Simulation applied-capacity rating basis.',
                    });
                }
                if (!guided.commercial_accepted) {
                    errors.push({
                        path: 'Commercial direct-scaling confirmation',
                        message: 'Confirm the direct capacity-scaling rationale and rating basis.',
                    });
                }
            }
            return errors;
        }

        function technoeconomicSetGuidedControl(element, value) {
            if (element) element.value = technoeconomicText(value);
        }

        function technoeconomicRenderGuidedForm(value) {
            const guided = technoeconomicGuidedInputsFromDraft(value);
            const pairs = [
                ['guidedCostYear', 'cost_year'], ['guidedProjectLife', 'project_life_years'],
                ['guidedDiscount', 'discount'], ['guidedDiscountLow', 'discount_low'],
                ['guidedDiscountHigh', 'discount_high'],
                ['guidedDegradation', 'degradation'],
                ['guidedDegradationLow', 'degradation_low'],
                ['guidedDegradationHigh', 'degradation_high'],
                ['guidedSolectriaCapex', 'solectria_capex'],
                ['guidedSolectriaCapexLow', 'solectria_capex_low'],
                ['guidedSolectriaCapexHigh', 'solectria_capex_high'],
                ['guidedSolectriaOm', 'solectria_om'],
                ['guidedSolectriaOmLow', 'solectria_om_low'],
                ['guidedSolectriaOmHigh', 'solectria_om_high'],
                ['guidedSolarEdgeCapex', 'solaredge_capex'],
                ['guidedSolarEdgeCapexLow', 'solaredge_capex_low'],
                ['guidedSolarEdgeCapexHigh', 'solaredge_capex_high'],
                ['guidedSolarEdgeOm', 'solaredge_om'],
                ['guidedSolarEdgeOmLow', 'solaredge_om_low'],
                ['guidedSolarEdgeOmHigh', 'solaredge_om_high'],
                ['guidedAssumptionNote', 'assumption_note'],
            ];
            pairs.forEach(([elementKey, valueKey]) => {
                technoeconomicSetGuidedControl(technoeconomicElements[elementKey], guided[valueKey]);
            });
            if (technoeconomicElements.guidedAccept) {
                technoeconomicElements.guidedAccept.checked = guided.accepted;
            }
            const commercialPairs = [
                ['technoeconomicGuidedCommercialTargetCapacity', 'commercial_target_capacity'],
                ['technoeconomicGuidedCommercialTargetUnit', 'commercial_target_unit'],
                ['technoeconomicGuidedCommercialRatingBasis', 'commercial_rating_basis'],
                ['technoeconomicGuidedCommercialCost', 'commercial_cost'],
                ['technoeconomicGuidedCommercialCostLow', 'commercial_cost_low'],
                ['technoeconomicGuidedCommercialCostHigh', 'commercial_cost_high'],
                ['technoeconomicGuidedCommercialCostTiming', 'commercial_cost_timing'],
                ['technoeconomicGuidedCommercialRationale', 'commercial_rationale'],
            ];
            commercialPairs.forEach(([elementId, valueKey]) => {
                technoeconomicSetGuidedControl(
                    technoeconomicDomElement(elementId), guided[valueKey]
                );
            });
            const commercialEnabled = technoeconomicDomElement(
                'technoeconomicGuidedCommercialEnabled'
            );
            if (commercialEnabled) commercialEnabled.checked = guided.commercial_enabled;
            const commercialAccept = technoeconomicDomElement(
                'technoeconomicGuidedCommercialAccept'
            );
            if (commercialAccept) commercialAccept.checked = guided.commercial_accepted;
            const hasRanges = pairs.some(([elementKey, valueKey]) =>
                (elementKey.endsWith('Low') || elementKey.endsWith('High')) && guided[valueKey]
            );
            if (technoeconomicElements.guidedRanges) {
                technoeconomicElements.guidedRanges.open = hasRanges;
            }
            technoeconomicRenderGuidedCommercialControls();
            technoeconomicRenderGuidedEstimates();
        }

        function technoeconomicRenderEntryMode() {
            const guided = technoeconomicEntryMode === TECHNOECONOMIC_GUIDED_ENTRY_MODE;
            const standaloneWorkspace = Boolean(technoeconomicElements.standaloneResults);
            if (standaloneWorkspace
                && typeof document === 'object'
                && typeof document.querySelectorAll === 'function') {
                document.querySelectorAll('.tea-legacy-v3-workspace').forEach((panel) => {
                    panel.hidden = true;
                    panel.setAttribute('inert', '');
                });
            }
            if (technoeconomicElements.guidedPanel) {
                technoeconomicElements.guidedPanel.hidden = standaloneWorkspace || !guided;
            }
            if (technoeconomicElements.advancedDetails) {
                technoeconomicElements.advancedDetails.hidden = true;
                technoeconomicElements.advancedDetails.open = false;
            }
            if (technoeconomicElements.entryModeRow) {
                technoeconomicElements.entryModeRow.hidden = guided;
            }
            if (technoeconomicElements.submitPanel) {
                technoeconomicElements.submitPanel.hidden = standaloneWorkspace || !guided;
            }
            if (technoeconomicElements.useGuidedButton) {
                technoeconomicElements.useGuidedButton.hidden = guided;
            }
            if (technoeconomicElements.entryModeStatus) {
                technoeconomicElements.entryModeStatus.textContent = guided
                    ? 'Guided SolarTAC setup is active. Detailed request fields are generated automatically.'
                    : 'A saved custom TEA draft was found. Detailed editing is unavailable in '
                        + 'the minimum-entry interface. Start a new Guided SolarTAC form to continue; '
                        + 'the saved draft is preserved until you confirm the reset.';
            }
        }

        function technoeconomicMaterializeGuidedEditors() {
            if (technoeconomicEntryMode !== TECHNOECONOMIC_GUIDED_ENTRY_MODE) return;
            const draft = getTechnoeconomicFormState();
            technoeconomicApplyingDraft = true;
            try {
                technoeconomicElements.basis.value = draft.basis;
                technoeconomicElements.realizations.value = draft.n;
                technoeconomicElements.seed.value = draft.seed;
                technoeconomicElements.costYear.value = draft.cost_year;
                technoeconomicElements.projectLife.value = draft.project_life_years;
                technoeconomicElements.transferEnabled.checked = false;
                technoeconomicRenderEditors(draft);
            } finally {
                technoeconomicApplyingDraft = false;
            }
        }

        function technoeconomicCloseStaleAdvancedPreview() {
            if (technoeconomicEntryMode === TECHNOECONOMIC_GUIDED_ENTRY_MODE
                && technoeconomicElements.advancedDetails?.open) {
                technoeconomicElements.advancedDetails.open = false;
            }
        }

        function technoeconomicUseGuidedSolarTac() {
            const proceed = typeof window !== 'object' || typeof window.confirm !== 'function'
                || window.confirm(
                    'Start a blank Guided SolarTAC form? '
                    + 'This replaces the saved custom TEA draft in this browser.'
                );
            if (!proceed) return;
            const current = getTechnoeconomicFormState();
            const guided = technoeconomicDefaultDraft();
            guided.source_annual_job_id = current.source_annual_job_id;
            guided.seed = current.seed || technoeconomicGenerateSafeSeed();
            applyTechnoeconomicFormState(guided);
            if (technoeconomicElements.advancedDetails) {
                technoeconomicElements.advancedDetails.open = false;
            }
            technoeconomicDraftRevision += 1;
            technoeconomicMarkDraftChanged('Guided SolarTAC setup restored.');
        }

        function technoeconomicIsTerminalState(state) {
            return TECHNOECONOMIC_TERMINAL_STATES.has(String(state || ''));
        }

        function technoeconomicDifferenceLabel(value, positive, negative, neutral = 'Within tolerance') {
            const number = Number(value);
            if (!Number.isFinite(number) || number === 0) return neutral;
            return number > 0 ? positive : negative;
        }

        function technoeconomicTradeoffLabel(key) {
            return TECHNOECONOMIC_TRADEOFF_LABELS[key] || 'Unclassified cost and energy outcome';
        }

        function technoeconomicSafeArtifactUrl(jobId, artifactId, candidateUrl) {
            const safeId = typeof jobId === 'string' && /^tea_[A-Za-z0-9._:-]+$/.test(jobId)
                ? jobId : '';
            const suffixes = {
                csv_bundle: 'exports/csv', xlsx_workbook: 'exports/xlsx',
                cdf_plot: 'artifacts/cdf_plot',
                sensitivity_plot: 'artifacts/sensitivity_plot',
                convergence_plot: 'artifacts/convergence_plot',
            };
            if (!safeId || !Object.prototype.hasOwnProperty.call(suffixes, artifactId)) return null;
            const expected = `/api/technoeconomic/jobs/${safeId}/${suffixes[artifactId]}`;
            if (typeof candidateUrl !== 'string' || !candidateUrl) return null;
            try {
                const base = typeof location === 'object' && location.origin
                    ? location.origin : 'https://local.invalid';
                const parsed = new URL(candidateUrl, base);
                let decodedPath = '';
                try {
                    decodedPath = decodeURIComponent(parsed.pathname);
                } catch (_error) {
                    return null;
                }
                if (parsed.origin !== base || parsed.search || parsed.hash || decodedPath !== expected) {
                    return null;
                }
                return parsed.pathname;
            } catch (_error) {
                return null;
            }
        }

        let technoeconomicDynamicId = 0;
        let technoeconomicDraftSaveTimer = null;

        function technoeconomicNode(tag, options = {}, children = []) {
            const node = document.createElement(tag);
            if (options.id) node.id = options.id;
            if (options.className) node.className = options.className;
            if (options.text !== undefined) node.textContent = String(options.text);
            if (options.type) node.type = options.type;
            if (options.value !== undefined) node.value = String(options.value);
            if (options.name) node.name = options.name;
            if (options.hidden !== undefined) node.hidden = Boolean(options.hidden);
            if (options.disabled !== undefined) node.disabled = Boolean(options.disabled);
            if (options.checked !== undefined) node.checked = Boolean(options.checked);
            if (options.placeholder) node.placeholder = options.placeholder;
            if (options.htmlFor) node.htmlFor = options.htmlFor;
            if (options.inputmode) node.setAttribute('inputmode', options.inputmode);
            if (options.min !== undefined) node.min = String(options.min);
            if (options.max !== undefined) node.max = String(options.max);
            if (options.step !== undefined) node.step = String(options.step);
            if (options.required) node.required = true;
            if (options.scope) node.scope = options.scope;
            if (options.colSpan !== undefined) node.colSpan = Number(options.colSpan);
            if (Array.isArray(children) && children.length) node.append(...children);
            return node;
        }

        function technoeconomicControl(field, value, options = {}) {
            const tag = options.values ? 'select' : options.multiline ? 'textarea' : 'input';
            const control = technoeconomicNode(tag, {
                type: tag === 'input' ? options.type || 'text' : undefined,
                value, placeholder: options.placeholder,
                min: options.min, max: options.max, step: options.step,
                checked: options.type === 'checkbox' ? Boolean(value) : undefined,
            });
            control.dataset.teaField = field;
            if (options.values) {
                const hasSelectedValue = options.values.some(
                    ([optionValue]) => String(optionValue) === String(value)
                );
                if (!hasSelectedValue) {
                    const placeholder = technoeconomicNode('option', {
                        value: '', text: 'Select a value',
                    });
                    placeholder.selected = true;
                    control.appendChild(placeholder);
                }
                for (const [optionValue, label] of options.values) {
                    const option = technoeconomicNode('option', {value: optionValue, text: label});
                    if (String(optionValue) === String(value)) option.selected = true;
                    control.appendChild(option);
                }
            }
            return control;
        }

        function technoeconomicField(labelText, control, options = {}) {
            const wrapper = technoeconomicNode('div', {className: `tea-field${options.wide ? ' tea-field-wide' : ''}`});
            const id = `teaDynamic${++technoeconomicDynamicId}`;
            control.id = id;
            const label = technoeconomicNode('label', {text: labelText});
            label.htmlFor = id;
            wrapper.append(label, control);
            if (options.help) {
                const help = technoeconomicNode('p', {className: 'tea-field-help', text: options.help});
                wrapper.appendChild(help);
            }
            return wrapper;
        }

        function technoeconomicGrid(className = 'tea-dynamic-grid') {
            return technoeconomicNode('div', {className});
        }

        function technoeconomicReadField(root, name) {
            const control = root ? root.querySelector(`[data-tea-field="${name}"]`) : null;
            if (!control) return '';
            return control.type === 'checkbox' ? control.checked : control.value;
        }

        function technoeconomicAppendHeading(root, title, detail = '') {
            root.appendChild(technoeconomicNode('h5', {text: title}));
            if (detail) root.appendChild(technoeconomicNode('p', {className: 'tea-field-help', text: detail}));
        }

        function technoeconomicCreateEvidenceEditor(value, title = 'Evidence') {
            const evidence = technoeconomicSanitizeEvidence(value);
            const root = technoeconomicNode('section', {className: 'tea-evidence-editor'});
            root.dataset.teaRole = 'evidence';
            technoeconomicAppendHeading(
                root, title,
                'Citations are metadata plus an excerpt or derivation note; this browser does not claim to preserve source bytes.'
            );
            const grid = technoeconomicGrid('tea-evidence-grid');
            const evidenceClass = technoeconomicControl(
                'evidence_class', evidence.evidence_class, {values: TECHNOECONOMIC_EVIDENCE_CLASSES}
            );
            grid.append(
                technoeconomicField('Evidence class', evidenceClass),
                technoeconomicField('Title', technoeconomicControl('title', evidence.citation.title)),
                technoeconomicField('Organization', technoeconomicControl('organization', evidence.citation.organization)),
                technoeconomicField('HTTP(S) URL (optional)', technoeconomicControl('url', evidence.citation.url, {type: 'url'})),
                technoeconomicField('Stable reference (optional)', technoeconomicControl('stable_reference', evidence.citation.stable_reference)),
                technoeconomicField('Publication or as-of date', technoeconomicControl(
                    'publication_or_as_of_date', evidence.citation.publication_or_as_of_date, {type: 'date'}
                )),
                technoeconomicField('Accessed date', technoeconomicControl(
                    'accessed_date', evidence.citation.accessed_date, {type: 'date'}
                )),
                technoeconomicField('Excerpt or derivation note', technoeconomicControl(
                    'excerpt_or_derivation_note', evidence.citation.excerpt_or_derivation_note, {multiline: true}
                ), {wide: true}),
                technoeconomicField('Optional SHA-256 of user-supplied content', technoeconomicControl(
                    'user_supplied_content_sha256', evidence.citation.user_supplied_content_sha256,
                    {placeholder: '64 lowercase hexadecimal characters'}
                ), {wide: true}),
                technoeconomicField('Why metadata-only preservation is appropriate', technoeconomicControl(
                    'metadata_only_rationale', evidence.citation.metadata_only_rationale, {multiline: true}
                ), {wide: true})
            );
            root.appendChild(grid);
            const provisional = technoeconomicNode('div', {className: 'tea-provisional-fields'});
            provisional.dataset.teaProvisional = 'true';
            const accept = technoeconomicControl('explicit_acceptance', evidence.explicit_acceptance, {type: 'checkbox'});
            provisional.append(
                technoeconomicField('Explicitly accept this provisional evidence', accept, {
                    help: 'Required for engineering judgment and secondary synthesis.'
                }),
                technoeconomicField('Acceptance rationale', technoeconomicControl(
                    'acceptance_rationale', evidence.acceptance_rationale, {multiline: true}
                ), {wide: true})
            );
            root.appendChild(provisional);
            technoeconomicSyncEvidenceVisibility(root);
            evidenceClass.addEventListener('change', () => technoeconomicSyncEvidenceVisibility(root));
            return root;
        }

        function technoeconomicSyncEvidenceVisibility(root) {
            const evidenceClass = technoeconomicReadField(root, 'evidence_class');
            const provisional = root.querySelector('[data-tea-provisional="true"]');
            if (provisional) provisional.hidden = ![
                'engineering_judgment', 'secondary_synthesis',
            ].includes(evidenceClass);
        }

        function technoeconomicReadEvidence(root) {
            return technoeconomicSanitizeEvidence({
                evidence_class: technoeconomicReadField(root, 'evidence_class'),
                citation: {
                    title: technoeconomicReadField(root, 'title'),
                    organization: technoeconomicReadField(root, 'organization'),
                    url: technoeconomicReadField(root, 'url'),
                    stable_reference: technoeconomicReadField(root, 'stable_reference'),
                    publication_or_as_of_date: technoeconomicReadField(root, 'publication_or_as_of_date'),
                    accessed_date: technoeconomicReadField(root, 'accessed_date'),
                    excerpt_or_derivation_note: technoeconomicReadField(root, 'excerpt_or_derivation_note'),
                    user_supplied_content_sha256: technoeconomicReadField(root, 'user_supplied_content_sha256'),
                    metadata_only_rationale: technoeconomicReadField(root, 'metadata_only_rationale'),
                },
                explicit_acceptance: technoeconomicReadField(root, 'explicit_acceptance') === true,
                acceptance_rationale: technoeconomicReadField(root, 'acceptance_rationale'),
            });
        }

        function technoeconomicCreateDistributionEditor(value, title = 'Distribution') {
            const distribution = technoeconomicSanitizeDistribution(value);
            const root = technoeconomicNode('fieldset', {className: 'tea-distribution-editor'});
            root.dataset.teaRole = 'distribution';
            root.appendChild(technoeconomicNode('legend', {text: title}));
            const grid = technoeconomicGrid('tea-distribution-grid');
            const family = technoeconomicControl(
                'family', distribution.family, {values: TECHNOECONOMIC_DISTRIBUTION_FAMILIES}
            );
            grid.append(
                technoeconomicField('Family', family),
                technoeconomicField('Value', technoeconomicControl('value', distribution.value, {type: 'number', step: 'any'})),
                technoeconomicField('Low', technoeconomicControl('low', distribution.low, {type: 'number', step: 'any'})),
                technoeconomicField('Mode', technoeconomicControl('mode', distribution.mode, {type: 'number', step: 'any'})),
                technoeconomicField('High', technoeconomicControl('high', distribution.high, {type: 'number', step: 'any'})),
                technoeconomicField('Mean', technoeconomicControl('mean', distribution.mean, {type: 'number', step: 'any'})),
                technoeconomicField('Standard deviation', technoeconomicControl('sd', distribution.sd, {type: 'number', min: '0', step: 'any'}))
            );
            root.appendChild(grid);
            technoeconomicSyncDistributionVisibility(root);
            family.addEventListener('change', () => technoeconomicSyncDistributionVisibility(root));
            return root;
        }

        function technoeconomicSyncDistributionVisibility(root) {
            const family = technoeconomicReadField(root, 'family');
            const shown = family === 'fixed' ? ['value']
                : family === 'uniform' ? ['low', 'high']
                : family === 'triangular' ? ['low', 'mode', 'high']
                : ['low', 'high', 'mean', 'sd'];
            for (const name of ['value', 'low', 'mode', 'high', 'mean', 'sd']) {
                const control = root.querySelector(`[data-tea-field="${name}"]`);
                if (control && control.parentElement) control.parentElement.hidden = !shown.includes(name);
            }
        }

        function technoeconomicReadDistribution(root) {
            const value = {family: technoeconomicReadField(root, 'family')};
            for (const key of ['value', 'low', 'mode', 'high', 'mean', 'sd']) {
                value[key] = technoeconomicReadField(root, key);
            }
            return technoeconomicSanitizeDistribution(value);
        }

        function technoeconomicCreateDocumentedEditor(value, unit, title) {
            const documented = technoeconomicSanitizeDocumented(value, unit);
            const root = technoeconomicNode('div', {className: 'tea-documented-editor'});
            root.dataset.teaRole = 'documented';
            root.dataset.teaUnit = unit;
            root.append(
                technoeconomicCreateDistributionEditor(documented.distribution, title),
                technoeconomicCreateEvidenceEditor(documented.evidence, `${title} evidence`)
            );
            return root;
        }

        function technoeconomicReadDocumentedEditor(root, unit) {
            return {
                unit,
                distribution: technoeconomicReadDistribution(
                    root.querySelector('[data-tea-role="distribution"]')
                ),
                evidence: technoeconomicReadEvidence(
                    root.querySelector('[data-tea-role="evidence"]')
                ),
            };
        }

        function technoeconomicCreateCurrencyEditor(value, targetYear) {
            const currency = technoeconomicSanitizeCurrencyYear(value, targetYear);
            const root = technoeconomicNode('section', {className: 'tea-currency-editor'});
            root.dataset.teaRole = 'currency';
            technoeconomicAppendHeading(root, 'Currency-year normalization');
            const method = technoeconomicControl('method', currency.method, {values: [
                ['same_year_no_adjustment', 'Same year; no adjustment'],
                ['price_index_adjustment', 'Documented price-index adjustment'],
            ]});
            const grid = technoeconomicGrid();
            grid.append(
                technoeconomicField('Method', method),
                technoeconomicField('Source cost year', technoeconomicControl(
                    'source_cost_year', currency.source_cost_year, {type: 'number', min: '1900', max: '3000', step: '1'}
                )),
                technoeconomicField('Target constant-dollar year', technoeconomicControl(
                    'target_constant_dollar_cost_year', targetYear, {type: 'number', disabled: true}
                )),
                technoeconomicField('Index identity', technoeconomicControl('index_identity', currency.index_identity)),
                technoeconomicField('Index factor', technoeconomicControl(
                    'index_factor', currency.index_factor, {type: 'number', min: '0', step: 'any'}
                )),
                technoeconomicField('Derivation', technoeconomicControl(
                    'derivation', currency.derivation, {multiline: true}
                ), {wide: true})
            );
            root.appendChild(grid);
            const evidence = technoeconomicCreateEvidenceEditor(
                currency.index_source_evidence, 'Price-index evidence'
            );
            evidence.dataset.teaIndexEvidence = 'true';
            root.appendChild(evidence);
            technoeconomicSyncCurrencyVisibility(root);
            method.addEventListener('change', () => technoeconomicSyncCurrencyVisibility(root));
            return root;
        }

        function technoeconomicSyncCurrencyVisibility(root) {
            const sameYear = technoeconomicReadField(root, 'method') === 'same_year_no_adjustment';
            const evidence = root.querySelector('[data-tea-index-evidence="true"]');
            if (evidence) evidence.hidden = sameYear;
            if (sameYear) {
                const target = technoeconomicReadField(root, 'target_constant_dollar_cost_year');
                for (const [name, value] of [
                    ['source_cost_year', target], ['index_identity', 'not_applicable_same_year'],
                    ['index_factor', '1'],
                ]) {
                    const control = root.querySelector(`[data-tea-field="${name}"]`);
                    if (control) control.value = value;
                }
            }
        }

        function technoeconomicReadCurrencyEditor(root, targetYear) {
            return technoeconomicSanitizeCurrencyYear({
                method: technoeconomicReadField(root, 'method'),
                source_cost_year: technoeconomicReadField(root, 'source_cost_year'),
                index_identity: technoeconomicReadField(root, 'index_identity'),
                index_factor: technoeconomicReadField(root, 'index_factor'),
                derivation: technoeconomicReadField(root, 'derivation'),
                index_source_evidence: technoeconomicReadEvidence(
                    root.querySelector('[data-tea-index-evidence="true"]')
                ),
            }, targetYear);
        }

        function technoeconomicCreateCostLineEditor(value, index, costYear, basis) {
            const line = technoeconomicSanitizeCostLine(value, index, costYear, basis);
            const site = basis === 'solartac_site';
            const normalizedUnits = site ? [
                ['usd_per_applied_w', 'USD per applied W'],
                ['usd_per_applied_w_year', 'USD per applied W-year'],
            ] : [
                ['usd_per_wdc', 'USD per Wdc'], ['usd_per_wdc_year', 'USD per Wdc-year'],
            ];
            const normalizationMethods = site ? [
                ['divide_by_frozen_applied_capacity_w', 'Divide total by frozen applied capacity'],
                ['multiply_quantity_then_divide_by_frozen_applied_capacity_w',
                    'Multiply quantity then divide by frozen applied capacity'],
            ] : [
                ['already_normalized_per_wdc', 'Already normalized per Wdc'],
            ];
            const root = technoeconomicNode('article', {className: 'tea-cost-line tea-editor-card'});
            root.dataset.teaRole = 'cost-line';
            const header = technoeconomicNode('div', {className: 'tea-section-heading'});
            header.append(
                technoeconomicNode('h4', {text: `Cost line ${index + 1}`}),
                technoeconomicNode('button', {className: 'tea-button tea-button-danger', type: 'button', text: 'Remove'})
            );
            header.lastElementChild.dataset.teaAction = 'remove-cost-line';
            root.appendChild(header);
            const grid = technoeconomicGrid();
            grid.append(
                technoeconomicField('Stable input ID', technoeconomicControl('input_id', line.input_id)),
                technoeconomicField('Label', technoeconomicControl('label', line.label)),
                technoeconomicField('Ownership', technoeconomicControl('ownership', line.ownership, {values: [
                    ['solectria_only', 'Solectria only'], ['solaredge_only', 'SolarEdge only'],
                    ['paired_shared', 'Paired or shared'],
                ]})),
                technoeconomicField('Cost type', technoeconomicControl('cost_type', line.cost_type, {values: [
                    ['initial_capex', 'Initial CAPEX'],
                    ['initial_installation_labor', 'Initial installation labor'],
                    ['recurring_labor', 'Recurring labor'], ['recurring_om', 'Recurring O&M'],
                    ['recurring_maintenance', 'Recurring maintenance'],
                ]})),
                technoeconomicField('Coverage include IDs', technoeconomicControl(
                    'coverage_include_ids', line.coverage_include_ids.join(', ')
                ), {wide: true, help: 'Comma-separated stable component or scope IDs.'}),
                technoeconomicField('Coverage exclude IDs', technoeconomicControl(
                    'coverage_exclude_ids', line.coverage_exclude_ids.join(', ')
                ), {wide: true}),
                technoeconomicField('Original unit', technoeconomicControl('original_unit', line.original_unit, {values: [
                    ['usd_total', 'USD total'], ['usd_total_per_year', 'USD total per year'],
                    ['usd_per_unit', 'USD per unit'], ['usd_per_unit_year', 'USD per unit-year'],
                    ['usd_per_wdc', 'USD per Wdc'], ['usd_per_wdc_year', 'USD per Wdc-year'],
                ]})),
                technoeconomicField('Normalized unit', technoeconomicControl(
                    'normalized_unit', line.normalized_unit, {values: normalizedUnits}
                )),
                technoeconomicField('Normalization method', technoeconomicControl(
                    'normalization_method', line.normalization_method,
                    {values: normalizationMethods}
                ), {wide: true}),
                technoeconomicField('Solectria quantity', technoeconomicControl(
                    'solectria_quantity', line.solectria_quantity, {type: 'number', min: '0', step: 'any'}
                )),
                technoeconomicField('SolarEdge quantity', technoeconomicControl(
                    'solaredge_quantity', line.solaredge_quantity, {type: 'number', min: '0', step: 'any'}
                )),
                technoeconomicField('Quantity unit (when per-unit)', technoeconomicControl(
                    'quantity_unit', line.quantity_unit
                )),
                technoeconomicField('Normalization derivation', technoeconomicControl(
                    'normalization_derivation', line.normalization_derivation, {multiline: true}
                ), {wide: true})
            );
            root.append(
                grid,
                technoeconomicCreateDistributionEditor(line.distribution, 'Submitted target-year cost distribution'),
                technoeconomicCreateCurrencyEditor(line.currency_year_normalization, costYear),
                technoeconomicCreateEvidenceEditor(line.evidence, 'Cost evidence')
            );
            return root;
        }

        function technoeconomicReadCostLineEditor(root, index, costYear, basis) {
            return technoeconomicSanitizeCostLine({
                input_id: technoeconomicReadField(root, 'input_id'),
                label: technoeconomicReadField(root, 'label'),
                ownership: technoeconomicReadField(root, 'ownership'),
                cost_type: technoeconomicReadField(root, 'cost_type'),
                distribution: technoeconomicReadDistribution(
                    root.querySelector('[data-tea-role="distribution"]')
                ),
                coverage_include_ids: technoeconomicReadField(root, 'coverage_include_ids'),
                coverage_exclude_ids: technoeconomicReadField(root, 'coverage_exclude_ids'),
                original_unit: technoeconomicReadField(root, 'original_unit'),
                normalized_unit: technoeconomicReadField(root, 'normalized_unit'),
                normalization_method: technoeconomicReadField(root, 'normalization_method'),
                solectria_quantity: technoeconomicReadField(root, 'solectria_quantity'),
                solaredge_quantity: technoeconomicReadField(root, 'solaredge_quantity'),
                quantity_unit: technoeconomicReadField(root, 'quantity_unit'),
                normalization_derivation: technoeconomicReadField(root, 'normalization_derivation'),
                currency_year_normalization: technoeconomicReadCurrencyEditor(
                    root.querySelector('[data-tea-role="currency"]'), costYear
                ),
                evidence: technoeconomicReadEvidence(
                    Array.from(root.querySelectorAll('[data-tea-role="evidence"]')).at(-1)
                ),
            }, index, costYear, basis);
        }

        function technoeconomicCreateTechnologyEditor(value, system) {
            const solaredge = system === 'solaredge';
            const design = technoeconomicSanitizeTechnology(value, solaredge);
            const root = technoeconomicNode('fieldset', {className: 'tea-technology-editor'});
            root.dataset.teaRole = `technology-${system}`;
            root.appendChild(technoeconomicNode('legend', {
                text: solaredge ? 'SolarEdge design' : 'Solectria design',
            }));
            const grid = technoeconomicGrid('tea-design-grid');
            for (const [key, label, type] of [
                ['optimizer_count', 'Optimizer count', 'number'],
                ['inverter_count', 'Inverter count', 'number'],
                ['transformer_count', 'Transformer count', 'number'],
                ['dc_ac_ratio', 'DC/AC ratio', 'number'],
                ['inverter_loading_ratio', 'Inverter loading ratio', 'number'],
                ['inverter_topology', 'Inverter topology', 'text'],
                ['transformer_topology', 'Transformer topology', 'text'],
                ['bos_scope', 'Balance-of-system scope', 'textarea'],
                ['labor_productivity_and_rates', 'Labor productivity and rates', 'textarea'],
                ['commissioning_scope', 'Commissioning scope', 'textarea'],
            ]) {
                const integer = ['optimizer_count', 'inverter_count', 'transformer_count'].includes(key);
                grid.appendChild(technoeconomicField(label, technoeconomicControl(key, design[key], {
                    type: type === 'number' ? 'number' : 'text',
                    multiline: type === 'textarea', min: type === 'number' ? '0' : undefined,
                    step: integer ? '1' : type === 'number' ? 'any' : undefined,
                }), {wide: type === 'textarea'}));
            }
            root.appendChild(grid);
            return root;
        }

        function technoeconomicReadTechnologyEditor(root, solaredge) {
            const value = {};
            for (const key of Object.keys(technoeconomicDefaultTechnologyDesign(solaredge))) {
                value[key] = technoeconomicReadField(root, key);
            }
            return technoeconomicSanitizeTechnology(value, solaredge);
        }

        function technoeconomicCreateCommercialDesignEditor(value, costYear) {
            const design = technoeconomicSanitizeCommercialDesign(value, costYear);
            const root = technoeconomicNode('div', {className: 'tea-commercial-design-editor'});
            root.dataset.teaRole = 'commercial-design';
            const grid = technoeconomicGrid('tea-design-grid');
            grid.append(
                technoeconomicField('Stable design ID', technoeconomicControl('design_id', design.design_id)),
                technoeconomicField('Reference capacity (Wdc)', technoeconomicControl(
                    'reference_wdc', design.reference_wdc, {type: 'number', min: '0', step: 'any'}
                )),
                technoeconomicField('Module model', technoeconomicControl('module_model', design.module_model)),
                technoeconomicField('Module STC rating (Wdc)', technoeconomicControl(
                    'module_stc_wdc', design.module_stc_wdc, {type: 'number', min: '0', step: 'any'}
                )),
                technoeconomicField('Module count', technoeconomicControl(
                    'module_count', design.module_count, {type: 'number', min: '1', step: '1'}
                )),
                technoeconomicField('Normalization derivation', technoeconomicControl(
                    'normalization_derivation', design.normalization_derivation, {multiline: true}
                ), {wide: true, help: 'Reference Wdc must equal module count multiplied by module STC Wdc.'})
            );
            root.append(
                grid,
                technoeconomicCreateTechnologyEditor(design.solectria, 'solectria'),
                technoeconomicCreateTechnologyEditor(design.solaredge, 'solaredge'),
                technoeconomicCreateEvidenceEditor(design.evidence, 'Commercial reference-design evidence')
            );
            return root;
        }

        function technoeconomicReadCommercialDesignEditor(root, costYear) {
            return technoeconomicSanitizeCommercialDesign({
                design_id: technoeconomicReadField(root, 'design_id'),
                reference_wdc: technoeconomicReadField(root, 'reference_wdc'),
                module_model: technoeconomicReadField(root, 'module_model'),
                module_stc_wdc: technoeconomicReadField(root, 'module_stc_wdc'),
                module_count: technoeconomicReadField(root, 'module_count'),
                normalization_derivation: technoeconomicReadField(root, 'normalization_derivation'),
                solectria: technoeconomicReadTechnologyEditor(
                    root.querySelector('[data-tea-role="technology-solectria"]'), false
                ),
                solaredge: technoeconomicReadTechnologyEditor(
                    root.querySelector('[data-tea-role="technology-solaredge"]'), true
                ),
                evidence: technoeconomicReadEvidence(
                    root.querySelector('[data-tea-role="evidence"]')
                ),
            }, costYear);
        }

        function technoeconomicCreateTransferEditor(value) {
            const transfer = technoeconomicSanitizeTransfer(value);
            const root = technoeconomicNode('div', {className: 'tea-transfer-editor-inner'});
            root.dataset.teaRole = 'commercial-transfer';
            const grid = technoeconomicGrid('tea-transfer-grid');
            grid.append(
                technoeconomicField('Attested by', technoeconomicControl('attested_by', transfer.attested_by)),
                technoeconomicField('Attested at (ISO-8601 with UTC offset)', technoeconomicControl(
                    'attested_at', transfer.attested_at, {placeholder: '2026-08-14T12:00:00-06:00'}
                )),
                technoeconomicField('Attestation rationale', technoeconomicControl(
                    'attestation_rationale', transfer.attestation_rationale, {multiline: true}
                ), {wide: true})
            );
            const attestation = technoeconomicControl(
                'explicit_attestation', transfer.explicit_attestation, {type: 'checkbox'}
            );
            grid.appendChild(technoeconomicField(
                'I explicitly attest that every transfer mechanism below was reviewed',
                attestation, {wide: true}
            ));
            root.append(
                grid,
                technoeconomicCreateDocumentedEditor(
                    transfer.baseline_factor, 'dimensionless_multiplier', 'Baseline transfer factor'
                ),
                technoeconomicCreateDocumentedEditor(
                    transfer.incremental_factor, 'dimensionless_multiplier', 'Incremental transfer factor'
                )
            );
            const mechanisms = technoeconomicNode('div', {className: 'tea-transfer-mechanisms'});
            mechanisms.appendChild(technoeconomicNode('h5', {text: 'Complete transfer-mechanism checklist'}));
            for (const item of transfer.mechanisms) {
                const card = technoeconomicNode('section', {className: 'tea-transfer-mechanism'});
                card.dataset.teaRole = 'transfer-mechanism';
                card.dataset.teaMechanism = item.mechanism;
                card.appendChild(technoeconomicNode('h6', {
                    text: item.mechanism.replaceAll('_', ' '),
                }));
                const itemGrid = technoeconomicGrid('tea-transfer-grid');
                itemGrid.append(
                    technoeconomicField('Status', technoeconomicControl('status', item.status, {values: [
                        ['supported', 'Supported'], ['not_applicable', 'Not applicable'],
                        ['not_transferred', 'Not transferred (blocks approval)'],
                    ]})),
                    technoeconomicField('Rationale', technoeconomicControl(
                        'rationale', item.rationale, {multiline: true}
                    ), {wide: true})
                );
                card.append(
                    itemGrid,
                    technoeconomicCreateEvidenceEditor(item.evidence, `${item.mechanism.replaceAll('_', ' ')} evidence`)
                );
                mechanisms.appendChild(card);
            }
            root.appendChild(mechanisms);
            return root;
        }

        function technoeconomicReadTransferEditor(root) {
            const documented = root.querySelectorAll('[data-tea-role="documented"]');
            const mechanisms = Array.from(
                root.querySelectorAll('[data-tea-role="transfer-mechanism"]')
            ).map((card) => ({
                mechanism: card.dataset.teaMechanism,
                status: technoeconomicReadField(card, 'status'),
                rationale: technoeconomicReadField(card, 'rationale'),
                evidence: technoeconomicReadEvidence(card.querySelector('[data-tea-role="evidence"]')),
            }));
            return technoeconomicSanitizeTransfer({
                explicit_attestation: technoeconomicReadField(root, 'explicit_attestation') === true,
                attested_by: technoeconomicReadField(root, 'attested_by'),
                attested_at: technoeconomicReadField(root, 'attested_at'),
                attestation_rationale: technoeconomicReadField(root, 'attestation_rationale'),
                baseline_factor: technoeconomicReadDocumentedEditor(
                    documented[0], 'dimensionless_multiplier'
                ),
                incremental_factor: technoeconomicReadDocumentedEditor(
                    documented[1], 'dimensionless_multiplier'
                ),
                mechanisms,
            });
        }

        function technoeconomicRenderCostLines(lines, costYear, basis) {
            const container = technoeconomicElements.costLines;
            if (!container) return;
            container.replaceChildren();
            lines.forEach((line, index) => container.appendChild(
                technoeconomicCreateCostLineEditor(line, index, costYear, basis)
            ));
            if (technoeconomicElements.costLinesEmpty) {
                technoeconomicElements.costLinesEmpty.hidden = lines.length > 0;
            }
        }

        function technoeconomicRenderBasisVisibility() {
            const commercial = technoeconomicElements.basis?.value === 'commercial_representative';
            if (technoeconomicElements.commercialDesign) {
                technoeconomicElements.commercialDesign.hidden = !commercial;
            }
            if (technoeconomicElements.commercialTransfer) {
                technoeconomicElements.commercialTransfer.hidden = !commercial;
            }
            if (technoeconomicElements.commercialTransferEditor) {
                technoeconomicElements.commercialTransferEditor.hidden = !(
                    commercial && technoeconomicElements.transferEnabled?.checked
                );
            }
        }

        function technoeconomicRenderEditors(draft) {
            technoeconomicDynamicId = 0;
            technoeconomicElements.projectLifeEvidence?.replaceChildren(
                technoeconomicCreateEvidenceEditor(draft.project_life_evidence, 'Project-life evidence')
            );
            technoeconomicElements.discountRateEditor?.replaceChildren(
                technoeconomicCreateDocumentedEditor(
                    draft.discount_rate, 'real_fraction_per_year', 'Real discount-rate distribution'
                )
            );
            technoeconomicElements.degradationEditor?.replaceChildren(
                technoeconomicCreateDocumentedEditor(
                    draft.shared_degradation, 'real_fraction_per_year', 'Shared degradation distribution'
                )
            );
            technoeconomicRenderCostLines(draft.cost_lines, draft.cost_year, draft.basis);
            technoeconomicElements.commercialDesignEditor?.replaceChildren(
                technoeconomicCreateCommercialDesignEditor(
                    draft.commercial_reference_design, draft.cost_year
                )
            );
            technoeconomicElements.commercialTransferEditor?.replaceChildren(
                technoeconomicCreateTransferEditor(draft.commercial_transfer)
            );
            technoeconomicRenderBasisVisibility();
        }

        function getTechnoeconomicFormState() {
            if (typeof document !== 'object' || !technoeconomicElements?.form) {
                return sanitizeTechnoeconomicDraft({active_job_id: null});
            }
            const costYear = technoeconomicElements.costYear?.value || '';
            const basis = technoeconomicElements.basis?.value || '';
            const costLines = Array.from(
                technoeconomicElements.costLines?.querySelectorAll('[data-tea-role="cost-line"]') || []
            ).map((card, index) => technoeconomicReadCostLineEditor(card, index, costYear, basis));
            const projectEvidence = technoeconomicElements.projectLifeEvidence
                ?.querySelector('[data-tea-role="evidence"]');
            const discount = technoeconomicElements.discountRateEditor
                ?.querySelector('[data-tea-role="documented"]');
            const degradation = technoeconomicElements.degradationEditor
                ?.querySelector('[data-tea-role="documented"]');
            const design = technoeconomicElements.commercialDesignEditor
                ?.querySelector('[data-tea-role="commercial-design"]');
            const transfer = technoeconomicElements.commercialTransferEditor
                ?.querySelector('[data-tea-role="commercial-transfer"]');
            const advancedDraft = sanitizeTechnoeconomicDraft({
                entry_mode: technoeconomicEntryMode,
                provisional_reference_applied: false,
                source_annual_job_id: technoeconomicElements.sourceSelect?.value || '',
                basis, n: technoeconomicElements.realizations?.value || '',
                seed: technoeconomicElements.seed?.value || '', cost_year: costYear,
                project_life_years: technoeconomicElements.projectLife?.value || '',
                project_life_evidence: projectEvidence
                    ? technoeconomicReadEvidence(projectEvidence) : technoeconomicDefaultEvidence(),
                discount_rate: discount
                    ? technoeconomicReadDocumentedEditor(discount, 'real_fraction_per_year')
                    : technoeconomicDefaultDocumented('real_fraction_per_year', ''),
                shared_degradation: degradation
                    ? technoeconomicReadDocumentedEditor(degradation, 'real_fraction_per_year')
                    : technoeconomicDefaultDocumented('real_fraction_per_year', ''),
                cost_lines: costLines,
                commercial_reference_design: design
                    ? technoeconomicReadCommercialDesignEditor(design, costYear)
                    : technoeconomicDefaultCommercialDesign(),
                transfer_enabled: technoeconomicElements.transferEnabled?.checked === true,
                commercial_transfer: transfer
                    ? technoeconomicReadTransferEditor(transfer) : technoeconomicDefaultCommercialTransfer(),
                active_job_id: null,
            });
            if (technoeconomicEntryMode !== TECHNOECONOMIC_GUIDED_ENTRY_MODE) {
                return advancedDraft;
            }
            return technoeconomicBuildGuidedDraft(
                advancedDraft, technoeconomicReadGuidedForm(), {
                    seed: advancedDraft.seed || technoeconomicGenerateSafeSeed(),
                }
            );
        }

        function technoeconomicEnsureSourceOption(sourceId) {
            if (sourceId && !technoeconomicPendingSourceId) {
                technoeconomicPendingSourceId = sourceId;
            }
        }

        function applyTechnoeconomicFormState(value) {
            if (typeof document !== 'object' || typeof technoeconomicElements === 'undefined'
                || !technoeconomicElements.form) return false;
            let candidate = value;
            if (candidate === undefined) candidate = technoeconomicLoadLocalDraft()
                || technoeconomicDefaultDraft();
            else if (candidate === null) candidate = technoeconomicDefaultDraft();
            else {
                candidate = technoeconomicMigrateDraftCandidate(candidate);
                if (!candidate) return false;
            }
            const draft = sanitizeTechnoeconomicDraft(candidate);
            if (draft.entry_mode === TECHNOECONOMIC_GUIDED_ENTRY_MODE && !draft.seed) {
                draft.seed = technoeconomicGenerateSafeSeed();
            }
            technoeconomicApplyingDraft = true;
            try {
                technoeconomicEntryMode = draft.entry_mode;
                technoeconomicEnsureSourceOption(draft.source_annual_job_id);
                technoeconomicElements.sourceSelect.value = draft.source_annual_job_id;
                technoeconomicElements.basis.value = draft.basis;
                technoeconomicElements.realizations.value = draft.n;
                technoeconomicElements.seed.value = draft.seed;
                technoeconomicElements.costYear.value = draft.cost_year;
                technoeconomicElements.projectLife.value = draft.project_life_years;
                technoeconomicElements.transferEnabled.checked = draft.transfer_enabled;
                technoeconomicRenderEditors(draft);
                technoeconomicRenderGuidedForm(draft);
                technoeconomicRenderEntryMode();
                technoeconomicRenderSelectedSource();
            } finally {
                technoeconomicApplyingDraft = false;
            }
            return true;
        }

        function technoeconomicPersistDraft() {
            if (typeof localStorage !== 'object') {
                if (technoeconomicElements?.draftStatus) {
                    technoeconomicElements.draftStatus.textContent =
                        'Draft could not be saved because browser storage is unavailable.';
                }
                return false;
            }
            try {
                const draft = getTechnoeconomicFormState();
                draft.active_job_id = null;
                localStorage.setItem(
                    TECHNOECONOMIC_DRAFT_STORAGE_KEY,
                    JSON.stringify(sanitizeTechnoeconomicDraft(draft))
                );
                return true;
            } catch (_error) {
                // Private browsing or a full storage quota must not block submission.
                if (technoeconomicElements?.draftStatus) {
                    technoeconomicElements.draftStatus.textContent =
                        'Draft could not be saved. Browser storage is unavailable or full.';
                }
                return false;
            }
        }

        function technoeconomicLoadLocalDraft() {
            if (typeof localStorage !== 'object') return null;
            const read = (key) => {
                try {
                    return JSON.parse(localStorage.getItem(key) || 'null');
                } catch (_error) {
                    return null;
                }
            };
            const parsed = read(TECHNOECONOMIC_DRAFT_STORAGE_KEY);
            if (parsed?.schema_version === TECHNOECONOMIC_DRAFT_SCHEMA_VERSION) {
                return sanitizeTechnoeconomicDraft(parsed);
            }
            const previous = read(TECHNOECONOMIC_PREVIOUS_DRAFT_STORAGE_KEY);
            if (previous?.schema_version === TECHNOECONOMIC_PREVIOUS_DRAFT_SCHEMA_VERSION) {
                return technoeconomicMigrateDraftCandidate(previous);
            }
            const legacy = read(TECHNOECONOMIC_LEGACY_DRAFT_STORAGE_KEY);
            if (legacy?.schema_version !== TECHNOECONOMIC_LEGACY_DRAFT_SCHEMA_VERSION) return null;
            return technoeconomicMigrateDraftCandidate(legacy);
        }

        function technoeconomicMigrateDraftCandidate(value) {
            const source = technoeconomicPlainObject(value);
            if (source.schema_version === TECHNOECONOMIC_DRAFT_SCHEMA_VERSION) {
                return sanitizeTechnoeconomicDraft(source);
            }
            if (source.schema_version === TECHNOECONOMIC_PREVIOUS_DRAFT_SCHEMA_VERSION) {
                return sanitizeTechnoeconomicDraft({
                    ...source, schema_version: TECHNOECONOMIC_DRAFT_SCHEMA_VERSION,
                });
            }
            if (source.schema_version === TECHNOECONOMIC_LEGACY_DRAFT_SCHEMA_VERSION) {
                return sanitizeTechnoeconomicDraft({
                    ...source,
                    schema_version: TECHNOECONOMIC_DRAFT_SCHEMA_VERSION,
                    entry_mode: TECHNOECONOMIC_ADVANCED_ENTRY_MODE,
                });
            }
            return null;
        }

        function technoeconomicMarkDraftChanged(action = 'Draft updated.') {
            if (technoeconomicApplyingDraft) return;
            technoeconomicDraftRevision += 1;
            if (technoeconomicElements.draftStatus) {
                technoeconomicElements.draftStatus.textContent = `${action} Saving in this browser...`;
            }
            clearTimeout(technoeconomicDraftSaveTimer);
            technoeconomicDraftSaveTimer = setTimeout(() => {
                const saved = technoeconomicPersistDraft()
                    && technoeconomicPersistStandaloneDraft();
                if (typeof saveDashboardState === 'function') saveDashboardState();
                if (technoeconomicElements.draftStatus) {
                    technoeconomicElements.draftStatus.textContent = saved
                        ? `${action} Draft saved in this browser.`
                        : `${action} Draft could not be saved. Keep this page open and copy important evidence before leaving.`;
                }
                if (typeof updateAgentContext === 'function') updateAgentContext();
            }, 250);
        }

        function technoeconomicAddCostLine() {
            const draft = getTechnoeconomicFormState();
            draft.cost_lines.push(technoeconomicDefaultCostLine(
                draft.cost_lines.length % 2 ? 'solaredge' : 'solectria',
                draft.cost_lines.length
            ));
            draft.cost_lines.at(-1).constant_dollar_cost_year = draft.cost_year;
            draft.cost_lines.at(-1).currency_year_normalization = technoeconomicDefaultCurrencyYear(
                draft.cost_year
            );
            technoeconomicRenderCostLines(draft.cost_lines, draft.cost_year, draft.basis);
            technoeconomicMarkDraftChanged('Cost line added.');
        }

        function technoeconomicRemoveCostLine(button) {
            const card = button.closest('[data-tea-role="cost-line"]');
            if (!card) return;
            const draft = getTechnoeconomicFormState();
            const cards = Array.from(technoeconomicElements.costLines.querySelectorAll(
                '[data-tea-role="cost-line"]'
            ));
            const index = cards.indexOf(card);
            if (index >= 0) draft.cost_lines.splice(index, 1);
            technoeconomicRenderCostLines(draft.cost_lines, draft.cost_year, draft.basis);
            technoeconomicMarkDraftChanged('Cost line removed.');
        }

        function technoeconomicPushError(errors, path, message) {
            errors.push({path, message});
        }

        function technoeconomicStrictText(value, path, errors, options = {}) {
            const text = typeof value === 'string' ? value.trim() : '';
            const maximum = options.maximum || 4000;
            if (!text && !options.optional) {
                technoeconomicPushError(errors, path, 'A value is required.');
                return '';
            }
            if (text.length > maximum) {
                technoeconomicPushError(errors, path, `Must contain at most ${maximum} characters.`);
            }
            const illegalXml = Array.from(text).some((character) => {
                const codepoint = character.codePointAt(0);
                return (codepoint < 0x20 && ![0x09, 0x0A, 0x0D].includes(codepoint))
                    || (codepoint >= 0xD800 && codepoint <= 0xDFFF)
                    || codepoint === 0xFFFE || codepoint === 0xFFFF;
            });
            if (illegalXml) {
                technoeconomicPushError(errors, path, 'Contains a character that cannot be exported to XLSX.');
            }
            return text;
        }

        function technoeconomicStableId(value, path, errors) {
            const text = technoeconomicStrictText(value, path, errors, {maximum: 160});
            if (text && !/^[a-z0-9._:-]+$/.test(text)) {
                technoeconomicPushError(
                    errors, path, 'Use only lowercase letters, numbers, period, underscore, colon, or hyphen.'
                );
            }
            return text;
        }

        function technoeconomicFiniteNumber(value, path, errors, options = {}) {
            const raw = typeof value === 'string' ? value.trim() : value;
            if (raw === '' || raw === null || raw === undefined) {
                technoeconomicPushError(errors, path, 'A finite number is required.');
                return null;
            }
            if (typeof raw === 'string'
                && !/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/.test(raw)) {
                technoeconomicPushError(errors, path, 'Enter a decimal number.');
                return null;
            }
            const number = Number(raw);
            if (!Number.isFinite(number)) {
                technoeconomicPushError(errors, path, 'Enter a finite number.');
                return null;
            }
            if (options.integer && !Number.isSafeInteger(number)) {
                technoeconomicPushError(errors, path, 'Enter a safe whole number.');
            }
            if (options.min !== undefined && number < options.min) {
                technoeconomicPushError(errors, path, `Must be at least ${options.min}.`);
            }
            if (options.max !== undefined && number > options.max) {
                technoeconomicPushError(errors, path, `Must be no greater than ${options.max}.`);
            }
            if (options.positive && !(number > 0)) {
                technoeconomicPushError(errors, path, 'Must be greater than zero.');
            }
            return number;
        }

        function technoeconomicDecimalParts(value) {
            const text = typeof value === 'string' ? value.trim() : String(value ?? '').trim();
            const match = /^([+-]?)(\d*)(?:\.(\d*))?(?:[eE]([+-]?\d+))?$/.exec(text);
            if (!match || !(match[2] || match[3])) return null;
            const exponent = Number(match[4] || 0);
            if (!Number.isSafeInteger(exponent) || Math.abs(exponent) > 1000) return null;
            const fraction = match[3] || '';
            const digits = `${match[2] || ''}${fraction}`.replace(/^0+/, '') || '0';
            let coefficient = BigInt(digits);
            if (match[1] === '-') coefficient = -coefficient;
            let scale = fraction.length - exponent;
            if (scale < 0) {
                coefficient *= 10n ** BigInt(-scale);
                scale = 0;
            }
            while (scale > 0 && coefficient % 10n === 0n) {
                coefficient /= 10n;
                scale -= 1;
            }
            return {coefficient, scale};
        }

        function technoeconomicDecimalEqualsIntegerProduct(reference, multiplicand, multiplier) {
            const recorded = technoeconomicDecimalParts(reference);
            const unit = technoeconomicDecimalParts(multiplicand);
            if (!recorded || !unit || !Number.isSafeInteger(multiplier)) return false;
            const derived = {
                coefficient: unit.coefficient * BigInt(multiplier),
                scale: unit.scale,
            };
            const scale = Math.max(recorded.scale, derived.scale);
            const recordedCoefficient = recorded.coefficient
                * (10n ** BigInt(scale - recorded.scale));
            const derivedCoefficient = derived.coefficient
                * (10n ** BigInt(scale - derived.scale));
            return recordedCoefficient === derivedCoefficient;
        }

        function technoeconomicIsoDate(value, path, errors) {
            const text = technoeconomicStrictText(value, path, errors);
            const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(text);
            let valid = false;
            if (match) {
                const year = Number(match[1]);
                const month = Number(match[2]);
                const day = Number(match[3]);
                const leap = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
                const days = [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
                valid = year >= 1 && month >= 1 && month <= 12
                    && day >= 1 && day <= days[month - 1];
            }
            if (!valid) {
                technoeconomicPushError(errors, path, 'Use a valid date in YYYY-MM-DD form.');
            }
            return text;
        }

        function technoeconomicSerializeEvidence(value, path, errors, context) {
            const evidence = technoeconomicSanitizeEvidence(value);
            context.evidenceCount += 1;
            const evidenceClass = evidence.evidence_class;
            if (!TECHNOECONOMIC_EVIDENCE_CLASSES.some((item) => item[0] === evidenceClass)) {
                technoeconomicPushError(errors, `${path}.evidence_class`, 'Select a supported evidence class.');
            }
            const provisional = ['engineering_judgment', 'secondary_synthesis'].includes(evidenceClass);
            if (provisional) context.provisionalEvidenceCount += 1;
            const urlText = technoeconomicStrictText(
                evidence.citation.url, `${path}.citation.url`, errors, {optional: true}
            );
            if (urlText) {
                try {
                    const parsed = new URL(urlText);
                    if (!['http:', 'https:'].includes(parsed.protocol)) throw new Error('unsupported');
                } catch (_error) {
                    technoeconomicPushError(errors, `${path}.citation.url`, 'Use a complete HTTP(S) URL.');
                }
            }
            const stableReference = technoeconomicStrictText(
                evidence.citation.stable_reference,
                `${path}.citation.stable_reference`, errors, {optional: true}
            );
            if (!urlText && !stableReference) {
                technoeconomicPushError(
                    errors, `${path}.citation`, 'Provide either an HTTP(S) URL or a stable reference.'
                );
            }
            const hash = technoeconomicStrictText(
                evidence.citation.user_supplied_content_sha256,
                `${path}.citation.user_supplied_content_sha256`, errors, {optional: true}
            );
            if (hash && !/^[0-9a-f]{64}$/.test(hash)) {
                technoeconomicPushError(errors, `${path}.citation.user_supplied_content_sha256`,
                    'Use exactly 64 lowercase hexadecimal characters.');
            }
            const explicitlyAccepted = evidence.explicit_acceptance === true;
            let rationale = null;
            if (provisional || explicitlyAccepted) {
                if (evidence.explicit_acceptance !== true) {
                    technoeconomicPushError(errors, `${path}.explicit_acceptance`,
                        'Explicit acceptance is required for provisional evidence.');
                }
                rationale = technoeconomicStrictText(
                    evidence.acceptance_rationale, `${path}.acceptance_rationale`, errors
                );
            }
            return {
                evidence_class: evidenceClass,
                citation: {
                    title: technoeconomicStrictText(
                        evidence.citation.title, `${path}.citation.title`, errors
                    ),
                    organization: technoeconomicStrictText(
                        evidence.citation.organization, `${path}.citation.organization`, errors
                    ),
                    url: urlText || null,
                    stable_reference: stableReference || null,
                    publication_or_as_of_date: technoeconomicIsoDate(
                        evidence.citation.publication_or_as_of_date,
                        `${path}.citation.publication_or_as_of_date`, errors
                    ),
                    accessed_date: technoeconomicIsoDate(
                        evidence.citation.accessed_date, `${path}.citation.accessed_date`, errors
                    ),
                    excerpt_or_derivation_note: technoeconomicStrictText(
                        evidence.citation.excerpt_or_derivation_note,
                        `${path}.citation.excerpt_or_derivation_note`, errors
                    ),
                    preservation_mode: 'metadata_excerpt_only',
                    user_supplied_content_sha256: hash || null,
                    metadata_only_rationale: technoeconomicStrictText(
                        evidence.citation.metadata_only_rationale,
                        `${path}.citation.metadata_only_rationale`, errors
                    ),
                },
                explicit_acceptance: explicitlyAccepted ? true : null,
                acceptance_rationale: explicitlyAccepted ? rationale : null,
            };
        }

        function technoeconomicSerializeDistribution(value, path, errors, role) {
            const distribution = technoeconomicSanitizeDistribution(value);
            let payload;
            let supportLow = null;
            let supportHigh = null;
            const allowedFamilies = TECHNOECONOMIC_DISTRIBUTION_FAMILIES.map((item) => item[0]);
            if (!allowedFamilies.includes(distribution.family)) {
                technoeconomicPushError(errors, `${path}.family`, 'Select a supported distribution family.');
                return {
                    payload: {family: distribution.family},
                    supportLow: null, supportHigh: null, nonfixed: false,
                };
            }
            if (distribution.family === 'fixed') {
                const fixed = technoeconomicFiniteNumber(distribution.value, `${path}.value`, errors);
                payload = {family: 'fixed', value: fixed};
                supportLow = fixed;
                supportHigh = fixed;
            } else if (distribution.family === 'uniform') {
                const low = technoeconomicFiniteNumber(distribution.low, `${path}.low`, errors);
                const high = technoeconomicFiniteNumber(distribution.high, `${path}.high`, errors);
                payload = {family: 'uniform', low, high};
                supportLow = low;
                supportHigh = high;
                if (low !== null && high !== null && low > high) {
                    technoeconomicPushError(errors, path, 'Uniform distributions require low less than or equal to high.');
                }
            } else if (distribution.family === 'triangular') {
                const low = technoeconomicFiniteNumber(distribution.low, `${path}.low`, errors);
                const mode = technoeconomicFiniteNumber(distribution.mode, `${path}.mode`, errors);
                const high = technoeconomicFiniteNumber(distribution.high, `${path}.high`, errors);
                payload = {family: 'triangular', low, mode, high};
                supportLow = low;
                supportHigh = high;
                if (low !== null && mode !== null && high !== null && !(low <= mode && mode <= high)) {
                    technoeconomicPushError(errors, path,
                        'Triangular distributions require low less than or equal to mode, and mode less than or equal to high.');
                }
            } else {
                const low = technoeconomicFiniteNumber(distribution.low, `${path}.low`, errors);
                const high = technoeconomicFiniteNumber(distribution.high, `${path}.high`, errors);
                const mean = technoeconomicFiniteNumber(distribution.mean, `${path}.mean`, errors);
                const sd = technoeconomicFiniteNumber(distribution.sd, `${path}.sd`, errors, {positive: true});
                payload = {family: 'bounded_normal', low, high, mean, sd};
                supportLow = low;
                supportHigh = high;
                if (low !== null && high !== null && !(low < high)) {
                    technoeconomicPushError(errors, path, 'Bounded-normal distributions require low less than high.');
                }
            }
            if (supportLow !== null && supportHigh !== null) {
                if (role === 'cost' && supportLow < 0) {
                    technoeconomicPushError(errors, path, 'Cost distributions must have nonnegative support.');
                }
                if (role === 'discount_rate' && supportLow <= -1) {
                    technoeconomicPushError(errors, path, 'Discount-rate support must be greater than -1.');
                }
                if (role === 'degradation' && (supportLow < 0 || supportHigh >= 1)) {
                    technoeconomicPushError(errors, path, 'Degradation support must satisfy 0 <= rate < 1.');
                }
                if (role === 'transfer_baseline' && supportLow <= 0) {
                    technoeconomicPushError(errors, path, 'Baseline-transfer support must be strictly positive.');
                }
                if (role === 'transfer_incremental' && supportLow < 0) {
                    technoeconomicPushError(errors, path, 'Incremental-transfer support must be nonnegative.');
                }
            }
            const nonfixed = distribution.family !== 'fixed'
                && !(['uniform', 'triangular'].includes(distribution.family)
                    && supportLow !== null && supportLow === supportHigh);
            return {payload, supportLow, supportHigh, nonfixed};
        }

        function technoeconomicSerializeDocumented(value, unit, path, errors, context, role) {
            const documented = technoeconomicSanitizeDocumented(value, unit);
            const distribution = technoeconomicSerializeDistribution(
                documented.distribution, `${path}.distribution`, errors, role
            );
            if (distribution.nonfixed) context.nonfixedPredictorCount += 1;
            return {
                payload: {
                    unit,
                    distribution: distribution.payload,
                    evidence: technoeconomicSerializeEvidence(
                        documented.evidence, `${path}.evidence`, errors, context
                    ),
                },
                distribution,
            };
        }

        function technoeconomicSerializeCurrency(value, costYear, path, errors, context) {
            const currency = technoeconomicSanitizeCurrencyYear(value, String(costYear ?? ''));
            const sourceYear = technoeconomicFiniteNumber(
                currency.source_cost_year, `${path}.source_cost_year`, errors,
                {integer: true, min: 1900, max: 3000}
            );
            const factor = technoeconomicFiniteNumber(
                currency.index_factor, `${path}.index_factor`, errors, {positive: true}
            );
            const common = {
                method: currency.method,
                source_cost_year: sourceYear,
                target_constant_dollar_cost_year: costYear,
                submitted_distribution_basis: 'target_constant_dollar_year',
                index_identity: technoeconomicStrictText(
                    currency.index_identity, `${path}.index_identity`, errors
                ),
                index_factor: factor,
                derivation: technoeconomicStrictText(currency.derivation, `${path}.derivation`, errors),
            };
            if (!['same_year_no_adjustment', 'price_index_adjustment'].includes(currency.method)) {
                technoeconomicPushError(errors, `${path}.method`, 'Select a supported currency normalization method.');
                return common;
            }
            if (currency.method === 'same_year_no_adjustment') {
                if (sourceYear !== costYear) technoeconomicPushError(errors, path,
                    'Same-year normalization requires identical source and target years.');
                if (factor !== 1) technoeconomicPushError(errors, path,
                    'Same-year normalization requires an index factor of 1.');
                if (common.index_identity !== 'not_applicable_same_year') {
                    technoeconomicPushError(errors, `${path}.index_identity`,
                        'Same-year normalization uses the literal not_applicable_same_year.');
                }
                return common;
            }
            if (sourceYear === costYear) technoeconomicPushError(errors, path,
                'Price-index normalization requires different source and target years.');
            return {
                ...common,
                index_source_evidence: technoeconomicSerializeEvidence(
                    currency.index_source_evidence, `${path}.index_source_evidence`, errors, context
                ),
            };
        }

        function technoeconomicApplicableSystems(ownership) {
            if (ownership === 'solectria_only') return ['solectria'];
            if (ownership === 'solaredge_only') return ['solaredge'];
            return ['solectria', 'solaredge'];
        }

        function technoeconomicSerializeCostLine(value, index, draft, costYear, errors, context) {
            const path = `cost_lines[${index}]`;
            const line = technoeconomicSanitizeCostLine(value, index, draft.cost_year, draft.basis);
            const costType = line.cost_type;
            const recurring = costType.startsWith('recurring_');
            if (!['solectria_only', 'solaredge_only', 'paired_shared'].includes(line.ownership)) {
                technoeconomicPushError(errors, `${path}.ownership`, 'Select a supported ownership.');
            }
            if (![
                'initial_capex', 'initial_installation_labor', 'recurring_labor',
                'recurring_om', 'recurring_maintenance',
            ].includes(costType)) {
                technoeconomicPushError(errors, `${path}.cost_type`, 'Select a supported cost type.');
            }
            if (![
                'usd_total', 'usd_total_per_year', 'usd_per_unit', 'usd_per_unit_year',
                'usd_per_wdc', 'usd_per_wdc_year',
            ].includes(line.original_unit)) {
                technoeconomicPushError(errors, `${path}.original_unit`, 'Select a supported original unit.');
            }
            if (![
                'usd_per_wdc', 'usd_per_wdc_year',
                'usd_per_applied_w', 'usd_per_applied_w_year',
            ].includes(line.normalized_unit)) {
                technoeconomicPushError(errors, `${path}.normalized_unit`, 'Select a supported normalized unit.');
            }
            if (![
                'divide_by_frozen_source_wdc',
                'multiply_quantity_then_divide_by_frozen_source_wdc',
                'divide_by_frozen_applied_capacity_w',
                'multiply_quantity_then_divide_by_frozen_applied_capacity_w',
                'already_normalized_per_wdc',
            ].includes(line.normalization_method)) {
                technoeconomicPushError(errors, `${path}.normalization_method`,
                    'Select a supported normalization method.');
            }
            const distribution = technoeconomicSerializeDistribution(
                line.distribution, `${path}.distribution`, errors, 'cost'
            );
            if (distribution.nonfixed) context.nonfixedPredictorCount += 1;
            const includes = line.coverage_include_ids.map((item, itemIndex) =>
                technoeconomicStableId(item, `${path}.coverage_include_ids[${itemIndex}]`, errors));
            const excludes = line.coverage_exclude_ids.map((item, itemIndex) =>
                technoeconomicStableId(item, `${path}.coverage_exclude_ids[${itemIndex}]`, errors));
            if (!includes.length) technoeconomicPushError(errors, `${path}.coverage_include_ids`,
                'At least one coverage ID is required.');
            if (includes.length > 256) technoeconomicPushError(
                errors, `${path}.coverage_include_ids`, 'Use no more than 256 coverage include IDs.');
            if (excludes.length > 256) technoeconomicPushError(
                errors, `${path}.coverage_exclude_ids`, 'Use no more than 256 coverage exclude IDs.');
            if (new Set(includes).size !== includes.length) technoeconomicPushError(
                errors, `${path}.coverage_include_ids`, 'Coverage include IDs must be unique.');
            if (new Set(excludes).size !== excludes.length) technoeconomicPushError(
                errors, `${path}.coverage_exclude_ids`, 'Coverage exclude IDs must be unique.');
            if (includes.some((item) => excludes.includes(item))) technoeconomicPushError(
                errors, path, 'Included and excluded coverage IDs must be disjoint.');
            const solQuantity = technoeconomicFiniteNumber(
                line.solectria_quantity, `${path}.solectria_quantity`, errors, {min: 0}
            );
            const seQuantity = technoeconomicFiniteNumber(
                line.solaredge_quantity, `${path}.solaredge_quantity`, errors, {min: 0}
            );
            if (line.ownership === 'solectria_only' && !(solQuantity > 0 && seQuantity === 0)) {
                technoeconomicPushError(errors, path, 'Solectria-only lines require positive SOL and zero SE quantity.');
            }
            if (line.ownership === 'solaredge_only' && !(seQuantity > 0 && solQuantity === 0)) {
                technoeconomicPushError(errors, path, 'SolarEdge-only lines require zero SOL and positive SE quantity.');
            }
            if (line.ownership === 'paired_shared' && !(solQuantity > 0 && seQuantity > 0)) {
                technoeconomicPushError(errors, path, 'Paired/shared lines require positive quantities for both systems.');
            }
            const expectedNormalized = draft.basis === 'solartac_site'
                ? recurring ? 'usd_per_applied_w_year' : 'usd_per_applied_w'
                : recurring ? 'usd_per_wdc_year' : 'usd_per_wdc';
            if (line.normalized_unit !== expectedNormalized) technoeconomicPushError(
                errors, `${path}.normalized_unit`, `${costType} requires ${expectedNormalized}.`);
            const annualOriginals = ['usd_total_per_year', 'usd_per_unit_year', 'usd_per_wdc_year'];
            if (annualOriginals.includes(line.original_unit) !== recurring) technoeconomicPushError(
                errors, `${path}.original_unit`, 'Original-unit timing must match the cost type.');
            let quantityUnit = technoeconomicStrictText(
                line.quantity_unit, `${path}.quantity_unit`, errors, {optional: true}
            ) || null;
            if (['divide_by_frozen_source_wdc', 'divide_by_frozen_applied_capacity_w'].includes(
                line.normalization_method
            )) {
                if (!['usd_total', 'usd_total_per_year'].includes(line.original_unit)) {
                    technoeconomicPushError(errors, path, 'Total-capacity normalization requires a total-USD unit.');
                }
                if (quantityUnit) technoeconomicPushError(errors, `${path}.quantity_unit`,
                    'Total-capacity normalization must not declare a quantity unit.');
                quantityUnit = null;
            } else if ([
                'multiply_quantity_then_divide_by_frozen_source_wdc',
                'multiply_quantity_then_divide_by_frozen_applied_capacity_w',
            ].includes(line.normalization_method)) {
                if (!['usd_per_unit', 'usd_per_unit_year'].includes(line.original_unit)) {
                    technoeconomicPushError(errors, path, 'Quantity normalization requires a per-unit USD unit.');
                }
                if (!quantityUnit) technoeconomicPushError(errors, `${path}.quantity_unit`,
                    'Quantity normalization requires a quantity unit.');
            } else {
                if (!['usd_per_wdc', 'usd_per_wdc_year'].includes(line.original_unit)) {
                    technoeconomicPushError(errors, path, 'Already-normalized costs require a per-Wdc unit.');
                }
                if (quantityUnit) technoeconomicPushError(errors, `${path}.quantity_unit`,
                    'Already-normalized costs must not declare a quantity unit.');
                quantityUnit = null;
            }
            if ([
                'divide_by_frozen_source_wdc', 'divide_by_frozen_applied_capacity_w',
                'already_normalized_per_wdc',
            ].includes(
                line.normalization_method
            ) && ![solQuantity, seQuantity].every((item) => item === 0 || item === 1)) {
                technoeconomicPushError(errors, path,
                    'Total or already-normalized lines use quantity 1 for each applicable system and 0 otherwise.');
            }
            if (draft.basis === 'solartac_site' && ![
                'divide_by_frozen_applied_capacity_w',
                'multiply_quantity_then_divide_by_frozen_applied_capacity_w',
            ].includes(line.normalization_method)) {
                technoeconomicPushError(errors, path,
                    'SolarTAC site costs must be normalized by frozen applied capacity.');
            }
            if (draft.basis === 'commercial_representative'
                && line.normalization_method !== 'already_normalized_per_wdc') {
                technoeconomicPushError(errors, path,
                    'Commercial representative costs must use a sourced per-Wdc basis.');
            }
            return {
                payload: {
                    input_id: technoeconomicStableId(line.input_id, `${path}.input_id`, errors),
                    label: technoeconomicStrictText(line.label, `${path}.label`, errors),
                    ownership: line.ownership, cost_type: costType,
                    distribution: distribution.payload,
                    coverage_include_ids: includes, coverage_exclude_ids: excludes,
                    original_unit: line.original_unit, normalized_unit: line.normalized_unit,
                    normalization_method: line.normalization_method,
                    solectria_quantity: solQuantity, solaredge_quantity: seQuantity,
                    quantity_unit: quantityUnit,
                    normalization_derivation: technoeconomicStrictText(
                        line.normalization_derivation, `${path}.normalization_derivation`, errors
                    ),
                    constant_dollar_cost_year: costYear,
                    currency_year_normalization: technoeconomicSerializeCurrency(
                        line.currency_year_normalization, costYear,
                        `${path}.currency_year_normalization`, errors, context
                    ),
                    evidence: technoeconomicSerializeEvidence(
                        line.evidence, `${path}.evidence`, errors, context
                    ),
                },
                systems: technoeconomicApplicableSystems(line.ownership),
                timing: recurring ? 'recurring_year_end' : 'initial_t0',
            };
        }

        function technoeconomicSerializeTechnology(value, system, path, errors) {
            const design = technoeconomicSanitizeTechnology(value, system === 'solaredge');
            return {
                optimizer_count: technoeconomicFiniteNumber(
                    design.optimizer_count, `${path}.optimizer_count`, errors,
                    {integer: true, min: 0}
                ),
                inverter_count: technoeconomicFiniteNumber(
                    design.inverter_count, `${path}.inverter_count`, errors,
                    {integer: true, min: 1}
                ),
                transformer_count: technoeconomicFiniteNumber(
                    design.transformer_count, `${path}.transformer_count`, errors,
                    {integer: true, min: 0}
                ),
                dc_ac_ratio: technoeconomicFiniteNumber(
                    design.dc_ac_ratio, `${path}.dc_ac_ratio`, errors, {positive: true}
                ),
                inverter_loading_ratio: technoeconomicFiniteNumber(
                    design.inverter_loading_ratio, `${path}.inverter_loading_ratio`, errors,
                    {positive: true}
                ),
                inverter_topology: technoeconomicStrictText(
                    design.inverter_topology, `${path}.inverter_topology`, errors
                ),
                transformer_topology: technoeconomicStrictText(
                    design.transformer_topology, `${path}.transformer_topology`, errors
                ),
                bos_scope: technoeconomicStrictText(design.bos_scope, `${path}.bos_scope`, errors),
                labor_productivity_and_rates: technoeconomicStrictText(
                    design.labor_productivity_and_rates,
                    `${path}.labor_productivity_and_rates`, errors
                ),
                commissioning_scope: technoeconomicStrictText(
                    design.commissioning_scope, `${path}.commissioning_scope`, errors
                ),
            };
        }

        function technoeconomicSerializeCommercialDesign(value, costYear, errors, context) {
            const path = 'commercial_reference_design';
            const design = technoeconomicSanitizeCommercialDesign(value, String(costYear ?? ''));
            const referenceWdc = technoeconomicFiniteNumber(
                design.reference_wdc, `${path}.reference_wdc`, errors, {positive: true}
            );
            const moduleStc = technoeconomicFiniteNumber(
                design.module_stc_wdc, `${path}.module_stc_wdc`, errors, {positive: true}
            );
            const moduleCount = technoeconomicFiniteNumber(
                design.module_count, `${path}.module_count`, errors, {integer: true, min: 1}
            );
            if (referenceWdc > 0 && moduleStc > 0 && moduleCount >= 1
                && !technoeconomicDecimalEqualsIntegerProduct(
                    String(referenceWdc), String(moduleStc), moduleCount
                )) {
                technoeconomicPushError(errors, path,
                    'Reference Wdc must exactly equal module count multiplied by module STC Wdc.');
            }
            return {
                design_id: technoeconomicStableId(design.design_id, `${path}.design_id`, errors),
                reference_wdc: referenceWdc,
                module_model: technoeconomicStrictText(
                    design.module_model, `${path}.module_model`, errors
                ),
                module_stc_wdc: moduleStc,
                module_count: moduleCount,
                constant_dollar_cost_year: costYear,
                solectria: technoeconomicSerializeTechnology(
                    design.solectria, 'solectria', `${path}.solectria`, errors
                ),
                solaredge: technoeconomicSerializeTechnology(
                    design.solaredge, 'solaredge', `${path}.solaredge`, errors
                ),
                normalization_derivation: technoeconomicStrictText(
                    design.normalization_derivation, `${path}.normalization_derivation`, errors
                ),
                evidence: technoeconomicSerializeEvidence(
                    design.evidence, `${path}.evidence`, errors, context
                ),
            };
        }

        function technoeconomicSerializeTransfer(value, errors, context) {
            const path = 'commercial_transfer';
            const transfer = technoeconomicSanitizeTransfer(value);
            if (transfer.explicit_attestation !== true) {
                technoeconomicPushError(errors, `${path}.explicit_attestation`,
                    'Explicit transfer attestation is required.');
            }
            const timestamp = technoeconomicStrictText(
                transfer.attested_at, `${path}.attested_at`, errors
            );
            const timestampPattern = /^\d{4}-\d{2}-\d{2}T(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d(?:\.\d+)?(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)$/;
            const dateErrors = [];
            technoeconomicIsoDate(timestamp.slice(0, 10), `${path}.attested_at`, dateErrors);
            if (!timestampPattern.test(timestamp) || dateErrors.length
                || Number.isNaN(Date.parse(timestamp))) {
                technoeconomicPushError(errors, `${path}.attested_at`,
                    'Use a valid ISO-8601 timestamp with an explicit UTC offset.');
            }
            const baseline = technoeconomicSerializeDocumented(
                transfer.baseline_factor, 'dimensionless_multiplier',
                `${path}.baseline_factor`, errors, context, 'transfer_baseline'
            );
            const incremental = technoeconomicSerializeDocumented(
                transfer.incremental_factor, 'dimensionless_multiplier',
                `${path}.incremental_factor`, errors, context, 'transfer_incremental'
            );
            const mechanisms = transfer.mechanisms.map((item, index) => ({
                mechanism: item.mechanism,
                status: item.status,
                rationale: technoeconomicStrictText(
                    item.rationale, `${path}.mechanisms[${index}].rationale`, errors
                ),
                evidence: technoeconomicSerializeEvidence(
                    item.evidence, `${path}.mechanisms[${index}].evidence`, errors, context
                ),
            }));
            transfer.mechanisms.forEach((item, index) => {
                if (!['supported', 'not_applicable', 'not_transferred'].includes(item.status)) {
                    technoeconomicPushError(
                        errors, `${path}.mechanisms[${index}].status`,
                        'Select a supported transfer-mechanism status.'
                    );
                }
            });
            const mechanismNames = mechanisms.map((item) => item.mechanism);
            if (mechanismNames.length !== TECHNOECONOMIC_TRANSFER_MECHANISMS.length
                || new Set(mechanismNames).size !== TECHNOECONOMIC_TRANSFER_MECHANISMS.length
                || TECHNOECONOMIC_TRANSFER_MECHANISMS.some((item) => !mechanismNames.includes(item))) {
                technoeconomicPushError(errors, `${path}.mechanisms`,
                    'The complete unique transfer-mechanism checklist is required.');
            }
            if (mechanisms.some((item) => item.status === 'not_transferred')) {
                technoeconomicPushError(errors, `${path}.mechanisms`,
                    'An approved transfer cannot include not-transferred mechanisms; disable transfer for a cost-only request.');
            }
            if (!mechanisms.some((item) => item.status === 'supported')) {
                technoeconomicPushError(errors, `${path}.mechanisms`,
                    'At least one transfer mechanism must be supported.');
            }
            return {
                status: 'approved', explicit_attestation: true,
                attested_by: technoeconomicStrictText(
                    transfer.attested_by, `${path}.attested_by`, errors
                ),
                attested_at: timestamp,
                attestation_rationale: technoeconomicStrictText(
                    transfer.attestation_rationale, `${path}.attestation_rationale`, errors
                ),
                baseline_factor: baseline.payload,
                incremental_factor: incremental.payload,
                mechanisms,
            };
        }

        function technoeconomicValidateCostCoverage(serializedLines, errors) {
            for (let leftIndex = 0; leftIndex < serializedLines.length; leftIndex += 1) {
                const left = serializedLines[leftIndex];
                for (let rightIndex = leftIndex + 1; rightIndex < serializedLines.length; rightIndex += 1) {
                    const right = serializedLines[rightIndex];
                    const sharedSystem = left.systems.some((system) => right.systems.includes(system));
                    const sameTiming = left.timing === right.timing;
                    const sharedCoverage = left.payload.coverage_include_ids.filter(
                        (item) => right.payload.coverage_include_ids.includes(item)
                    );
                    if (sharedSystem && sameTiming && sharedCoverage.length) {
                        technoeconomicPushError(
                            errors,
                            `cost_lines[${leftIndex}], cost_lines[${rightIndex}]`,
                            `Overlapping cost coverage is not allowed: ${sharedCoverage.join(', ')}.`
                        );
                    }
                }
            }
        }

        function technoeconomicSerializeCommercialScaling(
            value, source, errors, context
        ) {
            if (value === null || value === undefined) return null;
            const scaling = technoeconomicSanitizeCommercialScaling(value);
            if (!scaling) return null;
            const path = 'commercial_scaling';
            const targetCapacity = technoeconomicFiniteNumber(
                scaling.target_capacity, `${path}.target_capacity`, errors, {positive: true}
            );
            if (!['kw', 'mw'].includes(scaling.target_capacity_unit)) {
                technoeconomicPushError(
                    errors, `${path}.target_capacity_unit`, 'Select kW or MW.'
                );
            }
            const multiplier = scaling.target_capacity_unit === 'mw' ? 1000000 : 1000;
            if (targetCapacity !== null && !Number.isFinite(targetCapacity * multiplier)) {
                technoeconomicPushError(
                    errors, `${path}.target_capacity`,
                    'The target capacity cannot be represented in watts.'
                );
            }
            if (!['ac_operating_limit', 'dc_installed_nameplate'].includes(
                scaling.target_rating_basis
            )) {
                technoeconomicPushError(
                    errors, `${path}.target_rating_basis`,
                    'Select AC operating limit or DC installed nameplate.'
                );
            }
            const sourceBasis = technoeconomicSourceRatingBasis(source);
            if (sourceBasis && scaling.target_rating_basis !== sourceBasis) {
                technoeconomicPushError(
                    errors, `${path}.target_rating_basis`,
                    'The commercial target rating basis must match the frozen source applied-capacity rating basis.'
                );
            }
            const marginalCost = technoeconomicSerializeDistribution(
                scaling.marginal_cost_difference,
                `${path}.marginal_cost_difference`, errors, 'signed_marginal_cost'
            );
            if (marginalCost.nonfixed) context.nonfixedPredictorCount += 1;
            if (!['lifecycle_present_value', 'equivalent_annual'].includes(
                scaling.marginal_cost_timing
            )) {
                technoeconomicPushError(
                    errors, `${path}.marginal_cost_timing`,
                    'Select lifecycle present value or equivalent annual timing.'
                );
            }
            const marginalCostUnit = scaling.marginal_cost_timing === 'equivalent_annual'
                ? 'constant_usd_per_year' : 'constant_usd';
            return {
                target_capacity: targetCapacity,
                target_capacity_unit: scaling.target_capacity_unit,
                target_rating_basis: scaling.target_rating_basis,
                marginal_cost_difference: marginalCost.payload,
                marginal_cost_timing: scaling.marginal_cost_timing,
                marginal_cost_unit: marginalCostUnit,
                transfer_method: 'direct_capacity_scaling',
                transfer_rationale: technoeconomicStrictText(
                    scaling.transfer_rationale, `${path}.transfer_rationale`, errors
                ),
                evidence: technoeconomicSerializeEvidence(
                    scaling.evidence, `${path}.evidence`, errors, context
                ),
            };
        }

        function serializeTechnoeconomicRequest(value, options = {}) {
            const draft = sanitizeTechnoeconomicDraft(value);
            const errors = [];
            const context = {
                evidenceCount: 0, provisionalEvidenceCount: 0, nonfixedPredictorCount: 0,
            };
            const sourceId = technoeconomicStrictText(
                draft.source_annual_job_id, 'source_annual_job_id', errors, {maximum: 200}
            );
            if (!['solartac_site', 'commercial_representative'].includes(draft.basis)) {
                technoeconomicPushError(errors, 'basis', 'Select SolarTAC site or commercial representative.');
            }
            if (Array.isArray(options.sources)) {
                const source = options.sources.find((item) => item?.source_annual_job_id === sourceId);
                if (!source) technoeconomicPushError(errors, 'source_annual_job_id',
                    'Refresh sources and select a listed Annual Simulation.');
                else if (source.eligible !== true) technoeconomicPushError(errors, 'source_annual_job_id',
                    source.detail || 'The selected Annual Simulation is not eligible.');
            }
            const n = technoeconomicFiniteNumber(draft.n, 'n', errors, {
                integer: true, min: 1, max: 100000,
            });
            let seed = null;
            const seedText = typeof draft.seed === 'string' ? draft.seed.trim() : '';
            if (!/^\d+$/.test(seedText)) {
                technoeconomicPushError(errors, 'seed', 'Enter a nonnegative whole-number seed using digits only.');
            } else {
                try {
                    const exactSeed = BigInt(seedText);
                    if (exactSeed > BigInt(TECHNOECONOMIC_MAX_SAFE_SEED)) {
                        technoeconomicPushError(errors, 'seed',
                            `The browser policy rejects seeds above ${TECHNOECONOMIC_MAX_SAFE_SEED.toLocaleString('en-US')} to prevent rounding.`);
                    } else seed = Number(exactSeed);
                } catch (_error) {
                    technoeconomicPushError(errors, 'seed', 'The sampling seed is invalid.');
                }
            }
            const costYear = technoeconomicFiniteNumber(draft.cost_year, 'finance.constant_dollar_cost_year', errors, {
                integer: true, min: 1900, max: 3000,
            });
            const projectLife = technoeconomicFiniteNumber(
                draft.project_life_years, 'finance.project_life_years', errors,
                {integer: true, min: 1}
            );
            const serializedLines = draft.cost_lines.map((line, index) =>
                technoeconomicSerializeCostLine(line, index, draft, costYear, errors, context));
            if (!serializedLines.length) technoeconomicPushError(errors, 'cost_lines',
                'Add at least one fully documented cost line.');
            if (serializedLines.length > 1000) technoeconomicPushError(errors, 'cost_lines',
                'Use no more than 1,000 cost lines.');
            const inputIds = serializedLines.map((item) => item.payload.input_id);
            if (new Set(inputIds).size !== inputIds.length) technoeconomicPushError(errors, 'cost_lines',
                'Cost input IDs must be unique.');
            const collisions = inputIds.filter((item) => TECHNOECONOMIC_RESERVED_INPUT_IDS.has(item));
            if (collisions.length) technoeconomicPushError(errors, 'cost_lines',
                `Cost input IDs are reserved: ${[...new Set(collisions)].join(', ')}.`);
            technoeconomicValidateCostCoverage(serializedLines, errors);
            for (const system of ['solectria', 'solaredge']) {
                if (!serializedLines.some((item) => item.systems.includes(system))) {
                    technoeconomicPushError(
                        errors, 'cost_lines',
                        `A full-system cost stack requires at least one ${
                            system === 'solectria' ? 'Solectria' : 'SolarEdge'
                        } cost stream.`
                    );
                }
            }
            const discount = technoeconomicSerializeDocumented(
                draft.discount_rate, 'real_fraction_per_year', 'finance.real_discount_rate',
                errors, context, 'discount_rate'
            );
            const degradation = technoeconomicSerializeDocumented(
                draft.shared_degradation, 'real_fraction_per_year',
                'shared_degradation.annual_rate', errors, context, 'degradation'
            );
            const projectEvidence = technoeconomicSerializeEvidence(
                draft.project_life_evidence, 'finance.project_life_evidence', errors, context
            );
            const selectedSource = Array.isArray(options.sources)
                ? options.sources.find((item) => item?.source_annual_job_id === sourceId) : null;
            let commercialScaling = null;
            if (draft.commercial_scaling !== null) {
                if (draft.basis !== 'solartac_site'
                    || draft.capacity_normalization !== TECHNOECONOMIC_APPLIED_CAPACITY_NORMALIZATION) {
                    technoeconomicPushError(
                        errors, 'commercial_scaling',
                        'Commercial direct scaling requires the SolarTAC site applied-capacity basis.'
                    );
                }
                commercialScaling = technoeconomicSerializeCommercialScaling(
                    draft.commercial_scaling, selectedSource, errors, context
                );
            }
            let commercialDesign = null;
            let commercialTransfer = null;
            if (draft.basis === 'commercial_representative') {
                commercialDesign = technoeconomicSerializeCommercialDesign(
                    draft.commercial_reference_design, costYear, errors, context
                );
                if (draft.transfer_enabled) commercialTransfer = technoeconomicSerializeTransfer(
                    draft.commercial_transfer, errors, context
                );
            } else if (draft.transfer_enabled) {
                technoeconomicPushError(errors, 'commercial_transfer',
                    'SolarTAC site requests cannot include commercial transfer.');
            }
            if (n !== null) {
                const declaredInputs = serializedLines.length + 2
                    + (commercialTransfer ? 2 : 0) + (commercialScaling ? 1 : 0);
                const exportCells = n * (48 + declaredInputs);
                if (exportCells > TECHNOECONOMIC_MAX_REALIZATION_EXPORT_CELLS) {
                    technoeconomicPushError(errors, 'n',
                        `The realization export budget would be ${exportCells.toLocaleString('en-US')} cells; the limit is ${TECHNOECONOMIC_MAX_REALIZATION_EXPORT_CELLS.toLocaleString('en-US')}.`);
                }
                const workUnits = n * context.nonfixedPredictorCount ** 2;
                if (workUnits > TECHNOECONOMIC_MAX_SENSITIVITY_WORK_UNITS) {
                    technoeconomicPushError(errors, 'n',
                        `The sensitivity work budget would be ${workUnits.toLocaleString('en-US')} units; the limit is ${TECHNOECONOMIC_MAX_SENSITIVITY_WORK_UNITS.toLocaleString('en-US')}.`);
                }
            }
            const payload = {
                source_annual_job_id: sourceId,
                basis: draft.basis,
                capacity_normalization: draft.basis === 'solartac_site'
                    ? TECHNOECONOMIC_APPLIED_CAPACITY_NORMALIZATION : null,
                n,
                seed,
                cost_stack_completeness: 'full_system',
                cost_lines: serializedLines.map((item) => item.payload),
                finance: {
                    treatment_key: 'constant-real-v1',
                    constant_dollar_cost_year: costYear,
                    project_life_years: projectLife,
                    project_life_evidence: projectEvidence,
                    real_discount_rate: discount.payload,
                },
                shared_degradation: {
                    degradation_model: 'shared_module_v1',
                    annual_rate: degradation.payload,
                },
                commercial_reference_design: commercialDesign,
                commercial_transfer: commercialTransfer,
                commercial_scaling: commercialScaling,
            };
            return {
                payload,
                errors,
                valid: errors.length === 0,
                evidenceCount: context.evidenceCount,
                provisionalEvidenceCount: context.provisionalEvidenceCount,
                nonfixedPredictorCount: context.nonfixedPredictorCount,
            };
        }

        function normalizeTechnoeconomicApiError(statusOrError, body = null) {
            if (statusOrError instanceof Error && body === null) {
                return {
                    status: null, code: statusOrError.name === 'AbortError' ? 'request_aborted' : 'network_error',
                    message: statusOrError.name === 'AbortError'
                        ? 'The request was superseded.'
                        : 'The technoeconomic service could not be reached. Check the connection and retry.',
                    fields: [],
                };
            }
            const status = typeof statusOrError === 'number'
                ? statusOrError : Number(statusOrError?.status) || null;
            const value = body ?? statusOrError?.body ?? statusOrError;
            const detail = technoeconomicPlainObject(value).detail ?? value;
            const fields = [];
            let code = status === 429 ? 'queue_full'
                : status === 404 ? 'not_found'
                : status === 409 ? 'conflict'
                : status === 422 ? 'validation_error'
                : status && status >= 500 ? 'server_error' : 'request_failed';
            let message = `Technoeconomic request failed${status ? ` (HTTP ${status})` : ''}.`;
            if (Array.isArray(detail)) {
                for (const item of detail) {
                    const location = Array.isArray(item?.loc)
                        ? item.loc.filter((part) => part !== 'body').join('.') : '';
                    const text = typeof item?.msg === 'string' ? item.msg : 'Invalid value.';
                    fields.push({path: location, message: text});
                }
                if (fields.length) message = fields.map((item) =>
                    `${item.path ? `${item.path}: ` : ''}${item.message}`).join(' ');
            } else if (detail && typeof detail === 'object') {
                if (typeof detail.code === 'string') code = detail.code;
                if (typeof detail.message === 'string') message = detail.message;
                else if (typeof detail.detail === 'string') message = detail.detail;
            } else if (typeof detail === 'string' && detail.trim()) {
                message = detail.trim();
            } else if (statusOrError instanceof Error && statusOrError.message) {
                message = statusOrError.message;
            }
            return {status, code, message, fields};
        }

        function technoeconomicRenderErrors(element, errors) {
            if (!element) return;
            element.replaceChildren();
            if (!errors?.length) {
                element.hidden = true;
                element.removeAttribute('data-error-code');
                return;
            }
            const heading = technoeconomicNode('strong', {
                text: errors.length === 1 ? 'Resolve this issue:' : `Resolve these ${errors.length} issues:`,
            });
            const list = technoeconomicNode('ul');
            for (const error of errors) {
                list.appendChild(technoeconomicNode('li', {
                    text: `${error.path ? `${error.path}: ` : ''}${error.message}`,
                }));
            }
            element.append(heading, list);
            element.hidden = false;
        }

        function technoeconomicRenderApiError(element, error) {
            const normalized = error?.code ? error : normalizeTechnoeconomicApiError(error);
            technoeconomicRenderErrors(element, [{path: '', message: normalized.message}]);
            if (element) element.dataset.errorCode = normalized.code;
        }

        async function technoeconomicFetchJson(url, options = {}) {
            const request = {
                method: options.method || 'GET',
                credentials: 'same-origin', cache: 'no-store',
                headers: {Accept: 'application/json', ...(options.headers || {})},
                signal: options.signal,
            };
            if (options.body !== undefined) {
                request.headers['Content-Type'] = 'application/json';
                request.body = JSON.stringify(options.body);
            }
            let response;
            try {
                response = await fetch(url, request);
            } catch (error) {
                throw normalizeTechnoeconomicApiError(error);
            }
            const text = await response.text();
            let body = null;
            if (text) {
                try {
                    body = JSON.parse(text);
                } catch (_error) {
                    body = null;
                }
            }
            if (!response.ok) throw normalizeTechnoeconomicApiError(response.status, body);
            if (body === null) throw {
                status: response.status, code: 'invalid_response', fields: [],
                message: 'The technoeconomic service returned an invalid JSON response.',
            };
            return body;
        }

        function technoeconomicSetSourceState(state, title, detail) {
            if (technoeconomicElements.sourceStatusPanel) {
                technoeconomicElements.sourceStatusPanel.dataset.state = state;
            }
            if (technoeconomicElements.standaloneSourceStatusPanel) {
                technoeconomicElements.standaloneSourceStatusPanel.dataset.state = state;
            }
            if (technoeconomicElements.sourceStatus) technoeconomicElements.sourceStatus.textContent = title;
            if (technoeconomicElements.sourceDetail) technoeconomicElements.sourceDetail.textContent = detail;
            if (technoeconomicElements.standaloneSourceStatus) {
                technoeconomicElements.standaloneSourceStatus.textContent = title;
            }
            if (technoeconomicElements.standaloneSourceHelp) {
                technoeconomicElements.standaloneSourceHelp.textContent = detail;
            }
        }

        function technoeconomicSetSourceRefreshBusy(busy) {
            for (const button of [
                technoeconomicElements.refreshSourcesButton,
                technoeconomicElements.standaloneRefreshSourcesButton,
            ]) {
                if (!button) continue;
                button.disabled = false;
                button.textContent = busy ? 'Retry source check' : 'Refresh sources';
                button.setAttribute?.('aria-busy', String(busy));
            }
            for (const select of [
                technoeconomicElements.sourceSelect,
                technoeconomicElements.standaloneSourceSelect,
            ]) select?.setAttribute?.('aria-busy', String(busy));
        }

        function technoeconomicSetSourcePlaceholder(text) {
            for (const select of [
                technoeconomicElements.sourceSelect,
                technoeconomicElements.standaloneSourceSelect,
            ]) {
                if (!select) continue;
                const placeholder = Array.from(select.options || []).find(
                    (option) => option.value === ''
                );
                if (placeholder) placeholder.textContent = text;
            }
        }

        function technoeconomicDefinition(root, term, description) {
            if (!root) return;
            root.append(
                technoeconomicNode('dt', {text: term}),
                technoeconomicNode('dd', {text: description ?? 'Unavailable'})
            );
        }

        function technoeconomicFormatNumber(value, maximumFractionDigits = 3) {
            if (value === null || value === undefined || value === '') return 'Unavailable';
            const number = Number(value);
            return Number.isFinite(number)
                ? number.toLocaleString('en-US', {maximumFractionDigits}) : 'Unavailable';
        }

        function technoeconomicQuantile(values, probability) {
            const sorted = (Array.isArray(values) ? values : [])
                .map(Number)
                .filter((value) => Number.isFinite(value))
                .sort((left, right) => left - right);
            if (!sorted.length) return null;
            if (sorted.length === 1) return sorted[0];
            const position = (sorted.length - 1) * probability;
            const lower = Math.floor(position);
            const upper = Math.ceil(position);
            const fraction = position - lower;
            return sorted[lower] + ((sorted[upper] - sorted[lower]) * fraction);
        }

        function technoeconomicAnnualEnergies(source, system) {
            const field = system === 'solaredge' ? 'solaredge_kwh' : 'solectria_kwh';
            return (Array.isArray(source?.annual_energy_by_year)
                ? source.annual_energy_by_year : [])
                .map((row) => Number(row?.[field]))
                .filter((value) => Number.isFinite(value) && value > 0);
        }

        function technoeconomicFormatCapacity(value) {
            const wdc = Number(value);
            return Number.isFinite(wdc) && wdc > 0
                ? `${technoeconomicFormatNumber(wdc / 1000, 2)} kWdc`
                : 'Unavailable';
        }

        function technoeconomicOperatingLimitKwac(source) {
            const operatingLimit = technoeconomicPlainObject(
                technoeconomicPlainObject(source?.provenance).operating_limit
            );
            const limit = Number(operatingLimit.curtailment_limit_kw);
            return operatingLimit.curtailment_enabled === true
                && Number.isFinite(limit) && limit > 0 ? limit : null;
        }

        function technoeconomicSourceRatingBasis(source) {
            if (!source) return '';
            const applied = technoeconomicPlainObject(source.applied_capacity);
            const bases = ['solectria', 'solaredge'].map((system) =>
                technoeconomicPlainObject(applied[system]).rating_basis
            ).filter((basis) => ['ac_operating_limit', 'dc_installed_nameplate'].includes(basis));
            if (bases.length === 2 && bases[0] === bases[1]) return bases[0];
            return technoeconomicOperatingLimitKwac(source) !== null
                ? 'ac_operating_limit' : 'dc_installed_nameplate';
        }

        function technoeconomicRatingBasisLabel(value) {
            return value === 'ac_operating_limit'
                ? 'AC operating limit' : value === 'dc_installed_nameplate'
                    ? 'DC installed nameplate' : 'Unavailable';
        }

        function technoeconomicSyncGuidedCommercialSourceBasis(source) {
            const select = technoeconomicDomElement(
                'technoeconomicGuidedCommercialRatingBasis'
            );
            const status = technoeconomicDomElement(
                'technoeconomicGuidedCommercialSourceBasis'
            );
            const sourceId = technoeconomicElements.sourceSelect?.value || '';
            if (!source) {
                if (select && !sourceId) select.value = '';
                if (status) status.textContent = sourceId
                    ? 'Refresh the saved Annual Simulation source to verify its rating basis.'
                    : 'Select an Annual Simulation source to determine the matching applied-capacity basis.';
                return;
            }
            const basis = technoeconomicSourceRatingBasis(source);
            if (select) select.value = basis;
            if (status) status.textContent = `${technoeconomicRatingBasisLabel(basis)} is required `
                + 'because it is the selected source\'s frozen applied-capacity basis.';
        }

        function technoeconomicRenderGuidedCommercialControls() {
            const enabled = technoeconomicDomElement(
                'technoeconomicGuidedCommercialEnabled'
            );
            const fields = technoeconomicDomElement('technoeconomicGuidedCommercialFields');
            const active = enabled?.checked === true;
            if (enabled) enabled.setAttribute('aria-expanded', active ? 'true' : 'false');
            if (fields) fields.hidden = !active;
            const timing = technoeconomicDomElement(
                'technoeconomicGuidedCommercialCostTiming'
            )?.value;
            const unit = timing === 'equivalent_annual' ? '/year' : 'total PV';
            if (typeof document === 'object' && typeof document.querySelectorAll === 'function') {
                document.querySelectorAll('.tea-commercial-cost-unit').forEach((element) => {
                    element.textContent = unit;
                });
            }
        }

        function technoeconomicAppliedCapacity(source, system) {
            const operatingLimitKwac = technoeconomicOperatingLimitKwac(source);
            if (operatingLimitKwac !== null) {
                return `${technoeconomicFormatNumber(operatingLimitKwac, 2)} kWac`;
            }
            const installedWdc = system === 'solaredge'
                ? source?.solaredge_installed_wdc : source?.solectria_installed_wdc;
            return technoeconomicFormatCapacity(installedWdc);
        }

        function technoeconomicFormatEnergy(value) {
            const kwh = Number(value);
            return Number.isFinite(kwh) && kwh > 0
                ? `${technoeconomicFormatNumber(kwh / 1000, 1)} MWh/year`
                : 'Unavailable';
        }

        function technoeconomicFormatCurrency(value) {
            const number = Number(value);
            return Number.isFinite(number)
                ? number.toLocaleString('en-US', {
                    style: 'currency', currency: 'USD', maximumFractionDigits: 0,
                })
                : 'Not available';
        }

        function technoeconomicFormatLcoe(value) {
            const number = Number(value);
            return Number.isFinite(number)
                ? number.toLocaleString('en-US', {
                    style: 'currency', currency: 'USD',
                    minimumFractionDigits: 3, maximumFractionDigits: 3,
                })
                : 'Not available';
        }

        function technoeconomicLifecycleFactors(
            discountPercent, degradationPercent, projectLifeYears
        ) {
            const life = Number(projectLifeYears);
            const discount = Number(discountPercent) / 100;
            const degradation = Number(degradationPercent) / 100;
            if (!Number.isSafeInteger(life) || life < 1
                || !Number.isFinite(discount) || discount <= -1
                || !Number.isFinite(degradation) || degradation < 0 || degradation >= 1) {
                return null;
            }
            const logGrowth = Math.log1p(discount);
            const annuityFactor = discount === 0
                ? life : -Math.expm1(-life * logGrowth) / discount;
            const logRatio = Math.log1p(-degradation) - logGrowth;
            const geometricSum = logRatio === 0
                ? life : Math.expm1(life * logRatio) / Math.expm1(logRatio);
            const energyFactor = geometricSum / (1 + discount);
            const capitalRecoveryFactor = 1 / annuityFactor;
            if (![annuityFactor, energyFactor, capitalRecoveryFactor].every(
                (value) => Number.isFinite(value) && value > 0
            )) return null;
            return {annuityFactor, energyFactor, capitalRecoveryFactor};
        }

        function technoeconomicGuidedEstimate(options = {}) {
            const present = (value) => value !== '' && value !== null && value !== undefined;
            const number = (value, fallback = null) => {
                const parsed = Number(value);
                return present(value) && Number.isFinite(parsed) && parsed >= 0 ? parsed : fallback;
            };
            const discountNumber = (value, fallback = null) => {
                const parsed = Number(value);
                return present(value) && Number.isFinite(parsed) && parsed > -100
                    ? parsed : fallback;
            };
            const degradationNumber = (value, fallback = null) => {
                if (!present(value)) return fallback;
                const parsed = number(value);
                return parsed !== null && parsed < 100 ? parsed : null;
            };
            const range = (centralValue, lowValue, highValue, parser, fallback = null) => {
                const central = parser(centralValue, fallback);
                const hasLow = present(lowValue);
                const hasHigh = present(highValue);
                if (central === null || hasLow !== hasHigh) return null;
                const low = hasLow ? parser(lowValue) : central;
                const high = hasHigh ? parser(highValue) : central;
                if (low === null || high === null || low > central || central > high) return null;
                return {low, central, high};
            };
            const rangeValues = (value) => [...new Set([value.low, value.central, value.high])];
            const projectLifeYears = Number(options.projectLifeYears);
            const capex = range(
                options.capex, options.capexLow, options.capexHigh, number
            );
            const annualOm = range(
                options.annualOm, options.omLow, options.omHigh, number
            );
            const discount = range(
                options.discountPercent,
                options.discountLowPercent,
                options.discountHighPercent,
                discountNumber
            );
            const degradation = range(
                options.degradationPercent,
                options.degradationLowPercent,
                options.degradationHighPercent,
                degradationNumber,
                0
            );
            const energies = (Array.isArray(options.annualEnergies)
                ? options.annualEnergies : [])
                .map(Number)
                .filter((value) => Number.isFinite(value) && value > 0)
                .sort((left, right) => left - right);
            if (!capex || !annualOm || !discount || !degradation
                || !Number.isSafeInteger(projectLifeYears) || projectLifeYears < 1
                || !energies.length) return null;

            const centralFactors = technoeconomicLifecycleFactors(
                discount.central, degradation.central, projectLifeYears
            );
            if (!centralFactors) return null;
            const lifecycleCost = capex.central
                + (annualOm.central * centralFactors.annuityFactor);
            const typicalEnergy = technoeconomicQuantile(energies, 0.5);
            const lcoeCentral = lifecycleCost
                / (typicalEnergy * centralFactors.energyFactor);
            const lcoeCandidates = [];
            for (const capexValue of rangeValues(capex)) {
                for (const omValue of rangeValues(annualOm)) {
                    for (const discountValue of rangeValues(discount)) {
                        for (const degradationValue of rangeValues(degradation)) {
                            const factors = technoeconomicLifecycleFactors(
                                discountValue, degradationValue, projectLifeYears
                            );
                            if (!factors) return null;
                            const cost = capexValue + (omValue * factors.annuityFactor);
                            for (const energy of [energies[0], energies[energies.length - 1]]) {
                                lcoeCandidates.push(cost / (energy * factors.energyFactor));
                            }
                        }
                    }
                }
            }
            if (![lifecycleCost, lcoeCentral, ...lcoeCandidates].every(Number.isFinite)) return null;
            return {
                lifecycleCost,
                annualizedCost: lifecycleCost * centralFactors.capitalRecoveryFactor,
                typicalEnergy,
                lcoeLow: Math.min(...lcoeCandidates, lcoeCentral),
                lcoeCentral,
                lcoeHigh: Math.max(...lcoeCandidates, lcoeCentral),
            };
        }

        function technoeconomicNaturalList(items) {
            if (items.length < 2) return items[0] || '';
            if (items.length === 2) return `${items[0]} and ${items[1]}`;
            return `${items.slice(0, -1).join(', ')}, and ${items.at(-1)}`;
        }

        function technoeconomicGuidedEstimatePrompt(system, source, guided) {
            if (!source) return 'Select an Annual source';
            if (source.eligible !== true) return 'Select an eligible Annual source';
            if (!technoeconomicAnnualEnergies(source, system).length) {
                return 'Annual energy is unavailable';
            }
            const prefix = system === 'solaredge' ? 'solaredge' : 'solectria';
            const missing = [
                [guided.project_life_years, 'project life'],
                [guided.discount, 'discount rate'],
                [guided[`${prefix}_capex`], 'CAPEX'],
                [guided[`${prefix}_om`], 'annual O&M'],
            ].filter(([value]) => !technoeconomicText(value).trim())
                .map(([, label]) => label);
            return missing.length
                ? `Enter ${technoeconomicNaturalList(missing)}`
                : 'Check project settings and uncertainty ranges';
        }

        function technoeconomicSetGuidedEstimate(system, source, guided) {
            const solaredge = system === 'solaredge';
            const prefix = solaredge ? 'solaredge' : 'solectria';
            const elementPrefix = solaredge ? 'guidedSolarEdge' : 'guidedSolectria';
            const energies = technoeconomicAnnualEnergies(source, system);
            const typicalEnergy = technoeconomicQuantile(energies, 0.5);
            const capacityElement = technoeconomicElements[`${elementPrefix}Capacity`];
            const energyElement = technoeconomicElements[`${elementPrefix}Energy`];
            if (capacityElement) capacityElement.textContent = source
                ? technoeconomicAppliedCapacity(source, system) : 'Select a source';
            if (energyElement) energyElement.textContent = source
                ? technoeconomicFormatEnergy(typicalEnergy) : 'Select a source';
            const estimate = technoeconomicGuidedEstimate({
                capex: guided[`${prefix}_capex`],
                capexLow: guided[`${prefix}_capex_low`],
                capexHigh: guided[`${prefix}_capex_high`],
                annualOm: guided[`${prefix}_om`],
                omLow: guided[`${prefix}_om_low`],
                omHigh: guided[`${prefix}_om_high`],
                projectLifeYears: guided.project_life_years,
                discountPercent: guided.discount,
                discountLowPercent: guided.discount_low,
                discountHighPercent: guided.discount_high,
                degradationPercent: guided.degradation || '0',
                degradationLowPercent: guided.degradation_low,
                degradationHighPercent: guided.degradation_high,
                annualEnergies: energies,
            });
            const root = technoeconomicElements[`${elementPrefix}Estimate`];
            const lifecycle = technoeconomicElements[`${elementPrefix}LifecycleCost`];
            const annualized = technoeconomicElements[`${elementPrefix}AnnualizedCost`];
            const lcoe = technoeconomicElements[`${elementPrefix}LcoeRange`];
            if (root) root.dataset.state = estimate ? 'ready' : 'empty';
            if (lifecycle) lifecycle.textContent = estimate
                ? technoeconomicFormatCurrency(estimate.lifecycleCost)
                : technoeconomicGuidedEstimatePrompt(system, source, guided);
            if (annualized) annualized.textContent = estimate
                ? `${technoeconomicFormatCurrency(estimate.annualizedCost)}/year` : 'Not available';
            if (lcoe) lcoe.textContent = estimate
                ? `${technoeconomicFormatLcoe(estimate.lcoeLow)}–${technoeconomicFormatLcoe(
                    estimate.lcoeHigh
                )}/kWh · central ${technoeconomicFormatLcoe(estimate.lcoeCentral)}`
                : 'Not available';
        }

        function technoeconomicRenderGuidedEstimates() {
            const sourceId = technoeconomicElements.sourceSelect?.value || '';
            const source = technoeconomicSources.find(
                (item) => item?.source_annual_job_id === sourceId
            ) || null;
            const guided = technoeconomicReadGuidedForm();
            technoeconomicSetGuidedEstimate('solectria', source, guided);
            technoeconomicSetGuidedEstimate('solaredge', source, guided);
            technoeconomicRenderGuidedCommercialControls();
        }

        function technoeconomicRenderSelectedSource() {
            const sourceId = technoeconomicElements.sourceSelect?.value || '';
            const source = technoeconomicSources.find((item) => item.source_annual_job_id === sourceId);
            const details = technoeconomicElements.sourceDetails;
            const energyRows = technoeconomicElements.sourceEnergyRows;
            technoeconomicSyncGuidedCommercialSourceBasis(source);
            if (details) details.hidden = true;
            if (energyRows) energyRows.replaceChildren();
            if (!sourceId) {
                technoeconomicSetSourceState(
                    'idle', 'Choose an Annual Simulation source',
                    'Select a source to review its operating limit, installed capacity, and yearly energy.'
                );
                technoeconomicRenderGuidedEstimates();
                return;
            }
            if (!source) {
                technoeconomicSetSourceState(
                    'unverified', 'Source must be refreshed',
                    'The saved Annual job ID is not in the current eligibility response.'
                );
                technoeconomicRenderGuidedEstimates();
                return;
            }
            const yearly = (Array.isArray(source.annual_energy_by_year)
                ? source.annual_energy_by_year : [])
                .filter((row) => Number.isInteger(Number(row?.year)))
                .sort((left, right) => Number(left.year) - Number(right.year));
            if (source.eligible !== true) {
                technoeconomicSetSourceState(
                    'ineligible', 'Annual source is not eligible',
                    source.detail || source.reason_code || 'The current provenance checks did not pass.'
                );
            } else {
                technoeconomicSetSourceState(
                    'ready', 'Calibrated annual energy is ready',
                    `${yearly.length} eligible weather year${yearly.length === 1 ? '' : 's'} will be frozen and re-verified at submission.`
                );
            }
            const provenance = technoeconomicPlainObject(source.provenance);
            const operatingLimit = technoeconomicPlainObject(provenance.operating_limit);
            const limit = technoeconomicOperatingLimitKwac(source);
            const operatingText = limit !== null
                ? `${technoeconomicFormatNumber(limit, 2)} kWac`
                : operatingLimit.curtailment_enabled === false
                    ? 'No AC limit enabled' : 'Unavailable';
            const setText = (element, text) => {
                if (element) element.textContent = text;
            };
            setText(technoeconomicElements.sourceOperatingLimit, operatingText);
            setText(
                technoeconomicElements.sourceCapacityNote,
                (limit !== null
                    ? 'The AC operating limit is already reflected in energy and is the '
                        + 'applied capacity used for cost and energy normalization. '
                    : operatingLimit.curtailment_enabled === false
                        ? 'The selected run did not enable an AC operating limit, so installed '
                            + 'DC nameplate is the applied capacity used for normalization. '
                        : 'A valid AC operating limit is unavailable, so installed DC nameplate '
                            + 'is the applied capacity used for normalization. ')
                    + 'The installed DC record remains separate engineering provenance.'
            );
            setText(
                technoeconomicElements.sourceSolectriaCapacity,
                technoeconomicAppliedCapacity(source, 'solectria')
            );
            setText(
                technoeconomicElements.sourceSolarEdgeCapacity,
                technoeconomicAppliedCapacity(source, 'solaredge')
            );
            setText(
                technoeconomicElements.sourceSolectriaEnergy,
                technoeconomicFormatEnergy(technoeconomicQuantile(
                    technoeconomicAnnualEnergies(source, 'solectria'), 0.5
                ))
            );
            setText(
                technoeconomicElements.sourceSolarEdgeEnergy,
                technoeconomicFormatEnergy(technoeconomicQuantile(
                    technoeconomicAnnualEnergies(source, 'solaredge'), 0.5
                ))
            );
            if (energyRows) {
                yearly.forEach((row) => {
                    energyRows.append(technoeconomicNode('tr', {}, [
                        technoeconomicNode('th', {text: String(row.year), scope: 'row'}),
                        technoeconomicNode('td', {
                            text: technoeconomicFormatEnergy(row.solectria_kwh),
                        }),
                        technoeconomicNode('td', {
                            text: technoeconomicFormatEnergy(row.solaredge_kwh),
                        }),
                    ]));
                });
                if (!yearly.length) {
                    energyRows.append(technoeconomicNode('tr', {}, [
                        technoeconomicNode('td', {
                            text: 'No eligible yearly energy is available.', colSpan: 3,
                        }),
                    ]));
                }
            }
            if (details) details.hidden = false;
            technoeconomicRenderGuidedEstimates();
        }

        function technoeconomicRenderSourceOptions(selectedId = '') {
            const select = technoeconomicElements.sourceSelect;
            if (!select) return;
            const ordered = technoeconomicSources.filter(
                (source) => source?.eligible === true
            ).sort((left, right) => String(
                right.provenance?.completed_at || ''
            ).localeCompare(String(left.provenance?.completed_at || '')));
            const requestedSelectedId = selectedId
                || technoeconomicPendingSourceId
                || technoeconomicElements.standaloneSourceSelect?.value
                || technoeconomicElements.sourceSelect?.value
                || '';
            const resolvedSelectedId = ordered.some(
                (source) => source.source_annual_job_id === requestedSelectedId
            ) ? requestedSelectedId : ordered[0]?.source_annual_job_id || '';
            const populate = (target) => {
                if (!target) return;
                target.replaceChildren(technoeconomicNode('option', {
                    value: '', text: 'Select a completed, verified Annual Simulation',
                }));
                for (const source of ordered) {
                    const years = Array.isArray(source.eligible_years)
                        ? ` | ${source.eligible_years.join(', ')}` : '';
                    target.appendChild(technoeconomicNode('option', {
                        value: source.source_annual_job_id,
                        text: `${source.source_annual_job_id}${years}`,
                    }));
                }
                target.value = resolvedSelectedId;
            };
            populate(select);
            populate(technoeconomicElements.standaloneSourceSelect);
            technoeconomicPendingSourceId = '';
            technoeconomicRenderSelectedSource();
            technoeconomicRenderStandaloneDraft();
            if (technoeconomicJob?.state === 'done' && technoeconomicJob.result) {
                renderTechnoeconomicJobResult(technoeconomicJob);
            }
        }

        async function refreshTechnoeconomicSources(options = {}) {
            const revision = ++technoeconomicSourceRequestRevision;
            if (technoeconomicSourceAbortController) technoeconomicSourceAbortController.abort();
            const controller = new AbortController();
            technoeconomicSourceAbortController = controller;
            let timedOut = false;
            const timeoutId = setTimeout(() => {
                timedOut = true;
                controller.abort();
            }, TECHNOECONOMIC_SOURCE_REFRESH_TIMEOUT_MS);
            const selectedId = options.selectedId !== undefined
                ? options.selectedId
                : technoeconomicPendingSourceId
                    || technoeconomicElements.standaloneSourceSelect?.value
                    || technoeconomicElements.sourceSelect?.value
                    || '';
            technoeconomicSetSourceRefreshBusy(true);
            technoeconomicSetSourcePlaceholder('Checking verified Annual Simulations…');
            technoeconomicSetSourceState(
                'loading', 'Checking Annual Simulation sources',
                'Eligible runs will appear automatically. Choose Retry source check if this request stalls.'
            );
            try {
                const body = await technoeconomicFetchJson('/api/technoeconomic/sources', {
                    signal: controller.signal,
                });
                if (revision !== technoeconomicSourceRequestRevision) return technoeconomicSources;
                const rows = Array.isArray(body.sources) ? body.sources : [];
                technoeconomicSources = rows.filter((row) => {
                    const id = row?.source_annual_job_id;
                    return typeof id === 'string' && id.length > 0 && id.length <= 200;
                }).map((row) => ({...row}));
                technoeconomicCloseStaleAdvancedPreview();
                technoeconomicRenderSourceOptions(selectedId);
                if (!technoeconomicSources.some((source) => source.eligible === true)) {
                    technoeconomicSetSourceState(
                        'empty', 'No verified Annual Simulation sources',
                        'Complete a calibrated Annual Simulation, then refresh this list.'
                    );
                }
                return technoeconomicSources;
            } catch (error) {
                if (revision !== technoeconomicSourceRequestRevision) {
                    return technoeconomicSources;
                }
                if (error.code === 'request_aborted' && !timedOut) {
                    return technoeconomicSources;
                }
                technoeconomicSetSourcePlaceholder(
                    timedOut
                        ? 'Source check timed out — refresh to retry'
                        : 'Sources unavailable — refresh to retry'
                );
                technoeconomicSetSourceState(
                    'reconnecting',
                    timedOut ? 'Source check timed out' : 'Could not refresh sources',
                    timedOut
                        ? 'The server did not answer within 15 seconds. Choose Refresh sources to try again.'
                        : error.message
                );
                return technoeconomicSources;
            } finally {
                clearTimeout(timeoutId);
                if (revision === technoeconomicSourceRequestRevision) {
                    technoeconomicSetSourceRefreshBusy(false);
                }
            }
        }

        function technoeconomicDeepFreeze(value) {
            if (!value || typeof value !== 'object' || Object.isFrozen(value)) return value;
            Object.freeze(value);
            for (const item of Object.values(value)) technoeconomicDeepFreeze(item);
            return value;
        }

        function technoeconomicSummaryItem(label, value) {
            const item = technoeconomicNode('div', {className: 'tea-summary-item'});
            item.append(
                technoeconomicNode('span', {text: label}),
                technoeconomicNode('strong', {text: value})
            );
            return item;
        }

        function technoeconomicConfirmationGroup(title, items, options = {}) {
            const section = technoeconomicNode('section', {
                className: `tea-confirm-group${options.className ? ` ${options.className}` : ''}`,
            });
            const rows = technoeconomicNode('div', {className: 'tea-confirm-group-rows'});
            rows.append(...items);
            section.append(
                technoeconomicNode('h4', {text: title}),
                rows
            );
            if (options.trailing) section.append(options.trailing);
            return section;
        }

        function technoeconomicConfirmationSystem(system, label, items) {
            const section = technoeconomicNode('article', {className: 'tea-confirm-system'});
            section.dataset.system = system;
            section.append(technoeconomicNode('h5', {text: label}), ...items);
            return section;
        }

        function technoeconomicConfirmationReadinessItem(title, description, status) {
            const heading = technoeconomicNode('div', {className: 'tea-confirm-readiness-heading'});
            heading.append(
                technoeconomicNode('strong', {text: title}),
                technoeconomicNode('span', {
                    className: 'tea-confirm-readiness-status', text: status,
                })
            );
            const item = technoeconomicNode('article', {className: 'tea-confirm-readiness-item'});
            item.append(heading, technoeconomicNode('p', {text: description}));
            return item;
        }

        function technoeconomicRenderConfirmationReadiness(items) {
            const readiness = technoeconomicElements.confirmReadiness;
            if (!readiness) return;
            readiness.replaceChildren(...items.map((item) => (
                technoeconomicConfirmationReadinessItem(
                    item.title, item.description, item.status
                )
            )));
        }

        function technoeconomicReviewDistribution(value) {
            const distribution = technoeconomicPlainObject(value);
            const family = distribution.family || 'unknown';
            const fields = ({
                fixed: ['value'],
                uniform: ['low', 'high'],
                triangular: ['low', 'mode', 'high'],
                bounded_normal: ['low', 'high', 'mean', 'sd'],
            })[family] || [];
            const parameters = fields.map((field) => `${field}=${distribution[field]}`).join(', ');
            return parameters ? `${family} (${parameters})` : family;
        }

        function technoeconomicReviewEvidence(value) {
            const evidence = technoeconomicPlainObject(value);
            const citation = technoeconomicPlainObject(evidence.citation);
            const locator = citation.url || citation.stable_reference || 'no locator';
            const parts = [
                evidence.evidence_class || 'unknown class',
                [citation.organization, citation.title].filter(Boolean).join(' | '),
                locator,
                [
                    citation.publication_or_as_of_date
                        ? `published/as of ${citation.publication_or_as_of_date}` : '',
                    citation.accessed_date ? `accessed ${citation.accessed_date}` : '',
                ].filter(Boolean).join('; '),
                citation.user_supplied_content_sha256
                    ? `user content SHA-256 ${citation.user_supplied_content_sha256}` : '',
                evidence.explicit_acceptance === true
                    ? `provisional acceptance: ${evidence.acceptance_rationale}` : '',
            ].filter(Boolean);
            return parts.join(' | ');
        }

        function technoeconomicReviewTechnology(label, value) {
            const design = technoeconomicPlainObject(value);
            return `${label}: optimizers=${design.optimizer_count}, inverters=${design.inverter_count}, `
                + `transformers=${design.transformer_count}, DC/AC=${design.dc_ac_ratio}, `
                + `loading=${design.inverter_loading_ratio}; inverter topology=${design.inverter_topology}; `
                + `transformer topology=${design.transformer_topology}; BOS=${design.bos_scope}; `
                + `labor=${design.labor_productivity_and_rates}; commissioning=${design.commissioning_scope}`;
        }

        function technoeconomicReviewCostLine(line, index) {
            const currency = technoeconomicPlainObject(line.currency_year_normalization);
            const coverage = `include=[${(line.coverage_include_ids || []).join(', ')}], `
                + `exclude=[${(line.coverage_exclude_ids || []).join(', ')}]`;
            const quantities = `Solectria quantity=${line.solectria_quantity}, `
                + `SolarEdge quantity=${line.solaredge_quantity}`
                + (line.quantity_unit ? ` ${line.quantity_unit}` : '');
            const currencyReview = `${currency.method}; ${currency.source_cost_year} to `
                + `${currency.target_constant_dollar_cost_year}; index=${currency.index_identity}; `
                + `factor=${currency.index_factor}; ${currency.derivation}`;
            return technoeconomicSummaryItem(
                `Cost line ${index + 1}: ${line.input_id}`,
                `${line.label} | ${line.ownership} | ${line.cost_type} | `
                + `${technoeconomicReviewDistribution(line.distribution)} | `
                + `${line.original_unit} to ${line.normalized_unit} by ${line.normalization_method}; `
                + `${quantities}; ${coverage}; normalization: ${line.normalization_derivation}; `
                + `currency: ${currencyReview}; evidence: ${technoeconomicReviewEvidence(line.evidence)}`
            );
        }

        function technoeconomicConfirmationSource(source) {
            const value = technoeconomicPlainObject(source);
            const applied = technoeconomicPlainObject(value.applied_capacity);
            const appliedFor = (system) => {
                const item = technoeconomicPlainObject(applied[system]);
                const watts = Number(item.applied_capacity_w);
                return {
                    applied_capacity_w: Number.isFinite(watts) && watts > 0 ? watts : null,
                    rating_basis: ['ac_operating_limit', 'dc_installed_nameplate'].includes(
                        item.rating_basis
                    ) ? item.rating_basis : null,
                };
            };
            return {
                source_annual_job_id: typeof value.source_annual_job_id === 'string'
                    ? value.source_annual_job_id : '',
                source_snapshot_sha256: typeof value.source_snapshot_sha256 === 'string'
                    ? value.source_snapshot_sha256 : '',
                eligible_years: Array.isArray(value.eligible_years)
                    ? value.eligible_years.filter(Number.isSafeInteger) : [],
                solectria_installed_wdc: Number.isFinite(Number(value.solectria_installed_wdc))
                    ? Number(value.solectria_installed_wdc) : null,
                solaredge_installed_wdc: Number.isFinite(Number(value.solaredge_installed_wdc))
                    ? Number(value.solaredge_installed_wdc) : null,
                applied_capacity: {
                    solectria: appliedFor('solectria'),
                    solaredge: appliedFor('solaredge'),
                },
            };
        }

        function technoeconomicConfirmationCapacity(sourceSummary, system, applied) {
            if (applied) {
                const item = technoeconomicPlainObject(sourceSummary.applied_capacity?.[system]);
                const watts = Number(item.applied_capacity_w);
                if (Number.isFinite(watts) && watts > 0) {
                    const basis = item.rating_basis === 'ac_operating_limit'
                        ? 'AC operating limit' : 'installed DC nameplate fallback';
                    return `${technoeconomicFormatNumber(watts, 1)} W (${basis})`;
                }
                return 'Re-verified by server at submission';
            }
            const installed = system === 'solectria'
                ? sourceSummary.solectria_installed_wdc : sourceSummary.solaredge_installed_wdc;
            return installed === null ? 'Unavailable'
                : `${technoeconomicFormatNumber(installed, 1)} Wdc`;
        }

        function technoeconomicRenderStandaloneConfirmation(serialized, sourceSummary) {
            const payload = serialized.payload;
            const standalone = technoeconomicPlainObject(payload.standalone_commercial);
            const paired = technoeconomicPlainObject(payload.paired_commercial);
            const commercial = Object.keys(paired).length ? paired : standalone;
            const pairedSystems = Array.isArray(paired.systems) ? paired.systems : [];
            const lifecycle = technoeconomicPlainObject(paired.lifecycle);
            const lifecycleSystems = Array.isArray(lifecycle.systems)
                ? lifecycle.systems : [];
            const lifecycleV6 = payload.calculation_contract_version
                === TECHNOECONOMIC_LIFECYCLE_CONTRACT_VERSION
                && Object.keys(lifecycle).length > 0;
            const lifecycleUsesTemplate = lifecycleV6
                && technoeconomicLifecycleMatchesTemplateShape(lifecycle);
            const lifecycleDistributionText = (documented, multiplier = 1) => (
                technoeconomicStandaloneDistributionDisplay(
                    technoeconomicPlainObject(documented).distribution, multiplier
                )
            );
            const targetWatts = Number(commercial.target_capacity)
                * (commercial.target_capacity_unit === 'mw' ? 1000000 : 1000);
            const systems = pairedSystems.length ? pairedSystems : [{
                technology: 'solaredge', cost_lines: standalone.cost_lines,
            }];
            const costLineCount = systems.reduce(
                (count, system) => count + system.cost_lines.length, 0
            );
            const provisionalCount = serialized.provisionalEvidenceCount;

            technoeconomicRenderConfirmationReadiness([
                {
                    title: 'Source locked', status: 'Locked',
                    description: 'The Previous Annual Simulation source is verified and frozen.',
                },
                {
                    title: 'Scale & sampling', status: 'Set',
                    description: 'Commercial scale, LHS realizations, sampling seed, and contract are set.',
                },
                {
                    title: 'Finance reviewed', status: 'Reviewed',
                    description: 'Financial assumptions are frozen in the selected constant-dollar year.',
                },
                {
                    title: lifecycleV6 ? 'Lifecycle evidence reviewed' : 'Cost evidence accepted',
                    status: lifecycleV6 && provisionalCount ? 'Provisional' : 'Accepted',
                    description: provisionalCount
                        ? `${provisionalCount} provisional evidence record${
                            provisionalCount === 1 ? ' is' : 's are'
                        } accepted for this request. ${lifecycleUsesTemplate
                            ? 'The values come from provisional template v1, not vendor data.'
                            : ''}`
                        : 'All submitted cost-line evidence is recorded with this request.',
                },
            ]);

            const summary = technoeconomicElements.confirmSummary;
            if (summary) {
                const sourceItems = [
                    technoeconomicSummaryItem('Annual source', payload.source_annual_job_id),
                    technoeconomicSummaryItem('Status', 'Verified prior run (frozen)'),
                    technoeconomicSummaryItem(
                        'Frozen source snapshot SHA-256',
                        sourceSummary.source_snapshot_sha256 || 'Re-verified by server at submission'
                    ),
                    technoeconomicSummaryItem(
                        'Eligible weather years',
                        sourceSummary.eligible_years.join(', ') || 'Re-verified by server at submission'
                    ),
                    technoeconomicSummaryItem(
                        'Weather-year allocation', lifecycleV6
                            ? 'Balanced across realizations independently for every project year'
                            : 'Balanced seeded paired-year allocation'
                    ),
                    technoeconomicSummaryItem(
                        'Frozen Solectria applied capacity',
                        pairedSystems.length
                            ? technoeconomicConfirmationCapacity(sourceSummary, 'solectria', true)
                            : 'Not part of this v4 job'
                    ),
                    technoeconomicSummaryItem(
                        'Frozen SolarEdge applied capacity',
                        technoeconomicConfirmationCapacity(sourceSummary, 'solaredge', true)
                    ),
                ];
                const scaleItems = [
                    technoeconomicSummaryItem(
                        'Analysis', lifecycleV6
                            ? 'Paired lifecycle upgrade NPV (SolarEdge relative to Solectria)'
                            : pairedSystems.length
                            ? 'Paired commercial Solectria and SolarEdge LCOE'
                            : 'Standalone commercial SolarEdge LCOE'
                    ),
                    technoeconomicSummaryItem(
                        'Commercial target capacity',
                        technoeconomicStandaloneFormatCapacity(
                            targetWatts, commercial.target_rating_basis, {forceMw: true}
                        )
                    ),
                    technoeconomicSummaryItem(
                        'Frozen source scale',
                        technoeconomicStandaloneScaleText(sourceSummary, targetWatts)
                    ),
                    technoeconomicSummaryItem(
                        'Energy transfer',
                        `${technoeconomicHumanize(commercial.transfer_method)}; ${commercial.transfer_rationale}`
                    ),
                    technoeconomicSummaryItem(
                        'Sampling method', 'Seeded Latin Hypercube Sampling (LHS)'
                    ),
                    technoeconomicSummaryItem(
                        'Sampling contract', lifecycleV6
                            ? TECHNOECONOMIC_LIFECYCLE_SAMPLING_VERSION
                            : TECHNOECONOMIC_SAMPLING_VERSION
                    ),
                    technoeconomicSummaryItem('Realizations', payload.n.toLocaleString('en-US')),
                    technoeconomicSummaryItem('Sampling seed', String(payload.seed)),
                ];
                const financeItems = [
                    technoeconomicSummaryItem(
                        'Constant-dollar year', String(payload.finance.constant_dollar_cost_year)
                    ),
                    technoeconomicSummaryItem(
                        'Project life', `${payload.finance.project_life_years} years`
                    ),
                    technoeconomicSummaryItem(
                        'Real discount rate',
                        `${technoeconomicStandaloneDistributionDisplay(
                            payload.finance.real_discount_rate.distribution, 100
                        )}%`
                    ),
                    technoeconomicSummaryItem(
                        'Annual module degradation', lifecycleV6
                            ? lifecycleSystems.map((system) => `${
                                technoeconomicHumanize(system.technology)
                            }: ${technoeconomicStandaloneDistributionDisplay(
                                technoeconomicPlainObject(system.degradation).distribution, 100
                            )}%`).join('; ')
                            : `${technoeconomicStandaloneDistributionDisplay(
                                payload.shared_degradation.annual_rate.distribution, 100
                            )}%`
                    ),
                ];
                const costSummaryItems = [
                    technoeconomicSummaryItem(
                        lifecycleV6 ? 'Lifecycle component classes' : 'Commercial cost lines',
                        String(lifecycleV6
                            ? lifecycleSystems.reduce((count, system) => (
                                count + (Array.isArray(system.components)
                                    ? system.components.length : 0)
                            ), 0)
                            : costLineCount)
                    ),
                    technoeconomicSummaryItem(
                        'Evidence records', String(serialized.evidenceCount)
                    ),
                ];
                if (lifecycleV6) {
                    const commonEvent = Array.isArray(lifecycle.common_cause_events)
                        ? lifecycle.common_cause_events[0] : null;
                    costSummaryItems.push(
                        technoeconomicSummaryItem(
                            'Lifecycle input set', lifecycleUsesTemplate
                                ? `${TECHNOECONOMIC_LIFECYCLE_TEMPLATE_REFERENCE} · version 1 · provisional synthetic review fixture`
                                : 'Custom evidenced lifecycle specification'
                        ),
                        technoeconomicSummaryItem(
                            'Recommendation reliability mode',
                            `${technoeconomicHumanize(lifecycle.reliability_mode)}; ${
                                technoeconomicFormatNumber(
                                    Number(lifecycle.decision_probability_threshold) * 100, 4
                                )
                            }% decision threshold`
                        ),
                        technoeconomicSummaryItem(
                            'Electricity value',
                            `${lifecycleDistributionText(lifecycle.electricity_value)} real USD/kWh; `
                            + `${lifecycleDistributionText(
                                lifecycle.electricity_value_real_growth, 100
                            )}% real annual growth`
                        ),
                        technoeconomicSummaryItem(
                            'Upgrade NPV tie tolerance',
                            `${technoeconomicFormatNumber(
                                lifecycle.decision_npv_tolerance_usd_per_target_w, 6
                            )} USD/target W`
                        ),
                        technoeconomicSummaryItem(
                            'Component scaling',
                            `ceil(${technoeconomicFormatNumber(targetWatts / 1000, 2)} kW ÷ 100 kW) `
                            + `and ceil(${technoeconomicFormatNumber(
                                targetWatts / 1000, 2
                            )} kW ÷ 1,000 kW) per system`
                        )
                    );
                    if (commonEvent) {
                        costSummaryItems.push(technoeconomicSummaryItem(
                            'Shared site event',
                            `${lifecycleDistributionText(
                                commonEvent.annual_probability, 100
                            )}% annual probability; ${lifecycleDistributionText(
                                commonEvent.downtime_hours
                            )} hours; ${technoeconomicFormatNumber(
                                Number(commonEvent.capacity_impact) * 100, 4
                            )}% capacity; ${lifecycleDistributionText(
                                commonEvent.cost_per_event
                            )} real USD/event; ${lifecycleDistributionText(
                                commonEvent.real_cost_growth, 100
                            )}% real growth; paired across both systems`
                        ));
                    }
                }
                const systemGrid = technoeconomicNode('div', {
                    className: 'tea-confirm-system-grid',
                });
                (lifecycleV6 ? lifecycleSystems : systems).forEach((system) => {
                    const label = technoeconomicPairedSystem(system.technology)?.label
                        || technoeconomicHumanize(system.technology);
                    const costItems = [];
                    (system.cost_lines || []).forEach((line, index) => {
                        const years = line.timing === 'scheduled_year_end'
                            ? `; years ${line.occurrence_years.join(', ')}` : '';
                        costItems.push(technoeconomicSummaryItem(
                            `Cost line ${index + 1}: ${line.label}`,
                            `${technoeconomicHumanize(line.timing)}; ${
                                technoeconomicStandaloneCostReview(
                                    line, commercial.target_rating_basis,
                                    payload.finance.constant_dollar_cost_year
                                )
                            }${years}; evidence: ${technoeconomicReviewEvidence(line.evidence)}`
                        ));
                    });
                    if (lifecycleV6) {
                        const initialCostLine = Array.isArray(system.initial_cost_lines)
                            ? system.initial_cost_lines[0] : null;
                        costItems.push(
                            technoeconomicSummaryItem(
                                'Target BOM component classes',
                                String(Array.isArray(system.components)
                                    ? system.components.length : 0)
                            ),
                            technoeconomicSummaryItem(
                                'Source-energy basis',
                                technoeconomicHumanize(lifecycle.source_energy_basis)
                            ),
                            technoeconomicSummaryItem(
                                'Degradation and availability',
                                `${lifecycleDistributionText(system.degradation, 100)}% degradation/year; `
                                + `${lifecycleDistributionText(system.base_availability, 100)}% base availability`
                            ),
                            technoeconomicSummaryItem(
                                'Initial cost and base O&M',
                                `${initialCostLine
                                    ? lifecycleDistributionText(initialCostLine.cost_per_w)
                                    : 'Unavailable'} real ${payload.finance.constant_dollar_cost_year} `
                                + `USD/W${technoeconomicStandaloneRatingSuffix(
                                    commercial.target_rating_basis
                                )}; ${lifecycleDistributionText(
                                    system.base_om_cost_per_w_year, 1000
                                )} real USD/kW${technoeconomicStandaloneRatingSuffix(
                                    commercial.target_rating_basis
                                )}-year; ${lifecycleDistributionText(
                                    system.base_om_real_growth, 100
                                )}% real growth`
                            ),
                            technoeconomicSummaryItem(
                                'Terminal and scheduled costs',
                                `${lifecycleDistributionText(
                                    system.decommissioning_cost
                                )} real USD decommissioning; ${lifecycleDistributionText(
                                    system.salvage_value
                                )} real USD salvage; ${Array.isArray(system.scheduled_costs)
                                    && system.scheduled_costs.length
                                    ? `${system.scheduled_costs.length} scheduled cost line(s)`
                                    : 'no scheduled cost lines'}`
                            )
                        );
                        for (const component of Array.isArray(system.components)
                            ? system.components : []) {
                            const warranty = technoeconomicPlainObject(component.warranty);
                            costItems.push(technoeconomicSummaryItem(
                                `Component: ${technoeconomicHumanize(component.component_id)}`,
                                `${Number(component.count).toLocaleString('en-US')} units; `
                                + `${technoeconomicFormatNumber(
                                    Number(component.capacity_impact) * 100, 6
                                )}% capacity/unit; Weibull beta ${lifecycleDistributionText(
                                    component.weibull_beta
                                )}, eta ${lifecycleDistributionText(
                                    component.weibull_eta_years
                                )} years; repair ${lifecycleDistributionText(
                                    component.repair_hours
                                )} hours; emergency logistics ${lifecycleDistributionText(
                                    component.logistics_hours
                                )} hours`
                            ), technoeconomicSummaryItem(
                                `${technoeconomicHumanize(component.component_id)} costs, spares, and warranty`,
                                `Emergency hardware ${lifecycleDistributionText(
                                    component.emergency_unit_cost
                                )} USD; restock ${lifecycleDistributionText(
                                    component.restock_unit_cost
                                )} USD; labor ${lifecycleDistributionText(
                                    component.labor_cost
                                )} USD/failure; mobilization ${lifecycleDistributionText(
                                    component.mobilization_cost
                                )} USD/batch of ${component.batch_size}; initial/target spares `
                                + `${component.initial_spares}/${component.spare_target}; warranty `
                                + `${warranty.age_limit_years ?? 'none'} years at ${
                                    Number.isFinite(Number(warranty.fraction))
                                        ? technoeconomicFormatNumber(
                                            Number(warranty.fraction) * 100, 4
                                        ) : 'unavailable'
                                }% for ${(warranty.covered_cost_categories || []).join(', ') || 'none'}; `
                                + `${lifecycleDistributionText(
                                    component.real_cost_growth, 100
                                )}% real cost growth; ${Array.isArray(
                                    component.preventive_replacements
                                ) && component.preventive_replacements.length
                                    ? `${component.preventive_replacements.length} preventive schedule(s)`
                                    : 'no preventive replacements'}`
                            ));
                        }
                    }
                    systemGrid.append(technoeconomicConfirmationSystem(
                        system.technology, label, costItems
                    ));
                });
                summary.replaceChildren(
                    technoeconomicConfirmationGroup(
                        'Previous Annual Simulation source', sourceItems
                    ),
                    technoeconomicConfirmationGroup(
                        'Commercial scale & sampling', scaleItems
                    ),
                    technoeconomicConfirmationGroup('Financial assumptions', financeItems),
                    technoeconomicConfirmationGroup('System costs', costSummaryItems, {
                        className: 'tea-confirm-costs-group', trailing: systemGrid,
                    })
                );
            }
            if (technoeconomicElements.confirmProvisional) {
                technoeconomicElements.confirmProvisional.hidden = provisionalCount === 0;
                technoeconomicElements.confirmProvisional.textContent = provisionalCount
                    ? `${provisionalCount} provisional evidence record${
                        provisionalCount === 1 ? '' : 's'
                    } included. The accepted records are frozen with this request and remain available for audit.`
                    : '';
            }
            technoeconomicRenderErrors(technoeconomicElements.confirmError, []);
        }

        function technoeconomicRenderConfirmation(serialized, sourceSummary) {
            const payload = serialized.payload;
            if (payload.paired_commercial || payload.standalone_commercial) {
                technoeconomicRenderStandaloneConfirmation(serialized, sourceSummary);
                return;
            }
            technoeconomicRenderConfirmationReadiness([
                {
                    title: 'Source locked', status: 'Locked',
                    description: 'The Previous Annual Simulation source is verified and frozen.',
                },
                {
                    title: 'Analysis & sampling', status: 'Set',
                    description: 'The analysis basis, LHS realizations, and sampling seed are set.',
                },
                {
                    title: 'Finance reviewed', status: 'Reviewed',
                    description: 'Financial and degradation assumptions are frozen for submission.',
                },
                {
                    title: 'Evidence accepted', status: 'Accepted',
                    description: serialized.provisionalEvidenceCount
                        ? 'Recorded provisional evidence acceptances are included.'
                        : 'All submitted evidence is recorded with this request.',
                },
            ]);
            const summary = technoeconomicElements.confirmSummary;
            if (summary) {
                const items = [
                    technoeconomicSummaryItem('Annual source', payload.source_annual_job_id),
                    technoeconomicSummaryItem('Frozen source snapshot SHA-256',
                        sourceSummary.source_snapshot_sha256 || 'Re-verified by server at submission'),
                    technoeconomicSummaryItem('Eligible weather years',
                        sourceSummary.eligible_years.join(', ') || 'Re-verified by server at submission'),
                    technoeconomicSummaryItem('Weather-year allocation',
                        'Balanced seeded paired-year allocation'),
                    technoeconomicSummaryItem(
                        payload.capacity_normalization
                            ? 'Frozen Solectria applied capacity' : 'Frozen Solectria capacity',
                        technoeconomicConfirmationCapacity(
                            sourceSummary, 'solectria', Boolean(payload.capacity_normalization)
                        )
                    ),
                    technoeconomicSummaryItem(
                        payload.capacity_normalization
                            ? 'Frozen SolarEdge applied capacity' : 'Frozen SolarEdge capacity',
                        technoeconomicConfirmationCapacity(
                            sourceSummary, 'solaredge', Boolean(payload.capacity_normalization)
                        )
                    ),
                    technoeconomicSummaryItem('Capacity normalization',
                        payload.capacity_normalization || 'Legacy installed-Wdc contract'),
                    technoeconomicSummaryItem('Basis', payload.basis === 'solartac_site'
                        ? 'SolarTAC site as-built' : 'Commercial representative'),
                    technoeconomicSummaryItem('Sampling method',
                        'Seeded Latin Hypercube Sampling (LHS)'),
                    technoeconomicSummaryItem('Sampling contract',
                        TECHNOECONOMIC_SAMPLING_VERSION),
                    technoeconomicSummaryItem('Realizations', payload.n.toLocaleString('en-US')),
                    technoeconomicSummaryItem('Sampling seed', String(payload.seed)),
                    technoeconomicSummaryItem('Constant-dollar year', String(
                        payload.finance.constant_dollar_cost_year
                    )),
                    technoeconomicSummaryItem('Project life', `${payload.finance.project_life_years} years`),
                    technoeconomicSummaryItem('Cost lines', String(payload.cost_lines.length)),
                    technoeconomicSummaryItem('Evidence records', String(serialized.evidenceCount)),
                    technoeconomicSummaryItem('Energy treatment', payload.basis === 'solartac_site'
                        ? 'Frozen SolarTAC paired energy'
                        : payload.commercial_transfer ? 'Explicit approved commercial transfer'
                            : 'Cost-only; commercial energy unavailable'),
                    technoeconomicSummaryItem('Difference sign',
                        'Every marginal result is SolarEdge minus Solectria.'),
                    technoeconomicSummaryItem('Real discount-rate distribution',
                        `${payload.finance.real_discount_rate.unit}: ${technoeconomicReviewDistribution(
                            payload.finance.real_discount_rate.distribution
                        )}`),
                    technoeconomicSummaryItem('Real discount-rate evidence',
                        technoeconomicReviewEvidence(payload.finance.real_discount_rate.evidence)),
                    technoeconomicSummaryItem('Project-life evidence',
                        technoeconomicReviewEvidence(payload.finance.project_life_evidence)),
                    technoeconomicSummaryItem('Shared degradation distribution',
                        `${payload.shared_degradation.annual_rate.unit}: ${technoeconomicReviewDistribution(
                            payload.shared_degradation.annual_rate.distribution
                        )}`),
                    technoeconomicSummaryItem('Shared degradation evidence',
                        technoeconomicReviewEvidence(payload.shared_degradation.annual_rate.evidence)),
                ];
                payload.cost_lines.forEach((line, index) => {
                    items.push(technoeconomicReviewCostLine(line, index));
                });
                if (payload.commercial_scaling) {
                    const scaling = payload.commercial_scaling;
                    const capacityUnit = scaling.target_capacity_unit === 'mw' ? 'MW' : 'kW';
                    const costUnit = scaling.marginal_cost_unit === 'constant_usd_per_year'
                        ? 'constant USD/year' : 'constant USD';
                    items.push(
                        technoeconomicSummaryItem(
                            'Commercial target capacity',
                            `${technoeconomicFormatNumber(scaling.target_capacity, 6)} ${capacityUnit} `
                                + `(${technoeconomicRatingBasisLabel(scaling.target_rating_basis)})`
                        ),
                        technoeconomicSummaryItem(
                            'Commercial marginal cost difference',
                            `${technoeconomicReviewDistribution(
                                scaling.marginal_cost_difference
                            )} ${costUnit}; ${technoeconomicHumanize(
                                scaling.marginal_cost_timing
                            )}`
                        ),
                        technoeconomicSummaryItem(
                            'Commercial energy transfer',
                            `${technoeconomicHumanize(scaling.transfer_method)}; `
                                + scaling.transfer_rationale
                        ),
                        technoeconomicSummaryItem(
                            'Commercial scaling evidence',
                            technoeconomicReviewEvidence(scaling.evidence)
                        )
                    );
                }
                if (payload.commercial_reference_design) items.push(
                    technoeconomicSummaryItem('Commercial reference capacity',
                        `${technoeconomicFormatNumber(
                            payload.commercial_reference_design.reference_wdc, 1
                        )} Wdc`),
                    technoeconomicSummaryItem('Commercial reference design',
                        `${payload.commercial_reference_design.design_id}; module `
                        + `${payload.commercial_reference_design.module_model}; `
                        + `${payload.commercial_reference_design.module_count} × `
                        + `${payload.commercial_reference_design.module_stc_wdc} Wdc; `
                        + `normalization: ${payload.commercial_reference_design.normalization_derivation}`),
                    technoeconomicSummaryItem('Commercial Solectria design',
                        technoeconomicReviewTechnology(
                            'Solectria', payload.commercial_reference_design.solectria
                        )),
                    technoeconomicSummaryItem('Commercial SolarEdge design',
                        technoeconomicReviewTechnology(
                            'SolarEdge', payload.commercial_reference_design.solaredge
                        )),
                    technoeconomicSummaryItem('Commercial design evidence',
                        technoeconomicReviewEvidence(payload.commercial_reference_design.evidence)),
                    technoeconomicSummaryItem('Commercial transfer mode',
                        payload.commercial_transfer
                            ? 'Approved evidenced transfer' : 'Disabled; cost-only result')
                );
                if (payload.commercial_transfer) {
                    items.push(
                        technoeconomicSummaryItem('Transfer attestation',
                            `${payload.commercial_transfer.attested_by} at `
                            + `${payload.commercial_transfer.attested_at}; `
                            + payload.commercial_transfer.attestation_rationale),
                        technoeconomicSummaryItem('Baseline transfer factor',
                            technoeconomicReviewDistribution(
                                payload.commercial_transfer.baseline_factor.distribution
                            )),
                        technoeconomicSummaryItem('Baseline transfer evidence',
                            technoeconomicReviewEvidence(
                                payload.commercial_transfer.baseline_factor.evidence
                            )),
                        technoeconomicSummaryItem('Incremental transfer factor',
                            technoeconomicReviewDistribution(
                                payload.commercial_transfer.incremental_factor.distribution
                            )),
                        technoeconomicSummaryItem('Incremental transfer evidence',
                            technoeconomicReviewEvidence(
                                payload.commercial_transfer.incremental_factor.evidence
                            ))
                    );
                    payload.commercial_transfer.mechanisms.forEach((mechanism) => {
                        items.push(technoeconomicSummaryItem(
                            `Transfer mechanism: ${mechanism.mechanism}`,
                            `${mechanism.status}; ${mechanism.rationale}; evidence: `
                            + technoeconomicReviewEvidence(mechanism.evidence)
                        ));
                    });
                }
                summary.replaceChildren(
                    technoeconomicConfirmationGroup('Request details', items)
                );
            }
            if (technoeconomicElements.confirmProvisional) {
                const count = serialized.provisionalEvidenceCount;
                technoeconomicElements.confirmProvisional.hidden = count === 0;
                technoeconomicElements.confirmProvisional.textContent = count
                    ? `${count} provisional evidence ${count === 1 ? 'entry requires' : 'entries require'} the explicit acceptances recorded in this frozen request.`
                    : '';
            }
            technoeconomicRenderErrors(technoeconomicElements.confirmError, []);
        }

        function technoeconomicFinishAssumptionsClose() {
            const trigger = technoeconomicAssumptionsTrigger
                || technoeconomicElements.standaloneEditAssumptionsButton;
            if (technoeconomicAssumptionsReturnFocus) {
                trigger?.focus?.({preventScroll: true});
            }
            technoeconomicAssumptionsTrigger = null;
            technoeconomicAssumptionsReturnFocus = true;
        }

        const TECHNOECONOMIC_BUILDER_SECTIONS = [
            {
                key: 'source', label: 'Source & Scale',
                description: 'Choose the verified Annual Simulation and define the commercial target and reproducible sampling.',
            },
            {
                key: 'finance', label: 'Finance',
                description: 'Set the lifecycle horizon and evidenced real financial assumptions.',
            },
            {
                key: 'lifecycle', label: 'Lifecycle',
                description: 'Apply the approved planning template, then review and edit the aligned Solectria and SolarEdge assumptions.',
            },
            {
                key: 'reliability', label: 'Reliability',
                description: 'Review component scaling, availability, failure treatment, spares, and the shared site event.',
            },
            {
                key: 'value', label: 'Value',
                description: 'Review electricity value, growth, tie tolerance, and the locked decision rule.',
            },
            {
                key: 'review', label: 'Evidence & Review',
                description: 'Confirm evidence completeness, provisional values, template differences, and the required acceptance.',
            },
        ];
        let technoeconomicBuilderSectionIndex = 0;

        function technoeconomicBuilderIssueTarget(error) {
            if (error?.element) {
                return {
                    section: error.section || 'review',
                    element: error.element,
                };
            }
            const path = technoeconomicText(error?.path);
            if (path === 'explicit_acceptance' || path.endsWith('.explicit_acceptance')) {
                return {
                    section: 'review',
                    element: technoeconomicElements?.standaloneAccept,
                };
            }
            if (path === 'acceptance_rationale' || path.endsWith('.acceptance_rationale')
                || path === 'evidence.assumption_note') {
                return {
                    section: 'review',
                    element: technoeconomicElements?.standaloneAssumptionNote,
                };
            }
            const generatedEvidencePath = /(^|\.)(evidence|project_life_evidence)(\.|$)/
                .test(path);
            const generatedEvidenceMode = technoeconomicSelectedContractVersion()
                === TECHNOECONOMIC_PAIRED_CONTRACT_VERSION
                || technoeconomicLifecycleEntryMode !== 'advanced';
            if (generatedEvidencePath && generatedEvidenceMode) {
                return {
                    section: 'review',
                    element: technoeconomicElements?.standaloneAssumptionNote,
                };
            }
            const financeDistributionMatch = path.match(
                /^(finance\.real_discount_rate|shared_degradation\.annual_rate)\.distribution\.(value|low|mode|high|mean|sd)$/
            );
            if (financeDistributionMatch) {
                const degradation = financeDistributionMatch[1].startsWith(
                    'shared_degradation'
                );
                const container = degradation
                    ? technoeconomicElements?.standaloneDegradationParameters
                    : technoeconomicElements?.standaloneDiscountParameters;
                return {
                    section: 'finance',
                    element: container?.querySelector?.(
                        `[data-tea-v4-param="${financeDistributionMatch[2]}"]`
                    ) || (degradation
                        ? technoeconomicElements?.standaloneDegradationFamily
                        : technoeconomicElements?.standaloneDiscountFamily),
                };
            }
            if ((path === 'shared_degradation' || path.startsWith('shared_degradation.'))
                && technoeconomicSelectedContractVersion()
                    === TECHNOECONOMIC_PAIRED_CONTRACT_VERSION) {
                return {
                    section: 'finance',
                    element: technoeconomicElements?.standaloneDegradationFamily,
                };
            }
            const systemMatch = path.match(
                /^paired_commercial(?:\.lifecycle)?\.systems\.(\d+)(?:\.(.*))?$/
            );
            if (systemMatch) {
                const prefix = Number(systemMatch[1]) === 1 ? 'SolarEdge' : 'Solectria';
                const suffix = technoeconomicText(systemMatch[2]);
                if (!path.startsWith('paired_commercial.lifecycle.systems.')) {
                    const container = technoeconomicElements?.[
                        `standalone${prefix}CostLines`
                    ];
                    const costMatch = suffix.match(
                        /^cost_lines\.(\d+)(?:\.distribution(?:\.(value|low|mode|high|mean|sd))?)?/
                    );
                    const card = costMatch
                        ? Array.from(container?.querySelectorAll?.(
                            '[data-tea-v4-cost-line]'
                        ) || [])[Number(costMatch[1])]
                        : null;
                    const field = costMatch?.[2]
                        ? card?.querySelector?.(`[data-tea-v4-param="${costMatch[2]}"]`)
                        : card?.querySelector?.('select, input, textarea');
                    return {
                        section: 'lifecycle',
                        element: field || container,
                    };
                }
                const systemMappings = [
                    ['degradation', `lifecycle${prefix}Degradation`],
                    ['base_availability', `lifecycle${prefix}Availability`],
                    ['initial_cost_lines', `lifecycle${prefix}InitialCost`],
                    ['base_om_cost_per_w_year', `lifecycle${prefix}BaseOm`],
                    ['decommissioning_cost', `lifecycle${prefix}Decommissioning`],
                    ['salvage_value', `lifecycle${prefix}Salvage`],
                ];
                const systemField = systemMappings.find(([field]) =>
                    suffix === field || suffix.startsWith(`${field}.`)
                );
                if (systemField) {
                    return {
                        section: 'lifecycle',
                        element: technoeconomicElements?.[systemField[1]],
                    };
                }
                return {
                    section: 'lifecycle',
                    element: technoeconomicElements?.lifecycleJson,
                    reveal: technoeconomicElements?.lifecycleAdvancedDetails,
                };
            }
            const commonEventMatch = path.match(
                /^paired_commercial\.lifecycle\.common_cause_events\.\d+\.(.*)$/
            );
            if (commonEventMatch) {
                const suffix = commonEventMatch[1];
                const commonMappings = [
                    ['annual_probability', 'lifecycleCommonProbability'],
                    ['downtime_hours', 'lifecycleCommonDowntime'],
                    ['capacity_impact', 'lifecycleCommonImpact'],
                    ['cost_per_event', 'lifecycleCommonCost'],
                ];
                const commonField = commonMappings.find(([field]) =>
                    suffix === field || suffix.startsWith(`${field}.`)
                );
                if (commonField) {
                    return {
                        section: 'reliability',
                        element: technoeconomicElements?.[commonField[1]],
                    };
                }
            }
            const mappings = [
                ['source_annual_job_id', 'source', 'standaloneSourceSelect'],
                ['paired_commercial.target_capacity', 'source', 'standaloneTargetCapacityInput'],
                ['paired_commercial.target_rating_basis', 'source', 'standaloneSourceSelect'],
                ['n', 'source', 'standaloneRealizations'],
                ['seed', 'source', 'standaloneSeed'],
                ['finance.project_life_years', 'finance', 'standaloneProjectLife'],
                ['finance.project_life', 'finance', 'standaloneProjectLife'],
                ['finance.real_discount_rate', 'finance', 'standaloneDiscountFamily'],
                ['shared_degradation', 'lifecycle', 'lifecycleSolectriaDegradation'],
                ['lifecycle.electricity_value_real_growth', 'value', 'lifecycleElectricityGrowth'],
                ['lifecycle.electricity_value', 'value', 'lifecycleElectricityValue'],
                ['lifecycle.decision_npv_tolerance_usd_per_target_w', 'value', 'lifecycleNpvTolerance'],
                ['lifecycle.common_cause_events', 'reliability', 'lifecycleCommonProbability'],
                ['lifecycle.reliability_mode', 'reliability', 'lifecycleReliabilityMode'],
                ['lifecycle.source_energy_basis', 'lifecycle', 'lifecycleSourceBasis'],
                ['Lifecycle setup', 'lifecycle', 'useLifecycleTemplateButton'],
                ['cost_lines', 'lifecycle', 'standaloneSolectriaCostLines'],
                ['evidence.assumption_note', 'review', 'standaloneAssumptionNote'],
                ['evidence', 'review', 'standaloneAssumptionNote'],
            ];
            const match = mappings.find(([prefix]) => path === prefix
                || path.startsWith(`${prefix}.`)
                || path.endsWith(`.${prefix}`)
                || path.includes(`.${prefix}.`));
            if (match) return {section: match[1], element: technoeconomicElements?.[match[2]]};
            if (path === 'paired_commercial.lifecycle'
                || path.startsWith('paired_commercial.lifecycle.')) {
                if (technoeconomicLifecycleEntryMode === 'empty') {
                    return {
                        section: 'lifecycle',
                        element: technoeconomicElements?.useLifecycleTemplateButton,
                    };
                }
                return {
                    section: 'lifecycle',
                    element: technoeconomicElements?.lifecycleJson,
                    reveal: technoeconomicElements?.lifecycleAdvancedDetails,
                };
            }
            return {section: 'review', element: technoeconomicElements?.standaloneAssumptionNote};
        }

        function technoeconomicBuilderNormalizeIssue(error) {
            const path = technoeconomicText(error?.path);
            if (path === 'explicit_acceptance' || path.endsWith('.explicit_acceptance')) {
                return {
                    ...error,
                    path: 'evidence.explicit_acceptance',
                    message: 'Confirm the required review acceptance.',
                };
            }
            if (path === 'acceptance_rationale' || path.endsWith('.acceptance_rationale')
                || path === 'evidence.assumption_note') {
                return {
                    ...error,
                    path: 'evidence.assumption_note',
                    message: 'Document the source or justification for these assumptions.',
                };
            }
            const generatedEvidencePath = /(^|\.)(evidence|project_life_evidence)(\.|$)/
                .test(path);
            const generatedEvidenceMode = technoeconomicSelectedContractVersion()
                === TECHNOECONOMIC_PAIRED_CONTRACT_VERSION
                || technoeconomicLifecycleEntryMode !== 'advanced';
            if (generatedEvidencePath && generatedEvidenceMode) {
                return {
                    ...error,
                    path: 'evidence.assumption_note',
                    message: 'Document the source or justification for these assumptions.',
                };
            }
            return error;
        }

        function technoeconomicBuilderIssueLabel(error) {
            const message = technoeconomicText(error?.message) || 'Complete this requirement.';
            const target = technoeconomicBuilderIssueTarget(error).element;
            const conciseLabels = new Map([
                [technoeconomicElements?.standaloneSourceSelect, 'Previous Annual Simulation source'],
                [technoeconomicElements?.standaloneAssumptionNote, 'Source / justification'],
                [technoeconomicElements?.standaloneAccept, 'Review acceptance'],
                [technoeconomicElements?.useLifecycleTemplateButton, 'Approved lifecycle template'],
            ]);
            const explicitLabel = conciseLabels.get(target) || target?.labels?.[0]?.textContent;
            const rowLabel = target?.closest?.('tr')?.querySelector?.('th[scope="row"]')?.textContent;
            const label = technoeconomicText(explicitLabel || rowLabel)
                .replace(/\s+/g, ' ').trim();
            if (!label || message.toLocaleLowerCase().includes(label.toLocaleLowerCase())) {
                return message;
            }
            return `${label}: ${message}`;
        }

        function technoeconomicBuilderClearInlineErrors() {
            const dialog = technoeconomicElements?.standaloneAssumptionsDialog;
            dialog?.querySelectorAll?.('.tea-field-errors, .tea-field-error')
                .forEach((node) => node.remove());
            dialog?.querySelectorAll?.('[aria-invalid="true"]').forEach((node) => {
                node.removeAttribute('aria-invalid');
                const describedBy = technoeconomicText(node.getAttribute('aria-describedby'))
                    .split(/\s+/).filter((id) => id && !id.startsWith('tea-builder-error-'));
                if (describedBy.length) node.setAttribute('aria-describedby', describedBy.join(' '));
                else node.removeAttribute('aria-describedby');
            });
        }

        function technoeconomicBuilderRenderInlineErrors(errors) {
            technoeconomicBuilderClearInlineErrors();
            const grouped = new Map();
            for (const [index, error] of (errors || []).entries()) {
                const target = technoeconomicBuilderIssueTarget(error).element;
                if (!target) continue;
                const errorId = `tea-builder-error-${index}`;
                const message = technoeconomicNode('span', {
                    className: 'tea-field-error', id: errorId, text: error.message,
                });
                if (!grouped.has(target)) {
                    grouped.set(target, {
                        messages: new Set(),
                        node: technoeconomicNode('div', {
                            className: 'tea-field-errors',
                        }),
                    });
                }
                const group = grouped.get(target);
                if (group.messages.has(error.message)) continue;
                group.messages.add(error.message);
                group.node.appendChild(message);
                target.setAttribute?.('aria-invalid', 'true');
                const describedBy = technoeconomicText(target.getAttribute?.('aria-describedby'))
                    .split(/\s+/).filter(Boolean);
                if (!describedBy.includes(errorId)) describedBy.push(errorId);
                target.setAttribute?.('aria-describedby', describedBy.join(' '));
            }
            for (const [target, group] of grouped.entries()) {
                const checkboxRow = target.closest?.('.tea-checkbox-row');
                const templateHeading = target.closest?.('.tea-v6-template-heading');
                const host = checkboxRow?.parentElement
                    || templateHeading
                    || target.closest?.('.tea-field, .tea-v6-template-field, td')
                    || target.parentElement;
                host?.appendChild?.(group.node);
            }
        }

        function technoeconomicBuilderReviewCard(title, lines, status = '') {
            const card = technoeconomicNode('section', {className: 'tea-builder-review-card'});
            card.dataset.status = status;
            const heading = technoeconomicNode('div', {
                className: 'tea-builder-review-card-heading',
            });
            heading.appendChild(technoeconomicNode('h5', {text: title}));
            if (status) {
                const labels = {
                    verified: 'Verified', provisional: 'Provisional',
                    required: 'Required', locked: 'Locked',
                };
                heading.appendChild(technoeconomicNode('span', {
                    className: `tea-status-badge tea-status-${status}`,
                    text: labels[status] || status,
                }));
            }
            card.appendChild(heading);
            const list = technoeconomicNode('ul');
            for (const line of lines) list.appendChild(technoeconomicNode('li', {text: line}));
            card.appendChild(list);
            return card;
        }

        function technoeconomicBuilderLegacyPresetDifferences(draft) {
            const differences = [];
            for (const {key, label} of TECHNOECONOMIC_PAIRED_SYSTEMS) {
                const systemDraft = draft?.systems?.[key];
                const definitions = technoeconomicStandaloneCostDefinitions(
                    draft?.rating_basis, key
                );
                for (const definition of definitions) {
                    const line = (systemDraft?.cost_lines || []).find(
                        (candidate) => candidate.key === definition.key
                    );
                    const family = technoeconomicText(line?.distribution?.family);
                    const value = technoeconomicText(line?.distribution?.value).trim();
                    if (family !== 'fixed' || Number(value) !== Number(definition.value)) {
                        const current = line
                            ? `${family || 'unknown'}${value ? ` ${value}` : ''}`
                            : 'not entered';
                        differences.push(
                            `${label} ${definition.label}: ${current} `
                            + `(preset fixed ${definition.value})`
                        );
                    }
                }
                const extraLines = (systemDraft?.cost_lines || []).filter(
                    (line) => !definitions.some((definition) => definition.key === line.key)
                );
                if (extraLines.length) {
                    differences.push(
                        `${label}: ${extraLines.length} additional sourced cost ${
                            extraLines.length === 1 ? 'line' : 'lines'}`
                    );
                }
            }
            return differences;
        }

        function technoeconomicBuilderRenderReview(serialized) {
            const root = technoeconomicElements?.builderReviewSummary;
            if (!root) return;
            const payload = technoeconomicPlainObject(serialized?.payload);
            const paired = technoeconomicPlainObject(payload.paired_commercial);
            const systems = Array.isArray(paired.systems) ? paired.systems : [];
            const source = technoeconomicStandaloneSelectedSource();
            const lifecycleContract = technoeconomicSelectedContractVersion()
                === TECHNOECONOMIC_LIFECYCLE_CONTRACT_VERSION;
            const provisional = Number(serialized?.provisionalEvidenceCount || 0);
            const lifecycleSystemLines = (prefix) => [
                `Annual degradation: ${technoeconomicElements?.[`lifecycle${prefix}Degradation`]?.value || 'Not entered'}%`,
                `Base availability: ${technoeconomicElements?.[`lifecycle${prefix}Availability`]?.value || 'Not entered'}%`,
                `Initial installed cost: ${technoeconomicElements?.[`lifecycle${prefix}InitialCost`]?.value || 'Not entered'}`,
                `Base O&M: ${technoeconomicElements?.[`lifecycle${prefix}BaseOm`]?.value || 'Not entered'}`,
                `Decommissioning: ${technoeconomicElements?.[`lifecycle${prefix}Decommissioning`]?.value || 'Not entered'} USD`,
                `Salvage value: ${technoeconomicElements?.[`lifecycle${prefix}Salvage`]?.value || 'Not entered'} USD`,
            ];
            const standaloneDraft = !lifecycleContract
                ? technoeconomicStandaloneDraftSnapshot() : null;
            const templateDifferences = lifecycleContract
                ? technoeconomicLifecycleEntryMode === 'template'
                    ? technoeconomicLifecycleTemplateDifferences() : []
                : technoeconomicBuilderLegacyPresetDifferences(standaloneDraft);
            const templateLines = lifecycleContract
                ? technoeconomicLifecycleEntryMode === 'empty'
                    ? ['Approved template values have not been applied.']
                    : technoeconomicLifecycleEntryMode === 'advanced'
                        ? ['A custom Advanced lifecycle specification is active. Compare its documented values with the approved planning template before submission.']
                        : templateDifferences.length
                        ? ['Values changed from the approved planning template:',
                            ...templateDifferences]
                        : ['No values differ from the approved planning template.']
                : templateDifferences.length
                    ? ['Values changed from the NREL 2024 ATB cost preset:',
                        ...templateDifferences]
                    : ['No cost values differ from the NREL 2024 ATB preset.'];
            const legacySystemLines = (systemKey) => {
                const systemDraft = standaloneDraft?.systems?.[systemKey];
                const definitions = technoeconomicStandaloneCostDefinitions(
                    standaloneDraft?.rating_basis, systemKey
                );
                return (systemDraft?.cost_lines || []).map((line) => {
                    const definition = definitions.find((item) => item.key === line.key);
                    const values = Object.entries(line.distribution || {})
                        .filter(([key, value]) => key !== 'family'
                            && technoeconomicText(value).trim())
                        .map(([key, value]) => `${key} ${value}`).join(', ');
                    const family = technoeconomicText(line.distribution?.family || 'fixed');
                    return `${definition?.label || line.key}: ${family}${
                        values ? ` (${values})` : ''}`;
                });
            };
            const provisionalLines = lifecycleContract
                ? technoeconomicLifecycleEntryMode === 'empty'
                    ? ['The approved planning template has not been applied. The visible lifecycle values remain provisional and cannot be calculated until reviewed and applied.']
                    : [provisional
                        ? `${provisional} provisional evidence ${provisional === 1 ? 'entry' : 'entries'} require acceptance.`
                        : 'Applied lifecycle planning values remain provisional unless supported by project evidence.']
                : ['V5 benchmark costs and shared degradation remain editable; their evidence and acceptance are reviewed below.'];
            root.replaceChildren(
                technoeconomicBuilderReviewCard('Shared assumptions', [
                    `${technoeconomicElements?.standaloneTargetCapacityInput?.value || 'Not entered'} MW target capacity`,
                    `${technoeconomicElements?.standaloneProjectLife?.value || 'Not entered'}-year project life`,
                    `${technoeconomicElements?.standaloneRealizations?.value || 'Not entered'} seeded LHS trials`,
                    technoeconomicElements?.calculationContract?.selectedOptions?.[0]?.textContent
                        || technoeconomicSelectedContractVersion(),
                ], 'verified'),
                technoeconomicBuilderReviewCard('Solectria assumptions', [
                    ...(lifecycleContract
                        ? lifecycleSystemLines('Solectria') : legacySystemLines('solectria')),
                    `${lifecycleContract
                        ? systems.find((item) => item?.technology === 'solectria')?.cost_lines?.length || 0
                        : standaloneDraft?.systems?.solectria?.cost_lines?.length || 0} cost lines`,
                ], 'provisional'),
                technoeconomicBuilderReviewCard('SolarEdge assumptions', [
                    ...(lifecycleContract
                        ? lifecycleSystemLines('SolarEdge') : legacySystemLines('solaredge')),
                    `${lifecycleContract
                        ? systems.find((item) => item?.technology === 'solaredge')?.cost_lines?.length || 0
                        : standaloneDraft?.systems?.solaredge?.cost_lines?.length || 0} cost lines`,
                ], 'provisional'),
                technoeconomicBuilderReviewCard('Template comparison', templateLines,
                    lifecycleContract && technoeconomicLifecycleEntryMode === 'empty'
                        ? 'required' : provisional ? 'provisional' : 'verified'),
                technoeconomicBuilderReviewCard('Provisional values', [
                    ...provisionalLines,
                ], lifecycleContract || provisional ? 'provisional' : 'verified'),
                technoeconomicBuilderReviewCard('Evidence completeness', [
                    source ? 'Annual source selected for server re-verification.' : 'Annual source is required.',
                    technoeconomicText(technoeconomicElements?.standaloneAssumptionNote?.value).trim()
                        ? 'Source / justification provided.' : 'Source / justification is required.',
                    technoeconomicElements?.standaloneAccept?.checked
                        ? 'Required acceptance confirmed.' : 'Required acceptance is not confirmed.',
                ], serialized?.valid ? 'verified' : 'required'),
            );
        }

        function technoeconomicBuilderSectionState(
            key, issuesBySection, lifecycleContract, result
        ) {
            if (!lifecycleContract && ['reliability', 'value'].includes(key)) {
                return 'locked';
            }
            if (issuesBySection[key]?.length) return 'required';
            if (key === 'review' || key === 'source') return 'verified';
            if (key === 'finance') {
                return Number(result?.provisionalEvidenceCount || 0) > 0
                    ? 'provisional' : 'verified';
            }
            if (key === 'lifecycle' && !lifecycleContract) return 'provisional';
            if (lifecycleContract && ['lifecycle', 'reliability', 'value'].includes(key)) {
                return Number(result?.provisionalEvidenceCount || 0) > 0
                    ? 'provisional' : 'verified';
            }
            return 'verified';
        }

        function technoeconomicBuilderUpdate(serialized = null) {
            if (!technoeconomicElements?.builderSteps) return;
            const result = serialized || technoeconomicSerializeCurrentRequest({
                sources: technoeconomicSources,
            });
            const errors = Array.isArray(result.errors) ? result.errors : [];
            const displayErrors = [...errors];
            const issuesBySection = Object.fromEntries(
                TECHNOECONOMIC_BUILDER_SECTIONS.map(({key}) => [key, []])
            );
            for (const error of errors) {
                issuesBySection[technoeconomicBuilderIssueTarget(error).section].push(error);
            }
            const addRequirement = (section, requirement) => {
                const duplicate = displayErrors.some((error) =>
                    technoeconomicText(error?.path) === technoeconomicText(requirement.path)
                    && technoeconomicText(error?.message) === technoeconomicText(requirement.message)
                );
                if (duplicate) return;
                issuesBySection[section].push(requirement);
                displayErrors.push(requirement);
            };
            const discountInputs = Array.from(
                technoeconomicElements?.standaloneDiscountParameters?.querySelectorAll?.(
                    'input:not([disabled]), select:not([disabled])'
                ) || []
            );
            const emptyDiscountInput = discountInputs.find((input) =>
                !technoeconomicText(input.value).trim()
            );
            if (emptyDiscountInput) {
                addRequirement('finance', {
                    path: 'finance.real_discount_rate.distribution',
                    message: 'Enter the real discount-rate value.',
                    section: 'finance',
                    element: emptyDiscountInput,
                });
            }
            if (!technoeconomicText(
                technoeconomicElements?.standaloneAssumptionNote?.value
            ).trim()) {
                addRequirement('review', {
                    path: 'evidence.assumption_note',
                    message: 'Provide the source or justification for these assumptions.',
                    section: 'review',
                    element: technoeconomicElements?.standaloneAssumptionNote,
                });
            }
            if (!technoeconomicElements?.standaloneAccept?.checked) {
                addRequirement('review', {
                    path: 'evidence.explicit_acceptance',
                    message: 'Confirm the required review acceptance.',
                    section: 'review',
                    element: technoeconomicElements?.standaloneAccept,
                });
            }
            const lifecycleRequired = technoeconomicSelectedContractVersion()
                === TECHNOECONOMIC_LIFECYCLE_CONTRACT_VERSION
                && technoeconomicLifecycleEntryMode === 'empty';
            if (lifecycleRequired) {
                const sectionRequirements = {
                    lifecycle: {
                        path: 'Lifecycle setup',
                        message: 'Apply the approved template or provide a complete custom lifecycle specification.',
                    },
                    reliability: {
                        path: 'paired_commercial.lifecycle.reliability_mode',
                        message: 'Apply or provide the reliability specification.',
                    },
                    value: {
                        path: 'paired_commercial.lifecycle.electricity_value',
                        message: 'Apply or provide the value specification.',
                    },
                };
                for (const [key, requirement] of Object.entries(sectionRequirements)) {
                    if (!issuesBySection[key].length) {
                        issuesBySection[key].push(requirement);
                        if (key === 'lifecycle') displayErrors.push(requirement);
                    }
                }
            }
            const actionableErrors = [];
            const seenErrorsByTarget = new Map();
            for (const originalError of displayErrors) {
                let error = technoeconomicBuilderNormalizeIssue(originalError);
                let target = technoeconomicBuilderIssueTarget(error);
                if (target.element === technoeconomicElements?.standaloneSourceSelect
                    && !technoeconomicElements.standaloneSourceSelect?.value) {
                    error = {
                        path: 'source_annual_job_id',
                        message: 'Select a completed, verified Annual Simulation.',
                    };
                    target = technoeconomicBuilderIssueTarget(error);
                }
                const targetKey = target.element || target.section;
                if (!seenErrorsByTarget.has(targetKey)) {
                    seenErrorsByTarget.set(targetKey, new Set());
                }
                const messageKey = `${technoeconomicText(error.path)}:${
                    technoeconomicText(error.message)}`;
                if (seenErrorsByTarget.get(targetKey).has(messageKey)) continue;
                seenErrorsByTarget.get(targetKey).add(messageKey);
                actionableErrors.push(error);
            }
            const active = TECHNOECONOMIC_BUILDER_SECTIONS[technoeconomicBuilderSectionIndex]
                || TECHNOECONOMIC_BUILDER_SECTIONS[0];
            const lifecycleContract = technoeconomicSelectedContractVersion()
                === TECHNOECONOMIC_LIFECYCLE_CONTRACT_VERSION;
            const v5Descriptions = {
                lifecycle: 'Review and edit the paired Solectria and SolarEdge cost stacks used by the v5 LCOE calculation.',
                reliability: 'Review the reliability treatment locked by the v5 paired-LCOE contract.',
                value: 'Review the LCOE value methodology locked by the v5 paired-LCOE contract.',
            };
            technoeconomicElements.builderSectionEyebrow.textContent =
                `Section ${technoeconomicBuilderSectionIndex + 1} of ${TECHNOECONOMIC_BUILDER_SECTIONS.length}`;
            technoeconomicElements.builderSectionHeading.textContent = active.label;
            technoeconomicElements.builderSectionDescription.textContent = !lifecycleContract
                && v5Descriptions[active.key] ? v5Descriptions[active.key] : active.description;
            technoeconomicElements.standaloneAssumptionsDialog.querySelectorAll(
                '[data-tea-builder-section]'
            ).forEach((group) => {
                let visible = technoeconomicText(group.dataset.teaBuilderSection)
                    .split(/\s+/).includes(active.key);
                if (group === technoeconomicElements.lifecycleInputGroup) {
                    visible = visible && lifecycleContract;
                }
                if (group === technoeconomicElements.legacyCostGroup) {
                    visible = visible && !lifecycleContract;
                }
                group.hidden = !visible;
            });
            technoeconomicElements.standaloneAssumptionsDialog.querySelectorAll(
                '[data-tea-builder-panel]'
            ).forEach((panel) => {
                panel.hidden = panel.dataset.teaBuilderPanel !== active.key;
            });
            technoeconomicElements.standaloneAssumptionsDialog.querySelectorAll(
                '[data-tea-builder-v5-section]'
            ).forEach((panel) => {
                panel.hidden = lifecycleContract
                    || panel.dataset.teaBuilderV5Section !== active.key;
            });
            const assumptionsTableRegion = technoeconomicElements.builderStage
                ?.querySelector?.('.tea-assumptions-table-region');
            if (assumptionsTableRegion) {
                assumptionsTableRegion.hidden = !lifecycleContract
                    && ['reliability', 'value'].includes(active.key);
            }
            technoeconomicElements.builderReview.hidden = active.key !== 'review';
            technoeconomicElements.builderSteps.querySelectorAll('[data-tea-builder-step]')
                .forEach((button) => {
                    const key = button.dataset.teaBuilderStep;
                    const state = technoeconomicBuilderSectionState(
                        key, issuesBySection, lifecycleContract, result
                    );
                    button.dataset.status = state;
                    button.toggleAttribute('aria-current', key === active.key);
                    if (key === active.key) button.setAttribute('aria-current', 'step');
                    const status = button.querySelector('small');
                    if (status) status.textContent = state[0].toUpperCase() + state.slice(1);
                });
            const targetValue = Number(technoeconomicElements.standaloneTargetCapacityInput?.value);
            technoeconomicElements.builderTarget.textContent = Number.isFinite(targetValue) && targetValue > 0
                ? `${technoeconomicFormatNumber(targetValue, 4)} MW` : 'Required';
            const projectLife = Number(technoeconomicElements.standaloneProjectLife?.value);
            technoeconomicElements.builderLife.textContent = Number.isSafeInteger(projectLife)
                && projectLife > 0 ? `${projectLife} years` : 'Required';
            const trials = Number(technoeconomicElements.standaloneRealizations?.value);
            technoeconomicElements.builderTrials.textContent = Number.isSafeInteger(trials)
                && trials >= 1 && trials <= 100000
                ? trials.toLocaleString('en-US') : 'Required';
            technoeconomicElements.builderContract.textContent =
                technoeconomicElements.calculationContract?.selectedOptions?.[0]?.textContent
                || technoeconomicSelectedContractVersion();
            const selectedSource = technoeconomicStandaloneSelectedSource();
            technoeconomicElements.builderSource.textContent = selectedSource
                ? `${selectedSource.source_annual_job_id} · ${
                    Array.isArray(selectedSource.eligible_years)
                        ? `${selectedSource.eligible_years.length} weather years`
                        : 'verified source'}`
                : 'Not selected';
            technoeconomicElements.builderCompletion.replaceChildren(...TECHNOECONOMIC_BUILDER_SECTIONS.map(
                ({key, label}) => {
                    const item = technoeconomicNode('li');
                    const state = technoeconomicBuilderSectionState(
                        key, issuesBySection, lifecycleContract, result
                    );
                    item.dataset.status = state;
                    item.append(
                        technoeconomicNode('span', {text: label}),
                        technoeconomicNode('span', {
                            text: state[0].toUpperCase() + state.slice(1),
                        })
                    );
                    return item;
                }
            ));
            technoeconomicElements.builderIssueCount.textContent = String(actionableErrors.length);
            technoeconomicElements.builderIssues.replaceChildren(...actionableErrors.map((error) => {
                const item = technoeconomicNode('li');
                const target = technoeconomicBuilderIssueTarget(error);
                const button = technoeconomicNode('button', {
                    type: 'button', text: technoeconomicBuilderIssueLabel(error),
                });
                button.dataset.issuePath = technoeconomicText(error.path);
                button.addEventListener('click', () => {
                    technoeconomicBuilderGoTo(target.section, {
                        focus: target.element,
                        reveal: target.reveal,
                    });
                });
                item.appendChild(button);
                return item;
            }));
            if (!actionableErrors.length) {
                technoeconomicElements.builderIssues.replaceChildren(
                    technoeconomicNode('li', {text: 'All current requirements are verified.'})
                );
            }
            technoeconomicBuilderRenderInlineErrors(actionableErrors);
            technoeconomicBuilderRenderReview(result);
            const remaining = actionableErrors.map((error) => technoeconomicBuilderIssueLabel(error));
            technoeconomicElements.builderFooterRequirements.dataset.state = actionableErrors.length
                ? 'blocked' : 'ready';
            technoeconomicElements.builderFooterRequirements.dataset.overflow =
                actionableErrors.length > 3 ? 'true' : 'false';
            const footerTitle = technoeconomicNode('strong', {
                text: actionableErrors.length
                    ? `Calculation blocked — ${remaining.length} remaining ${
                        remaining.length === 1 ? 'requirement' : 'requirements'}`
                    : 'Ready to review and calculate',
            });
            if (actionableErrors.length) {
                const footerList = technoeconomicNode('ul');
                for (const requirement of remaining) {
                    footerList.appendChild(technoeconomicNode('li', {text: requirement}));
                }
                technoeconomicElements.builderFooterRequirements.replaceChildren(
                    footerTitle, footerList
                );
            } else {
                technoeconomicElements.builderFooterRequirements.replaceChildren(
                    footerTitle,
                    technoeconomicNode('span', {
                        text: 'All required evidence and acceptance are present.',
                    })
                );
            }
            technoeconomicElements.builderBackButton.disabled = technoeconomicBuilderSectionIndex === 0;
            technoeconomicElements.builderContinueButton.hidden =
                technoeconomicBuilderSectionIndex === TECHNOECONOMIC_BUILDER_SECTIONS.length - 1;
            technoeconomicElements.standaloneAssumptionsReviewButton.hidden =
                technoeconomicBuilderSectionIndex !== TECHNOECONOMIC_BUILDER_SECTIONS.length - 1;
            technoeconomicElements.standaloneAssumptionsReviewButton.disabled = !result.valid;
            technoeconomicElements.standaloneAssumptionsReviewButton.textContent =
                'Review & calculate';
            return result;
        }

        function technoeconomicBuilderGoTo(section, options = {}) {
            const index = TECHNOECONOMIC_BUILDER_SECTIONS.findIndex(
                (candidate) => candidate.key === section
            );
            if (index < 0) return false;
            technoeconomicBuilderSectionIndex = index;
            technoeconomicBuilderUpdate();
            const focusTarget = options.focus || technoeconomicElements.builderStage;
            requestAnimationFrame(() => {
                if (options.reveal) options.reveal.open = true;
                const bodyScroller = technoeconomicElements.builderStage?.parentElement;
                if (bodyScroller) bodyScroller.scrollTop = 0;
                if (technoeconomicElements.builderStage) {
                    technoeconomicElements.builderStage.scrollTop = 0;
                }
                const activeStep = technoeconomicElements.builderSteps?.querySelector?.(
                    `[data-tea-builder-step="${section}"]`
                );
                activeStep?.scrollIntoView?.({block: 'nearest', inline: 'nearest'});
                if (focusTarget !== technoeconomicElements.builderStage) {
                    focusTarget?.scrollIntoView?.({block: 'center', inline: 'nearest'});
                }
                focusTarget?.focus?.({preventScroll: true});
            });
            return true;
        }

        function technoeconomicBuilderSaveDraft() {
            const saved = technoeconomicPersistDraft() && technoeconomicPersistStandaloneDraft();
            if (technoeconomicElements?.draftStatus) {
                technoeconomicElements.draftStatus.textContent = saved
                    ? 'Scenario Builder draft saved in this browser.'
                    : 'Draft could not be saved in this browser.';
            }
            if (technoeconomicElements?.liveStatus) {
                technoeconomicElements.liveStatus.textContent = saved
                    ? 'Scenario draft saved.' : 'Scenario draft could not be saved.';
            }
        }

        function technoeconomicOpenAssumptionsDialog(trigger) {
            const dialog = technoeconomicElements.standaloneAssumptionsDialog;
            if (!dialog) return false;
            if (!dialog.open) {
                technoeconomicAssumptionsTrigger = trigger?.focus
                    ? trigger
                    : technoeconomicElements.standaloneEditAssumptionsButton;
                technoeconomicAssumptionsReturnFocus = true;
                if (typeof dialog.showModal === 'function') dialog.showModal();
                else dialog.setAttribute('open', '');
            }
            technoeconomicBuilderUpdate();
            const active = TECHNOECONOMIC_BUILDER_SECTIONS[technoeconomicBuilderSectionIndex]?.key;
            const initialFocus = active === 'source'
                ? technoeconomicElements.standaloneSourceSelect
                : technoeconomicElements.builderStage;
            initialFocus?.focus?.({preventScroll: true});
            return true;
        }

        function technoeconomicCloseAssumptionsDialog(options = {}) {
            const dialog = technoeconomicElements.standaloneAssumptionsDialog;
            if (!dialog?.open) return false;
            technoeconomicAssumptionsReturnFocus = options.restoreFocus !== false;
            if (typeof dialog.close === 'function') dialog.close();
            else {
                dialog.removeAttribute('open');
                technoeconomicFinishAssumptionsClose();
            }
            return true;
        }

        function technoeconomicOpenConfirmation(event) {
            event?.preventDefault();
            const errorElement = technoeconomicElements.standaloneFormErrors
                || technoeconomicElements.formErrors;
            if (technoeconomicLifecycleRequestInFlight || technoeconomicSubmissionRequestInFlight) {
                technoeconomicRenderErrors(errorElement, [{
                    path: '',
                    message: 'Wait for the current technoeconomic job action to finish before reviewing another submission.',
                }]);
                errorElement?.focus();
                return;
            }
            if (['queued', 'running'].includes(technoeconomicJob?.state)) {
                technoeconomicRenderErrors(errorElement, [{
                    path: '',
                    message: 'Wait for or cancel the active technoeconomic job before queueing another.',
                }]);
                errorElement?.focus();
                return;
            }
            const serialized = technoeconomicSerializeCurrentRequest({
                sources: technoeconomicSources,
            });
            technoeconomicRenderErrors(errorElement, serialized.errors);
            if (!serialized.valid) {
                technoeconomicOpenAssumptionsDialog(event?.submitter);
                technoeconomicBuilderUpdate(serialized);
                const firstTarget = technoeconomicBuilderIssueTarget(serialized.errors[0]);
                technoeconomicBuilderGoTo(firstTarget.section, {focus: firstTarget.element});
                return;
            }
            const frozenPayload = technoeconomicDeepFreeze(
                JSON.parse(JSON.stringify(serialized.payload))
            );
            const source = technoeconomicSources.find(
                (item) => item.source_annual_job_id === frozenPayload.source_annual_job_id
            );
            const sourceSummary = technoeconomicDeepFreeze(
                technoeconomicConfirmationSource(source)
            );
            technoeconomicPendingSubmission = {
                payload: frozenPayload,
                draftRevision: technoeconomicDraftRevision,
                sourceSummary,
                evidenceCount: serialized.evidenceCount,
                provisionalEvidenceCount: serialized.provisionalEvidenceCount,
            };
            technoeconomicCloseAssumptionsDialog({restoreFocus: false});
            technoeconomicRenderConfirmation(serialized, sourceSummary);
            const dialog = technoeconomicElements.confirmDialog;
            if (dialog?.showModal) dialog.showModal();
            else dialog?.setAttribute('open', '');
        }

        function technoeconomicCloseConfirmation() {
            if (technoeconomicSubmissionRequestInFlight) return;
            const dialog = technoeconomicElements.confirmDialog;
            if (dialog?.open && dialog.close) dialog.close();
            else dialog?.removeAttribute('open');
            technoeconomicPendingSubmission = null;
        }

        function technoeconomicPersistActiveJobId(jobId) {
            technoeconomicActiveJobId = typeof jobId === 'string'
                && jobId.length <= 200
                && /^tea_[A-Za-z0-9._:-]+$/.test(jobId) ? jobId : null;
            if (typeof localStorage !== 'object') {
                if (technoeconomicElements?.draftStatus) {
                    technoeconomicElements.draftStatus.textContent =
                        'The active job recovery pointer was not saved because browser storage is unavailable.';
                }
                return false;
            }
            try {
                if (technoeconomicActiveJobId) localStorage.setItem(
                    TECHNOECONOMIC_ACTIVE_JOB_STORAGE_KEY, technoeconomicActiveJobId
                );
                else localStorage.removeItem(TECHNOECONOMIC_ACTIVE_JOB_STORAGE_KEY);
                return true;
            } catch (_error) {
                // Durable recovery still works through dashboard state when local storage is unavailable.
                if (technoeconomicElements?.draftStatus) {
                    technoeconomicElements.draftStatus.textContent =
                        'Could not save the active job recovery pointer. Keep this page open and record the job ID.';
                }
                return false;
            }
        }

        function technoeconomicLoadActiveJobId() {
            if (typeof localStorage !== 'object') return null;
            try {
                const value = localStorage.getItem(TECHNOECONOMIC_ACTIVE_JOB_STORAGE_KEY);
                return typeof value === 'string' && value.length <= 200
                    && /^tea_[A-Za-z0-9._:-]+$/.test(value)
                    ? value : null;
            } catch (_error) {
                return null;
            }
        }

        function technoeconomicNormalizeJob(value) {
            const job = technoeconomicPlainObject(value?.job || value);
            const jobId = typeof job.job_id === 'string' ? job.job_id : '';
            if (jobId.length > 200 || !/^tea_[A-Za-z0-9._:-]+$/.test(jobId)
                || job.workflow !== 'technoeconomic') {
                throw {
                    status: null, code: 'invalid_job_response', fields: [],
                    message: 'The service returned an invalid technoeconomic job projection.',
                };
            }
            return job;
        }

        function technoeconomicStateLabel(state) {
            return ({
                queued: 'Queued', running: 'Running', done: 'Completed', error: 'Error',
                cancelled: 'Cancelled', interrupted: 'Interrupted', reconnecting: 'Reconnecting',
            })[state] || 'Unknown';
        }

        function technoeconomicRenderJob(job, options = {}) {
            if (!job || !technoeconomicElements.jobPanel) return;
            const state = options.reconnecting ? 'reconnecting' : job.state;
            technoeconomicElements.jobPanel.hidden = false;
            technoeconomicElements.jobPanel.dataset.state = state;
            technoeconomicElements.jobState.textContent = technoeconomicStateLabel(state);
            const rawProgress = Number(job.progress);
            const progress = Number.isFinite(rawProgress) ? Math.max(0, Math.min(100, rawProgress)) : 0;
            technoeconomicElements.progress.value = progress;
            technoeconomicElements.progress.textContent = `${Math.round(progress)}%`;
            technoeconomicElements.progressValue.textContent = `${Math.round(progress)}%`;
            technoeconomicElements.progressStage.textContent = options.reconnecting
                ? options.message || 'Connection interrupted; retrying status without changing the job.'
                : job.stage || `Job is ${technoeconomicStateLabel(job.state).toLowerCase()}.`;
            const active = ['queued', 'running'].includes(job.state);
            const mutationInFlight = technoeconomicLifecycleRequestInFlight
                || technoeconomicSubmissionRequestInFlight;
            technoeconomicElements.cancelButton.hidden = !active;
            technoeconomicElements.cancelButton.disabled = mutationInFlight
                || job.cancel_requested === true;
            technoeconomicElements.cancelButton.textContent = job.cancel_requested
                ? 'Cancellation requested' : 'Cancel job';
            technoeconomicElements.retryButton.hidden = !TECHNOECONOMIC_RETRYABLE_STATES.has(job.state);
            technoeconomicElements.retryButton.disabled = mutationInFlight;
            technoeconomicElements.deleteButton.hidden = !technoeconomicIsTerminalState(job.state);
            technoeconomicElements.deleteButton.disabled = mutationInFlight;
            if (technoeconomicElements.submitButton) {
                technoeconomicElements.submitButton.disabled = mutationInFlight;
            }
            if (technoeconomicElements.standaloneSubmitButton) {
                technoeconomicElements.standaloneSubmitButton.disabled = mutationInFlight || active;
            }
            if (job.error) technoeconomicRenderApiError(
                technoeconomicElements.jobError,
                {code: 'job_failed', message: String(job.error), fields: []}
            );
            else technoeconomicRenderErrors(technoeconomicElements.jobError, []);
            if (job.state === 'done' && job.result) renderTechnoeconomicJobResult(job);
            else if (technoeconomicElements.results) technoeconomicElements.results.hidden = true;
        }

        function technoeconomicAdoptJob(value) {
            const job = technoeconomicNormalizeJob(value);
            technoeconomicJob = job;
            technoeconomicPersistActiveJobId(job.job_id);
            technoeconomicPollFailureCount = 0;
            technoeconomicRenderJob(job);
            if (technoeconomicElements.liveStatus) {
                technoeconomicElements.liveStatus.textContent = `Technoeconomic job ${job.job_id}: ${technoeconomicStateLabel(job.state)}.`;
            }
            if (typeof updateAgentContext === 'function') updateAgentContext();
            return job;
        }

        function invalidateTechnoeconomicStatusPoll() {
            technoeconomicStatusRequestRevision += 1;
            clearTimeout(technoeconomicStatusTimer);
            technoeconomicStatusTimer = null;
            if (technoeconomicStatusAbortController) technoeconomicStatusAbortController.abort();
            technoeconomicStatusAbortController = null;
        }

        function invalidateTechnoeconomicLifecycleRequest() {
            technoeconomicLifecycleRequestRevision += 1;
            technoeconomicLifecycleRequestInFlight = false;
            if (technoeconomicLifecycleAbortController) {
                technoeconomicLifecycleAbortController.abort();
            }
            technoeconomicLifecycleAbortController = null;
        }

        function invalidateTechnoeconomicSubmissionRequest() {
            technoeconomicSubmissionRequestRevision += 1;
            technoeconomicSubmissionRequestInFlight = false;
            if (technoeconomicSubmissionAbortController) {
                technoeconomicSubmissionAbortController.abort();
            }
            technoeconomicSubmissionAbortController = null;
            if (technoeconomicElements?.submitButton) {
                technoeconomicElements.submitButton.disabled = false;
            }
            if (technoeconomicElements?.standaloneSubmitButton) {
                technoeconomicElements.standaloneSubmitButton.disabled = false;
            }
            if (technoeconomicElements?.confirmSubmitButton) {
                technoeconomicElements.confirmSubmitButton.disabled = false;
                technoeconomicElements.confirmSubmitButton.textContent = 'Confirm and queue';
            }
            if (technoeconomicElements?.confirmCancelButton) {
                technoeconomicElements.confirmCancelButton.disabled = false;
            }
            if (technoeconomicElements?.confirmCloseButton) {
                technoeconomicElements.confirmCloseButton.disabled = false;
            }
        }

        function technoeconomicScheduleStatusPoll(jobId, revision, delay) {
            clearTimeout(technoeconomicStatusTimer);
            technoeconomicStatusTimer = setTimeout(() => {
                if (revision === technoeconomicStatusRequestRevision
                    && jobId === technoeconomicActiveJobId) {
                    technoeconomicPollJob(jobId, revision);
                }
            }, delay);
        }

        async function technoeconomicPollJob(jobId, revision = technoeconomicStatusRequestRevision) {
            if (!jobId || revision !== technoeconomicStatusRequestRevision) return null;
            if (technoeconomicStatusAbortController) technoeconomicStatusAbortController.abort();
            technoeconomicStatusAbortController = new AbortController();
            try {
                const body = await technoeconomicFetchJson(
                    `/api/technoeconomic/jobs/${encodeURIComponent(jobId)}`,
                    {signal: technoeconomicStatusAbortController.signal}
                );
                if (revision !== technoeconomicStatusRequestRevision
                    || jobId !== technoeconomicActiveJobId) return null;
                const job = technoeconomicAdoptJob(body);
                if (!technoeconomicIsTerminalState(job.state)) {
                    const delay = job.state === 'queued' ? 1500 : 1000;
                    technoeconomicScheduleStatusPoll(jobId, revision, delay);
                }
                return job;
            } catch (error) {
                if (revision !== technoeconomicStatusRequestRevision
                    || jobId !== technoeconomicActiveJobId || error.code === 'request_aborted') return null;
                if (error.status === 404) {
                    invalidateTechnoeconomicStatusPoll();
                    technoeconomicJob = null;
                    technoeconomicPersistActiveJobId(null);
                    technoeconomicClearResults();
                    if (technoeconomicElements.jobPanel) {
                        technoeconomicElements.jobPanel.hidden = false;
                        technoeconomicElements.jobPanel.dataset.state = 'missing';
                    }
                    if (technoeconomicElements.jobState) {
                        technoeconomicElements.jobState.textContent = 'Unavailable';
                    }
                    if (technoeconomicElements.progress) technoeconomicElements.progress.value = 0;
                    if (technoeconomicElements.progressValue) {
                        technoeconomicElements.progressValue.textContent = '0%';
                    }
                    if (technoeconomicElements.progressStage) {
                        technoeconomicElements.progressStage.textContent =
                            `Durable job ${jobId} could not be restored. The draft remains available.`;
                    }
                    for (const button of [
                        technoeconomicElements.cancelButton,
                        technoeconomicElements.retryButton,
                        technoeconomicElements.deleteButton,
                    ]) if (button) button.hidden = true;
                    technoeconomicRenderApiError(technoeconomicElements.jobError, error);
                    technoeconomicElements.jobError?.focus();
                    if (technoeconomicElements.liveStatus) {
                        technoeconomicElements.liveStatus.textContent =
                            `Technoeconomic job ${jobId} is unavailable; the local draft was preserved.`;
                    }
                    if (typeof updateAgentContext === 'function') updateAgentContext();
                    return null;
                }
                technoeconomicPollFailureCount += 1;
                if (technoeconomicJob) technoeconomicRenderJob(technoeconomicJob, {
                    reconnecting: true,
                    message: `${error.message} Retrying without changing the server job.`,
                });
                const delay = Math.min(10000, 1000 * (2 ** Math.min(technoeconomicPollFailureCount, 4)));
                technoeconomicScheduleStatusPoll(jobId, revision, delay);
                return null;
            }
        }

        async function restoreTechnoeconomicActiveJob(jobId = null) {
            const candidate = jobId || technoeconomicActiveJobId || technoeconomicLoadActiveJobId();
            if (!candidate || candidate.length > 200
                || !/^tea_[A-Za-z0-9._:-]+$/.test(candidate)) return null;
            invalidateTechnoeconomicStatusPoll();
            technoeconomicPersistActiveJobId(candidate);
            const revision = technoeconomicStatusRequestRevision;
            if (technoeconomicElements.jobPanel) technoeconomicElements.jobPanel.hidden = false;
            if (technoeconomicElements.jobState) technoeconomicElements.jobState.textContent = 'Reconnecting';
            if (technoeconomicElements.progressStage) {
                technoeconomicElements.progressStage.textContent = 'Restoring the durable server job.';
            }
            return technoeconomicPollJob(candidate, revision);
        }

        async function reconnectTechnoeconomicWorkspace() {
            if (typeof document !== 'object' || !technoeconomicElements?.form) return null;
            const [, job] = await Promise.all([
                refreshTechnoeconomicSources(),
                restoreTechnoeconomicActiveJob(),
            ]);
            return job;
        }

        async function technoeconomicConfirmSubmission() {
            const pending = technoeconomicPendingSubmission;
            if (!pending) return;
            if (technoeconomicLifecycleRequestInFlight || technoeconomicSubmissionRequestInFlight) {
                technoeconomicRenderApiError(technoeconomicElements.confirmError, {
                    code: 'job_action_in_progress', fields: [],
                    message: 'Wait for the current technoeconomic job action to finish before queueing another job.',
                });
                return;
            }
            if (pending.draftRevision !== technoeconomicDraftRevision) {
                technoeconomicRenderApiError(technoeconomicElements.confirmError, {
                    code: 'draft_changed', fields: [],
                    message: 'The draft changed after this confirmation was prepared. Go back and review the updated request.',
                });
                return;
            }
            const revision = ++technoeconomicSubmissionRequestRevision;
            const priorActiveJobId = technoeconomicActiveJobId;
            technoeconomicSubmissionRequestInFlight = true;
            technoeconomicSubmissionAbortController = new AbortController();
            technoeconomicElements.confirmSubmitButton.disabled = true;
            technoeconomicElements.confirmSubmitButton.textContent = 'Queueing...';
            if (technoeconomicElements.confirmCancelButton) {
                technoeconomicElements.confirmCancelButton.disabled = true;
            }
            if (technoeconomicElements.confirmCloseButton) {
                technoeconomicElements.confirmCloseButton.disabled = true;
            }
            if (technoeconomicElements.submitButton) {
                technoeconomicElements.submitButton.disabled = true;
            }
            if (technoeconomicElements.standaloneSubmitButton) {
                technoeconomicElements.standaloneSubmitButton.disabled = true;
            }
            if (technoeconomicJob) technoeconomicRenderJob(technoeconomicJob);
            try {
                const body = await technoeconomicFetchJson('/api/technoeconomic/jobs', {
                    method: 'POST', body: pending.payload,
                    signal: technoeconomicSubmissionAbortController.signal,
                });
                if (revision !== technoeconomicSubmissionRequestRevision
                    || pending !== technoeconomicPendingSubmission
                    || priorActiveJobId !== technoeconomicActiveJobId) return;
                const job = technoeconomicAdoptJob(body);
                const dialog = technoeconomicElements.confirmDialog;
                if (dialog?.open && dialog.close) dialog.close();
                else dialog?.removeAttribute('open');
                technoeconomicPendingSubmission = null;
                technoeconomicDraftRevision += 1;
                technoeconomicPersistDraft();
                invalidateTechnoeconomicStatusPoll();
                const statusRevision = technoeconomicStatusRequestRevision;
                if (!technoeconomicIsTerminalState(job.state)) {
                    technoeconomicScheduleStatusPoll(job.job_id, statusRevision, 600);
                }
            } catch (error) {
                if (revision !== technoeconomicSubmissionRequestRevision
                    || error.code === 'request_aborted') return;
                technoeconomicRenderApiError(technoeconomicElements.confirmError, error);
                technoeconomicElements.confirmError?.focus();
            } finally {
                if (revision === technoeconomicSubmissionRequestRevision) {
                    technoeconomicSubmissionRequestInFlight = false;
                    technoeconomicSubmissionAbortController = null;
                    technoeconomicElements.confirmSubmitButton.disabled = false;
                    technoeconomicElements.confirmSubmitButton.textContent = 'Confirm and queue';
                    if (technoeconomicElements.confirmCancelButton) {
                        technoeconomicElements.confirmCancelButton.disabled = false;
                    }
                    if (technoeconomicElements.confirmCloseButton) {
                        technoeconomicElements.confirmCloseButton.disabled = false;
                    }
                    if (technoeconomicElements.submitButton) {
                        technoeconomicElements.submitButton.disabled = false;
                    }
                    if (technoeconomicElements.standaloneSubmitButton) {
                        technoeconomicElements.standaloneSubmitButton.disabled = false;
                    }
                    if (technoeconomicJob) technoeconomicRenderJob(technoeconomicJob);
                }
            }
        }

        async function technoeconomicLifecycleRequest(action, method = 'POST') {
            const jobId = technoeconomicActiveJobId;
            if (!jobId || technoeconomicLifecycleRequestInFlight
                || technoeconomicSubmissionRequestInFlight || technoeconomicPendingSubmission) {
                return null;
            }
            const suffix = action ? `/${action}` : '';
            const revision = ++technoeconomicLifecycleRequestRevision;
            let displayedError = null;
            technoeconomicLifecycleRequestInFlight = true;
            technoeconomicLifecycleAbortController = new AbortController();
            if (technoeconomicJob) technoeconomicRenderJob(technoeconomicJob);
            try {
                const body = await technoeconomicFetchJson(
                    `/api/technoeconomic/jobs/${encodeURIComponent(jobId)}${suffix}`,
                    {method, signal: technoeconomicLifecycleAbortController.signal}
                );
                if (revision !== technoeconomicLifecycleRequestRevision
                    || jobId !== technoeconomicActiveJobId) return null;
                if (method === 'DELETE') return body;
                return technoeconomicAdoptJob(body);
            } catch (error) {
                if (revision !== technoeconomicLifecycleRequestRevision
                    || jobId !== technoeconomicActiveJobId || error.code === 'request_aborted') {
                    return null;
                }
                displayedError = error;
                return null;
            } finally {
                if (revision === technoeconomicLifecycleRequestRevision) {
                    technoeconomicLifecycleRequestInFlight = false;
                    technoeconomicLifecycleAbortController = null;
                    if (technoeconomicJob) technoeconomicRenderJob(technoeconomicJob);
                    if (displayedError) {
                        technoeconomicRenderApiError(technoeconomicElements.jobError, displayedError);
                        technoeconomicElements.jobError?.focus();
                    }
                }
            }
        }

        async function technoeconomicCancelJob() {
            const job = await technoeconomicLifecycleRequest('cancel');
            if (job && !technoeconomicIsTerminalState(job.state)) {
                invalidateTechnoeconomicStatusPoll();
                technoeconomicScheduleStatusPoll(job.job_id, technoeconomicStatusRequestRevision, 600);
            }
        }

        async function technoeconomicRetryJob() {
            const job = await technoeconomicLifecycleRequest('retry');
            if (job) {
                invalidateTechnoeconomicStatusPoll();
                technoeconomicScheduleStatusPoll(job.job_id, technoeconomicStatusRequestRevision, 600);
            }
        }

        async function technoeconomicDeleteJob() {
            if (!technoeconomicActiveJobId) return;
            if (typeof window === 'object' && !window.confirm(
                'Delete this terminal technoeconomic job and its confined artifacts? This cannot be undone.'
            )) return;
            const deleted = await technoeconomicLifecycleRequest('', 'DELETE');
            if (deleted?.deleted === true) {
                invalidateTechnoeconomicWorkspace({preserveDraft: true});
                if (technoeconomicElements.liveStatus) {
                    technoeconomicElements.liveStatus.textContent = 'Technoeconomic job deleted.';
                }
            }
        }

        function technoeconomicMetricUnit(metricName) {
            if (metricName === 'CommercialTargetCapacity_W') return 'W';
            if (metricName.includes('LCOE') || metricName.includes('LCOO')
                || metricName.includes('lcoo')) return 'USD/kWh AC';
            if (metricName.startsWith('CommercialEquivalentAnnual')
                && metricName.includes('Cost')) return 'USD/year';
            if (metricName.startsWith('Commercial') && metricName.includes('Cost')) return 'USD';
            if (metricName.startsWith('CommercialEquivalentAnnual')
                && metricName.includes('Energy')) return 'kWh AC/year';
            if (metricName.startsWith('Commercial') && metricName.includes('Energy')) return 'kWh AC';
            const applied = metricName.includes('per_applied_W')
                || metricName.includes('PerAppliedW');
            if (applied && metricName.includes('AnnualCost')) return 'USD/applied W-year';
            if (applied && metricName.includes('Cost')) return 'USD/applied W';
            if (applied && metricName.includes('AnnualEnergy')) return 'kWh AC/applied W-year';
            if (applied && metricName.includes('Energy')) return 'kWh AC/applied W';
            if (metricName.includes('AnnualCost')) return 'USD/Wdc-year';
            if (metricName.includes('Cost')) return 'USD/Wdc';
            if (metricName.includes('AnnualEnergy')) return 'kWh AC/Wdc-year';
            if (metricName.includes('Energy')) return 'kWh AC/Wdc';
            return '';
        }

        function technoeconomicFormatMetric(metricName, value) {
            if (value === null || value === undefined || value === '') return 'Unavailable';
            const number = Number(value);
            if (!Number.isFinite(number)) return 'Unavailable';
            const digits = metricName.includes('LCOE') || metricName.includes('lcoo') ? 5 : 4;
            const rendered = number.toLocaleString('en-US', {maximumFractionDigits: digits});
            const unit = technoeconomicMetricUnit(metricName);
            return unit ? `${rendered} ${unit}` : rendered;
        }

        function technoeconomicFormatPercent(value) {
            if (value === null || value === undefined || value === '') return 'Unavailable';
            const number = Number(value);
            return Number.isFinite(number)
                ? number.toLocaleString('en-US', {style: 'percent', maximumFractionDigits: 2})
                : 'Unavailable';
        }

        function technoeconomicHumanize(value) {
            return String(value || 'unavailable').replaceAll('_', ' ');
        }

        function technoeconomicMetricCard(metricName, summary) {
            const card = technoeconomicNode('article', {className: 'tea-metric-card'});
            const commercialLabel = TECHNOECONOMIC_COMMERCIAL_METRICS.find(
                ([name]) => name === metricName
            )?.[1];
            card.appendChild(technoeconomicNode('h4', {
                text: TECHNOECONOMIC_METRIC_LABELS[metricName]
                    || commercialLabel || technoeconomicHumanize(metricName),
            }));
            const value = technoeconomicPlainObject(summary);
            if (value.status !== 'available') {
                card.appendChild(technoeconomicNode('p', {
                    className: 'tea-unavailable',
                    text: `Unavailable: ${technoeconomicHumanize(value.reason)}`,
                }));
                return card;
            }
            const percentiles = technoeconomicPlainObject(value.percentiles);
            const list = technoeconomicNode('dl', {className: 'tea-percentile-list'});
            for (const quantile of ['p5', 'p50', 'p95']) {
                technoeconomicDefinition(
                    list, quantile.toUpperCase(),
                    technoeconomicFormatMetric(metricName, percentiles[quantile])
                );
            }
            technoeconomicDefinition(list, 'Population', technoeconomicFormatNumber(value.count, 0));
            card.appendChild(list);
            return card;
        }

        function technoeconomicRenderMetrics(result) {
            const root = technoeconomicElements.metricSummary;
            if (!root) return;
            root.replaceChildren();
            const summaries = technoeconomicPlainObject(result.summaries);
            for (const metricName of Object.keys(TECHNOECONOMIC_METRIC_LABELS)) {
                if (Object.prototype.hasOwnProperty.call(summaries, metricName)) {
                    root.appendChild(technoeconomicMetricCard(metricName, summaries[metricName]));
                }
            }
        }

        function technoeconomicCommercialMetricSummary(result, metricName) {
            const summaries = technoeconomicPlainObject(result.summaries);
            const candidates = [
                metricName,
                ...(TECHNOECONOMIC_COMMERCIAL_METRIC_ALIASES[metricName] || []),
            ];
            for (const candidate of candidates) {
                if (Object.prototype.hasOwnProperty.call(summaries, candidate)) {
                    return technoeconomicPlainObject(summaries[candidate]);
                }
            }
            let directValue = null;
            for (const candidate of candidates) {
                if (Object.prototype.hasOwnProperty.call(result, candidate)) {
                    directValue = result[candidate];
                    break;
                }
            }
            if (metricName === 'CommercialTargetCapacity_W'
                && (directValue === null || directValue === undefined)) {
                directValue = technoeconomicPlainObject(result.commercial_scaling).target_capacity_w;
            }
            const number = directValue === null || directValue === undefined || directValue === ''
                ? NaN : Number(directValue);
            if (Number.isFinite(number)) {
                return {
                    status: 'available', count: Number(result.realization_count) || 1,
                    percentiles: {p5: number, p50: number, p95: number},
                };
            }
            const scaling = technoeconomicPlainObject(result.commercial_scaling);
            return {
                status: 'unavailable', count: 0,
                reason: result.commercial_marginal_lcoo_unavailable_reason
                    || scaling.unavailable_reason || 'commercial_scaling_result_unavailable',
                percentiles: {p5: null, p50: null, p95: null},
            };
        }

        function technoeconomicRenderCommercialScaling(result) {
            const section = technoeconomicDomElement('technoeconomicCommercialResults');
            const root = technoeconomicDomElement('technoeconomicCommercialResultMetrics');
            const status = technoeconomicDomElement('technoeconomicCommercialResultStatus');
            if (!section || !root) return;
            const summaries = technoeconomicPlainObject(result.summaries);
            const scaling = technoeconomicPlainObject(result.commercial_scaling);
            const requested = Object.keys(scaling).length > 0
                || TECHNOECONOMIC_COMMERCIAL_METRICS.some(([metricName]) => [
                    metricName,
                    ...(TECHNOECONOMIC_COMMERCIAL_METRIC_ALIASES[metricName] || []),
                ].some((candidate) => Object.prototype.hasOwnProperty.call(summaries, candidate)
                    || Object.prototype.hasOwnProperty.call(result, candidate)));
            root.replaceChildren();
            section.hidden = !requested;
            if (!requested) {
                if (status) {
                    status.textContent = '';
                    delete status.dataset.state;
                }
                return;
            }
            const rendered = new Map();
            for (const [metricName] of TECHNOECONOMIC_COMMERCIAL_METRICS) {
                const summary = technoeconomicCommercialMetricSummary(result, metricName);
                rendered.set(metricName, summary);
                root.appendChild(technoeconomicMetricCard(metricName, summary));
            }
            if (status) {
                const marginal = technoeconomicPlainObject(rendered.get(
                    'CommercialMarginalLCOO_se_minus_sol_USD_per_kWh_AC'
                ));
                const unavailable = marginal.status !== 'available';
                status.dataset.state = unavailable ? 'unavailable' : 'available';
                status.textContent = unavailable
                    ? `Commercial marginal LCOO unavailable: ${technoeconomicHumanize(
                        marginal.reason
                    )}. The target, energy, and cost fields retain their completed server evidence.`
                    : `Commercial marginal LCOO is available using ${technoeconomicHumanize(
                        scaling.marginal_cost_timing
                    )} cost timing and the ${technoeconomicRatingBasisLabel(
                        scaling.target_rating_basis
                    )} capacity basis.`;
            }
        }

        function technoeconomicTradeoffCard(label, key, group) {
            const card = technoeconomicNode('article', {className: 'tea-tradeoff-card'});
            card.appendChild(technoeconomicNode('h4', {text: label}));
            if (group.status === 'unavailable') {
                card.appendChild(technoeconomicNode('p', {
                    text: `Unavailable: ${technoeconomicHumanize(group.reason)}`,
                }));
                return card;
            }
            const probability = technoeconomicPlainObject(group.probabilities)[key];
            const count = technoeconomicPlainObject(group.counts)[key];
            card.append(
                technoeconomicNode('strong', {text: technoeconomicFormatPercent(probability)}),
                technoeconomicNode('p', {
                    text: `${technoeconomicFormatNumber(count, 0)} of ${technoeconomicFormatNumber(group.denominator, 0)} realizations`,
                })
            );
            return card;
        }

        function technoeconomicRenderTradeoffs(result) {
            const root = technoeconomicElements.tradeoffs;
            if (!root) return;
            root.replaceChildren();
            const summaries = technoeconomicPlainObject(result.summaries);
            const energy = technoeconomicPlainObject(summaries.energy_classes);
            const tradeoffs = technoeconomicPlainObject(summaries.tradeoff_classes);
            for (const [key, label] of [
                ['positive_lifecycle_gain', 'Positive lifecycle energy gain'],
                ['zero_lifecycle_gain', 'Within-tolerance lifecycle energy change'],
                ['negative_lifecycle_gain', 'Lifecycle energy loss'],
            ]) root.appendChild(technoeconomicTradeoffCard(label, key, energy));
            for (const key of [
                'cost_increase_energy_gain', 'cost_neutral_energy_gain', 'cost_saving_energy_gain',
                'cost_increase_energy_loss', 'cost_neutral_energy_loss', 'cost_saving_energy_loss',
                'cost_increase_zero_energy_change', 'cost_neutral_zero_energy_change',
                'cost_saving_zero_energy_change',
            ]) {
                root.appendChild(technoeconomicTradeoffCard(
                    technoeconomicTradeoffLabel(key), key, tradeoffs
                ));
            }
        }

        function technoeconomicTableCell(row, value) {
            row.appendChild(technoeconomicNode('td', {text: value}));
        }

        function technoeconomicMetricP50(metrics, key) {
            const metric = technoeconomicPlainObject(technoeconomicPlainObject(metrics)[key]);
            return metric.status === 'available'
                ? technoeconomicFormatMetric(key, technoeconomicPlainObject(metric.percentiles).p50)
                : `Unavailable: ${technoeconomicHumanize(metric.reason)}`;
        }

        function technoeconomicRenderPerYear(result) {
            const body = technoeconomicElements.perYearBody;
            if (!body) return;
            body.replaceChildren();
            for (const item of Array.isArray(result.per_weather_year) ? result.per_weather_year : []) {
                const applied = Object.prototype.hasOwnProperty.call(
                    item, 'source_sol_specific_kwh_ac_per_applied_w_year'
                );
                const solSpecific = applied
                    ? item.source_sol_specific_kwh_ac_per_applied_w_year
                    : item.source_sol_specific_kwh_ac_per_wdc_year;
                const seSpecific = applied
                    ? item.source_se_specific_kwh_ac_per_applied_w_year
                    : item.source_se_specific_kwh_ac_per_wdc_year;
                const capacityUnit = applied ? 'applied W' : 'Wdc';
                const costMetric = applied
                    ? 'DeltaLifecycleCostPerAppliedW_se_minus_sol_USD_per_applied_W'
                    : 'DeltaLifecycleCostPerWdc_se_minus_sol_USD_per_Wdc';
                const energyMetric = applied
                    ? 'DeltaLifecycleEnergyPerAppliedW_se_minus_sol_kWh_AC_per_applied_W'
                    : 'DeltaLifecycleEnergyPerWdc_se_minus_sol_kWh_AC_per_Wdc';
                const row = technoeconomicNode('tr');
                technoeconomicTableCell(row, String(item.year ?? 'Unavailable'));
                technoeconomicTableCell(row, technoeconomicFormatNumber(item.realization_count, 0));
                technoeconomicTableCell(row, technoeconomicFormatPercent(item.realization_share));
                technoeconomicTableCell(row,
                    `${technoeconomicFormatNumber(solSpecific, 4)} kWh AC/${capacityUnit}-year`);
                technoeconomicTableCell(row,
                    `${technoeconomicFormatNumber(seSpecific, 4)} kWh AC/${capacityUnit}-year`);
                technoeconomicTableCell(row, technoeconomicMetricP50(item.metrics, costMetric));
                technoeconomicTableCell(row, technoeconomicMetricP50(item.metrics, energyMetric));
                technoeconomicTableCell(row, technoeconomicMetricP50(
                    item.metrics, 'headline_positive_gain_lcoo'
                ));
                body.appendChild(row);
            }
        }

        function technoeconomicRenderSensitivity(result) {
            const body = technoeconomicElements.sensitivityBody;
            if (!body) return;
            body.replaceChildren();
            const sensitivity = technoeconomicPlainObject(result.sensitivity);
            for (const [responseName, rawModel] of Object.entries(sensitivity)) {
                const model = technoeconomicPlainObject(rawModel);
                const label = TECHNOECONOMIC_SENSITIVITY_LABELS[responseName]
                    || technoeconomicHumanize(responseName);
                const steps = Array.isArray(model.steps) ? model.steps : [];
                if (model.status !== 'available' || !steps.length) {
                    const row = technoeconomicNode('tr');
                    technoeconomicTableCell(row, label);
                    technoeconomicTableCell(row, model.status !== 'available'
                        ? `Unavailable: ${technoeconomicHumanize(model.reason)}`
                        : 'No predictor met the entry threshold');
                    for (let index = 0; index < 4; index += 1) technoeconomicTableCell(row, '');
                    body.appendChild(row);
                } else {
                    for (const step of steps) {
                        const row = technoeconomicNode('tr');
                        technoeconomicTableCell(row, label);
                        technoeconomicTableCell(row, step.predictor_id || 'Unavailable');
                        technoeconomicTableCell(row, technoeconomicFormatNumber(step.entry_order, 0));
                        technoeconomicTableCell(row, technoeconomicFormatNumber(step.incremental_r_squared, 5));
                        technoeconomicTableCell(row, technoeconomicFormatNumber(step.standardized_beta, 5));
                        technoeconomicTableCell(row, technoeconomicHumanize(step.sign));
                        body.appendChild(row);
                    }
                }
                for (const [predictor, rawExclusion] of Object.entries(
                    technoeconomicPlainObject(model.exclusions)
                )) {
                    const exclusion = typeof rawExclusion === 'string'
                        ? rawExclusion : technoeconomicPlainObject(rawExclusion).reason;
                    const row = technoeconomicNode('tr');
                    technoeconomicTableCell(row, label);
                    technoeconomicTableCell(row,
                        `${predictor}: excluded (${technoeconomicHumanize(exclusion)})`);
                    for (let index = 0; index < 4; index += 1) technoeconomicTableCell(row, '');
                    body.appendChild(row);
                }
            }
        }

        function technoeconomicConvergenceChange(metric) {
            const changes = technoeconomicPlainObject(metric.change_from_previous);
            const p50 = technoeconomicPlainObject(changes.p50);
            if (p50.relative !== null && p50.relative !== undefined) {
                return `P50 relative ${technoeconomicFormatPercent(p50.relative)}`;
            }
            if (p50.absolute !== null && p50.absolute !== undefined) {
                return `P50 absolute ${technoeconomicFormatNumber(p50.absolute, 6)}`;
            }
            return 'First checkpoint';
        }

        function technoeconomicRenderConvergence(result) {
            const convergence = technoeconomicPlainObject(result.convergence);
            if (technoeconomicElements.convergenceStatus) {
                const stable = convergence.status === 'stable';
                const reasons = Array.isArray(convergence.reasons) ? convergence.reasons : [];
                technoeconomicElements.convergenceStatus.dataset.state = stable ? 'stable' : 'not-demonstrated';
                technoeconomicElements.convergenceStatus.textContent = stable
                    ? 'Checkpoint stability demonstrated under the server contract. This is diagnostic evidence, not a mathematical guarantee.'
                    : `Checkpoint stability not demonstrated${reasons.length
                        ? `: ${reasons.map(technoeconomicHumanize).join('; ')}` : '.'}`;
            }
            const body = technoeconomicElements.convergenceBody;
            if (!body) return;
            body.replaceChildren();
            for (const checkpoint of Array.isArray(convergence.checkpoints)
                ? convergence.checkpoints : []) {
                for (const [metricName, rawMetric] of Object.entries(
                    technoeconomicPlainObject(checkpoint.metrics)
                )) {
                    const metric = technoeconomicPlainObject(rawMetric);
                    const percentiles = technoeconomicPlainObject(metric.percentiles);
                    const row = technoeconomicNode('tr');
                    technoeconomicTableCell(row, technoeconomicFormatNumber(
                        checkpoint.realization_count, 0
                    ));
                    technoeconomicTableCell(row,
                        TECHNOECONOMIC_METRIC_LABELS[metricName] || technoeconomicHumanize(metricName));
                    technoeconomicTableCell(row, technoeconomicFormatMetric(metricName, percentiles.p5));
                    technoeconomicTableCell(row, technoeconomicFormatMetric(metricName, percentiles.p50));
                    technoeconomicTableCell(row, technoeconomicFormatMetric(metricName, percentiles.p95));
                    technoeconomicTableCell(row, technoeconomicConvergenceChange(metric));
                    body.appendChild(row);
                }
            }
        }

        function technoeconomicDecisionMetric(summaries, metricNames) {
            for (const metricName of metricNames) {
                const summary = technoeconomicPlainObject(summaries[metricName]);
                if (summary.status === 'available') return {metricName, summary};
            }
            return {metricName: metricNames[0], summary: {}};
        }

        function technoeconomicProbabilityTotal(probabilities, keys) {
            let total = 0;
            let available = false;
            for (const key of keys) {
                const rawValue = probabilities[key];
                if (rawValue === null || rawValue === undefined || rawValue === '') continue;
                const value = Number(rawValue);
                if (Number.isFinite(value)) {
                    total += value;
                    available = true;
                }
            }
            return available ? total : null;
        }

        function technoeconomicRenderDecision(result) {
            const summaries = technoeconomicPlainObject(result.summaries);
            const cost = technoeconomicDecisionMetric(summaries, [
                'DeltaLifecycleCostPerAppliedW_se_minus_sol_USD_per_applied_W',
                'DeltaLifecycleCostPerWdc_se_minus_sol_USD_per_Wdc',
            ]);
            const energy = technoeconomicDecisionMetric(summaries, [
                'DeltaLifecycleEnergyPerAppliedW_se_minus_sol_kWh_AC_per_applied_W',
                'DeltaLifecycleEnergyPerWdc_se_minus_sol_kWh_AC_per_Wdc',
            ]);
            const costPercentiles = technoeconomicPlainObject(cost.summary.percentiles);
            const energyPercentiles = technoeconomicPlainObject(energy.summary.percentiles);
            const costP50 = costPercentiles.p50 === null || costPercentiles.p50 === undefined
                || costPercentiles.p50 === '' ? NaN : Number(costPercentiles.p50);
            const energyP50 = energyPercentiles.p50 === null || energyPercentiles.p50 === undefined
                || energyPercentiles.p50 === '' ? NaN : Number(energyPercentiles.p50);
            const hasMedians = cost.summary.status === 'available'
                && energy.summary.status === 'available'
                && Number.isFinite(costP50) && Number.isFinite(energyP50);

            let state = 'tradeoff';
            let heading = 'No decisive median advantage';
            let explanation = 'The completed result does not support a single-system decision from cost and energy together.';
            if (hasMedians && costP50 < 0 && energyP50 > 0) {
                state = 'solaredge';
                heading = 'SolarEdge has the stronger median outcome';
                explanation = 'At P50, SolarEdge has lower lifecycle cost and higher lifecycle AC energy than Solectria.';
            } else if (hasMedians && costP50 > 0 && energyP50 < 0) {
                state = 'solectria';
                heading = 'Solectria has the stronger median outcome';
                explanation = 'At P50, Solectria has lower lifecycle cost and higher lifecycle AC energy than SolarEdge.';
            } else if (hasMedians) {
                heading = 'The median result is a cost–energy trade-off';
                explanation = costP50 >= 0 && energyP50 >= 0
                    ? 'At P50, SolarEdge produces more lifecycle energy but also costs more.'
                    : 'At P50, SolarEdge costs less but also produces less lifecycle energy.';
            }

            const finitePercentile = (value) => value === null || value === undefined
                || value === '' || !Number.isFinite(Number(value)) ? null : Number(value);
            const costP5 = finitePercentile(costPercentiles.p5);
            const costP95 = finitePercentile(costPercentiles.p95);
            const energyP5 = finitePercentile(energyPercentiles.p5);
            const energyP95 = finitePercentile(energyPercentiles.p95);
            const stable = result.convergence?.status === 'stable';
            const rangeSupportsDecision = state === 'solaredge'
                ? costP95 !== null && energyP5 !== null && costP95 < 0 && energyP5 > 0
                : state === 'solectria' && costP5 !== null && energyP95 !== null
                    ? costP5 > 0 && energyP95 < 0 : false;
            const confidence = rangeSupportsDecision && stable ? 'Strong'
                : stable ? 'Mixed' : 'Provisional';
            const caveat = state === 'tradeoff'
                ? 'Choose only after deciding how much additional lifecycle energy is worth relative to lifecycle cost.'
                : rangeSupportsDecision
                    ? 'The P5–P95 ranges support the same direction as the median result.'
                    : 'The P5–P95 ranges overlap a decision boundary, so the median result is not decisive in every realization.';

            if (technoeconomicElements.decision) {
                technoeconomicElements.decision.dataset.decision = state;
            }
            if (technoeconomicElements.decisionHeading) {
                technoeconomicElements.decisionHeading.textContent = heading;
            }
            if (technoeconomicElements.decisionText) {
                technoeconomicElements.decisionText.textContent = explanation;
            }
            if (technoeconomicElements.decisionCaveat) {
                technoeconomicElements.decisionCaveat.textContent = `${confidence} decision confidence. ${caveat}`;
            }

            const tradeoffs = technoeconomicPlainObject(summaries.tradeoff_classes);
            const probabilities = technoeconomicPlainObject(tradeoffs.probabilities);
            const solarEdgeAdvantage = technoeconomicProbabilityTotal(probabilities, [
                'cost_saving_energy_gain', 'cost_neutral_energy_gain',
                'cost_saving_zero_energy_change',
            ]);
            const solectriaAdvantage = technoeconomicProbabilityTotal(probabilities, [
                'cost_increase_energy_loss', 'cost_neutral_energy_loss',
                'cost_increase_zero_energy_change',
            ]);
            const advantageText = solarEdgeAdvantage === null || solectriaAdvantage === null
                ? 'Unavailable'
                : `SolarEdge ${technoeconomicFormatPercent(solarEdgeAdvantage)} · Solectria ${technoeconomicFormatPercent(solectriaAdvantage)}`;
            technoeconomicElements.decisionMetrics?.replaceChildren(
                technoeconomicSummaryItem('Lifecycle cost difference · P50',
                    technoeconomicFormatMetric(cost.metricName, costPercentiles.p50)),
                technoeconomicSummaryItem('Lifecycle energy difference · P50',
                    technoeconomicFormatMetric(energy.metricName, energyPercentiles.p50)),
                technoeconomicSummaryItem('Joint cost-and-energy advantage', advantageText),
                technoeconomicSummaryItem('Decision confidence', confidence)
            );
        }

        function technoeconomicRenderResultSummary(job, result) {
            const root = technoeconomicElements.resultSummary;
            if (!root) return;
            root.replaceChildren(
                technoeconomicSummaryItem('Job', job.job_id),
                technoeconomicSummaryItem('Basis', result.analysis_basis === 'solartac_site'
                    ? 'SolarTAC site as-built' : 'Commercial representative'),
                technoeconomicSummaryItem('Realizations', technoeconomicFormatNumber(
                    result.realization_count, 0
                )),
                technoeconomicSummaryItem('Seed', String(result.seed ?? 'Unavailable')),
                technoeconomicSummaryItem('Project life',
                    `${technoeconomicFormatNumber(result.project_life_years, 0)} years`),
                technoeconomicSummaryItem('Energy', result.energy_available === true
                    ? 'Available' : 'Unavailable; commercial cost-only result'),
                technoeconomicSummaryItem('Commercial transfer',
                    technoeconomicHumanize(result.commercial_transfer_status)),
                technoeconomicSummaryItem('Evidence status',
                    technoeconomicHumanize(result.input_status)),
                technoeconomicSummaryItem('Elapsed time', job.elapsed_seconds === null
                    || job.elapsed_seconds === undefined ? 'Unavailable'
                    : `${technoeconomicFormatNumber(job.elapsed_seconds, 1)} seconds`)
            );
        }

        function technoeconomicRenderProvenance(job, result) {
            const root = technoeconomicElements.provenance;
            if (!root) return;
            root.replaceChildren();
            const resultProvenance = technoeconomicPlainObject(job.result_provenance);
            technoeconomicDefinition(root, 'Annual source job', job.source_annual_job_id);
            technoeconomicDefinition(root, 'Analysis basis', result.analysis_basis);
            technoeconomicDefinition(root, 'Capacity basis', result.capacity_basis);
            technoeconomicDefinition(root, 'Eligible weather years',
                Array.isArray(result.eligible_weather_years)
                    ? result.eligible_weather_years.join(', ') : 'Unavailable');
            technoeconomicDefinition(root, 'Calculation contract', result.calculation_contract_version);
            technoeconomicDefinition(root, 'Sampling contract', result.sampling_version);
            technoeconomicDefinition(root, 'Source snapshot SHA-256', result.source_snapshot_sha256);
            technoeconomicDefinition(root, 'Request SHA-256', resultProvenance.request_sha256);
            technoeconomicDefinition(root, 'Submission provenance SHA-256',
                job.submission_provenance_sha256 || resultProvenance.submission_provenance_sha256);
            technoeconomicDefinition(root, 'Completed at', job.completed_at);
            const commercialScaling = technoeconomicPlainObject(result.commercial_scaling);
            if (Object.keys(commercialScaling).length) {
                const targetWatts = Number(commercialScaling.target_capacity_w);
                technoeconomicDefinition(
                    root, 'Commercial scaling target',
                    Number.isFinite(targetWatts) && targetWatts > 0
                        ? `${technoeconomicFormatNumber(targetWatts / 1000, 6)} kW `
                            + `(${technoeconomicRatingBasisLabel(
                                commercialScaling.target_rating_basis
                            )})`
                        : 'Unavailable'
                );
                technoeconomicDefinition(
                    root, 'Commercial marginal-cost timing',
                    technoeconomicHumanize(commercialScaling.marginal_cost_timing)
                );
                technoeconomicDefinition(
                    root, 'Commercial transfer method',
                    technoeconomicHumanize(commercialScaling.transfer_method)
                );
            }
            const counts = technoeconomicPlainObject(result.evidence_class_counts);
            for (const evidenceClass of TECHNOECONOMIC_EVIDENCE_CLASSES.map((item) => item[0])) {
                if (Object.prototype.hasOwnProperty.call(counts, evidenceClass)) {
                    technoeconomicDefinition(root, `Evidence: ${technoeconomicHumanize(evidenceClass)}`,
                        technoeconomicFormatNumber(counts[evidenceClass], 0));
                }
            }
            const capacities = technoeconomicPlainObject(result.capacities);
            const appliedCapacities = technoeconomicPlainObject(result.applied_capacities);
            for (const system of ['solectria', 'solaredge']) {
                const systemLabel = system === 'solectria' ? 'Solectria' : 'SolarEdge';
                const capacity = technoeconomicPlainObject(capacities[system]);
                const applied = technoeconomicPlainObject(appliedCapacities[system]);
                const appliedWatts = Number(applied.applied_capacity_w);
                if (Number.isFinite(appliedWatts) && appliedWatts > 0) {
                    const appliedUnit = applied.rating_basis === 'ac_operating_limit'
                        ? 'kWac' : 'kWdc';
                    const appliedBasis = applied.rating_basis === 'ac_operating_limit'
                        ? 'AC operating limit' : 'installed DC nameplate fallback';
                    technoeconomicDefinition(
                        root, `${systemLabel} applied capacity`,
                        `${technoeconomicFormatNumber(appliedWatts / 1000, 2)} ${appliedUnit} | ${appliedBasis}`
                    );
                } else if (Object.keys(capacity).length) {
                    technoeconomicDefinition(
                        root, `${systemLabel} capacity`,
                        `${technoeconomicFormatNumber(capacity.installed_wdc, 1)} Wdc | ${capacity.module_model || 'module unavailable'}`
                    );
                }
                if (Object.keys(capacity).length) {
                    if (Number.isFinite(appliedWatts) && appliedWatts > 0) {
                        technoeconomicDefinition(
                            root, `${systemLabel} installed DC provenance`,
                            `${technoeconomicFormatNumber(capacity.installed_wdc, 1)} Wdc | ${capacity.module_model || 'module unavailable'}`
                        );
                    }
                    technoeconomicDefinition(
                        root, `${systemLabel} physics`,
                        `${capacity.physics_version || 'Unavailable'} | ${capacity.physics_fingerprint || 'fingerprint unavailable'}`
                    );
                }
            }
        }

        function technoeconomicSetPlot(image, fallback, url, unavailableText) {
            if (!image || !fallback) return;
            image.onload = null;
            image.onerror = null;
            image.removeAttribute('src');
            image.hidden = true;
            fallback.hidden = false;
            fallback.textContent = unavailableText;
            if (!url) return;
            image.onload = () => {
                image.hidden = false;
                fallback.hidden = true;
            };
            image.onerror = () => {
                image.hidden = true;
                fallback.hidden = false;
                fallback.textContent = 'The verified figure could not be loaded.';
            };
            image.src = url;
        }

        function technoeconomicSetDownload(link, url) {
            if (!link) return;
            link.removeAttribute('href');
            link.hidden = true;
            if (url) {
                link.href = url;
                link.hidden = false;
            }
        }

        function technoeconomicRenderArtifacts(job) {
            const manifest = technoeconomicPlainObject(
                technoeconomicPlainObject(job.artifacts).exports
            );
            const entries = technoeconomicPlainObject(manifest.artifacts);
            const safe = (artifactId) => technoeconomicSafeArtifactUrl(
                job.job_id, artifactId, technoeconomicPlainObject(entries[artifactId]).url
            );
            technoeconomicSetPlot(
                technoeconomicElements.cdfPlot, technoeconomicElements.cdfPlotFallback,
                safe('cdf_plot'), 'CDF figure is not available in the verified artifact manifest.'
            );
            technoeconomicSetPlot(
                technoeconomicElements.sensitivityPlot,
                technoeconomicElements.sensitivityPlotFallback,
                safe('sensitivity_plot'),
                'Sensitivity figure is not available in the verified artifact manifest.'
            );
            technoeconomicSetPlot(
                technoeconomicElements.convergencePlot,
                technoeconomicElements.convergencePlotFallback,
                safe('convergence_plot'),
                'Convergence figure is not available in the verified artifact manifest.'
            );
            technoeconomicSetDownload(technoeconomicElements.csvLink, safe('csv_bundle'));
            technoeconomicSetDownload(technoeconomicElements.xlsxLink, safe('xlsx_workbook'));
        }

        function renderTechnoeconomicJobResult(job) {
            const result = technoeconomicPlainObject(job?.result);
            if (!job || job.state !== 'done' || !Object.keys(result).length) {
                if (technoeconomicElements.results) technoeconomicElements.results.hidden = true;
                return;
            }
            const contractVersion = result.calculation_contract_version
                || job.request?.calculation_contract_version;
            const standaloneV4 = contractVersion === TECHNOECONOMIC_STANDALONE_CONTRACT_VERSION;
            const pairedV5 = contractVersion === TECHNOECONOMIC_PAIRED_CONTRACT_VERSION;
            const lifecycleV6 = contractVersion === TECHNOECONOMIC_LIFECYCLE_CONTRACT_VERSION;
            if (standaloneV4 || pairedV5 || lifecycleV6) {
                if (technoeconomicElements.results) technoeconomicElements.results.hidden = true;
                if (technoeconomicElements.standaloneResults) {
                    technoeconomicElements.standaloneResults.hidden = false;
                }
                if (lifecycleV6) technoeconomicRenderLifecycleResult(job, result);
                else if (pairedV5) technoeconomicRenderPairedResult(job, result);
                else technoeconomicRenderStandaloneResult(job, result);
                return;
            }
            if (technoeconomicElements.standaloneResults) {
                technoeconomicElements.standaloneResults.hidden = true;
            }
            technoeconomicRenderDecision(result);
            technoeconomicRenderResultSummary(job, result);
            technoeconomicRenderCommercialScaling(result);
            technoeconomicRenderMetrics(result);
            technoeconomicRenderTradeoffs(result);
            technoeconomicRenderPerYear(result);
            technoeconomicRenderSensitivity(result);
            technoeconomicRenderConvergence(result);
            technoeconomicRenderProvenance(job, result);
            technoeconomicRenderArtifacts(job);
            technoeconomicElements.results.hidden = false;
        }

        function renderTechnoeconomicAnalysis(_legacyResultIgnored) {
            // Shared historical callers may still invoke this after an Annual render.
            // TEA never consumes that browser result; only the durable TEA job is authoritative.
            if (technoeconomicJob?.state === 'done') renderTechnoeconomicJobResult(technoeconomicJob);
            else if (!technoeconomicJob
                && (technoeconomicActiveJobId || technoeconomicLoadActiveJobId())) {
                void restoreTechnoeconomicActiveJob();
            }
        }

        function technoeconomicSafeMetricContext(summary) {
            const value = technoeconomicPlainObject(summary);
            const percentiles = technoeconomicPlainObject(value.percentiles);
            const finiteOrNull = (item) => {
                if (item === null || item === undefined || item === '') return null;
                const number = Number(item);
                return Number.isFinite(number) ? number : null;
            };
            return {
                status: value.status === 'available' ? 'available' : 'unavailable',
                reason: typeof value.reason === 'string' ? value.reason : null,
                count: Number.isSafeInteger(Number(value.count)) ? Number(value.count) : 0,
                p5: finiteOrNull(percentiles.p5),
                p50: finiteOrNull(percentiles.p50),
                p95: finiteOrNull(percentiles.p95),
            };
        }

        function getTechnoeconomicChatContext() {
            const draft = typeof document === 'object' && technoeconomicElements?.form
                ? getTechnoeconomicFormState() : technoeconomicDefaultDraft();
            const context = {
                schema_version: 'technoeconomic-chat-context-v1',
                read_only: true,
                server_authoritative: true,
                job_id: technoeconomicJob?.job_id || technoeconomicActiveJobId || null,
                job_state: technoeconomicJob?.state || 'draft',
                progress: Number.isFinite(Number(technoeconomicJob?.progress))
                    ? Number(technoeconomicJob.progress) : 0,
                stage: typeof technoeconomicJob?.stage === 'string' ? technoeconomicJob.stage : null,
                source_annual_job_id: technoeconomicJob?.source_annual_job_id
                    || draft.source_annual_job_id || null,
                analysis_basis: technoeconomicJob?.result?.analysis_basis || draft.basis || null,
                realization_count: null,
                energy_available: null,
                commercial_transfer_status: null,
                convergence_status: null,
                summaries: {},
            };
            if (technoeconomicJob?.state !== 'done' || !technoeconomicJob.result) return context;
            const result = technoeconomicPlainObject(technoeconomicJob.result);
            context.realization_count = Number.isSafeInteger(Number(result.realization_count))
                ? Number(result.realization_count) : null;
            context.energy_available = result.energy_available === true;
            context.commercial_transfer_status = typeof result.commercial_transfer_status === 'string'
                ? result.commercial_transfer_status : null;
            context.convergence_status = typeof result.convergence?.status === 'string'
                ? result.convergence.status : null;
            const summaries = technoeconomicPlainObject(result.summaries);
            for (const metricName of Object.keys(TECHNOECONOMIC_METRIC_LABELS)) {
                if (Object.prototype.hasOwnProperty.call(summaries, metricName)) {
                    context.summaries[metricName] = technoeconomicSafeMetricContext(
                        summaries[metricName]
                    );
                }
            }
            for (const groupName of ['energy_classes', 'tradeoff_classes']) {
                const group = technoeconomicPlainObject(summaries[groupName]);
                const probabilities = {};
                for (const [name, raw] of Object.entries(
                    technoeconomicPlainObject(group.probabilities)
                )) {
                    const number = Number(raw);
                    if (/^[a-z_]+$/.test(name) && Number.isFinite(number)) {
                        probabilities[name] = number;
                    }
                }
                context.summaries[groupName] = {
                    status: group.status === 'unavailable' ? 'unavailable' : 'available',
                    reason: typeof group.reason === 'string' ? group.reason : null,
                    probabilities,
                };
            }
            return context;
        }

        function technoeconomicClearResults() {
            if (technoeconomicElements.results) technoeconomicElements.results.hidden = true;
            if (technoeconomicElements.standaloneResults) {
                technoeconomicElements.standaloneResults.hidden = false;
            }
            technoeconomicClearStandaloneResult();
            for (const root of [
                technoeconomicElements.decisionMetrics,
                technoeconomicElements.resultSummary, technoeconomicElements.metricSummary,
                technoeconomicElements.tradeoffs, technoeconomicElements.perYearBody,
                technoeconomicElements.sensitivityBody, technoeconomicElements.convergenceBody,
                technoeconomicElements.provenance,
            ]) root?.replaceChildren();
            const commercialSection = technoeconomicDomElement('technoeconomicCommercialResults');
            const commercialMetrics = technoeconomicDomElement(
                'technoeconomicCommercialResultMetrics'
            );
            const commercialStatus = technoeconomicDomElement(
                'technoeconomicCommercialResultStatus'
            );
            if (commercialSection) commercialSection.hidden = true;
            commercialMetrics?.replaceChildren();
            if (commercialStatus) {
                commercialStatus.textContent = '';
                delete commercialStatus.dataset.state;
            }
            if (technoeconomicElements.convergenceStatus) {
                technoeconomicElements.convergenceStatus.textContent = '';
            }
            technoeconomicSetPlot(
                technoeconomicElements.cdfPlot, technoeconomicElements.cdfPlotFallback,
                null, 'CDF figure is not available.'
            );
            technoeconomicSetPlot(
                technoeconomicElements.sensitivityPlot,
                technoeconomicElements.sensitivityPlotFallback,
                null, 'Sensitivity figure is not available.'
            );
            technoeconomicSetPlot(
                technoeconomicElements.convergencePlot,
                technoeconomicElements.convergencePlotFallback,
                null, 'Convergence figure is not available.'
            );
            technoeconomicSetDownload(technoeconomicElements.csvLink, null);
            technoeconomicSetDownload(technoeconomicElements.xlsxLink, null);
        }

        function invalidateTechnoeconomicWorkspace(options = {}) {
            invalidateTechnoeconomicStatusPoll();
            invalidateTechnoeconomicLifecycleRequest();
            invalidateTechnoeconomicSubmissionRequest();
            technoeconomicJob = null;
            technoeconomicPendingSubmission = null;
            if (options.preserveActiveJob !== true) technoeconomicPersistActiveJobId(null);
            technoeconomicClearResults();
            if (technoeconomicElements.jobPanel) technoeconomicElements.jobPanel.hidden = true;
            if (technoeconomicElements.jobState) technoeconomicElements.jobState.textContent = 'Not started';
            if (technoeconomicElements.progress) technoeconomicElements.progress.value = 0;
            if (technoeconomicElements.progressValue) technoeconomicElements.progressValue.textContent = '0%';
            if (technoeconomicElements.progressStage) {
                technoeconomicElements.progressStage.textContent = 'Waiting to start.';
            }
            technoeconomicRenderErrors(technoeconomicElements.jobError, []);
            if (!options.preserveDraft) technoeconomicPendingSubmission = null;
            if (typeof updateAgentContext === 'function') updateAgentContext();
        }

        function resetTechnoeconomicWorkspace(options = {}) {
            invalidateTechnoeconomicWorkspace({preserveDraft: false});
            const preserveDraft = options.preserveDraft === true;
            if (!preserveDraft) {
                if (typeof localStorage === 'object') {
                    try {
                        localStorage.removeItem(TECHNOECONOMIC_DRAFT_STORAGE_KEY);
                        localStorage.removeItem(TECHNOECONOMIC_STANDALONE_DRAFT_STORAGE_KEY);
                        localStorage.removeItem(
                            TECHNOECONOMIC_STANDALONE_PREVIOUS_DRAFT_STORAGE_KEY
                        );
                        localStorage.removeItem(
                            TECHNOECONOMIC_STANDALONE_LEGACY_DRAFT_STORAGE_KEY
                        );
                    } catch (_error) {
                        // A reset still succeeds when local storage is unavailable.
                    }
                }
                applyTechnoeconomicFormState(technoeconomicDefaultDraft());
                technoeconomicStandaloneApplyDraft(technoeconomicStandaloneDefaultDraft());
                technoeconomicDraftRevision += 1;
            }
            if (options.refreshSources !== false) refreshTechnoeconomicSources();
        }

        function initializeTechnoeconomicWorkspace() {
            if (technoeconomicWorkspaceInitialized || typeof document !== 'object'
                || !technoeconomicElements?.form) return;
            technoeconomicWorkspaceInitialized = true;
            technoeconomicStandaloneInitializeEditors();
            technoeconomicRenderContractMode();
            const standaloneDraft = technoeconomicLoadStandaloneDraft();
            if (standaloneDraft) technoeconomicStandaloneApplyDraft(standaloneDraft);
            else if (technoeconomicElements.standaloneAccept) {
                technoeconomicElements.standaloneAccept.checked = false;
            }
            const localDraft = technoeconomicLoadLocalDraft();
            applyTechnoeconomicFormState(localDraft || technoeconomicDefaultDraft());
            technoeconomicElements.form.addEventListener('submit', technoeconomicOpenConfirmation);
            technoeconomicElements.form.addEventListener('input', (event) => {
                technoeconomicClearStandaloneAcceptance(event.target);
                technoeconomicHandleLifecycleTemplateInput(event.target);
                const commercialAccept = technoeconomicDomElement(
                    'technoeconomicGuidedCommercialAccept'
                );
                const guidedDependency = technoeconomicElements.guidedPanel?.contains(event.target)
                    || event.target === technoeconomicElements.sourceSelect;
                if (technoeconomicEntryMode === TECHNOECONOMIC_GUIDED_ENTRY_MODE
                    && guidedDependency) {
                    technoeconomicCloseStaleAdvancedPreview();
                }
                if (technoeconomicEntryMode === TECHNOECONOMIC_GUIDED_ENTRY_MODE
                    && guidedDependency
                    && event.target !== technoeconomicElements.guidedAccept
                    && event.target !== commercialAccept
                    && technoeconomicElements.guidedAccept?.checked) {
                    technoeconomicElements.guidedAccept.checked = false;
                }
                if (technoeconomicEntryMode === TECHNOECONOMIC_GUIDED_ENTRY_MODE
                    && guidedDependency
                    && event.target !== technoeconomicElements.guidedAccept
                    && event.target !== commercialAccept
                    && commercialAccept?.checked) {
                    commercialAccept.checked = false;
                }
                if (technoeconomicEntryMode === TECHNOECONOMIC_GUIDED_ENTRY_MODE
                    && technoeconomicElements.advancedDetails?.contains(event.target)) {
                    technoeconomicEntryMode = TECHNOECONOMIC_ADVANCED_ENTRY_MODE;
                    technoeconomicRenderEntryMode();
                }
                if (technoeconomicEntryMode === TECHNOECONOMIC_GUIDED_ENTRY_MODE
                    && technoeconomicElements.guidedPanel?.contains(event.target)) {
                    technoeconomicRenderGuidedEstimates();
                }
                if (technoeconomicElements.standaloneAssumptionsDialog?.contains(event.target)) {
                    technoeconomicRenderStandaloneDraft();
                }
                technoeconomicMarkDraftChanged();
            });
            technoeconomicElements.form.addEventListener('change', (event) => {
                technoeconomicClearStandaloneAcceptance(event.target);
                if (event.target === technoeconomicElements.calculationContract) {
                    technoeconomicRenderContractMode();
                    // Contract rendering controls which version is available; the
                    // builder remains the owner of which section is visible.
                    if (technoeconomicElements.standaloneAssumptionsDialog?.open) {
                        technoeconomicBuilderUpdate();
                    }
                }
                if (event.target === technoeconomicElements.standaloneSourceSelect) {
                    if (technoeconomicLifecycleEntryMode === 'template') {
                        technoeconomicLifecycleEntryMode = 'empty';
                        technoeconomicLifecycleTemplateModified = false;
                        technoeconomicSetLifecycleTemplateControlsEnabled(false);
                        technoeconomicSetLifecycleTemplateButtonMode(false);
                        if (technoeconomicElements.lifecycleJson) {
                            technoeconomicElements.lifecycleJson.value = '';
                        }
                        technoeconomicRenderLifecycleTemplateCostBasis(
                            technoeconomicLifecycleTemplateRatingBasis()
                        );
                        technoeconomicSetLifecycleTemplateStatus(
                            'ready', 'Annual source changed; apply the template again',
                            'Reapplying selects the correct AC- or DC-basis NREL CAPEX and O&M preset and regenerates component scaling.'
                        );
                    }
                    if (technoeconomicElements.sourceSelect) {
                        technoeconomicElements.sourceSelect.value = event.target.value;
                    }
                    technoeconomicRenderSelectedSource();
                    technoeconomicRenderStandaloneDraft();
                }
                if (event.target === technoeconomicElements.sourceSelect) {
                    technoeconomicCloseStaleAdvancedPreview();
                    technoeconomicRenderSelectedSource();
                }
                if (event.target === technoeconomicElements.basis
                    || event.target === technoeconomicElements.transferEnabled) {
                    if (event.target === technoeconomicElements.basis) {
                        technoeconomicEntryMode = TECHNOECONOMIC_ADVANCED_ENTRY_MODE;
                        technoeconomicRenderEntryMode();
                    }
                    technoeconomicRenderBasisVisibility();
                }
                if (event.target === technoeconomicElements.costYear) {
                    const draft = getTechnoeconomicFormState();
                    technoeconomicRenderCostLines(draft.cost_lines, draft.cost_year, draft.basis);
                    technoeconomicElements.commercialDesignEditor?.replaceChildren(
                        technoeconomicCreateCommercialDesignEditor(
                            draft.commercial_reference_design, draft.cost_year
                        )
                    );
                }
                if (event.target === technoeconomicDomElement(
                    'technoeconomicGuidedCommercialEnabled'
                ) || event.target === technoeconomicDomElement(
                    'technoeconomicGuidedCommercialCostTiming'
                )) technoeconomicRenderGuidedCommercialControls();
                for (const {key} of TECHNOECONOMIC_PAIRED_SYSTEMS) {
                    if (event.target === technoeconomicPairedSystemElements(key).replacementEnabled) {
                        technoeconomicStandaloneRenderReplacement(key);
                        technoeconomicRenderStandaloneDraft();
                    }
                }
                technoeconomicMarkDraftChanged();
            });
            technoeconomicElements.costLines?.addEventListener('click', (event) => {
                const button = event.target.closest('[data-tea-action="remove-cost-line"]');
                if (button) {
                    technoeconomicEntryMode = TECHNOECONOMIC_ADVANCED_ENTRY_MODE;
                    technoeconomicRenderEntryMode();
                    technoeconomicRemoveCostLine(button);
                }
            });
            technoeconomicElements.addCostLineButton?.addEventListener(
                'click', () => {
                    technoeconomicEntryMode = TECHNOECONOMIC_ADVANCED_ENTRY_MODE;
                    technoeconomicRenderEntryMode();
                    technoeconomicAddCostLine();
                }
            );
            technoeconomicElements.useGuidedButton?.addEventListener(
                'click', technoeconomicUseGuidedSolarTac
            );
            technoeconomicElements.useLifecycleTemplateButton?.addEventListener(
                'click', technoeconomicApplyLifecycleTemplate
            );
            technoeconomicElements.advancedDetails?.addEventListener('toggle', () => {
                if (technoeconomicElements.advancedDetails.open
                    && technoeconomicEntryMode === TECHNOECONOMIC_GUIDED_ENTRY_MODE) {
                    technoeconomicMaterializeGuidedEditors();
                }
            });
            technoeconomicElements.refreshSourcesButton?.addEventListener(
                'click', () => refreshTechnoeconomicSources()
            );
            technoeconomicElements.standaloneRefreshSourcesButton?.addEventListener(
                'click', () => refreshTechnoeconomicSources()
            );
            technoeconomicElements.openAnnualButton?.addEventListener('click', () => {
                if (typeof switchMode === 'function') switchMode('annual');
            });
            technoeconomicElements.standaloneOpenAnnualButton?.addEventListener('click', () => {
                if (typeof switchMode === 'function') switchMode('annual');
            });
            technoeconomicElements.standaloneEditAssumptionsButton?.addEventListener(
                'click', (event) => technoeconomicOpenAssumptionsDialog(event.currentTarget)
            );
            technoeconomicElements.standaloneAssumptionsCloseButton?.addEventListener(
                'click', () => technoeconomicCloseAssumptionsDialog()
            );
            technoeconomicElements.builderSteps?.addEventListener('click', (event) => {
                const button = event.target.closest?.('[data-tea-builder-step]');
                if (button) technoeconomicBuilderGoTo(button.dataset.teaBuilderStep);
            });
            technoeconomicElements.builderSaveButton?.addEventListener(
                'click', technoeconomicBuilderSaveDraft
            );
            technoeconomicElements.builderBackButton?.addEventListener('click', () => {
                const previous = TECHNOECONOMIC_BUILDER_SECTIONS[
                    Math.max(0, technoeconomicBuilderSectionIndex - 1)
                ];
                technoeconomicBuilderGoTo(previous.key);
            });
            technoeconomicElements.builderContinueButton?.addEventListener('click', () => {
                const next = TECHNOECONOMIC_BUILDER_SECTIONS[
                    Math.min(
                        TECHNOECONOMIC_BUILDER_SECTIONS.length - 1,
                        technoeconomicBuilderSectionIndex + 1
                    )
                ];
                technoeconomicBuilderGoTo(next.key);
            });
            technoeconomicElements.standaloneAssumptionsDialog?.addEventListener('cancel', () => {
                technoeconomicAssumptionsReturnFocus = true;
            });
            technoeconomicElements.standaloneAssumptionsDialog?.addEventListener('close', () => {
                technoeconomicFinishAssumptionsClose();
            });
            technoeconomicElements.confirmCancelButton?.addEventListener(
                'click', technoeconomicCloseConfirmation
            );
            technoeconomicElements.confirmCloseButton?.addEventListener(
                'click', technoeconomicCloseConfirmation
            );
            technoeconomicElements.confirmSubmitButton?.addEventListener(
                'click', technoeconomicConfirmSubmission
            );
            technoeconomicElements.confirmDialog?.addEventListener('cancel', (event) => {
                if (technoeconomicSubmissionRequestInFlight) {
                    event.preventDefault();
                    return;
                }
                technoeconomicPendingSubmission = null;
            });
            technoeconomicElements.confirmDialog?.addEventListener('close', () => {
                if (!technoeconomicElements.confirmSubmitButton?.disabled) {
                    technoeconomicPendingSubmission = null;
                }
            });
            technoeconomicElements.cancelButton?.addEventListener('click', technoeconomicCancelJob);
            technoeconomicElements.retryButton?.addEventListener('click', technoeconomicRetryJob);
            technoeconomicElements.deleteButton?.addEventListener('click', technoeconomicDeleteJob);
            technoeconomicRenderSelectedSource();
            technoeconomicRenderStandaloneDraft();
        }
