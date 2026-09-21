from __future__ import annotations

from contextlib import closing, redirect_stderr, redirect_stdout
import importlib.util
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location(
    "dashboard_backup", Path(__file__).resolve().parents[1] / "scripts" / "dashboard_backup.py"
)
backup = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(backup)


class DashboardBackupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="sbepv-backup-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.source = self.root / "output"
        self.destination = self.root / "backup"
        (self.source / ".agent_state").mkdir(parents=True)
        with closing(sqlite3.connect(self.source / backup.DATABASE)) as connection:
            connection.executescript("""
                CREATE TABLE jobs(job_id TEXT PRIMARY KEY, state TEXT, artifact_path TEXT);
                CREATE TABLE technoeconomic_jobs(tea_job_id TEXT PRIMARY KEY, state TEXT);
                CREATE TABLE saved_results(job_id TEXT PRIMARY KEY, name TEXT);
                CREATE TABLE current_baselines(mode TEXT PRIMARY KEY, job_id TEXT);
            """)
            connection.execute("INSERT INTO jobs VALUES (?, ?, ?)", ("annual_fixture", "done", str(self.source / "annual_fixture" / "result.json")))
            connection.execute("INSERT INTO technoeconomic_jobs VALUES ('tea_fixture', 'done')")
            connection.execute("INSERT INTO saved_results VALUES ('annual_fixture', 'Synthetic saved result')")
            connection.execute("INSERT INTO current_baselines VALUES ('annual', 'annual_fixture')")
            connection.commit()
        for relative, content in {
            "annual_fixture/result.json": '{"synthetic":true}',
            ".annual_sources/sha256/ab/frozen.csv": "timestamp,value\nfixture,1\n",
            ".technoeconomic_attempts/tea_fixture/report.pdf": "synthetic-pdf-fixture",
            ".calibration_reviews/review.json": '{"synthetic":true}',
            ".data_collections/collect_fixture.json": '{"state":"completed"}',
            ".data_collections/collect_fixture.csv": "fixture,1\n",
        }.items():
            path = self.source / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        self.options = {"service_stopped": True, "private_storage": True}

    def create(self):
        return backup.create_backup(self.source, self.destination, **self.options)

    def test_complete_backup_restores_original_paths_and_all_private_artifacts(self) -> None:
        original = backup._inventory(self.source)
        manifest = self.create()
        self.assertEqual(set(manifest["files"]), set(original))
        self.assertEqual(manifest["original_output_root"], str(self.source))
        self.assertEqual(backup.verify_backup(self.destination), manifest)
        self.source.rename(self.root / "retained-original")
        backup.restore_backup(self.destination, self.source, **self.options)
        with closing(sqlite3.connect(self.source / backup.DATABASE)) as connection:
            artifact = Path(connection.execute("SELECT artifact_path FROM jobs").fetchone()[0])
            self.assertTrue(artifact.is_file())
            self.assertEqual(connection.execute("SELECT name FROM saved_results").fetchone()[0], "Synthetic saved result")
            self.assertEqual(connection.execute("SELECT job_id FROM current_baselines").fetchone()[0], "annual_fixture")
        self.assertEqual((self.source / ".annual_sources/sha256/ab/frozen.csv").read_text(), "timestamp,value\nfixture,1\n")

    def test_online_sqlite_backup_includes_committed_wal_rows(self) -> None:
        with closing(sqlite3.connect(self.source / backup.DATABASE)) as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("INSERT INTO saved_results VALUES ('wal_fixture', 'From WAL')")
            connection.commit()
            self.assertTrue(Path(str(self.source / backup.DATABASE) + "-wal").exists())
            manifest = self.create()
            self.assertNotIn(backup.DATABASE + "-wal", manifest["files"])
            self.assertNotIn(backup.DATABASE + "-shm", manifest["files"])
        with closing(sqlite3.connect(self.destination / "payload" / backup.DATABASE)) as restored:
            self.assertEqual(restored.execute("SELECT name FROM saved_results WHERE job_id='wal_fixture'").fetchone()[0], "From WAL")

    def test_active_jobs_tea_and_collection_refuse_before_destination_creation(self) -> None:
        for table in ("jobs", "technoeconomic_jobs"):
            with self.subTest(table=table):
                with closing(sqlite3.connect(self.source / backup.DATABASE)) as connection:
                    connection.execute(f"UPDATE {table} SET state='running'")
                    connection.commit()
                with self.assertRaisesRegex(backup.BackupError, "Active or queued"):
                    self.create()
                self.assertFalse(self.destination.exists())
                with closing(sqlite3.connect(self.source / backup.DATABASE)) as connection:
                    connection.execute(f"UPDATE {table} SET state='done'")
                    connection.commit()
        (self.source / ".data_collections/collect_fixture.json").write_text('{"state":"cancelling"}')
        with self.assertRaisesRegex(backup.BackupError, "active collection"):
            self.create()
        self.assertFalse(self.destination.exists())

    def test_mutating_source_leaves_no_valid_manifest(self) -> None:
        real_copy = backup._copy_file
        changed = False

        def mutate(source, destination):
            nonlocal changed
            real_copy(source, destination)
            if not changed:
                changed = True
                (self.source / "annual_fixture/result.json").write_text('{"changed":true}')

        with patch.object(backup, "_copy_file", side_effect=mutate):
            with self.assertRaisesRegex(backup.BackupError, "Source changed"):
                self.create()
        self.assertFalse((self.destination / backup.MANIFEST).exists())

    def test_unreadable_directory_and_unknown_state_fail_closed(self) -> None:
        def unreadable(*args, **kwargs):
            kwargs["onerror"](PermissionError("private fixture"))
            return iter(())

        with patch.object(backup.os, "walk", side_effect=unreadable):
            with self.assertRaisesRegex(backup.BackupError, "incomplete artifact inventory"):
                self.create()
        with closing(sqlite3.connect(self.source / backup.DATABASE)) as connection:
            connection.execute("UPDATE jobs SET state='unexpected'")
            connection.commit()
        with self.assertRaisesRegex(backup.BackupError, "unknown job state"):
            self.create()
        self.assertFalse(self.destination.exists())

    def test_corrupted_missing_and_extra_artifacts_fail_verification(self) -> None:
        self.create()
        path = self.destination / "payload/annual_fixture/result.json"
        original = path.read_bytes()
        path.write_bytes(b"corrupt")
        with self.assertRaisesRegex(backup.BackupError, "hash or size"):
            backup.verify_backup(self.destination)
        path.unlink()
        with self.assertRaisesRegex(backup.BackupError, "inventory"):
            backup.verify_backup(self.destination)
        path.write_bytes(original)
        (self.destination / "payload/unexpected.txt").write_text("extra")
        with self.assertRaisesRegex(backup.BackupError, "inventory"):
            backup.verify_backup(self.destination)

    def test_acknowledgements_no_overwrite_no_relocation_and_non_nested_paths(self) -> None:
        for options in ({"service_stopped": False, "private_storage": True}, {"service_stopped": True, "private_storage": False}):
            with self.assertRaises(backup.BackupError):
                backup.create_backup(self.source, self.destination, **options)
        with self.assertRaisesRegex(backup.BackupError, "non-nested"):
            backup.create_backup(self.source, self.source / "backup", **self.options)
        self.create()
        with self.assertRaisesRegex(backup.BackupError, "already exists"):
            self.create()
        with self.assertRaisesRegex(backup.BackupError, "original absolute"):
            backup.restore_backup(self.destination, self.root / "relocated", **self.options)
        with self.assertRaisesRegex(backup.BackupError, "already exists"):
            backup.restore_backup(self.destination, self.source, **self.options)

    def test_manifest_traversal_and_linked_sources_are_rejected(self) -> None:
        self.create()
        path = self.destination / backup.MANIFEST
        manifest = json.loads(path.read_text())
        manifest["files"]["../outside"] = {"size": 0, "sha256": "x"}
        path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(backup.BackupError, "Unsafe artifact path"):
            backup.verify_backup(self.destination)
        # Windows symlink creation may require developer mode; exercise the
        # same explicit link guard without changing system privileges.
        with patch.object(Path, "is_symlink", return_value=True):
            with self.assertRaisesRegex(backup.BackupError, "Symbolic links"):
                backup._safe_path(self.source)

    def test_cli_prints_only_summary_and_does_not_expose_private_file_contents(self) -> None:
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = backup.main(["backup", "--source", str(self.source), "--destination", str(self.destination), "--service-stopped", "--private-storage-confirmed"])
        self.assertEqual(code, 0, stderr.getvalue())
        self.assertIn("Backup verified:", stdout.getvalue())
        self.assertNotIn("Synthetic saved result", stdout.getvalue())
        self.assertNotIn("result.json", stdout.getvalue())
        self.assertEqual(stderr.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
