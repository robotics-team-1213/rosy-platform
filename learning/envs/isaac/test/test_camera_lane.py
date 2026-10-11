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
    assert held.status().reason == 'authority_missing'


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
