"""Download MIDC STAC data and save model-interval averages as a CSV file."""

from __future__ import annotations

import io
import os
import re
import sys
import tempfile
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd
from pandas.errors import EmptyDataError, ParserError

from sbepv.paths import discover_project_root


API_URL = "https://midcdmz.nlr.gov/apps/data_api.pl"
SITE = "STAC"
FIRST_AVAILABLE_DATE = date(2011, 2, 11)
REFERENCE_URL = (
    "https://midcdmz.nlr.gov/apps/daily.pl?"
    "site=STAC&start=20110211&yr=2026&mo=7&dy=12"
)
REQUEST_TIMEOUT_SECONDS = 120
MISSING_SENTINEL_MAX = -6000

DATE_COLUMN = "DATE (MM/DD/YYYY)"
HOUR_COLUMN = "HOUR-MST"
MINUTE_COLUMN = "MINUTE-MST"

MEASUREMENT_COLUMNS = {
    "Global Horizontal [W/m^2]": "Avg Global Horizontal [W/m^2]",
    "Direct Normal [W/m^2]": "Avg Direct Normal [W/m^2]",
    "Diffuse Horizontal [W/m^2]": "Avg Diffuse Horizontal [W/m^2]",
    "Air Temperature [deg C]": "Avg Air Temperature [deg C]",
    "Avg Wind Speed @ 10m [m/s]": "Avg Avg Wind Speed @ 10m [m/s]",
}
RAW_REQUIRED_COLUMNS = ["Year", "DOY", "MST", *MEASUREMENT_COLUMNS]
MAX_CHUNK_DAYS = 366


class MidcError(Exception):
    """A user-facing error that prevents creation of the output CSV."""


@dataclass
class MidcFetchResult:
    """Aggregated MIDC data plus source-quality metadata for a completed fetch."""

    hourly: pd.DataFrame
    raw_rows: int
    data_request_count: int
    dropped_timestamp_rows: int
    missing_value_count: int
    affected_interval_count: int
    interval_seconds: int = 3_600
    partial_interval_count: int = 0
    unavailable_interval_count: int = 0

    @property
    def chunk_count(self) -> int:
        """Backward-compatible internal alias for older callers and fixtures."""
        return self.data_request_count

    @property
    def affected_hour_count(self) -> int:
        """Backward-compatible alias retained for hourly-only callers."""
        return self.affected_interval_count

    @property
    def interval_data(self) -> pd.DataFrame:
        """Return model-ready rows; ``hourly`` remains for API compatibility."""
        return self.hourly

    @property
    def warnings(self) -> list[str]:
        messages: list[str] = []
        if self.dropped_timestamp_rows:
            messages.append(
                f"Ignored {self.dropped_timestamp_rows} source row(s) with invalid "
                "date/time values."
            )
        if self.missing_value_count:
            if self.interval_seconds == 3_600:
                interval_label = "hourly"
            elif self.interval_seconds < 3_600:
                interval_label = f"{self.interval_seconds // 60}-minute interval"
            else:
                interval_label = f"{self.interval_seconds // 3_600}-hour interval"
            messages.append(
                f"Left {self.missing_value_count} {interval_label} measurement value(s) blank "
                f"across {self.affected_interval_count} interval(s) because no valid source "
                "readings were available."
            )
        if self.partial_interval_count:
            messages.append(
                f"Averaged available readings in {self.partial_interval_count} "
                "interval(s) that contained fewer than the expected one-minute "
                "MIDC source samples."
            )
        if self.unavailable_interval_count:
            messages.append(
                f"Omitted {self.unavailable_interval_count} interval(s) with no "
                "available MIDC weather readings; no zero-generation or weather "
                "proxy was used."
            )
        return messages


def parse_user_date(value: str, label: str) -> date:
    """Parse an exactly formatted MM/DD/YYYY date."""
    cleaned = value.strip()
    if not re.fullmatch(r"\d{2}/\d{2}/\d{4}", cleaned):
        raise MidcError(f"{label} date must use MM/DD/YYYY (for example, 07/12/2026).")

    try:
        return datetime.strptime(cleaned, "%m/%d/%Y").date()
    except ValueError as exc:
        raise MidcError(f"{label} date is not a valid calendar date: {cleaned}.") from exc


def build_api_url(start_date: date, end_date: date) -> str:
    """Build the MIDC API URL for an inclusive date range."""
    query = urlencode(
        {
            "site": SITE,
            "begin": start_date.strftime("%Y%m%d"),
            "end": end_date.strftime("%Y%m%d"),
        }
    )
    return f"{API_URL}?{query}"


