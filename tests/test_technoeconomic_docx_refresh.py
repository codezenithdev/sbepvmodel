from io import BytesIO
from pathlib import Path
import base64
import json
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


WRITER_NAMESPACES = ('xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
                     'xmlns:w14="http://schemas.microsoft.com/office/word/2010/wordml" '
                     'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" mc:Ignorable="w14"')
# Paragraph shapes LibreOffice Writer saves around report page breaks.
SEPARATOR = ('<w:p><w:pPr><w:pStyle w:val="Normal"/><w:rPr></w:rPr></w:pPr>'
             '<w:r><w:rPr></w:rPr></w:r><w:r><w:br w:type="page"/></w:r></w:p>')
HEADING = ('<w:p><w:pPr><w:pStyle w:val="Heading1"/><w:rPr></w:rPr></w:pPr><w:r><w:br w:type="page"/></w:r>'
           '<w:bookmarkStart w:id="1" w:name="executive_summary"/><w:r><w:rPr></w:rPr><w:t>Executive Summary</w:t></w:r>'
           '<w:bookmarkEnd w:id="1"/></w:p>')
SUBHEADING = ('<w:p><w:pPr><w:pStyle w:val="Heading2"/><w:pageBreakBefore w:val="false"/></w:pPr>'
              '<w:r><w:br w:type="page"/><w:t>Objectives</w:t></w:r></w:p>')
TRAILING = '<w:p><w:r><w:t>Saved results remain unchanged.</w:t></w:r><w:r><w:br w:type="page"/></w:r></w:p>'
CELL = '<w:tbl><w:tr><w:tc><w:p><w:r><w:br w:type="page"/><w:t>Cell</w:t></w:r></w:p></w:tc></w:tr></w:tbl>'


def writer_docx(body):
    output = BytesIO()
    with ZipFile(output, 'w') as archive:
        archive.writestr('[Content_Types].xml', '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        archive.writestr('word/document.xml', '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                         f'<w:document {WRITER_NAMESPACES}><w:body>{body}<w:sectPr/></w:body></w:document>')
        archive.writestr('word/styles.xml', f'<w:styles {WRITER_NAMESPACES}/>')
    return output.getvalue()


def page_breaks(paragraph):
    return [node for node in paragraph.iter(refresh.W + 'br') if node.get(refresh.W + 'type') == 'page']


