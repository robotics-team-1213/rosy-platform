#!/usr/bin/env python3
"""Camera geometry from a checkerboard: intrinsics, the wrist camera on the gripper (hand-eye), the top camera in the
arm frame, and pixel -> arm point on a surface of known height. Depth is explicit, not folded into a 2-D map.

Why (2026-10-29): the top-camera homography was 1-2 cm off near the board edge, and the oblique wrist camera has no
fixed relation between its image axes and the floor (a 19 mm move along the closing axis showed up 'across'); a
reference pixel and a probed Jacobian were workarounds for not knowing the cameras' geometry. With K, distortion and
each camera's pose, any wrist or top pixel becomes a ray, and its intersection with surface_z is an arm-frame point.

Procedure (arm only, after a person lays a printed checkerboard flat on the floor once):
  1. grid of hover poses over the board (x, y, height, yaw); at each, FK pose + wrist frame  -> `views`
  2. calibrate_intrinsics(frames of the board tilted by hand in front of the camera)           -> K, dist (wrist)
     (gripper-down hovers all see the board plane at one angle: they cannot give the focal length)
  3. hand_eye_top_down(FK poses, board poses, board_z)  (capture -> solve)                     -> camera in gripper
  4. board_in_base(...)  (from any view)                                                         -> board in arm frame
  5. top camera: solvePnP on its own view of the same board                                     -> top camera in arm
  6. pixel_to_plane(pixel, K, dist, camera pose in arm frame, surface_z)                         -> arm point
"""
from __future__ import annotations

import json
import math
import subprocess

import numpy as np
from cell_board_capture import capture_intrinsics_frames
from cell_camera_binding import live_camera_binding, runtime_viewer_state, viewer_label_from_url, viewer_session


def board_points(cols: int, rows: int, square_m: float) -> np.ndarray:
    """Inner-corner coordinates on the board plane (z = 0), metres, row-major as OpenCV returns them."""
    grid = np.zeros((rows * cols, 3), np.float32)
    grid[:, :2] = np.mgrid[0:cols, 0:rows].T.reshape(-1, 2) * square_m
    return grid


def find_corners(img, cols: int, rows: int):
    import cv2

    gray = img if img.ndim == 2 else cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    ok, corners = cv2.findChessboardCorners(gray, (cols, rows), cv2.CALIB_CB_ADAPTIVE_THRESH | cv2.CALIB_CB_NORMALIZE_IMAGE)
    if not ok:
        return None
    return cv2.cornerSubPix(gray, corners, (5, 5), (-1, -1), (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 1e-3))


def calibrate_intrinsics(corner_sets: list, board: np.ndarray, size: tuple, extra_flags: int = 0) -> dict:
    import cv2

    objects = board if isinstance(board, list) else [board] * len(corner_sets)  # ChArUco: each view its own corners
    rms, K, dist, _, _ = cv2.calibrateCamera(objects, corner_sets, size, None, None, flags=cv2.CALIB_FIX_K3 | extra_flags)
    return {"K": K, "dist": dist, "rms_px": float(rms)}


def board_pose(corners, board: np.ndarray, K, dist):
    """(R, t) of the board in the camera frame."""
    import cv2

    ok, rvec, tvec = cv2.solvePnP(board, corners, K, dist)
    if not ok:
        return None
    return cv2.Rodrigues(rvec)[0], tvec.reshape(3)


def hand_eye(gripper_in_base: list, board_in_camera: list) -> tuple:
    """The camera's pose in the gripper frame from N views (cv2.calibrateHandEye, Tsai). Inputs are (R, t) pairs.
    The views must tilt the wrist (joint 4), not only yaw: with one shared rotation axis the camera offset along that
    axis is unobservable. Every view must show the whole board in front of the camera, or solvePnP returns a mirror."""
    import cv2

    col = lambda v: np.asarray(v, np.float64).reshape(3, 1)
    R, t = cv2.calibrateHandEye([np.asarray(g[0], np.float64) for g in gripper_in_base], [col(g[1]) for g in gripper_in_base],
                                [np.asarray(b[0], np.float64) for b in board_in_camera], [col(b[1]) for b in board_in_camera],
                                method=cv2.CALIB_HAND_EYE_TSAI)
    return R, t.reshape(3)


def compose(a: tuple, b: tuple) -> tuple:
    return a[0] @ b[0], a[0] @ b[1] + a[1]


