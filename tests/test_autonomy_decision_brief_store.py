from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import threading
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

from sbepv.store import (
    AgentStore,
    InvalidStateTransition,
    SCHEMA_VERSION,
    SchemaVersionError,
    StoreConflict,
)


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


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


class AutonomyDecisionBriefStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        handle = tempfile.NamedTemporaryFile(
            prefix="autonomy-decision-brief-store-test-",
            suffix=".sqlite3",
            dir=Path(__file__).resolve().parent,
            delete=False,
        )
        handle.close()
        self.db_path = Path(handle.name)
        self.addCleanup(self._remove_database_files, self.db_path)
        self.clock = MutableClock()
        self.store = AgentStore(self.db_path, now=self.clock)
        self.source = self._completed_annual_source("annual-decision-brief-source")
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
        self.source_snapshot_sha256 = _canonical_sha256(self.source_snapshot)
        self.case = self._locked_case("Decision Brief store contract")

    @staticmethod
    def _remove_database_files(path: Path) -> None:
        for candidate in (path, Path(f"{path}-wal"), Path(f"{path}-shm")):
            candidate.unlink(missing_ok=True)

    def _completed_annual_source(self, job_id: str) -> dict[str, Any]:
        created = self.store.create_job(
            job_id=job_id,
            kind="manual",
            mode="annual",
            request={"mode": "annual", "years": [2024]},
            source_path=f"artifacts/{job_id}/midc.csv",
            source_hash="1" * 64,
        )
        claimed = self.store.claim_next_queued_job()
        self.assertIsNotNone(claimed)
        assert claimed is not None
        self.assertEqual(created["id"], claimed["id"])
        return self.store.update_job(
            job_id,
            state="done",
            stage="Done",
            result={"mode": "annual", "stats": {}},
            provenance={"source": "decision-brief-store-test"},
        )

    def _locked_case(self, title: str) -> dict[str, Any]:
        case = self.store.create_decision_case(
            title=title,
            question="Which immutable scenario result should support the decision?",
            operator_name="Alex Operator",
        )
        return self.store.lock_decision_case(
            case["id"],
            expected_revision=case["revision"],
            source_annual_job_id=self.source["id"],
            source_snapshot_sha256=self.source_snapshot_sha256,
            analysis_basis="solartac_site",
            operator_name="Alex Operator",
        )

    def _refresh_case(self, case_id: str | None = None) -> dict[str, Any]:
        current = self.store.get_decision_case(case_id or self.case["id"])
        if current is None:
            raise AssertionError("test case disappeared")
        if case_id is None or case_id == self.case["id"]:
            self.case = current
        return current

    def _scenario_request(self) -> dict[str, Any]:
        return {
            "source_annual_job_id": self.source["id"],
            "basis": "solartac_site",
            "n": 1_000,
            "seed": 42,
            "assumptions": {
                "solaredge_initial_capex_usd": 130_000.0,
                "project_life_years": 20,
                "real_discount_rate": 0.05,
                "annual_degradation_rate": 0.005,
            },
        }

    def _confirmed_baseline(
        self,
        *,
        complete: bool,
        job_id: str = "tea_decision_brief_baseline",
    ) -> dict[str, Any]:
        request = self._scenario_request()
        current = self._refresh_case()
        scenario = self.store.create_decision_scenario(
            current["id"],
            expected_case_revision=current["revision"],
            label="Current baseline",
            kind="baseline",
            request=request,
            request_sha256=_canonical_sha256(request),
            changed_fields=[],
            comparison_classification="baseline",
            evidence_receipt_refs=[],
            operator_name="Scenario Editor",
            scenario_id="dsc_decision_brief_baseline",
            scenario_revision_id="dscr_decision_brief_baseline_r1",
        )
        current = self._refresh_case()
        validation = {
            "validation_version": "autonomy-scenario-validation-v1",
            "valid": True,
            "request_sha256": scenario["request_sha256"],
            "baseline_request_sha256": None,
            "kind": "baseline",
            "comparison_classification": "baseline",
            "changed_fields": [],
            "declared_changed_fields": [],
            "field_errors": [],
            "violated_rules": [],
            "closest_supported_alternatives": [],
        }
        scenario = self.store.record_decision_scenario_validation(
            scenario["scenario_revision_id"],
            expected_case_revision=current["revision"],
            expected_revision=scenario["revision"],
            request_sha256=scenario["request_sha256"],
            validation=validation,
            valid=True,
            operator_name="Scenario Validator",
        )
        current = self._refresh_case()
        current = self.store.transition_decision_case(
            current["id"],
            expected_revision=current["revision"],
            status="evidence_needed",
            operator_name="Scenario Validator",
            reason="Scenario evidence is under deterministic review.",
        )
        current = self.store.transition_decision_case(
            current["id"],
            expected_revision=current["revision"],
            status="ready_to_run",
            operator_name="Scenario Validator",
            reason="The selected immutable scenario revision is validated.",
        )
        item = {
            "scenario_revision_id": scenario["scenario_revision_id"],
            "expected_revision": scenario["revision"],
            "request_sha256": scenario["request_sha256"],
            "job_id": job_id,
            "request": scenario["request"],
            "source_annual_job_id": self.source["id"],
            "source_artifact_storage_key": f"sha256/11/{'1' * 64}.csv",
            "source_artifact_sha256": "1" * 64,
            "source_artifact_bytes": 12_345,
            "source_snapshot": self.source_snapshot,
            "submission_provenance": {
                "schema_version": 1,
                "analysis_basis": "solartac_site",
                "scenario_revision_id": scenario["scenario_revision_id"],
                "scenario_request_sha256": scenario["request_sha256"],
                "evidence_receipt_ids": [],
            },
        }
        review = {
            "schema_version": 1,
            "case_id": current["id"],
            "source_annual_job_id": self.source["id"],
            "source_snapshot_sha256": self.source_snapshot_sha256,
            "analysis_basis": "solartac_site",
            "queue_behavior": "global_leased_sequential_worker",
            "request_hashes": [scenario["request_sha256"]],
        }
        confirmed = self.store.confirm_decision_scenarios_batch(
            current["id"],
            [item],
            expected_case_revision=current["revision"],
            idempotency_key="confirm-decision-brief-baseline",
            operator_name="Alex Operator",
            rationale="Run the exact validated comparison set.",
            acknowledgement=(
                "I confirm the selected scenarios, source and basis lock, evidence "
                "status, realization count, seed, and exact request hashes shown here."
            ),
            confirmation_review=review,
            atomic_source_check=lambda _connection: self.source_snapshot_sha256,
        )
        self._refresh_case()

        if complete:
            claimed = self.store.claim_next_queued_work(
                worker_id="decision-brief-store-worker"
            )
            self.assertIsNotNone(claimed)
            assert claimed is not None
            self.assertEqual(job_id, claimed["id"])
            self.store.update_technoeconomic_job(
                job_id,
                expected_worker_id="decision-brief-store-worker",
                expected_lease_token=claimed["lease_token"],
                state="done",
                progress=100.0,
                stage="Done",
                result={
                    "schema_version": "technoeconomic-result-v3",
                    "summary": {"scenario": job_id},
                },
                result_provenance={
                    "schema_version": "technoeconomic-result-provenance-v3",
                    "kernel_contract": "tea-calculation-v3",
                },
                artifacts={},
            )
            reconciled = self.store.reconcile_decision_case_execution(current["id"])
            self.assertEqual("results_ready", reconciled["case"]["status"])
            self._refresh_case()

        scenario = self.store.get_decision_scenario(
            scenario["scenario_revision_id"]
        )
        self.assertIsNotNone(scenario)
        assert scenario is not None
        confirmation = confirmed["confirmation"]
        job = self.store.get_technoeconomic_job(job_id)
        self.assertIsNotNone(job)
        assert job is not None
        return {
            "scenario": scenario,
            "confirmation": confirmation,
            "job": job,
        }

    def _attempt_proof(
        self,
        execution: Mapping[str, Any],
        *,
        verified: bool,
    ) -> dict[str, Any]:
        scenario = execution["scenario"]
        job = execution["job"]
        return {
            "item_index": 0,
            "scenario_revision_id": scenario["scenario_revision_id"],
            "scenario_id": scenario["scenario_id"],
            "scenario_revision": scenario["revision"],
            "attempt_number": 1,
            "tea_job_id": job["id"],
            "retry_of_job_id": None,
            "selected_for_comparison": True,
            "state": job["state"],
            "verification_status": "verified" if verified else "pending",
            "request_sha256": scenario["request_sha256"],
            "source_snapshot_sha256": scenario["source_snapshot_sha256"],
            "result_sha256": (
                _canonical_sha256(job["result"])
                if job["result"] is not None
                else None
            ),
            "result_provenance_sha256": (
                _canonical_sha256(job["result_provenance"])
                if job["result_provenance"] is not None
                else None
            ),
            "evidence_set_sha256": _canonical_sha256([]),
            "reporting_tieout_sha256": "e" * 64 if verified else None,
        }

    def _create_bundle(
        self,
        execution: Mapping[str, Any],
        *,
        complete: bool,
        marker: str = "initial",
        expected_case_revision: int | None = None,
        comparison_bundle_id: str | None = None,
    ) -> dict[str, Any]:
        proof = self._attempt_proof(execution, verified=complete)
        bundle: dict[str, Any] = {
            "schema_version": "autonomy-decision-comparison-v1",
            "is_complete": complete,
            "recommendation_eligible": False,
            "attempt_proofs": [proof],
            "scenarios": [
                {
                    "scenario_revision_id": proof["scenario_revision_id"],
                    "tea_job_id": proof["tea_job_id"],
                    "status": proof["state"],
                }
            ],
            "comparison": {"fixture_marker": marker},
            "recommendation": {
                "state": "classification_pending_contract",
                "reversal_conditions": [],
            },
        }
        bundle_sha256 = _canonical_sha256(bundle)
        bundle["bundle_hash"] = bundle_sha256
        current = self._refresh_case()
        return self.store.create_decision_comparison_bundle(
            current["id"],
            expected_case_revision=(
                current["revision"]
                if expected_case_revision is None
                else expected_case_revision
            ),
            source_confirmation_id=execution["confirmation"]["id"],
            bundle=bundle,
            bundle_sha256=bundle_sha256,
            attempt_proofs=[proof],
            created_by="Decision Brief Builder",
            comparison_bundle_id=comparison_bundle_id,
        )

    def _create_brief(
        self,
        bundle: Mapping[str, Any],
        *,
        expected_case_revision: int | None = None,
        idempotency_key: str = "create-decision-brief",
        caveats: list[Any] | None = None,
        brief_id: str | None = None,
        brief_revision_id: str | None = None,
    ) -> dict[str, Any]:
        current = self._refresh_case()
        provenance = {
            "schema_version": "autonomy-decision-brief-provenance-v1",
            "case_id": current["id"],
            "source_confirmation_id": bundle["source_confirmation_id"],
            "comparison_bundle_id": bundle["comparison_bundle_id"],
            "comparison_bundle_sha256": bundle["bundle_sha256"],
            "comparison_schema_version": bundle["bundle_schema_version"],
            "recommendation_contract_state": "classification_pending_contract",
            "result_interpretation": "deterministic_server_only",
            "decision_agent_result_access": False,
            "signoff_available": False,
            "report_generation_available": False,
        }
        return self.store.create_decision_brief(
            current["id"],
            expected_case_revision=(
                current["revision"]
                if expected_case_revision is None
                else expected_case_revision
            ),
            comparison_bundle_id=bundle["comparison_bundle_id"],
            recommendation_classification="classification_pending_contract",
            confidence_state="classification_pending_contract",
            caveats=(
                caveats
                if caveats is not None
                else ["Recommendation thresholds remain pending contract approval."]
            ),
            reversal_conditions=[],
            provenance=provenance,
            created_by="Decision Brief Builder",
            idempotency_key=idempotency_key,
            brief_id=brief_id,
            brief_revision_id=brief_revision_id,
        )

    def test_schema_v8_migrates_v7_transactionally_and_survives_restart(self) -> None:
        case_id = self.case["id"]
        source_id = self.source["id"]
        with closing(sqlite3.connect(self.db_path)) as connection:
            connection.execute("PRAGMA foreign_keys = OFF")
            trigger_rows = connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'trigger' "
                "AND (name LIKE 'decision_comparison_%' "
                "OR name LIKE 'decision_brief_%')"
            ).fetchall()
            for (trigger_name,) in trigger_rows:
                connection.execute(f'DROP TRIGGER "{trigger_name}"')
            for table_name in (
                "decision_brief_idempotency",
                "decision_briefs",
                "decision_comparison_bundle_attempts",
                "decision_comparison_bundles",
            ):
                connection.execute(f'DROP TABLE "{table_name}"')
            connection.execute("DELETE FROM schema_migrations WHERE version = 8")
            connection.execute("PRAGMA user_version = 7")
            connection.commit()

        reopened = AgentStore(self.db_path, now=self.clock)
        restarted = AgentStore(self.db_path, now=self.clock)

        self.assertEqual(8, SCHEMA_VERSION)
        self.assertEqual(8, reopened.schema_version)
        self.assertEqual(8, restarted.schema_version)
        self.assertEqual(case_id, restarted.get_decision_case(case_id)["id"])
        self.assertEqual(source_id, restarted.get_job(source_id)["id"])
        with closing(sqlite3.connect(self.db_path)) as connection:
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            migrations = connection.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            ).fetchall()
        self.assertTrue(
            {
                "decision_comparison_bundles",
                "decision_comparison_bundle_attempts",
                "decision_briefs",
                "decision_brief_idempotency",
            }.issubset(tables)
        )
        self.assertEqual([(number,) for number in range(1, 9)], migrations)

    def test_schema_v8_failure_rolls_back_every_migration_side_effect(self) -> None:
        with closing(sqlite3.connect(self.db_path)) as connection:
            connection.execute("PRAGMA foreign_keys = OFF")
            trigger_rows = connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'trigger' "
                "AND (name LIKE 'decision_comparison_%' "
                "OR name LIKE 'decision_brief_%')"
            ).fetchall()
            for (trigger_name,) in trigger_rows:
                connection.execute(f'DROP TRIGGER "{trigger_name}"')
            for table_name in (
                "decision_brief_idempotency",
                "decision_briefs",
                "decision_comparison_bundle_attempts",
                "decision_comparison_bundles",
            ):
                connection.execute(f'DROP TABLE "{table_name}"')
            connection.execute("DELETE FROM schema_migrations WHERE version = 8")
            connection.execute("PRAGMA user_version = 7")
            connection.execute(
                "CREATE TABLE decision_comparison_bundles ("
                "comparison_bundle_id TEXT PRIMARY KEY)"
            )
            connection.commit()

        with self.assertRaises(sqlite3.OperationalError):
            AgentStore(self.db_path, now=self.clock)

        with closing(sqlite3.connect(self.db_path)) as connection:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            migration = connection.execute(
                "SELECT 1 FROM schema_migrations WHERE version = 8"
            ).fetchone()
            created_tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table' "
                    "AND (name LIKE 'decision_comparison_%' "
                    "OR name LIKE 'decision_brief_%')"
                )
            }
        self.assertEqual(7, version)
        self.assertIsNone(migration)
        self.assertEqual({"decision_comparison_bundles"}, created_tables)

    def test_newer_schema_is_rejected(self) -> None:
        future_path = self.db_path.with_name(
            f"{self.db_path.stem}-future.sqlite3"
        )
        self.addCleanup(self._remove_database_files, future_path)
        with closing(sqlite3.connect(future_path)) as connection:
            connection.execute("PRAGMA user_version = 9")
        with self.assertRaises(SchemaVersionError):
            AgentStore(future_path, now=self.clock)

    def test_exact_bundle_and_brief_idempotency_survive_restart(self) -> None:
        execution = self._confirmed_baseline(complete=True)
        bundle = self._create_bundle(
            execution,
            complete=True,
            comparison_bundle_id="dcmp_exact_snapshot",
        )
        replay = self.store.create_decision_comparison_bundle(
            self.case["id"],
            expected_case_revision=bundle["expected_case_revision"],
            source_confirmation_id=bundle["source_confirmation_id"],
            bundle=bundle["bundle"],
            bundle_sha256=bundle["bundle_sha256"],
            attempt_proofs=bundle["attempt_proofs"],
            created_by=bundle["created_by"],
            comparison_bundle_id="dcmp_ignored_on_exact_replay",
        )
        self.assertEqual(bundle["id"], replay["id"])
        self.assertTrue(replay["idempotent_replay"])
        with self.assertRaises(StoreConflict):
            self.store.create_decision_comparison_bundle(
                self.case["id"],
                expected_case_revision=bundle["expected_case_revision"],
                source_confirmation_id=bundle["source_confirmation_id"],
                bundle=bundle["bundle"],
                bundle_sha256=bundle["bundle_sha256"],
                attempt_proofs=bundle["attempt_proofs"],
                created_by="Different Builder",
            )

        expected_revision = self._refresh_case()["revision"]
        brief = self._create_brief(
            bundle,
            expected_case_revision=expected_revision,
            brief_id="dbf_exact_snapshot",
            brief_revision_id="dbr_exact_snapshot_r1",
        )
        replay = self._create_brief(
            bundle,
            expected_case_revision=expected_revision,
            brief_id="dbf_exact_snapshot",
            brief_revision_id="dbr_exact_snapshot_r1",
        )
        natural_replay = self._create_brief(
            bundle,
            expected_case_revision=expected_revision,
            idempotency_key="create-decision-brief-natural-replay",
            brief_id="dbf_exact_snapshot",
            brief_revision_id="dbr_exact_snapshot_r1",
        )
        self.assertEqual(brief["id"], replay["id"])
        self.assertEqual(brief["id"], natural_replay["id"])
        self.assertTrue(replay["idempotent_replay"])
        self.assertTrue(natural_replay["idempotent_replay"])
        with self.assertRaises(StoreConflict):
            self._create_brief(
                bundle,
                expected_case_revision=expected_revision,
                caveats=["Changed input under a reused idempotency key."],
            )

        restarted = AgentStore(self.db_path, now=self.clock)
        self.assertEqual(bundle["bundle"], restarted.get_decision_comparison_bundle(
            bundle["id"]
        )["bundle"])
        self.assertEqual(brief["provenance"], restarted.get_decision_brief(
            brief["id"]
        )["provenance"])
        exact_snapshot = restarted.get_decision_brief_for_snapshot(
            self.case["id"],
            comparison_bundle_id=bundle["id"],
            expected_case_revision=brief["expected_case_revision"],
            comparison_bundle_sha256=bundle["bundle_sha256"],
        )
        self.assertIsNotNone(exact_snapshot)
        assert exact_snapshot is not None
        self.assertEqual(brief["id"], exact_snapshot["id"])

    def test_concurrent_exact_bundle_and_brief_creation_converges(self) -> None:
        execution = self._confirmed_baseline(complete=True)
        proof = self._attempt_proof(execution, verified=True)
        payload: dict[str, Any] = {
            "schema_version": "autonomy-decision-comparison-v1",
            "is_complete": True,
            "recommendation_eligible": False,
            "attempt_proofs": [proof],
            "comparison": {"fixture_marker": "concurrent"},
        }
        digest = _canonical_sha256(payload)
        payload["bundle_hash"] = digest
        expected_revision = self._refresh_case()["revision"]
        stores = [
            AgentStore(self.db_path, now=self.clock),
            AgentStore(self.db_path, now=self.clock),
        ]
        barrier = threading.Barrier(2)
        bundles: list[dict[str, Any]] = []
        errors: list[BaseException] = []

        def create_bundle(index: int) -> None:
            try:
                barrier.wait()
                bundles.append(
                    stores[index].create_decision_comparison_bundle(
                        self.case["id"],
                        expected_case_revision=expected_revision,
                        source_confirmation_id=execution["confirmation"]["id"],
                        bundle=payload,
                        bundle_sha256=digest,
                        attempt_proofs=[proof],
                        created_by="Decision Brief Builder",
                        comparison_bundle_id=f"dcmp_concurrent_{index}",
                    )
                )
            except BaseException as exc:  # pragma: no cover - asserted below
                errors.append(exc)

        threads = [
            threading.Thread(target=create_bundle, args=(index,))
            for index in range(2)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual([], errors)
        self.assertEqual(2, len(bundles))
        self.assertEqual(1, len({bundle["id"] for bundle in bundles}))
        self.assertEqual(1, sum(bundle["idempotent_replay"] for bundle in bundles))

        bundle = bundles[0]
        brief_revision = self._refresh_case()["revision"]
        barrier = threading.Barrier(2)
        briefs: list[dict[str, Any]] = []
        errors = []

        def create_brief(index: int) -> None:
            try:
                barrier.wait()
                briefs.append(
                    stores[index].create_decision_brief(
                        self.case["id"],
                        expected_case_revision=brief_revision,
                        comparison_bundle_id=bundle["id"],
                        recommendation_classification=(
                            "classification_pending_contract"
                        ),
                        confidence_state="classification_pending_contract",
                        caveats=["Threshold contract remains pending."],
                        reversal_conditions=[],
                        provenance={"comparison_bundle_sha256": digest},
                        created_by="Decision Brief Builder",
                        idempotency_key=f"concurrent-brief-{index}",
                    )
                )
            except BaseException as exc:  # pragma: no cover - asserted below
                errors.append(exc)

        threads = [
            threading.Thread(target=create_brief, args=(index,))
            for index in range(2)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual([], errors)
        self.assertEqual(2, len(briefs))
        self.assertEqual(1, len({brief["id"] for brief in briefs}))
        self.assertEqual(1, sum(brief["idempotent_replay"] for brief in briefs))

    def test_concurrent_distinct_bundles_consume_one_case_revision(self) -> None:
        execution = self._confirmed_baseline(complete=True)
        proof = self._attempt_proof(execution, verified=True)
        expected_revision = self._refresh_case()["revision"]
        stores = [
            AgentStore(self.db_path, now=self.clock),
            AgentStore(self.db_path, now=self.clock),
        ]
        payloads: list[dict[str, Any]] = []
        for marker in ("first", "second"):
            payload: dict[str, Any] = {
                "schema_version": "autonomy-decision-comparison-v1",
                "is_complete": True,
                "recommendation_eligible": False,
                "attempt_proofs": [proof],
                "comparison": {"fixture_marker": marker},
            }
            payload["bundle_hash"] = _canonical_sha256(payload)
            payloads.append(payload)

        barrier = threading.Barrier(2)
        bundles: list[dict[str, Any]] = []
        errors: list[BaseException] = []

        def create_distinct_bundle(index: int) -> None:
            try:
                barrier.wait()
                payload = payloads[index]
                bundles.append(
                    stores[index].create_decision_comparison_bundle(
                        self.case["id"],
                        expected_case_revision=expected_revision,
                        source_confirmation_id=execution["confirmation"]["id"],
                        bundle=payload,
                        bundle_sha256=payload["bundle_hash"],
                        attempt_proofs=[proof],
                        created_by="Decision Brief Builder",
                        comparison_bundle_id=f"dcmp_distinct_{index}",
                    )
                )
            except BaseException as exc:  # pragma: no cover - asserted below
                errors.append(exc)

        threads = [
            threading.Thread(target=create_distinct_bundle, args=(index,))
            for index in range(2)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(1, len(bundles))
        self.assertEqual(1, len(errors))
        self.assertIsInstance(errors[0], StoreConflict)
        self.assertEqual(
            expected_revision + 1,
            self._refresh_case()["revision"],
        )
        self.assertEqual(
            1,
            len(self.store.list_decision_comparison_bundles(self.case["id"])),
        )

    def test_store_rejects_unapproved_recommendation_authority(self) -> None:
        execution = self._confirmed_baseline(complete=True)
        proof = self._attempt_proof(execution, verified=True)
        unauthorized: dict[str, Any] = {
            "schema_version": "autonomy-decision-comparison-v1",
            "is_complete": True,
            "recommendation_eligible": True,
            "attempt_proofs": [proof],
        }
        unauthorized["bundle_hash"] = _canonical_sha256(unauthorized)
        with self.assertRaisesRegex(
            InvalidStateTransition,
            "pending a versioned contract",
        ):
            self.store.create_decision_comparison_bundle(
                self.case["id"],
                expected_case_revision=self._refresh_case()["revision"],
                source_confirmation_id=execution["confirmation"]["id"],
                bundle=unauthorized,
                bundle_sha256=unauthorized["bundle_hash"],
                attempt_proofs=[proof],
                created_by="Unauthorized classifier",
            )

        bundle = self._create_bundle(execution, complete=True)
        with self.assertRaisesRegex(
            InvalidStateTransition,
            "pending a versioned contract",
        ):
            self.store.create_decision_brief(
                self.case["id"],
                expected_case_revision=bundle["case_revision_after"],
                comparison_bundle_id=bundle["id"],
                recommendation_classification="solaredge",
                confidence_state="strong",
                caveats=[],
                reversal_conditions=[],
                provenance={"contract": "not-approved"},
                created_by="Unauthorized classifier",
                idempotency_key="unauthorized-final-brief",
            )

    def test_incomplete_bundle_cannot_create_a_durable_brief(self) -> None:
        execution = self._confirmed_baseline(complete=False)
        bundle = self._create_bundle(execution, complete=False)
        self.assertFalse(bundle["is_complete"])
        with self.assertRaises(InvalidStateTransition):
            self._create_brief(bundle)

        provenance_json = _canonical_json({"schema_version": "raw-guard-test"})
        with closing(sqlite3.connect(self.db_path)) as connection:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    """
                    INSERT INTO decision_briefs (
                        brief_revision_id, brief_id, case_id, revision,
                        parent_revision_id, superseded_by_revision_id,
                        source_confirmation_id, comparison_bundle_id,
                        expected_case_revision, case_revision_after,
                        comparison_bundle_json, comparison_bundle_sha256,
                        recommendation_classification, confidence_state,
                        caveats_json, reversal_conditions_json,
                        provenance_json, provenance_sha256, created_by,
                        created_at
                    ) VALUES (
                        ?, ?, ?, 1, NULL, NULL, ?, ?, ?, ?, ?, ?,
                        'classification_pending_contract',
                        'classification_pending_contract',
                        '[]', '[]', ?, ?, ?, ?
                    )
                    """,
                    (
                        "dbr_raw_incomplete_r1",
                        "dbf_raw_incomplete",
                        self.case["id"],
                        bundle["source_confirmation_id"],
                        bundle["id"],
                        bundle["expected_case_revision"],
                        bundle["expected_case_revision"] + 1,
                        _canonical_json(bundle["bundle"]),
                        bundle["bundle_sha256"],
                        provenance_json,
                        _canonical_sha256({"schema_version": "raw-guard-test"}),
                        "Raw guard test",
                        self.clock.value.isoformat(),
                    ),
                )
            connection.rollback()

    def test_brief_supersession_timestamp_requires_a_target_at_insert(self) -> None:
        execution = self._confirmed_baseline(complete=True)
        bundle = self._create_bundle(execution, complete=True)
        provenance = {"schema_version": "raw-supersession-guard-test"}
        provenance_json = _canonical_json(provenance)
        with closing(sqlite3.connect(self.db_path)) as connection:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    """
                    INSERT INTO decision_briefs (
                        brief_revision_id, brief_id, case_id, revision,
                        parent_revision_id, superseded_by_revision_id,
                        source_confirmation_id, comparison_bundle_id,
                        expected_case_revision, case_revision_after,
                        comparison_bundle_json, comparison_bundle_sha256,
                        recommendation_classification, confidence_state,
                        caveats_json, reversal_conditions_json,
                        provenance_json, provenance_sha256, created_by,
                        created_at, superseded_at
                    ) VALUES (
                        ?, ?, ?, 1, NULL, NULL, ?, ?, ?, ?, ?, ?,
                        'classification_pending_contract',
                        'classification_pending_contract',
                        '[]', '[]', ?, ?, ?, ?, ?
                    )
                    """,
                    (
                        "dbr_raw_superseded_r1",
                        "dbf_raw_superseded",
                        self.case["id"],
                        bundle["source_confirmation_id"],
                        bundle["id"],
                        bundle["expected_case_revision"],
                        bundle["expected_case_revision"] + 1,
                        _canonical_json(bundle["bundle"]),
                        bundle["bundle_sha256"],
                        provenance_json,
                        _canonical_sha256(provenance),
                        "Raw guard test",
                        self.clock.value.isoformat(),
                        self.clock.value.isoformat(),
                    ),
                )
            connection.rollback()

    def test_cross_case_and_tampered_creation_identities_are_rejected(self) -> None:
        execution = self._confirmed_baseline(complete=True)
        proof = self._attempt_proof(execution, verified=True)
        bundle_payload = {
            "schema_version": "autonomy-decision-comparison-v1",
            "is_complete": True,
            "recommendation_eligible": False,
            "attempt_proofs": [proof],
        }
        digest = _canonical_sha256(bundle_payload)
        bundle_payload["bundle_hash"] = digest
        with self.assertRaises(StoreConflict):
            self.store.create_decision_comparison_bundle(
                self.case["id"],
                expected_case_revision=self._refresh_case()["revision"],
                source_confirmation_id=execution["confirmation"]["id"],
                bundle=bundle_payload,
                bundle_sha256="f" * 64,
                attempt_proofs=[proof],
                created_by="Decision Brief Builder",
            )
        tampered_proof = dict(proof)
        tampered_proof["scenario_id"] = "dsc_unrelated"
        tampered_bundle = dict(bundle_payload)
        tampered_bundle["attempt_proofs"] = [tampered_proof]
        tampered_bundle.pop("bundle_hash")
        tampered_digest = _canonical_sha256(tampered_bundle)
        tampered_bundle["bundle_hash"] = tampered_digest
        with self.assertRaises(StoreConflict):
            self.store.create_decision_comparison_bundle(
                self.case["id"],
                expected_case_revision=self._refresh_case()["revision"],
                source_confirmation_id=execution["confirmation"]["id"],
                bundle=tampered_bundle,
                bundle_sha256=tampered_digest,
                attempt_proofs=[tampered_proof],
                created_by="Decision Brief Builder",
            )

        bundle = self._create_bundle(execution, complete=True)
        other_case = self._locked_case("Unrelated decision case")
        with self.assertRaises(StoreConflict):
            self.store.create_decision_brief(
                other_case["id"],
                expected_case_revision=other_case["revision"],
                comparison_bundle_id=bundle["id"],
                recommendation_classification="classification_pending_contract",
                confidence_state="classification_pending_contract",
                caveats=[],
                reversal_conditions=[],
                provenance={"case_id": other_case["id"]},
                created_by="Decision Brief Builder",
                idempotency_key="cross-case-brief",
            )

    def test_database_guards_retain_bundle_brief_proofs_receipts_and_events(self) -> None:
        execution = self._confirmed_baseline(complete=True)
        bundle = self._create_bundle(execution, complete=True)
        brief = self._create_brief(bundle)
        with closing(sqlite3.connect(self.db_path)) as connection:
            guarded_statements = (
                (
                    "UPDATE decision_comparison_bundles SET bundle_json = '{}' "
                    "WHERE comparison_bundle_id = ?",
                    (bundle["id"],),
                ),
                (
                    "DELETE FROM decision_comparison_bundle_attempts "
                    "WHERE comparison_bundle_id = ?",
                    (bundle["id"],),
                ),
                (
                    "DELETE FROM decision_comparison_bundles "
                    "WHERE comparison_bundle_id = ?",
                    (bundle["id"],),
                ),
                (
                    "UPDATE decision_briefs SET caveats_json = '[]' "
                    "WHERE brief_revision_id = ?",
                    (brief["id"],),
                ),
                (
                    "DELETE FROM decision_briefs WHERE brief_revision_id = ?",
                    (brief["id"],),
                ),
                (
                    "DELETE FROM decision_brief_idempotency "
                    "WHERE brief_revision_id = ?",
                    (brief["id"],),
                ),
                (
                    "DELETE FROM decision_events WHERE case_id = ?",
                    (self.case["id"],),
                ),
            )
            for statement, parameters in guarded_statements:
                with self.subTest(statement=statement):
                    with self.assertRaises(sqlite3.IntegrityError):
                        connection.execute(statement, parameters)
                    connection.rollback()

    def test_bundle_and_brief_revisions_are_stale_and_superseded_one_way(self) -> None:
        execution = self._confirmed_baseline(complete=True)
        first_bundle = self._create_bundle(
            execution,
            complete=True,
            marker="first",
            comparison_bundle_id="dcmp_lineage_r1",
        )
        first_brief = self._create_brief(
            first_bundle,
            brief_id="dbf_lineage",
            brief_revision_id="dbr_lineage_r1",
        )
        current_revision = self._refresh_case()["revision"]
        second_bundle = self._create_bundle(
            execution,
            complete=True,
            marker="second",
            expected_case_revision=current_revision,
            comparison_bundle_id="dcmp_lineage_r2",
        )
        first_bundle = self.store.get_decision_comparison_bundle(first_bundle["id"])
        self.assertEqual(second_bundle["id"], first_bundle["superseded_by_bundle_id"])
        self.assertIsNotNone(first_bundle["stale_at"])
        self.assertFalse(first_bundle["is_current"])

        second_brief = self._create_brief(
            second_bundle,
            expected_case_revision=second_bundle["case_revision_after"],
            idempotency_key="create-decision-brief-r2",
            brief_id=first_brief["brief_id"],
            brief_revision_id="dbr_lineage_r2",
        )
        first_brief = self.store.get_decision_brief(first_brief["id"])
        self.assertEqual(2, second_brief["revision"])
        self.assertEqual(first_brief["id"], second_brief["parent_revision_id"])
        self.assertEqual(
            second_brief["id"], first_brief["superseded_by_revision_id"]
        )
        self.assertIsNotNone(first_brief["stale_at"])
        self.assertFalse(first_brief["is_current"])

        with closing(sqlite3.connect(self.db_path)) as connection:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "UPDATE decision_briefs SET stale_at = NULL, "
                    "stale_reason_json = NULL WHERE brief_revision_id = ?",
                    (first_brief["id"],),
                )
            connection.rollback()
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "UPDATE decision_comparison_bundles "
                    "SET superseded_by_bundle_id = NULL, superseded_at = NULL "
                    "WHERE comparison_bundle_id = ?",
                    (first_bundle["id"],),
                )
            connection.rollback()

        event_types = [
            event["event_type"]
            for event in self.store.list_decision_events(self.case["id"])
        ]
        self.assertEqual(2, event_types.count("decision_comparison_bundle_built"))
        self.assertEqual(
            1, event_types.count("decision_comparison_bundle_superseded")
        )
        self.assertEqual(2, event_types.count("decision_brief_created"))
        self.assertEqual(1, event_types.count("decision_brief_superseded"))

    def test_result_completion_and_retry_proactively_stale_current_bundle(self) -> None:
        execution = self._confirmed_baseline(complete=False)
        queued_bundle = self._create_bundle(execution, complete=False)
        claimed = self.store.claim_next_queued_work(worker_id="result-worker")
        self.assertIsNotNone(claimed)
        assert claimed is not None
        self.store.update_technoeconomic_job(
            execution["job"]["id"],
            expected_worker_id="result-worker",
            expected_lease_token=claimed["lease_token"],
            state="error",
            stage="Failed",
            error="deterministic fixture failure",
        )
        stale = self.store.get_decision_comparison_bundle(queued_bundle["id"])
        self.assertIsNotNone(stale["stale_at"])
        self.assertEqual(
            "decision_scenario_attempt_changed", stale["stale_reason"]["code"]
        )

        execution["job"] = self.store.get_technoeconomic_job(
            execution["job"]["id"]
        )
        failed_bundle = self._create_bundle(
            execution,
            complete=False,
            marker="failed-before-retry",
        )
        current = self._refresh_case()
        retry = self.store.retry_decision_scenario_job(
            current["id"],
            execution["scenario"]["scenario_revision_id"],
            execution["job"]["id"],
            expected_case_revision=current["revision"],
            operator_name="Retry Operator",
            reason="Retry the exact frozen request.",
            new_job_id="tea_decision_brief_retry_2",
        )
        failed_bundle = self.store.get_decision_comparison_bundle(
            failed_bundle["id"]
        )
        self.assertIsNotNone(failed_bundle["stale_at"])
        self.assertEqual(
            "decision_scenario_retry_created",
            failed_bundle["stale_reason"]["code"],
        )
        original_proof = failed_bundle["attempt_proofs"][0]
        retry_job = retry["job"]
        with closing(sqlite3.connect(self.db_path)) as connection:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    """
                    INSERT INTO decision_comparison_bundle_attempts (
                        comparison_bundle_id, case_id, item_index,
                        scenario_revision_id, scenario_id, scenario_revision,
                        attempt_number, tea_job_id, retry_of_job_id,
                        selected_for_comparison, state, verification_status,
                        request_sha256, source_snapshot_sha256,
                        result_sha256, result_provenance_sha256,
                        evidence_set_sha256, reporting_tieout_sha256,
                        created_at
                    ) VALUES (
                        ?, ?, ?, ?, ?, ?, 2, ?, ?, 1, 'queued', 'pending',
                        ?, ?, NULL, NULL, ?, NULL, ?
                    )
                    """,
                    (
                        failed_bundle["id"],
                        self.case["id"],
                        original_proof["item_index"],
                        original_proof["scenario_revision_id"],
                        original_proof["scenario_id"],
                        original_proof["scenario_revision"],
                        retry_job["id"],
                        retry_job["retry_of_job_id"],
                        original_proof["request_sha256"],
                        original_proof["source_snapshot_sha256"],
                        original_proof["evidence_set_sha256"],
                        retry_job["created_at"],
                    ),
                )
            connection.rollback()
        restarted = AgentStore(self.db_path, now=self.clock)
        self.assertEqual(
            failed_bundle["stale_at"],
            restarted.get_decision_comparison_bundle(failed_bundle["id"])[
                "stale_at"
            ],
        )

    def test_new_scenario_revision_atomically_stales_bundle_and_brief(self) -> None:
        execution = self._confirmed_baseline(complete=True)
        bundle = self._create_bundle(execution, complete=True)
        brief = self._create_brief(bundle)
        current = self._refresh_case()
        scenario = execution["scenario"]
        revised = self.store.revise_decision_scenario(
            scenario["scenario_id"],
            expected_case_revision=current["revision"],
            expected_revision=scenario["revision"],
            label="Current baseline revision two",
            request=scenario["request"],
            request_sha256=scenario["request_sha256"],
            changed_fields=[],
            comparison_classification="baseline",
            evidence_receipt_refs=[],
            operator_name="Scenario Editor",
            scenario_revision_id="dscr_decision_brief_baseline_r2",
        )
        self.assertEqual(2, revised["revision"])
        stale_bundle = self.store.get_decision_comparison_bundle(bundle["id"])
        stale_brief = self.store.get_decision_brief(brief["id"])
        self.assertEqual(stale_bundle["stale_at"], stale_brief["stale_at"])
        self.assertEqual(
            "decision_scenario_revision_created",
            stale_bundle["stale_reason"]["code"],
        )
        self.assertEqual(stale_bundle["stale_reason"], stale_brief["stale_reason"])
        event_types = [
            event["event_type"]
            for event in self.store.list_decision_events(self.case["id"])
        ]
        self.assertGreaterEqual(
            event_types.count("decision_comparison_bundle_stale"), 1
        )
        self.assertGreaterEqual(event_types.count("decision_brief_stale"), 1)
        restarted = AgentStore(self.db_path, now=self.clock)
        self.assertEqual(
            stale_brief["stale_at"],
            restarted.get_decision_brief(brief["id"])["stale_at"],
        )

    def test_read_fails_closed_after_bundle_payload_tampering(self) -> None:
        execution = self._confirmed_baseline(complete=True)
        bundle = self._create_bundle(execution, complete=True)
        with closing(sqlite3.connect(self.db_path)) as connection:
            connection.execute(
                "DROP TRIGGER decision_comparison_bundle_identity_is_immutable"
            )
            connection.execute(
                "UPDATE decision_comparison_bundles SET bundle_json = ? "
                "WHERE comparison_bundle_id = ?",
                (
                    _canonical_json(
                        {
                            "schema_version": "autonomy-decision-comparison-v1",
                            "is_complete": True,
                            "recommendation_eligible": False,
                            "bundle_hash": bundle["bundle_sha256"],
                            "tampered": True,
                        }
                    ),
                    bundle["id"],
                ),
            )
            connection.commit()
        with self.assertRaises(StoreConflict):
            self.store.get_decision_comparison_bundle(bundle["id"])

    def test_read_fails_closed_after_attempt_proof_tampering(self) -> None:
        execution = self._confirmed_baseline(complete=True)
        bundle = self._create_bundle(execution, complete=True)
        brief = self._create_brief(bundle)
        with closing(sqlite3.connect(self.db_path)) as connection:
            connection.execute(
                "DROP TRIGGER decision_comparison_attempt_update_guard"
            )
            connection.execute(
                "UPDATE decision_comparison_bundle_attempts "
                "SET reporting_tieout_sha256 = ? "
                "WHERE comparison_bundle_id = ?",
                ("f" * 64, bundle["id"]),
            )
            connection.commit()
        with self.assertRaises(StoreConflict):
            self.store.get_decision_comparison_bundle(bundle["id"])
        with self.assertRaises(StoreConflict):
            self.store.get_decision_brief(brief["id"])
        with self.assertRaises(StoreConflict):
            self.store.list_decision_briefs(self.case["id"])
        with self.assertRaises(StoreConflict):
            self._create_brief(
                bundle,
                expected_case_revision=brief["expected_case_revision"],
            )

    def test_read_fails_closed_after_brief_provenance_or_replay_tampering(
        self,
    ) -> None:
        execution = self._confirmed_baseline(complete=True)
        bundle = self._create_bundle(execution, complete=True)
        brief = self._create_brief(bundle)
        with closing(sqlite3.connect(self.db_path)) as connection:
            connection.execute("DROP TRIGGER decision_brief_identity_is_immutable")
            connection.execute(
                "UPDATE decision_briefs SET provenance_json = ? "
                "WHERE brief_revision_id = ?",
                (_canonical_json({"tampered": True}), brief["id"]),
            )
            connection.commit()
        with self.assertRaises(StoreConflict):
            self.store.get_decision_brief(brief["id"])

        with closing(sqlite3.connect(self.db_path)) as connection:
            connection.execute(
                "DROP TRIGGER decision_brief_idempotency_update_guard"
            )
            connection.execute(
                "UPDATE decision_brief_idempotency SET response_sha256 = ? "
                "WHERE brief_revision_id = ?",
                ("2" * 64, brief["id"]),
            )
            connection.commit()
        with self.assertRaises(StoreConflict):
            self._create_brief(
                bundle,
                expected_case_revision=brief["expected_case_revision"],
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
