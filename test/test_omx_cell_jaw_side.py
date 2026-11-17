"""cell_jaw_side: one visible jaw over a cluttered site (2026-11-17), on small synthetic top views."""
import json
import math
import sys
import types
from pathlib import Path

import pytest

cv2 = pytest.importorskip("cv2")
np = pytest.importorskip("numpy")
OMX = Path(__file__).resolve().parents[1] / "deploy" / "robot" / "omx"
sys.path.insert(0, str(OMX))
import cell_jaw_side as js  # noqa: E402
import cell_pivot  # noqa: E402

REF, OTHER = (300.0, 200.0), (370.0, 210.0)  # predicted reference and other jaw, 70 px apart


def frames(*blobs):
    """Closed and open top views; each blob (x, y) is a 20 x 24 px jaw that only shows when open."""
    closed, opened = np.full((400, 640, 3), 200, np.uint8), np.full((400, 640, 3), 200, np.uint8)
    for x, y in blobs:
        cv2.rectangle(opened, (int(x) - 10, int(y) - 12), (int(x) + 10, int(y) + 12), (20, 20, 20), -1)
    return closed, opened


def jaws(**extra):
    return {"places": [REF, OTHER], "radius_px": 45.0, "band": None, "to": "reference", **extra}


def test_a_change_outside_both_jaw_discs_is_never_a_mark():
    closed, opened = frames((520, 330))  # a box shadow far from both jaws: the old path saw it
    assert cell_pivot.jaw_blobs(closed, opened)
    assert js.marks(closed, opened, None, False, jaws()) == []
    within = js.discs(closed.shape, [REF], 45)
    assert cell_pivot.jaw_blobs(closed, opened, within=within) == []


def test_the_depth_band_keeps_the_jaw_height_and_unknown_and_drops_box_tops():
    heights = np.full((60, 60), 110.0, np.float32)  # jaws at 110 mm over the table
    heights[:, :20] = 60.0  # a container top 50 mm under them
    heights[:, 40:] = np.nan  # no depth return (thin finger edges)
    band = js.height_band(heights, 110.0, {"jaw_side.band_mm": 18.0, "jaw_side.above_mm": 74.0})
    assert band[30, 30] == 255 and band[30, 55] == 255 and band[30, 5] == 0
    assert band[30, 16] == 255  # the 5 px widening for the colour-depth alignment
    closed, opened = frames(REF)
    full = np.zeros(closed.shape[:2], np.uint8)  # the band says nothing there stands at the jaws' height
    assert js.marks(closed, opened, None, False, jaws(band=full)) == []
    assert js.marks(closed, opened, None, False, jaws(band=full + 255))


def test_the_other_jaw_seen_alone_is_moved_to_the_reference_jaw():
    closed, opened = frames((OTHER[0] + 3, OTHER[1] + 2))
    (x, y, _, side), = js.marks(closed, opened, None, False, jaws())
    assert (x, y) == pytest.approx((REF[0] + 3, REF[1] + 2), abs=1) and side == "other"
    closed, opened = frames((REF[0] - 4, REF[1]))
    (x, y, _, side), = js.marks(closed, opened, None, False, jaws())
    assert (x, y) == pytest.approx((REF[0] - 4, REF[1]), abs=1) and side == "ref"
    (x, y, _, _), = js.marks(*frames(OTHER), None, False, jaws(to="middle"))
    assert (x, y) == pytest.approx(((REF[0] + OTHER[0]) / 2, (REF[1] + OTHER[1]) / 2), abs=1)


def test_the_side_follows_the_fk_yaw_through_the_jaw_model():
    record = {"homography": [[0.001, 0, 0], [0, 0.001, 0], [0, 0, 1]], "z_view": 0.1}
    config = {"sites": {"s": {"z": 0.1}}, "cameras": {"top": {"height_m": 0.6, "center_px": [0, 0]}},
              "params": {"jaw_side.other_mm": 50.0, "jaw_side.other_deg": 90.0}}
    ref, other = js.jaw_places(record, config, "s", (0.2, 0.1), 0.0, 0.1)
    assert ref == pytest.approx((200, 100)) and other == pytest.approx((200, 150))
    ref, other = js.jaw_places(record, config, "s", (0.2, 0.1), 90.0, 0.1)  # the gripper turned: the other jaw too
    assert other == pytest.approx((150, 100))
    geo = dict(config, pivot={"geometry": {"radius_mm": 20.0, "phase_deg": 0.0}})
    assert js.jaw_places(record, geo, "s", (0.2, 0.1), 0.0, 0.1)[0] == pytest.approx((220, 100))


