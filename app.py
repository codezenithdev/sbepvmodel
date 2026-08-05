"""app.py — local web backend for the SB Energy dashboard.

Serves sb_energy_dashboard.html, accepts a from/to window + interval (UTC),
runs the historian -> model pipeline as a background job with progress, and
serves the generated PNG charts + stats back to the UI.

Run:
    uvicorn app:app --reload --port 8000
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
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

import bazefield_historian as historian
import midc_stac_hourly as midc
import sbe_pv_model as model
from calibration_workflow import (
    CALIBRATION_PROFILE_SCHEMA_VERSION,
    apply_quality_decisions,
    inspect_historian_csv,
    public_quality_report,
    quality_issue_rows,
    season_name,
    validate_seasonal_calibration_profile,
)
from agent_store import (
    SCHEMA_VERSION as AGENT_STORE_SCHEMA_VERSION,
    AgentStore,
    AgentStoreError,
    InvalidStateTransition,
    LeaseOwnershipLost,
    QueueCapacityExceeded,
    RecordNotFound,
    StoreConflict,
)
from scenario_reporting import (
    SourceFingerprintMismatch,
    generate_comparison_artifacts,
    sha256_file,
    verify_source_sha256,
)

logger = logging.getLogger(__name__)


def _bounded_env_number(
    name: str,
    default: float,
    *,
    minimum: float,
    maximum: float,
) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        logger.warning("Ignoring invalid %s value", name)
        return default
    if not math.isfinite(value) or not minimum <= value <= maximum:
        logger.warning("Ignoring out-of-range %s value", name)
        return default
    return value

HERE = Path(__file__).parent
historian.load_dotenv(str(HERE / ".env"))


def _configured_output_dir() -> Path:
    configured = os.getenv("PV_DASHBOARD_OUTPUT_DIR")
    if not configured:
        return HERE / "outputs"
    path = Path(configured).expanduser()
    if not path.is_absolute():
        path = HERE / path
    return path


OUTPUT_DIR = _configured_output_dir()
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
CALIBRATION_REVIEW_DIR = OUTPUT_DIR / ".calibration_reviews"
CALIBRATION_REVIEW_DIR.mkdir(parents=True, exist_ok=True)
PRIVATE_OUTPUT_DIRS = (
    (OUTPUT_DIR / ".agent_state").resolve(),
    CALIBRATION_REVIEW_DIR.resolve(),
)
PUBLIC_OUTPUT_SUFFIXES = frozenset({".csv", ".png", ".xlsx"})
CALIBRATION_REVIEW_TTL = timedelta(hours=24)
CALIBRATION_REVIEW_MAX_RANGE = timedelta(days=366)
CALIBRATION_REVIEW_MAX_ROWS = 200_000
VALIDATION_RUN_MAX_RANGE = CALIBRATION_REVIEW_MAX_RANGE
VALIDATION_RUN_MAX_ROWS = CALIBRATION_REVIEW_MAX_ROWS
ANNUAL_RUN_MAX_DAYS = 3 * 366
MAX_ACTIVE_MODEL_JOBS = int(
    _bounded_env_number(
        "PV_DASHBOARD_MAX_ACTIVE_JOBS", 25, minimum=1, maximum=500
    )
)
JOB_HEARTBEAT_SECONDS = _bounded_env_number(
    "PV_DASHBOARD_JOB_HEARTBEAT_SECONDS", 10, minimum=1, maximum=60
)
JOB_STALE_SECONDS = max(
    JOB_HEARTBEAT_SECONDS * 3,
    _bounded_env_number(
        "PV_DASHBOARD_JOB_STALE_SECONDS", 120, minimum=10, maximum=3_600
    ),
)
OPENAI_TIMEOUT_SECONDS = _bounded_env_number(
    "OPENAI_REQUEST_TIMEOUT_SECONDS", 45, minimum=5, maximum=300
)
OPENAI_MAX_RETRIES = int(
    _bounded_env_number("OPENAI_MAX_RETRIES", 0, minimum=0, maximum=5)
)


class PublicOutputStaticFiles(StaticFiles):
    """Serve only root-level generated artifacts from an explicit allowlist."""

    def lookup_path(self, path: str):
        full_path, stat_result = super().lookup_path(path)
        if not full_path:
            return full_path, stat_result
        try:
            resolved = Path(full_path).resolve()
        except OSError:
            return "", None
        if any(
            resolved == private_root or private_root in resolved.parents
            for private_root in PRIVATE_OUTPUT_DIRS
        ):
            return "", None
        if (
            resolved.parent != OUTPUT_DIR.resolve()
            or resolved.name.startswith(".")
            or resolved.suffix.casefold() not in PUBLIC_OUTPUT_SUFFIXES
            or (stat_result is not None and not resolved.is_file())
        ):
            return "", None
        return full_path, stat_result

# ``JOBS`` remains as a live compatibility/read-through cache for existing local
# integrations. SQLite is the authoritative registry and survives restarts.
JOBS: dict[str, dict] = {}
AGENT_STORE = AgentStore(OUTPUT_DIR / ".agent_state" / "solar_agent.sqlite3")
_WORKER_STOP = threading.Event()
_WORKER_WAKE = threading.Event()
_WORKER_LOCK = threading.Lock()
_ORCHESTRATION_LOCK = threading.RLock()
_WORKER_THREAD: threading.Thread | None = None
_APP_STARTED = False


@asynccontextmanager
async def _app_lifespan(_app: FastAPI):
    global _APP_STARTED
    _dashboard_basic_credentials()
    interrupted = AGENT_STORE.mark_stale_running_jobs_interrupted(
        before=datetime.now(timezone.utc) - timedelta(seconds=JOB_STALE_SECONDS)
    )
    if interrupted:
        logger.warning("Marked %s stale model job(s) interrupted", interrupted)
    _start_model_worker()
    _APP_STARTED = True
    try:
        yield
    finally:
        _APP_STARTED = False
        _stop_model_worker()


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
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)
app.mount(
    "/outputs",
    PublicOutputStaticFiles(directory=str(OUTPUT_DIR)),
    name="outputs",
)

SERVER_SESSION_ID = uuid.uuid4().hex

UNIT_SECONDS = {"minutes": 60, "hours": 3600, "days": 86400}
AUTH_REALM = "SB Energy Dashboard"


def _dashboard_basic_credentials() -> tuple[str, str] | None:
    username = os.getenv("DASHBOARD_BASIC_USER", "").strip()
    password = os.getenv("DASHBOARD_BASIC_PASSWORD", "")
    if bool(username) != bool(password):
        raise RuntimeError(
            "DASHBOARD_BASIC_USER and DASHBOARD_BASIC_PASSWORD must be configured together"
        )
    if not username:
        return None
    return username, password


def _auth_required_response() -> JSONResponse:
    return JSONResponse(
        {"detail": "Authentication required."},
        status_code=401,
        headers={"WWW-Authenticate": f'Basic realm="{AUTH_REALM}"'},
    )


def _basic_auth_is_valid(authorization: str | None) -> bool:
    expected = _dashboard_basic_credentials()
    if expected is None:
        return True
    if not authorization or not authorization.startswith("Basic "):
        return False
    try:
        decoded = base64.b64decode(
            authorization.removeprefix("Basic ").strip(),
            validate=True,
        ).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError):
        return False

    username, separator, password = decoded.partition(":")
    if not separator:
        return False
    return secrets.compare_digest(username, expected[0]) and secrets.compare_digest(
        password, expected[1]
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
        "/outputs/.calibration_reviews",
    )
    if any(
        normalized_path == root or normalized_path.startswith(f"{root}/")
        for root in private_roots
    ):
        return JSONResponse({"detail": "Not found."}, status_code=404)
    return await call_next(request)


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RunRequest(StrictRequest):
    from_date: str  # YYYY-MM-DD
    from_time: str = "00:00"  # HH:MM
    to_date: str
    to_time: str = "00:00"
    interval_value: int = 1
    interval_unit: Literal["minutes", "hours", "days"] = "hours"
    backtrack: bool = model.BACKTRACK
    solaredge_inverter_efficiency: float = 1.0
    solaredge_bos_efficiency: float = 1.0
    solectria_inverter_efficiency: float = 1.0
    solectria_bos_efficiency: float = 1.0
    iam_model: Literal["physical", "martin_ruiz"] = "physical"
    include_iam: bool | None = Field(
        default=model.INCLUDE_IAM,
        exclude=True,
        deprecated="Use iam_model and iam_a_r instead.",
    )
    iam_a_r: float | None = model.A_R
    curtailment_enabled: bool = False
    curtailment_limit_kw: float | None = None
    calibrate_model: bool = True


class CalibrationDecisionRequest(StrictRequest):
    decisions: dict[str, Literal["retain", "exclude"]] = Field(
        default_factory=dict
    )


class AnnualRunRequest(StrictRequest):
    from_date: str  # YYYY-MM-DD, inclusive fixed MST date
    to_date: str
    backtrack: bool = model.BACKTRACK
    solaredge_inverter_efficiency: float = 1.0
    solaredge_bos_efficiency: float = 1.0
    solectria_inverter_efficiency: float = 1.0
    solectria_bos_efficiency: float = 1.0
    iam_model: Literal["physical", "martin_ruiz"] = "physical"
    include_iam: bool | None = Field(
        default=model.INCLUDE_IAM,
        exclude=True,
        deprecated="Use iam_model and iam_a_r instead.",
    )
    iam_a_r: float | None = model.A_R
    curtailment_enabled: bool = False
    curtailment_limit_kw: float | None = None


class ChatMessage(StrictRequest):
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(StrictRequest):
    message: str
    job_id: str | None = None
    history: list[ChatMessage] = Field(default_factory=list)
    active_mode: Literal["validation", "annual"] = "validation"
    current_config: dict[str, Any] | None = None
    allow_scenario_actions: bool = True


class ProposalEditRequest(StrictRequest):
    overrides: dict[str, Any]


SOLAR_AGENT_INSTRUCTIONS = """You are Solar Agent, a concise PV performance analyst for a local SB Energy dashboard.
Use the supplied dashboard run context as the source of truth for run-specific questions.
Explain model behavior in plain engineering terms: measured vs predicted energy, percent deltas, DHI source, IAM, backtracking, clipping/curtailment, and efficiency assumptions.
Validation-view runs may be calibrated or physics-model-only. Treat request.calibrate_model and result.stats.calibration_enabled as authoritative, and never describe a run as calibrated when calibration_enabled is false.
Calibration runs first review Bazefield quality and record the user's retain/exclude decisions. Treat data_quality, calibration_factors, uncalibrated, and factor_driver_diagnostics in the run result as authoritative. Explain that each per-system meteorological-season factor uses every reviewed row: without curtailment it is measured energy divided by uncalibrated modeled energy, while a curtailment-aware solve preserves that same whole-season energy match when clipping is active; factors may be above 1. This in-sample energy balance is a calibration constraint, not independent model accuracy. Driver diagnostics are associations, not causal proof, and soiling cannot be isolated without dedicated soiling, rainfall, cleaning, or maintenance data.
Solar Agent may start a calibration scenario only when it reuses the exact hash-verified source and frozen calibration profile of a reviewed baseline. A new date, time, interval, missing reviewed baseline, changed source, or other cross-run calibration request requires the visible Calibration form: the user must retrieve Bazefield data, review every flagged irregularity, choose Retain or Exclude where offered, and then apply the reviewed run. If the tool returns data_review_required, say clearly that no proposal or model job was created and direct the user to that visible review flow.
Treat visible_iam_selection as the authoritative IAM state for the visible dashboard form. Physical IAM is an active IAM selection, even though iam_a_r is null because that coefficient applies only to Martin-Ruiz. Never describe Physical IAM as disabled, off, or not selected.
If no live run context is available, say the dashboard needs a completed analysis for grounded run-specific answers, while still answering general model questions from the provided model notes.
When the user explicitly asks to run, test, simulate, compare, or perform a what-if with one dashboard configuration, call propose_model_scenario exactly once. Put only explicitly requested changes in the tool arguments and use null for every unchanged field. Do not call the tool for conceptual questions.
When the user explicitly asks to compare multiple values or gives a range and increment for one supported numeric model parameter, call run_model_parameter_sweep exactly once and do not also call propose_model_scenario. Supported sweep parameters are Martin-Ruiz a_r, SolarEdge or Solectria inverter efficiency, SolarEdge or Solectria BOS efficiency, and the curtailment limit. The sweep is inclusive, keeps every unrelated baseline setting and the source data fixed, applies required dependent selectors such as Martin-Ruiz IAM or enabled curtailment, and returns one application-rendered deterministic comparison across the values. Efficiency values use decimal ratios from 0 to 1, so convert an explicit percentage such as 97% to 0.97. Do not sweep dates, times, mode, or interval because those change the input context.
Bazefield supplies measured data for calibration. The internal API value for this view is validation; select that mode if the user explicitly asks to use Bazefield, even when the annual view is active. Always call this view calibration in user-facing answers. Calibration end timestamps are exclusive: interpret a whole-day range such as June 1-7 as June 1 00:00 through June 8 00:00 so all of June 7 is included.
IAM is a method selection, not a generic scalar. If the user gives a numeric IAM value without explicitly naming Martin-Ruiz or a_r, ask which value they mean and do not call the tool.
Never calculate scenario deltas yourself. The application returns deterministic comparison metrics after the model run; explain those values without changing them. A multi-field scenario is a combined scenario and must not be attributed to one field. A cross-run comparison uses different input data and must not be described causally.
After explaining a completed deterministic comparison, suggest one or two useful follow-up experiments, but never request or launch them unless the user explicitly asks in a later turn.
The application, not you, decides whether a run requires confirmation. Never claim a run started unless the tool output says it did.
When the tool output status is started or batch_started, explicitly say the run or sweep was queued from verified source data (and from reviewed data when calibration is enabled) and do not ask for confirmation. Ask for confirmation only when the tool output status is confirmation_required or baseline_required. A data_review_required status is not a confirmation request and must never be described as a queued run.
When web_search is available and you use external information, include source links in the answer.
Format answers for a narrow chat sidebar. Use concise Markdown with bold section labels and short bullets. Do not use nested bullets. Do not use tables unless the user explicitly asks for a table.
For ordinary questions, lead with the answer and stay under 90 words unless the user asks for detail. Do not restate the request or repeat the same metric in prose and bullets.
For performance-summary questions, use this order: **Performance Summary**, **SolarEdge**, **Solectria**, **Run Context**. Under each system, use the same four bullets: Measured, Predicted, Difference, Model delta.
Use signs consistently: Difference should be actual minus predicted, with + when measured is above predicted. Model delta should explain whether the model underpredicted or overpredicted.
Do not invent measurements, hidden files, credentials, or run outputs not present in the supplied context."""


SCENARIO_OVERRIDE_FIELDS = (
    "mode",
    "from_date",
    "from_time",
    "to_date",
    "to_time",
    "interval_value",
    "interval_unit",
    "backtrack",
    "solaredge_inverter_efficiency",
    "solaredge_bos_efficiency",
    "solectria_inverter_efficiency",
    "solectria_bos_efficiency",
    "iam_model",
    "iam_a_r",
    "curtailment_enabled",
    "curtailment_limit_kw",
)

SCENARIO_FIELD_LABELS = {
    "mode": "Analysis mode",
    "from_date": "Start date",
    "from_time": "Start time",
    "to_date": "End date",
    "to_time": "End time",
    "interval_value": "Interval value",
    "interval_unit": "Interval unit",
    "backtrack": "Backtracking",
    "solaredge_inverter_efficiency": "SolarEdge inverter efficiency",
    "solaredge_bos_efficiency": "SolarEdge BOS efficiency",
    "solectria_inverter_efficiency": "Solectria inverter efficiency",
    "solectria_bos_efficiency": "Solectria BOS efficiency",
    "iam_model": "IAM model",
    "iam_a_r": "Martin-Ruiz a_r",
    "curtailment_enabled": "Clipping / curtailment",
    "curtailment_limit_kw": "Clipping / curtailment limit",
}


def _nullable_schema(base_type: str, **extra: Any) -> dict[str, Any]:
    schema: dict[str, Any] = {"type": [base_type, "null"]}
    schema.update(extra)
    return schema


SCENARIO_TOOL = {
    "type": "function",
    "name": "propose_model_scenario",
    "description": (
        "Propose one solar model scenario containing only settings the user explicitly "
        "asked to change. Use null for all unchanged settings. The application validates, "
        "approves, executes, and compares the run. A calibration scenario can execute only "
        "from the exact reviewed baseline source. A new calibration window is handed back "
        "to the visible data-quality review flow and is never fetched automatically. Do not "
        "use this tool for multiple values or ranges; use run_model_parameter_sweep."
    ),
    "strict": True,
    "parameters": {
        "type": "object",
        "properties": {
            "mode": _nullable_schema(
                "string", enum=["validation", "annual", None]
            ),
            "from_date": _nullable_schema("string"),
            "from_time": _nullable_schema("string"),
            "to_date": _nullable_schema("string"),
            "to_time": _nullable_schema("string"),
            "interval_value": _nullable_schema("integer", minimum=1),
            "interval_unit": _nullable_schema(
                "string", enum=["minutes", "hours", "days", None]
            ),
            "backtrack": _nullable_schema("boolean"),
            "solaredge_inverter_efficiency": _nullable_schema(
                "number", minimum=0, maximum=1
            ),
            "solaredge_bos_efficiency": _nullable_schema(
                "number", minimum=0, maximum=1
            ),
            "solectria_inverter_efficiency": _nullable_schema(
                "number", minimum=0, maximum=1
            ),
            "solectria_bos_efficiency": _nullable_schema(
                "number", minimum=0, maximum=1
            ),
            "iam_model": _nullable_schema(
                "string", enum=["physical", "martin_ruiz", None]
            ),
            "iam_a_r": _nullable_schema("number", exclusiveMinimum=0),
            "curtailment_enabled": _nullable_schema("boolean"),
            "curtailment_limit_kw": _nullable_schema(
                "number", exclusiveMinimum=0
            ),
        },
        "required": list(SCENARIO_OVERRIDE_FIELDS),
        "additionalProperties": False,
    },
}

SWEEPABLE_PARAMETER_CONFIG: dict[str, dict[str, Any]] = {
    "solaredge_inverter_efficiency": {
        "label": "SolarEdge inverter efficiency",
        "minimum": Decimal("0"),
        "maximum": Decimal("1"),
    },
    "solaredge_bos_efficiency": {
        "label": "SolarEdge BOS efficiency",
        "minimum": Decimal("0"),
        "maximum": Decimal("1"),
    },
    "solectria_inverter_efficiency": {
        "label": "Solectria inverter efficiency",
        "minimum": Decimal("0"),
        "maximum": Decimal("1"),
    },
    "solectria_bos_efficiency": {
        "label": "Solectria BOS efficiency",
        "minimum": Decimal("0"),
        "maximum": Decimal("1"),
    },
    "iam_a_r": {
        "label": "Martin-Ruiz a_r",
        "exclusive_minimum": Decimal("0"),
    },
    "curtailment_limit_kw": {
        "label": "Curtailment limit",
        "unit": "kW",
        "exclusive_minimum": Decimal("0"),
    },
}
PARAMETER_SWEEP_FIELDS = ("mode", "parameter", "start", "stop", "increment")
MAX_PARAMETER_SWEEP_VALUES = 12


class ProposalSweepConfirmRequest(StrictRequest):
    proposal_ids: list[str] = Field(
        min_length=1, max_length=MAX_PARAMETER_SWEEP_VALUES
    )


PARAMETER_SWEEP_TOOL = {
    "type": "function",
    "name": "run_model_parameter_sweep",
    "description": (
        "Run a controlled numeric model-parameter sweep against the selected baseline. "
        "Supported parameters are IAM a_r, SolarEdge/Solectria inverter efficiency, "
        "SolarEdge/Solectria BOS efficiency, and curtailment limit kW. Efficiency "
        "values are decimal ratios from 0 to 1. The inclusive start, stop, and "
        f"increment must produce between 2 and {MAX_PARAMETER_SWEEP_VALUES} values. "
        "Every unrelated model input and the verified source data stay fixed; "
        "required dependent selectors are applied consistently to every sweep row."
    ),
    "strict": True,
    "parameters": {
        "type": "object",
        "properties": {
            "mode": _nullable_schema(
                "string", enum=["validation", "annual", None]
            ),
            "parameter": {
                "type": "string",
                "enum": list(SWEEPABLE_PARAMETER_CONFIG),
            },
            "start": {
                "type": "number",
            },
            "stop": {
                "type": "number",
            },
            "increment": {
                "type": "number",
                "exclusiveMinimum": 0,
            },
        },
        "required": list(PARAMETER_SWEEP_FIELDS),
        "additionalProperties": False,
    },
}


SOLAR_MODEL_KNOWLEDGE = {
    "site": "SBE Innovation Center PV, STAC1 East array",
    "coordinates": {"lat": model.LAT, "lon": model.LON},
    "systems": {
        "SolarEdge": (
            "Modeled as module-level optimization by summing pvlib module p_mp "
            "over the as-built bay tilts."
        ),
        "Solectria": (
            "Modeled as string-level mismatch using pvlib irradiance/temperature "
            "inputs and pvmismatch string calculations over the as-built string layout."
        ),
    },
    "weather_inputs": (
        "Historian CSV provides measured inverter power plus DNI, GHI, DHI, "
        "ambient temperature, and wind speed. Measured DHI is preferred when present; "
        "otherwise DHI is derived from GHI - DNI * cos(zenith)."
    ),
    "tracking": {
        "axis_azimuth": model.AXIS_AZIMUTH,
        "max_angle": model.MAX_ANGLE,
        "gcr": model.GCR,
        "default_backtrack": model.BACKTRACK,
    },
    "module": model.MODULE_NAME,
    "layout": {
        "modules_per_bay": model.MODULES_PER_BAY,
        "solaredge_strings": model.SOLAREDGE_STRINGS,
        "solaredge_bays_per_string": model.SOLAREDGE_BAYS_PER_STRING,
        "solectria_strings": model.SOLECTRIA_STRINGS,
        "solectria_bays_per_string": model.SOLECTRIA_BAYS_PER_STRING,
    },
    "outputs": (
        "Calibration runs return an audited Bazefield data-quality review, user "
        "retain/exclude decisions, per-system meteorological-season factors, before/after "
        "model residuals, diagnostic physical-driver associations, AC power and "
        "cumulative energy charts, and an Excel workbook. Annual MIDC runs return "
        "predicted-only AC power, cumulative energy, and monthly energy charts, the "
        "exact hourly source CSV, an Excel workbook with a monthly_energy sheet, and "
        "visible data-quality warnings describing any weather fallbacks."
    ),
}


def _finite_float(value: float, label: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail=f"{label} must be a finite number.")
    if not math.isfinite(out):
        raise HTTPException(status_code=422, detail=f"{label} must be a finite number.")
    return out


def _efficiency(value: float, label: str) -> float:
    out = _finite_float(value, label)
    if out < 0 or out > 1:
        raise HTTPException(status_code=422, detail=f"{label} must be between 0 and 1.")
    return out


def _request_fields_set(req: BaseModel) -> set[str]:
    """Return explicitly supplied request fields on Pydantic v1 or v2."""
    fields_set = getattr(req, "model_fields_set", None)
    if fields_set is None:
        fields_set = getattr(req, "__fields_set__", set())
    return set(fields_set)


def _validate_run_request(req: RunRequest | AnnualRunRequest) -> None:
    req.solaredge_inverter_efficiency = _efficiency(
        req.solaredge_inverter_efficiency, "SolarEdge inverter efficiency"
    )
    req.solaredge_bos_efficiency = _efficiency(
        req.solaredge_bos_efficiency, "SolarEdge BOS efficiency"
    )
    req.solectria_inverter_efficiency = _efficiency(
        req.solectria_inverter_efficiency, "Solectria inverter efficiency"
    )
    req.solectria_bos_efficiency = _efficiency(
        req.solectria_bos_efficiency, "Solectria BOS efficiency"
    )

    fields_set = _request_fields_set(req)
    if "iam_model" not in fields_set and "include_iam" in fields_set:
        # Compatibility for payloads created before the explicit model selector:
        # include_iam chose a default or custom Martin-Ruiz coefficient.
        req.iam_model = "martin_ruiz"
        if not req.__dict__.get("include_iam", model.INCLUDE_IAM):
            req.iam_a_r = model.A_R

    if req.iam_model == "martin_ruiz":
        req.iam_a_r = _finite_float(req.iam_a_r, "Martin-Ruiz a_r")
        if req.iam_a_r <= 0:
            raise HTTPException(
                status_code=422, detail="Martin-Ruiz a_r must be positive."
            )

    if isinstance(req, RunRequest):
        if int(req.interval_value) < 1:
            raise HTTPException(
                status_code=422, detail="Interval value must be at least 1."
            )
        try:
            start = datetime.fromisoformat(_iso(req.from_date, req.from_time))
            end = datetime.fromisoformat(_iso(req.to_date, req.to_time))
        except (TypeError, ValueError) as exc:
            detail = (
                str(exc)
                if str(exc).startswith("The selected local time")
                else "Calibration dates and times must use YYYY-MM-DD and HH:MM."
            )
            raise HTTPException(
                status_code=422,
                detail=detail,
            ) from exc
        if start >= end:
            raise HTTPException(
                status_code=422,
                detail="Calibration start date/time must be before end date/time.",
            )
        interval_seconds = int(req.interval_value) * UNIT_SECONDS[req.interval_unit]
        _validate_requested_window(
            start=start,
            end=end,
            interval_seconds=interval_seconds,
            max_range=VALIDATION_RUN_MAX_RANGE,
            max_rows=VALIDATION_RUN_MAX_ROWS,
            label="Calibration runs",
        )


def _validate_curtailment(req: RunRequest | AnnualRunRequest) -> None:
    if not req.curtailment_enabled:
        if req.curtailment_limit_kw is not None:
            inactive_limit = _finite_float(
                req.curtailment_limit_kw, "Curtailment limit"
            )
            if inactive_limit <= 0:
                raise HTTPException(
                    status_code=422,
                    detail="Curtailment limit must be a positive kW value.",
                )
        req.curtailment_limit_kw = None
        return
    limit_kw = req.curtailment_limit_kw
    if limit_kw is None:
        req.curtailment_limit_kw = model.DEFAULT_CURTAILMENT_LIMIT_KW
        return
    limit_kw = _finite_float(limit_kw, "Curtailment limit")
    if limit_kw <= 0:
        raise HTTPException(
            status_code=422,
            detail="Curtailment limit must be a positive kW value.",
        )
    req.curtailment_limit_kw = limit_kw


def _annual_dates(req: AnnualRunRequest) -> tuple[date, date]:
    try:
        start_date = date.fromisoformat(req.from_date)
        end_date = date.fromisoformat(req.to_date)
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=422, detail="Annual dates must use YYYY-MM-DD."
        ) from exc
    if start_date > end_date:
        raise HTTPException(
            status_code=422, detail="Annual start date must be on or before end date."
        )
    inclusive_days = (end_date - start_date).days + 1
    if inclusive_days > ANNUAL_RUN_MAX_DAYS:
        raise HTTPException(
            status_code=422,
            detail=f"Annual runs are limited to {ANNUAL_RUN_MAX_DAYS:,} days.",
        )
    return start_date, end_date


LOCAL_TZ = ZoneInfo("America/Denver")  # matches model.TIMEZONE
UTC_TZ = ZoneInfo("UTC")


def _iso(date_str: str, time_str: str) -> str:
    """Interpret the input date/time as local Mountain time and return naive UTC ISO.

    The dashboard collects times in local Mountain (America/Denver, DST-aware)
    time; the Bazefield historian expects UTC. Convert here so the rest of the
    pipeline continues to work in UTC.
    """
    t = (time_str or "00:00").strip()
    if len(t) == 5:  # HH:MM -> HH:MM:SS
        t += ":00"
    naive = datetime.strptime(f"{date_str}T{t}", "%Y-%m-%dT%H:%M:%S")
    candidates: dict[datetime, datetime] = {}
    for fold in (0, 1):
        aware = naive.replace(tzinfo=LOCAL_TZ, fold=fold)
        utc_candidate = aware.astimezone(UTC_TZ)
        if (
            utc_candidate.astimezone(LOCAL_TZ).replace(tzinfo=None)
            == naive
        ):
            candidates[utc_candidate] = aware
    if not candidates:
        raise ValueError(
            "The selected local time does not exist because of the daylight-saving "
            "transition. Choose a different boundary time."
        )
    if len(candidates) > 1:
        raise ValueError(
            "The selected local time occurs twice because of the daylight-saving "
            "transition. Choose a boundary outside the repeated hour."
        )
    utc = next(iter(candidates))
    return utc.strftime("%Y-%m-%dT%H:%M:%S")


def _validation_window_metadata(from_iso: str, to_iso: str) -> dict[str, Any]:
    """Return display-safe validation boundaries while preserving legacy fields."""

    def boundary(value: str) -> tuple[str, str]:
        utc = datetime.fromisoformat(value).replace(tzinfo=UTC_TZ)
        explicit_utc = utc.isoformat(timespec="seconds").replace("+00:00", "Z")
        local = utc.astimezone(LOCAL_TZ).isoformat(timespec="seconds")
        return explicit_utc, local

    from_utc, from_local = boundary(from_iso)
    to_utc, to_local = boundary(to_iso)
    return {
        "from": from_iso,
        "to": to_iso,
        "from_utc": from_utc,
        "to_utc": to_utc,
        "from_local": from_local,
        "to_local": to_local,
        "timezone": str(LOCAL_TZ),
        "end_exclusive": True,
    }


def _output_url(path: Path) -> str:
    return f"/outputs/{path.name}"


def _workbook_download_name(
    req: RunRequest | AnnualRunRequest,
    *,
    calibrated: bool = False,
) -> str:
    """Return a readable, filesystem-safe name for a model workbook download."""

    def safe_part(value: Any) -> str:
        normalized = "".join(
            character if character.isalnum() or character in "-_" else "-"
            for character in str(value).strip()
        )
        return normalized.strip("-_") or "unknown"

    if isinstance(req, AnnualRunRequest):
        run_label = "Annual_Simulation"
        start = safe_part(req.from_date)
        end = safe_part(req.to_date)
    else:
        run_label = "Calibrated_Model" if calibrated else "Physics_Model"
        start = safe_part(f"{req.from_date}_{req.from_time}")
        end = safe_part(f"{req.to_date}_{req.to_time}")
    return f"SB_Energy_{run_label}_{start}_to_{end}.xlsx"


def _public_source_url(path: Path) -> str | None:
    """Return a URL only for source snapshots directly served from OUTPUT_DIR."""

    try:
        relative = path.resolve().relative_to(OUTPUT_DIR.resolve())
    except (OSError, ValueError):
        return None
    if relative.parent != Path("."):
        return None
    return _output_url(path)


def _job_attempt_prefix(job_id: str, lease_token: str | None) -> str:
    """Return a collision-free output prefix for one claimed execution attempt."""

    return f"{job_id}_{lease_token}" if lease_token else job_id


def _job_output_file(raw: Any) -> Path | None:
    """Resolve one recorded job artifact only when it is a direct output file."""

    if not isinstance(raw, str) or not raw:
        return None
    value = raw.split("?", 1)[0].split("#", 1)[0]
    if value.startswith("/outputs/"):
        candidate = OUTPUT_DIR / value.removeprefix("/outputs/")
    else:
        candidate = Path(value)
        if not candidate.is_absolute():
            candidate = OUTPUT_DIR / candidate
    try:
        resolved = candidate.resolve()
        if resolved.parent != OUTPUT_DIR.resolve() or not resolved.is_file():
            return None
    except (OSError, RuntimeError, ValueError):
        return None
    return resolved


def _delete_job_artifacts(job: dict[str, Any]) -> int:
    """Remove files generated for one job without touching shared sources."""

    job_id = str(job.get("id") or "").strip()
    if not job_id or any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for character in job_id):
        return 0
    output_root = OUTPUT_DIR.resolve()
    candidates: set[Path] = set()
    protected_shared_sources: set[Path] = set()

    # Same-input scenarios deliberately reuse their baseline's immutable source
    # snapshot. That path can appear both as ``source_path`` and inside the
    # public result payload, so protect it before recursively collecting files.
    baseline_id = job.get("baseline_id")
    if baseline_id:
        baseline = _get_job_record(str(baseline_id))
        baseline_source = _job_output_file((baseline or {}).get("source_path"))
        job_source = _job_output_file(job.get("source_path"))
        if baseline_source is not None and baseline_source == job_source:
            protected_shared_sources.add(baseline_source)

    def collect(value: Any) -> None:
        if isinstance(value, dict):
            for item in value.values():
                collect(item)
        elif isinstance(value, (list, tuple, set)):
            for item in value:
                collect(item)
        else:
            path = _job_output_file(value)
            if path is not None:
                candidates.add(path)

    collect(job.get("result"))
    collect(job.get("artifacts"))
    source_path = job.get("source_path")
    source_file = _job_output_file(source_path)
    if source_file is not None:
        candidates.add(source_file)

    try:
        generated = [output_root / job_id, *output_root.glob(f"{job_id}_*")]
        candidates.update(
            path.resolve()
            for path in generated
            if path.is_file() and path.resolve().parent == output_root
        )
    except OSError:
        logger.warning("Could not enumerate output artifacts for job %s", job_id, exc_info=True)

    candidates.difference_update(protected_shared_sources)

    removed = 0
    for candidate in candidates:
        try:
            if candidate.parent != output_root or not candidate.is_file():
                continue
            candidate.unlink()
            removed += 1
        except OSError:
            logger.warning("Could not remove deleted job artifact %s", candidate, exc_info=True)
    return removed


def _delete_job_attempt_artifacts(job_id: str, lease_token: str | None) -> int:
    """Remove files from a fenced-off attempt after it loses ownership."""

    if not lease_token:
        return 0
    attempt_prefix = _job_attempt_prefix(job_id, lease_token)
    if any(
        character
        not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
        for character in attempt_prefix
    ):
        return 0
    output_root = OUTPUT_DIR.resolve()
    protected_source: Path | None = None
    current = _get_job_record(job_id)
    if current is not None:
        protected_source = _job_output_file(current.get("source_path"))
    try:
        candidates = [
            output_root / attempt_prefix,
            *output_root.glob(f"{attempt_prefix}*"),
        ]
    except OSError:
        logger.warning(
            "Could not enumerate expired attempt artifacts for job %s",
            job_id,
            exc_info=True,
        )
        return 0

    removed = 0
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
            if (
                resolved.parent != output_root
                or not resolved.is_file()
                or resolved == protected_source
            ):
                continue
            resolved.unlink()
            removed += 1
        except OSError:
            logger.warning(
                "Could not remove expired attempt artifact %s",
                candidate,
                exc_info=True,
            )
    return removed


def _render_input_data_plots(csv_path: Path, output_base: Path) -> dict[str, str]:
    """Render early historian-input plots before the slower PV model runs."""
    import pandas as pd
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates

    df = pd.read_csv(csv_path)
    if "timestamp" not in df.columns:
        raise ValueError("Historian CSV is missing the timestamp column.")

    times = pd.to_datetime(df["timestamp"], errors="coerce")
    times = times.dt.tz_localize("UTC").dt.tz_convert("America/Denver")
    plot_df = df.loc[~times.isna()].copy()
    times = times.loc[~times.isna()]
    if plot_df.empty:
        raise ValueError("Historian CSV did not contain plottable timestamp rows.")

    numeric_cols = [
        "solaredge_measured_power",
        "solectria_measured_power",
        "dni",
        "ghi",
        "dhi",
    ]
    for col in numeric_cols:
        if col in plot_df.columns:
            plot_df[col] = pd.to_numeric(plot_df[col], errors="coerce")

    measured_path = output_base.with_name(f"{output_base.name}_measured_power.png")
    irradiance_path = output_base.with_name(f"{output_base.name}_irradiance.png")

    fig1, ax1 = plt.subplots(figsize=(14, 6))
    ax1.plot(
        times,
        plot_df["solaredge_measured_power"] / 1000.0,
        color="#dc2626",
        linewidth=2,
        label="SolarEdge measured",
    )
    ax1.plot(
        times,
        plot_df["solectria_measured_power"] / 1000.0,
        color="#2563eb",
        linewidth=2,
        label="Solectria measured",
    )
    ax1.set_title("Measured AC Power Input")
    ax1.set_xlabel("Time (Mountain)")
    ax1.set_ylabel("Measured Power (kW)")
    ax1.grid(True, alpha=0.25)
    ax1.legend(loc="best")
    ax1.xaxis.set_major_formatter(
        mdates.DateFormatter("%m-%d-%Y %H:%M", tz=LOCAL_TZ)
    )
    fig1.autofmt_xdate()
    fig1.savefig(measured_path, dpi=200, bbox_inches="tight")
    plt.close(fig1)

    fig2, ax2 = plt.subplots(figsize=(14, 6))
    for col, label, color in (
        ("dni", "DNI", "#f97316"),
        ("ghi", "GHI", "#16a34a"),
        ("dhi", "DHI", "#7c3aed"),
    ):
        if col in plot_df.columns:
            ax2.plot(times, plot_df[col], linewidth=2, color=color, label=label)
    ax2.set_title("Irradiance Input")
    ax2.set_xlabel("Time (Mountain)")
    ax2.set_ylabel("Irradiance (W/m2)")
    ax2.grid(True, alpha=0.25)
    ax2.legend(loc="best")
    ax2.xaxis.set_major_formatter(
        mdates.DateFormatter("%m-%d-%Y %H:%M", tz=LOCAL_TZ)
    )
    fig2.autofmt_xdate()
    fig2.savefig(irradiance_path, dpi=200, bbox_inches="tight")
    plt.close(fig2)

    return {
        "measured_power_png": _output_url(measured_path),
        "irradiance_png": _output_url(irradiance_path),
    }


def _render_midc_input_data_plots(
    csv_path: Path, output_base: Path
) -> dict[str, str]:
    """Render annual irradiance as soon as the MIDC source is available."""
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates

    frame, _ = model.parse_midc_csv(str(csv_path))
    irradiance_path = output_base.with_name(f"{output_base.name}_irradiance.png")

    fig, ax = plt.subplots(figsize=(14, 6))
    for column, label, color, linestyle in (
        ("dni_wm2", "DNI", "#f97316", "-"),
        ("ghi_wm2", "GHI", "#16a34a", "--"),
        ("dhi_wm2", "DHI", "#7c3aed", ":"),
    ):
        ax.plot(
            frame.index,
            frame[column],
            linewidth=1.5,
            linestyle=linestyle,
            color=color,
            label=label,
        )
    ax.set_title("Annual Irradiance Input")
    ax.set_xlabel("Time (America/Denver)")
    ax.set_ylabel("Irradiance (W/m2)")
    ax.set_ylim(bottom=0)
    ax.grid(True, alpha=0.25)
    ax.legend(loc="best", ncols=3)
    ax.xaxis.set_major_formatter(
        mdates.DateFormatter("%m-%d-%Y %H:%M", tz=LOCAL_TZ)
    )
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(irradiance_path, dpi=200, bbox_inches="tight")
    plt.close(fig)

    return {"irradiance_png": _output_url(irradiance_path)}


def _model_dump(obj: BaseModel) -> dict:
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    return obj.dict()


def _iam_metadata(req: RunRequest | AnnualRunRequest) -> dict[str, str | float | None]:
    return {
        "iam_model": req.iam_model,
        "iam_a_r": (
            float(req.iam_a_r) if req.iam_model == "martin_ruiz" else None
        ),
    }


def _run_request_context(req: RunRequest | AnnualRunRequest) -> dict:
    """Serialize the canonical IAM selection without the legacy input flag."""
    context = _model_dump(req)
    context.update(_iam_metadata(req))
    return context


def _calibration_review_path(review_id: str, suffix: str) -> Path:
    candidate = str(review_id).strip().lower()
    if len(candidate) != 32 or any(
        character not in "0123456789abcdef" for character in candidate
    ):
        raise HTTPException(status_code=404, detail="Unknown calibration review.")
    return CALIBRATION_REVIEW_DIR / f"{candidate}{suffix}"


_CALIBRATION_REVIEW_SUFFIXES = (
    ".json",
    ".json.tmp",
    ".raw.csv",
    ".reviewed.csv",
)


def _delete_calibration_review_artifacts(
    review_id: str,
    *,
    preserve_reviewed: bool = False,
) -> int:
    """Delete the private files for one validated review identifier."""

    review_root = CALIBRATION_REVIEW_DIR.resolve()
    removed = 0
    candidates = {
        _calibration_review_path(review_id, suffix)
        for suffix in _CALIBRATION_REVIEW_SUFFIXES
    }
    candidates.update(CALIBRATION_REVIEW_DIR.glob(f"{review_id}.*.json.tmp"))
    candidates.update(
        CALIBRATION_REVIEW_DIR.glob(f"{review_id}.*.reviewed.csv")
    )
    for candidate in candidates:
        if preserve_reviewed and candidate.name.endswith(".reviewed.csv"):
            continue
        try:
            resolved = candidate.resolve()
            if resolved.parent != review_root:
                continue
            if candidate.is_file():
                candidate.unlink()
                removed += 1
        except OSError:
            logger.warning(
                "Could not remove expired calibration review artifact %s",
                candidate,
                exc_info=True,
            )
    return removed


def _reviewed_source_is_job_bound(
    record: dict[str, Any],
    *,
    review_id: str | None = None,
) -> bool:
    """Return whether a review snapshot is still bound to its durable job."""

    bound_review_id = str(review_id or record.get("review_id") or "").strip()
    if not bound_review_id:
        return False
    job_id = str(
        record.get("job_id") or f"review-{bound_review_id}"
    ).strip()
    job = _get_job_record(job_id)
    if not job or not job.get("source_path"):
        return False
    quality = (job.get("provenance") or {}).get("data_quality")
    if (
        not isinstance(quality, dict)
        or quality.get("review_id") != bound_review_id
        or quality.get("reviewed_source_sha256") != job.get("source_hash")
    ):
        return False
    cleaned_source = record.get("cleaned_source_path") or job.get("source_path")
    try:
        source_path = Path(str(job["source_path"])).resolve()
        return (
            Path(str(cleaned_source)).resolve() == source_path
            and source_path.parent == CALIBRATION_REVIEW_DIR.resolve()
            and source_path.name.startswith(f"{bound_review_id}.")
            and source_path.name.endswith(".reviewed.csv")
        )
    except (OSError, RuntimeError, ValueError):
        return False


def _cleanup_expired_calibration_reviews(
    *, now: datetime | None = None
) -> int:
    """Opportunistically remove expired or stale orphaned private review files."""

    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    else:
        current = current.astimezone(timezone.utc)
    stale_before = current - CALIBRATION_REVIEW_TTL
    removed = 0
    review_root = CALIBRATION_REVIEW_DIR
    try:
        records = list(review_root.glob("*.json"))
    except OSError:
        logger.warning(
            "Could not enumerate calibration review records", exc_info=True
        )
        return 0

    for path in records:
        review_id = path.name[: -len(".json")]
        try:
            _calibration_review_path(review_id, ".json")
        except HTTPException:
            continue
        expired = False
        record: dict[str, Any] = {}
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            expires_at = datetime.fromisoformat(str(record["expires_at"]))
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            expired = expires_at.astimezone(timezone.utc) <= current
        except (KeyError, TypeError, ValueError, OSError, json.JSONDecodeError):
            try:
                modified = datetime.fromtimestamp(
                    path.stat().st_mtime, tz=timezone.utc
                )
                expired = modified <= stale_before
            except OSError:
                continue
        if expired:
            removed += _delete_calibration_review_artifacts(
                review_id,
                preserve_reviewed=_reviewed_source_is_job_bound(
                    record,
                    review_id=review_id,
                ),
            )

    # Reviewed CSVs can remain the immutable source for a queued/completed job
    # and its same-input scenarios. Orphans are removed only after confirming
    # that the deterministic review job no longer references them.
    for pattern in ("*.json.tmp", "*.raw.csv", "*.reviewed.csv"):
        try:
            orphan_candidates = list(review_root.glob(pattern))
        except OSError:
            continue
        for path in orphan_candidates:
            review_id = path.name.split(".", 1)[0]
            try:
                record_path = _calibration_review_path(review_id, ".json")
                _calibration_review_path(review_id, path.name[len(review_id) :])
                modified = datetime.fromtimestamp(
                    path.stat().st_mtime, tz=timezone.utc
                )
            except (HTTPException, OSError):
                continue
            if not record_path.is_file() and modified <= stale_before:
                if path.name.endswith(".reviewed.csv") and (
                    _reviewed_source_is_job_bound(
                        {"review_id": review_id},
                        review_id=review_id,
                    )
                ):
                    continue
                try:
                    path.unlink()
                    removed += 1
                except OSError:
                    logger.warning(
                        "Could not remove orphaned calibration review artifact %s",
                        path,
                        exc_info=True,
                    )
    return removed


def _save_calibration_review(record: dict[str, Any]) -> None:
    review_id = str(record["review_id"])
    destination = _calibration_review_path(review_id, ".json")
    temporary = _calibration_review_path(
        review_id,
        f".{uuid.uuid4().hex}.json.tmp",
    )
    try:
        temporary.write_text(
            json.dumps(record, allow_nan=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        os.replace(temporary, destination)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            logger.warning(
                "Could not remove temporary calibration review record %s",
                temporary,
                exc_info=True,
            )


def _load_calibration_review(review_id: str) -> dict[str, Any]:
    path = _calibration_review_path(review_id, ".json")
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Unknown calibration review.")
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
        expires_at = datetime.fromisoformat(str(record["expires_at"]))
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=409,
            detail="The calibration review record is invalid; start a new review.",
        ) from exc
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= datetime.now(timezone.utc):
        _delete_calibration_review_artifacts(
            review_id,
            preserve_reviewed=_reviewed_source_is_job_bound(
                record,
                review_id=review_id,
            ),
        )
        raise HTTPException(
            status_code=410,
            detail="This calibration review expired; retrieve the data again.",
        )
    try:
        source_path = Path(str(record.get("source_path", ""))).resolve()
        review_root = CALIBRATION_REVIEW_DIR.resolve()
        source_is_available = (
            review_root in source_path.parents and source_path.is_file()
        )
    except (OSError, RuntimeError, ValueError):
        source_is_available = False
    if not source_is_available:
        raise HTTPException(
            status_code=409,
            detail="The reviewed Bazefield source is unavailable; start a new review.",
        )
    try:
        verify_source_sha256(source_path, str(record["source_hash"]))
    except (
        KeyError,
        OSError,
        TypeError,
        ValueError,
        SourceFingerprintMismatch,
    ) as exc:
        raise HTTPException(
            status_code=409,
            detail="The reviewed Bazefield source changed; start a new review.",
        ) from exc
    return record


def _quality_context(
    record: dict[str, Any],
    *,
    cleaning: dict[str, Any],
    reviewed_source_hash: str,
    submitted_decisions: dict[str, str],
) -> dict[str, Any]:
    return {
        "review_id": record["review_id"],
        "source_sha256": record["source_hash"],
        "reviewed_source_sha256": reviewed_source_hash,
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
        "submitted_decisions": dict(submitted_decisions),
        "report": public_quality_report(record["report"]),
        "cleaning": cleaning,
    }


def _calibration_review_state(report: dict[str, Any]) -> str:
    status = str((report.get("summary") or {}).get("status") or "").strip()
    if status == "blocked":
        return "blocked"
    if status == "clean":
        return "ready"
    return "decision_required"


def _validate_requested_window(
    *,
    start: datetime,
    end: datetime,
    interval_seconds: int,
    max_range: timedelta,
    max_rows: int,
    label: str,
) -> None:
    span = end - start
    if span > max_range:
        raise HTTPException(
            status_code=422,
            detail=f"{label} are limited to {max_range.days} days.",
        )
    expected_rows = int(
        math.ceil(span.total_seconds() / max(int(interval_seconds), 1))
    )
    if expected_rows > max_rows:
        raise HTTPException(
            status_code=422,
            detail=(
                "The selected range and interval would produce approximately "
                f"{expected_rows:,} rows; {label.lower()} are limited to "
                f"{max_rows:,} rows."
            ),
        )


def _validate_calibration_review_size(
    *,
    from_iso: str,
    to_iso: str,
    interval_seconds: int,
) -> None:
    start = datetime.fromisoformat(from_iso).replace(tzinfo=timezone.utc)
    end = datetime.fromisoformat(to_iso).replace(tzinfo=timezone.utc)
    _validate_requested_window(
        start=start,
        end=end,
        interval_seconds=interval_seconds,
        max_range=CALIBRATION_REVIEW_MAX_RANGE,
        max_rows=CALIBRATION_REVIEW_MAX_ROWS,
        label="Calibration reviews",
    )


def _cache_job_record(record: dict[str, Any]) -> dict[str, Any]:
    """Mirror a durable job into the legacy process cache."""
    job_id = str(record["id"])
    cached = JOBS.setdefault(job_id, {})
    runtime_fields = {
        key: cached[key]
        for key in ("input_plots", "traceback")
        if key in cached
    }
    cached.update({key: value for key, value in record.items() if key != "id"})
    cached.update(runtime_fields)
    input_plots = (record.get("artifacts") or {}).get("input_plots")
    if input_plots:
        cached["input_plots"] = input_plots
    return cached


def _get_job_record(job_id: str) -> dict[str, Any] | None:
    try:
        record = AGENT_STORE.get_job(job_id)
    except AgentStoreError:
        logger.exception("Could not read durable job %s", job_id)
        record = None
    if record is not None:
        _cache_job_record(record)
        return record
    cached = JOBS.get(job_id)
    if cached is None:
        return None
    return {"id": job_id, **cached}


def _update_job(
    job_id: str,
    *,
    worker_id: str | None = None,
    lease_token: str | None = None,
    **fields: Any,
) -> dict[str, Any]:
    """Update SQLite when present and always keep the compatibility cache fresh."""
    try:
        if AGENT_STORE.get_job(job_id) is not None:
            record = AGENT_STORE.update_job(
                job_id,
                expected_worker_id=worker_id,
                expected_lease_token=lease_token,
                **fields,
            )
            _cache_job_record(record)
            return record
    except LeaseOwnershipLost:
        raise
    except AgentStoreError:
        logger.exception("Could not update durable job %s", job_id)
        raise
    cached = JOBS.setdefault(job_id, {})
    cached.update(fields)
    artifacts = fields.get("artifacts")
    if isinstance(artifacts, dict) and artifacts.get("input_plots"):
        cached["input_plots"] = artifacts["input_plots"]
    return {"id": job_id, **cached}


def _job_cancel_requested(
    job_id: str,
    *,
    worker_id: str | None = None,
    lease_token: str | None = None,
) -> bool:
    if worker_id is not None or lease_token is not None:
        return AGENT_STORE.is_cancel_requested(
            job_id,
            expected_worker_id=worker_id,
            expected_lease_token=lease_token,
        )
    record = _get_job_record(job_id)
    if record is None:
        return False
    if record.get("cancel_requested"):
        return True
    return bool(JOBS.get(job_id, {}).get("cancel_requested"))


class _JobCancelled(RuntimeError):
    pass


def _check_job_cancelled(
    job_id: str,
    *,
    worker_id: str | None = None,
    lease_token: str | None = None,
) -> None:
    if _job_cancel_requested(
        job_id, worker_id=worker_id, lease_token=lease_token
    ):
        raise _JobCancelled("Cancellation requested")


def _latest_completed_job_id(mode: str | None = None) -> str | None:
    modes = (mode,) if mode in {"validation", "annual"} else ("validation", "annual")
    for selected_mode in modes:
        promoted = AGENT_STORE.get_current_baseline(selected_mode)
        if promoted and promoted.get("job_id"):
            return str(promoted["job_id"])
    completed = AGENT_STORE.list_jobs(states=["done"], mode=mode, limit=1)
    if completed:
        return str(completed[0]["id"])
    for job_id, job in reversed(JOBS.items()):
        if job.get("state") == "done" and (
            mode is None or job.get("mode", "validation") == mode
        ):
            return job_id
    return None


_CAMEL_CONFIG_FIELDS = {
    "fromDate": "from_date",
    "fromTime": "from_time",
    "toDate": "to_date",
    "toTime": "to_time",
    "intervalValue": "interval_value",
    "intervalUnit": "interval_unit",
    "solaredgeInverterEfficiency": "solaredge_inverter_efficiency",
    "solaredgeBosEfficiency": "solaredge_bos_efficiency",
    "solectriaInverterEfficiency": "solectria_inverter_efficiency",
    "solectriaBosEfficiency": "solectria_bos_efficiency",
    "iamModel": "iam_model",
    "iamAr": "iam_a_r",
    "curtailmentEnabled": "curtailment_enabled",
    "curtailmentLimitKw": "curtailment_limit_kw",
}


def _normalise_config_keys(config: dict[str, Any] | None) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in (config or {}).items():
        canonical = _CAMEL_CONFIG_FIELDS.get(key, key)
        if (
            canonical in SCENARIO_OVERRIDE_FIELDS and canonical != "mode"
        ) or canonical == "calibrate_model":
            out[canonical] = value
    return out


def _canonical_request(
    mode: Literal["validation", "annual"], config: dict[str, Any]
) -> tuple[RunRequest | AnnualRunRequest, dict[str, Any]]:
    values = _normalise_config_keys(config)
    try:
        request_model: RunRequest | AnnualRunRequest
        if mode == "annual":
            for unsupported in ("from_time", "to_time", "interval_value", "interval_unit"):
                values.pop(unsupported, None)
            values.pop("calibrate_model", None)
            request_model = AnnualRunRequest(**values)
        else:
            request_model = RunRequest(**values)
        _validate_run_request(request_model)
        _validate_curtailment(request_model)
        if isinstance(request_model, AnnualRunRequest):
            _annual_dates(request_model)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=422, detail="Invalid model configuration.") from exc
    return request_model, _run_request_context(request_model)


def _explicit_overrides(arguments: dict[str, Any]) -> dict[str, Any]:
    unknown = set(arguments) - set(SCENARIO_OVERRIDE_FIELDS)
    if unknown:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported scenario field: {sorted(unknown)[0]}",
        )
    return {
        field: arguments.get(field)
        for field in SCENARIO_OVERRIDE_FIELDS
        if field in arguments and arguments.get(field) is not None
    }


def _parameter_sweep_values(
    arguments: dict[str, Any],
) -> tuple[
    Literal["validation", "annual"] | None,
    str,
    dict[str, Any],
    list[float],
]:
    unknown = set(arguments) - set(PARAMETER_SWEEP_FIELDS)
    if unknown:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported parameter sweep field: {sorted(unknown)[0]}",
        )
    target_mode = arguments.get("mode")
    if target_mode not in {None, "validation", "annual"}:
        raise HTTPException(status_code=422, detail="Unsupported analysis mode.")

    parameter = arguments.get("parameter")
    parameter_config = SWEEPABLE_PARAMETER_CONFIG.get(str(parameter))
    if parameter_config is None:
        raise HTTPException(
            status_code=422,
            detail=(
                "This field cannot be swept as a controlled same-input model "
                "parameter."
            ),
        )

    decimals: dict[str, Decimal] = {}
    labels = {
        "start": "Parameter sweep start",
        "stop": "Parameter sweep stop",
        "increment": "Parameter sweep increment",
    }
    for field, label in labels.items():
        value = arguments.get(field)
        if isinstance(value, bool):
            raise HTTPException(status_code=422, detail=f"{label} must be a number.")
        try:
            parsed = Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=422, detail=f"{label} must be a number."
            ) from exc
        if not parsed.is_finite():
            raise HTTPException(
                status_code=422, detail=f"{label} must be a finite number."
            )
        if field == "increment" and parsed <= 0:
            raise HTTPException(
                status_code=422, detail=f"{label} must be greater than zero."
            )
        decimals[field] = parsed

    start = decimals["start"]
    stop = decimals["stop"]
    increment = decimals["increment"]
    if stop < start:
        raise HTTPException(
            status_code=422,
            detail="Parameter sweep stop must be greater than or equal to its start.",
        )
    minimum = parameter_config.get("minimum")
    exclusive_minimum = parameter_config.get("exclusive_minimum")
    maximum = parameter_config.get("maximum")
    if minimum is not None and start < minimum:
        raise HTTPException(
            status_code=422,
            detail=f"{parameter_config['label']} must be at least {minimum}.",
        )
    if exclusive_minimum is not None and start <= exclusive_minimum:
        raise HTTPException(
            status_code=422,
            detail=(
                f"{parameter_config['label']} must be greater than "
                f"{exclusive_minimum}."
            ),
        )
    if maximum is not None and stop > maximum:
        raise HTTPException(
            status_code=422,
            detail=f"{parameter_config['label']} must not exceed {maximum}.",
        )
    step_count = (stop - start) / increment
    whole_steps = step_count.to_integral_value()
    if step_count != whole_steps:
        raise HTTPException(
            status_code=422,
            detail=(
                "Parameter sweep increment must land exactly on the inclusive stop "
                "value."
            ),
        )
    if whole_steps >= MAX_PARAMETER_SWEEP_VALUES:
        raise HTTPException(
            status_code=422,
            detail=(
                f"A parameter sweep can contain at most "
                f"{MAX_PARAMETER_SWEEP_VALUES} values."
            ),
        )
    count = int(whole_steps) + 1
    if count < 2:
        raise HTTPException(
            status_code=422,
            detail="A parameter sweep must contain at least two values.",
        )
    values = [float(start + increment * index) for index in range(count)]
    if not all(math.isfinite(value) for value in values):
        raise HTTPException(
            status_code=422,
            detail="Parameter sweep values must be finite numbers.",
        )
    return target_mode, str(parameter), parameter_config, values


def _scenario_changes(
    baseline: dict[str, Any], candidate: dict[str, Any]
) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    for field in SCENARIO_OVERRIDE_FIELDS:
        if field == "mode":
            continue
        before = baseline.get(field)
        after = candidate.get(field)
        if before == after:
            continue
        item = {
            "field": field,
            "label": SCENARIO_FIELD_LABELS[field],
            "from": before,
            "to": after,
        }
        if field == "curtailment_limit_kw":
            item["unit"] = "kW"
        changes.append(item)
    return changes


def _apply_dependent_scenario_overrides(
    overrides: dict[str, Any], baseline: dict[str, Any]
) -> dict[str, Any]:
    normalized = dict(overrides)
    if normalized.get("iam_model") == "physical" and normalized.get("iam_a_r") is not None:
        raise HTTPException(
            status_code=422,
            detail="Martin-Ruiz a_r cannot be combined with Physical IAM.",
        )
    if "iam_a_r" in normalized and "iam_model" not in normalized:
        normalized["iam_model"] = "martin_ruiz"
    selected_iam = normalized.get("iam_model", baseline.get("iam_model"))
    if selected_iam == "martin_ruiz" and normalized.get(
        "iam_a_r", baseline.get("iam_a_r")
    ) is None:
        normalized["iam_a_r"] = model.A_R
    if "curtailment_limit_kw" in normalized and "curtailment_enabled" not in normalized:
        normalized["curtailment_enabled"] = True
    return normalized


def _same_input_context(
    mode: str, baseline: dict[str, Any], candidate: dict[str, Any]
) -> bool:
    if mode == "annual":
        keys = ("from_date", "to_date")
    else:
        keys = (
            "from_date",
            "from_time",
            "to_date",
            "to_time",
            "interval_value",
            "interval_unit",
        )
    return all(baseline.get(key) == candidate.get(key) for key in keys)


def _ambiguous_numeric_iam(message: str) -> bool:
    import re

    text = (message or "").lower()
    if "iam" not in text:
        return False
    explicit = ("martin", "ruiz", "a_r", "a-r", "coefficient", "physical")
    if any(marker in text for marker in explicit):
        return False
    number = r"(?<![\w.])-?(?:\d+(?:\.\d*)?|\.\d+)"
    relation = r"(?:value|setting|at|to|of|is|=|:)"
    patterns = (
        rf"\biam\b\s*(?:{relation}\s*)?({number})",
        rf"({number})\s*(?:{relation}\s*)?\biam\b",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if not match:
            continue
        token = match.group(1)
        suffix = text[match.end(1) : match.end(1) + 12].lstrip()
        try:
            value = float(token)
        except ValueError:
            continue
        if suffix.startswith("%"):
            continue
        if value.is_integer() and 1900 <= value <= 2200:
            continue
        return True
    return False


def _visible_iam_selection(current_config: dict[str, Any] | None) -> dict[str, Any]:
    """Make the visible IAM choice unambiguous in the model's chat context."""
    config = current_config if isinstance(current_config, dict) else {}
    iam_model = config.get("iam_model")
    if iam_model == "physical":
        return {
            "selected": True,
            "model": "physical",
            "label": "Physical IAM",
            "martin_ruiz_selected": False,
            "iam_a_r": None,
            "iam_a_r_status": "not applicable to Physical IAM",
        }
    if iam_model == "martin_ruiz":
        return {
            "selected": True,
            "model": "martin_ruiz",
            "label": "Martin-Ruiz IAM",
            "martin_ruiz_selected": True,
            "iam_a_r": config.get("iam_a_r"),
            "iam_a_r_status": "selected Martin-Ruiz coefficient",
        }
    return {
        "selected": False,
        "model": None,
        "label": "IAM selection unavailable",
        "martin_ruiz_selected": False,
        "iam_a_r": None,
        "iam_a_r_status": "unavailable",
    }


