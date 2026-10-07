"""D-491: crosswalk zones the IR lane guard may rest in, anchored in odom at the image pose.

The camera reports a crosswalk's near and far edge ahead of base_footprint at the image
stamp; by the time the IR row reaches it the camera no longer sees it. Each zone is kept
against the odom pose of its image and checked against the IR row's position in that
pose's frame: along the heading inside [near, far] (capped) plus margin, across within
the lane corridor, and heading within MAX_TURN_RAD of the image's. A zone exists only for
CALIBRATED or GAZEBO ground with a bounded projection uncertainty, and dies with the
D-468 pose trail epoch, once passed, after a turn, or off the corridor. One rest lasts at
most the rest budget of measured travel; after that the guard must read clear once before
it may rest again, so chained detections cannot extend it.
"""
from __future__ import annotations

import math

from core_features.line_follow.lane_return import _angle

#: Same admission bounds as D-468 lane evidence (lane_return_evidence.LaneReturnEvidence).
MAX_UNCERTAINTY_M = .015
EVIDENCE_TTL_S = .3
MAX_ZONES = 8
#: A crosswalk is crossed straight; a larger heading change means another road.
MAX_TURN_RAD = .3
#: Lane half-width (0.0925 m, D-364 keep) rounded up: the IR row must stay in this corridor.
CORRIDOR_HALF_M = .10


class CrosswalkZones:
    def __init__(self):
        self._zones = []
        self._epoch = None
        self._last = None
        self._odometer = 0.
        self._rest_from = None
        self._spent = False

    def clear(self):
        self._zones.clear()
        self._epoch = self._last = self._rest_from = None
        self._odometer = 0.
        self._spent = False

    def observe(self, evidence, *, epoch, received_at):
        crosswalk = evidence.crosswalk
        if (crosswalk is None or evidence.ground_source not in ("CALIBRATED", "GAZEBO")
                or evidence.uncertainty_m is None or evidence.uncertainty_m > MAX_UNCERTAINTY_M):
            return
        self._zones.append(dict(epoch=epoch, stamp_ns=round(evidence.stamp*1e9), near=crosswalk.near_m,
                                far=crosswalk.far_m, uncertainty=evidence.uncertainty_m,
                                received_at=received_at, anchor=None))
        del self._zones[:-MAX_ZONES]

    def holds(self, evidence, *, now, firing, ir_x, max_length, odom_error_fraction):
        """Call every guarded tick. True while the guard fires inside a zone within the rest budget."""
        if self._epoch != evidence.epoch:  # zones carry their own epoch; restart the rest state
            self._epoch, self._last, self._rest_from, self._odometer, self._spent = evidence.epoch, None, None, 0., False
        samples = evidence.trail.samples
        current = samples[-1] if samples else None
        if current is None or not 0 <= now-current.received_at <= EVIDENCE_TTL_S:
            self._rest_from = None
            return False
        if self._last is not None:
            self._odometer += math.hypot(current.x-self._last.x, current.y-self._last.y)
        self._last = current
        ix = current.x+math.cos(current.yaw)*ir_x
        iy = current.y+math.sin(current.yaw)*ir_x
        inside = False
        for zone in list(self._zones):
            if zone["epoch"] != evidence.epoch:
                self._zones.remove(zone)
                continue
            if zone["anchor"] is None:
                zone["anchor"] = evidence._image_pose(zone["stamp_ns"])
                if zone["anchor"] is None:
                    if now-zone["received_at"] > EVIDENCE_TTL_S:
                        self._zones.remove(zone)
                    continue
            anchor = zone["anchor"]
            c, s = math.cos(anchor.yaw), math.sin(anchor.yaw)
            along = c*(ix-anchor.x)+s*(iy-anchor.y)
            across = -s*(ix-anchor.x)+c*(iy-anchor.y)
            margin = zone["uncertainty"]+odom_error_fraction*math.hypot(current.x-anchor.x, current.y-anchor.y)
            far = min(zone["far"], zone["near"]+max_length)
            if (along > far+margin or abs(_angle(current.yaw-anchor.yaw)) > MAX_TURN_RAD
                    or abs(across) > CORRIDOR_HALF_M+margin):
                self._zones.remove(zone)
            elif along >= zone["near"]-margin:
                inside = True
        if not firing:
            self._rest_from, self._spent = None, False
            return False
        if not inside or self._spent:
            self._rest_from = None
            return False
        if self._rest_from is None:
            self._rest_from = self._odometer
        budget = max_length*(1+2*odom_error_fraction)+2*MAX_UNCERTAINTY_M
        if self._odometer-self._rest_from > budget:
            self._zones.clear()
            self._rest_from, self._spent = None, True
            return False
        return True
