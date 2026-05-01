# Shannon Tidal Resource Explorer

A local-first Streamlit web app that turns the DIVAST 2D hydrodynamic
model output into an interactive map of the Shannon Estuary's
tidal-current energy resource. Pick one of the 13 turbine configurations,
look at the map, click a cell, drag a threshold slider, download the
underlying data — all without touching a `.dat` file.

The tool is the companion to the Shannon Estuary tidal-energy paper
(Eftekhari et al., in prep) and is designed to make the paper's analysis
explorable in a browser, on a laptop, with no cloud dependencies.

---

## Tier 1 vs Tier 2 — what this is and isn't

The tool was scoped in two tiers from the start.

### Tier 1 — what's built (this repo, version 1)

Tier 1 is the **simplest thing that demonstrates the analysis to
someone who isn't running Python**. It is single-page, single-config,
local-only, and deliberately under-featured. Its goals:

1. Replace "let me email you the figures" with "open this and click around."
2. Let Dr Nash interrogate any of the 13 configs on his own machine.
3. Be readable in two days of code (~700 lines including data prep).
4. Stay in sync with the paper's `Final_Results/` analysis automatically.

What's in Tier 1 (everything in this folder):

- Interactive map of the Shannon Estuary, one turbine config at a time
- Three map fields: Annual energy, Capacity factor, Peak velocity
- Live spatial filters (shipping lane, strategic sites, viable cells)
- Cell inspector — click any cell to see all 13 configs at that location
- Top-10 best cells highlight
- Distribution histogram of the visible field
- Cumulative-area-vs-threshold curve with interactive slider
- 13-config comparison table
- CSV download of the visible cells
- Always-on land underlay (sandy brown) + sea background (light blue)
- Tooltips on every metric explaining methodology and caveats

### Tier 2 — deferred (not built)

Tier 2 is the "make this publishable on the SEAI website" version.
Bigger ambition, more code, hosted publicly. Items discussed but not built:

- Side-by-side comparison of two turbine configs (or a difference map)
- Multi-page app (separate methodology / about / glossary pages)
- Custom packing-density slider for the resource estimate
- URL state sharing (paste a link, open the same view)
- PNG export with embedded caption metadata
- Comparison strip against the SEAI 2005 baseline (0.915 TWh/yr)
- Polygon-draw region select with custom statistics
- Time-series playback (would require rebuilding the data pipeline
  to retain hourly velocity)
- LCOE / economics calculator
- Public web hosting (GitHub Pages, Streamlit Community Cloud, etc.)
- Screenshot showcase / hero image for the README

If/when Tier 2 ships, it will live under
<https://github.com/eftekhari-alireza/eftekhari-alireza.github.io>. For
now, this is local-only.

---

## Quick start

You'll need Python 3.10 or newer (3.12 / 3.13 also tested).

```bash
# from the project root
cd DIVAST-Turbine

# install dependencies (a venv is fine but not required)
pip install -r tool/requirements.txt

# (optional, for click-to-inspect on the map)
pip install streamlit-plotly-events

# build the parquet file (one-off — takes ~15-30 s)
python tool/build_data.py

# launch the app
streamlit run tool/app.py
```

The app opens automatically in your default browser at
<http://localhost:8501>. Stop it with Ctrl+C in the terminal.

If `streamlit-plotly-events` is not installed, the app still works —
you just lose the click-to-inspect feature and have to type cell
coordinates manually.

---

## Architecture

The tool has two layers, kept deliberately separate so each can evolve
without disturbing the other:

```
   ┌────────────────────┐       ┌──────────────────────┐
   │  Final_Results/    │       │  Shannon_Turbine_    │
   │  _shared/          │──┐    │  Results_V2/         │
   │   masks.py         │  │    │   Set01_*/SHANNON…   │
   │   dat_loader.py    │  │    │   Set02_*/SHANNON…   │
   │   turbine_configs  │  │    │   …                  │
   └────────────────────┘  │    └──────────────────────┘
                           │              │
                           ▼              ▼
                  ┌──────────────────────────┐
                  │  tool/build_data.py       │   one-off (15 s)
                  └──────────────────────────┘
                           │
                           ▼
                  ┌──────────────────────────┐
                  │  tool/data/               │
                  │   shannon_grid.parquet    │   ≈ 0.7 MB, 110,019 rows
                  │   metadata.json           │
                  └──────────────────────────┘
                           │
                           ▼
                  ┌──────────────────────────┐
                  │  tool/app.py              │   live, interactive
                  │   (Streamlit + Plotly)    │
                  └──────────────────────────┘
```

