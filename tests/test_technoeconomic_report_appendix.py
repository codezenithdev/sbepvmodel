"""Frozen-evidence selection and pure presentation behavior of the appendix."""
from copy import deepcopy
import unittest

from sbepv import technoeconomic_report_appendix as appendix


def saved_job():
    model_version, physics_version, fingerprint = next(iter(appendix.DOCUMENTED_PHYSICS))
    temporal_version, temporal_fingerprint = next(iter(appendix.DOCUMENTED_ANNUAL_SEMANTICS))
    return {
        "request": {
            "n": 8000, "seed": (1 << 64) - 1,
            "finance": {"project_life_years": 30, "constant_dollar_cost_year": 2026},
        },
        "source_snapshot": {
            "model_contract": {
                "model_version": model_version,
                "calibration_physics_version": physics_version,
                "calibration_physics_fingerprint": fingerprint,
                "annual_temporal_semantics_version": temporal_version,
                "annual_temporal_semantics_fingerprint": temporal_fingerprint,
            },
            "source_annual_job": {
                "request": {"iam_model": "physical", "backtrack": True,
                            "interval_value": 1, "interval_unit": "hours",
                            "solaredge_inverter_efficiency": .96},
                "result": {"stats": {"solaredge_inverter_efficiency": .973,
                                     "solaredge_bos_efficiency": .987}},
            },
        },
    }


def anchor_set(blocks):
    return {block["anchor"] for block in blocks if block["kind"] == "heading"}


def table_row(blocks, label):
    return next(row for block in blocks if block["kind"] == "table"
                for row in block["rows"] if row[0] == label)


