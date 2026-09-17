"""Report names remain display metadata and never change a saved calculation."""
from copy import deepcopy
import json
from pathlib import Path
import shutil
import subprocess
import unittest
from unittest.mock import patch
from urllib.parse import unquote

from fastapi.testclient import TestClient

from sbepv import technoeconomic_docx, technoeconomic_pdf, technoeconomic_pdf_layout, technoeconomic_docx_refresh
from sbepv.api import main as app, security, state
from sbepv.technoeconomic_report_metadata import normalize_analysis_name


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class ReportMetadataTests(unittest.TestCase):
    def test_report_download_filename_uses_safe_analysis_name(self):
        report = {'version': '2.5.1', 'run_id': 'tea_123', 'include_technical_appendix': True}
        for extension in ('pdf', 'docx'):
            for name, expected in (
                ('Lcoe report', 'Lcoe report'),
                ('  Spring\n factors & étude  ', 'Spring factors & étude'),
                ('../LCOE: "A/B" <2026>\\?', '_LCOE_ _A_B_ _2026___'),
                ('CON', '_CON'),
                ('LPT1.summary', '_LPT1.summary'),
                ('  Report.  ', 'Report'),
            ):
                with self.subTest(extension=extension, name=name):
                    named = {**report, 'analysis_name': name}
                    original = deepcopy(named)
                    self.assertEqual(expected + '.' + extension,
                                     technoeconomic_pdf.report_filename(named, extension))
                    self.assertEqual(original, named)
            for name in (None, '', '   ', '...', 'TEA tea_123'):
                for appendix, scope in ((True, 'full'), (False, 'summary')):
                    with self.subTest(extension=extension, name=name, appendix=appendix):
                        self.assertEqual(f'LCOE_Comparison_v2.5.1_{scope}_tea_123.{extension}',
                            technoeconomic_pdf.report_filename(
                                {**report, 'analysis_name': name, 'include_technical_appendix': appendix}, extension))
            long_name = technoeconomic_pdf.report_filename({**report, 'analysis_name': '☀' * 120}, extension)
            self.assertLessEqual(len(long_name.encode('utf-8')), 255)
            self.assertTrue(long_name.startswith('☀'))
            self.assertTrue(long_name.endswith('.' + extension))

    def test_export_routes_deliver_analysis_name_in_download_header(self):
        saved = {'id': 'tea_123', 'state': 'done', 'request': {'seed': 42}, 'result': {'n': 10}}
        original = deepcopy(saved)
        client = TestClient(app.app)
        with patch.object(security, '_dashboard_basic_credentials', return_value=None), \
             patch.object(app, '_require_supported_technoeconomic_job'), \
             patch.object(state.AGENT_STORE, 'get_technoeconomic_job', return_value=saved), \
             patch.object(technoeconomic_pdf, 'prepare_report') as prepare, \
             patch.object(technoeconomic_pdf_layout, 'render_pdf', return_value=b'%PDF-fixture'), \
             patch.object(technoeconomic_docx, 'render_docx', return_value=b'word-fixture'), \
             patch.object(technoeconomic_docx_refresh, 'refresh_docx_fields', side_effect=lambda payload: payload):
            for extension in ('pdf', 'docx'):
                for name in ('Lcoe report', 'Étude solaire 太阳 ☀', 'LCOE 100% complete'):
                    for appendix in (True, False):
                        with self.subTest(extension=extension, name=name, appendix=appendix):
                            prepare.return_value = {'analysis_name': name, 'run_id': 'tea_123',
                                                    'version': '2.5.1', 'include_technical_appendix': appendix}
                            response = client.get('/api/technoeconomic/jobs/tea_123/exports/' + extension,
                                params={'analysis_name': name, 'include_technical_appendix': str(appendix).lower()})
                            self.assertEqual(200, response.status_code, response.text)
                            disposition = response.headers['content-disposition']
                            self.assertTrue(disposition.startswith('attachment; '))
                            if "filename*=utf-8''" in disposition:
                                filename = unquote(disposition.split("filename*=utf-8''", 1)[1])
                            else:
                                filename = disposition.split('filename="', 1)[1].rstrip('"')
                            self.assertEqual(name + '.' + extension, filename)
                            self.assertEqual('private, no-store', response.headers['cache-control'])
                            self.assertEqual(original, saved)

    def test_name_normalization_and_boundaries(self):
        self.assertEqual('Spring factors • étude', normalize_analysis_name('  Spring\n factors\t • étude  '))
        self.assertEqual('TEA tea_123', normalize_analysis_name(' \n\t ', run_id='tea_123'))
        self.assertEqual('TEA tea_123', normalize_analysis_name(None, run_id='tea_123'))
        self.assertEqual('é' * 120, normalize_analysis_name('é' * 120))
        for value in ('x' * 121, 'bad\0name', 'bad\x7fname', 'bad\u202ename', 12, {}, []):
            with self.subTest(value=repr(value)), self.assertRaises(ValueError):
                normalize_analysis_name(value)

    def test_routes_forward_report_name_and_do_not_modify_job(self):
        saved = {'id': 'tea_123', 'state': 'done', 'request': {'seed': 42}, 'result': {'n': 10}}
        original = deepcopy(saved)
        client = TestClient(app.app)
        with patch.object(security, '_dashboard_basic_credentials', return_value=None), \
             patch.object(app, '_require_supported_technoeconomic_job'), \
             patch.object(state.AGENT_STORE, 'get_technoeconomic_job', return_value=saved):
            for extension, module, method in (
                ('pdf', technoeconomic_pdf, 'build_pdf'), ('docx', technoeconomic_docx, 'build_docx'),
            ):
                with patch.object(module, method, return_value=(b'file', 'report.' + extension)) as render:
                    response = client.get('/api/technoeconomic/jobs/tea_123/exports/' + extension,
                        params={'analysis_name': '  Spring\n factors & étude  ', 'include_technical_appendix': 'false'})
                    self.assertEqual(200, response.status_code, response.text)
                    render.assert_called_once_with(saved, include_technical_appendix=False,
                                                   analysis_name='Spring factors & étude')
                    self.assertEqual(saved, original)
                    self.assertEqual('private, no-store', response.headers['cache-control'])
                    render.reset_mock()
                    response = client.get('/api/technoeconomic/jobs/tea_123/exports/' + extension,
                                          params={'analysis_name': '  '})
                    self.assertEqual(200, response.status_code)
                    render.assert_called_once_with(saved, include_technical_appendix=True,
                                                   analysis_name='TEA tea_123')

    def test_invalid_names_are_rejected_before_loading_or_rendering(self):
        client = TestClient(app.app)
        with patch.object(security, '_dashboard_basic_credentials', return_value=None), \
             patch.object(state.AGENT_STORE, 'get_technoeconomic_job') as fetch:
            for extension in ('pdf', 'docx'):
                for value in ('x' * 121, 'x\0y', 'x\u202ey'):
                    response = client.get('/api/technoeconomic/jobs/tea_123/exports/' + extension,
                                          params={'analysis_name': value})
                    self.assertEqual(422, response.status_code, response.text)
            for invalid_type in (123, {}, []):
                with self.assertRaises(app.HTTPException) as caught:
                    app.download_technoeconomic_pdf('tea_123', analysis_name=invalid_type)
                self.assertEqual(422, caught.exception.status_code)
            fetch.assert_not_called()

    @unittest.skipUnless(shutil.which('node'), 'Node.js is required')
    def test_frontend_keeps_names_per_job_and_outside_calculation_inputs(self):
        script = (PROJECT_ROOT / 'frontend/js/06-technoeconomic.js').read_text(encoding='utf-8')
        assertions = r"""
const assert = require('node:assert/strict');
const values = new Map();
globalThis.localStorage = {
  getItem: (key) => values.get(key) ?? null,
  setItem: (key, value) => values.set(key, value),
};
const link = () => ({hidden: true, removeAttribute(key) { delete this[key]; }});
technoeconomicElements = {
  standalonePdfLink: link(), reportNameOption: {},
  analysisName: {value: '', setCustomValidity(value) { this.error = value; }},
};
const job = {job_id: 'tea_one', state: 'done',
  result: {calculation_contract_version: TECHNOECONOMIC_PAIRED_CONTRACT_VERSION}};
const original = JSON.stringify(job);
technoeconomicRenderReportDownloads(job);
assert.equal(technoeconomicElements.analysisName.value, 'TEA tea_one');
technoeconomicElements.analysisName.value = '  Spring factors & étude <A>  ';
technoeconomicPersistReportName();
technoeconomicRenderReportDownloads(job);
const url = new URL(technoeconomicElements.standalonePdfLink.href, 'https://example.test');
assert.equal(url.pathname, '/api/technoeconomic/jobs/tea_one/exports/pdf');
assert.equal(url.searchParams.get('analysis_name'), 'Spring factors & étude <A>');
assert.equal(url.searchParams.get('include_technical_appendix'), 'true');
assert.equal(technoeconomicElements.analysisName.value, '  Spring factors & étude <A>  ');
technoeconomicRenderReportDownloads({...job, job_id: 'tea_two'});
assert.equal(technoeconomicElements.analysisName.value, 'TEA tea_two');
technoeconomicRenderReportDownloads(job);
assert.equal(technoeconomicElements.analysisName.value, '  Spring factors & étude <A>  ');
technoeconomicReportNames.clear();
technoeconomicRenderReportDownloads(null);
assert.equal(technoeconomicElements.reportNameOption.hidden, true);
technoeconomicRenderReportDownloads(job);
assert.equal(technoeconomicElements.analysisName.value, '  Spring factors & étude <A>  ');
technoeconomicElements.analysisName.value = '  ';
technoeconomicRenderReportDownloads(job);
assert.equal(new URL(technoeconomicElements.standalonePdfLink.href, 'https://example.test')
  .searchParams.get('analysis_name'), 'TEA tea_one');
technoeconomicElements.analysisName.value = 'x'.repeat(121);
technoeconomicRenderReportDownloads(job);
assert.equal(technoeconomicElements.standalonePdfLink.hidden, true);
assert.ok(technoeconomicElements.analysisName.error);
technoeconomicElements.analysisName.value = '\ud800';
technoeconomicRenderReportDownloads(job);
assert.equal(technoeconomicElements.standalonePdfLink.hidden, true);
assert.equal(JSON.stringify(job), original);
assert.equal([...values.keys()].every((key) => key.startsWith(TECHNOECONOMIC_REPORT_NAME_STORAGE_PREFIX)), true);
console.log(JSON.stringify({passed: true}));
"""
        result = subprocess.run([shutil.which('node'), '-'], input=script + '\n' + assertions,
                                cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=30)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertTrue(json.loads(result.stdout)['passed'])
        # Report controls bubble through the TEA form; both handlers must exclude them.
        initializer = script.split('function initializeTechnoeconomicWorkspace', 1)[1]
        self.assertEqual(2, initializer.count('event.target === technoeconomicElements.analysisName) return;'))

    @unittest.skipUnless(shutil.which('node'), 'Node.js is required')
    def test_report_name_events_save_reload_and_ignore_stale_appendix_preference(self):
        script = (PROJECT_ROOT / 'frontend/js/06-technoeconomic.js').read_text(encoding='utf-8')
        assertions = r"""
const assert = require('node:assert/strict');
const values = new Map();
const reads = [];
globalThis.localStorage = {getItem(key){reads.push(key);return values.get(key)??null;},setItem:(key,value)=>values.set(key,value)};
const control=options=>({...options,handlers:{},addEventListener(kind,callback){this.handlers[kind]=callback;}});
const link=()=>({hidden:true,removeAttribute(key){delete this[key];}});
technoeconomicElements={
  standalonePdfLink:link(),reportNameOption:{},analysisNameSaveStatus:{textContent:''},
  analysisName:control({value:'',setCustomValidity(value){this.error=value;},reportValidity(){return !this.error;}}),
};
const first={job_id:'tea_4313e2de43d8421cbf55e17b49f021de',state:'done',result:{calculation_contract_version:TECHNOECONOMIC_PAIRED_CONTRACT_VERSION}};
const second={...first,job_id:'tea_other'};
const staleAppendixKey='sbepv.technoeconomic.report-appendix.v1.'+first.job_id;
values.set(staleAppendixKey,'false');
const original=JSON.stringify(first);
const source=require('node:fs').readFileSync('frontend/js/06-technoeconomic.js','utf8');
const start=source.indexOf("technoeconomicElements.analysisName?.addEventListener('input'");
const end=source.indexOf("document.getElementById('technoeconomicRestoreApprovedBtn')",start);
eval(source.slice(start,end));
const urlFor=(name)=>{
  const link=technoeconomicElements.standalonePdfLink;
  assert.equal(link.hidden,false);
  const url=new URL(link.href,'https://example.test');
  assert.equal(url.pathname,`/api/technoeconomic/jobs/${technoeconomicJob.job_id}/exports/pdf`);
  assert.equal(url.searchParams.get('analysis_name'),name);
  assert.equal(url.searchParams.get('include_technical_appendix'),'true');
};
technoeconomicJob=first;technoeconomicRenderReportDownloads(first);
urlFor('TEA '+first.job_id);
technoeconomicElements.analysisName.value='Spring calibration applied to fall';
technoeconomicElements.analysisName.handlers.input();
assert.equal(technoeconomicElements.analysisNameSaveStatus.textContent,'Saved in this browser.');
urlFor('Spring calibration applied to fall');
let prevented=false;technoeconomicElements.analysisName.handlers.keydown({key:'Enter',preventDefault(){prevented=true;}});
assert.equal(prevented,true);
technoeconomicJob=second;technoeconomicRenderReportDownloads(second);
urlFor('TEA tea_other');
technoeconomicJob=first;technoeconomicRenderReportDownloads(first);
urlFor('Spring calibration applied to fall');
// Reset in-memory report state, as on reload; legacy preferences remain in storage.
const reload=()=>{
  technoeconomicReportNames.clear();technoeconomicReportNameSaveStates.clear();
  technoeconomicRenderReportDownloads(null);
  technoeconomicElements.analysisName.value='';
  technoeconomicRenderReportDownloads(first);
};
reload();urlFor('Spring calibration applied to fall');
assert.equal(technoeconomicElements.analysisName.value,'Spring calibration applied to fall');
assert.equal(technoeconomicElements.analysisNameSaveStatus.textContent,'Saved in this browser.');
technoeconomicElements.analysisName.value='invalid\u0000name';technoeconomicElements.analysisName.handlers.input();
assert.equal(technoeconomicElements.standalonePdfLink.hidden,true);
assert.equal(technoeconomicElements.analysisNameSaveStatus.textContent,'Enter a valid analysis name to save it and enable downloads.');
reload();urlFor('Spring calibration applied to fall');
assert.equal(reads.includes(staleAppendixKey),false);
assert.equal(values.get(staleAppendixKey),'false');
globalThis.localStorage={getItem(){throw new Error('blocked');},setItem(){throw new Error('blocked');}};
technoeconomicElements.analysisName.value='Temporary name';technoeconomicElements.analysisName.handlers.input();
assert.equal(technoeconomicElements.analysisNameSaveStatus.textContent,'Available for this visit; browser storage is unavailable.');
urlFor('Temporary name');
assert.equal(JSON.stringify(first),original);
console.log(JSON.stringify({passed:true}));
"""
        result = subprocess.run([shutil.which('node'), '-'], input=script + '\n' + assertions,
                                cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=30)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertTrue(json.loads(result.stdout)['passed'])


if __name__ == '__main__':
    unittest.main()
