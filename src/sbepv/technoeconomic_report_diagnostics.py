"""Report-only diagnostics derived from verified, immutable TEA evidence.

No fitting, sampling, model execution, API imports, or persistence belongs here.
The caller verifies the seal and routine result before passing their contents.
Missing historical evidence is reported; inconsistent evidence fails closed.
"""
from __future__ import annotations

import base64
from collections.abc import Mapping
from io import BytesIO
import math
import textwrap

import numpy as np
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from matplotlib.ticker import MaxNLocator, PercentFormatter, StrMethodFormatter


SYSTEMS = (("solectria", "Solectria", "#AD7610"), ("solaredge", "SolarEdge", "#2E66A3"))
PERCENTILES = (("p10", .1), ("p50", .5), ("p90", .9))
MAX_TORNADO_HEIGHT = 6.0  # Inches; leaves room for captions within either page layout.
CHART_WIDTH_INCHES = 522 / 72  # Match the embedded width so 8 pt remains 8 pt.
CHART_FONT_SIZE = 8


class ReportDiagnosticsError(ValueError):
    """Saved report evidence is inconsistent and must not be charted."""


def predictor_labels(paired_commercial):
    """Name cost predictors from their recorded system ownership, not bare labels.

    Accept either the request's system list or the sealed provenance's system
    mapping. The same label is used for chart bars, exclusions and warnings.
    """
    systems = paired_commercial.get("systems") or {}
    if isinstance(systems, Mapping):
        systems = [{**record, "technology": technology} for technology, record in systems.items()]
    labels = {}
    owners = {}
    known_systems = {system: label for system, label, _ in SYSTEMS}
    for system in systems:
        technology = system.get("technology")
        if technology not in known_systems:
            continue
        owner = known_systems[technology]
        for line in system.get("cost_lines") or []:
            identifier = line.get("input_id")
            if not identifier:
                continue
            if identifier in owners and owners[identifier] != technology:
                raise ReportDiagnosticsError(f"Predictor {identifier!r} has conflicting saved system ownership.")
            owners[identifier] = technology
            if line.get("cost_category") == "full_annual_om":
                label = owner + " annual O&M"
            else:
                label = str(line.get("label") or identifier).strip()
                if label.lower().startswith(owner.lower() + " "):
                    label = owner + label[len(owner):]
                else:
                    label = owner + " " + label
            labels[identifier] = label
    return labels


def _display_text(value):
    return str(value).replace(" \u2014 ", ": ").replace("\u2014", ": ")


def _label(identifier, labels):
    known = {
        "capex.shared-base-wdc": "Shared base CAPEX",
        "capex.optimizer-installation-wdc": "Optimizer installation",
        "finance.discount-rate": "Real discount rate",
        "energy.shared-degradation": "Annual degradation",
        "solectria.annual-om": "Solectria annual O&M",
        "solaredge.annual-om": "SolarEdge annual O&M",
    }
    if identifier in labels:
        return _display_text(labels[identifier])
    if identifier in known:
        return known[identifier]
    if "specific" in identifier.lower() or ("source" in identifier.lower() and "energy" in identifier.lower()):
        system = "SolarEdge" if "solaredge" in identifier.lower() or "solar_edge" in identifier.lower() else "Solectria"
        return system + " specific energy"
    return _display_text(identifier).replace("_", " ").replace(".", " ")


def _words(value):
    return _display_text(value).replace("_", " ")


def _finite(value):
    if isinstance(value, (bool, str)) or value is None:
        return False
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _count(value):
    return isinstance(value, (int, np.integer)) and not isinstance(value, bool) and value > 0


def _unavailable(system, label, reason, *, notes=()):
    return {"system": system, "label": label, "status": "unavailable", "reason": reason,
            "rows": [], "series": [], "notes": list(notes), "height": 2.85}


