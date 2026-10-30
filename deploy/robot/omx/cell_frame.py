#!/usr/bin/env python3
"""The top camera's model in the arm frame, kept true by printed markers (D-933): no per-surface maps.

One camera model per fixed camera: K, distortion and the camera's pose in the arm base frame. The pose comes once
from the gripper marker at forward-kinematics points; the same view then learns where every base and surface marker
of this arm slot lies (its four corners, in the arm frame, on the touched height of its plane). After that:
  - every frame re-solves the camera pose from the base markers (a camera bumped by 7 deg needs no new map),
  - a surface with two or more of its markers in view gives its motion since setup (the Pinky that drifted 45 px),
  - a pixel is a ray; where it meets the plane at the box's height (moved with its surface) is the arm point.
Markers out of view fall back to the setup pose and to the existing maps; the caller refuses beyond that.

  rosy.omx-cell-calibration.v1 gains "cameras": {"top": {"K", "dist", "size", "slot", "camera_in_base": {"R", "t"},
      "rms_px", "markers": {"<id>": [[x, y, z] x 4]}, "base": [ids], "surfaces": {"<site>": [ids]}, "measured"}}

  cell_frame.py learn --config C --intrinsics I.json --views DIR --slot 1      (views from cell_checkerboard capture
                                                                               --camera top: view-N.png + FK json)
  cell_frame.py check --config C FRAME.jpg                                     camera drift, each surface's motion
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cell_calibration as cal  # noqa: E402
import cell_marks  # noqa: E402
from cell_checkerboard import compose, pixel_to_plane  # noqa: E402

MIN_SURFACE_MARKERS = 2  # one marker's four corners leave the tilt loose and can flip the plane (D-933 4)


def slot_ids(slot: int) -> dict:
    """The same table as the print sheets' arm_ids (D-933 8): gripper, 2 base, 3 surfaces of 4."""
    first = 35 + 15 * (int(slot) - 1)
    return {"gripper": first, "base": [first + 1, first + 2],
            "surfaces": [list(range(first + 3 + 4 * k, first + 7 + 4 * k)) for k in range(3)]}


def corners(img) -> dict:
    """{id: 4x2 corner pixels} of every DICT_4X4_100 marker in the frame, OpenCV's corner order."""
    import cv2

    grey = img if img.ndim == 2 else cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    found, ids, _ = cv2.aruco.ArucoDetector(cell_marks._dictionary(), cv2.aruco.DetectorParameters()).detectMarkers(grey)
    return {} if ids is None else {int(i): c.reshape(4, 2).astype(np.float64) for c, i in zip(found, ids.flatten())}


def inverse(pose: tuple) -> tuple:
    return pose[0].T, -pose[0].T @ pose[1]


def solve(obj, pix, K, dist) -> tuple:
    """(pose of the object frame in the camera, reprojection rms px) for 3-D points and their pixels."""
    import cv2

    obj, pix = np.asarray(obj, np.float64).reshape(-1, 3), np.asarray(pix, np.float64).reshape(-1, 2)
    flag = getattr(cv2, "SOLVEPNP_SQPNP", cv2.SOLVEPNP_ITERATIVE)
    ok, rvec, tvec = cv2.solvePnP(obj, pix, K, dist, flags=flag)
    if not ok:
        return None, None
    ok, rvec, tvec = cv2.solvePnP(obj, pix, K, dist, rvec, tvec, useExtrinsicGuess=True, flags=cv2.SOLVEPNP_ITERATIVE)
    back, _ = cv2.projectPoints(obj, rvec, tvec, K, dist)
    return (cv2.Rodrigues(rvec)[0], tvec.reshape(3)), float(np.sqrt(np.mean(np.sum((back.reshape(-1, 2) - pix) ** 2, 1))))


def project(point, K, dist, camera_in_base: tuple):
    import cv2

    R, t = inverse(camera_in_base)
    p, _ = cv2.projectPoints(np.asarray(point, np.float64).reshape(1, 3), cv2.Rodrigues(R)[0], t, K, dist)
    return tuple(float(v) for v in p.reshape(2))


