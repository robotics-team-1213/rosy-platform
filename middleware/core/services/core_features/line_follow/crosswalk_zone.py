"""D-491: crosswalk zones the IR lane guard may rest in, anchored in odom at the image pose.

The camera reports a crosswalk's near and far edge ahead of base_footprint at the image
stamp; by the time the IR row reaches it the camera no longer sees it. Each zone is kept
against the odom pose of its image and checked against the IR row's position along that
pose's heading. A zone exists only for CALIBRATED or GAZEBO ground with a bounded
projection uncertainty, and dies with the D-468 pose trail epoch or once the IR row is past it.
"""
from __future__ import annotations

import math

#: Same admission bounds as D-468 lane evidence (lane_return_evidence.LaneReturnEvidence).
MAX_UNCERTAINTY_M = .015
EVIDENCE_TTL_S = .3
MAX_ZONES = 8


class CrosswalkZones:
    def __init__(self):
        self._zones = []

    def clear(self):
        self._zones.clear()

    def observe(self, evidence, *, epoch, received_at):
        crosswalk = evidence.crosswalk
        if (crosswalk is None or evidence.ground_source not in ("CALIBRATED", "GAZEBO")
                or evidence.uncertainty_m is None or evidence.uncertainty_m > MAX_UNCERTAINTY_M):
            return
        self._zones.append(dict(epoch=epoch, stamp_ns=round(evidence.stamp*1e9), near=crosswalk.near_m,
                                far=crosswalk.far_m, uncertainty=evidence.uncertainty_m,
                                received_at=received_at, anchor=None))
        del self._zones[:-MAX_ZONES]

    def holds(self, evidence, *, now, ir_x, max_length, odom_error_fraction):
        """True while the IR row at ir_x (base_footprint) is inside a zone at the current pose."""
        samples = evidence.trail.samples
        current = samples[-1] if samples else None
        if current is None or not 0 <= now-current.received_at <= EVIDENCE_TTL_S:
            return False
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
            along = math.cos(anchor.yaw)*(ix-anchor.x)+math.sin(anchor.yaw)*(iy-anchor.y)
            margin = zone["uncertainty"]+odom_error_fraction*math.hypot(current.x-anchor.x, current.y-anchor.y)
            far = min(zone["far"], zone["near"]+max_length)
            if along > far+margin:
                self._zones.remove(zone)
            elif along >= zone["near"]-margin:
                inside = True
        return inside
