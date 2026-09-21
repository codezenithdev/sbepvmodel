"""Shared presentation model for PDF and Word; consumes verified saved evidence.

No model execution, sampling, storage writes, or baseline lookup belongs here.
Chart images and all displayed tables are shared by both document renderers.
"""
from __future__ import annotations

import base64
from datetime import datetime, timezone
from decimal import Decimal, localcontext, ROUND_HALF_UP
from io import BytesIO
import math
import re
import textwrap

import numpy as np
from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.ticker import PercentFormatter, MaxNLocator, StrMethodFormatter
from sbepv import technoeconomic_report_diagnostics as diagnostics
from sbepv import technoeconomic_report_appendix as appendix
from sbepv.technoeconomic_report_metadata import normalize_analysis_name

REPORT_VERSION = "2.5.1"
REPORT_TITLE = "Technoeconomic Analysis of Module-Level and Central Optimization in Solar PV Systems"
REPORT_SUBTITLE = "Evaluation of SolarEdge and Solectria PV systems at SolarTAC"
SYSTEMS = (("solectria", "Solectria", "sol"), ("solaredge", "SolarEdge", "se"))
COLORS = ("#CC921A", "#2E66A3", "#454545")


def number(value, digits=2):
    # Counts remain integers; displayed measurements use two decimals only.
    digits = 0 if digits == 0 else 2
    if value is None:
        return "Not available"
    try:
        value = float(value)
        if not math.isfinite(value):
            return "Not available"
        with localcontext() as context:
            context.rounding = ROUND_HALF_UP
            return f"{Decimal(str(value)):,.{digits}f}"
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
    return f"{number(value / scale)} {unit}{basis}"


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
    if isinstance(value, float):
        return number(value)
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
    fig = Figure(figsize=(diagnostics.CHART_WIDTH_INCHES, height), dpi=320, facecolor="white")
    font_size = diagnostics.CHART_FONT_SIZE
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
                    ax.text(value + limit*.018, j, f"{value:.2f}", va="center", fontsize=font_size)
            ax.set_title(panel["label"] + "\nR² = " + number(panel.get("r_squared"), 3), fontsize=font_size, loc="left", pad=12)
            ax.set_xlim(0, limit)
            ax.set_xlabel("Incremental R²", fontsize=font_size)
            ax.xaxis.set_major_locator(MaxNLocator(3))
            ax.xaxis.set_major_formatter(StrMethodFormatter('{x:,.2f}'))
            ax.set_yticks(y, [textwrap.fill(label, 23) for label in labels])
            ax.tick_params(axis="y", length=0, labelsize=font_size)
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
            ax.yaxis.set_major_formatter(PercentFormatter(1, decimals=0))
            ax.xaxis.set_major_formatter(StrMethodFormatter('{x:,.6g}'))
            ax.set_ylabel('Cumulative probability', fontsize=font_size)
            ax.set_xlabel('SolarTAC annual AC energy (MWh)', fontsize=font_size)
            ax.legend(loc='lower left', bbox_to_anchor=(0, 1.02), ncols=2, frameon=False, fontsize=font_size, borderaxespad=0)
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
                                textcoords="offset points", fontsize=font_size, color=COLORS[i],
                                bbox={"facecolor":"white", "edgecolor":"none", "pad":2},
                                arrowprops={"arrowstyle":"-", "color":COLORS[i], "lw":.8})
            ax.set_ylim(0, 1.04)
            ax.yaxis.set_major_formatter(PercentFormatter(1, decimals=0))
            ax.xaxis.set_major_formatter(StrMethodFormatter('{x:,.6g}'))
            ax.set_ylabel("Cumulative probability", fontsize=font_size)
            ax.set_xlabel("LCOE (USD/MWh)" if kind=="cdf" else "SolarEdge minus Solectria LCOE (USD/MWh)", fontsize=font_size)
            if kind == "paired":
                values = np.asarray(series[0]["values"])
                extent = max(float(np.max(np.abs(values))), .01)
                low, high = min(float(np.min(values)), 0)-extent*.16, max(float(np.max(values)), 0)+extent*.16
                ax.set_xlim(low, high)
                ax.axvline(0, color="#555555", linestyle=":", linewidth=1)
                ax.text(.01, 1.07, "Negative: favors SolarEdge", transform=ax.transAxes, fontsize=font_size)
                ax.text(.99, 1.07, "Positive: favors Solectria", transform=ax.transAxes, ha="right", fontsize=font_size)
        elif kind == "bars":
            labels = payload["labels"]
            for i, item in enumerate(series):
                x = np.arange(len(labels)) + (i-(len(series)-1)/2)*(.78/len(series))
                ax.bar(x, item["values"], width=.78/len(series), label=item["label"], color=COLORS[i], hatch=("", "//", "..")[i % 3])
            ax.set_xticks(np.arange(len(labels)), labels)
            ax.set_ylabel(payload["ylabel"], fontsize=font_size)
            ax.yaxis.set_major_formatter(StrMethodFormatter('{x:,.6g}'))
            ax.legend(loc="lower left", bbox_to_anchor=(0,1.02), ncols=len(series), frameon=False, fontsize=font_size, borderaxespad=0)
        else:
            for i, item in enumerate(series):
                ax.plot(item["x"], item["values"], label=item["label"], color=COLORS[i], linestyle=("-", "--")[i%2], marker=("o", "s")[i%2], markersize=4)
            ax.set_ylabel(payload["ylabel"], fontsize=font_size)
            ax.set_xlabel(payload.get("xlabel", "Weather year"), fontsize=font_size)
            ax.xaxis.set_major_locator(MaxNLocator(integer=True))
            ax.xaxis.set_major_formatter(StrMethodFormatter('{x:.0f}'))
            ax.yaxis.set_major_formatter(StrMethodFormatter('{x:,.6g}'))
            ax.legend(loc="lower left", bbox_to_anchor=(0,1.02), ncols=2, frameon=False, fontsize=font_size, borderaxespad=0)
        # Probability charts need space for the percent ticks plus the vertical title.
        left = .15 if kind in ('annual_cdf', 'cdf', 'paired') else .12
        fig.subplots_adjust(left=left, right=.97, top=.84, bottom=.23 if height<2.5 else .19)
    for ax in axes:
        ax.grid(axis="x" if kind=="sensitivity" else "y", color="#DDDDDD", linewidth=.6)
        ax.set_axisbelow(True)
        ax.spines[["top", "right"]].set_visible(False)
        ax.spines[["bottom", "left"]].set_color("#AAAAAA")
        ax.tick_params(axis="both", labelsize=font_size)
        ax.xaxis.offsetText.set_fontsize(font_size)
        ax.yaxis.offsetText.set_fontsize(font_size)
    stream = BytesIO()
    canvas.print_png(stream)
    return base64.b64encode(stream.getvalue()).decode("ascii")


