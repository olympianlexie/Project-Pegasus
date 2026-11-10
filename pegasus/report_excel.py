"""Excel outputs: the relocation plan workbook (with data-quality and reconciliation
sheets) and a full NAP / OLT / PON table workbook."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from . import config

HEADER_FILL = PatternFill("solid", fgColor="1F3A5F")
LEVEL_FILL = {L: PatternFill("solid", fgColor=c.lstrip("#")) for L, c in config.LEVEL_COLORS.items()}

REC_COLUMNS = {
    "priority_rank": "Priority rank", "priority_group": "Priority group",
    "nap_id": "Candidate NAP ID", "lcp": "LCP", "olt": "OLT", "pon": "PON port",
    "barangay": "Barangay", "municipality": "Municipality", "lat": "Latitude", "lon": "Longitude",
    "used_ports": "Used ports", "available_ports": "Available ports", "rfs_date": "RFS date",
    "target_hotspot": "Target hotspot", "target_level": "Target level",
    "hotspot_naps": "Hotspot NAPs", "hotspot_risk_naps": "Hotspot Risk NAPs", "hotspot_high_naps": "Hotspot High NAPs",
    "target_nap": "Target NAP (nearest pole)", "target_nap_level": "Target NAP level",
    "target_lat": "Target latitude", "target_lon": "Target longitude",
    "hotspot_lat": "Hotspot centre latitude", "hotspot_lon": "Hotspot centre longitude",
    "distance_m": "Distance (m)", "same_lcp": "Target on same LCP", "same_olt": "Target on same OLT",
    "target_lcp": "Target LCP", "target_olt": "Target OLT",
    "lcp_to_target_m": "LCP to target (m, approx.)",
    "new_sellable_ports": "New sellable ports", "idle_ports_redeployed": "Idle ports redeployed",
    "subscribers_to_rehome": "Subscribers to re-home", "rehome_to": "Re-home subscribers to",
    "potential_subscriber_gain": "Potential subscriber gain", "olt_inferred": "OLT inferred",
    "within_drop_reach": "Within drop reach", "notes": "Notes",
}


def _write(writer, name: str, df: pd.DataFrame, level_cols: tuple[str, ...] = (), note: str | None = None):
    df = df.copy()
    for c in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[c]):
            df[c] = df[c].dt.date
        elif str(df[c].dtype) in ("string", "Int64", "boolean"):
            df[c] = df[c].astype(object).where(df[c].notna(), None)
    start = 2 if note else 0
    df.to_excel(writer, sheet_name=name[:31], index=False, startrow=start)
    ws = writer.sheets[name[:31]]
    if note:
        ws.cell(row=1, column=1, value=note).font = Font(italic=True, color="555555")
    hr = start + 1
    for j, col in enumerate(df.columns, 1):
        c = ws.cell(row=hr, column=j)
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = HEADER_FILL
        c.alignment = Alignment(wrap_text=True, vertical="top")
        width = max([len(str(col))] + [len(str(v)) for v in df[col].head(300)])
        ws.column_dimensions[get_column_letter(j)].width = min(max(9, width + 2), 60)
    ws.freeze_panes = ws.cell(row=hr + 1, column=1)
    if len(df):
        ws.auto_filter.ref = f"A{hr}:{get_column_letter(len(df.columns))}{hr + len(df)}"
    for lc in level_cols:
        if lc not in df.columns or len(df) > 60000:
            continue
        j = list(df.columns).index(lc) + 1
        for i, v in enumerate(df[lc], hr + 1):
            if v in LEVEL_FILL:
                cell = ws.cell(row=i, column=j)
                cell.fill = LEVEL_FILL[v]
                cell.font = Font(color="FFFFFF", bold=True)


def _about(ds, reloc: dict) -> pd.DataFrame:
    rows = [
        ("Built", pd.Timestamp.now().strftime("%Y-%m-%d %H:%M")),
        ("Raw file", ds.raw_path.name),
        ("Tableau file", ds.tableau_path.name if ds.tableau_path else "(not found)"),
        ("Run date used for RFS age", str(ds.reference_date.date())),
        ("", ""),
        ("SETTINGS (pegasus/config.py)", ""),
        ("Utilized ports", " + ".join(sorted(config.UTILIZED_STATUSES))),
        ("NAP levels (8-port NAP)", "Low 0-2 used, Optimal 3-4, High 5-6, Risk 7-8"),
        ("Max relocation distance (m)", config.MAX_RELOCATION_M),
        ("Fiber rule", "relocated NAP stays on its own LCP/PON; cable re-routed or extended"),
        ("Target scope", config.TARGET_SCOPE),
        ("Prefer same LCP", config.PREFER_SAME_LCP),
        ("Skip NAPs RFS'd within (months)", config.NEW_NAP_EXCLUSION_MONTHS),
        ("Drop reach (m)", config.DROP_REACH_M),
        ("Low NAPs with demand within drop reach", config.NEAR_DEMAND_RULE +
         (" = kept in place (Sell_From_Existing sheet); their idle ports reduce the hotspot's need"
          if config.NEAR_DEMAND_RULE == "keep" else " = treated as relocation candidates")),
        ("Hotspots", f"DBSCAN, {config.HOTSPOT_EPS_M} m, min {config.HOTSPOT_MIN_NAPS} NAPs, split above "
                     f"{config.HOTSPOT_MAX_RADIUS_M} m radius; single-pole groups included: {config.INCLUDE_SINGLE_NAP_HOTSPOTS}"),
        ("Hotspot capacity", f"ports needed to bring each Risk/High NAP down to {config.HOTSPOT_RELIEF_TARGET_USED} used, "
                             "÷ ports per NAP, rounded up"),
        ("Re-home subscribers", f"required: {config.REQUIRE_SUBSCRIBER_REHOME}, within {config.REHOME_MAX_M} m, "
                                f"same LCP only: {config.REHOME_SAME_LCP_ONLY}"),
        ("Max relocated NAPs per target pole", config.MAX_NEW_NAPS_PER_TARGET_POLE),
        ("Placeholder stacks excluded", f"{config.EXCLUDE_PLACEHOLDER_STACKS_FROM_RELOCATION} (> {config.STACK_FLAG_THRESHOLD} NAPs at one coordinate)"),
        ("", ""),
        ("RESULTS", ""),
    ]
    rows += [(k, v) for k, v in reloc["stats"].items()]
    rows += [("", ""), ("COLUMN NOTES", ""),
             ("New sellable ports", "all ports of the moved NAP (its current subscribers are re-homed first)"),
             ("Idle ports redeployed", "ports AVAILABLE today on the candidate, moved from a low-demand to a high-demand area"),
             ("Potential subscriber gain", "new sellable ports, capped by the hotspot's remaining need"),
             ("Target NAP", "nearest Risk/High NAP of the hotspot: a concrete pole to move to; the hotspot centre is also given")]
    return pd.DataFrame(rows, columns=["Item", "Value"])


def write_relocation_workbook(ds, reloc: dict, path: Path) -> Path:
    rec = reloc["recommendations"]
    rec_out = rec[[c for c in REC_COLUMNS if c in rec.columns]].rename(columns=REC_COLUMNS) if len(rec) else rec
    with pd.ExcelWriter(path, engine="openpyxl") as w:
        _write(w, "About", _about(ds, reloc))
        _write(w, "Recommendations", rec_out, ("Target level", "Target NAP level"),
               note="One row per Low NAP recommended for relocation, in priority order "
                    "(0 used ports first, then 1, then 2; Risk targets before High; same LCP preferred; shorter first).")
        _write(w, "Sell_From_Existing", reloc["sell_from_existing"].rename(columns={"used": "used_ports", "available": "available_ports"}),
               ("nearest_demand_level",),
               note=f"Low NAPs with Risk/High demand within {config.DROP_REACH_M} m (drop reach). Not relocated: "
                    "connect new subscribers in the nearby hotspot to these NAPs first.")
        _write(w, "Hotspots", reloc["hotspots"].sort_values(["relocated_naps_assigned", "ports_needed_net"], ascending=False),
               ("level",), note="Demand hotspots: groups of Risk/High NAPs. ports_needed = ports to bring every NAP down to "
                                f"{config.HOTSPOT_RELIEF_TARGET_USED} used; _net subtracts idle ports on Low NAPs within reach.")
        _write(w, "Summary_From_Municipality", reloc["summary_from"]["municipality"],
               note="By where the candidate NAP is today. idle_ports_redeployed = ports freed from low-demand areas.")
        _write(w, "Summary_From_Barangay", reloc["summary_from"]["barangay"])
        _write(w, "Summary_To_Municipality", reloc["summary_to"]["municipality"],
               note="By the hotspot that receives the NAP (where subscribers can be gained).")
        _write(w, "Summary_To_Barangay", reloc["summary_to"]["barangay"])
        _write(w, "Not_Relocated", reloc["not_moved"], note="Low NAPs that were excluded or could not be placed, with the reason.")

        dq = ds.dq
        _write(w, "DQ_Summary", dq["summary"])
        _write(w, "DQ_OLT_Inferred", dq["olt_inferred"], note="Blank OLT ID in the raw file; OLT filled from Tableau (translated to current numbering).")
        _write(w, "DQ_Placeholder_Stacks", dq["placeholder_stacks"],
               note=f"Coordinates shared by more than {config.STACK_FLAG_THRESHOLD} NAPs: possible placeholder locations.")
        _write(w, "DQ_Stack_Sizes", dq["stack_size_counts"])
        _write(w, "DQ_Active_No_Account", dq["active_no_account"])
        _write(w, "DQ_Inactive_With_Account", dq["inactive_with_account"])
        _write(w, "DQ_Odd_Account_Numbers", dq["odd_account_numbers"],
               note="Account numbers that are not 12-13 digits or 7 digits + letter + 5 digits.")
        _write(w, "DQ_Cross_Fed", dq["cross_fed"], note="NAP site prefix differs from its OLT's prefix (Ñ treated as N). Not an error.")
        _write(w, "DQ_PON_Unknown", dq["pon_unknown"])
        _write(w, "DQ_Unmatched_Barangays", dq["unmatched_barangays"],
               note="Barangay names with no PSGC polygon. Add them to boundaries/barangay_aliases.csv.")

        rc = ds.recon
        if rc:
            _write(w, "Recon_Summary", rc["summary"])
            _write(w, "Recon_OLT_Renumbering", rc["olt_renumbering"],
                   note="Tableau OLT -> raw OLT, from NAP overlap. Raw IDs are treated as current.")
            _write(w, "Recon_New_NAPs", rc["new_naps"], ("level",), note="NAPs in the raw file but not in the Tableau export.")
            _write(w, "Recon_Missing_From_Raw", rc["missing_from_raw"])
            _write(w, "Recon_Level_Mismatch", rc["level_mismatch"], ("level", "tableau_level"))
            _write(w, "Recon_Level_Crosstab", rc["level_crosstab"])
            _write(w, "Recon_OLT_Municipality", rc["olt_municipality"],
                   note="Tableau Sheet 1 (OLT x municipality), mapped to current OLT IDs, vs the raw file.")
            _write(w, "Recon_Tableau_Stray_Rows", rc["tableau_stray_rows"],
                   note="Single-port rows at the end of Tableau Sheet 1 (have a Lcp Port value). Excluded from the comparison.")
    return path


def write_nap_workbook(ds, path: Path) -> Path:
    n = ds.naps
    cols = ["nap_id", "site", "lcp", "np", "olt", "olt_source", "pon", "municipality", "barangay", "lat", "lon",
            "rfs_date", "ports_total", "used", "available", "active", "allocated", "reserved", "util_pct", "level",
            "port_codes", "olt_distance_km", "olt_distance_source", "pole_count", "placeholder_stack", "cross_fed",
            "in_tableau", "tableau_olt", "tableau_used", "tableau_level", "active_no_account", "inactive_with_account"]
    with pd.ExcelWriter(path, engine="openpyxl") as w:
        _write(w, "NAPs", n[cols].sort_values(["municipality", "barangay", "nap_id"]),
               note="One row per NAP. port_codes: port 1..8 status (A active, V available, L allocated, R reserved).")
        _write(w, "OLTs", ds.olts.sort_values("olt"), ("level",))
        _write(w, "PONs", ds.pons.sort_values(["olt", "pon"]))
        from .aggregate import area_summary
        _write(w, "Municipalities", area_summary(n, ["municipality"]).sort_values("municipality"))
        _write(w, "Barangays", area_summary(n, ["municipality", "barangay"]).sort_values(["municipality", "barangay"]))
    return path
