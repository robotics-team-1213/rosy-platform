"""omx_real2sim without the cell or MuJoCo: temp plates measured from a synthetic top frame, snapshot diff, the Layout choice."""
import json
import math
from pathlib import Path
import sys

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools/sim"))
import omx_real2sim as r2s  # noqa: E402
import omx_two_arm_sites as sites  # noqa: E402

SHAPE = dict(step_deg=13.6, radius_m=.217)
POSES = dict(a=(-.0378, -.1672, math.radians(1.)), b=(-.0334, .1474, math.radians(-2.)))
COVERED = dict(a=2, b=1)  # a container sits in this lane, the others show their dark pad


def frame(layout, hide=()):
    img = np.full((480, 640, 3), (60, 200, 200), np.uint8)  # the yellow table (hue 30, clear of the orange mask's < 22)
    cam = r2s.Camera(layout.fixture["real_cameras"]["top"], img.shape[:2])
    box_h = sites.CONTAINER[layout.choices["ship_source"]][2]
    for tag, pose in POSES.items():
        for k, local in r2s.plate_lanes(SHAPE).items():
            if (tag, k) in hide:
                continue
            (x, y), yaw = r2s.place(local, pose)
            on_top = k == COVERED[tag]
            z = layout.deck_z + (box_h if on_top else 0.)
            corners = [cam.project((x + a * .045 * math.cos(yaw) - b * .015 * math.sin(yaw),
                                    y + a * .045 * math.sin(yaw) + b * .015 * math.cos(yaw), z))
                       for a, b in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
            cv2.fillPoly(img, [np.round(corners).astype(np.int32)], (40, 110, 240) if on_top else (30, 30, 30))
    return img


def truth(tag, k):
    (x, y), yaw = r2s.place(r2s.plate_lanes(SHAPE)[k], POSES[tag])
    return (x, y), r2s.fold(yaw)


def test_plates_are_found_with_their_covered_lane():
    layout = sites.Layout()
    got = r2s.measure_temp_plates(frame(layout), layout)
    assert got["shape"]["step_deg"] == pytest.approx(SHAPE["step_deg"], abs=1.)
    for tag in "ab":
        lanes = {l["lane"]: l for l in got["plates"][tag]["lanes"]}
        assert sorted(lanes) == [1, 2, 3]
        assert got["plates"][tag]["seen"] == 3
        for k, lane in lanes.items():
            xy, yaw = truth(tag, k)
            assert math.dist(lane["xy"], xy) < .003, (tag, k)
            assert abs(lane["yaw_deg"] - math.degrees(yaw)) < 1.5, (tag, k)
        assert lanes[COVERED[tag]]["source"] == "container"
    assert max(got["camera_check"]["worst_mm"]) < 3


def test_a_plate_seen_by_one_lane_comes_from_the_previous_shape():
    layout = sites.Layout()
    first = r2s.measure_temp_plates(frame(layout), layout)
    prev = dict(plates={t: p["lanes"] for t, p in first["plates"].items()}, shape=first["shape"])
    again = r2s.measure_temp_plates(frame(layout, hide={("b", 2), ("b", 3)}), layout, prev)  # only b's container lane left
    assert again["plates"]["b"]["seen"] == 1
    for lane in again["plates"]["b"]["lanes"]:
        assert math.dist(lane["xy"], truth("b", lane["lane"])[0]) < .004


def test_two_lanes_give_the_fan():
    a, b = truth("a", 1), truth("a", 3)
    shape = r2s.fit_shape(a, b, 2)
    assert shape["step_deg"] == pytest.approx(SHAPE["step_deg"], abs=.05)
    assert shape["radius_m"] == pytest.approx(SHAPE["radius_m"], abs=.001)


def snap(dx=0.):
    lanes = {t: [dict(lane=k, xy=[truth(t, k)[0][0] + dx, truth(t, k)[0][1]], yaw_deg=round(math.degrees(truth(t, k)[1]), 1))
                 for k in (1, 2, 3)] for t in "ab"}
    return dict(schema=r2s.SCHEMA, camera=dict(top=[1]), items=dict(temp_plates=dict(plates=lanes, shape=SHAPE)))


def test_diff_names_moved_lanes_and_the_stages_that_read_them():
    assert r2s.diff(snap(), snap(.001)) == ({}, [])
    changed, rerun = r2s.diff(snap(), snap(.02))
    assert len(changed["temp_plates"]) == 6
    assert rerun == sorted(s for s, (item, *_) in r2s.STAGES.items() if item == "temp_plates")
    moved = snap()
    moved["camera"] = dict(top=[2])
    assert r2s.diff(snap(), moved)[1] == sorted(r2s.STAGES)


def test_layout_reads_a_snapshot_choice(tmp_path):
    path = tmp_path / "snap.json"
    path.write_text(json.dumps(snap()), encoding="utf-8")
    layout = sites.Layout(cell_snapshot=str(path), temp_lanes="snapshot")
    for t in "ab":
        for k in (1, 2, 3):
            assert math.dist(layout.sites[f"tmp-{t}-{k}"]["xy"], truth(t, k)[0]) < 1e-4
    with pytest.raises(ValueError, match="cell_snapshot"):
        sites.Layout(temp_lanes="snapshot")
    broken = snap()
    broken["items"]["temp_plates"]["plates"]["a"].pop()
    path.write_text(json.dumps(broken), encoding="utf-8")
    with pytest.raises(ValueError, match="plate a"):
        sites.Layout(cell_snapshot=str(path), temp_lanes="snapshot")


def test_the_committed_snapshot_loads():
    snaps = sorted((ROOT / "deploy/robot/omx/sim/cell_snapshots").glob("*.json"))
    assert snaps
    for p in snaps:
        layout = sites.Layout(cell_snapshot=str(p.relative_to(ROOT)), temp_lanes="snapshot")
        assert all(f"tmp-{t}-{k}" in layout.sites for t in "ab" for k in (1, 2, 3))


def test_a_previous_snapshot_without_a_plate_still_measures_both():
    layout = sites.Layout()
    first = r2s.measure_temp_plates(frame(layout), layout)
    prev = dict(plates={"a": first["plates"]["a"]["lanes"]}, shape=first["shape"])  # plate b was not measured last time
    again = r2s.measure_temp_plates(frame(layout), layout, prev)
    assert again["plates"]["b"]["seen"] == 3
