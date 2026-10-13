"""D-708: observed centre geometry held in odometry across a drivable gap."""
from __future__ import annotations

import math

from ..drivable.drivable_steer import pursuit_error

COMMIT_FRAMES = 3
HEADING_GATE_RAD = math.radians(12.0)
LOOKAHEAD_M = 0.10
SLOW_M = 0.25
HOLD_S = 2.5
CONF_NEAR = 0.90
CONF_SLOW = 0.68

def _angle(delta):
    return abs(math.atan2(math.sin(delta), math.cos(delta)))


def _dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _world(point, pose):
    yaw = pose[2]
    return (pose[0] + point[0] * math.cos(yaw) - point[1] * math.sin(yaw),
            pose[1] + point[0] * math.sin(yaw) + point[1] * math.cos(yaw))


def _body(point, pose):
    dx, dy = point[0] - pose[0], point[1] - pose[1]
    yaw = pose[2]
    return (dx * math.cos(yaw) + dy * math.sin(yaw),
            -dx * math.sin(yaw) + dy * math.cos(yaw))


def _valid_pose(pose, stamp):
    try:
        return len(pose) == 3 and math.isfinite(stamp) and all(math.isfinite(v) for v in pose)
    except (TypeError, ValueError):
        return False


def _forbidden(info):
    return bool(info.get('strategy') != 'drivable_centre' or info.get('reason') or info.get('straddle'))


def _geometry(pose, info):
    """An ordered, measured centre polyline and its near tangent; never a point bearing."""
    if info.get('strategy') != 'drivable_centre' or info.get('reason') or info.get('straddle'):
        return None
    raw = info.get('centre_path_m')
    try:
        if raw is None or not 2 <= len(raw) <= 32:
            return None
        points = tuple((float(p[0]), float(p[1])) for p in raw if len(p) == 2)
        if len(points) != len(raw) or any(not all(math.isfinite(v) for v in p) or p[0] <= 0 for p in points):
            return None
        if any(a[0] >= b[0] for a, b in zip(points, points[1:])):
            return None
    except (TypeError, ValueError, IndexError):
        return None
    a, b = points[:2]
    heading = pose[2] + math.atan2(b[1] - a[1], b[0] - a[0])
    return tuple(_world(p, pose) for p in points), heading


