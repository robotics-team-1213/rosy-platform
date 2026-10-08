"""D-507 items 3-4: the junction instruction's expected window and the approach to the pivot.

Fleet's optional fields give the expected cross line as a travelled distance (2026-10-08 user
decision): expect_in_m is the place's distance along the lane from the robot when the instruction
arrives, less pivot_past_line_m unless the sighting is a fork. A sighting is this instruction's
junction only when the odom path length driven from receipt to the sighting's pose plus
line/keep_debug junction_ahead_m is within expect_tol_m of it, so a curved approach (the 260919
ring) gets a window too; on a straight approach this equals the old straight-ahead point. After
the stop confirm, a turn with pivot_past_line_m drives straight on the entry heading to the
latest sighting's cross-line point plus pivot_past_line_m, through the same tick, gate and
abort rules as the D-495 advance, then stop-confirms and turns. Mixed into JunctionMixin.
pivot_past_line_m is signed (2026-10-08): negative when the measured line is past the place
(the far edge at a roundabout entry or a T). A goal at or behind the robot is no approach: it
turns where it stands, never reverses.
"""
from __future__ import annotations

import math

from core_features.line_follow.crosswalk_zone import CORRIDOR_HALF_M

MAX_EXPECT_IN_M, MAX_EXPECT_TOL_M, MAX_PIVOT_PAST_LINE_M = 2., .30, .30
MAX_AHEAD_M = 2.
#: The window fails closed once odom has fallen this far below its peak since receipt (a reverse,
#: e.g. a D-468 retrace); standing jitter of a few mm stays under it.
WINDOW_RETREAT_M = .01
#: odom sample at the sighting's camera time: nearest trail sample within this.
SIGHTING_POSE_S = .1
ARRIVED_M = .005
STEP_MARGIN_S = 2.  # advance and approach: distance / speed + this
#: D-495 reacquisition after a turn (and the D-507 bend pass): within this travel, heading, time.
REACQUIRE_M = .20
REACQUIRE_HEADING_RAD = math.radians(30.)
STEP_TIME_S = 5.


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
    if pivot is not None and (action == 'stop' or (action != 'straight' and turn_deg is None)
                              or not -MAX_PIVOT_PAST_LINE_M <= pivot <= MAX_PIVOT_PAST_LINE_M):
        raise ValueError('pivot_past_line_m belongs to straight or a turn and must be in [-0.30, 0.30]')


#: ponytail: 260919 transverse tape width; must become a per-site calibration value.
CROSS_LINE_TAPE_M = .025


def band_coords(row, line, yaw):
    """(along, lateral) of the IR row from the line point in the entry frame."""
    dx, dy = row[0]-line[0], row[1]-line[1]
    return dx*math.cos(yaw)+dy*math.sin(yaw), -dx*math.sin(yaw)+dy*math.cos(yaw)


def cross_line_band(row, line, yaw, width, error, half_width):
    """D-507 6 (2026-10-08): is the IR row inside [line - width/2 - error, line + width/2 + error]
    along yaw and within half_width + error across it? row and line are odom (x, y); line is the
    measured tape centre on the robot's track (keeper _across_path, Fleet's map edge)."""
    along, lateral = band_coords(row, line, yaw)
    return abs(along) <= width/2+error and abs(lateral) <= half_width+error


