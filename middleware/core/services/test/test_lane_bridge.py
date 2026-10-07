"""D-476 expected-road bridge on lane loss; real manager, no ROS or physical motion."""
import math
from types import SimpleNamespace

import pytest

from core_common.protocol.lane_containment import LaneContainmentEvidence
from core_features.line_follow.manager import LineFollowManager
from core_features.line_follow.model import (LineFollowConfig, LineFollowDecision, LineFollowMode,
                                             LineObservation)

DT = .05
CAMERA = LineFollowMode.CAMERA_LINE


class Bus:
    def __init__(self): self.events = []
    def publish(self, event, **kwargs): self.events.append(event)


class Rig:
    """Straight lane along odom x, edges at y = +-0.1 m; the robot integrates its own twist."""

    def __init__(self, probe=lambda now, v, w: True, floor=None, uncertainty=.001, **config):
        base = dict(body_front_x_m=.08, body_rear_x_m=-.08, body_half_width_m=.06,
                    body_lidar_x_m=0., body_rotation_radius_m=.1, cruise_speed=.04,
                    max_linear=.04, recovery_local_enabled=True, bridge_enabled=True,
                    ir_guard_enabled=True)  # D-476 rev 1: the bridge needs the IR guard
        base.update(config)
        self.now, self.x, self.y, self.yaw, self.points = 1., 0., 0., 0., ()
        self.uncertainty = uncertainty
        self.bus = Bus()
        self.m = LineFollowManager(self.bus, clock=lambda: self.now,
                                   config=LineFollowConfig(**base))
        self.m.bind_recovery(calibration_active=lambda: False, linear_ceiling=lambda: .04)
        self.m.bind_return_motion(probe, floor_proof_live=floor)
        self.m.set_mode(CAMERA)

    def _pose(self, pose=True, frame='odom', scan=True):
        stamp = round(self.now*1e9)
        if pose:
            self.m.observe_return_pose(stamp_ns=stamp, source_now_ns=stamp, frame=frame,
                                       x=self.x, y=self.y, yaw=self.yaw, received_at=self.now)
        if scan:
            self.m.observe_scan_points(self.points, received_at=self.now)

    def step(self, seen=True, *, confidence=.9, quality=None, move=True, slip=None,
             dt=DT, pose=True, frame='odom', ir='none', error=0., scan=True):
        """seen: True lane, False invisible frame, None no camera frame at all.
        ir: None no IR sample, else the IR line error (or 'none' for an invisible IR line)."""
        self.now = round(self.now+dt, 6)
        self._pose(pose, frame, scan)
        if ir is not None:
            visible = ir != 'none'
            self.m.observe(LineObservation(
                LineFollowMode.IR_LINE, self.now, visible, ir if visible else None,
                .9 if visible else 0., ir_calibrated=True, calibration_revision='ir-rig'),
                received_at=self.now)
        if seen is None:
            obs = None
        elif seen:
            edges = [dict(side=side, slope=-math.tan(self.yaw),
                          intercept_m=(edge-self.y)/math.cos(self.yaw),
                          observed_x_min_m=0., observed_x_max_m=.4)
                     for side, edge in (('left', .1), ('right', -.1))]
            containment = LaneContainmentEvidence.model_validate(dict(
                stamp=self.now, geometry_id='rig-a', ground_source='CALIBRATED',
                uncertainty_m=self.uncertainty, boundaries=edges))
            obs = LineObservation(CAMERA, self.now, True, error, confidence,
                                  containment=containment)
        else:
            obs = LineObservation(CAMERA, self.now, False, None, 0., quality_reason=quality)
        if obs is not None:
            self.m.observe(obs, received_at=self.now, source_now=self.now)
        decision = self.m.tick(self.now)
        if move:
            travel = decision.linear*DT if slip is None else slip
            self.x += travel*math.cos(self.yaw)
            self.y += travel*math.sin(self.yaw)
            self.yaw += decision.angular*DT
        return decision

    def follow(self, frames=5, **kwargs):
        for _ in range(frames):
            decision = self.step(**kwargs)
        assert self.m.status().state == 'TRACKING' and decision.linear > 0
        if self.m.config.recovery_local_enabled:
            assert self.m._return_controller.checkpoint is not None

    @property
    def reason(self):
        return self.m.status().reason


def _trace(rig, ticks):
    out = []
    for _ in range(ticks):
        d = rig.step(seen=False)
        s = rig.m.status()
        out.append((round(d.linear, 9), round(d.angular, 9), s.state, s.reason))
    return out


def test_bridge_off_is_todays_behaviour_whatever_its_values():
    plain = Rig(bridge_enabled=False)
    tuned = Rig(bridge_enabled=False, bridge_lookahead_m=.2, bridge_coast_m=.05,
                bridge_slow_m=.4, bridge_slow_scale=.9, bridge_distance_scale=1.5,
                bridge_time_margin_s=1.)
    tuned.m.set_bridge_route_hint('straight')
    plain.follow()
    tuned.follow()
    a, b = _trace(plain, 70), _trace(tuned, 70)
    assert a == b
    # Today: the loss tick holds, nothing ever drives forward on an unseen lane.
    assert a[0][:2] == (0, 0) and a[0][2] == 'HOLD'
    assert all(linear <= 0 for linear, *_ in a)
    assert all(reason != 'lane_bridge' for *_, reason in a)


