"""Editable Word rendering of exactly the same verified report blocks as PDF."""
import base64
from io import BytesIO


def render_docx(report):
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK, WD_TAB_ALIGNMENT
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Inches, Pt, RGBColor

    document=Document()
    for border in document.styles.element.xpath('.//w:pBdr'):
        border.getparent().remove(border)
    section=document.sections[0]
    section.page_width=Inches(8.5);section.page_height=Inches(11)
    section.left_margin=section.right_margin=Pt(45)
    section.top_margin=Pt(42);section.bottom_margin=Pt(43)
    section.header_distance=section.footer_distance=Pt(19)
    for style_name,size in (('Normal',11),('Title',25),('Subtitle',11),('Heading 1',19),('Heading 2',12),('Heading 3',11)):
        style=document.styles[style_name]
        style.font.name='Arial';style.font.size=Pt(size);style.font.color.rgb=RGBColor(0,0,0)
        style.paragraph_format.space_after=Pt(7)
        style.paragraph_format.line_spacing=1.1
        if style_name.startswith('Heading') or style_name=='Title':
            style.font.bold=True;style.paragraph_format.keep_with_next=True
    document.styles['Normal'].paragraph_format.widow_control=True
    document.styles['Heading 1'].paragraph_format.space_before=Pt(8)
    document.styles['Title'].paragraph_format.space_before=Pt(0)
    outline=OxmlElement('w:outlineLvl');outline.set(qn('w:val'),'0')
    document.styles['Title'].element.get_or_add_pPr().append(outline)
    document.core_properties.title=report['title']
    document.core_properties.author='SBE PV Dashboard'
    document.core_properties.subject='Calibration annual simulation and technoeconomic comparison'
    document.core_properties.version=report['version']
    def field(paragraph,instruction,placeholder=''):
        run=paragraph.add_run()
        begin=OxmlElement('w:fldChar');begin.set(qn('w:fldCharType'),'begin');begin.set(qn('w:dirty'),'true')
        code=OxmlElement('w:instrText');code.set(qn('xml:space'),'preserve');code.text=' '+instruction+' '
        separate=OxmlElement('w:fldChar');separate.set(qn('w:fldCharType'),'separate')
        result=OxmlElement('w:t');result.text=placeholder
        end=OxmlElement('w:fldChar');end.set(qn('w:fldCharType'),'end')
        for item in (begin,code,separate,result,end):run._r.append(item)
    footer=section.footer.paragraphs[0]
    footer.paragraph_format.tab_stops.add_tab_stop(Pt(522),WD_TAB_ALIGNMENT.RIGHT)
    footer.add_run(f"PV comparison  |  Report v{report['version']}\tPage ")
    field(footer,'PAGE');footer.add_run(' of ');field(footer,'NUMPAGES')
    for run in footer.runs:run.font.size=Pt(9)
    update=OxmlElement('w:updateFields');update.set(qn('w:val'),'true');document.settings.element.append(update)
    heading_counter=0
    for block in report['blocks']:
        kind=block['kind']
        if kind=='pagebreak':
            p=document.add_paragraph();p.paragraph_format.space_after=Pt(0);p.paragraph_format.space_before=Pt(0)
            p.add_run().add_break(WD_BREAK.PAGE)
        elif kind=='heading':
            p=document.add_paragraph(block['text'],style='Title' if block['anchor']=='summary' else f"Heading {block['level']}")
            p.paragraph_format.page_break_before=bool(block.get('page'))
            start=OxmlElement('w:bookmarkStart');start.set(qn('w:id'),str(heading_counter));start.set(qn('w:name'),block['anchor'].replace('-','_'))
            end=OxmlElement('w:bookmarkEnd');end.set(qn('w:id'),str(heading_counter))
            p._p.insert(0,start);p._p.append(end);heading_counter+=1
        elif kind=='paragraph':
            style=block.get('style','body')
            p=document.add_paragraph(block['text'],style='Subtitle' if style=='subtitle' else 'Normal')
            if style in ('small','meta'):
                for run in p.runs:run.font.size=Pt(10)
            if style in ('finding','toc_title'):
                for run in p.runs:run.bold=True;run.font.size=Pt(12 if style=='finding' else 17)
                p.paragraph_format.keep_with_next=style=='toc_title'
        elif kind=='toc':
            # Native fields recalculate against Word's own pagination; never copy PDF page numbers.
            p=document.add_paragraph()
            field(p,'TOC \\o "1-1" \\t "Title,1" \\h \\z \\u','Open in Word and update the table of contents to display page numbers.')
        elif kind=='chart':
            p=document.add_paragraph();p.paragraph_format.keep_with_next=True
            run=p.add_run();run.add_picture(BytesIO(base64.b64decode(block['image'])),width=Pt(522),height=Pt(block['height']))
            p.paragraph_format.space_after=Pt(0)
            for doc_properties in p._p.xpath('.//wp:docPr'):
                doc_properties.set('descr',block['caption'])
            p=document.add_paragraph(block['caption'])
            for run in p.runs:run.font.size=Pt(10)
        elif kind=='table':
            table=document.add_table(rows=1,cols=len(block['headers']))
            table.autofit=False
            widths=block.get('widths') or [1/len(block['headers'])]*len(block['headers'])
            for col,width in zip(table.columns,widths):col.width=Pt(522*width)
            header=OxmlElement('w:tblHeader');table.rows[0]._tr.get_or_add_trPr().append(header)
            for row_index,values in enumerate([block['headers']]+block['rows']):
                row=table.rows[0] if row_index==0 else table.add_row()
                if all(len(str(value))<700 for value in values):
                    cant_split=OxmlElement('w:cantSplit');row._tr.get_or_add_trPr().append(cant_split)
                for i,(cell,value) in enumerate(zip(row.cells,values)):
                    cell.width=Pt(522*widths[i]);cell.text=str(value)
                    props=cell._tc.get_or_add_tcPr()
                    margins=OxmlElement('w:tcMar')
                    for side,twips in (('top',90),('bottom',90),('left',120),('right',120)):
                        item=OxmlElement('w:'+side);item.set(qn('w:w'),str(twips));item.set(qn('w:type'),'dxa');margins.append(item)
                    props.append(margins)
                    if row_index==0:
                        shade=OxmlElement('w:shd');shade.set(qn('w:fill'),'EDEDED');props.append(shade)
                    borders=OxmlElement('w:tcBorders');bottom=OxmlElement('w:bottom');bottom.set(qn('w:val'),'single');bottom.set(qn('w:sz'),'3');bottom.set(qn('w:color'),'D0D0D0');borders.append(bottom);props.append(borders)
                    for p in cell.paragraphs:
                        p.paragraph_format.space_after=Pt(0);p.paragraph_format.line_spacing=1.0
                        p.paragraph_format.keep_with_next=bool(block.get('keep') and row_index<len(block['rows']))
                        if i in block.get('numeric',[]):p.alignment=WD_ALIGN_PARAGRAPH.RIGHT
                        for run in p.runs:run.font.size=Pt(10);run.bold=row_index==0
            after=document.add_paragraph();after.paragraph_format.space_after=Pt(0);after.paragraph_format.space_before=Pt(0)
            after.paragraph_format.line_spacing=Pt(5)
    output=BytesIO();document.save(output)
    return output.getvalue()


def build_docx(job, *, generated_at=None):
    from sbepv import technoeconomic_pdf
    report=technoeconomic_pdf.prepare_report(job,generated_at=generated_at)
    return render_docx(report),technoeconomic_pdf.report_filename(report,'docx')