def tornado_payloads(metadata, *, input_labels=None):
    """Read signed final-model betas, sorted by magnitude then stable input ID.

Excluded inputs are never assigned zero coefficients. Their saved reasons and
correlation warnings remain visible even when a model cannot be plotted.
Large models are split into consecutive panels without dropping coefficients.
"""
    labels = dict(input_labels or {})
    # Historical default IDs identify the systems even if their display labels
    # were generic. Recorded ownership below takes precedence when available.
    labels.update({"solectria.annual-om": "Solectria annual O&M", "solaredge.annual-om": "SolarEdge annual O&M"})
    paired_provenance = (metadata.get("kernel_provenance") or {}).get("commercial_paired") or {}
    labels.update(predictor_labels(paired_provenance))
    models = metadata.get("sensitivity") or {}
    payloads = []
    for system, label, color in SYSTEMS:
        model = models.get(f"commercial_{system}_lifecycle_lcoe")
        if not model:
            payloads.append(_unavailable(system, label, "Saved rank-regression model is unavailable."))
            continue
        notes = []
        exclusions = model.get("exclusions") or {}
        for identifier, detail in sorted(exclusions.items()):
            detail = {"reason": detail} if isinstance(detail, str) else detail
            reason = _words(detail.get("reason") or "reason not recorded")
            extra = f"; duplicate of {_label(detail['duplicate_of'], labels)}" if detail.get("duplicate_of") else ""
            notes.append(f"{_label(identifier, labels)} excluded from the {label} model: {reason}{extra}.")
        for warning in model.get("warnings") or []:
            if isinstance(warning, Mapping) and warning.get("code") == "high_pairwise_rank_correlation":
                correlation = warning.get("correlation")
                value = f"{correlation:+.2f}" if _finite(correlation) else "not recorded"
                notes.append("High rank correlation between " + _label(str(warning.get("left_predictor")), labels)
                             + " and " + _label(str(warning.get("right_predictor")), labels)
                             + f" ({value}); correlated inputs can affect coefficient size and sign.")
            else:
                notes.append("Saved sensitivity warning: " + _words(warning) + ".")
        reason = model.get("reason")
        if model.get("status") != "available":
            payloads.append(_unavailable(system, label, "Rank regression unavailable: " + _words(reason or "status not recorded") + ".", notes=notes))
            continue
        count, r_squared = model.get("sample_count"), model.get("final_r_squared")
        if not _count(count) or not _finite(r_squared) or not 0 <= r_squared <= 1 + 1e-12:
            raise ReportDiagnosticsError(f"{label} rank-regression sample count or R² is invalid.")
        rows, seen = [], set()
        missing = False
        for step in model.get("steps") or []:
            identifier, beta = step.get("predictor_id"), step.get("standardized_beta")
            if not isinstance(identifier, str) or not identifier or identifier in seen:
                raise ReportDiagnosticsError(f"{label} rank-regression predictor IDs are invalid or duplicated.")
            seen.add(identifier)
            if beta is None:
                missing = True
                continue
            if not _finite(beta):
                raise ReportDiagnosticsError(f"{label} rank-regression coefficient is non-finite or invalid.")
            rows.append({"predictor_id": identifier, "label": _label(identifier, labels), "beta": float(beta)})
        if missing or not rows:
            reason = "Saved standardized coefficients are incomplete." if missing else "No predictors entered the saved rank model."
            payloads.append(_unavailable(system, label, reason, notes=notes))
            continue
        rows.sort(key=lambda row: (-abs(row["beta"]), row["predictor_id"]))
        for row in rows:
            lines = textwrap.wrap(row["label"], 29) or [row["predictor_id"]]
            if len(lines) > 3:
                lines = lines[:3]
                lines[-1] = lines[-1].rstrip() + "…"
                notes.append(f"Shortened chart label: {row['label']} (input {_display_text(row['predictor_id'])}).")
            row["display_label"] = "\n".join(lines)
        label_lines = max(len(row["display_label"].splitlines()) for row in rows)
        row_height = max(.39, .16 * label_lines + .08)
        full_height = max(2.6, 1.15 + row_height * len(rows))
        per_panel = len(rows) if full_height <= MAX_TORNADO_HEIGHT else max(1, int((MAX_TORNADO_HEIGHT - 1.5) / row_height))
        panel_count = math.ceil(len(rows) / per_panel)
        limit = max(max(abs(row["beta"]) for row in rows) * 1.32, .01)
        for start in range(0, len(rows), per_panel):
            panel_rows = rows[start:start + per_panel]
            end = start + len(panel_rows)
            panel_notes = notes if end == len(rows) else []
            if panel_count > 1:
                panel_notes = [f"Coefficient ranks {start + 1}–{end} of {len(rows)}. All selected predictors appear across {panel_count} panels with the same axis scale.", *panel_notes]
            payloads.append({"system": system, "label": label, "status": "available", "reason": None,
                             "rows": panel_rows, "sample_count": int(count), "r_squared": float(r_squared),
                             "notes": panel_notes, "color": color,
                             "height": max(2.6, (1.5 if panel_count > 1 else 1.15) + row_height * len(panel_rows)),
                             "panel_count": panel_count, "rank_start": start + 1, "rank_end": end,
                             "entered_predictor_count": len(rows), "axis_limit": limit})
    return payloads