def seed(views, K, dist, offset_m) -> tuple:
    """Camera in the arm frame from the gripper marker seen at FK poses: views are (R, t, pixel) with the marker's
    centre at t + R offset_m (the marker measured from the TCP in the gripper frame, by ruler). 6+ views at mixed
    heights; returns (camera_in_base, rms px)."""
    if len(views) < 6:
        raise ValueError(f"need 6 or more gripper views, got {len(views)}")
    pts = [np.asarray(t) + np.asarray(R) @ np.asarray(offset_m) for R, t, _ in views]
    pose, rms = solve(pts, [v[2] for v in views], K, dist)
    if pose is None:
        raise ValueError("solvePnP found no camera pose from the gripper views")
    return inverse(pose), rms


def learn(seen: dict, K, dist, camera_in_base: tuple, slot: int, z_m: dict, surfaces: list) -> dict:
    """The camera record: every base and surface marker of `slot` in view, lifted onto its plane's touched height
    (z_m["base"], z_m[<site>]). `surfaces` names the slot's surfaces 1-3 in order (None for an unused one)."""
    ids = slot_ids(slot)
    planes = {i: "base" for i in ids["base"]}
    names = {}
    for name, block in zip(surfaces, ids["surfaces"]):
        if name:
            names[name] = block
            planes.update({i: name for i in block})
    markers = {}
    for i, plane in planes.items():
        if i in seen:
            lifted = [pixel_to_plane(c, K, dist, camera_in_base, float(z_m[plane])) for c in seen[i]]
            if all(p is not None for p in lifted):
                markers[str(i)] = np.round(lifted, 5).tolist()
    if not any(str(i) in markers for i in ids["base"]):
        raise ValueError(f"no base marker of slot {slot} ({ids['base']}) in view: the camera pose cannot be re-solved later")
    return {"K": np.asarray(K).tolist(), "dist": np.asarray(dist).ravel().tolist(), "slot": int(slot),
            "camera_in_base": {"R": np.asarray(camera_in_base[0]).tolist(), "t": np.asarray(camera_in_base[1]).tolist()},
            "markers": markers, "base": ids["base"], "surfaces": names,
            "measured": datetime.now(timezone.utc).isoformat()}


def _model(record: dict):
    return np.array(record["K"]), np.array(record["dist"])


def _pose(p: dict) -> tuple:
    return np.array(p["R"]), np.array(p["t"])


def _known(record: dict, seen: dict, ids) -> tuple:
    use = [i for i in ids if str(i) in record["markers"] and i in seen]
    return use, [p for i in use for p in record["markers"][str(i)]], [p for i in use for p in seen[i]]


def camera_pose(record: dict, seen: dict):
    """(camera_in_base, rms px) from the base markers in this frame, or (None, None) when none is seen."""
    use, obj, pix = _known(record, seen, record["base"])
    if not use:
        return None, None
    pose, rms = solve(obj, pix, *_model(record))
    return (inverse(pose), rms) if pose else (None, None)


def surface_motion(record: dict, seen: dict, site: str, camera_in_base: tuple):
    """The rigid motion (R, t) of `site` since setup, in the arm frame (identity when it has not moved), or None
    with fewer than MIN_SURFACE_MARKERS of its markers in view."""
    use, obj, pix = _known(record, seen, record["surfaces"].get(site, []))
    if len(use) < MIN_SURFACE_MARKERS:
        return None
    pose, _ = solve(obj, pix, *_model(record))  # the setup arm frame as seen now
    return None if pose is None else compose(camera_in_base, pose)


def refresh(record: dict, img) -> dict:
    """This frame's camera pose and every surface's motion, kept in record["now"] for to_arm/to_pixel."""
    return update(record, corners(img))


def update(record: dict, seen: dict) -> dict:
    camera, rms = camera_pose(record, seen)
    now = {"base_seen": camera is not None, "rms_px": None if rms is None else round(rms, 2), "motion": {}}
    camera = camera or _pose(record["camera_in_base"])
    now["camera_in_base"] = camera
    for site in record["surfaces"]:
        motion = surface_motion(record, seen, site, camera)
        if motion is not None:
            now["motion"][site] = motion
    record["now"] = now
    return now


def _current(record: dict, site: str) -> tuple:
    now = record.get("now") or {}
    camera = now.get("camera_in_base") or _pose(record["camera_in_base"])
    return camera, (now.get("motion") or {}).get(site, (np.eye(3), np.zeros(3)))