def test_default_config_keeps_the_bridge_off():
    assert LineFollowConfig().bridge_enabled is False


def test_loss_after_contained_following_bridges_slowly_along_the_known_lane():
    r = Rig()
    r.follow()
    d = r.step(seen=False)
    assert 0 < d.linear <= r.m.config.cruise_speed
    assert d.angular == pytest.approx(0, abs=1e-9)  # no hint: straight extension only
    assert r.m.status().state == 'RECOVERING' and r.reason == 'lane_bridge'
    # The D-422 judgement on the next tick sweeps the bridge arc, not the stale follow intent.
    assert r.m._intended == (d.linear, d.angular)
    assert r.m.apply_if_current(d, lambda decision: None)


def test_bridge_steers_back_to_the_lane_centre_line():
    r = Rig()
    r.y = .01  # contained, 1 cm left of the centre line
    r.follow()
    d = r.step(seen=False)
    assert r.reason == 'lane_bridge' and d.linear > 0 and d.angular < 0


@pytest.mark.parametrize('case', ['no_follow', 'low_confidence', 'low_light',
                                  'turn_hint', 'disabled'])
def test_bridge_entry_requires_confident_following(case):
    config = {}
    if case == 'disabled': config['bridge_enabled'] = False
    r = Rig(**config)
    if case == 'turn_hint': r.m.set_bridge_route_hint('left')
    if case != 'no_follow':
        for _ in range(5): r.step()
    if case == 'low_confidence':
        d = r.step(confidence=.1)
    elif case == 'low_light':
        d = r.step(seen=False, quality='low_light')
    else:
        d = r.step(seen=False)
    assert d.linear <= 0 and r.reason != 'lane_bridge'
    # Never entered later in the same loss either.
    for _ in range(5):
        assert r.step(seen=False).linear <= 0 and r.reason != 'lane_bridge'


def test_obstacle_on_the_bridge_path_holds_and_ends_the_bridge():
    r = Rig()
    r.follow()
    assert r.step(seen=False).linear > 0
    r.points = ((.10, 0.),)  # 2 cm in front of the body
    d = r.step(seen=False)
    assert d.linear == d.angular == 0 and r.reason == 'obstacle_ahead'
    r.points = ()
    for _ in range(10):
        r.step(seen=False)
        assert r.reason != 'lane_bridge'


def test_bridge_arc_itself_is_swept_for_the_body_gap():
    # Straight follow intent is clear; the curved bridge arc sweeps the right-side point.
    r = Rig(bridge_lookahead_m=.04)
    r.y = .01
    r.follow()
    r.points = ((.06, -.08),)
    d = r.step(seen=False)
    assert d.linear == d.angular == 0 and r.reason == 'lane_bridge_blocked'
    assert r.m.status().body_gap_m is not None


def test_distance_ladder_halves_then_stops_by_measured_travel():
    r = Rig()
    r.follow()
    speeds = []
    for _ in range(20):  # wheels report 2 cm per tick, more than commanded
        d = r.step(seen=False, slip=.02)
        if r.reason != 'lane_bridge':
            break
        speeds.append(d.linear)
    assert speeds[0] == pytest.approx(.04) and speeds[-1] == pytest.approx(.02)
    # 1.08 x travel reaches 0.25 m after 12 ticks of 2 cm (0.24 m -> 0.259 m).
    assert len(speeds) == 12
    assert r.reason.startswith('lane_return_')


def test_time_bound_ends_bridge_before_lost_and_never_moves_the_loss_clock():
    r = Rig()
    r.follow()
    r.step(seen=False, slip=0.)
    loss = r.m._loss_started_at
    assert loss == r.now and r.reason == 'lane_bridge'
    last = None
    while r.reason == 'lane_bridge':
        last = r.now
        assert r.m._loss_started_at == loss
        r.step(seen=False, slip=0.)  # wheels slip: no measured travel
    bound = r.m.config.lost_after_s-r.m.config.bridge_time_margin_s
    assert last - loss < bound <= r.now - loss
    assert r.m._loss_started_at == loss


def test_reacquired_lane_is_verified_by_d468_then_follows_and_rearms():
    r = Rig()
    r.follow()
    for _ in range(3):
        assert r.step(seen=False).linear > 0 and r.reason == 'lane_bridge'
    for _ in range(6):
        d = r.step()
        if r.m.status().state == 'TRACKING':
            break
    assert r.m.status().state == 'TRACKING' and d.linear > 0
    r.follow(30, slip=.01)  # 0.30 m of camera-confirmed travel >= bridge_slow_m
    assert r.step(seen=False).linear > 0 and r.reason == 'lane_bridge'


def test_exhausted_bridge_hands_over_to_d468_retrace_over_the_bridged_path():
    r = Rig()
    r.follow()
    # Bridge 0.24 m: farther than D-468's 0.15 m retrace reach from the loss pose, so the
    # retrace only works because its path now includes the bridged travel.
    while r.step(seen=False, slip=.02).linear > 0 and r.reason == 'lane_bridge':
        pass
    retrace = []
    for _ in range(10):
        d = r.step(seen=False)
        assert r.reason != 'lane_bridge'
        retrace.append((d.linear, r.reason))
    assert any(v < 0 and reason == 'lane_return_measured_path_return' for v, reason in retrace)