def _tie_out(actual, expected, description):
    # Far tighter than displayed cents/MWh, allowing only floating-point noise.
    if not _finite(expected) or not math.isclose(float(actual), float(expected), rel_tol=1e-12, abs_tol=1e-12):
        raise ReportDiagnosticsError(f"{description} disagrees with saved percentiles.")


def lifecycle_cdf_payload(metadata, by_name, routine, *, row_count=None):
    """Rebuild the two system ECDFs from verified saved rows, without sampling.

    The canonical convention is right-continuous with ties collapsed. All
    observations contribute; display values and percentile markers use USD/MWh.
    """
    unavailable = {"status": "unavailable", "reason": None, "series": [], "notes": [], "height": 3.55}
    count = routine.get("realization_count")
    if not _count(count) or (row_count is not None and row_count != count):
        raise ReportDiagnosticsError("Saved realization count does not match the sealed calculation.")
    indices = by_name.get("realization_index")
    if indices is None:
        return {**unavailable, "reason": "Original realization identities are unavailable in the saved evidence."}
    if not np.array_equal(np.asarray(indices), np.arange(1, count + 1)):
        raise ReportDiagnosticsError("Sealed realizations are not in their original one-based order.")
    paired = routine.get("paired_commercial") or {}
    systems = paired.get("systems") or {}
    recorded_year = paired.get("constant_dollar_cost_year")
    sealed_year = ((metadata.get("kernel_provenance") or {}).get("commercial_paired") or {}).get("constant_dollar_cost_year")
    for year in (recorded_year, sealed_year):
        if year is not None and (not _count(year) or not 1900 <= year <= 3000):
            raise ReportDiagnosticsError("Saved LCOE constant-dollar year is invalid.")
    if recorded_year is not None and sealed_year is not None and recorded_year != sealed_year:
        raise ReportDiagnosticsError("Routine and sealed LCOE constant-dollar years disagree.")
    series = []
    for system, label, color in SYSTEMS:
        result = systems.get(system) or {}
        metric = result.get("headline_metric_id")
        if not metric or metric not in by_name:
            return {**unavailable, "reason": f"{label} saved lifecycle LCOE realizations are unavailable."}
        if result.get("technology") not in (None, system):
            raise ReportDiagnosticsError(f"{label} saved LCOE system ownership is inconsistent.")
        unit = result.get("unit")
        if unit is None:
            return {**unavailable, "reason": f"{label} saved LCOE units are unavailable."}
        if unit != "constant_usd_per_kwh_ac":
            raise ReportDiagnosticsError(f"{label} saved LCOE units do not permit the USD/MWh conversion.")
        try:
            values = np.asarray(by_name[metric], dtype=float)
        except (TypeError, ValueError) as error:
            raise ReportDiagnosticsError(f"{label} saved LCOE realizations are invalid.") from error
        if values.ndim != 1 or len(values) != count or not np.all(np.isfinite(values)):
            raise ReportDiagnosticsError(f"{label} saved LCOE values must be finite and match the realization count.")
        percentiles = result.get("percentiles") or {}
        if any(percentiles.get(key) is None for key, _ in PERCENTILES):
            return {**unavailable, "reason": f"{label} headline percentiles needed to verify the chart are unavailable."}
        calculated = np.quantile(values, [p for _, p in PERCENTILES], method="linear")
        for (key, _), value in zip(PERCENTILES, calculated):
            _tie_out(value, percentiles[key], f"{label} {key.upper()} CDF marker")
        unique, frequencies = np.unique(values, return_counts=True)
        cumulative_count = np.cumsum(frequencies, dtype=np.int64)
        probability = cumulative_count / count
        summary = (metadata.get("summaries") or {}).get(metric) or {}
        if "count" in summary and summary["count"] != count:
            raise ReportDiagnosticsError(f"{label} sealed LCOE summary count is inconsistent.")
        saved_cdf = summary.get("cdf")
        if saved_cdf is not None:
            try:
                saved_values = np.asarray(saved_cdf["values"], dtype=float)
                saved_probability = np.asarray(saved_cdf["cumulative_probability"], dtype=float)
            except (KeyError, TypeError, ValueError) as error:
                raise ReportDiagnosticsError(f"{label} sealed LCOE CDF evidence is invalid.") from error
            if (saved_cdf.get("population_count") != count or saved_values.shape != unique.shape
                    or saved_probability.shape != probability.shape
                    or not np.allclose(saved_values, unique, rtol=1e-12, atol=1e-12)
                    or not np.allclose(saved_probability, probability, rtol=0, atol=1e-15)):
                raise ReportDiagnosticsError(f"{label} regenerated ECDF disagrees with sealed CDF evidence.")
        series.append({"system": system, "label": label, "metric_id": metric, "color": color,
                       "values": (unique * 1000).tolist(), "probability": probability.tolist(),
                       "cumulative_count": cumulative_count.tolist(), "sample_count": int(count),
                       "percentiles": {key: float(value * 1000) for (key, _), value in zip(PERCENTILES, calculated)},
                       "linestyle": "--" if system == "solectria" else "-"})
    if series[0]["metric_id"] == series[1]["metric_id"]:
        raise ReportDiagnosticsError("The two systems cannot share one saved LCOE metric identity.")
    return {"status": "available", "reason": None, "series": series, "sample_count": int(count),
            "constant_dollar_cost_year": recorded_year if recorded_year is not None else sealed_year,
            "unit": "USD/MWh AC", "height": 3.55,
            "notes": ["Uses all verified saved realizations; no new simulation or random draws.",
                      "Right-continuous empirical CDFs collapse ties. P10/P50/P90 markers use the saved type-7 quantiles and agree with the report table."]}


