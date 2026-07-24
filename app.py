"""
================================================================================
Shannon Tidal Resource Explorer — STREAMLIT APP (Tier 1)
================================================================================
Loads tool/data/shannon_grid.parquet (built once via tool/build_data.py)
and provides an interactive map of the Shannon Estuary tidal-current
resource for 15 turbine configurations (5 diameters × 3 rated velocities).

Run locally:
    pip install -r tool/requirements.txt
    python tool/build_data.py        # one-time, ~30 s
    streamlit run tool/app.py        # opens at http://localhost:8501

Author: Alireza
Date: 2026-04-30
================================================================================
"""

import json
import os

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# Optional: enables click-to-inspect on the map. If not installed, the app
# falls back to typed (i, j) input only.
try:
    from streamlit_plotly_events import plotly_events
    HAS_PLOTLY_EVENTS = True
except ImportError:
    HAS_PLOTLY_EVENTS = False

# --------------------------------------------------------------------------
# PATHS
# --------------------------------------------------------------------------
TOOL_DIR    = os.path.dirname(os.path.abspath(__file__))
DATA_FILE   = os.path.join(TOOL_DIR, "data", "shannon_grid.parquet")
META_FILE   = os.path.join(TOOL_DIR, "data", "metadata.json")
DIST_FILE   = os.path.join(TOOL_DIR, "data", "shannon_distributions.npz")


# --------------------------------------------------------------------------
# PAGE CONFIG
# --------------------------------------------------------------------------
st.set_page_config(
    page_title="Shannon Tidal Resource Explorer",
    page_icon="🌊",
    layout="wide",
    initial_sidebar_state="expanded",
)


# --------------------------------------------------------------------------
# DATA LOADING (cached so reruns are instant)
# --------------------------------------------------------------------------
@st.cache_data(show_spinner="Loading Shannon grid…")
def load_data():
    if not os.path.exists(DATA_FILE):
        return None, None
    df = pd.read_parquet(DATA_FILE)
    with open(META_FILE, "r") as f:
        meta = json.load(f)
    return df, meta


df, meta = load_data()

if df is None:
    st.error(
        f"Data file not found: `{DATA_FILE}`\n\n"
        f"Run the data preparation script first:\n\n"
        f"```\npython tool/build_data.py\n```"
    )
    st.stop()


IMAX = meta["imax"]
JMAX = meta["jmax"]
CELL_AREA_KM2 = meta["cell_area_km2"]
CONFIGS_AVAIL = meta["configs"]    # list of dicts
ALL_LABELS = [c["label"] for c in CONFIGS_AVAIL]


# --------------------------------------------------------------------------
# SPEED-DISTRIBUTION LAYER  (optional — enables the custom-turbine panel)
# --------------------------------------------------------------------------
# Built by tool/build_distributions.py. Holds an annual speed-duration curve
# per estuary cell plus the water-depth field, which together let the app
# evaluate a turbine that was not part of the 15-configuration design grid.
#
# The depth and velocity criteria read the depth and peak-speed fields
# directly. Energy and capacity factor integrate the user's power curve
# against the cell's speed-duration curve.
#
# If the file is absent the app behaves exactly as before and the panel is
# simply not offered.
@st.cache_data(show_spinner="Loading speed distributions…")
def load_distributions():
    if not os.path.exists(DIST_FILE):
        return None
    z = np.load(DIST_FILE)
    return {k: z[k] for k in z.files}


DIST = load_distributions()
HAS_CUSTOM = DIST is not None

# Flat grid index -> row in the distribution arrays (-1 where absent).
if HAS_CUSTOM:
    DIST_ROW = np.full(IMAX * JMAX, -1, dtype=np.int32)
    DIST_ROW[DIST["cell"]] = np.arange(len(DIST["cell"]), dtype=np.int32)

RHO_SEAWATER = meta.get("rho", 1025.0)

# Gauss-Legendre nodes for integrating a power curve across a speed bin. The
# curve is strongly convex below rated and has hard kinks at cut-in, rated and
# cut-out, so the bin MEAN matters — evaluating at the midpoint biases energy.
_GL_X, _GL_W = np.polynomial.legendre.leggauss(8)


def analytic_curve(D, Vr, cutin, cp, cutout=None):
    """Standard cubic-to-rated curve, P in kW (Lewis et al. 2021, Eq. 3)."""
    k = 0.5 * cp * RHO_SEAWATER * (np.pi * D ** 2 / 4.0) / 1000.0

    def P(v):
        v = np.asarray(v, dtype=float)
        out = np.where(v < cutin, 0.0, k * np.minimum(v, Vr) ** 3)
        if cutout is not None:
            out = np.where(v > cutout, 0.0, out)
        return out

    P.rated_kW = k * Vr ** 3
    return P


def curve_bin_weights(P, edges):
    """Mean power (kW) in each speed bin, assuming uniform density within it."""
    lo, hi = edges[:-1], edges[1:]
    mid, half = 0.5 * (lo + hi), 0.5 * (hi - lo)
    nodes = mid[:, None] + half[:, None] * _GL_X[None, :]
    return 0.5 * (P(nodes.ravel()).reshape(nodes.shape) * _GL_W[None, :]).sum(axis=1)


def min_depth_for(D, clearance):
    """
    Paper Eq. 5 / Eq. 6, solved for the self-referential bottom clearance:

        hmin = c + D + max(0.25 hmin, c)  ->  max(D + 2c, (D + c) / 0.75)

    With c = 5 m this returns 13 / 15 / 20 / 26.67 / 33.33 m for
    D = 3 / 5 / 10 / 15 / 20 m — the thresholds used for the published runs.
    """
    return max(D + 2.0 * clearance, (D + clearance) / 0.75)

# Detect whether parquet contains rEMEC columns (sensitivity criterion).
# If not, the criterion toggle is hidden and the app forces bEMEC.
HAS_REMEC = "rEMEC" in meta.get("criteria_available", ["bEMEC"])


# --------------------------------------------------------------------------
# URL STATE SHARING — read query params on load, sync session_state back
# at the end of the script. Pattern: URL → session_state (first load only)
# → widgets (via key=) → user changes → session_state → URL.
# --------------------------------------------------------------------------
qp = st.query_params

def _qp_bool(key, default):
    v = qp.get(key)
    if v is None: return default
    return str(v).lower() in ("1", "true", "yes")

def _qp_int(key, default):
    try: return int(qp.get(key, default))
    except (TypeError, ValueError): return default

# Map between full radio labels (what the widget expects) and short URL codes
FIELD_TO_CODE = {
    "Annual energy per turbine (MWh/yr)": "energy",
    "Capacity factor (%)":                "cf",
    "Peak velocity (m/s)":                "vel",
}
CODE_TO_FIELD = {v: k for k, v in FIELD_TO_CODE.items()}

# First-load-only seeding of session_state from URL (or defaults)
if "selected_set" not in st.session_state:
    seeded = qp.get("set", "Set01")
    st.session_state["selected_set"] = seeded if seeded in ALL_LABELS else "Set01"
