"""D-759 rev 1: a left/right junction turn aims at the exit lane's map heading (Fleet's map_entry,
carried into odom by the yaw pair) instead of entry yaw + turn_deg, within MAP_ENTRY_MAX_HEADING_RAD."""
import math

import pytest

from core_features.line_follow.recovery.junction import bend
from test_line_junction import Rig

WALL = 1_790_000_000.            # CORE wall clock at rig time 0 (snapshot odom_pose.stamp is on it)
MAP_TURN = .4                    # the map frame: odom turned by this
TURN = -108.1                    # Gazebo NW roundabout exit, right turn (Fleet's fixed turn_deg)
INHERITED = -.08                 # Gazebo m18/m19: the body enters the junction 0.07-0.10 rad off the lane
EXIT = math.radians(TURN)        # the exit lane's heading in odom (the entry lane runs along +x)


def _rig(enabled=True):
    rig = Rig(turn_map_entry_enabled=enabled)
    rig.m._wall = lambda: WALL + rig.now
    rig.yaw = INHERITED
    rig.step()
    return rig


def _entry(rig, exit_yaw=EXIT, **over):
    """Fleet's map_entry: the exit lane's map heading and the yaw pair of the newest odom sample."""
    return dict(dict(yaw_rad=exit_yaw+MAP_TURN, pose_yaw_rad=rig.yaw+MAP_TURN, odom_stamp_s=WALL+rig.now), **over)


def _turn(rig, entry=None):
    """Send the right turn (with `entry` as map_entry), stop at the junction and turn: the status."""
    expect = None if entry is None else dict(map_entry=entry)
    assert rig.m.set_junction('right', 'J1', 10., None, TURN, None, expect=expect) == (True, 1, 'armed')
    rig.step()
    rig.step(junction=True, seen=False, move=True)
    _, status = rig.turn_until('turning', seen=False)
    assert status.junction.state == 'advancing'
    return status


def _wrapped(angle):
    return math.atan2(math.sin(angle), math.cos(angle))


def test_the_map_entry_turns_to_the_exit_lanes_heading_despite_an_inherited_yaw_error():
    rig = _rig()
    status = _turn(rig, _entry(rig))
    assert rig.m._junction['target'] == pytest.approx(EXIT, abs=1e-9)
    assert (status.junction.map_entry_used, status.junction.map_entry_reason) == (True, None)
    assert abs(_wrapped(rig.yaw-EXIT)) <= math.radians(5.)


def test_without_a_map_entry_the_inherited_error_passes_into_the_exit_heading_as_before():
    rig = _rig()
    status = _turn(rig)
    assert rig.m._junction['target'] == pytest.approx(_wrapped(INHERITED+EXIT), abs=1e-9)
    assert (status.junction.map_entry_used, status.junction.map_entry_reason) == (False, 'none_sent')


@pytest.mark.parametrize('over, reason', [
    (dict(exit_yaw=EXIT+INHERITED+bend.MAP_ENTRY_MAX_HEADING_RAD+.01), 'heading'),
    (dict(odom_stamp_s=WALL-3.), 'stale'),
])
def test_a_map_entry_it_cannot_use_keeps_todays_target_with_the_reason(over, reason):
    rig = _rig()
    status = _turn(rig, _entry(rig, **over))
    assert rig.m._junction['target'] == pytest.approx(_wrapped(INHERITED+EXIT), abs=1e-9)
    assert (status.junction.map_entry_used, status.junction.map_entry_reason) == (False, reason)


def test_a_map_heading_just_inside_the_bound_is_used():
    rig = _rig()
    near = EXIT+INHERITED+bend.MAP_ENTRY_MAX_HEADING_RAD-.01
    _turn(rig, _entry(rig, exit_yaw=near))
    assert rig.m._junction['target'] == pytest.approx(_wrapped(near), abs=1e-9)


def test_with_the_flag_off_a_map_entry_is_ignored_and_the_turn_is_todays():
    off, plain = _rig(enabled=False), _rig(enabled=False)
    s1, s2 = _turn(off, _entry(off)), _turn(plain)
    assert (s1.junction.map_entry_used, s1.junction.map_entry_reason) == (False, 'disabled')
    assert off.m._junction['target'] == plain.m._junction['target']
    assert (off.yaw, off.x, off.y) == (plain.yaw, plain.x, plain.y)
    assert s2.junction.map_entry_reason == 'none_sent'


def test_capability_needs_the_flag_and_junction_turn():
    for enabled, corner, expected in ((True, True, True), (False, True, False), (True, False, False)):
        rig = Rig(turn_map_entry_enabled=enabled)
        if corner:
            rig.m.observe_junction('no_boundary', rig.now, corner_turning=True)
        assert rig.m.supports_lane_turn_map_entry is expected
    with pytest.raises(ValueError):
        Rig(turn_map_entry_enabled=1)


@pytest.mark.parametrize('action, turn_deg', [('straight', None), ('stop', None), ('left', None)])
def test_map_entry_belongs_to_bend_or_a_turn(action, turn_deg):
    rig = _rig()
    with pytest.raises(ValueError):
        rig.m.set_junction(action, 'J1', 10., None, turn_deg, None, expect=dict(map_entry=_entry(rig)))