def median_lcoe_comparison(system_results):
    return ''.join(segment['text'] for segment in median_lcoe_comparison_segments(system_results))


def median_lcoe_comparison_segments(system_results, *, include_medians=True):
    """Compare marginal medians; the median paired delta is a different statistic."""
    medians = [(system_results.get(key) or {}).get("percentiles", {}).get("p50") for key, _, _ in SYSTEMS]
    if any(value is None or not math.isfinite(float(value)) for value in medians):
        return [{'text': "The difference between system median LCOEs is unavailable in this saved result."}]
    difference = (medians[1] - medians[0]) * 1000
    if difference == 0:
        return [
            {'text': "The equivalent-capacity commercial systems have "},
            {'text': "equal median LCOE" + (f" of ${number(medians[0]*1000)}/MWh" if include_medians else ""), 'bold': True},
            {'text': " under the modelled assumptions."},
        ]
    lower, higher = ("Solectria", "SolarEdge") if difference > 0 else ("SolarEdge", "Solectria")
    segments = [
        {'text': f"Under the modelled assumptions, the median LCOE of the commercial {lower} system is "},
        {'text': f"${number(abs(difference))}/MWh lower", 'bold': True},
        {'text': f" than that of the equivalent-capacity {higher} system."},
    ]
    if include_medians:
        segments.append({'text': f" Median LCOE is ${number(medians[0]*1000)}/MWh for Solectria and ${number(medians[1]*1000)}/MWh for SolarEdge."})
    return segments


def median_rounding_note(system_results):
    """Explain a displayed subtraction only when rounding changes its result."""
    values = [(system_results.get(key) or {}).get('percentiles', {}).get('p50') for key, _, _ in SYSTEMS]
    if any(value is None or not math.isfinite(float(value)) for value in values):
        return None
    displayed = [Decimal(number(value * 1000).replace(',', '')) for value in values]
    displayed_gap = abs(displayed[1] - displayed[0])
    actual_gap = abs((values[1] - values[0]) * 1000)
    if displayed_gap == Decimal(number(actual_gap).replace(',', '')):
        return None
    return (f"The median difference is calculated before rounding. Subtracting the displayed medians gives "
            f"${number(displayed_gap)}/MWh; the difference between the unrounded saved medians rounds to "
            f"${number(actual_gap)}/MWh.")


def reviewed_v24_comparison(request, energy_evidence):
    """Context for the specific revised scenario reviewed against report v2.4.

    Guard the note with the saved scenario facts so it cannot be carried into
    exports with different selections or a different measurement window.
    """
    adjustment = request.get('cost_year_adjustment') or {}
    frozen = energy_evidence.get('frozen') or {}
    substitution = (frozen.get('calibration_application') or {}).get('seasonal_substitution') or {}
    dates = [str(row.get('last_timestamp') or '')[:10] for row in frozen.get('seasonal_rows', [])]
    if not (request.get('n') == 65000 and adjustment.get('source_year') == 2024
            and adjustment.get('target_year') == 2020 and substitution.get('source_season') == 'spring'
            and substitution.get('target_season') == 'fall' and substitution.get('explicitly_accepted') is True
            and dates and max(dates) == '2026-09-15'):
        return None
    return ("Changes from v2.4: spring factors are applied to fall, measurement coverage extends through "
            "September 15, 65,000 realizations replace 10,000, and the cost basis is converted from 2024 USD "
            "to 2020 USD. Differences between these reports reflect several changes and cannot be attributed "
            "entirely to calibration.")


def energy_comparison(label, solectria, solaredge, *, include_values=True):
    if any(value is None or not math.isfinite(float(value)) for value in (solectria, solaredge)):
        return f"{label}: a two-system comparison is unavailable in the saved evidence."
    difference = solectria - solaredge
    statement = f"{label}: "
    if include_values:
        statement += f"Solectria {number(solectria/1000,1)} MWh and SolarEdge {number(solaredge/1000,1)} MWh. "
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


