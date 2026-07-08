#!/usr/bin/env python3
"""
Bazefield historian data puller.

A standalone CLI that pulls historical time-series ("historian") data from a
Bazefield Services REST API and writes it as CSV or JSON.

No third-party dependencies -- standard library only.

By default (no --object-ids/--points) it pulls a fixed set of objects and points
for the SBE Innovation Center PV (STAC1) site -- see TARGETS below -- and writes a
WIDE CSV: one row per timestamp with the columns
    timestamp, solaredge_measured_power, solectria_measured_power,
    dni, ghi, dhi, temp_air, wind_speed

The time window and interval are fixed in code (FROM_TIME / TO_TIME / INTERVAL /
AGGREGATE constants below) -- edit them there, not on the command line.

Quick start
-----------
    set BAZEFIELD_API_KEY (PowerShell):  setx BAZEFIELD_API_KEY "your-key-here"
    # open a new terminal so the variable is visible, then:

    # Pull the static STAC1 wide CSV for the configured window:
    python bazefield_historian.py -o stac1.csv

    # Discovery still works:
    python bazefield_historian.py --list-sites
    python bazefield_historian.py --list-points 1418E76F0E846000

    # Ad hoc override (long format, pass BOTH; still uses the in-code time window):
    python bazefield_historian.py --object-ids 141A49D30A046000 --points ActivePower

See README.md for more.
"""

import argparse
import csv
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

DEFAULT_BASE_URL = "https://bazefield.sbenergy-us.com/Bazefield.Services/api/"
HTTP_TIMEOUT_SECONDS = 60

# Aggregate name -> integer code, per the Bazefield API Developer Guide (rev 11).
# Names work on current servers; integer codes are a fallback for older ones.
AGGREGATE_CODES = {
    "INTERPOLATIVE": 1,
    "TOTAL": 2,
    "AVERAGE": 3,
    "TIMEAVERAGE": 4,
    "COUNT": 5,
    "STDEV": 6,
    "MINIMUMACTUALTIME": 7,
    "MINIMUM": 8,
    "MAXIMUMACTUALTIME": 9,
    "MAXIMUM": 10,
    "START": 11,
    "END": 12,
    "DELTA": 13,
    "VARIANCE": 17,
    "RANGE": 18,
    "DURATIONGOOD": 19,
    "DURATIONBAD": 20,
    "PERCENTGOOD": 21,
    "PERCENTBAD": 22,
}

# Static configuration -- SBE Innovation Center PV (STAC1).
# When the script is run without --object-ids/--points, it pulls exactly these
# object/point combinations. Each object is requested with only the points that
# actually carry data for it (verified live against the instance).
TARGETS = [
    {
        "objectId": "141A49D30A046000",
        "name": "STAC1 East PV Array, Solaredge",
        "points": ["ActivePower"],
    },
    {
        "objectId": "141A47BC71046000",
        "name": "STAC1 East PV Array, Solectria",
        "points": ["ActivePower"],
    },
    {
        "objectId": "1418E76F0E846000",
        "name": "STAC1 Weather Station",
        # DNI/GHI/DHI = irradiance (W/m2), AmbientTemp (C), WindSpeed (m/s).
        # Ambient temperature has real data only on the weather station, not the
        # inverters, so it is requested here.
        "points": ["DNI", "GHI", "DHI", "AmbientTemp", "WindSpeed"],
    },
]

# objectId -> friendly name, derived from TARGETS for output labelling.
OBJECT_NAMES = {t["objectId"]: t["name"] for t in TARGETS}

# ---------------------------------------------------------------------------
# Time window + interval for the pull. EDIT THESE HERE (not on the command line).
#   FROM_TIME / TO_TIME : epoch-ms, ISO-8601, or shorthand (*, *-1d, *-7d, *d,
#                         *d-1d, *M, *M-1M, ...). See README "Time shorthand".
#   INTERVAL            : aggregation interval -- seconds, or 10m / 1h / 1d.
#   AGGREGATE           : how each interval is summarized (TIMEAVERAGE = mean).
# ---------------------------------------------------------------------------
FROM_TIME = "2026-06-20T06:00:00"
TO_TIME = "2026-06-27T06:00:00"
INTERVAL = "3600"  # 1 hour
AGGREGATE = "TIMEAVERAGE"

# Default output file written when --output is not given (so a bare run always
# produces a CSV file instead of printing to the terminal). Edit name/path here.
OUTPUT_FILE = "stac1.csv"

