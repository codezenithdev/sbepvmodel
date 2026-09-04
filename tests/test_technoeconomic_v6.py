import calendar
import unittest
from collections import Counter
from dataclasses import replace
from unittest.mock import patch

import numpy as np

from sbepv import technoeconomic as tea


def fixed(input_id, value):
    return tea.DistributionSpec(input_id=input_id, family="fixed", value=value)


EVIDENCE = {"status": "evidenced", "source": "hand-calculated-test"}


def capacity(system):
    return tea.CapacitySpec(
        system=system,
        module_model="v6-test-module",
        module_stc_wdc=10.0,
        strings=2,
        bays_per_string=5,
        modules_per_bay=1,
        module_count=10,
        installed_wdc=100.0,
        physics_version="physics-v1",
        physics_fingerprint="a" * 64,
    )


def component(system, *, eta=1e12, count=2, initial_spares=1, spare_target=1):
    prefix = f"lifecycle.{system}.inverter"
    return tea.LifecycleComponentSpec(
        component_id="inverter",
        category="inverter",
        count=count,
        capacity_impact=0.5,
        weibull_beta=fixed(f"{prefix}.weibull-beta", 1.0),
        weibull_eta_years=fixed(f"{prefix}.weibull-eta", eta),
        repair_hours=fixed(f"{prefix}.repair-hours", 1.0),
        logistics_hours=fixed(f"{prefix}.logistics-hours", 2.0),
        emergency_unit_cost=fixed(f"{prefix}.emergency-cost", 20.0),
        restock_unit_cost=fixed(f"{prefix}.restock-cost", 10.0),
        labor_cost=fixed(f"{prefix}.labor-cost", 3.0),
        mobilization_cost=fixed(f"{prefix}.mobilization-cost", 4.0),
        real_cost_growth=fixed(f"{prefix}.cost-growth", 0.0),
        batch_size=2,
        initial_spares=initial_spares,
        spare_target=spare_target,
        warranty=None,
        preventive_replacements=(),
        coverage_ids=(f"coverage.{system}.inverter",),
        evidence=EVIDENCE,
    )


def lifecycle_system(system, *, initial_cost_per_w, degradation=0.0, eta=1e12):
    prefix = f"lifecycle.{system}"
    return tea.LifecycleSystemSpec(
        technology=system,
        degradation=fixed(f"{prefix}.degradation", degradation),
        base_availability=fixed(f"{prefix}.base-availability", 1.0),
        base_om_cost_per_w_year=fixed(f"{prefix}.base-om", 0.01),
        base_om_real_growth=fixed(f"{prefix}.base-om-growth", 0.0),
        initial_cost_lines=(
            tea.LifecycleInitialCostLineSpec(
                input_id=f"{prefix}.initial",
                label=f"{system} initial",
                cost_per_w=fixed(f"{prefix}.initial", initial_cost_per_w),
                coverage_ids=(f"coverage.{system}.initial",),
                evidence=EVIDENCE,
            ),
        ),
        scheduled_costs=(),
        components=(component(system, eta=eta),),
        decommissioning_cost=fixed(f"{prefix}.decommissioning", 0.0),
        salvage_value=fixed(f"{prefix}.salvage", 0.0),
        source_availability_by_year=(),
        base_om_coverage_ids=(f"coverage.{system}.base-om",),
        evidence=EVIDENCE,
    )


