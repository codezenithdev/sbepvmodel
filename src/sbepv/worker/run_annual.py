"""Executes one annual simulation job: MIDC download -> model -> artifacts."""

from __future__ import annotations

import logging
import secrets
from copy import deepcopy
from datetime import date
from pathlib import Path
from typing import Any

from sbepv import model
from sbepv.api import config, state, technoeconomic as technoeconomic_api
from sbepv.api.artifacts import (
    _job_attempt_prefix,
    _output_url,
    _public_source_url,
    _workbook_download_name,
)
from sbepv.api.job_store import _check_job_cancelled, _get_job_record, _update_job
from sbepv.api.request_context import _iam_metadata
from sbepv.api.schemas import AnnualRunRequest
from sbepv.api.validation import _annual_interval_seconds, _annual_periods
from sbepv.ingest import midc
from sbepv import reporting
from sbepv.reporting import sha256_file
from sbepv.worker import completion

logger = logging.getLogger(__name__)


def _periods_with_source_coverage(
    periods: list[dict[str, object]],
    period_quality: list[dict[str, Any]],
    interval_seconds: int,
) -> tuple[list[dict[str, object]], list[dict[str, Any]]]:
    """Attach post-download source coverage to requested annual periods.

    Request validation can establish calendar boundaries, but only the downloaded
    MIDC source can establish whether every interval inside those boundaries had
    usable measurements.  Unknown source coverage is deliberately treated as
    incomplete so a legacy cached artifact cannot enter the complete-year CDF by
    inference alone.
    """

    intervals_per_day = 86_400 // int(interval_seconds)
    quality_by_year = {
        int(row["year"]): deepcopy(row)
        for row in period_quality
        if isinstance(row, dict) and row.get("year") is not None
    }
    enriched_periods: list[dict[str, object]] = []
    enriched_quality: list[dict[str, Any]] = []

    for original in periods:
        period = deepcopy(original)
        year = int(period["year"])
        period_start = date.fromisoformat(str(period["period_start"]))
        period_end = date.fromisoformat(str(period["period_end"]))
        source_expected = ((period_end - period_start).days + 1) * intervals_per_day
        annual_expected = (
            (date(year, 12, 31) - date(year, 1, 1)).days + 1
        ) * intervals_per_day
        quality = quality_by_year.get(year, {})

        try:
            interval_rows = int(quality["interval_rows"])
            unavailable = int(quality["unavailable_interval_count"])
        except (KeyError, TypeError, ValueError, OverflowError):
            source_covered: int | None = None
            source_coverage_pct: float | None = None
            annual_coverage_pct: float | None = None
            source_complete = False
            quality["unavailable_interval_count"] = None
        else:
            # Normally the downloader materializes every requested interval and
            # unavailable rows are all-null.  A reconstructed legacy audit may
            # instead count omitted rows as unavailable, so use the larger of the
            # explicit count and the row deficit without double-counting either.
            effective_unavailable = max(
                max(0, unavailable),
                max(0, source_expected - interval_rows),
            )
            source_covered = source_expected - min(
                source_expected, effective_unavailable
            )
            quality["unavailable_interval_count"] = (
                source_expected - source_covered
            )
            source_coverage_pct = round(
                source_covered / source_expected * 100.0, 3
            )
            annual_coverage_pct = round(
                source_covered / annual_expected * 100.0, 3
            )
            source_complete = source_covered == source_expected

        date_complete = period.get("complete_calendar_year") is True
        period.update(
            {
                "source_expected_interval_count": source_expected,
                "source_covered_interval_count": source_covered,
                "source_coverage_pct": source_coverage_pct,
                "annual_expected_interval_count": annual_expected,
                "annual_coverage_pct": annual_coverage_pct,
                "source_complete": source_complete,
                "cdf_eligible": bool(date_complete and source_complete),
            }
        )
        if date_complete and not source_complete:
            period["coverage_status"] = "incomplete_source"

        enriched_periods.append(period)
        enriched_quality.append({**quality, **deepcopy(period)})

    return enriched_periods, enriched_quality


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
        periods = _annual_periods(req, allow_resolved_partial=True)
        interval_seconds = _annual_interval_seconds(req)
        interval_minutes = interval_seconds // 60
        interval_hours = (
            interval_seconds // 3_600
            if interval_seconds % 3_600 == 0
            else interval_seconds / 3_600
        )
        attempt_prefix = _job_attempt_prefix(job_id, lease_token)
        csv_path = (
            Path(source_path)
            if source_path and expected_source_hash
            else config.OUTPUT_DIR / f"{attempt_prefix}_midc_hourly.csv"
        )
        base_path = config.OUTPUT_DIR / attempt_prefix
        source_warnings: list[str] = []
        source_quality: dict[str, Any]
        existing_record = _get_job_record(job_id) or {}
        existing_provenance = dict(existing_record.get("provenance") or {})

        def period_row_counts(frame: Any) -> list[dict[str, Any]]:
            import pandas as pd

            parsed_dates = pd.to_datetime(
                frame[midc.DATE_COLUMN], format="%m/%d/%Y", errors="coerce"
            ).dt.date
            measurement_columns = list(midc.MEASUREMENT_COLUMNS.values())
            has_measurements = all(column in frame for column in measurement_columns)
            rows: list[dict[str, Any]] = []
            for period in periods:
                period_start = date.fromisoformat(str(period["period_start"]))
                period_end = date.fromisoformat(str(period["period_end"]))
                period_mask = (parsed_dates >= period_start) & (
                    parsed_dates <= period_end
                )
                interval_rows = int(period_mask.sum())
                source_expected = (
                    (period_end - period_start).days + 1
                ) * (86_400 // interval_seconds)
                if has_measurements:
                    covered_rows = int(
                        frame.loc[period_mask, measurement_columns]
                        .notna()
                        .any(axis=1)
                        .sum()
                    )
                    unavailable_interval_count: int | None = max(
                        0, source_expected - min(source_expected, covered_rows)
                    )
                else:
                    unavailable_interval_count = None
                rows.append(
                    {
                        **deepcopy(period),
                        "interval_rows": interval_rows,
                        "unavailable_interval_count": unavailable_interval_count,
                    }
                )
            return rows

        if source_path and expected_source_hash:
            set_progress(5, "Verifying cached annual source")
            source_hash = reporting.verify_source_sha256(csv_path, expected_source_hash)
            import pandas as pd

            cached_frame = pd.read_csv(csv_path)
            interval_rows = int(len(cached_frame))
            cached_period_quality = period_row_counts(cached_frame)
            stored_audit = existing_provenance.get("annual_source_audit")
            audit_matches = (
                isinstance(stored_audit, dict)
                and isinstance(stored_audit.get("source_sha256"), str)
                and secrets.compare_digest(
                    str(stored_audit["source_sha256"]).strip().lower(),
                    str(source_hash).strip().lower(),
                )
                and stored_audit.get("interval_seconds") == interval_seconds
                and isinstance(stored_audit.get("source_quality"), dict)
                and isinstance(stored_audit.get("warnings"), list)
            )
            if audit_matches:
                source_quality = deepcopy(stored_audit["source_quality"])
                stored_periods = {
                    int(row["year"]): deepcopy(row)
                    for row in source_quality.get("periods") or []
                    if isinstance(row, dict) and row.get("year") is not None
                }
                source_quality["periods"] = [
                    {
                        **stored_periods.get(int(row["year"]), {}),
                        **row,
                    }
                    for row in cached_period_quality
                ]
                source_quality["reused_verified_source"] = True
                source_warnings = [str(item) for item in stored_audit["warnings"]]
            else:
                source_quality = {
                    "reference_url": midc.REFERENCE_URL,
                    "raw_rows": None,
                    "hourly_rows": interval_rows if interval_seconds == 3_600 else None,
                    "interval_rows": interval_rows,
                    "interval_seconds": interval_seconds,
                    "data_request_count": None,
                    "missing_value_count": None,
                    "affected_interval_count": None,
                    "partial_interval_count": None,
                    "periods": cached_period_quality,
                    "reused_verified_source": True,
                }
        else:
            import pandas as pd

            interval_frames: list[Any] = []
            raw_rows = 0
            data_request_count = 0
            missing_value_count = 0
            affected_interval_count = 0
            partial_interval_count = 0
            unavailable_interval_count = 0
            period_quality: list[dict[str, Any]] = []
            period_count = len(periods)
            set_progress(
                5,
                f"Downloading MIDC data for {period_count} selected "
                f"year{'s' if period_count != 1 else ''}",
            )
            for period_index, period in enumerate(periods, start=1):
                period_start = date.fromisoformat(str(period["period_start"]))
                period_end = date.fromisoformat(str(period["period_end"]))
                period_year = int(period["year"])

                def download_progress(
                    frac: float,
                    msg: str,
                    *,
                    index: int = period_index,
                    year: int = period_year,
                ) -> None:
                    overall = ((index - 1) + max(0.0, min(1.0, frac))) / period_count
                    set_progress(5 + int(overall * 20), f"{year}: {msg}")

                source = midc.fetch_hourly_data(
                    period_start,
                    period_end,
                    interval_seconds=interval_seconds,
                    progress_cb=download_progress,
                )
                interval_frames.append(source.interval_data)
                raw_rows += int(source.raw_rows)
                data_request_count += int(source.data_request_count)
                missing_value_count += int(source.missing_value_count)
                affected_interval_count += int(source.affected_interval_count)
                partial_interval_count += int(source.partial_interval_count)
                unavailable_interval_count += int(source.unavailable_interval_count)
                source_warnings.extend(
                    f"{period_year}: {warning}" for warning in source.warnings
                )
                period_quality.append(
                    {
                        **deepcopy(period),
                        "raw_rows": int(source.raw_rows),
                        "interval_rows": int(len(source.interval_data)),
                        "data_request_count": int(source.data_request_count),
                        "missing_value_count": int(source.missing_value_count),
                        "affected_interval_count": int(source.affected_interval_count),
                        "partial_interval_count": int(source.partial_interval_count),
                        "unavailable_interval_count": int(
                            source.unavailable_interval_count
                        ),
                    }
                )

            interval_data = pd.concat(interval_frames, ignore_index=True)
            sort_dates = pd.to_datetime(
                interval_data[midc.DATE_COLUMN],
                format="%m/%d/%Y",
                errors="coerce",
            )
            interval_data = (
                interval_data.assign(_sort_date=sort_dates)
                .sort_values(
                    [
                        "_sort_date",
                        midc.HOUR_COLUMN,
                        *(
                            [midc.MINUTE_COLUMN]
                            if midc.MINUTE_COLUMN in interval_data
                            else []
                        ),
                    ],
                    kind="stable",
                )
                .drop(columns="_sort_date")
                .reset_index(drop=True)
            )
            _check_job_cancelled(
                job_id, worker_id=worker_id, lease_token=lease_token
            )
            set_progress(27, "Saving exact MIDC interval source")
            midc.write_csv_atomically(interval_data, csv_path)
            source_hash = sha256_file(csv_path)
            source_quality = {
                "reference_url": midc.REFERENCE_URL,
                "raw_rows": raw_rows,
                "hourly_rows": (
                    int(len(interval_data)) if interval_seconds == 3_600 else None
                ),
                "interval_rows": int(len(interval_data)),
                "interval_seconds": interval_seconds,
                "data_request_count": data_request_count,
                "missing_value_count": missing_value_count,
                "affected_interval_count": affected_interval_count,
                "partial_interval_count": partial_interval_count,
                "unavailable_interval_count": unavailable_interval_count,
                "periods": period_quality,
                "reused_verified_source": False,
            }

        periods, enriched_period_quality = _periods_with_source_coverage(
            periods,
            list(source_quality.get("periods") or []),
            interval_seconds,
        )
        source_quality["periods"] = enriched_period_quality
        unavailable_counts = [
            row.get("unavailable_interval_count")
            for row in enriched_period_quality
        ]
        source_quality["unavailable_interval_count"] = (
            sum(int(value) for value in unavailable_counts)
            if all(value is not None for value in unavailable_counts)
            else None
        )
        existing_provenance["annual_source_audit"] = {
            "schema_version": 2,
            "source_sha256": source_hash,
            "interval_seconds": interval_seconds,
            "source_quality": deepcopy(source_quality),
            "warnings": deepcopy(source_warnings),
        }
        source_artifact = technoeconomic_api.harden_annual_source_artifact(
            csv_path,
            source_hash,
            annual_job_id=job_id,
        )
        existing_provenance["annual_source_artifact"] = deepcopy(source_artifact)
        capacity_manifest = model.capacity_manifest()
        existing_provenance["capacity_manifest"] = deepcopy(capacity_manifest)
        _update_job(
            job_id,
            worker_id=worker_id,
            lease_token=lease_token,
            source_path=str(csv_path.resolve()),
            source_hash=source_hash,
            provenance=existing_provenance,
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
            annual_periods=periods,
        )
        warnings = list(
            dict.fromkeys([*source_warnings, *stats.get("data_quality_warnings", [])])
        )
        stats["data_quality_warnings"] = warnings
        stats["capacity_manifest"] = deepcopy(capacity_manifest)
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
            "source_csv": _public_source_url(csv_path),
            "warnings": warnings,
            "source_quality": source_quality,
            "annual_source_artifact": deepcopy(source_artifact),
            "annual_energy_by_year": deepcopy(
                stats.get("annual_energy_by_year") or []
            ),
            "annual_energy_cdf": deepcopy(stats.get("annual_energy_cdf") or {}),
            "capacity_manifest": deepcopy(capacity_manifest),
            "calibration_application": calibration_application,
            "window": {
                "from": req.from_date,
                "to": req.to_date,
                "years": deepcopy(req.years),
                "periods": deepcopy(periods),
                "interval_value": req.interval_value,
                "interval_unit": req.interval_unit,
                "interval_seconds": interval_seconds,
                "interval_minutes": interval_minutes,
                "interval_hours": interval_hours,
                "timezone": "MST (UTC-7)",
                "interval_convention": "right-closed, right-labeled",
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
