"""One straight corridor held in odometry across a missing drivable frame.

The path is the near centre and its heading. A new frame replaces that path only
when it is the same centre corridor, or when three frames agree on a new heading.
During a gap the pursuit point is 0.10 m ahead of the robot's projection on the
frozen heading. The far end only caps the length, so moving it sideways does not
steer. Travel is measured from the first missing frame, and the budgets are the
committed length, 0.25 m, and 2.5 s.
"""
from __future__ import annotations

import math

COMMIT_FRAMES = 3
HEADING_GATE_RAD = math.radians(12.0)
LOOKAHEAD_M = 0.10
SLOW_M = 0.25
HOLD_S = 2.5
CONF_NEAR = 0.90
CONF_SLOW = 0.68

_FORBID_PREFIX = ("drivable_pivot_", "drivable_turn_", "drivable_off_line_")
_FORBID_STRATEGY = {"drivable_crosswalk_straight", "drivable_closed"}
_FORBID_REASON = {"way_beyond_line", "drivable_closed"}


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


def _forbidden(info):
    strategy = info.get("strategy") or ""
    reason = info.get("reason") or ""
    if info.get("straddle"):
        return True
    if reason in _FORBID_REASON or strategy in _FORBID_STRATEGY:
        return True
    return strategy.startswith(_FORBID_PREFIX)


def _centre_heading(pose, info):
    """Heading of one drivable_centre frame, or None when the frame cannot commit."""
    if info.get("strategy") != "drivable_centre" or info.get("straddle") or info.get("reason"):
        return None
    near = info.get("near_centre_m")
    if near is None or info.get("ahead_m") is None:
        return None
    return pose[2] + math.atan2(near[1], near[0])


class ExpectedPath:
    """Odom hypothesis. `half` is the lane half-width that turns a lateral offset into error."""

    def __init__(self, half):
        self.half = float(half)
        self.end_m = None
        self._anchor = None
        self._heading = None
        self._length = 0.0
        self._committed = False
        self._dropped = False
        self._streak_heading = None
        self._streak = 0
        self._replace_heading = None
        self._replace = 0
        self._pose = None
        self._stamp = None
        self._loss_pose = None
        self._loss_stamp = None

    def update(self, pose, stamp, info):
        """Accept one way frame. A committed path stays until three new headings agree."""
        if pose is None or stamp is None:
            self._clear()
            return self._view("dropped")
        if self._jumped(pose, stamp):
            self._clear()
            self._remember(pose, stamp)
            return self._view("dropped")
        self._remember(pose, stamp)
        if _forbidden(info):
            self._clear()
            return self._view("dropped")
        heading = _centre_heading(pose, info)
        if heading is None:
            if self._committed:
                self._replace = 0
                self._replace_heading = None
                return self._steer(pose, "held")
            self._streak = 0
            self._streak_heading = None
            return self._view("dropped" if self._dropped else None)
        if not self._committed:
            if (self._streak_heading is None
                    or _angle(heading - self._streak_heading) > HEADING_GATE_RAD):
                self._streak_heading = heading
                self._streak = 1
            else:
                self._streak += 1
            if self._streak < COMMIT_FRAMES:
                return self._view(None)
            self._accept(pose, info, heading)
            return self._steer(pose, "live")
        if _angle(heading - self._heading) <= HEADING_GATE_RAD:
            self._accept(pose, info, heading)
            return self._steer(pose, "live")
        if (self._replace_heading is None
                or _angle(heading - self._replace_heading) > HEADING_GATE_RAD):
            self._replace_heading = heading
            self._replace = 1
        else:
            self._replace += 1
        if self._replace >= COMMIT_FRAMES:
            self._accept(pose, info, heading)
            return self._steer(pose, "live")
        return self._steer(pose, "held")

    def hold(self, pose, stamp):
        """Republish the committed corridor after one missing frame, moved by odometry."""
        if pose is None or stamp is None:
            self._clear()
            return self._view("dropped")
        if self._jumped(pose, stamp):
            self._clear()
            self._remember(pose, stamp)
            return self._view("dropped")
        self._remember(pose, stamp)
        # A missing frame breaks a run of new headings, and an uncommitted streak.
        # Those frames were not consecutive.
        self._replace = 0
        self._replace_heading = None
        if not self._committed:
            self._streak = 0
            self._streak_heading = None
            return self._view("dropped" if self._dropped else None)
        if self._loss_pose is None:
            self._loss_pose = self._pose
            self._loss_stamp = self._stamp
        travel = _dist(self._pose, self._loss_pose)
        elapsed = self._stamp - self._loss_stamp
        if travel >= self._length or travel >= SLOW_M or elapsed >= HOLD_S:
            self._clear()
            return self._view("dropped")
        view = self._steer(pose, "held")
        view["s_m"] = travel
        view["confidence"] = CONF_NEAR if travel < LOOKAHEAD_M else CONF_SLOW
        return view

    def _accept(self, pose, info, heading):
        near = info["near_centre_m"]
        anchor = _world(near, pose)
        length = min(max(0.0, float(info["ahead_m"])), SLOW_M)
        self._anchor = anchor
        self._heading = heading
        self._length = length
        self.end_m = (anchor[0] + length * math.cos(heading),
                      anchor[1] + length * math.sin(heading))
        self._committed = True
        self._dropped = False
        self._streak = 0
        self._streak_heading = None
        self._replace = 0
        self._replace_heading = None
        self._loss_pose = None
        self._loss_stamp = None

    def _steer(self, pose, state):
        hx, hy = math.cos(self._heading), math.sin(self._heading)
        # Along-track cap only. end_m's lateral part is ignored on purpose.
        cap = ((self.end_m[0] - self._anchor[0]) * hx
               + (self.end_m[1] - self._anchor[1]) * hy)
        along = ((pose[0] - self._anchor[0]) * hx
                 + (pose[1] - self._anchor[1]) * hy)
        pursuit = min(along + LOOKAHEAD_M, cap)
        target = (self._anchor[0] + pursuit * hx, self._anchor[1] + pursuit * hy)
        start = _body(self._anchor, pose)
        end = _body((self._anchor[0] + cap * hx, self._anchor[1] + cap * hy), pose)
        body = _body(target, pose)
        error = None if self.half <= 0.0 else -body[1] / self.half
        return self._view(state, error=error, target_m=body,
                          path_m=(start, end))

    def _jumped(self, pose, stamp):
        if self._pose is None:
            return False
        if float(stamp) < self._stamp:
            return True
        return _dist(pose, self._pose) > SLOW_M

    def _remember(self, pose, stamp):
        self._pose = (float(pose[0]), float(pose[1]), float(pose[2]))
        self._stamp = float(stamp)

    def _clear(self):
        self._committed = False
        self._dropped = True
        self._anchor = None
        self._heading = None
        self._length = 0.0
        self.end_m = None
        self._streak = 0
        self._streak_heading = None
        self._replace = 0
        self._replace_heading = None
        self._loss_pose = None
        self._loss_stamp = None

    def _view(self, state, error=None, confidence=None, target_m=None, path_m=None, s_m=0.0):
        return {"state": state, "error": error, "confidence": confidence,
                "target_m": target_m, "path_m": path_m, "s_m": s_m,
                "committed": self._committed}
