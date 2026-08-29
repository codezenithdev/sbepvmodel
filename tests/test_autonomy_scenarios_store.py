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
from typing import Any, Mapping, Sequence

from sbepv.store import (
    AgentStore,
    InvalidStateTransition,
    LeaseOwnershipLost,
    SCHEMA_VERSION,
    StoreConflict,
)


def _canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


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


class AutonomyScenarioStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        handle = tempfile.NamedTemporaryFile(
            prefix="autonomy-scenarios-store-test-",
            suffix=".sqlite3",
            dir=Path(__file__).resolve().parent,
            delete=False,
        )
        handle.close()
        self.db_path = Path(handle.name)
        self.addCleanup(self._remove_database_files, self.db_path)
        self.clock = MutableClock()
        self.store = AgentStore(self.db_path, now=self.clock)
        self.source = self._completed_annual_source("annual-scenario-source")
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
        self.case = self._locked_case("Scenario execution decision")
        self._receipt: dict[str, Any] | None = None
        self._receipt_asset: dict[str, Any] | None = None

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
            provenance={"source": "scenario-store-test"},
        )

    def _locked_case(self, title: str) -> dict[str, Any]:
        case = self.store.create_decision_case(
            title=title,
            question="Which exact TEA assumptions should be compared?",
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

    def _ensure_case_ready_to_run(self) -> dict[str, Any]:
        current = self._refresh_case()
        if current["status"] == "draft":
            current = self.store.transition_decision_case(
                current["id"],
                expected_revision=current["revision"],
                status="evidence_needed",
                operator_name="Scenario Validator",
                reason="Scenario evidence is under deterministic review.",
            )
        if current["status"] in {"evidence_needed", "blocked"}:
            current = self.store.transition_decision_case(
                current["id"],
                expected_revision=current["revision"],
                status="ready_to_run",
                operator_name="Scenario Validator",
                reason="Selected scenario revisions are validated.",
            )
        self.case = current
        return current

    def _accepted_receipt_for_case(
        self,
        case: Mapping[str, Any],
        *,
        suffix: str,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        digest = suffix * 64
        asset = self.store.create_decision_evidence_asset(
            str(case["id"]),
            original_filename=f"scenario-evidence-{suffix}.pdf",
            display_filename=f"scenario-evidence-{suffix}.pdf",
            media_type="application/pdf",
            sha256=digest,
            byte_count=100,
            storage_key=f"sha256/{digest[:2]}/{digest}.pdf",
            evidence_class="project_actual",
            operator_name="Alex Operator",
            expected_revision=int(case["revision"]),
            candidates=[
                {
                    "field_name": "cost_lines.cost-se-capex.distribution.value",
                    "value": 130_000.0,
                    "unit": "USD",
                    "confidence": 0.99,
                    "source_location": {"page": 2, "line": 14},
                }
            ],
        )
        receipt = self.store.record_decision_evidence_review(
            asset["candidates"][0]["id"],
            decision="accepted",
            operator_name="Evidence Reviewer",
            rationale="Verified project actual for the scenario input.",
        )
        return asset, receipt

    def _ensure_receipt(self) -> dict[str, Any]:
        if self._receipt is None:
            asset, receipt = self._accepted_receipt_for_case(
                self._refresh_case(), suffix="a"
            )
            self._receipt_asset = asset
            self._receipt = receipt
            self._refresh_case()
        return self._receipt

    def _scenario_request(
        self,
        *,
        capex: float = 130_000.0,
        source_annual_job_id: str | None = None,
        basis: str = "solartac_site",
        n: int = 1_000,
        seed: int = 42,
    ) -> dict[str, Any]:
        return {
            "source_annual_job_id": source_annual_job_id or self.source["id"],
            "basis": basis,
            "n": n,
            "seed": seed,
            "assumptions": {
                "solaredge_initial_capex_usd": capex,
                "project_life_years": 20,
                "real_discount_rate": 0.05,
                "annual_degradation_rate": 0.005,
            },
        }

    def _create_scenario(
        self,
        *,
        kind: str,
        label: str | None = None,
        request: Mapping[str, Any] | None = None,
        changed_fields: Sequence[str] | None = None,
        comparison_classification: str | None = None,
        evidence_receipt_ids: Sequence[str] | None = None,
        expires_at: datetime | None = None,
        scenario_id: str | None = None,
        scenario_revision_id: str | None = None,
    ) -> dict[str, Any]:
        if evidence_receipt_ids is None:
            evidence_receipt_ids = [self._ensure_receipt()["id"]]
        current = self._refresh_case()
        scenario_request = dict(request or self._scenario_request())
        created = self.store.create_decision_scenario(
            current["id"],
            expected_case_revision=current["revision"],
            label=label or ("Current baseline" if kind == "baseline" else "Alternative"),
            kind=kind,
            request=scenario_request,
            request_sha256=_canonical_sha256(scenario_request),
            changed_fields=list(
                changed_fields
                if changed_fields is not None
                else (
                    []
                    if kind == "baseline"
                    else ["/assumptions/solaredge_initial_capex_usd"]
                )
            ),
            comparison_classification=(
                comparison_classification
                or ("baseline" if kind == "baseline" else "controlled")
            ),
            evidence_receipt_refs=list(evidence_receipt_ids),
            operator_name="Scenario Editor",
            expires_at=expires_at,
            scenario_id=scenario_id,
            scenario_revision_id=scenario_revision_id,
        )
        self._refresh_case()
        return created

    def _validate_scenario(
        self,
        scenario: Mapping[str, Any],
        *,
        valid: bool = True,
    ) -> dict[str, Any]:
        current_scenarios = self.store.list_decision_scenarios(
            str(scenario["case_id"]),
            include_history=False,
            include_expired=False,
        )
        baseline = next(
            (item for item in current_scenarios if item["kind"] == "baseline"),
            None,
        )
        validation = {
            "validation_version": "autonomy-scenario-validation-v1",
            "valid": valid,
            "request_sha256": scenario["request_sha256"],
            "baseline_request_sha256": (
                baseline["request_sha256"]
                if scenario["kind"] == "alternative" and baseline is not None
                else None
            ),
            "kind": scenario["kind"],
            "comparison_classification": scenario[
                "comparison_classification"
            ],
            "changed_fields": list(scenario["changed_fields"]),
            "declared_changed_fields": list(scenario["changed_fields"]),
            "field_errors": [] if valid else [
                {
                    "field": "assumptions.solaredge_initial_capex_usd",
                    "message": "A supported finite value is required.",
                }
            ],
            "violated_rules": [] if valid else ["tea.inputs.finite"],
            "closest_supported_alternatives": [] if valid else [
                {
                    "field": "assumptions.solaredge_initial_capex_usd",
                    "value": 130_000.0,
                }
            ],
        }
        current = self._refresh_case()
        updated = self.store.record_decision_scenario_validation(
            str(scenario["scenario_revision_id"]),
            expected_case_revision=current["revision"],
            expected_revision=int(scenario["revision"]),
            request_sha256=str(scenario["request_sha256"]),
            validation=validation,
            valid=valid,
            operator_name="Scenario Validator",
        )
        self._refresh_case()
        self.assertEqual(_canonical_sha256(validation), updated["validation_sha256"])
        return updated

    def _confirmation_item(
        self,
        scenario: Mapping[str, Any],
        *,
        job_id: str,
    ) -> dict[str, Any]:
        return {
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
                "evidence_receipt_ids": scenario["evidence_receipt_ids"],
            },
        }

    def _confirm(
        self,
        scenarios: Sequence[Mapping[str, Any]],
        *,
        idempotency_key: str,
        job_ids: Sequence[str] | None = None,
        expected_case_revision: int | None = None,
        max_active_jobs: int | None = None,
        rationale: str = "Run the exact validated comparison set.",
    ) -> dict[str, Any]:
        current = self._ensure_case_ready_to_run()
        resolved_job_ids = list(
            job_ids
            or [f"tea_scenario_{index + 1}" for index in range(len(scenarios))]
        )
        confirmations = [
            self._confirmation_item(scenario, job_id=job_id)
            for scenario, job_id in zip(scenarios, resolved_job_ids, strict=True)
        ]
        review = {
            "schema_version": 1,
            "case_id": current["id"],
            "source_annual_job_id": self.source["id"],
            "source_snapshot_sha256": self.source_snapshot_sha256,
            "analysis_basis": "solartac_site",
            "queue_behavior": "global_leased_sequential_worker",
            "request_hashes": [item["request_sha256"] for item in confirmations],
        }
        result = self.store.confirm_decision_scenarios_batch(
            current["id"],
            confirmations,
            expected_case_revision=(
                current["revision"]
                if expected_case_revision is None
                else expected_case_revision
            ),
            idempotency_key=idempotency_key,
            operator_name="Alex Operator",
            rationale=rationale,
            acknowledgement=(
                "I confirm the selected scenarios, source and basis lock, evidence "
                "status, realization count, seed, and exact request hashes shown here."
            ),
            confirmation_review=review,
            atomic_source_check=lambda _connection: self.source_snapshot_sha256,
            max_active_jobs=max_active_jobs,
        )
        self._refresh_case()
        return result

    def _finish_next_tea(self, *, state: str, worker_id: str) -> dict[str, Any]:
        claimed = self.store.claim_next_queued_work(worker_id=worker_id)
        self.assertIsNotNone(claimed)
        assert claimed is not None
        self.assertEqual("technoeconomic", claimed["workflow"])
        kwargs: dict[str, Any] = {
            "expected_worker_id": worker_id,
            "expected_lease_token": claimed["lease_token"],
            "state": state,
            "progress": 100.0,
            "stage": state.title(),
        }
        if state == "done":
            kwargs.update(
                result={"summary": {"scenario": claimed["id"]}},
                result_provenance={"kernel_contract": "tea-calculation-v3"},
                artifacts={},
            )
        else:
            kwargs["error"] = "synthetic scenario execution failure"
        return self.store.update_technoeconomic_job(claimed["id"], **kwargs)

    def test_schema_v7_migrates_v6_transactionally_and_preserves_existing_rows(
        self,
    ) -> None:
        case_id = self.case["id"]
        source_id = self.source["id"]
        with closing(sqlite3.connect(self.db_path)) as connection:
            connection.execute("PRAGMA foreign_keys = OFF")
            triggers = connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'trigger' "
                "AND sql LIKE '%decision_scenario%'"
            ).fetchall()
            for (trigger_name,) in triggers:
                connection.execute(f'DROP TRIGGER "{trigger_name}"')
            tables = connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' "
                "AND name LIKE 'decision_scenario%'"
            ).fetchall()
            for (table_name,) in tables:
                connection.execute(f'DROP TABLE "{table_name}"')
            connection.execute("DELETE FROM schema_migrations WHERE version = 7")
            connection.execute("PRAGMA user_version = 6")
            connection.commit()

        reopened = AgentStore(self.db_path, now=self.clock)

        self.assertEqual(7, SCHEMA_VERSION)
        self.assertEqual(7, reopened.schema_version)
        self.assertEqual(case_id, reopened.get_decision_case(case_id)["id"])
        self.assertEqual(source_id, reopened.get_job(source_id)["id"])
        expected_tables = {
            "decision_scenarios",
            "decision_scenario_evidence",
            "decision_scenario_confirmations",
            "decision_scenario_confirmation_items",
            "decision_scenario_jobs",
            "decision_scenario_confirmation_idempotency",
        }
        with closing(sqlite3.connect(self.db_path)) as connection:
            actual_tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table' "
                    "AND name LIKE 'decision_scenario%'"
                )
            }
            migrations = connection.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            ).fetchall()
            scenario_columns = {
                row[1]
                for row in connection.execute("PRAGMA table_info(decision_scenarios)")
            }
            indexed_tables = {
                row[0]
                for row in connection.execute(
                    "SELECT DISTINCT tbl_name FROM sqlite_master "
                    "WHERE type = 'index' AND sql IS NOT NULL "
                    "AND tbl_name LIKE 'decision_scenario%'"
                )
            }
        self.assertEqual(expected_tables, actual_tables)
        self.assertEqual([(1,), (2,), (3,), (4,), (5,), (6,), (7,)], migrations)
        self.assertTrue(
            {
                "scenario_revision_id",
                "scenario_id",
                "case_id",
                "revision",
                "request_json",
                "request_sha256",
                "source_annual_job_id",
                "source_snapshot_sha256",
                "analysis_basis",
            }.issubset(scenario_columns)
        )
        self.assertIn("decision_scenarios", indexed_tables)
        self.assertIn("decision_scenario_jobs", indexed_tables)

    def test_schema_v7_failure_rolls_back_every_migration_side_effect(self) -> None:
        with closing(sqlite3.connect(self.db_path)) as connection:
            connection.execute("PRAGMA foreign_keys = OFF")
            triggers = connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'trigger' "
                "AND sql LIKE '%decision_scenario%'"
            ).fetchall()
            for (trigger_name,) in triggers:
                connection.execute(f'DROP TRIGGER "{trigger_name}"')
            tables = connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' "
                "AND name LIKE 'decision_scenario%'"
            ).fetchall()
            for (table_name,) in tables:
                connection.execute(f'DROP TABLE "{table_name}"')
            connection.execute("DELETE FROM schema_migrations WHERE version = 7")
            connection.execute("PRAGMA user_version = 6")
            connection.execute(
                "CREATE TABLE decision_scenarios ("
                "scenario_revision_id TEXT PRIMARY KEY)"
            )
            connection.commit()

        with self.assertRaises(sqlite3.OperationalError):
            AgentStore(self.db_path, now=self.clock)

        with closing(sqlite3.connect(self.db_path)) as connection:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            migration = connection.execute(
                "SELECT 1 FROM schema_migrations WHERE version = 7"
            ).fetchone()
            created_tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table' "
                    "AND name LIKE 'decision_scenario%'"
                )
            }
        self.assertEqual(6, version)
        self.assertIsNone(migration)
        self.assertEqual({"decision_scenarios"}, created_tables)

    def test_scenario_round_trip_freezes_lock_evidence_hash_and_seven_day_expiry(
        self,
    ) -> None:
        before = self.clock.value
        request = self._scenario_request()
        created = self._create_scenario(
            kind="baseline",
            request=request,
            scenario_id="dsc_baseline",
            scenario_revision_id="dscr_baseline_r1",
        )

        self.assertEqual("dsc_baseline", created["id"])
        self.assertEqual("dscr_baseline_r1", created["scenario_revision_id"])
        self.assertEqual("dsc_baseline", created["scenario_id"])
        self.assertEqual("draft", created["status"])
        self.assertEqual(request, created["request"])
        self.assertEqual(_canonical_sha256(request), created["request_sha256"])
        self.assertEqual(self.source["id"], created["source_annual_job_id"])
        self.assertEqual(
            self.source_snapshot_sha256, created["source_snapshot_sha256"]
        )
        self.assertEqual("solartac_site", created["analysis_basis"])
        self.assertEqual([self._ensure_receipt()["id"]], created["evidence_receipt_ids"])
        self.assertEqual(
            before + timedelta(days=7), datetime.fromisoformat(created["expires_at"])
        )
        self.assertIsNone(created["validation"])
        self.assertEqual([], created["jobs"])

        reopened = AgentStore(self.db_path, now=self.clock)
        self.assertEqual(
            created,
            reopened.get_decision_scenario(created["scenario_revision_id"]),
        )
        self.assertEqual(
            [created],
            reopened.list_decision_scenarios(
                self.case["id"], include_history=True, include_expired=True
            ),
        )
        event_types = [
            event["event_type"]
            for event in reopened.list_decision_events(self.case["id"])
        ]
        self.assertIn("decision_scenario_created", event_types)

        with self.assertRaises(StoreConflict):
            current = self._refresh_case()
            self.store.create_decision_scenario(
                current["id"],
                expected_case_revision=current["revision"],
                label="Bad hash",
                kind="alternative",
                request=request,
                request_sha256="f" * 64,
                changed_fields=["/assumptions/solaredge_initial_capex_usd"],
                comparison_classification="controlled",
                evidence_receipt_refs=[self._ensure_receipt()["id"]],
                operator_name="Scenario Editor",
            )

    def test_one_baseline_three_alternatives_and_source_basis_contract_are_enforced(
        self,
    ) -> None:
        baseline = self._create_scenario(kind="baseline")
        with self.assertRaises(StoreConflict):
            self._create_scenario(kind="baseline", label="Duplicate baseline")

        with self.assertRaisesRegex(StoreConflict, "source"):
            self._create_scenario(
                kind="alternative",
                label="Cross-source attempt",
                request=self._scenario_request(
                    source_annual_job_id="annual-different-source"
                ),
            )
        with self.assertRaisesRegex(StoreConflict, "basis"):
            self._create_scenario(
                kind="alternative",
                label="Cross-basis attempt",
                request=self._scenario_request(basis="commercial_representative"),
            )

        alternatives = [
            self._create_scenario(
                kind="alternative",
                label=f"Alternative {index}",
                request=self._scenario_request(capex=130_000.0 + index),
            )
            for index in range(1, 4)
        ]
        with self.assertRaises(StoreConflict):
            self._create_scenario(
                kind="alternative",
                label="Alternative 4",
                request=self._scenario_request(capex=140_000.0),
            )

        visible = self.store.list_decision_scenarios(
            self.case["id"], include_history=False, include_expired=False
        )
        self.assertEqual(4, len(visible))
        self.assertEqual(1, sum(row["kind"] == "baseline" for row in visible))
        self.assertEqual(3, sum(row["kind"] == "alternative" for row in visible))
        self.assertEqual(
            {baseline["scenario_id"], *(row["scenario_id"] for row in alternatives)},
            {row["scenario_id"] for row in visible},
        )

        unlocked = self.store.create_decision_case(
            title="Unlocked case",
            question="Can this run without a source lock?",
            operator_name="Alex Operator",
        )
        request = self._scenario_request()
        with self.assertRaisesRegex(InvalidStateTransition, "source.*basis|lock"):
            self.store.create_decision_scenario(
                unlocked["id"],
                expected_case_revision=unlocked["revision"],
                label="No locked source",
                kind="baseline",
                request=request,
                request_sha256=_canonical_sha256(request),
                changed_fields=[],
                comparison_classification="baseline",
                evidence_receipt_refs=[],
                operator_name="Scenario Editor",
            )

    def test_evidence_receipts_must_be_accepted_same_case_and_digest_consistent(
        self,
    ) -> None:
        receipt = self._ensure_receipt()
        self.assertEqual(
            receipt,
            self.store.get_decision_evidence_receipt(receipt["id"]),
        )
        self.assertIsNone(
            self.store.get_decision_evidence_receipt("evr_missing_receipt")
        )
        current = self._refresh_case()
        second_case = self._locked_case("Separate evidence case")
        _second_asset, second_receipt = self._accepted_receipt_for_case(
            second_case, suffix="b"
        )
        with self.assertRaisesRegex(StoreConflict, "evidence.*case|receipt"):
            self._create_scenario(
                kind="baseline", evidence_receipt_ids=[second_receipt["id"]]
            )

        rejected_digest = "c" * 64
        rejected_asset = self.store.create_decision_evidence_asset(
            current["id"],
            original_filename="rejected.pdf",
            display_filename="rejected.pdf",
            media_type="application/pdf",
            sha256=rejected_digest,
            byte_count=50,
            storage_key=f"sha256/cc/{rejected_digest}.pdf",
            evidence_class="project_actual",
            operator_name="Alex Operator",
            candidates=[
                {
                    "field_name": "cost_lines.cost-se-capex.distribution.value",
                    "value": 99.0,
                    "unit": "USD",
                    "confidence": 0.5,
                    "source_location": {"page": 1},
                }
            ],
        )
        rejected = self.store.record_decision_evidence_review(
            rejected_asset["candidates"][0]["id"],
            decision="rejected",
            operator_name="Evidence Reviewer",
        )
        self._refresh_case()
        with self.assertRaises(InvalidStateTransition):
            self._create_scenario(
                kind="baseline", evidence_receipt_ids=[rejected["id"]]
            )

        assert self._receipt_asset is not None
        replacement_digest = "d" * 64
        with closing(sqlite3.connect(self.db_path)) as connection:
            connection.execute(
                "DROP TRIGGER decision_evidence_asset_identity_is_immutable"
            )
            connection.execute(
                "UPDATE decision_evidence_assets SET sha256 = ?, storage_key = ? "
                "WHERE evidence_asset_id = ?",
                (
                    replacement_digest,
                    f"sha256/dd/{replacement_digest}.pdf",
                    self._receipt_asset["id"],
                ),
            )
            connection.commit()
        with self.assertRaisesRegex(StoreConflict, "digest|sha256|receipt"):
            self._create_scenario(
                kind="baseline", evidence_receipt_ids=[receipt["id"]]
            )

    def test_validation_is_hash_bound_and_optimistically_fenced(self) -> None:
        scenario = self._create_scenario(kind="baseline")
        current = self._refresh_case()
        validation = {
            "schema_version": 1,
            "valid": True,
            "field_errors": [],
            "violated_rules": [],
            "closest_supported_alternatives": [],
        }
        with self.assertRaisesRegex(StoreConflict, "revision"):
            self.store.record_decision_scenario_validation(
                scenario["scenario_revision_id"],
                expected_case_revision=current["revision"] - 1,
                expected_revision=scenario["revision"],
                request_sha256=scenario["request_sha256"],
                validation=validation,
                valid=True,
                operator_name="Scenario Validator",
            )
        with self.assertRaises(StoreConflict):
            self.store.record_decision_scenario_validation(
                scenario["scenario_revision_id"],
                expected_case_revision=current["revision"],
                expected_revision=scenario["revision"],
                request_sha256="e" * 64,
                validation=validation,
                valid=True,
                operator_name="Scenario Validator",
            )

        contradictory = {
            "validation_version": "autonomy-scenario-validation-v1",
            "valid": False,
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
        with self.assertRaisesRegex(ValueError, "validation.valid"):
            self.store.record_decision_scenario_validation(
                scenario["scenario_revision_id"],
                expected_case_revision=current["revision"],
                expected_revision=scenario["revision"],
                request_sha256=scenario["request_sha256"],
                validation=contradictory,
                valid=True,
                operator_name="Scenario Validator",
            )

        invalid = self._validate_scenario(scenario, valid=False)
        self.assertEqual("invalid", invalid["status"])
        self.assertFalse(invalid["validation"]["valid"])
        rewritten_validation = {
            **invalid["validation"],
            "violated_rules": ["rewritten-after-validation"],
        }
        with closing(sqlite3.connect(self.db_path)) as connection:
            with self.assertRaisesRegex(
                sqlite3.IntegrityError,
                "validation receipts are immutable",
            ):
                connection.execute(
                    "UPDATE decision_scenarios "
                    "SET validation_json = ?, validation_sha256 = ? "
                    "WHERE scenario_revision_id = ?",
                    (
                        json.dumps(
                            rewritten_validation,
                            allow_nan=False,
                            separators=(",", ":"),
                            sort_keys=True,
                        ),
                        _canonical_sha256(rewritten_validation),
                        invalid["scenario_revision_id"],
                    ),
                )
        retained = self.store.get_decision_scenario(invalid["scenario_revision_id"])
        self.assertIsNotNone(retained)
        assert retained is not None
        self.assertEqual(invalid["validation"], retained["validation"])
        current = self._ensure_case_ready_to_run()
        with self.assertRaises(InvalidStateTransition):
            self.store.confirm_decision_scenarios_batch(
                current["id"],
                [self._confirmation_item(invalid, job_id="tea_invalid")],
                expected_case_revision=current["revision"],
                idempotency_key="invalid-scenario-confirmation",
                operator_name="Alex Operator",
                rationale="This must not execute.",
                acknowledgement="I reviewed the exact invalid request.",
                confirmation_review={"request_hashes": [invalid["request_sha256"]]},
                atomic_source_check=lambda _connection: self.source_snapshot_sha256,
            )

    def test_confirmation_rejects_alternative_bound_to_superseded_baseline(
        self,
    ) -> None:
        baseline = self._validate_scenario(
            self._create_scenario(kind="baseline")
        )
        alternative = self._validate_scenario(
            self._create_scenario(
                kind="alternative",
                request=self._scenario_request(capex=125_000.0),
            )
        )
        current = self._refresh_case()
        replacement_request = self._scenario_request(seed=43)
        replacement = self.store.revise_decision_scenario(
            baseline["scenario_id"],
            expected_case_revision=current["revision"],
            expected_revision=baseline["revision"],
            label="Baseline with a new common seed",
            request=replacement_request,
            request_sha256=_canonical_sha256(replacement_request),
            changed_fields=[],
            comparison_classification="baseline",
            evidence_receipt_refs=baseline["evidence_receipt_ids"],
            operator_name="Scenario Editor",
        )
        replacement = self._validate_scenario(replacement)
        ready = self._ensure_case_ready_to_run()
        confirmations = [
            self._confirmation_item(replacement, job_id="tea_new_baseline"),
            self._confirmation_item(alternative, job_id="tea_stale_alternative"),
        ]
        with self.assertRaisesRegex(StoreConflict, "selected baseline|revalidate"):
            self.store.confirm_decision_scenarios_batch(
                ready["id"],
                confirmations,
                expected_case_revision=ready["revision"],
                idempotency_key="stale-baseline-binding",
                operator_name="Alex Operator",
                rationale="This stale comparison must not execute.",
                acknowledgement="I reviewed both exact requests.",
                confirmation_review={"request_hashes": [
                    item["request_sha256"] for item in confirmations
                ]},
                atomic_source_check=lambda _connection: self.source_snapshot_sha256,
            )
        self.assertIsNone(self.store.get_technoeconomic_job("tea_new_baseline"))
        self.assertIsNone(
            self.store.get_technoeconomic_job("tea_stale_alternative")
        )
        self.assertIsNone(self.store.get_technoeconomic_job("tea_invalid"))

    def test_revisions_preserve_history_and_confirmed_values_are_immutable(
        self,
    ) -> None:
        original = self._validate_scenario(self._create_scenario(kind="baseline"))
        confirmed = self._confirm(
            [original],
            idempotency_key="confirm-before-revision",
            job_ids=["tea_confirmed_revision"],
        )
        confirmed_row = self.store.get_decision_scenario(
            original["scenario_revision_id"]
        )
        self.assertIsNotNone(confirmed_row)
        assert confirmed_row is not None
        self.assertEqual("confirmed", confirmed_row["status"])
        self.assertEqual("tea_confirmed_revision", confirmed_row["jobs"][0]["id"])
        frozen_request = confirmed_row["request"]
        frozen_hash = confirmed_row["request_sha256"]

        revised_request = self._scenario_request(capex=135_000.0)
        current = self._refresh_case()
        revised = self.store.revise_decision_scenario(
            confirmed_row["scenario_id"],
            expected_case_revision=current["revision"],
            expected_revision=confirmed_row["revision"],
            label="Current baseline revision 2",
            request=revised_request,
            request_sha256=_canonical_sha256(revised_request),
            changed_fields=[],
            comparison_classification="baseline",
            evidence_receipt_refs=[self._ensure_receipt()["id"]],
            operator_name="Scenario Editor",
            scenario_revision_id="dscr_confirmed_r2",
        )
        self._refresh_case()

        prior = self.store.get_decision_scenario(
            confirmed_row["scenario_revision_id"]
        )
        self.assertIsNotNone(prior)
        assert prior is not None
        self.assertEqual("confirmed", prior["status"])
        self.assertEqual(frozen_request, prior["request"])
        self.assertEqual(frozen_hash, prior["request_sha256"])
        self.assertEqual(
            revised["scenario_revision_id"], prior["superseded_by_revision_id"]
        )
        self.assertIsNotNone(prior["confirmation_id"])
        self.assertEqual(2, revised["revision"])
        self.assertEqual(prior["scenario_id"], revised["scenario_id"])
        self.assertEqual(
            prior["scenario_revision_id"], revised["parent_revision_id"]
        )
        self.assertEqual("draft", revised["status"])
        self.assertIsNone(revised["confirmation_id"])
        self.assertEqual([], revised["jobs"])

        history = self.store.list_decision_scenarios(
            self.case["id"], include_history=True, include_expired=True
        )
        self.assertEqual([1, 2], sorted(row["revision"] for row in history))
        latest = self.store.list_decision_scenarios(
            self.case["id"], include_history=False, include_expired=True
        )
        self.assertEqual(
            [revised["scenario_revision_id"]],
            [row["scenario_revision_id"] for row in latest],
        )

        with closing(sqlite3.connect(self.db_path)) as connection:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "UPDATE decision_scenarios SET superseded_by_revision_id = ? "
                    "WHERE scenario_revision_id = ?",
                    (
                        prior["scenario_revision_id"],
                        revised["scenario_revision_id"],
                    ),
                )
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "UPDATE decision_scenarios SET request_json = '{}' "
                    "WHERE scenario_revision_id = ?",
                    (prior["scenario_revision_id"],),
                )
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "DELETE FROM decision_scenario_evidence "
                    "WHERE scenario_revision_id = ?",
                    (prior["scenario_revision_id"],),
                )
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "DELETE FROM decision_scenario_jobs WHERE tea_job_id = ?",
                    ("tea_confirmed_revision",),
                )
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "DELETE FROM decision_scenarios WHERE scenario_revision_id = ?",
                    (prior["scenario_revision_id"],),
                )

        with self.assertRaisesRegex(InvalidStateTransition, "case-scoped"):
            self.store.cancel_technoeconomic_job("tea_confirmed_revision")
        current_case = self._refresh_case()
        self.store.cancel_decision_scenario_job(
            current_case["id"],
            "tea_confirmed_revision",
            expected_case_revision=current_case["revision"],
            operator_name="Alex Operator",
            reason="Cancel the retained test attempt.",
        )
        with self.assertRaisesRegex(InvalidStateTransition, "retained|scenario"):
            self.store.delete_technoeconomic_job("tea_confirmed_revision")
        self.assertEqual(
            confirmed["confirmation"]["id"], prior["confirmation_id"]
        )

    def test_expiry_marks_due_unconfirmed_history_and_touches_case_once(self) -> None:
        expires_at = self.clock.value + timedelta(days=7)
        baseline = self._create_scenario(
            kind="baseline", expires_at=expires_at
        )
        alternative = self._create_scenario(
            kind="alternative",
            expires_at=expires_at,
            request=self._scenario_request(capex=132_000.0),
        )
        current_case = self._refresh_case()
        revised_baseline = self.store.revise_decision_scenario(
            baseline["scenario_id"],
            expected_case_revision=current_case["revision"],
            expected_revision=baseline["revision"],
            label="Baseline revision two",
            request=baseline["request"],
            request_sha256=baseline["request_sha256"],
            changed_fields=[],
            comparison_classification="baseline",
            evidence_receipt_refs=baseline["evidence_receipt_ids"],
            operator_name="Scenario Editor",
            expires_at=expires_at,
        )
        before_expiry = self._refresh_case()

        self.clock.advance(days=6, hours=23, minutes=59)
        not_due = self.store.expire_decision_scenario_drafts(
            self.case["id"],
            operator_name="system:scenario-expiry",
            expected_case_revision=before_expiry["revision"],
        )
        self.assertEqual(0, not_due["expired_count"])
        self.assertEqual([], not_due["scenario_revision_ids"])
        self.assertEqual(before_expiry["revision"], self._refresh_case()["revision"])

        self.clock.advance(minutes=1)
        expired = self.store.expire_decision_scenario_drafts(
            self.case["id"],
            operator_name="system:scenario-expiry",
            expected_case_revision=before_expiry["revision"],
        )
        after_expiry = self._refresh_case()
        self.assertEqual(
            {
                baseline["scenario_revision_id"],
                revised_baseline["scenario_revision_id"],
                alternative["scenario_revision_id"],
            },
            set(expired["scenario_revision_ids"]),
        )
        self.assertEqual(3, expired["expired_count"])
        self.assertTrue(
            all(
                self.store.get_decision_scenario(revision_id)["status"] == "expired"
                for revision_id in expired["scenario_revision_ids"]
            )
        )
        self.assertEqual(before_expiry["revision"] + 1, after_expiry["revision"])
        self.assertEqual(
            [],
            self.store.list_decision_scenarios(
                self.case["id"], include_history=False, include_expired=False
            ),
        )
        retained = self.store.list_decision_scenarios(
            self.case["id"], include_history=True, include_expired=True
        )
        self.assertEqual(3, len(retained))
        repeated = self.store.expire_decision_scenario_drafts(
            self.case["id"], operator_name="system:scenario-expiry"
        )
        self.assertEqual(0, repeated["expired_count"])
        event_types = [
            event["event_type"]
            for event in self.store.list_decision_events(self.case["id"])
        ]
        self.assertEqual(1, event_types.count("decision_scenarios_expired"))

    def test_elapsed_drafts_expire_before_validation_or_revision(self) -> None:
        expires_at = self.clock.value + timedelta(days=7)
        baseline = self._create_scenario(kind="baseline", expires_at=expires_at)
        alternative = self._create_scenario(
            kind="alternative",
            request=self._scenario_request(capex=127_000.0),
            expires_at=expires_at,
        )
        self.clock.advance(days=7)
        current = self._refresh_case()
        with self.assertRaisesRegex(InvalidStateTransition, "expired"):
            self.store.record_decision_scenario_validation(
                baseline["scenario_revision_id"],
                expected_case_revision=current["revision"],
                expected_revision=baseline["revision"],
                request_sha256=baseline["request_sha256"],
                validation={},
                valid=False,
                operator_name="Scenario Validator",
            )
        self.assertEqual(
            "expired",
            self.store.get_decision_scenario(baseline["scenario_revision_id"])[
                "status"
            ],
        )
        current = self._refresh_case()
        with self.assertRaisesRegex(InvalidStateTransition, "expired"):
            self.store.revise_decision_scenario(
                alternative["scenario_id"],
                expected_case_revision=current["revision"],
                expected_revision=alternative["revision"],
                label="Too-late revision",
                request=alternative["request"],
                request_sha256=alternative["request_sha256"],
                changed_fields=alternative["changed_fields"],
                comparison_classification=alternative[
                    "comparison_classification"
                ],
                evidence_receipt_refs=alternative["evidence_receipt_ids"],
                operator_name="Scenario Editor",
            )
        self.assertEqual(
            "expired",
            self.store.get_decision_scenario(alternative["scenario_revision_id"])[
                "status"
            ],
        )

    def test_grouped_confirmation_is_atomic_idempotent_and_revision_fenced(
        self,
    ) -> None:
        baseline = self._validate_scenario(self._create_scenario(kind="baseline"))
        alternative = self._validate_scenario(
            self._create_scenario(
                kind="alternative",
                request=self._scenario_request(capex=125_000.0),
            )
        )
        before = self._ensure_case_ready_to_run()
        confirmations = [
            self._confirmation_item(baseline, job_id="tea_atomic_1"),
            self._confirmation_item(alternative, job_id="tea_atomic_2"),
        ]
        review = {
            "schema_version": 1,
            "request_hashes": [row["request_sha256"] for row in confirmations],
        }

        with self.assertRaises(StoreConflict):
            self.store.confirm_decision_scenarios_batch(
                before["id"],
                confirmations,
                expected_case_revision=before["revision"],
                idempotency_key="atomic-capacity-failure",
                operator_name="Alex Operator",
                rationale="Prove all-or-none queue creation.",
                acknowledgement="I confirm both exact requests.",
                confirmation_review=review,
                atomic_source_check=lambda _connection: self.source_snapshot_sha256,
                max_active_jobs=1,
            )
        self.assertEqual(before, self._refresh_case())
        self.assertIsNone(self.store.get_technoeconomic_job("tea_atomic_1"))
        self.assertIsNone(self.store.get_technoeconomic_job("tea_atomic_2"))
        with closing(sqlite3.connect(self.db_path)) as connection:
            self.assertEqual(
                0,
                connection.execute(
                    "SELECT COUNT(*) FROM decision_scenario_confirmations"
                ).fetchone()[0],
            )
            self.assertEqual(
                0,
                connection.execute(
                    "SELECT COUNT(*) FROM decision_scenario_confirmation_items"
                ).fetchone()[0],
            )
            self.assertEqual(
                0,
                connection.execute(
                    "SELECT COUNT(*) FROM decision_scenario_jobs"
                ).fetchone()[0],
            )

        with self.assertRaisesRegex(StoreConflict, "revision"):
            self.store.confirm_decision_scenarios_batch(
                before["id"],
                confirmations,
                expected_case_revision=before["revision"] - 1,
                idempotency_key="stale-confirmation",
                operator_name="Alex Operator",
                rationale="Stale browser must not queue work.",
                acknowledgement="I confirm both exact requests.",
                confirmation_review=review,
                atomic_source_check=lambda _connection: self.source_snapshot_sha256,
            )

        first = self.store.confirm_decision_scenarios_batch(
            before["id"],
            confirmations,
            expected_case_revision=before["revision"],
            idempotency_key="atomic-confirmation-success",
            operator_name="Alex Operator",
            rationale="Execute both exact validated scenarios.",
            acknowledgement="I confirm both exact requests.",
            confirmation_review=review,
            atomic_source_check=lambda _connection: self.source_snapshot_sha256,
            max_active_jobs=4,
        )
        self.assertFalse(first["idempotent_replay"])
        self.assertEqual(2, len(first["items"]))
        self.assertEqual(
            ["tea_atomic_1", "tea_atomic_2"], [job["id"] for job in first["jobs"]]
        )
        self.assertEqual("running", first["case"]["status"])
        self.assertEqual(before["revision"] + 1, first["case"]["revision"])

        replay = self.store.confirm_decision_scenarios_batch(
            before["id"],
            confirmations,
            expected_case_revision=before["revision"],
            idempotency_key="atomic-confirmation-success",
            operator_name="Alex Operator",
            rationale="Execute both exact validated scenarios.",
            acknowledgement="I confirm both exact requests.",
            confirmation_review=review,
            atomic_source_check=lambda _connection: self.source_snapshot_sha256,
            max_active_jobs=4,
        )
        self.assertTrue(replay["idempotent_replay"])
        self.assertEqual(first["confirmation"], replay["confirmation"])
        self.assertEqual(first["jobs"], replay["jobs"])
        self.assertEqual(first["case"], replay["case"])
        with closing(sqlite3.connect(self.db_path)) as connection:
            self.assertEqual(
                2,
                connection.execute(
                    "SELECT COUNT(*) FROM technoeconomic_jobs"
                ).fetchone()[0],
            )

        with self.assertRaisesRegex(StoreConflict, "idempotency"):
            self.store.confirm_decision_scenarios_batch(
                before["id"],
                confirmations,
                expected_case_revision=before["revision"],
                idempotency_key="atomic-confirmation-success",
                operator_name="Alex Operator",
                rationale="A different payload must conflict.",
                acknowledgement="I confirm both exact requests.",
                confirmation_review=review,
                atomic_source_check=lambda _connection: self.source_snapshot_sha256,
                max_active_jobs=4,
            )

    def test_concurrent_confirmations_across_store_instances_have_one_winner(
        self,
    ) -> None:
        baseline = self._validate_scenario(self._create_scenario(kind="baseline"))
        ready = self._ensure_case_ready_to_run()
        barrier = threading.Barrier(2)

        def confirm(index: int) -> tuple[str, str]:
            local_store = AgentStore(self.db_path, now=self.clock)
            item = self._confirmation_item(
                baseline,
                job_id=f"tea_concurrent_confirmation_{index}",
            )
            barrier.wait(timeout=5)
            try:
                result = local_store.confirm_decision_scenarios_batch(
                    ready["id"],
                    [item],
                    expected_case_revision=ready["revision"],
                    idempotency_key=f"concurrent-confirmation-{index}",
                    operator_name=f"Concurrent Operator {index}",
                    rationale="Prove the revision fence has exactly one winner.",
                    acknowledgement="I reviewed the exact request.",
                    confirmation_review={
                        "request_hashes": [item["request_sha256"]]
                    },
                    atomic_source_check=lambda _connection: (
                        self.source_snapshot_sha256
                    ),
                )
            except (InvalidStateTransition, StoreConflict) as exc:
                return "rejected", str(exc)
            return "confirmed", str(result["confirmation"]["id"])

        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(confirm, (1, 2)))
        self.assertEqual(1, sum(state == "confirmed" for state, _ in outcomes))
        self.assertEqual(1, sum(state == "rejected" for state, _ in outcomes))
        jobs = [
            self.store.get_technoeconomic_job(
                f"tea_concurrent_confirmation_{index}"
            )
            for index in (1, 2)
        ]
        self.assertEqual(1, sum(job is not None for job in jobs))
        self.assertEqual("running", self._refresh_case()["status"])

    def test_grouped_confirmation_rejects_mixed_cases_without_partial_jobs(self) -> None:
        baseline = self._validate_scenario(self._create_scenario(kind="baseline"))
        second_case = self._locked_case("Second scenario case")
        _asset, receipt = self._accepted_receipt_for_case(second_case, suffix="b")
        second_case = self._refresh_case(second_case["id"])
        second_request = self._scenario_request(capex=120_000.0)
        second = self.store.create_decision_scenario(
            second_case["id"],
            expected_case_revision=second_case["revision"],
            label="Other case baseline",
            kind="baseline",
            request=second_request,
            request_sha256=_canonical_sha256(second_request),
            changed_fields=[],
            comparison_classification="baseline",
            evidence_receipt_refs=[receipt["id"]],
            operator_name="Scenario Editor",
        )
        second_case = self._refresh_case(second_case["id"])
        second = self.store.record_decision_scenario_validation(
            second["scenario_revision_id"],
            expected_case_revision=second_case["revision"],
            expected_revision=second["revision"],
            request_sha256=second["request_sha256"],
            validation={
                "validation_version": "autonomy-scenario-validation-v1",
                "valid": True,
                "request_sha256": second["request_sha256"],
                "baseline_request_sha256": None,
                "kind": "baseline",
                "comparison_classification": "baseline",
                "changed_fields": [],
                "declared_changed_fields": [],
                "field_errors": [],
                "violated_rules": [],
                "closest_supported_alternatives": [],
            },
            valid=True,
            operator_name="Scenario Validator",
        )
        first_case = self._ensure_case_ready_to_run()
        confirmations = [
            self._confirmation_item(baseline, job_id="tea_mixed_1"),
            self._confirmation_item(second, job_id="tea_mixed_2"),
        ]
        with self.assertRaisesRegex(StoreConflict, "case"):
            self.store.confirm_decision_scenarios_batch(
                first_case["id"],
                confirmations,
                expected_case_revision=first_case["revision"],
                idempotency_key="mixed-case-confirmation",
                operator_name="Alex Operator",
                rationale="This mixed batch must be rejected.",
                acknowledgement="I reviewed both requests.",
                confirmation_review={
                    "request_hashes": [row["request_sha256"] for row in confirmations]
                },
                atomic_source_check=lambda _connection: self.source_snapshot_sha256,
            )
        self.assertIsNone(self.store.get_technoeconomic_job("tea_mixed_1"))
        self.assertIsNone(self.store.get_technoeconomic_job("tea_mixed_2"))

    def test_retry_links_new_frozen_attempt_and_is_idempotent(self) -> None:
        scenario = self._validate_scenario(self._create_scenario(kind="baseline"))
        confirmed = self._confirm(
            [scenario],
            idempotency_key="retry-source-confirmation",
            job_ids=["tea_retry_source"],
        )
        with self.assertRaisesRegex(InvalidStateTransition, "case-scoped"):
            self.store.cancel_technoeconomic_job("tea_retry_source")
        before_cancel = self._refresh_case()
        cancelled = self.store.cancel_decision_scenario_job(
            before_cancel["id"],
            "tea_retry_source",
            expected_case_revision=before_cancel["revision"],
            operator_name="Alex Operator",
            reason="Exercise the audited retry path.",
        )
        source_job = cancelled["link"]["job"]
        self.assertEqual("cancelled", source_job["state"])
        with self.assertRaisesRegex(InvalidStateTransition, "case-scoped"):
            self.store.retry_technoeconomic_job("tea_retry_source")
        before_retry = cancelled["case"]

        retried = self.store.retry_decision_scenario_job(
            before_retry["id"],
            scenario["scenario_revision_id"],
            source_job["id"],
            expected_case_revision=before_retry["revision"],
            operator_name="Alex Operator",
            new_job_id="tea_retry_child",
        )
        self.assertFalse(retried["idempotent_replay"])
        self.assertEqual("tea_retry_child", retried["job"]["id"])
        self.assertEqual("tea_retry_source", retried["job"]["retry_of_job_id"])
        self.assertEqual(source_job["request"], retried["job"]["request"])
        self.assertEqual(
            source_job["source_snapshot"], retried["job"]["source_snapshot"]
        )
        self.assertEqual(
            source_job["source_snapshot_sha256"],
            retried["job"]["source_snapshot_sha256"],
        )
        self.assertEqual(before_retry["revision"] + 1, retried["case"]["revision"])
        linked_ids = [job["id"] for job in retried["scenario"]["jobs"]]
        self.assertEqual(["tea_retry_source", "tea_retry_child"], linked_ids)

        replay = self.store.retry_decision_scenario_job(
            before_retry["id"],
            scenario["scenario_revision_id"],
            source_job["id"],
            expected_case_revision=before_retry["revision"],
            operator_name="Alex Operator",
            new_job_id="tea_ignored_on_idempotent_retry",
        )
        self.assertTrue(replay["idempotent_replay"])
        self.assertEqual(retried["job"], replay["job"])
        self.assertIsNone(
            self.store.get_technoeconomic_job("tea_ignored_on_idempotent_retry")
        )

        with self.assertRaisesRegex(InvalidStateTransition, "retained|scenario"):
            self.store.delete_technoeconomic_job("tea_retry_child")
        with closing(sqlite3.connect(self.db_path)) as connection:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "DELETE FROM decision_scenario_jobs WHERE tea_job_id = ?",
                    ("tea_retry_child",),
                )
        self.assertEqual(
            confirmed["confirmation"]["id"],
            retried["scenario"]["confirmation_id"],
        )

    def test_scenario_retry_uses_existing_worker_and_lost_lease_cannot_overwrite(
        self,
    ) -> None:
        scenario = self._validate_scenario(self._create_scenario(kind="baseline"))
        self._confirm(
            [scenario],
            idempotency_key="lost-lease-confirmation",
            job_ids=["tea_lost_lease_source"],
        )
        claimed = self.store.claim_next_queued_work(worker_id="worker-old")
        self.assertIsNotNone(claimed)
        assert claimed is not None
        self.assertEqual("technoeconomic", claimed["workflow"])
        self.assertEqual("tea_lost_lease_source", claimed["id"])

        self.clock.advance(minutes=10)
        interrupted = self.store.mark_stale_running_technoeconomic_jobs_interrupted(
            before=self.clock.value - timedelta(minutes=1)
        )
        self.assertEqual(1, interrupted)
        current = self._refresh_case()
        retry = self.store.retry_decision_scenario_job(
            current["id"],
            scenario["scenario_revision_id"],
            claimed["id"],
            expected_case_revision=current["revision"],
            operator_name="Alex Operator",
            new_job_id="tea_lost_lease_retry",
        )
        replacement = self.store.claim_next_queued_work(worker_id="worker-new")
        self.assertIsNotNone(replacement)
        assert replacement is not None
        self.assertEqual("technoeconomic", replacement["workflow"])
        self.assertEqual(retry["job"]["id"], replacement["id"])

        with self.assertRaises(LeaseOwnershipLost):
            self.store.update_technoeconomic_job(
                claimed["id"],
                expected_worker_id="worker-old",
                expected_lease_token=claimed["lease_token"],
                state="done",
                progress=100.0,
                stage="Late stale completion",
                result={"must_not_persist": True},
                result_provenance={"must_not_persist": True},
                artifacts={},
            )
        source = self.store.get_technoeconomic_job(claimed["id"])
        self.assertEqual("interrupted", source["state"])
        self.assertIsNone(source["result"])
        self.assertEqual(
            "running",
            self.store.get_technoeconomic_job(replacement["id"])["state"],
        )

    def test_execution_reconciliation_uses_latest_attempt_and_survives_restart(
        self,
    ) -> None:
        baseline = self._validate_scenario(self._create_scenario(kind="baseline"))
        alternative = self._validate_scenario(
            self._create_scenario(
                kind="alternative",
                request=self._scenario_request(capex=125_000.0),
            )
        )
        confirmed = self._confirm(
            [baseline, alternative],
            idempotency_key="execution-reconciliation",
            job_ids=["tea_execution_1", "tea_execution_2"],
        )
        self.assertEqual("running", confirmed["case"]["status"])

        done = self._finish_next_tea(state="done", worker_id="scenario-worker-1")
        partial = self.store.reconcile_decision_case_execution(self.case["id"])
        self.assertEqual("running", partial["case"]["status"])
        self.assertIn(done["id"], [job["id"] for job in partial["jobs"]])

        failed = self._finish_next_tea(state="error", worker_id="scenario-worker-2")
        still_partial = self.store.reconcile_decision_case_execution(self.case["id"])
        self.assertEqual("running", still_partial["case"]["status"])
        self.assertEqual(
            {"done", "error"}, {job["state"] for job in still_partial["jobs"]}
        )

        failed_scenario = next(
            row
            for row in (baseline, alternative)
            if any(
                linked["id"] == failed["id"]
                for linked in self.store.get_decision_scenario(
                    row["scenario_revision_id"]
                )["jobs"]
            )
        )
        before_retry = self._refresh_case()
        retried = self.store.retry_decision_scenario_job(
            before_retry["id"],
            failed_scenario["scenario_revision_id"],
            failed["id"],
            expected_case_revision=before_retry["revision"],
            operator_name="Alex Operator",
            new_job_id="tea_execution_retry",
        )
        queued_latest = self.store.reconcile_decision_case_execution(self.case["id"])
        self.assertEqual("running", queued_latest["case"]["status"])
        self.assertIn("queued", {job["state"] for job in queued_latest["jobs"]})
        self.assertEqual("tea_execution_retry", retried["job"]["id"])

        self._finish_next_tea(state="done", worker_id="scenario-worker-3")
        reopened = AgentStore(self.db_path, now=self.clock)
        ready = reopened.reconcile_decision_case_execution(self.case["id"])
        self.assertEqual("results_ready", ready["case"]["status"])
        self.assertEqual(
            {"done", "error"}, {job["state"] for job in ready["jobs"]}
        )
        revision = ready["case"]["revision"]
        repeated = reopened.reconcile_decision_case_execution(self.case["id"])
        self.assertEqual("results_ready", repeated["case"]["status"])
        self.assertEqual(revision, repeated["case"]["revision"])
        event_types = [
            event["event_type"]
            for event in reopened.list_decision_events(self.case["id"])
        ]
        self.assertEqual(1, event_types.count("decision_case_results_ready"))

    def test_unknown_scenario_records_fail_without_mutation(self) -> None:
        before = self._refresh_case()
        self.assertIsNone(self.store.get_decision_scenario("dscr_missing"))
        self.assertEqual(before, self._refresh_case())


if __name__ == "__main__":
    unittest.main()
