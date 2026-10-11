"""D-494 3: Fleet map pose for trip execution. Rosy Cam sightings anchor, robot odom bridges. Pure.

Each accepted sighting is paired with the robot's `odom_pose` at its capture time and becomes
the anchor. Sightings wait in a `captured_at`-ordered queue (odom usually arrives later than the
camera) until an odom sample at or after their capture time arrives: then they are interpolated
between the two samples that bracket them (gap at most `max_interp_gap_s`), else paired with the
nearest sample within `max_pair_s`, else dropped. A sighting waits at most `max_odom_age_s`.
Between sightings the pose is the anchor composed with the rigid odom delta since it.

States: LOCALIZED; DEGRADED when the bridge is longer than `max_dead_reckon_m` or turned more
than `max_bridge_turn_deg`, the anchor is older than `max_anchor_age_s`, or a sighting disagreed
with the bridged prediction by more than `max_jump_m` / `max_jump_deg` (it re-anchors and needs
`RECOVER_AFTER` consistent sightings; so does a first anchor; sightings more than
`max_anchor_age_s` apart reset that count unless odom stood still between them); UNKNOWN when never anchored or
odom is older than `max_odom_age_s`. An odom gap longer than `max_odom_age_s`, odom resuming
after such staleness, or a step faster than `max_speed_mps` / `max_turn_rate_dps` (a CORE
restart resets odom to 0) drops the anchor: the pose stays UNKNOWN until the next sighting.
A caller that knows the active map frame passes it: a sighting for another frame is counted and
ignored, and an anchor in another frame reads DEGRADED.

Operator pin (D-593): a named operator may set the anchor by hand (`add_pin`). It pairs with the
newest odom sample (fresh within `max_odom_age_s`), reads LOCALIZED at once and is bridged by odom
under the same limits as a sighting anchor (`max_dead_reckon_m`, `max_bridge_turn_deg`,
`max_anchor_age_s`). The next sighting is checked against it like any anchor: a disagreement
beyond `max_jump_m` / `max_jump_deg` reads DEGRADED. Sightings captured before the pin are dropped.
`anchor_source` names the anchor kind (`sighting` | `operator_pin`).

Path and turn are summed per received sample (chord, |dyaw|), so they are lower bounds that
depend on the odom rate; the trip loop refreshes odom at 2 Hz or faster (D-494 appendix).

Times are UTC epoch seconds: sighting `captured_at` and odom `stamp` (CORE wall clock on odom
arrival; an ISO string is also read). The
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
#: D-593: an anchor set by a named operator on the console map.
OPERATOR_PIN = "operator_pin"
#: A sighting further ahead of `now` than this is refused (as the sighting ingest does).
MAX_SIGHTING_FUTURE_S = 0.05
#: D-494 3: consecutive consistent sightings that end a DEGRADED episode (and confirm a first anchor).
RECOVER_AFTER = 2
#: The newest odom samples kept per robot for pairing (25 s at 10 Hz; less when polled faster).
ODOM_BUFFER = 256
#: Allowance on top of `max_speed_mps * dt` for odom noise before a step counts as an odom reset.
ODOM_STEP_MARGIN_M = 0.05
ODOM_TURN_MARGIN_RAD = 0.1
#: Odom path / turn since the anchor at or below which the robot stood still (odom jitter).
STILL_PATH_M = 0.02
STILL_TURN_RAD = math.radians(2.0)
#: Sightings waiting for odom per robot (3.2 s at 10 Hz); the oldest goes first when full.
PENDING_SIGHTINGS = 32

Pose = tuple[float, float, float]


def _finite(*values) -> bool:
    try:
        return all(not isinstance(v, bool) and isinstance(v, (int, float)) and math.isfinite(v)
                   for v in values)
    except (OverflowError, ValueError, TypeError):
        return False


@dataclass(frozen=True)
class MapPoseConfig:
    """Site config ``fleet.map_pose`` (D-494 3). Out-of-range values are refused at start-up."""

    max_dead_reckon_m: float = 1.5
    max_jump_m: float = 0.15
    max_jump_deg: float = 20.0
    max_odom_age_s: float = 3.0
    max_pair_s: float = 0.25
    #: Two odom samples this close around a sighting are interpolated (1 Hz heartbeat fits).
    max_interp_gap_s: float = 1.2
    #: Robot vs site clock skew stays under 0.1 s (chrony); the lease is the sighting's age budget.
    sighting_lease_s: float = 1.0
    #: A sighting with a worker quality below this is ignored; one without quality passes.
    min_quality: float = 0.5
    #: Odom stamped further ahead of `now` than this is refused (robot clock skew).
    max_odom_future_s: float = 0.5
    #: An odom step faster than this is an odom reset, not motion.
    max_speed_mps: float = 1.0
    #: An odom heading change faster than this is an odom reset, not motion.
    max_turn_rate_dps: float = 360.0
    #: One planned U-turn (180 deg) plus margin bridges without a sighting.
    max_bridge_turn_deg: float = 270.0
    max_anchor_age_s: float = 10.0

    def __post_init__(self) -> None:
        upper = {"max_dead_reckon_m": 20.0, "max_jump_m": 2.0, "max_jump_deg": 180.0,
                 "max_odom_age_s": 30.0, "max_pair_s": 1.0, "max_interp_gap_s": 5.0,
                 "sighting_lease_s": 5.0, "max_odom_future_s": 5.0, "max_speed_mps": 10.0,
                 "max_bridge_turn_deg": 3600.0, "max_turn_rate_dps": 3600.0, "max_anchor_age_s": 600.0}
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
    map_id: Optional[str] = None


@dataclass(frozen=True)
class MapPose:
    x: Optional[float]
    y: Optional[float]
    yaw: Optional[float]
    state: str
    source: Optional[str]
    dead_reckon_m: float
    age_s: Optional[float]
    anchor_age_s: Optional[float] = None
    map_id: Optional[str] = None
    #: Odom samples refused so far and why the last one was (future, out_of_order, malformed).
    odom_refused: int = 0
    odom_refused_reason: Optional[str] = None
    #: Sightings ignored because their map_id is not the active site map frame.
    sightings_filtered_map_id: int = 0
    #: D-517 4: CORE's stamp of the newest odom sample in this pose (the authority's ``pose_stamp``).
    odom_stamp: Optional[float] = None
    #: D-593: what set the anchor, `sighting` or `operator_pin`; None without one.
    anchor_source: Optional[str] = None
    #: D-593: summed |odom heading change| since the anchor (deg), the turn twin of `dead_reckon_m`.
    bridge_turn_deg: float = 0.0


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


def parse_utc(text) -> Optional[float]:
    """Epoch seconds of a UTC ISO stamp (`captured_at` format); None when not one."""
    if not isinstance(text, str):
        return None
    try:
        stamp = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return stamp.timestamp() if stamp.tzinfo is not None else None
    except (ValueError, OverflowError, OSError):
        return None


def odom_from_snapshot(state: Optional[Mapping]) -> Optional[OdomSample]:
    """The snapshot's D-494 2 `odom_pose {x, y, yaw, stamp}`; None when absent or malformed.

    `stamp` is UTC epoch seconds (float, same as sighting `captured_at`); a UTC ISO string is
    accepted for robustness."""
    raw = state.get("odom_pose") if isinstance(state, Mapping) else None
    if not isinstance(raw, Mapping):
        return None
    x, y, yaw, stamp = raw.get("x"), raw.get("y"), raw.get("yaw"), raw.get("stamp")
    stamp = float(stamp) if _finite(stamp) else parse_utc(stamp)
    if stamp is None or not _finite(x, y, yaw):
        return None
    return OdomSample(float(x), float(y), float(yaw), stamp)


def sighting_from_row(row: Optional[Mapping]) -> Optional[Sighting]:
    """An accepted sighting row (`SightingService.accept`); None when malformed."""
    if not isinstance(row, Mapping):
        return None
    robot_id, quality, map_id = row.get("robot_id"), row.get("quality"), row.get("map_id")
    values = (row.get("x"), row.get("y"), row.get("yaw"), row.get("captured_at"))
    if (not isinstance(robot_id, str) or not _finite(*values)
            or not (quality is None or _finite(quality)) or not (map_id is None or isinstance(map_id, str))):
        return None
    return Sighting(robot_id, *(float(v) for v in values),
                    quality=None if quality is None else float(quality), map_id=map_id)


@dataclass(frozen=True)
class _Odom:
    stamp: float
    pose: Pose
    path_m: float      # cumulative chord length since the odom buffer started
    turn_rad: float    # cumulative |dyaw|


@dataclass(frozen=True)
class _Anchor:
    map_pose: Pose
    odom: _Odom
    captured_at: float
    map_id: Optional[str]
    kind: str = SIGHTING


class MapPoseTracker:
    """One robot's map pose. Feed odom and accepted sightings in any order; read `pose(now)`."""

    def __init__(self, robot_id: str, config: MapPoseConfig = MapPoseConfig()) -> None:
        self.robot_id = robot_id
        self.config = config
        self._odom: deque[_Odom] = deque(maxlen=ODOM_BUFFER)
        self._anchor: Optional[_Anchor] = None
        self._pending: deque[Sighting] = deque(maxlen=PENDING_SIGHTINGS)
        self._filtered_map_id = 0
        self._newest_sighting: Optional[float] = None
        self._degraded = False
        self._consistent = 0
        self._refused = 0
        self._refused_reason: Optional[str] = None
        self._epoch = 0   # D-581: odom resets so far (odom_to_map)

    @property
    def sourced(self) -> bool:
        """A sighting for this robot was ever accepted or filtered (D-577 1: a lost pose, not none)."""
        return self._newest_sighting is not None or self._filtered_map_id > 0

    @property
    def latest_odom_stamp(self) -> Optional[float]:
        return self._odom[-1].stamp if self._odom else None

    def moved_since(self, since: float, min_m: float, min_rad: float) -> bool:
        """D-511 2: an odom sample after `since` is more than `min_m` / `min_rad` (a jitter
        deadband) from the last one before it (an odom reset starts over)."""
        if not self._odom or self._odom[-1].stamp < since:
            return False
        base = next((o for o in reversed(self._odom) if o.stamp < since), self._odom[0])
        return any(math.dist(o.pose[:2], base.pose[:2]) > min_m
                   or abs(_wrap(o.pose[2] - base.pose[2])) > min_rad
                   for o in self._odom if o.stamp >= since)

    def odom_to_map(self) -> Optional[tuple[Pose, Pose, float, int]]:
        """D-581: (map <- odom of the current anchor, newest odom pose, the anchor's captured_at,
        odom epoch); None unanchored. The epoch counts odom resets: a transform from another epoch
        belongs to an odom frame that no longer exists. Read beside `pose()` (may it be used)."""
        if self._anchor is None or not self._odom:
            return None
        anchor = self._anchor
        return (compose(anchor.map_pose, relative(anchor.odom.pose, (0.0, 0.0, 0.0))),
                self._odom[-1].pose, anchor.captured_at, self._epoch)

    def refuse_odom(self, reason: str) -> None:
        """Count an odom sample that never reached `add_odom` (malformed snapshot)."""
        self._refused += 1
        self._refused_reason = reason

    def add_odom(self, sample: OdomSample, now: float) -> bool:
        """False for a future, repeated or out-of-order sample (counted in the pose output)."""
        cfg = self.config
        if sample.stamp > now + cfg.max_odom_future_s:
            self.refuse_odom("future")
            return False
        last = self._odom[-1] if self._odom else None
        if last is not None and sample.stamp <= last.stamp:
            if sample.stamp < last.stamp or (sample.x, sample.y, sample.yaw) != last.pose:
                self.refuse_odom("out_of_order")
            return False           # the same sample read twice is not a refusal
        pose = (sample.x, sample.y, sample.yaw)
        if last is not None:
            dt = sample.stamp - last.stamp
            step = math.dist(last.pose[:2], pose[:2])
            turn = abs(_wrap(pose[2] - last.pose[2]))
            if (dt > cfg.max_odom_age_s or now - last.stamp > cfg.max_odom_age_s
                    or step > cfg.max_speed_mps * dt + ODOM_STEP_MARGIN_M
                    or turn > math.radians(cfg.max_turn_rate_dps) * dt + ODOM_TURN_MARGIN_RAD):
                self._reset(sample.stamp)   # gap, resumed after UNKNOWN, or odom reset: anchor is void
                last = None
        if last is None:
            self._odom.append(_Odom(sample.stamp, pose, 0.0, 0.0))
        else:
            self._odom.append(_Odom(sample.stamp, pose, last.path_m + math.dist(last.pose[:2], pose[:2]),
                                    last.turn_rad + abs(_wrap(pose[2] - last.pose[2]))))
        self._resolve(now)
        return True

    def add_sighting(self, sighting: Sighting, now: float, active_map_id: Optional[str] = None) -> bool:
        """False for another robot or map frame, low quality, outside the lease, future or not newer."""
        cfg = self.config
        age = now - sighting.captured_at
        if (sighting.robot_id == self.robot_id and active_map_id is not None
                and sighting.map_id != active_map_id):
            self._filtered_map_id += 1
            return False
        if (sighting.robot_id != self.robot_id
                or (sighting.quality is not None and sighting.quality < cfg.min_quality)
                or age < -MAX_SIGHTING_FUTURE_S or age > cfg.sighting_lease_s
                or (self._newest_sighting is not None and sighting.captured_at <= self._newest_sighting)):
            return False
        self._newest_sighting = sighting.captured_at
        self._pending.append(sighting)   # in captured_at order; never displaces a waiting one
        self._resolve(now)
        return True

    def add_pin(self, pose: Pose, now: float, map_id: Optional[str] = None) -> Optional[str]:
        """D-593: anchor on an operator's map pose at the newest odom sample.

        Returns None when anchored, else why not: `ODOM_STALE` (no odom within `max_odom_age_s`
        of `now`) or `POSE_INVALID`. Pending sightings captured before `now` are dropped."""
        if not _finite(*pose, now):
            return "POSE_INVALID"
        self._resolve(now)
        latest = self._odom[-1] if self._odom else None
        if latest is None or not 0.0 <= now - latest.stamp <= self.config.max_odom_age_s:
            return "ODOM_STALE"
        while self._pending and self._pending[0].captured_at < now:
            self._pending.popleft()
        self._anchor = _Anchor((float(pose[0]), float(pose[1]), _wrap(float(pose[2]))), latest, now,
                               map_id, OPERATOR_PIN)
        self._degraded, self._consistent = False, RECOVER_AFTER
        return None

    def pose(self, now: float, active_map_id: Optional[str] = None) -> MapPose:
        cfg = self.config
        self._resolve(now)
        diag = {"odom_refused": self._refused, "odom_refused_reason": self._refused_reason,
                "sightings_filtered_map_id": self._filtered_map_id}
        latest = self._odom[-1] if self._odom else None
        anchor = self._anchor
        if anchor is None or latest is None or now - latest.stamp > cfg.max_odom_age_s:
            return MapPose(None, None, None, UNKNOWN, None, 0.0, None, **diag)
        anchor_age = max(0.0, now - anchor.captured_at)
        if latest.stamp <= anchor.odom.stamp:
            (x, y, yaw), source, bridged, turned = anchor.map_pose, anchor.kind, 0.0, 0.0
            age = anchor_age
        else:
            x, y, yaw = compose(anchor.map_pose, relative(anchor.odom.pose, latest.pose))
            source, age = BRIDGED, max(0.0, now - latest.stamp)
            bridged = latest.path_m - anchor.odom.path_m
            turned = latest.turn_rad - anchor.odom.turn_rad
        degraded = (self._degraded or bridged > cfg.max_dead_reckon_m
                    or (active_map_id is not None and anchor.map_id != active_map_id)
                    or turned > math.radians(cfg.max_bridge_turn_deg) or anchor_age > cfg.max_anchor_age_s)
        return MapPose(x, y, yaw, DEGRADED if degraded else LOCALIZED, source, bridged, age,
                       anchor_age, anchor.map_id, odom_stamp=latest.stamp, anchor_source=anchor.kind,
                       bridge_turn_deg=math.degrees(turned), **diag)

    def _reset(self, since: float) -> None:
        self._epoch += 1
        self._odom.clear()
        self._anchor = None
        while self._pending and self._pending[0].captured_at < since:
            self._pending.popleft()        # seen in the odom frame that just ended
        self._degraded, self._consistent = False, 0

    def _resolve(self, now: float) -> None:
        cfg = self.config
        while self._pending:
            sighting = self._pending[0]
            t = sighting.captured_at
            after = next((o for o in self._odom if o.stamp >= t), None)
            if after is None:
                if now - t <= cfg.max_odom_age_s:
                    return                    # its odom has not arrived yet; later ones wait too
                self._pending.popleft()       # stale while waiting
                continue
            self._pending.popleft()
            before = next((o for o in reversed(self._odom) if o.stamp <= t), None)
            if before is not None and after.stamp - before.stamp <= cfg.max_interp_gap_s:
                odom = _interpolate(before, after, t)
            else:
                near = [o for o in (before, after) if o is not None and abs(o.stamp - t) <= cfg.max_pair_s]
                odom = min(near, key=lambda o: abs(o.stamp - t)) if near else None
            if odom is not None:
                self._apply(sighting, odom)

    def _apply(self, sighting: Sighting, odom: _Odom) -> None:
        cfg = self.config
        seen = (sighting.x, sighting.y, sighting.yaw)
        anchor = self._anchor
        if anchor is not None and sighting.captured_at < anchor.captured_at:
            return                            # D-593: seen before the operator pin it would undo
        if anchor is not None and anchor.map_id != sighting.map_id:
            anchor = None                     # another map frame: start over from this sighting
        if anchor is None:
            self._degraded, self._consistent = True, 0       # a first anchor is not yet confirmed
        else:
            predicted = compose(anchor.map_pose, relative(anchor.odom.pose, odom.pose))
            jumped = (math.dist(predicted[:2], seen[:2]) > cfg.max_jump_m
                      or abs(_wrap(predicted[2] - seen[2])) > math.radians(cfg.max_jump_deg))
            path = odom.path_m - anchor.odom.path_m
            turn = odom.turn_rad - anchor.odom.turn_rad
            # A robot that stood still since the anchor has no odom drift to bound: two agreeing
            # sightings any time apart re-localize it (site 2026-10-10: rosy_40 parked, marker read
            # 1 frame in 8, never LOCALIZED again). Same odom epoch is implied: a reset drops the anchor.
            still = path <= STILL_PATH_M and turn <= STILL_TURN_RAD
            stretched = (path > cfg.max_dead_reckon_m or turn > math.radians(cfg.max_bridge_turn_deg)
                         or (sighting.captured_at - anchor.captured_at > cfg.max_anchor_age_s and not still))
            if jumped:
                self._degraded, self._consistent = True, 0
            else:
                if stretched:
                    self._degraded, self._consistent = True, 0
                self._consistent = min(self._consistent + 1, RECOVER_AFTER)
                if self._consistent >= RECOVER_AFTER:
                    self._degraded = False
        self._anchor = _Anchor(seen, odom, sighting.captured_at, sighting.map_id)


def _interpolate(before: _Odom, after: _Odom, t: float) -> _Odom:
    if after.stamp == before.stamp:
        return before
    k = (t - before.stamp) / (after.stamp - before.stamp)
    (bx, by, byaw), (ax, ay, _) = before.pose, after.pose
    pose = (bx + k * (ax - bx), by + k * (ay - by), _wrap(byaw + k * _wrap(after.pose[2] - byaw)))
    return _Odom(t, pose, before.path_m + k * (after.path_m - before.path_m),
                 before.turn_rad + k * (after.turn_rad - before.turn_rad))
