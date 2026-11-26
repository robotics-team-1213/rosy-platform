"""Observe the S5 ship and fan tray in the registered top frame (pixels, then arm-plane estimates)."""
from functools import lru_cache
import itertools
import json
from pathlib import Path

import cv2
import numpy as np


@lru_cache(maxsize=1)
def _hull_samples():
    # R08 CAD is a search prior. Only actual image edges are returned as observations.
    model = json.loads(Path(__file__).with_name("ship-r08-outline.json").read_bytes())
    polygon = np.array(model["hull_mm"], dtype=float)
    return np.concatenate([np.linspace(a, b, max(2, round(np.linalg.norm(b-a)/3)), endpoint=False)
                           for a, b in zip(polygon, np.roll(polygon, -1, axis=0))])


def _crosses(gray):
    radius = max(3, round(5 * gray.shape[1] / 640))
    size = 4 * radius - 1
    centre = size // 2
    template = np.zeros((size, size), np.uint8)
    for dx, dy in ((radius, 0), (0, radius)):
        cv2.line(template, (centre-dx, centre-dy), (centre+dx, centre+dy), 230, max(1, round(radius*.4)))
    score = cv2.matchTemplate(gray, cv2.GaussianBlur(template, (3, 3), .6), cv2.TM_CCOEFF_NORMED)
    y, x = np.where((score == cv2.dilate(score, np.ones((size, size), np.uint8))) & (score >= .78))
    return np.column_stack((x + centre, y + centre))


def _deck_and_berth(frame):
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    marks = _crosses(gray)
    if not 4 <= len(marks) <= 16:
        return None
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    # Match the sky-blue printed deck, distinct from cargo and the dark cross supports.
    mask = cv2.inRange(hsv, (89, 55, 140), (111, 161, 255))
    contours = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0]
    choices = []
    for contour in contours:
        if cv2.contourArea(contour) < gray.size * .018:
            continue
        x, y, width, height = cv2.boundingRect(contour)
        if not 1.6 < height/width < 3.4:
            continue
        sides = []
        for edge in (x, x+width):
            near = marks[(abs(marks[:,0]-edge) < .24*width) & (marks[:,1]>y) & (marks[:,1]<y+.6*height)]
            sides.append([(a,b) for a,b in itertools.combinations(sorted(near.tolist(), key=lambda q:q[1]),2)
                          if .25*width < b[1]-a[1] < .65*width and abs(b[0]-a[0]) < width*.16])
        for left,right in itertools.product(*sides):
            a,b,c,d = np.array([left[0], left[1], right[0], right[1]],dtype=float)
            if (max(a[0],b[0]) >= x or min(c[0],d[0]) <= x+width-1
                    or max(abs(a[1]-c[1]),abs(b[1]-d[1])) > .20*width):
                continue
            choices.append((cv2.convexHull(contour)[:,0], np.array([a,c,b,d])))
    return choices[0] if len(choices)==1 else None


