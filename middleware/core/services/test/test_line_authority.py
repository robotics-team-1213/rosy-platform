"""D-517 4 (M2): the Fleet movement authority gate in the real line-follow manager (no ROS)."""
import pytest

from core_features.line_follow.authority import AuthorityRefused
from core_features.line_follow.manager import LineFollowManager
from core_features.line_follow.model import LineFollowConfig, LineFollowMode, LineObservation

CAMERA = LineFollowMode.CAMERA_LINE
WALL = 1_800_000_000.0  # CORE wall clock = line clock + WALL in this rig


class Bus:
    def publish(self, event, **kwargs):
        pass


class Rig:
    def __init__(self, **config):
        self.now, self.x = 1., 0.
        self.m = LineFollowManager(Bus(), clock=lambda: self.now, config=LineFollowConfig(**config))
        self.m._wall = lambda: WALL + self.now
        self.m.set_mode(CAMERA)
        self.stop = self.m.config.derived_stop_gap_m(self.m.config.max_linear)
        self.resume = self.stop + self.m.config.obstacle_resume_hysteresis_m

    def step(self, dx=0., pose=True):
        self.now = round(self.now + .05, 6)
        self.x += dx
        if pose:
            stamp = round(self.now * 1e9)
            self.m.observe_return_pose(stamp_ns=stamp, source_now_ns=stamp, frame='odom',
                                       x=self.x, y=0., yaw=0., received_at=self.now)
        self.m.observe(LineObservation(CAMERA, self.now, True, 0., .9), received_at=self.now)
        return self.m.tick(self.now)

    def send(self, until_m, leg='L1', ttl_s=2., stamp=None):
        return self.m.set_authority('A1', leg, WALL + self.now if stamp is None else stamp, until_m, ttl_s)

    def authority(self):
        return self.m.authority_status()


def test_inactive_authority_leaves_line_following_unchanged():
    rig = Rig()
    for _ in range(5):
        decision = rig.step(dx=.004)
    assert decision.linear > 0 and rig.m.status().state == 'TRACKING'
    assert rig.authority() is None  # GET /line-follow keeps its old shape
    assert rig.m._authority_gate(rig.now, decision) is decision


def test_required_without_authority_stands():
    rig = Rig(authority_required=True)
    decision = rig.step()
    assert (decision.linear, decision.angular) == (0., 0.)
    assert (rig.m.status().state, rig.m.status().reason) == ('HOLD', 'authority_none')
    assert rig.authority()['state'] == 'NONE'


def test_remaining_is_anchored_at_the_pose_stamp_odom():
    rig = Rig()
    for _ in range(3):
        rig.step()
    stamp = WALL + rig.now  # Fleet's pose was taken here; its authority arrives 3 steps later
    for _ in range(3):
        rig.step(dx=.01)
    result = rig.send(.5, stamp=stamp)
    assert result['accepted'] is True
    assert rig.authority()['remaining_m'] == pytest.approx(.47, abs=1e-6)
    assert rig.authority()['state'] == 'FREE'


def test_stops_at_remaining_minus_the_body_stop_gap_and_resumes_past_the_hysteresis():
    rig = Rig()
    rig.step()
    rig.send(rig.stop + .045)
    travelled = 0.
    for _ in range(20):
        if rig.step(dx=.01).linear == 0.:
            break
        travelled += .01
        rig.send(rig.stop + .045 - travelled)  # the same end, refreshed by Fleet from the new pose
    assert travelled == pytest.approx(.04, abs=1e-6)  # stood once remaining <= d_stop(v)
    assert rig.authority()['state'] == 'HOLDING' and rig.m.status().reason == 'authority_end'
    assert rig.authority()['remaining_m'] <= rig.stop
    rig.send(rig.resume - .001)  # a new end still inside the resume gap: keeps standing
    assert rig.step().linear == 0.
    rig.send(rig.resume + .01)
    assert rig.step().linear > 0. and rig.authority()['state'] == 'FREE'


