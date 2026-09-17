"""Tie the frozen currency-year index catalog to downloaded source observations."""
import csv
import hashlib
from importlib.resources import files
from io import StringIO
import json
import unittest


class CostIndexSnapshotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog=json.loads(files('sbepv').joinpath('data/gdp_deflator_2026_09_17.json').read_text(encoding='utf-8'))

    def test_annual_catalog_matches_frozen_bea_fred_download(self):
        source=self.catalog['sources']['annual']
        self.assertEqual('b4a07e87eae266f43afcc14e28d4bc091ab9cfc71b0348cfaf22246ba4f60da4',source['raw_sha256'])
        self.assertEqual(source['raw_sha256'],hashlib.sha256(source['raw_csv'].encode('utf-8')).hexdigest())
        rows=list(csv.DictReader(StringIO(source['raw_csv'])))
        self.assertEqual(list(range(1947,2026)),[int(row['observation_date'][:4]) for row in rows])
        for row in rows:
            year=row['observation_date'][:4]
            record=self.catalog['years'][year]
            self.assertEqual(float(row[source['series_id']]),record['value'])
            self.assertEqual(year,record['period'])
            self.assertEqual('annual',record['status'])
            self.assertFalse(record['provisional'])
        self.assertEqual({2022:118.023,2023:122.390,2024:125.428,2025:128.979},
                         {year:self.catalog['years'][str(year)]['value'] for year in (2022,2023,2024,2025)})

    def test_partial_2026_uses_only_published_quarter_and_no_future_years(self):
        source=self.catalog['sources']['quarterly']
        self.assertEqual('6614276db86aa01a2fbb4d069f0885fe34bb480f73f09b3b67180a5dd94c7586',source['raw_sha256'])
        self.assertEqual(source['raw_sha256'],hashlib.sha256(source['raw_csv'].encode('utf-8')).hexdigest())
        rows=list(csv.DictReader(StringIO(source['raw_csv'])))
        self.assertEqual({'observation_date':'2026-04-01','GDPDEF':'133.855'},rows[-1])
        proxy=self.catalog['years']['2026']
        self.assertEqual(float(rows[-1]['GDPDEF']),proxy['value'])
        self.assertEqual('2026-Q2',proxy['period'])
        self.assertEqual('quarterly_proxy',proxy['status'])
        self.assertTrue(proxy['provisional'])
        self.assertEqual(set(range(1947,2027)),set(map(int,self.catalog['years'])))
        self.assertEqual('2026-08-26',source['release_date'])


if __name__=='__main__':
    unittest.main()
