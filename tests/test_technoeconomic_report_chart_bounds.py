"""Document-sized chart labels must survive fixed-size image embedding."""
import unittest
from unittest.mock import patch

from matplotlib.backends.backend_agg import FigureCanvasAgg

from sbepv import technoeconomic_report as report


class ReportChartBoundsTests(unittest.TestCase):
    def test_annual_cdf_percentage_ticks_and_titles_fit_inside_image(self):
        captured = []

        def capture_canvas(figure):
            canvas = FigureCanvasAgg(figure)
            captured.append(canvas)
            return canvas

        with patch.object(report, 'FigureCanvasAgg', side_effect=capture_canvas):
            report.chart_image('annual_cdf', {'series': [
                {'label': 'Solectria', 'x': [259, 270, 286], 'probability': [.1, .5, .9]},
                {'label': 'SolarEdge', 'x': [265, 276, 293], 'probability': [.1, .5, .9]},
            ]}, 3.0)
        canvas = captured[0]
        canvas.draw()
        figure = canvas.figure
        box = figure.axes[0].get_tightbbox(canvas.get_renderer())
        self.assertGreaterEqual(box.x0, 6)
        self.assertGreaterEqual(box.y0, 6)
        self.assertLessEqual(box.x1, figure.bbox.width - 6)
        self.assertLessEqual(box.y1, figure.bbox.height - 6)


if __name__ == '__main__':
    unittest.main()
