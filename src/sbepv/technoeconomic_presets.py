"""Explicitly selected, versioned assumptions; never applied as silent defaults."""
from copy import deepcopy

PRESET_ID = "thursday-2026-09-17-v1"
LIMITATIONS = (
    "Proposed real 2024-dollar basis. Later vendor and market prices are unadjusted "
    "face-value proxies, not inflation-normalized quotes. O&M coverage of major "
    "maintenance remains unresolved; no separate major-maintenance charge is added. "
    "Lifecycle conclusions are provisional. Component allocations are explanatory, "
    "not independently sampled. Inverter quote assumed per Wdc; optimizer design "
    "uses 103,077 H1300 units for two 650 W modules each, excluding spares."
)
COMPONENT_ALLOCATIONS = (
    ("Modules", .270, .260, .280, "DOE market update, Q3 2025 proxy"),
    ("Inverters", .060, .060, .060, "Kleber vendor quote; Wdc assumed"),
    ("Trackers / structural BOS", .150, .145, .155, "DOE benchmark allocation"),
    ("Transformers", .040, .035, .045, "Separate hardware allocation"),
    ("Other electrical BOS", .150, .145, .155, "Excludes transformers and controls"),
    ("Controls / monitoring", .025, .022, .028, "Separate allowance"),
    ("Field installation", .140, .130, .150, "Excludes commissioning and optimizer installation"),
    ("Commissioning", .015, .013, .017, "Separate allowance"),
    ("Engineering and other costs", .270, .260, .280, "Permits, interconnection, overhead, contingency; excludes construction financing"),
)


def thursday_assumptions(source_annual_job_id: str) -> dict:
    """Return a strict v5 request; the ordinary submission path verifies its source."""
    def evidence(note):
        return {
            "evidence_class": "engineering_judgment",
            "explicit_acceptance": True,
            "acceptance_rationale": "Explicit selection and confirmation of the September 15 assumptions preset, including its stated limitations.",
            "citation": {
                "title": "TEA Assumptions for Confirmation / September 15 approved scenario",
                "organization": "SBE PV project",
                "stable_reference": "TEA_Assumptions.docx; Outlook: TEA assumptions for confirmation; preset " + PRESET_ID,
                "publication_or_as_of_date": "2026-09-15",
                "accessed_date": "2026-09-15",
                "excerpt_or_derivation_note": note + " " + LIMITATIONS,
                "preservation_mode": "metadata_excerpt_only",
                "metadata_only_rationale": "Source assumptions and derivations transcribed here; this service does not preserve vendor quote bytes.",
            },
        }
    def uniform(low, high):
        return {"family": "uniform", "low": low, "high": high}
    ratio = 1.34
    hardware_per_ac_w = 103_077 * 37.75 / 100_000_000
    systems = []
    for technology, om in (("solectria", (8, 13)), ("solaredge", (12, 18))):
        premium = (hardware_per_ac_w + .004 * ratio, hardware_per_ac_w + .010 * ratio) if technology == "solaredge" else (0, 0)
        systems.append({
            "technology": technology,
            "evidence": evidence("Scale each system's paired annual AC energy by 100 MWac / its frozen AC operating limit."),
            "cost_lines": [{
                "input_id": technology + ".full-capex", "label": technology.title() + " derived total CAPEX",
                "cost_category": "full_initial_capex", "coverage_ids": ["full-system-capex"],
                "timing": "initial_t0", "unit": "constant_usd_per_target_w",
                "distribution": uniform(1.07 * ratio + premium[0], 1.17 * ratio + premium[1]),
                "constant_dollar_cost_year": 2024,
                "evidence": evidence("Support envelope only, not a sampled uniform total. Common U(1.07,1.17) USD/Wdc x 1.34; SolarEdge additionally receives 103077 x USD37.75 hardware and independent U(.004,.010) USD/Wdc installation."),
            }, {
                "input_id": technology + ".annual-om", "label": technology.title() + " annual O&M",
                "cost_category": "full_annual_om", "coverage_ids": ["annual-operation-maintenance"],
                "timing": "annual_year_end", "unit": "constant_usd_per_target_w_year",
                "distribution": uniform(om[0] / 1000 * ratio, om[1] / 1000 * ratio),
                "constant_dollar_cost_year": 2024,
                "evidence": evidence(f"August 20 Teams provisional estimate: U({om[0]},{om[1]}) USD/kWdc-year; divide by 1000 and multiply by 1.34. Independent system O&M draws."),
            }],
        })
    return deepcopy({
        "calculation_contract_version": "tea-calculation-v5",
        "source_annual_job_id": source_annual_job_id,
        "basis": "solartac_site", "capacity_normalization": "annual_applied_capacity_v1",
        "n": 10_000, "seed": 20260916, "cost_stack_completeness": "full_system", "cost_lines": [],
        "finance": {
            "treatment_key": "constant-real-v1", "constant_dollar_cost_year": 2024,
            "project_life_years": 30, "project_life_evidence": evidence("30 years; Cliff's September 14 reply."),
            "real_discount_rate": {"unit": "real_fraction_per_year", "distribution": uniform(.05, .07), "evidence": evidence("Uniform 5–7% real discount rate, shared across systems.")},
        },
        "shared_degradation": {"degradation_model": "shared_module_v1", "annual_rate": {
            "unit": "real_fraction_per_year", "distribution": {"family": "triangular", "low": .003, "mode": .005, "high": .007},
            "evidence": evidence("Jordan and Kurtz review: 0.5% median reference; bounds and triangular shape are proposed. Shared draw; first-year energy undegraded."),
        }},
        "paired_commercial": {
            "target_capacity": 100, "target_capacity_unit": "mw", "target_rating_basis": "ac_operating_limit",
            "transfer_method": "direct_capacity_scaling", "transfer_rationale": "Existing AC-normalized SolarTAC transfer to 100 MWac; DC cost basis 134 MWdc. No DC ratio applied to energy.",
            "evidence": evidence("NLR 2024 ATB proposed DC/AC ratio 1.34 and single-axis tracking; site transfer does not establish a generalized-site yield model."),
            "systems": systems,
            "shared_initial_capex": {
                "method": "shared_base_optimizer_premium_v1", "dc_capacity_w": 134_000_000,
                "common_capex_wdc": uniform(1.07, 1.17), "optimizer_installation_wdc": uniform(.004, .010),
                "optimizer_count": 103_077, "optimizer_unit_price_usd": 37.75,
                "report_context": {
                    "preset_id": PRESET_ID, "limitations": LIMITATIONS,
                    "component_allocations": [{"label": row[0], "midpoint_wdc": row[1], "low_wdc": row[2], "high_wdc": row[3], "source_note": row[4]} for row in COMPONENT_ALLOCATIONS],
                },
                "evidence": evidence("August 13 vendor price USD37.75; preliminary Teams installation bounds. DOE Q1 2025 benchmark supports USD1.12/Wdc common midpoint in 2024 dollars. Component midpoint allocations: " + "; ".join(f"{row[0]} {row[1]:.3f} USD/Wdc" for row in COMPONENT_ALLOCATIONS)),
            },
        },
    })