def _active_model_jobs() -> list[dict[str, Any]]:
    durable = AGENT_STORE.list_jobs(states=["queued", "running"], limit=100)
    durable_ids = {str(item["id"]) for item in durable}
    for job_id, cached in JOBS.items():
        if job_id not in durable_ids and cached.get("state") in {"queued", "running"}:
            durable.append({"id": job_id, **cached})
    return durable


def _selected_baseline(mode: str) -> dict[str, Any] | None:
    promoted = AGENT_STORE.get_current_baseline(mode)
    if promoted and promoted.get("job"):
        return promoted["job"]
    # Compatibility for a completed run created before durable orchestration.
    for job_id, cached in reversed(JOBS.items()):
        if cached.get("state") == "done" and cached.get("mode", "validation") == mode:
            return {"id": job_id, **cached}
    return None


def _visible_baseline(
    req: ChatRequest,
    target_mode: str,
    *,
    allow_mode_change: bool = False,
) -> dict[str, Any] | None:
    """Resolve the completed job visible to chat before using a stored default."""

    if req.job_id:
        visible = _get_job_record(str(req.job_id))
        if (
            visible
            and visible.get("state") == "done"
            and visible.get("mode", "validation") == req.active_mode
            and (
                allow_mode_change
                or visible.get("mode", "validation") == target_mode
            )
        ):
            return visible
    return _selected_baseline(target_mode)


