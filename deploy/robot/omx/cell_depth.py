"""Heights in the cell from the top depth camera, in the colour view's pixels: no ruler, no touch.

2026-11-01: a person's ruler, closed-jaw touches and hand-picked depth boxes all failed to give the belt's height.
The touches stopped at the planning floor, and a 16 g container slid away from the jaws without a contact. So the
heights come from the depth image instead:
- the table is the largest plane (RANSAC), and every height is measured from it, so a tilted camera does not matter;
- the depth view (wider field) is put onto the colour view by the scene's edges: the scale and shift where the
  colour image's edges lie closest to the height steps (`align_edges`). The object mask alone (`align`) slides
  along a row of objects standing in one line, as the cell's did on 2026-11-01;
- an arm's FK zero is the top of the plate it stands on, read in a ring around its base.

The D435 runs without its SDK here (USB 3.0, v4l2 Z16); its intrinsics are nominal (`FOCAL_PX`).

    python cell_depth.py --depth d.raw --colour c.jpg --px 345,80 --px 330,320   # read only
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import numpy as np


def _run_v4l2_z16(cmd: list[str], timeout_s: float, **kwargs):
    """Run v4l2-ctl with 'Z16' primary, falling back to 'Z16 ' ONLY on CalledProcessError."""
    try:
        return subprocess.run(cmd, timeout=float(timeout_s), check=True, **kwargs)
    except subprocess.CalledProcessError:
        fmt = "--set-fmt-video=width=640,height=480,pixelformat=Z16"
        if fmt not in cmd:
            raise
        retry = [f"{fmt} " if part == fmt else part for part in cmd]
        return subprocess.run(retry, timeout=float(timeout_s), check=True, **kwargs)


def capture_top_depth_z16(dev_path: str = "/dev/v4l/by-id/rosy-realsense-d435-depth", out_raw: Path | None = None,
                          *, timeout_s: float = 12.0) -> np.ndarray | None:
    """Capture a fresh warmed 640x480 Z16 frame; never reuse old raw on capture failure."""
    raw_path = Path(out_raw) if out_raw is not None else Path(tempfile.gettempdir()) / "rosy-top-depth-z16.raw"
    if not Path(dev_path).exists():
        return None
    try:
        raw_path.unlink(missing_ok=True)
    except OSError:
        return None
    try:
        captured = _run_v4l2_z16(["v4l2-ctl", "-d", dev_path,
                                  "--set-fmt-video=width=640,height=480,pixelformat=Z16", "--set-parm=6",
                                  "--stream-mmap=3", "--stream-skip=12", "--stream-count=1",
                                  f"--stream-to={raw_path}"], float(timeout_s),
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return None
    if getattr(captured, "returncode", 0) != 0 or not raw_path.exists() or raw_path.stat().st_size != 640 * 480 * 2:
        return None
    arr = np.fromfile(raw_path, dtype=np.uint16)
    return arr.reshape(480, 640) if float((arr > 0).mean()) >= 0.40 else None


def capture_top_depth_z16_receipt(dev_path: str, out_raw: Path, *, timeout_s: float = 12.0) -> tuple[np.ndarray, dict] | None:
    """Capture one Z16 frame with the V4L2 start-of-exposure stamp from the same buffer."""
    lock_path = Path(out_raw).with_suffix(Path(out_raw).suffix + ".lock")
    # shortcut: a crash leaves this path locked; use a unique output path per attempt until owner cleanup exists.
    try:
        lock_fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except OSError:
        return None
    try:
        return _capture_top_depth_z16_receipt_locked(dev_path, out_raw, timeout_s)
    finally:
        os.close(lock_fd)
        lock_path.unlink(missing_ok=True)


def _sync_parent(path: Path) -> None:
    if os.name == "posix":
        fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def _capture_top_depth_z16_receipt_locked(dev_path: str, out_raw: Path, timeout_s: float) -> tuple[np.ndarray, dict] | None:
    raw_path = Path(out_raw)
    receipt_path = raw_path.with_suffix(raw_path.suffix + ".receipt.json")
    try:
        raw_path.unlink(missing_ok=True)
        receipt_path.unlink(missing_ok=True)
        if not Path(dev_path).exists():
            return None
        started_wall = time.time()
        started = time.monotonic()
        captured = _run_v4l2_z16(["v4l2-ctl", "--verbose", "-d", dev_path,
                                  "--set-fmt-video=width=640,height=480,pixelformat=Z16", "--set-parm=6",
                                  "--stream-mmap=3", "--stream-skip=12", "--stream-count=1",
                                  f"--stream-to={raw_path}"], float(timeout_s),
                                 stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        ended = time.monotonic()
        ended_wall = time.time()
        raw = raw_path.read_bytes()
    except (OSError, subprocess.SubprocessError):
        raw_path.unlink(missing_ok=True)
        return None
    lines = [line for line in (captured.stderr or "").splitlines() if "cap dqbuf:" in line]
    last = lines[-1] if lines else ""
    match = re.search(r"seq:\s*(\d+).*?bytesused:\s*(\d+).*?ts:\s*([0-9.]+)", last)
    if (captured.returncode != 0 or len(raw) != 640 * 480 * 2 or match is None or int(match.group(2)) != len(raw)
            or "ts-monotonic, ts-src-soe" not in last):
        raw_path.unlink(missing_ok=True)
        return None
    stamp = float(match.group(3))
    depth = np.frombuffer(raw, dtype="<u2").reshape(480, 640)
    valid = float((depth > 0).mean())
    if not started - 0.5 <= stamp <= ended + 0.5 or valid < 0.40:
        raw_path.unlink(missing_ok=True)
        return None
    start_offset, end_offset = started_wall - started, ended_wall - ended
    if abs(start_offset - end_offset) > 0.5:
        raw_path.unlink(missing_ok=True)
        return None
    try:
        boot_id = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    except OSError:
        boot_id = None
    receipt = {"source_seq": int(match.group(1)), "exposure_monotonic_s": stamp,
               "source_seq_scope": "per_v4l2_capture_stream",
               "capture_started_monotonic_s": started, "capture_ended_monotonic_s": ended,
               "capture_started_wall_s": started_wall, "capture_ended_wall_s": ended_wall,
               "exposure_wall_estimate_s": stamp + (start_offset + end_offset) / 2,
               "wall_bridge_uncertainty_s": abs(start_offset - end_offset) / 2 + 0.01,
               "boot_id": boot_id,
               "clock_semantics": "v4l2_monotonic_start_of_exposure", "raw_sha256": hashlib.sha256(raw).hexdigest(),
               "valid_depth_ratio": valid, "raw_path": str(raw_path)}
    pending = receipt_path.with_suffix(receipt_path.suffix + ".pending")
    try:
        with raw_path.open("rb+") as saved_raw:
            os.fsync(saved_raw.fileno())
        _sync_parent(raw_path)
        with pending.open("w", encoding="utf-8") as saved_receipt:
            json.dump(receipt, saved_receipt, allow_nan=False)
            saved_receipt.flush()
            os.fsync(saved_receipt.fileno())
        pending.replace(receipt_path)
        _sync_parent(receipt_path)
    except OSError:
        pending.unlink(missing_ok=True)
        raw_path.unlink(missing_ok=True)
        receipt_path.unlink(missing_ok=True)
        return None
    return depth, receipt

FOCAL_PX = 385.0  # D435 depth at 640 x 480, nominal
PLANE_MM = 4.0
RAISED_MM = (18.0, 120.0)  # what stands up from the table: containers, stacks (not the 10 mm pallet)


def points(depth, focal: float = FOCAL_PX):
    """(h, w, 3) camera-frame points in mm; zero depth (no return) stays zero."""
    h, w = depth.shape
    z = depth.astype(float)
    z_f = z / focal
    return np.dstack([(np.arange(w) - w / 2)[None, :] * z_f, (np.arange(h) - h / 2)[:, None] * z_f, z])


def _ransac(pts, tol_mm: float, tries: int, rng):
    """(unit normal, a point on it), inlier count: the plane with the most points within `tol_mm`."""
    normals, points_a = [], []
    for _ in range(tries):
        a, b, c = pts[rng.choice(len(pts), 3, replace=False)]
        u, v = b - a, c - a
        nx = float(u[1] * v[2] - u[2] * v[1])
        ny = float(u[2] * v[0] - u[0] * v[2])
        nz = float(u[0] * v[1] - u[1] * v[0])
        norm = (nx * nx + ny * ny + nz * nz) ** 0.5
        if norm < 1e-9:
            continue
        inv = -1.0 / norm if nz > 0 else 1.0 / norm
        normals.append((nx * inv, ny * inv, nz * inv))
        points_a.append(a)
    if not normals:
        return None, -1
    best, count = None, -1
    n_mat = np.asarray(normals, float)
    a_mat = np.asarray(points_a, float)
    offsets = np.sum(a_mat * n_mat, axis=1)
    for start in range(0, len(n_mat), 32):
        nb = n_mat[start:start + 32]
        ob = offsets[start:start + 32]
        diff = pts @ nb.T
        np.subtract(diff, ob, out=diff)
        np.abs(diff, out=diff)
        counts = (diff < tol_mm).sum(axis=0)
        idx = int(np.argmax(counts))
        if int(counts[idx]) > count:
            count = int(counts[idx])
            best = (nb[idx], a_mat[start + idx])
    return best, count


def table_plane(depth, tol_mm: float = PLANE_MM, tries: int = 400, seed: int = 0, share: float = 0.25):
    """(unit normal toward the camera, offset): the cell's table, refitted on its points. The view also holds a lower
    surface about 60 mm under the table, sometimes larger than it: of the two largest parallel planes the higher one is
    the table when it holds `share` of the larger's points (2026-11-01: the pallet read 75 mm in one frame, 10 in the
    next, as the plane flipped between them)."""
    h, w = depth.shape
    ys, xs = np.nonzero(depth > 0)
    ys, xs = ys[::7], xs[::7]
    z = depth[ys, xs].astype(float)
    pts = np.column_stack(((xs - w / 2) * (z / FOCAL_PX), (ys - h / 2) * (z / FOCAL_PX), z))
    rng = np.random.default_rng(seed)
    (n, a), k = _ransac(pts, tol_mm, tries, rng)
    rest = pts[np.abs(pts @ n - float(a @ n)) >= tol_mm]
    if len(rest) >= 3:
        (n2, a2), k2 = _ransac(rest, tol_mm, tries, rng)
        if k2 >= share * k and (a2 - a) @ n > 5 * tol_mm and abs(n2 @ n) > 0.98:
            n, a = n2, a2
    near = pts[np.abs(pts @ n - float(a @ n)) < tol_mm]
    _, _, vt = np.linalg.svd(np.c_[near, np.ones(len(near))], full_matrices=False)
    normal, offset = vt[-1][:3], vt[-1][3]
    scale = np.linalg.norm(normal)
    normal, offset = normal / scale, offset / scale
    if normal[2] > 0:  # +height is toward the camera (smaller depth)
        normal, offset = -normal, -offset
    return normal, offset


def height_map(depth, plane) -> np.ndarray:
    """mm above the table plane; NaN where the camera had no return."""
    normal, offset = plane
    h, w = depth.shape
    ray_dot = ((np.arange(w) - w / 2) * (normal[0] / FOCAL_PX))[None, :] + (
        (np.arange(h) - h / 2) * (normal[1] / FOCAL_PX) + normal[2]
    )[:, None]
    return np.where(depth > 0, depth * ray_dot + offset, np.nan)


def align(object_mask, heights, scales=np.arange(0.55, 0.86, 0.01), step: int = 2) -> tuple[np.ndarray, float]:
    """Colour -> depth affine (scale, shift) where the colour object mask lies best on the raised depth pixels, and
    that overlap (0..1). Searched on half-size images, then refined by one pixel around the best."""
    import cv2

    raised = ((np.nan_to_num(heights) > RAISED_MM[0]) & (np.nan_to_num(heights) < RAISED_MM[1])).astype(np.uint8)
    raised = cv2.morphologyEx(raised, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    om = (object_mask > 0).astype(np.uint8)
    h, w = raised.shape

    def overlap(m, src, dst, size):
        warped = cv2.warpAffine(src, m, size, flags=cv2.INTER_NEAREST)
        return (warped & dst).sum() / max(1, warped.sum())

    small = (cv2.resize(om, (om.shape[1] // 2, om.shape[0] // 2), interpolation=cv2.INTER_NEAREST),
             cv2.resize(raised, (w // 2, h // 2), interpolation=cv2.INTER_NEAREST))
    best, score = None, -1.0
    for s in scales:  # shifts within 40 px of a centred view (the colour lens sits beside the depth one)
        cx, cy = w * (1 - s) / 4, h * (1 - s) / 4  # half-size
        for tx in range(int(cx) - 20, int(cx) + 21, step):
            for ty in range(int(cy) - 20, int(cy) + 21, step):
                v = overlap(np.float32([[s, 0, tx], [0, s, ty]]), *small, (w // 2, h // 2))
                if v > score:
                    best, score = (s, 2 * tx, 2 * ty), v
    s, tx, ty = best
    for dx in range(-2, 3):
        for dy in range(-2, 3):
            m = np.float32([[s, 0, tx + dx], [0, s, ty + dy]])
            v = overlap(m, om, raised, (w, h))
            if v >= score:
                best, score = (s, tx + dx, ty + dy), v
    s, tx, ty = best
    return np.float32([[s, 0, tx], [0, s, ty]]), float(score)


def align_edges(colour, heights, scales=np.arange(0.55, 0.86, 0.01), reach: int = 40) -> tuple[np.ndarray, float]:
    """Colour -> depth affine (scale, shift) where the colour image's edges lie closest to the height steps, and the
    mean edge distance in depth pixels (lower is better). Every rim, plate and object counts, so objects standing
    in one row cannot leave the alignment loose as they do in `align`. Coarse grid, then one-pixel refinement."""
    import cv2

    hn = np.clip(np.nan_to_num(heights, nan=-100.0) + 100.0, 0, 255).astype(np.uint8)
    depth_edges = cv2.Canny(cv2.GaussianBlur(hn, (5, 5), 0), 10, 30)  # steps of a few mm
    grey = colour if colour.ndim == 2 else cv2.cvtColor(colour, cv2.COLOR_BGR2GRAY)
    ys, xs = np.nonzero(cv2.Canny(cv2.GaussianBlur(grey, (5, 5), 0), 40, 120))
    pts = np.c_[xs, ys].astype(float)[::3]
    dist = np.minimum(cv2.distanceTransform((depth_edges == 0).astype(np.uint8), cv2.DIST_L2, 3), 15.0)
    h, w = heights.shape
    min_ok = int(np.ceil(0.7 * len(pts)))

    def search_scale(s, tx_range, ty_range):
        if not len(pts):
            return (float("inf"), s, tx_range[0], ty_range[0])
        u0, v0 = pts[:, 0] * s, pts[:, 1] * s
        ui0, vi0 = np.floor(u0).astype(int), np.floor(v0).astype(int)
        best_s = (float("inf"), s, tx_range[0], ty_range[0])
        for tx in tx_range:
            ok_u = (u0 >= -tx) & (u0 < w - 1 - tx)
            if int(ok_u.sum()) < min_ok:
                continue
            ui = ui0 + tx
            for ty in ty_range:
                ok = ok_u & (v0 >= -ty) & (v0 < h - 1 - ty)
                k = int(ok.sum())
                if k >= min_ok:
                    c_val = float(dist[vi0[ok] + ty, ui[ok]].sum()) / k
                    if c_val < best_s[0]:
                        best_s = (c_val, s, tx, ty)
        return best_s

    best = min(search_scale(s, range(int(w * (1 - s) / 2) - reach, int(w * (1 - s) / 2) + reach + 1, 3),
                            range(int(h * (1 - s) / 2) - reach, int(h * (1 - s) / 2) + reach + 1, 3))
               for s in scales)
    _, s, tx, ty = best
    c, s, tx, ty = min(search_scale(s2, range(tx - 3, tx + 4), range(ty - 3, ty + 4))
                       for s2 in np.arange(s - 0.01, s + 0.011, 0.002))
    return np.float32([[s, 0, tx], [0, s, ty]]), c


def height_at(heights, to_depth, px, r: int = 4) -> float:
    """Median height (mm) within `r` depth pixels of where colour pixel `px` lands."""
    x, y = np.round(to_depth @ [px[0], px[1], 1.0]).astype(int)
    patch = heights[max(0, y - r):y + r + 1, max(0, x - r):x + r + 1]
    return float(np.nanmedian(patch)) if np.isfinite(patch).any() else float("nan")


def plate_top(heights, to_depth, base_px, radius_px: float = 45.0, plate_mm=(8.0, 35.0)) -> float | None:
    """The plate an arm stands on, read in a ring around its base (colour pixel): the median of the ring samples
    in the plate's height range. Links and cables crossing the ring read higher and are left out."""
    ring = [height_at(heights, to_depth, (base_px[0] + radius_px * np.cos(t), base_px[1] + radius_px * np.sin(t)), 2)
            for t in np.linspace(0, 2 * np.pi, 36, endpoint=False)]
    on = [v for v in ring if plate_mm[0] <= v <= plate_mm[1]]
    return float(np.median(on)) if len(on) >= 4 else None


