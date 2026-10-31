"""cell_frame (D-933): the top camera found from the gripper marker, the base and surface markers learned once, then a
bumped camera and a moved Pinky are re-solved from the markers and a box pixel still lands on its arm point."""
import sys
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
cv2 = pytest.importorskip("cv2")
if not hasattr(cv2, "aruco"):
    pytest.skip("OpenCV without aruco", allow_module_level=True)
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy/robot/omx"))
import cell_frame as cf  # noqa: E402
import cell_marks  # noqa: E402
import cell_observe  # noqa: E402

K = np.array([[560.0, 0, 322], [0, 560.0, 238], [0, 0, 1]])
DIST = np.array([-0.08, 0.02, 0.0, 0.0, 0.0])
Z = {"base": 0.0, "board": 0.012, "belt": 0.064, "pinky": 0.06}


def rot(rx, ry, rz):
    return cv2.Rodrigues(np.array([rx, ry, rz], float))[0]


def looking_down(x, y, h, tilt=(0.05, -0.03, 0.4)):
    """The top camera 0.65 m up, optical axis down, slightly tilted and turned about the vertical."""
    return rot(np.pi, 0, 0) @ rot(*tilt), np.array([x, y, h])


CAMERA = looking_down(0.12, 0.05, 0.65)


def square(cx, cy, z, side=0.025, turn=0.2):
    c, s = np.cos(turn), np.sin(turn)
    return [np.array([cx + c * u - s * v, cy + s * u + c * v, z]) for u, v in
            ((-side / 2, -side / 2), (side / 2, -side / 2), (side / 2, side / 2), (-side / 2, side / 2))]


def layout(slot=1):
    ids = cf.slot_ids(slot)
    out = {ids["base"][0]: square(0.03, -0.06, Z["base"]), ids["base"][1]: square(0.03, 0.10, Z["base"])}
    spots = {"board": [(0.12, -0.10), (0.30, -0.10), (0.30, 0.10), (0.14, 0.12)],
             "belt": [(0.0, 0.20), (0.22, 0.21), (0.0, 0.26), (0.22, 0.27)],
             "pinky": [(-0.14, -0.02), (-0.05, -0.03), (-0.13, 0.13), (-0.04, 0.12)]}
    for name, block in zip(("board", "belt", "pinky"), ids["surfaces"]):
        for i, (x, y) in zip(block, spots[name]):
            out[i] = square(x, y, Z[name])
    return out


def seen_by(camera, points: dict, moved=None) -> dict:
    out = {}
    for i, pts in points.items():
        pts = [moved(i, p) if moved else p for p in pts]
        out[i] = np.array([cf.project(p, K, DIST, camera) for p in pts])
    return out


def learned():
    rng = np.random.default_rng(3)
    offset = np.array([0.0, 0.0, 0.07])  # marker 70 mm above the TCP in the gripper frame
    views = []
    for k in range(14):
        R = rot(np.pi, 0, 0) @ rot(0, 0, 0.5 * k)  # gripper down, turned
        t = np.array([0.10 + 0.08 * rng.random(), -0.06 + 0.14 * rng.random(), 0.08 + 0.08 * (k % 3)])
        views.append((R, t, np.array(cf.project(t + R @ offset, K, DIST, CAMERA)) + rng.normal(0, 0.3, 2)))
    camera, rms = cf.seed(views, K, DIST, offset)
    record = cf.learn(seen_by(CAMERA, layout()), K, DIST, camera, 1, Z, ["board", "belt", "pinky"])
    return record, camera, rms


def test_slot_ids_are_the_print_sheet_table():
    assert cf.slot_ids(1) == {"gripper": 35, "base": [36, 37], "surfaces": [[38, 39, 40, 41], [42, 43, 44, 45], [46, 47, 48, 49]]}
    assert [cf.slot_ids(n)["gripper"] for n in (1, 2, 3, 4)] == [35, 50, 65, 80]


