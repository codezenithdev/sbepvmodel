from io import BytesIO
from pathlib import Path
import base64
import unittest
from unittest.mock import patch
from zipfile import ZipFile
import xml.etree.ElementTree as ET

from sbepv import technoeconomic_docx as docx
from sbepv import technoeconomic_docx_refresh as refresh


def document(figures=False):
    blocks = [{'kind': 'title', 'text': 'PV Comparison'}, {'kind': 'toc'},
              {'kind': 'heading', 'level': 1, 'number': '1', 'anchor': 'executive-summary', 'text': 'Executive Summary'},
              {'kind': 'paragraph', 'text': 'Saved results remain unchanged.'}]
    if figures:
        from PIL import Image
        buffer = BytesIO()
        Image.new('RGB', (20, 20), 'white').save(buffer, format='PNG')
        for index in range(1, 9):
            figure_id = 'fixture-' + str(index)
            blocks.append({'kind': 'paragraph', 'text': 'Figure ' + str(index),
                           'segments': [{'text': 'Figure '}, {'figure_ref': figure_id, 'text': str(index)}]})
            blocks.append({'kind': 'chart', 'figure_id': figure_id, 'figure_number': index,
                           'image': base64.b64encode(buffer.getvalue()).decode(), 'height': 30, 'caption': 'Fixture'})
    return docx.render_docx({'title': 'PV Comparison', 'version': '2.5',
        'analysis_name': 'Spring calibration applied to fall',
        'analysis_at': '2026-09-17T16:30:04+00:00',
        'blocks': blocks})


def edited_xml(payload, edit):
    output = BytesIO()
    with ZipFile(BytesIO(payload)) as source, ZipFile(output, 'w') as target:
        for item in source.infolist():
            value = source.read(item.filename)
            if item.filename == 'word/document.xml':
                root = ET.fromstring(value)
                edit(root)
                value = ET.tostring(root, encoding='utf-8', xml_declaration=True)
            target.writestr(item, value)
    return output.getvalue()


def fill_toc(root):
    for node in root.iter(refresh.W + 't'):
        if node.text and 'Open in Word and update' in node.text:
            node.text = '1 Executive Summary 2'


