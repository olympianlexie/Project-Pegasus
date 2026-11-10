"""Reconcile the raw NAP table with the Tableau export, fill blank OLTs, and collect data-quality issues."""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import config
from .aggregate import haversine_m, olt_level


def _fold(s: pd.Series) -> pd.Series:
    """Upper-case and treat Ñ as N (site codes use BÑL, OLT IDs use BNL)."""
    return s.astype("string").str.upper().str.replace("Ñ", "N", regex=False)


def olt_renumber_map(naps: pd.DataFrame, t2: pd.DataFrame) -> pd.DataFrame:
    """For each Tableau OLT, which raw OLT its NAPs are on now."""
    j = naps[["nap_id", "olt_raw"]].merge(t2[["Nap Id", "Olt Id"]], left_on="nap_id", right_on="Nap Id")
    j = j.dropna(subset=["olt_raw"])
    ct = j.groupby(["Olt Id", "olt_raw"]).size().rename("naps").reset_index()
    tot = ct.groupby("Olt Id")["naps"].transform("sum")
    ct["share_of_tableau_olt"] = ct["naps"] / tot
    ct = ct.sort_values(["Olt Id", "naps"], ascending=[True, False])
    ct["dominant"] = ~ct.duplicated("Olt Id") & (ct["share_of_tableau_olt"] >= config.OLT_RENUMBER_MIN_SHARE)
    ct["renumbered"] = ct["Olt Id"] != ct["olt_raw"]
    return ct.rename(columns={"Olt Id": "tableau_olt", "olt_raw": "raw_olt"}).reset_index(drop=True)