if "field_choice" not in st.session_state:
    st.session_state["field_choice"] = CODE_TO_FIELD.get(
        qp.get("field", "energy"), "Annual energy per turbine (MWh/yr)"
    )
if "highlight_top" not in st.session_state:
    st.session_state["highlight_top"] = _qp_bool("top", False)
if "exclude_shipping" not in st.session_state:
    st.session_state["exclude_shipping"] = _qp_bool("excl_ship", False)
if "sites_only" not in st.session_state:
    st.session_state["sites_only"] = _qp_bool("sites_only", False)
if "viable_only" not in st.session_state:
    st.session_state["viable_only"] = _qp_bool("viable_only", False)
if "compare_mode" not in st.session_state:
    st.session_state["compare_mode"] = _qp_bool("cmp", False)
if "selected_set_b" not in st.session_state:
    seeded_b = qp.get("setB", "Set12")
    st.session_state["selected_set_b"] = seeded_b if seeded_b in ALL_LABELS else "Set12"
if "cmp_view" not in st.session_state:
    cmp_default = qp.get("cmpmode", "sbs")
    st.session_state["cmp_view"] = (
        "Side-by-side" if cmp_default == "sbs" else "Difference (B − A)"
    )
if "criterion" not in st.session_state:
    crit_default = qp.get("crit", "b").lower()
    st.session_state["criterion"] = "rEMEC" if crit_default == "r" else "bEMEC"


# --------------------------------------------------------------------------
# SIDEBAR — TURBINE SELECTOR + LAYER TOGGLES
# --------------------------------------------------------------------------
st.sidebar.title("Shannon Tidal Resource Explorer")
st.sidebar.caption("Tier 2  |  DIVAST 2D model output")

# --- turbine selector ----
st.sidebar.subheader("1. Turbine configuration")

def _fmt_set(lbl):
    c = next(c for c in CONFIGS_AVAIL if c["label"] == lbl)
    return f"{c['label']}  —  D = {c['D_m']} m,  Vr = {c['Vr_mps']} m/s"

selected_label = st.sidebar.selectbox(
    "Select a turbine",
    ALL_LABELS,
    format_func=_fmt_set,
    key="selected_set",
)
cfg = next(c for c in CONFIGS_AVAIL if c["label"] == selected_label)
LABEL = cfg["label"]

# --- custom turbine (NEW) ----
# Specify any machine, not just the fifteen that were simulated. Energy and
# capacity factor come from the reconstructed speed-duration curve at each
# cell; viability comes from the exact depth and velocity criteria.
CUSTOM_ON = False
CUSTOM = {}
if HAS_CUSTOM:
    CUSTOM_ON = st.sidebar.checkbox(
        "Define my own turbine",
        key="custom_on",
        help=(
            "Replaces the selected configuration with a turbine of your own. "
            "Every map, metric and export below then describes YOUR machine.\n\n"
            "**Note to developer — accuracy.** Energy and capacity factor are "
            "within about 1 % (median cell error) for rated velocities of "
            "1.0–2.5 m/s with a cut-in of 0.45–0.75 m/s. Above 2.5 m/s the "
            "90th-percentile cell error rises to roughly 10 %; below a 0.45 m/s "
            "cut-in the speed distribution is unconstrained and error is not "
            "characterised. Rotor diameter is exact at any value."
        ),
    )
    if CUSTOM_ON:
        with st.sidebar.expander("Turbine specification", expanded=True):
            c_D = st.slider("Rotor diameter D (m)", 2.0, 25.0, 12.0, 0.5,
                            key="c_D",
                            help="Sets swept area and, through the clearance "
                                 "rule, the minimum water depth.")
            c_Vr = st.slider("Rated velocity Vr (m/s)", 0.8, 3.0, 1.80, 0.05,
                             key="c_Vr")
            c_auto = st.checkbox("Cut-in = 0.30 Vr", True, key="c_auto",
                                 help="The Lewis et al. (2021) convention used "
                                      "for the fifteen simulated designs.")
            if c_auto:
                c_cut = 0.30 * c_Vr
                st.caption(f"Cut-in Vc = **{c_cut:.2f} m/s**")
            else:
                c_cut = st.slider("Cut-in Vc (m/s)", 0.10,
                                  float(max(0.15, min(1.50, c_Vr - 0.05))),
                                  float(min(0.60, c_Vr - 0.05)), 0.05,
                                  key="c_cut")
            c_cp = st.slider("Power coefficient Cp", 0.25, 0.50, 0.40, 0.01,
                             key="c_cp",
                             help="0.40 was used for the published runs; the "
                                  "14-device mean in Lewis et al. (2021) is 0.37.")
            c_useco = st.checkbox("Apply a cut-out speed", False, key="c_useco")
            c_co = (st.slider("Cut-out (m/s)", float(c_Vr), 3.0,
                              float(min(3.0, c_Vr + 0.5)), 0.05, key="c_co")
                    if c_useco else None)

            c_clr_mode = st.radio(
                "Installation clearance",
                ["EMEC 5 m (Eq. 5)", "Relaxed 4 m (Eq. 6)", "Custom"],
                key="c_clrmode",
                help="Top clearance c below LAT, bottom clearance the greater "
                     "of c and 25 % of depth, giving "
                     "hmin = max(D + 2c, (D + c) / 0.75).",
            )
            c_clr = (5.0 if c_clr_mode.startswith("EMEC")
                     else 4.0 if c_clr_mode.startswith("Relaxed")
                     else st.slider("Clearance c (m)", 1.0, 8.0, 5.0, 0.5,
                                    key="c_clr"))

            _P = analytic_curve(c_D, c_Vr, c_cut, c_cp, c_co)
            _hmin = min_depth_for(c_D, c_clr)
            st.markdown(
                f"**Rated power** {_P.rated_kW:,.0f} kW &nbsp;·&nbsp; "
                f"**swept area** {np.pi * c_D ** 2 / 4:,.0f} m² &nbsp;·&nbsp; "
                f"**min depth** {_hmin:.1f} m LAT"
            )
            CUSTOM = dict(D=c_D, Vr=c_Vr, cutin=c_cut, cp=c_cp, cutout=c_co,
                          clearance=c_clr, P=_P, hmin=_hmin)

# --- compare mode (NEW) ----
if CUSTOM_ON:
    st.session_state["compare_mode"] = False
compare_mode = False if CUSTOM_ON else st.sidebar.checkbox(
    "Compare with another turbine",
    key="compare_mode",
    help=(
        "Show a second turbine alongside the primary one (side-by-side), "
        "OR a difference map (B − A) using a diverging colormap. "
        "Cell inspector, threshold curve, comparison table and CSV export "
        "below stay tied to the primary turbine (A)."
    ),
)
if compare_mode:
    selected_label_b = st.sidebar.selectbox(
        "Compare against (Turbine B):",
        ALL_LABELS,
        format_func=_fmt_set,
        key="selected_set_b",
    )
    cmp_view = st.sidebar.radio(
        "View:",
        ["Side-by-side", "Difference (B − A)"],
        key="cmp_view",
        horizontal=True,
    )
    cfg_b = next(c for c in CONFIGS_AVAIL if c["label"] == selected_label_b)
    LABEL_B = cfg_b["label"]
