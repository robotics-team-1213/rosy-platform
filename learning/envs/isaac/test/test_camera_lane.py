"""D-650: existing perception/CORE gates, not an alternate motion owner."""
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import sys

import numpy as np
import pytest


@pytest.mark.parametrize("name", ["camera_tick", "camera_episode_usable", "camera_admission_error", "camera_sample_due",
                                  "learn_transition", "remember_camera_action", "camera_snapshot_due"])
def test_native_runner_preserves_camera_guard_exports(name):
    import camera_checks
    import run_map_rl
    assert getattr(run_map_rl, name) is getattr(camera_checks, name)

ROOT = Path(__file__).resolve().parents[4]
for part in ('tools/sim/isaac', 'contracts/foundation', 'contracts/motion/src',
             'contracts/skill/src', 'middleware/core/services', 'middleware/core/events',
             'middleware/core/gateway', 'middleware/perception'):
    sys.path.insert(0, str(ROOT / part))


def perception_id():
    return {'schema': 'isaac-camera-error-confidence/2',
            'model_revision': 'lane-seg-test', 'model_sha256': 'a' * 64}


def test_physics_tick_camera_policy_cannot_restore_as_observation_policy():
    from camera_lane import CameraQPolicy
    current = perception_id()
    old = CameraQPolicy(17, perception=current).export()
    old['perception']['schema'] = 'isaac-camera-error-confidence/1'
    with pytest.raises(ValueError, match='identity differs'):
        CameraQPolicy.restore(old, perception=current)
    with pytest.raises(ValueError, match='identity required'):
        CameraQPolicy(17, perception=old['perception'])


@pytest.mark.parametrize('mode', ['applied', 'zero', 'clipped', 'selection_failed', 'invalid', 'halted'])
def test_terminal_credit_requires_successful_matching_core_dispatch(mode):
    from camera_checks import remember_camera_action
    from core.bridge.cmd_vel import cmd_vel_cycle
    from core_features.command.manager import Twist
    receipts, warnings = [], []
    def select():
        if mode == 'selection_failed':
            raise RuntimeError('injected selection failure')
        return Twist(0., 0.) if mode == 'zero' else Twist(.02, .1 if mode == 'clipped' else .2)
    command = SimpleNamespace(select_output=select, announce_pending=lambda: None)
    power = SimpleNamespace(on_activity=lambda source: None)
    cmd_vel_cycle(command, power, lambda twist: receipts.append((twist.linear, twist.angular)), warn=warnings.append)
    state = None if mode == 'invalid' else (2, 1)
    record = remember_camera_action(None, state, 3, 42, (.02, .2), receipts, warnings, mode == 'halted')
    if mode == 'applied':
        assert record == dict(state=(2, 1), action=3, frame=42, twist=(.02, .2))
    else:
        assert record is None


def test_core_selection_failure_zero_breaks_existing_camera_interval():
    from camera_checks import CameraLearningWindow, remember_camera_action
    from camera_lane import CameraQPolicy
    from core.bridge.cmd_vel import cmd_vel_cycle
    policy = CameraQPolicy(17, perception=perception_id())
    window = CameraLearningWindow()
    state = (2, 1)
    action = window.choose(policy, state, 1., frame=42, train=True)
    result = dict(reward=.1, terminated=False, truncated=False, reason='running')
    window.learn(policy, state, result, credit=None)
    prior = remember_camera_action(None, state, action, 42, (.02, .2), [(.02, .2)], [], False)
    receipts, warnings = [], []
    def failed_select():
        raise RuntimeError('injected failure after valid dispatch')
    command = SimpleNamespace(select_output=failed_select, announce_pending=lambda: None)
    cmd_vel_cycle(command, SimpleNamespace(on_activity=lambda source: None),
                  lambda twist: receipts.append((twist.linear, twist.angular)), warn=warnings.append)
    assert receipts == [(0., 0.)] and warnings
    credit = remember_camera_action(prior, state, action, 43, (.02, .2), receipts, warnings, False)
    assert credit is None
    window.choose(policy, state, 1.1, frame=66, train=True)
    window.learn(policy, state, result, credit=credit)
    assert policy.updates == 0


def test_camera_terminal_credit_survives_invalid_gap_but_not_episode_reset():
    from camera_checks import remember_camera_action
    from camera_lane import CameraQPolicy
    from run_map_rl import learn_transition
    policy = CameraQPolicy(seed=17, perception=perception_id())
    record = remember_camera_action(None, (2, 1), 3, 42, (.02, .2), [(.02, .2)], [], False)
    for frame in (43, 44):
        record = remember_camera_action(record, None, 1, frame, (0., 0.), [(0., 0.)], [], False)
    assert record['frame'] == 42
    terminal = dict(reward=-10., terminated=True, truncated=False, reason='camera_lane_lost',
                    camera_failure_reason='camera_target_unavailable')
    assert learn_transition(policy, (record['state'], record['action']), None, terminal) == 'terminal_camera_loss'
    assert policy.updates == 1 and policy.table[(2, 1)][3] == -1.5
    record = None  # The runner resets its ledger at each episode boundary.
    assert learn_transition(policy, record, None, terminal) == 'invalid_camera_observation'
    assert policy.updates == 1


@pytest.mark.parametrize('state,candidate,receipts,warnings,halted', [
    (None, (.02, .2), [(.02, .2)], [], False),
    ((2, 1), (.02, .2), [(.02, .1)], [], False),
    ((2, 1), (.02, .2), [(.02, .2)], ['delivery warning'], False),
    ((2, 1), (.02, .2), [(.02, .2)], [], True),
])
def test_unlearned_motion_breaks_prior_terminal_credit(state, candidate, receipts, warnings, halted):
    from camera_checks import remember_camera_action
    from camera_lane import CameraQPolicy
    from run_map_rl import learn_transition
    record = remember_camera_action(None, (2, 1), 3, 42, (.02, .2), [(.02, .2)], [], False)
    record = remember_camera_action(record, state, 1, 43, candidate, receipts, warnings, halted)
    assert record is None
    policy = CameraQPolicy(seed=17, perception=perception_id())
    result = dict(reward=-10., terminated=True, truncated=False, reason='camera_lane_lost',
                  camera_failure_reason='camera_target_unavailable')
    assert learn_transition(policy, record, None, result) == 'invalid_camera_observation'
    assert policy.updates == 0