class TechnicalAppendixTests(unittest.TestCase):
    def test_identified_physics_enables_details_without_mutating_saved_evidence(self):
        job = saved_job()
        original = deepcopy(job)
        blocks = appendix.build_technical_appendix(job)
        self.assertEqual(original, job)
        self.assertEqual(blocks, appendix.build_technical_appendix(job))
        self.assertIn("appendix-electrical", anchor_set(blocks))
        self.assertIn("appendix-irradiance", anchor_set(blocks))
        self.assertEqual(len(anchor_set(blocks)), sum(block["kind"] == "heading" for block in blocks))
        for block in blocks:
            if block["kind"] == "table":
                for row in block["rows"]:
                    self.assertEqual(len(block["headers"]), len(row))

    def test_same_version_with_different_or_absent_fingerprint_cannot_claim_physics(self):
        for changed in ({"calibration_physics_fingerprint": "0" * 64},
                        {"calibration_physics_fingerprint": None},
                        {"model_version": "future"}):
            with self.subTest(changed=changed):
                job = saved_job()
                job["source_snapshot"]["model_contract"].update(changed)
                self.assertFalse(appendix.physics_description_supported(job))
                blocks = appendix.build_technical_appendix(job)
                self.assertNotIn("appendix-electrical", anchor_set(blocks))
                self.assertNotIn("appendix-irradiance", anchor_set(blocks))
                self.assertIn("appendix-finance", anchor_set(blocks))

    def test_applied_values_override_request_and_missing_values_are_not_defaults(self):
        blocks = appendix.build_technical_appendix(saved_job())
        self.assertEqual("0.973 / 0.987", table_row(blocks, "SolarEdge inverter / BOS efficiencies")[1])
        self.assertEqual("Not recorded / Not recorded", table_row(blocks, "Solectria inverter / BOS efficiencies")[1])
        self.assertEqual("8000 / 18446744073709551615", table_row(blocks, "Realizations / random seed")[1])
        self.assertEqual("Not applicable", table_row(blocks, "Martin-Ruiz coefficient a_r")[1])
        self.assertEqual("1 hour", table_row(blocks, "Weather interval")[1])

    def test_unknown_physics_and_missing_optional_records_render_without_live_model(self):
        blocks = appendix.build_technical_appendix({})
        self.assertNotIn("appendix-electrical", anchor_set(blocks))
        self.assertEqual("Not recorded", table_row(blocks, "PV model version")[1])
        self.assertEqual("Not recorded", table_row(blocks, "Real discount rate r (fraction/year)")[1])
        self.assertTrue(all(block["kind"] in {"heading", "paragraph", "table"} for block in blocks))

    def test_applied_factors_use_resolved_profile_and_recorded_substitution_not_original_fit(self):
        job = saved_job()
        origin = {"spring": {"solectria": .98, "solaredge": 1.02},
                  "summer": {"solectria": .94, "solaredge": .97}}
        resolved = deepcopy(origin)
        resolved["fall"] = deepcopy(origin["spring"])
        job["source_snapshot"]["calibration_lineage"] = {
            "origin_profile": {"seasonal_factors": origin},
            "resolved_profile": {"seasonal_factors": resolved},
            "application": {"seasonal_substitution": {
                "source_season": "spring", "target_season": "fall",
                "factors": deepcopy(origin["spring"]), "explicitly_accepted": True,
            }},
        }
        original = deepcopy(job)
        self.assertTrue(appendix.physics_description_supported(job))
        blocks = appendix.applied_calibration_blocks(job)
        self.assertEqual(["Fall", "0.9800", "1.0200", "Recorded substitute from Spring"], table_row(blocks, "Fall"))
        self.assertEqual(["Winter", "Not recorded", "Not recorded", "Not recorded"], table_row(blocks, "Winter"))
        self.assertEqual(original, job)
        self.assertNotIn("fall", job["source_snapshot"]["calibration_lineage"]["origin_profile"]["seasonal_factors"])

    def test_missing_resolved_profile_is_not_filled_from_original_factors(self):
        job = {"source_snapshot": {"calibration_lineage": {
            "origin_profile": {"seasonal_factors": {"fall": {"solectria": .87, "solaredge": .92}}},
        }}}
        blocks = appendix.applied_calibration_blocks(job)
        self.assertFalse(any(block["kind"] == "table" for block in blocks))
        self.assertTrue(any("unavailable" in block.get("text", "") for block in blocks))
        self.assertTrue(any("status is not recorded" in block.get("text", "") for block in blocks))

    def test_saved_receipt_and_canonical_profile_substitution_are_both_supported(self):
        for evidence, substitution in (
            ("result_application", {"source_season": "spring", "target_season": "fall", "explicitly_accepted": True}),
            ("resolved_profile", {"from_season": "spring", "to_season": "fall"}),
            ("resolved_profile", {"mapping": "fall<-spring"}),
        ):
            with self.subTest(evidence=evidence, substitution=substitution):
                lineage = {"resolved_profile": {"seasonal_factors": {"fall": {"solectria": .9, "solaredge": .95}}}}
                lineage.setdefault(evidence, {})["seasonal_substitution"] = substitution
                blocks = appendix.applied_calibration_blocks({"source_snapshot": {"calibration_lineage": lineage}})
                self.assertEqual("Recorded substitute from Spring", table_row(blocks, "Fall")[3])
                if evidence == "resolved_profile":
                    self.assertTrue(any("acceptance is not recorded" in block.get("text", "") for block in blocks))

    def test_factor_equality_uses_saved_precision_before_four_decimal_display(self):
        factors = {"fall": {"solectria": .951234, "solaredge": .783456}}
        job = {"source_snapshot": {"calibration_lineage": {
            "origin_profile": {"seasonal_factors": deepcopy(factors)},
            "resolved_profile": {"seasonal_factors": deepcopy(factors)},
            "application": {"seasonal_substitution": None},
        }}}
        blocks = appendix.applied_calibration_blocks(job)
        self.assertEqual(["0.9512", "0.7835"], table_row(blocks, "Fall")[1:3])
        self.assertTrue(any("equal the original fitted" in b.get("text", "") for b in blocks))
        self.assertTrue(any("no seasonal substitution" in b.get("text", "") for b in blocks))
        job["source_snapshot"]["calibration_lineage"]["resolved_profile"]["seasonal_factors"]["fall"]["solectria"] = .951235
        original = deepcopy(job)
        blocks = appendix.applied_calibration_blocks(job)
        self.assertEqual(["0.9512", "0.7835"], table_row(blocks, "Fall")[1:3])
        self.assertFalse(any("equal the original fitted" in b.get("text", "") for b in blocks))
        self.assertEqual(original, job)

    def test_confirmed_equal_complete_profile_uses_one_paragraph_without_duplicate_table(self):
        factors = {season: {"solectria": .951234, "solaredge": .783456}
                   for season in ("winter", "spring", "summer", "fall")}
        lineage = {
            "origin_profile": {"seasonal_factors": deepcopy(factors)},
            "resolved_profile": {"seasonal_factors": deepcopy(factors)},
            "application": {"seasonal_substitution": None},
        }
        job = {"source_snapshot": {"calibration_lineage": lineage}}
        blocks = appendix.applied_calibration_blocks(job)
        self.assertEqual(["paragraph"], [block["kind"] for block in blocks])
        self.assertIn("all four seasons", blocks[0]["text"])
        self.assertIn("no seasonal substitution", blocks[0]["text"])
        lineage["resolved_profile"]["seasonal_factors"]["fall"]["solectria"] += .000001
        self.assertTrue(any(block["kind"] == "table" for block in appendix.applied_calibration_blocks(job)))
        lineage["resolved_profile"]["seasonal_factors"] = deepcopy(factors)
        lineage.pop("application")
        self.assertTrue(any(block["kind"] == "table" for block in appendix.applied_calibration_blocks(job)))


if __name__ == "__main__":
    unittest.main()