def test_lost_latches_on_the_same_clock_with_or_without_bridge_and_d468_continues():
    # D-476 open question: the bridge does not reset or extend _loss_started_at, so LOST
    # latches lost_after_s after the first loss tick either way. D-468 keeps acting under
    # the LOST latch (reselection_required is one of its local reasons).
    latched = {}
    for enabled in (False, True):
        r = Rig(bridge_enabled=enabled)
        r.follow()
        loss = r.now+DT
        while not r.m._lost_latched:
            r.step(seen=False)
            assert r.now - loss <= r.m.config.lost_after_s + DT
        latched[enabled] = round(r.now - loss, 6)
        assert 'nav.lane_lost' in r.bus.events
        r.step(seen=False)
        assert r.reason.startswith('lane_return_')
    assert latched[True] == latched[False]
    assert latched[True] > 3.0


def test_route_hint_values():
    r = Rig()
    for hint in (None, 'straight', 'left', 'right'):
        r.m.set_bridge_route_hint(hint)
    with pytest.raises(ValueError):
        r.m.set_bridge_route_hint('back')


@pytest.mark.parametrize('bad', [dict(bridge_enabled='true'), dict(bridge_lookahead_m=0.),
                                 dict(bridge_coast_m=.3), dict(bridge_slow_scale=0.),
                                 dict(bridge_distance_scale=.9), dict(bridge_time_margin_s=3.)])
def test_bridge_config_is_validated(bad):
    with pytest.raises(ValueError):
        LineFollowConfig(**bad)


def _unbound(r):
    r.m._return_motion = None


# (rig config, setup before the loss tick, loss-tick step kwargs, expected reason or None)
REFUSALS = {
    'ir_guard_not_clear': (dict(ir_guard_enabled=True), dict(ir='none'), dict(ir=-.5), None),
    # IR centre = lane_departure: D-468 owns that tick (it holds), the bridge never enters.
    'lane_departure': (dict(ir_guard_enabled=True), dict(ir='none'), dict(ir=0.),
                       'lane_return_containment_unconfirmed'),
    'stale_pose': ({}, {}, dict(pose=False, dt=.35), None),
    'frame_mismatch': ({}, {}, dict(frame='map'), None),
    'probe_false': (dict(probe=lambda now, v, w: False), {}, {}, 'lane_bridge_motion_unconfirmed'),
    'probe_unbound': ({}, {}, dict(setup=_unbound), 'lane_bridge_motion_unconfirmed'),
    'obstacle_on_loss_tick': ({}, {}, dict(points=((.10, 0.),)), 'obstacle_ahead'),
}


@pytest.mark.parametrize('case', sorted(REFUSALS))
def test_bridge_is_refused_without_its_evidence(case):
    config, follow, loss, expected = REFUSALS[case]
    r = Rig(**config)
    r.follow(**follow)
    loss = dict(loss)
    setup = loss.pop('setup', None)
    if setup: setup(r)
    r.points = loss.pop('points', r.points)
    d = r.step(seen=False, **{**follow, **loss})
    assert d.linear <= 0 and r.reason != 'lane_bridge'
    if expected: assert r.reason == expected


def test_epoch_change_mid_bridge_ends_it():
    r = Rig()
    r.follow()
    assert r.step(seen=False).linear > 0 and r.reason == 'lane_bridge'
    r.m.invalidate_return_pose()
    for _ in range(5):
        assert r.step(seen=False).linear <= 0 and r.reason != 'lane_bridge'


def test_observation_stale_also_enters_the_bridge():
    # A missing camera frame keeps the last one usable for stale_after_s, then bridges.
    r = Rig()
    r.follow()
    d = r.step(seen=None, dt=.35)
    assert r.reason == 'lane_bridge' and d.linear > 0


def test_no_observation_cannot_follow_a_contained_track():
    # no_observation exists only before the first frame of a mode; set_mode also drops the
    # D-468 controller, so the bridge never has an armed checkpoint to start from there.
    r = Rig()
    r.follow()
    r.m.set_mode(CAMERA)
    assert r.m._bridge is None and r.m._return_controller is None
    assert r.step(seen=None).linear <= 0 and r.reason == 'camera_no_observation'


def test_bridge_never_exceeds_the_live_linear_ceiling():
    r = Rig()
    r.follow()
    r.m.bind_recovery(linear_ceiling=lambda: .015)
    d = r.step(seen=False)
    assert r.reason == 'lane_bridge' and 0 < d.linear <= .015


def test_bridge_submission_is_rechecked_at_apply_time():
    r = Rig()
    r.follow()
    d = r.step(seen=False)
    assert r.reason == 'lane_bridge'
    r.m.bind_recovery(linear_ceiling=lambda: 0.)
    assert not r.m.apply_if_current(d, lambda decision: pytest.fail('revoked bridge applied'))


def _direct_step(r, state='armed'):
    """_bridge_step on a fresh loss tick, called straight (as if no earlier gate stopped it)."""
    armed = r.m._bridge  # (epoch, anchor pose, corridor) from the last confident tick
    assert armed is not None and not isinstance(armed, dict)
    r.m._status = r.m._status.model_copy(update={'state': 'HOLD',
                                                 'reason': 'camera_line_not_visible'})
    view = r.m.return_evidence(now=r.now)
    if state == 'armed':
        state = armed
    else:
        epoch, anchor, corridor = armed
        state = {'epoch': epoch, 'anchor': anchor, 'corridor': corridor, 'last': None, 'travel': 0.}
    return r.m._bridge_step(r.now, state, view, True, .04, LineFollowDecision(mode=CAMERA))


