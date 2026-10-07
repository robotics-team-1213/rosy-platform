"""D-491 3: Fleet map pose for trip execution. Rosy Cam sightings anchor, robot odom bridges. Pure.

Each accepted sighting is paired with the robot's `odom_pose` at its capture time (the nearest
sample within `max_pair_s`, or interpolated between two samples that bracket it) and becomes the
anchor. Between sightings the pose is the anchor composed with the rigid odom delta since it.
State: LOCALIZED, DEGRADED (bridged further than `max_dead_reckon_m`, or a sighting disagreed
with the bridged prediction by more than `max_jump_m` / `max_jump_deg`; it re-anchors and needs
`RECOVER_AFTER` consistent sightings), UNKNOWN (never anchored, or odom older than
`max_odom_age_s`).

Times are site wall seconds: sighting `captured_at`, odom `stamp` parsed from UTC ISO. The
caller passes `now`; no clock, no transport. Only trip execution reads this pose: `/route`
(D-463), D-395 and traffic keep `trusted_map_pose`. D-457 markerless tracking is not an input.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, fields
from datetime import datetime
from typing import Mapping, Optional

LOCALIZED, DEGRADED, UNKNOWN = "LOCALIZED", "DEGRADED", "UNKNOWN"
SIGHTING, BRIDGED = "sighting", "bridged"
#: A timestamp further ahead of `now` than this is refused (as the sighting ingest does).
MAX_FUTURE_S = 0.05
#: D-491 3: consecutive consistent sightings that end a DEGRADED episode (and confirm a first anchor).
RECOVER_AFTER = 2
#: Odom samples kept per robot for pairing (about 25 s at 10 Hz).
ODOM_BUFFER = 256

Pose = tuple[float, float, float]


@dataclass(frozen=True)
class MapPoseConfig:
    """Site config ``fleet.map_pose`` (D-491 3). Out-of-range values are refused at start-up."""

    max_dead_reckon_m: float = 1.5
    max_jump_m: float = 0.15
    max_jump_deg: float = 20.0
    max_odom_age_s: float = 3.0
    max_pair_s: float = 0.25
    #: Two odom samples this close around a sighting are interpolated (1 Hz heartbeat fits).
    max_interp_gap_s: float = 1.2
    sighting_lease_s: float = 1.0
    #: A sighting with a worker quality below this is ignored; one without quality passes.
    min_quality: float = 0.5

    def __post_init__(self) -> None:
        upper = {"max_dead_reckon_m": 20.0, "max_jump_m": 2.0, "max_jump_deg": 180.0,
                 "max_odom_age_s": 30.0, "max_pair_s": 1.0, "max_interp_gap_s": 5.0,
                 "sighting_lease_s": 5.0}
        for item in fields(self):
            value = getattr(self, item.name)
            if not _finite(value):
                raise ValueError(f"fleet.map_pose.{item.name} must be a finite number")
            if item.name in upper and not 0.0 < value <= upper[item.name]:
                raise ValueError(f"fleet.map_pose.{item.name} must be within (0, {upper[item.name]}]")
        if not 0.0 <= self.min_quality <= 1.0:
            raise ValueError("fleet.map_pose.min_quality must be within [0, 1]")
        if self.max_interp_gap_s < self.max_pair_s:
            raise ValueError("fleet.map_pose.max_interp_gap_s must be >= max_pair_s")

    @classmethod
    def from_mapping(cls, raw: Mapping | None) -> "MapPoseConfig":
        raw = dict(raw or {})
        unknown = set(raw) - {item.name for item in fields(cls)}
        if unknown:
            raise ValueError(f"fleet.map_pose has unknown keys: {sorted(unknown)}")
        return cls(**raw)


@dataclass(frozen=True)
class OdomSample:
    x: float
    y: float
    yaw: float
    stamp: float


@dataclass(frozen=True)
class Sighting:
    robot_id: str
    x: float
    y: float
    yaw: float
    captured_at: float
    quality: Optional[float] = None


@dataclass(frozen=True)
class MapPose:
    x: Optional[float]
    y: Optional[float]
    yaw: Optional[float]
    state: str
    source: Optional[str]
    dead_reckon_m: float
    age_s: Optional[float]


def _wrap(angle: float) -> float:
    return (angle + math.pi) % (2.0 * math.pi) - math.pi


def relative(a: Pose, b: Pose) -> Pose:
    """`b` in the frame of `a` (a^-1 * b)."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    c, s = math.cos(a[2]), math.sin(a[2])
    return c * dx + s * dy, -s * dx + c * dy, _wrap(b[2] - a[2])