# Wide-output mapping: (objectId, pointName) -> CSV column, in output order.
# This is the static STAC1 shape the CSV is pivoted into.
COLUMN_MAP = [
    ("141A49D30A046000", "ActivePower", "solaredge_measured_power"),
    ("141A47BC71046000", "ActivePower", "solectria_measured_power"),
    ("1418E76F0E846000", "DNI", "dni"),
    ("1418E76F0E846000", "GHI", "ghi"),
    ("1418E76F0E846000", "DHI", "dhi"),
    ("1418E76F0E846000", "AmbientTemp", "temp_air"),
    ("1418E76F0E846000", "WindSpeed", "wind_speed"),
]
WIDE_COLUMNS = ["timestamp"] + [col for _, _, col in COLUMN_MAP]

# Columns whose values are converted from kW to W (x1000) before rounding.
KW_TO_W_COLUMNS = {"solaredge_measured_power", "solectria_measured_power"}
# All numeric values in the wide CSV are rounded to this many decimal places.
ROUND_DECIMALS = 1

# Long-format columns (used only for ad hoc --object-ids/--points overrides).
CSV_COLUMNS = [
    "objectId",
    "objectName",
    "pointName",
    "aggregate",
    "t_ms",
    "timestamp_utc",
    "t_local",
    "quality",
    "value",
]


def load_dotenv(path=".env"):
    """Load KEY=VALUE pairs from a .env file into os.environ (without overriding).

    Minimal, dependency-free. Existing environment variables win.
    """
    if not os.path.isfile(path):
        return
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


class BazefieldError(RuntimeError):
    """Raised when the API returns an error body or the request fails."""


class BazefieldClient:
    def __init__(self, base_url, api_key):
        if not base_url:
            raise BazefieldError("No base URL configured.")
        if not api_key:
            raise BazefieldError(
                "No API key found. Set the BAZEFIELD_API_KEY environment variable "
                '(PowerShell: setx BAZEFIELD_API_KEY "your-key", then reopen the '
                "terminal) or pass --api-key."
            )
        # Ensure exactly one trailing slash so urljoin-style concatenation is safe.
        self.base_url = base_url.rstrip("/") + "/"
        self.api_key = api_key

    def _request(self, path, params=None):
        """GET <base>/<path>?<params> and return the parsed JSON body."""
        query = ""
        if params:
            # Drop None values; keep everything else as-is.
            clean = {k: v for k, v in params.items() if v is not None}
            query = "?" + urllib.parse.urlencode(clean, safe="*:,+-")
        url = self.base_url + path.lstrip("/") + query

        req = urllib.request.Request(url, method="GET")
        req.add_header("Authorization", "Bearer " + self.api_key)
        req.add_header("Accept", "application/json")  # avoids the HTML preview page

        try:
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_SECONDS) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
            raise BazefieldError(
                "HTTP {} from {}\n{}".format(exc.code, url, body[:1000])
            ) from exc
        except urllib.error.URLError as exc:
            raise BazefieldError(
                "Could not reach {}: {}".format(url, exc.reason)
            ) from exc

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise BazefieldError(
                "Expected JSON but got something else from {} "
                "(first 300 chars):\n{}".format(url, raw[:300])
            ) from exc

        # Bazefield returns errors as a responseStatus object even with HTTP 200.
        status = data.get("responseStatus") if isinstance(data, dict) else None
        if status and status.get("errorCode"):
            raise BazefieldError(
                "API error: {} - {}".format(
                    status.get("errorCode"), status.get("message", "")
                )
            )
        return data

    def get_historian(
        self, object_ids, points, aggregates, frm, to, interval, timezone_name=None
    ):
        params = {
            "objectIds": object_ids,
            "points": points,
            "aggregates": aggregates,
            "from": frm,
            "to": to,
            "interval": interval,
        }
        if timezone_name:
            params["TimeZone"] = timezone_name
        return self._request("objects/timeseries/aggregated", params)

    def list_sites(self):
        return self._request("objects/structure", {"type": 102})

    def list_points(self, object_id):
        return self._request("objects/getschemas", {"objectIds": object_id})


def normalize_aggregates(value, use_codes=False):
    """Normalize a comma list of aggregate names/codes.

    Pass through as-is by default; map names to integer codes when use_codes is set.
    """
    parts = [p.strip() for p in value.split(",") if p.strip()]
    if not use_codes:
        return ",".join(parts)
    mapped = []
    for p in parts:
        if p.isdigit():
            mapped.append(p)
        else:
            code = AGGREGATE_CODES.get(p.upper())
            if code is None:
                raise BazefieldError("Unknown aggregate: {}".format(p))
            mapped.append(str(code))
    return ",".join(mapped)


def _iso_utc(t_ms):
    """Convert epoch milliseconds to an ISO-8601 UTC string."""
    try:
        return datetime.fromtimestamp(t_ms / 1000.0, tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OverflowError, OSError):
        return ""


