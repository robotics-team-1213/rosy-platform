"""cell_shared_markers: with the top D435's factory calibration, depth turns marker corners the top camera sees into
millimetres, the side camera's pose comes out of the same markers, and the printed board's spacing checks the top
focal length without Intel's colour calibration."""
import json
import sys
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
cv2 = pytest.importorskip("cv2")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "deploy/robot/omx"))
import cell_checkerboard as cb  # noqa: E402
import cell_shared_markers as sm  # noqa: E402

COLOUR_K = np.array([[618.5, 0, 322.3], [0, 618.7, 236.6], [0, 0, 1.0]])
FACTORY = {"K": COLOUR_K.tolist(), "depth": {"size": [640, 480], "K": [[388.7, 0, 321.0], [0, 388.7, 245.0], [0, 0, 1]]},
           "depth_to_colour": {"R": np.eye(3).tolist(), "t_m": [0.0145, 0.0, 0.0]}}
PPM = 2000  # texture pixels per metre of table
SIDE_K = np.array([[900.0, 0, 320], [0, 900.0, 240], [0, 0, 1]])


def texture():
    """0.34 x 0.26 m of table: the printed board at the left, markers 40 and 45 (40 mm; the board itself uses 0-34) at the right."""
    tex = np.full((int(0.26 * PPM), int(0.34 * PPM)), 255, np.uint8)
    board = cb.charuco_image((int(0.14 * PPM), int(0.20 * PPM)))
    tex[60:60 + board.shape[0], 40:40 + board.shape[1]] = board
    d = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    draw = getattr(cv2.aruco, "generateImageMarker", None) or cv2.aruco.drawMarker
    for marker_id, (x, y) in ((40, (420, 80)), (45, (500, 300))):
        m = cv2.copyMakeBorder(draw(d, marker_id, 80), 10, 10, 10, 10, cv2.BORDER_CONSTANT, value=255)
        tex[y:y + 100, x:x + 100] = m
    return tex


def look_at(eye, target):
    z = (target - eye) / np.linalg.norm(target - eye)
    x = np.cross(z, [0, 0, 1.0])  # the table normal here is roughly the colour camera's -z
    x /= np.linalg.norm(x)
    return np.vstack([x, np.cross(z, x), z])  # rows: camera axes in the top camera frame


def scene():
    """(top colour, depth mm, side image, plane rotation, plane origin m, side R, side t m)."""
    Rp = cv2.Rodrigues(np.radians([11.0, 0, 3.0]))[0]  # table seen 11 deg off the optical axis
    origin = np.array([-0.17, -0.13, 0.60])
    to_m = np.array([[1 / PPM, 0, 0], [0, 1 / PPM, 0], [0, 0, 1]])
    tex = texture()
    top = cv2.warpPerspective(tex, COLOUR_K @ np.column_stack([Rp[:, 0], Rp[:, 1], origin]) @ to_m, (640, 480),
                              borderValue=180)
    n = Rp[:, 2]
    dK = np.asarray(FACTORY["depth"]["K"])
    v, u = np.mgrid[0:480, 0:640]
    rays = np.dstack([(u - dK[0, 2]) / dK[0, 0], (v - dK[1, 2]) / dK[1, 1], np.ones((480, 640))])
    depth = (n @ origin - n @ np.array(FACTORY["depth_to_colour"]["t_m"])) / (rays @ n) * 1000.0
    centre = origin + Rp @ [0.17, 0.13, 0]
    eye = centre + np.array([0.0, 0.35, -0.25])  # beside the table, looking down at it obliquely
    Rs = look_at(eye, centre)
    ts = -Rs @ eye
    side = cv2.warpPerspective(tex, SIDE_K @ np.column_stack([Rs @ Rp[:, 0], Rs @ Rp[:, 1], Rs @ origin + ts]) @ to_m,
                               (640, 480), borderValue=180)
    return (cv2.cvtColor(top, cv2.COLOR_GRAY2BGR), np.round(depth).astype(np.uint16),
            cv2.cvtColor(side, cv2.COLOR_GRAY2BGR), Rs, ts)


def test_marker_corners_in_millimetres_and_the_side_camera_from_them():
    top, depth, side, Rs, ts = scene()
    corners = sm.marker_corners(top, depth, FACTORY)
    assert {40, 45} <= set(corners)
    assert all(abs(corners[i]["edge_mm"] - 40.0) < 1.0 for i in (40, 45))
    assert abs(corners[0]["edge_mm"] - 15.0) < 1.0  # the board's own markers are shared markers too
    misprinted = sm.marker_corners(top, depth, FACTORY, edge_mm={40: 50.0, 45: 40.0})
    assert 40 not in misprinted and 45 in misprinted
    pose = sm.side_pose(side, SIDE_K, np.zeros(5), json.loads(json.dumps(corners)))  # as read back from a file
    assert pose["ok"] is True, pose
    turn = np.degrees(np.arccos(np.clip((np.trace(np.asarray(pose["R"]) @ Rs.T) - 1) / 2, -1, 1)))
    assert turn < 1.0 and np.linalg.norm(np.asarray(pose["t_mm"]) - ts * 1000) < 10.0


def test_side_needs_two_shared_markers():
    top, depth, side, _, _ = scene()
    corners = sm.marker_corners(top, depth, FACTORY)
    one = {k: v for k, v in corners.items() if k == 40}
    assert sm.side_pose(side, SIDE_K, np.zeros(5), one)["reason"] == "need two markers seen by both cameras"


def test_depth_checks_the_top_focal_length():
    top, depth, _, _, _ = scene()
    found = cb.find_charuco(top, cb.charuco_board(*cb.PRINTED), min_corners=12)
    good = sm.focal_from_depth(*found, depth, FACTORY, (640, 480))
    assert good["ok"] is True and abs(good["f_px"] - 618.5) < 0.015 * 618.5, good
    wrong = dict(FACTORY, K=(COLOUR_K * [[1.08], [1.08], [1]]).tolist())  # a record 8 % off
    assert sm.focal_from_depth(*found, depth, wrong, (640, 480))["ok"] is False