def compose(a: Pose, d: Pose) -> Pose:
    c, s = math.cos(a[2]), math.sin(a[2])
    return a[0] + c * d[0] - s * d[1], a[1] + s * d[0] + c * d[1], _wrap(a[2] + d[2])


def _finite(*values) -> bool:
    return all(not isinstance(v, bool) and isinstance(v, (int, float)) and math.isfinite(v) for v in values)


def parse_utc(text) -> Optional[float]:
    """Epoch seconds of a UTC ISO stamp (`captured_at` format); None when not one."""
    if not isinstance(text, str):
        return None
    try:
        stamp = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if stamp.tzinfo is None:
        return None
    return stamp.timestamp()


def odom_from_snapshot(state: Optional[Mapping]) -> Optional[OdomSample]:
    """The snapshot's D-491 2 `odom_pose {x, y, yaw, stamp}`; None when absent or malformed."""
    raw = (state or {}).get("odom_pose")
    if not isinstance(raw, Mapping):
        return None
    x, y, yaw, stamp = raw.get("x"), raw.get("y"), raw.get("yaw"), parse_utc(raw.get("stamp"))
    if stamp is None or not _finite(x, y, yaw):
        return None
    return OdomSample(float(x), float(y), float(yaw), stamp)


def sighting_from_row(row: Optional[Mapping]) -> Optional[Sighting]:
    """An accepted sighting row (`SightingService.accept`); None when malformed."""
    row = row or {}
    robot_id, quality = row.get("robot_id"), row.get("quality")
    values = (row.get("x"), row.get("y"), row.get("yaw"), row.get("captured_at"))
    if not isinstance(robot_id, str) or not _finite(*values) or not (quality is None or _finite(quality)):
        return None
    return Sighting(robot_id, *(float(v) for v in values),
                    quality=None if quality is None else float(quality))


@dataclass(frozen=True)
class _Odom:
    stamp: float
    pose: Pose
    path_m: float      # cumulative odom path length, for dead reckoning


@dataclass(frozen=True)
class _Anchor:
    map_pose: Pose
    odom: _Odom