else:
    cfg_b = None
    LABEL_B = None
    cmp_view = None

# --- depth criterion (NEW for §4.6 sensitivity) ----
if HAS_REMEC:
    criterion = st.sidebar.radio(
        "Depth criterion:",
        ["bEMEC (primary, §§4.1–4.5)", "rEMEC (relaxed, §4.6 sensitivity)"],
        index=0 if st.session_state["criterion"] == "bEMEC" else 1,
        key="criterion_label",
        help=(
            "**bEMEC** is the EMEC-baseline depth criterion adopted for the "
            "headline §§4.1–4.5 results. **rEMEC** is the relaxed variant "
            "obtained by reducing the per-rotor depth threshold by 2.5 m "
            "(see §4.6 of the paper). Switching this changes which set of "
            "viability/energy/CF columns is read from the parquet."
        ),
    )
    st.session_state["criterion"] = (
        "bEMEC" if criterion.startswith("bEMEC") else "rEMEC"
    )

CRITERION = st.session_state["criterion"]
SUFFIX = "" if CRITERION == "bEMEC" else "_rEMEC"

# --- evaluate the custom turbine (NEW) --------------------------------------
# Three columns are written under the fixed name "CUSTOM", and LABEL is
# repointed at them. Every downstream code path builds its column names from
# LABEL + SUFFIX, so the maps, metrics, inspector, threshold curve and CSV
# export all pick up the custom machine with no further changes.
#
# Note the columns are attached to the cached DataFrame. The names are fixed,
# so a rerun overwrites rather than accumulating.
if CUSTOM_ON:
    T_SIM = float(DIST["T"])            # 8,928 h — the DIVAST accumulation
                                        # period, so custom numbers are
                                        # directly comparable with the
                                        # published columns
    mean_kW = DIST["phi"].astype(np.float32) @ curve_bin_weights(
        CUSTOM["P"], DIST["edges"].astype(np.float64))

    # Paper Eq. 4. Exact — neither term goes through the reconstruction.
    viable_cells = ((DIST["vmax"] >= CUSTOM["cutin"]) &
                    (DIST["h_lat"] >= CUSTOM["hmin"]))

    energy_mwh = np.where(viable_cells, mean_kW * T_SIM / 1000.0, 0.0)
    cf_pct = np.where(viable_cells,
                      mean_kW / max(CUSTOM["P"].rated_kW, 1e-9) * 100.0, 0.0)

    _n = len(df)
    _e = np.zeros(_n, np.float32)
    _c = np.zeros(_n, np.float32)
    _v = np.zeros(_n, bool)
    _idx = DIST["cell"]
    _e[_idx], _c[_idx], _v[_idx] = energy_mwh, cf_pct, viable_cells
    df["CUSTOM_energy_mwh"] = _e
    df["CUSTOM_cf_pct"] = _c
    df["CUSTOM_viable"] = _v

    LABEL = "CUSTOM"
    SUFFIX = ""
    # compute_display_grid() and the export build column names from
    # cfg["label"], so it must be the column stem, not a pretty name.
    cfg = {"label": "CUSTOM", "display": "Custom turbine", "D_m": CUSTOM["D"],
           "Vr_mps": CUSTOM["Vr"], "Pr_kW": CUSTOM["P"].rated_kW}

# --- field to display on map ----
st.sidebar.subheader("2. Map field")
field_choice = st.sidebar.radio(
    "Show on map:",
    list(FIELD_TO_CODE.keys()),
    key="field_choice",
)
TOP_N = 10
highlight_top = st.sidebar.checkbox(
    f"Highlight top {TOP_N} cells",
    key="highlight_top",
    help=(
        f"Draws a red outline around the {TOP_N} cells with the highest "
        "value in the currently-selected field, within the visible "
        "(filtered) region. Useful for 'where would you actually put a "
        "turbine?'"
    ),
)

# --- spatial filters ----
# Estuary mask is ALWAYS applied — it's the analysis frame, not optional.
# Anchorage exclusion removed as redundant with shipping exclusion.
st.sidebar.subheader("3. Spatial filters")
st.sidebar.caption("Estuary mask is always applied.")
exclude_shipping  = st.sidebar.checkbox("Exclude shipping lane", key="exclude_shipping")
sites_only        = st.sidebar.checkbox("Strategic sites only (Q/R/S/T)", key="sites_only")
viable_only       = st.sidebar.checkbox(
    f"Class 3 viable cells only ({LABEL})", key="viable_only",
)

# --- about / metadata ----
st.sidebar.subheader("4. About")
with st.sidebar.expander("Build info"):
    st.write(f"**Built:** `{meta['build_timestamp_utc']}`")
    st.write(f"**Grid:** {IMAX} × {JMAX}  ({IMAX*JMAX:,} cells)")
    st.write(f"**Cell area:** {CELL_AREA_KM2:.4f} km²")
    st.write(f"**Estuary cells:** {meta['estuary_cells']:,}  "
             f"({meta['estuary_cells'] * CELL_AREA_KM2:.0f} km²)")
    st.write(f"**Configs loaded:** {len(CONFIGS_AVAIL)}")
    st.write(f"**Cp:** {meta['cp']}  |  **ρ:** {meta['rho']} kg/m³")

# Export section (5.) is rendered later in the script after `keep` + `LABEL`
# are computed; Streamlit places it in the sidebar regardless of call order.


# --------------------------------------------------------------------------
# COMPUTE THE MASKED 2-D GRID FOR THE MAP
# --------------------------------------------------------------------------
def compute_display_grid(df, cfg, field_choice, masks):
    """Returns (data_grid 2-D, title, hover-fmt, colorscale, zmin, zmax)."""
    label = cfg["label"]

    if field_choice.startswith("Annual energy"):
        col = f"{label}_energy_mwh{SUFFIX}"
        title = "Annual energy (MWh/yr)"
        cmap = "Viridis"
        hover_fmt = ":.1f"
    elif field_choice.startswith("Capacity factor"):
        col = f"{label}_cf_pct{SUFFIX}"
        title = "Capacity factor (%)"
        cmap = "Plasma"
        hover_fmt = ":.1f"
    else:  # Peak velocity
        col = "peak_vel_mps"
        title = "Peak velocity (m/s)"
        cmap = "Turbo"
        hover_fmt = ":.2f"

    values = df[col].values.astype(np.float32)

    # Apply filter: cells outside become NaN (transparent over the land/water
    # underlay)
    masked = np.where(masks, values, np.nan).reshape(IMAX, JMAX)

    # NOTE: NO row flip. DIVAST row 0 is already north — Plotly's
    # yaxis.autorange='reversed' will place row 0 at the top of the plot.
    # (This matches Final_Results figure_1 which uses imshow origin='lower'
    # with a manual flip, equivalent to "row 0 at top" in screen space.)

    finite = masked[np.isfinite(masked)]
    if finite.size:
        zmin = float(np.nanmin(finite))
        zmax = float(np.nanmax(finite))
        if zmax == zmin:
            zmax = zmin + 1.0
    else:
        zmin, zmax = 0.0, 1.0

    return masked, title, hover_fmt, cmap, zmin, zmax


