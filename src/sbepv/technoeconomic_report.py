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

REPORT_VERSION = "2.2"
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
    return str(value).replace("_", " ").replace("solaredge", "SolarEdge").replace("solectria", "Solectria")


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


def build_report(job, calculation, routine, checks, *, generated_at=None, lifecycle_chart=None):
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
    finance = request.get("finance") or {}
    metadata = calculation.metadata
    blocks = []
    def paragraph(text, style="body"):
        blocks.append({"kind":"paragraph", "text":text, "style":style})
    def heading(text, anchor, *, page=False, level=1):
        blocks.append({"kind":"heading", "text":text, "anchor":anchor, "page":page, "level":level})
    def table(headers, rows, widths=None, numeric=(), *, keep=False):
        if not rows:
            paragraph("No supporting values were recorded.")
            return
        blocks.append({"kind":"table", "headers":headers, "rows":rows, "widths":widths, "numeric":list(numeric), "keep":keep or len(rows)<=3})
    def chart(kind, data, height, caption):
        if not data.get("series") and not data.get("panels"):
            paragraph("Chart unavailable because its saved observations are missing.")
            return
        blocks.append({"kind":"chart", "image":chart_image(kind,data,height), "height":height*72, "caption":caption})
    def q(value, key="p50", scale=1, digits=2):
        raw = (value.get("percentiles") or {}).get(key)
        return number(raw*scale if raw is not None else None, digits)
    def saved_series(metric, label, p50=None, scale=1):
        values = calculation.by_name.get(metric)
        if values is None or not len(values) or not np.all(np.isfinite(values)):
            return None
        return {"label":label,"values":(np.asarray(values,dtype=float)*scale).tolist(),"p50":p50*scale if p50 is not None else None}

    target_w = paired.get("target_capacity_w")
    target_text = capacity(target_w, "ac" if scenario.get("target_rating_basis")=="ac_operating_limit" else "dc")
    delta = paired.get("lcoe_delta_se_minus_sol") or {}
    delta_p50 = (delta.get("percentiles") or {}).get("p50")
    system_results = paired.get("systems") or {}
    report = {"title":"SolarEdge and Solectria PV comparison", "version":REPORT_VERSION,
              "generated_at":generated.isoformat(), "analysis_at":job.get("completed_at"),
              "run_id":str(job.get("id") or job.get("job_id")), "blocks":blocks}

    heading(report["title"], "summary")
    paragraph(f"SBE Innovation Center at SolarTAC  |  {target_text} commercial comparison", "subtitle")
    paragraph(f"Report date {display_date(generated.isoformat())}  |  Version {REPORT_VERSION}\nAnalysis completed {display_date(job.get('completed_at'),time=True)}", "meta")
    paragraph("Contents", "toc_title")
    blocks.append({"kind":"toc"})
    heading("Comparison summary", "comparison-summary", level=2)
    if delta_p50 is not None:
        favored = "Solectria" if delta_p50>0 else "SolarEdge" if delta_p50<0 else "Neither system"
        paragraph(f"{favored} has the lower median paired LCOE in this scenario. The median SolarEdge minus Solectria difference is ${delta_p50*1000:+.2f}/MWh.", "finding")
    else:
        paragraph("A paired LCOE comparison is unavailable in this saved result.", "finding")
    rows, lcoe_series = [], []
    for key,label,_ in SYSTEMS:
        result = system_results.get(key) or {}
        rows.append([label,*[q(result,p,1000) for p in ("p10","p50","p90")]])
        series = saved_series(result.get("headline_metric_id"),label,(result.get("percentiles") or {}).get("p50"),1000)
        if series:
            lcoe_series.append(series)
    table(["LCOE (USD/MWh)","P10","P50 median","P90"],rows,[.37,.21,.21,.21],numeric=(1,2,3),keep=True)
    paragraph("Lower LCOE means a lower discounted cost per unit of generated AC energy. P10 and P90 bound the middle 80% of this scenario's costs. The completed TEA chart appears in the lifecycle comparison section.", "small")
    if context.get("limitations"):
        paragraph("Scenario qualifications: " + words(context["limitations"]), "small")

    heading("Economic comparison", "economics", page=True)
    costs = metadata.get("summaries",{}).get("paired_commercial_cost_line_summaries") or []
    cost_rows=[]
    for category,label,unit in (("full_initial_capex","Initial investment","USD million"),("full_annual_om","Annual O&M","USD million/year")):
        cells=[]
        for key,_,_ in SYSTEMS:
            found=[item for item in costs if item.get("technology")==key and item.get("cost_category")==category]
            cells.append(q(found[0],scale=1e-6,digits=3) if len(found)==1 else "Not available")
        cost_rows.append([f"{label} ({unit})",*cells])
    table(["Saved cost medians","Solectria","SolarEdge"],cost_rows,[.52,.24,.24],numeric=(1,2),keep=True)
    paragraph("These are medians of saved cost realizations. The assumptions section separately shows deterministic midpoint costs.", "small")
    delta_series=saved_series(delta.get("headline_metric_id"),"Paired difference",delta_p50,1000)
    chart("paired",{"series":[delta_series] if delta_series else []},2.45,"Each difference pairs the same weather year, discount rate and degradation. The median of paired differences need not equal the difference of the two system medians.")
    if delta_series:
        values=np.asarray(delta_series["values"])
        wins=int(np.count_nonzero(values<0)); count=len(values)
        paragraph(f"SolarEdge has lower LCOE in {wins:,} of {count:,} saved realizations ({wins/count:.1%}, rounded to one decimal). " +
                  ("No lower-LCOE SolarEdge case occurred in this finite sample; this does not prove the real-world probability is zero." if wins==0 else "This frequency applies to the sampled assumptions, not a validated probability of future outcomes."), "small")

    heading("Calibration and data quality", "calibration",page=True)
    paragraph(f"Measured window: {measured_window(c_request, calibration['result'])}. "
              f"Interval: {words(c_request.get('interval_value'))} {words(c_request.get('interval_unit')).removesuffix('s') if c_request.get('interval_value') == 1 else words(c_request.get('interval_unit'))}. "
              f"AC clipping: {capacity(c_request['curtailment_limit_kw'] * 1000, 'ac')+' per system' if c_request.get('curtailment_enabled') and c_request.get('curtailment_limit_kw') is not None else 'disabled' if c_request.get('curtailment_enabled') is False else 'not recorded'}.")
    table(["Collected rows","Excluded rows","Excluded share","Retained rows"],[[number(cleaning.get(k),0 if k!='excluded_row_pct' else 1)+('%' if k=='excluded_row_pct' and cleaning.get(k) is not None else '') for k in ("original_rows","excluded_rows","excluded_row_pct","final_rows")]],numeric=(0,1,2,3),keep=True)
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
                            *[number((season.get("systems",{}).get(key) or {}).get("factor"),3) for key,_,_ in SYSTEMS]])
    table(["Season","Observed coverage","Rows","Solectria factor","SolarEdge factor"],season_rows,[.13,.34,.13,.2,.2],numeric=(2,3,4),keep=len(season_rows)<=4)
    decisions=cleaning.get("decisions") or []
    actions=sorted({words(row.get("action")) for row in decisions})
    paragraph(f"Quality review: {len(decisions)} recorded issue decisions" + (f" ({', '.join(actions)})" if actions else "") + ". Issue counts can overlap. Seasonal date ranges describe observed coverage, not complete seasons. Missing optional fields are reported as unavailable.", "small")

    heading("Annual production", "annual",page=True)
    annual_rows=annual["result"].get("annual_energy_by_year") or []
    eligible=snapshot.get("eligible_paired_energy_rows") or []
    paragraph(f"{len(eligible)} eligible paired weather years. The table and chart show SolarTAC-scale AC energy; commercial costs and LCOE use the {target_text} scenario.")
    table(["Weather year","Coverage","Solectria MWh","SolarEdge MWh","Eligible"],[[words(row.get("year")),number(row.get("annual_coverage_pct"),1)+('%' if row.get('annual_coverage_pct') is not None else ''),
          *[number(row[prefix+"_predicted_kwh"]/1000 if row.get(prefix+"_predicted_kwh") is not None else None,1) for _,_,prefix in SYSTEMS],words(row.get("cdf_eligible"))] for row in annual_rows],[.17,.18,.23,.23,.19],numeric=(0,1,2,3))
    series=[]
    for _,label,prefix in SYSTEMS:
        available=[row for row in annual_rows if row.get("year") is not None and row.get(prefix+"_predicted_kwh") is not None]
        if available:
            series.append({"label":label,"x":[row['year'] for row in available],"values":[row[prefix+'_predicted_kwh']/1000 for row in available]})
    chart("annual",{"series":series,"ylabel":"AC energy (MWh)"},2.05,"Lines connect the recorded weather years for comparison; intervening unselected years have not been simulated.")
    heading("Annual energy distribution", "annual-distribution", page=True)
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
        paragraph("Energy P90 is the 10th cumulative percentile: energy exceeded in an estimated 90% of cases. " + ("It is provisional with 5–9 complete years; exceedance estimates are withheld." if len(eligible)<10 else "These historical estimates retain finite-sample uncertainty."),"small")
    else:
        paragraph("Annual percentiles are withheld because fewer than five complete years are available.","small")
    excluded=snapshot.get("excluded_annual_energy_rows") or []
    if excluded:
        table(["Excluded weather year","Reason"],[[words((row.get('row') or {}).get('year')),words(row.get('reasons'))] for row in excluded],[.22,.78])
    else:
        paragraph("No weather years are excluded in the frozen annual source.","small")

    heading("Assumptions and cost breakdown", "assumptions",page=True)
    ratio=shared.get("dc_capacity_w",0)/target_w if shared and target_w else None
    inputs=[["Commercial capacity",target_text + (f"; {capacity(shared['dc_capacity_w'], 'dc')} cost basis" if shared else "")],
            ["Project life / realizations",f"{finance.get('project_life_years','Not recorded')} years / {number(request.get('n'),0)}"],
            ["Real discount rate",distribution((finance.get('real_discount_rate') or {}).get('distribution'),100)+"% per year"],
            ["Annual degradation",distribution(((request.get('shared_degradation') or {}).get('annual_rate') or {}).get('distribution'),100)+"% per year"],
            ["Dollar basis",f"Proposed real {finance.get('constant_dollar_cost_year','unrecorded')} USD"]]
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
    if shared:
        paragraph("The same common CAPEX draw is used for both systems. SolarEdge adds fixed optimizer hardware and independently sampled installation. Its total is derived from these inputs; the support range is not independently sampled. O&M draws are independent by system.","small")
        allocations=context.get('component_allocations') or []
        if allocations:
            heading("Common CAPEX component allocations", "components",level=2)
            table(["Component","Midpoint USD/Wdc"],[[row['label'],number(row.get('midpoint_wdc'),3)] for row in allocations]+[["Sum",number(sum(row['midpoint_wdc'] for row in allocations),3)]],[.73,.27],numeric=(1,))
        base=midpoint(shared['common_capex_wdc']); install=midpoint(shared['optimizer_installation_wdc'])
        if base is not None and install is not None:
            sol=base*shared['dc_capacity_w']; se=sol+shared['optimizer_count']*shared['optimizer_unit_price_usd']+install*shared['dc_capacity_w']
            paragraph(f"Deterministic midpoint initial investment: Solectria ${sol/1e6:,.3f} million; SolarEdge ${se/1e6:,.3f} million. Component allocations explain the base total and are not additional sampled costs.","small")
        paragraph(f"DC cost intensities convert to the AC calculation basis using {number(ratio,2)}. This ratio does not multiply energy. Cost coverage follows the recorded cost lines and any scenario qualifications on the opening page.","small")

    heading("Lifecycle LCOE comparison", "lifecycle-comparison", page=True)
    paragraph(f"Full {finance.get('project_life_years', 'recorded')}-year commercial project comparison. The chart below is the verified chart generated when this TEA completed.")
    if lifecycle_chart:
        blocks.append({"kind":"chart", **lifecycle_chart,
                       "caption":"Completed-run lifecycle LCOE CDF. Lower values indicate a lower discounted cost per unit of AC energy. The chart retains its original values, system colors and empirical CDF method."})
    else:
        paragraph("The completed-run lifecycle LCOE chart is unavailable.", "small")
    summary_rows = []
    for label, suffix, scale in (("Discounted lifecycle cost (USD million)", "LifecycleCost_USD", 1e-6),
                                 ("Discounted lifecycle AC energy (GWh)", "LifecycleEnergy_kWh_AC", 1e-6)):
        summary_rows.append([label, *[q(metadata.get('summaries', {}).get('Commercial'+system+suffix) or {}, scale=scale, digits=3)
                                     for system in ('Solectria', 'SolarEdge')]])
    table(["Saved lifecycle medians", "Solectria", "SolarEdge"], summary_rows, [.52, .24, .24], numeric=(1,2), keep=True)
    paragraph("LCOE is calculated separately for every realization as discounted lifecycle cost divided by discounted energy. Dividing the two medians above need not reproduce median LCOE.", "small")

    heading("Convergence and method", "method",page=True)
    convergence=metadata.get('convergence') or {}
    paragraph("Saved convergence status: "+words(convergence.get('status') or 'not recorded').capitalize()+".")
    if convergence.get('reasons') or convergence.get('reason'):
        paragraph(words(convergence.get('reasons') or convergence.get('reason')),"small")
    checkpoints=convergence.get('checkpoints') or []
    if checkpoints and delta.get('headline_metric_id'):
        table(["Realizations","Paired P5","Paired P50","Paired P95"],[[number(row.get('realization_count'),0),*[q((row.get('metrics') or {}).get(delta['headline_metric_id']) or {},p,1000) for p in ('p5','p50','p95')]] for row in checkpoints],[.25,.25,.25,.25],numeric=(0,1,2,3))
        paragraph("Checkpoint values are in USD/MWh. P5/P95 describe the middle 90% of the paired LCOE difference; they differ from the P10/P90 headline interval. Stability does not validate the input assumptions.","small")
    else:
        paragraph("Paired convergence checkpoints are unavailable in the saved record.","small")
    heading("Calculation method", "calculation-method",level=2)
    paragraph("Reviewed measured intervals establish seasonal calibration factors. The annual model applies the frozen factors and physics settings to historical weather, retaining each year's two-system pairing. Commercial energy equals SolarTAC annual AC energy divided by each system's applied capacity, then multiplied by the target capacity.")
    paragraph(f"For each realization, energy degrades over {finance.get('project_life_years','the recorded number of')} years. LCOE divides discounted lifecycle costs by discounted AC energy using the same real discount rate. Initial investment occurs at project start; O&M is paid at each year end. Only explicitly recorded scheduled costs are included.")
    paragraph(f"Verification: {len(checks)} saved-result and export checks passed, together with independent reference cases. Report rendering does not rerun the model or alter the saved analysis.","small")
    heading("References and evidence", "references",level=2)
    if shared:
        citation=(shared.get('evidence') or {}).get('citation') or {}
        source_title=citation.get('title') or 'the recorded TEA assumptions'
        paragraph(f"Cost source: {source_title}. The preserved meeting/email assumptions combine benchmark allocations, vendor estimates and provisional O&M. Evidence consists of metadata and excerpts; vendor quote files are not independently archived.","small")
    else:
        paragraph("Cost evidence and citations are preserved with the selected request and its numerical exports.","small")
    heading("Technical record", "technical-record",level=2)
    table(["Record","Saved identifier"],[["TEA analysis",report['run_id']],["Annual simulation",request['source_annual_job_id']],["Calibration",calibration.get('id') or calibration.get('job_id') or 'Not recorded'],["Random seed",str(request.get('seed','Not recorded'))]],[.27,.73])
    return report