def test_native_camera_containment_reaches_core_with_unknown_error(monkeypatch):
    import camera_lane
    from control.sensing.perception.camera_ground import ground_plane
    from control.sensing.perception.lane import LaneObservation
    model = SimpleNamespace(model_revision='lane-seg-test', infer_drivable=lambda frame:
        (np.ones((240, 320), np.uint8), 'drivable', {'crosswalk_mask': np.zeros((240, 320), np.uint8)}, 1.))
    lane = camera_lane.LearnedCameraLane(model, ground_plane(.06343, .139626, 281.6, 160., 120., .6),
                                         camera_x=.03317, clock=lambda: 10.)
    def observed(*args, **kwargs):
        lane.keeper.last = {'boundaries': [], 'crosswalk': (.1, .2)}
        return LaneObservation(.1, .9)
    monkeypatch.setattr(lane.keeper, 'update', observed)
    monkeypatch.setattr(camera_lane, 'keep_step', lambda *args: (None, False))
    try:
        lane.observe(np.full((240, 320, 3), 100, np.uint8), stamp=1., source_now=1., pose=(0., 0., 0.))
        evidence = lane.manager._observation.containment
        assert evidence.ground_source == 'ISAAC' and evidence.stamp == 1.
        assert evidence.crosswalk.near_m == .1
        assert evidence.uncertainty_m is None and evidence.crosswalk_uncertainty_m is None
        assert lane.last['containment'] == evidence.model_dump()
        lane.invalidate('camera_target_unavailable')
        assert lane.state() is None and lane.last['model_used'] is False
    finally:
        lane.close()


def test_native_scan_reaches_camera_wall_and_core_return_evidence(monkeypatch):
    import camera_lane
    from core_common.robot_body import NOMINAL_BODY
    from control.sensing.perception.camera_ground import ground_plane
    from native_scan import scan_sample
    way = np.zeros((240, 320), np.uint8)
    way[112:, 65:256] = 255
    model = SimpleNamespace(model_revision='lane-seg-test',
                            infer_drivable=lambda frame: (way, 'drivable', {}, 1.))
    lane = camera_lane.LearnedCameraLane(model,
        ground_plane(.06343, .139626, 281.6, 160., 120., .6), camera_x=.03317, clock=lambda: 10.)
    seen = []
    original = camera_lane.keep_step
    def capture(*args):
        seen.append(args[8])
        return original(*args)
    monkeypatch.setattr(camera_lane, 'keep_step', capture)
    sample = scan_sample(lambda ray, report: None, lambda ray: ray,
                         robot_path='/World/Imported', stamp_ns=1_000_000_000)
    try:
        assert lane.observe_scan(sample, body=NOMINAL_BODY) is True
        assert lane.manager._return_view.points == ()
        assert len(lane.manager._return_view.unknown) == 640
        assert lane.manager._return_source_high_water_ns == 1_000_000_000
        lane.observe(np.full((240, 320, 3), 100, np.uint8),
                     stamp=1., source_now=1., pose=(0., 0., 0.))
        assert seen == [(None, 1., {'left': None, 'right': None}, None)]   # + CORE's front sector (none)
        assert lane.observe_scan(sample, body=NOMINAL_BODY) is False
        assert lane.state() is None
        stale = {**sample, 'source_stamp_ns': 2_000_000_000, 'source_now_ns': 3_000_000_000}
        assert lane.observe_scan(stale, body=NOMINAL_BODY) is False
    finally:
        lane.close()


@pytest.mark.parametrize('age_ns,accepted', [(0, True), (250_000_001, False), (-1_000_000, False)])
def test_native_scan_nanosecond_rounding_does_not_discard_current_camera(age_ns, accepted):
    from camera_lane import LearnedCameraLane
    from core_common.robot_body import NOMINAL_BODY
    from control.sensing.perception.camera_ground import ground_plane
    from native_scan import scan_sample
    source_now = 241 / 240
    stamp_ns = round(source_now * 1e9) - age_ns
    assert source_now < round(source_now * 1e9) / 1e9
    way = np.zeros((240, 320), np.uint8)
    way[112:, 65:256] = 255
    model = SimpleNamespace(model_revision='lane-seg-test',
                            infer_drivable=lambda frame: (way, 'drivable', {}, 1.))
    lane = LearnedCameraLane(model,
        ground_plane(.06343, .139626, 281.6, 160., 120., .6), camera_x=.03317, clock=lambda: 10.)
    sample = scan_sample(lambda ray, report: None, lambda ray: ray,
                         robot_path='/World/Imported', stamp_ns=stamp_ns)
    try:
        assert lane.observe_scan(sample, body=NOMINAL_BODY)
        lane.observe(np.full((240, 320, 3), 100, np.uint8),
                     stamp=source_now, source_now=source_now, pose=(0., 0., 0.))
        assert (lane.state() is not None) is accepted
        if not accepted:
            assert lane.last['reason'] == 'native_scan_stale'
    finally:
        lane.close()


