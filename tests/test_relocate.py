"""Synthetic relocation scenario: checks the confirmed rules end to end."""
from types import SimpleNamespace

import numpy as np
import pandas as pd

from pegasus import config, relocate

LAT0, LON0 = 14.2, 121.1
M_PER_DEG_LON = 111320 * np.cos(np.radians(LAT0))


def nap(nid, east_m, used, olt="T01-OLT-01", lcp=None, rfs="2020-01-01", north_m=0.0):
    lat, lon = LAT0 + north_m / 110540, LON0 + east_m / M_PER_DEG_LON
    lvl = "Low" if used <= 2 else "Optimal" if used <= 4 else "High" if used <= 6 else "Risk"
    return dict(nap_id=nid, lat=lat, lon=lon, used=used, available=8 - used, ports_total=8, level=lvl,
                olt=olt, lcp=lcp or nid.rsplit(" ", 1)[0], pon="gpon_olt-1/1/1", municipality="TEST",
                barangay="B1", rfs_date=pd.Timestamp(rfs), placeholder_stack=False, olt_inferred=False,
                pole_key=f"{lat:.7f},{lon:.7f}")


def build(rows):
    naps = pd.DataFrame(rows)
    lcp = naps.groupby("lcp")[["lat", "lon"]].mean()
    return SimpleNamespace(naps=naps, reference_date=pd.Timestamp("2026-11-10"), extra={"lcp_sites": lcp})


def test_rules():
    rows = [
        # hotspot A: 3 Risk NAPs within a few metres -> needs 3*(8-4)=12 ports
        nap("T01 LP1 NP1", 0, 8), nap("T01 LP1 NP2", 0, 8), nap("T01 LP1 NP3", 10, 8),
        nap("T01 LP9 NP1", 20, 0),                       # idle, 20 m from demand: kept (sell from existing)
        nap("T01 LP2 NP1", 300, 0),                      # idle, 300 m east: should be relocated to A
        nap("T01 LP3 NP1", -300, 0),                     # idle, 300 m west: competes for A's capacity
        nap("T02 LP4 NP1", 0, 0, olt="T02-OLT-01", north_m=300),   # other OLT: not allowed
        nap("T01 LP5 NP1", 0, 0, north_m=-300, rfs="2026-06-01"),  # RFS'd < 12 months ago: excluded
        nap("T01 LP6 NP1", 2000, 1),                     # no demand within 500 m
    ]
    r = relocate.plan(build(rows))
    rec, notm, sell = r["recommendations"], r["not_moved"].set_index("nap_id"), r["sell_from_existing"]

    assert set(sell["nap_id"]) == {"T01 LP9 NP1"}
    # 12 ports needed - 8 idle ports already within reach = 4 -> 1 relocated NAP
    hs = r["hotspots"].set_index("hotspot")
    assert int(hs["ports_needed"].iloc[0]) == 12 and int(hs["ports_needed_net"].iloc[0]) == 4
    assert len(rec) == 1 and rec.iloc[0]["nap_id"] in {"T01 LP2 NP1", "T01 LP3 NP1"}
    assert 285 < rec.iloc[0]["distance_m"] < 305
    assert rec.iloc[0]["target_level"] == "Risk" and rec.iloc[0]["priority_rank"] == 1
    loser = ({"T01 LP2 NP1", "T01 LP3 NP1"} - {rec.iloc[0]["nap_id"]}).pop()
    assert "enough relocated NAPs" in notm.at[loser, "reason"]
    assert "same OLT" in notm.at["T02 LP4 NP1", "reason"]
    assert notm.at["T01 LP5 NP1", "reason"].startswith("new NAP")
    assert "within 500 m" in notm.at["T01 LP6 NP1", "reason"]


def test_same_pole_target_ignored_when_relocating_everything(monkeypatch):
    monkeypatch.setattr(config, "NEAR_DEMAND_RULE", "relocate")
    rows = [nap("T01 LP1 NP1", 0, 8), nap("T01 LP1 NP2", 0, 8), nap("T01 LP1 NP3", 0, 8),
            nap("T01 LP1 NP4", 0, 0)]  # idle NAP on the same pole as the only demand
    r = relocate.plan(build(rows))
    assert len(r["recommendations"]) == 0
    assert "within 500 m" in r["not_moved"].set_index("nap_id").at["T01 LP1 NP4", "reason"]


def test_subscribers_must_be_rehomed(monkeypatch):
    monkeypatch.setattr(config, "NEAR_DEMAND_RULE", "keep")
    rows = [nap("T01 LP1 NP1", 0, 8), nap("T01 LP1 NP2", 0, 8), nap("T01 LP1 NP3", 5, 8),
            nap("T01 LP2 NP1", 300, 2),                 # 2 subscribers, nowhere to put them
            nap("T01 LP3 NP1", -300, 1), nap("T01 LP3 NP2", -300, 0, north_m=20)]  # sibling can take 1
    r = relocate.plan(build(rows))
    rec = r["recommendations"].set_index("nap_id")
    # LP3 NP2 (0 used) goes first; LP3 NP1 then can't re-home into a NAP that has moved
    assert "T01 LP3 NP2" in rec.index
    assert "T01 LP2 NP1" not in rec.index
