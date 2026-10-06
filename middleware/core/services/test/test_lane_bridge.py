"""D-476 expected-road bridge on lane loss; real manager, no ROS or physical motion."""
import math

import pytest

from core_common.protocol.lane_containment import LaneContainmentEvidence
from core_features.line_follow.manager import LineFollowManager
from core_features.line_follow.model import LineFollowConfig, LineFollowMode, LineObservation

DT = .05
CAMERA = LineFollowMode.CAMERA_LINE


class Bus:
    def __init__(self): self.events = []
    def publish(self, event, **kwargs): self.events.append(event)


class Rig:
    """Straight lane along odom x, edges at y = +-0.1 m; the robot integrates its own twist."""

    def __init__(self, probe=lambda now, v, w: True, **config):
        base = dict(body_front_x_m=.08, body_rear_x_m=-.08, body_half_width_m=.06,
                    body_lidar_x_m=0., body_rotation_radius_m=.1, cruise_speed=.04,
                    max_linear=.04, recovery_local_enabled=True, bridge_enabled=True)
        base.update(config)
        self.now, self.x, self.y, self.yaw, self.points = 1., 0., 0., 0., ()
        self.bus = Bus()
        self.m = LineFollowManager(self.bus, clock=lambda: self.now,
                                   config=LineFollowConfig(**base))
        self.m.bind_recovery(calibration_active=lambda: False, linear_ceiling=lambda: .04)
        self.m.bind_return_motion(probe)
        self.m.set_mode(CAMERA)

    def _pose(self):
        stamp = round(self.now*1e9)
        self.m.observe_return_pose(stamp_ns=stamp, source_now_ns=stamp, frame='odom',
                                   x=self.x, y=self.y, yaw=self.yaw, received_at=self.now)
        self.m.observe_scan_points(self.points, received_at=self.now)

    def step(self, seen=True, *, confidence=.9, quality=None, move=True, slip=None):
        self.now = round(self.now+DT, 6)
        self._pose()
        if seen:
            edges = [dict(side=side, slope=-math.tan(self.yaw),
                          intercept_m=(edge-self.y)/math.cos(self.yaw),
                          observed_x_min_m=0., observed_x_max_m=.4)
                     for side, edge in (('left', .1), ('right', -.1))]
            containment = LaneContainmentEvidence.model_validate(dict(
                stamp=self.now, geometry_id='rig-a', ground_source='CALIBRATED',
                uncertainty_m=.001, boundaries=edges))
            obs = LineObservation(CAMERA, self.now, True, 0., confidence, containment=containment)
        else:
            obs = LineObservation(CAMERA, self.now, False, None, 0., quality_reason=quality)
        self.m.observe(obs, received_at=self.now, source_now=self.now)
        decision = self.m.tick(self.now)
        if move:
            travel = decision.linear*DT if slip is None else slip
            self.x += travel*math.cos(self.yaw)
            self.y += travel*math.sin(self.yaw)
            self.yaw += decision.angular*DT
        return decision

    def follow(self, frames=5):
        for _ in range(frames):
            decision = self.step()
        assert self.m.status().state == 'TRACKING' and decision.linear > 0
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


@pytest.mark.parametrize('case', ['no_follow', 'no_d468', 'low_confidence', 'low_light',
                                  'turn_hint', 'disabled'])
def test_bridge_entry_requires_confident_contained_following(case):
    config = {}
    if case == 'no_d468': config['recovery_local_enabled'] = False
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
    r.follow(3)
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