def test_direct_bridge_step_reaches_the_motion_when_nothing_blocks():
    r = Rig()
    r.follow()
    r.m._loss_started_at = r.now
    assert _direct_step(r).linear > 0


def test_open_stuck_never_bridges():
    r = Rig()
    r.follow()
    r.m._loss_started_at = r.now
    r.m._recovery._id = 'stuck-x'  # whatever opened it, an open stuck owns the robot
    assert _direct_step(r) is None


def test_backwards_clock_ends_the_bridge():
    r = Rig()
    r.follow()
    r.m._loss_started_at = r.now + 1.  # loss clock ahead of now: clock went backwards
    assert _direct_step(r, state='bridging') is None


def test_retrace_is_rebased_once_when_the_bridge_ends():
    r = Rig()
    r.follow()
    calls = []
    original = r.m._return_controller.rebase_retrace
    r.m._return_controller.rebase_retrace = lambda: (calls.append(r.now), original())
    assert r.step(seen=False, slip=.02).linear > 0 and r.reason == 'lane_bridge'
    calls.clear()  # the loss tick's own D-468 departure transition built the first path
    bridged = 0
    while r.step(seen=False, slip=.02).linear > 0 and r.reason == 'lane_bridge':
        bridged += 1
    assert bridged > 2 and len(calls) == 1
    for _ in range(5): r.step(seen=False)
    assert len(calls) == 1


def test_mode_change_clears_the_route_hint():
    r = Rig()
    r.m.set_bridge_route_hint('left')
    r.m.set_mode(CAMERA)
    assert r.m._bridge_hint is None


# ---- D-476 option A (2026-10-07): entry from the follower's own confident following ----------
# Narrow 260919 track: 23.45 mm play per side (STL nominal, unmeasured), real 320x240 projection
# uncertainty 26-134 mm (record/NOMINAL), so the D-468 corridor (cap 15 mm) is never certified. Device defaults: recovery_local_enabled false,
# control.sensor_adapter off, so the worker floor proof is not live and always says no.

def _narrow(**config):
    base = dict(probe=lambda now, v, w: False, floor=lambda: False, uncertainty=.05,
                recovery_local_enabled=False, site_floor_map_id='lab-a', obstacle_mode='path')
    base.update(config)
    return Rig(**base)


def test_narrow_track_bridges_from_confident_following_without_d468_or_floor_proof():
    r = _narrow()
    r.follow()
    view = r.m.return_evidence(now=r.now)
    assert view.corridor is None and view.reason == 'projection_uncertainty_excessive'
    assert r.m._return_controller is None
    d = r.step(seen=False)
    assert r.reason == 'lane_bridge' and r.m.status().state == 'RECOVERING'
    assert 0 < d.linear <= r.m.config.cruise_speed
    assert d.angular == pytest.approx(0, abs=1e-9)  # straight on the followed heading
    assert r.m.apply_if_current(d, lambda decision: None)


def test_uncertified_target_is_the_followed_odom_line_extended_straight():
    r = _narrow()
    r.yaw = .2  # following along a lane that runs at 0.2 rad in odom
    r.follow()
    r.step(seen=False)
    r.yaw -= .05  # odom shows the body turned off that line
    d = r.step(seen=False)
    assert r.reason == 'lane_bridge' and d.angular > 0  # steers back onto the followed line


def _weak_streak(r):
    for _ in range(5): r.step()
    r.step(confidence=.4)  # still FOLLOW (>= min_confidence) but below bridge_arm_confidence
    r.step(); r.step()     # only 2 confident frames since


NOT_ARMED = {
    'low_confidence': (dict(confidence=.4), {}),
    'too_few_frames': (dict(frames=2), {}),
    'streak_broken': ('weak', {}),
    'low_light': ({}, dict(quality='low_light')),
    'obstacle_ahead': ({}, dict(points=((.10, 0.),))),
    'ir_not_clear': (dict(ir='none'), dict(ir=-.5)),
    'open_stuck': ({}, dict(stuck=True)),
    'hint_left': ({}, dict(hint='left')),
    'hint_right': ({}, dict(hint='right')),
}


@pytest.mark.parametrize('case', sorted(NOT_ARMED))
def test_narrow_bridge_refused_without_confident_following_or_its_guards(case):
    follow, loss = NOT_ARMED[case]
    r = _narrow()
    if follow == 'weak':
        _weak_streak(r)
    else:
        follow = dict(follow)
        frames = follow.pop('frames', 5)
        for _ in range(frames): r.step(**follow)
        assert r.m.status().state == 'TRACKING'
    loss = dict(loss)
    r.points = loss.pop('points', r.points)
    if loss.pop('stuck', False): r.m._recovery._id = 'stuck-x'
    if 'hint' in loss: r.m.set_bridge_route_hint(loss.pop('hint'))
    ir = loss.pop('ir', None)
    for _ in range(4):
        d = r.step(seen=False, ir=ir, **loss)
        assert d.linear <= 0 and r.reason != 'lane_bridge'


