"""D-650: existing perception/CORE gates, not an alternate motion owner."""
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import sys

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[4]
for part in ('tools/sim/isaac', 'contracts/foundation', 'contracts/motion/src',
             'contracts/skill/src', 'middleware/core/services', 'middleware/core/events',
             'middleware/core/gateway', 'middleware/perception'):
    sys.path.insert(0, str(ROOT / part))


def perception_id():
    return {'schema': 'isaac-camera-error-confidence/1',
            'model_revision': 'lane-seg-test', 'model_sha256': 'a' * 64}


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
    assert guide[1:3] == (17., True)
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
