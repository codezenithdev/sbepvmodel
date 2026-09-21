"""Read-only energy evidence for a report; never execute or alter a model job.

Frozen database evidence remains distinct from optional reconstruction of current
workbook bytes. Historical workbook byte hashes may be unavailable. Reconciliation
does not turn a newly captured hash into a historical integrity proof.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from datetime import datetime, timedelta
import csv
import hashlib
import math
from pathlib import Path
from statistics import mean, median
from zipfile import BadZipFile


SEASONS = ("winter", "spring", "summer", "fall")
SYSTEMS = (("solectria", "sol"), ("solaredge", "se"))
MONTH_SEASON = {month: season for season, months in zip(
    SEASONS, ((12, 1, 2), (3, 4, 5), (6, 7, 8), (9, 10, 11))
) for month in months}
ENERGY_TOLERANCE_KWH = 0.051  # Saved annual totals are rounded to 0.1 kWh.


def _number(value):
    if isinstance(value, bool):
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _comparison(sol, se):
    if sol is None or se is None:
        return None
    return {"solectria_kwh": sol, "solaredge_kwh": se,
            "difference_kwh": sol - se,
            "difference_pct_of_solaredge": 100 * (sol - se) / se if se else None}


def _annual_comparison(rows):
    values = [(row.get("year"), _number(row.get("sol_predicted_kwh")),
               _number(row.get("se_predicted_kwh"))) for row in rows]
    values = [(year, sol, se) for year, sol, se in values if sol is not None and se is not None]
    if not values:
        return None
    return {"year_count": len(values),
            "difference_of_system_medians": _comparison(
                median(sol for _, sol, _ in values), median(se for _, _, se in values)),
            "median_of_paired_differences_kwh": median(sol - se for _, sol, se in values),
            "mean_paired_difference_kwh": mean(sol - se for _, sol, se in values)}


def _frozen(snapshot):
    lineage = snapshot.get("calibration_lineage") or {}
    calibration = lineage.get("origin_validation_job") or {}
    result = calibration.get("result") or {}
    stats = result.get("stats") or {}
    origin = lineage.get("origin_profile") or {}
    resolved = lineage.get("resolved_profile") or {}
    fit = origin.get("fit_metadata") or result.get("calibration_factors") or stats.get("calibration_factors") or {}
    applied = resolved.get("seasonal_factors") or {}
    by_season = {record.get("season"): record for record in fit.get("seasons") or []}
    rows = []
    for season in SEASONS:
        record = by_season.get(season)
        if not record:
            continue
        systems = record.get("systems") or {}
        energies, factors = {}, {}
        for system, _ in SYSTEMS:
            evidence = systems.get(system) or {}
            energies[system] = _number(evidence.get("energy_balance_target_kwh", evidence.get("measured_kwh")))
            factors[system] = {"fitted": _number(evidence.get("factor")),
                               "applied": _number((applied.get(season) or {}).get(system))}
        rows.append({"season": season, "first_timestamp": record.get("first_timestamp"),
                     "last_timestamp": record.get("last_timestamp"), "row_count": record.get("row_count"),
                     "measured": _comparison(energies["solectria"], energies["solaredge"]),
                     "factors": factors})
    balance = (fit.get("energy_balance") or {}).get("systems") or {}
    totals = {system: _number((balance.get(system) or {}).get("measured_kwh")) for system, _ in SYSTEMS}
    for system, prefix in SYSTEMS:
        if totals[system] is None and rows and all(row["measured"] is not None for row in rows):
            totals[system] = math.fsum(row["measured"][system + "_kwh"] for row in rows)
        if totals[system] is None:
            totals[system] = _number(stats.get(prefix + "_measured_kwh"))
    application = lineage.get("result_application") or lineage.get("application") or {}
    matches = bool(rows) and all(
        factors["fitted"] is not None and factors["applied"] == factors["fitted"]
        for row in rows for factors in row["factors"].values()
    )
    annual = snapshot.get("source_annual_job") or {}
    installed = (snapshot.get("capacity_manifest") or {}).get("systems") or {}
    return {
        "seasonal_rows": rows,
        "measured_comparison": _comparison(totals["solectria"], totals["solaredge"]),
        "annual_comparison": _annual_comparison(snapshot.get("eligible_paired_energy_rows") or []),
        "calibration_application": {
            "fitted_equals_applied": matches,
            "seasonal_substitution": application.get("seasonal_substitution"),
            "origin_profile_sha256": lineage.get("origin_profile_sha256"),
            "resolved_profile_sha256": lineage.get("resolved_profile_sha256"),
        },
        "capacities": {system: _number((installed.get(system) or {}).get("installed_wdc")) for system, _ in SYSTEMS},
        "operating_limits": {name: {"enabled": (job.get("request") or {}).get("curtailment_enabled"),
                                     "limit_kw": (job.get("request") or {}).get("curtailment_limit_kw")}
                             for name, job in (("calibration", calibration), ("annual", annual))},
        "limitations": [
            "Calibration observations cover intervals used for calibration, not a complete measured year.",
            "Seasonal energy differences are descriptive; they do not independently identify physical causes.",
            "The difference of system medians and the median of paired differences are different statistics.",
        ],
    }


def _confined(path, output_root):
    root = Path(output_root).resolve(strict=True)
    candidate = Path(path).resolve(strict=True)
    if not candidate.is_relative_to(root) or not candidate.is_file():
        raise ValueError("Saved artifact path is outside the output directory or is not a file.")
    return candidate


def _digest(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def _interval_hours(request):
    multiplier = {"minutes": 1 / 60, "hours": 1}.get(request.get("interval_unit"))
    value = _number(request.get("interval_value"))
    if multiplier is None or value is None or value <= 0:
        raise ValueError("Saved interval duration is not supported by this diagnostic.")
    return value * multiplier


def _timestamp(value):
    if not isinstance(value, datetime) or value.tzinfo is not None:
        raise ValueError("Workbook timestamps must be recorded naive datetimes.")
    return value


def _verified_measurements(lineage, output_root):
    source = lineage.get("origin_validation_source") or {}
    expected = source.get("sha256")
    if not expected or not source.get("path"):
        raise ValueError("The saved reviewed-measurement source and byte hash are unavailable.")
    path = _confined(source["path"], output_root)
    if _digest(path) != expected:
        raise ValueError("Reviewed-measurement source bytes differ from the saved SHA-256.")
    values = {}
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            timestamp = datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00"))
            if timestamp.tzinfo is not None:
                from datetime import timezone
                timestamp = timestamp.astimezone(timezone.utc).replace(tzinfo=None)
            pair = tuple(_number(row[system + "_measured_power"]) for system, _ in SYSTEMS)
            if timestamp in values or any(value is None for value in pair):
                raise ValueError("Reviewed measurements contain duplicate or nonfinite paired observations.")
            values[timestamp] = pair
    if _digest(path) != expected:
        raise ValueError("Reviewed-measurement source changed while being read.")
    return values, expected


def _read_workbook(job, *, output_root, applied_factors, measurements=None, factor_basis="applied annual"):
    import openpyxl

    artifact = ((job.get("artifacts") or {}).get("model_workbook") or {})
    if not artifact.get("path"):
        raise ValueError("The saved model-workbook path is unavailable.")
    path = _confined(artifact["path"], output_root)
    if path.suffix.lower() != ".xlsx":
        raise ValueError("The saved model-workbook path does not identify an XLSX file.")
    before = _digest(path)
    if artifact.get("sha256") and artifact["sha256"] != before:
        raise ValueError("Workbook bytes differ from the recorded historical SHA-256.")
    request = job.get("request") or {}
    cap_kw = _number(request.get("curtailment_limit_kw"))
    if request.get("curtailment_enabled") is not True or cap_kw is None or not 0 < cap_kw <= 250:
        raise ValueError("This reconstruction requires a recorded common operating cap no greater than 250 kW.")
    cap_w = cap_kw * 1000
    interval_hours = _interval_hours(request)
    seasonal = defaultdict(lambda: defaultdict(float))
    yearly = defaultdict(lambda: defaultdict(float))
    scenario = defaultdict(lambda: defaultdict(float))
    seasonal_windows = {}
    seen, previous = set(), None
    sensitivity_supported = all(
        _number((applied_factors.get(season) or {}).get(system)) is not None
        for season in SEASONS for system, _ in SYSTEMS
    ) and all(0 < applied_factors["fall"][system] <= applied_factors["summer"][system]
              for system, _ in SYSTEMS)
    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        iterator = workbook["time_series"].iter_rows(values_only=True)
        headers = next(iterator)
        positions = {name: index for index, name in enumerate(headers)}
        required = ["timestamp_local_naive", "timestamp_utc_naive", "dt_hours"]
        required += [prefix + suffix for _, prefix in SYSTEMS for suffix in (
            "_calibration_factor", "_calibrated_power_w", "_uncalibrated_power_w", "_measured_power_w")]
        if any(name not in positions for name in required):
            raise ValueError("The saved workbook lacks interval powers, factors, timestamps, or durations.")
        for row in iterator:
            utc = _timestamp(row[positions["timestamp_utc_naive"]])
            local = _timestamp(row[positions["timestamp_local_naive"]])
            if utc in seen or (previous is not None and utc <= previous):
                raise ValueError("Workbook timestamps are duplicated or out of order.")
            # Only the site's standard/daylight offsets are valid; season uses
            # the stored local clock, while Annual year uses the fixed-MST clock.
            if (utc - local).total_seconds() not in (6 * 3600, 7 * 3600):
                raise ValueError("Workbook local/UTC timestamps are incompatible with the saved site.")
            previous = utc
            seen.add(utc)
            season = MONTH_SEASON[local.month]
            seasonal_windows.setdefault(season, {"first_local": local.isoformat()})
            seasonal_windows[season]["last_local"] = local.isoformat()
            year = (utc - timedelta(hours=7)).year
            dt = _number(row[positions["dt_hours"]])
            if dt is None or not 0 < dt <= interval_hours + 1e-10:
                raise ValueError("Workbook interval duration is incompatible with the saved request.")
            seasonal[season]["rows"] += 1
            yearly[year]["rows"] += 1
            for system_index, (system, prefix) in enumerate(SYSTEMS):
                factor = _number(row[positions[prefix + "_calibration_factor"]])
                expected_factor = _number((applied_factors.get(season) or {}).get(system))
                if factor is None or expected_factor is None or not math.isclose(factor, expected_factor, abs_tol=1e-12, rel_tol=1e-12):
                    raise ValueError(f"Workbook factors differ from the saved {factor_basis} calibration profile.")
                powers = {kind: _number(row[positions[prefix + "_" + kind + "_power_w"]])
                          for kind in ("measured", "uncalibrated", "calibrated")}
                if any(value is None for value in powers.values()):
                    raise ValueError("Workbook contains a missing or nonfinite system power.")
                for kind in ("uncalibrated", "calibrated"):
                    power = powers[kind]
                    if power < -1e-7 or power > cap_w + 1e-7:
                        raise ValueError("Workbook model powers violate the saved operating cap.")
                    seasonal[season][system + "_" + kind + "_kwh"] += power * dt / 1000
                    yearly[year][system + "_" + kind + "_kwh"] += power * dt / 1000
                    seasonal[season][system + "_" + kind + "_at_cap_rows"] += int(abs(power - cap_w) < 1e-7)
                # When the calibrated value is below its cap, the upstream power
                # is recoverable. Reapply the cap to compare the saved prefit value.
                if factor > 0 and powers["calibrated"] < cap_w - 1e-7:
                    reconstructed = min(powers["calibrated"] / factor, cap_w)
                    if not math.isclose(reconstructed, powers["uncalibrated"], abs_tol=1e-6, rel_tol=1e-9):
                        raise ValueError("Workbook calibrated and prefit powers do not reconcile through the saved factor/cap.")
                if powers["uncalibrated"] < cap_w - 1e-7:
                    expected_power = min(powers["uncalibrated"] * factor, cap_w)
                    if not math.isclose(expected_power, powers["calibrated"], abs_tol=1e-6, rel_tol=1e-9):
                        raise ValueError("Workbook prefit and calibrated powers do not reconcile through the saved factor/cap.")
                if measurements is not None:
                    expected = measurements.get(utc)
                    if expected is None or not math.isclose(powers["measured"], expected[system_index], abs_tol=1e-6, rel_tol=1e-10):
                        raise ValueError("Workbook measurements differ from the SHA-verified reviewed source.")
                seasonal[season][system + "_measured_kwh"] += powers["measured"] * dt / 1000
                value = powers["calibrated"]
                if sensitivity_supported and season == "fall":
                    value = min(value * applied_factors["summer"][system] / factor, cap_w)
                scenario[year][system + "_calibrated_kwh"] += value * dt / 1000
    finally:
        workbook.close()
    if measurements is not None and set(measurements) != seen:
        raise ValueError("Workbook and reviewed source use different measurement intervals used for calibration.")
    if before != _digest(path):
        raise ValueError("Workbook bytes changed while the diagnostic was being read.")
    return {"identity": {"filename": path.name, "sha256": before,
                         "byte_count": path.stat().st_size, "historical_byte_hash_recorded": bool(artifact.get("sha256")),
                         "historical_bytes_verified": bool(artifact.get("sha256") == before)},
            "seasonal": seasonal, "yearly": yearly, "scenario": scenario,
            "seasonal_windows": seasonal_windows,
            "sensitivity_supported": sensitivity_supported, "row_count": len(seen)}


def _reconstruct(snapshot, frozen, output_root):
    lineage = snapshot["calibration_lineage"]
    factors = lineage["resolved_profile"]["seasonal_factors"]
    # The calibration workbook belongs to the original fit. A later Annual
    # substitution changes only its applied profile, not those fitted intervals.
    fitted_factors = {row["season"]: {system: row["factors"][system]["fitted"]
                                     for system, _ in SYSTEMS}
                      for row in frozen["seasonal_rows"]}
    measurements, reviewed_sha = _verified_measurements(lineage, output_root)
    calibration = _read_workbook(lineage["origin_validation_job"], output_root=output_root,
                                 applied_factors=fitted_factors, measurements=measurements,
                                 factor_basis="original fitted")
    for record in frozen["seasonal_rows"]:
        actual = calibration["seasonal"].get(record["season"])
        if not actual or actual["rows"] != record["row_count"] or record["measured"] is None:
            raise ValueError("Workbook seasonal rows used for calibration do not match saved calibration evidence.")
        for bound, key in (("first_timestamp", "first_local"), ("last_timestamp", "last_local")):
            if record.get(bound) is not None:
                expected = datetime.fromisoformat(record[bound]).replace(tzinfo=None).isoformat()
                if calibration["seasonal_windows"][record["season"]][key] != expected:
                    raise ValueError("Workbook observation window differs from the saved calibration evidence.")
        for system, _ in SYSTEMS:
            for kind in ("measured", "calibrated"):
                if abs(actual[system + "_" + kind + "_kwh"] - record["measured"][system + "_kwh"]) > 0.0011:
                    raise ValueError("Workbook seasonal energies do not match saved calibration evidence.")
    annual_job = snapshot["source_annual_job"]
    annual = _read_workbook(annual_job, output_root=output_root, applied_factors=factors)
    recorded_rows = annual_job["result"]["annual_energy_by_year"]
    recorded_years = {int(row["year"]) for row in recorded_rows}
    if recorded_years != set(annual["yearly"]) or len(recorded_years) != len(recorded_rows):
        raise ValueError("Workbook weather years differ from saved annual evidence.")
    max_error = 0.0
    for row in recorded_rows:
        actual = annual["yearly"][int(row["year"])]
        if actual["rows"] != row.get("row_count"):
            raise ValueError("Workbook Annual row counts differ from the saved result.")
        for system, prefix in SYSTEMS:
            expected = _number(row.get(prefix + "_predicted_kwh"))
            if expected is None:
                raise ValueError("Saved annual energy required for reconciliation is missing.")
            error = abs(actual[system + "_calibrated_kwh"] - expected)
            max_error = max(max_error, error)
            if error > ENERGY_TOLERANCE_KWH:
                raise ValueError("Workbook annual energy differs from the saved result beyond its rounding precision.")
            physics = _number(row.get(prefix + "_physics_only_kwh"))
            if physics is not None and abs(actual[system + "_uncalibrated_kwh"] - physics) > ENERGY_TOLERANCE_KWH:
                raise ValueError("Workbook prefit annual energy differs from the saved result.")
    eligible = {int(row["year"]) for row in snapshot["eligible_paired_energy_rows"]}
    if eligible != recorded_years:
        raise ValueError("Seasonal reconstruction currently requires every saved Annual year to be eligible.")
    n = len(eligible)
    seasonal_rows = []
    for season in SEASONS:
        values = annual["seasonal"][season]
        seasonal_rows.append({"season": season,
                              "mean_annual": _comparison(values["solectria_calibrated_kwh"] / n,
                                                          values["solaredge_calibrated_kwh"] / n),
                              "mean_prefit_annual": _comparison(values["solectria_uncalibrated_kwh"] / n,
                                                                 values["solaredge_uncalibrated_kwh"] / n),
                              "measured": next((row["measured"] for row in frozen["seasonal_rows"] if row["season"] == season), None),
                              "mean_at_cap_rows": {system: values[system + "_calibrated_at_cap_rows"] / n for system, _ in SYSTEMS}})
    def rows_for(values):
        return [{"year": year, "sol_predicted_kwh": row["solectria_calibrated_kwh"],
                 "se_predicted_kwh": row["solaredge_calibrated_kwh"]} for year, row in values.items()]
    baseline = _annual_comparison(rows_for(annual["yearly"]))
    reductions = [system for system, _ in SYSTEMS if factors["summer"][system] < factors["fall"][system]]
    capped_fall_rows = {system: int(annual["seasonal"]["fall"][system + "_calibrated_at_cap_rows"])
                       for system in reductions}
    reduction_names = ", ".join("SolarEdge" if system == "solaredge" else "Solectria" for system in reductions)
    sensitivity = {"status": "unavailable",
                   "reason": f"Summer-for-fall would reduce the applied factor for {reduction_names or 'at least one system'}. The saved powers are already capped, so an exact decrease requires unavailable pre-cap power",
                   "systems_requiring_lower_factor": reductions,
                   "affected_system_capped_fall_rows": capped_fall_rows}
    if annual["sensitivity_supported"]:
        scenario = _annual_comparison(rows_for(annual["scenario"]))
        sensitivity = {
            "status": "available", "id": "fall_uses_summer_factors_v1",
            "label": "Diagnostic only: each system's fall factor replaced by its own summer factor",
            "baseline": baseline, "scenario": scenario,
            "change_in_mean_paired_difference_kwh": scenario["mean_paired_difference_kwh"] - baseline["mean_paired_difference_kwh"],
            "changed_factors": {system: {"baseline_fall": factors["fall"][system],
                                          "diagnostic_fall": factors["summer"][system]} for system, _ in SYSTEMS},
            "method": "For each fall interval, scale saved calibrated power by summer/fall and reapply the unchanged cap. Both ratios are at least one, so min(r*min(P,C),C)=min(r*P,C), including already clipped intervals. All other intervals and inputs remain fixed.",
            "interpretation": "A joint sensitivity to the recorded fall calibration, not a corrected baseline, a new model run, a validated replacement factor, or an additive attribution of independent causes. Factor/cap interactions are included. LCOE is not recalculated.",
        }
    verified_workbooks = [name for name, workbook in (("calibration", calibration), ("annual", annual))
                          if workbook["identity"]["historical_bytes_verified"]]
    if len(verified_workbooks) == 2:
        historical_provenance = "Both workbooks also match their saved historical byte hashes."
    elif verified_workbooks:
        verified_name = verified_workbooks[0]
        missing_name = "annual" if verified_name == "calibration" else "calibration"
        historical_provenance = (f"The {verified_name} workbook also matches its saved historical byte hash. "
                                 f"No historical byte hash was recorded for the {missing_name} workbook; its current hash is not historical integrity proof.")
    else:
        historical_provenance = "Neither workbook has a recorded historical byte hash; their current hashes are not historical integrity proof."
    fall_record = next((row for row in frozen["seasonal_rows"] if row["season"] == "fall"), {})
    first, last = fall_record.get("first_timestamp"), fall_record.get("last_timestamp")
    fall_coverage = (f"Recorded fall observations span {first} to {last}. " if first and last else
                     "The fall observation window is not recorded. ")
    return {"status": "reconciled_current_artifacts",
            "identity": {"annual": annual["identity"], "calibration": calibration["identity"],
                         "diagnostic_method": "saved_interval_energy_reconstruction_v2",
                         "source_annual_job_id": snapshot.get("source_annual_job_id"),
                         "source_calibration_job_id": lineage["origin_validation_job"].get("id"),
                         "reviewed_measurement_sha256": reviewed_sha},
            "seasonal_rows": seasonal_rows, "annual_comparison": baseline, "fall_sensitivity": sensitivity,
            "profile_validation": {"calibration_workbook": "original_fitted",
                                   "annual_workbook": "annual_applied",
                                   "fitted_equals_applied": frozen["calibration_application"]["fitted_equals_applied"],
                                   "seasonal_substitution": frozen["calibration_application"]["seasonal_substitution"]},
            "reconciliation": {"annual_rows": annual["row_count"], "paired_measurement_rows": calibration["row_count"],
                               "maximum_annual_rounding_difference_kwh": max_error,
                               "annual_tolerance_kwh": ENERGY_TOLERANCE_KWH,
                               "matching_measurement_intervals": True, "matching_frozen_factors": True,
                               "matching_saved_operating_caps": True},
            "limitations": [
                "Current workbook bytes are checksummed and reconciled to saved yearly totals, factors, caps, and SHA-verified measurements. " + historical_provenance,
                "Seasonal means add to the mean annual difference, not the difference of system medians.",
                "The stored prefit powers are already capped, so exact losses from removing the operating caps cannot be recovered from these exports.",
                fall_coverage + "The sensitivity does not establish that summer factors represent fall conditions or validate extrapolation beyond the observed window.",
            ]}


def build_energy_evidence(snapshot: Mapping, *, output_root: Path | None = None) -> dict:
    """Return frozen facts and, when possible, a separately identified diagnostic.

    ``output_root`` is explicit so importing this module cannot initialize API
    settings or a production database. Optional artifact failures fail closed to
    an explanatory unavailable result, leaving frozen saved results untouched.
    """
    frozen = _frozen(snapshot)
    diagnostic = {"status": "unavailable", "reason": "No output directory was supplied for current-artifact reconstruction."}
    if output_root is not None:
        try:
            diagnostic = _reconstruct(snapshot, frozen, output_root)
        except (KeyError, IndexError, TypeError, ValueError, OSError, StopIteration, BadZipFile, ImportError) as exc:
            diagnostic = {"status": "unavailable", "reason": str(exc) or type(exc).__name__}
    return {"schema_version": 1, "difference_direction": "solectria_minus_solaredge",
            "frozen": frozen, "artifact_diagnostic": diagnostic}
