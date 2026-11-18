"""cell_checkerboard: a simulated wrist camera on the gripper is recovered by hand-eye from board views, and a pixel
then maps to the floor point within a millimetre - the depth-aware geometry the 2-D map and Jacobian lacked."""
import sys
import hashlib
import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

np = pytest.importorskip("numpy")
cv2 = pytest.importorskip("cv2")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "deploy/robot/omx"))
import cell_checkerboard as cb  # noqa: E402
import cell_camera_binding as cbind  # noqa: E402

K = np.array([[600.0, 0, 320], [0, 600.0, 240], [0, 0, 1]])
DIST = np.zeros(5)
BINDING = {"viewer_label": "top", "topic": "/top_camera/image_raw", "role": "top",
           "device_alias": "/dev/v4l/by-path/test", "usb_id": "0001:0002", "usb_port": "1-2",
           "usb_interface": "1-2:1.0", "serial": "camera-test", "focus_controls": {},
           "unique_hardware_identity": True, "viewer_invocation_id": "session-1",
           "producer_invocation_id": "producer-1"}


def test_runtime_viewer_topic_must_match_jpeg_source(monkeypatch):
    state = {"cameras": {"top": {"topic": BINDING["topic"], "fresh": True,
                                   "sequence": 3, "source_stamp": 123.0}}}
    monkeypatch.setattr(cbind.urllib.request, "urlopen", lambda url, timeout: io.BytesIO(json.dumps(state).encode()))
    assert cbind.runtime_viewer_state("top", BINDING["topic"]) == (3, 123.0)
    with pytest.raises(ValueError, match="running viewer source"):
        cbind.runtime_viewer_state("top", "/different/image_raw")


