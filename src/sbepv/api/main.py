"""FastAPI backend for the SB Energy dashboard.

Assembles the dashboard from ``frontend/``, accepts a from/to window + interval
(UTC), runs the historian -> model pipeline as a background job with progress,
and serves the generated PNG charts + stats back to the UI.

Run:
    uvicorn sbepv.api.main:app --app-dir src --reload --port 8000
Then open http://127.0.0.1:8000
"""

from __future__ import annotations

import base64
import binascii
from copy import deepcopy
import hashlib
import logging
import secrets
import threading
import traceback
import uuid
import math
import json
import os
import posixpath
from decimal import Decimal, InvalidOperation
from time import perf_counter
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, StrictBool

from sbepv import dashboard, model, reporting
from sbepv import technoeconomic as technoeconomic_kernel
from sbepv.api import autonomy as autonomy_api
from sbepv.api import collect_data as collect_data_api
from sbepv.api import config, job_store, plots, review_store, state
from sbepv.api import technoeconomic as technoeconomic_api
from sbepv.api import baselines as baselines_module
from sbepv.api import proposals as proposals_module
from sbepv.agent import chat as agent_chat
from sbepv.api.baselines import (
    _annual_confirmation_context,
    _annual_request_seasons,
    _calibration_conflict,
    _calibration_setting_deltas,
    _public_current_calibration,
    _reviewed_baseline_data_quality,
    _verified_baseline_source,
)
from sbepv.api.proposals import (
    _confirm_durable_proposal,
    _confirm_durable_proposals,
    _create_candidate_proposal,
)
from sbepv.api.serializers import (
    _public_job,
    _public_proposal,
    _public_saved_result,
    _public_technoeconomic_job,
    _public_value,
)
from sbepv.worker import loop as worker_loop
from sbepv.api.security import (
    _auth_required_response,
    _basic_auth_is_valid,
    _basic_auth_principal,
    _dashboard_basic_credentials,
)
from sbepv.api.static_files import PublicOutputStaticFiles
from sbepv.api.review_store import (
    _calibration_review_path,
    _calibration_review_state,
    _cleanup_expired_calibration_reviews,
    _delete_calibration_review_artifacts,
    _load_calibration_review,
    _quality_context,
)
from sbepv.agent.message_guards import (
    _ambiguous_numeric_iam,
    _visible_iam_selection,
)
from sbepv.agent.scenario_math import (
    _apply_dependent_scenario_overrides,
    _canonical_request,
    _explicit_overrides,
    _normalise_config_keys,
    _parameter_sweep_values,
    _same_input_context,
    _scenario_changes,
)
from sbepv.api.artifacts import (
    ArtifactCleanupError,
    ArtifactIntegrityError,
    _delete_job_artifacts,
    _delete_job_attempt_artifacts,
    _delete_technoeconomic_job_artifacts,
    _job_attempt_prefix,
    _output_url,
    _public_source_url,
    _verified_technoeconomic_artifact,
    _workbook_download_name,
)
from sbepv.api.job_store import (
    _JobCancelled,
    _cache_job_record,
    _check_job_cancelled,
    _get_job_record,
    _job_cancel_requested,
    _update_job,
)
from sbepv.api.request_context import (
    _ANNUAL_FALLBACK_MAPPING,
    _CALIBRATION_SETTING_FIELDS,
    _METEOROLOGICAL_SEASONS,
    _annual_submission_request,
    _iam_metadata,
    _json_sha256,
    _run_request_context,
)
from sbepv.api.timewindows import _iso, _validation_window_metadata
from sbepv.api.validation import (
    _annual_dates,
    _annual_interval_seconds,
    _efficiency,
    _finite_float,
    _request_fields_set,
    _validate_calibration_review_size,
    _validate_curtailment,
    _validate_requested_window,
    _validate_run_request,
)
from sbepv.agent.prompts import SOLAR_AGENT_INSTRUCTIONS, SOLAR_MODEL_KNOWLEDGE
from sbepv.agent.tool_schemas import (
    MAX_PARAMETER_SWEEP_VALUES,
    PARAMETER_SWEEP_FIELDS,
    PARAMETER_SWEEP_TOOL,
    SCENARIO_FIELD_LABELS,
    SCENARIO_OVERRIDE_FIELDS,
    SCENARIO_TOOL,
    SWEEPABLE_PARAMETER_CONFIG,
)
from sbepv.api.schemas import (
    ANNUAL_APPLIED_CAPACITY_NORMALIZATION,
    AnnualRunRequest,
    AnnualRunSubmission,
    CalibrationDecisionRequest,
    ChatMessage,
    ChatRequest,
    ProposalEditRequest,
    ProposalSweepConfirmRequest,
    RunRequest,
    SavedResultCreateRequest,
    SavedResultRenameRequest,
    SeasonalFallbackAcknowledgement,
    StrictRequest,
    TechnoeconomicSubmissionRequest,
)
from sbepv.ingest import bazefield as historian
from sbepv.ingest import midc
from sbepv.calibration import (
    CALIBRATION_PROFILE_SCHEMA_VERSION,
    apply_quality_decisions,
    inspect_historian_csv,
    public_quality_report,
    quality_issue_rows,
    season_name,
    validate_seasonal_calibration_profile,
)
from sbepv.store import (
    SCHEMA_VERSION as AGENT_STORE_SCHEMA_VERSION,
    AgentStore,
    AgentStoreError,
    InvalidStateTransition,
    LeaseOwnershipLost,
    QueueCapacityExceeded,
    RecordNotFound,
    SAVED_RESULTS_LIMIT,
    StoreConflict,
)
from sbepv.reporting import (
    SourceFingerprintMismatch,
    generate_comparison_artifacts,
    sha256_file,
)

logger = logging.getLogger(__name__)


_COMPAT_CONFIG_EXPORTS = frozenset(
    {
        "CALIBRATION_REVIEW_TTL",
        "OPENAI_MAX_RETRIES",
        "OPENAI_TIMEOUT_SECONDS",
        "SERVER_SESSION_ID",
    }
)