def download_api_csv(start_date: date, end_date: date) -> str:
    """Download and decode the raw minute-level CSV returned by MIDC."""
    request = Request(
        build_api_url(start_date, end_date),
        headers={"User-Agent": "midc-stac-hourly/1.0"},
    )

    try:
        with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            payload = response.read()
    except HTTPError as exc:
        raise MidcError(f"MIDC API returned HTTP {exc.code}: {exc.reason}.") from exc
    except URLError as exc:
        reason = getattr(exc, "reason", exc)
        raise MidcError(f"Could not connect to the MIDC API: {reason}.") from exc
    except (TimeoutError, OSError) as exc:
        raise MidcError(f"MIDC API request failed: {exc}.") from exc

    if not payload.strip():
        raise MidcError("MIDC API returned an empty response.")

    try:
        return payload.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise MidcError("MIDC API returned data that was not valid UTF-8 CSV.") from exc


def _parse_source_dates(frame: pd.DataFrame) -> pd.Series:
    """Convert the API Year and day-of-year fields into normalized dates."""
    years = pd.to_numeric(frame["Year"], errors="coerce")
    days = pd.to_numeric(frame["DOY"], errors="coerce")

    integer_years = years.where(years.mod(1).eq(0)).astype("Int64").astype("string")
    integer_days = days.where(days.mod(1).eq(0)).astype("Int64").astype("string")
    date_codes = integer_years + integer_days.str.zfill(3)

    return pd.to_datetime(date_codes, format="%Y%j", errors="coerce").dt.normalize()


def parse_api_csv(csv_text: str) -> pd.DataFrame:
    """Parse one MIDC API response and retain only annual-model source fields."""
    try:
        source = pd.read_csv(io.StringIO(csv_text))
    except (EmptyDataError, ParserError, UnicodeError, ValueError) as exc:
        raise MidcError(f"Could not parse the MIDC CSV response: {exc}.") from exc

    source.columns = source.columns.map(str).str.strip()
    missing_columns = sorted(set(RAW_REQUIRED_COLUMNS).difference(source.columns))
    if missing_columns:
        raise MidcError(
            "MIDC API response is missing required columns: "
            + ", ".join(missing_columns)
            + "."
        )
    if source.empty:
        raise MidcError("MIDC API returned column headers but no data rows.")
    return source.loc[:, RAW_REQUIRED_COLUMNS].copy()


def _missing_begin_date(csv_text: str) -> date | None:
    """Return the unavailable begin date from a known MIDC error document.

    MIDC reports a missing daily source file as a small HTML/text response with
    HTTP 200.  Keep this recognizer deliberately narrow so a malformed CSV or a
    different server error is never mistaken for an ordinary coverage gap.
    """

    match = re.search(
        r"(?:Unable\s+to\s+open\s+|No\s+data\s+found\s+for\s+begin\s+date\s+of\s+)"
        r"(\d{8})(?:\.TXT)?",
        csv_text,
        flags=re.IGNORECASE,
    )
    if match is None:
        return None
    try:
        return datetime.strptime(match.group(1), "%Y%m%d").date()
    except ValueError:
        return None


def _suggested_available_dates(csv_text: str) -> list[date]:
    """Extract human-readable closest-date links from a MIDC error document."""

    candidates: set[date] = set()
    for month, day, year in re.findall(r"\b(\d{2})/(\d{2})/(\d{4})\b", csv_text):
        try:
            candidates.add(date(int(year), int(month), int(day)))
        except ValueError:
            continue
    return sorted(candidates)


def _download_chunk_with_leading_gap_recovery(
    start_date: date,
    end_date: date,
) -> tuple[pd.DataFrame, int]:
    """Download one chunk, advancing past unavailable leading source days.

    A request beginning inside the STAC outage spanning late 2022/early 2023
    returns an HTTP-200 error document instead of the later rows that do exist.
    Retry at the next server-suggested date (or the next day when the suggestion
    is only a prior date).  Aggregation still uses the original requested bounds,
    so skipped intervals remain explicit all-null coverage rows rather than being
    synthesized from zero generation or a weather proxy.
    """

    cursor = start_date
    request_count = 0
    while cursor <= end_date:
        csv_text = download_api_csv(cursor, end_date)
        request_count += 1
        try:
            return parse_api_csv(csv_text), request_count
        except MidcError:
            missing_date = _missing_begin_date(csv_text)
            if missing_date != cursor:
                raise
            later_suggestions = [
                candidate
                for candidate in _suggested_available_dates(csv_text)
                if cursor < candidate <= end_date
            ]
            cursor = (
                later_suggestions[0]
                if later_suggestions
                else cursor + timedelta(days=1)
            )
    # An entire trailing chunk can fall inside a source outage.  Return an empty
    # schema-compatible frame so the caller can preserve that chunk as explicit
    # unavailable coverage when another chunk did contain usable source rows.
    return pd.DataFrame(columns=RAW_REQUIRED_COLUMNS), request_count


