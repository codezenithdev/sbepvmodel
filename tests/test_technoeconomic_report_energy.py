from copy import deepcopy
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
from contextlib import contextmanager
import shutil
import uuid
import unittest
from unittest.mock import patch

from sbepv import technoeconomic_report_energy as energy


@contextmanager
def temporary_directory():
    # mkdir's inherited ACL works in Windows restricted-token test sessions;
    # tempfile's mode-0700 directories can deny their own creating process.
    root = Path(__file__).resolve().parent
    path = root / (".tea-energy-" + uuid.uuid4().hex)
    path.mkdir()
    try:
        yield str(path)
    finally:
        resolved = path.resolve()
        if resolved.parent != root or not resolved.name.startswith(".tea-energy-"):
            raise RuntimeError("Refusing to remove a test directory outside tests/.")
        shutil.rmtree(resolved)


HEADERS = ["timestamp_local_naive", "timestamp_utc_naive", "dt_hours"] + [
    prefix + suffix for _, prefix in energy.SYSTEMS for suffix in (
        "_calibration_factor", "_calibrated_power_w", "_uncalibrated_power_w", "_measured_power_w")]


class Workbook:
    def __init__(self, rows):
        self.rows = rows

    def __getitem__(self, name):
        if name != "time_series":
            raise KeyError(name)
        return self

    def iter_rows(self, **kwargs):
        return iter([HEADERS, *self.rows])

    def close(self):
        pass


def fixture(root):
    factors = {season: {"solectria": .9, "solaredge": .8} for season in energy.SEASONS}
    factors["fall"] = {"solectria": .8, "solaredge": .7}
    records, rows, csv_rows = [], [], ["timestamp,solaredge_measured_power,solectria_measured_power"]
    for season, month, raw_power in zip(energy.SEASONS, (1, 4, 7, 9), (500, 1200, 1000, 1200)):
        local = datetime(2025, month, 15, 12)
        utc = local + timedelta(hours=7 if month == 1 else 6)
        row = [local, utc, 1]
        systems = {}
        for system, _ in energy.SYSTEMS:
            factor = factors[season][system]
            power = min(raw_power * factor, 1000)
            row += [factor, power, min(raw_power, 1000), power]
            systems[system] = {"factor": factor, "energy_balance_target_kwh": power / 1000,
                               "measured_kwh": power / 1000}
        rows.append(row)
        csv_rows.append(f"{utc.isoformat()},{row[10]},{row[6]}")
        records.append({"season": season, "row_count": 1, "first_timestamp": local.isoformat(),
                        "last_timestamp": local.isoformat(), "systems": systems})
    totals = {system: sum(row["systems"][system]["measured_kwh"] for row in records) for system, _ in energy.SYSTEMS}
    yearly = [{"year": 2025, "row_count": 4,
               "sol_predicted_kwh": totals["solectria"], "se_predicted_kwh": totals["solaredge"],
               "sol_physics_only_kwh": 3.5, "se_physics_only_kwh": 3.5}]
    request = {"curtailment_enabled": True, "curtailment_limit_kw": 1,
               "interval_unit": "hours", "interval_value": 1}
    calibration_path, annual_path, csv_path = (root / name for name in ("calibration.xlsx", "annual.xlsx", "reviewed.csv"))
    calibration_path.write_bytes(b"current calibration fixture identity")
    annual_path.write_bytes(b"current annual fixture identity")
    csv_path.write_text("\n".join(csv_rows), encoding="utf-8")
    def job(path):
        return {"request": request, "artifacts": {"model_workbook": {"path": str(path)}}, "result": {}}
    calibration, annual = job(calibration_path), job(annual_path)
    annual["result"]["annual_energy_by_year"] = yearly
    snapshot = {"source_annual_job": annual, "eligible_paired_energy_rows": yearly,
                "calibration_lineage": {
                    "origin_validation_job": calibration,
                    "origin_profile": {"fit_metadata": {"seasons": records}},
                    "resolved_profile": {"seasonal_factors": factors},
                    "origin_profile_sha256": "same", "resolved_profile_sha256": "same",
                    "result_application": {"seasonal_substitution": None},
                    "origin_validation_source": {"path": str(csv_path),
                                                 "sha256": hashlib.sha256(csv_path.read_bytes()).hexdigest()}}}
    return snapshot, {annual_path: deepcopy(rows), calibration_path: deepcopy(rows)}


