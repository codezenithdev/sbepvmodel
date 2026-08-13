"""Selecting the calibration baseline a new run inherits from.

A promoted baseline carries both settings and per-season calibration factors.
Reuse is only allowed when the source data is still hash-verified and the
reviewed seasons actually cover the requested window -- everything else is sent
back through the visible data-quality review rather than silently inherited.
"""

from __future__ import annotations

import logging
import secrets
from copy import deepcopy
from datetime import date, datetime, timedelta
from typing import Any

from fastapi import HTTPException

from sbepv.api import config, job_store, state
from sbepv.api.request_context import (
    _ANNUAL_FALLBACK_MAPPING,
    _CALIBRATION_SETTING_FIELDS,
    _METEOROLOGICAL_SEASONS,
    _json_sha256,
)
from sbepv.calibration import (
    CALIBRATION_PROFILE_SCHEMA_VERSION,
    season_name,
    validate_seasonal_calibration_profile,
)
from sbepv.api.job_store import _get_job_record
from sbepv.api.schemas import AnnualRunRequest, ChatRequest, RunRequest
from sbepv.api.request_context import _run_request_context
from sbepv.api.validation import (
    _annual_periods,
    _validate_curtailment,
    _validate_run_request,
)
from sbepv import model, reporting
from sbepv.reporting import SourceFingerprintMismatch

logger = logging.getLogger(__name__)


def _validate_current_physics_profile(
    profile: dict[str, Any],
    *,
    required_seasons: tuple[str, ...] | list[str] = (),
) -> dict[str, Any]:
    """Validate profile structure and its complete fit-time physics identity."""

    canonical = validate_seasonal_calibration_profile(
        profile,
        required_seasons=required_seasons,
    )
    model.validate_calibration_profile_physics(canonical)
    return canonical


def _active_model_jobs() -> list[dict[str, Any]]:
    durable = state.AGENT_STORE.list_jobs(states=["queued", "running"], limit=100)
    durable_ids = {str(item["id"]) for item in durable}
    for job_id, cached in state.JOBS.items():
        if job_id not in durable_ids and cached.get("state") in {"queued", "running"}:
            durable.append({"id": job_id, **cached})
    return durable


def _selected_baseline(mode: str) -> dict[str, Any] | None:
    promoted = state.AGENT_STORE.get_current_baseline(mode)
    if promoted and promoted.get("job"):
        return promoted["job"]
    # Compatibility for a completed run created before durable orchestration.
    for job_id, cached in reversed(state.JOBS.items()):
        if cached.get("state") == "done" and cached.get("mode", "validation") == mode:
            return {"id": job_id, **cached}
    return None


def _visible_baseline(
    req: ChatRequest,
    target_mode: str,
    *,
    allow_mode_change: bool = False,
) -> dict[str, Any] | None:
    """Resolve the completed job visible to chat before using a stored default."""

    if req.job_id:
        visible = _get_job_record(str(req.job_id))
        if (
            visible
            and visible.get("state") == "done"
            and visible.get("mode", "validation") == req.active_mode
            and (
                allow_mode_change
                or visible.get("mode", "validation") == target_mode
            )
        ):
            return visible
    return _selected_baseline(target_mode)


def _verified_baseline_source(
    baseline: dict[str, Any] | None,
) -> tuple[str | None, str | None]:
    if not baseline:
        return None, None
    source_path = baseline.get("source_path")
    source_hash = baseline.get("source_hash")
    if not source_path or not source_hash:
        return None, None
    try:
        reporting.verify_source_sha256(source_path, source_hash)
    except (OSError, TypeError, ValueError, SourceFingerprintMismatch):
        logger.warning("Baseline source fingerprint is unavailable or changed")
        return None, None
    return str(source_path), str(source_hash)


def _has_current_annual_temporal_semantics(
    baseline: dict[str, Any] | None,
) -> bool:
    """Return whether a completed annual job used today's time semantics."""

    if (
        not baseline
        or baseline.get("state") != "done"
        or baseline.get("mode") != "annual"
    ):
        return False
    stats = ((baseline.get("result") or {}).get("stats") or {})
    version = stats.get("annual_temporal_semantics_version")
    fingerprint = stats.get("annual_temporal_semantics_fingerprint")
    return (
        version == model.ANNUAL_TEMPORAL_SEMANTICS_VERSION
        and isinstance(fingerprint, str)
        and secrets.compare_digest(
            fingerprint.strip().lower(),
            model.ANNUAL_TEMPORAL_SEMANTICS_FINGERPRINT,
        )
    )