def _load_json_opt(path: Path | None) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8")) if (path and path.is_file()) else None
    except (OSError, ValueError):
        return None


def _project_site_px(rec: dict | None, cam_top: dict, arm_xy, fit_z: float | None, target_z: float | None, cal_mod):
    if not arm_xy or len(arm_xy) < 2 or not rec or not rec.get("homography"):
        return None
    try:
        u, v = cal_mod.to_pixel(rec["homography"], arm_xy[:2])
        if target_z is not None and fit_z is not None and cam_top.get("center_px") and cam_top.get("height_m"):
            u, v = cal_mod.parallax((u, v), float(fit_z), float(target_z), cam_top)
        return [round(float(u), 2), round(float(v), 2)]
    except Exception:
        return None


def _num2(p) -> bool:
    return isinstance(p, (list, tuple)) and len(p) >= 2 and isinstance(p[0], (int, float)) and isinstance(p[1], (int, float))


def _poly_center_px(px):
    if _num2(px):
        return [float(px[0]), float(px[1])]
    pts = [p for p in (px or ()) if _num2(p)] if isinstance(px, (list, tuple)) else []
    return [round(sum(float(p[0]) for p in pts) / len(pts), 2), round(sum(float(p[1]) for p in pts) / len(pts), 2)] if pts else None


