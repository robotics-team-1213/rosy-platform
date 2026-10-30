"""cell_checkerboard: a simulated wrist camera on the gripper is recovered by hand-eye from board views, and a pixel
then maps to the floor point within a millimetre - the depth-aware geometry the 2-D map and Jacobian lacked."""
import sys
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
cv2 = pytest.importorskip("cv2")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "deploy/robot/omx"))
import cell_checkerboard as cb  # noqa: E402

K = np.array([[600.0, 0, 320], [0, 600.0, 240], [0, 0, 1]])
DIST = np.zeros(5)


def rot(rx, ry, rz):
    return cv2.Rodrigues(np.array([rx, ry, rz], float))[0]


def look_at(eye, target, roll):
    """Camera pose in the base frame: optical axis (z) from eye to target, rolled about it."""
    z = (target - eye) / np.linalg.norm(target - eye)
    x = np.cross(z, [0.0, 0.0, 1.0])
    x /= np.linalg.norm(x)
    R = np.column_stack([x, np.cross(z, x), z]) @ rot(0, 0, roll)
    return R, eye


def inverse(p):
    return p[0].T, -p[0].T @ p[1]


def test_hand_eye_then_pixel_to_floor_within_a_millimetre():
    board = cb.board_points(7, 5, 0.015)
    board_in_base = (rot(0, 0, 0.3), np.array([0.05, 0.15, 0.006]))  # flat on the floor
    centre = cb.compose(board_in_base, (np.eye(3), np.array([0.045, 0.03, 0.0])))[1]
    cam_in_gripper = (rot(0.4, 0.1, 0.2), np.array([0.01, -0.03, 0.05]))  # an oblique wrist camera
    grippers, boards = [], []
    for k in range(10):  # hovers that move, change height, yaw and tilt (one rotation axis alone leaves an offset unobservable)
        eye = centre + np.array([0.05 * np.cos(k), 0.05 * np.sin(k), 0.19 + 0.01 * (k % 3)])
        cam = look_at(eye, centre, 0.4 * k)
        grippers.append(cb.compose(cam, inverse(cam_in_gripper)))
        b_in_c = cb.compose(inverse(cam), board_in_base)
        pts, _ = cv2.projectPoints(board, cv2.Rodrigues(b_in_c[0])[0], b_in_c[1], K, DIST)
        assert ((pts > 0) & (pts < [640, 480])).all()  # the whole board is in view, as a real capture needs
        boards.append(cb.board_pose(pts.astype(np.float32), board, K, DIST))
    R, t = cb.hand_eye(grippers, boards)
    assert np.allclose(R, cam_in_gripper[0], atol=1e-3) and np.allclose(t, cam_in_gripper[1], atol=1e-3)
    # a container top 36 mm above the floor: project it from the last view, map the pixel back on z = 0.036
    target = centre + np.array([0.01, -0.01, 0.03])
    cam = cb.compose(grippers[-1], (R, t))
    p, _ = cv2.projectPoints(target.reshape(1, 3), cv2.Rodrigues(cam[0].T)[0], -cam[0].T @ cam[1], K, DIST)
    back = cb.pixel_to_plane(p.reshape(2), K, DIST, cam, target[2])
    assert np.allclose(back, target, atol=1e-3)
    # the depth matters: the same pixel read on the floor plane instead lands centimetres away
    assert np.linalg.norm(cb.pixel_to_plane(p.reshape(2), K, DIST, cam, 0.006) - target) > 0.01


