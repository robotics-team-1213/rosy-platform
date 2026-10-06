"""D-468 local lane return proposals; no ROS, transport or final command writer.

Inputs are validated by the producer/bridge before use. Unknown clearance/floor
evidence is false. This policy cannot turn perception debug into driving authority.
"""
from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass
from core_features.line_follow.lane_return_approach import CorridorApproach


def _finite(*values):
    if not all(isinstance(v, (int, float)) and not isinstance(v, bool)
               and math.isfinite(v) for v in values):
        raise ValueError("finite numeric evidence required")


def _angle(value):
    return math.atan2(math.sin(value), math.cos(value))


@dataclass(frozen=True)
class Boundary:
    slope: float
    intercept: float

    def __post_init__(self):
        _finite(self.slope, self.intercept)

    def y(self, x):
        return self.slope*x + self.intercept


@dataclass(frozen=True)
class Footprint:
    front: float
    rear: float
    half_width: float

    def __post_init__(self):
        _finite(self.front, self.rear, self.half_width)
        if not self.rear < self.front or self.half_width <= 0:
            raise ValueError("invalid footprint")


@dataclass(frozen=True)
class Pose:
    received_at: float
    stamp_ns: int
    frame: str
    x: float
    y: float
    yaw: float

    def __post_init__(self):
        _finite(self.received_at, self.x, self.y, self.yaw)
        if (type(self.stamp_ns) is not int or self.stamp_ns < 0 or
                not isinstance(self.frame, str) or not self.frame.strip()):
            raise ValueError("original pose timestamp and frame required")


@dataclass(frozen=True)
class Corridor:
    left: Boundary
    right: Boundary
    geometry_id: str

    def __post_init__(self):
        if not self.geometry_id or self.left.intercept <= self.right.intercept:
            raise ValueError("ordered boundaries and geometry identity required")

    def margin(self, body):
        # Signed perpendicular distances at all four footprint corners.
        return min(min((self.left.y(x)-body.half_width)/math.hypot(1, self.left.slope),
                       (-body.half_width-self.right.y(x))/math.hypot(1, self.right.slope))
                   for x in (body.front, body.rear))

    @property
    def heading(self):
        return math.atan((self.left.slope+self.right.slope)/2)

    @property
    def center(self):
        return (self.left.intercept+self.right.intercept)/2

    def matches(self, previous, anchor, current):
        if self.geometry_id != previous.geometry_id or anchor.frame != current.frame:
            return False
        # Compare transformed boundaries at two points, not visibility/confidence.
        ca, sa = math.cos(anchor.yaw), math.sin(anchor.yaw)
        cc, sc = math.cos(current.yaw), math.sin(current.yaw)
        for edge, old_edge in ((self.left, previous.left), (self.right, previous.right)):
            for x in (0., .15):
                y = edge.y(x)
                wx, wy = current.x+cc*x-sc*y, current.y+sc*x+cc*y
                dx, dy = wx-anchor.x, wy-anchor.y
                ax, ay = ca*dx+sa*dy, -sa*dx+ca*dy
                if abs(ay-old_edge.y(ax))/math.hypot(1, old_edge.slope) > .015:
                    return False
        return abs(_angle(current.yaw+self.heading-anchor.yaw-previous.heading)) < .12


class PoseTrail:
    """Bounded measured path; invalidation never synthesizes missing travel."""
    def __init__(self):
        self.samples = deque(maxlen=100)

    def add(self, sample):
        if self.samples:
            old = self.samples[-1]
            dt = sample.received_at-old.received_at
            jump = math.hypot(sample.x-old.x, sample.y-old.y)
            if (sample.frame != old.frame or sample.stamp_ns <= old.stamp_ns
                    or not 0 < dt <= .5 or jump > .02+.2*dt
                    or abs(_angle(sample.yaw-old.yaw)) > .1+dt):
                self.samples.clear()
                self.samples.append(sample)
                return False
        self.samples.append(sample)
        while self.samples and sample.received_at-self.samples[0].received_at > 5:
            self.samples.popleft()
        return True

    @property
    def distance(self):
        return sum(math.hypot(b.x-a.x, b.y-a.y)
                   for a, b in zip(self.samples, list(self.samples)[1:]))


@dataclass(frozen=True)
class ReturnInput:
    now: float
    pose: Pose | None = None
    corridor: Corridor | None = None
    corridor_at: float | None = None
    clearance_at: float | None = None
    front_clear: bool = False
    rear_clear: bool = False
    turn_clear: bool = False
    floor_safe: bool = False
    authorized: bool = False
    linear_limit: float = 0
    angular_limit: float = 0
    corridor_stamp_ns: int | None = None
    epoch: int = 0


