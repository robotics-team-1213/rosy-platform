"""D-511 2: one lane-compliance judgement from the Fleet map pose and the active site graph. Pure.

The pose is projected onto every arc (``fleet.routing.graph.Arc.project``). An arc counts only when
the foot point lies strictly inside it (past either end the offset sign is arbitrary), within
``max_lateral_m`` (default: the arc's own ``width_m``), and with its tangent within
``heading_gate_deg`` of the robot heading. A pose without a heading (``yaw`` None: a still
D-472 LED track) skips the heading gate: the nearest arc wins, so the margin is right but on a
two-way edge the offset sign may belong to the opposite arc. Of those the nearest is used, so on a two-way edge and
at a junction the arc along the direction of travel wins. The lateral offset is signed against
that arc's tangent (left +). The body margin is
``width_m / 2 - (|offset| + body_half_width_m)``: the gap between the body side and the lane edge,
negative once the body crosses it. ``MapPose.yaw`` is ``base_footprint`` forward, so a robot
backing along a one-way lane has no arc and reads UNKNOWN. The body half width is the URDF nominal from
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

from core_common.robot_body import PINKY_PRO

OK, WARN, ACT, UNKNOWN = "OK", "WARN", "ACT", "UNKNOWN"
#: D-424 URDF nominal. ponytail: one body for every robot; per-kind bodies when a second kind drives.
BODY_HALF_WIDTH_M = PINKY_PRO.half_width_m


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

    def __post_init__(self) -> None:
        for name in ("warn_margin_m", "act_timeout_s", "heading_gate_deg", "moving_min_m",
                     "moving_min_deg") + (("max_lateral_m",) if self.max_lateral_m is not None else ()):
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
    best = None
    for arc in arcs:
        dist, s, tangent = arc.project(x, y)
        limit = arc.width_m if config.max_lateral_m is None else config.max_lateral_m
        if (END_EPS_M < s < arc.length_m - END_EPS_M and dist <= limit
                and (yaw is None or abs(_wrap(tangent - yaw)) <= gate)
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
