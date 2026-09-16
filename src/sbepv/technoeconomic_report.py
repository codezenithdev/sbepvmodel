"""Shared presentation model for PDF and Word; consumes verified saved evidence.

No model execution, sampling, storage writes, or baseline lookup belongs here.
Chart images and all displayed tables are shared by both document renderers.
"""
from __future__ import annotations

import base64
from datetime import datetime, timezone
from io import BytesIO
import math
import re
import textwrap

import numpy as np
from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.ticker import PercentFormatter, MaxNLocator
from sbepv import technoeconomic_report_diagnostics as diagnostics
from sbepv import technoeconomic_report_appendix as appendix

REPORT_VERSION = "2.4.1"
SYSTEMS = (("solectria", "Solectria", "sol"), ("solaredge", "SolarEdge", "se"))
COLORS = ("#CC921A", "#2E66A3", "#454545")


def number(value, digits=2):
    if value is None:
        return "Not available"
    try:
        value = float(value)
        return f"{value:,.{digits}f}" if math.isfinite(value) else "Not available"
    except (TypeError, ValueError):
        return "Not available"


def display_date(value, *, time=False):
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if time and parsed.tzinfo:
            parsed = parsed.astimezone(timezone.utc)
        return parsed.strftime("%d %b %Y at %H:%M UTC" if time else "%d %b %Y")
    except (TypeError, ValueError):
        return "Not recorded"


def capacity(value, basis):
    if value is None:
        return "Not recorded"
    scale, unit = (1e6, "MW") if abs(value) >= 1e6 else (1000, "kW")
    return f"{number(value / scale, 3).rstrip('0').rstrip('.')} {unit}{basis}"


def measured_window(request, result):
    window = result.get("window") or {}
    def boundary(side):
        value = window.get(side + "_local")
        if value:
            try:
                return datetime.fromisoformat(value).strftime("%d %b %Y %H:%M")
            except (TypeError, ValueError):
                pass
        return display_date(request.get(side + "_date")) + " " + str(request.get(side + "_time") or "(time not recorded)")
    zone = window.get("timezone") or "America/Denver"
    ending = "end inclusive" if window.get("end_exclusive") is False else "end exclusive"
    return f"{boundary('from')} to {boundary('to')} ({zone}; {ending})"


def words(value):
    if value is None or value == "":
        return "Not recorded"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, (tuple, list)):
        return "; ".join(words(item) for item in value) or "None recorded"
    if isinstance(value, dict):
        return "; ".join(f"{words(key)}: {words(item)}" for key, item in value.items()) or "None recorded"
    return str(value).replace("—", ": ").replace("_", " ").replace("solaredge", "SolarEdge").replace("solectria", "Solectria")


def distribution(value, scale=1, digits=2):
    if not isinstance(value, dict):
        return "Not recorded"
    def f(key):
        return number(value.get(key) * scale if value.get(key) is not None else None, digits)
    family = value.get("family")
    if family == "fixed":
        return f"Fixed {f('value')}"
    if family == "uniform":
        return f"Uniform {f('low')} to {f('high')}"
    if family == "triangular":
        return f"Triangular {f('low')} / {f('mode')} / {f('high')}"
    if family == "bounded_normal":
        return f"Bounded normal {f('low')} to {f('high')}; mean {f('mean')}, SD {f('sd')}"
    return "Distribution not recorded"


def midpoint(value):
    if value.get("family") == "fixed":
        return value["value"]
    if value.get("low") is not None and value.get("high") is not None:
        return (value["low"] + value["high"]) / 2
    return None


def predictor_label(value, input_labels):
    known = {"capex.shared-base-wdc": "Shared base CAPEX", "capex.optimizer-installation-wdc": "Optimizer installation",
             "finance.discount-rate": "Real discount rate", "energy.shared-degradation": "Annual degradation",
             "solectria.annual-om": "Solectria O&M", "solaredge.annual-om": "SolarEdge O&M"}
    text = str(value)
    if text in known:
        return known[text]
    if "specific" in text.lower() or ("source" in text.lower() and "energy" in text.lower()):
        return ("SolarEdge" if "solaredge" in text.lower() or "solar_edge" in text.lower() else "Solectria") + " specific energy"
    return input_labels.get(text, words(text).replace(".", " "))


def annual_interpolation_points(values):
    """Match the dashboard's tie-aware midpoint ranks, without fitted tails."""
    values = np.asarray(values, dtype=float)
    values = values[np.isfinite(values)]
    x, counts = np.unique(values, return_counts=True)
    if len(values) < 2 or len(x) < 2:
        return None
    last = np.cumsum(counts)
    first = last - counts + 1
    return x, (first + last - 1) / (2 * len(values))


