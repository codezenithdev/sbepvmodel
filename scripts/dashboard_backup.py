"""Offline dashboard backup/verification. Does not import application configuration."""

from __future__ import annotations

import argparse
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import sqlite3
import stat
import sys
from datetime import datetime, timezone


DATABASE = ".agent_state/solar_agent.sqlite3"
MANIFEST = "manifest.json"
ACTIVE_STATES = {"queued", "running", "collecting", "cancelling"}


class BackupError(Exception):
    """A backup safety or integrity check failed."""


def _safe_path(path: Path) -> Path:
    path = path.absolute()
    for part in (path, *path.parents):
        if part.is_symlink() or (part.exists() and getattr(part.lstat(), "st_file_attributes", 0) & 1024):
            raise BackupError("Symbolic links and Windows reparse points are not supported.")
    return path.resolve()


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _inventory(root: Path) -> dict[str, dict]:
    def unreadable_directory(error: OSError) -> None:
        raise BackupError("A directory cannot be read; refusing an incomplete artifact inventory.") from error

    entries = {}
    for directory, folders, filenames in os.walk(root, followlinks=False, onerror=unreadable_directory):
        for name in folders + filenames:
            path = Path(directory) / name
            _safe_path(path)
            info = path.stat()
            relative = path.relative_to(root).as_posix()
            if stat.S_ISDIR(info.st_mode):
                continue
            if not stat.S_ISREG(info.st_mode):
                raise BackupError("Only regular files and directories are supported.")
            if relative == DATABASE + "-shm":
                continue
            digest = _hash(path)
            after = path.stat()
            identity = (info.st_size, info.st_mtime_ns, info.st_ino)
            if identity != (after.st_size, after.st_mtime_ns, after.st_ino):
                raise BackupError("Source changed during inspection; stop all writers and retry.")
            entries[relative] = {
                "size": info.st_size,
                "sha256": digest,
                "mtime_ns": info.st_mtime_ns,
                "inode": info.st_ino,
            }
    return entries


def _readonly_database(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=5)
    connection.execute("PRAGMA query_only=ON")
    return connection


def _check_database(path: Path) -> None:
    with closing(_readonly_database(path)) as connection:
        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise BackupError("SQLite integrity check failed.")
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "jobs" not in tables:
            raise BackupError("The dashboard jobs table is missing.")
        for table in ("jobs", "technoeconomic_jobs"):
            if table not in tables:
                continue
            # Table names are fixed constants, never user input.
            if connection.execute(f"SELECT 1 FROM {table} WHERE state IN ('queued','running','collecting','cancelling') LIMIT 1").fetchone():
                raise BackupError("Active or queued work exists; drain or cancel it before backup.")
            if connection.execute(f"SELECT 1 FROM {table} WHERE state IS NULL OR state NOT IN ('done','error','cancelled','interrupted') LIMIT 1").fetchone():
                raise BackupError("An unknown job state prevents a safe quiescence check.")


def _check_collections(root: Path) -> None:
    for path in (root / ".data_collections").glob("collect_*.json"):
        record = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(record, dict) or "state" not in record:
            raise BackupError("A collection record cannot be checked safely.")
        if record["state"] in ACTIVE_STATES:
            raise BackupError("An active collection exists; drain or cancel it before backup.")
        if record["state"] not in {"completed", "failed", "cancelled"}:
            raise BackupError("An unknown collection state prevents a safe quiescence check.")


def _acknowledge(service_stopped: bool, private_storage: bool) -> None:
    if not service_stopped:
        raise BackupError("Stop the API, workers, schedulers, and other writers; acknowledge with --service-stopped.")
    if not private_storage:
        raise BackupError("Verify restricted destination access; acknowledge with --private-storage-confirmed.")


def _new_destination(source: Path, destination: Path) -> None:
    if destination.exists():
        raise BackupError("Destination already exists; overwriting is refused.")
    if destination.is_relative_to(source) or source.is_relative_to(destination):
        raise BackupError("Source and destination must be separate, non-nested directories.")
    if not destination.parent.is_dir():
        raise BackupError("Create and secure the destination parent directory first.")
    destination.mkdir(mode=0o700)


