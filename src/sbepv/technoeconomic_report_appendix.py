"""Versioned explanatory report blocks, selected only from frozen evidence.

This is presentation content, not an executable physics or finance implementation.
It deliberately does not import the live model, read a baseline, or call an LLM.
The caller must verify the saved report evidence before using these blocks.
"""
from __future__ import annotations

from collections.abc import Mapping
import math


APPENDIX_CONTENT_VERSION = "1.1"

# Reviewed against model.py/calibration.py on 2026-09-16. The full manifest also
# commits to pvlib 0.15.2 and PVMismatch 4.1. A changed dependency/manifest must not
# silently make these descriptions appear to describe an unknown historical run.
DOCUMENTED_PHYSICS = frozenset({
    ("5", "sbe-stac1-calibration-physics-v1",
     "827ceca557a95b79aa15e53bea367c3873bfbd6d9d7f9b8b3e4e09aa162d2196"),
})
DOCUMENTED_ANNUAL_SEMANTICS = frozenset({
    ("2", "37137b11b2aa26f6bd20b4c0302a6ccecaab4a13b9b9f43a95b9c34dc97ac2df"),
})

# Primary references checked when reviewing this content. The shared report may
# include these as linked reference blocks alongside its saved evidence citations.
APPENDIX_REFERENCES = (
    ("pvlib: Hay-Davies sky diffuse irradiance",
     "https://pvlib-python.readthedocs.io/en/stable/reference/generated/pvlib.irradiance.haydavies.html"),
    ("pvlib: SAPM cell temperature",
     "https://pvlib-python.readthedocs.io/en/stable/reference/generated/pvlib.temperature.sapm_cell.html"),
    ("pvlib: physical incidence-angle modifier",
     "https://pvlib-python.readthedocs.io/en/stable/reference/generated/pvlib.iam.physical.html"),
    ("pvlib: Martin-Ruiz incidence-angle modifier",
     "https://pvlib-python.readthedocs.io/en/stable/reference/generated/pvlib.iam.martin_ruiz.html"),
    ("pvlib: CEC single-diode parameter translation",
     "https://pvlib-python.readthedocs.io/en/stable/reference/generated/pvlib.pvsystem.calcparams_cec.html"),
    ("pvlib: single-diode current-voltage equation",
     "https://pvlib-python.readthedocs.io/en/stable/reference/generated/pvlib.pvsystem.singlediode.html"),
    ("PVMismatch: cell current-voltage model",
     "https://sunpower.github.io/PVMismatch/api/pvcell.html"),
    ("PVMismatch: module topology and bypass diodes",
     "https://sunpower.github.io/PVMismatch/api/pvmodule.html"),
)


def _mapping(value):
    return value if isinstance(value, Mapping) else {}


def _value(value):
    if value is None or value == "":
        return "Not recorded"
    if isinstance(value, bool):
        return "Enabled" if value else "Disabled"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return f"{value:.12g}" if math.isfinite(value) else "Not available"
    return str(value)


def _distribution(value):
    value = _mapping(value)
    family = value.get("family")
    if family == "fixed":
        return "Fixed " + _value(value.get("value"))
    if family == "uniform":
        return "Uniform " + _value(value.get("low")) + " to " + _value(value.get("high"))
    if family == "triangular":
        return "Triangular low/mode/high: " + " / ".join(_value(value.get(k)) for k in ("low", "mode", "high"))
    if family == "bounded_normal":
        return ("Bounded normal " + _value(value.get("low")) + " to " + _value(value.get("high"))
                + "; mean " + _value(value.get("mean")) + ", SD " + _value(value.get("sd")))
    return "Not recorded"


