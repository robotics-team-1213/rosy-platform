"""D-511 2: one lane-compliance judgement from the Fleet map pose and the active site graph. Pure.

The pose is projected onto every arc (``fleet.routing.graph.Arc.project``). An arc counts only when
the foot point lies strictly inside it (past either end the offset sign is arbitrary), within
``max_lateral_m`` (default: the arc's own ``width_m``), and with its tangent within
``heading_gate_deg`` of the robot heading. A pose without a heading (``yaw`` None: a D-472 LED
track before its first motion heading) skips the heading gate and takes the nearest arc: on a
two-way edge the offset sign may belong to the opposite arc, and at a junction the nearest arc
may be the crossing lane. Of those the nearest is used, so on a two-way edge and
at a junction the arc along the direction of travel wins. The lateral offset is signed against
that arc's tangent (left +). The body margin is
``width_m / 2 - (|offset| + body_half_width_m)``: the gap between the body side and the lane edge,
negative once the body crosses it. ``MapPose.yaw`` is ``base_footprint`` forward; on a one-way
lane the heading gate also accepts the opposite heading during reverse recovery. The body half width
is the URDF nominal from
``core_common.robot_body`` (D-424), never a local number.

Levels: OK; WARN after ``persist_n`` consecutive samples with ``margin < warn_margin_m``; ACT after
``persist_n`` consecutive samples with ``margin < 0``; UNKNOWN when the pose is not LOCALIZED, no
site map is active, or no arc passes the three tests above (a bay or yard off the graph, past a
dead end, across a lane). UNKNOWN is not a departure (D-82 Law 0) and
restarts both counts. M0 only observes: nothing here sends anything to a robot.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, fields
from typing import Mapping, Optional

from core_common.robot_body import NOMINAL_BODY

OK, WARN, ACT, UNKNOWN = "OK", "WARN", "ACT", "UNKNOWN"
#: D-424 URDF nominal. ponytail: one body for every robot; per-kind bodies when a second kind drives.
BODY_HALF_WIDTH_M = NOMINAL_BODY.half_width_m
#: D-424 URDF nominal: base_footprint to the body front (m), for the crosswalk hint distance.
BODY_FRONT_M = NOMINAL_BODY.front_x_m


@dataclass(frozen=True)
class LaneComplianceConfig:
    """Site config ``fleet.lane_compliance`` (D-511 2). Defaults are provisional until measured
    in SIM and on the field (D-511 Open); a site overrides them in its YAML."""

    #: WARN when the body is closer than this to the lane edge (m).
    warn_margin_m: float = 0.02
    #: Consecutive samples a level needs (2 Hz monitor: 3 samples = 1.5 s).
    persist_n: int = 3
    #: How long ACT may last before the M1/M2 stop rule; M0 reports it only.
    act_timeout_s: float = 3.0
    #: A pose further than this from an arc centreline is not on that lane (m); None = its width_m.
    max_lateral_m: Optional[float] = None
    #: An arc counts only when its tangent is within this of the robot heading (deg).
    heading_gate_deg: float = 45.0
    #: Monitor deadband: odom within this distance / turn over max_odom_age_s is "still" (jitter).
    moving_min_m: float = 0.01
    moving_min_deg: float = 2.0
    #: A D-472 LED track must move this far before its direction is taken as the heading (m).
    #: Sized above overhead blob jitter; provisional until measured on ceiling_north.
    track_heading_min_m: float = 0.05
    #: D-511 rev 1 (return loop). Half the painted tape width (m): the body is on the line while
    #: it overlaps the tape, measured on map_v2_fleet paint (2.5 cm tape).
    line_half_width_m: float = 0.0125
    #: The mapped area is the lanes' bounding box grown by this (m); outside it is OFF_MAP.
    off_map_pad_m: float = 0.15
    #: A moving robot Fleet cannot place for this long is OFF_MAP (not seen) (s).
    off_map_unseen_s: float = 3.0
    #: A return state must hold this long before it is reported (debounce) (s).
    return_persist_s: float = 1.0
    #: WRONG_WAY also needs this much travel against the lane while it holds (m).
    wrong_way_min_m: float = 0.10
    #: The re-entry point is this far ahead of the nearest lane point, along the lane (m).
    entry_ahead_m: float = 0.10
    #: A crosswalk this far ahead along the lane goes into the cue as ``crosswalk_ahead`` (m).
    crosswalk_ahead_m: float = 0.6
    #: Ceiling pose error bound for the zone (m): D-587 calibration residual p90 0.018 m + marker
    #: height 0.02-0.03 m -> 0.012-0.019 m at the bottom road (validation 2026-10-10).
    crosswalk_uncertainty_m: float = 0.035
    #: Send the return cue (``POST /line-follow/lane-cue``) to the robot; off = observe only.
    return_cue: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.return_cue, bool):
            raise ValueError("fleet.lane_compliance.return_cue must be true or false")
        for name in ("line_half_width_m", "off_map_pad_m", "off_map_unseen_s", "return_persist_s",
                     "wrong_way_min_m", "entry_ahead_m", "crosswalk_ahead_m", "crosswalk_uncertainty_m"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0.0 <= value <= 10.0:
                raise ValueError(f"fleet.lane_compliance.{name} must be a number within [0, 10]")
        for name in ("warn_margin_m", "act_timeout_s", "heading_gate_deg", "moving_min_m",
                     "moving_min_deg", "track_heading_min_m") + (
                         ("max_lateral_m",) if self.max_lateral_m is not None else ()):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError(f"fleet.lane_compliance.{name} must be a finite number")
        if not 0.0 <= self.warn_margin_m <= 1.0:
            raise ValueError("fleet.lane_compliance.warn_margin_m must be within [0, 1]")
        if not 0.0 < self.act_timeout_s <= 60.0:
            raise ValueError("fleet.lane_compliance.act_timeout_s must be within (0, 60]")
        if self.max_lateral_m is not None and not 0.0 < self.max_lateral_m <= 10.0:
            raise ValueError("fleet.lane_compliance.max_lateral_m must be within (0, 10]")
        if not 0.0 < self.heading_gate_deg < 90.0:
            raise ValueError("fleet.lane_compliance.heading_gate_deg must be within (0, 90)")
        if not (0.0 <= self.moving_min_m <= 1.0 and 0.0 <= self.moving_min_deg <= 90.0):
            raise ValueError("fleet.lane_compliance.moving_min_m/deg must be within [0, 1] m / [0, 90] deg")
        if not 0.0 < self.track_heading_min_m <= 1.0:
            raise ValueError("fleet.lane_compliance.track_heading_min_m must be within (0, 1]")
        if isinstance(self.persist_n, bool) or not isinstance(self.persist_n, int) or not 1 <= self.persist_n <= 100:
            raise ValueError("fleet.lane_compliance.persist_n must be an integer within [1, 100]")

    @classmethod
    def from_mapping(cls, raw: Mapping | None) -> "LaneComplianceConfig":
        raw = dict(raw or {})
        unknown = set(raw) - {item.name for item in fields(cls)}
        if unknown:
            raise ValueError(f"fleet.lane_compliance has unknown keys: {sorted(unknown)}")
        return cls(**raw)


@dataclass(frozen=True)
class LaneSample:
    """One pose against the lanes; ``edge_id`` None means no lane to project onto."""

    pose_state: str
    edge_id: Optional[str] = None
    arc_id: Optional[str] = None
    offset_m: Optional[float] = None
    margin_m: Optional[float] = None
    width_m: Optional[float] = None


@dataclass(frozen=True)
class LaneCompliance:
    level: str
    pose_state: str
    edge_id: Optional[str]
    arc_id: Optional[str]
    offset_m: Optional[float]
    margin_m: Optional[float]
    width_m: Optional[float]
    body_half_width_m: float
    #: Consecutive samples under ``warn_margin_m`` / under 0 so far (ACT ones count for both).
    warn_count: int
    act_count: int


def _wrap(angle: float) -> float:
    return (angle + math.pi) % (2.0 * math.pi) - math.pi


#: Numerical tolerance for "the foot point is the arc's end", not a tuning value.
END_EPS_M = 1e-6


def sample(pose, graph, body_half_width_m: float = BODY_HALF_WIDTH_M,
           config: LaneComplianceConfig = LaneComplianceConfig()) -> LaneSample:
    """``pose`` is a ``MapPose``; ``graph`` a ``fleet.routing.graph.Graph`` or None."""
    state = getattr(pose, "state", "UNKNOWN") if pose is not None else "UNKNOWN"
    arcs = list(graph.arcs.values()) if graph is not None else []
    if state != "LOCALIZED" or not arcs:
        return LaneSample(state)
    x, y, yaw = pose.x, pose.y, pose.yaw
    gate = math.radians(config.heading_gate_deg)
    reversible_edges = {arc.edge_id for arc in arcs if not arc.forward}
    best = None
    for arc in arcs:
        dist, s, tangent = arc.project(x, y)
        limit = arc.width_m if config.max_lateral_m is None else config.max_lateral_m
        if (END_EPS_M < s < arc.length_m - END_EPS_M and dist <= limit
                and (yaw is None or abs(_wrap(tangent - yaw)) <= gate or
                     (arc.edge_id not in reversible_edges and abs(_wrap(tangent - yaw + math.pi)) <= gate))
                and (best is None or dist < best[1])):
            best = (arc, dist, s, tangent)
    if best is None:
        return LaneSample(state)
    arc, dist, s, tangent = best
    px, py, _ = arc.point_at(s)
    left = math.cos(tangent) * (y - py) - math.sin(tangent) * (x - px)
    offset = math.copysign(dist, left)
    margin = arc.width_m / 2.0 - (dist + body_half_width_m)
    return LaneSample(state, arc.edge_id, arc.id, offset, margin, arc.width_m)


class LaneComplianceTracker:
    """One robot's level with the ``persist_n`` rule. Feed samples in time order."""

    def __init__(self, config: LaneComplianceConfig = LaneComplianceConfig(),
                 body_half_width_m: float = BODY_HALF_WIDTH_M) -> None:
        self.config = config
        self.body_half_width_m = body_half_width_m
        self._warn = self._act = 0

    def update(self, lane: LaneSample) -> LaneCompliance:
        cfg = self.config
        if lane.margin_m is None:
            self._warn = self._act = 0
            level = UNKNOWN
        else:
            self._warn = self._warn + 1 if lane.margin_m < cfg.warn_margin_m else 0
            self._act = self._act + 1 if lane.margin_m < 0.0 else 0
            level = ACT if self._act >= cfg.persist_n else WARN if self._warn >= cfg.persist_n else OK
        return LaneCompliance(level, lane.pose_state, lane.edge_id, lane.arc_id, lane.offset_m,
                              lane.margin_m, lane.width_m, self.body_half_width_m, self._warn, self._act)

    def judge(self, pose, graph) -> LaneCompliance:
        return self.update(sample(pose, graph, self.body_half_width_m, self.config))