def _copy_file(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with source.open("rb") as incoming, destination.open("xb") as outgoing:
        shutil.copyfileobj(incoming, outgoing, length=1024 * 1024)
    if os.name != "nt":
        destination.chmod(0o600)


def create_backup(source: Path, destination: Path, *, service_stopped: bool, private_storage: bool) -> dict:
    _acknowledge(service_stopped, private_storage)
    source, destination = _safe_path(source), _safe_path(destination)
    if not source.is_dir() or not (source / DATABASE).is_file():
        raise BackupError("Source must be the complete output root containing the dashboard SQLite database.")
    before = _inventory(source)
    _check_database(source / DATABASE)
    _check_collections(source)
    _new_destination(source, destination)
    payload = destination / "payload"
    payload.mkdir(mode=0o700)
    for relative in before:
        if relative in {DATABASE, DATABASE + "-wal", DATABASE + "-journal"}:
            continue
        _copy_file(source / relative, payload / relative)
    target_db = payload / DATABASE
    target_db.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with closing(_readonly_database(source / DATABASE)) as incoming, closing(sqlite3.connect(target_db)) as outgoing:
        incoming.backup(outgoing)
        outgoing.execute("PRAGMA journal_mode=DELETE")
    if os.name != "nt":
        target_db.chmod(0o600)
    _check_database(target_db)
    _check_collections(source)
    if _inventory(source) != before:
        raise BackupError("Source changed during backup; incomplete destination must not be restored.")
    files = _inventory(payload)
    manifest = {
        "format": "sbepv-output-backup-v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "original_output_root": str(source),
        "restore_requires_original_output_root": True,
        "database": DATABASE,
        "files": {name: {"size": row["size"], "sha256": row["sha256"]} for name, row in sorted(files.items())},
    }
    with (destination / MANIFEST).open("x", encoding="utf-8") as stream:
        json.dump(manifest, stream, indent=2, sort_keys=True)
        stream.write("\n")
    if os.name != "nt":
        (destination / MANIFEST).chmod(0o600)
    return verify_backup(destination)


def verify_backup(backup: Path) -> dict:
    backup = _safe_path(backup)
    _safe_path(backup / MANIFEST)
    manifest = json.loads((backup / MANIFEST).read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or manifest.get("format") != "sbepv-output-backup-v1" or manifest.get("database") != DATABASE:
        raise BackupError("Unsupported backup format.")
    original = manifest.get("original_output_root")
    if not isinstance(original, str) or not Path(original).is_absolute():
        raise BackupError("Backup does not identify a valid original absolute output root.")
    if manifest.get("restore_requires_original_output_root") is not True:
        raise BackupError("Backup does not declare the required restore location.")
    files = manifest.get("files")
    if not isinstance(files, dict) or DATABASE not in files:
        raise BackupError("Backup manifest is incomplete.")
    for name in files:
        relative = PurePosixPath(name)
        if relative.is_absolute() or ".." in relative.parts or "\\" in name or ":" in name or relative.as_posix() != name:
            raise BackupError("Unsafe artifact path in backup manifest.")
    payload = _safe_path(backup / "payload")
    if not payload.is_dir():
        raise BackupError("Backup payload directory is missing.")
    actual = _inventory(payload)
    if set(actual) != set(files):
        raise BackupError("Backup artifact inventory does not match the manifest.")
    for name, expected in files.items():
        if expected != {"size": actual[name]["size"], "sha256": actual[name]["sha256"]}:
            raise BackupError("Backup artifact hash or size does not match the manifest.")
    _check_database(payload / DATABASE)
    _check_collections(payload)
    return manifest


def restore_backup(backup: Path, destination: Path, *, service_stopped: bool, private_storage: bool) -> dict:
    _acknowledge(service_stopped, private_storage)
    backup, destination = _safe_path(backup), _safe_path(destination)
    manifest = verify_backup(backup)
    original = Path(manifest.get("original_output_root", ""))
    if not original.is_absolute() or destination != _safe_path(original):
        raise BackupError("Restore requires the original absolute output root; relocation is unsupported.")
    _new_destination(backup, destination)
    for relative in manifest["files"]:
        _copy_file(backup / "payload" / relative, destination / relative)
    actual = _inventory(destination)
    restored = {name: {"size": row["size"], "sha256": row["sha256"]} for name, row in actual.items()}
    if restored != manifest["files"]:
        raise BackupError("Restored files failed verification; keep the service stopped.")
    _check_database(destination / DATABASE)
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    backup = commands.add_parser("backup")
    backup.add_argument("--source", required=True, type=Path)
    backup.add_argument("--destination", required=True, type=Path)
    verify = commands.add_parser("verify")
    verify.add_argument("--backup", required=True, type=Path)
    restore = commands.add_parser("restore")
    restore.add_argument("--backup", required=True, type=Path)
    restore.add_argument("--destination", required=True, type=Path)
    for command in (backup, restore):
        command.add_argument("--service-stopped", action="store_true")
        command.add_argument("--private-storage-confirmed", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "verify":
            result = verify_backup(args.backup)
        else:
            options = {"service_stopped": args.service_stopped, "private_storage": args.private_storage_confirmed}
            result = create_backup(args.source, args.destination, **options) if args.command == "backup" else restore_backup(args.backup, args.destination, **options)
        print(f"{args.command.capitalize()} verified: {len(result['files'])} files. Private contents were not printed.")
        return 0
    except BackupError as exc:
        print(f"Refused: {exc}", file=sys.stderr)
    except (OSError, sqlite3.Error, ValueError, TypeError, KeyError):
        print("Failed: files or database could not be verified. Keep the service stopped; an incomplete destination may remain.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
