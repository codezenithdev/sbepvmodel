"""Bounded, read-only TEA evidence for the Solar Agent.

The browser supplies only the identity of the TEA job currently visible in the
dashboard.  Every economic value is read back from the durable store, checked
against its saved hashes, and projected through a small public allowlist before
it can be returned to the model.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import hashlib
import json
import re
import secrets
from typing import Any

from sbepv.agent.technoeconomic_tool_contract import (
    TECHNOECONOMIC_EVIDENCE_SECTIONS,
    TECHNOECONOMIC_EVIDENCE_TOOL_NAME,
)
from sbepv.api import state
from sbepv.store import TECHNOECONOMIC_ID_PREFIX, AgentStoreError


TOOL_NAME = TECHNOECONOMIC_EVIDENCE_TOOL_NAME
EVIDENCE_SECTIONS = TECHNOECONOMIC_EVIDENCE_SECTIONS
MAX_EVIDENCE_BYTES = 48_000
MAX_CHART_POINTS_PER_SERIES = 240
_METRIC_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.:/-]{1,200}$")
_PRIVATE_PATH_PATTERN = re.compile(
    r"(?:^|[\s'\"(])(?:[A-Za-z]:[\\/]|\\\\[^\\\s]+\\|"
    r"/(?:home|users|var|tmp|opt|srv|mnt)/)",
    re.IGNORECASE,
)
_PRIVATE_KEY_PARTS = (
    "api_key",
    "credential",
    "lease",
    "password",
    "secret",
    "storage_key",
    "token",
    "traceback",
)


def _canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _visible_job_id(current_config: dict[str, Any] | None) -> str | None:
    if not isinstance(current_config, dict):
        return None
    visible = current_config.get("technoeconomic_analysis")
    if not isinstance(visible, dict):
        return None
    job_id = visible.get("job_id")
    if not isinstance(job_id, str):
        return None
    normalized = job_id.strip()
    if not normalized.startswith(TECHNOECONOMIC_ID_PREFIX):
        return None
    return normalized


def _is_private_key(key: str) -> bool:
    normalized = key.lower()
    return (
        normalized == "path"
        or normalized.endswith("_path")
        or any(part in normalized for part in _PRIVATE_KEY_PARTS)
    )


def _public_value(
    value: Any,
    *,
    depth: int = 0,
    list_limit: int = 240,
) -> Any:
    """Return ordinary JSON data without private locations or unbounded fields."""

    if depth >= 10:
        return {"omitted": "depth_limit"}
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for index, (raw_key, item) in enumerate(value.items()):
            if index >= 160:
                result["omitted_for_length"] = True
                break
            key = str(raw_key)
            if _is_private_key(key):
                continue
            result[key] = _public_value(
                item,
                depth=depth + 1,
                list_limit=list_limit,
            )
        return result
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        values = list(value)
        result = [
            _public_value(item, depth=depth + 1, list_limit=list_limit)
            for item in values[:list_limit]
        ]
        if len(values) > list_limit:
            result.append(
                {
                    "omitted_item_count": len(values) - list_limit,
                    "reason": "length_limit",
                }
            )
        return result
    if isinstance(value, str):
        if _PRIVATE_PATH_PATTERN.search(value):
            return "[private filesystem location omitted]"
        return value if len(value) <= 4_000 else value[:4_000] + "..."
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)[:4_000]


def _unavailable(
    *,
    section: str | None,
    reason: str,
    job_id: str | None = None,
    job_state: str | None = None,
    metric_id: str | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "schema_version": "technoeconomic-agent-evidence-v1",
        "status": "unavailable",
        "read_only": True,
        "server_authoritative": True,
        "section": section,
        "reason": reason,
    }
    if job_id:
        result["job_id"] = job_id
    if job_state:
        result["job_state"] = job_state
    if metric_id:
        result["metric_id"] = metric_id
    return result


def _verified_job(
    current_config: dict[str, Any] | None,
    *,
    section: str,
    metric_id: str | None,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    job_id = _visible_job_id(current_config)
    if not job_id:
        return None, _unavailable(
            section=section,
            metric_id=metric_id,
            reason="no_visible_technoeconomic_job",
        )
    try:
        job = state.AGENT_STORE.get_technoeconomic_job(job_id)
    except (AgentStoreError, ValueError):
        return None, _unavailable(
            section=section,
            metric_id=metric_id,
            job_id=job_id,
            reason="visible_technoeconomic_job_could_not_be_read",
        )
    if not isinstance(job, dict):
        return None, _unavailable(
            section=section,
            metric_id=metric_id,
            job_id=job_id,
            reason="visible_technoeconomic_job_not_found",
        )
    job_state = str(job.get("state") or "unknown")
    if job_state != "done":
        return None, _unavailable(
            section=section,
            metric_id=metric_id,
            job_id=str(job.get("id") or job_id),
            job_state=job_state,
            reason="visible_technoeconomic_job_not_complete",
        )

    request = job.get("request")
    snapshot = job.get("source_snapshot")
    submission = job.get("submission_provenance")
    result = job.get("result")
    provenance = job.get("result_provenance")
    if not all(
        isinstance(item, Mapping)
        for item in (request, snapshot, submission, result, provenance)
    ):
        return None, _unavailable(
            section=section,
            metric_id=metric_id,
            job_id=str(job.get("id") or job_id),
            job_state=job_state,
            reason="completed_job_evidence_is_incomplete",
        )

    expected = {
        "request": provenance.get("request_sha256"),
        "source_snapshot": provenance.get("source_snapshot_sha256"),
        "submission_provenance": provenance.get("submission_provenance_sha256"),
        "result": provenance.get("routine_result_sha256"),
    }
    stored = {
        "source_snapshot": job.get("source_snapshot_sha256"),
        "submission_provenance": job.get("submission_provenance_sha256"),
    }
    if any(
        not isinstance(value, str) or len(value) != 64
        for value in expected.values()
    ):
        return None, _unavailable(
            section=section,
            metric_id=metric_id,
            job_id=str(job.get("id") or job_id),
            job_state=job_state,
            reason="integrity_hashes_are_missing",
        )
    try:
        calculated = {
            "request": _canonical_sha256(request),
            "source_snapshot": _canonical_sha256(snapshot),
            "submission_provenance": _canonical_sha256(submission),
            "result": _canonical_sha256(result),
        }
    except (TypeError, ValueError, OverflowError):
        return None, _unavailable(
            section=section,
            metric_id=metric_id,
            job_id=str(job.get("id") or job_id),
            job_state=job_state,
            reason="evidence_is_not_canonical_json",
        )
    if any(
        not secrets.compare_digest(calculated[name], str(expected[name]))
        for name in calculated
    ) or any(
        stored[name] is not None
        and not secrets.compare_digest(calculated[name], str(stored[name]))
        for name in stored
    ):
        return None, _unavailable(
            section=section,
            metric_id=metric_id,
            job_id=str(job.get("id") or job_id),
            job_state=job_state,
            reason="integrity_hash_check_failed",
        )
    return job, {
        "request_sha256": calculated["request"],
        "source_snapshot_sha256": calculated["source_snapshot"],
        "submission_provenance_sha256": calculated["submission_provenance"],
        "validated_kernel_request_sha256": provenance.get(
            "validated_kernel_request_sha256"
        ),
        "routine_result_sha256": calculated["result"],
        "result_provenance_sha256": _canonical_sha256(provenance),
    }


def _paired_headlines(result: Mapping[str, Any]) -> dict[str, Any] | None:
    paired = result.get("paired_commercial")
    if not isinstance(paired, Mapping):
        return None
    systems: dict[str, Any] = {}
    raw_systems = paired.get("systems")
    if isinstance(raw_systems, Mapping):
        for technology in ("solectria", "solaredge"):
            system = raw_systems.get(technology)
            if not isinstance(system, Mapping):
                continue
            systems[technology] = {
                key: _public_value(system.get(key))
                for key in (
                    "technology",
                    "source_applied_capacity_w",
                    "source_rating_basis",
                    "capacity_scale_factor",
                    "headline_metric_id",
                    "unit",
                    "percentiles",
                )
                if key in system
            }
    return {
        key: _public_value(paired.get(key))
        for key in (
            "target_capacity_w",
            "target_rating_basis",
            "transfer_method",
            "constant_dollar_cost_year",
        )
        if key in paired
    } | {
        "systems": systems,
        "lcoe_delta_se_minus_sol": _public_value(
            paired.get("lcoe_delta_se_minus_sol") or {}
        ),
    }


def _overview(job: Mapping[str, Any]) -> dict[str, Any]:
    result = job["result"]
    return {
        key: _public_value(result.get(key))
        for key in (
            "analysis_basis",
            "project_life_years",
            "realization_count",
            "eligible_weather_years",
            "energy_available",
            "commercial_transfer_status",
            "cost_stack_completeness",
            "convergence",
        )
        if key in result
    } | {"paired_commercial": _paired_headlines(result)}


def _assumptions(job: Mapping[str, Any]) -> dict[str, Any]:
    submission = job["submission_provenance"]
    return {
        "immutable_request": _public_value(job["request"], list_limit=120),
        "paired_commercial_receipt": _public_value(
            submission.get("paired_commercial_receipt"), list_limit=120
        ),
        "commercial_reference_design": _public_value(
            submission.get("commercial_reference_design"), list_limit=120
        ),
        "evidence_receipt": _public_value(
            submission.get("evidence_receipt"), list_limit=120
        ),
    }


def _formulas(job: Mapping[str, Any]) -> dict[str, Any]:
    kernel = job["result_provenance"].get("kernel")
    if not isinstance(kernel, Mapping):
        return {"status": "unavailable", "reason": "kernel_provenance_missing"}
    return {
        key: _public_value(kernel.get(key), list_limit=120)
        for key in (
            "calculation_contract_version",
            "analysis_basis",
            "statistics",
            "capacity_normalization",
            "commercial_scaling",
            "commercial_standalone",
            "commercial_paired",
        )
        if key in kernel
    }


def _metric(job: Mapping[str, Any], metric_id: str | None) -> dict[str, Any]:
    result = job["result"]
    summaries = result.get("summaries")
    summaries = summaries if isinstance(summaries, Mapping) else {}
    per_weather_year = result.get("per_weather_year")
    per_weather_year = (
        per_weather_year
        if isinstance(per_weather_year, Sequence)
        and not isinstance(per_weather_year, (str, bytes, bytearray))
        else []
    )
    weather_metric_ids: set[str] = set()
    for row in per_weather_year:
        if isinstance(row, Mapping) and isinstance(row.get("metrics"), Mapping):
            weather_metric_ids.update(str(key) for key in row["metrics"])
    available = sorted(
        {
            *(
                str(key)
                for key, value in summaries.items()
                if isinstance(value, Mapping)
            ),
            *weather_metric_ids,
        }
    )
    if metric_id is None:
        return {
            "status": "metric_id_required",
            "available_metric_ids": available[:160],
        }
    if not _METRIC_ID_PATTERN.fullmatch(metric_id):
        return {
            "status": "unavailable",
            "reason": "invalid_metric_id",
            "available_metric_ids": available[:160],
        }
    summary = summaries.get(metric_id)
    weather_summaries = []
    for row in per_weather_year:
        if not isinstance(row, Mapping):
            continue
        metrics = row.get("metrics")
        weather_summary = metrics.get(metric_id) if isinstance(metrics, Mapping) else None
        if isinstance(weather_summary, Mapping):
            weather_summaries.append(
                {
                    "year": row.get("year"),
                    "realization_count": row.get("realization_count"),
                    "realization_share": row.get("realization_share"),
                    "summary": _public_value(weather_summary, list_limit=40),
                }
            )
    if not isinstance(summary, Mapping) and not weather_summaries:
        return {
            "status": "unavailable",
            "reason": "unknown_metric_id",
            "available_metric_ids": available[:160],
        }
    return {
        "metric_id": metric_id,
        "overall_summary": (
            _public_value(summary, list_limit=120)
            if isinstance(summary, Mapping)
            else None
        ),
        "per_weather_year": weather_summaries,
    }


def _cost_breakdown(job: Mapping[str, Any]) -> dict[str, Any]:
    result = job["result"]
    request = job["request"]
    paired_result = result.get("paired_commercial")
    paired_request = request.get("paired_commercial")
    output: dict[str, Any] = {
        "constant_dollar_cost_year": result.get("constant_dollar_cost_year"),
        "systems": {},
    }
    if isinstance(paired_result, Mapping):
        output["constant_dollar_cost_year"] = paired_result.get(
            "constant_dollar_cost_year"
        )
        systems = paired_result.get("systems")
        if isinstance(systems, Mapping):
            for technology in ("solectria", "solaredge"):
                system = systems.get(technology)
                if isinstance(system, Mapping):
                    output["systems"][technology] = {
                        "summary": _public_value(
                            system.get("commercial_cost_line_summaries"),
                            list_limit=80,
                        )
                    }
    if isinstance(paired_request, Mapping):
        for system in paired_request.get("systems") or []:
            if not isinstance(system, Mapping):
                continue
            technology = system.get("technology")
            if technology not in {"solectria", "solaredge"}:
                continue
            output["systems"].setdefault(str(technology), {})["assumptions"] = (
                _public_value(system.get("cost_lines"), list_limit=80)
            )
    return output


def _cdf_projection(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, Mapping):
        return None
    values = list(raw.get("values") or [])
    probabilities = list(raw.get("cumulative_probability") or [])
    if not values or len(values) != len(probabilities):
        return None
    if len(values) <= MAX_CHART_POINTS_PER_SERIES:
        indexes = list(range(len(values)))
    else:
        last = len(values) - 1
        indexes = sorted(
            {
                round(index * last / (MAX_CHART_POINTS_PER_SERIES - 1))
                for index in range(MAX_CHART_POINTS_PER_SERIES)
            }
        )
    return {
        "population_count": raw.get("population_count"),
        "source_point_count": raw.get("source_point_count", len(values)),
        "returned_point_count": len(indexes),
        "projection": "deterministic_display_subset_including_endpoints",
        "values": [values[index] for index in indexes],
        "cumulative_probability": [probabilities[index] for index in indexes],
        "full_cdf_sha256": raw.get("full_cdf_sha256"),
    }


def _chart(job: Mapping[str, Any]) -> dict[str, Any]:
    paired = job["result"].get("paired_commercial")
    if not isinstance(paired, Mapping):
        return {"status": "unavailable", "reason": "paired_chart_data_missing"}
    systems: dict[str, Any] = {}
    raw_systems = paired.get("systems")
    if isinstance(raw_systems, Mapping):
        for technology in ("solectria", "solaredge"):
            system = raw_systems.get(technology)
            if not isinstance(system, Mapping):
                continue
            systems[technology] = {
                "headline_metric_id": system.get("headline_metric_id"),
                "unit": system.get("unit"),
                "percentiles": _public_value(system.get("percentiles")),
                "cdf": _cdf_projection(system.get("cdf")),
            }
    kernel = job["result_provenance"].get("kernel")
    commercial = kernel.get("commercial_paired") if isinstance(kernel, Mapping) else None
    return {
        "curve_definition": (
            commercial.get("cdf") if isinstance(commercial, Mapping) else None
        ),
        "systems": systems,
        "lcoe_delta_se_minus_sol": _public_value(
            paired.get("lcoe_delta_se_minus_sol"), list_limit=120
        ),
    }


def _weather_years(job: Mapping[str, Any]) -> dict[str, Any]:
    result = job["result"]
    snapshot = job["source_snapshot"]
    per_weather_year = result.get("per_weather_year")
    rows = (
        list(per_weather_year)
        if isinstance(per_weather_year, Sequence)
        and not isinstance(per_weather_year, (str, bytes, bytearray))
        else []
    )
    metric_ids: set[str] = set()
    compact_rows: list[dict[str, Any]] = []
    for raw_row in rows[:100]:
        if not isinstance(raw_row, Mapping):
            continue
        metrics = raw_row.get("metrics")
        metrics = metrics if isinstance(metrics, Mapping) else {}
        metric_ids.update(str(key) for key in metrics)
        headline_metrics = {
            str(key): _public_value(value, list_limit=40)
            for key, value in metrics.items()
            if "lcoe" in str(key).lower()
        }
        compact_rows.append(
            {
                key: _public_value(raw_row.get(key), list_limit=40)
                for key in (
                    "year",
                    "realization_count",
                    "realization_share",
                    "reason",
                    "commercial_target_capacity_w",
                    "commercial_target_rating_basis",
                    "commercial_transfer_method",
                    "systems",
                )
                if key in raw_row
            }
            | {"headline_lcoe_metrics": headline_metrics}
        )
    return {
        "eligible_weather_years": _public_value(
            result.get("eligible_weather_years"), list_limit=100
        ),
        "per_weather_year": compact_rows,
        "available_metric_ids": sorted(metric_ids),
        "metric_detail_hint": (
            "Use the metric section with one available_metric_id for its exact "
            "overall and per-weather-year summaries."
        ),
        "source_energy_rows": _public_value(
            snapshot.get("eligible_paired_energy_rows"), list_limit=100
        ),
    }


def _diagnostics(job: Mapping[str, Any]) -> dict[str, Any]:
    result = job["result"]
    return {
        key: _public_value(result.get(key), list_limit=80)
        for key in (
            "convergence",
            "sensitivity",
            "input_status",
            "evidence_class_counts",
            "common_cost_audit",
        )
        if key in result
    }


def _source(job: Mapping[str, Any]) -> dict[str, Any]:
    snapshot = job["source_snapshot"]
    result = job["result"]
    provenance = job["result_provenance"]
    return {
        "source_annual_job_id": job.get("source_annual_job_id"),
        "source_snapshot": {
            key: _public_value(snapshot.get(key), list_limit=100)
            for key in (
                "schema_version",
                "eligibility_version",
                "source_annual_job_id",
                "capacity_manifest",
                "eligible_paired_energy_rows",
            )
            if key in snapshot
        },
        "applied_capacities": _public_value(result.get("applied_capacities")),
        "installed_capacities": _public_value(result.get("capacities")),
        "source_artifact_identity": _public_value(
            provenance.get("source_artifact")
        ),
    }


def _exports(job: Mapping[str, Any]) -> dict[str, Any]:
    result = job["result"]
    provenance = job["result_provenance"]
    return {
        "public_manifest": _public_value(result.get("exports"), list_limit=120),
        "manifest_identity": _public_value(provenance.get("exports")),
    }


def _section_data(
    job: Mapping[str, Any], section: str, metric_id: str | None
) -> dict[str, Any]:
    if section == "overview":
        return _overview(job)
    if section == "assumptions":
        return _assumptions(job)
    if section == "formulas":
        return _formulas(job)
    if section == "metric":
        return _metric(job, metric_id)
    if section == "cost_breakdown":
        return _cost_breakdown(job)
    if section == "chart":
        return _chart(job)
    if section == "weather_years":
        return _weather_years(job)
    if section == "diagnostics":
        return _diagnostics(job)
    if section == "source":
        return _source(job)
    return _exports(job)


def get_technoeconomic_evidence(
    current_config: dict[str, Any] | None,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    """Resolve one evidence section for the currently visible durable TEA job."""

    if not isinstance(arguments, dict):
        return _unavailable(section=None, reason="tool_arguments_must_be_an_object")
    if set(arguments) - {"section", "metric_id"}:
        return _unavailable(
            section=None,
            reason="unsupported_tool_argument",
        )
    section = arguments.get("section")
    metric_id = arguments.get("metric_id")
    if section not in EVIDENCE_SECTIONS:
        return _unavailable(section=None, reason="unknown_evidence_section")
    if metric_id is not None and not isinstance(metric_id, str):
        return _unavailable(
            section=str(section), reason="metric_id_must_be_text_or_null"
        )
    if section != "metric" and metric_id is not None:
        return _unavailable(
            section=str(section), reason="metric_id_is_only_valid_for_metric_section"
        )
    job, identity = _verified_job(
        current_config,
        section=str(section),
        metric_id=metric_id,
    )
    if job is None:
        return identity
    result = job["result"]
    payload = {
        "schema_version": "technoeconomic-agent-evidence-v1",
        "status": "available",
        "read_only": True,
        "server_authoritative": True,
        "section": section,
        "metric_id": metric_id,
        "job_id": str(job.get("id")),
        "job_state": str(job.get("state")),
        "calculation_contract_version": result.get(
            "calculation_contract_version"
        ),
        "hashes": _public_value(identity),
        "data": _section_data(job, str(section), metric_id),
    }
    if len(json.dumps(payload, default=str, ensure_ascii=True)) > MAX_EVIDENCE_BYTES:
        return _unavailable(
            section=str(section),
            metric_id=metric_id,
            job_id=str(job.get("id")),
            job_state=str(job.get("state")),
            reason="evidence_section_exceeds_safe_response_limit",
        )
    return payload


def evidence_tool_context(job: Mapping[str, Any]) -> dict[str, Any]:
    """Return the small tool hint embedded in the base chat context."""

    result = job.get("result")
    provenance = job.get("result_provenance")
    result = result if isinstance(result, Mapping) else {}
    provenance = provenance if isinstance(provenance, Mapping) else {}
    return {
        "name": TOOL_NAME,
        "available": job.get("state") == "done",
        "bound_to_visible_job": True,
        "read_only": True,
        "sections": list(EVIDENCE_SECTIONS),
        "calculation_contract_version": result.get(
            "calculation_contract_version"
        ),
        "request_sha256": provenance.get("request_sha256"),
        "routine_result_sha256": provenance.get("routine_result_sha256"),
        "use": (
            "Call this tool for formulas, assumptions, a named metric, cost lines, "
            "chart points, weather-year detail, diagnostics, source facts, or exports."
        ),
    }


__all__ = [
    "EVIDENCE_SECTIONS",
    "MAX_CHART_POINTS_PER_SERIES",
    "TOOL_NAME",
    "evidence_tool_context",
    "get_technoeconomic_evidence",
]
