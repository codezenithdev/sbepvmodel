"""Durable SQLite state for dashboard model jobs and agent proposals.

The store deliberately owns persistence and state transitions only.  Model execution,
request validation, and HTTP serialization stay in ``app.py``.  Every public method
returns ordinary dictionaries so the store is easy to integrate with FastAPI.
"""

from __future__ import annotations

import json
import math
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping, Sequence


SCHEMA_VERSION = 4
SAVED_RESULTS_LIMIT = 10
PROPOSAL_STATES = frozenset(
    {"pending", "confirmed", "superseded", "dismissed", "expired"}
)
JOB_STATES = frozenset(
    {"queued", "running", "done", "error", "cancelled", "interrupted"}
)
MODES = frozenset({"validation", "annual"})
COMPARISON_KINDS = frozenset({"same_input", "cross_run"})


class AgentStoreError(RuntimeError):
    """Base class for persistence and state-transition failures."""


class RecordNotFound(AgentStoreError):
    """Raised when an update targets an unknown proposal or job."""


class InvalidStateTransition(AgentStoreError):
    """Raised when a proposal or job cannot move to the requested state."""


class StoreConflict(AgentStoreError):
    """Raised when a transaction conflicts with existing durable state."""


class QueueCapacityExceeded(StoreConflict):
    """Raised when accepting another job would exceed the active queue limit."""


class LeaseOwnershipLost(StoreConflict):
    """Raised when a runner no longer owns the lease for a running job."""


class SchemaVersionError(AgentStoreError):
    """Raised when the database was created by a newer application version."""


_UNSET = object()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _timestamp(value: datetime) -> str:
    return _as_utc(value).isoformat(timespec="microseconds")


def _parse_timestamp(value: str) -> datetime:
    return _as_utc(datetime.fromisoformat(value))


def _json_dump(value: Any) -> str:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("value must be JSON serializable and contain no NaN/Infinity") from exc


def _json_load(value: str | None) -> Any:
    return None if value is None else json.loads(value)


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


