"""Temp plate slot prior (cell_slot_prior via cell_auto_pick_plan.observe/choose), 2026-11-27 temp plate panel.

The safety list it pins: no slots means no change; a bad plate fit, a slot miss over 8 mm / 5 deg / 4 mm across or a tier
reading off a whole tier leaves the free path; foreground on the plate outside every slot turns the prior off; blobs off
the plate are never targets; depth and side half a tier apart hold the slot; an unmeasured slot is SITE_NOT_MEASURED;
the jaws never close along a pocket; a neighbour of unknown height counts as 3 tiers; only snapped objects use the
site's finger_params and the cell defaults stay; a side past the view still blocks.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

import cv2
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy" / "robot" / "omx"))

import cell_slot_prior as sp  # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures" / "omx_temp_plate_1127"
STEP = 0.0324
SLOTS = [{"name": f"s{i}", "xy": [0.045 * i, 0.2], "yaw_deg": 90.0, "pocket_mm": [30.8, 96]} for i in (-1, 0, 1)]


def px(xy, _z):  # 1 px per mm, no parallax
    return (500 + 1000 * xy[0], 500 - 1000 * xy[1])


def blob(x_mm, y_mm, **extra):
    c = px((x_mm / 1000, y_mm / 1000), 0)
    return {"centre_mm": [x_mm, y_mm], "hull_px": [[c[0] - 5, c[1] - 5], [c[0] + 5, c[1] - 5], [c[0] + 5, c[1] + 5],
                                                  [c[0] - 5, c[1] + 5]], "matched": False, "object": None, **extra}


def box(x_mm, y_mm, axis=90.0):
    return blob(x_mm, y_mm, matched=True, object="c3", long_axis_deg=axis, length_mm=90.0, width_mm=30.0)


ENTRIES = {"c3": {"id": "c3", "length_mm": 90, "width_mm": 30}}


def run(base, tops, found=None, sites=None, side=None):
    found = found if found is not None else {}
    return sp.apply(base, SLOTS, tops, sites=sites or {}, surface_z=0.0, step_m=STEP, pixel_fn=px,
                    redetect=lambda outline, extra: found.get(next(s["name"] for s in SLOTS if sp._inside(
                        outline, px(s["xy"], 0))), []), entries=ENTRIES, side_mm=side)


# -- pure rules ---------------------------------------------------------------------------------------------------------

def test_plate_fit_missing_or_over_3mm_1deg_turns_the_prior_off():
    assert sp.active({})[0] is None
    assert sp.active({"slots": SLOTS})[0] is None  # slots without a measured fit
    assert sp.active({"slots": SLOTS, "slots_fit": {"residual_mm": 3.1, "residual_deg": 0.2}})[0] is None
    assert sp.active({"slots": SLOTS, "slots_fit": {"residual_mm": 1.0, "residual_deg": 1.1}})[0] is None
    assert sp.active({"slots": SLOTS, "slots_fit": {"residual_mm": 3.0, "residual_deg": 1.0}})[0] == SLOTS
    assert sp.active({"slots": SLOTS, "slots_fit": {"residual_mm": 1, "residual_deg": 0}, "tier_of": "plate"})[0] is None


def test_tier_count_only_within_7mm_of_a_whole_tier():
    assert sp.tier_of(97.2, 32.4) == 3 and sp.tier_of(64.8 - 6.9, 32.4) == 2 and sp.tier_of(-3.0, 32.4) == 0
    assert sp.tier_of(97.2 + 7.5, 32.4) is None and sp.tier_of(48.6, 32.4) is None
    assert sp.tier_of(4 * 32.4, 32.4) is None and sp.tier_of(float("nan"), 32.4) is None and sp.tier_of(None, 32.4) is None


@pytest.mark.parametrize("dx,dy,axis,ok", [
    (1.5, 5.0, 92.0, True),    # inside every band: snapped
    (4.5, 0.0, 90.0, False),   # 4.5 mm across the pocket axis
    (0.0, 0.0, 95.5, False),   # 5.5 deg turned
    (0.0, 8.5, 90.0, False),   # 8.5 mm from the slot centre
])
def test_snap_bands(dx, dy, axis, ok):
    got = sp.snap(box(dx, 200 + dy, axis), SLOTS[1], 96.0, 90.0)
    assert (got is not None) == ok
    if ok:
        assert got["centre_mm"] == [0.0, 203.0]  # across offset gone, along clamped to the 3 mm the pocket allows
        assert got["long_axis_deg"] % 180 == 90.0 and got["slot_seen"]["across_mm"] == -1.5


def test_jaws_never_close_along_a_pocket():
    o = {"slot_yaw_deg": 90.0}
    assert sp.across(o, 180.0) and sp.across(o, 2.9) and sp.across(o, 362.5)
    assert not sp.across(o, 90.0) and not sp.across(o, 3.5)


# -- apply ----------------------------------------------------------------------------------------------------------------

def test_off_plate_blob_is_never_a_target_and_a_slot_box_snaps():
    tops = {s["name"]: 3 * 32.4 for s in SLOTS}
    out, note = run([blob(200.0, 50.0), box(0.0, 200.0)], tops, {"s0": [box(1.0, 201.0)]})
    assert note["prior"] == "on" and note["outside"] == 1
    off, snapped = out
    assert off["refuse"].startswith("outside the plate's slots")
    assert snapped["slot"] == "s0" and snapped["layers_below"] == 2 and snapped["dz_m"] == round(2 * STEP, 4)
    assert snapped["slot_params"] is True and "refuse" not in snapped


def test_foreground_on_the_plate_outside_every_slot_turns_the_prior_off():
    base = [blob(-22.5, 200.0), box(0.0, 200.0)]  # between pockets s-1 and s0, inside the plate's outline
    tops = {s["name"]: 97.2 for s in SLOTS}
    out, note = run(base, tops, {"s0": [box(0.0, 200.0)]})
    assert note["prior"] == "off" and out is base


def test_unknown_or_off_band_tiers_leave_the_slot_to_the_free_path():
    base = [box(0.0, 200.0)]
    for tops in ({}, {"s0": 97.2 + 8.0}):
        out, note = run(base, tops, {"s0": [box(0.0, 200.0)]})
        assert out == base and "slot" not in out[0]


def test_two_blobs_in_a_slot_are_not_explained():
    base = [box(0.0, 200.0)]
    out, _ = run(base, {s["name"]: 97.2 for s in SLOTS}, {"s0": [box(0.0, 200.0), blob(0.0, 240.0)]})
    assert out == base


def test_neighbour_of_unknown_height_counts_as_three_tiers():
    tops = {"s-1": 2 * 32.4, "s0": 2 * 32.4}  # s1 unknown
    out, _ = run([box(0.0, 200.0)], tops, {"s0": [box(0.0, 200.0)]})
    assert out[0]["slot"] == "s0" and out[0]["slot_params"] is False
    tops["s1"] = 32.4
    out, _ = run([box(0.0, 200.0)], tops, {"s0": [box(0.0, 200.0)]})
    assert out[0]["slot_params"] is True


def test_depth_and_side_half_a_tier_apart_hold_the_slot():
    tops = {s["name"]: 97.2 for s in SLOTS}
    out, _ = run([box(0.0, 200.0)], tops, {"s0": [box(0.0, 200.0)]}, side={"s0": 97.2 - 16.0})
    assert "held" in out[0]["refuse"]
    out, _ = run([box(0.0, 200.0)], tops, {"s0": [box(0.0, 200.0)]}, side={"s0": 97.2 - 15.0})
    assert "refuse" not in out[0]


def test_an_unmeasured_registered_slot_is_site_not_measured():
    tops = {s["name"]: 97.2 for s in SLOTS}
    out, _ = run([box(0.0, 200.0)], tops, {"s0": [box(0.0, 200.0)]}, sites={"s0": {"status": "planned"}})
    assert out[0]["refuse"].startswith("SITE_NOT_MEASURED")
    out, _ = run([box(0.0, 200.0)], {}, sites={"s0": {"status": "planned"}})  # unknown tiers: the free-path blob too
    assert out[0]["refuse"].startswith("SITE_NOT_MEASURED")


def test_tiers_read_from_depth_where_each_count_would_show():
    import cell_depth  # noqa: F401  (read_tops uses its height_at)

    heights = np.full((1000, 1000), 15.5)  # the arm plate 15.5 mm over the table: arm z 0
    to_depth = np.float32([[1, 0, 0], [0, 1, 0]])
    for s, top in zip(SLOTS, (97.2, 2 * 32.4 + 10.0, 0.0)):
        c = px(s["xy"], 0)
        heights[int(c[1]) - 6:int(c[1]) + 7, int(c[0]) - 6:int(c[0]) + 7] = 15.5 + top
    got = sp.read_tops(heights, to_depth, 15.5, SLOTS, 0.0, STEP, px)
    assert got == {"s-1": 97.2, "s1": 0.0}  # s0 reads 74.8 mm: no whole tier, unknown


# -- choose ---------------------------------------------------------------------------------------------------------------

def _choose_cfg(slots: bool):
    site = {"start": [0.0, 0.2], "yaw_deg": 90.0, "finger_params": {"auto.neighbour_clear_mm": 3.0}}
    if slots:
        site.update(slots=SLOTS, slots_fit={"residual_mm": 1.0, "residual_deg": 0.2})
    return {"params": {"auto.neighbour_clear_mm": 14.0}, "sites": {"plate": site}}


def _patch(monkeypatch, cap, seen, pixel=(100, 100)):
    monkeypatch.setattr(cap, "predicted_pixel", lambda *a: pixel)
    monkeypatch.setattr(cap, "past_pan_limit", lambda *a: None)
    monkeypatch.setattr(cap, "past_park_reach", lambda *a: None)
    monkeypatch.setattr(cap, "reachable_ends", lambda *a: [])
    monkeypatch.setattr(cap, "finger_room", lambda _m, _r, _pf, o, _e, params, **_kw:
                        seen.append((o.get("slot"), params["auto.neighbour_clear_mm"])) or {"margin_mm": None, "free_mm": [7.0, 7.0]})


def _obj(**extra):
    return {"raw_m": [0.0, 0.2], "matched": True, "object": "c3", "long_axis_deg": 90.0, "centre_mm": [0.0, 200.0], **extra}


CAT = [{"id": "c3", "length_mm": 90, "width_mm": 30, "grasp": {"jaw_axis_deg_from_long": 90}}]


def test_site_finger_params_reach_only_snapped_slot_objects(monkeypatch):
    import cell_auto_pick_plan as cap

    seen = []
    _patch(monkeypatch, cap, seen)
    objs = [_obj(slot="s0", slot_yaw_deg=90.0, slot_params=True), _obj(slot="s1", slot_yaw_deg=90.0, slot_params=False),
            _obj(raw_m=[0.0, 0.21])]
    cap.choose(None, _choose_cfg(True), {}, "plate", "belt", [0.1, -0.05], [0, 0, 300, 300], objs, None, CAT, {}, [], None)
    assert sorted(seen, key=str) == sorted([("s0", 3.0), ("s1", 14.0), (None, 14.0)], key=str)
    seen.clear()  # without slots the site's finger_params still cover the whole site, as before
    cap.choose(None, _choose_cfg(False), {}, "plate", "belt", [0.1, -0.05], [0, 0, 300, 300], [_obj()], None, CAT, {}, [], None)
    assert seen == [(None, 3.0)]


def test_a_refused_object_never_reaches_the_finger_check(monkeypatch):
    import cell_auto_pick_plan as cap

    seen = []
    _patch(monkeypatch, cap, seen)
    _, refused = cap.choose(None, _choose_cfg(True), {}, "plate", "belt", [0.1, -0.05], [0, 0, 300, 300],
                            [_obj(refuse="SITE_NOT_MEASURED: slot s0")], None, CAT, {}, [], None)
    assert seen == [] and refused[0]["why"] == "SITE_NOT_MEASURED: slot s0"


def test_a_side_past_the_view_still_blocks_a_slot_object(monkeypatch):
    import cell_auto_pick_plan as cap

    seen = []
    _patch(monkeypatch, cap, seen, pixel=(295, 100))  # within 12 px of the ROI edge
    _, refused = cap.choose(None, _choose_cfg(True), {}, "plate", "belt", [0.1, -0.05], [0, 0, 300, 300],
                            [_obj(slot="s0", slot_yaw_deg=90.0, slot_params=True)], None, CAT, {}, [], None)
    assert seen == [] and refused[0]["why"] == "not inside the camera view"


def test_closing_along_the_pocket_is_refused(monkeypatch, tmp_path):
    import cell_auto_pick_plan as cap
    import cell_choices

    seen = []
    _patch(monkeypatch, cap, seen)
    monkeypatch.setattr(cap, "finger_room", lambda *a, **k: {"margin_mm": 4.0, "free_mm": [9.0, 9.0], "mark_half_mm": None})
    monkeypatch.setattr(cap.cell_jaw_axis, "offer_measured", lambda *a: None)
    monkeypatch.setattr(cap.cell_jaw_axis, "offset_for", lambda *a: (0.0, None))
    monkeypatch.setattr(cap.cell_place_fit, "options", lambda *a: ([], "stop here"))
    cfg = _choose_cfg(True)
    for axis, why in ((90.0, "place: stop here"), (80.0, "closing axis not across slot s0")):
        _, refused = cap.choose(None, cfg, {}, "plate", "belt", [0.1, -0.05], [0, 0, 300, 300],
                                [_obj(long_axis_deg=axis, slot="s0", slot_yaw_deg=90.0, slot_params=True)], None, CAT,
                                {"regions": []}, cell_choices.Choices(tmp_path / "c.json"), tmp_path)
        assert refused[0]["why"] == why


def test_a_square_box_in_a_slot_is_closed_across_the_pocket(monkeypatch):
    import cell_auto_pick_plan as cap

    seen = []
    _patch(monkeypatch, cap, seen)
    monkeypatch.setattr(cap, "finger_room", lambda _m, _r, _pf, o, closing, *a, **k: seen.append(closing) or {"margin_mm": None, "free_mm": [1.0, 1.0]})
    cfg = _choose_cfg(True)
    cfg["sites"]["plate"]["yaw_deg"] = 60.0  # the pocket (90) is 30 deg off the site yaw: never squared to the site
    cat = [{"id": "c1", "length_mm": 30, "width_mm": 30, "grasp": {"jaw_axis_deg_from_long": 90}}]
    _, refused = cap.choose(None, cfg, {}, "plate", "belt", [0.1, -0.05], [0, 0, 300, 300],
                            [_obj(object="c1", slot="s0", slot_yaw_deg=90.0, slot_params=True)], None, cat, {}, [], None)
    assert [c % 180 for c in seen] == [0.0] and refused[0]["why"].endswith("on either closing axis")


def test_cell_clearance_defaults_are_unchanged():
    import cell_params as prm

    assert [prm.default(k) for k in ("auto.neighbour_clear_mm", "auto.min_jaw_margin_mm", "auto.finger_mm")] == [0.0, 2.0, 8.0]


# -- the 2026-11-27 frame -------------------------------------------------------------------------------------------------

def _scene(arm, slots, tops=True):
    data = json.loads((FIX / "scene.json").read_text())
    a, site = data["arms"][arm], f"temp_plate_{arm}"
    s = dict(a["site"])
    if slots:
        s.update(slots=data["slots"][arm], slots_fit={"residual_mm": 1.0, "residual_deg": 0.3},
                 finger_params={"auto.neighbour_clear_mm": 3.0})
    config = {"sites": {site: s}, "cameras": {"top": a["camera"]}, "params": data["params"], "objects": {"hsv": data["hsv"]},
              "plan": data["plan"], **({"want": a["want"]} if a.get("want") else {})}
    tops_mm = {x["name"]: 3 * 32.4 for x in data["slots"][arm]} if slots and tops else None
    return config, {"sites": {site: a["record"]}}, data["catalog"]["objects"], site, tops_mm


def _pick(monkeypatch, tmp_path, arm, slots, tops=True):
    import cell_auto_pick_plan as cap
    import cell_choices

    config, cal, catalog, site, tops_mm = _scene(arm, slots, tops)
    fake = lambda config, site, dest, xy, o, *a, **k: ({}, {"x": o["raw_m"][0], "y": o["raw_m"][1]}, {}, 0.04, 0, {})  # noqa: E731
    monkeypatch.setattr(cap, "plan_pick", fake)
    if "cell_auto_pick" in sys.modules:
        monkeypatch.setattr(sys.modules["cell_auto_pick"], "plan_pick", fake, raising=False)
    monkeypatch.setattr(cap.cell_place_fit, "options", lambda config, dest, xy, *a: ([(tuple(xy), 0.0)], None))
    img = cv2.imread(str(FIX / "top.jpg"))
    roi = config["sites"][site]["auto_roi"]
    _, mask, objects, error = cap.observe(None, config, cal, site, roi, catalog, image=img, slot_tops_mm=tops_mm)
    assert error is None
    usable, refused = cap.choose(None, config, cal, site, site, config["sites"][site]["start"], roi, objects, mask, catalog,
                                 {"regions": []}, cell_choices.Choices(tmp_path / "c.json"), tmp_path)
    return objects, usable, refused


# what the cell refused on 2026-11-27 (cell_auto_pick --dry-run), before this change: the free path, unchanged
WITHOUT_SLOTS = {
    "a": [([9.0, 193.1], "container-3", "neighbour clearance: 15.0 / 7.0 mm free beside it"),
          ([-66.9, 194.4], "container-3", "neighbour clearance: 8.0 / 20.0 mm free beside it"),
          ([-84.2, 127.2], None, "no catalogue match"), ([84.9, 186.3], None, "no catalogue match"),
          ([96.1, 230.5], None, "no catalogue match"),
          ([79.1, 141.5], "container-2", "neighbour clearance: 6.0 / 26.0 mm free beside it")],
    "b": [([61.2, -152.5], "container-2", "wanted object container-3, got container-2"),
          ([38.0, -212.5], None, "tangled blob"), ([10.5, -123.0], None, "no catalogue match"),
          ([-33.0, -123.3], None, "no catalogue match"), ([-41.0, -213.7], None, "tangled blob"),
          ([-103.5, -192.4], None, "tangled blob")],
}


@pytest.mark.parametrize("arm", ["a", "b"])
def test_frame_without_slots_is_judged_as_before(monkeypatch, tmp_path, arm):
    _, usable, refused = _pick(monkeypatch, tmp_path, arm, slots=False)
    assert usable == []
    assert [(r["centre_mm"], r["object"], r["why"]) for r in refused] == WITHOUT_SLOTS[arm]


@pytest.mark.parametrize("arm", ["a", "b"])
def test_frame_with_slots_drops_every_table_piece(monkeypatch, tmp_path, arm):
    objects, usable, refused = _pick(monkeypatch, tmp_path, arm, slots=True)
    off = [o for o in objects if (o.get("refuse") or "").startswith("outside the plate")]
    # the yellow table read as container-2 beside both plates (A 79,142; B 61,-153): never a target now
    assert {tuple(o["centre_mm"]) for o in off} == ({(79.1, 141.5), (84.9, 186.3), (96.1, 230.5), (-84.2, 127.2)} if arm == "a"
                                                   else {(61.2, -152.5), (10.5, -123.0), (-33.0, -123.3)})
    assert not any(u["object"].get("refuse") or not u["object"].get("slot") for u in usable)
    per_slot = {}
    for o in objects:
        if o.get("slot"):
            per_slot[o["slot"]] = per_slot.get(o["slot"], 0) + 1
    assert all(n == 1 for n in per_slot.values())


def test_frame_with_slots_passes_the_one_whole_stack_top_and_holds_the_cut_ones(monkeypatch, tmp_path):
    _, usable, refused = _pick(monkeypatch, tmp_path, "b", slots=True)
    # B: the pink 3-tier stack's top reads 94 x 33 mm at its real height and snaps to tmp-b-3; the orange and yellow
    # stacks' tops run past the frame and stay tangled on the free path
    assert [(u["object"]["slot"], u["object"]["object"]) for u in usable] == [("tmp-b-3", "container-3")]
    assert usable[0]["object"]["dz_m"] == round(2 * STEP, 4)
    assert sorted(r["why"] for r in refused if not r["why"].startswith("outside")) == ["tangled blob", "tangled blob"]
    _, usable_a, refused_a = _pick(monkeypatch, tmp_path, "a", slots=True)
    # A: both stack tops run past the frame bottom, so nothing snaps: the free path refuses them as before
    assert usable_a == [] and sum(r["why"].startswith("neighbour clearance") for r in refused_a) == 2


def test_frame_with_slots_but_no_depth_never_snaps(monkeypatch, tmp_path):
    objects, usable, _ = _pick(monkeypatch, tmp_path, "b", slots=True, tops=False)
    assert usable == [] and not any(o.get("slot") for o in objects)
