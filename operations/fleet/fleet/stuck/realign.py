"""D-622 standalone REALIGN candidates; CORE owns live obstacle checks and motion."""
from dataclasses import dataclass
from datetime import datetime
import math

from core_common.robot_body import nominal_body_for


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


@dataclass(frozen=True)
class RealignConfig:
    robots: frozenset = frozenset()
    areas: tuple = ()

    @classmethod
    def from_mapping(cls, raw=None):
        raw = raw or {}
        if not isinstance(raw, dict):
            raise ValueError("stuck_resolver must be a mapping")
        ids, areas = raw.get("realign_robots", []), raw.get("realign_areas", [])
        if not isinstance(ids, list) or not all(isinstance(i, str) and i for i in ids):
            raise ValueError("realign_robots must be a list of robot ids")
        if not isinstance(areas, list):
            raise ValueError("realign_areas must be a list")
        parsed = []
        for area in areas:
            if not isinstance(area, dict) or set(area) != {"map_revision", "polygon"}:
                raise ValueError("realign area requires map_revision and polygon")
            polygon = area["polygon"]
            revision = area["map_revision"]
            if (not (isinstance(revision, str) and revision or type(revision) is int and revision > 0)
                    or not isinstance(polygon, list) or len(polygon) < 3
                    or not all(isinstance(p, (list, tuple)) and len(p) == 2 and all(map(finite,p)) for p in polygon)):
                raise ValueError("realign area requires finite convex map coordinates")
            points = tuple(tuple(p) for p in polygon)
            turns = [(b[0]-a[0])*(c[1]-b[1])-(b[1]-a[1])*(c[0]-b[0])
                     for a,b,c in zip(points, points[1:]+points[:1], points[2:]+points[:2])]
            if not (all(t > 0 for t in turns) or all(t < 0 for t in turns)):
                raise ValueError("realign area must be strictly convex")
            points = points if turns[0] > 0 else tuple(reversed(points))
            if not _in_area(points, 0., points):
                raise ValueError("realign area must be convex and simple")
            parsed.append((area["map_revision"], points))
        return cls(frozenset(ids), tuple(parsed))


def _centres(req, proof):
    """Exact nominal CORE arc centres; half a sampling step pads every continuous segment."""
    angle, sign = abs(req["angle_rad"]), math.copysign(1., req["angle_rad"])
    if req["kind"] == "PIVOT":
        return [(proof["x"], proof["y"])], 0.
    rb, rf = req["back_radius_m"], req["fwd_radius_m"]
    back = min(angle, 2*math.asin(req["back_m"]/(2*rb)))  # CORE uses measured chord length
    n = max(1, math.ceil(angle/.02))
    points = []
    ca, sa = math.cos(proof["yaw"]), math.sin(proof["yaw"])
    for k in range(n+1):
        t = angle*k/n
        b = min(t, back)
        x, y = -rb*math.sin(b), -sign*rb*(1-math.cos(b))
        if t > back:
            x += rf*(math.sin(t)-math.sin(back))
            y += sign*rf*(math.cos(back)-math.cos(t))
        points.append((proof["x"]+ca*x-sa*y, proof["y"]+sa*x+ca*y))
    return points, max(rb,rf)*angle/n/2


def _in_area(points, radius, polygon):
    return all(((b[0]-a[0])*(p[1]-a[1])-(b[1]-a[1])*(p[0]-a[0]))
               >= radius*math.hypot(b[0]-a[0], b[1]-a[1])
               for p in points for a,b in zip(polygon, polygon[1:]+polygon[:1]))


def _observed_at(value):
    if finite(value):
        return value
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.timestamp() if parsed.tzinfo is not None else None
    except (TypeError, AttributeError, ValueError, OverflowError, OSError):
        return None


def _base(row):
    caps = row.get("capabilities") or {}
    controls = caps.get("controls") if isinstance(caps, dict) else None
    items = controls.get("items") if isinstance(controls, dict) else None
    return next((i for i in items if isinstance(i, dict)
                 and i.get("kind") == "base_velocity"), {}) if isinstance(items, list) else {}