def _finite_height(heights, to_depth, px) -> float | None:
    if isinstance(px, (list, tuple)) and len(px) >= 3 and isinstance(px[0], (list, tuple)):
        import cv2
        pts = [np.round(to_depth @ [float(p[0]), float(p[1]), 1.0])[:2] for p in px if _num2(p)]
        if len(pts) >= 3:
            mask = np.zeros(heights.shape, dtype=np.uint8)
            cv2.fillPoly(mask, [np.asarray(pts, dtype=np.int32)], 1)
            if mask.any():
                vals = heights[(mask == 1) & np.isfinite(heights)]
                return round(float(np.median(vals)), 2) if vals.size else None
        px = _poly_center_px(px)
    val = height_at(heights, to_depth, px) if _num2(px) else float("nan")
    return round(float(val), 2) if np.isfinite(val) else None


def _import_omx():
    omx_dir = str(Path(__file__).resolve().parent)
    if omx_dir not in sys.path:
        sys.path.insert(0, omx_dir)
    import cell_attempts, cell_calibration, cell_params, cell_pivot
    return cell_attempts, cell_calibration, cell_params, cell_pivot


def verify_profile_depth(config: dict, calibration: dict | None, bias: dict | None = None, *,
                         depth=None, colour=None, live: dict | None = None,
                         touch_receipts: dict[str, dict] | None = None, now_ts: float | None = None) -> dict:
    """Read-only post-calibration cross-verification across D435 depth, touch receipts, map LOO/bias, and live FK."""
    import math
    from datetime import datetime, timezone

    cell_attempts, cal, prm, cell_pivot = _import_omx()
    now = float(now_ts) if now_ts is not None else time.time()
    work_dir = Path(config["work_dir"]).expanduser() if config.get("work_dir") else None
    try:
        with_maps = cell_pivot.with_site_maps(config, calibration) if (calibration and calibration.get("sites")) else (calibration or {"sites": {}})
    except SystemExit:
        with_maps = calibration or {"sites": {}}

    cam_top = (config.get("cameras") or {}).get("top") or {}
    cfg_height_m = cam_top.get("height_m")
    flags: list[str] = []
    cam_report: dict = dict.fromkeys(("cam_to_table_mm", "height_diff_mm", "plate_mm", "cam_to_plate_mm",
                                      "align_scale", "align_shift", "align_edge_px"))
    cam_report["config_height_m"] = cfg_height_m

    heights = to_depth = plate_mm = None
    if depth is not None and colour is not None:
        plane = table_plane(depth)
        cam_mm = round(abs(float(plane[1])), 2)
        heights = height_map(depth, plane)
        to_depth, edge_px = align_edges(colour, heights)
        cam_report.update({
            "cam_to_table_mm": cam_mm, "align_scale": round(float(to_depth[0, 0]), 3),
            "align_shift": [round(float(to_depth[0, 2]), 1), round(float(to_depth[1, 2]), 1)],
            "align_edge_px": round(float(edge_px), 2),
            "height_diff_mm": round(cam_mm - float(cfg_height_m) * 1000.0, 1) if cfg_height_m is not None else None,
        })
        base_px = cam_top.get("plate_px")
        if base_px is None:
            map_sites = (config.get("calibrate") or {}).get("map_sites") or list(config.get("sites") or [])
            for sname in list(map_sites) + list((with_maps.get("sites") or {}).keys()):
                rec = cell_pivot.map_record(with_maps, sname)
                if rec and rec.get("homography"):
                    fit_z = rec.get("z_view", ((config.get("sites") or {}).get(sname) or {}).get("z"))
                    base_px = _project_site_px(rec, cam_top, (0.0, 0.0), fit_z, 0.0, cal)
                    if base_px is not None:
                        break
        plate_mm = plate_top(heights, to_depth, base_px) if base_px is not None else None
        if plate_mm is not None:
            plate_mm = round(float(plate_mm), 2)
            cam_report.update({"plate_mm": plate_mm, "cam_to_plate_mm": round(cam_mm - plate_mm, 2)})
        else:
            flags.append("plate_not_found")
    else:
        flags.append("missing_depth")

    sites_report: dict[str, dict] = {}
    max_loo_limit = float(prm.default("calibrate.max_loo_mm"))
    bias_regions = (bias or {}).get("regions") or []
    for name, spec in (config.get("sites") or {}).items():
        rec = cell_pivot.map_record(with_maps, name)
        surface_z = spec.get("surface_z")
        fit_z = (rec or {}).get("z_view", spec.get("z"))
        target_z = surface_z if surface_z is not None else spec.get("z")
        site_flags: list[str] = []

        place_px = _project_site_px(rec, cam_top, spec.get("place"), fit_z, target_z, cal) or _poly_center_px(spec.get("surface_px"))
        start_px = _project_site_px(rec, cam_top, spec.get("start"), fit_z, target_z, cal)
        place_mm = _finite_height(heights, to_depth, place_px) if heights is not None else None
        start_mm = _finite_height(heights, to_depth, start_px) if heights is not None else None
        surf_px_mm = _finite_height(heights, to_depth, spec.get("surface_px")) if heights is not None else None
        site_mm = next((v for v in (place_mm, surf_px_mm, start_mm) if v is not None), None)

        depth_z = round((site_mm - plate_mm) / 1000.0, 4) if (site_mm is not None and plate_mm is not None) else None
        depth_diff_mm = round((depth_z - float(surface_z)) * 1000.0, 1) if (depth_z is not None and surface_z is not None) else None
        step_mm = round(place_mm - start_mm, 1) if (place_mm is not None and start_mm is not None) else None
        if depth_diff_mm is not None and abs(depth_diff_mm) > 6.0:
            site_flags.append("depth_diff_gt_6mm")
        if step_mm is not None and abs(step_mm) > 8.0:
            site_flags.append("place_vs_start_step_gt_8mm")

        receipt = (touch_receipts or {}).get(name) or (_load_json_opt(work_dir / f"surface-{name}.json") if (touch_receipts is None and work_dir) else None)
        touch_z = receipt.get("surface_z") if (receipt and receipt.get("result") in (None, "touched") and receipt.get("surface_z") is not None) else None
        touch_diff_mm = round((float(touch_z) - float(surface_z)) * 1000.0, 1) if (touch_z is not None and surface_z is not None) else None
        if touch_diff_mm is not None and abs(touch_diff_mm) > 5.0:
            site_flags.append("touch_diff_gt_5mm")

        loo_max = ((rec or {}).get("loo_error_mm") or {}).get("max")
        if loo_max is not None and float(loo_max) > max_loo_limit:
            site_flags.append("high_loo")
        rec_sha = cell_attempts.digest(rec) if rec else None
        site_bias = [r for r in bias_regions if r.get("site") == name]
        bias_fresh = all(rec_sha is not None and r.get("map_sha") == rec_sha for r in site_bias) if site_bias else None
        if bias_fresh is False:
            site_flags.append("stale_bias")

        flags.extend(f"{name}:{fl}" for fl in site_flags)
        sites_report[name] = {
            "surface_z": surface_z, "place_mm": place_mm, "start_mm": start_mm, "surface_px_mm": surf_px_mm,
            "depth_surface_z_m": depth_z, "depth_diff_mm": depth_diff_mm, "place_vs_start_step_mm": step_mm,
            "touch_surface_z_m": touch_z, "touch_measured": (receipt or {}).get("measured"), "touch_diff_mm": touch_diff_mm,
            "loo_max_mm": loo_max, "bias_fresh": bias_fresh, "flags": site_flags,
        }

    live_data = live if live is not None else (_load_json_opt(Path(config["io"]).expanduser() / "live.json") if config.get("io") else None)
    fk_report: dict = {"present": bool(live_data), "fresh": False, "age_s": None, "tcp": None, "within_reach": None}
    if live_data:
        t = live_data.get("t")
        age_s = round(now - float(t), 2) if isinstance(t, (int, float)) else None
        fk_report.update({"age_s": age_s, "fresh": age_s is not None and age_s <= 2.0})
        state = live_data.get("state")
        if isinstance(state, list) and len(state) >= 5:
            plan = _load_json_opt(Path(config["plan_path"]).expanduser()) if config.get("plan_path") else None
            tcp_x_m = config.get("tcp_x_m") if config.get("tcp_x_m") is not None else (plan or {}).get("tcp_x_m")
            max_reach = (config.get("calibrate") or {}).get("max_reach_m") or ((plan or {}).get("limits") or {}).get("max_reach_m")
            try:
                x, y, z, yaw = cell_pivot.joints_tcp(state, tcp_x_m)
                fk_report["tcp"] = {"x": round(float(x), 4), "y": round(float(y), 4), "z": round(float(z), 4), "yaw_deg": round(float(yaw), 1)}
                fk_report["within_reach"] = (math.hypot(x, y) <= float(max_reach) + 1e-6) if max_reach is not None else None
            except (Exception, SystemExit):
                fk_report["tcp"] = None

    crit_tags = ("depth_diff_gt_6mm", "touch_diff_gt_5mm", "place_vs_start_step_gt_8mm", "stale_bias", "high_loo")
    verdict = "fail" if any(any(tag in fl for tag in crit_tags) for fl in flags) else ("warn" if (flags or not sites_report) else "pass")
    return {
        "schema": "rosy.omx-cell-depth-verify.v1", "arm_id": config.get("arm_id"),
        "measured": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "verdict": verdict, "ok": verdict == "pass", "flags": flags,
        "camera_top": cam_report, "sites": sites_report, "live_fk": fk_report,
    }