@pytest.mark.parametrize('distance,moving', [(.5, True), (.075, False), (float('inf'), False)])
def test_native_body_sweep_uses_the_actual_scan_and_holds_unknown(distance, moving):
    from camera_lane import LearnedCameraLane
    from core_common.robot_body import NOMINAL_BODY
    from control.sensing.perception.camera_ground import ground_plane
    from native_scan import scan_sample
    way = np.zeros((240, 320), np.uint8)
    way[112:, 65:256] = 255
    lane = LearnedCameraLane(SimpleNamespace(model_revision='lane-seg-test',
        infer_drivable=lambda frame: (way, 'drivable', {}, 1.)),
        ground_plane(.06343, .139626, 281.6, 160., 120., .6), camera_x=.03317,
        clock=lambda: 10., body=NOMINAL_BODY)
    sample = scan_sample(lambda ray, report: None, lambda ray: ray,
                         robot_path='/World/Imported', stamp_ns=1_000_000_000)
    sample['ranges'] = [distance] * 640
    try:
        assert lane.manager.config.body_stop_known
        assert lane.manager.config.obstacle_mode == 'path'
        admitted = lane.observe_scan(sample, body=NOMINAL_BODY)
        if admitted:
            lane.observe(np.full((240, 320, 3), 100, np.uint8),
                         stamp=1., source_now=1., pose=(0., 0., 0.))
        decision = lane.manager.tick_gain(10., gain=1.)
        assert (decision.linear > 0.) is moving
        if distance == float('inf'):
            assert not admitted and lane.state() is None
            assert lane.last['reason'] == 'native_scan_unknown'
        else:
            assert admitted and lane.manager._scan_points
        with pytest.raises(ValueError, match='geometry differ'):
            lane.observe_scan(sample, body=replace(NOMINAL_BODY, rotation_radius_m=.1))
    finally:
        lane.close()


@pytest.mark.parametrize('yaw', [0., .4, 6.683185307179586])
def test_camera_route_guide_separates_local_tangent_from_ahead_curve(yaw):
    import math
    from run_map_rl import camera_route_guide
    task = SimpleNamespace(points=((0., 0.), (.1, 0.), (.1, -.3)), distance=(0., .1, .4), index=0)
    result = dict(deviation_m=.012, progress_m=.03)
    guide = camera_route_guide(task, (0., 0., yaw), result, 17.)
    wrap = lambda angle: math.degrees(math.atan2(math.sin(angle), math.cos(angle)))
    assert guide[0] == pytest.approx(wrap(math.atan2(-.3, .1) - yaw))
    assert guide[3] == pytest.approx(wrap(-yaw))
    assert guide[1:3] == (17., False)
    assert guide[4:] == (.012, .03)


@pytest.mark.parametrize('index', [0, 2, 3])
def test_camera_route_guide_uses_nonzero_tangent_at_duplicates_and_route_end(index):
    from run_map_rl import camera_route_guide
    task = SimpleNamespace(points=((0., 0.), (0., 0.), (0., .3), (0., .3)),
                           distance=(0., 0., .3, .3), index=index)
    guide = camera_route_guide(task, (*task.points[index], 0.),
                               dict(deviation_m=0., progress_m=task.distance[index]), 1.)
    assert guide[3] == pytest.approx(90.)


def test_missing_camera_observation_is_not_a_learning_state():
    from camera_lane import LearnedCameraLane
    from control.sensing.perception.camera_ground import ground_plane
    lane = LearnedCameraLane(SimpleNamespace(), ground_plane(.06343, .139626, 281.6, 160., 120., .6),
                             camera_x=.03317, clock=lambda: 10.)
    try:
        assert lane.state() is None
    finally:
        lane.close()


def test_unusable_training_episode_preserves_failure_and_allows_later_valid_learning():
    from camera_lane import CameraQPolicy
    from run_map_rl import camera_episode_usable, learn_transition
    policy = CameraQPolicy(seed=17, perception=perception_id())
    assert camera_episode_usable('train', 0) is False
    assert learn_transition(policy, ((3, 1), 1), None,
                            dict(reward=-10., terminated=True, truncated=False)) == 'invalid_camera_observation'
    assert policy.updates == 0 and policy.table == {}
    assert camera_episode_usable('train', 1) is True
    assert learn_transition(policy, ((3, 1), 1), (3, 1),
                            dict(reward=1., terminated=True, truncated=False)) == 'updated'
    assert policy.updates == 1


@pytest.mark.parametrize('phase', ['baseline', 'eval'])
def test_camera_admission_still_rejects_an_unusable_baseline_or_evaluation(phase):
    from run_map_rl import camera_episode_usable
    assert camera_episode_usable(phase, 1) is True
    with pytest.raises(RuntimeError, match='candidate not accepted'):
        camera_episode_usable(phase, 0)


def test_learning_state_expires_with_source_age_and_processing_time():
    from camera_lane import LearnedCameraLane
    from control.sensing.perception.camera_ground import ground_plane
    now = [10.]
    way = np.zeros((240, 320), np.uint8)
    way[112:, 65:256] = 255
    model = SimpleNamespace(model_revision='lane-seg-test',
                            infer_drivable=lambda frame: (way, 'drivable', {}, 1.))
    lane = LearnedCameraLane(model, ground_plane(.06343, .139626, 281.6, 160., 120., .6),
                             camera_x=.03317, clock=lambda: now[0])
    try:
        lane.observe(np.full((240, 320, 3), 100, np.uint8), stamp=1., source_now=1.15, pose=(0., 0., 0.))
        assert lane.state() is not None
        now[0] = 10.151
        assert lane.state() is None
        now[0] = 9.9
        assert lane.state() is None
    finally:
        lane.close()


@pytest.mark.parametrize('previous,state,reason', [
    (((2, 1), 3), None, 'invalid_camera_observation'),
    (None, (3, 1), 'no_previous_observation'),
    ((None, 3), (3, 1), 'no_previous_observation'),
])
def test_learning_rejects_missing_observations_without_creating_q(previous, state, reason):
    from camera_lane import CameraQPolicy
    from run_map_rl import learn_transition
    policy = CameraQPolicy(seed=17, perception=perception_id())
    assert learn_transition(policy, previous, state,
                            dict(reward=1., terminated=False, truncated=False)) == reason
    assert policy.updates == 0 and policy.table == {}


def test_measured_terminal_transition_does_not_bootstrap_and_counts_real_update():
    from camera_lane import CameraQPolicy
    from run_map_rl import learn_transition
    policy = CameraQPolicy(seed=17, perception=perception_id())
    policy.table[(3, 1)] = [100.] * 4
    result = dict(reward=-10., terminated=True, truncated=False)
    assert learn_transition(policy, ((2, 1), 3), (3, 1), result) == 'updated'
    assert policy.updates == 1 and policy.table[(2, 1)][3] == pytest.approx(-1.5)


