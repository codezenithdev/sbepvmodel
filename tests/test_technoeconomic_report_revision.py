"""Cliff's report revisions preserve saved values and editable references."""
from copy import deepcopy
import hashlib
from importlib.resources import files
import json
import unittest

from sbepv import technoeconomic_report as report
from sbepv import technoeconomic_report_appendix as appendix
from sbepv import technoeconomic_docx as word
from sbepv import technoeconomic_docx_refresh as refresh
from sbepv import technoeconomic_pdf_layout as pdf
from tests.test_technoeconomic_report_fields import report_fixture
from tests.test_technoeconomic_docx_refresh import edited_xml, fill_toc


class RevisionTests(unittest.TestCase):
    def test_exclusions_are_distinct_intervals_not_summed_issue_counts(self):
        cleaning = {'original_rows': 6671, 'excluded_rows': 976, 'final_rows': 5695,
                    'decisions': [{'action': 'exclude', 'affected_rows': count}
                                  for count in (1,56,52,444,54,375,841,661,9,15,16)]}
        cleaning['decisions'].append({'action': 'retain', 'affected_rows': 200})
        original = deepcopy(cleaning)
        text = ' '.join(report.quality_count_explanation(cleaning))
        for value in ('6,671', '976', '5,695', '2,524', '1,548'):
            self.assertIn(value, text)
        self.assertEqual(original, cleaning)
        self.assertEqual([], report.quality_count_explanation({}))
        cleaning['final_rows'] = 100
        self.assertIn('do not reconcile', ' '.join(report.quality_count_explanation(cleaning)))

    def test_tables_renumber_and_native_references_survive_refresh(self):
        for include_appendix in (False, True):
            model = report_fixture()
            model['blocks'][2]['text'] = 'Executive Summary'
            model['blocks'].append({'kind':'table','headers':['LCOE (USD/MWh)','P50'],
                                    'rows':[['Solectria','50.00']], 'keep':True})
            if include_appendix:
                model['blocks'].extend([
                    {'kind':'heading','level':1,'anchor':'appendix','text':'Appendix'},
                    {'kind':'table','headers':['Equation','Meaning'],'rows':[['E=P t','Energy']]}])
            report._caption_report_tables(model['blocks'])
            report._number_report_blocks(model['blocks'])
            tables = [block for block in model['blocks'] if block['kind']=='table']
            self.assertEqual(list(range(1,len(tables)+1)),[b['table_number'] for b in tables])
            refs = [s for b in model['blocks'] for s in b.get('segments',[]) if s.get('table_ref')]
            self.assertEqual({b['table_id'] for b in tables},{s['table_ref'] for s in refs})
            raw = word.render_docx(model)
            def populate_toc(root):
                fill_toc(root)
                if include_appendix:
                    for node in root.iter(refresh.W+'t'):
                        if node.text=='1 Executive Summary 2': node.text += ' 2 Appendix 3'
            refreshed = edited_xml(raw,populate_toc)
            refresh.validate_refreshed_docx(raw,refreshed)
            self.assertTrue(pdf.render_pdf(model).startswith(b'%PDF-'))
            def corrupt_reference(root):
                populate_toc(root)
                for paragraph in root.iter(refresh.W+'p'):
                    if any('REF tbl_' in (n.text or '') for n in paragraph.iter(refresh.W+'instrText')):
                        for run in paragraph.iter(refresh.W+'r'):
                            if any('REF tbl_' in (n.text or '') for n in run.iter(refresh.W+'instrText')):
                                next(run.iter(refresh.W+'t')).text='99'
                                return
            with self.assertRaisesRegex(refresh.DocxRefreshError,'numbered captions'):
                refresh.validate_refreshed_docx(raw,edited_xml(raw,corrupt_reference))

    def test_presentation_assets_have_recorded_provenance(self):
        resources=files('sbepv').joinpath('data','report')
        manifest=json.loads(resources.joinpath('sources.json').read_text())
        self.assertEqual(8,manifest['figure_slide'])
        for name,record in manifest['assets'].items():
            self.assertEqual(record['sha256'],hashlib.sha256(resources.joinpath(name).read_bytes()).hexdigest())

    def test_seasonal_energy_table_is_not_captioned_as_calibration_factors(self):
        blocks=[{'kind':'table','headers':['Season','Measured gap (MWh)'],
                 'rows':[['Winter','1.20']]},
                {'kind':'table','headers':['Season','Solectria factor','SolarEdge factor','Factor source'],
                 'rows':[['Winter','.90','.95','Saved applied calibration']]}]
        report._caption_report_tables(blocks)
        captions=[b['caption'] for b in blocks if b['kind']=='table']
        self.assertIn('energy differences',captions[0])
        self.assertIn('calibration factors',captions[1])

    def test_partial_fall_coverage_is_not_described_as_absent(self):
        lineage={'resolved_profile':{'seasonal_factors':{'fall':{'solectria':.94,'solaredge':.93}}},
                 'origin_profile':{'fit_metadata':{'seasons':[{'season':'fall','row_count':360,
                    'first_timestamp':'2026-09-01T00:00:00','last_timestamp':'2026-09-15T23:00:00'}]}},
                 'application':{'seasonal_substitution':{'source_season':'spring','target_season':'fall','explicitly_accepted':True}}}
        original=deepcopy(lineage)
        blocks=appendix.applied_calibration_blocks({'source_snapshot':{'calibration_lineage':lineage}})
        self.assertEqual(1,sum(b['kind']=='table' for b in blocks))
        self.assertFalse(any(b['kind']=='heading' for b in blocks))
        self.assertIn('not absent',' '.join(b.get('text','') for b in blocks))
        self.assertEqual(original,lineage)


if __name__=='__main__':
    unittest.main()
