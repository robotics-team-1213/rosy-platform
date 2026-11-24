"""Pick between two mirror-twin start poses with the ceiling camera (SLAM fallback, 2026-11-18). Pure: no transport, no clock of its own.

After the fallback switch a robot has no SLAM pose, and a symmetric arena gives loc_assist two equally good candidates about
180 degrees apart that no scan cue (paint, peers, slots, squares) separates. The ceiling camera position can: the twins are at least
SEPARATION_M apart, far more than the camera's display-only calibration error (about 0.33 m). The camera only breaks that tie. It
never overrides a decision the normal arbiter can make, never chooses between candidates that are not twins, and with no fresh
sighting there is no decision (CORE keeps the robot stopped and raises its alert). The caller allows it only while the robot's CORE
reports slam_fallback phase WAITING_LOCALIZATION (never once ACTIVE), and the twins must fit the scan as well as loc_assist's own
verify floor. Every other number is an unmeasured proposal.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional, Sequence

from core_common.protocol.localization import (CandidateReport, Cue, DecisionSource, LocalizationDecision, MapPose)
from fleet.localization.cues import wrap

SEPARATION_M = 1.0          # twins closer than this are the same place, not two hypotheses
OPPOSITE_TOL_RAD = math.radians(25.0)
MIN_FIT = 0.85             # the best twin fits the scan at least this well: loc_assist's own verify floor (min_fit)
TWIN_FIT_GAP = 0.10         # a twin's scan fit is within this of the best one
NEAR_M = 0.60               # the chosen twin must be this close to the camera (camera error is about 0.33 m)
UNIQUE_NEAR_M = 0.35        # unique-candidate overhead corroboration cap
FAR_MARGIN_M = 0.40         # the other twin must be at least this much farther
HOLD_S = 2.0
TTL_S = 5.0


def twins(report: CandidateReport) -> Optional[tuple]:
    """The two candidates if they are mirror twins fitting at or above MIN_FIT; else None."""
    ranked = sorted(report.candidates, key=lambda c: -c.scan_fit)
    if len(ranked) != 2:
        return None
    a, b = ranked[0], ranked[1]
    opposite = abs(abs(wrap(a.yaw - b.yaw)) - math.pi) <= OPPOSITE_TOL_RAD
    if (not (math.isfinite(a.scan_fit) and math.isfinite(b.scan_fit))
            or a.scan_fit < MIN_FIT or b.scan_fit < MIN_FIT
            or math.dist((a.x, a.y), (b.x, b.y)) < SEPARATION_M or not opposite
            or a.scan_fit - b.scan_fit > TWIN_FIT_GAP):
        return None
    return a, b


def choose(report: CandidateReport, camera_xy: Optional[Sequence[float]]) -> Optional[tuple]:
    """(candidate, evidence) the camera picks from mirror twins, or None."""
    pair = twins(report)
    if pair is None or camera_xy is None:
        return None
    near, far = sorted(pair, key=lambda c: math.dist((c.x, c.y), camera_xy))
    d_near, d_far = math.dist((near.x, near.y), camera_xy), math.dist((far.x, far.y), camera_xy)
    if d_near > NEAR_M or d_far - d_near < FAR_MARGIN_M:
        return None
    return near, {"camera_to_chosen_m": round(d_near, 3), "camera_to_other_m": round(d_far, 3)}


def choose_unique(report: CandidateReport, camera_xy: Optional[Sequence[float]]) -> Optional[tuple]:
    """(candidate, evidence) when one strong laser candidate is corroborated by the camera."""
    if len(report.candidates) != 1 or camera_xy is None:
        return None
    c = report.candidates[0]
    if not math.isfinite(c.scan_fit) or c.scan_fit < MIN_FIT:
        return None
    d_near = math.dist((c.x, c.y), camera_xy)
    if d_near > UNIQUE_NEAR_M:
        return None
    return c, {"camera_to_chosen_m": round(d_near, 3)}


@dataclass
class Tiebreak:
    hold_s: float = HOLD_S
    _lead: dict = field(default_factory=dict)      # robot -> (mode, request_id, x, y, since)
    _decided: dict = field(default_factory=dict)   # robot -> (request_id, stamp)

    def observe(self, report: CandidateReport, camera_xy: Optional[Sequence[float]], now: float) -> Optional[LocalizationDecision]:
        robot = report.robot_id
        if self._decided.get(robot) == (report.request_id, report.stamp):
            return None
        picked = choose(report, camera_xy)
        mode = "twin"
        if picked is None:
            picked = choose_unique(report, camera_xy)
            mode = "unique"
        if picked is None:
            self._lead.pop(robot, None)
            return None
        candidate, evidence = picked
        lead = self._lead.get(robot)
        if lead is None or lead[0] != mode or lead[1] != report.request_id or (lead[2], lead[3]) != (candidate.x, candidate.y):
            self._lead[robot] = (mode, report.request_id, candidate.x, candidate.y, now)
            return None
        if now - lead[4] < self.hold_s:
            return None
        self._decided[robot] = (report.request_id, report.stamp)
        self._lead.pop(robot, None)
        return LocalizationDecision(
            request_id=report.request_id, pose=MapPose(x=candidate.x, y=candidate.y, yaw=candidate.yaw),
            source=DecisionSource.OVERHEAD, cues=[Cue.OVERHEAD], evidence={"tiebreak": mode, **evidence}, ttl_s=TTL_S)
