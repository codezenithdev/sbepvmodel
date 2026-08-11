from __future__ import annotations

import unittest

from tools import bazefield_quality_factor_comparison as comparison


class BazefieldQualityFactorComparisonTests(unittest.TestCase):
    def _samples(self, quality=524480, *, timestamp_ms=0):
        return [
            {
                "objectId": object_id,
                "pointName": point,
                "t_ms": timestamp_ms,
                "quality": quality,
                "value": 1.5 if "power" in column else 10.0,
            }
            for object_id, point, column in comparison.bazefield.COLUMN_MAP
        ]

    def _index(self, rows):
        return comparison.index_samples(
            rows,
            start_ms=0,
            end_ms=900_000,
            interval_seconds=900,
        )

    def test_decodes_composite_primary_quality_without_treating_one_as_good(self):
        self.assertEqual(comparison.primary_quality(524480), 192)
        self.assertEqual(comparison.primary_quality(524352), 64)
        self.assertTrue(comparison.is_primary_good(524480))
        self.assertFalse(comparison.is_primary_good(1))
        self.assertEqual(comparison.primary_quality_label(0x80), "unknown")
        self.assertTrue(comparison.is_literal_quality_one("1"))
        self.assertFalse(comparison.is_literal_quality_one(524480))

    def test_all_seven_samples_must_pass_the_selected_quality_rule(self):
        rows = self._samples()
        rows[0]["quality"] = 524352
        buckets, _ = self._index(rows)

        accepted, rejected = comparison.eligible_timestamps(
            buckets,
            required_quality_columns=comparison.ALL_COLUMNS,
            quality_rule=comparison.is_primary_good,
        )

        self.assertEqual(accepted, set())
        self.assertEqual(rejected, {"quality_rule_failed": 1})

    def test_missing_nonfinite_and_duplicate_samples_are_not_model_rows(self):
        cases = []
        missing = self._samples()[:-1]
        cases.append(missing)
        nonfinite = self._samples()
        nonfinite[-1]["value"] = float("nan")
        cases.append(nonfinite)
        duplicate = self._samples()
        duplicate.append(dict(duplicate[-1]))
        cases.append(duplicate)

        for rows in cases:
            with self.subTest(row_count=len(rows)):
                buckets, _ = self._index(rows)
                accepted, rejected = comparison.eligible_timestamps(
                    buckets,
                    required_quality_columns=comparison.ALL_COLUMNS,
                    quality_rule=comparison.is_primary_good,
                )
                self.assertEqual(accepted, set())
                self.assertEqual(sum(rejected.values()), 1)

    def test_end_boundary_is_excluded_and_power_is_converted_to_watts(self):
        rows = self._samples(timestamp_ms=0) + self._samples(timestamp_ms=900_000)
        buckets, diagnostics = self._index(rows)
        accepted, _ = comparison.eligible_timestamps(
            buckets,
            required_quality_columns=comparison.ALL_COLUMNS,
            quality_rule=comparison.is_primary_good,
        )
        wide = comparison.wide_rows(buckets, accepted)

        self.assertEqual(accepted, {0})
        self.assertEqual(diagnostics["outside_window_sample_count"], 7)
        self.assertEqual(wide[0]["solaredge_measured_power"], 1500.0)
        self.assertEqual(wide[0]["solectria_measured_power"], 1500.0)

    def test_system_specific_rule_ignores_other_system_quality(self):
        rows = self._samples()
        rows[0]["quality"] = 524352  # SolarEdge power is uncertain.
        buckets, _ = self._index(rows)
        solectria_columns = (*comparison.WEATHER_COLUMNS, comparison.POWER_COLUMNS["solectria"])
        accepted, _ = comparison.eligible_timestamps(
            buckets,
            required_quality_columns=solectria_columns,
            quality_rule=comparison.is_primary_good,
        )

        self.assertEqual(accepted, {0})

    def test_good_quality_does_not_hide_physical_bound_violation(self):
        rows = self._samples()
        temperature = next(row for row in rows if row["pointName"] == "AmbientTemp")
        temperature["value"] = -394.6
        buckets, _ = self._index(rows)

        violations = comparison.domain_bound_violations(buckets, {0})

        self.assertEqual(violations["temp_air"]["row_count"], 1)
        self.assertEqual(violations["temp_air"]["minimum_observed"], -394.6)

    def test_analysis_directory_supports_the_temporary_csv_workflow(self):
        with comparison.temporary_working_csv() as path:
            path.write_text("timestamp\n", encoding="utf-8")
            self.assertEqual(path.read_text(encoding="utf-8"), "timestamp\n")
        self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
