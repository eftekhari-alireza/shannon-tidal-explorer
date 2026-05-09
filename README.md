# Shannon Tidal Resource Explorer

A local-first Streamlit web app that turns the DIVAST 2D hydrodynamic
model output into an interactive map of the Shannon Estuary's
tidal-current energy resource. Pick one of the 15 turbine configurations,
click any cell, drag a threshold slider, download the underlying data —
all without touching a `.dat` file.

The tool is the companion to the Shannon Estuary tidal-energy paper
(Eftekhari et al., in prep) and is designed to make the paper's analysis
explorable in a browser, on a laptop, with no cloud dependencies.

---

## Live demo

| Where | What you see |
|---|---|
| [shannon-tidal-explorer.streamlit.app](https://shannon-tidal-explorer.streamlit.app/) | The standalone app, full screen |
| [eftekhari-alireza.github.io/Shannon-Tidal-Resource-Explorer](https://eftekhari-alireza.github.io/Shannon-Tidal-Resource-Explorer/) | The same app embedded in a portfolio page with description and context |

The app is hosted free on Streamlit Community Cloud and auto-redeploys
from this repo on every push to `main`. **Just want to play with it?**
Open either link — no install needed.

---

## Tier 1 vs Tier 2 — what this is and isn't

The tool was scoped in two tiers from the start.

### Tier 1 — what's built (this repo, version 1)

Tier 1 is the **simplest thing that demonstrates the analysis to
someone who isn't running Python**. It is single-page, single-config,
and deliberately under-featured. Its goals:

1. Replace "let me email you the figures" with "open this and click around."
2. Let supervisors and collaborators interrogate any of the 15 configs
   on their own machine or in a browser.
3. Be readable in two days of code (~700 lines including data prep).
4. Stay in sync with the paper's analysis automatically.

What's in Tier 1 (everything in this folder):

- Interactive map of the Shannon Estuary, one turbine config at a time
- Three map fields: Annual energy, Capacity factor, Peak velocity
- Live spatial filters (shipping lane, strategic sites, viable cells)
- **Side-by-side comparison** of any two configs, OR a **difference map
  (B − A)** with diverging colormap — directly visualises why one turbine
  beats another at a given cell
- **Depth-criterion sensitivity toggle** — switch between bEMEC (the
  EMEC-baseline criterion adopted for §§4.1–4.5 of the paper) and rEMEC
  (the relaxed variant used in §4.6's sensitivity test). Every number
  in the app re-reads from the chosen criterion's columns
- **"Best config at this cell" auto-suggest** in the cell inspector —
  shows which of the 15 configs maximises annual energy and which
  maximises capacity factor at the inspected cell, honouring the active
  depth criterion
- Cell inspector — click any cell to see all 15 configs at that location,
  or type the (i, j) coordinates manually
- Top-10 best cells highlight (respects active spatial filters)
- Distribution histogram of the visible field below the map
- Cumulative-area-vs-threshold curve with interactive slider
- 15-config comparison table for the visible region
- CSV download of the visible cells (one click, in the sidebar)
- **URL state sharing** — every sidebar choice (turbine, field, filters,
  compare mode, depth criterion, inspect cell) is encoded in the page URL.
  Copy and paste the URL to share the exact view with a collaborator
- Always-on land underlay (sandy brown) + sea background (light blue)
- Tooltips on every metric explaining methodology and caveats
- Stable layout — switching fields/filters never shifts the map or colorbar
- Hosted publicly on Streamlit Community Cloud with auto-redeploy
- Embedded on a portfolio page with description

### Tier 2 — deferred (not built)

Tier 2 is the bigger-ambition version. Items discussed but not built:

- Multi-page app (separate methodology / about / glossary pages)
- Custom packing-density slider for the resource estimate
- PNG export with embedded caption metadata
- Comparison strip against the SEAI 2005 baseline (0.915 TWh/yr)
- Polygon-draw region select with custom statistics
- Time-series playback (would require rebuilding the data pipeline
  to retain hourly velocity)
- LCOE / economics calculator
- Screenshot showcase / hero image for the README

(Three items previously listed under Tier 2 — side-by-side comparison,
URL state sharing, and depth-criterion sensitivity — were folded into
Tier 1 because they fit the single-page architecture and have direct
counterparts in the paper's analysis.)

---

## Quick start

You'll need Python 3.10 or newer (3.12 / 3.13 also tested).

```bash
# clone the repo
git clone https://github.com/eftekhari-alireza/shannon-tidal-explorer.git
cd shannon-tidal-explorer

# install dependencies (a venv is fine but not required)
pip install -r requirements.txt

# (optional, for click-to-inspect on the map)
pip install streamlit-plotly-events

# launch the app
streamlit run app.py
```

The app opens automatically in your default browser at
<http://localhost:8501>. Stop it with Ctrl+C in the terminal.

The pre-built parquet ships with this repo (~0.7 MB), so you don't need
to regenerate it yourself. If `streamlit-plotly-events` is not installed,
the app still works — you just lose the click-to-inspect feature and
have to type cell coordinates manually.

---

## Architecture

The tool has two layers, kept deliberately separate so each can evolve
without disturbing the other:

```
   ┌────────────────────┐    ┌──────────────────────┐  ┌──────────────────────┐
   │  Final_Results/    │    │  Shannon_Turbine_    │  │  Shannon_Turbine_    │
   │  _shared/          │─┐  │  Results_V2/ (bEMEC) │  │  Results_V1/ (rEMEC) │
   │   masks.py         │ │  │   Set01_*/SHANNON…   │  │   Set01_*/SHANNON…   │
   │   dat_loader.py    │ │  │   …                  │  │   …                  │
   │   turbine_configs  │ │  │   Set15_*/SHANNON…   │  │   Set15_*/SHANNON…   │
   └────────────────────┘ │  └──────────────────────┘  └──────────────────────┘
                          │            │                          │
                          ▼            ▼                          ▼
                  ┌──────────────────────────────────────────────────┐
                  │  build_data.py                  one-off (~30 s)  │
                  │  loads BOTH bEMEC and rEMEC datasets             │
                  └──────────────────────────────────────────────────┘
                                       │
                                       ▼
                  ┌──────────────────────────────────────────────────┐
                  │  data/                                            │
                  │   shannon_grid.parquet     ≈ 1.1 MB, 110,019 rows │
                  │                              105 columns          │
                  │                              (60 bEMEC + 45 rEMEC)│
                  │   metadata.json                                   │
                  └──────────────────────────────────────────────────┘
                                       │
                                       ▼
                  ┌──────────────────────────────────────────────────┐
                  │  app.py                  live, interactive       │
                  │   (Streamlit + Plotly)                            │
                  └──────────────────────────────────────────────────┘
```

**Why the two layers?** Re-parsing the F15.3 fixed-width `.dat` files on
every page-load is too slow (≈ 5 s × 15 files = 75 s). The data prep
script does it once, writes a single compact Parquet, and the app reads
it in < 100 ms.

`build_data.py` lives in the parent research project workspace
(`DIVAST-Turbine/tool/build_data.py`); the parquet it produces is
pre-built and committed to this repo so the public version is
self-contained and runnable without any of the underlying `.dat` files.

---

## Data layer — `build_data.py`

A one-off script that reads **30 SHANNONMAXVEL.dat files** (15 bEMEC +
15 rEMEC) plus the three masks, and writes one Parquet file at
`data/shannon_grid.parquet`.

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
| Per-config × 15 (bEMEC) | `{Set##}_viable` | bool | Class 3 under bEMEC (the EMEC-baseline criterion of §3.3 in the paper) |
| | `{Set##}_energy_mwh` | float32 | annual energy with bEMEC depth+velocity constraint |
| | `{Set##}_cf_pct` | float32 | capacity factor (%) under bEMEC |
| Per-config × 15 (rEMEC) | `{Set##}_viable_rEMEC` | bool | Class 3 under rEMEC (relaxed criterion, §4.6 sensitivity test) |
| | `{Set##}_energy_mwh_rEMEC` | float32 | annual energy under rEMEC |
| | `{Set##}_cf_pct_rEMEC` | float32 | capacity factor (%) under rEMEC |

Total: 105 columns × 110,019 rows × float32/bool ≈ ~1.1 MB on disk
(snappy compression). Still small enough to commit to Git.

The bEMEC columns alone (60 cols) are sufficient for §§4.1–4.5 of the
paper. The rEMEC columns (the additional 45) power the depth-criterion
sensitivity toggle in the sidebar and let the app reproduce the §4.6
analysis interactively.

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

If the paper's analysis changes — depth-criterion swap (bEMEC ↔ rEMEC),
new strategic site, mask boundary moves — rerun:

```bash
# from the parent DIVAST-Turbine workspace
python tool/build_data.py
```

The script imports `Final_Results/_shared/` so it picks up changes
automatically. Then copy the regenerated `data/shannon_grid.parquet`
and `data/metadata.json` into this repo and commit.

---

## App layer — `app.py`

A single-file Streamlit app, ~700 lines (heavily commented). The layout
is divided into two columns: a sidebar with all the controls, and a
main area with the visualisations.

### Sidebar (left, fixed)

1. **Turbine configuration** — dropdown selector for one of 15 configs
   (Set01–Set15). The 5 × 3 grid is: 5 rotor diameters
   (3, 5, 10, 15, 20 m) × 3 rated velocities (1.5, 2.0, 2.5 m/s).
   Default = **Set01** (D = 20 m, Vᵣ = 2.5 m/s).

   Two add-on controls appear below the selector:
   - *Compare with another turbine* — when ticked, a second selectbox and
     a "Side-by-side / Difference (B − A)" radio appear. The map area
     switches to either two side-by-side maps with shared color scale,
     or a single difference map using a diverging RdBu colormap. Cell
     inspector, threshold curve, comparison table and CSV export stay
     tied to the primary turbine (A).
   - *Depth criterion* (only shown when the parquet contains rEMEC
     columns) — radio with **bEMEC** (primary, §§4.1–4.5) and **rEMEC**
     (relaxed, §4.6 sensitivity). Switching this re-reads every number
     in the app from the chosen criterion's columns. Header subtitle
     shows which criterion is active.

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

2. **Map** — Plotly heatmap with multiple layers:
   - Layer 1: Land — sandy-brown raster, always visible
   - Layer 2: Data — viridis / plasma / turbo, NaN-masked outside
     the visible region (so the land underlay shows through)
   - Layer 3 (optional): Top-N highlight markers
   - Layer 4: Inspect-cell × marker (white-rim X)

   The map has a fixed pixel layout — switching fields or filters
   never shifts the plot box or the colorbar position.

3. **Histogram strip** — small (~160 px) horizontal histogram of the
   currently-active field's distribution across visible cells.

4. **Cell inspector (expandable)** — type (i, j) coordinates OR click
   directly on the map (requires `streamlit-plotly-events`). Shows:
   - 4 context metrics for that cell: peak velocity, average power
     density, in-estuary flag, in-shipping-lane flag
   - **"Best config at this cell" auto-suggest** — two green callout
     boxes with the per-cell argmax over the 15 configs: best by
     annual energy (with MWh/yr) and best by capacity factor (with %).
     Honours the active depth criterion (bEMEC or rEMEC). If no config
     is Class 3 viable at the cell, a yellow warning explains and
     suggests switching the criterion or picking a deeper cell.
   - 15-row table — for each turbine config, the cell's viability
     flag, annual energy (MWh/yr), and capacity factor (%) under the
     active criterion

   Default cell on first load: the highest-peak-velocity cell in the
   estuary, OR — if the URL contains `?i=…&j=…` — those coords.

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

7. **Configuration comparison table (expandable)** — 15-row table
   showing every config's stats over the currently-visible region,
   for direct comparison.

8. **Footer** — methodology line: DIVAST 2D, Lewis et al. 2021 power
   curve, Cp / ρ / cut-in values, build timestamp.

### Interaction notes

- **URL state sharing**: every meaningful sidebar choice is written to
  the page URL — turbine selection, map field, filters, compare mode +
  Turbine B, compare view, depth criterion, inspect cell. Copy the URL
  in your browser bar and paste it elsewhere to reproduce the exact
  view. Pasting a URL with no params loads the default state.
- **Click-to-inspect**: requires `streamlit-plotly-events`. Without it,
  the app falls back to typed (i, j) coordinates only, and shows a tip
  in the caption explaining how to enable clicking. In compare mode,
  the click handler is attached only to the primary (A) map.
- **Top-N selection**: respects all spatial filters. If you tick
  "Strategic sites only," the top 10 are picked from inside the sites,
  not the whole estuary. (Disabled in compare mode for clarity.)
- **Compare mode**: when active, the map area is replaced by either
  two side-by-side maps (shared colour scale) or a single difference
  map (B − A, diverging RdBu colormap). Difference of "Peak velocity"
  is identically zero (peak velocity is set-independent) — a notice
  appears explaining this.
- **Map orientation**: north is at the top. DIVAST row 0 corresponds to
  the high-Y northern boundary; the y-axis is reversed accordingly.
- **Inspect-cell × marker**: stays put when filters change, so you
  can compare the same physical location across different views.

---

## Deployment

The live app is hosted on **Streamlit Community Cloud** (free tier).
Every push to the `main` branch triggers an auto-redeploy:

1. Push code change to GitHub `main`
2. Streamlit Cloud detects the push within ~30 seconds
3. Rebuilds the container (~1–2 minutes for code-only changes,
   slightly longer if `requirements.txt` changed)
4. New version goes live without downtime — failed builds keep the
   old version running, so visitors are never seeing a broken app

The same app is embedded inline at
<https://eftekhari-alireza.github.io/Shannon-Tidal-Resource-Explorer/>
via an iframe with the `?embed=true` query parameter to hide
Streamlit Cloud's chrome.

### Iteration loop

```
edit locally → test (streamlit run app.py) → git commit → git push
                                                              ↓
                              Streamlit Cloud auto-rebuilds (~2 min)
                                                              ↓
                                                        live URL updated
```

No manual redeploy step. Updates land in front of users within a couple
of minutes of pushing to `main`.

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

## File layout

```
shannon-tidal-explorer/
├── README.md             ← this file (canonical)
├── RUNBOOK.md            ← operational playbook for future updates
├── SKILL.md              ← architectural skill file (loaded by Claude when editing)
├── requirements.txt      ← Python deps
├── app.py                ← Streamlit app (~1,000 lines, single file)
├── .gitignore
├── .gitattributes
└── data/
    ├── shannon_grid.parquet     ← compact wide-format table (~1.1 MB)
    └── metadata.json            ← grid + per-config metadata (incl. rEMEC counts)
```

`build_data.py` is **not** in this public repo. It lives in the parent
research project at `DIVAST-Turbine/tool/build_data.py` because it
imports the paper's `Final_Results/_shared/*` analysis modules. The
parquet it produces is pre-built and committed here so the public
version is fully self-contained.

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
- **Methodology page** explaining DIVAST, Class 3, cut-in, Lewis 2021,
  etc., as a separate Streamlit page.
- **Custom packing-density slider** for the resource estimate
  (could expose the three packing scenarios from §4.6 of the paper).
- **SEAI 2005 baseline reference card** in the metric strip.
- **PNG export** with embedded caption metadata.
- **Polygon-draw region select** for custom statistics.

When the paper's analysis changes (mask boundary moves, depth criterion
swap, new strategic site, etc.), just rerun `build_data.py` from the
parent `DIVAST-Turbine/` workspace and copy the regenerated parquet +
metadata into this repo. The app's selector picks up new configs
automatically.

---

## Project context

This tool is part of the Shannon Estuary tidal-energy assessment
research (University of Galway, 2026), supervised by Dr Stephen Nash
(with Dr Michael Hartnett). The DIVAST 2D depth-integrated model
(Falconer 1992) was run for a 5 × 3 turbine design grid; the analysis
and figures live in `Final_Results/` (sections 4.1–4.6 of the paper).

---

*Author: Alireza Eftekhari — University of Galway, 2026*
