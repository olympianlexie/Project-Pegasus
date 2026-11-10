"""Build the self-contained interactive HTML map (Leaflet, libraries inlined)."""
from __future__ import annotations

import base64
import json
from pathlib import Path

import numpy as np
import pandas as pd

from . import config

HERE = Path(__file__).resolve().parent
VENDOR = HERE / "vendor"
TEMPLATES = HERE / "templates"

FLAG_BITS = {
    "olt_inferred": 1, "placeholder_stack": 2, "cross_fed": 4, "new_vs_tableau": 8,
    "level_differs_tableau": 16, "relocate": 32, "sell_existing": 64, "reloc_target": 128,
    "pon_unknown": 256, "dist_estimated": 512, "new_rfs": 1024,
}


def _r(a, nd):
    return [None if (v is None or (isinstance(v, float) and np.isnan(v))) else round(float(v), nd) for v in a]


def payload(ds, reloc: dict) -> dict:
    n = ds.naps.sort_values(["municipality", "barangay", "nap_id"]).reset_index(drop=True)
    idx = {k: i for i, k in enumerate(n["nap_id"])}
    lv_i = {L: i for i, L in enumerate(config.LEVELS)}

    munis = sorted(n["municipality"].dropna().unique())
    m_i = {m: i for i, m in enumerate(munis)}
    mfeat = n.groupby("municipality")["municipality_feature"].first()
    pairs = n[["municipality", "barangay"]].drop_duplicates().sort_values(["municipality", "barangay"])
    b_i = {(a, b): i for i, (a, b) in enumerate(pairs.itertuples(index=False))}
    bfeat = n.groupby(["municipality", "barangay"])["barangay_feature"].first()
    olts = sorted(n["olt"].dropna().unique())
    o_i = {o: i for i, o in enumerate(olts)}
    pons = sorted(n["pon"].dropna().unique())
    p_i = {p: i for i, p in enumerate(pons)}

    flags = np.zeros(len(n), dtype=int)
    def setf(mask, name):
        flags[np.asarray(mask, dtype=bool)] |= FLAG_BITS[name]
    setf(n["olt_inferred"], "olt_inferred")
    setf(n["placeholder_stack"], "placeholder_stack")
    setf(n["cross_fed"], "cross_fed")
    setf(~n["in_tableau"].astype(bool), "new_vs_tableau")
    setf(n["in_tableau"].astype(bool) & (n["level"] != n["tableau_level"]), "level_differs_tableau")
    setf(n["pon"].isna(), "pon_unknown")
    setf(n["olt_distance_source"] != "Tableau", "dist_estimated")
    cutoff = ds.reference_date - pd.DateOffset(months=config.NEW_NAP_EXCLUSION_MONTHS)
    setf(n["rfs_date"] > cutoff, "new_rfs")
    rec = reloc["recommendations"]
    sell = reloc["sell_from_existing"]
    setf(n["nap_id"].isin(rec["nap_id"]) if len(rec) else False, "relocate")
    setf(n["nap_id"].isin(sell["nap_id"]), "sell_existing")
    setf(n["nap_id"].isin(rec["target_nap"]) if len(rec) else False, "reloc_target")

    rfs = n["rfs_date"]
    rfs_days = np.where(rfs.notna(), (rfs - pd.Timestamp("1970-01-01")).dt.days.fillna(-1), -1).astype(int)

    naps = {
        "id": n["nap_id"].tolist(),
        "lat": _r(n["lat"], 6), "lon": _r(n["lon"], 6),
        "lv": [lv_i[x] for x in n["level"]],
        "u": n["used"].astype(int).tolist(), "a": n["available"].astype(int).tolist(),
        "t": n["ports_total"].astype(int).tolist(),
        "ps": n["port_codes"].tolist(),
        "o": [o_i.get(x, -1) if pd.notna(x) else -1 for x in n["olt"]],
        "p": [p_i.get(x, -1) if pd.notna(x) else -1 for x in n["pon"]],
        "b": [b_i[(a, b)] for a, b in zip(n["municipality"], n["barangay"])],
        "r": rfs_days.tolist(),
        "d": _r(n["olt_distance_km"], 2),
        "f": flags.tolist(),
        "tl": [lv_i.get(x, -1) if isinstance(x, str) else -1 for x in n["tableau_level"]],
        "tu": [int(x) if pd.notna(x) else -1 for x in n["tableau_used"]],
    }
    brgys = [[m_i[a], b, int(bfeat[(a, b)]) if pd.notna(bfeat[(a, b)]) else -1] for (a, b) in pairs.itertuples(index=False)]
    muni_list = [[m, int(mfeat[m]) if pd.notna(mfeat[m]) else -1] for m in munis]

    o = ds.olts.set_index("olt")
    olt_list = []
    for oid in olts:
        r = o.loc[oid]
        olt_list.append({
            "id": oid, "lat": round(float(r["lat"]), 6), "lon": round(float(r["lon"]), 6),
            "lv": lv_i[r["level"]], "src": r["location_source"], "util": round(float(r["util_rate"]), 4),
            "naps": int(r["naps"]), "ports": int(r["ports_total"]), "used": int(r["used"]),
            "avail": int(r["available"]), "pons": int(r["pons"]), "lcps": int(r["lcps"]),
            "byLv": [int(r[f"naps_{L.lower()}"]) for L in config.LEVELS],
            "munis": r["municipalities"],
        })

    rl = {}
    if len(rec):
        rl = {
            "c": [idx[x] for x in rec["nap_id"]], "t": [idx[x] for x in rec["target_nap"]],
            "h": rec["target_hotspot"].tolist(), "d": _r(rec["distance_m"], 0),
            "rank": rec["priority_rank"].astype(int).tolist(),
            "lv": [lv_i[x] for x in rec["target_level"]],
            "sl": rec["same_lcp"].astype(int).tolist(),
            "g": rec["potential_subscriber_gain"].astype(int).tolist(),
            "rh": rec["rehome_to"].fillna("").tolist(),
        }
    hs = reloc["hotspots"]
    hot = {
        "id": hs["hotspot"].tolist(), "lat": _r(hs["lat"], 6), "lon": _r(hs["lon"], 6),
        "n": hs["naps"].astype(int).tolist(), "risk": hs["risk_naps"].astype(int).tolist(),
        "high": hs["high_naps"].astype(int).tolist(), "rad": _r(hs["radius_m"], 0),
        "lv": [lv_i[x] for x in hs["level"]], "need": hs["ports_needed"].astype(int).tolist(),
        "net": hs["ports_needed_net"].astype(int).tolist(), "idle": hs["idle_ports_within_reach"].astype(int).tolist(),
        "cap": hs["capacity_naps_net"].astype(int).tolist(), "asg": hs["relocated_naps_assigned"].astype(int).tolist(),
        "m": hs["municipality"].tolist(), "bg": hs["barangay"].tolist(),
    }
    sl = {"i": [idx[x] for x in sell["nap_id"]], "d": _r(sell["nearest_demand_m"], 0),
          "n": [idx.get(x, -1) for x in sell["nearest_demand_nap"]]}

    return {
        "meta": {
            "title": config.MAP_TITLE, "generated": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M"),
            "raw": ds.raw_path.name, "tableau": ds.tableau_path.name if ds.tableau_path else None,
            "utilized": sorted(config.UTILIZED_STATUSES), "levels": config.LEVELS, "colors": config.LEVEL_COLORS,
            "center": config.MAP_CENTER, "zoom": config.MAP_START_ZOOM, "flags": FLAG_BITS,
            "refDate": str(ds.reference_date.date()), "newMonths": config.NEW_NAP_EXCLUSION_MONTHS,
            "dropReach": config.DROP_REACH_M, "maxReloc": config.MAX_RELOCATION_M,
            "nearRule": config.NEAR_DEMAND_RULE, "stackThreshold": config.STACK_FLAG_THRESHOLD,
            "oltBounds": [b[1] for b in config.OLT_LEVEL_BOUNDS[:3]],
        },
        "munis": muni_list, "brgys": brgys, "olts": olt_list, "pons": pons,
        "naps": naps, "reloc": rl, "hot": hot, "sell": sl,
        "geoM": ds.munis, "geoB": ds.bgys,
    }