@st.cache_data
def precompute_land_grid(df_index_signature):
    """Land grid (brown) — water cells = NaN so the sea-blue plot bg shows
    through. Cached so we don't rebuild it on every rerun."""
    if "is_water" not in df.columns:
        return None
    is_land_2d = (~df["is_water"].values.astype(bool)).reshape(IMAX, JMAX)
    grid = np.where(is_land_2d, 1.0, np.nan).astype(np.float32)
    return grid


LAND_GRID = precompute_land_grid(len(df))    # signature arg just for cache key


# --------------------------------------------------------------------------
# CELL-INSPECTOR session state — initialised once. Priority order:
#   1. URL params ?i=…&j=… (if both valid)
#   2. Highest-peak-velocity cell in the estuary (fallback)
# The number_input widgets below the map write to these keys via
# Streamlit's `key=` parameter, which is read back here on the next run.
# --------------------------------------------------------------------------
if "inspect_i" not in st.session_state:
    qp_i = _qp_int("i", -1)
    qp_j = _qp_int("j", -1)
    if 0 <= qp_i < IMAX and 0 <= qp_j < JMAX:
        st.session_state["inspect_i"] = qp_i
        st.session_state["inspect_j"] = qp_j
    else:
        # Fallback: highest-velocity estuary cell
        _pv_in_est = np.where(
            df["in_estuary"].values, df["peak_vel_mps"].values, -1.0,
        )
        _best_idx = int(np.argmax(_pv_in_est))
        st.session_state["inspect_i"] = int(df.iloc[_best_idx]["i"])
        st.session_state["inspect_j"] = int(df.iloc[_best_idx]["j"])

inspect_i = int(st.session_state["inspect_i"])
inspect_j = int(st.session_state["inspect_j"])


# Build the boolean keep-mask. Estuary mask is ALWAYS applied.
keep = df["in_estuary"].values.copy()
if exclude_shipping:
    keep &= ~df["in_shipping"].values
if sites_only:
    keep &= df["in_any_site"].values
if viable_only:
    keep &= df[f"{LABEL}_viable{SUFFIX}"].values.astype(bool)

grid, fld_title, hover_fmt, cmap, zmin, zmax = compute_display_grid(
    df, cfg, field_choice, keep,
)


# --------------------------------------------------------------------------
# HEADER + SUMMARY METRICS
# --------------------------------------------------------------------------
st.title("Shannon Tidal Resource Explorer")
if CUSTOM_ON:
    _co = f" · cut-out **{CUSTOM['cutout']:.2f} m/s**" if CUSTOM["cutout"] else ""
    st.markdown(
        f"**Custom turbine** · D = **{cfg['D_m']:g} m** · "
        f"Vr = **{cfg['Vr_mps']:.2f} m/s** · "
        f"cut-in **{CUSTOM['cutin']:.2f} m/s** · "
        f"Cp = **{CUSTOM['cp']:.2f}** · "
        f"Rated power = **{cfg['Pr_kW']:,.0f} kW**{_co} · "
        f"clearance **{CUSTOM['clearance']:g} m** "
        f"(min depth {CUSTOM['hmin']:.1f} m LAT)"
    )
    _warn = []
    if not (1.0 <= CUSTOM["Vr"] <= 2.5):
        _warn.append(f"a rated velocity of {CUSTOM['Vr']:.2f} m/s sits outside "
                     f"the 1.0–2.5 m/s range this tool is calibrated over")
    if CUSTOM["cutin"] < 0.45:
        _warn.append(f"a cut-in of {CUSTOM['cutin']:.2f} m/s is below 0.45 m/s, "
                     f"the lowest speed the underlying data constrains")
    if _warn:
        st.warning("Energy and capacity factor are less reliable here: "
                   + "; ".join(_warn) + ".")
else:
    _crit_tag = ("**bEMEC** (primary)" if CRITERION == "bEMEC"
                 else "**rEMEC** (relaxed, §4.6)")
    st.markdown(
        f"**{LABEL}** · D = **{cfg['D_m']} m** · "
        f"Vr = **{cfg['Vr_mps']} m/s** · "
        f"Rated power = **{cfg['Pr_kW']:.1f} kW** · "
        f"Criterion = {_crit_tag}"
    )

# Stats over visible cells
visible = df[keep]
n_visible = len(visible)

# Derived metrics for THIS config in the visible region
viable_mask = visible[f"{LABEL}_viable{SUFFIX}"].values.astype(bool)
n_class3 = int(viable_mask.sum())
area_class3_km2 = n_class3 * CELL_AREA_KM2
energy_arr = visible[f"{LABEL}_energy_mwh{SUFFIX}"].values
cf_arr     = visible[f"{LABEL}_cf_pct{SUFFIX}"].values
mean_energy = float(np.nanmean(energy_arr[viable_mask])) if n_class3 else 0.0
total_energy_gwh = float(np.nansum(energy_arr[viable_mask]) / 1000.0)
mean_cf    = float(np.nanmean(cf_arr[viable_mask])) if n_class3 else 0.0

c1, c2, c3, c4 = st.columns(4)
c1.metric(
    "Class 3 viable cells",
    f"{n_class3:,}",
    help=(
        "Number of cells in the visible region where BOTH the depth and "
        "velocity criteria are met for this turbine (D, Vᵣ)."
    ),
)
c2.metric(
    "Viable area",
    f"{area_class3_km2:.1f} km²",
    help=(
        "Class 3 cell count × 0.0357 km² per cell "
        "(189 m × 189 m DIVAST grid). "
        "This is the geographic footprint of viable cells — it does NOT "
        "account for wake spacing or realistic farm packing."
    ),
)
c3.metric(
    "Mean energy / turbine",
    f"{mean_energy:.1f} MWh/yr",
    help=(
        "Arithmetic mean of annual energy across Class 3 viable cells "
        "in the visible region.\n\n"
        "Reads as: 'one turbine of this (D, Vᵣ) deployed at the AVERAGE "
        "viable cell would generate this much per year.'\n\n"
        "Caveats:\n"
        "• Computed only over Class 3 cells (non-viable cells excluded — "
        "they would otherwise pull the mean down to ~zero).\n"
        "• Cell-level arithmetic mean; sensitive to a few high-velocity "
        "outlier cells in narrow channels.\n"
        "• Reflects one full year (365 days) of accumulated energy."
    ),
)
c4.metric(
    "Theoretical max (1 turbine/cell)",
    f"{total_energy_gwh:.1f} GWh/yr",
    help=(
        "Sum of annual energy across all Class 3 cells, ASSUMING ONE "
        "TURBINE per 189 m × 189 m cell.\n\n"
        "This is an UPPER-BOUND estimate. It does NOT include:\n"
        "• Farm-spacing constraints (real arrays use 5–10 rotor "
        "diameters between turbines)\n"
        "• Wake losses between adjacent turbines\n"
        "• Array efficiency factors\n\n"
        "Realistic deployment density depends on rotor diameter:\n"
        "• Small turbines (D = 3–5 m): real packing is much DENSER → "
        "true total could be higher\n"
        "• Large turbines (D = 15–20 m): real packing is comparable, "
        "but wakes still reduce yield\n\n"
        "Treat this number as a relative comparator across configs, "
        "not as an absolute resource estimate."
    ),
)


