"""D-507 6: motion_admitted, one admission with two bases (enforce, site) and the site-basis
reverse for the D-468 retrace only. Real manager, no ROS, no physical motion."""
import pytest

from core_features.line_follow.manager import LineFollowManager
from core_features.line_follow.model import LineFollowConfig, LineFollowMode, LineObservation
from test_lane_bridge import Rig as BridgeRig

BODY = dict(body_front_x_m=.08, body_rear_x_m=-.08, body_half_width_m=.06, body_lidar_x_m=0.,
            body_rotation_radius_m=.1)
SITE = dict(BODY, ir_guard_enabled=True, obstacle_mode='path', site_floor_map_id='lab-a')
CLEAR = [(1.5, 1.5)]
KINDS = ('bridge', 'approach', 'turn', 'advance', 'return', 'retrace')
# D-507 6 (b): IR verdicts each kind may move on. Written out here, not imported.
ALLOWED = {'bridge': {'clear'},
           'approach': {'clear', 'left', 'right'},
           'turn': {'clear', 'left', 'right'},
           'advance': {'clear', 'left', 'right'},
           'return': {'clear', 'left', 'right', 'centre'},
           'retrace': {'clear', 'left', 'right', 'centre'}}
IR_ERROR = {'clear': None, 'left': -.9, 'right': .9, 'centre': 0.}


class Bus:
    def publish(self, event, **kwargs): pass


class Site:
    def __init__(self, ir='clear', points=CLEAR, enforce=None, **config):
        self.now = 1.
        self.m = LineFollowManager(Bus(), clock=lambda: self.now,
                                   config=LineFollowConfig(**{**SITE, **config}))
        self.m.bind_recovery(calibration_active=lambda: False, linear_ceiling=lambda: .1)
        if enforce is not None:
            self.m.bind_return_motion(enforce, floor_proof_live=lambda: True,
                                      proof_configured=lambda: True)
        self.m.set_mode(LineFollowMode.CAMERA_LINE)
        self.feed(ir, points)

    def feed(self, ir='clear', points=CLEAR):
        """ir: an IR guard verdict, or 'stale' for no sample; points None: no new scan."""
        if ir != 'stale':
            error = IR_ERROR[ir]
            self.m.observe(LineObservation(LineFollowMode.IR_LINE, self.now, error is not None,
                                           error, .9 if error is not None else 0.,
                                           ir_calibrated=True, calibration_revision='r'),
                           received_at=self.now)
        if points is not None:
            self.m.observe_scan_points(points, received_at=self.now)

    def admit(self, linear, angular, kind, **kwargs):
        return self.m.motion_admitted(self.now, linear, angular, kind, **kwargs)


@pytest.mark.parametrize('kind', KINDS)
@pytest.mark.parametrize('ir', ['clear', 'left', 'right', 'centre', 'stale'])
def test_site_basis_ir_verdict_matrix(kind, ir):
    site = Site(ir=ir)
    assert site.m._ir_guard(site.now) == ir
    expected = ir in ALLOWED[kind]
    assert site.admit(.02, 0., kind) is expected
    assert site.admit(0., .3, kind) is expected
    assert site.admit(0., 0., kind) is expected  # the standing part alone (D-468 floor probe)


@pytest.mark.parametrize('kind', KINDS)
def test_no_declaration_is_no_site_basis(kind):
    assert Site(site_floor_map_id=None).admit(.02, 0., kind) is False


@pytest.mark.parametrize('map_id, ok', [(None, True), ('lab-a', True), ('lab-b', False),
                                        ('site', False)])
def test_instruction_map_id_must_match_the_declaration(map_id, ok):
    assert Site().admit(.02, 0., 'approach', map_id=map_id) is ok


@pytest.mark.parametrize('missing', ['ir_guard', 'path'])
def test_runtime_prerequisites_are_rechecked(missing):
    site = Site()
    config = site.m._config  # what a validated config cannot hold, the admission still checks
    object.__setattr__(config, 'ir_guard_enabled' if missing == 'ir_guard' else 'obstacle_mode',
                       False if missing == 'ir_guard' else 'sector')
    assert site.admit(.02, 0., 'return') is False


def test_twist_sweep_below_the_restart_gap_is_refused():
    site = Site(points=[(.13, 0.)])          # 0.05 m ahead of the body front
    assert site.admit(.02, 0., 'approach') is False
    assert site.admit(0., .3, 'turn') is True   # the rotation circle (0.1 m) does not reach it
    site.feed(points=[(.30, 0.)])
    assert site.admit(.02, 0., 'approach') is True