class WordRefreshTests(unittest.TestCase):
    def test_temporary_profile_cleanup_retries_a_transient_windows_lock(self):
        class TemporaryProfile:
            name = 'isolated-profile'
            cleanups = 0

            def cleanup(self):
                self.cleanups += 1

        profile = TemporaryProfile()
        with patch.object(refresh.tempfile, 'TemporaryDirectory', return_value=profile), \
             patch.object(refresh.shutil, 'rmtree', side_effect=[PermissionError('Writer is releasing the profile'), None]) as remove, \
             patch.object(refresh.time, 'sleep') as sleep:
            with refresh._word_temporary_directory() as directory:
                self.assertEqual('isolated-profile', directory)
        self.assertEqual(2, remove.call_count)
        self.assertEqual(1, profile.cleanups)
        sleep.assert_called_once_with(.25)

    def test_cached_contents_pages_must_match_rendered_heading_bookmarks(self):
        raw = document()
        refreshed = edited_xml(raw, toc_with_page_link)
        refresh.validate_refreshed_docx(raw, refreshed)
        refresh.validate_pagination(raw, refreshed, {'bookmark_pages': {'executive_summary': 2}})
        with self.assertRaisesRegex(refresh.DocxRefreshError, 'rendered heading pages'):
            refresh.validate_pagination(raw, refreshed, {'bookmark_pages': {'executive_summary': 3}})

    def test_writer_page_break_at_paragraph_start_becomes_word_page_break_before(self):
        # Word keeps a numbered paragraph's label before an in-paragraph break, so
        # Writer's saved form would leave "1" on the contents page.
        writer = writer_docx(SEPARATOR + HEADING + SUBHEADING + TRAILING + CELL)
        moved = refresh.move_leading_page_breaks(writer)
        self.assertEqual(moved, refresh.move_leading_page_breaks(moved))
        with ZipFile(BytesIO(writer)) as before, ZipFile(BytesIO(moved)) as after:
            self.assertEqual(before.namelist(), after.namelist())
            self.assertEqual(['word/document.xml'], [name for name in before.namelist() if before.read(name) != after.read(name)])
            saved = after.read('word/document.xml')
        # Word rejects mc:Ignorable prefixes that are no longer declared.
        self.assertIn(b'xmlns:w14=', saved[:saved.index(b'<w:body>')])
        self.assertIn(b'mc:Ignorable="w14"', saved[:saved.index(b'<w:body>')])
        root = ET.fromstring(saved)
        separator, heading, subheading, trailing = root.find(refresh.W + 'body').findall(refresh.W + 'p')
        for paragraph, text in ((heading, 'Executive Summary'), (subheading, 'Objectives')):
            properties = paragraph.find(refresh.W + 'pPr')
            self.assertEqual([], page_breaks(paragraph))
            self.assertEqual(text, ''.join(node.text for node in paragraph.iter(refresh.W + 't')))
            self.assertEqual(refresh.W + 'pageBreakBefore', properties[1].tag)
            self.assertEqual({}, properties[1].attrib)
        self.assertEqual('executive_summary', heading.find(refresh.W + 'bookmarkStart').get(refresh.W + 'name'))
        for paragraph in (separator, trailing, root.find('.//' + refresh.W + 'tc/' + refresh.W + 'p')):
            self.assertEqual(1, len(page_breaks(paragraph)))
            self.assertIsNone(paragraph.find(refresh.W + 'pPr/' + refresh.W + 'pageBreakBefore'))

    def test_documents_without_paragraph_start_breaks_are_returned_unchanged(self):
        for payload in (document(), writer_docx(SEPARATOR + TRAILING + CELL)):
            self.assertEqual(payload, refresh.move_leading_page_breaks(payload))
        with self.assertRaisesRegex(refresh.DocxRefreshError, 'valid editable document'):
            refresh.move_leading_page_breaks(b'not a Word archive')

    def test_refresh_moves_writer_heading_break_before_verifying_the_export(self):
        raw = document()
        def writer_heading_break(root):
            toc_with_page_link(root)
            for paragraph in root.iter(refresh.W + 'p'):
                style = paragraph.find(refresh.W + 'pPr/' + refresh.W + 'pStyle')
                if style is not None and style.get(refresh.W + 'val') == 'Heading1':
                    run = ET.Element(refresh.W + 'r')
                    ET.SubElement(run, refresh.W + 'br', {refresh.W + 'type': 'page'})
                    paragraph.insert(1, run)
        writer = edited_xml(raw, writer_heading_break)

        class Office:
            def __init__(self, command, **options):
                self.pid, self.returncode = 0, 0
                if Path(command[1]).name == 'technoeconomic_uno_worker.py':
                    target, pdf, manifest = map(Path, command[4:7])
                    target.write_bytes(writer)
                    pdf.write_bytes(b'%PDF-1.7 fixture')
                    manifest.write_text(json.dumps({'page_count': 1, 'contents_stable': True,
                                                    'bookmark_pages': {'executive_summary': 2}}))

            def communicate(self, timeout=None):
                return b'', b''

            def poll(self):
                return 0

        with patch.object(refresh, 'office_runtime', return_value=('soffice', 'python')), \
             patch.object(refresh.subprocess, 'Popen', Office):
            finished = refresh.refresh_docx_fields(raw)
        with ZipFile(BytesIO(finished)) as archive:
            root = ET.fromstring(archive.read('word/document.xml'))
        heading = next(paragraph for paragraph in root.iter(refresh.W + 'p')
                       if paragraph.find(refresh.W + 'pPr/' + refresh.W + 'pStyle[@' + refresh.W + 'val="Heading1"]') is not None)
        self.assertEqual([], page_breaks(heading))
        self.assertEqual({}, heading.find(refresh.W + 'pPr/' + refresh.W + 'pageBreakBefore').attrib)

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
