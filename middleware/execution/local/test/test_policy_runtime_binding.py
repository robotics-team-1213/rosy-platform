"""HOST composition using unchanged runtime methods; no ROS/DDS acceptance."""
import __future__
import ast
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Callable, Any
import threading
from uuid import uuid4

import pytest

from test_omx_policy_session import setup_session, candidate, ROOT
from rosy.execution.local.policy_journal import PolicyExecutionJournal
from omx_adapter.command_owner import JointStateSnapshot, CommandDecision
from omx_adapter.ros_goal_contract import RosGoalEvent


def runtime_methods(session, client):
    file = ROOT / 'middleware/apps/device/omx/adapter/omx_adapter/ros_runtime.py'
    tree = ast.parse(file.read_text(encoding='utf-8'))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef)
               and node.name == 'RosArmCommandRuntime')
    names = {'bind_policy_driver', 'register_phase_event_sink', 'unregister_phase_event_sink',
             '_dispatch_goal_event', '_on_joint_state', '_watchdog_tick', 'submit', '_submit_policy'}
    cls.body = [node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name in names]
    scope = dict(RosGoalEvent=RosGoalEvent, Callable=Callable, JointStateSnapshot=JointStateSnapshot,
                 CommandDecision=CommandDecision, JointState=Any)
    exec(compile(ast.Module(body=[cls], type_ignores=[]), str(file), 'exec',
                 flags=__future__.annotations.compiler_flag, dont_inherit=True), scope)
    runtime = scope['RosArmCommandRuntime'].__new__(scope['RosArmCommandRuntime'])
    runtime.owner = session.owner
    runtime.action_port = client
    session._clock = session.owner._monotonic
    runtime.monotonic = session._clock
    runtime.owner_clock = 'steady'
    runtime.poll_period_s = .02
    runtime._policy_binding = None
    runtime._goal_event_lock = threading.RLock()
    runtime._phase_event_sinks = {}
    runtime._observer_goal_event = None
    runtime._sequence = 10
    runtime.latest_joint_state = None
    runtime.last_terminal_decision = None
    runtime.last_decision = CommandDecision(True, 'ready', 'ready')
    client.last_handle = None
    return runtime


def attached(tmp_path, camera=False):
    journal = PolicyExecutionJournal(tmp_path / 'policy.sqlite3')
    session, client, clock, authority, root = setup_session(tmp_path, execution_journal=journal, camera=camera)
    runtime = runtime_methods(session, client)
    session.bind_runtime(runtime)
    return session, runtime, client, clock, authority, journal, root


def test_same_runtime_observes_once_registers_before_send_and_preserves_source_bytes(tmp_path):
    session, runtime, client, clock, authority, journal, root = attached(tmp_path)
    runtime._on_joint_state(SimpleNamespace(name=['joint_1','joint_2'], position=[.1, 0.]))
    assert session._snapshot.sequence == session.owner._joint_state.sequence == 11
    assert session.owner.state == 'ready'
    send = client.send_goal
    goal = str(uuid4())
    def native_send(command):
        assert command.command_id in runtime._phase_event_sinks
        intent = journal.read(command.command_id)['intent']
        source = journal.read_source(intent['source_revision'])
        assert source['payloads']['policy/policy-artifact.json'] == (root/'policy-artifact.json').read_bytes()
        assert source['payloads']['policy/model.bin'] == b'host-fixture'
        assert source['header']['policy_revision'] == session.lease.policy_revision
        runtime._dispatch_goal_event(RosGoalEvent('GOAL_ACCEPTED',command.command_id,None,goal,10.,1))
        return send(command)
    client.send_goal = native_send
    result = session.submit(candidate(session, sequence=11))
    runtime._dispatch_goal_event(RosGoalEvent('TERMINAL_RESULT',result.command_id,None,goal,10.01,2,
                                            status=4,result_code=0))
    assert journal.read(result.command_id)['driver_goal_id'] == goal != result.command_id
    assert result.command_id not in runtime._phase_event_sinks
    assert len(client.commands) == 1


def test_watchdog_rechecks_revoked_lease_and_cancels(tmp_path):
    session, runtime, client, clock, authority, *_ = attached(tmp_path)
    session.submit(candidate(session))
    authority[0] = False
    runtime._watchdog_tick()
    assert session.hold_reason and session.owner.state == 'hold'
    assert client.handles[0].cancel_calls == 1


@pytest.mark.parametrize('mutation', ['authority', 'artifact'])
def test_revocation_during_send_cancels_and_preserves_late_native_events(tmp_path, mutation):
    session, runtime, client, _, authority, journal, root = attached(tmp_path)
    send = client.send_goal
    def changed_send(command):
        handle = send(command)
        if mutation == 'authority':authority[0] = False
        else:(root/'model.bin').write_bytes(b'replaced')
        return handle
    client.send_goal = changed_send
    with pytest.raises(PermissionError):session.submit(candidate(session))
    assert session.hold_reason and session.owner.state == 'hold'
    assert client.handles[0].cancel_calls == 1
    command = client.commands[0]
    assert command.command_id in runtime._phase_event_sinks
    goal = str(uuid4())
    runtime._dispatch_goal_event(RosGoalEvent('GOAL_ACCEPTED', command.command_id,None,goal,10.,1))
    assert journal.read(command.command_id)['driver_goal_id'] == goal


