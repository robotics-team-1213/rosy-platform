"""D-491 decision 4: the junction instruction gate in the real line-follow manager (no ROS)."""
import pytest

from core_features.line_follow.manager import LineFollowManager
from core_features.line_follow.model import LineFollowConfig, LineFollowMode, LineObservation

CAMERA = LineFollowMode.CAMERA_LINE


class Bus:
    def publish(self, event, **kwargs): pass


class Rig:
    def __init__(self):
        self.now, self.x = 1., 0.
        self.m = LineFollowManager(Bus(), clock=lambda: self.now, config=LineFollowConfig())
        self.m.set_mode(CAMERA)

    def step(self, *, junction=False, pose=True, dx=0.):
        self.now = round(self.now + .05, 6)
        self.x += dx
        if pose:
            stamp = round(self.now * 1e9)
            self.m.observe_return_pose(stamp_ns=stamp, source_now_ns=stamp, frame='odom',
                                       x=self.x, y=0., yaw=0., received_at=self.now)
        self.m.observe(LineObservation(CAMERA, self.now, True, 0., .9), received_at=self.now)
        if junction:
            self.m.observe_junction('junction_fork', self.now)
        decision = self.m.tick(self.now)
        return decision, self.m.status()

    def send(self, action, expires_s=10., stop_after_m=None):
        return self.m.set_junction(action, 'J1', expires_s, stop_after_m)


def test_idle_tracks_and_reports_idle():
    rig = Rig()
    decision, status = rig.step()
    assert decision.linear > 0 and status.state == 'TRACKING'
    assert status.junction.model_dump() == dict(pending_action=None, place_id=None,
                                                state='idle', seq=0)


def test_no_instruction_at_a_junction_waits_and_latches():
    rig = Rig()
    decision, status = rig.step(junction=True)
    assert (decision.linear, decision.angular) == (0., 0.)
    assert (status.state, status.reason, status.junction.state) == ('HOLD', 'junction_waiting', 'waiting')
    rig.now += 1.  # the sighting goes stale: still latched
    decision, status = rig.step()
    assert decision.linear == 0. and status.junction.state == 'waiting'


def test_straight_arms_executes_and_clears_after_the_junction():
    rig = Rig()
    assert rig.send('straight') == (1, 'armed')
    assert rig.m._bridge_hint == 'straight'
    decision, status = rig.step()
    assert decision.linear > 0 and status.junction.state == 'armed'
    assert status.junction.pending_action == 'straight' and status.junction.place_id == 'J1'
    decision, status = rig.step(junction=True)
    assert decision.linear > 0 and status.junction.state == 'executing'
    rig.now += 1.
    decision, status = rig.step()
    assert decision.linear > 0 and status.junction.state == 'idle' and status.junction.seq == 1
    assert rig.m._bridge_hint is None


def test_expired_instruction_at_a_junction_waits():
    rig = Rig()
    rig.send('straight', expires_s=.5)
    rig.now += 1.
    decision, status = rig.step(junction=True)
    assert decision.linear == 0. and status.reason == 'junction_waiting'
    assert status.junction.pending_action is None and rig.m._bridge_hint is None


def test_expired_instruction_without_a_junction_is_dropped():
    rig = Rig()
    rig.send('straight', expires_s=.5)
    rig.now += 1.
    decision, status = rig.step()
    assert decision.linear > 0 and status.junction.state == 'idle'


@pytest.mark.parametrize('action', ['left', 'right'])
def test_left_and_right_are_unresolved_and_hold_at_once(action):
    rig = Rig()
    assert rig.send(action) == (1, 'unresolved')
    decision, status = rig.step()
    assert (decision.linear, decision.angular) == (0., 0.)
    assert (status.state, status.reason, status.junction.state) == ('HOLD', 'junction_unresolved', 'unresolved')
    assert rig.m._bridge_hint == action


def test_stop_zero_holds_at_once_until_the_next_instruction():
    rig = Rig()
    assert rig.send('stop') == (1, 'executing')
    decision, status = rig.step()
    assert decision.linear == 0. and status.reason == 'junction_stop'
    rig.send('straight')
    decision, status = rig.step()
    assert decision.linear > 0 and status.junction.seq == 2


def test_stop_after_m_drives_the_measured_distance_then_holds():
    rig = Rig()
    rig.step()
    rig.send('stop', stop_after_m=.09)
    moving = [rig.step(dx=.02)[0].linear > 0 for _ in range(6)]
    assert moving == [True] * 5 + [False]  # 0, .02, .04, .06, .08 then .10 >= .09
    rig.step(dx=0.)
    assert rig.m.status().reason == 'junction_stop'


def test_stop_after_m_holds_when_odom_jumps():
    rig = Rig()
    rig.step()
    rig.send('stop', stop_after_m=.5)
    assert rig.step(dx=.01)[0].linear > 0
    decision, status = rig.step(dx=.2)  # PoseTrail drops the jump: distance unknown
    assert decision.linear == 0. and status.reason == 'junction_stop'


def test_stop_after_m_without_fresh_odom_holds_at_once():
    rig = Rig()
    rig.send('stop', stop_after_m=.5)
    decision, status = rig.step(pose=False)
    assert decision.linear == 0. and status.reason == 'junction_stop'


def test_refused_unless_camera_or_ir_line_and_cleared_by_mode_change():
    rig = Rig()
    rig.send('left')
    rig.m.set_mode(LineFollowMode.OFF)
    assert rig.m.status().junction.state == 'idle'
    assert rig.send('straight') is None


@pytest.mark.parametrize('args', [('north', 5., None), ('stop', 31., None), ('stop', 0., None),
                                  ('straight', 5., .2), ('stop', 5., 2.5)])
def test_invalid_instructions_raise(args):
    with pytest.raises(ValueError):
        Rig().m.set_junction(args[0], 'J1', args[1], args[2])


def test_only_junction_reasons_count_as_a_sighting():
    rig = Rig()
    rig.m.observe_junction('no_boundary', rig.now + .05)
    decision, status = rig.step()
    assert decision.linear > 0 and status.junction.state == 'idle'
