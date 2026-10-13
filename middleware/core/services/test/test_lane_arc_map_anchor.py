"""D-744 SOURCE: the arc's circle anchored in the map. Fleet's `exit_segment.map_anchor` (the map
circle centre and one map pose / odom stamp pair) is placed in odom at receipt and opens the arc;
every case it cannot be trusted keeps today's pose-derived circle. Real LineFollowManager on the
kinematic rig of test_lane_arc.py, no ROS, no physical motion."""
import math

import pytest

from core_features.line_follow.arc import lane_arc
from core_features.line_follow.authority import (ARC_ANCHOR_MAX_AGE_S, ARC_ANCHOR_MAX_CARRY_M,
                                                  ARC_ANCHOR_MAX_HEADING_RAD, ARC_ANCHOR_MAX_RADIAL_M)
from test_lane_arc import K, SEGMENT, ArcRig, running, send

WALL = 1_790_000_000.            # CORE wall clock at rig time 0 (snapshot odom_pose.stamp is on it)
MAP_TURN, MAP_SHIFT = .4, (2., 1.)   # the map frame: odom turned and shifted


def _wall_rig(**config):
    rig = ArcRig(**config)
    rig.m._wall = lambda: WALL + rig.now
    rig.step()
    return rig


def _to_map(x, y):
    c, s = math.cos(MAP_TURN), math.sin(MAP_TURN)
    return c*x - s*y + MAP_SHIFT[0], s*x + c*y + MAP_SHIFT[1]


def _anchor(rig, centre, **over):
    """Fleet's anchor for a circle centred at `centre` in the rig's odom frame, with the pose pair
    of the rig's newest odom sample."""
    (cx, cy), (px, py) = _to_map(*centre), _to_map(rig.x, rig.y)
    return dict(dict(centre_x_m=cx, centre_y_m=cy, pose_x_m=px, pose_y_m=py,
                     pose_yaw_rad=rig.yaw + MAP_TURN, odom_stamp_s=WALL + rig.now), **over)


def _off_circle(k=K, radial=.02, off_deg=10.):
    """The centre of a circle the robot at the odom origin (yaw 0) is `radial` outside of, heading
    `off_deg` outward of its tangent."""
    phi = math.copysign(math.radians(off_deg), k) - math.copysign(math.pi/2, k)
    d = 1/abs(k) + radial
    return -d*math.cos(phi), -d*math.sin(phi)


def _radial(rig, centre, k=K):
    return math.hypot(rig.x - centre[0], rig.y - centre[1]) - 1/abs(k)


def _pose_circle(rig, k=K):
    """Today's circle: tangent to the robot's own pose."""
    return rig.x - math.sin(rig.yaw)/k, rig.y + math.cos(rig.yaw)/k


def _open(rig):
    with rig.m._lock:
        assert rig.m._open_arc(rig.m._junction, rig.now) is None
    return rig.m.status()


def _send_open(rig, anchor, segment=SEGMENT):
    turn = math.copysign(64., segment['curvature_1pm'])
    send(rig, 'left' if turn > 0 else 'right', 'SW', turn, dict(segment, map_anchor=anchor))
    return _open(rig)


# --- the map circle ------------------------------------------------------------------------------

@pytest.mark.parametrize('k', [K, -K])
@pytest.mark.parametrize('length, final', [(SEGMENT['length_m'], .015), (1., .01)])
def test_a_map_anchor_opens_the_arc_on_the_map_circle_and_the_robot_converges(k, length, final):
    """Gazebo 2026-10-13: the pivot ended 2 cm outside the ring and 10 deg off its tangent."""
    rig, centre = _wall_rig(), _off_circle(k)
    status = _send_open(rig, _anchor(rig, centre), dict(SEGMENT, curvature_1pm=k, length_m=length))
    assert rig.m._arc['centre'] == pytest.approx(centre, abs=1e-9)
    assert rig.m._arc['centre'] != pytest.approx(_pose_circle(rig, k), abs=.01)
    assert status.arc.map_anchor_used is True and status.arc.state == 'running'
    assert status.arc.map_anchor_reason is None
    assert _radial(rig, centre, k) == pytest.approx(.02)
    worst = 0.
    while running(rig):
        rig.drive()
        worst = max(worst, abs(_radial(rig, centre, k)))
    assert rig.m._arc['reason'] == 'lane_arc_end_unarmed' and rig.m._arc['corr'] is None
    assert worst <= .04 and abs(_radial(rig, centre, k)) <= final, (worst, _radial(rig, centre, k))


