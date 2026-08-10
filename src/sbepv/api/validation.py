"""Request validation shared by the run, annual, and calibration endpoints.

Every failure raises ``HTTPException(422)`` with a message written for the
dashboard user. Several validators also normalise the request in place -- they
coerce efficiencies to floats and clear a curtailment limit that is not in use --
so callers must validate before reading those fields.
"""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone

from fastapi import HTTPException
from pydantic import BaseModel

from sbepv import model
from sbepv.api import config
from sbepv.api.config import (
    ANNUAL_RUN_MAX_DAYS,
    CALIBRATION_REVIEW_MAX_RANGE,
    UNIT_SECONDS,
    VALIDATION_RUN_MAX_RANGE,
    VALIDATION_RUN_MAX_ROWS,
)
from sbepv.api.schemas import AnnualRunRequest, RunRequest
from sbepv.api.timewindows import _iso


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


def _annual_interval_seconds(req: AnnualRunRequest) -> int:
    """Return a model-safe whole-hour annual interval."""
    try:
        interval_value = int(req.interval_value)
        seconds = interval_value * UNIT_SECONDS[req.interval_unit]
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="Invalid annual interval.") from exc
    if interval_value < 1:
        raise HTTPException(
            status_code=422, detail="Interval value must be at least 1."
        )
    if seconds < 3_600 or seconds > 86_400 or seconds % 3_600:
        raise HTTPException(
            status_code=422,
            detail=(
                "Annual Simulation intervals must be whole hours between "
                "1 hour and 1 day."
            ),
        )
    interval_hours = seconds // 3_600
    if 24 % interval_hours:
        raise HTTPException(
            status_code=422,
            detail=(
                "Annual Simulation intervals must divide evenly into a "
                "24-hour day."
            ),
        )
    return seconds


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

    if int(req.interval_value) < 1:
        raise HTTPException(
            status_code=422, detail="Interval value must be at least 1."
        )
    if isinstance(req, AnnualRunRequest):
        _annual_interval_seconds(req)

    if isinstance(req, RunRequest):
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
        max_rows=config.CALIBRATION_REVIEW_MAX_ROWS,
        label="Calibration reviews",
    )
