from __future__ import annotations

import asyncio
import base64
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import shutil
import unittest
import uuid
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from sbepv.api import autonomy as autonomy_api
from sbepv.api import config, state
from sbepv.api import main as app
from sbepv.store import AgentStore


class _SafeAgentFailure(RuntimeError):
    code = "agent_unavailable"
    detail = "safe"
    trace_id = None


class AutonomyApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = (
            Path(__file__).resolve().parent / f"autonomy-api-{uuid.uuid4().hex}"
        )
        self.root.mkdir(parents=False, exist_ok=False)
        self.addCleanup(self._cleanup)
        self.original_store = state.AGENT_STORE
        self.original_evidence_dir = config.DECISION_EVIDENCE_DIR
        state.AGENT_STORE = AgentStore(self.root / "agent.sqlite3")
        state.DECISION_AGENT_TASKS.clear()
        config.DECISION_EVIDENCE_DIR = self.root / ".decision_evidence"
        config.DECISION_EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
        self.client = TestClient(app.app)
        self.readiness_patch = patch.object(
            autonomy_api.readiness,
            "evaluate_decision_case_readiness",
            side_effect=self._fake_readiness,
        )
        self.sources_patch = patch.object(
            autonomy_api.readiness,
            "list_eligible_annual_sources",
            return_value=[],
        )
        self.shadow_patch = patch.object(
            config, "DECISION_AGENT_SHADOW_MODE", False
        )
        self.readiness_patch.start()
        self.sources_patch.start()
        self.shadow_patch.start()

    def _cleanup(self) -> None:
        self.shadow_patch.stop()
        self.readiness_patch.stop()
        self.sources_patch.stop()
        state.DECISION_AGENT_TASKS.clear()
        state.AGENT_STORE = self.original_store
        config.DECISION_EVIDENCE_DIR = self.original_evidence_dir
        shutil.rmtree(self.root, ignore_errors=True)

    @staticmethod
    def _fake_readiness(case_id, **_kwargs):
        case = state.AGENT_STORE.get_decision_case(case_id)
        if case is None:
            raise KeyError(case_id)
        return {
            "schema_version": "decision-readiness-v1",
            "case_id": case_id,
            "case_revision": case["revision"],
            "evaluated_at": "2026-08-29T12:00:00+00:00",
            "overall_status": "needs_attention",
            "ready_to_run": False,
            "suggested_case_status": "evidence_needed",
            "checks": [],
            "blockers": [
                {
                    "code": "scenario_execution_not_in_phase",
                    "blocking": True,
                }
            ],
            "supported_next_actions": [],
            "allowed_case_actions": [
                {"id": "upload_evidence", "enabled": True},
                {"id": "ask_decision_agent", "enabled": True},
            ],
            "eligible_annual_sources": [],
            "supported_analysis_bases": [],
            "phase_boundary": {
                "current_phase": "agent_and_evidence",
                "scenario_execution_available": False,
            },
        }

    def _create_case(self, *, title="Architecture decision"):
        response = self.client.post(
            "/api/autonomy/cases",
            json={
                "title": title,
                "question": "What supports this decision?",
                "operator_name": "Jordan Lee",
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()["case"]

    def test_case_crud_is_revisioned_and_archive_is_read_only(self):
        created = self._create_case()
        case_id = created["case_id"]

        listed = self.client.get("/api/autonomy/cases")
        self.assertEqual(listed.status_code, 200)
        self.assertEqual([item["case_id"] for item in listed.json()["cases"]], [case_id])

        updated = self.client.put(
            f"/api/autonomy/cases/{case_id}",
            json={
                "expected_revision": created["revision"],
                "operator_name": "Jordan Lee",
                "question": "Why does the verified basis support this decision?",
                "decision_owner": "Alex Kim",
            },
        )
        self.assertEqual(updated.status_code, 200, updated.text)
        update_case = updated.json()["case"]
        self.assertEqual(update_case["owner"], "Alex Kim")
        self.assertEqual(
            update_case["original_question"], "What supports this decision?"
        )

        stale = self.client.put(
            f"/api/autonomy/cases/{case_id}",
            json={
                "expected_revision": created["revision"],
                "operator_name": "Jordan Lee",
                "title": "Stale edit",
            },
        )
        self.assertEqual(stale.status_code, 409)

        current = state.AGENT_STORE.get_decision_case(case_id)
        archived = self.client.post(
            f"/api/autonomy/cases/{case_id}/archive",
            json={
                "expected_revision": current["revision"],
                "operator_name": "Jordan Lee",
                "reason": "Decision scope closed.",
            },
        )
        self.assertEqual(archived.status_code, 200, archived.text)
        self.assertEqual(archived.json()["case"]["status"], "archived")
        self.assertEqual(self.client.get("/api/autonomy/cases").json()["cases"], [])
        self.assertEqual(
            len(
                self.client.get(
                    "/api/autonomy/cases", params={"include_archived": "true"}
                ).json()["cases"]
            ),
            1,
        )

    def test_eligible_source_and_analysis_basis_lock_is_one_way(self):
        case = self._create_case()
        case_id = case["case_id"]
        annual_job = state.AGENT_STORE.create_job(
            job_id="annual-live-source",
            kind="manual",
            mode="annual",
            request={"mode": "annual", "years": [2024]},
            source_path="artifacts/annual-live-source/midc.csv",
            source_hash="1" * 64,
        )
        state.AGENT_STORE.claim_next_queued_job()
        annual_job = state.AGENT_STORE.update_job(
            annual_job["id"],
            state="done",
            stage="Done",
            result={
                "stats": {"calibration_enabled": True},
                "calibration_application": {"applied": True},
            },
            provenance={"source": "test"},
        )
        snapshot_sha256 = "a" * 64
        source_summary = {
            "eligible": True,
            "annual_job_id": annual_job["id"],
            "source_snapshot_sha256": snapshot_sha256,
            "completed_at": "2026-08-29T12:00:00+00:00",
            "eligible_years": list(range(2012, 2022)) + [2024, 2025],
        }
        autonomy_api.readiness.list_eligible_annual_sources.return_value = [
            source_summary
        ]

        sources = self.client.get("/api/autonomy/sources")
        self.assertEqual(sources.status_code, 200, sources.text)
        self.assertEqual(sources.json()["sources"], [source_summary])
        self.assertEqual(
            {item["id"] for item in sources.json()["analysis_bases"]},
            {"solartac_site", "commercial_representative"},
        )

        locked = self.client.put(
            f"/api/autonomy/cases/{case_id}",
            json={
                "expected_revision": case["revision"],
                "operator_name": "Jordan Lee",
                "source_annual_job_id": annual_job["id"],
                "source_snapshot_sha256": snapshot_sha256,
                "analysis_basis": "solartac_site",
            },
        )
        self.assertEqual(locked.status_code, 200, locked.text)
        lock = locked.json()["case"]["source_lock"]
        self.assertTrue(lock["locked"])
        self.assertEqual(lock["annual_job_id"], annual_job["id"])
        self.assertEqual(lock["source_snapshot_sha256"], snapshot_sha256)
        self.assertEqual(lock["analysis_basis"], "solartac_site")

        immutable = self.client.put(
            f"/api/autonomy/cases/{case_id}",
            json={
                "expected_revision": locked.json()["case"]["revision"],
                "operator_name": "Jordan Lee",
                "source_annual_job_id": annual_job["id"],
                "source_snapshot_sha256": snapshot_sha256,
                "analysis_basis": "commercial_representative",
            },
        )
        self.assertEqual(immutable.status_code, 409, immutable.text)

    def test_basic_auth_protects_autonomy_routes(self):
        credentials = {
            "DASHBOARD_BASIC_USER": "dashboard-user",
            "DASHBOARD_BASIC_PASSWORD": "secret",
        }
        payload = {
            "title": "Protected case",
            "question": "Is this protected?",
            "operator_name": "Jordan Lee",
        }
        with patch.dict("os.environ", credentials):
            unauthorized = self.client.post("/api/autonomy/cases", json=payload)
            token = base64.b64encode(b"dashboard-user:secret").decode("ascii")
            authorized = self.client.post(
                "/api/autonomy/cases",
                json=payload,
                headers={"Authorization": f"Basic {token}"},
            )
        self.assertEqual(unauthorized.status_code, 401)
        self.assertEqual(authorized.status_code, 201, authorized.text)

    def test_csv_upload_review_download_tamper_and_deletion_guard(self):
        case = self._create_case()
        case_id = case["case_id"]
        payload = b"installed_cost (USD/kW),source_year\n1200,2025\n"
        uploaded = self.client.post(
            f"/api/autonomy/cases/{case_id}/evidence",
            files={"file": ("project-cost.csv", payload, "text/csv")},
            data={
                "evidence_class": "project_actual",
                "operator_name": "Jordan Lee",
            },
        )
        self.assertEqual(uploaded.status_code, 201, uploaded.text)
        asset = uploaded.json()["evidence"]
        self.assertNotIn("storage_key", asset)
        self.assertNotIn(str(self.root), uploaded.text)
        self.assertEqual(asset["content_sha256"], asset["content_sha256"].lower())
        self.assertGreaterEqual(len(asset["candidates"]), 1)
        self.assertIsInstance(asset["candidates"][0]["source_location"], dict)

        download = self.client.get(asset["download_url"])
        self.assertEqual(download.status_code, 200, download.text)
        self.assertEqual(download.content, payload)
        self.assertEqual(download.headers["x-content-type-options"], "nosniff")

        candidate = asset["candidates"][0]
        revision = state.AGENT_STORE.get_decision_case(case_id)["revision"]
        reviewed = self.client.post(
            f"/api/autonomy/cases/{case_id}/evidence/{asset['evidence_id']}/candidates/{candidate['candidate_id']}/review",
            json={
                "decision": "accepted",
                "operator_name": "Jordan Lee",
                "rationale": "Matches the approved project ledger.",
                "expected_revision": revision,
            },
        )
        self.assertEqual(reviewed.status_code, 200, reviewed.text)
        receipt = reviewed.json()["receipt"]
        self.assertEqual(receipt["preservation_mode"], "server_managed_content_v1")
        self.assertEqual(receipt["content_sha256"], asset["content_sha256"])

        revision = state.AGENT_STORE.get_decision_case(case_id)["revision"]
        guarded = self.client.request(
            "DELETE",
            f"/api/autonomy/cases/{case_id}/evidence/{asset['evidence_id']}",
            json={
                "operator_name": "Jordan Lee",
                "reason": "Attempted removal.",
                "expected_revision": revision,
            },
        )
        self.assertEqual(guarded.status_code, 409)

        private = state.AGENT_STORE.get_decision_evidence_asset(asset["evidence_id"])
        storage_path = config.DECISION_EVIDENCE_DIR.joinpath(
            *private["storage_key"].split("/")
        )
        storage_path.write_bytes(b"tampered")
        tampered = self.client.get(asset["download_url"])
        self.assertEqual(tampered.status_code, 409)
        self.assertNotIn(str(storage_path), tampered.text)

    def test_upload_rejects_unsafe_filename_and_mime_mismatch(self):
        case_id = self._create_case()["case_id"]
        unsafe = self.client.post(
            f"/api/autonomy/cases/{case_id}/evidence",
            files={"file": ("../outside.csv", b"a,b\n1,2\n", "text/csv")},
            data={
                "evidence_class": "project_actual",
                "operator_name": "Jordan Lee",
            },
        )
        self.assertEqual(unsafe.status_code, 400, unsafe.text)
        self.assertEqual(unsafe.json()["detail"]["code"], "unsafe_filename")

        mismatch = self.client.post(
            f"/api/autonomy/cases/{case_id}/evidence",
            files={"file": ("fake.png", b"a,b\n1,2\n", "image/png")},
            data={
                "evidence_class": "project_actual",
                "operator_name": "Jordan Lee",
            },
        )
        self.assertEqual(mismatch.status_code, 400, mismatch.text)
        self.assertIn(
            mismatch.json()["detail"]["code"],
            {"malformed_image", "mime_type_mismatch"},
        )

    def test_message_stream_completes_and_replays_from_durable_cursor(self):
        case_id = self._create_case()["case_id"]
        created = self.client.post(
            f"/api/autonomy/cases/{case_id}/messages",
            json={
                "message": "Why is this case blocked?",
                "client_message_id": "client-001",
                "operator_name": "Jordan Lee",
            },
        )
        self.assertEqual(created.status_code, 202, created.text)
        turn = created.json()["turn"]
        self.assertNotIn("claim_token", turn)

        result = {
            "assistant_message": "The exact blocker is missing accepted evidence.",
            "structured_output": {
                "answer_kind": "why",
                "status": "blocked",
                "non_runnable": True,
            },
            "citations": [{"source_type": "readiness", "source_id": case_id}],
            "tool_outcomes": [
                {"name": "read_readiness", "status": "ok", "result_summary": "blocked"}
            ],
            "trace_id": "trace_" + "1" * 32,
            "timing": {"duration_ms": 1, "timeout_seconds": 45, "timed_out": False},
        }
        async def complete_with_claimed_trace(*_args, trace_id=None, **_kwargs):
            return {**result, "trace_id": trace_id}

        with patch.object(
            autonomy_api.decision_agent_module,
            "run_decision_agent_turn",
            new=AsyncMock(side_effect=complete_with_claimed_trace),
        ) as run_agent:
            streamed = self.client.get(
                f"/api/autonomy/cases/{case_id}/message-stream/{turn['turn_id']}"
            )
        self.assertEqual(streamed.status_code, 200, streamed.text)
        self.assertIn("event: status", streamed.text)
        self.assertIn("event: final", streamed.text)
        self.assertIn("missing accepted evidence", streamed.text)
        run_agent.assert_awaited_once()

        events = self.client.get(f"/api/autonomy/cases/{case_id}/events").json()
        terminal_cursor = events["next_event_id"]
        replay = self.client.get(
            f"/api/autonomy/cases/{case_id}/message-stream/{turn['turn_id']}",
            params={"after_event_id": terminal_cursor},
        )
        self.assertEqual(replay.status_code, 200)
        self.assertEqual(replay.text, "")
        messages = self.client.get(
            f"/api/autonomy/cases/{case_id}/messages"
        ).json()["messages"]
        self.assertEqual([item["role"] for item in messages], ["user", "assistant"])
        self.assertRegex(messages[-1]["trace_id"], r"^trace_[0-9a-f]{32}$")

    def test_agent_unavailable_stream_is_terminal_and_manual_state_survives(self):
        case_id = self._create_case()["case_id"]
        turn = self.client.post(
            f"/api/autonomy/cases/{case_id}/messages",
            json={
                "message": "What does this metric mean?",
                "client_message_id": "client-002",
                "operator_name": "Jordan Lee",
            },
        ).json()["turn"]
        with patch.object(
            autonomy_api.decision_agent_module,
            "run_decision_agent_turn",
            new=AsyncMock(side_effect=_SafeAgentFailure("unavailable")),
        ):
            streamed = self.client.get(
                f"/api/autonomy/cases/{case_id}/message-stream/{turn['turn_id']}"
            )
        self.assertEqual(streamed.status_code, 200)
        self.assertIn("event: error", streamed.text)
        self.assertIn("Deterministic readiness", streamed.text)
        durable = state.AGENT_STORE.get_decision_turn(turn["turn_id"])
        self.assertEqual(durable["state"], "failed")
        self.assertEqual(durable["error_code"], "agent_unavailable")

    def test_shutdown_only_fails_turns_claimed_by_this_process(self):
        case_id = self._create_case()["case_id"]
        local_turn = state.AGENT_STORE.create_decision_turn(
            case_id,
            client_message_id="local-worker",
            user_message="Will the local worker finish?",
            operator_name="Jordan Lee",
        )
        other_turn = state.AGENT_STORE.create_decision_turn(
            case_id,
            client_message_id="other-worker",
            user_message="Will the other worker finish?",
            operator_name="Jordan Lee",
        )
        state.AGENT_STORE.claim_decision_turn(
            local_turn["id"],
            worker_id=autonomy_api._decision_worker_id(),
            trace_id="trace-local-worker",
        )
        state.AGENT_STORE.claim_decision_turn(
            other_turn["id"],
            worker_id="decision-agent:another-process",
            trace_id="trace-other-worker",
        )

        asyncio.run(autonomy_api.shutdown_decision_agent_tasks())

        local = state.AGENT_STORE.get_decision_turn(local_turn["id"])
        other = state.AGENT_STORE.get_decision_turn(other_turn["id"])
        self.assertEqual("failed", local["state"])
        self.assertEqual("claimed", other["state"])
        events = state.AGENT_STORE.list_decision_events(
            case_id, turn_id=local_turn["id"]
        )
        self.assertEqual(
            "worker_shutdown", events[-1]["payload"]["recovery_reason"]
        )

    def test_stream_reconnect_respects_then_recovers_expired_foreign_claim(self):
        now = [datetime.now(timezone.utc)]
        state.AGENT_STORE._now = lambda: now[0]
        case_id = self._create_case()["case_id"]
        turn = state.AGENT_STORE.create_decision_turn(
            case_id,
            client_message_id="interrupted-foreign-worker",
            user_message="Why is this case blocked?",
            operator_name="Jordan Lee",
        )
        claimed = state.AGENT_STORE.claim_decision_turn(
            turn["id"],
            worker_id="decision-agent:another-process",
            trace_id="trace-interrupted-worker",
        )
        claimed_at = datetime.fromisoformat(claimed["claimed_at"])

        class ControlledDateTime:
            @classmethod
            def now(cls, tz=None):
                current = now[0]
                return current if tz is None else current.astimezone(tz)

        with (
            patch.object(config, "DECISION_AGENT_TURN_STALE_SECONDS", 120),
            patch.object(autonomy_api, "datetime", ControlledDateTime),
        ):
            now[0] = claimed_at + timedelta(seconds=119)
            observed = autonomy_api._ensure_turn_task(case_id, turn["id"])
            self.assertEqual("claimed", observed["state"])
            self.assertEqual(
                "claimed", state.AGENT_STORE.get_decision_turn(turn["id"])["state"]
            )

            now[0] = claimed_at + timedelta(seconds=121)
            streamed = self.client.get(
                f"/api/autonomy/cases/{case_id}/message-stream/{turn['id']}"
            )

        self.assertEqual(200, streamed.status_code, streamed.text)
        self.assertIn("event: error", streamed.text)
        self.assertIn("agent_interrupted", streamed.text)
        recovered = state.AGENT_STORE.get_decision_turn(turn["id"])
        self.assertEqual("failed", recovered["state"])
        self.assertEqual(
            "Why is this case blocked?",
            recovered["user_message"]["content_text"],
        )
        events = state.AGENT_STORE.list_decision_events(
            case_id, turn_id=turn["id"]
        )
        self.assertEqual(
            "stale_claim_after_process_restart",
            events[-1]["payload"]["recovery_reason"],
        )

    def test_lifespan_uses_bounded_decision_turn_stale_cutoff(self):
        recovery_calls = []

        def record_recovery(**kwargs):
            recovery_calls.append(kwargs)
            return 0

        async def exercise_lifespan():
            with (
                patch.object(app, "_dashboard_basic_credentials"),
                patch.object(
                    state.AGENT_STORE,
                    "mark_stale_claimed_decision_turns_failed",
                    side_effect=record_recovery,
                ),
                patch.object(config, "DECISION_AGENT_TURN_STALE_SECONDS", 73),
                patch.object(
                    app.worker_loop,
                    "_mark_stale_running_work_interrupted",
                    return_value={"model": 0, "technoeconomic": 0},
                ),
                patch.object(app.worker_loop, "_start_model_worker"),
                patch.object(app.worker_loop, "_stop_model_worker"),
                patch.object(
                    autonomy_api,
                    "shutdown_decision_agent_tasks",
                    new=AsyncMock(),
                ),
            ):
                started_at = datetime.now(timezone.utc)
                async with app._app_lifespan(app.app):
                    pass
                finished_at = datetime.now(timezone.utc)
            return started_at, finished_at

        started_at, finished_at = asyncio.run(exercise_lifespan())

        self.assertEqual(1, len(recovery_calls))
        cutoff = recovery_calls[0]["before"]
        lease = timedelta(seconds=73)
        self.assertGreaterEqual(cutoff, started_at - lease)
        self.assertLessEqual(cutoff, finished_at - lease)
        self.assertNotIn("worker_id", recovery_calls[0])

    def test_legacy_singular_decision_authority_routes_do_not_exist(self):
        case_id = self._create_case()["case_id"]
        for suffix in ("decision-brief", "signoff"):
            response = self.client.post(
                f"/api/autonomy/cases/{case_id}/{suffix}", json={}
            )
            self.assertEqual(response.status_code, 404, suffix)

    def test_authority_routes_require_both_configured_principal_and_intent(self):
        case_id = self._create_case()["case_id"]
        report_url = f"/api/autonomy/cases/{case_id}/reports"
        signoff_url = (
            f"/api/autonomy/cases/{case_id}/decision-briefs/dbr_abc123/signoffs"
        )
        shadow_url = "/api/autonomy/shadow-reviews"
        authority_requests = (
            (
                report_url,
                {
                    "expected_case_revision": 1,
                    "report_kind": "draft",
                    "brief_revision_id": "dbr_abc123",
                    "idempotency_key": "report-auth-gate",
                },
            ),
            (
                signoff_url,
                {
                    "expected_case_revision": 1,
                    "disposition": "defer",
                    "decision_owner_name": "Decision Owner",
                    "rationale": "Defer until the exact evidence is reviewed.",
                    "acknowledgement_text": (
                        autonomy_api._DECISION_ACKNOWLEDGEMENT_TEXT
                    ),
                    "acknowledgement_version": (
                        autonomy_api._DECISION_ACKNOWLEDGEMENT_VERSION
                    ),
                    "provisional_warning_acknowledgements": [],
                    "idempotency_key": "signoff-auth-gate",
                },
            ),
            (
                shadow_url,
                {
                    "case_id": case_id,
                    "brief_revision_id": "dbr_abc123",
                    "report_id": "drpt_abc123",
                    "report_snapshot_sha256": "1" * 64,
                    "pdf_sha256": "2" * 64,
                    "report_identity_sha256": "3" * 64,
                    "review_case_key": "auth-gate-shadow-case",
                    "checklist_version": "autonomy-shadow-review-v2",
                    "reviewer_name": "Human Reviewer",
                    "outcome": "passed",
                    "review": {
                        "unauthorized_execution_observed": False,
                        "numeric_citations_verified": True,
                        "result_tie_out_verified": True,
                        "report_tie_out_verified": True,
                    },
                },
            ),
        )

        with patch.dict(
            os.environ,
            {"DASHBOARD_BASIC_USER": "", "DASHBOARD_BASIC_PASSWORD": ""},
        ):
            for url, payload in authority_requests:
                with self.subTest(url=url, gate="intent"):
                    response = self.client.post(url, json=payload)
                    self.assertEqual(403, response.status_code, response.text)
                    self.assertEqual(
                        "human_action_intent_required",
                        response.json()["detail"]["code"],
                    )
                with self.subTest(url=url, gate="principal"):
                    response = self.client.post(
                        url,
                        headers={"X-Autonomy-Human-Action": "1"},
                        json=payload,
                    )
                    self.assertEqual(403, response.status_code, response.text)
                    self.assertEqual(
                        "authenticated_principal_required",
                        response.json()["detail"]["code"],
                    )

        authorization = "Basic " + base64.b64encode(
            b"authority-user:authority-password"
        ).decode("ascii")
        with patch.dict(
            os.environ,
            {
                "DASHBOARD_BASIC_USER": "authority-user",
                "DASHBOARD_BASIC_PASSWORD": "authority-password",
            },
        ):
            missing_intent = self.client.post(
                report_url,
                headers={"Authorization": authorization},
                json=authority_requests[0][1],
            )
            self.assertEqual(403, missing_intent.status_code, missing_intent.text)
            self.assertEqual(
                "human_action_intent_required",
                missing_intent.json()["detail"]["code"],
            )
            crossed_both_gates = self.client.post(
                report_url,
                headers={
                    "Authorization": authorization,
                    "X-Autonomy-Human-Action": "1",
                },
                json=authority_requests[0][1],
            )
            self.assertEqual(404, crossed_both_gates.status_code, crossed_both_gates.text)

    def test_release_readiness_separates_behavior_evals_from_human_reviews(self):
        renderer = autonomy_api.decision_reporting.renderer_fingerprint()
        reviews = []
        reports = {}
        tampered_report_ids = set()

        def add_review(index, outcome="passed", *, case_id=None):
            suffix = f"{index + 1:x}" * 64
            case_id = case_id or f"case_shadow{index}"
            report_id = f"drpt_shadow{index}"
            report = {
                "report_id": report_id,
                "case_id": case_id,
                "brief_revision_id": f"dbr_shadow{index}",
                "report_kind": "draft",
                "signoff_id": None,
                "snapshot_sha256": suffix,
                "pdf_sha256": suffix[::-1],
                "report_identity_sha256": (f"{15 - index:x}" * 64),
                "recommendation_contract_version": (
                    autonomy_api.recommendation_service.RECOMMENDATION_CONTRACT_VERSION
                ),
                "recommendation_contract_digest": (
                    autonomy_api.recommendation_service.RECOMMENDATION_CONTRACT_DIGEST
                ),
                "generation_contract_version": (
                    autonomy_api.decision_reporting.REPORT_GENERATION_CONTRACT_VERSION
                ),
                "renderer_fingerprint": renderer,
                "snapshot": {
                    "schema_version": (
                        autonomy_api.decision_reporting.REPORT_SNAPSHOT_SCHEMA_VERSION
                    )
                },
            }
            reports[report_id] = report
            reviews.append(
                {
                    **report,
                    "report_snapshot_sha256": report["snapshot_sha256"],
                    "checklist_version": "autonomy-shadow-review-v2",
                    "outcome": outcome,
                }
            )

        for index in range(10):
            add_review(index)
        add_review(12, case_id="case_shadow0")

        def verify_report(_root, report):
            if report["report_id"] in tampered_report_ids:
                raise autonomy_api.decision_reporting.DecisionReportError(
                    "report_artifact_tampered", "tampered"
                )
            return b"%PDF-fixture", {
                "snapshot_sha256": report["snapshot_sha256"],
                "pdf_sha256": report["pdf_sha256"],
            }

        with (
            patch.object(
                state.AGENT_STORE,
                "list_decision_shadow_reviews",
                side_effect=lambda **_kwargs: list(reviews),
            ) as list_reviews,
            patch.object(
                state.AGENT_STORE,
                "get_decision_report",
                side_effect=lambda report_id: reports.get(report_id),
            ),
            patch.object(
                autonomy_api.decision_reporting,
                "verified_report_pdf",
                side_effect=verify_report,
            ),
            patch.object(config, "DECISION_AGENT_ENABLED", True),
        ):
            with patch.object(config, "DECISION_AGENT_BEHAVIOR_EVAL_CASES", 19):
                incomplete = self.client.get("/api/autonomy/release-readiness")
            self.assertEqual(200, incomplete.status_code, incomplete.text)
            readiness = incomplete.json()["release_readiness"]
            self.assertEqual("incomplete", readiness["automated_gates"]["status"])
            self.assertEqual(
                "incomplete", readiness["automated_gates"]["behavior_evals"]["status"]
            )
            self.assertEqual("complete", readiness["human_shadow_review"]["status"])
            self.assertFalse(readiness["release_ready"])

            with patch.object(config, "DECISION_AGENT_BEHAVIOR_EVAL_CASES", 20):
                complete = self.client.get("/api/autonomy/release-readiness")
            self.assertEqual(200, complete.status_code, complete.text)
            readiness = complete.json()["release_readiness"]
            self.assertEqual("passed", readiness["automated_gates"]["status"])
            self.assertEqual(10, readiness["human_shadow_review"]["passed_cases"])
            self.assertEqual(11, readiness["human_shadow_review"]["verified_cases"])
            self.assertTrue(readiness["release_ready"])

            tampered_report_ids.add("drpt_shadow0")
            with patch.object(config, "DECISION_AGENT_BEHAVIOR_EVAL_CASES", 20):
                tampered = self.client.get("/api/autonomy/release-readiness")
            tampered_readiness = tampered.json()["release_readiness"]
            self.assertEqual(
                1, tampered_readiness["human_shadow_review"]["invalid_evidence_cases"]
            )
            self.assertFalse(tampered_readiness["release_ready"])
            tampered_report_ids.clear()

            add_review(10, "needs_followup")
            with patch.object(config, "DECISION_AGENT_BEHAVIOR_EVAL_CASES", 20):
                followup = self.client.get("/api/autonomy/release-readiness")
            followup_readiness = followup.json()["release_readiness"]
            self.assertEqual(
                1,
                followup_readiness["human_shadow_review"]["needs_followup_cases"],
            )
            self.assertFalse(followup_readiness["release_ready"])

            add_review(11, "failed")
            with patch.object(config, "DECISION_AGENT_BEHAVIOR_EVAL_CASES", 20):
                failed = self.client.get("/api/autonomy/release-readiness")
            self.assertFalse(failed.json()["release_readiness"]["release_ready"])
            self.assertTrue(list_reviews.call_args_list)
            for review_call in list_reviews.call_args_list:
                self.assertEqual(
                    {
                        "checklist_version": "autonomy-shadow-review-v2",
                        "limit": None,
                    },
                    review_call.kwargs,
                )

    def test_shadow_review_requires_shadow_mode_and_exact_verified_draft_report(self):
        renderer = autonomy_api.decision_reporting.renderer_fingerprint()
        report = {
            "report_id": "drpt_shadowbinding",
            "case_id": "case_shadowbinding",
            "brief_revision_id": "dbr_shadowbinding",
            "report_kind": "draft",
            "signoff_id": None,
            "snapshot_sha256": "1" * 64,
            "pdf_sha256": "2" * 64,
            "report_identity_sha256": "3" * 64,
            "recommendation_contract_version": (
                autonomy_api.recommendation_service.RECOMMENDATION_CONTRACT_VERSION
            ),
            "recommendation_contract_digest": (
                autonomy_api.recommendation_service.RECOMMENDATION_CONTRACT_DIGEST
            ),
            "generation_contract_version": (
                autonomy_api.decision_reporting.REPORT_GENERATION_CONTRACT_VERSION
            ),
            "renderer_fingerprint": renderer,
            "snapshot": {
                "schema_version": (
                    autonomy_api.decision_reporting.REPORT_SNAPSHOT_SCHEMA_VERSION
                )
            },
        }
        payload = {
            "case_id": report["case_id"],
            "brief_revision_id": report["brief_revision_id"],
            "report_id": report["report_id"],
            "report_snapshot_sha256": report["snapshot_sha256"],
            "pdf_sha256": report["pdf_sha256"],
            "report_identity_sha256": report["report_identity_sha256"],
            "review_case_key": "representative-case-001",
            "checklist_version": "autonomy-shadow-review-v2",
            "reviewer_name": "Human Reviewer",
            "outcome": "passed",
            "review": {
                "unauthorized_execution_observed": False,
                "numeric_citations_verified": True,
                "result_tie_out_verified": True,
                "report_tie_out_verified": True,
            },
        }
        token = base64.b64encode(b"authority-user:authority-password").decode("ascii")
        headers = {
            "Authorization": f"Basic {token}",
            "X-Autonomy-Human-Action": "1",
        }

        def persist_review(**kwargs):
            return {
                **kwargs,
                "shadow_review_id": "dshr_shadowbinding",
                "review_sha256": "4" * 64,
                "reviewed_at": "2026-08-30T12:00:00+00:00",
            }

        with (
            patch.dict(
                os.environ,
                {
                    "DASHBOARD_BASIC_USER": "authority-user",
                    "DASHBOARD_BASIC_PASSWORD": "authority-password",
                },
            ),
            patch.object(config, "DECISION_AGENT_ENABLED", True),
            patch.object(
                state.AGENT_STORE, "get_decision_report", return_value=report
            ),
            patch.object(
                state.AGENT_STORE,
                "create_decision_shadow_review",
                side_effect=persist_review,
            ) as create_review,
            patch.object(
                autonomy_api.decision_reporting,
                "verified_report_pdf",
                return_value=(
                    b"%PDF-fixture",
                    {
                        "snapshot_sha256": report["snapshot_sha256"],
                        "pdf_sha256": report["pdf_sha256"],
                    },
                ),
            ),
        ):
            not_shadow = self.client.post(
                "/api/autonomy/shadow-reviews", headers=headers, json=payload
            )
            self.assertEqual(409, not_shadow.status_code, not_shadow.text)
            self.assertEqual(
                "decision_agent_shadow_mode_required",
                not_shadow.json()["detail"]["code"],
            )

            with patch.object(config, "DECISION_AGENT_SHADOW_MODE", True):
                malformed = self.client.post(
                    "/api/autonomy/shadow-reviews",
                    headers=headers,
                    json={
                        **payload,
                        "review": {**payload["review"], "unexpected": True},
                    },
                )
                self.assertEqual(422, malformed.status_code, malformed.text)

                failed_gate = self.client.post(
                    "/api/autonomy/shadow-reviews",
                    headers=headers,
                    json={
                        **payload,
                        "review": {
                            **payload["review"],
                            "report_tie_out_verified": False,
                        },
                    },
                )
                self.assertEqual(422, failed_gate.status_code, failed_gate.text)
                self.assertEqual(
                    "shadow_review_pass_not_supported",
                    failed_gate.json()["detail"]["code"],
                )

                mismatched = self.client.post(
                    "/api/autonomy/shadow-reviews",
                    headers=headers,
                    json={**payload, "report_snapshot_sha256": "f" * 64},
                )
                self.assertEqual(409, mismatched.status_code, mismatched.text)
                self.assertEqual(
                    "shadow_review_report_identity_mismatch",
                    mismatched.json()["detail"]["code"],
                )

                created = self.client.post(
                    "/api/autonomy/shadow-reviews", headers=headers, json=payload
                )
                self.assertEqual(201, created.status_code, created.text)
                self.assertEqual(
                    report["report_id"], created.json()["shadow_review"]["report_id"]
                )
                self.assertEqual(1, create_review.call_count)


if __name__ == "__main__":
    unittest.main()