**Why the two layers?** Re-parsing the F15.3 fixed-width `.dat` files on
every page-load is too slow (≈ 5 s × 13 files = 65 s). The data prep
script does it once, writes a single compact Parquet, and the app reads
it in < 100 ms.

---

## Data layer — `build_data.py`

A one-off script that reads the 13 SHANNONMAXVEL.dat files plus the
three masks, and writes one Parquet file at `tool/data/shannon_grid.parquet`.

### Schema (wide format, one row per DIVAST grid cell)

| Group | Column | Type | Notes |
|---|---|---|---|
| Cell metadata | `i`, `j` | int16 | row / column indices (0..IMAX-1, 0..JMAX-1) |
| | `x`, `y` | float32 | cell-centre coordinates in metres |
| Masks | `is_water` | bool | full DIVAST water mask (estuary + Atlantic) |
| | `in_estuary` | bool | True inside the Shannon Estuary mask only |
| | `in_shipping` | bool | True inside commercial shipping lane |
| | `in_anchorage` | bool | True inside designated anchorage |
| | `in_any_site` | bool | True inside any strategic site (Q/R/S/T) |
| | `site_q/r/s/t` | bool | individual strategic-site flags |
| Set-independent | `peak_vel_mps` | float32 | DIVAST peak velocity, capped at 3.0 m/s |
| | `avg_pd_kwm2` | float32 | time-averaged available power density (kW/m²) |
| Per-config × 13 | `{Set##}_viable` | bool | Class 3 (depth + velocity criteria met) |
| | `{Set##}_energy_mwh` | float32 | annual energy with depth+velocity constraint |
| | `{Set##}_cf_pct` | float32 | capacity factor in percent |

Total: ~50 columns × 110,019 rows × float32/bool ≈ ~0.7 MB on disk
(snappy compression). Easy to commit to Git or to drop into a Slack DM.

A small `metadata.json` sidecar carries grid constants (IMAX, JMAX,
cell area), per-config rated power, and a build timestamp.

### Capacity factor formula

```
CF (%) = AnnualEnergy(MWh) / (P_r_kW × 8760 / 1000) × 100
P_r_kW = 0.5 × Cp × ρ × (π × D² / 4) × Vᵣ³ / 1000
Cp = 0.40,  ρ = 1025 kg/m³
```

This matches `Final_Results/4.4_Economic_Considerations`.

### Re-running

If the paper's analysis changes — Set14/Set15 land, V1↔V2 depth flip,
new strategic site, mask boundary moves — rerun:

```bash
python tool/build_data.py
```

The script imports `Final_Results/_shared/` so it picks up changes
automatically. The app loads the new Parquet on its next launch.

---

## App layer — `app.py`

A single-file Streamlit app, ~700 lines (heavily commented). The layout
is divided into two columns: a sidebar with all the controls, and a
main area with the visualisations.

### Sidebar (left, fixed)

1. **Turbine configuration** — dropdown selector for one of 13 configs
   (Set01–Set13). The 5 × 3 grid is: 5 rotor diameters
   (3, 5, 10, 15, 20 m) × 3 rated velocities (1.5, 2.0, 2.5 m/s).
   Set14 and Set15 are reserved for the two pending V1.5 runs.

2. **Map field** — radio button for the field to colour the map by:
   Annual energy (MWh/yr), Capacity factor (%), or Peak velocity (m/s).

   Below the radio, a checkbox enables **"Highlight top 10 cells"** —
   draws red circle outlines around the 10 highest-value cells in the
   currently-visible region.

3. **Spatial filters** — three checkboxes (estuary mask is always on
   and not user-toggleable):
   - *Exclude shipping lane*
   - *Strategic sites only (Q/R/S/T)*
   - *Class 3 viable cells only ({selected config})*

   All filters are applied via boolean AND; the visible region is the
   intersection.

4. **About** — expandable build info: build timestamp, grid dims,
   cell area, estuary cell count, configs loaded, Cp/ρ values.