def test_camera_loss_penalizes_last_applied_action_without_a_next_observation():
    from camera_lane import CameraQPolicy
    from run_map_rl import learn_transition
    policy = CameraQPolicy(seed=17, perception=perception_id())
    policy.table[(3, 1)] = [100.] * 4
    result = dict(reward=-10., terminated=True, truncated=False, reason='camera_lane_lost',
                  camera_failure_reason='camera_target_unavailable')
    assert learn_transition(policy, ((2, 1), 3), None, result) == 'terminal_camera_loss'
    assert policy.updates == 1 and policy.table[(2, 1)][3] == pytest.approx(-1.5)
    assert None not in policy.table and policy.table[(3, 1)] == [100.] * 4


@pytest.mark.parametrize('previous,terminated,truncated,reason', [
    (None, True, False, 'camera_lane_lost'),
    ((None, 3), True, False, 'camera_lane_lost'),
    (((2, 1), 3), False, False, 'camera_lane_lost'),
    (((2, 1), 3), False, True, 'time_limit'),
    (((2, 1), 3), True, True, 'camera_lane_lost'),
    (((2, 1), 3), True, False, 'off_route'),
])
def test_missing_camera_terminal_credit_requires_executed_state_and_camera_loss(
        previous, terminated, truncated, reason):
    from camera_lane import CameraQPolicy
    from run_map_rl import learn_transition
    policy = CameraQPolicy(seed=17, perception=perception_id())
    result = dict(reward=-10., terminated=terminated, truncated=truncated, reason=reason,
                  camera_failure_reason='camera_target_unavailable')
    assert learn_transition(policy, previous, None, result) == 'invalid_camera_observation'
    assert policy.updates == 0 and policy.table == {}


@pytest.mark.parametrize('cause', [None, 'camera_source_stale', 'camera_processing_stale',
    'learned_camera_unavailable', 'native_scan_unavailable', 'native_scan_unknown', 'native_scan_stale'])
def test_sensor_failure_is_not_credited_to_steering(cause):
    from camera_lane import CameraQPolicy
    from run_map_rl import learn_transition
    policy = CameraQPolicy(seed=17, perception=perception_id())
    result = dict(reward=-10., terminated=True, truncated=False, reason='camera_lane_lost',
                  camera_failure_reason=cause)
    assert learn_transition(policy, ((2, 1), 3), None, result) == 'invalid_camera_observation'
    assert policy.updates == 0 and not policy.table


def test_camera_command_is_zero_if_observation_expires_during_core_tick(monkeypatch):
    from camera_lane import LearnedCameraLane
    from control.sensing.perception.camera_ground import ground_plane
    from run_map_rl import camera_tick
    now = [10.]
    way = np.zeros((240, 320), np.uint8)
    way[112:, 65:256] = 255
    lane = LearnedCameraLane(SimpleNamespace(model_revision='lane-seg-test',
        infer_drivable=lambda frame: (way, 'drivable', {}, 1.)),
        ground_plane(.06343, .139626, 281.6, 160., 120., .6),
        camera_x=.03317, clock=lambda: now[0])
    try:
        lane.observe(np.full((240, 320, 3), 100, np.uint8), stamp=1., source_now=1., pose=(0., 0., 0.))
        original = lane.manager.tick_gain
        def delayed_tick(current, *, gain):
            decision = original(current, gain=gain)
            assert decision.linear > 0.
            now[0] += .002
            return decision
        monkeypatch.setattr(lane.manager, 'tick_gain', delayed_tick)
        now[0] = 10.299
        decision, state = camera_tick(lane, now[0], gain=1.)
        assert state is None
        applied = []
        assert lane.manager.apply_if_current(decision, lambda command:
                                             applied.append((command.linear, command.angular)))
        assert applied == [(0., 0.)]
    finally:
        lane.close()


def test_two_camera_lanes_keep_distinct_core_event_identity_and_loss_state():
    from camera_lane import LearnedCameraLane
    from control.sensing.perception.camera_ground import ground_plane
    from core_features.line_follow import LineFollowMode, LineObservation
    ground = ground_plane(.06343, .139626, 281.6, 160., 120., .6)
    lanes = [LearnedCameraLane(SimpleNamespace(), ground, camera_x=.03317, clock=lambda: 10.,
                              device_id=device_id)
             for device_id in ('isaac-pinky-a', 'isaac-pinky-b')]
    try:
        for lane, device_id in zip(lanes, ('isaac-pinky-a', 'isaac-pinky-b')):
            events = lane.manager._events.history()
            assert events and {event.robot_id for event in events} == {device_id}
            lane.manager.observe(LineObservation(LineFollowMode.CAMERA_LINE, 10., True, .2, 1.),
                                 received_at=10., source_now=10.)
        lanes[0].invalidate('test_camera_loss')
        assert lanes[0].manager.tick_gain(10., gain=1.).linear == 0
        assert lanes[1].manager.tick_gain(10., gain=1.).linear > 0
    finally:
        for lane in lanes:
            lane.close()


@pytest.mark.parametrize('device_id', ['real-pinky', '', None, True])
def test_camera_manager_refuses_non_simulation_identity(device_id):
    from camera_lane import CameraLineManager
    from core_features.line_follow import LineFollowConfig
    with pytest.raises(ValueError, match='simulation device'):
        CameraLineManager(config=LineFollowConfig(), clock=lambda: 10., device_id=device_id)


def test_camera_policy_roundtrip_refuses_path_policy_and_other_model():
    from camera_lane import CameraQPolicy
    from map_task import QPolicy
    identity = perception_id()
    p = CameraQPolicy(seed=17, perception=identity)
    p.update((2, 1), 3, 1., (3, 1), terminated=True)
    assert CameraQPolicy.restore(p.export(), perception=identity).export() == p.export()
    with pytest.raises(ValueError):
        CameraQPolicy.restore(QPolicy(seed=17).export(), perception=identity)
    with pytest.raises(ValueError):
        CameraQPolicy.restore(p.export(), perception={**identity, 'model_sha256': 'b' * 64})