def test_narrow_bridge_arc_blocked_by_body_sweep_holds():
    r = _narrow()
    r.follow()
    # The tick-level D-422 check judges an in-place turn (rotation gap 0.03 m: clear); the
    # straight bridge arc's swept body gap is 0.05 m, inside its resume gap at 0.04 m/s.
    r.m._intended = (0., .5)
    r.points = ((.13, 0.),)
    d = r.step(seen=False)
    assert d.linear == d.angular == 0 and r.reason == 'lane_bridge_blocked'
    assert r.m.status().state == 'HOLD' and r.m.status().body_gap_m == pytest.approx(.05)


def test_narrow_bridge_distance_cap_then_todays_hold_and_lost_on_the_same_clock():
    r = _narrow()
    r.follow()
    loss = r.now + DT
    speeds = []
    while True:
        d = r.step(seen=False, slip=.02)
        if r.reason != 'lane_bridge':
            break
        assert r.m._loss_started_at == loss
        speeds.append(d.linear)
    assert len(speeds) == 12 and speeds[-1] == pytest.approx(.02)
    # D-468 off: exhaustion falls through to today's path, HOLD then LOST at lost_after_s.
    assert d.linear == d.angular == 0 and r.reason == 'camera_line_not_visible'
    while not r.m._lost_latched:
        assert r.step(seen=False).linear <= 0 and r.reason != 'lane_bridge'
    assert r.now - loss == pytest.approx(r.m.config.lost_after_s + DT, abs=DT)
    assert r.m.status().state == 'LOST'


def test_narrow_bridge_time_cap():
    r = _narrow()
    r.follow()
    r.step(seen=False, slip=0.)
    loss = r.m._loss_started_at
    while r.reason == 'lane_bridge':
        last = r.now
        r.step(seen=False, slip=0.)
    bound = r.m.config.lost_after_s - r.m.config.bridge_time_margin_s
    assert last - loss < bound <= r.now - loss and r.m._loss_started_at == loss


def test_live_floor_proof_is_still_required_when_enforce_is_on():
    denied = _narrow(floor=lambda: True)  # enforce: the worker proof is live and says no
    denied.follow()
    assert denied.step(seen=False).linear <= 0
    assert denied.reason == 'lane_bridge_motion_unconfirmed'
    allowed = _narrow(floor=lambda: True, probe=lambda now, v, w: True)
    allowed.follow()
    assert allowed.step(seen=False).linear > 0 and allowed.reason == 'lane_bridge'


def test_unreadable_floor_liveness_requires_the_proof():
    r = _narrow(floor=lambda: 1/0)
    r.follow()
    assert r.step(seen=False).linear <= 0 and r.reason == 'lane_bridge_motion_unconfirmed'


def test_narrow_bridge_is_rechecked_at_apply_time_without_a_d468_controller():
    r = _narrow()
    r.follow()
    d = r.step(seen=False)
    assert r.reason == 'lane_bridge' and r.m._return_controller is None
    r.m.observe_scan_points(((.10, 0.),), received_at=r.now)  # object between tick and apply
    assert not r.m.apply_if_current(d, lambda decision: pytest.fail('blocked bridge applied'))
    r.m.observe_scan_points((), received_at=r.now)
    r.m.bind_recovery(linear_ceiling=lambda: 0.)
    assert not r.m.apply_if_current(d, lambda decision: pytest.fail('revoked bridge applied'))


def test_narrow_bridge_reacquires_then_needs_a_new_confident_streak():
    r = _narrow()
    r.follow()
    assert r.step(seen=False).linear > 0 and r.reason == 'lane_bridge'
    r.step(); r.step()  # two frames back on the lane: following, not yet re-armed
    assert r.m.status().state == 'TRACKING' and r.m._bridge is None
    assert r.step(seen=False).linear <= 0 and r.reason != 'lane_bridge'


@pytest.mark.parametrize('bad', [dict(bridge_arm_confidence=0.), dict(bridge_arm_confidence=1.1),
                                 dict(bridge_arm_frames=0), dict(bridge_arm_frames=2.),
                                 dict(bridge_enabled=True, ir_guard_enabled=True,
                                      bridge_arm_confidence=.3),
                                 dict(bridge_enabled=True),  # no IR guard: no lateral fence
                                 dict(bridge_arm_max_error=0.), dict(bridge_arm_max_angular=.8),
                                 dict(site_floor_map_id=True)])
def test_bridge_arming_config_is_validated(bad):
    with pytest.raises(ValueError):
        LineFollowConfig(**bad)


# ---- review fixes 2026-10-07 ----------------------------------------------------------------

def test_dropoff_acceptance_or_live_floor_proof_is_required():
    # Floor proof not live (adapter off) and no site acceptance: never bridges.
    r = _narrow(site_floor_map_id=None)
    r.follow()
    for _ in range(4):
        assert r.step(seen=False).linear <= 0 and r.reason != 'lane_bridge'
    # Live floor proof that admits the motion: the site flag is not needed.
    r = _narrow(site_floor_map_id=None, floor=lambda: True, probe=lambda now, v, w: True)
    r.follow()
    assert r.step(seen=False).linear > 0 and r.reason == 'lane_bridge'