def flatten(resp):
    """Flatten the nested historian response into a list of row dicts."""
    rows = []
    objects = (resp or {}).get("objects") or {}
    for object_id, obj in objects.items():
        points = (obj or {}).get("points") or {}
        for point_name, blocks in points.items():
            # Each point maps to a list of aggregate blocks.
            for block in blocks or []:
                aggregate = block.get("aggregate")
                for sample in block.get("timeSeries") or []:
                    t_ms = sample.get("t")
                    oid = sample.get("objectId", object_id)
                    rows.append(
                        {
                            "objectId": oid,
                            "objectName": OBJECT_NAMES.get(oid, ""),
                            "pointName": sample.get("pointName", point_name),
                            "aggregate": aggregate,
                            "t_ms": t_ms,
                            "timestamp_utc": _iso_utc(t_ms) if t_ms is not None else "",
                            "t_local": sample.get("t_local", ""),
                            "quality": sample.get("q"),
                            "value": sample.get("v"),
                        }
                    )
    return rows


def _utc_stamp(t_ms):
    """Epoch ms -> 'YYYY-MM-DD HH:MM:SS' in UTC."""
    if t_ms is None:
        return ""
    try:
        return datetime.fromtimestamp(t_ms / 1000.0, tz=timezone.utc).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
    except (TypeError, ValueError, OverflowError, OSError):
        return ""


def _fmt_value(col, v):
    """kW->W for power columns, then round to ROUND_DECIMALS. None stays None."""
    if v is None:
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return v
    if col in KW_TO_W_COLUMNS:
        x *= 1000.0
    return round(x, ROUND_DECIMALS)


def pivot(rows):
    """Pivot flat rows into one wide dict per timestamp using COLUMN_MAP.

    All series come from a single combined request, so they share one timestamp
    grid and align exactly on t_ms.
    """
    col_of = {(o, p): c for o, p, c in COLUMN_MAP}
    buckets = {}  # t_ms -> {column: value}
    for r in rows:
        col = col_of.get((r.get("objectId"), r.get("pointName")))
        if col is None:
            continue
        t_ms = r.get("t_ms")
        if t_ms is None:
            continue
        buckets.setdefault(t_ms, {})[col] = r.get("value")
    out = []
    for t_ms in sorted(buckets):
        b = buckets[t_ms]
        row = {"timestamp": _utc_stamp(t_ms)}  # UTC timestamp
        for _, _, col in COLUMN_MAP:
            row[col] = _fmt_value(col, b.get(col))
        out.append(row)
    return out


def _open_out(output):
    """Return (file_handle, should_close) for a path or stdout."""
    if output and output != "-":
        return open(output, "w", newline="", encoding="utf-8"), True
    return sys.stdout, False


