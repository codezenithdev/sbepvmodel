"""Conversion between the dashboard's local Mountain times and UTC.

The UI collects wall-clock Mountain times; the historian and the model work in
UTC. Both daylight-saving edge cases -- the hour that does not exist and the one
that happens twice -- are rejected here rather than silently resolved.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sbepv.api import config


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
    candidates: dict[datetime, datetime] = {}
    for fold in (0, 1):
        aware = naive.replace(tzinfo=config.LOCAL_TZ, fold=fold)
        utc_candidate = aware.astimezone(config.UTC_TZ)
        if (
            utc_candidate.astimezone(config.LOCAL_TZ).replace(tzinfo=None)
            == naive
        ):
            candidates[utc_candidate] = aware
    if not candidates:
        raise ValueError(
            "The selected local time does not exist because of the daylight-saving "
            "transition. Choose a different boundary time."
        )
    if len(candidates) > 1:
        raise ValueError(
            "The selected local time occurs twice because of the daylight-saving "
            "transition. Choose a boundary outside the repeated hour."
        )
    utc = next(iter(candidates))
    return utc.strftime("%Y-%m-%dT%H:%M:%S")


def _validation_window_metadata(from_iso: str, to_iso: str) -> dict[str, Any]:
    """Return display-safe validation boundaries while preserving legacy fields."""

    def boundary(value: str) -> tuple[str, str]:
        utc = datetime.fromisoformat(value).replace(tzinfo=config.UTC_TZ)
        explicit_utc = utc.isoformat(timespec="seconds").replace("+00:00", "Z")
        local = utc.astimezone(config.LOCAL_TZ).isoformat(timespec="seconds")
        return explicit_utc, local

    from_utc, from_local = boundary(from_iso)
    to_utc, to_local = boundary(to_iso)
    return {
        "from": from_iso,
        "to": to_iso,
        "from_utc": from_utc,
        "to_utc": to_utc,
        "from_local": from_local,
        "to_local": to_local,
        "timezone": str(config.LOCAL_TZ),
        "end_exclusive": True,
    }
