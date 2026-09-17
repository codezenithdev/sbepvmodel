"""Report diagnostic checks use hand-computable evidence, never saved outputs."""
import base64
from copy import deepcopy
from io import BytesIO
import unittest

import numpy as np
from PIL import Image
from matplotlib.backends.backend_agg import FigureCanvasAgg

from sbepv import technoeconomic_report_diagnostics as diagnostics


def sensitivity_fixture():
    model = {"status": "available", "sample_count": 80, "final_r_squared": .82,
             "steps": [{"predictor_id": "z", "standardized_beta": -.6},
                       {"predictor_id": "a", "standardized_beta": .6},
                       {"predictor_id": "m", "standardized_beta": -.1}],
             "exclusions": {"fixed": {"reason": "fixed_input"},
                            "constant": {"reason": "constant_predictor"},
                            "small": {"reason": "below_entry_threshold"}},
             "warnings": [{"code": "high_pairwise_rank_correlation", "left_predictor": "a",
                           "right_predictor": "z", "correlation": -.97}]}
    return {"sensitivity": {"commercial_solectria_lifecycle_lcoe": model,
                             "commercial_solaredge_lifecycle_lcoe": deepcopy(model)}}


def convergence_fixture():
    # Original order differs from sorted order; the first two quantiles are
    # 18/50/82 USD/MWh, whereas sorting the full vector first gives 12/20/28.
    by_name = {"realization_index": np.arange(1, 5),
               "sol": np.array([.09, .01, .03, .07]), "se": np.array([.10, .02, .04, .08])}
    metadata = {"convergence": {"status": "not_demonstrated", "reasons": ["example"],
                                 "checkpoints": [{"realization_count": n} for n in (2, 4)]}}
    routine = {"realization_count": 4, "paired_commercial": {"systems": {
        "solectria": {"headline_metric_id": "sol", "percentiles": {"p10": .016, "p50": .05, "p90": .084}},
        "solaredge": {"headline_metric_id": "se", "percentiles": {"p10": .026, "p50": .06, "p90": .094}},
    }}}
    return metadata, by_name, routine


