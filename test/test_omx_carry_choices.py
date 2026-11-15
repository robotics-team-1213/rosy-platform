"""Sim-ranked carry offers reach the real pick plan (cell_carry_choices): applied, clamped, ignored when bad, recorded, seen by the sweep's real table."""
import json
import math
from pathlib import Path
import sys

import pytest

pytest.importorskip("cv2")
pytest.importorskip("numpy")
pytest.importorskip("yaml")
OMX = Path(__file__).parents[1] / "deploy/robot/omx"
sys.path.insert(0, str(OMX))
try:
    import cell_attempts
    import cell_auto_pick as auto
    import cell_carry_choices as carry
    import cell_choices
finally:
    sys.path.remove(str(OMX))

ENTRY = {"id": "container-v2-3", "length_mm": 90, "width_mm": 30, "top_height_mm": 32.4, "grasp": {"jaw_axis_deg_from_long": 0}}
OBJECT = {"raw_m": [0.12, 0.015], "long_axis_deg": 89.0}
CONFIG = {"plan": {"approach_m": 0.04}, "params": {"gripper.open_max": 62.0},
          "sites": {"ship": {"surface_z": -0.0167, "yaw_deg": 0.0}, "table": {"surface_z": -0.0197, "yaw_deg": -90.0}}}
DEST = "table-l1"  # tier 2


def store(tmp_path, *values, name="carry.tier2"):
    ch = cell_choices.Choices(tmp_path / "choices.json")
    ch.data["values"][name] = list(values) if values and isinstance(values[0], dict) and "candidate" not in values[0] else [
        {"value": v, "source": "sim:test", "ok": 0, "tries": 0, "last": None} for v in values]
    return ch


def offer(**kw):
    return {"candidate": "c01", "tier": 2, "auto.grasp_depth_m": 0.012, "place_dz": 0.006, "auto.jaw_margin_mm": 4.0} | kw


def plan(config, tmp_path, monkeypatch):
    monkeypatch.setattr(auto.cp, "write_library", lambda cfg, pick, place, path: path)
    _, pick, place, _, _, used = auto.plan_pick(config, "ship", "table", (0.068, -0.112), OBJECT, ENTRY, 0, (0, 0), tmp_path)
    return pick, place, used["grip_open"]


def test_a_merged_offer_changes_pick_depth_place_z_and_jaw_gap(tmp_path, monkeypatch):
    base = plan(CONFIG, tmp_path, monkeypatch)
    config, applied, _ = carry.apply(CONFIG, store(tmp_path, offer()), DEST, "table")
    pick, place, jaw = plan(config, tmp_path, monkeypatch)
    assert applied[0] == "carry.tier2" and CONFIG["sites"]["table"].get("place_dz") is None  # the input is untouched
    assert pick["z"] - base[0]["z"] == pytest.approx(0.003)  # grip 12 mm instead of 15 under the top
    assert place["z"] - base[1]["z"] == pytest.approx(0.003 + 0.006)  # a 3 mm shallower grip lifts the box seat 3 mm, plus the 6 mm drop
    assert jaw < base[2]


def test_the_sweep_files_key_is_read_as_the_plans_place_dz(tmp_path):
    sweep = {"candidate": "c02", "tier": 2, "auto.grasp_depth_m": 0.01, "site.place_dz_m": 0.007, "auto.jaw_margin_mm": 3.0}
    config, applied, _ = carry.apply(CONFIG, store(tmp_path, sweep), DEST, "table")
    assert config["sites"]["table"]["place_dz"] == 0.007 and config["params"]["auto.grasp_depth_m"] == 0.01 and applied


@pytest.mark.parametrize("raw, want", [
    ({"auto.grasp_depth_m": 0.05, "place_dz": 0.1, "auto.jaw_margin_mm": 25.0}, (0.024, 0.010, 6.5)),
    ({"auto.grasp_depth_m": 0.0, "place_dz": -0.01, "auto.jaw_margin_mm": 0.5}, (0.008, 0.0, 2.0)),
])
def test_out_of_range_values_are_clamped_inside_both_bounds(tmp_path, raw, want):
    config, _, _ = carry.apply(CONFIG, store(tmp_path, offer(**raw)), DEST, "table")
    assert (config["params"]["auto.grasp_depth_m"], config["sites"]["table"]["place_dz"], config["params"]["auto.jaw_margin_mm"]) == want


def test_the_min_jaw_margin_parameter_raises_the_floor(tmp_path):
    cfg = dict(CONFIG, params=CONFIG["params"] | {"auto.min_jaw_margin_mm": 3.0})
    config, _, _ = carry.apply(cfg, store(tmp_path, offer(**{"auto.jaw_margin_mm": 2.0})), DEST, "table")
    assert config["params"]["auto.jaw_margin_mm"] == 3.0


@pytest.mark.parametrize("bad", ["junk", {"candidate": "x"}, offer(place_dz=math.nan), offer(place_dz="0.005"),
                                 offer(**{"auto.grasp_depth_m": True}), offer(place_dz=math.inf), [1, 2]])