# --- D-511 rev 1: the return loop (user, 2026-10-10) --------------------------------------------
#: Where the body is against the map. ``UNSEEN`` is "no judgement yet" and is never sent.
ON_LANE, ON_LINE, OFF_LANE, OFF_MAP, WRONG_WAY, UNSEEN = (
    "ON_LANE", "ON_LINE", "OFF_LANE", "OFF_MAP", "WRONG_WAY", "UNSEEN")


@dataclass(frozen=True)
class ReturnSample:
    """One raw (undebounced) classification. Angles in degrees. ``side`` is where the lane centre
    is, seen from the robot (``left``/``right``); None when on the lane."""

    state: str
    edge_id: Optional[str] = None
    offset_m: Optional[float] = None
    side: Optional[str] = None
    bearing_deg: Optional[float] = None       # to the re-entry point, robot frame (left +)
    lane_heading_deg: Optional[float] = None  # allowed direction of the nearest lane, map frame
    turn_deg: Optional[float] = None          # lane direction minus robot heading (left +)
    entry: Optional[tuple] = None             # re-entry point (x, y), map frame
    crosswalk: Optional[str] = None
    #: D-491/D-573 zone ``{id, near_m, far_m, uncertainty_m, source}`` of the crosswalk ahead (or under
    #: the body) along the lane from base_footprint; None when none is near.
    crosswalk_ahead: Optional[dict] = None


