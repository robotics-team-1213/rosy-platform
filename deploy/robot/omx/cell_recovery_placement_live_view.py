"""Check the entire proposed load footprint in the calibrated overhead view."""
from itertools import product
import math

import cv2
import numpy as np

import cell_params
from cell_calibration import parallax
from cell_objects import foreground
from cell_observe import predicted_pixel
from cell_place_fit import footprint
from cell_preflight import camera_shift_px
from grasp_planner import BODY_MARGIN_M, norm_to_rad
from omx_adapter.swept_volume import capsules


def verify_arrival(config, calibration, name, cargo, catalog, ref, before, after, cell):
    from cell_auto_pick_plan import observe
    from cell_envelope import verification_tolerance
    from cell_place_fit import why_not

    site = config["sites"][name]
    fine = calibration.get("sites", {}).get(name)
    if not isinstance(fine, dict) or not fine.get("homography") or fine.get("coarse"):
        return {"verified": False, "reason": "fine_destination_map_missing"}
    if not all(camera_aligned(ref, frame["image"], config["params"]) for frame in (before, after)):
        return {"verified": False, "reason": "camera_alignment_changed"}
    tolerance = verification_tolerance(config)
    target = site["place"]
    arrivals = []
    for frame in (before, after):
        _, _, objects, error = observe(cell, config, calibration, name, site["auto_roi"], catalog, image=frame["image"])
        if error:
            return {"verified": False, "reason": "destination_observation_unavailable"}
        near = []
        for obj in objects:
            center = np.asarray(obj["centre_mm"], dtype=float) / 1000
            raw = np.asarray(obj["raw_m"], dtype=float)
            if any(p.shape != (2,) or not np.isfinite(p).all() for p in (center, raw)):
                return {"verified": False, "reason": "object_position_unknown"}
            if min(math.dist(center, target), math.dist(raw, target)) * 1000 <= tolerance:
                near.append(obj)
        if frame is before and near:
            return {"verified": False, "reason": "destination_previously_occupied"}
        if frame is after:
            arrivals = near
    if len(arrivals) != 1 or arrivals[0].get("matched") is not True or arrivals[0].get("object") != cargo["object_id"]:
        return {"verified": False, "reason": "arrival_not_unique"}
    obj = arrivals[0]
    center = [v / 1000 for v in obj["centre_mm"]]
    if max(math.dist(center, target), math.dist(obj["raw_m"], target)) * 1000 > tolerance:
        return {"verified": False, "reason": "outside_destination"}
    points = footprint(center, obj["long_axis_deg"], max(obj["length_mm"], cargo["length_mm"]),
                       max(obj["width_mm"], cargo["width_mm"]))
    if why_not(points, lambda point: predicted_pixel(config, calibration, name, point), site["surface_px"]):
        return {"verified": False, "reason": "arrival_outside_support"}
    return {"verified": True, "inside": True, "object_id": cargo["object_id"], "observed_xy_m": center, "target_xy_m": target,
            "tolerance_mm": tolerance}


def camera_aligned(ref, image, params):
    if image.shape != ref.shape:
        return False
    shift = camera_shift_px(cv2.cvtColor(ref, cv2.COLOR_BGR2GRAY), cv2.cvtColor(image, cv2.COLOR_BGR2GRAY))
    return shift.get("ok") is True and shift.get("max_px", math.inf) <= cell_params.get(params, "calibrate.max_shift_px")


def empty_surface(config, calibration, site_name, cargo, entry, kin, joints, image):
    site, camera = config["sites"][site_name], config["cameras"]["top"]
    # A uniformly covered surface can match the median of the live image.
    colours = site.get("surface_lab")
    if colours is None:
        return "surface_colour_unmeasured"
    colours = np.atleast_2d(np.asarray(colours, dtype=float))
    if (colours.ndim != 2 or colours.shape[1] != 3 or not colours.size or not np.isfinite(colours).all()
            or (colours < 0).any() or (colours > 255).any()):
        return "surface_colour_unmeasured"
    roi = site["auto_roi"]
    if not (0 <= roi[0] < roi[2] <= image.shape[1] and 0 <= roi[1] < roi[3] <= image.shape[0]):
        return "surface_outside_frame"
    margin = cell_params.get(config["params"], "place.margin_mm")
    points = footprint(site["place"], site["yaw_deg"] + cargo["held_axis_deg"],
                       cargo["length_mm"] + 2 * margin, cargo["width_mm"] + 2 * margin)
    def project(point, z):
        xy = predicted_pixel(config, calibration, site_name, point)
        if xy is None or not isinstance(camera, dict) or not camera.get("height_m") or z >= camera["height_m"]:
            return None
        if camera.get("center_px") is None and (camera.get("K") is None or camera.get("normal") is None):
            return None
        px = parallax(xy, site["z"], z, camera)
        if px is None or not np.all(np.isfinite(px)):
            return None
        return np.asarray(px, dtype=np.float32)

    pixels = [project(p, site["surface_z"]) for p in points]
    if any(p is None or not (roi[0] <= round(float(p[0])) < roi[2] and roi[1] <= round(float(p[1])) < roi[3])
           for p in pixels):
        return "footprint_outside_camera"
    target = cv2.convexHull(np.asarray(pixels, dtype=np.float32).reshape(-1, 2))
    shape = (roi[3] - roi[1], roi[2] - roi[0])
    offset = np.array(roi[:2])
    target_mask = np.zeros(shape, np.uint8)
    cv2.fillConvexPoly(target_mask, np.rint(target.reshape(-1, 2) - offset).astype(np.int32), 1)
    surface = np.zeros(shape, np.uint8)
    cv2.fillPoly(surface, [np.rint(np.asarray(site["surface_px"]) - offset).astype(np.int32)], 1)
    if not target_mask.any() or (target_mask & (surface == 0)).any():
        return "footprint_outside_support"
    # A region behind the arm/held item cannot establish an empty surface even if it matches the floor's colour.
    radius = max(math.hypot(cargo["length_mm"], cargo["width_mm"]) / 2000,
                 entry["top_height_mm"] / 1000 - cargo["grasp_above_base_m"])
    links = capsules(kin, [norm_to_rad(v) for v in joints[:5]], fingertip_m=0, gripper_radius_m=BODY_MARGIN_M,
                     item=(cargo["grasp_above_base_m"], radius))
    for a, b, r in links:
        corners = [project((x + dx, y + dy), z + dz) for x, y, z in (a, b)
                   for dx, dy, dz in product((-r, r), repeat=3)]
        if any(p is None for p in corners):
            return "arm_projection_unknown"
        hull = cv2.convexHull(np.asarray(corners, dtype=np.float32).reshape(-1, 2))
        if cv2.intersectConvexConvex(target, hull)[0] > 0:
            return "target_occluded"
    mask = foreground(image, roi, params=config["params"], surface_px=site["surface_px"],
                      surface_lab=colours)
    return "target_occupied" if ((mask != 0) & (target_mask != 0)).any() else None
