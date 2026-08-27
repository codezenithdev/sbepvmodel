"""Environment-derived settings and filesystem locations for the API.

Importing this module has side effects, by design and in this order: it locates
the repository root, loads ``.env`` from it, then creates the output directories
that the rest of the application assumes exist. Every other API module imports
this one, so that sequence runs exactly once and before anything reads a setting.

Tests override values here with ``patch.object(config, "OUTPUT_DIR", ...)``.
Callers must therefore reach settings through the module (``config.OUTPUT_DIR``)
rather than binding them with ``from .config import OUTPUT_DIR`` -- a value
import captures the original and silently ignores the patch.
"""

from __future__ import annotations

import logging
import math
import os
import uuid
from datetime import timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from sbepv.ingest import bazefield as historian
from sbepv.paths import discover_project_root

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


PROJECT_ROOT = discover_project_root(Path(__file__))
historian.load_dotenv(str(PROJECT_ROOT / ".env"))


def _configured_output_dir() -> Path:
    configured = os.getenv("PV_DASHBOARD_OUTPUT_DIR")
    if not configured:
        return PROJECT_ROOT / "outputs"
    path = Path(configured).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path


OUTPUT_DIR = _configured_output_dir()
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
CALIBRATION_REVIEW_DIR = OUTPUT_DIR / ".calibration_reviews"
CALIBRATION_REVIEW_DIR.mkdir(parents=True, exist_ok=True)
ANNUAL_SOURCE_ARTIFACT_DIR = OUTPUT_DIR / ".annual_sources"
ANNUAL_SOURCE_ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
PRIVATE_OUTPUT_DIRS = (
    (OUTPUT_DIR / ".agent_state").resolve(),
    CALIBRATION_REVIEW_DIR.resolve(),
    ANNUAL_SOURCE_ARTIFACT_DIR.resolve(),
    (OUTPUT_DIR / ".technoeconomic_attempts").resolve(),
)
PUBLIC_OUTPUT_SUFFIXES = frozenset({".csv", ".png", ".xlsx"})
CALIBRATION_REVIEW_TTL = timedelta(hours=24)
CALIBRATION_REVIEW_MAX_RANGE = timedelta(days=366)
CALIBRATION_REVIEW_MAX_ROWS = 200_000
VALIDATION_RUN_MAX_RANGE = CALIBRATION_REVIEW_MAX_RANGE
VALIDATION_RUN_MAX_ROWS = CALIBRATION_REVIEW_MAX_ROWS
ANNUAL_RUN_MAX_DAYS = 3 * 366
# Excel worksheets allow 1,048,576 rows including the header. Annual runs emit
# one time-series row per interval, so reject requests that cannot be exported.
ANNUAL_RUN_MAX_ROWS = 1_048_575
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
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.6-sol").strip() or "gpt-5.6-sol"
OPENAI_REASONING_EFFORT = os.getenv("OPENAI_REASONING_EFFORT", "high").strip().lower() or "high"
OPENAI_REASONING_EFFORTS = frozenset({
    "none",
    "low",
    "medium",
    "high",
    "xhigh",
    "max",
})
if OPENAI_REASONING_EFFORT not in OPENAI_REASONING_EFFORTS:
    logger.warning("Ignoring invalid OPENAI_REASONING_EFFORT value")
    OPENAI_REASONING_EFFORT = "low"

SERVER_SESSION_ID = uuid.uuid4().hex

UNIT_SECONDS = {"minutes": 60, "hours": 3600, "days": 86400}
AUTH_REALM = "SB Energy Dashboard"

LOCAL_TZ = ZoneInfo("America/Denver")  # matches model.TIMEZONE
ANNUAL_TZ = ZoneInfo("Etc/GMT+7")  # MIDC source dates are fixed MST (UTC-7)
UTC_TZ = ZoneInfo("UTC")
