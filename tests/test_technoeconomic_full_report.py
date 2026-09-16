from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import shutil
import uuid
import unittest
import base64
from io import BytesIO
import json
from zipfile import ZipFile
from xml.etree import ElementTree
from unittest.mock import patch

import numpy as np
from fastapi.testclient import TestClient
from sbepv import model, technoeconomic as kernel, technoeconomic_pdf as pdf
from sbepv import technoeconomic_presets as presets, technoeconomic_reporting as reporting
from sbepv import technoeconomic_report as report_model, technoeconomic_docx as docx_report, technoeconomic_pdf_layout
from sbepv.api import config, state, security, main as app, technoeconomic as api
from sbepv.api.schemas import TechnoeconomicSubmissionRequest
from sbepv.worker import run_technoeconomic as worker


def synthetic_snapshot():
    rows = [{"year": year, "period_start": f"{year}-01-01", "period_end": f"{year}-12-31",
             "sol_predicted_kwh": 250_000 + 1000*(year-2012), "se_predicted_kwh": 262_500 + 1500*(year-2012),
             "row_count": 8760, "annual_coverage_pct": 100, "cdf_eligible": True}
            for year in range(2012,2022)]
    request = {"curtailment_enabled": True, "curtailment_limit_kw": 125, "interval_value": 1, "interval_unit": "hours"}
    stats = {"se_measured_kwh": 220, "sol_measured_kwh": 210, "se_predicted_kwh": 220, "sol_predicted_kwh": 210,
             "uncalibrated": {"se_predicted_kwh": 250, "sol_predicted_kwh": 245}}
    return {
        "schema_version": 1, "eligibility_version": api.ANNUAL_SOURCE_ELIGIBILITY_VERSION,
        "source_annual_job_id": "annual-report-fixture", "eligible_paired_energy_rows": rows,
        "excluded_annual_energy_rows": [], "capacity_manifest": model.capacity_manifest(),
        "source_annual_job": {"id": "annual-report-fixture", "request": request,
                              "result": {"annual_energy_by_year": rows}},
        "calibration_lineage": {
            "origin_validation_job": {"id": "synthetic-calibration", "request": request, "result": {"stats": stats}},
            "resolved_profile": {"seasonal_factors": {"winter": {"solaredge": .95,"solectria": .9}}},
            "data_quality": {"cleaning": {"decisions": [{"issue_id": "synthetic.issue", "action": "exclude", "affected_rows": 1}]}},
        },
    }


def kernel_case(n=128):
    payload = presets.thursday_assumptions("annual-report-fixture")
    payload["n"] = n
    payload = api.canonical_submission_request_payload(payload)
    snapshot = synthetic_snapshot()
    request = api.build_technoeconomic_kernel_request(payload, snapshot)
    provenance = api.build_technoeconomic_submission_provenance(payload, {
        "source_snapshot": snapshot, "source_snapshot_sha256": api.canonical_json_sha256(snapshot),
    }, request)
    return payload, snapshot, request, provenance


