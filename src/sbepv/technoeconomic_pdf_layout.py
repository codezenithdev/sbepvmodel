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
from reportlab.pdfgen import canvas as pdfcanvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import BaseDocTemplate, CondPageBreak, Flowable, Frame, HRFlowable, Image, KeepTogether, PageBreak, PageTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.platypus.tableofcontents import TableOfContents

from sbepv.technoeconomic_math import equation_markup, equation_plain


PAGE_WIDTH, PAGE_HEIGHT = letter
SIDE_MARGIN = 72
TOP_MARGIN = 58
BOTTOM_MARGIN = 58
CONTENT_WIDTH = PAGE_WIDTH - 2 * SIDE_MARGIN
FOOTER_RULE_Y = 47
# Charts and explicit table widths were authored against the original 522pt
# column. Rescaling by this factor keeps their proportions on the wider margins.
AUTHORED_WIDTH = 522
CHART_SCALE = CONTENT_WIDTH / AUTHORED_WIDTH
# Height the CDF no longer needs below its axis title now that the marker key
# lives in the caption.
CDF_CAPTION_RECLAIM = 12
INK = colors.HexColor('#1A1D21')
BODY_INK = colors.HexColor('#333333')
MUTED_INK = colors.HexColor('#5A6470')


def text(value):
    return escape(str(value)).replace("\n", "<br/>")


def paragraph_markup(block):
    """Render shared text emphasis and links to numbered figures."""
    if block.get('math'):
        return equation_markup(block['text'])
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
        elif segment.get('table_ref'):
            target=escape('table-'+str(segment['table_ref']),{'"':'&quot;'})
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
    required = {'ReportSans','ReportSans-Bold','ReportMono','ReportMono-Bold'}
    if required.issubset(pdfmetrics.getRegisteredFontNames()):
        return
    if directory is None:
        import matplotlib
        directory = Path(matplotlib.get_data_path()) / 'fonts' / 'ttf'
    for name, filename in (('ReportSans','DejaVuSans.ttf'), ('ReportSans-Bold','DejaVuSans-Bold.ttf'),
                           ('ReportMono','DejaVuSansMono.ttf'), ('ReportMono-Bold','DejaVuSansMono-Bold.ttf')):
        if name not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(name, str(directory / filename)))
    pdfmetrics.registerFontFamily('ReportSans', normal='ReportSans', bold='ReportSans-Bold',
                                  italic='ReportSans', boldItalic='ReportSans-Bold')
    pdfmetrics.registerFontFamily('ReportMono', normal='ReportMono', bold='ReportMono-Bold',
                                  italic='ReportMono', boldItalic='ReportMono-Bold')


class LifecycleCDF(Flowable):
    """Native PDF paths and embedded-font labels from the verified population."""
    def __init__(self, payload, width, height):
        super().__init__()
        self.payload, self.width, self.height = payload, width, height

    def draw(self):
        c, data = self.canv, self.payload
        left, bottom, right, top = 72, 47, self.width-18, self.height-39
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
            c.drawRightString(left-8,y(probability)-3,f'{probability:.0%}')
        for index in range(int(round((upper-lower)/step))+1):
            value = lower+index*step
            c.setStrokeColor(colors.HexColor('#73808A'))
            c.line(x(value),bottom,x(value),bottom-4)
            decimals=0 if step>=1 else (1 if step>=.1 else 2)
            c.drawCentredString(x(value),bottom-17,f'{value:.{decimals}f}')
        c.setStrokeColor(colors.HexColor('#73808A'));c.line(left,bottom,left,top);c.line(left,bottom,right,bottom)
        c.setFont('ReportSans', 8)
        year = data.get('constant_dollar_cost_year')
        basis = f'real {year} USD' if year is not None else 'constant USD'
        c.drawCentredString((left+right)/2,10,f'Lifecycle LCOE ({basis}/MWh AC)')
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
            c.setFillColor(INK);c.setFont('ReportSans-Bold',8.5)
            c.drawString(legend_x+29,self.height-16,series['label'])
            c.setFillColor(MUTED_INK);c.setFont('ReportSans',8)
            c.drawString(legend_x,self.height-29,f"n = {data['sample_count']:,}   P50 = ${median:.2f}/MWh")
        c.restoreState()


