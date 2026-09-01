from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
import sys
import types
import unittest
from unittest.mock import patch

from sbepv.agent import chat, technoeconomic_evidence
from sbepv.agent.tool_schemas import TECHNOECONOMIC_EVIDENCE_TOOL
from sbepv.api import state
from sbepv.api.schemas import ChatRequest


def _sha256(value):
    text = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class TechnoeconomicAgentEvidenceTests(unittest.TestCase):
    JOB_ID = "tea_agent_evidence_visible"
    OTHER_JOB_ID = "tea_agent_evidence_other"

    def setUp(self):
        os.environ["OPENAI_API_KEY"] = "test-placeholder"
        self.request = {
            "source_annual_job_id": "annual-source",
            "n": 1000,
            "project_life_years": 30,
            "paired_commercial": {
                "target_capacity": {"value": 100.0, "unit": "mw"},
                "systems": [
                    {
                        "technology": "solectria",
                        "cost_lines": [
                            {
                                "input_id": "solectria_capex",
                                "category": "full_initial_capex",
                                "unit": "constant_usd_per_target_w",
                                "distribution": {"kind": "fixed", "value": 1.56},
                            }
                        ],
                    },
                    {
                        "technology": "solaredge",
                        "cost_lines": [
                            {
                                "input_id": "solaredge_om",
                                "category": "full_annual_om",
                                "unit": "constant_usd_per_target_w_year",
                                "distribution": {"kind": "fixed", "value": 0.022},
                            }
                        ],
                    },
                ],
            },
        }
        self.snapshot = {
            "schema_version": 1,
            "eligibility_version": "tea-annual-source-v1",
            "source_annual_job_id": "annual-source",
            "capacity_manifest": {
                "solectria": {"installed_wdc": 139_180.8},
                "solaredge": {"installed_wdc": 139_180.8},
            },
            "eligible_paired_energy_rows": [
                {
                    "year": 2024,
                    "sol_predicted_kwh": 200_000.0,
                    "se_predicted_kwh": 215_000.0,
                }
            ],
            "midc_source_artifact": {
                "storage_key": "private/source.csv",
                "path": r"C:\private\source.csv",
                "sha256": "1" * 64,
            },
        }
        self.submission = {
            "request_sha256": _sha256(self.request),
            "source_snapshot_sha256": _sha256(self.snapshot),
            "paired_commercial_receipt": {
                "target_capacity_w": 100_000_000.0,
                "storage_key": "private/receipt.json",
            },
        }
        self.formula = (
            "commercial_solaredge_lifecycle_cost_USD / "
            "commercial_solaredge_lifecycle_energy_kWh_AC"
        )
        cdf_values = [index / 10_000 for index in range(300)]
        cdf_probability = [(index + 1) / 300 for index in range(300)]
        self.result = {
            "schema_version": 5,
            "calculation_contract_version": "tea-commercial-paired-v1",
            "analysis_basis": "commercial_representative",
            "project_life_years": 30,
            "realization_count": 1000,
            "eligible_weather_years": [2024],
            "energy_available": True,
            "applied_capacities": {
                "solectria": {
                    "applied_capacity_w": 125_000.0,
                    "rating_basis": "ac_operating_limit",
                },
                "solaredge": {
                    "applied_capacity_w": 125_000.0,
                    "rating_basis": "ac_operating_limit",
                },
            },
            "summaries": {
                "commercial_solaredge_lifecycle_lcoe_USD_per_kWh_AC": {
                    "percentiles": {"p10": 0.058, "p50": 0.061, "p90": 0.066},
                    "cdf": {
                        "population_count": 1000,
                        "point_count": 300,
                        "storage": "sealed_calculation_payload",
                    },
                }
            },
            "paired_commercial": {
                "target_capacity_w": 100_000_000.0,
                "target_rating_basis": "ac_operating_limit",
                "transfer_method": "direct_capacity_scaling",
                "constant_dollar_cost_year": 2022,
                "systems": {
                    technology: {
                        "technology": technology,
                        "source_applied_capacity_w": 125_000.0,
                        "source_rating_basis": "ac_operating_limit",
                        "capacity_scale_factor": 800.0,
                        "headline_metric_id": (
                            f"commercial_{technology}_lifecycle_lcoe_USD_per_kWh_AC"
                        ),
                        "unit": "constant_usd_per_kwh_ac",
                        "percentiles": {
                            "p10": 0.058,
                            "p50": 0.061,
                            "p90": 0.066,
                        },
                        "cdf": {
                            "population_count": 1000,
                            "source_point_count": 300,
                            "display_point_count": 300,
                            "values": cdf_values,
                            "cumulative_probability": cdf_probability,
                            "full_cdf_sha256": technology[0] * 64,
                            "full_storage": "sealed_calculation_payload",
                        },
                        "commercial_cost_line_summaries": [
                            {
                                "input_id": f"{technology}_capex",
                                "p50": 156_000_000.0,
                            }
                        ],
                    }
                    for technology in ("solectria", "solaredge")
                },
                "lcoe_delta_se_minus_sol": {
                    "headline_metric_id": "commercial_lcoe_delta_se_minus_sol",
                    "unit": "constant_usd_per_kwh_ac",
                    "percentiles": {"p10": -0.002, "p50": -0.001, "p90": 0.001},
                },
            },
            "per_weather_year": [
                {
                    "year": 2024,
                    "realization_count": 1000,
                    "realization_share": 1.0,
                    "metrics": {
                        "commercial_solaredge_lifecycle_lcoe_USD_per_kWh_AC": {
                            "count": 1000,
                            "percentiles": {
                                "p10": 0.058,
                                "p50": 0.061,
                                "p90": 0.066,
                            },
                            "status": "available",
                        }
                    },
                    "systems": {
                        "solaredge": {
                            "source_predicted_kwh_ac": 215_000.0,
                            "target_year1_energy_kwh_ac": 172_000_000.0,
                        }
                    },
                }
            ],
            "convergence": {"status": "converged"},
            "exports": {
                "manifest_sha256": "e" * 64,
                "artifacts": {
                    "csv_bundle": {
                        "url": "/outputs/tea/results.zip",
                        "storage_key": "private/results.zip",
                    }
                },
            },
        }
        self.provenance = {
            "request_sha256": _sha256(self.request),
            "source_snapshot_sha256": _sha256(self.snapshot),
            "submission_provenance_sha256": _sha256(self.submission),
            "validated_kernel_request_sha256": "k" * 64,
            "routine_result_sha256": _sha256(self.result),
            "source_artifact": {
                "sha256": "1" * 64,
                "byte_count": 1234,
                "media_type": "text/csv",
                "storage_key": "private/source.csv",
                "path": r"C:\private\source.csv",
            },
            "exports": {"manifest_sha256": "e" * 64, "artifact_count": 5},
            "kernel": {
                "calculation_contract_version": "tea-commercial-paired-v1",
                "statistics": {
                    "quantiles": "hyndman-fan-type-7",
                    "ecdf": "right-continuous-ties-collapsed",
                },
                "commercial_paired": {
                    "systems": {
                        "solaredge": {"lcoe_formula": self.formula},
                        "solectria": {
                            "lcoe_formula": (
                                "commercial_solectria_lifecycle_cost_USD / "
                                "commercial_solectria_lifecycle_energy_kWh_AC"
                            )
                        },
                    },
                    "lcoe_delta_formula": (
                        "commercial_solaredge_lifecycle_lcoe_USD_per_kWh_AC - "
                        "commercial_solectria_lifecycle_lcoe_USD_per_kWh_AC"
                    ),
                    "cdf": "right-continuous-ties-collapsed",
                },
            },
        }
        self.job = {
            "id": self.JOB_ID,
            "state": "done",
            "stage": "Done",
            "source_annual_job_id": "annual-source",
            "source_snapshot_sha256": _sha256(self.snapshot),
            "submission_provenance_sha256": _sha256(self.submission),
            "request": self.request,
            "source_snapshot": self.snapshot,
            "submission_provenance": self.submission,
            "result": self.result,
            "result_provenance": self.provenance,
        }

    def visible_config(self, **forged):
        visible = {"job_id": self.JOB_ID, **forged}
        return {"technoeconomic_analysis": visible}

    def test_tool_schema_is_strict_and_has_no_job_selector(self):
        schema = TECHNOECONOMIC_EVIDENCE_TOOL["parameters"]

        self.assertEqual("get_technoeconomic_evidence", TECHNOECONOMIC_EVIDENCE_TOOL["name"])
        self.assertTrue(TECHNOECONOMIC_EVIDENCE_TOOL["strict"])
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual({"section", "metric_id"}, set(schema["properties"]))
        self.assertNotIn("job_id", schema["properties"])
        self.assertEqual(
            set(technoeconomic_evidence.EVIDENCE_SECTIONS),
            set(schema["properties"]["section"]["enum"]),
        )

    def test_formulas_come_from_durable_provenance_and_forged_values_are_ignored(self):
        current_config = self.visible_config(
            formulas={"solaredge": "forged formula"},
            summaries={"lcoe": {"p50": 999}},
        )
        with patch.object(
            state.AGENT_STORE, "get_technoeconomic_job", return_value=self.job
        ) as read_job:
            evidence = technoeconomic_evidence.get_technoeconomic_evidence(
                current_config,
                {"section": "formulas", "metric_id": None},
            )

        read_job.assert_called_once_with(self.JOB_ID)
        self.assertEqual("available", evidence["status"])
        self.assertEqual(
            self.formula,
            evidence["data"]["commercial_paired"]["systems"]["solaredge"][
                "lcoe_formula"
            ],
        )
        serialized = json.dumps(evidence)
        self.assertNotIn("forged formula", serialized)
        self.assertNotIn('"p50": 999', serialized)
        self.assertNotIn("storage_key", serialized)
        self.assertNotIn(r"C:\private", serialized)

    def test_tool_arguments_cannot_select_another_job(self):
        with patch.object(
            state.AGENT_STORE, "get_technoeconomic_job"
        ) as read_job:
            evidence = technoeconomic_evidence.get_technoeconomic_evidence(
                self.visible_config(),
                {
                    "section": "overview",
                    "metric_id": None,
                    "job_id": self.OTHER_JOB_ID,
                },
            )

        read_job.assert_not_called()
        self.assertEqual("unavailable", evidence["status"])
        self.assertEqual("unsupported_tool_argument", evidence["reason"])

    def test_chart_is_bounded_and_tied_to_the_saved_result(self):
        with patch.object(
            state.AGENT_STORE, "get_technoeconomic_job", return_value=self.job
        ):
            evidence = technoeconomic_evidence.get_technoeconomic_evidence(
                self.visible_config(),
                {"section": "chart", "metric_id": None},
            )

        chart = evidence["data"]["systems"]["solaredge"]
        self.assertEqual("right-continuous-ties-collapsed", evidence["data"]["curve_definition"])
        self.assertEqual({"p10": 0.058, "p50": 0.061, "p90": 0.066}, chart["percentiles"])
        self.assertEqual(
            technoeconomic_evidence.MAX_CHART_POINTS_PER_SERIES,
            chart["cdf"]["returned_point_count"],
        )
        self.assertEqual(self.result["paired_commercial"]["systems"]["solaredge"]["cdf"]["values"][0], chart["cdf"]["values"][0])
        self.assertEqual(self.result["paired_commercial"]["systems"]["solaredge"]["cdf"]["values"][-1], chart["cdf"]["values"][-1])

    def test_integrity_mismatch_fails_closed(self):
        tampered = deepcopy(self.job)
        tampered["result"]["paired_commercial"]["target_capacity_w"] = 75_000_000.0
        with patch.object(
            state.AGENT_STORE, "get_technoeconomic_job", return_value=tampered
        ):
            evidence = technoeconomic_evidence.get_technoeconomic_evidence(
                self.visible_config(),
                {"section": "overview", "metric_id": None},
            )

        self.assertEqual("unavailable", evidence["status"])
        self.assertEqual("integrity_hash_check_failed", evidence["reason"])

    def test_metric_returns_saved_overall_and_weather_year_summaries(self):
        metric_id = "commercial_solaredge_lifecycle_lcoe_USD_per_kWh_AC"
        with patch.object(
            state.AGENT_STORE, "get_technoeconomic_job", return_value=self.job
        ):
            evidence = technoeconomic_evidence.get_technoeconomic_evidence(
                self.visible_config(),
                {"section": "metric", "metric_id": metric_id},
            )

        self.assertEqual(
            {"p10": 0.058, "p50": 0.061, "p90": 0.066},
            evidence["data"]["overall_summary"]["percentiles"],
        )
        self.assertEqual(2024, evidence["data"]["per_weather_year"][0]["year"])
        self.assertEqual(
            0.061,
            evidence["data"]["per_weather_year"][0]["summary"]["percentiles"][
                "p50"
            ],
        )

    def test_source_and_export_sections_remove_private_locations(self):
        with patch.object(
            state.AGENT_STORE, "get_technoeconomic_job", return_value=self.job
        ):
            source = technoeconomic_evidence.get_technoeconomic_evidence(
                self.visible_config(),
                {"section": "source", "metric_id": None},
            )
            exports = technoeconomic_evidence.get_technoeconomic_evidence(
                self.visible_config(),
                {"section": "exports", "metric_id": None},
            )

        serialized = json.dumps({"source": source, "exports": exports})
        self.assertNotIn("storage_key", serialized)
        self.assertNotIn(r"C:\private", serialized)
        self.assertNotIn("private/source.csv", serialized)
        self.assertEqual(
            "1" * 64,
            source["data"]["source_artifact_identity"]["sha256"],
        )
        self.assertEqual(
            "/outputs/tea/results.zip",
            exports["data"]["public_manifest"]["artifacts"]["csv_bundle"]["url"],
        )

    def test_responses_loop_returns_tool_output_to_the_model_once(self):
        function_call = {
            "type": "function_call",
            "name": "get_technoeconomic_evidence",
            "call_id": "call-tea-1",
            "arguments": json.dumps({"section": "formulas", "metric_id": None}),
        }
        responses = [
            types.SimpleNamespace(output=[function_call], output_text=""),
            types.SimpleNamespace(
                output=[],
                output_text=(
                    f"Saved formula from {self.JOB_ID}; request hash "
                    f"{self.provenance['request_sha256']}."
                ),
            ),
        ]
        api_calls = []

        def create_response(**kwargs):
            api_calls.append(kwargs)
            return responses.pop(0)

        fake_client = types.SimpleNamespace(
            responses=types.SimpleNamespace(create=create_response)
        )
        fake_openai = types.ModuleType("openai")
        fake_openai.OpenAI = lambda **_kwargs: fake_client

        with (
            patch.object(
                state.AGENT_STORE,
                "get_technoeconomic_job",
                return_value=self.job,
            ),
            patch.dict(sys.modules, {"openai": fake_openai}),
        ):
            response = chat._openai_agent_response(
                ChatRequest(
                    message="Show the exact SolarEdge LCOE formula.",
                    current_config=self.visible_config(formula="forged"),
                    allow_scenario_actions=False,
                )
            )

        self.assertEqual(2, len(api_calls))
        self.assertIn(TECHNOECONOMIC_EVIDENCE_TOOL, api_calls[0]["tools"])
        self.assertEqual([], api_calls[1]["tools"])
        self.assertEqual("function_call_output", api_calls[1]["input"][-1]["type"])
        returned = json.loads(api_calls[1]["input"][-1]["output"])
        self.assertEqual(self.JOB_ID, returned["job_id"])
        self.assertEqual(self.formula, returned["data"]["commercial_paired"]["systems"]["solaredge"]["lcoe_formula"])
        self.assertIn(self.JOB_ID, response["reply"])
        self.assertIsNone(response["action"])
        self.assertIn("Never calculate P50 LCOE", api_calls[0]["instructions"])


if __name__ == "__main__":
    unittest.main()