def test_fresh_replacement_camera_does_not_refresh_original_candidate_camera(tmp_path):
    from rosy.execution.local.omx_policy import CameraSnapshot
    session, runtime, client, clock, *_ = attached(tmp_path, camera=True)
    original = CameraSnapshot('front','cam-front','a'*64,(3,2,2),9_980_000_000,'c'*64)
    current = [original]
    session._cameras = lambda:tuple(current)
    session.capture_observation()
    send = client.send_goal
    def replace_camera(command):
        handle = send(command)
        clock[0] = 10.04
        current[0] = replace(original,received_at_ns=10_040_000_000,frame_sha256='d'*64)
        return handle
    client.send_goal = replace_camera
    with pytest.raises(PermissionError):
        session.submit(candidate(session,camera_frames=('c'*64,),camera_received_at_ns=(9_980_000_000,)))
    assert session.hold_reason == 'policy_camera_source_stale'
    assert session.owner.state == 'hold' and client.handles[0].cancel_calls == 1
    assert client.commands[0].command_id in runtime._phase_event_sinks


@pytest.mark.parametrize('path', ['runtime', 'owner'])
def test_raw_command_bypasses_are_denied(tmp_path, path):
    session, runtime, client, *_ = attached(tmp_path)
    result = session.submit(candidate(session))
    client.handles[0].finished = client.handles[0].success = True
    runtime._watchdog_tick()
    assert session.owner.state == 'ready'
    runtime._on_joint_state(SimpleNamespace(name=['joint_1','joint_2'],position=[.1,0.]))
    command = replace(client.commands[0], command_id=str(uuid4()), source_state_sequence=11)
    denied = runtime.submit(command) if path == 'runtime' else session.owner.submit(command)
    assert not denied.accepted
    assert denied.reason == ('policy_session_required' if path == 'runtime' else 'control_seat_fenced')
    assert len(client.commands) == 1


@pytest.mark.parametrize('change', ['clock', 'sim_clock', 'owner', 'port', 'slow_poll'])
def test_wrong_runtime_binding_blocks_attach(tmp_path, change):
    journal = PolicyExecutionJournal(tmp_path / 'policy.sqlite3')
    session, client, *_ = setup_session(tmp_path, execution_journal=journal)
    runtime = runtime_methods(session, client)
    if change == 'clock': runtime.monotonic = lambda:10.
    if change == 'sim_clock': runtime.owner_clock = 'sim'
    if change == 'owner': runtime.owner = object()
    if change == 'port': runtime.action_port = object()
    if change == 'slow_poll': runtime.poll_period_s = .5
    with pytest.raises(ValueError): session.bind_runtime(runtime)
    assert not client.commands


def test_fast_callback_failure_cannot_be_overwritten_by_owner_submission(tmp_path):
    session, runtime, client, _, _, journal, _ = attached(tmp_path)
    send = client.send_goal
    def native_send(command):
        handle = send(command)
        with pytest.raises(ValueError):
            runtime._dispatch_goal_event(RosGoalEvent('RUNNING_FEEDBACK',command.command_id,None,
                str(uuid4()),10.,1,feedback_sequence=1))
        return handle
    client.send_goal = native_send
    with pytest.raises(PermissionError): session.submit(candidate(session))
    assert session.owner.state == 'hold' and session.hold_reason
    assert client.handles[0].cancel_calls == 1


def test_registration_delay_rechecked_and_unused_sink_removed(tmp_path):
    session, runtime, client, clock, *_ = attached(tmp_path)
    register = runtime.register_phase_event_sink
    def slow(command_id, sink):
        register(command_id, sink)
        clock[0] += 1
    runtime.register_phase_event_sink = slow
    with pytest.raises(PermissionError): session.submit(candidate(session))
    assert not client.commands and not runtime._phase_event_sinks


def test_captured_installed_bytes_survive_original_file_loss(tmp_path):
    session, runtime, client, clock, authority, journal, root = attached(tmp_path)
    revision = session._runtime_binding.source_revision
    (root/'model.bin').unlink()
    source = PolicyExecutionJournal(journal.path).read_source(revision)
    assert source['payloads']['policy/model.bin'] == b'host-fixture'
    with pytest.raises(PermissionError): session.submit(candidate(session))
    assert not client.commands


@pytest.mark.parametrize('field', ['action_port','monotonic','owner_clock','poll_period_s','owner'])
def test_runtime_rebinding_latches_without_dispatch(tmp_path, field):
    session, runtime, client, *_ = attached(tmp_path)
    setattr(runtime,field,object())
    with pytest.raises(PermissionError): session.submit(candidate(session))
    assert not client.commands and session.hold_reason


def test_second_attach_and_active_attach_are_rejected(tmp_path):
    session, runtime, client, *_ = attached(tmp_path)
    with pytest.raises(ValueError): session.bind_runtime(runtime)
    journal = PolicyExecutionJournal(tmp_path/'other'/'journal.sqlite3')
    other, other_client, *_ = setup_session(tmp_path/'other', execution_journal=journal)
    other.submit(candidate(other))
    with pytest.raises(ValueError): other.bind_runtime(runtime_methods(other,other_client))


def test_source_payload_corruption_is_not_read_back_as_valid(tmp_path):
    import sqlite3
    session, runtime, client, _, _, journal, _ = attached(tmp_path)
    with sqlite3.connect(journal.path) as db:
        db.execute("UPDATE policy_source_files SET payload=? WHERE path='policy/model.bin'",(b'changed',))
    with pytest.raises(ValueError): journal.read_source(session._runtime_binding.source_revision)
