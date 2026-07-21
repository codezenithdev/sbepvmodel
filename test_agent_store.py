from __future__ import annotations

import sqlite3
import tempfile
import threading
import unittest
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agent_store import (
    AgentStore,
    InvalidStateTransition,
    RecordNotFound,
    SCHEMA_VERSION,
    SchemaVersionError,
    StoreConflict,
)


class MutableClock:
    def __init__(self) -> None:
        self.value = datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc)
        self._lock = threading.Lock()

    def __call__(self) -> datetime:
        with self._lock:
            return self.value

    def advance(self, **kwargs: int) -> None:
        with self._lock:
            self.value += timedelta(**kwargs)


class AgentStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        handle = tempfile.NamedTemporaryFile(
            prefix="agent-store-test-",
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

    def proposal(self, **overrides):
        values = {
            "proposal_id": "proposal-1",
            "mode": "validation",
            "baseline_id": "baseline-1",
            "comparison_kind": "same_input",
            "effective_request": {
                "from_date": "2026-06-20",
                "iam_model": "martin_ruiz",
                "iam_a_r": 0.8,
            },
            "changes": [
                {
                    "field": "iam_a_r",
                    "label": "Martin–Ruiz a_r",
                    "from": 0.16,
                    "to": 0.8,
                }
            ],
            "confirmation_required": False,
            "confirmation_reason": "same source data",
        }
        values.update(overrides)
        return self.store.create_proposal(**values)

    def complete_job(self, *, job_id: str, mode: str = "validation"):
        job = self.store.create_job(
            job_id=job_id,
            kind="manual",
            mode=mode,
            request={"mode": mode, "marker": job_id},
        )
        claimed = self.store.claim_next_queued_job()
        self.assertEqual(job["id"], claimed["id"])
        return self.store.update_job(
            job_id,
            state="done",
            stage="Done",
            result={"energy_kwh": 12.5},
            provenance={"model_version": "test"},
            artifacts={"excel": f"/{job_id}.xlsx"},
        )

    def test_schema_is_versioned_and_state_survives_reopen(self) -> None:
        self.assertEqual(SCHEMA_VERSION, self.store.schema_version)
        created = self.proposal()

        reopened = AgentStore(self.db_path, now=self.clock)
        loaded = reopened.get_proposal(created["id"])

        self.assertEqual(created["effective_request"], loaded["effective_request"])
        self.assertEqual(created["changes"], loaded["changes"])
        with closing(sqlite3.connect(self.db_path)) as connection:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            migrations = connection.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            ).fetchall()
        self.assertEqual(SCHEMA_VERSION, version)
        self.assertEqual([(1,)], migrations)

    def test_newer_schema_is_rejected(self) -> None:
        other_path = self.db_path.with_name(f"{self.db_path.stem}-future.sqlite3")
        self.addCleanup(self._remove_database_files, other_path)
        with closing(sqlite3.connect(other_path)) as connection:
            connection.execute("PRAGMA user_version = 999")
        with self.assertRaises(SchemaVersionError):
            AgentStore(other_path)

    def test_proposal_expires_after_24_hours_and_cannot_be_confirmed(self) -> None:
        proposal = self.proposal()
        expected_expiry = self.clock.value + timedelta(hours=24)
        self.assertEqual(expected_expiry, datetime.fromisoformat(proposal["expires_at"]))

        self.clock.advance(hours=24, seconds=1)
        loaded = self.store.get_proposal(proposal["id"])

        self.assertEqual("expired", loaded["state"])
        self.assertIsNotNone(loaded["expired_at"])
        with self.assertRaises(InvalidStateTransition):
            self.store.confirm_proposal(proposal["id"])

    def test_replacement_is_atomic_and_payloads_are_immutable(self) -> None:
        original = self.proposal()
        replacement = self.proposal(
            proposal_id="proposal-2",
            effective_request={"iam_model": "martin_ruiz", "iam_a_r": 0.7},
            changes=[
                {
                    "field": "iam_a_r",
                    "label": "Martin–Ruiz a_r",
                    "from": 0.16,
                    "to": 0.7,
                }
            ],
            supersedes_id=original["id"],
        )

        original = self.store.get_proposal(original["id"])
        self.assertEqual("superseded", original["state"])
        self.assertEqual(replacement["id"], original["superseded_by_id"])
        self.assertEqual(original["id"], replacement["supersedes_id"])

        with closing(sqlite3.connect(self.db_path)) as connection:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "UPDATE proposals SET changes_json = '{}' WHERE proposal_id = ?",
                    (replacement["id"],),
                )

    def test_confirm_is_idempotent_and_copies_immutable_request(self) -> None:
        proposal = self.proposal()
        first = self.store.confirm_proposal(
            proposal["id"],
            job_id="candidate-1",
            confirmation_metadata={"actor": "auto_policy"},
            source_path="baseline.csv",
            source_hash="abc123",
        )
        second = self.store.confirm_proposal(proposal["id"], job_id="ignored-job")

        self.assertEqual("candidate-1", first["id"])
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(proposal["effective_request"], first["request"])
        self.assertEqual("baseline-1", first["baseline_id"])
        self.assertEqual("abc123", first["source_hash"])
        self.assertEqual(1, len(self.store.list_jobs()))
        confirmed = self.store.get_proposal(proposal["id"])
        self.assertEqual("confirmed", confirmed["state"])
        self.assertEqual("auto_policy", confirmed["confirmation_metadata"]["actor"])

        with closing(sqlite3.connect(self.db_path)) as connection:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "UPDATE jobs SET request_json = '{}' WHERE job_id = ?",
                    (first["id"],),
                )

    def test_concurrent_confirmation_creates_exactly_one_job(self) -> None:
        proposal = self.proposal()
        barrier = threading.Barrier(8)

        def confirm(index: int) -> str:
            local_store = AgentStore(self.db_path, now=self.clock)
            barrier.wait(timeout=5)
            return local_store.confirm_proposal(
                proposal["id"], job_id=f"candidate-{index}"
            )["id"]

        with ThreadPoolExecutor(max_workers=8) as pool:
            ids = list(pool.map(confirm, range(8)))

        self.assertEqual(1, len(set(ids)))
        jobs = self.store.list_jobs(kind="candidate")
        self.assertEqual(1, len(jobs))
        self.assertEqual(proposal["id"], jobs[0]["proposal_id"])

    def test_duplicate_ids_and_unknown_records_are_reported(self) -> None:
        self.proposal()
        with self.assertRaises(StoreConflict):
            self.proposal()
        self.assertIsNone(self.store.get_job("missing"))
        with self.assertRaises(RecordNotFound):
            self.store.cancel_job("missing")

    def test_claim_serializes_work_and_uses_queue_order(self) -> None:
        first = self.store.create_job(
            job_id="a-job", kind="manual", mode="validation", request={"n": 1}
        )
        second = self.store.create_job(
            job_id="b-job", kind="manual", mode="annual", request={"n": 2}
        )

        claimed = self.store.claim_next_queued_job()
        self.assertEqual(first["id"], claimed["id"])
        self.assertEqual("running", claimed["state"])
        self.assertIsNone(self.store.claim_next_queued_job())

        self.store.update_job(first["id"], state="done", result={"ok": True})
        claimed = self.store.claim_next_queued_job()
        self.assertEqual(second["id"], claimed["id"])

    def test_concurrent_claims_never_create_two_running_jobs(self) -> None:
        for index in range(4):
            self.store.create_job(
                job_id=f"job-{index}",
                kind="manual",
                mode="validation",
                request={"index": index},
            )
        barrier = threading.Barrier(6)

        def claim() -> str | None:
            local_store = AgentStore(self.db_path, now=self.clock)
            barrier.wait(timeout=5)
            job = local_store.claim_next_queued_job()
            return job["id"] if job else None

        with ThreadPoolExecutor(max_workers=6) as pool:
            claimed_ids = list(pool.map(lambda _: claim(), range(6)))

        self.assertEqual(1, len([job_id for job_id in claimed_ids if job_id]))
        self.assertEqual(1, len(self.store.list_jobs(states=["running"])))
        self.assertEqual(3, len(self.store.list_jobs(states=["queued"])))

    def test_queued_cancel_is_final_and_running_cancel_is_cooperative(self) -> None:
        queued = self.store.create_job(
            job_id="queued", kind="manual", mode="validation", request={}
        )
        cancelled = self.store.cancel_job(queued["id"])
        self.assertEqual("cancelled", cancelled["state"])
        self.assertTrue(cancelled["cancel_requested"])
        self.assertIsNone(self.store.claim_next_queued_job())

        running = self.store.create_job(
            job_id="running", kind="manual", mode="validation", request={}
        )
        self.store.claim_next_queued_job()
        requested = self.store.cancel_job(running["id"])
        self.assertEqual("running", requested["state"])
        self.assertTrue(requested["cancel_requested"])
        self.assertTrue(self.store.is_cancel_requested(running["id"]))
        finished = self.store.update_job(running["id"], state="cancelled")
        self.assertEqual("cancelled", finished["state"])

    def test_restart_interrupts_running_job_and_retry_is_explicit(self) -> None:
        job = self.store.create_job(
            job_id="restart-job", kind="candidate", mode="validation", request={}
        )
        self.store.claim_next_queued_job()

        self.assertEqual(1, self.store.mark_stale_running_jobs_interrupted())
        interrupted = self.store.get_job(job["id"])
        self.assertEqual("interrupted", interrupted["state"])
        self.assertIsNone(self.store.claim_next_queued_job())

        retried = self.store.retry_job(job["id"])
        self.assertEqual("queued", retried["state"])
        self.assertFalse(retried["cancel_requested"])
        self.assertEqual(job["request"], retried["request"])
        self.assertEqual(job["id"], self.store.claim_next_queued_job()["id"])

    def test_stale_cutoff_leaves_recent_running_job_untouched(self) -> None:
        self.store.create_job(
            job_id="recent", kind="manual", mode="validation", request={}
        )
        self.store.claim_next_queued_job()
        cutoff = self.clock.value - timedelta(minutes=1)
        self.assertEqual(
            0, self.store.mark_stale_running_jobs_interrupted(before=cutoff)
        )
        self.assertEqual("running", self.store.get_job("recent")["state"])

    def test_job_update_persists_structured_outputs_and_validates_state(self) -> None:
        job = self.store.create_job(
            job_id="structured", kind="candidate", mode="validation", request={}
        )
        self.store.claim_next_queued_job()
        updated = self.store.update_job(
            job["id"],
            progress=75,
            stage="Comparing",
            comparison={"classification": "same_input", "delta_kwh": -2.5},
            provenance={"source_hash": "def456"},
            artifacts={"overlay": "/overlay.png"},
            source_path="cached.csv",
            source_hash="def456",
        )
        self.assertEqual(75, updated["progress"])
        self.assertEqual(-2.5, updated["comparison"]["delta_kwh"])
        self.assertEqual("/overlay.png", updated["artifacts"]["overlay"])
        self.assertEqual("cached.csv", updated["source_path"])
        with self.assertRaises(ValueError):
            self.store.update_job(job["id"], progress=float("nan"))
        self.store.update_job(job["id"], state="done")
        with self.assertRaises(InvalidStateTransition):
            self.store.update_job(job["id"], state="running")

    def test_promote_tracks_current_and_previous_baselines(self) -> None:
        first = self.complete_job(job_id="baseline-a")
        promoted_first = self.store.promote_job(first["id"])
        self.assertIsNone(promoted_first["previous_job_id"])

        second = self.complete_job(job_id="baseline-b")
        promoted_second = self.store.promote_job(second["id"])
        self.assertEqual(first["id"], promoted_second["previous_job_id"])

        current = self.store.get_current_baseline("validation")
        self.assertEqual(second["id"], current["job_id"])
        self.assertEqual(first["id"], current["previous_job_id"])
        self.assertEqual(2, len(self.store.list_promotions(mode="validation")))
        repeated = self.store.promote_job(second["id"])
        self.assertEqual(first["id"], repeated["previous_job_id"])
        self.assertEqual(2, len(self.store.list_promotions(mode="validation")))
        with self.assertRaises(InvalidStateTransition):
            queued = self.store.create_job(
                kind="manual", mode="annual", request={"mode": "annual"}
            )
            self.store.promote_job(queued["id"])

    def test_snapshot_contains_actionable_agent_state(self) -> None:
        baseline = self.complete_job(job_id="baseline")
        self.store.promote_job(baseline["id"])
        proposal = self.proposal(proposal_id="pending")
        queued = self.store.create_job(
            job_id="queued", kind="manual", mode="validation", request={}
        )

        snapshot = self.store.snapshot_state(mode="validation")

        self.assertEqual(baseline["id"], snapshot["current_baselines"]["validation"]["job_id"])
        self.assertEqual([proposal["id"]], [p["id"] for p in snapshot["pending_proposals"]])
        self.assertEqual([queued["id"]], [j["id"] for j in snapshot["queued_jobs"]])
        self.assertIsNone(snapshot["active_job"])
        self.assertGreaterEqual(len(snapshot["recent_jobs"]), 2)


if __name__ == "__main__":
    unittest.main()