class WordRefreshTests(unittest.TestCase):
    def test_cached_contents_pages_must_match_rendered_heading_bookmarks(self):
        raw = document()
        def toc_with_page_link(root):
            for paragraph in root.iter(refresh.W + 'p'):
                style = paragraph.find(refresh.W + 'pPr/' + refresh.W + 'pStyle')
                if style is not None and style.get(refresh.W + 'val') == 'Heading1':
                    ET.SubElement(paragraph, refresh.W + 'bookmarkStart',
                                  {refresh.W + 'id': '2000', refresh.W + 'name': '__RefHeading_test'})
                    ET.SubElement(paragraph, refresh.W + 'bookmarkEnd', {refresh.W + 'id': '2000'})
                runs = [run for run in paragraph if run.tag == refresh.W + 'r']
                if not any('TOC ' in (node.text or '') for node in paragraph.iter(refresh.W + 'instrText')):
                    continue
                run = runs[0]
                for child in list(run):
                    if child.tag == refresh.W + 't' or (child.tag == refresh.W + 'fldChar' and child.get(refresh.W + 'fldCharType') == 'end'):
                        run.remove(child)
                link = ET.SubElement(paragraph, refresh.W + 'hyperlink', {refresh.W + 'anchor': '__RefHeading_test'})
                for text in ['1 Executive Summary', '2']:
                    ET.SubElement(ET.SubElement(link, refresh.W + 'r'), refresh.W + 't').text = text
                ET.SubElement(ET.SubElement(paragraph, refresh.W + 'r'), refresh.W + 'fldChar', {refresh.W + 'fldCharType': 'end'})
        refreshed = edited_xml(raw, toc_with_page_link)
        refresh.validate_refreshed_docx(raw, refreshed)
        refresh.validate_pagination(raw, refreshed, {'bookmark_pages': {'executive_summary': 2}})
        with self.assertRaisesRegex(refresh.DocxRefreshError, 'rendered heading pages'):
            refresh.validate_pagination(raw, refreshed, {'bookmark_pages': {'executive_summary': 3}})

    def test_active_footer_relationships_must_keep_native_page_fields(self):
        raw = document()
        def remove_footer_relationship(root):
            fill_toc(root)
            for section in root.iter(refresh.W + 'sectPr'):
                for reference in section.findall(refresh.W + 'footerReference'):
                    section.remove(reference)
        with self.assertRaisesRegex(refresh.DocxRefreshError, 'active report footer'):
            refresh.validate_refreshed_docx(raw, edited_xml(raw, remove_footer_relationship))

    def test_eight_figure_fields_and_reference_cache_agreement_are_required(self):
        raw = document(figures=True)
        refreshed = edited_xml(raw, fill_toc)
        refresh.validate_refreshed_docx(raw, refreshed)
        inventory = refresh.field_inventory(refreshed)
        kinds = [refresh._field_key(field['instruction'])[0] for field in inventory['fields']]
        self.assertEqual(8, kinds.count('SEQ'))
        self.assertEqual(8, kinds.count('REF'))
        def corrupt_reference(root):
            fill_toc(root)
            for paragraph in root.iter(refresh.W + 'p'):
                if any((node.text or '').strip().startswith('REF ') for node in paragraph.iter(refresh.W + 'instrText')):
                    list(paragraph.iter(refresh.W + 't'))[-1].text = '99'
                    break
        with self.assertRaisesRegex(refresh.DocxRefreshError, 'numbered captions'):
            refresh.validate_refreshed_docx(raw, edited_xml(raw, corrupt_reference))

    def test_raw_document_is_not_accepted_as_a_finished_export(self):
        raw = document()
        with self.assertRaisesRegex(refresh.DocxRefreshError, 'page numbers|placeholder'):
            refresh.validate_refreshed_docx(raw, raw)
        refreshed = edited_xml(raw, fill_toc)
        refresh.validate_refreshed_docx(raw, refreshed)

    def test_lost_bookmarks_and_heading_structure_are_rejected(self):
        raw = document()
        def remove_bookmark(root):
            fill_toc(root)
            for parent in root.iter():
                for child in list(parent):
                    if child.tag == refresh.W + 'bookmarkStart': parent.remove(child)
        with self.assertRaisesRegex(refresh.DocxRefreshError, 'bookmarks'):
            refresh.validate_refreshed_docx(raw, edited_xml(raw, remove_bookmark))
        def change_heading(root):
            fill_toc(root)
            for node in root.iter(refresh.W + 'pStyle'):
                if node.get(refresh.W + 'val') == 'Heading1': node.set(refresh.W + 'val', 'Normal')
        with self.assertRaisesRegex(refresh.DocxRefreshError, 'headings'):
            refresh.validate_refreshed_docx(raw, edited_xml(raw, change_heading))

    def test_missing_runtime_fails_clearly_without_silent_placeholder_export(self):
        with patch.dict('os.environ', {'PV_REPORT_SOFFICE': str(Path('missing-office-runtime.exe').resolve())}):
            with self.assertRaisesRegex(refresh.DocxRefreshError, 'PV_REPORT_SOFFICE'):
                refresh.refresh_docx_fields(document())

    def test_real_export_requires_finalization_after_report_verification(self):
        from sbepv import technoeconomic_pdf
        with patch.object(technoeconomic_pdf, 'prepare_report', return_value={'version': '2.5', 'run_id': 'tea_fixture', 'include_technical_appendix': True}) as prepare, \
             patch.object(docx, 'render_docx', return_value=b'raw') as render, \
             patch.object(refresh, 'refresh_docx_fields', return_value=b'finished') as finalize:
            result, name = docx.build_docx({'id': 'tea_fixture'}, analysis_name='Saved name')
            self.assertEqual(b'finished', result)
            finalize.assert_called_once_with(b'raw')
            self.assertEqual('Saved name', prepare.call_args.kwargs['analysis_name'])
            self.assertTrue(name.endswith('.docx'))

    def test_unavailable_engine_has_a_distinct_service_error(self):
        from sbepv.api import main as app, state
        with patch.object(app, '_require_supported_technoeconomic_job'), \
             patch.object(state.AGENT_STORE, 'get_technoeconomic_job', return_value={'id': 'tea_fixture'}), \
             patch.object(docx, 'build_docx', side_effect=refresh.DocxRefreshError('Configure PV_REPORT_SOFFICE')):
            with self.assertRaises(app.HTTPException) as caught:
                app.download_technoeconomic_docx('tea_fixture')
            self.assertEqual(503, caught.exception.status_code)
            self.assertIn('PV_REPORT_SOFFICE', caught.exception.detail)
