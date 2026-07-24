# Shannon Tidal Resource Explorer

A local-first Streamlit web app that turns the DIVAST 2D hydrodynamic
model output into an interactive map of the Shannon Estuary's
tidal-current energy resource. Pick one of the 15 turbine configurations
— **or specify a turbine of your own** — click any cell, drag a threshold
slider, download the underlying data, all without touching a `.dat` file.

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

## Tier 1 → Tier 2

The tool was scoped in two tiers from the start. **Tier 2 is what is now
deployed.**

### Tier 1 — the original release

Tier 1 was the **simplest thing that demonstrates the analysis to
someone who isn't running Python**: single-page, one configuration at a
time, deliberately under-featured. Its goals were to replace "let me
email you the figures" with "open this and click around", to let
supervisors and collaborators interrogate any of the 15 configs
themselves, and to stay in sync with the paper's analysis automatically.

Everything in Tier 1 is still here:

- Interactive map of the Shannon Estuary, one turbine config at a time
- Three map fields: Annual energy, Capacity factor, Peak velocity
- Live spatial filters (shipping lane, strategic sites, viable cells)
- **Side-by-side comparison** of any two configs, OR a **difference map
  (B − A)** with diverging colormap
- **Depth-criterion sensitivity toggle** — bEMEC (the EMEC-baseline
  criterion adopted for §§4.1–4.5 of the paper) or rEMEC (the relaxed
  variant used in §4.6's sensitivity test)
- **"Best config at this cell" auto-suggest** in the cell inspector
- Cell inspector — click any cell to see all 15 configs at that location,
  or type the (i, j) coordinates manually
- Top-10 best cells highlight (respects active spatial filters)
- Distribution histogram of the visible field below the map
- Cumulative-area-vs-threshold curve with interactive slider
- 15-config comparison table for the visible region
- CSV download of the visible cells
- **URL state sharing** — every sidebar choice is encoded in the page URL
- Always-on land underlay + sea background, stable layout, tooltips
  on every metric

### Tier 2 — what this release adds

Tier 1 could only answer questions about the fifteen turbines that were
simulated. Tier 2 answers them for **any** turbine, without re-running
the hydrodynamic model.

- **Define my own turbine** — a checkbox at the top of the sidebar opens
  a specification panel: rotor diameter (2–25 m), rated velocity
  (0.8–3.0 m/s), cut-in speed (either the 0.30 Vᵣ convention or set
  independently), power coefficient Cp, an optional cut-out speed, and
  the installation clearance criterion. Rated power, swept area and
  minimum deployment depth update live.
- **Every downstream view follows the custom machine** — the map, the
  four metric cards, the "viable cells only" filter, the threshold
  curve, the filter breakdown and the CSV export all describe the
  turbine you specified rather than a preset.
- **Speed-duration curve per cell** — the cell inspector plots how many
  hours a year the cell spends at or above each current speed, with
  cut-in and rated marked, plus the speeds exceeded 50 %, 25 % and 10 %
  of the year. This is the quantity that actually determines yield, and
  Tier 1 could only show the peak.
- **Clearance as a control** — the EMEC 5 m criterion (Eq. 5), the less
  conservative 4 m criterion (Eq. 6), or an arbitrary value, applied
  against the recovered bathymetry rather than a fixed lookup.

Ticking the checkbox is the only visible change to the Tier 1 interface.
With it unticked the app behaves exactly as before.

### Still deferred

- Multi-page app (separate methodology / about / glossary pages)
- Custom packing-density slider for the resource estimate
- PNG export with embedded caption metadata
- Comparison strip against the SEAI 2005 baseline (0.915 TWh/yr)
- Polygon-draw region select with custom statistics
- Time-series playback (needs hourly velocity, which the distribution
  layer deliberately does not retain — see below)
- LCOE / economics calculator
- Screenshot showcase / hero image for the README

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

Both pre-built data files ship with this repo (~2 MB total), so you
don't need to regenerate anything. If `streamlit-plotly-events` is not
installed the app still works — you just lose click-to-inspect and have
to type cell coordinates manually. If
`data/shannon_distributions.npz` is missing the app runs as Tier 1 and
the custom-turbine checkbox is simply not offered.

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
                 ┌────────┴────────────┴──────────────────────────┴─────┐
                 ▼                                                      ▼
   ┌──────────────────────────────────┐   ┌──────────────────────────────────┐
   │  build_data.py       (~30 s)     │   │  build_distributions.py  (~15 s) │
   │  loads bEMEC + rEMEC datasets    │   │  speed-duration curves + depth   │
   └──────────────────────────────────┘   └──────────────────────────────────┘
                 │                                          │
                 ▼                                          ▼
   ┌──────────────────────────────────────────────────────────────────────┐
   │  data/                                                                │
   │   shannon_grid.parquet          ≈ 1.1 MB, 110,019 rows, 105 columns   │
   │   shannon_distributions.npz     ≈ 0.9 MB, 14,612 estuary cells        │
   │   metadata.json                                                       │
   └──────────────────────────────────────────────────────────────────────┘
                                     │
                                     ▼
                 ┌──────────────────────────────────────────────────┐
                 │  app.py                  live, interactive       │
                 │   (Streamlit + Plotly)                            │
                 └──────────────────────────────────────────────────┘
```

**Why the layers?** Re-parsing the F15.3 fixed-width `.dat` files on
every page-load is too slow (≈ 5 s × 15 files = 75 s). The prep scripts
do it once and the app reads the results in well under a second.

Both prep scripts live in the parent research project workspace
(`DIVAST-Turbine/tool/`) because they import the paper's
`Final_Results/_shared/*` analysis modules. The artifacts they produce
are committed here so the public version is self-contained and runnable
without any of the underlying `.dat` files.

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

Total: 105 columns × 110,019 rows ≈ 1.1 MB on disk (snappy compression).

A small `metadata.json` sidecar carries grid constants (IMAX, JMAX,
cell area), per-config rated power, and a build timestamp.

### Capacity factor formula

```
CF (%) = AnnualEnergy(MWh) / (P_r_kW × 8760 / 1000) × 100
P_r_kW = 0.5 × Cp × ρ × (π × D² / 4) × Vᵣ³ / 1000
Cp = 0.40,  ρ = 1025 kg/m³
```

This matches `Final_Results/4.4_Economic_Considerations`.

---

## Distribution layer — `build_distributions.py`

The second prep step, and what makes Tier 2 possible. It writes
`data/shannon_distributions.npz`:

| Array | Type | Shape | Notes |
|---|---|---|---|
| `cell` | int32 | (n,) | flat grid index of each estuary cell |
| `phi` | float16 | (n, 120) | fraction of the year spent in each speed bin |
| `edges` | float32 | (121,) | bin edges, 0 → 3.0 m/s in 0.025 m/s steps |
| `h_lat` | float32 | (n,) | water depth relative to LAT, metres |
| `vmax` | float32 | (n,) | peak current speed, m/s |
| `mean_v3` | float32 | (n,) | E[v³], retained for cross-checking |

n = 14,612 estuary cells. About 0.9 MB compressed — comfortably
committable.

### How it works

The fifteen runs share one hydrodynamic solution: turbines are applied
in post-processing and never feed back into the flow, so peak velocity
and mean power density are identical across all fifteen `.dat` files and
`TOTAL_HOUR` takes only three distinct values, one per cut-in speed.
Everything those runs record about a cell's speed distribution therefore
reduces to a handful of numbers — the peak speed, three points on the
duration curve, the mean cube of speed, and three annual energies.

`build_distributions.py` solves the small inverse problem those numbers
define, recovering a 120-bin speed-duration curve per cell by
non-negative least squares with a smoothness penalty. The water-depth
field is read from the model input deck. Given the curve, the annual
energy of *any* power curve is a single dot product, and capacity factor
follows immediately.

### Accuracy

Rotor diameter is exact — energy scales precisely with swept area — and
the depth and velocity criteria read the depth and peak-speed fields
directly, so viable-area and cell-count outputs carry no reconstruction
error at all.

Energy and capacity factor are within **about 1 % (median cell error)**
for rated velocities of 1.0–2.5 m/s with a cut-in of 0.45–0.75 m/s,
which covers the commercially relevant range. Above 2.5 m/s the
90th-percentile cell error rises to roughly 10 %; below a 0.45 m/s
cut-in the underlying data does not constrain the distribution and the
error is not characterised. The app warns when a specification falls
outside the calibrated range.

The layer recovers the *distribution* of speed, not its time history.
Spring–neap sequencing, time-of-day structure and flow direction are not
represented, which is why time-series playback stays on the deferred
list.

### Re-running

If the underlying analysis changes, rerun both steps in order from the
parent workspace:

```bash
python tool/build_data.py            # parquet + metadata
python tool/build_distributions.py   # distributions + depth field
```

The second script re-verifies the recovered depth field against the
runs' own viability flags and refuses to write if they stop matching, so
a bad artifact cannot ship silently. Then copy
`data/shannon_grid.parquet`, `data/shannon_distributions.npz` and
`data/metadata.json` into this repo and commit.

---

## App layer — `app.py`

A single-file Streamlit app (heavily commented). The layout is divided
into two columns: a sidebar with all the controls, and a main area with
the visualisations.

### Sidebar (left, fixed)

1. **Turbine configuration** — dropdown selector for one of 15 configs
   (Set01–Set15). The 5 × 3 grid is: 5 rotor diameters
   (3, 5, 10, 15, 20 m) × 3 rated velocities (1.5, 2.0, 2.5 m/s).
   Default = **Set01** (D = 20 m, Vᵣ = 2.5 m/s).

   Three add-on controls appear below the selector:
   - *Define my own turbine* — opens the Tier 2 specification panel
     (diameter, rated velocity, cut-in, Cp, optional cut-out,
     clearance criterion). When ticked, the custom machine replaces the
     selected configuration everywhere below, and the preset selector
     and compare mode are stood down.
   - *Compare with another turbine* — a second selectbox and a
     "Side-by-side / Difference (B − A)" radio. The map area switches to
     either two side-by-side maps with shared colour scale, or a single
     difference map using a diverging RdBu colormap.
   - *Depth criterion* (only shown when the parquet contains rEMEC
     columns) — radio with **bEMEC** (primary, §§4.1–4.5) and **rEMEC**
     (relaxed, §4.6 sensitivity).

2. **Map field** — radio button for the field to colour the map by:
   Annual energy (MWh/yr), Capacity factor (%), or Peak velocity (m/s),
   plus a **"Highlight top 10 cells"** checkbox.

3. **Spatial filters** — three checkboxes (estuary mask is always on
   and not user-toggleable): exclude shipping lane, strategic sites
   only (Q/R/S/T), Class 3 viable cells only. All applied via boolean
   AND.

4. **About** — expandable build info: build timestamp, grid dims,
   cell area, estuary cell count, configs loaded, Cp/ρ values.

5. **Export** — a download button for the visible cells as CSV, labelled
   with the row count.

### Main area (top to bottom)

1. **Title + 4 metric cards** — Class 3 viable cells, viable area
   (km²), mean energy per turbine (MWh/yr), and "Theoretical max
   (1 turbine/cell)" (GWh/yr). Each has a tooltip explaining
   methodology and caveats. In custom mode the subtitle shows the full
   specification: diameter, rated velocity, cut-in, Cp, rated power,
   clearance and minimum depth.

2. **Map** — Plotly heatmap: land underlay, the data layer NaN-masked
   outside the visible region, optional top-N markers, and the
   inspect-cell marker. Fixed pixel layout, so switching fields or
   filters never shifts the plot box.

3. **Histogram strip** — distribution of the active field across
   visible cells.

4. **Cell inspector (expandable)** — type (i, j) coordinates or click
   the map. Shows four context metrics, the "best config at this cell"
   auto-suggest, and the 15-row per-config table. **In custom mode it
   also plots the cell's speed-duration curve**, with cut-in and rated
   marked and the 50 / 25 / 10 % exceedance speeds beneath it.

5. **Cumulative area vs. threshold (expandable)** — threshold on
   velocity, energy or CF, with a slider and a live curve of estuary
   area exceeding it. Computed over the full estuary regardless of the
   sidebar filters.

6. **Filter details (expandable)** — cell counts, viable area, mean CF,
   total resource for the visible region.

7. **Configuration comparison table (expandable)** — every config's
   stats over the currently-visible region.

8. **Footer** — methodology line and build timestamp.

### Interaction notes

- **URL state sharing**: every meaningful sidebar choice is written to
  the page URL. Copy it to reproduce the exact view elsewhere.
- **Click-to-inspect**: requires `streamlit-plotly-events`. Without it,
  the app falls back to typed (i, j) coordinates.
- **Top-N selection**: respects all spatial filters.
- **Compare mode**: difference of "Peak velocity" is identically zero
  (peak velocity is set-independent) — a notice explains this.
- **Map orientation**: north is at the top; DIVAST row 0 is the high-Y
  northern boundary and the y-axis is reversed accordingly.
- **Inspect-cell marker**: stays put when filters change, so you can
  compare the same location across views.

---

## Deployment

The live app is hosted on **Streamlit Community Cloud** (free tier).
Every push to the `main` branch triggers an auto-redeploy:

1. Push code change to GitHub `main`
2. Streamlit Cloud detects the push within ~30 seconds
3. Rebuilds the container (~1–2 minutes for code-only changes,
   slightly longer if `requirements.txt` changed)
4. New version goes live without downtime — failed builds keep the
   old version running, so visitors never see a broken app

The same app is embedded inline at
<https://eftekhari-alireza.github.io/Shannon-Tidal-Resource-Explorer/>
via an iframe with the `?embed=true` query parameter.

### Iteration loop

```
edit locally → test (streamlit run app.py) → git commit → git push
                                                              ↓
                              Streamlit Cloud auto-rebuilds (~2 min)
                                                              ↓
                                                        live URL updated
```

---

## Stay-in-sync mapping

The prep scripts import the existing analysis modules so that adding a
turbine, changing a depth threshold, or moving the estuary mask all
propagate automatically.

| Subject | Single source of truth |
|---|---|
| Grid constants (IMAX, JMAX, DELX) | `Final_Results/_shared/masks.py` |
| Cell area, estuary count | `_shared/masks.py` (computed at import) |
| Estuary / shipping / sites masks | `_shared/masks.py` loaders |
| Land/sea mask (`is_water`) | `_shared/masks.py` (`load_water_mask_2d`) |
| 27-column `.dat` parser + column indices | `_shared/dat_loader.py` |
| 15-config registry, V1/V2 toggle, MIN_DEPTH | `_shared/turbine_configs.py` |
| Clearance rule, depth field | `tool/recon/criteria.py` |
| Cp = 0.40, ρ = 1025, cut-in = 0.30·Vᵣ | matches `4.4_Economic_Considerations` |

Beyond evaluating a user-specified power curve, the tool holds no
analysis logic of its own — it is a visualisation layer over the
paper's authoritative numbers.

---

## File layout

```
shannon-tidal-explorer/
├── README.md             ← this file (canonical)
├── RUNBOOK.md            ← operational playbook for future updates
├── SKILL.md              ← architectural skill file (loaded by Claude when editing)
├── requirements.txt      ← Python deps
├── app.py                ← Streamlit app (single file)
├── .gitignore
├── .gitattributes
└── data/
    ├── shannon_grid.parquet          ← compact wide-format table (~1.1 MB)
    ├── shannon_distributions.npz     ← speed-duration curves + depth (~0.9 MB)
    └── metadata.json                 ← grid + per-config metadata
```

`build_data.py` and `build_distributions.py` are **not** in this public
repo. They live in the parent research project at `DIVAST-Turbine/tool/`
because they import the paper's `Final_Results/_shared/*` analysis
modules. The artifacts they produce are pre-built and committed here so
the public version is fully self-contained.

---

## Versioning notes

- **Plotly is pinned to `<6`.** Plotly 6.x changed its JSON schema in a
  way that older Streamlit versions (≤ 1.34) silently fail to render.
  We're staying on Plotly 5.24.x; the requirements file enforces this.
- **Streamlit ≥ 1.30** works. If you upgrade past 1.40 you could replace
  `streamlit-plotly-events` with built-in `st.plotly_chart(on_select=...)`,
  but the current pattern works fine.
- **NumPy ≥ 1.26** is required for the distribution layer's Gauss–Legendre
  bin integration; it is already in `requirements.txt`.

---

## Roadmap / known follow-ups

In rough priority order:

- Add a **screenshot to the README** as a hero image (currently
  text-only).
- **Methodology page** explaining DIVAST, Class 3, cut-in, Lewis 2021,
  etc., as a separate Streamlit page.
- **Turbine library** — preset specifications for real commercial
  machines, selectable in the custom panel.
- **Power-curve upload** — accept a user's own (v, P) CSV instead of the
  parametric curve.
- **Optimal rated-velocity map** — sweep Vᵣ continuously and colour each
  cell by the value that maximises energy or capacity factor.
- **Custom packing-density slider** for the resource estimate.
- **SEAI 2005 baseline reference card** in the metric strip.
- **PNG export** with embedded caption metadata.
- **Polygon-draw region select** for custom statistics.

---

## Project context

This tool is part of the Shannon Estuary tidal-energy assessment
research (University of Galway, 2026), supervised by Dr Stephen Nash. The DIVAST 2D depth-integrated model
(Falconer 1992) was run for a 5 × 3 turbine design grid.

---

*Author: Alireza Eftekhari — University of Galway, 2026*
