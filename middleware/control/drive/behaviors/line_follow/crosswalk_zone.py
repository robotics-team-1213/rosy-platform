"""D-491: crosswalk zones the IR lane guard may rest in, anchored in odom at the image pose.

The camera saw the crosswalk ahead; the IR row reaches it after the camera lost it. A zone
needs the frame's along-track crosswalk bound (D-573 6, <= crosswalk_max_uncertainty_m) and a lane
lateral bound within MAX_LATERAL_M (any ground, as D-468); the along bound is its along-track
margin, the lateral bound widens its corridor. It is kept at its image's odom pose,
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
#: The IR row centre still reads crosswalk stripes up to 0.0725 + 0.020 = 0.0925 m from the lane centre
#: (D-491 Context; same as the D-364 keep half-width), rounded up. The lane itself is 0.079 m half-width
#: between inner edges (D-573 6 개정 2): the corridor reaches over the paint, bounded by IR_CATCH_HALF_M.
CORRIDOR_HALF_M = .10
#: D-491 개정 2026-10-10: the farthest IR row centre from the lane centre at which an IR sensor still
#: reads the boundary paint: inner-edge half-width 0.079 (lane 0.158 m between inner edges, D-573 6
#: 개정 2) + paint 0.025 (perception LANE_LINE_WIDTH_M) + IR half span 0.020 (URDF ir_left/right).
#: A rest ends when the IR row leaves the corridor, so the corridor must end before this reach or a
#: departure over the paint would pass unseen. RobotBody does not enter: the body sweep (D-422) is
#: independent of the IR rest.
IR_CATCH_HALF_M = .079+.025+.020
#: Largest lane lateral bound a zone admits: its corridor CORRIDOR_HALF_M + lateral stays in the reach.
MAX_LATERAL_M = round(IR_CATCH_HALF_M-CORRIDOR_HALF_M, 6)  # 0.024


class CrosswalkZones:
    def __init__(self):
        self.clear()

    def clear(self):
        self._zones, self._epoch, self._last, self._rest_from, self._odometer, self._spent = [], None, None, None, 0., False
        self.fresh = []  # D-573 6: every new zone, for the report's own list (crosswalk_report.py)

    def observe(self, evidence, *, epoch, received_at, max_along):
        crosswalk, lateral, along = evidence.crosswalk, evidence.uncertainty_m, evidence.crosswalk_uncertainty_m
        # D-573 6: the along-track bound places the zone; the lateral one only widens its corridor.
        if crosswalk is None or along is None or along > max_along or lateral is None or lateral > MAX_LATERAL_M:
            return
        # D-573: the lane corridor across the zone (inner paint edges at its near/far ends, body
        # frame at the image), None when a side was not seen. Only the crosswalk gate reads it.
        edges = {b.side: [b.slope*x+b.intercept_m for x in (crosswalk.near_m, crosswalk.far_m)]
                 for b in evidence.boundaries}
        self._zones.append(dict(epoch=epoch, stamp_ns=round(evidence.stamp*1e9), near=crosswalk.near_m,
                                far=crosswalk.far_m, uncertainty=lateral, along=along,
                                received_at=received_at, anchor=None,
                                left=max(edges["left"]) if "left" in edges else None,
                                right=min(edges["right"]) if "right" in edges else None))
        self.fresh.append(self._zones[-1])
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
            drift = odom_error_fraction*math.hypot(current.x-anchor.x, current.y-anchor.y)
            margin = zone["along"]+range_error_fraction*zone["far"]+drift
            if (zone["epoch"] != evidence.epoch or along > min(zone["far"], zone["near"]+max_length)+margin
                    or abs(_angle(current.yaw-anchor.yaw)) > MAX_TURN_RAD
                    # drift is position doubt: it narrows the corridor, never past the IR catch reach
                    or abs(across)+drift > min(CORRIDOR_HALF_M+zone["uncertainty"], IR_CATCH_HALF_M)):
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