def test_both_jaws_seen_keep_the_two_jaw_pair_and_one_pair_side_off_a_jaw_does_not_count():
    closed, opened = frames(REF, OTHER)
    found = js.marks(closed, opened, None, False, jaws())
    assert found[0][:2] == pytest.approx(REF, abs=1) and found[0][2] > 600 and found[0][3] == "pair"
    closed, opened = frames(REF, (REF[0], REF[1] + 40))  # a pair inside the reference disc only: a link edge
    assert all(m[2] < 600 for m in js.marks(closed, opened, None, False, jaws()))


def test_mark_jaws_without_jaws_keeps_the_old_path_and_with_jaws_returns_the_reference(monkeypatch):
    monkeypatch.setitem(sys.modules, "cell_pipeline", types.SimpleNamespace(grip_to=lambda cell, value: True))
    closed, opened = frames(OTHER)
    seq = iter([closed, opened] * 6)
    monkeypatch.setattr(cell_pivot, "settled_frame", lambda *a, **k: next(seq))
    assert cell_pivot.mark_jaws(None, {"plan": {}}, lambda s: None) == pytest.approx(OTHER, abs=1)
    seq = iter([closed, opened] * 6)
    assert cell_pivot.mark_jaws(None, {"plan": {}}, lambda s: None, jaws=jaws()) == pytest.approx(REF, abs=1)


def test_pivot_jaws_falls_back_without_fk_or_map_and_keeps_its_prediction(tmp_path):
    config = {"sites": {"s": {"z": 0.1}}, "cameras": {"top": {"center_px": [0, 0], "height_m": 0.6, "has_depth": False}}}
    record = {"homography": [[0.001, 0, 0], [0, 0.001, 0], [0, 0, 1]], "z_view": 0.1}
    assert js.pivot_jaws(None, config, record, "s", None, tmp_path / "a") is None
    assert js.pivot_jaws(None, config, {"homography": []}, "s", (0.2, 0.1, 0.1, 0.0), tmp_path / "b") is None
    out = js.pivot_jaws(None, config, record, "s", (0.2, 0.1, 0.1, 0.0), tmp_path / "c")
    assert out["band"] is None and out["places"][0] == pytest.approx((200, 100))  # no depth camera: no band
    assert json.loads((tmp_path / "c" / "jaws.json").read_text())["depth"] is None
    assert json.loads((tmp_path / "c" / "jaws.json").read_text())["places"][0] == [200.0, 100.0]