def write_csv(rows, output, columns):
    fh, should_close = _open_out(output)
    try:
        writer = csv.DictWriter(fh, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    finally:
        if should_close:
            fh.close()


def write_json(data, output):
    fh, should_close = _open_out(output)
    try:
        json.dump(data, fh, indent=2)
        fh.write("\n")
    finally:
        if should_close:
            fh.close()


def _print_sites(resp):
    rows = (resp or {}).get("data") or []
    if not rows:
        print("No sites returned.", file=sys.stderr)
        return
    print("{:<20} {:<14} {}".format("objectId", "objectKey", "name"))
    for r in rows:
        a = r.get("attributes", {})
        print(
            "{:<20} {:<14} {}".format(
                a.get("objectId", ""), a.get("objectKey", ""), a.get("name", "")
            )
        )


def _print_points(resp):
    info = (resp or {}).get("domaininfo") or {}
    found = False
    header = "{:<32} {:<12} {:<8} {}".format(
        "point (schema)", "valueType", "unit", "description"
    )
    for domain in info.values():
        for s in domain.get("schemas", []) or []:
            if not found:
                print(header)
                found = True
            print(
                "{:<32} {:<12} {:<8} {}".format(
                    s.get("schema", ""),
                    s.get("valueType", ""),
                    s.get("unit", "") or "",
                    (s.get("desc", "") or "").replace("\n", " "),
                )
            )
    if not found:
        print("No points/schemas found for that object.", file=sys.stderr)


def build_parser():
    p = argparse.ArgumentParser(
        description="Pull historian (historical time-series) data from Bazefield.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--object-ids",
        help="Comma-separated objectIds to override the static STAC1 targets "
        "(must be paired with --points).",
    )
    p.add_argument(
        "--points",
        help="Comma-separated point names to override the static STAC1 targets "
        "(must be paired with --object-ids).",
    )
    # NOTE: from / to / interval / aggregate are fixed in code (see the constants
    # FROM_TIME, TO_TIME, INTERVAL, AGGREGATE near the top of this file) -- not CLI args.
    p.add_argument(
        "--format",
        choices=["csv", "json"],
        default="csv",
        help="Output format (default: csv).",
    )
    p.add_argument("--output", "-o", help="Output file path (default: stdout).")
    p.add_argument(
        "--raw",
        action="store_true",
        help="With --format json, dump the untouched API response envelope.",
    )
    p.add_argument("--list-sites", action="store_true", help="List sites and exit.")
    p.add_argument(
        "--list-points",
        metavar="OBJECTID",
        help="List available points/schemas for an objectId and exit.",
    )
    p.add_argument("--api-key", help="API key (overrides BAZEFIELD_API_KEY env var).")
    p.add_argument(
        "--base-url", help="Base URL (overrides BAZEFIELD_BASE_URL env var)."
    )
    return p


def run_historian(
    from_time,
    to_time,
    interval,
    output_csv,
    api_key=None,
    base_url=None,
):
    """Pull the static STAC1 targets for a window and write the wide CSV.

    Callable entrypoint used by the web backend. Reuses the same static targets,
    single combined request, and wide pivot as the CLI. Returns the row count.
    Raises BazefieldError if the query returns no data.
    """
    load_dotenv()
    client = BazefieldClient(
        base_url or os.environ.get("BAZEFIELD_BASE_URL") or DEFAULT_BASE_URL,
        api_key or os.environ.get("BAZEFIELD_API_KEY"),
    )

    object_ids = ",".join(t["objectId"] for t in TARGETS)
    seen, union = set(), []
    for t in TARGETS:
        for pt in t["points"]:
            if pt not in seen:
                seen.add(pt)
                union.append(pt)
    points = ",".join(union)

    resp = client.get_historian(
        object_ids=object_ids,
        points=points,
        aggregates=normalize_aggregates(AGGREGATE),
        frm=from_time,
        to=to_time,
        interval=interval,
    )
    rows = pivot(flatten(resp))
    if not rows:
        err = (resp.get("replyInfo") or {}).get("error") or "no data returned"
        raise BazefieldError(f"No data for the requested window ({err}).")
    write_csv(rows, output_csv, WIDE_COLUMNS)
    return len(rows)


def main(argv=None):
    args = build_parser().parse_args(argv)

    load_dotenv()  # optional: pick up a local .env if present
    base_url = args.base_url or os.environ.get("BAZEFIELD_BASE_URL") or DEFAULT_BASE_URL
    api_key = args.api_key or os.environ.get("BAZEFIELD_API_KEY")

    try:
        client = BazefieldClient(base_url, api_key)

        if args.list_sites:
            _print_sites(client.list_sites())
            return 0

        if args.list_points:
            _print_points(client.list_points(args.list_points))
            return 0

        # Override the static config only when BOTH object ids and points are given.
        if bool(args.object_ids) != bool(args.points):
            print(
                "Error: pass BOTH --object-ids and --points to override, or NEITHER "
                "to use the static STAC1 targets.\n"
                "       (Use --list-sites and --list-points to discover ids/points.)",
                file=sys.stderr,
            )
            return 2

        aggregates = normalize_aggregates(AGGREGATE)
        static_mode = not (args.object_ids and args.points)

        if static_mode:
            # One combined request for all targets so every series shares the same
            # timestamp grid (required for the wide pivot to line up).
            object_ids = ",".join(t["objectId"] for t in TARGETS)
            seen, union = set(), []
            for t in TARGETS:
                for pt in t["points"]:
                    if pt not in seen:
                        seen.add(pt)
                        union.append(pt)
            points = ",".join(union)
        else:
            object_ids, points = args.object_ids, args.points

        resp = client.get_historian(
            object_ids=object_ids,
            points=points,
            aggregates=aggregates,
            frm=FROM_TIME,
            to=TO_TIME,
            interval=INTERVAL,
        )

        flat_rows = flatten(resp)
        if not flat_rows:
            err = (resp.get("replyInfo") or {}).get("error") or "no data returned"
            print("Warning: {}".format(err), file=sys.stderr)

        # Static mode -> wide CSV (timestamp + named columns); override -> long rows.
        out_rows = pivot(flat_rows) if static_mode else flat_rows
        columns = WIDE_COLUMNS if static_mode else CSV_COLUMNS

        # Default to writing a file (OUTPUT_FILE) so a bare run never dumps to the
        # terminal. Pass --output - to force stdout.
        output = args.output if args.output is not None else OUTPUT_FILE

        if args.format == "json":
            write_json(resp if args.raw else out_rows, output)
        else:
            write_csv(out_rows, output, columns)
        return 0

    except BazefieldError as exc:
        print("Error: {}".format(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
