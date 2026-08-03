"""Data-quality review and calibration helpers for historian model runs.

The dashboard uses this module in two distinct stages:

1. profile the untouched Bazefield CSV and obtain explicit retain/exclude
   decisions from the user;
2. calculate transparent, energy-weighted calibration factors after the
   physics model has produced its uncalibrated prediction.

The functions deliberately return JSON-friendly dictionaries.  Private keys
whose names begin with ``_`` carry row positions needed to apply a review and
are stripped before a report is returned through the API.
"""

from __future__ import annotations

import os
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

import numpy as np
import pandas as pd


REPORT_VERSION = 1
CALIBRATION_PROFILE_SCHEMA_VERSION = 1
LOCAL_TIMEZONE = "America/Denver"
BAD_ROW_PREVIEW_LIMIT = 50

HISTORIAN_COLUMNS = (
    "timestamp",
    "solaredge_measured_power",
    "solectria_measured_power",
    "dni",
    "ghi",
    "dhi",
    "temp_air",
    "wind_speed",
)
NUMERIC_COLUMNS = HISTORIAN_COLUMNS[1:]
POWER_COLUMNS = (
    "solaredge_measured_power",
    "solectria_measured_power",
)
IRRADIANCE_COLUMNS = ("dni", "ghi", "dhi")

COLUMN_LABELS = {
    "solaredge_measured_power": "SolarEdge measured power",
    "solectria_measured_power": "Solectria measured power",
    "dni": "DNI",
    "ghi": "GHI",
    "dhi": "DHI",
    "temp_air": "ambient temperature",
    "wind_speed": "wind speed",
}

# Broad physical/domain bounds.  They are intentionally wider than ordinary
# operating ranges so legitimate extreme weather is not silently rejected.
DOMAIN_BOUNDS = {
    "solaredge_measured_power": (-1.0, 200_000.0),
    "solectria_measured_power": (-1.0, 200_000.0),
    "dni": (-5.0, 1_500.0),
    "ghi": (-5.0, 1_400.0),
    "dhi": (-5.0, 1_400.0),
    "temp_air": (-40.0, 60.0),
    "wind_speed": (-0.1, 50.0),
}

LOCAL_OUTLIER_FLOORS = {
    "solaredge_measured_power": 55_000.0,
    "solectria_measured_power": 55_000.0,
    "dni": 600.0,
    "ghi": 500.0,
    "dhi": 350.0,
    "temp_air": 12.0,
    "wind_speed": 15.0,
}

SEASON_MONTHS = {
    "winter": "Dec-Feb",
    "spring": "Mar-May",
    "summer": "Jun-Aug",
    "fall": "Sep-Nov",
}


def season_name(value: Any) -> str:
    """Return the meteorological season for a timestamp-like value."""

    month = int(pd.Timestamp(value).month)
    if month in (12, 1, 2):
        return "winter"
    if month in (3, 4, 5):
        return "spring"
    if month in (6, 7, 8):
        return "summer"
    return "fall"


def validate_seasonal_calibration_profile(
    profile: Mapping[str, Any],
    *,
    required_seasons: tuple[str, ...] | list[str] = (),
) -> dict[str, Any]:
    """Return a canonical, JSON-safe frozen seasonal calibration profile."""

    if not isinstance(profile, Mapping):
        raise ValueError("Calibration profile must be an object.")
    version = profile.get("schema_version")
    if (
        isinstance(version, bool)
        or version != CALIBRATION_PROFILE_SCHEMA_VERSION
    ):
        raise ValueError(
            "Calibration profile schema_version must be "
            f"{CALIBRATION_PROFILE_SCHEMA_VERSION}."
        )
    canonical = deepcopy(dict(profile))
    for field in (
        "origin_job_id",
        "origin_source_sha256",
        "origin_review_id",
    ):
        value = canonical.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"Calibration profile {field} must not be blank.")
        canonical[field] = value.strip()

    raw_factors = canonical.get("seasonal_factors")
    if not isinstance(raw_factors, Mapping) or not raw_factors:
        raise ValueError(
            "Calibration profile seasonal_factors must not be empty."
        )
    factors: dict[str, dict[str, float]] = {}
    for raw_season, raw_systems in raw_factors.items():
        season = str(raw_season).strip().lower()
        if season not in SEASON_MONTHS:
            raise ValueError(
                f"Calibration profile contains an unknown season: {raw_season}."
            )
        if season in factors:
            raise ValueError(
                f"Calibration profile contains duplicate season: {season}."
            )
        if not isinstance(raw_systems, Mapping):
            raise ValueError(
                f"Calibration profile {season} factors must be an object."
            )
        factors[season] = {}
        for system in ("solaredge", "solectria"):
            value = raw_systems.get(system)
            if isinstance(value, (bool, str)) or value is None:
                raise ValueError(
                    f"Calibration profile {season} {system} factor "
                    "must be a finite non-negative number."
                )
            try:
                factor = float(value)
            except (TypeError, ValueError, OverflowError) as exc:
                raise ValueError(
                    f"Calibration profile {season} {system} factor "
                    "must be a finite non-negative number."
                ) from exc
            if not np.isfinite(factor) or factor < 0.0:
                raise ValueError(
                    f"Calibration profile {season} {system} factor "
                    "must be a finite non-negative number."
                )
            factors[season][system] = factor

    missing = sorted(
        {
            str(value).strip().lower()
            for value in required_seasons
            if str(value).strip().lower() not in factors
        }
    )
    if missing:
        raise ValueError(
            "Calibration profile does not cover required season(s): "
            + ", ".join(missing)
            + "."
        )
    canonical["seasonal_factors"] = factors
    return canonical


