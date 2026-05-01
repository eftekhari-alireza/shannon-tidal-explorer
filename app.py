"""
================================================================================
Shannon Tidal Resource Explorer — STREAMLIT APP (Tier 1)
================================================================================
Loads tool/data/shannon_grid.parquet (built once via tool/build_data.py)
and provides an interactive map of the Shannon Estuary tidal-current
resource for 13 turbine configurations (5 diameters × 3 rated velocities,
minus the 2 still-pending model runs).

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


# --------------------------------------------------------------------------
# SIDEBAR — TURBINE SELECTOR + LAYER TOGGLES
# --------------------------------------------------------------------------
st.sidebar.title("Shannon Tidal Resource Explorer")
st.sidebar.caption("Tier 1 prototype  |  DIVAST 2D model output")

# --- turbine selector ----
st.sidebar.subheader("1. Turbine configuration")

config_labels = [
    f"{c['label']}  —  D = {c['D_m']} m,  $V_r$ = {c['Vr_mps']} m/s"
    for c in CONFIGS_AVAIL
]
default_idx = next(
    (i for i, c in enumerate(CONFIGS_AVAIL) if c["label"] == "Set05"),
    0,
)
selected_idx = st.sidebar.selectbox(
    "Select a turbine",
    range(len(config_labels)),
    format_func=lambda i: config_labels[i],
    index=default_idx,
)
cfg = CONFIGS_AVAIL[selected_idx]
LABEL = cfg["label"]

# --- field to display on map ----
st.sidebar.subheader("2. Map field")
field_choice = st.sidebar.radio(
    "Show on map:",
    ["Annual energy per turbine (MWh/yr)",
     "Capacity factor (%)",
     "Peak velocity (m/s)"],
    index=0,
)
TOP_N = 10
highlight_top = st.sidebar.checkbox(
    f"Highlight top {TOP_N} cells",
    value=False,
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
exclude_shipping  = st.sidebar.checkbox("Exclude shipping lane", value=False)
sites_only        = st.sidebar.checkbox("Strategic sites only (Q/R/S/T)", value=False)
viable_only       = st.sidebar.checkbox(
    f"Class 3 viable cells only ({LABEL})", value=False,
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
        col = f"{label}_energy_mwh"
        title = "Annual energy (MWh/yr)"
        cmap = "Viridis"
        hover_fmt = ":.1f"
    elif field_choice.startswith("Capacity factor"):
        col = f"{label}_cf_pct"
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
# CELL-INSPECTOR session state — initialised once to the highest-velocity
# estuary cell.  The number_input widgets below the map write to these keys
# via Streamlit's `key=` parameter, which is read back here on the next run.
# --------------------------------------------------------------------------
if "inspect_i" not in st.session_state:
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
    keep &= df[f"{LABEL}_viable"].values.astype(bool)

grid, fld_title, hover_fmt, cmap, zmin, zmax = compute_display_grid(
    df, cfg, field_choice, keep,
)


# --------------------------------------------------------------------------
# HEADER + SUMMARY METRICS
# --------------------------------------------------------------------------
st.title("Shannon Tidal Resource Explorer")
st.markdown(
    f"**{LABEL}** · D = **{cfg['D_m']} m** · "
    f"$V_r$ = **{cfg['Vr_mps']} m/s** · "
    f"Rated power = **{cfg['Pr_kW']:.1f} kW**"
)

# Stats over visible cells
visible = df[keep]
n_visible = len(visible)

# Derived metrics for THIS config in the visible region
viable_mask = visible[f"{LABEL}_viable"].values.astype(bool)
n_class3 = int(viable_mask.sum())
area_class3_km2 = n_class3 * CELL_AREA_KM2

energy_arr = visible[f"{LABEL}_energy_mwh"].values
cf_arr     = visible[f"{LABEL}_cf_pct"].values
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
# PLOTLY HEATMAP
# --------------------------------------------------------------------------
st.subheader(f"{fld_title}  —  {LABEL}")

# Layout constants — fixed so switching fields/filters doesn't shift the map.
FIG_HEIGHT       = 520
RIGHT_MARGIN     = 80     # reserves space for the colorbar (no title) +
                          # tick labels. With no field-name title, this is
                          # constant across all 3 fields.
LAND_COLOR       = "#8b6f47"   # darker, earthier brown
SEA_COLOR        = "#bcd6e6"   # light sea blue

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
        f"{LABEL}_energy_mwh" if field_choice.startswith("Annual energy") else
        f"{LABEL}_cf_pct"     if field_choice.startswith("Capacity factor") else
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
# CELL INSPECTOR — see all 13 configs at a single cell
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

        rows = []
        for c in CONFIGS_AVAIL:
            rows.append({
                "Set":       c["label"],
                "D (m)":     c["D_m"],
                "Vᵣ (m/s)": c["Vr_mps"],
                "Pᵣ (kW)":  c["Pr_kW"],
                "Class 3 viable": "✓" if cell[f"{c['label']}_viable"] else "—",
                "Annual energy (MWh/yr)": round(float(cell[f"{c['label']}_energy_mwh"]), 1),
                "Capacity factor (%)":    round(float(cell[f"{c['label']}_cf_pct"]), 2),
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
        th_values = df[f"{LABEL}_energy_mwh"].values[estuary_only_arr]
        th_max = max(float(np.max(th_values)), 1.0)
        th_unit, th_step, th_default = "MWh/yr", max(th_max / 100, 1.0), th_max / 4
    else:
        th_values = df[f"{LABEL}_cf_pct"].values[estuary_only_arr]
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
        v = m[f"{c['label']}_viable"].values.astype(bool)
        e = m[f"{c['label']}_energy_mwh"].values
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
    f"{LABEL}_viable",
    f"{LABEL}_energy_mwh",
    f"{LABEL}_cf_pct",
]
_export_df = df.loc[keep, _export_cols].rename(columns={
    f"{LABEL}_viable":     "viable",
    f"{LABEL}_energy_mwh": "energy_mwh",
    f"{LABEL}_cf_pct":     "cf_pct",
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
# FOOTER
# --------------------------------------------------------------------------
st.markdown("---")
st.caption(
    "Data: DIVAST 2D depth-integrated hydrodynamic model "
    "(Falconer 1992, Lewis et al. 2021 standardized turbine power curve). "
    "Estuary mask: J = 50 boundary  ·  "
    "Cp = 0.40, ρ = 1025 kg/m³, cut-in = 0.30 × $V_r$. "
    f"Built {meta['build_timestamp_utc']}."
)