def manager(config=None):
    from camera_lane import CameraLineManager
    from core_features.line_follow import LineFollowConfig, LineFollowMode, LineObservation
    now = [10.]
    m = CameraLineManager(config=config or LineFollowConfig(cruise_speed=.04, steering_gain=.4),
                          clock=lambda: now[0])
    m.set_mode(LineFollowMode.CAMERA_LINE)
    m.observe(LineObservation(LineFollowMode.CAMERA_LINE, 10., True, .2, 1.),
              received_at=10., source_now=10.)
    return m, now


def test_gain_changes_steering_before_manager_caps_and_authority_gate():
    from core_features.line_follow import LineFollowConfig
    m, now = manager()
    before = m.tick_gain(10., gain=1.)
    after = m.tick_gain(10., gain=1.7)
    assert after.angular == pytest.approx(before.angular * 1.7)
    assert after.linear == before.linear
    held, _ = manager(LineFollowConfig(cruise_speed=.04, steering_gain=.4,
                                     authority_required=True))
    out = held.tick_gain(10., gain=1.7)
    assert (out.linear, out.angular) == (0., 0.)
    assert held.status().reason == 'authority_none'


def test_camera_stale_and_invalid_gain_cannot_drive():
    m, now = manager()
    now[0] = 10.31
    out = m.tick_gain(now[0], gain=1.7)
    assert (out.linear, out.angular) == (0., 0.)
    for gain in (float('nan'), 0., 8., True):
        with pytest.raises(ValueError):
            m.tick_gain(now[0], gain=gain)


def test_changed_gain_uses_changed_intended_twist_for_body_sweep():
    m, now = manager()
    m.observe_scan_points(((.5, .5),), received_at=10.)
    seen = []
    original = m._path_clearance
    def capture():
        seen.append(m._intended)
        return original()
    m._path_clearance = capture
    m._config = replace(m.config, obstacle_mode='path')
    decision = m.tick_gain(10., gain=1.7)
    assert seen and seen[-1] == pytest.approx((decision.linear, decision.angular))


def test_camera_pipeline_inference_failure_holds_without_rule_fallback():
    from camera_lane import LearnedCameraLane
    from control.sensing.perception.camera_ground import ground_plane
    class Broken:
        model_revision = 'lane-seg-test'
        def infer_drivable(self, frame):
            raise RuntimeError('test failed inference')
    ground = ground_plane(.06343, .139626, 281.6, 160., 120., .6)
    lane = LearnedCameraLane(Broken(), ground, camera_x=.03317, clock=lambda: 10.)
    lane.observe(np.full((240, 320, 3), 100, np.uint8), stamp=1., source_now=1., pose=(0., 0., 0.))
    out = lane.manager.tick_gain(10., gain=1.7)
    assert (out.linear, out.angular) == (0., 0.)
    assert lane.last['model_used'] is False and lane.last['inference_error']


def test_camera_source_age_and_replay_invalidate_existing_observation():
    from camera_lane import LearnedCameraLane
    from control.sensing.perception.camera_ground import ground_plane
    ground = ground_plane(.06343, .139626, 281.6, 160., 120., .6)
    model = SimpleNamespace(model_revision='lane-seg-test', infer_drivable=lambda _f: pytest.fail('stale inferred'))
    lane = LearnedCameraLane(model, ground, camera_x=.03317, clock=lambda: 10.)
    lane.observe(np.full((240, 320, 3), 100, np.uint8), stamp=1., source_now=1.31, pose=(0., 0., 0.))
    assert lane.last['reason'] == 'camera_source_stale'
    assert lane.state() is None


def test_low_light_image_never_calls_model():
    from camera_lane import LearnedCameraLane
    from control.sensing.perception.camera_ground import ground_plane
    ground = ground_plane(.06343, .139626, 281.6, 160., 120., .6)
    model = SimpleNamespace(model_revision='lane-seg-test', infer_drivable=lambda _f: pytest.fail('dark inferred'))
    lane = LearnedCameraLane(model, ground, camera_x=.03317, clock=lambda: 10.)
    lane.observe(np.zeros((240, 320, 3), np.uint8), stamp=1., source_now=1., pose=(0., 0., 0.))
    assert lane.last['reason'] == 'low_light'
    out = lane.manager.tick_gain(10., gain=1.)
    assert (out.linear, out.angular) == (0., 0.)


def test_existing_drivable_output_reaches_core_then_replayed_frame_stops():
    from camera_lane import LearnedCameraLane
    from control.sensing.perception.camera_ground import ground_plane
    ground = ground_plane(.06343, .139626, 281.6, 160., 120., .6)
    rows, cols = np.mgrid[0:240, 0:320]
    denominator = ground.focal_px * np.sin(ground.pitch_rad) + (rows - 120) * np.cos(ground.pitch_rad)
    with np.errstate(divide='ignore', invalid='ignore'):
        lateral = ground.height_m * (cols - 160) / denominator
    way = ((denominator > 0) & (np.abs(lateral) < .0925)).astype(np.uint8)
    calls = []
    def infer(frame):
        calls.append(frame)
        return way, 'drivable', {}, 1.
    model = SimpleNamespace(model_revision='lane-seg-test', infer_drivable=infer)
    lane = LearnedCameraLane(model, ground, camera_x=.03317, clock=lambda: 10.)
    frame = np.full((240, 320, 3), 100, np.uint8)
    lane.observe(frame, stamp=1., source_now=1., pose=(0., 0., 0.))
    assert lane.last['model_used'] and lane.last['paint_kind'] == 'drivable'
    out = lane.manager.tick_gain(10., gain=1.)
    assert out.linear > 0. and abs(out.angular) < .01
    lane.observe(frame, stamp=1., source_now=1., pose=(0., 0., 0.))
    stopped = lane.manager.tick_gain(10., gain=1.7)
    assert (stopped.linear, stopped.angular) == (0., 0.) and len(calls) == 1


