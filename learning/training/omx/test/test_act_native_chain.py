"""Opt-in actual CPU/native chain; synthetic weights/capture, no physical robot."""
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
sys.path[:0] = [str(ROOT/'middleware/robot_execution/local/test'),
               str(ROOT/'middleware/devices/omx/adapter/test')]
pytest.importorskip('rclpy', reason='isolated Jazzy ROS transport required')
pytest.importorskip('torch', reason='actual CPU numerical model required')
pytest.importorskip('lerobot', reason='pinned local ACT SDK required')
from test_policy_runtime_ros import test_native_session_goal_facts_and_revocation as run_native

pytestmark = pytest.mark.skipif(os.environ.get('ROS_DOMAIN_ID') != '199' or not (
    os.environ.get('ROS_LOCALHOST_ONLY') == '1' or
    os.environ.get('ROS_AUTOMATIC_DISCOVERY_RANGE') == 'LOCALHOST'),
    reason='explicit isolated domain199/localhost required')


@pytest.mark.parametrize('revoke', [False, True])
def test_actual_cpu_result_to_same_native_parent_episode_fleet(tmp_path, revoke):
    run_native(tmp_path, revoke, True, with_inference=True)