# --------------------------------------------------------------------------
# PLOTLY HEATMAP — layout constants apply to BOTH single-map and compare-mode
# branches, so they live OUTSIDE the if/else.
# --------------------------------------------------------------------------
FIG_HEIGHT       = 520
RIGHT_MARGIN     = 80     # reserves space for the colorbar (no title) +
                          # tick labels. With no field-name title, this is
                          # constant across all 3 fields.
LAND_COLOR       = "#8b6f47"   # darker, earthier brown
SEA_COLOR        = "#bcd6e6"   # light sea blue

if not compare_mode:
    st.subheader(f"{fld_title}  —  {LABEL}")

    fig = go.Figure()

    # Layer 1 — LAND (always visible, brown). Water cells are NaN so the sea-blue
    # plot background shows through.
    if LAND_GRID is not None:
        fig.add_trace(go.Heatmap(
            z=LAND_GRID,
            colorscale=[[0.0, LAND_COLOR], [1.0, LAND_COLOR]],
            showscale=False,
            hoverinfo="skip",
            zmin=0, zmax=1,
            zsmooth=False,
        ))

    # Layer 2 — DATA (filtered, with colorbar). NaN cells are transparent so the
    # land+sea underlay shows through wherever the filter excludes the cell.
    fig.add_trace(go.Heatmap(
        z=grid,
        colorscale=cmap,
        zmin=zmin, zmax=zmax,
        hoverongaps=False,
        connectgaps=False,
        zsmooth=False,
        colorbar=dict(
            # No title here — the subheader above the map already says
            # "{Field} — {Set##}". A title on the colorbar was the thing
            # making the layout shift between fields (different titles have
            # different widths, which pushed the plot area around).
            title=dict(text=""),
            tickfont=dict(color="black", size=10),
            thickness=14,
            len=0.85,
            x=1.01, xanchor="left",
            y=0.5,  yanchor="middle",
            outlinewidth=0,
        ),
        hovertemplate=(
            "i = %{y}, j = %{x}<br>"
            f"{fld_title}: %{{z:{hover_fmt[1:]}}}<extra></extra>"
        ),
    ))

    # Layer 3 — TOP-N highlight markers (red outlined circles), if enabled.
    if highlight_top:
        sort_col = (
            f"{LABEL}_energy_mwh{SUFFIX}" if field_choice.startswith("Annual energy") else
            f"{LABEL}_cf_pct{SUFFIX}"     if field_choice.startswith("Capacity factor") else
            "peak_vel_mps"
        )
        visible_only = df[keep].copy()
        if len(visible_only) >= 1:
            top_cells = visible_only.nlargest(TOP_N, sort_col)
            fig.add_trace(go.Scatter(
                x=top_cells["j"].values,
                y=top_cells["i"].values,
                mode="markers",
                marker=dict(
                    symbol="circle-open",
                    size=12,
                    color="rgba(220,40,40,1)",
                    line=dict(width=2.5, color="rgba(220,40,40,1)"),
                ),
                customdata=top_cells[sort_col].values,
                showlegend=False,
                hovertemplate=(
                    f"Top {TOP_N} cell<br>"
                    "i = %{y}, j = %{x}<br>"
                    f"{fld_title}: %{{customdata:{hover_fmt[1:]}}}<extra></extra>"
                ),
            ))

    # Layer 4 — INSPECT marker (white-rim X at the user-selected cell).
    fig.add_trace(go.Scatter(
        x=[inspect_j], y=[inspect_i],
        mode="markers",
        marker=dict(
            symbol="x",
            size=16,
            color="white",
            line=dict(width=3, color="black"),
        ),
        showlegend=False,
        hovertemplate=f"Inspect cell<br>i = {inspect_i}, j = {inspect_j}<extra></extra>",
    ))

    fig.update_layout(
        height=FIG_HEIGHT,
        autosize=True,                              # fill container width as before
        margin=dict(l=10, r=RIGHT_MARGIN, t=10, b=10),
        plot_bgcolor=SEA_COLOR,
        paper_bgcolor="white",
    )
    fig.update_xaxes(
        showgrid=False, showticklabels=False, zeroline=False,
        range=[0, JMAX - 1],          # FIXED data range — never auto-scales
        constrain="domain",
    )
    fig.update_yaxes(
        showgrid=False, showticklabels=False, zeroline=False,
        range=[IMAX - 1, 0],          # FIXED + reversed (high i at bottom = south at bottom)
        scaleanchor="x", scaleratio=1,
        constrain="domain",
    )

    if HAS_PLOTLY_EVENTS:
        # Click-to-inspect: any single-click on the map updates the inspector cell.
        # Width is left to streamlit-plotly-events' default (fills the container);
        # only height is pinned. The colorbar has no title (see above), so the
        # plot area is identical for every field regardless of width.
        selected = plotly_events(
            fig,
            click_event=True,
            hover_event=False,
            select_event=False,
            override_height=FIG_HEIGHT + 10,
            key="map_click",
        )
        if selected:
            pt = selected[0]
            try:
                new_j = int(round(float(pt.get("x"))))
                new_i = int(round(float(pt.get("y"))))
                new_i = max(0, min(IMAX - 1, new_i))
                new_j = max(0, min(JMAX - 1, new_j))
                if new_i != inspect_i or new_j != inspect_j:
                    st.session_state["inspect_i"] = new_i
                    st.session_state["inspect_j"] = new_j
                    st.rerun()
            except (TypeError, ValueError):
                pass    # ignore malformed click payloads
        st.caption(
            "💡 Click any cell on the map to load it into the Cell inspector below."
        )
    else:
        # Fallback: no click events. Container-filled width as before.
        st.plotly_chart(
            fig, use_container_width=True, config={"displaylogo": False},
        )
        st.caption(
            "💡 Tip: `pip install streamlit-plotly-events` to enable "
            "click-to-inspect on the map."
        )