def completed_fixture(*, missing_lineage=False, project_life=None, transform_payload=None):
    payload, snapshot, request, provenance = kernel_case()
    if transform_payload is not None:
        transform_payload(payload)
    if project_life is not None:
        payload['finance']['project_life_years']=project_life
        payload['finance']['project_life_evidence']['citation']['excerpt_or_derivation_note']=f'Synthetic test case: {project_life} years.'
    if transform_payload is not None or project_life is not None:
        payload=api.canonical_submission_request_payload(payload)
        request=api.build_technoeconomic_kernel_request(payload,snapshot)
        provenance=api.build_technoeconomic_submission_provenance(payload,{
            'source_snapshot':snapshot,'source_snapshot_sha256':api.canonical_json_sha256(snapshot),
        },request)
    if missing_lineage:
        snapshot['calibration_lineage'] = {}
        provenance = api.build_technoeconomic_submission_provenance(payload, {
            'source_snapshot':snapshot,'source_snapshot_sha256':api.canonical_json_sha256(snapshot),
        },request)
    calculation = kernel.run_technoeconomic(request)
    digests = {"request_sha256": api.canonical_json_sha256(payload),
               "source_snapshot_sha256": api.canonical_json_sha256(snapshot),
               "submission_provenance_sha256": api.canonical_json_sha256(provenance)}
    artifact = worker._write_sealed_calculation_payload("tea_full_report", "report_lease", calculation, **digests, publish_check=lambda:None)
    path = config.OUTPUT_DIR / artifact["storage_key"]
    result = worker._routine_result(request,calculation,artifact,provenance)
    manifest = reporting.generate_technoeconomic_exports(
        job_id="tea_full_report", attempt_directory=path.parent, sealed_calculation_path=path,
        sealed_calculation_artifact=artifact, request_payload=payload, source_snapshot=snapshot,
        submission_provenance=provenance, routine_result=result, cancellation_check=lambda:None, publish_check=lambda:None)
    result["exports"] = worker._public_export_manifest(manifest)
    job = {"id":"tea_full_report", "state":"done", "request":payload, "source_snapshot":snapshot,
           "submission_provenance":provenance, "result":result, **digests,
           "result_provenance": {**digests, "routine_result_sha256":api.canonical_json_sha256(result)},
           "artifacts":{"sealed_calculation":artifact,"exports":manifest}}
    return job, calculation


