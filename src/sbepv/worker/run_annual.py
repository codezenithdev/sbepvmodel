"""Executes one annual simulation job: MIDC download -> model -> artifacts."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from sbepv import model
from copy import deepcopy

from sbepv.api import config, plots, state
from sbepv.api.artifacts import (
    _job_attempt_prefix,
    _output_url,
    _public_source_url,
    _workbook_download_name,
)
from sbepv.api.job_store import _check_job_cancelled, _get_job_record, _update_job
from sbepv.api.plots import _render_midc_input_data_plots
from sbepv.api.request_context import _iam_metadata
from sbepv.api.schemas import AnnualRunRequest
from sbepv.api.validation import _annual_dates, _annual_interval_seconds
from sbepv.ingest import midc
from sbepv import reporting
from sbepv.reporting import sha256_file
from sbepv.worker import completion

logger = logging.getLogger(__name__)


def _run_annual_job(
    job_id: str,
    req: AnnualRunRequest,
    *,
    source_path: str | Path | None = None,
    expected_source_hash: str | None = None,
    calibration_profile: dict[str, Any] | None = None,
    calibration_application_context: dict[str, Any] | None = None,
    worker_id: str | None = None,
    lease_token: str | None = None,
) -> None:
    state.JOBS.setdefault(job_id, {"mode": "annual", "state": "running"})

    def set_progress(pct: int, stage: str) -> None:
        _check_job_cancelled(
            job_id, worker_id=worker_id, lease_token=lease_token
        )
        _update_job(
            job_id,
            worker_id=worker_id,
            lease_token=lease_token,
            progress=int(pct),
            stage=stage,
        )

    try:
        start_date, end_date = _annual_dates(req)
        interval_seconds = _annual_interval_seconds(req)
        interval_hours = interval_seconds // 3_600
        attempt_prefix = _job_attempt_prefix(job_id, lease_token)
        csv_path = (
            Path(source_path)
            if source_path and expected_source_hash
            else config.OUTPUT_DIR / f"{attempt_prefix}_midc_hourly.csv"
        )
        base_path = config.OUTPUT_DIR / attempt_prefix
        source_warnings: list[str] = []
        source_quality: dict[str, Any]

        if source_path and expected_source_hash:
            set_progress(5, "Verifying cached annual source")
            source_hash = reporting.verify_source_sha256(csv_path, expected_source_hash)
            import pandas as pd

            interval_rows = int(len(pd.read_csv(csv_path)))
            source_quality = {
                "raw_rows": None,
                "hourly_rows": interval_rows if interval_seconds == 3_600 else None,
                "interval_rows": interval_rows,
                "interval_seconds": interval_seconds,
                "chunk_count": None,
                "missing_value_count": None,
                "affected_hour_count": None,
                "reused_verified_source": True,
            }
        else:
            def download_progress(frac: float, msg: str) -> None:
                set_progress(5 + int(frac * 20), msg)

            set_progress(5, "Downloading MIDC minute data")
            source = midc.fetch_hourly_data(
                start_date,
                end_date,
                interval_seconds=interval_seconds,
                progress_cb=download_progress,
            )
            _check_job_cancelled(
                job_id, worker_id=worker_id, lease_token=lease_token
            )
            set_progress(27, "Saving exact MIDC interval source")
            midc.write_csv_atomically(source.interval_data, csv_path)
            source_hash = sha256_file(csv_path)
            source_warnings = list(source.warnings)
            source_quality = {
                "raw_rows": source.raw_rows,
                "hourly_rows": (
                    int(len(source.interval_data)) if interval_seconds == 3_600 else None
                ),
                "interval_rows": int(len(source.interval_data)),
                "interval_seconds": interval_seconds,
                "chunk_count": source.chunk_count,
                "missing_value_count": source.missing_value_count,
                "affected_hour_count": source.affected_hour_count,
                "reused_verified_source": False,
            }
        _update_job(
            job_id,
            worker_id=worker_id,
            lease_token=lease_token,
            source_path=str(csv_path.resolve()),
            source_hash=source_hash,
        )
        set_progress(28, "Rendering annual irradiance inputs")
        input_plots = _render_midc_input_data_plots(csv_path, base_path)
        existing_artifacts = (_get_job_record(job_id) or {}).get("artifacts") or {}
        _update_job(
            job_id,
            worker_id=worker_id,
            lease_token=lease_token,
            artifacts={**existing_artifacts, "input_plots": input_plots},
        )

        def model_progress(frac: float, msg: str) -> None:
            set_progress(30 + int(frac * 60), msg)

        set_progress(30, "Running annual PV model")
        stats = model.run_model(
            input_csv=str(csv_path),
            output_base=str(base_path),
            progress_cb=model_progress,
            backtrack=req.backtrack,
            solaredge_inverter_efficiency=req.solaredge_inverter_efficiency,
            solaredge_bos_efficiency=req.solaredge_bos_efficiency,
            solectria_inverter_efficiency=req.solectria_inverter_efficiency,
            solectria_bos_efficiency=req.solectria_bos_efficiency,
            iam_model=req.iam_model,
            iam_a_r=(req.iam_a_r if req.iam_model == "martin_ruiz" else None),
            curtailment_enabled=req.curtailment_enabled,
            curtailment_limit_kw=req.curtailment_limit_kw,
            input_kind="midc",
            annual_mode=True,
            expected_interval_seconds=interval_seconds,
            calibration_profile=calibration_profile,
            calibration_application_context=calibration_application_context,
        )
        warnings = list(
            dict.fromkeys([*source_warnings, *stats.get("data_quality_warnings", [])])
        )
        stats["data_quality_warnings"] = warnings
        model_application = stats.get("calibration_application")
        calibration_application: dict[str, Any] = (
            {
                key: deepcopy(value)
                for key, value in model_application.items()
                if key not in {"origin_profile", "resolved_profile"}
            }
            if isinstance(model_application, dict)
            else {}
        )
        if isinstance(model_application, dict):
            # Profiles stay in durable provenance. Results expose the hashes,
            # factors, lineage, deltas and consent without duplicating fit details.
            stats["calibration_application"] = deepcopy(calibration_application)
        if calibration_profile is not None and calibration_application_context:
            resolved_profile = calibration_application_context.get(
                "resolved_profile"
            )
            calibration_application.update(
                {
                    "applied": True,
                    "method": "frozen_baseline_seasonal_factors",
                    "baseline_job_id": calibration_application_context.get(
                        "baseline_job_id"
                    ),
                    "baseline_review_id": calibration_application_context.get(
                        "baseline_review_id"
                    ),
                    "server_timestamp": calibration_application_context.get(
                        "server_timestamp"
                    ),
                    "origin_profile_sha256": calibration_application_context.get(
                        "origin_profile_sha256"
                    ),
                    "resolved_profile_sha256": calibration_application_context.get(
                        "resolved_profile_sha256"
                    ),
                    "required_seasons": deepcopy(
                        calibration_application_context.get("required_seasons") or []
                    ),
                    "seasonal_factors": deepcopy(
                        (resolved_profile or {}).get("seasonal_factors") or {}
                    ),
                    "settings_deltas": deepcopy(
                        calibration_application_context.get("settings_deltas") or []
                    ),
                    "seasonal_substitution": deepcopy(
                        calibration_application_context.get("seasonal_substitution")
                    ),
                    "server_confirmation": deepcopy(
                        calibration_application_context.get("server_confirmation")
                    ),
                }
            )
        elif not calibration_application:
            calibration_application = {
                "applied": False,
                "method": "physics_only",
            }
        set_progress(96, "Finalizing annual results")
        result = {
            "mode": "annual",
            "stats": stats,
            "ac_png": _output_url(Path(stats["ac_png"])),
            "energy_png": _output_url(Path(stats["energy_png"])),
            "monthly_png": _output_url(Path(stats["monthly_png"])),
            "excel": _output_url(Path(stats["excel"])),
            "excel_filename": _workbook_download_name(req),
            "input_plots": state.JOBS[job_id].get("input_plots"),
            "source_csv": _public_source_url(csv_path),
            "warnings": warnings,
            "source_quality": source_quality,
            "calibration_application": calibration_application,
            "window": {
                "from": req.from_date,
                "to": req.to_date,
                "interval_value": req.interval_value,
                "interval_unit": req.interval_unit,
                "interval_seconds": interval_seconds,
                "interval_hours": interval_hours,
                "timezone": "MST (UTC-7)",
                "hour_convention": "right-closed, right-labeled",
                "backtrack": req.backtrack,
                "solaredge_inverter_efficiency": req.solaredge_inverter_efficiency,
                "solaredge_bos_efficiency": req.solaredge_bos_efficiency,
                "solectria_inverter_efficiency": req.solectria_inverter_efficiency,
                "solectria_bos_efficiency": req.solectria_bos_efficiency,
                "solaredge_total_efficiency": (
                    req.solaredge_inverter_efficiency * req.solaredge_bos_efficiency
                ),
                "solectria_total_efficiency": (
                    req.solectria_inverter_efficiency * req.solectria_bos_efficiency
                ),
                **_iam_metadata(req),
                "curtailment_enabled": req.curtailment_enabled,
                "curtailment_limit_kw": (
                    float(req.curtailment_limit_kw)
                    if req.curtailment_enabled
                    else None
                ),
            },
        }
        completion._finish_model_job(
            job_id,
            result,
            worker_id=worker_id,
            lease_token=lease_token,
        )
    except Exception as exc:
        completion._handle_model_failure(
            job_id,
            exc,
            worker_id=worker_id,
            lease_token=lease_token,
        )