def test_charuco_page_detects_whole_and_half_view():
    page = cb.page("charuco")
    img = cv2.resize(page, None, fx=0.25, fy=0.25, interpolation=cv2.INTER_AREA)  # about 3 px/mm, like the top camera
    whole = cb.find_charuco(img, cb.charuco_board())
    assert whole is not None and len(whole[0]) == 6 * 4  # every inner corner, named
    half = cb.find_charuco(img[:, : img.shape[1] // 2], cb.charuco_board())
    assert half is not None and len(half[0]) >= 6  # a partial view still gives corners (a plain board gives none)
    assert cb.find_corners(cb.page("checker"), 7, 5) is not None  # the plain page is found by the plain detector


def test_top_down_hand_eye_from_moves_and_yaws_where_tsai_cannot():
    board = cb.board_points(7, 5, 0.015)
    board_in_base = (rot(0, 0, 0.3), np.array([0.05, 0.15, 0.006]))
    centre = cb.compose(board_in_base, (np.eye(3), np.array([0.045, 0.03, 0.0])))[1]
    cam_in_gripper = (rot(0.35, 0.05, 0.1), np.array([0.01, -0.03, 0.05]))  # tilted wrist camera
    down = rot(np.pi, 0, 0)
    grippers, boards = [], []
    for yaw in (-0.5, 0.0, 0.5):  # the OMX reaches only gripper-down poses: yaw and position change, nothing tilts
        for z in (0.24, 0.27):
            for dx, dy in ((0, 0), (0.02, 0), (0, 0.02), (-0.02, 0), (0, -0.02)):
                g = (rot(0, 0, yaw) @ down, centre + np.array([0, 0, z]))
                cam = cb.compose(g, cam_in_gripper)  # aim: shift the hover so the optical axis meets the board centre
                axis = cam[0][:, 2]
                hit = cam[1] + (centre[2] - cam[1][2]) / axis[2] * axis
                g = (g[0], g[1] + np.array([centre[0] - hit[0] + dx, centre[1] - hit[1] + dy, 0]))
                cam = cb.compose(g, cam_in_gripper)
                b_in_c = cb.compose(inverse(cam), board_in_base)
                pts, _ = cv2.projectPoints(board, cv2.Rodrigues(b_in_c[0])[0], b_in_c[1], K, DIST)
                if (b_in_c[0] @ board.T + b_in_c[1][:, None])[2].min() <= 0 or not ((pts > 0) & (pts < [640, 480])).all():
                    continue  # a real capture skips views without the board
                grippers.append(g)
                boards.append(cb.board_pose(pts.astype(np.float32), board, K, DIST))
    assert len(grippers) >= 12
    out = cb.hand_eye_top_down(grippers, boards, board_z=0.006)
    assert np.allclose(out["R"], cam_in_gripper[0], atol=1e-3) and np.allclose(out["t"], cam_in_gripper[1], atol=1e-3)
    assert np.allclose(out["board_origin"], board_in_base[1], atol=1e-3) and out["rms_mm"] < 0.1
    tsai = cb.hand_eye(grippers, boards)  # the standard method on the same gripper-down views misses the camera
    assert not np.allclose(tsai[1], cam_in_gripper[1], atol=5e-3)


def test_intrinsics_from_hand_tilted_charuco_views():
    ppm = 4000  # board image pixels per metre
    board_obj = cb.charuco_board()
    render = getattr(board_obj, "generateImage", None) or board_obj.draw
    art = render((int(0.175 * ppm), int(0.125 * ppm)), marginSize=0, borderBits=1)
    art = cv2.copyMakeBorder(art, 40, 40, 40, 40, cv2.BORDER_CONSTANT, value=255)
    to_m = np.array([[1 / ppm, 0, -40 / ppm - 0.0875], [0, 1 / ppm, -40 / ppm - 0.0625], [0, 0, 1]])  # centred on the board

    class Hand:  # a person tilting the board in front of the camera
        k = 0

        def frame(self, camera):
            Hand.k += 1
            R = rot(0.35 * np.sin(Hand.k), 0.35 * np.cos(1.3 * Hand.k), 0.2 * Hand.k)
            H = K @ np.column_stack([R[:, 0], R[:, 1], np.array([0.01, -0.01, 0.30])]) @ to_m
            return cv2.warpPerspective(art, H, (640, 480), borderValue=200)

    out = cb.grab_intrinsics(Hand(), "wrist", 10, every_s=0, log=lambda _: None)
    assert out["rms_px"] < 1.0 and abs(out["K"][0][0] - 600) < 15 and abs(out["K"][0][2] - 320) < 15