class SharedCapexTests(unittest.TestCase):
    def test_primitive_pairing_costs_and_sensitivity(self):
        payload,snapshot,request,provenance = kernel_case(256)
        result = kernel.run_technoeconomic(request)
        table = result.realization_table
        base = np.asarray(table['SampledInput::capex.shared-base-wdc'])*134_000_000
        install = np.asarray(table['SampledInput::capex.optimizer-installation-wdc'])*134_000_000
        np.testing.assert_allclose(table[kernel.COMMERCIAL_PAIRED_SOLECTRIA_FIELD_INITIAL_COST],base,rtol=1e-14)
        np.testing.assert_allclose(table[kernel.COMMERCIAL_STANDALONE_FIELD_INITIAL_COST],base+install+3_891_156.75,rtol=1e-14)
        primitive_ids = {d.input_id for d in kernel.paired_primitive_distributions(request.paired_commercial)}
        self.assertNotIn('solectria.full-capex',primitive_ids)
        self.assertNotIn('solaredge.full-capex',primitive_ids)
        self.assertEqual(4,len(primitive_ids))
        self.assertIn('shared_initial_capex',provenance['paired_commercial_receipt'])
        for item in result.sensitivity.values():
            self.assertFalse(any(s.get('predictor_id','').endswith('.full-capex') for s in item.get('steps',())))

    def test_midpoints_and_independent_discounted_cashflows(self):
        payload,snapshot,_,_ = kernel_case(20)
        paired = payload['paired_commercial']; shared = paired['shared_initial_capex']
        shared['common_capex_wdc'] = {'family':'fixed','value':1.12}
        shared['optimizer_installation_wdc'] = {'family':'fixed','value':.007}
        for system in paired['systems']:
            for line in system['cost_lines']:
                line['distribution'] = {'family':'fixed','value':
                    (1.5008 if system['technology']=='solectria' else 1.5490915675)
                    if line['cost_category']=='full_initial_capex' else
                    (.01407 if system['technology']=='solectria' else .02010)}
        payload['finance']['real_discount_rate']['distribution']={'family':'fixed','value':.06}
        payload['shared_degradation']['annual_rate']['distribution']={'family':'fixed','value':.005}
        request=api.build_technoeconomic_kernel_request(payload,snapshot)
        table=kernel.run_technoeconomic(request).realization_table
        af=sum((1.06)**-year for year in range(1,31))
        ef=sum(.995**(year-1)/(1.06)**year for year in range(1,31))
        for initial,om,cost_field,energy_field,lcoe_field in (
            (150080000,1407000,kernel.COMMERCIAL_PAIRED_SOLECTRIA_FIELD_LIFECYCLE_COST,kernel.COMMERCIAL_PAIRED_SOLECTRIA_FIELD_YEAR1_ENERGY,kernel.COMMERCIAL_PAIRED_SOLECTRIA_FIELD_LCOE),
            (154909156.75,2010000,kernel.COMMERCIAL_STANDALONE_FIELD_LIFECYCLE_COST,kernel.COMMERCIAL_STANDALONE_FIELD_YEAR1_ENERGY,kernel.COMMERCIAL_STANDALONE_FIELD_LCOE)):
            np.testing.assert_allclose(table[cost_field],initial+om*af,rtol=1e-13)
            np.testing.assert_allclose(table[lcoe_field],(initial+om*af)/(np.asarray(table[energy_field])*ef),rtol=1e-13)
        self.assertEqual(9,len(pdf.independent_reference_checks()))

    def test_rejects_invalid_support_and_preserves_absent_serialization(self):
        payload,snapshot,_,_=kernel_case()
        changed=deepcopy(payload)
        changed['paired_commercial']['systems'][0]['cost_lines'][0]['distribution']['low']=.1
        with self.assertRaises(kernel.TechnoeconomicValidationError):
            api.build_technoeconomic_kernel_request(changed,snapshot)
        payload['paired_commercial'].pop('shared_initial_capex')
        serialized=TechnoeconomicSubmissionRequest.model_validate(payload).model_dump(mode='json',exclude_none=False)
        self.assertNotIn('shared_initial_capex',serialized['paired_commercial'])

    def test_optional_assumptions_status_preserves_historical_context_serialization(self):
        payload,_,_,_=kernel_case()
        context=payload['paired_commercial']['shared_initial_capex']['report_context']
        self.assertNotIn('assumptions_status',context)
        serialized=TechnoeconomicSubmissionRequest.model_validate(payload).model_dump(mode='json',exclude_none=False)
        self.assertEqual(context,serialized['paired_commercial']['shared_initial_capex']['report_context'])
        for status in ('approved_defaults','modified'):
            context['assumptions_status']=status
            serialized=api.canonical_submission_request_payload(payload)
            self.assertEqual(status,serialized['paired_commercial']['shared_initial_capex']['report_context']['assumptions_status'])
        context['assumptions_status']='unrecognized'
        with self.assertRaises(ValueError):
            TechnoeconomicSubmissionRequest.model_validate(payload)


