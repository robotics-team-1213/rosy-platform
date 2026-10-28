"""D-657 ownership and ROS/DB-free execution contract, with real consumer regressions elsewhere."""

import ast
from datetime import datetime, timezone
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / 'operations/site_execution/src/rosy/execution/site'


def test_decision_no_longer_owns_fleet_store_dispatch():
    decision = ROOT / 'operations/decision/src/rosy/decision'
    assert not (decision / 'tool_dispatch.py').exists()
    assert (ROOT / 'operations/fleet/fleet/server/evidence/model_feedback_dispatch.py').is_file()
    for path in decision.glob('*.py'):
        for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
            modules = ([node.module or ''] if isinstance(node, ast.ImportFrom) else
                       [item.name for item in node.names] if isinstance(node, ast.Import) else [])
            assert not any(name == 'fleet' or name.startswith('fleet.') for name in modules), path


def test_execution_rules_import_without_fleet_or_device_dependencies():
    probe = r'''
import importlib.abc
import sys
class RefuseIO(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'fleet', 'sqlite3', 'httpx', 'rclpy', 'core', 'core_common'}:
            raise AssertionError('pure execution imported ' + fullname)
sys.meta_path.insert(0, RefuseIO())
sys.path.insert(0, sys.argv[1])
from rosy.execution.site.goal_evidence import GoalPredicate, GoalEvidenceError
from rosy.execution.site.workflow import mission_step_state, project_progress
assert callable(project_progress)
assert mission_step_state('ACTION_SUCCEEDED') == 'AWAITING_GOAL_EVIDENCE'
assert GoalPredicate.from_mapping(dict(predicate_id='p', condition='object_in_destination',
    object_id='o', destination_id='d', evidence_source='camera_observation')).object_id == 'o'
'''
    result = subprocess.run([sys.executable, '-I', '-c', probe,
                             str(ROOT / 'operations/site_execution/src')],
                            cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize('status, expected', [
    ('PROPOSED', 'NOT_ADMITTED'), ('READY', 'READY'), ('RUNNING', 'RUNNING'),
    ('ACTION_SUCCEEDED', 'AWAITING_GOAL_EVIDENCE'), ('GOAL_CONFIRMED', 'COMPLETED'),
    ('HOLD', 'HOLD'), ('CANCELED', 'CANCELED'), ('unrecognized', 'UNKNOWN'),
])
def test_workflow_never_confuses_action_acceptance_with_goal_success(status, expected):
    sys.path.insert(0, str(ROOT / 'operations/site_execution/src'))
    try:
        from rosy.execution.site.workflow import mission_step_state
        assert mission_step_state(status) == expected
    finally:
        sys.path.pop(0)


def test_progress_freshness_keeps_existing_boundary_and_invalid_time_rules():
    sys.path.insert(0, str(ROOT / 'operations/site_execution/src'))
    try:
        from rosy.execution.site.workflow import _freshness, _timestamp
        now = datetime.fromtimestamp(100, timezone.utc)
        assert _freshness(_timestamp(85), now=now, max_age_s=15) == 'FRESH'
        assert _freshness(_timestamp(84.999), now=now, max_age_s=15) == 'STALE'
        assert _freshness(_timestamp(101), now=now, max_age_s=15) == 'STALE'
        for value in (None, True, float('nan'), float('inf'), 10**1000, 'invalid', datetime(2026, 1, 1)):
            assert _freshness(_timestamp(value), now=now, max_age_s=15) == 'UNKNOWN'
        assert _timestamp('1970-01-01T00:01:40') == now
    finally:
        sys.path.pop(0)