def column_widths(block, styles):
    """Size columns from their content rather than splitting the measure evenly.

    Most report tables carry no explicit widths. Equal columns stretched a
    one-word record value across the full measure and wrapped a 64-character
    hash mid-string, so the natural width of each column is measured instead.
    """
    headers, rows = block['headers'], block['rows']
    if block.get('widths'):
        return [CONTENT_WIDTH*width for width in block['widths']]
    mono_columns = set(block.get('mono_columns', ()))
    math_columns = set(block.get('math_columns', ()))
    padding = 12
    demand, floor = [], []
    for index, header in enumerate(headers):
        monospaced = index in mono_columns or index in math_columns
        body_font = 'ReportMono' if monospaced else 'ReportSans'
        body_size = styles['mono'].fontSize if monospaced else styles['cell'].fontSize
        entries = [(str(header), 'ReportSans-Bold', styles['head'].fontSize)]
        entries += [((equation_plain(row[index]) if index in math_columns else str(row[index])) if index < len(row) else '', body_font, body_size) for row in rows]
        widest_line = widest_word = 0
        for value, font, size in entries:
            for line in value.split('\n'):
                widest_line = max(widest_line, pdfmetrics.stringWidth(line, font, size))
                for word in line.split(' '):
                    widest_word = max(widest_word, pdfmetrics.stringWidth(word, font, size))
        demand.append(widest_line+padding)
        # Fixed-width content is authored to a column; wrapping it destroys the
        # alignment, so a monospaced column never gives up its natural width.
        floor.append(min(demand[-1] if monospaced else widest_word+padding, CONTENT_WIDTH*(.75 if monospaced else .55)))
    total = sum(demand)
    if total <= CONTENT_WIDTH:
        # A short table reads better left-aligned at its natural width than
        # stretched across the measure, but must not look like a fragment.
        return [width*max(1.0, CONTENT_WIDTH*.62/total) for width in demand] if total else demand
    slack = CONTENT_WIDTH-sum(floor)
    if slack <= 0:
        share = sum(floor) or 1
        return [CONTENT_WIDTH*width/share for width in floor]
    extra = [wanted-least for wanted, least in zip(demand, floor)]
    pool = sum(extra) or 1
    return [least+slack*want/pool for least, want in zip(floor, extra)]


class ReportTable(Table):
    """A table whose repeated header says so when it continues onto a new page."""
    def __init__(self, *args, **named):
        super().__init__(*args, **named)
        self._pieces = 0
        self._continued = False

    def onSplit(self, piece, byRow=1):
        piece._pieces = 0
        piece._continued = self._continued or self._pieces > 0
        self._pieces += 1
        if piece._continued and piece.repeatRows:
            self._label_continuation(piece)
        return super().onSplit(piece, byRow)

    @staticmethod
    def _label_continuation(piece):
        """Append the marker only when it still fits the header's first line.

        The split pieces carry precomputed row heights, so a header that wrapped
        onto a second line would overflow its row.
        """
        cell = piece._cellvalues[0][0]
        paragraphs = cell if isinstance(cell, (list, tuple)) else [cell]
        if len(paragraphs) != 1 or not isinstance(paragraphs[0], Paragraph):
            return
        original = paragraphs[0]
        plain = original.getPlainText()
        if 'continued' in plain:
            return
        style = original.style
        available = piece._colWidths[0]-12
        if pdfmetrics.stringWidth(plain+' (continued)', style.fontName, style.fontSize) > available:
            return
        marker = Paragraph(original.text+f' <font size="{style.fontSize-1.2:.1f}" color="#6B7680">(continued)</font>', style)
        marker.wrapOn(piece.canv if hasattr(piece, 'canv') else None, available, piece._rowHeights[0])
        # The pieces share their header row object, so copy it before editing or
        # the first page is labelled a continuation of itself.
        header = list(piece._cellvalues[0])
        header[0] = type(cell)([marker]) if isinstance(cell, tuple) else [marker]
        piece._cellvalues[0] = header