def test_live_camera_binding_uses_viewer_registry_usb_and_focus(monkeypatch):
    import camera_readiness
    import cell_upkeep
    import omx_cameras
    import omx_devices

    monkeypatch.setattr(cell_upkeep, "viewer_labels", lambda: {"top": "/top_camera/image_raw"})
    monkeypatch.setattr(omx_cameras, "load", lambda: {"cameras": [{"role": "top", "topic": "/top_camera/image_raw",
                                                                    "device": BINDING["device_alias"], "usb_id": BINDING["usb_id"],
                                                                    "frame": "top_camera"}]})
    monkeypatch.setattr(camera_readiness, "identity", lambda device: {"realpath": "/dev/video2", "rdev": 10})
    monkeypatch.setattr(omx_devices, "video_facts", lambda: {"/dev/video2": {"id": BINDING["usb_id"],
                                                                              "usb": BINDING["usb_port"],
                                                                              "interface": BINDING["usb_interface"],
                                                                              "serial": BINDING["serial"]}})
    monkeypatch.setattr(camera_readiness, "producer", lambda role, device, wait_s: {"MainPID": "1", "InvocationID": "producer-1"})
    monkeypatch.setattr(cbind, "viewer_session", lambda: "session-1")
    monkeypatch.setattr(cbind, "runtime_viewer_state", lambda label, topic: (1, 1.0))
    monkeypatch.setattr(cbind, "producer_argv", lambda pid: ["python3", "camera_source.py", "--device", BINDING["device_alias"],
                                                             "--topic", BINDING["topic"], "--frame-id", "top_camera"])
    monkeypatch.setattr(camera_readiness, "command", lambda argv: "focus_absolute 0x009a090a (int) : min=0 max=255 value=15")
    monkeypatch.setattr(camera_readiness, "get_controls", lambda device, names: {"focus_absolute": 15})
    assert cb.live_camera_binding("top") == BINDING | {"focus_controls": {"focus_absolute": 15}}
    monkeypatch.setattr(cbind, "producer_argv", lambda pid: ["python3", "camera_source.py", "--device", BINDING["device_alias"],
                                                             "--topic", "/wrong", "--frame-id", "top_camera"])
    with pytest.raises(ValueError, match="producer command"):
        cb.live_camera_binding("top")
    monkeypatch.setattr(cbind, "producer_argv", lambda pid: ["python3", "camera_source.py", "--device", BINDING["device_alias"],
                                                             "--topic", BINDING["topic"], "--frame-id", "top_camera"])
    monkeypatch.setattr(omx_devices, "video_facts", lambda: {
        "/dev/video2": {"id": BINDING["usb_id"], "usb": "1-2", "interface": "1-2:1.0", "serial": "camera-test"},
        "/dev/video4": {"id": BINDING["usb_id"], "usb": "1-3", "interface": "1-3:1.0", "serial": "camera-test"}})
    assert cb.live_camera_binding("top")["unique_hardware_identity"] is False
    monkeypatch.setattr(omx_devices, "video_facts", lambda: {"/dev/video2": {"id": BINDING["usb_id"],
                                                                              "usb": "1-2", "interface": "1-2:1.0",
                                                                              "serial": "SN0001"}})
    assert cb.live_camera_binding("top")["unique_hardware_identity"] is False
    with pytest.raises(ValueError, match="unique registered source"):
        cb.live_camera_binding("side")


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
    assert whole is not None and len(whole[0]) == 6 * 9  # every inner corner, named
    half = cb.find_charuco(img[:, : img.shape[1] // 2], cb.charuco_board())
    assert half is not None and len(half[0]) >= 6  # a partial view still gives corners (a plain board gives none)
    assert cb.find_corners(cb.page("checker"), 7, 5) is not None  # the plain page is found by the plain detector


def test_fleet_print_sheet_board_has_enough_named_corners_for_offline_fit():
    board = cb.charuco_board(*cb.PRINTED)
    draw = getattr(board, "generateImage", None) or board.draw
    image = draw((700, 1000), marginSize=20, borderBits=1)
    found = cb.find_charuco(image, board, min_corners=30)
    assert found is not None and len(found[0]) >= 30


def test_charuco_legacy_api_keeps_corner_ids_and_rejects_missing_detections(monkeypatch):
    """Exercise the 4.6 API even on test PCs with newer OpenCV."""
    image = np.full((50, 70), 255, np.uint8)
    points = np.arange(72, dtype=np.float32).reshape(24, 3)
    ids = np.array([[22], [1], [17], [3], [8], [12]], np.int32)
    corners = np.arange(12, dtype=np.float32).reshape(6, 1, 2)
    dictionary = object()
    marker_ids = np.array([[4]], np.int32)

    def draw(size, *, marginSize, borderBits):
        assert size == (70, 50) and marginSize == 0 and borderBits == 1
        return image

    board = SimpleNamespace(dictionary=dictionary, chessboardCorners=points, draw=draw)

    def create(cols, rows, square, marker, selected):
        assert (cols, rows, square, marker) == (7, 5, 0.025, 0.018)
        assert selected is dictionary
        return board

    def detect(gray, selected):
        assert gray is image and selected is dictionary
        return [corners], marker_ids, []

    def interpolate(markers, detected_ids, gray, selected):
        assert markers[0] is corners and detected_ids is marker_ids
        assert gray is image and selected is board
        return len(ids) if ids is not None else 0, corners, ids

    monkeypatch.setattr(cv2, "aruco", SimpleNamespace(
        DICT_4X4_50=0, getPredefinedDictionary=lambda _: dictionary,
        CharucoBoard_create=create, detectMarkers=detect, interpolateCornersCharuco=interpolate,
    ))
    legacy = cb.charuco_board(7, 5, 0.025, 0.018)
    assert cb.charuco_image((70, 50), board=legacy) is image
    obj, pix = cb.find_charuco(image, legacy)
    np.testing.assert_array_equal(obj, points[ids.ravel()])
    np.testing.assert_array_equal(pix, corners)
    assert obj.dtype == pix.dtype == np.float32
    assert cb.find_charuco(image, board, min_corners=7) is None
    ids = None
    assert cb.find_charuco(image, board) is None
    marker_ids = None
    assert cb.find_charuco(image, board) is None


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
    legacy = cb.charuco_board(7, 5, 0.025, 0.018)
    art = cb.charuco_image((int(0.175 * ppm), int(0.125 * ppm)), board=legacy)
    art = cv2.copyMakeBorder(art, 40, 40, 40, 40, cv2.BORDER_CONSTANT, value=255)
    to_m = np.array([[1 / ppm, 0, -40 / ppm - 0.0875], [0, 1 / ppm, -40 / ppm - 0.0625], [0, 0, 1]])  # centred on the board

    class Hand:  # a person tilting the board in front of the camera
        k = 0

        def frame(self, camera):
            Hand.k += 1
            R = rot(0.35 * np.sin(Hand.k), 0.35 * np.cos(1.3 * Hand.k), 0.2 * Hand.k)
            H = K @ np.column_stack([R[:, 0], R[:, 1], np.array([0.01, -0.01, 0.30])]) @ to_m
            return cv2.warpPerspective(art, H, (640, 480), borderValue=200)

    out = cb.grab_intrinsics(Hand(), "wrist", 10, board=legacy, every_s=0, log=lambda _: None)
    assert out["rms_px"] < 1.0 and abs(out["K"][0][0] - 600) < 15 and abs(out["K"][0][2] - 320) < 15
    assert out["dist"][4] == 0  # D-933 fixes k3


def test_board_view_scale_follows_distance_not_tilt_and_mirrored_tilts_differ():
    obj = np.column_stack([np.mgrid[0:6, 0:9].T.reshape(-1, 2) * 0.02, np.zeros(54)])

    def view(z, tilt_deg):
        pix, _ = cv2.projectPoints(obj - [0.05, 0.08, 0], np.array([0, np.radians(tilt_deg), 0]), np.array([0, 0, z]), K, None)
        return cb.board_view(obj, pix)

    flat, left, right, far = view(0.4, 0), view(0.4, 30), view(0.4, -30), view(0.6, 45)
    assert abs(left[0] / flat[0] - 1) < 0.01 and abs(right[0] / flat[0] - 1) < 0.01  # was 1495 / 2688 vs 2250
    assert abs(flat[0] / far[0] - 1.5) < 0.02
    assert not cb._same_look((320, 240, left[0], left[1]), (320, 240, right[0], right[1]))
    assert cb._same_look((320, 240, left[0], left[1]), (325, 238, left[0], left[1]))
    assert cb.board_view(obj[:3], np.zeros((3, 1, 2))) is None


def test_offline_intrinsics_rejects_wrong_print_scale_and_repeated_frames(tmp_path):
    assert cb.intrinsics_from_frames(tmp_path, "top", 50.0)["checks"]["reasons"] == ["need_at_least_25_valid_views"]
    with pytest.raises(ValueError, match="scale bar"):
        cb.intrinsics_from_frames(tmp_path, "top", 51.0)
    for i in range(25):
        path = tmp_path / f"view-{i:02}.png"
        cv2.imwrite(str(path), np.full((480, 640, 3), 100, np.uint8))
        path.with_suffix(".json").write_text(json.dumps({"camera": "top", "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                                                       "source_seq": i, "source_stamp": float(i + 1), "device_binding": BINDING}))
    out = cb.intrinsics_from_frames(tmp_path, "top", 50.0)
    assert out["accepted"] is False and "K" not in out
    assert out["checks"]["unique_views"] == 1
    receipt = tmp_path / "view-01.json"
    row = json.loads(receipt.read_text())
    row["source_seq"] = 0
    receipt.write_text(json.dumps(row))
    with pytest.raises(ValueError, match="sequence or stamp did not advance"):
        cb.intrinsics_from_frames(tmp_path, "top", 50.0)


def test_offline_intrinsics_records_source_and_requires_coverage_tilt_and_rms(tmp_path, monkeypatch):
    for i in range(25):
        img = np.full((480, 640, 3), 220, np.uint8)
        img[0, 0] = i
        path = tmp_path / f"view-{i}.png"  # lexicographic order is 0,1,10,11,...,2
        cv2.imwrite(str(path), img)
        path.with_suffix(".json").write_text(json.dumps({"camera": "top", "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                                                       "source_seq": i, "source_stamp": float(i + 1), "device_binding": BINDING}))
    objects = cb.board_points(6, 6, 0.02)

    def found(img, board, min_corners):
        i = int(img[0, 0, 0])
        x = 85 + (i % 5) * 110
        y = 55 + (i // 5) * 90
        grid = np.mgrid[0:6, 0:6].T.reshape(-1, 2).astype(np.float32) * 10 * (1 + 0.02 * i)  # nearer and farther
        return objects, (grid + [x, y]).reshape(-1, 1, 2)

    monkeypatch.setattr(cb, "find_charuco", found)
    monkeypatch.setattr(cb, "calibrate_intrinsics", lambda *_: {"K": K.copy(), "dist": DIST.copy(), "rms_px": 0.3})
    calls = iter(range(25))

    def pose(*_):
        i = next(calls)
        return rot(0.1 + i * 0.02, 0.15 + i * 0.02, 0), np.zeros(3)

    monkeypatch.setattr(cb, "board_pose", pose)
    out = cb.intrinsics_from_frames(tmp_path, "top", 50.0)
    assert out["accepted"] is True and len(out["source_frames"]) == 25
    assert [row["source_seq"] for row in out["source_frames"]] == list(range(25))
    assert all(len(row["sha256"]) == 64 for row in out["source_frames"])
    assert out["board"] == {"cols": 7, "rows": 10, "square_m": 0.020,
                             "marker_m": 0.015, "dictionary": "DICT_4X4_50", "scale_bar_mm": 50.0}
    assert out["size"] == [640, 480] and out["rms_px"] == 0.3
    assert out["checks"]["image_coverage"]["left"] <= 0.2

    for receipt in tmp_path.glob("view-*.json"):
        row = json.loads(receipt.read_text())
        row["device_binding"]["unique_hardware_identity"] = False
        receipt.write_text(json.dumps(row))
    calls = iter(range(25))
    unbound = cb.intrinsics_from_frames(tmp_path, "top", 50.0)
    assert unbound["accepted"] is False and unbound["checks"]["reasons"] == ["camera_identity_unverified"]
    assert unbound["diagnostic_fit"]["K"] == K.tolist() and "K" not in unbound
    for receipt in tmp_path.glob("view-*.json"):
        row = json.loads(receipt.read_text())
        row.pop("device_binding")
        receipt.write_text(json.dumps(row))
    calls = iter(range(25))
    legacy = cb.intrinsics_from_frames(tmp_path, "top", 50.0)
    assert legacy["accepted"] is False and legacy["diagnostic_fit"]["K"] == K.tolist()
    for receipt in tmp_path.glob("view-*.json"):
        row = json.loads(receipt.read_text())
        row["device_binding"] = BINDING
        receipt.write_text(json.dumps(row))

    monkeypatch.setattr(cb, "calibrate_intrinsics", lambda *_: {"K": K.copy(), "dist": DIST.copy(), "rms_px": 0.7})
    calls = iter(range(25))
    bad = cb.intrinsics_from_frames(tmp_path, "top", 50.0)
    assert bad["accepted"] is False and "K" not in bad
    assert "rms_above_0_5_px" in bad["checks"]["reasons"]
    monkeypatch.setattr(cb, "calibrate_intrinsics", lambda pix, obj, size, extra=0: {
        "K": K * [[1.2 if extra else 1, 1, 1], [1, 1, 1], [1, 1, 1]], "dist": DIST.copy(), "rms_px": 0.3})
    calls = iter(range(25))
    swings = cb.intrinsics_from_frames(tmp_path, "top", 50.0)
    assert swings["accepted"] is False and swings["checks"]["reasons"] == ["focal_length_unstable"]
    monkeypatch.setattr(cb, "calibrate_intrinsics", lambda *_: {"K": K.copy(), "dist": DIST.copy(), "rms_px": 0.3})

    def one_distance(img, board, min_corners):
        i = int(img[0, 0, 0])
        grid = np.mgrid[0:6, 0:6].T.reshape(-1, 2).astype(np.float32) * 12
        return objects, (grid + [85 + (i % 5) * 110, 55 + (i // 5) * 90]).reshape(-1, 1, 2)

    monkeypatch.setattr(cb, "find_charuco", one_distance)
    calls = iter(range(25))
    flat = cb.intrinsics_from_frames(tmp_path, "top", 50.0)  # one distance is reported, the focal check decides
    assert flat["accepted"] is True and flat["checks"]["image_coverage"]["distance_ratio"] == 1.0
    def upper_half(img, board, min_corners):  # 2026-11-13's side set: the board never below the middle
        objs, pix = found(img, board, min_corners)
        return objs, pix * [1.0, 0.1] + [0.0, 120.0]  # centres within 36 px of each other vertically

    monkeypatch.setattr(cb, "find_charuco", upper_half)
    short = cb.intrinsics_from_frames(tmp_path, "top", 50.0)
    assert short["accepted"] is False and "K" not in short
    assert "board_not_seen_across_image" in short["checks"]["reasons"]
    assert short["diagnostic_fit"]["K"] == K.tolist() and "cy" in short["diagnostic_fit"]["unpinned"]
    monkeypatch.setattr(cb, "find_charuco", lambda img, board, min_corners: tuple(
        v[:24] for v in found(img, board, min_corners)))
    wrong_layout = cb.intrinsics_from_frames(tmp_path, "top", 50.0)
    assert wrong_layout["accepted"] is False
    assert wrong_layout["checks"]["reasons"] == ["printed_board_layout_not_seen"]
    (tmp_path / "view-0.json").unlink()
    with pytest.raises(ValueError, match="no source receipt"):
        cb.intrinsics_from_frames(tmp_path, "top", 50.0)


def test_live_board_capture_is_bounded_read_only_and_checks_saved_receipts(tmp_path, monkeypatch):
    state = [0]
    monkeypatch.setattr(cb, "live_camera_binding", lambda camera, **kwargs: BINDING)
    monkeypatch.setattr(cb, "viewer_session", lambda: "session-1")
    monkeypatch.setattr(cb, "runtime_viewer_state", lambda label, topic: (state[0], float(state[0])))
    def moved(img, board, min_corners):  # the board a little further across and nearer in each frame
        i = int(img[0, 0, 0]) // 5
        base = np.mgrid[0:4, 0:3].T.reshape(-1, 2).astype(np.float32)
        return np.column_stack([base * 0.02, np.zeros(12)]), (base * (8 + i) + [20 * i, 15 * i]).reshape(-1, 1, 2)

    monkeypatch.setattr(cb, "find_charuco", moved)

    class Camera:
        count = 0
        cameras = {"top": {"url": "http://127.0.0.1:8767/frame/top.jpg"}}

        def act(self, *_):
            raise AssertionError("calibration may not command an arm")

        def frame_receipt(self, camera, *, previous=None, max_age_s):
            assert camera == "top" and max_age_s == 2.0
            assert previous is None if self.count == 0 else previous["source_seq"] == self.count
            self.count += 1
            state[0] = self.count
            image = np.full((480, 640, 3), 180, np.uint8)
            image[:32, :32] = self.count * 5 % 256
            ok, jpg = cv2.imencode(".jpg", image)
            assert ok
            raw = jpg.tobytes()
            return {"image": image, "jpeg_bytes": raw, "jpeg_sha256": hashlib.sha256(raw).hexdigest(),
                    "source_seq": self.count, "source_stamp": float(self.count), "camera": camera}

    folder = tmp_path / "frames"
    rows = []
    # Coverage alone is insufficient to finish: this sweep has no proven tilt diversity.
    assert cb.capture_intrinsics_frames(Camera(), "top", folder, want=40, timeout_s=2, every_s=0, log=rows.append) == 40
    assert len(list(folder.glob("view-*.jpg"))) == 40
    assert rows[0]["missing"] and "bottom-right" in rows[0]["empty_cells"]
    assert rows[-1]["saved"] == 40 and rows[-1]["missing"] == []
    assert "top-right" in rows[-1]["empty_cells"]  # a diagonal sweep passes the gate; the cells still show the gap
    assert json.loads((folder / "view-000.json").read_text())["source_seq"] == 1
    out = cb.intrinsics_from_frames(folder, "top", 50.0)
    assert out["checks"]["valid_views"] == 40
    assert out["source_frames"][0]["source_seq"] == 1
    (folder / "view-000.json").write_text('{"camera":"top","sha256":"wrong"}')
    with pytest.raises(ValueError, match="source receipt"):
        cb.intrinsics_from_frames(folder, "top", 50.0)

    class Stale:
        cameras = Camera.cameras
        def frame_receipt(self, *args, **kwargs):
            raise ValueError("non-advancing frame")

    assert cb.capture_intrinsics_frames(Stale(), "top", tmp_path / "stale", timeout_s=0.01, every_s=0) == 0

    seen = []
    monkeypatch.setattr(cb, "live_camera_binding", lambda camera, **kwargs: (seen.append((camera, kwargs["viewer_label"]))
                                                                        or BINDING | {"viewer_label": "front"}))
    class WristStale(Stale):
        cameras = {"wrist": {"url": "http://127.0.0.1:8767/frame/front.jpg"}}
    assert cb.capture_intrinsics_frames(WristStale(), "wrist", tmp_path / "wrist", timeout_s=0.01, every_s=0) == 0
    assert seen == [("wrist", "front"), ("wrist", "front")]

    class Still(Camera):  # fresh frames, but the board never moves
        def frame_receipt(self, camera, *, previous=None, max_age_s):
            receipt = super().frame_receipt(camera, previous=previous, max_age_s=max_age_s)
            receipt["image"] = np.full((480, 640, 3), 5, np.uint8)
            return receipt

    state[0] = 0
    assert cb.capture_intrinsics_frames(Still(), "top", tmp_path / "still", want=25, timeout_s=0.2, every_s=0,
                                        log=lambda _: None) == 1


def test_offline_intrinsics_cli_preserves_result_and_records_rejected_input(tmp_path):
    frames = tmp_path / "frames"
    frames.mkdir()
    output = tmp_path / "intrinsics.json"
    args = ["intrinsics-from-frames", str(frames), "--camera", "top", "--scale-bar-mm", "51", "--out", str(output)]
    assert cb.main(args) == 1
    rejected = json.loads(output.read_text())
    assert rejected["accepted"] is False
    assert "scale bar" in rejected["checks"]["reasons"][0]
    assert cb.main(args) == 1
    assert json.loads(output.read_text()) == rejected

    bad = frames / "view-000.png"
    cv2.imwrite(str(bad), np.zeros((16, 16, 3), np.uint8))
    other = tmp_path / "bad-receipt.json"
    assert cb.main(["intrinsics-from-frames", str(frames), "--camera", "top", "--scale-bar-mm", "50", "--out", str(other)]) == 1
    assert "source receipt" in json.loads(other.read_text())["checks"]["reasons"][0]


def test_solve_cli_holds_before_writing_authoritative_hand_eye(tmp_path):
    args = ["solve", str(tmp_path), "--intrinsics", str(tmp_path / "missing.json"),
            "--board-z", "0.0", "--config", str(tmp_path / "missing-config.json")]
    with pytest.raises(SystemExit, match="FK authority unavailable"):
        cb.main(args)
    assert not (tmp_path / "hand-eye.json").exists()


def test_hand_eye_views_require_same_camera_and_untampered_receipts(tmp_path):
    import cell_board_capture as capture

    binding = BINDING | {"viewer_label": "front", "role": "wrist"}
    for i in range(12):
        data = f"jpeg-{i}".encode()
        (tmp_path / f"view-{i}.jpg").write_bytes(data)
        (tmp_path / f"view-{i}.json").write_text(json.dumps({
            "camera": "wrist", "device_binding": binding,
            "source_seq": i + 10, "source_stamp": 100.0 + i,
            "sha256": hashlib.sha256(data).hexdigest(), "t": [0.1, 0.2, 0.3],
            "R": np.eye(3).tolist(), "motion_evidence": {
                "checked_owner": True, "settled": True, "goto_reported_at": 98.0 + i,
                "state_before_at": 99.0 + i, "state_after_at": 100.5 + i,
                "state_before": [0] * 5, "state_after": [0] * 5}}))
    capture.verify_hand_eye_views(tmp_path, binding)
    row = json.loads((tmp_path / "view-1.json").read_text())
    row["source_stamp"] = float("nan")
    (tmp_path / "view-1.json").write_text(json.dumps(row))
    with pytest.raises(ValueError, match="CALIBRATION_REQUIRED"):
        capture.verify_hand_eye_views(tmp_path, binding)
    row["source_stamp"] = 101.0
    row["motion_evidence"]["state_after"][0] = 1
    (tmp_path / "view-1.json").write_text(json.dumps(row))
    with pytest.raises(ValueError, match="CALIBRATION_REQUIRED"):
        capture.verify_hand_eye_views(tmp_path, binding)
    row["motion_evidence"]["state_after"][0] = 0
    (tmp_path / "view-1.json").write_text(json.dumps(row))
    with pytest.raises(ValueError, match="CALIBRATION_REQUIRED"):
        capture.verify_hand_eye_views(tmp_path, binding | {"focus_controls": {"focus_absolute": 16}})
    (tmp_path / "view-1.jpg").write_bytes(b"modified")
    with pytest.raises(ValueError, match="CALIBRATION_REQUIRED"):
        capture.verify_hand_eye_views(tmp_path, binding)
    (tmp_path / "view-1.jpg").unlink()
    (tmp_path / "view-1.json").unlink()
    row = json.loads((tmp_path / "view-0.json").read_text())
    row.pop("device_binding")
    (tmp_path / "view-0.json").write_text(json.dumps(row))
    with pytest.raises(ValueError, match="CALIBRATION_REQUIRED"):
        capture.verify_hand_eye_views(tmp_path, binding)


def test_hand_eye_capture_is_held_before_any_owner_command(tmp_path):
    class Cell:
        def act(self, command):
            raise AssertionError(f"unexpected owner command: {command}")

    with pytest.raises(RuntimeError, match="supervised checked"):
        cb.capture(Cell(), {}, (0, 0), [0.2], [0], 0.02, tmp_path / "views")
    with pytest.raises(SystemExit, match="supervised checked"):
        cb.main(["capture", "--config", str(tmp_path / "missing.json"), "--out", str(tmp_path / "out"),
                 "--centre", "0", "0", "--yaws", "0"])


def test_live_intrinsics_refuses_wrong_print_scale_before_camera_access(tmp_path):
    out = tmp_path / "intrinsics.json"
    assert cb.main(["intrinsics", "--config", str(tmp_path / "unread.json"), "--camera", "top",
                    "--out", str(out), "--scale-bar-mm", "51"]) == 1
    assert json.loads(out.read_text())["accepted"] is False
