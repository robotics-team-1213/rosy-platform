"""D-517 4 (M2): Fleet movement authority, enforced with config ``authority_required`` or, for the rest
of a line-follow session, once Fleet sent one. ``until_m`` counts from the odom sample at ``pose_stamp``
(CORE wall clock, as snapshot ``odom_pose.stamp``); travel since is the odom path length (unsigned:
reversing never adds room). The gate only zeroes a tick's decision, so the body stop (D-422), IR guard
(D-491) and E-stop, which zero it first, always win. Manager lock throughout; a mode change resets it."""
import logging
import math
import time
from collections import deque
from dataclasses import replace

from core_common.protocol.line_authority import SHRINK_TOL_M, STAMP_TOL_S, AuthorityRefused, LineAuthorityStatus

#: D-744 5: a map anchor's odom stamp may be this old at receipt. The pose trail keeps 2 s at 50 Hz
#: (100 samples); Fleet's pose is one trip period (0.5 s) and the request old.
ARC_ANCHOR_MAX_AGE_S = 2.
#: D-744 5: odom path length (unsigned) from receipt to the arc opening over which the placed circle
#: is kept (the bridge Fleet itself trusts between sightings, fleet.map_pose.max_dead_reckon_m; the
#: instruction comes within arm_distance_m 0.6 m, or one lane <= 1 m, of the place).
ARC_ANCHOR_MAX_CARRY_M = 1.5
#: D-744 5: the body may be this far from the placed circle at the opening. Below ARC_MAX_RADIAL_M
#: (0.075 m, where the arc stops lane_arc_edge) by the transient of the pull-in (host rig: +0.009 m
#: from 0.02 m / 10 deg), so an accepted anchor does not open an arc that stops at once.
ARC_ANCHOR_MAX_RADIAL_M = .045
#: D-744 5: the heading may be this far off the placed circle's tangent at the opening: above the
#: 10 deg pivot error measured in Gazebo (2026-10-13); more is a wrong map yaw, not a pivot error.
ARC_ANCHOR_MAX_HEADING_RAD = math.radians(25.)
ARC_ANCHOR_FIELDS = ('centre_x_m', 'centre_y_m', 'pose_x_m', 'pose_y_m', 'pose_yaw_rad', 'odom_stamp_s')


