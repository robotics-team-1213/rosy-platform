"""D-491: crosswalk zones the IR lane guard may rest in, anchored in odom at the image pose.

The camera saw the crosswalk ahead; the IR row reaches it after the camera lost it. A zone
needs a bounded projection uncertainty (any ground, as D-468), is kept at its image's odom pose,
and dies with the pose trail epoch, once passed, after a turn or off the lane corridor.
One rest is capped by measured travel and re-arms only after the guard reads clear.
"""
from __future__ import annotations

import math

from core_features.line_follow.recovery.lane_return import _angle

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
        self.clear()

    def clear(self):
        self._zones, self._epoch, self._last, self._rest_from, self._odometer, self._spent = [], None, None, None, 0., False

    def observe(self, evidence, *, epoch, received_at):
        crosswalk = evidence.crosswalk
        if crosswalk is None or evidence.uncertainty_m is None or evidence.uncertainty_m > MAX_UNCERTAINTY_M:
            return
        # D-573: the lane corridor across the zone (inner paint edges at its near/far ends, body
        # frame at the image), None when a side was not seen. Only the crosswalk gate reads it.
        edges = {b.side: [b.slope*x+b.intercept_m for x in (crosswalk.near_m, crosswalk.far_m)]
                 for b in evidence.boundaries}
        self._zones.append(dict(epoch=epoch, stamp_ns=round(evidence.stamp*1e9), near=crosswalk.near_m,
                                far=crosswalk.far_m, uncertainty=evidence.uncertainty_m,
                                received_at=received_at, anchor=None,
                                left=max(edges["left"]) if "left" in edges else None,
                                right=min(edges["right"]) if "right" in edges else None))
        del self._zones[:-MAX_ZONES]

    def holds(self, evidence, *, now, guard, ir_x, max_length, odom_error_fraction, range_error_fraction=0.):
        """Call every guarded tick. True while a firing guard (left/right/centre) may rest."""
        if self._epoch != evidence.epoch:  # zones carry their own epoch; restart the rest state
            self._epoch, self._last, self._rest_from, self._odometer, self._spent = evidence.epoch, None, None, 0., False
        samples = evidence.trail.samples
        current = samples[-1] if samples else None
        if current is None or not 0 <= now-current.received_at <= EVIDENCE_TTL_S:
            return False
        if self._last is not None:
            self._odometer += math.hypot(current.x-self._last.x, current.y-self._last.y)
        self._last = current
        ix, iy = current.x+math.cos(current.yaw)*ir_x, current.y+math.sin(current.yaw)*ir_x
        inside = False
        for zone in list(self._zones):
            if zone["anchor"] is None and zone["epoch"] == evidence.epoch:
                zone["anchor"] = evidence._image_pose(zone["stamp_ns"])
            anchor = zone["anchor"]
            if anchor is None:
                if zone["epoch"] != evidence.epoch or now-zone["received_at"] > EVIDENCE_TTL_S:
                    self._zones.remove(zone)
                continue
            c, s = math.cos(anchor.yaw), math.sin(anchor.yaw)
            along, across = c*(ix-anchor.x)+s*(iy-anchor.y), -s*(ix-anchor.x)+c*(iy-anchor.y)
            margin = (zone["uncertainty"]+range_error_fraction*zone["far"]
                      + odom_error_fraction*math.hypot(current.x-anchor.x, current.y-anchor.y))
            if (zone["epoch"] != evidence.epoch or along > min(zone["far"], zone["near"]+max_length)+margin
                    or abs(_angle(current.yaw-anchor.yaw)) > MAX_TURN_RAD or abs(across) > CORRIDOR_HALF_M+margin):
                self._zones.remove(zone)
            elif along >= zone["near"]-margin:
                inside = True
        if guard == "clear":
            self._rest_from, self._spent = None, False
        if guard not in ("left", "right", "centre") or not inside or self._spent:
            return False
        if self._rest_from is None:
            self._rest_from = self._odometer
        if self._odometer-self._rest_from > max_length*(1+2*odom_error_fraction+2*range_error_fraction)+2*MAX_UNCERTAINTY_M:
            self._zones.clear()
            self._rest_from, self._spent = None, True
            return False
        return True
