"""Bounded PDF output checks for the report's observed pagination failures."""
from io import BytesIO
import unittest

from sbepv import technoeconomic_pdf_layout as layout

try:
    from pypdf import PdfReader
    from pypdf.generic import ContentStream
except ImportError:
    PdfReader = None


@unittest.skipIf(PdfReader is None, "Optional pypdf PDF-QA parser is not installed")
class ReportPaginationTests(unittest.TestCase):
    def prefix(self, lines=42):
        # This fills the first page far enough that a heading still fits but
        # its four-row table does not. It also leaves room for six body lines.
        return [
            {"kind": "heading", "text": "Calibration evidence", "level": 1, "anchor": "calibration"},
            {"kind": "paragraph", "text": "\n".join(["Context line"] * lines)},
        ]

    def pdf_reader(self, blocks):
        data = layout.render_pdf({"title": "Pagination regression", "version": "test", "blocks": blocks})
        return PdfReader(BytesIO(data))

    def page_texts(self, blocks):
        return [page.extract_text() for page in self.pdf_reader(blocks).pages]

    def cdf_block(self):
        series = [{"system": system, "label": label, "values": values,
                   "probability": [1/3, 2/3, 1], "percentiles": {"p10": values[0], "p50": values[1], "p90": values[2]},
                   "color": color, "linestyle": line}
                  for system,label,values,color,line in (
                      ("solectria", "Solectria", [40, 50, 60], "#AD7610", "--"),
                      ("solaredge", "SolarEdge", [45, 55, 65], "#2E66A3", "-"))]
        # Deliberately invalid raster fallback proves the PDF uses native paths.
        return {"kind": "chart", "image": "not-a-png", "height": 3.55 * 72,
                "vector": {"series": series, "sample_count": 6, "constant_dollar_cost_year": 2024},
                "caption": "Verified lifecycle CDF caption."}

    def test_heading_moves_with_its_kept_table(self):
        pages = self.page_texts(self.prefix() + [
            {"kind": "heading", "text": "Applied Annual calibration factors", "level": 2, "anchor": "factors"},
            {"kind": "table", "headers": ["Season", "Factor"],
             "rows": [["Winter", ".9"], ["Spring", ".8"], ["Summer", ".7"], ["Fall", ".6"]],
             "keep": True},
        ])
        self.assertEqual(len(pages), 2)
        self.assertNotIn("Applied Annual calibration factors", pages[0])
        self.assertIn("Applied Annual calibration factors", pages[1])
        for season in ("Winter", "Spring", "Summer", "Fall"):
            self.assertIn(season, pages[1])
        self.assertLess(pages[1].index("Applied Annual calibration factors"), pages[1].index("Season"))

    def test_paragraph_does_not_leave_single_line_on_next_page(self):
        pages = self.page_texts(self.prefix() + [
            {"kind": "paragraph", "text": "\n".join(f"Equation line {i}" for i in range(1, 8))},
        ])
        self.assertEqual(len(pages), 2)
        self.assertIn("Equation line 1", pages[0])
        self.assertNotIn("Equation line 6", pages[0])
        self.assertIn("Equation line 6", pages[1])
        self.assertIn("Equation line 7", pages[1])
        for index in range(1, 8):
            self.assertEqual(sum(f"Equation line {index}" in page for page in pages), 1)

    def test_every_page_footer_shows_current_and_total_page_count(self):
        pages = self.page_texts(self.prefix() + [
            {"kind": "pagebreak"},
            {"kind": "paragraph", "text": "Final page"},
        ])
        self.assertGreaterEqual(len(pages), 2)
        for page_number, page in enumerate(pages, start=1):
            self.assertIn(f"Page {page_number} of {len(pages)}", page)
            self.assertNotIn(f"{page_number}/{len(pages)}", page)

    def test_cover_carries_its_subheader_and_names_the_run_once(self):
        data = layout.render_pdf({"title": "Cover title", "subtitle": "Cover subheader",
                                  "version": "test", "analysis_name": "Fall substitution run",
                                  "blocks": [{"kind": "title", "text": "Cover title", "subtitle": "Cover subheader"},
                                             {"kind": "paragraph", "style": "meta", "text": "Fall substitution run"},
                                             {"kind": "pagebreak"},
                                             {"kind": "paragraph", "text": "Body page"}]})
        pages = [page.extract_text() for page in PdfReader(BytesIO(data)).pages]
        self.assertIn("Cover subheader", pages[0])
        # The cover states the run under its title; the repeated footer name put
        # it on the page twice.
        self.assertEqual(1, pages[0].count("Fall substitution run"))
        self.assertIn("Fall substitution run", pages[1])

    def test_chart_heading_introduction_and_caption_travel_with_figure(self):
        pages = self.page_texts(self.prefix(lines=30) + [
            {"kind": "heading", "text": "Lifecycle comparison", "level": 2, "anchor": "lifecycle"},
            {"kind": "paragraph", "text": "Verified saved realization evidence.", "style": "lead"},
            self.cdf_block(),
        ])
        self.assertEqual(len(pages), 2)
        for expected in ("Lifecycle comparison", "Verified saved realization evidence.",
                         "Solectria", "SolarEdge", "Verified lifecycle CDF caption."):
            self.assertNotIn(expected, pages[0])
            self.assertIn(expected, pages[1])
        self.assertLess(pages[1].index("Lifecycle comparison"), pages[1].index("Solectria"))
        self.assertLess(pages[1].index("Solectria"), pages[1].index("Verified lifecycle CDF caption."))

    def test_cdf_pdf_contains_native_curve_paths_and_embeds_fonts_used_for_text(self):
        reader = self.pdf_reader([self.cdf_block()])
        self.assertEqual(len(reader.pages), 1)
        page = reader.pages[0]
        resources = page["/Resources"].get_object()
        self.assertFalse(resources.get("/XObject"), "Native CDF PDF must not substitute a raster image")
        operations = ContentStream(page.get_contents(), reader).operations
        curve_lengths, current_path_length = [], 0
        used_fonts, active_font = set(), None
        for operands, operator in operations:
            if operator == b"m":
                current_path_length = 0
            elif operator == b"l":
                current_path_length += 1
            elif operator == b"S":
                curve_lengths.append(current_path_length)
                current_path_length = 0
            elif operator == b"Tf":
                active_font = operands[0]
            elif operator in (b"Tj", b"TJ", b"'", b'"'):
                used_fonts.add(active_font)
        self.assertEqual(sum(length >= 6 for length in curve_lengths), 2,
                         "Both three-point ECDFs must be drawn as connected step paths")
        self.assertGreaterEqual(len(used_fonts), 2)
        for font_name in used_fonts:
            font = resources["/Font"][font_name].get_object()
            self.assertIn("DejaVuSans", font["/BaseFont"])
            descriptor = font["/FontDescriptor"].get_object()
            self.assertTrue(descriptor.get("/FontFile2"), "Every font actually used to draw text must be embedded")
        text = page.extract_text()
        self.assertIn("n = 6", text)
        self.assertIn("P50 = $50.00/MWh", text)
        self.assertIn("P50 = $55.00/MWh", text)


if __name__ == "__main__":
    unittest.main()