def pixel_to_plane(pixel, K, dist, camera_in_base: tuple, plane_z: float):
    """The arm-frame point where the pixel's ray meets the plane z = plane_z (None if parallel or behind)."""
    import cv2

    if not np.any(dist):
        rx = (float(pixel[0]) - float(K[0][2])) / float(K[0][0])
        ry = (float(pixel[1]) - float(K[1][2])) / float(K[1][1])
    else:
        ray = cv2.undistortPoints(np.array([[pixel]], np.float64), K, dist).reshape(2)
        rx, ry = float(ray[0]), float(ray[1])
    R, t = camera_in_base
    dx = float(R[0][0]) * rx + float(R[0][1]) * ry + float(R[0][2])
    dy = float(R[1][0]) * rx + float(R[1][1]) * ry + float(R[1][2])
    dz = float(R[2][0]) * rx + float(R[2][1]) * ry + float(R[2][2])
    if abs(dz) < 1e-9:
        return None
    s = (float(plane_z) - float(t[2])) / dz
    return None if s <= 0 else np.array([float(t[0]) + s * dx, float(t[1]) + s * dy, float(t[2]) + s * dz])


# --- ChArUco and printable pages (2026-10-29) ------------------------------------------------------------------------
# A ChArUco board names visible corners even in partial views.
PX_PER_MM = 12  # 304.8 dpi; print the PDF at 100 % (no fit-to-page), then check the 50 mm bar with a ruler
A4_MM = (210, 297)


PRINTED = (7, 10, 0.020, 0.015)  # the Fleet print sheet's board (cell_print_sheets.charuco_pdf, D-933 1)


def charuco_board(cols: int = PRINTED[0], rows: int = PRINTED[1],
                  square_m: float = PRINTED[2], marker_m: float = PRINTED[3]):
    import cv2

    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    create = getattr(cv2.aruco, "CharucoBoard_create", None)
    return create(cols, rows, square_m, marker_m, dictionary) if create else cv2.aruco.CharucoBoard((cols, rows), square_m, marker_m, dictionary)


def charuco_image(size: tuple, board=None) -> np.ndarray:
    """Render the calibration board with either OpenCV's 4.6 or 4.7+ API."""
    board = board or charuco_board()
    draw = getattr(board, "generateImage", None) or board.draw
    return draw(size, marginSize=0, borderBits=1)


def find_charuco(img, board, min_corners: int = 6):
    """(board points, image points) of the corners seen, or None under min_corners."""
    import cv2

    gray = img if img.ndim == 2 else cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    if hasattr(cv2.aruco, "CharucoDetector"):
        corners, ids, _, _ = cv2.aruco.CharucoDetector(board).detectBoard(gray)
    else:
        markers, marker_ids, _ = cv2.aruco.detectMarkers(gray, board.dictionary)
        if marker_ids is None:
            return None
        _, corners, ids = cv2.aruco.interpolateCornersCharuco(markers, marker_ids, gray, board)
    if ids is None or len(ids) < min_corners:
        return None
    if hasattr(board, "matchImagePoints"):
        obj, pix = board.matchImagePoints(corners, ids)
    else:
        obj, pix = board.chessboardCorners[ids.reshape(-1)], corners
    return obj.reshape(-1, 3).astype(np.float32), pix.reshape(-1, 1, 2).astype(np.float32)


