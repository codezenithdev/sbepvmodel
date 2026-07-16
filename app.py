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
import secrets
import threading
import traceback
import uuid
import math
import json
import os
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import bazefield_historian as historian
import midc_stac_hourly as midc
import sbe_pv_model as model

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

app = FastAPI(title="SB Energy Dashboard")
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

# In-memory job registry (single-user local tool).
JOBS: dict[str, dict] = {}
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
    return await call_next(request)


class RunRequest(BaseModel):
    from_date: str  # YYYY-MM-DD
    from_time: str = "00:00"  # HH:MM
    to_date: str
    to_time: str = "00:00"
    interval_value: int = 1
    interval_unit: str = "hours"  # minutes | hours | days
    backtrack: bool = model.BACKTRACK
    solaredge_inverter_efficiency: float = 1.0
    solaredge_bos_efficiency: float = 1.0
    solectria_inverter_efficiency: float = 1.0
    solectria_bos_efficiency: float = 1.0
    include_iam: bool = model.INCLUDE_IAM
    iam_a_r: float = model.A_R
    curtailment_enabled: bool = False
    curtailment_limit_kw: float | None = None


class AnnualRunRequest(BaseModel):
    from_date: str  # YYYY-MM-DD, inclusive fixed MST date
    to_date: str
    backtrack: bool = model.BACKTRACK
    solaredge_inverter_efficiency: float = 1.0
    solaredge_bos_efficiency: float = 1.0
    solectria_inverter_efficiency: float = 1.0
    solectria_bos_efficiency: float = 1.0
    include_iam: bool = model.INCLUDE_IAM
    iam_a_r: float = model.A_R
    curtailment_enabled: bool = False
    curtailment_limit_kw: float | None = None


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str
    job_id: str | None = None
    history: list[ChatMessage] = Field(default_factory=list)


SOLAR_AGENT_INSTRUCTIONS = """You are Solar Agent, a concise PV performance analyst for a local SB Energy dashboard.
Use the supplied dashboard run context as the source of truth for run-specific questions.
Explain model behavior in plain engineering terms: measured vs predicted energy, percent deltas, DHI source, IAM, backtracking, clipping/curtailment, and efficiency assumptions.
If no live run context is available, say the dashboard needs a completed analysis for grounded run-specific answers, while still answering general model questions from the provided model notes.
When web_search is available and you use external information, include source links in the answer.
Format answers for a narrow chat sidebar. Use concise Markdown with bold section labels and short bullets. Do not use nested bullets. Do not use tables unless the user explicitly asks for a table.
For performance-summary questions, use this order: **Performance Summary**, **SolarEdge**, **Solectria**, **Run Context**. Under each system, use the same four bullets: Measured, Predicted, Difference, Model delta.
Use signs consistently: Difference should be actual minus predicted, with + when measured is above predicted. Model delta should explain whether the model underpredicted or overpredicted.
Do not invent measurements, hidden files, credentials, or run outputs not present in the supplied context."""


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

    if req.include_iam:
        req.iam_a_r = _finite_float(req.iam_a_r, "Martin-Ruiz a_r")
        if req.iam_a_r <= 0:
            raise HTTPException(
                status_code=422, detail="Martin-Ruiz a_r must be positive."
            )


def _validate_curtailment(req: RunRequest | AnnualRunRequest) -> None:
    if not req.curtailment_enabled:
        return
    limit_kw = req.curtailment_limit_kw
    if limit_kw is None or not math.isfinite(float(limit_kw)) or limit_kw <= 0:
        raise HTTPException(
            status_code=422,
            detail="Curtailment limit must be a positive kW value.",
        )


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


def _latest_completed_job_id() -> str | None:
    for job_id, job in reversed(JOBS.items()):
        if job.get("state") == "done":
            return job_id
    return None


def _clean_chat_history(history: list[ChatMessage]) -> list[dict[str, str]]:
    cleaned: list[dict[str, str]] = []
    for item in history[-8:]:
        role = item.role if item.role in {"user", "assistant"} else "user"
        content = (item.content or "").strip()
        if not content:
            continue
        cleaned.append({"role": role, "content": content[:1400]})
    return cleaned


def _chat_run_context(job_id: str | None) -> tuple[str | None, dict]:
    resolved_job_id = job_id or _latest_completed_job_id()
    if not resolved_job_id:
        return None, {
            "state": "missing",
            "message": "No completed dashboard run is available yet.",
        }

    job = JOBS.get(resolved_job_id)
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