def _reviewed_baseline_data_quality(
    baseline: dict[str, Any],
) -> dict[str, Any] | None:
    """Return review provenance only when it is bound to baseline source bytes."""

    if str(baseline.get("mode") or "") != "validation":
        return None
    quality = (baseline.get("provenance") or {}).get("data_quality")
    if not isinstance(quality, dict):
        return None
    review_id = quality.get("review_id")
    reviewed_hash = quality.get("reviewed_source_sha256")
    source_hash = baseline.get("source_hash")
    if not all(
        isinstance(value, str) and value.strip()
        for value in (review_id, reviewed_hash, source_hash)
    ):
        return None
    if not secrets.compare_digest(
        str(reviewed_hash).strip(), str(source_hash).strip()
    ):
        return None
    return deepcopy(quality)


def _validation_request_seasons(request: dict[str, Any]) -> tuple[str, ...]:
    """Return Denver-local meteorological seasons in an end-exclusive request."""

    try:
        start = datetime.fromisoformat(
            f"{request['from_date']}T{request.get('from_time') or '00:00'}"
        )
        end = datetime.fromisoformat(
            f"{request['to_date']}T{request.get('to_time') or '00:00'}"
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(
            "Validation request dates are unavailable for profile coverage."
        ) from exc
    if end <= start:
        raise ValueError("Validation request end must be after its start.")
    last_included = end - timedelta(microseconds=1)
    cursor = datetime(start.year, start.month, 1)
    final_month = datetime(last_included.year, last_included.month, 1)
    seasons: list[str] = []
    while cursor <= final_month:
        label = season_name(cursor)
        if label not in seasons:
            seasons.append(label)
        cursor = (
            datetime(cursor.year + 1, 1, 1)
            if cursor.month == 12
            else datetime(cursor.year, cursor.month + 1, 1)
        )
    return tuple(seasons)


def _baseline_calibration_profile(
    baseline: dict[str, Any],
    *,
    candidate_request: dict[str, Any],
) -> dict[str, Any] | None:
    """Snapshot or reuse the reviewed baseline's immutable fit profile."""

    if str(baseline.get("mode") or "") != "validation":
        return None
    required_seasons = _validation_request_seasons(candidate_request)
    existing = (baseline.get("provenance") or {}).get(
        "calibration_profile"
    )
    if existing is not None:
        return _validate_current_physics_profile(
            existing,
            required_seasons=required_seasons,
        )

    quality = _reviewed_baseline_data_quality(baseline)
    if quality is None:
        # Compatibility for local jobs created before calibration reviews.
        return None
    result = baseline.get("result") or {}
    stats = result.get("stats") or {}
    fit_metadata = (
        result.get("calibration_factors")
        or stats.get("calibration_factors")
    )
    if not isinstance(fit_metadata, dict):
        raise ValueError(
            "The reviewed baseline does not contain seasonal calibration factors."
        )
    factors: dict[str, dict[str, float]] = {}
    for record in fit_metadata.get("seasons") or []:
        if not isinstance(record, dict):
            raise ValueError(
                "The reviewed baseline contains an invalid seasonal factor record."
            )
        label = str(record.get("season") or "").strip().lower()
        if label in factors:
            raise ValueError(
                f"The reviewed baseline contains duplicate {label} factors."
            )
        systems = record.get("systems")
        if not label or not isinstance(systems, dict):
            raise ValueError(
                "The reviewed baseline contains an invalid seasonal factor record."
            )
        factors[label] = {}
        for system in ("solaredge", "solectria"):
            details = systems.get(system)
            if not isinstance(details, dict):
                raise ValueError(
                    f"The reviewed baseline {label} {system} factor is invalid."
                )
            factors[label][system] = details.get("factor")
    diagnostics = (
        result.get("factor_driver_diagnostics")
        or stats.get("factor_driver_diagnostics")
        or {}
    )
    profile = {
        "schema_version": CALIBRATION_PROFILE_SCHEMA_VERSION,
        "origin_job_id": str(baseline["id"]),
        "origin_source_sha256": str(baseline["source_hash"]),
        "origin_review_id": str(quality["review_id"]),
        "calibration_physics_version": stats.get(
            "calibration_physics_version"
        ),
        "calibration_physics_fingerprint": stats.get(
            "calibration_physics_fingerprint"
        ),
        "solectria_physics_version": stats.get(
            "solectria_physics_version"
        ),
        "solectria_physics_fingerprint": stats.get(
            "solectria_physics_fingerprint"
        ),
        "seasonal_factors": factors,
        "fit_metadata": deepcopy(fit_metadata),
        "factor_driver_diagnostics": deepcopy(diagnostics),
    }
    return _validate_current_physics_profile(
        profile,
        required_seasons=required_seasons,
    )


def _annual_request_seasons(request: dict[str, Any]) -> tuple[str, ...]:
    """Return Denver-local meteorological seasons in an inclusive annual range."""

    if request.get("years") is not None:
        try:
            periods = _annual_periods(
                AnnualRunRequest(**request),
                allow_resolved_partial=True,
            )
        except (HTTPException, TypeError, ValueError) as exc:
            raise ValueError(
                "Annual selected-year periods are unavailable for calibration coverage."
            ) from exc
    else:
        try:
            start = date.fromisoformat(str(request["from_date"]))
            end = date.fromisoformat(str(request["to_date"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(
                "Annual request dates are unavailable for calibration coverage."
            ) from exc
        if end < start:
            raise ValueError("Annual request end must not be before its start.")
        periods = [
            {
                "period_start": start.isoformat(),
                "period_end": end.isoformat(),
            }
        ]

    seasons: list[str] = []
    for period in periods:
        start = date.fromisoformat(str(period["period_start"]))
        end = date.fromisoformat(str(period["period_end"]))
        cursor = date(start.year, start.month, 1)
        final_month = date(end.year, end.month, 1)
        while cursor <= final_month:
            label = season_name(cursor)
            if label not in seasons:
                seasons.append(label)
            cursor = (
                date(cursor.year + 1, 1, 1)
                if cursor.month == 12
                else date(cursor.year, cursor.month + 1, 1)
            )
    return tuple(seasons)


def _inherited_annual_calibration_provenance(
    baseline: dict[str, Any],
    *,
    candidate_request: dict[str, Any],
) -> dict[str, Any] | None:
    """Validate calibration provenance inherited by a same-input annual scenario."""

    baseline_provenance = baseline.get("provenance") or {}
    raw_profile = baseline_provenance.get("calibration_profile")
    raw_application = baseline_provenance.get("calibration_application")
    if raw_profile is None and raw_application is None:
        return None
    if not isinstance(raw_profile, dict) or not isinstance(raw_application, dict):
        raise ValueError(
            "The annual baseline calibration provenance is incomplete."
        )
    if (
        raw_application.get("seasonal_substitution") is not None
        or raw_application.get("server_confirmation") is not None
    ):
        raise ValueError(
            "A seasonal substitution requires a fresh confirmation in the Annual form."
        )

    required_seasons = _annual_request_seasons(candidate_request)
    profile = _validate_current_physics_profile(
        raw_profile,
        required_seasons=required_seasons,
    )
    embedded_profile = _validate_current_physics_profile(
        raw_application.get("resolved_profile"),
        required_seasons=required_seasons,
    )
    if (
        profile.get("seasonal_substitution") is not None
        or embedded_profile.get("seasonal_substitution") is not None
    ):
        raise ValueError(
            "A seasonal substitution requires a fresh confirmation in the Annual form."
        )
    profile_sha256 = _json_sha256(profile)
    if not secrets.compare_digest(
        profile_sha256,
        _json_sha256(embedded_profile),
    ):
        raise ValueError(
            "The annual baseline calibration application does not match its profile."
        )
    recorded_sha256 = str(
        raw_application.get("resolved_profile_sha256") or ""
    ).strip().lower()
    if not recorded_sha256 or not secrets.compare_digest(
        profile_sha256,
        recorded_sha256,
    ):
        raise ValueError(
            "The annual baseline calibration profile fingerprint is invalid."
        )

    application = deepcopy(raw_application)
    origin_job_id = str(application.get("baseline_job_id") or "").strip()
    origin = _get_job_record(origin_job_id) if origin_job_id else None
    if (
        origin is None
        or origin.get("mode") != "validation"
        or origin.get("state") != "done"
    ):
        raise ValueError(
            "The reviewed calibration baseline used by this annual run is unavailable."
        )
    application["settings_deltas"] = _calibration_setting_deltas(
        _baseline_transferable_settings(origin),
        candidate_request,
    )
    application["required_seasons"] = list(required_seasons)
    application["resolved_profile"] = embedded_profile
    application["resolved_profile_sha256"] = profile_sha256
    return {
        "calibration_profile": profile,
        "calibration_application": application,
    }



def _baseline_transferable_settings(baseline: dict[str, Any]) -> dict[str, Any]:
    """Return the nine canonical settings shared by calibration and annual runs."""

    request = RunRequest(**dict(baseline.get("request") or {}))
    _validate_run_request(request)
    _validate_curtailment(request)
    canonical = _run_request_context(request)
    return {
        field: deepcopy(canonical.get(field))
        for field in _CALIBRATION_SETTING_FIELDS
    }


def _current_calibration_bundle() -> dict[str, Any] | None:
    """Return a verified current reviewed calibration and its safe derived data."""

    promoted = state.AGENT_STORE.get_current_baseline("validation")
    if not promoted or not isinstance(promoted.get("job"), dict):
        return None
    baseline = promoted["job"]
    if baseline.get("state") != "done" or baseline.get("mode") != "validation":
        return None
    quality = _reviewed_baseline_data_quality(baseline)
    source_path, source_hash = _verified_baseline_source(baseline)
    if quality is None or not source_path or not source_hash:
        return None
    profile = _baseline_calibration_profile(
        baseline,
        candidate_request=dict(baseline.get("request") or {}),
    )
    if profile is None:
        return None
    canonical_profile = _validate_current_physics_profile(profile)
    return {
        "promotion": deepcopy(promoted),
        "baseline": deepcopy(baseline),
        "quality": quality,
        "profile": canonical_profile,
        "profile_sha256": _json_sha256(canonical_profile),
        "settings": _baseline_transferable_settings(baseline),
    }


def _public_current_calibration(bundle: dict[str, Any]) -> dict[str, Any]:
    baseline = bundle["baseline"]
    promotion = bundle["promotion"]
    profile = bundle["profile"]
    quality = bundle["quality"]
    request = dict(baseline.get("request") or {})
    factors = deepcopy(profile["seasonal_factors"])
    return {
        "available": True,
        "verified": True,
        "job_id": str(baseline["id"]),
        "origin_job_id": str(profile["origin_job_id"]),
        "review_id": str(quality["review_id"]),
        "calibration_physics_version": profile[
            "calibration_physics_version"
        ],
        "calibration_physics_fingerprint": profile[
            "calibration_physics_fingerprint"
        ],
        "solectria_physics_version": profile[
            "solectria_physics_version"
        ],
        "solectria_physics_fingerprint": profile[
            "solectria_physics_fingerprint"
        ],
        "promoted_at": promotion.get("promoted_at"),
        "receipt_url": f"/api/status/{baseline['id']}",
        "profile_sha256": bundle["profile_sha256"],
        "profile_fingerprint": bundle["profile_sha256"],
        "calibration_window": {
            "from_date": request.get("from_date"),
            "from_time": request.get("from_time") or "00:00",
            "to_date": request.get("to_date"),
            "to_time": request.get("to_time") or "00:00",
            "timezone": "America/Denver",
            "end_exclusive": True,
        },
        "settings": deepcopy(bundle["settings"]),
        "factor_coverage": {
            season: season in factors for season in _METEOROLOGICAL_SEASONS
        },
        "seasonal_factors": factors,
    }


def _calibration_setting_deltas(
    baseline_settings: dict[str, Any], annual_request: dict[str, Any]
) -> list[dict[str, Any]]:
    deltas: list[dict[str, Any]] = []
    for field in _CALIBRATION_SETTING_FIELDS:
        calibrated = baseline_settings.get(field)
        annual = annual_request.get(field)
        if annual != calibrated:
            deltas.append(
                {
                    "field": field,
                    "calibrated_value": deepcopy(calibrated),
                    "annual_value": deepcopy(annual),
                }
            )
    return deltas


def _annual_confirmation_context(
    *,
    baseline_job_id: str,
    profile_sha256: str,
    annual_request: dict[str, Any],
    required_seasons: tuple[str, ...],
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "baseline_job_id": baseline_job_id,
        "profile_sha256": profile_sha256,
        "annual_request": deepcopy(annual_request),
        "required_seasons": list(required_seasons),
        "mapping": deepcopy(_ANNUAL_FALLBACK_MAPPING),
    }


def _calibration_conflict(
    code: str, message: str, **context: Any
) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={"code": code, "message": message, **context},
    )