def request(*, n=20, seed=7, life=2, eta=1e12, reliability_mode="event"):
    return tea.TechnoeconomicRequest(
        basis="solartac_site",
        n=n,
        seed=seed,
        project_life_years=life,
        capacities=(capacity("solectria"), capacity("solaredge")),
        applied_capacities=(
            tea.AppliedCapacitySpec("solectria", 100.0, "ac_operating_limit"),
            tea.AppliedCapacitySpec("solaredge", 100.0, "ac_operating_limit"),
        ),
        paired_energy_rows=(
            tea.PairedEnergyRow(2021, 1_000.0, 1_100.0),
        ),
        cost_lines=(),
        discount_rate=fixed("lifecycle.finance.discount-rate", 0.0),
        shared_degradation=None,
        calculation_contract_version=tea.LIFECYCLE_CALCULATION_CONTRACT_VERSION,
        sampling_version=tea.LIFECYCLE_SAMPLING_VERSION,
        constant_dollar_cost_year=2026,
        paired_lifecycle=tea.PairedLifecycleSpec(
            target_capacity_w=100.0,
            target_rating_basis="ac_operating_limit",
            source_energy_basis="gross",
            reliability_mode=reliability_mode,
            systems=(
                lifecycle_system("solectria", initial_cost_per_w=1.0, eta=eta),
                lifecycle_system("solaredge", initial_cost_per_w=1.1, eta=eta),
            ),
            electricity_value=fixed("lifecycle.electricity.value", 0.1),
            electricity_value_real_growth=fixed(
                "lifecycle.electricity.growth",
                0.0,
            ),
            electricity_value_evidence=EVIDENCE,
        ),
    )


