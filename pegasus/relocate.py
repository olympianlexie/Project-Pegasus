"""NAP relocation planner: move idle Low NAPs to nearby Risk/High demand hotspots.

Fiber rule (confirmed): a relocated NAP stays on its own LCP and PON (its cable is
re-routed or extended), so no splitter leg or PON capacity is needed at the target.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
from sklearn.cluster import DBSCAN, KMeans
from sklearn.neighbors import BallTree

from . import config
from .aggregate import haversine_m

R_EARTH = 6371008.8


def _rad(df: pd.DataFrame) -> np.ndarray:
    return np.radians(df[["lat", "lon"]].to_numpy(dtype=float))


def _xy(lat: np.ndarray, lon: np.ndarray, lat0: float) -> np.ndarray:
    return np.c_[lon * math.cos(math.radians(lat0)) * 111320.0, lat * 110540.0]


def _split_large(idx: np.ndarray, lat: np.ndarray, lon: np.ndarray, max_r: float) -> list[np.ndarray]:
    """Recursively bisect a group until every point is within max_r of the group centroid."""
    xy = _xy(lat[idx], lon[idx], float(lat[idx].mean()))
    r = np.sqrt(((xy - xy.mean(axis=0)) ** 2).sum(axis=1)).max()
    if r <= max_r or len(np.unique(xy, axis=0)) < 2:
        return [idx]
    lab = KMeans(n_clusters=2, n_init=4, random_state=0).fit_predict(xy)
    return (_split_large(idx[lab == 0], lat, lon, max_r) + _split_large(idx[lab == 1], lat, lon, max_r))


def build_hotspots(targets: pd.DataFrame) -> pd.DataFrame:
    """Group Risk/High NAPs into demand hotspots. Adds 'hotspot' to targets; returns the hotspot table."""
    lat, lon = targets["lat"].to_numpy(float), targets["lon"].to_numpy(float)
    lab = DBSCAN(eps=config.HOTSPOT_EPS_M / R_EARTH, min_samples=config.HOTSPOT_MIN_NAPS,
                 metric="haversine", algorithm="ball_tree").fit_predict(np.radians(np.c_[lat, lon]))
    groups: list[np.ndarray] = []
    for c in sorted(set(lab) - {-1}):
        groups += _split_large(np.flatnonzero(lab == c), lat, lon, config.HOTSPOT_MAX_RADIUS_M)
    if config.INCLUDE_SINGLE_NAP_HOTSPOTS:
        noise = np.flatnonzero(lab == -1)
        for _, g in pd.Series(noise).groupby(targets["pole_key"].to_numpy()[noise]):
            groups.append(g.to_numpy())
    hid = np.full(len(targets), "", dtype=object)
    # Number hotspots by size (largest first) for stable, readable IDs.
    groups.sort(key=lambda g: (-len(g), float(lat[g].mean()), float(lon[g].mean())))
    for k, g in enumerate(groups, 1):
        hid[g] = f"H{k:05d}"
    targets["hotspot"] = hid
    t = targets[targets["hotspot"] != ""]

    relief = config.HOTSPOT_RELIEF_TARGET_USED
    hs = t.groupby("hotspot").agg(
        naps=("nap_id", "size"), risk_naps=("level", lambda s: int((s == "Risk").sum())),
        high_naps=("level", lambda s: int((s == "High").sum())),
        used=("used", "sum"), ports_total=("ports_total", "sum"), available=("available", "sum"),
        lat=("lat", "mean"), lon=("lon", "mean"),
        ports_needed=("used", lambda s: int(np.clip(s - relief, 0, None).sum())),
        ports_per_nap=("ports_total", "median"),
        municipality=("municipality", lambda s: s.mode().iat[0]),
        barangay=("barangay", lambda s: s.mode().iat[0]),
        olts=("olt", lambda s: ", ".join(sorted(s.dropna().unique()))),
        lcps=("lcp", "nunique"),
    )
    hs["level"] = np.where(hs["risk_naps"] >= hs["high_naps"], "Risk", "High")
    hs["util_rate"] = hs["used"] / hs["ports_total"]
    hs["capacity_naps"] = np.ceil(hs["ports_needed"] / hs["ports_per_nap"]).astype(int)
    # radius: farthest member from the centroid
    d = haversine_m(t["lat"].to_numpy(), t["lon"].to_numpy(),
                    t["hotspot"].map(hs["lat"]).to_numpy(), t["hotspot"].map(hs["lon"]).to_numpy())
    hs["radius_m"] = pd.Series(d, index=t.index).groupby(t["hotspot"]).max().round(0)
    hs["small_group"] = hs["naps"] < config.HOTSPOT_MIN_NAPS
    return hs.reset_index()


def plan(ds) -> dict:
    naps = ds.naps.reset_index(drop=True).copy()
    ref = ds.reference_date
    cutoff = ref - pd.DateOffset(months=config.NEW_NAP_EXCLUSION_MONTHS)
    lcp_loc = ds.extra["lcp_sites"]

    # ---- candidates and exclusions -----------------------------------------
    low = naps[naps["level"] == "Low"].copy()
    reason = pd.Series("", index=low.index, dtype=object)
    reason[low["rfs_date"] > cutoff] = f"new NAP (RFS within {config.NEW_NAP_EXCLUSION_MONTHS} months)"
    if config.EXCLUDE_PLACEHOLDER_STACKS_FROM_RELOCATION:
        reason[(reason == "") & low["placeholder_stack"]] = "possible placeholder coordinate"
    if config.TARGET_SCOPE == "same_olt":
        reason[(reason == "") & low["olt"].isna()] = "OLT unknown"
    excluded = low[reason != ""].assign(reason=reason[reason != ""])
    cand = low[reason == ""].copy()

    # ---- targets and hotspots ---------------------------------------------
    tmask = naps["level"].isin(["Risk", "High"])
    if config.EXCLUDE_PLACEHOLDER_STACKS_FROM_RELOCATION:
        tmask &= ~naps["placeholder_stack"]
    targets = naps[tmask].copy()
    hotspots = build_hotspots(targets)
    targets = targets[targets["hotspot"] != ""]
    hs = hotspots.set_index("hotspot")
    cap_left = hs["capacity_naps"].to_dict()
    ports_left = hs["ports_needed"].astype(float).to_dict()
    hs_level = hs["level"].to_dict()

    t_tree = BallTree(_rad(targets), metric="haversine")

    # ---- Low NAPs already within drop reach of demand ----------------------
    near_d, near_i = t_tree.query(_rad(cand), k=1)
    near_d = near_d[:, 0] * R_EARTH
    near_i = near_i[:, 0]
    near = near_d <= config.DROP_REACH_M
    nt = targets.iloc[near_i]
    near_tbl = cand.assign(
        nearest_demand_nap=nt["nap_id"].to_numpy(), nearest_demand_level=nt["level"].to_numpy(),
        nearest_demand_hotspot=nt["hotspot"].to_numpy(), nearest_demand_m=near_d.round(1),
        nearest_demand_same_pole=near_d <= config.SAME_POLE_TOLERANCE_M)[near]
    supply = {}
    if config.NEAR_DEMAND_RULE == "keep":
        supply = near_tbl.groupby("nearest_demand_hotspot")["available"].sum().to_dict()
        for h, sp in supply.items():
            net = max(0.0, float(hs.at[h, "ports_needed"]) - sp)
            ports_left[h] = net
            cap_left[h] = int(math.ceil(net / hs.at[h, "ports_per_nap"]))
        cand = cand[~near]
    hotspots["idle_ports_within_reach"] = hotspots["hotspot"].map(supply).fillna(0).astype(int)
    hotspots["ports_needed_net"] = hotspots["hotspot"].map(ports_left).round(0).astype(int)
    hotspots["capacity_naps_net"] = hotspots["hotspot"].map(cap_left).astype(int)

    t_idx, t_dist = t_tree.query_radius(_rad(cand), r=config.MAX_RELOCATION_M / R_EARTH,
                                        return_distance=True, sort_results=True)
    T = {c: targets[c].to_numpy() for c in ["nap_id", "olt", "lcp", "hotspot", "pole_key", "lat", "lon", "level"]}

    # Sensitivity: how many candidates have any target under each scope rule.
    scope_counts = {"any": 0, "same_olt": 0, "same_lcp": 0}
    nearest_ok = np.full(len(cand), np.inf)
    c_olt, c_lcp = cand["olt"].to_numpy(), cand["lcp"].to_numpy()
    for k, (ix, dd) in enumerate(zip(t_idx, t_dist)):
        m = dd * R_EARTH > config.SAME_POLE_TOLERANCE_M
        ix, dd = ix[m], dd[m]
        if len(ix):
            scope_counts["any"] += 1
            so = T["olt"][ix] == c_olt[k]
            sl = T["lcp"][ix] == c_lcp[k]
            scope_counts["same_olt"] += bool(so.any())
            scope_counts["same_lcp"] += bool(sl.any())
            ok = {"any": np.ones(len(ix), bool), "same_olt": so, "same_lcp": sl}[config.TARGET_SCOPE]
            if ok.any():
                nearest_ok[k] = dd[ok].min() * R_EARTH
        t_idx[k], t_dist[k] = ix, dd

    # ---- re-homing subscribers of 1-2 used candidates -----------------------
    all_tree = BallTree(_rad(naps), metric="haversine")
    free = naps["available"].to_numpy().astype(int).copy()
    locked = np.zeros(len(naps), bool)      # absorbed subscribers: must stay put
    moved = np.zeros(len(naps), bool)
    pos = {n: i for i, n in enumerate(naps["nap_id"])}
    A = {c: naps[c].to_numpy() for c in ["nap_id", "lcp"]}

    def rehome(ci: int, need: int):
        i_self = pos[cand.at[ci, "nap_id"]]
        ix, dd = all_tree.query_radius(_rad(cand.loc[[ci]]), r=config.REHOME_MAX_M / R_EARTH,
                                       return_distance=True, sort_results=True)
        plan_, left = [], need
        for j, d in zip(ix[0], dd[0]):
            if j == i_self or moved[j] or free[j] <= 0:
                continue
            if config.REHOME_SAME_LCP_ONLY and A["lcp"][j] != cand.at[ci, "lcp"]:
                continue
            take = min(free[j], left)
            plan_.append((j, take, d * R_EARTH))
            left -= take
            if left == 0:
                return plan_
        return None

    # ---- greedy assignment -------------------------------------------------
    order = np.lexsort((nearest_ok, cand["used"].to_numpy()))
    pole_load: dict[str, int] = {}
    rows, unplaced = [], []
    cand_pos = cand.index.to_numpy()
    for k in order:
        ci = cand_pos[k]
        c = cand.loc[ci]
        ix, dd = t_idx[k], t_dist[k] * R_EARTH
        if len(ix) == 0:
            unplaced.append((ci, f"no Risk/High NAP within {config.MAX_RELOCATION_M} m"))
            continue
        ok = np.ones(len(ix), bool)
        if config.TARGET_SCOPE == "same_olt":
            ok &= T["olt"][ix] == c["olt"]
        elif config.TARGET_SCOPE == "same_lcp":
            ok &= T["lcp"][ix] == c["lcp"]
        if not ok.any():
            unplaced.append((ci, f"no Risk/High NAP within {config.MAX_RELOCATION_M} m on the same "
                                 f"{'OLT' if config.TARGET_SCOPE == 'same_olt' else 'LCP'}"))
            continue
        ok &= np.array([cap_left[h] > 0 for h in T["hotspot"][ix]])
        if not ok.any():
            unplaced.append((ci, "nearby hotspots already have enough relocated NAPs"))
            continue
        ok &= np.array([pole_load.get(p, 0) < config.MAX_NEW_NAPS_PER_TARGET_POLE for p in T["pole_key"][ix]])
        if not ok.any():
            unplaced.append((ci, "nearby target poles already receive the maximum relocated NAPs"))
            continue
        cix, cdd = ix[ok], dd[ok]
        same_lcp = T["lcp"][cix] == c["lcp"]
        risk_first = np.array([hs_level[h] != "Risk" for h in T["hotspot"][cix]])
        lcp_key = ~same_lcp if config.PREFER_SAME_LCP else np.zeros(len(cix), bool)
        best = np.lexsort((cdd, lcp_key, risk_first))[0]
        j, dist = cix[best], float(cdd[best])

        i_self = pos[c["nap_id"]]
        if locked[i_self]:  # it already absorbed subscribers from another moved NAP
            unplaced.append((ci, "kept in place: it takes re-homed subscribers from another moved NAP"))
            continue
        rh = []
        if c["used"] > 0 and config.REQUIRE_SUBSCRIBER_REHOME:
            rh = rehome(ci, int(c["used"]))
            if rh is None:
                unplaced.append((ci, f"no NAP within {config.REHOME_MAX_M} m"
                                     f"{' on the same LCP' if config.REHOME_SAME_LCP_ONLY else ''}"
                                     f" can take its {int(c['used'])} subscriber(s)"))
                continue
            for jj, take, _ in rh:
                free[jj] -= take
                locked[jj] = True
        moved[i_self] = True

        h = T["hotspot"][j]
        cap_left[h] -= 1
        gain = min(float(c["ports_total"]), ports_left[h])
        ports_left[h] -= gain
        pole_load[T["pole_key"][j]] = pole_load.get(T["pole_key"][j], 0) + 1
        lcp_lat, lcp_lon = lcp_loc.at[c["lcp"], "lat"], lcp_loc.at[c["lcp"], "lon"]
        rows.append({
            "nap_id": c["nap_id"], "lcp": c["lcp"], "olt": c["olt"], "pon": c["pon"],
            "barangay": c["barangay"], "municipality": c["municipality"], "lat": c["lat"], "lon": c["lon"],
            "used_ports": int(c["used"]), "available_ports": int(c["available"]), "ports_total": int(c["ports_total"]),
            "rfs_date": c["rfs_date"], "olt_inferred": bool(c["olt_inferred"]),
            "target_hotspot": h, "target_level": hs_level[h],
            "hotspot_naps": int(hs.at[h, "naps"]), "hotspot_risk_naps": int(hs.at[h, "risk_naps"]),
            "hotspot_high_naps": int(hs.at[h, "high_naps"]),
            "hotspot_lat": hs.at[h, "lat"], "hotspot_lon": hs.at[h, "lon"],
            "target_nap": T["nap_id"][j], "target_nap_level": T["level"][j],
            "target_lat": T["lat"][j], "target_lon": T["lon"][j],
            "target_olt": T["olt"][j], "target_lcp": T["lcp"][j],
            "distance_m": round(dist, 1), "same_lcp": bool(T["lcp"][j] == c["lcp"]),
            "same_olt": bool(T["olt"][j] == c["olt"]),
            "lcp_to_target_m": round(float(haversine_m(lcp_lat, lcp_lon, T["lat"][j], T["lon"][j])), 1),
            "new_sellable_ports": int(c["ports_total"]),
            "idle_ports_redeployed": int(c["available"]),
            "subscribers_to_rehome": int(c["used"]),
            "rehome_to": "; ".join(f"{A['nap_id'][jj]} ({take} port{'s' if take > 1 else ''}, {d:.0f} m)" for jj, take, d in rh),
            "potential_subscriber_gain": int(gain),
            "within_drop_reach": dist < config.DROP_REACH_M,
        })

    rec = pd.DataFrame(rows)
    if len(rec):
        rec["_risk"] = rec["target_level"] != "Risk"
        rec["_lcp"] = ~rec["same_lcp"]
        rec = rec.sort_values(["used_ports", "_risk", "_lcp", "distance_m"]).drop(columns=["_risk", "_lcp"])
        rec.insert(0, "priority_rank", range(1, len(rec) + 1))
        rec["priority_group"] = rec["used_ports"].map({0: "1 - idle (0 used)", 1: "2 - 1 used", 2: "3 - 2 used"})
        notes = []
        for r in rec.itertuples():
            n = []
            if r.within_drop_reach:
                n.append(f"target < {config.DROP_REACH_M} m away: demand may already be within drop reach")
            if r.olt_inferred:
                n.append("OLT inferred from Tableau")
            if r.subscribers_to_rehome:
                n.append(f"re-home {r.subscribers_to_rehome} subscriber(s) first")
            notes.append("; ".join(n))
        rec["notes"] = notes

    un = pd.DataFrame(unplaced, columns=["idx", "reason"]).set_index("idx")
    not_placed = cand.loc[un.index].assign(reason=un["reason"])
    keep = ["nap_id", "lcp", "olt", "pon", "municipality", "barangay", "lat", "lon", "used", "rfs_date", "reason"]
    not_moved = pd.concat([not_placed[keep], excluded[keep]]).sort_values(["reason", "nap_id"])

    hs_out = hotspots.copy()
    hs_out["relocated_naps_assigned"] = hs_out["hotspot"].map(rec["target_hotspot"].value_counts() if len(rec) else {}).fillna(0).astype(int)
    hs_out["ports_still_needed"] = hs_out["hotspot"].map(ports_left).round(0).astype(int)

    stats = {
        "Low NAPs": len(low),
        f"  excluded: new (RFS within {config.NEW_NAP_EXCLUSION_MONTHS} months)": int(excluded["reason"].str.startswith("new NAP").sum()),
        "  excluded: possible placeholder coordinate": int((excluded["reason"] == "possible placeholder coordinate").sum()),
        "  excluded: OLT unknown": int((excluded["reason"] == "OLT unknown").sum()),
        f"Low NAPs with Risk/High demand within {config.DROP_REACH_M} m (drop reach)": int(near.sum()),
        "  of which on the same pole as demand": int(near_tbl["nearest_demand_same_pole"].sum()),
        "  handling": ("kept in place: sell from existing NAP" if config.NEAR_DEMAND_RULE == "keep"
                       else "treated as relocation candidates"),
        "Relocation candidates considered": len(cand),
        f"  with a Risk/High NAP within {config.MAX_RELOCATION_M} m (any OLT / same OLT / same LCP)":
            f"{scope_counts['any']:,} / {scope_counts['same_olt']:,} / {scope_counts['same_lcp']:,}",
        "Demand hotspots (Risk/High groups)": len(hotspots),
        "  hotspot capacity before idle supply nearby (NAPs)": int(hotspots["capacity_naps"].sum()),
        "  hotspot capacity after idle supply nearby (NAPs)": int(hotspots["capacity_naps_net"].sum()),
        "Recommended relocations": len(rec),
        "  by used ports (0 / 1 / 2)": " / ".join(str(int((rec["used_ports"] == u).sum())) if len(rec) else "0" for u in (0, 1, 2)),
        "  to Risk / High hotspots": (f"{int((rec['target_level'] == 'Risk').sum()):,} / {int((rec['target_level'] == 'High').sum()):,}"
                                      if len(rec) else "0 / 0"),
        "  on the same LCP as the target": int(rec["same_lcp"].sum()) if len(rec) else 0,
        "  median distance (m)": round(float(rec["distance_m"].median()), 0) if len(rec) else 0,
        "  new sellable ports at targets": int(rec["new_sellable_ports"].sum()) if len(rec) else 0,
        "  potential subscriber gain (capped by hotspot demand)": int(rec["potential_subscriber_gain"].sum()) if len(rec) else 0,
        "  subscribers to re-home first": int(rec["subscribers_to_rehome"].sum()) if len(rec) else 0,
        "Candidates not placed": len(not_placed),
    }
    for r_, c_ in not_placed["reason"].value_counts().items():
        stats[f"  not placed: {r_}"] = int(c_)

    sell_cols = ["nap_id", "lcp", "olt", "pon", "municipality", "barangay", "lat", "lon", "used", "available",
                 "rfs_date", "nearest_demand_nap", "nearest_demand_level", "nearest_demand_m",
                 "nearest_demand_same_pole", "nearest_demand_hotspot"]
    sell = near_tbl[sell_cols].sort_values(["used", "nearest_demand_m"]) if config.NEAR_DEMAND_RULE == "keep" \
        else near_tbl[sell_cols].iloc[0:0]
    return {"recommendations": rec, "hotspots": hs_out, "not_moved": not_moved, "stats": stats,
            "sell_from_existing": sell,
            "summary_from": _summary(rec, "municipality", "barangay"),
            "summary_to": _summary_to(rec, hotspots)}


def _agg(g):
    return g.agg(naps_movable=("nap_id", "size"),
                 idle_ports_redeployed=("idle_ports_redeployed", "sum"),
                 subscribers_to_rehome=("subscribers_to_rehome", "sum"),
                 new_sellable_ports=("new_sellable_ports", "sum"),
                 potential_subscriber_gain=("potential_subscriber_gain", "sum"),
                 zero_used=("used_ports", lambda s: int((s == 0).sum())))


def _summary(rec: pd.DataFrame, mcol: str, bcol: str) -> dict:
    if not len(rec):
        return {"municipality": pd.DataFrame(), "barangay": pd.DataFrame()}
    m = _agg(rec.groupby(mcol)).sort_values("naps_movable", ascending=False).reset_index()
    b = _agg(rec.groupby([mcol, bcol])).sort_values("naps_movable", ascending=False).reset_index()
    return {"municipality": m, "barangay": b}


def _summary_to(rec: pd.DataFrame, hotspots: pd.DataFrame) -> dict:
    if not len(rec):
        return {"municipality": pd.DataFrame(), "barangay": pd.DataFrame()}
    h = hotspots.set_index("hotspot")
    r = rec.assign(target_municipality=rec["target_hotspot"].map(h["municipality"]),
                   target_barangay=rec["target_hotspot"].map(h["barangay"]))
    return _summary(r, "target_municipality", "target_barangay")
