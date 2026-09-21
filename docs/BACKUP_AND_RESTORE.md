# Dashboard output backup and recovery

`scripts/dashboard_backup.py` backs up the complete configured output root,
including the SQLite job store, saved bookmarks, baseline lineage, calibration
reviews, frozen Annual sources, TEA evidence, and collection/export artifacts.
It uses Python's SQLite online-backup API and standard library only. It never
imports the application or reads `.env`, never starts workers, and never selects
a production path automatically.

## Before backup

1. Drain or cancel queued/running model, TEA, and collection requests. Wait for
   cancellation cleanup. Stop the API, workers, scheduled jobs, and all other
   processes that write to this output root. Keep them stopped for the backup.
2. Identify the exact `PV_DASHBOARD_OUTPUT_DIR` used by the service. It must
   contain `.agent_state/solar_agent.sqlite3`; do not select only public exports.
3. Prepare a destination parent directory outside any served output or web
   directory. Restrict access to the authorized recovery operators and use the
   company's encrypted storage/retention policy. On Windows, inspect the parent's
   ACL before continuing: new files inherit it. The script's acknowledgement does
   **not** inspect or guarantee Windows ACLs. On POSIX, created directories/files
   use owner-only modes. The backup contains private scientific and chat evidence.

Commands below use explicit example paths; replace them with verified paths.
The destination itself must not exist. Do not use a directory inside the source.

```powershell
python scripts/dashboard_backup.py backup --source 'D:\SBE\outputs' --destination 'E:\PrivateBackups\pv-2026-09-21' --service-stopped --private-storage-confirmed
python scripts/dashboard_backup.py verify --backup 'E:\PrivateBackups\pv-2026-09-21'
```

The script checks active job/collection records and hashes the source before and
after copying. These checks detect common concurrent changes; they cannot prove
that an arbitrary external process is stopped. `--service-stopped` is an operator
assertion, not a switch that stops the service. A valid backup is published only
after source stability and database integrity checks. If a command fails, keep
the service stopped until its cause is understood. An incomplete destination may
remain; do not reuse or restore it. The tool never deletes that directory for you.

The manifest records each artifact's relative path, size, and SHA-256 plus the
original output root. SQLite WAL contents are captured through online backup;
the source WAL, SHM, and rollback-journal files are not restored beside the copied
database. Empty directories are recreated by the application as needed. Symlinks
and Windows reparse points are refused. Hashes detect corruption and missing or
extra files; they do not authenticate a maliciously replaced manifest. Store the
entire backup in trusted private storage. The tool does not encrypt it itself.

## Restore rehearsal or recovery

Some persisted evidence includes absolute paths. This tool **requires restoring
to the original absolute output root**, recorded in the manifest. It refuses a
different path and performs no database rewrites or migrations. A rehearsal on
another machine must provide the same absolute directory location. Cross-platform
relocation is unsupported.

1. Verify the backup before any recovery action. Stop every writer and protect
   access as described above. Keep the existing output root as a separately
   secured rollback copy using an operator-reviewed move or storage snapshot.
   The restore destination must not exist; the script never overwrites it.
2. Run the restore command using the manifest's original output-root location:

```powershell
python scripts/dashboard_backup.py restore --backup 'E:\PrivateBackups\pv-2026-09-21' --destination 'D:\SBE\outputs' --service-stopped --private-storage-confirmed
```

3. The tool compares restored file hashes and checks SQLite integrity before
   reporting success. If verification fails, keep the service stopped. Restore
   creates a new directory but does not switch deployments or start the app.
4. With the matching application revision and supported runtime, start one API
   process in an isolated environment. Open a saved result, inspect its source
   provenance, resolve the promoted baseline, open a completed TEA analysis, and
   download its report and a collection artifact. Verify their identities against
   the backup, then exercise a new synthetic job. Record the outcome before
   approving production recovery.

Application code, runtime packages, environment settings, API credentials, hosting
configuration, and files outside the selected output root are not included.
Preserve these separately through approved deployment and secret-management
procedures. The synthetic automated tests prove file/database reconstruction;
they are not evidence of a completed production disaster-recovery rehearsal.
