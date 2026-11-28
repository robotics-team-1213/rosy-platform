"""Temp plate height reference and slot measurement (cell_temp_plate, cell_slot_prior.depth_tops), 2026-11-27 18:10 follow-up.

Pins: the tier reference is the plate's own flat top beside the pockets, read on the median of several depth captures, and
no deck reading leaves every tier unknown (the prior then never applies); the plate-pose tool gives slots only when the
arm-side edge and both long sides are seen, the plate looks its CAD size through the camera model (+-3 %) and the residual
is inside the prior's 3 mm / 1 deg; the 2026-11-27 frame (plates cut by the frame bottom, one long side under the stacks)
is refused on both arms.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
import sys

import cv2
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy" / "robot" / "omx"))

import cell_slot_prior as sp  # noqa: E402
import cell_temp_plate as tp  # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures" / "omx_temp_plate_1127"
STEP = 0.0324
NAMES = ["s1", "s2", "s3"]
PLATE = (0.0, 0.2, 90.0)  # plate pose in the arm frame: middle pocket 200 mm out on +y
K = 1100.0  # synthetic camera: px per m, no parallax


def px(p, _z):
    return (320 + K * p[0], 20 + K * p[1])


# -- CAD geometry ---------------------------------------------------------------------------------------------------------

def test_cad_v12_fan_and_slots_round_trip():
    assert tp.FAN_DEG == pytest.approx(13.77, abs=0.01)  # scad: 13.76 deg between lanes
    behind = tp.slots_at((-0.2, 0.0, 180.0), NAMES)  # a plate on the arm's -x side: bearings wrap at +-180 deg
    assert tp.pose_of(behind[::-1]) == pytest.approx((-0.2, 0.0, -180.0), abs=1e-4)
    pose = (0.2 * math.cos(math.radians(95)), 0.2 * math.sin(math.radians(95)), 95.0)  # lanes facing the arm axis at 0
    slots = tp.slots_at(pose, NAMES)
    assert [s["yaw_deg"] for s in slots] == [108.8, 95.0, 81.2]
    assert all(math.hypot(*s["xy"]) == pytest.approx(0.2, abs=1e-4) for s in slots)  # every pocket centre 200 mm out
    assert tp.pose_of(slots) == pytest.approx(pose, abs=1e-4)
    assert tp.pose_of(slots[:2]) is None and tp.deck_points(slots[:2]) == []
    deck = np.asarray(tp.deck_points(slots))
    assert len(deck) == 13 and np.hypot(*(deck - deck.mean(0)).T).max() == pytest.approx(0.030, abs=1e-4)
    assert math.hypot(*deck.mean(0)) == pytest.approx(0.2 - 0.0615, abs=1e-4)  # the F3-F4 strip, 61.5 mm toward the arm


# -- the height reference: plate deck, median of captures -----------------------------------------------------------------

def _heights(deck_mm=13.6, tops=(97.2, 64.8, 32.4), cover_deck=0):
    """A depth height map (mm above the table, aligned 1:1 with px) of a plate at PLATE: its arm-side flat top at deck_mm, the
    pocket floor 5.6 mm lower, and each slot's stack top at floor + top. cover_deck hides that many deck samples."""
    slots = tp.slots_at(PLATE, NAMES)
    h = np.full((400, 640), 1.0)  # the table
    for k, p in enumerate(tp.deck_points(slots)):
        x, y = (int(round(v)) for v in px(p, 0))
        h[y - 3:y + 4, x - 3:x + 4] = 120.0 if k < cover_deck else deck_mm
    for s, top in zip(slots, tops):
        x, y = (int(round(v)) for v in px(s["xy"], 0))
        h[y - 6:y + 7, x - 6:x + 7] = deck_mm - 5.6 + top
    return h, slots


IDENT = np.float32([[1, 0, 0], [0, 1, 0]])


def test_deck_floor_reads_the_plate_top_and_refuses_what_is_not_it():
    h, slots = _heights()
    assert sp.deck_floor(h, IDENT, slots, 0.0, px) == pytest.approx(8.0)
    h, _ = _heights(cover_deck=5)  # 5 of 13 samples under a stack: more than a third off
    assert sp.deck_floor(h, IDENT, slots, 0.0, px) is None
    h, _ = _heights(deck_mm=8.0)  # the strip reads a pocket floor (slots fitted off the plate): not the deck
    assert sp.deck_floor(h, IDENT, slots, 0.0, px) is None
    assert sp.deck_floor(h, IDENT, slots[:2], 0.0, px) is None


def test_tiers_are_counted_above_the_deck_floor():
    h, slots = _heights(deck_mm=17.0)  # the table plane fit 3.4 mm low: deck and stacks move together
    for surface_z in (0.0, -0.004, -0.01):  # the site's surface_z only places pixels; the floor comes from the deck
        floor = sp.deck_floor(h, IDENT, slots, surface_z, px)
        tops = sp.read_tops(h, IDENT, floor, slots, surface_z, STEP, px)
        assert floor == pytest.approx(11.4) and {k: sp.tier_of(v, 32.4) for k, v in tops.items()} == {"s1": 3, "s2": 2, "s3": 1}


def _captures(monkeypatch, maps):
    import cell_depth
    import cell_depth_slots
    import cell_zone_verification as zones

    it = iter(maps)
    monkeypatch.setattr(zones, "_depth_after", lambda config, after: next(it))
    monkeypatch.setattr(cell_depth, "table_plane", lambda raw: None)
    monkeypatch.setattr(cell_depth, "height_map", lambda raw, plane: np.where(raw == 0, np.nan, raw / 10))  # 0: no depth
    monkeypatch.setattr(cell_depth_slots, "frame_alignment", lambda depth, colour: (IDENT, 0.0))


