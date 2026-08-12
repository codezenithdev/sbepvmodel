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
from sbepv.api.schemas import AnnualRunRequest, RunRequest
from sbepv.api.timewindows import _iso
from sbepv.ingest import midc


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
    """Return a model-safe annual interval at minute or whole-hour resolution."""
    try:
        interval_value = int(req.interval_value)
        seconds = interval_value * config.UNIT_SECONDS[req.interval_unit]
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="Invalid annual interval.") from exc
    if interval_value < 1:
        raise HTTPException(
            status_code=422, detail="Interval value must be at least 1."
        )
    supported_hours = frozenset({1, 2, 3, 4, 6, 8, 12, 24})
    if req.interval_unit == "minutes" and (
        interval_value > 60 or 1_440 % interval_value
    ):
        raise HTTPException(
            status_code=422,
            detail=(
                "Annual Simulation minute intervals must be from 1 to 60 "
                "minutes and divide evenly into a 24-hour day."
            ),
        )
    if req.interval_unit == "hours" and interval_value not in supported_hours:
        raise HTTPException(
            status_code=422,
            detail=(
                "Annual Simulation hour intervals must be one of "
                "1, 2, 3, 4, 6, 8, 12, or 24 hours."
            ),
        )
    if req.interval_unit == "days" and interval_value != 1:
        raise HTTPException(
            status_code=422,
            detail="Annual Simulation supports a maximum interval of 1 day.",
        )
    if seconds < 60 or seconds > 86_400 or seconds % 60 or 86_400 % seconds:
        raise HTTPException(
            status_code=422,
            detail=(
                "Annual Simulation intervals must be supported whole-minute "
                "divisors of a 24-hour day."
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
        interval_seconds = (
            int(req.interval_value) * config.UNIT_SECONDS[req.interval_unit]
        )
        _validate_requested_window(
            start=start,
            end=end,
            interval_seconds=interval_seconds,
            max_range=config.VALIDATION_RUN_MAX_RANGE,
            max_rows=config.VALIDATION_RUN_MAX_ROWS,
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


def _annual_period_record(
    year: int,
    start_date: date,
    end_date: date,
) -> dict[str, object]:
    calendar_start = date(year, 1, 1)
    calendar_end = date(year, 12, 31)
    complete = start_date == calendar_start and end_date == calendar_end
    if complete:
        coverage_status = "complete"
    elif year == midc.FIRST_AVAILABLE_DATE.year and start_date == midc.FIRST_AVAILABLE_DATE:
        coverage_status = "partial_start"
    elif start_date == calendar_start and end_date < calendar_end:
        coverage_status = "year_to_date"
    else:
        coverage_status = "custom_range"
    return {
        "year": year,
        "period_start": start_date.isoformat(),
        "period_end": end_date.isoformat(),
        "coverage_status": coverage_status,
        "complete_calendar_year": complete,
        "cdf_eligible": complete,
        "available_days": (end_date - start_date).days + 1,
        "calendar_days": (calendar_end - calendar_start).days + 1,
    }


def _legacy_annual_periods(start_date: date, end_date: date) -> list[dict[str, object]]:
    periods: list[dict[str, object]] = []
    for year in range(start_date.year, end_date.year + 1):
        period_start = max(start_date, date(year, 1, 1))
        period_end = min(end_date, date(year, 12, 31))
        periods.append(_annual_period_record(year, period_start, period_end))
    return periods


def _validate_annual_row_count(
    req: AnnualRunRequest,
    periods: list[dict[str, object]],
) -> None:
    """Reject annual requests whose complete time series cannot fit in Excel."""

    interval_seconds = _annual_interval_seconds(req)
    expected_rows = sum(
        int(period["available_days"]) * (86_400 // interval_seconds)
        for period in periods
    )
    if expected_rows > config.ANNUAL_RUN_MAX_ROWS:
        raise HTTPException(
            status_code=422,
            detail=(
                "The selected years and interval would produce approximately "
                f"{expected_rows:,} rows; annual runs are limited to "
                f"{config.ANNUAL_RUN_MAX_ROWS:,} rows so the complete time "
                "series remains exportable to Excel. Select fewer years or a "
                "longer interval."
            ),
        )


def _annual_periods(
    req: AnnualRunRequest,
    *,
    today: date | None = None,
    allow_resolved_partial: bool = False,
) -> list[dict[str, object]]:
    """Return immutable model periods for a legacy range or selected years.

    MIDC publishes complete STAC daily files through yesterday.  A years-only
    submission is therefore resolved once, at request-validation time, and the
    resulting from/to bounds are stored with the job.  Revalidating a queued job
    accepts that frozen partial cutoff, including after New Year, instead of
    silently adding another day or changing the final selected period.  Only
    durable-record call sites may set ``allow_resolved_partial``; initial API
    submissions must match the server's complete available periods exactly.
    """

    selected_years = req.years
    if selected_years is None:
        if not req.from_date or not req.to_date:
            raise HTTPException(
                status_code=422,
                detail="Choose annual start/end dates or at least one MIDC year.",
            )
        try:
            start_date = date.fromisoformat(req.from_date)
            end_date = date.fromisoformat(req.to_date)
        except (TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=422, detail="Annual dates must use YYYY-MM-DD."
            ) from exc
        if start_date > end_date:
            raise HTTPException(
                status_code=422,
                detail="Annual start date must be on or before end date.",
            )
        inclusive_days = (end_date - start_date).days + 1
        if inclusive_days > config.ANNUAL_RUN_MAX_DAYS:
            raise HTTPException(
                status_code=422,
                detail=(
                    "Annual runs are limited to "
                    f"{config.ANNUAL_RUN_MAX_DAYS:,} days."
                ),
            )
        periods = _legacy_annual_periods(start_date, end_date)
        _validate_annual_row_count(req, periods)
        return periods

    if not selected_years:
        raise HTTPException(
            status_code=422, detail="Select at least one MIDC year."
        )
    normalized_years = [int(year) for year in selected_years]
    if len(set(normalized_years)) != len(normalized_years):
        raise HTTPException(
            status_code=422, detail="Selected MIDC years must not contain duplicates."
        )
    normalized_years.sort()

    local_today = today or datetime.now(config.ANNUAL_TZ).date()
    current_year = local_today.year
    invalid_years = [
        year
        for year in normalized_years
        if year < midc.FIRST_AVAILABLE_DATE.year or year > current_year
    ]
    if invalid_years:
        raise HTTPException(
            status_code=422,
            detail=(
                "MIDC STAC years must be between "
                f"{midc.FIRST_AVAILABLE_DATE.year} and {current_year}."
            ),
        )

    data_through = local_today - timedelta(days=1)
    if current_year in normalized_years and data_through.year < current_year:
        raise HTTPException(
            status_code=422,
            detail=(
                f"MIDC has no complete daily file for {current_year} yet; "
                "try again once January 1 data is published."
            ),
        )

    expected_start = (
        midc.FIRST_AVAILABLE_DATE
        if normalized_years[0] == midc.FIRST_AVAILABLE_DATE.year
        else date(normalized_years[0], 1, 1)
    )
    expected_end = (
        data_through
        if normalized_years[-1] == current_year
        else date(normalized_years[-1], 12, 31)
    )

    if req.from_date is None and req.to_date is None:
        resolved_start = expected_start
        resolved_end = expected_end
    elif not req.from_date or not req.to_date:
        raise HTTPException(
            status_code=422,
            detail="Selected years require either both resolved dates or neither date.",
        )
    else:
        try:
            resolved_start = date.fromisoformat(req.from_date)
            resolved_end = date.fromisoformat(req.to_date)
        except (TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=422, detail="Annual dates must use YYYY-MM-DD."
            ) from exc
        if resolved_start != expected_start:
            raise HTTPException(
                status_code=422,
                detail=(
                    "The resolved annual start does not match the selected MIDC years."
                ),
            )
        if not allow_resolved_partial and resolved_end != expected_end:
            raise HTTPException(
                status_code=422,
                detail=(
                    "Selected MIDC years must use their complete available periods; "
                    "omit custom dates and let the server resolve them."
                ),
            )
        if allow_resolved_partial:
            final_year = normalized_years[-1]
            earliest_final_date = (
                midc.FIRST_AVAILABLE_DATE
                if final_year == midc.FIRST_AVAILABLE_DATE.year
                else date(final_year, 1, 1)
            )
            latest_final_date = (
                data_through
                if final_year == current_year
                else date(final_year, 12, 31)
            )
            if not earliest_final_date <= resolved_end <= latest_final_date:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        "The frozen annual end must be an available date within the "
                        "final selected MIDC year."
                    ),
                )

    req.years = normalized_years
    req.from_date = resolved_start.isoformat()
    req.to_date = resolved_end.isoformat()

    periods: list[dict[str, object]] = []
    final_year = normalized_years[-1]
    for year in normalized_years:
        period_start = (
            midc.FIRST_AVAILABLE_DATE
            if year == midc.FIRST_AVAILABLE_DATE.year
            else date(year, 1, 1)
        )
        period_end = resolved_end if year == final_year else date(year, 12, 31)
        periods.append(_annual_period_record(year, period_start, period_end))
    _validate_annual_row_count(req, periods)
    return periods


def _annual_dates(
    req: AnnualRunRequest,
    *,
    allow_resolved_partial: bool = False,
) -> tuple[date, date]:
    periods = _annual_periods(
        req,
        allow_resolved_partial=allow_resolved_partial,
    )
    try:
        start_date = date.fromisoformat(str(periods[0]["period_start"]))
        end_date = date.fromisoformat(str(periods[-1]["period_end"]))
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=422, detail="Annual dates must use YYYY-MM-DD."
        ) from exc
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
        max_range=config.CALIBRATION_REVIEW_MAX_RANGE,
        max_rows=config.CALIBRATION_REVIEW_MAX_ROWS,
        label="Calibration reviews",
    )