def reconcile(naps: pd.DataFrame, ports: pd.DataFrame, tab: dict) -> tuple[pd.DataFrame, dict]:
    t1, t2 = tab["sheet1"], tab["sheet2"]
    rec: dict[str, pd.DataFrame] = {}

    naps = naps.copy()
    t2i = t2.set_index("Nap Id")
    naps["in_tableau"] = naps["nap_id"].isin(t2i.index)
    naps["tableau_olt"] = naps["nap_id"].map(t2i["Olt Id"])
    naps["tableau_used"] = naps["nap_id"].map(t2i["UTILIZED PORTS"])
    naps["tableau_level"] = naps["nap_id"].map(t2i["level"])
    naps["tableau_distance_km"] = naps["nap_id"].map(t2i["NAP-OLT Distance (km)"])

    # --- OLT renumbering and blank-OLT inference ------------------------------
    rmap = olt_renumber_map(naps, t2)
    rec["olt_renumbering"] = rmap
    dom = rmap[rmap["dominant"]].set_index("tableau_olt")["raw_olt"]

    naps["olt"] = naps["olt_raw"]
    naps["olt_inferred"] = False
    naps["olt_source"] = np.where(naps["olt_raw"].notna(), "raw file", "")
    naps["pon_inferred"] = False
    blank = naps["olt"].isna()

    # 1) Other NAPs on the same LCP that do have an OLT (an LCP is always on one OLT/PON).
    known = naps[~blank].groupby("lcp").agg(o=("olt", "unique"), p=("pon", "unique"))
    for i in naps.index[blank]:
        lcp = naps.at[i, "lcp"]
        if lcp in known.index and len(known.at[lcp, "o"]) == 1:
            naps.at[i, "olt"] = known.at[lcp, "o"][0]
            naps.at[i, "olt_source"] = "inferred: same-LCP NAPs"
            pons = [p for p in known.at[lcp, "p"] if pd.notna(p)]
            if pd.isna(naps.at[i, "pon"]) and len(pons) == 1:
                naps.at[i, "pon"] = pons[0]
                naps.at[i, "pon_inferred"] = True
    # 2) Tableau's OLT, translated to the current (raw) numbering.
    blank = naps["olt"].isna()
    for i in naps.index[blank]:
        t = naps.at[i, "tableau_olt"]
        if pd.isna(t):
            continue
        cur = dom.get(t, t if t in set(naps["olt_raw"].dropna()) else None)
        if cur is None:
            continue
        naps.at[i, "olt"] = cur
        naps.at[i, "olt_source"] = f"inferred: Tableau {t}" + (f" (renumbered to {cur})" if cur != t else "")
    naps["olt_inferred"] = naps["olt_raw"].isna() & naps["olt"].notna()

    rec["olt_inferred"] = naps.loc[naps["olt_raw"].isna(), [
        "nap_id", "lcp", "municipality", "barangay", "tableau_olt", "olt", "olt_source", "pon", "pon_inferred"]
    ].rename(columns={"olt": "olt_used", "pon": "pon_used"})

    # --- Cross-fed: NAP site prefix differs from its OLT's prefix ---------------
    olt_prefix = naps["olt"].astype("string").str.split("-").str[0]
    naps["cross_fed"] = naps["olt"].notna() & (_fold(naps["site"]) != _fold(olt_prefix))
    naps["prefix_spelling_only"] = (naps["olt"].notna() & (naps["site"].str.upper() != olt_prefix.str.upper())
                                    & ~naps["cross_fed"])

    # --- Level comparison with Tableau ---------------------------------------
    naps["level_matches_tableau"] = np.where(naps["in_tableau"], naps["level"] == naps["tableau_level"], pd.NA)
    naps["used_matches_tableau"] = np.where(naps["in_tableau"], naps["used"] == naps["tableau_used"], pd.NA)

    rec["new_naps"] = naps.loc[~naps["in_tableau"], [
        "nap_id", "lcp", "olt", "pon", "municipality", "barangay", "lat", "lon", "rfs_date", "used", "ports_total", "level"]]
    rec["missing_from_raw"] = pd.DataFrame({"Nap Id": sorted(set(t2["Nap Id"]) - set(naps["nap_id"]))})
    rec["level_mismatch"] = naps.loc[naps["in_tableau"] & (naps["level"] != naps["tableau_level"]), [
        "nap_id", "olt", "municipality", "used", "level", "tableau_used", "tableau_level", "active", "allocated", "reserved"]]
    rec["level_crosstab"] = pd.crosstab(naps.loc[naps["in_tableau"], "level"],
                                        naps.loc[naps["in_tableau"], "tableau_level"],
                                        rownames=["raw level"], colnames=["Tableau level"]).reset_index()

    # --- Sheet 1: OLT x municipality, compared in current (raw) OLT numbering ---
    s1 = t1[~t1["stray_single_port_row"]].copy()
    s1["raw_olt"] = s1["Olt Id"].map(dom).fillna(s1["Olt Id"])
    tab_om = s1.groupby(["raw_olt", "z MUNICIPALITYNAME"]).agg(
        tableau_olt_ids=("Olt Id", lambda s: ", ".join(sorted(s.unique()))),
        tableau_deployed=("DEPLOYED PORTS", "sum"), tableau_utilized=("UTILIZED PORTS", "sum"),
        tableau_levels=("level", lambda s: ", ".join(sorted(s.unique()))))
    raw_om = naps.dropna(subset=["olt"]).groupby(["olt", "municipality"]).agg(
        raw_deployed=("ports_total", "sum"), raw_utilized=("used", "sum"))
    raw_om.index.names = ["raw_olt", "z MUNICIPALITYNAME"]
    om = raw_om.join(tab_om, how="outer").reset_index().rename(columns={"z MUNICIPALITYNAME": "municipality"})
    om["raw_rate"] = om["raw_utilized"] / om["raw_deployed"]
    om["tableau_rate"] = om["tableau_utilized"] / om["tableau_deployed"]
    om["raw_level"] = olt_level(om["raw_rate"])
    om["deployed_diff"] = om["raw_deployed"].fillna(0) - om["tableau_deployed"].fillna(0)
    om["utilized_diff"] = om["raw_utilized"].fillna(0) - om["tableau_utilized"].fillna(0)
    rec["olt_municipality"] = om
    rec["tableau_stray_rows"] = t1[t1["stray_single_port_row"]].drop(columns=["stray_single_port_row"])

    rec["summary"] = pd.DataFrame([
        ("NAPs in raw file", len(naps)),
        ("NAPs in Tableau Sheet 2", t2["Nap Id"].nunique()),
        ("Tableau NAPs found in raw", int(naps["in_tableau"].sum())),
        ("Tableau NAPs missing from raw", len(rec["missing_from_raw"])),
        ("New NAPs (raw only)", len(rec["new_naps"])),
        ("Utilized ports equal Tableau (% of matched NAPs)", round(100 * naps.loc[naps["in_tableau"], "used"].eq(
            naps.loc[naps["in_tableau"], "tableau_used"]).mean(), 2)),
        ("Level equals Tableau (% of matched NAPs)", round(100 * naps.loc[naps["in_tableau"], "level"].eq(
            naps.loc[naps["in_tableau"], "tableau_level"]).mean(), 2)),
        ("Level differs from Tableau (NAPs)", len(rec["level_mismatch"])),
        ("OLTs in raw (non-blank)", naps["olt_raw"].nunique()),
        ("OLTs in Tableau Sheet 1", t1["Olt Id"].nunique()),
        ("Tableau OLT IDs renumbered in raw", ", ".join(
            f"{r.tableau_olt} -> {r.raw_olt}" for r in rmap[rmap["dominant"] & rmap["renumbered"]].itertuples())),
        ("NAPs with blank OLT in raw", int(naps["olt_raw"].isna().sum())),
        ("  of which OLT inferred", int(naps["olt_inferred"].sum())),
        ("Tableau Sheet 1 stray single-port rows", len(rec["tableau_stray_rows"])),
    ], columns=["check", "value"])
    return naps, rec


