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
            "039ea395a578085ee0181dc062bc6f11f0f2b0f0813a311dc9df2d437583a47b",
        )
        self.assertEqual(
            model.solectria_physics_manifest()["mppt_assumption"],
            "each modeled string maximized independently",
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


if __name__ == "__main__":
    unittest.main()