def _frame(h):
    return (np.round(h * 10).astype(np.uint16), {}, None)


def test_depth_tops_takes_the_median_of_three_captures(monkeypatch):
    good, slots = _heights()
    jumpy, _ = _heights(deck_mm=13.6 + 6.0)  # one capture's plate and stacks 6 mm off (cf. 13.9 / 18.2 mm on 11-27)
    jumpy[:] = np.where(jumpy > 50, jumpy + 15.0, jumpy)  # and its stack tops another 15 mm
    _captures(monkeypatch, [_frame(jumpy), _frame(good), _frame(good)])  # the first alone reads no deck
    tops = sp.depth_tops({}, slots, 0.0, STEP, px, None)
    assert {k: sp.tier_of(v, 32.4) for k, v in tops.items()} == {"s1": 3, "s2": 2, "s3": 1}


def test_depth_tops_is_unknown_without_most_captures_or_the_deck(monkeypatch):
    good, slots = _heights()
    jumpy, _ = _heights(deck_mm=13.6 + 6.0)
    _captures(monkeypatch, [_frame(good), _frame(jumpy), _frame(jumpy)])
    assert sp.depth_tops({}, slots, 0.0, STEP, px, None) == {}  # most captures off the deck band: unknown, not the good one
    _captures(monkeypatch, [_frame(good), _frame(good * 0), _frame(good * 0)])  # a pixel only one capture saw is unknown
    assert sp.depth_tops({}, slots, 0.0, STEP, px, None) == {}
    _captures(monkeypatch, [_frame(good), (None, None, "depth-d435.lock busy"), (None, None, "timeout")])
    assert sp.depth_tops({}, slots, 0.0, STEP, px, None) == {}
    covered, _ = _heights(cover_deck=13)
    _captures(monkeypatch, [_frame(covered)] * 3)
    assert sp.depth_tops({}, slots, 0.0, STEP, px, None) == {}  # every tier unknown: the prior leaves the free path alone


# -- plate pose from the top camera ---------------------------------------------------------------------------------------

def render(pose, scale=1.0, h=250, stack=False):
    """Yellow table, the plate outline in white, an orange container in each pocket; h cuts the plate's far end off."""
    img = np.full((h, 640, 3), (0, 190, 240), np.uint8)
    pts, _ = tp.outline_mm(0.5)
    cv2.fillPoly(img, [cv2.convexHull(np.float32([px(p, 0) for p in tp.to_arm(pose, pts, scale)])).astype(np.int32)], (235, 235, 228))
    boxes = [(i, 0.0, 0.0) for i in range(3)] + ([(0, -18.0, 30.0)] if stack else [])  # a stack leaning past the left side
    for i, dx, dy in boxes:
        c = [tp.lane(i, (sx * 15 + dx, sy * 45 + dy)) for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
        cv2.fillPoly(img, [np.int32([px(p, 0) for p in tp.to_arm(pose, c, scale)])], (40, 110, 240))
    return img


SITE = {"surface_z": 0.0, "auto_roi": [200, 140, 440, 250], "slots": tp.slots_at(PLATE, NAMES)}
TRUE = (0.004, 0.203, 92.5)  # the plate moved 4.5 mm and 2.5 deg from where the config last had it


def test_cut_plate_with_both_long_sides_gives_its_slots():
    out = tp.measure(render(TRUE), px, SITE)
    assert "refuse" not in out and out["matched"]["far"] == 0  # the far end is past the frame
    assert out["slots_fit"]["residual_mm"] <= 1.0 and out["slots_fit"]["residual_deg"] <= 0.5
    for got, want in zip(out["slots"], tp.slots_at(TRUE, NAMES)):
        assert got["name"] == want["name"] and np.linalg.norm(np.subtract(got["xy"], want["xy"])) <= 0.001
        assert abs(got["yaw_deg"] - want["yaw_deg"]) <= 0.3


@pytest.mark.parametrize("img,why", [
    (render(TRUE, stack=True), "plate looks 0.9"),         # one long side half hidden: the size it reads is wrong, refused
    (render(TRUE, scale=1.15), "plate looks 1.15x"),       # the camera model off at plate height
    (render(TRUE, h=185), "too little outline matched"),   # the frame cuts the plate 15 mm past its arm-side edge
    (np.full((250, 640, 3), (0, 190, 240), np.uint8), "no plate-coloured region"),
])
def test_what_the_frame_cannot_fix_is_refused(img, why):
    out = tp.measure(img, px, SITE)
    assert out["refuse"].startswith(why) and "slots" not in out


# the 2026-11-27 frame: both plates run past the frame bottom and the stacks lean over one long side
@pytest.mark.parametrize("arm", ["a", "b"])
def test_frame_1127_is_refused_on_both_arms(arm):
    data = json.loads((FIX / "scene.json").read_text())
    a, site = data["arms"][arm], f"temp_plate_{arm}"
    config = {"sites": {site: dict(a["site"])}, "cameras": {"top": a["camera"]}}
    calibration = {"sites": {site: a["record"]}}
    out = tp.measure(cv2.imread(str(FIX / "top.jpg")), lambda p, z: sp.pixel_at(config, calibration, site, p, z),
                     {**a["site"], "slots": data["slots"][arm]})
    assert out["refuse"].startswith("too little outline matched") and "slots" not in out
    sides = sorted((out["matched"]["left"], out["matched"]["right"]))
    assert sides[0] < 10 <= sides[1] and out["matched"]["arm"] >= 45  # the arm-side edge and one long side are found
