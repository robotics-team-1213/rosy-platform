from dataclasses import asdict, replace
import sqlite3
from uuid import uuid4
import ast
import threading
from typing import Callable

import pytest

from test_omx_policy_session import setup_session, candidate
from test_omx_policy_session import ROOT
from omx_adapter.ros_goal_contract import RosGoalEvent


def journal_type():
    from rosy.execution.local.policy_journal import PolicyExecutionJournal
    return PolicyExecutionJournal


def test_same_execution_preserves_original_goal_and_intent_before_transport(tmp_path):
    journal = journal_type()(tmp_path / 'policy.sqlite3')
    session, client, *_ = setup_session(tmp_path, execution_journal=journal)
    original_send = client.send_goal
    goal = str(uuid4())

    def send(command):
        intent = journal.read(command.command_id)['intent']
        assert intent['lease']['identity'] == asdict(session.lease.identity)
        assert intent['candidate']['sequence'] == command.source_state_sequence
        assert intent['policy_revision'] == session.lease.policy_revision
        assert intent['command']['positions'] == dict(command.positions)
        assert journal.read(command.command_id)['driver_goal_id'] is None
        assert journal.observe(RosGoalEvent('GOAL_ACCEPTED', command.command_id, None, goal, 10., 1)) is True
        return original_send(command)

    client.send_goal = send
    result = session.submit(candidate(session))
    journal.observe(RosGoalEvent('TERMINAL_RESULT', result.command_id, None, goal, 10.01, 2,
                                status=4, result_code=0))
    reopened = journal_type()(journal.path).read(result.command_id)
    assert reopened['driver_goal_id'] == goal != result.command_id
    assert [row['kind'] for row in reopened['events']] == ['GOAL_ACCEPTED', 'TERMINAL_RESULT']
    assert 'action_receipt' not in reopened


def test_failed_intent_commit_never_calls_transport(tmp_path):
    journal = journal_type()(tmp_path / 'policy.sqlite3')
    session, client, *_ = setup_session(tmp_path, execution_journal=journal)
    def fail(*args, **kwargs):
        raise sqlite3.OperationalError('disk full')
    journal.prepare = fail
    with pytest.raises(PermissionError):
        session.submit(candidate(session))
    assert not client.commands and session.hold_reason


def test_storage_delay_is_rechecked_before_transport(tmp_path):
    journal = journal_type()(tmp_path / 'policy.sqlite3')
    session, client, clock, *_ = setup_session(tmp_path, execution_journal=journal)
    original = journal.prepare
    def slow(*args, **kwargs):
        original(*args, **kwargs)
        clock[0] += 1
    journal.prepare = slow
    with pytest.raises(PermissionError):
        session.submit(candidate(session))
    assert not client.commands


@pytest.mark.parametrize('fault', ['unknown_command', 'wrong_goal', 'duplicate', 'after_terminal'])
def test_callback_mismatch_never_changes_original_record(tmp_path, fault):
    journal = journal_type()(tmp_path / 'policy.sqlite3')
    session, *_ = setup_session(tmp_path, execution_journal=journal)
    command = session.submit(candidate(session)).command_id
    goal = str(uuid4())
    journal.observe(RosGoalEvent('GOAL_ACCEPTED', command, None, goal, 10., 1))
    if fault == 'after_terminal':
        journal.observe(RosGoalEvent('TERMINAL_RESULT', command, None, goal, 10.01, 2,
                                    status=4, result_code=0))
    before = journal.read(command)
    event = RosGoalEvent('RUNNING_FEEDBACK',
        'unknown' if fault == 'unknown_command' else command, None,
        str(uuid4()) if fault == 'wrong_goal' else goal, 10.02,
        1 if fault == 'duplicate' else (3 if fault == 'after_terminal' else 2), feedback_sequence=1)
    with pytest.raises(ValueError):
        journal.observe(event)
    assert journal.read(command) == before


def test_rejected_goal_and_restart_never_invent_acceptance_or_replay(tmp_path):
    journal = journal_type()(tmp_path / 'policy.sqlite3')
    session, client, *_ = setup_session(tmp_path, execution_journal=journal)
    command = session.submit(candidate(session)).command_id
    journal.observe(RosGoalEvent('GOAL_REJECTED', command, None, None, 10., 1))
    reopened = journal_type()(journal.path)
    assert reopened.read(command)['driver_goal_id'] is None
    assert len(client.commands) == 1
    with pytest.raises(ValueError):
        reopened.observe(RosGoalEvent('GOAL_ACCEPTED', command, None, str(uuid4()), 10.01, 2))
    assert reopened.read(command)['driver_goal_id'] is None