class MapPoseTracker:
    """One robot's map pose. Feed odom and accepted sightings in any order; read `pose(now)`."""

    def __init__(self, robot_id: str, config: MapPoseConfig = MapPoseConfig()) -> None:
        self.robot_id = robot_id
        self.config = config
        self._odom: deque[_Odom] = deque(maxlen=ODOM_BUFFER)
        self._anchor: Optional[_Anchor] = None
        self._pending: Optional[Sighting] = None
        self._newest_sighting: Optional[float] = None
        self._degraded = False
        self._consistent = 0

    def add_odom(self, sample: OdomSample, now: float) -> bool:
        """False for a future, repeated or out-of-order sample."""
        if sample.stamp > now + MAX_FUTURE_S or (self._odom and sample.stamp <= self._odom[-1].stamp):
            return False
        pose = (sample.x, sample.y, sample.yaw)
        path = self._odom[-1].path_m + math.dist(self._odom[-1].pose[:2], pose[:2]) if self._odom else 0.0
        self._odom.append(_Odom(sample.stamp, pose, path))
        self._resolve(now)
        return True

    def add_sighting(self, sighting: Sighting, now: float) -> bool:
        """False for another robot, low quality, outside the lease, future or not newer."""
        cfg = self.config
        age = now - sighting.captured_at
        if (sighting.robot_id != self.robot_id
                or (sighting.quality is not None and sighting.quality < cfg.min_quality)
                or age < -MAX_FUTURE_S or age > cfg.sighting_lease_s
                or (self._newest_sighting is not None and sighting.captured_at <= self._newest_sighting)):
            return False
        self._newest_sighting = sighting.captured_at
        self._pending = sighting       # a newer sighting supersedes one still waiting for odom
        self._resolve(now)
        return True

    def pose(self, now: float) -> MapPose:
        cfg = self.config
        latest = self._odom[-1] if self._odom else None
        if self._anchor is None or latest is None or now - latest.stamp > cfg.max_odom_age_s:
            return MapPose(None, None, None, UNKNOWN, None, 0.0, None)
        anchor = self._anchor
        if latest.stamp <= anchor.odom.stamp:
            x, y, yaw = anchor.map_pose
            return MapPose(x, y, yaw, DEGRADED if self._degraded else LOCALIZED, SIGHTING, 0.0,
                           max(0.0, now - anchor.odom.stamp))
        x, y, yaw = compose(anchor.map_pose, relative(anchor.odom.pose, latest.pose))
        bridged = latest.path_m - anchor.odom.path_m
        state = DEGRADED if self._degraded or bridged > cfg.max_dead_reckon_m else LOCALIZED
        return MapPose(x, y, yaw, state, BRIDGED, bridged, max(0.0, now - latest.stamp))

    def _resolve(self, now: float) -> None:
        sighting = self._pending
        if sighting is None:
            return
        odom = self._odom_at(sighting.captured_at)
        if odom is None:
            # Wait for a later sample to bracket it, unless one already came or it went stale.
            if ((self._odom and self._odom[-1].stamp >= sighting.captured_at)
                    or now - sighting.captured_at > self.config.max_odom_age_s):
                self._pending = None
            return
        self._pending = None
        self._apply(sighting, odom)

    def _odom_at(self, t: float) -> Optional[_Odom]:
        cfg = self.config
        before = next((o for o in reversed(self._odom) if o.stamp <= t), None)
        after = next((o for o in self._odom if o.stamp >= t), None)
        if before is not None and after is not None:
            if after.stamp == before.stamp:
                return before
            if after.stamp - before.stamp <= cfg.max_interp_gap_s:
                k = (t - before.stamp) / (after.stamp - before.stamp)
                step = relative(before.pose, after.pose)
                bx, by, byaw = before.pose
                ax, ay, _ = after.pose
                pose = (bx + k * (ax - bx), by + k * (ay - by), _wrap(byaw + k * step[2]))
                return _Odom(t, pose, before.path_m + k * (after.path_m - before.path_m))
        near = [o for o in (before, after) if o is not None and abs(o.stamp - t) <= cfg.max_pair_s]
        return min(near, key=lambda o: abs(o.stamp - t)) if near else None

    def _apply(self, sighting: Sighting, odom: _Odom) -> None:
        cfg = self.config
        seen = (sighting.x, sighting.y, sighting.yaw)
        anchor = self._anchor
        if anchor is None:
            self._degraded, self._consistent = True, 0       # a first anchor is not yet confirmed
        else:
            predicted = compose(anchor.map_pose, relative(anchor.odom.pose, odom.pose))
            jumped = (math.dist(predicted[:2], seen[:2]) > cfg.max_jump_m
                      or abs(_wrap(predicted[2] - seen[2])) > math.radians(cfg.max_jump_deg))
            if jumped:
                self._degraded, self._consistent = True, 0
            else:
                if odom.path_m - anchor.odom.path_m > cfg.max_dead_reckon_m:
                    self._degraded, self._consistent = True, 0
                self._consistent += 1
                if self._consistent >= RECOVER_AFTER:
                    self._degraded = False
        self._anchor = _Anchor(seen, odom)
