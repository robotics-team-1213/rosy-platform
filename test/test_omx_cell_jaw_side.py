"""cell_jaw_side: one visible jaw over a cluttered site (2026-11-17), on small synthetic top views."""
import json
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
    (x, y, _), = js.marks(closed, opened, None, False, jaws())
    assert (x, y) == pytest.approx((REF[0] + 3, REF[1] + 2), abs=1)
    closed, opened = frames((REF[0] - 4, REF[1]))
    (x, y, _), = js.marks(closed, opened, None, False, jaws())
    assert (x, y) == pytest.approx((REF[0] - 4, REF[1]), abs=1)
    (x, y, _), = js.marks(*frames(OTHER), None, False, jaws(to="middle"))
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
    assert found[0][:2] == pytest.approx(REF, abs=1) and found[0][2] > 600  # the pair: both sides' area
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
    assert json.loads((tmp_path / "c" / "jaws.json").read_text())["places"][0] == [200.0, 100.0]


def test_pivot_jaws_keeps_the_depth_frame_and_bands_at_the_jaws_height(tmp_path, monkeypatch):
    import cell_depth

    config = {"sites": {"s": {"z": 0.1}}, "cameras": {"top": {"center_px": [0, 0], "height_m": 0.596, "depth_device": "d435"}}}
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
    out = js.pivot_jaws(cell, config, record, "s", (0.2, 0.1, 0.1, 0.0), tmp_path)
    assert seen["raw"] == tmp_path / "depth.raw" and (tmp_path / "depth-colour.jpg").exists()
    info = json.loads((tmp_path / "jaws.json").read_text())["depth"]
    assert info["jaw_mm"] == pytest.approx(611.0 - 496.0)  # table 611 mm under the camera, TCP 0.1 over the arm's zero
    assert out["band"][100, 200] == 255 and out["band"][300, 500] == 0