class AgentStore:
    """Thread-safe durable storage for proposals, jobs, and promoted baselines.

    A fresh SQLite connection is used per operation.  Writes use
    ``BEGIN IMMEDIATE`` and a process-local re-entrant lock, which makes compound
    operations atomic both between threads and between multiple store instances.
    """

    def __init__(
        self,
        database_path: str | Path,
        *,
        now: Callable[[], datetime] | None = None,
        busy_timeout_ms: int = 10_000,
    ) -> None:
        self.path = Path(database_path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._now = now or _utc_now
        self._busy_timeout_ms = int(busy_timeout_ms)
        self._lock = threading.RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            str(self.path),
            timeout=max(self._busy_timeout_ms / 1000, 0.1),
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(f"PRAGMA busy_timeout = {self._busy_timeout_ms}")
        return connection

    @contextmanager
    def _transaction(self, *, write: bool = False) -> Iterator[sqlite3.Connection]:
        with self._lock:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
                yield connection
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            finally:
                connection.close()

    def _initialize(self) -> None:
        with self._lock:
            connection = self._connect()
            try:
                version = int(connection.execute("PRAGMA user_version").fetchone()[0])
                if version > SCHEMA_VERSION:
                    raise SchemaVersionError(
                        f"database schema {version} is newer than supported schema "
                        f"{SCHEMA_VERSION}"
                    )
                connection.execute("PRAGMA journal_mode = WAL")
                if version == 0:
                    self._migrate_v1(connection)
                    version = 1
                if version < 2:
                    self._migrate_v2(connection)
                    version = 2
                if version < 3:
                    self._migrate_v3(connection)
                    version = 3
                if version < 4:
                    self._migrate_v4(connection)
            finally:
                connection.close()

    def _migrate_v1(self, connection: sqlite3.Connection) -> None:
        applied_at = _timestamp(self._current_time())
        connection.executescript(
            """
            BEGIN IMMEDIATE;

            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS proposals (
                proposal_id TEXT PRIMARY KEY,
                state TEXT NOT NULL CHECK (
                    state IN ('pending','confirmed','superseded','dismissed','expired')
                ),
                mode TEXT NOT NULL CHECK (mode IN ('validation','annual')),
                baseline_id TEXT,
                comparison_kind TEXT NOT NULL CHECK (
                    comparison_kind IN ('same_input','cross_run')
                ),
                effective_request_json TEXT NOT NULL,
                changes_json TEXT NOT NULL,
                confirmation_required INTEGER NOT NULL CHECK (
                    confirmation_required IN (0,1)
                ),
                confirmation_reason TEXT,
                confirmation_metadata_json TEXT NOT NULL,
                supersedes_id TEXT REFERENCES proposals(proposal_id),
                superseded_by_id TEXT REFERENCES proposals(proposal_id),
                confirmed_job_id TEXT,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                confirmed_at TEXT,
                superseded_at TEXT,
                dismissed_at TEXT,
                expired_at TEXT
            );

            CREATE TABLE IF NOT EXISTS jobs (
                job_id TEXT PRIMARY KEY,
                state TEXT NOT NULL CHECK (
                    state IN ('queued','running','done','error','cancelled','interrupted')
                ),
                kind TEXT NOT NULL,
                mode TEXT NOT NULL CHECK (mode IN ('validation','annual')),
                baseline_id TEXT,
                proposal_id TEXT REFERENCES proposals(proposal_id),
                request_json TEXT NOT NULL,
                result_json TEXT,
                comparison_json TEXT,
                provenance_json TEXT,
                artifacts_json TEXT,
                progress REAL NOT NULL DEFAULT 0 CHECK (progress >= 0 AND progress <= 100),
                stage TEXT NOT NULL DEFAULT 'Queued',
                source_path TEXT,
                source_hash TEXT,
                cancel_requested INTEGER NOT NULL DEFAULT 0 CHECK (
                    cancel_requested IN (0,1)
                ),
                error TEXT,
                created_at TEXT NOT NULL,
                queued_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                started_at TEXT,
                completed_at TEXT,
                cancel_requested_at TEXT,
                interrupted_at TEXT
            );

            CREATE TABLE IF NOT EXISTS current_baselines (
                mode TEXT PRIMARY KEY CHECK (mode IN ('validation','annual')),
                job_id TEXT NOT NULL REFERENCES jobs(job_id),
                previous_job_id TEXT REFERENCES jobs(job_id),
                promoted_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS baseline_promotions (
                promotion_id INTEGER PRIMARY KEY AUTOINCREMENT,
                mode TEXT NOT NULL CHECK (mode IN ('validation','annual')),
                job_id TEXT NOT NULL REFERENCES jobs(job_id),
                previous_job_id TEXT REFERENCES jobs(job_id),
                promoted_at TEXT NOT NULL
            );

            CREATE UNIQUE INDEX IF NOT EXISTS proposals_confirmed_job_unique
                ON proposals(confirmed_job_id)
                WHERE confirmed_job_id IS NOT NULL;
            CREATE UNIQUE INDEX IF NOT EXISTS jobs_proposal_unique
                ON jobs(proposal_id)
                WHERE proposal_id IS NOT NULL;
            CREATE INDEX IF NOT EXISTS proposals_state_created_idx
                ON proposals(state, created_at);
            CREATE INDEX IF NOT EXISTS jobs_state_queued_idx
                ON jobs(state, queued_at);
            CREATE INDEX IF NOT EXISTS jobs_mode_created_idx
                ON jobs(mode, created_at DESC);

            CREATE TRIGGER IF NOT EXISTS proposals_payload_is_immutable
            BEFORE UPDATE OF effective_request_json, changes_json ON proposals
            BEGIN
                SELECT RAISE(ABORT, 'proposal request and changes are immutable');
            END;

            CREATE TRIGGER IF NOT EXISTS job_request_is_immutable
            BEFORE UPDATE OF request_json ON jobs
            BEGIN
                SELECT RAISE(ABORT, 'job request is immutable');
            END;
            """
        )
        connection.execute(
            "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (?, ?)",
            (1, applied_at),
        )
        connection.execute("PRAGMA user_version = 1")
        connection.commit()

    def _migrate_v2(self, connection: sqlite3.Connection) -> None:
        """Add process ownership and renewable leases to running jobs."""

        applied_at = _timestamp(self._current_time())
        connection.execute("BEGIN IMMEDIATE")
        try:
            columns = {
                str(row[1]) for row in connection.execute("PRAGMA table_info(jobs)")
            }
            if "worker_id" not in columns:
                connection.execute("ALTER TABLE jobs ADD COLUMN worker_id TEXT")
            if "heartbeat_at" not in columns:
                connection.execute("ALTER TABLE jobs ADD COLUMN heartbeat_at TEXT")
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                (2, applied_at),
            )
            connection.execute("PRAGMA user_version = 2")
            connection.commit()
        except Exception:
            connection.rollback()
            raise

    def _migrate_v3(self, connection: sqlite3.Connection) -> None:
        """Add a unique token so each individual job lease can be fenced."""

        applied_at = _timestamp(self._current_time())
        connection.execute("BEGIN IMMEDIATE")
        try:
            columns = {
                str(row[1]) for row in connection.execute("PRAGMA table_info(jobs)")
            }
            if "lease_token" not in columns:
                connection.execute("ALTER TABLE jobs ADD COLUMN lease_token TEXT")
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                (3, applied_at),
            )
            connection.execute("PRAGMA user_version = 3")
            connection.commit()
        except Exception:
            connection.rollback()
            raise

    def _migrate_v4(self, connection: sqlite3.Connection) -> None:
        """Add the bounded durable collection of explicitly saved results."""

        applied_at = _timestamp(self._current_time())
        connection.execute("BEGIN IMMEDIATE")
        try:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS saved_results (
                    job_id TEXT PRIMARY KEY REFERENCES jobs(job_id) ON DELETE RESTRICT,
                    name TEXT NOT NULL,
                    saved_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS saved_results_saved_at_idx
                    ON saved_results(saved_at DESC, job_id DESC)
                """
            )
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                (4, applied_at),
            )
            connection.execute("PRAGMA user_version = 4")
            connection.commit()
        except Exception:
            connection.rollback()
            raise

    def _current_time(self) -> datetime:
        return _as_utc(self._now())

    @property
    def schema_version(self) -> int:
        with self._transaction() as connection:
            return int(connection.execute("PRAGMA user_version").fetchone()[0])

    @staticmethod
    def _validate_mode(mode: str) -> None:
        if mode not in MODES:
            raise ValueError(f"mode must be one of {sorted(MODES)}")

    @staticmethod
    def _validate_comparison_kind(comparison_kind: str) -> None:
        if comparison_kind not in COMPARISON_KINDS:
            raise ValueError(
                f"comparison_kind must be one of {sorted(COMPARISON_KINDS)}"
            )

    @staticmethod
    def _proposal_from_row(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        result = dict(row)
        result["id"] = result.pop("proposal_id")
        result["effective_request"] = _json_load(result.pop("effective_request_json"))
        result["changes"] = _json_load(result.pop("changes_json"))
        result["confirmation_metadata"] = _json_load(
            result.pop("confirmation_metadata_json")
        )
        result["confirmation_required"] = bool(result["confirmation_required"])
        return result

    @staticmethod
    def _job_from_row(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        result = dict(row)
        result["id"] = result.pop("job_id")
        for field in ("request", "result", "comparison", "provenance", "artifacts"):
            result[field] = _json_load(result.pop(f"{field}_json"))
        result["cancel_requested"] = bool(result["cancel_requested"])
        # Older rows may predate interrupted jobs receiving ``completed_at``.
        # Treat the interruption timestamp as their terminal timestamp so
        # elapsed-duration consumers do not keep counting after the job stops.
        if result["state"] == "interrupted" and not result.get("completed_at"):
            result["completed_at"] = result.get("interrupted_at")
        return result

    @staticmethod
    def _expire_due(
        connection: sqlite3.Connection, now_text: str
    ) -> int:
        cursor = connection.execute(
            """
            UPDATE proposals
               SET state = 'expired', updated_at = ?, expired_at = ?
             WHERE state = 'pending' AND expires_at <= ?
            """,
            (now_text, now_text, now_text),
        )
        return int(cursor.rowcount)

    def expire_proposals(self) -> int:
        now_text = _timestamp(self._current_time())
        with self._transaction(write=True) as connection:
            return self._expire_due(connection, now_text)

    def create_proposal(
        self,
        *,
        mode: str,
        effective_request: Mapping[str, Any],
        changes: Any,
        baseline_id: str | None,
        comparison_kind: str,
        confirmation_required: bool,
        confirmation_reason: str | None = None,
        confirmation_metadata: Mapping[str, Any] | None = None,
        expires_at: datetime | None = None,
        proposal_id: str | None = None,
        supersedes_id: str | None = None,
    ) -> dict[str, Any]:
        """Create a pending immutable proposal.

        When ``supersedes_id`` is supplied, creation of the replacement and the
        pending -> superseded transition are committed atomically.
        """

        self._validate_mode(mode)
        self._validate_comparison_kind(comparison_kind)
        now = self._current_time()
        expiry = _as_utc(expires_at) if expires_at else now + timedelta(hours=24)
        if expiry <= now:
            raise ValueError("expires_at must be in the future")
        proposal_id = proposal_id or _new_id("proposal")
        effective_json = _json_dump(dict(effective_request))
        # UI proposal cards use an ordered list of field changes.  Preserve the
        # caller's JSON shape rather than coercing lists into mappings.
        changes_json = _json_dump(changes)
        metadata_json = _json_dump(dict(confirmation_metadata or {}))
        now_text = _timestamp(now)
        expiry_text = _timestamp(expiry)

        with self._transaction(write=True) as connection:
            self._expire_due(connection, now_text)
            if supersedes_id:
                prior = connection.execute(
                    "SELECT * FROM proposals WHERE proposal_id = ?", (supersedes_id,)
                ).fetchone()
                if prior is None:
                    raise RecordNotFound(f"unknown proposal: {supersedes_id}")
                if prior["state"] != "pending":
                    raise InvalidStateTransition(
                        f"cannot supersede proposal in state {prior['state']}"
                    )
            try:
                connection.execute(
                    """
                    INSERT INTO proposals (
                        proposal_id, state, mode, baseline_id, comparison_kind,
                        effective_request_json, changes_json, confirmation_required,
                        confirmation_reason, confirmation_metadata_json,
                        supersedes_id, created_at, expires_at, updated_at
                    ) VALUES (?, 'pending', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        proposal_id,
                        mode,
                        baseline_id,
                        comparison_kind,
                        effective_json,
                        changes_json,
                        int(bool(confirmation_required)),
                        confirmation_reason,
                        metadata_json,
                        supersedes_id,
                        now_text,
                        expiry_text,
                        now_text,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise StoreConflict(f"proposal id already exists: {proposal_id}") from exc

            if supersedes_id:
                connection.execute(
                    """
                    UPDATE proposals
                       SET state = 'superseded', superseded_by_id = ?,
                           superseded_at = ?, updated_at = ?
                     WHERE proposal_id = ? AND state = 'pending'
                    """,
                    (proposal_id, now_text, now_text, supersedes_id),
                )
            row = connection.execute(
                "SELECT * FROM proposals WHERE proposal_id = ?", (proposal_id,)
            ).fetchone()
        return self._proposal_from_row(row)  # type: ignore[return-value]

    def get_proposal(self, proposal_id: str) -> dict[str, Any] | None:
        now_text = _timestamp(self._current_time())
        with self._transaction(write=True) as connection:
            self._expire_due(connection, now_text)
            row = connection.execute(
                "SELECT * FROM proposals WHERE proposal_id = ?", (proposal_id,)
            ).fetchone()
        return self._proposal_from_row(row)

    def list_proposals(
        self,
        *,
        states: Sequence[str] | None = None,
        mode: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        if mode is not None:
            self._validate_mode(mode)
        if states is not None:
            unknown = set(states) - PROPOSAL_STATES
            if unknown:
                raise ValueError(f"unknown proposal states: {sorted(unknown)}")
        if limit <= 0:
            return []
        clauses: list[str] = []
        parameters: list[Any] = []
        if states:
            clauses.append(f"state IN ({','.join('?' for _ in states)})")
            parameters.extend(states)
        if mode:
            clauses.append("mode = ?")
            parameters.append(mode)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        parameters.append(int(limit))
        now_text = _timestamp(self._current_time())
        with self._transaction(write=True) as connection:
            self._expire_due(connection, now_text)
            rows = connection.execute(
                f"SELECT * FROM proposals {where} "
                "ORDER BY created_at DESC, proposal_id DESC LIMIT ?",
                parameters,
            ).fetchall()
        return [self._proposal_from_row(row) for row in rows]  # type: ignore[misc]

    def update_proposal(
        self,
        proposal_id: str,
        *,
        state: str | None = None,
        confirmation_metadata: Mapping[str, Any] | None | object = _UNSET,
        superseded_by_id: str | None = None,
    ) -> dict[str, Any]:
        """Update mutable proposal metadata or a non-confirmation state.

        Confirmation must use :meth:`confirm_proposal`, which atomically creates
        the candidate job.  Proposal request and changes are immutable by API and
        by database triggers.
        """

        if state == "confirmed":
            raise InvalidStateTransition("use confirm_proposal to confirm a proposal")
        if state is not None and state not in PROPOSAL_STATES:
            raise ValueError(f"unknown proposal state: {state}")
        now_text = _timestamp(self._current_time())
        with self._transaction(write=True) as connection:
            self._expire_due(connection, now_text)
            row = connection.execute(
                "SELECT * FROM proposals WHERE proposal_id = ?", (proposal_id,)
            ).fetchone()
            if row is None:
                raise RecordNotFound(f"unknown proposal: {proposal_id}")

            assignments = ["updated_at = ?"]
            values: list[Any] = [now_text]
            if confirmation_metadata is not _UNSET:
                assignments.append("confirmation_metadata_json = ?")
                values.append(_json_dump(dict(confirmation_metadata or {})))
            if state is not None and state != row["state"]:
                if row["state"] != "pending" or state not in {
                    "dismissed",
                    "expired",
                    "superseded",
                }:
                    raise InvalidStateTransition(
                        f"cannot move proposal from {row['state']} to {state}"
                    )
                assignments.append("state = ?")
                values.append(state)
                assignments.append(f"{state}_at = ?")
                values.append(now_text)
                if state == "superseded":
                    if not superseded_by_id:
                        raise ValueError("superseded_by_id is required")
                    replacement = connection.execute(
                        "SELECT proposal_id FROM proposals WHERE proposal_id = ?",
                        (superseded_by_id,),
                    ).fetchone()
                    if replacement is None:
                        raise RecordNotFound(
                            f"unknown replacement proposal: {superseded_by_id}"
                        )
                    assignments.append("superseded_by_id = ?")
                    values.append(superseded_by_id)

            values.append(proposal_id)
            connection.execute(
                f"UPDATE proposals SET {', '.join(assignments)} WHERE proposal_id = ?",
                values,
            )
            updated = connection.execute(
                "SELECT * FROM proposals WHERE proposal_id = ?", (proposal_id,)
            ).fetchone()
        return self._proposal_from_row(updated)  # type: ignore[return-value]

    def dismiss_proposal(self, proposal_id: str) -> dict[str, Any]:
        return self.update_proposal(proposal_id, state="dismissed")

    @staticmethod
    def _insert_job(
        connection: sqlite3.Connection,
        *,
        job_id: str,
        kind: str,
        mode: str,
        request_json: str,
        baseline_id: str | None,
        proposal_id: str | None,
        source_path: str | None,
        source_hash: str | None,
        provenance_json: str | None,
        artifacts_json: str | None,
        now_text: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO jobs (
                job_id, state, kind, mode, baseline_id, proposal_id, request_json,
                provenance_json, artifacts_json, progress, stage, source_path,
                source_hash, cancel_requested, created_at, queued_at, updated_at
            ) VALUES (?, 'queued', ?, ?, ?, ?, ?, ?, ?, 0, 'Queued', ?, ?, 0, ?, ?, ?)
            """,
            (
                job_id,
                kind,
                mode,
                baseline_id,
                proposal_id,
                request_json,
                provenance_json,
                artifacts_json,
                source_path,
                source_hash,
                now_text,
                now_text,
                now_text,
            ),
        )

    @staticmethod
    def _ensure_queue_capacity(
        connection: sqlite3.Connection,
        *,
        max_active_jobs: int | None,
        required: int = 1,
    ) -> None:
        if max_active_jobs is None:
            return
        limit = int(max_active_jobs)
        required_slots = int(required)
        if limit < 1:
            raise ValueError("max_active_jobs must be at least 1")
        if required_slots < 1:
            raise ValueError("required must be at least 1")
        active = int(
            connection.execute(
                "SELECT COUNT(*) FROM jobs WHERE state IN ('queued','running')"
            ).fetchone()[0]
        )
        if active + required_slots > limit:
            raise QueueCapacityExceeded(
                f"model queue is full ({active}/{limit} active jobs)"
            )

    def ensure_job_capacity(self, *, max_active_jobs: int, required: int = 1) -> None:
        """Fail when a requested batch cannot fit in the active queue."""

        with self._transaction(write=True) as connection:
            self._ensure_queue_capacity(
                connection,
                max_active_jobs=max_active_jobs,
                required=required,
            )

    def confirm_proposal(
        self,
        proposal_id: str,
        *,
        job_id: str | None = None,
        job_kind: str = "candidate",
        confirmation_metadata: Mapping[str, Any] | None = None,
        source_path: str | None = None,
        source_hash: str | None = None,
        provenance: Mapping[str, Any] | None = None,
        max_active_jobs: int | None = None,
    ) -> dict[str, Any]:
        """Confirm once and atomically enqueue exactly one candidate job.

        Repeated or concurrent confirmations return the original job unchanged.
        """

        return self.confirm_proposals_batch(
            [
                {
                    "proposal_id": proposal_id,
                    "job_id": job_id,
                    "job_kind": job_kind,
                    "confirmation_metadata": confirmation_metadata,
                    "source_path": source_path,
                    "source_hash": source_hash,
                    "provenance": provenance,
                }
            ],
            max_active_jobs=max_active_jobs,
        )[0]

    def confirm_proposals_batch(
        self,
        confirmations: Sequence[Mapping[str, Any]],
        *,
        max_active_jobs: int | None = None,
    ) -> list[dict[str, Any]]:
        """Confirm a proposal batch and enqueue all of its jobs atomically.

        Already-confirmed proposals are returned idempotently and consume no new
        capacity. Every still-pending proposal is validated, capacity-checked,
        inserted, and marked confirmed in one ``BEGIN IMMEDIATE`` transaction.
        Any error therefore leaves the entire pending portion unchanged.
        """

        if not confirmations:
            raise ValueError("confirmations must not be empty")

        prepared: list[dict[str, Any]] = []
        proposal_ids: set[str] = set()
        for raw in confirmations:
            proposal_id = str(raw.get("proposal_id") or "").strip()
            if not proposal_id:
                raise ValueError("proposal_id must not be blank")
            if proposal_id in proposal_ids:
                raise ValueError(f"duplicate proposal id: {proposal_id}")
            proposal_ids.add(proposal_id)

            job_kind = str(raw.get("job_kind", "candidate") or "").strip()
            if not job_kind:
                raise ValueError("job_kind must not be blank")
            requested_job_id = str(raw.get("job_id") or _new_id("job")).strip()
            if not requested_job_id:
                raise ValueError("job_id must not be blank")
            confirmation_metadata = raw.get("confirmation_metadata")
            provenance = raw.get("provenance")
            prepared.append(
                {
                    "proposal_id": proposal_id,
                    "job_id": requested_job_id,
                    "job_kind": job_kind,
                    "confirmation_metadata": dict(confirmation_metadata or {}),
                    "source_path": raw.get("source_path"),
                    "source_hash": raw.get("source_hash"),
                    "provenance_json": (
                        None if provenance is None else _json_dump(dict(provenance))
                    ),
                }
            )

        now_text = _timestamp(self._current_time())
        with self._transaction(write=True) as connection:
            self._expire_due(connection, now_text)
            pending: list[tuple[dict[str, Any], sqlite3.Row]] = []
            jobs_by_proposal: dict[str, sqlite3.Row] = {}
            for item in prepared:
                proposal = connection.execute(
                    "SELECT * FROM proposals WHERE proposal_id = ?",
                    (item["proposal_id"],),
                ).fetchone()
                if proposal is None:
                    raise RecordNotFound(
                        f"unknown proposal: {item['proposal_id']}"
                    )
                if proposal["confirmed_job_id"]:
                    existing = connection.execute(
                        "SELECT * FROM jobs WHERE job_id = ?",
                        (proposal["confirmed_job_id"],),
                    ).fetchone()
                    if existing is None:
                        raise StoreConflict(
                            "confirmed proposal references a missing job"
                        )
                    jobs_by_proposal[item["proposal_id"]] = existing
                    continue
                if proposal["state"] != "pending":
                    raise InvalidStateTransition(
                        f"cannot confirm proposal in state {proposal['state']}"
                    )
                pending.append((item, proposal))

            if pending:
                self._ensure_queue_capacity(
                    connection,
                    max_active_jobs=max_active_jobs,
                    required=len(pending),
                )

            try:
                for item, proposal in pending:
                    existing_metadata = _json_load(
                        proposal["confirmation_metadata_json"]
                    )
                    existing_metadata.update(item["confirmation_metadata"])
                    self._insert_job(
                        connection,
                        job_id=item["job_id"],
                        kind=item["job_kind"],
                        mode=proposal["mode"],
                        request_json=proposal["effective_request_json"],
                        baseline_id=proposal["baseline_id"],
                        proposal_id=item["proposal_id"],
                        source_path=item["source_path"],
                        source_hash=item["source_hash"],
                        provenance_json=item["provenance_json"],
                        artifacts_json=None,
                        now_text=now_text,
                    )
                    updated = connection.execute(
                        """
                        UPDATE proposals
                           SET state = 'confirmed', confirmed_job_id = ?,
                               confirmed_at = ?, confirmation_metadata_json = ?,
                               updated_at = ?
                         WHERE proposal_id = ? AND state = 'pending'
                        """,
                        (
                            item["job_id"],
                            now_text,
                            _json_dump(existing_metadata),
                            now_text,
                            item["proposal_id"],
                        ),
                    )
                    if updated.rowcount != 1:
                        raise StoreConflict("proposal changed during batch confirmation")
                    job = connection.execute(
                        "SELECT * FROM jobs WHERE job_id = ?", (item["job_id"],)
                    ).fetchone()
                    jobs_by_proposal[item["proposal_id"]] = job
            except sqlite3.IntegrityError as exc:
                raise StoreConflict(
                    "could not create unique jobs for proposal batch"
                ) from exc

            ordered_jobs = [
                jobs_by_proposal[item["proposal_id"]] for item in prepared
            ]
        return [self._job_from_row(job) for job in ordered_jobs]  # type: ignore[misc]

    def create_job(
        self,
        *,
        kind: str,
        mode: str,
        request: Mapping[str, Any],
        baseline_id: str | None = None,
        job_id: str | None = None,
        source_path: str | None = None,
        source_hash: str | None = None,
        provenance: Mapping[str, Any] | None = None,
        artifacts: Mapping[str, Any] | None = None,
        max_active_jobs: int | None = None,
    ) -> dict[str, Any]:
        """Enqueue a manual/baseline job not owned by an agent proposal."""

        self._validate_mode(mode)
        if not kind or not kind.strip():
            raise ValueError("kind must not be blank")
        job_id = job_id or _new_id("job")
        now_text = _timestamp(self._current_time())
        request_json = _json_dump(dict(request))
        provenance_json = None if provenance is None else _json_dump(dict(provenance))
        artifacts_json = None if artifacts is None else _json_dump(dict(artifacts))
        with self._transaction(write=True) as connection:
            if connection.execute(
                "SELECT 1 FROM jobs WHERE job_id = ?", (job_id,)
            ).fetchone() is not None:
                raise StoreConflict(f"job id already exists: {job_id}")
            self._ensure_queue_capacity(
                connection, max_active_jobs=max_active_jobs
            )
            try:
                self._insert_job(
                    connection,
                    job_id=job_id,
                    kind=kind.strip(),
                    mode=mode,
                    request_json=request_json,
                    baseline_id=baseline_id,
                    proposal_id=None,
                    source_path=source_path,
                    source_hash=source_hash,
                    provenance_json=provenance_json,
                    artifacts_json=artifacts_json,
                    now_text=now_text,
                )
            except sqlite3.IntegrityError as exc:
                raise StoreConflict(f"job id already exists: {job_id}") from exc
            row = connection.execute(
                "SELECT * FROM jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
        return self._job_from_row(row)  # type: ignore[return-value]

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT * FROM jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
        return self._job_from_row(row)

    def list_jobs(
        self,
        *,
        states: Sequence[str] | None = None,
        mode: str | None = None,
        kind: str | None = None,
        baseline_id: str | None | object = _UNSET,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        if mode is not None:
            self._validate_mode(mode)
        if states is not None:
            unknown = set(states) - JOB_STATES
            if unknown:
                raise ValueError(f"unknown job states: {sorted(unknown)}")
        if limit <= 0:
            return []
        clauses: list[str] = []
        parameters: list[Any] = []
        if states:
            clauses.append(f"state IN ({','.join('?' for _ in states)})")
            parameters.extend(states)
        if mode:
            clauses.append("mode = ?")
            parameters.append(mode)
        if kind:
            clauses.append("kind = ?")
            parameters.append(kind)
        if baseline_id is not _UNSET:
            if baseline_id is None:
                clauses.append("baseline_id IS NULL")
            else:
                clauses.append("baseline_id = ?")
                parameters.append(baseline_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        parameters.append(int(limit))
        with self._transaction() as connection:
            rows = connection.execute(
                f"SELECT * FROM jobs {where} "
                "ORDER BY created_at DESC, job_id DESC LIMIT ?",
                parameters,
            ).fetchall()
        return [self._job_from_row(row) for row in rows]  # type: ignore[misc]

    def list_parameter_sweep_jobs(
        self,
        sweep_ids: Sequence[str],
        *,
        mode: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return every terminal member of the requested parameter sweeps."""

        if mode is not None:
            self._validate_mode(mode)
        normalized_ids = list(
            dict.fromkeys(str(value).strip() for value in sweep_ids if str(value).strip())
        )
        if not normalized_ids:
            return []
        if len(normalized_ids) > 10:
            raise ValueError("at most ten parameter sweeps can be loaded at once")

        placeholders = ",".join("?" for _ in normalized_ids)
        mode_clause = " AND mode = ?" if mode else ""
        parameters: list[Any] = [*normalized_ids]
        if mode:
            parameters.append(mode)
        with self._transaction() as connection:
            rows = connection.execute(
                "SELECT * FROM jobs "
                "WHERE state IN ('done','error','cancelled','interrupted') "
                "AND json_extract(provenance_json, '$.scenario_sweep.type') = "
                "'parameter_sweep' "
                "AND json_extract(provenance_json, '$.scenario_sweep.sweep_id') "
                f"IN ({placeholders})"
                + mode_clause
                + " ORDER BY COALESCE(completed_at, interrupted_at, updated_at, "
                "created_at) DESC, job_id DESC",
                parameters,
            ).fetchall()
        return [self._job_from_row(row) for row in rows]  # type: ignore[misc]

    @staticmethod
    def _check_job_transition(current: str, requested: str) -> None:
        if requested == current:
            return
        allowed = {
            "queued": {"running", "cancelled", "error"},
            "running": {"done", "error", "cancelled", "interrupted"},
            "done": set(),
            "error": set(),
            "cancelled": set(),
            "interrupted": set(),
        }
        if requested not in allowed[current]:
            raise InvalidStateTransition(
                f"cannot move job from {current} to {requested}"
            )

    def update_job(
        self,
        job_id: str,
        *,
        expected_worker_id: str | None = None,
        expected_lease_token: str | None = None,
        state: str | None = None,
        progress: float | None = None,
        stage: str | None = None,
        result: Mapping[str, Any] | None | object = _UNSET,
        comparison: Mapping[str, Any] | None | object = _UNSET,
        provenance: Mapping[str, Any] | None | object = _UNSET,
        artifacts: Mapping[str, Any] | None | object = _UNSET,
        source_path: str | None | object = _UNSET,
        source_hash: str | None | object = _UNSET,
        error: str | None | object = _UNSET,
    ) -> dict[str, Any]:
        """Update mutable job execution fields while enforcing state transitions."""

        if (expected_worker_id is None) != (expected_lease_token is None):
            raise ValueError(
                "expected_worker_id and expected_lease_token must be supplied together"
            )
        if expected_worker_id is not None and (
            not expected_worker_id.strip() or not expected_lease_token.strip()
        ):
            raise ValueError("job lease owner and token must not be blank")
        if state is not None and state not in JOB_STATES:
            raise ValueError(f"unknown job state: {state}")
        if progress is not None:
            if not math.isfinite(float(progress)) or not 0 <= float(progress) <= 100:
                raise ValueError("progress must be a finite percentage in [0, 100]")
        now_text = _timestamp(self._current_time())
        with self._transaction(write=True) as connection:
            row = connection.execute(
                "SELECT * FROM jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
            if row is None:
                raise RecordNotFound(f"unknown job: {job_id}")
            lease_is_owned = bool(row["worker_id"] or row["lease_token"])
            expected_lease = expected_worker_id is not None
            if expected_lease and (
                row["state"] != "running"
                or row["worker_id"] != expected_worker_id
                or row["lease_token"] != expected_lease_token
            ):
                raise LeaseOwnershipLost(
                    f"runner no longer owns the active lease for job {job_id}"
                )
            if row["state"] == "running" and lease_is_owned and not expected_lease:
                raise LeaseOwnershipLost(
                    f"running job {job_id} requires its active lease token"
                )
            if state is not None:
                self._check_job_transition(row["state"], state)

            assignments = ["updated_at = ?"]
            values: list[Any] = [now_text]
            if state is not None and state != row["state"]:
                assignments.append("state = ?")
                values.append(state)
                if state == "running":
                    assignments.extend(["started_at = ?", "stage = ?"])
                    values.extend([now_text, stage or "Running"])
                elif state in {"done", "error", "cancelled"}:
                    assignments.append("completed_at = ?")
                    values.append(now_text)
                elif state == "interrupted":
                    assignments.extend(
                        ["interrupted_at = ?", "completed_at = ?", "stage = ?"]
                    )
                    values.extend([now_text, now_text, stage or "Interrupted"])
                if state == "done" and progress is None:
                    assignments.append("progress = 100")
                if state in {"done", "error", "cancelled", "interrupted"}:
                    assignments.extend(
                        ["worker_id = NULL", "lease_token = NULL", "heartbeat_at = NULL"]
                    )
            if progress is not None:
                assignments.append("progress = ?")
                values.append(float(progress))
            if stage is not None and not (state in {"running", "interrupted"}):
                assignments.append("stage = ?")
                values.append(str(stage))

            for name, value in (
                ("result", result),
                ("comparison", comparison),
                ("provenance", provenance),
                ("artifacts", artifacts),
            ):
                if value is not _UNSET:
                    assignments.append(f"{name}_json = ?")
                    values.append(None if value is None else _json_dump(dict(value)))
            for name, value in (
                ("source_path", source_path),
                ("source_hash", source_hash),
                ("error", error),
            ):
                if value is not _UNSET:
                    assignments.append(f"{name} = ?")
                    values.append(value)

            values.append(job_id)
            connection.execute(
                f"UPDATE jobs SET {', '.join(assignments)} WHERE job_id = ?", values
            )
            updated = connection.execute(
                "SELECT * FROM jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
        return self._job_from_row(updated)  # type: ignore[return-value]

    def claim_next_queued_job(
        self, *, worker_id: str | None = None
    ) -> dict[str, Any] | None:
        """Atomically claim the oldest job, unless another job is running."""

        if worker_id is not None and not worker_id.strip():
            raise ValueError("worker_id must not be blank")
        now_text = _timestamp(self._current_time())
        lease_token = uuid.uuid4().hex if worker_id is not None else None
        with self._transaction(write=True) as connection:
            active = connection.execute(
                "SELECT job_id FROM jobs WHERE state = 'running' LIMIT 1"
            ).fetchone()
            if active is not None:
                return None
            queued = connection.execute(
                """
                SELECT job_id FROM jobs
                 WHERE state = 'queued' AND cancel_requested = 0
                 ORDER BY queued_at ASC, job_id ASC
                 LIMIT 1
                """
            ).fetchone()
            if queued is None:
                return None
            cursor = connection.execute(
                """
                UPDATE jobs
                   SET state = 'running', stage = 'Running', started_at = ?,
                       updated_at = ?, worker_id = ?, lease_token = ?, heartbeat_at = ?
                 WHERE job_id = ? AND state = 'queued' AND cancel_requested = 0
                """,
                (
                    now_text,
                    now_text,
                    worker_id,
                    lease_token,
                    now_text,
                    queued["job_id"],
                ),
            )
            if cursor.rowcount != 1:
                return None
            row = connection.execute(
                "SELECT * FROM jobs WHERE job_id = ?", (queued["job_id"],)
            ).fetchone()
        return self._job_from_row(row)

    def heartbeat_job(
        self, job_id: str, *, worker_id: str, lease_token: str
    ) -> bool:
        """Renew a running job lease only for the process that claimed it."""

        if not worker_id or not worker_id.strip():
            raise ValueError("worker_id must not be blank")
        if not lease_token or not lease_token.strip():
            raise ValueError("lease_token must not be blank")
        now_text = _timestamp(self._current_time())
        with self._transaction(write=True) as connection:
            cursor = connection.execute(
                """
                UPDATE jobs
                   SET heartbeat_at = ?, updated_at = ?
                 WHERE job_id = ? AND state = 'running' AND worker_id = ?
                   AND lease_token = ?
                """,
                (now_text, now_text, job_id, worker_id, lease_token),
            )
        return cursor.rowcount == 1

    def cancel_job(self, job_id: str) -> dict[str, Any]:
        """Cancel a queued job, or request cooperative cancellation of a runner."""

        now_text = _timestamp(self._current_time())
        with self._transaction(write=True) as connection:
            row = connection.execute(
                "SELECT * FROM jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
            if row is None:
                raise RecordNotFound(f"unknown job: {job_id}")
            if row["state"] == "queued":
                connection.execute(
                    """
                    UPDATE jobs
                       SET state = 'cancelled', cancel_requested = 1,
                           cancel_requested_at = ?, completed_at = ?, updated_at = ?,
                           stage = 'Cancelled'
                     WHERE job_id = ? AND state = 'queued'
                    """,
                    (now_text, now_text, now_text, job_id),
                )
            elif row["state"] == "running" and not row["cancel_requested"]:
                connection.execute(
                    """
                    UPDATE jobs
                       SET cancel_requested = 1, cancel_requested_at = ?, updated_at = ?
                     WHERE job_id = ? AND state = 'running'
                    """,
                    (now_text, now_text, job_id),
                )
            updated = connection.execute(
                "SELECT * FROM jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
        return self._job_from_row(updated)  # type: ignore[return-value]

    def is_cancel_requested(
        self,
        job_id: str,
        *,
        expected_worker_id: str | None = None,
        expected_lease_token: str | None = None,
    ) -> bool:
        if (expected_worker_id is None) != (expected_lease_token is None):
            raise ValueError(
                "expected_worker_id and expected_lease_token must be supplied together"
            )
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT state, worker_id, lease_token, cancel_requested "
                "FROM jobs WHERE job_id = ?",
                (job_id,),
            ).fetchone()
        if row is None:
            raise RecordNotFound(f"unknown job: {job_id}")
        if expected_worker_id is not None and (
            row["state"] != "running"
            or row["worker_id"] != expected_worker_id
            or row["lease_token"] != expected_lease_token
        ):
            raise LeaseOwnershipLost(
                f"runner no longer owns the active lease for job {job_id}"
            )
        return bool(row["cancel_requested"])

    def mark_stale_running_jobs_interrupted(
        self, *, before: datetime | None = None
    ) -> int:
        """Mark jobs left running by a prior process as interrupted.

        With no cutoff, all running jobs are treated as stale for explicit
        administrative recovery. Application startup should always supply a lease
        cutoff so another live process's work remains valid.
        """

        now_text = _timestamp(self._current_time())
        clauses = ["state = 'running'"]
        parameters: list[Any] = [now_text, now_text, now_text]
        if before is not None:
            clauses.append("COALESCE(heartbeat_at, started_at, updated_at) <= ?")
            parameters.append(_timestamp(before))
        with self._transaction(write=True) as connection:
            cursor = connection.execute(
                """
                UPDATE jobs
                   SET state = 'interrupted', stage = 'Interrupted after service restart',
                       interrupted_at = ?, completed_at = ?, updated_at = ?, worker_id = NULL,
                       lease_token = NULL, heartbeat_at = NULL
                 WHERE """
                + " AND ".join(clauses),
                parameters,
            )
            return int(cursor.rowcount)

    def retry_job(
        self, job_id: str, *, max_active_jobs: int | None = None
    ) -> dict[str, Any]:
        """Explicitly requeue an interrupted, errored, or cancelled job."""

        now_text = _timestamp(self._current_time())
        with self._transaction(write=True) as connection:
            row = connection.execute(
                "SELECT * FROM jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
            if row is None:
                raise RecordNotFound(f"unknown job: {job_id}")
            if row["state"] not in {"interrupted", "error", "cancelled"}:
                raise InvalidStateTransition(
                    f"cannot retry job in state {row['state']}"
                )
            self._ensure_queue_capacity(
                connection, max_active_jobs=max_active_jobs
            )
            connection.execute(
                """
                UPDATE jobs
                   SET state = 'queued', progress = 0, stage = 'Queued',
                       result_json = NULL, comparison_json = NULL, artifacts_json = NULL,
                       cancel_requested = 0, error = NULL, queued_at = ?, updated_at = ?,
                       started_at = NULL, completed_at = NULL,
                        cancel_requested_at = NULL, interrupted_at = NULL,
                        worker_id = NULL, lease_token = NULL, heartbeat_at = NULL
                 WHERE job_id = ?
                """,
                (now_text, now_text, job_id),
            )
            updated = connection.execute(
                "SELECT * FROM jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
        return self._job_from_row(updated)  # type: ignore[return-value]

    @staticmethod
    def _saved_result_record(
        saved_row: sqlite3.Row,
        job_row: sqlite3.Row,
    ) -> dict[str, Any]:
        return {
            "job_id": str(saved_row["job_id"]),
            "name": str(saved_row["name"]),
            "saved_at": str(saved_row["saved_at"]),
            "updated_at": str(saved_row["updated_at"]),
            "job": AgentStore._job_from_row(job_row),
        }

    @staticmethod
    def _saved_result_name(name: str | None, *, fallback: str | None = None) -> str:
        normalized = " ".join(str(name if name is not None else fallback or "").split())
        if not normalized:
            raise ValueError("saved result name must not be blank")
        if len(normalized) > 120:
            raise ValueError("saved result name must contain at most 120 characters")
        return normalized

    @staticmethod
    def _default_saved_result_name(job: sqlite3.Row) -> str:
        workflow = (
            "Annual simulation"
            if job["mode"] == "annual"
            else "Calibration / validation"
        )
        terminal_time = str(job["completed_at"] or job["updated_at"] or "")
        terminal_date = terminal_time[:10]
        return f"{workflow} - {terminal_date}" if terminal_date else workflow

    def save_result(self, job_id: str, *, name: str | None = None) -> dict[str, Any]:
        """Idempotently add one completed result job to the saved collection."""

        now_text = _timestamp(self._current_time())
        with self._transaction(write=True) as connection:
            existing = connection.execute(
                "SELECT * FROM saved_results WHERE job_id = ?", (job_id,)
            ).fetchone()
            if existing is not None:
                job = connection.execute(
                    "SELECT * FROM jobs WHERE job_id = ?", (job_id,)
                ).fetchone()
                return self._saved_result_record(existing, job)

            job = connection.execute(
                "SELECT * FROM jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
            if job is None:
                raise RecordNotFound(f"unknown job: {job_id}")
            if job["state"] != "done" or job["result_json"] is None:
                raise InvalidStateTransition(
                    "only completed jobs with results can be saved"
                )
            count = int(
                connection.execute("SELECT COUNT(*) FROM saved_results").fetchone()[0]
            )
            if count >= SAVED_RESULTS_LIMIT:
                raise StoreConflict(
                    f"at most {SAVED_RESULTS_LIMIT} results can be saved"
                )
            saved_name = self._saved_result_name(
                name, fallback=self._default_saved_result_name(job)
            )
            connection.execute(
                """
                INSERT INTO saved_results(job_id, name, saved_at, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                (job_id, saved_name, now_text, now_text),
            )
            saved = connection.execute(
                "SELECT * FROM saved_results WHERE job_id = ?", (job_id,)
            ).fetchone()
        return self._saved_result_record(saved, job)

    def list_saved_results(self) -> list[dict[str, Any]]:
        """Return every saved result, newest save first."""

        with self._transaction() as connection:
            saved_rows = connection.execute(
                """
                SELECT * FROM saved_results
                 ORDER BY saved_at DESC, job_id DESC
                 LIMIT ?
                """,
                (SAVED_RESULTS_LIMIT,),
            ).fetchall()
            records = []
            for saved in saved_rows:
                job = connection.execute(
                    "SELECT * FROM jobs WHERE job_id = ?", (saved["job_id"],)
                ).fetchone()
                records.append(self._saved_result_record(saved, job))
        return records

    def rename_saved_result(self, job_id: str, name: str) -> dict[str, Any]:
        """Rename one saved result without changing its saved-order timestamp."""

        saved_name = self._saved_result_name(name)
        now_text = _timestamp(self._current_time())
        with self._transaction(write=True) as connection:
            saved = connection.execute(
                "SELECT * FROM saved_results WHERE job_id = ?", (job_id,)
            ).fetchone()
            if saved is None:
                raise RecordNotFound(f"unknown saved result: {job_id}")
            connection.execute(
                "UPDATE saved_results SET name = ?, updated_at = ? WHERE job_id = ?",
                (saved_name, now_text, job_id),
            )
            updated = connection.execute(
                "SELECT * FROM saved_results WHERE job_id = ?", (job_id,)
            ).fetchone()
            job = connection.execute(
                "SELECT * FROM jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
        return self._saved_result_record(updated, job)

    def remove_saved_result(self, job_id: str) -> dict[str, Any]:
        """Remove a saved marker while preserving the underlying completed job."""

        with self._transaction(write=True) as connection:
            saved = connection.execute(
                "SELECT * FROM saved_results WHERE job_id = ?", (job_id,)
            ).fetchone()
            if saved is None:
                raise RecordNotFound(f"unknown saved result: {job_id}")
            job = connection.execute(
                "SELECT * FROM jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
            connection.execute("DELETE FROM saved_results WHERE job_id = ?", (job_id,))
        return self._saved_result_record(saved, job)

    def delete_job(self, job_id: str) -> dict[str, Any]:
        """Delete a terminal Solar Agent run.

        A baseline can be deleted even after promotion; its current-baseline
        pointer and promotion-history references are removed in the same
        transaction.  Scenario runs still need an unpromoted state because
        promoted scenarios are used as baselines by later comparisons.
        """

        now_text = _timestamp(self._current_time())
        with self._transaction(write=True) as connection:
            row = connection.execute(
                "SELECT * FROM jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
            if row is None:
                raise RecordNotFound(f"unknown job: {job_id}")
            is_scenario = row["kind"] == "candidate"
            is_baseline = row["kind"] in {"baseline", "manual"}
            if not (is_scenario or is_baseline) or (
                is_scenario and row["baseline_id"] is None
            ):
                raise InvalidStateTransition(
                    "only baseline or scenario runs can be deleted"
                )
            if row["state"] in {"queued", "running"}:
                raise InvalidStateTransition(
                    "cancel the active run before deleting it"
                )

            saved = connection.execute(
                "SELECT 1 FROM saved_results WHERE job_id = ?", (job_id,)
            ).fetchone()
            if saved is not None:
                raise InvalidStateTransition(
                    "remove the saved result before deleting this run"
                )

            promotion = connection.execute(
                """
                SELECT 1 FROM current_baselines
                 WHERE job_id = ? OR previous_job_id = ?
                UNION ALL
                SELECT 1 FROM baseline_promotions
                 WHERE job_id = ? OR previous_job_id = ?
                LIMIT 1
                """,
                (job_id, job_id, job_id, job_id),
            ).fetchone()
            if promotion is not None and is_scenario:
                raise InvalidStateTransition(
                    "promoted scenario runs cannot be deleted"
                )

            child = connection.execute(
                "SELECT 1 FROM jobs WHERE baseline_id = ? LIMIT 1", (job_id,)
            ).fetchone()
            if child is not None:
                raise InvalidStateTransition(
                    "scenario runs with dependent comparisons cannot be deleted"
                )

            pending_proposal = connection.execute(
                """
                SELECT 1 FROM proposals
                 WHERE baseline_id = ? AND state = 'pending'
                 LIMIT 1
                """,
                (job_id,),
            ).fetchone()
            if pending_proposal is not None:
                raise InvalidStateTransition(
                    "runs referenced by a pending proposal cannot be deleted"
                )

            deleted = self._job_from_row(row)
            if is_baseline:
                connection.execute(
                    "DELETE FROM current_baselines WHERE job_id = ?", (job_id,)
                )
                connection.execute(
                    """
                    UPDATE current_baselines
                       SET previous_job_id = NULL
                     WHERE previous_job_id = ?
                    """,
                    (job_id,),
                )
                connection.execute(
                    "DELETE FROM baseline_promotions WHERE job_id = ?", (job_id,)
                )
                connection.execute(
                    """
                    UPDATE baseline_promotions
                       SET previous_job_id = NULL
                     WHERE previous_job_id = ?
                    """,
                    (job_id,),
                )
            if row["proposal_id"]:
                connection.execute(
                    """
                    UPDATE proposals
                       SET state = 'dismissed', confirmed_job_id = NULL,
                           dismissed_at = ?, updated_at = ?
                     WHERE proposal_id = ? AND confirmed_job_id = ?
                    """,
                    (now_text, now_text, row["proposal_id"], job_id),
                )
            connection.execute("DELETE FROM jobs WHERE job_id = ?", (job_id,))
        return deleted  # type: ignore[return-value]

    def promote_job(self, job_id: str) -> dict[str, Any]:
        """Make a completed job the current baseline for its mode."""

        now_text = _timestamp(self._current_time())
        with self._transaction(write=True) as connection:
            job = connection.execute(
                "SELECT * FROM jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
            if job is None:
                raise RecordNotFound(f"unknown job: {job_id}")
            if job["state"] != "done":
                raise InvalidStateTransition("only a completed job can be promoted")
            current = connection.execute(
                "SELECT * FROM current_baselines WHERE mode = ?", (job["mode"],)
            ).fetchone()
            if current is not None and current["job_id"] == job_id:
                result = dict(current)
                result["job"] = self._job_from_row(job)
                return result
            previous_id = current["job_id"] if current else None
            connection.execute(
                """
                INSERT INTO current_baselines(mode, job_id, previous_job_id, promoted_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(mode) DO UPDATE SET
                    job_id = excluded.job_id,
                    previous_job_id = excluded.previous_job_id,
                    promoted_at = excluded.promoted_at
                """,
                (job["mode"], job_id, previous_id, now_text),
            )
            connection.execute(
                """
                INSERT INTO baseline_promotions(mode, job_id, previous_job_id, promoted_at)
                VALUES (?, ?, ?, ?)
                """,
                (job["mode"], job_id, previous_id, now_text),
            )
            baseline = connection.execute(
                "SELECT * FROM current_baselines WHERE mode = ?", (job["mode"],)
            ).fetchone()
        result = dict(baseline)
        result["job"] = self._job_from_row(job)
        return result

    def get_current_baseline(self, mode: str) -> dict[str, Any] | None:
        self._validate_mode(mode)
        with self._transaction() as connection:
            row = connection.execute(
                """
                SELECT cb.*, j.*
                  FROM current_baselines cb
                  JOIN jobs j ON j.job_id = cb.job_id
                 WHERE cb.mode = ?
                """,
                (mode,),
            ).fetchone()
        if row is None:
            return None
        # Duplicate column names make a joined Row unsuitable for job decoding.
        job = self.get_job(row["job_id"])
        return {
            "mode": mode,
            "job_id": row["job_id"],
            "previous_job_id": row["previous_job_id"],
            "promoted_at": row["promoted_at"],
            "job": job,
        }

    def list_promotions(
        self, *, mode: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        if mode is not None:
            self._validate_mode(mode)
        if limit <= 0:
            return []
        query = "SELECT * FROM baseline_promotions"
        parameters: list[Any] = []
        if mode:
            query += " WHERE mode = ?"
            parameters.append(mode)
        query += " ORDER BY promotion_id DESC LIMIT ?"
        parameters.append(int(limit))
        with self._transaction() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [dict(row) for row in rows]

    def snapshot_state(
        self, *, mode: str | None = None, recent_limit: int = 10
    ) -> dict[str, Any]:
        """Return the durable state needed by ``GET /api/agent/state``."""

        if mode is not None:
            self._validate_mode(mode)
        now_text = _timestamp(self._current_time())
        mode_clause = " AND mode = ?" if mode else ""
        mode_parameters: list[Any] = [mode] if mode else []
        with self._transaction(write=True) as connection:
            self._expire_due(connection, now_text)
            baseline_query = "SELECT * FROM current_baselines"
            baseline_params: list[Any] = []
            if mode:
                baseline_query += " WHERE mode = ?"
                baseline_params.append(mode)
            baseline_rows = connection.execute(
                baseline_query, baseline_params
            ).fetchall()
            active = connection.execute(
                "SELECT * FROM jobs WHERE state = 'running'"
                + mode_clause
                + " ORDER BY started_at ASC LIMIT 1",
                mode_parameters,
            ).fetchone()
            queued = connection.execute(
                "SELECT * FROM jobs WHERE state = 'queued'"
                + mode_clause
                + " ORDER BY queued_at ASC, job_id ASC",
                mode_parameters,
            ).fetchall()
            pending = connection.execute(
                "SELECT * FROM proposals WHERE state = 'pending'"
                + mode_clause
                + " ORDER BY created_at DESC, proposal_id DESC",
                mode_parameters,
            ).fetchall()
            recent_params = [*mode_parameters, max(int(recent_limit), 0)]
            recent = connection.execute(
                "SELECT * FROM jobs "
                "WHERE state IN ('done','error','cancelled','interrupted')"
                + mode_clause
                + " ORDER BY COALESCE(completed_at, interrupted_at, updated_at, "
                "created_at) DESC, job_id DESC LIMIT ?",
                recent_params,
            ).fetchall()

        baselines: dict[str, Any] = {}
        for baseline in baseline_rows:
            baseline_dict = dict(baseline)
            baseline_dict["job"] = self.get_job(baseline["job_id"])
            baselines[baseline["mode"]] = baseline_dict
        return {
            "generated_at": now_text,
            "current_baselines": baselines,
            "active_job": self._job_from_row(active),
            "queued_jobs": [self._job_from_row(row) for row in queued],
            "pending_proposals": [self._proposal_from_row(row) for row in pending],
            "recent_jobs": [self._job_from_row(row) for row in recent],
        }


__all__ = [
    "AgentStore",
    "AgentStoreError",
    "COMPARISON_KINDS",
    "InvalidStateTransition",
    "JOB_STATES",
    "LeaseOwnershipLost",
    "MODES",
    "PROPOSAL_STATES",
    "RecordNotFound",
    "SAVED_RESULTS_LIMIT",
    "SCHEMA_VERSION",
    "SchemaVersionError",
    "StoreConflict",
]