def to_arm(record: dict, site: str, pixel, z: float):
    """The arm point (x, y, z) where `pixel` meets the plane at height z of `site` as it lies now, or None."""
    camera, motion = _current(record, site)
    back = inverse(motion)  # work in the surface's setup frame, where its plane is z = const
    p = pixel_to_plane(pixel, *_model(record), compose(back, camera), z)
    return None if p is None else motion[0] @ p + motion[1]


def yaw_sign(record: dict, site: str, pixel, z: float) -> int:
    """+1 when a turn in the image is the same turn about the arm's z axis, -1 when the view mirrors it."""
    o, ex, ey = (to_arm(record, site, (pixel[0] + du, pixel[1] + dv), z)[:2] for du, dv in ((0, 0), (1, 0), (0, 1)))
    return 1 if float(np.cross(ex - o, ey - o)) > 0 else -1


def to_pixel(record: dict, point, z: float):
    """Where the arm point (x, y) at height z shows in this camera now."""
    camera, _ = _current(record, None)
    return project([point[0], point[1], z], *_model(record), camera)


def drift(record: dict) -> dict:
    """How far the camera and each surface moved since setup: degrees and millimetres (for preflight and check)."""
    now = record.get("now") or {}
    out = {}
    if now.get("base_seen"):
        a, b = _pose(record["camera_in_base"]), now["camera_in_base"]
        out["camera"] = {"deg": _angle(a[0].T @ b[0]), "mm": round(1000 * float(np.linalg.norm(a[1] - b[1])), 1)}
    for site, (R, t) in (now.get("motion") or {}).items():
        out[site] = {"deg": _angle(R), "mm": round(1000 * float(np.linalg.norm(t)), 1)}
    return out


def _angle(R) -> float:
    return round(float(np.degrees(np.arccos(np.clip((np.trace(R) - 1) / 2, -1, 1)))), 2)


def save(path: Path, camera: str, record: dict) -> None:
    data = cal.load(path) if Path(path).exists() else {"schema": cal.SCHEMA, "sites": {}}
    data.setdefault("cameras", {})[camera] = {k: v for k, v in record.items() if k != "now"}
    tmp = Path(path).with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1))
    tmp.replace(path)


def main(argv=None):
    import cv2

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="verb", required=True)
    s = sub.add_parser("learn")
    s.add_argument("--config", required=True, type=Path)
    s.add_argument("--intrinsics", required=True, type=Path, help="cell_checkerboard intrinsics --camera top output")
    s.add_argument("--views", required=True, type=Path, help="cell_checkerboard capture --camera top folder")
    c = sub.add_parser("check")
    c.add_argument("--config", required=True, type=Path)
    c.add_argument("frame", type=Path)
    args = ap.parse_args(argv)
    config = json.loads(args.config.read_text())
    spec = config["markers"]  # {"slot", "gripper_offset_m", "z_m": {"base", <site>...}, "surfaces": [site|null x 3]}
    path = Path(config["calibration_path"]).expanduser()
    if args.verb == "check":
        record = cal.load(path)["cameras"]["top"]
        refresh(record, cv2.imread(str(args.frame)))
        print(json.dumps({"base_seen": record["now"]["base_seen"], "rms_px": record["now"]["rms_px"], "drift": drift(record)}))
        return 0
    intr = json.loads(args.intrinsics.read_text())
    K, dist = np.array(intr["K"]), np.array(intr["dist"])
    gripper, views, last = slot_ids(spec["slot"])["gripper"], [], None
    for meta in sorted(args.views.glob("view-*.json")):
        img = cv2.imread(str(meta.with_suffix(".png")))
        seen = corners(img)
        if gripper in seen:
            m = json.loads(meta.read_text())
            views.append((np.array(m["R"]), np.array(m["t"]), seen[gripper].mean(0)))
            last = seen
    camera, rms = seed(views, K, dist, spec["gripper_offset_m"])
    record = learn(last, K, dist, camera, spec["slot"], spec["z_m"], spec["surfaces"])
    record.update(size=intr.get("size"), rms_px=round(rms, 2), views=len(views))
    save(path, "top", record)
    print(json.dumps({"views": len(views), "rms_px": record["rms_px"], "markers": sorted(record["markers"], key=int)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
