"""Opt-in CORE HTTP to native ROS action/cancel; synthetic inputs, no real robot."""
import pytest

pytest.importorskip('rclpy', reason='isolated Jazzy transport required')
from test_policy_runtime_ros import test_native_session_goal_facts_and_revocation as run_native


@pytest.mark.parametrize('revoke', [False, True])
def test_core_gateway_to_native_owner(tmp_path, revoke):
    run_native(tmp_path, revoke, False, with_core=True)
