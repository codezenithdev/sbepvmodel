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
import logging
import secrets
import threading
import traceback
import uuid
import math
import json
import os
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
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
from agent_store import (
    AgentStore,
    AgentStoreError,
    InvalidStateTransition,
    RecordNotFound,
)
from scenario_reporting import (
    SourceFingerprintMismatch,
    generate_comparison_artifacts,
    sha256_file,
    verify_source_sha256,
)

logger = logging.getLogger(__name__)

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

# ``JOBS`` remains as a live compatibility/read-through cache for existing local
# integrations. SQLite is the authoritative registry and survives restarts.
JOBS: dict[str, dict] = {}
AGENT_STORE = AgentStore(OUTPUT_DIR / ".agent_state" / "solar_agent.sqlite3")
_WORKER_STOP = threading.Event()
_WORKER_WAKE = threading.Event()
_WORKER_LOCK = threading.Lock()
_ORCHESTRATION_LOCK = threading.RLock()
_WORKER_THREAD: threading.Thread | None = None


@asynccontextmanager
async def _app_lifespan(_app: FastAPI):
    interrupted = AGENT_STORE.mark_stale_running_jobs_interrupted()
    if interrupted:
        logger.warning("Marked %s stale model job(s) interrupted", interrupted)
    _start_model_worker()
    try:
        yield
    finally:
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
app.mount("/outputs", StaticFiles(directory=str(OUTPUT_DIR)), name="outputs")

SERVER_SESSION_ID = uuid.uuid4().hex

UNIT_SECONDS = {"minutes": 60, "hours": 3600, "days": 86400}
AUTH_REALM = "SB Energy Dashboard"