def _number_report_blocks(blocks):
    """Resolve one shared heading/figure sequence without changing saved evidence."""
    heading_counts = [0, 0, 0]
    figures = {}
    for block in blocks:
        if block['kind'] == 'heading':
            level = block.get('level', 1)
            heading_counts[level - 1] += 1
            heading_counts[level:] = [0] * (3 - level)
            block['number'] = '.'.join(str(value) for value in heading_counts[:level])
        elif block['kind'] == 'chart':
            identifier = block['figure_id']
            if identifier in figures:
                raise ValueError('Duplicate report figure identifier: ' + identifier)
            block['figure_number'] = len(figures) + 1
            figures[identifier] = block['figure_number']
    for block in blocks:
        if block['kind'] == 'paragraph' and block.get('segments'):
            for segment in block['segments']:
                if 'figure_ref' in segment:
                    segment['text'] = str(figures[segment['figure_ref']])
            block['text'] = ''.join(segment['text'] for segment in block['segments'])


def build_report(job, calculation, routine, checks, *, generated_at=None, lifecycle_chart=None,
                 include_technical_appendix=True, dashboard_identity=None, energy_evidence=None,
                 analysis_name=None):
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
    def paragraph(text, style="body", *, segments=None):
        block = {"kind":"paragraph", "text":text, "style":style}
        if segments is not None:
            block['segments'] = segments
        blocks.append(block)
    def heading(text, anchor, *, page=False, level=1):
        blocks.append({"kind":"heading", "text":text, "anchor":anchor, "page":page, "level":level})
    def table(headers, rows, widths=None, numeric=(), *, keep=False, compact=False, emphasis_rows=(), mono=()):
        if not rows:
            paragraph("No supporting values were recorded.")
            return
        blocks.append({"kind":"table", "headers":headers, "rows":rows, "widths":widths, "numeric":list(numeric), "keep":keep or len(rows)<=3, "compact":compact, "emphasis_rows":list(emphasis_rows), "mono_columns":list(mono)})
    def figure(block, figure_id, description):
        blocks.append({'kind':'paragraph', 'style':'body', 'text':'', 'segments':[
            {'text':'Figure '}, {'figure_ref':figure_id, 'text':''}, {'text':' ' + description}]})
        blocks.append({'kind':'chart', **block, 'figure_id':figure_id})
    def chart(kind, data, height, caption, *, figure_id, description):
        if not data.get("series") and not data.get("panels"):
            paragraph("Chart unavailable because its saved observations are missing.")
            return
        figure({"image":chart_image(kind,data,height), "height":height*72, "caption":caption}, figure_id, description)
    def q(value, key="p50", scale=1, digits=2):
        raw = (value.get("percentiles") or {}).get(key)
        return number(raw*scale if raw is not None else None, digits)

    def lcoe_percentile_table():
        rows = []
        for key,label,_ in SYSTEMS:
            result = system_results.get(key) or {}
            # The header already declares USD/MWh; repeating it in every cell only
            # breaks the numeric alignment readers scan down.
            rows.append([label,*[q(result,p,1000) if (result.get('percentiles') or {}).get(p) is not None else 'Not available' for p in ("p10","p50","p90")]])
        table(["LCOE (USD/MWh)","P10","P50 median","P90"],rows,[.37,.21,.21,.21],numeric=(1,2,3),keep=True)
        paragraph("Lower LCOE means a lower discounted cost per unit of generated AC energy. Cost P10 and P90 bound the middle 80% of the sampled LCOEs. The headline comparison subtracts system medians; it is not the median of paired differences.", "small")

    target_w = paired.get("target_capacity_w")
    target_text = capacity(target_w, "ac" if scenario.get("target_rating_basis")=="ac_operating_limit" else "dc")
    system_results = paired.get("systems") or {}
    identity = dashboard_identity or {"version":"Not recorded", "version_source":"not recorded", "build":"Not recorded"}
    run_id = str(job.get("id") or job.get("job_id"))
    resolved_analysis_name = normalize_analysis_name(analysis_name, run_id=run_id)
    report = {"title":REPORT_TITLE, "subtitle":REPORT_SUBTITLE, "version":REPORT_VERSION,
              "generated_at":generated.isoformat(), "analysis_at":job.get("completed_at"),
              "run_id":run_id, "analysis_name":resolved_analysis_name, "blocks":blocks,
              "include_technical_appendix":bool(include_technical_appendix), "dashboard_identity":dict(identity)}
    report['verification_check_count'] = len(checks)
    report['verification_check_ids'] = [str(row[0]) for row in checks]
    report['energy_evidence'] = energy_evidence

    # The subheader travels with the title so the cover rule closes the whole
    # heading. Run details sit below it in the muted tier; giving them the
    # subheader's own size left three equal lines and no visible hierarchy.
    blocks.append({"kind":"title", "text":report["title"], "subtitle":report["subtitle"]})
    paragraph(report['analysis_name'], 'meta')
    paragraph(f"{target_text} commercial comparison", "meta")
    paragraph(f"Analysis completed {display_date(job.get('completed_at'),time=True)}\n"
              f"Generating dashboard version {identity['version']} ({identity['version_source']})", "meta")
    blocks.append({"kind":"pagebreak"})
    paragraph("Contents", "toc_title")
    blocks.append({"kind":"toc"})
    heading("Executive Summary", "executive-summary", page=True)
    heading("Objectives", "summary-objectives", level=2)
    paragraph(f"The objectives are to compare module-level and centralized optimization, using the SolarEdge and Solectria systems at SolarTAC as a case study. The comparison evaluates energy production and lifecycle levelized cost of electricity (LCOE) for an equal-capacity {target_text} commercial scenario.")
    heading("Approach", "summary-approach", level=2)
    paragraph("We review Bazefield power and weather measurements and fit seasonal factors for each PV system. We apply those factors to historical MIDC weather to predict annual energy. The technoeconomic analysis uses Latin Hypercube Sampling for uncertain continuous inputs and a balanced selection of paired weather years to calculate lifecycle LCOE.")
    heading("Results", "summary-results", level=2)
    finding_segments = median_lcoe_comparison_segments(system_results)
    paragraph(''.join(segment['text'] for segment in finding_segments), "finding", segments=finding_segments)
    lcoe_percentile_table()
    rounding_note = median_rounding_note(system_results)
    if rounding_note:
        paragraph(rounding_note, 'small')
    revision_note = reviewed_v24_comparison(request, energy_evidence)
    if revision_note:
        paragraph(revision_note, 'small')
    if context.get("limitations"):
        paragraph("Scenario qualifications: " + words(context["limitations"]), "small")

    heading("Introduction and Objectives", "introduction", page=True)
    paragraph("The SBE Innovation Center at SolarTAC hosts SolarEdge and Solectria PV systems. SolarEdge optimizes power at the module level; Solectria uses a common inverter operating point for connected strings. These architectures respond differently to uneven module conditions.")
    paragraph("This study calibrates each system against reviewed site measurements, predicts production across full historical weather years, and compares lifecycle cost per unit of AC energy at equal commercial capacity. It uses the recorded geometry and model assumptions without assuming either technology produces more energy. Calibration coverage and cost assumptions limit how broadly the results apply.")
    heading("Analysis", "analysis-approach")
    paragraph("The study has four steps. We collect power and weather measurements, review data quality and calibrate the PV model, simulate full historical weather years, and calculate lifecycle LCOE from the recorded energy and cost assumptions. Saved records link each step to its source.")

    heading("Data Collection", "data-collection", level=2)
    paragraph("Bazefield supplies the power and weather measurements used for calibration. Data-quality review determines which intervals to retain. Excluded intervals contribute no measured energy.")
    paragraph(f"The measurements cover {measured_window(c_request, calibration['result'])}. "
              f"The recorded interval is {words(c_request.get('interval_value'))} {words(c_request.get('interval_unit')).removesuffix('s') if c_request.get('interval_value') == 1 else words(c_request.get('interval_unit'))}. "
              f"The optional AC operating limit is {capacity(c_request['curtailment_limit_kw'] * 1000, 'ac')+' per system' if c_request.get('curtailment_enabled') and c_request.get('curtailment_limit_kw') is not None else 'disabled' if c_request.get('curtailment_enabled') is False else 'not recorded'}.")
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

    heading("Modeling and Calibration", "calibration", level=2)
    if appendix.physics_description_supported(job):
        paragraph("The Python PV model uses pvlib to calculate solar position, tracker orientation, irradiance, module temperature and module electrical output. SolarEdge aggregates individual module maximum-power predictions. For Solectria, PVMismatch represents the cell and module current-voltage response, bypass diodes and electrical mismatch; the model combines strings at a common inverter operating point. Recorded conversion efficiencies and operating limits produce AC power.")
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
    chart("bars",{"labels":[label for _,label,_ in SYSTEMS],"series":energy_series,"ylabel":"AC energy (MWh)"},2.1,"Energy covers the retained measured-data intervals at SolarTAC. Agreement after fitting is calibration, not an independent prediction test.",
          figure_id='calibration-energy', description='compares retained measured energy with model predictions before and after seasonal calibration.')
    seasons=(calibration["result"].get("calibration_factors") or stats.get("calibration_factors") or {}).get("seasons") or []
    season_rows=[]
    for season in seasons:
        season_rows.append([words(season.get("season")).title(),f"{display_date(season.get('first_timestamp'))}\nto {display_date(season.get('last_timestamp'))}",number(season.get("row_count"),0),
                            *[number((season.get("systems",{}).get(key) or {}).get("factor"),4) for key,_,_ in SYSTEMS]])
    heading("Fitted calibration factors", "fitted-factors",level=3)
    table(["Season","Observed coverage","Rows","Solectria\nfactor","SolarEdge\nfactor"],season_rows,[.13,.34,.13,.2,.2],numeric=(2,3,4),keep=len(season_rows)<=4)
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

    for block in appendix.applied_calibration_blocks(job):
        blocks.append({**block, 'level':3} if block['kind']=='heading' else block)
    heading("Annual Simulation", "annual", level=2)
    annual_rows=annual["result"].get("annual_energy_by_year") or []
    eligible=snapshot.get("eligible_paired_energy_rows") or []
    paragraph("The model uses historical MIDC weather from SolarTAC, saved seasonal factors and operating limits to predict annual AC energy. Annual predictions cover full weather years; calibration covers only the measured intervals.")
    paragraph(f"The frozen source contains {len(eligible)} eligible paired weather years. The table and chart show SolarTAC-scale AC energy; commercial costs and LCOE use the {target_text} scenario.")
    table(["Weather year","Coverage","Solectria MWh","SolarEdge MWh","Eligible"],[[words(row.get("year")),number(row.get("annual_coverage_pct"),1)+('%' if row.get('annual_coverage_pct') is not None else ''),
          *[number(row[prefix+"_predicted_kwh"]/1000 if row.get(prefix+"_predicted_kwh") is not None else None,1) for _,_,prefix in SYSTEMS],words(row.get("cdf_eligible"))] for row in annual_rows],[.17,.18,.23,.23,.19],numeric=(0,1,2,3),compact=True)
    series=[]
    for _,label,prefix in SYSTEMS:
        available=[row for row in annual_rows if row.get("year") is not None and row.get(prefix+"_predicted_kwh") is not None]
        if available:
            series.append({"label":label,"x":[row['year'] for row in available],"values":[row[prefix+'_predicted_kwh']/1000 for row in available]})
    chart("annual",{"series":series,"ylabel":"AC energy (MWh)"},2.05,"Lines connect the recorded weather years for comparison; intervening unselected years have not been simulated.",
          figure_id='annual-energy', description='compares the two systems within each modeled weather year, using the saved seasonal factors and operating limits.')
    paragraph(energy_comparison("Retained measured intervals",stats.get('sol_measured_kwh'),stats.get('se_measured_kwh')),"small")
    if len(eligible)>=5:
        annual_medians = [float(np.quantile([row[prefix+'_predicted_kwh'] for row in eligible],.5,method='linear')) for _,_,prefix in SYSTEMS]
        paragraph(energy_comparison("Predicted annual medians",*annual_medians),"small")
    heading("Understanding the energy difference", "energy-difference", level=3)
    frozen_energy = energy_evidence['frozen']
    energy_diagnostic = energy_evidence['artifact_diagnostic']
    if energy_diagnostic.get('status') == 'reconciled_current_artifacts':
        reconciliation = energy_diagnostic['reconciliation']
        capacities = frozen_energy.get('capacities') or {}
        paragraph(f"The same {number(reconciliation['paired_measurement_rows'],0)} retained timestamps contain finite measurements for both systems and match the SHA-verified reviewed source. The review uses one combined exclusion mask. "
                  f"Installed capacities: Solectria {capacity(capacities.get('solectria'),'dc')}; SolarEdge {capacity(capacities.get('solaredge'),'dc')}. "
                  "Each workbook matches its corresponding saved calibration profile and operating caps.","small")
        profile_validation = energy_diagnostic.get('profile_validation') or {}
        substitution = profile_validation.get('seasonal_substitution') or {}
        if profile_validation.get('fitted_equals_applied') is False:
            paragraph("The calibration workbook retains the original fitted factors. The annual workbook uses the recorded "
                      f"{words(substitution.get('source_season'))} factors for {words(substitution.get('target_season'))}. "
                      "These profiles intentionally differ; each workbook is checked against its own profile.", 'small')
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
        table(['Season','Measured gap (MWh)','Mean annual gap before calibration (MWh)','Mean annual gap with applied calibration (MWh)'],
              comparison_rows,[.16,.24,.30,.30],numeric=(1,2,3),keep=True)
        paragraph("Annual columns average the same eligible full weather years; the measured column covers only retained observations. Applying calibration factors interacts with operating caps, so these columns do not separate independent physical causes. Seasonal means sum to the mean annual gap, not the difference of system medians.","small")
        sensitivity = energy_diagnostic.get('fall_sensitivity') or {}
        if sensitivity.get('status') == 'available':
            heading("Fall calibration sensitivity (diagnostic only)", "fall-sensitivity", level=3)
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
            affected = sensitivity.get('affected_system_capped_fall_rows') or {}
            if affected:
                cap_detail = ', '.join(f"{number(count,0)} {words(key)} fall intervals" for key,count in affected.items() if count)
                paragraph("An exact fall-to-summer sensitivity is unavailable. Lowering the applied fall factor requires "
                          f"pre-cap power for {cap_detail}, which is absent from these exports. The verified seasonal "
                          "comparison above uses the saved spring-for-fall scenario and does not infer those missing powers.", 'small')
            else:
                paragraph("Fall sensitivity unavailable: " + str(sensitivity.get('reason') or 'insufficient saved evidence') + '.',"small")
        cap_rows = {key:sum(row['mean_at_cap_rows'][key] for row in seasonal) for key,_,_ in SYSTEMS}
        paragraph("Annual averages at the operating cap: " + ', '.join(f"{label} {number(cap_rows[key],1)} intervals" for key,label,_ in SYSTEMS)
                  + ". Saved capped powers cannot establish exact losses from removing the cap.","small")
    else:
        measured_seasons = [row for row in frozen_energy['seasonal_rows'] if row.get('measured')]
        if measured_seasons:
            table(['Season','Retained measured Solectria − SolarEdge (MWh)'],
                  [[row['season'].title(),number(row['measured']['difference_kwh']/1000,2)] for row in measured_seasons],[.3,.7],numeric=(1,))
        paragraph("Interval-level seasonal and controlled comparisons are unavailable: " + energy_diagnostic.get('reason','supporting artifacts unavailable') +
                  " Frozen totals remain valid, but they do not quantify individual factor or cap contributions.","small")
    heading("Annual energy distribution", "annual-distribution", level=3, page='auto')
    interpolation_series = []
    for _, label, prefix in SYSTEMS:
        values = [row[prefix+'_predicted_kwh']/1000 for row in eligible if row.get(prefix+'_predicted_kwh') is not None]
        points = annual_interpolation_points(values)
        if points is not None:
            interpolation_series.append({'label':label, 'x':points[0], 'probability':points[1]})
        else:
            paragraph(label + ': interpolation requires at least two complete years with distinct energies.', 'small')
    chart('annual_cdf', {'series':interpolation_series}, 3.0,
          'Straight-line interpolation connects the modeled annual energies for display, matching the dashboard. Points use midpoint ranks with average ranks for ties. No probability tails are extrapolated beyond the observed range.',
          figure_id='annual-energy-distribution', description='shows how annual energy varies across the selected historical weather years.')
    paragraph('The TEA selects the discrete paired annual results directly; it does not sample interpolated values from this curve. The percentile table uses the existing type-7 quantile method; it is not read from the plotted curve.', 'small')
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

    heading("Technoeconomic Analysis", "technoeconomic-analysis", level=2, page='auto')
    paragraph(f"The {finance.get('project_life_years','recorded')}-year commercial comparison scales each system's annual SolarTAC AC energy by its own applied source capacity to the common {target_text} target. The declared DC capacity provides the cost basis; it does not independently multiply energy.")
    paragraph("Latin Hypercube Sampling draws the uncertain continuous cost, discount-rate and degradation inputs from their recorded distributions. Each realization uses the same selected weather year, discount rate and degradation for both systems; system-specific O&M inputs are sampled independently. Pairing describes the shared inputs, while Latin Hypercube Sampling describes the sampling method.")
    if eligible and request.get('n'):
        quotient, remainder = divmod(request['n'], len(eligible))
        count_text = f"{number(quotient,0)} or {number(quotient+1,0)}" if remainder else number(quotient,0)
        paragraph(f"Weather years are assigned directly with balanced counts: {number(request['n'],0)} realizations divided by {len(eligible)} selected years gives {count_text} uses per year. Both systems retain the energy values from the same year. The selected annual yield supplies first-year energy, and degradation is applied over the project life without selecting a new weather year for each project year.")
    paragraph("LCOE is discounted lifecycle cost divided by discounted AC energy. Costs include initial investment, annual O&M and only explicitly recorded scheduled costs.")
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
    heading("Assumptions and cost breakdown", "assumptions",level=3)
    ratio=shared.get("dc_capacity_w",0)/target_w if shared and target_w else None
    inputs=[["Commercial capacity",target_text + (f"; {capacity(shared['dc_capacity_w'], 'dc')} cost basis" if shared else "")],
            ["Project life / realizations",f"{finance.get('project_life_years','Not recorded')} years / {number(request.get('n'),0)}"],
            ["Real discount rate",distribution((finance.get('real_discount_rate') or {}).get('distribution'),100)+"% per year"],
            ["Annual degradation",distribution(((request.get('shared_degradation') or {}).get('annual_rate') or {}).get('distribution'),100)+"% per year"],
            ["Dollar basis",f"{'Declared' if request.get('cost_year_adjustment') or context.get('preset_id') == 'user-cost-basis-2026-v1' else 'Proposed'} real {finance.get('constant_dollar_cost_year','unrecorded')} USD"]]
    if assumptions_status in {"approved_defaults", "modified"}:
        inputs.insert(0, ["Recorded assumptions selection", "Comparison defaults (saved preset)" if assumptions_status == "approved_defaults" else "Modified assumptions"])
    if shared:
        inputs += [["Common initial CAPEX",distribution(shared.get('common_capex_wdc'),digits=2)+" USD/Wdc"],
                   ["SolarEdge optimizer installation",distribution(shared.get('optimizer_installation_wdc'),1000)+" USD/kWdc"],
                   ["SolarEdge optimizer hardware",f"{number(shared.get('optimizer_count'),0)} units \u00d7 ${number(shared.get('optimizer_unit_price_usd'))}"]]
    for key,label,_ in SYSTEMS:
        system=next((s for s in scenario.get('systems',[]) if s.get('technology')==key),{})
        for line in system.get('cost_lines',[]):
            if shared and line.get('cost_category')=='full_initial_capex':
                continue
            is_om=line.get('unit')=='constant_usd_per_target_w_year' and ratio
            units='USD/kWdc-year' if is_om else {'constant_usd_per_target_w':'USD/kW of target capacity','constant_usd_per_target_w_year':'USD/kW of target capacity per year','constant_usd':'USD'}.get(line.get('unit'),words(line.get('unit')))
            display_scale = 1000 / ratio if is_om else (1000 if line.get('unit') in {'constant_usd_per_target_w','constant_usd_per_target_w_year'} else 1)
            timing = "; at year-end in years " + ", ".join(str(year) for year in line.get('occurrence_years', [])) if line.get('timing') == 'scheduled_year_end' else ""
            inputs.append([label+' '+('annual O&M' if line.get('cost_category')=='full_annual_om' else words(line.get('label'))),distribution(line.get('distribution'),display_scale)+" "+units+timing])
    table(["Input","Saved assumption"],inputs,[.37,.63])
    adjustment = request.get('cost_year_adjustment')
    if adjustment:
        from sbepv import technoeconomic_cost_year
        catalog = technoeconomic_cost_year.get_index_catalog(adjustment['index_snapshot_id'])
        source_year, target_year = adjustment['source_year'], adjustment['target_year']
        paragraph(f"Cost assumptions were converted from {source_year} USD to {target_year} USD using the U.S. GDP price deflator. Each monetary value and its uncertainty bounds are multiplied by the same index ratio; energy, quantities and real rates are unchanged.", 'small')
        table(["Dollar-year conversion", "Saved value"], [
            ["Original dollar year / index", f"{catalog['years'][str(source_year)]['label']} / {number(adjustment['source_index'],3)}"],
            ["Selected dollar year / index", f"{catalog['years'][str(target_year)]['label']} / {number(adjustment['target_index'],3)}"],
            ["Multiplier (selected / original)", number(adjustment['factor'],8)],
            ["Index snapshot", adjustment['index_snapshot_id']],
        ], [.52,.48], compact=True, keep=True)
        for year in sorted({source_year, target_year}):
            observation = catalog['years'][str(year)]
            if observation['provisional']:
                paragraph(f"The {year} index is a provisional proxy using {observation['period'].replace('-', ' ')}, the latest quarter in this saved index snapshot. It is not a full-year {year} observation.", 'small')
        paragraph("The conversion changes the dollar basis; it does not forecast equipment prices or resolve the original cost-source qualifications. Original amounts and the adjustment record are retained with the analysis.", 'small')
        blocks.append({'kind':'reference', 'text':'U.S. GDP price deflator: BEA data distributed by FRED',
                       'url':'https://fred.stlouisfed.org/series/GDPDEF'})
    elif assumptions_status == "modified":
        paragraph("These inputs differ from the original comparison preset. No price-index conversion is recorded in this saved analysis; the dollar year is the declared basis of the entered amounts.","small")
    elif assumptions_status == "approved_defaults":
        paragraph("The saved record identifies the comparison preset as approved defaults. The cost-year and maintenance qualifications remain unresolved. Exporting the report changes no assumptions.","small")
    if shared:
        paragraph("The same common CAPEX draw is used for both systems. SolarEdge adds fixed optimizer hardware and independently sampled installation. Its total is derived from these inputs; the support range is not independently sampled. O&M draws are independent by system.","small")
        allocations=context.get('component_allocations') or []
        if allocations:
            heading("Common CAPEX component allocations", "components",level=3)
            table(["Component","Midpoint USD/kWdc"],[[row['label'],number(row['midpoint_wdc']*1000)] for row in allocations]+[["Sum",number(sum(row['midpoint_wdc'] for row in allocations)*1000)]],[.73,.27],numeric=(1,),emphasis_rows=(len(allocations),))
        base=midpoint(shared['common_capex_wdc']); install=midpoint(shared['optimizer_installation_wdc'])
        if base is not None and install is not None:
            sol=base*shared['dc_capacity_w']; se=sol+shared['optimizer_count']*shared['optimizer_unit_price_usd']+install*shared['dc_capacity_w']
            paragraph(f"Deterministic midpoint initial investment: Solectria ${sol/1e6:,.2f} million; SolarEdge ${se/1e6:,.2f} million." + (" Component allocations explain the base total and are not additional sampled costs." if allocations else ""),"small")
        rating_label = 'AC' if scenario.get('target_rating_basis')=='ac_operating_limit' else 'DC'
        paragraph(f"DC cost intensities convert to the {rating_label} target-capacity basis using {number(ratio,2)}. This ratio does not multiply energy. Cost coverage follows the recorded cost lines and scenario qualifications in the Executive Summary.","small")

    heading("Lifecycle LCOE comparison", "lifecycle-comparison", level=3)
    if lifecycle_chart:
        figure({**lifecycle_chart,
                "caption":"Lifecycle LCOE empirical CDF from saved realizations. Lower LCOE is better; each curve shows the share of results at or below that cost. Percentiles match the Executive Summary."},
               'lifecycle-lcoe', f"compares lifecycle LCOE over {finance.get('project_life_years', 'the recorded project life')} years using the verified realizations from this run.")
    else:
        paragraph("The completed-run lifecycle LCOE chart is unavailable.", "small")
    lcoe_percentile_table()
    summary_rows = []
    for label, suffix, scale in (("Discounted lifecycle cost (USD million)", "LifecycleCost_USD", 1e-6),
                                 ("Discounted lifecycle AC energy (GWh)", "LifecycleEnergy_kWh_AC", 1e-6)):
        summary_rows.append([label, *[q(metadata.get('summaries', {}).get('Commercial'+system+suffix) or {}, scale=scale, digits=3)
                                     for system in ('Solectria', 'SolarEdge')]])
    table(["Saved lifecycle medians", "Solectria", "SolarEdge"], summary_rows, [.52, .24, .24], numeric=(1,2), keep=True)
    paragraph("Future costs and energy are discounted to a common reference year. LCOE is calculated separately for every realization as discounted lifecycle cost divided by discounted energy. Dividing the two medians above need not reproduce median LCOE.", "small")

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

    heading("Input sensitivity", "sensitivity", level=3)
    paragraph("Larger bars show stronger influence in the saved rank regression. Positive coefficients increase LCOE rank; negative coefficients decrease it. Coefficients are dimensionless associations, not dollar changes or causal effects.","lead")
    labels = diagnostics.predictor_labels(scenario)
    for payload in diagnostics.tornado_payloads(metadata,input_labels=labels):
        if payload['status']=='available':
            figure_id = 'lcoe-sensitivity-' + payload['system'] + '-rank-' + str(payload.get('rank_start',1))
            figure({"image":diagnostics.render_tornado(payload), "height":payload['height']*72,
                    "caption":f"{payload['label']} LCOE rank sensitivity. Bars show final standardized regression coefficients; sample count and final R-squared describe the saved fitted model."},
                   figure_id, f"shows the relative influence of the recorded inputs on {payload['label']} LCOE in the saved multivariable rank regression.")
        else:
            paragraph(f"{payload['label']} sensitivity unavailable: {payload['reason']}.","small")
        if payload.get('notes'):
            paragraph(' '.join(payload['notes']),"small")

    heading("Summary", "summary", page=True)
    heading("Key results", "summary-key-results", level=2)
    closing_segments = median_lcoe_comparison_segments(system_results, include_medians=False)
    paragraph(''.join(segment['text'] for segment in closing_segments), 'finding', segments=closing_segments)
    closing_rows = [[f"Lifecycle LCOE (USD/MWh)\n{target_text} commercial systems",
                     *[q(system_results.get(key) or {}, scale=1000) for key, _, _ in SYSTEMS]]]
    if len(eligible)>=5:
        closing_rows.append(["Predicted annual AC energy (MWh/year)\nSolarTAC site",
                             *[number(value/1000,1) for value in annual_medians]])
    table(["Median result and basis", "Solectria", "SolarEdge"], closing_rows, [.56,.22,.22], numeric=(1,2), keep=True)
    if len(eligible)>=5:
        paragraph(energy_comparison("Predicted annual medians at SolarTAC",*annual_medians,include_values=False))
    heading("Interpretation and calibration", "summary-interpretation", level=2)
    paragraph("Higher energy alone does not establish lower LCOE; the recorded capital, operating and financing assumptions also determine the result.")
    paragraph("The energy comparison uses the saved seasonal calibration factors. Limited measured coverage can affect transfer to complete seasons, and this TEA does not sample calibration-factor uncertainty.")
    if context.get('limitations'):
        heading("Cost qualifications", "summary-cost-qualifications", level=2)
        paragraph("The comparison retains these cost qualifications: " + words(context['limitations']), 'small')

    if include_technical_appendix:
        heading("Technical Appendix", "technical-appendix", page=True)
        blocks.extend(appendix.build_technical_appendix(job))
        heading("LCOE percentile stability", "appendix-convergence", level=2, page='auto')
        paragraph("P10/P50/P90 are recalculated over increasing prefixes of the saved realizations. Final points match the headline table. These are subsets of one experiment, not new simulations.","lead")
        for payload in diagnostics.convergence_payloads(metadata,calculation.by_name,routine,row_count=calculation.row_count):
            if payload['status']=='available':
                figure({"image":diagnostics.render_convergence(payload), "height":payload['height']*72,
                        "caption":f"{payload['label']} cumulative LCOE percentiles in USD/MWh. Original realization ordering is preserved."},
                       'lcoe-convergence-' + payload['system'], f"shows how {payload['label']} P10, P50 and P90 LCOE change as more of the saved realizations are included.")
            else:
                paragraph(f"{payload['label']} percentile stability unavailable: {payload['reason']}.","small")
            if payload.get('status')=='available' and len(payload.get('checkpoints',[]))<2:
                paragraph("Only one checkpoint was saved; a stability trend cannot be assessed.","small")
        paragraph("The original convergence checks remain unchanged. These plots show sampling stability; they do not define confidence intervals.","small")

    heading("References and Evidence", "references",page=True)
    direct_checks = sum(str(row[0]).startswith('independent_direct_sum_') for row in checks)
    saved_checks = len(checks) - direct_checks
    paragraph(f"Numerical verification: {saved_checks} saved-result consistency checks and {direct_checks} independent "
              "annual-sum checks passed. The saved checks are listed in checks.csv in the CSV export and in the Excel "
              "Checks sheet; the additional export checks compare direct annual sums for the annuity and lifecycle-energy "
              "factors. These checks establish numerical consistency, not calibration validity or prediction accuracy. "
              "Report generation does not rerun the model or alter the saved analysis.","small")
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
    heading("Technical record", "technical-record",level=2,page='auto' if include_technical_appendix else False)
    model_contract=snapshot.get('model_contract') or {}
    table(["Record","Saved identifier"],[["TEA analysis",report['run_id']],["Annual simulation",request['source_annual_job_id']],["Calibration",calibration.get('id') or calibration.get('job_id') or 'Not recorded'],["Random seed",str(request.get('seed','Not recorded'))],
          ["Generating dashboard version",f"{identity['version']} ({identity['version_source']})"],
          ["Generating dashboard build",identity.get('build') or 'Not recorded'],
          ["Analysis dashboard version",(job.get('submission_provenance') or {}).get('dashboard_version') or 'Not recorded'],
          ["Analysis dashboard build",(job.get('submission_provenance') or {}).get('dashboard_build') or 'Not recorded'],
          ["Saved model version",model_contract.get('model_version') or 'Not recorded'],
          ["Saved physics version",model_contract.get('calibration_physics_version') or 'Not recorded'],
          ["Analysis completion time",job.get('completed_at') or 'Not recorded'],
          ["Export generation time",report['generated_at']],
          ["Report format",REPORT_VERSION]],[.34,.66],compact=True)
    paragraph("Generating version/build describes this export. A package label does not identify a deployed build. Historical versions are shown only when saved with the analysis.","small")
    if energy_diagnostic.get('status') == 'reconciled_current_artifacts':
        table(['Diagnostic source','Current workbook SHA-256'],[
            [label,energy_diagnostic['identity'][key]['sha256']] for key,label in (
                ('calibration','Calibration workbook'),('annual','Annual workbook'))],mono=(1,))
    _number_report_blocks(blocks)
    return report
