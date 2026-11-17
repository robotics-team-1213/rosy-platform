"""cell-site-map.json: the generated list of cell places (tools/sim/export_site_map.py) and its loader."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import re
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT / "tools/sim", ROOT / "deploy/robot/omx"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import cell_site_map as csm  # noqa: E402
import export_site_map as gen  # noqa: E402
import omx_two_arm_sites as sites  # noqa: E402

DOC = csm.load()
ZONES = {z["id"]: z for z in DOC["zones"]}


def test_tier_places_are_37_in_18_9_9_1():
    counts = {zid: sum(len(s["tiers"]) for s in z["slots"]) for zid, z in ZONES.items()}
    assert counts == {"yard": 18, "temp_a": 9, "temp_b": 9, "stand": 1}
    assert len(csm.tier_places(DOC)) == 37


def test_arm_rules_and_stand_has_no_sim_place():
    assert {zid: z["arms"] for zid, z in ZONES.items()} == {"yard": ["arm_a", "arm_b"], "temp_a": ["arm_a"], "temp_b": ["arm_b"], "stand": ["arm_a"]}
    assert ZONES["stand"]["slots"][0]["tiers"] == [{"tier": 1, "id": "stand:r1-s1-t1", "item": None}]


def test_ids_match_regex_and_nest():
    rx = re.compile(r"^(yard|temp_a|temp_b|stand):r[1-3]-s[1-2](-t[1-3])?$")
    for z in DOC["zones"]:
        for s in z["slots"]:
            assert rx.match(s["id"]) and "-t" not in s["id"]
            assert all(rx.match(t["id"]) and t["id"].startswith(s["id"] + "-t") for t in s["tiers"])


def test_every_item_is_a_sim_site():
    items = [i for i in csm.tier_places(DOC).values() if i]
    assert len(items) == 36 and len(set(items)) == 36
    assert set(items) <= set(sites.Layout().sites)


def test_yard_row_and_hold_mapping_is_computed_from_slot_records():
    recs = json.loads((sites.SHIP_ASSETS / "slots.json").read_text(encoding="utf-8"))["tier_records"]
    assert min(r["y_mm"] for r in recs) == -38  # slots.json row 01 = ship y -38 = fixture y +38 (arm_b side)
    yard = {s["id"]: s for s in ZONES["yard"]["slots"]}
    # Harbor row 1 (fixture y +38) is sim r2; columns 1-3 are sim h2, columns 4-6 sim h1
    assert yard["yard:r1-s1"]["tiers"][0]["item"] == "ship-h2r2-l0"
    assert yard["yard:r3-s2"]["tiers"][0]["item"] == "ship-h1r0-l0"
    assert yard["yard:r1-s1"]["columns"] == [1, 3] and yard["yard:r1-s2"]["columns"] == [4, 6] and ZONES["yard"]["hold_boundary"] == {"columns": [3, 4]}
    assert yard["yard:r1-s1"]["physical"] == ["010182", "030182", "050182"]  # row 01, bays 01-05 at tier 82
    assert all(len(s["physical"]) == 3 for s in yard.values())


def test_aliases_resolve():
    a = DOC["aliases"]
    assert a["legacy_layout"]["yard-r1-c1"] == "yard:r1-s1"
    assert a["legacy_layout"]["yard-r1-c4"] == "yard:r1-s2" and a["legacy_layout"]["temp_a-2"] == "temp_a:r2-s1" and a["legacy_layout"]["stand-1"] == "stand:r1-s1"
    assert a["legacy_sim"]["ship-h2r2-l0"] == "yard:r1-s1-t1" and a["legacy_sim"]["ship-stern-l0"] == "not_places:ship_stern"
    assert a["legacy_station_zones"]["EXP_S1"] == "stand:r1-s1" and a["legacy_station_zones"]["STG_C2"] is None
    assert {n["id"] for n in DOC["not_places"]} == {"belt", "supply_s", "ship_stern", "ship_bow", "pinky_tray"}


def test_committed_file_is_the_generators_output(tmp_path):
    assert gen.main(["--check"]) == 0
    out = tmp_path / "a.json"
    gen.main(["--out", str(out)])
    assert out.read_text(encoding="utf-8") == gen.render() == gen.render()
    assert gen.main(["--check", "--out", str(tmp_path / "missing.json")]) == 1
    out.write_text(out.read_text(encoding="utf-8").replace("planned_unverified", "x", 1), encoding="utf-8")
    assert gen.main(["--check", "--out", str(out)]) == 1


def test_validator_rejects_a_bad_id():
    bad = copy.deepcopy(DOC)
    bad["zones"][0]["slots"][0]["tiers"][0]["id"] = "yard:r4-s1-t1"
    with pytest.raises(ValueError):
        csm.validate(bad)


def test_site_coords_are_only_read():
    import cell_fleet_pipeline as pipe
    before = copy.deepcopy(pipe.FleetModelPipeline.SITE_COORDS)
    assert "belt" in before and "pinky_tray" in before  # the not_places the map names
    csm.load()
    gen.render()
    assert pipe.FleetModelPipeline.SITE_COORDS == before
    assert not (set(before) & {t for t in csm.tier_places(DOC)})  # no place id doubles as a pipeline site key