def __getattr__(name: str) -> Any:
    """Keep the former ``api.main`` settings surface without freezing values."""

    if name in _COMPAT_CONFIG_EXPORTS:
        return getattr(config, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


@asynccontextmanager
async def _app_lifespan(_app: FastAPI):
    _dashboard_basic_credentials()
    try:
        collect_data_api.reconcile_interrupted_collections()
        collect_data_api.prune_data_collections()
    except Exception:
        logger.exception(
            "Standalone data collection recovery failed; other workflows will continue"
        )
    state.AGENT_STORE.mark_stale_claimed_decision_turns_failed(
        before=datetime.now(timezone.utc)
        - timedelta(seconds=config.DECISION_AGENT_TURN_STALE_SECONDS),
        error_code="agent_interrupted",
        error_detail="The Decision Agent process stopped before the response completed.",
    )
    worker_loop._mark_stale_running_work_interrupted(
        before=datetime.now(timezone.utc)
        - timedelta(seconds=config.JOB_STALE_SECONDS)
    )
    worker_loop._start_model_worker()
    state._APP_STARTED = True
    try:
        yield
    finally:
        state._APP_STARTED = False
        await autonomy_api.shutdown_decision_agent_tasks()
        worker_loop._stop_model_worker()


app = FastAPI(title="SB Energy Dashboard", lifespan=_app_lifespan)
allowed_origins = [
    origin.strip()
    for origin in os.getenv(
        "PV_DASHBOARD_ALLOWED_ORIGINS",
        "http://localhost:3000,http://127.0.0.1:3000",
    ).split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Content-Type", "X-Autonomy-Human-Action"],
)
app.include_router(autonomy_api.router)
app.include_router(collect_data_api.router)
app.mount(
    "/outputs",
    PublicOutputStaticFiles(directory=str(config.OUTPUT_DIR)),
    name="outputs",
)


@app.middleware("http")
async def require_dashboard_basic_auth(request: Request, call_next):
    if request.url.path == "/healthz":
        return await call_next(request)
    try:
        authenticated = _basic_auth_is_valid(request.headers.get("authorization"))
    except RuntimeError:
        logger.error("Dashboard Basic authentication is only partially configured")
        return JSONResponse(
            {"detail": "Dashboard authentication is misconfigured."},
            status_code=503,
        )
    if not authenticated:
        return _auth_required_response()
    request.state.authenticated_principal = _basic_auth_principal(
        request.headers.get("authorization")
    )
    request_path = request.url.path.replace("\\", "/")
    normalized_path = posixpath.normpath(
        "/" + request_path.lstrip("/")
    )
    # Win32 path lookup is case-insensitive and ignores trailing dots/spaces in
    # path components. Normalize those aliases before applying the denylist.
    normalized_path = "/".join(
        component.rstrip(" .").casefold()
        for component in normalized_path.split("/")
    ).rstrip("/")
    private_roots = (
        "/outputs/.agent_state",
        "/outputs/.annual_sources",
        "/outputs/.calibration_reviews",
        "/outputs/.data_collections",
        "/outputs/.decision_evidence",
        "/outputs/.decision_reports",
        "/outputs/.technoeconomic_attempts",
    )
    if any(
        normalized_path == root or normalized_path.startswith(f"{root}/")
        for root in private_roots
    ):
        return JSONResponse({"detail": "Not found."}, status_code=404)
    return await call_next(request)


@app.get("/")
def index() -> HTMLResponse:
    return HTMLResponse(
        dashboard.render_dashboard(config.PROJECT_ROOT),
        headers={"Cache-Control": "no-store"},
    )


@app.get("/annual-warning.png", include_in_schema=False)
def annual_warning_icon() -> FileResponse:
    """Serve the warning asset shared by direct FastAPI and Vinext previews."""

    return FileResponse(
        str(config.PROJECT_ROOT / "public" / "annual-warning.png"),
        media_type="image/png",
    )


@app.get("/healthz")
def healthz() -> JSONResponse:
    failures: list[str] = []
    try:
        _dashboard_basic_credentials()
    except RuntimeError:
        failures.append("authentication configuration")
    try:
        if state.AGENT_STORE.schema_version != AGENT_STORE_SCHEMA_VERSION:
            failures.append("state schema")
    except Exception:
        logger.exception("Health check could not read durable state")
        failures.append("durable state")
    if not config.OUTPUT_DIR.is_dir() or not os.access(config.OUTPUT_DIR, os.W_OK):
        failures.append("output directory")
    worker = state._WORKER_THREAD
    if state._APP_STARTED and (worker is None or not worker.is_alive()):
        failures.append("model worker")
    if failures:
        return JSONResponse(
            {"status": "unavailable", "failed_checks": failures},
            status_code=503,
        )
    return JSONResponse({"status": "ok"})


@app.get("/api/session")
def session() -> JSONResponse:
    promoted = {
        mode: (state.AGENT_STORE.get_current_baseline(mode) or {}).get("job_id")
        for mode in ("validation", "annual")
    }
    return JSONResponse(
        {
            "session_id": config.SERVER_SESSION_ID,
            "promoted_baselines": promoted,
        }
    )


@app.get("/api/current-calibration")
def current_calibration() -> JSONResponse:
    """Return the sanitized current promoted, reviewed calibration summary."""

    with state._ORCHESTRATION_LOCK:
        try:
            bundle = baselines_module._current_calibration_bundle()
        except (AgentStoreError, HTTPException, KeyError, OSError, TypeError, ValueError):
            logger.warning(
                "The promoted calibration could not be verified for annual use",
                exc_info=True,
            )
            bundle = None
    if bundle is None:
        return JSONResponse({"available": False})
    return JSONResponse(_public_current_calibration(bundle))


def _enqueue_baseline_job(
    mode: Literal["validation", "annual"],
    request_snapshot: dict[str, Any],
    *,
    job_id: str | None = None,
    source_path: str | None = None,
    source_hash: str | None = None,
    provenance: dict[str, Any] | None = None,
    artifacts: dict[str, Any] | None = None,
) -> dict[str, Any]:
    with state._ORCHESTRATION_LOCK:
        try:
            record = state.AGENT_STORE.create_job(
                kind="baseline",
                mode=mode,
                request=request_snapshot,
                job_id=job_id or uuid.uuid4().hex[:12],
                source_path=source_path,
                source_hash=source_hash,
                provenance=provenance,
                artifacts=artifacts,
                max_active_jobs=config.MAX_ACTIVE_MODEL_JOBS,
            )
        except QueueCapacityExceeded as exc:
            raise HTTPException(
                status_code=429,
                detail="The model queue is full. Wait for an active run to finish and retry.",
            ) from exc
        _cache_job_record(record)
        state._WORKER_WAKE.set()
        return record


@app.post("/api/calibration-reviews")
def create_calibration_review(req: RunRequest) -> JSONResponse:
    """Retrieve Bazefield data and return issues before model calibration."""

    if not req.calibrate_model:
        raise HTTPException(
            status_code=422,
            detail=(
                "Data-quality decisions are only required when model calibration "
                "is selected. Use POST /api/run for an uncalibrated model run."
            ),
        )
    _validate_run_request(req)
    _validate_curtailment(req)
    with state._ORCHESTRATION_LOCK:
        _cleanup_expired_calibration_reviews()
    review_id = uuid.uuid4().hex
    interval_seconds = (
        int(req.interval_value) * config.UNIT_SECONDS[req.interval_unit]
    )
    source_path = _calibration_review_path(review_id, ".raw.csv")
    from_iso = _iso(req.from_date, req.from_time)
    to_iso = _iso(req.to_date, req.to_time)
    _validate_calibration_review_size(
        from_iso=from_iso,
        to_iso=to_iso,
        interval_seconds=interval_seconds,
    )
    try:
        row_count = historian.run_historian(
            from_time=from_iso,
            to_time=to_iso,
            interval=str(interval_seconds),
            output_csv=str(source_path),
        )
        if int(row_count) > config.CALIBRATION_REVIEW_MAX_ROWS:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Bazefield returned {int(row_count):,} rows; calibration "
                    f"reviews are limited to {config.CALIBRATION_REVIEW_MAX_ROWS:,} rows."
                ),
            )
        source_hash = sha256_file(source_path)
        report = inspect_historian_csv(
            source_path,
            expected_interval_seconds=interval_seconds,
            requested_start=from_iso,
            requested_end=to_iso,
        )
        profiled_rows = int((report.get("source") or {}).get("row_count") or 0)
        if profiled_rows > config.CALIBRATION_REVIEW_MAX_ROWS:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Bazefield returned {profiled_rows:,} rows; calibration "
                    f"reviews are limited to {config.CALIBRATION_REVIEW_MAX_ROWS:,} rows."
                ),
            )
    except HTTPException:
        _delete_calibration_review_artifacts(review_id)
        raise
    except historian.BazefieldError as exc:
        _delete_calibration_review_artifacts(review_id)
        raise HTTPException(
            status_code=502,
            detail=f"Bazefield data retrieval failed: {exc}",
        ) from exc
    except (OSError, TypeError, ValueError) as exc:
        _delete_calibration_review_artifacts(review_id)
        raise HTTPException(
            status_code=422,
            detail=f"Bazefield data could not be profiled: {exc}",
        ) from exc

    report["source"]["sha256"] = source_hash
    now = datetime.now(timezone.utc)
    record = {
        "review_id": review_id,
        "state": "pending",
        "created_at": now.isoformat(),
        "expires_at": (now + config.CALIBRATION_REVIEW_TTL).isoformat(),
        "request": _run_request_context(req),
        "source_path": str(source_path.resolve()),
        "source_hash": source_hash,
        "source_row_count": int(row_count),
        "report": report,
    }
    try:
        review_store._save_calibration_review(record)
    except (OSError, TypeError, ValueError) as exc:
        _delete_calibration_review_artifacts(review_id)
        raise HTTPException(
            status_code=500,
            detail="The calibration review could not be stored; try again.",
        ) from exc
    return JSONResponse(
        {
            "review_id": review_id,
            "state": _calibration_review_state(report),
            "created_at": record["created_at"],
            "expires_at": record["expires_at"],
            "report": public_quality_report(report),
        }
    )