def test_authority_never_shrinks_on_the_same_leg():
    rig = Rig()
    rig.step()
    rig.send(1.)
    ignored = rig.send(.5)
    assert ignored['accepted'] is False and ignored['reason'] == 'shrink'
    assert rig.authority()['remaining_m'] == pytest.approx(1.)
    assert rig.send(.99)['accepted'] is True  # inside the noise band: the held end stays
    assert rig.authority()['remaining_m'] == pytest.approx(1.)
    assert rig.send(.5, leg='L2')['accepted'] is True  # another leg replaces it
    assert rig.authority()['remaining_m'] == pytest.approx(.5)


def test_an_ignored_shrink_does_not_refresh_the_ttl():
    rig = Rig()
    rig.step()
    rig.send(1., ttl_s=.52)
    for _ in range(10):  # 0.5 s of shrinking sends, each ignored
        assert rig.send(.3)['accepted'] is False
        assert rig.step().linear > 0.
    decision = rig.step()
    assert decision.linear == 0. and rig.authority()['state'] == 'EXPIRED'
    assert rig.send(.3)['accepted'] is True  # after expiry a smaller end is a new authority


def test_ttl_expiry_on_cores_clock_stands_the_robot():
    rig = Rig()
    rig.step()
    rig.send(1., ttl_s=.52)
    for _ in range(10):  # 0.5 s: still inside the ttl
        assert rig.step().linear > 0.
    decision = rig.step()
    assert (decision.linear, decision.angular) == (0., 0.)
    assert rig.authority()['state'] == 'EXPIRED' and rig.m.status().reason == 'authority_expired'
    rig.send(1.)
    assert rig.step().linear > 0.


@pytest.mark.parametrize('stamp_offset, code', [(-6., 'AUTHORITY_POSE_STALE'), (.5, 'AUTHORITY_POSE_FUTURE')])
def test_a_pose_stamp_outside_the_odom_history_is_refused_and_the_robot_stands(stamp_offset, code):
    rig = Rig()
    for _ in range(3):
        rig.step()
    rig.send(1.)
    with pytest.raises(AuthorityRefused) as err:
        rig.send(2., stamp=WALL + rig.now + stamp_offset)
    assert err.value.code == code
    assert rig.authority()['state'] == 'NONE' and rig.step().linear == 0.


def test_without_fresh_odom_nothing_is_accepted_or_driven():
    rig = Rig()
    rig.step(pose=False)
    with pytest.raises(AuthorityRefused) as err:
        rig.send(1.)
    assert err.value.code == 'AUTHORITY_ODOM_STALE'
    rig.step()
    rig.send(1.)
    for _ in range(7):  # odom stops: travel cannot be measured
        decision = rig.step(pose=False)
    assert decision.linear == 0. and rig.authority()['reason'] == 'authority_odom_stale'


def test_an_odom_jump_drops_the_measurement():
    rig = Rig()
    rig.step()
    rig.send(1.)
    rig.step(dx=.5)  # a reset or jump starts a new odom run
    assert rig.step().linear == 0. and rig.authority()['state'] == 'HOLDING'


def test_body_stop_and_estop_come_before_the_authority():
    rig = Rig()
    rig.step()
    rig.send(1.)
    rig.m.observe_clearance(.01, received_at=rig.now + .05)  # something right ahead
    decision = rig.step()
    assert decision.linear == 0. and rig.m.status().reason == 'obstacle_ahead'
    assert rig.authority()['state'] == 'FREE'
    rig.m.stop('estop')
    with pytest.raises(AuthorityRefused) as err:
        rig.send(1.)
    assert err.value.code == 'LINE_FOLLOW_NOT_ACTIVE'
    assert rig.step().linear == 0.


def test_config_flag_is_a_boolean():
    with pytest.raises(ValueError, match='^authority_required must be a boolean$'):
        LineFollowConfig(authority_required='yes')
    with pytest.raises(ValueError, match='^ir_guard_enabled must be a boolean$'):  # unchanged by D-517
        LineFollowConfig(ir_guard_enabled='yes')


def test_the_stop_gap_is_from_max_linear_not_cruise():
    # Line follow may command up to max_linear (D-468 return included), not only cruise.
    rig = Rig(cruise_speed=.04, max_linear=.10)
    rig.step()
    rig.send(rig.m.config.derived_stop_gap_m(.10) - .001)
    assert rig.step().linear == 0. and rig.authority()['state'] == 'HOLDING'
    assert rig.m.config.derived_stop_gap_m(.04) < rig.m.config.derived_stop_gap_m(.10) - .001