def convergence_payloads(metadata, by_name, routine, *, row_count=None):
    """Type-7 P10/P50/P90 at saved cumulative checkpoints in original order.

The existing P5/P50/P95 convergence status and tests are not recalculated or
replaced. These extra report curves describe stability, not a new pass/fail gate.
"""
    checkpoints = (metadata.get("convergence") or {}).get("checkpoints") or []
    systems = ((routine.get("paired_commercial") or {}).get("systems") or {})
    if not checkpoints:
        return [_unavailable(system, label, "Saved convergence checkpoints are unavailable.") for system, label, _ in SYSTEMS]
    count = routine.get("realization_count")
    if not _count(count) or (row_count is not None and row_count != count):
        raise ReportDiagnosticsError("Saved realization count does not match the sealed calculation.")
    counts = [checkpoint.get("realization_count") for checkpoint in checkpoints]
    if (any(not _count(value) or value > count for value in counts)
            or any(left >= right for left, right in zip(counts, counts[1:])) or counts[-1] != count):
        raise ReportDiagnosticsError("Saved convergence checkpoints must increase strictly to the full realization count.")
    indices = by_name.get("realization_index")
    if indices is None:
        return [_unavailable(system, label, "Original realization order is unavailable in the saved evidence.") for system, label, _ in SYSTEMS]
    if not np.array_equal(np.asarray(indices), np.arange(1, count + 1)):
        raise ReportDiagnosticsError("Sealed realizations are not in their original one-based order.")
    payloads = []
    for system, label, color in SYSTEMS:
        result = systems.get(system) or {}
        metric = result.get("headline_metric_id")
        raw = by_name.get(metric)
        if raw is None:
            payloads.append(_unavailable(system, label, "Saved lifecycle LCOE realizations are unavailable."))
            continue
        try:
            values = np.asarray(raw, dtype=float)
        except (TypeError, ValueError) as error:
            raise ReportDiagnosticsError(f"{label} saved LCOE realizations are invalid.") from error
        if values.ndim != 1 or len(values) != count or not np.all(np.isfinite(values)):
            raise ReportDiagnosticsError(f"{label} saved LCOE values must be finite and match the realization count.")
        percentiles = result.get("percentiles") or {}
        if any(percentiles.get(key) is None for key, _ in PERCENTILES):
            payloads.append(_unavailable(system, label, "Headline P10/P50/P90 values needed to verify the final points are unavailable."))
            continue
        samples = []
        for checkpoint, prefix in zip(checkpoints, counts):
            population = values[:prefix]
            samples.append(np.quantile(population, [.1, .5, .9], method="linear"))
            saved = (checkpoint.get("metrics") or {}).get(metric)
            if saved is not None:
                if saved.get("population_count") != prefix:
                    raise ReportDiagnosticsError(f"{label} saved checkpoint population does not match its prefix.")
                saved_percentiles = saved.get("percentiles") or {}
                for key, probability in (("p5", .05), ("p50", .5), ("p95", .95)):
                    _tie_out(np.quantile(population, probability, method="linear"), saved_percentiles.get(key),
                             f"{label} checkpoint {prefix} {key.upper()}")
        for index, (key, _) in enumerate(PERCENTILES):
            _tie_out(samples[-1][index], percentiles[key], f"{label} final {key.upper()}")
        series = [{"label": key.upper(), "x": list(counts),
                   "values": [float(sample[index] * 1000) for sample in samples]}
                  for index, (key, _) in enumerate(PERCENTILES)]
        notes = ["Each checkpoint uses the first N saved realizations in their original order. Type-7 quantiles are shown in USD/MWh.",
                 "The final points agree with the headline percentile table. These curves do not replace the saved P5/P50/P95 convergence criteria or status."]
        if len(counts) < 2:
            notes.append("Only one checkpoint was saved; a trend cannot be assessed.")
        payloads.append({"system": system, "label": label, "status": "available", "reason": None,
                         "checkpoints": list(counts), "series": series, "sample_count": int(count),
                         "notes": notes, "color": color, "height": 2.85})
    return payloads


