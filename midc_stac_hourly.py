"""Download MIDC STAC data and save hourly averages as a CSV file."""

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


API_URL = "https://midcdmz.nlr.gov/apps/data_api.pl"
SITE = "STAC"
REQUEST_TIMEOUT_SECONDS = 120
MISSING_SENTINEL_MAX = -6000

DATE_COLUMN = "DATE (MM/DD/YYYY)"
HOUR_COLUMN = "HOUR-MST"

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
    """Hourly MIDC data plus source-quality metadata for a completed fetch."""

    hourly: pd.DataFrame
    raw_rows: int
    chunk_count: int
    dropped_timestamp_rows: int
    missing_value_count: int
    affected_hour_count: int

    @property
    def warnings(self) -> list[str]:
        messages: list[str] = []
        if self.dropped_timestamp_rows:
            messages.append(
                f"Ignored {self.dropped_timestamp_rows} source row(s) with invalid "
                "date/time values."
            )
        if self.missing_value_count:
            messages.append(
                f"Left {self.missing_value_count} hourly measurement value(s) blank "
                f"across {self.affected_hour_count} hour(s) because no valid source "
                "readings were available."
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


def aggregate_hourly_frame(
    source: pd.DataFrame, start_date: date, end_date: date
) -> tuple[pd.DataFrame, int, int, int]:
    """Calculate reference-hour means from parsed minute-level API rows."""
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

    # Preserve the reference file's exact convention: an hour label marks the
    # right edge of its interval. For example, hour 1 contains 00:01-01:00.
    source_timestamps = (
        source_dates
        + pd.to_timedelta(source_hours, unit="h")
        + pd.to_timedelta(source_minutes, unit="m")
    )

    working = pd.DataFrame({"_timestamp": source_timestamps})
    for column in MEASUREMENT_COLUMNS:
        values = pd.to_numeric(source[column], errors="coerce")
        working[column] = values.mask(values <= MISSING_SENTINEL_MAX)

    requested_range = source_dates.between(
        pd.Timestamp(start_date), pd.Timestamp(end_date)
    )
    working = working.loc[valid_timestamps & requested_range].copy()
    if working.empty:
        raise MidcError("MIDC API returned no valid data rows for the requested date range.")

    grouped = (
        working.set_index("_timestamp")[list(MEASUREMENT_COLUMNS)]
        .resample("h", closed="right", label="right")
        .mean()
    )

    full_index = pd.date_range(
        start=pd.Timestamp(start_date),
        end=pd.Timestamp(end_date) + pd.Timedelta(hours=23),
        freq="h",
        name="_timestamp",
    )
    hourly = grouped.reindex(full_index)
    missing_value_count = int(hourly.isna().sum().sum())
    affected_hour_count = int(hourly.isna().any(axis=1).sum())

    hourly = hourly.rename(columns=MEASUREMENT_COLUMNS).reset_index()
    hourly[DATE_COLUMN] = hourly["_timestamp"].dt.strftime("%m/%d/%Y")
    hourly[HOUR_COLUMN] = hourly["_timestamp"].dt.hour.astype(int)

    output_columns = [DATE_COLUMN, HOUR_COLUMN, *MEASUREMENT_COLUMNS.values()]
    output = hourly.loc[:, output_columns]
    output.loc[:, list(MEASUREMENT_COLUMNS.values())] = output.loc[
        :, list(MEASUREMENT_COLUMNS.values())
    ].round(4)
    return output, dropped_timestamp_rows, missing_value_count, affected_hour_count


def aggregate_hourly(
    csv_text: str, start_date: date, end_date: date
) -> tuple[pd.DataFrame, int, int, int]:
    """Calculate right-closed hourly means matching the reference CSV."""
    return aggregate_hourly_frame(parse_api_csv(csv_text), start_date, end_date)


def _date_chunks(
    start_date: date, end_date: date, chunk_days: int
) -> list[tuple[date, date]]:
    if start_date > end_date:
        raise MidcError("Start date must be on or before end date.")
    if chunk_days <= 0:
        raise MidcError("MIDC chunk size must be positive.")

    chunks: list[tuple[date, date]] = []
    cursor = start_date
    while cursor <= end_date:
        chunk_end = min(cursor + timedelta(days=chunk_days - 1), end_date)
        chunks.append((cursor, chunk_end))
        cursor = chunk_end + timedelta(days=1)
    return chunks


def fetch_hourly_data(
    start_date: date,
    end_date: date,
    progress_cb: Callable[[float, str], None] | None = None,
    chunk_days: int = MAX_CHUNK_DAYS,
) -> MidcFetchResult:
    """Download any date range in bounded chunks and aggregate it once."""
    chunks = _date_chunks(start_date, end_date, chunk_days)
    parsed_chunks: list[pd.DataFrame] = []
    for index, (chunk_start, chunk_end) in enumerate(chunks, start=1):
        if progress_cb:
            progress_cb(
                (index - 1) / len(chunks) * 0.85,
                f"Downloading MIDC chunk {index}/{len(chunks)} "
                f"({chunk_start:%m/%d/%Y}-{chunk_end:%m/%d/%Y})...",
            )
        parsed_chunks.append(
            parse_api_csv(download_api_csv(chunk_start, chunk_end))
        )

    source = pd.concat(parsed_chunks, ignore_index=True)
    if progress_cb:
        progress_cb(0.9, "Aggregating reference-hour MIDC data...")
    hourly, dropped, missing, affected = aggregate_hourly_frame(
        source, start_date, end_date
    )
    if progress_cb:
        progress_cb(1.0, "MIDC hourly data ready")
    return MidcFetchResult(
        hourly=hourly,
        raw_rows=int(len(source)),
        chunk_count=len(chunks),
        dropped_timestamp_rows=dropped,
        missing_value_count=missing,
        affected_hour_count=affected,
    )


def output_path_for(start_date: date, end_date: date) -> Path:
    """Return the deterministic output location beside this script."""
    filename = (
        f"MIDC_STAC_hourly_{start_date:%Y%m%d}_to_{end_date:%Y%m%d}.csv"
    )
    return Path(__file__).resolve().parent / filename


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
