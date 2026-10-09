"""D-563 3: drivable training labels projected from the map at the robot's ceiling-camera pose.

  derive (--session DIR | --video MP4 --sidecar JSONL) --ceiling DIR --robot DEVICE --out DIR
         [--clock-offset-s S | --clock-offset-s auto] [--near-m 0.15] [--far-m 0.40]
         [--min-spacing-s 0.5] [--split train] [--session-name NAME] [--pitch-deg D]
         [--pitch-sigma-deg 1.0] [--min-line-iou 0.3] [--calibration-root DIR] [--tool-commit SHA]

--session is a D-356 recording (bag/*.mcap: camera/front, odom); --video/--sidecar is the
bag_to_video.py output. --ceiling is a ceiling_record.py recording after ceiling_pose.py detect
(poses.jsonl, calibration.json). Review, canaries and finalize are lane_derived_drivable.py's
sheets / import-verdicts / finalize on the same --out (its verify_dataset knows this schema).
  overlays --out DIR --dest PNG [--count 24]   sample label overlays for a quick look
One command from (robot session, ceiling recording) to review sheets: tools/capture/map_labels_run.sh.

Road raster (map_v2_fleet, 2 mm, cached under data/perception/cache): road = every lane_graph
centreline (segments and parking spur) +- 0.0925 m, i.e. up to the white line centres (D-563
2); line = the STL boundary-line paint; other paint = crosswalk bars; off-road = the rest of the
map. Per usable frame (ceiling_pose.fuse), ground cells forward near_m..far_m of base are
projected into the robot camera (camera_profile: URDF nominal < accepted record, D-397):
road -> 5 drivable only on the robot's own road (4-connected to its map cell without crossing a line,
within own_road_radius_m; D-576 4), other roads -> 0, off-road -> 0, line/other paint -> 255, everything else 255. A cell closer to
a class boundary than the pose margin (sigma_m + forward * sigma_yaw + pitch error moved to the
floor) stays 255, so far rows lose more. Rows above ignore_top are 255. A frame is rejected when
fewer than min_line_px projected line pixels are in view, or the projected line cells and the
observed bright pixels (walls are taller than the lens: a column above a ray that lands in a
wall or off the map sees the wall and is left out) (gray >= stripe_min) of the ground region, both dilated by line_tol_px,
have IoU below min_line_iou (pose or clock error). Labels are not human approval:
annotation_origin map_projected, evaluation_use training_val_only.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import sys
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
for _p in (HERE, REPO / "contracts" / "foundation"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import lane_derived_drivable as ldd  # noqa: E402
from ceiling_pose import FUSE, estimate_clock_offset, fuse, read_calibration  # noqa: E402
from geometry import PROFILE_PATH, Camera  # noqa: E402

SCHEMA = "rosy.map-projected-drivable/1"
ORIGIN = "map_projected"
ADR = "D-563"
BUNDLE = REPO / "middleware" / "perception" / "map" / "map_v2_fleet"
CACHE = REPO / "data" / "perception" / "cache"
HALF_WIDTH_M = 0.0925
OFF, ROAD, LINE, PAINT, WALL = 0, 1, 2, 3, 4
PARAMS = {"near_m": 0.15, "far_m": 0.40, "ignore_top": 110, "stripe_min": ldd.STRIPE_MIN,
          "pitch_sigma_rad": math.radians(1.0), "min_line_iou": 0.3, "line_tol_px": 2, "min_line_px": 30,
          "min_spacing_s": 0.5, "own_road_radius_m": 0.6, "seed_radius_m": 0.03}


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _file_sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def boundary_distance(cls, raster_m):
    """Metres from each cell to the nearest cell of another class."""
    boundary = np.zeros(cls.shape, np.float32)
    for k in np.unique(cls):
        inside = cls == k
        boundary[inside] = cv2.distanceTransform(inside.astype(np.uint8), cv2.DIST_L2, 5)[inside] * raster_m
    return boundary


def road_raster(bundle=BUNDLE, cache_dir=CACHE):
    """{x0, y1, raster_m, cls (OFF/ROAD/LINE/PAINT), boundary_m, lane_graph_sha256, stl_sha256}."""
    import yaml
    bundle = Path(bundle)
    graph_raw = (bundle / "lane_graph.yaml").read_bytes()
    stl = sorted(bundle.glob("260919*.STL"))[0]
    key = _sha(graph_raw + stl.read_bytes() + repr((HALF_WIDTH_M, "walls")).encode())
    cached = Path(cache_dir) / f"road-raster-{key[:16]}.npz" if cache_dir else None
    if cached and cached.is_file():
        with np.load(cached) as z:
            return {k: (z[k].item() if z[k].ndim == 0 else z[k]) for k in z.files}
    spec = importlib.util.spec_from_file_location("map_lane_graph", bundle / "scripts" / "lane_graph.py")
    lane_graph = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(lane_graph)
    scene = lane_graph.load_scene()
    x0, y1, lines, bars = lane_graph.paint_masks(scene)
    r = lane_graph.RASTER_M
    graph = yaml.safe_load(graph_raw)
    road = np.zeros(lines.shape, np.uint8)
    paths = [s["points"] for s in graph["segments"].values()] + [graph["parking"]["points"]]
    for points in paths:
        px = np.array([[(x - x0) / r, (y1 - y) / r] for x, y in points])
        cv2.polylines(road, [np.rint(px * 16).astype(np.int32)], False, 1,
                      thickness=int(round(2 * HALF_WIDTH_M / r)), lineType=cv2.LINE_8, shift=4)
    cls = np.full(lines.shape, OFF, np.uint8)
    cls[road > 0] = ROAD
    cls[bars] = PAINT
    cls[lines] = LINE
    for w in scene.walls:
        a = ((w.cx - w.size_x / 2 - x0) / r, (y1 - w.cy - w.size_y / 2) / r)
        b = ((w.cx + w.size_x / 2 - x0) / r, (y1 - w.cy + w.size_y / 2) / r)
        cv2.rectangle(cls, np.floor(a).astype(int).tolist(), np.ceil(b).astype(int).tolist(), WALL, -1)
    out = {"x0": float(x0), "y1": float(y1), "raster_m": float(r), "cls": cls,
           "boundary_m": boundary_distance(cls, r),
           "lane_graph_sha256": _sha(graph_raw), "stl_sha256": _file_sha(stl)}
    if cached:
        cached.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(cached, **out)
    return out


def robot_camera(device, *, root=None, pitch_rad=None, height_m=None):
    """(Camera, values, source): URDF nominal profile < the device's accepted camera_profile < pitch override."""
    import yaml
    from core_common.calibration_store import resolve
    static = yaml.safe_load(Path(PROFILE_PATH).read_text(encoding="utf-8"))
    values, source = resolve("camera_profile", static, fallback_source=str(PROFILE_PATH.name), robot=device,
                             root=root or str(REPO / "data" / "calibration"),
                             override={"pitch_rad": pitch_rad, "height_m": height_m})
    camera = Camera(int(values["width"]), int(values["height"]), float(values["fx"]), float(values["cx"]),
                    float(values["cy"]), float(values["pitch_rad"]), float(values["height_m"]),
                    float(values.get("x_offset_m", 0.0)))
    return camera, values, source


