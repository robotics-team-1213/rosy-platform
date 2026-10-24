"""GoalEscape gates on real values (D-171 track 1).

The escape mixin imported std_msgs and had no host test at all. GoalNode now
owns its topics and publish_escape; a plain subclass stands in for the node.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from control import goal_escape
from control.goal_escape import GoalEscape


def test_escape_runtime_source_is_owned_by_drive():
    assert Path(goal_escape.__file__).resolve().parent == Path(__file__).resolve().parents[2] / 'drive/runtime'


def test_escape_imports_from_built_distribution_outside_checkout(tmp_path):
    stage = tmp_path / 'installed'
    result = subprocess.run([sys.executable, 'setup.py', 'build_py', '--build-lib', str(stage)],
                            cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    code = ('from control.goal_escape import GoalEscape; import control, sys; from pathlib import Path; '
            'assert Path(control.__file__).resolve().is_relative_to(Path(sys.argv[1]))')
    result = subprocess.run([sys.executable, '-c', code, str(stage)], cwd=tmp_path,
                            env={**os.environ, 'PYTHONPATH': str(stage)}, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


class FakeGoal(GoalEscape):
    def __init__(self, now_s=100.):
        self.now_s = now_s
        self.published = []
        self.cleared = []
        self.params = {'use_sim_time': True}
        self.init_escape()

    def get_clock(self):
        return SimpleNamespace(now=lambda: SimpleNamespace(nanoseconds=int(self.now_s * 1e9)))

    def get_parameter(self, name):
        return SimpleNamespace(value=self.params[name])

    def publish_escape(self, intent):
        self.published.append(intent)

    def _clear_route(self, reason):
        self.cleared.append(reason)


def active(node, target=(1., 2.)):
    node.escape_intent = {'id': 'e1', 'target': list(target), 'yaw': 0., 'geometry': 'geom-A'}
    node.escape_budget.begin('e1', node.now_s)


def result(**over):
    value = {'id': 'e1', 'geometry': 'geom-A', 'status': 'complete', 'issued_s': 99.8, 'pose': [1.001, 2.001]}
    value.update(over)
    return SimpleNamespace(data=json.dumps(value))


def test_module_is_ros_free():
    assert not hasattr(goal_escape, 'String')
    assert 'publish_escape' not in vars(GoalEscape)       # the node owns the message edge


def test_matching_fresh_result_completes_the_escape():
    node = FakeGoal()
    active(node)
    node.on_escape_result(result())
    assert node.escape_intent is None
    assert node.published == [None]


@pytest.mark.parametrize('over', [
    {'id': 'other'}, {'geometry': 'geom-B'}, {'status': 'failed'},
    {'issued_s': 99.4}, {'issued_s': 100.1},                 # older than 0.5 s / from the future
    {'pose': [1.004, 2.]}, {'pose': [1.]}, {'pose': [float('nan'), 2.]},
])
def test_mismatched_or_stale_result_is_ignored(over):
    node = FakeGoal()
    active(node)
    node.on_escape_result(result(**over))
    assert node.escape_intent is not None and node.published == []


def test_result_without_an_active_intent_or_malformed_is_ignored():
    node = FakeGoal()
    node.on_escape_result(result())
    node.on_escape_result(SimpleNamespace(data='not json'))
    assert node.published == []


def test_limits_are_parsed_or_cleared():
    node = FakeGoal()
    node.on_escape_limits(SimpleNamespace(data=json.dumps({'bounded_motion_enabled': True})))
    assert node.escape_limits == {'bounded_motion_enabled': True} and node.escape_seen is not None
    node.on_escape_limits(SimpleNamespace(data='{'))
    assert node.escape_limits is None


def test_no_escape_unless_the_planner_reports_the_robot_inside_clearance():
    node = FakeGoal()
    assert node.escape_plan(None, (0., 0., 0.), status='planning blocked: no frontier') is False
    assert node.published == [] and node.cleared == []


def test_active_escape_outside_the_isolated_rig_is_abandoned_and_stopped(monkeypatch):
    monkeypatch.delenv('ROS_DOMAIN_ID', raising=False)
    node = FakeGoal()
    active(node)
    assert node.escape_plan(None, (0., 0., 0.)) is True
    assert node.escape_intent is None and node.escape_budget.failed is True
    assert node.published == [None]
    assert node.cleared == ['planning blocked: straight escape evidence lost']
