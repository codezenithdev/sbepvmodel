from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import unittest
import uuid
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from sbepv.api import config, state
from sbepv.api import main as app
from sbepv.api import technoeconomic as tea_api
from sbepv.api.artifacts import (
    _delete_technoeconomic_attempt_artifacts,
    _technoeconomic_attempt_directory,
)
from sbepv.worker import loop as worker_loop
from tests.test_technoeconomic_api import _applied_site_request_payload
from tests import test_technoeconomic_source as source_fixtures


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class TechnoeconomicPhase3IntegrationTests(unittest.TestCase):
    """Exercise Phase 3 wiring that unit-level route mocks cannot cover."""

    def setUp(self) -> None:
        # Reuse the complete Phase 2 Annual/calibration/review/promotion fixture so
        # these tests traverse the production verifier rather than a reduced copy.
        self.source_fixture = source_fixtures.TechnoeconomicAnnualSourceTests(
            methodName="runTest"
        )
        self.source_fixture.setUp()
        self.addCleanup(self.source_fixture.doCleanups)
        self.store = self.source_fixture.store
        self.annual, self.origin, self.promotion = (
            self.source_fixture._create_dependencies()
        )

        self.original_store = state.AGENT_STORE
        self.original_wake = state._WORKER_WAKE
        state.AGENT_STORE = self.store
        state._WORKER_WAKE = Mock()
        state.JOBS.clear()
        self.addCleanup(self._restore_state)

        self.client = TestClient(app.app)
        self.addCleanup(self.client.close)
        self.auth_patch = patch.dict(
            os.environ,
            {
                "DASHBOARD_BASIC_USER": "",
                "DASHBOARD_BASIC_PASSWORD": "",
            },
        )
        self.auth_patch.start()
        self.addCleanup(self.auth_patch.stop)

    def _restore_state(self) -> None:
        state.AGENT_STORE = self.original_store
        state._WORKER_WAKE = self.original_wake
        state.JOBS.clear()

    def _post_real_job(self):
        return self.client.post(
            "/api/technoeconomic/jobs",
            json=_applied_site_request_payload(source_id=self.annual["id"], n=8),
        )

    def test_eligible_source_route_uses_unbounded_durable_listing(self) -> None:
        list_jobs = self.store.list_jobs
        with patch.object(
            self.store,
            "list_jobs",
            wraps=list_jobs,
        ) as durable_list:
            response = self.client.get("/api/technoeconomic/sources")

        self.assertEqual(200, response.status_code, response.text)
        durable_list.assert_called_once_with(
            states=("done",),
            mode="annual",
            limit=None,
        )
        rows = response.json()["sources"]
        self.assertEqual(
            [self.annual["id"]],
            [row["source_annual_job_id"] for row in rows],
        )
        self.assertTrue(rows[0]["eligible"])

    def test_real_route_resolves_exact_promotion_and_runs_atomic_snapshot_check(
        self,
    ) -> None:
        exact_lookup = self.store.get_promotion
        with (
            patch.object(
                self.store,
                "get_promotion",
                wraps=exact_lookup,
            ) as get_promotion,
            patch.object(
                self.store,
                "list_promotions",
                side_effect=AssertionError(
                    "TEA submission must not use a bounded promotion-history scan"
                ),
            ),
        ):
            response = self._post_real_job()

        self.assertEqual(202, response.status_code, response.text)
        get_promotion.assert_called_once_with(
            mode="validation",
            job_id=self.origin["id"],
            promoted_at=self.promotion["promoted_at"],
        )
        public = response.json()["job"]
        stored = self.store.get_technoeconomic_job(public["job_id"])
        self.assertIsNotNone(stored)
        snapshot = stored["source_snapshot"]
        self.assertEqual(
            self.promotion,
            snapshot["calibration_lineage"]["promotion"],
        )
        self.assertEqual(
            stored["source_snapshot_sha256"],
            tea_api.canonical_json_sha256(snapshot),
        )
        self.assertEqual("queued", stored["state"])
        state._WORKER_WAKE.set.assert_called_once_with()

    def test_real_atomic_callback_rejects_source_bytes_changed_before_insert(
        self,
    ) -> None:
        artifact = self.annual["provenance"]["annual_source_artifact"]
        artifact_path = config.ANNUAL_SOURCE_ARTIFACT_DIR / Path(
            artifact["storage_key"]
        )
        original_bytes = artifact_path.read_bytes()
        create_job = self.store.create_technoeconomic_job

        def tamper_then_create(**kwargs):
            artifact_path.chmod(0o666)
            artifact_path.write_bytes(b"changed after candidate snapshot")
            return create_job(**kwargs)

        try:
            with patch.object(
                self.store,
                "create_technoeconomic_job",
                side_effect=tamper_then_create,
            ):
                response = self._post_real_job()
        finally:
            artifact_path.chmod(0o666)
            artifact_path.write_bytes(original_bytes)

        self.assertEqual(409, response.status_code, response.text)
        self.assertEqual([], self.store.list_technoeconomic_jobs())
        state._WORKER_WAKE.set.assert_not_called()

    def test_private_attempt_payload_is_not_served_from_outputs(self) -> None:
        job_id = f"tea_static_{uuid.uuid4().hex}"
        lease_token = uuid.uuid4().hex
        attempt = _technoeconomic_attempt_directory(
            job_id,
            lease_token,
            create=True,
        )
        payload = attempt / "calculation_payload_v1.npz"
        payload.write_bytes(b"private-sealed-payload")
        self.addCleanup(
            _delete_technoeconomic_attempt_artifacts,
            job_id,
            lease_token,
        )

        response = self.client.get(
            f"/outputs/.technoeconomic_attempts/{job_id}/{lease_token}/"
            "calculation_payload_v1.npz"
        )

        self.assertEqual(404, response.status_code, response.text)
        self.assertNotIn("private-sealed-payload", response.text)

    def test_lifespan_recovers_both_workflows_before_starting_worker(self) -> None:
        with (
            patch.object(
                worker_loop,
                "_mark_stale_running_work_interrupted",
                return_value={"model": 0, "technoeconomic": 0},
            ) as recover,
            patch.object(worker_loop, "_start_model_worker") as start,
            patch.object(worker_loop, "_stop_model_worker") as stop,
            TestClient(app.app),
        ):
            pass

        recover.assert_called_once()
        self.assertIn("before", recover.call_args.kwargs)
        start.assert_called_once_with()
        stop.assert_called_once_with()

    def test_delete_retains_row_when_artifact_cleanup_fails(self) -> None:
        created = self._post_real_job()
        self.assertEqual(202, created.status_code, created.text)
        job_id = created.json()["job"]["job_id"]
        cancelled = self.client.post(
            f"/api/technoeconomic/jobs/{job_id}/cancel"
        )
        self.assertEqual("cancelled", cancelled.json()["job"]["state"])

        lease_token = uuid.uuid4().hex
        attempt = _technoeconomic_attempt_directory(
            job_id,
            lease_token,
            create=True,
        )
        owned = attempt / "calculation_payload_v1.npz"
        owned.write_bytes(b"owned")
        job_directory = attempt.parent
        original_lstat = Path.lstat
        original_unlink = Path.unlink

        def fail_job_directory_lstat(path: Path, *args, **kwargs):
            if path == job_directory:
                raise PermissionError("synthetic inaccessible artifact directory")
            return original_lstat(path, *args, **kwargs)

        def fail_owned_unlink(path: Path, *args, **kwargs):
            if path == owned:
                raise PermissionError("synthetic locked artifact")
            return original_unlink(path, *args, **kwargs)

        with patch.object(Path, "lstat", new=fail_job_directory_lstat):
            inaccessible = self.client.delete(
                f"/api/technoeconomic/jobs/{job_id}"
            )

        self.assertEqual(409, inaccessible.status_code, inaccessible.text)
        self.assertIsNotNone(self.store.get_technoeconomic_job(job_id))
        self.assertTrue(owned.is_file())

        with patch.object(Path, "unlink", new=fail_owned_unlink):
            failed = self.client.delete(
                f"/api/technoeconomic/jobs/{job_id}"
            )

        self.assertEqual(409, failed.status_code, failed.text)
        self.assertIn("retained", failed.json()["detail"])
        self.assertIsNotNone(self.store.get_technoeconomic_job(job_id))
        self.assertTrue(owned.is_file())

        retried = self.client.delete(f"/api/technoeconomic/jobs/{job_id}")
        self.assertEqual(200, retried.status_code, retried.text)
        self.assertIsNone(self.store.get_technoeconomic_job(job_id))
        self.assertFalse(owned.exists())


