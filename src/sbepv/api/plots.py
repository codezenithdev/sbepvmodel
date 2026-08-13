"""Input-data charts rendered before the slower PV model runs.

These give the dashboard something to show while a job is still executing.
matplotlib and pandas are imported inside the functions: the import cost is only
paid when a job actually renders, and the Agg backend is already pinned by
``sbepv.model`` well before then.
"""

from __future__ import annotations

from pathlib import Path

from sbepv import model
from sbepv.api import config
from sbepv.api.artifacts import _output_url


def _render_input_data_plots(csv_path: Path, output_base: Path) -> dict[str, str]:
    """Render early historian-input plots before the slower PV model runs."""
    import pandas as pd
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates

    df = pd.read_csv(csv_path)
    if "timestamp" not in df.columns:
        raise ValueError("Historian CSV is missing the timestamp column.")

    times = pd.to_datetime(df["timestamp"], errors="coerce")
    times = times.dt.tz_localize("UTC").dt.tz_convert("America/Denver")
    plot_df = df.loc[~times.isna()].copy()
    times = times.loc[~times.isna()]
    if plot_df.empty:
        raise ValueError("Historian CSV did not contain plottable timestamp rows.")

    numeric_cols = [
        "solaredge_measured_power",
        "solectria_measured_power",
        "dni",
        "ghi",
        "dhi",
    ]
    for col in numeric_cols:
        if col in plot_df.columns:
            plot_df[col] = pd.to_numeric(plot_df[col], errors="coerce")

    measured_path = output_base.with_name(f"{output_base.name}_measured_power.png")
    irradiance_path = output_base.with_name(f"{output_base.name}_irradiance.png")

    fig1, ax1 = plt.subplots(figsize=(14, 6))
    ax1.plot(
        times,
        plot_df["solaredge_measured_power"] / 1000.0,
        color="#dc2626",
        linewidth=2,
        label="SolarEdge measured",
    )
    ax1.plot(
        times,
        plot_df["solectria_measured_power"] / 1000.0,
        color="#2563eb",
        linewidth=2,
        label="Solectria measured",
    )
    ax1.set_title("Measured AC Power Input")
    ax1.set_xlabel("Time (Mountain)")
    ax1.set_ylabel("Measured Power (kW)")
    ax1.grid(True, alpha=0.25)
    ax1.legend(loc="best")
    ax1.xaxis.set_major_formatter(
        mdates.DateFormatter("%m-%d-%Y %H:%M", tz=config.LOCAL_TZ)
    )
    fig1.autofmt_xdate()
    fig1.savefig(measured_path, dpi=200, bbox_inches="tight")
    plt.close(fig1)

    fig2, ax2 = plt.subplots(figsize=(14, 6))
    for col, label, color in (
        ("dni", "DNI", "#f97316"),
        ("ghi", "GHI", "#16a34a"),
        ("dhi", "DHI", "#7c3aed"),
    ):
        if col in plot_df.columns:
            ax2.plot(times, plot_df[col], linewidth=2, color=color, label=label)
    ax2.set_title("Irradiance Input")
    ax2.set_xlabel("Time (Mountain)")
    ax2.set_ylabel("Irradiance (W/m2)")
    ax2.grid(True, alpha=0.25)
    ax2.legend(loc="best")
    ax2.xaxis.set_major_formatter(
        mdates.DateFormatter("%m-%d-%Y %H:%M", tz=config.LOCAL_TZ)
    )
    fig2.autofmt_xdate()
    fig2.savefig(irradiance_path, dpi=200, bbox_inches="tight")
    plt.close(fig2)

    return {
        "measured_power_png": _output_url(measured_path),
        "irradiance_png": _output_url(irradiance_path),
    }