@app.post("/api/calibration-reviews/{review_id}/run")
def run_reviewed_calibration(
    review_id: str,
    req: CalibrationDecisionRequest,
) -> JSONResponse:
    """Apply audited decisions and enqueue calibration from the reviewed source."""

    with state._ORCHESTRATION_LOCK:
        record = _load_calibration_review(review_id)
        canonical_decisions = {
            str(key): str(value)
            for key, value in sorted(req.decisions.items())
        }
        if record.get("state") == "consumed":
            if canonical_decisions != (record.get("decisions") or {}):
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "This review already started with different decisions; "
                        "retrieve the data again for another calibration."
                    ),
                )
            job = _get_job_record(str(record["job_id"]))
            if job is None:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "This review references a job that is no longer available; "
                        "retrieve the data again."
                    ),
                )
            return JSONResponse(
                {
                    "job_id": job["id"],
                    "review_id": record["review_id"],
                    "state": job["state"],
                    "data_quality": record.get("quality_context"),
                }
            )
        if record.get("state") != "pending":
            raise HTTPException(
                status_code=409,
                detail="This calibration review can no longer start a run.",
            )

        decision_payload = json.dumps(
            canonical_decisions,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        decision_digest = hashlib.sha256(decision_payload).hexdigest()[:16]
        cleaned_path = _calibration_review_path(
            review_id,
            f".{decision_digest}.reviewed.csv",
        )
        try:
            cleaning = apply_quality_decisions(
                record["source_path"],
                cleaned_path,
                record["report"],
                canonical_decisions,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        cleaned_hash = sha256_file(cleaned_path)
        quality_context = _quality_context(
            record,
            cleaning=cleaning,
            reviewed_source_hash=cleaned_hash,
            submitted_decisions=canonical_decisions,
        )
        deterministic_job_id = f"review-{review_id}"
        try:
            job = _enqueue_baseline_job(
                "validation",
                dict(record["request"]),
                job_id=deterministic_job_id,
                source_path=str(cleaned_path.resolve()),
                source_hash=cleaned_hash,
                provenance={"data_quality": quality_context},
            )
        except StoreConflict as exc:
            existing = _get_job_record(deterministic_job_id)
            existing_quality = (
                (existing or {}).get("provenance") or {}
            ).get("data_quality")
            same_review = (
                isinstance(existing_quality, dict)
                and existing_quality.get("review_id") == review_id
                and existing_quality.get("submitted_decisions")
                == canonical_decisions
                and existing_quality.get("reviewed_source_sha256")
                == cleaned_hash
                and (existing or {}).get("source_hash") == cleaned_hash
            )
            if not same_review:
                try:
                    cleaned_path.unlink(missing_ok=True)
                except OSError:
                    logger.warning(
                        "Could not remove conflicting reviewed source %s",
                        cleaned_path,
                        exc_info=True,
                    )
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "This review already started with different decisions; "
                        "retrieve the data again for another calibration."
                    ),
                ) from exc
            job = existing
            quality_context = existing_quality
            cleaned_path = Path(str(job["source_path"]))
            cleaned_hash = str(job["source_hash"])
        record.update(
            {
                "state": "consumed",
                "decisions": canonical_decisions,
                "cleaned_source_path": str(cleaned_path.resolve()),
                "cleaned_source_hash": cleaned_hash,
                "quality_context": quality_context,
                "job_id": job["id"],
                "consumed_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        try:
            review_store._save_calibration_review(record)
        except (OSError, TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=500,
                detail=(
                    "The calibration job started, but its review receipt could "
                    "not be stored. Retry the same decisions to recover the job."
                ),
            ) from exc
        return JSONResponse(
            {
                "job_id": job["id"],
                "review_id": review_id,
                "state": job["state"],
                "data_quality": quality_context,
            }
        )


def _legacy_unreviewed_run_enabled() -> bool:
    return os.getenv(
        "PV_DASHBOARD_ENABLE_LEGACY_RUN", ""
    ).strip().lower() in {
        "1",
        "true",
        "yes",
    }


@app.post("/api/run")
def start_run(req: RunRequest) -> JSONResponse:
    if req.calibrate_model and not _legacy_unreviewed_run_enabled():
        raise HTTPException(
            status_code=410,
            detail=(
                "Direct calibration runs are retired. Start with "
                "POST /api/calibration-reviews, review the detected issues, "
                "then submit decisions to the returned review run endpoint."
            ),
        )
    _validate_run_request(req)
    _validate_curtailment(req)
    job = _enqueue_baseline_job("validation", _run_request_context(req))
    return JSONResponse({"job_id": job["id"]})


@app.get("/api/calibration-reviews/{review_id}/rows")
def calibration_review_rows(
    review_id: str,
    issue_id: str,
    offset: int = 0,
    limit: int = 50,
    all_rows: bool = False,
) -> JSONResponse:
    """Return bounded hash-verified rows, or all rows when explicitly requested."""

    with state._ORCHESTRATION_LOCK:
        record = _load_calibration_review(review_id)
    try:
        page = quality_issue_rows(
            record["source_path"],
            record["report"],
            issue_id,
            offset=offset,
            limit=None if all_rows else limit,
        )
        reporting.verify_source_sha256(record["source_path"], record["source_hash"])
    except SourceFingerprintMismatch as exc:
        raise HTTPException(
            status_code=409,
            detail="The reviewed Bazefield source changed; retrieve it again.",
        ) from exc
    except (KeyError, OSError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return JSONResponse(page)


@app.post("/api/annual-run")
def start_annual_run(req: AnnualRunSubmission) -> JSONResponse:
    selected_baseline = req.calibration_baseline_job_id
    if selected_baseline is None:
        if req.seasonal_fallback_acknowledgement is not None:
            raise HTTPException(
                status_code=422,
                detail=(
                    "A seasonal fallback acknowledgement requires a selected "
                    "calibration baseline."
                ),
            )
        _, annual_request = _annual_submission_request(req)
        job = _enqueue_baseline_job("annual", annual_request)
        return JSONResponse({"job_id": job["id"]})

    selected_baseline = str(selected_baseline).strip()
    if not selected_baseline:
        raise HTTPException(
            status_code=422,
            detail="calibration_baseline_job_id must not be blank.",
        )
    # Reject malformed annual input independently of baseline availability.
    _annual_submission_request(deepcopy(req))

    with state._ORCHESTRATION_LOCK:
        try:
            bundle = baselines_module._current_calibration_bundle()
        except (AgentStoreError, HTTPException, KeyError, OSError, TypeError, ValueError):
            logger.warning(
                "The selected annual calibration baseline could not be verified",
                exc_info=True,
            )
            bundle = None
        if bundle is None:
            raise _calibration_conflict(
                "calibration_baseline_unavailable",
                "No promoted, reviewed calibration is currently available.",
            )

        baseline = bundle["baseline"]
        current_baseline_id = str(baseline["id"])
        if not secrets.compare_digest(selected_baseline, current_baseline_id):
            raise _calibration_conflict(
                "calibration_baseline_changed",
                "The promoted calibration changed. Refresh the annual configuration.",
                requested_baseline_job_id=selected_baseline,
                current_baseline_job_id=current_baseline_id,
            )

        _, annual_request = _annual_submission_request(
            req,
            inherited_settings=bundle["settings"],
        )
        required_seasons = _annual_request_seasons(annual_request)
        origin_profile = deepcopy(bundle["profile"])
        available_factors = origin_profile["seasonal_factors"]
        missing_seasons = [
            season for season in required_seasons if season not in available_factors
        ]
        settings_deltas = _calibration_setting_deltas(
            bundle["settings"], annual_request
        )
        resolved_profile = deepcopy(origin_profile)
        substitution: dict[str, Any] | None = None
        server_confirmation: dict[str, Any] | None = None
        server_timestamp = datetime.now(timezone.utc).isoformat()

        if missing_seasons:
            fall_from_spring_supported = (
                set(missing_seasons) == {"fall"} and "spring" in available_factors
            )
            if not fall_from_spring_supported:
                raise _calibration_conflict(
                    "seasonal_calibration_coverage_missing",
                    (
                        "The selected calibration does not cover every season required "
                        "by this annual range. Only an explicit Fall from Spring "
                        "substitution is supported."
                    ),
                    required_seasons=list(required_seasons),
                    missing_seasons=missing_seasons,
                    available_seasons=[
                        season
                        for season in _METEOROLOGICAL_SEASONS
                        if season in available_factors
                    ],
                )

            confirmation_context = _annual_confirmation_context(
                baseline_job_id=current_baseline_id,
                profile_sha256=bundle["profile_sha256"],
                annual_request=annual_request,
                required_seasons=required_seasons,
            )
            confirmation_sha256 = _json_sha256(confirmation_context)
            acknowledgement = req.seasonal_fallback_acknowledgement
            confirmation_detail = {
                "baseline_job_id": current_baseline_id,
                "profile_sha256": bundle["profile_sha256"],
                "mapping": deepcopy(_ANNUAL_FALLBACK_MAPPING),
                "spring_factors": deepcopy(available_factors["spring"]),
                "required_seasons": list(required_seasons),
                "modified_settings": deepcopy(settings_deltas),
                "confirmation_context_sha256": confirmation_sha256,
            }
            if acknowledgement is None:
                raise _calibration_conflict(
                    "seasonal_fallback_confirmation_required",
                    (
                        "Fall factors are unavailable. Confirm whether the exact "
                        "reviewed Spring factors should be used for Fall."
                    ),
                    **confirmation_detail,
                )
            if acknowledgement.accepted is not True:
                raise _calibration_conflict(
                    "seasonal_fallback_confirmation_invalid",
                    "The Fall from Spring substitution was not explicitly accepted.",
                    **confirmation_detail,
                )
            submitted_context_sha256 = str(
                acknowledgement.confirmation_context_sha256
            ).strip().lower()
            if not secrets.compare_digest(
                submitted_context_sha256, confirmation_sha256
            ):
                raise _calibration_conflict(
                    "seasonal_fallback_confirmation_context_changed",
                    (
                        "The calibration or annual request changed after confirmation. "
                        "Review the current Spring factors and confirm again."
                    ),
                    **confirmation_detail,
                )

            resolved_profile["seasonal_factors"]["fall"] = deepcopy(
                available_factors["spring"]
            )
            substitution = {
                **deepcopy(_ANNUAL_FALLBACK_MAPPING),
                "factors": deepcopy(available_factors["spring"]),
                "explicitly_accepted": True,
            }
            server_confirmation = {
                "accepted": True,
                "mapping": deepcopy(_ANNUAL_FALLBACK_MAPPING),
                "confirmation_context_sha256": confirmation_sha256,
                "recorded_at": server_timestamp,
            }
        elif req.seasonal_fallback_acknowledgement is not None:
            raise _calibration_conflict(
                "seasonal_fallback_not_required",
                "The selected calibration already covers every required season.",
                required_seasons=list(required_seasons),
            )

        resolved_profile = validate_seasonal_calibration_profile(
            resolved_profile,
            required_seasons=required_seasons,
        )
        resolved_profile_sha256 = _json_sha256(resolved_profile)
        calibration_application = {
            "baseline_job_id": current_baseline_id,
            "baseline_review_id": str(bundle["quality"]["review_id"]),
            "baseline_promoted_at": bundle["promotion"].get("promoted_at"),
            "server_timestamp": server_timestamp,
            "origin_profile_sha256": bundle["profile_sha256"],
            "resolved_profile_sha256": resolved_profile_sha256,
            "origin_profile": origin_profile,
            "resolved_profile": resolved_profile,
            "required_seasons": list(required_seasons),
            "seasonal_substitution": substitution,
            "settings_deltas": settings_deltas,
            "server_confirmation": server_confirmation,
        }
        provenance = {
            "calibration_profile": resolved_profile,
            "calibration_application": calibration_application,
        }

        # Re-read immediately before enqueueing so a promotion that occurred while
        # resolving settings/factors cannot silently bind the job to stale state.
        try:
            rechecked = baselines_module._current_calibration_bundle()
        except (AgentStoreError, HTTPException, KeyError, OSError, TypeError, ValueError):
            rechecked = None
        if (
            rechecked is None
            or str(rechecked["baseline"]["id"]) != current_baseline_id
            or not secrets.compare_digest(
                str(rechecked["profile_sha256"]), str(bundle["profile_sha256"])
            )
        ):
            raise _calibration_conflict(
                "calibration_baseline_changed",
                "The promoted calibration changed before the run was queued.",
                requested_baseline_job_id=selected_baseline,
                current_baseline_job_id=(
                    str(rechecked["baseline"]["id"]) if rechecked else None
                ),
            )

        job = _enqueue_baseline_job(
            "annual",
            annual_request,
            provenance=provenance,
        )
    return JSONResponse({"job_id": job["id"]})


def _completed_calibrated_annual_source(job: dict[str, Any]) -> bool:
    """Return whether a durable row is worth running through the TEA verifier."""

    if job.get("mode") != "annual" or job.get("state") != "done":
        return False
    result = job.get("result")
    if not isinstance(result, dict):
        return False
    stats = result.get("stats")
    application = result.get("calibration_application")
    return (
        isinstance(stats, dict)
        and stats.get("calibration_enabled") is True
        and isinstance(application, dict)
        and application.get("applied") is True
    )


def _public_annual_source_context(job: dict[str, Any]) -> dict[str, Any]:
    """Project only non-sensitive Annual identity and calibration lineage."""

    request = job.get("request") if isinstance(job.get("request"), dict) else {}
    result = job.get("result") if isinstance(job.get("result"), dict) else {}
    curtailment_enabled = request.get("curtailment_enabled") is True
    application = (
        result.get("calibration_application")
        if isinstance(result.get("calibration_application"), dict)
        else {}
    )
    return {
        "kind": job.get("kind"),
        "created_at": job.get("created_at"),
        "completed_at": job.get("completed_at"),
        "annual_window": {
            key: deepcopy(request.get(key))
            for key in (
                "from_date",
                "to_date",
                "years",
                "interval_value",
                "interval_unit",
            )
            if key in request
        },
        "operating_limit": {
            "curtailment_enabled": curtailment_enabled,
            "curtailment_limit_kw": (
                deepcopy(request.get("curtailment_limit_kw"))
                if curtailment_enabled
                else None
            ),
            "unit": "kWac",
        },
        "calibration": {
            key: deepcopy(application.get(key))
            for key in (
                "baseline_job_id",
                "baseline_review_id",
                "baseline_promoted_at",
                "origin_profile_sha256",
                "resolved_profile_sha256",
                "seasonal_substitution",
            )
            if key in application
        },
    }


@app.get("/api/technoeconomic/sources")
def eligible_technoeconomic_sources() -> JSONResponse:
    """List completed calibrated Annual jobs with fail-closed TEA eligibility."""

    candidates = state.AGENT_STORE.list_jobs(
        states=("done",),
        mode="annual",
        limit=None,
    )
    sources: list[dict[str, Any]] = []
    for annual_job in candidates:
        if not _completed_calibrated_annual_source(annual_job):
            continue
        try:
            dependencies = technoeconomic_api.resolve_annual_source_dependencies(
                state.AGENT_STORE,
                str(annual_job["id"]),
            )
            eligibility = technoeconomic_api.inspect_annual_source_eligibility(
                dependencies["annual_job"],
                origin_validation_job=dependencies["origin_validation_job"],
                promotion_record=dependencies["promotion_record"],
            )
        except technoeconomic_api.AnnualSourceValidationError as exc:
            eligibility = {
                "eligible": False,
                "reason_code": exc.code,
                "detail": exc.detail,
                "source_annual_job_id": annual_job.get("id"),
            }
        except (AgentStoreError, KeyError, OSError, TypeError, ValueError):
            logger.warning(
                "Could not inspect Annual source %s for technoeconomic eligibility",
                annual_job.get("id"),
                exc_info=True,
            )
            eligibility = {
                "eligible": False,
                "reason_code": "annual_source_unverifiable",
                "detail": "The Annual source provenance could not be verified.",
                "source_annual_job_id": annual_job.get("id"),
            }
        eligibility["provenance"] = _public_annual_source_context(annual_job)
        sources.append(_public_value(eligibility))
    return JSONResponse(
        {
            "eligibility_version": (
                technoeconomic_api.ANNUAL_SOURCE_ELIGIBILITY_VERSION
            ),
            "sources": sources,
        }
    )


@app.post("/api/technoeconomic/jobs", status_code=202)
def create_technoeconomic_job(
    req: TechnoeconomicSubmissionRequest,
) -> JSONResponse:
    """Verify, freeze, validate, and enqueue one probabilistic TEA job."""

    if (
        req.basis == "solartac_site"
        and req.capacity_normalization
        != ANNUAL_APPLIED_CAPACITY_NORMALIZATION
    ):
        raise HTTPException(
            status_code=422,
            detail=(
                "New SolarTAC jobs must declare "
                "capacity_normalization='annual_applied_capacity_v1'."
            ),
        )

    request_payload = req.model_dump(mode="json", exclude_none=False)
    if req.capacity_normalization is None:
        request_payload.pop("capacity_normalization", None)
    if req.commercial_scaling is None:
        request_payload.pop("commercial_scaling", None)
    if getattr(req, "standalone_commercial", None) is None:
        request_payload.pop("standalone_commercial", None)
    if getattr(req, "paired_commercial", None) is None:
        request_payload.pop("paired_commercial", None)
    try:
        with state._ORCHESTRATION_LOCK:
            if state.AGENT_STORE.get_job(req.source_annual_job_id) is None:
                raise HTTPException(status_code=404, detail="Unknown Annual source id")
            dependencies = technoeconomic_api.resolve_annual_source_dependencies(
                state.AGENT_STORE,
                req.source_annual_job_id,
            )
            snapshot_envelope = technoeconomic_api.build_annual_source_snapshot(
                dependencies["annual_job"],
                origin_validation_job=dependencies["origin_validation_job"],
                promotion_record=dependencies["promotion_record"],
            )
            kernel_request = (
                technoeconomic_api.build_technoeconomic_kernel_request(
                    request_payload,
                    snapshot_envelope["source_snapshot"],
                )
            )
            submission_provenance = (
                technoeconomic_api.build_technoeconomic_submission_provenance(
                    request_payload,
                    snapshot_envelope,
                    kernel_request,
                )
            )
            source_fields = technoeconomic_api.technoeconomic_source_store_fields(
                snapshot_envelope
            )
            job = state.AGENT_STORE.create_technoeconomic_job(
                request=request_payload,
                submission_provenance=submission_provenance,
                max_active_jobs=config.MAX_ACTIVE_MODEL_JOBS,
                **source_fields,
            )
    except HTTPException:
        raise
    except technoeconomic_api.AnnualSourceValidationError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": exc.code, "message": exc.detail},
        ) from exc
    except technoeconomic_kernel.TechnoeconomicValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RecordNotFound as exc:
        raise HTTPException(status_code=404, detail="Unknown Annual source id") from exc
    except QueueCapacityExceeded as exc:
        raise HTTPException(
            status_code=429,
            detail="The shared work queue is full. Wait for active work to finish.",
        ) from exc
    except (InvalidStateTransition, StoreConflict) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    state._WORKER_WAKE.set()
    return JSONResponse(
        {"job": _public_technoeconomic_job(job)},
        status_code=202,
    )


@app.get("/api/technoeconomic/jobs/{job_id}")
def technoeconomic_status(job_id: str) -> JSONResponse:
    job = state.AGENT_STORE.get_technoeconomic_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown technoeconomic job id")
    return JSONResponse(_public_technoeconomic_job(job))


def _technoeconomic_export_response(job_id: str, export_format: str) -> FileResponse:
    job = state.AGENT_STORE.get_technoeconomic_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown technoeconomic job id")
    if job.get("state") != "done":
        raise HTTPException(
            status_code=409,
            detail="Technoeconomic exports are available only after completion.",
        )
    try:
        artifact_path, artifact = _verified_technoeconomic_artifact(
            job,
            export_format,
        )
    except (ArtifactIntegrityError, ValueError) as exc:
        logger.warning(
            "Rejected unverifiable %s export for technoeconomic job %s",
            export_format,
            job_id,
            exc_info=True,
        )
        raise HTTPException(
            status_code=409,
            detail=(
                "The requested technoeconomic export could not be verified. "
                "Re-run the analysis to create a new immutable export."
            ),
        ) from exc
    return FileResponse(
        artifact_path,
        media_type=str(artifact["media_type"]),
        filename=str(artifact["filename"]),
        headers={
            "Cache-Control": "private, no-store",
            "ETag": f'"sha256-{artifact["sha256"]}"',
            "X-Content-Type-Options": "nosniff",
        },
    )


@app.get("/api/technoeconomic/jobs/{job_id}/exports/csv")
def download_technoeconomic_csv(job_id: str) -> FileResponse:
    """Download the verified UTF-8 CSV table bundle for one completed TEA."""

    return _technoeconomic_export_response(job_id, "csv")


@app.get("/api/technoeconomic/jobs/{job_id}/exports/xlsx")
def download_technoeconomic_xlsx(job_id: str) -> FileResponse:
    """Download the verified workbook for one completed TEA."""

    return _technoeconomic_export_response(job_id, "xlsx")


@app.get(
    "/api/technoeconomic/jobs/{job_id}/artifacts/{artifact_id}",
    response_class=FileResponse,
)
def download_technoeconomic_plot(job_id: str, artifact_id: str) -> FileResponse:
    """Serve one literal allowlisted public plot from a completed TEA manifest."""

    if artifact_id not in {
        "cdf_plot",
        "sensitivity_plot",
        "convergence_plot",
    }:
        raise HTTPException(status_code=404, detail="Unknown technoeconomic artifact")
    job = state.AGENT_STORE.get_technoeconomic_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown technoeconomic job id")
    if job.get("state") != "done":
        raise HTTPException(
            status_code=409,
            detail="Technoeconomic artifacts are available only after completion.",
        )
    try:
        artifact_path, artifact = _verified_technoeconomic_artifact(
            job,
            artifact_id,
        )
    except (ArtifactIntegrityError, ValueError) as exc:
        logger.warning(
            "Rejected unverifiable %s for technoeconomic job %s",
            artifact_id,
            job_id,
            exc_info=True,
        )
        raise HTTPException(
            status_code=409,
            detail=(
                "The requested technoeconomic artifact could not be verified. "
                "Re-run the analysis to create a new immutable artifact."
            ),
        ) from exc
    return FileResponse(
        artifact_path,
        media_type="image/png",
        filename=str(artifact["filename"]),
        content_disposition_type="inline",
        headers={
            "Cache-Control": "private, no-store",
            "ETag": f'"sha256-{artifact["sha256"]}"',
            "X-Content-Type-Options": "nosniff",
        },
    )


@app.post("/api/technoeconomic/jobs/{job_id}/cancel")
def cancel_technoeconomic_job(job_id: str) -> JSONResponse:
    try:
        job = state.AGENT_STORE.cancel_technoeconomic_job(job_id)
    except RecordNotFound as exc:
        raise HTTPException(status_code=404, detail="Unknown technoeconomic job id") from exc
    except InvalidStateTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    state._WORKER_WAKE.set()
    return JSONResponse({"job": _public_technoeconomic_job(job)})


@app.post("/api/technoeconomic/jobs/{job_id}/retry", status_code=202)
def retry_technoeconomic_job(job_id: str) -> JSONResponse:
    try:
        job = state.AGENT_STORE.retry_technoeconomic_job(
            job_id,
            max_active_jobs=config.MAX_ACTIVE_MODEL_JOBS,
        )
    except RecordNotFound as exc:
        raise HTTPException(status_code=404, detail="Unknown technoeconomic job id") from exc
    except InvalidStateTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except QueueCapacityExceeded as exc:
        raise HTTPException(
            status_code=429,
            detail="The shared work queue is full. Wait for active work to finish.",
        ) from exc
    state._WORKER_WAKE.set()
    return JSONResponse(
        {"job": _public_technoeconomic_job(job)},
        status_code=202,
    )


@app.delete("/api/technoeconomic/jobs/{job_id}")
def delete_technoeconomic_job(job_id: str) -> JSONResponse:
    with state._ORCHESTRATION_LOCK:
        artifacts_deleted = 0

        def cleanup_before_delete(job: dict[str, Any]) -> None:
            nonlocal artifacts_deleted
            artifacts_deleted = _delete_technoeconomic_job_artifacts(
                job,
                require_complete=True,
            )

        try:
            state.AGENT_STORE.delete_technoeconomic_job(
                job_id,
                before_delete=cleanup_before_delete,
            )
        except RecordNotFound as exc:
            raise HTTPException(
                status_code=404,
                detail="Unknown technoeconomic job id",
            ) from exc
        except InvalidStateTransition as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ArtifactCleanupError as exc:
            raise HTTPException(
                status_code=409,
                detail=(
                    "The technoeconomic job was retained because its confined "
                    "artifacts could not be completely removed. Retry deletion."
                ),
            ) from exc
    return JSONResponse(
        {
            "job_id": job_id,
            "deleted": True,
            "artifacts_deleted": artifacts_deleted,
        }
    )


@app.get("/api/status/{job_id}")
def status(job_id: str) -> JSONResponse:
    job = _get_job_record(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown job id")
    return JSONResponse(_public_job(job))


def _history_activity_key(job: dict[str, Any]) -> tuple[str, str]:
    provenance = job.get("provenance") or {}
    sweep = (
        provenance.get("scenario_sweep")
        if isinstance(provenance, dict)
        else None
    )
    if isinstance(sweep, dict) and sweep.get("type") == "parameter_sweep":
        sweep_id = str(sweep.get("sweep_id") or "").strip()
        if sweep_id:
            return "sweep", sweep_id
    return "job", str(job.get("id") or "")


def _recent_history_jobs(
    terminal_jobs: list[dict[str, Any]], *, activity_limit: int
) -> list[dict[str, Any]]:
    """Keep the newest logical activities without splitting parameter sweeps."""

    if activity_limit <= 0:
        return []

    selected_keys: list[tuple[str, str]] = []
    selected_set: set[tuple[str, str]] = set()
    for job in terminal_jobs:
        key = _history_activity_key(job)
        if key in selected_set:
            continue
        if len(selected_keys) >= activity_limit:
            break
        selected_keys.append(key)
        selected_set.add(key)
    return [
        job for job in terminal_jobs if _history_activity_key(job) in selected_set
    ]


@app.get("/api/agent/state")
def agent_state(mode: Literal["validation", "annual"] | None = None) -> JSONResponse:
    history_limit = 10
    # One logical sweep may contain MAX_PARAMETER_SWEEP_VALUES durable jobs.
    # Read enough terminal rows to select ten logical activities atomically.
    snapshot = state.AGENT_STORE.snapshot_state(
        mode=mode,
        recent_limit=history_limit * MAX_PARAMETER_SWEEP_VALUES,
    )
    recent_jobs = _recent_history_jobs(
        snapshot.get("recent_jobs", []), activity_limit=history_limit
    )
    selected_sweep_ids = [
        key
        for kind, key in dict.fromkeys(
            _history_activity_key(item) for item in recent_jobs
        )
        if kind == "sweep"
    ]
    if selected_sweep_ids:
        jobs_by_id = {str(item["id"]): item for item in recent_jobs}
        for item in state.AGENT_STORE.list_parameter_sweep_jobs(
            selected_sweep_ids,
            mode=mode,
        ):
            jobs_by_id.setdefault(str(item["id"]), item)
        recent_jobs = list(jobs_by_id.values())
    active_sweep_ids = [
        key
        for kind, key in dict.fromkeys(
            _history_activity_key(item)
            for item in [
                snapshot.get("active_job"),
                *snapshot.get("queued_jobs", []),
            ]
            if item
        )
        if kind == "sweep"
    ]
    active_sweep_terminal_members = (
        state.AGENT_STORE.list_parameter_sweep_jobs(active_sweep_ids, mode=mode)
        if active_sweep_ids
        else []
    )
    proposals = [
        _public_proposal(item) for item in snapshot.get("pending_proposals", [])
    ]
    jobs_by_id: dict[str, dict[str, Any]] = {}
    for item in [
        snapshot.get("active_job"),
        *snapshot.get("queued_jobs", []),
        *recent_jobs,
        *active_sweep_terminal_members,
        *[
            baseline.get("job")
            for baseline in snapshot.get("current_baselines", {}).values()
        ],
    ]:
        if item:
            jobs_by_id[str(item["id"])] = _public_job(item)
    baselines = {"validation": None, "annual": None}
    for baseline_mode, item in snapshot.get("current_baselines", {}).items():
        baselines[baseline_mode] = item.get("job_id")
    return JSONResponse(
        {
            "proposals": proposals,
            "jobs": list(jobs_by_id.values()),
            "recent_job_ids": [
                str(item["id"]) for item in recent_jobs
            ],
            "recent_activity_count": len(
                {_history_activity_key(item) for item in recent_jobs}
            ),
            "history_limit": history_limit,
            "promoted_baselines": baselines,
        }
    )


def _proposal_or_404(proposal_id: str) -> dict[str, Any]:
    proposal = state.AGENT_STORE.get_proposal(proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail="Unknown proposal id")
    return proposal


def _proposal_parameter_sweep(
    proposal: dict[str, Any],
) -> dict[str, Any] | None:
    metadata = proposal.get("confirmation_metadata") or {}
    sweep = metadata.get("scenario_sweep")
    if not isinstance(sweep, dict) or sweep.get("type") != "parameter_sweep":
        return None
    return sweep


def _parameter_sweep_confirmation_proposals(
    sweep_id: str, proposal_ids: list[str]
) -> list[dict[str, Any]]:
    """Resolve and verify the exact, complete proposal set for one sweep."""

    normalized_id = str(sweep_id).strip()
    normalized_proposal_ids = [str(item).strip() for item in proposal_ids]
    if not normalized_id or any(not item for item in normalized_proposal_ids):
        raise HTTPException(status_code=422, detail="Sweep and proposal ids are required")
    if len(set(normalized_proposal_ids)) != len(normalized_proposal_ids):
        raise HTTPException(status_code=422, detail="Sweep proposal ids must be unique")

    proposals = [_proposal_or_404(item) for item in normalized_proposal_ids]
    indexed: list[tuple[int, dict[str, Any]]] = []
    expected_count: int | None = None
    group_signature: tuple[Any, ...] | None = None
    for proposal in proposals:
        sweep = _proposal_parameter_sweep(proposal)
        if sweep is None or str(sweep.get("sweep_id")) != normalized_id:
            raise HTTPException(
                status_code=409,
                detail="Every proposal must belong to the requested parameter sweep.",
            )
        try:
            candidate_count = int(sweep["candidate_count"])
            index = int(sweep["index"])
        except (KeyError, TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=409,
                detail="The parameter sweep metadata is incomplete.",
            ) from exc
        if expected_count is None:
            expected_count = candidate_count
        elif candidate_count != expected_count:
            raise HTTPException(
                status_code=409,
                detail="The parameter sweep proposal count is inconsistent.",
            )
        signature = (
            sweep.get("mode"),
            sweep.get("parameter"),
            sweep.get("baseline_job_id"),
        )
        if group_signature is None:
            group_signature = signature
        elif signature != group_signature:
            raise HTTPException(
                status_code=409,
                detail="The parameter sweep proposals do not share one baseline.",
            )
        indexed.append((index, proposal))

    if expected_count != len(proposals):
        raise HTTPException(
            status_code=409,
            detail="The complete parameter sweep must be confirmed as one batch.",
        )
    if len({index for index, _ in indexed}) != len(indexed):
        raise HTTPException(
            status_code=409,
            detail="The parameter sweep contains duplicate row indexes.",
        )
    return [proposal for _, proposal in sorted(indexed, key=lambda item: item[0])]


def _parameter_sweep_started_action(
    proposals: list[dict[str, Any]], jobs: list[dict[str, Any]]
) -> dict[str, Any]:
    sweep = deepcopy(_proposal_parameter_sweep(proposals[0]) or {})
    sweep.pop("index", None)
    sweep.pop("value", None)
    public_jobs = [_public_job(job) for job in jobs]
    sweep["job_ids"] = [job["job_id"] for job in public_jobs]
    return {
        "type": "job_batch_started",
        "sweep": sweep,
        "jobs": public_jobs,
    }


@app.post("/api/agent/sweeps/{sweep_id}/confirm")
def confirm_agent_sweep(
    sweep_id: str, req: ProposalSweepConfirmRequest
) -> JSONResponse:
    with state._ORCHESTRATION_LOCK:
        proposals = _parameter_sweep_confirmation_proposals(
            sweep_id, req.proposal_ids
        )
        try:
            jobs = _confirm_durable_proposals(proposals, automatic=False)
        except InvalidStateTransition as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        action = _parameter_sweep_started_action(proposals, jobs)
    return JSONResponse({"action": action})


@app.post("/api/agent/proposals/{proposal_id}/confirm")
def confirm_agent_proposal(proposal_id: str) -> JSONResponse:
    with state._ORCHESTRATION_LOCK:
        proposal = _proposal_or_404(proposal_id)
        if _proposal_parameter_sweep(proposal) is not None:
            raise HTTPException(
                status_code=409,
                detail="Confirm the complete parameter sweep as one batch.",
            )
        if proposal.get("confirmed_job_id"):
            existing = _get_job_record(str(proposal["confirmed_job_id"]))
            if existing is None:
                raise HTTPException(status_code=409, detail="Confirmed job is missing")
            return JSONResponse({"job": _public_job(existing)})
        try:
            job = _confirm_durable_proposal(proposal, automatic=False)
        except InvalidStateTransition as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    return JSONResponse({"job": _public_job(job)})


@app.post("/api/agent/proposals/{proposal_id}/edit")
def edit_agent_proposal(
    proposal_id: str, req: ProposalEditRequest
) -> JSONResponse:
    with state._ORCHESTRATION_LOCK:
        prior = _proposal_or_404(proposal_id)
        if prior["state"] != "pending":
            raise HTTPException(status_code=409, detail="Only a pending proposal can be edited")
        overrides = _explicit_overrides(req.overrides)
        target_mode = overrides.pop("mode", prior["mode"])
        if target_mode == "validation" and "years" in overrides:
            raise HTTPException(
                status_code=422,
                detail="MIDC year selection can only be changed for annual runs.",
            )
        validation_only = {"from_time", "to_time"}
        if target_mode == "annual" and validation_only.intersection(overrides):
            raise HTTPException(
                status_code=422,
                detail="Start and end times can only be changed for calibration runs.",
            )
        if "interval_value" in overrides and "interval_unit" not in overrides:
            raise HTTPException(
                status_code=422,
                detail="An interval change must explicitly include minutes, hours, or days.",
            )
        candidate_values = dict(prior["effective_request"])
        overrides = _apply_dependent_scenario_overrides(overrides, candidate_values)
        candidate_values.update(overrides)
        _, candidate = _canonical_request(
            target_mode,
            candidate_values,
            allow_resolved_partial=(
                target_mode == "annual" and "years" not in overrides
            ),
        )
        if prior.get("baseline_id"):
            baseline = _get_job_record(str(prior["baseline_id"]))
            if baseline is None:
                raise HTTPException(status_code=409, detail="The proposal baseline is missing")
            changes = _scenario_changes(baseline.get("request") or {}, candidate)
            baseline_mode = str(baseline.get("mode", prior["mode"]))
            if baseline_mode != target_mode:
                changes.insert(
                    0,
                    {
                        "field": "mode",
                        "label": SCENARIO_FIELD_LABELS["mode"],
                        "from": baseline_mode,
                        "to": target_mode,
                    },
                )
            if not changes:
                raise HTTPException(status_code=422, detail="The edited proposal makes no changes")
            proposal = _create_candidate_proposal(
                mode=target_mode,
                baseline=baseline,
                candidate=candidate,
                changes=changes,
                supersedes_id=proposal_id,
            )
        else:
            proposal = state.AGENT_STORE.create_proposal(
                mode=target_mode,
                effective_request=candidate,
                changes=[],
                baseline_id=None,
                comparison_kind="same_input",
                confirmation_required=True,
                confirmation_reason="No completed baseline exists for this mode",
                confirmation_metadata={"job_kind": "baseline"},
                supersedes_id=proposal_id,
            )
        if not proposal["confirmation_required"]:
            job = _confirm_durable_proposal(proposal, automatic=True)
            return JSONResponse(
                {"action": {"type": "job_started", "job": _public_job(job)}}
            )
    return JSONResponse({"proposal": _public_proposal(proposal)})


@app.post("/api/agent/proposals/{proposal_id}/dismiss")
def dismiss_agent_proposal(proposal_id: str) -> JSONResponse:
    try:
        proposal = state.AGENT_STORE.dismiss_proposal(proposal_id)
    except RecordNotFound as exc:
        raise HTTPException(status_code=404, detail="Unknown proposal id") from exc
    except InvalidStateTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return JSONResponse({"proposal": _public_proposal(proposal)})


@app.get("/api/saved-results")
def list_saved_results() -> JSONResponse:
    saved_results = [
        _public_saved_result(item)
        for item in state.AGENT_STORE.list_saved_results()
    ]
    return JSONResponse(
        {"saved_results": saved_results, "limit": SAVED_RESULTS_LIMIT}
    )


@app.post("/api/saved-results/{job_id}")
def save_result(
    job_id: str, req: SavedResultCreateRequest | None = None
) -> JSONResponse:
    if job_store._get_durable_model_job_record(job_id) is None:
        raise HTTPException(status_code=404, detail="Unknown job id")
    try:
        saved_result = state.AGENT_STORE.save_result(
            job_id, name=req.name if req is not None else None
        )
    except RecordNotFound as exc:
        raise HTTPException(status_code=404, detail="Unknown job id") from exc
    except (InvalidStateTransition, StoreConflict) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return JSONResponse({"saved_result": _public_saved_result(saved_result)})


@app.put("/api/saved-results/{job_id}")
def rename_saved_result(
    job_id: str, req: SavedResultRenameRequest
) -> JSONResponse:
    try:
        saved_result = state.AGENT_STORE.rename_saved_result(job_id, req.name)
    except RecordNotFound as exc:
        raise HTTPException(status_code=404, detail="Unknown saved result") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return JSONResponse({"saved_result": _public_saved_result(saved_result)})


@app.delete("/api/saved-results/{job_id}")
def remove_saved_result(job_id: str) -> JSONResponse:
    try:
        state.AGENT_STORE.remove_saved_result(job_id)
    except RecordNotFound as exc:
        raise HTTPException(status_code=404, detail="Unknown saved result") from exc
    return JSONResponse({"job_id": job_id, "removed": True})


@app.post("/api/jobs/{job_id}/cancel")
def cancel_model_job(job_id: str) -> JSONResponse:
    try:
        job = state.AGENT_STORE.cancel_job(job_id)
    except RecordNotFound as exc:
        raise HTTPException(status_code=404, detail="Unknown job id") from exc
    _cache_job_record(job)
    state._WORKER_WAKE.set()
    return JSONResponse({"job": _public_job(job)})


@app.post("/api/jobs/{job_id}/retry")
def retry_model_job(job_id: str) -> JSONResponse:
    try:
        job = state.AGENT_STORE.retry_job(
            job_id, max_active_jobs=config.MAX_ACTIVE_MODEL_JOBS
        )
    except RecordNotFound as exc:
        raise HTTPException(status_code=404, detail="Unknown job id") from exc
    except InvalidStateTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except QueueCapacityExceeded as exc:
        raise HTTPException(
            status_code=429,
            detail="The model queue is full. Wait for an active run to finish and retry.",
        ) from exc
    _cache_job_record(job)
    state._WORKER_WAKE.set()
    return JSONResponse({"job": _public_job(job)})


@app.post("/api/jobs/{job_id}/delete")
def delete_model_job(job_id: str) -> JSONResponse:
    with state._ORCHESTRATION_LOCK:
        try:
            job = state.AGENT_STORE.delete_job(job_id)
        except RecordNotFound as exc:
            raise HTTPException(status_code=404, detail="Unknown job id") from exc
        except InvalidStateTransition as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        state.JOBS.pop(job_id, None)
        artifacts_deleted = _delete_job_artifacts(job)
    return JSONResponse(
        {
            "job_id": job_id,
            "deleted": True,
            "artifacts_deleted": artifacts_deleted,
        }
    )


@app.post("/api/jobs/{job_id}/promote")
def promote_model_job(job_id: str) -> JSONResponse:
    candidate = job_store._get_durable_model_job_record(job_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="Unknown job id")
    if candidate.get("mode") == "validation":
        verified_path, verified_hash = _verified_baseline_source(candidate)
        calibration_requested = bool(
            (candidate.get("request") or {}).get("calibrate_model", True)
        )
        reviewed_quality = (
            _reviewed_baseline_data_quality(candidate)
            if calibration_requested
            else None
        )
        if not verified_path or not verified_hash or (
            calibration_requested and reviewed_quality is None
        ):
            raise HTTPException(
                status_code=409,
                detail=(
                    "This validation job is not bound to an available, hash-verified "
                    + (
                        "data-quality review and cannot be promoted. Run the requested "
                        "range through the visible Calibration review first."
                        if calibration_requested
                        else "source and cannot be promoted. Re-run the physics model first."
                    )
                ),
            )
    try:
        with state._ORCHESTRATION_LOCK:
            promoted = state.AGENT_STORE.promote_job(job_id)
    except InvalidStateTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    job = promoted["job"]
    public_job = _public_job(job)
    return JSONResponse(
        {
            "job_id": public_job["job_id"],
            "mode": public_job["mode"],
            "result": public_job.get("result"),
            "request": public_job.get("request"),
            "comparison": public_job.get("comparison"),
            "provenance": public_job.get("provenance"),
            "artifacts": public_job.get("artifacts") or {},
        }
    )


@app.post("/api/chat")
def chat(req: ChatRequest) -> JSONResponse:
    return JSONResponse(agent_chat._openai_agent_response(req))