def map_bounds(graph, pad_m: float) -> Optional[tuple]:
    """The lanes' bounding box grown by ``pad_m``: (x0, y0, x1, y1), or None without lanes."""
    points = [p for arc in graph.arcs.values() for p in arc.polyline] if graph is not None else []
    if not points:
        return None
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    return min(xs) - pad_m, min(ys) - pad_m, max(xs) + pad_m, max(ys) + pad_m


def classify(x: float, y: float, yaw: Optional[float], travel: Optional[float], graph, crosswalks=(),
             config: LaneComplianceConfig = LaneComplianceConfig(),
             body_half_width_m: float = BODY_HALF_WIDTH_M, bounds=None,
             body_front_m: float = BODY_FRONT_M) -> ReturnSample:
    """Raw state of one map position. ``yaw`` is the body heading (None: unknown), ``travel`` the
    direction of the last ``track_heading_min_m`` of motion (None: no motion yet). WRONG_WAY reads
    ``travel`` only: a robot turning in place to come back is not going the wrong way yet.
    ``crosswalks`` are ``(id, polygon)`` pairs: inside one the robot crosses on purpose (D-573),
    so it is never ON_LINE or OFF_LANE there."""
    from fleet.site_map import _inside
    arcs = list(graph.arcs.values()) if graph is not None else []
    if bounds is None:
        bounds = map_bounds(graph, config.off_map_pad_m)
    if not arcs or bounds is None or not (bounds[0] <= x <= bounds[2] and bounds[1] <= y <= bounds[3]):
        return ReturnSample(OFF_MAP)
    projected = [(arc, *arc.project(x, y)) for arc in arcs]
    arc, dist, s, tangent = min(projected, key=lambda item: item[1])
    px, py, _ = arc.point_at(s)
    left = math.cos(tangent) * (y - py) - math.sin(tangent) * (x - px)
    offset = math.copysign(dist, left)
    half = arc.width_m / 2.0
    crossing = next((cid for cid, polygon in crosswalks if _inside((x, y), list(polygon))), None)
    if crossing is not None or dist + body_half_width_m <= half - config.line_half_width_m:
        state = ON_LANE
    elif dist - body_half_width_m < half + config.line_half_width_m:
        state = ON_LINE
    else:
        state = OFF_LANE
    if travel is not None and state != OFF_LANE:
        # Every lane under the body runs against the travel: wrong way. At a junction a lane
        # within 90 deg is always under the body, so turning there is not.
        under = [t for a, d, _, t in projected if d - body_half_width_m < a.width_m / 2.0]
        if under and min(abs(_wrap(t - travel)) for t in under) > math.radians(180.0 - config.heading_gate_deg):
            state = WRONG_WAY
    ex, ey, _ = arc.point_at(s + config.entry_ahead_m)
    heading = yaw if yaw is not None else travel
    bearing = turn = side = None
    if heading is not None:
        bearing = math.degrees(_wrap(math.atan2(ey - y, ex - x) - heading))
        turn = math.degrees(_wrap(tangent - heading))
    if state in (ON_LINE, OFF_LANE):
        if bearing is not None:
            side = "left" if bearing > 0 else "right"
        else:   # no heading: assume it goes the lane's way; the centre is across the offset
            side = "right" if offset > 0 else "left"
    ahead = (crosswalk_ahead(arc, s, crosswalks, config.crosswalk_ahead_m, body_front_m,
                             config.crosswalk_uncertainty_m)
             if crosswalks and state in (ON_LANE, ON_LINE) else None)
    return ReturnSample(state, arc.edge_id, round(offset, 4), side,
                        None if bearing is None else round(bearing, 1), round(math.degrees(tangent), 1),
                        None if turn is None else round(turn, 1), (round(ex, 4), round(ey, 4)), crossing, ahead)