def test_the_anchored_tangent_is_the_ir_level_reference():
    """yaw0 is the map circle's tangent at the opening pose (not the robot's own heading)."""
    rig, centre = _wall_rig(), _off_circle()
    _send_open(rig, _anchor(rig, centre))
    assert rig.m._arc['yaw0'] == pytest.approx(math.radians(10.))


def test_the_anchor_is_placed_at_receipt_and_carried_over_odom_to_the_opening():
    """The instruction comes 0.6 m before the place: the pair's odom sample is long gone when the
    arc opens, so the centre is placed in odom when the instruction is received."""
    rig = _wall_rig()
    centre = (.5, 1/K)                          # the circle the robot reaches after 0.5 m
    send(rig, 'left', 'SW', 64., dict(SEGMENT, map_anchor=_anchor(rig, centre)))
    while rig.x < .5 - 1e-9:
        rig.step(dx=.01)                        # 2.5 s: more than the anchor's age bound
    status = _open(rig)
    assert rig.m._arc['centre'] == pytest.approx(centre, abs=1e-9) and status.arc.map_anchor_used


def test_a_chained_straight_takes_a_fresh_anchor_and_keeps_the_integral():
    rig = _wall_rig()
    send(rig, 'left', 'SW', 64., dict(SEGMENT))
    _open(rig)
    kept = rig.m._arc['centre']
    rig.turn_scale = .85                        # an under-turning robot builds the integral
    rig.drive(20)
    centre = (kept[0] + .01, kept[1])
    send(rig, 'straight', 'SE', segment=dict(SEGMENT, end_place_id='NE', length_m=.4595,
                                             map_anchor=_anchor(rig, centre)))
    for _ in range(400):
        integral = rig.m._arc['integral']
        if rig.drive()[1].arc.arc_seq == 2:
            break
    assert rig.m._arc['centre'] == pytest.approx(centre, abs=1e-9)
    assert rig.m.status().arc.map_anchor_used is True
    # the ring's integral is carried on (it is the robot's turn response, not the circle's place)
    assert abs(integral) > .01 and rig.m._arc['integral'] == pytest.approx(integral, abs=1e-9)


def test_a_chained_straight_after_an_ir_correction_keeps_the_paint_anchored_circle():
    """Review 3: the IR verdict re-anchored the ring on the paint; a map anchor does not undo it."""
    rig = _wall_rig()
    send(rig, 'left', 'SW', 64., dict(SEGMENT))
    _open(rig)
    rig.drive(20)
    kept = rig.m._arc['centre']
    send(rig, 'straight', 'SE', segment=dict(SEGMENT, end_place_id='NE', length_m=.4595,
                                             map_anchor=_anchor(rig, (kept[0] + .01, kept[1]))))
    assert 'centre' in rig.m._junction['arc_anchor']
    # the record of a finished one-time correction (driven for real in test_lane_arc.py)
    rig.m._arc['corr'] = dict(side='right', phase='done', away_m=.12, level_m=.01, deadline=0.)
    rig.until(lambda d, s: s.arc.arc_seq == 2)
    arc = rig.m.status().arc
    assert rig.m._arc['centre'] == kept
    assert (arc.map_anchor_used, arc.map_anchor_reason) == (False, 'ir_chain')


def test_a_chained_straight_without_an_anchor_keeps_the_previous_circle():
    rig = _wall_rig()
    _send_open(rig, _anchor(rig, _off_circle()))
    kept = rig.m._arc['centre']
    send(rig, 'straight', 'SE', segment=dict(SEGMENT, end_place_id='NE', length_m=.4595))
    rig.until(lambda d, s: s.arc.arc_seq == 2)
    assert rig.m._arc['centre'] == kept and rig.m.status().arc.map_anchor_used is False
    assert rig.m.status().arc.map_anchor_reason == 'none_sent'


# --- fail closed: the pose-derived circle of D-520, with the reason on the record -----------------

