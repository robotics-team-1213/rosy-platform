"""D-517 4 (M2): Fleet movement authority, enforced with config ``authority_required``, while CORE's trip lease
is open (D-760 2) or, for the rest of a session, once Fleet sent one. ``until_m`` counts from the odom sample at ``pose_stamp``
(CORE wall clock, as snapshot ``odom_pose.stamp``; D-758 0: the sample published with that stamp, else the
one logged at or before it); travel since is the odom path length (unsigned:
reversing never adds room). The gate only zeroes a tick's decision, so the body stop (D-422), IR guard
(D-491) and E-stop, which zero it first, always win. Manager lock throughout; a mode change resets it."""
import logging
import math
import time
from collections import deque
from dataclasses import replace

from core_common.protocol.line_authority import SHRINK_TOL_M, STAMP_TOL_S, AuthorityRefused, LineAuthorityStatus
from .route_guide import bind_guide

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
#: D-760 3: legs whose newest ``seq`` is remembered at once. A leg is forgotten only when it was last seen
#: before the oldest sample of the odom log: a late request for it carries an older pose_stamp and is refused
#: (AUTHORITY_POSE_STALE, the robot stands). A new leg beyond this many live ones is refused (seq_legs_full).
SEQ_LEGS = 8
ARC_ANCHOR_FIELDS = ('centre_x_m', 'centre_y_m', 'pose_x_m', 'pose_y_m', 'pose_yaw_rad', 'odom_stamp_s')
#: D-758 0: an echoed stamp this close to a logged one is that sample (Fleet returns the snapshot's float
#: through JSON unchanged; a wall stamp near 1.8e9 s resolves to 2.4e-7 s).
STAMP_MATCH_S = 1e-6