def _ship(frame):
    found = _deck_and_berth(frame)
    if found is None:
        return {"status":"unverified","reason":"no_unique_deck_between_four_berth_crosses"}
    deck, crosses = found
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    height,width = gray.shape
    # Keep subpixel search and correspondence in pixels. Recovery never uses an invisible CAD corner.
    edges = cv2.Canny(cv2.GaussianBlur(gray,(3,3),.65),18,55)
    dist = cv2.distanceTransform(255-edges,cv2.DIST_L2,5)
    pts = _hull_samples()
    axis = (crosses[1]-crosses[0]+crosses[3]-crosses[2]); axis /= np.linalg.norm(axis)
    forward = np.array([-axis[1],axis[0]])
    across, along = deck@axis, deck@forward
    init = np.array([(across.min()+across.max())/2, along.min(), np.ptp(across)/130, np.ptp(across)/130, 0.0])
    def transform(par):
        u, v, sx, sy, rot = par
        c,s=np.cos(rot),np.sin(rot)
        return (u*axis + v*forward + pts[:,1,None]*sx*(c*axis+s*forward)
                + pts[:,0,None]*sy*(-s*axis+c*forward))
    def loss(par):
        pixel=np.rint(transform(par)).astype(int)
        inside=(pixel[:,0]>=0)&(pixel[:,0]<width)&(pixel[:,1]>=0)&(pixel[:,1]<height)
        if np.mean(inside)<.87:return 1e4
        z=dist[pixel[inside,1],pixel[inside,0]]
        return float(np.minimum(z,7).mean()+2*(1-inside.mean()))
    par=init.copy()
    # Coordinate descent bounded by the measured deck scale; re-evaluate against the whole perimeter.
    for steps in ((2.0,2.0,.024,.04,.015),(1.,1.,.012,.02,.008),(.5,.5,.006,.01,.004)):
        for _ in range(4):
            changed=False
            for i,step in enumerate(steps):
                best=loss(par);winner=par
                for sign in (-1,1):
                    q=par.copy();q[i]+=step*sign
                    if not (.90*init[2]<=q[2]<=1.14*init[2] and .9*init[3]<=q[3]<=1.22*init[3]): continue
                    score=loss(q)
                    if score+1e-5<best:best,winner=score,q
                if winner is not par:changed=True;par=winner
            if not changed:break
    expected=transform(par)
    hits=[]
    for i,p in enumerate(expected):
        tangent=expected[(i+1)%len(expected)]-expected[i-1]
        normal=np.array([-tangent[1],tangent[0]])/max(np.linalg.norm(tangent),1e-8)
        ray=np.rint(p+np.arange(-3,4)[:,None]*normal).astype(int)
        valid=(ray[:,0]>=1)&(ray[:,0]<width-1)&(ray[:,1]>=1)&(ray[:,1]<height-1)
        candidates=ray[valid];candidates=candidates[edges[candidates[:,1],candidates[:,0]]>0]
        hits.append(min(candidates,key=lambda q:np.linalg.norm(q-p)).tolist() if len(candidates) else None)
    fraction=sum(q is not None for q in hits)/len(hits)
    if fraction<.65:
        return {"status":"unverified","reason":"insufficient_hull_edge_support","supported_fraction":round(fraction,3)}
    clipping=[name for name,flag in (("left",expected[:,0].min()<1),("right",expected[:,0].max()>width-2),
              ("top",expected[:,1].min()<1),("bottom",expected[:,1].max()>height-2)) if flag]
    segments=[]
    for valid,g in itertools.groupby(hits,key=lambda p:p is not None):
        run=list(g)
        if valid and len(run)>=3:
            segments.append(cv2.approxPolyDP(np.int32(run),.9,False)[:,0].tolist())
    complete=not clipping and all(q is not None for q in hits)
    deck_pts=cv2.approxPolyDP(deck,1.5,True)[:,0].tolist()
    return {"geometry_role":"ship_hull","status":"observed" if complete else "partial",
            "touches_frame":bool(clipping),"clipping_edges":clipping,"outline_px":hits if complete else [],
            "segments":[{"kind":"image_edge","points_px":s} for s in segments],
            "berth_crosses_px":crosses.astype(int).tolist(),"deck_contour_px":deck_pts,
            "supported_fraction":round(fraction,3),"uncertainty":{"edge_search_radius_px":3,"model_edge_residual_px":round(loss(par),2)},
            "model":"r08","model_outline_px":cv2.approxPolyDP(expected.astype(np.float32),1,True)[:,0].round(2).tolist()}



def _plane_point(record, camera, pixel, plane_z):
    import cell_calibration as cal
    from cell_map_fit import predict_sigma_mm

    fit_z = record.get("z_view")
    if not record.get("homography") or plane_z is None or fit_z is None:
        return None
    center = (record.get("camera_in_base") or {}).get("t")
    if center is not None:
        cx, cy, cz = map(float, center)
        if cz <= max(fit_z, plane_z):
            return None
        fit_pixel = pixel
        x, y = cal.to_arm(record["homography"], fit_pixel)
        scale = (cz - plane_z) / (cz - fit_z)
        xy = (cx + (x - cx) * scale, cy + (y - cy) * scale)
    else:
        if camera.get("height_m") is None or not (camera.get("center_px") or camera.get("K")):
            return None
        fit_pixel = cal.parallax(pixel, plane_z, fit_z, camera)
        xy = cal.to_arm(record["homography"], fit_pixel)
    if not np.isfinite(xy).all():
        return None
    sigma = predict_sigma_mm(record, fit_pixel)
    return {"xy_m": [round(float(x), 5) for x in xy], "map_sigma_mm": round(float(sigma), 2) if np.isfinite(sigma) else None}


