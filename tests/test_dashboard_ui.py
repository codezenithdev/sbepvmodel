import json
import re
import shutil
import subprocess
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import matplotlib.dates as mdates
import matplotlib.figure
import pandas as pd
from fastapi.testclient import TestClient

from sbepv.api import config, plots, state
from sbepv.api import main as app
from sbepv import dashboard, model, reporting
from sbepv.store import AgentStore
from sbepv.worker import run_annual, run_validation


PLOT_TIMESTAMP_FORMAT = "%m-%d-%Y %H:%M"


def assert_plot_timestamp_format(test_case, axis):
    formatter = axis.xaxis.get_major_formatter()
    test_case.assertIsInstance(formatter, mdates.DateFormatter)
    test_case.assertEqual(formatter.fmt, PLOT_TIMESTAMP_FORMAT)
    sample = datetime(2025, 12, 15, 9, 0, tzinfo=formatter.tz)
    test_case.assertEqual(
        formatter(mdates.date2num(sample)),
        "12-15-2025 09:00",
    )


class CurtailmentDefaultTests(unittest.TestCase):
    def setUp(self):
        legacy_run = patch.object(
            app,
            "_legacy_unreviewed_run_enabled",
            return_value=True,
        )
        legacy_run.start()
        self.addCleanup(legacy_run.stop)
        state.JOBS.clear()
        handle = tempfile.NamedTemporaryFile(
            prefix="dashboard-api-test-",
            suffix=".sqlite3",
            dir=Path(__file__).resolve().parent,
            delete=False,
        )
        handle.close()
        database = Path(handle.name)
        original_store = state.AGENT_STORE
        state.AGENT_STORE = AgentStore(database)
        self.addCleanup(setattr, state, "AGENT_STORE", original_store)
        self.addCleanup(
            lambda: [
                path.unlink(missing_ok=True)
                for path in (database, Path(f"{database}-wal"), Path(f"{database}-shm"))
            ]
        )

    def test_validation_and_annual_requests_default_enabled_curtailment_to_125(self):
        cases = (
            (
                "/api/run",
                {"from_date": "2026-06-20", "to_date": "2026-06-21"},
                run_validation,
                "_run_job",
            ),
            (
                "/api/annual-run",
                {"from_date": "2025-01-01", "to_date": "2025-01-02"},
                run_annual,
                "_run_annual_job",
            ),
        )

        for endpoint, base_payload, worker_module, worker_name in cases:
            with self.subTest(endpoint=endpoint):
                with patch.object(worker_module, worker_name, return_value=None):
                    response = TestClient(app.app).post(
                        endpoint,
                        json={**base_payload, "curtailment_enabled": True},
                    )

                self.assertEqual(response.status_code, 200)
                request = state.JOBS[response.json()["job_id"]]["request"]
                self.assertTrue(request["curtailment_enabled"])
                self.assertEqual(
                    request["curtailment_limit_kw"],
                    model.DEFAULT_CURTAILMENT_LIMIT_KW,
                )

    def test_custom_value_is_kept_and_disabled_value_is_canonicalized_to_none(self):
        enabled = app.RunRequest(
            from_date="2026-06-20",
            to_date="2026-06-21",
            curtailment_enabled=True,
            curtailment_limit_kw=140,
        )
        app._validate_curtailment(enabled)
        self.assertEqual(enabled.curtailment_limit_kw, 140.0)

        disabled = app.RunRequest(
            from_date="2026-06-20",
            to_date="2026-06-21",
            curtailment_enabled=False,
            curtailment_limit_kw=140,
        )
        app._validate_curtailment(disabled)
        self.assertIsNone(disabled.curtailment_limit_kw)

    def test_non_positive_enabled_values_are_rejected(self):
        for value in (0, -1):
            with self.subTest(value=value):
                request = app.RunRequest(
                    from_date="2026-06-20",
                    to_date="2026-06-21",
                    curtailment_enabled=True,
                    curtailment_limit_kw=value,
                )
                with self.assertRaises(app.HTTPException):
                    app._validate_curtailment(request)

    def test_agent_state_exposes_ten_terminal_history_ids_separately(self):
        for index in range(12):
            job_id = f"history-{index:02d}"
            state.AGENT_STORE.create_job(
                job_id=job_id,
                kind="baseline",
                mode="annual",
                request={"from_date": "2025-01-01", "to_date": "2025-12-31"},
            )
            state.AGENT_STORE.claim_next_queued_job()
            state.AGENT_STORE.update_job(
                job_id,
                state="done",
                result={"stats": {"se_predicted_kwh": index}},
            )
        state.AGENT_STORE.promote_job("history-00")
        state.AGENT_STORE.create_job(
            job_id="history-active",
            kind="baseline",
            mode="annual",
            request={},
        )
        state.AGENT_STORE.claim_next_queued_job()
        state.AGENT_STORE.create_job(
            job_id="history-queued",
            kind="baseline",
            mode="annual",
            request={},
        )

        response = app.agent_state(mode="annual")
        payload = json.loads(response.body)

        self.assertEqual(10, payload["history_limit"])
        self.assertEqual(10, len(payload["recent_job_ids"]))
        self.assertNotIn("history-00", payload["recent_job_ids"])
        self.assertNotIn("history-active", payload["recent_job_ids"])
        self.assertNotIn("history-queued", payload["recent_job_ids"])
        jobs = {job["job_id"]: job for job in payload["jobs"]}
        self.assertIn("history-00", jobs)  # promoted context, not history
        self.assertIn("history-active", jobs)
        self.assertIn("history-queued", jobs)
        self.assertEqual("dashboard", jobs["history-00"]["origin"])

    def test_agent_state_keeps_a_twelve_member_sweep_atomic(self):
        sweep_id = "parameter-history-atomic"
        for index in range(12):
            job_id = f"sweep-history-{index:02d}"
            state.AGENT_STORE.create_job(
                job_id=job_id,
                kind="candidate",
                mode="annual",
                request={"years": [2024]},
                provenance={
                    "scenario_sweep": {
                        "type": "parameter_sweep",
                        "sweep_id": sweep_id,
                        "parameter": "curtailment_limit_kw",
                        "index": index,
                        "candidate_count": 12,
                    }
                },
            )
            state.AGENT_STORE.claim_next_queued_job()
            state.AGENT_STORE.update_job(
                job_id,
                state="done",
                result={"stats": {"se_predicted_kwh": index}},
            )

        response = app.agent_state(mode="annual")
        payload = json.loads(response.body)

        self.assertEqual(10, payload["history_limit"])
        self.assertEqual(1, payload["recent_activity_count"])
        self.assertEqual(12, len(payload["recent_job_ids"]))
        self.assertEqual(
            {f"sweep-history-{index:02d}" for index in range(12)},
            set(payload["recent_job_ids"]),
        )

    def test_agent_state_expands_an_old_sweep_after_one_member_becomes_recent(self):
        sweep_id = "parameter-history-retried"
        sweep_job_ids = []
        for index in range(12):
            job_id = f"retried-sweep-{index:02d}"
            sweep_job_ids.append(job_id)
            state.AGENT_STORE.create_job(
                job_id=job_id,
                kind="candidate",
                mode="annual",
                request={"years": [2024]},
                provenance={
                    "scenario_sweep": {
                        "type": "parameter_sweep",
                        "sweep_id": sweep_id,
                        "parameter": "curtailment_limit_kw",
                        "index": index,
                        "candidate_count": 12,
                    }
                },
            )
            if index == 0:
                state.AGENT_STORE.cancel_job(job_id)
            else:
                state.AGENT_STORE.claim_next_queued_job()
                state.AGENT_STORE.update_job(job_id, state="done")

        for index in range(119):
            job_id = f"newer-single-{index:03d}"
            state.AGENT_STORE.create_job(
                job_id=job_id,
                kind="baseline",
                mode="annual",
                request={"years": [2024]},
            )
            state.AGENT_STORE.claim_next_queued_job()
            state.AGENT_STORE.update_job(job_id, state="done")

        state.AGENT_STORE.retry_job(sweep_job_ids[0])

        queued_payload = json.loads(app.agent_state(mode="annual").body)
        queued_job_ids = {job["job_id"] for job in queued_payload["jobs"]}
        self.assertTrue(set(sweep_job_ids).issubset(queued_job_ids))
        self.assertNotIn(sweep_job_ids[0], queued_payload["recent_job_ids"])

        state.AGENT_STORE.claim_next_queued_job()
        state.AGENT_STORE.update_job(sweep_job_ids[0], state="done")

        payload = json.loads(app.agent_state(mode="annual").body)

        self.assertEqual(10, payload["recent_activity_count"])
        self.assertTrue(set(sweep_job_ids).issubset(payload["recent_job_ids"]))
        self.assertEqual(21, len(payload["recent_job_ids"]))

    def test_public_job_removes_local_paths_but_keeps_output_links(self):
        private_root = str(config.OUTPUT_DIR.resolve())
        public = app._public_job(
            {
                "id": "sanitized-history",
                "state": "done",
                "result": {
                    "excel": "/outputs/safe.xlsx",
                    "stats": {
                        "excel": str(config.OUTPUT_DIR / "private.xlsx"),
                        "input_csv": str(config.OUTPUT_DIR / "private.csv"),
                    },
                },
                "provenance": {
                    "baseline": {
                        "job_id": "baseline",
                        "workbook": str(config.OUTPUT_DIR / "baseline.xlsx"),
                    },
                    "files": [
                        str(config.OUTPUT_DIR / "nested-private.csv"),
                        "/outputs/safe.csv",
                    ],
                },
                "artifacts": {
                    "model_workbook": {
                        "path": str(config.OUTPUT_DIR / "private.xlsx"),
                        "url": "/outputs/safe.xlsx",
                        "filename": "safe.xlsx",
                    }
                },
                "error": (
                    "Source file does not exist: "
                    + str(config.OUTPUT_DIR / "private-source.csv")
                ),
            }
        )

        def nested_strings(value):
            if isinstance(value, dict):
                for item in value.values():
                    yield from nested_strings(item)
            elif isinstance(value, list):
                for item in value:
                    yield from nested_strings(item)
            elif isinstance(value, str):
                yield value

        self.assertFalse(
            any(private_root in value for value in nested_strings(public))
        )
        self.assertEqual("/outputs/safe.xlsx", public["result"]["excel"])
        self.assertNotIn("excel", public["result"]["stats"])
        self.assertNotIn("input_csv", public["result"]["stats"])
        self.assertNotIn("workbook", public["provenance"]["baseline"])
        self.assertEqual(["/outputs/safe.csv"], public["provenance"]["files"])
        self.assertNotIn("path", public["artifacts"]["model_workbook"])
        self.assertEqual(
            "/outputs/safe.xlsx",
            public["artifacts"]["model_workbook"]["url"],
        )
        self.assertEqual(
            "The run could not be completed. Check the server logs for details.",
            public["error"],
        )
        unc_public = app._public_job(
            {
                "id": "sanitized-unc-error",
                "state": "error",
                "error": r"Failed opening \\fileserver\pv\secret.csv",
            }
        )
        self.assertEqual(
            "The run could not be completed. Check the server logs for details.",
            unc_public["error"],
        )

    def test_saved_results_api_is_durable_safe_and_idempotent(self):
        job = state.AGENT_STORE.create_job(
            job_id="api-saved-result",
            kind="manual",
            mode="annual",
            request={"years": [2025]},
        )
        state.AGENT_STORE.claim_next_queued_job()
        private_source = str(config.OUTPUT_DIR / "private-source.csv")
        state.AGENT_STORE.update_job(
            job["id"],
            state="done",
            result={
                "workbook_url": "/outputs/safe.xlsx",
                "input_csv": private_source,
                "detail": {"source": private_source},
            },
        )
        client = TestClient(app.app)

        created = client.post(
            f"/api/saved-results/{job['id']}",
            json={"name": "Annual reference"},
        )
        repeated = client.post(
            f"/api/saved-results/{job['id']}",
            json={"name": "Ignored idempotent rename"},
        )
        listed = client.get("/api/saved-results")

        self.assertEqual(200, created.status_code)
        self.assertEqual(created.json(), repeated.json())
        self.assertEqual(10, listed.json()["limit"])
        self.assertEqual(1, len(listed.json()["saved_results"]))
        public_saved = listed.json()["saved_results"][0]
        self.assertEqual(job["id"], public_saved["job_id"])
        self.assertEqual("Annual reference", public_saved["name"])
        self.assertEqual("done", public_saved["job"]["state"])
        self.assertEqual(
            "/outputs/safe.xlsx",
            public_saved["job"]["result"]["workbook_url"],
        )
        self.assertNotIn(private_source, json.dumps(public_saved))

        renamed = client.put(
            f"/api/saved-results/{job['id']}",
            json={"name": "  Annual   reference  "},
        )
        self.assertEqual(200, renamed.status_code)
        self.assertEqual("Annual reference", renamed.json()["saved_result"]["name"])

        protected = client.post(f"/api/jobs/{job['id']}/delete")
        self.assertEqual(409, protected.status_code)
        removed = client.delete(f"/api/saved-results/{job['id']}")
        self.assertEqual(
            {"job_id": job["id"], "removed": True},
            removed.json(),
        )
        self.assertEqual(job["id"], state.AGENT_STORE.get_job(job["id"])["id"])
        self.assertEqual([], client.get("/api/saved-results").json()["saved_results"])

        default_job = state.AGENT_STORE.create_job(
            job_id="api-default-saved-name",
            kind="manual",
            mode="validation",
            request={},
        )
        state.AGENT_STORE.claim_next_queued_job()
        state.AGENT_STORE.update_job(
            default_job["id"], state="done", result={"energy_kwh": 1.0}
        )
        default_named = client.post(f"/api/saved-results/{default_job['id']}")
        self.assertEqual(200, default_named.status_code)
        self.assertTrue(
            default_named.json()["saved_result"]["name"].startswith(
                "Calibration / validation - "
            )
        )

    def test_saved_results_api_rejects_ineligible_or_unknown_jobs(self):
        queued = state.AGENT_STORE.create_job(
            job_id="api-unsaveable",
            kind="manual",
            mode="annual",
            request={},
        )
        client = TestClient(app.app)

        self.assertEqual(
            409,
            client.post(f"/api/saved-results/{queued['id']}").status_code,
        )
        self.assertEqual(
            404,
            client.post("/api/saved-results/unknown-job").status_code,
        )
        self.assertEqual(
            404,
            client.put(
                "/api/saved-results/unknown-job", json={"name": "Name"}
            ).status_code,
        )
        self.assertEqual(
            404,
            client.delete("/api/saved-results/unknown-job").status_code,
        )


