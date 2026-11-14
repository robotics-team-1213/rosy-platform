"""cell_tier_check: with the right camera model the printed board's corners land on its printed layout at every stack
height; a stack that is not the height claimed, or a one-height model used at another height, is caught."""
import sys
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
cv2 = pytest.importorskip("cv2")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "deploy/robot/omx"))
import cell_checkerboard as cb  # noqa: E402
import cell_tier_check as tc  # noqa: E402

K = np.array([[618.5, 0, 322.3], [0, 618.7, 236.6], [0, 0, 1.0]])  # the cell D435's colour stream
PPM = 2000
ART = cv2.copyMakeBorder(cb.charuco_image((int(0.14 * PPM), int(0.20 * PPM))), 30, 30, 30, 30, cv2.BORDER_CONSTANT, value=255)
TO_M = np.array([[1 / PPM, 0, -30 / PPM], [0, 1 / PPM, -30 / PPM], [0, 0, 1]])
R0 = cv2.Rodrigues(np.radians([11.0, 0, 4.0]))[0]  # the table seen 11 deg off the optical axis, as measured
T0 = np.array([0.02, -0.03, 0.597]) - R0 @ [0.07, 0.10, 0]  # the board's centre ~597 mm away


def frame(height_mm=0.0, dx=0.0, dy=0.0, yaw_deg=0.0, n=0):
    """The board lying on a plane `height_mm` above the table, moved and turned on it; n moves it a hair per frame."""
    R = R0 @ cv2.Rodrigues(np.radians([0, 0, yaw_deg]))[0]
    t = T0 + R0 @ [dx + 0.0004 * n, dy, -height_mm / 1000.0]
    image = cv2.warpPerspective(ART, K @ np.column_stack([R[:, 0], R[:, 1], t]) @ TO_M, (640, 480), borderValue=200)
    return cb.find_charuco(image, cb.charuco_board(*cb.PRINTED), min_corners=12)


def tiers(actual=None):
    actual = actual or {30.0: 30.0, 60.0: 60.0, 90.0: 90.0}
    spots = {30.0: (0.03, 0.01, 15), 60.0: (-0.02, 0.03, -20), 90.0: (0.01, -0.02, 35)}
    return {claimed: [frame(real, *spots[claimed], n=k) for k in range(3)] for claimed, real in actual.items()}


def test_every_tier_lands_on_the_printed_layout():
    table = [frame(n=k) for k in range(3)]
    out = tc.check(table, tiers(), K, np.zeros(5))
    assert out["accepted"] is True, out
    assert abs(out["camera_above_table_mm"] - 597) < 60  # along the table normal, not the optical axis
    for height, row in out["tiers"].items():
        assert row["rms_mm"] < 0.8 and abs(row["height_solved_mm"] - float(height)) < 1.0


def test_a_stack_off_by_5_mm_and_a_one_height_model_are_caught():
    table = [frame(n=k) for k in range(3)]
    short = tc.check(table, tiers({30.0: 30.0, 60.0: 55.0, 90.0: 90.0}), K, np.zeros(5))
    assert short["accepted"] is False
    assert short["tiers"]["60.0"]["ok"] is False and abs(short["tiers"]["60.0"]["height_solved_mm"] - 55.0) < 1.5
    bumped = [frame(n=0), frame(dx=0.01, n=1), frame(n=2)]  # the table board moved between its frames
    assert tc.check(bumped, tiers(), K, np.zeros(5))["reason"] == "table board pose does not fit its frames"
    flat = tc.check(table, {0.0: [frame(60.0, 0.03, 0.01, 15, n=k) for k in range(3)]}, K, np.zeros(5))
    assert flat["tiers"]["0.0"]["ok"] is False and flat["tiers"]["0.0"]["max_mm"] > 2.5  # 60 mm read as the table
