"""Checks a real export against expected totals kept in data/expected_counts.json.

That file is git-ignored (this repository is public), so the figures stay private.
The test skips itself when the export or the file is missing, or when the file was
written for a different export (its "naps" total doesn't match). Format:

{"naps": 0, "ports": 0, "olts": 0, "levels": {"Low": 0, "Optimal": 0, "High": 0, "Risk": 0},
 "low_zero_used": 0, "blank_olt": 0, "inferred_olt": {"OLT-ID": 0}, "new_vs_tableau": 0,
 "cross_fed": 0, "placeholder_stacks": 0}
"""
import json

import pytest

from pegasus import config, pipeline

EXPECTED = config.DATA_DIR / "expected_counts.json"
RAW = list(config.DATA_DIR.glob(config.RAW_FILE_GLOB))
pytestmark = pytest.mark.skipif(not RAW or not EXPECTED.exists(), reason="export or expected_counts.json not in data/")


@pytest.fixture(scope="module")
def exp():
    return json.loads(EXPECTED.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def ds(exp):
    d = pipeline.build()
    if len(d.naps) != exp["naps"]:
        pytest.skip("expected_counts.json was written for a different export")
    return d


def test_totals(ds, exp):
    n = ds.naps
    assert len(ds.ports) == exp["ports"] == int(n["ports_total"].sum())
    assert n["olt_raw"].nunique() == exp["olts"]
    assert n["level"].value_counts().to_dict() == exp["levels"]
    assert int(((n["level"] == "Low") & (n["used"] == 0)).sum()) == exp["low_zero_used"]


def test_reconciliation(ds, exp):
    n = ds.naps
    assert int(n["olt_raw"].isna().sum()) == exp["blank_olt"]
    assert int(n["olt"].isna().sum()) == 0
    assert n.loc[n["olt_raw"].isna(), "olt"].value_counts().to_dict() == exp["inferred_olt"]
    assert int((~n["in_tableau"]).sum()) == exp["new_vs_tableau"]
    assert int(n["cross_fed"].sum()) == exp["cross_fed"]
    assert len(ds.dq["placeholder_stacks"]) == exp["placeholder_stacks"]
    assert int(n["barangay_feature"].isna().sum()) == 0
