"""Test import side effects must never use the real dashboard output directory."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class TestBootstrapIsolationTests(unittest.TestCase):
    def run_probe(self, output=None):
        environment = dict(os.environ)
        environment.pop("PV_DASHBOARD_OUTPUT_DIR", None)
        if output is not None:
            environment["PV_DASHBOARD_OUTPUT_DIR"] = str(output)
        completed = subprocess.run(
            [sys.executable, "-c", "import tests; from sbepv.api import config; import json; "
             "print(json.dumps({'output':str(config.OUTPUT_DIR.resolve()),"
             "'root':str(config.PROJECT_ROOT.resolve()),'exists':config.OUTPUT_DIR.is_dir()}))"],
            cwd=Path(__file__).resolve().parents[1], env=environment,
            capture_output=True, text=True, timeout=30, check=True,
        )
        return json.loads(completed.stdout)

    def test_plain_unittest_import_uses_temporary_output(self):
        result = self.run_probe()
        self.assertTrue(result["exists"])
        output = Path(result["output"])
        self.assertNotEqual(output, Path(result["root"]) / "outputs")
        self.assertTrue(output.name.startswith("sbepv-tests-"))
        self.assertFalse(output.exists(), "Subprocess temporary output should be cleaned up")

    def test_explicit_runner_output_is_preserved(self):
        with tempfile.TemporaryDirectory(prefix="test-runner-output-") as directory:
            result = self.run_probe(directory)
            self.assertEqual(Path(result["output"]), Path(directory).resolve())
            self.assertTrue(result["exists"])
