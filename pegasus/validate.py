"""Validation report printed on every run (and saved to output/validation_report.txt)."""
from __future__ import annotations

import pandas as pd

from . import config


def _fmt(n) -> str:
    return f"{n:,}" if isinstance(n, (int,)) or (hasattr(n, "is_integer") and float(n).is_integer()) else str(n)


def report(ds, reloc: dict | None = None) -> tuple[str, list[str]]:
    """Returns (report text, list of FAILED invariant checks)."""
    p, n, o = ds.ports, ds.naps, ds.olts
    lines, fails = [], []

    def h(t):
        lines.append("")
        lines.append(t)
        lines.append("-" * len(t))

    def check(ok: bool, msg: str):
        lines.append(f"  [{'OK' if ok else 'FAIL'}] {msg}")
        if not ok:
            fails.append(msg)

    lines.append("PROJECT PEGASUS - VALIDATION REPORT")
    lines.append(f"Raw file:     {ds.raw_path.name}")
    lines.append(f"Tableau file: {ds.tableau_path.name if ds.tableau_path else '(not found - reconciliation skipped)'}")
    lines.append(f"Run date used for RFS age: {ds.reference_date.date()}")
    lines.append(f"Utilized = {' + '.join(sorted(config.UTILIZED_STATUSES))}")

    h("Rows and totals")
    lines.append(f"  Port rows read:      {len(p):,}")
    lines.append(f"  NAPs:                {len(n):,}")
    lines.append(f"  Ports (sum of NAPs): {int(n['ports_total'].sum()):,}")
    lines.append(f"  OLTs (non-blank):    {n['olt_raw'].nunique():,}  (after inference: {n['olt'].nunique():,})")
    lines.append(f"  LCPs: {n['lcp'].nunique():,}   PON ports: {ds.pons.shape[0]:,}")
    lines.append(f"  Municipalities: {n['municipality'].nunique()}   Barangays (municipality+name): "
                 f"{n.groupby(['municipality', 'barangay']).ngroups}   distinct barangay names: {n['barangay'].nunique()}")
    lines.append(f"  Province values: {', '.join(f'{k} ({v:,})' for k, v in p['z PROVINCENAME'].value_counts().items())}")
    check(int(n["ports_total"].sum()) == len(p), "ports summed over NAPs equal port rows")
    check(not p.duplicated(["Poi Full Assignment"]).any(), "no duplicate port rows")
    check((n["n_lat"] == 1).all() and (n["n_lon"] == 1).all(), "every NAP has exactly one coordinate")
    check((n["n_olt"] <= 1).all(), "every NAP has at most one OLT")
    check(n["lat"].notna().all() and n["lon"].notna().all(), "no missing coordinates")
    check(n["lcp"].notna().all(), "every Poi Name parses into site / LCP / NAP")
    sizes = n["ports_total"].value_counts()
    check(list(sizes.index) == [8], f"every NAP has 8 ports (sizes seen: { {int(k): int(v) for k, v in sizes.items()} })")

    h("Port status")
    for k, v in p["Port Status"].value_counts(dropna=False).items():
        lines.append(f"  {k!s:<12} {v:>9,}")

    h("NAP levels")
    lv = n["level"].value_counts()
    for L in config.LEVELS:
        lines.append(f"  {L:<8} {int(lv.get(L, 0)):>7,}")
    lines.append(f"  (Low with zero used ports: {int(((n['level'] == 'Low') & (n['used'] == 0)).sum()):,})")
    check(int(lv.sum()) == len(n), "every NAP has a level")

    h("OLT levels (utilized / total ports per OLT)")
    ol = o["level"].value_counts()
    for L in config.LEVELS:
        lines.append(f"  {L:<8} {int(ol.get(L, 0)):>4}")
    lines.append(f"  OLT locations: {(o['location_source'] == 'site file').sum()} from site file, "
                 f"{(o['location_source'] != 'site file').sum()} approximate")

    h("Coverage gaps and unmatched IDs")
    lines.append(f"  NAPs with blank OLT ID: {int(n['olt_raw'].isna().sum()):,}  -> OLT inferred: {int(n['olt_inferred'].sum()):,}"
                 f"  -> still unknown: {int(n['olt'].isna().sum()):,}")
    for src, c in n.loc[n["olt_raw"].isna(), "olt_source"].value_counts().items():
        lines.append(f"      {c:>4} {src}")
    lines.append(f"  NAPs with no PON port: {int(n['pon'].isna().sum()):,}")
    lines.append(f"  Cross-fed NAPs (site prefix != OLT prefix, Ñ = N): {int(n['cross_fed'].sum()):,}"
                 f"   (+{int(n['prefix_spelling_only'].sum()):,} that differ only by Ñ/N spelling)")
    um = n["municipality_feature"].isna()
    ub = n["barangay_feature"].isna()
    lines.append(f"  Municipality names not matched to a boundary: {n.loc[um, 'municipality'].nunique()} ({int(um.sum()):,} NAPs)")
    lines.append(f"  Barangay names not matched to a boundary:     "
                 f"{n.loc[ub, ['municipality', 'barangay']].drop_duplicates().shape[0]} ({int(ub.sum()):,} NAPs)")
    for (m, b), c in n.loc[ub].groupby(["municipality", "barangay"]).size().sort_values(ascending=False).head(10).items():
        lines.append(f"      {c:>5}  {m} / {b}   (add to boundaries/barangay_aliases.csv)")
    if ds.recon:
        s = ds.recon["summary"].set_index("check")["value"]
        lines.append(f"  Tableau NAPs found in raw: {s['Tableau NAPs found in raw']:,} of {s['NAPs in Tableau Sheet 2']:,}"
                     f"   missing from raw: {s['Tableau NAPs missing from raw']:,}   new (raw only): {s['New NAPs (raw only)']:,}")
        lines.append(f"  Utilized ports equal Tableau: {s['Utilized ports equal Tableau (% of matched NAPs)']}%   "
                     f"level equals Tableau: {s['Level equals Tableau (% of matched NAPs)']}%")
        lines.append(f"  OLT renumbering detected (Tableau -> raw): {s['Tableau OLT IDs renumbered in raw'] or 'none'}")
        lines.append(f"  Tableau Sheet 1 stray single-port rows: {s['Tableau Sheet 1 stray single-port rows']}")

    h("Stacked coordinates")
    sc = n.groupby("pole_key").size().value_counts().sort_index()
    lines.append(f"  Distinct coordinates: {n['pole_key'].nunique():,}")
    lines.append("  NAPs per coordinate: " + ", ".join(f"{k}: {v:,}" for k, v in sc.items()))
    ps = ds.dq["placeholder_stacks"]
    lines.append(f"  Possible placeholder coordinates (> {config.STACK_FLAG_THRESHOLD} NAPs): {len(ps)} locations, "
                 f"{int(ps['naps'].sum()) if len(ps) else 0} NAPs")
    for r in ps.head(5).itertuples():
        lines.append(f"      {r.naps:>3} NAPs at {r.lat:.6f}, {r.lon:.6f}  {r.municipality}")

    h("Data quality")
    for r in ds.dq["summary"].itertuples():
        lines.append(f"  {r.count:>7,}  {r.issue}")

    if reloc:
        h("Relocation plan")
        for k, v in reloc["stats"].items():
            lines.append(f"  {k}: {_fmt(v)}")

    lines.append("")
    lines.append("RESULT: " + ("all invariant checks passed" if not fails else f"{len(fails)} check(s) FAILED"))
    return "\n".join(lines), fails
