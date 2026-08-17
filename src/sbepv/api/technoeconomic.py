"""Fail-closed Annual Simulation source verification for technoeconomic jobs.

This module contains no routes and performs no database writes.  Its one deliberate
filesystem mutation hardens verified MIDC bytes into private content-addressed
Annual-owned storage.  It turns already resolved durable records into one canonical
source snapshot that a later store transaction can compare and insert atomically.
Calculation workers must consume that snapshot rather than re-reading a mutable
Annual job.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
import os
from pathlib import Path
import secrets
import shutil
import sqlite3
from typing import Any
import uuid

from sbepv import calibration, model, reporting
from sbepv import technoeconomic as technoeconomic_kernel
from sbepv.api import config, timewindows
from sbepv.api.schemas import (
    ANNUAL_APPLIED_CAPACITY_NORMALIZATION,
    TechnoeconomicDistributionRequest,
    TechnoeconomicEvidenceRequest,
    TechnoeconomicSubmissionRequest,
)
from sbepv.reporting import SourceFingerprintMismatch


ANNUAL_SOURCE_SNAPSHOT_SCHEMA_VERSION = 1
ANNUAL_SOURCE_ELIGIBILITY_VERSION = "tea-annual-source-v1"
ANNUAL_SOURCE_ARTIFACT_SCHEMA_VERSION = 1
TECHNOECONOMIC_SUBMISSION_PROVENANCE_SCHEMA_VERSION = 1


class AnnualSourceValidationError(ValueError):
    """A completed Annual Simulation cannot be frozen as a TEA energy source."""

    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code
        self.detail = detail


def canonical_json_text(value: Any) -> str:
    """Return the exact canonical JSON representation used by the durable store."""

    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError, OverflowError) as exc:
        raise AnnualSourceValidationError(
            "noncanonical_json",
            "Annual source evidence must be finite and JSON serializable.",
        ) from exc


def canonical_json_sha256(value: Any) -> str:
    """Return a SHA-256 matching ``AgentStore`` canonical JSON persistence."""

    try:
        return hashlib.sha256(canonical_json_text(value).encode("utf-8")).hexdigest()
    except (TypeError, ValueError, OverflowError) as exc:
        raise AnnualSourceValidationError(
            "noncanonical_json",
            "Annual source evidence must be finite and JSON serializable.",
        ) from exc


def _fail(code: str, detail: str) -> None:
    raise AnnualSourceValidationError(code, detail)


def _mapping(value: Any, code: str, detail: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail(code, detail)
    return value


def _sequence(value: Any, code: str, detail: str) -> Sequence[Any]:
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes, bytearray))
    ):
        _fail(code, detail)
    return value


def _nonempty_text(value: Any, code: str, detail: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\0" in value:
        _fail(code, detail)
    return value.strip()


def _sha256(value: Any, code: str, detail: str) -> str:
    normalized = _nonempty_text(value, code, detail).lower()
    if len(normalized) != 64 or any(
        character not in "0123456789abcdef" for character in normalized
    ):
        _fail(code, detail)
    return normalized


def _positive_int(value: Any, code: str, detail: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        _fail(code, detail)
    return int(value)


def _finite_float(value: Any, code: str, detail: str) -> float:
    if isinstance(value, bool):
        _fail(code, detail)
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise AnnualSourceValidationError(code, detail) from exc
    if not math.isfinite(result):
        _fail(code, detail)
    return result


def _annual_curtailment_state(
    record: Mapping[str, Any],
    *,
    label: str,
) -> tuple[bool, float | None] | None:
    """Validate one optional Annual curtailment record.

    Older uncurtailed Annual fixtures may omit both keys.  Once either key is
    present, both are required so a clipped TEA denominator is never inferred from
    partial or contradictory provenance.
    """

    has_enabled = "curtailment_enabled" in record
    has_limit = "curtailment_limit_kw" in record
    if not has_enabled and not has_limit:
        return None
    if not has_enabled or not has_limit:
        _fail(
            "annual_curtailment_record_incomplete",
            f"The Annual {label} curtailment record is incomplete.",
        )
    enabled = record.get("curtailment_enabled")
    if not isinstance(enabled, bool):
        _fail(
            "annual_curtailment_record_invalid",
            f"The Annual {label} curtailment-enabled value is invalid.",
        )
    raw_limit = record.get("curtailment_limit_kw")
    if not enabled:
        if raw_limit is not None:
            _fail(
                "annual_curtailment_record_invalid",
                f"The disabled Annual {label} curtailment record retains a limit.",
            )
        return False, None
    limit = _finite_float(
        raw_limit,
        "annual_curtailment_record_invalid",
        f"The enabled Annual {label} curtailment limit is invalid.",
    )
    if limit <= 0:
        _fail(
            "annual_curtailment_record_invalid",
            f"The enabled Annual {label} curtailment limit must be positive.",
        )
    return True, limit


def _verify_annual_curtailment_consistency(
    request: Mapping[str, Any],
    window: Mapping[str, Any],
    stats: Mapping[str, Any],
) -> None:
    """Prove that the requested and actually reported clipping settings agree."""

    request_state = _annual_curtailment_state(request, label="request")
    window_state = _annual_curtailment_state(window, label="result window")
    stats_state = _annual_curtailment_state(stats, label="result statistics")
    if request_state is None and window_state is None and stats_state is None:
        return

    # An omitted legacy request means the historical default: curtailment off.
    expected = request_state or (False, None)
    if window_state is None or stats_state is None:
        _fail(
            "annual_curtailment_provenance_missing",
            "The Annual result does not fully report its applied curtailment setting.",
        )
    if window_state[0] != expected[0] or stats_state[0] != expected[0]:
        _fail(
            "annual_curtailment_provenance_mismatch",
            "The Annual request and result disagree about whether curtailment was applied.",
        )
    if not expected[0]:
        return
    assert expected[1] is not None
    assert window_state[1] is not None
    assert stats_state[1] is not None
    if Decimal(str(window_state[1])) != Decimal(str(expected[1])):
        _fail(
            "annual_curtailment_provenance_mismatch",
            "The Annual request and result window use different curtailment limits.",
        )
    # Annual statistics intentionally round the applied limit to three decimals.
    if not math.isclose(stats_state[1], expected[1], rel_tol=0.0, abs_tol=0.0005):
        _fail(
            "annual_curtailment_provenance_mismatch",
            "The Annual request and result statistics use different curtailment limits.",
        )


def _canonical_equal(left: Any, right: Any) -> bool:
    return canonical_json_sha256(left) == canonical_json_sha256(right)


def _require_digest_match(
    left: str,
    right: str,
    code: str,
    detail: str,
) -> None:
    if not secrets.compare_digest(left.lower(), right.lower()):
        _fail(code, detail)


def _validated_review_quality(
    quality: Mapping[str, Any],
    *,
    review_id: str,
    reviewed_source_sha256: str,
    origin_request: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate the complete review receipt before freezing it as provenance."""

    required = {
        "review_id",
        "source_sha256",
        "reviewed_source_sha256",
        "reviewed_at",
        "submitted_decisions",
        "report",
        "cleaning",
    }
    if not required.issubset(quality):
        _fail(
            "origin_review_incomplete",
            "The origin data-quality review receipt is incomplete.",
        )
    if quality.get("review_id") != review_id:
        _fail(
            "origin_review_mismatch",
            "The origin validation data-quality review ID does not match.",
        )
    _sha256(
        quality.get("source_sha256"),
        "origin_review_raw_source_hash_invalid",
        "The origin review's raw-source SHA-256 is invalid.",
    )
    frozen_reviewed_hash = _sha256(
        quality.get("reviewed_source_sha256"),
        "origin_review_source_hash_invalid",
        "The reviewed origin source SHA-256 is invalid.",
    )
    _require_digest_match(
        frozen_reviewed_hash,
        reviewed_source_sha256,
        "origin_review_source_mismatch",
        "The reviewed origin source SHA-256 does not match the validation job.",
    )
    reviewed_at = _nonempty_text(
        quality.get("reviewed_at"),
        "origin_review_timestamp_invalid",
        "The origin review timestamp is missing or invalid.",
    )
    try:
        parsed_reviewed_at = datetime.fromisoformat(reviewed_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise AnnualSourceValidationError(
            "origin_review_timestamp_invalid",
            "The origin review timestamp is missing or invalid.",
        ) from exc
    if parsed_reviewed_at.utcoffset() is None:
        _fail(
            "origin_review_timestamp_invalid",
            "The origin review timestamp must include a UTC offset.",
        )

    submitted = _mapping(
        quality.get("submitted_decisions"),
        "origin_review_incomplete",
        "The origin review submitted-decision record is missing.",
    )
    normalized_submitted: dict[str, str] = {}
    for issue_id, action in submitted.items():
        normalized_id = _nonempty_text(
            issue_id,
            "origin_review_decisions_invalid",
            "The origin review contains an invalid decision issue ID.",
        )
        normalized_action = _nonempty_text(
            action,
            "origin_review_decisions_invalid",
            "The origin review contains an invalid decision action.",
        )
        if normalized_action not in {"retain", "exclude"}:
            _fail(
                "origin_review_decisions_invalid",
                "Origin review decision actions must be retain or exclude.",
            )
        normalized_submitted[normalized_id] = normalized_action

    report = _mapping(
        quality.get("report"),
        "origin_review_incomplete",
        "The origin data-quality report is missing.",
    )
    report_required = {"version", "source", "summary", "seasons", "issues"}
    if not report_required.issubset(report):
        _fail(
            "origin_review_incomplete",
            "The origin data-quality report is incomplete.",
        )
    report_version = report.get("version")
    if (
        isinstance(report_version, bool)
        or report_version != calibration.REPORT_VERSION
    ):
        _fail(
            "origin_review_report_invalid",
            "The origin data-quality report version is unsupported.",
        )
    report_source = _mapping(
        report.get("source"),
        "origin_review_report_invalid",
        "The origin data-quality report source record is invalid.",
    )
    source_required = {
        "row_count",
        "expected_interval_seconds",
        "requested_start",
        "requested_end",
        "first_timestamp",
        "last_timestamp",
    }
    if not source_required.issubset(report_source):
        _fail(
            "origin_review_incomplete",
            "The origin data-quality report source record is incomplete.",
        )
    source_row_count = report_source.get("row_count")
    if (
        isinstance(source_row_count, bool)
        or not isinstance(source_row_count, int)
        or source_row_count <= 0
    ):
        _fail(
            "origin_review_report_invalid",
            "The origin data-quality report source row count is invalid.",
        )
    _positive_int(
        report_source.get("expected_interval_seconds"),
        "origin_review_report_invalid",
        "The origin data-quality report source interval is invalid.",
    )
    for field in (
        "requested_start",
        "requested_end",
        "first_timestamp",
        "last_timestamp",
    ):
        value = report_source.get(field)
        _nonempty_text(
            value,
            "origin_review_report_invalid",
            f"The origin data-quality report source {field} is invalid.",
        )
    interval_value = origin_request.get("interval_value")
    interval_unit = origin_request.get("interval_unit")
    if (
        isinstance(interval_value, bool)
        or not isinstance(interval_value, int)
        or interval_value <= 0
        or interval_unit not in config.UNIT_SECONDS
    ):
        _fail(
            "origin_request_invalid",
            "The origin validation request interval is invalid.",
        )
    expected_interval_seconds = interval_value * config.UNIT_SECONDS[str(interval_unit)]
    if report_source.get("expected_interval_seconds") != expected_interval_seconds:
        _fail(
            "origin_review_request_mismatch",
            "The origin data-quality report interval differs from its immutable request.",
        )

    def aware_timestamp(field: str) -> datetime:
        value = _nonempty_text(
            report_source.get(field),
            "origin_review_report_invalid",
            f"The origin data-quality report source {field} is invalid.",
        )
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise AnnualSourceValidationError(
                "origin_review_report_invalid",
                f"The origin data-quality report source {field} is invalid.",
            ) from exc
        if parsed.utcoffset() is None:
            _fail(
                "origin_review_report_invalid",
                f"The origin data-quality report source {field} must be timezone-aware.",
            )
        return parsed.astimezone(timezone.utc)

    try:
        expected_start = datetime.fromisoformat(
            timewindows._iso(
                str(origin_request["from_date"]),
                str(origin_request.get("from_time") or "00:00"),
            )
        ).replace(tzinfo=timezone.utc)
        expected_end = datetime.fromisoformat(
            timewindows._iso(
                str(origin_request["to_date"]),
                str(origin_request.get("to_time") or "00:00"),
            )
        ).replace(tzinfo=timezone.utc)
    except (KeyError, TypeError, ValueError) as exc:
        raise AnnualSourceValidationError(
            "origin_request_invalid",
            "The origin validation request window is invalid.",
        ) from exc
    requested_start = aware_timestamp("requested_start")
    requested_end = aware_timestamp("requested_end")
    first_timestamp = aware_timestamp("first_timestamp")
    last_timestamp = aware_timestamp("last_timestamp")
    if requested_start != expected_start or requested_end != expected_end:
        _fail(
            "origin_review_request_mismatch",
            "The origin data-quality report window differs from its immutable request.",
        )
    if not (
        requested_start < requested_end
        and requested_start <= first_timestamp <= last_timestamp < requested_end
    ):
        _fail(
            "origin_review_report_invalid",
            "The origin data-quality report timestamps are inconsistent.",
        )
    report_summary = _mapping(
        report.get("summary"),
        "origin_review_report_invalid",
        "The origin data-quality report summary is invalid.",
    )
    summary_required = {
        "status",
        "blocking",
        "issue_count",
        "actionable_issue_count",
        "affected_rows",
        "affected_row_pct",
        "missing_intervals",
        "severity_counts",
    }
    if not summary_required.issubset(report_summary):
        _fail(
            "origin_review_incomplete",
            "The origin data-quality report summary is incomplete.",
        )
    report_seasons = _sequence(
        report.get("seasons"),
        "origin_review_report_invalid",
        "The origin data-quality season record is invalid.",
    )
    season_names: set[str] = set()
    for season in report_seasons:
        if not isinstance(season, Mapping) or not {
            "name",
            "months",
            "row_count",
            "first_timestamp",
            "last_timestamp",
        }.issubset(season):
            _fail(
                "origin_review_incomplete",
                "The origin data-quality report contains an incomplete season record.",
            )
        season_name = _nonempty_text(
            season.get("name"),
            "origin_review_report_invalid",
            "The origin data-quality report contains an invalid season name.",
        )
        if season_name in season_names:
            _fail(
                "origin_review_report_invalid",
                "The origin data-quality report contains a duplicate season.",
            )
        season_names.add(season_name)
        month_label = _nonempty_text(
            season.get("months"),
            "origin_review_report_invalid",
            "The origin data-quality report season months are invalid.",
        )
        if (
            season_name not in calibration.SEASON_MONTHS
            or month_label != calibration.SEASON_MONTHS[season_name]
        ):
            _fail(
                "origin_review_report_invalid",
                "The origin data-quality report season months are invalid.",
            )
        season_row_count = season.get("row_count")
        if (
            isinstance(season_row_count, bool)
            or not isinstance(season_row_count, int)
            or season_row_count <= 0
        ):
            _fail(
                "origin_review_report_invalid",
                "The origin data-quality report season row count is invalid.",
            )
        for field in ("first_timestamp", "last_timestamp"):
            _nonempty_text(
                season.get(field),
                "origin_review_report_invalid",
                f"The origin data-quality report season {field} is invalid.",
            )
    report_issues = _sequence(
        report.get("issues"),
        "origin_review_report_invalid",
        "The origin data-quality issue record is invalid.",
    )
    report_issue_ids: set[str] = set()
    issue_contracts: dict[str, dict[str, Any]] = {}
    severity_counts = {severity: 0 for severity in ("critical", "high", "medium", "low")}
    actionable_issue_count = 0
    issue_required = {
        "id",
        "category",
        "severity",
        "title",
        "description",
        "row_count",
        "columns",
        "allowed_actions",
        "recommended_action",
        "evidence",
        "affected_rows_available",
    }
    for issue in report_issues:
        if not isinstance(issue, Mapping) or not issue_required.issubset(issue):
            _fail(
                "origin_review_incomplete",
                "The origin data-quality report contains an incomplete issue.",
            )
        issue_id = _nonempty_text(
            issue.get("id"),
            "origin_review_report_invalid",
            "The origin data-quality report contains an invalid issue ID.",
        )
        if issue_id in report_issue_ids:
            _fail(
                "origin_review_report_invalid",
                "The origin data-quality report contains a duplicate issue ID.",
            )
        report_issue_ids.add(issue_id)
        for field in ("category", "title", "description"):
            _nonempty_text(
                issue.get(field),
                "origin_review_report_invalid",
                f"The origin data-quality issue {field} is invalid.",
            )
        severity = issue.get("severity")
        if severity not in severity_counts:
            _fail(
                "origin_review_report_invalid",
                "The origin data-quality issue severity is invalid.",
            )
        severity_counts[str(severity)] += 1
        issue_row_count = issue.get("row_count")
        if (
            isinstance(issue_row_count, bool)
            or not isinstance(issue_row_count, int)
            or issue_row_count < 0
        ):
            _fail(
                "origin_review_report_invalid",
                "The origin data-quality issue row count is invalid.",
            )
        columns = _sequence(
            issue.get("columns"),
            "origin_review_report_invalid",
            "The origin data-quality issue columns are invalid.",
        )
        if any(not isinstance(value, str) or not value for value in columns):
            _fail(
                "origin_review_report_invalid",
                "The origin data-quality issue columns are invalid.",
            )
        allowed_actions = list(
            _sequence(
                issue.get("allowed_actions"),
                "origin_review_report_invalid",
                "The origin data-quality issue actions are invalid.",
            )
        )
        if any(action not in {"retain", "exclude"} for action in allowed_actions):
            _fail(
                "origin_review_report_invalid",
                "The origin data-quality issue actions are invalid.",
            )
        if len(set(allowed_actions)) != len(allowed_actions):
            _fail(
                "origin_review_report_invalid",
                "The origin data-quality issue actions contain duplicates.",
            )
        if len(allowed_actions) > 1:
            actionable_issue_count += 1
        recommended = issue.get("recommended_action")
        if recommended not in {"retain", "exclude", "blocked"}:
            _fail(
                "origin_review_report_invalid",
                "The origin data-quality issue recommendation is invalid.",
            )
        if allowed_actions and recommended not in allowed_actions:
            _fail(
                "origin_review_report_invalid",
                "The origin data-quality issue recommendation is not an allowed action.",
            )
        _mapping(
            issue.get("evidence"),
            "origin_review_report_invalid",
            "The origin data-quality issue evidence is invalid.",
        )
        if not isinstance(issue.get("affected_rows_available"), bool):
            _fail(
                "origin_review_report_invalid",
                "The origin data-quality issue row-availability flag is invalid.",
            )
        issue_contracts[issue_id] = {
            "allowed_actions": tuple(allowed_actions),
            "recommended_action": str(recommended),
            "expected_affected_rows": (
                issue_row_count if issue["affected_rows_available"] else 0
            ),
        }

    summary_counts: dict[str, int] = {}
    for field in (
        "issue_count",
        "actionable_issue_count",
        "affected_rows",
        "missing_intervals",
    ):
        value = report_summary.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            _fail(
                "origin_review_report_invalid",
                "The origin data-quality report summary counts are invalid.",
            )
        summary_counts[field] = value
    if (
        summary_counts["issue_count"] != len(report_issues)
        or summary_counts["actionable_issue_count"] != actionable_issue_count
        or summary_counts["affected_rows"] > source_row_count
    ):
        _fail(
            "origin_review_report_invalid",
            "The origin data-quality report summary does not match its issues.",
        )
    supplied_severity_counts = _mapping(
        report_summary.get("severity_counts"),
        "origin_review_report_invalid",
        "The origin data-quality severity counts are invalid.",
    )
    if dict(supplied_severity_counts) != severity_counts:
        _fail(
            "origin_review_report_invalid",
            "The origin data-quality severity counts do not match its issues.",
        )
    affected_pct = _finite_float(
        report_summary.get("affected_row_pct"),
        "origin_review_report_invalid",
        "The origin data-quality affected-row percentage is invalid.",
    )
    expected_affected_pct = round(
        summary_counts["affected_rows"] / source_row_count * 100.0, 3
    )
    if not math.isclose(affected_pct, expected_affected_pct, abs_tol=5e-4):
        _fail(
            "origin_review_report_invalid",
            "The origin data-quality affected-row percentage is inconsistent.",
        )
    expected_blocking = severity_counts["critical"] > 0
    expected_status = (
        "blocked"
        if expected_blocking
        else "action_required"
        if report_issues
        else "clean"
    )
    if (
        not isinstance(report_summary.get("blocking"), bool)
        or report_summary.get("blocking") is not expected_blocking
        or report_summary.get("status") != expected_status
    ):
        _fail(
            "origin_review_report_invalid",
            "The origin data-quality report status does not match its issues.",
        )
    if expected_blocking:
        _fail(
            "origin_review_report_blocking",
            "A blocking data-quality review cannot be a calibration source.",
        )
    required_submitted_ids = {
        issue_id
        for issue_id, contract in issue_contracts.items()
        if len(contract["allowed_actions"]) > 1
    }
    if set(normalized_submitted) != required_submitted_ids:
        _fail(
            "origin_review_decisions_invalid",
            "The submitted origin review decisions do not cover every actionable issue.",
        )
    for issue_id, action in normalized_submitted.items():
        if action not in issue_contracts[issue_id]["allowed_actions"]:
            _fail(
                "origin_review_decisions_invalid",
                "A submitted origin review action is not allowed by the frozen report.",
            )

    cleaning = _mapping(
        quality.get("cleaning"),
        "origin_review_incomplete",
        "The origin data-quality cleaning receipt is missing.",
    )
    cleaning_required = {
        "original_rows",
        "final_rows",
        "excluded_rows",
        "excluded_row_pct",
        "retained_issue_ids",
        "excluded_issue_ids",
        "decisions",
    }
    if not cleaning_required.issubset(cleaning):
        _fail(
            "origin_review_incomplete",
            "The origin data-quality cleaning receipt is incomplete.",
        )
    counts: dict[str, int] = {}
    for field in ("original_rows", "final_rows", "excluded_rows"):
        value = cleaning.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            _fail(
                "origin_review_cleaning_invalid",
                "The origin data-quality cleaning row counts are invalid.",
            )
        counts[field] = value
    if (
        counts["final_rows"] <= 0
        or counts["original_rows"] - counts["final_rows"]
        != counts["excluded_rows"]
        or counts["original_rows"] != source_row_count
    ):
        _fail(
            "origin_review_cleaning_invalid",
            "The origin data-quality cleaning row counts are inconsistent.",
        )
    excluded_pct = _finite_float(
        cleaning.get("excluded_row_pct"),
        "origin_review_cleaning_invalid",
        "The origin data-quality cleaning percentage is invalid.",
    )
    if excluded_pct < 0.0 or excluded_pct > 100.0:
        _fail(
            "origin_review_cleaning_invalid",
            "The origin data-quality cleaning percentage is invalid.",
        )
    expected_excluded_pct = round(
        counts["excluded_rows"] / counts["original_rows"] * 100.0, 3
    )
    if not math.isclose(excluded_pct, expected_excluded_pct, abs_tol=5e-4):
        _fail(
            "origin_review_cleaning_invalid",
            "The origin data-quality cleaning percentage is inconsistent.",
        )
    retained_ids = list(
        _sequence(
            cleaning.get("retained_issue_ids"),
            "origin_review_cleaning_invalid",
            "The origin data-quality cleaning retained issues are invalid.",
        )
    )
    excluded_ids = list(
        _sequence(
            cleaning.get("excluded_issue_ids"),
            "origin_review_cleaning_invalid",
            "The origin data-quality cleaning excluded issues are invalid.",
        )
    )
    cleaning_decisions = _sequence(
        cleaning.get("decisions"),
        "origin_review_cleaning_invalid",
        "The origin data-quality cleaning decision record is invalid.",
    )
    cleaning_actions: set[tuple[str, str]] = set()
    cleaning_issue_ids: set[str] = set()
    for item in cleaning_decisions:
        if not isinstance(item, Mapping) or not {
            "issue_id",
            "action",
            "affected_rows",
        }.issubset(item):
            _fail(
                "origin_review_incomplete",
                "The origin data-quality cleaning decision record is incomplete.",
            )
        issue_id = _nonempty_text(
            item.get("issue_id"),
            "origin_review_cleaning_invalid",
            "The origin data-quality cleaning issue ID is invalid.",
        )
        if issue_id in cleaning_issue_ids:
            _fail(
                "origin_review_cleaning_invalid",
                "The origin data-quality cleaning receipt contains a duplicate issue.",
            )
        cleaning_issue_ids.add(issue_id)
        action = item.get("action")
        if action not in {"retain", "exclude"}:
            _fail(
                "origin_review_cleaning_invalid",
                "The origin data-quality cleaning action is invalid.",
            )
        affected_rows = item.get("affected_rows")
        if (
            isinstance(affected_rows, bool)
            or not isinstance(affected_rows, int)
            or affected_rows < 0
        ):
            _fail(
                "origin_review_cleaning_invalid",
                "The origin data-quality cleaning affected-row count is invalid.",
            )
        contract = issue_contracts.get(issue_id)
        if contract is None:
            _fail(
                "origin_review_cleaning_invalid",
                "The origin data-quality cleaning receipt names an unknown issue.",
            )
        allowed_actions = contract["allowed_actions"]
        expected_action = (
            normalized_submitted[issue_id]
            if len(allowed_actions) > 1
            else allowed_actions[0]
            if len(allowed_actions) == 1
            else contract["recommended_action"]
        )
        if (
            action != expected_action
            or affected_rows != contract["expected_affected_rows"]
        ):
            _fail(
                "origin_review_cleaning_invalid",
                "The origin data-quality cleaning decision contradicts the frozen report.",
            )
        cleaning_actions.add((issue_id, str(action)))
    if cleaning_issue_ids != report_issue_ids:
        _fail(
            "origin_review_cleaning_invalid",
            "The origin data-quality cleaning receipt does not cover every report issue.",
        )
    expected_retained_ids = [
        issue_id for issue_id, action in cleaning_actions if action == "retain"
    ]
    expected_excluded_ids = [
        issue_id for issue_id, action in cleaning_actions if action == "exclude"
    ]
    if (
        sorted(retained_ids) != sorted(expected_retained_ids)
        or sorted(excluded_ids) != sorted(expected_excluded_ids)
    ):
        _fail(
            "origin_review_cleaning_invalid",
            "The origin data-quality cleaning issue lists are inconsistent.",
        )
    if any(item not in cleaning_actions for item in normalized_submitted.items()):
        _fail(
            "origin_review_decisions_invalid",
            "A submitted origin review decision is absent from the cleaning receipt.",
        )

    # This also rejects NaN/infinity or non-JSON evidence before it enters an
    # immutable source snapshot.
    canonical_json_sha256(quality)
    return deepcopy(dict(quality))


def _verified_source_identity(
    job: Mapping[str, Any],
    *,
    label: str,
) -> dict[str, Any]:
    source_path = _nonempty_text(
        job.get("source_path"),
        f"{label}_source_missing",
        f"The {label} source path is missing.",
    )
    source_sha256 = _sha256(
        job.get("source_hash"),
        f"{label}_source_hash_invalid",
        f"The {label} source SHA-256 is missing or invalid.",
    )
    try:
        verified = reporting.verify_source_sha256(source_path, source_sha256)
        resolved = Path(source_path).resolve(strict=True)
        byte_count = resolved.stat().st_size
    except (OSError, RuntimeError, TypeError, ValueError, SourceFingerprintMismatch) as exc:
        raise AnnualSourceValidationError(
            f"{label}_source_unverifiable",
            f"The {label} source bytes are missing or no longer match their SHA-256.",
        ) from exc
    _require_digest_match(
        _sha256(
            verified,
            f"{label}_source_hash_invalid",
            f"The verified {label} source SHA-256 is invalid.",
        ),
        source_sha256,
        f"{label}_source_hash_mismatch",
        f"The verified {label} source SHA-256 does not match the durable record.",
    )
    return {
        "path": str(resolved),
        "sha256": source_sha256,
        "byte_count": int(byte_count),
        "media_type": "text/csv",
        "retention_status": "verified_durable_job_source_path",
    }


def _annual_source_artifact_path(source_sha256: str) -> tuple[Path, str]:
    root = config.ANNUAL_SOURCE_ARTIFACT_DIR.resolve()
    storage_key = f"sha256/{source_sha256[:2]}/{source_sha256}.csv"
    destination = (root / Path(storage_key)).resolve()
    if root not in destination.parents:
        _fail(
            "annual_source_artifact_path_invalid",
            "The Annual source artifact path escapes private storage.",
        )
    return destination, storage_key


def harden_annual_source_artifact(
    source_path: str | Path,
    expected_sha256: str,
    *,
    annual_job_id: str,
) -> dict[str, Any]:
    """Create or verify the private immutable content-addressed MIDC artifact."""

    source_hash = _sha256(
        expected_sha256,
        "annual_source_artifact_hash_invalid",
        "The Annual source artifact SHA-256 is invalid.",
    )
    owner_job_id = _nonempty_text(
        annual_job_id,
        "annual_job_id_missing",
        "The Annual source artifact must name its owning Annual job.",
    )
    try:
        reporting.verify_source_sha256(source_path, source_hash)
        source = Path(source_path).resolve(strict=True)
        source_bytes = int(source.stat().st_size)
    except (OSError, RuntimeError, TypeError, ValueError, SourceFingerprintMismatch) as exc:
        raise AnnualSourceValidationError(
            "annual_source_unverifiable",
            "The Annual MIDC source bytes cannot be hardened because their SHA-256 changed.",
        ) from exc
    if source_bytes <= 0:
        _fail(
            "annual_source_artifact_empty",
            "The Annual MIDC source artifact must not be empty.",
        )

    destination, storage_key = _annual_source_artifact_path(source_hash)
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        # ``resolve()`` can retain a non-existent final directory spelling on
        # Windows; refresh after creation before opening the atomic temp file.
        destination = destination.parent.resolve(strict=True) / destination.name
        if destination.exists():
            if destination.is_symlink() or not destination.is_file():
                _fail(
                    "annual_source_artifact_invalid",
                    "The content-addressed Annual source destination is not a regular file.",
                )
            reporting.verify_source_sha256(destination, source_hash)
        else:
            temporary = destination.with_name(
                f".{destination.name}.{uuid.uuid4().hex}.tmp"
            )
            try:
                with source.open("rb") as source_handle, temporary.open("xb") as target_handle:
                    shutil.copyfileobj(source_handle, target_handle)
                    target_handle.flush()
                    os.fsync(target_handle.fileno())
                reporting.verify_source_sha256(temporary, source_hash)
                if int(temporary.stat().st_size) != source_bytes:
                    _fail(
                        "annual_source_artifact_size_mismatch",
                        "The hardened Annual source byte count changed during copying.",
                    )
                os.replace(temporary, destination)
            finally:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass
        artifact_bytes = int(destination.stat().st_size)
        if artifact_bytes != source_bytes:
            _fail(
                "annual_source_artifact_size_mismatch",
                "The content-addressed Annual source has the wrong byte count.",
            )
        reporting.verify_source_sha256(destination, source_hash)
        if os.name != "nt":
            try:
                destination.chmod(0o444)
            except OSError:
                # The content hash remains authoritative on filesystems that
                # cannot persist POSIX-style read-only mode bits.
                pass
    except AnnualSourceValidationError:
        raise
    except (OSError, RuntimeError, TypeError, ValueError, SourceFingerprintMismatch) as exc:
        raise AnnualSourceValidationError(
            "annual_source_artifact_unavailable",
            "The private content-addressed Annual source artifact could not be created or verified.",
        ) from exc

    return {
        "schema_version": ANNUAL_SOURCE_ARTIFACT_SCHEMA_VERSION,
        "owner_workflow": "annual_simulation",
        "owner_annual_job_id": owner_job_id,
        "content_address_algorithm": "sha256",
        "storage_key": storage_key,
        "sha256": source_hash,
        "byte_count": artifact_bytes,
        "media_type": "text/csv",
        "immutable": True,
    }


def verify_annual_source_artifact(
    raw_identity: Mapping[str, Any],
    *,
    annual_job_id: str,
    expected_sha256: str,
    expected_bytes: int,
) -> dict[str, Any]:
    """Verify a recorded private artifact identity and its current bytes."""

    identity = _mapping(
        raw_identity,
        "annual_source_artifact_missing",
        "The Annual source artifact identity is missing.",
    )
    required_fields = {
        "schema_version",
        "owner_workflow",
        "owner_annual_job_id",
        "content_address_algorithm",
        "storage_key",
        "sha256",
        "byte_count",
        "media_type",
        "immutable",
    }
    if set(identity) != required_fields:
        _fail(
            "annual_source_artifact_shape_invalid",
            "The Annual source artifact identity does not match schema version 1.",
        )
    if (
        identity.get("schema_version") != ANNUAL_SOURCE_ARTIFACT_SCHEMA_VERSION
        or identity.get("owner_workflow") != "annual_simulation"
        or identity.get("owner_annual_job_id") != annual_job_id
        or identity.get("content_address_algorithm") != "sha256"
        or identity.get("media_type") != "text/csv"
        or identity.get("immutable") is not True
    ):
        _fail(
            "annual_source_artifact_identity_invalid",
            "The Annual source artifact identity is invalid.",
        )
    artifact_hash = _sha256(
        identity.get("sha256"),
        "annual_source_artifact_hash_invalid",
        "The Annual source artifact SHA-256 is invalid.",
    )
    _require_digest_match(
        artifact_hash,
        expected_sha256,
        "annual_source_artifact_hash_mismatch",
        "The Annual source artifact SHA-256 differs from the Annual job source.",
    )
    byte_count = _positive_int(
        identity.get("byte_count"),
        "annual_source_artifact_size_invalid",
        "The Annual source artifact byte count is invalid.",
    )
    if byte_count != expected_bytes:
        _fail(
            "annual_source_artifact_size_mismatch",
            "The Annual source artifact byte count differs from the verified source.",
        )
    destination, storage_key = _annual_source_artifact_path(artifact_hash)
    if identity.get("storage_key") != storage_key:
        _fail(
            "annual_source_artifact_storage_key_mismatch",
            "The Annual source artifact storage key is not its canonical content address.",
        )
    try:
        if destination.is_symlink() or not destination.is_file():
            _fail(
                "annual_source_artifact_unavailable",
                "The private Annual source artifact is missing.",
            )
        if int(destination.stat().st_size) != byte_count:
            _fail(
                "annual_source_artifact_size_mismatch",
                "The private Annual source artifact byte count changed.",
            )
        reporting.verify_source_sha256(destination, artifact_hash)
    except AnnualSourceValidationError:
        raise
    except (OSError, RuntimeError, TypeError, ValueError, SourceFingerprintMismatch) as exc:
        raise AnnualSourceValidationError(
            "annual_source_artifact_unverifiable",
            "The private Annual source artifact no longer matches its SHA-256.",
        ) from exc
    return deepcopy(dict(identity))


def validate_capacity_manifest(
    raw_manifest: Mapping[str, Any],
    *,
    expected_physics_version: str,
    expected_physics_fingerprint: str,
) -> dict[str, Any]:
    """Return a canonical, internally hashed per-system Wdc manifest."""

    manifest = _mapping(
        raw_manifest,
        "capacity_manifest_missing",
        "The Annual Simulation capacity manifest is missing.",
    )
    required_root_fields = {
        "schema_version",
        "rating_basis",
        "systems",
        "capacity_manifest_sha256",
    }
    if set(manifest) != required_root_fields:
        _fail(
            "capacity_manifest_shape_invalid",
            "The capacity manifest fields do not match schema version 1.",
        )
    if manifest.get("schema_version") != model.CAPACITY_MANIFEST_SCHEMA_VERSION:
        _fail(
            "capacity_manifest_version_invalid",
            "The capacity manifest schema version is not supported.",
        )
    if manifest.get("rating_basis") != model.CAPACITY_RATING_BASIS:
        _fail(
            "capacity_rating_basis_invalid",
            "Capacity must use module DC nameplate watts at STC.",
        )

    supplied_manifest_hash = _sha256(
        manifest.get("capacity_manifest_sha256"),
        "capacity_manifest_hash_invalid",
        "The capacity manifest SHA-256 is missing or invalid.",
    )
    unhashed = {
        key: deepcopy(value)
        for key, value in manifest.items()
        if key != "capacity_manifest_sha256"
    }
    expected_manifest_hash = canonical_json_sha256(unhashed)
    _require_digest_match(
        supplied_manifest_hash,
        expected_manifest_hash,
        "capacity_manifest_hash_mismatch",
        "The capacity manifest does not match its canonical SHA-256.",
    )

    expected_version = _nonempty_text(
        expected_physics_version,
        "capacity_physics_identity_invalid",
        "The expected calibration-physics version is missing.",
    )
    expected_fingerprint = _sha256(
        expected_physics_fingerprint,
        "capacity_physics_identity_invalid",
        "The expected calibration-physics fingerprint is missing or invalid.",
    )
    systems = _mapping(
        manifest.get("systems"),
        "capacity_systems_invalid",
        "The capacity manifest systems must be an object.",
    )
    if set(systems) != {"solectria", "solaredge"}:
        _fail(
            "capacity_systems_invalid",
            "Exactly one Solectria and one SolarEdge capacity record are required.",
        )

    required_system_fields = {
        "system",
        "rating_basis",
        "module_model",
        "module_stc_wdc",
        "strings",
        "bays_per_string",
        "modules_per_bay",
        "module_count",
        "installed_wdc",
        "calibration_physics_version",
        "calibration_physics_fingerprint",
    }
    canonical_systems: dict[str, dict[str, Any]] = {}
    for system_name in ("solectria", "solaredge"):
        record = _mapping(
            systems.get(system_name),
            "capacity_record_invalid",
            f"The {system_name} capacity record is missing.",
        )
        if set(record) != required_system_fields:
            _fail(
                "capacity_record_shape_invalid",
                f"The {system_name} capacity fields do not match schema version 1.",
            )
        if record.get("system") != system_name:
            _fail(
                "capacity_system_mismatch",
                f"The {system_name} capacity record names a different system.",
            )
        if record.get("rating_basis") != model.CAPACITY_RATING_BASIS:
            _fail(
                "capacity_rating_basis_invalid",
                f"The {system_name} capacity record does not use DC-STC nameplate watts.",
            )
        module_model = _nonempty_text(
            record.get("module_model"),
            "capacity_module_model_invalid",
            f"The {system_name} module model is missing.",
        )
        module_stc_wdc = _finite_float(
            record.get("module_stc_wdc"),
            "capacity_value_invalid",
            f"The {system_name} module STC rating must be finite and positive.",
        )
        installed_wdc = _finite_float(
            record.get("installed_wdc"),
            "capacity_value_invalid",
            f"The {system_name} installed Wdc must be finite and positive.",
        )
        if module_stc_wdc <= 0 or installed_wdc <= 0:
            _fail(
                "capacity_value_invalid",
                f"The {system_name} capacity values must be positive.",
            )
        strings = _positive_int(
            record.get("strings"),
            "capacity_topology_invalid",
            f"The {system_name} string count must be a positive integer.",
        )
        bays_per_string = _positive_int(
            record.get("bays_per_string"),
            "capacity_topology_invalid",
            f"The {system_name} bays per string must be a positive integer.",
        )
        modules_per_bay = _positive_int(
            record.get("modules_per_bay"),
            "capacity_topology_invalid",
            f"The {system_name} modules per bay must be a positive integer.",
        )
        module_count = _positive_int(
            record.get("module_count"),
            "capacity_topology_invalid",
            f"The {system_name} module count must be a positive integer.",
        )
        if strings * bays_per_string * modules_per_bay != module_count:
            _fail(
                "capacity_topology_mismatch",
                f"The {system_name} topology product does not equal module_count.",
            )
        try:
            derived_wdc = Decimal(module_count) * Decimal(str(module_stc_wdc))
            recorded_wdc = Decimal(str(installed_wdc))
        except InvalidOperation as exc:
            raise AnnualSourceValidationError(
                "capacity_value_invalid",
                f"The {system_name} capacity values are not canonical decimals.",
            ) from exc
        if derived_wdc != recorded_wdc:
            _fail(
                "capacity_wdc_mismatch",
                f"The {system_name} module_count times module STC watts does not equal installed_wdc.",
            )
        physics_version = _nonempty_text(
            record.get("calibration_physics_version"),
            "capacity_physics_identity_invalid",
            f"The {system_name} calibration-physics version is missing.",
        )
        physics_fingerprint = _sha256(
            record.get("calibration_physics_fingerprint"),
            "capacity_physics_identity_invalid",
            f"The {system_name} calibration-physics fingerprint is invalid.",
        )
        if physics_version != expected_version:
            _fail(
                "capacity_physics_version_mismatch",
                f"The {system_name} capacity version does not match the Annual result.",
            )
        _require_digest_match(
            physics_fingerprint,
            expected_fingerprint,
            "capacity_physics_fingerprint_mismatch",
            f"The {system_name} capacity fingerprint does not match the Annual result.",
        )
        canonical_systems[system_name] = {
            "system": system_name,
            "rating_basis": model.CAPACITY_RATING_BASIS,
            "module_model": module_model,
            "module_stc_wdc": module_stc_wdc,
            "strings": strings,
            "bays_per_string": bays_per_string,
            "modules_per_bay": modules_per_bay,
            "module_count": module_count,
            "installed_wdc": installed_wdc,
            "calibration_physics_version": physics_version,
            "calibration_physics_fingerprint": physics_fingerprint,
        }

    canonical = {
        "schema_version": model.CAPACITY_MANIFEST_SCHEMA_VERSION,
        "rating_basis": model.CAPACITY_RATING_BASIS,
        "systems": canonical_systems,
    }
    canonical["capacity_manifest_sha256"] = canonical_json_sha256(canonical)
    _require_digest_match(
        canonical["capacity_manifest_sha256"],
        supplied_manifest_hash,
        "capacity_manifest_not_canonical",
        "The capacity manifest is valid but not in canonical form.",
    )
    return canonical


def _validated_calibration_lineage(
    annual_job: Mapping[str, Any],
    origin_validation_job: Mapping[str, Any] | None,
    promotion_record: Mapping[str, Any] | None,
) -> dict[str, Any]:
    result = _mapping(
        annual_job.get("result"),
        "annual_result_missing",
        "The completed Annual Simulation result is missing.",
    )
    stats = _mapping(
        result.get("stats"),
        "annual_stats_missing",
        "The completed Annual Simulation statistics are missing.",
    )
    if stats.get("calibration_enabled") is not True:
        _fail(
            "annual_not_calibrated",
            "The Annual Simulation is physics-only; a calibrated source is required.",
        )
    if stats.get("calibration_kind") != "frozen_profile":
        _fail(
            "annual_calibration_kind_invalid",
            "The Annual Simulation did not apply a frozen reviewed calibration profile.",
        )
    result_application = _mapping(
        result.get("calibration_application"),
        "calibration_application_missing",
        "The Annual result calibration-application evidence is missing.",
    )
    if result_application.get("applied") is not True:
        _fail(
            "calibration_not_applied",
            "The Annual result does not confirm that calibration was applied.",
        )
    stats_application = _mapping(
        stats.get("calibration_application"),
        "calibration_application_missing",
        "The Annual statistics calibration-application evidence is missing.",
    )
    provenance = _mapping(
        annual_job.get("provenance"),
        "annual_provenance_missing",
        "The Annual Simulation durable provenance is missing.",
    )
    profile_raw = _mapping(
        provenance.get("calibration_profile"),
        "calibration_profile_missing",
        "The Annual Simulation calibration profile is missing.",
    )
    application = _mapping(
        provenance.get("calibration_application"),
        "calibration_application_missing",
        "The Annual Simulation durable calibration application is missing.",
    )
    origin_profile_raw = _mapping(
        application.get("origin_profile"),
        "origin_calibration_profile_missing",
        "The origin calibration profile is missing.",
    )
    resolved_profile_raw = _mapping(
        application.get("resolved_profile"),
        "resolved_calibration_profile_missing",
        "The resolved calibration profile is missing.",
    )
    required_seasons_raw = _sequence(
        application.get("required_seasons"),
        "required_seasons_missing",
        "The Annual calibration required-season record is missing.",
    )
    required_seasons = [str(value).strip().lower() for value in required_seasons_raw]
    if not required_seasons or any(not value for value in required_seasons):
        _fail(
            "required_seasons_invalid",
            "The Annual calibration required-season record is invalid.",
        )
    try:
        origin_profile = calibration.validate_seasonal_calibration_profile(
            origin_profile_raw
        )
        resolved_profile = calibration.validate_seasonal_calibration_profile(
            resolved_profile_raw,
            required_seasons=required_seasons,
        )
        durable_profile = calibration.validate_seasonal_calibration_profile(
            profile_raw,
            required_seasons=required_seasons,
        )
        model.validate_calibration_profile_physics(origin_profile)
        model.validate_calibration_profile_physics(resolved_profile)
        model.validate_calibration_profile_physics(durable_profile)
    except (TypeError, ValueError) as exc:
        raise AnnualSourceValidationError(
            "calibration_profile_invalid",
            "The Annual Simulation calibration profile is invalid or uses incompatible physics.",
        ) from exc
    if not _canonical_equal(resolved_profile, durable_profile):
        _fail(
            "resolved_calibration_profile_mismatch",
            "The durable and resolved Annual calibration profiles differ.",
        )
    origin_profile_hash = canonical_json_sha256(origin_profile)
    resolved_profile_hash = canonical_json_sha256(resolved_profile)
    _require_digest_match(
        _sha256(
            application.get("origin_profile_sha256"),
            "origin_profile_hash_invalid",
            "The origin calibration-profile SHA-256 is missing or invalid.",
        ),
        origin_profile_hash,
        "origin_profile_hash_mismatch",
        "The origin calibration profile does not match its SHA-256.",
    )
    _require_digest_match(
        _sha256(
            application.get("resolved_profile_sha256"),
            "resolved_profile_hash_invalid",
            "The resolved calibration-profile SHA-256 is missing or invalid.",
        ),
        resolved_profile_hash,
        "resolved_profile_hash_mismatch",
        "The resolved calibration profile does not match its SHA-256.",
    )

    # ``run_annual`` stores the original application context (without the two
    # full profiles) in stats, then adds the explicit applied receipt to the
    # top-level result.  Reconstruct both copies exactly so substitution consent,
    # settings deltas, timestamps, and other lineage cannot disagree silently.
    expected_stats_application = {
        key: deepcopy(value)
        for key, value in application.items()
        if key not in {"origin_profile", "resolved_profile"}
    }
    expected_result_application = deepcopy(expected_stats_application)
    expected_result_application.update(
        {
            "applied": True,
            "method": "frozen_baseline_seasonal_factors",
            "seasonal_factors": deepcopy(resolved_profile["seasonal_factors"]),
        }
    )
    if not _canonical_equal(stats_application, expected_stats_application):
        _fail(
            "calibration_application_mismatch",
            "The Annual statistics calibration application differs from durable provenance.",
        )
    if not _canonical_equal(result_application, expected_result_application):
        _fail(
            "calibration_application_mismatch",
            "The Annual result calibration application differs from durable provenance.",
        )

    baseline_job_id = _nonempty_text(
        application.get("baseline_job_id"),
        "origin_job_id_missing",
        "The Annual calibration origin job ID is missing.",
    )
    review_id = _nonempty_text(
        application.get("baseline_review_id"),
        "origin_review_id_missing",
        "The Annual calibration review ID is missing.",
    )
    promoted_at = _nonempty_text(
        application.get("baseline_promoted_at"),
        "origin_promotion_missing",
        "The Annual calibration promotion timestamp is missing.",
    )
    for exposed in (result_application, stats_application):
        if exposed.get("baseline_job_id") != baseline_job_id:
            _fail(
                "calibration_application_mismatch",
                "The Annual result and durable calibration origin job IDs differ.",
            )
        if exposed.get("baseline_review_id") != review_id:
            _fail(
                "calibration_application_mismatch",
                "The Annual result and durable calibration review IDs differ.",
            )
        for field, expected in (
            ("origin_profile_sha256", origin_profile_hash),
            ("resolved_profile_sha256", resolved_profile_hash),
        ):
            exposed_hash = _sha256(
                exposed.get(field),
                "calibration_application_mismatch",
                f"The Annual result {field} is missing or invalid.",
            )
            _require_digest_match(
                exposed_hash,
                expected,
                "calibration_application_mismatch",
                f"The Annual result {field} does not match durable provenance.",
            )

    origin_job = _mapping(
        origin_validation_job,
        "origin_validation_job_missing",
        "The reviewed origin validation job can no longer be resolved.",
    )
    if origin_job.get("id") != baseline_job_id:
        _fail(
            "origin_validation_job_mismatch",
            "The resolved origin validation job ID does not match calibration provenance.",
        )
    if origin_job.get("state") != "done" or origin_job.get("mode") != "validation":
        _fail(
            "origin_validation_job_invalid",
            "The calibration origin must be a completed validation job.",
        )
    if origin_profile.get("origin_job_id") != baseline_job_id:
        _fail(
            "origin_profile_job_mismatch",
            "The origin calibration profile names a different validation job.",
        )
    if origin_profile.get("origin_review_id") != review_id:
        _fail(
            "origin_profile_review_mismatch",
            "The origin calibration profile names a different review.",
        )
    origin_source = _verified_source_identity(origin_job, label="origin_validation")
    origin_profile_source_hash = _sha256(
        origin_profile.get("origin_source_sha256"),
        "origin_profile_source_hash_invalid",
        "The origin profile source SHA-256 is invalid.",
    )
    _require_digest_match(
        origin_profile_source_hash,
        origin_source["sha256"],
        "origin_profile_source_mismatch",
        "The origin profile and validation job source SHA-256 values differ.",
    )
    origin_provenance = _mapping(
        origin_job.get("provenance"),
        "origin_validation_provenance_missing",
        "The origin validation provenance is missing.",
    )
    quality = _mapping(
        origin_provenance.get("data_quality"),
        "origin_review_missing",
        "The reviewed origin data-quality decisions are missing.",
    )
    validated_quality = _validated_review_quality(
        quality,
        review_id=review_id,
        reviewed_source_sha256=origin_source["sha256"],
        origin_request=_mapping(
            origin_job.get("request"),
            "origin_request_invalid",
            "The origin validation request is missing.",
        ),
    )
    embedded_origin_profile = origin_provenance.get("calibration_profile")
    if embedded_origin_profile is not None and not _canonical_equal(
        embedded_origin_profile, origin_profile
    ):
        _fail(
            "origin_embedded_profile_mismatch",
            "The origin validation's embedded profile differs from Annual provenance.",
        )
    origin_result = _mapping(
        origin_job.get("result"),
        "origin_validation_result_missing",
        "The completed origin validation result is missing.",
    )
    fit_metadata = origin_result.get("calibration_factors") or _mapping(
        origin_result.get("stats"),
        "origin_validation_stats_missing",
        "The origin validation statistics are missing.",
    ).get("calibration_factors")
    if fit_metadata is None or not _canonical_equal(
        fit_metadata, origin_profile.get("fit_metadata")
    ):
        _fail(
            "origin_fit_metadata_mismatch",
            "The origin validation fit metadata does not match the frozen profile.",
        )
    diagnostics = origin_result.get("factor_driver_diagnostics") or _mapping(
        origin_result.get("stats"),
        "origin_validation_stats_missing",
        "The origin validation statistics are missing.",
    ).get("factor_driver_diagnostics")
    if diagnostics is None or not _canonical_equal(
        diagnostics, origin_profile.get("factor_driver_diagnostics")
    ):
        _fail(
            "origin_fit_diagnostics_mismatch",
            "The origin validation diagnostics do not match the frozen profile.",
        )

    promotion = _mapping(
        promotion_record,
        "origin_promotion_missing",
        "The historical calibration promotion receipt can no longer be resolved.",
    )
    if promotion.get("mode") != "validation" or promotion.get("job_id") != baseline_job_id:
        _fail(
            "origin_promotion_mismatch",
            "The historical promotion receipt does not name the origin validation job.",
        )
    if promotion.get("promoted_at") != promoted_at:
        _fail(
            "origin_promotion_mismatch",
            "The historical promotion timestamp does not match Annual provenance.",
        )

    return {
        "origin_profile": origin_profile,
        "resolved_profile": resolved_profile,
        "origin_profile_sha256": origin_profile_hash,
        "resolved_profile_sha256": resolved_profile_hash,
        "application": deepcopy(dict(application)),
        "result_application": deepcopy(dict(result_application)),
        "origin_validation_source": origin_source,
        "origin_validation_job": _snapshot_job_record(origin_job),
        "data_quality": validated_quality,
        "promotion": deepcopy(dict(promotion)),
    }


def _request_interval_seconds(request: Mapping[str, Any]) -> int:
    value = _positive_int(
        request.get("interval_value"),
        "annual_interval_invalid",
        "The Annual request interval value must be a positive integer.",
    )
    unit = request.get("interval_unit")
    factors = {"minutes": 60, "hours": 3_600, "days": 86_400}
    if unit not in factors:
        _fail(
            "annual_interval_invalid",
            "The Annual request interval unit is invalid.",
        )
    interval_seconds = value * factors[str(unit)]
    if (
        interval_seconds < 60
        or interval_seconds > model.ANNUAL_MAX_PHYSICS_INTERVAL_SECONDS
        or interval_seconds % 60
        or 86_400 % interval_seconds
    ):
        _fail(
            "annual_interval_invalid",
            "The Annual request interval is incompatible with current temporal semantics.",
        )
    return interval_seconds


def _validate_period_identity(row: Mapping[str, Any], interval_seconds: int) -> int:
    year = row.get("year")
    if isinstance(year, bool) or not isinstance(year, int) or not 1 <= year <= 9999:
        _fail("annual_row_year_invalid", "An Annual energy row has an invalid year.")
    try:
        period_start = date.fromisoformat(str(row.get("period_start")))
        period_end = date.fromisoformat(str(row.get("period_end")))
    except (TypeError, ValueError) as exc:
        raise AnnualSourceValidationError(
            "annual_row_period_invalid",
            f"Annual energy row {year} has invalid period dates.",
        ) from exc
    if period_end < period_start or period_start.year != year or period_end.year != year:
        _fail(
            "annual_row_period_invalid",
            f"Annual energy row {year} has inconsistent period dates.",
        )
    if row.get("complete_calendar_year") is True and (
        period_start != date(year, 1, 1) or period_end != date(year, 12, 31)
    ):
        _fail(
            "annual_row_period_invalid",
            f"Annual energy row {year} claims completeness without calendar-year bounds.",
        )
    expected = ((period_end - period_start).days + 1) * (86_400 // interval_seconds)
    recorded_expected = _positive_int(
        row.get("source_expected_interval_count"),
        "annual_row_coverage_invalid",
        f"Annual energy row {year} is missing its expected interval count.",
    )
    if recorded_expected != expected:
        _fail(
            "annual_row_coverage_mismatch",
            f"Annual energy row {year} has an inconsistent expected interval count.",
        )
    covered = row.get("source_covered_interval_count")
    if isinstance(covered, bool) or not isinstance(covered, int) or not 0 <= covered <= expected:
        _fail(
            "annual_row_coverage_invalid",
            f"Annual energy row {year} has an invalid covered interval count.",
        )
    row_count = row.get("row_count")
    if (
        isinstance(row_count, bool)
        or not isinstance(row_count, int)
        or not 0 <= row_count <= expected
    ):
        _fail(
            "annual_row_count_invalid",
            f"Annual energy row {year} has an invalid model row count.",
        )
    # The model intentionally omits wholly unavailable MIDC intervals instead
    # of fabricating zero generation.  Complete rows therefore have the full
    # expected count, while excluded rows may have fewer rows; in both cases the
    # model-row population must equal the source intervals actually covered.
    if row_count != covered:
        _fail(
            "annual_row_count_mismatch",
            f"Annual energy row {year} model row count does not match its covered source intervals.",
        )
    if row.get("source_complete") is True:
        if covered != expected:
            _fail(
                "annual_row_coverage_mismatch",
                f"Annual energy row {year} claims complete source coverage with missing intervals.",
            )
        coverage_pct = _finite_float(
            row.get("source_coverage_pct"),
            "annual_row_coverage_invalid",
            f"Annual energy row {year} has an invalid source coverage percentage.",
        )
        if coverage_pct != 100.0:
            _fail(
                "annual_row_coverage_mismatch",
                f"Annual energy row {year} claims completeness below 100 percent coverage.",
            )
    return year


def _row_eligibility(
    row: Mapping[str, Any],
) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if row.get("complete_calendar_year") is not True:
        reasons.append("not_complete_calendar_year")
    if row.get("source_complete") is not True:
        reasons.append("source_incomplete")
    if row.get("cdf_eligible") is not True:
        reasons.append("cdf_ineligible")
    for field, reason in (
        ("sol_predicted_kwh", "nonpositive_solectria_energy"),
        ("se_predicted_kwh", "nonpositive_solaredge_energy"),
    ):
        try:
            value = _finite_float(
                row.get(field),
                "annual_row_energy_invalid",
                f"Annual energy field {field} must be finite.",
            )
        except AnnualSourceValidationError:
            reasons.append(reason)
        else:
            if value <= 0:
                reasons.append(reason)
    return not reasons, reasons


def _validate_paired_rows(
    result: Mapping[str, Any],
    stats: Mapping[str, Any],
    source_quality: Mapping[str, Any],
    window: Mapping[str, Any],
    interval_seconds: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    top_rows = _sequence(
        result.get("annual_energy_by_year"),
        "annual_rows_missing",
        "The Annual result paired energy rows are missing.",
    )
    stats_rows = _sequence(
        stats.get("annual_energy_by_year"),
        "annual_rows_missing",
        "The Annual statistics paired energy rows are missing.",
    )
    if not _canonical_equal(top_rows, stats_rows):
        _fail(
            "annual_rows_mismatch",
            "The top-level and statistics copies of paired Annual energy rows differ.",
        )
    quality_periods = _sequence(
        source_quality.get("periods"),
        "annual_source_periods_missing",
        "The Annual source audit has no per-period coverage records.",
    )
    window_periods = _sequence(
        window.get("periods"),
        "annual_window_periods_missing",
        "The Annual result window has no per-period records.",
    )
    quality_by_year: dict[int, Mapping[str, Any]] = {}
    window_by_year: dict[int, Mapping[str, Any]] = {}
    for destination, raw_periods, code in (
        (quality_by_year, quality_periods, "annual_source_period_invalid"),
        (window_by_year, window_periods, "annual_window_period_invalid"),
    ):
        for raw_period in raw_periods:
            period = _mapping(raw_period, code, "An Annual period record is invalid.")
            year = period.get("year")
            if isinstance(year, bool) or not isinstance(year, int) or year in destination:
                _fail(code, "Annual period years must be unique integers.")
            destination[year] = period

    eligible: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    seen_years: set[int] = set()
    period_fields = (
        "year",
        "period_start",
        "period_end",
        "coverage_status",
        "complete_calendar_year",
        "source_expected_interval_count",
        "source_covered_interval_count",
        "source_coverage_pct",
        "annual_expected_interval_count",
        "annual_coverage_pct",
        "source_complete",
        "cdf_eligible",
    )
    for raw_row in top_rows:
        row = _mapping(
            raw_row,
            "annual_row_invalid",
            "An Annual paired energy row is not an object.",
        )
        year = _validate_period_identity(row, interval_seconds)
        if year in seen_years:
            _fail("annual_row_duplicate_year", f"Annual energy year {year} is duplicated.")
        seen_years.add(year)
        for period_map, code, label in (
            (quality_by_year, "annual_source_period_mismatch", "source audit"),
            (window_by_year, "annual_window_period_mismatch", "result window"),
        ):
            period = period_map.get(year)
            if period is None:
                _fail(code, f"Annual energy year {year} is missing from the {label}.")
            for field in period_fields:
                if field not in row or field not in period or not _canonical_equal(
                    row[field], period[field]
                ):
                    _fail(
                        code,
                        f"Annual energy year {year} field {field} differs from the {label}.",
                    )
        sol_energy = _finite_float(
            row.get("sol_predicted_kwh"),
            "annual_row_energy_invalid",
            f"Annual energy year {year} has invalid Solectria energy.",
        )
        se_energy = _finite_float(
            row.get("se_predicted_kwh"),
            "annual_row_energy_invalid",
            f"Annual energy year {year} has invalid SolarEdge energy.",
        )
        combined = _finite_float(
            row.get("combined_predicted_kwh"),
            "annual_row_energy_invalid",
            f"Annual energy year {year} has invalid combined energy.",
        )
        if round(sol_energy + se_energy, 1) != combined:
            _fail(
                "annual_row_combined_energy_mismatch",
                f"Annual energy year {year} combined energy does not equal the paired sum.",
            )
        is_eligible, reasons = _row_eligibility(row)
        frozen_row = deepcopy(dict(row))
        if is_eligible:
            eligible.append(frozen_row)
        else:
            excluded.append({"row": frozen_row, "reasons": reasons})
    if set(quality_by_year) != seen_years or set(window_by_year) != seen_years:
        _fail(
            "annual_period_population_mismatch",
            "Annual source/window periods do not match the paired energy-row population.",
        )
    if not eligible:
        _fail(
            "no_eligible_annual_years",
            "The Annual Simulation has no complete, positive-energy paired weather year.",
        )
    return eligible, excluded


def _snapshot_job_record(job: Mapping[str, Any]) -> dict[str, Any]:
    request = deepcopy(job.get("request"))
    result = deepcopy(job.get("result"))
    provenance = deepcopy(job.get("provenance"))
    artifacts = deepcopy(job.get("artifacts"))
    return {
        "id": deepcopy(job.get("id")),
        "kind": deepcopy(job.get("kind")),
        "mode": deepcopy(job.get("mode")),
        "state": deepcopy(job.get("state")),
        "request": request,
        "result": result,
        "provenance": provenance,
        "artifacts": artifacts,
        "source_path": deepcopy(job.get("source_path")),
        "source_hash": deepcopy(job.get("source_hash")),
        "timestamps": {
            field: deepcopy(job.get(field))
            for field in (
                "created_at",
                "queued_at",
                "started_at",
                "completed_at",
                "updated_at",
            )
        },
        "record_hashes": {
            "request_sha256": canonical_json_sha256(request),
            "result_sha256": canonical_json_sha256(result),
            "provenance_sha256": canonical_json_sha256(provenance),
            "artifacts_sha256": canonical_json_sha256(artifacts),
        },
    }


def _resolve_capacity_manifest(
    annual_job: Mapping[str, Any],
    *,
    stats: Mapping[str, Any],
    resolved_profile: Mapping[str, Any],
    allow_legacy_capacity: bool,
) -> tuple[dict[str, Any], str]:
    result = _mapping(
        annual_job.get("result"),
        "annual_result_missing",
        "The completed Annual Simulation result is missing.",
    )
    provenance = _mapping(
        annual_job.get("provenance"),
        "annual_provenance_missing",
        "The Annual Simulation durable provenance is missing.",
    )
    candidates = (
        result.get("capacity_manifest"),
        stats.get("capacity_manifest"),
        provenance.get("capacity_manifest"),
    )
    present = [candidate for candidate in candidates if candidate is not None]
    if present:
        if len(present) != len(candidates):
            _fail(
                "capacity_manifest_copies_incomplete",
                "The Annual Simulation contains only some required capacity-manifest copies.",
            )
        if not all(_canonical_equal(present[0], candidate) for candidate in present[1:]):
            _fail(
                "capacity_manifest_copies_mismatch",
                "The Annual result, statistics, and provenance capacity manifests differ.",
            )
        raw_manifest = _mapping(
            present[0],
            "capacity_manifest_missing",
            "The Annual Simulation capacity manifest is invalid.",
        )
        source = "explicit_annual_manifest"
    else:
        if not allow_legacy_capacity:
            _fail(
                "legacy_capacity_manifest_disallowed",
                "This Annual Simulation predates explicit Wdc provenance and must be rerun.",
            )
        annual_fingerprint = _sha256(
            stats.get("calibration_physics_fingerprint"),
            "annual_physics_fingerprint_invalid",
            "The Annual calibration-physics fingerprint is missing or invalid.",
        )
        _require_digest_match(
            annual_fingerprint,
            model.CALIBRATION_PHYSICS_FINGERPRINT,
            "legacy_capacity_fingerprint_mismatch",
            "Legacy Wdc reconstruction requires the exact current calibration-physics fingerprint.",
        )
        raw_manifest = model.capacity_manifest()
        source = "legacy_exact_current_physics_fingerprint_reconstruction"

    annual_version = _nonempty_text(
        stats.get("calibration_physics_version"),
        "annual_physics_version_invalid",
        "The Annual calibration-physics version is missing.",
    )
    annual_fingerprint = _sha256(
        stats.get("calibration_physics_fingerprint"),
        "annual_physics_fingerprint_invalid",
        "The Annual calibration-physics fingerprint is missing or invalid.",
    )
    if resolved_profile.get("calibration_physics_version") != annual_version:
        _fail(
            "annual_profile_physics_version_mismatch",
            "The Annual result and applied calibration profile physics versions differ.",
        )
    profile_fingerprint = _sha256(
        resolved_profile.get("calibration_physics_fingerprint"),
        "calibration_profile_physics_fingerprint_invalid",
        "The applied calibration profile physics fingerprint is invalid.",
    )
    _require_digest_match(
        profile_fingerprint,
        annual_fingerprint,
        "annual_profile_physics_fingerprint_mismatch",
        "The Annual result and applied calibration profile physics fingerprints differ.",
    )
    return (
        validate_capacity_manifest(
            raw_manifest,
            expected_physics_version=annual_version,
            expected_physics_fingerprint=annual_fingerprint,
        ),
        source,
    )


def _resolve_annual_source_artifact(
    annual_job: Mapping[str, Any],
    *,
    annual_source: Mapping[str, Any],
) -> tuple[dict[str, Any], str]:
    result = _mapping(
        annual_job.get("result"),
        "annual_result_missing",
        "The completed Annual Simulation result is missing.",
    )
    provenance = _mapping(
        annual_job.get("provenance"),
        "annual_provenance_missing",
        "The Annual Simulation durable provenance is missing.",
    )
    result_identity = result.get("annual_source_artifact")
    provenance_identity = provenance.get("annual_source_artifact")
    if result_identity is None and provenance_identity is None:
        hardened = harden_annual_source_artifact(
            annual_source["path"],
            annual_source["sha256"],
            annual_job_id=str(annual_job["id"]),
        )
        source = "legacy_materialized_from_verified_annual_source"
    else:
        if result_identity is None or provenance_identity is None:
            _fail(
                "annual_source_artifact_copies_incomplete",
                "The Annual result and provenance do not both contain the source artifact identity.",
            )
        if not _canonical_equal(result_identity, provenance_identity):
            _fail(
                "annual_source_artifact_copies_mismatch",
                "The Annual result and provenance source artifact identities differ.",
            )
        hardened = verify_annual_source_artifact(
            _mapping(
                result_identity,
                "annual_source_artifact_missing",
                "The Annual source artifact identity is invalid.",
            ),
            annual_job_id=str(annual_job["id"]),
            expected_sha256=str(annual_source["sha256"]),
            expected_bytes=int(annual_source["byte_count"]),
        )
        source = "explicit_annual_artifact"
    return hardened, source


def build_annual_source_snapshot(
    annual_job: Mapping[str, Any],
    *,
    origin_validation_job: Mapping[str, Any] | None,
    promotion_record: Mapping[str, Any] | None,
    allow_legacy_capacity: bool = True,
) -> dict[str, Any]:
    """Verify and freeze one completed calibrated Annual Simulation.

    The caller must resolve the named origin validation job and exact historical
    promotion receipt before calling.  A future persistence transaction can compare
    the returned record hashes after re-reading those same rows, closing the
    verification/insert race without putting store access in this pure helper.
    """

    annual = _mapping(
        annual_job,
        "annual_job_missing",
        "The selected Annual Simulation cannot be resolved.",
    )
    job_id = _nonempty_text(
        annual.get("id"),
        "annual_job_id_missing",
        "The selected Annual Simulation has no durable job ID.",
    )
    if annual.get("mode") != "annual" or annual.get("state") != "done":
        _fail(
            "annual_job_not_completed",
            "The selected source must be a completed Annual Simulation job.",
        )
    _nonempty_text(
        annual.get("kind"),
        "annual_job_kind_missing",
        "The selected Annual Simulation has no durable job kind.",
    )
    request = _mapping(
        annual.get("request"),
        "annual_request_missing",
        "The selected Annual Simulation request is missing.",
    )
    result = _mapping(
        annual.get("result"),
        "annual_result_missing",
        "The completed Annual Simulation result is missing.",
    )
    if result.get("mode") != "annual":
        _fail(
            "annual_result_mode_invalid",
            "The selected job's result is not an Annual Simulation result.",
        )
    stats = _mapping(
        result.get("stats"),
        "annual_stats_missing",
        "The completed Annual Simulation statistics are missing.",
    )
    if stats.get("mode") != "annual":
        _fail(
            "annual_stats_mode_invalid",
            "The selected job's statistics are not Annual Simulation statistics.",
        )
    if stats.get("annual_temporal_semantics_version") != model.ANNUAL_TEMPORAL_SEMANTICS_VERSION:
        _fail(
            "annual_temporal_semantics_obsolete",
            "The Annual Simulation uses an obsolete temporal-semantics version.",
        )
    temporal_fingerprint = _sha256(
        stats.get("annual_temporal_semantics_fingerprint"),
        "annual_temporal_semantics_invalid",
        "The Annual temporal-semantics fingerprint is missing or invalid.",
    )
    _require_digest_match(
        temporal_fingerprint,
        model.ANNUAL_TEMPORAL_SEMANTICS_FINGERPRINT,
        "annual_temporal_semantics_obsolete",
        "The Annual Simulation uses an obsolete temporal-semantics fingerprint.",
    )
    interval_seconds = _request_interval_seconds(request)
    window = _mapping(
        result.get("window"),
        "annual_window_missing",
        "The completed Annual Simulation window is missing.",
    )
    if window.get("interval_seconds") != interval_seconds:
        _fail(
            "annual_window_interval_mismatch",
            "The Annual result window interval differs from its immutable request.",
        )
    _verify_annual_curtailment_consistency(request, window, stats)

    annual_source = _verified_source_identity(annual, label="annual_midc")
    provenance = _mapping(
        annual.get("provenance"),
        "annual_provenance_missing",
        "The Annual Simulation durable provenance is missing.",
    )
    audit = _mapping(
        provenance.get("annual_source_audit"),
        "annual_source_audit_missing",
        "The Annual MIDC source audit is missing.",
    )
    if audit.get("schema_version") != 2:
        _fail(
            "annual_source_audit_version_invalid",
            "The Annual MIDC source audit schema is not supported.",
        )
    audited_hash = _sha256(
        audit.get("source_sha256"),
        "annual_source_audit_hash_invalid",
        "The Annual MIDC audit source SHA-256 is invalid.",
    )
    _require_digest_match(
        audited_hash,
        annual_source["sha256"],
        "annual_source_audit_hash_mismatch",
        "The Annual MIDC audit and job source SHA-256 values differ.",
    )
    if audit.get("interval_seconds") != interval_seconds:
        _fail(
            "annual_source_audit_interval_mismatch",
            "The Annual MIDC audit interval differs from the immutable request.",
        )
    _sequence(
        audit.get("warnings"),
        "annual_source_audit_warnings_invalid",
        "The Annual MIDC audit warnings must be a list.",
    )
    source_quality = _mapping(
        audit.get("source_quality"),
        "annual_source_quality_missing",
        "The Annual MIDC source-quality audit is missing.",
    )
    if not _canonical_equal(source_quality, result.get("source_quality")):
        _fail(
            "annual_source_quality_mismatch",
            "The Annual result and durable MIDC source-quality audits differ.",
        )
    if source_quality.get("interval_seconds") != interval_seconds:
        _fail(
            "annual_source_quality_interval_mismatch",
            "The Annual source-quality interval differs from the immutable request.",
        )
    source_artifact, source_artifact_origin = _resolve_annual_source_artifact(
        annual,
        annual_source=annual_source,
    )

    lineage = _validated_calibration_lineage(
        annual,
        origin_validation_job,
        promotion_record,
    )
    capacity, capacity_source = _resolve_capacity_manifest(
        annual,
        stats=stats,
        resolved_profile=lineage["resolved_profile"],
        allow_legacy_capacity=allow_legacy_capacity,
    )
    eligible_rows, excluded_rows = _validate_paired_rows(
        result,
        stats,
        source_quality,
        window,
        interval_seconds,
    )

    payload: dict[str, Any] = {
        "schema_version": ANNUAL_SOURCE_SNAPSHOT_SCHEMA_VERSION,
        "eligibility_version": ANNUAL_SOURCE_ELIGIBILITY_VERSION,
        "source_annual_job_id": job_id,
        "source_annual_job": _snapshot_job_record(annual),
        "midc_source": annual_source,
        "midc_source_artifact": source_artifact,
        "midc_source_artifact_origin": source_artifact_origin,
        "annual_source_audit": deepcopy(dict(audit)),
        "eligible_paired_energy_rows": eligible_rows,
        "excluded_annual_energy_rows": excluded_rows,
        "capacity_manifest": capacity,
        "capacity_manifest_source": capacity_source,
        "calibration_lineage": lineage,
        "model_contract": {
            "model_version": deepcopy(stats.get("model_version")),
            "calibration_physics_version": deepcopy(
                stats.get("calibration_physics_version")
            ),
            "calibration_physics_fingerprint": deepcopy(
                stats.get("calibration_physics_fingerprint")
            ),
            "annual_temporal_semantics_version": model.ANNUAL_TEMPORAL_SEMANTICS_VERSION,
            "annual_temporal_semantics_fingerprint": (
                model.ANNUAL_TEMPORAL_SEMANTICS_FINGERPRINT
            ),
        },
    }
    return {
        "source_snapshot": payload,
        # This is exactly the value AgentStore persists and hashes.  Keeping the
        # digest outside the payload avoids a recursive/self-referential hash.
        "source_snapshot_sha256": canonical_json_sha256(payload),
    }


def _decode_job_row(row: sqlite3.Row) -> dict[str, Any]:
    decoded = dict(row)
    decoded["id"] = decoded.pop("job_id")
    for field in ("request", "result", "comparison", "provenance", "artifacts"):
        raw = decoded.pop(f"{field}_json")
        try:
            decoded[field] = json.loads(raw) if raw is not None else None
        except (TypeError, json.JSONDecodeError) as exc:
            raise AnnualSourceValidationError(
                "atomic_source_record_invalid",
                f"The durable Annual dependency has invalid {field} JSON.",
            ) from exc
    decoded["cancel_requested"] = bool(decoded.get("cancel_requested"))
    return decoded


def _record_hashes_match(
    record: Mapping[str, Any],
    frozen: Mapping[str, Any],
) -> bool:
    hashes = frozen.get("record_hashes")
    if not isinstance(hashes, Mapping):
        return False
    for field in ("request", "result", "provenance", "artifacts"):
        expected = hashes.get(f"{field}_sha256")
        if not isinstance(expected, str):
            return False
        if not secrets.compare_digest(
            canonical_json_sha256(record.get(field)), expected
        ):
            return False
    return all(
        _canonical_equal(record.get(field), frozen.get(field))
        for field in ("id", "kind", "mode", "state", "source_path", "source_hash")
    )


def make_atomic_source_recheck(
    source_snapshot_envelope: Mapping[str, Any],
):
    """Build the non-mutating callback accepted by ``AgentStore`` TEA creation."""

    envelope = deepcopy(dict(source_snapshot_envelope))
    supplied_hash = _sha256(
        envelope.get("source_snapshot_sha256"),
        "source_snapshot_hash_invalid",
        "The source snapshot SHA-256 is missing or invalid.",
    )
    frozen = _mapping(
        envelope.get("source_snapshot"),
        "source_snapshot_invalid",
        "The source snapshot envelope has no payload.",
    )
    if set(envelope) != {"source_snapshot", "source_snapshot_sha256"}:
        _fail(
            "source_snapshot_envelope_invalid",
            "The source snapshot envelope has unexpected fields.",
        )
    _require_digest_match(
        supplied_hash,
        canonical_json_sha256(frozen),
        "source_snapshot_hash_mismatch",
        "The source snapshot does not match its canonical SHA-256.",
    )
    annual_frozen = _mapping(
        frozen.get("source_annual_job"),
        "source_snapshot_invalid",
        "The source snapshot is missing its Annual job record.",
    )
    lineage = _mapping(
        frozen.get("calibration_lineage"),
        "source_snapshot_invalid",
        "The source snapshot is missing calibration lineage.",
    )
    origin_frozen = _mapping(
        lineage.get("origin_validation_job"),
        "source_snapshot_invalid",
        "The source snapshot is missing its origin validation record.",
    )
    promotion_frozen = _mapping(
        lineage.get("promotion"),
        "source_snapshot_invalid",
        "The source snapshot is missing its promotion receipt.",
    )
    artifact_frozen = _mapping(
        frozen.get("midc_source_artifact"),
        "source_snapshot_invalid",
        "The source snapshot is missing its immutable MIDC artifact.",
    )

    def atomic_source_check(connection: sqlite3.Connection) -> str | None:
        try:
            annual_row = connection.execute(
                "SELECT * FROM jobs WHERE job_id = ?",
                (str(annual_frozen.get("id")),),
            ).fetchone()
            origin_row = connection.execute(
                "SELECT * FROM jobs WHERE job_id = ?",
                (str(origin_frozen.get("id")),),
            ).fetchone()
            if annual_row is None or origin_row is None:
                return None
            annual_record = _decode_job_row(annual_row)
            origin_record = _decode_job_row(origin_row)
            if not _record_hashes_match(annual_record, annual_frozen):
                return None
            if not _record_hashes_match(origin_record, origin_frozen):
                return None
            annual_source = _verified_source_identity(
                annual_record,
                label="annual_midc",
            )
            _verified_source_identity(
                origin_record,
                label="origin_validation",
            )
            verify_annual_source_artifact(
                artifact_frozen,
                annual_job_id=str(annual_record["id"]),
                expected_sha256=str(annual_source["sha256"]),
                expected_bytes=int(annual_source["byte_count"]),
            )

            promotion_id = promotion_frozen.get("promotion_id")
            if isinstance(promotion_id, bool) or not isinstance(promotion_id, int):
                promotion_row = connection.execute(
                    """
                    SELECT * FROM baseline_promotions
                     WHERE mode = ? AND job_id = ? AND promoted_at = ?
                     ORDER BY promotion_id DESC LIMIT 1
                    """,
                    (
                        promotion_frozen.get("mode"),
                        promotion_frozen.get("job_id"),
                        promotion_frozen.get("promoted_at"),
                    ),
                ).fetchone()
            else:
                promotion_row = connection.execute(
                    "SELECT * FROM baseline_promotions WHERE promotion_id = ?",
                    (promotion_id,),
                ).fetchone()
            if promotion_row is None or not _canonical_equal(
                dict(promotion_row), promotion_frozen
            ):
                return None
            return supplied_hash
        except AnnualSourceValidationError:
            return None

    return atomic_source_check


def technoeconomic_source_store_fields(
    source_snapshot_envelope: Mapping[str, Any],
) -> dict[str, Any]:
    """Return source arguments whose persisted hash equals the envelope hash."""

    envelope = deepcopy(dict(source_snapshot_envelope))
    callback = make_atomic_source_recheck(envelope)
    payload = deepcopy(dict(envelope["source_snapshot"]))
    digest = str(envelope["source_snapshot_sha256"])
    if canonical_json_sha256(payload) != digest:
        _fail(
            "source_snapshot_hash_mismatch",
            "The source snapshot does not match its canonical SHA-256.",
        )
    artifact = _mapping(
        payload.get("midc_source_artifact"),
        "source_snapshot_invalid",
        "The source snapshot is missing its immutable MIDC artifact.",
    )
    return {
        "source_annual_job_id": payload["source_annual_job_id"],
        "source_artifact_storage_key": artifact["storage_key"],
        "source_artifact_sha256": artifact["sha256"],
        "source_artifact_bytes": artifact["byte_count"],
        "source_snapshot": payload,
        "atomic_source_check": callback,
    }


def inspect_annual_source_eligibility(
    annual_job: Mapping[str, Any],
    *,
    origin_validation_job: Mapping[str, Any] | None,
    promotion_record: Mapping[str, Any] | None,
    allow_legacy_capacity: bool = True,
) -> dict[str, Any]:
    """Return a safe eligibility summary without weakening snapshot validation."""

    try:
        envelope = build_annual_source_snapshot(
            annual_job,
            origin_validation_job=origin_validation_job,
            promotion_record=promotion_record,
            allow_legacy_capacity=allow_legacy_capacity,
        )
    except AnnualSourceValidationError as exc:
        return {
            "eligible": False,
            "reason_code": exc.code,
            "detail": exc.detail,
            "source_annual_job_id": annual_job.get("id") if isinstance(annual_job, Mapping) else None,
        }
    snapshot = envelope["source_snapshot"]
    capacity = snapshot["capacity_manifest"]["systems"]
    capacity_specs_tuple = _snapshot_capacity_specs(snapshot)
    capacity_specs = {item.system: item for item in capacity_specs_tuple}
    applied_capacity_specs = _snapshot_applied_capacity_specs(
        snapshot,
        capacity_specs,
    )
    annual_energy_by_year = [
        {
            "year": row["year"],
            "solectria_kwh": row["sol_predicted_kwh"],
            "solaredge_kwh": row["se_predicted_kwh"],
        }
        for row in snapshot["eligible_paired_energy_rows"]
    ]
    return {
        "eligible": True,
        "reason_code": None,
        "detail": None,
        "source_annual_job_id": snapshot["source_annual_job_id"],
        "eligible_years": [
            row["year"] for row in snapshot["eligible_paired_energy_rows"]
        ],
        "solectria_installed_wdc": capacity["solectria"]["installed_wdc"],
        "solaredge_installed_wdc": capacity["solaredge"]["installed_wdc"],
        "applied_capacity": {
            item.system: {
                "applied_capacity_w": item.applied_capacity_w,
                "rating_basis": item.rating_basis,
            }
            for item in applied_capacity_specs
        },
        "annual_energy_by_year": annual_energy_by_year,
        "capacity_manifest_source": snapshot["capacity_manifest_source"],
        "source_snapshot_sha256": envelope["source_snapshot_sha256"],
    }


def resolve_annual_source_dependencies(
    agent_store: Any,
    source_annual_job_id: str,
) -> dict[str, Any]:
    """Resolve the exact Annual, origin-validation, and promotion records.

    Store access is deliberately injected.  This keeps module singletons out of
    the source-verification layer and lets the caller hold its orchestration lock.
    The historical promotion lookup is exact rather than a bounded scan of recent
    promotion history.
    """

    source_id = _nonempty_text(
        source_annual_job_id,
        "annual_job_id_missing",
        "The selected Annual Simulation job ID is missing.",
    )
    annual_job = agent_store.get_job(source_id)
    annual = _mapping(
        annual_job,
        "annual_job_missing",
        "The selected Annual Simulation cannot be resolved.",
    )
    provenance = _mapping(
        annual.get("provenance"),
        "annual_provenance_missing",
        "The Annual Simulation durable provenance is missing.",
    )
    application = _mapping(
        provenance.get("calibration_application"),
        "calibration_application_missing",
        "The Annual Simulation durable calibration application is missing.",
    )
    origin_job_id = _nonempty_text(
        application.get("baseline_job_id"),
        "origin_job_id_missing",
        "The Annual calibration origin job ID is missing.",
    )
    promoted_at = _nonempty_text(
        application.get("baseline_promoted_at"),
        "origin_promotion_missing",
        "The Annual calibration promotion timestamp is missing.",
    )
    origin_job = agent_store.get_job(origin_job_id)
    promotion = agent_store.get_promotion(
        mode="validation",
        job_id=origin_job_id,
        promoted_at=promoted_at,
    )
    return {
        "annual_job": annual,
        "origin_validation_job": origin_job,
        "promotion_record": promotion,
    }


def _parsed_submission_request(
    request_payload: Mapping[str, Any] | TechnoeconomicSubmissionRequest,
) -> TechnoeconomicSubmissionRequest:
    if isinstance(request_payload, TechnoeconomicSubmissionRequest):
        payload: Mapping[str, Any] = request_payload.model_dump(
            mode="python",
            exclude_none=False,
        )
    elif isinstance(request_payload, Mapping):
        payload = request_payload
    else:
        raise TypeError("technoeconomic request payload must be an object")
    return TechnoeconomicSubmissionRequest.model_validate(dict(payload))


def _kernel_distribution(
    input_id: str,
    distribution: TechnoeconomicDistributionRequest,
) -> technoeconomic_kernel.DistributionSpec:
    values = distribution.model_dump(mode="python", exclude_none=True)
    family = values.pop("family")
    return technoeconomic_kernel.DistributionSpec(
        input_id=input_id,
        family=family,
        **values,
    )


def _snapshot_capacity_specs(
    source_snapshot: Mapping[str, Any],
) -> tuple[
    technoeconomic_kernel.CapacitySpec,
    technoeconomic_kernel.CapacitySpec,
]:
    manifest = _mapping(
        source_snapshot.get("capacity_manifest"),
        "source_snapshot_capacity_missing",
        "The frozen source snapshot has no capacity manifest.",
    )
    systems = _mapping(
        manifest.get("systems"),
        "source_snapshot_capacity_missing",
        "The frozen source snapshot has no per-system capacity records.",
    )
    if set(systems) != {"solectria", "solaredge"}:
        _fail(
            "source_snapshot_capacity_invalid",
            "The frozen source snapshot must contain exactly Solectria and SolarEdge capacities.",
        )
    result: list[technoeconomic_kernel.CapacitySpec] = []
    for system in ("solectria", "solaredge"):
        record = _mapping(
            systems.get(system),
            "source_snapshot_capacity_invalid",
            f"The frozen {system} capacity record is missing.",
        )
        try:
            result.append(
                technoeconomic_kernel.CapacitySpec(
                    system=system,
                    module_model=record["module_model"],
                    module_stc_wdc=record["module_stc_wdc"],
                    strings=record["strings"],
                    bays_per_string=record["bays_per_string"],
                    modules_per_bay=record["modules_per_bay"],
                    module_count=record["module_count"],
                    installed_wdc=record["installed_wdc"],
                    physics_version=record["calibration_physics_version"],
                    physics_fingerprint=record[
                        "calibration_physics_fingerprint"
                    ],
                )
            )
        except KeyError as exc:
            raise AnnualSourceValidationError(
                "source_snapshot_capacity_invalid",
                f"The frozen {system} capacity record is incomplete.",
            ) from exc
    return result[0], result[1]


def _snapshot_applied_capacity_specs(
    source_snapshot: Mapping[str, Any],
    capacities: Mapping[str, technoeconomic_kernel.CapacitySpec],
) -> tuple[
    technoeconomic_kernel.AppliedCapacitySpec,
    technoeconomic_kernel.AppliedCapacitySpec,
]:
    """Derive the v2 normalization basis from the frozen Annual request.

    The source snapshot already seals the complete Annual job and its immutable
    request, so the applied-capacity evidence does not need a second mutable or
    duplicated snapshot field.  A valid enabled AC operating limit is shared by
    both systems.  Otherwise each system falls back to its independently verified
    installed DC nameplate.
    """

    frozen_job = _mapping(
        source_snapshot.get("source_annual_job"),
        "source_snapshot_applied_capacity_missing",
        "The frozen source snapshot has no Annual job record.",
    )
    annual_request = _mapping(
        frozen_job.get("request"),
        "source_snapshot_applied_capacity_missing",
        "The frozen Annual job has no immutable request.",
    )

    operating_limit_kw: float | None = None
    raw_limit = annual_request.get("curtailment_limit_kw")
    if annual_request.get("curtailment_enabled") is True and not isinstance(
        raw_limit, bool
    ):
        try:
            candidate = float(raw_limit)
        except (TypeError, ValueError, OverflowError):
            candidate = math.nan
        if math.isfinite(candidate) and candidate > 0:
            operating_limit_kw = candidate

    if operating_limit_kw is not None:
        applied_w = operating_limit_kw * 1_000.0
        if not math.isfinite(applied_w):
            _fail(
                "source_snapshot_applied_capacity_invalid",
                "The frozen Annual AC operating limit cannot be represented in watts.",
            )
        return tuple(
            technoeconomic_kernel.AppliedCapacitySpec(
                system=system,
                applied_capacity_w=applied_w,
                rating_basis="ac_operating_limit",
            )
            for system in ("solectria", "solaredge")
        )  # type: ignore[return-value]

    return tuple(
        technoeconomic_kernel.AppliedCapacitySpec(
            system=system,
            applied_capacity_w=capacities[system].installed_wdc,
            rating_basis="dc_installed_nameplate",
        )
        for system in ("solectria", "solaredge")
    )  # type: ignore[return-value]


def _snapshot_energy_rows(
    source_snapshot: Mapping[str, Any],
) -> tuple[technoeconomic_kernel.PairedEnergyRow, ...]:
    raw_rows = _sequence(
        source_snapshot.get("eligible_paired_energy_rows"),
        "source_snapshot_energy_missing",
        "The frozen source snapshot has no eligible paired energy rows.",
    )
    rows: list[technoeconomic_kernel.PairedEnergyRow] = []
    for raw in raw_rows:
        row = _mapping(
            raw,
            "source_snapshot_energy_invalid",
            "A frozen paired energy row is invalid.",
        )
        try:
            rows.append(
                technoeconomic_kernel.PairedEnergyRow(
                    year=row["year"],
                    sol_predicted_kwh_ac=row["sol_predicted_kwh"],
                    se_predicted_kwh_ac=row["se_predicted_kwh"],
                    provenance=deepcopy(dict(row)),
                )
            )
        except KeyError as exc:
            raise AnnualSourceValidationError(
                "source_snapshot_energy_invalid",
                "A frozen paired energy row is incomplete.",
            ) from exc
    return tuple(rows)


def _cost_intensity_multipliers(
    line: Any,
    *,
    basis: str,
    normalization_capacity_w: Mapping[str, float],
) -> tuple[float, float]:
    quantities = {
        "solectria": float(line.solectria_quantity),
        "solaredge": float(line.solaredge_quantity),
    }
    if basis == "commercial_representative":
        # The strict schema permits only explicitly sourced commercial per-Wdc
        # target-year values.  No SolarTAC total is silently divided by a
        # hypothetical size, and the documented pre-submission currency index
        # is not applied a second time.
        return quantities["solectria"], quantities["solaredge"]
    return (
        quantities["solectria"] / normalization_capacity_w["solectria"],
        quantities["solaredge"] / normalization_capacity_w["solaredge"],
    )


def build_technoeconomic_kernel_request(
    request_payload: Mapping[str, Any] | TechnoeconomicSubmissionRequest,
    source_snapshot: Mapping[str, Any],
) -> technoeconomic_kernel.TechnoeconomicRequest:
    """Build and validate a kernel request from strict input plus frozen source.

    The API body has no capacity or energy fields.  Both system Wdc manifests and
    every paired weather row are reconstructed exclusively from the already
    verified immutable snapshot.  This helper is safe to call once before enqueue
    and again in the worker from the two frozen durable payloads.
    """

    request = _parsed_submission_request(request_payload)
    snapshot = _mapping(
        source_snapshot,
        "source_snapshot_invalid",
        "The frozen Annual source snapshot is invalid.",
    )
    snapshot_source_id = _nonempty_text(
        snapshot.get("source_annual_job_id"),
        "source_snapshot_invalid",
        "The frozen source snapshot has no Annual job ID.",
    )
    if not secrets.compare_digest(snapshot_source_id, request.source_annual_job_id):
        _fail(
            "source_snapshot_job_mismatch",
            "The request Annual job ID does not match the frozen source snapshot.",
        )

    capacities_tuple = _snapshot_capacity_specs(snapshot)
    capacities = {item.system: item for item in capacities_tuple}
    applied_capacities = (
        _snapshot_applied_capacity_specs(snapshot, capacities)
        if request.capacity_normalization == ANNUAL_APPLIED_CAPACITY_NORMALIZATION
        else None
    )
    if applied_capacities is None:
        normalization_capacity_w = {
            system: capacity.installed_wdc
            for system, capacity in capacities.items()
        }
    else:
        normalization_capacity_w = {
            capacity.system: capacity.applied_capacity_w
            for capacity in applied_capacities
        }
    paired_rows = _snapshot_energy_rows(snapshot)

    cost_lines: list[technoeconomic_kernel.CostLineSpec] = []
    for line in request.cost_lines:
        sol_multiplier, se_multiplier = _cost_intensity_multipliers(
            line,
            basis=request.basis,
            normalization_capacity_w=normalization_capacity_w,
        )
        cost_lines.append(
            technoeconomic_kernel.CostLineSpec(
                input_id=line.input_id,
                label=line.label,
                basis=request.basis,
                ownership=line.ownership,
                cost_type=line.cost_type,
                distribution=_kernel_distribution(
                    line.input_id,
                    line.distribution,
                ),
                solectria_multiplier_to_intensity=sol_multiplier,
                solaredge_multiplier_to_intensity=se_multiplier,
                coverage_ids=tuple(line.coverage_include_ids),
                solectria_treatment_key=technoeconomic_kernel.SUPPORTED_COST_TREATMENT,
                solaredge_treatment_key=technoeconomic_kernel.SUPPORTED_COST_TREATMENT,
            )
        )

    transfer: technoeconomic_kernel.TransferSpec | None = None
    if request.commercial_transfer is not None:
        transfer = technoeconomic_kernel.TransferSpec(
            baseline=_kernel_distribution(
                "transfer.baseline",
                request.commercial_transfer.baseline_factor.distribution,
            ),
            incremental=_kernel_distribution(
                "transfer.incremental",
                request.commercial_transfer.incremental_factor.distribution,
            ),
            mechanism_status=request.commercial_transfer.status,
        )

    kernel_request = technoeconomic_kernel.TechnoeconomicRequest(
        basis=request.basis,
        n=request.n,
        seed=request.seed,
        project_life_years=request.finance.project_life_years,
        capacities=capacities_tuple,
        paired_energy_rows=paired_rows,
        cost_lines=tuple(cost_lines),
        discount_rate=_kernel_distribution(
            "finance.discount-rate",
            request.finance.real_discount_rate.distribution,
        ),
        shared_degradation=_kernel_distribution(
            "energy.shared-degradation",
            request.shared_degradation.annual_rate.distribution,
        ),
        applied_capacities=applied_capacities,
        transfer=transfer,
        commercial_reference_wdc=(
            request.commercial_reference_design.reference_wdc
            if request.commercial_reference_design is not None
            else None
        ),
        cost_stack_completeness=request.cost_stack_completeness,
        calculation_contract_version=(
            technoeconomic_kernel.CALCULATION_CONTRACT_VERSION
            if request.capacity_normalization == ANNUAL_APPLIED_CAPACITY_NORMALIZATION
            else technoeconomic_kernel.LEGACY_CALCULATION_CONTRACT_VERSION
        ),
        sampling_version=technoeconomic_kernel.SAMPLING_VERSION,
    )
    return technoeconomic_kernel.validate_request(kernel_request)


def _evidence_receipt(
    request: TechnoeconomicSubmissionRequest,
) -> dict[str, Any]:
    subjects: list[tuple[str, TechnoeconomicEvidenceRequest]] = [
        (f"cost:{line.input_id}", line.evidence) for line in request.cost_lines
    ]
    subjects.extend(
        [
            ("finance:project-life", request.finance.project_life_evidence),
            (
                "finance:discount-rate",
                request.finance.real_discount_rate.evidence,
            ),
            (
                "energy:shared-degradation",
                request.shared_degradation.annual_rate.evidence,
            ),
        ]
    )
    if request.commercial_reference_design is not None:
        subjects.append(
            ("commercial:reference-design", request.commercial_reference_design.evidence)
        )
    if request.commercial_transfer is not None:
        subjects.extend(
            [
                (
                    "transfer:baseline-factor",
                    request.commercial_transfer.baseline_factor.evidence,
                ),
                (
                    "transfer:incremental-factor",
                    request.commercial_transfer.incremental_factor.evidence,
                ),
            ]
        )
        subjects.extend(
            (
                f"transfer-mechanism:{mechanism.mechanism}",
                mechanism.evidence,
            )
            for mechanism in request.commercial_transfer.mechanisms
        )

    subjects.extend(
        (
            f"cost-currency-index:{line.input_id}",
            line.currency_year_normalization.index_source_evidence,
        )
        for line in request.cost_lines
        if line.currency_year_normalization.method == "price_index_adjustment"
    )

    counts: dict[str, int] = {}
    preservation_counts: dict[str, int] = {}
    preservation: list[dict[str, Any]] = []
    provisional: list[dict[str, Any]] = []
    for subject, evidence in subjects:
        counts[evidence.evidence_class] = counts.get(evidence.evidence_class, 0) + 1
        citation = evidence.citation
        preservation_counts[citation.preservation_mode] = (
            preservation_counts.get(citation.preservation_mode, 0) + 1
        )
        preservation.append(
            {
                "subject": subject,
                "mode": citation.preservation_mode,
                "user_supplied_content_sha256": (
                    citation.user_supplied_content_sha256
                ),
                "content_sha256_provenance": (
                    "user_supplied_metadata"
                    if citation.user_supplied_content_sha256 is not None
                    else None
                ),
                "server_verified_bytes": False,
                "metadata_only_rationale": citation.metadata_only_rationale,
            }
        )
        if evidence.evidence_class in {
            "engineering_judgment",
            "secondary_synthesis",
        }:
            provisional.append(
                {
                    "subject": subject,
                    "evidence_class": evidence.evidence_class,
                    "explicit_acceptance": evidence.explicit_acceptance is True,
                    "acceptance_rationale_sha256": canonical_json_sha256(
                        evidence.acceptance_rationale
                    ),
                }
            )
    return {
        "status": "provisional_inputs" if provisional else "documented_inputs",
        "evidence_class_counts": dict(sorted(counts.items())),
        "preservation_mode_counts": dict(sorted(preservation_counts.items())),
        "subject_count": len(subjects),
        "preservation": sorted(preservation, key=lambda item: item["subject"]),
        "provisional_inputs": sorted(provisional, key=lambda item: item["subject"]),
    }


def _normalization_receipt(
    request: TechnoeconomicSubmissionRequest,
    kernel_request: technoeconomic_kernel.TechnoeconomicRequest,
) -> dict[str, Any]:
    source_lines = {line.input_id: line for line in request.cost_lines}
    capacities = {item.system: item for item in kernel_request.capacities}
    applied_capacities = {
        item.system: item
        for item in (kernel_request.applied_capacities or ())
    }
    applied_capacity_receipt: dict[str, dict[str, Any]] | None = None
    if request.capacity_normalization == ANNUAL_APPLIED_CAPACITY_NORMALIZATION:
        applied_capacity_receipt = {}
        for system in ("solectria", "solaredge"):
            applied = applied_capacities[system]
            applied_capacity_receipt[system] = {
                "applied_capacity_w": applied.applied_capacity_w,
                "rating_basis": applied.rating_basis,
                "selection_method": (
                    "enabled_positive_annual_curtailment_else_installed_dc"
                ),
                "source_field": (
                    "source_snapshot.source_annual_job.request."
                    "curtailment_limit_kw"
                    if applied.rating_basis == "ac_operating_limit"
                    else "source_snapshot.capacity_manifest.systems."
                    f"{system}.installed_wdc"
                ),
            }
    receipts: list[dict[str, Any]] = []
    for line in kernel_request.cost_lines:
        source = source_lines[line.input_id]
        if request.capacity_normalization == ANNUAL_APPLIED_CAPACITY_NORMALIZATION:
            capacity_denominator: dict[str, Any] = {
                "method": "frozen_annual_applied_capacity_v1",
                "solectria": {
                    "applied_capacity_w": applied_capacities[
                        "solectria"
                    ].applied_capacity_w,
                    "rating_basis": applied_capacities["solectria"].rating_basis,
                    "source_field": (
                        "source_snapshot.source_annual_job.request."
                        "curtailment_limit_kw"
                        if applied_capacities["solectria"].rating_basis
                        == "ac_operating_limit"
                        else "source_snapshot.capacity_manifest.systems."
                        "solectria.installed_wdc"
                    ),
                    "applied": source.solectria_quantity > 0,
                },
                "solaredge": {
                    "applied_capacity_w": applied_capacities[
                        "solaredge"
                    ].applied_capacity_w,
                    "rating_basis": applied_capacities["solaredge"].rating_basis,
                    "source_field": (
                        "source_snapshot.source_annual_job.request."
                        "curtailment_limit_kw"
                        if applied_capacities["solaredge"].rating_basis
                        == "ac_operating_limit"
                        else "source_snapshot.capacity_manifest.systems."
                        "solaredge.installed_wdc"
                    ),
                    "applied": source.solaredge_quantity > 0,
                },
            }
            denominator_field = "capacity_denominator"
        elif request.basis == "solartac_site":
            capacity_denominator = {
                "method": "frozen_annual_source_capacity_manifest",
                "solectria": {
                    "installed_wdc": capacities["solectria"].installed_wdc,
                    "source_field": (
                        "source_snapshot.capacity_manifest.systems."
                        "solectria.installed_wdc"
                    ),
                    "applied": source.solectria_quantity > 0,
                },
                "solaredge": {
                    "installed_wdc": capacities["solaredge"].installed_wdc,
                    "source_field": (
                        "source_snapshot.capacity_manifest.systems."
                        "solaredge.installed_wdc"
                    ),
                    "applied": source.solaredge_quantity > 0,
                },
            }
            denominator_field = "wdc_denominator"
        else:
            design = request.commercial_reference_design
            if design is None:  # guarded by the strict request model
                _fail(
                    "commercial_reference_design_missing",
                    "Commercial normalization has no reference design.",
                )
            capacity_denominator = {
                "method": "declared_commercial_per_wdc_basis",
                "reference_design_id": design.design_id,
                "reference_wdc": design.reference_wdc,
                "applied_to_input_normalization": False,
            }
            denominator_field = "wdc_denominator"
        receipt = {
                "input_id": line.input_id,
                "basis": request.basis,
                "ownership": line.ownership,
                "cost_type": line.cost_type,
                "original_unit": source.original_unit,
                "normalized_unit": source.normalized_unit,
                "normalization_method": source.normalization_method,
                "solectria_quantity": source.solectria_quantity,
                "solaredge_quantity": source.solaredge_quantity,
                "quantity_unit": source.quantity_unit,
                "normalization_derivation": source.normalization_derivation,
                "constant_dollar_cost_year": source.constant_dollar_cost_year,
                "currency_year_normalization": (
                    source.currency_year_normalization.model_dump(
                        mode="json",
                        exclude_none=False,
                    )
                ),
                "documented_pre_submission_index_factor": (
                    source.currency_year_normalization.index_factor
                ),
                "solectria_multiplier_to_intensity": (
                    line.solectria_multiplier_to_intensity
                ),
                "solaredge_multiplier_to_intensity": (
                    line.solaredge_multiplier_to_intensity
                ),
            }
        receipt[denominator_field] = capacity_denominator
        receipts.append(receipt)
    normalization_receipt: dict[str, Any] = {
        "status": "validated",
        "lines": receipts,
    }
    if applied_capacity_receipt is not None:
        normalization_receipt["capacity_normalization"] = (
            request.capacity_normalization
        )
        normalization_receipt["applied_capacities"] = applied_capacity_receipt
    return normalization_receipt


def _overlap_receipt(
    request: TechnoeconomicSubmissionRequest,
    kernel_request: technoeconomic_kernel.TechnoeconomicRequest,
) -> dict[str, Any]:
    source_lines = {line.input_id: line for line in request.cost_lines}
    assignments: list[dict[str, Any]] = []
    scopes: dict[str, dict[str, Any]] = {}
    ordered_lines = sorted(kernel_request.cost_lines, key=lambda item: item.input_id)
    for line in ordered_lines:
        systems = (
            ["solectria"]
            if line.ownership == "solectria_only"
            else ["solaredge"]
            if line.ownership == "solaredge_only"
            else ["solectria", "solaredge"]
        )
        timing_group = (
            "initial_t0"
            if line.cost_type in technoeconomic_kernel.INITIAL_COST_TYPES
            else "recurring_year_end"
        )
        source = source_lines[line.input_id]
        scopes[line.input_id] = {
            "systems": systems,
            "timing_group": timing_group,
            "coverage_include_ids": sorted(line.coverage_ids),
            "coverage_exclude_ids": sorted(source.coverage_exclude_ids),
        }
        for system in systems:
            for coverage_id in line.coverage_ids:
                assignments.append(
                    {
                        "system": system,
                        "timing_group": timing_group,
                        "coverage_id": coverage_id,
                        "input_id": line.input_id,
                    }
                )
        assignments.append(
            {
                "input_id": line.input_id,
                "excluded_coverage_ids": list(source.coverage_exclude_ids),
            }
        )

    pairwise_decisions: list[dict[str, Any]] = []
    potentially_overlapping_pairs = 0
    for left_index, left in enumerate(ordered_lines):
        for right in ordered_lines[left_index + 1 :]:
            left_scope = scopes[left.input_id]
            right_scope = scopes[right.input_id]
            shared_systems = sorted(
                set(left_scope["systems"]) & set(right_scope["systems"])
            )
            same_timing = (
                left_scope["timing_group"] == right_scope["timing_group"]
            )
            shared_coverage = sorted(
                set(left.coverage_ids) & set(right.coverage_ids)
            )
            left_excludes_right = sorted(
                set(left_scope["coverage_exclude_ids"]) & set(right.coverage_ids)
            )
            right_excludes_left = sorted(
                set(right_scope["coverage_exclude_ids"]) & set(left.coverage_ids)
            )
            potentially_overlapping = bool(shared_systems and same_timing)
            if potentially_overlapping:
                potentially_overlapping_pairs += 1
            if not shared_systems:
                decision = "disjoint_system_ownership"
            elif not same_timing:
                decision = "disjoint_cost_timing"
            elif shared_coverage:
                _fail(
                    "cost_coverage_overlap",
                    "Validated kernel request contains overlapping cost coverage.",
                )
            elif left_excludes_right or right_excludes_left:
                decision = "disjoint_by_declared_exclusion"
            else:
                decision = "disjoint_stable_coverage_ids"
            pairwise_decisions.append(
                {
                    "left_input_id": left.input_id,
                    "right_input_id": right.input_id,
                    "potentially_overlapping": potentially_overlapping,
                    "shared_systems": shared_systems,
                    "same_timing_group": same_timing,
                    "shared_coverage_ids": shared_coverage,
                    "left_excludes_right_coverage_ids": left_excludes_right,
                    "right_excludes_left_coverage_ids": right_excludes_left,
                    "decision": decision,
                    "overlap_detected": False,
                }
            )
    return {
        "status": "validated_no_overlap",
        "assignments": assignments,
        "line_scopes": [
            {"input_id": input_id, **scopes[input_id]}
            for input_id in sorted(scopes)
        ],
        "pair_count": len(pairwise_decisions),
        "potentially_overlapping_pair_count": potentially_overlapping_pairs,
        "pairwise_decisions": pairwise_decisions,
    }


def _commercial_reference_receipt(
    request: TechnoeconomicSubmissionRequest,
) -> dict[str, Any] | None:
    design = request.commercial_reference_design
    if design is None:
        return None
    design_payload = design.model_dump(mode="json", exclude_none=False)
    return {
        "design_id": design.design_id,
        "reference_wdc": design.reference_wdc,
        "module_model": design.module_model,
        "module_stc_wdc": design.module_stc_wdc,
        "module_count": design.module_count,
        "constant_dollar_cost_year": design.constant_dollar_cost_year,
        "design_sha256": canonical_json_sha256(design_payload),
    }


def _transfer_receipt(request: TechnoeconomicSubmissionRequest) -> dict[str, Any]:
    if request.basis == "solartac_site":
        return {
            "status": "not_applicable",
            "energy_available": True,
            "commercial_reference_design": None,
        }
    transfer = request.commercial_transfer
    reference_design = _commercial_reference_receipt(request)
    if transfer is None:
        return {
            "status": "cost_only",
            "energy_available": False,
            "commercial_reference_design": reference_design,
            "baseline_factor": None,
            "incremental_factor": None,
        }
    return {
        "status": "approved",
        "energy_available": True,
        "commercial_reference_design": reference_design,
        "explicit_attestation": transfer.explicit_attestation,
        "attested_by": transfer.attested_by,
        "attested_at": transfer.attested_at,
        "attestation_rationale_sha256": canonical_json_sha256(
            transfer.attestation_rationale
        ),
        "baseline_factor_input_id": "transfer.baseline",
        "incremental_factor_input_id": "transfer.incremental",
        "all_mechanisms_resolved": all(
            item.status in {"supported", "not_applicable"}
            for item in transfer.mechanisms
        ),
        "mechanisms": [
            {
                "mechanism": item.mechanism,
                "status": item.status,
                "rationale_sha256": canonical_json_sha256(item.rationale),
            }
            for item in sorted(transfer.mechanisms, key=lambda value: value.mechanism)
        ],
    }


def build_technoeconomic_submission_provenance(
    request_payload: Mapping[str, Any] | TechnoeconomicSubmissionRequest,
    source_snapshot_envelope: Mapping[str, Any],
    validated_kernel_request: technoeconomic_kernel.TechnoeconomicRequest,
) -> dict[str, Any]:
    """Build deterministic immutable validation receipts for one submission."""

    request = _parsed_submission_request(request_payload)
    envelope = _mapping(
        source_snapshot_envelope,
        "source_snapshot_envelope_invalid",
        "The source snapshot envelope is invalid.",
    )
    if set(envelope) != {"source_snapshot", "source_snapshot_sha256"}:
        _fail(
            "source_snapshot_envelope_invalid",
            "The source snapshot envelope has unexpected fields.",
        )
    snapshot = _mapping(
        envelope.get("source_snapshot"),
        "source_snapshot_invalid",
        "The source snapshot envelope has no payload.",
    )
    snapshot_sha256 = _sha256(
        envelope.get("source_snapshot_sha256"),
        "source_snapshot_hash_invalid",
        "The source snapshot SHA-256 is missing or invalid.",
    )
    _require_digest_match(
        snapshot_sha256,
        canonical_json_sha256(snapshot),
        "source_snapshot_hash_mismatch",
        "The source snapshot does not match its canonical SHA-256.",
    )

    expected_kernel = build_technoeconomic_kernel_request(request, snapshot)
    supplied_kernel = technoeconomic_kernel.validate_request(validated_kernel_request)
    expected_kernel_payload = technoeconomic_kernel.canonical_request_payload(
        expected_kernel
    )
    supplied_kernel_payload = technoeconomic_kernel.canonical_request_payload(
        supplied_kernel
    )
    expected_kernel_hash = canonical_json_sha256(expected_kernel_payload)
    supplied_kernel_hash = canonical_json_sha256(supplied_kernel_payload)
    if not secrets.compare_digest(expected_kernel_hash, supplied_kernel_hash):
        _fail(
            "kernel_request_mismatch",
            "The validated kernel request does not match the strict request and frozen source.",
        )

    canonical_request = request.model_dump(mode="json", exclude_none=False)
    if request.capacity_normalization is None:
        # This field did not exist on v1 durable requests.  Omitting its default
        # preserves their exact immutable request/provenance hashes on retry.
        canonical_request.pop("capacity_normalization", None)
    normalization = _normalization_receipt(request, supplied_kernel)
    overlap = _overlap_receipt(request, supplied_kernel)
    evidence = _evidence_receipt(request)
    transfer = _transfer_receipt(request)
    commercial_reference = _commercial_reference_receipt(request)
    receipts = {
        "normalization": normalization,
        "overlap": overlap,
        "evidence": evidence,
        "commercial_transfer": transfer,
    }
    provenance = {
        "schema_version": (
            2
            if request.capacity_normalization == ANNUAL_APPLIED_CAPACITY_NORMALIZATION
            else TECHNOECONOMIC_SUBMISSION_PROVENANCE_SCHEMA_VERSION
        ),
        "source_annual_job_id": request.source_annual_job_id,
        "analysis_basis": request.basis,
        "commercial_transfer_status": transfer["status"],
        "commercial_reference_design": commercial_reference,
        "commercial_reference_design_sha256": (
            commercial_reference["design_sha256"]
            if commercial_reference is not None
            else None
        ),
        "commercial_reference_receipt_sha256": (
            canonical_json_sha256(commercial_reference)
            if commercial_reference is not None
            else None
        ),
        "calculation_contract_version": supplied_kernel.calculation_contract_version,
        "sampling_version": supplied_kernel.sampling_version,
        "request_schema": (
            "technoeconomic-submission-v2"
            if request.capacity_normalization == ANNUAL_APPLIED_CAPACITY_NORMALIZATION
            else "technoeconomic-submission-v1"
        ),
        "request_sha256": canonical_json_sha256(canonical_request),
        "source_snapshot_sha256": snapshot_sha256,
        "validated_kernel_request_sha256": supplied_kernel_hash,
        "normalization_receipt": normalization,
        "normalization_receipt_sha256": canonical_json_sha256(normalization),
        "overlap_receipt": overlap,
        "overlap_receipt_sha256": canonical_json_sha256(overlap),
        "evidence_receipt": evidence,
        "evidence_receipt_sha256": canonical_json_sha256(evidence),
        "commercial_transfer_receipt": transfer,
        "commercial_transfer_receipt_sha256": canonical_json_sha256(transfer),
        "validation_receipts_sha256": canonical_json_sha256(receipts),
        "provisional_inputs": evidence["status"] == "provisional_inputs",
    }
    if request.capacity_normalization is not None:
        provenance["capacity_normalization"] = request.capacity_normalization
    return provenance


__all__ = [
    "ANNUAL_SOURCE_ELIGIBILITY_VERSION",
    "ANNUAL_SOURCE_SNAPSHOT_SCHEMA_VERSION",
    "AnnualSourceValidationError",
    "TECHNOECONOMIC_SUBMISSION_PROVENANCE_SCHEMA_VERSION",
    "build_annual_source_snapshot",
    "build_technoeconomic_kernel_request",
    "build_technoeconomic_submission_provenance",
    "canonical_json_sha256",
    "harden_annual_source_artifact",
    "inspect_annual_source_eligibility",
    "make_atomic_source_recheck",
    "resolve_annual_source_dependencies",
    "technoeconomic_source_store_fields",
    "validate_capacity_manifest",
    "verify_annual_source_artifact",
]
