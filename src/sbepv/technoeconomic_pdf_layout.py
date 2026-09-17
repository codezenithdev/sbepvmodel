"""Flowing PDF layout for the shared engineering report presentation model."""
import base64
from datetime import datetime, timezone
from io import BytesIO
import math
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import BaseDocTemplate, Flowable, Frame, Image, KeepTogether, PageBreak, PageTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.platypus.tableofcontents import TableOfContents


def text(value):
    return escape(str(value)).replace("\n", "<br/>")


def paragraph_markup(block):
    """Render shared text emphasis and links to numbered figures."""
    if not block.get('segments'):
        return text(block['text'])
    pieces=[]
    for segment in block['segments']:
        value=text(segment['text'])
        if segment.get('bold'):
            value=f'<b>{value}</b>'
        if segment.get('figure_ref'):
            target=escape('figure-'+str(segment['figure_ref']),{'"':'&quot;'})
            value=f'<link href="#{target}">{value}</link>'
        pieces.append(value)
    return ''.join(pieces)


def footer_timestamp(report):
    value=report.get('analysis_at') or report.get('generated_at')
    label='Completed' if report.get('analysis_at') else 'Exported'
    if not value:
        return 'Analysis timestamp unavailable'
    try:
        parsed=datetime.fromisoformat(str(value).replace('Z','+00:00'))
        if parsed.tzinfo is not None:
            parsed=parsed.astimezone(timezone.utc)
            return f'{label} {parsed:%Y-%m-%d %H:%M} UTC'
        return f'{label} {parsed:%Y-%m-%d %H:%M}'
    except ValueError:
        return f'{label} {value}'


def register_report_fonts(directory=None):
    """Embed the portable fonts already shipped with our plotting dependency."""
    if {'ReportSans','ReportSans-Bold'}.issubset(pdfmetrics.getRegisteredFontNames()):
        return
    if directory is None:
        import matplotlib
        directory = Path(matplotlib.get_data_path()) / 'fonts' / 'ttf'
    for name, filename in (('ReportSans','DejaVuSans.ttf'), ('ReportSans-Bold','DejaVuSans-Bold.ttf')):
        if name not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(name, str(directory / filename)))
    pdfmetrics.registerFontFamily('ReportSans', normal='ReportSans', bold='ReportSans-Bold',
                                  italic='ReportSans', boldItalic='ReportSans-Bold')


class LifecycleCDF(Flowable):
    """Native PDF paths and embedded-font labels from the verified population."""
    def __init__(self, payload, width, height):
        super().__init__()
        self.payload, self.width, self.height = payload, width, height

    def draw(self):
        c, data = self.canv, self.payload
        left, bottom, right, top = 72, 59, self.width-18, self.height-39
        values = [value for series in data['series'] for value in series['values']]
        lower, upper = min(values), max(values)
        span = upper-lower or max(abs(lower)*.1, 1)
        magnitude = 10**math.floor(math.log10(span/6))
        step = next((unit*magnitude for unit in (1,2,5,10) if unit*magnitude >= span/6), 10*magnitude)
        lower, upper = math.floor((lower-span*.02)/step)*step, math.ceil((upper+span*.02)/step)*step
        x = lambda value: left+(value-lower)/(upper-lower)*(right-left)
        y = lambda probability: bottom+probability*(top-bottom)
        c.saveState()
        c.setFont('ReportSans', 8)
        for probability in (0,.25,.5,.75,1):
            c.setStrokeColor(colors.HexColor('#D7DCE1'));c.setLineWidth(.45)
            c.line(left,y(probability),right,y(probability))
            c.setFillColor(colors.HexColor('#26323D'))
            c.drawRightString(left-8,y(probability)-3,f'{probability:.2%}')
        for index in range(int(round((upper-lower)/step))+1):
            value = lower+index*step
            c.setStrokeColor(colors.HexColor('#73808A'))
            c.line(x(value),bottom,x(value),bottom-4)
            label=f'{value:.2f}'
            c.drawCentredString(x(value),bottom-17,label)
        c.setStrokeColor(colors.HexColor('#73808A'));c.line(left,bottom,left,top);c.line(left,bottom,right,bottom)
        c.setFont('ReportSans', 8)
        year = data.get('constant_dollar_cost_year')
        basis = f'real {year} USD' if year is not None else 'constant USD'
        c.drawCentredString((left+right)/2,22,f'Lifecycle LCOE ({basis}/MWh AC)')
        c.saveState();c.translate(12,(bottom+top)/2);c.rotate(90)
        c.drawCentredString(0,0,'Probability at or below LCOE');c.restoreState()
        for index, series in enumerate(data['series']):
            color = colors.HexColor(series['color'])
            c.setStrokeColor(color);c.setFillColor(color);c.setLineWidth(1.5)
            c.setDash(5,3) if series['linestyle']=='--' else c.setDash()
            coordinates = list(zip(series['values'],series['probability']))
            path = c.beginPath();path.moveTo(x(coordinates[0][0]),y(0))
            previous_probability = 0
            for value, probability in coordinates:
                path.lineTo(x(value),y(previous_probability))
                path.lineTo(x(value),y(probability))
                previous_probability = probability
            c.drawPath(path,stroke=1,fill=0)
            c.setDash();c.setFillColor(colors.white)
            for key, probability, direction in (('p10',.1,-1),('p50',.5,0),('p90',.9,1)):
                marker_x, marker_y = x(series['percentiles'][key]), y(probability)
                if direction == 0:
                    c.circle(marker_x,marker_y,2.7,stroke=1,fill=1)
                else:
                    marker = c.beginPath()
                    marker.moveTo(marker_x,marker_y+direction*3)
                    marker.lineTo(marker_x-3,marker_y-direction*2.5)
                    marker.lineTo(marker_x+3,marker_y-direction*2.5)
                    marker.close()
                    c.drawPath(marker,stroke=1,fill=1)
            median = series['percentiles']['p50']
            legend_x = left+index*(right-left)/2
            c.setDash(5,3) if series['linestyle']=='--' else c.setDash()
            c.line(legend_x,self.height-13,legend_x+23,self.height-13);c.setDash()
            c.setFillColor(colors.HexColor('#26323D'));c.setFont('ReportSans',8)
            c.drawString(legend_x+29,self.height-16,series['label'])
            c.setFont('ReportSans',8)
            c.drawString(legend_x,self.height-29,f"n = {data['sample_count']:,}   P50 = ${median:.2f}/MWh")
        c.setFillColor(colors.HexColor('#26323D'));c.setFont('ReportSans',8)
        c.drawString(left,4,'Markers: triangle down P10; circle P50; triangle up P90 (type-7 quantiles).')
        c.restoreState()