def _validated_interval_seconds(interval_seconds: int) -> int:
    """Return a supported interval aligned to the MIDC one-minute source."""
    try:
        seconds = int(interval_seconds)
    except (TypeError, ValueError, OverflowError) as exc:
        raise MidcError(
            "MIDC aggregation interval must be a supported whole-minute value."
        ) from exc
    if seconds < 60 or seconds > 86_400 or seconds % 60 or 86_400 % seconds:
        raise MidcError(
            "MIDC aggregation interval must be at least 1 minute and divide "
            "evenly into one day."
        )
    return seconds


def aggregate_interval_frame(
    source: pd.DataFrame,
    start_date: date,
    end_date: date,
    interval_seconds: int,
) -> tuple[pd.DataFrame, int, int, int]:
    """Calculate right-closed interval means from parsed minute-level rows.

    Hourly/coarser files preserve the reference integer-hour right edge. A
    two-hour day is therefore labeled 1, 3, ..., 23, while the one-hour form
    remains 0, 1, ..., 23. Sub-hour files add ``MINUTE-MST`` and use right-edge
    labels such as 00:00, 00:15, ..., 23:45. Source rows immediately before
    ``start_date`` are retained because they belong to the first interval.
    """
    seconds = _validated_interval_seconds(interval_seconds)
    if start_date > end_date:
        raise MidcError("Start date must be on or before end date.")
    source = source.copy()
    source.columns = source.columns.map(str).str.strip()
    missing_columns = sorted(set(RAW_REQUIRED_COLUMNS).difference(source.columns))
    if missing_columns:
        raise MidcError(
            "MIDC source data is missing required columns: "
            + ", ".join(missing_columns)
            + "."
        )
    if source.empty:
        raise MidcError("MIDC API returned no data rows.")

    source_dates = _parse_source_dates(source)
    mst_values = pd.to_numeric(source["MST"], errors="coerce")
    integer_mst = mst_values.where(mst_values.mod(1).eq(0))
    source_hours = integer_mst.floordiv(100)
    source_minutes = integer_mst.mod(100)

    valid_timestamps = (
        source_dates.notna()
        & source_hours.between(0, 23)
        & source_minutes.between(0, 59)
    )
    dropped_timestamp_rows = int((~valid_timestamps).sum())

    # Preserve the reference file's right-edge convention. For example, an
    # hourly label of 1 contains 00:01-01:00; coarser intervals keep the final
    # hour label in each within-day interval.
    source_timestamps = (
        source_dates
        + pd.to_timedelta(source_hours, unit="h")
        + pd.to_timedelta(source_minutes, unit="m")
    )

    working = pd.DataFrame({"_timestamp": source_timestamps})
    for column in MEASUREMENT_COLUMNS:
        values = pd.to_numeric(source[column], errors="coerce")
        working[column] = values.mask(values <= MISSING_SENTINEL_MAX)

    interval = pd.Timedelta(seconds=seconds)
    label_offset = max(interval - pd.Timedelta(hours=1), pd.Timedelta(0))
    first_label = pd.Timestamp(start_date) + label_offset
    last_label = (
        pd.Timestamp(end_date)
        + pd.Timedelta(days=1)
        - interval
        + label_offset
    )
    first_interval_left = first_label - interval
    requested_range = source_timestamps.gt(first_interval_left) & source_timestamps.le(
        last_label
    )
    working = working.loc[valid_timestamps & requested_range].copy()
    if working.empty:
        raise MidcError("MIDC API returned no valid data rows for the requested date range.")

    grouped = (
        working.set_index("_timestamp")[list(MEASUREMENT_COLUMNS)]
        .resample(
            f"{seconds}s",
            closed="right",
            label="right",
            origin=pd.Timestamp(start_date),
            offset=label_offset,
        )
        .mean()
    )

    full_index = pd.date_range(
        start=first_label,
        end=last_label,
        freq=interval,
        name="_timestamp",
    )
    valid_sample_counts = (
        working.set_index("_timestamp")[list(MEASUREMENT_COLUMNS)]
        .notna()
        .groupby(level=0)
        .any()
        .resample(
            f"{seconds}s",
            closed="right",
            label="right",
            origin=pd.Timestamp(start_date),
            offset=label_offset,
        )
        .sum()
        .reindex(full_index, fill_value=0)
    )
    expected_samples_per_interval = seconds // 60
    partial_interval_count = int(
        (
            valid_sample_counts.gt(0)
            & valid_sample_counts.lt(expected_samples_per_interval)
        ).any(axis=1).sum()
    )
    unavailable_interval_count = int(valid_sample_counts.eq(0).all(axis=1).sum())
    intervals = grouped.reindex(full_index)
    missing_value_count = int(intervals.isna().sum().sum())
    affected_interval_count = int(intervals.isna().any(axis=1).sum())

    intervals = intervals.rename(columns=MEASUREMENT_COLUMNS).reset_index()
    intervals[DATE_COLUMN] = intervals["_timestamp"].dt.strftime("%m/%d/%Y")
    intervals[HOUR_COLUMN] = intervals["_timestamp"].dt.hour.astype(int)
    include_minute = seconds % 3_600 != 0
    if include_minute:
        intervals[MINUTE_COLUMN] = intervals["_timestamp"].dt.minute.astype(int)

    output_columns = [DATE_COLUMN, HOUR_COLUMN]
    if include_minute:
        output_columns.append(MINUTE_COLUMN)
    output_columns.extend(MEASUREMENT_COLUMNS.values())
    output = intervals.loc[:, output_columns]
    output.loc[:, list(MEASUREMENT_COLUMNS.values())] = output.loc[
        :, list(MEASUREMENT_COLUMNS.values())
    ].round(4)
    output.attrs["partial_interval_count"] = partial_interval_count
    output.attrs["unavailable_interval_count"] = unavailable_interval_count
    output.attrs["expected_samples_per_interval"] = expected_samples_per_interval
    return output, dropped_timestamp_rows, missing_value_count, affected_interval_count