class LifecycleV6ContractTests(unittest.TestCase):
    def test_v6_is_additive_and_old_payload_shapes_are_unchanged(self):
        legacy = tea.TechnoeconomicRequest(
            basis="solartac_site",
            n=1,
            seed=1,
            project_life_years=1,
            capacities=(capacity("solectria"), capacity("solaredge")),
            paired_energy_rows=(tea.PairedEnergyRow(2021, 1.0, 1.0),),
            cost_lines=(),
            discount_rate=fixed("finance.discount", 0.0),
            shared_degradation=fixed("energy.degradation", 0.0),
        )
        self.assertNotIn("paired_lifecycle", tea.canonical_request_payload(legacy))
        payload = tea.canonical_request_payload(request())
        self.assertIn("paired_lifecycle", payload)
        self.assertEqual(payload["sampling_version"], "tea-lhs-v2")

    def test_balanced_yearwise_weather_is_reproducible_and_paired(self):
        first = tea.allocate_weather_paths_v2(11, 123, [2020, 2021, 2022], 4)
        second = tea.allocate_weather_paths_v2(11, 123, [2020, 2021, 2022], 4)
        np.testing.assert_array_equal(first, second)
        self.assertEqual(first.shape, (11, 4))
        for project_year in range(4):
            counts = Counter(first[:, project_year].tolist())
            self.assertLessEqual(max(counts.values()) - min(counts.values()), 1)
        self.assertFalse(np.array_equal(first[:, 0], first[:, 1]))

    def test_v2_sampling_and_event_streams_have_golden_vectors(self):
        weather = tea.allocate_weather_paths_v2(
            7,
            20260903,
            [2019, 2020, 2021],
            3,
        )
        np.testing.assert_array_equal(
            weather,
            np.asarray(
                [
                    [2019, 2019, 2019],
                    [2020, 2021, 2020],
                    [2021, 2020, 2020],
                    [2021, 2021, 2019],
                    [2019, 2019, 2021],
                    [2019, 2020, 2021],
                    [2020, 2019, 2019],
                ],
                dtype=np.int64,
            ),
        )
        uniform = tea.DistributionSpec(
            "v6.golden.uniform",
            "uniform",
            low=0.0,
            high=1.0,
        )
        np.testing.assert_array_equal(
            tea.generate_lhs_v2(5, 20260903, [uniform])[uniform.input_id],
            np.asarray(
                [
                    0.35691535810130076,
                    0.50633554543902071,
                    0.9739078439347173,
                    0.75026253128213161,
                    0.18543109184528334,
                ]
            ),
        )
        generator = np.random.Generator(
            tea._lifecycle_substream(
                20260903,
                "component-binomial",
                "solectria.inverter.t0001.a0000",
            )
        )
        np.testing.assert_array_equal(
            generator.binomial(np.full(6, 10), np.full(6, 0.1)),
            np.asarray([2, 1, 0, 0, 0, 1]),
        )

    def test_hand_calculated_zero_rate_upgrade_npv_and_formulas(self):
        result = tea.run_technoeconomic(request())
        table = result.realization_table
        # Initial spare inventory is equal on both sides.  Delta initial cost is
        # $10; each of two years gains 100 kWh worth $10, so NPV is +$10.
        np.testing.assert_allclose(
            table["UpgradeNPV_se_minus_sol_USD"],
            10.0,
            rtol=0.0,
            atol=1e-8,
        )
        self.assertEqual(result.provenance["result_version"], "tea-result-v6")
        self.assertEqual(result.provenance["formula_registry"]["count"], 28)
        self.assertEqual(
            result.provenance["formula_registry"]["sha256"],
            tea.formula_registry_hash(),
        )
        self.assertIn(
            "SampledInput::lifecycle.finance.discount-rate",
            table,
        )
        self.assertEqual(
            result.summaries["headline_decision"]["decision"],
            "SolarEdge preferred",
        )
        self.assertEqual(
            result.summaries["probability_counts"]["upgrade_npv"]["positive"],
            20,
        )

    def test_real_om_growth_and_separate_degradation_are_hand_calculated(self):
        base = request(life=3)
        lifecycle = base.paired_lifecycle
        so_system, se_system = lifecycle.systems
        so_system = replace(
            so_system,
            degradation=fixed(so_system.degradation.input_id, 0.01),
            base_om_real_growth=fixed(
                so_system.base_om_real_growth.input_id,
                0.10,
            ),
        )
        se_system = replace(
            se_system,
            degradation=fixed(se_system.degradation.input_id, 0.02),
        )
        result = tea.run_technoeconomic(
            replace(
                base,
                paired_lifecycle=replace(
                    lifecycle,
                    systems=(so_system, se_system),
                ),
            )
        )
        annual = result.summaries["representative_event_traces"]["annual"]
        so_rows = [
            row
            for row in annual
            if row["selection_label"] == "NPV-P50"
            and row["system"] == "solectria"
        ]
        se_rows = [
            row
            for row in annual
            if row["selection_label"] == "NPV-P50"
            and row["system"] == "solaredge"
        ]
        np.testing.assert_allclose(
            [row["degradation_factor"] for row in so_rows],
            [1.0, 0.99, 0.99**2],
            rtol=0.0,
            atol=1e-14,
        )
        np.testing.assert_allclose(
            [row["degradation_factor"] for row in se_rows],
            [1.0, 0.98, 0.98**2],
            rtol=0.0,
            atol=1e-14,
        )
        np.testing.assert_allclose(
            [row["base_om_cost_usd"] for row in so_rows],
            [1.0, 1.1, 1.21],
            rtol=0.0,
            atol=1e-14,
        )

    def test_shared_common_cause_uses_one_event_draw_for_both_systems(self):
        base = request(n=40, life=3)
        lifecycle = base.paired_lifecycle
        shared_event = tea.LifecycleCommonCauseSpec(
            event_id="shared-grid-event",
            annual_probability=fixed("lifecycle.common.grid.probability", 0.5),
            downtime_hours=fixed("lifecycle.common.grid.downtime-hours", 24.0),
            capacity_impact=1.0,
            cost_per_event=fixed("lifecycle.common.grid.cost", 12.0),
            real_cost_growth=fixed("lifecycle.common.grid.growth", 0.0),
            affected_systems=("solectria", "solaredge"),
            coverage_ids=("coverage.common.grid",),
            evidence=EVIDENCE,
        )
        common_request = replace(
            base,
            paired_lifecycle=replace(
                lifecycle,
                common_cause_events=(shared_event,),
            ),
        )
        validated = tea.validate_request(common_request)
        samples = tea.generate_lhs_v2(
            validated.n,
            validated.seed,
            tea._v6_distribution_specs(validated),
        )
        weather = tea.allocate_weather_paths_v2(
            validated.n,
            validated.seed,
            [row.year for row in validated.paired_energy_rows],
            validated.project_life_years,
        )
        hours = np.where(
            np.vectorize(calendar.isleap, otypes=[bool])(weather),
            8784.0,
            8760.0,
        )
        simulated = tea._v6_common_cause_simulation(
            validated,
            samples,
            hours,
        )
        np.testing.assert_array_equal(
            simulated["event_availability"]["solectria"],
            simulated["event_availability"]["solaredge"],
        )
        np.testing.assert_array_equal(
            simulated["event_cost"]["solectria"],
            simulated["event_cost"]["solaredge"],
        )
        event_draws = simulated["details"]["shared-grid-event"]["event"]
        self.assertGreater(np.count_nonzero(event_draws), 0)
        self.assertLess(np.count_nonzero(event_draws), event_draws.size)

    def test_seeded_event_failures_are_reproducible_and_expected_is_diagnostic(self):
        stochastic = request(n=100, seed=987, life=3, eta=1.5)
        first = tea.run_technoeconomic(stochastic)
        second = tea.run_technoeconomic(stochastic)
        np.testing.assert_array_equal(
            first.realization_table["EventUpgradeNPV_se_minus_sol_USD"],
            second.realization_table["EventUpgradeNPV_se_minus_sol_USD"],
        )
        self.assertIn("event_sampling_diagnostic", first.sensitivity)
        traces = first.summaries["representative_event_traces"]
        self.assertEqual(
            [row["selection_label"] for row in traces["selection"]],
            ["NPV-P10", "NPV-P50", "NPV-P90"],
        )
        self.assertTrue(traces["components"])
        for selection in traces["selection"]:
            label = selection["selection_label"]
            realization_index = selection["realization_index"]
            self.assertGreaterEqual(realization_index, 1)
            self.assertEqual(
                first.realization_table["realization_index"][realization_index - 1],
                realization_index,
            )
            self.assertEqual(
                first.realization_table["EventUpgradeNPV_se_minus_sol_USD"][realization_index - 1],
                selection["upgrade_npv_usd"],
            )
            self.assertEqual(
                {
                    row["realization_index"]
                    for row in traces["annual"]
                    if row["selection_label"] == label
                },
                {realization_index},
            )
            final_annual = next(
                row
                for row in traces["annual"]
                if row["selection_label"] == label
                and row["system"] == "solectria"
                and row["project_year"] == stochastic.project_life_years
            )
            self.assertAlmostEqual(
                final_annual["cumulative_upgrade_npv_usd"],
                selection["upgrade_npv_usd"],
                places=7,
            )
            self.assertEqual(
                {
                    row["realization_index"]
                    for row in traces["components"]
                    if row["selection_label"] == label
                },
                {realization_index},
            )

    def test_weibull_beta_one_matches_exponential_and_general_beta(self):
        eta = np.asarray([5.0, 5.0])
        beta_one = tea._v6_weibull_probability(np.asarray([1.0, 1.0]), eta, 3)
        np.testing.assert_allclose(
            beta_one,
            1.0 - np.exp(-1.0 / eta),
            rtol=1e-14,
            atol=0.0,
        )
        beta_two = tea._v6_weibull_probability(np.asarray([2.0, 2.0]), eta, 3)
        expected = 1.0 - np.exp(-(((4.0 / eta) ** 2) - ((3.0 / eta) ** 2)))
        np.testing.assert_allclose(beta_two, expected, rtol=1e-14, atol=0.0)

    def test_spares_warranty_and_preventive_ordering_tie_to_traces(self):
        base = request(n=20, life=2, eta=1e-9)
        lifecycle = base.paired_lifecycle
        so_system, se_system = lifecycle.systems
        so_component = replace(
            so_system.components[0],
            warranty=tea.LifecycleWarrantySpec(
                age_limit_years=1,
                fraction=0.5,
                covered_cost_categories=("hardware", "labor", "mobilization"),
                coverage_ids=("coverage.solectria.inverter.warranty",),
                evidence=EVIDENCE,
            ),
        )
        so_system = replace(so_system, components=(so_component,))
        result = tea.run_technoeconomic(
            replace(base, paired_lifecycle=replace(lifecycle, systems=(so_system, se_system)))
        )
        trace = next(
            row
            for row in result.summaries["representative_event_traces"]["components"]
            if row["selection_label"] == "NPV-P50"
            and row["system"] == "solectria"
            and row["project_year"] == 1
            and row["cohort_age"] == 0
        )
        self.assertEqual(trace["event_failures"], 2)
        self.assertEqual(trace["stocked_replacements"], 1)
        self.assertEqual(trace["emergency_replacements"], 1)
        self.assertEqual(trace["restock_quantity"], 1)
        # Gross corrective cost is 1*$20 + 1*$10 + 2*$3 + 1*$4 = $40;
        # all failures are age-covered, so the 50% warranty credit is $20.
        self.assertAlmostEqual(trace["warranty_credit_usd"], 20.0)
        self.assertAlmostEqual(trace["corrective_cost_usd"], 20.0)

        preventive_base = request(n=20, life=2, eta=1e12)
        lifecycle = preventive_base.paired_lifecycle
        so_system, se_system = lifecycle.systems
        scheduled = tea.LifecyclePreventiveReplacementSpec(
            year=2,
            quantity=1,
            coverage_ids=("coverage.solectria.inverter.preventive.y2",),
            evidence=EVIDENCE,
        )
        so_component = replace(
            so_system.components[0],
            preventive_replacements=(scheduled,),
        )
        preventive_result = tea.run_technoeconomic(
            replace(
                preventive_base,
                paired_lifecycle=replace(
                    lifecycle,
                    systems=(replace(so_system, components=(so_component,)), se_system),
                ),
            )
        )
        oldest = next(
            row
            for row in preventive_result.summaries["representative_event_traces"]["components"]
            if row["selection_label"] == "NPV-P50"
            and row["system"] == "solectria"
            and row["project_year"] == 2
            and row["cohort_age"] == 1
        )
        self.assertEqual(oldest["preventive_replacements"], 1)

    def test_net_source_availability_correction_is_not_clamped(self):
        gross = request(n=20)
        lifecycle = gross.paired_lifecycle
        availability = (
            tea.LifecycleSourceAvailabilitySpec(2021, 0.5, EVIDENCE),
        )
        systems = tuple(
            replace(system, source_availability_by_year=availability)
            for system in lifecycle.systems
        )
        net = replace(
            gross,
            paired_lifecycle=replace(
                lifecycle,
                source_energy_basis="net",
                systems=systems,
            ),
        )
        result = tea.run_technoeconomic(net)
        np.testing.assert_allclose(
            result.realization_table["LifecyclePVEnergy_SOL_kWh_AC"],
            4_000.0,
            rtol=0.0,
            atol=1e-8,
        )
        trace = next(
            row
            for row in result.summaries["representative_event_traces"]["annual"]
            if row["selection_label"] == "NPV-P50"
            and row["system"] == "solectria"
            and row["project_year"] == 1
        )
        self.assertEqual(trace["availability_adjustment"], 2.0)

    def test_terminal_decommissioning_and_salvage_keep_their_signs(self):
        base = request(life=2)
        lifecycle = base.paired_lifecycle
        so_system, se_system = lifecycle.systems
        so_system = replace(
            so_system,
            decommissioning_cost=fixed(
                so_system.decommissioning_cost.input_id,
                30.0,
            ),
            salvage_value=fixed(so_system.salvage_value.input_id, 10.0),
        )
        se_system = replace(
            se_system,
            decommissioning_cost=fixed(
                se_system.decommissioning_cost.input_id,
                5.0,
            ),
            salvage_value=fixed(se_system.salvage_value.input_id, 15.0),
        )
        result = tea.run_technoeconomic(
            replace(
                base,
                paired_lifecycle=replace(
                    lifecycle,
                    systems=(so_system, se_system),
                ),
            )
        )
        np.testing.assert_allclose(
            result.realization_table["LifecyclePVCost_SOL_USD"],
            132.0,
            rtol=0.0,
            atol=1e-8,
        )
        np.testing.assert_allclose(
            result.realization_table["LifecyclePVCost_SE_USD"],
            112.0,
            rtol=0.0,
            atol=1e-8,
        )
        np.testing.assert_allclose(
            result.realization_table["UpgradeNPV_se_minus_sol_USD"],
            40.0,
            rtol=0.0,
            atol=1e-8,
        )
        terminal_rows = {
            row["system"]: row
            for row in result.summaries["representative_event_traces"]["annual"]
            if row["selection_label"] == "NPV-P50"
            and row["project_year"] == 2
        }
        self.assertEqual(terminal_rows["solectria"]["terminal_cost_usd"], 20.0)
        self.assertEqual(terminal_rows["solaredge"]["terminal_cost_usd"], -10.0)

    def test_npv_negative_tie_and_exact_probability_boundary(self):
        def with_solaredge_initial(base_request, cost_per_w):
            lifecycle = base_request.paired_lifecycle
            so_system, se_system = lifecycle.systems
            initial = se_system.initial_cost_lines[0]
            se_system = replace(
                se_system,
                initial_cost_lines=(
                    replace(
                        initial,
                        cost_per_w=fixed(initial.cost_per_w.input_id, cost_per_w),
                    ),
                ),
            )
            return replace(
                base_request,
                paired_lifecycle=replace(
                    lifecycle,
                    systems=(so_system, se_system),
                ),
            )

        negative = tea.run_technoeconomic(with_solaredge_initial(request(), 1.3))
        self.assertTrue(
            np.all(negative.realization_table["NPVOutcome"] == "negative")
        )
        self.assertEqual(
            negative.summaries["headline_decision"]["decision"],
            "Solectria preferred",
        )

        tied = tea.run_technoeconomic(with_solaredge_initial(request(), 1.2))
        self.assertTrue(np.all(tied.realization_table["NPVOutcome"] == "tie"))
        self.assertEqual(
            tied.summaries["headline_decision"]["decision"],
            "No decisive winner",
        )

        boundary = with_solaredge_initial(request(n=20), 1.05)
        lifecycle = boundary.paired_lifecycle
        boundary = replace(
            boundary,
            paired_lifecycle=replace(
                lifecycle,
                electricity_value=tea.DistributionSpec(
                    input_id=lifecycle.electricity_value.input_id,
                    family="uniform",
                    low=0.0,
                    high=0.1,
                ),
                npv_absolute_tolerance_usd_per_w=0.0,
                relative_tolerance=0.0,
            ),
        )
        # Convergence is orthogonal to this boundary test; pin it stable so the
        # assertion isolates the inclusive 75% decision rule.
        with patch.object(
            tea,
            "convergence_diagnostics",
            return_value={"status": "stable"},
        ):
            boundary_result = tea.run_technoeconomic(boundary)
        counts = boundary_result.summaries["probability_counts"]["upgrade_npv"]
        self.assertEqual(counts["positive"], 15)
        self.assertEqual(counts["negative"], 5)
        self.assertEqual(counts["tie"], 0)
        self.assertEqual(counts["p_positive"], 0.75)
        self.assertEqual(
            boundary_result.summaries["headline_decision"]["decision"],
            "SolarEdge preferred",
        )

    def test_decision_probability_convergence_checks_the_headline_buckets(self):
        convergence = {
            "status": "stable",
            "reasons": [],
            "class_probability_change_threshold": 0.001,
            "checkpoints": [
                {"realization_count": 4},
                {"realization_count": 8},
            ],
        }
        result = tea._v6_add_decision_probability_convergence(
            convergence,
            {
                "upgrade_npv": (
                    np.asarray(
                        [
                            "positive",
                            "positive",
                            "positive",
                            "positive",
                            "positive",
                            "positive",
                            "negative",
                            "negative",
                        ],
                        dtype=object,
                    ),
                    ("positive", "negative", "tie"),
                ),
                "delta_lcoe": (
                    np.asarray(["tie"] * 8, dtype=object),
                    ("higher", "lower", "tie"),
                ),
            },
        )

        self.assertEqual("not_demonstrated", result["status"])
        self.assertEqual(
            1.0,
            result["checkpoints"][0]["decision_probabilities"]["upgrade_npv"][
                "positive"
            ],
        )
        self.assertEqual(
            0.75,
            result["checkpoints"][1]["decision_probabilities"]["upgrade_npv"][
                "positive"
            ],
        )
        self.assertIn(
            "decision_probability_change:upgrade_npv:positive",
            result["reasons"],
        )

    def test_lcoo_reports_all_nonzero_cost_energy_quadrants(self):
        scenarios = (
            (1.1, 1_000.0, 1_100.0, "cost_increase_energy_gain", 0.05),
            (0.9, 1_000.0, 1_100.0, "cost_saving_energy_gain", -0.05),
            (1.1, 1_100.0, 1_000.0, "cost_increase_energy_loss", -0.05),
            (0.9, 1_100.0, 1_000.0, "cost_saving_energy_loss", 0.05),
        )
        for se_initial, so_energy, se_energy, quadrant, expected_lcoo in scenarios:
            with self.subTest(quadrant=quadrant):
                base = request()
                lifecycle = base.paired_lifecycle
                so_system, se_system = lifecycle.systems
                initial = se_system.initial_cost_lines[0]
                se_system = replace(
                    se_system,
                    initial_cost_lines=(
                        replace(
                            initial,
                            cost_per_w=fixed(
                                initial.cost_per_w.input_id,
                                se_initial,
                            ),
                        ),
                    ),
                )
                result = tea.run_technoeconomic(
                    replace(
                        base,
                        paired_energy_rows=(
                            tea.PairedEnergyRow(2021, so_energy, se_energy),
                        ),
                        paired_lifecycle=replace(
                            lifecycle,
                            systems=(so_system, se_system),
                        ),
                    )
                )
                self.assertTrue(
                    np.all(result.realization_table["tradeoff_class"] == quadrant)
                )
                np.testing.assert_allclose(
                    result.realization_table[
                        "IncrementalLCOO_se_minus_sol_USD_per_kWh_AC"
                    ],
                    expected_lcoo,
                    rtol=0.0,
                    atol=1e-12,
                )
                self.assertEqual(
                    result.summaries["cost_energy_quadrants"][quadrant]["count"],
                    base.n,
                )

    def test_near_zero_incremental_energy_and_negative_lifecycle_cost_are_explicit(self):
        equal_energy = replace(
            request(),
            paired_energy_rows=(tea.PairedEnergyRow(2021, 1_000.0, 1_000.0),),
        )
        result = tea.run_technoeconomic(equal_energy)
        self.assertTrue(
            np.isnan(
                result.realization_table[
                    "IncrementalLCOO_se_minus_sol_USD_per_kWh_AC"
                ]
            ).all()
        )
        self.assertTrue(
            np.all(
                result.realization_table["IncrementalLCOOReason"]
                == "near_zero_incremental_energy"
            )
        )

        base = request()
        lifecycle = base.paired_lifecycle
        so_system, se_system = lifecycle.systems
        so_system = replace(
            so_system,
            salvage_value=fixed("lifecycle.solectria.salvage.large", 1_000.0),
        )
        negative = tea.run_technoeconomic(
            replace(base, paired_lifecycle=replace(lifecycle, systems=(so_system, se_system)))
        )
        self.assertTrue(
            np.all(negative.realization_table["LifecyclePVCost_SOL_USD"] < 0)
        )
        self.assertIn(
            "negative_derived_lifecycle_cost",
            {warning["code"] for warning in negative.summaries["warnings"]},
        )

    def test_expected_mode_suppresses_recommendation(self):
        result = tea.run_technoeconomic(request(reliability_mode="expected"))
        decision = result.summaries["headline_decision"]
        self.assertEqual(decision["status"], "suppressed")
        self.assertIn("expected_mode_diagnostic_only", decision["reason_codes"])

    def test_version_and_evidence_fail_closed(self):
        with self.assertRaisesRegex(
            tea.TechnoeconomicValidationError,
            "tea-lhs-v2",
        ):
            tea.validate_request(replace(request(), sampling_version=tea.SAMPLING_VERSION))
        lifecycle = replace(
            request().paired_lifecycle,
            electricity_value_evidence={"status": "provisional"},
        )
        with self.assertRaisesRegex(
            tea.TechnoeconomicValidationError,
            "accepted=true",
        ):
            tea.validate_request(replace(request(), paired_lifecycle=lifecycle))

    def test_cost_coverage_id_overlap_is_rejected(self):
        base = request()
        lifecycle = base.paired_lifecycle
        so_system, se_system = lifecycle.systems
        so_component = replace(
            so_system.components[0],
            coverage_ids=(so_system.base_om_coverage_ids[0],),
        )
        overlapping = replace(
            base,
            paired_lifecycle=replace(
                lifecycle,
                systems=(
                    replace(so_system, components=(so_component,)),
                    se_system,
                ),
            ),
        )
        with self.assertRaisesRegex(
            tea.TechnoeconomicValidationError,
            "Coverage ID .* overlaps",
        ):
            tea.validate_request(overlapping)

    def test_admission_estimator_reports_a_request_specific_limit(self):
        estimate = tea.estimate_lifecycle_memory(1_000, 30, 4)
        self.assertEqual(
            estimate["estimated_peak_bytes"],
            tea.LIFECYCLE_MEMORY_BASE_BYTES
            + 2 * estimate["planned_ndarray_bytes"],
        )
        safe = tea.lifecycle_safe_realization_max(30, 4)
        self.assertGreater(safe["safe_max_realizations"], 0)
        self.assertLessEqual(safe["safe_max_realizations"], tea.MAX_REALIZATIONS)
        self.assertLess(safe["safe_max_realizations"], 100_000)

        component_heavy = tea.lifecycle_safe_realization_max(30, 40)
        self.assertLess(
            component_heavy["safe_max_realizations"],
            safe["safe_max_realizations"],
        )

        export_limited = tea.lifecycle_safe_realization_max(
            1,
            0,
            realization_export_columns=100,
        )
        self.assertEqual(
            "realization_export_cells",
            export_limited["limiting_dimension"],
        )
        self.assertLessEqual(
            export_limited["safe_max_realizations"] * 100,
            tea.LIFECYCLE_EXPORT_CELL_LIMIT,
        )

    def test_admission_benchmark_covers_scale_growth_without_claiming_rss(self):
        from tools import benchmark_tea_v6_admission as benchmark

        report = benchmark.admission_benchmark_report()
        self.assertEqual("analytical_estimator_only", report["measurement_kind"])
        self.assertIsNone(report["measured_rss_bytes"])
        self.assertEqual(
            2 * 1024 * 1024 * 1024,
            report["deployed_service_memory_bytes"],
        )
        self.assertEqual(100_000, report["public_realization_ceiling"])
        self.assertAlmostEqual(
            0.6,
            report["admission_limit_share_of_deployed_service"],
        )
        rows = report["rows"]
        self.assertTrue(all(row["estimated_peak_within_limit"] for row in rows))
        self.assertTrue(all(row["export_cells_within_limit"] for row in rows))
        self.assertTrue(
            all(row["next_realization_exceeds_limiting_dimension"] for row in rows)
        )
        self.assertTrue(
            all(not row["public_ceiling_request_admitted"] for row in rows)
        )

        thirty_year = {
            row["component_count"]: row
            for row in rows
            if row["project_life_years"] == 30
        }
        self.assertEqual([0, 2, 4, 8, 16, 40], sorted(thirty_year))
        safe_counts = [
            thirty_year[count]["safe_max_realizations"]
            for count in sorted(thirty_year)
        ]
        self.assertEqual(sorted(safe_counts, reverse=True), safe_counts)
        self.assertGreater(
            next(
                row["safe_max_realizations"]
                for row in rows
                if row["project_life_years"] == 20
                and row["component_count"] == 4
            ),
            next(
                row["safe_max_realizations"]
                for row in rows
                if row["project_life_years"] == 40
                and row["component_count"] == 4
            ),
        )
        export_limited_row = next(
            row
            for row in rows
            if row["project_life_years"] == 1
            and row["component_count"] == 0
        )
        self.assertEqual(
            "realization_export_cells",
            export_limited_row["limiting_dimension"],
        )

    def test_v6_checks_cancellation_inside_cohort_years(self):
        calls = 0

        def cancel():
            nonlocal calls
            calls += 1
            if calls == 5:
                raise RuntimeError("cancelled")

        with self.assertRaisesRegex(RuntimeError, "cancelled"):
            tea.run_technoeconomic(request(life=3), cancel_check=cancel)
        self.assertEqual(calls, 5)


if __name__ == "__main__":
    unittest.main()
