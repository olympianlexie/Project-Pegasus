"""Read and clean the raw port export and the Tableau crosstab."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pandas as pd

from . import config

RAW_COLUMNS = [
    "RFS Date", "Olt Id", "Olt Port Assignment", "Poi Name", "Np Latitude", "Np Longitude",
    "Account Number", "z PROVINCENAME", "z MUNICIPALITYNAME", "z BARANGAYNAME",
    "Poi Full Assignment", "Port Number", "Port Status",
]

POI_RE = re.compile(r"^\s*(?P<site>\S+)\s+(?P<lp>LP\d+)\s+(?P<np>NP\d+)\s*$", re.IGNORECASE)


def find_input(pattern: str, explicit: str | None) -> Path:
    if explicit:
        p = Path(explicit)
        if not p.exists():
            raise FileNotFoundError(p)
        return p
    matches = sorted(config.DATA_DIR.glob(pattern), key=lambda p: p.stat().st_mtime)
    if not matches:
        raise FileNotFoundError(
            f"No file matching '{pattern}' in {config.DATA_DIR}. Put the export there or pass its path."
        )
    return matches[-1]


def _cache_path(path: Path, tag: str) -> Path:
    st = path.stat()
    key = hashlib.sha1(f"{path.resolve()}|{st.st_size}|{st.st_mtime_ns}|{tag}|v1".encode()).hexdigest()[:16]
    return config.CACHE_DIR / f"{tag}-{key}.pkl"


def _blank(s: pd.Series) -> pd.Series:
    """True where a text cell is missing or only whitespace."""
    return s.isna() | s.astype("string").str.strip().fillna("").eq("")


def read_raw(path: Path) -> pd.DataFrame:
    """One row per NAP port, cleaned. Cached by file size + mtime (reading the xlsx takes ~25 s)."""
    cache = _cache_path(path, "raw")
    if cache.exists():
        return pd.read_pickle(cache)

    df = pd.read_excel(path, dtype={"Account Number": str, "Olt Id": str, "Olt Port Assignment": str})
    missing = [c for c in RAW_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"Raw file is missing columns: {missing}")
    df = df[RAW_COLUMNS].copy()

    for c in ["Olt Id", "Olt Port Assignment", "Poi Name", "Poi Full Assignment",
              "z PROVINCENAME", "z MUNICIPALITYNAME", "z BARANGAYNAME", "Account Number"]:
        df[c] = df[c].astype("string").str.strip()
        df.loc[df[c].eq(""), c] = pd.NA
    df["Account Number"] = df["Account Number"].str.replace(r"\.0$", "", regex=True)
    df["Port Status"] = df["Port Status"].astype("string").str.strip().str.upper()
    df["RFS Date"] = pd.to_datetime(df["RFS Date"], errors="coerce")
    df["Port Number"] = pd.to_numeric(df["Port Number"], errors="coerce").astype("Int64")

    parts = df["Poi Name"].str.extract(POI_RE)
    df["site"] = parts["site"].str.upper()
    df["lcp"] = (parts["site"].str.upper() + " " + parts["lp"].str.upper())
    df["np"] = parts["np"].str.upper()

    config.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    df.to_pickle(cache)
    return df


def read_tableau(path: Path) -> dict:
    """Sheet 1 (OLT x municipality) and Sheet 2 (NAP) with blank grouping cells forward-filled."""
    cache = _cache_path(path, "tableau")
    if cache.exists():
        return pd.read_pickle(cache)

    xl = pd.ExcelFile(path)
    s1 = pd.read_excel(xl, "Sheet 1")
    s1[["z PROVINCENAME", "UTILIZATION LEVEL", "Olt Id"]] = s1[["z PROVINCENAME", "UTILIZATION LEVEL", "Olt Id"]].ffill()
    lcp_port = s1["Lcp Port"].astype("string").str.strip()
    s1["stray_single_port_row"] = lcp_port.notna() & lcp_port.ne("*") & lcp_port.ne("")
    s1["level"] = s1["UTILIZATION LEVEL"].str.replace(" Utilization", "", regex=False).str.strip()

    s2 = pd.read_excel(xl, "Sheet 2")
    s2[["Olt Id", "UTILIZATION LEVEL"]] = s2[["Olt Id", "UTILIZATION LEVEL"]].ffill()
    s2["Nap Id"] = s2["Nap Id"].astype("string").str.strip()
    s2["level"] = s2["UTILIZATION LEVEL"].str.replace(" Utilization", "", regex=False).str.strip()

    out = {"sheet1": s1, "sheet2": s2}
    config.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    pd.to_pickle(out, cache)
    return out


def read_sites(path: Path, id_col: str) -> pd.DataFrame | None:
    """Optional OLT/LCP site file (id, Latitude, Longitude). Returns None if absent."""
    if not path.exists():
        return None
    df = pd.read_csv(path, dtype={id_col: str})
    cols = {c.lower().strip(): c for c in df.columns}
    need = [id_col.lower(), "latitude", "longitude"]
    if not all(n in cols for n in need):
        raise ValueError(f"{path} must have columns: {id_col}, Latitude, Longitude")
    df = df.rename(columns={cols[id_col.lower()]: "id", cols["latitude"]: "lat", cols["longitude"]: "lon"})
    df["id"] = df["id"].str.strip()
    return df[["id", "lat", "lon"]].dropna()