class TornadoTests(unittest.TestCase):
    def test_generic_om_labels_are_qualified_by_saved_system_ownership(self):
        metadata = {"kernel_provenance": {"commercial_paired": {"systems": {}}}, "sensitivity": {}}
        for technology in ("solectria", "solaredge"):
            other = "solaredge" if technology == "solectria" else "solectria"
            identifier = technology + ".maintenance-cost"
            metadata["kernel_provenance"]["commercial_paired"]["systems"][technology] = {"cost_lines": [
                {"input_id": identifier, "label": "Annual operations and maintenance", "cost_category": "full_annual_om"}]}
            metadata["sensitivity"][f"commercial_{technology}_lifecycle_lcoe"] = {
                "status": "available", "sample_count": 200, "final_r_squared": .91,
                "steps": [{"predictor_id": identifier, "standardized_beta": .27}],
                "exclusions": {other + ".maintenance-cost": {"reason": "no_structural_effect"}},
            }
        labels = {technology + ".maintenance-cost": "Annual operations and maintenance" for technology in ("solectria", "solaredge")}
        payloads = diagnostics.tornado_payloads(metadata, input_labels=labels)
        for payload, own, other in zip(payloads, ("Solectria", "SolarEdge"), ("SolarEdge", "Solectria")):
            self.assertEqual(payload["rows"][0]["label"], own + " annual O&M")
            self.assertEqual(payload["rows"][0]["beta"], .27)
            self.assertEqual((payload["sample_count"], payload["r_squared"]), (200, .91))
            self.assertEqual(payload["notes"], [f"{other} annual O&M excluded from the {own} model: no structural effect."])

    def test_request_labels_and_historical_default_ids_avoid_ambiguous_om(self):
        labels = diagnostics.predictor_labels({"systems": [{"technology": "solaredge", "cost_lines": [
            {"input_id": "se-cost", "label": "Annual operations and maintenance", "cost_category": "full_annual_om"},
            {"input_id": "se-replace", "label": "Solaredge replacement", "cost_category": "scheduled_maintenance"}]}]})
        self.assertEqual(labels, {"se-cost": "SolarEdge annual O&M", "se-replace": "SolarEdge replacement"})
        metadata = sensitivity_fixture()
        metadata["sensitivity"]["commercial_solectria_lifecycle_lcoe"]["steps"][0]["predictor_id"] = "solectria.annual-om"
        payload = diagnostics.tornado_payloads(metadata, input_labels={"solectria.annual-om": "Annual operations and maintenance"})[0]
        own = next(row for row in payload["rows"] if row["predictor_id"] == "solectria.annual-om")
        self.assertEqual(own["label"], "Solectria annual O&M")

    def test_signed_coefficients_tie_order_and_model_evidence(self):
        metadata = sensitivity_fixture()
        before = deepcopy(metadata)
        payload = diagnostics.tornado_payloads(metadata, input_labels={"a": "CAPEX"})[0]
        self.assertEqual([row["predictor_id"] for row in payload["rows"]], ["a", "z", "m"])
        self.assertEqual([row["beta"] for row in payload["rows"]], [.6, -.6, -.1])
        self.assertEqual(payload["rows"][0]["label"], "CAPEX")
        self.assertEqual((payload["sample_count"], payload["r_squared"]), (80, .82))
        notes = " ".join(payload["notes"])
        for expected in ("fixed input", "constant predictor", "below entry threshold", "-0.97", "coefficient size and sign"):
            self.assertIn(expected, notes)
        self.assertEqual(metadata, before)

    def test_absent_and_incomplete_coefficients_are_not_zero_bars(self):
        self.assertTrue(all(row["status"] == "unavailable" for row in diagnostics.tornado_payloads({})))
        for steps in ([], [{"predictor_id": "a", "standardized_beta": None}]):
            metadata = sensitivity_fixture()
            metadata["sensitivity"]["commercial_solectria_lifecycle_lcoe"]["steps"] = steps
            result = diagnostics.tornado_payloads(metadata)[0]
            self.assertEqual(result["status"], "unavailable")
            self.assertEqual(result["rows"], [])
            self.assertIn("fixed input", " ".join(result["notes"]))

    def test_saved_unavailable_reason_is_preserved(self):
        metadata = sensitivity_fixture()
        metadata["sensitivity"]["commercial_solectria_lifecycle_lcoe"].update(status="unavailable", reason="constant_response")
        self.assertIn("constant response", diagnostics.tornado_payloads(metadata)[0]["reason"])

    def test_invalid_coefficients_and_duplicate_predictors_fail_closed(self):
        for beta in (float("nan"), float("inf"), "0.4", True):
            metadata = sensitivity_fixture()
            metadata["sensitivity"]["commercial_solectria_lifecycle_lcoe"]["steps"][0]["standardized_beta"] = beta
            with self.assertRaises(diagnostics.ReportDiagnosticsError):
                diagnostics.tornado_payloads(metadata)
        metadata = sensitivity_fixture()
        metadata["sensitivity"]["commercial_solectria_lifecycle_lcoe"]["steps"][0]["predictor_id"] = "a"
        with self.assertRaisesRegex(diagnostics.ReportDiagnosticsError, "duplicated"):
            diagnostics.tornado_payloads(metadata)

    def test_chart_is_zero_centered_with_negative_values_and_readable_labels(self):
        payload = diagnostics.tornado_payloads(sensitivity_fixture())[0]
        figure = diagnostics._tornado_figure(payload)
        axis = figure.axes[0]
        left, right = axis.get_xlim()
        self.assertEqual(-left, right)
        self.assertLess(left, -.6)
        self.assertEqual([bar.get_width() for bar in axis.patches], [.6, -.6, -.1])
        self.assertTrue(axis.yaxis_inverted())
        self.assertIn("n = 80", axis.get_title(loc="left"))
        self.assertIn("R² = 0.82", axis.get_title(loc="left"))
        image = Image.open(BytesIO(base64.b64decode(diagnostics.render_tornado(payload))))
        self.assertGreater(image.width, 2000)
        self.assertGreater(image.height, 800)

    def test_tornado_endpoint_tick_labels_have_room_at_the_image_edge(self):
        metadata = sensitivity_fixture()
        metadata['sensitivity']['commercial_solectria_lifecycle_lcoe']['steps'][0]['standardized_beta'] = .76
        figure = diagnostics._tornado_figure(diagnostics.tornado_payloads(metadata)[0])
        canvas = FigureCanvasAgg(figure)
        canvas.draw()
        bounds = figure.axes[0].get_tightbbox(canvas.get_renderer())
        self.assertGreaterEqual(bounds.x0, 6)
        self.assertLessEqual(bounds.x1, figure.bbox.width - 6)

    def test_large_models_paginate_all_coefficients_on_a_common_scale(self):
        metadata = sensitivity_fixture()
        model = metadata["sensitivity"]["commercial_solectria_lifecycle_lcoe"]
        model["steps"] = [{"predictor_id": f"cost-{i:02d}", "standardized_beta": (-1)**i * (30-i)/30} for i in range(30)]
        panels = [item for item in diagnostics.tornado_payloads(metadata) if item["system"] == "solectria"]
        self.assertGreater(len(panels), 1)
        self.assertEqual([row["predictor_id"] for panel in panels for row in panel["rows"]], [f"cost-{i:02d}" for i in range(30)])
        self.assertTrue(all(panel["height"] <= diagnostics.MAX_TORNADO_HEIGHT for panel in panels))
        self.assertEqual(len({panel["axis_limit"] for panel in panels}), 1)
        self.assertTrue(all(panel["entered_predictor_count"] == 30 for panel in panels))
        self.assertEqual(sum("fixed input" in note for panel in panels for note in panel["notes"]), 1)
        self.assertEqual((panels[0]["rank_start"], panels[-1]["rank_end"]), (1, 30))

    def test_extremely_long_labels_preserve_full_names_in_notes_and_fit_page(self):
        label = "This unusually long saved input label " * 20
        metadata = sensitivity_fixture()
        panels = diagnostics.tornado_payloads(metadata, input_labels={"a": label})
        for panel in panels:
            self.assertLessEqual(panel["height"], diagnostics.MAX_TORNADO_HEIGHT)
            self.assertTrue(all(len(row["display_label"].splitlines()) <= 3 for row in panel["rows"]))
            self.assertIn(label, " ".join(panel["notes"]))