class ExpectedPath:
    """The observed path owns gap budgets; CORE still owns the final motion gates."""

    def __init__(self, half, *, error_for_target=pursuit_error):
        self.half = float(half)
        self._error_for_target = error_for_target
        self._path = None
        self._heading = None
        self._length = 0.
        self._committed = False
        self._dropped = False
        self._streak_heading = self._replace_heading = None
        self._streak = self._replace = 0
        self._pose = self._stamp = None
        self._observation_stamp = self._accepted_stamp = None
        self._travel = 0.

    def update(self, pose, stamp, info, *, observation_stamp=None, current_pose=None):
        """Only independent camera geometry can commit or refresh the measured path."""
        current = pose if current_pose is None else current_pose
        observed = stamp if observation_stamp is None else observation_stamp
        if not _valid_pose(pose, observed) or not _valid_pose(current, stamp) or observed > stamp:
            self._clear()
            return self._view('dropped')
        if self._jumped(current, stamp):
            self._clear()
            self._remember(current, stamp)
            return self._view('dropped')
        self._remember(current, stamp)
        if _forbidden(info):
            self._clear()
            return self._view('dropped')
        if self._observation_stamp is not None and observed <= self._observation_stamp:
            return self._held(current, stamp)
        self._observation_stamp = observed
        geometry = _geometry(pose, info)
        if geometry is None:
            self._clear()
            return self._view('dropped')
        path, heading = geometry
        if not self._committed:
            if self._streak_heading is None or _angle(heading - self._streak_heading) > HEADING_GATE_RAD:
                self._streak_heading, self._streak = heading, 1
            else:
                self._streak += 1
            if self._streak < COMMIT_FRAMES:
                return self._view(None)
        elif _angle(heading - self._heading) > HEADING_GATE_RAD:
            if self._replace_heading is None or _angle(heading - self._replace_heading) > HEADING_GATE_RAD:
                self._replace_heading, self._replace = heading, 1
            else:
                self._replace += 1
            if self._replace < COMMIT_FRAMES:
                return self._held(current, stamp)
        self._path, self._heading = path, heading
        self._length = min(SLOW_M, sum(_dist(a, b) for a, b in zip(path, path[1:])))
        self._accepted_stamp = observed
        self._travel = _dist(pose, current)
        self._committed, self._dropped = True, False
        self._streak = self._replace = 0
        self._streak_heading = self._replace_heading = None
        return self._steer(current, 'live')

    def hold(self, pose, stamp):
        """Move the observed shape into this pose without refreshing its age or distance."""
        self._streak = self._replace = 0
        self._streak_heading = self._replace_heading = None
        return self._held(pose, stamp)

    def _held(self, pose, stamp):
        if not _valid_pose(pose, stamp) or self._jumped(pose, stamp):
            self._clear()
            if _valid_pose(pose, stamp):
                self._remember(pose, stamp)
            return self._view('dropped')
        self._remember(pose, stamp)
        if not self._committed:
            return self._view('dropped' if self._dropped else None)
        if self._travel >= self._length or stamp - self._accepted_stamp >= HOLD_S:
            self._clear()
            return self._view('dropped')
        return self._steer(pose, 'held')

    def _steer(self, pose, state):
        segments = []
        walked = 0.
        for a, b in zip(self._path, self._path[1:]):
            dx, dy = b[0] - a[0], b[1] - a[1]
            length = math.hypot(dx, dy)
            along = ((pose[0] - a[0]) * dx + (pose[1] - a[1]) * dy) / (length * length)
            t = max(0., min(1., along))
            projection = (a[0] + t * dx, a[1] + t * dy)
            lateral = _dist(pose, (a[0] + along * dx, a[1] + along * dy))
            segments.append((_dist(pose, projection), walked + t * length, a, b, length, walked, lateral))
            walked += length
        nearest = min(segments, key=lambda segment: segment[0])
        station = min(nearest[1] + LOOKAHEAD_M, walked)
        if nearest[1] >= walked or nearest[6] > self.half or self.half <= 0:
            self._clear()
            return self._view('dropped')
        target = None
        for _, _, a, b, length, start, _lateral in segments:
            if station <= start + length:
                f = (station - start) / length
                target = _body((a[0] + f * (b[0] - a[0]), a[1] + f * (b[1] - a[1])), pose)
                break
        if target is None or target[0] <= 0:
            self._clear()
            return self._view('dropped')
        confidence = CONF_NEAR if self._travel < LOOKAHEAD_M else CONF_SLOW
        return self._view(state, error=self._error_for_target(*target, confidence), confidence=confidence,
                          target_m=target, path_m=tuple(_body(p, pose) for p in self._path), s_m=self._travel)

    def _jumped(self, pose, stamp):
        if self._pose is None:
            return False
        return (stamp < self._stamp or _dist(pose, self._pose) > SLOW_M
                or _angle(pose[2] - self._pose[2]) >= math.pi / 2)

    def _remember(self, pose, stamp):
        if self._pose is not None:
            self._travel += _dist(pose, self._pose)
        self._pose, self._stamp = tuple(pose), float(stamp)

    def _clear(self):
        self._committed, self._dropped = False, True
        self._path = self._heading = self._accepted_stamp = None
        self._length = self._travel = 0.
        self._streak = self._replace = 0
        self._streak_heading = self._replace_heading = None
        self._pose = self._stamp = None

    def _view(self, state, error=None, confidence=None, target_m=None, path_m=None, s_m=0.):
        return dict(state=state, error=error, confidence=confidence, target_m=target_m,
                    path_m=path_m, s_m=s_m, committed=self._committed)
