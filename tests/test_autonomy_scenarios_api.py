from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
import shutil
import sqlite3
import threading
import unittest
import uuid
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from sbepv.api import autonomy as autonomy_api
from sbepv.api import config, state
from sbepv.api import main as app
from sbepv.api import technoeconomic as technoeconomic_api
from sbepv.autonomy import comparison as comparison_service
from sbepv.store import AgentStore
from tests.test_autonomy_comparison import _verified_outcome
from tests.test_autonomy_scenarios import _request


class AutonomyScenarioExecutionApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = (
            Path(__file__).resolve().parent
            / f"autonomy-scenarios-api-{uuid.uuid4().hex}"
        )
        self.root.mkdir(parents=False, exist_ok=False)
        self.addCleanup(self._cleanup)

        self.original_store = state.AGENT_STORE
        self.original_wake = state._WORKER_WAKE
        state.AGENT_STORE = AgentStore(self.root / "agent.sqlite3")
        state._WORKER_WAKE = Mock()

        self.source = self._completed_annual_source("annual-scenario-api")
        self.source_snapshot = {
            "schema_version": 1,
            "source_annual_job_id": self.source["id"],
            "midc_source_artifact": {
                "owner_annual_job_id": self.source["id"],
                "storage_key": f"sha256/11/{'1' * 64}.csv",
                "sha256": "1" * 64,
                "byte_count": 12_345,
            },
            "energy_rows": [
                {
                    "weather_year": 2024,
                    "solectria_kwh": 1_000.0,
                    "solaredge_kwh": 1_050.0,
                }
            ],
            "capacity_manifest": {
                "solectria_wdc": 139_180.8,
                "solaredge_wdc": 139_180.8,
            },
        }
        self.source_snapshot_sha256 = technoeconomic_api.canonical_json_sha256(
            self.source_snapshot
        )
        self.case = self._locked_case(
            "Scenario API decision",
            analysis_basis="solartac_site",
        )

        self.readiness_patch = patch.object(
            autonomy_api.readiness,
            "evaluate_decision_case_readiness",
            side_effect=self._fake_readiness,
        )
        self.readiness_patch.start()
        self.client = TestClient(app.app)

    def _cleanup(self) -> None:
        self.client.close()
        self.readiness_patch.stop()
        state.AGENT_STORE = self.original_store
        state._WORKER_WAKE = self.original_wake
        shutil.rmtree(self.root, ignore_errors=True)

    def _completed_annual_source(self, job_id: str) -> dict:
        created = state.AGENT_STORE.create_job(
            job_id=job_id,
            kind="manual",
            mode="annual",
            request={"mode": "annual", "years": [2024]},
            source_path=f"artifacts/{job_id}/midc.csv",
            source_hash="1" * 64,
        )
        claimed = state.AGENT_STORE.claim_next_queued_job()
        self.assertIsNotNone(claimed)
        self.assertEqual(created["id"], claimed["id"])
        return state.AGENT_STORE.update_job(
            created["id"],
            state="done",
            stage="Done",
            result={"mode": "annual", "stats": {}},
            provenance={"source": "scenario-api-test"},
        )

    def _locked_case(self, title: str, *, analysis_basis: str) -> dict:
        case_record = state.AGENT_STORE.create_decision_case(
            title=title,
            question="Which exact TEA assumptions should be compared?",
            operator_name="Alex Operator",
        )
        return state.AGENT_STORE.lock_decision_case(
            case_record["id"],
            expected_revision=case_record["revision"],
            source_annual_job_id=self.source["id"],
            source_snapshot_sha256=self.source_snapshot_sha256,
            analysis_basis=analysis_basis,
            operator_name="Alex Operator",
        )

    @staticmethod
    def _fake_readiness(case_id: str, **_kwargs) -> dict:
        case_record = state.AGENT_STORE.get_decision_case(case_id)
        if case_record is None:
            raise KeyError(case_id)
        current = state.AGENT_STORE.list_decision_scenarios(
            case_id,
            include_history=False,
            include_expired=False,
            limit=10,
        )
        has_validated_baseline = any(
            item.get("kind") == "baseline"
            and item.get("status") in {"validated", "confirmed"}
            for item in current
        )
        current_status = str(case_record["status"])
        suggested = (
            current_status
            if current_status in {"running", "results_ready", "signed", "archived"}
            else "ready_to_run" if has_validated_baseline else "evidence_needed"
        )
        blocker = {
            "code": "validated_baseline_required",
            "message": "Validate one baseline before confirming a scenario batch.",
            "blocking": True,
        }
        return {
            "schema_version": "decision-readiness-v1",
            "case_id": case_id,
            "case_revision": int(case_record["revision"]),
            "evaluated_at": "2026-08-29T12:00:00+00:00",
            "overall_status": "ready" if has_validated_baseline else "needs_attention",
            "ready_to_run": has_validated_baseline
            and current_status in {"draft", "evidence_needed", "blocked", "ready_to_run"},
            "suggested_case_status": suggested,
            "checks": [],
            "blockers": [] if has_validated_baseline else [blocker],
            "supported_next_actions": [],
            "allowed_case_actions": [
                {"id": "create_scenario", "enabled": current_status != "running"},
                {"id": "compare_scenarios", "enabled": has_validated_baseline},
                {
                    "id": "confirm_scenarios",
                    "enabled": has_validated_baseline
                    and current_status == "ready_to_run",
                },
            ],
            "eligible_annual_sources": [],
            "supported_analysis_bases": [],
            "phase_boundary": {
                "current_phase": "scenarios_and_execution",
                "scenarios_and_execution_available": True,
                "decision_brief_available": False,
            },
        }

    def _current_case(self, case_id: str | None = None) -> dict:
        current = state.AGENT_STORE.get_decision_case(case_id or self.case["id"])
        self.assertIsNotNone(current)
        return current

    def _create_scenario(
        self,
        *,
        case_id: str | None = None,
        kind: str,
        label: str,
        request: dict,
        changed_fields: list[str] | None = None,
    ) -> dict:
        resolved_case_id = case_id or self.case["id"]
        response = self.client.post(
            f"/api/autonomy/cases/{resolved_case_id}/scenarios",
            json={
                "expected_case_revision": self._current_case(resolved_case_id)[
                    "revision"
                ],
                "operator_name": "Alex Operator",
                "label": label,
                "kind": kind,
                "request": request,
                "changed_fields": changed_fields or [],
                "evidence_references": [],
            },
        )
        self.assertEqual(201, response.status_code, response.text)
        return response.json()["scenario"]

    def _validate_scenario(self, scenario: dict) -> dict:
        response = self.client.post(
            (
                f"/api/autonomy/cases/{scenario['case_id']}/scenarios/"
                f"{scenario['scenario_id']}/validate"
            ),
            json={
                "expected_case_revision": self._current_case(scenario["case_id"])[
                    "revision"
                ],
                "expected_scenario_revision": scenario["revision"],
                "expected_request_sha256": scenario["request_sha256"],
                "operator_name": "Scenario Validator",
            },
        )
        self.assertEqual(200, response.status_code, response.text)
        self.assertTrue(response.json()["validation"]["valid"], response.text)
        return response.json()["scenario"]

    def _validated_baseline(self, *, case_id: str | None = None) -> dict:
        resolved_case_id = case_id or self.case["id"]
        baseline = self._create_scenario(
            case_id=resolved_case_id,
            kind="baseline",
            label="Current baseline",
            request=_request(source_id=self.source["id"], value=10.0),
        )
        return self._validate_scenario(baseline)

    def _validated_pair(self) -> tuple[dict, dict]:
        baseline = self._validated_baseline()
        alternative_request = _request(source_id=self.source["id"], value=12.0)
        alternative_request.pop("n")
        alternative_request.pop("seed")
        alternative = self._create_scenario(
            kind="alternative",
            label="Lower-risk alternative",
            request=alternative_request,
            changed_fields=["/cost_lines/0/distribution/value"],
        )
        return baseline, self._validate_scenario(alternative)

    def _confirmation_payload(
        self,
        scenarios: list[dict],
        *,
        idempotency_key: str,
        expected_case_revision: int | None = None,
        rationale: str = "Run this exact validated comparison set.",
    ) -> dict:
        return {
            "expected_case_revision": (
                self._current_case()["revision"]
                if expected_case_revision is None
                else expected_case_revision
            ),
            "selections": [
                {
                    "scenario_id": item["scenario_id"],
                    "revision": item["revision"],
                    "request_sha256": item["request_sha256"],
                }
                for item in scenarios
            ],
            "operator_name": "Alex Operator",
            "rationale": rationale,
            "acknowledgement_accepted": True,
            "idempotency_key": idempotency_key,
        }

    def _fake_prepare_bundle(self, *, agent_store, case_record, request_payload):
        del agent_store
        request_hash = technoeconomic_api.canonical_json_sha256(request_payload)
        return {
            "request": deepcopy(request_payload),
            "request_sha256": request_hash,
            "source_snapshot_envelope": {
                "source_snapshot": deepcopy(self.source_snapshot),
                "source_snapshot_sha256": self.source_snapshot_sha256,
            },
            "validated_kernel_request": {"test_only": True},
            "submission_provenance": {
                "schema_version": 1,
                "request_sha256": request_hash,
                "analysis_basis": case_record["analysis_basis"],
            },
            "source_store_fields": {
                "source_annual_job_id": self.source["id"],
                "source_artifact_storage_key": f"sha256/11/{'1' * 64}.csv",
                "source_artifact_sha256": "1" * 64,
                "source_artifact_bytes": 12_345,
                "source_snapshot": deepcopy(self.source_snapshot),
                "atomic_source_check": (
                    lambda _connection: self.source_snapshot_sha256
                ),
            },
        }

    def test_new_scenario_routes_are_basic_auth_protected(self) -> None:
        path = f"/api/autonomy/cases/{self.case['id']}/scenarios"
        credentials = {
            "DASHBOARD_BASIC_USER": "dashboard-user",
            "DASHBOARD_BASIC_PASSWORD": "secret",
        }
        with patch.dict("os.environ", credentials):
            unauthorized = self.client.get(path)
            token = base64.b64encode(b"dashboard-user:secret").decode("ascii")
            authorized = self.client.get(
                path,
                headers={"Authorization": f"Basic {token}"},
            )

        self.assertEqual(401, unauthorized.status_code)
        self.assertEqual(200, authorized.status_code, authorized.text)

    def test_create_revise_validate_list_and_compare_are_live_and_exact(self) -> None:
        baseline, alternative = self._validated_pair()
        revised_request = _request(source_id=self.source["id"], value=13.0)
        revised = self.client.post(
            (
                f"/api/autonomy/cases/{self.case['id']}/scenarios/"
                f"{alternative['scenario_id']}/revisions"
            ),
            json={
                "expected_case_revision": self._current_case()["revision"],
                "expected_scenario_revision": alternative["revision"],
                "operator_name": "Alex Operator",
                "label": "Lower-risk alternative v2",
                "kind": "alternative",
                "request": revised_request,
                "changed_fields": ["/cost_lines/0/distribution/value"],
                "evidence_references": [],
            },
        )
        self.assertEqual(201, revised.status_code, revised.text)
        revision = revised.json()["scenario"]
        self.assertEqual(2, revision["revision"])
        self.assertEqual(
            alternative["scenario_revision_id"], revision["parent_revision_id"]
        )
        revision = self._validate_scenario(revision)

        listed = self.client.get(
            f"/api/autonomy/cases/{self.case['id']}/scenarios"
        )
        self.assertEqual(200, listed.status_code, listed.text)
        payload = listed.json()
        self.assertEqual(3, len(payload["scenarios"]))
        self.assertEqual(2, len(payload["current_scenarios"]))
        self.assertIn("allowed_actions", payload)
        self.assertIn("blockers", payload)
        public_ids = {
            item["scenario_revision_id"] for item in payload["scenarios"]
        }
        self.assertEqual(
            {
                baseline["scenario_revision_id"],
                alternative["scenario_revision_id"],
                revision["scenario_revision_id"],
            },
            public_ids,
        )

        compared = self.client.get(
            f"/api/autonomy/cases/{self.case['id']}/scenarios/compare"
        )
        self.assertEqual(200, compared.status_code, compared.text)
        comparison = compared.json()["comparison"]
        self.assertTrue(comparison["available"])
        self.assertFalse(comparison["outcomes_available"])
        self.assertEqual(
            "inputs_or_hypotheses_not_outcomes",
            comparison["pre_run_value_semantics"],
        )
        self.assertEqual(32, comparison["realization_count"])
        self.assertEqual(42, comparison["seed"])
        self.assertEqual(
            ["/cost_lines/0/distribution/value"],
            [item["path"] for item in comparison["difference_matrix"]],
        )
        matrix_row = comparison["difference_matrix"][0]
        self.assertEqual(10.0, matrix_row["baseline"]["value"])
        self.assertEqual(13.0, matrix_row["alternatives"][0]["value"])
        self.assertEqual("input", matrix_row["baseline"]["value_kind"])
        self.assertEqual("hypothesis", matrix_row["alternatives"][0]["value_kind"])

        expired = self.client.post(
            (
                f"/api/autonomy/cases/{self.case['id']}/scenarios/"
                f"{revision['scenario_id']}/expire"
            ),
            json={
                "expected_case_revision": self._current_case()["revision"],
                "expected_scenario_revision": revision["revision"],
                "operator_name": "Alex Operator",
                "reason": "This alternative is no longer part of the live comparison.",
            },
        )
        self.assertEqual(200, expired.status_code, expired.text)
        self.assertEqual("expired", expired.json()["scenario"]["draft_status"])
        after_expiry = self.client.get(
            f"/api/autonomy/cases/{self.case['id']}/scenarios"
        )
        self.assertEqual(200, after_expiry.status_code, after_expiry.text)
        self.assertEqual(3, len(after_expiry.json()["scenarios"]))
        self.assertEqual(
            [baseline["scenario_id"]],
            [item["scenario_id"] for item in after_expiry.json()["current_scenarios"]],
        )

    def test_structured_schema_source_and_basis_errors_include_supported_action(self) -> None:
        unsupported = _request(source_id=self.source["id"])
        unsupported["agent_guess"] = "must never be inferred"
        schema_error = self.client.post(
            f"/api/autonomy/cases/{self.case['id']}/scenarios",
            json={
                "expected_case_revision": self._current_case()["revision"],
                "operator_name": "Alex Operator",
                "label": "Unsupported baseline",
                "kind": "baseline",
                "request": unsupported,
                "changed_fields": [],
                "evidence_references": [],
            },
        )
        self.assertEqual(422, schema_error.status_code, schema_error.text)
        schema_detail = schema_error.json()["detail"]
        self.assertEqual("scenario_draft_invalid", schema_detail["code"])
        self.assertIn(
            "unsupported_field",
            {item["code"] for item in schema_detail["field_errors"]},
        )
        self.assertIn(
            "open_expert_tea_form",
            {
                item["action"]
                for item in schema_detail["closest_supported_alternatives"]
            },
        )

        cross_source = self.client.post(
            f"/api/autonomy/cases/{self.case['id']}/scenarios",
            json={
                "expected_case_revision": self._current_case()["revision"],
                "operator_name": "Alex Operator",
                "label": "Cross-source draft",
                "kind": "baseline",
                "request": _request(source_id="annual-other-source"),
                "changed_fields": [],
                "evidence_references": [],
            },
        )
        self.assertEqual(422, cross_source.status_code, cross_source.text)
        source_detail = cross_source.json()["detail"]
        self.assertEqual("scenario_draft_invalid", source_detail["code"])
        self.assertIn(
            "cross_source_comparison",
            {item["code"] for item in source_detail["field_errors"]},
        )
        self.assertIn(
            "create_new_case",
            {
                item["action"]
                for item in source_detail["closest_supported_alternatives"]
            },
        )

        commercial_case = self._locked_case(
            "Commercial-basis mismatch",
            analysis_basis="commercial_representative",
        )
        cross_basis = self.client.post(
            f"/api/autonomy/cases/{commercial_case['id']}/scenarios",
            json={
                "expected_case_revision": self._current_case(commercial_case["id"])[
                    "revision"
                ],
                "operator_name": "Alex Operator",
                "label": "Cross-basis draft",
                "kind": "baseline",
                "request": _request(source_id=self.source["id"]),
                "changed_fields": [],
                "evidence_references": [],
            },
        )
        self.assertEqual(422, cross_basis.status_code, cross_basis.text)
        basis_detail = cross_basis.json()["detail"]
        self.assertEqual("scenario_draft_invalid", basis_detail["code"])
        self.assertIn(
            "cross_basis_comparison",
            {
                item["code"]
                for item in basis_detail["field_errors"]
            },
        )
        self.assertIn(
            "create_new_case",
            {
                item["action"]
                for item in basis_detail["closest_supported_alternatives"]
            },
        )

    def test_confirmation_is_atomic_revision_fenced_and_idempotent(self) -> None:
        baseline = self._validated_baseline()
        stale_revision = self._current_case()["revision"] - 1
        stale_payload = self._confirmation_payload(
            [baseline],
            idempotency_key="scenario-confirm-stale",
            expected_case_revision=stale_revision,
        )
        with patch.object(
            autonomy_api.scenarios,
            "prepare_technoeconomic_bundle",
            side_effect=self._fake_prepare_bundle,
        ):
            stale = self.client.post(
                f"/api/autonomy/cases/{self.case['id']}/scenarios/confirm",
                json=stale_payload,
            )
        self.assertEqual(409, stale.status_code, stale.text)
        self.assertEqual([], state.AGENT_STORE.list_technoeconomic_jobs())

        request_payload = self._confirmation_payload(
            [baseline], idempotency_key="scenario-confirm-once"
        )
        with patch.object(
            autonomy_api.scenarios,
            "prepare_technoeconomic_bundle",
            side_effect=self._fake_prepare_bundle,
        ):
            confirmed = self.client.post(
                f"/api/autonomy/cases/{self.case['id']}/scenarios/confirm",
                json=request_payload,
            )
        self.assertEqual(202, confirmed.status_code, confirmed.text)
        confirmation = confirmed.json()["confirmation"]
        self.assertEqual("Alex Operator", confirmation["operator_name"])
        self.assertEqual(1, len(confirmation["items"]))
        self.assertEqual(1, len(confirmed.json()["jobs"]))
        self.assertFalse(confirmed.json()["idempotent_replay"])

        replay = self.client.post(
            f"/api/autonomy/cases/{self.case['id']}/scenarios/confirm",
            json=request_payload,
        )
        self.assertEqual(202, replay.status_code, replay.text)
        self.assertTrue(replay.json()["idempotent_replay"])
        self.assertEqual(
            confirmation["confirmation_id"],
            replay.json()["confirmation"]["confirmation_id"],
        )
        self.assertEqual(
            [item["job_id"] for item in confirmed.json()["jobs"]],
            [item["job_id"] for item in replay.json()["jobs"]],
        )
        self.assertEqual(
            [item["request"] for item in confirmed.json()["jobs"]],
            [item["request"] for item in replay.json()["jobs"]],
        )
        self.assertEqual(1, len(state.AGENT_STORE.list_technoeconomic_jobs()))

        mismatched = deepcopy(request_payload)
        mismatched["rationale"] = "Reuse the key for a different request."
        conflict = self.client.post(
            f"/api/autonomy/cases/{self.case['id']}/scenarios/confirm",
            json=mismatched,
        )
        self.assertEqual(409, conflict.status_code, conflict.text)
        self.assertEqual("idempotency_key_reused", conflict.json()["detail"]["code"])

    def test_concurrent_duplicate_confirmation_replays_after_lock(self) -> None:
        baseline = self._validated_baseline()
        request_payload = self._confirmation_payload(
            [baseline], idempotency_key="scenario-confirm-concurrent"
        )
        original_lookup = (
            state.AGENT_STORE.get_decision_scenario_confirmation_by_idempotency
        )
        barrier = threading.Barrier(2)
        counter_lock = threading.Lock()
        lookup_count = 0

        def synchronized_lookup(case_id: str, key: str):
            nonlocal lookup_count
            result = original_lookup(case_id, key)
            with counter_lock:
                lookup_count += 1
                wait_for_peer = lookup_count <= 2
            if wait_for_peer:
                barrier.wait(timeout=5)
            return result

        def submit(_index: int):
            return self.client.post(
                f"/api/autonomy/cases/{self.case['id']}/scenarios/confirm",
                json=request_payload,
            )

        with (
            patch.object(
                state.AGENT_STORE,
                "get_decision_scenario_confirmation_by_idempotency",
                side_effect=synchronized_lookup,
            ),
            patch.object(
                autonomy_api.scenarios,
                "prepare_technoeconomic_bundle",
                side_effect=self._fake_prepare_bundle,
            ),
            ThreadPoolExecutor(max_workers=2) as executor,
        ):
            responses = list(executor.map(submit, range(2)))

        self.assertEqual([202, 202], sorted(item.status_code for item in responses))
        payloads = [item.json() for item in responses]
        self.assertEqual(
            [False, True],
            sorted(item["idempotent_replay"] for item in payloads),
        )
        self.assertEqual(
            1,
            len(
                {
                    item["confirmation"]["confirmation_id"]
                    for item in payloads
                }
            ),
        )
        self.assertEqual(1, len(state.AGENT_STORE.list_technoeconomic_jobs()))

    def test_mixed_case_confirmation_is_rejected_before_any_job_is_created(self) -> None:
        baseline = self._validated_baseline()
        other_case = self._locked_case(
            "Other decision case",
            analysis_basis="solartac_site",
        )
        other_baseline = self._validated_baseline(case_id=other_case["id"])
        payload = self._confirmation_payload(
            [baseline, other_baseline],
            idempotency_key="mixed-case-selection",
        )
        with patch.object(
            autonomy_api.scenarios,
            "prepare_technoeconomic_bundle",
            side_effect=self._fake_prepare_bundle,
        ):
            response = self.client.post(
                f"/api/autonomy/cases/{self.case['id']}/scenarios/confirm",
                json=payload,
            )
        self.assertEqual(404, response.status_code, response.text)
        self.assertEqual([], state.AGENT_STORE.list_technoeconomic_jobs())

    def test_partial_batch_insert_failure_rolls_back_confirmation_and_every_job(self) -> None:
        baseline, alternative = self._validated_pair()
        payload = self._confirmation_payload(
            [baseline, alternative],
            idempotency_key="atomic-batch-rollback",
        )
        original_insert = state.AGENT_STORE._insert_technoeconomic_job
        insertion_count = 0

        def fail_after_second_insert(*args, **kwargs):
            nonlocal insertion_count
            insertion_count += 1
            result = original_insert(*args, **kwargs)
            if insertion_count == 2:
                raise sqlite3.IntegrityError("synthetic second insert failure")
            return result

        with (
            patch.object(
                autonomy_api.scenarios,
                "prepare_technoeconomic_bundle",
                side_effect=self._fake_prepare_bundle,
            ),
            patch.object(
                state.AGENT_STORE,
                "_insert_technoeconomic_job",
                side_effect=fail_after_second_insert,
            ),
        ):
            response = self.client.post(
                f"/api/autonomy/cases/{self.case['id']}/scenarios/confirm",
                json=payload,
            )
        self.assertEqual(409, response.status_code, response.text)
        self.assertEqual(2, insertion_count)
        self.assertEqual([], state.AGENT_STORE.list_technoeconomic_jobs())
        self.assertIsNone(
            state.AGENT_STORE.get_decision_scenario_confirmation_by_idempotency(
                self.case["id"], "atomic-batch-rollback"
            )
        )
        current = state.AGENT_STORE.list_decision_scenarios(
            self.case["id"], include_history=False, include_expired=False
        )
        self.assertEqual({"validated"}, {item["status"] for item in current})

    def test_execution_reconnect_cancel_retry_and_public_projection(self) -> None:
        baseline = self._validated_baseline()
        payload = self._confirmation_payload(
            [baseline], idempotency_key="execution-actions"
        )
        with patch.object(
            autonomy_api.scenarios,
            "prepare_technoeconomic_bundle",
            side_effect=self._fake_prepare_bundle,
        ):
            confirmed = self.client.post(
                f"/api/autonomy/cases/{self.case['id']}/scenarios/confirm",
                json=payload,
            )
        self.assertEqual(202, confirmed.status_code, confirmed.text)
        public_job = confirmed.json()["jobs"][0]
        job_id = public_job["job_id"]
        self.assertEqual("queued", public_job["state"])
        self.assertNotIn("source_snapshot", public_job)
        self.assertNotIn("source_artifact_storage_key", public_job)
        self.assertNotIn("submission_provenance", public_job)
        self.assertNotIn("lease_token", public_job)

        reconnect = self.client.get(
            f"/api/autonomy/cases/{self.case['id']}/execution"
        )
        self.assertEqual(200, reconnect.status_code, reconnect.text)
        execution = reconnect.json()["execution"]
        self.assertEqual("queued", execution["state"])
        self.assertEqual([job_id], execution["cancellable_job_ids"])
        self.assertTrue(execution["decision_brief_available"])
        self.assertEqual(
            "classification_pending_contract",
            execution["recommendation_contract_state"],
        )
        self.assertFalse(execution["recommendation_available"])
        self.assertFalse(execution["signoff_available"])
        self.assertFalse(execution["report_generation_available"])

        generic_cancel = self.client.post(
            f"/api/technoeconomic/jobs/{job_id}/cancel"
        )
        self.assertEqual(409, generic_cancel.status_code, generic_cancel.text)
        generic_retry = self.client.post(
            f"/api/technoeconomic/jobs/{job_id}/retry"
        )
        self.assertEqual(409, generic_retry.status_code, generic_retry.text)
        self.assertEqual(
            "queued",
            state.AGENT_STORE.get_technoeconomic_job(job_id)["state"],
        )

        cancelled = self.client.post(
            f"/api/autonomy/cases/{self.case['id']}/execution/{job_id}/cancel",
            json={
                "expected_case_revision": self._current_case()["revision"],
                "operator_name": "Alex Operator",
                "rationale": "Cancel this queued attempt safely.",
            },
        )
        self.assertEqual(200, cancelled.status_code, cancelled.text)
        self.assertTrue(cancelled.json()["cancelled"])
        self.assertEqual("cancelled", cancelled.json()["job"]["job"]["state"])

        retry = self.client.post(
            f"/api/autonomy/cases/{self.case['id']}/execution/{job_id}/retry",
            json={
                "expected_case_revision": self._current_case()["revision"],
                "operator_name": "Alex Operator",
                "rationale": "Retry the same frozen request and source snapshot.",
            },
        )
        self.assertEqual(202, retry.status_code, retry.text)
        retry_link = retry.json()["job"]
        self.assertNotEqual(job_id, retry_link["job"]["job_id"])
        self.assertEqual(job_id, retry_link["job"]["retry_of_job_id"])
        self.assertEqual("queued", retry_link["job"]["state"])
        self.assertNotIn("source_snapshot", retry_link["job"])
        self.assertEqual(
            baseline["request_sha256"],
            technoeconomic_api.canonical_json_sha256(retry_link["job"]["request"]),
        )
        self.assertTrue(state._WORKER_WAKE.set.called)

    def test_partial_decision_comparison_is_live_but_cannot_create_brief(self) -> None:
        baseline = self._validated_baseline()
        confirmation_payload = self._confirmation_payload(
            [baseline],
            idempotency_key="decision-brief-partial-confirmation",
        )
        with patch.object(
            autonomy_api.scenarios,
            "prepare_technoeconomic_bundle",
            side_effect=self._fake_prepare_bundle,
        ):
            confirmed = self.client.post(
                f"/api/autonomy/cases/{self.case['id']}/scenarios/confirm",
                json=confirmation_payload,
            )
        self.assertEqual(202, confirmed.status_code, confirmed.text)
        confirmation_id = confirmed.json()["confirmation"]["confirmation_id"]
        case_revision = self._current_case()["revision"]

        stale = self.client.post(
            f"/api/autonomy/cases/{self.case['id']}/comparison-bundles",
            json={
                "expected_case_revision": case_revision - 1,
                "confirmation_id": confirmation_id,
                "operator_name": "Alex Operator",
            },
        )
        self.assertEqual(409, stale.status_code, stale.text)
        self.assertEqual("stale_case_revision", stale.json()["detail"]["code"])

        injected_result = self.client.post(
            f"/api/autonomy/cases/{self.case['id']}/comparison-bundles",
            json={
                "expected_case_revision": case_revision,
                "confirmation_id": confirmation_id,
                "operator_name": "Alex Operator",
                "result": {"winner": "client-controlled"},
            },
        )
        self.assertEqual(422, injected_result.status_code, injected_result.text)

        created = self.client.post(
            f"/api/autonomy/cases/{self.case['id']}/comparison-bundles",
            json={
                "expected_case_revision": case_revision,
                "confirmation_id": confirmation_id,
                "operator_name": "Alex Operator",
            },
        )
        self.assertEqual(201, created.status_code, created.text)
        comparison_record = created.json()["comparison_bundle"]
        self.assertFalse(comparison_record["is_complete"])
        self.assertFalse(comparison_record["recommendation_eligible"])
        self.assertEqual(
            "classification_pending_contract",
            comparison_record["bundle"]["recommendation"]["state"],
        )
        self.assertEqual(
            "queued",
            comparison_record["bundle"]["scenarios"][0]["attempt"][
                "display_status"
            ],
        )
        self.assertNotIn("source_artifact_storage_key", created.text)
        actions = {
            item["id"]: item for item in created.json()["decision_allowed_actions"]
        }
        self.assertTrue(actions["open_decision_brief"]["enabled"])
        self.assertFalse(actions["create_decision_brief"]["enabled"])

        listed = self.client.get(
            f"/api/autonomy/cases/{self.case['id']}/comparison-bundles"
        )
        self.assertEqual(200, listed.status_code, listed.text)
        listed_payload = listed.json()
        self.assertEqual(self.case["id"], listed_payload["case"]["case_id"])
        self.assertEqual(
            self._current_case()["revision"],
            listed_payload["case_revision"],
        )
        self.assertEqual(
            listed_payload["case"]["revision"],
            listed_payload["case_revision"],
        )
        self.assertEqual(
            [comparison_record["comparison_bundle_id"]],
            [
                item["comparison_bundle_id"]
                for item in listed_payload["comparison_bundles"]
            ],
        )
        listed_briefs = self.client.get(
            f"/api/autonomy/cases/{self.case['id']}/decision-briefs"
        )
        self.assertEqual(200, listed_briefs.status_code, listed_briefs.text)
        self.assertEqual([], listed_briefs.json()["decision_briefs"])
        self.assertEqual(
            listed_briefs.json()["case"]["revision"],
            listed_briefs.json()["case_revision"],
        )
        fetched = self.client.get(
            f"/api/autonomy/cases/{self.case['id']}/comparison-bundles/"
            f"{comparison_record['comparison_bundle_id']}"
        )
        self.assertEqual(200, fetched.status_code, fetched.text)
        self.assertEqual(
            comparison_record["bundle_sha256"],
            fetched.json()["comparison_bundle"]["bundle_sha256"],
        )

        brief = self.client.post(
            f"/api/autonomy/cases/{self.case['id']}/decision-briefs",
            json={
                "expected_case_revision": case_revision,
                "comparison_bundle_id": comparison_record[
                    "comparison_bundle_id"
                ],
                "bundle_sha256": comparison_record["bundle_sha256"],
                "operator_name": "Alex Operator",
                "idempotency_key": "partial-brief-must-not-finalize",
            },
        )
        self.assertEqual(409, brief.status_code, brief.text)
        self.assertEqual("comparison_incomplete", brief.json()["detail"]["code"])

        state.AGENT_STORE.mark_decision_comparison_bundle_stale(
            comparison_record["comparison_bundle_id"],
            reason={"code": "focused_api_stale_history"},
        )
        stale_history = self.client.get(
            f"/api/autonomy/cases/{self.case['id']}/comparison-bundles"
        )
        self.assertEqual(200, stale_history.status_code, stale_history.text)
        stale_actions = {
            item["id"]: item
            for item in stale_history.json()["decision_allowed_actions"]
        }
        self.assertTrue(stale_actions["build_comparison_bundle"]["enabled"])
        self.assertIn(
            "comparison_stale",
            {
                item["code"]
                for item in stale_history.json()["decision_blockers"]
            },
        )

    def test_missing_confirmed_scenario_fails_closed_without_persistence(self) -> None:
        baseline = self._validated_baseline()
        with patch.object(
            autonomy_api.scenarios,
            "prepare_technoeconomic_bundle",
            side_effect=self._fake_prepare_bundle,
        ):
            confirmed = self.client.post(
                f"/api/autonomy/cases/{self.case['id']}/scenarios/confirm",
                json=self._confirmation_payload(
                    [baseline],
                    idempotency_key="missing-confirmed-scenario-corruption",
                ),
            )
        self.assertEqual(202, confirmed.status_code, confirmed.text)
        confirmation_id = confirmed.json()["confirmation"]["confirmation_id"]

        with (
            patch.object(
                state.AGENT_STORE,
                "get_decision_scenario",
                return_value=None,
            ),
            patch.object(
                state.AGENT_STORE,
                "create_decision_comparison_bundle",
            ) as create_bundle,
        ):
            response = self.client.post(
                f"/api/autonomy/cases/{self.case['id']}/comparison-bundles",
                json={
                    "expected_case_revision": self._current_case()["revision"],
                    "confirmation_id": confirmation_id,
                    "operator_name": "Alex Operator",
                },
            )

        self.assertEqual(409, response.status_code, response.text)
        self.assertEqual(
            "confirmed_scenario_missing",
            response.json()["detail"]["code"],
        )
        create_bundle.assert_not_called()
        self.assertEqual(
            [],
            state.AGENT_STORE.list_decision_comparison_bundles(self.case["id"]),
        )

    def test_decision_brief_routes_are_authenticated_and_cross_case_safe(self) -> None:
        path = f"/api/autonomy/cases/{self.case['id']}/comparison-bundles"
        credentials = {
            "DASHBOARD_BASIC_USER": "dashboard-user",
            "DASHBOARD_BASIC_PASSWORD": "secret",
        }
        with patch.dict("os.environ", credentials):
            unauthorized = self.client.get(path)
            token = base64.b64encode(b"dashboard-user:secret").decode("ascii")
            authorized = self.client.get(
                path,
                headers={"Authorization": f"Basic {token}"},
            )
        self.assertEqual(401, unauthorized.status_code)
        self.assertEqual(200, authorized.status_code, authorized.text)

        baseline = self._validated_baseline()
        with patch.object(
            autonomy_api.scenarios,
            "prepare_technoeconomic_bundle",
            side_effect=self._fake_prepare_bundle,
        ):
            confirmed = self.client.post(
                f"/api/autonomy/cases/{self.case['id']}/scenarios/confirm",
                json=self._confirmation_payload(
                    [baseline],
                    idempotency_key="cross-case-comparison-confirmation",
                ),
            )
        self.assertEqual(202, confirmed.status_code, confirmed.text)
        other_case = self._locked_case(
            "Another exact decision case",
            analysis_basis="solartac_site",
        )
        cross_case = self.client.post(
            f"/api/autonomy/cases/{other_case['id']}/comparison-bundles",
            json={
                "expected_case_revision": other_case["revision"],
                "confirmation_id": confirmed.json()["confirmation"][
                    "confirmation_id"
                ],
                "operator_name": "Alex Operator",
            },
        )
        self.assertEqual(404, cross_case.status_code, cross_case.text)
        self.assertEqual("Not found.", cross_case.json()["detail"])

    def test_complete_bundle_creates_only_unsigned_pending_idempotent_brief(self) -> None:
        baseline = self._validated_baseline()
        with patch.object(
            autonomy_api.scenarios,
            "prepare_technoeconomic_bundle",
            side_effect=self._fake_prepare_bundle,
        ):
            confirmed = self.client.post(
                f"/api/autonomy/cases/{self.case['id']}/scenarios/confirm",
                json=self._confirmation_payload(
                    [baseline],
                    idempotency_key="complete-brief-confirmation",
                ),
            )
        self.assertEqual(202, confirmed.status_code, confirmed.text)
        confirmation = state.AGENT_STORE.get_decision_scenario_confirmation(
            confirmed.json()["confirmation"]["confirmation_id"]
        )
        self.assertIsNotNone(confirmation)
        job_id = confirmed.json()["jobs"][0]["job_id"]
        claimed = state.AGENT_STORE.claim_next_queued_work(
            worker_id="decision-brief-api-test"
        )
        self.assertIsNotNone(claimed)
        self.assertEqual(job_id, claimed["id"])
        result_payload = {"schema_version": 3, "verified_fixture": True}
        result_provenance = {
            "schema_version": 1,
            "fixture": "store-authority-only",
        }
        state.AGENT_STORE.update_technoeconomic_job(
            job_id,
            expected_worker_id="decision-brief-api-test",
            expected_lease_token=claimed["lease_token"],
            state="done",
            stage="Done",
            result=result_payload,
            result_provenance=result_provenance,
            artifacts={},
        )
        execution = state.AGENT_STORE.reconcile_decision_case_execution(
            self.case["id"]
        )
        self.assertTrue(execution["all_successful"])
        current_case = self._current_case()
        self.assertEqual("results_ready", current_case["status"])
        scenario_record = state.AGENT_STORE.get_decision_scenario(
            confirmation["items"][0]["scenario_revision_id"]
        )
        completed_job = scenario_record["jobs"][0]
        attempt_proof = {
            "item_index": 0,
            "scenario_revision_id": scenario_record["scenario_revision_id"],
            "scenario_id": scenario_record["scenario_id"],
            "scenario_revision": scenario_record["revision"],
            "attempt_number": 1,
            "tea_job_id": job_id,
            "retry_of_job_id": None,
            "selected_for_comparison": True,
            "state": "done",
            "verification_status": "verified",
            "request_sha256": scenario_record["request_sha256"],
            "source_snapshot_sha256": completed_job[
                "source_snapshot_sha256"
            ],
            "result_sha256": technoeconomic_api.canonical_json_sha256(
                result_payload
            ),
            "result_provenance_sha256": (
                technoeconomic_api.canonical_json_sha256(result_provenance)
            ),
            "evidence_set_sha256": technoeconomic_api.canonical_json_sha256([]),
            "reporting_tieout_sha256": "9" * 64,
        }
        bundle = {
            "schema_version": "autonomy-comparison-bundle-v1",
            "is_complete": True,
            "recommendation_eligible": False,
            "case": {
                "case_id": self.case["id"],
                "expected_case_revision": current_case["revision"],
            },
            "confirmation": {
                "confirmation_id": confirmation["id"],
            },
            "completeness": {
                "status": "complete",
                "selected_count": 1,
                "verified_done_count": 1,
                "blockers": [],
            },
            "attempt_proofs": [attempt_proof],
            "scenarios": [
                {
                    "scenario_id": scenario_record["scenario_id"],
                    "scenario_revision_id": scenario_record[
                        "scenario_revision_id"
                    ],
                    "request_sha256": scenario_record["request_sha256"],
                    "attempt": {
                        "tea_job_id": job_id,
                        "attempt_number": 1,
                        "display_status": "done",
                    },
                    "verification": {"status": "verified"},
                    "result": {
                        "metrics": {},
                        "warnings": [
                            {
                                "code": "provisional_inputs",
                                "source": "evidence",
                            }
                        ],
                    },
                }
            ],
            "recommendation": {
                "state": "classification_pending_contract",
                "classification": None,
                "confidence": None,
                "reversal_conditions": [],
            },
            "canonicalization": {
                "version": "canonical-json-sha256-v1",
                "excluded_fields": ["bundle_hash"],
            },
            "warnings": [
                {
                    "code": "classification_pending_contract",
                    "message": "No deterministic winner threshold is approved.",
                }
            ],
        }
        bundle["bundle_hash"] = (
            comparison_service.canonical_comparison_bundle_sha256(bundle)
        )
        bundle_record = state.AGENT_STORE.create_decision_comparison_bundle(
            self.case["id"],
            expected_case_revision=current_case["revision"],
            source_confirmation_id=confirmation["id"],
            bundle=bundle,
            bundle_sha256=bundle["bundle_hash"],
            attempt_proofs=[attempt_proof],
            created_by="Alex Operator",
        )

        request_payload = {
            "expected_case_revision": bundle_record["case_revision_after"],
            "comparison_bundle_id": bundle_record["comparison_bundle_id"],
            "bundle_sha256": bundle_record["bundle_sha256"],
            "operator_name": "Alex Operator",
            "idempotency_key": "complete-pending-brief-create",
        }
        with (
            patch.object(
                autonomy_api,
                "_build_verified_comparison_snapshot",
                return_value=({"is_complete": False}, "0" * 64),
            ),
            patch.object(
                state.AGENT_STORE,
                "mark_decision_comparison_bundle_stale",
            ) as mark_stale,
        ):
            failed_admission = self.client.post(
                f"/api/autonomy/cases/{self.case['id']}/decision-briefs",
                json=request_payload,
            )
        self.assertEqual(409, failed_admission.status_code, failed_admission.text)
        self.assertEqual(
            "brief_admission_reverification_failed",
            failed_admission.json()["detail"]["code"],
        )
        mark_stale.assert_called_once()

        with patch.object(
            autonomy_api,
            "_build_verified_comparison_snapshot",
            return_value=(bundle, bundle["bundle_hash"]),
        ):
            created = self.client.post(
                f"/api/autonomy/cases/{self.case['id']}/decision-briefs",
                json=request_payload,
            )
        self.assertEqual(201, created.status_code, created.text)
        brief = created.json()["decision_brief"]
        self.assertFalse(brief["signed"])
        self.assertEqual(
            "classification_pending_contract",
            brief["recommendation_classification"],
        )
        self.assertEqual(
            "classification_pending_contract",
            brief["confidence_state"],
        )
        self.assertEqual(
            "classification_pending_contract",
            brief["caveats"][0]["code"],
        )
        self.assertEqual(
            {
                "source": "scenario_result_warning",
                "scenario_id": scenario_record["scenario_id"],
                "scenario_revision_id": scenario_record[
                    "scenario_revision_id"
                ],
                "tea_job_id": job_id,
                "attempt_number": 1,
                "warning": {
                    "code": "provisional_inputs",
                    "source": "evidence",
                },
            },
            brief["caveats"][1],
        )
        self.assertFalse(created.json()["idempotent_replay"])
        self.assertEqual("results_ready", created.json()["case"]["status"])
        self.assertNotEqual("decision_ready", created.json()["case"]["status"])

        listed_briefs = self.client.get(
            f"/api/autonomy/cases/{self.case['id']}/decision-briefs"
        )
        self.assertEqual(200, listed_briefs.status_code, listed_briefs.text)
        self.assertEqual(
            listed_briefs.json()["case"]["revision"],
            listed_briefs.json()["case_revision"],
        )
        self.assertEqual(
            brief["brief_revision_id"],
            listed_briefs.json()["decision_briefs"][0]["brief_revision_id"],
        )

        replay = self.client.post(
            f"/api/autonomy/cases/{self.case['id']}/decision-briefs",
            json=request_payload,
        )
        self.assertEqual(201, replay.status_code, replay.text)
        self.assertTrue(replay.json()["idempotent_replay"])
        self.assertEqual(
            brief["brief_revision_id"],
            replay.json()["decision_brief"]["brief_revision_id"],
        )

        state.AGENT_STORE.mark_decision_comparison_bundle_stale(
            bundle_record["comparison_bundle_id"],
            reason={"code": "qualifying_result_changed_after_commit"},
        )
        stale_replay = self.client.post(
            f"/api/autonomy/cases/{self.case['id']}/decision-briefs",
            json=request_payload,
        )
        self.assertEqual(201, stale_replay.status_code, stale_replay.text)
        self.assertTrue(stale_replay.json()["idempotent_replay"])
        self.assertEqual(
            brief["brief_revision_id"],
            stale_replay.json()["decision_brief"]["brief_revision_id"],
        )

        tampered = deepcopy(request_payload)
        tampered["bundle_sha256"] = "0" * 64
        rejected = self.client.post(
            f"/api/autonomy/cases/{self.case['id']}/decision-briefs",
            json=tampered,
        )
        self.assertEqual(409, rejected.status_code, rejected.text)
        self.assertEqual(
            "comparison_bundle_hash_mismatch",
            rejected.json()["detail"]["code"],
        )

    def test_live_build_then_brief_reverification_freezes_bundle_revision(self) -> None:
        baseline = self._validated_baseline()
        with patch.object(
            autonomy_api.scenarios,
            "prepare_technoeconomic_bundle",
            side_effect=self._fake_prepare_bundle,
        ):
            confirmed = self.client.post(
                f"/api/autonomy/cases/{self.case['id']}/scenarios/confirm",
                json=self._confirmation_payload(
                    [baseline],
                    idempotency_key="revision-frozen-brief-confirmation",
                ),
            )
        self.assertEqual(202, confirmed.status_code, confirmed.text)
        job_id = confirmed.json()["jobs"][0]["job_id"]
        claimed = state.AGENT_STORE.claim_next_queued_work(
            worker_id="revision-frozen-brief-worker"
        )
        self.assertIsNotNone(claimed)
        assert claimed is not None
        stored_job = state.AGENT_STORE.get_technoeconomic_job(job_id)
        self.assertIsNotNone(stored_job)
        assert stored_job is not None
        outcome = _verified_outcome(
            job_id,
            source_snapshot_sha256=stored_job["source_snapshot_sha256"],
        )
        self.assertIsNotNone(outcome.verified_result)
        assert outcome.verified_result is not None
        state.AGENT_STORE.update_technoeconomic_job(
            job_id,
            expected_worker_id="revision-frozen-brief-worker",
            expected_lease_token=claimed["lease_token"],
            state="done",
            stage="Done",
            result=outcome.verified_result.result,
            result_provenance=outcome.verified_result.result_provenance,
            artifacts={},
        )
        state.AGENT_STORE.reconcile_decision_case_execution(self.case["id"])
        comparison_revision = self._current_case()["revision"]
        confirmation_id = confirmed.json()["confirmation"]["confirmation_id"]

        with patch.object(
            autonomy_api.result_verification,
            "verify_completed_technoeconomic_result",
            return_value=outcome,
        ):
            built = self.client.post(
                f"/api/autonomy/cases/{self.case['id']}/comparison-bundles",
                json={
                    "expected_case_revision": comparison_revision,
                    "confirmation_id": confirmation_id,
                    "operator_name": "Alex Operator",
                },
            )
        self.assertEqual(201, built.status_code, built.text)
        comparison_bundle = built.json()["comparison_bundle"]
        self.assertEqual(
            comparison_revision,
            comparison_bundle["expected_case_revision"],
        )
        self.assertEqual(
            comparison_revision + 1,
            comparison_bundle["case_revision_after"],
        )

        with patch.object(
            autonomy_api.result_verification,
            "verify_completed_technoeconomic_result",
            return_value=outcome,
        ):
            brief = self.client.post(
                f"/api/autonomy/cases/{self.case['id']}/decision-briefs",
                json={
                    "expected_case_revision": comparison_bundle[
                        "case_revision_after"
                    ],
                    "comparison_bundle_id": comparison_bundle[
                        "comparison_bundle_id"
                    ],
                    "bundle_sha256": comparison_bundle["bundle_sha256"],
                    "operator_name": "Alex Operator",
                    "idempotency_key": "revision-frozen-brief-create",
                },
            )
        self.assertEqual(201, brief.status_code, brief.text)
        self.assertEqual(
            "classification_pending_contract",
            brief.json()["decision_brief"]["recommendation_classification"],
        )


if __name__ == "__main__":
    unittest.main()
