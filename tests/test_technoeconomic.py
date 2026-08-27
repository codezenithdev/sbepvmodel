import hashlib
import json
import math
import unittest
from collections import Counter
from dataclasses import replace

import numpy as np
import scipy

from sbepv import technoeconomic as tea


GOLDEN_WDC = 240 * 579.92


def fixed(input_id, value):
    return tea.DistributionSpec(input_id=input_id, family="fixed", value=value)


def capacity(system, *, installed_wdc=GOLDEN_WDC):
    if installed_wdc == GOLDEN_WDC:
        if system == "solectria":
            strings, bays, modules = 10, 4, 6
        else:
            strings, bays, modules = 5, 8, 6
        module_stc = 579.92
    elif installed_wdc == 100_000:
        strings, bays, modules = 10, 2, 5
        module_stc = 1_000.0
    elif installed_wdc == 200_000:
        strings, bays, modules = 10, 4, 5
        module_stc = 1_000.0
    else:
        raise AssertionError("Unsupported test capacity")
    module_count = strings * bays * modules
    return tea.CapacitySpec(
        system=system,
        module_model="golden-module",
        module_stc_wdc=module_stc,
        strings=strings,
        bays_per_string=bays,
        modules_per_bay=modules,
        module_count=module_count,
        installed_wdc=installed_wdc,
        physics_version="physics-v1",
        physics_fingerprint="a" * 64,
    )


def cost_line(
    input_id,
    value_or_distribution,
    ownership,
    cost_type,
    sol_multiplier,
    se_multiplier,
    *,
    basis="solartac_site",
    coverage_id=None,
    sol_treatment="constant-real-v1",
    se_treatment="constant-real-v1",
):
    distribution = (
        value_or_distribution
        if isinstance(value_or_distribution, tea.DistributionSpec)
        else fixed(input_id, value_or_distribution)
    )
    return tea.CostLineSpec(
        input_id=input_id,
        label=input_id,
        basis=basis,
        ownership=ownership,
        cost_type=cost_type,
        distribution=distribution,
        solectria_multiplier_to_intensity=sol_multiplier,
        solaredge_multiplier_to_intensity=se_multiplier,
        coverage_ids=(coverage_id or input_id,),
        solectria_treatment_key=sol_treatment,
        solaredge_treatment_key=se_treatment,
    )


def golden_cost_lines(wdc=GOLDEN_WDC):
    sol = 1.0 / wdc
    se = 1.0 / wdc
    return (
        cost_line("cost.sol.capex", 100_000, "solectria_only", "initial_capex", sol, 0),
        cost_line(
            "cost.sol.install",
            20_000,
            "solectria_only",
            "initial_installation_labor",
            sol,
            0,
        ),
        cost_line("cost.se.capex", 130_000, "solaredge_only", "initial_capex", 0, se),
        cost_line(
            "cost.se.install",
            20_000,
            "solaredge_only",
            "initial_installation_labor",
            0,
            se,
        ),
        cost_line("cost.shared.capex", 10_000, "paired_shared", "initial_capex", sol, se),
        cost_line(
            "cost.shared.install",
            5_000,
            "paired_shared",
            "initial_installation_labor",
            sol,
            se,
        ),
        cost_line("cost.sol.labor", 1_000, "solectria_only", "recurring_labor", sol, 0),
        cost_line("cost.sol.om", 2_000, "solectria_only", "recurring_om", sol, 0),
        cost_line(
            "cost.sol.maintenance",
            500,
            "solectria_only",
            "recurring_maintenance",
            sol,
            0,
        ),
        cost_line("cost.se.labor", 1_100, "solaredge_only", "recurring_labor", 0, se),
        cost_line("cost.se.om", 2_100, "solaredge_only", "recurring_om", 0, se),
        cost_line(
            "cost.se.maintenance",
            500,
            "solaredge_only",
            "recurring_maintenance",
            0,
            se,
        ),
        cost_line("cost.shared.labor", 200, "paired_shared", "recurring_labor", sol, se),
        cost_line("cost.shared.om", 300, "paired_shared", "recurring_om", sol, se),
        cost_line(
            "cost.shared.maintenance",
            100,
            "paired_shared",
            "recurring_maintenance",
            sol,
            se,
        ),
    )


def golden_request(*, n=1, seed=7, se_energy=215_000.0, rows=None, cost_lines=None):
    return tea.TechnoeconomicRequest(
        basis="solartac_site",
        n=n,
        seed=seed,
        project_life_years=20,
        capacities=(capacity("solectria"), capacity("solaredge")),
        paired_energy_rows=tuple(
            rows
            or (
                tea.PairedEnergyRow(
                    year=2021,
                    sol_predicted_kwh_ac=200_000.0,
                    se_predicted_kwh_ac=se_energy,
                ),
            )
        ),
        cost_lines=tuple(cost_lines or golden_cost_lines()),
        discount_rate=fixed("finance.discount-rate", 0.05),
        shared_degradation=fixed("energy.shared-degradation", 0.005),
    )


def applied_capacity_request(*, applied_w=125_000.0, rating_basis="ac_operating_limit"):
    costs = (
        cost_line(
            "cost.sol.total",
            100_000,
            "solectria_only",
            "initial_capex",
            1 / applied_w,
            0,
        ),
        cost_line(
            "cost.se.total",
            120_000,
            "solaredge_only",
            "initial_capex",
            0,
            1 / applied_w,
        ),
    )
    return tea.TechnoeconomicRequest(
        basis="solartac_site",
        n=1,
        seed=7,
        project_life_years=1,
        capacities=(capacity("solectria"), capacity("solaredge")),
        applied_capacities=(
            tea.AppliedCapacitySpec("solectria", applied_w, rating_basis),
            tea.AppliedCapacitySpec("solaredge", applied_w, rating_basis),
        ),
        paired_energy_rows=(tea.PairedEnergyRow(2021, 172_263.0, 174_227.0),),
        cost_lines=costs,
        discount_rate=fixed("finance.discount-rate", 0),
        shared_degradation=fixed("energy.shared-degradation", 0),
        calculation_contract_version=tea.CALCULATION_CONTRACT_VERSION,
    )


def commercial_scaling_request(
    *,
    target_capacity_w=100_000_000.0,
    marginal_cost=314_240.0,
    marginal_cost_timing="lifecycle_present_value",
):
    request = applied_capacity_request()
    return replace(
        request,
        calculation_contract_version=(
            tea.COMMERCIAL_SCALING_CALCULATION_CONTRACT_VERSION
        ),
        commercial_scaling=tea.CommercialScalingSpec(
            target_capacity_w=target_capacity_w,
            target_rating_basis="ac_operating_limit",
            marginal_cost_difference=(
                marginal_cost
                if isinstance(marginal_cost, tea.DistributionSpec)
                else fixed(
                    tea.COMMERCIAL_MARGINAL_COST_DIFFERENCE_INPUT_ID,
                    marginal_cost,
                )
            ),
            marginal_cost_timing=marginal_cost_timing,
        ),
    )


def commercial_request(*, n=1, rows=None, transfer=True, costs=None):
    cost_lines = costs or (
        cost_line(
            "cost.sol.total",
            0.80,
            "solectria_only",
            "initial_capex",
            1,
            0,
            basis="commercial_representative",
        ),
        cost_line(
            "cost.se.total",
            0.90,
            "solaredge_only",
            "initial_capex",
            0,
            1,
            basis="commercial_representative",
        ),
        cost_line(
            "cost.shared.total",
            0.20,
            "paired_shared",
            "initial_capex",
            1,
            1,
            basis="commercial_representative",
        ),
    )
    transfer_spec = (
        tea.TransferSpec(
            baseline=fixed("transfer.baseline", 0.90),
            incremental=fixed("transfer.incremental", 0.50),
        )
        if transfer
        else None
    )
    return tea.TechnoeconomicRequest(
        basis="commercial_representative",
        n=n,
        seed=42,
        project_life_years=1,
        capacities=(
            capacity("solectria", installed_wdc=100_000),
            capacity("solaredge", installed_wdc=100_000),
        ),
        paired_energy_rows=tuple(
            rows
            or (
                tea.PairedEnergyRow(2020, 140_000.0, 150_000.0),
            )
        ),
        cost_lines=tuple(cost_lines),
        discount_rate=fixed("finance.discount-rate", 0.0),
        shared_degradation=fixed("energy.shared-degradation", 0.0),
        transfer=transfer_spec,
    )