def test_pivot_jaws_keeps_the_depth_frame_and_bands_only_when_the_band_is_on(tmp_path, monkeypatch):
    import cell_depth

    config = {"sites": {"s": {"z": 0.1}}, "cameras": {"top": {"center_px": [0, 0], "height_m": 0.596, "depth_device": "d435"}},
              "params": {"jaw_side.depth_band": 1}}
    record = {"homography": [[0.001, 0, 0], [0, 0.001, 0], [0, 0, 1]], "z_view": 0.1}
    seen = {}

    def capture(out_raw=None, **_):
        seen["raw"] = out_raw
        return np.full((480, 640), 500, np.uint16)

    monkeypatch.setattr(cell_depth, "capture_top_depth_z16", capture)
    heights = np.full((400, 640), 40.0, np.float32)
    heights[90:110, 190:210] = 112.0
    monkeypatch.setattr(js, "heights_in_colour", lambda depth, colour: (heights, 611.0))
    cell = types.SimpleNamespace(frame=lambda name: np.zeros((400, 640, 3), np.uint8))
    off = js.pivot_jaws(cell, dict(config, params={}), record, "s", (0.2, 0.1, 0.1, 0.0), tmp_path / "off")
    assert off["band"] is None and seen["raw"] == tmp_path / "off" / "depth.raw"  # default: depth kept, no band
    assert json.loads((tmp_path / "off" / "jaws.json").read_text())["depth"] == {"saved": True, "band": False}
    out = js.pivot_jaws(cell, config, record, "s", (0.2, 0.1, 0.1, 0.0), tmp_path)
    assert seen["raw"] == tmp_path / "depth.raw" and (tmp_path / "depth-colour.jpg").exists()
    info = json.loads((tmp_path / "jaws.json").read_text())["depth"]
    assert info["band"] and info["jaw_mm"] == pytest.approx(611.0 - 496.0)  # table 611 mm under the camera, TCP 0.1 over zero
    assert out["band"][100, 200] == 255 and out["band"][300, 500] == 0
    monkeypatch.setattr(cell_depth, "capture_top_depth_z16", lambda out_raw=None, **_: None)
    failed = js.pivot_jaws(cell, config, record, "s", (0.2, 0.1, 0.1, 0.0), tmp_path / "failed")
    assert failed["band"] is None  # recorded; path_check refuses this yaw beside banded ones
    assert json.loads((tmp_path / "failed" / "jaws.json").read_text())["depth"] == {"saved": False, "band": False}
    assert js.path_check([{"path": "band"}, {"path": "discs"}]).startswith("jaw paths mixed")


def test_where_the_discs_meet_the_reference_jaw_wins():
    near = {"places": [REF, (REF[0] + 30, REF[1])], "radius_px": 45.0, "band": None, "to": "reference"}
    (x, y, _, side), = js.marks(*frames((REF[0] + 20, REF[1])), None, False, near)  # inside both discs
    assert side == "ref" and (x, y) == pytest.approx((REF[0] + 20, REF[1]), abs=1)
    (x, y, _, side), = js.marks(*frames((REF[0] + 60, REF[1])), None, False, near)  # only in the other's disc
    assert side == "other" and (x, y) == pytest.approx((REF[0] + 30, REF[1]), abs=1)


GEO = {"radius_mm": 18.0, "phase_deg": 40.0}
CENTRE = (0.08, -0.09)


def marks_for(yaws, shift_mm=(0.0, 0.0)):
    r = GEO["radius_mm"] / 1000
    return [(CENTRE[0] + r * math.cos(math.radians(y + GEO["phase_deg"])) + shift_mm[0] / 1000,
             CENTRE[1] + r * math.sin(math.radians(y + GEO["phase_deg"])) + shift_mm[1] / 1000) for y in yaws]


def test_a_wrong_other_jaw_offset_is_refused_by_the_side_balance_and_other_only_needs_validation():
    yaws = [-60.0, -30.0, 0.0, 30.0]
    tcps = [(0.07, -0.1, 0.1, y) for y in yaws]
    hows = [{"side": s, "path": "discs"} for s in ("ref", "other", "ref", "other")]
    good = marks_for(yaws)
    res = cell_pivot.known_geometry_bias(good, tcps, GEO, "s", {"homography": []}, None, hows, "arm_a")
    assert res["result"] == "calibrated" and res["bias"]["jaw_sides"] == ["ref", "other", "ref", "other"]
    off = [m if h["side"] == "ref" else (m[0] + 0.006, m[1]) for m, h in zip(good, hows)]  # jaw_side offset 6 mm wrong
    res = cell_pivot.known_geometry_bias(off, tcps, GEO, "s", {"homography": []}, None, hows, "arm_a")
    assert res["result"].startswith("jaw sides disagree") and res["bias"]["rms_mm"] <= 5.0  # spread alone passed
    others = [{"side": "other", "path": "discs"}] * 4
    res = cell_pivot.known_geometry_bias(good, tcps, GEO, "s", {"homography": []}, None, others, "arm_a")
    assert res["result"].startswith("jaw sides unvalidated: 0 reference-side marks")
    res = cell_pivot.known_geometry_bias(good, tcps, GEO, "s", {"homography": []}, {"jaw_side.validated_arm_a": 1}, others, "arm_a")
    assert res["result"] == "calibrated"
    assert cell_pivot.known_geometry_bias(good, tcps, GEO, "s", {"homography": []})["result"] == "calibrated"  # no sides: as before