def page(kind: str) -> np.ndarray:
    """An A4 page (white, PX_PER_MM) with the board, a 50 mm scale bar and its label."""
    import cv2

    W, H = A4_MM[0] * PX_PER_MM, A4_MM[1] * PX_PER_MM
    img = np.full((H, W), 255, np.uint8)
    if kind == "checker":
        cols, rows, sq = 8, 6, 15  # 7 x 5 inner corners, 15 mm squares (wrist camera)
        q = sq * PX_PER_MM
        board = ((np.add.outer(np.arange(rows * q) // q, np.arange(cols * q) // q) % 2) * 255).astype(np.uint8)
        label = "checkerboard 7x5 inner corners, 15 mm squares"
    else:
        cols, rows, sq = 7, 10, 20
        board = charuco_image((cols * sq * PX_PER_MM, rows * sq * PX_PER_MM))
        label = "ChArUco 7x10 squares, 20 mm, markers 15 mm, DICT_4X4_50"
    y, x = 30 * PX_PER_MM, (W - board.shape[1]) // 2
    img[y:y + board.shape[0], x:x + board.shape[1]] = board
    yb = y + board.shape[0] + 20 * PX_PER_MM
    img[yb:yb + 2 * PX_PER_MM, x:x + 50 * PX_PER_MM] = 0
    cv2.putText(img, "50 mm", (x, yb + 9 * PX_PER_MM), cv2.FONT_HERSHEY_SIMPLEX, 2.4, 0, 4)
    cv2.putText(img, label, (x, yb + 18 * PX_PER_MM), cv2.FONT_HERSHEY_SIMPLEX, 1.6, 0, 3)
    cv2.putText(img, "print at 100% (actual size), matte paper, glue flat", (x, yb + 25 * PX_PER_MM), cv2.FONT_HERSHEY_SIMPLEX, 1.6, 0, 3)
    return img


def hand_eye_top_down(gripper_in_base: list, board_in_camera: list, board_z: float, same_deg: float = 1.0) -> dict:
    """Hand-eye for an arm that only reaches gripper-down poses (OMX IK is top-down): every rotation shares the
    vertical axis, so calibrateHandEye cannot see the camera's turn about it nor its offset along it. Instead:
      rotation    - views at the same yaw differ only by translation: R_x (c_i - c_j) = G^T (g_j - g_i)  (Kabsch)
      translation - the board origin p = g_i + G_i (R_x c_i + t_x) is fixed; with p_z = board_z it is linear.
    Needs translations in two directions at one yaw (x/y/z moves) and two or more yaws."""
    u, v = [], []
    for i, (Gi, gi) in enumerate(gripper_in_base):
        for j in range(i + 1, len(gripper_in_base)):
            Gj, gj = gripper_in_base[j]
            if np.degrees(np.arccos(np.clip((np.trace(Gi.T @ Gj) - 1) / 2, -1, 1))) <= same_deg:
                u.append(board_in_camera[i][1] - board_in_camera[j][1])
                v.append(Gi.T @ (gj - gi))
    if len(u) < 2 or np.linalg.matrix_rank(np.array(u), tol=1e-3) < 2:
        raise ValueError("need translations in two directions at one yaw")
    U, _, Vt = np.linalg.svd(np.array(u).T @ np.array(v))
    R = Vt.T @ np.diag([1, 1, np.linalg.det(Vt.T @ U.T)]) @ U.T
    rows, rhs = [], []
    for (G, g), (_, c) in zip(gripper_in_base, board_in_camera):  # G t_x - p = -(g + G R c)
        rows.append(np.hstack([G, -np.eye(3)]))
        rhs.append(-(g + G @ R @ c))
    rows.append(np.array([[0, 0, 0, 0, 0, 1.0]]))
    rhs.append(np.array([board_z]))
    x, *_ = np.linalg.lstsq(np.vstack(rows), np.hstack(rhs), rcond=None)
    resid = np.vstack(rows) @ x - np.hstack(rhs)
    return {"R": R, "t": x[:3], "board_origin": x[3:], "rms_mm": float(1000 * np.sqrt(np.mean(resid ** 2)))}


def capture(cell, config: dict, centre, z_list, yaw_list, step_m: float, out, camera: str = "wrist", log=print) -> int:
    from cell_board_capture import capture_hand_eye
    return capture_hand_eye(cell, config, centre, z_list, yaw_list, step_m, out, camera, log)


def solve(folder, K, dist, board_z: float, board=None, *, binding=None) -> dict:
    """hand_eye_top_down over the captured views whose ChArUco corners give a pose."""
    import cv2

    from cell_board_capture import verify_hand_eye_views
    verify_hand_eye_views(folder, binding)
    board = board or charuco_board()
    G, B = [], []
    for meta in sorted(folder.glob("view-*.json")):
        found = find_charuco(cv2.imread(str(meta.with_suffix(".jpg"))), board)
        pose = found and board_pose(found[1], found[0], K, dist)
        if pose:
            m = json.loads(meta.read_text())
            G.append((np.array(m["R"]), np.array(m["t"])))
            B.append(pose)
    out = hand_eye_top_down(G, B, board_z)
    return {"views": len(G), "R": out["R"].tolist(), "t": out["t"].tolist(), "rms_mm": round(out["rms_mm"], 2)}


def grab_intrinsics(cell, camera: str, want: int, board=None, every_s: float = 1.5, min_corners: int = 12, log=print) -> dict:
    """K and dist from `want` frames of the board held by a person at different tilts (only the camera viewer is used)."""
    import time

    board = board or charuco_board()
    objs, pixs, size = [], [], None
    while len(objs) < want:
        img = cell.frame(camera)
        found = find_charuco(img, board, min_corners)
        if found:
            objs.append(found[0])
            pixs.append(found[1])
            size = img.shape[1], img.shape[0]
        log({"intrinsics_frames": len(objs), "of": want})
        time.sleep(every_s)
    out = calibrate_intrinsics(pixs, objs, size)
    return {"camera": camera, "size": size, "K": out["K"].tolist(), "dist": out["dist"].ravel().tolist(), "rms_px": round(out["rms_px"], 3)}


def main(argv=None):
    import argparse
    from pathlib import Path

    import cv2

    ap = argparse.ArgumentParser(description="checkerboard camera calibration for arm S")
    sub = ap.add_subparsers(dest="verb", required=True)
    sub.add_parser("pages").add_argument("out", type=Path)
    for verb in ("intrinsics", "capture"):
        s = sub.add_parser(verb)
        s.add_argument("--config", required=True, type=Path)
        s.add_argument("--camera", default="wrist")
        s.add_argument("--out", required=True, type=Path)
    sub.choices["intrinsics"].add_argument("--frames", type=int, default=60,
                                           help="most views to keep; capture stops at this count or timeout")
    sub.choices["intrinsics"].add_argument("--scale-bar-mm", type=float, required=True)
    sub.choices["intrinsics"].add_argument("--timeout-s", type=float, default=180)
    offline = sub.add_parser("intrinsics-from-frames", help="fit saved RGB frames without moving an arm")
    offline.add_argument("dir", type=Path)
    offline.add_argument("--camera", required=True)
    offline.add_argument("--scale-bar-mm", type=float, required=True, help="measured length of the printed 50 mm bar")
    offline.add_argument("--out", required=True, type=Path)
    cap = sub.choices["capture"]
    cap.add_argument("--centre", nargs=2, type=float, required=True, help="TCP hover centre (m) with the board in the wrist view")
    cap.add_argument("--z", nargs="+", type=float, default=[0.20, 0.23])
    cap.add_argument("--yaws", nargs="+", type=float, required=True, help="degrees, two or more")
    cap.add_argument("--step", type=float, default=0.02)
    sol = sub.add_parser("solve")
    sol.add_argument("dir", type=Path)
    sol.add_argument("--intrinsics", required=True, type=Path)
    sol.add_argument("--board-z", required=True, type=float, help="board surface height in the arm frame (m)")
    sol.add_argument("--config", required=True, type=Path, help="cell config with the wrist viewer URL")
    args = ap.parse_args(argv)

    def save_intrinsics(result):
        try:
            with args.out.open("x", encoding="utf-8") as output:
                json.dump(result, output, indent=1, allow_nan=False)
        except FileExistsError:
            print(json.dumps({"accepted": False, "checks": {"reasons": ["result_file_exists"]}}))
            return 1
        print(json.dumps({"accepted": result["accepted"], "checks": result["checks"]}))
        return 0 if result["accepted"] else 1

    def fit_intrinsics(folder):
        try:
            return intrinsics_from_frames(folder, args.camera, args.scale_bar_mm)
        except (ValueError, OSError) as exc:
            return {"camera": args.camera, "accepted": False, "checks": {"reasons": [str(exc)]}}

    if args.verb == "pages":
        for kind in ("checker", "charuco"):
            cv2.imwrite(str(args.out / f"arm-s-{kind}-a4.png"), page(kind))
        return 0
    if args.verb == "solve":
        raise SystemExit("CALIBRATION_REQUIRED: checked hand-eye capture and FK authority unavailable")
    if args.verb == "intrinsics-from-frames":
        if args.out.exists():
            return save_intrinsics({"accepted": False, "checks": {"reasons": ["result_file_exists"]}})
        return save_intrinsics(fit_intrinsics(args.dir))
    if args.verb == "intrinsics" and (not math.isfinite(args.scale_bar_mm) or not 49.5 <= args.scale_bar_mm <= 50.5):
        return save_intrinsics({"camera": args.camera, "accepted": False,
                                "checks": {"reasons": ["printed 50 mm scale bar must be measured within 0.5 mm"]}})
    if args.verb == "intrinsics" and args.out.exists():
        return save_intrinsics({"accepted": False, "checks": {"reasons": ["result_file_exists"]}})
    if args.verb == "capture":
        raise SystemExit("CALIBRATION_REQUIRED: supervised checked hand-eye capture unavailable")
    import cell_pipeline as cp

    config = json.loads(args.config.read_text())
    cell = cp.FifoCell(Path(config["io"]).expanduser(), config["cameras"])
    if args.verb == "intrinsics":
        folder = args.out.parent / f"{args.out.stem}-frames"
        try:
            captured = capture_intrinsics_frames(cell, args.camera, folder, args.frames, args.timeout_s)
        except (OSError, RuntimeError, SystemExit, ValueError, subprocess.SubprocessError):
            return save_intrinsics({"camera": args.camera, "accepted": False,
                                    "checks": {"reasons": ["camera_identity_or_capture_unavailable"]}})
        result = fit_intrinsics(folder)
        result["checks"]["captured_views"] = captured
        return save_intrinsics(result)
    config["plan"] = json.loads(Path(config["plan_path"]).expanduser().read_text())
    if not cell.act("state").get("ok"):
        raise SystemExit("start the chunk session first: no chunk_runner answers")
    print(json.dumps({"views": capture(cell, config, args.centre, args.z, args.yaws, args.step, args.out, args.camera)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


from cell_intrinsics_frames import (  # noqa: E402,F401  (re-exported; the module imports this one, so it comes last)
    CELLS,
    board_view,
    board_scale,
    view_coverage,
    coverage_reasons,
    board_spec,
    intrinsics_from_frames,
    board_observations,
    _fit,
    _same_look,
)