def _verified_baseline_source(
    baseline: dict[str, Any] | None,
) -> tuple[str | None, str | None]:
    if not baseline:
        return None, None
    source_path = baseline.get("source_path")
    source_hash = baseline.get("source_hash")
    if not source_path or not source_hash:
        return None, None
    try:
        verify_source_sha256(source_path, source_hash)
    except (OSError, TypeError, ValueError, SourceFingerprintMismatch):
        logger.warning("Baseline source fingerprint is unavailable or changed")
        return None, None
    return str(source_path), str(source_hash)


def _reviewed_baseline_data_quality(
    baseline: dict[str, Any],
) -> dict[str, Any] | None:
    """Return review provenance only when it is bound to baseline source bytes."""

    if str(baseline.get("mode") or "") != "validation":
        return None
    quality = (baseline.get("provenance") or {}).get("data_quality")
    if not isinstance(quality, dict):
        return None
    review_id = quality.get("review_id")
    reviewed_hash = quality.get("reviewed_source_sha256")
    source_hash = baseline.get("source_hash")
    if not all(
        isinstance(value, str) and value.strip()
        for value in (review_id, reviewed_hash, source_hash)
    ):
        return None
    if not secrets.compare_digest(
        str(reviewed_hash).strip(), str(source_hash).strip()
    ):
        return None
    return deepcopy(quality)


