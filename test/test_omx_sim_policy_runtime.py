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
    (.139, .1, True), (.141, .1, False), (.1399, .0995, False)])
def test_step_uses_final_owner_readback(tmp_path, monkeypatch, target, readback, accepted):
    journal = PolicyExecutionJournal(tmp_path/'policy.sqlite3')
    session, client, *_ = setup_session(tmp_path, execution_journal=journal)
    runtime = runtime_methods(session, client)
    bind_sim_runtime(session, runtime)
    message = joint_message(runtime)
    message.position = [readback, 0.]
    runtime._on_joint_state(message)
    original = candidate(session, sequence=10)
    checked = []
    check = session._runtime_binding.check_command
    def trace(command):
        result = check(command)
        checked.append(result)
        return result
    monkeypatch.setattr(session._runtime_binding, 'check_command', trace)
    proposed = replace(original, positions=(target, 0.))
    if accepted:
        assert session.submit(proposed).accepted
    else:
        with pytest.raises(PermissionError):
            session.submit(proposed)
        assert session.hold_reason
    assert checked and checked[-1] is accepted
    assert len(client.commands) == int(accepted)


def test_existing_binding_cannot_be_replaced(tmp_path):
    journal = PolicyExecutionJournal(tmp_path/'policy.sqlite3')
    session, client, *_ = setup_session(tmp_path, execution_journal=journal)
    runtime = runtime_methods(session, client)
    session.bind_runtime(runtime)
    with pytest.raises(ValueError, match='already bound'):
        bind_sim_runtime(session, runtime)


def test_revocation_at_final_native_admission_sends_no_new_goal(tmp_path,monkeypatch):
    journal=PolicyExecutionJournal(tmp_path/'policy.sqlite3')
    session,client,_,authority,*_=setup_session(tmp_path,execution_journal=journal)
    runtime=runtime_methods(session,client)
    bind_sim_runtime(session,runtime)
    submit=runtime._submit_policy
    def revoke_at_edge(command,binding):
        authority[0]=False
        return submit(command,binding)
    monkeypatch.setattr(runtime,'_submit_policy',revoke_at_edge)
    with pytest.raises(PermissionError):session.submit(candidate(session))
    assert not client.commands and session.hold_reason
