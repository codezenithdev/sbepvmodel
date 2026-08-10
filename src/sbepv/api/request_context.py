"""Turning validated requests into the canonical dicts stored with a job.

The context recorded here is what the agent, the comparison report, and the
audit trail all read back, so it deliberately drops the deprecated ``include_iam``
flag and records the resolved IAM selection instead.
"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any

from pydantic import BaseModel

from sbepv.api.schemas import (
    AnnualRunRequest,
    AnnualRunSubmission,
    RunRequest,
)
from sbepv.api.validation import (
    _annual_dates,
    _request_fields_set,
    _validate_curtailment,
    _validate_run_request,
)


def _model_dump(obj: BaseModel) -> dict:
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    return obj.dict()


def _iam_metadata(req: RunRequest | AnnualRunRequest) -> dict[str, str | float | None]:
    return {
        "iam_model": req.iam_model,
        "iam_a_r": (
            float(req.iam_a_r) if req.iam_model == "martin_ruiz" else None
        ),
    }


def _run_request_context(req: RunRequest | AnnualRunRequest) -> dict:
    """Serialize the canonical IAM selection without the legacy input flag."""
    context = _model_dump(req)
    context.update(_iam_metadata(req))
    return context


_CALIBRATION_SETTING_FIELDS = (
    "backtrack",
    "solaredge_inverter_efficiency",
    "solaredge_bos_efficiency",
    "solectria_inverter_efficiency",
    "solectria_bos_efficiency",
    "iam_model",
    "iam_a_r",
    "curtailment_enabled",
    "curtailment_limit_kw",
)
_METEOROLOGICAL_SEASONS = ("winter", "spring", "summer", "fall")
_ANNUAL_FALLBACK_MAPPING = {
    "target_season": "fall",
    "source_season": "spring",
}


def _json_sha256(value: Any) -> str:
    """Return a stable SHA-256 fingerprint for a JSON-safe value."""

    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _annual_submission_request(
    submission: AnnualRunSubmission,
    *,
    inherited_settings: dict[str, Any] | None = None,
) -> tuple[AnnualRunRequest, dict[str, Any]]:
    """Return an executable annual request with API-only controls removed.

    When a reviewed baseline is selected, omitted shared settings inherit from
    that baseline. Explicitly supplied annual fields remain user-editable.
    """

    supplied_fields = _request_fields_set(submission)
    _validate_run_request(submission)
    _validate_curtailment(submission)
    _annual_dates(submission)
    values = _model_dump(submission)
    values.pop("calibration_baseline_job_id", None)
    values.pop("seasonal_fallback_acknowledgement", None)
    if inherited_settings:
        effective_fields = set(supplied_fields)
        if "include_iam" in supplied_fields and "iam_model" not in supplied_fields:
            effective_fields.add("iam_model")
        for field in _CALIBRATION_SETTING_FIELDS:
            if field not in effective_fields:
                values[field] = deepcopy(inherited_settings[field])
    request = AnnualRunRequest(**values)
    _validate_run_request(request)
    _validate_curtailment(request)
    _annual_dates(request)
    return request, _run_request_context(request)
