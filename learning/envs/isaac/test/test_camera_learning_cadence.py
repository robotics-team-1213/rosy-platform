"""A camera action lasts for an observation interval, with measured credit."""
import importlib.util
from pathlib import Path

import pytest


@pytest.fixture
def window():
    path = Path(__file__).resolve().parents[4] / 'tools/sim/isaac/camera_checks.py'
    spec = importlib.util.spec_from_file_location('cadence_checks', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    cls = getattr(module, 'CameraLearningWindow', None)
    assert cls is not None, 'Camera learning needs an observation interval, not a physics tick'
    return cls()


class Policy:
    def __init__(self):
        self.choices = []
        self.updates = []

    def choose(self, state, *, explore):
        self.choices.append((state, explore))
        return len(self.choices) % 4

    def update(self, *args, **kwargs):
        self.updates.append((args, kwargs))


def result(reward, **overrides):
    return dict(reward=reward, terminated=False, truncated=False, reason='running', **overrides)


def receipt(state, action, frame):
    return dict(state=state, action=action, frame=frame, twist=(.01, .04))


def test_same_image_holds_action_and_next_image_sums_rewards(window):
    policy = Policy()
    state = (1, 2)
    action = window.choose(policy, state, 1., frame=10, train=True)
    window.learn(policy, state, result(99.), credit=None)
    for frame in range(11, 34):
        assert window.choose(policy, state, 1., frame=frame, train=True) == action
        assert window.learn(policy, state, result(.01), credit=receipt(state, action, frame-1)) == 'waiting_camera'
    assert len(policy.choices) == 1 and policy.updates == []
    window.choose(policy, (2, 2), 1.1, frame=34, train=True)
    assert window.learn(policy, (2, 2), result(.02), credit=receipt(state, action, 33)) == 'updated'
    args, flags = policy.updates[0]
    assert args[:2] == (state, action)
    assert args[2] == pytest.approx(.25)
    assert args[3] == (2, 2) and flags == {'terminated': False}


def test_zero_only_interval_does_not_reuse_old_receipt(window):
    policy = Policy()
    state = (1, 2)
    action = window.choose(policy, state, 1., frame=10, train=True)
    window.learn(policy, state, result(0.), credit=None)
    window.choose(policy, state, 1.1, frame=34, train=True)
    window.learn(policy, state, result(1.), credit=receipt(state, action, 9))
    assert policy.updates == []


def test_terminal_loss_once(window):
    policy = Policy()
    state = (1, 2)
    action = window.choose(policy, state, 1., frame=10, train=True)
    window.learn(policy, state, result(0.), credit=None)
    window.choose(policy, None, 1., frame=11, train=True)
    terminal = dict(reward=-10., terminated=True, truncated=False, reason='camera_lane_lost',
                    camera_failure_reason='camera_target_unavailable')
    assert window.learn(policy, None, terminal, credit=receipt(state, action, 10)) == 'terminal_camera_loss'
    window.learn(policy, None, terminal, credit=receipt(state, action, 10))
    assert len(policy.updates) == 1 and policy.updates[0][1]['terminated']


def test_eval_selects_once_and_invalid_stamp_fails_closed(window):
    policy = Policy()
    state = (1, 2)
    chosen = window.choose(policy, state, 1., frame=10, train=False)
    assert window.choose(policy, state, 1., frame=11, train=False) == chosen
    assert policy.choices == [(state, False)] and policy.updates == []
    with pytest.raises(ValueError):
        window.choose(policy, state, .9, frame=12, train=False)


@pytest.mark.parametrize('cause,credit', [
    ('camera_source_stale', receipt((1, 2), 1, 10)),
    ('camera_inference_error', receipt((1, 2), 1, 10)),
    ('camera_target_unavailable', None),
])
def test_external_failure_or_broken_credit_does_not_train(window, cause, credit):
    policy = Policy()
    window.choose(policy, (1, 2), 1., frame=10, train=True)
    window.learn(policy, (1, 2), result(0.), credit=None)
    terminal = dict(reward=-10., terminated=True, truncated=False, reason='camera_lane_lost',
                    camera_failure_reason=cause)
    window.choose(policy, None, 1., frame=11, train=True)
    window.learn(policy, None, terminal, credit=credit)
    assert policy.updates == [] and window.ended


def test_baseline_does_not_explore_and_episode_starts_without_credit(window):
    policy = Policy()
    assert window.choose(policy, (1, 2), 1., frame=10, train=False, baseline=True) == 1
    assert window.choose(policy, (2, 2), 1.1, frame=34, train=False, baseline=True) == 1
    assert policy.choices == [] and policy.updates == []
    fresh = type(window)()
    fresh.choose(policy, (1, 2), .1, frame=0, train=True)
    fresh.learn(policy, (1, 2), result(100.), credit=None)
    assert policy.updates == []


def test_interrupted_interval_credits_only_confirmed_resumed_suffix(window):
    policy = Policy()
    state = (1, 2)
    action = window.choose(policy, state, 1., frame=10, train=True)
    window.learn(policy, state, result(0.), credit=None)
    for frame, reward, credit in (
            (11, 4., receipt(state, action, 10)),
            (12, 99., None), (13, 777., None),
            (14, 2., receipt(state, action, 13))):
        window.choose(policy, state, 1., frame=frame, train=True)
        window.learn(policy, state, result(reward), credit=credit)
    window.choose(policy, state, 1.1, frame=34, train=True)
    window.learn(policy, state, result(3.), credit=receipt(state, action, 14))
    assert len(policy.updates) == 1
    assert policy.updates[0][0][2] == 5.
    assert window.last_update['reward'] == 5.


def test_boundary_selection_precedes_update_without_reassigning_old_credit(window):
    class ResponsivePolicy(Policy):
        def choose(self, state, *, explore):
            return 0 if self.updates else 1
    policy = ResponsivePolicy()
    state = (1, 2)
    assert window.choose(policy, state, 1., frame=10, train=True) == 1
    window.learn(policy, state, result(0.), credit=None)
    assert window.choose(policy, state, 1.1, frame=34, train=True) == 1
    window.learn(policy, state, result(-10.), credit=receipt(state, 1, 33))
    assert policy.updates[0][0][:3] == (state, 1, -10.)
    assert window.choose(policy, state, 1.2, frame=58, train=True) == 0
