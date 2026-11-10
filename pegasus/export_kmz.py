"""Google Earth (Pro and Web) KMZ export.

Approach: one KMZ per NAP level (Risk / High / Optimal / Low), each with a folder per
municipality, plus separate KMZs for OLTs, the barangay + municipality choropleth, and
the relocation plan. Every file is self-contained (icons embedded).

Why split by level: Google Earth Web slows down sharply above roughly 10-20k
placemarks in one file, and KML Regions/level-of-detail are not supported by Earth
Web. Splitting by level keeps each file at most ~20k placemarks (Low is the largest),
matches how the map is read (switch on Risk only, then High, ...), and works the same
in Earth Pro and Earth Web.
"""
from __future__ import annotations

import io
import math
import zipfile
from html import escape
from pathlib import Path

import pandas as pd
from PIL import Image, ImageDraw

from . import config


def kml_color(hex_rgb: str, alpha: int = 255) -> str:
    h = hex_rgb.lstrip("#")
    return f"{alpha:02x}{h[4:6]}{h[2:4]}{h[0:2]}"


def _icon(shape: str) -> bytes:
    s = 64
    im = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    if shape == "dot":
        d.ellipse((4, 4, s - 5, s - 5), fill=(255, 255, 255, 255), outline=(40, 40, 40, 255), width=5)
    else:  # diamond
        c = s / 2
        d.polygon([(c, 2), (s - 3, c), (c, s - 3), (3, c)], fill=(255, 255, 255, 255), outline=(0, 0, 0, 255))
        d.polygon([(c, 9), (s - 10, c), (c, s - 10), (10, c)], fill=(255, 255, 255, 255))
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


def _table(rows: list[tuple[str, object]]) -> str:
    tr = "".join(f"<tr><td style='color:#555;padding-right:8px'>{escape(str(k))}</td><td>{v}</td></tr>" for k, v in rows)
    return f"<table style='font-family:Arial;font-size:12px'>{tr}</table>"


def _cdata(html: str) -> str:
    return "<![CDATA[" + html.replace("]]>", "]]&gt;") + "]]>"


def _doc(name: str, body: str, styles: str, desc: str = "") -> str:
    return ("<?xml version='1.0' encoding='UTF-8'?>\n"
            "<kml xmlns='http://www.opengis.net/kml/2.2'><Document>"
            f"<name>{escape(name)}</name><open>1</open>"
            f"<description>{_cdata(desc)}</description>{styles}{body}</Document></kml>")


def _point_style(sid: str, color: str, icon: str, scale: float) -> str:
    bal = "<BalloonStyle><text>$[description]</text></BalloonStyle>"
    return (f"<Style id='{sid}_n'><IconStyle><color>{color}</color><scale>{scale}</scale>"
            f"<Icon><href>files/{icon}.png</href></Icon></IconStyle><LabelStyle><scale>0</scale></LabelStyle>{bal}</Style>"
            f"<Style id='{sid}_h'><IconStyle><color>{color}</color><scale>{scale * 1.4}</scale>"
            f"<Icon><href>files/{icon}.png</href></Icon></IconStyle><LabelStyle><scale>0.9</scale></LabelStyle>{bal}</Style>"
            f"<StyleMap id='{sid}'><Pair><key>normal</key><styleUrl>#{sid}_n</styleUrl></Pair>"
            f"<Pair><key>highlight</key><styleUrl>#{sid}_h</styleUrl></Pair></StyleMap>")


def _write_kmz(path: Path, kml: str, icons: list[str]):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("doc.kml", kml.encode("utf-8"))
        for ic in icons:
            z.writestr(f"files/{ic}.png", _icon(ic))