def _todays(rig, status, reason):
    assert rig.m._arc['centre'] == pytest.approx(_pose_circle(rig), abs=1e-12)
    assert rig.m._arc['yaw0'] == rig.yaw
    assert status.arc.state == 'running'
    assert (status.arc.map_anchor_used, status.arc.map_anchor_reason) == (False, reason)


def test_no_anchor_keeps_todays_circle():
    rig = _wall_rig()
    send(rig, 'left', 'SW', 64., dict(SEGMENT))
    _todays(rig, _open(rig), 'none_sent')
    dump = rig.m.status().arc.model_dump()
    assert (dump['map_anchor_used'], dump['map_anchor_reason']) == (False, 'none_sent')


@pytest.mark.parametrize('bad', [
    dict(centre_x_m=math.nan), dict(centre_y_m=math.inf), dict(pose_x_m=-math.inf),
    dict(pose_y_m=math.nan), dict(pose_yaw_rad=math.nan), dict(odom_stamp_s=math.nan),
    dict(odom_stamp_s=None), dict(centre_x_m='1')])
def test_a_non_finite_anchor_keeps_todays_circle(bad):
    rig = _wall_rig()
    _todays(rig, _send_open(rig, _anchor(rig, _off_circle(), **bad)), 'malformed')


@pytest.mark.parametrize('anchor', [{}, 'x', dict(centre_x_m=1., centre_y_m=1.)])
def test_a_malformed_anchor_keeps_todays_circle(anchor):
    rig = _wall_rig()
    _todays(rig, _send_open(rig, anchor), 'malformed')


def test_an_anchor_older_than_the_bound_keeps_todays_circle():
    rig = _wall_rig()
    old = _anchor(rig, _off_circle())           # its odom sample stays in the trail (5 s)
    for _ in range(round(ARC_ANCHOR_MAX_AGE_S/.05) + 1):
        rig.step()
    _todays(rig, _send_open(rig, old), 'stale')


def test_an_anchor_inside_the_age_bound_is_used():
    rig = _wall_rig()
    anchor, centre = _anchor(rig, _off_circle()), _off_circle()
    for _ in range(round(ARC_ANCHOR_MAX_AGE_S/.05) - 2):
        rig.step()
    assert _send_open(rig, anchor).arc.map_anchor_used is True
    assert rig.m._arc['centre'] == pytest.approx(centre, abs=1e-9)


@pytest.mark.parametrize('offset, reason', [(.5, 'future'), (-.9, 'no_sample')])
def test_a_stamp_outside_cores_odom_history_keeps_todays_circle(offset, reason):
    """Newer than CORE's clock, or older than the first odom sample of this run."""
    rig = _wall_rig()
    rig.step()
    anchor = _anchor(rig, _off_circle(), odom_stamp_s=WALL + rig.now + offset)
    _todays(rig, _send_open(rig, anchor), reason)


@pytest.mark.parametrize('after_s', [.001, .01])
def test_a_stamp_a_few_ms_after_its_odom_sample_is_paired_with_it(after_s):
    """Review 6: snapshot odom_pose.stamp is taken just after the sample is logged."""
    rig, centre = _wall_rig(), _off_circle()
    anchor = _anchor(rig, centre, odom_stamp_s=WALL + rig.now + after_s)
    rig.step()                                  # a newer sample exists; the pair is the older one
    assert _send_open(rig, anchor).arc.map_anchor_used is True
    assert rig.m._arc['centre'] == pytest.approx(centre, abs=1e-9)


def test_a_stamp_more_than_the_tolerance_after_any_sample_keeps_todays_circle():
    rig = _wall_rig()
    anchor = _anchor(rig, _off_circle(), odom_stamp_s=WALL + rig.now + .051)
    rig.step(pose=False)                        # no odom sample for 0.05 s: the nearest is 0.051 s older
    send(rig, 'left', 'SW', 64., dict(SEGMENT, map_anchor=anchor))
    assert rig.m._junction['arc_anchor'] == dict(reason='no_sample')


def test_an_odom_reset_before_receipt_keeps_todays_circle():
    rig = _wall_rig()
    anchor = _anchor(rig, _off_circle())
    rig.m.invalidate_return_pose()              # a new odom epoch: the sample of the pair is gone
    rig.step()
    _todays(rig, _send_open(rig, anchor), 'no_sample')