class AuthorityMixin:
    _wall = staticmethod(time.time)  # CORE wall clock, the one odom_pose.stamp is on
    authority_leased = staticmethod(lambda: False)  # D-760 2: CORE binds "a trip lease is open" (core/trip_lease.py)
    _authority_seq = {}  # D-760 3: leg_id -> (newest seq seen, line clock); replaced, never mutated; outlives modes

    # odom log: (published wall stamp, (epoch, frame), stamp_ns, path_m, x, y, line clock), >= 4 s at 50 Hz
    def _init_authority(self):
        self._odom_log, self._authority, self._authority_held = deque(maxlen=200), None, False
        self._authority_seen = bool(self.authority_leased())  # D-760 2: a lease open at the mode change latches too

    def observe_return_pose(self, wall=None, **sample):
        """``wall``: the stamp the state snapshot published for this sample (D-758 0); None: CORE's wall now."""
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
            log.append((self._wall() if wall is None else wall, key, p.stamp_ns, path, p.x, p.y, p.received_at))
        return accepted

    def _odom_entry(self, stamp):
        """D-758 0: (entry, exact). The one entry published at ``stamp`` (a wall step cannot move it), else
        (an older Fleet's or a computed stamp) the one logged at or before it on the wall clock, as before.
        (None, True) refuses: two entries share the stamp (review 1: the newer counts less travel, more room),
        or no entry does while the log's wall stamps step back (review 3: "at or before" lands after the step)."""
        log = self._odom_log
        hits = [e for e in log if abs(e[0]-stamp) <= STAMP_MATCH_S]
        if hits:
            return (hits[0] if len(hits) == 1 else None), True
        if any(a[0] > b[0] for a, b in zip(log, list(log)[1:])):
            return None, True
        return next((e for e in reversed(log) if e[0] <= stamp), None), False

    def set_authority(self, authority_id, leg_id, pose_stamp, until_m, ttl_s, now=None, shrink=False, seq=None, route_guide=None):
        """Store Fleet's authority. ``AuthorityRefused`` drops the held one too (the robot stands). D-760 3:
        ``seq`` at or below the newest seen on the leg is ignored, as is a request without ``seq`` on a leg that
        has one; ``shrink`` takes min(held end, this end) and never grants: with nothing live to shrink, none is held."""
        with self._lock:
            if self._mode.value == 'OFF':
                raise AuthorityRefused('LINE_FOLLOW_NOT_ACTIVE', 'line-follow is OFF')
            now, log, ev = self._clock() if now is None else now, self._odom_log, self._return_evidence
            self._authority_seen, pose = True, self._fresh_pose(now)
            seqs = {k: v for k, v in self._authority_seq.items() if k == leg_id or not log or v[1] >= log[0][6]}
            ignored = ((None if leg_id not in seqs else 'seq_required') if seq is None else
                       'stale_seq' if seq <= seqs.get(leg_id, (-1,))[0] else
                       'seq_legs_full' if leg_id not in seqs and len(seqs) >= SEQ_LEGS else None)
            if ignored:  # the held end and its ttl stay as they are
                return dict(accepted=False, reason=ignored, authority=self.authority_status(now))
            if seq is not None:  # seen before any refusal: a refused shrink still outranks an older extend
                self._authority_seq = {**seqs, leg_id: (seq, now)}
            fresh = pose is not None and bool(log) and log[-1][1] == (ev.epoch, pose.frame)
            # The sample at or before pose_stamp: never less travel than since the pose.
            base, exact = self._odom_entry(pose_stamp) if fresh else (None, False)
            refusal = (('AUTHORITY_ODOM_STALE', 'no fresh odom to measure travel') if not fresh else
                       ('AUTHORITY_POSE_FUTURE', 'pose_stamp is newer than CORE odom')
                       if not exact and pose_stamp > log[-1][0]+STAMP_TOL_S else
                       ('AUTHORITY_POSE_STALE', 'pose_stamp is older than CORE odom history') if base is None else None)
            if refusal is not None:
                self._authority = None
                raise AuthorityRefused(*refusal)
            end, a = base[3]+until_m, self._authority
            live = a is not None and (a['leg_id'], a['key']) == (leg_id, base[1]) and now <= a['expires_at']
            if shrink and not live:  # a shrink never grants: Fleet wants less, so whatever is held goes too
                self._authority = None
                return dict(accepted=False, reason='shrink_none_held', authority=self.authority_status(now))
            binding, self._route_source_budget = bind_guide(route_guide, base=base, exact=exact,
                leg_id=leg_id, seq=seq, now=now, ttl_s=ttl_s, shrink=shrink,
                budget=getattr(self, '_route_source_budget', None))
            if live:
                if end < a['end']-SHRINK_TOL_M and not shrink:  # never shrinks unasked: ignored, so it expires
                    logging.getLogger(__name__).info('authority %s on leg %s ignored: %.3f m short', authority_id, leg_id, a['end']-end)
                    # ... but its route prior is fresh evidence, never a grant: kept (v2 lap r48b/r49a: Fleet's map
                    # metres ran behind CORE's odom path, every such extend dropped the prior for 3 sim-seconds)
                    if binding is not None:
                        a['route_guide'] = binding
                    return dict(accepted=False, reason='shrink', authority=self.authority_status(now))
                end = min(end, a['end']) if shrink else max(end, a['end'])
            self._authority = dict(authority_id=authority_id, leg_id=leg_id, end=end, key=base[1],
                                   expires_at=now+ttl_s, route_guide=binding)
            return dict(accepted=True, reason=None, authority=self.authority_status(now))

    def route_guide(self, now=None):
        """The active authority's source-expiring prior, never a movement grant."""
        binding = self.route_guide_binding(now)
        return None if binding is None else binding['prior']

    def route_guide_binding(self, now=None):
        """route_guide's binding: ``prior``, ``expires_at`` and its odom sample ``stamp_ns`` (D-573 rev 8)."""
        with self._lock:
            now = self._clock() if now is None else now
            binding = (self._authority or {}).get('route_guide')
            if (binding is None or self._mode.value == 'OFF' or now >= binding['expires_at']
                    or self._authority_state(now)[0] != 'FREE'):
                return None
            return binding

    def _authority_on(self):
        """Enforced: by config, by a request this session, or once a trip lease was seen open (D-760 2: latched
        until the mode changes, so a lease that ends before the first authority frees nothing). Locked."""
        self._authority_seen = self._authority_seen or bool(self.authority_leased())
        return self._config.authority_required or self._authority_seen

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
            if not self._authority_on():
                return None
            now = self._clock() if now is None else now
            (state, remaining, reason), a = self._authority_state(now), self._authority or {}
            return LineAuthorityStatus(state=state, authority_id=a.get('authority_id'), leg_id=a.get('leg_id'),
                reason=reason, remaining_m=None if remaining is None else round(remaining, 3),
                expires_in_s=None if not a else round(max(0., a['expires_at']-now), 3)).model_dump()

    def _authority_gate(self, now, decision):
        state = self._authority_on() and self._authority_state(now)
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
        now), or why a map pose computed for that stamp cannot be paired with CORE's odom. D-758 0: a
        published stamp is aged on the line clock; any other on the wall clock, as before."""
        base, exact = self._odom_entry(stamp)  # the sample the map pose was computed for
        if exact and base is None:
            return 'no_sample'
        age = now-base[6] if exact else self._wall()-stamp
        if not -STAMP_TOL_S <= age <= ARC_ANCHOR_MAX_AGE_S:
            return 'stale' if age > 0 else 'future'
        pose, ev, log = self._fresh_pose(now), self._return_evidence, self._odom_log
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