def pivot_rig(monkeypatch, tmp_path, mark):
    """pivot_calibrate with the map, FK and motion faked; `mark(cell, config, sleep, **kw)` stands for mark_jaws."""
    import joint_jitter

    yaws = iter([-75.0, -45.0, -15.0, 15.0, 45.0, 75.0])
    monkeypatch.setitem(sys.modules, "cell_pipeline", types.SimpleNamespace(
        write_library=lambda c, a, b, path: path, fold=lambda cell, s: None, grip_to=lambda cell, v: True))
    monkeypatch.setattr(joint_jitter, "settled_state", lambda *a, **k: {"state": [0, 0, 0, 0, 0, 56]})
    monkeypatch.setattr(cell_pivot, "joints_tcp", lambda *a, **k: (0.10, 0.15, 0.08, next(yaws)))
    monkeypatch.setattr(cell_pivot, "fold", lambda *a, **k: None)
    monkeypatch.setattr(cell_pivot, "mark_jaws", mark)
    cfg = {"plan": {"approach_m": 0.03}, "coarse": {"z_view": 0.08}, "sites": {"floor": {"z": 0.08}},
           "cameras": {"top": {"height_m": 0.6, "center_px": [0, 0], "has_depth": False}}}
    cal = {"sites": {"floor~coarse": {"homography": [[0.001, 0, 0], [0, 0.001, 0], [0, 0, 1]], "z_view": 0.08}}}
    cell = types.SimpleNamespace(act=lambda cmd: {"ok": True})
    return cell_pivot.pivot_calibrate(cell, cfg, (0.10, 0.15), [-75, -45, -15, 15, 45, 75], cal, "floor", tmp_path,
                                      lambda _: None, lambda _: None)


def test_a_static_blob_inside_the_disc_is_refused_by_the_radius_guard(tmp_path, monkeypatch):
    closed, opened = frames((110, 150))  # the TCP shows at (100, 150); a white board edge 10 px off, still at every yaw
    real = cell_pivot.mark_jaws

    def mark(cell, config, sleep, **kw):
        seq = iter([closed, opened] * 6)
        monkeypatch.setattr(cell_pivot, "settled_frame", lambda *a, **k: next(seq))
        return real(cell, config, sleep, **kw)

    res = pivot_rig(monkeypatch, tmp_path, mark)
    assert res["result"].startswith("circle refused") and res["bias"]["radius_mm"] < 12.0
    kept = json.loads(next(tmp_path.glob("pivot-frames/floor-*/00/jaws.json")).read_text())
    assert kept["side"] == "ref" and kept["path"] == "discs"


def test_a_pivot_mixing_disc_and_old_path_marks_is_refused(tmp_path, monkeypatch):
    placed = iter([True, True, False, True, True, True])
    real = js.pivot_jaws
    monkeypatch.setattr(js, "pivot_jaws", lambda *a, **k: real(*a, **k) if next(placed) else None)

    def mark(cell, config, sleep, report=None, jaws=None, **kw):
        if report is not None and jaws is not None:
            report.update(reason=None, side="ref")
        return (100.0, 150.0)

    assert pivot_rig(monkeypatch, tmp_path, mark)["result"].startswith("jaw paths mixed: discs, old")


def test_pivot_frames_keep_the_newest_per_site(tmp_path):
    root = tmp_path / "pivot-frames"
    for k in range(4):
        (root / f"floor-20261117-1200{k:02d}-000000").mkdir(parents=True)
    (root / "floorx-20261117-120000-000000").mkdir()
    new = js.frames_dir(tmp_path, "floor", {"pivot.keep_frames": 3})
    assert new.name.startswith("floor-") and len(new.name.split("-")[-1]) == 6
    assert sorted(d.name for d in root.iterdir()) == ["floor-20261117-120002-000000", "floor-20261117-120003-000000",
                                                      "floorx-20261117-120000-000000"]