def test_the_gripper_marker_at_fk_points_gives_the_camera_and_the_markers_their_arm_corners():
    record, camera, rms = learned()
    assert rms < 1.0
    assert np.linalg.norm(camera[1] - CAMERA[1]) < 0.004 and cf._angle(camera[0].T @ CAMERA[0]) < 0.3
    truth = layout()
    for i in (36, 37, 38, 47):
        assert np.abs(np.array(record["markers"][str(i)]) - truth[i]).max() < 0.004


def test_a_bumped_camera_is_re_solved_from_the_base_markers_and_the_box_still_lands():
    record, _, _ = learned()
    bumped = (rot(0, 0, np.radians(7)) @ CAMERA[0], CAMERA[1] + np.array([0.02, -0.01, 0.0]))
    cf.update(record, seen_by(bumped, layout()))
    assert record["now"]["base_seen"] and cf.drift(record)["camera"]["deg"] == pytest.approx(7, abs=0.6)
    box = np.array([0.22, 0.0, Z["board"] + 0.036])  # a container top on the board
    pixel = cf.project(box, K, DIST, bumped)
    assert np.linalg.norm(cf.to_arm(record, "board", pixel, box[2]) - box) < 0.003
    assert np.linalg.norm(np.array(cf.to_pixel(record, box[:2], box[2])) - pixel) < 2.0
    # the setup pose alone would have put it centimetres off: what the old per-surface maps did after a bump
    record["now"]["camera_in_base"] = cf._pose(record["camera_in_base"])
    assert np.linalg.norm(cf.to_arm(record, "board", pixel, box[2]) - box) > 0.02


def test_a_moved_pinky_is_followed_by_its_markers_and_one_marker_is_not_enough():
    record, _, _ = learned()
    pinky = set(cf.slot_ids(1)["surfaces"][2])
    turn, shift = rot(0, 0, np.radians(6)), np.array([0.035, -0.02, 0.0])  # ~45 px at the top camera
    moved = lambda i, p: turn @ p + shift if i in pinky else p  # noqa: E731
    seen = seen_by(CAMERA, layout(), moved)
    cf.update(record, seen)
    assert cf.drift(record)["pinky"]["mm"] > 30 and "board" in record["now"]["motion"]
    assert cf.drift(record)["board"]["mm"] < 3
    box_at_setup = np.array([-0.09, 0.05, Z["pinky"]])
    box = turn @ box_at_setup + shift
    pixel = cf.project(box, K, DIST, CAMERA)
    assert np.linalg.norm(cf.to_arm(record, "pinky", pixel, Z["pinky"]) - box) < 0.003
    only_one = {i: c for i, c in seen.items() if i not in pinky or i == 46}
    cf.update(record, only_one)
    assert "pinky" not in record["now"]["motion"]


def test_learning_refuses_without_a_base_marker_in_view():
    _, camera, _ = learned()
    seen = {i: c for i, c in seen_by(CAMERA, layout()).items() if i not in (36, 37)}
    with pytest.raises(ValueError, match="no base marker"):
        cf.learn(seen, K, DIST, camera, 1, Z, ["board", "belt", "pinky"])


def test_markers_on_a_printed_sheet_are_found_with_their_corners():
    page = cell_marks.sheet((25,), (36, 49, 94), dpi=150)
    found = cf.corners(page)
    assert set(found) == {36, 49, 94}
    side = np.linalg.norm(found[36][1] - found[36][0])
    assert side == pytest.approx(25 * 150 / 25.4, rel=0.03)


def test_the_observe_seam_uses_the_model_when_the_calibration_has_one():
    record, _, _ = learned()
    cf.update(record, seen_by(CAMERA, layout()))
    config = {"sites": {"board": {"z": Z["board"] + 0.036}}}
    calibration = {"sites": {}, "cameras": {"top": record}}
    box = np.array([0.20, 0.03, config["sites"]["board"]["z"]])
    pixel = cell_observe.predicted_pixel(config, calibration, "board", box[:2])
    assert np.linalg.norm(np.array(pixel) - cf.project(box, K, DIST, CAMERA)) < 2.0
    est = cell_observe.model_estimate(config, record, "board", {"cx": pixel[0], "cy": pixel[1], "yaw": 10.0})
    assert np.linalg.norm(np.array(est["arm_m"]) - box[:2]) < 0.003 and est["map"] == "model" and est["base_seen"]