else:
    # ----------------------------------------------------------------------
    # COMPARE MODE — side-by-side (two maps) OR difference map (B − A)
    # ----------------------------------------------------------------------
    grid_b, _, _, _, zmin_b, zmax_b = compute_display_grid(
        df, cfg_b, field_choice, keep,
    )

    st.subheader(
        f"Compare: {LABEL} (A) vs {LABEL_B} (B)  —  {fld_title}"
    )
    st.caption(
        f"**A:** {LABEL}  D = {cfg['D_m']} m, Vr = {cfg['Vr_mps']} m/s, "
        f"Pr = {cfg['Pr_kW']:.0f} kW        "
        f"**B:** {LABEL_B}  D = {cfg_b['D_m']} m, Vr = {cfg_b['Vr_mps']} m/s, "
        f"Pr = {cfg_b['Pr_kW']:.0f} kW"
    )

    if cmp_view == "Side-by-side":
        # Use a SHARED zmin/zmax across both maps so colours are comparable
        finite_a = grid[np.isfinite(grid)]
        finite_b = grid_b[np.isfinite(grid_b)]
        if finite_a.size and finite_b.size:
            z_lo = float(min(finite_a.min(), finite_b.min()))
            z_hi = float(max(finite_a.max(), finite_b.max()))
        else:
            z_lo, z_hi = 0.0, 1.0
        if z_hi == z_lo:
            z_hi = z_lo + 1.0

        col_a, col_b = st.columns(2, gap="small")
        for col, this_grid, this_label in [
            (col_a, grid,   f"{LABEL} (A)"),
            (col_b, grid_b, f"{LABEL_B} (B)"),
        ]:
            with col:
                st.markdown(f"**{this_label}**")
                fig = go.Figure()
                if LAND_GRID is not None:
                    fig.add_trace(go.Heatmap(
                        z=LAND_GRID,
                        colorscale=[[0.0, LAND_COLOR], [1.0, LAND_COLOR]],
                        showscale=False, hoverinfo="skip",
                        zmin=0, zmax=1, zsmooth=False,
                    ))
                fig.add_trace(go.Heatmap(
                    z=this_grid,
                    colorscale=cmap,
                    zmin=z_lo, zmax=z_hi,
                    hoverongaps=False, connectgaps=False, zsmooth=False,
                    colorbar=dict(
                        title=dict(text=""),
                        tickfont=dict(color="black", size=9),
                        thickness=12, len=0.85,
                        x=1.01, xanchor="left",
                        y=0.5,  yanchor="middle",
                        outlinewidth=0,
                    ),
                    hovertemplate=(
                        "i = %{y}, j = %{x}<br>"
                        f"{fld_title}: %{{z:{hover_fmt[1:]}}}<extra></extra>"
                    ),
                ))
                fig.update_layout(
                    height=FIG_HEIGHT,
                    autosize=True,
                    margin=dict(l=10, r=RIGHT_MARGIN, t=10, b=10),
                    plot_bgcolor=SEA_COLOR,
                    paper_bgcolor="white",
                )
                fig.update_xaxes(
                    showgrid=False, showticklabels=False, zeroline=False,
                    range=[0, JMAX - 1], constrain="domain",
                )
                fig.update_yaxes(
                    showgrid=False, showticklabels=False, zeroline=False,
                    range=[IMAX - 1, 0],
                    scaleanchor="x", scaleratio=1, constrain="domain",
                )
                st.plotly_chart(fig, use_container_width=True,
                                config={"displaylogo": False})

        st.caption(
            "💡 Both maps share the same colour scale for visual "
            "comparability. The cell inspector, threshold curve, comparison "
            "table, and CSV export below remain tied to Turbine A."
        )

    else:  # Difference (B − A)
        if field_choice.startswith("Peak"):
            st.info(
                "Peak velocity is set-independent — every cell shows zero "
                "difference. Switch the map field to Annual energy or "
                "Capacity factor to see meaningful differences between the "
                "two turbines."
            )
        diff_grid = grid_b - grid
        finite = diff_grid[np.isfinite(diff_grid)]
        abs_max = float(np.nanmax(np.abs(finite))) if finite.size else 1.0
        if abs_max == 0:
            abs_max = 1.0

        fig_diff = go.Figure()
        if LAND_GRID is not None:
            fig_diff.add_trace(go.Heatmap(
                z=LAND_GRID,
                colorscale=[[0.0, LAND_COLOR], [1.0, LAND_COLOR]],
                showscale=False, hoverinfo="skip",
                zmin=0, zmax=1, zsmooth=False,
            ))
        fig_diff.add_trace(go.Heatmap(
            z=diff_grid,
            colorscale="RdBu_r",
            zmin=-abs_max, zmax=abs_max, zmid=0,
            hoverongaps=False, connectgaps=False, zsmooth=False,
            colorbar=dict(
                title=dict(text=""),
                tickfont=dict(color="black", size=10),
                thickness=14, len=0.85,
                x=1.01, xanchor="left",
                y=0.5,  yanchor="middle",
                outlinewidth=0,
            ),
            hovertemplate=(
                "i = %{y}, j = %{x}<br>"
                f"Δ {fld_title}: %{{z:{hover_fmt[1:]}}}<extra></extra>"
            ),
        ))
        fig_diff.update_layout(
            height=FIG_HEIGHT,
            autosize=True,
            margin=dict(l=10, r=RIGHT_MARGIN, t=10, b=10),
            plot_bgcolor=SEA_COLOR,
            paper_bgcolor="white",
        )
        fig_diff.update_xaxes(
            showgrid=False, showticklabels=False, zeroline=False,
            range=[0, JMAX - 1], constrain="domain",
        )
        fig_diff.update_yaxes(
            showgrid=False, showticklabels=False, zeroline=False,
            range=[IMAX - 1, 0],
            scaleanchor="x", scaleratio=1, constrain="domain",
        )
        st.plotly_chart(fig_diff, use_container_width=True,
                        config={"displaylogo": False})
        st.caption(
            f"💡 Red = {LABEL_B} (B) higher than {LABEL} (A). "
            f"Blue = {LABEL_B} (B) lower. White = no difference. "
            f"Cells where one or both configs are non-viable, or that fall "
            f"outside the visible filter, appear as gaps."
        )



# --------------------------------------------------------------------------
# HISTOGRAM STRIP — distribution of the current field over visible cells
# --------------------------------------------------------------------------
hist_values = grid[np.isfinite(grid)]
if hist_values.size:
    hist_fig = go.Figure(go.Histogram(
        x=hist_values,
        nbinsx=40,
        marker=dict(color="#4575b4", line=dict(width=0)),
        showlegend=False,
        hovertemplate=f"{fld_title}: %{{x}}<br>Cells: %{{y}}<extra></extra>",
    ))
    hist_fig.update_layout(
        height=160,
        margin=dict(l=50, r=20, t=10, b=40),
        plot_bgcolor="white",
        bargap=0.05,
        xaxis_title=fld_title,
        yaxis_title="# of cells",
        font=dict(size=10),
    )
    hist_fig.update_xaxes(showgrid=True, gridcolor="#eeeeee")
    hist_fig.update_yaxes(showgrid=True, gridcolor="#eeeeee")
    st.plotly_chart(
        hist_fig, use_container_width=True, config={"displaylogo": False}
    )


