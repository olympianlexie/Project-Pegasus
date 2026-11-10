# Project Pegasus

Interactive utilization map of every **OLT** and **NAP** in **Laguna**, and a **NAP relocation plan** that moves
idle (Low) NAPs to nearby areas where NAPs are full (High/Risk).

One command builds everything from the raw port export:

| Output | What it is |
|---|---|
| `output/pegasus_map.html` | Self-contained web map (opens offline in any browser; only the basemap tiles need internet). |
| `output/google_earth/*.kmz` | Google Earth files: NAPs per level, OLTs, utilization choropleth, relocation plan. |
| `output/Pegasus_Relocation_Plan.xlsx` | Relocation recommendations, "sell from existing" list, hotspots, summaries, data-quality and reconciliation sheets. |
| `output/Pegasus_NAP_Table.xlsx` | One row per NAP, plus OLT, PON, municipality and barangay tables. |
| `output/validation_report.txt` | The validation report printed on every run. |

> **This repository is public.** The exports and every output contain customer account numbers and network
> locations, so `data/` and `output/` are git-ignored. Never commit them. Share outputs through your usual
> internal channels.

## Setup (once)

Python 3.10+.

```bash
pip install -r requirements.txt
```

## Run

1. Put the two exports in `data/` (names can keep their date suffixes):
   - `Raw - Port Utilization*.xlsx` (required: one row per NAP port)
   - `Network Elements Map_Tableau Data*.xlsx` (optional: used for reconciliation, NAP-OLT distance and
     filling blank OLT IDs)
2. Rebuild:

```bash
python -m pegasus.run
```

The newest matching file in `data/` is used. To point at specific files:

```bash
python -m pegasus.run --raw "path/to/Raw - Port Utilization.xlsx" --tableau "path/to/Network Elements Map_Tableau Data.xlsx"
```

`--skip-kmz` and `--skip-excel` make a quick map-only rebuild. The first read of a new export takes about 30 s,
then it is cached in `output/.cache/`. A full run takes about 30-60 s.

### Updating the data

Drop the new export into `data/` and run `python -m pegasus.run` again. Then check the validation report it
prints:

- every `[OK]` check passed (8 ports per NAP, one coordinate and one OLT per NAP, no duplicate ports), and
- **Coverage gaps and unmatched IDs**: blank OLT IDs, barangay names that didn't match a boundary (add them to
  `boundaries/barangay_aliases.csv`), and any OLT renumbering detected against Tableau.

`tests/test_snapshot.py` checks the totals in `data/expected_counts.json` (git-ignored, so the figures stay
private). It skips itself when that file is missing or was written for a different export; edit the file to pin a
new export.

### Real OLT / LCP locations

The exports have no OLT coordinates, so each OLT is drawn at the **centroid of its NAPs** and labelled
"approximate". To use real sites, create `data/olt_sites.csv`:

```
Olt Id,Latitude,Longitude
ABC001-OLT-01,14.2101,121.1650
```

`data/lcp_sites.csv` (`Lcp Id,Latitude,Longitude`) does the same for LCPs (used for the "LCP to target" distance).
Listed sites override the centroids; others stay approximate.

## Settings

Everything tunable is at the top of [`pegasus/config.py`](pegasus/config.py). Confirmed defaults:

| Setting | Default | Meaning |
|---|---|---|
| `UTILIZED_STATUSES` | ACTIVE + ALLOCATED + RESERVED | Ports that count as utilized (can't be sold). Matches Tableau far better than ACTIVE only. |
| NAP levels | Low 0-2, Optimal 3-4, High 5-6, Risk 7-8 used | Per 8-port NAP. |
| OLT levels | < 30%, 30-60%, 60-80%, > 80% | Utilized / total ports of the OLT. |
| `MAX_RELOCATION_M` | 500 | Farthest move. |
| Fiber rule | own LCP/PON | A moved NAP stays on its own LCP and PON (cable re-routed or extended). |
| `TARGET_SCOPE` | `same_olt` | Target must be on the candidate's OLT (`same_lcp` or `any` also possible); same LCP is preferred. |
| `NEW_NAP_EXCLUSION_MONTHS` | 12 | Skip Low NAPs RFS'd within this many months of the run date. |
| `HOTSPOT_RELIEF_TARGET_USED` | 4 | A hotspot can take as many NAPs as needed to bring its Risk/High NAPs down to 4 used ports. |
| `DROP_REACH_M` / `NEAR_DEMAND_RULE` | 150 / `keep` | See below. |

### Why most Low NAPs are not relocated (`NEAR_DEMAND_RULE`)

In the current data, **most eligible Low NAPs already have a Risk or High NAP within 150 m**, many on the same
pole: idle and full NAPs are interleaved. The validation report prints the exact counts. Moving such a NAP 20-100 m adds no capacity, since the
demand is already within drop-cable reach. With `NEAR_DEMAND_RULE = "keep"` (default):

- those NAPs are listed on the **Sell_From_Existing** sheet (connect new subscribers in that area to them first),
  and are not moved;
- their idle ports count as supply already serving the nearby hotspot, so it needs fewer relocated NAPs;
- only Low NAPs that are out of reach of any demand are relocated.

Set it to `"relocate"` to treat every Low NAP as a candidate (only same-pole targets are skipped). That produces
many more, but mostly very short, moves.

## How the relocation plan works

1. **Candidates**: Low NAPs, minus NAPs RFS'd in the last 12 months and NAPs at possible placeholder coordinates.
2. **Demand hotspots**: Risk and High NAPs grouped with DBSCAN (150 m), large groups split to a 400 m radius.
   Each hotspot's need = ports required to bring every member down to 4 used, minus idle ports already in reach,
   divided by 8 ports per NAP.
3. **Assignment**, in priority order: 0 used ports first, then 1, then 2; closer moves first. Each candidate goes
   to the best hotspot within 500 m on its OLT: Risk before High, same LCP preferred, then nearest. The target is
   the nearest pole in that hotspot (never the candidate's own pole, at most 2 relocated NAPs per pole).
4. **Subscribers**: a candidate with 1-2 used ports is only moved if a NAP within 150 m on its LCP has enough
   available ports to take its subscribers. That NAP is then kept in place.
5. **Output**: `Recommendations` (priority rank, candidate, target hotspot/NAP and coordinates, distance, level,
   new sellable ports, subscribers to re-home), `Not_Relocated` with a reason for every other Low NAP, and summaries
   by municipality and barangay, both from where NAPs are taken and to where they go.

## Using the map

Open `output/pegasus_map.html` in Chrome, Edge or Firefox (double-click; no server needed).

- **Layers** (top right): street map or Esri satellite, NAPs, OLTs, relocation arrows, demand hotspots, heat maps
  per level, barangay and municipality choropleths.
- **Clusters**: the ring shows the mix of levels inside. Click to zoom in. NAPs stacked on one coordinate fan out
  (spiderfy) when clicked, so none are hidden.
- **Click a NAP**: IDs, OLT + PON, barangay, ports used/available/total, status per port, RFS date, distance to
  OLT, other NAPs on the same pole, relocation advice and data-quality flags.
- **Click an OLT**: totals, NAP counts by level, and a per-PON table.
- **Filters** (left panel): municipality, barangay, OLT, level, RFS date range and "Show" (relocation candidates,
  sell-from-existing, data-quality flags, ...). The summary, choropleths, heat maps and arrows follow the filters.
- **Search**: a NAP ID (`ABC001 LP12 NP3`), LCP (`ABC001 LP12`) or OLT (`ABC001-OLT-01`).

## Google Earth

Files are in `output/google_earth/`:

| File | Content |
|---|---|
| `pegasus_naps_risk.kmz`, `_high`, `_optimal`, `_low` | NAPs of one level, in a folder per municipality, same colors and popup info as the map. |
| `pegasus_olts.kmz` | OLTs (approximate locations). |
| `pegasus_choropleth.kmz` | Barangay utilization polygons (on) and municipality polygons (off). |
| `pegasus_relocations.kmz` | Relocation lines by municipality, candidate NAPs, and the hotspots that receive NAPs. |

**Why one file per level:** Google Earth Web slows down badly above roughly 10-20k placemarks in one file, and it
doesn't support KML Regions (level-of-detail). Splitting by level keeps every file at 20k placemarks or fewer (Low
is the largest), matches how the data is read (switch on Risk first), and behaves the same in Earth Pro and Earth
Web. Each file embeds its own icons.

- **Google Earth Pro** (desktop): File → Open → pick one or more `.kmz` files. They appear under *Temporary Places*;
  tick folders on and off, click a dot for its details. Drag them to *My Places* to keep them.
- **Google Earth Web** (earth.google.com): open the **Projects** panel → **New project** → **Import KML file from
  computer** → pick a `.kmz`. Repeat for each file you want. Start with Risk and High; the Low file is the heaviest.

## Data issues handled (and reported every run)

The validation report and the `DQ_*` / `Recon_*` sheets list each of these with counts and IDs.

- **Blank OLT IDs**: filled first from other NAPs on the same LCP, otherwise from Tableau, translated to the current
  OLT numbering, and marked "OLT inferred". Their PON port stays unknown.
- **OLT renumbering** between the Tableau export and the raw file: detected automatically from NAP overlap; raw IDs
  are treated as current, and the mapping is in `Recon_OLT_Renumbering`.
- **Stacked coordinates**: coordinates with more than 4 NAPs are flagged as possible placeholders and left out of
  relocation. On the map, stacked NAPs fan out when clicked.
- **Cross-fed NAPs**: site prefix differs from the OLT prefix. Site codes are written with `Ñ` and OLT IDs with `N`
  (e.g. `BÑL…` vs `BNL…`); Ñ is treated as N so spelling alone doesn't count as cross-fed.
- **Account numbers**: read as text. ACTIVE ports without an account, non-active ports with one, and account numbers
  in an unusual format (test accounts, corrupted values) are listed.
- **Reconciliation with Tableau**: NAPs missing on either side, utilized-port and level differences, and Tableau
  Sheet 1 (OLT × municipality) compared in current OLT numbering, with its stray single-port rows flagged.
- **Barangay names**: matched to PSGC boundaries after normalizing case, Ñ, "CITY OF" and "(POB.)", plus
  `boundaries/barangay_aliases.csv` for PSGC spellings.

## Project layout

```
pegasus/
  config.py        settings (edit this)
  load.py          read and clean the exports
  aggregate.py     port rows -> NAPs -> OLT / PON / area summaries, levels
  reconcile.py     Tableau reconciliation, OLT inference, data-quality checks
  geo.py           PSGC boundaries and name matching
  pipeline.py      builds the cleaned dataset used by every output
  relocate.py      demand hotspots and relocation plan
  build_map.py     HTML map (templates/ holds the page, styles and map code)
  export_kmz.py    Google Earth files
  report_excel.py  Excel workbooks
  validate.py      validation report
  run.py           the one command
  vendor/          Leaflet 1.9.4, Leaflet.markercluster 1.5.3, Leaflet.heat 0.2.0 (inlined into the map)
boundaries/        Laguna municipality + barangay polygons (PSGC 3Q 2026) and name aliases
tests/             unit tests, a synthetic relocation scenario, and snapshot checks
data/              your exports (git-ignored)
output/            generated files (git-ignored)
```

Run the tests with `python -m pytest`.