def _fetch_colour_frame(url: str):
    import urllib.error, urllib.parse, urllib.request, cv2

    if urllib.parse.urlparse(url).scheme not in ("http", "https"):
        return None
    try:
        with urllib.request.urlopen(url, timeout=2.0) as res:
            arr = np.frombuffer(res.read(5 * 1024 * 1024), dtype=np.uint8)
        return cv2.imdecode(arr, cv2.IMREAD_COLOR) if arr.size else None
    except (urllib.error.URLError, OSError, ValueError):
        return None


def _verify_main(argv: list[str]) -> int:
    import cv2

    _, _, _, cell_pivot = _import_omx()
    ap = argparse.ArgumentParser(description="Verify calibrated sites against D435 depth, touch receipts, and live FK")
    ap.add_argument("--config", required=True, type=Path)
    ap.add_argument("--depth", type=Path, help="raw Z16, 640x480 mm")
    ap.add_argument("--colour", type=Path, help="top camera colour frame")
    ap.add_argument("--capture", action="store_true", help="capture fresh Z16 depth (and colour from cameras.top.url)")
    ap.add_argument("--write", action="store_true", help="write work_dir/depth-verify.json atomically")
    args = ap.parse_args(argv)
    config = json.loads(args.config.read_text(encoding="utf-8"))
    cal_p = Path(config["calibration_path"]).expanduser() if config.get("calibration_path") else None
    cal, bias = _load_json_opt(cal_p), (_load_json_opt(cell_pivot.bias_path(cal_p)) if cal_p else None)
    depth = np.fromfile(args.depth, np.uint16).reshape(480, 640) if args.depth else (capture_top_depth_z16() if args.capture else None)
    colour = cv2.imread(str(args.colour)) if args.colour else None
    url = ((config.get("cameras") or {}).get("top") or {}).get("url")
    if colour is None and args.capture and url:
        colour = _fetch_colour_frame(url)
    report = verify_profile_depth(config, cal, bias, depth=depth, colour=colour)
    if args.write and config.get("work_dir"):
        work = Path(config["work_dir"]).expanduser()
        work.mkdir(parents=True, exist_ok=True)
        tmp, out = work / "depth-verify.tmp", work / "depth-verify.json"
        tmp.write_text(json.dumps(report, indent=1), encoding="utf-8")
        tmp.replace(out)
    print(json.dumps(report, indent=1))
    return 0


