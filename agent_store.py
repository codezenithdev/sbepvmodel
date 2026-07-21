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


SCHEMA_VERSION = 1
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
        connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        connection.commit()

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

    def confirm_proposal(
        self,
        proposal_id: str,
        *,
        job_id: str | None = None,
        job_kind: str = "candidate",
        confirmation_metadata: Mapping[str, Any] | None = None,
        source_path: str | None = None,
        source_hash: str | None = None,
    ) -> dict[str, Any]:
        """Confirm once and atomically enqueue exactly one candidate job.

        Repeated or concurrent confirmations return the original job unchanged.
        """

        if not job_kind or not job_kind.strip():
            raise ValueError("job_kind must not be blank")
        now_text = _timestamp(self._current_time())
        requested_job_id = job_id or _new_id("job")
        with self._transaction(write=True) as connection:
            self._expire_due(connection, now_text)
            proposal = connection.execute(
                "SELECT * FROM proposals WHERE proposal_id = ?", (proposal_id,)
            ).fetchone()
            if proposal is None:
                raise RecordNotFound(f"unknown proposal: {proposal_id}")
            if proposal["confirmed_job_id"]:
                existing = connection.execute(
                    "SELECT * FROM jobs WHERE job_id = ?",
                    (proposal["confirmed_job_id"],),
                ).fetchone()
                if existing is None:
                    raise StoreConflict("confirmed proposal references a missing job")
                return self._job_from_row(existing)  # type: ignore[return-value]
            if proposal["state"] != "pending":
                raise InvalidStateTransition(
                    f"cannot confirm proposal in state {proposal['state']}"
                )

            existing_metadata = _json_load(proposal["confirmation_metadata_json"])
            existing_metadata.update(dict(confirmation_metadata or {}))
            metadata_json = _json_dump(existing_metadata)
            try:
                self._insert_job(
                    connection,
                    job_id=requested_job_id,
                    kind=job_kind.strip(),
                    mode=proposal["mode"],
                    request_json=proposal["effective_request_json"],
                    baseline_id=proposal["baseline_id"],
                    proposal_id=proposal_id,
                    source_path=source_path,
                    source_hash=source_hash,
                    provenance_json=None,
                    artifacts_json=None,
                    now_text=now_text,
                )
                connection.execute(
                    """
                    UPDATE proposals
                       SET state = 'confirmed', confirmed_job_id = ?, confirmed_at = ?,
                           confirmation_metadata_json = ?, updated_at = ?
                     WHERE proposal_id = ? AND state = 'pending'
                    """,
                    (
                        requested_job_id,
                        now_text,
                        metadata_json,
                        now_text,
                        proposal_id,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise StoreConflict("could not create a unique proposal job") from exc
            job = connection.execute(
                "SELECT * FROM jobs WHERE job_id = ?", (requested_job_id,)
            ).fetchone()
        return self._job_from_row(job)  # type: ignore[return-value]

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
                    assignments.extend(["interrupted_at = ?", "stage = ?"])
                    values.extend([now_text, stage or "Interrupted"])
                if state == "done" and progress is None:
                    assignments.append("progress = 100")
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

    def claim_next_queued_job(self) -> dict[str, Any] | None:
        """Atomically claim the oldest job, unless another job is running."""

        now_text = _timestamp(self._current_time())
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
                   SET state = 'running', stage = 'Running', started_at = ?, updated_at = ?
                 WHERE job_id = ? AND state = 'queued' AND cancel_requested = 0
                """,
                (now_text, now_text, queued["job_id"]),
            )
            if cursor.rowcount != 1:
                return None
            row = connection.execute(
                "SELECT * FROM jobs WHERE job_id = ?", (queued["job_id"],)
            ).fetchone()
        return self._job_from_row(row)

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

    def is_cancel_requested(self, job_id: str) -> bool:
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT cancel_requested FROM jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
        if row is None:
            raise RecordNotFound(f"unknown job: {job_id}")
        return bool(row["cancel_requested"])

    def mark_stale_running_jobs_interrupted(
        self, *, before: datetime | None = None
    ) -> int:
        """Mark jobs left running by a prior process as interrupted.

        With no cutoff, all running jobs are treated as stale, which is intended
        for application startup.  Supplying ``before`` supports live health checks.
        """

        now_text = _timestamp(self._current_time())
        clauses = ["state = 'running'"]
        parameters: list[Any] = [now_text, now_text]
        if before is not None:
            clauses.append("started_at <= ?")
            parameters.append(_timestamp(before))
        with self._transaction(write=True) as connection:
            cursor = connection.execute(
                """
                UPDATE jobs
                   SET state = 'interrupted', stage = 'Interrupted after service restart',
                       interrupted_at = ?, updated_at = ?
                 WHERE """
                + " AND ".join(clauses),
                parameters,
            )
            return int(cursor.rowcount)

    def retry_job(self, job_id: str) -> dict[str, Any]:
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
            connection.execute(
                """
                UPDATE jobs
                   SET state = 'queued', progress = 0, stage = 'Queued',
                       result_json = NULL, comparison_json = NULL, artifacts_json = NULL,
                       cancel_requested = 0, error = NULL, queued_at = ?, updated_at = ?,
                       started_at = NULL, completed_at = NULL,
                       cancel_requested_at = NULL, interrupted_at = NULL
                 WHERE job_id = ?
                """,
                (now_text, now_text, job_id),
            )
            updated = connection.execute(
                "SELECT * FROM jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
        return self._job_from_row(updated)  # type: ignore[return-value]

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
        self, *, mode: str | None = None, recent_limit: int = 20
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
                "SELECT * FROM jobs WHERE 1 = 1"
                + mode_clause
                + " ORDER BY created_at DESC, job_id DESC LIMIT ?",
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
    "MODES",
    "PROPOSAL_STATES",
    "RecordNotFound",
    "SCHEMA_VERSION",
    "SchemaVersionError",
    "StoreConflict",
]