def data_quality(naps: pd.DataFrame, ports: pd.DataFrame) -> dict:
    dq: dict[str, pd.DataFrame] = {}
    st = ports["Port Status"]
    acct = ports["Account Number"]
    cols = ["Poi Full Assignment", "Poi Name", "Olt Id", "z MUNICIPALITYNAME", "z BARANGAYNAME",
            "Port Number", "Port Status", "Account Number"]
    dq["active_no_account"] = ports.loc[st.eq("ACTIVE") & acct.isna(), cols]
    dq["inactive_with_account"] = ports.loc[~st.eq("ACTIVE") & acct.notna(), cols]
    # Normal formats seen: 12 digits, 13 digits, or 7 digits + letter + 5 digits (1919102E78432).
    normal = acct.str.fullmatch(r"\d{12,13}|\d{7}[A-Z]\d{5}").fillna(False).astype(bool)
    dq["odd_account_numbers"] = ports.loc[acct.notna() & ~normal, cols]

    stacks = naps[naps["placeholder_stack"]].groupby("pole_key").agg(
        naps=("nap_id", "size"), lat=("lat", "first"), lon=("lon", "first"),
        municipality=("municipality", lambda s: ", ".join(sorted(s.unique()))),
        barangay=("barangay", lambda s: ", ".join(sorted(s.unique()))),
        lcps=("lcp", lambda s: ", ".join(sorted(s.unique()))),
        olts=("olt", lambda s: ", ".join(sorted(s.dropna().unique()))),
        nap_ids=("nap_id", lambda s: ", ".join(sorted(s))))
    dq["placeholder_stacks"] = stacks.sort_values("naps", ascending=False).reset_index(drop=True)
    dq["stack_size_counts"] = (naps.groupby("pole_key").size().value_counts().sort_index()
                               .rename_axis("NAPs at one coordinate").rename("locations").reset_index())
    dq["cross_fed"] = naps.loc[naps["cross_fed"], ["nap_id", "site", "olt", "olt_source", "pon", "municipality", "barangay"]]
    dq["olt_inferred"] = naps.loc[naps["olt_raw"].isna(), ["nap_id", "lcp", "municipality", "barangay",
                                                            "tableau_olt", "olt", "olt_source", "pon"]]
    dq["pon_unknown"] = naps.loc[naps["pon"].isna(), ["nap_id", "lcp", "olt", "olt_source", "municipality"]]
    rng = naps["lat"].between(13.5, 15.0) & naps["lon"].between(120.5, 122.0)
    dq["coords_outside_laguna_box"] = naps.loc[~rng, ["nap_id", "lat", "lon", "municipality"]]
    dq["unmatched_barangays"] = naps.loc[naps["barangay_feature"].isna(), ["municipality", "barangay"]] \
        .value_counts().rename("naps").reset_index() if "barangay_feature" in naps else pd.DataFrame()

    dq["summary"] = pd.DataFrame([
        ("Port rows", len(ports)),
        ("ACTIVE ports with no account number", len(dq["active_no_account"])),
        ("Non-active ports with an account number", len(dq["inactive_with_account"])),
        ("Account numbers with an unusual format", len(dq["odd_account_numbers"])),
        ("NAPs with blank OLT ID (OLT inferred)", len(dq["olt_inferred"])),
        ("NAPs with no PON port", len(dq["pon_unknown"])),
        (f"Coordinates shared by more than {config.STACK_FLAG_THRESHOLD} NAPs (possible placeholders)",
         len(dq["placeholder_stacks"])),
        ("  NAPs at those coordinates", int(dq["placeholder_stacks"]["naps"].sum()) if len(stacks) else 0),
        ("Distinct NAP coordinates", naps["pole_key"].nunique()),
        ("Cross-fed NAPs (site prefix differs from OLT prefix, Ñ = N)", len(dq["cross_fed"])),
        ("NAPs whose prefix differs only by Ñ/N spelling (not cross-fed)", int(naps["prefix_spelling_only"].sum())),
        ("NAPs outside the Laguna bounding box", len(dq["coords_outside_laguna_box"])),
        ("Barangay names not matched to a PSGC polygon (distinct)", len(dq["unmatched_barangays"])),
    ], columns=["issue", "count"])
    return dq


def add_olt_distance(naps: pd.DataFrame, olts: pd.DataFrame) -> pd.DataFrame:
    o = olts.set_index("olt")
    olat = naps["olt"].map(o["lat"])
    olon = naps["olt"].map(o["lon"])
    est = haversine_m(naps["lat"], naps["lon"], olat, olon) / 1000
    naps["olt_distance_km"] = naps["tableau_distance_km"].fillna(est)
    naps["olt_distance_source"] = np.where(
        naps["tableau_distance_km"].notna(), "Tableau",
        np.where(est.notna(), "estimated (straight line to approximate OLT location)", "unknown"))
    return naps