def _nap_desc(r, pole_others: str, reloc_note: str) -> str:
    color = config.LEVEL_COLORS[r.level]
    status = ", ".join(f"{n} {int(getattr(r, c))}" for n, c in
                       [("ACTIVE", "active"), ("AVAILABLE", "available"), ("ALLOCATED", "allocated"), ("RESERVED", "reserved")]
                       if getattr(r, c))
    rows = [
        ("Level", f"<b style='color:{color}'>{r.level}</b>"),
        ("LCP", escape(r.lcp)),
        ("OLT", escape(str(r.olt)) + (" (inferred)" if r.olt_inferred else "")),
        ("PON port", escape(str(r.pon) if pd.notna(r.pon) else "unknown")),
        ("Barangay", escape(str(r.barangay))), ("Municipality", escape(str(r.municipality))),
        ("Ports", f"<b>{int(r.used)}</b> used / {int(r.available)} available / {int(r.ports_total)} total"),
        ("Utilization", f"{100 * r.util_pct:.1f}%"), ("Status", escape(status)),
        ("Port map", escape(r.port_codes) + " <span style='color:#888'>(A active, V available, L allocated, R reserved)</span>"),
        ("RFS date", r.rfs_date.date() if pd.notna(r.rfs_date) else "–"),
        ("Distance to OLT", f"{r.olt_distance_km:.2f} km" + ("" if r.olt_distance_source == "Tableau" else " (estimated)")
         if pd.notna(r.olt_distance_km) else "–"),
        ("Same pole", escape(pole_others) or "none"),
    ]
    if r.placeholder_stack:
        rows.append(("Warning", "coordinate shared by many NAPs (possible placeholder)"))
    if reloc_note:
        rows.append(("Relocation", reloc_note))
    return f"<h3 style='font-family:Arial;margin:0 0 4px'>{escape(r.nap_id)}</h3>" + _table(rows)