class FullReportTests(unittest.TestCase):
    def setUp(self):
        self.test_root=Path(__file__).resolve().parent / ('.tea-pdf-' + uuid.uuid4().hex)
        self.test_root.mkdir()
        self.addCleanup(self.cleanup_files)
        self.patch=patch.object(config,'OUTPUT_DIR',self.test_root)
        self.patch.start(); self.addCleanup(self.patch.stop)

    def cleanup_files(self):
        if self.test_root.resolve().parent != Path(__file__).resolve().parent:
            raise AssertionError('Unsafe test cleanup path')
        shutil.rmtree(self.test_root)

    def test_complete_pdf_and_integrity_rejections(self):
        job,_=completed_fixture()
        original=deepcopy(job)
        payload,name=pdf.build_pdf(job,generated_at=datetime(2026,9,15,tzinfo=timezone.utc))
        self.assertTrue(payload.startswith(b'%PDF-'))
        self.assertEqual('LCOE_comparsion.pdf',name)
        self.assertIn(b'/Outlines',payload)
        self.assertIn(b'/Annots',payload)
        self.assertEqual(job,original)
        for field in ('source_snapshot','submission_provenance','result'):
            bad=deepcopy(job); bad[field]['tampered']=True
            for build in (pdf.build_pdf, docx_report.build_docx):
                with self.subTest(field=field, format=build.__module__),self.assertRaises(pdf.FullReportError): build(bad)
        bad=deepcopy(job);bad['state']='running'
        with self.assertRaises(pdf.FullReportError):pdf.build_pdf(bad)
        with patch.object(state.AGENT_STORE,'get_current_baseline',side_effect=AssertionError('Must not read live baseline'),create=True):
            again,_=pdf.build_pdf(job)
            self.assertTrue(again.startswith(b'%PDF-'))
        csv_path=config.OUTPUT_DIR/job['artifacts']['exports']['artifacts']['csv_bundle']['storage_key']
        csv_path.write_bytes(b'tampered')
        with self.assertRaises(pdf.artifacts.ArtifactIntegrityError):pdf.build_pdf(job)

    def test_pdf_route_uses_existing_auth_and_completed_guard(self):
        with patch.object(app,'_require_supported_technoeconomic_job'),patch.object(state.AGENT_STORE,'get_technoeconomic_job',return_value={'state':'running'}):
            for download in (app.download_technoeconomic_pdf,app.download_technoeconomic_docx):
                with self.assertRaises(app.HTTPException) as caught:download('tea_fixture')
                self.assertEqual(409,caught.exception.status_code)
        self.assertTrue(any(getattr(route,'path','').endswith('/exports/pdf') for route in app.app.routes))
        with patch.object(security,'_dashboard_basic_credentials',return_value=('test-user','test-password')):
            client=TestClient(app.app)
            for extension in ('pdf','docx'):
                response=client.get('/api/technoeconomic/jobs/tea_fixture/exports/'+extension)
                self.assertEqual(401,response.status_code)

    def test_missing_frozen_lineage_is_rejected_after_integrity_checks(self):
        job,_=completed_fixture(missing_lineage=True)
        with self.assertRaisesRegex(pdf.FullReportError,'lineage'):
            pdf.build_pdf(job)

    def test_word_and_pdf_share_values_images_and_native_navigation(self):
        job,_=completed_fixture()
        original=deepcopy(job)
        report=pdf.prepare_report(job,generated_at=datetime(2026,9,18,tzinfo=timezone.utc))
        self.assertTrue(any(job['request']['paired_commercial']['shared_initial_capex']['report_context']['limitations'] in block.get('text','') for block in report['blocks']))
        word=docx_report.render_docx(report)
        document_pdf=technoeconomic_pdf_layout.render_pdf(report)
        self.assertTrue(document_pdf.startswith(b'%PDF-'))
        self.assertEqual(job,original)
        self.assertIn('_2026-09-18_v2.2_',pdf.report_filename(report,'docx'))
        original_chart=(config.OUTPUT_DIR/job['artifacts']['exports']['artifacts']['cdf_plot']['storage_key']).read_bytes()
        charts=[block for block in report['blocks'] if block['kind']=='chart']
        self.assertTrue(any(base64.b64decode(block['image'])==original_chart for block in charts))
        self.assertFalse(any(block.get('anchor')=='sensitivity' for block in report['blocks']))
        self.assertTrue(any(block.get('anchor')=='lifecycle-comparison' for block in report['blocks']))
        with ZipFile(BytesIO(word)) as archive:
            xml=archive.read('word/document.xml')
            root=ElementTree.fromstring(xml)
            ns={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
            style_ids={node.attrib['{'+ns['w']+'}val'] for node in root.findall('.//w:pStyle',ns)}
            self.assertTrue({'Title','Heading1','Heading2'}.issubset(style_ids))
            self.assertIn(b'TOC ',xml)
            self.assertIn(b'w:bookmarkStart',xml)
            self.assertIn(b'w:tblHeader',xml)
            self.assertIn(b'updateFields',archive.read('word/settings.xml'))
            media={archive.read(name) for name in archive.namelist() if name.startswith('word/media/')}
            for block in report['blocks']:
                if block['kind']=='chart':self.assertIn(base64.b64decode(block['image']),media)
                elif block['kind']=='table':
                    for row in block['rows']:
                        for value in row:
                            if '\n' not in str(value):self.assertIn(str(value),''.join(root.itertext()))

    def test_optional_missing_values_and_long_content_remain_readable(self):
        job,_=completed_fixture()
        calculation,routine,checks=pdf.verified_report_evidence(job)
        presentation_job=deepcopy(job)
        snapshot=presentation_job['source_snapshot']
        snapshot['calibration_lineage']['origin_validation_job']['result']['stats'].pop('uncalibrated')
        snapshot['eligible_paired_energy_rows']=snapshot['eligible_paired_energy_rows'][:3]
        snapshot['excluded_annual_energy_rows']=[{'row':{'year':1990+i},'reasons':['Missing intervals with a long evidence explanation. '*8]} for i in range(12)]
        calculation.metadata['convergence']={'status':'unavailable','checkpoints':[]}
        report=report_model.build_report(presentation_job,calculation,routine,checks)
        text=json.dumps([{k:v for k,v in b.items() if k!='image'} for b in report['blocks']])
        self.assertIn('Annual percentiles are withheld',text)
        self.assertIn('completed-run lifecycle LCOE chart is unavailable',text)
        self.assertIn('Not available',text)
        self.assertNotIn('reasons: []',text)
        self.assertTrue(technoeconomic_pdf_layout.render_pdf(report).startswith(b'%PDF-'))
        self.assertTrue(docx_report.render_docx(report).startswith(b'PK'))
        # Presentation variants above never replace a completed job's evidence.
        self.assertEqual(len(job['source_snapshot']['eligible_paired_energy_rows']),10)

    def test_saved_chart_tampering_blocks_both_report_formats(self):
        job,_=completed_fixture()
        chart=config.OUTPUT_DIR/job['artifacts']['exports']['artifacts']['cdf_plot']['storage_key']
        chart.write_bytes(b'tampered chart')
        for build in (pdf.build_pdf,docx_report.build_docx):
            with self.assertRaises(pdf.artifacts.ArtifactIntegrityError):build(job)

    def test_annual_interpolation_matches_dashboard_ties_and_small_samples(self):
        x,p=report_model.annual_interpolation_points([4,2,1,2,float('nan')])
        np.testing.assert_array_equal(x,[1,2,4])
        np.testing.assert_array_equal(p,[.125,.5,.875])
        self.assertIsNone(report_model.annual_interpolation_points([1]))
        self.assertIsNone(report_model.annual_interpolation_points([1,1]))

    def test_display_zero_is_not_missing_and_dates_are_not_substituted(self):
        self.assertEqual('0.00',report_model.number(0))
        self.assertEqual('Not available',report_model.number(None))
        self.assertEqual('Not recorded',report_model.display_date('malformed-date'))
        self.assertNotEqual(report_model.distribution({'family':'fixed','value':0}),report_model.distribution(None))
        self.assertEqual('250 kWac',report_model.capacity(250000,'ac'))
        self.assertEqual('12.5 MWac',report_model.capacity(12500000,'ac'))
        self.assertIn('06:30',report_model.measured_window({'from_date':'2026-01-01','from_time':'06:30'},{}))

    def test_different_completed_inputs_produce_their_own_report_values(self):
        displayed=[]
        for life in (20,40):
            with patch.object(config,'OUTPUT_DIR',self.test_root / str(life)):
                job,_=completed_fixture(project_life=life)
                report=pdf.prepare_report(job)
            lcoe_table=next(block for block in report['blocks'] if block['kind']=='table' and block['headers'][0]=='LCOE (USD/MWh)')
            expected=job['result']['paired_commercial']['systems']['solectria']['percentiles']['p50']*1000
            self.assertEqual(report_model.number(expected),lcoe_table['rows'][0][2])
            self.assertIn(f'{life} years /',json.dumps([{k:v for k,v in b.items() if k!='image'} for b in report['blocks']]))
            displayed.append(lcoe_table['rows'][0][2])
        self.assertNotEqual(*displayed)

    def test_modified_year_and_shared_costs_reach_saved_results_and_report(self):
        note='Synthetic revised cost estimate: common CAPEX 1.30-1.40 USD/Wdc; declared real 2030 USD, with no inflation adjustment.'
        def modified_inputs(payload):
            payload['finance']['constant_dollar_cost_year']=2030
            paired=payload['paired_commercial']
            shared=paired['shared_initial_capex']
            shared['dc_capacity_w']=140_000_000
            shared['common_capex_wdc']={'family':'uniform','low':1.3,'high':1.4}
            shared['optimizer_count']=100_000
            shared['optimizer_unit_price_usd']=40
            context=shared['report_context']
            context['assumptions_status']='modified'
            context['component_allocations']=[]
            context['limitations']='Proposed real 2030-dollar basis; later vendor prices are unadjusted proxies. Major-maintenance coverage remains unresolved.'
            shared['evidence']['citation']['excerpt_or_derivation_note']=note
            ratio=1.4
            for system in paired['systems']:
                is_solaredge=system['technology']=='solaredge'
                for line in system['cost_lines']:
                    line['constant_dollar_cost_year']=2030
                    if line['cost_category']=='full_initial_capex':
                        line['distribution']={'family':'uniform',
                            'low':1.3*ratio+(.04+.004*ratio if is_solaredge else 0),
                            'high':1.4*ratio+(.04+.010*ratio if is_solaredge else 0)}
                    else:
                        low,high=(12,18) if is_solaredge else (8,13)
                        line['distribution']={'family':'uniform','low':low/1000*ratio,'high':high/1000*ratio}

        displayed=[]
        for scenario,transform in (('original',None),('modified',modified_inputs)):
            with patch.object(config,'OUTPUT_DIR',self.test_root / scenario):
                job,calculation=completed_fixture(transform_payload=transform)
                original=deepcopy(job)
                report=pdf.prepare_report(job)
                self.assertEqual(original,job)
                lcoe_table=next(block for block in report['blocks'] if block['kind']=='table' and block['headers'][0]=='LCOE (USD/MWh)')
                expected=job['result']['paired_commercial']['systems']['solectria']['percentiles']['p50']*1000
                self.assertEqual(report_model.number(expected),lcoe_table['rows'][0][2])
                displayed.append(expected)
                if scenario=='modified':
                    report_text=json.dumps([{k:v for k,v in block.items() if k!='image'} for block in report['blocks']])
                    self.assertIn('Modified assumptions',report_text)
                    self.assertIn('Proposed real 2030 USD',report_text)
                    self.assertIn(note,report_text)
                    self.assertIn('does not automatically inflation-adjust',report_text)
                    self.assertNotIn('Common CAPEX component allocations',report_text)
                    self.assertNotIn('Component allocations explain the base total',report_text)
                    table=calculation.realization_table
                    common=np.asarray(table['SampledInput::capex.shared-base-wdc'])*140_000_000
                    install=np.asarray(table['SampledInput::capex.optimizer-installation-wdc'])*140_000_000
                    np.testing.assert_allclose(table[kernel.COMMERCIAL_PAIRED_SOLECTRIA_FIELD_INITIAL_COST],common,rtol=1e-14)
                    np.testing.assert_allclose(table[kernel.COMMERCIAL_STANDALONE_FIELD_INITIAL_COST],common+install+4_000_000,rtol=1e-14)
                    self.assertTrue(technoeconomic_pdf_layout.render_pdf(report).startswith(b'%PDF-'))
        self.assertGreater(displayed[1],displayed[0])
