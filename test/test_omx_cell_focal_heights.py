"""cell_focal_heights: the printed board flat at two CAD-known heights under a tilted camera gives its focal length,
wherever in the image and at whatever in-plane turn the board lies; a held or tilted board is refused."""
import sys
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
cv2 = pytest.importorskip("cv2")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "deploy/robot/omx"))
import cell_checkerboard as cb  # noqa: E402
import cell_focal_heights as fh  # noqa: E402

F = 615.0
K = np.array([[F, 0, 320], [0, F, 240], [0, 0, 1]])
PPM = 2000  # board art pixels per metre
ART = cv2.copyMakeBorder(cb.charuco_image((int(0.14 * PPM), int(0.20 * PPM))), 30, 30, 30, 30, cv2.BORDER_CONSTANT, value=255)
TO_M = np.array([[1 / PPM, 0, -30 / PPM], [0, 1 / PPM, -30 / PPM], [0, 0, 1]])


def frame(plane_m, pixel, yaw_deg, tilt_deg=13.1, extra_tilt_deg=0.0):
    """The board lying on a horizontal plane `plane_m` from a camera tilted `tilt_deg`, its centre at `pixel`."""
    R = cv2.Rodrigues(np.array([np.radians(tilt_deg + extra_tilt_deg), 0, 0]))[0] @ \
        cv2.Rodrigues(np.array([0, 0, np.radians(yaw_deg)]))[0]
    ray = np.linalg.solve(K, [pixel[0], pixel[1], 1.0])
    centre = ray * plane_m / abs(float(R[:, 2] @ ray))
    t = centre - R @ [0.07, 0.10, 0]
    H = K @ np.column_stack([R[:, 0], R[:, 1], t]) @ TO_M
    return cv2.warpPerspective(ART, H, (640, 480), borderValue=200)


def test_focal_from_two_heights_wherever_the_board_lies():
    low = fh.detections([frame(0.59, (300, 260), 5), frame(0.59, (305, 262), 5)])
    high = fh.detections([frame(0.50, (360, 200), -20), frame(0.50, (362, 201), -20)])  # 90 mm up, moved, turned
    out = fh.focal_from_heights(low, high, (640, 480), 0.090)
    assert out["accepted"] is True, out
    assert abs(out["f_px"] - F) < 0.02 * F
    assert abs(out["distance_low_m"] - 0.59) < 0.01
    assert out["f_pairs_px"][0] <= out["f_px"] <= out["f_pairs_px"][1]
    lifted = fh.detections([frame(0.50, (360, 200), -20), frame(0.48, (362, 201), -20)])  # one view on a book
    assert fh.focal_from_heights(low, lifted, (640, 480), 0.090)["reasons"] == ["board_moved_within_a_height"]


def test_refuses_a_board_not_lying_flat_and_a_lift_no_focal_length_explains():
    low = fh.detections([frame(0.59, (300, 260), 5), frame(0.59, (305, 262), 5)])
    propped = fh.detections([frame(0.50, (360, 200), 0, extra_tilt_deg=8), frame(0.50, (362, 201), 0, extra_tilt_deg=8)])
    assert "boards_not_parallel" in fh.focal_from_heights(low, propped, (640, 480), 0.090)["reasons"]
    same = fh.detections([frame(0.59, (320, 240), 0), frame(0.59, (322, 241), 0)])
    assert fh.focal_from_heights(low, same, (640, 480), 0.090)["reasons"] == ["lift_not_explained_by_any_focal_length"]
    assert fh.focal_from_heights(low[:1], same, (640, 480), 0.090)["reasons"] == ["need_two_views_per_height"]
    with pytest.raises(ValueError, match="lift"):
        fh.focal_from_heights(low, same, (640, 480), 0.5)
