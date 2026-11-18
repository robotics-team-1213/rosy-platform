"""cell_depth_pose: the work board's plane from a depth frame, placed in the colour camera by the factory transform,
gives the camera's height and tilt; a box standing on the board outside the colour box is left out; a move shows."""
import math
import sys
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "deploy/robot/omx"))
import cell_depth_pose as dp  # noqa: E402

FACTORY = {"K": [[618.5, 0, 322.3], [0, 618.7, 236.6], [0, 0, 1]],
           "depth": {"size": [640, 480], "K": [[388.7, 0, 321.0], [0, 388.7, 245.0], [0, 0, 1]]},
           "depth_to_colour": {"R": np.eye(3).tolist(), "t_m": [0.0145, 0.0, 0.0]}}  # the lenses sit side by side


def depth_frame(height_mm, tilt_deg, box=True, seed=0, noise_mm=1.0):
    """A board `height_mm` below the colour camera, its normal `tilt_deg` from the optical axis (about x), 1 mm noise;
    with `box`, a 60 mm block on it in the depth image's right third."""
    K = np.asarray(FACTORY["depth"]["K"])
    v, u = np.mgrid[0:480, 0:640]
    rays = np.dstack([(u - K[0, 2]) / K[0, 0], (v - K[1, 2]) / K[1, 1], np.ones((480, 640))])
    normal = np.array([0.0, -math.sin(math.radians(tilt_deg)), -math.cos(math.radians(tilt_deg))])
    depth = height_mm / -(rays @ normal)  # t is along x, normal has no x: the depth frame sees the same distance
    if box:
        raised = height_mm - 60.0
        depth[:, 430:] = (raised / -(rays @ normal))[:, 430:]
    depth += np.random.default_rng(seed).normal(0, noise_mm, depth.shape)
    return np.round(depth).astype(np.uint16)


def test_board_height_and_tilt_in_the_colour_frame():
    out = dp.surface(depth_frame(597.0, 11.0), FACTORY, (0, 0, 400, 480))
    assert out["ok"] is True, out
    assert abs(out["height_mm"] - 597.0) < 0.5 and abs(out["tilt_deg"] - 11.0) < 0.1
    whole = dp.surface(depth_frame(597.0, 11.0), FACTORY, (0, 0, 640, 480))
    assert abs(whole["height_mm"] - 597.0) < 0.5  # the board outnumbers the box, so it is still the plane found


def test_compare_reports_a_bump_and_not_noise():
    before = dp.surface(depth_frame(597.0, 11.0, seed=1), FACTORY, (0, 0, 400, 480))
    again = dp.surface(depth_frame(597.0, 11.0, seed=2), FACTORY, (0, 0, 400, 480))
    lowered = dp.surface(depth_frame(589.0, 11.0, seed=3), FACTORY, (0, 0, 400, 480))
    tipped = dp.surface(depth_frame(597.0, 14.0, seed=4), FACTORY, (0, 0, 400, 480))
    assert dp.compare(again, before)["moved"] is False
    moved = dp.compare(lowered, before)
    assert moved["moved"] is True and abs(moved["height_change_mm"] + 8.0) < 0.5 and moved["tilt_change_deg"] < 0.5
    assert dp.compare(tipped, before)["moved"] is True
    assert dp.compare({"ok": False}, before)["moved"] is None
    elsewhere = dp.surface(depth_frame(597.0, 11.0, seed=5), FACTORY, (0, 0, 300, 480))
    assert dp.compare(elsewhere, before)["moved"] is None  # another box may hold another surface


def test_bump_tells_a_turn_from_a_change_of_height():
    cv2 = pytest.importorskip("cv2")
    rng = np.random.default_rng(7)
    scene = cv2.GaussianBlur(rng.integers(0, 255, (480, 640)).astype(np.uint8), (0, 0), 2)  # a textured view
    turned_view = np.roll(scene, 12, axis=1)
    reference = dp.surface(depth_frame(597.0, 11.0, seed=1), FACTORY, (0, 0, 400, 480))
    same = dp.surface(depth_frame(597.0, 11.0, seed=2), FACTORY, (0, 0, 400, 480))
    lowered = dp.surface(depth_frame(589.0, 11.0, seed=3), FACTORY, (0, 0, 400, 480))
    assert dp.bump(scene, scene, reference, same)["kind"] == "none"
    assert dp.bump(scene, turned_view, reference, same)["kind"] == "view"
    assert dp.bump(scene, scene, reference, lowered)["kind"] == "height"
    assert dp.bump(scene, np.zeros_like(scene), reference, same)["moved"] is None  # no features: not "fine"


def test_a_box_without_one_clear_surface_is_refused():
    cluttered = dp.surface(depth_frame(597.0, 11.0, noise_mm=15.0), FACTORY, (0, 0, 400, 480))  # parts, cables
    assert cluttered["ok"] is False and cluttered["reason"] == "plane_not_clear_in_roi"


def test_refuses_a_record_without_depth_calibration_and_an_empty_box():
    with pytest.raises(ValueError, match="depth"):
        dp.surface(depth_frame(597.0, 11.0), {"K": FACTORY["K"]}, (0, 0, 400, 480))
    assert dp.surface(depth_frame(597.0, 11.0), FACTORY, (700, 0, 800, 10))["reason"] == "too_few_depth_points_in_roi"


def test_the_nadir_is_where_parallax_must_scale_about_on_a_tilted_camera():
    out = dp.surface(depth_frame(597.0, 11.0), FACTORY, (0, 0, 400, 480))
    u, v = out["nadir_px"]
    assert abs(u - 322.3) < 0.5 and abs(v - (236.6 + 618.7 * math.tan(math.radians(11.0)))) < 1.0
