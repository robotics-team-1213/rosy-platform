"""D-759 rev 1: a left/right junction turn aims at the exit lane's map heading (Fleet's map_entry,
carried into odom by the yaw pair) instead of entry yaw + turn_deg, within MAP_ENTRY_MAX_HEADING_RAD."""
import math

import pytest

from core_features.line_follow import authority
from core_features.line_follow.recovery.junction.turn import TURN_MAP_ENTRY_MAX_RAD
from test_lane_arc import SEGMENT, ArcRig
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


def _send(rig, entry=None, turn=TURN, seq=1):
    expect = None if entry is None else dict(map_entry=entry)
    action = 'left' if turn > 0 else 'right'
    assert rig.m.set_junction(action, 'J1', 10., None, turn, None, expect=expect) == (True, seq, 'armed')


def _turn(rig, entry=None, turn=TURN, sent=False):
    """Send the turn (with `entry` as map_entry) unless `sent`, stop at the junction and turn: the status."""
    if not sent:
        _send(rig, entry, turn)
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
    (dict(exit_yaw=EXIT+INHERITED+TURN_MAP_ENTRY_MAX_RAD+.01), 'heading'),
    (dict(exit_yaw=EXIT+INHERITED+math.radians(20.)), 'heading'),   # review: 20 deg off is a wrong map yaw
    (dict(odom_stamp_s=WALL-3.), 'stale'),
    (dict(odom_stamp_s=WALL+1.2), 'future'),                      # rig time ~1.05: 0.15 s ahead
])
def test_a_map_entry_it_cannot_use_keeps_todays_target_with_the_reason(over, reason):
    rig = _rig()
    status = _turn(rig, _entry(rig, **over))
    assert rig.m._junction['target'] == pytest.approx(_wrapped(INHERITED+EXIT), abs=1e-9)
    assert (status.junction.map_entry_used, status.junction.map_entry_reason) == (False, reason)


def test_a_map_heading_just_inside_the_bound_is_used():
    rig = _rig()
    near = EXIT+INHERITED+TURN_MAP_ENTRY_MAX_RAD-.01
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


def test_a_left_turn_takes_the_map_heading_too():
    rig = _rig()
    exit_yaw = math.radians(-TURN)
    status = _turn(rig, _entry(rig, exit_yaw=exit_yaw), turn=-TURN)
    assert rig.m._junction['target'] == pytest.approx(exit_yaw, abs=1e-9)
    assert status.junction.map_entry_used is True


def test_a_new_odom_run_between_receipt_and_turn_keeps_todays_target():
    """Review 1: a new run restarts the path length, so carry alone would pass."""
    rig = _rig()
    _send(rig, _entry(rig))
    rig.m.invalidate_return_pose()
    rig.step()
    status = _turn(rig, sent=True)
    assert rig.m._junction['target'] == pytest.approx(_wrapped(INHERITED+EXIT), abs=1e-9)
    assert (status.junction.map_entry_used, status.junction.map_entry_reason) == (False, 'epoch')


def test_more_odom_travel_than_the_carry_bound_keeps_todays_target():
    rig = _rig()
    _send(rig, _entry(rig))
    while rig.x <= authority.ARC_ANCHOR_MAX_CARRY_M+.05:
        rig.step(dx=.02)
    status = _turn(rig, sent=True)
    assert (status.junction.map_entry_used, status.junction.map_entry_reason) == (False, 'carry')
    assert rig.m._junction['target'] == pytest.approx(_wrapped(INHERITED+EXIT), abs=1e-9)


def test_a_resend_of_the_armed_turn_places_a_heading_the_first_could_not():
    rig = _rig()
    _send(rig, _entry(rig, odom_stamp_s=WALL-3.))
    assert rig.m.status().junction.map_entry_reason == 'stale'
    _send(rig, _entry(rig), seq=2)
    assert rig.m.status().junction.map_entry_reason is None
    status = _turn(rig, sent=True)
    assert rig.m._junction['target'] == pytest.approx(EXIT, abs=1e-9) and status.junction.map_entry_used


def test_a_map_target_past_180_deg_still_turns_the_commanded_way():
    """Review 3: 150 deg left plus a 14 deg correction, the body 17 deg right of its entry yaw."""
    rig = _rig()
    turn, extra = 150., math.radians(14.)
    _send(rig, _entry(rig, exit_yaw=INHERITED+math.radians(turn)+extra), turn=turn)
    rig.step()
    rig.step(junction=True, seen=False)
    for _ in range(3):                                   # under the odom trail's yaw-jump bound
        rig.yaw -= math.radians(17.)/3
        rig.step(seen=False)
    for _ in range(20):
        decision, status = rig.step(seen=False, move=True)
        if decision.angular:
            break
    assert status.junction.state == 'turning' and status.junction.map_entry_used is True
    assert decision.angular > 0                          # left, the long way (181 deg), not right


def test_a_turn_into_a_d520_arc_leaves_on_the_map_heading():
    rig = ArcRig(turn_map_entry_enabled=True)
    rig.m._wall = lambda: WALL + rig.now
    rig.step()
    exit_yaw = math.radians(64.+5.)                      # the body entered 5 deg right of the lane
    entry = _entry(rig, exit_yaw=exit_yaw)
    assert rig.m.set_junction('left', 'SW', 10., None, 64., .2,
                              expect=dict(map_id='lab-a', expect_in_m=.4, expect_tol_m=.1, pivot_past_line_m=0.,
                                          map_entry=entry), exit_segment=dict(SEGMENT)) == (True, 1, 'armed')
    while rig.x < .2 - 1e-9:
        rig.step(dx=.01)
    rig.m.observe_junction('junction_transverse', round(rig.now + .05, 6), ahead_m=.2)
    rig.step(seen=False)
    _, status = rig.until(lambda d, s: s.arc is not None, seen=False)
    assert status.arc.state == 'running'
    assert rig.m._arc['yaw0'] == pytest.approx(exit_yaw, abs=1e-9)