def test_an_odom_jump_between_receipt_and_opening_keeps_todays_circle():
    rig = _wall_rig()
    send(rig, 'left', 'SW', 64., dict(SEGMENT, map_anchor=_anchor(rig, _off_circle())))
    rig.x += 1.                                 # a discontinuity: a new odom epoch
    rig.step()
    _todays(rig, _open(rig), 'epoch')


def test_an_odom_frame_change_between_receipt_and_opening_keeps_todays_circle():
    rig = _wall_rig()
    send(rig, 'left', 'SW', 64., dict(SEGMENT, map_anchor=_anchor(rig, _off_circle())))
    rig.now = round(rig.now + .05, 6)
    stamp = round(rig.now*1e9)
    rig.m.observe_return_pose(stamp_ns=stamp, source_now_ns=stamp, frame='odom2', x=rig.x, y=rig.y,
                              yaw=rig.yaw, received_at=rig.now)
    _todays(rig, _open(rig), 'epoch')


def test_more_odom_travel_than_the_carry_bound_keeps_todays_circle():
    rig = _wall_rig()
    far = ARC_ANCHOR_MAX_CARRY_M + .05
    send(rig, 'left', 'SW', 64., dict(SEGMENT, map_anchor=_anchor(rig, (far, 1/K))), expires_s=30.)
    while rig.x < far - 1e-9:
        rig.step(dx=.02)
    _todays(rig, _open(rig), 'carry')


def test_the_carry_bound_counts_path_length_not_net_travel():
    """Review 4: forward and back again is travel (odom drift), though the odometer nets to zero."""
    rig = _wall_rig()
    send(rig, 'left', 'SW', 64., dict(SEGMENT, map_anchor=_anchor(rig, (0., 1/K))), expires_s=30.)
    half = round((ARC_ANCHOR_MAX_CARRY_M/2 + .04)/.02)
    for dx in [.02]*half + [-.02]*half:
        rig.step(dx=dx)
    assert abs(rig.x) < 1e-9 and abs(rig.m._return_evidence.trail.odometer) < 1e-9
    _todays(rig, _open(rig), 'carry')


def test_a_circle_the_robot_is_too_far_from_keeps_todays_circle():
    """Review 2: the opening bound is below ARC_MAX_RADIAL_M, the |e_r| that stops the arc."""
    assert ARC_ANCHOR_MAX_RADIAL_M == .045 < lane_arc.ARC_MAX_RADIAL_M
    for radial in (.07, .05):
        rig = _wall_rig()
        _todays(rig, _send_open(rig, _anchor(rig, _off_circle(radial=radial, off_deg=0.))), 'radial')


def test_an_anchor_four_centimetres_off_is_used_and_drives_to_the_arc_end():
    rig, centre = _wall_rig(), _off_circle(radial=.04, off_deg=0.)
    assert _send_open(rig, _anchor(rig, centre)).arc.map_anchor_used is True
    while running(rig):
        rig.drive()
    assert rig.m._arc['reason'] == 'lane_arc_end_unarmed' and rig.m._arc['corr'] is None
    assert abs(_radial(rig, centre)) <= .025, _radial(rig, centre)


@pytest.mark.parametrize('yaw_error', [.5, -.5, math.pi])
def test_a_map_yaw_that_puts_the_heading_off_the_tangent_keeps_todays_circle(yaw_error):
    """Review 1: a wrong pose_yaw_rad turns the placed circle about the robot: |e_r| stays small,
    the tangent does not. Past 25 deg the anchor is not believed."""
    assert ARC_ANCHOR_MAX_HEADING_RAD == pytest.approx(math.radians(25.))
    rig = _wall_rig()
    anchor = _anchor(rig, (0., 1/K))            # the robot exactly on the circle and its tangent
    anchor['pose_yaw_rad'] += yaw_error
    _todays(rig, _send_open(rig, anchor), 'heading')


def test_a_heading_inside_the_bound_is_used():
    rig = _wall_rig()
    status = _send_open(rig, _anchor(rig, _off_circle(radial=0., off_deg=24.)))
    assert (status.arc.map_anchor_used, status.arc.map_anchor_reason) == (True, None)


def test_capability_follows_lane_arc():
    assert _wall_rig().m.supports_lane_arc_map_anchor is True
    assert ArcRig(arc_enabled=False).m.supports_lane_arc_map_anchor is False
