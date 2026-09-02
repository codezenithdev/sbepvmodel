from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from sbepv.ingest import bazefield
from sbepv.ingest import collection


def _timestamp_ms(value: str) -> int:
    return int(datetime.fromisoformat(value).replace(tzinfo=timezone.utc).timestamp() * 1_000)


class CollectDataIngestTests(unittest.TestCase):
    def _response(self) -> dict:
        first = _timestamp_ms("2026-06-01T06:00:00")
        second = _timestamp_ms("2026-06-01T07:00:00")

        def block(object_id, point, values, qualities):
            return [{
                "aggregate": "TIMEAVERAGE",
                "timeSeries": [
                    {
                        "objectId": object_id,
                        "pointName": point,
                        "t": timestamp,
                        "q": quality,
                        "v": value,
                    }
                    for timestamp, value, quality in zip(
                        (first, second), values, qualities, strict=True
                    )
                ],
            }]

        weather_id = "1418E76F0E846000"
        return {
            "objects": {
                "141A49D30A046000": {
                    "points": {
                        "ActivePower": block(
                            "141A49D30A046000",
                            "ActivePower",
                            (10.0, 11.0),
                            (524480, 524480),
                        )
                    }
                },
                weather_id: {
                    "points": {
                        "DNI": block(
                            weather_id, "DNI", (500.0, 1600.0), (524480, 524480)
                        ),
                        "GHI": block(
                            weather_id, "GHI", (400.0, 450.0), (524480, 524352)
                        ),
                        "DHI": block(
                            weather_id, "DHI", (100.0, 110.0), (524480, 524480)
                        ),
                        "AmbientTemp": block(
                            weather_id, "AmbientTemp", (20.0, 21.0), (524480, 524480)
                        ),
                        "WindSpeed": [{
                            "aggregate": "TIMEAVERAGE",
                            "timeSeries": [{
                                "objectId": weather_id,
                                "pointName": "WindSpeed",
                                "t": first,
                                "q": 524480,
                                "v": 2.0,
                            }],
                        }],
                    }
                },
            }
        }

    def test_selected_collection_preserves_flags_and_reports_quality(self) -> None:
        client = Mock()
        client.get_historian.return_value = self._response()
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "selected.csv"
            with patch.object(bazefield, "BazefieldClient", return_value=client):
                result = collection.collect_historian_data(
                    from_time="2026-06-01T06:00:00",
                    to_time="2026-06-01T08:00:00",
                    interval_seconds=3600,
                    data_groups=["weather", "solaredge"],
                    output_csv=output,
                    api_key="test-key",
                    base_url="https://bazefield.test/api",
                )

            with output.open(newline="", encoding="utf-8") as source:
                rows = list(csv.DictReader(source))

        client.get_historian.assert_called_once_with(
            object_ids="141A49D30A046000,1418E76F0E846000",
            points="ActivePower,DNI,GHI,DHI,AmbientTemp,WindSpeed",
            aggregates="TIMEAVERAGE",
            frm="2026-06-01T06:00:00",
            to="2026-06-01T08:00:00",
            interval="3600",
        )
        self.assertEqual(result["row_count"], 2)
        self.assertEqual(
            [item["id"] for item in result["data_groups"]],
            ["solaredge", "weather"],
        )
        self.assertNotIn("solectria_measured_power", rows[0])
        self.assertEqual(rows[0]["solaredge_measured_power"], "10000.0")
        self.assertEqual(rows[0]["solaredge_measured_power_quality_code"], "524480")
        self.assertEqual(rows[0]["solaredge_measured_power_quality"], "good")
        self.assertEqual(rows[1]["ghi_quality"], "uncertain")

        issue_keys = {
            (item["code"], item.get("series"))
            for item in result["quality"]["issues"]
        }
        self.assertIn(("missing_samples", "wind_speed"), issue_keys)
        self.assertIn(("non_good_source_quality", "ghi"), issue_keys)
        self.assertIn(("domain_bound_violations", "dni"), issue_keys)
        self.assertEqual(
            result["quality"]["summary"]["timestamp_coverage_percent"], 100.0
        )
        self.assertEqual(
            result["quality"]["summary"]["sample_presence_percent"], 91.7
        )
        self.assertEqual(
            result["quality"]["summary"]["usable_value_completeness_percent"],
            91.7,
        )

    def test_empty_successful_response_exports_headers_and_missingness(self) -> None:
        client = Mock()
        client.get_historian.return_value = {"objects": {}}
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "empty.csv"
            with patch.object(bazefield, "BazefieldClient", return_value=client):
                result = collection.collect_historian_data(
                    from_time="2026-06-01T06:00:00",
                    to_time="2026-06-01T08:00:00",
                    interval_seconds=3600,
                    data_groups=["solaredge"],
                    output_csv=output,
                    api_key="test-key",
                )
            exported = output.read_text(encoding="utf-8")

        self.assertEqual(result["row_count"], 0)
        self.assertEqual(
            result["quality"]["summary"]["usable_value_completeness_percent"],
            0.0,
        )
        self.assertEqual(
            result["quality"]["summary"]["missing_timestamp_count"], 2
        )
        self.assertIn("timestamp,solaredge_measured_power", exported)

    def test_present_nonfinite_value_is_not_counted_as_usable(self) -> None:
        report = collection._quality_report(
            {
                _timestamp_ms("2026-06-01T06:00:00"): {
                    "solaredge_measured_power": [
                        {"value": None, "quality": 524480}
                    ]
                }
            },
            ["solaredge_measured_power"],
            expected_timestamp_count=1,
            invalid_timestamp_sample_count=0,
            outside_window_sample_count=0,
            off_grid_sample_count=0,
        )

        summary = report["summary"]
        self.assertEqual(summary["timestamp_coverage_percent"], 100.0)
        self.assertEqual(summary["sample_presence_percent"], 100.0)
        self.assertEqual(summary["usable_value_completeness_percent"], 0.0)
        self.assertEqual(summary["nonfinite_value_count"], 1)

    def test_quality_decoder_uses_composite_primary_bits(self) -> None:
        self.assertEqual(collection.primary_quality_label(524480), "good")
        self.assertEqual(collection.primary_quality_label(524352), "uncertain")
        self.assertEqual(collection.primary_quality_label(524288), "bad")
        self.assertEqual(collection.primary_quality_label(1), "bad")

    def test_group_selection_rejects_empty_and_unknown_values(self) -> None:
        with self.assertRaisesRegex(bazefield.BazefieldError, "at least one"):
            collection.selected_series([])
        with self.assertRaisesRegex(bazefield.BazefieldError, "Unknown data group"):
            collection.selected_series(["model-output"])


if __name__ == "__main__":
    unittest.main()
