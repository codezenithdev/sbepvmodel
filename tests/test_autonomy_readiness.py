from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import unittest
from unittest.mock import patch

from sbepv.api import config, security
from sbepv.autonomy import readiness, recommendation


class _ReadinessStore:
    def __init__(
        self,
        case: dict,
        *,
        assets=None,
        jobs=None,
        tea_jobs=None,
        annual=None,
        scenarios=None,
    ):
        self.case = deepcopy(case)
        self.assets = deepcopy(assets or [])
        self.jobs = deepcopy(jobs or [])
        self.tea_jobs = deepcopy(tea_jobs or [])
        self.annual = deepcopy(annual)
        self.scenarios = deepcopy(scenarios or [])

    def get_decision_case(self, case_id):
        return deepcopy(self.case) if case_id == self.case["id"] else None

    def list_decision_evidence_assets(self, case_id, **_kwargs):
        if case_id != self.case["id"]:
            raise AssertionError("wrong case")
        return deepcopy(self.assets)

    def list_jobs(self, *, states=None, mode=None, limit=100, **_kwargs):
        rows = self.jobs
        if states:
            rows = [item for item in rows if item.get("state") in states]
        if mode:
            rows = [item for item in rows if item.get("mode") == mode]
        return deepcopy(rows)

    def list_technoeconomic_jobs(self, *, states=None, limit=100, **_kwargs):
        rows = self.tea_jobs
        if states:
            rows = [item for item in rows if item.get("state") in states]
        return deepcopy(rows)

    def get_job(self, job_id):
        if self.annual and self.annual.get("id") == job_id:
            return deepcopy(self.annual)
        return next((deepcopy(item) for item in self.jobs if item.get("id") == job_id), None)

    def list_decision_scenarios(self, case_id, **_kwargs):
        if case_id != self.case["id"]:
            raise AssertionError("wrong case")
        return deepcopy(self.scenarios)


def _case(**overrides):
    value = {
        "id": "case_abc123",
        "title": "Inverter decision",
        "original_question": "Which architecture is supported?",
        "question": "Which architecture is supported?",
        "status": "evidence_needed",
        "source_annual_job_id": None,
        "source_snapshot_sha256": None,
        "analysis_basis": None,
        "source_basis_locked_at": None,
        "source_basis_locked_by": None,
        "decision_owner": "Jordan",
        "active_recommendation_revision": None,
        "revision": 3,
        "created_by": "Jordan",
        "updated_by": "Jordan",
        "created_at": "2026-08-29T12:00:00+00:00",
        "updated_at": "2026-08-29T12:00:00+00:00",
        "archived_at": None,
    }
    value.update(overrides)
    return value


def _source(job_id="annual_verified", completed_at="2026-08-28T00:00:00+00:00"):
    return {
        "eligible": True,
        "annual_job_id": job_id,
        "completed_at": completed_at,
        "created_at": "2026-08-27T00:00:00+00:00",
        "source_snapshot_sha256": "a" * 64,
        "eligible_years": [
            *range(2012, 2022),
            2024,
            2025,
        ],
        "annual_window": {
            "years": [*range(2012, 2022), 2024, 2025],
            "interval_value": 1,
            "interval_unit": "hours",
        },
        "calibration_lineage": {
            "origin_validation_job_id": "cal_verified",
            "promotion_id": 7,
            "promoted_at": "2026-08-20T00:00:00+00:00",
        },
        "capacity_manifest_source": "annual_result",
    }


def _inspection(source=None):
    public = deepcopy(source or _source())
    public["_dependencies"] = {
        "annual_job": {"id": public["annual_job_id"]},
        "origin_validation_job": {"id": "cal_verified"},
        "promotion_record": {
            "promotion_id": 7,
            "promoted_at": "2026-08-20T00:00:00+00:00",
        },
    }
    return public


def _accepted_asset(value="1200"):
    return {
        "id": "evi_abc",
        "case_id": "case_abc123",
        "candidates": [
            {
                "id": "evc_abc",
                "review_state": "accepted",
                "receipt": {
                    "id": f"evr_{value}",
                    "decision": "accepted",
                    "evidence_class": "project_actual",
                    "field_name": "installed_cost",
                    "value": value,
                    "unit": "USD/kW",
                    "rationale": None,
                },
            }
        ],
    }


