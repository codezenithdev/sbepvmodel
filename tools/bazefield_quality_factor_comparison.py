"""Quality-gating helpers for the Bazefield factor-comparison utility.

The repository's regression tests and ad-hoc analysis workflow share these
small, deterministic helpers.  They deliberately require one finite sample for
every modeled column before a timestamp can enter a comparison.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Mapping
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import sys
from typing import Any
from uuid import uuid4


def _repository_root(start: Path) -> Path:
    for candidate in (start, *start.parents):
        if (candidate / "pyproject.toml").is_file() and (
            candidate / "src" / "sbepv"
        ).is_dir():
            return candidate
    raise RuntimeError("Could not locate the sbepv repository root.")


REPO_ROOT = _repository_root(Path(__file__).resolve().parent)
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from sbepv.ingest import bazefield
PRIMARY_QUALITY_MASK = 0xC0
PRIMARY_GOOD = 0xC0
PRIMARY_UNCERTAIN = 0x40
PRIMARY_BAD = 0x00

ALL_COLUMNS = tuple(column for _, _, column in bazefield.COLUMN_MAP)
WEATHER_COLUMNS = ("dni", "ghi", "dhi", "temp_air", "wind_speed")
POWER_COLUMNS = {
    "solaredge": "solaredge_measured_power",
    "solectria": "solectria_measured_power",
}
COLUMN_BY_POINT = {
    (object_id, point_name): column
    for object_id, point_name, column in bazefield.COLUMN_MAP
}
DOMAIN_BOUNDS = {
    "solaredge_measured_power": (-1.0, 200_000.0),
    "solectria_measured_power": (-1.0, 200_000.0),
    "dni": (-5.0, 1_500.0),
    "ghi": (-5.0, 1_400.0),
    "dhi": (-5.0, 1_400.0),
    "temp_air": (-40.0, 60.0),
    "wind_speed": (-0.1, 50.0),
}


def _quality_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(numeric) or not numeric.is_integer():
        return None
    return int(numeric)


def primary_quality(value: Any) -> int | None:
    numeric = _quality_int(value)
    return None if numeric is None else numeric & PRIMARY_QUALITY_MASK


def primary_quality_label(value: Any) -> str:
    decoded = primary_quality(value)
    if decoded == PRIMARY_GOOD:
        return "good"
    if decoded == PRIMARY_UNCERTAIN:
        return "uncertain"
    if decoded == PRIMARY_BAD:
        return "bad"
    return "unknown"


def is_literal_quality_one(value: Any) -> bool:
    return _quality_int(value) == 1


def is_primary_good(value: Any) -> bool:
    return primary_quality(value) == PRIMARY_GOOD


def _finite_number(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError, OverflowError):
        return False


def _expected_grid(start_ms: int, end_ms: int, interval_seconds: int) -> set[int]:
    step_ms = int(interval_seconds) * 1_000
    if step_ms <= 0 or end_ms <= start_ms:
        raise ValueError(
            "The interval and end-exclusive time window must be positive."
        )
    if (end_ms - start_ms) % step_ms:
        raise ValueError("The requested time window is not aligned to the interval.")
    return set(range(start_ms, end_ms, step_ms))


def index_samples(
    flat_rows: Iterable[Mapping[str, Any]],
    *,
    start_ms: int,
    end_ms: int,
    interval_seconds: int,
) -> tuple[dict[int, dict[str, list[Mapping[str, Any]]]], dict[str, Any]]:
    expected = _expected_grid(start_ms, end_ms, interval_seconds)
    step_ms = int(interval_seconds) * 1_000
    buckets: defaultdict[int, defaultdict[str, list[Mapping[str, Any]]]] = (
        defaultdict(lambda: defaultdict(list))
    )
    ignored_series = invalid_timestamps = outside_window = off_grid = 0

    for sample in flat_rows:
        column = COLUMN_BY_POINT.get(
            (sample.get("objectId"), sample.get("pointName"))
        )
        if column is None:
            ignored_series += 1
            continue
        try:
            timestamp_ms = int(sample.get("t_ms"))
        except (TypeError, ValueError, OverflowError):
            invalid_timestamps += 1
            continue
        if not start_ms <= timestamp_ms < end_ms:
            outside_window += 1
            continue
        if (timestamp_ms - start_ms) % step_ms:
            off_grid += 1
            continue
        buckets[timestamp_ms][column].append(sample)

    duplicate_keys = sum(
        1
        for columns in buckets.values()
        for samples in columns.values()
        if len(samples) > 1
    )
    observed = set(buckets)
    diagnostics = {
        "expected_timestamp_count": len(expected),
        "observed_timestamp_count": len(observed),
        "missing_timestamp_count": len(expected - observed),
        "unexpected_timestamp_count": len(observed - expected),
        "duplicate_sample_key_count": duplicate_keys,
        "invalid_timestamp_sample_count": invalid_timestamps,
        "outside_window_sample_count": outside_window,
        "off_grid_sample_count": off_grid,
        "ignored_unmapped_sample_count": ignored_series,
    }
    return {
        timestamp_ms: dict(columns)
        for timestamp_ms, columns in buckets.items()
    }, diagnostics


def eligible_timestamps(
    buckets: Mapping[int, Mapping[str, list[Mapping[str, Any]]]],
    *,
    required_quality_columns: Iterable[str],
    quality_rule: Callable[[Any], bool],
) -> tuple[set[int], dict[str, int]]:
    required_quality = set(required_quality_columns)
    accepted: set[int] = set()
    rejection_counts: Counter[str] = Counter()
    for timestamp_ms, columns in buckets.items():
        if any(len(columns.get(column, [])) != 1 for column in ALL_COLUMNS):
            rejection_counts["missing_or_duplicate_sample"] += 1
            continue
        samples = {column: columns[column][0] for column in ALL_COLUMNS}
        if any(not _finite_number(sample.get("value")) for sample in samples.values()):
            rejection_counts["nonfinite_value"] += 1
            continue
        if any(
            not quality_rule(samples[column].get("quality"))
            for column in required_quality
        ):
            rejection_counts["quality_rule_failed"] += 1
            continue
        accepted.add(timestamp_ms)
    return accepted, dict(sorted(rejection_counts.items()))


def wide_rows(
    buckets: Mapping[int, Mapping[str, list[Mapping[str, Any]]]],
    timestamps_ms: Iterable[int],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for timestamp_ms in sorted(set(timestamps_ms)):
        columns = buckets[timestamp_ms]
        row: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(
                timestamp_ms / 1_000.0, tz=timezone.utc
            ).strftime("%Y-%m-%d %H:%M:%S")
        }
        for column in ALL_COLUMNS:
            value = float(columns[column][0]["value"])
            if column in bazefield.KW_TO_W_COLUMNS:
                value *= 1_000.0
            row[column] = round(value, bazefield.ROUND_DECIMALS)
        rows.append(row)
    return rows


def domain_bound_violations(
    buckets: Mapping[int, Mapping[str, list[Mapping[str, Any]]]],
    timestamps_ms: Iterable[int],
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for column, (lower, upper) in DOMAIN_BOUNDS.items():
        violations: list[tuple[int, float]] = []
        for timestamp_ms in sorted(set(timestamps_ms)):
            samples = buckets.get(timestamp_ms, {}).get(column, [])
            if len(samples) != 1 or not _finite_number(samples[0].get("value")):
                continue
            value = float(samples[0]["value"])
            if column in bazefield.KW_TO_W_COLUMNS:
                value *= 1_000.0
            if value < lower or value > upper:
                violations.append((timestamp_ms, value))
        if not violations:
            continue
        result[column] = {
            "row_count": len(violations),
            "allowed_minimum": lower,
            "allowed_maximum": upper,
            "minimum_observed": min(value for _, value in violations),
            "maximum_observed": max(value for _, value in violations),
            "sample_timestamps_utc": [
                datetime.fromtimestamp(timestamp_ms / 1_000.0, tz=timezone.utc).isoformat()
                for timestamp_ms, _ in violations[:8]
            ],
        }
    return result


@contextmanager
def temporary_working_csv() -> Iterable[Path]:
    path = REPO_ROOT / "analysis" / f".bazefield-quality-{uuid4().hex}.csv"
    try:
        yield path
    finally:
        path.unlink(missing_ok=True)


__all__ = [
    "ALL_COLUMNS",
    "DOMAIN_BOUNDS",
    "POWER_COLUMNS",
    "WEATHER_COLUMNS",
    "domain_bound_violations",
    "eligible_timestamps",
    "index_samples",
    "is_literal_quality_one",
    "is_primary_good",
    "primary_quality",
    "primary_quality_label",
    "temporary_working_csv",
    "wide_rows",
]
