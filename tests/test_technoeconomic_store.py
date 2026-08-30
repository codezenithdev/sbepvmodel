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
    InvalidStateTransition,
    LeaseOwnershipLost,
    QueueCapacityExceeded,
    RecordNotFound,
    SCHEMA_VERSION,
    SchemaVersionError,
    StoreConflict,
)


class MutableClock:
    def __init__(self) -> None:
        self.value = datetime(2026, 8, 13, 12, 0, tzinfo=timezone.utc)
        self._lock = threading.Lock()

    def __call__(self) -> datetime:
        with self._lock:
            return self.value

    def advance(self, **kwargs: int) -> None:
        with self._lock:
            self.value += timedelta(**kwargs)


class TechnoeconomicStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        handle = tempfile.NamedTemporaryFile(
            prefix="technoeconomic-store-test-",
            suffix=".sqlite3",
            dir=Path(__file__).resolve().parent,
            delete=False,
        )
        handle.close()
        self.db_path = Path(handle.name)
        self.addCleanup(self._remove_database_files, self.db_path)
        self.clock = MutableClock()
        self.store = AgentStore(self.db_path, now=self.clock)
        self.source = self._completed_annual_source("annual-source")

    @staticmethod
    def _remove_database_files(path: Path) -> None:
        for candidate in (path, Path(f"{path}-wal"), Path(f"{path}-shm")):
            candidate.unlink(missing_ok=True)

    def _completed_annual_source(self, job_id: str) -> dict:
        created = self.store.create_job(
            job_id=job_id,
            kind="manual",
            mode="annual",
            request={"mode": "annual", "year": 2024},
            source_path=f"artifacts/{job_id}/midc.csv",
            source_hash="1" * 64,
            provenance={"calibration": {"job_id": "validation-source"}},
        )
        claimed = self.store.claim_next_queued_job()
        self.assertEqual(created["id"], claimed["id"])
        return self.store.update_job(
            job_id,
            state="done",
            result={"annual_energy_kwh": 1000.0},
            provenance={"calibration": {"job_id": "validation-source"}},
        )

    def _create_tea(self, *, job_id: str = "tea_example", **overrides) -> dict:
        values = {
            "job_id": job_id,
            "request": {"n": 1000, "seed": 42, "project_life_years": 20},
            "source_annual_job_id": self.source["id"],
            "source_artifact_storage_key": f"sha256/11/{'1' * 64}.csv",
            "source_artifact_sha256": "1" * 64,
            "source_artifact_bytes": 12345,
            "source_snapshot": {
                "schema_version": 1,
                "source_annual_job_id": self.source["id"],
                "midc_source_artifact": {
                    "owner_annual_job_id": self.source["id"],
                    "storage_key": f"sha256/11/{'1' * 64}.csv",
                    "sha256": "1" * 64,
                    "byte_count": 12345,
                },
                "energy_rows": [{"weather_year": 2024, "solectria_kwh": 1000}],
                "capacity_manifest": {"solectria_wdc": 100000},
            },
            "submission_provenance": {
                "schema_version": 1,
                "analysis_basis": "solartac",
                "evidence": [{"cost_id": "cost.capex", "class": "project_primary"}],
            },
        }
        values.update(overrides)
        if "atomic_source_check" not in values:
            def verified_snapshot_hash(
                _connection: sqlite3.Connection,
                snapshot=values["source_snapshot"],
            ) -> str:
                snapshot_text = json.dumps(
                    snapshot,
                    allow_nan=False,
                    ensure_ascii=True,
                    separators=(",", ":"),
                    sort_keys=True,
                )
                return hashlib.sha256(snapshot_text.encode("utf-8")).hexdigest()

            values["atomic_source_check"] = verified_snapshot_hash
        return self.store.create_technoeconomic_job(**values)

    def _claim_tea(self, job_id: str, *, worker_id: str = "tea-worker") -> dict:
        claimed = self.store.claim_next_queued_work(worker_id=worker_id)
        self.assertIsNotNone(claimed)
        self.assertEqual(job_id, claimed["id"])
        self.assertEqual("technoeconomic", claimed["workflow"])
        return claimed

    def _finish_tea(
        self, job_id: str, *, state: str = "done", worker_id: str = "tea-worker"
    ) -> dict:
        claimed = self._claim_tea(job_id, worker_id=worker_id)
        kwargs = {
            "expected_worker_id": worker_id,
            "expected_lease_token": claimed["lease_token"],
            "state": state,
            "stage": state.title(),
        }
        if state == "done":
            kwargs.update(
                result={"summary": {"baseline_lcoe_p50": 0.1}},
                result_provenance={"kernel_contract": "tea-calc-v1"},
                artifacts={"csv": {"storage_key": "tea/attempt/results.csv"}},
            )
        else:
            kwargs["error"] = "synthetic failure"
        return self.store.update_technoeconomic_job(job_id, **kwargs)

    def test_schema_v5_migration_preserves_existing_model_rows(self) -> None:
        with closing(sqlite3.connect(self.db_path)) as connection:
            for trigger in (
                "technoeconomic_job_inputs_are_immutable",
                "technoeconomic_job_terminal_payload_is_immutable",
                "technoeconomic_job_terminal_state_is_immutable",
                "technoeconomic_job_terminal_row_is_immutable",
            ):
                connection.execute(f"DROP TRIGGER {trigger}")
            connection.execute("DROP TABLE technoeconomic_jobs")
            connection.execute("DELETE FROM schema_migrations WHERE version = 5")
            connection.execute("PRAGMA user_version = 4")
            connection.commit()

        reopened = AgentStore(self.db_path, now=self.clock)

        self.assertEqual(8, SCHEMA_VERSION)
        self.assertEqual(8, reopened.schema_version)
        self.assertEqual(self.source["id"], reopened.get_job(self.source["id"])["id"])
        with closing(sqlite3.connect(self.db_path)) as connection:
            table = connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' "
                "AND name = 'technoeconomic_jobs'"
            ).fetchone()
            migrations = connection.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            ).fetchall()
        self.assertEqual(("technoeconomic_jobs",), table)
        self.assertEqual(
            [(1,), (2,), (3,), (4,), (5,), (6,), (7,), (8,)],
            migrations,
        )

    def test_v5_migration_fails_closed_on_legacy_reserved_namespace_collision(self) -> None:
        other_path = self.db_path.with_name(f"{self.db_path.stem}-collision.sqlite3")
        self.addCleanup(self._remove_database_files, other_path)
        legacy = AgentStore(other_path, now=self.clock)
        with closing(sqlite3.connect(other_path)) as connection:
            connection.execute(
                "DROP TRIGGER IF EXISTS model_job_tea_namespace_insert_guard"
            )
            for trigger in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'trigger' AND "
                "(tbl_name = 'technoeconomic_jobs' OR name LIKE '%tea_%' "
                "OR name = 'retained_annual_source_state_guard' "
                "OR name LIKE '%global_running_guard')"
            ).fetchall():
                connection.execute(f"DROP TRIGGER {trigger[0]}")
            connection.execute("DROP TABLE technoeconomic_jobs")
            connection.execute("DELETE FROM schema_migrations WHERE version = 5")
            connection.execute("PRAGMA user_version = 4")
            connection.execute(
                """
                INSERT INTO jobs (
                    job_id, state, kind, mode, request_json, progress, stage,
                    cancel_requested, created_at, queued_at, updated_at
                ) VALUES (
                    'tea_legacy', 'done', 'manual', 'annual', '{}', 100,
                    'Done', 0, '2026-08-13T12:00:00Z',
                    '2026-08-13T12:00:00Z', '2026-08-13T12:00:00Z'
                )
                """
            )
            connection.commit()
        del legacy

        with self.assertRaisesRegex(SchemaVersionError, "reserves"):
            AgentStore(other_path, now=self.clock)
        with closing(sqlite3.connect(other_path)) as connection:
            self.assertEqual(4, connection.execute("PRAGMA user_version").fetchone()[0])
            self.assertIsNone(
                connection.execute(
                    "SELECT name FROM sqlite_master WHERE name = 'technoeconomic_jobs'"
                ).fetchone()
            )

    def test_create_round_trips_canonical_payloads_and_computed_hashes(self) -> None:
        created = self._create_tea()
        reopened = AgentStore(self.db_path, now=self.clock)
        loaded = reopened.get_technoeconomic_job(created["id"])

        self.assertEqual("queued", loaded["state"])
        self.assertEqual(created["request"], loaded["request"])
        self.assertEqual(created["source_snapshot"], loaded["source_snapshot"])
        self.assertEqual(
            created["submission_provenance"], loaded["submission_provenance"]
        )
        snapshot_json = json.dumps(
            created["source_snapshot"], allow_nan=False, separators=(",", ":"), sort_keys=True
        )
        provenance_json = json.dumps(
            created["submission_provenance"],
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        self.assertEqual(
            hashlib.sha256(snapshot_json.encode()).hexdigest(),
            loaded["source_snapshot_sha256"],
        )
        self.assertEqual(
            hashlib.sha256(provenance_json.encode()).hexdigest(),
            loaded["submission_provenance_sha256"],
        )

    def test_inputs_are_database_immutable(self) -> None:
        job = self._create_tea()
        immutable_columns = {
            "tea_job_id": "tea_renamed",
            "request_json": "{}",
            "source_annual_job_id": "another-source",
            "source_artifact_storage_key": "different.csv",
            "source_artifact_sha256": "2" * 64,
            "source_artifact_bytes": 2,
            "source_snapshot_json": "{}",
            "source_snapshot_sha256": "3" * 64,
            "submission_provenance_json": "{}",
            "submission_provenance_sha256": "4" * 64,
            "retry_of_job_id": "tea_other",
        }
        with closing(sqlite3.connect(self.db_path)) as connection:
            for column, value in immutable_columns.items():
                with self.subTest(column=column), self.assertRaises(sqlite3.IntegrityError):
                    connection.execute(
                        f"UPDATE technoeconomic_jobs SET {column} = ? "
                        "WHERE tea_job_id = ?",
                        (value, job["id"]),
                    )

    def test_create_requires_reserved_id_valid_hash_and_completed_annual_source(self) -> None:
        with self.assertRaisesRegex(ValueError, "reserved"):
            self._create_tea(job_id="job_wrong")
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            self._create_tea(job_id="tea_bad_hash", source_artifact_sha256="ABC")
        with self.assertRaisesRegex(ValueError, "canonical content address"):
            self._create_tea(
                job_id="tea_escaping_artifact",
                source_artifact_storage_key="../outside.csv",
            )
        with self.assertRaisesRegex(ValueError, "canonical content address"):
            self._create_tea(
                job_id="tea_unrelated_artifact",
                source_artifact_storage_key=f"sha256/22/{'2' * 64}.csv",
            )
        with self.assertRaisesRegex(ValueError, "positive"):
            self._create_tea(job_id="tea_empty_artifact", source_artifact_bytes=0)
        for index, invalid_bytes in enumerate((True, 1.5, "12345")):
            with self.subTest(source_artifact_bytes=invalid_bytes), self.assertRaisesRegex(
                ValueError, "positive integer"
            ):
                self._create_tea(
                    job_id=f"tea_invalid_bytes_{index}",
                    source_artifact_bytes=invalid_bytes,
                )
        with self.assertRaises(RecordNotFound):
            self._create_tea(
                job_id="tea_missing_source",
                source_annual_job_id="missing",
                source_snapshot={
                    "source_annual_job_id": "missing",
                    "midc_source_artifact": {
                        "owner_annual_job_id": "missing",
                        "storage_key": f"sha256/11/{'1' * 64}.csv",
                        "sha256": "1" * 64,
                        "byte_count": 12345,
                    },
                },
            )

        validation = self.store.create_job(
            job_id="validation-source",
            kind="manual",
            mode="validation",
            request={"mode": "validation"},
        )
        with self.assertRaises(InvalidStateTransition):
            self._create_tea(
                job_id="tea_validation_source",
                source_annual_job_id=validation["id"],
                source_snapshot={
                    "source_annual_job_id": validation["id"],
                    "midc_source_artifact": {
                        "owner_annual_job_id": validation["id"],
                        "storage_key": f"sha256/11/{'1' * 64}.csv",
                        "sha256": "1" * 64,
                        "byte_count": 12345,
                    },
                },
            )

    def test_snapshot_identity_copies_must_match_top_level_columns(self) -> None:
        base_snapshot = self._create_tea(job_id="tea_identity_control")[
            "source_snapshot"
        ]
        self.store.cancel_technoeconomic_job("tea_identity_control")
        cases = {
            "source_id": {
                **base_snapshot,
                "source_annual_job_id": "different-annual",
            },
            "owner_id": {
                **base_snapshot,
                "midc_source_artifact": {
                    **base_snapshot["midc_source_artifact"],
                    "owner_annual_job_id": "different-annual",
                },
            },
            "storage_key": {
                **base_snapshot,
                "midc_source_artifact": {
                    **base_snapshot["midc_source_artifact"],
                    "storage_key": f"sha256/22/{'2' * 64}.csv",
                },
            },
            "sha256": {
                **base_snapshot,
                "midc_source_artifact": {
                    **base_snapshot["midc_source_artifact"],
                    "sha256": "2" * 64,
                },
            },
            "byte_count": {
                **base_snapshot,
                "midc_source_artifact": {
                    **base_snapshot["midc_source_artifact"],
                    "byte_count": 999,
                },
            },
        }
        for index, (field, snapshot) in enumerate(cases.items()):
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "match"):
                self._create_tea(
                    job_id=f"tea_identity_mismatch_{index}",
                    source_snapshot=snapshot,
                )
        with closing(sqlite3.connect(self.db_path)) as connection:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    """
                    INSERT INTO technoeconomic_jobs (
                        tea_job_id, state, request_json, source_annual_job_id,
                        source_artifact_storage_key, source_artifact_sha256,
                        source_artifact_bytes, source_snapshot_json,
                        source_snapshot_sha256, submission_provenance_json,
                        submission_provenance_sha256, progress, stage,
                        cancel_requested, created_at, queued_at, updated_at
                    )
                    SELECT
                        'tea_direct_identity_mismatch', 'queued', request_json,
                        source_annual_job_id, source_artifact_storage_key,
                        source_artifact_sha256, source_artifact_bytes,
                        replace(source_snapshot_json, '"byte_count":12345',
                                '"byte_count":999'),
                        source_snapshot_sha256, submission_provenance_json,
                        submission_provenance_sha256, 0, 'Queued', 0,
                        created_at, queued_at, updated_at
                      FROM technoeconomic_jobs WHERE tea_job_id = ?
                    """,
                    ("tea_identity_control",),
                )

    def test_canonical_payloads_reject_non_finite_numbers(self) -> None:
        with self.assertRaisesRegex(ValueError, "NaN/Infinity"):
            self._create_tea(job_id="tea_nan_request", request={"n": float("nan")})
        with self.assertRaisesRegex(ValueError, "NaN/Infinity"):
            self._create_tea(
                job_id="tea_nan_snapshot",
                source_snapshot={
                    "source_annual_job_id": self.source["id"],
                    "midc_source_artifact": {
                        "owner_annual_job_id": self.source["id"],
                        "storage_key": f"sha256/11/{'1' * 64}.csv",
                        "sha256": "1" * 64,
                        "byte_count": 12345,
                    },
                    "energy_kwh": float("inf"),
                },
            )
        with self.assertRaisesRegex(ValueError, "NaN/Infinity"):
            self._create_tea(
                job_id="tea_nan_provenance",
                submission_provenance={"cost": float("-inf")},
            )

    def test_model_jobs_reject_reserved_tea_prefix(self) -> None:
        with self.assertRaisesRegex(ValueError, "reserved"):
            self.store.create_job(
                job_id="tea_model_collision",
                kind="manual",
                mode="annual",
                request={"mode": "annual"},
            )
        with self.assertRaisesRegex(ValueError, "isolated"):
            self.store.create_job(
                job_id="disguised-tea",
                kind="  TechnoEconomic ",
                mode="annual",
                request={"mode": "annual"},
            )
        with self.assertRaisesRegex(ValueError, "baseline"):
            self.store.create_job(
                job_id="model-with-tea-baseline",
                kind="candidate",
                mode="annual",
                baseline_id="tea_forbidden",
                request={"mode": "annual"},
            )
        with self.assertRaisesRegex(ValueError, "baseline"):
            self.store.create_proposal(
                proposal_id="proposal-tea-baseline",
                mode="annual",
                effective_request={"mode": "annual"},
                changes=[],
                baseline_id="tea_forbidden",
                comparison_kind="same_input",
                confirmation_required=False,
            )

    def test_database_guards_reserved_model_and_proposal_references(self) -> None:
        model = self.store.create_job(
            job_id="unguarded-model",
            kind="candidate",
            mode="annual",
            baseline_id="normal-baseline",
            request={"mode": "annual"},
        )
        proposal = self.store.create_proposal(
            proposal_id="unguarded-proposal",
            mode="annual",
            effective_request={"mode": "annual"},
            changes=[],
            baseline_id="normal-baseline",
            comparison_kind="same_input",
            confirmation_required=False,
        )
        with closing(sqlite3.connect(self.db_path)) as connection:
            statements = (
                ("UPDATE jobs SET job_id = 'tea_direct' WHERE job_id = ?", model["id"]),
                (
                    "UPDATE jobs SET kind = ' TechnoEconomic ' WHERE job_id = ?",
                    model["id"],
                ),
                (
                    "UPDATE jobs SET baseline_id = 'tea_direct' WHERE job_id = ?",
                    model["id"],
                ),
                (
                    "UPDATE proposals SET baseline_id = 'tea_direct' "
                    "WHERE proposal_id = ?",
                    proposal["id"],
                ),
                (
                    "UPDATE proposals SET confirmed_job_id = 'tea_direct' "
                    "WHERE proposal_id = ?",
                    proposal["id"],
                ),
                (
                    "INSERT INTO current_baselines "
                    "(mode, job_id, previous_job_id, promoted_at) "
                    "VALUES ('annual', ?, NULL, '2026-08-13T12:00:00Z')",
                    "tea_direct",
                ),
                (
                    "INSERT INTO baseline_promotions "
                    "(mode, job_id, previous_job_id, promoted_at) "
                    "VALUES ('annual', ?, NULL, '2026-08-13T12:00:00Z')",
                    "tea_direct",
                ),
                (
                    "INSERT INTO saved_results (job_id, name, saved_at, updated_at) "
                    "VALUES (?, 'forbidden', '2026-08-13T12:00:00Z', "
                    "'2026-08-13T12:00:00Z')",
                    "tea_direct",
                ),
            )
            for sql, record_id in statements:
                with self.subTest(sql=sql), self.assertRaises(sqlite3.IntegrityError):
                    connection.execute(sql, (record_id,))

    def test_generic_running_transition_cannot_bypass_global_claimer(self) -> None:
        older = self._create_tea(job_id="tea_run_guard")
        self.clock.advance(seconds=1)
        newer = self.store.create_job(
            job_id="newer-model-run-guard",
            kind="manual",
            mode="annual",
            request={"mode": "annual"},
        )

        with self.assertRaises(InvalidStateTransition):
            self.store.update_technoeconomic_job(older["id"], state="running")
        with self.assertRaises(InvalidStateTransition):
            self.store.update_job(newer["id"], state="running")
        with closing(sqlite3.connect(self.db_path)) as connection:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "UPDATE technoeconomic_jobs SET state = 'running' "
                    "WHERE tea_job_id = ?",
                    (older["id"],),
                )
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "UPDATE jobs SET state = 'running' WHERE job_id = ?",
                    (newer["id"],),
                )

        with self.assertRaisesRegex(ValueError, "required"):
            self.store.claim_next_queued_work()

        claimed = self.store.claim_next_queued_work(worker_id="guard-worker")
        self.assertEqual(older["id"], claimed["id"])

    def test_referenced_annual_source_cannot_lose_completed_annual_state(self) -> None:
        self._create_tea(job_id="tea_source_state_guard")
        for field, value in (
            ("result", {"changed": True}),
            ("provenance", {"changed": True}),
            ("artifacts", {"changed": True}),
            ("source_path", "different.csv"),
            ("source_hash", "2" * 64),
        ):
            with self.subTest(field=field), self.assertRaises(InvalidStateTransition):
                self.store.update_job(self.source["id"], **{field: value})
        with closing(sqlite3.connect(self.db_path)) as connection:
            statements = (
                "UPDATE jobs SET state = 'error' WHERE job_id = ?",
                "UPDATE jobs SET mode = 'validation' WHERE job_id = ?",
                "UPDATE jobs SET kind = 'candidate' WHERE job_id = ?",
                "UPDATE jobs SET request_json = '{}' WHERE job_id = ?",
                "UPDATE jobs SET result_json = '{}' WHERE job_id = ?",
                "UPDATE jobs SET provenance_json = '{}' WHERE job_id = ?",
                "UPDATE jobs SET artifacts_json = '{}' WHERE job_id = ?",
                "UPDATE jobs SET source_path = 'different.csv' WHERE job_id = ?",
                f"UPDATE jobs SET source_hash = '{'2' * 64}' WHERE job_id = ?",
            )
            for sql in statements:
                with self.subTest(sql=sql), self.assertRaises(sqlite3.IntegrityError):
                    connection.execute(sql, (self.source["id"],))

    def test_tea_ids_are_absent_and_ineligible_in_every_model_only_path(self) -> None:
        tea = self._create_tea(job_id="tea_isolated")

        self.assertIsNone(self.store.get_job(tea["id"]))
        for operation in (
            lambda: self.store.promote_job(tea["id"]),
            lambda: self.store.save_result(tea["id"]),
            lambda: self.store.cancel_job(tea["id"]),
            lambda: self.store.retry_job(tea["id"]),
            lambda: self.store.delete_job(tea["id"]),
        ):
            with self.subTest(operation=operation), self.assertRaises(RecordNotFound):
                operation()

        self.assertNotIn(tea["id"], {job["id"] for job in self.store.list_jobs()})
        self.assertNotIn(tea["id"], json.dumps(self.store.snapshot_state()))
        self.assertNotIn(tea["id"], json.dumps(self.store.list_saved_results()))
        self.assertNotIn(tea["id"], json.dumps(self.store.list_promotions()))

    def test_atomic_source_check_rolls_back_stale_candidate(self) -> None:
        observed = []

        def stale(connection: sqlite3.Connection) -> str | None:
            observed.append(
                connection.execute(
                    "SELECT state FROM jobs WHERE job_id = ?", (self.source["id"],)
                ).fetchone()[0]
            )
            return None

        with self.assertRaisesRegex(StoreConflict, "changed"):
            self._create_tea(job_id="tea_stale", atomic_source_check=stale)

        self.assertEqual(["done"], observed)
        self.assertIsNone(self.store.get_technoeconomic_job("tea_stale"))

    def test_original_enqueue_requires_atomic_source_check(self) -> None:
        with self.assertRaisesRegex(ValueError, "atomic_source_check is required"):
            self._create_tea(job_id="tea_without_recheck", atomic_source_check=None)

        self.assertIsNone(self.store.get_technoeconomic_job("tea_without_recheck"))

    def test_list_filters_by_state_and_source(self) -> None:
        first = self._create_tea(job_id="tea_first")
        second = self._create_tea(job_id="tea_second")
        self.store.cancel_technoeconomic_job(first["id"])

        queued = self.store.list_technoeconomic_jobs(states=["queued"])
        by_source = self.store.list_technoeconomic_jobs(
            source_annual_job_id=self.source["id"]
        )

        self.assertEqual([second["id"]], [job["id"] for job in queued])
        self.assertEqual({first["id"], second["id"]}, {job["id"] for job in by_source})

    def test_global_capacity_counts_model_and_technoeconomic_jobs(self) -> None:
        self._create_tea(job_id="tea_capacity", max_active_jobs=1)
        with self.assertRaises(QueueCapacityExceeded):
            self.store.create_job(
                job_id="model-over-capacity",
                kind="manual",
                mode="annual",
                request={"mode": "annual"},
                max_active_jobs=1,
            )

        self.store.cancel_technoeconomic_job("tea_capacity")
        model = self.store.create_job(
            job_id="model-capacity",
            kind="manual",
            mode="annual",
            request={"mode": "annual"},
            max_active_jobs=1,
        )
        with self.assertRaises(QueueCapacityExceeded):
            self._create_tea(
                job_id="tea_over_capacity",
                max_active_jobs=1,
            )
        self.store.cancel_job(model["id"])

    def test_global_oldest_first_and_legacy_model_claim_does_not_leapfrog(self) -> None:
        tea = self._create_tea(job_id="tea_oldest")
        self.clock.advance(seconds=1)
        model = self.store.create_job(
            job_id="model-newer",
            kind="manual",
            mode="annual",
            request={"mode": "annual"},
        )

        self.assertIsNone(self.store.claim_next_queued_job(worker_id="model-worker"))
        claimed_tea = self.store.claim_next_queued_work(worker_id="tea-worker")
        self.assertEqual((tea["id"], "technoeconomic"), (claimed_tea["id"], claimed_tea["workflow"]))
        self.store.update_technoeconomic_job(
            tea["id"],
            expected_worker_id="tea-worker",
            expected_lease_token=claimed_tea["lease_token"],
            state="done",
            result={"ok": True},
            result_provenance={"schema_version": 1},
            artifacts={},
        )
        claimed_model = self.store.claim_next_queued_work(worker_id="model-worker")
        self.assertEqual((model["id"], "model"), (claimed_model["id"], claimed_model["workflow"]))

    def test_running_work_blocks_claims_in_the_other_workflow(self) -> None:
        tea = self._create_tea(job_id="tea_running")
        claimed = self._claim_tea(tea["id"])
        self.store.create_job(
            job_id="model-waiting",
            kind="manual",
            mode="annual",
            request={"mode": "annual"},
        )

        self.assertIsNone(self.store.claim_next_queued_work(worker_id="other-worker"))
        self.assertIsNone(self.store.claim_next_queued_job(worker_id="model-worker"))
        self.assertTrue(
            self.store.heartbeat_technoeconomic_job(
                tea["id"],
                worker_id="tea-worker",
                lease_token=claimed["lease_token"],
            )
        )

    def test_concurrent_global_claims_create_only_one_running_job(self) -> None:
        self._create_tea(job_id="tea_concurrent")
        barrier = threading.Barrier(6)

        def claim(index: int):
            local = AgentStore(self.db_path, now=self.clock)
            barrier.wait(timeout=5)
            return local.claim_next_queued_work(worker_id=f"worker-{index}")

        with ThreadPoolExecutor(max_workers=6) as executor:
            claimed = list(executor.map(claim, range(6)))

        winners = [record for record in claimed if record is not None]
        self.assertEqual(1, len(winners))
        self.assertEqual("technoeconomic", winners[0]["workflow"])

    def test_lease_fencing_cancellation_and_terminal_immutability(self) -> None:
        tea = self._create_tea(job_id="tea_leased")
        claimed = self._claim_tea(tea["id"], worker_id="worker-a")
        with self.assertRaises(LeaseOwnershipLost):
            self.store.update_technoeconomic_job(
                tea["id"],
                expected_worker_id="worker-b",
                expected_lease_token=claimed["lease_token"],
                progress=50,
            )
        cancellation = self.store.cancel_technoeconomic_job(tea["id"])
        self.assertTrue(cancellation["cancel_requested"])
        self.assertTrue(
            self.store.is_technoeconomic_cancel_requested(
                tea["id"],
                expected_worker_id="worker-a",
                expected_lease_token=claimed["lease_token"],
            )
        )
        terminal = self.store.update_technoeconomic_job(
            tea["id"],
            expected_worker_id="worker-a",
            expected_lease_token=claimed["lease_token"],
            state="cancelled",
            stage="Cancelled",
        )
        self.assertEqual("cancelled", terminal["state"])
        with self.assertRaises(InvalidStateTransition):
            self.store.update_technoeconomic_job(tea["id"], stage="Changed")
        with closing(sqlite3.connect(self.db_path)) as connection:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "UPDATE technoeconomic_jobs SET result_json = '{}' "
                    "WHERE tea_job_id = ?",
                    (tea["id"],),
                )

    def test_stale_interruption_and_retry_create_new_frozen_attempt(self) -> None:
        original = self._create_tea(job_id="tea_original")
        claimed = self._claim_tea(original["id"])
        self.clock.advance(minutes=10)
        cutoff = self.clock.value - timedelta(minutes=1)

        self.assertEqual(
            1,
            self.store.mark_stale_running_technoeconomic_jobs_interrupted(
                before=cutoff
            ),
        )
        interrupted = self.store.get_technoeconomic_job(original["id"])
        retried = self.store.retry_technoeconomic_job(
            original["id"], new_job_id="tea_retry"
        )

        self.assertEqual("interrupted", interrupted["state"])
        self.assertEqual("queued", retried["state"])
        self.assertEqual(original["id"], retried["retry_of_job_id"])
        for field in (
            "request",
            "source_annual_job_id",
            "source_artifact_storage_key",
            "source_artifact_sha256",
            "source_artifact_bytes",
            "source_snapshot",
            "source_snapshot_sha256",
            "submission_provenance",
            "submission_provenance_sha256",
        ):
            self.assertEqual(interrupted[field], retried[field], field)
        self.assertNotEqual(claimed["lease_token"], retried["lease_token"])
        self.assertEqual("interrupted", self.store.get_technoeconomic_job(original["id"])["state"])

    def test_retry_rejects_completed_or_active_jobs_and_obeys_capacity(self) -> None:
        queued = self._create_tea(job_id="tea_not_retryable")
        with self.assertRaises(InvalidStateTransition):
            self.store.retry_technoeconomic_job(queued["id"])
        self.store.cancel_technoeconomic_job(queued["id"])
        self.store.create_job(
            job_id="capacity-blocker",
            kind="manual",
            mode="annual",
            request={"mode": "annual"},
        )
        with self.assertRaises(QueueCapacityExceeded):
            self.store.retry_technoeconomic_job(
                queued["id"], max_active_jobs=1
            )

    def test_source_retention_and_terminal_delete_rules(self) -> None:
        tea = self._create_tea(job_id="tea_retains_source")
        with self.assertRaisesRegex(InvalidStateTransition, "retained"):
            self.store.delete_job(self.source["id"])
        with closing(sqlite3.connect(self.db_path)) as connection:
            connection.execute("PRAGMA foreign_keys = ON")
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "DELETE FROM jobs WHERE job_id = ?", (self.source["id"],)
                )
        with self.assertRaises(InvalidStateTransition):
            self.store.delete_technoeconomic_job(tea["id"])

        cancelled = self.store.cancel_technoeconomic_job(tea["id"])
        deleted = self.store.delete_technoeconomic_job(cancelled["id"])
        self.assertEqual(cancelled["id"], deleted["id"])
        self.assertIsNone(self.store.get_technoeconomic_job(cancelled["id"]))
        self.assertEqual(self.source["id"], self.store.delete_job(self.source["id"])["id"])

    def test_retry_lineage_prevents_deleting_earlier_attempt_first(self) -> None:
        original = self._create_tea(job_id="tea_lineage")
        self.store.cancel_technoeconomic_job(original["id"])
        retry = self.store.retry_technoeconomic_job(
            original["id"], new_job_id="tea_lineage_retry"
        )
        self.store.cancel_technoeconomic_job(retry["id"])

        with self.assertRaisesRegex(InvalidStateTransition, "later"):
            self.store.delete_technoeconomic_job(original["id"])
        self.store.delete_technoeconomic_job(retry["id"])
        self.store.delete_technoeconomic_job(original["id"])


if __name__ == "__main__":
    unittest.main()
