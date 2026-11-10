import pandas as pd
import pytest

from pegasus import aggregate, config, geo, load
from pegasus.export_kmz import kml_color


def test_nap_levels_for_8_ports():
    used = pd.Series(range(9))
    got = aggregate.nap_level(used, pd.Series([8] * 9)).tolist()
    assert got == ["Low"] * 3 + ["Optimal"] * 2 + ["High"] * 2 + ["Risk"] * 2


def test_olt_level_boundaries():
    rates = pd.Series([0.0, 0.2999, 0.30, 0.5999, 0.60, 0.80, 0.8001, 1.0])
    assert aggregate.olt_level(rates).tolist() == ["Low", "Low", "Optimal", "Optimal", "High", "High", "Risk", "Risk"]


@pytest.mark.parametrize("raw,expected", [
    ("CITY OF BIÑAN", "BINAN"), ("LOS BAÑOS", "LOS BANOS"), ("Los Baños", "LOS BANOS"),
    ("BAGONG BAYAN II-A (POB.)", "BAGONG BAYAN II A"), ("Poblacion II (Pob.)", "II"), ("City of Santa Rosa", "SANTA ROSA"),
])
def test_norm_name(raw, expected):
    assert geo.norm_name(raw) == expected


def test_poi_name_parse():
    m = load.POI_RE.match("XÑZ001 LP20 NP3")
    assert (m["site"], m["lp"], m["np"]) == ("XÑZ001", "LP20", "NP3")
    assert load.POI_RE.match("ABC001 LP87 NP1")["lp"] == "LP87"


def test_kml_color_is_aabbggrr():
    assert kml_color("#d62728") == "ff2827d6"
    assert kml_color("#1f6fd1", 0x80) == "80d16f1f"


def test_haversine_one_degree_lat():
    assert abs(aggregate.haversine_m(14.0, 121.0, 15.0, 121.0) - 111_195) < 50
