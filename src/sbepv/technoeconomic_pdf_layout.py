"""Flowing PDF layout for the shared engineering report presentation model."""
import base64
from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import BaseDocTemplate, Frame, Image, KeepTogether, PageBreak, PageTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.platypus.tableofcontents import TableOfContents


def text(value):
    return escape(str(value)).replace("\n", "<br/>")


class EngineeringDocument(BaseDocTemplate):
    def __init__(self, stream, report):
        super().__init__(stream, pagesize=letter, leftMargin=45, rightMargin=45,
                         topMargin=42, bottomMargin=43, title=report['title'], author="SBE PV Dashboard")
        self.report = report
        self.heading_pages = {}
        frame = Frame(45,43,self.width,self.height,id="body",leftPadding=0,rightPadding=0,topPadding=0,bottomPadding=0)
        self.addPageTemplates(PageTemplate(id="report",frames=frame,onPage=self.decorate))

    def decorate(self, canvas, doc):
        canvas.saveState()
        canvas.setFillColor(colors.black)
        canvas.setStrokeColor(colors.HexColor("#B0B0B0"))
        canvas.line(45,32,letter[0]-45,32)
        canvas.setFont("Helvetica",9)
        canvas.drawString(45,20,f"PV comparison  |  Report v{self.report['version']}")
        canvas.drawRightString(letter[0]-45,20,f"Page {doc.page}")
        canvas.restoreState()

    def afterFlowable(self, flowable):
        if isinstance(flowable,Paragraph) and hasattr(flowable,'report_anchor'):
            anchor,level=flowable.report_anchor,flowable.report_level
            self.canv.bookmarkPage(anchor)
            self.canv.addOutlineEntry(flowable.getPlainText(),anchor,level=level-1,closed=False)
            self.heading_pages[anchor]=self.page
            if level==1:
                self.notify('TOCEntry',(0,flowable.getPlainText(),self.page,anchor))


def render_pdf(report):
    body=ParagraphStyle('Body',fontName='Helvetica',fontSize=11,leading=14.2,spaceAfter=7,textColor=colors.black)
    styles={
        'body':body,
        'small':ParagraphStyle('Small',parent=body,fontSize=10,leading=12.6,spaceAfter=7),
        'meta':ParagraphStyle('Meta',parent=body,fontSize=10,leading=13,spaceAfter=7),
        'subtitle':ParagraphStyle('Subtitle',parent=body,fontSize=11,leading=14,spaceAfter=8),
        'finding':ParagraphStyle('Finding',parent=body,fontName='Helvetica-Bold',fontSize=12,leading=15,spaceBefore=7,spaceAfter=10),
        'toc_title':ParagraphStyle('ContentsTitle',parent=body,fontName='Helvetica-Bold',fontSize=17,leading=21,spaceAfter=9,keepWithNext=True),
    }
    title=ParagraphStyle('Title',parent=body,fontName='Helvetica-Bold',fontSize=25,leading=28,spaceAfter=10,keepWithNext=True)
    h1=ParagraphStyle('Heading1',parent=body,fontName='Helvetica-Bold',fontSize=19,leading=23,spaceBefore=8,spaceAfter=11,keepWithNext=True)
    h2=ParagraphStyle('Heading2',parent=body,fontName='Helvetica-Bold',fontSize=12,leading=15,spaceBefore=9,spaceAfter=7,keepWithNext=True)
    cell=ParagraphStyle('Cell',parent=body,fontSize=10,leading=12,spaceAfter=0,splitLongWords=True)
    numeric=ParagraphStyle('Numeric',parent=cell,alignment=TA_RIGHT)
    head=ParagraphStyle('HeaderCell',parent=cell,fontName='Helvetica-Bold')
    numeric_head=ParagraphStyle('NumericHeaderCell',parent=head,alignment=TA_RIGHT)
    story=[]
    for block in report['blocks']:
        kind=block['kind']
        if kind=='pagebreak':
            story.append(PageBreak())
        elif kind=='heading':
            if block.get('page'):
                story.append(PageBreak())
            heading=Paragraph(text(block['text']),title if block['anchor']=='summary' else h1 if block['level']==1 else h2)
            heading.report_anchor=block['anchor'];heading.report_level=block['level']
            story.append(heading)
        elif kind=='paragraph':
            story.append(Paragraph(text(block['text']),styles[block.get('style','body')]))
        elif kind=='toc':
            contents=TableOfContents()
            contents.levelStyles=[ParagraphStyle('TOC',parent=body,fontSize=11,leading=18,spaceBefore=0,spaceAfter=0,alignment=TA_LEFT)]
            story.extend([contents,Spacer(1,12)])
        elif kind=='chart':
            chart=Image(BytesIO(base64.b64decode(block['image'])),width=522,height=block['height'])
            story.append(KeepTogether([chart,Paragraph(text(block['caption']),styles['small']),Spacer(1,3)]))
        elif kind=='table':
            numeric_columns=set(block.get('numeric',()))
            data=[[Paragraph(text(value),numeric_head if i in numeric_columns else head) for i,value in enumerate(block['headers'])]]
            data += [[Paragraph(text(value),numeric if i in numeric_columns else cell) for i,value in enumerate(row)] for row in block['rows']]
            widths=block.get('widths') or [1/len(block['headers'])]*len(block['headers'])
            table=Table(data,colWidths=[522*w for w in widths],repeatRows=1,hAlign='LEFT',splitByRow=1,splitInRow=1)
            table.setStyle(TableStyle([
                ('BACKGROUND',(0,0),(-1,0),colors.HexColor('#EDEDED')),
                ('LINEBELOW',(0,0),(-1,0),.6,colors.black),
                ('LINEBELOW',(0,1),(-1,-1),.3,colors.HexColor('#DDDDDD')),
                ('VALIGN',(0,0),(-1,-1),'TOP'),
                ('LEFTPADDING',(0,0),(-1,-1),6),('RIGHTPADDING',(0,0),(-1,-1),6),
                ('TOPPADDING',(0,0),(-1,-1),5),('BOTTOMPADDING',(0,0),(-1,-1),5),
            ]))
            story.append(KeepTogether([table,Spacer(1,8)]) if block.get('keep') else table)
            if not block.get('keep'):
                story.append(Spacer(1,8))
    output=BytesIO()
    document=EngineeringDocument(output,report)
    document.multiBuild(story)
    return output.getvalue()