def _style_axis(ax, *, grid):
    ax.grid(axis=grid, color="#DDDDDD", linewidth=.6)
    ax.set_axisbelow(True)
    ax.spines[["top", "right"]].set_visible(False)
    ax.spines[["bottom", "left"]].set_color("#AAAAAA")
    ax.tick_params(axis="both", labelsize=CHART_FONT_SIZE)
    ax.xaxis.offsetText.set_fontsize(CHART_FONT_SIZE)
    ax.yaxis.offsetText.set_fontsize(CHART_FONT_SIZE)


def _tornado_figure(payload):
    if payload.get("status") != "available":
        raise ReportDiagnosticsError("An unavailable tornado payload cannot be charted.")
    fig = Figure(figsize=(CHART_WIDTH_INCHES, payload["height"]), dpi=320, facecolor="white")
    ax = fig.add_subplot(111)
    rows = payload["rows"]
    positions = np.arange(len(rows))
    values = [row["beta"] for row in rows]
    limit = payload["axis_limit"]
    ax.barh(positions, values, height=.62, color=payload["color"])
    ax.axvline(0, color="#444444", linewidth=.9)
    for position, value in zip(positions, values):
        ax.text(value + (.025 * limit if value >= 0 else -.025 * limit), position,
                f"{value:+.2f}", ha="left" if value >= 0 else "right", va="center", fontsize=CHART_FONT_SIZE)
    ax.set_yticks(positions, [row["display_label"] for row in rows])
    ax.tick_params(axis="y", length=0)
    ax.invert_yaxis()
    ax.set_xlim(-limit, limit)
    ax.set_xlabel("Standardized rank coefficient (dimensionless)", fontsize=CHART_FONT_SIZE)
    title = f"{payload['label']} lifecycle LCOE  |  n = {payload['sample_count']:,}  |  R² = {payload['r_squared']:.2f}"
    if payload["panel_count"] > 1:
        title += f"\nCoefficient ranks {payload['rank_start']}–{payload['rank_end']} of {payload['entered_predictor_count']}"
    ax.set_title(title, loc="left", fontsize=CHART_FONT_SIZE, pad=12)
    ax.xaxis.set_major_locator(MaxNLocator(5))
    ax.xaxis.set_major_formatter(StrMethodFormatter('{x:.2f}'))
    _style_axis(ax, grid="x")
    top_margin = .60 if payload["panel_count"] > 1 else .38
    fig.subplots_adjust(left=.37, right=.96, top=1 - top_margin / payload["height"], bottom=.50 / payload["height"])
    return fig