def _dashboard_basic_credentials() -> tuple[str, str] | None:
    username = os.getenv("DASHBOARD_BASIC_USER", "").strip()
    password = os.getenv("DASHBOARD_BASIC_PASSWORD", "")
    if not username or not password:
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
    if not _basic_auth_is_valid(request.headers.get("authorization")):
        return _auth_required_response()
    if request.url.path.startswith("/outputs/.agent_state/"):
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
Treat visible_iam_selection as the authoritative IAM state for the visible dashboard form. Physical IAM is an active IAM selection, even though iam_a_r is null because that coefficient applies only to Martin-Ruiz. Never describe Physical IAM as disabled, off, or not selected.
If no live run context is available, say the dashboard needs a completed analysis for grounded run-specific answers, while still answering general model questions from the provided model notes.
When the user explicitly asks to run, test, simulate, compare, or perform a what-if with dashboard settings, call propose_model_scenario exactly once. Put only explicitly requested changes in the tool arguments and use null for every unchanged field. Do not call the tool for conceptual questions.
Bazefield is the validation data source. If the user explicitly asks to use Bazefield, select validation mode even when the annual view is active. Validation end timestamps are exclusive: interpret a whole-day range such as June 1-7 as June 1 00:00 through June 8 00:00 so all of June 7 is included.
IAM is a method selection, not a generic scalar. If the user gives a numeric IAM value without explicitly naming Martin-Ruiz or a_r, ask which value they mean and do not call the tool.
Never calculate scenario deltas yourself. The application returns deterministic comparison metrics after the model run; explain those values without changing them. A multi-field scenario is a combined scenario and must not be attributed to one field. A cross-run comparison uses different input data and must not be described causally.
After explaining a completed deterministic comparison, suggest one or two useful follow-up experiments, but never request or launch them unless the user explicitly asks in a later turn.
The application, not you, decides whether a run requires confirmation. Never claim a run started unless the tool output says it did.
When the tool output status is started, explicitly say the run was queued, describe whether it will reuse verified source data or pull fresh Bazefield data, and do not ask for confirmation. Ask for confirmation only when the tool output status is confirmation_required or baseline_required.
When web_search is available and you use external information, include source links in the answer.
Format answers for a narrow chat sidebar. Use concise Markdown with bold section labels and short bullets. Do not use nested bullets. Do not use tables unless the user explicitly asks for a table.
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
        "approves, executes, and compares the run. A changed validation window is "
        "automatically fetched from Bazefield and compared with the selected baseline."
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
        "Validation runs return measured-versus-predicted summary stats, AC power and "
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
            raise HTTPException(
                status_code=422,
                detail="Validation dates and times must use YYYY-MM-DD and HH:MM.",
            ) from exc
        if start >= end:
            raise HTTPException(
                status_code=422,
                detail="Validation start date/time must be before end date/time.",
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
    utc = naive.replace(tzinfo=LOCAL_TZ).astimezone(UTC_TZ)
    return utc.strftime("%Y-%m-%dT%H:%M:%S")


def _output_url(path: Path) -> str:
    return f"/outputs/{path.name}"


def _render_input_data_plots(csv_path: Path, output_base: Path) -> dict[str, str]:
    """Render early historian-input plots before the slower PV model runs."""
    import pandas as pd
    import matplotlib.pyplot as plt

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


def _update_job(job_id: str, **fields: Any) -> dict[str, Any]:
    """Update SQLite when present and always keep the compatibility cache fresh."""
    cached = JOBS.setdefault(job_id, {})
    cached.update(fields)
    artifacts = fields.get("artifacts")
    if isinstance(artifacts, dict) and artifacts.get("input_plots"):
        cached["input_plots"] = artifacts["input_plots"]
    try:
        if AGENT_STORE.get_job(job_id) is not None:
            record = AGENT_STORE.update_job(job_id, **fields)
            _cache_job_record(record)
            return record
    except AgentStoreError:
        logger.exception("Could not update durable job %s", job_id)
        raise
    return {"id": job_id, **cached}


def _job_cancel_requested(job_id: str) -> bool:
    record = _get_job_record(job_id)
    if record is None:
        return False
    if record.get("cancel_requested"):
        return True
    return bool(JOBS.get(job_id, {}).get("cancel_requested"))


class _JobCancelled(RuntimeError):
    pass


def _check_job_cancelled(job_id: str) -> None:
    if _job_cancel_requested(job_id):
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
        if canonical in SCENARIO_OVERRIDE_FIELDS and canonical != "mode":
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
    if "iam" not in text or not re.search(r"\b\d+(?:\.\d+)?\b", text):
        return False
    explicit = ("martin", "ruiz", "a_r", "a-r", "coefficient", "physical")
    return not any(marker in text for marker in explicit)


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
    except (OSError, SourceFingerprintMismatch):
        logger.warning("Baseline source fingerprint is unavailable or changed")
        return None, None
    return str(source_path), str(source_hash)


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
            "Fresh Bazefield data will be fetched; the comparison will be non-like-for-like"
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
        "Same-input validation can reuse the baseline source fingerprint"
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


def _create_candidate_proposal(
    *,
    mode: Literal["validation", "annual"],
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    changes: list[dict[str, Any]],
    supersedes_id: str | None = None,
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
    return AGENT_STORE.create_proposal(
        mode=mode,
        effective_request=candidate,
        changes=changes,
        baseline_id=str(baseline["id"]),
        comparison_kind=comparison_kind,
        confirmation_required=confirmation_required,
        confirmation_reason=confirmation_reason,
        confirmation_metadata={
            "job_kind": "candidate",
            "source_reusable": reusable,
            "baseline_source_path": source_path if reusable else None,
            "baseline_source_hash": source_hash if reusable else None,
        },
        supersedes_id=supersedes_id,
    )


def _confirm_durable_proposal(
    proposal: dict[str, Any], *, automatic: bool = False
) -> dict[str, Any]:
    metadata = proposal.get("confirmation_metadata") or {}
    source_path: str | None = None
    source_hash: str | None = None
    if proposal.get("baseline_id") and proposal.get("comparison_kind") == "same_input":
        baseline = _get_job_record(str(proposal["baseline_id"]))
        source_path, source_hash = _verified_baseline_source(baseline)
        if not source_path or not source_hash:
            raise HTTPException(
                status_code=409,
                detail="The baseline source fingerprint is no longer valid. Confirm a fresh baseline run.",
            )
    job = AGENT_STORE.confirm_proposal(
        str(proposal["id"]),
        job_kind=str(metadata.get("job_kind", "candidate")),
        confirmation_metadata={"automatic": automatic},
        source_path=source_path,
        source_hash=source_hash,
    )
    _cache_job_record(job)
    _WORKER_WAKE.set()
    return job


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
            detail="Times and intervals can only be changed for validation runs.",
        )
    if "interval_value" in overrides and "interval_unit" not in overrides:
        raise HTTPException(
            status_code=422,
            detail="An interval change must explicitly include minutes, hours, or days.",
        )

    with _ORCHESTRATION_LOCK:
        baseline = (
            _selected_baseline(req.active_mode)
            if target_mode != req.active_mode
            else _selected_baseline(target_mode)
        ) or _selected_baseline(target_mode)
        if baseline is None:
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
                started_message = (
                    "The validation scenario was queued automatically. It will pull fresh "
                    "data from Bazefield and run a non-like-for-like comparison against "
                    "the selected baseline."
                )
            else:
                started_message = (
                    "The verified same-input validation scenario was queued automatically."
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


def _clean_chat_history(history: list[ChatMessage]) -> list[dict[str, str]]:
    cleaned: list[dict[str, str]] = []
    for item in history[-8:]:
        role = item.role if item.role in {"user", "assistant"} else "user"
        content = (item.content or "").strip()
        if not content:
            continue
        cleaned.append({"role": role, "content": content[:1400]})
    return cleaned


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
        context["result"] = job.get("result", {})
        if job.get("comparison"):
            context["comparison"] = job["comparison"]
        if job.get("provenance"):
            context["provenance"] = job["provenance"]
        if job.get("artifacts"):
            context["artifacts"] = job["artifacts"]
    elif job.get("state") == "error":
        context["error"] = job.get("error", "Unknown error")
    return resolved_job_id, context


def _should_allow_web_search(message: str) -> bool:
    text = (message or "").lower()
    triggers = (
        "web",
        "internet",
        "online",
        "source",
        "sources",
        "citation",
        "citations",
        "reference",
        "references",
        "latest",
        "current",
        "today",
        "recent",
        "forecast",
        "weather",
        "nrel",
        "pvlib",
        "pvmismatch",
        "prediction",
        "predict",
        "external",
        "research",
    )
    return any(trigger in text for trigger in triggers)


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
    return [
        item
        for item in (getattr(response, "output", None) or [])
        if _response_item_value(item, "type") == "function_call"
        and _response_item_value(item, "name") == "propose_model_scenario"
    ]


def _openai_agent_response(req: ChatRequest) -> dict[str, Any]:
    if not (req.message or "").strip():
        raise HTTPException(status_code=422, detail="Message is required.")
    if len(req.message) > 4000:
        raise HTTPException(
            status_code=422, detail="Message must be 4,000 characters or fewer."
        )

    resolved_job_id, run_context = _chat_run_context(req.job_id, req.active_mode)
    if _ambiguous_numeric_iam(req.message):
        return {
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
        [SCENARIO_TOOL] if req.allow_scenario_actions else []
    )
    if allow_web:
        tools.append({"type": "web_search"})
    payload = {
        "question": req.message.strip(),
        "dashboard_run_context": run_context,
        "active_mode": req.active_mode,
        "visible_dashboard_configuration": req.current_config,
        "visible_iam_selection": _visible_iam_selection(req.current_config),
        "model_knowledge": SOLAR_MODEL_KNOWLEDGE,
        "recent_chat_history": _clean_chat_history(req.history),
    }
    user_input = {
        "role": "user",
        "content": (
            "Answer the user's question using this JSON context. Prefer dashboard "
            "context over external sources for run-specific facts.\n\n"
            + json.dumps(payload, indent=2, default=str)
        ),
    }

    client = OpenAI()
    try:
        response = client.responses.create(
            model=os.getenv("OPENAI_MODEL", "gpt-5.5"),
            instructions=SOLAR_AGENT_INSTRUCTIONS,
            input=[user_input],
            tools=tools,
            store=False,
            text={"verbosity": "low"},
        )
    except Exception as exc:
        logger.error("OpenAI request failed: %s", exc.__class__.__name__)
        raise HTTPException(
            status_code=502,
            detail="Solar Agent is temporarily unavailable. Please retry.",
        ) from exc

    web_sources = _extract_web_sources(response)
    action: dict[str, Any] | None = None
    tool_calls = _scenario_tool_calls(response) if req.allow_scenario_actions else []
    if len(tool_calls) > 1:
        raise HTTPException(
            status_code=502,
            detail="Solar Agent requested more than one scenario. Please retry.",
        )
    if tool_calls:
        tool_call = tool_calls[0]
        try:
            arguments = json.loads(_response_item_value(tool_call, "arguments", "{}"))
            if not isinstance(arguments, dict):
                raise ValueError("Tool arguments must be an object")
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

        followup_input: list[Any] = [user_input]
        followup_input.extend(getattr(response, "output", None) or [])
        followup_input.append(
            {
                "type": "function_call_output",
                "call_id": _response_item_value(tool_call, "call_id"),
                "output": json.dumps(tool_result, default=str),
            }
        )
        try:
            response = client.responses.create(
                model=os.getenv("OPENAI_MODEL", "gpt-5.5"),
                instructions=SOLAR_AGENT_INSTRUCTIONS,
                input=followup_input,
                store=False,
                text={"verbosity": "low"},
            )
            web_sources.extend(
                source
                for source in _extract_web_sources(response)
                if source not in web_sources
            )
        except Exception as exc:
            logger.error("OpenAI tool follow-up failed: %s", exc.__class__.__name__)
            # The deterministic action remains valid even if the explanatory turn fails.
            response = type(
                "FallbackResponse",
                (),
                {"output_text": tool_result.get("message", "Scenario request prepared.")},
            )()

    reply = _extract_response_text(response)
    if not reply:
        reply = "I could not generate a response from the model for this question."
    return {
        "reply": reply,
        "job_id": resolved_job_id,
        "web_search_enabled": allow_web,
        "web_sources": web_sources,
        "action": action,
    }


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


def _model_worker_loop() -> None:
    while not _WORKER_STOP.is_set():
        try:
            record = AGENT_STORE.claim_next_queued_job()
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
                )
            else:
                req = RunRequest(**record["request"])
                _validate_run_request(req)
                _validate_curtailment(req)
                _run_job(
                    job_id,
                    req,
                    source_path=record.get("source_path"),
                    expected_source_hash=record.get("source_hash"),
                )
        except Exception:
            logger.exception("Unhandled model worker failure for %s", job_id)
            current = _get_job_record(job_id)
            if current and current.get("state") == "running":
                _update_job(
                    job_id,
                    state="error",
                    stage="Failed",
                    error="The model run failed. Review server logs and retry.",
                )


def _artifact_file(result: dict[str, Any], key: str) -> Path:
    stats = result.get("stats") or {}
    raw = stats.get(key) or result.get(key)
    if not raw:
        raise ValueError(f"Model result is missing the {key} artifact")
    raw_path = Path(str(raw))
    if raw_path.is_absolute():
        return raw_path
    return OUTPUT_DIR / raw_path.name


def _finish_model_job(job_id: str, result: dict[str, Any]) -> None:
    record = _get_job_record(job_id) or {"id": job_id, **JOBS.get(job_id, {})}
    artifacts = dict(record.get("artifacts") or {})
    if JOBS.get(job_id, {}).get("input_plots"):
        artifacts["input_plots"] = JOBS[job_id]["input_plots"]
    artifacts.setdefault(
        "model_workbook",
        {"path": str(_artifact_file(result, "excel")), "url": result.get("excel")},
    )

    comparison = None
    provenance = record.get("provenance")
    baseline_id = record.get("baseline_id")
    if baseline_id:
        _update_job(job_id, progress=97, stage="Calculating trusted comparison")
        _check_job_cancelled(job_id)
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
            OUTPUT_DIR / job_id,
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
        provenance = generated["provenance"]
        artifacts.update(generated["artifacts"])

    _check_job_cancelled(job_id)
    _update_job(
        job_id,
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
    if completed and completed.get("kind") in {"baseline", "manual"}:
        try:
            AGENT_STORE.promote_job(job_id)
        except AgentStoreError:
            logger.exception("Completed baseline %s could not be promoted", job_id)


def _handle_model_failure(job_id: str, exc: Exception) -> None:
    if isinstance(exc, _JobCancelled) or _job_cancel_requested(job_id):
        current = _get_job_record(job_id)
        if current and current.get("state") == "running":
            _update_job(job_id, state="cancelled", stage="Cancelled", error=None)
        return
    logger.error("Model job %s failed\n%s", job_id, traceback.format_exc())
    JOBS.setdefault(job_id, {})["traceback"] = traceback.format_exc()
    current = _get_job_record(job_id)
    if current and current.get("state") == "running":
        _update_job(
            job_id,
            state="error",
            stage="Failed",
            error="The model run failed. Review server logs and retry.",
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
) -> None:
    JOBS.setdefault(job_id, {"mode": "validation", "state": "running"})

    def set_progress(pct: int, stage: str) -> None:
        _check_job_cancelled(job_id)
        _update_job(job_id, progress=int(pct), stage=stage)

    try:
        from_iso = _iso(req.from_date, req.from_time)
        to_iso = _iso(req.to_date, req.to_time)
        interval_seconds = int(req.interval_value) * UNIT_SECONDS[req.interval_unit]
        csv_path = (
            Path(source_path)
            if source_path and expected_source_hash
            else OUTPUT_DIR / f"{job_id}.csv"
        )
        base_path = OUTPUT_DIR / job_id

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
            _check_job_cancelled(job_id)
            source_hash = sha256_file(csv_path)
        _update_job(
            job_id,
            source_path=str(csv_path.resolve()),
            source_hash=source_hash,
        )
        _check_job_cancelled(job_id)
        input_plots = _render_input_data_plots(csv_path, base_path)
        existing_artifacts = (_get_job_record(job_id) or {}).get("artifacts") or {}
        _update_job(
            job_id,
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
        )
        set_progress(95, "Finalizing model artifacts")
        result = {
            "mode": "validation",
            "stats": stats,
            "ac_png": _output_url(Path(stats["ac_png"])),
            "energy_png": _output_url(Path(stats["energy_png"])),
            "excel": _output_url(Path(stats["excel"])),
            "input_plots": JOBS[job_id].get("input_plots"),
            "source_csv": _output_url(csv_path),
            "window": {
                "from": from_iso,
                "to": to_iso,
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
            },
        }
        _finish_model_job(job_id, result)
    except Exception as exc:
        _handle_model_failure(job_id, exc)


def _run_annual_job(
    job_id: str,
    req: AnnualRunRequest,
    *,
    source_path: str | Path | None = None,
    expected_source_hash: str | None = None,
) -> None:
    JOBS.setdefault(job_id, {"mode": "annual", "state": "running"})

    def set_progress(pct: int, stage: str) -> None:
        _check_job_cancelled(job_id)
        _update_job(job_id, progress=int(pct), stage=stage)

    try:
        start_date, end_date = _annual_dates(req)
        csv_path = (
            Path(source_path)
            if source_path and expected_source_hash
            else OUTPUT_DIR / f"{job_id}_midc_hourly.csv"
        )
        base_path = OUTPUT_DIR / job_id
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
            _check_job_cancelled(job_id)
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
            source_path=str(csv_path.resolve()),
            source_hash=source_hash,
        )
        set_progress(28, "Rendering annual irradiance inputs")
        input_plots = _render_midc_input_data_plots(csv_path, base_path)
        existing_artifacts = (_get_job_record(job_id) or {}).get("artifacts") or {}
        _update_job(
            job_id,
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
            "input_plots": JOBS[job_id].get("input_plots"),
            "source_csv": _output_url(csv_path),
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
        _finish_model_job(job_id, result)
    except Exception as exc:
        _handle_model_failure(job_id, exc)


@app.get("/")
def index() -> FileResponse:
    return FileResponse(str(HERE / "sb_energy_dashboard_modern.html"))


@app.get("/healthz")
def healthz() -> JSONResponse:
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
) -> dict[str, Any]:
    with _ORCHESTRATION_LOCK:
        record = AGENT_STORE.create_job(
            kind="baseline",
            mode=mode,
            request=request_snapshot,
            job_id=uuid.uuid4().hex[:12],
        )
        _cache_job_record(record)
        _WORKER_WAKE.set()
        return record


@app.post("/api/run")
def start_run(req: RunRequest) -> JSONResponse:
    _validate_run_request(req)
    _validate_curtailment(req)
    job = _enqueue_baseline_job("validation", _run_request_context(req))
    return JSONResponse({"job_id": job["id"]})


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


@app.post("/api/agent/proposals/{proposal_id}/confirm")
def confirm_agent_proposal(proposal_id: str) -> JSONResponse:
    with _ORCHESTRATION_LOCK:
        proposal = _proposal_or_404(proposal_id)
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
                detail="Times and intervals can only be changed for validation runs.",
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
        job = AGENT_STORE.retry_job(job_id)
    except RecordNotFound as exc:
        raise HTTPException(status_code=404, detail="Unknown job id") from exc
    except InvalidStateTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    _cache_job_record(job)
    _WORKER_WAKE.set()
    return JSONResponse({"job": _public_job(job)})


@app.post("/api/jobs/{job_id}/promote")
def promote_model_job(job_id: str) -> JSONResponse:
    try:
        promoted = AGENT_STORE.promote_job(job_id)
    except RecordNotFound as exc:
        raise HTTPException(status_code=404, detail="Unknown job id") from exc
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
