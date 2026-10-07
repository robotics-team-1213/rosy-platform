"""D-507 items 3-4: the junction instruction's expected window and the approach to the pivot.

Fleet's optional fields place one expected cross-line point in odom when the instruction
arrives (expect_in_m along the receive heading, less pivot_past_line_m unless the sighting is a
fork). A sighting is this instruction's junction only when its measured cross-line point (odom
pose at the sighting + line/keep_debug junction_ahead_m) lies within expect_tol_m of it. After
the stop confirm, a turn with pivot_past_line_m drives straight on the entry heading to the
latest sighting's cross-line point plus pivot_past_line_m, through the same tick, gate and
abort rules as the D-495 advance, then stop-confirms and turns. Mixed into JunctionMixin.
"""
from __future__ import annotations

import math

MAX_EXPECT_IN_M, MAX_EXPECT_TOL_M, MAX_PIVOT_PAST_LINE_M = 2., .30, .30
MAX_AHEAD_M = 2.
#: odom sample at the sighting's camera time: nearest trail sample within this.
SIGHTING_POSE_S = .1
ARRIVED_M = .005
STEP_MARGIN_S = 2.  # advance and approach: distance / speed + this


def _point(pose, ahead, yaw, extra=0.):
    return (pose.x+ahead*math.cos(pose.yaw)+extra*math.cos(yaw),
            pose.y+ahead*math.sin(pose.yaw)+extra*math.sin(yaw))


def check_expect(expect, action, turn_deg):
    """Range and pairing of the D-507 2 fields (the API answers 400 before this)."""
    if expect is None:
        return
    e_in, tol, pivot = (expect.get(k) for k in ('expect_in_m', 'expect_tol_m', 'pivot_past_line_m'))
    if (e_in is None) != (tol is None) or (e_in is not None and not (
            0 < e_in <= MAX_EXPECT_IN_M and 0 < tol <= MAX_EXPECT_TOL_M)):
        raise ValueError('expect_in_m (0, 2] and expect_tol_m (0, 0.30] come together')
    if pivot is not None and (turn_deg is None or action not in ('left', 'right')
                              or not 0 <= pivot <= MAX_PIVOT_PAST_LINE_M):
        raise ValueError('pivot_past_line_m belongs to a left/right turn and must be in [0, 0.30]')


class JunctionApproachMixin:
    _junction_ahead = None  # (junction_ahead_m or None, reason) of the latest sighting

    def _expect_window(self, expect, now):
        """The odom placement of the expected window, None without the fields, False without
        fresh odom to place it. Locked."""
        if expect is None or expect.get('expect_in_m') is None:
            return None
        pose = self._fresh_pose(now)
        if pose is None:
            return False
        return dict(key=(self._return_evidence.epoch, pose.frame), pose=pose,
                    expect_in=expect['expect_in_m'], tol=expect['expect_tol_m'])

    def _sighting(self):
        """(odom pose at the latest sighting, junction_ahead_m, reason) or None."""
        ahead, reason = self._junction_ahead or (None, None)
        at = self._junction_seen_at
        if ahead is None or at is None:
            return None
        samples = self._return_evidence.trail.samples
        pose = min(samples, key=lambda p: abs(p.received_at-at), default=None)
        if pose is None or abs(pose.received_at-at) > SIGHTING_POSE_S:
            return None
        return pose, ahead, reason

    def _in_window(self, j):
        """D-507 3: no window means today's behaviour; an unmeasurable sighting is outside."""
        w = j.get('window')
        if w is None:
            return True
        sighting = self._sighting()
        if sighting is None or (self._return_evidence.epoch, sighting[0].frame) != w['key']:
            return False
        pose, ahead, reason = sighting
        pivot = 0. if reason == 'junction_fork' else (j.get('pivot') or 0.)
        expected = _point(w['pose'], w['expect_in']-pivot, w['pose'].yaw)
        return math.dist(_point(pose, ahead, pose.yaw), expected) <= w['tol']

    def _half_trip_speed(self):
        """D-495 1b: half of min(line_follow.max_linear, manual linear limit), 0 if unknown."""
        ceiling = self._provided('linear_ceiling')
        return (.5*min(self._config.max_linear, float(ceiling))
                if type(ceiling) in (int, float) and math.isfinite(ceiling) else 0.)

    def _start_approach(self, j, now, pose):
        """D-507 4, once per stop: 'map' drives to the pivot, 'stop_point' turns here. Locked;
        returns an abort reason or None."""
        sighting = self._sighting()
        fresh = (self._junction_seen_at is not None
                 and 0 <= now-self._junction_seen_at <= self._config.stale_after_s)
        if j.get('pivot') is None or not fresh or (self._junction_ahead or (None,))[0] is None:
            j['pivot_basis'] = 'stop_point'  # no field or no measured line: today's behaviour
            return None
        if sighting is None or (self._return_evidence.epoch, sighting[0].frame) != j['key']:
            return 'odom'
        yaw = pose.yaw if self._junction_entry is None else self._junction_entry[0]
        at, ahead, reason = sighting
        goal = _point(at, ahead, yaw, 0. if reason == 'junction_fork' else j['pivot'])
        distance = (goal[0]-pose.x)*math.cos(yaw)+(goal[1]-pose.y)*math.sin(yaw)
        j.update(pivot_basis='map', approach_m=max(0., distance))
        if distance <= ARRIVED_M:
            return None
        speed = self._half_trip_speed()
        if speed <= 0:
            return 'linear_limit_zero'
        self._next_phase(j, 'approaching', now, distance/speed+STEP_MARGIN_S)
        j.update(sub='approach', goal=goal, yaw=yaw, speed=speed)
        self._odom_travel(j, now)
        return None

    def _approach_twist(self, j, pose):
        """(linear, angular) toward the pivot holding the entry heading, or None on arrival."""
        yaw = j['yaw']
        remaining = (j['goal'][0]-pose.x)*math.cos(yaw)+(j['goal'][1]-pose.y)*math.sin(yaw)
        if remaining <= ARRIVED_M:
            return None
        cap = self._angular_cap()
        error = math.atan2(math.sin(yaw-pose.yaw), math.cos(yaw-pose.yaw))
        return j['speed'], max(-cap, min(cap, 2.*error))