def ground_grid(camera):
    """(forward, left) floor metres in base for every pixel; nan above the horizon."""
    v, u = np.indices((camera.height, camera.width), dtype=np.float64)
    a, b = (camera.cy - v) / camera.fx, (camera.cx - u) / camera.fx
    s, c = math.sin(camera.pitch_rad), math.cos(camera.pitch_rad)
    den = s - a * c
    with np.errstate(divide="ignore", invalid="ignore"):
        dx = np.where(den > 1e-9, camera.height_m * (c + a * s) / den, np.nan)
    dx[dx <= 0] = np.nan
    return dx + camera.x_offset_m, b * (dx * c + camera.height_m * s)


def own_road(raster, x, y, radius_m, seed_m):
    """(row0, col0, bool window) of the road cells 4-connected to the robot's map cell without
    crossing line/wall/off-road cells, inside a +-radius_m window (D-576 4), or None off-road."""
    rm, cls = raster["raster_m"], raster["cls"]
    row, col = int(round((raster["y1"] - y) / rm)), int(round((x - raster["x0"]) / rm))
    n = int(radius_m / rm)
    r0, c0 = max(row - n, 0), max(col - n, 0)
    window = cls[r0:row + n + 1, c0:col + n + 1]
    road = ((window == ROAD) | (window == PAINT)).astype(np.uint8)
    if not road.size:
        return None
    _, labels = cv2.connectedComponents(road, connectivity=4)
    s = int(seed_m / rm)
    rr, cc = row - r0, col - c0
    near = labels[max(rr - s, 0):rr + s + 1, max(cc - s, 0):cc + s + 1]
    if not (near > 0).any():
        return None
    ys, xs = np.nonzero(near > 0)
    pick = np.argmin((ys + max(rr - s, 0) - rr) ** 2 + (xs + max(cc - s, 0) - cc) ** 2)
    return r0, c0, labels == near[ys[pick], xs[pick]]


