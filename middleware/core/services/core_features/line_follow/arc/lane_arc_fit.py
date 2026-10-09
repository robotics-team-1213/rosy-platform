"""D-520 stage 2 fixed-radius geometry candidate; never motion evidence by itself."""

import math
from typing import NamedTuple


class CircleCandidate(NamedTuple):
    centre_m: tuple[float, float]
    radial_rms_m: float
    span_deg: float
    used_points: int
    weak_axis_1sigma_m: float
    heading_u95_deg: float


def fit_circle_candidate(points, expected_centre_m, radius_m, *, point_sigma_m, radial_gate_m):
    """Fit a known outer radius near an expected robot-frame centre.

    The uncertainty assumes independent point noise; camera/odom systematic error and
    floor-vs-wall identity must be checked before a caller can use this for control.
    """
    if (len(expected_centre_m) != 2 or any(not math.isfinite(v) for v in expected_centre_m)
            or any(not math.isfinite(v) or v <= 0 for v in (radius_m, point_sigma_m, radial_gate_m))):
        raise ValueError("circle centre and positive finite radius/noise/gate required")
    points = tuple(points)
    if len(points) > 48 or any(len(p) != 2 or any(not math.isfinite(v) for v in p) for p in points):
        raise ValueError("at most 48 finite xy points required")
    cx, cy = (float(v) for v in expected_centre_m)
    selected = [(float(x), float(y)) for x, y in points
                if abs(math.hypot(x-cx, y-cy)-radius_m) <= radial_gate_m]
    # A spoke enters the radial band at its crossing, but its local direction
    # differs from the expected circle tangent (D-520's 45 mm / 30 deg gate).
    tangent_points = []
    for x, y in selected:
        nearby = [(px, py) for px, py in selected if math.hypot(px-x, py-y) <= 0.045]
        if len(nearby) < 4:
            continue
        mx = sum(px for px, _ in nearby)/len(nearby)
        my = sum(py for _, py in nearby)/len(nearby)
        xx = sum((px-mx)**2 for px, _ in nearby)
        xy = sum((px-mx)*(py-my) for px, py in nearby)
        yy = sum((py-my)**2 for _, py in nearby)
        if xx+yy <= 1e-12 or math.hypot(xx-yy, 2*xy)/(xx+yy) < 0.5:
            continue
        direction = 0.5*math.atan2(2*xy, xx-yy)
        tangent = math.atan2(x-cx, cy-y)
        if abs(math.cos(direction-tangent)) >= math.cos(math.radians(30)):
            tangent_points.append((x, y))
    selected = tangent_points
    if len(selected) < 8:
        return None

    for _ in range(5):
        xx = xy = yy = bx = by = 0.0
        for x, y in selected:
            dx, dy = cx-x, cy-y
            d = math.hypot(dx, dy)
            if d < 1e-9:
                return None
            jx, jy, residual = dx/d, dy/d, d-radius_m
            xx += jx*jx
            xy += jx*jy
            yy += jy*jy
            bx += jx*residual
            by += jy*residual
        det = xx*yy-xy*xy
        if det <= 1e-10:
            return None
        shift_x, shift_y = (yy*bx-xy*by)/det, (xx*by-xy*bx)/det
        cx -= shift_x
        cy -= shift_y
        if math.hypot(shift_x, shift_y) < 1e-9:
            break

    angles = sorted(math.atan2(y-cy, x-cx) % (2*math.pi) for x, y in selected)
    gaps = [b-a for a, b in zip(angles, angles[1:])]
    gaps.append(angles[0]+2*math.pi-angles[-1])
    span_deg = math.degrees(2*math.pi-max(gaps))
    rms = math.sqrt(sum((math.hypot(x-cx, y-cy)-radius_m)**2 for x, y in selected)/len(selected))
    weak_eigenvalue = (xx+yy-math.sqrt(max(0.0, (xx-yy)**2+4*xy*xy)))/2
    if weak_eigenvalue <= 1e-10:
        return None
    weak_sigma = point_sigma_m/math.sqrt(weak_eigenvalue)
    heading_u95 = math.degrees(math.atan2(1.96*weak_sigma, math.hypot(cx, cy)))
    return CircleCandidate((cx, cy), rms, span_deg, len(selected), weak_sigma, heading_u95)