def _projection(observation, name, config, calibration):
    from cell_site_target import resolve_cell_ab_site
    import cell_params as prm

    site = config["sites"][name]
    record = (calibration.get("sites") or {}).get(name, {})
    camera = (config.get("cameras") or {}).get("top", {})
    plane = site.get("surface_z")
    observation.update(arm_id=config["arm_id"], plane_z_m=plane, fit_plane_z_m=record.get("z_view"),
                       plane_source="configured_site_surface", outline_arm_xy_m=None, targets=[])
    observation.setdefault("uncertainty", {})["projection_limit"] = "Rim height relative to the configured surface is unmeasured."
    for label, slot in observation.get("placement_slots", {}).get("slots", {}).items():
        site_ref = resolve_cell_ab_site(f"tmp-a-{label[1:]}", tier=1)
        slot["slot_id"] = site_ref["slot_id"] if site_ref else None
        slot["plane_estimate"] = _plane_point(record, camera, slot["center_px"], plane)
        slot["map_sigma_limit_mm"] = float(prm.get(config.get("params"), "verify.map_sigma_max_mm"))
    if observation.get("status") == "observed" and observation.get("outline_px"):
        positions = [_plane_point(record, camera, px, plane) for px in observation["outline_px"]]
        if all(positions):
            observation["outline_arm_xy_m"] = [p["xy_m"] for p in positions]
    for slot, roi in (config.get("zone_rois") or {}).get("top", {}).items():
        canonical = resolve_cell_ab_site(slot) or resolve_cell_ab_site(slot + "-l0")
        if not canonical or config["arm_id"] not in canonical["arms"] or len(roi) != 4:
            continue
        base = canonical["base_site"]
        belongs = (name == "pallet" and base.startswith("ship-")) or (name == "temp_plate_a" and base.startswith("tmp-a-"))
        if belongs:
            x0, y0, x1, y1 = roi
            center = [(x0 + x1) / 2, (y0 + y1) / 2]
            observation["targets"].append({"slot": slot, "geometry_role": "registered_roi_center",
                "center_px": center, "plane_estimate": _plane_point(record, camera, center, plane)})


def inspect_fixtures(frame, config, calibration):
    from cell_tray_outline import tray_outline

    arm = config.get("arm_id")
    sites = config.get("sites") or {}
    fixtures = {}
    if arm in ("arm_a", "arm_b") and "pallet" in sites:
        fixtures["pallet"] = _ship(frame)
    if arm == "arm_a" and "temp_plate_a" in sites:
        roi = sites["temp_plate_a"].get("auto_roi")
        if roi is not None and len(roi) == 4:
            x0, y0, x1, y1 = roi
            # A saved ROI just inside the frame border can hide physical clipping.
            height, width = frame.shape[:2]
            dx, dy = (x1 - x0) * 0.1, (y1 - y0) * 0.1
            roi = (0 if x0 < dx else x0, 0 if y0 < dy else y0,
                   width if width - x1 < dx else x1, height if height - y1 < dy else y1)
        fixtures["temp_plate_a"] = tray_outline(frame, roi)
        if config.get("work_dir"):
            from cell_tray_archive import registered_slots
            directory = Path(config["work_dir"]).expanduser() / "fixture-observations" / "temp_plate_a"
            fixtures["temp_plate_a"]["placement_slots"] = registered_slots(frame, directory)
    for name, obs in fixtures.items():
        obs.setdefault("geometry_role", "ship_hull" if name == "pallet" else "visible_tray_material_edges")
        obs.setdefault("outline_px", [])
        obs.setdefault("clipping_edges", [])
        obs.setdefault("touches_frame", None)
        _projection(obs, name, config, calibration)
    return {"fixtures": fixtures}
