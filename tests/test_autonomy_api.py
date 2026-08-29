from __future__ import annotations

import asyncio
import base64
from datetime import datetime, timedelta, timezone
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
        self.readiness_patch.start()
        self.sources_patch.start()

    def _cleanup(self) -> None:
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

    def test_decision_brief_signoff_and_report_routes_do_not_exist(self):
        case_id = self._create_case()["case_id"]
        for suffix in ("decision-brief", "signoff", "reports"):
            response = self.client.post(
                f"/api/autonomy/cases/{case_id}/{suffix}", json={}
            )
            self.assertEqual(response.status_code, 404, suffix)


if __name__ == "__main__":
    unittest.main()