def test_pair_marks_count_as_the_reference_side_and_are_compared_with_other_marks():
    yaws = [-60.0, -30.0, 0.0, 30.0]
    tcps = [(0.07, -0.1, 0.1, y) for y in yaws]
    good = marks_for(yaws)
    pairs = [{"side": "pair", "path": "discs"}] * 4
    res = cell_pivot.known_geometry_bias(good, tcps, GEO, "s", {"homography": []}, None, pairs, "arm_a")
    assert res["result"] == "calibrated" and res["bias"]["jaw_sides"] == ["pair"] * 4  # all pairs: as before
    mix = [{"side": s, "path": "discs"} for s in ("pair", "other", "pair", "other")]
    assert cell_pivot.known_geometry_bias(good, tcps, GEO, "s", {"homography": []}, None, mix, "arm_a")["result"] == "calibrated"
    off = [m if h["side"] == "pair" else (m[0], m[1] - 0.005) for m, h in zip(good, mix)]
    res = cell_pivot.known_geometry_bias(off, tcps, GEO, "s", {"homography": []}, None, mix, "arm_a")
    assert res["result"].startswith("jaw sides disagree")
    one = [{"side": s, "path": "discs"} for s in ("pair", "other", "other", "other")]
    res = cell_pivot.known_geometry_bias(good, tcps, GEO, "s", {"homography": []}, None, one, None)  # no arm_id: not validated
    assert res["result"].startswith("jaw sides unvalidated: 1 reference-side marks")


def test_the_circle_path_refuses_disagreeing_sides(tmp_path, monkeypatch):
    yaws, seen = [-75.0, -45.0, -15.0, 15.0, 45.0, 75.0], {}

    def run(sides, shift_m, work):
        order = iter(range(6))

        def mark(cell, config, sleep, report=None, jaws=None, **kw):
            k = next(order)
            a = math.radians(yaws[k] + 30.0)  # marks on a 20 mm circle about (0.11, 0.16): bias 10, 10 mm
            seen["arm"] = (0.11 + 0.020 * math.cos(a) + (shift_m if sides[k] == "other" else 0.0), 0.16 + 0.020 * math.sin(a))
            report.update(reason=None, side=sides[k])
            return (100.0, 150.0)

        monkeypatch.setattr(cell_pivot, "mark_to_arm", lambda *a, **k: seen["arm"])
        return pivot_rig(monkeypatch, work, mark)

    assert run(["ref", "pair"] * 3, 0.0, tmp_path / "a")["result"] == "calibrated"
    assert run(["ref", "other"] * 3, 0.0, tmp_path / "b")["result"] == "calibrated"
    res = run(["ref", "other"] * 3, 0.006, tmp_path / "c")  # the other jaw's offset 6 mm wrong
    assert res["result"].startswith("jaw sides disagree") and res["bias"]["jaw_sides"] == ["ref", "other"] * 3
    assert res["bias"]["rms_mm"] <= 5.0  # the circle's own rms guard let it through


def test_tries_that_agree_in_place_but_switch_jaw_give_no_mark(monkeypatch):
    monkeypatch.setitem(sys.modules, "cell_pipeline", types.SimpleNamespace(grip_to=lambda cell, value: True))
    ref_seen, other_seen = frames((REF[0] + 2, REF[1])), frames((OTHER[0] + 2, OTHER[1]))  # the same place, either jaw
    seq = iter([*ref_seen, *other_seen] * 3)
    monkeypatch.setattr(cell_pivot, "settled_frame", lambda *a, **k: next(seq))
    report = {}
    assert cell_pivot.mark_jaws(None, {"plan": {}}, lambda s: None, jaws=jaws(), report=report) is None
    assert report["reason"] == "jaw sides switched between tries"
    seq = iter([*ref_seen, *ref_seen] * 3)
    report = {}
    assert cell_pivot.mark_jaws(None, {"plan": {}}, lambda s: None, jaws=jaws(), report=report) == pytest.approx(
        (REF[0] + 2, REF[1]), abs=1) and report["side"] == "ref"