def chart_image(kind, payload, height=2.55):
    """High-resolution charts from actual arrays; no fitted/interpolated CDFs."""
    fig = Figure(figsize=(7.15, height), dpi=320, facecolor="white")
    canvas = FigureCanvasAgg(fig)
    if kind == "sensitivity":
        panels = payload["panels"]
        axes = fig.subplots(1, len(panels), sharey=True, squeeze=False)[0]
        labels = payload["labels"]
        y = np.arange(len(labels))
        maximum = max((v for panel in panels for v in panel["values"] if v is not None), default=0)
        limit = max(.01, maximum * 1.32)
        for i, (ax, panel) in enumerate(zip(axes, panels)):
            values = np.asarray([np.nan if v is None else v for v in panel["values"]])
            ax.barh(y, values, color=COLORS[i % 3], height=.6, hatch=("", "//", "..")[i % 3])
            for j, value in enumerate(values):
                if np.isfinite(value):
                    ax.text(value + limit*.018, j, f"{value:.3g}", va="center", fontsize=9)
            ax.set_title(panel["label"] + "\nR² = " + number(panel.get("r_squared"), 3), fontsize=10, loc="left", pad=12)
            ax.set_xlim(0, limit)
            ax.set_xlabel("Incremental R²", fontsize=10)
            ax.xaxis.set_major_locator(MaxNLocator(3))
            ax.set_yticks(y, [textwrap.fill(label, 23) for label in labels])
            ax.tick_params(axis="y", length=0, labelsize=10)
        axes[0].invert_yaxis()
        fig.subplots_adjust(left=.29, right=.98, top=.82, bottom=.15, wspace=.22)
    else:
        ax = fig.add_subplot(111)
        axes = [ax]
        series = payload.get("series", [])
        if kind == "annual_cdf":
            for i, item in enumerate(series):
                ax.plot(item['x'], item['probability'], color=COLORS[i],
                        linestyle=('--', '-')[i % 2], marker=('o', 's')[i % 2],
                        markersize=4, label=item['label'])
            ax.set_ylim(0, 1)
            ax.yaxis.set_major_formatter(PercentFormatter(1))
            ax.set_ylabel('Cumulative probability', fontsize=10.5)
            ax.set_xlabel('SolarTAC annual AC energy (MWh)', fontsize=10.5)
            ax.legend(loc='lower left', bbox_to_anchor=(0, 1.02), ncols=2, frameon=False, fontsize=10, borderaxespad=0)
        elif kind in ("cdf", "paired"):
            for i, item in enumerate(series):
                x = np.sort(np.asarray(item["values"], dtype=float))
                y = np.arange(1, len(x)+1) / len(x)
                ax.step(x, y, where="post", color=COLORS[i], linestyle=("-", "--")[i % 2], linewidth=1.9, label=item["label"])
                p50 = item.get("p50")
                if p50 is not None:
                    ax.scatter([p50], [.5], color=COLORS[i], marker=("o", "s")[i % 2], s=30, zorder=4)
                    offset = (-58, 36) if i == 0 and len(series)>1 else (18, -42)
                    ax.annotate(f"{item['label']} P50\n${p50:.2f}/MWh", (p50,.5), xytext=offset,
                                textcoords="offset points", fontsize=10, color=COLORS[i],
                                bbox={"facecolor":"white", "edgecolor":"none", "pad":2},
                                arrowprops={"arrowstyle":"-", "color":COLORS[i], "lw":.8})
            ax.set_ylim(0, 1.04)
            ax.yaxis.set_major_formatter(PercentFormatter(1))
            ax.set_ylabel("Cumulative probability", fontsize=10.5)
            ax.set_xlabel("LCOE (USD/MWh)" if kind=="cdf" else "SolarEdge minus Solectria LCOE (USD/MWh)", fontsize=10.5)
            if kind == "paired":
                values = np.asarray(series[0]["values"])
                extent = max(float(np.max(np.abs(values))), .01)
                low, high = min(float(np.min(values)), 0)-extent*.16, max(float(np.max(values)), 0)+extent*.16
                ax.set_xlim(low, high)
                ax.axvline(0, color="#555555", linestyle=":", linewidth=1)
                ax.text(.01, 1.07, "Negative: favors SolarEdge", transform=ax.transAxes, fontsize=9.5)
                ax.text(.99, 1.07, "Positive: favors Solectria", transform=ax.transAxes, ha="right", fontsize=9.5)
        elif kind == "bars":
            labels = payload["labels"]
            for i, item in enumerate(series):
                x = np.arange(len(labels)) + (i-(len(series)-1)/2)*(.78/len(series))
                ax.bar(x, item["values"], width=.78/len(series), label=item["label"], color=COLORS[i], hatch=("", "//", "..")[i % 3])
            ax.set_xticks(np.arange(len(labels)), labels)
            ax.set_ylabel(payload["ylabel"], fontsize=10.5)
            ax.legend(loc="lower left", bbox_to_anchor=(0,1.02), ncols=len(series), frameon=False, fontsize=10, borderaxespad=0)
        else:
            for i, item in enumerate(series):
                ax.plot(item["x"], item["values"], label=item["label"], color=COLORS[i], linestyle=("-", "--")[i%2], marker=("o", "s")[i%2], markersize=4)
            ax.set_ylabel(payload["ylabel"], fontsize=10.5)
            ax.set_xlabel(payload.get("xlabel", "Weather year"), fontsize=10.5)
            ax.xaxis.set_major_locator(MaxNLocator(integer=True))
            ax.legend(loc="lower left", bbox_to_anchor=(0,1.02), ncols=2, frameon=False, fontsize=10, borderaxespad=0)
        fig.subplots_adjust(left=.12, right=.97, top=.84, bottom=.23 if height<2.5 else .19)
    for ax in axes:
        ax.grid(axis="x" if kind=="sensitivity" else "y", color="#DDDDDD", linewidth=.6)
        ax.set_axisbelow(True)
        ax.spines[["top", "right"]].set_visible(False)
        ax.spines[["bottom", "left"]].set_color("#AAAAAA")
        ax.tick_params(axis="both", labelsize=10)
    stream = BytesIO()
    canvas.print_png(stream)
    return base64.b64encode(stream.getvalue()).decode("ascii")


def median_lcoe_comparison(system_results):
    """Compare marginal medians; the median paired delta is a different statistic."""
    medians = [(system_results.get(key) or {}).get("percentiles", {}).get("p50") for key, _, _ in SYSTEMS]
    if any(value is None or not math.isfinite(float(value)) for value in medians):
        return "The difference between system median LCOEs is unavailable in this saved result."
    difference = (medians[1] - medians[0]) * 1000
    if difference == 0:
        return f"The equivalent-capacity commercial systems have equal median LCOE of ${number(medians[0]*1000)}/MWh under the modelled assumptions."
    lower, higher = ("Solectria", "SolarEdge") if difference > 0 else ("SolarEdge", "Solectria")
    return (f"Under the modelled assumptions, the median LCOE of the commercial {lower} system is "
            f"${abs(difference):.2f}/MWh lower than that of the equivalent-capacity {higher} system. "
            f"Median LCOE is ${number(medians[0]*1000)}/MWh for Solectria and ${number(medians[1]*1000)}/MWh for SolarEdge.")