def gap_lane(frames, curvature=0.):
    from camera_lane import LearnedCameraLane
    from control.sensing.perception.camera_ground import ground_plane
    ground = ground_plane(.06343, .139626, 281.6, 160., 120., .6)
    rows, cols = np.mgrid[0:240, 0:320]
    denominator = ground.focal_px * np.sin(ground.pitch_rad) + (rows - 120) * np.cos(ground.pitch_rad)
    with np.errstate(divide='ignore', invalid='ignore'):
        lateral = ground.height_m * (cols - 160) / denominator
        forward = ground.height_m * (ground.focal_px * np.cos(ground.pitch_rad)
            - (rows - 120) * np.sin(ground.pitch_rad)) / denominator + .03317
        centre = np.zeros_like(forward) if curvature == 0. else (
            1. - np.sqrt(1. - (curvature * forward) ** 2)) / curvature
    way = ((denominator > 0) & (np.abs(lateral + centre) < .0925)
        & ((forward < .45) if curvature else True)).astype(np.uint8)
    output = [way, 'drivable']
    model = SimpleNamespace(model_revision='lane-seg-test',
        infer_drivable=lambda _f: (*output, {}, 1.))
    now = [10.]
    lane = LearnedCameraLane(model, ground, camera_x=.03317, clock=lambda: now[0])
    image = np.full((240, 320, 3), 100, np.uint8)
    lane.history.add(9.9, 0., 0., 0.)  # Odom is already streaming before the first image.
    for index in range(frames):
        now[0] = 10. + index * .1
        lane.observe(image, stamp=now[0], source_now=now[0], pose=(0., 0., 0.))
    if frames >= 3 and curvature == 0.:
        assert lane.keeper.last.get('expected_path_state') == 'live', lane.keeper.last
    output[:] = [np.zeros_like(way), 'lane_marking']
    return lane, now, image, output


@pytest.mark.parametrize('frames,continues', [(2, False), (3, True)])
def test_camera_gap_uses_observed_geometry_without_learning(frames, continues):
    from run_map_rl import camera_tick
    lane, now, image, _output = gap_lane(frames)
    now[0] += .1
    lane.observe(image, stamp=now[0], source_now=now[0], pose=(.01, .01, .1))
    decision, state = camera_tick(lane, now[0], gain=1.)
    assert (decision.linear > 0.) is continues, (lane.last, lane.keeper.last)
    assert decision.angular < 0. if continues else decision.angular == 0.
    assert state is None
    lane.close()


@pytest.mark.parametrize('curvature', [-1., 1.])
def test_a_visible_curve_keeps_its_observed_shape_during_a_gap(curvature):
    from run_map_rl import camera_tick
    lane, now, image, _output = gap_lane(3, curvature=curvature)
    assert abs(lane.keeper.last['drivable_steer']['curvature_1pm']) > .5
    now[0] += .1
    lane.observe(image, stamp=now[0], source_now=now[0], pose=(0., 0., 0.))
    decision, state = camera_tick(lane, now[0], gain=1.)
    assert decision.linear > 0. and decision.angular * curvature > 0., lane.last
    assert lane.last['camera_provenance'] == 'odom_expected_path'
    assert state is None
    assert lane.state() is None
    boosted, boosted_state = camera_tick(lane, now[0], gain=1.7)
    assert (boosted.linear, boosted.angular) == pytest.approx((decision.linear, decision.angular))
    assert boosted_state is None
    lane.close()


@pytest.mark.parametrize('loss', ['time', 'distance', 'rewind', 'jump', 'dark', 'inference', 'stale', 'pose'])
def test_camera_geometry_hold_stops_at_budgets_and_invalid_input(loss):
    from run_map_rl import camera_tick
    lane, now, image, _output = gap_lane(3)
    now[0] += .1
    lane.observe(image, stamp=now[0], source_now=now[0], pose=(0., 0., 0.))
    assert camera_tick(lane, now[0], gain=1.)[0].linear > 0.
    if loss == 'time':
        for _ in range(25):
            now[0] += .1
            lane.observe(image, stamp=now[0], source_now=now[0], pose=(0., 0., 0.))
    else:
        now[0] += .1
        pose = (.25, 0., 0.) if loss == 'distance' else (.26, 0., 0.) if loss == 'jump' else (0., 0., 0.)
        if loss == 'pose':
            pose = (float('nan'), 0., 0.)
        stamp = 10. if loss == 'rewind' else now[0] - .31 if loss == 'stale' else now[0]
        if loss == 'dark':
            image = np.zeros_like(image)
        if loss == 'inference':
            def broken(_frame):
                raise RuntimeError('lost model')
            lane.worker._slot.poll().infer_drivable = broken
        lane.observe(image, stamp=stamp, source_now=now[0], pose=pose)
    decision, state = camera_tick(lane, now[0], gain=1.)
    assert (decision.linear, decision.angular) == (0., 0.)
    assert state is None
    lane.close()


def test_existing_model_revision_hash_and_roles_must_match_before_inference():
    from camera_lane import camera_model_identity
    model = SimpleNamespace(manifest=SimpleNamespace(model_revision='lane-seg-test',
        backend='onnx', classes=[SimpleNamespace(role='lane_marking'), SimpleNamespace(role='drivable')],
        files=[SimpleNamespace(name='model.onnx', sha256='a' * 64)],
        onnx_file=lambda: Path('model.onnx')))
    assert camera_model_identity(model, revision='lane-seg-test', sha256='a' * 64) == perception_id()
    for revision, sha in [('different', 'a' * 64), ('lane-seg-test', 'b' * 64)]:
        with pytest.raises(ValueError):
            camera_model_identity(model, revision=revision, sha256=sha)
    model.manifest.classes = [SimpleNamespace(role='lane_marking')]
    with pytest.raises(ValueError):
        camera_model_identity(model, revision='lane-seg-test', sha256='a' * 64)