def _convergence_figure(payload):
    if payload.get("status") != "available":
        raise ReportDiagnosticsError("An unavailable convergence payload cannot be charted.")
    fig = Figure(figsize=(CHART_WIDTH_INCHES, payload["height"]), dpi=320, facecolor="white")
    ax = fig.add_subplot(111)
    for item, style, marker in zip(payload["series"], ("--", "-", ":"), ("v", "o", "^")):
        ax.plot(item["x"], item["values"], label=item["label"], color=payload["color"],
                linestyle=style, marker=marker, markersize=4, linewidth=1.7)
    ax.set_title(f"{payload['label']} lifecycle LCOE percentile stability", loc="left", fontsize=CHART_FONT_SIZE, pad=37)
    ax.set_xlabel("Cumulative realizations", fontsize=CHART_FONT_SIZE)
    ax.set_ylabel("LCOE (USD/MWh)", fontsize=CHART_FONT_SIZE)
    ax.xaxis.set_major_locator(MaxNLocator(integer=True))
    ax.xaxis.set_major_formatter(StrMethodFormatter('{x:,.0f}'))
    ax.yaxis.set_major_formatter(StrMethodFormatter('{x:,.2f}'))
    ax.legend(loc="lower left", bbox_to_anchor=(0, 1.01), ncols=3, frameon=False, fontsize=CHART_FONT_SIZE, borderaxespad=0)
    _style_axis(ax, grid="y")
    fig.subplots_adjust(left=.115, right=.97, top=.75, bottom=.21)
    return fig


def _lifecycle_cdf_figure(payload):
    if payload.get("status") != "available":
        raise ReportDiagnosticsError("An unavailable lifecycle CDF cannot be charted.")
    fig = Figure(figsize=(CHART_WIDTH_INCHES, payload["height"]), dpi=320, facecolor="white")
    ax = fig.add_subplot(111)
    for item in payload["series"]:
        # Include the first jump, including a constant population's jump 0 -> 1.
        ax.step([item["values"][0], *item["values"]], [0, *item["probability"]], where="post", color=item["color"],
                linestyle=item["linestyle"], linewidth=1.8, label=item["label"])
        for key, probability, marker in (("p10", .1, "v"), ("p50", .5, "o"), ("p90", .9, "^")):
            ax.scatter([item["percentiles"][key]], [probability], s=24, marker=marker,
                       facecolor="white", edgecolor=item["color"], linewidth=1.1, zorder=4)
    year = payload.get("constant_dollar_cost_year")
    basis = f"real {year} USD" if year is not None else "constant USD"
    ax.set_xlabel(f"Lifecycle LCOE ({basis}/MWh AC)", fontsize=CHART_FONT_SIZE)
    ax.set_ylabel("Probability at or below LCOE", fontsize=CHART_FONT_SIZE)
    ax.set_ylim(0, 1.025)
    ax.margins(x=.07)
    ax.set_yticks(np.linspace(0, 1, 6))
    ax.yaxis.set_major_formatter(PercentFormatter(1, decimals=2))
    ax.xaxis.set_major_formatter(StrMethodFormatter('{x:,.2f}'))
    ax.legend(loc="lower left", bbox_to_anchor=(0, 1.01), ncols=2, frameon=False, fontsize=CHART_FONT_SIZE, borderaxespad=0)
    ax.set_title(f"Lifecycle LCOE  |  n = {payload['sample_count']:,} per system", loc="left", fontsize=CHART_FONT_SIZE, pad=36)
    fig.text(.15, .025, "Markers: triangle down P10; circle P50; triangle up P90 (type-7 quantiles).", fontsize=CHART_FONT_SIZE)
    _style_axis(ax, grid="y")
    # Leave room for the full vertical title beside two-decimal percentage
    # ticks, including 100.00%. The PNG is embedded at its fixed document size.
    fig.subplots_adjust(left=.15, right=.98, top=.78, bottom=.21)
    return fig


def _png(figure):
    stream = BytesIO()
    FigureCanvasAgg(figure).print_png(stream)
    return base64.b64encode(stream.getvalue()).decode("ascii")


def render_tornado(payload):
    """Return one high-resolution PNG as base64 for either document renderer."""
    return _png(_tornado_figure(payload))


def render_convergence(payload):
    """Return one high-resolution PNG as base64 for either document renderer."""
    return _png(_convergence_figure(payload))


def render_lifecycle_cdf(payload):
    """Return a document-sized, high-resolution CDF PNG from saved evidence."""
    return _png(_lifecycle_cdf_figure(payload))