class DistributionContractTests(unittest.TestCase):
    def test_equal_uniform_and_triangular_bounds_canonicalize_to_fixed(self):
        uniform = tea.validate_distribution(
            tea.DistributionSpec("cost.a", "uniform", low=2.5, high=2.5),
            "cost",
        )
        triangular = tea.validate_distribution(
            tea.DistributionSpec("cost.b", "triangular", low=4, mode=4, high=4),
            "cost",
        )

        self.assertEqual(uniform, fixed("cost.a", 2.5))
        self.assertEqual(triangular, fixed("cost.b", 4.0))

    def test_uniform_and_triangular_inverse_cdfs_are_analytic(self):
        uniform = tea.DistributionSpec("x.uniform", "uniform", low=10, high=20)
        triangular = tea.DistributionSpec(
            "x.triangular", "triangular", low=0, mode=0.5, high=1
        )

        np.testing.assert_allclose(
            tea.inverse_cdf(uniform, np.array([0.25, 0.75])),
            [12.5, 17.5],
        )
        np.testing.assert_allclose(
            tea.inverse_cdf(triangular, np.array([0.125, 0.875])),
            [0.25, 0.75],
        )

    def test_triangular_endpoint_modes_remain_valid(self):
        low_mode = tea.DistributionSpec(
            "x.low-mode", "triangular", low=0, mode=0, high=1
        )
        high_mode = tea.DistributionSpec(
            "x.high-mode", "triangular", low=0, mode=1, high=1
        )
        values = np.array([0.25, 0.75])

        np.testing.assert_allclose(
            tea.inverse_cdf(low_mode, values),
            1 - np.sqrt(1 - values),
        )
        np.testing.assert_allclose(
            tea.inverse_cdf(high_mode, values),
            np.sqrt(values),
        )

    def test_triangular_inverse_is_stable_for_large_finite_support(self):
        spec = tea.DistributionSpec(
            "x.large",
            "triangular",
            low=1e308,
            mode=1.3e308,
            high=1.6e308,
        )

        values = tea.inverse_cdf(spec, np.array([0.25, 0.75]))

        np.testing.assert_allclose(
            values,
            [1.2121320343559643e308, 1.3878679656440358e308],
            rtol=1e-15,
        )

    def test_bounded_normal_handles_far_tail_without_clipping(self):
        spec = tea.DistributionSpec(
            "x.tail", "bounded_normal", low=10, high=11, mean=0, sd=1
        )
        values = tea.inverse_cdf(spec, np.array([2**-53, 0.5, 1 - 2**-53]))

        self.assertTrue(np.all(values > 10))
        self.assertTrue(np.all(values < 11))
        self.assertGreater(values[1], values[0])
        self.assertGreater(values[2], values[1])

    def test_bounded_normal_rejects_interval_without_binary64_interior(self):
        low = 1.0
        high = math.nextafter(low, math.inf)
        with self.assertRaisesRegex(tea.TechnoeconomicValidationError, "no representable"):
            tea.validate_distribution(
                tea.DistributionSpec(
                    "x.narrow", "bounded_normal", low=low, high=high, mean=1, sd=1
                )
            )

    def test_every_continuous_family_rejects_no_binary64_interior(self):
        low = 1.0
        high = math.nextafter(low, math.inf)
        specs = (
            tea.DistributionSpec("x.uniform", "uniform", low=low, high=high),
            tea.DistributionSpec(
                "x.triangular", "triangular", low=low, mode=low, high=high
            ),
        )
        for spec in specs:
            with self.subTest(family=spec.family), self.assertRaisesRegex(
                tea.TechnoeconomicValidationError, "no representable"
            ):
                tea.validate_distribution(spec)

    def test_role_support_rules_fail_closed(self):
        cases = (
            (fixed("cost.negative", -0.01), "cost", "nonnegative"),
            (fixed("finance.invalid", -1), "discount_rate", "greater than -1"),
            (fixed("energy.invalid", 1), "degradation", "0 <= g < 1"),
            (fixed("transfer.invalid", 0), "transfer_baseline", "strictly positive"),
            (fixed("transfer.invalid", -0.1), "transfer_incremental", "nonnegative"),
        )
        for spec, role, message in cases:
            with self.subTest(role=role), self.assertRaisesRegex(
                tea.TechnoeconomicValidationError, message
            ):
                tea.validate_distribution(spec, role)

    def test_distribution_schema_rejects_extra_or_missing_parameters(self):
        with self.assertRaisesRegex(tea.TechnoeconomicValidationError, "requires only"):
            tea.validate_distribution(
                tea.DistributionSpec("x.bad", "fixed", value=1, low=0)
            )
        with self.assertRaisesRegex(tea.TechnoeconomicValidationError, "requires only"):
            tea.validate_distribution(
                tea.DistributionSpec("x.bad", "bounded_normal", low=0, high=1, mean=0)
            )


class NumericalContractGateTests(unittest.TestCase):
    """The gate must accept a conforming runtime and reject a drifted one."""

    def test_current_runtime_satisfies_every_probe(self):
        tea.validate_runtime_versions()
        fingerprint = tea.numerical_fingerprint()
        self.assertEqual(fingerprint["probe_digests"], tea.NUMERICAL_PROBE_DIGESTS)
        self.assertEqual(
            sorted(tea.NUMERICAL_PROBE_DIGESTS),
            ["binary64_growth", "pcg64dxsm_stream", "truncnorm_ppf", "type7_quantile"],
        )

    def test_a_drifted_probe_fails_closed_and_names_itself(self):
        original = dict(tea.NUMERICAL_PROBE_DIGESTS)
        tea.NUMERICAL_PROBE_DIGESTS["truncnorm_ppf"] = "00" * 32
        try:
            with self.assertRaises(tea.TechnoeconomicValidationError) as caught:
                tea.validate_runtime_versions()
        finally:
            tea.NUMERICAL_PROBE_DIGESTS.clear()
            tea.NUMERICAL_PROBE_DIGESTS.update(original)
        self.assertIn("truncnorm_ppf", str(caught.exception))
        self.assertNotIn("type7_quantile", str(caught.exception))

    def test_an_unevaluatable_probe_fails_closed(self):
        def exploding_probe():
            raise RuntimeError("scipy signature changed")

        original = tea._NUMERICAL_PROBES["truncnorm_ppf"]
        tea._NUMERICAL_PROBES["truncnorm_ppf"] = exploding_probe
        try:
            with self.assertRaises(tea.TechnoeconomicValidationError) as caught:
                tea.validate_runtime_versions()
        finally:
            tea._NUMERICAL_PROBES["truncnorm_ppf"] = original
        self.assertIn("scipy signature changed", str(caught.exception))

    def test_tolerance_absorbs_last_bit_drift_but_not_a_collapsed_tail(self):
        # SciPy 1.17.1 and 1.18.0 differ by three ULP on one near-bound case.
        # That must not trip the gate; a collapsed far-tail interval must.
        values = tea._NUMERICAL_PROBES["truncnorm_ppf"]()
        nudged = tuple(math.nextafter(v, math.inf) for v in values)
        self.assertEqual(
            tea._serialize_probe(values, exact=False),
            tea._serialize_probe(nudged, exact=False),
        )
        self.assertNotEqual(
            tea._serialize_probe(values, exact=True),
            tea._serialize_probe(nudged, exact=True),
        )
        collapsed = tuple(10.0 for _ in values)
        self.assertNotEqual(
            tea._serialize_probe(values, exact=False),
            tea._serialize_probe(collapsed, exact=False),
        )


