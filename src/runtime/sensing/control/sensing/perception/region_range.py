"""Subject: one range per camera region -- LiDAR when it can see the thing, else the floor (D-423).

The floor plane (camera_ground) ranges a region at its bottom edge, which is
honest only for things that touch the floor and only as good as the camera
pitch: with the URDF nominal 8 deg on a camera that really sits at 11.5 deg, a
contact point 0.40 m ahead reads about 0.66 m. The LiDAR does not care about
pitch, but its scan plane is 0.125 m above the floor, so low boxes and paint
are invisible to it. Each fills the other's gap:

  L <= G* + tolerance   LiDAR. A return in the region's bearing span that is
                        nearer than the contact point is the thing itself (the
                        floor estimate over-read) or something nearer still.
  L farther than that   the thing is below the scan plane: the floor, G.
  region off the floor  (every row above the horizon) only the LiDAR knows.

G* is the floor distance without the trusted-range cap, used only to judge
agreement; a reported G still honours the cap. Both distances are forward
metres from the camera, so they compare like for like.

Bearings use the pitched pinhole exactly (the same ray GroundPlane.lateral
projects), measured from the robot's forward axis at the camera, left
positive. A ground model without pinhole intrinsics (the homography profile)
has no bearing, and its regions keep their floor answer.
"""
import math

import numpy as np

LIDAR, GROUND = 'L', 'G'


def pixel_bearing(ground, column, row):
    """Horizontal bearing of a pixel's ray, radians, left positive, 0 = straight ahead."""
    forward = (ground.focal_px * math.cos(ground.pitch_rad)
               - (float(row) - ground.principal_y) * math.sin(ground.pitch_rad))
    return math.atan2(ground.principal_x - float(column), forward)


def region_span(ground, bbox_xyxy):
    """(low, high) bearing over the box corners, or None without pinhole geometry."""
    if not all(hasattr(ground, key) for key in ('focal_px', 'principal_x', 'principal_y', 'pitch_rad')):
        return None
    try:
        x0, y0, x1, y1 = (float(v) for v in bbox_xyxy)
    except (TypeError, ValueError):
        return None
    corners = [pixel_bearing(ground, u, v) for u in (x0, x1) for v in (y0, y1)]
    return min(corners), max(corners)


def floor_distance_unbounded(ground, row):
    """GroundPlane.distance without the trusted-range cap; None at or above the horizon."""
    angle = ground.pitch_rad + math.atan((float(row) - ground.principal_y) / ground.focal_px)
    if angle <= 0.0:
        return None
    metres = ground.height_m / math.tan(angle)
    return metres if math.isfinite(metres) and metres > 0.0 else None


def scan_in_camera(ranges, angle_min, angle_increment, range_min, range_max, *,
                   nose_rad, lidar_x_m, camera_x_m):
    """Valid LiDAR returns as (bearing, forward metres) seen from the camera.

    nose_rad is the scan angle of the robot's forward (lidar_mount: URDF pi,
    refined by an accepted record). Both sensors sit on the centre line (URDF
    y = 0), so only the forward offsets differ. Returns behind the camera drop.
    """
    r = np.asarray(ranges, dtype=float)
    yaw = angle_min + angle_increment * np.arange(r.size) - nose_rad
    lo = max(float(range_min), 0.0)
    hi = float(range_max) if range_max > 0 else np.inf
    with np.errstate(invalid='ignore'):
        keep = np.isfinite(r) & (r >= lo) & (r <= hi)
    r, yaw = r[keep], yaw[keep]
    forward = lidar_x_m + r * np.cos(yaw) - camera_x_m
    left = r * np.sin(yaw)
    ahead = forward > 0.0
    return np.arctan2(left[ahead], forward[ahead]), forward[ahead]


def choose_range(lidar_m, ground_m, ground_unbounded_m, *, tolerance_m, tolerance_ratio):
    """(metres, 'L' | 'G') or (None, None). See the module docstring for the rule."""
    if lidar_m is not None:
        if ground_unbounded_m is None:
            return lidar_m, LIDAR
        if lidar_m <= ground_unbounded_m + tolerance_m + tolerance_ratio * ground_unbounded_m:
            return lidar_m, LIDAR
    if ground_m is not None:
        return ground_m, GROUND
    return None, None


def range_regions(regions, ground, points, *, tolerance_m, tolerance_ratio):
    """New region dicts with distance_m and range_source; the input is not modified."""
    if points is None:
        return regions
    bearing, forward = points
    out = []
    for region in regions:
        span = region_span(ground, region.get('bbox_xyxy'))
        if span is None:
            out.append(region)
            continue
        inside = (bearing >= span[0]) & (bearing <= span[1])
        lidar_m = float(forward[inside].min()) if np.any(inside) else None
        metres, source = choose_range(
            lidar_m, region.get('distance_m'),
            floor_distance_unbounded(ground, region['bbox_xyxy'][3]),
            tolerance_m=tolerance_m, tolerance_ratio=tolerance_ratio)
        out.append(dict(region, distance_m=metres, range_source=source))
    return out