@pytest.mark.parametrize('error', [.2, -.2, .3])
def test_curve_or_correction_does_not_arm(error):
    # A curving or yawed follow steers (|error| 0.2-0.3 -> |angular| 0.16-0.24): the body
    # heading is not the lane's, so its straight extension would leave a narrow lane.
    # Rev 2: at this rig's cruise 0.04 these are also tighter than bridge_arm_max_curvature;
    # rev 1's 0.15 (kappa 3.9, steady) now arms as an arc (test_steady_curvature_arc_*).
    r = _narrow()
    r.follow(error=error)
    assert abs(r.m.status().angular) > r.m.config.bridge_arm_max_angular
    assert r.m._bridge is None
    assert r.step(seen=False).linear <= 0 and r.reason != 'lane_bridge'


def test_straight_streak_after_a_correction_arms_again():
    r = _narrow()
    r.follow(error=.2)
    r.follow(2)
    assert r.m._bridge is None  # 2 straight frames since the correction
    r.follow(1)
    assert r.m._bridge is not None
    assert r.step(seen=False).linear > 0 and r.reason == 'lane_bridge'


def _bridge_then_reacquire(r):
    r.follow()
    assert r.step(seen=False).linear > 0 and r.reason == 'lane_bridge'
    r.step(seen=False)


def test_chained_loss_needs_camera_confirmed_travel_between_bridges():
    r = _narrow()
    _bridge_then_reacquire(r)
    r.follow(24, slip=.01)  # 0.24 m of confident tracking < bridge_slow_m 0.25
    assert r.m._bridge is None
    assert r.step(seen=False).linear <= 0 and r.reason != 'lane_bridge'
    r = _narrow()
    _bridge_then_reacquire(r)
    r.follow(26, slip=.01)
    assert r.step(seen=False).linear > 0 and r.reason == 'lane_bridge'


def test_travel_while_not_confidently_tracking_does_not_count():
    r = _narrow()
    _bridge_then_reacquire(r)
    for _ in range(40):  # 0.40 m driven while following below bridge_arm_confidence
        r.step(slip=.01, confidence=.4)
    r.follow(3, slip=0.)
    assert r.m._bridge is None


def _bridging():
    r = _narrow()
    r.follow()
    assert r.step(seen=False).linear > 0 and r.reason == 'lane_bridge'
    return r


def test_stuck_opening_mid_bridge_ends_it():
    r = _bridging()
    r.m._recovery._id = 'stuck-x'
    for _ in range(3):
        assert r.step(seen=False).linear <= 0 and r.reason != 'lane_bridge'


def test_mode_change_mid_bridge_ends_it_for_good():
    r = _bridging()
    r.m.set_mode(CAMERA)
    assert r.m._bridge is None
    for _ in range(4):
        assert r.step(seen=False).linear <= 0 and r.reason != 'lane_bridge'


def test_scan_going_stale_mid_bridge_ends_it():
    r = _bridging()
    d = r.step(seen=False, scan=False)  # 0.1 s old scan: still bridging on it
    assert r.reason == 'lane_bridge'
    for _ in range(12):  # past clearance_stale_s 0.5 s
        d = r.step(seen=False, scan=False)
    assert d.linear <= 0 and r.reason != 'lane_bridge'


def test_stale_scan_rejects_a_bridge_at_apply_time():
    r = _bridging()
    d = r.step(seen=False)
    r.m._clearance_at -= r.m.config.clearance_stale_s + .01
    assert not r.m.apply_if_current(d, lambda decision: pytest.fail('stale-scan bridge applied'))


@pytest.mark.parametrize('change', ['frame', 'epoch'])
def test_pose_frame_or_epoch_change_mid_bridge_ends_it(change):
    r = _bridging()
    if change == 'epoch':
        r.m.invalidate_return_pose()
    for _ in range(4):
        d = r.step(seen=False, frame='map' if change == 'frame' else 'odom')
        assert d.linear <= 0 and r.reason != 'lane_bridge'


def _off_scenario(ir_guard):
    """Fixed device-like OFF scenario (recovery_local_enabled and bridge_enabled false). Only
    API present on main 7c0879274 too; its trace there is test_lane_bridge_off_golden.json."""
    now, pose, out = [1.], [0., 0., 0.], []
    m = LineFollowManager(Bus(), clock=lambda: now[0], config=LineFollowConfig(
        body_front_x_m=.08, body_rear_x_m=-.08, body_half_width_m=.06, body_lidar_x_m=0.,
        body_rotation_radius_m=.1, cruise_speed=.04, max_linear=.04,
        recovery_local_enabled=False, bridge_enabled=False, ir_guard_enabled=ir_guard))
    m.bind_recovery(calibration_active=lambda: False, linear_ceiling=lambda: .04)
    m.bind_return_motion(lambda now, v, w: True)
    m.set_mode(CAMERA)

    def step(seen=True, error=0., confidence=.9, quality=None, points=(), frame=True):
        now[0] = round(now[0]+.05, 6)
        t, stamp = now[0], round(now[0]*1e9)
        m.observe_return_pose(stamp_ns=stamp, source_now_ns=stamp, frame='odom',
                              x=pose[0], y=pose[1], yaw=pose[2], received_at=t)
        m.observe_scan_points(points, received_at=t)
        m.observe(LineObservation(LineFollowMode.IR_LINE, t, False, None, 0., ir_calibrated=True,
                                  calibration_revision='ir-rig'), received_at=t)
        if frame:
            if seen:
                edges = [dict(side=s, slope=0., intercept_m=e-pose[1], observed_x_min_m=0.,
                              observed_x_max_m=.4) for s, e in (('left', .1), ('right', -.1))]
                c = LaneContainmentEvidence.model_validate(dict(
                    stamp=t, geometry_id='g', ground_source='CALIBRATED', uncertainty_m=.05,
                    boundaries=edges))
                obs = LineObservation(CAMERA, t, True, error, confidence, containment=c)
            else:
                obs = LineObservation(CAMERA, t, False, None, 0., quality_reason=quality)
            m.observe(obs, received_at=t, source_now=t)
        d = m.tick(t)
        s = m.status()
        pose[0] += d.linear*.05*math.cos(pose[2])
        pose[1] += d.linear*.05*math.sin(pose[2])
        pose[2] += d.angular*.05
        out.append([round(d.linear, 9), round(d.angular, 9), s.state, s.reason])

    for _ in range(6): step()
    for _ in range(10): step(seen=False)
    for _ in range(5): step(error=.2)
    for _ in range(3): step(points=((.10, 0.),))
    for _ in range(5): step()
    for _ in range(2): step(seen=False, quality='low_light')
    for _ in range(4): step(confidence=.4)
    for _ in range(4): step()
    for _ in range(10): step(frame=False)
    for _ in range(70): step(seen=False)
    return out