class SamplingContractTests(unittest.TestCase):
    class FakeRaw:
        def __init__(self, words):
            self.words = iter(words)

        def random_raw(self):
            return next(self.words)

    def test_domain_separated_substream_has_pinned_golden_words(self):
        generator = tea._substream(42, tea.LHS_JITTER_PURPOSE, "cost.sol.capex")
        actual = [int(generator.random_raw()) for _ in range(6)]

        self.assertEqual(
            actual,
            [
                16134120184855450017,
                12494147110838038685,
                7176601401060945435,
                11053240246408089668,
                2560452283119679514,
                5025172646427091558,
            ],
        )

    def test_open_jitter_rejects_zero_and_accepts_extreme_words(self):
        minimum = tea._open_interval_jitter(self.FakeRaw([0, 1 << 11]))
        maximum = tea._open_interval_jitter(self.FakeRaw([(1 << 64) - 1]))

        self.assertEqual(minimum, 2**-53)
        self.assertEqual(maximum, 1 - 2**-53)

    def test_binary64_boundary_repair_keeps_every_stratum_open(self):
        for n in (3, 100_000):
            words = [(1 << 64) - 1] * n
            values = tea._jittered_strata(n, self.FakeRaw(words))
            for index in (0, n // 2, n - 1):
                self.assertGreater(values[index], index / n)
                self.assertLess(values[index], (index + 1) / n)

    def test_random_below_uses_rejection_without_uint64_overflow(self):
        result = tea._random_below(
            self.FakeRaw([(1 << 64) - 1, 5]),
            3,
        )
        power_of_two = tea._random_below(self.FakeRaw([(1 << 64) - 1]), 8)

        self.assertEqual(result, 2)
        self.assertEqual(power_of_two, 7)

    def test_lhs_has_pinned_values_and_one_value_per_stratum(self):
        sampled = tea.generate_lhs(
            6,
            42,
            [tea.DistributionSpec("cost.sol.capex", "uniform", low=0, high=1)],
        )["cost.sol.capex"]
        expected = np.array(
            [
                0.5998662257346655,
                0.3981740569174399,
                0.6898003993991986,
                0.1457720679630209,
                0.27955151200770073,
                0.8787358591697583,
            ]
        )

        np.testing.assert_array_equal(sampled, expected)
        self.assertEqual(sorted(np.floor(sampled * 6).astype(int).tolist()), list(range(6)))

    def test_dimension_order_and_addition_do_not_change_existing_draws(self):
        a = tea.DistributionSpec("input.a", "uniform", low=0, high=1)
        b = tea.DistributionSpec("input.b", "triangular", low=0, mode=1, high=2)
        c = tea.DistributionSpec(
            "input.c", "bounded_normal", low=0, high=2, mean=1, sd=0.5
        )

        forward = tea.generate_lhs(32, 99, [a, b])
        reverse = tea.generate_lhs(32, 99, [b, a])
        extended = tea.generate_lhs(32, 99, [c, b, a])

        np.testing.assert_array_equal(forward["input.a"], reverse["input.a"])
        np.testing.assert_array_equal(forward["input.a"], extended["input.a"])
        np.testing.assert_array_equal(forward["input.b"], extended["input.b"])

    def test_fixed_inputs_do_not_consume_an_lhs_dimension(self):
        uncertain = tea.DistributionSpec("input.a", "uniform", low=0, high=1)
        alone = tea.generate_lhs(20, 10, [uncertain])
        together = tea.generate_lhs(20, 10, [fixed("input.fixed", 3), uncertain])

        np.testing.assert_array_equal(alone["input.a"], together["input.a"])
        np.testing.assert_array_equal(together["input.fixed"], np.full(20, 3.0))

    def test_seed_and_identifier_validation_rejects_bool_and_reserved_id(self):
        spec = tea.DistributionSpec("input.a", "uniform", low=0, high=1)
        for seed in (True, -1, 1 << 64):
            with self.subTest(seed=seed), self.assertRaises(tea.TechnoeconomicValidationError):
                tea.generate_lhs(10, seed, [spec])
        with self.assertRaisesRegex(tea.TechnoeconomicValidationError, "reserved"):
            tea.generate_lhs(
                10,
                1,
                [tea.DistributionSpec("weather.year", "uniform", low=0, high=1)],
            )

    def test_realization_guardrails_and_seed_endpoints_are_exact(self):
        self.assertEqual(tea._validate_n_seed(1, 0), (1, 0))
        self.assertEqual(
            tea._validate_n_seed(100_000, (1 << 64) - 1),
            (100_000, (1 << 64) - 1),
        )
        for n in (True, 0, 100_001):
            with self.subTest(n=n), self.assertRaises(tea.TechnoeconomicValidationError):
                tea._validate_n_seed(n, 0)
        sampled = tea.generate_lhs(
            2,
            (1 << 64) - 1,
            [tea.DistributionSpec("input.a", "uniform", low=0, high=1)],
        )
        self.assertEqual(len(sampled["input.a"]), 2)

    def test_balanced_weather_has_pinned_assignment_and_order_invariance(self):
        years = [2019, 2020, 2021, 2022]
        expected = [2022, 2021, 2021, 2020, 2019, 2022, 2020, 2019, 2022, 2019, 2021]

        forward = tea.allocate_weather_years(11, 42, years)
        reverse = tea.allocate_weather_years(11, 42, list(reversed(years)))

        self.assertEqual(forward.tolist(), expected)
        np.testing.assert_array_equal(forward, reverse)
        counts = Counter(forward.tolist())
        self.assertLessEqual(max(counts.values()) - min(counts.values()), 1)

    def test_balanced_weather_preserves_zero_count_years_when_n_is_small(self):
        assignments = tea.allocate_weather_years(2, 4, [2018, 2019, 2020, 2021])

        self.assertEqual(len(assignments), 2)
        self.assertEqual(len(set(assignments.tolist())), 2)


class CapacityAndRequestValidationTests(unittest.TestCase):
    def test_current_capacity_manifest_is_exact_and_system_specific(self):
        sol = tea.validate_capacity(capacity("solectria"))
        se = tea.validate_capacity(capacity("solaredge"))

        self.assertEqual(sol.installed_wdc, 139_180.8)
        self.assertEqual(se.installed_wdc, 139_180.8)
        self.assertEqual(sol.module_count, 240)
        self.assertEqual(se.module_count, 240)
        self.assertNotEqual(sol.strings, se.strings)

    def test_capacity_rejects_bool_topology_mismatch_and_wrong_wdc(self):
        good = capacity("solectria")
        cases = (
            (replace(good, strings=True), "positive integer"),
            (replace(good, module_count=239), "topology product"),
            (replace(good, installed_wdc=1), "must equal installed_wdc"),
            (
                replace(good, installed_wdc=good.installed_wdc + 1e-8),
                "must equal installed_wdc",
            ),
        )
        for spec, message in cases:
            with self.subTest(message=message), self.assertRaisesRegex(
                tea.TechnoeconomicValidationError, message
            ):
                tea.validate_capacity(spec)

    def test_v2_requires_complete_consistent_applied_capacity_evidence(self):
        good = applied_capacity_request()
        invalid = (
            (replace(good, applied_capacities=None), "require applied_capacities"),
            (
                replace(
                    good,
                    applied_capacities=(
                        tea.AppliedCapacitySpec(
                            "solectria", 125_000, "ac_operating_limit"
                        ),
                        tea.AppliedCapacitySpec(
                            "solaredge", 124_999, "ac_operating_limit"
                        ),
                    ),
                ),
                "identical for both systems",
            ),
            (
                replace(
                    good,
                    applied_capacities=(
                        tea.AppliedCapacitySpec(
                            "solectria", 125_000, "ac_operating_limit"
                        ),
                        tea.AppliedCapacitySpec(
                            "solaredge", GOLDEN_WDC, "dc_installed_nameplate"
                        ),
                    ),
                ),
                "one shared rating basis",
            ),
        )
        for request, message in invalid:
            with self.subTest(message=message), self.assertRaisesRegex(
                tea.TechnoeconomicValidationError, message
            ):
                tea.validate_request(request)

    def test_contract_versions_fail_closed_around_applied_capacity(self):
        v2 = applied_capacity_request()
        with self.assertRaisesRegex(
            tea.TechnoeconomicValidationError, "v1 must not define"
        ):
            tea.validate_request(
                replace(
                    v2,
                    calculation_contract_version=(
                        tea.LEGACY_CALCULATION_CONTRACT_VERSION
                    ),
                )
            )
        with self.assertRaisesRegex(
            tea.TechnoeconomicValidationError, "only for the SolarTAC"
        ):
            tea.validate_request(
                replace(
                    commercial_request(),
                    calculation_contract_version=tea.CALCULATION_CONTRACT_VERSION,
                    applied_capacities=v2.applied_capacities,
                )
            )

    def test_v3_requires_scaling_and_v1_v2_forbid_it(self):
        v3 = commercial_scaling_request()
        with self.assertRaisesRegex(
            tea.TechnoeconomicValidationError, "v3 requires commercial_scaling"
        ):
            tea.validate_request(replace(v3, commercial_scaling=None))

        for older in (
            replace(golden_request(), commercial_scaling=v3.commercial_scaling),
            replace(
                applied_capacity_request(),
                commercial_scaling=v3.commercial_scaling,
            ),
        ):
            with self.subTest(version=older.calculation_contract_version), self.assertRaisesRegex(
                tea.TechnoeconomicValidationError, "v1 and tea-calculation-v2"
            ):
                tea.validate_request(older)

    def test_v3_validates_target_basis_method_timing_and_stable_cost_id(self):
        good = commercial_scaling_request()
        invalid_specs = (
            (
                replace(good.commercial_scaling, target_capacity_w=0),
                "target_capacity_w must be strictly positive",
            ),
            (
                replace(
                    good.commercial_scaling,
                    target_rating_basis="dc_installed_nameplate",
                ),
                "target rating basis must match",
            ),
            (
                replace(good.commercial_scaling, transfer_method="proportional_guess"),
                "direct_capacity_scaling",
            ),
            (
                replace(good.commercial_scaling, marginal_cost_timing="year_one"),
                "lifecycle_present_value.*equivalent_annual",
            ),
            (
                replace(
                    good.commercial_scaling,
                    marginal_cost_difference=fixed("commercial.wrong-id", 1),
                ),
                tea.COMMERCIAL_MARGINAL_COST_DIFFERENCE_INPUT_ID,
            ),
        )
        for spec, message in invalid_specs:
            with self.subTest(message=message), self.assertRaisesRegex(
                tea.TechnoeconomicValidationError, message
            ):
                tea.validate_request(replace(good, commercial_scaling=spec))

    def test_v3_accepts_signed_marginal_cost_support_and_rejects_overflow(self):
        signed = tea.DistributionSpec(
            tea.COMMERCIAL_MARGINAL_COST_DIFFERENCE_INPUT_ID,
            "uniform",
            low=-100,
            high=200,
        )
        validated = tea.validate_request(
            commercial_scaling_request(marginal_cost=signed)
        )
        self.assertEqual(
            tea.distribution_support(
                validated.commercial_scaling.marginal_cost_difference
            ),
            (-100.0, 200.0),
        )

        overflowing = commercial_scaling_request(
            target_capacity_w=1,
            marginal_cost=1e308,
        )
        with self.assertRaisesRegex(
            tea.TechnoeconomicValidationError, "commercial marginal LCOO"
        ):
            tea.validate_request(overflowing)

    def test_v2_dc_fallback_must_match_installed_manifests(self):
        request = applied_capacity_request(
            applied_w=GOLDEN_WDC,
            rating_basis="dc_installed_nameplate",
        )
        validated = tea.validate_request(request)
        self.assertEqual(validated.applied_capacities, request.applied_capacities)

        mismatched = replace(
            request,
            applied_capacities=(
                request.applied_capacities[0],
                replace(request.applied_capacities[1], applied_capacity_w=GOLDEN_WDC - 1),
            ),
        )
        with self.assertRaisesRegex(
            tea.TechnoeconomicValidationError, "must exactly match"
        ):
            tea.validate_request(mismatched)

    def test_canonical_payload_preserves_literal_v1_shape(self):
        legacy_payload = tea.canonical_request_payload(golden_request())
        applied_payload = tea.canonical_request_payload(applied_capacity_request())

        self.assertNotIn("applied_capacities", legacy_payload)
        self.assertNotIn("commercial_scaling", legacy_payload)
        self.assertNotIn("commercial_scaling", applied_payload)
        self.assertIn("applied_capacities", applied_payload)
        self.assertEqual(
            applied_payload["calculation_contract_version"],
            tea.CALCULATION_CONTRACT_VERSION,
        )
        legacy_bytes = json.dumps(
            legacy_payload,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        self.assertEqual(
            "b7fce66548f1d9b2504f8d7b0b9c6ff242259899cc5b10c82527b3e42a2c432c",
            hashlib.sha256(legacy_bytes).hexdigest(),
        )

        commercial_payload = tea.canonical_request_payload(
            commercial_scaling_request()
        )
        self.assertIn("commercial_scaling", commercial_payload)
        self.assertEqual(
            commercial_payload["commercial_scaling"]["transfer_method"],
            tea.COMMERCIAL_SCALING_TRANSFER_METHOD,
        )

    def test_request_canonicalizes_energy_and_cost_order(self):
        rows = (
            tea.PairedEnergyRow(2022, 210_000, 220_000),
            tea.PairedEnergyRow(2020, 190_000, 200_000),
        )
        costs = tuple(reversed(golden_cost_lines()))

        validated = tea.validate_request(golden_request(rows=rows, cost_lines=costs))

        self.assertEqual([row.year for row in validated.paired_energy_rows], [2020, 2022])
        self.assertEqual(
            [line.input_id for line in validated.cost_lines],
            sorted(line.input_id for line in costs),
        )

    def test_request_rejects_duplicate_input_ids_and_mixed_basis(self):
        lines = list(golden_cost_lines())
        lines[1] = replace(
            lines[1],
            input_id=lines[0].input_id,
            distribution=fixed(lines[0].input_id, 20_000),
        )
        with self.assertRaisesRegex(tea.TechnoeconomicValidationError, "input ID.*unique"):
            tea.validate_request(golden_request(cost_lines=lines))

        mixed = list(golden_cost_lines())
        mixed[0] = replace(mixed[0], basis="commercial_representative")
        with self.assertRaisesRegex(tea.TechnoeconomicValidationError, "mixes analysis bases"):
            tea.validate_request(golden_request(cost_lines=mixed))

    def test_request_rejects_cost_scope_overlap(self):
        lines = list(golden_cost_lines())
        # Different labels cannot hide an all-in t=0 total plus contained labor.
        lines[1] = replace(lines[1], coverage_ids=lines[0].coverage_ids)
        with self.assertRaisesRegex(tea.TechnoeconomicValidationError, "Cost scope overlap"):
            tea.validate_request(golden_request(cost_lines=lines))

    def test_full_system_stack_rejects_an_obviously_missing_system(self):
        one_sided = (
            cost_line(
                "cost.sol.only",
                1.0,
                "solectria_only",
                "initial_capex",
                1,
                0,
            ),
        )
        with self.assertRaisesRegex(tea.TechnoeconomicValidationError, "solaredge cost stream"):
            tea.validate_request(golden_request(cost_lines=one_sided))

    def test_same_component_can_have_disjoint_initial_and_recurring_scopes(self):
        lines = list(golden_cost_lines())
        lines[6] = replace(lines[6], coverage_ids=lines[0].coverage_ids)

        validated = tea.validate_request(golden_request(cost_lines=lines))

        self.assertEqual(len(validated.cost_lines), len(lines))

    def test_commercial_transfer_support_rejects_nonpositive_solaredge_yield(self):
        rows = (tea.PairedEnergyRow(2020, 140_000, 100_000),)
        request = commercial_request(rows=rows)
        bad_transfer = tea.TransferSpec(
            baseline=tea.DistributionSpec(
                "transfer.baseline", "uniform", low=0.1, high=0.2
            ),
            incremental=tea.DistributionSpec(
                "transfer.incremental", "uniform", low=0, high=1
            ),
        )

        with self.assertRaisesRegex(tea.TechnoeconomicValidationError, "positive absolute"):
            tea.validate_request(replace(request, transfer=bad_transfer))

    def test_commercial_transfer_requires_approved_status(self):
        request = commercial_request()
        with self.assertRaisesRegex(tea.TechnoeconomicValidationError, "approved mechanism"):
            tea.validate_request(
                replace(
                    request,
                    transfer=replace(request.transfer, mechanism_status="draft"),
                )
            )

    def test_enormous_life_and_transfer_overflow_fail_as_validation(self):
        with self.assertRaisesRegex(tea.TechnoeconomicValidationError, "not representable"):
            tea.annuity_factor_and_crf(0.05, 10**400)

        request = commercial_request()
        overflowing = tea.TransferSpec(
            baseline=tea.DistributionSpec(
                "transfer.baseline", "uniform", low=1e307, high=1.7e308
            ),
            incremental=fixed("transfer.incremental", 0),
        )
        with self.assertRaisesRegex(tea.TechnoeconomicValidationError, "positive absolute"):
            tea.validate_request(replace(request, transfer=overflowing))

    def test_nonfinite_site_raw_diagnostics_are_rejected_before_execution(self):
        huge_capacity = lambda system: tea.CapacitySpec(
            system=system,
            module_model="huge-module",
            module_stc_wdc=1e308,
            strings=1,
            bays_per_string=1,
            modules_per_bay=1,
            module_count=1,
            installed_wdc=1e308,
            physics_version="physics-v1",
            physics_fingerprint="b" * 64,
        )
        request = tea.TechnoeconomicRequest(
            basis="solartac_site",
            n=1,
            seed=1,
            project_life_years=1,
            capacities=(huge_capacity("solectria"), huge_capacity("solaredge")),
            paired_energy_rows=(tea.PairedEnergyRow(2020, 1e308, 1e308),),
            cost_lines=(
                cost_line(
                    "cost.sol.total", 2, "solectria_only", "initial_capex", 1, 0
                ),
                cost_line(
                    "cost.se.total", 2, "solaredge_only", "initial_capex", 0, 1
                ),
            ),
            discount_rate=fixed("finance.discount-rate", 0),
            shared_degradation=fixed("energy.shared-degradation", 0),
        )

        with self.assertRaisesRegex(tea.TechnoeconomicValidationError, "Support-wide"):
            tea.validate_request(request)

    def test_cost_support_overflow_is_rejected_before_execution(self):
        initial_lines = (
            cost_line(
                "cost.sol.total", 1e308, "solectria_only", "initial_capex", 2, 0
            ),
            cost_line(
                "cost.se.total", 1, "solaredge_only", "initial_capex", 0, 1
            ),
        )
        with self.assertRaisesRegex(tea.TechnoeconomicValidationError, "Support-wide"):
            tea.validate_request(golden_request(cost_lines=initial_lines))

        recurring_lines = (
            cost_line(
                "cost.sol.om", 1e308, "solectria_only", "recurring_om", 1, 0
            ),
            cost_line(
                "cost.se.om", 1e308, "solaredge_only", "recurring_om", 0, 1
            ),
        )
        recurring_request = replace(
            golden_request(cost_lines=recurring_lines),
            discount_rate=fixed("finance.discount-rate", -0.9),
        )
        with self.assertRaisesRegex(tea.TechnoeconomicValidationError, "Support-wide"):
            tea.validate_request(recurring_request)

    def test_commercial_reference_support_overflow_is_rejected(self):
        request = replace(
            commercial_request(transfer=False),
            commercial_reference_wdc=1.7e308,
        )

        with self.assertRaisesRegex(tea.TechnoeconomicValidationError, "Support-wide"):
            tea.validate_request(request)

    def test_reportable_lcoo_overflow_is_rejected_before_execution(self):
        costs = (
            cost_line(
                "cost.sol.total",
                1,
                "solectria_only",
                "initial_capex",
                1,
                0,
                basis="commercial_representative",
            ),
            cost_line(
                "cost.se.total",
                1e300,
                "solaredge_only",
                "initial_capex",
                0,
                1,
                basis="commercial_representative",
            ),
        )
        request = commercial_request(
            rows=(tea.PairedEnergyRow(2020, 140_000, 140_000.0002),),
            costs=costs,
        )

        with self.assertRaisesRegex(tea.TechnoeconomicValidationError, "signed LCOO"):
            tea.validate_request(request)

    def test_large_finite_lcoo_is_accepted_when_energy_is_bounded_away_from_zero(self):
        costs = (
            cost_line(
                "cost.sol.total",
                1,
                "solectria_only",
                "initial_capex",
                1,
                0,
                basis="commercial_representative",
            ),
            cost_line(
                "cost.se.total",
                1e300,
                "solaredge_only",
                "initial_capex",
                0,
                1,
                basis="commercial_representative",
            ),
        )
        request = commercial_request(
            rows=(tea.PairedEnergyRow(2020, 140_000, 300_000),),
            costs=costs,
        )

        result = tea.run_technoeconomic(request)

        self.assertTrue(math.isfinite(result.realization_table[tea.FIELD_LCOO][0]))
        self.assertGreater(result.realization_table[tea.FIELD_LCOO][0], 1e299)

    def test_shared_discount_endpoint_pairing_does_not_invent_overflow(self):
        costs = (
            cost_line(
                "cost.sol.om",
                1,
                "solectria_only",
                "recurring_om",
                1,
                0,
                basis="commercial_representative",
            ),
            cost_line(
                "cost.se.om",
                1,
                "solaredge_only",
                "recurring_om",
                0,
                1,
                basis="commercial_representative",
            ),
        )
        request = replace(
            commercial_request(costs=costs),
            discount_rate=tea.DistributionSpec(
                "finance.discount-rate",
                "uniform",
                low=-0.5,
                high=1.7e308,
            ),
        )

        validated = tea.validate_request(request)

        self.assertEqual(validated.discount_rate.high, 1.7e308)

    def test_interior_tolerance_crossover_lcoo_overflow_is_rejected(self):
        costs = (
            cost_line(
                "cost.sol.initial",
                0,
                "solectria_only",
                "initial_capex",
                1,
                0,
                basis="commercial_representative",
            ),
            cost_line(
                "cost.se.initial",
                1.1e299,
                "solaredge_only",
                "initial_capex",
                0,
                1,
                basis="commercial_representative",
            ),
            cost_line(
                "cost.sol.om",
                0,
                "solectria_only",
                "recurring_om",
                1,
                0,
                basis="commercial_representative",
            ),
            cost_line(
                "cost.se.om",
                1e296,
                "solaredge_only",
                "recurring_om",
                0,
                1,
                basis="commercial_representative",
            ),
        )
        request = replace(
            commercial_request(
                rows=(tea.PairedEnergyRow(2020, 100_000, 200_000),),
                costs=costs,
            ),
            project_life_years=20,
            discount_rate=tea.DistributionSpec(
                "finance.discount-rate", "uniform", low=-0.5, high=0
            ),
            shared_degradation=fixed("energy.shared-degradation", 0),
            transfer=tea.TransferSpec(
                baseline=fixed("transfer.baseline", 0.9),
                incremental=tea.DistributionSpec(
                    "transfer.incremental", "uniform", low=0, high=1
                ),
            ),
        )

        with self.assertRaisesRegex(tea.TechnoeconomicValidationError, "signed LCOO"):
            tea.validate_request(request)


class LifecycleCalculationTests(unittest.TestCase):
    def test_annuity_crf_and_energy_factor_match_golden(self):
        annuity, crf = tea.annuity_factor_and_crf(0.05, 20)
        factor = tea.lifecycle_energy_factor(0.05, 0.005, 20)

        self.assertAlmostEqual(annuity, 12.462210342539986, places=14)
        self.assertAlmostEqual(crf, 0.08024258719069133, places=14)
        self.assertAlmostEqual(factor, 11.9829422525055, places=13)
        self.assertEqual(tea.annuity_factor_and_crf(0, 20), (20.0, 0.05))

    def test_hand_calculated_golden_realization_ties_every_form(self):
        result = tea.run_technoeconomic(golden_request())
        row = result.realization_table

        self.assertAlmostEqual(row["PVCost_SOL_USD"][0], 186_095.06240441394, places=8)
        self.assertAlmostEqual(row["PVCost_SE_USD"][0], 218_587.50447292194, places=8)
        self.assertAlmostEqual(row["DeltaPVCostUSD_se_minus_sol"][0], 32_492.442068508, places=8)
        self.assertAlmostEqual(row["PVEnergy_SOL_kWh_AC"][0], 2_396_588.4505011002, places=7)
        self.assertAlmostEqual(row["PVEnergy_SE_kWh_AC"][0], 2_576_332.5842886827, places=7)
        self.assertAlmostEqual(row[tea.FIELD_LCOE_SOL][0], 0.07764998715799683, places=14)
        self.assertAlmostEqual(row[tea.FIELD_LCOE_SE][0], 0.08484444353416943, places=14)
        self.assertAlmostEqual(row[tea.FIELD_DELTA_COST][0], 0.23345491668756033, places=14)
        self.assertAlmostEqual(row[tea.FIELD_DELTA_ENERGY][0], 1.2914434590660674, places=13)
        self.assertAlmostEqual(row[tea.FIELD_DELTA_EA_COST][0], 0.01873302650739714, places=14)
        self.assertAlmostEqual(row[tea.FIELD_DELTA_EA_ENERGY][0], 0.10362876436595692, places=14)
        self.assertAlmostEqual(row[tea.FIELD_EA_COST_SOL][0], 14_932.7492707433 / GOLDEN_WDC, places=14)
        self.assertAlmostEqual(row[tea.FIELD_EA_COST_SE][0], 17_540.0268864641 / GOLDEN_WDC, places=14)
        self.assertAlmostEqual(row[tea.FIELD_EA_ENERGY_SOL][0], 192_308.45769953835 / GOLDEN_WDC, places=14)
        self.assertAlmostEqual(row[tea.FIELD_EA_ENERGY_SE][0], 206_731.59202700373 / GOLDEN_WDC, places=14)
        self.assertAlmostEqual(row[tea.FIELD_LCOO][0], 0.18077052854980412, places=14)
        self.assertAlmostEqual(
            row[tea.FIELD_DELTA_EA_COST][0] / row[tea.FIELD_DELTA_EA_ENERGY][0],
            row[tea.FIELD_LCOO][0],
            places=14,
        )
        self.assertEqual(row["energy_class"][0], "positive_lifecycle_gain")
        self.assertEqual(row["tradeoff_class"][0], "cost_increase_energy_gain")

    def test_v2_normalizes_site_energy_and_cost_by_applied_capacity(self):
        result = tea.run_technoeconomic(applied_capacity_request())
        row = result.realization_table

        self.assertNotIn(tea.FIELD_DELTA_ENERGY, row)
        self.assertAlmostEqual(
            row[tea.APPLIED_FIELD_YEAR1_SOL][0],
            172_263 / 125_000,
        )
        self.assertAlmostEqual(
            row[tea.APPLIED_FIELD_YEAR1_SE][0],
            174_227 / 125_000,
        )
        self.assertAlmostEqual(
            row[tea.APPLIED_FIELD_YEAR1_DELTA][0],
            1_964 / 125_000,
        )
        self.assertAlmostEqual(row[tea.APPLIED_FIELD_DELTA_COST][0], 0.16)
        self.assertAlmostEqual(
            row[tea.APPLIED_FIELD_DELTA_ENERGY][0],
            1_964 / 125_000,
        )
        self.assertAlmostEqual(row[tea.FIELD_LCOE_SOL][0], 100_000 / 172_263)
        self.assertAlmostEqual(row[tea.FIELD_LCOE_SE][0], 120_000 / 174_227)
        self.assertAlmostEqual(row[tea.FIELD_LCOO][0], 20_000 / 1_964)
        self.assertAlmostEqual(row["PVCost_SOL_USD"][0], 100_000)
        self.assertAlmostEqual(row["PVCost_SE_USD"][0], 120_000)
        self.assertEqual(row["PVEnergy_SOL_kWh_AC"][0], 172_263)
        self.assertEqual(row["PVEnergy_SE_kWh_AC"][0], 174_227)
        self.assertAlmostEqual(
            result.summaries[tea.APPLIED_FIELD_DELTA_ENERGY]["percentiles"]["p50"],
            1_964 / 125_000,
        )

        normalization = result.provenance["capacity_normalization"]
        self.assertEqual(normalization["method"], "annual_applied_capacity_v1")
        self.assertEqual(
            normalization["systems"]["solectria"],
            {
                "applied_capacity_w": 125_000.0,
                "rating_basis": "ac_operating_limit",
                "installed_wdc": GOLDEN_WDC,
            },
        )
        per_year = result.per_weather_year[0]
        self.assertEqual(per_year["solectria_applied_w"], 125_000)
        self.assertAlmostEqual(
            per_year["source_delta_specific_se_minus_sol_kwh_ac_per_applied_w_year"],
            1_964 / 125_000,
        )

    def test_v3_scales_the_illustrative_125_kw_source_to_100_mw(self):
        request = commercial_scaling_request()
        result = tea.run_technoeconomic(request)
        row = result.realization_table

        expected_energy = (174_227 - 172_263) / 125_000 * 100_000_000
        self.assertEqual(expected_energy, 1_571_200)
        self.assertEqual(
            row[tea.COMMERCIAL_FIELD_TARGET_CAPACITY][0],
            100_000_000,
        )
        self.assertEqual(
            row[tea.COMMERCIAL_FIELD_YEAR1_DELTA_ENERGY][0],
            expected_energy,
        )
        self.assertEqual(
            row[tea.COMMERCIAL_FIELD_LIFECYCLE_DELTA_ENERGY][0],
            expected_energy,
        )
        self.assertEqual(
            row[tea.COMMERCIAL_FIELD_EA_DELTA_ENERGY][0],
            expected_energy,
        )
        self.assertEqual(
            row[tea.COMMERCIAL_FIELD_LIFECYCLE_MARGINAL_COST][0],
            314_240,
        )
        self.assertEqual(
            row[tea.COMMERCIAL_FIELD_EA_MARGINAL_COST][0],
            314_240,
        )
        self.assertAlmostEqual(
            row[tea.COMMERCIAL_FIELD_MARGINAL_LCOO][0],
            0.2,
        )
        self.assertIsNone(
            row[tea.COMMERCIAL_FIELD_MARGINAL_LCOO_REASON][0]
        )

        v2_site_lcoo = tea.run_technoeconomic(
            applied_capacity_request()
        ).realization_table[tea.FIELD_LCOO][0]
        self.assertEqual(row[tea.FIELD_LCOO][0], v2_site_lcoo)
        self.assertEqual(
            result.summaries[tea.COMMERCIAL_FIELD_LIFECYCLE_DELTA_ENERGY][
                "percentiles"
            ]["p50"],
            expected_energy,
        )
        per_year = result.per_weather_year[0]
        self.assertEqual(
            per_year[
                "commercial_source_year1_delta_energy_se_minus_sol_kwh_ac"
            ],
            expected_energy,
        )
        self.assertEqual(
            per_year["metrics"][tea.COMMERCIAL_FIELD_MARGINAL_LCOO][
                "percentiles"
            ]["p50"],
            0.2,
        )
        provenance = result.provenance["commercial_scaling"]
        self.assertEqual(provenance["method"], "direct_capacity_scaling")
        self.assertEqual(provenance["target_rating_basis"], "ac_operating_limit")
        self.assertEqual(
            provenance["source_applied_capacities_w"],
            {"solectria": 125_000.0, "solaredge": 125_000.0},
        )

    def test_v3_cost_timing_conversions_produce_the_same_marginal_lcoo(self):
        discount_rate = 0.05
        lifecycle_cost = 1_000_000.0
        _, crf = tea.annuity_factor_and_crf(discount_rate, 20)
        common = {
            "project_life_years": 20,
            "discount_rate": fixed("finance.discount-rate", discount_rate),
            "shared_degradation": fixed("energy.shared-degradation", 0.005),
        }
        lifecycle_request = replace(
            commercial_scaling_request(marginal_cost=lifecycle_cost),
            **common,
        )
        annual_request = replace(
            commercial_scaling_request(
                marginal_cost=crf * lifecycle_cost,
                marginal_cost_timing="equivalent_annual",
            ),
            **common,
        )

        lifecycle = tea.run_technoeconomic(lifecycle_request).realization_table
        annual = tea.run_technoeconomic(annual_request).realization_table

        for table in (lifecycle, annual):
            self.assertAlmostEqual(
                table[tea.COMMERCIAL_FIELD_LIFECYCLE_MARGINAL_COST][0],
                lifecycle_cost,
            )
            self.assertAlmostEqual(
                table[tea.COMMERCIAL_FIELD_EA_MARGINAL_COST][0],
                crf * lifecycle_cost,
            )
        self.assertAlmostEqual(
            lifecycle[tea.COMMERCIAL_FIELD_MARGINAL_LCOO][0],
            annual[tea.COMMERCIAL_FIELD_MARGINAL_LCOO][0],
        )
        self.assertAlmostEqual(
            annual[tea.COMMERCIAL_FIELD_EA_MARGINAL_COST][0]
            / annual[tea.COMMERCIAL_FIELD_EA_DELTA_ENERGY][0],
            annual[tea.COMMERCIAL_FIELD_MARGINAL_LCOO][0],
        )

    def test_v3_normalizes_unequal_source_capacities_before_target_scaling(self):
        sol_capacity = capacity("solectria", installed_wdc=100_000)
        se_capacity = capacity("solaredge", installed_wdc=200_000)
        request = tea.TechnoeconomicRequest(
            basis="solartac_site",
            n=1,
            seed=1,
            project_life_years=1,
            capacities=(sol_capacity, se_capacity),
            applied_capacities=(
                tea.AppliedCapacitySpec(
                    "solectria", 100_000, "dc_installed_nameplate"
                ),
                tea.AppliedCapacitySpec(
                    "solaredge", 200_000, "dc_installed_nameplate"
                ),
            ),
            paired_energy_rows=(
                tea.PairedEnergyRow(2020, 1_000_000, 1_800_000),
            ),
            cost_lines=(
                cost_line(
                    "cost.sol.total", 100_000, "solectria_only", "initial_capex", 1 / 100_000, 0
                ),
                cost_line(
                    "cost.se.total", 180_000, "solaredge_only", "initial_capex", 0, 1 / 200_000
                ),
            ),
            discount_rate=fixed("finance.discount-rate", 0),
            shared_degradation=fixed("energy.shared-degradation", 0),
            commercial_scaling=tea.CommercialScalingSpec(
                target_capacity_w=3_000_000,
                target_rating_basis="dc_installed_nameplate",
                marginal_cost_difference=fixed(
                    tea.COMMERCIAL_MARGINAL_COST_DIFFERENCE_INPUT_ID,
                    150_000,
                ),
                marginal_cost_timing="lifecycle_present_value",
            ),
            calculation_contract_version=(
                tea.COMMERCIAL_SCALING_CALCULATION_CONTRACT_VERSION
            ),
        )

        row = tea.run_technoeconomic(request).realization_table

        self.assertEqual(row[tea.APPLIED_FIELD_YEAR1_SOL][0], 10)
        self.assertEqual(row[tea.APPLIED_FIELD_YEAR1_SE][0], 9)
        self.assertEqual(
            row[tea.COMMERCIAL_FIELD_YEAR1_DELTA_ENERGY][0],
            -3_000_000,
        )
        self.assertEqual(
            row[tea.COMMERCIAL_FIELD_LIFECYCLE_DELTA_ENERGY][0],
            -3_000_000,
        )
        self.assertEqual(
            row[tea.COMMERCIAL_FIELD_MARGINAL_LCOO][0],
            -0.05,
        )

    def test_v3_signed_cost_and_tolerance_zero_have_explicit_results(self):
        negative_cost = tea.run_technoeconomic(
            commercial_scaling_request(marginal_cost=-314_240)
        ).realization_table
        self.assertAlmostEqual(
            negative_cost[tea.COMMERCIAL_FIELD_MARGINAL_LCOO][0],
            -0.2,
        )

        exact_zero = replace(
            commercial_scaling_request(),
            paired_energy_rows=(
                tea.PairedEnergyRow(2021, 172_263.0, 172_263.0),
            ),
        )
        exact_result = tea.run_technoeconomic(exact_zero)
        exact_table = exact_result.realization_table
        self.assertEqual(
            exact_table[tea.COMMERCIAL_FIELD_LIFECYCLE_DELTA_ENERGY][0],
            0,
        )
        self.assertTrue(
            math.isnan(exact_table[tea.COMMERCIAL_FIELD_MARGINAL_LCOO][0])
        )
        self.assertEqual(
            exact_table[tea.COMMERCIAL_FIELD_MARGINAL_LCOO_REASON][0],
            tea.COMMERCIAL_ZERO_ENERGY_REASON,
        )
        self.assertEqual(
            exact_result.summaries[tea.COMMERCIAL_FIELD_MARGINAL_LCOO]["reason"],
            tea.COMMERCIAL_ZERO_ENERGY_REASON,
        )

        within_tolerance = replace(
            commercial_scaling_request(),
            paired_energy_rows=(
                tea.PairedEnergyRow(2021, 172_263.0, 172_263.0 + 1e-8),
            ),
        )
        tolerance_table = tea.run_technoeconomic(
            within_tolerance
        ).realization_table
        self.assertNotEqual(
            tolerance_table[tea.COMMERCIAL_FIELD_LIFECYCLE_DELTA_ENERGY][0],
            0,
        )
        self.assertEqual(tolerance_table["energy_class"][0], "zero_lifecycle_gain")
        self.assertTrue(
            math.isnan(tolerance_table[tea.COMMERCIAL_FIELD_MARGINAL_LCOO][0])
        )
        self.assertEqual(
            tolerance_table[tea.COMMERCIAL_FIELD_MARGINAL_LCOO_REASON][0],
            tea.COMMERCIAL_ZERO_ENERGY_REASON,
        )

    def test_v2_dc_nameplate_fallback_uses_installed_capacity(self):
        request = applied_capacity_request(
            applied_w=GOLDEN_WDC,
            rating_basis="dc_installed_nameplate",
        )
        result = tea.run_technoeconomic(request)
        row = result.realization_table

        self.assertAlmostEqual(
            row[tea.APPLIED_FIELD_YEAR1_DELTA][0],
            1_964 / GOLDEN_WDC,
        )
        self.assertEqual(
            result.provenance["capacity_normalization"]["systems"]["solaredge"][
                "rating_basis"
            ],
            "dc_installed_nameplate",
        )

    def test_public_signed_field_names_pin_order_and_units(self):
        self.assertEqual(
            tea.FIELD_YEAR1_DELTA,
            "Year1DeltaSpecificEnergy_se_minus_sol_kWh_AC_per_Wdc_year",
        )
        self.assertEqual(
            tea.FIELD_DELTA_COST,
            "DeltaLifecycleCostPerWdc_se_minus_sol_USD_per_Wdc",
        )
        self.assertEqual(
            tea.FIELD_DELTA_ENERGY,
            "DeltaLifecycleEnergyPerWdc_se_minus_sol_kWh_AC_per_Wdc",
        )
        self.assertEqual(
            tea.FIELD_DELTA_EA_COST,
            "DeltaEquivalentAnnualCostPerWdcYear_se_minus_sol_USD_per_Wdc_year",
        )
        self.assertEqual(
            tea.FIELD_DELTA_EA_ENERGY,
            "DeltaEquivalentAnnualEnergyPerWdcYear_se_minus_sol_kWh_AC_per_Wdc_year",
        )
        self.assertEqual(
            tea.FIELD_LCOO,
            "AllInLCOO_se_minus_sol_USD_per_kWh_AC",
        )
        self.assertEqual(
            (
                tea.COMMERCIAL_FIELD_TARGET_CAPACITY,
                tea.COMMERCIAL_FIELD_YEAR1_DELTA_ENERGY,
                tea.COMMERCIAL_FIELD_LIFECYCLE_DELTA_ENERGY,
                tea.COMMERCIAL_FIELD_EA_DELTA_ENERGY,
                tea.COMMERCIAL_FIELD_LIFECYCLE_MARGINAL_COST,
                tea.COMMERCIAL_FIELD_EA_MARGINAL_COST,
                tea.COMMERCIAL_FIELD_MARGINAL_LCOO,
            ),
            (
                "CommercialTargetCapacity_W",
                "CommercialYear1DeltaEnergy_se_minus_sol_kWh_AC",
                "CommercialLifecycleDeltaEnergy_se_minus_sol_kWh_AC",
                "CommercialEquivalentAnnualDeltaEnergy_se_minus_sol_kWh_AC_per_year",
                "CommercialLifecycleMarginalCostDelta_se_minus_sol_USD",
                "CommercialEquivalentAnnualMarginalCostDelta_se_minus_sol_USD_per_year",
                "CommercialMarginalLCOO_se_minus_sol_USD_per_kWh_AC",
            ),
        )

    def test_shared_streams_remain_in_lcoes_and_cancel_exactly_from_delta(self):
        result = tea.run_technoeconomic(golden_request())

        self.assertEqual(len(result.common_cost_audit), 5)
        for audit in result.common_cost_audit:
            self.assertEqual(audit["comparison_treatment"], "common_cancelled")
            self.assertTrue(audit["delta_contribution_se_minus_sol_exactly_zero"])
            self.assertEqual(audit["delta_contribution_min_se_minus_sol"], 0.0)
            self.assertEqual(audit["delta_contribution_max_se_minus_sol"], 0.0)
        shared_pv = 15_000 + 600 * 12.462210342539986
        self.assertAlmostEqual(shared_pv, 22_477.326205523994, places=8)

    def test_unimplemented_cost_treatments_are_rejected(self):
        lines = list(golden_cost_lines())
        shared = next(line for line in lines if line.input_id == "cost.shared.capex")
        lines[lines.index(shared)] = replace(
            shared,
            solaredge_treatment_key="different-timing-v1",
        )

        with self.assertRaisesRegex(tea.TechnoeconomicValidationError, "unsupported treatment"):
            tea.validate_request(golden_request(cost_lines=lines))

        both_unsupported = [
            replace(
                line,
                solectria_treatment_key="nominal-escalation-v9",
                solaredge_treatment_key="nominal-escalation-v9",
            )
            if line.input_id == shared.input_id
            else line
            for line in golden_cost_lines()
        ]
        with self.assertRaisesRegex(tea.TechnoeconomicValidationError, "constant-real-v1"):
            tea.validate_request(golden_request(cost_lines=both_unsupported))

    def test_huge_common_cost_cannot_erase_small_true_delta(self):
        lines = (
            cost_line(
                "cost.shared.huge",
                1e20,
                "paired_shared",
                "initial_capex",
                1,
                1,
                basis="commercial_representative",
            ),
            cost_line(
                "cost.sol.small",
                1,
                "solectria_only",
                "initial_capex",
                1,
                0,
                basis="commercial_representative",
            ),
            cost_line(
                "cost.se.small",
                2,
                "solaredge_only",
                "initial_capex",
                0,
                1,
                basis="commercial_representative",
            ),
        )

        result = tea.run_technoeconomic(commercial_request(transfer=False, costs=lines))

        self.assertEqual(result.realization_table[tea.FIELD_DELTA_COST][0], 1.0)
        self.assertEqual(result.realization_table["cost_class"][0], "cost_neutral")

    def test_negative_derived_cost_delta_is_valid(self):
        lines = (
            cost_line(
                "cost.sol.total",
                2,
                "solectria_only",
                "initial_capex",
                1,
                0,
                basis="commercial_representative",
            ),
            cost_line(
                "cost.se.total",
                1,
                "solaredge_only",
                "initial_capex",
                0,
                1,
                basis="commercial_representative",
            ),
        )

        result = tea.run_technoeconomic(commercial_request(transfer=False, costs=lines))

        self.assertEqual(result.realization_table[tea.FIELD_DELTA_COST][0], -1.0)
        self.assertEqual(result.realization_table["cost_class"][0], "cost_saving")

    def test_zero_energy_gain_is_retained_with_null_lcoo(self):
        result = tea.run_technoeconomic(golden_request(se_energy=200_000))
        row = result.realization_table

        self.assertEqual(len(row["realization_index"]), 1)
        self.assertEqual(row["energy_class"][0], "zero_lifecycle_gain")
        self.assertTrue(math.isnan(row[tea.FIELD_LCOO][0]))
        self.assertEqual(row["lcoo_unavailable_reason"][0], "zero_lifecycle_delta_energy")
        self.assertEqual(row["tradeoff_class"][0], "cost_increase_zero_energy_change")

    def test_tolerance_derived_classes_cover_the_complete_three_by_three_matrix(self):
        deltas = (1.0, 0.0, -1.0)
        observed = set()
        for cost_delta in deltas:
            for energy_delta in deltas:
                outcomes = tea._classify_outcomes(
                    np.array([100.0]),
                    np.array([100.0 + cost_delta]),
                    np.array([100.0]),
                    np.array([100.0 + energy_delta]),
                )
                observed.add(str(outcomes["tradeoff_class"][0]))
                if energy_delta == 0:
                    self.assertTrue(math.isnan(outcomes["lcoo"][0]))
                else:
                    self.assertAlmostEqual(
                        outcomes["lcoo"][0], cost_delta / energy_delta
                    )
        self.assertEqual(observed, set(tea.TRADEOFF_CLASSES))

        near_zero = tea._classify_outcomes(
            np.array([1.0]),
            np.array([1.0 + 5e-13]),
            np.array([100.0]),
            np.array([100.0 - 5e-10]),
        )
        self.assertEqual(near_zero["cost_class"][0], "cost_neutral")
        self.assertEqual(near_zero["energy_class"][0], "zero_lifecycle_gain")

    def test_negative_energy_gain_retains_signed_ratio_and_adverse_class(self):
        result = tea.run_technoeconomic(golden_request(se_energy=190_000))
        row = result.realization_table

        self.assertAlmostEqual(row["DeltaPVEnergyKWhAC_se_minus_sol"][0], -119_829.42252505501, places=7)
        self.assertAlmostEqual(row[tea.FIELD_LCOO][0], -0.27115579282470619, places=14)
        self.assertEqual(row["energy_class"][0], "negative_lifecycle_gain")
        self.assertEqual(row["tradeoff_class"][0], "cost_increase_energy_loss")

    def test_unequal_wdc_normalizes_before_differencing(self):
        sol_capacity = capacity("solectria", installed_wdc=100_000)
        se_capacity = capacity("solaredge", installed_wdc=200_000)
        lines = (
            cost_line("cost.sol.total", 100_000, "solectria_only", "initial_capex", 1 / 100_000, 0),
            cost_line("cost.se.total", 180_000, "solaredge_only", "initial_capex", 0, 1 / 200_000),
        )
        request = tea.TechnoeconomicRequest(
            basis="solartac_site",
            n=1,
            seed=1,
            project_life_years=1,
            capacities=(sol_capacity, se_capacity),
            paired_energy_rows=(tea.PairedEnergyRow(2020, 1_000_000, 1_800_000),),
            cost_lines=lines,
            discount_rate=fixed("finance.discount-rate", 0),
            shared_degradation=fixed("energy.shared-degradation", 0),
        )

        row = tea.run_technoeconomic(request).realization_table

        self.assertEqual(row["DeltaPVCostUSD_se_minus_sol"][0], 80_000)
        self.assertEqual(row["DeltaPVEnergyKWhAC_se_minus_sol"][0], 800_000)
        self.assertAlmostEqual(row[tea.FIELD_DELTA_COST][0], -0.1)
        self.assertAlmostEqual(row[tea.FIELD_DELTA_ENERGY][0], -1.0)
        self.assertAlmostEqual(row[tea.FIELD_LCOO][0], 0.1)
        self.assertEqual(row["tradeoff_class"][0], "cost_saving_energy_loss")

    def test_unequal_capacity_shared_totals_do_not_cancel_but_equal_intensity_does(self):
        sol_capacity = capacity("solectria", installed_wdc=100_000)
        se_capacity = capacity("solaredge", installed_wdc=200_000)
        lines = (
            cost_line(
                "cost.shared.total",
                20_000,
                "paired_shared",
                "initial_capex",
                1 / 100_000,
                1 / 200_000,
            ),
            cost_line(
                "cost.shared.intensity",
                0.20,
                "paired_shared",
                "recurring_om",
                1,
                1,
            ),
        )
        request = tea.TechnoeconomicRequest(
            basis="solartac_site",
            n=1,
            seed=1,
            project_life_years=1,
            capacities=(sol_capacity, se_capacity),
            paired_energy_rows=(tea.PairedEnergyRow(2020, 1_000_000, 1_800_000),),
            cost_lines=lines,
            discount_rate=fixed("finance.discount-rate", 0),
            shared_degradation=fixed("energy.shared-degradation", 0),
        )

        audits = {row["input_id"]: row for row in tea.run_technoeconomic(request).common_cost_audit}

        self.assertEqual(audits["cost.shared.total"]["comparison_treatment"], "shared_non_cancelling")
        self.assertAlmostEqual(
            audits["cost.shared.total"]["delta_contribution_min_se_minus_sol"],
            -0.1,
        )
        self.assertEqual(audits["cost.shared.intensity"]["comparison_treatment"], "common_cancelled")
        self.assertTrue(
            audits["cost.shared.intensity"][
                "delta_contribution_se_minus_sol_exactly_zero"
            ]
        )

    def test_commercial_transfer_fixture_keeps_baseline_and_incremental_separate(self):
        result = tea.run_technoeconomic(commercial_request())
        row = result.realization_table

        self.assertTrue(result.energy_available)
        self.assertAlmostEqual(row[tea.FIELD_YEAR1_SOL][0], 1.26)
        self.assertAlmostEqual(row[tea.FIELD_YEAR1_DELTA][0], 0.05)
        self.assertAlmostEqual(row[tea.FIELD_YEAR1_SE][0], 1.31)

    def test_commercial_without_transfer_is_explicit_cost_only(self):
        result = tea.run_technoeconomic(commercial_request(transfer=False))
        row = result.realization_table

        self.assertFalse(result.energy_available)
        self.assertTrue(math.isnan(row[tea.FIELD_LCOE_SOL][0]))
        self.assertTrue(math.isnan(row[tea.FIELD_DELTA_ENERGY][0]))
        self.assertTrue(math.isnan(row[tea.FIELD_LCOO][0]))
        self.assertEqual(result.summaries[tea.FIELD_LCOE_SOL]["reason"], "commercial_energy_transfer_unavailable")
        self.assertEqual(set(result.convergence["metric_absolute_tolerances"]), {tea.FIELD_DELTA_COST})

    def test_cost_only_commercial_reference_emits_cost_totals_without_fake_energy(self):
        request = replace(
            commercial_request(transfer=False),
            commercial_reference_wdc=1_000_000,
        )

        table = tea.run_technoeconomic(request).realization_table

        self.assertIn("ReferencePVCost_SOL_USD", table)
        self.assertIn("ReferenceDeltaPVCostUSD_se_minus_sol", table)
        self.assertNotIn("ReferencePVEnergy_SOL_kWh_AC", table)
        self.assertNotIn("ReferenceDeltaPVEnergyKWhAC_se_minus_sol", table)

    def test_all_four_distribution_families_flow_through_realizations(self):
        lines = list(golden_cost_lines())
        replacements = {
            "cost.sol.capex": tea.DistributionSpec(
                "cost.sol.capex", "uniform", low=90_000, high=110_000
            ),
            "cost.se.capex": tea.DistributionSpec(
                "cost.se.capex", "triangular", low=120_000, mode=130_000, high=145_000
            ),
            "cost.sol.om": tea.DistributionSpec(
                "cost.sol.om", "bounded_normal", low=1_500, high=2_500, mean=2_000, sd=200
            ),
        }
        lines = [
            replace(line, distribution=replacements.get(line.input_id, line.distribution))
            for line in lines
        ]
        request = replace(
            golden_request(n=64, cost_lines=lines),
            discount_rate=tea.DistributionSpec(
                "finance.discount-rate", "uniform", low=0.03, high=0.07
            ),
            shared_degradation=tea.DistributionSpec(
                "energy.shared-degradation",
                "bounded_normal",
                low=0.002,
                high=0.008,
                mean=0.005,
                sd=0.001,
            ),
        )

        result = tea.run_technoeconomic(request)

        self.assertEqual(len(result.realization_table["realization_index"]), 64)
        for identifier in replacements:
            self.assertGreater(np.ptp(result.sampled_inputs[identifier]), 0)
        # Provenance records the runtime that actually ran, not a literal: the
        # gate is the numerical fingerprint below, not a version string.
        self.assertEqual(result.provenance["numpy_version"], np.__version__)
        self.assertEqual(result.provenance["scipy_version"], scipy.__version__)
        numerics = result.provenance["numerics"]
        self.assertEqual(numerics["contract_version"], tea.NUMERICAL_CONTRACT_VERSION)
        self.assertEqual(numerics["probe_digests"], tea.NUMERICAL_PROBE_DIGESTS)
        self.assertEqual(
            numerics["bit_identical_to_reference"],
            numerics["exactness_digest"] == tea.NUMERICAL_EXACTNESS_DIGEST,
        )

    def test_headline_lcoo_population_is_positive_gain_only(self):
        rows = (
            tea.PairedEnergyRow(2019, 200_000, 215_000),
            tea.PairedEnergyRow(2020, 200_000, 200_000),
            tea.PairedEnergyRow(2021, 200_000, 190_000),
        )
        result = tea.run_technoeconomic(golden_request(n=3, rows=rows))

        self.assertEqual(result.summaries["headline_positive_gain_lcoo"]["count"], 1)
        self.assertEqual(result.summaries["signed_nonzero_lcoo"]["count"], 2)
        self.assertEqual(
            result.summaries["energy_classes"]["counts"],
            {
                "positive_lifecycle_gain": 1,
                "zero_lifecycle_gain": 1,
                "negative_lifecycle_gain": 1,
            },
        )


class SummaryAndSensitivityTests(unittest.TestCase):
    def test_ecdf_is_right_continuous_for_ties(self):
        cdf = tea.empirical_cdf([1, 1, 2])

        self.assertEqual(cdf["values"], [1.0, 2.0])
        self.assertEqual(cdf["cumulative_count"], [2, 3])
        np.testing.assert_allclose(cdf["cumulative_probability"], [2 / 3, 1])

    def test_type7_percentiles_have_pinned_two_point_values(self):
        self.assertEqual(
            tea.type7_percentiles([0, 10]),
            {"p5": 0.5, "p50": 5.0, "p95": 9.5},
        )

    def test_per_year_summary_keeps_year_with_zero_assignments(self):
        rows = (
            tea.PairedEnergyRow(2019, 190_000, 200_000),
            tea.PairedEnergyRow(2020, 200_000, 210_000),
            tea.PairedEnergyRow(2021, 210_000, 220_000),
        )
        result = tea.run_technoeconomic(golden_request(n=2, rows=rows))

        self.assertEqual([row["year"] for row in result.per_weather_year], [2019, 2020, 2021])
        zero_rows = [row for row in result.per_weather_year if row["realization_count"] == 0]
        self.assertEqual(len(zero_rows), 1)
        self.assertEqual(zero_rows[0]["reason"], "no_realizations_assigned")
        self.assertIsNone(zero_rows[0]["metrics"][tea.FIELD_DELTA_COST]["percentiles"]["p50"])

    def test_rank_regression_recovers_positive_monotonic_predictor(self):
        x = np.linspace(-2, 2, 40)
        result = tea.stepwise_rank_regression(x**3, {"input.x": x})

        self.assertEqual(result["status"], "available")
        self.assertEqual(result["steps"][0]["predictor_id"], "input.x")
        self.assertAlmostEqual(result["steps"][0]["incremental_r_squared"], 1.0)
        self.assertAlmostEqual(result["steps"][0]["standardized_beta"], 1.0)
        self.assertEqual(result["steps"][0]["sign"], "positive")

    def test_rank_regression_reports_negative_beta(self):
        x = np.arange(40, dtype=float)
        result = tea.stepwise_rank_regression(-x, {"input.x": x})

        self.assertAlmostEqual(result["final_r_squared"], 1.0)
        self.assertAlmostEqual(result["steps"][0]["standardized_beta"], -1.0)
        self.assertEqual(result["steps"][0]["sign"], "negative")

    def test_rank_regression_uses_stable_tie_and_excludes_rank_redundancy(self):
        x = np.arange(40, dtype=float)
        result = tea.stepwise_rank_regression(
            x,
            {
                "input.b": -x,
                "input.a": x,
                "input.duplicate": x.copy(),
            },
        )

        self.assertEqual(result["steps"][0]["predictor_id"], "input.a")
        self.assertEqual(result["exclusions"]["input.duplicate"]["reason"], "duplicate_rank")
        self.assertEqual(result["exclusions"]["input.b"]["reason"], "rank_singular")

    def test_rank_regression_reports_insufficient_and_constant_responses(self):
        insufficient = tea.stepwise_rank_regression(
            np.arange(19), {"input.x": np.arange(19)}
        )
        constant = tea.stepwise_rank_regression(
            np.ones(30), {"input.x": np.arange(30)}
        )

        self.assertEqual(insufficient["reason"], "insufficient_observations")
        self.assertEqual(constant["reason"], "constant_response")

    def test_kernel_sensitivity_excludes_fixed_and_common_cancelled_inputs(self):
        lines = list(golden_cost_lines())
        capex = next(line for line in lines if line.input_id == "cost.se.capex")
        lines[lines.index(capex)] = replace(
            capex,
            distribution=tea.DistributionSpec(
                "cost.se.capex", "uniform", low=120_000, high=140_000
            ),
        )
        rows = (
            tea.PairedEnergyRow(2019, 190_000, 203_000),
            tea.PairedEnergyRow(2020, 205_000, 222_000),
        )
        result = tea.run_technoeconomic(golden_request(n=64, rows=rows, cost_lines=lines))
        model = result.sensitivity["lifecycle_cost_delta_se_minus_sol"]

        self.assertEqual(model["status"], "available")
        self.assertEqual(model["steps"][0]["predictor_id"], "cost.se.capex")
        self.assertEqual(model["exclusions"]["cost.shared.capex"]["reason"], "no_structural_effect")
        self.assertEqual(model["exclusions"]["finance.discount-rate"]["reason"], "fixed_input")

    def test_cost_delta_sensitivity_excludes_finance_for_initial_only_costs(self):
        costs = (
            cost_line(
                "cost.sol.total",
                tea.DistributionSpec("cost.sol.total", "uniform", low=0.8, high=1.2),
                "solectria_only",
                "initial_capex",
                1,
                0,
                basis="commercial_representative",
            ),
            cost_line(
                "cost.se.total",
                tea.DistributionSpec("cost.se.total", "uniform", low=1.0, high=1.4),
                "solaredge_only",
                "initial_capex",
                0,
                1,
                basis="commercial_representative",
            ),
        )
        request = replace(
            commercial_request(n=40, transfer=False, costs=costs),
            project_life_years=20,
            discount_rate=tea.DistributionSpec(
                "finance.discount-rate", "uniform", low=0.02, high=0.08
            ),
        )

        model = tea.run_technoeconomic(request).sensitivity[
            "lifecycle_cost_delta_se_minus_sol"
        ]

        self.assertEqual(model["status"], "available")
        self.assertEqual(
            model["exclusions"]["finance.discount-rate"]["reason"],
            "no_structural_effect",
        )

    def test_recurring_only_zero_degradation_lcoe_excludes_finance(self):
        costs = (
            cost_line(
                "cost.sol.om.a",
                tea.DistributionSpec("cost.sol.om.a", "uniform", low=0.3, high=0.5),
                "solectria_only",
                "recurring_om",
                1,
                0,
                basis="commercial_representative",
            ),
            cost_line(
                "cost.sol.om.b",
                tea.DistributionSpec("cost.sol.om.b", "uniform", low=0.2, high=0.4),
                "solectria_only",
                "recurring_maintenance",
                1,
                0,
                basis="commercial_representative",
            ),
            cost_line(
                "cost.se.om.a",
                tea.DistributionSpec("cost.se.om.a", "uniform", low=0.4, high=0.6),
                "solaredge_only",
                "recurring_om",
                0,
                1,
                basis="commercial_representative",
            ),
            cost_line(
                "cost.se.om.b",
                tea.DistributionSpec("cost.se.om.b", "uniform", low=0.2, high=0.4),
                "solaredge_only",
                "recurring_maintenance",
                0,
                1,
                basis="commercial_representative",
            ),
        )
        request = replace(
            commercial_request(n=40, costs=costs),
            project_life_years=20,
            discount_rate=tea.DistributionSpec(
                "finance.discount-rate", "uniform", low=0.02, high=0.08
            ),
            shared_degradation=fixed("energy.shared-degradation", 0),
        )

        sensitivity = tea.run_technoeconomic(request).sensitivity

        for response in ("lifecycle_lcoe_solectria", "lifecycle_lcoe_solaredge"):
            self.assertEqual(
                sensitivity[response]["exclusions"]["finance.discount-rate"]["reason"],
                "no_structural_effect",
            )

    def test_one_year_sensitivity_excludes_degradation(self):
        costs = (
            cost_line(
                "cost.sol.total",
                tea.DistributionSpec("cost.sol.total", "uniform", low=0.8, high=1.2),
                "solectria_only",
                "initial_capex",
                1,
                0,
                basis="commercial_representative",
            ),
            cost_line(
                "cost.se.total",
                tea.DistributionSpec("cost.se.total", "uniform", low=1.0, high=1.4),
                "solaredge_only",
                "initial_capex",
                0,
                1,
                basis="commercial_representative",
            ),
        )
        request = replace(
            commercial_request(n=40, costs=costs),
            shared_degradation=tea.DistributionSpec(
                "energy.shared-degradation", "uniform", low=0.001, high=0.01
            ),
        )

        result = tea.run_technoeconomic(request)

        for name in (
            "lifecycle_lcoe_solectria",
            "lifecycle_lcoe_solaredge",
            "lifecycle_energy_delta_se_minus_sol",
            "headline_positive_gain_lcoo_se_minus_sol",
        ):
            self.assertEqual(
                result.sensitivity[name]["exclusions"]["energy.shared-degradation"]["reason"],
                "no_structural_effect",
            )

    def test_stepwise_tie_tolerance_cannot_weaken_entry_threshold(self):
        selected = tea._select_stepwise_candidate(
            [
                ("input.a", 0.9999995e-6, 0.9999995e-6),
                ("input.b", 1.0000004e-6, 1.0000004e-6),
            ],
            1e-6,
            1e-12,
        )

        self.assertEqual(selected[0], "input.b")

    def test_result_provenance_freezes_convergence_thresholds_and_units(self):
        provenance = tea.run_technoeconomic(golden_request()).provenance

        self.assertEqual(
            provenance["convergence_contract"]["absolute_quantile_tolerances"],
            {
                "lcoe_and_lcoo_USD_per_kWh_AC": 0.0001,
                "lifecycle_cost_USD_per_Wdc": 0.0001,
                "lifecycle_energy_kWh_AC_per_Wdc": 0.0001,
            },
        )


class ConvergenceContractTests(unittest.TestCase):
    def test_checkpoints_are_clamped_sorted_and_unique(self):
        self.assertEqual(tea.convergence_checkpoints(1), (1,))
        self.assertEqual(tea.convergence_checkpoints(20), (2, 5, 10, 15, 20))
        self.assertEqual(tea.convergence_checkpoints(100), (10, 20, 25, 50, 75, 100))

    def test_one_checkpoint_is_not_demonstrated(self):
        result = tea.convergence_diagnostics(
            {"metric": np.array([1.0])},
            {"metric": 0.0001},
            [2020],
            [2020],
        )

        self.assertEqual(result["status"], "not_demonstrated")
        self.assertIn("insufficient_unique_checkpoints", result["reasons"])

    def test_constant_metric_and_classes_are_stable(self):
        n = 100
        result = tea.convergence_diagnostics(
            {"metric": np.ones(n)},
            {"metric": 0.0001},
            np.full(n, 2020),
            [2020],
            energy_classes=np.full(n, "positive_lifecycle_gain", dtype=object),
            tradeoff_classes=np.full(n, "cost_increase_energy_gain", dtype=object),
        )

        self.assertEqual(result["status"], "stable")
        self.assertEqual(result["reasons"], [])

    def test_final_relative_quantile_shift_is_not_demonstrated(self):
        values = np.concatenate([np.ones(75), np.full(25, 2.0)])
        result = tea.convergence_diagnostics(
            {"metric": values},
            {"metric": 0.0001},
            np.full(100, 2020),
            [2020],
        )

        self.assertEqual(result["status"], "not_demonstrated")
        self.assertTrue(any(reason.startswith("relative_quantile_change") for reason in result["reasons"]))

    def test_near_zero_metric_uses_absolute_threshold(self):
        values = np.concatenate([np.zeros(75), np.full(25, 0.00005)])
        result = tea.convergence_diagnostics(
            {"metric": values},
            {"metric": 0.0001},
            np.full(100, 2020),
            [2020],
        )

        self.assertEqual(result["status"], "stable")

    def test_missing_weather_and_undefined_conditional_metric_are_explicit(self):
        missing_weather = tea.convergence_diagnostics(
            {"metric": np.ones(20)},
            {"metric": 0.0001},
            np.full(20, 2020),
            [2020, 2021],
        )
        undefined = tea.convergence_diagnostics(
            {"headline": np.full(20, np.nan)},
            {"headline": 0.0001},
            np.full(20, 2020),
            [2020],
        )

        self.assertIn("weather_year_unrepresented:2021", missing_weather["reasons"])
        self.assertIn("undefined_quantile:headline:p50", undefined["reasons"])


class ReproducibilityTests(unittest.TestCase):
    def test_reordered_cost_lines_produce_identical_numeric_and_class_tables(self):
        lines = list(golden_cost_lines())
        first = lines[0]
        second = lines[2]
        lines[0] = replace(
            first,
            distribution=tea.DistributionSpec(
                first.input_id, "uniform", low=90_000, high=110_000
            ),
        )
        lines[2] = replace(
            second,
            distribution=tea.DistributionSpec(
                second.input_id, "triangular", low=120_000, mode=130_000, high=140_000
            ),
        )
        rows = (
            tea.PairedEnergyRow(2019, 190_000, 203_000),
            tea.PairedEnergyRow(2020, 205_000, 222_000),
        )

        forward = tea.run_technoeconomic(
            golden_request(n=64, seed=123, rows=rows, cost_lines=lines)
        )
        reverse = tea.run_technoeconomic(
            golden_request(n=64, seed=123, rows=tuple(reversed(rows)), cost_lines=tuple(reversed(lines)))
        )

        self.assertEqual(list(forward.realization_table), list(reverse.realization_table))
        for name in forward.realization_table:
            left = forward.realization_table[name]
            right = reverse.realization_table[name]
            if left.dtype.kind in "f":
                np.testing.assert_array_equal(left, right)
            else:
                np.testing.assert_array_equal(left, right)
        self.assertEqual(forward.provenance, reverse.provenance)


if __name__ == "__main__":
    unittest.main()