# --------------------------------------------------------------------------
# CELL INSPECTOR — see all 15 configs at a single cell
# --------------------------------------------------------------------------
with st.expander(
    f"🔍  Cell inspector — see all {len(CONFIGS_AVAIL)} configs at one cell",
    expanded=False,
):
    ci_a, ci_b, ci_c = st.columns([1, 1, 3])
    with ci_a:
        st.number_input("Row (i)", min_value=0, max_value=IMAX - 1,
                        step=1, key="inspect_i")
    with ci_b:
        st.number_input("Col (j)", min_value=0, max_value=JMAX - 1,
                        step=1, key="inspect_j")
    with ci_c:
        st.caption(
            "Hover any cell on the map to read its (i, j), then type those "
            "here to inspect that cell across every turbine. Default = the "
            "highest-peak-velocity cell in the estuary."
        )

    cell_match = df[(df["i"] == inspect_i) & (df["j"] == inspect_j)]
    if cell_match.empty:
        st.warning(f"No cell at (i={inspect_i}, j={inspect_j}).")
    else:
        cell = cell_match.iloc[0]
        ctx = st.columns(4)
        ctx[0].metric("Peak velocity",        f"{cell['peak_vel_mps']:.2f} m/s")
        ctx[1].metric("Avg power density",     f"{cell['avg_pd_kwm2']:.2f} kW/m²")
        ctx[2].metric("In estuary",            "Yes" if cell["in_estuary"] else "No")
        ctx[3].metric("In shipping lane",      "Yes" if cell["in_shipping"] else "No")

        # ----- speed-duration curve at this cell (NEW) --------------------
        # How long the cell spends at each speed over the year, rather than
        # just its peak. Shown only in custom-turbine mode, so the default
        # view is unchanged.
        if CUSTOM_ON:
            _row = int(DIST_ROW[inspect_i * JMAX + inspect_j])
            if _row >= 0 and DIST["phi"][_row].sum() > 0:
                _phi = DIST["phi"][_row].astype(np.float64)
                _edges = DIST["edges"].astype(np.float64)
                _exc = np.clip(np.concatenate([[1.0], 1.0 - np.cumsum(_phi)]),
                               0.0, 1.0)
                _hrs = _exc * float(DIST["T"])

                dc = go.Figure()
                dc.add_trace(go.Scatter(
                    x=_edges, y=_hrs, mode="lines", fill="tozeroy",
                    line=dict(color="#1565A0", width=2),
                    fillcolor="rgba(21,101,160,0.15)", showlegend=False,
                    hovertemplate="Speed ≥ %{x:.2f} m/s<br>"
                                  "%{y:,.0f} h/yr<extra></extra>",
                ))
                for _nm, _v, _col in [("cut-in", CUSTOM["cutin"], "#2a9d8f"),
                                      ("rated", CUSTOM["Vr"], "#d1495b")]:
                    dc.add_vline(x=_v, line=dict(color=_col, dash="dash", width=1.5),
                                 annotation_text=_nm, annotation_position="top")
                dc.update_layout(
                    height=240, margin=dict(l=60, r=20, t=24, b=40),
                    plot_bgcolor="white", font=dict(size=10),
                    xaxis_title="Current speed (m/s)",
                    yaxis_title="Hours per year at or above",
                )
                dc.update_xaxes(showgrid=True, gridcolor="#eeeeee",
                                range=[0, float(cell["peak_vel_mps"]) * 1.05 or 1])
                dc.update_yaxes(showgrid=True, gridcolor="#eeeeee")
                st.markdown("**Speed-duration curve at this cell**")
                st.plotly_chart(dc, use_container_width=True,
                                config={"displaylogo": False})
                _q = [np.interp(f, _exc[::-1], _edges[::-1])
                      for f in (0.5, 0.25, 0.10)]
                st.caption(
                    f"Exceeded 50 % of the year: **{_q[0]:.2f} m/s** · "
                    f"25 %: **{_q[1]:.2f} m/s** · 10 %: **{_q[2]:.2f} m/s**."
                )

        # ----- Best config at this cell (per-cell argmax over 15 configs) -----
        # Honours the selected criterion (bEMEC or rEMEC).
        viable_configs = [
            c for c in CONFIGS_AVAIL
            if cell[f"{c['label']}_viable{SUFFIX}"]
        ]
        if viable_configs:
            best_e = max(
                viable_configs,
                key=lambda c: float(cell[f"{c['label']}_energy_mwh{SUFFIX}"]),
            )
            best_cf = max(
                viable_configs,
                key=lambda c: float(cell[f"{c['label']}_cf_pct{SUFFIX}"]),
            )
            e_val  = float(cell[f"{best_e['label']}_energy_mwh{SUFFIX}"])
            cf_val = float(cell[f"{best_cf['label']}_cf_pct{SUFFIX}"])

            bs1, bs2 = st.columns(2)
            bs1.success(
                f"🏆 **Best by energy: {best_e['label']}**  \n"
                f"D = {best_e['D_m']} m, Vr = {best_e['Vr_mps']} m/s  \n"
                f"**{e_val:,.1f} MWh/yr**"
            )
            bs2.success(
                f"🏆 **Best by CF: {best_cf['label']}**  \n"
                f"D = {best_cf['D_m']} m, Vr = {best_cf['Vr_mps']} m/s  \n"
                f"**{cf_val:.2f} %**"
            )
        else:
            st.warning(
                f"No turbine in the 15-config grid is Class 3 viable at "
                f"cell (i={inspect_i}, j={inspect_j}) under the {CRITERION} "
                f"criterion. Try a cell deeper in the central narrows, or "
                f"switch the criterion."
            )

        rows = []
        for c in CONFIGS_AVAIL:
            rows.append({
                "Set":       c["label"],
                "D (m)":     c["D_m"],
                "Vᵣ (m/s)": c["Vr_mps"],
                "Pᵣ (kW)":  c["Pr_kW"],
                "Class 3 viable": "✓" if cell[f"{c['label']}_viable{SUFFIX}"] else "—",
                "Annual energy (MWh/yr)": round(float(cell[f"{c['label']}_energy_mwh{SUFFIX}"]), 1),
                "Capacity factor (%)":    round(float(cell[f"{c['label']}_cf_pct{SUFFIX}"]), 2),
            })
        st.dataframe(
            pd.DataFrame(rows),
            hide_index=True,
            use_container_width=True,
        )


