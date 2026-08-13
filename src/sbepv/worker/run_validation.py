"""Executes one calibration/validation job: historian -> model -> artifacts."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from sbepv import model
from sbepv.api import config, plots, state
from sbepv.api.artifacts import (
    _job_attempt_prefix,
    _output_url,
    _public_source_url,
    _workbook_download_name,
)
from sbepv.api.job_store import _check_job_cancelled, _get_job_record, _update_job
from sbepv.api.request_context import _iam_metadata
from sbepv.api.schemas import RunRequest
from sbepv.api.timewindows import _iso, _validation_window_metadata
from sbepv.ingest import bazefield as historian
from sbepv import reporting
from sbepv.reporting import sha256_file
from sbepv.worker import completion

logger = logging.getLogger(__name__)


def _run_job(
    job_id: str,
    req: RunRequest,
    *,
    source_path: str | Path | None = None,
    expected_source_hash: str | None = None,
    data_quality_context: dict[str, Any] | None = None,
    calibration_profile: dict[str, Any] | None = None,
    worker_id: str | None = None,
    lease_token: str | None = None,
) -> None:
    state.JOBS.setdefault(job_id, {"mode": "validation", "state": "running"})

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
        from_iso = _iso(req.from_date, req.from_time)
        to_iso = _iso(req.to_date, req.to_time)
        interval_seconds = (
            int(req.interval_value) * config.UNIT_SECONDS[req.interval_unit]
        )
        attempt_prefix = _job_attempt_prefix(job_id, lease_token)
        csv_path = (
            Path(source_path)
            if source_path and expected_source_hash
            else config.OUTPUT_DIR / f"{attempt_prefix}.csv"
        )
        base_path = config.OUTPUT_DIR / attempt_prefix

        if source_path and expected_source_hash:
            set_progress(5, "Verifying cached baseline source")
            source_hash = reporting.verify_source_sha256(csv_path, expected_source_hash)
            with csv_path.open("rb") as handle:
                n = max(sum(1 for _ in handle) - 1, 0)
        else:
            set_progress(5, "Pulling data from Bazefield")
            n = historian.run_historian(
                from_time=from_iso,
                to_time=to_iso,
                interval=str(interval_seconds),
                output_csv=str(csv_path),
            )
            _check_job_cancelled(
                job_id, worker_id=worker_id, lease_token=lease_token
            )
            source_hash = sha256_file(csv_path)
        _update_job(
            job_id,
            worker_id=worker_id,
            lease_token=lease_token,
            source_path=str(csv_path.resolve()),
            source_hash=source_hash,
        )
        _check_job_cancelled(
            job_id, worker_id=worker_id, lease_token=lease_token
        )
        input_plots = plots._render_input_data_plots(csv_path, base_path)
        existing_artifacts = (_get_job_record(job_id) or {}).get("artifacts") or {}
        _update_job(
            job_id,
            worker_id=worker_id,
            lease_token=lease_token,
            artifacts={**existing_artifacts, "input_plots": input_plots},
        )
        set_progress(20, f"Loaded {n} rows; running pvlib ModelChain")

        def progress_cb(frac: float, msg: str) -> None:
            set_progress(25 + int(frac * 65), msg)

        stats = model.run_model(
            input_csv=str(csv_path),
            output_base=str(base_path),
            progress_cb=progress_cb,
            backtrack=req.backtrack,
            solaredge_inverter_efficiency=req.solaredge_inverter_efficiency,
            solaredge_bos_efficiency=req.solaredge_bos_efficiency,
            solectria_inverter_efficiency=req.solectria_inverter_efficiency,
            solectria_bos_efficiency=req.solectria_bos_efficiency,
            iam_model=req.iam_model,
            iam_a_r=(req.iam_a_r if req.iam_model == "martin_ruiz" else None),
            curtailment_enabled=req.curtailment_enabled,
            curtailment_limit_kw=req.curtailment_limit_kw,
            data_quality_context=data_quality_context,
            expected_interval_seconds=interval_seconds,
            requested_start=from_iso,
            requested_end=to_iso,
            calibration_profile=calibration_profile,
            calibrate_model=req.calibrate_model,
        )
        set_progress(95, "Finalizing model artifacts")
        result = {
            "mode": "validation",
            "stats": stats,
            "ac_png": _output_url(Path(stats["ac_png"])),
            "energy_png": _output_url(Path(stats["energy_png"])),
            "uncalibrated_ac_png": (
                _output_url(Path(stats["uncalibrated_ac_png"]))
                if stats.get("uncalibrated_ac_png")
                else None
            ),
            "uncalibrated_energy_png": (
                _output_url(Path(stats["uncalibrated_energy_png"]))
                if stats.get("uncalibrated_energy_png")
                else None
            ),
            "excel": _output_url(Path(stats["excel"])),
            "excel_filename": _workbook_download_name(
                req,
                calibrated=stats.get("calibration_enabled") is True,
            ),
            "input_plots": state.JOBS[job_id].get("input_plots"),
            "source_csv": _public_source_url(csv_path),
            "data_quality": data_quality_context,
            "historian_preflight": stats.get("historian_preflight"),
            "warnings": list(stats.get("data_quality_warnings") or []),
            "calibration_factors": stats.get("calibration_factors"),
            "factor_driver_diagnostics": stats.get(
                "factor_driver_diagnostics"
            ),
            "window": {
                **_validation_window_metadata(from_iso, to_iso),
                "interval_seconds": interval_seconds,
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
                "calibrate_model": req.calibrate_model,
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
