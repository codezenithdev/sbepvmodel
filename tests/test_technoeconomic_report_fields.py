"""Word editing contracts and linked PDF captions for the shared report model."""
from io import BytesIO
import unittest
from xml.etree import ElementTree
from zipfile import ZipFile

from sbepv import technoeconomic_docx as word
from sbepv import technoeconomic_pdf_layout as pdf


NS={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
W='{'+NS['w']+'}'
PNG='iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aXxkAAAAASUVORK5CYII='


def report_fixture():
    return {
        'title':'PV comparison', 'version':'2.5',
        'analysis_name':'Spring factors applied to fall',
        'analysis_at':'2026-09-17T08:20:00-06:00',
        'blocks':[
            {'kind':'title','text':'PV comparison'},
            {'kind':'toc'},
            {'kind':'heading','level':1,'number':'1','text':'Approach','anchor':'approach'},
            {'kind':'heading','level':2,'number':'1.1','text':'Annual Simulation','anchor':'annual'},
            {'kind':'paragraph','text':'Figure 1 shows annual energy.', 'segments':[
                {'text':'Figure '},{'figure_ref':'annual-energy','text':'1'},{'text':' shows annual energy.'}]},
            {'kind':'chart','figure_id':'annual-energy','figure_number':1,'image':PNG,'height':24,'caption':'Annual energy comparison.'},
        ],
    }


class ReportFieldsTests(unittest.TestCase):
    def test_word_uses_native_heading_caption_reference_and_page_fields(self):
        with ZipFile(BytesIO(word.render_docx(report_fixture()))) as archive:
            document=ElementTree.fromstring(archive.read('word/document.xml'))
            numbering=ElementTree.fromstring(archive.read('word/numbering.xml'))
            styles=ElementTree.fromstring(archive.read('word/styles.xml'))
            footer=ElementTree.fromstring(archive.read('word/footer1.xml'))
        instructions=[node.text.strip() for node in document.findall('.//w:instrText',NS)]
        self.assertIn('SEQ Figure \\* ARABIC',instructions)
        reference=next(value for value in instructions if value.startswith('REF '))
        reference_name=reference.split()[1]
        bookmarks={node.get(W+'name'):node.get(W+'id') for node in document.findall('.//w:bookmarkStart',NS)}
        self.assertIn(reference_name,bookmarks)
        ends={node.get(W+'id') for node in document.findall('.//w:bookmarkEnd',NS)}
        self.assertTrue(set(bookmarks.values()).issubset(ends))
        paragraphs=document.findall('.//w:p',NS)
        headings=[p for p in paragraphs if p.find("w:pPr/w:pStyle[@w:val='Heading1']",NS) is not None or p.find("w:pPr/w:pStyle[@w:val='Heading2']",NS) is not None]
        num_ids={p.find('w:pPr/w:numPr/w:numId',NS).get(W+'val') for p in headings}
        self.assertEqual(1,len(num_ids));self.assertNotIn('0',num_ids)
        num_id=num_ids.pop()
        abstract_id=numbering.find(f"w:num[@w:numId='{num_id}']/w:abstractNumId",NS).get(W+'val')
        definition=numbering.find(f"w:abstractNum[@w:abstractNumId='{abstract_id}']",NS)
        self.assertEqual(['%1','%1.%2','%1.%2.%3'],[node.get(W+'val') for node in definition.findall('w:lvl/w:lvlText',NS)])
        self.assertEqual(['Approach','Annual Simulation'],[''.join(p.itertext()) for p in headings])
        footer_text=''.join(footer.itertext())
        footer_display=''.join(node.text or '' for node in footer.findall('.//w:t',NS))
        self.assertIn('Spring factors applied to fall',footer_text)
        self.assertIn('Completed 2026-09-17 14:20 UTC',footer_text)
        self.assertIn('1/1',footer_display)
        self.assertNotIn('Page ',footer_text)
        self.assertNotIn(' of ',footer_text)
        self.assertEqual(['PAGE','NUMPAGES'],[node.text.strip() for node in footer.findall('.//w:instrText',NS)])
        stops=styles.findall("w:style[@w:styleId='Footer']/w:pPr/w:tabs/w:tab",NS)
        self.assertEqual([('right','10440')],[(node.get(W+'val'),node.get(W+'pos')) for node in stops])
        # A pPr must remain the first paragraph child, preceding all bookmarks.
        self.assertTrue(all(p[0].tag==W+'pPr' for p in headings))

    def test_pdf_references_resolve_and_long_names_fit_footer(self):
        report=report_fixture();report['analysis_name']='W'*120
        output=pdf.render_pdf(report)
        self.assertTrue(output.startswith(b'%PDF-'))
        self.assertIn('href="#figure-annual-energy"',pdf.paragraph_markup(report['blocks'][4]))
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.platypus import Paragraph
        footer=Paragraph(report['analysis_name'],ParagraphStyle('FooterTest',fontName='ReportSans',fontSize=8.5,leading=10,splitLongWords=True))
        self.assertLessEqual(footer.wrap(522,30)[1],20)

    def test_legacy_models_keep_unnumbered_headings_and_export_timestamp(self):
        report=report_fixture();report.pop('analysis_at');report.pop('analysis_name')
        report['generated_at']='2026-09-17T15:00:00+00:00'
        report['blocks']=report['blocks'][:4]
        for block in report['blocks']:
            block.pop('number',None)
        with ZipFile(BytesIO(word.render_docx(report))) as archive:
            document=ElementTree.fromstring(archive.read('word/document.xml'))
            footer=''.join(ElementTree.fromstring(archive.read('word/footer1.xml')).itertext())
        self.assertEqual({'0'},{node.get(W+'val') for node in document.findall('.//w:pPr/w:numPr/w:numId',NS)})
        self.assertIn('Exported 2026-09-17 15:00 UTC',footer)
        self.assertTrue(pdf.render_pdf(report).startswith(b'%PDF-'))

    def test_optional_appendix_captions_and_refs_resolve_without_stale_targets(self):
        for include_appendix in (False,True):
            with self.subTest(include_appendix=include_appendix):
                report=report_fixture()
                if include_appendix:
                    report['blocks'].extend([
                        {'kind':'heading','level':1,'number':'2','text':'Technical Appendix','anchor':'appendix'},
                        {'kind':'paragraph','text':'Figure 2 shows convergence.','segments':[
                            {'text':'Figure '},{'figure_ref':'convergence','text':'2'},{'text':' shows convergence.'}]},
                        {'kind':'chart','figure_id':'convergence','figure_number':2,'image':PNG,'height':24,'caption':'Convergence.'},
                    ])
                with ZipFile(BytesIO(word.render_docx(report))) as archive:
                    document=ElementTree.fromstring(archive.read('word/document.xml'))
                instructions=[node.text.strip() for node in document.findall('.//w:instrText',NS)]
                sequence=[value for value in instructions if value.startswith('SEQ Figure ')]
                refs=[value.split()[1] for value in instructions if value.startswith('REF ')]
                targets={node.get(W+'name') for node in document.findall('.//w:bookmarkStart',NS)}
                self.assertEqual(2 if include_appendix else 1,len(sequence))
                self.assertEqual(len(sequence),len(refs))
                self.assertEqual(len(refs),len(set(refs)))
                self.assertTrue(set(refs).issubset(targets))
                for paragraph in document.findall('.//w:p',NS):
                    if any((node.text or '').strip().startswith('REF ') for node in paragraph.findall('.//w:instrText',NS)):
                        self.assertIsNotNone(paragraph.find('w:pPr/w:keepNext',NS))
                self.assertTrue(pdf.render_pdf(report).startswith(b'%PDF-'))


if __name__=='__main__':
    unittest.main()