class JunctionApproachMixin:
    _junction_ahead = None  # (junction_ahead_m or None, reason) of the latest sighting
    _junction_anchor = None  # the latest measured sighting, anchored in odom (any age)
    _cross_band = None  # D-507 6: where IR 'centre' is the measured cross line
    _junction_ahead_v_at = None  # last keep_debug frame carrying junction_ahead_v >= 1
    _junction_held = False  # lap SIM A: a bend pass handed its sighting on; seen until odom passes the line

    def _expect_window(self, expect, now):
        """The odom placement of the expected window, None without the fields, False without
        fresh odom to place it. Locked."""
        if expect is None or expect.get('expect_in_m') is None:
            return None
        pose = self._fresh_pose(now)
        if pose is None:
            return False
        odometer = self._return_evidence.trail.odometer
        return dict(key=(self._return_evidence.epoch, pose.frame), odometer=odometer,
                    peak=odometer, retreat=0., seen_to=pose.received_at,
                    expect_in=expect['expect_in_m'], tol=expect['expect_tol_m'])

    def _track_retreat(self, w):
        """Fold trail samples newer than the last fold into the window's largest fall below its
        running peak since receipt. Every armed tick, so no sample leaves the trail unseen. Locked."""
        trail = self._return_evidence.trail
        for p, odo in zip(trail.samples, trail.odometers()):
            if p.received_at > w['seen_to']:
                w['peak'] = max(w['peak'], odo)
                w['retreat'] = max(w['retreat'], w['peak']-odo)
                w['seen_to'] = p.received_at

    def _anchor_sighting(self):
        """On a fresh sighting: anchor it at the odom pose of its camera time. A sighting without
        junction_ahead_m clears the anchor (no measurement); no pose keeps the last one. Locked."""
        ahead, reason = self._junction_ahead or (None, None)
        if ahead is None:
            self._junction_anchor = None
            return
        at, trail = self._junction_seen_at, self._return_evidence.trail
        pose = min(trail.samples, key=lambda p: abs(p.received_at-at), default=None)
        if pose is not None and abs(pose.received_at-at) <= SIGHTING_POSE_S:
            self._junction_anchor = dict(key=(self._return_evidence.epoch, pose.frame), pose=pose,
                                         odometer=trail.odometer_at(pose), ahead=ahead, reason=reason)

    def _line_ahead(self, now, since=-math.inf):
        """The latest sighting, of a run that began at or after `since` (review: not one carried
        over from the bend's own corner), is anchored in this odom frame with a measured line the
        odometer has not passed yet. Locked."""
        a, at, first = self._anchor_now(now), self._junction_seen_at, self._junction_first_seen
        return (a is not None and a['odometer'] is not None and at is not None
                and first is not None and first >= since
                and a['pose'].received_at >= since-SIGHTING_POSE_S
                and self._return_evidence.trail.odometer-a['odometer'] < a['ahead'])

    def _anchor_now(self, now):
        """The anchor if it is in the current odom frame, else None."""
        a, pose = self._junction_anchor, self._fresh_pose(now)
        return a if a is not None and pose is not None and a['key'] == (
            self._return_evidence.epoch, pose.frame) else None

    def _in_window(self, j, now):
        """D-507 3: legacy no-window sightings pass; map-backed ones need a window. Travelled
        distance: odom path length from receipt to the sighting pose + junction_ahead_m against
        expect_in_m - pivot (fail closed: no anchor, another odom run, no path length, or odom
        went back more than WINDOW_RETREAT_M since receipt, which a signed sum would hide)."""
        w, a = j.get('window'), self._anchor_now(now)
        if w is None:
            return j.get('map_id') is None
        self._track_retreat(w)
        if (a is None or a['key'] != w['key'] or a['odometer'] is None
                or w['retreat'] > WINDOW_RETREAT_M):
            return False
        pivot = 0. if a['reason'] == 'junction_fork' else (j.get('pivot') or 0.)
        measured = a['odometer']-w['odometer']+a['ahead']
        return abs(measured-(w['expect_in']-pivot)) <= w['tol']

    def _set_band(self, kind, yaw, now, half_width=None):
        """half_width: a positive pivot_past_line_m (Fleet's lane width / 2), else the D-491
        corridor half-width (a negative pivot is a far-edge offset, not a width)."""
        a = self._anchor_now(now)
        self._cross_band = None if a is None else dict(
            kind=kind, key=a['key'], yaw=a['pose'].yaw if yaw is None else yaw, ahead=a['ahead'],
            start=(a['pose'].x, a['pose'].y), half=half_width if (half_width or 0.) > 0 else CORRIDOR_HALF_M,
            line=_point(a['pose'], a['ahead'], a['pose'].yaw))

    def _centre_on_cross_line(self, now):
        """IR 'centre' is admitted only on the measured cross line: approaching, or a straight
        crossing (outlives its instruction). The band dies on an odom epoch/frame change."""
        b, j, c = self._cross_band, self._junction, self._config
        if b is None or c.ir_row_x_m is None or (b['kind'] == 'approach' and (
                j is None or j['state'] != 'approaching')):
            return False
        pose = self._fresh_pose(now)
        if pose is None or (self._return_evidence.epoch, pose.frame) != b['key']:
            self._cross_band = None if pose is not None else b
            return False
        # The band's own window: from the anchor until the row leaves the far edge. Odom error
        # counts only over that travel, so it cannot grow without bound.
        travel, window = math.dist((pose.x, pose.y), b['start']), b['ahead']+CROSS_LINE_TAPE_M/2
        error = (c.crosswalk_range_error_fraction*b['ahead']
                 + c.crosswalk_odom_error_fraction*min(travel, window))
        row = _point(pose, c.ir_row_x_m, pose.yaw)
        if (band_coords(row, b['line'], b['yaw'])[0] > CROSS_LINE_TAPE_M/2+error
                or travel > window+error):
            self._cross_band = None  # past the line: the band is spent
            return False
        return cross_line_band(row, b['line'], b['yaw'], CROSS_LINE_TAPE_M, error, b['half'])

    def _half_trip_speed(self):
        """D-495 1b: half of min(line_follow.max_linear, manual linear limit), 0 if unknown."""
        ceiling = self._provided('linear_ceiling')
        return (.5*min(self._config.max_linear, float(ceiling))
                if type(ceiling) in (int, float) and math.isfinite(ceiling) else 0.)

    def _start_approach(self, j, now, pose):
        """D-507 4, once per stop: 'map' drives to the pivot, 'stop_point' turns here. Locked;
        returns an abort reason or None. The latest anchored sighting counts at any age."""
        a = self._junction_anchor
        if j.get('pivot') is None or a is None:
            j['pivot_basis'] = 'stop_point'  # no field or no measured line: today's behaviour
            return None
        if a['key'] != j['key']:
            return 'odom'
        yaw = pose.yaw if self._junction_entry is None else self._junction_entry[0]
        goal = _point(a['pose'], a['ahead'], yaw, 0. if a['reason'] == 'junction_fork' else j['pivot'])
        distance = (goal[0]-pose.x)*math.cos(yaw)+(goal[1]-pose.y)*math.sin(yaw)
        j.update(pivot_basis='map', approach_m=max(0., distance))
        if distance <= ARRIVED_M:
            return None
        speed = self._half_trip_speed()
        if speed <= 0:
            return 'linear_limit_zero'
        self._next_phase(j, 'approaching', now, distance/speed+STEP_MARGIN_S)
        j.update(sub='approach', goal=goal, yaw=yaw, speed=speed)
        self._set_band('approach', yaw, now)
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