def _openai_chat_response(req: ChatRequest) -> tuple[str, str | None, bool]:
    if not (req.message or "").strip():
        raise HTTPException(status_code=422, detail="Message is required.")

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

    resolved_job_id, run_context = _chat_run_context(req.job_id)
    allow_web = _should_allow_web_search(req.message)
    tools = [{"type": "web_search"}] if allow_web else []
    payload = {
        "question": req.message.strip(),
        "dashboard_run_context": run_context,
        "model_knowledge": SOLAR_MODEL_KNOWLEDGE,
        "recent_chat_history": _clean_chat_history(req.history),
    }

    client = OpenAI()
    try:
        response = client.responses.create(
            model=os.getenv("OPENAI_MODEL", "gpt-5.5"),
            instructions=SOLAR_AGENT_INSTRUCTIONS,
            input=(
                "Answer the user's question using this JSON context. "
                "Prefer the dashboard context over external sources for run-specific facts.\n\n"
                + json.dumps(payload, indent=2, default=str)
            ),
            tools=tools,
            store=False,
            text={"verbosity": "low"},
        )
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"OpenAI request failed: {exc.__class__.__name__}: {exc}",
        ) from exc

    reply = _extract_response_text(response)
    if not reply:
        reply = "I could not generate a response from the model for this question."
    return reply, resolved_job_id, allow_web


def _run_job(job_id: str, req: RunRequest) -> None:
    job = JOBS[job_id]

    def set_progress(pct: int, stage: str) -> None:
        job["progress"] = int(pct)
        job["stage"] = stage

    try:
        from_iso = _iso(req.from_date, req.from_time)
        to_iso = _iso(req.to_date, req.to_time)
        interval_seconds = int(req.interval_value) * UNIT_SECONDS.get(
            req.interval_unit, 3600
        )

        csv_path = OUTPUT_DIR / f"{job_id}.csv"
        base_path = OUTPUT_DIR / job_id
        base = str(base_path)

        set_progress(5, "Pulling data from Bazefield…")
        n = historian.run_historian(
            from_time=from_iso,
            to_time=to_iso,
            interval=str(interval_seconds),
            output_csv=str(csv_path),
        )
        job["input_plots"] = _render_input_data_plots(csv_path, base_path)
        set_progress(20, f"Pulled {n} rows · running pvlib ModelChain…")

        # Map the model's 0..1 Solectria-loop callback into the 25..90 band.
        def progress_cb(frac: float, msg: str) -> None:
            set_progress(25 + int(frac * 65), msg)

        stats = model.run_model(
            input_csv=str(csv_path),
            output_base=base,
            progress_cb=progress_cb,
            backtrack=req.backtrack,
            solaredge_inverter_efficiency=req.solaredge_inverter_efficiency,
            solaredge_bos_efficiency=req.solaredge_bos_efficiency,
            solectria_inverter_efficiency=req.solectria_inverter_efficiency,
            solectria_bos_efficiency=req.solectria_bos_efficiency,
            include_iam=req.include_iam,
            iam_a_r=req.iam_a_r,
            curtailment_enabled=req.curtailment_enabled,
            curtailment_limit_kw=req.curtailment_limit_kw,
        )
        set_progress(95, "Rendering charts…")

        job["result"] = {
            "mode": "validation",
            "stats": stats,
            "ac_png": f"/outputs/{Path(stats['ac_png']).name}",
            "energy_png": f"/outputs/{Path(stats['energy_png']).name}",
            "excel": f"/outputs/{Path(stats['excel']).name}",
            "input_plots": job.get("input_plots"),
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
                "include_iam": req.include_iam,
                "iam_model": "martin_ruiz" if req.include_iam else "physical",
                "iam_a_r": float(req.iam_a_r),
                "curtailment_enabled": req.curtailment_enabled,
                "curtailment_limit_kw": (
                    float(req.curtailment_limit_kw)
                    if req.curtailment_enabled
                    else None
                ),
            },
        }
        set_progress(100, "Done")
        job["state"] = "done"
    except Exception as exc:  # surface a friendly message to the UI
        job["state"] = "error"
        job["error"] = str(exc) or exc.__class__.__name__
        job["traceback"] = traceback.format_exc()