@dataclass(frozen=True)
class ReturnAction:
    phase: str
    reason: str
    linear: float = 0
    angular: float = 0
    recovered: bool = False
    fleet_required: bool = False


class ReturnController:
    """Bounded retrace, alternating search, corridor verification, then Fleet.

    Caller resets on OFF/authority session change. Numeric bounds are internal
    conservative defaults, not a bypass for the caller's lower live limits.
    """
    def __init__(self, body):
        self.body = body
        self.trail = PoseTrail()
        self.checkpoint = None
        self.phase = "tracking"
        self._count = 0
        self._last_evidence = None
        self._opened = None
        self._search_start = None
        self._search_pose = None
        self._search_attempt = 0
        self._path = []
        self._last_pose = None
        self._candidate = None
        self._reference_invalid = False
        self._align_start = None
        self._align_pose = None
        self._epoch = None
        self._approach = CorridorApproach()

    @staticmethod
    def _fresh(now, stamp, ttl=.3):
        return stamp is not None and 0 <= now-stamp <= ttl

    def restart_verification(self, now):
        """Accepted console RESUME rechecks the lane; it does not resume old motion."""
        self.phase, self._opened = 'departure_stop', now
        self._count = self._search_attempt = 0
        self._last_evidence = self._candidate = None
        self._search_start = self._search_pose = None
        self._align_start = self._align_pose = None
        self._path.clear()
        self._approach = CorridorApproach()

    def rebase_retrace(self):
        """Retrace path = measured trail since the checkpoint (D-476: incl. bridged travel)."""
        if self.checkpoint:
            anchor = self.checkpoint[0]
            self._path = [s for s in self.trail.samples if s.received_at >= anchor.received_at]
            if not self._path or self._path[0] != anchor:
                self._path = []

    def _hold(self, reason):
        return ReturnAction(self.phase, reason)

    def _search(self, inp):
        self.phase = "search"
        if not inp.turn_clear:
            return self._hold("rotation_space_unconfirmed")
        if self._search_start is None:
            self._search_start, self._search_pose = inp.now, inp.pose
        turn = abs(_angle(inp.pose.yaw-self._search_pose.yaw))
        if turn >= .18 or inp.now-self._search_start >= 2:
            self._search_attempt += 1
            self._search_start = self._search_pose = None
            return self._hold("search_candidate_finished")
        if self._search_attempt >= 2:
            self.phase = "fleet"
            return ReturnAction(self.phase, "local_candidates_exhausted", fleet_required=True)
        rate = min(.15, inp.angular_limit)
        return ReturnAction(self.phase, "sensor_search", angular=rate*(1 if self._search_attempt == 0 else -1))

    def tick(self, inp):
        _finite(inp.now, inp.linear_limit, inp.angular_limit)
        if type(inp.epoch) is not int or inp.epoch < 0:
            raise ValueError("valid pose continuity epoch required")
        if self._epoch is not None and self._epoch != inp.epoch:
            self._path.clear()
            self.trail.samples.clear()
            self._count = 0
            self._last_evidence = self._candidate = self._last_pose = None
            self._reference_invalid = self.checkpoint is not None
            self.phase, self._opened = "departure_stop", inp.now
            self._approach.finished = True
        self._epoch = inp.epoch
        if inp.linear_limit < 0 or inp.angular_limit < 0:
            raise ValueError("nonnegative live limits required")
        p = inp.pose
        fresh_pose = p is not None and self._fresh(inp.now, p.received_at)
        if fresh_pose and (self._last_pose is None or p.stamp_ns != self._last_pose.stamp_ns):
            if not self.trail.add(p):
                # Retain the frozen corridor identity for rejection, but invalidate
                # every moving retrace candidate. A jump must not adopt a new lane.
                self._path.clear()
                self._count = 0
                self._reference_invalid = True
                self._candidate = None
                if self.phase == "tracking":
                    self.phase, self._opened = "departure_stop", inp.now
            self._last_pose = p
        source_stamp = inp.corridor_stamp_ns
        lane = (inp.corridor if self._fresh(inp.now, inp.corridor_at)
                and type(source_stamp) is int and source_stamp >= 0 else None)
        inside = lane is not None and lane.margin(self.body) >= .015
        same = (self.checkpoint is None or (not self._reference_invalid and
                (fresh_pose and lane is not None and lane.matches(self.checkpoint[1], self.checkpoint[0], p)))
                )
        if self.phase == "tracking":
            if fresh_pose and inside and same:
                if self.checkpoint is None and (self._candidate is None or
                        not lane.matches(self._candidate[1], self._candidate[0], p)):
                    self._candidate = (p, lane)
                    self._count = 0
                    self._last_evidence = None
                if self._last_evidence is None or source_stamp > self._last_evidence:
                    self._count += 1
                    self._last_evidence = source_stamp
                if self._count >= 3 and lane.margin(self.body) >= .025 and abs(lane.heading) <= .12:
                    self.checkpoint = (p, lane)
                    self._candidate = None
                return ReturnAction(self.phase, "contained")
            self.phase, self._opened = "departure_stop", inp.now
            self._count = 0
            self._last_evidence = None
            self.rebase_retrace()
            return self._hold("containment_unconfirmed")
        # Perception continues on every tick; no movement if authority or data is absent.
        if not inp.authorized:
            return self._hold("authority_missing")
        if not fresh_pose:
            return self._hold("pose_stale")
        if not self._fresh(inp.now, inp.clearance_at) or not inp.floor_safe:
            return self._hold("space_or_floor_unconfirmed")
        if inp.now-self._opened > 12:
            self.phase = "fleet"
            return ReturnAction(self.phase, "local_deadline", fleet_required=True)
        if self.phase == "fleet":
            return ReturnAction(self.phase, "local_candidates_exhausted", fleet_required=True)
        if inside and same and abs(lane.heading) <= .12:
            self.phase = "verify"
            if self._candidate is None or not lane.matches(self._candidate[1], self._candidate[0], p):
                self._candidate = (p, lane)
                self._count = 0
                self._last_evidence = None
            if self._last_evidence is None or source_stamp > self._last_evidence:
                self._count += 1
                self._last_evidence = source_stamp
            if self._count >= 3 and inp.front_clear:
                self.phase = "tracking"
                if lane.margin(self.body) >= .025:
                    self.checkpoint = (p, lane)
                self._opened = self._search_start = self._search_pose = None
                self._search_attempt = 0
                self._candidate = None
                self._align_start = self._align_pose = None
                self._approach = CorridorApproach()
                return ReturnAction(self.phase, "corridor_verified", recovered=True)
            return self._hold("corridor_verifying")
        self._count = 0
        self._candidate = None
        if (self.checkpoint is None and lane is not None and not inside and
                inp.front_clear and inp.turn_clear):
            twist = self._approach.step(inp, lane)
            if twist is not None:
                self.phase = "approach"
                return ReturnAction(self.phase, "sensor_corridor_approach", *twist)
        if self.checkpoint and self._path and inp.rear_clear:
            target = self._path[-1]
            while len(self._path) > 1 and math.hypot(target.x-p.x, target.y-p.y) <= .008:
                self._path.pop()
                target = self._path[-1]
            dx, dy = target.x-p.x, target.y-p.y
            dist = math.hypot(dx, dy)
            if .008 < dist <= .15 and inp.now-self.checkpoint[0].received_at <= 5:
                local_x = math.cos(p.yaw)*dx+math.sin(p.yaw)*dy
                local_y = -math.sin(p.yaw)*dx+math.cos(p.yaw)*dy
                if local_x < -.002 and abs(math.atan2(local_y, -local_x)) < .8:
                    self.phase = "retrace"
                    speed = min(.03, inp.linear_limit)
                    angular = -2*speed*local_y/max(dist*dist, .0004)
                    if angular and not inp.turn_clear:
                        return self._search(inp)
                    # Preserve curvature while obeying the live angular ceiling.
                    scale = min(1, inp.angular_limit/abs(angular)) if angular else 1
                    return ReturnAction(self.phase, "measured_path_return", -speed*scale, angular*scale)
        if lane is not None and inside and inp.turn_clear and abs(lane.heading) > .12:
            self.phase = "align"
            if self._align_start is None:
                self._align_start, self._align_pose = inp.now, p
            if (inp.now-self._align_start >= 2 or
                    abs(_angle(p.yaw-self._align_pose.yaw)) >= .18):
                return self._search(inp)
            return ReturnAction(self.phase, "lane_heading_align", angular=max(-inp.angular_limit,
                                min(inp.angular_limit, lane.heading)))
        return self._search(inp)
