"""Currency-year transformations must preserve energy and sampling semantics."""
from copy import deepcopy
import hashlib
import json
import unittest

import numpy as np

from sbepv import technoeconomic as kernel
from sbepv import technoeconomic_cost_year as cost_year
from sbepv import technoeconomic_presets as presets
from sbepv.api import technoeconomic as api
from sbepv.api.schemas import TechnoeconomicSubmissionRequest
from tests.test_technoeconomic_full_report import synthetic_snapshot


class CostYearConversionTests(unittest.TestCase):
    def setUp(self):
        self.source = presets.current_assumptions('annual-report-fixture')
        self.source['n'] = 128
        self.source = api.canonical_submission_request_payload(self.source)

    def test_current_optimizer_default_preserves_historical_requests_and_source(self):
        historical = presets.thursday_assumptions('annual-report-fixture')
        saved_request = deepcopy(historical)
        current = presets.current_assumptions('annual-report-fixture')
        snapshot = synthetic_snapshot()
        frozen_source = deepcopy(snapshot)
        for payload, count, year, preset_id, hardware, midpoint in (
            (historical, 103_077, 2024, presets.PRESET_ID, 3_891_156.75, 154_909_156.75),
            (current, 96_000, 2026, presets.CURRENT_PRESET_ID, 3_624_000, 154_642_000),
        ):
            with self.subTest(preset_id=preset_id):
                shared = payload['paired_commercial']['shared_initial_capex']
                self.assertEqual(count, shared['optimizer_count'])
                self.assertEqual(year, payload['finance']['constant_dollar_cost_year'])
                self.assertEqual(preset_id, shared['report_context']['preset_id'])
                self.assertEqual('annual-report-fixture', payload['source_annual_job_id'])
                self.assertEqual(hardware, count * shared['optimizer_unit_price_usd'])
                solaredge = next(system for system in payload['paired_commercial']['systems']
                                 if system['technology'] == 'solaredge')
                capex = next(line['distribution'] for line in solaredge['cost_lines']
                             if line['cost_category'] == 'full_initial_capex')
                self.assertAlmostEqual(midpoint, (capex['low'] + capex['high']) / 2 * 100_000_000)
                # The kernel request validates the support against quantity, unit price,
                # DC capacity and installation, without changing frozen Annual evidence.
                canonical = api.canonical_submission_request_payload(payload)
                api.build_technoeconomic_kernel_request(canonical, snapshot)
        self.assertAlmostEqual(1.4754, current['paired_commercial']['systems'][1]['cost_lines'][0]['distribution']['low'])
        self.assertAlmostEqual(1.61744, current['paired_commercial']['systems'][1]['cost_lines'][0]['distribution']['high'])
        self.assertNotIn('103077', json.dumps(current))
        self.assertNotIn('103,077', json.dumps(current))
        self.assertIn('96,000', current['paired_commercial']['shared_initial_capex']['report_context']['limitations'])
        self.assertEqual(saved_request, historical)
        self.assertEqual(saved_request, presets.thursday_assumptions('annual-report-fixture'))
        self.assertEqual(frozen_source, snapshot)

    def test_frozen_catalog_and_provisional_2026_are_inspectable(self):
        catalog = cost_year.get_index_catalog()
        self.assertEqual(118.023, catalog['years']['2022']['value'])
        self.assertEqual(133.855, catalog['years']['2026']['value'])
        self.assertEqual('2026-Q2', catalog['years']['2026']['period'])
        self.assertTrue(catalog['years']['2026']['provisional'])
        self.assertFalse(catalog['years']['2022']['provisional'])
        for source in catalog['sources'].values():
            self.assertEqual(source['raw_sha256'], hashlib.sha256(source['raw_csv'].encode('utf-8')).hexdigest())
        catalog['years']['2022']['value'] = 1
        self.assertEqual(118.023, cost_year.get_index_catalog()['years']['2022']['value'])

    def test_all_money_converts_and_original_inputs_remain_unchanged(self):
        before = deepcopy(self.source)
        converted = cost_year.convert_cost_year(self.source, 2022)
        self.assertEqual(before, self.source)
        factor = 118.023 / 133.855
        receipt = converted['cost_year_adjustment']
        self.assertEqual(factor, receipt['factor'])
        self.assertEqual(cost_year.collect_money(before), receipt['original_money'])
        expected = deepcopy(before)
        # Independently check every numeric leaf in the explicitly monetary map.
        for path, original in receipt['original_money'].items():
            actual = cost_year.collect_money(converted)[path]
            if isinstance(original, dict):
                self.assertEqual(original['family'], actual['family'])
                for parameter, amount in original.items():
                    if parameter != 'family':
                        self.assertEqual(amount * factor, actual[parameter], path)
            else:
                self.assertEqual(original * factor, actual, path)
        self.assertEqual(before['finance']['real_discount_rate'], converted['finance']['real_discount_rate'])
        self.assertEqual(before['shared_degradation'], converted['shared_degradation'])
        for key in ('n', 'seed', 'source_annual_job_id'):
            self.assertEqual(expected[key], converted[key])
        for key in ('optimizer_count', 'dc_capacity_w'):
            self.assertEqual(before['paired_commercial']['shared_initial_capex'][key],
                             converted['paired_commercial']['shared_initial_capex'][key])
        self.assertEqual(before['paired_commercial']['target_capacity'], converted['paired_commercial']['target_capacity'])
        self.assertEqual(2022, converted['finance']['constant_dollar_cost_year'])
        self.assertTrue(all(line['constant_dollar_cost_year'] == 2022
                            for system in converted['paired_commercial']['systems'] for line in system['cost_lines']))
        TechnoeconomicSubmissionRequest.model_validate(converted)

    def test_round_trip_uses_original_money_not_repeated_conversion(self):
        converted = cost_year.convert_cost_year(self.source, 2022)
        changed_again = cost_year.convert_cost_year(converted, 2024)
        direct = cost_year.convert_cost_year(self.source, 2024)
        self.assertEqual(direct, changed_again)
        restored = cost_year.convert_cost_year(changed_again, 2026)
        self.assertEqual(cost_year.collect_money(self.source), cost_year.collect_money(restored))
        self.assertEqual(1.0, restored['cost_year_adjustment']['factor'])
        self.assertEqual(2026, restored['cost_year_adjustment']['source_year'])
        TechnoeconomicSubmissionRequest.model_validate(restored)

    def test_mixed_original_cost_years_are_rejected_without_mutating_inputs(self):
        for year in (2024, None):
            with self.subTest(year=year):
                source = deepcopy(self.source)
                source['paired_commercial']['systems'][0]['cost_lines'][0]['constant_dollar_cost_year'] = year
                original = deepcopy(source)
                with self.assertRaisesRegex(ValueError, 'declared source dollar year'):
                    cost_year.convert_cost_year(source, 2022)
                self.assertEqual(original, source)

    def test_all_distribution_families_and_scheduled_costs(self):
        source = deepcopy(self.source)
        source['paired_commercial'].pop('shared_initial_capex')
        distributions = [
            {'family':'fixed', 'value':2.0},
            {'family':'uniform', 'low':.01, 'high':.02},
            {'family':'triangular', 'low':1.0, 'mode':1.5, 'high':2.0},
            {'family':'bounded_normal', 'low':.01, 'high':.03, 'mean':.02, 'sd':.004},
        ]
        lines = [line for system in source['paired_commercial']['systems'] for line in system['cost_lines']]
        for line, distribution in zip(lines, distributions):
            line['distribution'] = distribution
        replacement = deepcopy(lines[0])
        replacement.update(input_id='solectria.replacement', cost_category='scheduled_replacement',
                           coverage_ids=['replacement-equipment'], timing='scheduled_year_end', occurrence_years=[15],
                           distribution={'family':'fixed', 'value':.15})
        source['paired_commercial']['systems'][0]['cost_lines'].append(replacement)
        converted = cost_year.convert_cost_year(source, 2022)
        TechnoeconomicSubmissionRequest.model_validate(converted)
        self.assertEqual([15], converted['paired_commercial']['systems'][0]['cost_lines'][-1]['occurrence_years'])
        factor = converted['cost_year_adjustment']['factor']
        for path, value in cost_year.collect_money(source).items():
            actual = cost_year.collect_money(converted)[path]
            for parameter in value:
                if parameter != 'family':
                    self.assertEqual(value[parameter] * factor, actual[parameter])

    def test_tampered_receipts_are_rejected_before_kernel_construction(self):
        valid = cost_year.convert_cost_year(self.source, 2022)
        patches = {
            'factor': 1.0, 'source_index': 100.0, 'target_index': 100.0,
            'index_snapshot_id': 'invented-snapshot', 'source_provisional': False,
            'target_provisional': True, 'target_year': 2024, 'source_year': 2025,
        }
        for key, value in patches.items():
            with self.subTest(key=key):
                invalid = deepcopy(valid)
                invalid['cost_year_adjustment'][key] = value
                with self.assertRaises(ValueError):
                    TechnoeconomicSubmissionRequest.model_validate(invalid)
        first = next(iter(valid['cost_year_adjustment']['original_money']))
        for case in ('missing', 'extra', 'changed_original', 'changed_submitted', 'family'):
            with self.subTest(case=case):
                invalid = deepcopy(valid)
                original = invalid['cost_year_adjustment']['original_money']
                if case == 'missing': original.pop(first)
                elif case == 'extra': original['not-a-cost-field'] = 1.0
                elif case == 'changed_original': original[first]['low'] *= 1.05
                elif case == 'changed_submitted': invalid['paired_commercial']['shared_initial_capex']['optimizer_unit_price_usd'] += 1
                else: original[first] = {'family':'fixed', 'value':1.0}
                with self.assertRaises(ValueError):
                    TechnoeconomicSubmissionRequest.model_validate(invalid)
        with self.assertRaises(ValueError): cost_year.convert_cost_year(self.source, 2030)
        old_year = deepcopy(self.source)
        old_year['finance']['constant_dollar_cost_year'] = 1946
        with self.assertRaises(ValueError): cost_year.convert_cost_year(old_year, 2022)
        legacy = deepcopy(valid)
        legacy.pop('paired_commercial')
        legacy['calculation_contract_version'] = 'tea-calculation-v2'
        with self.assertRaisesRegex(ValueError, 'only supported'):
            TechnoeconomicSubmissionRequest.model_validate(legacy)

    def test_old_requests_keep_canonical_shape_and_no_extra_provenance(self):
        old = presets.thursday_assumptions('annual-report-fixture')
        old['n'] = 128
        canonical = api.canonical_submission_request_payload(old)
        self.assertNotIn('cost_year_adjustment', canonical)
        explicit_none = {**deepcopy(old), 'cost_year_adjustment': None}
        self.assertEqual(canonical, api.canonical_submission_request_payload(explicit_none))
        snapshot = synthetic_snapshot()
        request = api.build_technoeconomic_kernel_request(canonical, snapshot)
        envelope = {'source_snapshot':snapshot, 'source_snapshot_sha256':api.canonical_json_sha256(snapshot)}
        provenance = api.build_technoeconomic_submission_provenance(canonical, envelope, request)
        self.assertNotIn('cost_year_adjustment_receipt', provenance)
        self.assertNotIn('cost_year_adjustment_receipt_sha256', provenance)
        self.assertEqual(provenance, api.build_technoeconomic_submission_provenance(explicit_none, envelope, request))

    def test_same_seed_costs_scale_while_weather_energy_and_rates_are_identical(self):
        converted = cost_year.convert_cost_year(self.source, 2022)
        factor = converted['cost_year_adjustment']['factor']
        snapshot = synthetic_snapshot()
        original_request = api.build_technoeconomic_kernel_request(self.source, snapshot)
        converted_request = api.build_technoeconomic_kernel_request(converted, snapshot)
        original = kernel.run_technoeconomic(original_request).realization_table
        changed = kernel.run_technoeconomic(converted_request).realization_table
        unchanged = [name for name in original if 'Energy' in name or name in {
            'realization_index', 'weather_year', 'SampledInput::finance.discount-rate',
            'SampledInput::energy.shared-degradation', 'AnnuityFactor_years', 'CapitalRecoveryFactor_per_year'}]
        self.assertGreater(len(unchanged), 10)
        for name in unchanged:
            np.testing.assert_array_equal(original[name], changed[name], err_msg=name)
        money = [name for name in original if 'USD' in name or name.startswith('SampledInput::capex.')
                 or name.endswith('.annual-om') or name.endswith('.full-capex')]
        self.assertGreater(len(money), 10)
        for name in money:
            np.testing.assert_allclose(np.asarray(original[name]) * factor, changed[name], rtol=2e-12, atol=1e-12, err_msg=name)
        envelope = {'source_snapshot':snapshot, 'source_snapshot_sha256':api.canonical_json_sha256(snapshot)}
        provenance = api.build_technoeconomic_submission_provenance(converted, envelope, converted_request)
        receipt = provenance['cost_year_adjustment_receipt']
        self.assertEqual(converted['cost_year_adjustment'], {key:value for key,value in receipt.items() if key != 'index_metadata'})
        self.assertEqual(api.canonical_json_sha256(receipt), provenance['cost_year_adjustment_receipt_sha256'])
        metadata = receipt['index_metadata']
        self.assertEqual('2026-Q2', metadata['source_observation']['period'])
        self.assertEqual('2022', metadata['target_observation']['period'])
        self.assertEqual(64, len(metadata['catalog_sha256']))
        self.assertIn('retrieved_at', metadata)
        self.assertIn('raw_sha256', metadata['sources']['annual'])


if __name__ == '__main__':
    unittest.main()