class AuthorityMixin:
    _wall = staticmethod(time.time)  # CORE wall clock, the one odom_pose.stamp is on

    def _init_authority(self):  # odom log: (wall, (epoch, frame), stamp_ns, path_m, x, y), >= 4 s at 50 Hz
        self._odom_log, self._authority, self._authority_seen, self._authority_held = deque(maxlen=200), None, False, False

    def observe_return_pose(self, **sample):
        accepted = super().observe_return_pose(**sample)
        with self._lock:
            ev, log = self._return_evidence, self._odom_log
            p = ev.trail.samples[-1] if ev.trail.samples else None
            key = None if p is None else (ev.epoch, p.frame)
            if p is None or (log and log[-1][1:3] == (key, p.stamp_ns)):
                return accepted  # refused or already logged
            if not (log and log[-1][1] == key):
                log.clear()  # a new odom run: travel across the gap is unknown
            path = log[-1][3]+math.hypot(p.x-log[-1][4], p.y-log[-1][5]) if log else 0.
            log.append((self._wall(), key, p.stamp_ns, path, p.x, p.y))
        return accepted

    def set_authority(self, authority_id, leg_id, pose_stamp, until_m, ttl_s, now=None):
        """Store Fleet's authority. ``AuthorityRefused`` drops the held one too (the robot stands)."""
        with self._lock:
            if self._mode.value == 'OFF':
                raise AuthorityRefused('LINE_FOLLOW_NOT_ACTIVE', 'line-follow is OFF')
            now, log, ev = self._clock() if now is None else now, self._odom_log, self._return_evidence
            self._authority_seen, pose = True, self._fresh_pose(now)
            fresh = pose is not None and bool(log) and log[-1][1] == (ev.epoch, pose.frame)
            # The sample at or before pose_stamp: never less travel than since the pose.
            base = next((e for e in reversed(log) if e[0] <= pose_stamp), None) if fresh else None
            refusal = (('AUTHORITY_ODOM_STALE', 'no fresh odom to measure travel') if not fresh else
                       ('AUTHORITY_POSE_FUTURE', 'pose_stamp is newer than CORE odom')
                       if pose_stamp > log[-1][0]+STAMP_TOL_S else
                       ('AUTHORITY_POSE_STALE', 'pose_stamp is older than CORE odom history') if base is None else None)
            if refusal is not None:
                self._authority = None
                raise AuthorityRefused(*refusal)
            end, a = base[3]+until_m, self._authority
            if a is not None and (a['leg_id'], a['key']) == (leg_id, base[1]) and now <= a['expires_at']:
                if end < a['end']-SHRINK_TOL_M:  # never shrinks: ignored, so it expires unless extended
                    logging.getLogger(__name__).info('authority %s on leg %s ignored: %.3f m short', authority_id, leg_id, a['end']-end)
                    return dict(accepted=False, reason='shrink', authority=self.authority_status(now))
                end = max(end, a['end'])
            self._authority = dict(authority_id=authority_id, leg_id=leg_id, end=end, key=base[1], expires_at=now+ttl_s)
            return dict(accepted=True, reason=None, authority=self.authority_status(now))

    def _authority_state(self, now):
        """(state, remaining_m, reason); HOLDING latches with the D-422 stop gap + hysteresis. Locked."""
        a, log, c = self._authority, self._odom_log, self._config
        if a is None or now > a['expires_at']:
            return ('NONE', None, 'authority_none') if a is None else ('EXPIRED', None, 'authority_expired')
        if self._fresh_pose(now) is None or not log or log[-1][1] != a['key']:
            return 'HOLDING', None, 'authority_odom_stale'
        remaining, stop = a['end']-log[-1][3], c.derived_stop_gap_m(c.max_linear)  # fastest line follow commands
        self._authority_held = remaining <= stop+(c.obstacle_resume_hysteresis_m if self._authority_held else 0.)
        return ('HOLDING', remaining, 'authority_end') if self._authority_held else ('FREE', remaining, None)

    def authority_status(self, now=None):
        """GET /line-follow ``authority`` while enforced, else None (the response stays as before)."""
        with self._lock:
            if not (self._config.authority_required or self._authority_seen):
                return None
            now = self._clock() if now is None else now
            (state, remaining, reason), a = self._authority_state(now), self._authority or {}
            return LineAuthorityStatus(state=state, authority_id=a.get('authority_id'), leg_id=a.get('leg_id'),
                reason=reason, remaining_m=None if remaining is None else round(remaining, 3),
                expires_in_s=None if not a else round(max(0., a['expires_at']-now), 3)).model_dump()

    def _authority_gate(self, now, decision):
        state = (self._config.authority_required or self._authority_seen) and self._authority_state(now)
        if not state or state[0] == 'FREE' or not (decision.linear or decision.angular):
            return decision
        if self._status.state not in ('LOST', 'OFF'):
            self._status = self._status.model_copy(update={'state': 'HOLD', 'reason': state[2], 'linear': 0., 'angular': 0.})
        return replace(decision, linear=0., angular=0.)

    # --- D-744: the lane arc's map anchor (here for the odom log and the wall clock it is matched on) ---

    @property
    def supports_lane_arc_map_anchor(self):
        """D-744 2 capability: CORE takes `exit_segment.map_anchor` wherever it runs the arc."""
        return self.supports_lane_arc

    def _place_map_anchor(self, segment, now):
        """D-744 3: at receipt, Fleet's map circle centre placed in odom through its pose pair (the
        map pose and CORE's odom pose at `odom_stamp_s`, CORE wall clock as snapshot
        odom_pose.stamp): {centre, key, path}, or {reason} for today's pose-derived circle."""
        anchor = (segment or {}).get('map_anchor')
        if anchor is None:
            return dict(reason='none_sent')
        try:
            cx, cy, mx, my, myaw, stamp = values = [anchor[n] for n in ARC_ANCHOR_FIELDS]
        except (KeyError, TypeError, ValueError):
            return dict(reason='malformed')
        if not all(type(v) in (int, float) and math.isfinite(v) for v in values):
            return dict(reason='malformed')
        found = self._odom_at_stamp(stamp, now)
        if isinstance(found, str):
            return dict(reason=found)
        at, key, path = found
        c, n = math.cos(at.yaw-myaw), math.sin(at.yaw-myaw)  # map -> odom
        return dict(centre=(at.x+c*(cx-mx)-n*(cy-my), at.y+n*(cx-mx)+c*(cy-my)), key=key, path=path)

    def _odom_at_stamp(self, stamp, now):
        """D-744 3 (D-759 3 too): (CORE's odom pose logged at `stamp`, the odom key, the path length
        now), or why a map pose computed for that stamp cannot be paired with CORE's odom."""
        age = self._wall()-stamp
        if not -STAMP_TOL_S <= age <= ARC_ANCHOR_MAX_AGE_S:
            return 'stale' if age > 0 else 'future'
        pose, ev, log = self._fresh_pose(now), self._return_evidence, self._odom_log
        # the odom sample the map pose was computed for: the one logged at or just before the stamp
        base = next((e for e in reversed(log) if e[0] <= stamp), None)
        if pose is None or base is None or stamp-base[0] > STAMP_TOL_S:
            return 'no_sample'
        key = (ev.epoch, pose.frame)
        if base[1] != key:
            return 'epoch'
        at = ev._image_pose(base[2])
        return 'no_sample' if at is None else (at, key, log[-1][3])

    def _map_anchor_circle(self, anchor, pose, key, k, centre, yaw0, ir_chain):
        """D-744 4-5: (centre, yaw0, reason) at the arc opening: the placed map circle and its
        tangent at the pose with reason None, else the given (today's) circle and why. ir_chain: a
        chained straight whose previous arc used its IR correction keeps that paint-anchored circle."""
        if anchor is None or 'reason' in anchor:
            return centre, yaw0, (anchor or {}).get('reason', 'none_sent')
        (cx, cy), log = anchor['centre'], self._odom_log
        tangent = math.atan2(pose.y-cy, pose.x-cx) + math.copysign(math.pi/2, k)
        off = math.atan2(math.sin(pose.yaw-tangent), math.cos(pose.yaw-tangent))
        why = ('ir_chain' if ir_chain else
               'epoch' if anchor['key'] != key or not log or log[-1][1] != key else
               'carry' if log[-1][3]-anchor['path'] > ARC_ANCHOR_MAX_CARRY_M else
               'radial' if abs(math.hypot(pose.x-cx, pose.y-cy)-1/abs(k)) > ARC_ANCHOR_MAX_RADIAL_M else
               'heading' if abs(off) > ARC_ANCHOR_MAX_HEADING_RAD else None)
        return (centre, yaw0, why) if why else ((cx, cy), tangent, None)
