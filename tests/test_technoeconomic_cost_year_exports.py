"""Dollar-year adjustments survive the existing verified report/export path."""
from copy import deepcopy
from io import BytesIO
from pathlib import Path
import shutil
import unittest
import uuid
from unittest.mock import patch
from zipfile import ZipFile

from fastapi.testclient import TestClient
from sbepv import technoeconomic_cost_year as currency
from sbepv import technoeconomic_presets as presets
from sbepv import technoeconomic_pdf as pdf, technoeconomic_docx as word
from sbepv import technoeconomic as kernel
from sbepv.api import config, main, security
from sbepv.api.schemas import TechnoeconomicSubmissionRequest
from tests.test_technoeconomic_full_report import completed_fixture


class CostYearExportTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parent / ('.tea-year-export-' + uuid.uuid4().hex)
        self.root.mkdir()
        self.addCleanup(shutil.rmtree, self.root)
        self.output_patch = patch.object(config, 'OUTPUT_DIR', self.root)
        self.output_patch.start()
        self.addCleanup(self.output_patch.stop)

    def test_current_basis_preserves_historical_preset_and_amounts(self):
        historical = presets.thursday_assumptions('annual-fixture')
        current = presets.current_assumptions('annual-fixture')
        self.assertEqual(2024, historical['finance']['constant_dollar_cost_year'])
        self.assertEqual(2026, current['finance']['constant_dollar_cost_year'])
        historical_money = currency.collect_money(historical)
        current_money = currency.collect_money(current)
        capex_path = 'paired_commercial.systems.solaredge.cost_lines.solaredge.full-capex.distribution'
        historical_capex = historical_money.pop(capex_path)
        current_capex = current_money.pop(capex_path)
        # The new quantity changes only derived SolarEdge CAPEX; unit prices,
        # common CAPEX, installation, O&M and component allocations keep their amounts.
        self.assertEqual(historical_money, current_money)
        self.assertEqual('uniform', current_capex['family'])
        for bound in ('low', 'high'):
            self.assertAlmostEqual((103_077 - 96_000) * 37.75 / 100_000_000,
                                   historical_capex[bound] - current_capex[bound])
        self.assertNotEqual(historical['paired_commercial']['shared_initial_capex']['report_context']['preset_id'],
                            current['paired_commercial']['shared_initial_capex']['report_context']['preset_id'])
        TechnoeconomicSubmissionRequest.model_validate(current)
        self.assertNotIn('cost_year_adjustment', current)

    def test_catalog_and_current_preset_use_existing_auth(self):
        with patch.object(security, '_dashboard_basic_credentials', return_value=('user','pass')):
            client = TestClient(main.app)
            for path in ('/api/technoeconomic/cost-year-indices',
                         '/api/technoeconomic/presets/user-cost-basis-2026-v1?source_annual_job_id=annual-fixture'):
                self.assertEqual(401, client.get(path).status_code)
                response = client.get(path, auth=('user','pass'))
                self.assertEqual(200, response.status_code)
                self.assertEqual('private, no-store', response.headers['cache-control'])
            catalog = client.get('/api/technoeconomic/cost-year-indices', auth=('user','pass')).json()
            self.assertTrue(catalog['years']['2026']['provisional'])
            self.assertEqual(133.855, catalog['years']['2026']['value'])

    def test_conversion_is_visible_in_both_exports_without_recalculation(self):
        def transform(payload):
            current = presets.current_assumptions(payload['source_annual_job_id'])
            current['n'] = payload['n']
            converted = currency.convert_cost_year(current, 2022)
            payload.clear()
            payload.update(converted)
        job, _ = completed_fixture(transform_payload=transform)
        original = deepcopy(job)
        with patch.object(kernel, 'run_technoeconomic', side_effect=AssertionError('Report cannot recalculate TEA')):
            report = pdf.prepare_report(job)
            pdf_bytes, _ = pdf.build_pdf(job, include_technical_appendix=False)
            word_bytes = word.render_docx(report)
        self.assertEqual(original, job)
        self.assertTrue(pdf_bytes.startswith(b'%PDF-'))
        text = ' '.join(str({key:value for key,value in block.items() if key not in ('image','vector')})
                        for block in report['blocks'])
        self.assertIn('converted from 2026 USD to 2022 USD', text)
        self.assertIn('2026 Q2', text)
        self.assertIn('provisional', text)
        self.assertNotIn('No price-index conversion is recorded', text)
        figures = [block for block in report['blocks'] if block['kind']=='chart']
        self.assertEqual(list(range(1,len(figures)+1)), [block['figure_number'] for block in figures])
        references = [segment['figure_ref'] for block in report['blocks'] for segment in block.get('segments',[])
                      if 'figure_ref' in segment]
        self.assertEqual([block['figure_id'] for block in figures], references)
        with ZipFile(BytesIO(word_bytes)) as archive:
            document = archive.read('word/document.xml')
            self.assertEqual(len(figures), document.count(b'SEQ Figure'))
            self.assertEqual(len(figures), document.count(b'REF fig_'))
            self.assertIn(b'converted from 2026 USD to 2022 USD', document)

    def test_same_year_adjustment_reads_as_no_op_not_a_conversion(self):
        def transform(payload):
            base = presets.thursday_assumptions(payload['source_annual_job_id'])
            base['n'] = payload['n']
            # Selecting the same 2024 dollar year records a multiplier-1.00
            # adjustment; the report must not claim a conversion occurred.
            converted = currency.convert_cost_year(base, 2024)
            payload.clear()
            payload.update(converted)
        job, _ = completed_fixture(transform_payload=transform)
        report = pdf.prepare_report(job)
        pdf_bytes, _ = pdf.build_pdf(job, include_technical_appendix=False)
        self.assertTrue(pdf_bytes.startswith(b'%PDF-'))
        text = ' '.join(str({key:value for key,value in block.items() if key not in ('image','vector')})
                        for block in report['blocks'])
        self.assertIn('No dollar-year conversion was applied', text)
        self.assertIn('both 2024', text)
        self.assertIn('This record documents the dollar basis', text)
        self.assertNotIn('converted from 2024 USD to 2024 USD', text)
        self.assertNotIn('The conversion changes the dollar basis', text)
