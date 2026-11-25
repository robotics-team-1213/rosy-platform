#!/usr/bin/env python3
"""Where the top camera sits over the work board, from one D435 depth frame: height and tilt, no board, no arm.

Why (2026-11-13): the top camera gets bumped and must be re-placed fast, and an image-only re-registration cannot
split a bump into rotation and translation (1 deg and 10 mm both move the view about 10 px). The depth stream measures
the work board as a plane, and with the device's own factory calibration (depth K and depth -> colour transform,
`cell_device_intrinsics read`) that plane is known in the colour camera's frame: its distance is the camera's height
above the board and its normal the camera's tilt. On 2026-11-13 the board under the arms read 596.8 mm, and the
projected plane fell on the board's edges in the colour image.
Precision, measured on 30 frames that day (6 groups of 5): height +-0.3-0.6 mm, tilt only +-0.6 deg, since the depth
map itself steps between frames (about 1.2 deg once) and the board shares its height band with the ship deck and the
trays. So this settles height (a bump toward or away from the board, which the image cannot tell from a turn) and
only gross tilt; the reference-image shift (cell_preflight, about 0.1 deg per px) stays the tilt and yaw detector,
and markers (cell_frame) the full pose.

  cell_depth_pose.py measure --depth d.raw --factory factory.json --roi 40,150,620,470 --out pose.json
  cell_depth_pose.py compare pose.json reference.json        # exit 1 when the camera moved
  cell_depth_pose.py bump --image now.jpg --ref-image ref.jpg --pose pose.json --ref-pose reference.json
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

import cell_depth

TILT_MOVED_DEG = 2.0  # three times the measured +-0.6 deg; finer tilt is the image shift's job
HEIGHT_MOVED_MM = 6.0  # +-0.6 mm within a run, but D435 depth drifts up to ~1 % of 600 mm with warm-up across runs
MIN_SHARE, MAX_RMS_MM = 0.3, 3.0  # 2026-11-13 board: share 0.40, rms 2.2 mm


def _intrinsics_k(block: dict) -> np.ndarray:
    if "K" in block:
        return np.asarray(block["K"], float)
    return np.asarray([[block["fx"], 0.0, block["ppx"]], [0.0, block["fy"], block["ppy"]], [0.0, 0.0, 1.0]], float)


def calibration(factory: dict) -> tuple:
    """(depth K, colour K, R, t in mm) from canonical (`depth_to_colour`) or pyrealsense2 dump (`depth_to_color`) schema."""
    try:
        stream = factory.get("stream") if isinstance(factory.get("stream"), dict) else {}
        depth_K = np.asarray(factory["depth"]["K"], float) if "depth" in factory and "K" in factory["depth"] else _intrinsics_k(stream["depth"])
        colour_K = np.asarray(factory["K"], float) if "K" in factory else _intrinsics_k(stream["color"])
        if "depth_to_colour" in factory:
            ext = factory["depth_to_colour"]
            R_raw = np.asarray(ext["R"], float)
            R = R_raw.reshape(3, 3) if R_raw.size == 9 else R_raw
        else:
            ext = factory["depth_to_color"]
            R_raw = np.asarray(ext["R"], float)
            R = R_raw.reshape(3, 3).T if R_raw.size == 9 else R_raw
        t = np.asarray(ext["t_m"] if "t_m" in ext else ext["t"], float) * 1000.0
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("factory record lacks depth K or the depth -> colour transform") from exc
    if depth_K.shape != (3, 3) or colour_K.shape != (3, 3) or R.shape != (3, 3) or t.shape != (3,):
        raise ValueError("factory record has malformed depth calibration")
    if not (np.isfinite(depth_K).all() and np.isfinite(colour_K).all() and np.isfinite(R).all() and np.isfinite(t).all()):
        raise ValueError("factory record has non-finite depth calibration")
    if not np.allclose(R @ R.T, np.eye(3), atol=1e-4):
        raise ValueError("depth -> colour rotation is not a rotation")
    return depth_K, colour_K, R, t


def _colour_size(factory: dict, depth_shape: tuple[int, int]) -> tuple[int, int]:
    if isinstance(factory.get("size"), (list, tuple)) and len(factory["size"]) == 2:
        return int(factory["size"][0]), int(factory["size"][1])
    cs = (factory.get("stream") or {}).get("color") or {}
    if "width" in cs and "height" in cs:
        return int(cs["width"]), int(cs["height"])
    return int(depth_shape[1]), int(depth_shape[0])


def height_map_in_colour(depth_mm: np.ndarray, factory: dict, roi: tuple = (40, 150, 620, 470),
                         tol_mm: float = 4.0, seed: int = 0) -> tuple[np.ndarray, dict]:
    """Signed perpendicular height (mm) above the workboard plane at each colour pixel (positive toward camera)."""
    import cell_shared_markers

    plane = surface(depth_mm, factory, roi, tol_mm=tol_mm, seed=seed)
    if not plane.get("ok"):
        return np.full(depth_mm.shape, np.nan), plane
    size = _colour_size(factory, depth_mm.shape)
    colour_depth = cell_shared_markers.depth_in_colour(depth_mm, factory, size)
    _, colour_K, _, _ = calibration(factory)
    h_c, w_c = colour_depth.shape
    v_grid, u_grid = np.mgrid[0:h_c, 0:w_c]
    nx, ny, nz = (float(x) for x in plane["normal"])
    ray_dot = ((u_grid - colour_K[0, 2]) * (nx / colour_K[0, 0])
               + (v_grid - colour_K[1, 2]) * (ny / colour_K[1, 1]) + nz)
    return colour_depth * ray_dot + float(plane["height_mm"]), plane


def capture_median_depth(dev_path: str = "/dev/v4l/by-id/rosy-realsense-d435-depth",
                         n: int = 5, timeout_s: float = 12.0) -> np.ndarray | None:
    """Capture `n` locked depth frames and return their median, falling back to locked single-frame capture."""
    import tempfile
    import cell_depth_lock
    import cell_depth_slots

    if n > 1:
        try:
            with cell_depth_lock.hold_depth_lock(timeout_s=timeout_s):
                with tempfile.TemporaryDirectory(prefix="depth-median-") as scratch:
                    frames, _ = cell_depth_slots.capture_depth_frames(
                        dev_path, n, Path(scratch) / "depth.raw",
                        timeout_s=min(float(timeout_s), cell_depth_slots.DEPTH_BURST_S),
                    )
            if frames is not None:
                med, valid = cell_depth_slots.median_depth(frames)
                if valid >= 0.40:
                    return med
        except (TimeoutError, OSError, ValueError):
            pass
    return cell_depth.capture_top_depth_z16(dev_path, timeout_s=timeout_s)


def cal_eval_depth_setup(depth, colour, cam_top: dict, cam_report: dict, flags: list[str],
                         params, load_json_opt, find_base_px):
    """Align depth to colour using `d435_factory` when readable, else fall back to `align_edges`."""
    import cell_params as prm

    cfg_height_m = cam_top.get("height_m")
    factory = load_json_opt(Path(str(cam_top["d435_factory"])).expanduser()) if cam_top.get("d435_factory") else None
    heights = to_depth = None
    if depth is not None and factory is not None:
        roi = tuple(cam_top["depth_roi"]) if cam_top.get("depth_roi") else (40, 150, 620, 470)
        try:
            heights, plane = height_map_in_colour(depth, factory, roi)
            to_depth = np.eye(3)
            if plane.get("ok"):
                cam_mm = float(plane["height_mm"])
                nadir, center = plane.get("nadir_px"), cam_top.get("center_px")
                nadir_off = round(math.hypot(float(nadir[0]) - float(center[0]), float(nadir[1]) - float(center[1])), 1) if (nadir and center) else None
                cam_report.update({
                    "cam_to_table_mm": cam_mm, "tilt_deg": plane.get("tilt_deg"), "nadir_px": nadir,
                    "nadir_off_px": nadir_off, "depth_basis": "d435_factory",
                    "height_diff_mm": round(cam_mm - float(cfg_height_m) * 1000.0, 1) if cfg_height_m is not None else None,
                })
                if nadir_off is not None and nadir_off > float(prm.get(params, "verify.nadir_off_px")):
                    flags.append("nadir_off_gt_limit")
            else:
                flags.append(str(plane.get("reason") or "depth_plane_failed"))
        except (ValueError, KeyError, TypeError):
            heights = to_depth = None
    if heights is None and depth is not None and colour is not None:
        plane = cell_depth.table_plane(depth)
        cam_mm = round(abs(float(plane[1])), 2)
        heights = cell_depth.height_map(depth, plane)
        to_depth, edge_px = cell_depth.align_edges(colour, heights)
        cam_report.update({
            "cam_to_table_mm": cam_mm, "align_scale": round(float(to_depth[0, 0]), 3),
            "align_shift": [round(float(to_depth[0, 2]), 1), round(float(to_depth[1, 2]), 1)],
            "align_edge_px": round(float(edge_px), 2),
            "height_diff_mm": round(cam_mm - float(cfg_height_m) * 1000.0, 1) if cfg_height_m is not None else None,
        })
    if heights is not None:
        base_px = find_base_px()
        plate_mm = cell_depth.plate_top(heights, to_depth, base_px) if base_px is not None else None
        if plate_mm is not None:
            plate_mm = round(float(plate_mm), 2)
            cam_mm = cam_report.get("cam_to_table_mm")
            cam_report.update({"plate_mm": plate_mm, "cam_to_plate_mm": round(cam_mm - plate_mm, 2) if cam_mm is not None else None})
    else:
        flags.append("missing_depth")
    return heights, to_depth


def cal_eval_anchor_sites(sites_raw: dict[str, dict], cam_report: dict, flags: list[str], d_lim: float,
                          has_depth: bool) -> dict[str, dict]:
    """Anchor site depth heights using rigid touch FK median (fallback plate_mm; else relative inter-site deltas)."""
    anchors = [float(v["touch_z"]) - float(v["site_mm"]) / 1000.0
               for v in sites_raw.values() if v["touch_z"] is not None and v["site_mm"] is not None]
    fk_table_z_m = float(np.median(anchors)) if anchors else None
    plate_mm = cam_report.get("plate_mm")
    cam_report["fk_table_z_m"] = round(fk_table_z_m, 4) if fk_table_z_m is not None else None
    if has_depth and fk_table_z_m is None and plate_mm is None:
        flags.append("plate_not_found")
    rel_items = [(n, v) for n, v in sites_raw.items() if v["site_mm"] is not None and v["surface_z"] is not None]
    rel_diffs: dict[str, float] = {}
    if fk_table_z_m is None and plate_mm is None:
        if len(rel_items) == 2:
            (n0, v0), (n1, v1) = rel_items
            delta = round((float(v1["site_mm"]) - float(v0["site_mm"])) - (float(v1["surface_z"]) - float(v0["surface_z"])) * 1000.0, 1)
            rel_diffs[n0], rel_diffs[n1] = -delta, delta
        elif len(rel_items) >= 3:
            base_off = float(np.median([float(v["surface_z"]) * 1000.0 - float(v["site_mm"]) for _, v in rel_items]))
            for n, v in rel_items:
                rel_diffs[n] = round((float(v["site_mm"]) + base_off) - float(v["surface_z"]) * 1000.0, 1)
    sites_report: dict[str, dict] = {}
    for name, v in sites_raw.items():
        site_mm, surface_z, sflags = v["site_mm"], v["surface_z"], list(v["flags"])
        depth_z = (round(fk_table_z_m + site_mm / 1000.0, 4) if (site_mm is not None and fk_table_z_m is not None)
                   else (round((site_mm - plate_mm) / 1000.0, 4) if (site_mm is not None and plate_mm is not None) else None))
        depth_diff_mm = round((depth_z - float(surface_z)) * 1000.0, 1) if (depth_z is not None and surface_z is not None) else None
        rel_diff = rel_diffs.get(name)
        check_diff = depth_diff_mm if depth_diff_mm is not None else rel_diff
        if check_diff is not None and abs(check_diff) > d_lim and "depth_diff_gt_6mm" not in sflags:
            sflags.append("depth_diff_gt_6mm")
        flags.extend(f"{name}:{fl}" for fl in sflags)
        sites_report[name] = {**v["entry"], "site_above_table_mm": site_mm, "depth_surface_z_m": depth_z,
                              "depth_diff_mm": depth_diff_mm, **({"relative_depth_diff_mm": rel_diff} if rel_diff is not None else {}),
                              "flags": sflags}
    return sites_report


def surface(depth_mm: np.ndarray, factory: dict, roi: tuple, tol_mm: float = 4.0, seed: int = 0) -> dict:
    """The largest plane among depth points that land inside the colour-pixel box `roi` (x0, y0, x1, y1), in the colour
    camera frame: distance (camera height above it, mm), tilt of the optical axis from its normal, and fit quality."""
    depth_K, colour_K, R, t = calibration(factory)
    h, w = depth_mm.shape
    v, u = np.nonzero(depth_mm > 0)
    z = depth_mm[v, u].astype(float)
    pts = np.column_stack([(u - depth_K[0, 2]) * z / depth_K[0, 0], (v - depth_K[1, 2]) * z / depth_K[1, 1], z])
    in_colour = pts @ R.T + t
    pix = in_colour @ colour_K.T
    pix = pix[:, :2] / pix[:, 2:3]
    x0, y0, x1, y1 = roi
    keep = (pix[:, 0] >= x0) & (pix[:, 0] < x1) & (pix[:, 1] >= y0) & (pix[:, 1] < y1)
    sample = in_colour[keep][::3]
    if len(sample) < 500:
        return {"ok": False, "reason": "too_few_depth_points_in_roi", "points": int(len(sample))}
    best, _ = cell_depth._ransac(sample, tol_mm, 2000, np.random.default_rng(seed))
    if best is None:
        return {"ok": False, "reason": "no_plane", "points": int(len(sample))}
    normal, centre = best
    for _ in range(5):  # refit on the inliers of the refit plane
        near = sample[np.abs((sample - centre) @ normal) < tol_mm]
        if len(near) < 3:
            return {"ok": False, "reason": "no_plane", "points": int(len(sample))}
        centre = near.mean(axis=0)
        normal = np.linalg.svd(near - centre, full_matrices=False)[2][-1]
    distance = float(-normal @ centre)
    if distance < 0:
        normal, distance = -normal, -distance
    residual = (near - centre) @ normal
    tilt = math.degrees(math.acos(min(1.0, abs(float(normal[2])))))
    share, rms = len(near) / len(sample), float(np.sqrt((residual ** 2).mean()))
    clear = share >= MIN_SHARE and rms <= MAX_RMS_MM  # else a deck, tray or the far table may have won silently
    down = colour_K @ -normal
    return {"ok": clear, "reason": None if clear else "plane_not_clear_in_roi", "height_mm": round(distance, 1), "tilt_deg": round(tilt, 2),
            "tilt_toward_deg": round(math.degrees(math.atan2(-normal[1], -normal[0])), 1),
            "normal": [round(float(x), 5) for x in normal], "share": round(share, 3),
            "rms_mm": round(rms, 2), "roi": list(roi),
            # where a vertical line through the cell vanishes: the centre cell_calibration.parallax scales about
            # (config cameras.<name>.center_px); 2026-11-14 the top D435 tilted 10.6 deg put it 112 px from (320, 240)
            "nadir_px": [round(float(down[0] / down[2]), 1), round(float(down[1] / down[2]), 1)]}


def compare(current: dict, reference: dict) -> dict:
    """How far the camera moved between two `surface` results of the same board."""
    if not (current.get("ok") and reference.get("ok")):
        return {"moved": None, "reason": "a measurement failed"}
    if current.get("roi") != reference.get("roi"):
        return {"moved": None, "reason": "different colour boxes measure different surfaces"}
    cosine = abs(float(np.dot(current["normal"], reference["normal"])))
    tilt = math.degrees(math.acos(min(1.0, cosine)))
    height = current["height_mm"] - reference["height_mm"]
    return {"moved": tilt > TILT_MOVED_DEG or abs(height) > HEIGHT_MOVED_MM,
            "tilt_change_deg": round(tilt, 2), "height_change_mm": round(height, 1)}


def bump(reference_image, current_image, reference_pose: dict, current_pose: dict, max_shift_px: float = 6.0) -> dict:
    """After a knock: the reference-image shift (cell_preflight, turns and slides) and the depth height (toward or
    away from the board, which the image cannot tell from a turn) in one verdict."""
    import cell_preflight

    shift = cell_preflight.camera_shift_px(reference_image, current_image)
    depth = compare(current_pose, reference_pose)
    if not shift.get("ok") or depth["moved"] is None:
        return {"moved": None, "reason": shift.get("why") or depth.get("reason"), "shift": shift, "depth": depth}
    turned = shift["max_px"] > max_shift_px
    kind = "none" if not (turned or depth["moved"]) else "height" if depth["moved"] else "view"
    return {"moved": kind != "none", "kind": kind, "shift_px": shift["max_px"], **depth}


def main(argv=None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="verb", required=True)
    me = sub.add_parser("measure")
    me.add_argument("--depth", type=Path, required=True, help="raw Z16 (mm), one or more frames of the factory size")
    me.add_argument("--factory", type=Path, required=True, help="cell_device_intrinsics read output")
    me.add_argument("--roi", required=True, help="x0,y0,x1,y1 of the work board in colour pixels")
    me.add_argument("--out", type=Path)
    co = sub.add_parser("compare")
    co.add_argument("current", type=Path)
    co.add_argument("reference", type=Path)
    bu = sub.add_parser("bump", help="reference-image shift and depth height together")
    bu.add_argument("--image", type=Path, required=True)
    bu.add_argument("--ref-image", type=Path, required=True)
    bu.add_argument("--pose", type=Path, required=True, help="`measure` output now")
    bu.add_argument("--ref-pose", type=Path, required=True, help="`measure` output at the reference")
    bu.add_argument("--max-shift-px", type=float, default=6.0)
    args = ap.parse_args(argv)
    if args.verb == "bump":
        import cv2

        result = bump(cv2.imread(str(args.ref_image), cv2.IMREAD_GRAYSCALE), cv2.imread(str(args.image), cv2.IMREAD_GRAYSCALE),
                      json.loads(args.ref_pose.read_text()), json.loads(args.pose.read_text()), args.max_shift_px)
        print(json.dumps(result))
        return 1 if result["moved"] is not False else 0
    if args.verb == "compare":
        result = compare(json.loads(args.current.read_text()), json.loads(args.reference.read_text()))
        print(json.dumps(result))
        return 1 if result["moved"] is not False else 0
    factory = json.loads(args.factory.read_text())
    w, h = factory["depth"]["size"]
    frames = np.fromfile(args.depth, np.uint16)
    if frames.size % (w * h):
        raise SystemExit(f"depth file is not whole {w}x{h} frames")
    stack = frames.reshape(-1, h, w).astype(float)
    stack[stack == 0] = np.nan
    with np.errstate(all="ignore"):
        depth = np.nan_to_num(np.nanmedian(stack, axis=0), nan=0.0)  # median over frames, no return stays 0
    result = surface(depth, factory, tuple(int(v) for v in args.roi.split(",")))
    text = json.dumps(result, indent=1)
    if args.out:
        args.out.write_text(text)
    print(text)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
