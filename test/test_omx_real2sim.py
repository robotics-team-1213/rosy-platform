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
    assert rerun == sorted(s for s, (items, *_) in r2s.STAGES.items() if "temp_plates" in items)
    moved = snap()
    moved["camera"] = dict(top=[2])
    assert r2s.diff(snap(), moved)[1] == sorted(r2s.STAGES)
    shipped, moved_ship = snap(), snap()
    shipped["items"]["ship"] = dict(stern_x_m=.170, centre_y_m=-.011, yaw_deg=0.)
    moved_ship["items"]["ship"] = dict(stern_x_m=.180, centre_y_m=-.011, yaw_deg=0.)
    changed, rerun = r2s.diff(shipped, moved_ship)
    assert list(changed) == ["ship"] and rerun == sorted(r2s.STAGES)  # every stage stands on the ship


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


def test_pads_cut_short_still_hold_their_lane():
    layout = sites.Layout()
    first = r2s.measure_temp_plates(frame(layout), layout)
    prev = dict(plates={t: p["lanes"] for t, p in first["plates"].items()}, shape=first["shape"])
    img = frame(layout)
    cam = r2s.Camera(layout.fixture["real_cameras"]["top"], img.shape[:2])
    for k, keep in ((2, .070), (3, .050)):  # plate b's pads lose their -x end, as in the 2026-11-09 frame
        (x, y), yaw = truth("b", k)
        far = (x - (.045 - (.09 - keep) / 2) * math.cos(yaw), y - (.045 - (.09 - keep) / 2) * math.sin(yaw))
        corners = [cam.project((far[0] + a * (.09 - keep) / 2 * math.cos(yaw) - b * .017 * math.sin(yaw),
                                far[1] + a * (.09 - keep) / 2 * math.sin(yaw) + b * .017 * math.cos(yaw), layout.deck_z))
                   for a, b in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
        cv2.fillPoly(img, [np.round(corners).astype(np.int32)], (60, 200, 200))
    got = r2s.measure_temp_plates(img, layout, prev)
    b = {l["lane"]: l for l in got["plates"]["b"]["lanes"]}
    assert got["plates"]["b"]["seen"] == 3
    assert b[2]["source"] == "pad (partial)"
    for k, lane in b.items():
        assert math.dist(lane["xy"], truth("b", k)[0]) < .003
        assert abs(lane["yaw_deg"] - math.degrees(truth("b", k)[1])) < 1.


def test_white_printed_lane_labels_across_a_pad_do_not_split_it():
    layout = sites.Layout()
    img = frame(layout)
    cam = r2s.Camera(layout.fixture["real_cameras"]["top"], img.shape[:2])
    for t, k in (("a", 1), ("b", 2), ("b", 3)):  # 2026-11-10 live cell: white R1/R3 labels & dots split pads in two
        (x, y), yaw = truth(t, k)
        stripe = [cam.project((x + a * .002 * math.cos(yaw) - b * .017 * math.sin(yaw),
                               y + a * .002 * math.sin(yaw) + b * .017 * math.cos(yaw), layout.deck_z))
                  for a, b in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
        cv2.fillPoly(img, [np.round(stripe).astype(np.int32)], (245, 245, 245))
    got = r2s.measure_temp_plates(img, layout)
    assert got["plates"]["a"]["seen"] == 3 and got["plates"]["b"]["seen"] == 3


def test_yellow_containers_and_bottom_clipped_v11_plates_are_measured():
    layout = sites.Layout()
    first = r2s.measure_temp_plates(frame(layout), layout)
    prev = dict(plates={t: p["lanes"] for t, p in first["plates"].items()}, shape=first["shape"])
    v11 = dict(step_deg=17.0, radius_m=.203)
    poses = dict(a=(-.0933, -.1676, 0.), b=(-.0906, .1668, 0.))
    img = np.full((480, 640, 3), (60, 200, 200), np.uint8)
    cam = r2s.Camera(layout.fixture["real_cameras"]["top"], img.shape[:2])
    box_h = sites.CONTAINER[layout.choices["ship_source"]][2]
    for tag, pose in poses.items():
        for k, local in r2s.plate_lanes(v11).items():
            (x, y), yaw = r2s.place(local, pose)
            on_top = k == 2 or (tag == "a" and k == 3)
            z = layout.deck_z + (box_h if on_top else 0.)
            bgr = (30, 195, 220) if k == 2 else (40, 110, 240) if on_top else (30, 30, 30)  # yellow (H 26) in lane 2, orange in a-3
            corners = [cam.project((x + a * .045 * math.cos(yaw) - b * .015 * math.sin(yaw),
                                    y + a * .045 * math.sin(yaw) + b * .015 * math.cos(yaw), z))
                       for a, b in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
            cv2.fillPoly(img, [np.round(corners).astype(np.int32)], bgr)
    got = r2s.measure_temp_plates(img, layout, prev)
    assert got["shape"]["step_deg"] == pytest.approx(17.0, abs=1.)
    for tag, pose in poses.items():
        assert got["plates"][tag]["seen"] == 3
        lanes = {l["lane"]: l for l in got["plates"][tag]["lanes"]}
        assert "container" in lanes[2]["source"]
        for k, local in r2s.plate_lanes(v11).items():
            assert math.dist(lanes[k]["xy"], r2s.place(local, pose)[0]) < .004, (tag, k)


def test_the_ship_is_found_where_its_hull_lies():
    layout = sites.Layout()
    img = np.full((480, 640, 3), (60, 200, 200), np.uint8)
    cam = r2s.Camera(layout.fixture["real_cameras"]["top"], img.shape[:2])
    pose = (.1705, -.011, math.radians(.5))
    cv2.fillPoly(img, [np.round(r2s.ship_polygon(cam, layout, pose)).astype(np.int32)], (250, 215, 150))  # light blue hull
    got = r2s.measure_ship(img, layout)
    assert got["stern_x_m"] == pytest.approx(pose[0], abs=.002)
    assert got["centre_y_m"] == pytest.approx(pose[1], abs=.002)
    assert got["iou"] > .95
    assert "error" in r2s.measure_ship(np.full((480, 640, 3), (60, 200, 200), np.uint8), layout)


def test_layout_takes_the_ship_from_a_snapshot(tmp_path):
    s = snap()
    s["items"]["ship"] = dict(stern_x_m=.1705, centre_y_m=-.011, yaw_deg=0.)
    path = tmp_path / "snap.json"
    path.write_text(json.dumps(s), encoding="utf-8")
    base, moved = sites.Layout(), sites.Layout(cell_snapshot=str(path), ship_pose="snapshot")
    a, b = base.sites["ship-stern-l0"]["xy"], moved.sites["ship-stern-l0"]["xy"]
    assert b[0] - a[0] == pytest.approx(.1705 - base.choices["ship_stern_x_m"], abs=1e-6)
    assert b[1] - a[1] == pytest.approx(-.011 - base.choices["ship_centre_y_m"], abs=1e-6)
    with pytest.raises(ValueError, match="no measured ship"):
        sites.Layout(cell_snapshot=str(_write(tmp_path, snap())), ship_pose="snapshot")  # a snapshot without a ship


def _write(tmp_path, data):
    path = tmp_path / "plain.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_the_belt_end_and_centreline_come_from_its_strip():
    layout = sites.Layout()
    img = np.full((480, 640, 3), (60, 200, 200), np.uint8)
    cam = r2s.Camera(layout.fixture["real_cameras"]["top"], img.shape[:2])
    end, y, half = .205, -.037, .0425
    strip = [cam.project((x, yy, layout.belt_top)) for x, yy in ((end, y - half), (.40, y - half), (.40, y + half), (end, y + half))]
    cv2.fillPoly(img, [np.round(strip).astype(np.int32)], (30, 30, 30))
    got = r2s.measure_belt(img, layout)
    assert got["end_x_m"] == pytest.approx(end, abs=.003)
    assert got["centre_y_m"] == pytest.approx(y, abs=.003)
    assert got["width_m"] == pytest.approx(2 * half, abs=.006)


def test_layout_takes_the_belt_from_a_snapshot(tmp_path):
    s = snap()
    s["items"]["belt"] = dict(end_x_m=.205, centre_y_m=-.037, width_m=.085)
    path = _write(tmp_path, s)
    base, moved = sites.Layout(), sites.Layout(cell_snapshot=str(path), belt_pose="snapshot")
    assert (moved.belt_stop_x, moved.belt_y) == (.205, -.037)
    assert moved.sites["belt"]["xy"][0] - base.sites["belt"]["xy"][0] == pytest.approx(.205 - sites.BELT_STOP_X)
    assert moved.sites["belt"]["xy"][1] == -.037
    with pytest.raises(ValueError, match="no measured belt"):
        sites.Layout(cell_snapshot=str(_write(tmp_path, snap())), belt_pose="snapshot")


def test_a_stage_takes_extra_choices_after_the_snapshots_so_they_win():
    body = r2s.stage_body("stack", "deploy/robot/omx/sim/cell_snapshots/x.json", ["physics=twin-kp-20261109"])
    assert "--choice physics=twin-kp-20261109" in body
    assert body.rindex("--choice physics=") > body.rindex("--choice ship_pose=snapshot")  # parse_choices keeps the last
    assert sites.parse_choices(["temp_lanes=snapshot", "physics=design", "physics=twin-kp-20261109"])["physics"] == "twin-kp-20261109"
    assert "physics=" not in r2s.stage_body("stack", "x.json")


def test_the_belt_request_asks_for_one_tape_reading_that_tells_the_two_belts_apart(tmp_path):
    (tmp_path / "frames").mkdir()
    cv2.imwrite(str(tmp_path / "frames" / "top.jpg"), np.full((480, 640, 3), (60, 200, 200), np.uint8))
    s = snap()
    s["items"]["belt"] = dict(end_x_m=.205, centre_y_m=-.037, width_m=.085)
    s["taken_at"] = "2026-11-09T04:28:23+00:00"
    (tmp_path / "snapshot.json").write_text(json.dumps(s), encoding="utf-8")
    req, image = r2s.belt_request(tmp_path)
    layout = sites.Layout()
    axis = layout.arms["arm_b"].base[:2]
    assert req["candidates"] == dict(sim=round(math.dist(axis, (sites.BELT_STOP_X, layout.belt_y)) * 1000),
                                     camera=round(math.dist(axis, (.205, -.037)) * 1000))
    assert abs(req["candidates"]["camera"] - req["candidates"]["sim"]) > 2 * req["tolerance"]  # one reading decides
    assert req["id"] == "belt-end-20261109-0428" and req["gap"] == "G-30" and image.exists()


def test_a_moved_top_camera_is_caught_on_the_far_band(tmp_path, monkeypatch):
    import omx_cell_anchor as anchor
    rng = np.random.default_rng(0)
    scene = (rng.random((540, 720)) * 255).astype(np.uint8)
    scene = cv2.GaussianBlur(scene, (0, 0), 2)  # texture ORB can match, like the far table, belt and floor
    still = cv2.cvtColor(scene[30:510, 40:680], cv2.COLOR_GRAY2BGR)
    shifted = cv2.cvtColor(scene[30:510, 52:692], cv2.COLOR_GRAY2BGR)  # the camera turned: the view slid 12 px
    assert not anchor.moved(anchor.motion(still, still.copy()))
    m = anchor.motion(still, shifted)
    assert anchor.moved(m) and abs(m["dx_px"] + 12) < 1.5
    monkeypatch.setenv("ROSY_REAL2SIM_FRAMES", str(tmp_path / "frames"))
    path = tmp_path / "top.jpg"
    cv2.imwrite(str(path), still)
    name = anchor.remember(path)
    assert name == anchor.digest(path) and anchor.reference(name).read_bytes() == path.read_bytes()
    assert anchor.reference("sha256:" + "0" * 64) is None


def test_20261110_named_choices_and_arm_bases_candidates_match_the_snapshot():
    snap_path = "deploy/robot/omx/sim/cell_snapshots/20261110-1231.json"
    from_snap = sites.Layout(cell_snapshot=snap_path, temp_lanes="snapshot", ship_pose="snapshot", belt_pose="snapshot", arm_bases="snapshot")
    from_named = sites.Layout(temp_lanes="photo-20261110", ship_pose="photo-20261110", belt_pose="photo-20261110", arm_bases="plate-centre")
    for k in ("tmp-a-1", "tmp-a-2", "tmp-a-3", "tmp-b-1", "tmp-b-2", "tmp-b-3", "ship-h1r1-l0", "belt"):
        assert math.dist(from_snap.sites[k]["xy"], from_named.sites[k]["xy"]) < 1e-6, k
    assert tuple(from_named.arms["arm_b"].base[:2]) == pytest.approx((.107, .164))
    assert tuple(sites.Layout().arms["arm_b"].base[:2]) == pytest.approx((.104, .153))
    assert not any(s.get("blocked") for s in from_named.sites.values())  # tmp-b-1 clears the measured ship by 15.9 mm
    assert sites.WRIST_PHOTO_A["lens_m"][0] > sites.WRIST_PHOTO["lens_m"][0] and sites.WRIST_PHOTO_A["axis_hit_x_m"] > sites.WRIST_PHOTO["axis_hit_x_m"]