def export(ds, reloc: dict, out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    n = ds.naps
    out: list[Path] = []
    pole_groups = n.groupby("pole_key")["nap_id"].agg(list).to_dict()
    rec = reloc["recommendations"]
    rec_by = rec.set_index("nap_id") if len(rec) else None
    sell_ids = set(reloc["sell_from_existing"]["nap_id"])
    run_desc = (f"Project Pegasus · data {escape(ds.raw_path.name)} · utilized = {' + '.join(sorted(config.UTILIZED_STATUSES))}"
                f" · built {pd.Timestamp.now():%Y-%m-%d}")

    # --- NAPs, one file per level ---
    for level in reversed(config.LEVELS):
        sub = n[n["level"] == level].sort_values(["municipality", "barangay", "nap_id"])
        sid = f"lv_{level.lower()}"
        styles = _point_style(sid, kml_color(config.LEVEL_COLORS[level]), "dot", 0.55)
        parts = [f"<Folder><name>{level} NAPs ({len(sub):,})</name><open>1</open>"]
        for muni, g in sub.groupby("municipality", sort=True):
            parts.append(f"<Folder><name>{escape(str(muni))} ({len(g):,})</name>")
            for r in g.itertuples():
                others = ", ".join(x for x in pole_groups[r.pole_key] if x != r.nap_id)
                note = ""
                if rec_by is not None and r.nap_id in rec_by.index:
                    x = rec_by.loc[r.nap_id]
                    note = (f"move to near {escape(x.target_nap)} ({x.target_level} hotspot {x.target_hotspot}), "
                            f"{x.distance_m:.0f} m, priority #{int(x.priority_rank)}")
                elif r.nap_id in sell_ids:
                    note = "Risk/High demand within drop reach: sell from this NAP (not relocated)"
                parts.append(f"<Placemark><name>{escape(r.nap_id)}</name><styleUrl>#{sid}</styleUrl>"
                             f"<description>{_cdata(_nap_desc(r, others, note))}</description>"
                             f"<Point><coordinates>{r.lon:.7f},{r.lat:.7f},0</coordinates></Point></Placemark>")
            parts.append("</Folder>")
        parts.append("</Folder>")
        p = out_dir / f"pegasus_naps_{level.lower()}.kmz"
        _write_kmz(p, _doc(f"Pegasus · {level} NAPs", "".join(parts), styles, run_desc), ["dot"])
        out.append(p)

    # --- OLTs ---
    styles = "".join(_point_style(f"olt_{L.lower()}", kml_color(config.LEVEL_COLORS[L]), "diamond", 1.1) for L in config.LEVELS)
    parts = ["<Folder><name>OLTs (approximate locations unless a site file was given)</name><open>1</open>"]
    for r in ds.olts.sort_values("olt").itertuples():
        desc = f"<h3 style='font-family:Arial;margin:0 0 4px'>{escape(r.olt)}</h3>" + _table([
            ("Level", f"<b style='color:{config.LEVEL_COLORS[r.level]}'>{r.level}</b>"),
            ("Utilization", f"{100 * r.util_rate:.1f}% ({int(r.used):,} of {int(r.ports_total):,} ports)"),
            ("NAPs / LCPs / PONs", f"{int(r.naps):,} / {int(r.lcps):,} / {int(r.pons):,}"),
            ("NAPs by level", " · ".join(f"{L} {int(getattr(r, 'naps_' + L.lower())):,}" for L in reversed(config.LEVELS))),
            ("Municipalities", escape(r.municipalities)), ("Location", escape(r.location_source))])
        parts.append(f"<Placemark><name>{escape(r.olt)}</name><styleUrl>#olt_{r.level.lower()}</styleUrl>"
                     f"<description>{_cdata(desc)}</description>"
                     f"<Point><coordinates>{r.lon:.7f},{r.lat:.7f},0</coordinates></Point></Placemark>")
    parts.append("</Folder>")
    p = out_dir / "pegasus_olts.kmz"
    _write_kmz(p, _doc("Pegasus · OLTs", "".join(parts), styles, run_desc), ["diamond"])
    out.append(p)

    # --- choropleths ---
    out.append(_choropleth(ds, out_dir, run_desc))

    # --- relocations ---
    out.append(_relocations(ds, reloc, out_dir, run_desc))
    return out


def _poly_kml(geom: dict) -> str:
    polys = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
    def ring(r):
        return " ".join(f"{x:.6f},{y:.6f},0" for x, y in r)
    parts = []
    for poly in polys:
        s = f"<Polygon><tessellate>1</tessellate><outerBoundaryIs><LinearRing><coordinates>{ring(poly[0])}</coordinates></LinearRing></outerBoundaryIs>"
        for hole in poly[1:]:
            s += f"<innerBoundaryIs><LinearRing><coordinates>{ring(hole)}</coordinates></LinearRing></innerBoundaryIs>"
        parts.append(s + "</Polygon>")
    return "<MultiGeometry>" + "".join(parts) + "</MultiGeometry>"


def _util_class(rate: float) -> str | None:
    if rate is None or (isinstance(rate, float) and math.isnan(rate)):
        return None
    b = config.OLT_LEVEL_BOUNDS
    return "Low" if rate < b[0][1] else "Optimal" if rate < b[1][1] else "High" if rate <= b[2][1] else "Risk"


def _area_desc(title: str, sub: str, a) -> str:
    if a is None:
        return f"<h3 style='font-family:Arial'>{escape(title)}</h3>{escape(sub)}<br>No NAPs."
    return f"<h3 style='font-family:Arial;margin:0 0 4px'>{escape(title)}</h3>" + _table([
        ("Area", escape(sub)),
        ("Utilization", f"<b>{100 * a.util_rate:.1f}%</b> ({int(a.used):,} of {int(a.ports_total):,} ports)"),
        ("NAPs", f"{int(a.naps):,}"),
        *[(L, f"{int(getattr(a, 'naps_' + L.lower())):,}") for L in reversed(config.LEVELS)],
    ])


def _choropleth(ds, out_dir: Path, run_desc: str) -> Path:
    from .aggregate import area_summary
    n = ds.naps
    styles = ""
    for L in config.LEVELS:
        c = config.LEVEL_COLORS[L]
        styles += (f"<Style id='ch_{L.lower()}'><LineStyle><color>{kml_color('#333333', 200)}</color><width>1</width></LineStyle>"
                   f"<PolyStyle><color>{kml_color(c, 120)}</color></PolyStyle>"
                   "<BalloonStyle><text>$[description]</text></BalloonStyle></Style>")
    styles += (f"<Style id='ch_none'><LineStyle><color>{kml_color('#777777', 160)}</color><width>1</width></LineStyle>"
               f"<PolyStyle><color>{kml_color('#999999', 25)}</color></PolyStyle></Style>")

    bsum = area_summary(n.dropna(subset=["barangay_feature"]), ["barangay_feature"]).set_index("barangay_feature")
    msum = area_summary(n.dropna(subset=["municipality_feature"]), ["municipality_feature"]).set_index("municipality_feature")
    legend = ("Fill = port utilization of the area (utilized / total ports): "
              "&lt;30% blue (Low), 30–60% green (Optimal), 60–80% orange (High), &gt;80% red (Risk).<br>" + run_desc)

    def folder(name, feats, summ, label_fn, visible):
        parts = [f"<Folder><name>{name}</name><visibility>{int(visible)}</visibility>"]
        for i, f in enumerate(feats["features"]):
            a = next(summ.loc[[i]].itertuples()) if i in summ.index else None
            cls = _util_class(a.util_rate) if a is not None else None
            title, sub = label_fn(f["properties"])
            parts.append(f"<Placemark><name>{escape(title)}</name><visibility>{int(visible)}</visibility>"
                         f"<styleUrl>#ch_{cls.lower() if cls else 'none'}</styleUrl>"
                         f"<description>{_cdata(_area_desc(title, sub, a))}</description>{_poly_kml(f['geometry'])}</Placemark>")
        parts.append("</Folder>")
        return "".join(parts)

    body = (folder("Barangay utilization", ds.bgys, bsum, lambda p: (p["barangay"], p["municipality"]), True)
            + folder("Municipality utilization", ds.munis, msum, lambda p: (p["municipality"], "Municipality"), False))
    p = out_dir / "pegasus_choropleth.kmz"
    _write_kmz(p, _doc("Pegasus · utilization choropleth", body, styles, legend), [])
    return p


def _relocations(ds, reloc: dict, out_dir: Path, run_desc: str) -> Path:
    rec, hs = reloc["recommendations"], reloc["hotspots"]
    styles = (_point_style("cand", kml_color(config.LEVEL_COLORS["Low"]), "dot", 0.8)
              + _point_style("hot_risk", kml_color(config.LEVEL_COLORS["Risk"]), "diamond", 0.7)
              + _point_style("hot_high", kml_color(config.LEVEL_COLORS["High"]), "diamond", 0.7))
    for L in ("Risk", "High"):
        styles += (f"<Style id='ln_{L.lower()}'><LineStyle><color>{kml_color(config.LEVEL_COLORS[L])}</color>"
                   "<width>3</width></LineStyle><BalloonStyle><text>$[description]</text></BalloonStyle></Style>")
    parts = [f"<Folder><name>Relocations ({len(rec):,})</name><open>1</open>"]
    for muni, g in (rec.groupby("municipality") if len(rec) else []):
        parts.append(f"<Folder><name>{escape(str(muni))} ({len(g)})</name>")
        for r in g.sort_values("priority_rank").itertuples():
            desc = (f"<h3 style='font-family:Arial;margin:0 0 4px'>Relocation #{r.priority_rank}</h3>" + _table([
                ("Move NAP", f"{escape(r.nap_id)} ({r.used_ports} used, LCP {escape(r.lcp)})"),
                ("OLT / PON", f"{escape(str(r.olt))} / {escape(str(r.pon))}"),
                ("To near", f"{escape(r.target_nap)} ({r.target_nap_level})"),
                ("Hotspot", f"{r.target_hotspot} · {r.target_level} · {r.hotspot_naps} NAPs"),
                ("Distance", f"{r.distance_m:.0f} m" + (" · same LCP" if r.same_lcp else "")),
                ("New sellable ports", r.new_sellable_ports),
                ("Potential subscriber gain", r.potential_subscriber_gain),
                ("Re-home first", escape(r.rehome_to) or "–"),
            ]))
            lv = r.target_level.lower()
            parts.append(f"<Placemark><name>#{r.priority_rank} {escape(r.nap_id)}</name><styleUrl>#ln_{lv}</styleUrl>"
                         f"<description>{_cdata(desc)}</description><LineString><tessellate>1</tessellate><coordinates>"
                         f"{r.lon:.7f},{r.lat:.7f},0 {r.target_lon:.7f},{r.target_lat:.7f},0</coordinates></LineString></Placemark>")
            parts.append(f"<Placemark><name>{escape(r.nap_id)}</name><styleUrl>#cand</styleUrl>"
                         f"<description>{_cdata(desc)}</description>"
                         f"<Point><coordinates>{r.lon:.7f},{r.lat:.7f},0</coordinates></Point></Placemark>")
        parts.append("</Folder>")
    parts.append("</Folder>")
    used = hs[hs["relocated_naps_assigned"] > 0]
    parts.append(f"<Folder><name>Demand hotspots receiving NAPs ({len(used):,})</name>")
    for r in used.itertuples():
        desc = f"<h3 style='font-family:Arial;margin:0 0 4px'>Hotspot {r.hotspot}</h3>" + _table([
            ("Level", r.level), ("Area", f"{escape(r.barangay)}, {escape(r.municipality)}"),
            ("NAPs", f"{r.naps} (Risk {r.risk_naps}, High {r.high_naps})"), ("Radius", f"{r.radius_m:.0f} m"),
            ("Ports needed (net of idle ports nearby)", r.ports_needed_net),
            ("Relocated NAPs assigned", r.relocated_naps_assigned)])
        parts.append(f"<Placemark><name>{r.hotspot}</name><styleUrl>#hot_{r.level.lower()}</styleUrl>"
                     f"<description>{_cdata(desc)}</description>"
                     f"<Point><coordinates>{r.lon:.7f},{r.lat:.7f},0</coordinates></Point></Placemark>")
    parts.append("</Folder>")
    p = out_dir / "pegasus_relocations.kmz"
    _write_kmz(p, _doc("Pegasus · NAP relocation plan", "".join(parts), styles, run_desc), ["dot", "diamond"])
    return p