def test_a_bad_store_leaves_the_defaults_and_says_why(tmp_path, bad):
    logged = []
    ch = store(tmp_path, bad)
    config, applied, _ = carry.apply(CONFIG, ch, DEST, "table", logged.append)
    assert config is CONFIG and applied is None and "defaults kept" in logged[0]
    ch.data["values"]["carry.tier2"] = [{"nope": 1}]  # an entry without "value"
    assert carry.apply(CONFIG, ch, DEST, "table", logged.append)[1] is None
    carry.outcome(ch, applied, True)  # nothing applied, nothing recorded


def test_no_offer_for_the_tier_changes_nothing(tmp_path):
    ch = store(tmp_path, offer(), name="carry.tier3")  # dest is tier 2
    assert carry.apply(CONFIG, ch, DEST, "table")[0] is CONFIG


def test_choices_used_carries_the_tier_and_the_outcome_teaches_best(tmp_path):
    a, b = offer(), offer(candidate="c02", place_dz=0.002)
    ch = store(tmp_path, a, b)
    assert ch.best("carry.tier2") == a  # untried: the first
    _, applied, _ = carry.apply(CONFIG, ch, DEST, "table")
    assert cell_attempts.context(CONFIG, None, "ship", ch)["choices_used"]["carry.tier2"] == a
    carry.outcome(ch, applied, False)
    assert ch.best("carry.tier2") == b and cell_choices.Choices(tmp_path / "choices.json").data["values"]["carry.tier2"][0]["tries"] == 1


def test_the_sweeps_real_table_would_see_the_attempt_row(tmp_path):
    ch = store(tmp_path, offer())
    row = {"to": DEST, "outcome": "placed", "attempt_id": "r-001", "context": cell_attempts.context(CONFIG, None, "ship", ch)}
    path = tmp_path / "attempts.jsonl"
    path.write_text(json.dumps(row) + "\n")
    sweep = Path(__file__).parents[1] / "tools/sim"
    if (sweep / "omx_carry_sweep.py").exists():  # the sim-loop branch
        sys.path.insert(0, str(sweep))
        try:
            import omx_carry_sweep as sw
        finally:
            sys.path.remove(str(sweep))
        assert dict(sw.real_table(path)) == {("c01", 2): {"ok": 1}}
        assert carry.BOUNDS["auto.grasp_depth_m"] == sw.BOUNDS["auto.grasp_depth_m"] and carry.BOUNDS["place_dz"] == sw.BOUNDS["site.place_dz_m"]
    v = json.loads(path.read_text())["context"]["choices_used"]["carry.tier2"]  # documented row format: a dict with "candidate" under carry.tier*
    assert v["candidate"] == "c01" and carry.tier_name(DEST) == "carry.tier2"


def test_a_huge_int_in_the_store_keeps_the_defaults(tmp_path):
    logged = []
    config, applied, shadow = carry.apply(CONFIG, store(tmp_path, offer(place_dz=10**400)), DEST, "table", logged.append)
    assert config is CONFIG and applied is None and shadow is None and "defaults kept" in logged[0]


def test_a_floor_above_the_ceiling_keeps_the_defaults_instead_of_widening(tmp_path):
    cfg = dict(CONFIG, params=CONFIG["params"] | {"auto.min_jaw_margin_mm": 8.0})  # above the sweep's 6.5 ceiling
    config, applied, _ = carry.apply(cfg, store(tmp_path, offer()), DEST, "table")
    assert config is cfg and applied is None


def test_the_tier_is_the_layer_digit_plus_one():
    assert [carry.tier_name(d) for d in ("table", "table-l0", "table-l1", "ship-l2", "ship-l10", None)] == [
        "carry.tier1", "carry.tier1", "carry.tier2", "carry.tier3", "carry.tier11", "carry.tier1"]


@pytest.mark.parametrize("site, key", [("ship", "grasp_depth_m"), ("table", "place_dz")])
def test_a_site_value_wins_over_the_offer_and_the_row_says_so(tmp_path, site, key):
    cfg = {**CONFIG, "sites": {s: dict(v) for s, v in CONFIG["sites"].items()}}
    cfg["sites"][site][key] = 0.02 if key == "grasp_depth_m" else 0.003
    logged = []
    ch = store(tmp_path, offer())
    config, applied, shadow = carry.apply(cfg, ch, DEST, "table", logged.append, "ship")
    assert config is cfg and applied is None  # nothing of the offer ran
    assert shadow == {"offer": "carry.tier2", "candidate": "c01", "keys": [{"grasp_depth_m": "auto.grasp_depth_m"}.get(key, key)]}
    assert "shadowed" in logged[0]
    carry.outcome(ch, applied, True)  # no outcome is credited to the offer
    assert ch.data["values"]["carry.tier2"][0]["tries"] == 0


def test_the_attempt_row_carries_the_shadow_marker(tmp_path):
    src = (OMX / "cell_auto_pick.py").read_text(encoding="utf-8")
    assert 'tried["carry_shadowed"] = carry_shadow' in src and "cell_carry_choices.apply(config, choices, dest, dest_site, log, source)" in src