def label_frame(image, pose, camera, grid, raster, params=PARAMS):
    """(6-class mask, stats) or (None, stats with 'reason'). pose = fuse() row."""
    p = {**PARAMS, **params}
    forward, left = grid
    with np.errstate(invalid="ignore"):
        region = (forward >= p["near_m"]) & (forward <= p["far_m"])
    c, s = math.cos(pose["yaw"]), math.sin(pose["yaw"])
    wx = pose["x"] + forward * c - left * s
    wy = pose["y"] + forward * s + left * c
    cls_map = raster["cls"]
    with np.errstate(invalid="ignore"):
        row = np.rint((raster["y1"] - wy) / raster["raster_m"])
        col = np.rint((wx - raster["x0"]) / raster["raster_m"])
    in_map = (row >= 0) & (row < cls_map.shape[0]) & (col >= 0) & (col < cls_map.shape[1])
    seen = np.full(region.shape, 255, np.uint8)
    seen[in_map] = cls_map[row[in_map].astype(np.intp), col[in_map].astype(np.intp)]
    # Walls are taller than the lens: in a column, everything above a ray that lands in a wall or
    # beyond the map sees the wall, not the floor.
    blocked = np.isfinite(forward) & (~in_map | (seen == WALL))
    occluded = np.maximum.accumulate(blocked[::-1], axis=0)[::-1]
    region &= ~occluded
    inside = region & in_map
    r, k = row[inside].astype(np.intp), col[inside].astype(np.intp)
    cls = np.full(region.shape, 255, np.uint8)
    cls[inside] = seen[inside]
    near_edge = np.ones(region.shape, bool)
    h = camera.height_m
    margin = (pose["sigma_m"] + forward * pose["sigma_yaw"]
              + (forward ** 2 + h ** 2) / h * p["pitch_sigma_rad"])
    near_edge[inside] = raster["boundary_m"][r, k] < margin[inside]
    own = own_road(raster, pose["x"], pose["y"], p["own_road_radius_m"], p["seed_radius_m"])
    if own is None:
        return None, {"line_px": 0, "line_iou": None, "reason": "robot_off_road"}
    r0, c0, mine = own
    in_own = np.zeros(region.shape, bool)
    wr, wc = r - r0, k - c0
    ok = (wr >= 0) & (wr < mine.shape[0]) & (wc >= 0) & (wc < mine.shape[1])
    in_own.flat[np.flatnonzero(inside)[ok]] = mine[wr[ok], wc[ok]]
    mask = np.full(region.shape, ldd.IGNORE, np.uint8)
    # D-576 4: only the robot's own road is drivable; any other road in view is blocked.
    mask[(cls == ROAD) & ~near_edge & ~in_own] = 0
    mask[(cls == ROAD) & ~near_edge & in_own] = ldd.DRIVABLE
    mask[(cls == OFF) & ~near_edge] = 0
    mask[:p["ignore_top"]] = ldd.IGNORE
    kernel = np.ones((2 * p["line_tol_px"] + 1,) * 2, np.uint8)
    projected = cv2.dilate((cls == LINE).astype(np.uint8), kernel) > 0
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    observed = cv2.dilate((region & (gray >= p["stripe_min"])).astype(np.uint8), kernel) > 0
    projected &= region
    observed &= region
    union = int((projected | observed).sum())
    stats = {"line_px": int((cls == LINE).sum()),
             "line_iou": round(float((projected & observed).sum() / union), 4) if union else None}
    if stats["line_px"] < p["min_line_px"]:
        return None, {**stats, "reason": "no_line_in_view"}
    if stats["line_iou"] < p["min_line_iou"]:
        return None, {**stats, "reason": "line_iou"}
    return mask, stats