def test_same_server_goal_cannot_be_rebound_to_another_command(tmp_path):
    journal = journal_type()(tmp_path / 'policy.sqlite3')
    session, client, clock, *_ = setup_session(tmp_path, execution_journal=journal)
    first = session.submit(candidate(session)).command_id
    goal = str(uuid4())
    journal.observe(RosGoalEvent('GOAL_ACCEPTED', first, None, goal, 10., 1))
    # Duplicate command intent cannot replace the original scope after restart.
    intent_before = journal.read(first)
    with pytest.raises(sqlite3.IntegrityError):
        journal.prepare(session.lease, candidate(session), client.commands[0])
    assert journal.read(first) == intent_before
    second = replace(client.commands[0], command_id=str(uuid4()), source_state_sequence=11)
    journal.prepare(session.lease, candidate(session, sequence=11), second)
    with pytest.raises(sqlite3.IntegrityError):
        journal.observe(RosGoalEvent('GOAL_ACCEPTED', second.command_id, None, goal, 10.01, 1))
    assert journal.read(second.command_id)['events'] == []
    assert journal.read(second.command_id)['driver_goal_id'] is None


def test_original_runtime_dispatch_method_accepts_committed_sink_and_clears_terminal(tmp_path):
    # Execute unchanged dispatch methods from the actual ROS runtime source,
    # without importing unavailable rclpy. This is a host method seam, not ROS.
    file = ROOT / 'middleware/apps/device/omx/adapter/omx_adapter/ros_runtime.py'
    tree = ast.parse(file.read_text(encoding='utf-8'))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef)
               and node.name == 'RosArmCommandRuntime')
    names = {'register_phase_event_sink', 'unregister_phase_event_sink', '_dispatch_goal_event'}
    cls.body = [node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name in names]
    module = ast.Module(body=[cls], type_ignores=[])
    scope = dict(RosGoalEvent=RosGoalEvent, Callable=Callable)
    exec(compile(module, str(file), 'exec'), scope)
    runtime = scope['RosArmCommandRuntime'].__new__(scope['RosArmCommandRuntime'])
    runtime._goal_event_lock = threading.RLock()
    runtime._phase_event_sinks = {}
    observed = []
    runtime._observer_goal_event = observed.append
    journal = journal_type()(tmp_path / 'policy.sqlite3')
    session, *_ = setup_session(tmp_path, execution_journal=journal)
    command = session.submit(candidate(session)).command_id
    runtime.register_phase_event_sink(command, journal.observe)
    goal = str(uuid4())
    runtime._dispatch_goal_event(RosGoalEvent('GOAL_ACCEPTED', command, None, goal, 10., 1))
    runtime._dispatch_goal_event(RosGoalEvent('TERMINAL_RESULT', command, None, goal, 10.01, 2,
                                            status=4, result_code=0))
    assert len(observed) == len(journal.read(command)['events']) == 2
    assert command not in runtime._phase_event_sinks


def test_reopened_journal_denies_same_candidate_with_new_command_or_lease_id(tmp_path):
    journal = journal_type()(tmp_path / 'policy.sqlite3')
    session, client, *_ = setup_session(tmp_path, execution_journal=journal)
    original = session.submit(candidate(session)).command_id
    second = replace(client.commands[0], command_id=str(uuid4()))
    renewed = replace(session.lease, lease_id='renewed')
    reopened = journal_type()(journal.path)
    with pytest.raises(sqlite3.IntegrityError):
        reopened.prepare(renewed, candidate(session, lease_id='renewed'), second)
    assert reopened.read(original)['driver_goal_id'] is None
    with pytest.raises(KeyError):
        reopened.read(second.command_id)


@pytest.mark.parametrize('missing', ['intent_unique', 'goal_unique', 'event_pk', 'event_fk'])
def test_existing_schema_without_actual_constraints_is_rejected(tmp_path, missing):
    path = tmp_path / 'malformed.sqlite3'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE policy_commands(command_id TEXT PRIMARY KEY, intent TEXT NOT NULL, '
                   'intent_key TEXT NOT NULL' + ('' if missing == 'intent_unique' else ' UNIQUE') +
                   ', driver_goal_id TEXT' + ('' if missing == 'goal_unique' else ' UNIQUE') + ')')
        db.execute('CREATE TABLE policy_goal_events(command_id TEXT NOT NULL' +
                   ('' if missing == 'event_fk' else ' REFERENCES policy_commands(command_id)') +
                   ', sequence INTEGER NOT NULL, payload TEXT NOT NULL' +
                   ('' if missing == 'event_pk' else ', PRIMARY KEY(command_id,sequence)') + ')')
    with pytest.raises(RuntimeError):
        journal_type()(path)