class EngineeringDocument(BaseDocTemplate):
    def __init__(self, stream, report):
        super().__init__(stream, pagesize=letter, leftMargin=45, rightMargin=45,
                         topMargin=42, bottomMargin=58, title=report['title'], author="SBE PV Dashboard", initialFontName='ReportSans')
        self.report = report
        self.heading_pages = {}
        frame = Frame(45,58,self.width,self.height,id="body",leftPadding=0,rightPadding=0,topPadding=0,bottomPadding=0)
        self.addPageTemplates(PageTemplate(id="report",frames=frame,onPage=self.decorate))

    def decorate(self, canvas, doc):
        canvas.saveState()
        canvas.setFillColor(colors.black)
        canvas.setStrokeColor(colors.HexColor("#B0B0B0"))
        canvas.line(45,47,letter[0]-45,47)
        name=Paragraph(text(self.report.get('analysis_name') or 'PV comparison'),
                       ParagraphStyle('FooterName',fontName='ReportSans',fontSize=8.5,leading=10,splitLongWords=True))
        _,height=name.wrap(self.width,30)
        name.drawOn(canvas,45,40-height)
        canvas.setFont("ReportSans",8.5)
        canvas.drawString(45,12,footer_timestamp(self.report))
        canvas.drawRightString(letter[0]-45,12,f"Page {doc.page}")
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
    register_report_fonts()
    body=ParagraphStyle('Body',fontName='ReportSans',fontSize=10.5,leading=13.7,spaceAfter=7,textColor=colors.HexColor('#333333'),allowWidows=0,allowOrphans=0)
    styles={
        'body':body,
        'lead':ParagraphStyle('Lead',parent=body,keepWithNext=True),
        'small':ParagraphStyle('Small',parent=body,fontSize=10,leading=12.6,spaceAfter=7),
        'caption':ParagraphStyle('Caption',parent=body,fontSize=8,leading=10,spaceAfter=7),
        'meta':ParagraphStyle('Meta',parent=body,fontSize=10,leading=13,spaceAfter=7),
        'subtitle':ParagraphStyle('Subtitle',parent=body,fontSize=11,leading=14,spaceAfter=8),
        'finding':ParagraphStyle('Finding',parent=body,spaceBefore=3,spaceAfter=8),
        'toc_title':ParagraphStyle('ContentsTitle',parent=body,fontSize=17,leading=21,spaceAfter=9,keepWithNext=True),
    }
    title=ParagraphStyle('Title',parent=body,fontSize=22,leading=26,spaceAfter=10,keepWithNext=True)
    h1=ParagraphStyle('Heading1',parent=body,fontSize=17,leading=21,spaceBefore=8,spaceAfter=11,keepWithNext=True)
    h2=ParagraphStyle('Heading2',parent=body,fontName='ReportSans-Bold',fontSize=11.5,leading=14.5,textColor=colors.HexColor('#404040'),spaceBefore=9,spaceAfter=7,keepWithNext=True)
    h3=ParagraphStyle('Heading3',parent=h2,fontSize=11,leading=14,spaceBefore=7,spaceAfter=6)
    cell=ParagraphStyle('Cell',parent=body,fontSize=10,leading=12,spaceAfter=0,splitLongWords=True)
    numeric=ParagraphStyle('Numeric',parent=cell,alignment=TA_RIGHT)
    head=ParagraphStyle('HeaderCell',parent=cell,fontName='ReportSans-Bold')
    numeric_head=ParagraphStyle('NumericHeaderCell',parent=head,alignment=TA_RIGHT)
    story=[]
    for block in report['blocks']:
        kind=block['kind']
        if kind=='pagebreak':
            story.append(PageBreak())
        elif kind=='title':
            story.append(Paragraph(text(block['text']),title))
        elif kind=='heading':
            if block.get('page'):
                story.append(PageBreak())
            label=(str(block['number'])+' ' if block.get('number') else '')+block['text']
            heading=Paragraph(text(label),{1:h1,2:h2,3:h3}[block['level']])
            heading.report_anchor=block['anchor'];heading.report_level=block['level']
            story.append(heading)
        elif kind=='paragraph':
            style=styles[block.get('style','body')]
            if any(segment.get('figure_ref') for segment in block.get('segments',[])):
                style=ParagraphStyle('FigureReference',parent=style,keepWithNext=True)
            story.append(Paragraph(paragraph_markup(block),style))
        elif kind=='reference':
            story.append(Paragraph('<link href="'+escape(block['url'],{'"':'&quot;'})+'">'+text(block['text'])+'</link>',styles['small']))
        elif kind=='toc':
            contents=TableOfContents()
            contents.levelStyles=[ParagraphStyle('TOC',parent=body,fontSize=11,leading=18,spaceBefore=0,spaceAfter=0,alignment=TA_LEFT)]
            story.extend([contents,Spacer(1,12)])
        elif kind=='chart':
            chart=(LifecycleCDF(block['vector'],522,block['height']) if block.get('vector') else
                   Image(BytesIO(base64.b64decode(block['image'])),width=522,height=block['height']))
            caption=text(block['caption'])
            if block.get('figure_id') and block.get('figure_number') is not None:
                anchor=escape('figure-'+str(block['figure_id']),{'"':'&quot;'})
                caption=f'<a name="{anchor}"/>Figure {block["figure_number"]}. '+caption
            group=[chart,Paragraph(caption,styles['caption']),Spacer(1,3)]
            while story and isinstance(story[-1],Paragraph) and getattr(story[-1].style,'keepWithNext',False):
                group.insert(0,story.pop())
            story.append(KeepTogether(group))
        elif kind=='table':
            numeric_columns=set(block.get('numeric',()))
            emphasis_rows=set(block.get('emphasis_rows',()))
            data=[[Paragraph(text(value),numeric_head if i in numeric_columns else head) for i,value in enumerate(block['headers'])]]
            data += [[Paragraph(text(value),(numeric_head if i in numeric_columns else head) if row_index in emphasis_rows
                                else (numeric if i in numeric_columns else cell)) for i,value in enumerate(row)]
                     for row_index,row in enumerate(block['rows'])]
            widths=block.get('widths') or [1/len(block['headers'])]*len(block['headers'])
            table=Table(data,colWidths=[522*w for w in widths],repeatRows=1,hAlign='LEFT',splitByRow=1,splitInRow=1)
            table.setStyle(TableStyle([
                ('BACKGROUND',(0,0),(-1,0),colors.HexColor('#EDEDED')),
                ('LINEBELOW',(0,0),(-1,0),.6,colors.black),
                ('LINEBELOW',(0,1),(-1,-1),.3,colors.HexColor('#DDDDDD')),
                ('VALIGN',(0,0),(-1,-1),'TOP'),
                ('LEFTPADDING',(0,0),(-1,-1),6),('RIGHTPADDING',(0,0),(-1,-1),6),
                ('TOPPADDING',(0,0),(-1,-1),3 if block.get('compact') else 5),('BOTTOMPADDING',(0,0),(-1,-1),3 if block.get('compact') else 5),
            ]))
            for row_index in emphasis_rows:
                table.setStyle(TableStyle([('LINEABOVE',(0,row_index+1),(-1,row_index+1),.6,colors.HexColor('#999999'))]))
            if block.get('keep'):
                group=[table,Spacer(1,8)]
                # A nested KeepTogether does not inherit a preceding heading's
                # keepWithNext when the whole table moves to the next page.
                while story and isinstance(story[-1],Paragraph) and getattr(story[-1].style,'keepWithNext',False):
                    group.insert(0,story.pop())
                story.append(KeepTogether(group))
            else:
                story.append(table)
            if not block.get('keep'):
                story.append(Spacer(1,8))
    output=BytesIO()
    document=EngineeringDocument(output,report)
    document.multiBuild(story)
    return output.getvalue()