def _read_robot(session=None, video=None, sidecar=None):
    """(odometry PoseSeries, frame iterator of (stamp, bgr), input hashes)."""
    import autolabel
    if session is not None:
        files = autolabel._mcap_files(Path(session))
        odom, _ = autolabel.read_mcap_side(files)
        frames = ((t, bgr) for t, bgr, _ in autolabel.mcap_frames(files))
        return odom, frames, {f.name: _file_sha(f) for f in files}
    odom, make, _ = autolabel.read_sidecar(Path(video), Path(sidecar))
    return (odom, ((t, bgr) for t, bgr, _ in make()),
            {Path(video).name: _file_sha(video), Path(sidecar).name: _file_sha(sidecar)})


def derive(out, *, frames, odom, robot_inputs, ceiling, camera, camera_values, camera_source, raster,
           session, split="train", clock_offset_s=0.0, params=PARAMS, fuse_params=FUSE, tool_commit=None):
    out, ceiling = Path(out), Path(ceiling)
    p = {**PARAMS, **params}
    if out.exists():
        raise ValueError("new output directory required")
    tool_commit = ldd._git_commit(tool_commit)
    poses_raw = (ceiling / "poses.jsonl").read_bytes()
    detections = [json.loads(line) for line in poses_raw.decode("utf-8").splitlines() if line.strip()]
    calibration_raw, calibration_doc = read_calibration(ceiling)
    estimated = estimate_clock_offset(detections, odom)
    if clock_offset_s == "auto":
        if estimated is None:
            raise ValueError("clock offset estimate needs motion in both the odometry and the detections")
        clock_offset_s = estimated
    grid = ground_grid(camera)
    (out / "images").mkdir(parents=True)
    (out / "masks").mkdir()
    kept, rejected, last_t, seen = [], {}, None, 0
    for t, bgr in frames:
        seen += 1
        if last_t is not None and t - last_t < p["min_spacing_s"]:
            continue
        if bgr.shape[:2] != (camera.height, camera.width):
            raise ValueError(f"frame {bgr.shape[1]}x{bgr.shape[0]} differs from the camera profile")
        pose = fuse(detections, odom, [t], clock_offset_s=clock_offset_s, params=fuse_params)[0]
        if not pose["usable"]:
            rejected[pose["reason"]] = rejected.get(pose["reason"], 0) + 1
            continue
        mask, stats = label_frame(bgr, pose, camera, grid, raster, p)
        if mask is None:
            rejected[stats["reason"]] = rejected.get(stats["reason"], 0) + 1
            continue
        last_t = t
        name = f"{session}-{len(kept):06d}"
        image_raw = cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, 95])[1].tobytes()
        mask_raw = cv2.imencode(".png", mask)[1].tobytes()
        (out / f"images/{name}.jpg").write_bytes(image_raw)
        (out / f"masks/{name}.png").write_bytes(mask_raw)
        kept.append({"split": split, "session": session, "t": t,
                     "image": f"images/{name}.jpg", "image_sha256": _sha(image_raw),
                     "mask": f"masks/{name}.png", "mask_sha256": _sha(mask_raw),
                     "pose": {k: pose[k] for k in ("x", "y", "yaw", "sigma_m", "sigma_yaw", "anchor_dt")},
                     "line_iou": stats["line_iou"], "drivable_px": int((mask == ldd.DRIVABLE).sum()),
                     "offroad_px": int((mask == 0).sum())})
    anchor = [f["pose"]["anchor_dt"] for f in kept]
    calibration = calibration_doc.get("record") or {}
    doc = {"schema": SCHEMA, "annotation_origin": ORIGIN, "adr": ADR, "evaluation_use": "training_val_only",
           "source": {"session": session, "robot_inputs_sha256": robot_inputs,
                      "ceiling_poses_sha256": _sha(poses_raw), "ceiling_calibration_sha256": _sha(calibration_raw),
                      "ceiling_calibration_revision": calibration.get("calibration_revision"),
                      "map_id": calibration.get("map_id"),
                      "lane_graph_sha256": raster["lane_graph_sha256"], "stl_sha256": raster["stl_sha256"],
                      "camera_profile": {"values": camera_values, "source": camera_source}},
           "tool": {"name": "map_projected_drivable.py", "git_commit": tool_commit},
           "params": {**p, "fuse": dict({**FUSE, **fuse_params}), "half_width_m": HALF_WIDTH_M},
           "pose_stats": {"src": "aruco+odom", "detections": len(detections), "frames_seen": seen,
                          "clock_offset_s": clock_offset_s, "clock_offset_estimate_s": estimated,
                          "anchor_dt_median_s": float(np.median(anchor)) if anchor else None},
           "classes": ldd.CLASSES, "ignore_index": ldd.IGNORE, "skipped_frames": sum(rejected.values()),
           "rejected": rejected, "frames": kept}
    return ldd._write_manifest(out, doc), doc