5. **Export** — a download button for the visible cells as CSV. The
   button label shows the row count so you don't accidentally download
   something enormous. Filename encodes the selected config
   (e.g., `shannon_Set07_visible_cells.csv`).

### Main area (top to bottom)

1. **Title + 4 metric cards** — Class 3 viable cells, viable area
   (km²), mean energy per turbine (MWh/yr), and "Theoretical max
   (1 turbine/cell)" (GWh/yr). Each card has a hover tooltip
   explaining methodology and caveats.

2. **Map** — Plotly heatmap with three / four layers:
   - Layer 1: Land — sandy-brown raster, always visible
   - Layer 2: Data — viridis / plasma / turbo, NaN-masked outside
     the visible region (so the land underlay shows through)
   - Layer 3 (optional): Top-N highlight markers
   - Layer 4: Inspect-cell × marker (white-rim X)

   The map has a fixed pixel layout — switching fields or filters
   never shifts the plot box or the colorbar position.

3. **Histogram strip** — small (~160 px) horizontal histogram of the
   currently-active field's distribution across visible cells. Helpful
   for spotting whether the resource is concentrated in a few hotspots
   or spread evenly.

4. **Cell inspector (expandable)** — type (i, j) coordinates OR click
   directly on the map (requires `streamlit-plotly-events`). Shows:
   - 4 context metrics for that cell: peak velocity, average power
     density, in-estuary flag, in-shipping-lane flag
   - 13-row table — for each turbine config, the cell's viability
     flag, annual energy (MWh/yr), and capacity factor (%)

   Default cell on first load: the highest-peak-velocity cell in the
   estuary.

5. **Cumulative area vs. threshold (expandable)** — radio to pick
   which field to threshold on (velocity / energy / CF), a slider for
   the threshold value, and an interactive curve showing the area of
   estuary where the field exceeds the threshold. Three live metrics:
   cells above threshold, area in km², percentage of estuary.

   The curve is computed over the **full estuary** regardless of the
   sidebar's spatial filters — the estuary is the natural denominator
   for "how much of the resource is above this threshold."

6. **Filter details (expandable)** — text breakdown of the visible
   region: cell counts, viable area, mean CF, total resource.

7. **Configuration comparison table (expandable)** — 13-row table
   showing every config's stats over the currently-visible region,
   for direct comparison.

8. **Footer** — methodology line: DIVAST 2D, Lewis et al. 2021 power
   curve, Cp / ρ / cut-in values, build timestamp.

### Interaction notes

- **Click-to-inspect**: requires `streamlit-plotly-events`. Without it,
  the app falls back to typed (i, j) coordinates only, and shows a tip
  in the caption explaining how to enable clicking.
- **Top-N selection**: respects all spatial filters. If you tick
  "Strategic sites only," the top 10 are picked from inside the sites,
  not the whole estuary.
- **Map orientation**: north is at the top (matches `Final_Results/
  figure_1_resource_distribution.py`). DIVAST row 0 corresponds to
  the high-Y northern boundary; the y-axis is reversed accordingly.
- **Inspect-cell × marker**: stays put when filters change, so you
  can compare the same physical location across different views.

---

## Stay-in-sync mapping

`build_data.py` and `app.py` import the existing analysis modules so
that adding a new turbine, changing a depth threshold, or moving the
estuary mask all propagate automatically.

| Subject | Single source of truth |
|---|---|
| Grid constants (IMAX, JMAX, DELX) | `Final_Results/_shared/masks.py` |
| Cell area, estuary count | `_shared/masks.py` (computed at import) |
| Estuary / shipping / sites masks | `_shared/masks.py` loaders |
| Land/sea mask (`is_water`) | `_shared/masks.py` (`load_water_mask_2d`) |
| 27-column `.dat` parser + column indices | `_shared/dat_loader.py` |
| 15-config registry, V1/V2 toggle, MIN_DEPTH | `_shared/turbine_configs.py` |
| Cp = 0.40, ρ = 1025, cut-in = 0.30·Vᵣ | matches `4.4_Economic_Considerations` |

The tool deliberately holds **no analysis logic of its own** — it is a
pure visualisation layer over the paper's authoritative numbers.

---

## Honest caveats and limitations

A few things worth knowing before drawing conclusions from the tool.