def test_off_decisions_match_main_tick_for_tick():
    import json
    from pathlib import Path
    golden = json.loads((Path(__file__).with_name('test_lane_bridge_off_golden.json'))
                        .read_text(encoding='utf-8'))
    for key, ir_guard in (('ir_off', False), ('ir_on', True)):
        assert _off_scenario(ir_guard) == golden[key]


# ---- D-476 rev 2: steady-curvature arcs ------------------------------------------------------
# Roundabout-like follow: cruise 0.08, error -0.184 -> angular +0.147 (gazebo rev 1 B runs),
# kappa = 0.147 / (0.08 x 0.88 x 0.846) ~ 2.47 1/m (radius ~0.40 m), below the 4.0 cap.
ROUND_E = -.184
# An arc arms only over bridge_arm_min_travel_m (0.08/0.8 = 0.1 m) of odom; here ~3 mm a tick.
ARC_FRAMES = 40


def _arc(**config):
    return _narrow(**{**dict(cruise_speed=.08, max_linear=.08), **config})


def _kappa(r):
    s = r.m.status()
    return s.angular/s.linear


def test_steady_curvature_arc_arms_and_bridges_along_the_arc():
    r = _arc()
    r.follow(ARC_FRAMES, error=ROUND_E)
    kappa = _kappa(r)
    assert 2. < kappa < r.m.config.bridge_arm_max_curvature
    assert r.m._bridge is not None and r.m._bridge_kappa == pytest.approx(kappa)
    d = r.step(seen=False)
    assert r.reason == 'lane_bridge' and d.linear > 0
    # Pure pursuit from on the lane circle commands that circle; D-422 sweeps this twist.
    assert d.angular/d.linear == pytest.approx(kappa, rel=.05)
    assert r.m._intended == (d.linear, d.angular)


@pytest.mark.parametrize('errors, confidences', [
    ((-.15, -.25)*3, (.9,)*6),            # error swings: a correction, not an arc
    ((ROUND_E,)*6, (.9, .75)*3),          # steady error, speed changes: kappa spread 0.9
    ((-.3,)*6, (.9,)*6),                  # steady but kappa 4.4 > bridge_arm_max_curvature
    ((-.64, -.7, -.8, -.89, -.89), (.9,)*5),  # gazebo corner entry (rev 1 Cb runs)
    ((-.7,)*6, (.9,)*6),                  # steady large correction: kappa far above the cap
])
def test_varying_or_too_tight_curvature_does_not_arm(errors, confidences):
    r = _arc()
    for e, conf in zip(errors, confidences):
        r.step(error=e, confidence=conf)
    assert r.m.status().state == 'TRACKING' and r.m._bridge is None
    assert r.step(seen=False).linear <= 0 and r.reason != 'lane_bridge'


def test_error_spread_tolerance_is_derived_from_the_follow_gains():
    c = LineFollowConfig()
    # The error spread that commands exactly the curvature tolerance at cruise speed.
    assert c.bridge_arm_error_spread == pytest.approx(
        c.bridge_arm_curvature_tolerance*c.cruise_speed/c.steering_gain)


def test_arc_sweep_is_the_arc_not_the_straight_extension():
    # Tick-level D-422 judges an in-place turn (clear); only the bridge twist is swept.
    on_arc = _arc()
    on_arc.follow(ARC_FRAMES, error=ROUND_E)
    on_arc.m._intended = (0., .5)
    on_arc.points = ((.12, .07),)   # inside the left-turning arc's band, outside the straight one
    d = on_arc.step(seen=False)
    assert d.linear == d.angular == 0 and on_arc.reason == 'lane_bridge_blocked'
    off_arc = _arc()
    off_arc.follow(ARC_FRAMES, error=ROUND_E)
    off_arc.m._intended = (0., .5)
    off_arc.points = ((.13, -.058),)  # the straight sweep holds here, the arc's does not
    d = off_arc.step(seen=False)
    assert off_arc.reason == 'lane_bridge' and d.linear > 0