def overlays(out, dest, count=24, seed=0):
    """A grid of `count` random frames: image | labels (green drivable, cyan not drivable)."""
    out = Path(out)
    frames = ldd.verify_dataset(out)["frames"]
    pick = np.random.default_rng(seed).permutation(len(frames))[:count]
    tiles = []
    for i in sorted(pick):
        f = frames[i]
        image = cv2.imread(str(out / f["image"]))
        mask = cv2.imread(str(out / f["mask"]), cv2.IMREAD_UNCHANGED)
        tiles.append(ldd._tile(image, mask, f"{Path(f['image']).stem[-6:]} iou {f['line_iou']}", 0))
    if not tiles:
        raise ValueError("no frames")
    tiles += [np.full_like(tiles[0], 255)] * (-len(tiles) % 4)
    grid = np.vstack([np.hstack(tiles[i:i + 4]) for i in range(0, len(tiles), 4)])
    cv2.imwrite(str(dest), grid)
    return len(pick)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("derive")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--session", type=Path)
    src.add_argument("--video", type=Path)
    p.add_argument("--sidecar", type=Path)
    p.add_argument("--ceiling", type=Path, required=True)
    p.add_argument("--robot", required=True, help="device name of the calibration store")
    p.add_argument("--calibration-root")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--session-name")
    p.add_argument("--split", default="train", choices=("train", "val", "test"))
    p.add_argument("--clock-offset-s", default="0", help="robot - site clock (s), or 'auto'")
    p.add_argument("--pitch-deg", type=float, help="session camera pitch override")
    p.add_argument("--height-m", type=float, help="session camera height override")
    p.add_argument("--pitch-sigma-deg", type=float, default=math.degrees(PARAMS["pitch_sigma_rad"]))
    for key in ("near_m", "far_m", "min_line_iou", "min_spacing_s", "own_road_radius_m", "seed_radius_m"):
        p.add_argument("--" + key.replace("_", "-"), type=float, default=PARAMS[key])
    for key in ("ignore_top", "stripe_min", "line_tol_px", "min_line_px"):
        p.add_argument("--" + key.replace("_", "-"), type=int, default=PARAMS[key])
    for key in FUSE:
        p.add_argument("--" + key.replace("_", "-"), type=float, default=FUSE[key])
    p.add_argument("--tool-commit")
    p = sub.add_parser("overlays")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--dest", type=Path, required=True)
    p.add_argument("--count", type=int, default=24)
    args = parser.parse_args(argv)
    if args.command == "overlays":
        print(json.dumps({"tiles": overlays(args.out, args.dest, args.count)}))
        return 0
    if args.video is not None and args.sidecar is None:
        parser.error("--video needs --sidecar")
    camera, values, source = robot_camera(args.robot, root=args.calibration_root,
                                          pitch_rad=None if args.pitch_deg is None else math.radians(args.pitch_deg),
                                          height_m=args.height_m)
    odom, frames, inputs = _read_robot(args.session, args.video, args.sidecar)
    params = {key: getattr(args, key) for key in PARAMS if key != "pitch_sigma_rad"}
    params["pitch_sigma_rad"] = math.radians(args.pitch_sigma_deg)
    offset = args.clock_offset_s if args.clock_offset_s == "auto" else float(args.clock_offset_s)
    digest, doc = derive(args.out, frames=frames, odom=odom, robot_inputs=inputs, ceiling=args.ceiling,
                         camera=camera, camera_values=values, camera_source=source, raster=road_raster(),
                         session=args.session_name or (args.session or args.video).stem, split=args.split,
                         clock_offset_s=offset, params=params,
                         fuse_params={key: getattr(args, key) for key in FUSE}, tool_commit=args.tool_commit)
    print(json.dumps({"manifest_sha256": digest, "frames": len(doc["frames"]), "rejected": doc["rejected"],
                      "pose_stats": doc["pose_stats"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
