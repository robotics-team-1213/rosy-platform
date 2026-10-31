"""A pick must not use a scene that may have changed; wrist views keep the roll continuous; touched anchors re-scale a map."""
import sys
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
OMX = Path(__file__).parents[1] / "deploy/robot/omx"
sys.path.insert(0, str(OMX))
try:
    import cell_calibration as cal
    import cell_observe as obs
    import cell_scene as m
finally:
    sys.path.remove(str(OMX))

CONFIG = {"scene_since": "2026-10-27T10:30:00+00:00", "cameras": {"top": {"id": "usb-top-1"}}}


def found(observed="2026-10-27T11:00:00+00:00"):
    return {"found": True, "observed": observed, "estimates": [{"camera": "top", "map": "belt~local"}]}


def maps(measured="2026-10-27T11:00:00+00:00", camera_id="usb-top-1"):
    return {"sites": {"belt~local": {"measured": measured, "camera_id": camera_id}}}


def test_a_fresh_detection_and_map_pass():
    assert m.scene_check(CONFIG, maps(), found()) is None


@pytest.mark.parametrize("calibration,seen,word", [
    (maps(measured="2026-10-27T09:00:00+00:00"), found(), "before the scene change"),
    (maps(), found(observed="2026-10-27T10:00:00+00:00"), "older than the scene change"),
    (maps(camera_id="usb-top-2"), found(), "another camera"),
])
def test_an_older_map_detection_or_camera_is_refused_with_the_reason(calibration, seen, word):
    assert word in m.scene_check(CONFIG, calibration, seen)


def test_without_a_scene_change_nothing_is_refused_and_map_check_asks_the_scene_too():
    assert m.scene_check({"cameras": {}}, maps(measured="2020-01-01T00:00:00Z"), found()) is None
    seen = {**found(), "estimates": [{**found()["estimates"][0], "outside_mm": 0, "residual_mm": 1}]}
    assert obs.map_check(CONFIG, seen) is None
    assert "usb-top-2" in obs.map_check(CONFIG, seen, maps(camera_id="usb-top-2"))


def test_the_roll_stays_continuous_and_a_roll_near_its_limit_turns_90():
    assert m.view_yaw(10.0, previous_deg=61, limit_deg=170, square=False) == 10.0
    assert m.view_yaw(-120.0, previous_deg=61, limit_deg=170, square=False) == 60.0  # +180, not a 180 deg jump
    assert m.view_yaw(160.0, previous_deg=165, limit_deg=170, square=True) == 70.0  # 160 sits in the limit margin: turn 90
    assert m.view_yaw(170.0, previous_deg=165, limit_deg=170, square=False) == -10.0  # not-square: only +180 steps


def test_open_fingers_must_clear_a_stored_fixture_at_grasp_height():
    data = {"surfaces": {"tray": {"kind": "fixture", "measured": "t", "points": [[0.098, 0.10, 0.06]]}}}
    assert m.fixture_clear(data, 0.07, 0.10, 0.04, 0.0, 0.056) == ((0.098, 0.1), "tray", 0.06)  # a finger on the rim
    assert m.fixture_clear(data, 0.07, 0.10, 0.065, 0.0, 0.056) is None  # grasp point above the rim
    assert m.fixture_clear(data, 0.07, 0.10, 0.04, 90.0, 0.056) is None  # jaws open along y: clear of it


def test_two_touched_points_rescale_a_map_and_find_a_moved_box():
    base = cal.fit([((u, v), (0.1 + u / 1000, 0.2 - v / 1000)) for u, v in ((0, 0), (100, 0), (0, 100), (100, 100))])
    truth = [((50.0, 40.0), (0.30, 0.10)), ((250.0, 90.0), (0.30 + 200 * 0.00105, 0.10 - 50 * 0.00105))]
    h = cal.anchored(base, truth)
    for px, arm in truth:
        assert cal.to_arm(h, px) == pytest.approx(arm, abs=1e-9)
    assert cal.to_arm(h, (150.0, 65.0)) == pytest.approx((0.30 + 100 * 0.00105, 0.10 - 25 * 0.00105), abs=1e-9)
    with pytest.raises(ValueError):
        cal.anchored(base, truth[:1])
