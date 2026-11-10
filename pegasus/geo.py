"""Admin boundaries (PSGC) and matching raw municipality/barangay names to them."""
from __future__ import annotations

import json
import re
import unicodedata

import pandas as pd

from . import config


def norm_name(s) -> str:
    """CITY OF BIÑAN -> BINAN, 'Bagong Bayan II-A (Pob.)' -> BAGONG BAYAN II A."""
    if s is None or (isinstance(s, float) and pd.isna(s)) or s is pd.NA:
        return ""
    s = str(s).upper()
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = re.sub(r"\(POB\.?\)", " ", s)
    s = re.sub(r"\bPOBLACION\b", " ", s)
    s = re.sub(r"^\s*CITY OF\s+", "", s)
    s = re.sub(r"\s+CITY\s*$", "", s)
    s = re.sub(r"[^A-Z0-9 ]", " ", s)
    return " ".join(s.split())


def load_boundaries():
    with open(config.BOUNDARY_DIR / "laguna_municipalities.geojson", encoding="utf-8") as f:
        munis = json.load(f)
    with open(config.BOUNDARY_DIR / "laguna_barangays.geojson", encoding="utf-8") as f:
        bgys = json.load(f)
    return munis, bgys


def load_aliases() -> dict:
    """(municipality, raw barangay) normalized -> PSGC barangay normalized."""
    p = config.BARANGAY_ALIASES_FILE
    if not p.exists():
        return {}
    a = pd.read_csv(p, dtype=str).fillna("")
    return {(norm_name(r.municipality), norm_name(r.raw_barangay)): norm_name(r.psgc_barangay)
            for r in a.itertuples()}


def match_areas(naps: pd.DataFrame, munis: dict, bgys: dict) -> pd.DataFrame:
    """Adds municipality_feature / barangay_feature: index of the matching polygon, or NA."""
    mkey = {norm_name(f["properties"]["municipality"]): i for i, f in enumerate(munis["features"])}
    bkey = {}
    for i, f in enumerate(bgys["features"]):
        p = f["properties"]
        bkey[(norm_name(p["municipality"]), norm_name(p["barangay"]))] = i
    aliases = load_aliases()

    pairs = naps[["municipality", "barangay"]].drop_duplicates()
    m_idx, b_idx = {}, {}
    for mu, bg in pairs.itertuples(index=False):
        nm, nb = norm_name(mu), norm_name(bg)
        nb = aliases.get((nm, nb), nb)
        m_idx[(mu, bg)] = mkey.get(nm)
        b_idx[(mu, bg)] = bkey.get((nm, nb))
    k = list(zip(naps["municipality"], naps["barangay"]))
    naps["municipality_feature"] = pd.array([m_idx[x] for x in k], dtype="Int64")
    naps["barangay_feature"] = pd.array([b_idx[x] for x in k], dtype="Int64")
    return naps
