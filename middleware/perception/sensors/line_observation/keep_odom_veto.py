"""D-556 candidate (default off): fresh odometry vetoes a carried one-sided lane boundary.

LaneKeeper (D-364) stays camera-only and is the keeper the node builds unless
`lane_odom_veto_enabled` is true. This keeper judges the frame LaneKeeper just read: when the
boundary it steers from is the one selected last frame, and both that line carried to the new
odometry pose and the line in the image lie past the robot on the far side of the side it kept,
the robot crossed it. The hold then latches for the life of the keeper (D-556 rule 2: a camera
gap, a reset or a `both` reading does not release it). Odometry never approves a boundary.
"""
import math

from .sensing.perception.lane_bev import ODOM_MAX_STEP_M
from .sensing.perception.lane_keep import SIDE_X_M, TRACK_HEADING_RAD, TRACK_LATERAL_M, LaneKeeper

REASON = 'odom_side_conflict'
#: D-556 rule 1: the carried line and the seen line must both lie this far on the other side of
#: the robot. An image-side tolerance from the ADR, not robot geometry (no URDF source).
SIDE_CONFLICT_MARGIN_M = 0.01


def _finite_pose(pose):
    try:
        pose = tuple(float(v) for v in pose) if pose is not None else None
    except (TypeError, ValueError):
        return None
    return pose if pose is not None and len(pose) == 3 and all(math.isfinite(v) for v in pose) else None


class OdomVetoLaneKeeper(LaneKeeper):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.side_conflict_hold = False
        self._selected_line = None  # (lateral at SIDE_X_M, heading rad, side, odom pose) of the last frame

    def _forget(self) -> None:
        super()._forget()
        self._selected_line = None

    def update(self, bgr, ground, *, pose=None, **kwargs):
        observation = super().update(bgr, ground, **kwargs)
        pose = _finite_pose(pose)
        boundaries = self.last["boundaries"]
        selected = (next((r for r in boundaries if r.get("selected")), None)
                    if observation is not None and self.last["strategy"] in ("left_only", "right_only") else None)
        if (not self.side_conflict_hold and selected is not None and pose is not None
                and self._selected_line is not None):
            self.side_conflict_hold = self._crossed(selected, boundaries, pose)
        if self.side_conflict_hold:
            self.last.update(strategy="none", reason=REASON, target_m=None, target_px=None)
            self.last.pop("error", None)
            self.last.pop("confidence", None)
            for record in boundaries + self.last["candidates"]:
                record["selected"] = False
            self._previous_target = None
            self._tracked = []
            self._selected_line = None
            return None
        self._selected_line = ((selected["y_at_side_x_m"], math.radians(selected["heading_deg"]), selected["side"], pose)
                               if selected is not None and pose is not None else None)
        return observation

    def _crossed(self, selected, boundaries, pose) -> bool:
        prior_lateral, prior_heading, prior_side, prior_pose = self._selected_line
        step = math.hypot(pose[0] - prior_pose[0], pose[1] - prior_pose[1])
        turn = abs(math.remainder(pose[2] - prior_pose[2], 2.0 * math.pi))
        if max(step, self.last["lane_width_m"] / 2.0 * turn) > ODOM_MAX_STEP_M:
            return False  # an odometry jump judges nothing
        matches = [r for r in boundaries
                   if abs(r["y_at_side_x_m"] - prior_lateral) <= TRACK_LATERAL_M
                   and abs(math.radians(r["heading_deg"]) - prior_heading) <= TRACK_HEADING_RAD]
        if not selected.get("tracked") or selected["side"] != prior_side or len(matches) != 1 or matches[0] is not selected:
            return False  # not provably the boundary selected last frame
        # The prior line (a point on it at SIDE_X_M and its direction, in odom) read at the new pose's SIDE_X_M.
        angle = prior_pose[2] + prior_heading
        x = prior_pose[0] + SIDE_X_M * math.cos(prior_pose[2]) - prior_lateral * math.sin(prior_pose[2])
        y = prior_pose[1] + SIDE_X_M * math.sin(prior_pose[2]) + prior_lateral * math.cos(prior_pose[2])
        qx, qy = pose[0] + SIDE_X_M * math.cos(pose[2]), pose[1] + SIDE_X_M * math.sin(pose[2])
        predicted = -(x - qx) * math.sin(angle) + (y - qy) * math.cos(angle)
        sign = 1.0 if prior_side == "left" else -1.0
        return (sign * predicted < -SIDE_CONFLICT_MARGIN_M
                and sign * selected["y_at_side_x_m"] < -SIDE_CONFLICT_MARGIN_M)
