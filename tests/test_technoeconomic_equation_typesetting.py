"""Inline equation notation is typeset into sub/superscripts in both exports."""
import unittest

from sbepv.technoeconomic_math import equation_markup, equation_plain, equation_runs


class MathParserTests(unittest.TestCase):
    def test_subscript_token_stops_at_operators_and_spaces(self):
        self.assertEqual("R<sub>sh</sub> + R<sub>s</sub>", equation_markup("R_sh + R_s"))
        self.assertEqual("Rsh + Rs", equation_plain("R_sh + R_s"))

    def test_comma_stays_inside_a_subscript(self):
        self.assertEqual("E<sub>j,1</sub>", equation_markup("E_j,1"))
        self.assertEqual([("E", None), ("j,1", "sub")], equation_runs("E_j,1"))

    def test_superscript_accepts_bare_token_or_parenthesised_group(self):
        self.assertEqual("x<super>2</super>", equation_markup("x^2"))
        self.assertEqual("(1 + r)<super>-t</super>", equation_markup("(1 + r)^(-t)"))
        self.assertEqual("(1 - g)<super>t-1</super>", equation_markup("(1 - g)^(t-1)"))

    def test_summation_bounds_become_subscript_then_superscript(self):
        self.assertEqual("Σ<sub>t=1</sub><super>L</super>", equation_markup("Σ_(t=1)^(L)"))

    def test_nested_subscript_inside_superscript(self):
        self.assertEqual("(1 - U/V<sub>RBD</sub>)<super>-n<sub>RBD</sub></super>",
                         equation_markup("(1 - U/V_RBD)^(-n_RBD)"))
        # Word runs flatten to the nearest ancestor script.
        self.assertIn(("-n", "super"), equation_runs("(1 - U/V_RBD)^(-n_RBD)"))
        self.assertIn(("RBD", "sub"), equation_runs("(1 - U/V_RBD)^(-n_RBD)"))

    def test_plain_text_without_markers_is_left_untouched(self):
        digest = "827ceca557a95b79aa15e53bea367c3873bfbd6d"
        self.assertEqual(digest, equation_markup(digest))
        self.assertEqual(digest, equation_plain(digest))

    def test_a_trailing_marker_without_a_body_is_literal(self):
        self.assertEqual("a ^ b", equation_markup("a ^ b"))

    def test_newlines_become_line_breaks_in_markup_and_survive_runs(self):
        self.assertEqual("DF<sub>t</sub><br/>x", equation_markup("DF_t\nx"))
        self.assertEqual([("DF", None), ("t", "sub"), ("\nx", None)], equation_runs("DF_t\nx"))

    def test_markup_escapes_literal_xml_characters(self):
        self.assertEqual("a &lt; b &amp; c", equation_markup("a < b & c"))


class ReportTypesettingTests(unittest.TestCase):
    def setUp(self):
        import shutil, uuid
        from pathlib import Path
        from unittest.mock import patch
        from sbepv.api import config
        from tests.test_technoeconomic_full_report import completed_fixture
        from sbepv import technoeconomic_pdf as pdf
        self.root = Path(__file__).resolve().parent / ("-eqn-" + uuid.uuid4().hex)
        self.root.mkdir()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        patcher = patch.object(config, "OUTPUT_DIR", self.root)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.job, _ = completed_fixture()
        self.report = pdf.prepare_report(self.job)

    def test_lcoe_equation_paragraph_is_flagged_for_math(self):
        math_paragraphs = [b for b in self.report["blocks"]
                           if b["kind"] == "paragraph" and b.get("math")]
        self.assertTrue(math_paragraphs)
        self.assertTrue(any("LCOE_j" in b["text"] for b in math_paragraphs))

    def test_appendix_equation_tables_mark_the_equation_column(self):
        math_tables = [b for b in self.report["blocks"]
                       if b["kind"] == "table" and b.get("math_columns")]
        self.assertTrue(math_tables)
        for block in math_tables:
            self.assertEqual([0], block["math_columns"])
            self.assertEqual("Equation", block["headers"][0])

    def test_both_exports_render_the_typeset_equations(self):
        from sbepv import technoeconomic_pdf as pdf, technoeconomic_docx as word
        from io import BytesIO
        from zipfile import ZipFile
        pdf_bytes, _ = pdf.build_pdf(self.job, include_technical_appendix=True)
        self.assertTrue(pdf_bytes.startswith(b"%PDF-"))
        with ZipFile(BytesIO(word.render_docx(self.report))) as archive:
            xml = archive.read("word/document.xml").decode()
        self.assertIn('w:val="superscript"', xml)
        self.assertIn('w:val="subscript"', xml)


if __name__ == "__main__":
    unittest.main()