def aggregate_hourly_frame(
    source: pd.DataFrame, start_date: date, end_date: date
) -> tuple[pd.DataFrame, int, int, int]:
    """Calculate reference-hour means from parsed minute-level API rows."""
    return aggregate_interval_frame(source, start_date, end_date, 3_600)


def aggregate_hourly(
    csv_text: str, start_date: date, end_date: date
) -> tuple[pd.DataFrame, int, int, int]:
    """Calculate right-closed hourly means matching the reference CSV."""
    return aggregate_hourly_frame(parse_api_csv(csv_text), start_date, end_date)


def aggregate_interval(
    csv_text: str,
    start_date: date,
    end_date: date,
    interval_seconds: int,
) -> tuple[pd.DataFrame, int, int, int]:
    """Calculate a supported right-closed annual interval from MIDC CSV text."""
    return aggregate_interval_frame(
        parse_api_csv(csv_text), start_date, end_date, interval_seconds
    )


def _date_chunks(
    start_date: date, end_date: date, chunk_days: int
) -> list[tuple[date, date]]:
    if start_date > end_date:
        raise MidcError("Start date must be on or before end date.")
    if chunk_days <= 0:
        raise MidcError("MIDC data request size must be positive.")

    chunks: list[tuple[date, date]] = []
    cursor = start_date
    while cursor <= end_date:
        chunk_end = min(cursor + timedelta(days=chunk_days - 1), end_date)
        chunks.append((cursor, chunk_end))
        cursor = chunk_end + timedelta(days=1)
    return chunks


