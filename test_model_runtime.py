import unittest
from copy import copy

import numpy as np
import pvmismatch as pvm

import sbe_pv_model as model


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
