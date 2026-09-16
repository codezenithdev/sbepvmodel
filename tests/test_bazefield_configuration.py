"""CLI credentials resolve from the source checkout, independent of launch CWD."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from sbepv.ingest import bazefield

_BAZEFIELD_SCRIPT = Path(bazefield.__file__).resolve()


class BazefieldConfigurationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="bazefield-config-")
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.project = root / "project"
        anchor = self.project / "src" / "sbepv" / "ingest" / "bazefield.py"
        anchor.parent.mkdir(parents=True)
        anchor.touch()
        (self.project / "pyproject.toml").touch()
        (self.project / ".env").write_text("BAZEFIELD_API_KEY=project-fixture\n", encoding="utf-8")
        self.other = root / "unrelated"
        self.other.mkdir()
        (self.other / ".env").write_text("BAZEFIELD_API_KEY=wrong-cwd-fixture\n", encoding="utf-8")
        original_cwd = Path.cwd()
        self.addCleanup(os.chdir, original_cwd)
        os.chdir(self.other)
        environment = patch.dict(os.environ, {}, clear=True)
        environment.start()
        self.addCleanup(environment.stop)
        module_file = patch.object(bazefield, "__file__", str(anchor))
        module_file.start()
        self.addCleanup(module_file.stop)

    def test_default_env_uses_project_landmarks_from_unrelated_cwd(self):
        bazefield.load_dotenv()
        self.assertEqual("project-fixture", os.environ["BAZEFIELD_API_KEY"])

    def test_existing_environment_keeps_precedence(self):
        os.environ["BAZEFIELD_API_KEY"] = "configured-fixture"
        bazefield.load_dotenv()
        self.assertEqual("configured-fixture", os.environ["BAZEFIELD_API_KEY"])

    def test_explicit_env_path_is_still_supported(self):
        bazefield.load_dotenv(self.other / ".env")
        self.assertEqual("wrong-cwd-fixture", os.environ["BAZEFIELD_API_KEY"])

    def test_callable_historian_uses_project_credentials(self):
        with patch.object(bazefield, "BazefieldClient") as client, \
                patch.object(bazefield, "pivot", return_value=[{"fixture": 1}]), \
                patch.object(bazefield, "flatten", return_value=[]), \
                patch.object(bazefield, "write_csv"):
            client.return_value.get_historian.return_value = {}
            self.assertEqual(1, bazefield.run_historian("start", "end", "1h", "unused.csv"))
        client.assert_called_once_with(bazefield.DEFAULT_BASE_URL, "project-fixture")

    def test_direct_script_help_works_from_unrelated_cwd_without_package_install(self):
        existing_files = set(self.other.iterdir())
        completed = subprocess.run(
            [sys.executable, "-I", str(_BAZEFIELD_SCRIPT), "--help"],
            cwd=self.other,
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
        self.assertIn("usage:", completed.stdout)
        self.assertIn("--list-sites", completed.stdout)
        self.assertEqual(completed.stderr, "")
        self.assertEqual(set(self.other.iterdir()), existing_files)