#: Walk step along the lane for the crosswalk zone (m); the zone is this coarse.
XW_STEP_M = 0.01


def crosswalk_ahead(arc, s: float, crosswalks, horizon_m: float, behind_m: float,
                    uncertainty_m: float) -> Optional[dict]:
    """D-491/D-573 zone from the map: the first crosswalk polygon the lane centreline is in between
    ``behind_m`` behind and ``horizon_m`` ahead of base_footprint, as ``{id, near_m, far_m,
    uncertainty_m, source}`` along the lane from base_footprint (near < 0 once inside).
    ponytail: walks this arc only; a crosswalk past the arc's end shows once on the next arc."""
    from fleet.site_map import _inside
    for cid, polygon in crosswalks:
        polygon = list(polygon)
        hit = None
        along = s - behind_m
        while along <= min(s + horizon_m, arc.length_m) + 1e-9:
            x, y, _ = arc.point_at(max(along, 0.0))
            inside = _inside((x, y), polygon)
            if inside and hit is None:
                hit = along
            elif not inside and hit is not None:
                break
            along += XW_STEP_M
        if hit is not None and hit - s <= horizon_m and min(along, arc.length_m) - s > 0.0:  # base not past it
            return {"id": cid, "near_m": round(hit - s, 3), "far_m": round(min(along, arc.length_m) - s, 3),
                    "uncertainty_m": uncertainty_m, "source": "fleet_map"}
    return None


