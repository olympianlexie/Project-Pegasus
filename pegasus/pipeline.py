"""Build the cleaned dataset that every output (map, KMZ, Excel) is made from."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from . import aggregate, config, geo, load, reconcile


@dataclass
class Dataset:
    raw_path: Path
    tableau_path: Path | None
    ports: pd.DataFrame
    naps: pd.DataFrame
    olts: pd.DataFrame
    pons: pd.DataFrame
    recon: dict
    dq: dict
    munis: dict
    bgys: dict
    reference_date: pd.Timestamp
    extra: dict = field(default_factory=dict)


def build(raw: str | None = None, tableau: str | None = None) -> Dataset:
    raw_path = load.find_input(config.RAW_FILE_GLOB, raw)
    ports = load.read_raw(raw_path)
    naps = aggregate.build_naps(ports)
    naps = aggregate.coord_stacks(naps)

    try:
        tableau_path = load.find_input(config.TABLEAU_FILE_GLOB, tableau)
        tab = load.read_tableau(tableau_path)
    except FileNotFoundError:
        tableau_path, tab = None, None

    if tab is not None:
        naps, recon = reconcile.reconcile(naps, ports, tab)
    else:  # still runnable without the Tableau file; blank OLTs stay blank
        recon = {}
        for c in ["in_tableau", "olt_inferred", "pon_inferred", "level_matches_tableau", "used_matches_tableau"]:
            naps[c] = False
        for c in ["tableau_olt", "tableau_used", "tableau_level", "tableau_distance_km"]:
            naps[c] = pd.NA
        naps["olt"] = naps["olt_raw"]
        naps["olt_source"] = "raw file"
        prefix = naps["olt"].astype("string").str.split("-").str[0]
        fold = lambda s: s.astype("string").str.upper().str.replace("Ñ", "N", regex=False)
        naps["cross_fed"] = naps["olt"].notna() & (fold(naps["site"]) != fold(prefix))
        naps["prefix_spelling_only"] = naps["olt"].notna() & (naps["site"] != prefix) & ~naps["cross_fed"]

    munis, bgys = geo.load_boundaries()
    naps = geo.match_areas(naps, munis, bgys)

    olt_sites = load.read_sites(config.OLT_SITES_FILE, "Olt Id")
    olts = aggregate.build_olts(naps, olt_sites)
    lcp_sites = load.read_sites(config.LCP_SITES_FILE, "Lcp Id")
    pons = aggregate.build_pons(naps)
    naps = reconcile.add_olt_distance(naps, olts)

    # Approximate LCP location (centroid of its NAPs), overridable by a site file.
    lcp = naps.groupby("lcp")[["lat", "lon"]].mean()
    lcp["source"] = "approximate (centroid of its NAPs)"
    if lcp_sites is not None:
        s = lcp_sites.set_index("id")
        hit = lcp.index.intersection(s.index)
        lcp.loc[hit, ["lat", "lon"]] = s.loc[hit, ["lat", "lon"]].values
        lcp.loc[hit, "source"] = "site file"

    dq = reconcile.data_quality(naps, ports)

    ref = pd.Timestamp(config.RFS_REFERENCE_DATE) if config.RFS_REFERENCE_DATE else pd.Timestamp.today().normalize()
    return Dataset(raw_path, tableau_path, ports, naps, olts, pons, recon, dq, munis, bgys, ref,
                   extra={"lcp_sites": lcp, "tableau_loaded": tab is not None})