def test_sweep_judges_the_given_twist_not_the_follow_intent():
    site = Site(points=[(.11, .08)])         # front left, off the straight body path
    site.m._intended = (.04, 0.)
    assert site.admit(.02, 0., 'approach') is True
    assert site.admit(0., .5, 'turn') is True     # outside the rotation circle
    assert site.admit(.02, .5, 'turn') is False   # a left arc sweeps the right corner into it
    assert site.m._intended == (.04, 0.)          # the follow intent is left as it was


def test_stale_scan_is_refused():
    site = Site()
    site.now += .6                            # beyond clearance_stale_s (0.5); IR refreshed
    site.feed(points=None)
    assert site.admit(.02, 0., 'return') is False
    assert site.admit(-.02, 0., 'retrace') is False
    site.feed()
    assert site.admit(.02, 0., 'return') is True


@pytest.mark.parametrize('kind', KINDS)
def test_reverse_is_admitted_on_the_site_basis_only_for_the_retrace(kind):
    site = Site(ir='centre' if kind in ('return', 'retrace') else 'clear')
    assert site.admit(-.03, 0., kind) is (kind == 'retrace')
    assert site.admit(-.03, .2, kind) is (kind == 'retrace')


@pytest.mark.parametrize('points, ok', [([(-.12, 0.)], False),   # 0.04 m behind the body rear
                                        ([(-.11, .05)], False),
                                        ([(-.40, 0.)], True),
                                        ([(.10, 0.)], True)])    # ahead: not on a reverse path
def test_reverse_needs_the_rear_sweep_above_the_restart_gap(points, ok):
    assert Site(points=points).admit(-.03, 0., 'retrace') is ok


def test_reverse_refused_on_a_remembered_point_behind():
    site = Site(points=[(.0, .0)])
    site.m._near_memory = ((-.11, 0., 0.),)  # under range_min, remembered in odom
    assert site.admit(-.03, 0., 'retrace') is False


def test_enforce_basis_is_the_unchanged_probe():
    calls = []

    def probe(now, v, w):
        calls.append((v, w))
        return allow[0]

    allow = [True]
    site = Site(ir='stale', site_floor_map_id=None, enforce=probe)  # no site evidence at all
    assert site.admit(-.03, 0., 'bridge') is True   # enforce: no site reverse rule either
    allow[0] = False
    site.feed()                                  # site evidence now complete: enforce still wins
    assert site.admit(.02, 0., 'return') is False
    assert calls == [(-.03, 0.), (.02, 0.)]


def test_unknown_kind_is_a_programming_error():
    with pytest.raises(ValueError):
        Site().admit(.02, 0., 'stuck')


def test_junction_turn_capability_follows_the_shared_site_basis():
    site = Site()
    site.m.observe_junction('no_boundary', site.now, corner_turning=True)
    assert site.m.supports_junction_turn is True
    site.feed(ir='centre')
    assert site.m.supports_junction_turn is False


# ---- D-468 retrace on the site basis (bridge rig: straight lane, the robot integrates) ------

def _retrace(**config):
    r = BridgeRig(probe=lambda now, v, w: False, floor=lambda: False, **config)
    r.follow()
    while r.step(seen=False, slip=.02).linear > 0 and r.reason == 'lane_bridge':
        pass
    checkpoint = r.m._return_controller.checkpoint[0].received_at
    out = []
    for _ in range(10):
        d = r.step(seen=False)
        out.append((d.linear, d.angular, r.reason, r.now-checkpoint))
    return out


def test_site_basis_retraces_backwards_within_the_d468_limits():
    out = _retrace(site_floor_map_id='lab-a', obstacle_mode='path')
    back = [o for o in out if o[0] < 0]
    assert back and all(reason == 'lane_return_measured_path_return' for *_, reason, _ in back)
    assert all(-.03 - 1e-9 <= v for v, *_ in back)          # D-468: at most 0.03 m/s
    assert all(age <= 5. for *_, age in back)                 # within 5 s of the checkpoint


def test_without_a_basis_the_retrace_does_not_move():
    out = _retrace(site_floor_map_id=None, bridge_enabled=False)
    assert all(v == 0. and w == 0. for v, w, *_ in out)
