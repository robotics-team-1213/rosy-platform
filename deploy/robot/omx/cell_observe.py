"""Where the box is, seen by the cell's cameras (D-872): per-surface detection, fixed cameras fused by
their maps' errors, the wrist check right above the box, the frames decisions used, and where a box at an
arm point would show (for keeping placements on a surface's flat zone). cell_pipeline acts on these."""
from __future__ import annotations

import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cell_calibration as cal  # noqa: E402
from cell_scene import scene_check  # noqa: E402

def wrap90(deg: float) -> float:
    """A square box looks the same every 90 degrees: the smallest turn, in (-45, 45]."""
    return (deg + 45) % 90 - 45 if (deg + 45) % 90 else 45.0


def see(img, profile: dict, site: str) -> dict:
    """The box on one surface: the tray's colour rule (with yaw), or on the dark belt place_check's rule."""
    import cell_perception as cp

    if "hsv_min" in profile["sites"].get(site, {}):
        found = cp.place_check(img, profile, site)
        return {**found, "yaw": 0.0} if found.get("found") else {"found": False}
    return cp.top_box(img, profile, roi=profile["sites"].get(site, {}).get("search"))


KEEP = {"dir": None}  # set by main()/run(): where decision frames are written


def keep(name: str, img):
    """Write the frame a decision used next to the receipts; returns its path (None when not keeping)."""
    if KEEP["dir"] is None or img is None:
        return None
    import cv2

    KEEP["dir"].mkdir(parents=True, exist_ok=True)
    path = KEEP["dir"] / f"{datetime.now(timezone.utc):%Y%m%dT%H%M%S%f}-{name}.jpg"
    cv2.imwrite(str(path), img, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return str(path)


def fixed_cameras(config: dict) -> list:
    """The cell's fixed cameras, the top one first; each has its own map per surface. A rosy cam, when
    configured, is calibrated in the same pass and carries on when the top camera cannot see the box."""
    return [name for name in config["cameras"] if name != "wrist"]


def record_key(site: str, camera: str) -> str:
    return site if camera == "top" else f"{site}@{camera}"


def maps(calibration: dict, site: str, camera: str) -> list:
    """The maps that turn a `camera` pixel on `site` into arm x, y, best first: a local jaw map fitted around
    where the box was seen, the fine box map, the coarse jaw map (only the top camera marks the jaws)."""
    keys = [f"{site}~local", site, f"{site}~coarse"] if camera == "top" else [record_key(site, camera)]
    return [(key, calibration["sites"][key]) for key in keys if key in calibration["sites"]]


def outside_mm(record: dict, arm) -> float | None:
    """How far `arm` lies outside the arm points the map was fitted on (0 inside): beyond them it only
    extrapolates. None for a map that kept no points."""
    points = [p["arm_m"] for p in record.get("points") or []]
    if not points:
        return None
    xs, ys = zip(*points)
    dx, dy = max(min(xs) - arm[0], 0.0, arm[0] - max(xs)), max(min(ys) - arm[1], 0.0, arm[1] - max(ys))
    return round(1000 * math.hypot(dx, dy), 1)


def load_maps(path, config: dict) -> dict:
    """The calibration file, with a site-local map kept as its own file (sites.<site>.local_map, one record
    of the calibration form) as `<site>~local` unless the file already has a newer one from a re-map."""
    calibration = cal.load(path) if Path(path).exists() else {"schema": cal.SCHEMA, "sites": {}}
    for site, spec in config["sites"].items():
        local = Path(spec["local_map"]).expanduser() if spec.get("local_map") else None
        if local is not None and local.exists() and f"{site}~local" not in calibration["sites"]:
            record = json.loads(local.read_text())
            if not isinstance(record, dict) or len(record.get("homography") or []) != 3:
                raise SystemExit(f"{local}: a local map needs a 3x3 homography")
            calibration["sites"][f"{site}~local"] = record
    return calibration


def locate(cell, config: dict, calibration: dict, site: str) -> dict:
    """Every fixed camera with a map for `site` estimates the box, weighted by its map's leave-one-out
    error. One camera that cannot see the box does not stop the others. Each camera uses the first of its
    maps whose fitted points the box lies within (map_extent_mm), else its best map, marked as outside."""
    estimates, missing = [], []
    limit = config.get("map_extent_mm", 10.0)
    for camera in fixed_cameras(config):
        options = maps(calibration, site, camera)
        if not options:
            missing.append(f"{camera}: no map")
            continue
        img = cell.frame(camera)
        box = see(img, config["profiles"][camera], site)
        frame = keep(f"locate-{site}-{camera}", img)
        if not box.get("found"):
            missing.append(f"{camera}: box not seen")
            continue
        fits = []
        for key, record in options:
            pixel = (box["cx"], box["cy"])
            if "z_view" in record:  # a jaw map: bring the box pixel to the height the map was fitted at
                pixel = cal.parallax(pixel, config["sites"][site]["z"], record["z_view"], config["cameras"][camera])
            arm = cal.to_arm(record["homography"], pixel)
            fits.append((key, record, arm, outside_mm(record, arm)))
        key, record, (x, y), outside = next((f for f in fits if (f[3] or 0) <= limit), fits[0])
        turn = cal.yaw_sign(record["homography"], (box["cx"], box["cy"])) * wrap90(box["yaw"])
        sigma = max(0.5, (record.get("loo_error_mm") or {}).get("mean", 5.0))
        estimates.append({"camera": camera, "pixel": [box["cx"], box["cy"]], "arm_m": [x, y], "turn": turn,
                          "sigma_mm": sigma, "frame": frame, "map": key, "outside_mm": outside,
                          "residual_mm": (record.get("loo_error_mm") or {}).get("max")})
    if not estimates:
        return {"found": False, "error": "; ".join(missing) or "no fixed camera configured"}
    weights = [1 / e["sigma_mm"] ** 2 for e in estimates]

    def mean(values):
        return sum(w * v for w, v in zip(weights, values)) / sum(weights)

    x, y = mean([e["arm_m"][0] for e in estimates]), mean([e["arm_m"][1] for e in estimates])
    turn = mean([e["turn"] for e in estimates])
    return {"found": True, "observed": datetime.now(timezone.utc).isoformat(), "arm_m": [round(x, 4), round(y, 4)],
            "turn_deg": round(turn, 1),
            "yaw_deg": round(config["sites"][site]["yaw_deg"] + turn, 1),
            "sigma_mm": round(1 / math.sqrt(sum(weights)), 2), "estimates": estimates, "missing": missing}


def map_check(config: dict, found: dict, calibration: dict | None = None) -> str | None:
    """Why the map that put this box in arm x, y should not be trusted for a grasp here, or None: the box
    lies outside every map's fitted points by more than map_extent_mm, or the map's leave-one-out error
    is above map_residual_mm. With `calibration`, also a scene that changed since the map or detection (cell_scene)."""
    for e in found.get("estimates", []):
        if (e.get("outside_mm") or 0) > config.get("map_extent_mm", 10.0):
            return f"{e['camera']}: box {e['outside_mm']} mm outside the points of map {e['map']}"
        if (e.get("residual_mm") or 0) > config.get("map_residual_mm", 10.0):
            return f"{e['camera']}: map {e['map']} leave-one-out error {e['residual_mm']} mm"
    return scene_check(config, calibration, found) if calibration else None


def detection(found: dict) -> dict:
    """What a case row keeps of one detection: where the box was seen and through which map."""
    return {"found": found["found"], "arm_m": found.get("arm_m"), "error": found.get("error"),
            "maps": [{k: e.get(k) for k in ("camera", "pixel", "map", "outside_mm", "residual_mm")}
                     for e in found.get("estimates", [])]}


def hover_check(cell, config: dict, calibration: dict, site: str) -> dict:
    """Right above the box, before descending: does the wrist camera see the box where it sat in the
    hovers over boxes placed at known points (learned in calibration)? Unknown until learned."""
    import cell_perception as cp

    img = cell.frame("wrist")
    box = cp.wrist_box(img, config["profiles"]["top"])
    seen = {k: box.get(k) for k in ("found", "cx", "cy", "area", "tilt")}
    seen["frame"] = keep(f"hover-{site}-wrist", img)
    learned = (calibration["sites"].get(site) or {}).get("wrist")
    if not box.get("found"):
        return {"box_found": False, "aligned": False, "wrist": seen}
    if learned is None:
        return {"box_found": True, "aligned": None, "wrist": seen}
    off = math.dist((box["cx"], box["cy"]), (learned["cx"], learned["cy"]))
    return {"box_found": True, "aligned": off <= learned["spread_px"], "off_px": round(off, 1), "wrist": seen}


def predicted_pixel(config: dict, calibration: dict, site: str, point):
    """Where a box at arm `point` on `site` would show in the top view, from the best map there is."""
    record = calibration["sites"].get(record_key(site, "top")) or calibration["sites"].get(f"{site}~coarse")
    if record is None:
        return None
    pixel = cal.to_pixel(record["homography"], point)
    if "z_view" in record:  # coarse: fitted at the jaws' viewing height, bring it down to the box
        pixel = cal.parallax(pixel, record["z_view"], config["sites"][site]["z"], config["cameras"]["top"])
    return pixel


def on_flat(config: dict, calibration: dict, site: str, point) -> bool | None:
    """Would the whole box sit on the flat part of the surface (sites.<site>.flat_px, shrunk by half a box)?
    2026-10-25: a grid point 15 mm toward the Pinky put the box's edge over the Pinky frame; the descent hit
    it and the guard stopped with the box in the jaws. None when there is no zone or no map to check with."""
    zone, pixel = config["sites"][site].get("flat_px"), predicted_pixel(config, calibration, site, point)
    if zone is None or pixel is None:
        return None
    half = config["sites"][site].get("box_half_px", 20)
    return zone[0] + half <= pixel[0] <= zone[2] - half and zone[1] + half <= pixel[1] <= zone[3] - half


def grid_points(config: dict, calibration: dict, site: str) -> list:
    """The calibration grid, centred on the flat zone when a map can find its centre, else on the start."""
    s, center = config["sites"][site], tuple(config["sites"][site]["start"])
    record = calibration["sites"].get(record_key(site, "top")) or calibration["sites"].get(f"{site}~coarse")
    if s.get("flat_px") and record is not None:
        z = s["flat_px"]
        pixel = ((z[0] + z[2]) / 2, (z[1] + z[3]) / 2)
        if "z_view" in record:
            pixel = cal.parallax(pixel, s["z"], record["z_view"], config["cameras"]["top"])
        x, y = cal.to_arm(record["homography"], pixel)
        center = (round(x, 4), round(y, 4))
    return cal.grid(center, s["grid_spacing_m"], s.get("grid_n", 3))