class ConvergenceTests(unittest.TestCase):
    def test_type7_prefixes_preserve_original_order_and_units(self):
        metadata, by_name, routine = convergence_fixture()
        before = deepcopy(metadata)
        result = diagnostics.convergence_payloads(metadata, by_name, routine, row_count=4)
        np.testing.assert_allclose([item["values"] for item in result[0]["series"]], [[18, 16], [50, 50], [82, 84]])
        np.testing.assert_allclose([item["values"] for item in result[1]["series"]], [[28, 26], [60, 60], [92, 94]])
        self.assertEqual(result[0]["checkpoints"], [2, 4])
        self.assertEqual(metadata, before)
        self.assertIn("do not replace", " ".join(result[0]["notes"]))

    def test_existing_checkpoint_tie_outs_detect_changed_prefix_values(self):
        metadata, by_name, routine = convergence_fixture()
        for checkpoint in metadata["convergence"]["checkpoints"]:
            n = checkpoint["realization_count"]
            checkpoint["metrics"] = {"sol": {"population_count": n, "percentiles":
                dict(zip(("p5", "p50", "p95"), np.quantile(by_name["sol"][:n], [.05, .5, .95], method="linear")))}}
        diagnostics.convergence_payloads(metadata, by_name, routine)
        by_name["sol"] = by_name["sol"][[2, 3, 0, 1]]
        with self.assertRaisesRegex(diagnostics.ReportDiagnosticsError, "checkpoint 2"):
            diagnostics.convergence_payloads(metadata, by_name, routine)

    def test_final_points_must_equal_saved_headline_values(self):
        metadata, by_name, routine = convergence_fixture()
        routine["paired_commercial"]["systems"]["solectria"]["percentiles"]["p90"] += .001
        with self.assertRaisesRegex(diagnostics.ReportDiagnosticsError, "final P90"):
            diagnostics.convergence_payloads(metadata, by_name, routine)

    def test_count_order_and_finite_population_are_required(self):
        for change in ("count", "order", "nan", "short", "checkpoints", "checkpoint_bool", "final_checkpoint"):
            metadata, by_name, routine = convergence_fixture()
            if change == "count":
                routine["realization_count"] = 5
            elif change == "order":
                by_name["realization_index"] = np.array([2, 1, 3, 4])
            elif change == "nan":
                by_name["sol"][1] = np.nan
            elif change == "short":
                by_name["se"] = np.array([.1])
            elif change == "checkpoints":
                metadata["convergence"]["checkpoints"].reverse()
            elif change == "checkpoint_bool":
                metadata["convergence"]["checkpoints"][0]["realization_count"] = True
            else:
                metadata["convergence"]["checkpoints"][-1]["realization_count"] = 3
            with self.subTest(change=change), self.assertRaises(diagnostics.ReportDiagnosticsError):
                diagnostics.convergence_payloads(metadata, by_name, routine, row_count=4)

    def test_missing_historical_evidence_has_honest_unavailable_result(self):
        for missing in ("checkpoints", "indices", "values", "percentiles"):
            metadata, by_name, routine = convergence_fixture()
            if missing == "checkpoints":
                metadata = {}
            elif missing == "indices":
                by_name.pop("realization_index")
            elif missing == "values":
                by_name.pop("sol")
            else:
                routine["paired_commercial"]["systems"]["solectria"]["percentiles"].pop("p50")
            with self.subTest(missing=missing):
                result = diagnostics.convergence_payloads(metadata, by_name, routine)
                self.assertEqual(result[0]["status"], "unavailable")
                self.assertFalse(result[0]["series"])

    def test_rendered_lines_match_numeric_payload(self):
        payload = diagnostics.convergence_payloads(*convergence_fixture())[0]
        axis = diagnostics._convergence_figure(payload).axes[0]
        for line, item in zip(axis.lines, payload["series"]):
            np.testing.assert_array_equal(line.get_xdata(), [2, 4])
            np.testing.assert_array_equal(line.get_ydata(), item["values"])
        image = Image.open(BytesIO(base64.b64decode(diagnostics.render_convergence(payload))))
        self.assertGreater(image.width, 2000)
        self.assertGreater(image.height, 900)


