"""D-468 image/odometry synchronization and bounded geometric admission.

Source clocks identify poses and images; receipt clocks measure freshness only.
No transport imports, command integration or inferred calibration uncertainty.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from core_common.protocol.lane_containment import LaneContainmentEvidence
from core_features.line_follow.lane_return import Boundary, Corridor, Pose, PoseTrail, _angle, _finite
from core_features.line_follow.model import SOURCE_FUTURE_TOLERANCE_S


@dataclass(frozen=True)
class ReturnEvidenceView:
    reason: str
    epoch: int
    pose: Pose | None = None
    image_pose: Pose | None = None
    corridor: Corridor | None = None
    source_stamp_ns: int | None = None
    received_at: float | None = None


class LaneReturnEvidence:
    MAX_EXTRAPOLATION_M = .3
    MAX_UNCERTAINTY_M = .015
    MAX_POSE_GAP_NS = 150_000_000

    def __init__(self):
        self.trail = PoseTrail()
        self.epoch = 0
        self._lane = None
        self._received_at = None
        self._source_stamp_ns = None
        self._high_water_ns = None

    def reset(self):
        self.trail.samples.clear()
        self.epoch += 1
        self._lane = self._received_at = self._source_stamp_ns = self._high_water_ns = None

    def invalidate_lane(self):
        self._lane = self._received_at = self._source_stamp_ns = None

    def observe_pose(self, *, stamp_ns, source_now_ns, frame, x, y, yaw, received_at):
        if type(stamp_ns) is not int or type(source_now_ns) is not int:
            raise ValueError("original nanosecond timestamps required")
        _finite(received_at)
        age = (source_now_ns-stamp_ns)/1e9
        if age < -SOURCE_FUTURE_TOLERANCE_S:
            return False  # refuse the sample only; the trail and epoch stay
        age = max(0., age)
        if age > .3:
            self.reset()
            return False
        pose = Pose(received_at-age, stamp_ns, frame, x, y, yaw)
        continuous = self.trail.add(pose)
        if not continuous:
            self.epoch += 1
            self._lane = self._received_at = self._source_stamp_ns = self._high_water_ns = None
        return continuous

    def observe_lane(self, evidence, *, received_at):
        if not isinstance(evidence, LaneContainmentEvidence):
            raise ValueError("typed lane evidence required")
        _finite(received_at)
        stamp_ns = round(evidence.stamp*1e9)
        if self._high_water_ns is not None and stamp_ns <= self._high_water_ns:
            return False
        self._lane, self._received_at = evidence, received_at
        self._source_stamp_ns = self._high_water_ns = stamp_ns
        return True

    def _image_pose(self, stamp_ns):
        samples = list(self.trail.samples)
        for pose in samples:
            if pose.stamp_ns == stamp_ns:
                return pose
        for a, b in zip(samples, samples[1:]):
            gap = b.stamp_ns-a.stamp_ns
            if a.stamp_ns < stamp_ns < b.stamp_ns and 0 < gap <= self.MAX_POSE_GAP_NS:
                fraction = (stamp_ns-a.stamp_ns)/gap
                return Pose(a.received_at+(b.received_at-a.received_at)*fraction,
                    stamp_ns, a.frame, a.x+(b.x-a.x)*fraction, a.y+(b.y-a.y)*fraction,
                    a.yaw+_angle(b.yaw-a.yaw)*fraction)
        return None

    @staticmethod
    def _edge_at_current(edge, image_pose, current, uncertainty):
        # Map two points through the original image pose into the current body frame.
        points = []
        ci, si = math.cos(image_pose.yaw), math.sin(image_pose.yaw)
        cc, sc = math.cos(current.yaw), math.sin(current.yaw)
        for x in (edge.observed_x_min_m, edge.observed_x_max_m):
            y = edge.slope*x+edge.intercept_m
            wx, wy = image_pose.x+ci*x-si*y, image_pose.y+si*x+ci*y
            dx, dy = wx-current.x, wy-current.y
            points.append((cc*dx+sc*dy, -sc*dx+cc*dy))
        (x1, y1), (x2, y2) = points
        if abs(x2-x1) < .01:
            return None, None
        slope = (y2-y1)/(x2-x1)
        # Erode the corridor by measured uncertainty, preserving nominal labelling.
        shift = uncertainty*math.hypot(1, slope)*(1 if edge.side == "right" else -1)
        return Boundary(slope, y1-slope*x1+shift), (min(x1, x2), max(x1, x2))

    def snapshot(self, *, now, body):
        _finite(now)
        current = self.trail.samples[-1] if self.trail.samples else None
        base = dict(epoch=self.epoch, pose=current, source_stamp_ns=self._source_stamp_ns,
                    received_at=self._received_at)
        if current is None or not 0 <= now-current.received_at <= .3:
            return ReturnEvidenceView("pose_stale", **base)
        if self._lane is None or not 0 <= now-self._received_at <= .3:
            return ReturnEvidenceView("lane_stale", **base)
        evidence = self._lane
        if evidence.uncertainty_m is None:
            return ReturnEvidenceView("projection_uncertainty_unknown", **base)
        if evidence.uncertainty_m > self.MAX_UNCERTAINTY_M:
            return ReturnEvidenceView("projection_uncertainty_excessive", **base)
        image_pose = self._image_pose(self._source_stamp_ns)
        if image_pose is None:
            return ReturnEvidenceView("image_pose_unmatched", **base)
        if body is None:
            return ReturnEvidenceView("body_geometry_unknown", image_pose=image_pose, **base)
        edges = {}
        for edge in evidence.boundaries:
            boundary, support = self._edge_at_current(edge, image_pose, current, evidence.uncertainty_m)
            if support is None or (support[0]-body.rear > self.MAX_EXTRAPOLATION_M or
                                   body.front-support[1] > self.MAX_EXTRAPOLATION_M):
                return ReturnEvidenceView("boundary_support_insufficient", image_pose=image_pose, **base)
            edges[edge.side] = boundary
        if set(edges) != {"left", "right"}:
            return ReturnEvidenceView("complete_corridor_unconfirmed", image_pose=image_pose, **base)
        try:
            corridor = Corridor(edges["left"], edges["right"], evidence.geometry_id, evidence.uncertainty_m)
        except ValueError:
            return ReturnEvidenceView("boundary_order_invalid", image_pose=image_pose, **base)
        return ReturnEvidenceView("ready", image_pose=image_pose, corridor=corridor, **base)
