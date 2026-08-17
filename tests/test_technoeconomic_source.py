from __future__ import annotations

from copy import deepcopy
import hashlib
from pathlib import Path
import unittest
from unittest.mock import patch
from uuid import uuid4

from sbepv import calibration, model
from sbepv.api import config
from sbepv.api import technoeconomic as tea_api
from sbepv.store import AgentStore, StoreConflict


class TechnoeconomicAnnualSourceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.token = uuid4().hex
        self.root = Path(__file__).resolve().parents[1]
        self.output = self.root / "outputs"
        self.output.mkdir(exist_ok=True)
        self.private_sources = self.output / ".annual_sources"
        self.private_sources.mkdir(exist_ok=True)
        self.cleanup_files: set[Path] = set()
        self.cleanup_dirs: set[Path] = set()
        self.addCleanup(self._cleanup_fixture_files)
        self.config_patches = (
            patch.object(config, "OUTPUT_DIR", self.output),
            patch.object(
                config,
                "ANNUAL_SOURCE_ARTIFACT_DIR",
                self.private_sources,
            ),
        )
        for config_patch in self.config_patches:
            config_patch.start()
            self.addCleanup(config_patch.stop)
        database_path = self.output / f"tea-source-test-{self.token}.sqlite3"
        self.cleanup_files.update(
            {
                database_path,
                Path(f"{database_path}-shm"),
                Path(f"{database_path}-wal"),
            }
        )
        self.store = AgentStore(database_path)

    def _cleanup_fixture_files(self) -> None:
        for path in self.cleanup_files:
            if path.is_file():
                path.chmod(0o666)
                path.unlink(missing_ok=True)
        for path in sorted(self.cleanup_dirs, key=lambda item: len(item.parts), reverse=True):
            try:
                path.rmdir()
            except (FileNotFoundError, OSError):
                # A shared hash-prefix directory may contain another test/source.
                pass

    @staticmethod
    def _sha(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    @staticmethod
    def _profile(
        origin_job_id: str,
        review_id: str,
        source_hash: str,
    ) -> dict:
        return {
            "schema_version": calibration.CALIBRATION_PROFILE_SCHEMA_VERSION,
            "origin_job_id": origin_job_id,
            "origin_source_sha256": source_hash,
            "origin_review_id": review_id,
            "calibration_physics_version": model.CALIBRATION_PHYSICS_VERSION,
            "calibration_physics_fingerprint": (
                model.CALIBRATION_PHYSICS_FINGERPRINT
            ),
            "solectria_physics_version": model.SOLECTRIA_PHYSICS_VERSION,
            "solectria_physics_fingerprint": (
                model.SOLECTRIA_PHYSICS_FINGERPRINT
            ),
            "seasonal_factors": {
                season: {"solaredge": 1.01, "solectria": 0.99}
                for season in ("winter", "spring", "summer", "fall")
            },
            "fit_metadata": {"method": "fixture-reviewed-fit"},
            "factor_driver_diagnostics": {"systems": {}},
        }

    def _create_dependencies(
        self,
        *,
        explicit_capacity: bool = True,
        explicit_artifact: bool = True,
    ) -> tuple[dict, dict, dict]:
        origin_id = "validation-origin"
        review_id = "review-validation-origin"
        origin_source = self.output / f"validation-reviewed-{self.token}.csv"
        origin_source.write_text(
            f"timestamp,value\n2024-01-01,{self.token}\n",
            encoding="utf-8",
        )
        self.cleanup_files.add(origin_source)
        origin_hash = self._sha(origin_source)
        profile = self._profile(origin_id, review_id, origin_hash)
        quality = {
            "review_id": review_id,
            "source_sha256": origin_hash,
            "reviewed_source_sha256": origin_hash,
            "reviewed_at": "2026-08-01T12:00:00+00:00",
            "submitted_decisions": {},
            "report": {
                "version": 1,
                "source": {
                    "row_count": 1,
                    "expected_interval_seconds": 3_600,
                    "requested_start": "2024-01-01T07:00:00+00:00",
                    "requested_end": "2025-01-01T07:00:00+00:00",
                    "first_timestamp": "2024-01-01T07:00:00+00:00",
                    "last_timestamp": "2024-01-01T07:00:00+00:00",
                },
                "summary": {
                    "status": "clean",
                    "blocking": False,
                    "issue_count": 0,
                    "actionable_issue_count": 0,
                    "affected_rows": 0,
                    "affected_row_pct": 0.0,
                    "missing_intervals": 0,
                    "severity_counts": {
                        "critical": 0,
                        "high": 0,
                        "medium": 0,
                        "low": 0,
                    },
                },
                "seasons": [
                    {
                        "name": "winter",
                        "months": "Dec-Feb",
                        "row_count": 1,
                        "first_timestamp": "2024-01-01T07:00:00+00:00",
                        "last_timestamp": "2024-01-01T07:00:00+00:00",
                    }
                ],
                "issues": [],
            },
            "cleaning": {
                "original_rows": 1,
                "final_rows": 1,
                "excluded_rows": 0,
                "excluded_row_pct": 0.0,
                "retained_issue_ids": [],
                "excluded_issue_ids": [],
                "decisions": [],
            },
        }
        self.store.create_job(
            job_id=origin_id,
            kind="baseline",
            mode="validation",
            request={
                "from_date": "2024-01-01",
                "from_time": "00:00",
                "to_date": "2025-01-01",
                "to_time": "00:00",
                "interval_value": 1,
                "interval_unit": "hours",
            },
            source_path=str(origin_source),
            source_hash=origin_hash,
            provenance={
                "data_quality": quality,
                "calibration_profile": profile,
            },
        )
        claimed = self.store.claim_next_queued_job()
        self.assertEqual(origin_id, claimed["id"])
        origin = self.store.update_job(
            origin_id,
            state="done",
            result={
                "mode": "validation",
                "stats": {
                    "calibration_factors": profile["fit_metadata"],
                    "factor_driver_diagnostics": profile[
                        "factor_driver_diagnostics"
                    ],
                },
                "calibration_factors": profile["fit_metadata"],
                "factor_driver_diagnostics": profile[
                    "factor_driver_diagnostics"
                ],
            },
        )
        self.store.promote_job(origin_id)
        promotion = self.store.list_promotions(mode="validation", limit=1)[0]

        annual_id = "annual-source"
        annual_source = self.output / f"annual-midc-{self.token}.csv"
        annual_source.write_text(
            "timestamp,dni,ghi,dhi,temp_air,wind_speed,fixture\n"
            f"2024-01-01,1,1,1,20,2,{self.token}\n",
            encoding="utf-8",
        )
        self.cleanup_files.add(annual_source)
        annual_hash = self._sha(annual_source)
        profile_hash = tea_api.canonical_json_sha256(profile)
        application = {
            "baseline_job_id": origin_id,
            "baseline_review_id": review_id,
            "baseline_promoted_at": promotion["promoted_at"],
            "server_timestamp": "2026-08-02T12:00:00+00:00",
            "origin_profile_sha256": profile_hash,
            "resolved_profile_sha256": profile_hash,
            "origin_profile": profile,
            "resolved_profile": profile,
            "required_seasons": ["winter", "spring", "summer", "fall"],
            "seasonal_substitution": None,
            "settings_deltas": [],
            "server_confirmation": None,
        }
        stats_application = {
            key: deepcopy(value)
            for key, value in application.items()
            if key not in {"origin_profile", "resolved_profile"}
        }
        result_application = deepcopy(stats_application)
        result_application.update(
            {
                "applied": True,
                "method": "frozen_baseline_seasonal_factors",
                "seasonal_factors": profile["seasonal_factors"],
            }
        )
        expected = 366 * 24
        row = {
            "year": 2024,
            "period_start": "2024-01-01",
            "period_end": "2024-12-31",
            "row_count": expected,
            "coverage_status": "complete",
            "complete_calendar_year": True,
            "source_expected_interval_count": expected,
            "source_covered_interval_count": expected,
            "source_coverage_pct": 100.0,
            "annual_expected_interval_count": expected,
            "annual_coverage_pct": 100.0,
            "source_complete": True,
            "cdf_eligible": True,
            "sol_predicted_kwh": 200_000.0,
            "se_predicted_kwh": 215_000.0,
            "combined_predicted_kwh": 415_000.0,
        }
        period = {
            key: deepcopy(value)
            for key, value in row.items()
            if key
            not in {
                "row_count",
                "sol_predicted_kwh",
                "se_predicted_kwh",
                "combined_predicted_kwh",
            }
        }
        source_quality = {
            "interval_seconds": 3_600,
            "periods": [period],
            "unavailable_interval_count": 0,
        }
        audit = {
            "schema_version": 2,
            "source_sha256": annual_hash,
            "interval_seconds": 3_600,
            "source_quality": source_quality,
            "warnings": [],
        }
        stats = {
            "mode": "annual",
            "model_version": model.__version__,
            "calibration_enabled": True,
            "calibration_kind": "frozen_profile",
            "calibration_application": stats_application,
            "calibration_physics_version": model.CALIBRATION_PHYSICS_VERSION,
            "calibration_physics_fingerprint": (
                model.CALIBRATION_PHYSICS_FINGERPRINT
            ),
            "solectria_physics_version": model.SOLECTRIA_PHYSICS_VERSION,
            "solectria_physics_fingerprint": (
                model.SOLECTRIA_PHYSICS_FINGERPRINT
            ),
            "annual_temporal_semantics_version": (
                model.ANNUAL_TEMPORAL_SEMANTICS_VERSION
            ),
            "annual_temporal_semantics_fingerprint": (
                model.ANNUAL_TEMPORAL_SEMANTICS_FINGERPRINT
            ),
            "annual_energy_by_year": [row],
        }
        result = {
            "mode": "annual",
            "stats": stats,
            "annual_energy_by_year": [row],
            "calibration_application": result_application,
            "source_quality": source_quality,
            "window": {
                "from": "2024-01-01",
                "to": "2024-12-31",
                "interval_seconds": 3_600,
                "periods": [period],
            },
        }
        provenance = {
            "annual_source_audit": audit,
            "calibration_profile": profile,
            "calibration_application": application,
        }
        if explicit_capacity:
            capacity = model.capacity_manifest()
            result["capacity_manifest"] = deepcopy(capacity)
            stats["capacity_manifest"] = deepcopy(capacity)
            provenance["capacity_manifest"] = deepcopy(capacity)
        if explicit_artifact:
            artifact = tea_api.harden_annual_source_artifact(
                annual_source,
                annual_hash,
                annual_job_id=annual_id,
            )
            artifact_path = self.private_sources / Path(artifact["storage_key"])
            self.cleanup_files.add(artifact_path)
            self.cleanup_dirs.add(artifact_path.parent)
            result["annual_source_artifact"] = deepcopy(artifact)
            provenance["annual_source_artifact"] = deepcopy(artifact)

        self.store.create_job(
            job_id=annual_id,
            kind="manual",
            mode="annual",
            request={
                "from_date": "2024-01-01",
                "to_date": "2024-12-31",
                "years": [2024],
                "interval_value": 1,
                "interval_unit": "hours",
            },
            source_path=str(annual_source),
            source_hash=annual_hash,
            provenance=provenance,
        )
        claimed = self.store.claim_next_queued_job()
        self.assertEqual(annual_id, claimed["id"])
        annual = self.store.update_job(
            annual_id,
            state="done",
            result=result,
            provenance=provenance,
        )
        return annual, origin, promotion

    def _snapshot(self, **kwargs):
        annual, origin, promotion = self._create_dependencies(**kwargs)
        envelope = tea_api.build_annual_source_snapshot(
            annual,
            origin_validation_job=origin,
            promotion_record=promotion,
        )
        return envelope, annual, origin, promotion

    def test_capacity_manifest_is_explicit_hashed_and_separate(self) -> None:
        calibration_fingerprint = model.CALIBRATION_PHYSICS_FINGERPRINT

        manifest = model.capacity_manifest()

        self.assertEqual(calibration_fingerprint, model.CALIBRATION_PHYSICS_FINGERPRINT)
        self.assertEqual("module_dc_nameplate_at_stc", manifest["rating_basis"])
        self.assertEqual(
            tea_api.canonical_json_sha256(
                {
                    key: value
                    for key, value in manifest.items()
                    if key != "capacity_manifest_sha256"
                }
            ),
            manifest["capacity_manifest_sha256"],
        )
        for system in ("solectria", "solaredge"):
            self.assertEqual(240, manifest["systems"][system]["module_count"])
            self.assertEqual(
                139_180.8,
                manifest["systems"][system]["installed_wdc"],
            )

    def test_eligibility_projection_exposes_only_verified_yearly_energy(self) -> None:
        _, annual, origin, promotion = self._snapshot()

        eligibility = tea_api.inspect_annual_source_eligibility(
            annual,
            origin_validation_job=origin,
            promotion_record=promotion,
        )

        self.assertEqual([2024], eligibility["eligible_years"])
        self.assertEqual(
            [
                {
                    "year": 2024,
                    "solectria_kwh": 200_000.0,
                    "solaredge_kwh": 215_000.0,
                }
            ],
            eligibility["annual_energy_by_year"],
        )
        self.assertEqual(
            {"year", "solectria_kwh", "solaredge_kwh"},
            set(eligibility["annual_energy_by_year"][0]),
        )

    def test_explicit_snapshot_hash_and_store_integration_match(self) -> None:
        envelope, _, _, _ = self._snapshot()
        payload = envelope["source_snapshot"]

        self.assertEqual(
            tea_api.canonical_json_sha256(payload),
            envelope["source_snapshot_sha256"],
        )
        self.assertEqual(
            "explicit_annual_manifest",
            payload["capacity_manifest_source"],
        )
        self.assertEqual(
            "explicit_annual_artifact",
            payload["midc_source_artifact_origin"],
        )
        source_fields = tea_api.technoeconomic_source_store_fields(envelope)
        created = self.store.create_technoeconomic_job(
            job_id="tea_source_snapshot",
            request={"n": 16, "seed": 42},
            submission_provenance={"schema_version": 1},
            **source_fields,
        )

        self.assertEqual(payload, created["source_snapshot"])
        self.assertEqual(
            envelope["source_snapshot_sha256"],
            created["source_snapshot_sha256"],
        )
        artifact = payload["midc_source_artifact"]
        self.assertEqual(artifact["storage_key"], created["source_artifact_storage_key"])
        self.assertEqual(artifact["sha256"], created["source_artifact_sha256"])
        self.assertEqual(artifact["byte_count"], created["source_artifact_bytes"])

    def test_atomic_recheck_rejects_changed_annual_provenance(self) -> None:
        envelope, annual, _, _ = self._snapshot()
        changed = deepcopy(annual["provenance"])
        changed["calibration_application"]["server_timestamp"] = (
            "2026-08-03T00:00:00+00:00"
        )
        self.store.update_job(annual["id"], provenance=changed)

        with self.assertRaises(StoreConflict):
            self.store.create_technoeconomic_job(
                job_id="tea_stale_source",
                request={"n": 16, "seed": 42},
                submission_provenance={"schema_version": 1},
                **tea_api.technoeconomic_source_store_fields(envelope),
            )

    def test_atomic_recheck_is_bound_to_exact_persisted_snapshot(self) -> None:
        envelope, _, _, _ = self._snapshot()
        source_fields = tea_api.technoeconomic_source_store_fields(envelope)
        source_fields["source_snapshot"]["eligible_paired_energy_rows"][0][
            "se_predicted_kwh"
        ] = 999_999.0

        with self.assertRaisesRegex(StoreConflict, "does not match"):
            self.store.create_technoeconomic_job(
                job_id="tea_mutated_snapshot",
                request={"n": 16, "seed": 42},
                submission_provenance={"schema_version": 1},
                **source_fields,
            )

        self.assertIsNone(
            self.store.get_technoeconomic_job("tea_mutated_snapshot")
        )

    def test_review_source_hash_tampering_is_rejected(self) -> None:
        annual, origin, promotion = self._create_dependencies()
        tampered = deepcopy(origin)
        tampered["provenance"]["data_quality"]["reviewed_source_sha256"] = "0" * 64

        with self.assertRaises(tea_api.AnnualSourceValidationError) as raised:
            tea_api.build_annual_source_snapshot(
                annual,
                origin_validation_job=tampered,
                promotion_record=promotion,
            )

        self.assertEqual("origin_review_source_mismatch", raised.exception.code)

    def test_incomplete_review_receipt_is_rejected(self) -> None:
        annual, origin, promotion = self._create_dependencies()
        required_fields = (
            "source_sha256",
            "reviewed_at",
            "submitted_decisions",
            "report",
            "cleaning",
        )
        for field in required_fields:
            with self.subTest(field=field):
                tampered = deepcopy(origin)
                tampered["provenance"]["data_quality"].pop(field)

                with self.assertRaises(
                    tea_api.AnnualSourceValidationError
                ) as raised:
                    tea_api.build_annual_source_snapshot(
                        annual,
                        origin_validation_job=tampered,
                        promotion_record=promotion,
                    )

                self.assertEqual("origin_review_incomplete", raised.exception.code)

    def test_incomplete_or_inconsistent_review_report_is_rejected(self) -> None:
        annual, origin, promotion = self._create_dependencies()
        mutations = {
            "empty_source": lambda report: report.__setitem__("source", {}),
            "empty_summary": lambda report: report.__setitem__("summary", {}),
            "unsupported_version": lambda report: report.__setitem__(
                "version", calibration.REPORT_VERSION + 1
            ),
            "wrong_issue_count": lambda report: report["summary"].__setitem__(
                "issue_count", 1
            ),
            "wrong_status": lambda report: report["summary"].__setitem__(
                "status", "action_required"
            ),
            "invalid_timestamp": lambda report: report["source"].__setitem__(
                "first_timestamp", "not-a-timestamp"
            ),
            "request_interval_mismatch": lambda report: report["source"].__setitem__(
                "expected_interval_seconds", 7_200
            ),
        }
        for case, mutate in mutations.items():
            with self.subTest(case=case):
                tampered = deepcopy(origin)
                report = tampered["provenance"]["data_quality"]["report"]
                mutate(report)

                with self.assertRaises(
                    tea_api.AnnualSourceValidationError
                ) as raised:
                    tea_api.build_annual_source_snapshot(
                        annual,
                        origin_validation_job=tampered,
                        promotion_record=promotion,
                    )

                self.assertIn(
                    raised.exception.code,
                    {
                        "origin_review_incomplete",
                        "origin_review_report_invalid",
                        "origin_review_request_mismatch",
                    },
                )

    def test_review_decisions_must_exactly_match_report_and_cleaning(self) -> None:
        annual, origin, promotion = self._create_dependencies()

        def install_issue(
            target: dict,
            *,
            allowed_actions: list[str],
            cleaning_action: str,
            cleaning_affected_rows: int,
        ) -> None:
            quality = target["provenance"]["data_quality"]
            issue = {
                "id": "quality.test_issue",
                "category": "missing_value",
                "severity": "medium",
                "title": "Test issue",
                "description": "Synthetic provenance consistency issue.",
                "row_count": 1,
                "columns": ["dni"],
                "allowed_actions": allowed_actions,
                "recommended_action": allowed_actions[-1],
                "evidence": {},
                "affected_rows_available": True,
            }
            quality["report"]["issues"] = [issue]
            quality["report"]["summary"].update(
                {
                    "status": "action_required",
                    "blocking": False,
                    "issue_count": 1,
                    "actionable_issue_count": (
                        1 if len(allowed_actions) > 1 else 0
                    ),
                    "affected_rows": 1,
                    "affected_row_pct": 100.0,
                    "missing_intervals": 0,
                    "severity_counts": {
                        "critical": 0,
                        "high": 0,
                        "medium": 1,
                        "low": 0,
                    },
                }
            )
            quality["cleaning"].update(
                {
                    "retained_issue_ids": (
                        [issue["id"]] if cleaning_action == "retain" else []
                    ),
                    "excluded_issue_ids": (
                        [issue["id"]] if cleaning_action == "exclude" else []
                    ),
                    "decisions": [
                        {
                            "issue_id": issue["id"],
                            "action": cleaning_action,
                            "affected_rows": cleaning_affected_rows,
                        }
                    ],
                }
            )

        missing_submission = deepcopy(origin)
        install_issue(
            missing_submission,
            allowed_actions=["retain", "exclude"],
            cleaning_action="retain",
            cleaning_affected_rows=1,
        )
        with self.assertRaises(tea_api.AnnualSourceValidationError) as raised:
            tea_api.build_annual_source_snapshot(
                annual,
                origin_validation_job=missing_submission,
                promotion_record=promotion,
            )
        self.assertEqual("origin_review_decisions_invalid", raised.exception.code)

        contradictory_cleaning = deepcopy(origin)
        install_issue(
            contradictory_cleaning,
            allowed_actions=["exclude"],
            cleaning_action="retain",
            cleaning_affected_rows=0,
        )
        with self.assertRaises(tea_api.AnnualSourceValidationError) as raised:
            tea_api.build_annual_source_snapshot(
                annual,
                origin_validation_job=contradictory_cleaning,
                promotion_record=promotion,
            )
        self.assertEqual("origin_review_cleaning_invalid", raised.exception.code)

    def test_production_quality_report_shape_is_accepted(self) -> None:
        raw_source = self.output / f"quality-raw-{self.token}.csv"
        reviewed_source = self.output / f"quality-reviewed-{self.token}.csv"
        raw_source.write_text(
            "timestamp,solaredge_measured_power,solectria_measured_power,"
            "dni,ghi,dhi,temp_air,wind_speed\n"
            "2024-01-01 00:00:00,50000,45000,500,400,100,20,2\n"
            "2024-01-01 01:00:00,51000,45900,505,404,101,20.2,2.1\n",
            encoding="utf-8",
        )
        self.cleanup_files.update({raw_source, reviewed_source})
        report = calibration.inspect_historian_csv(
            raw_source,
            expected_interval_seconds=3_600,
            requested_start="2024-01-01T00:00:00Z",
            requested_end="2024-01-01T02:00:00Z",
        )
        self.assertIs(report["summary"]["blocking"], False)
        decisions = {
            str(issue["id"]): str(issue["recommended_action"])
            for issue in report["issues"]
            if len(issue.get("allowed_actions") or []) > 1
        }
        cleaning = calibration.apply_quality_decisions(
            raw_source,
            reviewed_source,
            report,
            decisions,
        )
        quality = {
            "review_id": "review-production-shape",
            "source_sha256": self._sha(raw_source),
            "reviewed_source_sha256": self._sha(reviewed_source),
            "reviewed_at": "2026-08-01T12:00:00+00:00",
            "submitted_decisions": decisions,
            "report": calibration.public_quality_report(report),
            "cleaning": cleaning,
        }

        validated = tea_api._validated_review_quality(
            quality,
            review_id="review-production-shape",
            reviewed_source_sha256=quality["reviewed_source_sha256"],
            origin_request={
                "from_date": "2023-12-31",
                "from_time": "17:00",
                "to_date": "2023-12-31",
                "to_time": "19:00",
                "interval_value": 1,
                "interval_unit": "hours",
            },
        )

        self.assertEqual(quality, validated)

    def test_calibration_application_copies_must_match_durable_provenance(self) -> None:
        annual, origin, promotion = self._create_dependencies()
        for location in ("stats", "result"):
            with self.subTest(location=location):
                tampered = deepcopy(annual)
                target = (
                    tampered["result"]["stats"]["calibration_application"]
                    if location == "stats"
                    else tampered["result"]["calibration_application"]
                )
                target["settings_deltas"] = [{"field": "forged"}]

                with self.assertRaises(tea_api.AnnualSourceValidationError) as raised:
                    tea_api.build_annual_source_snapshot(
                        tampered,
                        origin_validation_job=origin,
                        promotion_record=promotion,
                    )

                self.assertEqual(
                    "calibration_application_mismatch",
                    raised.exception.code,
                )

    def test_physics_only_annual_is_rejected(self) -> None:
        annual, origin, promotion = self._create_dependencies()
        annual["result"]["stats"]["calibration_enabled"] = False

        with self.assertRaises(tea_api.AnnualSourceValidationError) as raised:
            tea_api.build_annual_source_snapshot(
                annual,
                origin_validation_job=origin,
                promotion_record=promotion,
            )

        self.assertEqual("annual_not_calibrated", raised.exception.code)

    def test_obsolete_temporal_semantics_are_rejected(self) -> None:
        annual, origin, promotion = self._create_dependencies()
        annual["result"]["stats"]["annual_temporal_semantics_version"] = "legacy"

        with self.assertRaises(tea_api.AnnualSourceValidationError) as raised:
            tea_api.build_annual_source_snapshot(
                annual,
                origin_validation_job=origin,
                promotion_record=promotion,
            )

        self.assertEqual("annual_temporal_semantics_obsolete", raised.exception.code)

    def test_unresolved_and_mismatched_promotions_are_rejected(self) -> None:
        annual, origin, promotion = self._create_dependencies()

        with self.assertRaises(tea_api.AnnualSourceValidationError) as unresolved:
            tea_api.build_annual_source_snapshot(
                annual,
                origin_validation_job=origin,
                promotion_record=None,
            )
        self.assertEqual("origin_promotion_missing", unresolved.exception.code)

        mismatched_promotion = deepcopy(promotion)
        mismatched_promotion["promoted_at"] = "2026-08-04T00:00:00+00:00"
        with self.assertRaises(tea_api.AnnualSourceValidationError) as mismatched:
            tea_api.build_annual_source_snapshot(
                annual,
                origin_validation_job=origin,
                promotion_record=mismatched_promotion,
            )
        self.assertEqual("origin_promotion_mismatch", mismatched.exception.code)

    def test_original_midc_byte_tampering_is_rejected(self) -> None:
        annual, origin, promotion = self._create_dependencies()
        Path(annual["source_path"]).write_bytes(b"tampered original MIDC bytes")

        with self.assertRaises(tea_api.AnnualSourceValidationError) as raised:
            tea_api.build_annual_source_snapshot(
                annual,
                origin_validation_job=origin,
                promotion_record=promotion,
            )

        self.assertEqual("annual_midc_source_unverifiable", raised.exception.code)

    def test_paired_energy_copy_tampering_is_rejected(self) -> None:
        annual, origin, promotion = self._create_dependencies()
        annual["result"]["annual_energy_by_year"][0]["se_predicted_kwh"] += 1

        with self.assertRaises(tea_api.AnnualSourceValidationError) as raised:
            tea_api.build_annual_source_snapshot(
                annual,
                origin_validation_job=origin,
                promotion_record=promotion,
            )

        self.assertEqual("annual_rows_mismatch", raised.exception.code)

    def test_paired_rows_preserve_eligible_and_excluded_years(self) -> None:
        annual, origin, promotion = self._create_dependencies()
        result = annual["result"]
        excluded = deepcopy(result["annual_energy_by_year"][0])
        excluded.update(
            {
                "year": 2023,
                "period_start": "2023-01-01",
                "period_end": "2023-12-31",
                "row_count": 365 * 24 - 1,
                "source_expected_interval_count": 365 * 24,
                "source_covered_interval_count": 365 * 24 - 1,
                "source_coverage_pct": 99.99,
                "annual_expected_interval_count": 365 * 24,
                "annual_coverage_pct": 100.0,
                "source_complete": False,
                "cdf_eligible": False,
            }
        )
        excluded_period = {
            key: deepcopy(value)
            for key, value in excluded.items()
            if key
            not in {
                "row_count",
                "sol_predicted_kwh",
                "se_predicted_kwh",
                "combined_predicted_kwh",
            }
        }
        result["annual_energy_by_year"].append(deepcopy(excluded))
        result["stats"]["annual_energy_by_year"].append(deepcopy(excluded))
        result["source_quality"]["periods"].append(deepcopy(excluded_period))
        result["window"]["periods"].append(deepcopy(excluded_period))
        annual["provenance"]["annual_source_audit"]["source_quality"][
            "periods"
        ].append(deepcopy(excluded_period))

        envelope = tea_api.build_annual_source_snapshot(
            annual,
            origin_validation_job=origin,
            promotion_record=promotion,
        )

        payload = envelope["source_snapshot"]
        self.assertEqual(
            [2024],
            [row["year"] for row in payload["eligible_paired_energy_rows"]],
        )
        self.assertEqual(2023, payload["excluded_annual_energy_rows"][0]["row"]["year"])
        self.assertEqual(
            ["source_incomplete", "cdf_ineligible"],
            payload["excluded_annual_energy_rows"][0]["reasons"],
        )

    def test_no_eligible_paired_year_fails_closed(self) -> None:
        annual, origin, promotion = self._create_dependencies()
        result = annual["result"]
        result["annual_energy_by_year"][0]["cdf_eligible"] = False
        result["stats"]["annual_energy_by_year"][0]["cdf_eligible"] = False
        result["source_quality"]["periods"][0]["cdf_eligible"] = False
        result["window"]["periods"][0]["cdf_eligible"] = False
        annual["provenance"]["annual_source_audit"]["source_quality"]["periods"][
            0
        ]["cdf_eligible"] = False

        with self.assertRaises(tea_api.AnnualSourceValidationError) as raised:
            tea_api.build_annual_source_snapshot(
                annual,
                origin_validation_job=origin,
                promotion_record=promotion,
            )

        self.assertEqual("no_eligible_annual_years", raised.exception.code)

    def test_legacy_capacity_requires_exact_current_fingerprint(self) -> None:
        annual, origin, promotion = self._create_dependencies(explicit_capacity=False)

        envelope = tea_api.build_annual_source_snapshot(
            annual,
            origin_validation_job=origin,
            promotion_record=promotion,
        )
        self.assertEqual(
            "legacy_exact_current_physics_fingerprint_reconstruction",
            envelope["source_snapshot"]["capacity_manifest_source"],
        )

        with self.assertRaises(tea_api.AnnualSourceValidationError) as disallowed:
            tea_api.build_annual_source_snapshot(
                annual,
                origin_validation_job=origin,
                promotion_record=promotion,
                allow_legacy_capacity=False,
            )
        self.assertEqual("legacy_capacity_manifest_disallowed", disallowed.exception.code)

        annual["result"]["stats"]["calibration_physics_fingerprint"] = "0" * 64
        with self.assertRaises(tea_api.AnnualSourceValidationError) as mismatched:
            tea_api.build_annual_source_snapshot(
                annual,
                origin_validation_job=origin,
                promotion_record=promotion,
            )
        self.assertEqual(
            "legacy_capacity_fingerprint_mismatch",
            mismatched.exception.code,
        )

    def test_hardened_artifact_byte_tampering_is_rejected(self) -> None:
        annual, origin, promotion = self._create_dependencies()
        identity = annual["result"]["annual_source_artifact"]
        artifact_path = self.private_sources / Path(identity["storage_key"])
        artifact_path.write_bytes(b"tampered")

        with self.assertRaises(tea_api.AnnualSourceValidationError) as raised:
            tea_api.build_annual_source_snapshot(
                annual,
                origin_validation_job=origin,
                promotion_record=promotion,
            )

        self.assertIn(
            raised.exception.code,
            {
                "annual_source_artifact_size_mismatch",
                "annual_source_artifact_unverifiable",
            },
        )


if __name__ == "__main__":
    unittest.main()