class EnergyEvidenceTests(unittest.TestCase):
    def test_frozen_seasonal_facts_do_not_require_or_modify_artifacts(self):
        with temporary_directory() as directory:
            snapshot, _ = fixture(Path(directory))
            original = deepcopy(snapshot)
            result = energy.build_energy_evidence(snapshot)
            self.assertEqual(snapshot, original)
            self.assertEqual(result["artifact_diagnostic"]["status"], "unavailable")
            frozen = result["frozen"]
            self.assertEqual(len(frozen["seasonal_rows"]), 4)
            self.assertTrue(frozen["calibration_application"]["fitted_equals_applied"])
            self.assertAlmostEqual(frozen["measured_comparison"]["difference_kwh"], .31)
            json.dumps(result, allow_nan=False)

    def test_paired_median_is_not_difference_of_medians(self):
        result = energy._annual_comparison([
            {"year": 1, "sol_predicted_kwh": 100, "se_predicted_kwh": 95},
            {"year": 2, "sol_predicted_kwh": 200, "se_predicted_kwh": 195},
            {"year": 3, "sol_predicted_kwh": 210, "se_predicted_kwh": 180},
        ])
        self.assertEqual(result["difference_of_system_medians"]["difference_kwh"], 20)
        self.assertEqual(result["median_of_paired_differences_kwh"], 5)

    def _inspect(self, snapshot, tables, directory):
        with patch("openpyxl.load_workbook", side_effect=lambda path, **kwargs: Workbook(tables[path])):
            return energy.build_energy_evidence(snapshot, output_root=directory)

    def test_reconstruction_uses_current_hash_and_preserves_cap_in_fall_sensitivity(self):
        with temporary_directory() as directory:
            snapshot, tables = fixture(Path(directory))
            original = deepcopy(snapshot)
            result = self._inspect(snapshot, tables, directory)
            diagnostic = result["artifact_diagnostic"]
            self.assertEqual(diagnostic["status"], "reconciled_current_artifacts", diagnostic)
            self.assertEqual(snapshot, original)
            self.assertFalse(diagnostic["identity"]["annual"]["historical_bytes_verified"])
            self.assertEqual(diagnostic["reconciliation"]["paired_measurement_rows"], 4)
            sensitivity = diagnostic["fall_sensitivity"]
            self.assertEqual(sensitivity["status"], "available")
            # Fall SOL: .96 -> min(.96 * .9/.8, 1) = 1 kWh.
            # Fall SE: .84 -> .84 * .8/.7 = .96 kWh.
            self.assertAlmostEqual(sensitivity["change_in_mean_paired_difference_kwh"], -.08)
            self.assertAlmostEqual(sum(row["mean_annual"]["difference_kwh"] for row in diagnostic["seasonal_rows"]),
                                   diagnostic["annual_comparison"]["mean_paired_difference_kwh"])
            json.dumps(result, allow_nan=False)

    def test_altered_current_workbook_is_rejected_by_frozen_annual_totals(self):
        with temporary_directory() as directory:
            snapshot, tables = fixture(Path(directory))
            annual = tables[Path(directory) / "annual.xlsx"]
            annual[0][4] += 100
            annual[0][5] = annual[0][4] / annual[0][3]
            result = self._inspect(snapshot, tables, directory)
            self.assertEqual(result["artifact_diagnostic"]["status"], "unavailable")
            self.assertIn("annual energy differs", result["artifact_diagnostic"]["reason"])

    def test_changed_factors_and_unpaired_measurements_fail_closed(self):
        for changed in ("factor", "measurement"):
            with self.subTest(changed=changed), temporary_directory() as directory:
                snapshot, tables = fixture(Path(directory))
                if changed == "factor":
                    tables[Path(directory) / "annual.xlsx"][0][3] += .1
                else:
                    tables[Path(directory) / "calibration.xlsx"][0][6] += 10
                result = self._inspect(snapshot, tables, directory)
                self.assertEqual(result["artifact_diagnostic"]["status"], "unavailable")

    def test_recorded_workbook_byte_hash_is_enforced_when_present(self):
        with temporary_directory() as directory:
            snapshot, tables = fixture(Path(directory))
            snapshot["source_annual_job"]["artifacts"]["model_workbook"]["sha256"] = "0" * 64
            result = self._inspect(snapshot, tables, directory)
            self.assertEqual(result["artifact_diagnostic"]["status"], "unavailable")
            self.assertIn("historical SHA-256", result["artifact_diagnostic"]["reason"])

    def test_matching_historical_hashes_are_distinguished_from_new_current_hashes(self):
        for recorded in ((), ("annual",), ("calibration",), ("annual", "calibration")):
            with self.subTest(recorded=recorded), temporary_directory() as directory:
                snapshot, tables = fixture(Path(directory))
                jobs = {"annual": snapshot["source_annual_job"],
                        "calibration": snapshot["calibration_lineage"]["origin_validation_job"]}
                for name in recorded:
                    artifact = jobs[name]["artifacts"]["model_workbook"]
                    artifact["sha256"] = hashlib.sha256(Path(artifact["path"]).read_bytes()).hexdigest()
                original = deepcopy(snapshot)
                diagnostic = self._inspect(snapshot, tables, directory)["artifact_diagnostic"]
                self.assertEqual(diagnostic["status"], "reconciled_current_artifacts")
                self.assertEqual(snapshot, original)
                for name in jobs:
                    self.assertEqual(diagnostic["identity"][name]["historical_bytes_verified"], name in recorded)
                    self.assertEqual(diagnostic["identity"][name]["historical_byte_hash_recorded"], name in recorded)
                provenance = diagnostic["limitations"][0]
                if len(recorded) == 2:
                    self.assertIn("Both workbooks also match", provenance)
                    self.assertNotIn("not historical integrity proof", provenance)
                elif recorded:
                    self.assertIn(f"The {recorded[0]} workbook also matches", provenance)
                    missing = "calibration" if recorded[0] == "annual" else "annual"
                    self.assertIn(f"No historical byte hash was recorded for the {missing} workbook", provenance)
                else:
                    self.assertIn("Neither workbook has a recorded historical byte hash", provenance)

    def test_confined_path_and_changed_measurement_source_are_rejected(self):
        with temporary_directory() as directory, temporary_directory() as outside:
            snapshot, tables = fixture(Path(directory))
            snapshot["source_annual_job"]["artifacts"]["model_workbook"]["path"] = str(Path(outside) / "annual.xlsx")
            Path(outside, "annual.xlsx").write_bytes(b"outside")
            result = self._inspect(snapshot, tables, directory)
            self.assertIn("outside the output", result["artifact_diagnostic"]["reason"])
            snapshot, tables = fixture(Path(directory))
            Path(directory, "reviewed.csv").write_text("altered", encoding="utf-8")
            result = self._inspect(snapshot, tables, directory)
            self.assertIn("SHA-256", result["artifact_diagnostic"]["reason"])

    def test_decreasing_fall_factor_cannot_be_reconstructed_from_clipped_values(self):
        with temporary_directory() as directory:
            snapshot, tables = fixture(Path(directory))
            # Already clipped spring is irrelevant: the guard is explicitly
            # about whether the changed fall factor could expose lost power.
            factors = snapshot["calibration_lineage"]["resolved_profile"]["seasonal_factors"]
            factors["summer"]["solectria"] = .7
            for rows in tables.values():
                rows[2][3] = .7
                rows[2][4] = 700
                rows[2][6] = 700
            # Exercise the reconstruction's mathematical guard directly without
            # changing unrelated frozen measurement targets in this fixture.
            job = snapshot["source_annual_job"]
            with patch("openpyxl.load_workbook", side_effect=lambda path, **kwargs: Workbook(tables[path])):
                data = energy._read_workbook(job, output_root=directory, applied_factors=factors)
            self.assertFalse(data["sensitivity_supported"])


if __name__ == "__main__":
    unittest.main()
