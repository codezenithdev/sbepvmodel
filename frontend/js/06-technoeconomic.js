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
            'transfer.incremental', 'weather.year',
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

        function technoeconomicDefaultTechnologyDesign(solaredge = false) {
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
            return sanitizeTechnoeconomicDraft(draft);
        }

        function technoeconomicReadGuidedForm() {
            const read = (element) => element?.value || '';
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
            const hasRanges = pairs.some(([elementKey, valueKey]) =>
                (elementKey.endsWith('Low') || elementKey.endsWith('High')) && guided[valueKey]
            );
            if (technoeconomicElements.guidedRanges) {
                technoeconomicElements.guidedRanges.open = hasRanges;
            }
            technoeconomicRenderGuidedEstimates();
        }

        function technoeconomicRenderEntryMode() {
            const guided = technoeconomicEntryMode === TECHNOECONOMIC_GUIDED_ENTRY_MODE;
            if (technoeconomicElements.guidedPanel) {
                technoeconomicElements.guidedPanel.hidden = !guided;
            }
            if (technoeconomicElements.advancedDetails) {
                technoeconomicElements.advancedDetails.hidden = true;
                technoeconomicElements.advancedDetails.open = false;
            }
            if (technoeconomicElements.entryModeRow) {
                technoeconomicElements.entryModeRow.hidden = guided;
            }
            if (technoeconomicElements.submitPanel) {
                technoeconomicElements.submitPanel.hidden = !guided;
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
            if (options.className) node.className = options.className;
            if (options.text !== undefined) node.textContent = String(options.text);
            if (options.type) node.type = options.type;
            if (options.value !== undefined) node.value = String(options.value);
            if (options.name) node.name = options.name;
            if (options.hidden !== undefined) node.hidden = Boolean(options.hidden);
            if (options.disabled !== undefined) node.disabled = Boolean(options.disabled);
            if (options.checked !== undefined) node.checked = Boolean(options.checked);
            if (options.placeholder) node.placeholder = options.placeholder;
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
            const select = technoeconomicElements.sourceSelect;
            if (!select || !sourceId || Array.from(select.options).some((option) => option.value === sourceId)) {
                return;
            }
            const option = technoeconomicNode('option', {
                value: sourceId, text: `Saved Annual source ${sourceId} (refresh to verify)`,
            });
            select.appendChild(option);
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
                const saved = technoeconomicPersistDraft();
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
            let rationale = null;
            if (provisional) {
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
                explicit_acceptance: provisional ? evidence.explicit_acceptance === true : null,
                acceptance_rationale: provisional ? rationale : null,
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
                const declaredInputs = serializedLines.length + 2 + (commercialTransfer ? 2 : 0);
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
            if (technoeconomicElements.sourceStatus) technoeconomicElements.sourceStatus.textContent = title;
            if (technoeconomicElements.sourceDetail) technoeconomicElements.sourceDetail.textContent = detail;
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
        }

        function technoeconomicRenderSelectedSource() {
            const sourceId = technoeconomicElements.sourceSelect?.value || '';
            const source = technoeconomicSources.find((item) => item.source_annual_job_id === sourceId);
            const details = technoeconomicElements.sourceDetails;
            const energyRows = technoeconomicElements.sourceEnergyRows;
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
            select.replaceChildren(technoeconomicNode('option', {
                value: '', text: 'Select a verified Annual Simulation',
            }));
            const ordered = [...technoeconomicSources].sort((left, right) =>
                String(right.provenance?.completed_at || '').localeCompare(
                    String(left.provenance?.completed_at || '')
                ));
            for (const source of ordered) {
                const years = Array.isArray(source.eligible_years)
                    ? ` | ${source.eligible_years.join(', ')}` : '';
                const label = `${source.source_annual_job_id}${years}${
                    source.eligible === true ? '' : ` | ineligible: ${source.reason_code || 'verification failed'}`
                }`;
                const option = technoeconomicNode('option', {
                    value: source.source_annual_job_id, text: label,
                    disabled: source.eligible !== true,
                });
                select.appendChild(option);
            }
            if (selectedId && !ordered.some((source) => source.source_annual_job_id === selectedId)) {
                technoeconomicEnsureSourceOption(selectedId);
            }
            select.value = selectedId;
            technoeconomicRenderSelectedSource();
        }

        async function refreshTechnoeconomicSources(options = {}) {
            const revision = ++technoeconomicSourceRequestRevision;
            if (technoeconomicSourceAbortController) technoeconomicSourceAbortController.abort();
            technoeconomicSourceAbortController = new AbortController();
            const selectedId = options.selectedId ?? technoeconomicElements.sourceSelect?.value ?? '';
            if (technoeconomicElements.refreshSourcesButton) {
                technoeconomicElements.refreshSourcesButton.disabled = true;
            }
            technoeconomicSetSourceState(
                'loading', 'Checking Annual Simulation sources',
                'The server is verifying immutable artifacts, capacities, coverage, and calibration lineage.'
            );
            try {
                const body = await technoeconomicFetchJson('/api/technoeconomic/sources', {
                    signal: technoeconomicSourceAbortController.signal,
                });
                if (revision !== technoeconomicSourceRequestRevision) return technoeconomicSources;
                const rows = Array.isArray(body.sources) ? body.sources : [];
                technoeconomicSources = rows.filter((row) => {
                    const id = row?.source_annual_job_id;
                    return typeof id === 'string' && id.length > 0 && id.length <= 200;
                }).map((row) => ({...row}));
                technoeconomicCloseStaleAdvancedPreview();
                technoeconomicRenderSourceOptions(selectedId);
                if (!technoeconomicSources.length) technoeconomicSetSourceState(
                    'empty', 'No verified Annual Simulation sources',
                    'Complete a calibrated Annual Simulation, then refresh this list.'
                );
                return technoeconomicSources;
            } catch (error) {
                if (revision !== technoeconomicSourceRequestRevision || error.code === 'request_aborted') {
                    return technoeconomicSources;
                }
                technoeconomicSetSourceState(
                    'reconnecting', 'Could not refresh sources', error.message
                );
                return technoeconomicSources;
            } finally {
                if (revision === technoeconomicSourceRequestRevision
                    && technoeconomicElements.refreshSourcesButton) {
                    technoeconomicElements.refreshSourcesButton.disabled = false;
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

        function technoeconomicRenderConfirmation(serialized, sourceSummary) {
            const payload = serialized.payload;
            const summary = technoeconomicElements.confirmSummary;
            if (summary) {
                const items = [
                    technoeconomicSummaryItem('Annual source', payload.source_annual_job_id),
                    technoeconomicSummaryItem('Frozen source snapshot SHA-256',
                        sourceSummary.source_snapshot_sha256 || 'Re-verified by server at submission'),
                    technoeconomicSummaryItem('Eligible weather years',
                        sourceSummary.eligible_years.join(', ') || 'Re-verified by server at submission'),
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
                    technoeconomicSummaryItem('Realizations', payload.n.toLocaleString('en-US')),
                    technoeconomicSummaryItem('Seed', String(payload.seed)),
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
                summary.replaceChildren(...items);
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

        function technoeconomicOpenConfirmation(event) {
            event?.preventDefault();
            if (technoeconomicLifecycleRequestInFlight || technoeconomicSubmissionRequestInFlight) {
                technoeconomicRenderErrors(technoeconomicElements.formErrors, [{
                    path: '',
                    message: 'Wait for the current technoeconomic job action to finish before reviewing another submission.',
                }]);
                technoeconomicElements.formErrors?.focus();
                return;
            }
            if (['queued', 'running'].includes(technoeconomicJob?.state)) {
                technoeconomicRenderErrors(technoeconomicElements.formErrors, [{
                    path: '',
                    message: 'Wait for or cancel the active technoeconomic job before queueing another.',
                }]);
                technoeconomicElements.formErrors?.focus();
                return;
            }
            const guidedErrors = technoeconomicGuidedFormErrors();
            if (guidedErrors.length) {
                technoeconomicRenderErrors(technoeconomicElements.formErrors, guidedErrors);
                technoeconomicElements.formErrors?.focus();
                return;
            }
            const draft = getTechnoeconomicFormState();
            const serialized = serializeTechnoeconomicRequest(draft, {sources: technoeconomicSources});
            technoeconomicRenderErrors(technoeconomicElements.formErrors, serialized.errors);
            if (!serialized.valid) {
                technoeconomicElements.formErrors?.focus();
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
            if (technoeconomicElements?.confirmSubmitButton) {
                technoeconomicElements.confirmSubmitButton.disabled = false;
                technoeconomicElements.confirmSubmitButton.textContent = 'Confirm and queue';
            }
            if (technoeconomicElements?.confirmCancelButton) {
                technoeconomicElements.confirmCancelButton.disabled = false;
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
            if (technoeconomicElements.submitButton) {
                technoeconomicElements.submitButton.disabled = true;
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
                    if (technoeconomicElements.submitButton) {
                        technoeconomicElements.submitButton.disabled = false;
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
            if (metricName.includes('LCOE') || metricName.includes('lcoo')) return 'USD/kWh AC';
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
            card.appendChild(technoeconomicNode('h4', {
                text: TECHNOECONOMIC_METRIC_LABELS[metricName] || technoeconomicHumanize(metricName),
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
            technoeconomicRenderResultSummary(job, result);
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
            for (const root of [
                technoeconomicElements.resultSummary, technoeconomicElements.metricSummary,
                technoeconomicElements.tradeoffs, technoeconomicElements.perYearBody,
                technoeconomicElements.sensitivityBody, technoeconomicElements.convergenceBody,
                technoeconomicElements.provenance,
            ]) root?.replaceChildren();
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
                    } catch (_error) {
                        // A reset still succeeds when local storage is unavailable.
                    }
                }
                applyTechnoeconomicFormState(technoeconomicDefaultDraft());
                technoeconomicDraftRevision += 1;
            }
            if (options.refreshSources !== false) refreshTechnoeconomicSources();
        }

        function initializeTechnoeconomicWorkspace() {
            if (technoeconomicWorkspaceInitialized || typeof document !== 'object'
                || !technoeconomicElements?.form) return;
            technoeconomicWorkspaceInitialized = true;
            const localDraft = technoeconomicLoadLocalDraft();
            applyTechnoeconomicFormState(localDraft || technoeconomicDefaultDraft());
            technoeconomicElements.form.addEventListener('submit', technoeconomicOpenConfirmation);
            technoeconomicElements.form.addEventListener('input', (event) => {
                if (technoeconomicEntryMode === TECHNOECONOMIC_GUIDED_ENTRY_MODE
                    && (technoeconomicElements.guidedPanel?.contains(event.target)
                        || event.target === technoeconomicElements.sourceSelect)) {
                    technoeconomicCloseStaleAdvancedPreview();
                }
                if (technoeconomicEntryMode === TECHNOECONOMIC_GUIDED_ENTRY_MODE
                    && technoeconomicElements.guidedPanel?.contains(event.target)
                    && event.target !== technoeconomicElements.guidedAccept
                    && technoeconomicElements.guidedAccept?.checked) {
                    technoeconomicElements.guidedAccept.checked = false;
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
                technoeconomicMarkDraftChanged();
            });
            technoeconomicElements.form.addEventListener('change', (event) => {
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
            technoeconomicElements.advancedDetails?.addEventListener('toggle', () => {
                if (technoeconomicElements.advancedDetails.open
                    && technoeconomicEntryMode === TECHNOECONOMIC_GUIDED_ENTRY_MODE) {
                    technoeconomicMaterializeGuidedEditors();
                }
            });
            technoeconomicElements.refreshSourcesButton?.addEventListener(
                'click', () => refreshTechnoeconomicSources()
            );
            technoeconomicElements.openAnnualButton?.addEventListener('click', () => {
                if (typeof switchMode === 'function') switchMode('annual');
            });
            technoeconomicElements.confirmCancelButton?.addEventListener(
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
        }
