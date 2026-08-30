"""Deterministic Autonomy readiness derived from durable dashboard state."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import importlib.util
import os
from typing import Any

from sbepv.api import baselines as baselines_module
from sbepv.api import config, state
from sbepv.api import technoeconomic as technoeconomic_api
from sbepv.autonomy import lifecycle, serializers
from sbepv.store import AgentStoreError


READINESS_SCHEMA_VERSION = "decision-readiness-v1"
SUPPORTED_ANALYSIS_BASES = (
    {
        "id": "solartac_site",
        "label": "SolarTAC site",
        "rule": "Use project-specific installed totals normalized by frozen as-modeled capacity.",
    },
    {
        "id": "commercial_representative",
        "label": "Commercial representative",
        "rule": "Use a separately sourced commercial design and representative USD/Wdc inputs.",
    },
)
_CHECK_STATUSES = frozenset({"passed", "needs_attention", "blocked", "stale"})
_FORECAST_START_YEAR = 2012
_KNOWN_INCOMPLETE_YEARS = frozenset({2022, 2023})
_MINIMUM_VERIFIED_YEARS = 10


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _completed_calibrated_annual_source(job: Mapping[str, Any]) -> bool:
    if job.get("mode") != "annual" or job.get("state") != "done":
        return False
    result = job.get("result")
    if not isinstance(result, Mapping):
        return False
    stats = result.get("stats")
    application = result.get("calibration_application")
    return (
        isinstance(stats, Mapping)
        and stats.get("calibration_enabled") is True
        and isinstance(application, Mapping)
        and application.get("applied") is True
    )


def _safe_source_summary(
    annual_job: Mapping[str, Any],
    dependencies: Mapping[str, Any],
    eligibility: Mapping[str, Any],
) -> dict[str, Any]:
    request = annual_job.get("request")
    if not isinstance(request, Mapping):
        request = {}
    origin = dependencies.get("origin_validation_job")
    if not isinstance(origin, Mapping):
        origin = {}
    promotion = dependencies.get("promotion_record")
    if not isinstance(promotion, Mapping):
        promotion = {}
    return {
        "annual_job_id": str(annual_job.get("id") or ""),
        "completed_at": annual_job.get("completed_at"),
        "created_at": annual_job.get("created_at"),
        "source_snapshot_sha256": eligibility.get("source_snapshot_sha256"),
        "eligible_years": deepcopy(eligibility.get("eligible_years") or []),
        "annual_window": {
            key: deepcopy(request.get(key))
            for key in (
                "from_date",
                "to_date",
                "years",
                "interval_value",
                "interval_unit",
            )
            if key in request
        },
        "calibration_lineage": {
            "origin_validation_job_id": origin.get("id"),
            "promotion_id": promotion.get("promotion_id"),
            "promoted_at": promotion.get("promoted_at"),
        },
        "capacity_manifest_source": eligibility.get("capacity_manifest_source"),
    }


def _inspect_annual_source(
    agent_store: Any,
    annual_job: Mapping[str, Any],
) -> dict[str, Any]:
    annual_job_id = str(annual_job.get("id") or "")
    try:
        dependencies = technoeconomic_api.resolve_annual_source_dependencies(
            agent_store,
            annual_job_id,
        )
        eligibility = technoeconomic_api.inspect_annual_source_eligibility(
            dependencies["annual_job"],
            origin_validation_job=dependencies["origin_validation_job"],
            promotion_record=dependencies["promotion_record"],
        )
    except technoeconomic_api.AnnualSourceValidationError as exc:
        return {
            "eligible": False,
            "annual_job_id": annual_job_id,
            "reason_code": exc.code,
            "detail": exc.detail,
        }
    except (AgentStoreError, KeyError, OSError, TypeError, ValueError):
        return {
            "eligible": False,
            "annual_job_id": annual_job_id,
            "reason_code": "annual_source_unverifiable",
            "detail": "The Annual source provenance could not be verified.",
        }
    if not eligibility.get("eligible"):
        return {
            "eligible": False,
            "annual_job_id": annual_job_id,
            "reason_code": eligibility.get("reason_code") or "annual_source_ineligible",
            "detail": eligibility.get("detail") or "The Annual source is not eligible.",
        }
    return {
        "eligible": True,
        **_safe_source_summary(annual_job, dependencies, eligibility),
        "_dependencies": dependencies,
    }


def list_eligible_annual_sources(*, agent_store: Any | None = None) -> list[dict[str, Any]]:
    """Return strict, path-free source summaries for verified completed Annual jobs."""

    durable_store = agent_store if agent_store is not None else state.AGENT_STORE
    candidates = durable_store.list_jobs(states=("done",), mode="annual", limit=None)
    eligible: list[dict[str, Any]] = []
    for annual_job in candidates:
        if not _completed_calibrated_annual_source(annual_job):
            continue
        inspection = _inspect_annual_source(durable_store, annual_job)
        if inspection.get("eligible"):
            inspection.pop("_dependencies", None)
            eligible.append(serializers.safe_public_value(inspection))
    eligible.sort(
        key=lambda item: (str(item.get("completed_at") or ""), str(item.get("annual_job_id") or "")),
        reverse=True,
    )
    return eligible


def _blocker(
    *,
    code: str,
    check_id: str,
    detail: str,
    why: str,
    rule_id: str,
    rule: str,
    action_id: str,
    action_label: str,
    deep_link: str,
    blocking: bool = True,
) -> dict[str, Any]:
    return {
        "code": code,
        "check_id": check_id,
        "detail": detail,
        "why_it_matters": why,
        "rule_id": rule_id,
        "exact_rule": rule,
        "closest_supported_action": {
            "id": action_id,
            "label": action_label,
            "deep_link": deep_link,
        },
        "blocking": blocking,
    }


def _check(
    check_id: str,
    label: str,
    status: str,
    summary: str,
    *,
    rule_id: str,
    exact_rule: str,
    details: Mapping[str, Any] | None = None,
    blockers: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if status not in _CHECK_STATUSES:
        raise ValueError("unsupported readiness status")
    normalized_blockers = blockers or []
    primary_action = (
        normalized_blockers[0].get("closest_supported_action")
        if normalized_blockers
        else None
    )
    return {
        "id": check_id,
        "key": check_id,
        "label": label,
        "status": status,
        "summary": summary,
        "rule_id": rule_id,
        "exact_rule": exact_rule,
        "details": serializers.safe_public_value(details or {}),
        "blockers": normalized_blockers,
        "blocker": normalized_blockers[0] if normalized_blockers else None,
        "primary_action": primary_action,
    }


def _agent_availability() -> dict[str, Any]:
    enabled = bool(config.DECISION_AGENT_ENABLED)
    credential_present = bool(os.getenv("OPENAI_API_KEY", "").strip())
    try:
        sdk_available = importlib.util.find_spec("agents") is not None
    except (ImportError, ValueError):
        sdk_available = False
    available = enabled and credential_present and sdk_available
    reasons: list[str] = []
    if not enabled:
        reasons.append("disabled_by_configuration")
    if not credential_present:
        reasons.append("credential_unavailable")
    if not sdk_available:
        reasons.append("agents_sdk_unavailable")
    return {
        "available": available,
        "enabled": enabled,
        "credential_configured": credential_present,
        "sdk_available": sdk_available,
        "reason_codes": reasons,
        "manual_readiness_available": True,
    }


def _is_job_stale(job: Mapping[str, Any], now: datetime) -> bool:
    if job.get("state") != "running":
        return False
    last_seen = (
        _parse_timestamp(job.get("heartbeat_at"))
        or _parse_timestamp(job.get("started_at"))
        or _parse_timestamp(job.get("updated_at"))
    )
    return bool(
        last_seen
        and last_seen
        <= now - timedelta(seconds=float(config.JOB_STALE_SECONDS))
    )


def _job_health(agent_store: Any, now: datetime) -> dict[str, Any]:
    model_jobs = agent_store.list_jobs(
        states=("queued", "running", "error", "interrupted"),
        limit=100,
    )
    tea_jobs = agent_store.list_technoeconomic_jobs(
        states=("queued", "running", "error", "interrupted"),
        limit=100,
    )
    combined = [
        {
            "job_id": item.get("id"),
            "job_family": "model",
            "mode": item.get("mode"),
            "state": item.get("state"),
            "stale": _is_job_stale(item, now),
            "updated_at": item.get("updated_at"),
        }
        for item in model_jobs
    ] + [
        {
            "job_id": item.get("id"),
            "job_family": "technoeconomic",
            "mode": "technoeconomic",
            "state": item.get("state"),
            "stale": _is_job_stale(item, now),
            "updated_at": item.get("updated_at"),
        }
        for item in tea_jobs
    ]
    return {
        "jobs": combined,
        "active_count": sum(item["state"] in {"queued", "running"} for item in combined),
        "failed_count": sum(item["state"] == "error" for item in combined),
        "interrupted_count": sum(item["state"] == "interrupted" for item in combined),
        "stale_count": sum(bool(item["stale"]) for item in combined),
    }


def _evidence_health(agent_store: Any, case_id: str) -> dict[str, Any]:
    assets = agent_store.list_decision_evidence_assets(
        case_id,
        include_removed=False,
        limit=100,
    )
    pending = 0
    accepted: list[dict[str, Any]] = []
    rejected = 0
    invalid_provisional = 0
    for asset in assets:
        for candidate in asset.get("candidates") or ():
            review_state = candidate.get("review_state")
            receipt = candidate.get("receipt")
            if review_state == "pending":
                pending += 1
            elif review_state == "rejected":
                rejected += 1
            elif review_state == "accepted" and isinstance(receipt, Mapping):
                accepted.append(dict(receipt))
                if (
                    receipt.get("evidence_class") in lifecycle.PROVISIONAL_EVIDENCE_CLASSES
                    and not str(receipt.get("rationale") or "").strip()
                ):
                    invalid_provisional += 1
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for receipt in accepted:
        key = (
            str(receipt.get("field_name") or "").strip().casefold(),
            str(receipt.get("unit") or "").strip().casefold(),
        )
        groups.setdefault(key, []).append(receipt)
    conflicts: list[dict[str, Any]] = []
    for (field_name, unit), receipts in groups.items():
        values = {str(item.get("value") or "").strip().casefold() for item in receipts}
        if len(values) > 1:
            conflicts.append(
                {
                    "field": field_name,
                    "unit": unit or None,
                    "values": sorted(
                        {str(item.get("value") or "").strip() for item in receipts}
                    ),
                    "receipt_ids": [item.get("id") for item in receipts],
                }
            )
    return {
        "asset_count": len(assets),
        "candidate_count": pending + rejected + len(accepted),
        "pending_count": pending,
        "accepted_count": len(accepted),
        "rejected_count": rejected,
        "conflicts": conflicts,
        "invalid_provisional_count": invalid_provisional,
    }


def _scenario_health(
    agent_store: Any,
    case_id: str,
    now: datetime,
) -> dict[str, Any]:
    """Summarize only current durable scenario revisions and linked TEA attempts."""

    list_scenarios = getattr(agent_store, "list_decision_scenarios", None)
    if not callable(list_scenarios):
        return {
            "scenarios": [],
            "baseline_count": 0,
            "alternative_count": 0,
            "validated_count": 0,
            "validated_baseline": False,
            "cancellable_execution": False,
            "retryable_execution": False,
            "execution_states": {},
        }
    records = list_scenarios(
        case_id,
        include_history=False,
        include_expired=False,
        limit=100,
    )
    def elapsed_unconfirmed(item: Mapping[str, Any]) -> bool:
        if item.get("status") not in {"draft", "invalid", "validated"}:
            return False
        expires_at = _parse_timestamp(item.get("expires_at"))
        return expires_at is not None and expires_at <= now

    current = [
        item
        for item in records
        if not item.get("superseded_by_revision_id")
        and item.get("status") != "expired"
        and not elapsed_unconfirmed(item)
    ]
    jobs: list[Mapping[str, Any]] = []
    for scenario in current:
        raw_jobs = scenario.get("jobs") or []
        if isinstance(raw_jobs, Sequence) and not isinstance(
            raw_jobs, (str, bytes, bytearray)
        ):
            jobs.extend(item for item in raw_jobs if isinstance(item, Mapping))
        latest = scenario.get("latest_job")
        if isinstance(latest, Mapping) and latest not in jobs:
            jobs.append(latest)
    state_counts: dict[str, int] = {}
    for job in jobs:
        job_state = str(job.get("state") or "unknown")
        state_counts[job_state] = state_counts.get(job_state, 0) + 1
    return {
        "scenarios": [
            {
                "scenario_id": item.get("id") or item.get("scenario_id"),
                "revision": item.get("revision"),
                "kind": item.get("kind"),
                "status": item.get("status"),
                "request_sha256": item.get("request_sha256"),
                "classification": item.get("comparison_classification"),
            }
            for item in current
        ],
        "baseline_count": sum(item.get("kind") == "baseline" for item in current),
        "alternative_count": sum(
            item.get("kind") == "alternative" for item in current
        ),
        "validated_count": sum(
            item.get("status") in {"validated", "confirmed"} for item in current
        ),
        "validated_baseline": any(
            item.get("kind") == "baseline"
            and item.get("status") in {"validated", "confirmed"}
            for item in current
        ),
        "cancellable_execution": any(
            item.get("state") in {"queued", "running"} for item in jobs
        ),
        "retryable_execution": any(
            item.get("state") in {"error", "interrupted", "cancelled"}
            for item in jobs
        ),
        "execution_states": state_counts,
    }


def _selected_source(
    agent_store: Any,
    case_record: Mapping[str, Any],
    all_eligible: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    source_id = str(case_record.get("source_annual_job_id") or "").strip()
    if not source_id:
        return None, None
    annual_job = agent_store.get_job(source_id)
    if not isinstance(annual_job, Mapping):
        return None, {
            "eligible": False,
            "annual_job_id": source_id,
            "reason_code": "annual_source_missing",
            "detail": "The locked Annual source no longer resolves from durable state.",
        }
    inspection = _inspect_annual_source(agent_store, annual_job)
    expected_sha = str(case_record.get("source_snapshot_sha256") or "")
    actual_sha = str(inspection.get("source_snapshot_sha256") or "")
    if inspection.get("eligible") and expected_sha != actual_sha:
        inspection = {
            "eligible": False,
            "annual_job_id": source_id,
            "reason_code": "locked_source_hash_mismatch",
            "detail": "The verified Annual snapshot does not match the immutable case lock.",
        }
    selected_public = deepcopy(inspection)
    selected_public.pop("_dependencies", None)
    latest = all_eligible[0] if all_eligible else None
    return selected_public, latest


def evaluate_decision_case_readiness(
    case_id: str,
    *,
    agent_store: Any | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Evaluate one case without granting permissions or creating missing work."""

    durable_store = agent_store if agent_store is not None else state.AGENT_STORE
    evaluated_at = (now or _utc_now()).astimezone(timezone.utc)
    case_record = durable_store.get_decision_case(case_id)
    if case_record is None:
        raise KeyError("decision case not found")

    eligible_sources = list_eligible_annual_sources(agent_store=durable_store)
    selected_source, latest_source = _selected_source(
        durable_store,
        case_record,
        eligible_sources,
    )
    source_locked = bool(case_record.get("source_annual_job_id"))
    blockers: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []

    # Calibration lineage is verified through the locked source when present;
    # otherwise the currently promoted reviewed baseline is the prerequisite.
    current_bundle: dict[str, Any] | None
    try:
        current_bundle = baselines_module._current_calibration_bundle()
    except (KeyError, OSError, TypeError, ValueError):
        current_bundle = None
    locked_dependencies = None
    locked_inspection: Mapping[str, Any] | None = None
    if source_locked:
        annual_job = durable_store.get_job(str(case_record["source_annual_job_id"]))
        if isinstance(annual_job, Mapping):
            locked_inspection = _inspect_annual_source(durable_store, annual_job)
            locked_dependencies = locked_inspection.get("_dependencies")
    locked_origin = (
        locked_dependencies.get("origin_validation_job")
        if isinstance(locked_dependencies, Mapping)
        else None
    )
    locked_promotion = (
        locked_dependencies.get("promotion_record")
        if isinstance(locked_dependencies, Mapping)
        else None
    )
    locked_lineage_verified = bool(
        isinstance(locked_origin, Mapping)
        and str(locked_origin.get("id") or "").strip()
        and isinstance(locked_promotion, Mapping)
        and locked_promotion.get("promotion_id") not in (None, "")
        and str(locked_promotion.get("promoted_at") or "").strip()
    )
    if locked_lineage_verified:
        current_id = (
            str(current_bundle["baseline"].get("id"))
            if current_bundle and isinstance(current_bundle.get("baseline"), Mapping)
            else None
        )
        locked_id = str(locked_origin.get("id") or "")
        calibration_status = "passed" if not current_id or current_id == locked_id else "stale"
        calibration_summary = (
            "The case retains a verified reviewed calibration lineage."
            if calibration_status == "passed"
            else "The case lineage remains verified, but a newer promoted calibration exists."
        )
        checks.append(
            _check(
                "calibration",
                "Calibration",
                calibration_status,
                calibration_summary,
                rule_id="AUT-CAL-1",
                exact_rule="The case must use a verified reviewed calibration promotion frozen into its Annual source.",
                details={
                    "locked_origin_job_id": locked_id,
                    "locked_promoted_at": locked_promotion.get("promoted_at"),
                    "current_promoted_job_id": current_id,
                },
            )
        )
    elif source_locked:
        source_reason = (
            locked_inspection.get("reason_code")
            if isinstance(locked_inspection, Mapping)
            else (selected_source or {}).get("reason_code")
        ) or "locked_calibration_dependencies_missing"
        item = _blocker(
            code="locked_calibration_lineage_unverifiable",
            check_id="calibration",
            detail=(
                "The Calibration lineage frozen into the case's locked Annual "
                "source cannot be resolved and source-verified."
            ),
            why=(
                "A different currently promoted baseline cannot replace an "
                "immutable case source lock."
            ),
            rule_id="AUT-CAL-1",
            rule=(
                "When a case has a source lock, Calibration readiness must be "
                "proven only from the calibration lineage frozen into that locked "
                "Annual source; the current promoted baseline is not a substitute."
            ),
            action_id="create_new_case",
            action_label="Create a new case with a verifiable source",
            deep_link="#autonomy-new-case",
        )
        blockers.append(item)
        checks.append(
            _check(
                "calibration",
                "Calibration",
                "blocked",
                item["detail"],
                rule_id=item["rule_id"],
                exact_rule=item["exact_rule"],
                details={
                    "locked_annual_job_id": case_record.get("source_annual_job_id"),
                    "source_verification_reason_code": source_reason,
                    "current_promoted_baseline_is_substitute": False,
                },
                blockers=[item],
            )
        )
    elif current_bundle:
        baseline = current_bundle.get("baseline") or {}
        quality = current_bundle.get("quality") or {}
        checks.append(
            _check(
                "calibration",
                "Calibration",
                "passed",
                "A reviewed Calibration baseline is promoted and source-verified.",
                rule_id="AUT-CAL-1",
                exact_rule="A reviewed, source-verified Calibration baseline must be promoted before an Annual source can be selected.",
                details={
                    "job_id": baseline.get("id"),
                    "review_id": quality.get("review_id"),
                    "promoted_at": (current_bundle.get("promotion") or {}).get("promoted_at"),
                    "profile_sha256": current_bundle.get("profile_sha256"),
                },
            )
        )
    else:
        item = _blocker(
            code="calibration_not_ready",
            check_id="calibration",
            detail="No reviewed, source-verified Calibration baseline is currently available.",
            why="Annual and TEA conclusions require traceable measured-data calibration lineage.",
            rule_id="AUT-CAL-1",
            rule="A reviewed, source-verified Calibration baseline must be promoted.",
            action_id="open_calibration",
            action_label="Open Calibration",
            deep_link="#calibration",
        )
        blockers.append(item)
        checks.append(
            _check(
                "calibration",
                "Calibration",
                "blocked",
                item["detail"],
                rule_id=item["rule_id"],
                exact_rule=item["exact_rule"],
                blockers=[item],
            )
        )

    if source_locked and selected_source and selected_source.get("eligible"):
        newer = bool(
            latest_source
            and latest_source.get("annual_job_id") != selected_source.get("annual_job_id")
            and str(latest_source.get("completed_at") or "")
            > str(selected_source.get("completed_at") or "")
        )
        annual_status = "stale" if newer else "passed"
        checks.append(
            _check(
                "annual_source",
                "Annual source",
                annual_status,
                (
                    "The immutable Annual source is verified, but a newer eligible source is available."
                    if newer
                    else "The immutable Annual source and snapshot hash are verified."
                ),
                rule_id="AUT-ANNUAL-1",
                exact_rule="A case locks exactly one completed calibrated Annual source and its verified snapshot SHA-256.",
                details={
                    "selected": selected_source,
                    "newer_eligible_source": latest_source if newer else None,
                },
            )
        )
    elif source_locked:
        detail = (
            (selected_source or {}).get("detail")
            or "The locked Annual source could not be verified."
        )
        item = _blocker(
            code=str((selected_source or {}).get("reason_code") or "annual_source_invalid"),
            check_id="annual_source",
            detail=str(detail),
            why="Case conclusions must remain tied to immutable, source-verified Annual bytes and lineage.",
            rule_id="AUT-ANNUAL-1",
            rule="The locked Annual source must remain fully verifiable and match the case snapshot SHA-256.",
            action_id="create_new_case",
            action_label="Create a new case with another source",
            deep_link="#autonomy-new-case",
        )
        blockers.append(item)
        checks.append(
            _check(
                "annual_source",
                "Annual source",
                "blocked",
                item["detail"],
                rule_id=item["rule_id"],
                exact_rule=item["exact_rule"],
                blockers=[item],
            )
        )
    elif eligible_sources:
        item = _blocker(
            code="annual_source_not_locked",
            check_id="annual_source",
            detail="Eligible Annual sources exist, but this case has not locked one.",
            why="All later evidence and scenarios must share one immutable source identity.",
            rule_id="AUT-ANNUAL-1",
            rule="A case must lock exactly one eligible Annual source and snapshot hash before scenario work.",
            action_id="select_annual_source",
            action_label="Select an eligible Annual source",
            deep_link="#autonomy-source-selection",
        )
        blockers.append(item)
        checks.append(
            _check(
                "annual_source",
                "Annual source",
                "needs_attention",
                item["detail"],
                rule_id=item["rule_id"],
                exact_rule=item["exact_rule"],
                details={"eligible_sources": eligible_sources},
                blockers=[item],
            )
        )
    else:
        item = _blocker(
            code="eligible_annual_source_missing",
            check_id="annual_source",
            detail="No completed calibrated Annual source passes strict TEA source verification.",
            why="The decision case cannot infer or synthesize missing Annual model results.",
            rule_id="AUT-ANNUAL-1",
            rule="At least one completed calibrated Annual source must pass immutable provenance and artifact verification.",
            action_id="open_annual",
            action_label="Open Annual Simulation",
            deep_link="#annual",
        )
        blockers.append(item)
        checks.append(
            _check(
                "annual_source",
                "Annual source",
                "blocked",
                item["detail"],
                rule_id=item["rule_id"],
                exact_rule=item["exact_rule"],
                blockers=[item],
            )
        )

    weather_source = selected_source if selected_source and selected_source.get("eligible") else None
    if weather_source:
        eligible_years = sorted({int(year) for year in weather_source.get("eligible_years") or []})
        expected_years = [
            year
            for year in range(_FORECAST_START_YEAR, evaluated_at.year)
            if year not in _KNOWN_INCOMPLETE_YEARS
        ]
        missing_years = sorted(set(expected_years) - set(eligible_years))
        window = weather_source.get("annual_window") or {}
        hourly = window.get("interval_value") == 1 and window.get("interval_unit") == "hours"
        weather_ready = (
            len(eligible_years) >= _MINIMUM_VERIFIED_YEARS
            and not missing_years
            and hourly
            and not (set(eligible_years) & _KNOWN_INCOMPLETE_YEARS)
        )
        if weather_ready:
            checks.append(
                _check(
                    "weather_coverage",
                    "Weather coverage",
                    "passed",
                    f"{len(eligible_years)} complete source-verified hourly weather years satisfy policy.",
                    rule_id="AUT-WEATHER-1",
                    exact_rule="Use complete hourly calendar years from 2012 through the previous year, excluding 2022, 2023, 2011, and the current partial year, with at least ten verified years.",
                    details={
                        "eligible_years": eligible_years,
                        "excluded_years": sorted(_KNOWN_INCOMPLETE_YEARS),
                        "minimum_years": _MINIMUM_VERIFIED_YEARS,
                    },
                )
            )
        else:
            item = _blocker(
                code="weather_policy_not_satisfied",
                check_id="weather_coverage",
                detail="The locked source does not satisfy the complete hourly weather-year policy.",
                why="Incomplete or mismatched weather coverage can bias lifecycle comparisons.",
                rule_id="AUT-WEATHER-1",
                rule="Use complete hourly calendar years from 2012 through the previous year, excluding 2022, 2023, 2011, and the current partial year, with at least ten verified years.",
                action_id="open_annual",
                action_label="Create a policy-compliant Annual Simulation",
                deep_link="#annual",
            )
            blockers.append(item)
            checks.append(
                _check(
                    "weather_coverage",
                    "Weather coverage",
                    "blocked",
                    item["detail"],
                    rule_id=item["rule_id"],
                    exact_rule=item["exact_rule"],
                    details={
                        "eligible_years": eligible_years,
                        "missing_policy_years": missing_years,
                        "hourly_interval": hourly,
                        "minimum_years": _MINIMUM_VERIFIED_YEARS,
                    },
                    blockers=[item],
                )
            )
    else:
        checks.append(
            _check(
                "weather_coverage",
                "Weather coverage",
                "blocked",
                "Weather policy cannot be evaluated until an eligible Annual source is locked.",
                rule_id="AUT-WEATHER-1",
                exact_rule="Weather coverage is evaluated from the immutable selected Annual source.",
                details={"minimum_years": _MINIMUM_VERIFIED_YEARS},
            )
        )

    evidence = _evidence_health(durable_store, case_id)
    evidence_blockers: list[dict[str, Any]] = []
    if evidence["invalid_provisional_count"]:
        evidence_blockers.append(
            _blocker(
                code="provisional_evidence_rationale_missing",
                check_id="evidence",
                detail="Accepted provisional evidence is missing a human rationale.",
                why="Engineering judgment and secondary synthesis must remain visibly supervised.",
                rule_id="AUT-EVIDENCE-2",
                rule="Every accepted provisional candidate requires a named human and non-empty rationale.",
                action_id="review_evidence",
                action_label="Review evidence",
                deep_link="#autonomy-evidence",
            )
        )
    if evidence["conflicts"]:
        evidence_blockers.append(
            _blocker(
                code="accepted_evidence_conflicts",
                check_id="evidence",
                detail="Accepted sources disagree for one or more field-and-unit pairs.",
                why="Conflicting sources must remain visible and cannot be silently resolved by the agent.",
                rule_id="AUT-EVIDENCE-3",
                rule="Conflicting accepted evidence is displayed side by side and requires human resolution in a later scenario revision.",
                action_id="review_evidence",
                action_label="Inspect conflicting evidence",
                deep_link="#autonomy-evidence",
            )
        )
    if evidence_blockers:
        blockers.extend(evidence_blockers)
        evidence_status = "blocked"
        evidence_summary = "Accepted evidence requires human resolution."
    elif evidence["pending_count"]:
        item = _blocker(
            code="evidence_review_pending",
            check_id="evidence",
            detail=f"{evidence['pending_count']} extracted candidate(s) await explicit acceptance or rejection.",
            why="Extracted values are untrusted until a human reviews each candidate.",
            rule_id="AUT-EVIDENCE-1",
            rule="Every extracted candidate must be explicitly accepted or rejected; the agent cannot accept evidence.",
            action_id="review_evidence",
            action_label="Review extracted candidates",
            deep_link="#autonomy-evidence",
        )
        blockers.append(item)
        evidence_blockers.append(item)
        evidence_status = "needs_attention"
        evidence_summary = item["detail"]
    elif not evidence["accepted_count"]:
        item = _blocker(
            code="accepted_evidence_missing",
            check_id="evidence",
            detail="The case has no accepted immutable evidence receipts.",
            why="Decision inputs need a traceable human-approved basis before scenario validation.",
            rule_id="AUT-EVIDENCE-1",
            rule="At least one extracted candidate must be explicitly accepted before evidence readiness can pass.",
            action_id="upload_evidence",
            action_label="Upload evidence",
            deep_link="#autonomy-evidence-upload",
        )
        blockers.append(item)
        evidence_blockers.append(item)
        evidence_status = "needs_attention"
        evidence_summary = item["detail"]
    else:
        evidence_status = "passed"
        evidence_summary = f"{evidence['accepted_count']} immutable evidence receipt(s) are accepted with no unresolved conflict."
    checks.append(
        _check(
            "evidence",
            "TEA evidence",
            evidence_status,
            evidence_summary,
            rule_id="AUT-EVIDENCE-1",
            exact_rule="Uploaded bytes are untrusted; each extracted candidate requires a separate immutable human review receipt.",
            details=evidence,
            blockers=evidence_blockers,
        )
    )

    scenarios = _scenario_health(durable_store, case_id, evaluated_at)
    scenario_blockers: list[dict[str, Any]] = []
    if not source_locked:
        scenario_status = "needs_attention"
        scenario_summary = "Lock the Annual source and analysis basis before drafting scenarios."
    elif scenarios["baseline_count"] == 0:
        item = _blocker(
            code="baseline_scenario_missing",
            check_id="scenarios",
            detail="The case has no current baseline scenario.",
            why="Every comparison and grouped confirmation needs one immutable baseline request.",
            rule_id="AUT-SCENARIO-1",
            rule="A case has exactly one current baseline and no more than three current alternatives.",
            action_id="create_scenario",
            action_label="Create the baseline scenario",
            deep_link="#autonomy-compare",
        )
        blockers.append(item)
        scenario_blockers.append(item)
        scenario_status = "needs_attention"
        scenario_summary = item["detail"]
    elif not scenarios["validated_baseline"]:
        item = _blocker(
            code="baseline_scenario_not_validated",
            check_id="scenarios",
            detail="The current baseline scenario has not passed deterministic validation.",
            why="Only a validated immutable request may cross the human execution boundary.",
            rule_id="AUT-SCENARIO-3",
            rule="Every selected current scenario revision must be validated against its locked source, basis, evidence receipts, and TEA contract.",
            action_id="validate_scenario",
            action_label="Validate the baseline scenario",
            deep_link="#autonomy-compare",
        )
        blockers.append(item)
        scenario_blockers.append(item)
        scenario_status = "needs_attention"
        scenario_summary = item["detail"]
    else:
        scenario_status = "passed"
        scenario_summary = (
            f"{scenarios['validated_count']} current scenario revision(s) are "
            "validated or already confirmed."
        )
    checks.append(
        _check(
            "scenarios",
            "Scenario validation",
            scenario_status,
            scenario_summary,
            rule_id="AUT-SCENARIO-3",
            exact_rule="Every selected current scenario must match the immutable case source and basis, reference verified accepted evidence, and pass the existing TEA validators before confirmation.",
            details=scenarios,
            blockers=scenario_blockers,
        )
    )

    jobs = _job_health(durable_store, evaluated_at)
    if jobs["stale_count"]:
        jobs_status = "stale"
        jobs_summary = f"{jobs['stale_count']} running job(s) have a stale heartbeat."
    elif jobs["active_count"] or jobs["failed_count"] or jobs["interrupted_count"]:
        jobs_status = "needs_attention"
        jobs_summary = "Durable job state includes active, failed, or interrupted work; no Autonomy action will change it."
    else:
        jobs_status = "passed"
        jobs_summary = "No active, failed, interrupted, or stale durable work requires attention."
    checks.append(
        _check(
            "job_health",
            "Durable job state",
            jobs_status,
            jobs_summary,
            rule_id="AUT-JOB-1",
            exact_rule="Readiness observes durable leases and terminal states but never retries, creates, or mutates jobs.",
            details=jobs,
        )
    )

    agent = _agent_availability()
    agent_blockers: list[dict[str, Any]] = []
    if agent["available"]:
        agent_status = "passed"
        agent_summary = "The separate read-only Decision Agent is available."
    else:
        agent_status = "needs_attention"
        agent_summary = "The Decision Agent is unavailable; deterministic readiness and manual workflows remain available."
        agent_blockers.append(
            _blocker(
                code="decision_agent_unavailable",
                check_id="agent",
                detail=agent_summary,
                why="Agent explanations are optional and never define readiness or permissions.",
                rule_id="AUT-AGENT-1",
                rule="Agent availability never weakens deterministic readiness or blocks existing manual workflows.",
                action_id="continue_without_agent",
                action_label="Continue with deterministic readiness",
                deep_link="#autonomy-readiness",
                blocking=False,
            )
        )
    checks.append(
        _check(
            "agent",
            "Decision Agent",
            agent_status,
            agent_summary,
            rule_id="AUT-AGENT-1",
            exact_rule="The Decision Agent is a bounded read-only explanation surface and is never required to preserve manual access.",
            details=agent,
            blockers=agent_blockers,
        )
    )

    checks.append(
        _check(
            "phase_boundary",
            "Phase boundary",
            "passed",
            "Deterministic scenarios, named-human TEA confirmation, verified comparison bundles, and unsigned Decision Brief revisions are available; sign-off and reporting remain unavailable.",
            rule_id="AUT-PHASE-2",
            exact_rule="Only authenticated deterministic services and explicit named-human confirmation may mutate scenarios or create TEA jobs; comparison and Decision Brief services are read-only over immutable results, and the Decision Agent remains result-blind and read-only.",
        )
    )

    blocking_items = [item for item in blockers if item.get("blocking") is not False]
    hard_blocked = any(
        item["check_id"] in {"calibration", "annual_source", "weather_coverage"}
        for item in blocking_items
    )
    current_status = str(case_record.get("status") or "draft")
    ready_to_run = bool(
        not blocking_items
        and scenarios["validated_baseline"]
        and current_status in {"draft", "evidence_needed", "blocked", "ready_to_run"}
    )
    if hard_blocked:
        overall_status = "blocked"
        suggested_status = "blocked"
    elif blocking_items:
        overall_status = "needs_attention"
        suggested_status = "evidence_needed"
    else:
        overall_status = "passed"
        if current_status in {"running", "results_ready"}:
            suggested_status = current_status
        elif current_status == "draft":
            # Preserve the approved state graph; normal evidence reconciliation
            # advances a new case through evidence_needed before ready_to_run.
            suggested_status = "evidence_needed"
        else:
            suggested_status = "ready_to_run"
    supported_actions: list[dict[str, Any]] = []
    seen_action_ids: set[str] = set()
    for item in [*blocking_items, *agent_blockers]:
        action = item["closest_supported_action"]
        if action["id"] not in seen_action_ids:
            seen_action_ids.add(action["id"])
            supported_actions.append(action)
    actions = lifecycle.phase_actions_for_state(
        case_record.get("status"),
        source_locked=source_locked,
        has_pending_evidence=bool(evidence["pending_count"]),
        has_validated_scenarios=bool(scenarios["validated_count"]),
        has_retryable_execution=bool(scenarios["retryable_execution"]),
        has_cancellable_execution=bool(scenarios["cancellable_execution"]),
        agent_available=bool(agent["available"]),
    )
    return {
        "schema_version": READINESS_SCHEMA_VERSION,
        "case_id": case_id,
        "case_revision": int(case_record.get("revision") or 0),
        "evaluated_at": evaluated_at.isoformat(),
        "overall_status": overall_status,
        "ready_to_run": ready_to_run,
        "suggested_case_status": suggested_status,
        "checks": checks,
        "blockers": blockers,
        "supported_next_actions": supported_actions,
        "allowed_case_actions": actions,
        "eligible_annual_sources": eligible_sources,
        "supported_analysis_bases": list(SUPPORTED_ANALYSIS_BASES),
        "case": serializers.public_decision_case(case_record),
        "phase_boundary": {
            "current_phase": "autonomy_decision_brief",
            "non_runnable_suggestions_only": True,
            "scenario_execution_available": True,
            "tea_confirmation_available": True,
            "pre_run_values_label": "inputs_or_hypotheses",
            "decision_brief_available": True,
            "decision_brief_result_interpretation": "deterministic_server_only",
            "recommendation_contract_state": "classification_pending_contract",
            "decision_signoff_available": False,
            "report_generation_available": False,
        },
    }