def main(argv=None) -> int:
    import cv2

    tokens = list(sys.argv[1:] if argv is None else argv)
    if tokens and tokens[0] == "verify":
        return _verify_main(tokens[1:])
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--depth", required=True, help="raw Z16, 640 x 480, mm")
    ap.add_argument("--colour", required=True)
    ap.add_argument("--px", action="append", default=[], help="x,y colour pixel to report a height for")
    ap.add_argument("--base", action="append", default=[], help="x,y colour pixel of an arm's base (its plate)")
    ap.add_argument("--hsv", default="5,120,120,22,255,255", help="object colour range: mask alignment, compared")
    args = ap.parse_args(argv)
    depth = np.fromfile(args.depth, np.uint16).reshape(480, 640)
    colour = cv2.imread(args.colour)
    lo_hi = [int(v) for v in args.hsv.split(",")]
    mask = cv2.inRange(cv2.cvtColor(colour, cv2.COLOR_BGR2HSV), tuple(lo_hi[:3]), tuple(lo_hi[3:]))
    heights = height_map(depth, table_plane(depth))
    m, edge_px = align_edges(colour, heights)
    m_mask, score = align(mask, heights)
    out = {"align": {"scale": round(float(m[0, 0]), 3), "shift": [float(m[0, 2]), float(m[1, 2])],
                     "edge_px": round(edge_px, 2)},
           "mask_align": {"shift": [float(m_mask[0, 2]), float(m_mask[1, 2])], "overlap": round(score, 2)},  # compare
           "heights_mm": {p: round(height_at(heights, m, [float(v) for v in p.split(",")]), 1) for p in args.px},
           "plates_mm": {b: plate_top(heights, m, [float(v) for v in b.split(",")]) for b in args.base}}
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
