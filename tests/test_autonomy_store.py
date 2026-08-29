from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sbepv.store import (
    AgentStore,
    DECISION_EVIDENCE_MAX_CASE_BYTES,
    DECISION_EVIDENCE_MAX_FILE_BYTES,
    DECISION_EVIDENCE_MAX_FILES_PER_CASE,
    EvidenceLimitExceeded,
    InvalidStateTransition,
    LeaseOwnershipLost,
    RecordNotFound,
    SCHEMA_VERSION,
    StoreConflict,
)


class MutableClock:
    def __init__(self) -> None:
        self.value = datetime(2026, 8, 29, 12, 0, tzinfo=timezone.utc)
        self._lock = threading.Lock()

    def __call__(self) -> datetime:
        with self._lock:
            return self.value

    def advance(self, **kwargs: int) -> None:
        with self._lock:
            self.value += timedelta(**kwargs)


class AutonomyStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        handle = tempfile.NamedTemporaryFile(
            prefix="autonomy-store-test-",
            suffix=".sqlite3",
            dir=Path(__file__).resolve().parent,
            delete=False,
        )
        handle.close()
        self.db_path = Path(handle.name)
        self.addCleanup(self._remove_database_files, self.db_path)
        self.clock = MutableClock()
        self.store = AgentStore(self.db_path, now=self.clock)

    @staticmethod
    def _remove_database_files(path: Path) -> None:
        for candidate in (path, Path(f"{path}-wal"), Path(f"{path}-shm")):
            candidate.unlink(missing_ok=True)

    def _case(self, *, title: str = "Solar architecture decision") -> dict:
        return self.store.create_decision_case(
            title=title,
            question="Why do the two PV systems differ?",
            operator_name="Alex Operator",
        )

    def _completed_annual(self, job_id: str = "annual-autonomy-source") -> dict:
        created = self.store.create_job(
            job_id=job_id,
            kind="manual",
            mode="annual",
            request={"mode": "annual", "years": [2024]},
            source_path=f"artifacts/{job_id}/midc.csv",
            source_hash="1" * 64,
        )
        claimed = self.store.claim_next_queued_job()
        self.assertEqual(created["id"], claimed["id"])
        return self.store.update_job(
            job_id,
            state="done",
            stage="Done",
            result={"mode": "annual", "stats": {}},
            provenance={"source": "test"},
        )

    @staticmethod
    def _asset_kwargs(
        *,
        suffix: str = "a",
        evidence_class: str = "project_actual",
        byte_count: int = 100,
    ) -> dict:
        digest = suffix * 64
        return {
            "original_filename": f"evidence-{suffix}.pdf",
            "display_filename": f"evidence-{suffix}.pdf",
            "media_type": "application/pdf",
            "sha256": digest,
            "byte_count": byte_count,
            "storage_key": f"sha256/{digest[:2]}/{digest}.pdf",
            "evidence_class": evidence_class,
            "operator_name": "Alex Operator",
            "candidates": [
                {
                    "field_name": "initial_cost",
                    "value": 1250.0,
                    "unit": "USD/kWdc",
                    "confidence": 0.92,
                    "source_location": {"page": 2, "line": 14},
                }
            ],
        }

    def test_schema_v6_migrates_v5_and_preserves_existing_jobs(self) -> None:
        source = self._completed_annual()
        with closing(sqlite3.connect(self.db_path)) as connection:
            trigger_rows = connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'trigger' AND ("
                "name LIKE 'decision_%' OR name LIKE '%decision_case%' OR "
                "name IN ('accepted_evidence_removal_guard',"
                "'provisional_evidence_rationale_guard'))"
            ).fetchall()
            for (trigger_name,) in trigger_rows:
                connection.execute(f'DROP TRIGGER "{trigger_name}"')
            for table_name in (
                "decision_events",
                "decision_evidence_receipts",
                "decision_evidence_candidates",
                "decision_evidence_assets",
                "decision_messages",
                "decision_agent_turns",
                "decision_cases",
            ):
                connection.execute(f'DROP TABLE "{table_name}"')
            connection.execute("DELETE FROM schema_migrations WHERE version = 6")
            connection.execute("PRAGMA user_version = 5")
            connection.commit()

        reopened = AgentStore(self.db_path, now=self.clock)

        self.assertEqual(7, SCHEMA_VERSION)
        self.assertEqual(7, reopened.schema_version)
        self.assertEqual(source["id"], reopened.get_job(source["id"])["id"])
        with closing(sqlite3.connect(self.db_path)) as connection:
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table' "
                    "AND name LIKE 'decision_%'"
                )
            }
            migrations = connection.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            ).fetchall()
        self.assertEqual(
            {
                "decision_cases",
                "decision_agent_turns",
                "decision_messages",
                "decision_evidence_assets",
                "decision_evidence_candidates",
                "decision_evidence_receipts",
                "decision_events",
                "decision_scenarios",
                "decision_scenario_evidence",
                "decision_scenario_confirmations",
                "decision_scenario_confirmation_items",
                "decision_scenario_jobs",
                "decision_scenario_confirmation_idempotency",
            },
            tables,
        )
        self.assertEqual([(1,), (2,), (3,), (4,), (5,), (6,), (7,)], migrations)

    def test_case_round_trip_update_cas_and_original_question_immutability(self) -> None:
        created = self._case()
        self.clock.advance(seconds=1)
        updated = self.store.update_decision_case(
            created["id"],
            expected_revision=1,
            operator_name="Case Editor",
            title="Updated title",
            question="What changed?",
            decision_owner="Decision Owner",
        )

        self.assertEqual(2, updated["revision"])
        self.assertEqual(created["original_question"], updated["original_question"])
        self.assertEqual("What changed?", updated["question"])
        reopened = AgentStore(self.db_path, now=self.clock)
        self.assertEqual(updated, reopened.get_decision_case(created["id"]))
        with self.assertRaises(StoreConflict):
            self.store.update_decision_case(
                created["id"],
                expected_revision=1,
                operator_name="Stale Editor",
                title="Lost update",
            )

        with closing(sqlite3.connect(self.db_path)) as connection:
            with self.assertRaisesRegex(sqlite3.IntegrityError, "revision"):
                connection.execute(
                    "UPDATE decision_cases SET title = 'raw edit' WHERE case_id = ?",
                    (created["id"],),
                )
            with self.assertRaisesRegex(sqlite3.IntegrityError, "identity"):
                connection.execute(
                    "UPDATE decision_cases SET original_question = 'changed', "
                    "revision = revision + 1 WHERE case_id = ?",
                    (created["id"],),
                )

        events = self.store.list_decision_events(created["id"])
        self.assertEqual(
            ["decision_case_created", "decision_case_updated"],
            [event["event_type"] for event in events],
        )

    def test_source_basis_lock_is_one_way_and_retains_the_annual_source(self) -> None:
        source = self._completed_annual()
        other_source = self._completed_annual("annual-autonomy-other")
        case = self._case()
        locked = self.store.lock_decision_case(
            case["id"],
            expected_revision=case["revision"],
            source_annual_job_id=source["id"],
            source_snapshot_sha256="a" * 64,
            analysis_basis="solartac_site",
            operator_name="Alex Operator",
        )

        self.assertEqual(source["id"], locked["source_annual_job_id"])
        self.assertEqual(
            locked,
            self.store.lock_decision_case(
                case["id"],
                expected_revision=case["revision"],
                source_annual_job_id=source["id"],
                source_snapshot_sha256="a" * 64,
                analysis_basis="solartac_site",
                operator_name="Alex Operator",
            ),
        )
        with self.assertRaises(InvalidStateTransition):
            self.store.lock_decision_case(
                case["id"],
                expected_revision=locked["revision"],
                source_annual_job_id=other_source["id"],
                source_snapshot_sha256="b" * 64,
                analysis_basis="solartac_site",
                operator_name="Alex Operator",
            )
        with self.assertRaisesRegex(InvalidStateTransition, "decision case"):
            self.store.delete_job(source["id"])

        with closing(sqlite3.connect(self.db_path)) as connection:
            with self.assertRaisesRegex(sqlite3.IntegrityError, "lock is immutable"):
                connection.execute(
                    "UPDATE decision_cases SET source_snapshot_sha256 = ?, "
                    "revision = revision + 1 WHERE case_id = ?",
                    ("c" * 64, case["id"]),
                )
            with self.assertRaisesRegex(sqlite3.IntegrityError, "payload is retained"):
                connection.execute(
                    "UPDATE jobs SET result_json = '{}' WHERE job_id = ?",
                    (source["id"],),
                )

    def test_case_transition_map_and_archive_read_only_guard(self) -> None:
        case = self._case()
        with self.assertRaises(InvalidStateTransition):
            self.store.transition_decision_case(
                case["id"],
                expected_revision=1,
                status="running",
                operator_name="Alex Operator",
            )
        blocked = self.store.transition_decision_case(
            case["id"],
            expected_revision=1,
            status="blocked",
            operator_name="Alex Operator",
            reason="No eligible Annual source",
        )
        ready = self.store.transition_decision_case(
            case["id"],
            expected_revision=blocked["revision"],
            status="ready_to_run",
            operator_name="Alex Operator",
        )
        running = self.store.transition_decision_case(
            case["id"],
            expected_revision=ready["revision"],
            status="running",
            operator_name="Alex Operator",
        )
        results = self.store.transition_decision_case(
            case["id"],
            expected_revision=running["revision"],
            status="results_ready",
            operator_name="Alex Operator",
        )
        decision = self.store.transition_decision_case(
            case["id"],
            expected_revision=results["revision"],
            status="decision_ready",
            operator_name="Alex Operator",
        )
        signed = self.store.transition_decision_case(
            case["id"],
            expected_revision=decision["revision"],
            status="signed",
            operator_name="Alex Operator",
        )
        archived = self.store.archive_decision_case(
            case["id"],
            expected_revision=signed["revision"],
            operator_name="Alex Operator",
        )

        self.assertEqual("archived", archived["status"])
        self.assertIsNotNone(archived["archived_at"])
        self.assertEqual([], self.store.list_decision_cases())
        self.assertEqual(
            [archived], self.store.list_decision_cases(include_archived=True)
        )
        with self.assertRaises(InvalidStateTransition):
            self.store.create_decision_turn(
                case["id"],
                client_message_id="after-archive",
                user_message="Can this still run?",
                operator_name="Alex Operator",
            )
        with closing(sqlite3.connect(self.db_path)) as connection:
            with self.assertRaisesRegex(sqlite3.IntegrityError, "archived, not deleted"):
                connection.execute(
                    "DELETE FROM decision_cases WHERE case_id = ?", (case["id"],)
                )
            with self.assertRaisesRegex(sqlite3.IntegrityError, "archived.*read-only"):
                connection.execute(
                    "UPDATE decision_cases SET title = 'changed', "
                    "revision = revision + 1 WHERE case_id = ?",
                    (case["id"],),
                )

    def test_concurrent_idempotent_turn_creation_never_duplicates_user_message(self) -> None:
        case = self._case()

        def create_turn(_index: int) -> str:
            local = AgentStore(self.db_path, now=self.clock)
            turn = local.create_decision_turn(
                case["id"],
                client_message_id="browser-message-1",
                user_message="Why is the Annual source blocked?",
                operator_name="Alex Operator",
            )
            return str(turn["id"])

        with ThreadPoolExecutor(max_workers=8) as executor:
            turn_ids = list(executor.map(create_turn, range(16)))

        self.assertEqual(1, len(set(turn_ids)))
        messages = self.store.list_decision_messages(case["id"])
        self.assertEqual(1, len(messages))
        self.assertEqual("user", messages[0]["role"])
        events = self.store.list_decision_events(case["id"])
        self.assertEqual(1, sum(e["event_type"] == "decision_turn_created" for e in events))
        with self.assertRaises(StoreConflict):
            self.store.create_decision_turn(
                case["id"],
                client_message_id="browser-message-1",
                user_message="A different message",
                operator_name="Alex Operator",
            )

    def test_turn_claim_complete_idempotency_and_reconnect_cursor(self) -> None:
        case = self._case()
        turn = self.store.create_decision_turn(
            case["id"],
            client_message_id="browser-message-2",
            user_message="What is calibration lineage?",
            operator_name="Alex Operator",
        )
        claimed = self.store.claim_decision_turn(
            turn["id"], worker_id="decision-worker", trace_id="trace-1"
        )
        self.assertEqual(
            claimed,
            self.store.claim_decision_turn(
                turn["id"], worker_id="decision-worker", trace_id="trace-1"
            ),
        )
        with self.assertRaises(InvalidStateTransition):
            self.store.claim_decision_turn(turn["id"], worker_id="other-worker")
        cursor = self.store.list_decision_events(case["id"])[-1]["event_sequence"]

        completed = self.store.complete_decision_turn(
            turn["id"],
            worker_id="decision-worker",
            claim_token=claimed["claim_token"],
            assistant_message="It is the reviewed calibration origin.",
            structured_output={
                "answer": "It is the reviewed calibration origin.",
                "basis": [{"label": "model_result"}],
                "limits": [],
                "next_action": None,
            },
            citations=[{"source_id": "annual-1"}],
            tool_outcomes=[{"tool": "read_readiness", "status": "ok"}],
            trace_id="trace-1",
        )
        repeated = self.store.complete_decision_turn(
            turn["id"],
            worker_id="decision-worker",
            claim_token=claimed["claim_token"],
            assistant_message="It is the reviewed calibration origin.",
            structured_output={
                "answer": "It is the reviewed calibration origin.",
                "basis": [{"label": "model_result"}],
                "limits": [],
                "next_action": None,
            },
            citations=[{"source_id": "annual-1"}],
            tool_outcomes=[{"tool": "read_readiness", "status": "ok"}],
            trace_id="trace-1",
        )

        self.assertEqual(completed, repeated)
        self.assertEqual("completed", completed["state"])
        self.assertEqual(2, len(self.store.list_decision_messages(case["id"])))
        replay = self.store.list_decision_events(
            case["id"], after_event_sequence=cursor, turn_id=turn["id"]
        )
        self.assertEqual(["decision_turn_completed"], [e["event_type"] for e in replay])
        self.assertEqual(
            "It is the reviewed calibration origin.",
            replay[0]["payload"]["message"]["content"],
        )
        all_sequences = [
            event["event_sequence"]
            for event in self.store.list_decision_events(case["id"])
        ]
        self.assertEqual(sorted(set(all_sequences)), all_sequences)

    def test_turn_failure_is_fenced_terminal_and_adds_assistant_message(self) -> None:
        case = self._case()
        turn = self.store.create_decision_turn(
            case["id"],
            client_message_id="browser-message-3",
            user_message="Why can\u2019t we execute?",
            operator_name="Alex Operator",
        )
        claimed = self.store.claim_decision_turn(turn["id"], worker_id="worker")
        with self.assertRaises(LeaseOwnershipLost):
            self.store.fail_decision_turn(
                turn["id"],
                worker_id="worker",
                claim_token="wrong-token",
                assistant_message="The Decision Agent is unavailable.",
                error_code="agent_unavailable",
                error_detail="The configured model is unavailable.",
            )
        failed = self.store.fail_decision_turn(
            turn["id"],
            worker_id="worker",
            claim_token=claimed["claim_token"],
            assistant_message="The Decision Agent is unavailable.",
            error_code="agent_unavailable",
            error_detail="The configured model is unavailable.",
        )

        self.assertEqual("failed", failed["state"])
        self.assertEqual("error", failed["assistant_message"]["status"])
        self.assertEqual("agent_unavailable", failed["assistant_message"]["error_code"])
        with self.assertRaises(InvalidStateTransition):
            self.store.complete_decision_turn(
                turn["id"],
                worker_id="worker",
                claim_token=claimed["claim_token"],
                assistant_message="Late response",
                structured_output=None,
            )
        with closing(sqlite3.connect(self.db_path)) as connection:
            with self.assertRaisesRegex(sqlite3.IntegrityError, "terminal"):
                connection.execute(
                    "UPDATE decision_agent_turns SET error_detail = 'changed' "
                    "WHERE turn_id = ?",
                    (turn["id"],),
                )

    def test_stale_claim_recovery_is_atomic_replayable_and_restart_safe(self) -> None:
        case = self._case()
        stale_turns = []
        for index in range(2):
            turn = self.store.create_decision_turn(
                case["id"],
                client_message_id=f"stale-{index}",
                user_message=f"Question {index}?",
                operator_name="Alex Operator",
            )
            stale_turns.append(
                self.store.claim_decision_turn(
                    turn["id"],
                    worker_id=f"worker-{index}",
                    trace_id=f"trace-stale-{index}",
                )
            )
        self.clock.advance(seconds=5)
        cutoff = self.clock.value
        self.clock.advance(seconds=1)
        fresh_turn = self.store.create_decision_turn(
            case["id"],
            client_message_id="fresh-claim",
            user_message="Still running?",
            operator_name="Alex Operator",
        )
        fresh_claim = self.store.claim_decision_turn(
            fresh_turn["id"], worker_id="fresh-worker", trace_id="trace-fresh"
        )

        reopened = AgentStore(self.db_path, now=self.clock)
        self.assertEqual(
            2,
            reopened.mark_stale_claimed_decision_turns_failed(before=cutoff),
        )
        self.assertEqual(
            0,
            reopened.mark_stale_claimed_decision_turns_failed(before=cutoff),
        )
        for stale in stale_turns:
            recovered = reopened.get_decision_turn(stale["id"])
            self.assertEqual("failed", recovered["state"])
            self.assertEqual("error", recovered["assistant_message"]["status"])
            self.assertEqual(
                "agent_interrupted", recovered["assistant_message"]["error_code"]
            )
            events = reopened.list_decision_events(
                case["id"], turn_id=stale["id"]
            )
            self.assertEqual("decision_turn_failed", events[-1]["event_type"])
            self.assertEqual(
                "stale_claim_after_process_restart",
                events[-1]["payload"]["recovery_reason"],
            )
        self.assertEqual(
            "claimed", reopened.get_decision_turn(fresh_claim["id"])["state"]
        )

    def test_claim_recovery_can_be_fenced_to_one_worker(self) -> None:
        case = self._case()
        claimed_by_worker_a = []
        for index in range(2):
            turn = self.store.create_decision_turn(
                case["id"],
                client_message_id=f"worker-a-{index}",
                user_message=f"Worker A question {index}?",
                operator_name="Alex Operator",
            )
            claimed_by_worker_a.append(
                self.store.claim_decision_turn(
                    turn["id"],
                    worker_id="decision-agent:worker-a",
                    trace_id=f"trace-worker-a-{index}",
                )
            )
        other_turn = self.store.create_decision_turn(
            case["id"],
            client_message_id="worker-b",
            user_message="Worker B question?",
            operator_name="Alex Operator",
        )
        claimed_by_worker_b = self.store.claim_decision_turn(
            other_turn["id"],
            worker_id="decision-agent:worker-b",
            trace_id="trace-worker-b",
        )
        self.clock.advance(seconds=1)

        recovered = self.store.mark_stale_claimed_decision_turns_failed(
            before=self.clock.value + timedelta(seconds=1),
            worker_id="decision-agent:worker-a",
            recovery_reason="worker_shutdown",
        )

        self.assertEqual(2, recovered)
        for claimed in claimed_by_worker_a:
            current = self.store.get_decision_turn(claimed["id"])
            self.assertEqual("failed", current["state"])
            events = self.store.list_decision_events(
                case["id"], turn_id=claimed["id"]
            )
            self.assertEqual(
                "worker_shutdown", events[-1]["payload"]["recovery_reason"]
            )
        self.assertEqual(
            "claimed",
            self.store.get_decision_turn(claimed_by_worker_b["id"])["state"],
        )
        self.assertEqual(
            0,
            self.store.mark_stale_claimed_decision_turns_failed(
                before=self.clock.value + timedelta(seconds=1),
                worker_id="decision-agent:worker-a",
                recovery_reason="worker_shutdown",
            ),
        )

    def test_active_turn_must_finish_before_case_archive(self) -> None:
        case = self._case()
        self.store.create_decision_turn(
            case["id"],
            client_message_id="archive-guard",
            user_message="Can this case be archived?",
            operator_name="Alex Operator",
        )
        current = self.store.get_decision_case(case["id"])
        with self.assertRaises(InvalidStateTransition):
            self.store.archive_decision_case(
                case["id"],
                expected_revision=current["revision"],
                operator_name="Alex Operator",
            )
        with closing(sqlite3.connect(self.db_path)) as connection:
            with self.assertRaisesRegex(sqlite3.IntegrityError, "must finish"):
                connection.execute(
                    "UPDATE decision_cases SET status = 'archived', "
                    "archived_at = '2026-08-29T12:00:00.000000+00:00', "
                    "revision = revision + 1 WHERE case_id = ?",
                    (case["id"],),
                )

    def test_messages_and_events_are_append_only_at_the_database_boundary(self) -> None:
        case = self._case()
        turn = self.store.create_decision_turn(
            case["id"],
            client_message_id="browser-message-4",
            user_message="What is this?",
            operator_name="Alex Operator",
        )
        message_id = turn["user_message"]["id"]
        event_id = self.store.list_decision_events(case["id"])[0]["id"]
        with closing(sqlite3.connect(self.db_path)) as connection:
            for sql, identifier in (
                (
                    "UPDATE decision_messages SET content_text = 'changed' "
                    "WHERE message_id = ?",
                    message_id,
                ),
                ("DELETE FROM decision_messages WHERE message_id = ?", message_id),
                ("UPDATE decision_events SET event_type = 'changed' WHERE event_id = ?", event_id),
                ("DELETE FROM decision_events WHERE event_id = ?", event_id),
            ):
                with self.assertRaises(sqlite3.IntegrityError):
                    connection.execute(sql, (identifier,))

    def test_evidence_candidates_receipts_and_tombstone_guards(self) -> None:
        case = self._case()
        asset = self.store.create_decision_evidence_asset(
            case["id"], **self._asset_kwargs(evidence_class="engineering_judgment")
        )
        candidate = asset["candidates"][0]
        self.assertEqual("pending", candidate["review_state"])
        self.assertTrue(
            self.store.decision_evidence_storage_is_referenced(asset["storage_key"])
        )
        with self.assertRaisesRegex(ValueError, "rationale"):
            self.store.record_decision_evidence_review(
                candidate["id"],
                decision="accepted",
                operator_name="Evidence Reviewer",
            )
        receipt = self.store.record_decision_evidence_review(
            candidate["id"],
            decision="accepted",
            operator_name="Evidence Reviewer",
            rationale="Used provisionally pending a primary quote.",
        )

        self.assertEqual("server_managed_content_v1", receipt["preservation_mode"])
        encoded = json.dumps(
            receipt["receipt"],
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        self.assertEqual(hashlib.sha256(encoded).hexdigest(), receipt["receipt_sha256"])
        reviewed = self.store.get_decision_evidence_asset(asset["id"])
        self.assertEqual("accepted", reviewed["candidates"][0]["review_state"])
        with self.assertRaises(StoreConflict):
            self.store.record_decision_evidence_review(
                candidate["id"],
                decision="rejected",
                operator_name="Evidence Reviewer",
            )
        with self.assertRaises(InvalidStateTransition):
            self.store.tombstone_decision_evidence_asset(
                asset["id"],
                operator_name="Evidence Reviewer",
                reason="Attempted cleanup",
            )

        with closing(sqlite3.connect(self.db_path)) as connection:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "UPDATE decision_evidence_candidates SET confidence = 0.1 "
                    "WHERE evidence_candidate_id = ?",
                    (candidate["id"],),
                )
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "UPDATE decision_evidence_receipts SET rationale = 'changed' "
                    "WHERE evidence_receipt_id = ?",
                    (receipt["id"],),
                )
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "DELETE FROM decision_evidence_receipts "
                    "WHERE evidence_receipt_id = ?",
                    (receipt["id"],),
                )

    def test_rejected_evidence_can_be_tombstoned_and_storage_reference_is_precise(self) -> None:
        case = self._case()
        first = self.store.create_decision_evidence_asset(
            case["id"], **self._asset_kwargs(suffix="b")
        )
        self.store.record_decision_evidence_review(
            first["candidates"][0]["id"],
            decision="rejected",
            operator_name="Evidence Reviewer",
        )
        removed = self.store.tombstone_decision_evidence_asset(
            first["id"],
            operator_name="Evidence Reviewer",
            reason="Wrong project revision",
        )

        self.assertIsNotNone(removed["removed_at"])
        self.assertFalse(
            self.store.decision_evidence_storage_is_referenced(
                first["storage_key"], exclude_evidence_asset_id=first["id"]
            )
        )
        self.assertEqual([], self.store.list_decision_evidence_assets(case["id"]))
        self.assertEqual(
            [removed],
            self.store.list_decision_evidence_assets(
                case["id"], include_removed=True
            ),
        )
        with closing(sqlite3.connect(self.db_path)) as connection:
            with self.assertRaisesRegex(sqlite3.IntegrityError, "tombstoned"):
                connection.execute(
                    "DELETE FROM decision_evidence_assets "
                    "WHERE evidence_asset_id = ?",
                    (first["id"],),
                )

    def test_evidence_limits_are_transactional_including_concurrent_uploads(self) -> None:
        case = self._case()
        with self.assertRaises(EvidenceLimitExceeded):
            self.store.create_decision_evidence_asset(
                case["id"],
                max_file_bytes=99,
                **self._asset_kwargs(byte_count=100),
            )
        first = self.store.create_decision_evidence_asset(
            case["id"],
            max_files_per_case=2,
            max_case_bytes=150,
            **self._asset_kwargs(suffix="c", byte_count=100),
        )
        with self.assertRaises(EvidenceLimitExceeded):
            self.store.create_decision_evidence_asset(
                case["id"],
                max_files_per_case=2,
                max_case_bytes=150,
                **self._asset_kwargs(suffix="d", byte_count=51),
            )
        self.assertEqual(
            [first], self.store.list_decision_evidence_assets(case["id"])
        )

        other_case = self._case(title="Concurrent evidence")

        def upload(suffix: str) -> str:
            local = AgentStore(self.db_path, now=self.clock)
            asset = local.create_decision_evidence_asset(
                other_case["id"],
                max_files_per_case=1,
                **self._asset_kwargs(suffix=suffix),
            )
            return str(asset["id"])

        outcomes: list[str] = []
        failures: list[Exception] = []
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(upload, suffix) for suffix in ("e", "f")]
            for future in futures:
                try:
                    outcomes.append(future.result())
                except Exception as exc:  # explicit assertion below
                    failures.append(exc)
        self.assertEqual(1, len(outcomes))
        self.assertEqual(1, len(failures))
        self.assertIsInstance(failures[0], EvidenceLimitExceeded)
        self.assertEqual(
            1, len(self.store.list_decision_evidence_assets(other_case["id"]))
        )

    def test_evidence_limits_are_enforced_against_raw_sql(self) -> None:
        def insert_raw_asset(
            connection: sqlite3.Connection,
            *,
            case_id: str,
            suffix: str,
            byte_count: int,
        ) -> None:
            digest = suffix * 64
            connection.execute(
                """
                INSERT INTO decision_evidence_assets (
                    evidence_asset_id, case_id, evidence_class,
                    original_filename, display_filename, declared_media_type,
                    detected_media_type, canonical_extension, sha256,
                    byte_count, storage_key, extraction_status,
                    extraction_metadata_json, source_metadata_json,
                    uploaded_by, uploaded_at
                ) VALUES (
                    ?, ?, 'project_actual', ?, ?, 'application/pdf',
                    'application/pdf', '.pdf', ?, ?, ?, 'complete', '{}', '{}',
                    'Raw SQL test', '2026-08-29T12:00:00.000000+00:00'
                )
                """,
                (
                    f"evi_raw_{case_id}_{suffix}",
                    case_id,
                    f"raw-{suffix}.pdf",
                    f"raw-{suffix}.pdf",
                    digest,
                    byte_count,
                    f"sha256/{digest[:2]}/{digest}.pdf",
                ),
            )

        file_case = self._case(title="Raw file quota")
        with closing(sqlite3.connect(self.db_path)) as connection:
            with self.assertRaisesRegex(sqlite3.IntegrityError, "file limit"):
                insert_raw_asset(
                    connection,
                    case_id=file_case["id"],
                    suffix="1",
                    byte_count=DECISION_EVIDENCE_MAX_FILE_BYTES + 1,
                )

        count_case = self._case(title="Raw count quota")
        with closing(sqlite3.connect(self.db_path)) as connection:
            for index in range(DECISION_EVIDENCE_MAX_FILES_PER_CASE):
                insert_raw_asset(
                    connection,
                    case_id=count_case["id"],
                    suffix=hex(index)[2:],
                    byte_count=1,
                )
            with self.assertRaisesRegex(sqlite3.IntegrityError, "count limit"):
                insert_raw_asset(
                    connection,
                    case_id=count_case["id"],
                    suffix="f",
                    byte_count=1,
                )

        bytes_case = self._case(title="Raw case byte quota")
        with closing(sqlite3.connect(self.db_path)) as connection:
            for index in range(5):
                insert_raw_asset(
                    connection,
                    case_id=bytes_case["id"],
                    suffix=str(index + 2),
                    byte_count=DECISION_EVIDENCE_MAX_FILE_BYTES,
                )
            self.assertEqual(
                DECISION_EVIDENCE_MAX_CASE_BYTES,
                5 * DECISION_EVIDENCE_MAX_FILE_BYTES,
            )
            with self.assertRaisesRegex(sqlite3.IntegrityError, "case byte limit"):
                insert_raw_asset(
                    connection,
                    case_id=bytes_case["id"],
                    suffix="8",
                    byte_count=1,
                )

    def test_claim_identity_is_immutable_at_the_database_boundary(self) -> None:
        case = self._case()
        turn = self.store.create_decision_turn(
            case["id"],
            client_message_id="immutable-claim",
            user_message="Why is this blocked?",
            operator_name="Alex Operator",
        )
        claimed = self.store.claim_decision_turn(
            turn["id"], worker_id="decision-worker", trace_id="trace-immutable"
        )
        with closing(sqlite3.connect(self.db_path)) as connection:
            with self.assertRaisesRegex(sqlite3.IntegrityError, "claim identity"):
                connection.execute(
                    "UPDATE decision_agent_turns SET claim_token = ? WHERE turn_id = ?",
                    ("changed-token", claimed["id"]),
                )
            with self.assertRaisesRegex(sqlite3.IntegrityError, "trace identity"):
                connection.execute(
                    "UPDATE decision_agent_turns SET trace_id = ? WHERE turn_id = ?",
                    ("changed-trace", claimed["id"]),
                )

    def test_evidence_registration_rolls_back_all_candidates_on_invalid_input(self) -> None:
        case = self._case()
        kwargs = self._asset_kwargs(suffix="9")
        kwargs["candidates"] = [
            {
                "field_name": "valid",
                "value": 1,
                "confidence": 0.5,
                "source_location": {"row": 1},
            },
            {
                "field_name": "invalid",
                "value": float("nan"),
                "confidence": 0.5,
                "source_location": {"row": 2},
            },
        ]
        with self.assertRaises(ValueError):
            self.store.create_decision_evidence_asset(case["id"], **kwargs)
        self.assertEqual([], self.store.list_decision_evidence_assets(case["id"]))

    def test_bounded_message_and_event_reads_validate_case_and_cursor(self) -> None:
        case = self._case()
        for index in range(3):
            self.store.create_decision_turn(
                case["id"],
                client_message_id=f"message-{index}",
                user_message=f"Question {index}?",
                operator_name="Alex Operator",
            )
        messages = self.store.list_decision_messages(case["id"], limit=2)
        self.assertEqual([2, 3], [item["message_sequence"] for item in messages])
        older = self.store.list_decision_messages(
            case["id"], limit=2, before_message_sequence=3
        )
        self.assertEqual([1, 2], [item["message_sequence"] for item in older])
        with self.assertRaises(ValueError):
            self.store.list_decision_events(case["id"], after_event_sequence=-1)
        with self.assertRaises(RecordNotFound):
            self.store.list_decision_events("case_missing")
        with self.assertRaises(RecordNotFound):
            self.store.list_decision_events(
                case["id"], turn_id="dturn_missing"
            )


if __name__ == "__main__":
    unittest.main()