class ReturnTracker:
    """One robot's debounced return state. Feed ``update`` in time order; ``x`` None means Fleet
    cannot place the robot this tick. ``state`` changes only after ``return_persist_s`` (and, for
    WRONG_WAY, ``wrong_way_min_m`` of travel) in the new raw state."""

    def __init__(self, config: LaneComplianceConfig = LaneComplianceConfig(),
                 body_half_width_m: float = BODY_HALF_WIDTH_M) -> None:
        self.config = config
        self.body_half_width_m = body_half_width_m
        self._last_xy: Optional[tuple[float, float]] = None   # last point a motion step began at
        self.travel: Optional[float] = None
        self._seen_at: Optional[float] = None
        self._candidate: Optional[tuple] = None               # (state, since_t, since_xy)
        self.state = UNSEEN
        self.since: Optional[float] = None

    def _set(self, state: str, t: float) -> None:
        if state != self.state:
            self.state, self.since = state, t

    def update(self, t: float, x: Optional[float], y: Optional[float], yaw: Optional[float],
               graph, crosswalks=(), moving: bool = True, bounds=None) -> ReturnSample:
        cfg = self.config
        if x is None or y is None:
            self._candidate = None
            if moving and self._seen_at is not None and t - self._seen_at >= cfg.off_map_unseen_s:
                self._set(OFF_MAP, t)
            return ReturnSample(UNSEEN)
        self._seen_at = t
        last = self._last_xy
        if last is None or math.hypot(x - last[0], y - last[1]) >= cfg.track_heading_min_m:
            if last is not None:   # ponytail: last 5 cm step is the travel; fit a heading if noisy
                self.travel = math.atan2(y - last[1], x - last[0])
            self._last_xy = (x, y)
        raw = classify(x, y, yaw, self.travel, graph, crosswalks, cfg, self.body_half_width_m, bounds)
        if self._candidate is None or self._candidate[0] != raw.state:
            self._candidate = (raw.state, t, (x, y))
        state, since_t, (sx, sy) = self._candidate
        if (t - since_t >= cfg.return_persist_s
                and (state != WRONG_WAY or math.hypot(x - sx, y - sy) >= cfg.wrong_way_min_m)):
            self._set(state, t)
        return raw
