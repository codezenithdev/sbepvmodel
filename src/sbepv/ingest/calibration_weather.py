"""Explicit, audited MIDC weather substitution for calibration reviews.

The annual MIDC reader is deliberately unchanged.  This adapter maps the
repository's right-edge minute convention onto historian start-labeled bins.
It never interpolates a requested replacement or changes an unselected cell.
"""

from __future__ import annotations

import hashlib
import math
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

from sbepv import calibration
from sbepv.ingest import midc


POLICY = "midc_stac_complete_minutes_v1"
FIXED_MST = "Etc/GMT+7"
FIELD_COLUMNS = {
    "temp_air": "Air Temperature [deg C]",
    "wind_speed": "Avg Wind Speed @ 10m [m/s]",
}
MAX_SOURCE_REQUESTS = 32
SOURCE_CHUNK_DAYS = 31
SOURCE_BUDGET_SECONDS = 60.0
SOURCE_TIMEOUT_SECONDS = 12.0


def _utc_minute(value: Any, label: str) -> pd.Timestamp:
    try:
        stamp = pd.Timestamp(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{label} must be a valid timezone-aware timestamp.") from exc
    if pd.isna(stamp) or stamp.tzinfo is None:
        raise ValueError(f"{label} must be a valid timezone-aware timestamp.")
    stamp = stamp.tz_convert("UTC")
    if stamp != stamp.floor("min"):
        raise ValueError(f"{label} must align to a whole minute.")
    return stamp


def _json_value(value: Any) -> Any:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, (np.integer, int)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return float(value) if math.isfinite(float(value)) else str(value)
    if isinstance(value, (str, bool)):
        return value
    return str(value)


def _selection(
    raw: pd.DataFrame,
    report: Mapping[str, Any],
    *,
    fields: list[str],
    mode: str,
    start_utc: str | None,
    end_utc: str | None,
    interval_seconds: int,
    requested_start: str,
    requested_end: str,
) -> tuple[pd.Series, dict[str, list[int]], dict[str, Any]]:
    if not fields or len(fields) != len(set(fields)) or set(fields) - FIELD_COLUMNS.keys():
        raise ValueError("Choose ambient temperature and/or wind speed exactly once.")
    if mode not in {"flagged", "period"}:
        raise ValueError("Weather replacement mode must be flagged or period.")
    if isinstance(interval_seconds, bool) or not isinstance(interval_seconds, int):
        raise ValueError("MIDC replacement interval must be whole-minute seconds.")
    if interval_seconds < 60 or interval_seconds > 86400 or interval_seconds % 60:
        raise ValueError("MIDC replacement interval must be whole minutes from 1 minute to 1 day.")
    if "timestamp" not in raw or any(field not in raw for field in fields):
        raise ValueError("Historian source lacks the selected weather column or timestamps.")
    request_start = _utc_minute(requested_start, "Requested start")
    request_end = _utc_minute(requested_end, "Requested end")
    if request_start >= request_end:
        raise ValueError("Requested start must precede requested end.")
    if mode == "period":
        if start_utc is None or end_utc is None:
            raise ValueError("Period replacement requires start and end timestamps.")
        selected_start = _utc_minute(start_utc, "Replacement start")
        selected_end = _utc_minute(end_utc, "Replacement end")
        if not request_start <= selected_start < selected_end <= request_end:
            raise ValueError("Replacement period must lie within the reviewed request window.")
        step = pd.Timedelta(seconds=interval_seconds)
        if (selected_start - request_start) % step or (
            selected_end != request_end and (selected_end - request_start) % step
        ):
            raise ValueError(
                "Replacement period boundaries must align to the historian request "
                "interval grid; the reviewed request end is also allowed."
            )
    else:
        if start_utc is not None or end_utc is not None:
            raise ValueError("Flagged replacement does not accept custom period boundaries.")
        selected_start, selected_end = request_start, request_end

    stamps = pd.to_datetime(raw["timestamp"], errors="coerce", utc=True, format="mixed")
    structurally_excluded: set[int] = set()
    for issue in report.get("issues", []):
        if issue.get("id") in {"timestamp.invalid", "timestamp.outside_requested_window"}:
            if list(issue.get("allowed_actions") or []) == ["exclude"]:
                structurally_excluded.update(int(v) for v in issue.get("_row_positions", []))
    candidates = ~raw.index.isin(structurally_excluded)
    if stamps.loc[candidates].isna().any():
        raise ValueError("Invalid historian timestamps must be structurally excluded before replacement.")
    candidates &= stamps.ge(request_start) & stamps.lt(request_end)
    duplicate_rows = stamps.loc[candidates].duplicated(keep=False)
    duplicate_positions = set(int(v) for v in duplicate_rows.index[duplicate_rows])
    candidates &= ~raw.index.isin(duplicate_positions)
    if (stamps.loc[candidates] != stamps.loc[candidates].dt.floor("min")).any():
        raise ValueError("Historian timestamps must align to whole minutes for MIDC replacement.")
    selected = candidates & stamps.ge(selected_start) & stamps.lt(selected_end)
    positions: dict[str, list[int]] = {}
    for field in fields:
        if mode == "period":
            positions[field] = [int(v) for v in raw.index[selected]]
        else:
            flagged: set[int] = set()
            for issue in report.get("issues", []):
                if issue.get("id") in {
                    f"missing.{field}", f"numeric.invalid.{field}", f"range.{field}"
                }:
                    flagged.update(int(v) for v in issue.get("_row_positions", []))
            if any(v < 0 or v >= len(raw) for v in flagged):
                raise ValueError("Weather issue positions do not match the historian source.")
            positions[field] = sorted(v for v in flagged if bool(selected.iloc[v]))
    if not any(positions.values()):
        raise ValueError("No matching weather cells were found for the selected replacement fields and scope.")
    metadata = {
        "start_utc": selected_start.isoformat(),
        "end_utc": selected_end.isoformat(),
        "requested_start_utc": request_start.isoformat(),
        "requested_end_utc": request_end.isoformat(),
        "structurally_excluded_rows": len(structurally_excluded),
        "skipped_duplicate_rows": len(duplicate_positions),
    }
    return stamps, positions, metadata


def _minute_weather(source: pd.DataFrame, fields: list[str]) -> tuple[pd.DataFrame, int]:
    """Validate source keys and collapse only identical duplicate minute values."""
    if source.empty:
        return pd.DataFrame(columns=fields, index=pd.DatetimeIndex([], tz="UTC")), 0
    years = pd.to_numeric(source["Year"], errors="coerce")
    days = pd.to_numeric(source["DOY"], errors="coerce")
    dates = midc._parse_source_dates(source)
    clock_values = pd.to_numeric(source["MST"], errors="coerce")
    hours = clock_values.floordiv(100)
    minutes = clock_values.mod(100)
    valid = (
        dates.notna() & years.eq(dates.dt.year) & days.eq(dates.dt.dayofyear)
        & clock_values.mod(1).eq(0) & hours.between(0, 23) & minutes.between(0, 59)
    )
    dropped = int((~valid).sum())
    stamps = (dates + pd.to_timedelta(hours, unit="h") + pd.to_timedelta(minutes, unit="min"))
    stamps = stamps.loc[valid].dt.tz_localize(FIXED_MST).dt.tz_convert("UTC")
    weather = pd.DataFrame(index=pd.DatetimeIndex(stamps))
    for field in fields:
        weather[field] = pd.to_numeric(source.loc[valid, FIELD_COLUMNS[field]], errors="coerce").to_numpy()
    if weather.index.has_duplicates:
        for _, repeated in weather.loc[weather.index.duplicated(keep=False)].groupby(level=0):
            for field in fields:
                if repeated[field].nunique(dropna=False) > 1:
                    raise ValueError("MIDC contains conflicting values for the same minute timestamp.")
        weather = weather.loc[~weather.index.duplicated(keep="first")]
    for field in fields:
        lower, upper = calibration.DOMAIN_BOUNDS[field]
        # Wind is a speed; unlike historian rounding, replacement needs no clamp.
        if field == "wind_speed":
            lower = 0.0
        values = weather[field]
        valid_values = np.isfinite(values) & values.between(lower, upper) & values.gt(midc.MISSING_SENTINEL_MAX)
        weather[field] = values.where(valid_values)
    return weather.sort_index(), dropped


def _interval_statistics(
    values: pd.Series, starts_ns: np.ndarray, ends_ns: np.ndarray, interval_seconds: int
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Vectorized coverage and compensated means for (start, end] minute bins.

    Counts use timestamp searches, so missing source minutes cannot be hidden by
    adjacent readings. Rolling means use pandas' compensated summation rather
    than subtracting large accumulated floating-point sums.
    """
    source_ns = values.index.as_unit("ns").asi8
    left = np.searchsorted(source_ns, starts_ns, side="right")
    right = np.searchsorted(source_ns, ends_ns, side="right")
    expected = ((ends_ns - starts_ns) // (60 * 1_000_000_000)).astype(np.int64)
    valid_prefix = np.concatenate(([0], np.cumsum(values.notna().to_numpy(), dtype=np.int64)))
    counts = valid_prefix[right] - valid_prefix[left]
    complete = (expected > 0) & (counts == expected)
    means = np.full(len(starts_ns), np.nan, dtype=float)
    for sample_count in np.unique(expected[complete]):
        mask = complete & (expected == sample_count)
        if sample_count == 1:
            means[mask] = values.to_numpy(dtype=float)[right[mask] - 1]
        elif sample_count == interval_seconds // 60:
            rolling_means = values.rolling(int(sample_count), min_periods=int(sample_count)).mean().to_numpy()
            means[mask] = rolling_means[right[mask] - 1]
        else:
            # Only clipped boundary bins take this path, never every normal row.
            numeric = values.to_numpy(dtype=float)
            for index in np.flatnonzero(mask):
                means[index] = numeric[left[index]:right[index]].mean()
    return counts, expected, means


def apply_weather_replacement(
    raw: pd.DataFrame,
    report: Mapping[str, Any],
    source_minutes: pd.DataFrame,
    *,
    fields: list[str],
    mode: str,
    start_utc: str | None,
    end_utc: str | None,
    interval_seconds: int,
    requested_start: str,
    requested_end: str,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Pure substitution; incomplete candidate bins leave original cells intact."""
    raw = raw.reset_index(drop=True)
    stamps, positions, selection = _selection(
        raw, report, fields=fields, mode=mode, start_utc=start_utc, end_utc=end_utc,
        interval_seconds=interval_seconds, requested_start=requested_start, requested_end=requested_end,
    )
    weather, dropped = _minute_weather(source_minutes, fields)
    updated = raw.copy(deep=True)
    # Object storage permits replacement of malformed strings without coercing
    # any unselected cell or requiring pandas' incompatible-dtype assignment.
    for field in fields:
        updated[field] = updated[field].astype(object)
    end_bound = _utc_minute(selection["end_utc"], "Replacement end")
    request_start_ns = _utc_minute(requested_start, "Requested start").value
    request_end = _utc_minute(requested_end, "Requested end")
    ordered_stamps = pd.DatetimeIndex(
        stamps.loc[stamps.ge(pd.Timestamp(request_start_ns, tz="UTC")) & stamps.lt(request_end)]
    ).drop_duplicates().sort_values().as_unit("ns").asi8
    step_ns = interval_seconds * 1_000_000_000
    events: list[dict[str, Any]] = []
    for field in fields:
        field_positions = positions[field]
        selected_stamps = pd.DatetimeIndex(stamps.iloc[field_positions]).as_unit("ns")
        starts_ns = selected_stamps.asi8
        ends_ns = np.minimum(starts_ns + step_ns, end_bound.value)
        off_grid = (starts_ns - request_start_ns) % step_ns != 0
        next_indices = np.searchsorted(ordered_stamps, starts_ns, side="right")
        next_stamps = np.append(ordered_stamps, request_end.value)[next_indices]
        overlaps_next = next_stamps < ends_ns
        valid_counts, expected_counts, means = _interval_statistics(
            weather[field], starts_ns, ends_ns, interval_seconds
        )
        complete = np.isfinite(means) & ~off_grid & ~overlaps_next
        replaced_positions = np.asarray(field_positions, dtype=np.int64)[complete]
        updated.iloc[replaced_positions, updated.columns.get_loc(field)] = means[complete]
        for index, position in enumerate(field_positions):
            start = stamps.iloc[position]
            end = pd.Timestamp(ends_ns[index], tz="UTC")
            is_complete = bool(complete[index])
            replacement = float(means[index]) if is_complete else None
            reason = (
                "historian_interval_grid_mismatch" if off_grid[index]
                else "historian_interval_overlap" if overlaps_next[index]
                else "complete_valid_minute_coverage" if is_complete
                else "incomplete_or_invalid_midc_minutes"
            )
            events.append({
                "row_position": position, "timestamp_utc": start.isoformat(),
                "interval_end_utc": end.isoformat(), "column": field,
                "original_value": _json_value(raw.at[position, field]),
                "replacement_value": replacement,
                "status": "replaced" if is_complete else "unavailable",
                "reason": reason,
                "valid_samples": int(valid_counts[index]), "expected_samples": int(expected_counts[index]),
            })
    replaced = [event for event in events if event["status"] == "replaced"]
    audit = {
        "schema_version": 1, "policy": POLICY, "station": "STAC",
        "fields": list(fields), "mode": mode, "selection": selection,
        "source_timezone": FIXED_MST, "interval_seconds": interval_seconds,
        "interval_convention": "historian_start_t_matches_MIDC_minute_keys_(t,t+duration]",
        "alignment_basis": "repository_historian_start_and_MIDC_right_edge_contracts",
        "units": {field: "degC" if field == "temp_air" else "m/s" for field in fields},
        "wind_height_m": 10 if "wind_speed" in fields else None,
        "events": events,
        "counts": {
            "selected_cells": len(events), "replaced_cells": len(replaced),
            "unavailable_cells": len(events) - len(replaced),
            "selected_rows": len({event["row_position"] for event in events}),
            "replaced_rows": len({event["row_position"] for event in replaced}),
            "dropped_midc_timestamp_rows": dropped,
        },
        "source_snapshots": [], "source_warnings": [],
    }
    return updated, audit


def _download_sources(start_date: date, end_date: date) -> tuple[pd.DataFrame, list[dict], list[str]]:
    frames: list[pd.DataFrame] = []
    snapshots: list[dict] = []
    warnings: list[str] = []
    request_count = 0
    deadline = time.monotonic() + SOURCE_BUDGET_SECONDS
    for chunk_start, chunk_end in midc._date_chunks(start_date, end_date, SOURCE_CHUNK_DAYS):
        cursor = chunk_start
        while cursor <= chunk_end:
            remaining = deadline - time.monotonic()
            if request_count >= MAX_SOURCE_REQUESTS or remaining <= 0:
                warnings.append("MIDC download time/request budget reached; remaining source minutes are unavailable.")
                return (pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=midc.RAW_REQUIRED_COLUMNS), snapshots, warnings)
            request_count += 1
            try:
                csv_text = midc.download_api_csv(
                    cursor, chunk_end, timeout_seconds=min(SOURCE_TIMEOUT_SECONDS, remaining)
                )
            except midc.MidcError as exc:
                warnings.append(f"MIDC {cursor} through {chunk_end}: {exc}")
                break
            snapshot = {
                "start_date": cursor.isoformat(), "end_date": chunk_end.isoformat(),
                "url": midc.build_api_url(cursor, chunk_end),
                "sha256": hashlib.sha256(csv_text.encode("utf-8")).hexdigest(),
                "csv_text": csv_text,
            }
            snapshots.append(snapshot)
            try:
                parsed = midc.parse_api_csv(csv_text)
                dates = midc._parse_source_dates(parsed)
                in_window = dates.between(pd.Timestamp(cursor), pd.Timestamp(chunk_end)) | dates.isna()
                frames.append(parsed.loc[in_window].copy())
                break
            except midc.MidcError as exc:
                if midc._missing_begin_date(csv_text) != cursor:
                    warnings.append(f"MIDC {cursor} through {chunk_end}: {exc}")
                    break
                warnings.append(f"MIDC source file unavailable for {cursor}.")
                later = [day for day in midc._suggested_available_dates(csv_text) if cursor < day <= chunk_end]
                cursor = later[0] if later else cursor + timedelta(days=1)
    return (pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=midc.RAW_REQUIRED_COLUMNS), snapshots, warnings)


