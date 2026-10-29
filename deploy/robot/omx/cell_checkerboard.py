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

import numpy as np


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


def calibrate_intrinsics(corner_sets: list, board: np.ndarray, size: tuple) -> dict:
    import cv2

    objects = board if isinstance(board, list) else [board] * len(corner_sets)  # ChArUco: each view its own corners
    rms, K, dist, _, _ = cv2.calibrateCamera(objects, corner_sets, size, None, None)
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

    ray = cv2.undistortPoints(np.array([[pixel]], np.float64), K, dist).reshape(2)
    d_cam = np.array([ray[0], ray[1], 1.0])
    R, t = camera_in_base
    d = R @ d_cam
    if abs(d[2]) < 1e-9:
        return None
    s = (plane_z - t[2]) / d[2]
    return None if s <= 0 else t + s * d


# --- ChArUco and printable pages (2026-10-29) ------------------------------------------------------------------------
# A ChArUco board (ArUco markers in the white squares) names every corner, so a view that shows only part of the board
# still gives a pose and the corners cannot be matched mirrored - the two plain-board failure modes. One 25 mm board
# serves the wrist camera (partial views at 0.2 m) and the top camera (whole board at 0.65 m).
PX_PER_MM = 12  # 304.8 dpi; print the PDF at 100 % (no fit-to-page), then check the 50 mm bar with a ruler
A4_MM = (210, 297)


def charuco_board(cols: int = 7, rows: int = 5, square_m: float = 0.025, marker_m: float = 0.018):
    import cv2

    return cv2.aruco.CharucoBoard((cols, rows), square_m, marker_m, cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50))


def find_charuco(img, board, min_corners: int = 6):
    """(board points, image points) of the corners seen, or None under min_corners."""
    import cv2

    gray = img if img.ndim == 2 else cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    corners, ids, _, _ = cv2.aruco.CharucoDetector(board).detectBoard(gray)
    if ids is None or len(ids) < min_corners:
        return None
    obj, pix = board.matchImagePoints(corners, ids)
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
        cols, rows, sq = 7, 5, 25
        board = charuco_board().generateImage((cols * sq * PX_PER_MM, rows * sq * PX_PER_MM), marginSize=0, borderBits=1)
        label = "ChArUco 7x5 squares, 25 mm, markers 18 mm, DICT_4X4_50"
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
    """Hover the gripper (down) over a grid around `centre` at each height and yaw, save the wrist frame and the
    FK pose of the measured joints. Moves only through the planner's own libraries and the runner's goto."""
    import cv2

    import cell_pipeline as cp
    import grasp_planner as gp

    kin = gp.load_kinematics(None)[0]
    out.mkdir(parents=True, exist_ok=True)
    n = 0
    try:
        for yaw in yaw_list:
            for z in z_list:
                for dx, dy in ((0, 0), (step_m, 0), (0, step_m), (-step_m, 0), (0, -step_m)):
                    view = {"x": centre[0] + dx, "y": centre[1] + dy, "z": z, "yaw_deg": yaw}
                    try:
                        library = cp.write_library(config, view, view, out / f"lib-{n}.json")
                    except SystemExit as exc:  # out of reach here: the other hovers still count
                        log({"hover": view, "skipped": str(exc)[:120]})
                        continue
                    if not all(cell.act(c).get("ok") for c in (f"load {library}", "goto above_pick")):
                        log({"hover": view, "stopped": True})
                        return n
                    state = cell.act("state").get("state")
                    fk = kin.fk([gp.norm_to_rad(q) for q in state[:5]])
                    cv2.imwrite(str(out / f"view-{n}.png"), cell.frame(camera))
                    (out / f"view-{n}.json").write_text(json.dumps({"state": state, "R": fk.rotation, "t": [fk.x, fk.y, fk.z], "hover": view}))
                    n += 1
    finally:
        cell.act("park")
    return n


def solve(folder, K, dist, board_z: float, board=None) -> dict:
    """hand_eye_top_down over the captured views whose ChArUco corners give a pose."""
    import cv2

    board = board or charuco_board()
    G, B = [], []
    for meta in sorted(folder.glob("view-*.json")):
        found = find_charuco(cv2.imread(str(meta.with_suffix(".png"))), board)
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
    sub.choices["intrinsics"].add_argument("--frames", type=int, default=15)
    cap = sub.choices["capture"]
    cap.add_argument("--centre", nargs=2, type=float, required=True, help="TCP hover centre (m) with the board in the wrist view")
    cap.add_argument("--z", nargs="+", type=float, default=[0.20, 0.23])
    cap.add_argument("--yaws", nargs="+", type=float, required=True, help="degrees, two or more")
    cap.add_argument("--step", type=float, default=0.02)
    sol = sub.add_parser("solve")
    sol.add_argument("dir", type=Path)
    sol.add_argument("--intrinsics", required=True, type=Path)
    sol.add_argument("--board-z", required=True, type=float, help="board surface height in the arm frame (m)")
    args = ap.parse_args(argv)
    if args.verb == "pages":
        for kind in ("checker", "charuco"):
            cv2.imwrite(str(args.out / f"arm-s-{kind}-a4.png"), page(kind))
        return 0
    if args.verb == "solve":
        intr = json.loads(args.intrinsics.read_text())
        result = solve(args.dir, np.array(intr["K"]), np.array(intr["dist"]), args.board_z)
        (args.dir / "hand-eye.json").write_text(json.dumps(result, indent=1))
        print(json.dumps(result))
        return 0
    import cell_pipeline as cp

    config = json.loads(args.config.read_text())
    cell = cp.FifoCell(Path(config["io"]).expanduser(), config["cameras"])
    if args.verb == "intrinsics":
        result = grab_intrinsics(cell, args.camera, args.frames)
        args.out.write_text(json.dumps(result, indent=1))
        print(json.dumps(result))
        return 0
    config["plan"] = json.loads(Path(config["plan_path"]).expanduser().read_text())
    if not cell.act("state").get("ok"):
        raise SystemExit("start the chunk session first: no chunk_runner answers")
    print(json.dumps({"views": capture(cell, config, args.centre, args.z, args.yaws, args.step, args.out, args.camera)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
