"""Route priors never make unobserved floor an observation (D-769 rev 1): under one a map bridge creeps at most
BRIDGE_MAX_M along the route, then the robot turns toward it to look again, then stands for CORE's HOLD.
CORE's LiDAR, body and IR stops act every tick; the steer refuses a bridge across a boundary seen earlier."""
import math

from .target import _to_current

BRIDGES = ('drivable_map_bridge', 'drivable_creep_map')
#: frames that mean the camera saw floor ahead: only these give a new bridge budget (review: not pivots)
SEEN_FLOOR = ('drivable_centre', 'drivable_turn_')
BRIDGE_MAX_M = 0.14        # the camera's near blind zone (~0.14 m ahead of the wheels)
BRIDGE_CONFIDENCE = 0.45   # creep: the default law scales (0.45 - 0.35) / 0.65 = 15 % of cruise
LOOK_MIN_DEG = 15.0        # a route bend under this is straight on: turning shows nothing new
LOOK_MAX_RAD = math.pi / 2


class RouteBridge:
    """Per steer: the bridge's odometry start and the look-again turn's start yaw."""
    def __init__(self):
        self.start = self.look = None
        self._alignment = None

    def invalidate_alignment(self):
        """A reset/lost observation cannot prove the old odometry episode continued."""
        if self._alignment is not None:
            self._alignment['uncertain'] = True

    def _align(self, error, confidence, info, pose, owner, source_pose, stamp, observed):
        from .drivable_steer import (BEND_ON_X_M, LOOKAHEAD_M, MAX_CRUISE_MPS, PIVOT_AHEAD_M, PIVOT_ERROR,
                                     PIVOT_MAX_RAD, REALIGN_DEG, RECENTRE_M)
        from .drivable_keep import WAY_MAX_AGE_S
        from ..learned.paint_motion import ODOM_HISTORY_MAX_GAP_S

        def valid(value, size):
            try:
                return len(value) == size and all(math.isfinite(v) for v in value)
            except (TypeError, ValueError):
                return False

        timing = valid((stamp, observed), 2) and 0.0 <= stamp - observed <= WAY_MAX_AGE_S
        poses = valid(pose, 3) and valid(source_pose, 3)
        if timing and poses:
            age = stamp - observed
            poses = (math.hypot(pose[0] - source_pose[0], pose[1] - source_pose[1]) <= MAX_CRUISE_MPS * age + 1e-6
                     and abs(math.remainder(pose[2] - source_pose[2], math.tau)) <= owner.steering_law['steering_gain'] * age + 1e-6)
        state = self._alignment
        if state is not None:
            if not timing or not poses:
                state['uncertain'] = True
            else:
                dt = stamp - state['stamp']
                distance = math.hypot(pose[0] - state['last'][0], pose[1] - state['last'][1])
                angle = abs(math.remainder(pose[2] - state['last'][2], math.tau))
                law = owner.steering_law
                if (not 0.0 <= dt <= ODOM_HISTORY_MAX_GAP_S
                        or distance > MAX_CRUISE_MPS * dt + 1e-6
                        or angle > law['steering_gain'] * dt + 1e-6):
                    state['uncertain'] = True
                state['used'] += angle
                state['stamp'], state['last'] = stamp, tuple(pose)
                moved = math.hypot(pose[0] - state['origin'][0], pose[1] - state['origin'][1])
                # Independent observed forward floor AND continuous physical progress; a pivot or mask flicker is no refill.
                if (not state['uncertain'] and moved > BRIDGE_MAX_M and observed > state['observed']
                        and error is not None and info['strategy'] == 'drivable_centre'
                        and not info.get('reason') and not info.get('straddle')
                        and info.get('ahead_m', 0.0) >= LOOKAHEAD_M and len(info.get('centre_path_m', [])) >= 2):
                    self._alignment = state = None

        pivot = next((side for side, sign in (('left', -1), ('right', 1))
                      if info['strategy'] == f'drivable_pivot_{side}' and error == sign * PIVOT_ERROR
                      and confidence == owner._pivot_confidence), None)
        closed = error is None and info.get('reason') == 'drivable_closed' and info.get('recentre_first')
        opposing = state is not None and pivot is not None and pivot != state['side']
        if (info.get('front_blocked_m') is not None or info.get('pivot_limit')
                or info.get('straddle') or info.get('crosswalk_hold')):
            return None
        # A spent/uncertain observed episode cannot fall back to its opposing future-route latch.
        reason = ('recentre_alignment_spent' if opposing and state['used'] >= state['limit'] else
                  'recentre_alignment_odometry' if opposing and state['uncertain'] else None)
        if reason:
            return None, None, dict(info, strategy='none', reason=reason, target_m=None, target_now_m=None)
        ctx = owner._ctx
        fallback = ((None, None, dict(info, strategy='none', reason='recentre_alignment_unobserved',
                                     target_m=None, target_now_m=None)) if opposing else None)
        if (not (closed or pivot) or not timing or not poses or not ctx.get('guide') or not ctx.get('fresh')):
            return fallback
        near, target, seen = info.get('near_centre_m'), info.get('target_m'), info.get('seen_exit')
        opening = info.get('exit_point_m', {}).get(seen)
        if not (valid(near, 2) and valid(target, 2) and valid(opening, 2)):
            return fallback
        if info.get('exit_reach_m', {}).get(seen, 0.0) < PIVOT_AHEAD_M:
            return fallback
        near, target, opening = (_to_current(point, source_pose, pose) for point in (near, target, opening))
        sign = 1.0 if near[1] > 0.0 else -1.0
        bearing = math.atan2(near[1], near[0])
        here = ctx.get('here')
        if (near[0] <= 0.0 or not 0.0 < target[0] < BEND_ON_X_M or opening[0] <= 0.0
                or (not opposing and abs(near[1]) < RECENTRE_M) or target[1] * sign <= 0.0 or opening[1] * sign <= 0.0
                or here is None or not math.isfinite(here)
                or abs(math.remainder(math.radians(here) - bearing, math.tau)) > math.radians(REALIGN_DEG)):
            return fallback
        side = 'left' if sign > 0.0 else 'right'
        if pivot == side:
            return fallback
        if state is None:
            state = self._alignment = dict(origin=tuple(pose), last=tuple(pose), stamp=stamp, observed=observed,
                used=0.0, limit=min(PIVOT_MAX_RAD, abs(bearing)), side=side, uncertain=False)
        reason = ('recentre_alignment_spent' if state['used'] >= state['limit'] else
                  'recentre_alignment_odometry' if state['uncertain'] else
                  'recentre_alignment_changed' if state['side'] != side else None)
        detail = dict(info, target_m=None, target_now_m=None,
                      alignment_used_rad=round(state['used'], 4), alignment_limit_rad=round(state['limit'], 4))
        if reason:
            return None, None, dict(detail, strategy='none', reason=reason)
        return -sign * PIVOT_ERROR, owner._pivot_confidence, dict(detail,
            strategy=f'drivable_recentre_pivot_{side}', reason=None)

    def step(self, error, confidence, info, pose, owner, *, source_pose=None, current_stamp=None, observation_stamp=None):
        alignment = self._align(error, confidence, info, pose, owner, source_pose, current_stamp, observation_stamp)
        if alignment is not None:
            return alignment
        if info['strategy'] not in BRIDGES:
            if error is not None and info['strategy'].startswith(SEEN_FLOOR):   # the camera saw floor: new budget
                self.start = self.look = None
            return error, confidence, info
        if pose is None:
            return None, None, dict(info, strategy='none', reason='route_bridge_no_odometry', target_m=None, target_now_m=None)
        self.start = self.start or (pose[0], pose[1])
        used = math.hypot(pose[0] - self.start[0], pose[1] - self.start[1])
        guide = info.get('guide_deg')
        if used <= BRIDGE_MAX_M and self.look is None and guide is not None:
            from .drivable_steer import LOOKAHEAD_M, PIVOT_ERROR   # (steer imports this module)
            # the arc at the creep speed it is driven at: CORE keeps angular per error, so an error computed for a
            # faster confidence would drive a tighter arc than the one the steer checked against seen lines (review)
            error = owner.pursuit_error(LOOKAHEAD_M, LOOKAHEAD_M * math.tan(math.radians(guide)), BRIDGE_CONFIDENCE)
            return error, BRIDGE_CONFIDENCE, dict(info, strategy='drivable_route_bridge', bridge_m=round(used, 3))
        if self.look is None:   # spent: look toward the bend as it stood then (the guide shrinks as the robot turns)
            self.look = (pose[2], guide or 0.0)
        turned = abs(math.atan2(math.sin(pose[2] - self.look[0]), math.cos(pose[2] - self.look[0])))
        bend = self.look[1]
        if abs(bend) >= LOOK_MIN_DEG and turned < min(LOOK_MAX_RAD, math.radians(abs(bend))):
            from .drivable_steer import PIVOT_ERROR
            side = 'left' if bend > 0 else 'right'
            return (-PIVOT_ERROR if side == 'left' else PIVOT_ERROR), owner._pivot_confidence, dict(
                info, strategy=f'route_look_{side}', bridge_m=round(used, 3), target_m=None, target_now_m=None)
        return None, None, dict(info, strategy='none', reason='route_bridge_spent', bridge_m=round(used, 3),
                                target_m=None, target_now_m=None)


def observed_route_candidate(error, confidence, info, *, observed_only, owner=None, pose=None,
                             source_pose=None, current_stamp=None, observation_stamp=None):
    if not observed_only or owner is None:
        return error, confidence, info
    bridge = owner.__dict__.setdefault('_route_bridge', RouteBridge())
    return bridge.step(error, confidence, info, pose, owner, source_pose=source_pose,
                       current_stamp=current_stamp, observation_stamp=observation_stamp)