def fetch_interval_data(
    start_date: date,
    end_date: date,
    interval_seconds: int,
    progress_cb: Callable[[float, str], None] | None = None,
    chunk_days: int = MAX_CHUNK_DAYS,
) -> MidcFetchResult:
    """Download any date range plus its first-bin boundary, then aggregate once."""
    seconds = _validated_interval_seconds(interval_seconds)
    if start_date > end_date:
        raise MidcError("Start date must be on or before end date.")
    if start_date < FIRST_AVAILABLE_DATE:
        raise MidcError(
            f"MIDC STAC data begins on {FIRST_AVAILABLE_DATE:%m/%d/%Y}."
        )
    # Hour 0 is right-labeled and contains 23:01-00:00, so one prior source day
    # is required to make the first requested interval as complete as all others.
    source_start_date = max(start_date - timedelta(days=1), FIRST_AVAILABLE_DATE)
    chunks = _date_chunks(source_start_date, end_date, chunk_days)
    parsed_chunks: list[pd.DataFrame] = []
    data_request_count = 0
    for index, (chunk_start, chunk_end) in enumerate(chunks, start=1):
        if progress_cb:
            progress_cb(
                (index - 1) / len(chunks) * 0.85,
                f"Downloading MIDC data {index}/{len(chunks)} "
                f"({chunk_start:%m/%d/%Y}-{chunk_end:%m/%d/%Y})...",
            )
        parsed_chunk, chunk_request_count = _download_chunk_with_leading_gap_recovery(
            chunk_start,
            chunk_end,
        )
        if not parsed_chunk.empty:
            parsed_chunks.append(parsed_chunk)
        data_request_count += chunk_request_count

    if not parsed_chunks:
        raise MidcError(
            "MIDC API returned no available source data for the requested date range."
        )
    source = pd.concat(parsed_chunks, ignore_index=True)
    if progress_cb:
        interval_label = (
            f"{seconds // 60}-minute"
            if seconds < 3_600
            else f"{seconds // 3_600}-hour"
        )
        progress_cb(
            0.9,
            f"Aggregating MIDC data into {interval_label} intervals...",
        )
    interval_data, dropped, missing, affected = aggregate_interval_frame(
        source, start_date, end_date, seconds
    )
    partial = int(interval_data.attrs.get("partial_interval_count", 0))
    unavailable = int(interval_data.attrs.get("unavailable_interval_count", 0))
    if progress_cb:
        progress_cb(1.0, "MIDC interval data ready")
    return MidcFetchResult(
        hourly=interval_data,
        raw_rows=int(len(source)),
        data_request_count=data_request_count,
        dropped_timestamp_rows=dropped,
        missing_value_count=missing,
        affected_interval_count=affected,
        interval_seconds=seconds,
        partial_interval_count=partial,
        unavailable_interval_count=unavailable,
    )


def fetch_hourly_data(
    start_date: date,
    end_date: date,
    progress_cb: Callable[[float, str], None] | None = None,
    chunk_days: int = MAX_CHUNK_DAYS,
    interval_seconds: int = 3_600,
) -> MidcFetchResult:
    """Download MIDC data; hourly remains the backwards-compatible default."""
    return fetch_interval_data(
        start_date,
        end_date,
        interval_seconds,
        progress_cb=progress_cb,
        chunk_days=chunk_days,
    )


def output_path_for(start_date: date, end_date: date) -> Path:
    """Return the deterministic output location at the repository root."""
    filename = (
        f"MIDC_STAC_hourly_{start_date:%Y%m%d}_to_{end_date:%Y%m%d}.csv"
    )
    return discover_project_root(Path(__file__)) / filename


def write_csv_atomically(frame: pd.DataFrame, output_path: Path) -> None:
    """Write a complete CSV before replacing any existing output file."""
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            delete=False,
            dir=output_path.parent,
            prefix=f".{output_path.name}.",
            suffix=".tmp",
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            frame.to_csv(
                temporary_file,
                index=False,
                na_rep="",
                float_format="%.4f",
                lineterminator="\n",
            )

        os.replace(temporary_path, output_path)
        temporary_path = None
    except Exception as exc:
        raise MidcError(f"Could not save the output CSV: {exc}.") from exc
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass


def main() -> int:
    """Run the interactive command-line workflow."""
    try:
        start_date = parse_user_date(
            input("Start date (MM/DD/YYYY): "), "Start"
        )
        end_date = parse_user_date(input("End date (MM/DD/YYYY): "), "End")

        if start_date > end_date:
            raise MidcError("Start date must be on or before end date.")

        print(
            f"Fetching MIDC {SITE} data from {start_date:%m/%d/%Y} "
            f"through {end_date:%m/%d/%Y}..."
        )
        result = fetch_hourly_data(start_date, end_date)
        for warning in result.warnings:
            print(f"Warning: {warning}", file=sys.stderr)

        output_path = output_path_for(start_date, end_date)
        write_csv_atomically(result.hourly, output_path)
        print(f"Saved {len(result.hourly)} hourly rows to: {output_path}")
        return 0
    except (EOFError, KeyboardInterrupt):
        print("\nError: Input cancelled.", file=sys.stderr)
        return 1
    except MidcError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