class TechnoeconomicRenderProxyTests(unittest.TestCase):
    def test_exact_tea_allowlist_and_rejections(self) -> None:
        node = shutil.which("node")
        if node is None:
            self.skipTest("Node.js is unavailable")

        cases = [
            (["technoeconomic", "sources"], True),
            (["technoeconomic", "jobs"], True),
            (["technoeconomic", "jobs", "tea_abc123"], True),
            (["technoeconomic", "jobs", "tea_abc123", "cancel"], True),
            (["technoeconomic", "jobs", "tea_abc123", "retry"], True),
            (["technoeconomic", "jobs", "tea_abc123", "exports", "csv"], True),
            (["technoeconomic", "jobs", "tea_abc123", "exports", "xlsx"], True),
            (["technoeconomic", "jobs", "tea_abc123", "artifacts", "cdf_plot"], True),
            (["technoeconomic", "jobs", "tea_abc123", "artifacts", "sensitivity_plot"], True),
            (["technoeconomic", "jobs", "tea_abc123", "artifacts", "convergence_plot"], True),
            (["technoeconomic", "jobs", "tea_abc123", "promote"], False),
            (["technoeconomic", "jobs", ".."], False),
            (["technoeconomic", "jobs", "tea_abc123", "delete"], False),
            (["technoeconomic", "sources", "extra"], False),
            (["technoeconomic", "jobs", "tea_abc123", "cancel", "extra"], False),
            (["technoeconomic", "jobs", "tea_abc123", "exports", "png"], False),
            (["technoeconomic", "jobs", "tea_abc123", "exports", "csv", "extra"], False),
            (["technoeconomic", "jobs", "tea_abc123", "artifacts", "sealed_calculation"], False),
            (["technoeconomic", "jobs", "..", "exports", "csv"], False),
        ]
        script = f"""
import {{ isAllowedApiPath }} from './lib/render-proxy.ts';
const cases = {json.dumps(cases)};
for (const [path, expected] of cases) {{
  const actual = isAllowedApiPath(path);
  if (actual !== expected) {{
    console.error(JSON.stringify({{ path, expected, actual }}));
    process.exitCode = 1;
  }}
}}
"""
        completed = subprocess.run(
            [
                node,
                "--no-warnings",
                "--experimental-strip-types",
                "--input-type=module",
                "-e",
                script,
            ],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(
            0,
            completed.returncode,
            completed.stdout + completed.stderr,
        )


if __name__ == "__main__":
    unittest.main()