**Annual energy is from a 372-day simulation** — `TIMESM = 8928 hours`
in the DIVAST input file. That's ~1.018 years. The reported MWh/yr is
therefore ~1.8% above a strict 365-day annual estimate. The tooltip on
the *Mean energy / turbine* metric mentions "one full year (365 days)"
as a rounded reference; the underlying number is closer to 372 days.

**"Theoretical max (1 turbine/cell)" is an upper bound.** The metric
sums per-cell annual energy assuming exactly one turbine per
189 m × 189 m cell. That's roughly OK for D = 20 m turbines (cell
spacing ≈ 9.5 D, close to typical 5–10 D wake spacing) but heavily
underestimates packing density for D = 3–5 m turbines (cell spacing
38–63 D, much more sparse than realistic). Use this number as a
**relative comparator across configs**, not as an absolute resource
estimate. The tooltip on this metric spells this out.

**Capacity factor uses a fixed Cp = 0.40 and ρ = 1025 kg/m³.** Real
turbines have Cp curves that vary with tip-speed ratio and Reynolds
number. The fixed-Cp assumption is the standard Lewis et al. (2021)
simplification and is internally consistent with the paper.

**Peak velocity is capped at 3.0 m/s** by Shannon.f (this caps a
known model artefact in some narrow-channel cells). The tool just
reads the capped values; you'll see 3.0 m/s as the maximum in the
peak-velocity field.

**Set14 and Set15** (D = 20 m and D = 15 m at Vᵣ = 1.5 m/s) are not
yet simulated. They appear in `Final_Results/_shared/turbine_configs.py`
with `available=False` and are silently skipped by `build_data.py`.
When the runs land, flip `available=True` and rerun the build script.

**No farm-array effects.** Wakes between adjacent turbines, blockage,
and array efficiency factors are not modelled anywhere in this pipeline.
Resource numbers are single-turbine, isolated.

**Cell coordinates are DIVAST grid indices**, not lat/lon or projected
coords. The (x, y) metres in the parquet are arbitrary domain-relative
coordinates, not real-world. Useful for relative positioning on the
map; not useful for overlaying on a GIS.

---

## File layout

```
tool/
├── README.md             ← this file
├── requirements.txt      ← Python deps
├── build_data.py         ← one-off data prep (~250 lines)
├── app.py                ← Streamlit app (~700 lines)
└── data/
    ├── shannon_grid.parquet     ← compact wide-format table (~0.7 MB)
    └── metadata.json            ← grid + per-config metadata
```

`tool/data/` is created by `build_data.py` on first run. The parquet is
small enough to commit to Git; alternatively `.gitignore` it and let
each clone regenerate it.

---

## Versioning notes

- **Plotly is pinned to `<6`.** Plotly 6.x changed its JSON schema in a
  way that older Streamlit versions (≤ 1.34) silently fail to render.
  We're staying on Plotly 5.24.x; the requirements file enforces this.
- **Streamlit ≥ 1.30** works. 1.32 (current Anaconda default) is
  tested. If you upgrade past 1.40, you could replace
  `streamlit-plotly-events` with built-in `st.plotly_chart(on_select=...)`,
  but the current pattern works fine.

---

## Roadmap / known follow-ups

In rough priority order, things to do next if/when there's time:

- Add a **screenshot to the README** as a hero image (currently
  text-only).
- **Side-by-side comparison view** (Tier 2 marquee feature).
- **Methodology page** explaining DIVAST, Class 3, cut-in, Lewis 2021,
  etc., as a separate Streamlit page.
- **URL state encoding** so views are shareable.
- **Custom packing-density slider** for the resource estimate.
- **SEAI 2005 baseline reference card** in the metric strip.

When Set14 / Set15 land, just flip their `available` flags in
`Final_Results/_shared/turbine_configs.py` and rerun
`build_data.py`. The app's selector will pick them up automatically.

---

## Project context

This tool is part of the Shannon Estuary tidal-energy assessment
research (University of Galway, 2026), supervised by Dr Michael Hartnett
and Dr Stephen Nash. The DIVAST 2D depth-integrated model
(Falconer 1992) was run for a 5 × 3 turbine design grid; the analysis
and figures live in `Final_Results/` (sections 4.1–4.5 of the paper).

Future public hosting: <https://github.com/eftekhari-alireza/eftekhari-alireza.github.io>

---

*Author: Alireza Eftekhari — University of Galway, 2026*
