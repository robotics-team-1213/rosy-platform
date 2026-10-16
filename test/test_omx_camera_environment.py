"""Environment transitions must not reuse a dark-scene recovery in strong light."""
import importlib.util
from pathlib import Path
import sys

import numpy as np
import pytest

REPO = Path(__file__).parents[1]
FILES = {
    'camera_quality': REPO / 'deploy/robot/omx/camera_quality.py',
    'camera_environment': REPO / 'deploy/robot/omx/camera_environment.py',
    'camera_readiness': REPO / 'deploy/robot/omx/camera_readiness.py',
}


def load(name):
    spec = importlib.util.spec_from_file_location(name, FILES[name])
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize('value,condition', [(0, 'UNDEREXPOSED'), (255, 'OVEREXPOSED'),
                                           (100, 'LOW_CONTRAST')])
def test_conditions_distinguish_missing_light_excess_light_and_missing_structure(value, condition):
    frame = np.full((120, 160, 3), value, np.uint8)
    assert load('camera_quality').frame_quality(frame)['condition'] == condition


def test_mixed_glare_and_shadow_is_not_routed_to_blind_gain_increase():
    frame = np.zeros((120, 160, 3), np.uint8)
    frame[:, 80:] = 255
    quality = load('camera_quality').frame_quality(frame)
    assert quality['condition'] == 'MIXED_LIGHTING'
    assert not quality['usable']


def observe_many(plan, condition, now, *, count=3):
    action = None
    for index in range(count):
        action = plan.observe(condition, now+index*.1, source_stamp=1000+now+index*.1)
    return action


def test_recovery_rearms_for_sustained_dark_to_bright_to_dark_transitions():
    plan = load('camera_environment').ExposureRecovery(dark_count=1, bright_count=1)
    assert observe_many(plan, 'UNDEREXPOSED', 0)['kind'] == 'dark'
    assert observe_many(plan, 'OVEREXPOSED', 6)['kind'] == 'bright'
    assert observe_many(plan, 'UNDEREXPOSED', 12)['kind'] == 'dark'
    assert plan.epoch == 3


def test_a_single_normal_or_class_flip_does_not_rearm_exhausted_recovery():
    plan = load('camera_environment').ExposureRecovery(dark_count=1, bright_count=1)
    observe_many(plan, 'UNDEREXPOSED', 0)
    observe_many(plan, 'UNDEREXPOSED', 6)
    epoch = plan.epoch
    assert plan.observe('NORMAL', 12, source_stamp=1012) is None
    assert observe_many(plan, 'UNDEREXPOSED', 13) is None
    assert plan.epoch == epoch
    assert observe_many(plan, 'NORMAL', 19) is None
    assert observe_many(plan, 'UNDEREXPOSED', 25)['kind'] == 'dark'


def test_stale_or_repeated_observations_reset_pending_confirmation():
    plan = load('camera_environment').ExposureRecovery(dark_count=1, bright_count=1)
    plan.observe('UNDEREXPOSED', 0, source_stamp=1000)
    plan.observe('UNDEREXPOSED', .1, source_stamp=1000.1)
    plan.observe(None, .2, source_stamp=1000.1)
    assert plan.observe('UNDEREXPOSED', .3, source_stamp=1000.3) is None


def test_post_control_samples_must_advance_past_the_host_receive_settle_boundary():
    plan = load('camera_environment').ExposureRecovery(dark_count=1, bright_count=1)
    observe_many(plan, 'UNDEREXPOSED', 0)
    plan.applied(monotonic=1, wall=1001)
    assert plan.observe('NORMAL', 3, source_stamp=1001.5) is None
    assert plan.state == 'SETTLING'
    observe_many(plan, 'NORMAL', 4)
    assert plan.state == 'NORMAL'


def test_unsupported_conditions_cannot_request_exposure_changes():
    plan = load('camera_environment').ExposureRecovery(dark_count=1, bright_count=1)
    assert observe_many(plan, 'MIXED_LIGHTING', 0) is None
    assert plan.state == 'UNSUPPORTED'


def test_attempt_budget_survives_restart_and_full_budget_does_not_delete_originals(tmp_path):
    runtime = load('camera_readiness')
    for index in range(6):
        runtime.reserve_budget(tmp_path, now_ns=1_000_000_000+index)
    restarted = load('camera_readiness')
    with pytest.raises(RuntimeError):
        restarted.reserve_budget(tmp_path, now_ns=2_000_000_000)
    restarted.reserve_budget(tmp_path, now_ns=62_000_000_000)


def test_clock_rollback_cannot_reopen_the_write_budget(tmp_path):
    runtime = load('camera_readiness')
    runtime.reserve_budget(tmp_path, now_ns=5_000_000_000)
    with pytest.raises(RuntimeError):
        runtime.reserve_budget(tmp_path, now_ns=4_000_000_000)


def test_slow_application_does_not_consume_the_post_readback_cooldown():
    plan = load('camera_environment').ExposureRecovery(dark_count=1, bright_count=1)
    observe_many(plan, 'UNDEREXPOSED', 0)
    plan.applied(monotonic=10, wall=1010)
    assert observe_many(plan, 'UNDEREXPOSED', 12) is None
    assert plan.state == 'COOLDOWN'


def test_temporal_brightness_changes_are_held_without_claiming_flicker_detection():
    plan = load('camera_environment').ExposureRecovery(dark_count=1, bright_count=1)
    for index in range(8):
        action = plan.observe('NORMAL', index/10, source_stamp=1000+index/10,
                              intensity=50 if index % 2 else 150)
        assert action is None
    assert plan.condition == 'TEMPORAL_CHANGE'
    assert not plan.snapshot()['flicker_verified']