def energy_comparison(label, solectria, solaredge):
    if any(value is None or not math.isfinite(float(value)) for value in (solectria, solaredge)):
        return f"{label}: a two-system comparison is unavailable in the saved evidence."
    difference = solectria - solaredge
    statement = f"{label}: Solectria {number(solectria/1000,1)} MWh and SolarEdge {number(solaredge/1000,1)} MWh. "
    if difference == 0:
        return statement + "The saved energy totals are equal."
    lower = solaredge if difference > 0 else solectria
    percentage = f" ({number(abs(difference)/lower*100,2)}% relative to the lower value)" if lower > 0 else ""
    return statement + f"{'Solectria' if difference > 0 else 'SolarEdge'} is higher by {number(abs(difference)/1000,2)} MWh{percentage}."


def quality_issue_label(decision):
    """Translate saved machine identifiers without changing their review action."""
    if decision.get('label'):
        return words(decision['label'])
    identifier = str(decision.get('issue_id') or decision.get('issue_type') or '')
    descriptive = {'range.temp_air':'Air temperature outside the allowed range',
                   'range.wind_speed':'Wind speed outside the allowed range'}
    if identifier in descriptive:
        return descriptive[identifier]
    tokens = identifier.split('.')
    labels = {'pattern':'Pattern check', 'flatline':'Unchanging readings',
              'missing':'Missing readings', 'nonfinite':'Invalid readings',
              'negative':'Negative readings', 'outlier':'Outlying readings',
              'gap':'Missing intervals', 'duplicate':'Duplicate timestamps',
              'range':'Outside the allowed range', 'temp_air':'Air temperature', 'wind_speed':'Wind speed',
              'low_power_high_irradiance':'Low power despite high irradiance',
              'power_without_irradiance':'Power reported without irradiance',
              'ghi':'Global horizontal irradiance', 'dni':'Direct normal irradiance',
              'dhi':'Diffuse horizontal irradiance'}
    if tokens and tokens[0] == 'pattern':
        tokens = tokens[1:]
    return ': '.join(labels.get(token.lower(),words(token)) for token in tokens) or 'Unspecified issue'