class ValidationWindowMetadataTests(unittest.TestCase):
    def test_validation_window_metadata_preserves_legacy_utc_and_dst_offsets(self):
        cases = (
            (
                "summer",
                "2026-06-20T14:00:00",
                "2026-06-22T00:00:00",
                "2026-06-20T08:00:00-06:00",
                "2026-06-21T18:00:00-06:00",
            ),
            (
                "winter",
                "2026-12-20T15:00:00",
                "2026-12-23T01:00:00",
                "2026-12-20T08:00:00-07:00",
                "2026-12-22T18:00:00-07:00",
            ),
        )
        for label, from_value, to_value, from_local, to_local in cases:
            with self.subTest(label=label):
                window = app._validation_window_metadata(from_value, to_value)
                self.assertEqual(window["from"], from_value)
                self.assertEqual(window["to"], to_value)
                self.assertEqual(window["from_utc"], from_value + "Z")
                self.assertEqual(window["to_utc"], to_value + "Z")
                self.assertEqual(window["from_local"], from_local)
                self.assertEqual(window["to_local"], to_local)
                self.assertEqual(window["timezone"], "America/Denver")
                self.assertTrue(window["end_exclusive"])


class DashboardInteractionMarkupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = dashboard.render_dashboard()

    def test_both_curtailment_fields_start_at_125_and_preserve_edits(self):
        for element_id in ("curtailmentLimitKw", "annualCurtailmentLimitKw"):
            self.assertRegex(
                self.html,
                rf'<input[^>]*id="{re.escape(element_id)}"[^>]*value="125"[^>]*disabled',
            )
        self.assertIn(
            "if (enabled && !curtailmentLimitKw.value.trim()) curtailmentLimitKw.value = '125';",
            self.html,
        )
        self.assertIn(
            "if (enabled && !annualCurtailmentLimitKw.value.trim()) annualCurtailmentLimitKw.value = '125';",
            self.html,
        )
        self.assertNotIn("curtailmentLimitKw.value = '';", self.html)

    def test_calibration_is_an_unchecked_opt_in_below_curtailment(self):
        checkbox = re.search(
            r'<input(?=[^>]*\bid="calibrateModel")[^>]*>',
            self.html,
        )
        self.assertIsNotNone(checkbox)
        assert checkbox is not None
        self.assertNotIn("checked", checkbox.group(0))
        self.assertLess(
            self.html.index('id="curtailmentLimitKw"'),
            self.html.index('id="calibrateModel"'),
        )
        self.assertIn('id="validationActionTitle">Ready to run?</strong>', self.html)
        self.assertIn('<button class="run-btn" id="runBtn">Run model</button>', self.html)
        self.assertIn("enabled ? 'Ready to calibrate?' : 'Ready to run?'", self.html)
        self.assertIn(
            "'Run the physics model with the selected Bazefield data without fitting calibration factors.'",
            self.html,
        )
        self.assertIn("const calibrationRequested = calibrateModel.checked;", self.html)
        self.assertIn("calibrate_model: calibrationRequested", self.html)
        self.assertIn(
            "const endpoint = calibrationRequested ? '/api/calibration-reviews' : '/api/run';",
            self.html,
        )
        self.assertIn("if (calibrationRequested) {", self.html)
        self.assertIn("stage: 'Uncalibrated model queued'", self.html)

    def test_result_cards_show_uncalibrated_energy_and_delta_only_when_calibrated(self):
        for container_id in (
            "seUncalibratedComparison",
            "solUncalibratedComparison",
        ):
            container = re.search(
                rf'<div(?=[^>]*\bid="{container_id}")'
                rf'(?=[^>]*\bhidden\b)[^>]*>',
                self.html,
            )
            self.assertIsNotNone(container, container_id)
        for value_id in (
            "statSeUncalibratedPred",
            "statSeUncalibratedPct",
            "statSolUncalibratedPred",
            "statSolUncalibratedPct",
        ):
            self.assertIn(f'id="{value_id}"', self.html)
        self.assertGreaterEqual(self.html.count("Before calibration"), 2)

        signature = "function renderUncalibratedComparison(stats, calibrated)"
        self.assertIn(signature, self.html)
        helper = self.html.split(signature, 1)[1].split(
            "\n        function ",
            1,
        )[0]
        self.assertRegex(helper, r"stats\??\.uncalibrated")
        self.assertRegex(
            helper,
            r"calibrated\s*&&[\s\S]{0,240}typeof\s+[^;]+===\s*'object'",
        )
        self.assertIn("getElementById('seUncalibratedComparison')", helper)
        self.assertIn("getElementById('solUncalibratedComparison')", helper)
        self.assertEqual(
            len(re.findall(r"\.hidden\s*=\s*!\w+", helper)),
            2,
        )
        for field in (
            "uncalibrated.se_predicted_kwh",
            "uncalibrated.se_pct",
            "uncalibrated.sol_predicted_kwh",
            "uncalibrated.sol_pct",
        ):
            self.assertIn(field, helper)

        apply_result = self.html.split("function applyResult(result, cacheBust = true)", 1)[1].split(
            "\n        function ",
            1,
        )[0]
        self.assertIn("renderUncalibratedComparison(s, calibrated)", apply_result)

    def test_validation_run_context_precedes_result_summaries_and_plots(self):
        context = re.search(
            r'<(?P<tag>[a-z0-9]+)(?=[^>]*\bid="validationRunContext")'
            r'(?=[^>]*\bclass="[^"]*validation-run-context[^"]*")'
            r'(?=[^>]*\bhidden\b)[^>]*>',
            self.html,
            flags=re.IGNORECASE,
        )
        self.assertIsNotNone(context)
        assert context is not None

        context_index = context.start()
        summaries_index = self.html.index('class="validation-system-summaries"')
        plots_index = self.html.index('class="analysis-layout"', summaries_index)
        self.assertLess(context_index, summaries_index)
        self.assertLess(context_index, plots_index)
        self.assertLess(
            self.html.index('id="validationPreflightPanel"'),
            summaries_index,
        )

        for element_id in (
            "validationRunContextRange",
            "validationRunContextSeInverter",
            "validationRunContextSeBos",
            "validationRunContextSeTotal",
            "validationRunContextSolInverter",
            "validationRunContextSolBos",
            "validationRunContextSolTotal",
        ):
            self.assertEqual(self.html.count(f'id="{element_id}"'), 1, element_id)

    def test_validation_run_context_uses_frozen_result_window_and_clears_without_one(self):
        signature = "function renderValidationRunContext(result)"
        self.assertIn(signature, self.html)
        helper = self.html.split(signature, 1)[1].split(
            "\n        function ",
            1,
        )[0]

        for field in (
            "from_local",
            "to_local",
            "timezone",
            "end_exclusive",
            "solaredge_inverter_efficiency",
            "solaredge_bos_efficiency",
            "solaredge_total_efficiency",
            "solectria_inverter_efficiency",
            "solectria_bos_efficiency",
            "solectria_total_efficiency",
        ):
            self.assertIn(field, helper)

        self.assertRegex(
            helper,
            r"windowData\.from_local\s*(?:\?\?|\|\|)\s*windowData\.from\b",
        )
        self.assertRegex(
            helper,
            r"windowData\.to_local\s*(?:\?\?|\|\|)\s*windowData\.to\b",
        )
        self.assertRegex(
            helper,
            r"if\s*\(\s*!windowData\s*\)[\s\S]*?validationRunContext\.hidden\s*=\s*true",
        )
        self.assertIn("validationRunContextRange.textContent = '--'", helper)
        self.assertIn("validationRunContextTimezone.textContent = '--'", helper)
        self.assertIn(
            "Object.values(validationRunContextEfficiencyValues).forEach",
            helper,
        )
        self.assertIn("node.textContent = '--'", helper)
        self.assertIn("validationRunContext.hidden = false", helper)

        # Completed result provenance is authoritative. Changing the live form
        # after a run must not rewrite the context shown above its charts.
        for live_control in (
            "fromDate",
            "fromTime",
            "toDate",
            "toTime",
            "solaredgeInverterEfficiency",
            "solaredgeBosEfficiency",
            "solectriaInverterEfficiency",
            "solectriaBosEfficiency",
        ):
            self.assertNotIn(live_control, helper)
        self.assertNotIn("document.getElementById", helper)

        apply_result = self.html.split(
            "function applyResult(result, cacheBust = true)",
            1,
        )[1].split("\n        function ", 1)[0]
        render_index = apply_result.index("renderValidationRunContext(result)")
        guard_index = apply_result.index("if (!result || !result.stats) return")
        self.assertLess(render_index, guard_index)
        self.assertGreaterEqual(
            self.html.count("renderValidationRunContext(null)"),
            2,
        )

    @unittest.skipUnless(shutil.which("node"), "Node.js is required")
    def test_validation_weather_preflight_copy_reports_shared_coverage(self):
        helper = self.html.split(
            "function validationPreflightCopy(summary)", 1
        )[1].split("\n        function renderValidationPreflight", 1)[0]
        script = f"""
function validationPreflightCopy(summary){helper}
const partial = validationPreflightCopy({{
    input_row_count: 5831,
    usable_row_count: 5776,
    omitted_row_count: 55,
    coverage_pct: 99.057,
    wind_interpolated_count: 1,
    temperature_interpolated_count: 1,
    wind_clamped_count: 0,
}});
const clean = validationPreflightCopy({{
    input_row_count: 24,
    usable_row_count: 24,
    omitted_row_count: 0,
    coverage_pct: 100,
}});
console.log(JSON.stringify({{partial, clean}}));
"""
        completed = subprocess.run(
            [shutil.which("node"), "-e", script],
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(completed.stdout)
        self.assertFalse(payload["partial"]["ok"])
        self.assertEqual(
            "Validation completed with 99.1% usable coverage",
            payload["partial"]["title"],
        )
        self.assertIn(
            "5,776 of 5,831 intervals modeled", payload["partial"]["detail"]
        )
        self.assertIn("55 omitted", payload["partial"]["detail"])
        self.assertIn(
            "2 weather cells interpolated", payload["partial"]["detail"]
        )
        self.assertTrue(payload["clean"]["ok"])
        self.assertEqual(
            "Validation weather preflight passed", payload["clean"]["title"]
        )

    def test_validation_run_context_has_responsive_layout(self):
        self.assertRegex(
            self.html,
            r"\.validation-run-context-grid\s*\{[^}]*display:\s*grid;",
        )
        self.assertRegex(
            self.html,
            r"@media\s*\(max-width:\s*\d+px\)\s*\{[\s\S]*?"
            r"\.validation-run-context-grid\s*\{[^}]*"
            r"grid-template-columns:\s*1fr;",
        )

    def test_calibration_review_discloses_rows_and_keeps_applied_gate_receipt(self):
        for marker in (
            'id="calibrationReviewPanel"',
            'id="calibrationIssueList"',
            'id="applyCalibrationReviewBtn"',
            'id="calibrationFactorPanel"',
            'id="calibrationFactorRows"',
            'id="calibrationDecisionGate"',
            'id="sourceDecisionAcknowledgement"',
            'id="confirmCalibrationReviewBtn"',
            "buildCalibrationRowDisclosure(issue, issueIndex)",
            "issue.affected_rows_available",
            "Rows load from the private, hash-verified review snapshot.",
            "'/api/calibration-reviews/' + encodeURIComponent(pendingCalibrationReview.review_id) + '/rows?'",
            "Array.isArray(page.rows)",
            "Load more rows",
            "Last 50 rows",
            "Show first 50 rows",
            "Load all rows",
            "Math.max(totalRows - rowPageSize, 0)",
            "query.set('all_rows', 'true')",
            'className = \'calibration-row-actions\'',
            "showLast.hidden = totalRows <= rowPageSize",
            "const renderBatchSize = mode === 'all' ? 250",
            "await new Promise((resolve) => setTimeout(resolve, 0))",
            "calibrationReviewDecisions()",
            "renderCalibrationFactors(result)",
            "new AbortController()",
            "calibrationWorkflowRevision",
            "pendingCalibrationReview.decisions[issueId]",
            "calibrationReviewIsExpired",
            "Decision for ",
            "Show affected rows (",
            "applyCalibrationReviewBtn.addEventListener('click', openCalibrationDecisionGate)",
            "confirmCalibrationReviewBtn.addEventListener('click', applyCalibrationReview)",
            "renderAppliedCalibrationDecisionGate(pendingCalibrationReview)",
            "applied: true",
            "Source-data decision gate passed",
            "The receipt remains visible with this run.",
        ):
            self.assertIn(marker, self.html)

    def test_calibration_review_timestamps_use_mountain_time(self):
        signature = "function formatCalibrationReviewTimestamp(value)"
        self.assertIn(signature, self.html)
        formatter = self.html.split(signature, 1)[1].split(
            "\n        function ",
            1,
        )[0]
        for marker in (
            "CALIBRATION_REVIEW_TIMEZONE = 'America/Denver'",
            "timeZone: CALIBRATION_REVIEW_TIMEZONE",
            "timeZoneName: 'short'",
            "calendarCheck.getUTCFullYear()",
            "actual.some((part, index) => part !== expected[index])",
            "normalized + 'Z'",
            "if (Number.isNaN(timestamp.getTime())) return text",
        ):
            self.assertIn(marker, self.html)
        self.assertIn("calibrationReviewTimestampFormatter.format(timestamp)", formatter)
        for call_site in (
            "formatCalibrationReviewTimestamp(reviewPayload.expires_at)",
            "calibrationRowCellText(column, value)",
            "if (column === 'timestamp') return formatCalibrationReviewTimestamp(value)",
            ".map(formatCalibrationReviewTimestamp)",
            "Timestamp (Mountain)",
            "Examples (Mountain): ",
        ):
            self.assertIn(call_site, self.html)

    @unittest.skipUnless(shutil.which("node"), "Node.js is required")
    def test_calibration_review_timestamp_formatter_handles_dst_and_invalid_dates(self):
        start = self.html.index("const CALIBRATION_REVIEW_TIMEZONE")
        end = self.html.index(
            "\n        function calibrationReviewIsExpired",
            start,
        )
        formatter_source = self.html[start:end]
        inputs = [
            "2026-06-01 16:00:00",
            "2026-12-01T16:00:00+00:00",
            "2026-11-01T07:30:00Z",
            "2026-11-01T08:30:00Z",
            "not-a-timestamp",
            "row 3",
            "2026-02-31T00:00:00Z",
        ]
        script = (
            formatter_source
            + "\nconsole.log(JSON.stringify("
            + json.dumps(inputs)
            + ".map(formatCalibrationReviewTimestamp)));"
        )
        completed = subprocess.run(
            [shutil.which("node"), "-e", script],
            check=True,
            capture_output=True,
            text=True,
        )

        self.assertEqual(
            json.loads(completed.stdout),
            [
                "Jun 1, 2026, 10:00:00 MDT",
                "Dec 1, 2026, 09:00:00 MST",
                "Nov 1, 2026, 01:30:00 MDT",
                "Nov 1, 2026, 01:30:00 MST",
                "not-a-timestamp",
                "row 3",
                "2026-02-31T00:00:00Z",
            ],
        )

    def test_calibration_factor_table_shows_only_coverage_and_final_factor(self):
        for marker in (
            "Factors use all rows kept during review.",
            "appendFactorEvidence(coverage, 'SE', solarEdge)",
            "appendFactorEvidence(coverage, 'Sol', solectria)",
            "appendFactorValue(seFactor, solarEdge)",
            "appendFactorValue(solFactor, solectria)",
            "'Rows: '",
            "' excluded · '",
            "' modeled · '",
            "'Before calibration: SolarEdge '",
            "' (+ above measured, - below measured)'",
        ):
            self.assertIn(marker, self.html)
        for removed in (
            "calibration-factor-source",
            "daylight fit",
            "all rows balanced",
            " balanced: ",
            "overall_period_fallback",
        ):
            self.assertNotIn(removed, self.html)

    def test_calibration_review_preselects_recommended_dropdown_action(self):
        for marker in (
            ": issue.recommended_action;",
            "? 'Exclude affected rows'",
            ": 'Retain affected rows'",
            "Recommended decisions are selected by default.",
        ):
            self.assertIn(marker, self.html)
        self.assertNotIn("placeholder.textContent = 'Choose Retain or Exclude'", self.html)

    def test_applied_calibration_hides_inactive_review_action_rows(self):
        actions = re.search(
            r'<div(?=[^>]*\bclass="calibration-review-actions")'
            r'(?=[^>]*\bid="calibrationReviewActions")[^>]*>',
            self.html,
        )
        self.assertIsNotNone(actions)
        self.assertRegex(
            self.html,
            r"\.calibration-review-panel\s+\[hidden\]\s*\{"
            r"[^}]*display:\s*none\s*!important;",
        )
        for marker in (
            "calibrationReviewActions.hidden = applied;",
            "sourceDecisionAcknowledgementLabel.hidden = true;",
            "calibrationDecisionGateActions.hidden = true;",
            "applied: true",
            "renderCalibrationReview(pendingCalibrationReview, { focusPanel: false })",
        ):
            self.assertIn(marker, self.html)

    def test_bazefield_review_header_toggle_is_accessible_and_state_preserving(self):
        toggle = re.search(
            r'<button(?=[^>]*\bid="calibrationReviewToggle")'
            r'(?=[^>]*\baria-expanded="true")'
            r'(?=[^>]*\baria-controls="calibrationReviewContent")[^>]*>',
            self.html,
        )
        self.assertIsNotNone(toggle)
        self.assertRegex(
            self.html,
            r'<[^>]*class="[^"]*chevron[^"]*"[^>]*aria-hidden="true"[^>]*>',
        )
        self.assertIn('id="calibrationReviewContent"', self.html)
        signature = (
            "function setCalibrationReviewCollapsed("
            "collapsed, { persist = true } = {})"
        )
        self.assertIn(signature, self.html)
        collapse_block = self.html.split(signature, 1)[1].split(
            "\n        function ",
            1,
        )[0]
        for marker in (
            "calibrationReviewCollapsed",
            "calibrationReviewContent.hidden",
            "calibrationReviewToggle.setAttribute('aria-expanded'",
            "saveDashboardState()",
        ):
            self.assertIn(marker, collapse_block)
        self.assertNotIn("clearCalibrationReview", collapse_block)
        self.assertNotIn("pendingCalibrationReview = null", collapse_block)
        self.assertIn(
            "calibrationReviewToggle.addEventListener('click'",
            self.html,
        )
        self.assertIn(
            "setCalibrationReviewCollapsed(!calibrationReviewCollapsed)",
            self.html,
        )

    def test_chat_window_has_a_persistent_drag_handle(self):
        self.assertIn('id="chatDragHandle"', self.html)
        self.assertIn("CHAT_WINDOW_POSITION_KEY", self.html)
        self.assertIn("setChatWindowPosition", self.html)
        self.assertIn(
            "chatDragHandle.addEventListener('pointerdown'", self.html
        )
        self.assertIn(
            "chatDragHandle.addEventListener('pointermove'", self.html
        )
        self.assertIn(
            "chatDragHandle.addEventListener('pointerup'", self.html
        )
        self.assertIn("syncChatWindowPosition();", self.html)


class CalibrationOptInModelTests(unittest.TestCase):
    def test_uncalibrated_historian_run_skips_factor_fitting(self):
        index = pd.date_range(
            "2026-06-01 12:00:00",
            periods=2,
            freq="h",
            tz="America/Denver",
        )
        parsed = pd.DataFrame(
            {
                "timestamp_utc": index.tz_convert("UTC"),
                "se_measured_power_w": [4_000.0, 5_000.0],
                "sol_measured_power_w": [3_000.0, 4_000.0],
            },
            index=index,
        )
        predicted = parsed.assign(
            se_predicted_power_w=[4_500.0, 5_500.0],
            sol_predicted_power_w=[3_500.0, 4_500.0],
        )
        preflight = {
            "policy": "validation_weather_preflight_v1",
            "input_row_count": 3,
            "usable_row_count": 2,
            "omitted_row_count": 1,
            "coverage_pct": 66.667,
            "warnings": ["Validation omitted 1 unusable weather interval."],
            "events": [
                {
                    "timestamp": "2026-06-01T11:00:00-06:00",
                    "column": "wind_speed_ms",
                    "action": "omitted",
                    "original_value": -1999.0,
                    "final_value": None,
                }
            ],
        }
        parsed.attrs["historian_preflight"] = preflight
        metadata = {}
        progress_messages = []

        def capture_excel(_frame, _path, meta, annual_mode=False):
            self.assertFalse(annual_mode)
            metadata.update(meta)

        with (
            patch.object(
                model, "parse_input_csv", return_value=parsed
            ) as parser,
            patch.object(
                model,
                "predict_ac_power",
                return_value=(predicted, "historian_dhi"),
            ),
            patch.object(model, "apply_seasonal_calibration") as fit,
            patch.object(model, "apply_frozen_seasonal_calibration") as frozen,
            patch.object(model, "plot_results") as plots,
            patch.object(model, "write_excel", side_effect=capture_excel),
        ):
            result = model.run_model(
                input_csv="ignored.csv",
                output_base="ignored",
                calibrate_model=False,
                expected_interval_seconds=3_600,
                requested_start="2026-06-01T18:00:00",
                requested_end="2026-06-01T20:00:00",
                progress_cb=lambda _fraction, message: progress_messages.append(message),
            )

        fit.assert_not_called()
        frozen.assert_not_called()
        parser.assert_called_once_with(
            "ignored.csv",
            validation_weather_preflight=True,
            expected_interval_seconds=3_600,
            requested_start="2026-06-01T18:00:00",
            requested_end="2026-06-01T20:00:00",
        )
        self.assertFalse(result["calibration_enabled"])
        self.assertIsNone(result["calibration_factors"])
        self.assertIsNone(result["factor_driver_diagnostics"])
        self.assertEqual(result["se_predicted_kwh"], 10.0)
        self.assertEqual(result["uncalibrated"]["se_predicted_kwh"], 10.0)
        self.assertFalse(metadata["calibration_enabled"])
        self.assertEqual(metadata["calibration_method"], "not_applied")
        self.assertEqual(preflight, result["historian_preflight"])
        self.assertEqual(preflight, metadata["_historian_preflight"])
        self.assertIn(
            "Validation omitted 1 unusable weather interval.",
            result["data_quality_warnings"],
        )
        public_preflight = json.loads(metadata["historian_preflight"])
        self.assertEqual(1, public_preflight["omitted_row_count"])
        self.assertNotIn("events", public_preflight)
        plots.assert_called_once()
        self.assertFalse(plots.call_args.kwargs["calibrated"])
        self.assertEqual(progress_messages[-1], "Uncalibrated model predictions ready")


class WorkbookExportContractTests(unittest.TestCase):
    @staticmethod
    def _time_series_frame():
        index = pd.date_range(
            "2026-06-20 06:00", periods=2, freq="h", tz=model.TIMEZONE
        )
        return pd.DataFrame(
            {
                "timestamp_utc": index.tz_convert("UTC"),
                "se_measured_power_w": [1_000.0, 2_000.0],
                "se_uncalibrated_power_w": [900.0, 1_800.0],
                "se_predicted_power_w": [950.0, 1_900.0],
                "se_calibration_factor": [1.055, 1.055],
                "sol_measured_power_w": [800.0, 1_600.0],
                "sol_uncalibrated_power_w": [700.0, 1_400.0],
                "sol_predicted_power_w": [780.0, 1_560.0],
                "sol_calibration_factor": [1.114, 1.114],
                "se_measured_energy_kwh": [1.0, 3.0],
                "se_uncalibrated_energy_kwh": [0.9, 2.7],
                "se_predicted_energy_kwh": [0.95, 2.85],
                "sol_measured_energy_kwh": [0.8, 2.4],
                "sol_uncalibrated_energy_kwh": [0.7, 2.1],
                "sol_predicted_energy_kwh": [0.78, 2.34],
                "dt_hours": [1.0, 1.0],
            },
            index=index,
        )

    def test_calibrated_headers_are_truthful_and_loader_remains_compatible(self):
        path = config.OUTPUT_DIR / "_test_calibrated_export_contract.xlsx"
        try:
            model.write_excel(
                self._time_series_frame(),
                str(path),
                {"calibration_enabled": True, "annual_mode": False},
            )
            headers = list(
                pd.read_excel(path, sheet_name="time_series", nrows=0).columns
            )
            for name in (
                "se_calibrated_power_w",
                "sol_calibrated_power_w",
                "se_calibrated_energy_kwh",
                "sol_calibrated_energy_kwh",
                "se_uncalibrated_power_w",
                "sol_uncalibrated_power_w",
                "se_uncalibrated_energy_kwh",
                "sol_uncalibrated_energy_kwh",
            ):
                self.assertIn(name, headers)
            self.assertNotIn("se_predicted_power_w", headers)
            self.assertNotIn("sol_predicted_energy_kwh", headers)
            self.assertEqual(len(headers), len(set(headers)))

            loaded = reporting.load_model_workbook(path)
            self.assertIn("se_predicted_power_w", loaded.time_series)
            self.assertIn("sol_predicted_energy_kwh", loaded.time_series)
        finally:
            path.unlink(missing_ok=True)

    def test_physics_model_headers_remain_predicted(self):
        path = config.OUTPUT_DIR / "_test_physics_export_contract.xlsx"
        try:
            model.write_excel(
                self._time_series_frame(),
                str(path),
                {"calibration_enabled": False, "annual_mode": False},
            )
            headers = list(
                pd.read_excel(path, sheet_name="time_series", nrows=0).columns
            )
            self.assertIn("se_predicted_power_w", headers)
            self.assertIn("sol_predicted_energy_kwh", headers)
            self.assertNotIn("se_calibrated_power_w", headers)
            self.assertNotIn("sol_calibrated_energy_kwh", headers)
        finally:
            path.unlink(missing_ok=True)

    def test_historian_preflight_sheet_retains_detailed_audit_events(self):
        path = config.OUTPUT_DIR / "_test_historian_preflight_audit.xlsx"
        preflight = {
            "policy": "validation_weather_preflight_v1",
            "input_row_count": 2,
            "usable_row_count": 1,
            "omitted_row_count": 1,
            "coverage_pct": 50.0,
            "warnings": ["One interval was omitted."],
            "events": [
                {
                    "timestamp": "2026-06-20T06:00:00-06:00",
                    "column": "wind_speed_ms",
                    "action": "interpolated",
                    "original_value": -1999.0,
                    "final_value": 2.0,
                },
                {
                    "timestamp": "2026-06-20T07:00:00-06:00",
                    "column": "temp_air_c",
                    "action": "omitted",
                    "original_value": -80.3,
                    "final_value": None,
                },
            ],
        }
        try:
            model.write_excel(
                self._time_series_frame(),
                str(path),
                {
                    "calibration_enabled": False,
                    "annual_mode": False,
                    "historian_preflight": json.dumps(
                        {
                            key: value
                            for key, value in preflight.items()
                            if key != "events"
                        },
                        sort_keys=True,
                    ),
                    "_historian_preflight": preflight,
                },
            )

            with pd.ExcelFile(path) as workbook:
                self.assertIn("historian_preflight", workbook.sheet_names)
                audit = pd.read_excel(
                    workbook, sheet_name="historian_preflight"
                )
                run_info = pd.read_excel(workbook, sheet_name="run_info")

            events = audit.loc[audit["record_type"].eq("event")]
            self.assertEqual(2, len(events))
            self.assertEqual(
                ["interpolated", "omitted"], events["action"].tolist()
            )
            self.assertEqual(
                ["wind_speed_ms", "temp_air_c"], events["column"].tolist()
            )
            self.assertEqual(-1999.0, events.iloc[0]["original_value"])
            self.assertEqual(2.0, events.iloc[0]["final_value"])
            self.assertTrue(pd.isna(events.iloc[1]["final_value"]))
            self.assertIn(
                "historian_preflight", run_info["parameter"].tolist()
            )
        finally:
            path.unlink(missing_ok=True)

    def test_workbook_download_names_are_readable_and_safe(self):
        request = app.RunRequest(
            from_date="2026-06-20",
            from_time="06:30",
            to_date="2026-06-27",
            to_time="18:45",
        )
        self.assertEqual(
            app._workbook_download_name(request, calibrated=True),
            "SB_Energy_Calibrated_Model_2026-06-20_06-30_to_2026-06-27_18-45.xlsx",
        )
        self.assertEqual(
            app._workbook_download_name(request, calibrated=False),
            "SB_Energy_Physics_Model_2026-06-20_06-30_to_2026-06-27_18-45.xlsx",
        )
        annual = app.AnnualRunRequest(
            from_date="2026-01-01", to_date="2026-12-31"
        )
        self.assertEqual(
            app._workbook_download_name(annual),
            "SB_Energy_Annual_Simulation_2026-01-01_to_2026-12-31.xlsx",
        )


class AcChartLayoutTests(unittest.TestCase):
    def test_summary_and_legend_are_outside_ac_data_axes(self):
        index = pd.date_range(
            "2026-06-20", periods=3, freq="h", tz="America/Denver"
        )
        frame = pd.DataFrame(
            {
                "se_predicted_power_w": [0.0, 100_000.0, 0.0],
                "sol_predicted_power_w": [0.0, 90_000.0, 0.0],
                "se_measured_power_w": [0.0, 95_000.0, 0.0],
                "sol_measured_power_w": [0.0, 85_000.0, 0.0],
                "se_predicted_energy_kwh": [0.0, 50.0, 100.0],
                "sol_predicted_energy_kwh": [0.0, 45.0, 90.0],
                "se_measured_energy_kwh": [0.0, 47.5, 95.0],
                "sol_measured_energy_kwh": [0.0, 42.5, 85.0],
            },
            index=index,
        )
        saved_figures = []

        def capture(figure, *_args, **_kwargs):
            saved_figures.append(figure)

        with patch.object(
            matplotlib.figure.Figure,
            "savefig",
            autospec=True,
            side_effect=capture,
        ):
            model.plot_results(frame, "ignored")

        ac_figure = saved_figures[0]
        ac_axes = ac_figure.axes[0]
        self.assertEqual(len(ac_axes.texts), 0)
        self.assertEqual(len(ac_figure.texts), 1)
        self.assertEqual(len(ac_figure.legends), 1)
        self.assertLessEqual(ac_axes.get_position().y1, 0.781)


class GeneratedPlotTimestampTests(unittest.TestCase):
    @staticmethod
    def _model_frame():
        index = pd.date_range(
            "2025-12-15 09:00", periods=3, freq="h", tz="America/Denver"
        )
        return pd.DataFrame(
            {
                "se_predicted_power_w": [0.0, 100_000.0, 0.0],
                "sol_predicted_power_w": [0.0, 90_000.0, 0.0],
                "se_measured_power_w": [0.0, 95_000.0, 0.0],
                "sol_measured_power_w": [0.0, 85_000.0, 0.0],
                "se_predicted_energy_kwh": [0.0, 50.0, 100.0],
                "sol_predicted_energy_kwh": [0.0, 45.0, 90.0],
                "se_measured_energy_kwh": [0.0, 47.5, 95.0],
                "sol_measured_energy_kwh": [0.0, 42.5, 85.0],
            },
            index=index,
        )

    def test_calibrated_model_power_and_energy_plots_use_requested_format(self):
        saved_figures = []

        def capture(figure, *_args, **_kwargs):
            saved_figures.append(figure)

        with patch.object(
            matplotlib.figure.Figure,
            "savefig",
            autospec=True,
            side_effect=capture,
        ):
            model.plot_results(self._model_frame(), "ignored", calibrated=True)

        self.assertEqual(len(saved_figures), 2)
        for figure in saved_figures:
            assert_plot_timestamp_format(self, figure.axes[0])
        self.assertEqual(
            saved_figures[0].axes[0].get_title(), "Calibrated AC Power"
        )
        self.assertEqual(
            saved_figures[1].axes[0].get_title(),
            "Calibrated Cumulative Energy",
        )

    def test_historian_input_plots_use_requested_format(self):
        saved_figures = []
        source_frame = pd.DataFrame(
            {
                "timestamp": [
                    "2025-12-15 16:00:00",
                    "2025-12-15 17:00:00",
                ],
                "solaredge_measured_power": [1000.0, 1500.0],
                "solectria_measured_power": [900.0, 1400.0],
                "dni": [700.0, 750.0],
                "ghi": [500.0, 550.0],
                "dhi": [100.0, 110.0],
            }
        )

        def capture(figure, *_args, **_kwargs):
            saved_figures.append(figure)

        with (
            patch.object(pd, "read_csv", return_value=source_frame),
            patch.object(
                matplotlib.figure.Figure,
                "savefig",
                autospec=True,
                side_effect=capture,
            ),
        ):
            plots._render_input_data_plots(
                Path("ignored.csv"),
                Path("ignored"),
            )

        self.assertEqual(len(saved_figures), 2)
        for figure in saved_figures:
            assert_plot_timestamp_format(self, figure.axes[0])

if __name__ == "__main__":
    unittest.main()