def prepare_weather_replacement(
    source_csv: str | Path,
    report: Mapping[str, Any],
    *,
    fields: list[str],
    mode: str,
    start_utc: str | None,
    end_utc: str | None,
    interval_seconds: int,
    requested_start: str,
    requested_end: str,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Fetch archived source minutes and return a review candidate plus evidence."""
    raw = pd.read_csv(source_csv)
    kwargs = dict(fields=fields, mode=mode, start_utc=start_utc, end_utc=end_utc,
                  interval_seconds=interval_seconds, requested_start=requested_start, requested_end=requested_end)
    stamps, positions, _ = _selection(raw, report, **kwargs)
    selected_positions = sorted({position for values in positions.values() for position in values})
    source = pd.DataFrame(columns=midc.RAW_REQUIRED_COLUMNS)
    snapshots: list[dict] = []
    warnings: list[str] = []
    now_utc = pd.Timestamp(datetime.now(timezone.utc))
    last_complete_date = now_utc.tz_convert(FIXED_MST).date() - timedelta(days=1)
    if selected_positions:
        first_minute = stamps.iloc[selected_positions].min() + pd.Timedelta(minutes=1)
        last_minute = min(stamps.iloc[selected_positions].max() + pd.Timedelta(seconds=interval_seconds), _utc_minute(requested_end, "Requested end"))
        first_date = max(first_minute.tz_convert(FIXED_MST).date(), midc.FIRST_AVAILABLE_DATE)
        last_date = min(last_minute.tz_convert(FIXED_MST).date(), last_complete_date)
        if first_date <= last_date:
            source, snapshots, warnings = _download_sources(first_date, last_date)
        if first_minute.tz_convert(FIXED_MST).date() < midc.FIRST_AVAILABLE_DATE:
            warnings.append("Selected minutes precede the first archived MIDC STAC date.")
        if last_minute.tz_convert(FIXED_MST).date() > last_complete_date:
            warnings.append("Current-day and future MIDC minutes are unavailable; only completed fixed-MST source days are used.")
    updated, audit = apply_weather_replacement(raw, report, source, **kwargs)
    audit.update(source_snapshots=snapshots, source_warnings=warnings,
                 fetched_at_utc=now_utc.isoformat(), last_complete_source_date=last_complete_date.isoformat())
    return updated, audit
