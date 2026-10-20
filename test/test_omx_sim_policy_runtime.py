"""HOST final-admission checks; no Gazebo or learned object success evidence."""
from dataclasses import replace
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/p) for p in ('middleware/robot_execution/local/test',
    'middleware/devices/omx/adapter/test', 'deploy/robot/omx')]
from test_omx_policy_session import setup_session, candidate
from test_policy_runtime_binding import runtime_methods, joint_message
from rosy.execution.local.policy_journal import PolicyExecutionJournal
from sim_policy_runtime import bind_sim_runtime


@pytest.mark.parametrize('target,readback,accepted', [
    (.139, .1, True), (.141, .1, False), (.135, .081, False)])
def test_step_uses_final_owner_readback(tmp_path, target, readback, accepted):
    journal = PolicyExecutionJournal(tmp_path/'policy.sqlite3')
    session, client, *_ = setup_session(tmp_path, execution_journal=journal)
    runtime = runtime_methods(session, client)
    bind_sim_runtime(session, runtime)
    message = joint_message(runtime)
    message.position = [readback, 0.]
    runtime._on_joint_state(message)
    original = candidate(session, sequence=10)
    result = session.submit(replace(original, positions=(target, 0.)))
    assert result.accepted is accepted
    assert len(client.commands) == int(accepted)


def test_existing_binding_cannot_be_replaced(tmp_path):
    journal = PolicyExecutionJournal(tmp_path/'policy.sqlite3')
    session, client, *_ = setup_session(tmp_path, execution_journal=journal)
    runtime = runtime_methods(session, client)
    session.bind_runtime(runtime)
    with pytest.raises(ValueError, match='already bound'):
        bind_sim_runtime(session, runtime)