# --------------------------------------------------------------------------
# CUMULATIVE AREA vs THRESHOLD CURVE
# --------------------------------------------------------------------------
with st.expander(
    "📈  Cumulative area vs. threshold curve",
    expanded=False,
):
    th_field = st.radio(
        "Threshold on:",
        ["Peak velocity (m/s)", "Annual energy (MWh/yr)", "Capacity factor (%)"],
        horizontal=True,
        key="th_field",
    )

    # All curves are computed over the ESTUARY (the natural denominator).
    estuary_only_arr = df["in_estuary"].values
    if th_field.startswith("Peak"):
        th_values = df["peak_vel_mps"].values[estuary_only_arr]
        th_unit, th_max = "m/s", 3.0
        th_step, th_default = 0.05, 1.5
    elif th_field.startswith("Annual"):
        th_values = df[f"{LABEL}_energy_mwh{SUFFIX}"].values[estuary_only_arr]
        th_max = max(float(np.max(th_values)), 1.0)
        th_unit, th_step, th_default = "MWh/yr", max(th_max / 100, 1.0), th_max / 4
    else:
        th_values = df[f"{LABEL}_cf_pct{SUFFIX}"].values[estuary_only_arr]
        th_max = max(float(np.max(th_values)), 1.0)
        th_unit, th_step, th_default = "%", max(th_max / 100, 0.1), th_max / 4

    threshold = st.slider(
        f"Threshold ({th_unit})",
        min_value=0.0, max_value=float(th_max),
        value=float(th_default), step=float(th_step),
    )

    # Smooth curve
    n_pts = 200
    th_array = np.linspace(0.0, th_max, n_pts)
    area_above = np.array([
        float((th_values >= t).sum()) * CELL_AREA_KM2 for t in th_array
    ])
    n_above_now = int((th_values >= threshold).sum())
    area_now = n_above_now * CELL_AREA_KM2
    estuary_area_km2 = meta["estuary_cells"] * CELL_AREA_KM2

    curve_fig = go.Figure()
    curve_fig.add_trace(go.Scatter(
        x=th_array, y=area_above,
        fill="tozeroy",
        line=dict(color="#1565A0", width=2),
        fillcolor="rgba(21, 101, 160, 0.15)",
        showlegend=False,
        hovertemplate=(
            f"Threshold: %{{x:.2f}} {th_unit}<br>"
            "Area exceeding: %{y:.1f} km²<extra></extra>"
        ),
    ))
    curve_fig.add_vline(
        x=threshold, line=dict(color="red", dash="dash", width=2),
    )
    curve_fig.add_hline(
        y=area_now, line=dict(color="red", dash="dot", width=1),
    )
    curve_fig.update_layout(
        height=300,
        margin=dict(l=60, r=20, t=10, b=40),
        plot_bgcolor="white",
        font=dict(size=10),
        xaxis_title=f"Threshold ({th_unit})",
        yaxis_title="Estuary area exceeding (km²)",
    )
    curve_fig.update_xaxes(showgrid=True, gridcolor="#eeeeee")
    curve_fig.update_yaxes(
        showgrid=True, gridcolor="#eeeeee",
        range=[0, estuary_area_km2 * 1.05],
    )
    st.plotly_chart(
        curve_fig, use_container_width=True, config={"displaylogo": False}
    )

    cm1, cm2, cm3 = st.columns(3)
    cm1.metric(f"Cells ≥ {threshold:.2f} {th_unit}", f"{n_above_now:,}")
    cm2.metric("Area exceeding", f"{area_now:.1f} km²")
    cm3.metric(
        "% of estuary",
        f"{(area_now / estuary_area_km2 * 100):.1f}%",
    )


# --------------------------------------------------------------------------
# DETAILS PANEL
# --------------------------------------------------------------------------
with st.expander("Filter details", expanded=False):
    st.write(f"**Visible cells (after filters):** {n_visible:,}")
    st.write(f"**Visible area:** {n_visible * CELL_AREA_KM2:.1f} km²")
    if n_class3:
        st.write(
            f"**Class 3 viable** in visible region: {n_class3:,} cells, "
            f"{area_class3_km2:.1f} km²"
        )
        st.write(f"**Mean capacity factor (Class 3):** {mean_cf:.1f}%")
        st.write(f"**Total resource (Class 3 cells):** "
                 f"{total_energy_gwh:.1f} GWh/yr "
                 f"= {total_energy_gwh/1000:.2f} TWh/yr")

with st.expander("Configuration comparison table", expanded=False):
    rows = []
    for c in CONFIGS_AVAIL:
        m = df[keep]
        v = m[f"{c['label']}_viable{SUFFIX}"].values.astype(bool)
        e = m[f"{c['label']}_energy_mwh{SUFFIX}"].values
        rows.append({
            "Set":      c["label"],
            "D (m)":    c["D_m"],
            "Vr (m/s)": c["Vr_mps"],
            "Pr (kW)":  c["Pr_kW"],
            "Class 3 cells": int(v.sum()),
            "Viable area (km²)": round(int(v.sum()) * CELL_AREA_KM2, 2),
            "Mean energy (MWh/yr)": round(float(np.nanmean(e[v])) if v.any() else 0.0, 1),
            "Total resource (GWh/yr)": round(float(np.nansum(e[v]) / 1000.0), 2),
        })
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)


# --------------------------------------------------------------------------
# DOWNLOAD VISIBLE CELLS AS CSV  (rendered in sidebar)
# --------------------------------------------------------------------------
st.sidebar.subheader("5. Export")
_export_cols = [
    "i", "j", "x", "y",
    "in_estuary", "in_shipping", "in_any_site",
    "peak_vel_mps",
    f"{LABEL}_viable{SUFFIX}",
    f"{LABEL}_energy_mwh{SUFFIX}",
    f"{LABEL}_cf_pct{SUFFIX}",
]
_export_df = df.loc[keep, _export_cols].rename(columns={
    f"{LABEL}_viable{SUFFIX}":     "viable",
    f"{LABEL}_energy_mwh{SUFFIX}": "energy_mwh",
    f"{LABEL}_cf_pct{SUFFIX}":     "cf_pct",
    "peak_vel_mps":        "peak_vel",
})
_csv_bytes = _export_df.to_csv(index=False).encode("utf-8")
st.sidebar.download_button(
    label=f"📥 Download visible cells ({len(_export_df):,} rows)",
    data=_csv_bytes,
    file_name=f"shannon_{LABEL}_visible_cells.csv",
    mime="text/csv",
    use_container_width=True,
    help=(
        "Exports the cells currently visible (after spatial filters) for "
        "the selected turbine. Columns: i, j, x, y, masks, peak_vel, "
        "viable, energy_mwh, cf_pct."
    ),
)


# --------------------------------------------------------------------------
# URL STATE SYNC — write the current widget state back to the URL so the
# page URL is shareable / bookmarkable. Runs near the end so all widgets
# and click handlers have already updated session_state.
# --------------------------------------------------------------------------
st.query_params["set"]          = st.session_state["selected_set"]
st.query_params["field"]        = FIELD_TO_CODE.get(
    st.session_state["field_choice"], "energy"
)
st.query_params["top"]          = "1" if st.session_state["highlight_top"]   else "0"
st.query_params["excl_ship"]    = "1" if st.session_state["exclude_shipping"] else "0"
st.query_params["sites_only"]   = "1" if st.session_state["sites_only"]      else "0"
st.query_params["viable_only"]  = "1" if st.session_state["viable_only"]     else "0"
st.query_params["i"]            = str(int(st.session_state["inspect_i"]))
st.query_params["j"]            = str(int(st.session_state["inspect_j"]))
st.query_params["cmp"]          = "1" if st.session_state["compare_mode"] else "0"
if st.session_state["compare_mode"]:
    st.query_params["setB"]     = st.session_state["selected_set_b"]
    st.query_params["cmpmode"]  = (
        "sbs" if st.session_state["cmp_view"] == "Side-by-side" else "diff"
    )
st.query_params["crit"] = "r" if st.session_state["criterion"] == "rEMEC" else "b"


# --------------------------------------------------------------------------
# FOOTER
# --------------------------------------------------------------------------
st.markdown("---")
st.caption(
    "Data: DIVAST 2D depth-integrated hydrodynamic model "
    "(Falconer 1992, Lewis et al. 2021 standardized turbine power curve). "
    "Estuary mask: J = 50 boundary  ·  "
    "Cp = 0.40, ρ = 1025 kg/m³, cut-in = 0.30 × Vr. "
    "💡 The page URL encodes your current view — copy it to share or bookmark. "
    f"Built {meta['build_timestamp_utc']}."
)
