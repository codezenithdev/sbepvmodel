"""SQLite misses and failures must never revive a cached durable model job."""

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

from sbepv.agent import tools
from sbepv.api import baselines, config, job_store, serializers, state
from sbepv.api.schemas import ChatRequest
from sbepv.store import (
    AgentStore, AgentStoreError, LeaseOwnershipLost, QueueCapacityExceeded, RecordNotFound,
)


class JobCacheAuthorityTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="job-cache-authority-")
        self.addCleanup(temporary.cleanup)
        self.database = Path(temporary.name) / "jobs.sqlite3"
        self.store = AgentStore(self.database)
        store_patch = patch.object(state, "AGENT_STORE", self.store)
        cache_patch = patch.object(state, "JOBS", {})
        store_patch.start()
        cache_patch.start()
        self.addCleanup(store_patch.stop)
        self.addCleanup(cache_patch.stop)

    def create_job(self, job_id="durable-job", *, completed=False, mode="validation"):
        record = self.store.create_job(
            job_id=job_id, kind="manual", mode=mode, request={}
        )
        if completed:
            self.assertEqual(self.store.claim_next_queued_job()["id"], job_id)
            record = self.store.update_job(job_id, state="done", result={"stats": {}})
        return record

    def test_deletion_by_another_store_removes_mirror_without_resurrection(self):
        record = self.create_job(completed=True)
        job_store._cache_job_record(record)
        AgentStore(self.database).delete_job(record["id"])

        self.assertIsNone(job_store._get_job_record(record["id"]))
        self.assertNotIn(record["id"], state.JOBS)
        with self.assertRaises(RecordNotFound):
            job_store._update_job(record["id"], stage="Stale update")
        self.assertNotIn(record["id"], state.JOBS)

    def test_durable_only_lookup_discards_a_missing_mirror(self):
        record = self.create_job(completed=True)
        job_store._cache_job_record(record)
        self.store.delete_job(record["id"])
        self.assertIsNone(job_store._get_durable_model_job_record(record["id"]))
        self.assertNotIn(record["id"], state.JOBS)

    def test_database_errors_propagate_without_returning_cached_success(self):
        record = self.create_job(completed=True)
        job_store._cache_job_record(record)
        for error in (AgentStoreError("unavailable"), sqlite3.OperationalError("locked")):
            with self.subTest(error=type(error).__name__):
                with patch.object(self.store, "get_job", side_effect=error):
                    with self.assertRaises(type(error)):
                        job_store._get_job_record(record["id"])
                # An outage is not proof of deletion: a later read may recover.
                self.assertIn(record["id"], state.JOBS)
        self.assertEqual(job_store._get_job_record(record["id"]), record)

    def test_database_errors_do_not_mutate_cached_execution_state(self):
        record = self.create_job()
        cached = job_store._cache_job_record(record)
        before = dict(cached)
        with patch.object(self.store, "get_job", side_effect=AgentStoreError("unavailable")):
            with self.assertRaises(AgentStoreError):
                job_store._update_job(record["id"], state="done")
        self.assertEqual(cached, before)

    def test_missing_leased_job_never_falls_back_to_legacy_or_new_cache_row(self):
        for existing in (None, {"state": "running", "progress": 5}):
            with self.subTest(existing=existing):
                state.JOBS.clear()
                if existing is not None:
                    state.JOBS["missing"] = dict(existing)
                with self.assertRaises(LeaseOwnershipLost):
                    job_store._update_job(
                        "missing", worker_id="worker", lease_token="lease", progress=90
                    )
                self.assertEqual(state.JOBS.get("missing"), existing)

    def test_missing_mirrored_job_cannot_be_updated_without_a_lease(self):
        record = self.create_job(completed=True)
        job_store._cache_job_record(record)
        self.store.delete_job(record["id"])
        with self.assertRaises(RecordNotFound):
            job_store._update_job(record["id"], progress=90)
        self.assertNotIn(record["id"], state.JOBS)

    def test_deletion_between_lookup_and_update_is_reported_as_lost_lease(self):
        record = self.create_job()
        job_store._cache_job_record(record)
        with patch.object(self.store, "update_job", side_effect=RecordNotFound("removed")):
            with self.assertRaises(LeaseOwnershipLost):
                job_store._update_job(
                    record["id"], worker_id="worker", lease_token="lease", progress=90
                )
        self.assertNotIn(record["id"], state.JOBS)

    def test_partial_or_blank_lease_credentials_never_mutate_legacy_cache(self):
        state.JOBS["legacy"] = {"state": "running", "progress": 5}
        for credentials in (
            {"worker_id": "worker"},
            {"lease_token": "lease"},
            {"worker_id": "", "lease_token": "lease"},
        ):
            with self.subTest(credentials=credentials), self.assertRaises(ValueError):
                job_store._update_job("legacy", progress=90, **credentials)
        self.assertEqual(state.JOBS["legacy"]["progress"], 5)

    def test_existing_legacy_only_row_can_still_be_read_and_updated(self):
        state.JOBS["legacy"] = {"state": "running", "progress": 5}
        self.assertEqual(job_store._get_job_record("legacy")["progress"], 5)
        updated = job_store._update_job("legacy", progress=10)
        self.assertEqual(updated["progress"], 10)
        self.assertIsNone(self.store.get_job("legacy"))
        self.assertIsNone(job_store._get_durable_model_job_record("legacy"))
        self.assertIn("legacy", state.JOBS)

    def test_unknown_unleased_job_is_not_created_implicitly(self):
        with self.assertRaises(RecordNotFound):
            job_store._update_job("never-existed", progress=10)
        self.assertNotIn("never-existed", state.JOBS)

    def test_refresh_keeps_runtime_fields_object_identity_and_insertion_order(self):
        state.JOBS["legacy-older"] = {"state": "done"}
        record = self.create_job()
        cached = job_store._cache_job_record(record)
        cached.update(input_plots={"dni": "/outputs/dni.png"}, traceback="diagnostic")
        state.JOBS["legacy-newer"] = {"state": "done"}
        self.assertEqual(self.store.claim_next_queued_job()["id"], record["id"])
        self.store.update_job(record["id"], progress=20)
        job_store._get_job_record(record["id"])
        self.assertIs(state.JOBS[record["id"]], cached)
        self.assertEqual(list(state.JOBS), ["legacy-older", record["id"], "legacy-newer"])
        self.assertEqual(cached["progress"], 20)
        self.assertEqual(cached["input_plots"], {"dni": "/outputs/dni.png"})
        self.assertEqual(cached["traceback"], "diagnostic")
        self.assertNotIn("_durable_model_job", serializers._public_job({"id": record["id"], **cached}))

    def test_durable_artifact_plots_override_old_runtime_plot_cache(self):
        record = self.create_job()
        cached = job_store._cache_job_record(record)
        cached["input_plots"] = {"dni": "/outputs/old.png"}
        self.store.update_job(record["id"], artifacts={"input_plots": {"dni": "/outputs/new.png"}})
        job_store._get_job_record(record["id"])
        self.assertEqual(cached["input_plots"], {"dni": "/outputs/new.png"})

    def test_durable_completed_mirror_is_not_an_unpromoted_legacy_baseline(self):
        record = self.create_job(completed=True)
        job_store._cache_job_record(record)
        self.assertIsNone(baselines._selected_baseline("validation"))
        # The separate latest-completed lookup intentionally permits durable jobs.
        self.assertEqual(job_store._latest_completed_job_id("validation"), record["id"])
        self.store.delete_job(record["id"])
        self.assertIsNone(job_store._latest_completed_job_id("validation"))

    def test_stale_running_mirror_does_not_block_new_model_work(self):
        record = self.create_job()
        job_store._cache_job_record(record)
        AgentStore(self.database).cancel_job(record["id"])
        self.assertEqual(baselines._active_model_jobs(), [])
        state.JOBS["legacy-active"] = {"state": "running"}
        self.assertEqual([row["id"] for row in baselines._active_model_jobs()], ["legacy-active"])

    def test_old_active_baseline_is_visible_beyond_the_first_100_jobs(self):
        record = self.create_job("old-annual-baseline", mode="annual")
        job_store._cache_job_record(record)
        for index in range(100):
            job_store._cache_job_record(self.create_job(f"new-validation-{index}"))
        for queue_limit in (500, 25):
            with self.subTest(queue_limit=queue_limit), patch.object(
                config, "MAX_ACTIVE_MODEL_JOBS", queue_limit
            ):
                self.assertEqual(len(baselines._active_model_jobs()), 101)
                with self.assertRaises(HTTPException) as rejected:
                    tools._handle_scenario_tool(
                        ChatRequest(message="Run an Annual scenario", active_mode="annual"), {}
                    )
                self.assertEqual(rejected.exception.status_code, 409)
                self.assertIn("already queued or running", rejected.exception.detail)
        # Admission uses the database's complete count, independently of this view.
        with self.assertRaises(QueueCapacityExceeded):
            self.store.create_job(
                job_id="overflow", kind="manual", mode="validation", request={},
                max_active_jobs=101,
            )
        self.assertIsNone(self.store.get_job("overflow"))

    def test_promoted_baselines_keep_priority_over_newer_completed_runs(self):
        validation = self.create_job("validation-promoted", completed=True)
        annual = self.create_job("annual-promoted", completed=True, mode="annual")
        self.store.promote_job(validation["id"])
        self.store.promote_job(annual["id"])
        self.create_job("newer-unpromoted", completed=True)
        self.assertEqual(job_store._latest_completed_job_id(), validation["id"])
        self.assertEqual(job_store._latest_completed_job_id("validation"), validation["id"])
        self.assertEqual(job_store._latest_completed_job_id("annual"), annual["id"])
        self.assertEqual(baselines._selected_baseline("validation")["id"], validation["id"])

    def test_legacy_baseline_selection_keeps_insertion_order(self):
        state.JOBS["legacy-first"] = {"state": "done", "mode": "validation"}
        state.JOBS["legacy-second"] = {"state": "done", "mode": "validation"}
        record = self.create_job(completed=True)
        job_store._cache_job_record(record)
        self.assertEqual(baselines._selected_baseline("validation")["id"], "legacy-second")
        self.store.delete_job(record["id"])
        self.assertEqual(job_store._latest_completed_job_id("validation"), "legacy-second")

    def test_tea_cache_entries_never_enter_model_lookups_or_updates(self):
        for status in ("done", "running"):
            with self.subTest(status=status):
                state.JOBS["tea_isolated"] = {"state": status, "mode": "validation"}
                self.assertIsNone(job_store._get_job_record("tea_isolated"))
                self.assertIsNone(job_store._get_durable_model_job_record("tea_isolated"))
                self.assertIsNone(job_store._latest_completed_job_id("validation"))
                self.assertIsNone(baselines._selected_baseline("validation"))
                self.assertEqual(baselines._active_model_jobs(), [])
                with self.assertRaises(RecordNotFound):
                    job_store._update_job("tea_isolated", progress=90)
                self.assertNotIn("progress", state.JOBS["tea_isolated"])