def _validation_request_seasons(request: dict[str, Any]) -> tuple[str, ...]:
    """Return Denver-local meteorological seasons in an end-exclusive request."""

    try:
        start = datetime.fromisoformat(
            f"{request['from_date']}T{request.get('from_time') or '00:00'}"
        )
        end = datetime.fromisoformat(
            f"{request['to_date']}T{request.get('to_time') or '00:00'}"
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(
            "Validation request dates are unavailable for profile coverage."
        ) from exc
    if end <= start:
        raise ValueError("Validation request end must be after its start.")
    last_included = end - timedelta(microseconds=1)
    cursor = datetime(start.year, start.month, 1)
    final_month = datetime(last_included.year, last_included.month, 1)
    seasons: list[str] = []
    while cursor <= final_month:
        label = season_name(cursor)
        if label not in seasons:
            seasons.append(label)
        cursor = (
            datetime(cursor.year + 1, 1, 1)
            if cursor.month == 12
            else datetime(cursor.year, cursor.month + 1, 1)
        )
    return tuple(seasons)


def _baseline_calibration_profile(
    baseline: dict[str, Any],
    *,
    candidate_request: dict[str, Any],
) -> dict[str, Any] | None:
    """Snapshot or reuse the reviewed baseline's immutable fit profile."""

    if str(baseline.get("mode") or "") != "validation":
        return None
    required_seasons = _validation_request_seasons(candidate_request)
    existing = (baseline.get("provenance") or {}).get(
        "calibration_profile"
    )
    if existing is not None:
        return validate_seasonal_calibration_profile(
            existing,
            required_seasons=required_seasons,
        )

    quality = _reviewed_baseline_data_quality(baseline)
    if quality is None:
        # Compatibility for local jobs created before calibration reviews.
        return None
    result = baseline.get("result") or {}
    stats = result.get("stats") or {}
    fit_metadata = (
        result.get("calibration_factors")
        or stats.get("calibration_factors")
    )
    if not isinstance(fit_metadata, dict):
        raise ValueError(
            "The reviewed baseline does not contain seasonal calibration factors."
        )
    factors: dict[str, dict[str, float]] = {}
    for record in fit_metadata.get("seasons") or []:
        if not isinstance(record, dict):
            raise ValueError(
                "The reviewed baseline contains an invalid seasonal factor record."
            )
        label = str(record.get("season") or "").strip().lower()
        if label in factors:
            raise ValueError(
                f"The reviewed baseline contains duplicate {label} factors."
            )
        systems = record.get("systems")
        if not label or not isinstance(systems, dict):
            raise ValueError(
                "The reviewed baseline contains an invalid seasonal factor record."
            )
        factors[label] = {}
        for system in ("solaredge", "solectria"):
            details = systems.get(system)
            if not isinstance(details, dict):
                raise ValueError(
                    f"The reviewed baseline {label} {system} factor is invalid."
                )
            factors[label][system] = details.get("factor")
    diagnostics = (
        result.get("factor_driver_diagnostics")
        or stats.get("factor_driver_diagnostics")
        or {}
    )
    profile = {
        "schema_version": CALIBRATION_PROFILE_SCHEMA_VERSION,
        "origin_job_id": str(baseline["id"]),
        "origin_source_sha256": str(baseline["source_hash"]),
        "origin_review_id": str(quality["review_id"]),
        "seasonal_factors": factors,
        "fit_metadata": deepcopy(fit_metadata),
        "factor_driver_diagnostics": deepcopy(diagnostics),
    }
    return validate_seasonal_calibration_profile(
        profile,
        required_seasons=required_seasons,
    )


def _proposal_policy(
    *,
    mode: str,
    comparison_kind: str,
    source_available: bool,
    baseline_missing: bool = False,
) -> tuple[bool, str]:
    confirmation_reasons: list[str] = []
    informational_reasons: list[str] = []
    if baseline_missing:
        confirmation_reasons.append("A completed baseline must be run first")
    if mode == "annual":
        confirmation_reasons.append("Annual scenarios always require confirmation")
    if comparison_kind == "cross_run":
        informational_reasons.append(
            "Fresh Bazefield data will be fetched; the interval or source data will differ, so results are descriptive only"
        )
    if comparison_kind == "same_input" and not source_available and not baseline_missing:
        confirmation_reasons.append(
            "The baseline source file or SHA-256 fingerprint is unavailable"
        )
    if _active_model_jobs():
        informational_reasons.append(
            "Another model job is active; this run will remain queued"
        )
    required = bool(confirmation_reasons)
    reasons = confirmation_reasons + informational_reasons
    return required, "; ".join(reasons) if reasons else (
        "Same interval and source data; only the requested parameters change"
    )


def _public_proposal(proposal: dict[str, Any]) -> dict[str, Any]:
    metadata = proposal.get("confirmation_metadata") or {}
    unchanged_fields: list[dict[str, Any]] = []
    if proposal.get("baseline_id"):
        baseline = _get_job_record(str(proposal["baseline_id"]))
        baseline_request = (baseline or {}).get("request") or {}
        candidate_request = proposal.get("effective_request") or {}
        changed_names = {
            str(item.get("field"))
            for item in (proposal.get("changes") or [])
            if isinstance(item, dict)
        }
        for field in SCENARIO_OVERRIDE_FIELDS:
            if field == "mode" or field in changed_names or field not in candidate_request:
                continue
            unchanged_fields.append(
                {
                    "field": field,
                    "label": SCENARIO_FIELD_LABELS[field],
                    "value": baseline_request.get(field, candidate_request.get(field)),
                }
            )
    return {
        "proposal_id": proposal["id"],
        "kind": metadata.get("job_kind", "candidate"),
        "status": proposal["state"],
        "baseline_job_id": proposal.get("baseline_id"),
        "mode": proposal["mode"],
        "comparison_kind": proposal["comparison_kind"],
        "confirmation_required": proposal["confirmation_required"],
        "confirmation_reason": proposal.get("confirmation_reason"),
        "changes": proposal.get("changes") or [],
        "unchanged_fields": unchanged_fields,
        "effective_request": proposal.get("effective_request") or {},
        "scenario_sweep": (
            deepcopy(metadata.get("scenario_sweep"))
            if isinstance(metadata.get("scenario_sweep"), dict)
            else None
        ),
        "expires_at": proposal.get("expires_at"),
        "created_at": proposal.get("created_at"),
        "confirmed_job_id": proposal.get("confirmed_job_id"),
    }


def _public_job(job: dict[str, Any]) -> dict[str, Any]:
    artifacts = job.get("artifacts") or {}
    input_plots = artifacts.get("input_plots") or job.get("input_plots")
    elapsed_seconds: float | None = None
    started_at = job.get("started_at") or job.get("created_at")
    if started_at:
        try:
            started = datetime.fromisoformat(str(started_at))
            if started.tzinfo is None:
                started = started.replace(tzinfo=timezone.utc)
            ended_raw = job.get("completed_at")
            ended = (
                datetime.fromisoformat(str(ended_raw))
                if ended_raw
                else datetime.now(timezone.utc)
            )
            if ended.tzinfo is None:
                ended = ended.replace(tzinfo=timezone.utc)
            elapsed_seconds = max((ended - started).total_seconds(), 0.0)
        except (TypeError, ValueError):
            pass
    payload = {
        "job_id": job["id"],
        "kind": job.get("kind", "manual"),
        "proposal_id": job.get("proposal_id"),
        "baseline_job_id": job.get("baseline_id"),
        "mode": job.get("mode", "validation"),
        "state": job.get("state", "queued"),
        "progress": job.get("progress", 0),
        "stage": job.get("stage", ""),
        "cancel_requested": bool(job.get("cancel_requested")),
        "created_at": job.get("created_at"),
        "started_at": job.get("started_at"),
        "completed_at": job.get("completed_at"),
        "elapsed_seconds": elapsed_seconds,
        "result": job.get("result"),
        "comparison": job.get("comparison"),
        "provenance": job.get("provenance"),
        "artifacts": artifacts,
        "request": job.get("request"),
    }
    if input_plots:
        payload["input_plots"] = input_plots
    if job.get("error"):
        payload["error"] = job["error"]
    return payload


def _chat_timing(
    *, gpt_seconds: float, model_job_id: str | None
) -> dict[str, Any]:
    """Build timing metadata for one Solar Agent response."""

    model_run_seconds: float | None = None
    model_run_status = "not_run"
    if model_job_id:
        job = _get_job_record(model_job_id)
        if job is not None:
            public_job = _public_job(job)
            state = str(public_job.get("state") or "not_run")
            model_run_status = "completed" if state == "done" else state
            elapsed = public_job.get("elapsed_seconds")
            if (
                state == "done"
                and isinstance(elapsed, (int, float))
                and math.isfinite(float(elapsed))
            ):
                model_run_seconds = round(max(float(elapsed), 0.0), 3)

    return {
        "response_timestamp": datetime.now(timezone.utc).isoformat(),
        "gpt_seconds": round(max(float(gpt_seconds), 0.0), 3),
        "model_run_seconds": model_run_seconds,
        "model_run_status": model_run_status,
    }


def _create_baseline_proposal(
    req: ChatRequest,
    mode: Literal["validation", "annual"],
    requested_overrides: dict[str, Any],
) -> dict[str, Any]:
    if not req.current_config:
        raise HTTPException(
            status_code=422,
            detail="No completed baseline exists. Use the visible dashboard form to run a baseline first.",
        )
    _, effective = _canonical_request(mode, req.current_config)
    proposal = AGENT_STORE.create_proposal(
        mode=mode,
        effective_request=effective,
        changes=[],
        baseline_id=None,
        comparison_kind="same_input",
        confirmation_required=True,
        confirmation_reason="No completed baseline exists for this mode",
        confirmation_metadata={
            "job_kind": "baseline",
            "deferred_scenario_overrides": requested_overrides,
        },
    )
    return proposal


def _calibration_review_required(
    *,
    effective_request: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return a non-mutating handoff to the visible calibration review flow."""

    message = (
        "This calibration request needs a visible Bazefield data-quality review "
        "before a model job can start. Select the requested range and settings in "
        "the Calibration form, retrieve the data, review every irregularity, choose "
        "Retain or Exclude where offered, and then apply the reviewed run. No Solar "
        "Agent proposal or model job was created."
    )
    request = deepcopy(effective_request) if effective_request else None
    result: dict[str, Any] = {
        "status": "data_review_required",
        "message": message,
    }
    action: dict[str, Any] = {
        "type": "data_review_required",
        "mode": "validation",
        "message": message,
    }
    if request is not None:
        result["effective_request"] = request
        action["effective_request"] = request
    return result, action


def _create_candidate_proposal(
    *,
    mode: Literal["validation", "annual"],
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    changes: list[dict[str, Any]],
    supersedes_id: str | None = None,
    scenario_sweep: dict[str, Any] | None = None,
) -> dict[str, Any]:
    baseline_mode = str(baseline.get("mode", "validation"))
    baseline_request = baseline.get("request") or {}
    source_path, source_hash = _verified_baseline_source(baseline)
    same_window = mode == baseline_mode and _same_input_context(
        mode, baseline_request, candidate
    )
    reusable = same_window and bool(source_path and source_hash)
    # A fresh fetch is not scientifically same-input even when the requested
    # timestamps match: only an identical verified source earns that label.
    comparison_kind = "same_input" if reusable else "cross_run"
    confirmation_required, confirmation_reason = _proposal_policy(
        mode=mode,
        comparison_kind=comparison_kind,
        source_available=bool(source_path and source_hash),
    )
    confirmation_metadata: dict[str, Any] = {
        "job_kind": "candidate",
        "source_reusable": reusable,
        "baseline_source_path": source_path if reusable else None,
        "baseline_source_hash": source_hash if reusable else None,
    }
    if scenario_sweep:
        confirmation_metadata["scenario_sweep"] = deepcopy(scenario_sweep)
    return AGENT_STORE.create_proposal(
        mode=mode,
        effective_request=candidate,
        changes=changes,
        baseline_id=str(baseline["id"]),
        comparison_kind=comparison_kind,
        confirmation_required=confirmation_required,
        confirmation_reason=confirmation_reason,
        confirmation_metadata=confirmation_metadata,
        supersedes_id=supersedes_id,
    )


def _proposal_confirmation_spec(
    proposal: dict[str, Any], *, automatic: bool = False
) -> dict[str, Any]:
    """Validate one proposal and build its immutable store confirmation input."""

    if proposal.get("confirmed_job_id"):
        existing = _get_job_record(str(proposal["confirmed_job_id"]))
        if existing is None:
            raise HTTPException(
                status_code=409,
                detail="The confirmed proposal references an unavailable job.",
            )
        return {"proposal_id": str(proposal["id"])}
    metadata = proposal.get("confirmation_metadata") or {}
    job_kind = str(metadata.get("job_kind", "candidate"))
    source_path: str | None = None
    source_hash: str | None = None
    provenance: dict[str, Any] = {}
    scenario_sweep = metadata.get("scenario_sweep")
    if isinstance(scenario_sweep, dict):
        provenance["scenario_sweep"] = deepcopy(scenario_sweep)
    baseline: dict[str, Any] | None = None
    if proposal.get("baseline_id"):
        baseline = _get_job_record(str(proposal["baseline_id"]))
    validation_quality: dict[str, Any] | None = None
    effective_request = dict(proposal.get("effective_request") or {})
    calibration_requested = bool(effective_request.get("calibrate_model", True))
    if proposal.get("mode") == "validation" and calibration_requested:
        if (
            job_kind != "candidate"
            or proposal.get("comparison_kind") != "same_input"
            or baseline is None
            or baseline.get("state") != "done"
        ):
            raise HTTPException(
                status_code=409,
                detail=(
                    "Calibration jobs that do not reuse a completed reviewed baseline "
                    "must start from the visible Calibration data-quality review."
                ),
            )
        validation_quality = _reviewed_baseline_data_quality(baseline)
        if validation_quality is None:
            raise HTTPException(
                status_code=409,
                detail=(
                    "The calibration baseline is not bound to a hash-verified "
                    "data-quality review. Use the visible Calibration form to review "
                    "the requested data before running this scenario."
                ),
            )
    if (
        proposal.get("baseline_id")
        and proposal.get("comparison_kind") == "same_input"
    ):
        source_path, source_hash = _verified_baseline_source(baseline)
        if not source_path or not source_hash:
            raise HTTPException(
                status_code=409,
                detail="The baseline source fingerprint is no longer valid. Confirm a fresh baseline run.",
            )
    if (
        proposal.get("mode") == "validation"
        and calibration_requested
        and job_kind == "candidate"
        and proposal.get("baseline_id")
    ):
        if baseline is None or baseline.get("state") != "done":
            raise HTTPException(
                status_code=409,
                detail="The completed baseline bound to this proposal is unavailable.",
            )
        try:
            profile = _baseline_calibration_profile(
                baseline,
                candidate_request=dict(proposal.get("effective_request") or {}),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=409,
                detail=(
                    "The reviewed baseline calibration profile is invalid or "
                    f"does not cover this date range: {exc}"
                ),
            ) from exc
        if profile is None:
            raise HTTPException(
                status_code=409,
                detail=(
                    "The reviewed baseline does not contain a frozen seasonal "
                    "calibration profile. Re-run it through the visible Calibration "
                    "data-quality review."
                ),
            )
        provenance["calibration_profile"] = profile
        provenance["data_quality"] = validation_quality
    return {
        "proposal_id": str(proposal["id"]),
        "job_kind": job_kind,
        "confirmation_metadata": {"automatic": automatic},
        "source_path": source_path,
        "source_hash": source_hash,
        "provenance": provenance or None,
    }


def _confirm_durable_proposals(
    proposals: list[dict[str, Any]], *, automatic: bool = False
) -> list[dict[str, Any]]:
    """Validate and enqueue a proposal group in one durable transaction."""

    if not proposals:
        raise ValueError("proposals must not be empty")
    confirmations = [
        _proposal_confirmation_spec(proposal, automatic=automatic)
        for proposal in proposals
    ]
    try:
        jobs = AGENT_STORE.confirm_proposals_batch(
            confirmations,
            max_active_jobs=MAX_ACTIVE_MODEL_JOBS,
        )
    except QueueCapacityExceeded as exc:
        raise HTTPException(
            status_code=429,
            detail="The model queue is full. Wait for an active run to finish and retry.",
        ) from exc
    for job in jobs:
        _cache_job_record(job)
    _WORKER_WAKE.set()
    return jobs


def _confirm_durable_proposal(
    proposal: dict[str, Any], *, automatic: bool = False
) -> dict[str, Any]:
    return _confirm_durable_proposals([proposal], automatic=automatic)[0]


def _handle_scenario_tool(
    req: ChatRequest, arguments: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    overrides = _explicit_overrides(arguments)
    target_mode = overrides.pop("mode", req.active_mode)
    if target_mode not in {"validation", "annual"}:
        raise HTTPException(status_code=422, detail="Unsupported analysis mode.")
    validation_only = {"from_time", "to_time", "interval_value", "interval_unit"}
    if target_mode == "annual" and validation_only.intersection(overrides):
        raise HTTPException(
            status_code=422,
            detail="Times and intervals can only be changed for calibration runs.",
        )
    if "interval_value" in overrides and "interval_unit" not in overrides:
        raise HTTPException(
            status_code=422,
            detail="An interval change must explicitly include minutes, hours, or days.",
        )

    with _ORCHESTRATION_LOCK:
        baseline = _visible_baseline(
            req,
            target_mode,
            allow_mode_change=target_mode != req.active_mode,
        )
        if baseline is None:
            if target_mode == "validation":
                effective_request: dict[str, Any] | None = None
                if req.current_config:
                    candidate_values = dict(req.current_config)
                    candidate_values.update(overrides)
                    try:
                        _, effective_request = _canonical_request(
                            "validation", candidate_values
                        )
                    except HTTPException:
                        effective_request = None
                return _calibration_review_required(
                    effective_request=effective_request
                )
            active_baseline = next(
                (
                    job
                    for job in _active_model_jobs()
                    if job.get("mode") == req.active_mode
                    and job.get("kind") in {"baseline", "manual"}
                ),
                None,
            )
            if active_baseline:
                raise HTTPException(
                    status_code=409,
                    detail="A baseline for the visible mode is already queued or running.",
                )
            deferred = dict(overrides)
            if target_mode != req.active_mode:
                deferred["mode"] = target_mode
            proposal = _create_baseline_proposal(req, req.active_mode, deferred)
            public = _public_proposal(proposal)
            return (
                {
                    "status": "baseline_required",
                    "message": "Run the visible dashboard configuration as a baseline before the requested scenario.",
                    "proposal": public,
                },
                {"type": "proposal", "proposal": public},
            )

        baseline_request = dict(baseline.get("request") or {})
        overrides = _apply_dependent_scenario_overrides(overrides, baseline_request)
        candidate_values = dict(baseline_request)
        candidate_values.update(overrides)
        _, candidate = _canonical_request(target_mode, candidate_values)
        changes = _scenario_changes(baseline_request, candidate)
        baseline_mode = str(baseline.get("mode", req.active_mode))
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
            raise HTTPException(
                status_code=422,
                detail="The requested settings are already active in the selected baseline.",
            )
        if target_mode == "validation":
            source_path, source_hash = _verified_baseline_source(baseline)
            same_verified_input = (
                baseline_mode == "validation"
                and _same_input_context("validation", baseline_request, candidate)
                and bool(source_path and source_hash)
            )
            calibration_requested = bool(candidate.get("calibrate_model", True))
            reusable_calibration = (
                same_verified_input
                and _reviewed_baseline_data_quality(baseline) is not None
            )
            if calibration_requested and not reusable_calibration:
                return _calibration_review_required(
                    effective_request=candidate
                )
        proposal = _create_candidate_proposal(
            mode=target_mode,
            baseline=baseline,
            candidate=candidate,
            changes=changes,
        )
        if not proposal["confirmation_required"]:
            job = _confirm_durable_proposal(proposal, automatic=True)
            public_job = _public_job(job)
            if proposal["comparison_kind"] == "cross_run":
                scenario_label = (
                    "calibration"
                    if bool(candidate.get("calibrate_model", True))
                    else "physics-model"
                )
                started_message = (
                    f"The {scenario_label} scenario was queued automatically. It will pull fresh "
                    "data from Bazefield. The interval or source data will differ, so the "
                    "comparison is descriptive only."
                )
            else:
                source_label = (
                    "source data"
                    if bool(candidate.get("calibrate_model", True))
                    else "verified physics-model source data"
                )
                started_message = (
                    "The scenario was queued automatically with the same interval and "
                    f"{source_label}; only the requested parameters will change."
                )
            return (
                {
                    "status": "started",
                    "message": started_message,
                    "job": public_job,
                },
                {"type": "job_started", "job": public_job},
            )
        public = _public_proposal(proposal)
        return (
            {
                "status": "confirmation_required",
                "message": proposal.get("confirmation_reason"),
                "proposal": public,
            },
            {"type": "proposal", "proposal": public},
        )


def _handle_parameter_sweep_tool(
    req: ChatRequest, arguments: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    requested_mode, parameter, parameter_config, values = (
        _parameter_sweep_values(arguments)
    )
    target_mode: Literal["validation", "annual"] = (
        requested_mode or req.active_mode
    )

    with _ORCHESTRATION_LOCK:
        baseline = _visible_baseline(req, target_mode)
        if baseline is None:
            if target_mode == "validation":
                effective_request: dict[str, Any] | None = None
                if req.current_config:
                    candidate_values = dict(req.current_config)
                    candidate_values.update(
                        _apply_dependent_scenario_overrides(
                            {parameter: values[0]}, candidate_values
                        )
                    )
                    try:
                        _, effective_request = _canonical_request(
                            "validation", candidate_values
                        )
                    except HTTPException:
                        effective_request = None
                return _calibration_review_required(
                    effective_request=effective_request
                )
            active_baseline = next(
                (
                    job
                    for job in _active_model_jobs()
                    if job.get("mode") == target_mode
                    and job.get("kind") in {"baseline", "manual"}
                ),
                None,
            )
            if active_baseline:
                raise HTTPException(
                    status_code=409,
                    detail="A baseline for the visible mode is already queued or running.",
                )
            proposal = _create_baseline_proposal(req, target_mode, {})
            public = _public_proposal(proposal)
            return (
                {
                    "status": "baseline_required",
                    "message": (
                        "Run the visible dashboard configuration as a baseline, "
                        "then request the parameter sweep again."
                    ),
                    "proposal": public,
                },
                {"type": "proposal", "proposal": public},
            )

        baseline_request = dict(baseline.get("request") or {})
        candidate_specs: list[dict[str, Any]] = []
        baseline_index: int | None = None
        for index, value in enumerate(values):
            candidate_values = dict(baseline_request)
            candidate_values.update(
                _apply_dependent_scenario_overrides(
                    {parameter: value}, baseline_request
                )
            )
            _, candidate = _canonical_request(target_mode, candidate_values)
            changes = _scenario_changes(baseline_request, candidate)
            if not changes:
                baseline_index = index
                continue
            candidate_specs.append(
                {
                    "index": index,
                    "value": value,
                    "candidate": candidate,
                    "changes": changes,
                }
            )

        if not candidate_specs:
            raise HTTPException(
                status_code=422,
                detail=(
                    "The selected baseline already represents every requested "
                    "sweep value."
                ),
            )

        if target_mode == "validation":
            source_path, source_hash = _verified_baseline_source(baseline)
            same_verified_input = (
                str(baseline.get("mode")) == "validation"
                and bool(source_path and source_hash)
            )
            calibration_requested = bool(
                candidate_specs[0]["candidate"].get("calibrate_model", True)
            )
            reusable_calibration = (
                same_verified_input
                and _reviewed_baseline_data_quality(baseline) is not None
            )
            if calibration_requested and not reusable_calibration:
                return _calibration_review_required(
                    effective_request=candidate_specs[0]["candidate"]
                )
            if calibration_requested:
                try:
                    profile = _baseline_calibration_profile(
                        baseline,
                        candidate_request=candidate_specs[0]["candidate"],
                    )
                except (KeyError, TypeError, ValueError) as exc:
                    raise HTTPException(
                        status_code=409,
                        detail=(
                            "The reviewed baseline calibration profile is invalid or "
                            f"does not cover this date range: {exc}"
                        ),
                    ) from exc
                if profile is None:
                    raise HTTPException(
                        status_code=409,
                        detail=(
                            "The reviewed baseline does not contain a frozen seasonal "
                            "calibration profile. Re-run it through the visible "
                            "Calibration data-quality review."
                        ),
                    )
            try:
                AGENT_STORE.ensure_job_capacity(
                    max_active_jobs=MAX_ACTIVE_MODEL_JOBS,
                    required=len(candidate_specs),
                )
            except QueueCapacityExceeded as exc:
                raise HTTPException(
                    status_code=429,
                    detail=(
                        "The model queue does not have room for this sweep. "
                        "Wait for active runs to finish and retry."
                    ),
                ) from exc

        baseline_parameter_value = baseline_request.get(parameter)
        if parameter == "iam_a_r" and baseline_request.get("iam_model") != "martin_ruiz":
            baseline_label = "Physical IAM"
            baseline_parameter_value = None
        elif (
            parameter == "curtailment_limit_kw"
            and not baseline_request.get("curtailment_enabled")
        ):
            baseline_label = "Curtailment off"
        else:
            unit = parameter_config.get("unit")
            baseline_label = (
                f"{parameter_config['label']} "
                f"{baseline_parameter_value}"
                + (f" {unit}" if unit else "")
            )

        sweep_id = f"parameter-{uuid.uuid4().hex[:12]}"
        sweep_common: dict[str, Any] = {
            "type": "parameter_sweep",
            "sweep_id": sweep_id,
            "parameter": parameter,
            "label": parameter_config["label"],
            "unit": parameter_config.get("unit"),
            "mode": target_mode,
            "values": values,
            "count": len(values),
            "candidate_count": len(candidate_specs),
            "baseline_job_id": str(baseline["id"]),
            "baseline_index": baseline_index,
            "baseline_value": (
                values[baseline_index] if baseline_index is not None else None
            ),
            "baseline_parameter_value": baseline_parameter_value,
            "baseline_label": baseline_label,
        }
        proposals: list[dict[str, Any]] = []
        for spec in candidate_specs:
            scenario_sweep = {
                **sweep_common,
                "index": spec["index"],
                "value": spec["value"],
            }
            proposal = _create_candidate_proposal(
                mode=target_mode,
                baseline=baseline,
                candidate=spec["candidate"],
                changes=spec["changes"],
                scenario_sweep=scenario_sweep,
            )
            proposals.append(proposal)

        jobs: list[dict[str, Any]] = []
        if proposals and not proposals[0]["confirmation_required"]:
            jobs = _confirm_durable_proposals(proposals, automatic=True)

        public_sweep = deepcopy(sweep_common)
        if jobs:
            public_jobs = [_public_job(job) for job in jobs]
            public_sweep["job_ids"] = [job["job_id"] for job in public_jobs]
            baseline_note = (
                f" The baseline already represents "
                f"{parameter_config['label']} "
                f"{values[baseline_index]:g}"
                + (
                    f" {parameter_config['unit']}"
                    if parameter_config.get("unit")
                    else ""
                )
                + ", so it is reused as that row."
                if baseline_index is not None
                else ""
            )
            source_description = (
                "reviewed, hash-verified baseline source"
                if bool(baseline_request.get("calibrate_model", True))
                else "hash-verified physics-model baseline source"
            )
            message = (
                f"Queued {len(public_jobs)} controlled "
                f"{parameter_config['label']} scenario runs "
                f"from the same {source_description}. The "
                "comparison table will update as each value completes."
                + baseline_note
            )
            return (
                {
                    "status": "batch_started",
                    "message": message,
                    "sweep": public_sweep,
                    "job_ids": public_sweep["job_ids"],
                },
                {
                    "type": "job_batch_started",
                    "sweep": public_sweep,
                    "jobs": public_jobs,
                },
            )

        public_proposals = [_public_proposal(item) for item in proposals]
        public_sweep["proposal_ids"] = [
            item["proposal_id"] for item in public_proposals
        ]
        message = (
            f"The annual {parameter_config['label']} sweep is ready for one "
            "grouped confirmation. "
            f"Confirm it in Scenario Runs to queue {len(public_proposals)} "
            "controlled runs against the same baseline."
        )
        return (
            {
                "status": "confirmation_required",
                "message": message,
                "sweep": public_sweep,
                "proposal_ids": public_sweep["proposal_ids"],
            },
            {
                "type": "proposal_batch",
                "sweep": public_sweep,
                "proposals": public_proposals,
            },
        )


def _handle_iam_ar_sweep_tool(
    req: ChatRequest, arguments: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Backward-compatible adapter for pre-generalization IAM sweep calls."""

    return _handle_parameter_sweep_tool(
        req,
        {
            "mode": arguments.get("mode"),
            "parameter": "iam_a_r",
            "start": arguments.get("start_a_r"),
            "stop": arguments.get("stop_a_r"),
            "increment": arguments.get("increment"),
        },
    )


def _clean_chat_history(
    history: list[ChatMessage], *, current_message: str | None = None
) -> list[dict[str, str]]:
    cleaned: list[dict[str, str]] = []
    for item in history[-8:]:
        role = item.role if item.role in {"user", "assistant"} else "user"
        content = (item.content or "").strip()
        if not content:
            continue
        cleaned.append({"role": role, "content": content[:1400]})
    if (
        cleaned
        and cleaned[-1]["role"] == "user"
        and current_message
        and cleaned[-1]["content"] == current_message.strip()[:1400]
    ):
        cleaned.pop()
    return cleaned


def _deduplicated_job_context(job: dict[str, Any]) -> dict[str, Any]:
    """Keep trusted fields while removing large values repeated in nested sections."""

    result = deepcopy(job.get("result") or {})
    if not isinstance(result, dict):
        result = {}
    stats = result.get("stats")
    if isinstance(stats, dict):
        stats = deepcopy(stats)
        for key in (
            "calibration_factors",
            "factor_driver_diagnostics",
            "data_quality",
            "data_quality_review",
            "data_quality_warnings",
        ):
            if key in result and stats.get(key) == result.get(key):
                stats.pop(key, None)
        result["stats"] = stats

    provenance = deepcopy(job.get("provenance") or {})
    if isinstance(provenance, dict):
        if provenance.get("data_quality") == result.get("data_quality"):
            provenance.pop("data_quality", None)

    artifacts = deepcopy(job.get("artifacts") or {})
    if isinstance(artifacts, dict):
        workbook = artifacts.get("model_workbook")
        if isinstance(workbook, dict) and workbook.get("url") == result.get("excel"):
            artifacts.pop("model_workbook", None)
        if artifacts.get("input_plots") == result.get("input_plots"):
            artifacts.pop("input_plots", None)

    return {
        "result": result,
        "provenance": provenance,
        "artifacts": artifacts,
    }


def _chat_run_context(
    job_id: str | None, active_mode: str | None = None
) -> tuple[str | None, dict]:
    resolved_job_id = job_id or _latest_completed_job_id(active_mode)
    if not resolved_job_id:
        return None, {
            "state": "missing",
            "message": "No completed dashboard run is available yet.",
        }

    job_record = _get_job_record(resolved_job_id)
    job = None if job_record is None else {**job_record, **JOBS.get(resolved_job_id, {})}
    if job is None:
        return resolved_job_id, {
            "job_id": resolved_job_id,
            "state": "missing",
            "message": (
                "The browser had a cached job id, but this FastAPI process does "
                "not have that job in memory. Ask the user to rerun analysis for "
                "grounded run-specific answers."
            ),
        }

    context = {
        "job_id": resolved_job_id,
        "mode": job.get("mode", "validation"),
        "state": job.get("state"),
        "progress": job.get("progress", 0),
        "stage": job.get("stage", ""),
    }
    if "request" in job:
        context["request"] = job["request"]
    if job.get("state") == "done":
        compact = _deduplicated_job_context(job)
        context["result"] = compact["result"]
        if job.get("comparison"):
            context["comparison"] = job["comparison"]
        if compact["provenance"]:
            context["provenance"] = compact["provenance"]
        if compact["artifacts"]:
            context["artifacts"] = compact["artifacts"]
    elif job.get("state") == "error":
        context["error"] = job.get("error", "Unknown error")
    return resolved_job_id, context


def _should_allow_web_search(message: str) -> bool:
    import re

    text = (message or "").lower()
    explicit_external_intent = re.search(
        r"\b(?:web|internet|online|sources?|citations?|references?|external|research|search)\b"
        r"|\blook\s+up\b",
        text,
    )
    if explicit_external_intent:
        return True
    if re.search(r"\b(?:weather|forecast|nrel|pvlib|pvmismatch)\b", text):
        return True
    current_external_topic = re.search(
        r"\b(?:latest|current|today|recent)\b.*"
        r"\b(?:news|version|release|documentation|standard|specification|policy|law|price)\b"
        r"|\b(?:news|version|release|documentation|standard|specification|policy|law|price)\b.*"
        r"\b(?:latest|current|today|recent)\b",
        text,
    )
    return current_external_topic is not None


def _extract_response_text(response) -> str:
    text = getattr(response, "output_text", None)
    if text:
        return text
    output = getattr(response, "output", None) or []
    parts: list[str] = []
    for item in output:
        content = getattr(item, "content", None) or []
        for block in content:
            block_text = getattr(block, "text", None)
            if block_text:
                parts.append(block_text)
    return "\n".join(parts).strip()


def _extract_web_sources(response: Any) -> list[dict[str, str]]:
    """Extract URL citations without mixing them into trusted model evidence."""
    sources: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in (getattr(response, "output", None) or []):
        for block in (_response_item_value(item, "content", []) or []):
            for annotation in (_response_item_value(block, "annotations", []) or []):
                citation = _response_item_value(annotation, "url_citation", annotation)
                url = _response_item_value(citation, "url")
                if not isinstance(url, str) or not url.startswith(("https://", "http://")):
                    continue
                if url in seen:
                    continue
                seen.add(url)
                title = _response_item_value(citation, "title") or "External source"
                sources.append({"title": str(title)[:200], "url": url})
    return sources


def _response_item_value(item: Any, name: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(name, default)
    return getattr(item, name, default)


def _scenario_tool_calls(response: Any) -> list[Any]:
    supported_tools = {
        "propose_model_scenario",
        "run_model_parameter_sweep",
        "run_iam_ar_sweep",
    }
    return [
        item
        for item in (getattr(response, "output", None) or [])
        if _response_item_value(item, "type") == "function_call"
        and _response_item_value(item, "name") in supported_tools
    ]


def _openai_agent_response(req: ChatRequest) -> dict[str, Any]:
    if not (req.message or "").strip():
        raise HTTPException(status_code=422, detail="Message is required.")
    if len(req.message) > 4000:
        raise HTTPException(
            status_code=422, detail="Message must be 4,000 characters or fewer."
        )

    resolved_job_id, run_context = _chat_run_context(req.job_id, req.active_mode)
    gpt_seconds = 0.0
    if _ambiguous_numeric_iam(req.message):
        result = {
            "reply": (
                "**IAM clarification**\n\nYour model supports **Physical IAM** or "
                "**Martin-Ruiz IAM** with an `a_r` coefficient. Is your numeric "
                "value intended to be the Martin-Ruiz `a_r`, or do you want to "
                "keep Physical IAM? "
                "I will not start a run until that is explicit."
            ),
            "job_id": resolved_job_id,
            "web_search_enabled": False,
            "action": None,
        }
        result["timing"] = _chat_timing(
            gpt_seconds=gpt_seconds, model_job_id=resolved_job_id
        )
        return result

    try:
        from openai import OpenAI
    except ImportError as exc:
        raise HTTPException(
            status_code=503,
            detail=(
                "The OpenAI Python package is not installed. Install the project "
                "dependencies from requirements.txt, then restart the server."
            ),
        ) from exc

    if not os.getenv("OPENAI_API_KEY"):
        raise HTTPException(
            status_code=503,
            detail="OPENAI_API_KEY is not available to the server process.",
        )

    allow_web = _should_allow_web_search(req.message)
    tools: list[dict[str, Any]] = (
        [SCENARIO_TOOL, PARAMETER_SWEEP_TOOL]
        if req.allow_scenario_actions
        else []
    )
    if allow_web:
        tools.append({"type": "web_search"})
    payload = {
        "question": req.message.strip(),
        "dashboard_run_context": run_context,
        "active_mode": req.active_mode,
        "visible_dashboard_configuration": _normalise_config_keys(
            req.current_config
        ),
        "visible_iam_selection": _visible_iam_selection(req.current_config),
        "model_knowledge": SOLAR_MODEL_KNOWLEDGE,
        "recent_chat_history": _clean_chat_history(
            req.history, current_message=req.message
        ),
    }
    user_input = {
        "role": "user",
        "content": (
            "Answer the user's question using this JSON context. Prefer dashboard "
            "context over external sources for run-specific facts.\n\n"
            + json.dumps(payload, indent=2, default=str)
        ),
    }

    try:
        client = OpenAI(
            timeout=OPENAI_TIMEOUT_SECONDS,
            max_retries=OPENAI_MAX_RETRIES,
        )
    except TypeError:
        # Lightweight test doubles and older compatible clients may not expose
        # constructor options. The supported production SDK does.
        client = OpenAI()
    gpt_started = perf_counter()
    try:
        request_options: dict[str, Any] = {}
        if req.allow_scenario_actions:
            request_options.update(
                {"max_tool_calls": 1, "parallel_tool_calls": False}
            )
        response = client.responses.create(
            model=os.getenv("OPENAI_MODEL", "gpt-5.5"),
            instructions=SOLAR_AGENT_INSTRUCTIONS,
            input=[user_input],
            tools=tools,
            store=False,
            max_output_tokens=1_200,
            text={"verbosity": "low"},
            **request_options,
        )
    except Exception as exc:
        logger.error(
            "OpenAI request failed: type=%s status=%s request_id=%s",
            exc.__class__.__name__,
            getattr(exc, "status_code", None),
            getattr(exc, "request_id", None),
        )
        raise HTTPException(
            status_code=502,
            detail="Solar Agent is temporarily unavailable. Please retry.",
        ) from exc
    finally:
        gpt_seconds += perf_counter() - gpt_started

    web_sources = _extract_web_sources(response)
    action: dict[str, Any] | None = None
    deterministic_reply: str | None = None
    tool_calls = _scenario_tool_calls(response) if req.allow_scenario_actions else []
    if len(tool_calls) > 1:
        deterministic_reply = (
            "I did not start a run because more than one scenario action was "
            "requested in the same response. Please ask for one scenario or one "
            "parameter sweep at a time."
        )
        tool_calls = []
    if tool_calls:
        tool_call = tool_calls[0]
        try:
            arguments = json.loads(_response_item_value(tool_call, "arguments", "{}"))
            if not isinstance(arguments, dict):
                raise ValueError("Tool arguments must be an object")
            tool_name = _response_item_value(tool_call, "name")
            if tool_name == "run_model_parameter_sweep":
                tool_result, action = _handle_parameter_sweep_tool(req, arguments)
            elif tool_name == "run_iam_ar_sweep":
                tool_result, action = _handle_iam_ar_sweep_tool(req, arguments)
            else:
                tool_result, action = _handle_scenario_tool(req, arguments)
        except HTTPException as exc:
            tool_result = {"status": "rejected", "message": str(exc.detail)}
            action = None
        except (TypeError, ValueError, json.JSONDecodeError):
            tool_result = {
                "status": "rejected",
                "message": "The requested scenario settings were invalid.",
            }
            action = None
        deterministic_reply = str(
            tool_result.get("message") or "Scenario request prepared."
        )

    reply = deterministic_reply or _extract_response_text(response)
    if not reply:
        reply = "I could not generate a response from the model for this question."
    result = {
        "reply": reply,
        "job_id": resolved_job_id,
        "web_search_enabled": allow_web,
        "web_sources": web_sources,
        "action": action,
    }
    timing_job_id = resolved_job_id
    if action:
        if action.get("type") == "job_started":
            timing_job_id = (action.get("job") or {}).get("job_id")
        elif action.get("type") == "job_batch_started":
            jobs = action.get("jobs") or []
            timing_job_id = jobs[0].get("job_id") if jobs else None
        elif action.get("type") in {"proposal", "proposal_batch"}:
            timing_job_id = None
    result["timing"] = _chat_timing(
        gpt_seconds=gpt_seconds, model_job_id=timing_job_id
    )
    return result


def _openai_chat_response(req: ChatRequest) -> tuple[str, str | None, bool]:
    """Backward-compatible helper used by the existing unit tests."""
    result = _openai_agent_response(req)
    return result["reply"], result["job_id"], result["web_search_enabled"]


def _start_model_worker() -> None:
    global _WORKER_THREAD
    with _WORKER_LOCK:
        if _WORKER_THREAD is not None and _WORKER_THREAD.is_alive():
            return
        _WORKER_STOP.clear()
        _WORKER_THREAD = threading.Thread(
            target=_model_worker_loop,
            name="solar-model-worker",
            daemon=True,
        )
        _WORKER_THREAD.start()


def _stop_model_worker() -> None:
    global _WORKER_THREAD
    with _WORKER_LOCK:
        worker = _WORKER_THREAD
        if worker is None:
            return
        _WORKER_STOP.set()
        _WORKER_WAKE.set()
    worker.join(timeout=5)
    with _WORKER_LOCK:
        if not worker.is_alive():
            _WORKER_THREAD = None


def _heartbeat_model_job(
    job_id: str, lease_token: str, stop: threading.Event
) -> None:
    while not stop.wait(JOB_HEARTBEAT_SECONDS):
        try:
            if not AGENT_STORE.heartbeat_job(
                job_id,
                worker_id=SERVER_SESSION_ID,
                lease_token=lease_token,
            ):
                return
        except Exception:
            logger.exception("Could not renew the lease for model job %s", job_id)


def _model_worker_loop() -> None:
    next_stale_check = 0.0
    while not _WORKER_STOP.is_set():
        try:
            now = perf_counter()
            if now >= next_stale_check:
                interrupted = AGENT_STORE.mark_stale_running_jobs_interrupted(
                    before=datetime.now(timezone.utc)
                    - timedelta(seconds=JOB_STALE_SECONDS)
                )
                if interrupted:
                    logger.warning(
                        "Marked %s expired model job lease(s) interrupted",
                        interrupted,
                    )
                next_stale_check = now + min(JOB_STALE_SECONDS / 2, 30)
            record = AGENT_STORE.claim_next_queued_job(
                worker_id=SERVER_SESSION_ID
            )
        except AgentStoreError:
            logger.exception("The durable model queue could not claim a job")
            _WORKER_WAKE.wait(1.0)
            _WORKER_WAKE.clear()
            continue
        if record is None:
            _WORKER_WAKE.wait(0.5)
            _WORKER_WAKE.clear()
            continue
        _cache_job_record(record)
        job_id = str(record["id"])
        lease_token = str(record.get("lease_token") or "")
        if not lease_token:
            logger.error("Claimed model job %s without a lease token", job_id)
            continue
        heartbeat_stop = threading.Event()
        heartbeat = threading.Thread(
            target=_heartbeat_model_job,
            args=(job_id, lease_token, heartbeat_stop),
            name=f"solar-model-heartbeat-{job_id[:12]}",
            daemon=True,
        )
        heartbeat.start()
        try:
            if record["mode"] == "annual":
                req = AnnualRunRequest(**record["request"])
                _validate_run_request(req)
                _validate_curtailment(req)
                _annual_dates(req)
                _run_annual_job(
                    job_id,
                    req,
                    source_path=record.get("source_path"),
                    expected_source_hash=record.get("source_hash"),
                    worker_id=SERVER_SESSION_ID,
                    lease_token=lease_token,
                )
            else:
                req = RunRequest(**record["request"])
                _validate_run_request(req)
                _validate_curtailment(req)
                provenance = record.get("provenance") or {}
                _run_job(
                    job_id,
                    req,
                    source_path=record.get("source_path"),
                    expected_source_hash=record.get("source_hash"),
                    data_quality_context=provenance.get("data_quality"),
                    calibration_profile=provenance.get(
                        "calibration_profile"
                    ),
                    worker_id=SERVER_SESSION_ID,
                    lease_token=lease_token,
                )
        except LeaseOwnershipLost:
            removed = _delete_job_attempt_artifacts(job_id, lease_token)
            logger.warning(
                "Stopped model job %s after its lease was lost; removed %s "
                "expired attempt artifact(s)",
                job_id,
                removed,
            )
        except Exception:
            logger.exception("Unhandled model worker failure for %s", job_id)
            current = _get_job_record(job_id)
            if current and current.get("state") == "running":
                try:
                    _update_job(
                        job_id,
                        worker_id=SERVER_SESSION_ID,
                        lease_token=lease_token,
                        state="error",
                        stage="Failed",
                        error="The model run failed. Review server logs and retry.",
                    )
                except LeaseOwnershipLost:
                    logger.warning(
                        "Ignored failure transition for %s after lease loss", job_id
                    )
        finally:
            heartbeat_stop.set()
            heartbeat.join(timeout=1)


def _artifact_file(result: dict[str, Any], key: str) -> Path:
    stats = result.get("stats") or {}
    raw = stats.get(key) or result.get(key)
    if not raw:
        raise ValueError(f"Model result is missing the {key} artifact")
    raw_path = Path(str(raw))
    if raw_path.is_absolute():
        return raw_path
    return OUTPUT_DIR / raw_path.name


def _finish_model_job(
    job_id: str,
    result: dict[str, Any],
    *,
    worker_id: str | None = None,
    lease_token: str | None = None,
) -> None:
    record = _get_job_record(job_id) or {"id": job_id, **JOBS.get(job_id, {})}
    artifacts = dict(record.get("artifacts") or {})
    if JOBS.get(job_id, {}).get("input_plots"):
        artifacts["input_plots"] = JOBS[job_id]["input_plots"]
    artifacts.setdefault(
        "model_workbook",
        {
            "path": str(_artifact_file(result, "excel")),
            "url": result.get("excel"),
            "filename": result.get("excel_filename"),
        },
    )

    comparison = None
    provenance = record.get("provenance")
    baseline_id = record.get("baseline_id")
    if baseline_id:
        _update_job(
            job_id,
            worker_id=worker_id,
            lease_token=lease_token,
            progress=97,
            stage="Calculating trusted comparison",
        )
        _check_job_cancelled(
            job_id, worker_id=worker_id, lease_token=lease_token
        )
        baseline = _get_job_record(str(baseline_id))
        if baseline is None or baseline.get("state") != "done":
            raise ValueError("The bound baseline is not available as a completed job")
        baseline_result = baseline.get("result") or {}
        comparison_type = "cross_run"
        if record.get("proposal_id"):
            proposal = AGENT_STORE.get_proposal(str(record["proposal_id"]))
            if proposal:
                comparison_type = proposal["comparison_kind"]
        generated = generate_comparison_artifacts(
            _artifact_file(baseline_result, "excel"),
            _artifact_file(result, "excel"),
            OUTPUT_DIR / _job_attempt_prefix(job_id, lease_token),
            baseline_job_id=str(baseline_id),
            candidate_job_id=job_id,
            baseline_request=baseline.get("request") or {},
            candidate_request=record.get("request") or {},
            baseline_source_path=baseline.get("source_path"),
            candidate_source_path=record.get("source_path"),
            baseline_source_sha256=baseline.get("source_hash"),
            candidate_source_sha256=record.get("source_hash"),
            comparison_type=comparison_type,
            mode=record.get("mode"),
            extra_warnings=tuple(result.get("warnings") or ()),
        )
        comparison = generated["comparison"]
        provenance = {
            **dict(provenance or {}),
            **dict(generated["provenance"] or {}),
        }
        artifacts.update(generated["artifacts"])

    _check_job_cancelled(job_id, worker_id=worker_id, lease_token=lease_token)
    _update_job(
        job_id,
        worker_id=worker_id,
        lease_token=lease_token,
        state="done",
        progress=100,
        stage="Done",
        result=result,
        comparison=comparison,
        provenance=provenance,
        artifacts=artifacts,
        error=None,
    )
    completed = _get_job_record(job_id)
    if (
        completed
        and completed.get("kind") in {"baseline", "manual"}
    ):
        try:
            AGENT_STORE.promote_job(job_id)
        except AgentStoreError:
            logger.exception("Completed baseline %s could not be promoted", job_id)


def _handle_model_failure(
    job_id: str,
    exc: Exception,
    *,
    worker_id: str | None = None,
    lease_token: str | None = None,
) -> None:
    if isinstance(exc, LeaseOwnershipLost):
        removed = _delete_job_attempt_artifacts(job_id, lease_token)
        logger.warning(
            "Ignoring model job %s after its lease was lost; removed %s "
            "expired attempt artifact(s)",
            job_id,
            removed,
        )
        return
    try:
        cancelled = _job_cancel_requested(
            job_id, worker_id=worker_id, lease_token=lease_token
        )
    except LeaseOwnershipLost:
        removed = _delete_job_attempt_artifacts(job_id, lease_token)
        logger.warning(
            "Ignoring model job %s after its lease was lost; removed %s "
            "expired attempt artifact(s)",
            job_id,
            removed,
        )
        return
    if isinstance(exc, _JobCancelled) or cancelled:
        current = _get_job_record(job_id)
        if current and current.get("state") == "running":
            try:
                _update_job(
                    job_id,
                    worker_id=worker_id,
                    lease_token=lease_token,
                    state="cancelled",
                    stage="Cancelled",
                    error=None,
                )
            except LeaseOwnershipLost:
                logger.warning(
                    "Ignored cancellation transition for %s after lease loss", job_id
                )
        return
    logger.error("Model job %s failed\n%s", job_id, traceback.format_exc())
    JOBS.setdefault(job_id, {})["traceback"] = traceback.format_exc()
    current = _get_job_record(job_id)
    if current and current.get("state") == "running":
        try:
            _update_job(
                job_id,
                worker_id=worker_id,
                lease_token=lease_token,
                state="error",
                stage="Failed",
                error="The model run failed. Review server logs and retry.",
            )
        except LeaseOwnershipLost:
            logger.warning(
                "Ignored failure transition for %s after lease loss", job_id
            )
    else:
        JOBS[job_id]["state"] = "error"
        JOBS[job_id]["error"] = str(exc) or exc.__class__.__name__


def _run_job(
    job_id: str,
    req: RunRequest,
    *,
    source_path: str | Path | None = None,
    expected_source_hash: str | None = None,
    data_quality_context: dict[str, Any] | None = None,
    calibration_profile: dict[str, Any] | None = None,
    worker_id: str | None = None,
    lease_token: str | None = None,
) -> None:
    JOBS.setdefault(job_id, {"mode": "validation", "state": "running"})

    def set_progress(pct: int, stage: str) -> None:
        _check_job_cancelled(
            job_id, worker_id=worker_id, lease_token=lease_token
        )
        _update_job(
            job_id,
            worker_id=worker_id,
            lease_token=lease_token,
            progress=int(pct),
            stage=stage,
        )

    try:
        from_iso = _iso(req.from_date, req.from_time)
        to_iso = _iso(req.to_date, req.to_time)
        interval_seconds = int(req.interval_value) * UNIT_SECONDS[req.interval_unit]
        attempt_prefix = _job_attempt_prefix(job_id, lease_token)
        csv_path = (
            Path(source_path)
            if source_path and expected_source_hash
            else OUTPUT_DIR / f"{attempt_prefix}.csv"
        )
        base_path = OUTPUT_DIR / attempt_prefix

        if source_path and expected_source_hash:
            set_progress(5, "Verifying cached baseline source")
            source_hash = verify_source_sha256(csv_path, expected_source_hash)
            with csv_path.open("rb") as handle:
                n = max(sum(1 for _ in handle) - 1, 0)
        else:
            set_progress(5, "Pulling data from Bazefield")
            n = historian.run_historian(
                from_time=from_iso,
                to_time=to_iso,
                interval=str(interval_seconds),
                output_csv=str(csv_path),
            )
            _check_job_cancelled(
                job_id, worker_id=worker_id, lease_token=lease_token
            )
            source_hash = sha256_file(csv_path)
        _update_job(
            job_id,
            worker_id=worker_id,
            lease_token=lease_token,
            source_path=str(csv_path.resolve()),
            source_hash=source_hash,
        )
        _check_job_cancelled(
            job_id, worker_id=worker_id, lease_token=lease_token
        )
        input_plots = _render_input_data_plots(csv_path, base_path)
        existing_artifacts = (_get_job_record(job_id) or {}).get("artifacts") or {}
        _update_job(
            job_id,
            worker_id=worker_id,
            lease_token=lease_token,
            artifacts={**existing_artifacts, "input_plots": input_plots},
        )
        set_progress(20, f"Loaded {n} rows; running pvlib ModelChain")

        def progress_cb(frac: float, msg: str) -> None:
            set_progress(25 + int(frac * 65), msg)

        stats = model.run_model(
            input_csv=str(csv_path),
            output_base=str(base_path),
            progress_cb=progress_cb,
            backtrack=req.backtrack,
            solaredge_inverter_efficiency=req.solaredge_inverter_efficiency,
            solaredge_bos_efficiency=req.solaredge_bos_efficiency,
            solectria_inverter_efficiency=req.solectria_inverter_efficiency,
            solectria_bos_efficiency=req.solectria_bos_efficiency,
            iam_model=req.iam_model,
            iam_a_r=(req.iam_a_r if req.iam_model == "martin_ruiz" else None),
            curtailment_enabled=req.curtailment_enabled,
            curtailment_limit_kw=req.curtailment_limit_kw,
            data_quality_context=data_quality_context,
            expected_interval_seconds=interval_seconds,
            requested_start=from_iso,
            requested_end=to_iso,
            calibration_profile=calibration_profile,
            calibrate_model=req.calibrate_model,
        )
        set_progress(95, "Finalizing model artifacts")
        result = {
            "mode": "validation",
            "stats": stats,
            "ac_png": _output_url(Path(stats["ac_png"])),
            "energy_png": _output_url(Path(stats["energy_png"])),
            "uncalibrated_ac_png": (
                _output_url(Path(stats["uncalibrated_ac_png"]))
                if stats.get("uncalibrated_ac_png")
                else None
            ),
            "uncalibrated_energy_png": (
                _output_url(Path(stats["uncalibrated_energy_png"]))
                if stats.get("uncalibrated_energy_png")
                else None
            ),
            "excel": _output_url(Path(stats["excel"])),
            "excel_filename": _workbook_download_name(
                req,
                calibrated=stats.get("calibration_enabled") is True,
            ),
            "input_plots": JOBS[job_id].get("input_plots"),
            "source_csv": _public_source_url(csv_path),
            "data_quality": data_quality_context,
            "calibration_factors": stats.get("calibration_factors"),
            "factor_driver_diagnostics": stats.get(
                "factor_driver_diagnostics"
            ),
            "window": {
                **_validation_window_metadata(from_iso, to_iso),
                "interval_seconds": interval_seconds,
                "backtrack": req.backtrack,
                "solaredge_inverter_efficiency": req.solaredge_inverter_efficiency,
                "solaredge_bos_efficiency": req.solaredge_bos_efficiency,
                "solectria_inverter_efficiency": req.solectria_inverter_efficiency,
                "solectria_bos_efficiency": req.solectria_bos_efficiency,
                "solaredge_total_efficiency": (
                    req.solaredge_inverter_efficiency * req.solaredge_bos_efficiency
                ),
                "solectria_total_efficiency": (
                    req.solectria_inverter_efficiency * req.solectria_bos_efficiency
                ),
                **_iam_metadata(req),
                "curtailment_enabled": req.curtailment_enabled,
                "curtailment_limit_kw": (
                    float(req.curtailment_limit_kw)
                    if req.curtailment_enabled
                    else None
                ),
                "calibrate_model": req.calibrate_model,
            },
        }
        _finish_model_job(
            job_id,
            result,
            worker_id=worker_id,
            lease_token=lease_token,
        )
    except Exception as exc:
        _handle_model_failure(
            job_id,
            exc,
            worker_id=worker_id,
            lease_token=lease_token,
        )


def _run_annual_job(
    job_id: str,
    req: AnnualRunRequest,
    *,
    source_path: str | Path | None = None,
    expected_source_hash: str | None = None,
    worker_id: str | None = None,
    lease_token: str | None = None,
) -> None:
    JOBS.setdefault(job_id, {"mode": "annual", "state": "running"})

    def set_progress(pct: int, stage: str) -> None:
        _check_job_cancelled(
            job_id, worker_id=worker_id, lease_token=lease_token
        )
        _update_job(
            job_id,
            worker_id=worker_id,
            lease_token=lease_token,
            progress=int(pct),
            stage=stage,
        )

    try:
        start_date, end_date = _annual_dates(req)
        attempt_prefix = _job_attempt_prefix(job_id, lease_token)
        csv_path = (
            Path(source_path)
            if source_path and expected_source_hash
            else OUTPUT_DIR / f"{attempt_prefix}_midc_hourly.csv"
        )
        base_path = OUTPUT_DIR / attempt_prefix
        source_warnings: list[str] = []
        source_quality: dict[str, Any]

        if source_path and expected_source_hash:
            set_progress(5, "Verifying cached annual source")
            source_hash = verify_source_sha256(csv_path, expected_source_hash)
            import pandas as pd

            hourly_rows = int(len(pd.read_csv(csv_path)))
            source_quality = {
                "raw_rows": None,
                "hourly_rows": hourly_rows,
                "chunk_count": None,
                "missing_value_count": None,
                "affected_hour_count": None,
                "reused_verified_source": True,
            }
        else:
            def download_progress(frac: float, msg: str) -> None:
                set_progress(5 + int(frac * 20), msg)

            set_progress(5, "Downloading MIDC minute data")
            source = midc.fetch_hourly_data(
                start_date,
                end_date,
                progress_cb=download_progress,
            )
            _check_job_cancelled(
                job_id, worker_id=worker_id, lease_token=lease_token
            )
            set_progress(27, "Saving exact MIDC hourly source")
            midc.write_csv_atomically(source.hourly, csv_path)
            source_hash = sha256_file(csv_path)
            source_warnings = list(source.warnings)
            source_quality = {
                "raw_rows": source.raw_rows,
                "hourly_rows": int(len(source.hourly)),
                "chunk_count": source.chunk_count,
                "missing_value_count": source.missing_value_count,
                "affected_hour_count": source.affected_hour_count,
                "reused_verified_source": False,
            }
        _update_job(
            job_id,
            worker_id=worker_id,
            lease_token=lease_token,
            source_path=str(csv_path.resolve()),
            source_hash=source_hash,
        )
        set_progress(28, "Rendering annual irradiance inputs")
        input_plots = _render_midc_input_data_plots(csv_path, base_path)
        existing_artifacts = (_get_job_record(job_id) or {}).get("artifacts") or {}
        _update_job(
            job_id,
            worker_id=worker_id,
            lease_token=lease_token,
            artifacts={**existing_artifacts, "input_plots": input_plots},
        )

        def model_progress(frac: float, msg: str) -> None:
            set_progress(30 + int(frac * 60), msg)

        set_progress(30, "Running annual PV model")
        stats = model.run_model(
            input_csv=str(csv_path),
            output_base=str(base_path),
            progress_cb=model_progress,
            backtrack=req.backtrack,
            solaredge_inverter_efficiency=req.solaredge_inverter_efficiency,
            solaredge_bos_efficiency=req.solaredge_bos_efficiency,
            solectria_inverter_efficiency=req.solectria_inverter_efficiency,
            solectria_bos_efficiency=req.solectria_bos_efficiency,
            iam_model=req.iam_model,
            iam_a_r=(req.iam_a_r if req.iam_model == "martin_ruiz" else None),
            curtailment_enabled=req.curtailment_enabled,
            curtailment_limit_kw=req.curtailment_limit_kw,
            input_kind="midc",
            annual_mode=True,
            expected_interval_seconds=3600,
        )
        warnings = list(
            dict.fromkeys([*source_warnings, *stats.get("data_quality_warnings", [])])
        )
        stats["data_quality_warnings"] = warnings
        set_progress(96, "Finalizing annual results")
        result = {
            "mode": "annual",
            "stats": stats,
            "ac_png": _output_url(Path(stats["ac_png"])),
            "energy_png": _output_url(Path(stats["energy_png"])),
            "monthly_png": _output_url(Path(stats["monthly_png"])),
            "excel": _output_url(Path(stats["excel"])),
            "excel_filename": _workbook_download_name(req),
            "input_plots": JOBS[job_id].get("input_plots"),
            "source_csv": _public_source_url(csv_path),
            "warnings": warnings,
            "source_quality": source_quality,
            "window": {
                "from": req.from_date,
                "to": req.to_date,
                "timezone": "MST (UTC-7)",
                "hour_convention": "right-closed, right-labeled",
                "backtrack": req.backtrack,
                "solaredge_inverter_efficiency": req.solaredge_inverter_efficiency,
                "solaredge_bos_efficiency": req.solaredge_bos_efficiency,
                "solectria_inverter_efficiency": req.solectria_inverter_efficiency,
                "solectria_bos_efficiency": req.solectria_bos_efficiency,
                "solaredge_total_efficiency": (
                    req.solaredge_inverter_efficiency * req.solaredge_bos_efficiency
                ),
                "solectria_total_efficiency": (
                    req.solectria_inverter_efficiency * req.solectria_bos_efficiency
                ),
                **_iam_metadata(req),
                "curtailment_enabled": req.curtailment_enabled,
                "curtailment_limit_kw": (
                    float(req.curtailment_limit_kw)
                    if req.curtailment_enabled
                    else None
                ),
            },
        }
        _finish_model_job(
            job_id,
            result,
            worker_id=worker_id,
            lease_token=lease_token,
        )
    except Exception as exc:
        _handle_model_failure(
            job_id,
            exc,
            worker_id=worker_id,
            lease_token=lease_token,
        )


@app.get("/")
def index() -> FileResponse:
    return FileResponse(str(HERE / "sb_energy_dashboard_modern.html"))


@app.get("/healthz")
def healthz() -> JSONResponse:
    failures: list[str] = []
    try:
        _dashboard_basic_credentials()
    except RuntimeError:
        failures.append("authentication configuration")
    try:
        if AGENT_STORE.schema_version != AGENT_STORE_SCHEMA_VERSION:
            failures.append("state schema")
    except Exception:
        logger.exception("Health check could not read durable state")
        failures.append("durable state")
    if not OUTPUT_DIR.is_dir() or not os.access(OUTPUT_DIR, os.W_OK):
        failures.append("output directory")
    worker = _WORKER_THREAD
    if _APP_STARTED and (worker is None or not worker.is_alive()):
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
        mode: (AGENT_STORE.get_current_baseline(mode) or {}).get("job_id")
        for mode in ("validation", "annual")
    }
    return JSONResponse(
        {"session_id": SERVER_SESSION_ID, "promoted_baselines": promoted}
    )


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
    with _ORCHESTRATION_LOCK:
        try:
            record = AGENT_STORE.create_job(
                kind="baseline",
                mode=mode,
                request=request_snapshot,
                job_id=job_id or uuid.uuid4().hex[:12],
                source_path=source_path,
                source_hash=source_hash,
                provenance=provenance,
                artifacts=artifacts,
                max_active_jobs=MAX_ACTIVE_MODEL_JOBS,
            )
        except QueueCapacityExceeded as exc:
            raise HTTPException(
                status_code=429,
                detail="The model queue is full. Wait for an active run to finish and retry.",
            ) from exc
        _cache_job_record(record)
        _WORKER_WAKE.set()
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
    with _ORCHESTRATION_LOCK:
        _cleanup_expired_calibration_reviews()
    review_id = uuid.uuid4().hex
    interval_seconds = int(req.interval_value) * UNIT_SECONDS[req.interval_unit]
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
        if int(row_count) > CALIBRATION_REVIEW_MAX_ROWS:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Bazefield returned {int(row_count):,} rows; calibration "
                    f"reviews are limited to {CALIBRATION_REVIEW_MAX_ROWS:,} rows."
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
        if profiled_rows > CALIBRATION_REVIEW_MAX_ROWS:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Bazefield returned {profiled_rows:,} rows; calibration "
                    f"reviews are limited to {CALIBRATION_REVIEW_MAX_ROWS:,} rows."
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
        "expires_at": (now + CALIBRATION_REVIEW_TTL).isoformat(),
        "request": _run_request_context(req),
        "source_path": str(source_path.resolve()),
        "source_hash": source_hash,
        "source_row_count": int(row_count),
        "report": report,
    }
    try:
        _save_calibration_review(record)
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

    with _ORCHESTRATION_LOCK:
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
            _save_calibration_review(record)
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
) -> JSONResponse:
    """Return one bounded page of hash-verified rows for an issue."""

    with _ORCHESTRATION_LOCK:
        record = _load_calibration_review(review_id)
        try:
            verify_source_sha256(record["source_path"], record["source_hash"])
            page = quality_issue_rows(
                record["source_path"],
                record["report"],
                issue_id,
                offset=offset,
                limit=limit,
            )
        except SourceFingerprintMismatch as exc:
            raise HTTPException(
                status_code=409,
                detail="The reviewed Bazefield source changed; retrieve it again.",
            ) from exc
        except (KeyError, OSError, TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    return JSONResponse(page)


@app.post("/api/annual-run")
def start_annual_run(req: AnnualRunRequest) -> JSONResponse:
    _validate_run_request(req)
    _validate_curtailment(req)
    _annual_dates(req)
    job = _enqueue_baseline_job("annual", _run_request_context(req))
    return JSONResponse({"job_id": job["id"]})


@app.get("/api/status/{job_id}")
def status(job_id: str) -> JSONResponse:
    job = _get_job_record(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown job id")
    return JSONResponse(_public_job(job))


@app.get("/api/agent/state")
def agent_state(mode: Literal["validation", "annual"] | None = None) -> JSONResponse:
    snapshot = AGENT_STORE.snapshot_state(mode=mode, recent_limit=20)
    proposals = [
        _public_proposal(item) for item in snapshot.get("pending_proposals", [])
    ]
    jobs_by_id: dict[str, dict[str, Any]] = {}
    for item in [
        snapshot.get("active_job"),
        *snapshot.get("queued_jobs", []),
        *snapshot.get("recent_jobs", []),
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
            "promoted_baselines": baselines,
        }
    )


def _proposal_or_404(proposal_id: str) -> dict[str, Any]:
    proposal = AGENT_STORE.get_proposal(proposal_id)
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
    with _ORCHESTRATION_LOCK:
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
    with _ORCHESTRATION_LOCK:
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
    with _ORCHESTRATION_LOCK:
        prior = _proposal_or_404(proposal_id)
        if prior["state"] != "pending":
            raise HTTPException(status_code=409, detail="Only a pending proposal can be edited")
        overrides = _explicit_overrides(req.overrides)
        target_mode = overrides.pop("mode", prior["mode"])
        validation_only = {"from_time", "to_time", "interval_value", "interval_unit"}
        if target_mode == "annual" and validation_only.intersection(overrides):
            raise HTTPException(
                status_code=422,
                detail="Times and intervals can only be changed for calibration runs.",
            )
        if "interval_value" in overrides and "interval_unit" not in overrides:
            raise HTTPException(
                status_code=422,
                detail="An interval change must explicitly include minutes, hours, or days.",
            )
        candidate_values = dict(prior["effective_request"])
        overrides = _apply_dependent_scenario_overrides(overrides, candidate_values)
        candidate_values.update(overrides)
        _, candidate = _canonical_request(target_mode, candidate_values)
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
            proposal = AGENT_STORE.create_proposal(
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
        proposal = AGENT_STORE.dismiss_proposal(proposal_id)
    except RecordNotFound as exc:
        raise HTTPException(status_code=404, detail="Unknown proposal id") from exc
    except InvalidStateTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return JSONResponse({"proposal": _public_proposal(proposal)})


@app.post("/api/jobs/{job_id}/cancel")
def cancel_model_job(job_id: str) -> JSONResponse:
    try:
        job = AGENT_STORE.cancel_job(job_id)
    except RecordNotFound as exc:
        raise HTTPException(status_code=404, detail="Unknown job id") from exc
    _cache_job_record(job)
    _WORKER_WAKE.set()
    return JSONResponse({"job": _public_job(job)})


@app.post("/api/jobs/{job_id}/retry")
def retry_model_job(job_id: str) -> JSONResponse:
    try:
        job = AGENT_STORE.retry_job(
            job_id, max_active_jobs=MAX_ACTIVE_MODEL_JOBS
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
    _WORKER_WAKE.set()
    return JSONResponse({"job": _public_job(job)})


@app.post("/api/jobs/{job_id}/delete")
def delete_model_job(job_id: str) -> JSONResponse:
    with _ORCHESTRATION_LOCK:
        try:
            job = AGENT_STORE.delete_job(job_id)
        except RecordNotFound as exc:
            raise HTTPException(status_code=404, detail="Unknown job id") from exc
        except InvalidStateTransition as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        JOBS.pop(job_id, None)
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
    candidate = _get_job_record(job_id)
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
        promoted = AGENT_STORE.promote_job(job_id)
    except InvalidStateTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    job = promoted["job"]
    return JSONResponse(
        {
            "job_id": job["id"],
            "mode": job["mode"],
            "result": job.get("result"),
            "request": job.get("request"),
            "comparison": job.get("comparison"),
            "provenance": job.get("provenance"),
            "artifacts": job.get("artifacts") or {},
        }
    )


@app.post("/api/chat")
def chat(req: ChatRequest) -> JSONResponse:
    return JSONResponse(_openai_agent_response(req))