def build_report(job, calculation, routine, checks, *, generated_at=None, lifecycle_chart=None,
                 include_technical_appendix=True, dashboard_identity=None, energy_evidence=None):
    generated = generated_at or datetime.now(timezone.utc)
    request, snapshot = job["request"], job["source_snapshot"]
    lineage = snapshot["calibration_lineage"]
    calibration = lineage["origin_validation_job"]
    annual = snapshot["source_annual_job"]
    stats = calibration["result"].get("stats") or {}
    c_request = calibration.get("request") or {}
    cleaning = (lineage.get("data_quality") or {}).get("cleaning") or {}
    paired = routine.get("paired_commercial") or {}
    scenario = request.get("paired_commercial") or {}
    shared = scenario.get("shared_initial_capex") or {}
    context = shared.get("report_context") or {}
    assumptions_status = context.get("assumptions_status")
    finance = request.get("finance") or {}
    metadata = calculation.metadata
    if energy_evidence is None:
        from sbepv.technoeconomic_report_energy import build_energy_evidence
        energy_evidence = build_energy_evidence(snapshot)
    blocks = []
    def paragraph(text, style="body"):
        blocks.append({"kind":"paragraph", "text":text, "style":style})
    def heading(text, anchor, *, page=False, level=1):
        blocks.append({"kind":"heading", "text":text, "anchor":anchor, "page":page, "level":level})
    def table(headers, rows, widths=None, numeric=(), *, keep=False, compact=False):
        if not rows:
            paragraph("No supporting values were recorded.")
            return
        blocks.append({"kind":"table", "headers":headers, "rows":rows, "widths":widths, "numeric":list(numeric), "keep":keep or len(rows)<=3, "compact":compact})
    def chart(kind, data, height, caption):
        if not data.get("series") and not data.get("panels"):
            paragraph("Chart unavailable because its saved observations are missing.")
            return
        blocks.append({"kind":"chart", "image":chart_image(kind,data,height), "height":height*72, "caption":caption})
    def q(value, key="p50", scale=1, digits=2):
        raw = (value.get("percentiles") or {}).get(key)
        return number(raw*scale if raw is not None else None, digits)

    target_w = paired.get("target_capacity_w")
    target_text = capacity(target_w, "ac" if scenario.get("target_rating_basis")=="ac_operating_limit" else "dc")
    system_results = paired.get("systems") or {}
    identity = dashboard_identity or {"version":"Not recorded", "version_source":"not recorded", "build":"Not recorded"}
    report = {"title":"SolarEdge and Solectria PV comparison", "version":REPORT_VERSION,
              "generated_at":generated.isoformat(), "analysis_at":job.get("completed_at"),
              "run_id":str(job.get("id") or job.get("job_id")), "blocks":blocks,
              "include_technical_appendix":bool(include_technical_appendix), "dashboard_identity":dict(identity)}
    report['verification_check_count'] = len(checks)
    report['energy_evidence'] = energy_evidence

    blocks.append({"kind":"title", "text":report["title"]})
    paragraph(f"SBE Innovation Center at SolarTAC  |  {target_text} commercial comparison", "subtitle")
    paragraph(f"Analysis completed {display_date(job.get('completed_at'),time=True)}\n"
              f"Generating dashboard version {identity['version']} ({identity['version_source']})", "meta")
    paragraph("Contents", "toc_title")
    blocks.append({"kind":"toc"})
    heading("Executive Summary", "executive-summary", page=True)
    heading("Objectives", "summary-objectives", level=2)
    paragraph(f"Compare SolarEdge and Solectria energy production and lifecycle levelized cost of electricity (LCOE), using a model calibrated to SolarTAC measurements for an equal-capacity {target_text} commercial scenario.")
    heading("Approach", "summary-approach", level=2)
    paragraph("Data Collection > Modeling and Calibration > Annual Simulation > Technoeconomic Analysis. Reviewed Bazefield measurements establish seasonal model corrections; historical MIDC weather drives annual predictions; paired Monte Carlo realizations propagate the recorded energy and cost assumptions into lifecycle LCOE.")
    heading("Results", "summary-results", level=2)
    paragraph(median_lcoe_comparison(system_results), "finding")
    rows = []
    for key,label,_ in SYSTEMS:
        result = system_results.get(key) or {}
        rows.append([label,*[q(result,p,1000) for p in ("p10","p50","p90")]])
    table(["LCOE (USD/MWh)","P10","P50 median","P90"],rows,[.37,.21,.21,.21],numeric=(1,2,3),keep=True)
    paragraph("Lower LCOE means a lower discounted cost per unit of generated AC energy. Cost P10 and P90 bound the middle 80% of the sampled LCOEs. The headline comparison subtracts system medians; it is not the median of paired differences.", "small")
    if context.get("limitations"):
        paragraph("Scenario qualifications: " + words(context["limitations"]), "small")

    heading("Introduction and Objectives", "introduction", page=True)
    paragraph("The SBE Innovation Center at SolarTAC hosts SolarEdge and Solectria PV systems. SolarEdge optimizes power at the module level; Solectria uses a common inverter operating point for connected strings. These architectures respond differently to uneven module conditions.")
    paragraph("This study calibrates each system against reviewed site measurements, predicts production across full historical weather years, and compares lifecycle cost per unit of AC energy at equal commercial capacity. It uses the recorded geometry and model assumptions without assuming either technology produces more energy. Calibration coverage and cost assumptions limit how broadly the results apply.")
    heading("Analysis Approach", "analysis-approach")
    paragraph("Four steps: collect power and weather measurements; review data quality and fit seasonal model factors; apply those saved factors to historical weather years; and compare lifecycle LCOE through paired Monte Carlo sampling. Saved records link each step to its source.")

    heading("Data Collection", "data-collection")
    paragraph("Bazefield supplies the power and weather measurements used for calibration. Data-quality review determines which intervals to retain. Excluded intervals contribute no measured energy.")
    paragraph(f"Measured window: {measured_window(c_request, calibration['result'])}. "
              f"Interval: {words(c_request.get('interval_value'))} {words(c_request.get('interval_unit')).removesuffix('s') if c_request.get('interval_value') == 1 else words(c_request.get('interval_unit'))}. "
              f"Optional AC operating limit: {capacity(c_request['curtailment_limit_kw'] * 1000, 'ac')+' per system' if c_request.get('curtailment_enabled') and c_request.get('curtailment_limit_kw') is not None else 'disabled' if c_request.get('curtailment_enabled') is False else 'not recorded'}.")
    table(["Collected rows","Excluded rows","Excluded share","Retained rows"],[[number(cleaning.get(k),0 if k!='excluded_row_pct' else 1)+('%' if k=='excluded_row_pct' and cleaning.get(k) is not None else '') for k in ("original_rows","excluded_rows","excluded_row_pct","final_rows")]],numeric=(0,1,2,3),keep=True)
    decisions=cleaning.get("decisions") or []
    actions=sorted({words(row.get("action")) for row in decisions})
    paragraph(f"Quality review: {len(decisions)} recorded issue decisions" + (f" ({', '.join(actions)})" if actions else "") + ". Issue counts can overlap. The counts above describe reviewed rows; unavailable fields are not replaced by estimates.", "small")
    if decisions:
        decision_rows=[]
        for decision in decisions:
            decision_rows.append([quality_issue_label(decision),
                                  words(decision.get('action')),number(decision.get('affected_rows'),0)])
        table(["Reviewed issue","Decision","Affected rows"],decision_rows,[.58,.22,.2],numeric=(2,))

    heading("Modeling and Calibration", "calibration")
    if appendix.physics_description_supported(job):
        paragraph("The Python PV model translates weather and tracker geometry into effective irradiance, module temperature and electrical power. SolarEdge aggregates individual module maximum-power predictions; Solectria represents string mismatch and the common inverter operating point. Recorded conversion efficiencies and operating limits produce AC power.")
        paragraph("After review of flagged data-quality issues, separate seasonal factors are fitted for each system to reconcile retained measured AC energy with the model. When an operating ceiling is active, fitting accounts for clipping. Annual simulation uses the resolved frozen factors, including any explicitly recorded seasonal substitution, rather than fitting historical weather again.")
    else:
        paragraph("The saved calibration compares measured energy with the Python model before and after fitting. A reviewed description of the detailed electrical and fitting implementation is unavailable for this historical physics identity; the report retains its saved results without substituting current model details.")
    energy_rows=[]
    for _,label,prefix in SYSTEMS:
        energy_rows.append([label,number(stats.get(prefix+"_measured_kwh",0)/1000 if stats.get(prefix+"_measured_kwh") is not None else None,1),
                           number((stats.get("uncalibrated") or {}).get(prefix+"_predicted_kwh",0)/1000 if (stats.get("uncalibrated") or {}).get(prefix+"_predicted_kwh") is not None else None,1),
                           number(stats.get(prefix+"_predicted_kwh",0)/1000 if stats.get(prefix+"_predicted_kwh") is not None else None,1)])
    table(["SolarTAC energy (MWh)","Measured","Before fit","After fit"],energy_rows,[.37,.21,.21,.21],numeric=(1,2,3),keep=True)
    energy_series=[]
    for label,data,suffix in (("Measured",stats,"_measured_kwh"),("Before fit",stats.get("uncalibrated") or {},"_predicted_kwh"),("After fit",stats,"_predicted_kwh")):
        if all(data.get(prefix+suffix) is not None for _,_,prefix in SYSTEMS):
            energy_series.append({"label":label,"values":[data[prefix+suffix]/1000 for _,_,prefix in SYSTEMS]})
    chart("bars",{"labels":[label for _,label,_ in SYSTEMS],"series":energy_series,"ylabel":"AC energy (MWh)"},2.1,"Energy covers the retained measured-data intervals at SolarTAC. Agreement after fitting is calibration, not an independent prediction test.")
    seasons=(calibration["result"].get("calibration_factors") or stats.get("calibration_factors") or {}).get("seasons") or []
    season_rows=[]
    for season in seasons:
        season_rows.append([words(season.get("season")).title(),f"{display_date(season.get('first_timestamp'))}\nto {display_date(season.get('last_timestamp'))}",number(season.get("row_count"),0),
                            *[number((season.get("systems",{}).get(key) or {}).get("factor"),4) for key,_,_ in SYSTEMS]])
    heading("Fitted calibration factors", "fitted-factors",level=2)
    table(["Season","Observed coverage","Rows","Solectria factor","SolarEdge factor"],season_rows,[.13,.34,.13,.2,.2],numeric=(2,3,4),keep=len(season_rows)<=4)
    paragraph("Seasonal date ranges describe observed coverage, not complete seasons. Agreement after fitting demonstrates calibration to these measurements; independent predictive validation requires separate observations.", "small")
    for season in seasons:
        try:
            first = datetime.fromisoformat(str(season.get('first_timestamp')).replace('Z','+00:00')).date()
            last = datetime.fromisoformat(str(season.get('last_timestamp')).replace('Z','+00:00')).date()
            span = (last-first).days+1
        except (ValueError, TypeError):
            continue
        if 0 < span <= 31:
            paragraph(f"Coverage limitation: {words(season.get('season')).title()} observations span only {span} calendar days ({display_date(season.get('first_timestamp'))} to {display_date(season.get('last_timestamp'))}), with {number(season.get('row_count'),0)} retained rows. Applying this fitted factor to a complete season extrapolates beyond that observed window.","small")

    blocks.extend(appendix.applied_calibration_blocks(job))
    heading("Annual Simulation", "annual")
    annual_rows=annual["result"].get("annual_energy_by_year") or []
    eligible=snapshot.get("eligible_paired_energy_rows") or []
    paragraph("The model uses historical MIDC weather from SolarTAC, saved seasonal factors and operating limits to predict annual AC energy. Annual predictions cover full weather years; calibration covers only the measured intervals.")
    paragraph(f"{len(eligible)} eligible paired weather years. The table and chart show SolarTAC-scale AC energy; commercial costs and LCOE use the {target_text} scenario.")
    table(["Weather year","Coverage","Solectria MWh","SolarEdge MWh","Eligible"],[[words(row.get("year")),number(row.get("annual_coverage_pct"),1)+('%' if row.get('annual_coverage_pct') is not None else ''),
          *[number(row[prefix+"_predicted_kwh"]/1000 if row.get(prefix+"_predicted_kwh") is not None else None,1) for _,_,prefix in SYSTEMS],words(row.get("cdf_eligible"))] for row in annual_rows],[.17,.18,.23,.23,.19],numeric=(0,1,2,3),compact=True)
    series=[]
    for _,label,prefix in SYSTEMS:
        available=[row for row in annual_rows if row.get("year") is not None and row.get(prefix+"_predicted_kwh") is not None]
        if available:
            series.append({"label":label,"x":[row['year'] for row in available],"values":[row[prefix+'_predicted_kwh']/1000 for row in available]})
    chart("annual",{"series":series,"ylabel":"AC energy (MWh)"},2.05,"Lines connect the recorded weather years for comparison; intervening unselected years have not been simulated.")
    paragraph(energy_comparison("Retained measured intervals",stats.get('sol_measured_kwh'),stats.get('se_measured_kwh')),"small")
    if len(eligible)>=5:
        annual_medians = [float(np.quantile([row[prefix+'_predicted_kwh'] for row in eligible],.5,method='linear')) for _,_,prefix in SYSTEMS]
        paragraph(energy_comparison("Predicted annual medians",*annual_medians),"small")
    heading("Understanding the energy difference", "energy-difference", level=2)
    frozen_energy = energy_evidence['frozen']
    energy_diagnostic = energy_evidence['artifact_diagnostic']
    if energy_diagnostic.get('status') == 'reconciled_current_artifacts':
        reconciliation = energy_diagnostic['reconciliation']
        capacities = frozen_energy.get('capacities') or {}
        paragraph(f"The same {number(reconciliation['paired_measurement_rows'],0)} retained timestamps contain finite measurements for both systems and match the SHA-verified reviewed source. The review uses one combined exclusion mask. "
                  f"Installed capacities: Solectria {capacity(capacities.get('solectria'),'dc')}; SolarEdge {capacity(capacities.get('solaredge'),'dc')}. "
                  "The frozen factors and operating caps match the reconstructed intervals.","small")
        historical_hashes = all(energy_diagnostic['identity'][key].get('historical_bytes_verified') for key in ('annual','calibration'))
        hash_note = ("Both workbook byte hashes match their historical records." if historical_hashes else
                     "Historical byte hashes are unavailable for at least one workbook; current hashes identify this reconstruction.")
        paragraph("Diagnostic evidence: current calibration and annual workbooks reconcile to the frozen results. " + hash_note +
                  " Positive differences below mean Solectria produces more energy.","small")
        seasonal = energy_diagnostic['seasonal_rows']
        comparison_rows = [[row['season'].title(),number(row['measured']['difference_kwh']/1000 if row.get('measured') else None,2),
                            number(row['mean_prefit_annual']['difference_kwh']/1000,2),
                            number(row['mean_annual']['difference_kwh']/1000,2)] for row in seasonal]
        measured_gap = (frozen_energy.get('measured_comparison') or {}).get('difference_kwh')
        comparison_rows.append(['Total',number(measured_gap/1000 if measured_gap is not None else None,2),
                               *[number(sum(row[key]['difference_kwh'] for row in seasonal)/1000,2)
                                 for key in ('mean_prefit_annual','mean_annual')]])
        table(['Season','Measured gap (MWh)','Mean annual gap before fit (MWh)','Mean annual gap after fit (MWh)'],
              comparison_rows,[.16,.24,.30,.30],numeric=(1,2,3),keep=True)
        paragraph("Annual columns average the same eligible full weather years; the measured column covers only retained observations. Before/after fitting includes interactions between calibration factors and operating caps, so these columns do not separate independent physical causes. Seasonal means sum to the mean annual gap, not the difference of system medians.","small")
        sensitivity = energy_diagnostic.get('fall_sensitivity') or {}
        if sensitivity.get('status') == 'available':
            heading("Fall calibration sensitivity (diagnostic only)", "fall-sensitivity", level=2)
            factors = sensitivity['changed_factors']
            paragraph("Replace only each system's fall factor with its own summer factor: " + '; '.join(
                f"{label} {number(factors[key]['baseline_fall'],4)} to {number(factors[key]['diagnostic_fall'],4)}"
                for key,label,_ in SYSTEMS) + ". Keep weather, all other factors, capacities and caps fixed.","lead")
            table(['Scenario','Difference of system medians (MWh)','Median paired gap (MWh)','Mean paired gap (MWh)'],
                  [[label,number(value['difference_of_system_medians']['difference_kwh']/1000,2),
                    number(value['median_of_paired_differences_kwh']/1000,2),number(value['mean_paired_difference_kwh']/1000,2)]
                   for label,value in [('Saved baseline',frozen_energy['annual_comparison']),('Fall uses summer factors',sensitivity['scenario'])]],
                  [.28,.25,.24,.23],numeric=(1,2,3),keep=True)
            paragraph("Reconstruction: P′ = min(Psaved × fsummer / ffall, cap) for fall intervals. Both ratios are at least one, so this preserves clipping exactly, including previously capped intervals. This joint sensitivity includes cap interactions; it does not establish that summer factors are correct for fall. The saved run and LCOE results remain unchanged.","small")
        else:
            paragraph("Fall sensitivity unavailable: " + str(sensitivity.get('reason') or 'insufficient saved evidence') + '.',"small")
        cap_rows = {key:sum(row['mean_at_cap_rows'][key] for row in seasonal) for key,_,_ in SYSTEMS}
        paragraph("Operating caps bind for an annual average of " + ', '.join(f"{number(cap_rows[key],1)} intervals for {label}" for key,label,_ in SYSTEMS)
                  + ". The stored before-fit powers are already capped; these exports cannot recover exact losses from removing the cap. Confidence in full-season transfer depends on the measured coverage listed above; a replacement factor needs representative fall measurements.","small")
    else:
        measured_seasons = [row for row in frozen_energy['seasonal_rows'] if row.get('measured')]
        if measured_seasons:
            table(['Season','Retained measured Solectria − SolarEdge (MWh)'],
                  [[row['season'].title(),number(row['measured']['difference_kwh']/1000,2)] for row in measured_seasons],[.3,.7],numeric=(1,))
        paragraph("Interval-level seasonal and controlled comparisons are unavailable: " + energy_diagnostic.get('reason','supporting artifacts unavailable') +
                  " Frozen totals remain valid, but they do not quantify individual factor or cap contributions.","small")
    heading("Annual energy distribution", "annual-distribution", level=2, page=True)
    interpolation_series = []
    for _, label, prefix in SYSTEMS:
        values = [row[prefix+'_predicted_kwh']/1000 for row in eligible if row.get(prefix+'_predicted_kwh') is not None]
        points = annual_interpolation_points(values)
        if points is not None:
            interpolation_series.append({'label':label, 'x':points[0], 'probability':points[1]})
        else:
            paragraph(label + ': interpolation requires at least two complete years with distinct energies.', 'small')
    chart('annual_cdf', {'series':interpolation_series}, 3.0,
          'Straight-line interpolation between the observed annual energies, matching the dashboard. Points use midpoint ranks with average ranks for ties. No probability tails are extrapolated beyond the observed range.')
    paragraph('This display interpolation is distinct from the empirical cumulative distribution. The percentile table uses the existing type-7 quantile method; it is not read from the interpolated curve.', 'small')
    if len(eligible)>=5:
        table(["SolarTAC annual energy","P50 (MWh)","P90 exceedance (MWh)"],[[label,*[number(np.quantile([r[prefix+'_predicted_kwh'] for r in eligible],p,method='linear')/1000,1) for p in (.5,.1)]] for _,label,prefix in SYSTEMS],[.4,.25,.35],numeric=(1,2),keep=True)
        paragraph("Energy P90 is the 10th cumulative percentile: energy exceeded in an estimated 90% of cases. " + ("It is provisional with 5–9 complete years; the dashboard exceedance view requires ten complete years." if len(eligible)<10 else "These historical estimates retain finite-sample uncertainty."),"small")
    else:
        paragraph("Annual percentiles are withheld because fewer than five complete years are available.","small")
    excluded=snapshot.get("excluded_annual_energy_rows") or []
    if excluded:
        table(["Excluded weather year","Reason"],[[words((row.get('row') or {}).get('year')),words(row.get('reasons'))] for row in excluded],[.22,.78])
    else:
        paragraph("No weather years are excluded in the frozen annual source.","small")

    heading("Technoeconomic Analysis", "technoeconomic-analysis",page=True)
    paragraph(f"The {finance.get('project_life_years','recorded')}-year commercial comparison scales each system's annual SolarTAC AC energy by its own applied source capacity to the common {target_text} target. The declared DC capacity provides the cost basis; it does not independently multiply energy.")
    paragraph("Each Monte Carlo realization pairs a historical weather year, real discount rate and degradation across the systems. The recorded distributions describe sampled cost and finance assumptions. LCOE is discounted lifecycle cost divided by discounted AC energy, including initial investment, annual O&M and only explicitly recorded scheduled costs.")
    costs = metadata.get("summaries",{}).get("paired_commercial_cost_line_summaries") or []
    cost_rows=[]
    for category,label,unit in (("full_initial_capex","Initial investment","USD million"),("full_annual_om","Annual O&M","USD million/year")):
        cells=[]
        for key,_,_ in SYSTEMS:
            found=[item for item in costs if item.get("technology")==key and item.get("cost_category")==category]
            cells.append(q(found[0],scale=1e-6,digits=3) if len(found)==1 else "Not available")
        cost_rows.append([f"{label} ({unit})",*cells])
    table(["Saved cost medians","Solectria","SolarEdge"],cost_rows,[.52,.24,.24],numeric=(1,2),keep=True)
    paragraph("These are medians of saved cost realizations. Deterministic midpoint costs below describe the assumption ranges separately.", "small")
    heading("Assumptions and cost breakdown", "assumptions",level=2)
    ratio=shared.get("dc_capacity_w",0)/target_w if shared and target_w else None
    inputs=[["Commercial capacity",target_text + (f"; {capacity(shared['dc_capacity_w'], 'dc')} cost basis" if shared else "")],
            ["Project life / realizations",f"{finance.get('project_life_years','Not recorded')} years / {number(request.get('n'),0)}"],
            ["Real discount rate",distribution((finance.get('real_discount_rate') or {}).get('distribution'),100)+"% per year"],
            ["Annual degradation",distribution(((request.get('shared_degradation') or {}).get('annual_rate') or {}).get('distribution'),100)+"% per year"],
            ["Dollar basis",f"Proposed real {finance.get('constant_dollar_cost_year','unrecorded')} USD"]]
    if assumptions_status in {"approved_defaults", "modified"}:
        inputs.insert(0, ["Recorded assumptions selection", "Comparison defaults (saved preset)" if assumptions_status == "approved_defaults" else "Modified assumptions"])
    if shared:
        inputs += [["Common initial CAPEX",distribution(shared.get('common_capex_wdc'),digits=2)+" USD/Wdc"],
                   ["SolarEdge optimizer installation",distribution(shared.get('optimizer_installation_wdc'),digits=3)+" USD/Wdc"],
                   ["SolarEdge optimizer hardware",f"{number(shared.get('optimizer_count'),0)} units x ${number(shared.get('optimizer_unit_price_usd'))}"]]
    for key,label,_ in SYSTEMS:
        system=next((s for s in scenario.get('systems',[]) if s.get('technology')==key),{})
        for line in system.get('cost_lines',[]):
            if shared and line.get('cost_category')=='full_initial_capex':
                continue
            is_om=line.get('unit')=='constant_usd_per_target_w_year' and ratio
            units='USD/kWdc-year' if is_om else {'constant_usd_per_target_w':'USD/W of target capacity','constant_usd_per_target_w_year':'USD/W of target capacity per year','constant_usd':'USD'}.get(line.get('unit'),words(line.get('unit')))
            timing = "; at year-end in years " + ", ".join(str(year) for year in line.get('occurrence_years', [])) if line.get('timing') == 'scheduled_year_end' else ""
            inputs.append([label+' '+('annual O&M' if line.get('cost_category')=='full_annual_om' else words(line.get('label'))),distribution(line.get('distribution'),1000/ratio if is_om else 1)+" "+units+timing])
    table(["Input","Saved assumption"],inputs,[.37,.63])
    if assumptions_status == "modified":
        paragraph("These inputs were modified from the approved defaults. Changing the dollar year does not automatically inflation-adjust input costs. Later vendor or market prices remain unadjusted proxies unless the saved cost evidence explicitly documents an adjustment.","small")
    elif assumptions_status == "approved_defaults":
        paragraph("The saved record identifies the comparison preset as approved defaults. The cost-year and maintenance qualifications remain unresolved. Exporting the report changes no assumptions.","small")
    if shared:
        paragraph("The same common CAPEX draw is used for both systems. SolarEdge adds fixed optimizer hardware and independently sampled installation. Its total is derived from these inputs; the support range is not independently sampled. O&M draws are independent by system.","small")
        allocations=context.get('component_allocations') or []
        if allocations:
            heading("Common CAPEX component allocations", "components",level=2)
            table(["Component","Midpoint USD/Wdc"],[[row['label'],number(row.get('midpoint_wdc'),3)] for row in allocations]+[["Sum",number(sum(row['midpoint_wdc'] for row in allocations),3)]],[.73,.27],numeric=(1,))
        base=midpoint(shared['common_capex_wdc']); install=midpoint(shared['optimizer_installation_wdc'])
        if base is not None and install is not None:
            sol=base*shared['dc_capacity_w']; se=sol+shared['optimizer_count']*shared['optimizer_unit_price_usd']+install*shared['dc_capacity_w']
            paragraph(f"Deterministic midpoint initial investment: Solectria ${sol/1e6:,.3f} million; SolarEdge ${se/1e6:,.3f} million." + (" Component allocations explain the base total and are not additional sampled costs." if allocations else ""),"small")
        rating_label = 'AC' if scenario.get('target_rating_basis')=='ac_operating_limit' else 'DC'
        paragraph(f"DC cost intensities convert to the {rating_label} target-capacity basis using {number(ratio,2)}. This ratio does not multiply energy. Cost coverage follows the recorded cost lines and scenario qualifications in the Executive Summary.","small")

    heading("Lifecycle LCOE comparison", "lifecycle-comparison", level=2)
    paragraph(f"Lifecycle LCOE over {finance.get('project_life_years', 'the recorded project life')} years, using the verified realizations from this run.","lead")
    if lifecycle_chart:
        blocks.append({"kind":"chart", **lifecycle_chart,
                       "caption":"Lifecycle LCOE empirical CDF from saved realizations. Lower LCOE is better; each curve shows the share of results at or below that cost. Percentiles match the Executive Summary."})
    else:
        paragraph("The completed-run lifecycle LCOE chart is unavailable.", "small")
    summary_rows = []
    for label, suffix, scale in (("Discounted lifecycle cost (USD million)", "LifecycleCost_USD", 1e-6),
                                 ("Discounted lifecycle AC energy (GWh)", "LifecycleEnergy_kWh_AC", 1e-6)):
        summary_rows.append([label, *[q(metadata.get('summaries', {}).get('Commercial'+system+suffix) or {}, scale=scale, digits=3)
                                     for system in ('Solectria', 'SolarEdge')]])
    table(["Saved lifecycle medians", "Solectria", "SolarEdge"], summary_rows, [.52, .24, .24], numeric=(1,2), keep=True)
    paragraph("LCOE is calculated separately for every realization as discounted lifecycle cost divided by discounted energy. Dividing the two medians above need not reproduce median LCOE.", "small")

    convergence=metadata.get('convergence') or {}
    paragraph("Saved convergence status: "+words(convergence.get('status') or 'not recorded').capitalize()+".")
    if convergence.get('reasons') or convergence.get('reason'):
        metric_labels={item.get('headline_metric_id'):label+' LCOE' for key,label,_ in SYSTEMS if (item:=system_results.get(key))}
        metric_labels[(paired.get('lcoe_delta_se_minus_sol') or {}).get('headline_metric_id')]='paired LCOE difference'
        reasons=convergence.get('reasons') or [convergence.get('reason')]
        for reason in reasons:
            parts=str(reason).split(':')
            if len(parts)==3 and parts[0] in ('absolute_quantile_change','relative_quantile_change','undefined_quantile'):
                condition={'absolute_quantile_change':'absolute-change tolerance was exceeded',
                           'relative_quantile_change':'relative-change tolerance was exceeded',
                           'undefined_quantile':'quantile was unavailable'}[parts[0]]
                paragraph(f"Saved criterion: {metric_labels.get(parts[1],words(parts[1]))} {parts[2].upper()} {condition}.","small")
            else:
                paragraph("Saved criterion: "+words(reason)+".","small")
    paragraph("Sampling stability does not validate the input assumptions or measured-to-commercial transfer. " + ("P10/P50/P90 stability plots and detailed methods are included in the technical appendix." if include_technical_appendix else "The technical appendix was omitted for this export."),"small")

    heading("Input sensitivity", "sensitivity", level=2)
    paragraph("Larger bars show stronger influence in the saved rank regression. Positive coefficients increase LCOE rank; negative coefficients decrease it. Coefficients are dimensionless associations, not dollar changes or causal effects.","lead")
    labels = diagnostics.predictor_labels(scenario)
    for payload in diagnostics.tornado_payloads(metadata,input_labels=labels):
        if payload['status']=='available':
            blocks.append({"kind":"chart", "image":diagnostics.render_tornado(payload), "height":payload['height']*72,
                           "caption":f"{payload['label']} LCOE rank sensitivity. Bars show final standardized regression coefficients; sample count and final R-squared describe the saved fitted model."})
        else:
            paragraph(f"{payload['label']} sensitivity unavailable: {payload['reason']}.","small")
        if payload.get('notes'):
            paragraph(' '.join(payload['notes']),"small")

    if include_technical_appendix:
        heading("Technical Appendix", "technical-appendix", page=True)
        blocks.extend(appendix.build_technical_appendix(job))
        heading("LCOE percentile stability", "appendix-convergence", level=2, page=True)
        paragraph("P10/P50/P90 are recalculated over increasing prefixes of the saved realizations. Final points match the headline table. These are subsets of one experiment, not new simulations.","lead")
        for payload in diagnostics.convergence_payloads(metadata,calculation.by_name,routine,row_count=calculation.row_count):
            if payload['status']=='available':
                blocks.append({"kind":"chart", "image":diagnostics.render_convergence(payload), "height":payload['height']*72,
                               "caption":f"{payload['label']} cumulative LCOE percentiles in USD/MWh. Original realization ordering is preserved."})
            else:
                paragraph(f"{payload['label']} percentile stability unavailable: {payload['reason']}.","small")
            if payload.get('status')=='available' and len(payload.get('checkpoints',[]))<2:
                paragraph("Only one checkpoint was saved; a stability trend cannot be assessed.","small")
        paragraph("The original convergence checks remain unchanged. These plots show sampling stability; they do not define confidence intervals.","small")

    heading("References and Evidence", "references",page=True)
    paragraph(f"Verification: {len(checks)} saved-result and export checks passed, together with independent reference cases. Report rendering does not rerun the model or alter the saved analysis.","small")
    if shared:
        citation=(shared.get('evidence') or {}).get('citation') or {}
        source_title=citation.get('title') or 'the recorded TEA assumptions'
        if assumptions_status == "modified":
            paragraph(f"Assumption origin: {source_title}. The original approval does not apply to the modified scenario. Evidence consists of metadata and excerpts; vendor quote files are not independently archived.","small")
            if citation.get('excerpt_or_derivation_note'):
                paragraph("Recorded cost note: " + words(citation['excerpt_or_derivation_note']),"small")
        else:
            paragraph(f"Cost source: {source_title}. The preserved meeting/email assumptions combine benchmark allocations, vendor estimates and provisional O&M. Evidence consists of metadata and excerpts; vendor quote files are not independently archived.","small")
    else:
        paragraph("Cost evidence and citations are preserved with the selected request and its numerical exports.","small")
    if include_technical_appendix:
        for reference_title,reference_url in appendix.APPENDIX_REFERENCES:
            blocks.append({"kind":"reference", "text":reference_title, "url":reference_url})
    heading("Technical record", "technical-record",level=2)
    model_contract=snapshot.get('model_contract') or {}
    table(["Record","Saved identifier"],[["TEA analysis",report['run_id']],["Annual simulation",request['source_annual_job_id']],["Calibration",calibration.get('id') or calibration.get('job_id') or 'Not recorded'],["Random seed",str(request.get('seed','Not recorded'))],
          ["Generating dashboard version",f"{identity['version']} ({identity['version_source']})"],
          ["Generating dashboard build",identity.get('build') or 'Not recorded'],
          ["Analysis dashboard version",(job.get('submission_provenance') or {}).get('dashboard_version') or 'Not recorded'],
          ["Analysis dashboard build",(job.get('submission_provenance') or {}).get('dashboard_build') or 'Not recorded'],
          ["Saved model version",model_contract.get('model_version') or 'Not recorded'],
          ["Saved physics version",model_contract.get('calibration_physics_version') or 'Not recorded'],
          ["Report format",REPORT_VERSION]],[.34,.66])
    paragraph("Generating version/build describes this export. A package label does not identify a deployed build. Historical versions are shown only when saved with the analysis.","small")
    if energy_diagnostic.get('status') == 'reconciled_current_artifacts':
        table(['Diagnostic source','Current workbook SHA-256'],[
            [label,energy_diagnostic['identity'][key]['sha256']] for key,label in (
                ('calibration','Calibration workbook'),('annual','Annual workbook'))],[.3,.7])
    return report
