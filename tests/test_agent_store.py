from __future__ import annotations

import sqlite3
import tempfile
import threading
import unittest
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sbepv.store import (
    AgentStore,
    InvalidStateTransition,
    LeaseOwnershipLost,
    QueueCapacityExceeded,
    RecordNotFound,
    SAVED_RESULTS_LIMIT,
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
        self.assertEqual([(1,), (2,), (3,), (4,), (5,)], migrations)

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
        provenance = {
            "calibration_profile": {
                "schema_version": 1,
                "seasonal_factors": {"summer": {"solaredge": 1.1}},
            }
        }
        first = self.store.confirm_proposal(
            proposal["id"],
            job_id="candidate-1",
            confirmation_metadata={"actor": "auto_policy"},
            source_path="baseline.csv",
            source_hash="abc123",
            provenance=provenance,
        )
        second = self.store.confirm_proposal(
            proposal["id"],
            job_id="ignored-job",
            provenance={"calibration_profile": {"schema_version": 999}},
        )

        self.assertEqual("candidate-1", first["id"])
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(proposal["effective_request"], first["request"])
        self.assertEqual("baseline-1", first["baseline_id"])
        self.assertEqual("abc123", first["source_hash"])
        self.assertEqual(provenance, first["provenance"])
        self.assertEqual(provenance, second["provenance"])
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
            confirmed = local_store.confirm_proposal(
                proposal["id"],
                job_id=f"candidate-{index}",
                provenance={"confirmation_marker": index},
            )
            self.assertEqual(
                int(confirmed["id"].rsplit("-", 1)[1]),
                confirmed["provenance"]["confirmation_marker"],
            )
            return confirmed["id"]

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
        profile = {
            "calibration_profile": {
                "schema_version": 1,
                "seasonal_factors": {"summer": {"solaredge": 1.1}},
            }
        }
        job = self.store.create_job(
            job_id="restart-job",
            kind="candidate",
            mode="validation",
            request={},
            provenance=profile,
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
        self.assertEqual(profile, retried["provenance"])
        self.assertEqual(job["id"], self.store.claim_next_queued_job()["id"])

    def test_interrupted_job_uses_interruption_as_terminal_time(self) -> None:
        job = self.store.create_job(
            job_id="elapsed-interrupted",
            kind="manual",
            mode="validation",
            request={},
        )
        running = self.store.claim_next_queued_job()
        self.assertEqual(job["id"], running["id"])
        started_at = datetime.fromisoformat(running["started_at"])

        self.clock.advance(minutes=7)
        self.assertEqual(1, self.store.mark_stale_running_jobs_interrupted())
        interrupted = self.store.get_job(job["id"])

        self.assertEqual("interrupted", interrupted["state"])
        self.assertEqual(interrupted["interrupted_at"], interrupted["completed_at"])
        self.assertEqual(
            timedelta(minutes=7),
            datetime.fromisoformat(interrupted["completed_at"]) - started_at,
        )

        self.clock.advance(hours=3)
        reopened = AgentStore(self.db_path, now=self.clock)
        restored = reopened.get_job(job["id"])
        self.assertEqual(interrupted["completed_at"], restored["completed_at"])

        # Existing databases may contain interrupted rows written before
        # ``completed_at`` was populated. Their decoded terminal time must still
        # stop at ``interrupted_at``.
        with closing(sqlite3.connect(self.db_path)) as connection:
            connection.execute(
                "UPDATE jobs SET completed_at = NULL WHERE job_id = ?", (job["id"],)
            )
            connection.commit()
        legacy = AgentStore(self.db_path, now=self.clock).get_job(job["id"])
        self.assertEqual(interrupted["interrupted_at"], legacy["completed_at"])

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

    def test_worker_heartbeat_protects_live_job_until_lease_expires(self) -> None:
        self.store.create_job(
            job_id="leased", kind="manual", mode="validation", request={}
        )
        claimed = self.store.claim_next_queued_job(worker_id="worker-a")
        self.assertEqual("worker-a", claimed["worker_id"])
        lease_token = claimed["lease_token"]
        self.assertTrue(lease_token)

        self.clock.advance(minutes=5)
        self.assertFalse(
            self.store.heartbeat_job(
                "leased", worker_id="worker-b", lease_token=lease_token
            )
        )
        self.assertTrue(
            self.store.heartbeat_job(
                "leased", worker_id="worker-a", lease_token=lease_token
            )
        )
        cutoff = self.clock.value - timedelta(minutes=1)
        self.assertEqual(
            0, self.store.mark_stale_running_jobs_interrupted(before=cutoff)
        )

        self.clock.advance(minutes=2)
        cutoff = self.clock.value - timedelta(minutes=1)
        self.assertEqual(
            1, self.store.mark_stale_running_jobs_interrupted(before=cutoff)
        )
        self.assertEqual("interrupted", self.store.get_job("leased")["state"])

    def test_reclaimed_job_rejects_writes_from_expired_lease(self) -> None:
        self.store.create_job(
            job_id="reclaimed", kind="manual", mode="validation", request={}
        )
        first = self.store.claim_next_queued_job(worker_id="worker-a")
        first_token = first["lease_token"]

        self.clock.advance(minutes=2)
        cutoff = self.clock.value - timedelta(minutes=1)
        self.assertEqual(
            1, self.store.mark_stale_running_jobs_interrupted(before=cutoff)
        )
        self.store.retry_job("reclaimed")
        second = self.store.claim_next_queued_job(worker_id="worker-a")
        second_token = second["lease_token"]
        self.assertNotEqual(first_token, second_token)

        self.assertFalse(
            self.store.heartbeat_job(
                "reclaimed", worker_id="worker-a", lease_token=first_token
            )
        )
        with self.assertRaises(LeaseOwnershipLost):
            self.store.update_job(
                "reclaimed",
                expected_worker_id="worker-a",
                expected_lease_token=first_token,
                progress=99,
                stage="Stale worker write",
            )
        with self.assertRaises(LeaseOwnershipLost):
            self.store.is_cancel_requested(
                "reclaimed",
                expected_worker_id="worker-a",
                expected_lease_token=first_token,
            )

        current = self.store.get_job("reclaimed")
        self.assertEqual("running", current["state"])
        self.assertEqual(0, current["progress"])
        self.assertEqual(second_token, current["lease_token"])

    def test_owned_running_job_requires_lease_for_completion(self) -> None:
        self.store.create_job(
            job_id="owned", kind="manual", mode="validation", request={}
        )
        claimed = self.store.claim_next_queued_job(worker_id="worker-a")

        with self.assertRaises(LeaseOwnershipLost):
            self.store.update_job("owned", state="done")
        with self.assertRaises(LeaseOwnershipLost):
            self.store.update_job(
                "owned",
                expected_worker_id="worker-a",
                expected_lease_token="wrong-token",
                state="done",
            )

        completed = self.store.update_job(
            "owned",
            expected_worker_id="worker-a",
            expected_lease_token=claimed["lease_token"],
            state="done",
        )
        self.assertEqual("done", completed["state"])
        self.assertIsNone(completed["worker_id"])
        self.assertIsNone(completed["lease_token"])
        self.assertIsNone(completed["heartbeat_at"])

    def test_active_queue_capacity_is_checked_transactionally(self) -> None:
        self.store.create_job(
            job_id="capacity-1",
            kind="manual",
            mode="validation",
            request={},
            max_active_jobs=2,
        )
        self.store.create_job(
            job_id="capacity-2",
            kind="manual",
            mode="validation",
            request={},
            max_active_jobs=2,
        )

        with self.assertRaises(QueueCapacityExceeded):
            self.store.create_job(
                job_id="capacity-3",
                kind="manual",
                mode="validation",
                request={},
                max_active_jobs=2,
            )
        self.assertIsNone(self.store.get_job("capacity-3"))

        retryable = self.store.create_job(
            job_id="capacity-retry",
            kind="manual",
            mode="validation",
            request={},
        )
        self.store.cancel_job(retryable["id"])
        with self.assertRaises(QueueCapacityExceeded):
            self.store.retry_job(retryable["id"], max_active_jobs=2)
        self.assertEqual(
            "cancelled", self.store.get_job(retryable["id"])["state"]
        )

    def test_batch_confirmation_never_partially_enqueues_at_capacity(self) -> None:
        proposals = [
            self.proposal(
                proposal_id=f"batch-proposal-{index}",
                effective_request={"iam_a_r": index / 10},
            )
            for index in range(1, 4)
        ]
        active = self.store.create_job(
            job_id="batch-capacity-active",
            kind="manual",
            mode="validation",
            request={},
        )
        confirmations = [
            {
                "proposal_id": proposal["id"],
                "job_id": f"batch-job-{index}",
            }
            for index, proposal in enumerate(proposals, start=1)
        ]

        with self.assertRaises(QueueCapacityExceeded):
            self.store.confirm_proposals_batch(
                confirmations, max_active_jobs=3
            )

        self.assertEqual(
            [active["id"]],
            [job["id"] for job in self.store.list_jobs()],
        )
        self.assertTrue(
            all(
                self.store.get_proposal(proposal["id"])["state"] == "pending"
                for proposal in proposals
            )
        )

        self.store.cancel_job(active["id"])
        jobs = self.store.confirm_proposals_batch(
            confirmations, max_active_jobs=3
        )
        self.assertEqual(
            ["batch-job-1", "batch-job-2", "batch-job-3"],
            [job["id"] for job in jobs],
        )
        self.assertTrue(
            all(
                self.store.get_proposal(proposal["id"])["state"] == "confirmed"
                for proposal in proposals
            )
        )
        self.assertEqual(
            [job["id"] for job in jobs],
            [
                job["id"]
                for job in self.store.confirm_proposals_batch(
                    confirmations, max_active_jobs=3
                )
            ],
        )

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

    def test_delete_removes_terminal_unpromoted_scenario_and_detaches_proposal(self) -> None:
        proposal = self.proposal(proposal_id="delete-proposal")
        job = self.store.confirm_proposal(
            proposal["id"], job_id="candidate-delete", job_kind="candidate"
        )
        self.store.claim_next_queued_job()
        self.store.update_job(job["id"], state="done", result={"ok": True})

        deleted = self.store.delete_job(job["id"])

        self.assertEqual(job["id"], deleted["id"])
        self.assertIsNone(self.store.get_job(job["id"]))
        detached = self.store.get_proposal(proposal["id"])
        self.assertEqual("dismissed", detached["state"])
        self.assertIsNone(detached["confirmed_job_id"])

    def test_delete_rejects_active_or_promoted_scenarios(self) -> None:
        active = self.store.create_job(
            job_id="candidate-active",
            kind="candidate",
            mode="validation",
            baseline_id="baseline-1",
            request={},
        )
        with self.assertRaises(InvalidStateTransition):
            self.store.delete_job(active["id"])
        self.store.cancel_job(active["id"])

        promoted = self.store.create_job(
            job_id="candidate-promoted",
            kind="candidate",
            mode="annual",
            baseline_id="baseline-1",
            request={},
        )
        self.store.claim_next_queued_job()
        self.store.update_job(promoted["id"], state="done")
        self.store.promote_job(promoted["id"])
        with self.assertRaises(InvalidStateTransition):
            self.store.delete_job(promoted["id"])

    def test_delete_removes_unpromoted_baseline_run(self) -> None:
        baseline = self.store.create_job(
            job_id="baseline-delete", kind="baseline", mode="validation", request={}
        )
        self.store.claim_next_queued_job()
        self.store.update_job(baseline["id"], state="done")

        deleted = self.store.delete_job(baseline["id"])

        self.assertEqual(baseline["id"], deleted["id"])
        self.assertIsNone(self.store.get_job(baseline["id"]))

    def test_delete_removes_promoted_baseline_and_cleans_baseline_history(self) -> None:
        baseline = self.store.create_job(
            job_id="promoted-baseline-delete",
            kind="baseline",
            mode="validation",
            request={},
        )
        self.store.claim_next_queued_job()
        self.store.update_job(baseline["id"], state="done")
        self.store.promote_job(baseline["id"])

        self.store.delete_job(baseline["id"])

        self.assertIsNone(self.store.get_job(baseline["id"]))
        self.assertIsNone(self.store.get_current_baseline("validation"))
        self.assertEqual([], self.store.list_promotions(mode="validation"))

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
        self.assertEqual([baseline["id"]], [j["id"] for j in snapshot["recent_jobs"]])

    def test_snapshot_caps_terminal_history_without_counting_active_jobs(self) -> None:
        long_running = self.store.create_job(
            job_id="terminal-latest",
            kind="manual",
            mode="validation",
            request={"marker": "created-first"},
        )
        claimed = self.store.claim_next_queued_job()
        self.assertEqual(long_running["id"], claimed["id"])

        cancelled_ids = []
        for index in range(11):
            self.clock.advance(minutes=1)
            cancelled = self.store.create_job(
                job_id=f"terminal-{index:02d}",
                kind="manual",
                mode="validation",
                request={"marker": index},
            )
            cancelled_ids.append(cancelled["id"])
            self.store.cancel_job(cancelled["id"])

        # This job was created first but terminated last. Terminal history must
        # therefore order by its terminal timestamp, not by creation time.
        self.clock.advance(minutes=1)
        self.store.update_job(long_running["id"], state="done", result={"ok": True})

        active = self.store.create_job(
            job_id="active-job",
            kind="manual",
            mode="validation",
            request={},
        )
        queued = self.store.create_job(
            job_id="queued-job",
            kind="manual",
            mode="validation",
            request={},
        )
        self.assertEqual(active["id"], self.store.claim_next_queued_job()["id"])

        snapshot = self.store.snapshot_state(mode="validation")

        expected_history = [long_running["id"], *reversed(cancelled_ids[2:])]
        self.assertEqual(10, len(snapshot["recent_jobs"]))
        self.assertEqual(
            expected_history,
            [job["id"] for job in snapshot["recent_jobs"]],
        )
        self.assertEqual(active["id"], snapshot["active_job"]["id"])
        self.assertEqual([queued["id"]], [job["id"] for job in snapshot["queued_jobs"]])
        self.assertTrue(
            all(
                job["state"] in {"done", "error", "cancelled", "interrupted"}
                for job in snapshot["recent_jobs"]
            )
        )
        self.assertEqual(14, len(self.store.list_jobs()))

    def test_terminal_history_and_results_survive_store_reopen(self) -> None:
        completed = self.complete_job(job_id="durable-completed")
        self.clock.advance(minutes=1)
        cancelled = self.store.create_job(
            job_id="durable-cancelled",
            kind="manual",
            mode="annual",
            request={"mode": "annual"},
        )
        self.store.cancel_job(cancelled["id"])

        reopened = AgentStore(self.db_path, now=self.clock)
        restored = reopened.get_job(completed["id"])
        snapshot = reopened.snapshot_state()

        self.assertEqual(completed["request"], restored["request"])
        self.assertEqual(completed["result"], restored["result"])
        self.assertEqual(completed["provenance"], restored["provenance"])
        self.assertEqual(completed["artifacts"], restored["artifacts"])
        self.assertEqual(
            [cancelled["id"], completed["id"]],
            [job["id"] for job in snapshot["recent_jobs"]],
        )

    def test_saved_results_require_a_completed_job_with_a_result(self) -> None:
        queued = self.store.create_job(
            job_id="save-queued",
            kind="manual",
            mode="validation",
            request={},
        )
        with self.assertRaises(InvalidStateTransition):
            self.store.save_result(queued["id"])
        self.store.cancel_job(queued["id"])

        no_result = self.store.create_job(
            job_id="save-no-result",
            kind="manual",
            mode="validation",
            request={},
        )
        self.store.claim_next_queued_job()
        self.store.update_job(no_result["id"], state="done")
        with self.assertRaises(InvalidStateTransition):
            self.store.save_result(no_result["id"])
        with self.assertRaises(RecordNotFound):
            self.store.save_result("missing-job")

        completed = self.complete_job(job_id="save-completed")
        saved = self.store.save_result(completed["id"], name="  First   result  ")
        self.clock.advance(minutes=5)
        repeated = self.store.save_result(completed["id"], name="Ignored rename")

        self.assertEqual("First result", saved["name"])
        self.assertEqual(saved, repeated)
        self.assertEqual(1, len(self.store.list_saved_results()))

        annual = self.complete_job(job_id="save-default-name", mode="annual")
        default_named = self.store.save_result(annual["id"])
        self.assertEqual(
            "Annual simulation - 2026-07-20", default_named["name"]
        )

    def test_saved_results_are_bounded_and_list_newest_first(self) -> None:
        saved_ids = []
        for index in range(SAVED_RESULTS_LIMIT):
            completed = self.complete_job(job_id=f"saved-{index:02d}")
            self.store.save_result(completed["id"])
            saved_ids.append(completed["id"])
            self.clock.advance(minutes=1)

        overflow = self.complete_job(job_id="saved-overflow")
        with self.assertRaises(StoreConflict):
            self.store.save_result(overflow["id"])

        self.assertEqual(
            list(reversed(saved_ids)),
            [item["job_id"] for item in self.store.list_saved_results()],
        )

    def test_saved_result_rename_remove_and_job_delete_protection(self) -> None:
        completed = self.complete_job(job_id="saved-protected")
        saved = self.store.save_result(completed["id"])
        self.clock.advance(minutes=1)

        renamed = self.store.rename_saved_result(
            completed["id"], "  Annual   reference  "
        )
        self.assertEqual("Annual reference", renamed["name"])
        self.assertEqual(saved["saved_at"], renamed["saved_at"])
        self.assertNotEqual(saved["updated_at"], renamed["updated_at"])
        with self.assertRaises(InvalidStateTransition):
            self.store.delete_job(completed["id"])

        removed = self.store.remove_saved_result(completed["id"])
        self.assertEqual(completed["id"], removed["job_id"])
        self.assertEqual(completed["id"], self.store.get_job(completed["id"])["id"])
        self.assertEqual(completed["id"], self.store.delete_job(completed["id"])["id"])
        self.assertEqual([], self.store.list_saved_results())

    def test_saved_result_survives_history_eviction_and_store_reopen(self) -> None:
        completed = self.complete_job(job_id="saved-durable")
        self.store.save_result(completed["id"], name="Durable result")

        for index in range(11):
            self.clock.advance(minutes=1)
            newer = self.complete_job(job_id=f"newer-{index:02d}")
            self.assertEqual("done", newer["state"])

        self.assertNotIn(
            completed["id"],
            [job["id"] for job in self.store.snapshot_state()["recent_jobs"]],
        )
        reopened = AgentStore(self.db_path, now=self.clock)
        saved_results = reopened.list_saved_results()
        self.assertEqual([completed["id"]], [item["job_id"] for item in saved_results])
        self.assertEqual(completed["result"], saved_results[0]["job"]["result"])


if __name__ == "__main__":
    unittest.main()
