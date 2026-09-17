"""Explanations must reflect saved values and the reviewed scenario only."""
from copy import deepcopy
import unittest

from sbepv import technoeconomic_report as report


class ReportCorrectionTests(unittest.TestCase):
    def test_difference_uses_unrounded_saved_system_medians(self):
        systems = {
            'solaredge': {'percentiles': {'p50': .052852406000093616}},
            'solectria': {'percentiles': {'p50': .05029546884698233}},
        }
        original = deepcopy(systems)
        self.assertIn('$2.56/MWh lower', report.median_lcoe_comparison(systems))
        note = report.median_rounding_note(systems)
        self.assertIn('displayed medians gives $2.55/MWh', note)
        self.assertIn('unrounded saved medians rounds to $2.56/MWh', note)
        self.assertEqual(original, systems)
        exact = {'solaredge': {'percentiles': {'p50': .052}},
                 'solectria': {'percentiles': {'p50': .050}}}
        self.assertIsNone(report.median_rounding_note(exact))
        self.assertIsNone(report.median_rounding_note({}))

    def test_revision_note_requires_the_reviewed_saved_selections(self):
        request = {'n': 65000, 'cost_year_adjustment': {'source_year': 2024, 'target_year': 2020}}
        energy = {'frozen': {
            'calibration_application': {'seasonal_substitution': {
                'source_season': 'spring', 'target_season': 'fall', 'explicitly_accepted': True}},
            'seasonal_rows': [{'last_timestamp': '2026-09-15T23:00:00-06:00'}],
        }}
        note = report.reviewed_v24_comparison(request, energy)
        for required in ('v2.4', 'spring factors', 'September 15', '65,000', '10,000', '2024 USD', '2020 USD',
                         'cannot be attributed entirely to calibration'):
            self.assertIn(required, note)
        for modified in ({**request, 'n': 10000}, {**request, 'cost_year_adjustment': {}}):
            self.assertIsNone(report.reviewed_v24_comparison(modified, energy))
        changed = deepcopy(energy)
        changed['frozen']['seasonal_rows'][0]['last_timestamp'] = '2026-09-14T23:00:00-06:00'
        self.assertIsNone(report.reviewed_v24_comparison(request, changed))


if __name__ == '__main__':
    unittest.main()
