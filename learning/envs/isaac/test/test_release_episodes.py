"""Short release episodes: prior stack initialised at its targets, held box regrasped from the table."""
import math
from pathlib import Path
import sys

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import mapped_stack_fixture as f
import release_corrector as rc
import release_episodes as re_


def test_episode_case_runs_bounded_rl_episodes_with_the_pinned_corrector_and_residual():
    fixture = f.container_fixture(layers=3, case='release-episodes-rl0')
    assert fixture['release_episodes'] == 40
    assert fixture['release_corrector']['sha256'] == f.EVALUATION_CASES['nominal-bc-v0']['sha256']
    assert fixture['release_residual'] == {k: v for k, v in f.RL_RESIDUALS['nominal-bc-v0-rl0'].items() if k != 'sigma_m'}
    assert fixture['release_exploration_sigma_m'] == .0002 and fixture['release_convergence_m'] == .0015


def test_layout_puts_the_prior_stack_near_its_targets_and_the_held_box_flat_on_the_table():
    fixture = f.container_fixture(layers=3, case='release-episodes-rl0')
    items = f.plan(True, fixture=fixture)
    seen = set()
    for seed in range(60):
        layout = re_.layout(fixture, np.random.default_rng(seed))
        index = layout['index']
        seen.add(index)
        assert len(layout['prior']) == index
        for j, (position, yaw) in enumerate(layout['prior']):
            assert np.abs(np.subtract(position[:2], items[j]['target'][:2])).max() <= .001 + 1e-12
            assert position[2] == pytest.approx(items[j]['target'][2]+.0005) and abs(yaw-math.pi) <= .01
        position, yaw = layout['held']
        centre, size = fixture['leveling_center_m'], fixture['leveling_size_m']
        assert abs(position[0]-centre[0]) <= .005 and abs(position[1]-centre[1]) <= .005 and abs(yaw-math.pi) <= .05
        assert position[2] == pytest.approx(centre[2]+.015)
        assert abs(position[0]-centre[0]) + .045 <= size[0]/2  # stays on the leveling table
    assert seen == set(range(9))


def test_quaternion_is_a_yaw_about_z():
    q = re_.yaw_quaternion(.3)
    assert q == pytest.approx([math.cos(.15), 0., 0., math.sin(.15)])


def test_episode_rows_feed_rl_with_settled_or_blocked_rewards():
    decision = dict(iteration=1, observation=[0.]*rc.FEATURES, noise=[1., 0., 0.])
    outcome = dict(position_error_mm=.4, stable=True, gaps_mm=[3.5])
    report = dict(trials=[dict(layers=[], episodes=[
        dict(index=3, decisions=[decision], outcome=outcome),
        dict(index=5, decisions=[decision], outcome=None, error='opening blocked')])])
    assert re_.episode_rows(report) == [([0.]*rc.FEATURES, [1., 0., 0.], rc.release_reward(outcome)),
                                        ([0.]*rc.FEATURES, [1., 0., 0.], rc.BLOCKED_REWARD)]
