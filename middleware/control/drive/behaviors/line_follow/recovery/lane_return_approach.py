"""D-468 bounded approach to a sensor-verified corridor without an old checkpoint.

The caller owns fresh authority, floor and swept-space checks. Travel is measured
from successive actual poses. This proposes a twist and never publishes it.
"""
import math


class CorridorApproach:
    def __init__(self):
        self.anchor = None
        self.previous = None
        self.travel = 0.
        self.yaw_travel = 0.
        self.finished = False
        self.motion_start = None

    def step(self, inp, lane):
        if self.finished:
            return None
        if self.anchor is None:
            self.anchor = (inp.now, inp.pose, lane)
            self.previous = inp.pose
        start, origin, candidate = self.anchor
        if not lane.matches(candidate, origin, inp.pose):
            self.finished = True
            return None
        delta = math.hypot(inp.pose.x-self.previous.x, inp.pose.y-self.previous.y)
        turn = inp.pose.yaw-self.previous.yaw
        self.yaw_travel += abs(math.atan2(math.sin(turn),math.cos(turn)))
        self.travel += delta
        self.previous = inp.pose
        if inp.now-start >= 8 or self.travel >= .15 or self.yaw_travel >= 1.4:
            self.finished = True
            return None
        # Once lateral alignment is near, straighten in place inside verified space.
        if abs(lane.center) <= .008 and abs(lane.heading) > .12:
            return (0., max(-inp.angular_limit, min(inp.angular_limit, lane.heading)))
        if not inp.front_clear or not inp.turn_clear or abs(lane.center) > .12:
            return None
        if self.motion_start is None:
            self.motion_start = inp.now
        if inp.now-self.motion_start >= 1 and self.travel < .002:
            self.finished = True
            return None
        lookahead = .05
        target_y = lane.center+math.tan(lane.heading)*lookahead
        speed = min(.03, inp.linear_limit)
        angular = 2*speed*target_y/(lookahead*lookahead+target_y*target_y)
        scale = min(1.,inp.angular_limit/abs(angular)) if angular else 1.
        return (speed*scale, max(-inp.angular_limit,min(inp.angular_limit,angular*scale)))