def select(row, rows, config, *, now, attempt):
    """(request, None) or (None, hold reason); absence never grants a manoeuvre."""
    if row.get("robot_id") not in config.robots:
        return None, "disabled"
    if row.get("trip"):
        return None, "trip_realign_unproved"
    lf = (row.get("state") or {}).get("line_follow") or {}
    stuck = lf.get("stuck") or {}
    proof, clearance = row.get("realign_evidence") or {}, row.get("clearance_evidence") or {}
    if (lf.get("mode") != "CAMERA_LINE" or "crosswalk" not in lf or lf["crosswalk"] is not None
            or stuck.get("cause") not in ("lane_lost", "no_motion", "no_progress", "dithering", "obstacle_ahead")
            or row.get("ai_facts") or not stuck.get("local_enabled")
            or "REALIGN" not in stuck.get("decisions", ())):
        return None, "recovery_not_admitted"
    if (type(attempt) is not int or not 1 <= attempt <= 2
            or proof.get("status") != "heading_compared" or not proof.get("map_id")
            or not proof.get("map_version") or not proof.get("edge_id")
            or not all(finite(proof.get(k)) for k in ("turn_deg", "pose_stamp", "x", "y", "yaw", "u_m", "offset_m"))
            or proof["u_m"] < .018 or not .5 <= abs(proof["turn_deg"]) <= 90):
        return None, "heading_or_budget_unproved"
    observed = _observed_at(clearance.get("inquiry_observed_at"))
    obs = ((clearance.get("inquiry") or {}).get("observations") or {})
    age = obs.get("scan_age_s")
    if (clearance.get("stuck_id") != stuck.get("stuck_id") or not finite(now)
            or observed is None or not finite(age) or not 0 <= now-observed
            or not 0 <= age or age+now-observed > .3 or obs.get("geometry_known") is not True):
        return None, "clearance_stale"
    kind = "PIVOT" if proof.get("turn_spot") is True else "KTURN"
    base = _base(row)
    body = nominal_body_for(base.get("robot_kind"))
    kinds = base.get("stuck_realign")
    if body is None or not isinstance(kinds, (list, tuple)) or kind not in kinds:
        return None, "body_or_capability_unproved"
    if kind == "KTURN" and (clearance.get("rear_state") != "clear"
            or not finite(clearance.get("rear_clearance_m")) or clearance["rear_clearance_m"] <= .06):
        return None, "rear_unproved"
    req = {"kind":kind, "angle_rad":math.radians(proof["turn_deg"]), "pose_stamp":proof["pose_stamp"],
           "attempt":attempt, "turn_spot":kind == "PIVOT", "basis": {
               "map_revision":proof["map_version"], "pose_age_s":proof.get("pose_age_s", 0.),
               "target":"lane_heading", "d_m":proof["offset_m"],
               "psi_rad":math.radians(proof["turn_deg"]), "u_m":proof["u_m"]}}
    if kind == "KTURN":
        req.update(back_m=.04, back_radius_m=.08, fwd_radius_m=.02)
    points, pad = _centres(req, proof)
    travel = 0. if kind == "PIVOT" else .05+abs(req["angle_rad"])*req["fwd_radius_m"]
    radius = body.rotation_radius_m + body.sweep_pad_m + proof["u_m"] + .05*travel + pad
    if not any(revision == proof["map_version"] and _in_area(points, radius, polygon)
               for revision, polygon in config.areas):
        return None, "map_sweep_unproved"
    for peer in rows:
        if peer.get("robot_id") == row.get("robot_id"):
            continue
        other = peer.get("realign_evidence") or {}
        peer_body = nominal_body_for(_base(peer).get("robot_kind"))
        if (not peer.get("online", True) or other.get("status") != "heading_compared" or other.get("map_id") != proof["map_id"]
                or peer_body is None
                or other.get("map_version") != proof["map_version"]
                or not all(finite(other.get(k)) for k in ("x", "y", "u_m")) or other["u_m"] < .018):
            return None, "peer_unknown"
        reach = radius + peer_body.rotation_radius_m + other["u_m"] + .30
        if any(math.hypot(p[0]-other["x"],p[1]-other["y"]) <= reach for p in points):
            return None, "peer_near"
    return req, None