@pytest.mark.parametrize('guide_deg', [0., 60., 170.])
def test_map_only_bridge_or_pivot_is_not_a_camera_lane(guide_deg):
    from camera_lane import LearnedCameraLane
    from control.sensing.perception.camera_ground import ground_plane
    ground = ground_plane(.06343, .139626, 281.6, 160., 120., .6)
    way = np.zeros((240, 320), np.uint8)
    way[140:165, 110:210] = 1  # A real nonempty mask, but no way under the robot.
    model = SimpleNamespace(model_revision='lane-seg-test',
        infer_drivable=lambda _f: (way, 'drivable', {}, 1.))
    lane = LearnedCameraLane(model, ground, camera_x=.03317, clock=lambda: 10.)
    lane.observe(np.full((240, 320, 3), 100, np.uint8), stamp=1., source_now=1.,
                 pose=(0., 0., 0.), guide=(guide_deg, 1., True, guide_deg, 0., 0.))
    out = lane.manager.tick_gain(10., gain=1.7)
    assert lane.observation is None and (out.linear, out.angular) == (0., 0.)
    assert lane.last['reason'] == 'camera_target_unavailable'
    assert 'camera_target' in lane.last
    assert 'reason' in lane.last['camera_target']
    assert 'exit_behind_line' in lane.last['camera_target']
    assert 'centre_path_m' in lane.last['camera_target']
    assert lane.last['camera_target']['reason'] == 'way_beyond_line'
    assert lane.last['camera_target']['target_now_m'] is None
    assert lane.last['camera_target']['centre_path_m'] == []
    import json
    json.dumps(lane.last, allow_nan=False)
    lane.close()


@pytest.mark.parametrize('changes,accepted', [
    ({}, True),
    ({'observed_creep_key': 9.0}, False),
    ({'observed_creep_target_m': None}, False),
    ({'observed_creep_target_m': (-.2, .05)}, False),
    ({'observed_creep_target_m': (.2, float('nan'))}, False),
    ({'exit_from_memory': True}, False),
    ({'exit_behind_line': True}, False),
    ({'switch_pending': 'drivable_centre'}, False),
    ({'strategy': 'drivable_creep_map'}, False),
])
def test_only_current_observed_creep_is_admitted(monkeypatch, changes, accepted):
    import camera_lane
    lane, now, image, _ = gap_lane(1)
    now[0] = 10.1
    info = dict(strategy='drivable_creep', observed_creep_key=now[0],
                observed_creep_target_m=(.2, .05))
    info.update(changes)
    def keep(*args, **kwargs):
        args[2].update(strategy=info['strategy'], drivable_steer=info)
        return (-.1, .6), True
    monkeypatch.setattr(camera_lane, 'keep_step', keep)
    lane.observe(image, stamp=now[0], source_now=now[0], pose=(0., 0., 0.))
    if accepted:
        assert lane.observation is not None
        assert lane.last['camera_provenance'] == 'observed_creep'
    else:
        assert lane.observation is None
        assert lane.last['reason'] == 'camera_target_unavailable'
    lane.close()


@pytest.mark.parametrize('prior_frames', [0, 3])
def test_a_turning_corner_closed_further_than_the_pivot_distance_is_driven_up_to(prior_frames):
    # user 2026-10-18: a route prior names the side; the closed corner turns in place (was a guided creep)
    lane, now, image, output = gap_lane(prior_frames)
    now[0] += .1
    ground = lane.ground
    rows, cols = np.mgrid[0:240, 0:320]
    denominator = ground.focal_px * np.sin(ground.pitch_rad) + (rows - 120) * np.cos(ground.pitch_rad)
    with np.errstate(divide='ignore', invalid='ignore'):
        lateral = ground.height_m * (cols - 160) / denominator
        forward = ground.height_m * (ground.focal_px * np.cos(ground.pitch_rad)
            - (rows - 120) * np.sin(ground.pitch_rad)) / denominator + .03317
    output[:] = [((denominator > 0) & (np.abs(lateral) < .06) & (forward < .17)).astype(np.uint8), 'drivable']
    lane.observe(image, stamp=now[0], source_now=now[0], pose=(0., 0., 0.),
                 guide=(80., now[0], False, 0., 0., 0.))
    # closed 0.17 m ahead: it drives up to the corner and turns there (PIVOT_AHEAD_M), not 0.25 m early
    assert lane.last.get('camera_provenance') == 'observed_target', lane.last
    assert lane.keeper.last['strategy'] == 'drivable_centre', lane.keeper.last
    lane.close()


def test_camera_failure_snapshots_preserve_distinct_reasons_without_unbounded_output():
    from run_map_rl import camera_snapshot_due
    current = dict(reason='camera_target_unavailable', strategy='drivable_pivot_right')
    key = (current['reason'], current['strategy'])
    assert camera_snapshot_due(0, {}, set())
    assert not camera_snapshot_due(1, dict(reason=None, strategy='drivable_centre'), set())
    assert camera_snapshot_due(1, current, set())
    assert not camera_snapshot_due(2, current, {key})
    assert camera_snapshot_due(2, dict(reason='native_scan_unknown'), {key})
    assert not camera_snapshot_due(3, current, {(str(i), None) for i in range(8)})


@pytest.mark.parametrize('phase,visible,learned,expected', [
    ('train', 0, 0, None), ('baseline', 1, 0, None), ('eval', 1, 1, None),
    ('baseline', 0, 0, 'existing model produced no usable camera lane'),
    ('eval', 0, 0, 'existing model produced no usable camera lane'),
    ('eval', 1, 0, 'evaluation visited no learned state'),
])
def test_failed_camera_heading_remains_rejected_when_later_headings_are_measured(phase, visible, learned, expected):
    from run_map_rl import camera_admission_error
    error = camera_admission_error(phase, visible, learned)
    assert error is None if expected is None else expected in error


def test_inference_wall_time_cannot_refresh_an_old_camera_frame():
    from camera_lane import LearnedCameraLane
    from control.sensing.perception.camera_ground import ground_plane
    ground = ground_plane(.06343, .139626, 281.6, 160., 120., .6)
    now = [10.]
    def infer(_frame):
        now[0] += .31
        return np.ones((240, 320), np.uint8), 'drivable', {}, 310.
    lane = LearnedCameraLane(SimpleNamespace(model_revision='lane-seg-test', infer_drivable=infer),
                             ground, camera_x=.03317, clock=lambda: now[0])
    lane.observe(np.full((240, 320, 3), 100, np.uint8), stamp=1., source_now=1., pose=(0., 0., 0.))
    out = lane.manager.tick_gain(now[0], gain=1.)
    assert lane.observation is None and (out.linear, out.angular) == (0., 0.)
    assert lane.last['reason'] == 'camera_processing_stale'


