"""Aggregate port rows to one row per NAP, and NAPs to OLT / PON / area summaries."""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import config

STATUS_CODES = {"ACTIVE": "A", "AVAILABLE": "V", "ALLOCATED": "L", "RESERVED": "R"}


def nap_level(used: pd.Series, total: pd.Series) -> pd.Series:
    share = used / total.where(total > 0)
    out = pd.Series(pd.NA, index=used.index, dtype="string")
    lower = -np.inf
    for name, upper in config.NAP_LEVEL_BOUNDS:
        out[(share > lower) & (share <= upper + 1e-9)] = name
        lower = upper + 1e-9
    return out


def olt_level(rate: pd.Series) -> pd.Series:
    out = pd.Series(pd.NA, index=rate.index, dtype="string")
    lower = -np.inf
    for name, upper, op in config.OLT_LEVEL_BOUNDS:
        hit = (rate >= lower) & ((rate < upper) if op == "lt" else (rate <= upper + 1e-9))
        out[hit & out.isna()] = name
        lower = upper
    out[(rate > 1) & out.isna()] = "Risk"
    return out


def build_naps(ports: pd.DataFrame) -> pd.DataFrame:
    p = ports
    st = p["Port Status"].fillna("UNKNOWN")
    has_acct = p["Account Number"].notna()
    flags = pd.DataFrame({
        "nap_id": p["Poi Name"],
        "used": st.isin(config.UTILIZED_STATUSES),
        "available": st.isin(config.SELLABLE_STATUSES),
        "active": st.eq("ACTIVE"),
        "allocated": st.eq("ALLOCATED"),
        "reserved": st.eq("RESERVED"),
        "other_status": ~st.isin(["ACTIVE", "AVAILABLE", "ALLOCATED", "RESERVED"]),
        "active_no_account": st.eq("ACTIVE") & ~has_acct,
        "inactive_with_account": ~st.eq("ACTIVE") & has_acct,
    })
    counts = flags.groupby("nap_id", sort=False).sum()

    first = p.groupby("Poi Name", sort=False).agg(
        site=("site", "first"), lcp=("lcp", "first"), np_=("np", "first"),
        olt_raw=("Olt Id", "first"), pon=("Olt Port Assignment", "first"),
        municipality=("z MUNICIPALITYNAME", "first"), barangay=("z BARANGAYNAME", "first"),
        province=("z PROVINCENAME", "first"),
        lat=("Np Latitude", "first"), lon=("Np Longitude", "first"),
        rfs_date=("RFS Date", "first"), ports_total=("Port Number", "size"),
        n_olt=("Olt Id", "nunique"), n_lat=("Np Latitude", "nunique"), n_lon=("Np Longitude", "nunique"),
        n_rfs=("RFS Date", "nunique"),
    )
    naps = first.join(counts).reset_index().rename(columns={"Poi Name": "nap_id", "np_": "np"})

    # Per-port status string, ordered by port number: A=active V=available L=allocated R=reserved ?=other
    code = st.map(STATUS_CODES).fillna("?")
    ps = (pd.DataFrame({"nap_id": p["Poi Name"], "port": p["Port Number"], "c": code})
          .sort_values(["nap_id", "port"]).groupby("nap_id", sort=False)["c"].agg("".join))
    naps["port_codes"] = naps["nap_id"].map(ps)

    naps["util_pct"] = naps["used"] / naps["ports_total"]
    naps["level"] = nap_level(naps["used"], naps["ports_total"])
    return naps


def coord_stacks(naps: pd.DataFrame) -> pd.DataFrame:
    """Adds pole_key, pole_count and placeholder_stack flags."""
    key = naps["lat"].round(7).astype(str) + "," + naps["lon"].round(7).astype(str)
    naps["pole_key"] = key
    naps["pole_count"] = key.map(key.value_counts())
    naps["placeholder_stack"] = naps["pole_count"] > config.STACK_FLAG_THRESHOLD
    return naps


def haversine_m(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(np.radians, (lat1, lon1, lat2, lon2))
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371008.8 * np.arcsin(np.sqrt(a))


def build_olts(naps: pd.DataFrame, olt_sites: pd.DataFrame | None) -> pd.DataFrame:
    g = naps.dropna(subset=["olt"]).groupby("olt")
    olts = g.agg(
        naps=("nap_id", "size"), ports_total=("ports_total", "sum"), used=("used", "sum"),
        available=("available", "sum"), active=("active", "sum"), allocated=("allocated", "sum"),
        reserved=("reserved", "sum"), lat=("lat", "mean"), lon=("lon", "mean"),
        pons=("pon", "nunique"), lcps=("lcp", "nunique"),
        municipalities=("municipality", lambda s: ", ".join(sorted(s.dropna().unique()))),
    )
    lvl = naps.dropna(subset=["olt"]).pivot_table(index="olt", columns="level", values="nap_id",
                                                  aggfunc="count", fill_value=0)
    for L in config.LEVELS:
        olts[f"naps_{L.lower()}"] = lvl[L] if L in lvl else 0
    olts["util_rate"] = olts["used"] / olts["ports_total"]
    olts["level"] = olt_level(olts["util_rate"])
    olts["location_source"] = "approximate (centroid of its NAPs)"
    if olt_sites is not None:
        s = olt_sites.set_index("id")
        hit = olts.index.intersection(s.index)
        olts.loc[hit, "lat"] = s.loc[hit, "lat"]
        olts.loc[hit, "lon"] = s.loc[hit, "lon"]
        olts.loc[hit, "location_source"] = "site file"
    return olts.reset_index().rename(columns={"index": "olt"})


def build_pons(naps: pd.DataFrame) -> pd.DataFrame:
    g = naps.dropna(subset=["olt"]).assign(pon=lambda d: d["pon"].fillna("(unknown)")).groupby(["olt", "pon"])
    pons = g.agg(naps=("nap_id", "size"), lcps=("lcp", lambda s: ", ".join(sorted(s.unique()))),
                 ports_total=("ports_total", "sum"), used=("used", "sum"), available=("available", "sum"))
    pons["util_rate"] = pons["used"] / pons["ports_total"]
    return pons.reset_index()


def area_summary(naps: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    g = naps.groupby(keys, dropna=False)
    out = g.agg(naps=("nap_id", "size"), ports_total=("ports_total", "sum"), used=("used", "sum"),
                available=("available", "sum"), olts=("olt", "nunique"))
    lvl = naps.pivot_table(index=keys, columns="level", values="nap_id", aggfunc="count", fill_value=0)
    for L in config.LEVELS:
        out[f"naps_{L.lower()}"] = lvl[L] if L in lvl else 0
    out["util_rate"] = out["used"] / out["ports_total"]
    return out.reset_index()