def _utc_timestamp(value: Any, *, field_name: str) -> pd.Timestamp:
    """Normalize a requested-window boundary to an aware UTC timestamp."""

    try:
        timestamp = pd.Timestamp(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{field_name} must be a valid timestamp.") from exc
    if pd.isna(timestamp):
        raise ValueError(f"{field_name} must be a valid timestamp.")
    if timestamp.tzinfo is None:
        return timestamp.tz_localize("UTC")
    return timestamp.tz_convert("UTC")


def _requested_utc_window(
    requested_start: Any | None,
    requested_end: Any | None,
) -> tuple[pd.Timestamp, pd.Timestamp] | None:
    """Validate optional end-exclusive requested coverage boundaries."""

    if (requested_start is None) != (requested_end is None):
        raise ValueError(
            "requested_start and requested_end must be supplied together."
        )
    if requested_start is None:
        return None
    start = _utc_timestamp(requested_start, field_name="requested_start")
    end = _utc_timestamp(requested_end, field_name="requested_end")
    if start >= end:
        raise ValueError("requested_start must be before requested_end.")
    return start, end


def _json_scalar(value: Any) -> Any:
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        value = float(value)
        return value if np.isfinite(value) else None
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    return value


def _json_cell(value: Any) -> Any:
    """Return a JSON-safe scalar from one source-data cell."""

    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    converted = _json_scalar(value)
    if converted is None or isinstance(
        converted, (str, int, float, bool)
    ):
        return converted
    return str(converted)


def _affected_row_preview(
    raw: pd.DataFrame,
    positions: list[int],
    *,
    limit: int = BAD_ROW_PREVIEW_LIMIT,
) -> list[dict[str, Any]]:
    """Return a bounded source-row preview for an issue decision."""

    columns = [column for column in HISTORIAN_COLUMNS if column in raw.columns]
    rows: list[dict[str, Any]] = []
    for position in positions[: max(int(limit), 0)]:
        if position < 0 or position >= len(raw):
            continue
        source_row = raw.iloc[position]
        rows.append(
            {
                "source_row": int(position) + 2,
                **{
                    column: _json_cell(source_row[column])
                    for column in columns
                },
            }
        )
    return rows


def _positions(mask: pd.Series | np.ndarray) -> list[int]:
    values = np.asarray(mask, dtype=bool)
    return [int(value) for value in np.flatnonzero(values)]


def _sample_timestamps(
    parsed_timestamps: pd.Series,
    positions: list[int],
    *,
    limit: int = 8,
) -> list[str]:
    samples: list[str] = []
    for position in positions[:limit]:
        if position >= len(parsed_timestamps):
            continue
        value = parsed_timestamps.iloc[position]
        if pd.isna(value):
            samples.append(f"row {position + 2}")
        else:
            samples.append(pd.Timestamp(value).isoformat())
    return samples


def _issue(
    *,
    issue_id: str,
    category: str,
    severity: str,
    title: str,
    description: str,
    positions: list[int] | None = None,
    occurrence_count: int | None = None,
    columns: list[str] | None = None,
    evidence: Mapping[str, Any] | None = None,
    allowed_actions: tuple[str, ...] = ("retain", "exclude"),
    recommended_action: str = "exclude",
    parsed_timestamps: pd.Series | None = None,
) -> dict[str, Any]:
    row_positions = sorted({int(value) for value in (positions or [])})
    count = (
        int(occurrence_count)
        if occurrence_count is not None
        else len(row_positions)
    )
    payload: dict[str, Any] = {
        "id": issue_id,
        "category": category,
        "severity": severity,
        "title": title,
        "description": description,
        "row_count": count,
        "columns": list(columns or []),
        "allowed_actions": list(allowed_actions),
        "recommended_action": recommended_action,
        "evidence": {
            str(key): _json_scalar(value)
            for key, value in dict(evidence or {}).items()
        },
        "_row_positions": row_positions,
    }
    if parsed_timestamps is not None and row_positions:
        payload["sample_timestamps"] = _sample_timestamps(
            parsed_timestamps, row_positions
        )
    return payload


def _contiguous_runs(mask: np.ndarray) -> list[tuple[int, int]]:
    runs: list[tuple[int, int]] = []
    start: int | None = None
    for index, active in enumerate(mask):
        if active and start is None:
            start = index
        if start is not None and (not active or index == len(mask) - 1):
            end = index if active and index == len(mask) - 1 else index - 1
            runs.append((start, end))
            start = None
    return runs


def _flatline_positions(
    values: pd.Series,
    timestamps: pd.Series,
    *,
    interval_seconds: int,
    minimum_value: float,
) -> list[int]:
    """Find non-zero sensor values stuck for roughly four hours or longer."""

    if values.empty:
        return []
    required = max(4, int(np.ceil((4 * 3600) / max(interval_seconds, 1))))
    ordered = pd.DataFrame(
        {
            "position": np.arange(len(values), dtype=int),
            "value": pd.to_numeric(values, errors="coerce"),
            "timestamp": timestamps,
        }
    ).dropna(subset=["value", "timestamp"])
    if len(ordered) < required:
        return []
    ordered = ordered.sort_values("timestamp")
    rounded = ordered["value"].round(3)
    gap_break = (
        ordered["timestamp"].diff().dt.total_seconds()
        > max(interval_seconds, 1) * 1.5
    )
    group = (rounded.ne(rounded.shift()) | gap_break.fillna(False)).cumsum()
    positions: list[int] = []
    for _, block in ordered.groupby(group, sort=False):
        if (
            len(block) >= required
            and abs(float(block["value"].iloc[0])) >= minimum_value
        ):
            positions.extend(int(value) for value in block["position"])
    return sorted(set(positions))


def inspect_historian_csv(
    csv_path: str | Path,
    *,
    expected_interval_seconds: int,
    requested_start: Any | None = None,
    requested_end: Any | None = None,
) -> dict[str, Any]:
    """Profile one Bazefield historian CSV and return a review report."""

    source = Path(csv_path)
    raw = pd.read_csv(source)
    row_count = int(len(raw))
    interval_seconds = max(int(expected_interval_seconds), 1)
    requested_window = _requested_utc_window(requested_start, requested_end)
    requested_start_utc = requested_window[0] if requested_window else None
    requested_end_utc = requested_window[1] if requested_window else None
    issues: list[dict[str, Any]] = []

    missing_columns = [
        column for column in HISTORIAN_COLUMNS if column not in raw.columns
    ]
    if missing_columns:
        issues.append(
            _issue(
                issue_id="schema.missing_columns",
                category="schema",
                severity="critical",
                title="Required Bazefield columns are missing",
                description=(
                    "The source cannot be calibrated until the historian export "
                    "contains every required measurement and weather column."
                ),
                occurrence_count=len(missing_columns),
                columns=missing_columns,
                evidence={"missing_columns": ", ".join(missing_columns)},
                allowed_actions=(),
                recommended_action="blocked",
            )
        )
        return {
            "version": REPORT_VERSION,
            "source": {
                "path": str(source.resolve()),
                "row_count": row_count,
                "expected_interval_seconds": interval_seconds,
                "requested_start": (
                    requested_start_utc.isoformat()
                    if requested_start_utc is not None
                    else None
                ),
                "requested_end": (
                    requested_end_utc.isoformat()
                    if requested_end_utc is not None
                    else None
                ),
                "first_timestamp": None,
                "last_timestamp": None,
            },
            "summary": {
                "status": "blocked",
                "blocking": True,
                "issue_count": len(issues),
                "actionable_issue_count": 0,
                "affected_rows": 0,
                "affected_row_pct": 0.0,
                "missing_intervals": 0,
            },
            "seasons": [],
            "issues": issues,
        }

    raw_timestamps = raw["timestamp"]
    parsed_utc = pd.to_datetime(raw_timestamps, errors="coerce", utc=True)
    invalid_timestamp_mask = parsed_utc.isna()
    invalid_positions = _positions(invalid_timestamp_mask)
    if invalid_positions:
        issues.append(
            _issue(
                issue_id="timestamp.invalid",
                category="invalid_timestamp",
                severity="high",
                title="Invalid timestamps",
                description=(
                    "These rows cannot be placed on the model time axis and must "
                    "be discarded before calibration."
                ),
                positions=invalid_positions,
                columns=["timestamp"],
                allowed_actions=("exclude",),
                recommended_action="exclude",
                parsed_timestamps=parsed_utc,
            )
        )

    valid_timestamp_mask = ~invalid_timestamp_mask
    outside_window_mask = pd.Series(False, index=raw.index)
    if requested_window is not None:
        outside_window_mask = valid_timestamp_mask & (
            (parsed_utc < requested_start_utc)
            | (parsed_utc >= requested_end_utc)
        )
        outside_positions = _positions(outside_window_mask)
        if outside_positions:
            issues.append(
                _issue(
                    issue_id="timestamp.outside_requested_window",
                    category="unexpected_timestamp",
                    severity="medium",
                    title="Rows outside the requested window",
                    description=(
                        "Bazefield returned timestamps before the selected start or "
                        "at/after the end-exclusive finish. They must be removed so "
                        "the factor represents exactly the requested period."
                    ),
                    positions=outside_positions,
                    columns=["timestamp"],
                    allowed_actions=("exclude",),
                    recommended_action="exclude",
                    parsed_timestamps=parsed_utc,
                )
            )
    reviewable_row_mask = valid_timestamp_mask & ~outside_window_mask
    duplicate_mask = pd.Series(False, index=raw.index)
    duplicate_mask.loc[reviewable_row_mask] = parsed_utc.loc[
        reviewable_row_mask
    ].duplicated(keep="first")
    duplicate_positions = _positions(duplicate_mask)
    if duplicate_positions:
        issues.append(
            _issue(
                issue_id="timestamp.duplicate",
                category="duplicate_timestamp",
                severity="high",
                title="Duplicate timestamps",
                description=(
                    "More than one historian row represents the same interval. "
                    "The recommended action keeps the first row and excludes the "
                    "later duplicates."
                ),
                positions=duplicate_positions,
                columns=["timestamp"],
                allowed_actions=("retain", "exclude"),
                recommended_action="exclude",
                parsed_timestamps=parsed_utc,
            )
        )

    valid_unique_times = (
        parsed_utc.loc[reviewable_row_mask & ~duplicate_mask]
        .sort_values()
        .reset_index(drop=True)
    )
    if valid_unique_times.empty:
        issues.append(
            _issue(
                issue_id="data.no_valid_timestamps",
                category="completeness",
                severity="critical",
                title="No valid historian rows",
                description=(
                    "The selected source has no row that can be placed on the "
                    "requested time axis, so calibration cannot continue."
                ),
                occurrence_count=row_count,
                columns=["timestamp"],
                allowed_actions=(),
                recommended_action="blocked",
            )
        )
    missing_intervals = 0
    gap_evidence: list[str] = []
    irregular_count = 0
    if len(valid_unique_times) >= 2:
        deltas = valid_unique_times.diff().dt.total_seconds().iloc[1:]
        for index, delta in deltas.items():
            if not np.isfinite(delta) or delta <= 0:
                continue
            ratio = float(delta) / interval_seconds
            if ratio > 1.5:
                missing = max(int(round(ratio)) - 1, 1)
                missing_intervals += missing
                if len(gap_evidence) < 8:
                    prior = valid_unique_times.iloc[index - 1]
                    current = valid_unique_times.iloc[index]
                    gap_evidence.append(
                        f"{prior.isoformat()} to {current.isoformat()} "
                        f"({missing} missing)"
                    )
            elif not np.isclose(delta, interval_seconds, rtol=0.05, atol=1.0):
                irregular_count += 1
    if missing_intervals:
        issues.append(
            _issue(
                issue_id="timestamp.gaps",
                category="gap",
                severity="medium",
                title="Missing time intervals",
                description=(
                    "The historian time grid contains gaps. Missing intervals "
                    "cannot be recovered by excluding rows; energy integration is "
                    "bounded to the requested interval so gaps are not over-counted."
                ),
                occurrence_count=missing_intervals,
                columns=["timestamp"],
                evidence={
                    "missing_intervals": missing_intervals,
                    "sample_gaps": " | ".join(gap_evidence),
                },
                allowed_actions=(),
                recommended_action="retain",
            )
        )
    if irregular_count:
        issues.append(
            _issue(
                issue_id="timestamp.irregular_spacing",
                category="irregular_interval",
                severity="medium",
                title="Irregular timestamp spacing",
                description=(
                    "Some adjacent timestamps do not match the requested sampling "
                    "interval and are not whole missing-interval gaps."
                ),
                occurrence_count=irregular_count,
                columns=["timestamp"],
                evidence={"irregular_intervals": irregular_count},
                allowed_actions=(),
                recommended_action="retain",
            )
        )

    boundary_missing_intervals = 0
    leading_missing_intervals = 0
    trailing_missing_intervals = 0
    if requested_window is not None and not valid_unique_times.empty:
        first_timestamp = valid_unique_times.iloc[0]
        last_timestamp = valid_unique_times.iloc[-1]
        tolerance_seconds = min(
            max(interval_seconds * 0.05, 1.0),
            interval_seconds * 0.49,
        )
        leading_shortfall_seconds = float(
            (first_timestamp - requested_start_utc).total_seconds()
        )
        trailing_shortfall_seconds = float(
            (
                requested_end_utc
                - (
                    last_timestamp
                    + pd.Timedelta(seconds=interval_seconds)
                )
            ).total_seconds()
        )
        if leading_shortfall_seconds > tolerance_seconds:
            leading_missing_intervals = max(
                int(np.ceil(leading_shortfall_seconds / interval_seconds)),
                1,
            )
        if trailing_shortfall_seconds > tolerance_seconds:
            trailing_missing_intervals = max(
                int(np.ceil(trailing_shortfall_seconds / interval_seconds)),
                1,
            )
        boundary_missing_intervals = (
            leading_missing_intervals + trailing_missing_intervals
        )
        if boundary_missing_intervals:
            issues.append(
                _issue(
                    issue_id="timestamp.incomplete_coverage",
                    category="gap",
                    severity="medium",
                    title="Incomplete requested-window coverage",
                    description=(
                        "The returned historian rows do not cover the full "
                        "end-exclusive requested window. Missing leading or "
                        "trailing intervals cannot be recovered during calibration."
                    ),
                    occurrence_count=boundary_missing_intervals,
                    columns=["timestamp"],
                    evidence={
                        "requested_start": requested_start_utc,
                        "requested_end": requested_end_utc,
                        "leading_missing_intervals": leading_missing_intervals,
                        "trailing_missing_intervals": trailing_missing_intervals,
                    },
                    allowed_actions=(),
                    recommended_action="retain",
                )
            )
            missing_intervals += boundary_missing_intervals

    numeric: dict[str, pd.Series] = {}
    invalid_or_missing_by_column: dict[str, set[int]] = {}
    for column in NUMERIC_COLUMNS:
        source_values = raw[column]
        converted = pd.to_numeric(source_values, errors="coerce")
        numeric[column] = converted
        missing_mask = (
            source_values.isna()
            | source_values.astype(str).str.strip().eq("")
        ) & reviewable_row_mask
        invalid_numeric_mask = (
            converted.isna() & ~missing_mask & reviewable_row_mask
        )
        missing_positions = _positions(missing_mask)
        invalid_numeric_positions = _positions(invalid_numeric_mask)
        invalid_or_missing_by_column[column] = set(
            missing_positions + invalid_numeric_positions
        )

        if missing_positions:
            model_fallback = column in {"dhi", "temp_air", "wind_speed"}
            if column == "temp_air":
                missing_description = (
                    "Retained rows may use bounded temperature interpolation for "
                    "model continuity, but they are excluded from calibration-factor "
                    "fitting. Exclusion remains the safest recommendation."
                )
            elif model_fallback:
                missing_description = (
                    "The model has a documented fallback for this field, but "
                    "retained values do not contribute directly to factor fitting."
                )
            else:
                missing_description = (
                    "Missing values can bias the measured/model energy ratio; "
                    "excluding the affected timestamps is recommended."
                )
            issues.append(
                _issue(
                    issue_id=f"missing.{column}",
                    category="missing_value",
                    severity=(
                        "high"
                        if column in POWER_COLUMNS or column in {"dni", "ghi"}
                        else "medium"
                    ),
                    title=f"Missing {COLUMN_LABELS[column]} values",
                    description=missing_description,
                    positions=missing_positions,
                    columns=[column],
                    allowed_actions=("retain", "exclude"),
                    recommended_action=(
                        "retain"
                        if column in {"dhi", "wind_speed"}
                        else "exclude"
                    ),
                    parsed_timestamps=parsed_utc,
                )
            )
        if invalid_numeric_positions:
            issues.append(
                _issue(
                    issue_id=f"numeric.invalid.{column}",
                    category="invalid_value",
                    severity="high",
                    title=f"Non-numeric {COLUMN_LABELS[column]} values",
                    description=(
                        "Text or malformed values appeared where a numeric historian "
                        "measurement is required."
                    ),
                    positions=invalid_numeric_positions,
                    columns=[column],
                    allowed_actions=("retain", "exclude"),
                    recommended_action="exclude",
                    parsed_timestamps=parsed_utc,
                )
            )

        if (
            column in {"dni", "ghi", "temp_air"}
            and not bool(
                (
                    converted.notna()
                    & np.isfinite(converted)
                    & reviewable_row_mask
                ).any()
            )
        ):
            issues.append(
                _issue(
                    issue_id=f"data.no_usable_values.{column}",
                    category="completeness",
                    severity="critical",
                    title=f"No usable {COLUMN_LABELS[column]} values",
                    description=(
                        "At least one finite numeric value is required for this "
                        "weather input before the PV model can run."
                    ),
                    occurrence_count=row_count,
                    columns=[column],
                    allowed_actions=(),
                    recommended_action="blocked",
                )
            )

        lower, upper = DOMAIN_BOUNDS[column]
        range_mask = converted.notna() & (
            (converted < lower) | (converted > upper)
        ) & reviewable_row_mask
        range_positions = _positions(range_mask)
        if range_positions:
            issues.append(
                _issue(
                    issue_id=f"range.{column}",
                    category="out_of_range",
                    severity="high",
                    title=f"{COLUMN_LABELS[column].capitalize()} outside physical bounds",
                    description=(
                        f"Values outside {lower:g} to {upper:g} were detected. "
                        "These broad bounds are intended to catch unit, sign, and "
                        "sensor failures rather than ordinary weather extremes."
                    ),
                    positions=range_positions,
                    columns=[column],
                    evidence={
                        "minimum_observed": converted.where(
                            reviewable_row_mask
                        ).min(skipna=True),
                        "maximum_observed": converted.where(
                            reviewable_row_mask
                        ).max(skipna=True),
                        "allowed_minimum": lower,
                        "allowed_maximum": upper,
                    },
                    allowed_actions=("retain", "exclude"),
                    recommended_action="exclude",
                    parsed_timestamps=parsed_utc,
                )
            )

    # Physically suspicious operation: a system reporting no production while
    # the co-located irradiance signal is strong.  Each system is reported
    # separately so the user can understand which measurement triggered review.
    ghi = numeric["ghi"]
    dni = numeric["dni"]
    daylight = ((ghi >= 200.0) | (dni >= 350.0)) & reviewable_row_mask
    for column in POWER_COLUMNS:
        values = numeric[column]
        outage_mask = daylight & values.notna() & (values <= 1_000.0)
        outage_positions = _positions(outage_mask)
        if outage_positions:
            issues.append(
                _issue(
                    issue_id=f"pattern.low_power_high_irradiance.{column}",
                    category="irregular_pattern",
                    severity="high",
                    title=f"{COLUMN_LABELS[column].capitalize()} near zero in strong sun",
                    description=(
                        "This pattern may indicate an outage, curtailment, telemetry "
                        "freeze, or a valid operating event. Exclusion is recommended "
                        "when the goal is a normal-operation calibration factor."
                    ),
                    positions=outage_positions,
                    columns=[column, "ghi", "dni"],
                    allowed_actions=("retain", "exclude"),
                    recommended_action="exclude",
                    parsed_timestamps=parsed_utc,
                )
            )

        night_mask = (
            (ghi <= 10.0)
            & (dni <= 10.0)
            & values.notna()
            & (values >= 5_000.0)
            & reviewable_row_mask
        )
        night_positions = _positions(night_mask)
        if night_positions:
            issues.append(
                _issue(
                    issue_id=f"pattern.power_without_irradiance.{column}",
                    category="irregular_pattern",
                    severity="high",
                    title=f"{COLUMN_LABELS[column].capitalize()} without irradiance",
                    description=(
                        "Substantial measured production was reported while both "
                        "GHI and DNI were near zero."
                    ),
                    positions=night_positions,
                    columns=[column, "ghi", "dni"],
                    allowed_actions=("retain", "exclude"),
                    recommended_action="exclude",
                    parsed_timestamps=parsed_utc,
                )
            )

    # A centered Hampel-style check catches isolated local spikes while the
    # generous absolute floors avoid treating ordinary solar ramps/clouds as
    # outliers.
    window = max(7, min(25, int(round((6 * 3600) / interval_seconds)) | 1))
    if row_count >= window:
        for column in NUMERIC_COLUMNS:
            values = numeric[column].where(reviewable_row_mask)
            rolling_median = values.rolling(
                window=window, center=True, min_periods=max(4, window // 2)
            ).median()
            absolute_deviation = (values - rolling_median).abs()
            rolling_mad = absolute_deviation.rolling(
                window=window, center=True, min_periods=max(4, window // 2)
            ).median()
            threshold = pd.concat(
                [
                    rolling_mad * 1.4826 * 8.0,
                    pd.Series(
                        LOCAL_OUTLIER_FLOORS[column],
                        index=values.index,
                        dtype=float,
                    ),
                ],
                axis=1,
            ).max(axis=1)
            outlier_mask = absolute_deviation > threshold
            lower, upper = DOMAIN_BOUNDS[column]
            outlier_mask &= values.between(lower, upper)
            outlier_mask &= reviewable_row_mask
            if invalid_or_missing_by_column[column]:
                outlier_mask.iloc[
                    sorted(invalid_or_missing_by_column[column])
                ] = False
            outlier_positions = _positions(outlier_mask)
            if outlier_positions:
                issues.append(
                    _issue(
                        issue_id=f"outlier.local.{column}",
                        category="outlier",
                        severity="medium",
                        title=f"Isolated {COLUMN_LABELS[column]} spikes",
                        description=(
                            "A robust rolling-median check found values far from "
                            "their local neighborhood. Real fast-changing conditions "
                            "are possible, so these samples remain a user decision."
                        ),
                        positions=outlier_positions,
                        columns=[column],
                        allowed_actions=("retain", "exclude"),
                        recommended_action="exclude",
                        parsed_timestamps=parsed_utc,
                    )
                )

    for column in (*POWER_COLUMNS, *IRRADIANCE_COLUMNS):
        minimum = 1_000.0 if column in POWER_COLUMNS else 50.0
        flat_positions = _flatline_positions(
            numeric[column].where(reviewable_row_mask),
            parsed_utc,
            interval_seconds=interval_seconds,
            minimum_value=minimum,
        )
        if flat_positions:
            issues.append(
                _issue(
                    issue_id=f"pattern.flatline.{column}",
                    category="irregular_pattern",
                    severity="medium",
                    title=f"Possible {COLUMN_LABELS[column]} sensor flatline",
                    description=(
                        "The exact same non-trivial value persisted for roughly four "
                        "hours or longer. Rounded source data can create legitimate "
                        "repeats, so inspect the timestamps before deciding."
                    ),
                    positions=flat_positions,
                    columns=[column],
                    allowed_actions=("retain", "exclude"),
                    recommended_action="exclude",
                    parsed_timestamps=parsed_utc,
                )
            )

    actionable = [
        issue for issue in issues if len(issue.get("allowed_actions") or []) > 1
    ]
    affected_positions = sorted(
        {
            int(position)
            for issue in issues
            for position in issue.get("_row_positions", [])
        }
    )
    severity_counts = {
        severity: sum(1 for issue in issues if issue["severity"] == severity)
        for severity in ("critical", "high", "medium", "low")
    }

    seasons: list[dict[str, Any]] = []
    if not valid_unique_times.empty:
        local_times = valid_unique_times.dt.tz_convert(LOCAL_TIMEZONE)
        labels = local_times.map(season_name)
        for label in dict.fromkeys(labels.tolist()):
            selected = local_times[labels == label]
            seasons.append(
                {
                    "name": label,
                    "months": SEASON_MONTHS[label],
                    "row_count": int(len(selected)),
                    "first_timestamp": selected.iloc[0].isoformat(),
                    "last_timestamp": selected.iloc[-1].isoformat(),
                }
            )

    blocking = any(issue["severity"] == "critical" for issue in issues)
    status = (
        "blocked"
        if blocking
        else "action_required"
        if issues
        else "clean"
    )
    return {
        "version": REPORT_VERSION,
        "source": {
            "path": str(source.resolve()),
            "row_count": row_count,
            "expected_interval_seconds": interval_seconds,
            "requested_start": (
                requested_start_utc.isoformat()
                if requested_start_utc is not None
                else None
            ),
            "requested_end": (
                requested_end_utc.isoformat()
                if requested_end_utc is not None
                else None
            ),
            "first_timestamp": (
                valid_unique_times.iloc[0].isoformat()
                if not valid_unique_times.empty
                else None
            ),
            "last_timestamp": (
                valid_unique_times.iloc[-1].isoformat()
                if not valid_unique_times.empty
                else None
            ),
        },
        "summary": {
            "status": status,
            "blocking": blocking,
            "issue_count": len(issues),
            "actionable_issue_count": len(actionable),
            "affected_rows": len(affected_positions),
            "affected_row_pct": (
                round(len(affected_positions) / row_count * 100.0, 3)
                if row_count
                else 0.0
            ),
            "missing_intervals": int(missing_intervals),
            "severity_counts": severity_counts,
        },
        "seasons": seasons,
        "issues": issues,
    }


def public_quality_report(report: Mapping[str, Any]) -> dict[str, Any]:
    """Return a deep copy with internal row-position metadata removed."""

    output = deepcopy(dict(report))
    for issue in output.get("issues", []):
        issue["affected_rows_available"] = bool(
            issue.get("_row_positions")
        )
        for key in list(issue):
            if str(key).startswith("_"):
                issue.pop(key, None)
    source = output.get("source")
    if isinstance(source, dict):
        source.pop("path", None)
    return output


def quality_issue_rows(
    source_csv: str | Path,
    report: Mapping[str, Any],
    issue_id: str,
    *,
    offset: int = 0,
    limit: int = BAD_ROW_PREVIEW_LIMIT,
) -> dict[str, Any]:
    """Return a bounded page of source rows affected by one review issue."""

    normalized_issue_id = str(issue_id or "").strip()
    issues = {
        str(issue.get("id")): issue
        for issue in report.get("issues", [])
        if isinstance(issue, Mapping) and issue.get("id")
    }
    issue = issues.get(normalized_issue_id)
    if issue is None:
        raise ValueError("Unknown data-quality issue ID.")
    start = int(offset)
    page_size = int(limit)
    if start < 0:
        raise ValueError("Row offset must be zero or greater.")
    if page_size < 1 or page_size > 200:
        raise ValueError("Row page size must be between 1 and 200.")

    positions = sorted(
        {
            int(position)
            for position in issue.get("_row_positions", [])
        }
    )
    selected_positions = positions[start : start + page_size]
    raw = pd.read_csv(source_csv)
    rows = _affected_row_preview(
        raw,
        selected_positions,
        limit=len(selected_positions),
    )
    next_offset = start + len(selected_positions)
    return {
        "issue_id": normalized_issue_id,
        "offset": start,
        "limit": page_size,
        "total_rows": len(positions),
        "rows": rows,
        "next_offset": next_offset if next_offset < len(positions) else None,
    }


def apply_quality_decisions(
    source_csv: str | Path,
    output_csv: str | Path,
    report: Mapping[str, Any],
    decisions: Mapping[str, str],
) -> dict[str, Any]:
    """Apply retain/exclude decisions and write a reviewed historian CSV."""

    if bool((report.get("summary") or {}).get("blocking")):
        raise ValueError("The data-quality review contains a blocking issue.")

    issues = list(report.get("issues", []))
    normalized_decisions = {
        str(issue_id): str(action)
        for issue_id, action in decisions.items()
    }
    issues_by_id = {
        str(issue["id"]): issue
        for issue in issues
    }
    unknown_decision_ids = sorted(
        set(normalized_decisions).difference(issues_by_id)
    )
    if unknown_decision_ids:
        raise ValueError(
            "Unknown data-quality decision ID(s): "
            + ", ".join(unknown_decision_ids)
        )
    non_actionable_decision_ids = sorted(
        issue_id
        for issue_id in normalized_decisions
        if len(issues_by_id[issue_id].get("allowed_actions") or []) <= 1
    )
    if non_actionable_decision_ids:
        raise ValueError(
            "Decisions may only be supplied for actionable issue ID(s): "
            + ", ".join(non_actionable_decision_ids)
        )

    raw = pd.read_csv(source_csv)
    excluded_positions: set[int] = set()
    applied: list[dict[str, Any]] = []
    missing_decisions: list[str] = []

    for issue in issues:
        issue_id = str(issue["id"])
        allowed = [str(value) for value in issue.get("allowed_actions") or []]
        recommended = str(issue.get("recommended_action") or "retain")
        if not allowed:
            action = recommended
        elif len(allowed) == 1:
            action = allowed[0]
        else:
            supplied = normalized_decisions.get(issue_id)
            if supplied is None:
                missing_decisions.append(issue_id)
                continue
            action = str(supplied)
            if action not in allowed:
                raise ValueError(
                    f"Decision for {issue_id!r} must be one of: "
                    + ", ".join(allowed)
                )
        positions = {
            int(value) for value in issue.get("_row_positions", [])
        }
        if action == "exclude":
            excluded_positions.update(positions)
        applied.append(
            {
                "issue_id": issue_id,
                "action": action,
                "affected_rows": len(positions),
            }
        )

    if missing_decisions:
        raise ValueError(
            "A retain/exclude decision is required for: "
            + ", ".join(sorted(missing_decisions))
        )

    keep = np.ones(len(raw), dtype=bool)
    for position in excluded_positions:
        if 0 <= position < len(keep):
            keep[position] = False
    cleaned = raw.loc[keep].copy()
    if cleaned.empty:
        raise ValueError("The selected exclusions remove every historian row.")

    destination = Path(output_csv)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(
        f"{destination.name}.{uuid4().hex}.tmp"
    )
    try:
        cleaned.to_csv(temporary, index=False)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    retained_issue_ids = [
        item["issue_id"] for item in applied if item["action"] == "retain"
    ]
    excluded_issue_ids = [
        item["issue_id"] for item in applied if item["action"] == "exclude"
    ]
    return {
        "original_rows": int(len(raw)),
        "final_rows": int(len(cleaned)),
        "excluded_rows": int(len(raw) - len(cleaned)),
        "excluded_row_pct": round(
            (len(raw) - len(cleaned)) / len(raw) * 100.0, 3
        )
        if len(raw)
        else 0.0,
        "retained_issue_ids": retained_issue_ids,
        "excluded_issue_ids": excluded_issue_ids,
        "decisions": applied,
    }


def _bounded_interval_hours(
    index: pd.DatetimeIndex,
    expected_interval_seconds: int | None = None,
) -> pd.Series:
    raw = index.to_series().diff().dt.total_seconds() / 3600.0
    if expected_interval_seconds is not None:
        nominal = max(float(expected_interval_seconds) / 3600.0, 0.0)
    else:
        positive = raw[(raw > 0) & np.isfinite(raw)]
        nominal = float(positive.median()) if not positive.empty else 0.0
    if nominal <= 0:
        return pd.Series(0.0, index=index, dtype=float)
    # Each aggregated historian row represents one nominal interval.  A gap
    # must not cause the next row to stand in for several missing intervals.
    return raw.fillna(nominal).clip(lower=0.0, upper=nominal)


def _integrated_energy_kwh(
    power: pd.Series,
    *,
    row_mask: pd.Series,
    dt_hours: pd.Series,
    factor: float = 1.0,
    maximum_power_w: float | None = None,
) -> float:
    """Integrate power with the same missing-value semantics as ``add_energy``."""

    selected = row_mask.fillna(False).astype(bool)
    numeric_power = pd.to_numeric(power, errors="coerce").replace(
        [np.inf, -np.inf], np.nan
    )
    scaled_power = numeric_power * float(factor)
    if maximum_power_w is not None:
        scaled_power = scaled_power.clip(upper=float(maximum_power_w))
    step_energy = (
        scaled_power.loc[selected]
        * pd.to_numeric(dt_hours.loc[selected], errors="coerce")
        / 1_000.0
    )
    return float(step_energy.replace([np.inf, -np.inf], np.nan).fillna(0.0).sum())


def _energy_balance_observation(
    frame: pd.DataFrame,
    *,
    system: str,
    row_mask: pd.Series,
    dt_hours: pd.Series,
    maximum_predicted_power_w: float | None = None,
) -> dict[str, Any]:
    """Return the all-reviewed-row energy-ratio factor for one season.

    Without a curtailment cap this is the direct measured-energy divided by
    uncalibrated-modeled-energy ratio. With a cap, solve the equivalent clipped
    energy equation so the reported measured and predicted totals still match.
    """

    measured = frame[f"{system}_measured_power_w"]
    uncalibrated = pd.to_numeric(
        frame[f"{system}_uncalibrated_power_w"], errors="coerce"
    ).replace([np.inf, -np.inf], np.nan)
    selected = row_mask.fillna(False).astype(bool)
    numeric_dt_hours = pd.to_numeric(dt_hours, errors="coerce").replace(
        [np.inf, -np.inf], np.nan
    )
    covered = selected & numeric_dt_hours.notna() & (numeric_dt_hours > 0.0)
    finite_modeled = uncalibrated.loc[selected].dropna()
    if bool((finite_modeled < 0.0).any()):
        raise ValueError(
            "Energy balancing requires non-negative uncalibrated model power."
        )

    target_kwh = _integrated_energy_kwh(
        measured,
        row_mask=selected,
        dt_hours=dt_hours,
    )
    unscaled_modeled_kwh = _integrated_energy_kwh(
        uncalibrated,
        row_mask=selected,
        dt_hours=dt_hours,
    )
    tolerance_kwh = max(1e-6, abs(target_kwh) * 1e-10)
    if target_kwh < -tolerance_kwh:
        raise ValueError(
            "Reviewed measured energy is negative; exclude the affected rows "
            "before calibration."
        )

    if abs(target_kwh) <= tolerance_kwh:
        final_factor = 0.0
    elif unscaled_modeled_kwh <= 0.0:
        raise ValueError(
            "Measured energy is positive but the physics model produced no "
            "energy for the reviewed rows. Calibration cannot reconcile this "
            "season."
        )
    elif maximum_predicted_power_w is None:
        final_factor = target_kwh / unscaled_modeled_kwh
    else:
        cap_w = float(maximum_predicted_power_w)
        if not np.isfinite(cap_w) or cap_w <= 0.0:
            raise ValueError(
                "The curtailment limit must be finite and positive during "
                "energy balancing."
            )
        positive_modeled = finite_modeled[finite_modeled > 0.0]
        if positive_modeled.empty:
            raise ValueError(
                "Measured energy is positive but the physics model produced no "
                "positive power for the reviewed rows."
            )
        maximum_factor = float((cap_w / positive_modeled).max())
        upper_factor = maximum_factor * (1.0 + 1e-12)
        maximum_kwh = _integrated_energy_kwh(
            uncalibrated,
            row_mask=selected,
            dt_hours=dt_hours,
            factor=upper_factor,
            maximum_power_w=cap_w,
        )
        if target_kwh > maximum_kwh + tolerance_kwh:
            raise ValueError(
                "Measured energy cannot be matched within the selected "
                f"{cap_w / 1_000.0:g} kW curtailment limit. Increase or disable "
                "the limit, or review the affected source rows."
            )
        if abs(target_kwh - maximum_kwh) <= tolerance_kwh:
            final_factor = upper_factor
        else:
            lower_factor = 0.0
            for _ in range(120):
                candidate = (lower_factor + upper_factor) / 2.0
                candidate_kwh = _integrated_energy_kwh(
                    uncalibrated,
                    row_mask=selected,
                    dt_hours=dt_hours,
                    factor=candidate,
                    maximum_power_w=cap_w,
                )
                if candidate_kwh < target_kwh:
                    lower_factor = candidate
                else:
                    upper_factor = candidate
            final_factor = (lower_factor + upper_factor) / 2.0

    predicted_kwh = _integrated_energy_kwh(
        uncalibrated,
        row_mask=selected,
        dt_hours=dt_hours,
        factor=final_factor,
        maximum_power_w=maximum_predicted_power_w,
    )
    residual_kwh = predicted_kwh - target_kwh
    if abs(residual_kwh) > tolerance_kwh:
        raise ValueError(
            "Calibration could not reconcile measured and predicted energy "
            f"within {tolerance_kwh:.6g} kWh."
        )

    return {
        "factor": float(final_factor),
        "sample_count": int(covered.sum()),
        "valid_hours": float(numeric_dt_hours.loc[covered].sum()),
        "measured_kwh": target_kwh,
        "uncalibrated_modeled_kwh": unscaled_modeled_kwh,
        "energy_balance_target_kwh": target_kwh,
        "energy_balance_predicted_kwh": predicted_kwh,
        "energy_balance_residual_kwh": residual_kwh,
        "energy_balance_scope": "all_reviewed_rows_in_season",
        "energy_balance_status": "balanced",
        "curtailment_aware": maximum_predicted_power_w is not None,
    }


def _confidence(
    sample_count: int,
    valid_hours: float,
    factor: float | None,
) -> str:
    if factor is None or not 0.25 <= factor <= 2.0:
        return "low"
    if sample_count >= 24 and valid_hours >= 72:
        return "high"
    if sample_count >= 12 and valid_hours >= 24:
        return "medium"
    return "low"


def _round_factor_observation(
    observation: Mapping[str, Any],
    *,
    source: str,
    fallback_reason: str | None = None,
) -> dict[str, Any]:
    factor = observation.get("factor")
    if factor is not None and not np.isfinite(float(factor)):
        factor = None
    sample_count = int(observation.get("sample_count") or 0)
    valid_hours = float(observation.get("valid_hours") or 0.0)
    result = {
        # This value is also the durable application input for scenario jobs.
        # Keep the exact float used above; presentation layers may round it.
        "factor": float(factor) if factor is not None else 1.0,
        "sample_count": sample_count,
        "valid_hours": round(valid_hours, 3)
        if np.isfinite(valid_hours)
        else None,
        "measured_kwh": round(
            float(observation.get("measured_kwh") or 0.0), 3
        )
        if np.isfinite(float(observation.get("measured_kwh") or 0.0))
        else None,
        "uncalibrated_modeled_kwh": round(
            float(observation.get("uncalibrated_modeled_kwh") or 0.0), 3
        )
        if np.isfinite(
            float(observation.get("uncalibrated_modeled_kwh") or 0.0)
        )
        else None,
        "source": source,
        "confidence": _confidence(
            sample_count,
            valid_hours,
            float(factor) if factor is not None else None,
        ),
        "fallback_reason": fallback_reason,
    }
    for key, digits in (
        ("energy_balance_target_kwh", 6),
        ("energy_balance_predicted_kwh", 6),
        ("energy_balance_residual_kwh", 9),
    ):
        if key not in observation:
            continue
        raw_value = observation.get(key)
        result[key] = (
            round(float(raw_value), digits)
            if raw_value is not None and np.isfinite(float(raw_value))
            else None
        )
    for key in (
        "energy_balance_scope",
        "energy_balance_status",
        "curtailment_aware",
    ):
        if key in observation:
            result[key] = observation.get(key)
    return result


def _driver_diagnostics(
    frame: pd.DataFrame,
    *,
    system: str,
    valid_mask: pd.Series,
) -> dict[str, Any]:
    """Fit a small diagnostic log-factor model using physical variables."""

    predicted = pd.to_numeric(
        frame[f"{system}_uncalibrated_power_w"], errors="coerce"
    )
    measured = pd.to_numeric(
        frame[f"{system}_measured_power_w"], errors="coerce"
    )
    feature_specs = (
        ("temp_air_c", "temperature"),
        ("wind_speed_ms", "wind speed"),
        ("ghi_wm2", "GHI"),
        ("dni_wm2", "DNI"),
        ("dhi_wm2", "DHI"),
    )
    data = pd.DataFrame(index=frame.index)
    for column, _ in feature_specs:
        if column in frame:
            data[column] = pd.to_numeric(frame[column], errors="coerce")
    elapsed_days = (
        frame.index.to_series() - frame.index[0]
    ).dt.total_seconds() / 86_400.0
    data["elapsed_days"] = elapsed_days.to_numpy()
    ratio = measured / predicted
    data["target"] = np.log(ratio.clip(lower=0.05, upper=3.0))
    selected = data.loc[
        valid_mask
        & np.isfinite(data["target"])
        & ratio.between(0.05, 3.0)
    ].copy()

    if len(selected) < 30:
        return {
            "status": "insufficient_data",
            "sample_count": int(len(selected)),
            "message": (
                "At least 30 comparable measured/model samples are needed for "
                "physical-driver diagnostics."
            ),
        }

    diagnostic_bounds = {
        "temp_air_c": (-40.0, 60.0),
        "wind_speed_ms": (-0.1, 50.0),
        "ghi_wm2": (-5.0, 1_400.0),
        "dni_wm2": (-5.0, 1_500.0),
        "dhi_wm2": (-5.0, 1_400.0),
    }
    candidate_columns = []
    for column in selected.columns:
        if column == "target":
            continue
        selected[column] = pd.to_numeric(
            selected[column], errors="coerce"
        ).where(np.isfinite(selected[column]))
        if column in diagnostic_bounds:
            lower, upper = diagnostic_bounds[column]
            selected[column] = selected[column].where(
                selected[column].between(lower, upper)
            )
        observed = selected[column].dropna()
        if (
            len(observed) / len(selected) >= 0.8
            and np.isfinite(float(observed.std(ddof=0)))
            and float(observed.std(ddof=0)) > 1e-9
        ):
            candidate_columns.append(column)
    if len(candidate_columns) < 2:
        return {
            "status": "insufficient_variation",
            "sample_count": int(len(selected)),
            "message": "The selected period does not vary enough for driver diagnostics.",
        }

    selected = selected[["target", *candidate_columns]].copy()
    for column in candidate_columns:
        selected[column] = selected[column].fillna(selected[column].median())

    standardized = []
    standard_deviations: dict[str, float] = {}
    for column in candidate_columns:
        values = selected[column].to_numpy(dtype=float)
        standard_deviation = float(np.std(values))
        if not np.isfinite(standard_deviation) or standard_deviation <= 1e-9:
            return {
                "status": "unavailable",
                "sample_count": int(len(selected)),
                "message": "Physical-driver inputs were numerically unstable.",
            }
        standard_deviations[column] = standard_deviation
        standardized.append((values - float(np.mean(values))) / standard_deviation)
    matrix = np.column_stack([np.ones(len(selected)), *standardized])
    target = selected["target"].to_numpy(dtype=float)
    if not np.isfinite(matrix).all() or not np.isfinite(target).all():
        return {
            "status": "unavailable",
            "sample_count": int(len(selected)),
            "message": "Physical-driver inputs contained non-finite values.",
        }
    try:
        coefficients, _, rank, singular_values = np.linalg.lstsq(
            matrix, target, rcond=None
        )
    except (np.linalg.LinAlgError, FloatingPointError, ValueError):
        return {
            "status": "unavailable",
            "sample_count": int(len(selected)),
            "message": "Physical-driver regression could not be estimated safely.",
        }
    condition_number = (
        float(singular_values[0] / singular_values[-1])
        if len(singular_values) and singular_values[-1] > 0
        else np.inf
    )
    if (
        int(rank) < matrix.shape[1]
        or not np.isfinite(condition_number)
        or condition_number > 1e8
        or not np.isfinite(coefficients).all()
    ):
        return {
            "status": "unavailable",
            "sample_count": int(len(selected)),
            "message": "Physical-driver inputs were too collinear for a stable estimate.",
        }
    fitted = matrix @ coefficients
    residual_sum = float(np.square(target - fitted).sum())
    total_sum = float(np.square(target - target.mean()).sum())
    r_squared = 1.0 - residual_sum / total_sum if total_sum > 0 else 0.0

    labels = {column: label for column, label in feature_specs}
    labels["elapsed_days"] = "time through selected range"
    drivers = []
    for column, coefficient in zip(
        candidate_columns, coefficients[1:], strict=True
    ):
        relative_effect = (
            np.expm1(np.clip(float(coefficient), -20.0, 20.0)) * 100.0
        )
        drivers.append(
            {
                "variable": column,
                "label": labels.get(column, column),
                "direction": "higher factor" if coefficient >= 0 else "lower factor",
                "standardized_coefficient": round(float(coefficient), 5),
                "factor_change_pct_per_standard_deviation": round(
                    float(relative_effect), 2
                ),
                "observed_standard_deviation": round(
                    standard_deviations[column], 4
                ),
            }
        )
    drivers.sort(
        key=lambda item: abs(item["standardized_coefficient"]), reverse=True
    )
    return {
        "status": "available",
        "sample_count": int(len(selected)),
        "r_squared": round(float(max(min(r_squared, 1.0), -1.0)), 4),
        "drivers": drivers[:4],
        "interpretation": (
            "Diagnostic association only; weather correlations do not prove "
            "causation. Soiling requires a dedicated sensor, rainfall, or "
            "maintenance record to separate it reliably."
        ),
    }


def _calibration_local_index(index: pd.Index) -> pd.DatetimeIndex:
    """Validate the model time axis and normalize it to local civil time."""

    if not isinstance(index, pd.DatetimeIndex):
        raise ValueError(
            "Seasonal calibration requires a pandas DatetimeIndex."
        )
    if index.hasnans:
        raise ValueError(
            "Seasonal calibration index cannot contain invalid timestamps."
        )
    if index.tz is None:
        raise ValueError(
            "Seasonal calibration requires a timezone-aware DatetimeIndex."
        )
    if not index.is_monotonic_increasing:
        raise ValueError(
            "Seasonal calibration requires timestamps in ascending order."
        )
    return index.tz_convert(LOCAL_TIMEZONE)


def apply_frozen_seasonal_calibration(
    frame: pd.DataFrame,
    *,
    calibration_profile: Mapping[str, Any],
) -> tuple[pd.DataFrame, dict[str, Any], dict[str, Any]]:
    """Apply an immutable baseline profile without fitting candidate data."""

    required = {
        "se_predicted_power_w",
        "sol_predicted_power_w",
    }
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise ValueError(
            "Frozen seasonal calibration is missing required model columns: "
            + ", ".join(missing)
        )
    if frame.empty:
        raise ValueError(
            "Frozen seasonal calibration requires at least one model row."
        )

    output = frame.copy()
    output.index = _calibration_local_index(output.index)
    season_labels = pd.Series(
        [season_name(value) for value in output.index],
        index=output.index,
        dtype="object",
    )
    ordered_seasons = list(dict.fromkeys(season_labels.tolist()))
    profile = validate_seasonal_calibration_profile(
        calibration_profile,
        required_seasons=ordered_seasons,
    )
    seasonal_factors = profile["seasonal_factors"]

    for system in ("se", "sol"):
        output[f"{system}_uncalibrated_power_w"] = pd.to_numeric(
            output[f"{system}_predicted_power_w"], errors="coerce"
        )
        output[f"{system}_calibration_factor"] = 1.0

    fit_evidence: dict[tuple[str, str], dict[str, Any]] = {}
    fit_metadata = profile.get("fit_metadata")
    if isinstance(fit_metadata, Mapping):
        for record in fit_metadata.get("seasons") or []:
            if not isinstance(record, Mapping):
                continue
            label = str(record.get("season") or "").strip().lower()
            systems = record.get("systems")
            if label not in SEASON_MONTHS or not isinstance(systems, Mapping):
                continue
            for system in ("solaredge", "solectria"):
                evidence = systems.get(system)
                if isinstance(evidence, Mapping):
                    fit_evidence[(label, system)] = deepcopy(dict(evidence))

    season_records: list[dict[str, Any]] = []
    for label in ordered_seasons:
        season_mask = season_labels == label
        record: dict[str, Any] = {
            "season": label,
            "months": SEASON_MONTHS[label],
            "first_timestamp": output.index[season_mask][0].isoformat(),
            "last_timestamp": output.index[season_mask][-1].isoformat(),
            "row_count": int(season_mask.sum()),
            "systems": {},
        }
        for system, public_system in (
            ("se", "solaredge"),
            ("sol", "solectria"),
        ):
            factor = seasonal_factors[label][public_system]
            factor_column = f"{system}_calibration_factor"
            output.loc[season_mask, factor_column] = factor
            output.loc[season_mask, f"{system}_predicted_power_w"] = (
                output.loc[
                    season_mask, f"{system}_uncalibrated_power_w"
                ]
                * factor
            )
            evidence = fit_evidence.get((label, public_system), {})
            fit_source = evidence.get("source")
            record["systems"][public_system] = {
                **evidence,
                "factor": factor,
                "source": "frozen_baseline_profile",
                "fit_source": fit_source,
            }
        season_records.append(record)

    calibration = {
        "method": "frozen_baseline_seasonal_factors",
        "application_mode": "frozen_baseline_profile",
        "profile_schema_version": profile["schema_version"],
        "origin_job_id": profile["origin_job_id"],
        "origin_source_sha256": profile["origin_source_sha256"],
        "origin_review_id": profile["origin_review_id"],
        "season_definition": (
            "meteorological: winter Dec-Feb, spring Mar-May, "
            "summer Jun-Aug, fall Sep-Nov"
        ),
        "applied_seasons": ordered_seasons,
        "seasons": season_records,
        "season_count": len(season_records),
        "warnings": [],
        "fit_metadata": deepcopy(dict(fit_metadata))
        if isinstance(fit_metadata, Mapping)
        else {},
    }
    raw_diagnostics = profile.get("factor_driver_diagnostics")
    diagnostics = (
        deepcopy(dict(raw_diagnostics))
        if isinstance(raw_diagnostics, Mapping)
        else {}
    )
    diagnostics.update(
        {
            "application_mode": "frozen_baseline_profile",
            "applied_to_prediction": False,
            "origin_job_id": profile["origin_job_id"],
            "origin_review_id": profile["origin_review_id"],
        }
    )
    return output, calibration, diagnostics


def apply_seasonal_calibration(
    frame: pd.DataFrame,
    *,
    minimum_season_samples: int = 6,
    minimum_season_hours: float = 1.0,
    expected_interval_seconds: int | None = None,
    maximum_uncurtailed_power_w: float | None = None,
) -> tuple[pd.DataFrame, dict[str, Any], dict[str, Any]]:
    """Calculate and apply per-season, per-system all-row energy factors.

    ``minimum_season_samples`` and ``minimum_season_hours`` remain accepted for
    compatibility with older callers. They no longer filter or replace a
    seasonal factor: every reviewed row in each season contributes.
    """

    required = {
        "se_measured_power_w",
        "sol_measured_power_w",
        "se_predicted_power_w",
        "sol_predicted_power_w",
    }
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise ValueError(
            "Seasonal calibration is missing required model columns: "
            + ", ".join(missing)
        )
    if frame.empty:
        raise ValueError("Seasonal calibration requires at least one model row.")

    output = frame.copy()
    output.index = _calibration_local_index(output.index)
    for system in ("se", "sol"):
        output[f"{system}_uncalibrated_power_w"] = pd.to_numeric(
            output[f"{system}_predicted_power_w"], errors="coerce"
        )

    dt_hours = _bounded_interval_hours(
        output.index,
        expected_interval_seconds=expected_interval_seconds,
    )
    all_rows = pd.Series(True, index=output.index)

    season_labels = pd.Series(
        [season_name(value) for value in output.index],
        index=output.index,
        dtype="object",
    )
    ordered_seasons = list(dict.fromkeys(season_labels.tolist()))
    warnings: list[str] = []
    season_records: list[dict[str, Any]] = []
    diagnostics: dict[str, Any] = {}

    for system in ("se", "sol"):
        diagnostics[system] = _driver_diagnostics(
            output,
            system=system,
            valid_mask=all_rows,
        )

    for label in ordered_seasons:
        season_mask = season_labels == label
        record: dict[str, Any] = {
            "season": label,
            "months": SEASON_MONTHS[label],
            "first_timestamp": output.index[season_mask][0].isoformat(),
            "last_timestamp": output.index[season_mask][-1].isoformat(),
            "row_count": int(season_mask.sum()),
            "systems": {},
        }
        for system in ("se", "sol"):
            balance = _energy_balance_observation(
                output,
                system=system,
                row_mask=season_mask,
                dt_hours=dt_hours,
                maximum_predicted_power_w=maximum_uncurtailed_power_w,
            )
            factor = float(balance["factor"])
            if factor < 0.5 or factor > 1.5:
                warnings.append(
                    f"{label.title()} {system.upper()} applied factor {factor:.3f} is "
                    "outside the typical 0.5-1.5 review range."
                )

            factor_column = f"{system}_calibration_factor"
            if factor_column not in output:
                output[factor_column] = 1.0
            output.loc[season_mask, factor_column] = factor
            output.loc[season_mask, f"{system}_predicted_power_w"] = (
                output.loc[
                    season_mask, f"{system}_uncalibrated_power_w"
                ]
                * factor
            )
            record["systems"][
                "solaredge" if system == "se" else "solectria"
            ] = _round_factor_observation(
                balance,
                source="all_reviewed_rows_in_season",
            )
        season_records.append(record)

    calibration = {
        "method": "measured_energy_divided_by_uncalibrated_modeled_energy",
        "application_method": "curtailment_aware_all_reviewed_row_energy_ratio",
        "energy_balance_scope": "all reviewed rows, independently by season and system",
        "season_definition": "meteorological: winter Dec-Feb, spring Mar-May, summer Jun-Aug, fall Sep-Nov",
        "seasons": season_records,
        "season_count": len(season_records),
        "warnings": warnings,
    }
    driver_diagnostics = {
        "method": "diagnostic log-factor regression on standardized physical variables",
        "applied_to_prediction": False,
        "systems": {
            "solaredge": diagnostics["se"],
            "solectria": diagnostics["sol"],
        },
    }
    return output, calibration, driver_diagnostics