def test_existing_camera_derived_off_line_recovery_keeps_its_provenance():
    from camera_lane import LearnedCameraLane
    from control.sensing.perception.camera_ground import ground_plane
    ground = ground_plane(.06343, .139626, 281.6, 160., 120., .6)
    way = np.zeros((240, 320), np.uint8)
    way[90:, :100] = 1
    lane = LearnedCameraLane(SimpleNamespace(model_revision='lane-seg-test',
        infer_drivable=lambda _f: (way, 'drivable', {}, 1.)), ground, camera_x=.03317, clock=lambda: 10.)
    lane.observe(np.full((240, 320, 3), 100, np.uint8), stamp=1., source_now=1., pose=(0., 0., 0.))
    assert lane.observation is not None
    assert lane.last['strategy'] == 'drivable_off_line_left'
    assert lane.last['camera_provenance'] == 'observed_straddle'
    assert lane.manager.tick_gain(10., gain=1.).angular > 0.


def test_camera_training_has_three_paired_held_out_comparisons():
    from run_map_rl import episode_phases
    phases = episode_phases(6, camera=True, evaluation_only=False)
    assert phases[0] == ('baseline', 101, 0.)
    training = [item for item in phases if item[0] == 'train']
    assert [item[1] for item in training] == list(range(6))
    evaluations = [(index, seed, angle) for index, (phase, seed, angle) in enumerate(phases) if phase == 'eval']
    assert len(evaluations) >= 3 and len({seed for _, seed, _ in evaluations}) == len(evaluations)
    for index, seed, angle in evaluations:
        assert phases[index - 1] == ('baseline', seed, angle)
        assert seed not in {item[1] for item in training}
        assert all(item[0] != 'train' for item in phases[index:])


def test_saved_camera_policy_pairs_all_four_headings_without_training():
    import math
    from run_map_rl import episode_phases
    phases = episode_phases(6, camera=True, evaluation_only=True)
    assert len(phases) == 8 and all(phase != 'train' for phase, _, _ in phases)
    assert {angle for phase, _, angle in phases if phase == 'eval'} == {0., math.pi / 2, math.pi, -math.pi / 2}
    for index, (phase, seed, angle) in enumerate(phases):
        if phase == 'eval':
            assert phases[index - 1] == ('baseline', seed, angle)


def test_path_policy_keeps_its_existing_training_and_four_heading_protocol():
    from run_map_rl import episode_phases
    phases = episode_phases(2, camera=False, evaluation_only=False)
    assert [phase for phase, _, _ in phases] == ['baseline', 'train', 'train', 'eval', 'eval']
    assert all(phase == 'eval' for phase, _, _ in episode_phases(2, camera=False, evaluation_only=True))


def comparison_episodes():
    shared = dict(seed=202, initial_heading_offset_rad=0., initial_target_pose=[0., 0., .1],
                  initial_pose=[0., 0., .1, 0., 0.], time_limit_s=400., policy_state_sha256='a' * 64)
    return (dict(shared, phase='baseline', epoch=8, complete=False, sim_s=200.),
            dict(shared, phase='eval', epoch=9, complete=True, sim_s=190.))


def test_camera_comparison_preserves_a_failed_baseline_and_successful_fixed_policy():
    from run_map_rl import camera_comparison
    baseline, evaluated = comparison_episodes()
    pair = camera_comparison(baseline, evaluated)
    assert pair['baseline_epoch'] == 8 and pair['eval_epoch'] == 9
    assert pair['baseline_complete'] is False and pair['eval_complete'] is True
    assert pair['initial_position_delta_m'] == 0. and pair['initial_heading_delta_rad'] == 0.


@pytest.mark.parametrize('change', [
    {'seed': 303}, {'phase': 'train'}, {'time_limit_s': 200.}, {'policy_state_sha256': 'b' * 64},
    {'initial_target_pose': [0., 0., .2]}, {'initial_heading_offset_rad': 1.},
    {'initial_pose': [.016, 0., .1, 0., 0.]}, {'initial_pose': [0., 0., .126, 0., 0.]},
    {'initial_pose': [float('nan'), 0., .1, 0., 0.]}, {'epoch': 10},
])
def test_camera_comparison_rejects_different_conditions_or_physical_start(change):
    from run_map_rl import camera_comparison
    baseline, evaluated = comparison_episodes()
    evaluated.update(change)
    with pytest.raises(ValueError, match='paired camera'):
        camera_comparison(baseline, evaluated)


def test_camera_sample_offsets_match_despite_previous_episode_and_stop_frames():
    from run_map_rl import camera_sample_due
    for start in (0, 1, 23, 24, 3124, 5569):
        offsets = [offset for offset in range(100) if camera_sample_due(start + offset, start)]
        assert offsets == [0, 24, 48, 72, 96]


def test_saved_policy_json_format_changes_file_hash_but_not_comparison_state_hash():
    import hashlib
    import json
    from camera_lane import CameraQPolicy
    from run_map_rl import policy_state_sha256, camera_comparison
    policy = CameraQPolicy(seed=17, perception=perception_id())
    policy.update((3, 1), 1, 1., (3, 1), terminated=True)
    raws = [json.dumps(policy.export(), sort_keys=True).encode(),
            (json.dumps(policy.export(), indent=2) + '\n').encode()]
    assert hashlib.sha256(raws[0]).digest() != hashlib.sha256(raws[1]).digest()
    restored = [CameraQPolicy.restore(json.loads(raw), perception=perception_id()) for raw in raws]
    baseline, evaluated = comparison_episodes()
    baseline['policy_state_sha256'] = policy_state_sha256(restored[0].export())
    evaluated['policy_state_sha256'] = policy_state_sha256(restored[1].export())
    assert camera_comparison(baseline, evaluated)['eval_complete'] is True
