"""sbe_pv_model.py

Our own physics-based PV prediction model for the SBE Innovation Center PV
(STAC1) East array. Consumes the historian CSV (stac1.csv) and predicts AC power
and cumulative energy for the two systems, then compares against measured:

  - SolarEdge  -> module-level optimization (sum of module Pmp)
  - Solectria  -> string-level mismatch (pvmismatch)

This is a fresh, automated reimplementation of the physics in pvmismatch_Ho_v8.py
(the reference blueprint, which is NOT modified). Differences from the reference:
  - Runs with no prompts; all settings are the constants below.
  - Reads OUR column names (see COLUMN_RENAME) from stac1.csv.
  - Uses MEASURED DHI from the CSV when present (only derives it from GHI/DNI when
    DHI is missing).

INPUT  (stac1.csv, produced by bazefield_historian.py):
  timestamp, solaredge_measured_power, solectria_measured_power,
  dni, ghi, dhi, temp_air, wind_speed          (power in W, irradiance W/m2, degC, m/s)

OUTPUT:
  <OUTPUT_BASE>_ac_power.png, <OUTPUT_BASE>_cumulative_energy.png
  <OUTPUT_BASE>.xlsx  (tabs: time_series, tilts_and_strings, run_info)
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import matplotlib

matplotlib.use("Agg")  # non-interactive: save PNGs, never block on show()
import matplotlib.pyplot as plt

import pvlib as pvl
import pvmismatch as pvm
from pvmismatch.contrib import gen_coeffs

__version__ = "1"

# -----------------------------------------------------------------------------
# RUN SETTINGS (edit here -- no command-line prompts)
# -----------------------------------------------------------------------------
INPUT_CSV = "stac1.csv"
OUTPUT_BASE = "stac1_model"
INPUT_IS_UTC = True  # historian writes UTC timestamps
TIMEZONE = "America/Denver"  # local tz for display/indexing

# AC conversion efficiencies (predicted DC * eff). 1.0 = no derate.
SE_EFF = 1.0
SOL_EFF = 1.0

# Incidence-angle modifier (Martin-Ruiz). The default a_r is always applied.
# INCLUDE_IAM is retained as the API/UI flag for supplying a custom a_r value.
INCLUDE_IAM = False
A_R = 0.2


def resolve_iam_a_r(include_iam: bool, iam_a_r: float = A_R) -> float:
    """Return the custom IAM coefficient when enabled, otherwise the default."""
    value = float(iam_a_r) if include_iam else A_R
    if not np.isfinite(value) or value <= 0:
        raise ValueError("Martin-Ruiz a_r must be a positive finite value.")
    return value


# -----------------------------------------------------------------------------
# SITE / GEOMETRY / LAYOUT (copied verbatim from pvmismatch_Ho_v8.py)
# -----------------------------------------------------------------------------
LAT, LON = 39.7552, -104.6184  # SolarTAC SBE coordinates

AXIS_AZIMUTH = 180
MAX_ANGLE = 60
GCR = 0.4
BACKTRACK = True

INVERTER_PARAMETERS = {"pdc0": 9e9, "eta_inv_nom": 1}

MODULES_PER_BAY = 6
SOLECTRIA_STRINGS = 10
SOLECTRIA_BAYS_PER_STRING = 4
SOLAREDGE_STRINGS = 5
SOLAREDGE_BAYS_PER_STRING = 8

# Sandia module temperature model parameters
TEMPERATURE_MODEL_PARAMETERS = {"a": -3.47, "b": -0.0594, "deltaT": 0}

# As-built torque-tube slopes (axis_tilt, degrees) -- verbatim from reference.
SOLAREDGE_TILT_ASBUILT = [
    [3.05, 0.96, -1.35, -7.27, 7.31, -0.58, -0.05, -3.46],
    [-4.95, 7.62, -7.19, -0.26, -3.52, -5.27, 4.22, 2.67],
    [3.16, 0.71, -1.26, -7.46, 7.56, -0.57, 0.56, 2.87],
    [-3.4, -5.29, 7.06, -0.53, -0.12, -7.27, 2.86, 2.4],
    [2.78, -3.38, -5, 7.31, -0.57, -0.12, -7.28, 2.59],
]

SOLECTRIA_TILT_ASBUILT = [
    [3.14, 0.93, -1.41, -7.44],
    [7.52, -0.84, -0.03, -3.47],
    [-4.9, 7.63, -7.32, 4.27],
    [-0.5, -0.11, -3.58, -5.1],
    [0.73, -1.3, -7.45, 7.2],
    [2.78, 2.76, -3.26, -4.99],
    [7.28, -0.82, -0.08, -7.21],
    [2.59, 2.78, -3.9, 2.55],
    [0.62, -4.96, 7.61, -0.86],
    [-0.23, -7.16, 2.57, 2.6],
]

# -----------------------------------------------------------------------------
# MODULE PARAMETERS -- WAAREE BiN-08-580 (bifacial), verbatim from reference
# -----------------------------------------------------------------------------
_modules = pvl.pvsystem.retrieve_sam("CECMod")
_modules["WAAREE_BIN_08_580"] = _modules.index.map(
    {
        "Technology": "Mono-c-Si",
        "Bifacial": 1,
        "STC": 579.92,
        "PTC": 550.7,
        "A_c": 2.56,
        "Length": 0,
        "Width": 0,
        "N_s": 72,
        "I_sc_ref": 13.93,
        "V_oc_ref": 52.5,
        "I_mp_ref": 13.18,
        "V_mp_ref": 44,
        "alpha_sc": 0.0045969,
        "beta_oc": -0.12548,
        "T_NOCT": 43.2,
        "a_ref": 1.82068,
        "I_L_ref": 13.9415,
        "I_o_ref": 4.12e-12,
        "R_s": 0.206355,
        "R_sh_ref": 249.122,
        "Adjust": 3.05545,
        "gamma_r": -0.302,
        "BIPV": "N",
        "Version": "SAM 2023.12.17",
        "Date": "11/14/2024",
    }
)
MODULE_PARAMETERS = _modules["WAAREE_BIN_08_580"]
MODULE_NAME = "WAAREE_BIN_08_580"

# Our CSV column names -> the canonical names used internally.
COLUMN_RENAME = {
    "solaredge_measured_power": "se_measured_power_w",
    "solectria_measured_power": "sol_measured_power_w",
    "dni": "dni_wm2",
    "ghi": "ghi_wm2",
    "dhi": "dhi_wm2",
    "temp_air": "temp_air_c",
    "wind_speed": "wind_speed_ms",
}

MIDC_COLUMNS = {
    "DATE (MM/DD/YYYY)": "date",
    "HOUR-MST": "hour_mst",
    "Avg Global Horizontal [W/m^2]": "ghi_wm2",
    "Avg Direct Normal [W/m^2]": "dni_wm2",
    "Avg Diffuse Horizontal [W/m^2]": "dhi_wm2",
    "Avg Air Temperature [deg C]": "temp_air_c",
    "Avg Avg Wind Speed @ 10m [m/s]": "wind_speed_ms",
}


# -----------------------------------------------------------------------------
# I/O + PRE-PROCESSING
# -----------------------------------------------------------------------------
def parse_input_csv(path: str) -> pd.DataFrame:
    """Read stac1.csv, rename to canonical columns, index by local (tz-aware) time."""
    df = pd.read_csv(path)
    df = df.rename(columns=COLUMN_RENAME)
    df = df.dropna(subset=["timestamp"]).copy()

    ts = pd.to_datetime(df["timestamp"], errors="coerce")
    df = df.loc[~ts.isna()].copy()
    ts = ts.loc[~ts.isna()]

    if getattr(ts.dt, "tz", None) is None:
        if INPUT_IS_UTC:
            ts_local = ts.dt.tz_localize(
                "UTC", ambiguous="infer", nonexistent="shift_forward"
            ).dt.tz_convert(TIMEZONE)
        else:
            ts_local = ts.dt.tz_localize(
                TIMEZONE, ambiguous="infer", nonexistent="shift_forward"
            )
    else:
        ts_local = ts.dt.tz_convert(TIMEZONE)

    df.insert(0, "timestamp_local", ts_local)
    df["timestamp_utc"] = df["timestamp_local"].dt.tz_convert("UTC")
    df = df.set_index("timestamp_local").sort_index()

    numeric = [
        "se_measured_power_w",
        "sol_measured_power_w",
        "dni_wm2",
        "ghi_wm2",
        "dhi_wm2",
        "temp_air_c",
        "wind_speed_ms",
    ]
    for c in numeric:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")

    df["dni_wm2"] = df["dni_wm2"].fillna(0.0)
    df["ghi_wm2"] = df["ghi_wm2"].fillna(0.0)
    df["temp_air_c"] = df["temp_air_c"].interpolate(limit_direction="both")
    df["wind_speed_ms"] = (
        df["wind_speed_ms"].interpolate(limit_direction="both").fillna(0.0)
    )
    return df


def parse_midc_csv(path: str) -> tuple[pd.DataFrame, list[str]]:
    """Read dashboard-generated MIDC hourly data using fixed MST timestamps."""
    raw = pd.read_csv(path)
    missing_columns = sorted(set(MIDC_COLUMNS).difference(raw.columns))
    if missing_columns:
        raise ValueError(
            "MIDC file is missing required columns: " + ", ".join(missing_columns)
        )

    raw = raw.rename(columns=MIDC_COLUMNS)
    parsed_dates = pd.to_datetime(raw["date"], format="%m/%d/%Y", errors="coerce")
    hours = pd.to_numeric(raw["hour_mst"], errors="coerce")
    valid_time = parsed_dates.notna() & hours.between(0, 23) & hours.mod(1).eq(0)
    warnings: list[str] = []
    invalid_time_count = int((~valid_time).sum())
    if invalid_time_count:
        warnings.append(
            f"Dropped {invalid_time_count} MIDC row(s) with invalid date/hour values."
        )
    raw = raw.loc[valid_time].copy()
    parsed_dates = parsed_dates.loc[valid_time]
    hours = hours.loc[valid_time].astype(int)
    if raw.empty:
        raise ValueError("MIDC file contains no valid date/hour rows.")

    timestamp_mst = (
        parsed_dates + pd.to_timedelta(hours, unit="h")
    ).dt.tz_localize("Etc/GMT+7")
    timestamp_local = timestamp_mst.dt.tz_convert(TIMEZONE)

    data = pd.DataFrame(index=timestamp_local)
    for column in ("ghi_wm2", "dni_wm2", "dhi_wm2", "temp_air_c", "wind_speed_ms"):
        data[column] = pd.to_numeric(raw[column], errors="coerce").to_numpy()

    missing_counts = data[
        ["ghi_wm2", "dni_wm2", "dhi_wm2", "temp_air_c", "wind_speed_ms"]
    ].isna().sum()
    if int(missing_counts.sum()):
        detail = ", ".join(
            f"{column}={int(count)}"
            for column, count in missing_counts.items()
            if count
        )
        warnings.append(
            "Hourly MIDC gaps were filled for modeling "
            f"({detail}): GHI/DNI use zero, temperature/wind interpolate, "
            "and DHI uses a solar-position-derived fallback."
        )

    for column in ("ghi_wm2", "dni_wm2", "dhi_wm2"):
        data[column] = data[column].clip(lower=0.0)
    data["ghi_wm2"] = data["ghi_wm2"].fillna(0.0)
    data["dni_wm2"] = data["dni_wm2"].fillna(0.0)
    data["temp_air_c"] = data["temp_air_c"].interpolate(limit_direction="both")
    data["wind_speed_ms"] = (
        data["wind_speed_ms"].interpolate(limit_direction="both").fillna(0.0)
    )
    if data["temp_air_c"].isna().any():
        raise ValueError("MIDC air temperature is missing for the entire date range.")

    data["se_measured_power_w"] = 0.0
    data["sol_measured_power_w"] = 0.0
    data["timestamp_utc"] = data.index.tz_convert("UTC")
    data.index.name = "timestamp_local"
    if data.index.has_duplicates:
        raise ValueError("MIDC date/hour keys contain duplicate timestamps.")
    return data.sort_index(), warnings


# -----------------------------------------------------------------------------
# PVLIB WEATHER + MODELCHAIN
# -----------------------------------------------------------------------------
def build_weather(
    df: pd.DataFrame, location: pvl.location.Location
) -> tuple[pd.DataFrame, str]:
    """Build the pvlib weather frame. Prefer MEASURED DHI; derive it only if absent."""
    times = df.index
    dni = df["dni_wm2"].to_numpy(dtype=float)
    ghi = df["ghi_wm2"].to_numpy(dtype=float)

    solpos = location.get_solarposition(times)
    cos_zen = np.cos(np.deg2rad(solpos["zenith"].clip(0, 90))).to_numpy()
    derived = np.maximum(ghi - dni * cos_zen, 0.0)

    if "dhi_wm2" in df.columns and df["dhi_wm2"].notna().any():
        dhi = df["dhi_wm2"].to_numpy(dtype=float)
        missing = np.isnan(dhi)
        dhi = np.where(missing, derived, dhi)
        dhi = np.clip(dhi, 0.0, None)
        dhi_source = (
            "measured with derived fallback"
            if missing.any()
            else "measured"
        )
    else:
        dhi = derived
        dhi_source = "derived (GHI-DNI*cos z)"

    weather = pd.DataFrame(
        index=times,
        data={
            "dni": dni,
            "ghi": ghi,
            "dhi": dhi,
            "temp_air": df["temp_air_c"].to_numpy(),
            "wind_speed": df["wind_speed_ms"].to_numpy(),
        },
    )
    return weather, dhi_source


def run_modelchain_for_axis_tilt(
    axis_tilt: float,
    weather: pd.DataFrame,
    location: pvl.location.Location,
    backtrack: bool = BACKTRACK,
    include_iam: bool = INCLUDE_IAM,
    iam_a_r: float = A_R,
) -> dict:
    """Run pvlib ModelChain for a single tracker axis tilt -> Ee (suns), Tk, p_mp (W)."""
    effective_iam_a_r = resolve_iam_a_r(include_iam, iam_a_r)
    module_parameters = MODULE_PARAMETERS.copy()
    module_parameters["a_r"] = effective_iam_a_r
    array = pvl.pvsystem.Array(
        mount=pvl.pvsystem.SingleAxisTrackerMount(
            axis_tilt=axis_tilt,
            axis_azimuth=AXIS_AZIMUTH,
            max_angle=MAX_ANGLE,
            backtrack=bool(backtrack),
            gcr=GCR,
        ),
        module_parameters=module_parameters,
        temperature_model_parameters=TEMPERATURE_MODEL_PARAMETERS,
        modules_per_string=1,
        strings=1,
    )
    system = pvl.pvsystem.PVSystem(
        arrays=[array], inverter_parameters=INVERTER_PARAMETERS
    )

    mc = pvl.modelchain.ModelChain(
        system, location, aoi_model="martin_ruiz", spectral_model="no_loss"
    )
    mc.run_model(weather)

    effective = mc.results.effective_irradiance

    return {
        "Ee_suns": (effective / 1000.0).to_numpy(),
        "Tk": (mc.results.cell_temperature + 273.15).to_numpy(),
        "p_mp_w": mc.results.dc.p_mp.to_numpy(),
    }


# -----------------------------------------------------------------------------
# PVMISMATCH MODULE (two-diode fit)
# -----------------------------------------------------------------------------
def build_pvmismatch_module() -> pvm.pvmodule.PVmodule:
    """Create a pvmismatch PVmodule matching the CEC module."""
    args = (
        MODULE_PARAMETERS["I_sc_ref"],
        MODULE_PARAMETERS["V_oc_ref"],
        MODULE_PARAMETERS["I_mp_ref"],
        MODULE_PARAMETERS["V_mp_ref"],
        MODULE_PARAMETERS["N_s"],
        1,
        25,
    )
    x, _ = gen_coeffs.gen_two_diode(*args)
    pv_cell = pvm.pvcell.PVcell(
        Isat1_T0=x[0],
        Isat2_T0=x[1],
        Rs=x[2],
        Rsh=x[3],
        Isc0_T0=MODULE_PARAMETERS["I_sc_ref"],
        alpha_Isc=0.0005,
        pvconst=pvm.pvconstants.PVconstants(),
    )
    return pvm.pvmodule.PVmodule(
        cell_pos=pvm.pvmodule.STD72,
        cellArea=MODULE_PARAMETERS["A_c"],
        pvcells=[pv_cell] * int(MODULE_PARAMETERS["N_s"]),
    )


# -----------------------------------------------------------------------------
# SYSTEM PREDICTION
# -----------------------------------------------------------------------------
def predict_ac_power(
    df: pd.DataFrame,
    progress_cb=None,
    backtrack: bool = BACKTRACK,
    se_eff: float = SE_EFF,
    sol_eff: float = SOL_EFF,
    include_iam: bool = INCLUDE_IAM,
    iam_a_r: float = A_R,
) -> tuple[pd.DataFrame, str]:
    """Add predicted AC power columns for SolarEdge and Solectria.

    progress_cb(frac, msg): optional callback (frac in 0..1) for the Solectria
    time loop, so a UI can show a moving progress bar.
    """
    location = pvl.location.Location(LAT, LON, tz=str(df.index.tz))
    weather, dhi_source = build_weather(df, location)

    all_tilts = (
        np.array(SOLECTRIA_TILT_ASBUILT).flatten().tolist()
        + np.array(SOLAREDGE_TILT_ASBUILT).flatten().tolist()
    )
    unique_tilts = sorted({float(t) for t in all_tilts})
    print(f"ModelChain over {len(unique_tilts)} unique tilts (DHI source: {dhi_source})...")

    tilt_out = {
        t: run_modelchain_for_axis_tilt(
            t,
            weather,
            location,
            backtrack=backtrack,
            include_iam=include_iam,
            iam_a_r=iam_a_r,
        )
        for t in unique_tilts
    }

    # SolarEdge: module-level -> sum module p_mp over all bays x MODULES_PER_BAY
    se_dc = np.zeros(len(df), dtype=float)
    for t in np.array(SOLAREDGE_TILT_ASBUILT).flatten():
        se_dc += tilt_out[float(t)]["p_mp_w"] * MODULES_PER_BAY

    # Solectria: per-string mismatch via pvmismatch, per timestep
    pvm_mod = build_pvmismatch_module()
    solectria_strings = []
    for row in SOLECTRIA_TILT_ASBUILT:
        nmods = MODULES_PER_BAY * SOLECTRIA_BAYS_PER_STRING
        pvstr = pvm.pvstring.PVstring(numberMods=nmods, pvmods=[pvm_mod] * nmods)
        bay_Ee = [tilt_out[float(t)]["Ee_suns"] for t in row]
        bay_Tk = [tilt_out[float(t)]["Tk"] for t in row]
        solectria_strings.append((pvstr, bay_Ee, bay_Tk))

    n = len(df)
    print(f"Solectria string mismatch over {n} timesteps...")
    sol_dc = np.zeros(n, dtype=float)
    for j in range(n):
        if progress_cb is not None and (j % 5 == 0 or j == n - 1):
            progress_cb(j / n if n else 1.0, f"Computing string mismatch… {j + 1}/{n}")
        # Skip night / no-irradiance steps (first string's first bay as proxy)
        if np.isnan(solectria_strings[0][1][0][j]) or solectria_strings[0][1][0][j] < 0.01:
            continue
        for pvstr, bay_Ee, bay_Tk in solectria_strings:
            nmods = pvstr.numberMods
            Ee = {k: float(bay_Ee[k // MODULES_PER_BAY][j]) for k in range(nmods)}
            Tk = {k: float(bay_Tk[k // MODULES_PER_BAY][j]) for k in range(nmods)}
            pvstr.setSuns(Ee)
            pvstr.setTemps(Tk)
            _, _, Pstring = pvstr.calcString()
            sol_dc[j] += float(np.nanmax(Pstring))

    out = df.copy()
    out["se_predicted_power_w"] = se_dc * float(se_eff)
    out["sol_predicted_power_w"] = sol_dc * float(sol_eff)
    return out, dhi_source


def add_energy(df: pd.DataFrame) -> pd.DataFrame:
    """Add interval dt_hours and cumulative energies (kWh)."""
    out = df.copy()
    dt_h = out.index.to_series().diff().dt.total_seconds() / 3600.0
    dt0 = float(dt_h.dropna().median()) if dt_h.notna().any() else 0.0
    out["dt_hours"] = dt_h.fillna(dt0).clip(lower=0.0)

    for sysname in ("se", "sol"):
        for kind in ("measured", "predicted"):
            step = f"{sysname}_{kind}_energy_step_kwh"
            out[step] = out[f"{sysname}_{kind}_power_w"] * out["dt_hours"] / 1000.0
            out[f"{sysname}_{kind}_energy_kwh"] = out[step].cumsum()
    return out


def apply_curtailment(df: pd.DataFrame, limit_kw: float | None) -> pd.DataFrame:
    """Clip measured and predicted AC power columns to a per-series kW limit."""
    if limit_kw is None:
        return df

    cap_kw = float(limit_kw)
    if not np.isfinite(cap_kw) or cap_kw <= 0:
        raise ValueError("Curtailment limit must be a positive kW value.")

    out = df.copy()
    cap_w = cap_kw * 1000.0
    for col in (
        "se_measured_power_w",
        "sol_measured_power_w",
        "se_predicted_power_w",
        "sol_predicted_power_w",
    ):
        out[col] = out[col].clip(upper=cap_w)
    return out


# -----------------------------------------------------------------------------
# REPORTING (plots + Excel)
# -----------------------------------------------------------------------------
def tilt_summary() -> pd.DataFrame:
    """Bay tilt + string mapping for both systems."""
    recs = []
    for sysname, strings, bays, table in (
        ("Solectria", SOLECTRIA_STRINGS, SOLECTRIA_BAYS_PER_STRING, SOLECTRIA_TILT_ASBUILT),
        ("SolarEdge", SOLAREDGE_STRINGS, SOLAREDGE_BAYS_PER_STRING, SOLAREDGE_TILT_ASBUILT),
    ):
        bay_id = 1
        for s in range(strings):
            for b in range(bays):
                recs.append(
                    {
                        "system": sysname,
                        "string_id": s + 1,
                        "bay_in_string": b + 1,
                        "bay_id": bay_id,
                        "axis_tilt_deg": float(table[s][b]),
                        "modules_per_bay": MODULES_PER_BAY,
                    }
                )
                bay_id += 1
    return pd.DataFrame.from_records(recs)


def plot_results(
    df: pd.DataFrame, out_prefix: str, annual_mode: bool = False
) -> None:
    """Save AC-power and cumulative-energy charts for the selected run mode."""
    # AC power
    fig1, ax1 = plt.subplots(figsize=(14, 6))
    ax1.plot(df.index, df["se_predicted_power_w"] / 1000.0, "r-", label="SolarEdge predicted")
    ax1.plot(df.index, df["sol_predicted_power_w"] / 1000.0, "b-", label="Solectria predicted")
    if not annual_mode:
        ax1.plot(df.index, df["se_measured_power_w"] / 1000.0, "r--", label="SolarEdge measured")
        ax1.plot(df.index, df["sol_measured_power_w"] / 1000.0, "b--", label="Solectria measured")
    ax1.set_title(f"AC Power (kW) — sbe_pv_model v{__version__}")
    if annual_mode:
        ax1.set_title("Predicted AC Power (kW) - Annual Simulation")
    ax1.set_xlabel(f"Time ({df.index.tz})")
    ax1.set_ylabel("AC Power (kW)")
    ax1.grid(True, alpha=0.25)
    ax1.legend(loc="best")
    fig1.autofmt_xdate()

    se_meas = float(df["se_measured_energy_kwh"].iloc[-1])
    se_pred = float(df["se_predicted_energy_kwh"].iloc[-1])
    sol_meas = float(df["sol_measured_energy_kwh"].iloc[-1])
    sol_pred = float(df["sol_predicted_energy_kwh"].iloc[-1])

    def pct(pred, meas):
        return (pred - meas) / meas * 100.0 if meas != 0 else np.nan

    ac_txt = (
        f"SolarEdge: meas={se_meas:,.1f} kWh, pred={se_pred:,.1f} kWh, Δ={pct(se_pred, se_meas):+.2f}%\n"
        f"Solectria: meas={sol_meas:,.1f} kWh, pred={sol_pred:,.1f} kWh, Δ={pct(sol_pred, sol_meas):+.2f}%"
    )
    if annual_mode:
        pred_diff = se_pred - sol_pred
        pred_pct = pred_diff / sol_pred * 100.0 if sol_pred != 0 else np.nan
        ac_txt = (
            f"Period energy (kWh)\nSolarEdge: {se_pred:,.0f}\n"
            f"Solectria: {sol_pred:,.0f}\n"
            f"Difference: {pred_diff:,.0f} ({pred_pct:+.2f}%)"
        )
    ax1.text(
        0.01, 0.99, ac_txt, transform=ax1.transAxes, va="top", ha="left", fontsize=11,
        bbox=dict(boxstyle="round", facecolor="white", alpha=0.85, edgecolor="gray"),
    )
    fig1.savefig(f"{out_prefix}_ac_power.png", dpi=200, bbox_inches="tight")

    # Cumulative energy
    fig2, ax2 = plt.subplots(figsize=(14, 6))
    ax2.plot(df.index, df["se_predicted_energy_kwh"], "r-", label="SolarEdge predicted")
    ax2.plot(df.index, df["sol_predicted_energy_kwh"], "b-", label="Solectria predicted")
    if not annual_mode:
        ax2.plot(df.index, df["se_measured_energy_kwh"], "r--", label="SolarEdge measured")
        ax2.plot(df.index, df["sol_measured_energy_kwh"], "b--", label="Solectria measured")
    ax2.set_title(f"Cumulative Energy (kWh) — sbe_pv_model v{__version__}")
    if annual_mode:
        ax2.set_title("Cumulative Predicted Energy (kWh) - Annual Simulation")
    ax2.set_xlabel(f"Time ({df.index.tz})")
    ax2.set_ylabel("Cumulative Energy (kWh)")
    ax2.grid(True, alpha=0.25)
    ax2.legend(loc="best")
    fig2.autofmt_xdate()

    meas_sys_pct = (se_meas - sol_meas) / sol_meas * 100.0 if sol_meas != 0 else np.nan
    pred_sys_pct = (se_pred - sol_pred) / sol_pred * 100.0 if sol_pred != 0 else np.nan
    ce_txt = (
        f"SolarEdge\n measured : {se_meas:,.1f} kWh\n predicted: {se_pred:,.1f} kWh\n Δ: {pct(se_pred, se_meas):+.2f}%\n\n"
        f"Solectria\n measured : {sol_meas:,.1f} kWh\n predicted: {sol_pred:,.1f} kWh\n Δ: {pct(sol_pred, sol_meas):+.2f}%\n\n"
        f"SE vs Sol\n measured Δ : {meas_sys_pct:+.2f}%\n predicted Δ: {pred_sys_pct:+.2f}%"
    )
    if annual_mode:
        ce_txt = ac_txt
    ax2.text(
        0.01, 0.99, ce_txt, transform=ax2.transAxes, va="top", ha="left", fontsize=11,
        bbox=dict(boxstyle="round", facecolor="white", alpha=0.85, edgecolor="gray"),
    )
    fig2.savefig(f"{out_prefix}_cumulative_energy.png", dpi=200, bbox_inches="tight")
    plt.close("all")


def monthly_energy_table(df: pd.DataFrame) -> pd.DataFrame:
    """Return one predicted-energy summary row per local calendar month."""
    se_monthly = df["se_predicted_energy_step_kwh"].resample("MS").sum()
    sol_monthly = df["sol_predicted_energy_step_kwh"].resample("MS").sum()
    sol_monthly = sol_monthly.reindex(se_monthly.index)
    result = pd.DataFrame(
        {
            "month": se_monthly.index.strftime("%b %Y"),
            "month_start": se_monthly.index.tz_localize(None),
            "SolarEdge_predicted_kWh": se_monthly.to_numpy(),
            "Solectria_predicted_kWh": sol_monthly.to_numpy(),
        }
    )
    result["difference_kWh"] = (
        result["SolarEdge_predicted_kWh"] - result["Solectria_predicted_kWh"]
    )
    result["difference_pct"] = np.where(
        result["Solectria_predicted_kWh"] != 0,
        result["difference_kWh"] / result["Solectria_predicted_kWh"] * 100.0,
        np.nan,
    )
    return result


def plot_monthly_energy(df: pd.DataFrame, out_prefix: str) -> None:
    """Save the annual-result monthly predicted-energy comparison chart."""
    monthly = monthly_energy_table(df)
    x = np.arange(len(monthly))
    width = 0.38
    fig, ax = plt.subplots(figsize=(14, 6))
    se_values = monthly["SolarEdge_predicted_kWh"].to_numpy(dtype=float)
    sol_values = monthly["Solectria_predicted_kWh"].to_numpy(dtype=float)
    ax.bar(x - width / 2, se_values, width=width, color="red", label="SolarEdge (kWh)")
    ax.bar(x + width / 2, sol_values, width=width, color="blue", label="Solectria (kWh)")
    ax.set_xticks(x)
    ax.set_xticklabels(monthly["month"], rotation=35, ha="right")
    ax.set_xlabel("Month")
    ax.set_ylabel("Predicted Energy (kWh)")
    ax.set_title("Monthly Predicted Energy - Annual Simulation")
    ax.grid(True, axis="y", alpha=0.25)
    ax.legend(loc="best")

    ymax = float(np.nanmax([se_values.max(), sol_values.max()])) if len(monthly) else 0.0
    pad = ymax * 0.02 if ymax > 0 else 0.0
    for index, row in monthly.iterrows():
        pct_value = float(row["difference_pct"])
        label = "n/a" if not np.isfinite(pct_value) else f"{pct_value:+.1f}%"
        ax.text(
            x[index],
            max(row["SolarEdge_predicted_kWh"], row["Solectria_predicted_kWh"]) + pad,
            label,
            ha="center",
            va="bottom",
            fontsize=9,
            bbox=dict(boxstyle="round", facecolor="white", alpha=0.85, edgecolor="gray"),
        )

    se_total = float(df["se_predicted_energy_kwh"].iloc[-1])
    sol_total = float(df["sol_predicted_energy_kwh"].iloc[-1])
    total_diff = se_total - sol_total
    total_pct = total_diff / sol_total * 100.0 if sol_total else np.nan
    ax.text(
        0.01,
        0.99,
        f"Period energy (kWh)\nSolarEdge: {se_total:,.0f}\n"
        f"Solectria: {sol_total:,.0f}\nDifference: {total_diff:,.0f} ({total_pct:+.2f}%)",
        transform=ax.transAxes,
        va="top",
        ha="left",
        fontsize=10,
        bbox=dict(boxstyle="round", facecolor="white", alpha=0.85, edgecolor="gray"),
    )
    fig.tight_layout()
    fig.savefig(f"{out_prefix}_monthly_energy.png", dpi=200, bbox_inches="tight")
    plt.close(fig)


def write_excel(
    df: pd.DataFrame, excel_path: str, meta: dict, annual_mode: bool = False
) -> None:
    """Write time series, layout, run metadata, and optional monthly energy."""
    out = df.copy()
    out["timestamp_local_naive"] = out.index.tz_localize(None)
    out["timestamp_utc_naive"] = out["timestamp_utc"].dt.tz_localize(None)

    cols = [
        "timestamp_local_naive",
        "timestamp_utc_naive",
        "se_measured_power_w",
        "se_predicted_power_w",
        "sol_measured_power_w",
        "sol_predicted_power_w",
        "se_measured_energy_kwh",
        "se_predicted_energy_kwh",
        "sol_measured_energy_kwh",
        "sol_predicted_energy_kwh",
        "dni_wm2",
        "ghi_wm2",
        "temp_air_c",
        "wind_speed_ms",
        "dt_hours",
    ]
    if "dhi_wm2" in out.columns:
        cols.insert(11, "dhi_wm2")

    with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
        out[cols].to_excel(writer, sheet_name="time_series", index=False)
        tilt_summary().to_excel(writer, sheet_name="tilts_and_strings", index=False)
        if annual_mode:
            monthly_energy_table(df).to_excel(
                writer, sheet_name="monthly_energy", index=False
            )
        pd.DataFrame(list(meta.items()), columns=["parameter", "value"]).to_excel(
            writer, sheet_name="run_info", index=False
        )


# -----------------------------------------------------------------------------
# CALLABLE ENTRYPOINT + MAIN
# -----------------------------------------------------------------------------
def run_model(
    input_csv=INPUT_CSV,
    output_base=OUTPUT_BASE,
    progress_cb=None,
    backtrack: bool = BACKTRACK,
    solaredge_inverter_efficiency: float = 1.0,
    solaredge_bos_efficiency: float = 1.0,
    solectria_inverter_efficiency: float = 1.0,
    solectria_bos_efficiency: float = 1.0,
    include_iam: bool = INCLUDE_IAM,
    iam_a_r: float = A_R,
    curtailment_enabled: bool = False,
    curtailment_limit_kw: float | None = None,
    input_kind: str = "historian",
    annual_mode: bool = False,
) -> dict:
    """Run the full model on input_csv, write PNGs + Excel, return a stats dict.

    progress_cb(frac, msg): optional; forwarded to the Solectria time loop.
    Returns measured/predicted energy totals and pred-vs-meas % per system.
    """
    se_inv_eff = float(solaredge_inverter_efficiency)
    se_bos_eff = float(solaredge_bos_efficiency)
    sol_inv_eff = float(solectria_inverter_efficiency)
    sol_bos_eff = float(solectria_bos_efficiency)
    se_eff = se_inv_eff * se_bos_eff
    sol_eff = sol_inv_eff * sol_bos_eff
    effective_iam_a_r = resolve_iam_a_r(include_iam, iam_a_r)

    data_quality_warnings: list[str] = []
    if input_kind == "midc":
        df, data_quality_warnings = parse_midc_csv(input_csv)
    elif input_kind == "historian":
        df = parse_input_csv(input_csv)
    else:
        raise ValueError(f"Unsupported model input kind: {input_kind}")
    def prediction_progress(frac: float, msg: str) -> None:
        if progress_cb:
            progress_cb(max(0.0, min(1.0, frac)) * 0.84, msg)

    df, dhi_source = predict_ac_power(
        df,
        progress_cb=prediction_progress,
        backtrack=backtrack,
        se_eff=se_eff,
        sol_eff=sol_eff,
        include_iam=include_iam,
        iam_a_r=iam_a_r,
    )
    if curtailment_enabled and curtailment_limit_kw is None:
        raise ValueError("Curtailment limit must be a positive kW value.")
    if progress_cb:
        progress_cb(0.86, "Applying curtailment and integrating energy")
    active_curtailment_limit_kw = (
        float(curtailment_limit_kw) if curtailment_enabled else None
    )
    df = apply_curtailment(df, active_curtailment_limit_kw)
    df = add_energy(df)

    if progress_cb:
        progress_cb(0.89, "Rendering power and energy charts")
    plot_results(df, out_prefix=output_base, annual_mode=annual_mode)
    if annual_mode:
        if progress_cb:
            progress_cb(0.93, "Rendering monthly energy chart")
        plot_monthly_energy(df, out_prefix=output_base)

    meta = {
        "script": "sbe_pv_model.py",
        "version": __version__,
        "run_timestamp_utc": pd.Timestamp.now(tz="UTC").isoformat(),
        "input_csv": input_csv,
        "input_kind": input_kind,
        "annual_mode": bool(annual_mode),
        "input_is_utc": bool(INPUT_IS_UTC),
        "local_timezone": str(df.index.tz),
        "dhi_source": dhi_source,
        "SolarEdge_inverter_eff": float(se_inv_eff),
        "SolarEdge_BOS_eff": float(se_bos_eff),
        "SolarEdge_total_eff": float(se_eff),
        "Solectria_inverter_eff": float(sol_inv_eff),
        "Solectria_BOS_eff": float(sol_bos_eff),
        "Solectria_total_eff": float(sol_eff),
        "IAM_enabled": True,
        "IAM_customized": bool(include_iam),
        "IAM_model": "martin_ruiz",
        "IAM_a_r": float(effective_iam_a_r),
        "LAT": LAT,
        "LON": LON,
        "AXIS_AZIMUTH": AXIS_AZIMUTH,
        "MAX_ANGLE": MAX_ANGLE,
        "GCR": GCR,
        "BACKTRACK": bool(backtrack),
        "curtailment_enabled": bool(active_curtailment_limit_kw is not None),
        "curtailment_limit_kw": (
            float(active_curtailment_limit_kw)
            if active_curtailment_limit_kw is not None
            else "N/A"
        ),
        "MODULES_PER_BAY": MODULES_PER_BAY,
        "SOLECTRIA_STRINGS": SOLECTRIA_STRINGS,
        "SOLECTRIA_BAYS_PER_STRING": SOLECTRIA_BAYS_PER_STRING,
        "SOLAREDGE_STRINGS": SOLAREDGE_STRINGS,
        "SOLAREDGE_BAYS_PER_STRING": SOLAREDGE_BAYS_PER_STRING,
        "module_name": MODULE_NAME,
        "data_quality_warnings": " | ".join(data_quality_warnings) or "None",
    }
    if progress_cb:
        progress_cb(0.97, "Creating Excel workbook")
    write_excel(df, f"{output_base}.xlsx", meta, annual_mode=annual_mode)
    if progress_cb:
        progress_cb(1.0, "Model outputs ready")

    se_meas = float(df["se_measured_energy_kwh"].iloc[-1])
    se_pred = float(df["se_predicted_energy_kwh"].iloc[-1])
    sol_meas = float(df["sol_measured_energy_kwh"].iloc[-1])
    sol_pred = float(df["sol_predicted_energy_kwh"].iloc[-1])

    def _safe(x, ndigits=1):
        # JSON-safe: NaN/Inf -> None; else rounded float.
        try:
            xf = float(x)
        except (TypeError, ValueError):
            return None
        if not np.isfinite(xf):
            return None
        return round(xf, ndigits)

    def _pct(pred, meas):
        if not meas or not np.isfinite(meas):
            return None
        return _safe((pred - meas) / meas * 100.0, 2)

    predicted_difference = se_pred - sol_pred
    predicted_difference_pct = (
        predicted_difference / sol_pred * 100.0 if sol_pred else np.nan
    )

    return {
        "mode": "annual" if annual_mode else "validation",
        "se_measured_kwh": None if annual_mode else _safe(se_meas),
        "se_predicted_kwh": _safe(se_pred),
        "sol_measured_kwh": None if annual_mode else _safe(sol_meas),
        "sol_predicted_kwh": _safe(sol_pred),
        "se_pct": None if annual_mode else _pct(se_pred, se_meas),
        "sol_pct": None if annual_mode else _pct(sol_pred, sol_meas),
        "predicted_difference_kwh": _safe(predicted_difference),
        "predicted_difference_pct": _safe(predicted_difference_pct, 2),
        "dhi_source": dhi_source,
        "data_quality_warnings": data_quality_warnings,
        "backtrack": bool(backtrack),
        "solaredge_inverter_efficiency": _safe(se_inv_eff, 4),
        "solaredge_bos_efficiency": _safe(se_bos_eff, 4),
        "solaredge_total_efficiency": _safe(se_eff, 4),
        "solectria_inverter_efficiency": _safe(sol_inv_eff, 4),
        "solectria_bos_efficiency": _safe(sol_bos_eff, 4),
        "solectria_total_efficiency": _safe(sol_eff, 4),
        "include_iam": True,
        "iam_customized": bool(include_iam),
        "iam_model": "martin_ruiz",
        "iam_a_r": _safe(effective_iam_a_r, 4),
        "curtailment_enabled": bool(active_curtailment_limit_kw is not None),
        "curtailment_limit_kw": (
            _safe(active_curtailment_limit_kw, 3)
            if active_curtailment_limit_kw is not None
            else None
        ),
        "n_rows": int(len(df)),
        "ac_png": f"{output_base}_ac_power.png",
        "energy_png": f"{output_base}_cumulative_energy.png",
        "monthly_png": (
            f"{output_base}_monthly_energy.png" if annual_mode else None
        ),
        "excel": f"{output_base}.xlsx",
    }


def main() -> None:
    print(f"sbe_pv_model.py (v{__version__}) — input: {INPUT_CSV}")
    stats = run_model(INPUT_CSV, OUTPUT_BASE)
    print(f"Wrote: {stats['excel']}, {stats['ac_png']}, {stats['energy_png']}")
    print("End-of-period energy (kWh):")
    print(f"  SolarEdge  measured={stats['se_measured_kwh']:,.2f}  predicted={stats['se_predicted_kwh']:,.2f}")
    print(f"  Solectria  measured={stats['sol_measured_kwh']:,.2f}  predicted={stats['sol_predicted_kwh']:,.2f}")


if __name__ == "__main__":
    main()
