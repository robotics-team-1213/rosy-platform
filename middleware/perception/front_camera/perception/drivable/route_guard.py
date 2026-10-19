"""Route priors never make unobserved floor an observation (D-769 rev 1): under one a map bridge creeps at most
BRIDGE_MAX_M along the route, then the robot turns toward it to look again, then stands for CORE's HOLD.
CORE's LiDAR, body and IR stops act every tick; the steer refuses a bridge across a boundary seen earlier."""
import math

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

    def step(self, error, confidence, info, pose, owner):
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


def observed_route_candidate(error, confidence, info, *, observed_only, owner=None, pose=None):
    if not observed_only or owner is None:
        return error, confidence, info
    bridge = owner.__dict__.setdefault('_route_bridge', RouteBridge())
    return bridge.step(error, confidence, info, pose, owner)