def _inline_css() -> str:
    css = (VENDOR / "leaflet.css").read_text(encoding="utf-8")
    png = base64.b64encode((VENDOR / "layers.png").read_bytes()).decode()
    css = css.replace("url(images/layers.png)", f"url(data:image/png;base64,{png})")
    css = css.replace("url(images/layers-2x.png)", f"url(data:image/png;base64,{png})")
    return css + "\n" + (VENDOR / "MarkerCluster.css").read_text(encoding="utf-8")


def build(ds, reloc: dict, out_path: Path) -> Path:
    data = json.dumps(payload(ds, reloc), ensure_ascii=False, separators=(",", ":"))
    data = data.replace("</", "<\\/")
    libs = "\n".join((VENDOR / f).read_text(encoding="utf-8")
                     for f in ["leaflet.js", "leaflet.markercluster.js", "leaflet-heat.js"])
    html = (TEMPLATES / "map.html").read_text(encoding="utf-8")
    html = (html.replace("/*__VENDOR_CSS__*/", _inline_css())
                .replace("/*__APP_CSS__*/", (TEMPLATES / "app.css").read_text(encoding="utf-8"))
                .replace("/*__VENDOR_JS__*/", libs)
                .replace("/*__APP_JS__*/", (TEMPLATES / "app.js").read_text(encoding="utf-8"))
                .replace("__TITLE__", config.MAP_TITLE)
                .replace("__DATA__", data))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    return out_path
