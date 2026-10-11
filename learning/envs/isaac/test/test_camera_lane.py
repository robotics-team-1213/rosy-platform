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
    assert lane.state() == (3, 0)


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
