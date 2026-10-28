"""D-769 rev 1: under a route prior a map bridge is bounded and slow, then the robot looks again, then it stands."""
import math

import numpy as np

from control.sensing.perception.drivable.drivable_steer import DrivableSteer, LOOKAHEAD_M, PIVOT_ERROR
from control.sensing.perception.drivable.route_guard import BRIDGE_CONFIDENCE, BRIDGE_MAX_M, RouteBridge

BRIDGE = dict(strategy='drivable_map_bridge', target_m=None, target_now_m=None)


def _steps(frames):
    """frames: (strategy info, pose); returns each step's (error, confidence, info)."""
    owner, bridge = DrivableSteer(), RouteBridge()
    return owner, [bridge.step(0.1, 0.6, dict(info), pose, owner) for info, pose in frames]


def _bridge(guide, pose):
    return dict(BRIDGE, guide_deg=guide), pose


def test_the_bridge_creeps_at_most_the_blind_zone_then_stands_when_the_route_runs_straight():
    _, out = _steps([_bridge(3.0, (x, 0.0, 0.0)) for x in (0.0, 0.05, 0.10, BRIDGE_MAX_M, BRIDGE_MAX_M + 0.01)])
    assert all(i['strategy'] == 'drivable_route_bridge' and c == BRIDGE_CONFIDENCE for _, c, i in out[:4])
    error, _, info = out[4]
    assert error is None and info['reason'] == 'route_bridge_spent'


def test_the_bridge_drives_the_arc_it_was_checked_on_at_its_creep_speed():
    """Review HIGH: CORE keeps angular per error; the error must be the one for the arc at BRIDGE_CONFIDENCE."""
    owner, out = _steps([_bridge(20.0, (0.0, 0.0, 0.0))])
    expected = owner.pursuit_error(LOOKAHEAD_M, LOOKAHEAD_M * math.tan(math.radians(20.0)), BRIDGE_CONFIDENCE)
    assert out[0][0] == expected and out[0][1] == BRIDGE_CONFIDENCE
    assert expected != owner.pursuit_error(LOOKAHEAD_M, LOOKAHEAD_M * math.tan(math.radians(20.0)), 0.6)


def test_spent_on_a_bend_it_looks_toward_the_bend_as_it_stood_though_the_guide_shrinks_as_it_turns():
    spent = BRIDGE_MAX_M + 0.01
    frames = [_bridge(20.0, (0.0, 0.0, 0.0)), _bridge(20.0, (spent, 0.0, 0.0)),
              _bridge(12.0, (spent, 0.0, math.radians(8.0))), _bridge(6.0, (spent, 0.0, math.radians(14.0))),
              _bridge(0.0, (spent, 0.0, math.radians(20.5)))]
    _, out = _steps(frames)
    assert [o[2]['strategy'] for o in out[1:4]] == ['route_look_left'] * 3
    assert out[1][0] == -PIVOT_ERROR
    assert out[4][0] is None and out[4][2]['reason'] == 'route_bridge_spent'


def test_only_a_frame_on_seen_floor_gives_a_new_budget():
    spent = BRIDGE_MAX_M + 0.01
    pivot = dict(strategy='drivable_pivot_left'), (spent, 0.0, 0.0)
    centre = dict(strategy='drivable_centre'), (spent, 0.0, 0.0)
    _, out = _steps([_bridge(3.0, (0.0, 0.0, 0.0)), pivot, _bridge(3.0, (spent, 0.0, 0.0))])
    assert out[2][0] is None and out[2][2]['reason'] == 'route_bridge_spent'     # a pivot saw no floor
    _, out = _steps([_bridge(3.0, (0.0, 0.0, 0.0)), centre, _bridge(3.0, (spent, 0.0, 0.0))])
    assert out[2][2]['strategy'] == 'drivable_route_bridge'                       # the camera drove on floor


def test_no_odometry_no_bridge():
    error, _, info = RouteBridge().step(0.1, 0.6, dict(BRIDGE, guide_deg=0.0), None, DrivableSteer())
    assert error is None and info['reason'] == 'route_bridge_no_odometry'


def test_the_steer_refuses_a_bridge_across_a_lane_line_seen_before_and_bridges_without_it():
    from test_drivable_steer import G, HALF, XO, _lane

    def closed(line):
        steer = DrivableSteer()   # no earlier frame, so no strategy-switch delay hides the result
        pose = (0.0, 0.0, 0.0)
        steer._edges = [(0.15, float(y)) for y in np.linspace(-0.5, 0.5, 80)] if line else []
        return steer.update(_lane(HALF, -HALF, x_max=0.12), 2, G, XO, HALF, pose, pose, guide_deg=0.0)[2]
    assert closed(False)['strategy'] == 'drivable_map_bridge'     # control: the same closed way bridges
    assert closed(True)['strategy'] != 'drivable_map_bridge'      # a line seen across it refuses the bridge
