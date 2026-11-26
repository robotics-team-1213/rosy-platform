"""Locate visible portions of the cool-plastic A tray inside a registered image ROI."""
import cv2
import numpy as np


def tray_outline(frame_bgr, roi_xyxy):
    out = dict(status="unverified", geometry_role="visible_tray_material_edges",
               outline_px=[], outline_arm_xy_m=None, plane_z_m=None, segments=[],
               touches_frame=False, clipping_edges=[], roi_clipping_edges=[],
               pad_centers_px=[], lane_centerlines_px=[],
               uncertainty={"units": "px", "method": "edge fit residual plus material transition allowance"},
               reason="insufficient visible tray evidence")
    if frame_bgr is None or frame_bgr.ndim != 3 or frame_bgr.shape[2] != 3 or roi_xyxy is None:
        return out
    height, width = frame_bgr.shape[:2]
    x0, y0, x1, y1 = map(int, roi_xyxy)
    x0, y0, x1, y1 = max(x0, 0), max(y0, 0), min(x1, width), min(y1, height)
    if x1-x0 < 24 or y1-y0 < 24:
        return out
    image = frame_bgr[y0:y1, x0:x1]
    blue, green, red = image.astype(np.int16).transpose(2, 0, 1)
    material = ((blue > red+8) & (green > red+4) & (blue > 125) & (green > 115)).astype(np.uint8)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(material)
    if n < 2:
        return out
    rank = np.argsort(stats[1:, -1])[::-1]+1
    label = rank[0]
    area = stats[label, -1]
    if area < 200 or area > material.size*.65 or (len(rank)>1 and stats[rank[1], -1]>.50*area):
        return out
    component = (labels == label).astype(np.uint8)
    contour = max(cv2.findContours(component, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)[0], key=cv2.contourArea)
    contour = contour.reshape(-1, 2)
    corners = cv2.approxPolyDP(contour.reshape(-1,1,2), 2.3, True).reshape(-1, 2)
    edges = []
    for index, point in enumerate(corners):
        end = corners[(index+1)%len(corners)]
        delta = end-point
        length = np.linalg.norm(delta)
        if length < 12:
            continue
        # An image or ROI border can cut through the material.
        if any(point[j] == end[j] and point[j] in (0, component.shape[1-j]-1) for j in (0, 1)):
            continue
        start_i = int(np.flatnonzero(np.all(contour==point, axis=1))[0])
        end_i = int(np.flatnonzero(np.all(contour==end, axis=1))[0])
        points = contour[start_i:end_i+1] if end_i>start_i else np.vstack((contour[start_i:], contour[:end_i+1]))
        tangent = delta / length
        # OpenCV external contours have the exterior on the right in image coordinates.
        normal = np.array([-tangent[1], tangent[0]])
        probe = np.rint(points + normal*6).astype(int)
        inside = (probe[:,0]>=0)&(probe[:,0]<component.shape[1])&(probe[:,1]>=0)&(probe[:,1]<component.shape[0])
        probe = probe[inside]
        if len(probe)<6:
            continue
        b,g,r = image[probe[:,1],probe[:,0]].astype(int).T
        # Ochre tabletop is redder than the yellow cargo and less red than orange cargo.
        tabletop = (r-g>=16)&(r-g<=65)&(g-b>28)&(r>110)
        backed = float(np.mean(tabletop))
        # The block in lane 1 is yellow and can match the table hue.
        # A table interface also needs a free sight line out of the fixture.
        outward_axis = int(np.argmax(np.abs(normal)))
        if outward_axis == 0:
            exposed = [not (component[y, :x].any() if normal[0]<0 else component[y, x+1:].any()) for x,y in points]
        else:
            exposed = [not (component[:y, x].any() if normal[1]<0 else component[y+1:, x].any()) for x,y in points]
        exposed_fraction = float(np.mean(exposed))
        # The fixture opens toward the bottom. A downward-facing material
        # edge can be the top edge of cargo inside that opening.
        outer_facing = outward_axis == 0 or normal[1] < 0
        kind = "rim_table_boundary" if outer_facing and backed>=.7 and exposed_fraction>=.85 else "visible_plastic_boundary"
        error = float(np.max(np.abs((points-point)@normal)))
        # Bound camera blur/material-threshold uncertainty separately from line-fit residual.
        edges.append(dict(kind=kind, points_px=(np.array([point,end])+[x0,y0]).tolist(),
                          uncertainty_px=round(error+2.5, 2), support_px=len(points),
                          tabletop_support_fraction=round(backed, 2)))
    # Require the observed fan shape: divergent and near-vertical long material sides
    # and a separately observed upper ledge. Rectangles and unanchored cargo fail.
    def slope(edge):
        (x,y),(u,v) = edge["points_px"]
        return (u-x)/(v-y) if abs(v-y)>30 else None
    slopes = [slope(e) for e in edges if e["support_px"]>=40]
    ledge = any(abs(e["points_px"][1][1]-e["points_px"][0][1])<6 and e["support_px"]>=15 for e in edges)
    if not (ledge and any(s is not None and -.65<s<-.12 for s in slopes)
            and any(s is not None and abs(s)<.12 for s in slopes)
            and any(e["kind"]=="rim_table_boundary" for e in edges)):
        return out
    for name, seen, frame_boundary in (
        ("left",component[:,0].any(),x0==0),("right",component[:,-1].any(),x1==width),
        ("top",component[0].any(),y0==0),("bottom",component[-1].any(),y1==height)):
        if seen:
            out["clipping_edges" if frame_boundary else "roi_clipping_edges"].append(name)
    out.update(status="partial", touches_frame=bool(out["clipping_edges"]), segments=edges,
               reason="Visible material portions only. Cargo and mounting hardware obscure the deck. No complete pad contour or paired independent pad rails identified.")
    return out