def _factor_value(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
        return f"{value:.4f}"
    return _value(value)


def physics_description_supported(job):
    """Whether the saved model identity matches this reviewed physics content."""
    contract = _mapping(_mapping(job.get("source_snapshot")).get("model_contract"))
    identity = tuple(str(contract.get(key) or "") for key in (
        "model_version", "calibration_physics_version", "calibration_physics_fingerprint"))
    return identity in DOCUMENTED_PHYSICS


def applied_calibration_blocks(job):
    """Describe resolved Annual factors separately from origin calibration fits.

    The verified source snapshot is the sole source. In particular, an absent
    resolved factor is not replaced by an original fit or a guessed substitution.
    """
    lineage = _mapping(_mapping(job.get("source_snapshot")).get("calibration_lineage"))
    profile = _mapping(lineage.get("resolved_profile"))
    factors = _mapping(profile.get("seasonal_factors"))
    application = _mapping(lineage.get("application"))
    result_application = _mapping(lineage.get("result_application"))
    substitution = {}
    substitution_recorded = False
    for evidence in (application, result_application, profile):
        for key in ("seasonal_substitution", "seasonal_fallback"):
            if key in evidence:
                substitution_recorded = True
                if evidence[key] is not None:
                    substitution = _mapping(evidence[key])
                    break
        if substitution:
            break

    source = str(substitution.get("from_season") or substitution.get("source_season") or "").strip().lower()
    target = str(substitution.get("to_season") or substitution.get("target_season") or "").strip().lower()
    mapping = str(substitution.get("mapping") or "").lower().replace(" ", "")
    if not source and not target and mapping in {"fall<-spring", "fall←spring"}:
        source, target = "spring", "fall"

    fitted = _mapping(_mapping(lineage.get("origin_profile")).get("seasonal_factors"))
    seasons = ("winter", "spring", "summer", "fall")
    systems = ("solectria", "solaredge")
    explicit_no_substitution = substitution_recorded and all(
        evidence[key] is None
        for evidence in (application, result_application, profile)
        for key in ("seasonal_substitution", "seasonal_fallback") if key in evidence
    )
    complete_factors = set(factors) == set(seasons) and all(
        set(_mapping(factors.get(season))) == set(systems)
        and all(type(factors[season][system]) in (int, float)
                and math.isfinite(factors[season][system]) for system in systems)
        for season in seasons
    )
    if complete_factors and factors == fitted and explicit_no_substitution:
        return [{"kind": "paragraph", "style": "small", "text":
                 "Applied Annual factors equal the fitted factors above at saved precision for all four seasons; "
                 "the frozen application confirms no seasonal substitution."}]

    blocks = [{"kind": "heading", "text": "Applied Annual calibration factors",
               "anchor": "applied-annual-calibration", "page": False, "level": 2}]
    if factors:
        rows = []
        for season in seasons:
            values = _mapping(factors.get(season))
            source_text = ("Recorded substitute from " + source.title()
                           if season == target and source else "Frozen resolved profile")
            if not values:
                source_text = "Not recorded"
            rows.append([season.title(), _factor_value(values.get("solectria")),
                         _factor_value(values.get("solaredge")), source_text])
        blocks.append({"kind": "table", "headers": ["Season", "Solectria factor", "SolarEdge factor", "Factor source"],
                       "rows": rows, "widths": [.16, .20, .20, .44], "numeric": [1, 2], "keep": True})
        if factors == fitted:
            text = ("Applied Annual factors equal the original fitted factors at saved precision for every recorded season. "
                    "Values are dimensionless and displayed to four decimal places.")
        elif fitted:
            text = ("The resolved Annual factor profile differs from the original fitted profile. "
                    "Values are dimensionless and displayed to four decimal places; substitutions do not add measured coverage.")
        else:
            text = ("Applied Annual factors come from the frozen resolved profile; equality with the original fitted factors "
                    "is not established. Values are dimensionless and displayed to four decimal places.")
    else:
        text = ("Applied Annual calibration factors are unavailable in the frozen resolved profile. "
                "The original fitted factors alone do not establish which factors this Annual Simulation used.")
    blocks.append({"kind": "paragraph", "text": text, "style": "small"})

    if substitution:
        relation = target.title() + " <- " + source.title() if source and target else "mapping not recorded"
        accepted = substitution.get("explicitly_accepted")
        acceptance = ("Explicit acceptance is recorded." if accepted is True else
                      "The record marks explicit acceptance as false." if accepted is False else
                      "Explicit acceptance is not recorded.")
        text = "Saved seasonal substitution: " + relation + ". " + acceptance
    elif substitution_recorded:
        text = "The frozen application records no seasonal substitution."
    else:
        text = "Seasonal substitution status is not recorded."
    blocks.append({"kind": "paragraph", "text": text, "style": "small"})
    return blocks


def build_technical_appendix(job):
    """Build a concise methods reference from verified saved evidence only."""
    request = _mapping(job.get("request"))
    snapshot = _mapping(job.get("source_snapshot"))
    contract = _mapping(snapshot.get("model_contract"))
    annual = _mapping(snapshot.get("source_annual_job"))
    annual_request = _mapping(annual.get("request"))
    annual_stats = _mapping(_mapping(annual.get("result")).get("stats"))
    scenario = _mapping(request.get("paired_commercial"))
    finance = _mapping(request.get("finance"))
    degradation = _mapping(request.get("shared_degradation"))
    blocks = []

    def heading(text, anchor):
        blocks.append({"kind": "heading", "text": text, "anchor": "appendix-" + anchor,
                       "page": False, "level": 2})

    def paragraph(text):
        blocks.append({"kind": "paragraph", "text": text, "style": "small"})

    def table(headers, rows, widths=(.5, .5)):
        blocks.append({"kind": "table", "headers": headers, "rows": rows,
                       "widths": list(widths), "numeric": [], "keep": False})

    def setting(key):
        return annual_stats[key] if key in annual_stats else annual_request.get(key)

    supported = physics_description_supported(job)
    temporal_identity = tuple(str(contract.get(key) or "") for key in (
        "annual_temporal_semantics_version", "annual_temporal_semantics_fingerprint"))
    interval_unit = _value(annual_request.get("interval_unit"))
    if annual_request.get("interval_value") == 1:
        interval_unit = interval_unit.removesuffix("s")
    iam = setting("iam_model")

    heading("Saved model settings", "scope")
    paragraph(f"Methods revision {APPENDIX_CONTENT_VERSION}; saved results only, with no rerun or refit.")
    table(["Recorded item", "Saved value"], [
        ["PV model version", _value(contract.get("model_version"))],
        ["Physics version", _value(contract.get("calibration_physics_version"))],
        ["Physics SHA-256", _value(contract.get("calibration_physics_fingerprint"))],
        ["Physics description", "Matched reviewed identity" if supported else "Unavailable for this frozen identity"],
        ["Tracker backtracking", _value(setting("backtrack"))],
        ["Incidence-angle model", _value(iam)],
        ["Martin-Ruiz coefficient a_r", "Not applicable" if iam == "physical" else _value(setting("iam_a_r"))],
        ["SolarEdge inverter / BOS efficiencies", _value(setting("solaredge_inverter_efficiency")) + " / " + _value(setting("solaredge_bos_efficiency"))],
        ["Solectria inverter / BOS efficiencies", _value(setting("solectria_inverter_efficiency")) + " / " + _value(setting("solectria_bos_efficiency"))],
        ["Optional AC cap", _value(setting("curtailment_enabled")) + "; saved setting " + _value(setting("curtailment_limit_kw")) + " kW per system"],
        ["Weather interval", _value(annual_request.get("interval_value")) + " " + interval_unit],
        ["DHI source", _value(annual_stats.get("dhi_source"))],
    ])

    if supported:
        heading("Sunlight and temperature", "irradiance")
        paragraph("NREL solar position; as-built bay tilts; single-axis tracking with 180-degree azimuth, 60-degree rotation limit and ground coverage ratio 0.4.")
        rows = [
            ["DHI = max(GHI - DNI cos(z), 0)",
             "Fallback only when DHI is missing. z = solar zenith; irradiance in W/m2."],
            ["G_sky = DHI [A R_b + (1 - A)(1 + cos(tilt))/2]",
             "Hay-Davies sky diffuse. A = DNI / extraterrestrial DNI; R_b = projection ratio with horizon guards."],
            ["T_module = T_air + G_POA exp(a + b wind)\nT_cell = T_module + (G_POA / 1000) deltaT",
             "SAPM temperature in degrees C; wind in m/s. a = -3.47, b = -0.0594, deltaT = 0."],
        ]
        if iam == "physical":
            rows.append(["G_effective = G_beam IAM + G_diffuse",
                         "Physical reflection/transmission loss, applied once; no extra spectral loss."])
        elif iam == "martin_ruiz":
            rows.append(["IAM = [1 - exp(-cos(AOI)/a_r)] / [1 - exp(-1/a_r)]\nG_effective = IAM G_POA",
                         "Martin-Ruiz: zero outside front incidence; applied once before recalculating CEC power."])
        else:
            rows.append(["IAM selection unavailable", "The saved selection is missing; no default is applied."])
        table(["Equation", "Meaning and units"], rows, (.53, .47))

        heading("Electrical power and calibration", "electrical")
        table(["Equation", "Meaning and units"], [
            ["I = I_L - I_0 [exp((V + I R_s)/a) - 1]\n    - (V + I R_s)/R_sh",
             "CEC model: I_L = photocurrent; I_0 = saturation current. I[A], V/a[V], R_s/R_sh[ohms]; parameters follow irradiance/temperature."],
            ["P_DC,SE = sum(P_mp,module)",
             "SolarEdge sums module maximum powers. WAAREE BIN-08-580: 579.92 Wdc at STC."],
            ["I = I_gen - I_d1 - I_d2 - U/R_sh - I_RBD\nI_d1 = I_sat1 [exp(U/V_T) - 1]\nI_d2 = I_sat2 [exp(U/(2V_T)) - 1]\nV = U - I R_s",
             "Solectria cell model: U = diode voltage; V_T = k T_cell/q. Temperature[K], current[A], voltage[V]."],
            ["I_RBD = (a_RBD x + b_RBD x^2) I_sc,ref\n             * (1 - U/V_RBD)^(-n_RBD)\nx = U/(R_sh I_sc,ref)",
             "Reverse breakdown; I_sc,ref = reference short-circuit current. Three 24-cell substrings; -0.5 V bypass clamp each."],
            ["P_DC,SOL = max_V [V sum(I_string(V))]",
             "Ten parallel strings share one MPPT at 860-1250 V; four bays of six modules/string. Mismatch precedes power maximization."],
            ["P_AC = P_DC eta_inverter eta_BOS",
             "Saved efficiency scalars. Solectria's 250 kW hardware cap applies before and after calibration; the optional user cap applies afterward."],
            ["sum(min(f P_model,i, cap) dt_i)/1000\n    = E_measured",
             "Seasonal factor f includes active caps. Uncapped: f = measured / uncalibrated seasonal energy."],
            ["E_kWh = sum(P_W,i dt_hours,i)/1000",
             "Bounded intervals; gaps add no energy. Non-finite power contributes zero without implying measured zero output."],
        ], (.53, .47))
        paragraph("Limits: ideal SolarEdge module extraction; no optimizer efficiency curve or SolarEdge hardware clipping. No rear irradiance; uniform bay conditions.")
    else:
        paragraph("Detailed PV equations are unavailable for this frozen physics identity; current defaults are not assigned to historical runs.")

    heading("Calibration and time basis", "calibration")
    paragraph("Annual Simulation uses the saved applied factors. Calibration does not provide independent validation; short observation windows limit confidence in annual predictions.")
    if temporal_identity in DOCUMENTED_ANNUAL_SEMANTICS:
        paragraph("MIDC means use midpoint physics, right-labeled outputs and nominal durations. Annual totals use fixed MST; calibration seasons use Denver time.")
    else:
        paragraph("The saved Annual timestamp convention is unknown. The recorded interval is shown above; no current convention is assumed.")

    heading("Lifecycle cost and energy", "finance")
    table(["Saved assumption", "Value"], [
        ["Project life L (years)", _value(finance.get("project_life_years"))],
        ["Constant-dollar cost year", _value(finance.get("constant_dollar_cost_year"))],
        ["Real discount rate r (fraction/year)", _distribution(_mapping(finance.get("real_discount_rate")).get("distribution"))],
        ["Shared degradation g (fraction/year)", _distribution(_mapping(degradation.get("annual_rate")).get("distribution"))],
        ["Realizations / random seed", _value(request.get("n")) + " / " + _value(request.get("seed"))],
    ])
    financial_rows = []
    if scenario:
        financial_rows.append([
            "E_j,1 = E_source,j P_target / P_applied,j",
            "Commercial first-year kWh; source and target share the saved AC-cap or installed-DC basis. Proportional transfer, not a new plant model.",
        ])
    financial_rows.extend([
        ["E_j,t = E_j,1 (1 - g)^(t - 1)\nDF_t = (1 + r)^(-t)",
         "t = year 1 to L; j = system. Shared degradation, one paired weather-year basis; year one is undegraded."],
        ["PV_energy,j = sum(E_j,t DF_t)\nPV_cost,j = C_j,0 + sum(C_j,t DF_t)",
         "Discounted kWh and USD. Initial cost at year zero; annual and scheduled costs at their recorded year-ends."],
        ["LCOE_j = 1000 PV_cost,j / PV_energy,j",
         "USD/MWh. Real costs use the saved dollar year; no nominal inflation is added."],
        ["AF = sum(DF_t); CRF = 1/AF",
         "Annualizing both present values preserves LCOE. At r = 0: AF = L; CRF = 1/L."],
    ])
    table(["Equation", "Meaning and units"], financial_rows, (.53, .47))
    if scenario.get("shared_initial_capex"):
        paragraph("Shared CAPEX enters each system once; SolarEdge adds optimizer hardware/installation. Maintenance follows recorded coverage.")

    heading("Sampling and sensitivity", "statistics")
    table(["Method", "Interpretation"], [
        ["Seeded Latin Hypercube Sampling",
         "Stratified uncertain inputs; fixed inputs use no dimension. Systems share weather years; year counts differ by at most one."],
        ["P10 / P50 / P90 and empirical CDF",
         "Type-7 quantiles; CDF = P(X <= x), retaining ties. Sampled uncertainty, not measured-performance confidence."],
        ["Rank model: z(rank LCOE) = intercept + sum(beta_k z(rank input_k))",
         "Average ranks for ties; z standardizes by sample SD. Forward selection maximizes added R-squared; stop below 1e-6 improvement or insufficient degrees of freedom."],
        ["Signed standardized coefficients beta",
         "Dimensionless multivariable effects: positive raises LCOE rank, negative lowers it. R-squared measures rank fit, not physical accuracy."],
    ], (.43, .57))
    paragraph("Entry ties within 1e-12 use input-ID order. Constant, duplicate-rank and singular predictors are excluded.")
    return blocks