class LifecycleCdfTests(unittest.TestCase):
    def fixture(self):
        by_name = {"realization_index": np.arange(1, 5), "sol": np.array([.04, .01, .01, .02]),
                   "se": np.array([.06, .03, .03, .04])}
        systems = {}
        for technology, metric in (("solectria", "sol"), ("solaredge", "se")):
            systems[technology] = {"technology": technology, "headline_metric_id": metric,
                "unit": "constant_usd_per_kwh_ac", "percentiles": dict(zip(("p10", "p50", "p90"),
                    np.quantile(by_name[metric], [.1, .5, .9], method="linear")))}
        metadata = {"kernel_provenance": {"commercial_paired": {"constant_dollar_cost_year": 2024}},
                    "summaries": {"sol": {"count": 4, "cdf": {"values": [.01, .02, .04],
                        "cumulative_probability": [.5, .75, 1], "population_count": 4}}}}
        routine = {"realization_count": 4, "paired_commercial": {"systems": systems, "constant_dollar_cost_year": 2024}}
        return metadata, by_name, routine

    def test_right_continuous_ecdf_ties_units_and_headline_markers(self):
        metadata, by_name, routine = self.fixture()
        before = {key: value.copy() for key, value in by_name.items()}
        result = diagnostics.lifecycle_cdf_payload(metadata, by_name, routine, row_count=4)
        self.assertEqual(result["status"], "available")
        self.assertEqual((result["sample_count"], result["constant_dollar_cost_year"], result["unit"]), (4, 2024, "USD/MWh AC"))
        self.assertEqual(result["series"][0]["values"], [10, 20, 40])
        self.assertEqual(result["series"][0]["probability"], [.5, .75, 1])
        self.assertEqual(result["series"][0]["cumulative_count"], [2, 3, 4])
        np.testing.assert_allclose(list(result["series"][0]["percentiles"].values()), [10, 15, 34])
        self.assertEqual([series["system"] for series in result["series"]], ["solectria", "solaredge"])
        for key, value in before.items():
            np.testing.assert_array_equal(by_name[key], value)

    def test_invalid_units_counts_order_values_and_summaries_fail_closed(self):
        for change in ("unit", "count", "order", "nonfinite", "headline", "sealed_cdf", "dollar_year"):
            metadata, by_name, routine = self.fixture()
            if change == "unit":
                routine["paired_commercial"]["systems"]["solectria"]["unit"] = "USD/MWh"
            elif change == "count":
                routine["realization_count"] = 5
            elif change == "order":
                by_name["realization_index"] = np.array([2, 1, 3, 4])
            elif change == "nonfinite":
                by_name["sol"][0] = np.nan
            elif change == "headline":
                routine["paired_commercial"]["systems"]["solectria"]["percentiles"]["p50"] += .001
            elif change == "sealed_cdf":
                metadata["summaries"]["sol"]["cdf"]["cumulative_probability"][0] = .25
            else:
                routine["paired_commercial"]["constant_dollar_cost_year"] = 2025
            with self.subTest(change=change), self.assertRaises(diagnostics.ReportDiagnosticsError):
                diagnostics.lifecycle_cdf_payload(metadata, by_name, routine, row_count=4)

    def test_missing_evidence_does_not_invent_a_chart(self):
        for missing in ("indices", "values", "unit", "percentiles"):
            metadata, by_name, routine = self.fixture()
            if missing == "indices":
                by_name.pop("realization_index")
            elif missing == "values":
                by_name.pop("se")
            elif missing == "unit":
                routine["paired_commercial"]["systems"]["solaredge"].pop("unit")
            else:
                routine["paired_commercial"]["systems"]["solaredge"]["percentiles"].pop("p90")
            with self.subTest(missing=missing):
                payload = diagnostics.lifecycle_cdf_payload(metadata, by_name, routine)
                self.assertEqual(payload["status"], "unavailable")
                self.assertFalse(payload["series"])

    def test_constant_population_still_displays_its_full_cdf_jump(self):
        metadata, by_name, routine = self.fixture()
        by_name["sol"] = np.full(4, .03)
        metadata.pop("summaries")
        routine["paired_commercial"]["systems"]["solectria"]["percentiles"] = {key: .03 for key in ("p10", "p50", "p90")}
        payload = diagnostics.lifecycle_cdf_payload(metadata, by_name, routine)
        axis = diagnostics._lifecycle_cdf_figure(payload).axes[0]
        self.assertEqual(axis.lines[0].get_drawstyle(), "steps-post")
        np.testing.assert_array_equal(axis.lines[0].get_xdata(), [30, 30])
        np.testing.assert_array_equal(axis.lines[0].get_ydata(), [0, 1])

    def test_report_sized_cdf_render_matches_payload(self):
        payload = diagnostics.lifecycle_cdf_payload(*self.fixture())
        axis = diagnostics._lifecycle_cdf_figure(payload).axes[0]
        for line, series in zip(axis.lines, payload["series"]):
            np.testing.assert_array_equal(line.get_xdata()[1:], series["values"])
            np.testing.assert_array_equal(line.get_ydata()[1:], series["probability"])
            self.assertEqual(line.get_drawstyle(), "steps-post")
        self.assertIn("real 2024 USD/MWh AC", axis.get_xlabel())
        image = Image.open(BytesIO(base64.b64decode(diagnostics.render_lifecycle_cdf(payload))))
        self.assertGreater(image.width, 2000)
        self.assertGreater(image.height, 1000)

    def test_cdf_labels_and_percentile_markers_fit_inside_the_embedded_image(self):
        payload = diagnostics.lifecycle_cdf_payload(*self.fixture())
        figure = diagnostics._lifecycle_cdf_figure(payload)
        canvas = FigureCanvasAgg(figure)
        canvas.draw()
        renderer = canvas.get_renderer()
        axis = figure.axes[0]
        # The tight axes bounds include the actual drawn tick labels, axis
        # titles, chart title and legend, excluding ticks outside the view.
        bounds = [axis.get_tightbbox(renderer)]
        bounds.extend(artist.get_window_extent(renderer) for artist in figure.texts)
        for box in bounds:
            self.assertGreaterEqual(box.x0, 6)
            self.assertGreaterEqual(box.y0, 6)
            self.assertLessEqual(box.x1, figure.bbox.width - 6)
            self.assertLessEqual(box.y1, figure.bbox.height - 6)
        self.assertEqual(len(axis.collections), 6)
        for collection in axis.collections:
            points = collection.get_offset_transform().transform(collection.get_offsets())
            radius = np.sqrt(collection.get_sizes().max()) * figure.dpi / 144
            for x, y in points:
                self.assertGreaterEqual(x - radius, axis.bbox.x0)
                self.assertLessEqual(x + radius, axis.bbox.x1)
                self.assertGreaterEqual(y - radius, axis.bbox.y0)
                self.assertLessEqual(y + radius, axis.bbox.y1)


if __name__ == "__main__":
    unittest.main()