def test_worst_lateral_error_within_curvature_tolerance_is_bounded():
    r = _arc()
    r.follow(ARC_FRAMES, error=ROUND_E)
    c, kappa = r.m.config, r.m._bridge_kappa
    _, anchor, _ = r.m._bridge
    path = []
    while True:
        r.step(seen=False)
        if r.reason != 'lane_bridge':
            break
        path.append((r.x, r.y))
    reach = c.bridge_slow_m/c.bridge_distance_scale
    bound = c.bridge_arm_curvature_tolerance*reach**2/2   # 0.5 x 0.2315^2 / 2 = 13.4 mm
    assert bound == pytest.approx(.0134, abs=2e-4)

    def off(k, x, y):  # distance from the circle of curvature k through the anchor, its heading
        rad = 1/k
        cx, cy = anchor.x - rad*math.sin(anchor.yaw), anchor.y + rad*math.cos(anchor.yaw)
        return abs(math.hypot(x-cx, y-cy) - abs(rad))
    assert len(path) > 5
    assert max(off(kappa, *p) for p in path) < .002          # the bridge drives its arc
    for true_k in (kappa-c.bridge_arm_curvature_tolerance, kappa+c.bridge_arm_curvature_tolerance):
        assert max(off(true_k, *p) for p in path) <= bound + .002


def test_pending_junction_refuses_a_curved_bridge_not_a_straight_one():
    for error, bridges in ((ROUND_E, False), (0., True)):
        r = _arc()
        r.follow(ARC_FRAMES, error=error)
        r.m.set_junction('stop', 'p1', 10., stop_after_m=2.)  # pending, not held yet
        d = r.step(seen=False)
        assert (r.reason == 'lane_bridge' and d.linear > 0) is bridges, error


@pytest.mark.parametrize('bad', [dict(bridge_arm_max_curvature=0.), dict(bridge_arm_max_curvature=11.),
                                 dict(bridge_arm_curvature_tolerance=0.),
                                 dict(bridge_arm_curvature_tolerance=5.)])
def test_arc_config_is_validated(bad):
    with pytest.raises(ValueError):
        LineFollowConfig(**bad)


def test_singular_lane_circle_refuses_the_arc_without_raising():
    # kappa x center = 1 puts the lane centre on the turning centre (division by zero before).
    r = _arc()
    r.follow(ARC_FRAMES, error=ROUND_E)
    epoch, anchor, _ = r.m._bridge
    r.m._bridge, r.m._bridge_kappa = (epoch, anchor, SimpleNamespace(center=.25, heading=0.)), 4.
    d = r.step(seen=False)
    assert r.reason != 'lane_bridge' and d.linear <= 0


def _compensated(r, slip=None):
    # Curvature held at 2.5 1/m by trading confidence (speed) against an error drifting
    # -0.16 -> -0.20 (< bridge_arm_error_spread): kappa = 0.8|e| / (0.08 x scale x (1-0.65|e|)).
    for i in range(ARC_FRAMES+5):
        e = -.16-.04*i/(ARC_FRAMES+4)
        scale = .8*-e/(2.5*.08*(1+.65*e))
        r.step(error=e, confidence=.35+.65*scale, slip=slip)


def test_compensated_linear_arms_only_when_odom_curvature_agrees():
    agree = _arc()
    _compensated(agree)
    assert agree.m._bridge is not None and agree.m._bridge_kappa == pytest.approx(2.5, abs=.05)
    slipping = _arc()
    _compensated(slipping, slip=.006)  # wheels report twice the travel: odom kappa ~1.2
    assert slipping.m.status().state == 'TRACKING' and slipping.m._bridge is None


def test_steady_arc_short_of_min_travel_does_not_arm():
    r = _arc()
    r.follow(10, error=ROUND_E)  # 10 frames x ~3 mm < bridge_arm_min_travel_m 0.1 m
    assert r.m._bridge is None
    assert r.step(seen=False).linear <= 0 and r.reason != 'lane_bridge'


def test_rev1_yawed_correction_015_arms_as_arc_only_over_min_travel_with_odom_agreeing():
    # Rev 1's "yawed correction" (error 0.15 at cruise 0.04: kappa 3.9 <= 4.0). Held steady while
    # the body turns over 0.05 m (0.04/0.8) it is an arc by the gate's evidence; a real correction
    # on a straight lane would change the error as the body turns and fail the spread.
    short = _narrow()
    short.follow(error=.15)
    assert short.m._bridge is None
    slipping = _narrow()
    slipping.follow(ARC_FRAMES, error=.15, slip=.003)
    assert slipping.m._bridge is None
    steady = _narrow()
    steady.follow(ARC_FRAMES, error=.15)
    assert steady.m._bridge is not None and steady.m._bridge_kappa < 0


def test_arc_window_counts_distinct_camera_frames_not_ticks():
    r = _arc(bridge_arm_frames=12)
    for i in range(48):  # a camera frame every 4th tick: travel accrues, frames do not
        r.step(seen=True if i % 4 == 0 else None, error=ROUND_E)
        if i == 43:  # 11 frames, ~0.13 m
            assert r.m._bridge is None
    assert r.m._bridge is not None


@pytest.mark.parametrize('age, bridges', [(DT, False), (1., True)])
def test_recent_junction_sighting_refuses_a_curved_bridge(age, bridges):
    r = _arc()
    r.follow(ARC_FRAMES, error=ROUND_E)
    r.m._junction_seen_at = r.now+DT-age  # seen `age` before the bridge tick
    d = r.step(seen=False)
    assert (r.reason == 'lane_bridge' and d.linear > 0) is bridges
