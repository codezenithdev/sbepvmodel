import unittest
from copy import copy
from types import SimpleNamespace
from unittest import mock

import numpy as np
import pvlib as pvl
import pvmismatch as pvm

from sbepv import model


def _cec_reference_pmp_w(
    *, irradiance_w_m2: float, temperature_c: float
) -> float:
    """Return the CEC single-diode Pmp used to guard production curve shape."""

    parameters = pvl.pvsystem.calcparams_cec(
        float(irradiance_w_m2),
        float(temperature_c),
        alpha_sc=float(model.MODULE_PARAMETERS["alpha_sc"]),
        a_ref=float(model.MODULE_PARAMETERS["a_ref"]),
        I_L_ref=float(model.MODULE_PARAMETERS["I_L_ref"]),
        I_o_ref=float(model.MODULE_PARAMETERS["I_o_ref"]),
        R_sh_ref=float(model.MODULE_PARAMETERS["R_sh_ref"]),
        R_s=float(model.MODULE_PARAMETERS["R_s"]),
        Adjust=float(model.MODULE_PARAMETERS["Adjust"]),
    )
    return float(pvl.pvsystem.singlediode(*parameters)["p_mp"])


class ProductionSolectriaModuleTests(unittest.TestCase):
    def test_production_module_matches_nameplate_and_temperature_response(
        self,
    ) -> None:
        validation = model.validate_solectria_module(
            model.build_pvmismatch_module()
        )

        for name, target in {
            "pmp_w": 579.92,
            "vmp_v": 44.0,
            "imp_a": 13.18,
            "voc_v": 52.5,
            "isc_a": 13.93,
        }.items():
            with self.subTest(name=name):
                self.assertLessEqual(
                    abs(validation["stc"][name] / target - 1.0),
                    model.SOLECTRIA_DATASHEET_RELATIVE_TOLERANCE,
                )
        self.assertGreater(validation["pmp_0c_w"], validation["stc"]["pmp_w"])
        self.assertGreater(validation["stc"]["pmp_w"], validation["pmp_65c_w"])
        self.assertAlmostEqual(
            validation["pmp_temperature_coefficient_pct_per_c"],
            -0.302,
            delta=0.02,
        )
        self.assertAlmostEqual(
            validation["voc_temperature_coefficient_v_per_c"],
            -0.12548,
            delta=0.01,
        )

    def test_runtime_builder_uses_frozen_coefficients_without_solver(self) -> None:
        with mock.patch.object(
            model.gen_coeffs,
            "gen_two_diode",
            side_effect=AssertionError("runtime must not solve"),
        ):
            module = model.build_pvmismatch_module()

        cell = module.pvcells[0]
        np.testing.assert_array_equal(
            [cell.Isat1_T0, cell.Isat2_T0, cell.Rs, cell.Rsh],
            model.SOLECTRIA_TWO_DIODE_COEFFICIENTS,
        )
        self.assertEqual(float(cell.alpha_Isc), 0.00033)
        self.assertEqual(float(cell.Eg), 1.16)
        self.assertAlmostEqual(
            module.cellArea,
            2.56 * 10_000.0 / 72.0,
            places=12,
        )

    def test_seeded_offline_fit_matches_frozen_coefficients(self) -> None:
        np.testing.assert_allclose(
            model.fit_solectria_two_diode_coefficients(),
            model.SOLECTRIA_TWO_DIODE_COEFFICIENTS,
            rtol=1e-7,
            atol=1e-12,
        )

    def test_offline_fit_rejects_solver_failure_and_large_residual(self) -> None:
        failure = SimpleNamespace(
            success=False,
            status=5,
            message="not converged",
            fun=np.zeros(4),
        )
        with mock.patch.object(
            model.gen_coeffs,
            "gen_two_diode",
            return_value=(model.SOLECTRIA_TWO_DIODE_COEFFICIENTS, failure),
        ):
            with self.assertRaisesRegex(RuntimeError, r"fit failed: status=5"):
                model.fit_solectria_two_diode_coefficients()

        large_residual = SimpleNamespace(
            success=True,
            status=1,
            message="converged",
            fun=np.array([1e-2, 0.0, 0.0, 0.0]),
        )
        with mock.patch.object(
            model.gen_coeffs,
            "gen_two_diode",
            return_value=(
                model.SOLECTRIA_TWO_DIODE_COEFFICIENTS,
                large_residual,
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "residual is too large"):
                model.fit_solectria_two_diode_coefficients()

    def test_validator_rejects_corrupt_frozen_coefficients(self) -> None:
        corrupt = list(model.SOLECTRIA_TWO_DIODE_COEFFICIENTS)
        corrupt[2] *= 10.0
        module = model._build_pvmismatch_module_from_coefficients(tuple(corrupt))

        with self.assertRaisesRegex(ValueError, "misses datasheet tolerance"):
            model.validate_solectria_module(module)

    def test_physics_fingerprint_is_stable_and_records_mppt_contract(self) -> None:
        self.assertEqual(
            model.SOLECTRIA_PHYSICS_FINGERPRINT,
            "85b94189c11f54221d02f730b9d95d85a97c3afa5b003f89b13487c35f6f3a8c",
        )
        manifest = model.solectria_physics_manifest()
        self.assertEqual(manifest["inverter"]["mppt_count"], 1)
        self.assertEqual(
            manifest["inverter"]["model"],
            model.SOLECTRIA_INVERTER_MODEL,
        )
        self.assertEqual(manifest["inverter"]["mppt_min_v"], 860.0)
        self.assertEqual(manifest["inverter"]["mppt_max_v"], 1_250.0)
        self.assertEqual(manifest["inverter"]["ac_rating_w"], 250_000.0)
        self.assertEqual(
            manifest["inverter"]["cec_efficiency_default"],
            0.985,
        )
        self.assertIn("common inverter voltage", manifest["mppt_assumption"])

    def test_api_request_defaults_use_xgi_cec_efficiency(self) -> None:
        from sbepv.api.schemas import AnnualRunRequest, RunRequest

        validation = RunRequest(
            from_date="2026-06-01",
            to_date="2026-06-02",
        )
        annual = AnnualRunRequest(
            from_date="2026-01-01",
            to_date="2026-12-31",
        )

        self.assertEqual(
            validation.solectria_inverter_efficiency,
            model.SOLECTRIA_INVERTER_CEC_EFFICIENCY,
        )
        self.assertEqual(
            annual.solectria_inverter_efficiency,
            model.SOLECTRIA_INVERTER_CEC_EFFICIENCY,
        )

    def test_calibration_fingerprint_covers_both_arrays_and_shared_physics(
        self,
    ) -> None:
        self.assertEqual(
            model.CALIBRATION_PHYSICS_FINGERPRINT,
            "827ceca557a95b79aa15e53bea367c3873bfbd6d9d7f9b8b3e4e09aa162d2196",
        )
        manifest = model.calibration_physics_manifest()
        self.assertIn("solaredge", manifest)
        self.assertIn("solectria", manifest)
        self.assertEqual(
            manifest["temperature"]["parameters"],
            model.TEMPERATURE_MODEL_PARAMETERS,
        )

        modified_temperature = {
            **model.TEMPERATURE_MODEL_PARAMETERS,
            "deltaT": model.TEMPERATURE_MODEL_PARAMETERS["deltaT"] + 1,
        }
        with mock.patch.object(
            model,
            "TEMPERATURE_MODEL_PARAMETERS",
            modified_temperature,
        ):
            self.assertNotEqual(
                model.calibration_physics_fingerprint(),
                model.CALIBRATION_PHYSICS_FINGERPRINT,
            )

        modified_tilts = [list(row) for row in model.SOLAREDGE_TILT_ASBUILT]
        modified_tilts[0][0] += 0.01
        with mock.patch.object(model, "SOLAREDGE_TILT_ASBUILT", modified_tilts):
            self.assertNotEqual(
                model.calibration_physics_fingerprint(),
                model.CALIBRATION_PHYSICS_FINGERPRINT,
            )

    def test_production_curve_tracks_cec_reference_grid(self) -> None:
        module = model.build_pvmismatch_module()
        for irradiance_w_m2 in (500.0, 1_000.0, 1_200.0):
            for temperature_c in (0.0, 25.0, 65.0):
                with self.subTest(
                    irradiance_w_m2=irradiance_w_m2,
                    temperature_c=temperature_c,
                ):
                    actual = model.solectria_module_power_point(
                        module,
                        irradiance_suns=irradiance_w_m2 / 1_000.0,
                        temperature_c=temperature_c,
                    )["pmp_w"]
                    expected = _cec_reference_pmp_w(
                        irradiance_w_m2=irradiance_w_m2,
                        temperature_c=temperature_c,
                    )
                    self.assertLess(abs(actual / expected - 1.0), 0.03)

    def test_production_low_light_cec_difference_is_bounded(self) -> None:
        actual = model.solectria_module_power_point(
            model.build_pvmismatch_module(),
            irradiance_suns=0.2,
            temperature_c=25.0,
        )["pmp_w"]
        expected = _cec_reference_pmp_w(
            irradiance_w_m2=200.0,
            temperature_c=25.0,
        )

        self.assertLess(abs(actual / expected - 1.0), 0.06)


class FastMismatchParityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = model.build_pvmismatch_module()
        self.topology = model._uniform_series_topology(self.module)

    def fast_curve(
        self,
        irradiance_suns: float,
        temperature_k: float,
    ) -> tuple[np.ndarray, np.ndarray, float]:
        return model._uniform_module_curve(
            self.module.pvcells[0],
            self.module.pvconst,
            *self.topology,
            irradiance_suns,
            temperature_k,
        )

    def fast_string_curve(
        self,
        irradiance_suns: tuple[float, float, float, float],
        temperature_k: tuple[float, float, float, float],
    ) -> tuple[np.ndarray, np.ndarray]:
        return model._uniform_string_curve(
            [
                self.fast_curve(irradiance, temperature)
                for irradiance, temperature in zip(
                    irradiance_suns,
                    temperature_k,
                    strict=True,
                )
            ],
            self.module.pvconst,
        )

    def generic_string(
        self,
        irradiance_suns: tuple[float, float, float, float],
        temperature_k: tuple[float, float, float, float],
    ) -> pvm.pvstring.PVstring:
        number_modules = model.MODULES_PER_BAY * model.SOLECTRIA_BAYS_PER_STRING
        reference = pvm.pvstring.PVstring(
            numberMods=number_modules,
            pvmods=[self.module] * number_modules,
        )
        reference.setSuns(
            {
                module_index: irradiance_suns[
                    module_index // model.MODULES_PER_BAY
                ]
                for module_index in range(number_modules)
            }
        )
        reference.setTemps(
            {
                module_index: temperature_k[
                    module_index // model.MODULES_PER_BAY
                ]
                for module_index in range(number_modules)
            }
        )
        return reference

    def test_uniform_module_curve_matches_generic_pvmismatch(self) -> None:
        for irradiance_suns, temperature_k in (
            (0.05, 275.0),
            (0.63, 301.5),
            (1.12, 329.0),
        ):
            with self.subTest(
                irradiance_suns=irradiance_suns,
                temperature_k=temperature_k,
            ):
                reference = copy(self.module)
                reference.setSuns(irradiance_suns)
                reference.setTemps(temperature_k)

                current, voltage, short_circuit_current = self.fast_curve(
                    irradiance_suns,
                    temperature_k,
                )

                np.testing.assert_allclose(
                    current,
                    reference.Imod,
                    rtol=1e-12,
                    atol=1e-12,
                )
                np.testing.assert_allclose(
                    voltage,
                    reference.Vmod,
                    rtol=1e-12,
                    atol=1e-12,
                )
                self.assertAlmostEqual(
                    short_circuit_current,
                    float(reference.Isc.mean()),
                    places=12,
                )

    def test_string_power_matches_generic_pvmismatch(self) -> None:
        bay_irradiance = (0.24, 0.51, 0.83, 1.06)
        bay_temperature = (285.0, 296.0, 310.0, 324.0)
        number_modules = model.MODULES_PER_BAY * model.SOLECTRIA_BAYS_PER_STRING
        reference = pvm.pvstring.PVstring(
            numberMods=number_modules,
            pvmods=[self.module] * number_modules,
        )
        reference.setSuns(
            {
                module_index: bay_irradiance[
                    module_index // model.MODULES_PER_BAY
                ]
                for module_index in range(number_modules)
            }
        )
        reference.setTemps(
            {
                module_index: bay_temperature[
                    module_index // model.MODULES_PER_BAY
                ]
                for module_index in range(number_modules)
            }
        )
        expected = float(np.nanmax(reference.Pstring))

        curves = [
            self.fast_curve(irradiance, temperature)
            for irradiance, temperature in zip(
                bay_irradiance,
                bay_temperature,
                strict=True,
            )
        ]
        actual = model._uniform_string_max_power(curves, self.module.pvconst)

        self.assertAlmostEqual(actual, expected, places=9)

    def test_common_mppt_matches_generic_parallel_system(self) -> None:
        profiles = (
            ((0.24, 0.51, 0.83, 1.06), (285.0, 296.0, 310.0, 324.0)),
            ((1.02, 0.76, 0.39, 0.17), (323.0, 312.0, 298.0, 287.0)),
        )
        fast_strings = [
            self.fast_string_curve(irradiance, temperature)
            for irradiance, temperature in profiles
        ]
        reference = pvm.pvsystem.PVsystem(
            numberStrs=len(profiles),
            pvstrs=[
                self.generic_string(irradiance, temperature)
                for irradiance, temperature in profiles
            ],
        )
        expected_index = int(np.nanargmax(reference.Psys))

        power, voltage, current = model._common_mppt_power_point(
            fast_strings,
            self.module.pvconst,
            minimum_voltage=0.0,
            maximum_voltage=10_000.0,
        )

        self.assertAlmostEqual(power, float(reference.Psys[expected_index]), places=8)
        self.assertAlmostEqual(voltage, float(reference.Vsys[expected_index]), places=9)
        self.assertAlmostEqual(current, float(reference.Isys[expected_index]), places=11)

    def test_common_mppt_is_not_sum_of_independent_string_maxima(self) -> None:
        strings = [
            self.fast_string_curve(
                (0.24, 0.51, 0.83, 1.06),
                (285.0, 296.0, 310.0, 324.0),
            ),
            self.fast_string_curve(
                (1.02, 0.76, 0.39, 0.17),
                (323.0, 312.0, 298.0, 287.0),
            ),
        ]
        independent_power = sum(
            float(np.nanmax(current * voltage))
            for current, voltage in strings
        )

        common_power, voltage, _ = model._common_mppt_power_point(
            strings,
            self.module.pvconst,
            minimum_voltage=0.0,
            maximum_voltage=10_000.0,
        )

        self.assertLess(common_power, independent_power)
        self.assertGreaterEqual(voltage, 0.0)

    def test_common_mppt_searches_secondary_peak_inside_xgi_window(self) -> None:
        strings = [
            self.fast_string_curve(
                (0.254, 0.261, 0.220, 0.264),
                (297.2, 277.5, 288.1, 306.9),
            ),
            self.fast_string_curve(
                (0.182, 0.460, 0.338, 0.470),
                (304.0, 313.0, 295.9, 312.6),
            ),
        ]
        unconstrained_power, unconstrained_voltage, _ = (
            model._common_mppt_power_point(
                strings,
                self.module.pvconst,
                minimum_voltage=0.0,
                maximum_voltage=2_000.0,
            )
        )

        bounded_power, bounded_voltage, _ = model._common_mppt_power_point(
            strings,
            self.module.pvconst,
        )

        self.assertLess(unconstrained_voltage, 860.0)
        self.assertGreater(bounded_voltage, 900.0)
        self.assertNotEqual(bounded_voltage, 860.0)
        self.assertLess(bounded_power, unconstrained_power)
        self.assertAlmostEqual(bounded_power, 5_809.493365968902, places=8)
        self.assertAlmostEqual(bounded_voltage, 1_090.8125136716865, places=8)

    def test_production_curve_runs_on_one_mppt_inside_xgi_window(self) -> None:
        string_curve = self.fast_string_curve(
            (1.0, 1.0, 1.0, 1.0),
            (298.15, 298.15, 298.15, 298.15),
        )

        power, voltage, current = model._common_mppt_power_point(
            [string_curve] * model.SOLECTRIA_STRINGS,
            self.module.pvconst,
        )

        self.assertGreater(power, 139_000.0)
        self.assertLess(power, 139_300.0)
        self.assertGreaterEqual(voltage, model.SOLECTRIA_INVERTER_MPPT_MIN_V)
        self.assertLessEqual(voltage, model.SOLECTRIA_INVERTER_MPPT_MAX_V)
        self.assertAlmostEqual(power, voltage * current, places=8)

    def test_common_mppt_interpolates_exact_window_boundary(self) -> None:
        current = np.array([10.0, 9.0, 0.0])
        voltage = np.array([0.0, 800.0, 1_000.0])

        power, selected_voltage, selected_current = (
            model._common_mppt_power_point(
                [(current, voltage), (current, voltage)],
                self.module.pvconst,
                minimum_voltage=860.0,
                maximum_voltage=1_000.0,
            )
        )

        self.assertEqual(selected_voltage, 860.0)
        self.assertAlmostEqual(selected_current, 12.6, places=10)
        self.assertAlmostEqual(power, 10_836.0, places=7)

    def test_common_mppt_returns_zero_when_window_has_no_curve_overlap(self) -> None:
        power, voltage, current = model._common_mppt_power_point(
            [(np.array([10.0, 0.0]), np.array([0.0, 800.0]))],
            self.module.pvconst,
        )

        self.assertEqual(power, 0.0)
        self.assertTrue(np.isnan(voltage))
        self.assertEqual(current, 0.0)

    def test_common_mppt_rejects_invalid_curve_contracts(self) -> None:
        valid = (np.array([10.0, 0.0]), np.array([0.0, 1_000.0]))
        invalid_cases = (
            ([], "at least one"),
            (
                [valid, (np.array([10.0, 5.0, 0.0]), np.array([0.0, 500.0, 1_000.0]))],
                "shared grid size",
            ),
            (
                [(np.array([10.0, np.nan]), np.array([0.0, 1_000.0]))],
                "finite and aligned",
            ),
            (
                [(np.array([10.0, 5.0, 0.0]), np.array([0.0, 1_000.0, 900.0]))],
                "nondecreasing",
            ),
        )
        for curves, message in invalid_cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(ValueError, message):
                    model._common_mppt_power_point(
                        curves,
                        self.module.pvconst,
                    )

        with self.assertRaisesRegex(ValueError, "finite and ordered"):
            model._common_mppt_power_point(
                [valid],
                self.module.pvconst,
                minimum_voltage=1_250.0,
                maximum_voltage=860.0,
            )


if __name__ == "__main__":
    unittest.main()
