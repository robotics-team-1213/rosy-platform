"""D-495 bounded turn state on the existing LineFollowManager lock and generation."""
from __future__ import annotations

import math

#: Same freshness bound as the D-476 bridge, including the wait before a turn starts.
POSE_MAX_AGE_S = .3
TURN_TOLERANCE_RAD = math.radians(5.)
TURN_GAIN = 2.            # rad/s per rad of yaw error, clipped to [TURN_MIN_W, angular cap]
TURN_MIN_W = .3           # rad/s floor (or the cap, if lower); sets the turn time limit
TURN_TIME_MARGIN_S = 2.
SETTLE_S = .3             # inside the tolerance this long before the turn counts as done
#: Review L1: the turn starts only after odom shows the robot standing still this long.
#: Speeds are config (junction_still_linear / junction_still_angular, review L3).
STILL_S, STILL_LIMIT_S = .2, 2.


def _wrap(angle):
    return math.atan2(math.sin(angle), math.cos(angle))



class JunctionTurnMixin:
    def _standing_still(self, now):
        """Odom over its last STILL_S shows |v| < junction_still_linear, |w| < junction_still_angular."""
        trail = self._return_evidence.trail.samples
        if not trail:
            return False
        latest = trail[-1].received_at  # a lagging odom is judged over its own last STILL_S
        samples = [p for p in trail if latest-p.received_at <= STILL_S+.06]
        if len(samples) < 2 or samples[-1].received_at-samples[0].received_at < STILL_S-1e-6:
            return False
        for a, b in zip(samples, samples[1:]):
            dt = b.received_at-a.received_at
            if (dt <= 0 or math.hypot(b.x-a.x, b.y-a.y)/dt >= self._config.junction_still_linear
                    or abs(_wrap(b.yaw-a.yaw))/dt >= self._config.junction_still_angular):
                return False
        return True

    def _start_turn(self, j, now, decision):
        """D-495 (a): the junction is seen; stand still, then turn from the measured yaw."""
        pose = self._fresh_pose(now)
        if pose is None:
            # D-495 SIM finding 3: a mode select empties the trail; stay armed and stopped
            # until the first odom sample, at most POSE_MAX_AGE_S, then abort as before.
            waited_from = j.setdefault('odom_wait_at', now)
            if now-waited_from <= POSE_MAX_AGE_S:
                return self._junction_hold('junction_stopping', decision)
            return self._abort(j, 'odom', decision)
        j.pop('odom_wait_at', None)
        # Review M8: the instruction may clear LOST only if the junction sighting (the keeper's
        # junction HOLD) started the loss clock; a lane lost before the junction stays LOST.
        first = self._junction_first_seen
        if (self._loss_started_at is not None and first is not None
                and self._loss_started_at < first-self._config.stale_after_s):
            return self._abort(j, 'lane_lost_before_junction', decision)
        refusal = self._maneuver_refusal(now)
        if refusal is not None:
            return self._abort(j, refusal, decision)
        key, j['basis'] = (self._return_evidence.epoch, pose.frame), self._turn_basis_now
        if self._junction_entry is not None and self._junction_entry[1] != key:
            return self._abort(j, 'odom', decision)  # entry yaw no longer comparable
        self._loss_started_at, self._lost_latched = None, False
        j.update(state='turning', sub='stopping', key=key,
                 phase_at=now, limit=STILL_LIMIT_S, w=0., settled_at=None)
        return self._maneuver(j, now, decision)

    def _turn_step(self, j, now, pose):
        """This tick's angular speed, or None once the turn has settled. Locked."""
        tolerance = TURN_TOLERANCE_RAD
        cap = self._angular_cap()
        floor = min(cap, TURN_MIN_W)
        if j['sub'] == 'stopping':
            if not self._standing_still(now):
                return 0.
            # Review N1: aim from the junction's entry heading, not wherever an earlier
            # (aborted) attempt left the robot.
            base = pose.yaw if self._junction_entry is None else self._junction_entry[0]
            j['target'] = _wrap(base+math.radians(j['turn_deg']))
            error = _wrap(j['target']-pose.yaw)
            j.update(sub='rotating', phase_at=now, limit=abs(error)/floor+TURN_TIME_MARGIN_S)
        error = _wrap(j['target']-pose.yaw)
        if j['sub'] == 'rotating':
            # Review M6: stop early by what the commanded rate turns during the latency.
            if abs(error) > max(tolerance, abs(j['w'])*self._config.junction_turn_lead_s):
                j['w'] = math.copysign(min(cap, max(floor, TURN_GAIN*abs(error))), error)
                return j['w']
            j.update(sub='settling', w=0., settled_at=None)
        # settling: inside the tolerance for SETTLE_S, small corrections at the floor rate.
        if abs(error) > tolerance:
            j['settled_at'] = None
            j['w'] = math.copysign(floor, error)
            return j['w']
        if j['settled_at'] is None:
            j['settled_at'] = now
        j['w'] = 0.
        # Review R2: also standing still on odom, not only inside 5 deg of a lagging yaw.
        return None if now-j['settled_at'] >= SETTLE_S and self._standing_still(now) else 0.