def _run_annual_job(job_id: str, req: AnnualRunRequest) -> None:
    job = JOBS[job_id]

    def set_progress(pct: int, stage: str) -> None:
        job["progress"] = int(pct)
        job["stage"] = stage

    try:
        start_date, end_date = _annual_dates(req)
        source_path = OUTPUT_DIR / f"{job_id}_midc_hourly.csv"
        base_path = OUTPUT_DIR / job_id

        def download_progress(frac: float, msg: str) -> None:
            set_progress(5 + int(frac * 20), msg)

        set_progress(5, "Downloading MIDC minute data")
        source = midc.fetch_hourly_data(
            start_date,
            end_date,
            progress_cb=download_progress,
        )
        set_progress(27, "Saving exact MIDC hourly source")
        midc.write_csv_atomically(source.hourly, source_path)
        set_progress(28, "Rendering annual irradiance inputs")
        job["input_plots"] = _render_midc_input_data_plots(source_path, base_path)

        def model_progress(frac: float, msg: str) -> None:
            set_progress(30 + int(frac * 60), msg)

        set_progress(30, "Running annual PV model")
        stats = model.run_model(
            input_csv=str(source_path),
            output_base=str(base_path),
            progress_cb=model_progress,
            backtrack=req.backtrack,
            solaredge_inverter_efficiency=req.solaredge_inverter_efficiency,
            solaredge_bos_efficiency=req.solaredge_bos_efficiency,
            solectria_inverter_efficiency=req.solectria_inverter_efficiency,
            solectria_bos_efficiency=req.solectria_bos_efficiency,
            include_iam=req.include_iam,
            iam_a_r=req.iam_a_r,
            curtailment_enabled=req.curtailment_enabled,
            curtailment_limit_kw=req.curtailment_limit_kw,
            input_kind="midc",
            annual_mode=True,
        )

        warnings = list(dict.fromkeys(
            [*source.warnings, *stats.get("data_quality_warnings", [])]
        ))
        stats["data_quality_warnings"] = warnings
        set_progress(96, "Finalizing annual results")

        job["result"] = {
            "mode": "annual",
            "stats": stats,
            "ac_png": f"/outputs/{Path(stats['ac_png']).name}",
            "energy_png": f"/outputs/{Path(stats['energy_png']).name}",
            "monthly_png": f"/outputs/{Path(stats['monthly_png']).name}",
            "excel": f"/outputs/{Path(stats['excel']).name}",
            "input_plots": job.get("input_plots"),
            "source_csv": f"/outputs/{source_path.name}",
            "warnings": warnings,
            "source_quality": {
                "raw_rows": source.raw_rows,
                "hourly_rows": int(len(source.hourly)),
                "chunk_count": source.chunk_count,
                "missing_value_count": source.missing_value_count,
                "affected_hour_count": source.affected_hour_count,
            },
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
                "include_iam": req.include_iam,
                "iam_model": "martin_ruiz" if req.include_iam else "physical",
                "iam_a_r": float(req.iam_a_r),
                "curtailment_enabled": req.curtailment_enabled,
                "curtailment_limit_kw": (
                    float(req.curtailment_limit_kw)
                    if req.curtailment_enabled
                    else None
                ),
            },
        }
        set_progress(100, "Done")
        job["state"] = "done"
    except Exception as exc:
        job["state"] = "error"
        job["error"] = str(exc) or exc.__class__.__name__
        job["traceback"] = traceback.format_exc()


@app.get("/")
def index() -> FileResponse:
    return FileResponse(str(HERE / "sb_energy_dashboard_modern.html"))


@app.get("/healthz")
def healthz() -> JSONResponse:
    return JSONResponse({"status": "ok"})


@app.get("/api/session")
def session() -> JSONResponse:
    return JSONResponse({"session_id": SERVER_SESSION_ID})


@app.post("/api/run")
def start_run(req: RunRequest) -> JSONResponse:
    _validate_run_request(req)
    _validate_curtailment(req)

    job_id = uuid.uuid4().hex[:12]
    JOBS[job_id] = {
        "mode": "validation",
        "state": "running",
        "progress": 0,
        "stage": "Queued…",
        "request": _model_dump(req),
    }
    threading.Thread(target=_run_job, args=(job_id, req), daemon=True).start()
    return JSONResponse({"job_id": job_id})


@app.post("/api/annual-run")
def start_annual_run(req: AnnualRunRequest) -> JSONResponse:
    _validate_run_request(req)
    _validate_curtailment(req)
    _annual_dates(req)

    job_id = uuid.uuid4().hex[:12]
    JOBS[job_id] = {
        "mode": "annual",
        "state": "running",
        "progress": 0,
        "stage": "Queued",
        "request": _model_dump(req),
    }
    threading.Thread(target=_run_annual_job, args=(job_id, req), daemon=True).start()
    return JSONResponse({"job_id": job_id})


@app.get("/api/status/{job_id}")
def status(job_id: str) -> JSONResponse:
    job = JOBS.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown job id")
    out = {
        "state": job["state"],
        "progress": job.get("progress", 0),
        "stage": job.get("stage", ""),
    }
    if "input_plots" in job:
        out["input_plots"] = job["input_plots"]
    if job["state"] == "done":
        out["result"] = job["result"]
    elif job["state"] == "error":
        out["error"] = job.get("error", "Unknown error")
    return JSONResponse(out)


@app.post("/api/chat")
def chat(req: ChatRequest) -> JSONResponse:
    reply, resolved_job_id, web_search_enabled = _openai_chat_response(req)
    return JSONResponse(
        {
            "reply": reply,
            "job_id": resolved_job_id,
            "web_search_enabled": web_search_enabled,
        }
    )
