"""Durable SQLite state for dashboard model jobs and agent proposals.

The store deliberately owns persistence and state transitions only.  Model execution,
request validation, and HTTP serialization stay in ``app.py``.  Every public method
returns ordinary dictionaries so the store is easy to integrate with FastAPI.
"""

from __future__ import annotations

import hashlib
import json
import math
import secrets
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping, Sequence


SCHEMA_VERSION = 8
SAVED_RESULTS_LIMIT = 10
PROPOSAL_STATES = frozenset(
    {"pending", "confirmed", "superseded", "dismissed", "expired"}
)
JOB_STATES = frozenset(
    {"queued", "running", "done", "error", "cancelled", "interrupted"}
)
MODES = frozenset({"validation", "annual"})
COMPARISON_KINDS = frozenset({"same_input", "cross_run"})
TECHNOECONOMIC_ID_PREFIX = "tea_"
TERMINAL_JOB_STATES = frozenset({"done", "error", "cancelled", "interrupted"})

DECISION_CASE_STATES = frozenset(
    {
        "draft",
        "evidence_needed",
        "blocked",
        "ready_to_run",
        "running",
        "results_ready",
        "decision_ready",
        "signed",
        "archived",
    }
)
DECISION_CASE_TRANSITIONS: dict[str, frozenset[str]] = {
    "draft": frozenset({"evidence_needed", "blocked", "archived"}),
    "evidence_needed": frozenset({"blocked", "ready_to_run", "archived"}),
    "blocked": frozenset({"evidence_needed", "ready_to_run", "archived"}),
    "ready_to_run": frozenset(
        {"evidence_needed", "blocked", "running", "archived"}
    ),
    "running": frozenset({"results_ready"}),
    "results_ready": frozenset({"decision_ready"}),
    "decision_ready": frozenset({"signed"}),
    "signed": frozenset({"archived"}),
    "archived": frozenset(),
}
DECISION_TURN_STATES = frozenset({"pending", "claimed", "completed", "failed"})
DECISION_EVIDENCE_CLASSES = frozenset(
    {
        "project_actual",
        "direct_quote_or_primary_document",
        "public_market_proxy_or_benchmark",
        "engineering_judgment",
        "secondary_synthesis",
    }
)
DECISION_EVIDENCE_DECISIONS = frozenset({"accepted", "rejected"})
DECISION_SCENARIO_STATES = frozenset(
    {"draft", "invalid", "validated", "confirmed", "expired"}
)
DECISION_SCENARIO_KINDS = frozenset({"baseline", "alternative"})
DECISION_SCENARIO_COMPARISONS = frozenset(
    {"baseline", "controlled", "structural"}
)
DECISION_SCENARIO_DRAFT_LIFETIME = timedelta(days=7)
DECISION_RECOMMENDATION_CLASSIFICATIONS = frozenset(
    {
        "solaredge",
        "solectria",
        "no_decisive_winner",
        "classification_pending_contract",
    }
)
DECISION_CONFIDENCE_STATES = frozenset(
    {"strong", "mixed", "provisional", "classification_pending_contract"}
)
DECISION_EVIDENCE_MAX_FILE_BYTES = 10 * 1024 * 1024
DECISION_EVIDENCE_MAX_FILES_PER_CASE = 10
DECISION_EVIDENCE_MAX_CASE_BYTES = 50 * 1024 * 1024
_DECISION_EVIDENCE_MEDIA_EXTENSIONS = {
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "text/csv": ".csv",
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
}


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


class EvidenceLimitExceeded(StoreConflict):
    """Raised when a decision evidence upload would exceed a durable case limit."""


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


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _verified_decision_bundle_json(
    bundle_json: str,
    bundle_sha256: str,
) -> dict[str, Any]:
    payload = _json_load(bundle_json)
    if not isinstance(payload, Mapping):
        raise StoreConflict("stored comparison bundle is not an object")
    canonical = dict(payload)
    embedded_hash = canonical.pop("bundle_hash", None)
    if (
        embedded_hash != bundle_sha256
        or not secrets.compare_digest(
            str(bundle_sha256), _sha256_text(_json_dump(canonical))
        )
    ):
        raise StoreConflict("stored comparison bundle digest is invalid")
    return dict(payload)


def _bounded_text(value: Any, *, field: str, maximum: int) -> str:
    normalized = str(value).strip() if isinstance(value, str) else ""
    if not normalized or len(normalized) > maximum:
        raise ValueError(f"{field} must contain between 1 and {maximum} characters")
    return normalized


def _optional_bounded_text(
    value: Any,
    *,
    field: str,
    maximum: int,
) -> str | None:
    if value is None:
        return None
    return _bounded_text(value, field=field, maximum=maximum)


def _decision_evidence_storage_key(sha256: str, media_type: str) -> tuple[str, str]:
    extension = _DECISION_EVIDENCE_MEDIA_EXTENSIONS.get(media_type)
    if extension is None:
        raise ValueError("unsupported decision evidence media type")
    return f"sha256/{sha256[:2]}/{sha256}{extension}", extension


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
                    version = 4
                if version < 5:
                    self._migrate_v5(connection)
                    version = 5
                if version < 6:
                    self._migrate_v6(connection)
                    version = 6
                if version < 7:
                    self._migrate_v7(connection)
                    version = 7
                if version < 8:
                    self._migrate_v8(connection)
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

    def _migrate_v5(self, connection: sqlite3.Connection) -> None:
        """Add structurally isolated, immutable technoeconomic jobs."""

        applied_at = _timestamp(self._current_time())
        connection.executescript(
            """
            BEGIN IMMEDIATE;

            CREATE TABLE IF NOT EXISTS technoeconomic_jobs (
                tea_job_id TEXT PRIMARY KEY CHECK (
                    tea_job_id GLOB 'tea_*' AND length(tea_job_id) > 4
                ),
                state TEXT NOT NULL CHECK (
                    state IN ('queued','running','done','error','cancelled','interrupted')
                ),
                request_json TEXT NOT NULL CHECK (json_valid(request_json)),
                source_annual_job_id TEXT NOT NULL
                    REFERENCES jobs(job_id) ON DELETE RESTRICT,
                source_artifact_storage_key TEXT NOT NULL CHECK (
                    source_artifact_storage_key =
                        'sha256/' || substr(source_artifact_sha256, 1, 2) || '/'
                        || source_artifact_sha256 || '.csv'
                ),
                source_artifact_sha256 TEXT NOT NULL CHECK (
                    length(source_artifact_sha256) = 64
                    AND source_artifact_sha256 NOT GLOB '*[^0-9a-f]*'
                ),
                source_artifact_bytes INTEGER NOT NULL CHECK (
                    source_artifact_bytes > 0
                ),
                source_snapshot_json TEXT NOT NULL CHECK (
                    json_valid(source_snapshot_json)
                    AND json_extract(
                        source_snapshot_json, '$.source_annual_job_id'
                    ) = source_annual_job_id
                    AND json_extract(
                        source_snapshot_json,
                        '$.midc_source_artifact.owner_annual_job_id'
                    ) = source_annual_job_id
                    AND json_extract(
                        source_snapshot_json,
                        '$.midc_source_artifact.storage_key'
                    ) = source_artifact_storage_key
                    AND json_extract(
                        source_snapshot_json, '$.midc_source_artifact.sha256'
                    ) = source_artifact_sha256
                    AND json_extract(
                        source_snapshot_json, '$.midc_source_artifact.byte_count'
                    ) = source_artifact_bytes
                ),
                source_snapshot_sha256 TEXT NOT NULL CHECK (
                    length(source_snapshot_sha256) = 64
                    AND source_snapshot_sha256 NOT GLOB '*[^0-9a-f]*'
                ),
                submission_provenance_json TEXT NOT NULL CHECK (
                    json_valid(submission_provenance_json)
                ),
                submission_provenance_sha256 TEXT NOT NULL CHECK (
                    length(submission_provenance_sha256) = 64
                    AND submission_provenance_sha256 NOT GLOB '*[^0-9a-f]*'
                ),
                retry_of_job_id TEXT
                    REFERENCES technoeconomic_jobs(tea_job_id) ON DELETE RESTRICT,
                result_json TEXT CHECK (
                    result_json IS NULL OR json_valid(result_json)
                ),
                result_provenance_json TEXT CHECK (
                    result_provenance_json IS NULL
                    OR json_valid(result_provenance_json)
                ),
                artifacts_json TEXT CHECK (
                    artifacts_json IS NULL OR json_valid(artifacts_json)
                ),
                progress REAL NOT NULL DEFAULT 0 CHECK (
                    progress >= 0 AND progress <= 100
                ),
                stage TEXT NOT NULL DEFAULT 'Queued',
                cancel_requested INTEGER NOT NULL DEFAULT 0 CHECK (
                    cancel_requested IN (0,1)
                ),
                error TEXT,
                worker_id TEXT,
                lease_token TEXT,
                created_at TEXT NOT NULL,
                queued_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                started_at TEXT,
                completed_at TEXT,
                heartbeat_at TEXT,
                cancel_requested_at TEXT,
                interrupted_at TEXT
            );

            CREATE INDEX IF NOT EXISTS technoeconomic_jobs_state_queued_idx
                ON technoeconomic_jobs(state, queued_at);
            CREATE INDEX IF NOT EXISTS technoeconomic_jobs_source_idx
                ON technoeconomic_jobs(source_annual_job_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS technoeconomic_jobs_created_idx
                ON technoeconomic_jobs(created_at DESC, tea_job_id DESC);

            CREATE TRIGGER IF NOT EXISTS model_job_tea_namespace_insert_guard
            BEFORE INSERT ON jobs
            WHEN NEW.job_id GLOB 'tea_*'
            BEGIN
                SELECT RAISE(ABORT, 'tea_ ids are reserved for technoeconomic jobs');
            END;

            CREATE TRIGGER IF NOT EXISTS model_job_tea_namespace_update_guard
            BEFORE UPDATE OF job_id ON jobs
            WHEN NEW.job_id GLOB 'tea_*'
            BEGIN
                SELECT RAISE(ABORT, 'tea_ ids are reserved for technoeconomic jobs');
            END;

            CREATE TRIGGER IF NOT EXISTS model_job_technoeconomic_kind_insert_guard
            BEFORE INSERT ON jobs
            WHEN lower(trim(NEW.kind)) = 'technoeconomic'
            BEGIN
                SELECT RAISE(ABORT, 'technoeconomic work requires its isolated table');
            END;

            CREATE TRIGGER IF NOT EXISTS model_job_technoeconomic_kind_update_guard
            BEFORE UPDATE OF kind ON jobs
            WHEN lower(trim(NEW.kind)) = 'technoeconomic'
            BEGIN
                SELECT RAISE(ABORT, 'technoeconomic work requires its isolated table');
            END;

            CREATE TRIGGER IF NOT EXISTS model_job_tea_baseline_insert_guard
            BEFORE INSERT ON jobs
            WHEN NEW.baseline_id GLOB 'tea_*'
            BEGIN
                SELECT RAISE(ABORT, 'technoeconomic jobs cannot be model baselines');
            END;

            CREATE TRIGGER IF NOT EXISTS model_job_tea_baseline_update_guard
            BEFORE UPDATE OF baseline_id ON jobs
            WHEN NEW.baseline_id GLOB 'tea_*'
            BEGIN
                SELECT RAISE(ABORT, 'technoeconomic jobs cannot be model baselines');
            END;

            CREATE TRIGGER IF NOT EXISTS proposal_tea_reference_insert_guard
            BEFORE INSERT ON proposals
            WHEN NEW.baseline_id GLOB 'tea_*'
                 OR NEW.confirmed_job_id GLOB 'tea_*'
            BEGIN
                SELECT RAISE(ABORT, 'technoeconomic jobs cannot enter model proposals');
            END;

            CREATE TRIGGER IF NOT EXISTS proposal_tea_reference_update_guard
            BEFORE UPDATE OF baseline_id, confirmed_job_id ON proposals
            WHEN NEW.baseline_id GLOB 'tea_*'
                 OR NEW.confirmed_job_id GLOB 'tea_*'
            BEGIN
                SELECT RAISE(ABORT, 'technoeconomic jobs cannot enter model proposals');
            END;

            CREATE TRIGGER IF NOT EXISTS current_baseline_tea_reference_insert_guard
            BEFORE INSERT ON current_baselines
            WHEN NEW.job_id GLOB 'tea_*' OR NEW.previous_job_id GLOB 'tea_*'
            BEGIN
                SELECT RAISE(ABORT, 'technoeconomic jobs cannot be promoted');
            END;

            CREATE TRIGGER IF NOT EXISTS current_baseline_tea_reference_update_guard
            BEFORE UPDATE OF job_id, previous_job_id ON current_baselines
            WHEN NEW.job_id GLOB 'tea_*' OR NEW.previous_job_id GLOB 'tea_*'
            BEGIN
                SELECT RAISE(ABORT, 'technoeconomic jobs cannot be promoted');
            END;

            CREATE TRIGGER IF NOT EXISTS baseline_promotion_tea_reference_insert_guard
            BEFORE INSERT ON baseline_promotions
            WHEN NEW.job_id GLOB 'tea_*' OR NEW.previous_job_id GLOB 'tea_*'
            BEGIN
                SELECT RAISE(ABORT, 'technoeconomic jobs cannot enter promotion history');
            END;

            CREATE TRIGGER IF NOT EXISTS baseline_promotion_tea_reference_update_guard
            BEFORE UPDATE OF job_id, previous_job_id ON baseline_promotions
            WHEN NEW.job_id GLOB 'tea_*' OR NEW.previous_job_id GLOB 'tea_*'
            BEGIN
                SELECT RAISE(ABORT, 'technoeconomic jobs cannot enter promotion history');
            END;

            CREATE TRIGGER IF NOT EXISTS saved_result_tea_reference_insert_guard
            BEFORE INSERT ON saved_results
            WHEN NEW.job_id GLOB 'tea_*'
            BEGIN
                SELECT RAISE(ABORT, 'technoeconomic jobs cannot be saved model results');
            END;

            CREATE TRIGGER IF NOT EXISTS saved_result_tea_reference_update_guard
            BEFORE UPDATE OF job_id ON saved_results
            WHEN NEW.job_id GLOB 'tea_*'
            BEGIN
                SELECT RAISE(ABORT, 'technoeconomic jobs cannot be saved model results');
            END;

            CREATE TRIGGER IF NOT EXISTS technoeconomic_source_insert_guard
            BEFORE INSERT ON technoeconomic_jobs
            WHEN NOT EXISTS (
                SELECT 1 FROM jobs
                 WHERE job_id = NEW.source_annual_job_id
                   AND mode = 'annual' AND state = 'done'
            )
            BEGIN
                SELECT RAISE(ABORT, 'technoeconomic source must be a completed annual job');
            END;

            CREATE TRIGGER IF NOT EXISTS retained_annual_source_state_guard
            BEFORE UPDATE OF
                request_json, result_json, provenance_json, artifacts_json,
                source_path, source_hash, kind, mode, state
            ON jobs
            WHEN EXISTS (
                SELECT 1 FROM technoeconomic_jobs
                 WHERE source_annual_job_id = OLD.job_id
            )
            BEGIN
                SELECT RAISE(ABORT, 'referenced annual source payload is retained');
            END;

            CREATE TRIGGER IF NOT EXISTS model_job_global_running_guard
            BEFORE UPDATE OF state ON jobs
            WHEN NEW.state = 'running' AND OLD.state <> 'running'
            BEGIN
                SELECT RAISE(ABORT, 'only queued model jobs can start')
                 WHERE OLD.state <> 'queued' OR OLD.cancel_requested <> 0;
                SELECT RAISE(ABORT, 'another model or technoeconomic job is running')
                 WHERE EXISTS (SELECT 1 FROM jobs WHERE state = 'running')
                    OR EXISTS (
                        SELECT 1 FROM technoeconomic_jobs WHERE state = 'running'
                    );
                SELECT RAISE(ABORT, 'model job is not globally oldest queued work')
                 WHERE EXISTS (
                        SELECT 1 FROM jobs
                         WHERE state = 'queued' AND cancel_requested = 0
                           AND (
                                queued_at < OLD.queued_at
                                OR (queued_at = OLD.queued_at AND job_id < OLD.job_id)
                           )
                    )
                    OR EXISTS (
                        SELECT 1 FROM technoeconomic_jobs
                         WHERE state = 'queued' AND cancel_requested = 0
                           AND queued_at < OLD.queued_at
                    );
            END;

            CREATE TRIGGER IF NOT EXISTS technoeconomic_job_global_running_guard
            BEFORE UPDATE OF state ON technoeconomic_jobs
            WHEN NEW.state = 'running' AND OLD.state <> 'running'
            BEGIN
                SELECT RAISE(ABORT, 'only queued technoeconomic jobs can start')
                 WHERE OLD.state <> 'queued' OR OLD.cancel_requested <> 0;
                SELECT RAISE(ABORT, 'technoeconomic running work requires a lease')
                 WHERE NEW.worker_id IS NULL OR length(trim(NEW.worker_id)) = 0
                    OR NEW.lease_token IS NULL OR length(trim(NEW.lease_token)) = 0
                    OR NEW.started_at IS NULL OR NEW.heartbeat_at IS NULL;
                SELECT RAISE(ABORT, 'another model or technoeconomic job is running')
                 WHERE EXISTS (SELECT 1 FROM jobs WHERE state = 'running')
                    OR EXISTS (
                        SELECT 1 FROM technoeconomic_jobs WHERE state = 'running'
                    );
                SELECT RAISE(ABORT, 'technoeconomic job is not globally oldest queued work')
                 WHERE EXISTS (
                        SELECT 1 FROM jobs
                         WHERE state = 'queued' AND cancel_requested = 0
                           AND queued_at <= OLD.queued_at
                    )
                    OR EXISTS (
                        SELECT 1 FROM technoeconomic_jobs
                         WHERE state = 'queued' AND cancel_requested = 0
                           AND (
                                queued_at < OLD.queued_at
                                OR (
                                    queued_at = OLD.queued_at
                                    AND tea_job_id < OLD.tea_job_id
                                )
                           )
                    );
            END;

            CREATE TRIGGER IF NOT EXISTS technoeconomic_job_inputs_are_immutable
            BEFORE UPDATE OF
                tea_job_id,
                request_json,
                source_annual_job_id,
                source_artifact_storage_key,
                source_artifact_sha256,
                source_artifact_bytes,
                source_snapshot_json,
                source_snapshot_sha256,
                submission_provenance_json,
                submission_provenance_sha256,
                retry_of_job_id
            ON technoeconomic_jobs
            BEGIN
                SELECT RAISE(ABORT, 'technoeconomic request and source snapshot are immutable');
            END;

            CREATE TRIGGER IF NOT EXISTS technoeconomic_job_terminal_payload_is_immutable
            BEFORE UPDATE OF result_json, result_provenance_json, artifacts_json
            ON technoeconomic_jobs
            WHEN OLD.state IN ('done','error','cancelled','interrupted')
            BEGIN
                SELECT RAISE(ABORT, 'terminal technoeconomic payload is immutable');
            END;

            CREATE TRIGGER IF NOT EXISTS technoeconomic_job_terminal_state_is_immutable
            BEFORE UPDATE OF state ON technoeconomic_jobs
            WHEN OLD.state IN ('done','error','cancelled','interrupted')
                 AND NEW.state <> OLD.state
            BEGIN
                SELECT RAISE(ABORT, 'terminal technoeconomic state is immutable');
            END;

            CREATE TRIGGER IF NOT EXISTS technoeconomic_job_terminal_row_is_immutable
            BEFORE UPDATE ON technoeconomic_jobs
            WHEN OLD.state IN ('done','error','cancelled','interrupted')
            BEGIN
                SELECT RAISE(ABORT, 'terminal technoeconomic job is immutable');
            END;
            """
        )
        collision = connection.execute(
            """
            SELECT field_name, field_value FROM (
                SELECT 'jobs.job_id' AS field_name, job_id AS field_value
                  FROM jobs WHERE job_id GLOB 'tea_*'
                UNION ALL
                SELECT 'jobs.baseline_id', baseline_id
                  FROM jobs WHERE baseline_id GLOB 'tea_*'
                UNION ALL
                SELECT 'proposals.baseline_id', baseline_id
                  FROM proposals WHERE baseline_id GLOB 'tea_*'
                UNION ALL
                SELECT 'proposals.confirmed_job_id', confirmed_job_id
                  FROM proposals WHERE confirmed_job_id GLOB 'tea_*'
                UNION ALL
                SELECT 'current_baselines.job_id', job_id
                  FROM current_baselines WHERE job_id GLOB 'tea_*'
                UNION ALL
                SELECT 'current_baselines.previous_job_id', previous_job_id
                  FROM current_baselines WHERE previous_job_id GLOB 'tea_*'
                UNION ALL
                SELECT 'baseline_promotions.job_id', job_id
                  FROM baseline_promotions WHERE job_id GLOB 'tea_*'
                UNION ALL
                SELECT 'baseline_promotions.previous_job_id', previous_job_id
                  FROM baseline_promotions WHERE previous_job_id GLOB 'tea_*'
                UNION ALL
                SELECT 'saved_results.job_id', job_id
                  FROM saved_results WHERE job_id GLOB 'tea_*'
            ) LIMIT 1
            """
        ).fetchone()
        if collision is not None:
            connection.rollback()
            raise SchemaVersionError(
                "schema v5 reserves the 'tea_' namespace, but existing "
                f"{collision['field_name']} uses {collision['field_value']!r}"
            )
        connection.execute(
            "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (?, ?)",
            (5, applied_at),
        )
        connection.execute("PRAGMA user_version = 5")
        connection.commit()

    def _migrate_v6(self, connection: sqlite3.Connection) -> None:
        """Add durable, append-only Autonomy case and evidence state."""

        applied_at = _timestamp(self._current_time())
        connection.executescript(
            """
            BEGIN IMMEDIATE;

            CREATE TABLE IF NOT EXISTS decision_cases (
                case_id TEXT PRIMARY KEY CHECK (
                    case_id GLOB 'case_*' AND length(case_id) > 5
                ),
                title TEXT NOT NULL CHECK (
                    title = trim(title) AND length(title) BETWEEN 1 AND 200
                ),
                original_question TEXT NOT NULL CHECK (
                    original_question = trim(original_question)
                    AND length(original_question) BETWEEN 1 AND 8000
                ),
                question TEXT NOT NULL CHECK (
                    question = trim(question) AND length(question) BETWEEN 1 AND 8000
                ),
                status TEXT NOT NULL CHECK (
                    status IN (
                        'draft','evidence_needed','blocked','ready_to_run',
                        'running','results_ready','decision_ready','signed','archived'
                    )
                ),
                source_annual_job_id TEXT
                    REFERENCES jobs(job_id) ON DELETE RESTRICT,
                source_snapshot_sha256 TEXT,
                analysis_basis TEXT CHECK (
                    analysis_basis IS NULL OR analysis_basis IN (
                        'solartac_site','commercial_representative'
                    )
                ),
                source_basis_locked_at TEXT,
                source_basis_locked_by TEXT,
                decision_owner TEXT CHECK (
                    decision_owner IS NULL OR (
                        decision_owner = trim(decision_owner)
                        AND length(decision_owner) BETWEEN 1 AND 200
                    )
                ),
                active_recommendation_revision INTEGER CHECK (
                    active_recommendation_revision IS NULL
                    OR active_recommendation_revision > 0
                ),
                revision INTEGER NOT NULL DEFAULT 1 CHECK (revision > 0),
                created_by TEXT NOT NULL CHECK (
                    created_by = trim(created_by)
                    AND length(created_by) BETWEEN 1 AND 200
                ),
                updated_by TEXT NOT NULL CHECK (
                    updated_by = trim(updated_by)
                    AND length(updated_by) BETWEEN 1 AND 200
                ),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                archived_at TEXT,
                CHECK (
                    (
                        source_annual_job_id IS NULL
                        AND source_snapshot_sha256 IS NULL
                        AND analysis_basis IS NULL
                        AND source_basis_locked_at IS NULL
                        AND source_basis_locked_by IS NULL
                    ) OR (
                        source_annual_job_id IS NOT NULL
                        AND source_snapshot_sha256 IS NOT NULL
                        AND length(source_snapshot_sha256) = 64
                        AND source_snapshot_sha256 NOT GLOB '*[^0-9a-f]*'
                        AND analysis_basis IS NOT NULL
                        AND source_basis_locked_at IS NOT NULL
                        AND source_basis_locked_by IS NOT NULL
                        AND source_basis_locked_by = trim(source_basis_locked_by)
                        AND length(source_basis_locked_by) BETWEEN 1 AND 200
                    )
                ),
                CHECK (
                    (status = 'archived' AND archived_at IS NOT NULL)
                    OR (status <> 'archived' AND archived_at IS NULL)
                )
            );

            CREATE TABLE IF NOT EXISTS decision_agent_turns (
                turn_id TEXT PRIMARY KEY CHECK (
                    turn_id GLOB 'dturn_*' AND length(turn_id) > 6
                ),
                case_id TEXT NOT NULL
                    REFERENCES decision_cases(case_id) ON DELETE RESTRICT,
                client_message_id TEXT NOT NULL CHECK (
                    client_message_id = trim(client_message_id)
                    AND length(client_message_id) BETWEEN 1 AND 200
                ),
                state TEXT NOT NULL CHECK (
                    state IN ('pending','claimed','completed','failed')
                ),
                created_by TEXT NOT NULL CHECK (
                    created_by = trim(created_by)
                    AND length(created_by) BETWEEN 1 AND 200
                ),
                worker_id TEXT,
                claim_token TEXT,
                trace_id TEXT CHECK (
                    trace_id IS NULL OR (
                        trace_id = trim(trace_id)
                        AND length(trace_id) BETWEEN 1 AND 200
                    )
                ),
                error_code TEXT,
                error_detail TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                claimed_at TEXT,
                completed_at TEXT,
                failed_at TEXT,
                UNIQUE(case_id, client_message_id),
                UNIQUE(turn_id, case_id),
                CHECK (
                    (state = 'pending'
                        AND worker_id IS NULL AND claim_token IS NULL
                        AND claimed_at IS NULL AND completed_at IS NULL
                        AND failed_at IS NULL AND error_code IS NULL
                        AND error_detail IS NULL)
                    OR (state = 'claimed'
                        AND worker_id IS NOT NULL AND length(trim(worker_id)) > 0
                        AND claim_token IS NOT NULL AND length(trim(claim_token)) > 0
                        AND claimed_at IS NOT NULL AND completed_at IS NULL
                        AND failed_at IS NULL AND error_code IS NULL
                        AND error_detail IS NULL)
                    OR (state = 'completed'
                        AND worker_id IS NOT NULL AND claim_token IS NOT NULL
                        AND claimed_at IS NOT NULL AND completed_at IS NOT NULL
                        AND failed_at IS NULL AND error_code IS NULL
                        AND error_detail IS NULL)
                    OR (state = 'failed'
                        AND worker_id IS NOT NULL AND claim_token IS NOT NULL
                        AND claimed_at IS NOT NULL AND completed_at IS NULL
                        AND failed_at IS NOT NULL
                        AND error_code IS NOT NULL
                        AND length(trim(error_code)) > 0
                        AND error_detail IS NOT NULL
                        AND length(trim(error_detail)) > 0)
                )
            );

            CREATE TABLE IF NOT EXISTS decision_messages (
                message_id TEXT PRIMARY KEY CHECK (
                    message_id GLOB 'dmsg_*' AND length(message_id) > 5
                ),
                case_id TEXT NOT NULL,
                turn_id TEXT NOT NULL,
                message_sequence INTEGER NOT NULL CHECK (message_sequence > 0),
                role TEXT NOT NULL CHECK (role IN ('user','assistant')),
                status TEXT NOT NULL CHECK (status IN ('complete','error')),
                content_text TEXT NOT NULL CHECK (length(content_text) > 0),
                structured_output_json TEXT CHECK (
                    structured_output_json IS NULL
                    OR json_valid(structured_output_json)
                ),
                citations_json TEXT NOT NULL CHECK (json_valid(citations_json)),
                tool_outcomes_json TEXT NOT NULL CHECK (
                    json_valid(tool_outcomes_json)
                ),
                trace_id TEXT CHECK (
                    trace_id IS NULL OR (
                        trace_id = trim(trace_id)
                        AND length(trace_id) BETWEEN 1 AND 200
                    )
                ),
                operator_name TEXT,
                error_code TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(turn_id, case_id)
                    REFERENCES decision_agent_turns(turn_id, case_id)
                    ON DELETE RESTRICT,
                UNIQUE(case_id, message_sequence),
                UNIQUE(turn_id, role),
                CHECK (
                    (role = 'user' AND status = 'complete'
                        AND operator_name IS NOT NULL
                        AND operator_name = trim(operator_name)
                        AND length(operator_name) BETWEEN 1 AND 200
                        AND error_code IS NULL)
                    OR (role = 'assistant' AND operator_name IS NULL)
                ),
                CHECK (
                    (status = 'error' AND error_code IS NOT NULL
                        AND length(trim(error_code)) > 0)
                    OR (status = 'complete' AND error_code IS NULL)
                )
            );

            CREATE TABLE IF NOT EXISTS decision_evidence_assets (
                evidence_asset_id TEXT PRIMARY KEY CHECK (
                    evidence_asset_id GLOB 'evi_*'
                    AND length(evidence_asset_id) > 4
                ),
                case_id TEXT NOT NULL
                    REFERENCES decision_cases(case_id) ON DELETE RESTRICT,
                evidence_class TEXT NOT NULL CHECK (
                    evidence_class IN (
                        'project_actual','direct_quote_or_primary_document',
                        'public_market_proxy_or_benchmark',
                        'engineering_judgment','secondary_synthesis'
                    )
                ),
                original_filename TEXT NOT NULL CHECK (
                    original_filename = trim(original_filename)
                    AND length(original_filename) BETWEEN 1 AND 255
                    AND original_filename NOT GLOB '.*'
                    AND instr(original_filename, '/') = 0
                    AND instr(original_filename, '\\') = 0
                ),
                display_filename TEXT NOT NULL CHECK (
                    display_filename = trim(display_filename)
                    AND length(display_filename) BETWEEN 1 AND 255
                    AND display_filename NOT GLOB '.*'
                    AND instr(display_filename, '/') = 0
                    AND instr(display_filename, '\\') = 0
                ),
                declared_media_type TEXT NOT NULL,
                detected_media_type TEXT NOT NULL CHECK (
                    detected_media_type IN (
                        'application/pdf',
                        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                        'text/csv','image/png','image/jpeg','image/webp'
                    )
                ),
                canonical_extension TEXT NOT NULL CHECK (
                    canonical_extension IN (
                        '.pdf','.xlsx','.csv','.png','.jpg','.webp'
                    )
                ),
                sha256 TEXT NOT NULL CHECK (
                    length(sha256) = 64
                    AND sha256 NOT GLOB '*[^0-9a-f]*'
                ),
                byte_count INTEGER NOT NULL CHECK (byte_count > 0),
                storage_key TEXT NOT NULL CHECK (
                    storage_key = 'sha256/' || substr(sha256, 1, 2) || '/'
                        || sha256 || canonical_extension
                ),
                extraction_status TEXT NOT NULL CHECK (
                    extraction_status IN ('complete','not_supported','failed')
                ),
                extraction_metadata_json TEXT NOT NULL CHECK (
                    json_valid(extraction_metadata_json)
                ),
                source_metadata_json TEXT NOT NULL CHECK (
                    json_valid(source_metadata_json)
                ),
                uploaded_by TEXT NOT NULL CHECK (
                    uploaded_by = trim(uploaded_by)
                    AND length(uploaded_by) BETWEEN 1 AND 200
                ),
                uploaded_at TEXT NOT NULL,
                removed_by TEXT,
                removed_reason TEXT,
                removed_at TEXT,
                UNIQUE(evidence_asset_id, case_id),
                CHECK (declared_media_type = detected_media_type),
                CHECK (
                    canonical_extension = CASE detected_media_type
                        WHEN 'application/pdf' THEN '.pdf'
                        WHEN 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
                            THEN '.xlsx'
                        WHEN 'text/csv' THEN '.csv'
                        WHEN 'image/png' THEN '.png'
                        WHEN 'image/jpeg' THEN '.jpg'
                        WHEN 'image/webp' THEN '.webp'
                    END
                ),
                CHECK (
                    (removed_at IS NULL AND removed_by IS NULL AND removed_reason IS NULL)
                    OR (removed_at IS NOT NULL
                        AND removed_by IS NOT NULL
                        AND removed_by = trim(removed_by)
                        AND length(removed_by) BETWEEN 1 AND 200
                        AND removed_reason IS NOT NULL
                        AND length(trim(removed_reason)) > 0)
                )
            );

            CREATE TABLE IF NOT EXISTS decision_evidence_candidates (
                evidence_candidate_id TEXT PRIMARY KEY CHECK (
                    evidence_candidate_id GLOB 'evc_*'
                    AND length(evidence_candidate_id) > 4
                ),
                evidence_asset_id TEXT NOT NULL,
                case_id TEXT NOT NULL,
                field_name TEXT NOT NULL CHECK (
                    field_name = trim(field_name)
                    AND length(field_name) BETWEEN 1 AND 300
                ),
                value_json TEXT NOT NULL CHECK (json_valid(value_json)),
                unit TEXT CHECK (
                    unit IS NULL OR (
                        unit = trim(unit) AND length(unit) BETWEEN 1 AND 100
                    )
                ),
                confidence REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
                source_location_json TEXT NOT NULL CHECK (
                    json_valid(source_location_json)
                ),
                extracted_at TEXT NOT NULL,
                FOREIGN KEY(evidence_asset_id, case_id)
                    REFERENCES decision_evidence_assets(evidence_asset_id, case_id)
                    ON DELETE RESTRICT,
                UNIQUE(evidence_candidate_id, evidence_asset_id, case_id)
            );

            CREATE TABLE IF NOT EXISTS decision_evidence_receipts (
                evidence_receipt_id TEXT PRIMARY KEY CHECK (
                    evidence_receipt_id GLOB 'evr_*'
                    AND length(evidence_receipt_id) > 4
                ),
                evidence_candidate_id TEXT NOT NULL UNIQUE,
                evidence_asset_id TEXT NOT NULL,
                case_id TEXT NOT NULL,
                decision TEXT NOT NULL CHECK (decision IN ('accepted','rejected')),
                evidence_class TEXT NOT NULL CHECK (
                    evidence_class IN (
                        'project_actual','direct_quote_or_primary_document',
                        'public_market_proxy_or_benchmark',
                        'engineering_judgment','secondary_synthesis'
                    )
                ),
                field_name TEXT NOT NULL,
                value_json TEXT NOT NULL CHECK (json_valid(value_json)),
                unit TEXT,
                confidence REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
                source_location_json TEXT NOT NULL CHECK (
                    json_valid(source_location_json)
                ),
                asset_sha256 TEXT NOT NULL CHECK (
                    length(asset_sha256) = 64
                    AND asset_sha256 NOT GLOB '*[^0-9a-f]*'
                ),
                asset_byte_count INTEGER NOT NULL CHECK (asset_byte_count > 0),
                preservation_mode TEXT NOT NULL CHECK (
                    preservation_mode = 'server_managed_content_v1'
                ),
                operator_name TEXT NOT NULL CHECK (
                    operator_name = trim(operator_name)
                    AND length(operator_name) BETWEEN 1 AND 200
                ),
                rationale TEXT,
                reviewed_at TEXT NOT NULL,
                receipt_json TEXT NOT NULL CHECK (json_valid(receipt_json)),
                receipt_sha256 TEXT NOT NULL CHECK (
                    length(receipt_sha256) = 64
                    AND receipt_sha256 NOT GLOB '*[^0-9a-f]*'
                ),
                FOREIGN KEY(evidence_candidate_id, evidence_asset_id, case_id)
                    REFERENCES decision_evidence_candidates(
                        evidence_candidate_id, evidence_asset_id, case_id
                    ) ON DELETE RESTRICT
            );

            CREATE TABLE IF NOT EXISTS decision_events (
                event_sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT NOT NULL UNIQUE CHECK (
                    event_id GLOB 'devt_*' AND length(event_id) > 5
                ),
                case_id TEXT NOT NULL
                    REFERENCES decision_cases(case_id) ON DELETE RESTRICT,
                turn_id TEXT,
                event_type TEXT NOT NULL CHECK (
                    event_type = trim(event_type)
                    AND length(event_type) BETWEEN 1 AND 100
                ),
                actor_kind TEXT NOT NULL CHECK (
                    actor_kind IN ('operator','decision_agent','system')
                ),
                operator_name TEXT,
                trace_id TEXT CHECK (
                    trace_id IS NULL OR (
                        trace_id = trim(trace_id)
                        AND length(trace_id) BETWEEN 1 AND 200
                    )
                ),
                payload_json TEXT NOT NULL CHECK (json_valid(payload_json)),
                created_at TEXT NOT NULL,
                FOREIGN KEY(turn_id, case_id)
                    REFERENCES decision_agent_turns(turn_id, case_id)
                    ON DELETE RESTRICT,
                CHECK (
                    (actor_kind = 'operator'
                        AND operator_name IS NOT NULL
                        AND operator_name = trim(operator_name)
                        AND length(operator_name) BETWEEN 1 AND 200)
                    OR (actor_kind <> 'operator' AND operator_name IS NULL)
                )
            );

            CREATE INDEX IF NOT EXISTS decision_cases_status_updated_idx
                ON decision_cases(status, updated_at DESC, case_id DESC);
            CREATE INDEX IF NOT EXISTS decision_cases_source_idx
                ON decision_cases(source_annual_job_id)
                WHERE source_annual_job_id IS NOT NULL;
            CREATE INDEX IF NOT EXISTS decision_turns_case_state_idx
                ON decision_agent_turns(case_id, state, created_at, turn_id);
            CREATE UNIQUE INDEX IF NOT EXISTS decision_turns_claim_token_unique
                ON decision_agent_turns(claim_token)
                WHERE claim_token IS NOT NULL;
            CREATE INDEX IF NOT EXISTS decision_messages_case_sequence_idx
                ON decision_messages(case_id, message_sequence DESC);
            CREATE INDEX IF NOT EXISTS decision_evidence_case_live_idx
                ON decision_evidence_assets(case_id, removed_at, uploaded_at DESC);
            CREATE INDEX IF NOT EXISTS decision_evidence_sha256_idx
                ON decision_evidence_assets(sha256);
            CREATE INDEX IF NOT EXISTS decision_candidates_asset_idx
                ON decision_evidence_candidates(evidence_asset_id, extracted_at);
            CREATE INDEX IF NOT EXISTS decision_receipts_case_decision_idx
                ON decision_evidence_receipts(case_id, decision, reviewed_at DESC);
            CREATE INDEX IF NOT EXISTS decision_events_case_sequence_idx
                ON decision_events(case_id, event_sequence);
            CREATE INDEX IF NOT EXISTS decision_events_turn_sequence_idx
                ON decision_events(turn_id, event_sequence)
                WHERE turn_id IS NOT NULL;

            CREATE TRIGGER IF NOT EXISTS decision_case_insert_guard
            BEFORE INSERT ON decision_cases
            WHEN NEW.status <> 'draft'
                 OR NEW.revision <> 1
                 OR NEW.archived_at IS NOT NULL
            BEGIN
                SELECT RAISE(ABORT, 'decision cases must begin as revision-one drafts');
            END;

            CREATE TRIGGER IF NOT EXISTS decision_case_identity_is_immutable
            BEFORE UPDATE OF case_id, original_question, created_by, created_at
            ON decision_cases
            BEGIN
                SELECT RAISE(ABORT, 'decision case identity is immutable');
            END;

            CREATE TRIGGER IF NOT EXISTS decision_case_revision_must_increment
            BEFORE UPDATE ON decision_cases
            WHEN NEW.revision <> OLD.revision + 1
            BEGIN
                SELECT RAISE(ABORT, 'decision case revision must increment by one');
            END;

            CREATE TRIGGER IF NOT EXISTS decision_case_transition_guard
            BEFORE UPDATE OF status ON decision_cases
            WHEN NEW.status <> OLD.status AND NOT (
                (OLD.status = 'draft'
                    AND NEW.status IN ('evidence_needed','blocked','archived'))
                OR (OLD.status = 'evidence_needed'
                    AND NEW.status IN ('blocked','ready_to_run','archived'))
                OR (OLD.status = 'blocked'
                    AND NEW.status IN ('evidence_needed','ready_to_run','archived'))
                OR (OLD.status = 'ready_to_run'
                    AND NEW.status IN ('evidence_needed','blocked','running','archived'))
                OR (OLD.status = 'running' AND NEW.status = 'results_ready')
                OR (OLD.status = 'results_ready' AND NEW.status = 'decision_ready')
                OR (OLD.status = 'decision_ready' AND NEW.status = 'signed')
                OR (OLD.status = 'signed' AND NEW.status = 'archived')
            )
            BEGIN
                SELECT RAISE(ABORT, 'invalid decision case state transition');
            END;

            CREATE TRIGGER IF NOT EXISTS decision_case_active_turn_archive_guard
            BEFORE UPDATE OF status ON decision_cases
            WHEN NEW.status IN ('signed','archived') AND EXISTS (
                SELECT 1 FROM decision_agent_turns
                 WHERE case_id = OLD.case_id
                   AND state IN ('pending','claimed')
            )
            BEGIN
                SELECT RAISE(ABORT, 'active decision turns must finish first');
            END;

            CREATE TRIGGER IF NOT EXISTS decision_case_signed_mutation_guard
            BEFORE UPDATE ON decision_cases
            WHEN OLD.status = 'signed' AND NEW.status <> 'archived'
            BEGIN
                SELECT RAISE(ABORT, 'signed decision cases are read-only');
            END;

            CREATE TRIGGER IF NOT EXISTS decision_case_archived_mutation_guard
            BEFORE UPDATE ON decision_cases
            WHEN OLD.status = 'archived'
            BEGIN
                SELECT RAISE(ABORT, 'archived decision cases are read-only');
            END;

            CREATE TRIGGER IF NOT EXISTS decision_case_source_basis_is_one_way
            BEFORE UPDATE OF
                source_annual_job_id, source_snapshot_sha256, analysis_basis,
                source_basis_locked_at, source_basis_locked_by
            ON decision_cases
            WHEN OLD.source_annual_job_id IS NOT NULL AND NOT (
                NEW.source_annual_job_id IS OLD.source_annual_job_id
                AND NEW.source_snapshot_sha256 IS OLD.source_snapshot_sha256
                AND NEW.analysis_basis IS OLD.analysis_basis
                AND NEW.source_basis_locked_at IS OLD.source_basis_locked_at
                AND NEW.source_basis_locked_by IS OLD.source_basis_locked_by
            )
            BEGIN
                SELECT RAISE(ABORT, 'decision case source and basis lock is immutable');
            END;

            CREATE TRIGGER IF NOT EXISTS decision_case_source_insert_guard
            BEFORE INSERT ON decision_cases
            WHEN NEW.source_annual_job_id IS NOT NULL AND NOT EXISTS (
                SELECT 1 FROM jobs
                 WHERE job_id = NEW.source_annual_job_id
                   AND mode = 'annual' AND state = 'done'
            )
            BEGIN
                SELECT RAISE(ABORT, 'decision case source must be a completed annual job');
            END;

            CREATE TRIGGER IF NOT EXISTS decision_case_source_update_guard
            BEFORE UPDATE OF source_annual_job_id ON decision_cases
            WHEN NEW.source_annual_job_id IS NOT NULL AND NOT EXISTS (
                SELECT 1 FROM jobs
                 WHERE job_id = NEW.source_annual_job_id
                   AND mode = 'annual' AND state = 'done'
            )
            BEGIN
                SELECT RAISE(ABORT, 'decision case source must be a completed annual job');
            END;

            CREATE TRIGGER IF NOT EXISTS retained_decision_case_annual_source_guard
            BEFORE UPDATE OF
                request_json, result_json, provenance_json, artifacts_json,
                source_path, source_hash, kind, mode, state
            ON jobs
            WHEN EXISTS (
                SELECT 1 FROM decision_cases
                 WHERE source_annual_job_id = OLD.job_id
            )
            BEGIN
                SELECT RAISE(ABORT, 'decision case annual source payload is retained');
            END;

            CREATE TRIGGER IF NOT EXISTS decision_case_delete_guard
            BEFORE DELETE ON decision_cases
            BEGIN
                SELECT RAISE(ABORT, 'decision cases are archived, not deleted');
            END;

            CREATE TRIGGER IF NOT EXISTS decision_turn_identity_is_immutable
            BEFORE UPDATE OF turn_id, case_id, client_message_id, created_by, created_at
            ON decision_agent_turns
            BEGIN
                SELECT RAISE(ABORT, 'decision turn identity is immutable');
            END;

            CREATE TRIGGER IF NOT EXISTS decision_turn_transition_guard
            BEFORE UPDATE OF state ON decision_agent_turns
            WHEN NEW.state <> OLD.state AND NOT (
                (OLD.state = 'pending' AND NEW.state = 'claimed')
                OR (OLD.state = 'claimed' AND NEW.state IN ('completed','failed'))
            )
            BEGIN
                SELECT RAISE(ABORT, 'invalid decision turn state transition');
            END;

            CREATE TRIGGER IF NOT EXISTS decision_turn_terminal_is_immutable
            BEFORE UPDATE ON decision_agent_turns
            WHEN OLD.state IN ('completed','failed')
            BEGIN
                SELECT RAISE(ABORT, 'terminal decision turn is immutable');
            END;

            CREATE TRIGGER IF NOT EXISTS decision_turn_claim_is_immutable
            BEFORE UPDATE OF worker_id, claim_token, claimed_at
            ON decision_agent_turns
            WHEN OLD.state <> 'pending' AND NOT (
                NEW.worker_id IS OLD.worker_id
                AND NEW.claim_token IS OLD.claim_token
                AND NEW.claimed_at IS OLD.claimed_at
            )
            BEGIN
                SELECT RAISE(ABORT, 'decision turn claim identity is immutable');
            END;

            CREATE TRIGGER IF NOT EXISTS decision_turn_trace_is_one_way
            BEFORE UPDATE OF trace_id ON decision_agent_turns
            WHEN OLD.trace_id IS NOT NULL AND NEW.trace_id IS NOT OLD.trace_id
            BEGIN
                SELECT RAISE(ABORT, 'decision turn trace identity is immutable');
            END;

            CREATE TRIGGER IF NOT EXISTS decision_turn_delete_guard
            BEFORE DELETE ON decision_agent_turns
            BEGIN
                SELECT RAISE(ABORT, 'decision turns are immutable');
            END;

            CREATE TRIGGER IF NOT EXISTS decision_message_update_guard
            BEFORE UPDATE ON decision_messages
            BEGIN
                SELECT RAISE(ABORT, 'decision messages are append-only');
            END;

            CREATE TRIGGER IF NOT EXISTS decision_message_delete_guard
            BEFORE DELETE ON decision_messages
            BEGIN
                SELECT RAISE(ABORT, 'decision messages are append-only');
            END;

            CREATE TRIGGER IF NOT EXISTS decision_evidence_insert_must_be_active
            BEFORE INSERT ON decision_evidence_assets
            WHEN NEW.removed_at IS NOT NULL
                 OR NEW.removed_by IS NOT NULL
                 OR NEW.removed_reason IS NOT NULL
            BEGIN
                SELECT RAISE(ABORT, 'decision evidence must begin active');
            END;

            CREATE TRIGGER IF NOT EXISTS decision_evidence_file_limit_guard
            BEFORE INSERT ON decision_evidence_assets
            WHEN NEW.byte_count > 10485760
            BEGIN
                SELECT RAISE(ABORT, 'decision evidence file limit exceeded');
            END;

            CREATE TRIGGER IF NOT EXISTS decision_evidence_count_limit_guard
            BEFORE INSERT ON decision_evidence_assets
            WHEN (
                SELECT COUNT(*) FROM decision_evidence_assets
                 WHERE case_id = NEW.case_id AND removed_at IS NULL
            ) >= 10
            BEGIN
                SELECT RAISE(ABORT, 'decision evidence count limit exceeded');
            END;

            CREATE TRIGGER IF NOT EXISTS decision_evidence_case_bytes_limit_guard
            BEFORE INSERT ON decision_evidence_assets
            WHEN COALESCE((
                SELECT SUM(byte_count) FROM decision_evidence_assets
                 WHERE case_id = NEW.case_id AND removed_at IS NULL
            ), 0) + NEW.byte_count > 52428800
            BEGIN
                SELECT RAISE(ABORT, 'decision evidence case byte limit exceeded');
            END;

            CREATE TRIGGER IF NOT EXISTS decision_evidence_asset_identity_is_immutable
            BEFORE UPDATE OF
                evidence_asset_id, case_id, evidence_class, original_filename,
                display_filename, declared_media_type, detected_media_type,
                canonical_extension, sha256, byte_count, storage_key,
                extraction_status, extraction_metadata_json,
                source_metadata_json, uploaded_by, uploaded_at
            ON decision_evidence_assets
            BEGIN
                SELECT RAISE(ABORT, 'decision evidence identity is immutable');
            END;

            CREATE TRIGGER IF NOT EXISTS decision_evidence_removal_is_one_way
            BEFORE UPDATE OF removed_by, removed_reason, removed_at
            ON decision_evidence_assets
            WHEN OLD.removed_at IS NOT NULL
            BEGIN
                SELECT RAISE(ABORT, 'removed decision evidence is immutable');
            END;

            CREATE TRIGGER IF NOT EXISTS accepted_evidence_removal_guard
            BEFORE UPDATE OF removed_at ON decision_evidence_assets
            WHEN NEW.removed_at IS NOT NULL AND EXISTS (
                SELECT 1 FROM decision_evidence_receipts
                 WHERE evidence_asset_id = OLD.evidence_asset_id
                   AND decision = 'accepted'
            )
            BEGIN
                SELECT RAISE(ABORT, 'accepted decision evidence cannot be removed');
            END;

            CREATE TRIGGER IF NOT EXISTS decision_evidence_asset_delete_guard
            BEFORE DELETE ON decision_evidence_assets
            BEGIN
                SELECT RAISE(ABORT, 'decision evidence is tombstoned, not deleted');
            END;

            CREATE TRIGGER IF NOT EXISTS decision_evidence_candidate_update_guard
            BEFORE UPDATE ON decision_evidence_candidates
            BEGIN
                SELECT RAISE(ABORT, 'decision evidence candidates are immutable');
            END;

            CREATE TRIGGER IF NOT EXISTS decision_evidence_candidate_delete_guard
            BEFORE DELETE ON decision_evidence_candidates
            BEGIN
                SELECT RAISE(ABORT, 'decision evidence candidates are immutable');
            END;

            CREATE TRIGGER IF NOT EXISTS decision_evidence_receipt_snapshot_guard
            BEFORE INSERT ON decision_evidence_receipts
            WHEN NOT EXISTS (
                SELECT 1
                  FROM decision_evidence_candidates c
                  JOIN decision_evidence_assets a
                    ON a.evidence_asset_id = c.evidence_asset_id
                   AND a.case_id = c.case_id
                 WHERE c.evidence_candidate_id = NEW.evidence_candidate_id
                   AND c.evidence_asset_id = NEW.evidence_asset_id
                   AND c.case_id = NEW.case_id
                   AND c.field_name = NEW.field_name
                   AND c.value_json = NEW.value_json
                   AND c.unit IS NEW.unit
                   AND c.confidence = NEW.confidence
                   AND c.source_location_json = NEW.source_location_json
                   AND a.evidence_class = NEW.evidence_class
                   AND a.sha256 = NEW.asset_sha256
                   AND a.byte_count = NEW.asset_byte_count
                   AND a.removed_at IS NULL
            )
            BEGIN
                SELECT RAISE(ABORT, 'evidence receipt does not match immutable evidence');
            END;

            CREATE TRIGGER IF NOT EXISTS provisional_evidence_rationale_guard
            BEFORE INSERT ON decision_evidence_receipts
            WHEN NEW.decision = 'accepted'
                 AND NEW.evidence_class IN (
                    'engineering_judgment','secondary_synthesis'
                 )
                 AND (NEW.rationale IS NULL OR length(trim(NEW.rationale)) = 0)
            BEGIN
                SELECT RAISE(ABORT, 'provisional evidence requires a rationale');
            END;

            CREATE TRIGGER IF NOT EXISTS decision_evidence_receipt_update_guard
            BEFORE UPDATE ON decision_evidence_receipts
            BEGIN
                SELECT RAISE(ABORT, 'decision evidence receipts are immutable');
            END;

            CREATE TRIGGER IF NOT EXISTS decision_evidence_receipt_delete_guard
            BEFORE DELETE ON decision_evidence_receipts
            BEGIN
                SELECT RAISE(ABORT, 'decision evidence receipts are immutable');
            END;

            CREATE TRIGGER IF NOT EXISTS decision_event_update_guard
            BEFORE UPDATE ON decision_events
            BEGIN
                SELECT RAISE(ABORT, 'decision events are append-only');
            END;

            CREATE TRIGGER IF NOT EXISTS decision_event_delete_guard
            BEFORE DELETE ON decision_events
            BEGIN
                SELECT RAISE(ABORT, 'decision events are append-only');
            END;
            """
        )
        connection.execute(
            "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (?, ?)",
            (6, applied_at),
        )
        connection.execute("PRAGMA user_version = 6")
        connection.commit()

    def _migrate_v7(self, connection: sqlite3.Connection) -> None:
        """Add append-only Autonomy scenario revisions and execution receipts."""

        applied_at = _timestamp(self._current_time())
        connection.executescript(
            """
            BEGIN IMMEDIATE;

            CREATE TABLE IF NOT EXISTS decision_scenarios (
                scenario_revision_id TEXT PRIMARY KEY CHECK (
                    scenario_revision_id GLOB 'dscr_*'
                    AND length(scenario_revision_id) > 5
                ),
                scenario_id TEXT NOT NULL CHECK (
                    scenario_id GLOB 'dsc_*' AND length(scenario_id) > 4
                ),
                case_id TEXT NOT NULL
                    REFERENCES decision_cases(case_id) ON DELETE RESTRICT,
                label TEXT NOT NULL CHECK (
                    label = trim(label) AND length(label) BETWEEN 1 AND 200
                ),
                kind TEXT NOT NULL CHECK (kind IN ('baseline','alternative')),
                revision INTEGER NOT NULL CHECK (revision > 0),
                parent_revision_id TEXT UNIQUE
                    REFERENCES decision_scenarios(scenario_revision_id)
                    ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED,
                superseded_by_revision_id TEXT UNIQUE
                    REFERENCES decision_scenarios(scenario_revision_id)
                    ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED,
                status TEXT NOT NULL CHECK (
                    status IN ('draft','invalid','validated','confirmed','expired')
                ),
                request_json TEXT NOT NULL CHECK (json_valid(request_json)),
                request_sha256 TEXT NOT NULL CHECK (
                    length(request_sha256) = 64
                    AND request_sha256 NOT GLOB '*[^0-9a-f]*'
                ),
                changed_fields_json TEXT NOT NULL CHECK (
                    json_valid(changed_fields_json)
                    AND json_type(changed_fields_json) = 'array'
                ),
                comparison_classification TEXT NOT NULL CHECK (
                    comparison_classification IN ('baseline','controlled','structural')
                ),
                validation_json TEXT CHECK (
                    validation_json IS NULL OR json_valid(validation_json)
                ),
                validation_sha256 TEXT CHECK (
                    validation_sha256 IS NULL OR (
                        length(validation_sha256) = 64
                        AND validation_sha256 NOT GLOB '*[^0-9a-f]*'
                    )
                ),
                source_annual_job_id TEXT NOT NULL
                    REFERENCES jobs(job_id) ON DELETE RESTRICT,
                source_snapshot_sha256 TEXT NOT NULL CHECK (
                    length(source_snapshot_sha256) = 64
                    AND source_snapshot_sha256 NOT GLOB '*[^0-9a-f]*'
                ),
                analysis_basis TEXT NOT NULL CHECK (
                    analysis_basis IN ('solartac_site','commercial_representative')
                ),
                confirmation_id TEXT
                    REFERENCES decision_scenario_confirmations(confirmation_id)
                    ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED,
                created_by TEXT NOT NULL CHECK (
                    created_by = trim(created_by)
                    AND length(created_by) BETWEEN 1 AND 200
                ),
                updated_by TEXT NOT NULL CHECK (
                    updated_by = trim(updated_by)
                    AND length(updated_by) BETWEEN 1 AND 200
                ),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                validated_at TEXT,
                confirmed_at TEXT,
                expired_at TEXT,
                UNIQUE(scenario_id, revision),
                UNIQUE(scenario_revision_id, case_id),
                CHECK (
                    (revision = 1 AND parent_revision_id IS NULL)
                    OR (revision > 1 AND parent_revision_id IS NOT NULL)
                ),
                CHECK (
                    (kind = 'baseline' AND comparison_classification = 'baseline')
                    OR (kind = 'alternative'
                        AND comparison_classification IN ('controlled','structural'))
                ),
                CHECK (
                    (status = 'draft'
                        AND validation_json IS NULL
                        AND validation_sha256 IS NULL
                        AND validated_at IS NULL
                        AND confirmation_id IS NULL
                        AND confirmed_at IS NULL
                        AND expired_at IS NULL)
                    OR (status IN ('invalid','validated')
                        AND validation_json IS NOT NULL
                        AND validation_sha256 IS NOT NULL
                        AND validated_at IS NOT NULL
                        AND confirmation_id IS NULL
                        AND confirmed_at IS NULL
                        AND expired_at IS NULL)
                    OR (status = 'confirmed'
                        AND validation_json IS NOT NULL
                        AND validation_sha256 IS NOT NULL
                        AND validated_at IS NOT NULL
                        AND confirmation_id IS NOT NULL
                        AND confirmed_at IS NOT NULL
                        AND expired_at IS NULL)
                    OR (status = 'expired'
                        AND confirmation_id IS NULL
                        AND confirmed_at IS NULL
                        AND expired_at IS NOT NULL)
                )
            );

            CREATE TABLE IF NOT EXISTS decision_scenario_evidence (
                scenario_revision_id TEXT NOT NULL,
                request_path TEXT NOT NULL CHECK (
                    request_path = trim(request_path)
                    AND request_path GLOB '/*'
                    AND length(request_path) BETWEEN 1 AND 500
                ),
                evidence_receipt_id TEXT NOT NULL,
                case_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY(scenario_revision_id, request_path),
                FOREIGN KEY(scenario_revision_id, case_id)
                    REFERENCES decision_scenarios(scenario_revision_id, case_id)
                    ON DELETE RESTRICT,
                FOREIGN KEY(evidence_receipt_id)
                    REFERENCES decision_evidence_receipts(evidence_receipt_id)
                    ON DELETE RESTRICT
            );

            CREATE TABLE IF NOT EXISTS decision_scenario_confirmations (
                confirmation_id TEXT PRIMARY KEY CHECK (
                    confirmation_id GLOB 'dconf_*'
                    AND length(confirmation_id) > 6
                ),
                case_id TEXT NOT NULL
                    REFERENCES decision_cases(case_id) ON DELETE RESTRICT,
                idempotency_key TEXT NOT NULL CHECK (
                    idempotency_key = trim(idempotency_key)
                    AND length(idempotency_key) BETWEEN 1 AND 200
                ),
                expected_case_revision INTEGER NOT NULL CHECK (
                    expected_case_revision > 0
                ),
                case_revision_after INTEGER NOT NULL CHECK (
                    case_revision_after = expected_case_revision + 1
                ),
                confirmation_request_json TEXT NOT NULL CHECK (
                    json_valid(confirmation_request_json)
                ),
                confirmation_request_sha256 TEXT NOT NULL CHECK (
                    length(confirmation_request_sha256) = 64
                    AND confirmation_request_sha256 NOT GLOB '*[^0-9a-f]*'
                ),
                receipt_json TEXT NOT NULL CHECK (json_valid(receipt_json)),
                receipt_sha256 TEXT NOT NULL CHECK (
                    length(receipt_sha256) = 64
                    AND receipt_sha256 NOT GLOB '*[^0-9a-f]*'
                ),
                operator_name TEXT NOT NULL CHECK (
                    operator_name = trim(operator_name)
                    AND length(operator_name) BETWEEN 1 AND 200
                ),
                rationale TEXT NOT NULL CHECK (
                    rationale = trim(rationale)
                    AND length(rationale) BETWEEN 1 AND 4000
                ),
                acknowledgement TEXT NOT NULL CHECK (
                    acknowledgement = trim(acknowledgement)
                    AND length(acknowledgement) BETWEEN 1 AND 4000
                ),
                confirmed_at TEXT NOT NULL,
                UNIQUE(case_id, idempotency_key),
                UNIQUE(confirmation_id, case_id)
            );

            CREATE TABLE IF NOT EXISTS decision_scenario_confirmation_items (
                confirmation_id TEXT NOT NULL,
                case_id TEXT NOT NULL,
                item_index INTEGER NOT NULL CHECK (item_index BETWEEN 0 AND 3),
                scenario_revision_id TEXT NOT NULL UNIQUE,
                scenario_id TEXT NOT NULL,
                scenario_revision INTEGER NOT NULL CHECK (scenario_revision > 0),
                request_sha256 TEXT NOT NULL CHECK (
                    length(request_sha256) = 64
                    AND request_sha256 NOT GLOB '*[^0-9a-f]*'
                ),
                tea_job_id TEXT NOT NULL UNIQUE
                    REFERENCES technoeconomic_jobs(tea_job_id) ON DELETE RESTRICT,
                created_at TEXT NOT NULL,
                PRIMARY KEY(confirmation_id, item_index),
                FOREIGN KEY(confirmation_id, case_id)
                    REFERENCES decision_scenario_confirmations(confirmation_id, case_id)
                    ON DELETE RESTRICT,
                FOREIGN KEY(scenario_revision_id, case_id)
                    REFERENCES decision_scenarios(scenario_revision_id, case_id)
                    ON DELETE RESTRICT,
                FOREIGN KEY(scenario_id, scenario_revision)
                    REFERENCES decision_scenarios(scenario_id, revision)
                    ON DELETE RESTRICT
            );

            CREATE TABLE IF NOT EXISTS decision_scenario_jobs (
                tea_job_id TEXT PRIMARY KEY
                    REFERENCES technoeconomic_jobs(tea_job_id) ON DELETE RESTRICT,
                scenario_revision_id TEXT NOT NULL,
                case_id TEXT NOT NULL,
                attempt_number INTEGER NOT NULL CHECK (attempt_number > 0),
                retry_of_job_id TEXT
                    REFERENCES technoeconomic_jobs(tea_job_id) ON DELETE RESTRICT,
                confirmation_id TEXT
                    REFERENCES decision_scenario_confirmations(confirmation_id)
                    ON DELETE RESTRICT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(scenario_revision_id, case_id)
                    REFERENCES decision_scenarios(scenario_revision_id, case_id)
                    ON DELETE RESTRICT,
                UNIQUE(scenario_revision_id, attempt_number),
                CHECK (
                    (attempt_number = 1
                        AND retry_of_job_id IS NULL
                        AND confirmation_id IS NOT NULL)
                    OR (attempt_number > 1
                        AND retry_of_job_id IS NOT NULL
                        AND confirmation_id IS NULL)
                )
            );

            CREATE TABLE IF NOT EXISTS decision_scenario_confirmation_idempotency (
                case_id TEXT NOT NULL,
                idempotency_key TEXT NOT NULL,
                confirmation_request_sha256 TEXT NOT NULL CHECK (
                    length(confirmation_request_sha256) = 64
                    AND confirmation_request_sha256 NOT GLOB '*[^0-9a-f]*'
                ),
                confirmation_id TEXT NOT NULL UNIQUE
                    REFERENCES decision_scenario_confirmations(confirmation_id)
                    ON DELETE RESTRICT,
                response_json TEXT NOT NULL CHECK (json_valid(response_json)),
                response_sha256 TEXT NOT NULL CHECK (
                    length(response_sha256) = 64
                    AND response_sha256 NOT GLOB '*[^0-9a-f]*'
                ),
                created_at TEXT NOT NULL,
                PRIMARY KEY(case_id, idempotency_key),
                FOREIGN KEY(case_id, idempotency_key)
                    REFERENCES decision_scenario_confirmations(case_id, idempotency_key)
                    ON DELETE RESTRICT
            );

            CREATE UNIQUE INDEX IF NOT EXISTS decision_scenario_live_revision_idx
                ON decision_scenarios(scenario_id)
                WHERE superseded_by_revision_id IS NULL;
            CREATE INDEX IF NOT EXISTS decision_scenarios_case_live_idx
                ON decision_scenarios(
                    case_id, superseded_by_revision_id, status, kind, created_at
                );
            CREATE INDEX IF NOT EXISTS decision_scenarios_expiry_idx
                ON decision_scenarios(status, expires_at)
                WHERE status IN ('draft','invalid','validated');
            CREATE INDEX IF NOT EXISTS decision_scenario_evidence_receipt_idx
                ON decision_scenario_evidence(evidence_receipt_id);
            CREATE INDEX IF NOT EXISTS decision_scenario_items_case_idx
                ON decision_scenario_confirmation_items(case_id, confirmation_id);
            CREATE INDEX IF NOT EXISTS decision_scenario_jobs_revision_idx
                ON decision_scenario_jobs(scenario_revision_id, attempt_number DESC);
            CREATE UNIQUE INDEX IF NOT EXISTS decision_scenario_retry_once_idx
                ON decision_scenario_jobs(scenario_revision_id, retry_of_job_id)
                WHERE retry_of_job_id IS NOT NULL;

            CREATE TRIGGER IF NOT EXISTS decision_scenario_insert_guard
            BEFORE INSERT ON decision_scenarios
            WHEN NEW.status <> 'draft'
                 OR NEW.validation_json IS NOT NULL
                 OR NEW.confirmation_id IS NOT NULL
                 OR NEW.validated_at IS NOT NULL
                 OR NEW.confirmed_at IS NOT NULL
                 OR NEW.expired_at IS NOT NULL
            BEGIN
                SELECT RAISE(ABORT, 'decision scenario revisions must begin as drafts');
            END;

            CREATE TRIGGER IF NOT EXISTS decision_scenario_source_basis_guard
            BEFORE INSERT ON decision_scenarios
            WHEN NOT EXISTS (
                SELECT 1 FROM decision_cases c
                 WHERE c.case_id = NEW.case_id
                   AND c.source_annual_job_id = NEW.source_annual_job_id
                   AND c.source_snapshot_sha256 = NEW.source_snapshot_sha256
                   AND c.analysis_basis = NEW.analysis_basis
                   AND c.source_basis_locked_at IS NOT NULL
                   AND c.status NOT IN ('signed','archived')
            )
            BEGIN
                SELECT RAISE(ABORT, 'decision scenario must match the immutable case source and basis');
            END;

            CREATE TRIGGER IF NOT EXISTS decision_scenario_lineage_guard
            BEFORE INSERT ON decision_scenarios
            WHEN NEW.revision > 1 AND NOT EXISTS (
                SELECT 1 FROM decision_scenarios p
                 WHERE p.scenario_revision_id = NEW.parent_revision_id
                   AND p.scenario_id = NEW.scenario_id
                   AND p.case_id = NEW.case_id
                   AND p.kind = NEW.kind
                   AND p.revision = NEW.revision - 1
            )
            BEGIN
                SELECT RAISE(ABORT, 'decision scenario revision lineage is invalid');
            END;

            CREATE TRIGGER IF NOT EXISTS decision_scenario_baseline_limit_guard
            BEFORE INSERT ON decision_scenarios
            WHEN NEW.kind = 'baseline' AND EXISTS (
                SELECT 1 FROM decision_scenarios s
                 WHERE s.case_id = NEW.case_id
                   AND s.kind = 'baseline'
                   AND s.status <> 'expired'
                   AND s.superseded_by_revision_id IS NULL
                   AND s.scenario_id <> NEW.scenario_id
            )
            BEGIN
                SELECT RAISE(ABORT, 'decision case already has a live baseline scenario');
            END;

            CREATE TRIGGER IF NOT EXISTS decision_scenario_alternative_limit_guard
            BEFORE INSERT ON decision_scenarios
            WHEN NEW.kind = 'alternative' AND (
                SELECT COUNT(DISTINCT s.scenario_id)
                  FROM decision_scenarios s
                 WHERE s.case_id = NEW.case_id
                   AND s.kind = 'alternative'
                   AND s.status <> 'expired'
                   AND s.superseded_by_revision_id IS NULL
                   AND s.scenario_id <> NEW.scenario_id
            ) >= 3
            BEGIN
                SELECT RAISE(ABORT, 'decision case cannot have more than three live alternatives');
            END;

            CREATE TRIGGER IF NOT EXISTS decision_scenario_core_is_immutable
            BEFORE UPDATE OF
                scenario_revision_id, scenario_id, case_id, label, kind, revision,
                parent_revision_id, request_json, request_sha256,
                changed_fields_json, comparison_classification,
                source_annual_job_id, source_snapshot_sha256, analysis_basis,
                created_by, created_at, expires_at
            ON decision_scenarios
            BEGIN
                SELECT RAISE(ABORT, 'decision scenario revision inputs are immutable');
            END;

            CREATE TRIGGER IF NOT EXISTS decision_scenario_validation_is_immutable
            BEFORE UPDATE OF validation_json, validation_sha256, validated_at
            ON decision_scenarios
            WHEN OLD.validation_json IS NOT NULL
                 OR OLD.validation_sha256 IS NOT NULL
                 OR OLD.validated_at IS NOT NULL
            BEGIN
                SELECT RAISE(ABORT, 'decision scenario validation receipts are immutable');
            END;

            CREATE TRIGGER IF NOT EXISTS decision_scenario_status_transition_guard
            BEFORE UPDATE OF status ON decision_scenarios
            WHEN NEW.status <> OLD.status AND NOT (
                (OLD.status = 'draft' AND NEW.status IN ('invalid','validated','expired'))
                OR (OLD.status IN ('invalid','validated') AND NEW.status = 'expired')
                OR (OLD.status = 'validated' AND NEW.status = 'confirmed')
            )
            BEGIN
                SELECT RAISE(ABORT, 'invalid decision scenario state transition');
            END;

            CREATE TRIGGER IF NOT EXISTS decision_scenario_terminal_is_immutable
            BEFORE UPDATE OF
                status, validation_json, validation_sha256, validated_at,
                confirmation_id, confirmed_at, expired_at, updated_by, updated_at
            ON decision_scenarios
            WHEN OLD.status IN ('confirmed','expired')
            BEGIN
                SELECT RAISE(ABORT, 'terminal decision scenario revision is immutable');
            END;

            CREATE TRIGGER IF NOT EXISTS decision_scenario_supersession_is_one_way
            BEFORE UPDATE OF superseded_by_revision_id ON decision_scenarios
            WHEN NOT (
                (OLD.superseded_by_revision_id IS NULL
                    AND NEW.superseded_by_revision_id IS NOT NULL)
                OR (
                    OLD.superseded_by_revision_id GLOB 'dscr_pending_*'
                    AND NEW.superseded_by_revision_id IS NULL
                    AND OLD.revision > 1
                    AND EXISTS (
                        SELECT 1 FROM decision_scenarios p
                         WHERE p.scenario_revision_id = OLD.parent_revision_id
                           AND p.scenario_id = OLD.scenario_id
                           AND p.case_id = OLD.case_id
                           AND p.superseded_by_revision_id = OLD.scenario_revision_id
                    )
                )
            )
            BEGIN
                SELECT RAISE(ABORT, 'decision scenario supersession is immutable');
            END;

            CREATE TRIGGER IF NOT EXISTS decision_scenario_supersession_target_guard
            BEFORE UPDATE OF superseded_by_revision_id ON decision_scenarios
            WHEN OLD.superseded_by_revision_id IS NULL
                 AND NEW.superseded_by_revision_id IS NOT NULL
                 AND NOT EXISTS (
                    SELECT 1 FROM decision_scenarios n
                     WHERE n.scenario_revision_id = NEW.superseded_by_revision_id
                       AND n.scenario_id = OLD.scenario_id
                       AND n.case_id = OLD.case_id
                       AND n.kind = OLD.kind
                       AND n.parent_revision_id = OLD.scenario_revision_id
                       AND n.revision = OLD.revision + 1
                 )
            BEGIN
                SELECT RAISE(ABORT, 'decision scenario supersession target is invalid');
            END;

            CREATE TRIGGER IF NOT EXISTS decision_scenario_delete_guard
            BEFORE DELETE ON decision_scenarios
            BEGIN
                SELECT RAISE(ABORT, 'decision scenario revisions are retained, not deleted');
            END;

            CREATE TRIGGER IF NOT EXISTS decision_scenario_evidence_insert_guard
            BEFORE INSERT ON decision_scenario_evidence
            WHEN NOT EXISTS (
                SELECT 1
                  FROM decision_scenarios s
                  JOIN decision_evidence_receipts r
                    ON r.evidence_receipt_id = NEW.evidence_receipt_id
                 WHERE s.scenario_revision_id = NEW.scenario_revision_id
                   AND s.case_id = NEW.case_id
                   AND s.status = 'draft'
                   AND r.case_id = NEW.case_id
                   AND r.decision = 'accepted'
            )
            BEGIN
                SELECT RAISE(ABORT, 'scenario evidence must be an accepted receipt from the same case');
            END;

            CREATE TRIGGER IF NOT EXISTS decision_scenario_evidence_update_guard
            BEFORE UPDATE ON decision_scenario_evidence
            BEGIN
                SELECT RAISE(ABORT, 'decision scenario evidence links are immutable');
            END;

            CREATE TRIGGER IF NOT EXISTS decision_scenario_evidence_delete_guard
            BEFORE DELETE ON decision_scenario_evidence
            BEGIN
                SELECT RAISE(ABORT, 'decision scenario evidence links are immutable');
            END;

            CREATE TRIGGER IF NOT EXISTS decision_scenario_confirmation_update_guard
            BEFORE UPDATE ON decision_scenario_confirmations
            BEGIN
                SELECT RAISE(ABORT, 'decision scenario confirmations are immutable');
            END;

            CREATE TRIGGER IF NOT EXISTS decision_scenario_confirmation_delete_guard
            BEFORE DELETE ON decision_scenario_confirmations
            BEGIN
                SELECT RAISE(ABORT, 'decision scenario confirmations are immutable');
            END;

            CREATE TRIGGER IF NOT EXISTS decision_scenario_confirmation_item_insert_guard
            BEFORE INSERT ON decision_scenario_confirmation_items
            WHEN NOT EXISTS (
                SELECT 1
                  FROM decision_scenarios s
                  JOIN technoeconomic_jobs j
                    ON j.tea_job_id = NEW.tea_job_id
                 WHERE s.scenario_revision_id = NEW.scenario_revision_id
                   AND s.case_id = NEW.case_id
                   AND s.scenario_id = NEW.scenario_id
                   AND s.revision = NEW.scenario_revision
                   AND s.request_sha256 = NEW.request_sha256
                   AND s.confirmation_id = NEW.confirmation_id
                   AND s.status = 'confirmed'
                   AND j.request_json = s.request_json
                   AND j.source_annual_job_id = s.source_annual_job_id
                   AND j.source_snapshot_sha256 = s.source_snapshot_sha256
            )
            BEGIN
                SELECT RAISE(ABORT, 'confirmation item does not match its immutable scenario and TEA job');
            END;

            CREATE TRIGGER IF NOT EXISTS decision_scenario_confirmation_item_update_guard
            BEFORE UPDATE ON decision_scenario_confirmation_items
            BEGIN
                SELECT RAISE(ABORT, 'decision scenario confirmation items are immutable');
            END;

            CREATE TRIGGER IF NOT EXISTS decision_scenario_confirmation_item_delete_guard
            BEFORE DELETE ON decision_scenario_confirmation_items
            BEGIN
                SELECT RAISE(ABORT, 'decision scenario confirmation items are immutable');
            END;

            CREATE TRIGGER IF NOT EXISTS decision_scenario_job_insert_guard
            BEFORE INSERT ON decision_scenario_jobs
            WHEN NOT EXISTS (
                SELECT 1
                  FROM decision_scenarios s
                  JOIN technoeconomic_jobs j
                    ON j.tea_job_id = NEW.tea_job_id
                 WHERE s.scenario_revision_id = NEW.scenario_revision_id
                   AND s.case_id = NEW.case_id
                   AND s.status = 'confirmed'
                   AND j.request_json = s.request_json
                   AND j.source_annual_job_id = s.source_annual_job_id
                   AND j.source_snapshot_sha256 = s.source_snapshot_sha256
                   AND j.retry_of_job_id IS NEW.retry_of_job_id
                   AND (
                        (NEW.attempt_number = 1
                            AND s.confirmation_id = NEW.confirmation_id
                            AND j.retry_of_job_id IS NULL)
                        OR (NEW.attempt_number > 1
                            AND NEW.confirmation_id IS NULL
                            AND EXISTS (
                                SELECT 1 FROM decision_scenario_jobs prior
                                 WHERE prior.tea_job_id = NEW.retry_of_job_id
                                   AND prior.scenario_revision_id =
                                       NEW.scenario_revision_id
                                   AND prior.case_id = NEW.case_id
                                   AND prior.attempt_number =
                                       NEW.attempt_number - 1
                            ))
                   )
            )
            BEGIN
                SELECT RAISE(ABORT, 'scenario TEA link does not match immutable frozen inputs');
            END;

            CREATE TRIGGER IF NOT EXISTS decision_scenario_job_update_guard
            BEFORE UPDATE ON decision_scenario_jobs
            BEGIN
                SELECT RAISE(ABORT, 'decision scenario TEA links are immutable');
            END;

            CREATE TRIGGER IF NOT EXISTS decision_scenario_job_delete_guard
            BEFORE DELETE ON decision_scenario_jobs
            BEGIN
                SELECT RAISE(ABORT, 'decision scenario TEA links are immutable');
            END;

            CREATE TRIGGER IF NOT EXISTS decision_scenario_idempotency_update_guard
            BEFORE UPDATE ON decision_scenario_confirmation_idempotency
            BEGIN
                SELECT RAISE(ABORT, 'decision scenario idempotency receipts are immutable');
            END;

            CREATE TRIGGER IF NOT EXISTS decision_scenario_idempotency_insert_guard
            BEFORE INSERT ON decision_scenario_confirmation_idempotency
            WHEN NOT EXISTS (
                SELECT 1 FROM decision_scenario_confirmations c
                 WHERE c.confirmation_id = NEW.confirmation_id
                   AND c.case_id = NEW.case_id
                   AND c.idempotency_key = NEW.idempotency_key
                   AND c.confirmation_request_sha256 =
                       NEW.confirmation_request_sha256
            )
            BEGIN
                SELECT RAISE(ABORT, 'idempotency record does not match its confirmation');
            END;

            CREATE TRIGGER IF NOT EXISTS decision_scenario_idempotency_delete_guard
            BEFORE DELETE ON decision_scenario_confirmation_idempotency
            BEGIN
                SELECT RAISE(ABORT, 'decision scenario idempotency receipts are immutable');
            END;

            CREATE TRIGGER IF NOT EXISTS retained_decision_scenario_tea_job_guard
            BEFORE DELETE ON technoeconomic_jobs
            WHEN EXISTS (
                SELECT 1 FROM decision_scenario_jobs
                 WHERE tea_job_id = OLD.tea_job_id
            )
            BEGIN
                SELECT RAISE(ABORT, 'decision scenario TEA jobs are retained');
            END;

            DROP TRIGGER IF EXISTS decision_case_transition_guard;
            CREATE TRIGGER decision_case_transition_guard
            BEFORE UPDATE OF status ON decision_cases
            WHEN NEW.status <> OLD.status AND NOT (
                (OLD.status = 'draft'
                    AND NEW.status IN ('evidence_needed','blocked','archived'))
                OR (OLD.status = 'evidence_needed'
                    AND NEW.status IN ('blocked','ready_to_run','archived'))
                OR (OLD.status = 'blocked'
                    AND NEW.status IN ('evidence_needed','ready_to_run','archived'))
                OR (OLD.status = 'ready_to_run'
                    AND NEW.status IN ('evidence_needed','blocked','running','archived'))
                OR (OLD.status = 'running' AND NEW.status = 'results_ready')
                OR (OLD.status = 'results_ready' AND NEW.status = 'decision_ready')
                OR (OLD.status = 'results_ready' AND NEW.status = 'running'
                    AND EXISTS (
                        SELECT 1
                          FROM decision_scenario_jobs l
                          JOIN technoeconomic_jobs j
                            ON j.tea_job_id = l.tea_job_id
                         WHERE l.case_id = OLD.case_id
                           AND j.state = 'queued'
                           AND j.created_at = NEW.updated_at
                    ))
                OR (OLD.status = 'decision_ready' AND NEW.status = 'signed')
                OR (OLD.status = 'signed' AND NEW.status = 'archived')
            )
            BEGIN
                SELECT RAISE(ABORT, 'invalid decision case state transition');
            END;
            """
        )
        connection.execute(
            "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (?, ?)",
            (7, applied_at),
        )
        connection.execute("PRAGMA user_version = 7")
        connection.commit()

    def _migrate_v8(self, connection: sqlite3.Connection) -> None:
        """Add immutable comparison snapshots and Decision Brief revisions."""

        applied_at = _timestamp(self._current_time())
        connection.executescript(
            """
            BEGIN IMMEDIATE;

            CREATE TABLE IF NOT EXISTS decision_comparison_bundles (
                comparison_bundle_id TEXT PRIMARY KEY CHECK (
                    comparison_bundle_id GLOB 'dcmp_*'
                    AND length(comparison_bundle_id) > 5
                ),
                case_id TEXT NOT NULL
                    REFERENCES decision_cases(case_id) ON DELETE RESTRICT,
                source_confirmation_id TEXT NOT NULL,
                expected_case_revision INTEGER NOT NULL CHECK (
                    expected_case_revision > 0
                ),
                bundle_schema_version TEXT NOT NULL CHECK (
                    bundle_schema_version = trim(bundle_schema_version)
                    AND length(bundle_schema_version) BETWEEN 1 AND 100
                ),
                bundle_json TEXT NOT NULL CHECK (
                    json_valid(bundle_json)
                    AND json_type(bundle_json) = 'object'
                ),
                bundle_sha256 TEXT NOT NULL CHECK (
                    length(bundle_sha256) = 64
                    AND bundle_sha256 NOT GLOB '*[^0-9a-f]*'
                ),
                is_complete INTEGER NOT NULL CHECK (is_complete IN (0,1)),
                recommendation_eligible INTEGER NOT NULL CHECK (
                    recommendation_eligible IN (0,1)
                    AND recommendation_eligible <= is_complete
                    AND recommendation_eligible = 0
                ),
                created_by TEXT NOT NULL CHECK (
                    created_by = trim(created_by)
                    AND length(created_by) BETWEEN 1 AND 200
                ),
                created_at TEXT NOT NULL,
                stale_at TEXT,
                stale_reason_json TEXT CHECK (
                    stale_reason_json IS NULL OR (
                        json_valid(stale_reason_json)
                        AND json_type(stale_reason_json) = 'object'
                    )
                ),
                superseded_by_bundle_id TEXT UNIQUE
                    REFERENCES decision_comparison_bundles(comparison_bundle_id)
                    ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED,
                superseded_at TEXT,
                UNIQUE(comparison_bundle_id, case_id),
                UNIQUE(case_id, source_confirmation_id, bundle_sha256),
                FOREIGN KEY(source_confirmation_id, case_id)
                    REFERENCES decision_scenario_confirmations(
                        confirmation_id, case_id
                    ) ON DELETE RESTRICT,
                CHECK (
                    json_type(bundle_json, '$.is_complete')
                        IN ('true','false')
                    AND json_extract(bundle_json, '$.is_complete') = is_complete
                    AND json_type(bundle_json, '$.recommendation_eligible')
                        IN ('true','false')
                    AND json_extract(
                        bundle_json, '$.recommendation_eligible'
                    ) = recommendation_eligible
                    AND CAST(
                        json_extract(bundle_json, '$.schema_version') AS TEXT
                    ) = bundle_schema_version
                    AND json_type(bundle_json, '$.attempt_proofs') = 'array'
                ),
                CHECK (
                    (stale_at IS NULL AND stale_reason_json IS NULL)
                    OR (stale_at IS NOT NULL AND stale_reason_json IS NOT NULL)
                ),
                CHECK (
                    superseded_at IS NULL
                    OR superseded_by_bundle_id IS NOT NULL
                )
            );

            CREATE TABLE IF NOT EXISTS decision_comparison_bundle_attempts (
                comparison_bundle_id TEXT NOT NULL,
                case_id TEXT NOT NULL,
                item_index INTEGER NOT NULL CHECK (item_index BETWEEN 0 AND 3),
                scenario_revision_id TEXT NOT NULL,
                scenario_id TEXT NOT NULL,
                scenario_revision INTEGER NOT NULL CHECK (scenario_revision > 0),
                attempt_number INTEGER NOT NULL CHECK (attempt_number > 0),
                tea_job_id TEXT NOT NULL
                    REFERENCES technoeconomic_jobs(tea_job_id) ON DELETE RESTRICT,
                retry_of_job_id TEXT
                    REFERENCES technoeconomic_jobs(tea_job_id) ON DELETE RESTRICT,
                selected_for_comparison INTEGER NOT NULL CHECK (
                    selected_for_comparison IN (0,1)
                ),
                state TEXT NOT NULL CHECK (
                    state IN (
                        'queued','running','done','error','cancelled','interrupted'
                    )
                ),
                verification_status TEXT NOT NULL CHECK (
                    verification_status IN (
                        'verified','verification_failed','pending','not_applicable'
                    )
                ),
                request_sha256 TEXT NOT NULL CHECK (
                    length(request_sha256) = 64
                    AND request_sha256 NOT GLOB '*[^0-9a-f]*'
                ),
                source_snapshot_sha256 TEXT NOT NULL CHECK (
                    length(source_snapshot_sha256) = 64
                    AND source_snapshot_sha256 NOT GLOB '*[^0-9a-f]*'
                ),
                result_sha256 TEXT CHECK (
                    result_sha256 IS NULL OR (
                        length(result_sha256) = 64
                        AND result_sha256 NOT GLOB '*[^0-9a-f]*'
                    )
                ),
                result_provenance_sha256 TEXT CHECK (
                    result_provenance_sha256 IS NULL OR (
                        length(result_provenance_sha256) = 64
                        AND result_provenance_sha256 NOT GLOB '*[^0-9a-f]*'
                    )
                ),
                evidence_set_sha256 TEXT NOT NULL CHECK (
                    length(evidence_set_sha256) = 64
                    AND evidence_set_sha256 NOT GLOB '*[^0-9a-f]*'
                ),
                reporting_tieout_sha256 TEXT CHECK (
                    reporting_tieout_sha256 IS NULL OR (
                        length(reporting_tieout_sha256) = 64
                        AND reporting_tieout_sha256 NOT GLOB '*[^0-9a-f]*'
                    )
                ),
                created_at TEXT NOT NULL,
                PRIMARY KEY(comparison_bundle_id, item_index, attempt_number),
                UNIQUE(comparison_bundle_id, tea_job_id),
                FOREIGN KEY(comparison_bundle_id, case_id)
                    REFERENCES decision_comparison_bundles(
                        comparison_bundle_id, case_id
                    ) ON DELETE RESTRICT,
                FOREIGN KEY(scenario_revision_id, case_id)
                    REFERENCES decision_scenarios(scenario_revision_id, case_id)
                    ON DELETE RESTRICT,
                CHECK (
                    verification_status <> 'verified'
                    OR (
                        state = 'done'
                        AND result_sha256 IS NOT NULL
                        AND result_provenance_sha256 IS NOT NULL
                        AND reporting_tieout_sha256 IS NOT NULL
                    )
                )
            );

            CREATE TABLE IF NOT EXISTS decision_briefs (
                brief_revision_id TEXT PRIMARY KEY CHECK (
                    brief_revision_id GLOB 'dbr_*'
                    AND length(brief_revision_id) > 4
                ),
                brief_id TEXT NOT NULL CHECK (
                    brief_id GLOB 'dbf_*' AND length(brief_id) > 4
                ),
                case_id TEXT NOT NULL
                    REFERENCES decision_cases(case_id) ON DELETE RESTRICT,
                revision INTEGER NOT NULL CHECK (revision > 0),
                parent_revision_id TEXT UNIQUE
                    REFERENCES decision_briefs(brief_revision_id)
                    ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED,
                superseded_by_revision_id TEXT UNIQUE
                    REFERENCES decision_briefs(brief_revision_id)
                    ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED,
                source_confirmation_id TEXT NOT NULL,
                comparison_bundle_id TEXT NOT NULL,
                expected_case_revision INTEGER NOT NULL CHECK (
                    expected_case_revision > 0
                ),
                case_revision_after INTEGER NOT NULL CHECK (
                    case_revision_after = expected_case_revision + 1
                ),
                comparison_bundle_json TEXT NOT NULL CHECK (
                    json_valid(comparison_bundle_json)
                    AND json_type(comparison_bundle_json) = 'object'
                ),
                comparison_bundle_sha256 TEXT NOT NULL CHECK (
                    length(comparison_bundle_sha256) = 64
                    AND comparison_bundle_sha256 NOT GLOB '*[^0-9a-f]*'
                ),
                recommendation_classification TEXT NOT NULL CHECK (
                    recommendation_classification IN (
                        'solaredge','solectria','no_decisive_winner',
                        'classification_pending_contract'
                    )
                ),
                confidence_state TEXT NOT NULL CHECK (
                    confidence_state IN (
                        'strong','mixed','provisional',
                        'classification_pending_contract'
                    )
                ),
                caveats_json TEXT NOT NULL CHECK (
                    json_valid(caveats_json) AND json_type(caveats_json) = 'array'
                ),
                reversal_conditions_json TEXT NOT NULL CHECK (
                    json_valid(reversal_conditions_json)
                    AND json_type(reversal_conditions_json) = 'array'
                ),
                provenance_json TEXT NOT NULL CHECK (
                    json_valid(provenance_json)
                    AND json_type(provenance_json) = 'object'
                ),
                provenance_sha256 TEXT NOT NULL CHECK (
                    length(provenance_sha256) = 64
                    AND provenance_sha256 NOT GLOB '*[^0-9a-f]*'
                ),
                created_by TEXT NOT NULL CHECK (
                    created_by = trim(created_by)
                    AND length(created_by) BETWEEN 1 AND 200
                ),
                created_at TEXT NOT NULL,
                stale_at TEXT,
                stale_reason_json TEXT CHECK (
                    stale_reason_json IS NULL OR (
                        json_valid(stale_reason_json)
                        AND json_type(stale_reason_json) = 'object'
                    )
                ),
                superseded_at TEXT,
                UNIQUE(brief_id, revision),
                UNIQUE(brief_revision_id, case_id),
                UNIQUE(
                    case_id, expected_case_revision,
                    comparison_bundle_sha256
                ),
                FOREIGN KEY(source_confirmation_id, case_id)
                    REFERENCES decision_scenario_confirmations(
                        confirmation_id, case_id
                    ) ON DELETE RESTRICT,
                FOREIGN KEY(comparison_bundle_id, case_id)
                    REFERENCES decision_comparison_bundles(
                        comparison_bundle_id, case_id
                    ) ON DELETE RESTRICT,
                CHECK (
                    (revision = 1 AND parent_revision_id IS NULL)
                    OR (revision > 1 AND parent_revision_id IS NOT NULL)
                ),
                CHECK (
                    (
                        recommendation_classification =
                            'classification_pending_contract'
                        AND confidence_state = 'classification_pending_contract'
                    ) OR (
                        recommendation_classification <>
                            'classification_pending_contract'
                        AND confidence_state IN ('strong','mixed','provisional')
                    )
                ),
                CHECK (
                    recommendation_classification =
                        'classification_pending_contract'
                    AND confidence_state = 'classification_pending_contract'
                ),
                CHECK (
                    (stale_at IS NULL AND stale_reason_json IS NULL)
                    OR (stale_at IS NOT NULL AND stale_reason_json IS NOT NULL)
                ),
                CHECK (
                    superseded_at IS NULL
                    OR superseded_by_revision_id IS NOT NULL
                )
            );

            CREATE TABLE IF NOT EXISTS decision_brief_idempotency (
                case_id TEXT NOT NULL,
                idempotency_key TEXT NOT NULL CHECK (
                    idempotency_key = trim(idempotency_key)
                    AND length(idempotency_key) BETWEEN 1 AND 200
                ),
                creation_request_sha256 TEXT NOT NULL CHECK (
                    length(creation_request_sha256) = 64
                    AND creation_request_sha256 NOT GLOB '*[^0-9a-f]*'
                ),
                brief_revision_id TEXT NOT NULL
                    REFERENCES decision_briefs(brief_revision_id)
                    ON DELETE RESTRICT,
                response_json TEXT NOT NULL CHECK (json_valid(response_json)),
                response_sha256 TEXT NOT NULL CHECK (
                    length(response_sha256) = 64
                    AND response_sha256 NOT GLOB '*[^0-9a-f]*'
                ),
                created_at TEXT NOT NULL,
                PRIMARY KEY(case_id, idempotency_key),
                FOREIGN KEY(brief_revision_id, case_id)
                    REFERENCES decision_briefs(brief_revision_id, case_id)
                    ON DELETE RESTRICT
            );

            CREATE INDEX IF NOT EXISTS decision_comparison_bundles_case_idx
                ON decision_comparison_bundles(
                    case_id, created_at DESC, comparison_bundle_id DESC
                );
            CREATE UNIQUE INDEX IF NOT EXISTS decision_comparison_bundle_live_idx
                ON decision_comparison_bundles(case_id)
                WHERE superseded_by_bundle_id IS NULL;
            CREATE INDEX IF NOT EXISTS decision_comparison_attempts_scenario_idx
                ON decision_comparison_bundle_attempts(
                    scenario_revision_id, attempt_number
                );
            CREATE INDEX IF NOT EXISTS decision_briefs_case_revision_idx
                ON decision_briefs(case_id, revision DESC);
            CREATE UNIQUE INDEX IF NOT EXISTS decision_brief_live_idx
                ON decision_briefs(case_id)
                WHERE superseded_by_revision_id IS NULL;

            CREATE TRIGGER IF NOT EXISTS decision_comparison_bundle_insert_guard
            BEFORE INSERT ON decision_comparison_bundles
            WHEN NOT EXISTS (
                SELECT 1 FROM decision_scenario_confirmations c
                 WHERE c.confirmation_id = NEW.source_confirmation_id
                   AND c.case_id = NEW.case_id
            )
            BEGIN
                SELECT RAISE(ABORT, 'comparison bundle confirmation does not match its case');
            END;

            CREATE TRIGGER IF NOT EXISTS decision_comparison_bundle_identity_is_immutable
            BEFORE UPDATE OF
                comparison_bundle_id, case_id, source_confirmation_id,
                expected_case_revision, bundle_schema_version, bundle_json,
                bundle_sha256, is_complete, recommendation_eligible,
                created_by, created_at
            ON decision_comparison_bundles
            BEGIN
                SELECT RAISE(ABORT, 'decision comparison bundle payload is immutable');
            END;

            CREATE TRIGGER IF NOT EXISTS decision_comparison_bundle_stale_is_one_way
            BEFORE UPDATE OF stale_at, stale_reason_json
            ON decision_comparison_bundles
            WHEN NOT (
                (OLD.stale_at IS NULL AND OLD.stale_reason_json IS NULL
                    AND NEW.stale_at IS NOT NULL
                    AND NEW.stale_reason_json IS NOT NULL)
                OR (NEW.stale_at IS OLD.stale_at
                    AND NEW.stale_reason_json IS OLD.stale_reason_json)
            )
            BEGIN
                SELECT RAISE(ABORT, 'comparison bundle staleness is immutable');
            END;

            CREATE TRIGGER IF NOT EXISTS decision_comparison_bundle_supersession_is_one_way
            BEFORE UPDATE OF superseded_by_bundle_id, superseded_at
            ON decision_comparison_bundles
            WHEN NOT (
                (OLD.superseded_by_bundle_id IS NULL AND OLD.superseded_at IS NULL
                    AND NEW.superseded_by_bundle_id IS NOT NULL
                    AND NEW.superseded_at IS NOT NULL)
                OR (
                    OLD.superseded_by_bundle_id GLOB 'dcmp_pending_*'
                    AND NEW.superseded_by_bundle_id IS NULL
                    AND OLD.superseded_at IS NULL
                    AND NEW.superseded_at IS NULL
                    AND EXISTS (
                        SELECT 1 FROM decision_comparison_bundles p
                         WHERE p.superseded_by_bundle_id =
                            OLD.comparison_bundle_id
                           AND p.case_id = OLD.case_id
                    )
                )
                OR (NEW.superseded_by_bundle_id IS OLD.superseded_by_bundle_id
                    AND NEW.superseded_at IS OLD.superseded_at)
            )
            BEGIN
                SELECT RAISE(ABORT, 'comparison bundle supersession is immutable');
            END;

            CREATE TRIGGER IF NOT EXISTS decision_comparison_bundle_supersession_target_guard
            BEFORE UPDATE OF superseded_by_bundle_id
            ON decision_comparison_bundles
            WHEN OLD.superseded_by_bundle_id IS NULL
                 AND NEW.superseded_by_bundle_id IS NOT NULL
                 AND NOT EXISTS (
                    SELECT 1 FROM decision_comparison_bundles n
                     WHERE n.comparison_bundle_id = NEW.superseded_by_bundle_id
                       AND n.case_id = OLD.case_id
                       AND n.comparison_bundle_id <> OLD.comparison_bundle_id
                 )
            BEGIN
                SELECT RAISE(ABORT, 'comparison bundle supersession target is invalid');
            END;

            CREATE TRIGGER IF NOT EXISTS decision_comparison_bundle_delete_guard
            BEFORE DELETE ON decision_comparison_bundles
            BEGIN
                SELECT RAISE(ABORT, 'decision comparison bundles are retained');
            END;

            CREATE TRIGGER IF NOT EXISTS decision_comparison_attempt_insert_guard
            BEFORE INSERT ON decision_comparison_bundle_attempts
            WHEN NOT EXISTS (
                SELECT 1
                  FROM decision_comparison_bundles b
                  JOIN decision_scenario_confirmation_items i
                    ON i.confirmation_id = b.source_confirmation_id
                   AND i.case_id = b.case_id
                  JOIN decision_scenarios s
                    ON s.scenario_revision_id = i.scenario_revision_id
                   AND s.case_id = i.case_id
                  JOIN decision_scenario_jobs l
                    ON l.scenario_revision_id = s.scenario_revision_id
                   AND l.case_id = s.case_id
                  JOIN technoeconomic_jobs j ON j.tea_job_id = l.tea_job_id
                 WHERE b.comparison_bundle_id = NEW.comparison_bundle_id
                   AND b.case_id = NEW.case_id
                   AND i.item_index = NEW.item_index
                   AND i.scenario_revision_id = NEW.scenario_revision_id
                   AND i.scenario_id = NEW.scenario_id
                   AND i.scenario_revision = NEW.scenario_revision
                   AND l.attempt_number = NEW.attempt_number
                   AND l.tea_job_id = NEW.tea_job_id
                   AND l.retry_of_job_id IS NEW.retry_of_job_id
                   AND j.state = NEW.state
                   AND s.request_sha256 = NEW.request_sha256
                   AND j.request_json = s.request_json
                   AND j.source_annual_job_id = s.source_annual_job_id
                   AND j.source_snapshot_sha256 = NEW.source_snapshot_sha256
                   AND j.source_snapshot_sha256 = s.source_snapshot_sha256
                   AND NEW.selected_for_comparison = CASE WHEN EXISTS (
                        SELECT 1 FROM decision_scenario_jobs newer
                         WHERE newer.scenario_revision_id = l.scenario_revision_id
                           AND newer.attempt_number > l.attempt_number
                   ) THEN 0 ELSE 1 END
                   AND EXISTS (
                        SELECT 1
                          FROM json_each(b.bundle_json, '$.attempt_proofs') p
                         WHERE json_type(p.value) = 'object'
                           AND json_extract(p.value, '$.item_index') =
                                NEW.item_index
                           AND json_extract(
                                p.value, '$.scenario_revision_id'
                           ) = NEW.scenario_revision_id
                           AND json_extract(p.value, '$.scenario_id') =
                                NEW.scenario_id
                           AND json_extract(p.value, '$.scenario_revision') =
                                NEW.scenario_revision
                           AND json_extract(p.value, '$.attempt_number') =
                                NEW.attempt_number
                           AND json_extract(p.value, '$.tea_job_id') =
                                NEW.tea_job_id
                           AND json_extract(p.value, '$.retry_of_job_id') IS
                                NEW.retry_of_job_id
                           AND json_type(
                                p.value, '$.selected_for_comparison'
                           ) IN ('true','false')
                           AND json_extract(
                                p.value, '$.selected_for_comparison'
                           ) = NEW.selected_for_comparison
                           AND json_extract(p.value, '$.state') = NEW.state
                           AND json_extract(
                                p.value, '$.verification_status'
                           ) = NEW.verification_status
                           AND json_extract(p.value, '$.request_sha256') =
                                NEW.request_sha256
                           AND json_extract(
                                p.value, '$.source_snapshot_sha256'
                           ) = NEW.source_snapshot_sha256
                           AND json_extract(p.value, '$.result_sha256') IS
                                NEW.result_sha256
                           AND json_extract(
                                p.value, '$.result_provenance_sha256'
                           ) IS NEW.result_provenance_sha256
                           AND json_extract(
                                p.value, '$.evidence_set_sha256'
                           ) = NEW.evidence_set_sha256
                           AND json_extract(
                                p.value, '$.reporting_tieout_sha256'
                           ) IS NEW.reporting_tieout_sha256
                   )
            )
            BEGIN
                SELECT RAISE(ABORT, 'comparison attempt does not match immutable execution history');
            END;

            CREATE TRIGGER IF NOT EXISTS decision_comparison_attempt_update_guard
            BEFORE UPDATE ON decision_comparison_bundle_attempts
            BEGIN
                SELECT RAISE(ABORT, 'decision comparison attempt proofs are immutable');
            END;

            CREATE TRIGGER IF NOT EXISTS decision_comparison_attempt_delete_guard
            BEFORE DELETE ON decision_comparison_bundle_attempts
            BEGIN
                SELECT RAISE(ABORT, 'decision comparison attempt proofs are immutable');
            END;

            CREATE TRIGGER IF NOT EXISTS decision_brief_insert_guard
            BEFORE INSERT ON decision_briefs
            WHEN (NEW.revision = 1 AND NEW.superseded_by_revision_id IS NOT NULL)
                 OR (NEW.revision > 1 AND NOT (
                    NEW.superseded_by_revision_id GLOB 'dbr_pending_*'
                 ))
            BEGIN
                SELECT RAISE(ABORT, 'decision brief revision insertion is invalid');
            END;

            CREATE TRIGGER IF NOT EXISTS decision_brief_bundle_snapshot_guard
            BEFORE INSERT ON decision_briefs
            WHEN NOT EXISTS (
                SELECT 1 FROM decision_comparison_bundles b
                 WHERE b.comparison_bundle_id = NEW.comparison_bundle_id
                   AND b.case_id = NEW.case_id
                   AND b.source_confirmation_id = NEW.source_confirmation_id
                   AND b.expected_case_revision + 1 =
                        NEW.expected_case_revision
                   AND b.bundle_json = NEW.comparison_bundle_json
                   AND b.bundle_sha256 = NEW.comparison_bundle_sha256
                   AND b.is_complete = 1
                   AND json_array_length(
                        b.bundle_json, '$.attempt_proofs'
                   ) = (
                        SELECT COUNT(*)
                          FROM decision_comparison_bundle_attempts a
                         WHERE a.comparison_bundle_id =
                            b.comparison_bundle_id
                   )
                   AND (
                        NEW.recommendation_classification =
                            'classification_pending_contract'
                        OR b.recommendation_eligible = 1
                   )
            )
            BEGIN
                SELECT RAISE(ABORT, 'decision brief does not match its immutable comparison bundle');
            END;

            CREATE TRIGGER IF NOT EXISTS decision_brief_lineage_guard
            BEFORE INSERT ON decision_briefs
            WHEN NEW.revision > 1 AND NOT EXISTS (
                SELECT 1 FROM decision_briefs p
                 WHERE p.brief_revision_id = NEW.parent_revision_id
                   AND p.brief_id = NEW.brief_id
                   AND p.case_id = NEW.case_id
                   AND p.revision = NEW.revision - 1
                   AND p.superseded_by_revision_id IS NULL
            )
            BEGIN
                SELECT RAISE(ABORT, 'decision brief revision lineage is invalid');
            END;

            CREATE TRIGGER IF NOT EXISTS decision_brief_identity_is_immutable
            BEFORE UPDATE OF
                brief_revision_id, brief_id, case_id, revision,
                parent_revision_id, source_confirmation_id,
                comparison_bundle_id, expected_case_revision,
                case_revision_after, comparison_bundle_json,
                comparison_bundle_sha256, recommendation_classification,
                confidence_state, caveats_json, reversal_conditions_json,
                provenance_json, provenance_sha256, created_by, created_at
            ON decision_briefs
            BEGIN
                SELECT RAISE(ABORT, 'decision brief revision payload is immutable');
            END;

            CREATE TRIGGER IF NOT EXISTS decision_brief_stale_is_one_way
            BEFORE UPDATE OF stale_at, stale_reason_json
            ON decision_briefs
            WHEN NOT (
                (OLD.stale_at IS NULL AND OLD.stale_reason_json IS NULL
                    AND NEW.stale_at IS NOT NULL
                    AND NEW.stale_reason_json IS NOT NULL)
                OR (NEW.stale_at IS OLD.stale_at
                    AND NEW.stale_reason_json IS OLD.stale_reason_json)
            )
            BEGIN
                SELECT RAISE(ABORT, 'decision brief staleness is immutable');
            END;

            CREATE TRIGGER IF NOT EXISTS decision_brief_supersession_is_one_way
            BEFORE UPDATE OF superseded_by_revision_id, superseded_at
            ON decision_briefs
            WHEN NOT (
                (OLD.superseded_by_revision_id IS NULL AND OLD.superseded_at IS NULL
                    AND NEW.superseded_by_revision_id IS NOT NULL
                    AND NEW.superseded_at IS NOT NULL)
                OR (
                    OLD.superseded_by_revision_id GLOB 'dbr_pending_*'
                    AND NEW.superseded_by_revision_id IS NULL
                    AND OLD.superseded_at IS NULL
                    AND NEW.superseded_at IS NULL
                    AND OLD.revision > 1
                    AND EXISTS (
                        SELECT 1 FROM decision_briefs p
                         WHERE p.brief_revision_id = OLD.parent_revision_id
                           AND p.brief_id = OLD.brief_id
                           AND p.case_id = OLD.case_id
                           AND p.superseded_by_revision_id = OLD.brief_revision_id
                    )
                )
                OR (
                    NEW.superseded_by_revision_id IS OLD.superseded_by_revision_id
                    AND NEW.superseded_at IS OLD.superseded_at
                )
            )
            BEGIN
                SELECT RAISE(ABORT, 'decision brief supersession is immutable');
            END;

            CREATE TRIGGER IF NOT EXISTS decision_brief_supersession_target_guard
            BEFORE UPDATE OF superseded_by_revision_id ON decision_briefs
            WHEN OLD.superseded_by_revision_id IS NULL
                 AND NEW.superseded_by_revision_id IS NOT NULL
                 AND NOT EXISTS (
                    SELECT 1 FROM decision_briefs n
                     WHERE n.brief_revision_id = NEW.superseded_by_revision_id
                       AND n.brief_id = OLD.brief_id
                       AND n.case_id = OLD.case_id
                       AND n.parent_revision_id = OLD.brief_revision_id
                       AND n.revision = OLD.revision + 1
                 )
            BEGIN
                SELECT RAISE(ABORT, 'decision brief supersession target is invalid');
            END;

            CREATE TRIGGER IF NOT EXISTS decision_brief_delete_guard
            BEFORE DELETE ON decision_briefs
            BEGIN
                SELECT RAISE(ABORT, 'decision brief revisions are retained');
            END;

            CREATE TRIGGER IF NOT EXISTS decision_brief_idempotency_insert_guard
            BEFORE INSERT ON decision_brief_idempotency
            WHEN NOT EXISTS (
                SELECT 1 FROM decision_briefs b
                 WHERE b.brief_revision_id = NEW.brief_revision_id
                   AND b.case_id = NEW.case_id
            )
            BEGIN
                SELECT RAISE(ABORT, 'brief idempotency receipt does not match its revision');
            END;

            CREATE TRIGGER IF NOT EXISTS decision_brief_idempotency_update_guard
            BEFORE UPDATE ON decision_brief_idempotency
            BEGIN
                SELECT RAISE(ABORT, 'decision brief idempotency receipts are immutable');
            END;

            CREATE TRIGGER IF NOT EXISTS decision_brief_idempotency_delete_guard
            BEFORE DELETE ON decision_brief_idempotency
            BEGIN
                SELECT RAISE(ABORT, 'decision brief idempotency receipts are immutable');
            END;
            """
        )
        connection.execute(
            "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (?, ?)",
            (8, applied_at),
        )
        connection.execute("PRAGMA user_version = 8")
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
        # Older rows may predate interrupted jobs receiving ``completed_at``.
        # Treat the interruption timestamp as their terminal timestamp so
        # elapsed-duration consumers do not keep counting after the job stops.
        if result["state"] == "interrupted" and not result.get("completed_at"):
            result["completed_at"] = result.get("interrupted_at")
        return result

    @staticmethod
    def _technoeconomic_job_from_row(
        row: sqlite3.Row | None,
    ) -> dict[str, Any] | None:
        if row is None:
            return None
        result = dict(row)
        result["id"] = result.pop("tea_job_id")
        for field in (
            "request",
            "source_snapshot",
            "submission_provenance",
            "result",
            "result_provenance",
            "artifacts",
        ):
            result[field] = _json_load(result.pop(f"{field}_json"))
        result["cancel_requested"] = bool(result["cancel_requested"])
        if result["state"] == "interrupted" and not result.get("completed_at"):
            result["completed_at"] = result.get("interrupted_at")
        return result

    @staticmethod
    def _decision_case_from_row(
        row: sqlite3.Row | None,
    ) -> dict[str, Any] | None:
        if row is None:
            return None
        result = dict(row)
        result["id"] = result.pop("case_id")
        return result

    @staticmethod
    def _decision_turn_from_row(
        row: sqlite3.Row | None,
    ) -> dict[str, Any] | None:
        if row is None:
            return None
        result = dict(row)
        result["id"] = result.pop("turn_id")
        return result

    @staticmethod
    def _decision_message_from_row(
        row: sqlite3.Row | None,
    ) -> dict[str, Any] | None:
        if row is None:
            return None
        result = dict(row)
        result["id"] = result.pop("message_id")
        for field in ("structured_output", "citations", "tool_outcomes"):
            result[field] = _json_load(result.pop(f"{field}_json"))
        return result

    @staticmethod
    def _decision_evidence_asset_from_row(
        row: sqlite3.Row | None,
    ) -> dict[str, Any] | None:
        if row is None:
            return None
        result = dict(row)
        result["id"] = result.pop("evidence_asset_id")
        result["extraction_metadata"] = _json_load(
            result.pop("extraction_metadata_json")
        )
        result["source_metadata"] = _json_load(result.pop("source_metadata_json"))
        return result

    @staticmethod
    def _decision_evidence_candidate_from_row(
        row: sqlite3.Row | None,
    ) -> dict[str, Any] | None:
        if row is None:
            return None
        result = dict(row)
        result["id"] = result.pop("evidence_candidate_id")
        result["value"] = _json_load(result.pop("value_json"))
        result["source_location"] = _json_load(result.pop("source_location_json"))
        return result

    @staticmethod
    def _decision_evidence_receipt_from_row(
        row: sqlite3.Row | None,
    ) -> dict[str, Any] | None:
        if row is None:
            return None
        result = dict(row)
        result["id"] = result.pop("evidence_receipt_id")
        result["value"] = _json_load(result.pop("value_json"))
        result["source_location"] = _json_load(result.pop("source_location_json"))
        result["receipt"] = _json_load(result.pop("receipt_json"))
        return result

    @staticmethod
    def _decision_event_from_row(
        row: sqlite3.Row | None,
    ) -> dict[str, Any] | None:
        if row is None:
            return None
        result = dict(row)
        result["id"] = result.pop("event_id")
        result["payload"] = _json_load(result.pop("payload_json"))
        return result

    @staticmethod
    def _decision_scenario_from_row(
        row: sqlite3.Row | None,
    ) -> dict[str, Any] | None:
        if row is None:
            return None
        result = dict(row)
        # ``scenario_id`` is the stable public identity.  A revision row has its
        # own explicit identity so callers never have to infer it from a counter.
        result["id"] = str(result["scenario_id"])
        result["request"] = _json_load(result.pop("request_json"))
        result["changed_fields"] = _json_load(result.pop("changed_fields_json"))
        result["validation"] = _json_load(result.pop("validation_json"))
        result["is_current"] = result["superseded_by_revision_id"] is None
        return result

    @staticmethod
    def _decision_scenario_confirmation_from_row(
        row: sqlite3.Row | None,
    ) -> dict[str, Any] | None:
        if row is None:
            return None
        result = dict(row)
        result["id"] = result.pop("confirmation_id")
        result["confirmation_request"] = _json_load(
            result.pop("confirmation_request_json")
        )
        result["receipt"] = _json_load(result.pop("receipt_json"))
        return result

    @staticmethod
    def _decision_comparison_bundle_from_row(
        row: sqlite3.Row | None,
    ) -> dict[str, Any] | None:
        if row is None:
            return None
        result = dict(row)
        result["id"] = str(result["comparison_bundle_id"])
        bundle_json = str(result.pop("bundle_json"))
        result["bundle"] = _verified_decision_bundle_json(
            bundle_json, str(result["bundle_sha256"])
        )
        result["stale_reason"] = _json_load(result.pop("stale_reason_json"))
        result["is_complete"] = bool(result["is_complete"])
        result["recommendation_eligible"] = bool(
            result["recommendation_eligible"]
        )
        result["case_revision_after"] = int(
            result["expected_case_revision"]
        ) + 1
        result["is_current"] = (
            result["stale_at"] is None
            and result["superseded_by_bundle_id"] is None
        )
        return result

    @staticmethod
    def _decision_comparison_attempt_from_row(
        row: sqlite3.Row,
    ) -> dict[str, Any]:
        result = dict(row)
        result.pop("created_at", None)
        result.pop("case_id", None)
        result.pop("comparison_bundle_id", None)
        result["item_index"] = int(result["item_index"])
        result["scenario_revision"] = int(result["scenario_revision"])
        result["attempt_number"] = int(result["attempt_number"])
        result["selected_for_comparison"] = bool(
            result["selected_for_comparison"]
        )
        return result

    @staticmethod
    def _decision_brief_from_row(
        row: sqlite3.Row | None,
    ) -> dict[str, Any] | None:
        if row is None:
            return None
        result = dict(row)
        result["id"] = str(result["brief_revision_id"])
        comparison_bundle_json = str(result.pop("comparison_bundle_json"))
        result["comparison_bundle"] = _verified_decision_bundle_json(
            comparison_bundle_json,
            str(result["comparison_bundle_sha256"]),
        )
        result["caveats"] = _json_load(result.pop("caveats_json"))
        result["reversal_conditions"] = _json_load(
            result.pop("reversal_conditions_json")
        )
        provenance_json = str(result.pop("provenance_json"))
        if not secrets.compare_digest(
            str(result["provenance_sha256"]), _sha256_text(provenance_json)
        ):
            raise StoreConflict("stored decision brief provenance digest is invalid")
        result["provenance"] = _json_load(provenance_json)
        result["stale_reason"] = _json_load(result.pop("stale_reason_json"))
        result["is_current"] = (
            result["stale_at"] is None
            and result["superseded_by_revision_id"] is None
        )
        return result

    @staticmethod
    def _normalize_decision_scenario_evidence_refs(
        evidence_receipt_refs: Sequence[str | Mapping[str, Any]],
    ) -> list[dict[str, str]]:
        normalized: dict[str, str] = {}
        for index, raw in enumerate(evidence_receipt_refs):
            if isinstance(raw, str):
                receipt_id = raw.strip()
                request_path = f"/evidence/{index}"
            elif isinstance(raw, Mapping):
                receipt_id = str(
                    raw.get("evidence_receipt_id") or raw.get("receipt_id") or ""
                ).strip()
                request_path = str(raw.get("request_path") or "").strip()
            else:
                raise ValueError("evidence receipt references must be strings or objects")
            if not receipt_id.startswith("evr_") or len(receipt_id) <= 4:
                raise ValueError("evidence receipt ids must use the 'evr_' prefix")
            if (
                not request_path.startswith("/")
                or len(request_path) > 500
                or request_path != request_path.strip()
            ):
                raise ValueError("evidence request_path must be a JSON pointer")
            if request_path in normalized:
                raise ValueError(f"duplicate evidence request_path: {request_path}")
            normalized[request_path] = receipt_id
        return [
            {"request_path": path, "evidence_receipt_id": normalized[path]}
            for path in sorted(normalized)
        ]

    @staticmethod
    def _normalize_decision_scenario_changed_fields(
        changed_fields: Sequence[str],
    ) -> list[str]:
        if isinstance(changed_fields, (str, bytes)):
            raise ValueError("changed_fields must be an array of request paths")
        normalized: set[str] = set()
        for raw in changed_fields:
            path = str(raw).strip()
            if not path.startswith("/") or len(path) > 500:
                raise ValueError("changed_fields entries must be JSON pointers")
            normalized.add(path)
        return sorted(normalized)

    @staticmethod
    def _require_decision_scenario_row(
        connection: sqlite3.Connection,
        scenario_revision_id: str,
        *,
        current: bool = False,
    ) -> sqlite3.Row:
        row = connection.execute(
            "SELECT * FROM decision_scenarios WHERE scenario_revision_id = ?",
            (str(scenario_revision_id),),
        ).fetchone()
        if row is None:
            raise RecordNotFound(
                f"unknown decision scenario revision: {scenario_revision_id}"
            )
        if current and row["superseded_by_revision_id"] is not None:
            raise StoreConflict("decision scenario revision was superseded")
        return row

    @staticmethod
    def _require_decision_scenario_revision(
        row: sqlite3.Row,
        expected_revision: int,
    ) -> None:
        if isinstance(expected_revision, bool) or not isinstance(expected_revision, int):
            raise ValueError("expected_revision must be an integer")
        if int(row["revision"]) != expected_revision:
            raise StoreConflict(
                "decision scenario revision changed "
                f"(expected {expected_revision}, found {row['revision']})"
            )

    @staticmethod
    def _verify_decision_scenario_evidence_refs(
        connection: sqlite3.Connection,
        case_id: str,
        evidence_refs: Sequence[Mapping[str, str]],
    ) -> list[sqlite3.Row]:
        verified: list[sqlite3.Row] = []
        for reference in evidence_refs:
            receipt_id = str(reference["evidence_receipt_id"])
            row = connection.execute(
                """
                SELECT r.*, a.sha256 AS current_asset_sha256,
                       a.byte_count AS current_asset_byte_count,
                       a.detected_media_type AS current_asset_media_type,
                       a.removed_at AS current_asset_removed_at
                  FROM decision_evidence_receipts r
                  JOIN decision_evidence_assets a
                    ON a.evidence_asset_id = r.evidence_asset_id
                   AND a.case_id = r.case_id
                 WHERE r.evidence_receipt_id = ?
                """,
                (receipt_id,),
            ).fetchone()
            if row is None:
                raise RecordNotFound(f"unknown decision evidence receipt: {receipt_id}")
            if row["case_id"] != case_id:
                raise StoreConflict("scenario evidence belongs to a different case")
            if row["decision"] != "accepted":
                raise InvalidStateTransition(
                    f"scenario evidence receipt is not accepted: {receipt_id}"
                )
            if row["current_asset_removed_at"] is not None:
                raise StoreConflict("accepted scenario evidence content was removed")
            receipt_json = str(row["receipt_json"])
            if not secrets.compare_digest(
                str(row["receipt_sha256"]), _sha256_text(receipt_json)
            ):
                raise StoreConflict("scenario evidence receipt digest is invalid")
            receipt_payload = _json_load(receipt_json)
            content = (
                receipt_payload.get("content")
                if isinstance(receipt_payload, Mapping)
                else None
            )
            if not isinstance(content, Mapping) or any(
                (
                    receipt_payload.get("evidence_receipt_id") != receipt_id,
                    receipt_payload.get("case_id") != case_id,
                    content.get("sha256") != row["asset_sha256"],
                    content.get("byte_count") != row["asset_byte_count"],
                    content.get("media_type") != row["current_asset_media_type"],
                    row["asset_sha256"] != row["current_asset_sha256"],
                    row["asset_byte_count"] != row["current_asset_byte_count"],
                )
            ):
                raise StoreConflict(
                    "scenario evidence receipt does not match server-managed content"
                )
            verified.append(row)
        return verified

    def _decision_scenario_bundle(
        self,
        connection: sqlite3.Connection,
        row: sqlite3.Row,
    ) -> dict[str, Any]:
        result = self._decision_scenario_from_row(row)
        assert result is not None
        evidence_rows = connection.execute(
            """
            SELECT e.request_path AS linked_request_path, r.*
              FROM decision_scenario_evidence e
              JOIN decision_evidence_receipts r
                ON r.evidence_receipt_id = e.evidence_receipt_id
             WHERE e.scenario_revision_id = ?
             ORDER BY e.request_path ASC
            """,
            (row["scenario_revision_id"],),
        ).fetchall()
        evidence_refs: list[dict[str, Any]] = []
        for evidence_row in evidence_rows:
            receipt = self._decision_evidence_receipt_from_row(evidence_row)
            assert receipt is not None
            evidence_refs.append(
                {
                    "request_path": str(evidence_row["linked_request_path"]),
                    "evidence_receipt_id": str(evidence_row["evidence_receipt_id"]),
                    "receipt": receipt,
                }
            )
        result["evidence_receipt_refs"] = evidence_refs
        result["evidence_receipt_ids"] = [
            reference["evidence_receipt_id"] for reference in evidence_refs
        ]

        job_rows = connection.execute(
            """
            SELECT j.*, l.attempt_number, l.confirmation_id AS scenario_confirmation_id
              FROM decision_scenario_jobs l
              JOIN technoeconomic_jobs j ON j.tea_job_id = l.tea_job_id
             WHERE l.scenario_revision_id = ?
             ORDER BY l.attempt_number ASC
            """,
            (row["scenario_revision_id"],),
        ).fetchall()
        jobs: list[dict[str, Any]] = []
        for job_row in job_rows:
            job = self._technoeconomic_job_from_row(job_row)
            assert job is not None
            job["attempt_number"] = int(job_row["attempt_number"])
            job["scenario_confirmation_id"] = job_row["scenario_confirmation_id"]
            jobs.append(job)
        result["jobs"] = jobs
        result["tea_job_ids"] = [job["id"] for job in jobs]
        result["linked_tea_job_id"] = jobs[-1]["id"] if jobs else None
        result["latest_job"] = jobs[-1] if jobs else None
        return result

    def _decision_scenario_confirmation_bundle(
        self,
        connection: sqlite3.Connection,
        row: sqlite3.Row,
    ) -> dict[str, Any]:
        result = self._decision_scenario_confirmation_from_row(row)
        assert result is not None
        item_rows = connection.execute(
            """
            SELECT i.*, j.*
              FROM decision_scenario_confirmation_items i
              JOIN technoeconomic_jobs j ON j.tea_job_id = i.tea_job_id
             WHERE i.confirmation_id = ?
             ORDER BY i.item_index ASC
            """,
            (row["confirmation_id"],),
        ).fetchall()
        items: list[dict[str, Any]] = []
        for item_row in item_rows:
            job = self._technoeconomic_job_from_row(item_row)
            assert job is not None
            items.append(
                {
                    "item_index": int(item_row["item_index"]),
                    "scenario_id": str(item_row["scenario_id"]),
                    "scenario_revision_id": str(item_row["scenario_revision_id"]),
                    "scenario_revision": int(item_row["scenario_revision"]),
                    "request_sha256": str(item_row["request_sha256"]),
                    "tea_job_id": str(item_row["tea_job_id"]),
                    "job": job,
                }
            )
        result["items"] = items
        result["jobs"] = [item["job"] for item in items]
        return result

    def _decision_comparison_bundle_record(
        self,
        connection: sqlite3.Connection,
        row: sqlite3.Row,
    ) -> dict[str, Any]:
        result = self._decision_comparison_bundle_from_row(row)
        assert result is not None
        attempt_rows = connection.execute(
            """
            SELECT * FROM decision_comparison_bundle_attempts
             WHERE comparison_bundle_id = ?
             ORDER BY item_index ASC, attempt_number ASC
            """,
            (row["comparison_bundle_id"],),
        ).fetchall()
        result["attempt_proofs"] = [
            self._decision_comparison_attempt_from_row(attempt_row)
            for attempt_row in attempt_rows
        ]
        embedded_attempts = result["bundle"].get("attempt_proofs")
        if not isinstance(embedded_attempts, list) or not secrets.compare_digest(
            _json_dump(embedded_attempts), _json_dump(result["attempt_proofs"])
        ):
            raise StoreConflict("stored comparison attempt proofs are invalid")
        return result

    def _decision_brief_record(
        self,
        connection: sqlite3.Connection,
        row: sqlite3.Row,
    ) -> dict[str, Any]:
        result = self._decision_brief_from_row(row)
        assert result is not None
        source = connection.execute(
            """
            SELECT *
              FROM decision_comparison_bundles
             WHERE comparison_bundle_id = ? AND case_id = ?
            """,
            (row["comparison_bundle_id"], row["case_id"]),
        ).fetchone()
        if source is None:
            raise StoreConflict(
                "stored decision brief comparison snapshot is invalid"
            )
        verified_source = self._decision_comparison_bundle_record(
            connection, source
        )
        if any(
            (
                str(verified_source["bundle_sha256"])
                != str(row["comparison_bundle_sha256"]),
                str(source["bundle_json"])
                != str(row["comparison_bundle_json"]),
            )
        ):
            raise StoreConflict(
                "stored decision brief comparison snapshot is invalid"
            )
        return result

    @staticmethod
    def _normalize_decision_event_actor(
        actor_kind: str,
        operator_name: str | None,
    ) -> tuple[str, str | None]:
        actor = str(actor_kind).strip()
        if actor not in {"operator", "decision_agent", "system"}:
            raise ValueError("actor_kind must be operator, decision_agent, or system")
        if actor == "operator":
            return actor, _bounded_text(
                operator_name, field="operator_name", maximum=200
            )
        if operator_name is not None:
            raise ValueError("operator_name is only valid for operator events")
        return actor, None

    @staticmethod
    def _validate_decision_record_id(
        value: str | None,
        *,
        prefix: str,
        field: str,
    ) -> str:
        normalized = str(value or _new_id(prefix)).strip()
        expected = f"{prefix}_"
        if not normalized.startswith(expected) or len(normalized) <= len(expected):
            raise ValueError(f"{field} must use the {expected!r} prefix")
        return normalized

    def _verified_decision_comparison_attempts(
        self,
        connection: sqlite3.Connection,
        *,
        case_id: str,
        source_confirmation_id: str,
        attempt_proofs: Sequence[Mapping[str, Any]],
    ) -> list[dict[str, Any]]:
        """Rebuild and prove the exact confirmation-bound attempt history."""

        confirmation = connection.execute(
            """
            SELECT * FROM decision_scenario_confirmations
             WHERE confirmation_id = ? AND case_id = ?
            """,
            (source_confirmation_id, case_id),
        ).fetchone()
        if confirmation is None:
            raise RecordNotFound(
                f"unknown decision scenario confirmation: {source_confirmation_id}"
            )
        for payload_field, digest_field in (
            ("confirmation_request_json", "confirmation_request_sha256"),
            ("receipt_json", "receipt_sha256"),
        ):
            payload_json = str(confirmation[payload_field])
            if not secrets.compare_digest(
                str(confirmation[digest_field]), _sha256_text(payload_json)
            ):
                raise StoreConflict("scenario confirmation digest is invalid")
        receipt = _json_load(str(confirmation["receipt_json"]))
        if not isinstance(receipt, Mapping) or any(
            (
                receipt.get("confirmation_id") != source_confirmation_id,
                receipt.get("case_id") != case_id,
                receipt.get("case_revision_after")
                != int(confirmation["case_revision_after"]),
            )
        ):
            raise StoreConflict("scenario confirmation receipt identity is invalid")

        supplied_by_identity: dict[tuple[int, int], Mapping[str, Any]] = {}
        if isinstance(attempt_proofs, (str, bytes)):
            raise ValueError("attempt_proofs must be an array")
        for raw in attempt_proofs:
            if not isinstance(raw, Mapping):
                raise ValueError("attempt proof entries must be objects")
            item_index = raw.get("item_index")
            attempt_number = raw.get("attempt_number")
            if (
                isinstance(item_index, bool)
                or not isinstance(item_index, int)
                or item_index < 0
                or isinstance(attempt_number, bool)
                or not isinstance(attempt_number, int)
                or attempt_number <= 0
            ):
                raise ValueError(
                    "attempt proof item_index and attempt_number must be integers"
                )
            identity = (item_index, attempt_number)
            if identity in supplied_by_identity:
                raise ValueError("attempt_proofs contain duplicate attempt identities")
            supplied_by_identity[identity] = raw

        item_rows = connection.execute(
            """
            SELECT i.item_index, i.scenario_revision_id, i.scenario_id,
                   i.scenario_revision, i.request_sha256, i.tea_job_id,
                   s.request_json, s.source_annual_job_id,
                   s.source_snapshot_sha256
              FROM decision_scenario_confirmation_items i
              JOIN decision_scenarios s
                ON s.scenario_revision_id = i.scenario_revision_id
               AND s.case_id = i.case_id
             WHERE i.confirmation_id = ? AND i.case_id = ?
             ORDER BY i.item_index ASC
            """,
            (source_confirmation_id, case_id),
        ).fetchall()
        receipt_scenarios = receipt.get("scenarios")
        if (
            not item_rows
            or not isinstance(receipt_scenarios, list)
            or len(receipt_scenarios) != len(item_rows)
        ):
            raise StoreConflict("scenario confirmation membership is invalid")

        derived: list[dict[str, Any]] = []
        for item_row, receipt_item in zip(item_rows, receipt_scenarios, strict=True):
            if not isinstance(receipt_item, Mapping) or any(
                (
                    receipt_item.get("scenario_revision_id")
                    != item_row["scenario_revision_id"],
                    receipt_item.get("scenario_id") != item_row["scenario_id"],
                    receipt_item.get("scenario_revision")
                    != int(item_row["scenario_revision"]),
                    receipt_item.get("request_sha256")
                    != item_row["request_sha256"],
                    receipt_item.get("tea_job_id") != item_row["tea_job_id"],
                )
            ):
                raise StoreConflict("scenario confirmation item receipt is invalid")
            request_json = str(item_row["request_json"])
            if not secrets.compare_digest(
                str(item_row["request_sha256"]), _sha256_text(request_json)
            ):
                raise StoreConflict("scenario request digest is invalid")

            evidence_rows = connection.execute(
                """
                SELECT e.request_path, e.evidence_receipt_id,
                       r.receipt_sha256, r.asset_sha256
                  FROM decision_scenario_evidence e
                  JOIN decision_evidence_receipts r
                    ON r.evidence_receipt_id = e.evidence_receipt_id
                 WHERE e.scenario_revision_id = ?
                 ORDER BY e.request_path ASC
                """,
                (item_row["scenario_revision_id"],),
            ).fetchall()
            evidence_refs = [
                {
                    "request_path": str(evidence_row["request_path"]),
                    "evidence_receipt_id": str(
                        evidence_row["evidence_receipt_id"]
                    ),
                }
                for evidence_row in evidence_rows
            ]
            if receipt_item.get("evidence_receipt_refs") != evidence_refs:
                raise StoreConflict(
                    "scenario evidence links do not match confirmation receipt"
                )
            self._verify_decision_scenario_evidence_refs(
                connection, case_id, evidence_refs
            )
            evidence_identity = [
                {
                    "request_path": str(evidence_row["request_path"]),
                    "evidence_receipt_id": str(
                        evidence_row["evidence_receipt_id"]
                    ),
                    "receipt_sha256": str(evidence_row["receipt_sha256"]),
                    "content_sha256": str(evidence_row["asset_sha256"]),
                }
                for evidence_row in evidence_rows
            ]
            evidence_set_sha256 = _sha256_text(_json_dump(evidence_identity))

            job_rows = connection.execute(
                """
                SELECT l.attempt_number, l.retry_of_job_id, l.confirmation_id,
                       j.*
                  FROM decision_scenario_jobs l
                  JOIN technoeconomic_jobs j ON j.tea_job_id = l.tea_job_id
                 WHERE l.case_id = ? AND l.scenario_revision_id = ?
                 ORDER BY l.attempt_number ASC
                """,
                (case_id, item_row["scenario_revision_id"]),
            ).fetchall()
            if not job_rows:
                raise StoreConflict("confirmed scenario has no TEA attempt history")
            previous_job_id: str | None = None
            for offset, job_row in enumerate(job_rows, start=1):
                attempt_number = int(job_row["attempt_number"])
                if attempt_number != offset:
                    raise StoreConflict("scenario attempt history is not contiguous")
                if offset == 1:
                    if any(
                        (
                            job_row["retry_of_job_id"] is not None,
                            job_row["confirmation_id"] != source_confirmation_id,
                            job_row["tea_job_id"] != item_row["tea_job_id"],
                        )
                    ):
                        raise StoreConflict("initial scenario attempt linkage is invalid")
                elif any(
                    (
                        job_row["retry_of_job_id"] != previous_job_id,
                        job_row["confirmation_id"] is not None,
                    )
                ):
                    raise StoreConflict("scenario retry linkage is invalid")
                if any(
                    (
                        str(job_row["request_json"]) != request_json,
                        job_row["source_annual_job_id"]
                        != item_row["source_annual_job_id"],
                        job_row["source_snapshot_sha256"]
                        != item_row["source_snapshot_sha256"],
                        _sha256_text(str(job_row["source_snapshot_json"]))
                        != job_row["source_snapshot_sha256"],
                    )
                ):
                    raise StoreConflict("scenario attempt request or source is invalid")

                result_sha256 = (
                    None
                    if job_row["result_json"] is None
                    else _sha256_text(str(job_row["result_json"]))
                )
                result_provenance_sha256 = (
                    None
                    if job_row["result_provenance_json"] is None
                    else _sha256_text(str(job_row["result_provenance_json"]))
                )
                identity = (int(item_row["item_index"]), attempt_number)
                supplied = supplied_by_identity.pop(identity, None)
                if supplied is None:
                    raise StoreConflict("attempt_proofs omit durable attempt history")
                verification_status = str(
                    supplied.get("verification_status") or ""
                ).strip()
                if verification_status not in {
                    "verified",
                    "verification_failed",
                    "pending",
                    "not_applicable",
                }:
                    raise ValueError("unsupported attempt verification_status")
                reporting_tieout = supplied.get("reporting_tieout_sha256")
                normalized_tieout = (
                    None
                    if reporting_tieout is None
                    else self._validate_sha256(
                        str(reporting_tieout),
                        field="reporting_tieout_sha256",
                    )
                )
                proof = {
                    "item_index": int(item_row["item_index"]),
                    "scenario_revision_id": str(
                        item_row["scenario_revision_id"]
                    ),
                    "scenario_id": str(item_row["scenario_id"]),
                    "scenario_revision": int(item_row["scenario_revision"]),
                    "attempt_number": attempt_number,
                    "tea_job_id": str(job_row["tea_job_id"]),
                    "retry_of_job_id": job_row["retry_of_job_id"],
                    "selected_for_comparison": offset == len(job_rows),
                    "state": str(job_row["state"]),
                    "verification_status": verification_status,
                    "request_sha256": str(item_row["request_sha256"]),
                    "source_snapshot_sha256": str(
                        job_row["source_snapshot_sha256"]
                    ),
                    "result_sha256": result_sha256,
                    "result_provenance_sha256": result_provenance_sha256,
                    "evidence_set_sha256": evidence_set_sha256,
                    "reporting_tieout_sha256": normalized_tieout,
                }
                for field, expected_value in proof.items():
                    supplied_value = supplied.get(field)
                    if field == "selected_for_comparison":
                        if type(supplied_value) is not bool:
                            raise ValueError(
                                "selected_for_comparison must be a boolean"
                            )
                    if supplied_value != expected_value:
                        raise StoreConflict(
                            f"attempt proof {field} does not match durable history"
                        )
                if verification_status == "verified" and any(
                    (
                        proof["state"] != "done",
                        result_sha256 is None,
                        result_provenance_sha256 is None,
                        normalized_tieout is None,
                    )
                ):
                    raise StoreConflict(
                        "verified attempts require completed results and tie-out"
                    )
                derived.append(proof)
                previous_job_id = str(job_row["tea_job_id"])

        if supplied_by_identity:
            raise StoreConflict("attempt_proofs contain unrelated attempt history")
        return derived

    def _decision_comparison_bundle_still_matches_history(
        self,
        connection: sqlite3.Connection,
        row: sqlite3.Row,
    ) -> bool:
        stored_rows = connection.execute(
            """
            SELECT * FROM decision_comparison_bundle_attempts
             WHERE comparison_bundle_id = ?
             ORDER BY item_index, attempt_number
            """,
            (row["comparison_bundle_id"],),
        ).fetchall()
        supplied = [
            self._decision_comparison_attempt_from_row(stored_row)
            for stored_row in stored_rows
        ]
        try:
            current = self._verified_decision_comparison_attempts(
                connection,
                case_id=str(row["case_id"]),
                source_confirmation_id=str(row["source_confirmation_id"]),
                attempt_proofs=supplied,
            )
        except (AgentStoreError, ValueError):
            return False
        return secrets.compare_digest(_json_dump(supplied), _json_dump(current))

    def _prepare_decision_scenario_revision(
        self,
        *,
        label: str,
        kind: str,
        request: Mapping[str, Any],
        request_sha256: str,
        changed_fields: Sequence[str],
        comparison_classification: str,
        evidence_receipt_refs: Sequence[str | Mapping[str, Any]],
        expires_at: datetime | None,
    ) -> dict[str, Any]:
        normalized_label = _bounded_text(label, field="label", maximum=200)
        if kind not in DECISION_SCENARIO_KINDS:
            raise ValueError("scenario kind must be baseline or alternative")
        if comparison_classification not in DECISION_SCENARIO_COMPARISONS:
            raise ValueError("unsupported scenario comparison classification")
        if kind == "baseline" and comparison_classification != "baseline":
            raise ValueError("baseline scenarios require baseline classification")
        if kind == "alternative" and comparison_classification == "baseline":
            raise ValueError("alternative scenarios require controlled or structural classification")
        if not isinstance(request, Mapping):
            raise ValueError("scenario request must be an object")
        request_json = _json_dump(dict(request))
        normalized_hash = self._validate_sha256(
            request_sha256, field="request_sha256"
        )
        if not secrets.compare_digest(normalized_hash, _sha256_text(request_json)):
            raise StoreConflict("scenario request SHA-256 does not match canonical request")
        normalized_changed = self._normalize_decision_scenario_changed_fields(
            changed_fields
        )
        if kind == "baseline" and normalized_changed:
            raise ValueError("baseline changed_fields must be empty")
        normalized_evidence = self._normalize_decision_scenario_evidence_refs(
            evidence_receipt_refs
        )
        now = self._current_time()
        expiry = now + DECISION_SCENARIO_DRAFT_LIFETIME
        if expires_at is not None:
            expiry = _as_utc(expires_at)
            if expiry <= now:
                raise ValueError("scenario expiry must be in the future")
            if expiry > now + DECISION_SCENARIO_DRAFT_LIFETIME:
                raise ValueError("scenario drafts cannot live longer than seven days")
        return {
            "label": normalized_label,
            "kind": kind,
            "request_json": request_json,
            "request_sha256": normalized_hash,
            "changed_fields_json": _json_dump(normalized_changed),
            "comparison_classification": comparison_classification,
            "evidence_receipt_refs": normalized_evidence,
            "now_text": _timestamp(now),
            "expires_at": _timestamp(expiry),
        }

    def _prepare_decision_scenario_tea_item(
        self,
        raw: Mapping[str, Any],
    ) -> dict[str, Any]:
        scenario_revision_id = str(raw.get("scenario_revision_id") or "").strip()
        if not scenario_revision_id.startswith("dscr_"):
            raise ValueError("scenario_revision_id must use the 'dscr_' prefix")
        expected_revision = raw.get("expected_revision")
        if (
            isinstance(expected_revision, bool)
            or not isinstance(expected_revision, int)
            or expected_revision <= 0
        ):
            raise ValueError("scenario expected_revision must be a positive integer")
        request = raw.get("request")
        if not isinstance(request, Mapping):
            raise ValueError("confirmed scenario request must be an object")
        request_json = _json_dump(dict(request))
        request_hash = self._validate_sha256(
            str(raw.get("request_sha256") or ""), field="request_sha256"
        )
        if not secrets.compare_digest(request_hash, _sha256_text(request_json)):
            raise StoreConflict("confirmed scenario request hash is not canonical")

        job_id = self._validate_technoeconomic_job_id(
            str(raw.get("job_id") or _new_id("tea"))
        )
        source_id = _bounded_text(
            raw.get("source_annual_job_id"),
            field="source_annual_job_id",
            maximum=300,
        )
        artifact_hash = self._validate_sha256(
            str(raw.get("source_artifact_sha256") or ""),
            field="source_artifact_sha256",
        )
        storage_key = str(raw.get("source_artifact_storage_key") or "").strip()
        expected_storage_key = f"sha256/{artifact_hash[:2]}/{artifact_hash}.csv"
        if storage_key != expected_storage_key:
            raise ValueError(
                "source_artifact_storage_key must be the canonical content address "
                f"{expected_storage_key!r}"
            )
        artifact_bytes = raw.get("source_artifact_bytes")
        if (
            isinstance(artifact_bytes, bool)
            or not isinstance(artifact_bytes, int)
            or artifact_bytes <= 0
        ):
            raise ValueError("source_artifact_bytes must be a positive integer")
        snapshot = raw.get("source_snapshot")
        if not isinstance(snapshot, Mapping):
            raise ValueError("source_snapshot must be an object")
        snapshot_payload = dict(snapshot)
        if snapshot_payload.get("source_annual_job_id") != source_id:
            raise ValueError("source snapshot must identify the Annual Simulation source")
        artifact = snapshot_payload.get("midc_source_artifact")
        expected_artifact = {
            "owner_annual_job_id": source_id,
            "storage_key": storage_key,
            "sha256": artifact_hash,
            "byte_count": artifact_bytes,
        }
        if not isinstance(artifact, Mapping) or any(
            artifact.get(field) != expected for field, expected in expected_artifact.items()
        ):
            raise ValueError("source snapshot artifact must match the frozen identity")
        snapshot_json = _json_dump(snapshot_payload)
        provenance = raw.get("submission_provenance")
        if not isinstance(provenance, Mapping):
            raise ValueError("submission_provenance must be an object")
        provenance_json = _json_dump(dict(provenance))
        return {
            "scenario_revision_id": scenario_revision_id,
            "expected_revision": expected_revision,
            "request_json": request_json,
            "request_sha256": request_hash,
            "job_id": job_id,
            "source_annual_job_id": source_id,
            "source_artifact_storage_key": storage_key,
            "source_artifact_sha256": artifact_hash,
            "source_artifact_bytes": artifact_bytes,
            "source_snapshot_json": snapshot_json,
            "source_snapshot_sha256": _sha256_text(snapshot_json),
            "submission_provenance_json": provenance_json,
            "submission_provenance_sha256": _sha256_text(provenance_json),
        }

    def _expire_due_scenario_before_mutation(
        self,
        *,
        scenario_id: str | None = None,
        scenario_revision_id: str | None = None,
        operator_name: str,
    ) -> None:
        """Commit elapsed draft expiry before rejecting a stale mutation."""

        if (scenario_id is None) == (scenario_revision_id is None):
            raise ValueError("exactly one scenario identity is required")
        clause = (
            "scenario_id = ? AND superseded_by_revision_id IS NULL"
            if scenario_id is not None
            else "scenario_revision_id = ?"
        )
        identity = scenario_id if scenario_id is not None else scenario_revision_id
        with self._transaction() as connection:
            row = connection.execute(
                f"SELECT * FROM decision_scenarios WHERE {clause}",
                (str(identity),),
            ).fetchone()
            if row is None:
                return
            case = self._require_decision_case_row(connection, str(row["case_id"]))
            due = (
                row["superseded_by_revision_id"] is None
                and row["status"] in {"draft", "invalid", "validated"}
                and str(row["expires_at"])
                <= _timestamp(self._current_time())
            )
            expected_case_revision = int(case["revision"])
            expected_revision = int(row["revision"])
            stable_id = str(row["scenario_id"])
        if not due:
            return
        self.expire_decision_scenario(
            stable_id,
            expected_case_revision=expected_case_revision,
            expected_revision=expected_revision,
            operator_name=operator_name,
            reason="The unconfirmed scenario draft reached its seven-day expiry.",
        )
        raise InvalidStateTransition("decision scenario draft has expired")

    def _decision_scenario_job_record(
        self,
        row: sqlite3.Row,
    ) -> dict[str, Any]:
        job = self._technoeconomic_job_from_row(row)
        assert job is not None
        return {
            "tea_job_id": str(row["tea_job_id"]),
            "case_id": str(row["case_id"]),
            "scenario_id": str(row["scenario_id"]),
            "scenario_revision_id": str(row["scenario_revision_id"]),
            "scenario_revision": int(row["scenario_revision"]),
            "attempt_number": int(row["attempt_number"]),
            "retry_of_job_id": row["retry_of_job_id"],
            "confirmation_id": row["scenario_confirmation_id"],
            "job": job,
        }

    def _decision_case_execution_summary(
        self,
        connection: sqlite3.Connection,
        case_id: str,
    ) -> dict[str, Any]:
        rows = connection.execute(
            """
            SELECT j.*, l.case_id, l.scenario_revision_id, l.attempt_number,
                   l.confirmation_id AS scenario_confirmation_id,
                   s.scenario_id, s.revision AS scenario_revision
             FROM decision_scenario_jobs l
              JOIN decision_scenarios s
                ON s.scenario_revision_id = l.scenario_revision_id
              JOIN technoeconomic_jobs j ON j.tea_job_id = l.tea_job_id
             WHERE l.case_id = ?
             ORDER BY s.kind ASC, s.scenario_id ASC, l.attempt_number ASC
            """,
            (str(case_id),),
        ).fetchall()
        links = [self._decision_scenario_job_record(row) for row in rows]
        latest_by_revision: dict[str, dict[str, Any]] = {}
        for link in links:
            latest_by_revision[link["scenario_revision_id"]] = link
        latest_links = list(latest_by_revision.values())
        states = [str(item["job"]["state"]) for item in latest_links]
        counts = {state: states.count(state) for state in sorted(JOB_STATES)}
        terminal_count = sum(state in TERMINAL_JOB_STATES for state in states)
        done_count = states.count("done")
        return {
            "jobs": [link["job"] for link in links],
            "links": links,
            "latest_jobs": [link["job"] for link in latest_links],
            "latest_links": latest_links,
            "job_count": len(links),
            "state_counts": counts,
            "all_terminal": bool(latest_links) and terminal_count == len(latest_links),
            "all_successful": bool(latest_links) and done_count == len(latest_links),
            "results_available": done_count > 0,
            "partial_results": done_count > 0 and done_count < len(latest_links),
            "retryable_job_ids": [
                item["tea_job_id"]
                for item in latest_links
                if item["job"]["state"] in {"error", "cancelled", "interrupted"}
            ],
        }

    @staticmethod
    def _require_decision_case_row(
        connection: sqlite3.Connection,
        case_id: str,
        *,
        mutable: bool = False,
    ) -> sqlite3.Row:
        row = connection.execute(
            "SELECT * FROM decision_cases WHERE case_id = ?",
            (case_id,),
        ).fetchone()
        if row is None:
            raise RecordNotFound(f"unknown decision case: {case_id}")
        if mutable and row["status"] in {"signed", "archived"}:
            raise InvalidStateTransition(
                f"{row['status']} decision cases are read-only"
            )
        return row

    @staticmethod
    def _require_case_revision(
        row: sqlite3.Row,
        expected_revision: int | None,
    ) -> None:
        if expected_revision is None:
            return
        if isinstance(expected_revision, bool) or not isinstance(expected_revision, int):
            raise ValueError("expected_revision must be an integer")
        if int(row["revision"]) != expected_revision:
            raise StoreConflict(
                "decision case revision changed "
                f"(expected {expected_revision}, found {row['revision']})"
            )

    @staticmethod
    def _touch_decision_case(
        connection: sqlite3.Connection,
        row: sqlite3.Row,
        *,
        now_text: str,
        operator_name: str,
    ) -> sqlite3.Row:
        next_revision = int(row["revision"]) + 1
        cursor = connection.execute(
            """
            UPDATE decision_cases
               SET revision = ?, updated_at = ?, updated_by = ?
             WHERE case_id = ? AND revision = ?
            """,
            (
                next_revision,
                now_text,
                operator_name,
                row["case_id"],
                row["revision"],
            ),
        )
        if cursor.rowcount != 1:
            raise StoreConflict("decision case changed during mutation")
        updated = connection.execute(
            "SELECT * FROM decision_cases WHERE case_id = ?",
            (row["case_id"],),
        ).fetchone()
        assert updated is not None
        return updated

    @staticmethod
    def _next_decision_message_sequence(
        connection: sqlite3.Connection,
        case_id: str,
    ) -> int:
        row = connection.execute(
            """
            SELECT COALESCE(MAX(message_sequence), 0) + 1 AS next_sequence
              FROM decision_messages
             WHERE case_id = ?
            """,
            (case_id,),
        ).fetchone()
        return int(row["next_sequence"])

    @staticmethod
    def _insert_decision_event(
        connection: sqlite3.Connection,
        *,
        case_id: str,
        event_type: str,
        actor_kind: str,
        payload: Mapping[str, Any],
        created_at: str,
        operator_name: str | None = None,
        turn_id: str | None = None,
        trace_id: str | None = None,
    ) -> sqlite3.Row:
        event_id = _new_id("devt")
        connection.execute(
            """
            INSERT INTO decision_events (
                event_id, case_id, turn_id, event_type, actor_kind,
                operator_name, trace_id, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                case_id,
                turn_id,
                event_type,
                actor_kind,
                operator_name,
                trace_id,
                _json_dump(dict(payload)),
                created_at,
            ),
        )
        row = connection.execute(
            "SELECT * FROM decision_events WHERE event_id = ?",
            (event_id,),
        ).fetchone()
        assert row is not None
        return row

    def _mark_current_decision_outputs_stale(
        self,
        connection: sqlite3.Connection,
        *,
        case_id: str,
        reason: Mapping[str, Any],
        created_at: str,
    ) -> dict[str, int]:
        """Invalidate live derived snapshots in the caller's mutation transaction."""

        reason_payload = dict(reason)
        reason_json = _json_dump(reason_payload)
        bundle_rows = connection.execute(
            """
            SELECT comparison_bundle_id, bundle_sha256
              FROM decision_comparison_bundles
             WHERE case_id = ? AND stale_at IS NULL
               AND superseded_by_bundle_id IS NULL
            """,
            (case_id,),
        ).fetchall()
        brief_rows = connection.execute(
            """
            SELECT brief_id, brief_revision_id, comparison_bundle_sha256
              FROM decision_briefs
             WHERE case_id = ? AND stale_at IS NULL
               AND superseded_by_revision_id IS NULL
            """,
            (case_id,),
        ).fetchall()
        for row in bundle_rows:
            connection.execute(
                """
                UPDATE decision_comparison_bundles
                   SET stale_at = ?, stale_reason_json = ?
                 WHERE comparison_bundle_id = ? AND stale_at IS NULL
                """,
                (created_at, reason_json, row["comparison_bundle_id"]),
            )
            self._insert_decision_event(
                connection,
                case_id=case_id,
                event_type="decision_comparison_bundle_stale",
                actor_kind="system",
                payload={
                    "comparison_bundle_id": row["comparison_bundle_id"],
                    "bundle_sha256": row["bundle_sha256"],
                    "reason": reason_payload,
                },
                created_at=created_at,
            )
        for row in brief_rows:
            connection.execute(
                """
                UPDATE decision_briefs
                   SET stale_at = ?, stale_reason_json = ?
                 WHERE brief_revision_id = ? AND stale_at IS NULL
                """,
                (created_at, reason_json, row["brief_revision_id"]),
            )
            self._insert_decision_event(
                connection,
                case_id=case_id,
                event_type="decision_brief_stale",
                actor_kind="system",
                payload={
                    "brief_id": row["brief_id"],
                    "brief_revision_id": row["brief_revision_id"],
                    "comparison_bundle_sha256": row[
                        "comparison_bundle_sha256"
                    ],
                    "reason": reason_payload,
                },
                created_at=created_at,
            )
        return {"bundles": len(bundle_rows), "briefs": len(brief_rows)}

    def _decision_turn_bundle(
        self,
        connection: sqlite3.Connection,
        row: sqlite3.Row,
    ) -> dict[str, Any]:
        result = self._decision_turn_from_row(row)
        assert result is not None
        message_rows = connection.execute(
            """
            SELECT * FROM decision_messages
             WHERE turn_id = ?
             ORDER BY message_sequence ASC
            """,
            (row["turn_id"],),
        ).fetchall()
        messages = [
            self._decision_message_from_row(message_row)
            for message_row in message_rows
        ]
        result["messages"] = messages
        result["user_message"] = next(
            (item for item in messages if item and item["role"] == "user"),
            None,
        )
        result["assistant_message"] = next(
            (item for item in messages if item and item["role"] == "assistant"),
            None,
        )
        return result

    def _decision_evidence_asset_bundle(
        self,
        connection: sqlite3.Connection,
        row: sqlite3.Row,
    ) -> dict[str, Any]:
        result = self._decision_evidence_asset_from_row(row)
        assert result is not None
        candidate_rows = connection.execute(
            """
            SELECT c.*, r.evidence_receipt_id
              FROM decision_evidence_candidates c
              LEFT JOIN decision_evidence_receipts r
                ON r.evidence_candidate_id = c.evidence_candidate_id
             WHERE c.evidence_asset_id = ?
             ORDER BY c.extracted_at ASC, c.evidence_candidate_id ASC
            """,
            (row["evidence_asset_id"],),
        ).fetchall()
        candidates: list[dict[str, Any]] = []
        for candidate_row in candidate_rows:
            candidate = self._decision_evidence_candidate_from_row(candidate_row)
            assert candidate is not None
            receipt_id = candidate.pop("evidence_receipt_id", None)
            receipt_row = None
            if receipt_id is not None:
                receipt_row = connection.execute(
                    """
                    SELECT * FROM decision_evidence_receipts
                     WHERE evidence_receipt_id = ?
                    """,
                    (receipt_id,),
                ).fetchone()
            receipt = self._decision_evidence_receipt_from_row(receipt_row)
            candidate["receipt"] = receipt
            candidate["review_state"] = (
                str(receipt["decision"]) if receipt is not None else "pending"
            )
            candidates.append(candidate)
        result["candidates"] = candidates
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
        if baseline_id is not None and str(baseline_id).startswith(
            TECHNOECONOMIC_ID_PREFIX
        ):
            raise ValueError(
                "model proposal baseline ids must not use the reserved "
                f"{TECHNOECONOMIC_ID_PREFIX!r} prefix"
            )
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
        if job_id.startswith(TECHNOECONOMIC_ID_PREFIX):
            raise ValueError(
                f"model job ids must not use the reserved "
                f"{TECHNOECONOMIC_ID_PREFIX!r} prefix"
            )
        if kind.strip().casefold() == "technoeconomic":
            raise ValueError(
                "technoeconomic work must use the isolated technoeconomic job table"
            )
        if baseline_id is not None and str(baseline_id).startswith(
            TECHNOECONOMIC_ID_PREFIX
        ):
            raise ValueError(
                "model job baseline ids must not use the reserved "
                f"{TECHNOECONOMIC_ID_PREFIX!r} prefix"
            )
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
                "SELECT ("
                "  SELECT COUNT(*) FROM jobs WHERE state IN ('queued','running')"
                ") + ("
                "  SELECT COUNT(*) FROM technoeconomic_jobs "
                "  WHERE state IN ('queued','running')"
                ")"
            ).fetchone()[0]
        )
        if active + required_slots > limit:
            raise QueueCapacityExceeded(
                f"job queue is full ({active}/{limit} active jobs)"
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

    @staticmethod
    def _validate_technoeconomic_job_id(job_id: str) -> str:
        normalized = str(job_id).strip()
        if not normalized.startswith(TECHNOECONOMIC_ID_PREFIX) or len(normalized) <= len(
            TECHNOECONOMIC_ID_PREFIX
        ):
            raise ValueError(
                "technoeconomic job ids must use the reserved "
                f"{TECHNOECONOMIC_ID_PREFIX!r} prefix"
            )
        return normalized

    @staticmethod
    def _validate_sha256(value: str, *, field: str) -> str:
        normalized = str(value).strip()
        if len(normalized) != 64 or any(
            character not in "0123456789abcdef" for character in normalized
        ):
            raise ValueError(f"{field} must be a lowercase hexadecimal SHA-256")
        return normalized

    @staticmethod
    def _insert_technoeconomic_job(
        connection: sqlite3.Connection,
        *,
        job_id: str,
        request_json: str,
        source_annual_job_id: str,
        source_artifact_storage_key: str,
        source_artifact_sha256: str,
        source_artifact_bytes: int,
        source_snapshot_json: str,
        source_snapshot_sha256: str,
        submission_provenance_json: str,
        submission_provenance_sha256: str,
        retry_of_job_id: str | None,
        now_text: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO technoeconomic_jobs (
                tea_job_id, state, request_json, source_annual_job_id,
                source_artifact_storage_key, source_artifact_sha256,
                source_artifact_bytes, source_snapshot_json,
                source_snapshot_sha256, submission_provenance_json,
                submission_provenance_sha256, retry_of_job_id,
                progress, stage, cancel_requested, created_at, queued_at, updated_at
            ) VALUES (
                ?, 'queued', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                0, 'Queued', 0, ?, ?, ?
            )
            """,
            (
                job_id,
                request_json,
                source_annual_job_id,
                source_artifact_storage_key,
                source_artifact_sha256,
                source_artifact_bytes,
                source_snapshot_json,
                source_snapshot_sha256,
                submission_provenance_json,
                submission_provenance_sha256,
                retry_of_job_id,
                now_text,
                now_text,
                now_text,
            ),
        )

    def create_technoeconomic_job(
        self,
        *,
        request: Mapping[str, Any],
        source_annual_job_id: str,
        source_artifact_storage_key: str,
        source_artifact_sha256: str,
        source_artifact_bytes: int,
        source_snapshot: Mapping[str, Any],
        submission_provenance: Mapping[str, Any],
        job_id: str | None = None,
        max_active_jobs: int | None = None,
        atomic_source_check: Callable[[sqlite3.Connection], str | None] | None = None,
    ) -> dict[str, Any]:
        """Atomically freeze and enqueue a structurally isolated TEA job.

        ``atomic_source_check`` is required for an original enqueue and runs inside
        the same ``BEGIN IMMEDIATE`` transaction immediately before insertion.  It
        must re-read all Annual/calibration/review/promotion dependencies and return
        the SHA-256 of the exact candidate snapshot it verified.  A missing or
        different digest rejects the insert, binding the recheck to the bytes that
        will be persisted.  The callback must not commit, roll back, or mutate
        through the supplied connection.
        """

        job_id = self._validate_technoeconomic_job_id(job_id or _new_id("tea"))
        source_annual_job_id = str(source_annual_job_id).strip()
        if not source_annual_job_id:
            raise ValueError("source_annual_job_id must not be blank")
        artifact_hash = self._validate_sha256(
            source_artifact_sha256, field="source_artifact_sha256"
        )
        storage_key = str(source_artifact_storage_key).strip()
        expected_storage_key = (
            f"sha256/{artifact_hash[:2]}/{artifact_hash}.csv"
        )
        if storage_key != expected_storage_key:
            raise ValueError(
                "source_artifact_storage_key must be the canonical content address "
                f"{expected_storage_key!r}"
            )
        if isinstance(source_artifact_bytes, bool) or not isinstance(
            source_artifact_bytes, int
        ) or source_artifact_bytes <= 0:
            raise ValueError("source_artifact_bytes must be a positive integer")
        artifact_bytes = source_artifact_bytes

        request_json = _json_dump(dict(request))
        snapshot_payload = dict(source_snapshot)
        snapshot_source_id = snapshot_payload.get("source_annual_job_id")
        if snapshot_source_id != source_annual_job_id:
            raise ValueError(
                "source_annual_job_id must match the frozen source snapshot"
            )
        snapshot_artifact = snapshot_payload.get("midc_source_artifact")
        if not isinstance(snapshot_artifact, Mapping):
            raise ValueError(
                "source_snapshot must contain a midc_source_artifact identity"
            )
        expected_artifact_identity = {
            "owner_annual_job_id": source_annual_job_id,
            "storage_key": storage_key,
            "sha256": artifact_hash,
            "byte_count": artifact_bytes,
        }
        for field, expected in expected_artifact_identity.items():
            if snapshot_artifact.get(field) != expected:
                raise ValueError(
                    f"source snapshot artifact {field} must match the frozen "
                    "top-level identity"
                )
        snapshot_json = _json_dump(snapshot_payload)
        provenance_json = _json_dump(dict(submission_provenance))
        snapshot_hash = _sha256_text(snapshot_json)
        provenance_hash = _sha256_text(provenance_json)
        now_text = _timestamp(self._current_time())
        if atomic_source_check is None:
            raise ValueError(
                "atomic_source_check is required for a new technoeconomic job"
            )

        with self._transaction(write=True) as connection:
            source = connection.execute(
                "SELECT * FROM jobs WHERE job_id = ?", (source_annual_job_id,)
            ).fetchone()
            if source is None:
                raise RecordNotFound(
                    f"unknown Annual Simulation source: {source_annual_job_id}"
                )
            if source["mode"] != "annual" or source["state"] != "done":
                raise InvalidStateTransition(
                    "technoeconomic source must be a completed Annual Simulation"
                )
            if connection.execute(
                "SELECT 1 FROM technoeconomic_jobs WHERE tea_job_id = ?", (job_id,)
            ).fetchone() is not None or connection.execute(
                "SELECT 1 FROM jobs WHERE job_id = ?", (job_id,)
            ).fetchone() is not None:
                raise StoreConflict(f"technoeconomic job id already exists: {job_id}")
            self._ensure_queue_capacity(
                connection, max_active_jobs=max_active_jobs
            )
            verified_snapshot_hash = atomic_source_check(connection)
            if not isinstance(verified_snapshot_hash, str) or not secrets.compare_digest(
                verified_snapshot_hash, snapshot_hash
            ):
                raise StoreConflict(
                    "Annual Simulation source changed or the verified snapshot "
                    "does not match the technoeconomic payload"
                )
            try:
                self._insert_technoeconomic_job(
                    connection,
                    job_id=job_id,
                    request_json=request_json,
                    source_annual_job_id=source_annual_job_id,
                    source_artifact_storage_key=storage_key,
                    source_artifact_sha256=artifact_hash,
                    source_artifact_bytes=artifact_bytes,
                    source_snapshot_json=snapshot_json,
                    source_snapshot_sha256=snapshot_hash,
                    submission_provenance_json=provenance_json,
                    submission_provenance_sha256=provenance_hash,
                    retry_of_job_id=None,
                    now_text=now_text,
                )
            except sqlite3.IntegrityError as exc:
                raise StoreConflict(
                    f"could not create technoeconomic job: {job_id}"
                ) from exc
            row = connection.execute(
                "SELECT * FROM technoeconomic_jobs WHERE tea_job_id = ?", (job_id,)
            ).fetchone()
        return self._technoeconomic_job_from_row(row)  # type: ignore[return-value]

    def get_technoeconomic_job(self, job_id: str) -> dict[str, Any] | None:
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT * FROM technoeconomic_jobs WHERE tea_job_id = ?", (job_id,)
            ).fetchone()
        return self._technoeconomic_job_from_row(row)

    def list_technoeconomic_jobs(
        self,
        *,
        states: Sequence[str] | None = None,
        source_annual_job_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        if states is not None:
            unknown = set(states) - JOB_STATES
            if unknown:
                raise ValueError(f"unknown technoeconomic job states: {sorted(unknown)}")
        if limit <= 0:
            return []
        clauses: list[str] = []
        parameters: list[Any] = []
        if states:
            clauses.append(f"state IN ({','.join('?' for _ in states)})")
            parameters.extend(states)
        if source_annual_job_id is not None:
            clauses.append("source_annual_job_id = ?")
            parameters.append(str(source_annual_job_id))
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        parameters.append(int(limit))
        with self._transaction() as connection:
            rows = connection.execute(
                f"SELECT * FROM technoeconomic_jobs {where} "
                "ORDER BY created_at DESC, tea_job_id DESC LIMIT ?",
                parameters,
            ).fetchall()
        return [
            self._technoeconomic_job_from_row(row) for row in rows
        ]  # type: ignore[misc]

    def list_jobs(
        self,
        *,
        states: Sequence[str] | None = None,
        mode: str | None = None,
        kind: str | None = None,
        baseline_id: str | None | object = _UNSET,
        limit: int | None = 100,
    ) -> list[dict[str, Any]]:
        if mode is not None:
            self._validate_mode(mode)
        if states is not None:
            unknown = set(states) - JOB_STATES
            if unknown:
                raise ValueError(f"unknown job states: {sorted(unknown)}")
        if limit is not None and limit <= 0:
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
        limit_clause = ""
        if limit is not None:
            limit_clause = " LIMIT ?"
            parameters.append(int(limit))
        with self._transaction() as connection:
            rows = connection.execute(
                f"SELECT * FROM jobs {where} "
                f"ORDER BY created_at DESC, job_id DESC{limit_clause}",
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
            # Running work is entered only by the atomic cross-workflow claimer.
            "queued": {"cancelled", "error"},
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
            retained_source = connection.execute(
                "SELECT 1 FROM technoeconomic_jobs "
                "WHERE source_annual_job_id = ? LIMIT 1",
                (job_id,),
            ).fetchone()
            retained_payload_update = any(
                value is not _UNSET
                for value in (result, provenance, artifacts, source_path, source_hash)
            ) or (state is not None and state != row["state"])
            if retained_source is not None and retained_payload_update:
                raise InvalidStateTransition(
                    "referenced Annual Simulation source payload is retained"
                )
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

    @staticmethod
    def _running_work_exists(connection: sqlite3.Connection) -> bool:
        return (
            connection.execute(
                """
                SELECT 1 FROM jobs WHERE state = 'running'
                UNION ALL
                SELECT 1 FROM technoeconomic_jobs WHERE state = 'running'
                LIMIT 1
                """
            ).fetchone()
            is not None
        )

    @staticmethod
    def _oldest_queued_work(
        connection: sqlite3.Connection,
    ) -> sqlite3.Row | None:
        return connection.execute(
            """
            SELECT workflow, work_id, queued_at
              FROM (
                    SELECT 'model' AS workflow, job_id AS work_id, queued_at
                      FROM jobs
                     WHERE state = 'queued' AND cancel_requested = 0
                    UNION ALL
                    SELECT 'technoeconomic' AS workflow,
                           tea_job_id AS work_id, queued_at
                      FROM technoeconomic_jobs
                     WHERE state = 'queued' AND cancel_requested = 0
                   )
             ORDER BY queued_at ASC, workflow ASC, work_id ASC
             LIMIT 1
            """
        ).fetchone()

    def _claim_oldest_queued_work(
        self,
        connection: sqlite3.Connection,
        *,
        worker_id: str | None,
        now_text: str,
        model_only: bool,
    ) -> tuple[str, sqlite3.Row] | None:
        if self._running_work_exists(connection):
            return None
        queued = self._oldest_queued_work(connection)
        if queued is None or (model_only and queued["workflow"] != "model"):
            return None
        workflow = str(queued["workflow"])
        work_id = str(queued["work_id"])
        lease_token = uuid.uuid4().hex if worker_id is not None else None
        if workflow == "model":
            table = "jobs"
            id_column = "job_id"
        else:
            table = "technoeconomic_jobs"
            id_column = "tea_job_id"
        cursor = connection.execute(
            f"""
            UPDATE {table}
               SET state = 'running', stage = 'Running', started_at = ?,
                   updated_at = ?, worker_id = ?, lease_token = ?, heartbeat_at = ?
             WHERE {id_column} = ? AND state = 'queued' AND cancel_requested = 0
            """,
            (now_text, now_text, worker_id, lease_token, now_text, work_id),
        )
        if cursor.rowcount != 1:
            return None
        row = connection.execute(
            f"SELECT * FROM {table} WHERE {id_column} = ?", (work_id,)
        ).fetchone()
        if row is None:
            return None
        if workflow == "technoeconomic":
            decision_link = connection.execute(
                """
                SELECT case_id, scenario_revision_id, attempt_number
                  FROM decision_scenario_jobs WHERE tea_job_id = ?
                """,
                (work_id,),
            ).fetchone()
            if decision_link is not None:
                self._mark_current_decision_outputs_stale(
                    connection,
                    case_id=str(decision_link["case_id"]),
                    reason={
                        "code": "decision_scenario_attempt_changed",
                        "tea_job_id": work_id,
                        "scenario_revision_id": decision_link[
                            "scenario_revision_id"
                        ],
                        "attempt_number": int(decision_link["attempt_number"]),
                        "previous_state": "queued",
                        "state": "running",
                    },
                    created_at=now_text,
                )
        return workflow, row

    def claim_next_queued_work(
        self, *, worker_id: str | None = None
    ) -> dict[str, Any] | None:
        """Atomically claim the globally oldest model or TEA job."""

        if worker_id is None or not worker_id.strip():
            raise ValueError("worker_id is required to lease queued work")
        now_text = _timestamp(self._current_time())
        with self._transaction(write=True) as connection:
            claimed = self._claim_oldest_queued_work(
                connection,
                worker_id=worker_id,
                now_text=now_text,
                model_only=False,
            )
        if claimed is None:
            return None
        workflow, row = claimed
        if workflow == "model":
            result = self._job_from_row(row)
        else:
            result = self._technoeconomic_job_from_row(row)
        assert result is not None
        result["workflow"] = workflow
        return result

    def claim_next_queued_job(
        self, *, worker_id: str | None = None
    ) -> dict[str, Any] | None:
        """Claim a model job only when it is globally oldest.

        This compatibility entry point keeps the current model worker safe until it
        dispatches :meth:`claim_next_queued_work`: a queued TEA job cannot be
        leapfrogged, and a running job in either workflow blocks all other claims.
        """

        if worker_id is not None and not worker_id.strip():
            raise ValueError("worker_id must not be blank")
        now_text = _timestamp(self._current_time())
        with self._transaction(write=True) as connection:
            claimed = self._claim_oldest_queued_work(
                connection,
                worker_id=worker_id,
                now_text=now_text,
                model_only=True,
            )
        if claimed is None:
            return None
        _, row = claimed
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

    def update_technoeconomic_job(
        self,
        job_id: str,
        *,
        expected_worker_id: str | None = None,
        expected_lease_token: str | None = None,
        state: str | None = None,
        progress: float | None = None,
        stage: str | None = None,
        result: Mapping[str, Any] | None | object = _UNSET,
        result_provenance: Mapping[str, Any] | None | object = _UNSET,
        artifacts: Mapping[str, Any] | None | object = _UNSET,
        error: str | None | object = _UNSET,
    ) -> dict[str, Any]:
        """Update TEA execution fields with lease fencing and terminal sealing."""

        if (expected_worker_id is None) != (expected_lease_token is None):
            raise ValueError(
                "expected_worker_id and expected_lease_token must be supplied together"
            )
        if expected_worker_id is not None and (
            not expected_worker_id.strip()
            or not expected_lease_token
            or not expected_lease_token.strip()
        ):
            raise ValueError("job lease owner and token must not be blank")
        if state is not None and state not in JOB_STATES:
            raise ValueError(f"unknown technoeconomic job state: {state}")
        if progress is not None and (
            not math.isfinite(float(progress)) or not 0 <= float(progress) <= 100
        ):
            raise ValueError("progress must be a finite percentage in [0, 100]")

        now_text = _timestamp(self._current_time())
        with self._transaction(write=True) as connection:
            row = connection.execute(
                "SELECT * FROM technoeconomic_jobs WHERE tea_job_id = ?", (job_id,)
            ).fetchone()
            if row is None:
                if expected_worker_id is not None:
                    raise LeaseOwnershipLost(
                        "runner no longer owns the active lease for missing "
                        f"technoeconomic job {job_id}"
                    )
                raise RecordNotFound(f"unknown technoeconomic job: {job_id}")
            if row["state"] in TERMINAL_JOB_STATES and expected_worker_id is not None:
                raise LeaseOwnershipLost(
                    f"runner no longer owns the active lease for "
                    f"technoeconomic job {job_id}"
                )
            if row["state"] in TERMINAL_JOB_STATES:
                raise InvalidStateTransition(
                    f"terminal technoeconomic job {job_id} is immutable"
                )
            if state == "done" and bool(row["cancel_requested"]):
                raise InvalidStateTransition(
                    "cannot complete a technoeconomic job after cancellation "
                    "was requested"
                )

            lease_is_owned = bool(row["worker_id"] or row["lease_token"])
            expected_lease = expected_worker_id is not None
            if expected_lease and (
                row["state"] != "running"
                or row["worker_id"] != expected_worker_id
                or row["lease_token"] != expected_lease_token
            ):
                raise LeaseOwnershipLost(
                    f"runner no longer owns the active lease for "
                    f"technoeconomic job {job_id}"
                )
            if row["state"] == "running" and lease_is_owned and not expected_lease:
                raise LeaseOwnershipLost(
                    f"running technoeconomic job {job_id} requires its active "
                    "lease token"
                )
            if state is not None:
                self._check_job_transition(str(row["state"]), state)

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
                if state in TERMINAL_JOB_STATES:
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
                ("result_provenance", result_provenance),
                ("artifacts", artifacts),
            ):
                if value is not _UNSET:
                    assignments.append(f"{name}_json = ?")
                    values.append(None if value is None else _json_dump(dict(value)))
            if error is not _UNSET:
                assignments.append("error = ?")
                values.append(error)

            values.append(job_id)
            connection.execute(
                f"UPDATE technoeconomic_jobs SET {', '.join(assignments)} "
                "WHERE tea_job_id = ?",
                values,
            )
            if (
                (state is not None and state != row["state"])
                or result is not _UNSET
                or result_provenance is not _UNSET
            ):
                decision_link = connection.execute(
                    """
                    SELECT case_id, scenario_revision_id, attempt_number
                      FROM decision_scenario_jobs WHERE tea_job_id = ?
                    """,
                    (job_id,),
                ).fetchone()
                if decision_link is not None:
                    self._mark_current_decision_outputs_stale(
                        connection,
                        case_id=str(decision_link["case_id"]),
                        reason={
                            "code": "decision_scenario_attempt_changed",
                            "tea_job_id": str(job_id),
                            "scenario_revision_id": decision_link[
                                "scenario_revision_id"
                            ],
                            "attempt_number": int(
                                decision_link["attempt_number"]
                            ),
                            "previous_state": row["state"],
                            "state": state or row["state"],
                        },
                        created_at=now_text,
                    )
            updated = connection.execute(
                "SELECT * FROM technoeconomic_jobs WHERE tea_job_id = ?", (job_id,)
            ).fetchone()
        return self._technoeconomic_job_from_row(updated)  # type: ignore[return-value]

    def heartbeat_technoeconomic_job(
        self, job_id: str, *, worker_id: str, lease_token: str
    ) -> bool:
        """Renew a running TEA lease only for its current owner."""

        if not worker_id or not worker_id.strip():
            raise ValueError("worker_id must not be blank")
        if not lease_token or not lease_token.strip():
            raise ValueError("lease_token must not be blank")
        now_text = _timestamp(self._current_time())
        with self._transaction(write=True) as connection:
            cursor = connection.execute(
                """
                UPDATE technoeconomic_jobs
                   SET heartbeat_at = ?, updated_at = ?
                 WHERE tea_job_id = ? AND state = 'running' AND worker_id = ?
                   AND lease_token = ?
                """,
                (now_text, now_text, job_id, worker_id, lease_token),
            )
        return cursor.rowcount == 1

    def cancel_technoeconomic_job(self, job_id: str) -> dict[str, Any]:
        """Cancel queued TEA work or request cooperative runner cancellation."""

        now_text = _timestamp(self._current_time())
        with self._transaction(write=True) as connection:
            row = connection.execute(
                "SELECT * FROM technoeconomic_jobs WHERE tea_job_id = ?", (job_id,)
            ).fetchone()
            if row is None:
                raise RecordNotFound(f"unknown technoeconomic job: {job_id}")
            if connection.execute(
                "SELECT 1 FROM decision_scenario_jobs WHERE tea_job_id = ?",
                (job_id,),
            ).fetchone() is not None:
                raise InvalidStateTransition(
                    "decision scenario TEA jobs require case-scoped cancellation"
                )
            if row["state"] == "queued":
                connection.execute(
                    """
                    UPDATE technoeconomic_jobs
                       SET state = 'cancelled', cancel_requested = 1,
                           cancel_requested_at = ?, completed_at = ?, updated_at = ?,
                           stage = 'Cancelled'
                     WHERE tea_job_id = ? AND state = 'queued'
                    """,
                    (now_text, now_text, now_text, job_id),
                )
            elif row["state"] == "running" and not row["cancel_requested"]:
                connection.execute(
                    """
                    UPDATE technoeconomic_jobs
                       SET cancel_requested = 1, cancel_requested_at = ?, updated_at = ?
                     WHERE tea_job_id = ? AND state = 'running'
                    """,
                    (now_text, now_text, job_id),
                )
            updated = connection.execute(
                "SELECT * FROM technoeconomic_jobs WHERE tea_job_id = ?", (job_id,)
            ).fetchone()
        return self._technoeconomic_job_from_row(updated)  # type: ignore[return-value]

    def is_technoeconomic_cancel_requested(
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
                "FROM technoeconomic_jobs WHERE tea_job_id = ?",
                (job_id,),
            ).fetchone()
        if row is None:
            if expected_worker_id is not None:
                raise LeaseOwnershipLost(
                    "runner no longer owns the active lease for missing "
                    f"technoeconomic job {job_id}"
                )
            raise RecordNotFound(f"unknown technoeconomic job: {job_id}")
        if expected_worker_id is not None and (
            row["state"] != "running"
            or row["worker_id"] != expected_worker_id
            or row["lease_token"] != expected_lease_token
        ):
            raise LeaseOwnershipLost(
                f"runner no longer owns the active lease for technoeconomic job {job_id}"
            )
        return bool(row["cancel_requested"])

    def mark_stale_running_technoeconomic_jobs_interrupted(
        self, *, before: datetime | None = None
    ) -> int:
        """Interrupt TEA leases abandoned by a prior worker process."""

        now_text = _timestamp(self._current_time())
        clauses = ["state = 'running'"]
        parameters: list[Any] = [now_text, now_text, now_text]
        if before is not None:
            clauses.append("COALESCE(heartbeat_at, started_at, updated_at) <= ?")
            parameters.append(_timestamp(before))
        with self._transaction(write=True) as connection:
            decision_cases = connection.execute(
                """
                SELECT DISTINCT l.case_id
                 FROM technoeconomic_jobs j
                  JOIN decision_scenario_jobs l ON l.tea_job_id = j.tea_job_id
                 WHERE """
                + "j.state = 'running'"
                + (
                    " AND COALESCE(j.heartbeat_at, j.started_at, j.updated_at) <= ?"
                    if before is not None
                    else ""
                ),
                parameters[3:],
            ).fetchall()
            cursor = connection.execute(
                """
                UPDATE technoeconomic_jobs
                   SET state = 'interrupted',
                       stage = 'Interrupted after service restart',
                       interrupted_at = ?, completed_at = ?, updated_at = ?,
                       worker_id = NULL, lease_token = NULL, heartbeat_at = NULL
                 WHERE """
                + " AND ".join(clauses),
                parameters,
            )
            for decision_case in decision_cases:
                self._mark_current_decision_outputs_stale(
                    connection,
                    case_id=str(decision_case["case_id"]),
                    reason={
                        "code": "decision_scenario_attempts_interrupted",
                        "cause": "stale_worker_lease",
                    },
                    created_at=now_text,
                )
            return int(cursor.rowcount)

    def retry_technoeconomic_job(
        self,
        job_id: str,
        *,
        new_job_id: str | None = None,
        max_active_jobs: int | None = None,
    ) -> dict[str, Any]:
        """Create a new attempt from a retryable job's frozen evidence."""

        retry_id = self._validate_technoeconomic_job_id(
            new_job_id or _new_id("tea")
        )
        now_text = _timestamp(self._current_time())
        with self._transaction(write=True) as connection:
            row = connection.execute(
                "SELECT * FROM technoeconomic_jobs WHERE tea_job_id = ?", (job_id,)
            ).fetchone()
            if row is None:
                raise RecordNotFound(f"unknown technoeconomic job: {job_id}")
            if connection.execute(
                "SELECT 1 FROM decision_scenario_jobs WHERE tea_job_id = ?",
                (job_id,),
            ).fetchone() is not None:
                raise InvalidStateTransition(
                    "decision scenario TEA jobs require case-scoped retry"
                )
            if row["state"] not in {"interrupted", "error", "cancelled"}:
                raise InvalidStateTransition(
                    f"cannot retry technoeconomic job in state {row['state']}"
                )
            if connection.execute(
                "SELECT 1 FROM technoeconomic_jobs WHERE tea_job_id = ?", (retry_id,)
            ).fetchone() is not None or connection.execute(
                "SELECT 1 FROM jobs WHERE job_id = ?", (retry_id,)
            ).fetchone() is not None:
                raise StoreConflict(
                    f"technoeconomic job id already exists: {retry_id}"
                )
            self._ensure_queue_capacity(
                connection, max_active_jobs=max_active_jobs
            )
            try:
                self._insert_technoeconomic_job(
                    connection,
                    job_id=retry_id,
                    request_json=str(row["request_json"]),
                    source_annual_job_id=str(row["source_annual_job_id"]),
                    source_artifact_storage_key=str(
                        row["source_artifact_storage_key"]
                    ),
                    source_artifact_sha256=str(row["source_artifact_sha256"]),
                    source_artifact_bytes=int(row["source_artifact_bytes"]),
                    source_snapshot_json=str(row["source_snapshot_json"]),
                    source_snapshot_sha256=str(row["source_snapshot_sha256"]),
                    submission_provenance_json=str(
                        row["submission_provenance_json"]
                    ),
                    submission_provenance_sha256=str(
                        row["submission_provenance_sha256"]
                    ),
                    retry_of_job_id=job_id,
                    now_text=now_text,
                )
            except sqlite3.IntegrityError as exc:
                raise StoreConflict(
                    f"could not retry technoeconomic job as {retry_id}"
                ) from exc
            retried = connection.execute(
                "SELECT * FROM technoeconomic_jobs WHERE tea_job_id = ?", (retry_id,)
            ).fetchone()
        return self._technoeconomic_job_from_row(retried)  # type: ignore[return-value]

    def delete_technoeconomic_job(
        self,
        job_id: str,
        *,
        before_delete: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        """Delete a terminal TEA record after optional in-transaction cleanup.

        ``before_delete`` runs after all state and retry-lineage checks but before
        the row is removed.  The API uses it for confined filesystem cleanup so a
        cleanup failure rolls the database transaction back and leaves a durable
        job that can be deleted again.  The callback must not access this store.
        """

        with self._transaction(write=True) as connection:
            row = connection.execute(
                "SELECT * FROM technoeconomic_jobs WHERE tea_job_id = ?", (job_id,)
            ).fetchone()
            if row is None:
                raise RecordNotFound(f"unknown technoeconomic job: {job_id}")
            if connection.execute(
                "SELECT 1 FROM decision_scenario_jobs WHERE tea_job_id = ?",
                (job_id,),
            ).fetchone() is not None:
                raise InvalidStateTransition(
                    "decision scenario TEA jobs are retained for audit history"
                )
            if row["state"] not in TERMINAL_JOB_STATES:
                raise InvalidStateTransition(
                    "cancel active technoeconomic work before deleting it"
                )
            dependent = connection.execute(
                "SELECT tea_job_id FROM technoeconomic_jobs "
                "WHERE retry_of_job_id = ? LIMIT 1",
                (job_id,),
            ).fetchone()
            if dependent is not None:
                raise InvalidStateTransition(
                    "delete later technoeconomic retry attempts before their source attempt"
                )
            deleted = self._technoeconomic_job_from_row(row)
            assert deleted is not None
            if before_delete is not None:
                before_delete(deleted)
            connection.execute(
                "DELETE FROM technoeconomic_jobs WHERE tea_job_id = ?", (job_id,)
            )
        return deleted

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
            referenced_tea = connection.execute(
                "SELECT tea_job_id FROM technoeconomic_jobs "
                "WHERE source_annual_job_id = ? LIMIT 1",
                (job_id,),
            ).fetchone()
            if referenced_tea is not None:
                raise InvalidStateTransition(
                    "Annual Simulation is retained by technoeconomic job "
                    f"{referenced_tea['tea_job_id']}"
                )
            referenced_case = connection.execute(
                "SELECT case_id FROM decision_cases "
                "WHERE source_annual_job_id = ? LIMIT 1",
                (job_id,),
            ).fetchone()
            if referenced_case is not None:
                raise InvalidStateTransition(
                    "Annual Simulation is retained by decision case "
                    f"{referenced_case['case_id']}"
                )
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

    def get_promotion(
        self,
        *,
        mode: str,
        job_id: str,
        promoted_at: str,
    ) -> dict[str, Any] | None:
        """Return one exact historical baseline-promotion receipt.

        Annual Simulation provenance records the validation mode, origin job ID,
        and promotion timestamp.  TEA source verification must resolve that exact
        historical receipt rather than depending on the current baseline or on a
        bounded recent-promotion listing.
        """

        self._validate_mode(mode)
        normalized_job_id = job_id.strip() if isinstance(job_id, str) else ""
        normalized_promoted_at = (
            promoted_at.strip() if isinstance(promoted_at, str) else ""
        )
        if not normalized_job_id:
            raise ValueError("job_id must not be blank")
        if not normalized_promoted_at:
            raise ValueError("promoted_at must not be blank")
        with self._transaction() as connection:
            row = connection.execute(
                """
                SELECT * FROM baseline_promotions
                 WHERE mode = ? AND job_id = ? AND promoted_at = ?
                 ORDER BY promotion_id DESC
                 LIMIT 1
                """,
                (mode, normalized_job_id, normalized_promoted_at),
            ).fetchone()
        return None if row is None else dict(row)

    def create_decision_case(
        self,
        *,
        title: str,
        question: str,
        operator_name: str,
        case_id: str | None = None,
    ) -> dict[str, Any]:
        """Create one durable draft case and its first append-only event."""

        normalized_id = str(case_id or _new_id("case")).strip()
        if not normalized_id.startswith("case_") or len(normalized_id) <= 5:
            raise ValueError("decision case ids must use the 'case_' prefix")
        normalized_title = _bounded_text(title, field="title", maximum=200)
        normalized_question = _bounded_text(
            question, field="question", maximum=8_000
        )
        operator = _bounded_text(
            operator_name, field="operator_name", maximum=200
        )
        now_text = _timestamp(self._current_time())
        with self._transaction(write=True) as connection:
            try:
                connection.execute(
                    """
                    INSERT INTO decision_cases (
                        case_id, title, original_question, question, status,
                        revision, created_by, updated_by, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, 'draft', 1, ?, ?, ?, ?)
                    """,
                    (
                        normalized_id,
                        normalized_title,
                        normalized_question,
                        normalized_question,
                        operator,
                        operator,
                        now_text,
                        now_text,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise StoreConflict(
                    f"decision case id already exists or is invalid: {normalized_id}"
                ) from exc
            self._insert_decision_event(
                connection,
                case_id=normalized_id,
                event_type="decision_case_created",
                actor_kind="operator",
                operator_name=operator,
                payload={
                    "case_id": normalized_id,
                    "status": "draft",
                    "revision": 1,
                    "title": normalized_title,
                    "question": normalized_question,
                },
                created_at=now_text,
            )
            row = connection.execute(
                "SELECT * FROM decision_cases WHERE case_id = ?",
                (normalized_id,),
            ).fetchone()
        return self._decision_case_from_row(row)  # type: ignore[return-value]

    def get_decision_case(self, case_id: str) -> dict[str, Any] | None:
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT * FROM decision_cases WHERE case_id = ?",
                (str(case_id),),
            ).fetchone()
        return self._decision_case_from_row(row)

    def list_decision_cases(
        self,
        *,
        statuses: Sequence[str] | None = None,
        include_archived: bool = False,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        if statuses is not None:
            unknown = set(statuses) - DECISION_CASE_STATES
            if unknown:
                raise ValueError(f"unknown decision case states: {sorted(unknown)}")
        if limit <= 0:
            return []
        clauses: list[str] = []
        parameters: list[Any] = []
        if statuses:
            clauses.append(f"status IN ({','.join('?' for _ in statuses)})")
            parameters.extend(statuses)
        elif not include_archived:
            clauses.append("status <> 'archived'")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        parameters.append(int(limit))
        with self._transaction() as connection:
            rows = connection.execute(
                f"SELECT * FROM decision_cases {where} "
                "ORDER BY updated_at DESC, case_id DESC LIMIT ?",
                parameters,
            ).fetchall()
        return [
            self._decision_case_from_row(row) for row in rows
        ]  # type: ignore[misc]

    def update_decision_case(
        self,
        case_id: str,
        *,
        expected_revision: int,
        operator_name: str,
        title: str | object = _UNSET,
        question: str | object = _UNSET,
        decision_owner: str | None | object = _UNSET,
    ) -> dict[str, Any]:
        """Edit mutable case metadata with compare-and-swap revision fencing."""

        operator = _bounded_text(
            operator_name, field="operator_name", maximum=200
        )
        values: dict[str, Any] = {}
        if title is not _UNSET:
            values["title"] = _bounded_text(title, field="title", maximum=200)
        if question is not _UNSET:
            values["question"] = _bounded_text(
                question, field="question", maximum=8_000
            )
        if decision_owner is not _UNSET:
            values["decision_owner"] = _optional_bounded_text(
                decision_owner,
                field="decision_owner",
                maximum=200,
            )
        if not values:
            raise ValueError("at least one mutable decision case field is required")
        now_text = _timestamp(self._current_time())
        with self._transaction(write=True) as connection:
            current = self._require_decision_case_row(
                connection, str(case_id), mutable=True
            )
            self._require_case_revision(current, expected_revision)
            changed = {
                field: value
                for field, value in values.items()
                if current[field] != value
            }
            if not changed:
                return self._decision_case_from_row(current)  # type: ignore[return-value]
            assignments = [f"{field} = ?" for field in changed]
            parameters = [*changed.values(), now_text, operator, str(case_id), expected_revision]
            cursor = connection.execute(
                "UPDATE decision_cases SET "
                + ", ".join(assignments)
                + ", revision = revision + 1, updated_at = ?, updated_by = ? "
                "WHERE case_id = ? AND revision = ?",
                parameters,
            )
            if cursor.rowcount != 1:
                raise StoreConflict("decision case changed during update")
            updated = connection.execute(
                "SELECT * FROM decision_cases WHERE case_id = ?",
                (str(case_id),),
            ).fetchone()
            assert updated is not None
            self._insert_decision_event(
                connection,
                case_id=str(case_id),
                event_type="decision_case_updated",
                actor_kind="operator",
                operator_name=operator,
                payload={
                    "changed_fields": sorted(changed),
                    "changes": {
                        field: {
                            "before": current[field],
                            "after": changed[field],
                        }
                        for field in sorted(changed)
                    },
                    "revision": int(updated["revision"]),
                },
                created_at=now_text,
            )
        return self._decision_case_from_row(updated)  # type: ignore[return-value]

    def lock_decision_case(
        self,
        case_id: str,
        *,
        expected_revision: int,
        source_annual_job_id: str,
        source_snapshot_sha256: str,
        analysis_basis: str,
        operator_name: str,
    ) -> dict[str, Any]:
        """Set the case's Annual source and TEA basis exactly once."""

        source_id = _bounded_text(
            source_annual_job_id,
            field="source_annual_job_id",
            maximum=300,
        )
        source_hash = self._validate_sha256(
            source_snapshot_sha256,
            field="source_snapshot_sha256",
        )
        if analysis_basis not in {"solartac_site", "commercial_representative"}:
            raise ValueError("analysis_basis is unsupported")
        operator = _bounded_text(
            operator_name, field="operator_name", maximum=200
        )
        now_text = _timestamp(self._current_time())
        with self._transaction(write=True) as connection:
            current = self._require_decision_case_row(
                connection, str(case_id), mutable=True
            )
            if current["source_annual_job_id"] is not None:
                matches = (
                    current["source_annual_job_id"] == source_id
                    and current["source_snapshot_sha256"] == source_hash
                    and current["analysis_basis"] == analysis_basis
                )
                if matches:
                    return self._decision_case_from_row(current)  # type: ignore[return-value]
                raise InvalidStateTransition(
                    "a locked decision source or basis requires a new case"
                )
            self._require_case_revision(current, expected_revision)
            source = connection.execute(
                "SELECT mode, state FROM jobs WHERE job_id = ?",
                (source_id,),
            ).fetchone()
            if source is None:
                raise RecordNotFound(f"unknown Annual Simulation source: {source_id}")
            if source["mode"] != "annual" or source["state"] != "done":
                raise InvalidStateTransition(
                    "decision case source must be a completed Annual Simulation"
                )
            try:
                cursor = connection.execute(
                    """
                    UPDATE decision_cases
                       SET source_annual_job_id = ?, source_snapshot_sha256 = ?,
                           analysis_basis = ?, source_basis_locked_at = ?,
                           source_basis_locked_by = ?, revision = revision + 1,
                           updated_at = ?, updated_by = ?
                     WHERE case_id = ? AND revision = ?
                    """,
                    (
                        source_id,
                        source_hash,
                        analysis_basis,
                        now_text,
                        operator,
                        now_text,
                        operator,
                        str(case_id),
                        expected_revision,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise StoreConflict("could not lock decision case source and basis") from exc
            if cursor.rowcount != 1:
                raise StoreConflict("decision case changed while its source was locked")
            updated = connection.execute(
                "SELECT * FROM decision_cases WHERE case_id = ?",
                (str(case_id),),
            ).fetchone()
            assert updated is not None
            self._insert_decision_event(
                connection,
                case_id=str(case_id),
                event_type="decision_case_source_basis_locked",
                actor_kind="operator",
                operator_name=operator,
                payload={
                    "source_annual_job_id": source_id,
                    "source_snapshot_sha256": source_hash,
                    "analysis_basis": analysis_basis,
                    "revision": int(updated["revision"]),
                },
                created_at=now_text,
            )
        return self._decision_case_from_row(updated)  # type: ignore[return-value]

    def transition_decision_case(
        self,
        case_id: str,
        *,
        expected_revision: int,
        status: str,
        operator_name: str,
        reason: str | None = None,
    ) -> dict[str, Any]:
        """Apply one deterministic lifecycle edge with revision fencing."""

        if status not in DECISION_CASE_STATES:
            raise ValueError(f"unknown decision case status: {status}")
        operator = _bounded_text(
            operator_name, field="operator_name", maximum=200
        )
        normalized_reason = _optional_bounded_text(
            reason, field="reason", maximum=2_000
        )
        now_text = _timestamp(self._current_time())
        with self._transaction(write=True) as connection:
            current = self._require_decision_case_row(connection, str(case_id))
            self._require_case_revision(current, expected_revision)
            current_status = str(current["status"])
            if current_status == status:
                return self._decision_case_from_row(current)  # type: ignore[return-value]
            if status not in DECISION_CASE_TRANSITIONS[current_status]:
                raise InvalidStateTransition(
                    f"cannot move decision case from {current_status} to {status}"
                )
            archived_at = now_text if status == "archived" else None
            try:
                cursor = connection.execute(
                    """
                    UPDATE decision_cases
                       SET status = ?, archived_at = ?, revision = revision + 1,
                           updated_at = ?, updated_by = ?
                     WHERE case_id = ? AND revision = ?
                    """,
                    (
                        status,
                        archived_at,
                        now_text,
                        operator,
                        str(case_id),
                        expected_revision,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise InvalidStateTransition(
                    f"cannot move decision case from {current_status} to {status}"
                ) from exc
            if cursor.rowcount != 1:
                raise StoreConflict("decision case changed during transition")
            updated = connection.execute(
                "SELECT * FROM decision_cases WHERE case_id = ?",
                (str(case_id),),
            ).fetchone()
            assert updated is not None
            self._insert_decision_event(
                connection,
                case_id=str(case_id),
                event_type=(
                    "decision_case_archived"
                    if status == "archived"
                    else "decision_case_transitioned"
                ),
                actor_kind="operator",
                operator_name=operator,
                payload={
                    "from_status": current_status,
                    "to_status": status,
                    "reason": normalized_reason,
                    "revision": int(updated["revision"]),
                },
                created_at=now_text,
            )
        return self._decision_case_from_row(updated)  # type: ignore[return-value]

    def archive_decision_case(
        self,
        case_id: str,
        *,
        expected_revision: int,
        operator_name: str,
        reason: str | None = None,
    ) -> dict[str, Any]:
        return self.transition_decision_case(
            case_id,
            expected_revision=expected_revision,
            status="archived",
            operator_name=operator_name,
            reason=reason,
        )

    def create_decision_turn(
        self,
        case_id: str,
        *,
        client_message_id: str,
        user_message: str,
        operator_name: str,
        expected_revision: int | None = None,
        turn_id: str | None = None,
    ) -> dict[str, Any]:
        """Persist one user message exactly once for an idempotent agent turn."""

        normalized_turn_id = str(turn_id or _new_id("dturn")).strip()
        if not normalized_turn_id.startswith("dturn_") or len(normalized_turn_id) <= 6:
            raise ValueError("decision turn ids must use the 'dturn_' prefix")
        client_id = _bounded_text(
            client_message_id,
            field="client_message_id",
            maximum=200,
        )
        message_text = _bounded_text(
            user_message,
            field="user_message",
            maximum=32_000,
        )
        operator = _bounded_text(
            operator_name, field="operator_name", maximum=200
        )
        now_text = _timestamp(self._current_time())
        with self._transaction(write=True) as connection:
            existing = connection.execute(
                """
                SELECT * FROM decision_agent_turns
                 WHERE case_id = ? AND client_message_id = ?
                """,
                (str(case_id), client_id),
            ).fetchone()
            if existing is not None:
                existing_message = connection.execute(
                    """
                    SELECT * FROM decision_messages
                     WHERE turn_id = ? AND role = 'user'
                    """,
                    (existing["turn_id"],),
                ).fetchone()
                if (
                    existing_message is None
                    or existing_message["content_text"] != message_text
                    or existing_message["operator_name"] != operator
                ):
                    raise StoreConflict(
                        "client_message_id already identifies a different user message"
                    )
                return self._decision_turn_bundle(connection, existing)

            case = self._require_decision_case_row(
                connection, str(case_id), mutable=True
            )
            self._require_case_revision(case, expected_revision)
            message_id = _new_id("dmsg")
            sequence = self._next_decision_message_sequence(
                connection, str(case_id)
            )
            try:
                connection.execute(
                    """
                    INSERT INTO decision_agent_turns (
                        turn_id, case_id, client_message_id, state, created_by,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, 'pending', ?, ?, ?)
                    """,
                    (
                        normalized_turn_id,
                        str(case_id),
                        client_id,
                        operator,
                        now_text,
                        now_text,
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO decision_messages (
                        message_id, case_id, turn_id, message_sequence, role,
                        status, content_text, structured_output_json,
                        citations_json, tool_outcomes_json, trace_id,
                        operator_name, error_code, created_at
                    ) VALUES (
                        ?, ?, ?, ?, 'user', 'complete', ?, NULL,
                        '[]', '[]', NULL, ?, NULL, ?
                    )
                    """,
                    (
                        message_id,
                        str(case_id),
                        normalized_turn_id,
                        sequence,
                        message_text,
                        operator,
                        now_text,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise StoreConflict("could not create decision agent turn") from exc
            updated_case = self._touch_decision_case(
                connection,
                case,
                now_text=now_text,
                operator_name=operator,
            )
            self._insert_decision_event(
                connection,
                case_id=str(case_id),
                turn_id=normalized_turn_id,
                event_type="decision_turn_created",
                actor_kind="operator",
                operator_name=operator,
                payload={
                    "turn_id": normalized_turn_id,
                    "message_id": message_id,
                    "client_message_id": client_id,
                    "status": "pending",
                    "case_revision": int(updated_case["revision"]),
                },
                created_at=now_text,
            )
            row = connection.execute(
                "SELECT * FROM decision_agent_turns WHERE turn_id = ?",
                (normalized_turn_id,),
            ).fetchone()
            assert row is not None
            return self._decision_turn_bundle(connection, row)

    def get_decision_turn(self, turn_id: str) -> dict[str, Any] | None:
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT * FROM decision_agent_turns WHERE turn_id = ?",
                (str(turn_id),),
            ).fetchone()
            if row is None:
                return None
            return self._decision_turn_bundle(connection, row)

    def claim_decision_turn(
        self,
        turn_id: str,
        *,
        worker_id: str,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        """Claim a pending turn once and return its fenced private token."""

        worker = _bounded_text(worker_id, field="worker_id", maximum=200)
        normalized_trace_id = _optional_bounded_text(
            trace_id, field="trace_id", maximum=200
        )
        now_text = _timestamp(self._current_time())
        with self._transaction(write=True) as connection:
            row = connection.execute(
                "SELECT * FROM decision_agent_turns WHERE turn_id = ?",
                (str(turn_id),),
            ).fetchone()
            if row is None:
                raise RecordNotFound(f"unknown decision turn: {turn_id}")
            if row["state"] == "claimed" and row["worker_id"] == worker:
                if (
                    normalized_trace_id is not None
                    and row["trace_id"] is not None
                    and row["trace_id"] != normalized_trace_id
                ):
                    raise StoreConflict("decision turn trace id changed")
                return self._decision_turn_bundle(connection, row)
            if row["state"] != "pending":
                raise InvalidStateTransition(
                    f"cannot claim decision turn in state {row['state']}"
                )
            case = self._require_decision_case_row(
                connection, str(row["case_id"]), mutable=True
            )
            claim_token = secrets.token_hex(32)
            try:
                cursor = connection.execute(
                    """
                    UPDATE decision_agent_turns
                       SET state = 'claimed', worker_id = ?, claim_token = ?,
                           trace_id = ?, claimed_at = ?, updated_at = ?
                     WHERE turn_id = ? AND state = 'pending'
                    """,
                    (
                        worker,
                        claim_token,
                        normalized_trace_id,
                        now_text,
                        now_text,
                        str(turn_id),
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise StoreConflict("could not claim decision turn") from exc
            if cursor.rowcount != 1:
                raise StoreConflict("decision turn was claimed concurrently")
            updated_case = self._touch_decision_case(
                connection,
                case,
                now_text=now_text,
                operator_name=f"decision-agent:{worker}"[:200],
            )
            self._insert_decision_event(
                connection,
                case_id=str(row["case_id"]),
                turn_id=str(turn_id),
                event_type="decision_turn_claimed",
                actor_kind="decision_agent",
                trace_id=normalized_trace_id,
                payload={
                    "turn_id": str(turn_id),
                    "status": "claimed",
                    "case_revision": int(updated_case["revision"]),
                },
                created_at=now_text,
            )
            updated = connection.execute(
                "SELECT * FROM decision_agent_turns WHERE turn_id = ?",
                (str(turn_id),),
            ).fetchone()
            assert updated is not None
            return self._decision_turn_bundle(connection, updated)

    @staticmethod
    def _validate_decision_turn_lease(
        row: sqlite3.Row,
        *,
        worker_id: str,
        claim_token: str,
    ) -> None:
        if row["worker_id"] != worker_id or not secrets.compare_digest(
            str(row["claim_token"] or ""), claim_token
        ):
            raise LeaseOwnershipLost(
                f"runner no longer owns decision turn {row['turn_id']}"
            )

    def complete_decision_turn(
        self,
        turn_id: str,
        *,
        worker_id: str,
        claim_token: str,
        assistant_message: str,
        structured_output: Mapping[str, Any] | None,
        citations: Sequence[Mapping[str, Any]] = (),
        tool_outcomes: Sequence[Mapping[str, Any]] = (),
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        """Atomically persist the final assistant message and replayable event."""

        worker = _bounded_text(worker_id, field="worker_id", maximum=200)
        token = _bounded_text(claim_token, field="claim_token", maximum=200)
        message_text = _bounded_text(
            assistant_message,
            field="assistant_message",
            maximum=100_000,
        )
        structured_json = (
            None if structured_output is None else _json_dump(dict(structured_output))
        )
        citations_json = _json_dump([dict(item) for item in citations])
        outcomes_json = _json_dump([dict(item) for item in tool_outcomes])
        normalized_trace_id = _optional_bounded_text(
            trace_id, field="trace_id", maximum=200
        )
        now_text = _timestamp(self._current_time())
        with self._transaction(write=True) as connection:
            row = connection.execute(
                "SELECT * FROM decision_agent_turns WHERE turn_id = ?",
                (str(turn_id),),
            ).fetchone()
            if row is None:
                raise RecordNotFound(f"unknown decision turn: {turn_id}")
            if row["state"] == "completed":
                self._validate_decision_turn_lease(
                    row, worker_id=worker, claim_token=token
                )
                existing = connection.execute(
                    """
                    SELECT * FROM decision_messages
                     WHERE turn_id = ? AND role = 'assistant'
                    """,
                    (str(turn_id),),
                ).fetchone()
                if (
                    existing is None
                    or existing["content_text"] != message_text
                    or existing["structured_output_json"] != structured_json
                    or existing["citations_json"] != citations_json
                    or existing["tool_outcomes_json"] != outcomes_json
                ):
                    raise StoreConflict(
                        "completed decision turn has a different assistant response"
                    )
                return self._decision_turn_bundle(connection, row)
            if row["state"] != "claimed":
                raise InvalidStateTransition(
                    f"cannot complete decision turn in state {row['state']}"
                )
            self._validate_decision_turn_lease(
                row, worker_id=worker, claim_token=token
            )
            effective_trace_id = normalized_trace_id or row["trace_id"]
            if (
                normalized_trace_id is not None
                and row["trace_id"] is not None
                and normalized_trace_id != row["trace_id"]
            ):
                raise StoreConflict("decision turn trace id changed")
            case = self._require_decision_case_row(
                connection, str(row["case_id"]), mutable=True
            )
            message_id = _new_id("dmsg")
            sequence = self._next_decision_message_sequence(
                connection, str(row["case_id"])
            )
            try:
                connection.execute(
                    """
                    INSERT INTO decision_messages (
                        message_id, case_id, turn_id, message_sequence, role,
                        status, content_text, structured_output_json,
                        citations_json, tool_outcomes_json, trace_id,
                        operator_name, error_code, created_at
                    ) VALUES (
                        ?, ?, ?, ?, 'assistant', 'complete', ?, ?, ?, ?, ?,
                        NULL, NULL, ?
                    )
                    """,
                    (
                        message_id,
                        row["case_id"],
                        str(turn_id),
                        sequence,
                        message_text,
                        structured_json,
                        citations_json,
                        outcomes_json,
                        effective_trace_id,
                        now_text,
                    ),
                )
                connection.execute(
                    """
                    UPDATE decision_agent_turns
                       SET state = 'completed', trace_id = ?, completed_at = ?,
                           updated_at = ?
                     WHERE turn_id = ? AND state = 'claimed'
                    """,
                    (effective_trace_id, now_text, now_text, str(turn_id)),
                )
            except sqlite3.IntegrityError as exc:
                raise StoreConflict("could not complete decision turn") from exc
            updated_case = self._touch_decision_case(
                connection,
                case,
                now_text=now_text,
                operator_name=f"decision-agent:{worker}"[:200],
            )
            self._insert_decision_event(
                connection,
                case_id=str(row["case_id"]),
                turn_id=str(turn_id),
                event_type="decision_turn_completed",
                actor_kind="decision_agent",
                trace_id=effective_trace_id,
                payload={
                    "turn_id": str(turn_id),
                    "status": "completed",
                    "message": {
                        "message_id": message_id,
                        "content": message_text,
                        "structured_output": _json_load(structured_json),
                        "citations": _json_load(citations_json),
                        "trace_id": effective_trace_id,
                    },
                    "case_revision": int(updated_case["revision"]),
                },
                created_at=now_text,
            )
            updated = connection.execute(
                "SELECT * FROM decision_agent_turns WHERE turn_id = ?",
                (str(turn_id),),
            ).fetchone()
            assert updated is not None
            return self._decision_turn_bundle(connection, updated)

    def fail_decision_turn(
        self,
        turn_id: str,
        *,
        worker_id: str,
        claim_token: str,
        assistant_message: str,
        error_code: str,
        error_detail: str,
        structured_output: Mapping[str, Any] | None = None,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        """Atomically persist one sanitized terminal failure and error message."""

        worker = _bounded_text(worker_id, field="worker_id", maximum=200)
        token = _bounded_text(claim_token, field="claim_token", maximum=200)
        message_text = _bounded_text(
            assistant_message,
            field="assistant_message",
            maximum=100_000,
        )
        code = _bounded_text(error_code, field="error_code", maximum=200)
        detail = _bounded_text(error_detail, field="error_detail", maximum=4_000)
        structured_json = (
            None if structured_output is None else _json_dump(dict(structured_output))
        )
        normalized_trace_id = _optional_bounded_text(
            trace_id, field="trace_id", maximum=200
        )
        now_text = _timestamp(self._current_time())
        with self._transaction(write=True) as connection:
            row = connection.execute(
                "SELECT * FROM decision_agent_turns WHERE turn_id = ?",
                (str(turn_id),),
            ).fetchone()
            if row is None:
                raise RecordNotFound(f"unknown decision turn: {turn_id}")
            if row["state"] == "failed":
                self._validate_decision_turn_lease(
                    row, worker_id=worker, claim_token=token
                )
                existing = connection.execute(
                    """
                    SELECT * FROM decision_messages
                     WHERE turn_id = ? AND role = 'assistant'
                    """,
                    (str(turn_id),),
                ).fetchone()
                if (
                    existing is None
                    or existing["content_text"] != message_text
                    or existing["error_code"] != code
                    or row["error_detail"] != detail
                    or existing["structured_output_json"] != structured_json
                ):
                    raise StoreConflict(
                        "failed decision turn has a different terminal response"
                    )
                return self._decision_turn_bundle(connection, row)
            if row["state"] != "claimed":
                raise InvalidStateTransition(
                    f"cannot fail decision turn in state {row['state']}"
                )
            self._validate_decision_turn_lease(
                row, worker_id=worker, claim_token=token
            )
            effective_trace_id = normalized_trace_id or row["trace_id"]
            if (
                normalized_trace_id is not None
                and row["trace_id"] is not None
                and normalized_trace_id != row["trace_id"]
            ):
                raise StoreConflict("decision turn trace id changed")
            case = self._require_decision_case_row(
                connection, str(row["case_id"]), mutable=True
            )
            message_id = _new_id("dmsg")
            sequence = self._next_decision_message_sequence(
                connection, str(row["case_id"])
            )
            try:
                connection.execute(
                    """
                    INSERT INTO decision_messages (
                        message_id, case_id, turn_id, message_sequence, role,
                        status, content_text, structured_output_json,
                        citations_json, tool_outcomes_json, trace_id,
                        operator_name, error_code, created_at
                    ) VALUES (
                        ?, ?, ?, ?, 'assistant', 'error', ?, ?, '[]', '[]', ?,
                        NULL, ?, ?
                    )
                    """,
                    (
                        message_id,
                        row["case_id"],
                        str(turn_id),
                        sequence,
                        message_text,
                        structured_json,
                        effective_trace_id,
                        code,
                        now_text,
                    ),
                )
                connection.execute(
                    """
                    UPDATE decision_agent_turns
                       SET state = 'failed', trace_id = ?, error_code = ?,
                           error_detail = ?, failed_at = ?, updated_at = ?
                     WHERE turn_id = ? AND state = 'claimed'
                    """,
                    (
                        effective_trace_id,
                        code,
                        detail,
                        now_text,
                        now_text,
                        str(turn_id),
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise StoreConflict("could not fail decision turn") from exc
            updated_case = self._touch_decision_case(
                connection,
                case,
                now_text=now_text,
                operator_name=f"decision-agent:{worker}"[:200],
            )
            self._insert_decision_event(
                connection,
                case_id=str(row["case_id"]),
                turn_id=str(turn_id),
                event_type="decision_turn_failed",
                actor_kind="decision_agent",
                trace_id=effective_trace_id,
                payload={
                    "turn_id": str(turn_id),
                    "status": "failed",
                    "message": {
                        "message_id": message_id,
                        "content": message_text,
                        "structured_output": _json_load(structured_json),
                        "trace_id": effective_trace_id,
                    },
                    "error": {"code": code, "detail": detail},
                    "case_revision": int(updated_case["revision"]),
                },
                created_at=now_text,
            )
            updated = connection.execute(
                "SELECT * FROM decision_agent_turns WHERE turn_id = ?",
                (str(turn_id),),
            ).fetchone()
            assert updated is not None
            return self._decision_turn_bundle(connection, updated)

    def mark_stale_claimed_decision_turns_failed(
        self,
        *,
        before: datetime,
        worker_id: str | None = None,
        recovery_reason: str = "stale_claim_after_process_restart",
        error_code: str = "agent_interrupted",
        error_detail: str = (
            "The Decision Agent process stopped before the response completed."
        ),
    ) -> int:
        """Fail bounded stale claims, optionally fenced to one exact worker."""

        if not isinstance(before, datetime):
            raise ValueError("before must be a datetime")
        cutoff_text = _timestamp(before)
        worker = _optional_bounded_text(
            worker_id, field="worker_id", maximum=200
        )
        reason = _bounded_text(
            recovery_reason, field="recovery_reason", maximum=200
        )
        code = _bounded_text(error_code, field="error_code", maximum=200)
        detail = _bounded_text(error_detail, field="error_detail", maximum=4_000)
        assistant_message = (
            "The Decision Agent was interrupted before it finished. "
            "Please retry your question."
        )
        now_text = _timestamp(self._current_time())
        recovered = 0
        with self._transaction(write=True) as connection:
            worker_clause = "" if worker is None else " AND worker_id = ?"
            parameters = (
                (cutoff_text,) if worker is None else (cutoff_text, worker)
            )
            stale_rows = connection.execute(
                f"""
                SELECT * FROM decision_agent_turns
                 WHERE state = 'claimed' AND claimed_at < ?{worker_clause}
                 ORDER BY claimed_at ASC, turn_id ASC
                """,
                parameters,
            ).fetchall()
            for row in stale_rows:
                existing_message = connection.execute(
                    """
                    SELECT 1 FROM decision_messages
                     WHERE turn_id = ? AND role = 'assistant'
                    """,
                    (row["turn_id"],),
                ).fetchone()
                if existing_message is not None:
                    raise StoreConflict(
                        "claimed decision turn already has an assistant message"
                    )
                case = self._require_decision_case_row(
                    connection, str(row["case_id"])
                )
                message_id = _new_id("dmsg")
                sequence = self._next_decision_message_sequence(
                    connection, str(row["case_id"])
                )
                try:
                    connection.execute(
                        """
                        INSERT INTO decision_messages (
                            message_id, case_id, turn_id, message_sequence, role,
                            status, content_text, structured_output_json,
                            citations_json, tool_outcomes_json, trace_id,
                            operator_name, error_code, created_at
                        ) VALUES (
                            ?, ?, ?, ?, 'assistant', 'error', ?, NULL,
                            '[]', '[]', ?, NULL, ?, ?
                        )
                        """,
                        (
                            message_id,
                            row["case_id"],
                            row["turn_id"],
                            sequence,
                            assistant_message,
                            row["trace_id"],
                            code,
                            now_text,
                        ),
                    )
                    cursor = connection.execute(
                        """
                        UPDATE decision_agent_turns
                           SET state = 'failed', error_code = ?, error_detail = ?,
                               failed_at = ?, updated_at = ?
                         WHERE turn_id = ? AND state = 'claimed'
                           AND worker_id = ? AND claim_token = ?
                        """,
                        (
                            code,
                            detail,
                            now_text,
                            now_text,
                            row["turn_id"],
                            row["worker_id"],
                            row["claim_token"],
                        ),
                    )
                except sqlite3.IntegrityError as exc:
                    raise StoreConflict(
                        "could not recover stale decision turn"
                    ) from exc
                if cursor.rowcount != 1:
                    raise StoreConflict(
                        "decision turn changed during stale-claim recovery"
                    )
                updated_case = self._touch_decision_case(
                    connection,
                    case,
                    now_text=now_text,
                    operator_name="system:decision-agent-recovery",
                )
                self._insert_decision_event(
                    connection,
                    case_id=str(row["case_id"]),
                    turn_id=str(row["turn_id"]),
                    event_type="decision_turn_failed",
                    actor_kind="system",
                    trace_id=row["trace_id"],
                    payload={
                        "turn_id": str(row["turn_id"]),
                        "status": "failed",
                        "message": {
                            "message_id": message_id,
                            "content": assistant_message,
                            "structured_output": None,
                            "trace_id": row["trace_id"],
                        },
                        "error": {"code": code, "detail": detail},
                        "recovery_reason": reason,
                        "case_revision": int(updated_case["revision"]),
                    },
                    created_at=now_text,
                )
                recovered += 1
        return recovered

    def list_decision_messages(
        self,
        case_id: str,
        *,
        limit: int = 20,
        before_message_sequence: int | None = None,
    ) -> list[dict[str, Any]]:
        """Return bounded chronological conversation context for one case."""

        if limit <= 0:
            return []
        if limit > 200:
            raise ValueError("decision message limit cannot exceed 200")
        parameters: list[Any] = [str(case_id)]
        before_clause = ""
        if before_message_sequence is not None:
            if (
                isinstance(before_message_sequence, bool)
                or not isinstance(before_message_sequence, int)
                or before_message_sequence <= 0
            ):
                raise ValueError("before_message_sequence must be a positive integer")
            before_clause = " AND message_sequence < ?"
            parameters.append(before_message_sequence)
        parameters.append(int(limit))
        with self._transaction() as connection:
            self._require_decision_case_row(connection, str(case_id))
            rows = connection.execute(
                "SELECT * FROM ("
                "SELECT * FROM decision_messages WHERE case_id = ?"
                + before_clause
                + " ORDER BY message_sequence DESC LIMIT ?"
                ") ORDER BY message_sequence ASC",
                parameters,
            ).fetchall()
        return [
            self._decision_message_from_row(row) for row in rows
        ]  # type: ignore[misc]

    def list_decision_events(
        self,
        case_id: str,
        *,
        after_event_sequence: int = 0,
        turn_id: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        """Replay ordered case or turn events strictly after a durable cursor."""

        if (
            isinstance(after_event_sequence, bool)
            or not isinstance(after_event_sequence, int)
            or after_event_sequence < 0
        ):
            raise ValueError("after_event_sequence must be a nonnegative integer")
        if limit <= 0:
            return []
        if limit > 1_000:
            raise ValueError("decision event limit cannot exceed 1000")
        clauses = ["case_id = ?", "event_sequence > ?"]
        parameters: list[Any] = [str(case_id), after_event_sequence]
        if turn_id is not None:
            clauses.append("turn_id = ?")
            parameters.append(str(turn_id))
        parameters.append(int(limit))
        with self._transaction() as connection:
            self._require_decision_case_row(connection, str(case_id))
            if turn_id is not None:
                owned = connection.execute(
                    """
                    SELECT 1 FROM decision_agent_turns
                     WHERE turn_id = ? AND case_id = ?
                    """,
                    (str(turn_id), str(case_id)),
                ).fetchone()
                if owned is None:
                    raise RecordNotFound(
                        f"unknown decision turn for case {case_id}: {turn_id}"
                    )
            rows = connection.execute(
                "SELECT * FROM decision_events WHERE "
                + " AND ".join(clauses)
                + " ORDER BY event_sequence ASC LIMIT ?",
                parameters,
            ).fetchall()
        return [
            self._decision_event_from_row(row) for row in rows
        ]  # type: ignore[misc]

    def create_decision_evidence_asset(
        self,
        case_id: str,
        *,
        original_filename: str,
        display_filename: str,
        media_type: str,
        sha256: str,
        byte_count: int,
        storage_key: str,
        evidence_class: str,
        operator_name: str,
        candidates: Sequence[Mapping[str, Any]] = (),
        extraction_status: str = "complete",
        extraction_metadata: Mapping[str, Any] | None = None,
        source_metadata: Mapping[str, Any] | None = None,
        declared_media_type: str | None = None,
        expected_revision: int | None = None,
        evidence_asset_id: str | None = None,
        max_file_bytes: int = DECISION_EVIDENCE_MAX_FILE_BYTES,
        max_files_per_case: int = DECISION_EVIDENCE_MAX_FILES_PER_CASE,
        max_case_bytes: int = DECISION_EVIDENCE_MAX_CASE_BYTES,
    ) -> dict[str, Any]:
        """Atomically register one verified blob and all extracted candidates."""

        asset_id = str(evidence_asset_id or _new_id("evi")).strip()
        if not asset_id.startswith("evi_") or len(asset_id) <= 4:
            raise ValueError("decision evidence ids must use the 'evi_' prefix")
        if evidence_class not in DECISION_EVIDENCE_CLASSES:
            raise ValueError("unsupported decision evidence class")
        filename = _bounded_text(
            original_filename, field="original_filename", maximum=255
        )
        display = _bounded_text(
            display_filename, field="display_filename", maximum=255
        )
        for field, value in (
            ("original_filename", filename),
            ("display_filename", display),
        ):
            if (
                value.startswith(".")
                or "/" in value
                or "\\" in value
                or any(ord(character) < 32 for character in value)
            ):
                raise ValueError(f"{field} is unsafe")
        detected_media_type = str(media_type).strip().lower()
        declared = str(declared_media_type or detected_media_type).strip().lower()
        if declared != detected_media_type:
            raise ValueError("declared and detected evidence media types differ")
        content_hash = self._validate_sha256(sha256, field="sha256")
        expected_storage_key, extension = _decision_evidence_storage_key(
            content_hash, detected_media_type
        )
        if str(storage_key).strip() != expected_storage_key:
            raise ValueError(
                "storage_key must be the canonical decision evidence content address"
            )
        if isinstance(byte_count, bool) or not isinstance(byte_count, int) or byte_count <= 0:
            raise ValueError("byte_count must be a positive integer")
        for field, value in (
            ("max_file_bytes", max_file_bytes),
            ("max_files_per_case", max_files_per_case),
            ("max_case_bytes", max_case_bytes),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{field} must be a positive integer")
        if byte_count > max_file_bytes:
            raise EvidenceLimitExceeded(
                f"decision evidence file exceeds {max_file_bytes} bytes"
            )
        if extraction_status not in {"complete", "not_supported", "failed"}:
            raise ValueError("unsupported evidence extraction status")
        if extraction_status != "complete" and candidates:
            raise ValueError("only complete extraction may include candidates")
        operator = _bounded_text(
            operator_name, field="operator_name", maximum=200
        )
        extraction_json = _json_dump(dict(extraction_metadata or {}))
        source_json = _json_dump(dict(source_metadata or {}))
        now_text = _timestamp(self._current_time())

        normalized_candidates: list[dict[str, Any]] = []
        seen_candidate_ids: set[str] = set()
        for raw_candidate in candidates:
            if not isinstance(raw_candidate, Mapping):
                raise ValueError("each evidence candidate must be an object")
            candidate_id = str(
                raw_candidate.get("evidence_candidate_id") or _new_id("evc")
            ).strip()
            if not candidate_id.startswith("evc_") or len(candidate_id) <= 4:
                raise ValueError("evidence candidate ids must use the 'evc_' prefix")
            if candidate_id in seen_candidate_ids:
                raise ValueError("evidence candidate ids must be unique")
            seen_candidate_ids.add(candidate_id)
            field_name = _bounded_text(
                raw_candidate.get("field_name"),
                field="candidate field_name",
                maximum=300,
            )
            unit = _optional_bounded_text(
                raw_candidate.get("unit"),
                field="candidate unit",
                maximum=100,
            )
            confidence = raw_candidate.get("confidence")
            if (
                isinstance(confidence, bool)
                or not isinstance(confidence, (int, float))
                or not math.isfinite(float(confidence))
                or not 0 <= float(confidence) <= 1
            ):
                raise ValueError("candidate confidence must be between zero and one")
            source_location = raw_candidate.get("source_location")
            if not isinstance(source_location, Mapping):
                raise ValueError("candidate source_location must be an object")
            normalized_candidates.append(
                {
                    "id": candidate_id,
                    "field_name": field_name,
                    "value_json": _json_dump(raw_candidate.get("value")),
                    "unit": unit,
                    "confidence": float(confidence),
                    "source_location_json": _json_dump(dict(source_location)),
                }
            )

        with self._transaction(write=True) as connection:
            case = self._require_decision_case_row(
                connection, str(case_id), mutable=True
            )
            self._require_case_revision(case, expected_revision)
            usage = connection.execute(
                """
                SELECT COUNT(*) AS file_count,
                       COALESCE(SUM(byte_count), 0) AS byte_count
                  FROM decision_evidence_assets
                 WHERE case_id = ? AND removed_at IS NULL
                """,
                (str(case_id),),
            ).fetchone()
            if int(usage["file_count"]) + 1 > max_files_per_case:
                raise EvidenceLimitExceeded(
                    f"decision case cannot contain more than {max_files_per_case} files"
                )
            if int(usage["byte_count"]) + byte_count > max_case_bytes:
                raise EvidenceLimitExceeded(
                    f"decision case evidence exceeds {max_case_bytes} bytes"
                )
            try:
                connection.execute(
                    """
                    INSERT INTO decision_evidence_assets (
                        evidence_asset_id, case_id, evidence_class,
                        original_filename, display_filename,
                        declared_media_type, detected_media_type,
                        canonical_extension, sha256, byte_count, storage_key,
                        extraction_status, extraction_metadata_json,
                        source_metadata_json, uploaded_by, uploaded_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        asset_id,
                        str(case_id),
                        evidence_class,
                        filename,
                        display,
                        declared,
                        detected_media_type,
                        extension,
                        content_hash,
                        byte_count,
                        expected_storage_key,
                        extraction_status,
                        extraction_json,
                        source_json,
                        operator,
                        now_text,
                    ),
                )
                for candidate in normalized_candidates:
                    connection.execute(
                        """
                        INSERT INTO decision_evidence_candidates (
                            evidence_candidate_id, evidence_asset_id, case_id,
                            field_name, value_json, unit, confidence,
                            source_location_json, extracted_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            candidate["id"],
                            asset_id,
                            str(case_id),
                            candidate["field_name"],
                            candidate["value_json"],
                            candidate["unit"],
                            candidate["confidence"],
                            candidate["source_location_json"],
                            now_text,
                        ),
                    )
            except sqlite3.IntegrityError as exc:
                raise StoreConflict("could not register decision evidence") from exc
            updated_case = self._touch_decision_case(
                connection,
                case,
                now_text=now_text,
                operator_name=operator,
            )
            self._insert_decision_event(
                connection,
                case_id=str(case_id),
                event_type="decision_evidence_uploaded",
                actor_kind="operator",
                operator_name=operator,
                payload={
                    "evidence_asset_id": asset_id,
                    "sha256": content_hash,
                    "byte_count": byte_count,
                    "media_type": detected_media_type,
                    "evidence_class": evidence_class,
                    "candidate_count": len(normalized_candidates),
                    "case_revision": int(updated_case["revision"]),
                },
                created_at=now_text,
            )
            row = connection.execute(
                """
                SELECT * FROM decision_evidence_assets
                 WHERE evidence_asset_id = ?
                """,
                (asset_id,),
            ).fetchone()
            assert row is not None
            return self._decision_evidence_asset_bundle(connection, row)

    def get_decision_evidence_asset(
        self,
        evidence_asset_id: str,
    ) -> dict[str, Any] | None:
        with self._transaction() as connection:
            row = connection.execute(
                """
                SELECT * FROM decision_evidence_assets
                 WHERE evidence_asset_id = ?
                """,
                (str(evidence_asset_id),),
            ).fetchone()
            if row is None:
                return None
            return self._decision_evidence_asset_bundle(connection, row)

    def list_decision_evidence_assets(
        self,
        case_id: str,
        *,
        include_removed: bool = False,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        if limit <= 0:
            return []
        if limit > 500:
            raise ValueError("decision evidence limit cannot exceed 500")
        removed_clause = "" if include_removed else " AND removed_at IS NULL"
        with self._transaction() as connection:
            self._require_decision_case_row(connection, str(case_id))
            rows = connection.execute(
                "SELECT * FROM decision_evidence_assets WHERE case_id = ?"
                + removed_clause
                + " ORDER BY uploaded_at DESC, evidence_asset_id DESC LIMIT ?",
                (str(case_id), int(limit)),
            ).fetchall()
            return [
                self._decision_evidence_asset_bundle(connection, row) for row in rows
            ]

    def decision_evidence_storage_is_referenced(
        self,
        storage_key: str,
        *,
        exclude_evidence_asset_id: str | None = None,
    ) -> bool:
        """Return whether verified private bytes must still be retained."""

        key = _bounded_text(storage_key, field="storage_key", maximum=500)
        with self._transaction() as connection:
            row = connection.execute(
                """
                SELECT 1
                  FROM decision_evidence_assets a
                 WHERE a.storage_key = ?
                   AND (
                        (
                            a.removed_at IS NULL
                            AND (? IS NULL OR a.evidence_asset_id <> ?)
                        )
                        OR EXISTS (
                            SELECT 1 FROM decision_evidence_receipts r
                             WHERE r.evidence_asset_id = a.evidence_asset_id
                               AND r.decision = 'accepted'
                        )
                   )
                 LIMIT 1
                """,
                (
                    key,
                    exclude_evidence_asset_id,
                    exclude_evidence_asset_id,
                ),
            ).fetchone()
        return row is not None

    def tombstone_decision_evidence_asset(
        self,
        evidence_asset_id: str,
        *,
        operator_name: str,
        reason: str,
        expected_revision: int | None = None,
    ) -> dict[str, Any]:
        """Tombstone unaccepted evidence while retaining immutable audit rows."""

        operator = _bounded_text(
            operator_name, field="operator_name", maximum=200
        )
        normalized_reason = _bounded_text(reason, field="reason", maximum=2_000)
        now_text = _timestamp(self._current_time())
        with self._transaction(write=True) as connection:
            row = connection.execute(
                """
                SELECT * FROM decision_evidence_assets
                 WHERE evidence_asset_id = ?
                """,
                (str(evidence_asset_id),),
            ).fetchone()
            if row is None:
                raise RecordNotFound(
                    f"unknown decision evidence: {evidence_asset_id}"
                )
            if row["removed_at"] is not None:
                return self._decision_evidence_asset_bundle(connection, row)
            case = self._require_decision_case_row(
                connection, str(row["case_id"]), mutable=True
            )
            self._require_case_revision(case, expected_revision)
            accepted = connection.execute(
                """
                SELECT evidence_receipt_id FROM decision_evidence_receipts
                 WHERE evidence_asset_id = ? AND decision = 'accepted'
                 LIMIT 1
                """,
                (str(evidence_asset_id),),
            ).fetchone()
            if accepted is not None:
                raise InvalidStateTransition(
                    "accepted decision evidence cannot be removed"
                )
            try:
                connection.execute(
                    """
                    UPDATE decision_evidence_assets
                       SET removed_by = ?, removed_reason = ?, removed_at = ?
                     WHERE evidence_asset_id = ? AND removed_at IS NULL
                    """,
                    (
                        operator,
                        normalized_reason,
                        now_text,
                        str(evidence_asset_id),
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise InvalidStateTransition(
                    "decision evidence cannot be removed"
                ) from exc
            self._mark_current_decision_outputs_stale(
                connection,
                case_id=str(row["case_id"]),
                reason={
                    "code": "decision_evidence_removed",
                    "evidence_asset_id": str(evidence_asset_id),
                },
                created_at=now_text,
            )
            updated_case = self._touch_decision_case(
                connection,
                case,
                now_text=now_text,
                operator_name=operator,
            )
            self._insert_decision_event(
                connection,
                case_id=str(row["case_id"]),
                event_type="decision_evidence_removed",
                actor_kind="operator",
                operator_name=operator,
                payload={
                    "evidence_asset_id": str(evidence_asset_id),
                    "reason": normalized_reason,
                    "case_revision": int(updated_case["revision"]),
                },
                created_at=now_text,
            )
            updated = connection.execute(
                """
                SELECT * FROM decision_evidence_assets
                 WHERE evidence_asset_id = ?
                """,
                (str(evidence_asset_id),),
            ).fetchone()
            assert updated is not None
            return self._decision_evidence_asset_bundle(connection, updated)

    def get_decision_evidence_receipt(
        self,
        evidence_receipt_id: str,
    ) -> dict[str, Any] | None:
        """Return one canonical evidence receipt without scanning case assets."""

        receipt_id = str(evidence_receipt_id).strip()
        with self._transaction() as connection:
            row = connection.execute(
                """
                SELECT * FROM decision_evidence_receipts
                 WHERE evidence_receipt_id = ?
                """,
                (receipt_id,),
            ).fetchone()
            if row is None:
                return None
            receipt_json = str(row["receipt_json"])
            if not secrets.compare_digest(
                str(row["receipt_sha256"]), _sha256_text(receipt_json)
            ):
                raise StoreConflict("decision evidence receipt digest is invalid")
            payload = _json_load(receipt_json)
            if not isinstance(payload, Mapping) or any(
                (
                    payload.get("evidence_receipt_id") != receipt_id,
                    payload.get("case_id") != row["case_id"],
                    payload.get("decision") != row["decision"],
                )
            ):
                raise StoreConflict("decision evidence receipt payload is invalid")
            if row["decision"] == "accepted":
                self._verify_decision_scenario_evidence_refs(
                    connection,
                    str(row["case_id"]),
                    [
                        {
                            "request_path": "/receipt-integrity-check",
                            "evidence_receipt_id": receipt_id,
                        }
                    ],
                )
            return self._decision_evidence_receipt_from_row(row)

    def record_decision_evidence_review(
        self,
        evidence_candidate_id: str,
        *,
        decision: str,
        operator_name: str,
        rationale: str | None = None,
        expected_revision: int | None = None,
        evidence_receipt_id: str | None = None,
    ) -> dict[str, Any]:
        """Append exactly one immutable acceptance or rejection receipt."""

        if decision not in DECISION_EVIDENCE_DECISIONS:
            raise ValueError("evidence decision must be accepted or rejected")
        operator = _bounded_text(
            operator_name, field="operator_name", maximum=200
        )
        normalized_rationale = _optional_bounded_text(
            rationale, field="rationale", maximum=4_000
        )
        receipt_id = str(evidence_receipt_id or _new_id("evr")).strip()
        if not receipt_id.startswith("evr_") or len(receipt_id) <= 4:
            raise ValueError("evidence receipt ids must use the 'evr_' prefix")
        now_text = _timestamp(self._current_time())
        with self._transaction(write=True) as connection:
            joined = connection.execute(
                """
                SELECT c.*, a.evidence_class, a.sha256 AS asset_sha256,
                       a.byte_count AS asset_byte_count,
                       a.detected_media_type, a.removed_at
                  FROM decision_evidence_candidates c
                  JOIN decision_evidence_assets a
                    ON a.evidence_asset_id = c.evidence_asset_id
                   AND a.case_id = c.case_id
                 WHERE c.evidence_candidate_id = ?
                """,
                (str(evidence_candidate_id),),
            ).fetchone()
            if joined is None:
                raise RecordNotFound(
                    f"unknown decision evidence candidate: {evidence_candidate_id}"
                )
            existing = connection.execute(
                """
                SELECT * FROM decision_evidence_receipts
                 WHERE evidence_candidate_id = ?
                """,
                (str(evidence_candidate_id),),
            ).fetchone()
            if existing is not None:
                if (
                    existing["decision"] == decision
                    and existing["operator_name"] == operator
                    and existing["rationale"] == normalized_rationale
                ):
                    return self._decision_evidence_receipt_from_row(
                        existing
                    )  # type: ignore[return-value]
                raise StoreConflict("evidence candidate was already reviewed")
            if joined["removed_at"] is not None:
                raise InvalidStateTransition("removed evidence cannot be reviewed")
            if (
                decision == "accepted"
                and joined["evidence_class"]
                in {"engineering_judgment", "secondary_synthesis"}
                and normalized_rationale is None
            ):
                raise ValueError("provisional evidence acceptance requires a rationale")
            case = self._require_decision_case_row(
                connection, str(joined["case_id"]), mutable=True
            )
            self._require_case_revision(case, expected_revision)
            receipt_payload = {
                "schema_version": 1,
                "preservation_mode": "server_managed_content_v1",
                "evidence_receipt_id": receipt_id,
                "case_id": str(joined["case_id"]),
                "evidence_asset_id": str(joined["evidence_asset_id"]),
                "evidence_candidate_id": str(evidence_candidate_id),
                "decision": decision,
                "evidence_class": str(joined["evidence_class"]),
                "candidate": {
                    "field_name": str(joined["field_name"]),
                    "value": _json_load(str(joined["value_json"])),
                    "unit": joined["unit"],
                    "confidence": float(joined["confidence"]),
                    "source_location": _json_load(
                        str(joined["source_location_json"])
                    ),
                },
                "content": {
                    "sha256": str(joined["asset_sha256"]),
                    "byte_count": int(joined["asset_byte_count"]),
                    "media_type": str(joined["detected_media_type"]),
                },
                "review": {
                    "operator_name": operator,
                    "rationale": normalized_rationale,
                    "reviewed_at": now_text,
                },
            }
            receipt_json = _json_dump(receipt_payload)
            receipt_hash = _sha256_text(receipt_json)
            try:
                connection.execute(
                    """
                    INSERT INTO decision_evidence_receipts (
                        evidence_receipt_id, evidence_candidate_id,
                        evidence_asset_id, case_id, decision, evidence_class,
                        field_name, value_json, unit, confidence,
                        source_location_json, asset_sha256, asset_byte_count,
                        preservation_mode, operator_name, rationale, reviewed_at,
                        receipt_json, receipt_sha256
                    ) VALUES (
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        'server_managed_content_v1', ?, ?, ?, ?, ?
                    )
                    """,
                    (
                        receipt_id,
                        str(evidence_candidate_id),
                        joined["evidence_asset_id"],
                        joined["case_id"],
                        decision,
                        joined["evidence_class"],
                        joined["field_name"],
                        joined["value_json"],
                        joined["unit"],
                        joined["confidence"],
                        joined["source_location_json"],
                        joined["asset_sha256"],
                        joined["asset_byte_count"],
                        operator,
                        normalized_rationale,
                        now_text,
                        receipt_json,
                        receipt_hash,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise StoreConflict("could not record evidence review") from exc
            self._mark_current_decision_outputs_stale(
                connection,
                case_id=str(joined["case_id"]),
                reason={
                    "code": "decision_evidence_receipt_created",
                    "evidence_receipt_id": receipt_id,
                    "evidence_asset_id": str(joined["evidence_asset_id"]),
                    "decision": decision,
                },
                created_at=now_text,
            )
            updated_case = self._touch_decision_case(
                connection,
                case,
                now_text=now_text,
                operator_name=operator,
            )
            self._insert_decision_event(
                connection,
                case_id=str(joined["case_id"]),
                event_type="decision_evidence_reviewed",
                actor_kind="operator",
                operator_name=operator,
                payload={
                    "evidence_receipt_id": receipt_id,
                    "evidence_asset_id": str(joined["evidence_asset_id"]),
                    "evidence_candidate_id": str(evidence_candidate_id),
                    "decision": decision,
                    "evidence_class": str(joined["evidence_class"]),
                    "receipt_sha256": receipt_hash,
                    "case_revision": int(updated_case["revision"]),
                },
                created_at=now_text,
            )
            receipt_row = connection.execute(
                """
                SELECT * FROM decision_evidence_receipts
                 WHERE evidence_receipt_id = ?
                """,
                (receipt_id,),
            ).fetchone()
            assert receipt_row is not None
            return self._decision_evidence_receipt_from_row(
                receipt_row
            )  # type: ignore[return-value]

    def create_decision_scenario(
        self,
        case_id: str,
        *,
        expected_case_revision: int,
        label: str,
        kind: str,
        request: Mapping[str, Any],
        request_sha256: str,
        changed_fields: Sequence[str],
        comparison_classification: str,
        evidence_receipt_refs: Sequence[str | Mapping[str, Any]],
        operator_name: str,
        scenario_id: str | None = None,
        scenario_revision_id: str | None = None,
        expires_at: datetime | None = None,
    ) -> dict[str, Any]:
        """Create a revision-one scenario draft against a locked decision case."""

        stable_id = str(scenario_id or _new_id("dsc")).strip()
        revision_id = str(scenario_revision_id or _new_id("dscr")).strip()
        if not stable_id.startswith("dsc_") or len(stable_id) <= 4:
            raise ValueError("scenario ids must use the 'dsc_' prefix")
        if not revision_id.startswith("dscr_") or len(revision_id) <= 5:
            raise ValueError("scenario revision ids must use the 'dscr_' prefix")
        operator = _bounded_text(operator_name, field="operator_name", maximum=200)
        prepared = self._prepare_decision_scenario_revision(
            label=label,
            kind=kind,
            request=request,
            request_sha256=request_sha256,
            changed_fields=changed_fields,
            comparison_classification=comparison_classification,
            evidence_receipt_refs=evidence_receipt_refs,
            expires_at=expires_at,
        )
        with self._transaction(write=True) as connection:
            case = self._require_decision_case_row(
                connection, str(case_id), mutable=True
            )
            self._require_case_revision(case, expected_case_revision)
            if case["source_annual_job_id"] is None:
                raise InvalidStateTransition(
                    "decision case source and analysis basis must be locked first"
                )
            request_payload = _json_load(prepared["request_json"])
            request_source_id = request_payload.get("source_annual_job_id")
            if (
                request_source_id is not None
                and request_source_id != case["source_annual_job_id"]
            ):
                raise StoreConflict(
                    "scenario Annual source differs from the locked case; create a new case"
                )
            if request_payload.get("basis") != case["analysis_basis"]:
                raise StoreConflict(
                    "scenario analysis basis differs from the locked case; create a new case"
                )
            self._verify_decision_scenario_evidence_refs(
                connection, str(case_id), prepared["evidence_receipt_refs"]
            )
            try:
                connection.execute(
                    """
                    INSERT INTO decision_scenarios (
                        scenario_revision_id, scenario_id, case_id, label, kind,
                        revision, parent_revision_id, superseded_by_revision_id,
                        status, request_json, request_sha256, changed_fields_json,
                        comparison_classification, validation_json,
                        validation_sha256, source_annual_job_id,
                        source_snapshot_sha256, analysis_basis, confirmation_id,
                        created_by, updated_by, created_at, updated_at, expires_at,
                        validated_at, confirmed_at, expired_at
                    ) VALUES (
                        ?, ?, ?, ?, ?, 1, NULL, NULL, 'draft', ?, ?, ?, ?,
                        NULL, NULL, ?, ?, ?, NULL, ?, ?, ?, ?, ?, NULL, NULL, NULL
                    )
                    """,
                    (
                        revision_id,
                        stable_id,
                        str(case_id),
                        prepared["label"],
                        prepared["kind"],
                        prepared["request_json"],
                        prepared["request_sha256"],
                        prepared["changed_fields_json"],
                        prepared["comparison_classification"],
                        case["source_annual_job_id"],
                        case["source_snapshot_sha256"],
                        case["analysis_basis"],
                        operator,
                        operator,
                        prepared["now_text"],
                        prepared["now_text"],
                        prepared["expires_at"],
                    ),
                )
                for reference in prepared["evidence_receipt_refs"]:
                    connection.execute(
                        """
                        INSERT INTO decision_scenario_evidence (
                            scenario_revision_id, request_path,
                            evidence_receipt_id, case_id, created_at
                        ) VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            revision_id,
                            reference["request_path"],
                            reference["evidence_receipt_id"],
                            str(case_id),
                            prepared["now_text"],
                        ),
                    )
            except sqlite3.IntegrityError as exc:
                raise StoreConflict("could not create decision scenario draft") from exc
            self._mark_current_decision_outputs_stale(
                connection,
                case_id=str(case_id),
                reason={
                    "code": "decision_scenario_revision_created",
                    "scenario_id": stable_id,
                    "scenario_revision_id": revision_id,
                    "scenario_revision": 1,
                },
                created_at=prepared["now_text"],
            )
            updated_case = self._touch_decision_case(
                connection,
                case,
                now_text=prepared["now_text"],
                operator_name=operator,
            )
            self._insert_decision_event(
                connection,
                case_id=str(case_id),
                event_type="decision_scenario_created",
                actor_kind="operator",
                operator_name=operator,
                payload={
                    "scenario_id": stable_id,
                    "scenario_revision_id": revision_id,
                    "scenario_revision": 1,
                    "kind": prepared["kind"],
                    "request_sha256": prepared["request_sha256"],
                    "case_revision": int(updated_case["revision"]),
                },
                created_at=prepared["now_text"],
            )
            row = self._require_decision_scenario_row(connection, revision_id)
            return self._decision_scenario_bundle(connection, row)

    def revise_decision_scenario(
        self,
        scenario_id: str,
        *,
        expected_case_revision: int,
        expected_revision: int,
        label: str,
        request: Mapping[str, Any],
        request_sha256: str,
        changed_fields: Sequence[str],
        comparison_classification: str,
        evidence_receipt_refs: Sequence[str | Mapping[str, Any]],
        operator_name: str,
        scenario_revision_id: str | None = None,
        expires_at: datetime | None = None,
    ) -> dict[str, Any]:
        """Supersede the current row and append a new immutable draft revision."""

        stable_id = str(scenario_id).strip()
        if not stable_id.startswith("dsc_") or len(stable_id) <= 4:
            raise ValueError("scenario ids must use the 'dsc_' prefix")
        revision_id = str(scenario_revision_id or _new_id("dscr")).strip()
        if not revision_id.startswith("dscr_") or len(revision_id) <= 5:
            raise ValueError("scenario revision ids must use the 'dscr_' prefix")
        operator = _bounded_text(operator_name, field="operator_name", maximum=200)
        self._expire_due_scenario_before_mutation(
            scenario_id=stable_id,
            operator_name=operator,
        )
        with self._transaction(write=True) as connection:
            parent = connection.execute(
                """
                SELECT * FROM decision_scenarios
                 WHERE scenario_id = ? AND superseded_by_revision_id IS NULL
                """,
                (stable_id,),
            ).fetchone()
            if parent is None:
                raise RecordNotFound(f"unknown current decision scenario: {stable_id}")
            self._require_decision_scenario_revision(parent, expected_revision)
            if parent["status"] == "expired":
                raise InvalidStateTransition("expired decision scenarios cannot be revised")
            case = self._require_decision_case_row(
                connection, str(parent["case_id"]), mutable=True
            )
            self._require_case_revision(case, expected_case_revision)
            prepared = self._prepare_decision_scenario_revision(
                label=label,
                kind=str(parent["kind"]),
                request=request,
                request_sha256=request_sha256,
                changed_fields=changed_fields,
                comparison_classification=comparison_classification,
                evidence_receipt_refs=evidence_receipt_refs,
                expires_at=expires_at,
            )
            request_payload = _json_load(prepared["request_json"])
            request_source_id = request_payload.get("source_annual_job_id")
            if (
                request_source_id is not None
                and request_source_id != case["source_annual_job_id"]
            ):
                raise StoreConflict(
                    "scenario Annual source differs from the locked case; create a new case"
                )
            if request_payload.get("basis") != case["analysis_basis"]:
                raise StoreConflict(
                    "scenario analysis basis differs from the locked case; create a new case"
                )
            self._verify_decision_scenario_evidence_refs(
                connection,
                str(parent["case_id"]),
                prepared["evidence_receipt_refs"],
            )
            next_revision = int(parent["revision"]) + 1
            pending_supersession_id = (
                "dscr_pending_" + revision_id.removeprefix("dscr_")
            )
            try:
                connection.execute(
                    """
                    INSERT INTO decision_scenarios (
                        scenario_revision_id, scenario_id, case_id, label, kind,
                        revision, parent_revision_id, superseded_by_revision_id,
                        status, request_json, request_sha256, changed_fields_json,
                        comparison_classification, validation_json,
                        validation_sha256, source_annual_job_id,
                        source_snapshot_sha256, analysis_basis, confirmation_id,
                        created_by, updated_by, created_at, updated_at, expires_at,
                        validated_at, confirmed_at, expired_at
                    ) VALUES (
                        ?, ?, ?, ?, ?, ?, ?, ?, 'draft', ?, ?, ?, ?,
                        NULL, NULL, ?, ?, ?, NULL, ?, ?, ?, ?, ?, NULL, NULL, NULL
                    )
                    """,
                    (
                        revision_id,
                        stable_id,
                        parent["case_id"],
                        prepared["label"],
                        parent["kind"],
                        next_revision,
                        parent["scenario_revision_id"],
                        pending_supersession_id,
                        prepared["request_json"],
                        prepared["request_sha256"],
                        prepared["changed_fields_json"],
                        prepared["comparison_classification"],
                        parent["source_annual_job_id"],
                        parent["source_snapshot_sha256"],
                        parent["analysis_basis"],
                        operator,
                        operator,
                        prepared["now_text"],
                        prepared["now_text"],
                        prepared["expires_at"],
                    ),
                )
                cursor = connection.execute(
                    """
                    UPDATE decision_scenarios
                       SET superseded_by_revision_id = ?
                     WHERE scenario_revision_id = ?
                       AND superseded_by_revision_id IS NULL
                       AND revision = ?
                    """,
                    (revision_id, parent["scenario_revision_id"], expected_revision),
                )
                if cursor.rowcount != 1:
                    raise StoreConflict("decision scenario changed during revision")
                cursor = connection.execute(
                    """
                    UPDATE decision_scenarios
                       SET superseded_by_revision_id = NULL
                     WHERE scenario_revision_id = ?
                       AND superseded_by_revision_id = ?
                    """,
                    (revision_id, pending_supersession_id),
                )
                if cursor.rowcount != 1:
                    raise StoreConflict("decision scenario revision was not activated")
                for reference in prepared["evidence_receipt_refs"]:
                    connection.execute(
                        """
                        INSERT INTO decision_scenario_evidence (
                            scenario_revision_id, request_path,
                            evidence_receipt_id, case_id, created_at
                        ) VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            revision_id,
                            reference["request_path"],
                            reference["evidence_receipt_id"],
                            parent["case_id"],
                            prepared["now_text"],
                        ),
                    )
            except sqlite3.IntegrityError as exc:
                raise StoreConflict("could not revise decision scenario") from exc
            self._mark_current_decision_outputs_stale(
                connection,
                case_id=str(parent["case_id"]),
                reason={
                    "code": "decision_scenario_revision_created",
                    "scenario_id": stable_id,
                    "scenario_revision_id": revision_id,
                    "scenario_revision": next_revision,
                    "parent_scenario_revision_id": parent[
                        "scenario_revision_id"
                    ],
                },
                created_at=prepared["now_text"],
            )
            updated_case = self._touch_decision_case(
                connection,
                case,
                now_text=prepared["now_text"],
                operator_name=operator,
            )
            self._insert_decision_event(
                connection,
                case_id=str(parent["case_id"]),
                event_type="decision_scenario_revised",
                actor_kind="operator",
                operator_name=operator,
                payload={
                    "scenario_id": stable_id,
                    "parent_scenario_revision_id": parent["scenario_revision_id"],
                    "scenario_revision_id": revision_id,
                    "scenario_revision": next_revision,
                    "request_sha256": prepared["request_sha256"],
                    "case_revision": int(updated_case["revision"]),
                },
                created_at=prepared["now_text"],
            )
            row = self._require_decision_scenario_row(connection, revision_id)
            return self._decision_scenario_bundle(connection, row)

    def record_decision_scenario_validation(
        self,
        scenario_revision_id: str,
        *,
        expected_case_revision: int,
        expected_revision: int,
        request_sha256: str,
        validation: Mapping[str, Any],
        valid: bool,
        operator_name: str,
    ) -> dict[str, Any]:
        """Freeze deterministic validation on the exact current request revision."""

        if not isinstance(valid, bool):
            raise ValueError("valid must be a boolean")
        if not isinstance(validation, Mapping):
            raise ValueError("validation must be an object")
        operator = _bounded_text(operator_name, field="operator_name", maximum=200)
        self._expire_due_scenario_before_mutation(
            scenario_revision_id=str(scenario_revision_id),
            operator_name=operator,
        )
        request_hash = self._validate_sha256(
            request_sha256, field="request_sha256"
        )
        validation_json = _json_dump(dict(validation))
        validation_hash = _sha256_text(validation_json)
        now_text = _timestamp(self._current_time())
        with self._transaction(write=True) as connection:
            row = self._require_decision_scenario_row(
                connection, scenario_revision_id, current=True
            )
            self._require_decision_scenario_revision(row, expected_revision)
            case = self._require_decision_case_row(
                connection, str(row["case_id"]), mutable=True
            )
            self._require_case_revision(case, expected_case_revision)
            if row["status"] != "draft":
                raise InvalidStateTransition(
                    f"cannot validate decision scenario in state {row['status']}"
                )
            if not secrets.compare_digest(str(row["request_sha256"]), request_hash):
                raise StoreConflict("scenario request changed before validation")
            if validation.get("valid") is not valid:
                raise ValueError(
                    "validation.valid must match the requested validation state"
                )
            if validation.get("request_sha256") != request_hash:
                raise StoreConflict(
                    "scenario validation must bind the exact canonical request hash"
                )
            stored_changed_fields = _json_load(str(row["changed_fields_json"]))
            if (
                validation.get("kind") != row["kind"]
                or validation.get("comparison_classification")
                != row["comparison_classification"]
                or validation.get("declared_changed_fields")
                != stored_changed_fields
            ):
                raise StoreConflict(
                    "scenario validation does not match the immutable draft metadata"
                )
            if valid and (
                validation.get("field_errors") != []
                or validation.get("changed_fields") != stored_changed_fields
            ):
                raise StoreConflict(
                    "valid scenario receipt does not prove its declared differences"
                )
            if row["kind"] == "alternative" and valid:
                self._validate_sha256(
                    str(validation.get("baseline_request_sha256") or ""),
                    field="baseline_request_sha256",
                )
            self._verify_decision_scenario_evidence_refs(
                connection,
                str(row["case_id"]),
                self._normalize_decision_scenario_evidence_refs(
                    [
                        {
                            "request_path": evidence["request_path"],
                            "evidence_receipt_id": evidence["evidence_receipt_id"],
                        }
                        for evidence in connection.execute(
                            """
                            SELECT request_path, evidence_receipt_id
                              FROM decision_scenario_evidence
                             WHERE scenario_revision_id = ?
                             ORDER BY request_path
                            """,
                            (scenario_revision_id,),
                        ).fetchall()
                    ]
                ),
            )
            target_status = "validated" if valid else "invalid"
            try:
                connection.execute(
                    """
                    UPDATE decision_scenarios
                       SET status = ?, validation_json = ?, validation_sha256 = ?,
                           validated_at = ?, updated_at = ?, updated_by = ?
                     WHERE scenario_revision_id = ? AND status = 'draft'
                    """,
                    (
                        target_status,
                        validation_json,
                        validation_hash,
                        now_text,
                        now_text,
                        operator,
                        scenario_revision_id,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise StoreConflict("could not record scenario validation") from exc
            updated_case = self._touch_decision_case(
                connection, case, now_text=now_text, operator_name=operator
            )
            self._insert_decision_event(
                connection,
                case_id=str(row["case_id"]),
                event_type="decision_scenario_validated",
                actor_kind="operator",
                operator_name=operator,
                payload={
                    "scenario_id": row["scenario_id"],
                    "scenario_revision_id": scenario_revision_id,
                    "scenario_revision": int(row["revision"]),
                    "status": target_status,
                    "request_sha256": request_hash,
                    "validation_sha256": validation_hash,
                    "case_revision": int(updated_case["revision"]),
                },
                created_at=now_text,
            )
            updated = self._require_decision_scenario_row(connection, scenario_revision_id)
            return self._decision_scenario_bundle(connection, updated)

    def get_decision_scenario(
        self, scenario_revision_id: str
    ) -> dict[str, Any] | None:
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT * FROM decision_scenarios WHERE scenario_revision_id = ?",
                (str(scenario_revision_id),),
            ).fetchone()
            return None if row is None else self._decision_scenario_bundle(connection, row)

    def list_decision_scenarios(
        self,
        case_id: str,
        *,
        include_history: bool = True,
        include_expired: bool = True,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        if limit <= 0:
            return []
        if limit > 500:
            raise ValueError("decision scenario limit cannot exceed 500")
        clauses = ["case_id = ?"]
        parameters: list[Any] = [str(case_id)]
        if not include_history:
            clauses.append("superseded_by_revision_id IS NULL")
        if not include_expired:
            clauses.append("status <> 'expired'")
        parameters.append(int(limit))
        with self._transaction() as connection:
            self._require_decision_case_row(connection, str(case_id))
            rows = connection.execute(
                "SELECT * FROM decision_scenarios WHERE "
                + " AND ".join(clauses)
                + " ORDER BY kind ASC, scenario_id ASC, revision DESC LIMIT ?",
                parameters,
            ).fetchall()
            return [self._decision_scenario_bundle(connection, row) for row in rows]

    def get_decision_scenario_confirmation(
        self, confirmation_id: str
    ) -> dict[str, Any] | None:
        with self._transaction() as connection:
            row = connection.execute(
                """
                SELECT * FROM decision_scenario_confirmations
                 WHERE confirmation_id = ?
                """,
                (str(confirmation_id),),
            ).fetchone()
            return (
                None
                if row is None
                else self._decision_scenario_confirmation_bundle(connection, row)
            )

    def get_decision_scenario_confirmation_by_idempotency(
        self,
        case_id: str,
        idempotency_key: str,
    ) -> dict[str, Any] | None:
        """Return the immutable replay record before any external byte recheck."""

        key = _bounded_text(
            idempotency_key, field="idempotency_key", maximum=200
        )
        with self._transaction() as connection:
            row = connection.execute(
                """
                SELECT c.*, i.response_json, i.response_sha256
                  FROM decision_scenario_confirmations c
                  JOIN decision_scenario_confirmation_idempotency i
                    ON i.confirmation_id = c.confirmation_id
                 WHERE c.case_id = ? AND c.idempotency_key = ?
                """,
                (str(case_id), key),
            ).fetchone()
            if row is None:
                return None
            result = self._decision_scenario_confirmation_bundle(connection, row)
            response_json = str(row["response_json"])
            if not secrets.compare_digest(
                str(row["response_sha256"]), _sha256_text(response_json)
            ):
                raise StoreConflict("scenario confirmation replay receipt is invalid")
            result["response"] = _json_load(response_json)
            return result

    def confirm_decision_scenarios_batch(
        self,
        case_id: str,
        confirmations: Sequence[Mapping[str, Any]],
        *,
        expected_case_revision: int,
        idempotency_key: str,
        operator_name: str,
        rationale: str,
        acknowledgement: str,
        confirmation_review: Mapping[str, Any],
        atomic_source_check: Callable[[sqlite3.Connection], str | None],
        max_active_jobs: int | None = None,
        confirmation_id: str | None = None,
    ) -> dict[str, Any]:
        """Confirm exact scenario revisions and create every TEA job or none."""

        if not confirmations or len(confirmations) > 4:
            raise ValueError("confirmations must select between one and four scenarios")
        if not isinstance(confirmation_review, Mapping):
            raise ValueError("confirmation_review must be an object")
        if not callable(atomic_source_check):
            raise ValueError("atomic_source_check is required")
        key = _bounded_text(idempotency_key, field="idempotency_key", maximum=200)
        operator = _bounded_text(operator_name, field="operator_name", maximum=200)
        normalized_rationale = _bounded_text(rationale, field="rationale", maximum=4_000)
        normalized_acknowledgement = _bounded_text(
            acknowledgement, field="acknowledgement", maximum=4_000
        )
        if (
            isinstance(expected_case_revision, bool)
            or not isinstance(expected_case_revision, int)
            or expected_case_revision <= 0
        ):
            raise ValueError("expected_case_revision must be a positive integer")
        normalized_confirmation_id = str(
            confirmation_id or _new_id("dconf")
        ).strip()
        if (
            not normalized_confirmation_id.startswith("dconf_")
            or len(normalized_confirmation_id) <= 6
        ):
            raise ValueError("confirmation ids must use the 'dconf_' prefix")

        prepared = [self._prepare_decision_scenario_tea_item(item) for item in confirmations]
        revision_ids = [item["scenario_revision_id"] for item in prepared]
        if len(set(revision_ids)) != len(revision_ids):
            raise ValueError("a scenario revision may be confirmed only once per batch")
        job_ids = [item["job_id"] for item in prepared]
        if len(set(job_ids)) != len(job_ids):
            raise ValueError("TEA job ids must be unique within a confirmation")

        confirmation_request = {
            "schema_version": 1,
            "case_id": str(case_id),
            "expected_case_revision": expected_case_revision,
            "idempotency_key": key,
            "operator_name": operator,
            "rationale": normalized_rationale,
            "acknowledgement": normalized_acknowledgement,
            "confirmation_review": dict(confirmation_review),
            "scenarios": [
                {
                    "scenario_revision_id": item["scenario_revision_id"],
                    "expected_revision": item["expected_revision"],
                    "request_sha256": item["request_sha256"],
                    "source_annual_job_id": item["source_annual_job_id"],
                    "source_artifact_sha256": item["source_artifact_sha256"],
                    "source_artifact_bytes": item["source_artifact_bytes"],
                    "source_snapshot_sha256": item["source_snapshot_sha256"],
                    "submission_provenance_sha256": item[
                        "submission_provenance_sha256"
                    ],
                }
                for item in prepared
            ],
        }
        confirmation_request_json = _json_dump(confirmation_request)
        confirmation_request_hash = _sha256_text(confirmation_request_json)
        now_text = _timestamp(self._current_time())

        # Persist every elapsed unconfirmed revision before evaluating the
        # confirmation fence. If anything expires, the case revision advances
        # and this browser confirmation becomes safely stale.
        with self._transaction() as connection:
            replay_exists = connection.execute(
                "SELECT 1 FROM decision_scenario_confirmation_idempotency "
                "WHERE case_id = ? AND idempotency_key = ?",
                (str(case_id), key),
            ).fetchone()
        if replay_exists is None:
            self.expire_decision_scenario_drafts(
                str(case_id),
                operator_name="system:scenario-expiry",
            )

        with self._transaction(write=True) as connection:
            replay = connection.execute(
                """
                SELECT * FROM decision_scenario_confirmation_idempotency
                 WHERE case_id = ? AND idempotency_key = ?
                """,
                (str(case_id), key),
            ).fetchone()
            if replay is not None:
                if not secrets.compare_digest(
                    str(replay["confirmation_request_sha256"]),
                    confirmation_request_hash,
                ):
                    raise StoreConflict(
                        "idempotency key was already used for a different confirmation"
                    )
                response_json = str(replay["response_json"])
                if not secrets.compare_digest(
                    str(replay["response_sha256"]), _sha256_text(response_json)
                ):
                    raise StoreConflict("scenario confirmation replay receipt is invalid")
                confirmation_row = connection.execute(
                    """
                    SELECT * FROM decision_scenario_confirmations
                     WHERE confirmation_id = ?
                    """,
                    (replay["confirmation_id"],),
                ).fetchone()
                assert confirmation_row is not None
                stored_response = _json_load(response_json)
                return {
                    "confirmation": self._decision_scenario_confirmation_bundle(
                        connection, confirmation_row
                    ),
                    "items": self._decision_scenario_confirmation_bundle(
                        connection, confirmation_row
                    )["items"],
                    "jobs": self._decision_scenario_confirmation_bundle(
                        connection, confirmation_row
                    )["jobs"],
                    "case": stored_response["case"],
                    "idempotent_replay": True,
                }

            case = self._require_decision_case_row(
                connection, str(case_id), mutable=True
            )
            self._require_case_revision(case, expected_case_revision)
            if case["status"] != "ready_to_run":
                raise InvalidStateTransition(
                    "decision case must be ready_to_run before scenario confirmation"
                )
            if case["source_annual_job_id"] is None:
                raise InvalidStateTransition("decision case source and basis are not locked")
            source = connection.execute(
                "SELECT mode, state FROM jobs WHERE job_id = ?",
                (case["source_annual_job_id"],),
            ).fetchone()
            if source is None:
                raise RecordNotFound(
                    f"unknown Annual Simulation source: {case['source_annual_job_id']}"
                )
            if source["mode"] != "annual" or source["state"] != "done":
                raise InvalidStateTransition(
                    "scenario source must remain a completed Annual Simulation"
                )

            scenario_rows: list[sqlite3.Row] = []
            baseline_count = 0
            evidence_by_revision: dict[str, list[dict[str, str]]] = {}
            validation_by_revision: dict[str, dict[str, Any]] = {}
            for item in prepared:
                row = self._require_decision_scenario_row(
                    connection, item["scenario_revision_id"], current=True
                )
                if row["case_id"] != str(case_id):
                    raise StoreConflict("cannot confirm scenarios from different cases")
                self._require_decision_scenario_revision(
                    row, int(item["expected_revision"])
                )
                if row["status"] != "validated":
                    raise InvalidStateTransition(
                        f"cannot confirm scenario in state {row['status']}"
                    )
                if str(row["expires_at"]) <= now_text:
                    raise InvalidStateTransition("decision scenario draft has expired")
                if not secrets.compare_digest(
                    str(row["request_sha256"]), item["request_sha256"]
                ) or str(row["request_json"]) != item["request_json"]:
                    raise StoreConflict("scenario request changed before confirmation")
                if (
                    row["source_annual_job_id"] != case["source_annual_job_id"]
                    or row["source_snapshot_sha256"]
                    != case["source_snapshot_sha256"]
                    or row["analysis_basis"] != case["analysis_basis"]
                    or item["source_annual_job_id"] != case["source_annual_job_id"]
                    or item["source_snapshot_sha256"]
                    != case["source_snapshot_sha256"]
                ):
                    raise StoreConflict(
                        "scenario source or basis differs from the locked case; create a new case"
                    )
                validation_json = str(row["validation_json"])
                if not secrets.compare_digest(
                    str(row["validation_sha256"]), _sha256_text(validation_json)
                ):
                    raise StoreConflict("scenario validation receipt digest is invalid")
                validation_payload = _json_load(validation_json)
                if (
                    not isinstance(validation_payload, Mapping)
                    or validation_payload.get("valid") is not True
                    or validation_payload.get("request_sha256")
                    != row["request_sha256"]
                    or validation_payload.get("kind") != row["kind"]
                    or validation_payload.get("comparison_classification")
                    != row["comparison_classification"]
                    or validation_payload.get("declared_changed_fields")
                    != _json_load(str(row["changed_fields_json"]))
                    or validation_payload.get("changed_fields")
                    != _json_load(str(row["changed_fields_json"]))
                    or validation_payload.get("field_errors") != []
                ):
                    raise StoreConflict(
                        "scenario validation receipt does not prove the frozen request"
                    )
                validation_by_revision[str(row["scenario_revision_id"])] = dict(
                    validation_payload
                )
                refs = [
                    {
                        "request_path": str(link["request_path"]),
                        "evidence_receipt_id": str(link["evidence_receipt_id"]),
                    }
                    for link in connection.execute(
                        """
                        SELECT request_path, evidence_receipt_id
                          FROM decision_scenario_evidence
                         WHERE scenario_revision_id = ?
                         ORDER BY request_path
                        """,
                        (row["scenario_revision_id"],),
                    ).fetchall()
                ]
                self._verify_decision_scenario_evidence_refs(
                    connection, str(case_id), refs
                )
                evidence_by_revision[str(row["scenario_revision_id"])] = refs
                baseline_count += int(row["kind"] == "baseline")
                scenario_rows.append(row)
            if baseline_count != 1:
                raise InvalidStateTransition(
                    "a grouped confirmation must include exactly one validated baseline"
                )
            baseline_row = next(
                row for row in scenario_rows if row["kind"] == "baseline"
            )
            baseline_request = _json_load(str(baseline_row["request_json"]))
            baseline_hash = str(baseline_row["request_sha256"])
            for row in scenario_rows:
                if row["kind"] != "alternative":
                    continue
                alternative_request = _json_load(str(row["request_json"]))
                validation_payload = validation_by_revision[
                    str(row["scenario_revision_id"])
                ]
                if (
                    validation_payload.get("baseline_request_sha256")
                    != baseline_hash
                    or alternative_request.get("n") != baseline_request.get("n")
                    or alternative_request.get("seed")
                    != baseline_request.get("seed")
                ):
                    raise StoreConflict(
                        "alternative validation does not match the selected baseline; "
                        "revalidate the alternative"
                    )

            self._ensure_queue_capacity(
                connection,
                max_active_jobs=max_active_jobs,
                required=len(prepared),
            )
            for job_id in job_ids:
                if connection.execute(
                    "SELECT 1 FROM technoeconomic_jobs WHERE tea_job_id = ?",
                    (job_id,),
                ).fetchone() is not None or connection.execute(
                    "SELECT 1 FROM jobs WHERE job_id = ?", (job_id,)
                ).fetchone() is not None:
                    raise StoreConflict(f"technoeconomic job id already exists: {job_id}")
            verified_snapshot_hash = atomic_source_check(connection)
            if not isinstance(verified_snapshot_hash, str) or not secrets.compare_digest(
                verified_snapshot_hash, str(case["source_snapshot_sha256"])
            ):
                raise StoreConflict(
                    "Annual Simulation source changed or does not match the locked case"
                )

            receipt_payload = {
                "schema_version": 1,
                "confirmation_id": normalized_confirmation_id,
                "case_id": str(case_id),
                "case_revision_before": expected_case_revision,
                "case_revision_after": expected_case_revision + 1,
                "source_lock": {
                    "source_annual_job_id": case["source_annual_job_id"],
                    "source_snapshot_sha256": case["source_snapshot_sha256"],
                    "analysis_basis": case["analysis_basis"],
                },
                "operator": {
                    "name": operator,
                    "rationale": normalized_rationale,
                    "acknowledgement": normalized_acknowledgement,
                },
                "confirmation_review": dict(confirmation_review),
                "scenarios": [
                    {
                        "scenario_id": row["scenario_id"],
                        "scenario_revision_id": row["scenario_revision_id"],
                        "scenario_revision": int(row["revision"]),
                        "kind": row["kind"],
                        "request_sha256": row["request_sha256"],
                        "evidence_receipt_refs": evidence_by_revision[
                            str(row["scenario_revision_id"])
                        ],
                        "tea_job_id": item["job_id"],
                    }
                    for item, row in zip(prepared, scenario_rows, strict=True)
                ],
                "confirmed_at": now_text,
            }
            receipt_json = _json_dump(receipt_payload)
            receipt_hash = _sha256_text(receipt_json)
            try:
                connection.execute(
                    """
                    INSERT INTO decision_scenario_confirmations (
                        confirmation_id, case_id, idempotency_key,
                        expected_case_revision, case_revision_after,
                        confirmation_request_json, confirmation_request_sha256,
                        receipt_json, receipt_sha256, operator_name, rationale,
                        acknowledgement, confirmed_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        normalized_confirmation_id,
                        str(case_id),
                        key,
                        expected_case_revision,
                        expected_case_revision + 1,
                        confirmation_request_json,
                        confirmation_request_hash,
                        receipt_json,
                        receipt_hash,
                        operator,
                        normalized_rationale,
                        normalized_acknowledgement,
                        now_text,
                    ),
                )
                for index, (item, row) in enumerate(
                    zip(prepared, scenario_rows, strict=True)
                ):
                    self._insert_technoeconomic_job(
                        connection,
                        job_id=item["job_id"],
                        request_json=item["request_json"],
                        source_annual_job_id=item["source_annual_job_id"],
                        source_artifact_storage_key=item[
                            "source_artifact_storage_key"
                        ],
                        source_artifact_sha256=item["source_artifact_sha256"],
                        source_artifact_bytes=item["source_artifact_bytes"],
                        source_snapshot_json=item["source_snapshot_json"],
                        source_snapshot_sha256=item["source_snapshot_sha256"],
                        submission_provenance_json=item[
                            "submission_provenance_json"
                        ],
                        submission_provenance_sha256=item[
                            "submission_provenance_sha256"
                        ],
                        retry_of_job_id=None,
                        now_text=now_text,
                    )
                    cursor = connection.execute(
                        """
                        UPDATE decision_scenarios
                           SET status = 'confirmed', confirmation_id = ?,
                               confirmed_at = ?, updated_at = ?, updated_by = ?
                         WHERE scenario_revision_id = ?
                           AND status = 'validated'
                           AND revision = ?
                        """,
                        (
                            normalized_confirmation_id,
                            now_text,
                            now_text,
                            operator,
                            row["scenario_revision_id"],
                            item["expected_revision"],
                        ),
                    )
                    if cursor.rowcount != 1:
                        raise StoreConflict("scenario changed during confirmation")
                    connection.execute(
                        """
                        INSERT INTO decision_scenario_confirmation_items (
                            confirmation_id, case_id, item_index,
                            scenario_revision_id, scenario_id,
                            scenario_revision, request_sha256, tea_job_id, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            normalized_confirmation_id,
                            str(case_id),
                            index,
                            row["scenario_revision_id"],
                            row["scenario_id"],
                            row["revision"],
                            row["request_sha256"],
                            item["job_id"],
                            now_text,
                        ),
                    )
                    connection.execute(
                        """
                        INSERT INTO decision_scenario_jobs (
                            tea_job_id, scenario_revision_id, case_id,
                            attempt_number, retry_of_job_id,
                            confirmation_id, created_at
                        ) VALUES (?, ?, ?, 1, NULL, ?, ?)
                        """,
                        (
                            item["job_id"],
                            row["scenario_revision_id"],
                            str(case_id),
                            normalized_confirmation_id,
                            now_text,
                        ),
                    )
                cursor = connection.execute(
                    """
                    UPDATE decision_cases
                       SET status = 'running', revision = revision + 1,
                           updated_at = ?, updated_by = ?
                     WHERE case_id = ? AND revision = ? AND status = 'ready_to_run'
                    """,
                    (now_text, operator, str(case_id), expected_case_revision),
                )
                if cursor.rowcount != 1:
                    raise StoreConflict("decision case changed during confirmation")
            except sqlite3.IntegrityError as exc:
                raise StoreConflict(
                    "could not atomically confirm decision scenarios"
                ) from exc
            updated_case_row = self._require_decision_case_row(connection, str(case_id))
            updated_case = self._decision_case_from_row(updated_case_row)
            assert updated_case is not None
            self._insert_decision_event(
                connection,
                case_id=str(case_id),
                event_type="decision_scenarios_confirmed",
                actor_kind="operator",
                operator_name=operator,
                payload={
                    "confirmation_id": normalized_confirmation_id,
                    "receipt_sha256": receipt_hash,
                    "scenario_revision_ids": revision_ids,
                    "tea_job_ids": job_ids,
                    "case_revision": int(updated_case_row["revision"]),
                },
                created_at=now_text,
            )
            stored_response = {
                "schema_version": 1,
                "confirmation_id": normalized_confirmation_id,
                "case": updated_case,
                "scenario_revision_ids": revision_ids,
                "tea_job_ids": job_ids,
            }
            stored_response_json = _json_dump(stored_response)
            connection.execute(
                """
                INSERT INTO decision_scenario_confirmation_idempotency (
                    case_id, idempotency_key, confirmation_request_sha256,
                    confirmation_id, response_json, response_sha256, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(case_id),
                    key,
                    confirmation_request_hash,
                    normalized_confirmation_id,
                    stored_response_json,
                    _sha256_text(stored_response_json),
                    now_text,
                ),
            )
            confirmation_row = connection.execute(
                """
                SELECT * FROM decision_scenario_confirmations
                 WHERE confirmation_id = ?
                """,
                (normalized_confirmation_id,),
            ).fetchone()
            assert confirmation_row is not None
            confirmation = self._decision_scenario_confirmation_bundle(
                connection, confirmation_row
            )
            return {
                "confirmation": confirmation,
                "items": confirmation["items"],
                "jobs": confirmation["jobs"],
                "case": updated_case,
                "idempotent_replay": False,
            }

    def expire_decision_scenario(
        self,
        scenario_id: str,
        *,
        expected_case_revision: int,
        expected_revision: int,
        operator_name: str,
        reason: str,
    ) -> dict[str, Any]:
        """Explicitly expire one current unconfirmed scenario revision."""

        operator = _bounded_text(operator_name, field="operator_name", maximum=200)
        normalized_reason = _bounded_text(reason, field="reason", maximum=2_000)
        now_text = _timestamp(self._current_time())
        with self._transaction(write=True) as connection:
            row = connection.execute(
                """
                SELECT * FROM decision_scenarios
                 WHERE scenario_id = ? AND superseded_by_revision_id IS NULL
                """,
                (str(scenario_id),),
            ).fetchone()
            if row is None:
                raise RecordNotFound(f"unknown current decision scenario: {scenario_id}")
            self._require_decision_scenario_revision(row, expected_revision)
            if row["status"] == "expired":
                return self._decision_scenario_bundle(connection, row)
            if row["status"] == "confirmed":
                raise InvalidStateTransition("confirmed decision scenarios cannot expire")
            case = self._require_decision_case_row(
                connection, str(row["case_id"]), mutable=True
            )
            self._require_case_revision(case, expected_case_revision)
            connection.execute(
                """
                UPDATE decision_scenarios
                   SET status = 'expired', expired_at = ?, updated_at = ?, updated_by = ?
                 WHERE scenario_revision_id = ?
                   AND status IN ('draft','invalid','validated')
                """,
                (now_text, now_text, operator, row["scenario_revision_id"]),
            )
            updated_case = self._touch_decision_case(
                connection, case, now_text=now_text, operator_name=operator
            )
            self._insert_decision_event(
                connection,
                case_id=str(row["case_id"]),
                event_type="decision_scenario_expired",
                actor_kind="operator",
                operator_name=operator,
                payload={
                    "scenario_id": row["scenario_id"],
                    "scenario_revision_id": row["scenario_revision_id"],
                    "scenario_revision": int(row["revision"]),
                    "reason": normalized_reason,
                    "case_revision": int(updated_case["revision"]),
                },
                created_at=now_text,
            )
            updated = self._require_decision_scenario_row(
                connection, str(row["scenario_revision_id"])
            )
            return self._decision_scenario_bundle(connection, updated)

    def get_decision_scenario_job(
        self,
        case_id: str,
        job_id: str,
    ) -> dict[str, Any] | None:
        with self._transaction() as connection:
            row = connection.execute(
                """
                SELECT j.*, l.case_id, l.scenario_revision_id, l.attempt_number,
                       l.confirmation_id AS scenario_confirmation_id,
                       s.scenario_id, s.revision AS scenario_revision
                  FROM decision_scenario_jobs l
                  JOIN decision_scenarios s
                    ON s.scenario_revision_id = l.scenario_revision_id
                  JOIN technoeconomic_jobs j ON j.tea_job_id = l.tea_job_id
                 WHERE l.case_id = ? AND l.tea_job_id = ?
                """,
                (str(case_id), str(job_id)),
            ).fetchone()
            return None if row is None else self._decision_scenario_job_record(row)

    def get_decision_scenario_job_context(
        self,
        job_id: str,
    ) -> dict[str, Any] | None:
        """Return the immutable scenario/evidence binding for a TEA attempt."""

        with self._transaction() as connection:
            link_row = connection.execute(
                """
                SELECT j.*, l.case_id, l.scenario_revision_id, l.attempt_number,
                       l.confirmation_id AS scenario_confirmation_id,
                       s.scenario_id, s.revision AS scenario_revision
                  FROM decision_scenario_jobs l
                  JOIN decision_scenarios s
                    ON s.scenario_revision_id = l.scenario_revision_id
                  JOIN technoeconomic_jobs j ON j.tea_job_id = l.tea_job_id
                 WHERE l.tea_job_id = ?
                """,
                (str(job_id),),
            ).fetchone()
            if link_row is None:
                return None
            scenario_row = self._require_decision_scenario_row(
                connection,
                str(link_row["scenario_revision_id"]),
            )
            return {
                "link": self._decision_scenario_job_record(link_row),
                "scenario": self._decision_scenario_bundle(
                    connection,
                    scenario_row,
                ),
            }

    def list_decision_scenario_jobs(
        self,
        case_id: str,
        *,
        latest_attempts_only: bool = False,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        if limit <= 0:
            return []
        if limit > 1_000:
            raise ValueError("decision scenario job limit cannot exceed 1000")
        latest_clause = ""
        if latest_attempts_only:
            latest_clause = """
                AND l.attempt_number = (
                    SELECT MAX(newer.attempt_number)
                      FROM decision_scenario_jobs newer
                     WHERE newer.scenario_revision_id = l.scenario_revision_id
                )
            """
        with self._transaction() as connection:
            self._require_decision_case_row(connection, str(case_id))
            rows = connection.execute(
                """
                SELECT j.*, l.case_id, l.scenario_revision_id, l.attempt_number,
                       l.confirmation_id AS scenario_confirmation_id,
                       s.scenario_id, s.revision AS scenario_revision
                  FROM decision_scenario_jobs l
                  JOIN decision_scenarios s
                    ON s.scenario_revision_id = l.scenario_revision_id
                  JOIN technoeconomic_jobs j ON j.tea_job_id = l.tea_job_id
                 WHERE l.case_id = ?
                """
                + latest_clause
                + " ORDER BY j.created_at ASC, j.tea_job_id ASC LIMIT ?",
                (str(case_id), int(limit)),
            ).fetchall()
            return [self._decision_scenario_job_record(row) for row in rows]

    def retry_decision_scenario_job(
        self,
        case_id: str,
        scenario_revision_id: str,
        job_id: str,
        *,
        expected_case_revision: int,
        operator_name: str,
        reason: str | None = None,
        new_job_id: str | None = None,
        max_active_jobs: int | None = None,
    ) -> dict[str, Any]:
        """Append one linked TEA retry from the exact frozen prior attempt."""

        operator = _bounded_text(operator_name, field="operator_name", maximum=200)
        retry_reason = _optional_bounded_text(reason, field="reason", maximum=4000)
        retry_id = self._validate_technoeconomic_job_id(new_job_id or _new_id("tea"))
        now_text = _timestamp(self._current_time())
        with self._transaction(write=True) as connection:
            case = self._require_decision_case_row(
                connection, str(case_id), mutable=True
            )
            link = connection.execute(
                """
                SELECT l.*, j.*, s.scenario_id, s.revision AS scenario_revision,
                       l.confirmation_id AS scenario_confirmation_id
                  FROM decision_scenario_jobs l
                  JOIN decision_scenarios s
                    ON s.scenario_revision_id = l.scenario_revision_id
                  JOIN technoeconomic_jobs j ON j.tea_job_id = l.tea_job_id
                 WHERE l.case_id = ? AND l.scenario_revision_id = ?
                   AND l.tea_job_id = ?
                """,
                (str(case_id), str(scenario_revision_id), str(job_id)),
            ).fetchone()
            if link is None:
                raise RecordNotFound("TEA job is not linked to that decision scenario")
            existing = connection.execute(
                """
                SELECT j.*, l.case_id, l.scenario_revision_id, l.attempt_number,
                       l.confirmation_id AS scenario_confirmation_id,
                       s.scenario_id, s.revision AS scenario_revision
                  FROM decision_scenario_jobs l
                  JOIN decision_scenarios s
                    ON s.scenario_revision_id = l.scenario_revision_id
                  JOIN technoeconomic_jobs j ON j.tea_job_id = l.tea_job_id
                 WHERE l.scenario_revision_id = ? AND l.retry_of_job_id = ?
                """,
                (str(scenario_revision_id), str(job_id)),
            ).fetchone()
            if existing is not None:
                existing_link = self._decision_scenario_job_record(existing)
                scenario_row = self._require_decision_scenario_row(
                    connection, str(scenario_revision_id)
                )
                return {
                    "link": existing_link,
                    "job": existing_link["job"],
                    "scenario": self._decision_scenario_bundle(
                        connection, scenario_row
                    ),
                    "case": self._decision_case_from_row(case),
                    "idempotent_replay": True,
                }
            self._require_case_revision(case, expected_case_revision)
            if case["status"] not in {"running", "results_ready"}:
                raise InvalidStateTransition(
                    "decision scenario retries require running or results_ready cases"
                )
            if link["state"] not in {"interrupted", "error", "cancelled"}:
                raise InvalidStateTransition(
                    f"cannot retry technoeconomic job in state {link['state']}"
                )
            if connection.execute(
                "SELECT 1 FROM technoeconomic_jobs WHERE tea_job_id = ?", (retry_id,)
            ).fetchone() is not None or connection.execute(
                "SELECT 1 FROM jobs WHERE job_id = ?", (retry_id,)
            ).fetchone() is not None:
                raise StoreConflict(f"technoeconomic job id already exists: {retry_id}")
            self._ensure_queue_capacity(
                connection, max_active_jobs=max_active_jobs, required=1
            )
            next_attempt = int(
                connection.execute(
                    """
                    SELECT COALESCE(MAX(attempt_number), 0) + 1
                      FROM decision_scenario_jobs
                     WHERE scenario_revision_id = ?
                    """,
                    (str(scenario_revision_id),),
                ).fetchone()[0]
            )
            try:
                self._insert_technoeconomic_job(
                    connection,
                    job_id=retry_id,
                    request_json=str(link["request_json"]),
                    source_annual_job_id=str(link["source_annual_job_id"]),
                    source_artifact_storage_key=str(
                        link["source_artifact_storage_key"]
                    ),
                    source_artifact_sha256=str(link["source_artifact_sha256"]),
                    source_artifact_bytes=int(link["source_artifact_bytes"]),
                    source_snapshot_json=str(link["source_snapshot_json"]),
                    source_snapshot_sha256=str(link["source_snapshot_sha256"]),
                    submission_provenance_json=str(
                        link["submission_provenance_json"]
                    ),
                    submission_provenance_sha256=str(
                        link["submission_provenance_sha256"]
                    ),
                    retry_of_job_id=str(job_id),
                    now_text=now_text,
                )
                connection.execute(
                    """
                    INSERT INTO decision_scenario_jobs (
                        tea_job_id, scenario_revision_id, case_id,
                        attempt_number, retry_of_job_id, confirmation_id, created_at
                    ) VALUES (?, ?, ?, ?, ?, NULL, ?)
                    """,
                    (
                        retry_id,
                        str(scenario_revision_id),
                        str(case_id),
                        next_attempt,
                        str(job_id),
                        now_text,
                    ),
                )
                self._mark_current_decision_outputs_stale(
                    connection,
                    case_id=str(case_id),
                    reason={
                        "code": "decision_scenario_retry_created",
                        "scenario_revision_id": str(scenario_revision_id),
                        "retry_of_job_id": str(job_id),
                        "tea_job_id": retry_id,
                        "attempt_number": next_attempt,
                    },
                    created_at=now_text,
                )
                next_status = "running"
                cursor = connection.execute(
                    """
                    UPDATE decision_cases
                       SET status = ?, revision = revision + 1,
                           updated_at = ?, updated_by = ?
                     WHERE case_id = ? AND revision = ?
                       AND status IN ('running','results_ready')
                    """,
                    (
                        next_status,
                        now_text,
                        operator,
                        str(case_id),
                        expected_case_revision,
                    ),
                )
                if cursor.rowcount != 1:
                    raise StoreConflict("decision case changed during scenario retry")
            except sqlite3.IntegrityError as exc:
                raise StoreConflict("could not retry decision scenario TEA job") from exc
            updated_case = self._require_decision_case_row(connection, str(case_id))
            self._insert_decision_event(
                connection,
                case_id=str(case_id),
                event_type="decision_scenario_job_retried",
                actor_kind="operator",
                operator_name=operator,
                payload={
                    "scenario_revision_id": str(scenario_revision_id),
                    "retry_of_job_id": str(job_id),
                    "tea_job_id": retry_id,
                    "attempt_number": next_attempt,
                    "reason": retry_reason,
                    "case_revision": int(updated_case["revision"]),
                },
                created_at=now_text,
            )
            retry_row = connection.execute(
                """
                SELECT j.*, l.case_id, l.scenario_revision_id, l.attempt_number,
                       l.confirmation_id AS scenario_confirmation_id,
                       s.scenario_id, s.revision AS scenario_revision
                  FROM decision_scenario_jobs l
                  JOIN decision_scenarios s
                    ON s.scenario_revision_id = l.scenario_revision_id
                  JOIN technoeconomic_jobs j ON j.tea_job_id = l.tea_job_id
                 WHERE l.tea_job_id = ?
                """,
                (retry_id,),
            ).fetchone()
            assert retry_row is not None
            retry_link = self._decision_scenario_job_record(retry_row)
            scenario_row = self._require_decision_scenario_row(
                connection, str(scenario_revision_id)
            )
            return {
                "link": retry_link,
                "job": retry_link["job"],
                "scenario": self._decision_scenario_bundle(
                    connection, scenario_row
                ),
                "case": self._decision_case_from_row(updated_case),
                "idempotent_replay": False,
            }

    def cancel_decision_scenario_job(
        self,
        case_id: str,
        job_id: str,
        *,
        expected_case_revision: int,
        operator_name: str,
        reason: str,
    ) -> dict[str, Any]:
        """Apply the existing TEA cancellation policy to one case-linked job."""

        operator = _bounded_text(operator_name, field="operator_name", maximum=200)
        normalized_reason = _bounded_text(reason, field="reason", maximum=2_000)
        now_text = _timestamp(self._current_time())
        with self._transaction(write=True) as connection:
            case = self._require_decision_case_row(
                connection, str(case_id), mutable=True
            )
            self._require_case_revision(case, expected_case_revision)
            row = connection.execute(
                """
                SELECT j.*, l.case_id, l.scenario_revision_id, l.attempt_number,
                       l.confirmation_id AS scenario_confirmation_id,
                       s.scenario_id, s.revision AS scenario_revision
                  FROM decision_scenario_jobs l
                  JOIN decision_scenarios s
                    ON s.scenario_revision_id = l.scenario_revision_id
                  JOIN technoeconomic_jobs j ON j.tea_job_id = l.tea_job_id
                 WHERE l.case_id = ? AND l.tea_job_id = ?
                """,
                (str(case_id), str(job_id)),
            ).fetchone()
            if row is None:
                raise RecordNotFound("TEA job is not linked to that decision case")
            changed = False
            if row["state"] == "queued":
                cursor = connection.execute(
                    """
                    UPDATE technoeconomic_jobs
                       SET state = 'cancelled', cancel_requested = 1,
                           cancel_requested_at = ?, completed_at = ?, updated_at = ?,
                           stage = 'Cancelled'
                     WHERE tea_job_id = ? AND state = 'queued'
                    """,
                    (now_text, now_text, now_text, str(job_id)),
                )
                changed = cursor.rowcount == 1
            elif row["state"] == "running" and not row["cancel_requested"]:
                cursor = connection.execute(
                    """
                    UPDATE technoeconomic_jobs
                       SET cancel_requested = 1, cancel_requested_at = ?, updated_at = ?
                     WHERE tea_job_id = ? AND state = 'running'
                       AND cancel_requested = 0
                    """,
                    (now_text, now_text, str(job_id)),
                )
                changed = cursor.rowcount == 1
            if changed:
                self._mark_current_decision_outputs_stale(
                    connection,
                    case_id=str(case_id),
                    reason={
                        "code": "decision_scenario_attempt_cancelled",
                        "scenario_revision_id": row["scenario_revision_id"],
                        "tea_job_id": str(job_id),
                    },
                    created_at=now_text,
                )
                execution = self._decision_case_execution_summary(
                    connection, str(case_id)
                )
                next_status = (
                    "results_ready"
                    if case["status"] == "running" and execution["all_successful"]
                    else str(case["status"])
                )
                cursor = connection.execute(
                    """
                    UPDATE decision_cases
                       SET status = ?, revision = revision + 1,
                           updated_at = ?, updated_by = ?
                     WHERE case_id = ? AND revision = ?
                    """,
                    (
                        next_status,
                        now_text,
                        operator,
                        str(case_id),
                        expected_case_revision,
                    ),
                )
                if cursor.rowcount != 1:
                    raise StoreConflict("decision case changed during cancellation")
                case = self._require_decision_case_row(connection, str(case_id))
                self._insert_decision_event(
                    connection,
                    case_id=str(case_id),
                    event_type="decision_scenario_job_cancelled",
                    actor_kind="operator",
                    operator_name=operator,
                    payload={
                        "scenario_revision_id": row["scenario_revision_id"],
                        "tea_job_id": str(job_id),
                        "reason": normalized_reason,
                        "state": (
                            "cancelled" if row["state"] == "queued" else "running"
                        ),
                        "cancel_requested": True,
                        "case_status": next_status,
                        "case_revision": int(case["revision"]),
                    },
                    created_at=now_text,
                )
            updated_row = connection.execute(
                """
                SELECT j.*, l.case_id, l.scenario_revision_id, l.attempt_number,
                       l.confirmation_id AS scenario_confirmation_id,
                       s.scenario_id, s.revision AS scenario_revision
                  FROM decision_scenario_jobs l
                  JOIN decision_scenarios s
                    ON s.scenario_revision_id = l.scenario_revision_id
                  JOIN technoeconomic_jobs j ON j.tea_job_id = l.tea_job_id
                 WHERE l.case_id = ? AND l.tea_job_id = ?
                """,
                (str(case_id), str(job_id)),
            ).fetchone()
            assert updated_row is not None
            return {
                "link": self._decision_scenario_job_record(updated_row),
                "case": self._decision_case_from_row(case),
                "changed": changed,
            }

    def reconcile_decision_case_execution(
        self,
        case_id: str,
        *,
        operator_name: str = "system:scenario-execution",
    ) -> dict[str, Any]:
        """Project existing TEA states onto the case without changing job semantics."""

        operator = _bounded_text(operator_name, field="operator_name", maximum=200)
        now_text = _timestamp(self._current_time())
        with self._transaction(write=True) as connection:
            case = self._require_decision_case_row(connection, str(case_id))
            execution = self._decision_case_execution_summary(connection, str(case_id))
            transitioned = False
            if case["status"] == "running" and execution["all_successful"]:
                cursor = connection.execute(
                    """
                    UPDATE decision_cases
                       SET status = 'results_ready', revision = revision + 1,
                           updated_at = ?, updated_by = ?
                     WHERE case_id = ? AND revision = ? AND status = 'running'
                    """,
                    (now_text, operator, str(case_id), case["revision"]),
                )
                if cursor.rowcount != 1:
                    raise StoreConflict("decision case changed during execution reconciliation")
                case = self._require_decision_case_row(connection, str(case_id))
                self._insert_decision_event(
                    connection,
                    case_id=str(case_id),
                    event_type="decision_case_results_ready",
                    actor_kind="system",
                    payload={
                        "state_counts": execution["state_counts"],
                        "results_available": execution["results_available"],
                        "partial_results": execution["partial_results"],
                        "case_revision": int(case["revision"]),
                    },
                    created_at=now_text,
                )
                transitioned = True
            execution["case"] = self._decision_case_from_row(case)
            execution["case_transitioned"] = transitioned
            return execution

    def expire_decision_scenario_drafts(
        self,
        case_id: str,
        *,
        operator_name: str,
        expected_case_revision: int | None = None,
        before: datetime | None = None,
    ) -> dict[str, Any]:
        operator = _bounded_text(operator_name, field="operator_name", maximum=200)
        now_text = _timestamp(self._current_time())
        cutoff_text = _timestamp(before or self._current_time())
        with self._transaction(write=True) as connection:
            case = self._require_decision_case_row(
                connection, str(case_id), mutable=True
            )
            self._require_case_revision(case, expected_case_revision)
            rows = connection.execute(
                """
                SELECT * FROM decision_scenarios
                 WHERE case_id = ?
                   AND status IN ('draft','invalid','validated')
                   AND expires_at <= ?
                 ORDER BY created_at, scenario_revision_id
                """,
                (str(case_id), cutoff_text),
            ).fetchall()
            revision_ids = [str(row["scenario_revision_id"]) for row in rows]
            if revision_ids:
                placeholders = ",".join("?" for _ in revision_ids)
                connection.execute(
                    f"""
                    UPDATE decision_scenarios
                       SET status = 'expired', expired_at = ?, updated_at = ?,
                           updated_by = ?
                     WHERE scenario_revision_id IN ({placeholders})
                    """,
                    (now_text, now_text, operator, *revision_ids),
                )
                case = self._touch_decision_case(
                    connection, case, now_text=now_text, operator_name=operator
                )
                self._insert_decision_event(
                    connection,
                    case_id=str(case_id),
                    event_type="decision_scenarios_expired",
                    actor_kind="operator",
                    operator_name=operator,
                    payload={
                        "scenario_revision_ids": revision_ids,
                        "cutoff": cutoff_text,
                        "case_revision": int(case["revision"]),
                    },
                    created_at=now_text,
                )
            return {
                "expired_count": len(revision_ids),
                "scenario_revision_ids": revision_ids,
                "case": self._decision_case_from_row(case),
            }

    def create_decision_comparison_bundle(
        self,
        case_id: str,
        *,
        expected_case_revision: int,
        source_confirmation_id: str,
        bundle: Mapping[str, Any],
        bundle_sha256: str,
        attempt_proofs: Sequence[Mapping[str, Any]],
        created_by: str,
        comparison_bundle_id: str | None = None,
    ) -> dict[str, Any]:
        """Persist one exact, verified comparison snapshot without recalculation."""

        if not isinstance(bundle, Mapping):
            raise ValueError("bundle must be an object")
        if (
            isinstance(expected_case_revision, bool)
            or not isinstance(expected_case_revision, int)
            or expected_case_revision <= 0
        ):
            raise ValueError("expected_case_revision must be a positive integer")
        normalized_id = self._validate_decision_record_id(
            comparison_bundle_id,
            prefix="dcmp",
            field="comparison_bundle_id",
        )
        confirmation_id = self._validate_decision_record_id(
            source_confirmation_id,
            prefix="dconf",
            field="source_confirmation_id",
        )
        creator = _bounded_text(created_by, field="created_by", maximum=200)
        bundle_json = _json_dump(dict(bundle))
        normalized_hash = self._validate_sha256(
            bundle_sha256, field="bundle_sha256"
        )
        canonical_bundle = dict(bundle)
        embedded_hash = canonical_bundle.pop("bundle_hash", None)
        if (
            embedded_hash != normalized_hash
            or not secrets.compare_digest(
                normalized_hash,
                _sha256_text(_json_dump(canonical_bundle)),
            )
        ):
            raise StoreConflict("comparison bundle SHA-256 is not canonical")
        schema_version_value = bundle.get("schema_version")
        if schema_version_value is None:
            raise ValueError("bundle schema_version is required")
        bundle_schema_version = _bounded_text(
            str(schema_version_value), field="bundle.schema_version", maximum=100
        )
        is_complete_value = bundle.get("is_complete")
        recommendation_eligible_value = bundle.get("recommendation_eligible")
        if type(is_complete_value) is not bool:
            raise ValueError("bundle is_complete must be a boolean")
        if type(recommendation_eligible_value) is not bool:
            raise ValueError("bundle recommendation_eligible must be a boolean")
        is_complete = bool(is_complete_value)
        recommendation_eligible = bool(recommendation_eligible_value)
        if recommendation_eligible:
            raise InvalidStateTransition(
                "recommendation eligibility remains pending a versioned contract"
            )

        now_text = _timestamp(self._current_time())
        with self._transaction(write=True) as connection:
            existing = connection.execute(
                """
                SELECT * FROM decision_comparison_bundles
                 WHERE case_id = ? AND source_confirmation_id = ?
                   AND bundle_sha256 = ?
                """,
                (str(case_id), confirmation_id, normalized_hash),
            ).fetchone()
            if existing is not None:
                existing_record = self._decision_comparison_bundle_record(
                    connection, existing
                )
                supplied_json = _json_dump([dict(item) for item in attempt_proofs])
                if any(
                    (
                        int(existing["expected_case_revision"])
                        != expected_case_revision,
                        str(existing["bundle_json"]) != bundle_json,
                        str(existing["created_by"]) != creator,
                        _json_dump(existing_record["attempt_proofs"])
                        != supplied_json,
                    )
                ):
                    raise StoreConflict(
                        "comparison snapshot already exists with different inputs"
                    )
                existing_record["idempotent_replay"] = True
                return existing_record

            case = self._require_decision_case_row(
                connection, str(case_id), mutable=True
            )
            self._require_case_revision(case, expected_case_revision)
            if case["status"] not in {"running", "results_ready", "decision_ready"}:
                raise InvalidStateTransition(
                    "comparison bundles require an executed decision case"
                )
            proofs = self._verified_decision_comparison_attempts(
                connection,
                case_id=str(case_id),
                source_confirmation_id=confirmation_id,
                attempt_proofs=attempt_proofs,
            )
            selected = [
                proof for proof in proofs if proof["selected_for_comparison"]
            ]
            derived_complete = bool(selected) and all(
                proof["state"] == "done"
                and proof["verification_status"] == "verified"
                for proof in selected
            )
            if is_complete != derived_complete:
                raise StoreConflict(
                    "bundle completeness does not match selected attempt verification"
                )
            embedded_proofs = bundle.get("attempt_proofs")
            if not isinstance(embedded_proofs, list) or _json_dump(
                embedded_proofs
            ) != _json_dump(proofs):
                raise StoreConflict(
                    "bundle attempt_proofs do not match durable attempt history"
                )

            prior = connection.execute(
                """
                SELECT * FROM decision_comparison_bundles
                 WHERE case_id = ? AND superseded_by_bundle_id IS NULL
                """,
                (str(case_id),),
            ).fetchone()
            pending_supersession = (
                f"dcmp_pending_{uuid.uuid4().hex}" if prior is not None else None
            )
            try:
                connection.execute(
                    """
                    INSERT INTO decision_comparison_bundles (
                        comparison_bundle_id, case_id, source_confirmation_id,
                        expected_case_revision, bundle_schema_version,
                        bundle_json, bundle_sha256, is_complete,
                        recommendation_eligible, created_by, created_at,
                        superseded_by_bundle_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        normalized_id,
                        str(case_id),
                        confirmation_id,
                        expected_case_revision,
                        bundle_schema_version,
                        bundle_json,
                        normalized_hash,
                        int(is_complete),
                        int(recommendation_eligible),
                        creator,
                        now_text,
                        pending_supersession,
                    ),
                )
                for proof in proofs:
                    connection.execute(
                        """
                        INSERT INTO decision_comparison_bundle_attempts (
                            comparison_bundle_id, case_id, item_index,
                            scenario_revision_id, scenario_id,
                            scenario_revision, attempt_number, tea_job_id,
                            retry_of_job_id, selected_for_comparison, state,
                            verification_status, request_sha256,
                            source_snapshot_sha256, result_sha256,
                            result_provenance_sha256, evidence_set_sha256,
                            reporting_tieout_sha256, created_at
                        ) VALUES (
                            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                        )
                        """,
                        (
                            normalized_id,
                            str(case_id),
                            proof["item_index"],
                            proof["scenario_revision_id"],
                            proof["scenario_id"],
                            proof["scenario_revision"],
                            proof["attempt_number"],
                            proof["tea_job_id"],
                            proof["retry_of_job_id"],
                            int(proof["selected_for_comparison"]),
                            proof["state"],
                            proof["verification_status"],
                            proof["request_sha256"],
                            proof["source_snapshot_sha256"],
                            proof["result_sha256"],
                            proof["result_provenance_sha256"],
                            proof["evidence_set_sha256"],
                            proof["reporting_tieout_sha256"],
                            now_text,
                        ),
                    )
                if prior is not None:
                    stale_reason_json = _json_dump(
                        {
                            "code": "superseded_by_comparison_bundle",
                            "superseded_by_bundle_id": normalized_id,
                        }
                    )
                    connection.execute(
                        """
                        UPDATE decision_comparison_bundles
                           SET stale_at = COALESCE(stale_at, ?),
                               stale_reason_json = COALESCE(
                                   stale_reason_json, ?
                               ),
                               superseded_by_bundle_id = ?, superseded_at = ?
                         WHERE comparison_bundle_id = ?
                           AND superseded_by_bundle_id IS NULL
                        """,
                        (
                            now_text,
                            stale_reason_json,
                            normalized_id,
                            now_text,
                            prior["comparison_bundle_id"],
                        ),
                    )
                    connection.execute(
                        """
                        UPDATE decision_comparison_bundles
                           SET superseded_by_bundle_id = NULL
                         WHERE comparison_bundle_id = ?
                           AND superseded_by_bundle_id = ?
                        """,
                        (normalized_id, pending_supersession),
                    )
                    self._insert_decision_event(
                        connection,
                        case_id=str(case_id),
                        event_type="decision_comparison_bundle_superseded",
                        actor_kind="system",
                        payload={
                            "comparison_bundle_id": prior[
                                "comparison_bundle_id"
                            ],
                            "superseded_by_bundle_id": normalized_id,
                            "bundle_sha256": prior["bundle_sha256"],
                        },
                        created_at=now_text,
                    )
            except sqlite3.IntegrityError as exc:
                raise StoreConflict(
                    "could not persist immutable decision comparison bundle"
                ) from exc

            cursor = connection.execute(
                """
                UPDATE decision_cases
                   SET revision = revision + 1, updated_at = ?, updated_by = ?
                 WHERE case_id = ? AND revision = ?
                """,
                (
                    now_text,
                    creator,
                    str(case_id),
                    expected_case_revision,
                ),
            )
            if cursor.rowcount != 1:
                raise StoreConflict(
                    "decision case changed during comparison creation"
                )

            self._insert_decision_event(
                connection,
                case_id=str(case_id),
                event_type="decision_comparison_bundle_built",
                actor_kind="system",
                payload={
                    "comparison_bundle_id": normalized_id,
                    "source_confirmation_id": confirmation_id,
                    "bundle_sha256": normalized_hash,
                    "is_complete": is_complete,
                    "recommendation_eligible": recommendation_eligible,
                    "attempt_count": len(proofs),
                    "case_revision": expected_case_revision + 1,
                },
                created_at=now_text,
            )
            row = connection.execute(
                """
                SELECT * FROM decision_comparison_bundles
                 WHERE comparison_bundle_id = ?
                """,
                (normalized_id,),
            ).fetchone()
            assert row is not None
            result = self._decision_comparison_bundle_record(connection, row)
            result["idempotent_replay"] = False
            return result

    def get_decision_comparison_bundle(
        self, comparison_bundle_id: str
    ) -> dict[str, Any] | None:
        with self._transaction() as connection:
            row = connection.execute(
                """
                SELECT * FROM decision_comparison_bundles
                 WHERE comparison_bundle_id = ?
                """,
                (str(comparison_bundle_id),),
            ).fetchone()
            return (
                None
                if row is None
                else self._decision_comparison_bundle_record(connection, row)
            )

    def list_decision_comparison_bundles(
        self,
        case_id: str,
        *,
        include_stale: bool = True,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        bounded_limit = max(0, min(int(limit), 500))
        current_clause = "" if include_stale else (
            " AND stale_at IS NULL AND superseded_by_bundle_id IS NULL"
        )
        with self._transaction() as connection:
            rows = connection.execute(
                """
                SELECT * FROM decision_comparison_bundles
                 WHERE case_id = ?
                """
                + current_clause
                + " ORDER BY created_at DESC, comparison_bundle_id DESC LIMIT ?",
                (str(case_id), bounded_limit),
            ).fetchall()
            return [
                self._decision_comparison_bundle_record(connection, row)
                for row in rows
            ]

    def mark_decision_comparison_bundle_stale(
        self,
        comparison_bundle_id: str,
        *,
        reason: Mapping[str, Any],
        actor_kind: str = "system",
        operator_name: str | None = None,
    ) -> dict[str, Any]:
        if not isinstance(reason, Mapping) or not reason:
            raise ValueError("reason must be a non-empty object")
        reason_json = _json_dump(dict(reason))
        actor, operator = self._normalize_decision_event_actor(
            actor_kind, operator_name
        )
        now_text = _timestamp(self._current_time())
        with self._transaction(write=True) as connection:
            row = connection.execute(
                """
                SELECT * FROM decision_comparison_bundles
                 WHERE comparison_bundle_id = ?
                """,
                (str(comparison_bundle_id),),
            ).fetchone()
            if row is None:
                raise RecordNotFound(
                    f"unknown decision comparison bundle: {comparison_bundle_id}"
                )
            if row["stale_at"] is None:
                connection.execute(
                    """
                    UPDATE decision_comparison_bundles
                       SET stale_at = ?, stale_reason_json = ?
                     WHERE comparison_bundle_id = ? AND stale_at IS NULL
                    """,
                    (now_text, reason_json, str(comparison_bundle_id)),
                )
                self._insert_decision_event(
                    connection,
                    case_id=str(row["case_id"]),
                    event_type="decision_comparison_bundle_stale",
                    actor_kind=actor,
                    operator_name=operator,
                    payload={
                        "comparison_bundle_id": str(comparison_bundle_id),
                        "bundle_sha256": row["bundle_sha256"],
                        "reason": dict(reason),
                    },
                    created_at=now_text,
                )
            elif str(row["stale_reason_json"]) != reason_json:
                raise StoreConflict("comparison bundle is already stale")
            updated = connection.execute(
                """
                SELECT * FROM decision_comparison_bundles
                 WHERE comparison_bundle_id = ?
                """,
                (str(comparison_bundle_id),),
            ).fetchone()
            assert updated is not None
            return self._decision_comparison_bundle_record(connection, updated)

    def create_decision_brief(
        self,
        case_id: str,
        *,
        expected_case_revision: int,
        comparison_bundle_id: str,
        recommendation_classification: str,
        confidence_state: str,
        caveats: Sequence[Any],
        reversal_conditions: Sequence[Any],
        provenance: Mapping[str, Any],
        created_by: str,
        idempotency_key: str,
        brief_id: str | None = None,
        brief_revision_id: str | None = None,
    ) -> dict[str, Any]:
        """Create one immutable brief revision and atomically supersede its parent."""

        if (
            isinstance(expected_case_revision, bool)
            or not isinstance(expected_case_revision, int)
            or expected_case_revision <= 0
        ):
            raise ValueError("expected_case_revision must be a positive integer")
        classification = str(recommendation_classification).strip()
        if classification not in DECISION_RECOMMENDATION_CLASSIFICATIONS:
            raise ValueError("unsupported recommendation_classification")
        confidence = str(confidence_state).strip()
        if confidence not in DECISION_CONFIDENCE_STATES:
            raise ValueError("unsupported confidence_state")
        pending_classification = classification == "classification_pending_contract"
        if pending_classification != (
            confidence == "classification_pending_contract"
        ):
            raise ValueError(
                "classification-pending recommendation and confidence must match"
            )
        if not pending_classification:
            raise InvalidStateTransition(
                "final recommendation classifications remain pending a "
                "versioned contract"
            )
        if isinstance(caveats, (str, bytes)):
            raise ValueError("caveats must be an array")
        if isinstance(reversal_conditions, (str, bytes)):
            raise ValueError("reversal_conditions must be an array")
        if not isinstance(provenance, Mapping):
            raise ValueError("provenance must be an object")
        caveats_json = _json_dump(list(caveats))
        reversal_json = _json_dump(list(reversal_conditions))
        provenance_json = _json_dump(dict(provenance))
        provenance_sha256 = _sha256_text(provenance_json)
        creator = _bounded_text(created_by, field="created_by", maximum=200)
        key = _bounded_text(
            idempotency_key, field="idempotency_key", maximum=200
        )
        normalized_bundle_id = self._validate_decision_record_id(
            comparison_bundle_id,
            prefix="dcmp",
            field="comparison_bundle_id",
        )
        requested_brief_id = (
            None
            if brief_id is None
            else self._validate_decision_record_id(
                brief_id, prefix="dbf", field="brief_id"
            )
        )
        requested_revision_id = (
            None
            if brief_revision_id is None
            else self._validate_decision_record_id(
                brief_revision_id,
                prefix="dbr",
                field="brief_revision_id",
            )
        )
        creation_request = {
            "schema_version": 1,
            "case_id": str(case_id),
            "expected_case_revision": expected_case_revision,
            "comparison_bundle_id": normalized_bundle_id,
            "recommendation_classification": classification,
            "confidence_state": confidence,
            "caveats": list(caveats),
            "reversal_conditions": list(reversal_conditions),
            "provenance": dict(provenance),
            "created_by": creator,
            "brief_id": requested_brief_id,
            "brief_revision_id": requested_revision_id,
        }
        creation_request_json = _json_dump(creation_request)
        creation_request_sha256 = _sha256_text(creation_request_json)
        now_text = _timestamp(self._current_time())

        with self._transaction(write=True) as connection:
            replay = connection.execute(
                """
                SELECT * FROM decision_brief_idempotency
                 WHERE case_id = ? AND idempotency_key = ?
                """,
                (str(case_id), key),
            ).fetchone()
            if replay is not None:
                if not secrets.compare_digest(
                    str(replay["creation_request_sha256"]),
                    creation_request_sha256,
                ):
                    raise StoreConflict(
                        "idempotency key was already used for another brief request"
                    )
                response_json = str(replay["response_json"])
                if not secrets.compare_digest(
                    str(replay["response_sha256"]), _sha256_text(response_json)
                ):
                    raise StoreConflict("decision brief replay receipt is invalid")
                response = _json_load(response_json)
                if (
                    not isinstance(response, Mapping)
                    or response.get("brief_revision_id")
                    != replay["brief_revision_id"]
                ):
                    raise StoreConflict("decision brief replay identity is invalid")
                row = connection.execute(
                    """
                    SELECT * FROM decision_briefs WHERE brief_revision_id = ?
                    """,
                    (replay["brief_revision_id"],),
                ).fetchone()
                if row is None:
                    raise StoreConflict("decision brief replay revision is missing")
                case = self._require_decision_case_row(connection, str(case_id))
                result = self._decision_brief_record(connection, row)
                result["case"] = self._decision_case_from_row(case)
                result["idempotent_replay"] = True
                return result

            bundle_row = connection.execute(
                """
                SELECT * FROM decision_comparison_bundles
                 WHERE comparison_bundle_id = ?
                """,
                (normalized_bundle_id,),
            ).fetchone()
            if bundle_row is None:
                raise RecordNotFound(
                    f"unknown decision comparison bundle: {normalized_bundle_id}"
                )
            _verified_decision_bundle_json(
                str(bundle_row["bundle_json"]), str(bundle_row["bundle_sha256"])
            )
            if bundle_row["case_id"] != str(case_id):
                raise StoreConflict("comparison bundle belongs to a different case")

            natural = connection.execute(
                """
                SELECT * FROM decision_briefs
                 WHERE case_id = ? AND expected_case_revision = ?
                   AND comparison_bundle_sha256 = ?
                """,
                (
                    str(case_id),
                    expected_case_revision,
                    bundle_row["bundle_sha256"],
                ),
            ).fetchone()
            if natural is not None:
                if any(
                    (
                        natural["comparison_bundle_id"] != normalized_bundle_id,
                        natural["recommendation_classification"] != classification,
                        natural["confidence_state"] != confidence,
                        str(natural["caveats_json"]) != caveats_json,
                        str(natural["reversal_conditions_json"]) != reversal_json,
                        str(natural["provenance_json"]) != provenance_json,
                        natural["created_by"] != creator,
                        requested_brief_id is not None
                        and natural["brief_id"] != requested_brief_id,
                        requested_revision_id is not None
                        and natural["brief_revision_id"] != requested_revision_id,
                    )
                ):
                    raise StoreConflict(
                        "brief snapshot already exists with different inputs"
                    )
                stored_response = {
                    "schema_version": 1,
                    "brief_id": natural["brief_id"],
                    "brief_revision_id": natural["brief_revision_id"],
                    "case_id": str(case_id),
                    "case_revision_after": int(natural["case_revision_after"]),
                    "comparison_bundle_sha256": natural[
                        "comparison_bundle_sha256"
                    ],
                }
                response_json = _json_dump(stored_response)
                connection.execute(
                    """
                    INSERT INTO decision_brief_idempotency (
                        case_id, idempotency_key, creation_request_sha256,
                        brief_revision_id, response_json, response_sha256,
                        created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(case_id),
                        key,
                        creation_request_sha256,
                        natural["brief_revision_id"],
                        response_json,
                        _sha256_text(response_json),
                        now_text,
                    ),
                )
                case = self._require_decision_case_row(connection, str(case_id))
                result = self._decision_brief_record(connection, natural)
                result["case"] = self._decision_case_from_row(case)
                result["idempotent_replay"] = True
                return result

            case = self._require_decision_case_row(
                connection, str(case_id), mutable=True
            )
            self._require_case_revision(case, expected_case_revision)
            if (
                int(bundle_row["expected_case_revision"]) + 1
                != expected_case_revision
            ):
                raise StoreConflict(
                    "comparison bundle was built for another case revision"
                )
            if any(
                (
                    bundle_row["stale_at"] is not None,
                    bundle_row["superseded_by_bundle_id"] is not None,
                    not self._decision_comparison_bundle_still_matches_history(
                        connection, bundle_row
                    ),
                )
            ):
                raise StoreConflict(
                    "comparison bundle is stale or no longer verifies"
                )
            if not bool(bundle_row["is_complete"]):
                raise InvalidStateTransition(
                    "incomplete comparisons cannot be finalized as decision briefs"
                )
            if case["status"] not in {"running", "results_ready"}:
                raise InvalidStateTransition(
                    "classification-pending briefs require running or ready results"
                )

            parent = connection.execute(
                """
                SELECT * FROM decision_briefs
                 WHERE case_id = ? AND superseded_by_revision_id IS NULL
                """,
                (str(case_id),),
            ).fetchone()
            if parent is None:
                stable_brief_id = requested_brief_id or _new_id("dbf")
                revision = 1
                parent_revision_id = None
            else:
                stable_brief_id = str(parent["brief_id"])
                if (
                    requested_brief_id is not None
                    and requested_brief_id != stable_brief_id
                ):
                    raise StoreConflict("brief_id does not match existing lineage")
                revision = int(parent["revision"]) + 1
                parent_revision_id = str(parent["brief_revision_id"])
            normalized_revision_id = requested_revision_id or _new_id("dbr")
            pending_supersession = (
                f"dbr_pending_{uuid.uuid4().hex}" if parent is not None else None
            )
            bundle_json = str(bundle_row["bundle_json"])
            try:
                connection.execute(
                    """
                    INSERT INTO decision_briefs (
                        brief_revision_id, brief_id, case_id, revision,
                        parent_revision_id, superseded_by_revision_id,
                        source_confirmation_id, comparison_bundle_id,
                        expected_case_revision, case_revision_after,
                        comparison_bundle_json, comparison_bundle_sha256,
                        recommendation_classification, confidence_state,
                        caveats_json, reversal_conditions_json,
                        provenance_json, provenance_sha256, created_by,
                        created_at
                    ) VALUES (
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                    )
                    """,
                    (
                        normalized_revision_id,
                        stable_brief_id,
                        str(case_id),
                        revision,
                        parent_revision_id,
                        pending_supersession,
                        bundle_row["source_confirmation_id"],
                        normalized_bundle_id,
                        expected_case_revision,
                        expected_case_revision + 1,
                        bundle_json,
                        bundle_row["bundle_sha256"],
                        classification,
                        confidence,
                        caveats_json,
                        reversal_json,
                        provenance_json,
                        provenance_sha256,
                        creator,
                        now_text,
                    ),
                )
                if parent is not None:
                    stale_reason_json = _json_dump(
                        {
                            "code": "superseded_by_decision_brief_revision",
                            "superseded_by_revision_id": normalized_revision_id,
                        }
                    )
                    connection.execute(
                        """
                        UPDATE decision_briefs
                           SET stale_at = COALESCE(stale_at, ?),
                               stale_reason_json = COALESCE(
                                   stale_reason_json, ?
                               ),
                               superseded_by_revision_id = ?, superseded_at = ?
                         WHERE brief_revision_id = ?
                           AND superseded_by_revision_id IS NULL
                        """,
                        (
                            now_text,
                            stale_reason_json,
                            normalized_revision_id,
                            now_text,
                            parent_revision_id,
                        ),
                    )
                    connection.execute(
                        """
                        UPDATE decision_briefs
                           SET superseded_by_revision_id = NULL
                         WHERE brief_revision_id = ?
                           AND superseded_by_revision_id = ?
                        """,
                        (normalized_revision_id, pending_supersession),
                    )
                    self._insert_decision_event(
                        connection,
                        case_id=str(case_id),
                        event_type="decision_brief_superseded",
                        actor_kind="system",
                        payload={
                            "brief_id": stable_brief_id,
                            "brief_revision_id": parent_revision_id,
                            "superseded_by_revision_id": normalized_revision_id,
                            "comparison_bundle_sha256": parent[
                                "comparison_bundle_sha256"
                            ],
                        },
                        created_at=now_text,
                    )
                cursor = connection.execute(
                    """
                    UPDATE decision_cases
                       SET status = ?, active_recommendation_revision = ?,
                           revision = revision + 1, updated_at = ?, updated_by = ?
                     WHERE case_id = ? AND revision = ?
                    """,
                    (
                        case["status"],
                        case["active_recommendation_revision"],
                        now_text,
                        creator,
                        str(case_id),
                        expected_case_revision,
                    ),
                )
                if cursor.rowcount != 1:
                    raise StoreConflict("decision case changed during brief creation")
            except sqlite3.IntegrityError as exc:
                raise StoreConflict(
                    "could not persist immutable decision brief revision"
                ) from exc

            updated_case = self._require_decision_case_row(connection, str(case_id))
            self._insert_decision_event(
                connection,
                case_id=str(case_id),
                event_type="decision_brief_created",
                actor_kind="system",
                payload={
                    "brief_id": stable_brief_id,
                    "brief_revision_id": normalized_revision_id,
                    "revision": revision,
                    "comparison_bundle_id": normalized_bundle_id,
                    "comparison_bundle_sha256": bundle_row["bundle_sha256"],
                    "recommendation_classification": classification,
                    "confidence_state": confidence,
                    "case_status": updated_case["status"],
                    "case_revision": int(updated_case["revision"]),
                },
                created_at=now_text,
            )
            stored_response = {
                "schema_version": 1,
                "brief_id": stable_brief_id,
                "brief_revision_id": normalized_revision_id,
                "case_id": str(case_id),
                "case_revision_after": int(updated_case["revision"]),
                "comparison_bundle_sha256": bundle_row["bundle_sha256"],
            }
            response_json = _json_dump(stored_response)
            connection.execute(
                """
                INSERT INTO decision_brief_idempotency (
                    case_id, idempotency_key, creation_request_sha256,
                    brief_revision_id, response_json, response_sha256,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(case_id),
                    key,
                    creation_request_sha256,
                    normalized_revision_id,
                    response_json,
                    _sha256_text(response_json),
                    now_text,
                ),
            )
            row = connection.execute(
                """
                SELECT * FROM decision_briefs WHERE brief_revision_id = ?
                """,
                (normalized_revision_id,),
            ).fetchone()
            assert row is not None
            result = self._decision_brief_record(connection, row)
            result["case"] = self._decision_case_from_row(updated_case)
            result["idempotent_replay"] = False
            return result

    def get_decision_brief(
        self, brief_revision_id: str
    ) -> dict[str, Any] | None:
        with self._transaction() as connection:
            row = connection.execute(
                """SELECT * FROM decision_briefs WHERE brief_revision_id = ?""",
                (str(brief_revision_id),),
            ).fetchone()
            return None if row is None else self._decision_brief_record(connection, row)

    def get_decision_brief_for_snapshot(
        self,
        case_id: str,
        *,
        comparison_bundle_id: str,
        expected_case_revision: int,
        comparison_bundle_sha256: str,
    ) -> dict[str, Any] | None:
        """Read the exact immutable brief snapshot without a bounded history scan."""

        if (
            isinstance(expected_case_revision, bool)
            or not isinstance(expected_case_revision, int)
            or expected_case_revision <= 0
        ):
            raise ValueError("expected_case_revision must be a positive integer")
        normalized_bundle_id = self._validate_decision_record_id(
            comparison_bundle_id,
            prefix="dcmp",
            field="comparison_bundle_id",
        )
        normalized_hash = self._validate_sha256(
            comparison_bundle_sha256,
            field="comparison_bundle_sha256",
        )
        with self._transaction() as connection:
            row = connection.execute(
                """
                SELECT * FROM decision_briefs
                 WHERE case_id = ? AND comparison_bundle_id = ?
                   AND expected_case_revision = ?
                   AND comparison_bundle_sha256 = ?
                """,
                (
                    str(case_id),
                    normalized_bundle_id,
                    expected_case_revision,
                    normalized_hash,
                ),
            ).fetchone()
            return (
                None
                if row is None
                else self._decision_brief_record(connection, row)
            )

    def list_decision_briefs(
        self,
        case_id: str,
        *,
        include_superseded: bool = True,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        bounded_limit = max(0, min(int(limit), 500))
        current_clause = (
            "" if include_superseded else " AND superseded_by_revision_id IS NULL"
        )
        with self._transaction() as connection:
            rows = connection.execute(
                "SELECT * FROM decision_briefs WHERE case_id = ?"
                + current_clause
                + " ORDER BY revision DESC, created_at DESC LIMIT ?",
                (str(case_id), bounded_limit),
            ).fetchall()
            return [self._decision_brief_record(connection, row) for row in rows]

    def mark_decision_brief_stale(
        self,
        brief_revision_id: str,
        *,
        reason: Mapping[str, Any],
        actor_kind: str = "system",
        operator_name: str | None = None,
    ) -> dict[str, Any]:
        if not isinstance(reason, Mapping) or not reason:
            raise ValueError("reason must be a non-empty object")
        reason_json = _json_dump(dict(reason))
        actor, operator = self._normalize_decision_event_actor(
            actor_kind, operator_name
        )
        now_text = _timestamp(self._current_time())
        with self._transaction(write=True) as connection:
            row = connection.execute(
                """SELECT * FROM decision_briefs WHERE brief_revision_id = ?""",
                (str(brief_revision_id),),
            ).fetchone()
            if row is None:
                raise RecordNotFound(
                    f"unknown decision brief revision: {brief_revision_id}"
                )
            if row["stale_at"] is None:
                connection.execute(
                    """
                    UPDATE decision_briefs
                       SET stale_at = ?, stale_reason_json = ?
                     WHERE brief_revision_id = ? AND stale_at IS NULL
                    """,
                    (now_text, reason_json, str(brief_revision_id)),
                )
                self._insert_decision_event(
                    connection,
                    case_id=str(row["case_id"]),
                    event_type="decision_brief_stale",
                    actor_kind=actor,
                    operator_name=operator,
                    payload={
                        "brief_id": row["brief_id"],
                        "brief_revision_id": str(brief_revision_id),
                        "comparison_bundle_sha256": row[
                            "comparison_bundle_sha256"
                        ],
                        "reason": dict(reason),
                    },
                    created_at=now_text,
                )
            elif str(row["stale_reason_json"]) != reason_json:
                raise StoreConflict("decision brief is already stale")
            updated = connection.execute(
                """SELECT * FROM decision_briefs WHERE brief_revision_id = ?""",
                (str(brief_revision_id),),
            ).fetchone()
            assert updated is not None
            return self._decision_brief_record(connection, updated)

    def supersede_decision_brief(
        self,
        brief_revision_id: str,
        *,
        superseded_by_revision_id: str,
        actor_kind: str = "system",
        operator_name: str | None = None,
    ) -> dict[str, Any]:
        """Record an already-created direct child as a one-way supersession."""

        actor, operator = self._normalize_decision_event_actor(
            actor_kind, operator_name
        )
        now_text = _timestamp(self._current_time())
        with self._transaction(write=True) as connection:
            row = connection.execute(
                """SELECT * FROM decision_briefs WHERE brief_revision_id = ?""",
                (str(brief_revision_id),),
            ).fetchone()
            if row is None:
                raise RecordNotFound(
                    f"unknown decision brief revision: {brief_revision_id}"
                )
            if row["superseded_by_revision_id"] is not None:
                if row["superseded_by_revision_id"] != superseded_by_revision_id:
                    raise StoreConflict(
                        "decision brief already has another superseding revision"
                    )
                return self._decision_brief_record(connection, row)
            target = connection.execute(
                """SELECT * FROM decision_briefs WHERE brief_revision_id = ?""",
                (str(superseded_by_revision_id),),
            ).fetchone()
            if target is None:
                raise RecordNotFound(
                    "unknown superseding decision brief revision: "
                    f"{superseded_by_revision_id}"
                )
            if any(
                (
                    target["case_id"] != row["case_id"],
                    target["brief_id"] != row["brief_id"],
                    target["parent_revision_id"] != row["brief_revision_id"],
                    int(target["revision"]) != int(row["revision"]) + 1,
                )
            ):
                raise StoreConflict("superseding brief is not the direct child")
            reason = {
                "code": "superseded_by_decision_brief_revision",
                "superseded_by_revision_id": str(superseded_by_revision_id),
            }
            connection.execute(
                """
                UPDATE decision_briefs
                   SET stale_at = COALESCE(stale_at, ?),
                       stale_reason_json = COALESCE(stale_reason_json, ?),
                       superseded_by_revision_id = ?, superseded_at = ?
                 WHERE brief_revision_id = ?
                   AND superseded_by_revision_id IS NULL
                """,
                (
                    now_text,
                    _json_dump(reason),
                    str(superseded_by_revision_id),
                    now_text,
                    str(brief_revision_id),
                ),
            )
            self._insert_decision_event(
                connection,
                case_id=str(row["case_id"]),
                event_type="decision_brief_superseded",
                actor_kind=actor,
                operator_name=operator,
                payload={
                    "brief_id": row["brief_id"],
                    "brief_revision_id": str(brief_revision_id),
                    "superseded_by_revision_id": str(
                        superseded_by_revision_id
                    ),
                    "comparison_bundle_sha256": row[
                        "comparison_bundle_sha256"
                    ],
                },
                created_at=now_text,
            )
            updated = connection.execute(
                """SELECT * FROM decision_briefs WHERE brief_revision_id = ?""",
                (str(brief_revision_id),),
            ).fetchone()
            assert updated is not None
            return self._decision_brief_record(connection, updated)

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
    "DECISION_CASE_STATES",
    "DECISION_CASE_TRANSITIONS",
    "DECISION_EVIDENCE_CLASSES",
    "DECISION_EVIDENCE_DECISIONS",
    "DECISION_EVIDENCE_MAX_CASE_BYTES",
    "DECISION_EVIDENCE_MAX_FILE_BYTES",
    "DECISION_EVIDENCE_MAX_FILES_PER_CASE",
    "DECISION_CONFIDENCE_STATES",
    "DECISION_RECOMMENDATION_CLASSIFICATIONS",
    "DECISION_TURN_STATES",
    "EvidenceLimitExceeded",
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
    "TECHNOECONOMIC_ID_PREFIX",
    "TERMINAL_JOB_STATES",
]