class PageCountCanvas(pdfcanvas.Canvas):
    """Defer footer drawing while registering pages and their links normally."""

    def showPage(self):
        # ReportLab permits forward form references. Register each page now so
        # bookmarks and annotations retain its actual PDF page destination.
        self.doForm(f"report-page-footer-{self.getPageNumber()}")
        super().showPage()

    def save(self):
        if self._code:
            self.showPage()
        total_pages = self.getPageNumber() - 1
        for page_number in range(1, total_pages + 1):
            self.beginForm(f"report-page-footer-{page_number}")
            self.setFont("ReportSans", 8.5)
            self.setFillColor(MUTED_INK)
            self.drawRightString(PAGE_WIDTH-SIDE_MARGIN, FOOTER_RULE_Y-12,
                                 f"Page {page_number} of {total_pages}")
            self.endForm()
        super().save()


class EngineeringDocument(BaseDocTemplate):
    def __init__(self, stream, report):
        super().__init__(stream, pagesize=letter, leftMargin=SIDE_MARGIN, rightMargin=SIDE_MARGIN,
                         topMargin=TOP_MARGIN, bottomMargin=BOTTOM_MARGIN, title=report['title'],
                         author="SBE PV Dashboard", initialFontName='ReportSans')
        self.report = report
        self.heading_pages = {}
        frame = Frame(SIDE_MARGIN,BOTTOM_MARGIN,self.width,self.height,id="body",
                      leftPadding=0,rightPadding=0,topPadding=0,bottomPadding=0)
        self.addPageTemplates(PageTemplate(id="report",frames=frame,onPage=self.decorate))

    def decorate(self, canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(colors.HexColor("#D0D4D8"))
        canvas.setLineWidth(.5)
        canvas.line(SIDE_MARGIN,FOOTER_RULE_Y,PAGE_WIDTH-SIDE_MARGIN,FOOTER_RULE_Y)
        canvas.setFont("ReportSans",8.5)
        canvas.setFillColor(MUTED_INK)
        # The cover already names the run under its title; repeating it in the
        # footer there printed the same name twice. Page 1 keeps only its number.
        if doc.page > 1:
            name=Paragraph(text(self.report.get('analysis_name') or 'PV comparison'),
                           ParagraphStyle('FooterName',fontName='ReportSans',fontSize=8.5,leading=10,
                                          textColor=MUTED_INK,splitLongWords=True))
            _,height=name.wrap(self.width*.7,20)
            name.drawOn(canvas,SIDE_MARGIN,FOOTER_RULE_Y-12-height+10)
        canvas.restoreState()

    def afterFlowable(self, flowable):
        if isinstance(flowable,Paragraph) and hasattr(flowable,'report_anchor'):
            anchor,level=flowable.report_anchor,flowable.report_level
            self.canv.bookmarkPage(anchor)
            self.canv.addOutlineEntry(flowable.getPlainText(),anchor,level=level-1,closed=False)
            self.heading_pages[anchor]=self.page
            if level<=2:
                self.notify('TOCEntry',(level-1,flowable.getPlainText(),self.page,anchor))


def render_pdf(report):
    register_report_fonts()
    body=ParagraphStyle('Body',fontName='ReportSans',fontSize=10.5,leading=14.2,spaceAfter=8,textColor=BODY_INK,allowWidows=0,allowOrphans=0)
    styles={
        'body':body,
        'lead':ParagraphStyle('Lead',parent=body,keepWithNext=True),
        # Qualifications and notes are a deliberate secondary tier: a half-point
        # size drop alone reads as drift, so they also carry the muted ink.
        'small':ParagraphStyle('Small',parent=body,fontSize=9.7,leading=12.8,spaceAfter=8,textColor=MUTED_INK),
        'caption':ParagraphStyle('Caption',parent=body,fontSize=8.6,leading=11.2,spaceBefore=2,spaceAfter=8,textColor=MUTED_INK),
        'meta':ParagraphStyle('Meta',parent=body,fontSize=10,leading=14.5,spaceAfter=4,textColor=MUTED_INK),
        'subtitle':ParagraphStyle('Subtitle',parent=body,fontSize=12,leading=16,spaceAfter=4,textColor=BODY_INK),
        'finding':ParagraphStyle('Finding',parent=body,spaceBefore=3,spaceAfter=9),
        'toc_title':ParagraphStyle('ContentsTitle',parent=body,fontName='ReportSans-Bold',fontSize=17,leading=21,spaceAfter=12,textColor=INK,keepWithNext=True),
    }
    title=ParagraphStyle('Title',parent=body,fontName='ReportSans-Bold',fontSize=23,leading=27,spaceAfter=12,textColor=INK,keepWithNext=True)
    # A subheader set at the run details' size reads as another detail line. The
    # 23/14/10 ramp and the darker ink keep it attached to the title instead.
    cover_title=ParagraphStyle('CoverTitle',parent=title,spaceAfter=6)
    cover_subtitle=ParagraphStyle('CoverSubtitle',parent=body,fontSize=14,leading=18,spaceAfter=12,
                                  textColor=colors.HexColor('#2B3138'),keepWithNext=True)
    # Weight now increases up the hierarchy and every step is legible on its own:
    # the old 11.5/11/10.5 ramp made h2, h3 and body indistinguishable.
    h1=ParagraphStyle('Heading1',parent=body,fontName='ReportSans-Bold',fontSize=17,leading=21,spaceBefore=4,spaceAfter=12,textColor=INK,keepWithNext=True)
    h2=ParagraphStyle('Heading2',parent=body,fontName='ReportSans-Bold',fontSize=12.8,leading=16,textColor=colors.HexColor('#2B3138'),spaceBefore=16,spaceAfter=6,keepWithNext=True)
    h3=ParagraphStyle('Heading3',parent=h2,fontSize=10.9,leading=14,textColor=colors.HexColor('#4A5560'),spaceBefore=13,spaceAfter=5)
    cell=ParagraphStyle('Cell',parent=body,fontSize=9.8,leading=12.4,spaceAfter=0,textColor=BODY_INK,splitLongWords=True)
    numeric=ParagraphStyle('Numeric',parent=cell,alignment=TA_RIGHT)
    head=ParagraphStyle('HeaderCell',parent=cell,fontName='ReportSans-Bold',textColor=INK)
    numeric_head=ParagraphStyle('NumericHeaderCell',parent=head,alignment=TA_RIGHT)
    # Equations and hashes are fixed-width content; the authored column alignment
    # in the appendix only holds in a monospaced face.
    # Extra leading keeps stacked subscripts and superscripts in multi-line
    # equation cells from touching the line above or below.
    mono=ParagraphStyle('MonoCell',parent=cell,fontName='ReportMono',fontSize=8.6,leading=14)
    mono_head=ParagraphStyle('MonoHeaderCell',parent=head)
    story=[]
    for block in report['blocks']:
        kind=block['kind']
        if kind=='pagebreak':
            story.append(PageBreak())
        elif kind=='title':
            subtitle=block.get('subtitle')
            story.append(Paragraph(text(block['text']),cover_title if subtitle else title))
            if subtitle:
                story.append(Paragraph(text(subtitle),cover_subtitle))
            story.append(HRFlowable(width=CONTENT_WIDTH,thickness=1.2,color=INK,spaceBefore=0,spaceAfter=14,hAlign='LEFT'))
        elif kind=='heading':
            # A hard break belongs to a numbered section. Subsections ask only
            # not to be stranded: forcing them left pages all but empty.
            if block.get('page') is True:
                story.append(PageBreak())
            elif block.get('page'):
                story.append(CondPageBreak(190))
            label=(str(block['number'])+' ' if block.get('number') else '')+block['text']
            heading=Paragraph(text(label),{1:h1,2:h2,3:h3}[block['level']])
            heading.report_anchor=block['anchor'];heading.report_level=block['level']
            story.append(heading)
        elif kind=='paragraph':
            style=styles['body' if block.get('style')=='bullet' else block.get('style','body')]
            if block.get('style')=='bullet':
                style=ParagraphStyle('Bullet',parent=style,leftIndent=12,bulletIndent=0)
            if any(segment.get('figure_ref') or segment.get('table_ref') for segment in block.get('segments',[])):
                style=ParagraphStyle('FigureReference',parent=style,keepWithNext=True)
            if block.get('math'):
                style=ParagraphStyle('Equation',parent=style,fontName='ReportMono',fontSize=9.2,leading=15.5,spaceBefore=2)
            story.append(Paragraph(paragraph_markup(block),style,bulletText='\u2022' if block.get('style')=='bullet' else None))
        elif kind=='reference':
            story.append(Paragraph('<link href="'+escape(block['url'],{'"':'&quot;'})+'">'+text(block['text'])+'</link>',styles['small']))
        elif kind=='toc':
            contents=TableOfContents()
            contents.levelStyles=[
                ParagraphStyle('TOCSection',parent=body,fontName='ReportSans-Bold',fontSize=10.8,leading=16.5,
                               textColor=INK,spaceBefore=7,spaceAfter=0,alignment=TA_LEFT),
                ParagraphStyle('TOCSubsection',parent=body,fontSize=10,leading=14.5,textColor=BODY_INK,
                               leftIndent=16,spaceBefore=0,spaceAfter=0,alignment=TA_LEFT)]
            contents.dotsMinLevel=0
            story.extend([contents,Spacer(1,12)])
        elif kind=='chart':
            height=block['height']*CHART_SCALE
            chart=(LifecycleCDF(block['vector'],CONTENT_WIDTH,height-CDF_CAPTION_RECLAIM) if block.get('vector') else
                   Image(BytesIO(base64.b64decode(block['image'])),width=block.get('width',AUTHORED_WIDTH)*CHART_SCALE,height=height))
            caption=text(block['caption'])
            if block.get('vector'):
                caption+=' Markers: triangle down P10; circle P50; triangle up P90 (type-7 quantiles).'
            if block.get('figure_id') and block.get('figure_number') is not None:
                anchor=escape('figure-'+str(block['figure_id']),{'"':'&quot;'})
                caption=f'<a name="{anchor}"/>Figure {block["figure_number"]}. '+caption
            group=[chart,Paragraph(caption,styles['caption']),Spacer(1,3)]
            while story and isinstance(story[-1],Paragraph) and getattr(story[-1].style,'keepWithNext',False):
                group.insert(0,story.pop())
            story.append(KeepTogether(group))
        elif kind=='table':
            if block.get('table_id') and block.get('table_number') is not None:
                anchor=escape('table-'+str(block['table_id']),{'"':'&quot;'})
                caption=f'<a name="{anchor}"/>Table {block["table_number"]}. '+text(block['caption'])
                story.append(Paragraph(caption,ParagraphStyle('TableCaption',parent=styles['caption'],keepWithNext=True)))
            numeric_columns=set(block.get('numeric',()))
            emphasis_rows=set(block.get('emphasis_rows',()))
            mono_columns=set(block.get('mono_columns',()))
            math_columns=set(block.get('math_columns',()))
            def body_style(index,row_index):
                if row_index in emphasis_rows:
                    return numeric_head if index in numeric_columns else head
                if index in mono_columns or index in math_columns:
                    return mono
                return numeric if index in numeric_columns else cell
            def cell_markup(index,value):
                return equation_markup(value) if index in math_columns else text(value)
            data=[[Paragraph(text(value),numeric_head if i in numeric_columns else head) for i,value in enumerate(block['headers'])]]
            data += [[Paragraph(cell_markup(i,value),body_style(i,row_index)) for i,value in enumerate(row)]
                     for row_index,row in enumerate(block['rows'])]
            table=ReportTable(data,colWidths=column_widths(block,{'cell':cell,'head':head,'mono':mono}),
                              repeatRows=1,hAlign='LEFT',splitByRow=1,splitInRow=1)
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
    document.multiBuild(story, canvasmaker=PageCountCanvas)
    return output.getvalue()