class AutonomyReadinessTests(unittest.TestCase):
    NOW = datetime(2026, 8, 29, tzinfo=timezone.utc)

    def _evaluate(self, store, *, sources, bundle, agent_available=True, inspection=None):
        agent = {
            "available": agent_available,
            "enabled": agent_available,
            "credential_configured": agent_available,
            "sdk_available": agent_available,
            "reason_codes": [] if agent_available else ["credential_unavailable"],
            "manual_readiness_available": True,
        }
        with (
            patch.object(readiness, "list_eligible_annual_sources", return_value=sources),
            patch.object(readiness.baselines_module, "_current_calibration_bundle", return_value=bundle),
            patch.object(readiness, "_agent_availability", return_value=agent),
            patch.object(
                readiness,
                "_inspect_annual_source",
                return_value=inspection or _inspection(),
            ),
        ):
            return readiness.evaluate_decision_case_readiness(
                store.case["id"], agent_store=store, now=self.NOW
            )

    def test_missing_prerequisites_return_exact_rules_actions_and_no_execution(self):
        store = _ReadinessStore(_case(status="draft"))
        result = self._evaluate(store, sources=[], bundle=None, agent_available=False)

        self.assertEqual(result["overall_status"], "blocked")
        self.assertFalse(result["ready_to_run"])
        codes = {item["code"] for item in result["blockers"]}
        self.assertTrue(
            {
                "calibration_not_ready",
                "eligible_annual_source_missing",
                "accepted_evidence_missing",
            }.issubset(codes)
        )
        actions = {item["id"]: item for item in result["supported_next_actions"]}
        self.assertEqual(actions["open_calibration"]["deep_link"], "#calibration")
        self.assertEqual(actions["open_annual"]["deep_link"], "#annual")
        allowed_ids = {item["id"] for item in result["allowed_case_actions"]}
        self.assertFalse(
            allowed_ids
            & {"run_scenario", "queue_tea", "confirm_run", "sign_decision", "generate_report"}
        )
        boundary = result["phase_boundary"]
        self.assertTrue(boundary["non_runnable_suggestions_only"])
        self.assertTrue(boundary["decision_brief_available"])
        self.assertEqual(
            recommendation.RECOMMENDATION_CONTRACT_VERSION,
            boundary["recommendation_contract_version"],
        )
        self.assertEqual(
            recommendation.RECOMMENDATION_CONTRACT_DIGEST,
            boundary["recommendation_contract_digest"],
        )

    def test_phase_boundary_reports_the_authority_the_routes_actually_enforce(self):
        """Readiness must not describe a phase the server has moved past.

        The Decision Agent is told readiness is authoritative, so a frozen literal
        here becomes a confident false statement about what an operator may do.
        """

        store = _ReadinessStore(_case(status="draft"))
        for shadow_mode, credentials in ((True, ("ops", "pw")), (False, None), (False, ("ops", "pw"))):
            with self.subTest(shadow_mode=shadow_mode, authenticated=bool(credentials)):
                with (
                    patch.object(config, "DECISION_AGENT_SHADOW_MODE", shadow_mode),
                    patch.object(
                        security, "_dashboard_basic_credentials", return_value=credentials
                    ),
                ):
                    result = self._evaluate(store, sources=[], bundle=None)
                boundary = result["phase_boundary"]
                self.assertEqual(shadow_mode, boundary["shadow_mode"])
                self.assertEqual(
                    "shadow" if shadow_mode else "active",
                    boundary["recommendation_contract_state"],
                )
                self.assertEqual(
                    not shadow_mode, boundary["tea_confirmation_available"]
                )
                self.assertEqual(
                    bool(credentials) and not shadow_mode,
                    boundary["decision_signoff_available"],
                )
                self.assertEqual(
                    bool(credentials), boundary["report_generation_available"]
                )
                self.assertEqual(
                    bool(credentials) and not shadow_mode,
                    boundary["final_report_available"],
                )
                actions = {
                    item["id"]: item for item in result["allowed_case_actions"]
                }
                if shadow_mode and "confirm_scenarios" in actions:
                    self.assertFalse(actions["confirm_scenarios"]["enabled"])
                    self.assertEqual(
                        "Shadow mode blocks execution authority.",
                        actions["confirm_scenarios"]["disabled_reason"],
                    )

    def test_verified_locked_foundation_and_validated_baseline_are_ready_to_run(self):
        source = _source()
        case = _case(
            source_annual_job_id=source["annual_job_id"],
            source_snapshot_sha256=source["source_snapshot_sha256"],
            analysis_basis="solartac_site",
        )
        annual = {"id": source["annual_job_id"], "mode": "annual", "state": "done"}
        store = _ReadinessStore(
            case,
            assets=[_accepted_asset()],
            annual=annual,
            scenarios=[
                {
                    "id": "dsc_baseline",
                    "revision": 1,
                    "kind": "baseline",
                    "status": "validated",
                    "request_sha256": "c" * 64,
                    "comparison_classification": "baseline",
                    "jobs": [],
                }
            ],
        )
        bundle = {
            "baseline": {"id": "cal_verified"},
            "quality": {"review_id": "review_1"},
            "promotion": {"promoted_at": "2026-08-20T00:00:00+00:00"},
            "profile_sha256": "b" * 64,
        }

        result = self._evaluate(
            store,
            sources=[source],
            bundle=bundle,
            inspection=_inspection(source),
        )

        by_id = {item["id"]: item for item in result["checks"]}
        for check_id in (
            "calibration",
            "annual_source",
            "weather_coverage",
            "evidence",
            "job_health",
            "agent",
            "scenarios",
        ):
            self.assertEqual(by_id[check_id]["status"], "passed", check_id)
        self.assertEqual(result["overall_status"], "passed")
        self.assertTrue(result["ready_to_run"])
        self.assertEqual(result["blockers"], [])
        self.assertNotIn("allowed_actions", result["case"])

    def test_weather_policy_is_anchored_to_the_frozen_source_not_the_clock(self):
        """A verified immutable source must not expire because the year changed.

        Judging a frozen Annual source against today's calendar hard-blocked a
        passing case every 1 January, and the only offered action was to rebuild
        an Annual Simulation that had not become invalid.
        """

        source = _source()
        case = _case(
            source_annual_job_id=source["annual_job_id"],
            source_snapshot_sha256=source["source_snapshot_sha256"],
            analysis_basis="solartac_site",
        )
        store = _ReadinessStore(
            case,
            assets=[_accepted_asset()],
            annual={"id": source["annual_job_id"], "mode": "annual", "state": "done"},
        )
        bundle = {
            "baseline": {"id": "cal_verified"},
            "quality": {"review_id": "review_1"},
            "promotion": {"promoted_at": "2026-08-20T00:00:00+00:00"},
            "profile_sha256": "b" * 64,
        }
        for stamp in (
            datetime(2026, 12, 31, 23, tzinfo=timezone.utc),
            datetime(2027, 1, 1, 0, 0, 1, tzinfo=timezone.utc),
            datetime(2031, 6, 1, tzinfo=timezone.utc),
        ):
            with self.subTest(now=stamp.isoformat()):
                with (
                    patch.object(
                        readiness, "list_eligible_annual_sources", return_value=[source]
                    ),
                    patch.object(
                        readiness.baselines_module,
                        "_current_calibration_bundle",
                        return_value=bundle,
                    ),
                    patch.object(
                        readiness,
                        "_inspect_annual_source",
                        return_value=_inspection(source),
                    ),
                ):
                    result = readiness.evaluate_decision_case_readiness(
                        store.case["id"], agent_store=store, now=stamp
                    )
                check = next(
                    item
                    for item in result["checks"]
                    if item["id"] == "weather_coverage"
                )
                self.assertEqual("passed", check["status"])
                self.assertEqual(2026, check["details"]["coverage_anchor_year"])

    def test_elapsed_unconfirmed_baseline_is_not_ready_without_an_expiry_sweep(self):
        source = _source()
        case = _case(
            source_annual_job_id=source["annual_job_id"],
            source_snapshot_sha256=source["source_snapshot_sha256"],
            analysis_basis="solartac_site",
        )
        store = _ReadinessStore(
            case,
            assets=[_accepted_asset()],
            annual={"id": source["annual_job_id"], "mode": "annual", "state": "done"},
            scenarios=[
                {
                    "id": "dsc_expired_baseline",
                    "revision": 1,
                    "kind": "baseline",
                    "status": "validated",
                    "expires_at": "2026-08-28T23:59:59+00:00",
                    "request_sha256": "c" * 64,
                    "comparison_classification": "baseline",
                    "jobs": [],
                }
            ],
        )
        bundle = {
            "baseline": {"id": "cal_verified"},
            "quality": {"review_id": "review_1"},
            "promotion": {"promoted_at": "2026-08-20T00:00:00+00:00"},
            "profile_sha256": "b" * 64,
        }

        result = self._evaluate(
            store,
            sources=[source],
            bundle=bundle,
            inspection=_inspection(source),
        )

        self.assertFalse(result["ready_to_run"])
        self.assertIn(
            "baseline_scenario_missing",
            {item["code"] for item in result["blockers"]},
        )
        scenarios_check = next(
            item for item in result["checks"] if item["id"] == "scenarios"
        )
        self.assertEqual("needs_attention", scenarios_check["status"])

    def test_locked_unverifiable_lineage_never_falls_back_to_current_baseline(self):
        source = _source()
        case = _case(
            source_annual_job_id=source["annual_job_id"],
            source_snapshot_sha256=source["source_snapshot_sha256"],
            analysis_basis="solartac_site",
        )
        store = _ReadinessStore(
            case,
            annual={"id": source["annual_job_id"], "mode": "annual", "state": "done"},
        )
        unrelated_current_bundle = {
            "baseline": {"id": "cal_unrelated_current"},
            "quality": {"review_id": "review_current"},
            "promotion": {"promoted_at": "2026-08-28T00:00:00+00:00"},
            "profile_sha256": "b" * 64,
        }
        invalid_inspection = {
            "eligible": False,
            "annual_job_id": source["annual_job_id"],
            "reason_code": "origin_validation_missing",
            "detail": "The frozen origin Validation job cannot be resolved.",
        }

        result = self._evaluate(
            store,
            sources=[source],
            bundle=unrelated_current_bundle,
            inspection=invalid_inspection,
        )

        calibration = next(item for item in result["checks"] if item["id"] == "calibration")
        self.assertEqual(calibration["status"], "blocked")
        self.assertEqual(
            calibration["blocker"]["code"],
            "locked_calibration_lineage_unverifiable",
        )
        self.assertEqual(
            calibration["details"]["source_verification_reason_code"],
            "origin_validation_missing",
        )
        self.assertFalse(calibration["details"]["current_promoted_baseline_is_substitute"])
        self.assertIn(
            "current promoted baseline is not a substitute",
            calibration["exact_rule"],
        )
        self.assertEqual(result["overall_status"], "blocked")

    def test_conflicting_accepted_evidence_is_blocked_and_preserved_side_by_side(self):
        store = _ReadinessStore(
            _case(),
            assets=[_accepted_asset("1200"), _accepted_asset("1600")],
        )
        result = self._evaluate(store, sources=[], bundle=None)
        evidence_check = next(item for item in result["checks"] if item["id"] == "evidence")

        self.assertEqual(evidence_check["status"], "blocked")
        self.assertEqual(
            evidence_check["details"]["conflicts"][0]["values"],
            ["1200", "1600"],
        )
        self.assertIn(
            "accepted_evidence_conflicts",
            {item["code"] for item in result["blockers"]},
        )

    def test_newer_source_and_stale_job_are_reported_without_mutating_case(self):
        selected = _source(completed_at="2026-08-20T00:00:00+00:00")
        latest = _source("annual_newer", "2026-08-28T00:00:00+00:00")
        case = _case(
            source_annual_job_id=selected["annual_job_id"],
            source_snapshot_sha256=selected["source_snapshot_sha256"],
            analysis_basis="solartac_site",
        )
        store = _ReadinessStore(
            case,
            assets=[_accepted_asset()],
            annual={"id": selected["annual_job_id"], "mode": "annual", "state": "done"},
            jobs=[
                {
                    "id": "annual_running",
                    "mode": "annual",
                    "state": "running",
                    "heartbeat_at": "2026-08-28T00:00:00+00:00",
                    "updated_at": "2026-08-28T00:00:00+00:00",
                }
            ],
        )
        bundle = {
            "baseline": {"id": "cal_verified"},
            "quality": {"review_id": "review_1"},
            "promotion": {"promoted_at": "2026-08-20T00:00:00+00:00"},
            "profile_sha256": "b" * 64,
        }

        result = self._evaluate(
            store,
            sources=[latest, selected],
            bundle=bundle,
            inspection=_inspection(selected),
        )
        by_id = {item["id"]: item for item in result["checks"]}
        self.assertEqual(by_id["annual_source"]["status"], "stale")
        self.assertEqual(by_id["job_health"]["status"], "stale")
        self.assertEqual(by_id["job_health"]["details"]["stale_count"], 1)
        self.assertEqual(store.case["revision"], 3)


if __name__ == "__main__":
    unittest.main()
