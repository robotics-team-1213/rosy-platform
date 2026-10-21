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
@pytest.mark.parametrize('traced',[False,True])
def test_step_uses_final_owner_readback(tmp_path, monkeypatch, target, readback, accepted,traced):
    journal = PolicyExecutionJournal(tmp_path/'policy.sqlite3')
    session, client, *_ = setup_session(tmp_path, execution_journal=journal)
    runtime = runtime_methods(session, client)
    bind_sim_runtime(session, runtime)
    if traced:
        from sim_policy_runtime import trace_sim_admission
        admission_trace=trace_sim_admission(session,journal,runtime)
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
        rejection=session._runtime_binding.admission_rejection
        assert rejection['reason']=='readback_step'
        assert rejection['positions']['joint_1']==readback
        assert rejection['max_step_rad']==pytest.approx(abs(target-readback))
        assert rejection['command_id']
        assert session._runtime_binding.check_command(object()) is False
        assert session._runtime_binding.admission_rejection is rejection
    assert checked and checked[-1] is accepted
    assert len(client.commands) == int(accepted)
    if traced:
        assert admission_trace and all(row['ended_owner_ns']>=row['started_owner_ns'] for row in admission_trace)
        assert all(row['thread_id']>0 for row in admission_trace)
        assert any(row['stage']=='guard' for row in admission_trace)
        assert any(row['stage']=='journal_prepare' for row in admission_trace)
        if accepted:
            assert any(row['stage']=='native_send' and row['outcome']=='returned' for row in admission_trace)
        else:
            assert any(row['outcome']=='raised' for row in admission_trace)


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


@pytest.mark.parametrize('broken_diagnostic', [False, True])
def test_failed_guard_trace_preserves_original_joint_receipts_and_exception(tmp_path,monkeypatch,broken_diagnostic):
    from sim_policy_runtime import trace_sim_admission
    from omx_adapter.watchdog_observation import JointIntakeObservation
    journal=PolicyExecutionJournal(tmp_path/'policy.sqlite3')
    session,client,*_=setup_session(tmp_path,execution_journal=journal)
    runtime=runtime_methods(session,client)
    bind_sim_runtime(session,runtime)
    original=session._snapshot
    runtime.latest_joint_state=original
    intake=JointIntakeObservation(10,11,10.,10.,10.,10.,True,10,None)
    runtime.owner.joint_intake_observation=intake
    failure=PermissionError('original stale failure')
    class BrokenSnapshot:
        @property
        def sequence(self):raise RuntimeError('diagnostic unavailable')
    def fail():
        runtime.latest_joint_state=(BrokenSnapshot() if broken_diagnostic else
            replace(original,sequence=11,received_at=10.1))
        runtime.owner.joint_intake_observation=replace(intake,intake_sequence=11,received_at=10.1)
        raise failure
    monkeypatch.setattr(session,'_guard',fail)
    records=trace_sim_admission(session,journal,runtime)
    with pytest.raises(PermissionError) as raised:session._guard()
    assert raised.value is failure
    assert session._snapshot is original
    row=next(row for row in records if row['stage']=='guard')
    assert row['outcome']=='raised'
    if broken_diagnostic:
        assert row['joint_diagnostic_error']=='RuntimeError'
    else:
        facts=row['joint_delivery']
        assert facts['before']['session']==facts['after']['session']==dict(sequence=10,received_owner_s=10.)
        assert facts['before']['latest']==dict(sequence=10,received_owner_s=10.)
        assert facts['after']['latest']==dict(sequence=11,received_owner_s=10.1)
        assert facts['before']['intake']['intake_sequence']==10
        assert facts['after']['intake']['intake_sequence']==11


def test_guard_delivers_valid_native_intake_waiting_for_session_lock(tmp_path,monkeypatch):
    import threading
    journal=PolicyExecutionJournal(tmp_path/'policy.sqlite3')
    session,client,clock,*_=setup_session(tmp_path,execution_journal=journal)
    runtime=runtime_methods(session,client)
    bind_sim_runtime(session,runtime)
    binding=session._runtime_binding
    waiting=threading.Event()
    observe=binding.observe
    def pending(snapshot):
        waiting.set()
        return observe(snapshot)
    monkeypatch.setattr(binding,'observe',pending)
    clock[0]=10.6
    message=joint_message(runtime)
    message.header.stamp.sec=10
    message.header.stamp.nanosec=500_000_000
    message.position=[.11,0.]
    worker=threading.Thread(target=runtime._on_joint_state,args=(message,))
    try:
        with session._lock:
            worker.start()
            assert waiting.wait(2), 'native callback did not reach session delivery'
            original=runtime.latest_joint_state
            assert original is not session._snapshot
            assert original.received_at==pytest.approx(10.5)
            session._guard()
            assert session._snapshot is original
            assert session.owner._joint_state is original
            assert session._history[original.sequence] is original
            assert original.received_at==pytest.approx(10.5)
    finally:
        worker.join(2)
    assert not worker.is_alive()
    assert session.hold_reason is None and session.owner.state=='ready'
    assert session._snapshot is original and not client.commands


@pytest.mark.parametrize('mode', ['stale','future','calibration','expired','hold'])
def test_pending_intake_keeps_existing_fail_closed_checks(tmp_path,mode):
    journal=PolicyExecutionJournal(tmp_path/'policy.sqlite3')
    session,client,clock,*_=setup_session(tmp_path,execution_journal=journal)
    runtime=runtime_methods(session,client)
    bind_sim_runtime(session,runtime)
    clock[0]=10.1 if mode in ('future','calibration','hold') else 10.6 if mode=='stale' else 10.95
    receipt=10.2 if mode=='future' else 10.0 if mode=='stale' else clock[0]
    latest=replace(session._snapshot,sequence=11,received_at=receipt,
        calibration_revision='other' if mode=='calibration' else session._snapshot.calibration_revision)
    runtime.latest_joint_state=latest
    if mode=='hold':
        with pytest.raises(PermissionError):session._fail('existing_hold')
    with pytest.raises(PermissionError):session._guard()
    assert session.hold_reason and not client.commands
    assert latest.received_at==receipt
    if mode=='hold':assert session._snapshot.sequence==10


@pytest.mark.parametrize('copy_replay', [False,True])
def test_native_delivery_skip_is_one_shot_and_preserves_replay_rejection(tmp_path,copy_replay):
    journal=PolicyExecutionJournal(tmp_path/'policy.sqlite3')
    session,client,*_=setup_session(tmp_path,execution_journal=journal)
    runtime=runtime_methods(session,client)
    bind_sim_runtime(session,runtime)
    latest=replace(session._snapshot,sequence=11)
    runtime.latest_joint_state=latest
    binding=session._runtime_binding
    binding.observe(latest)
    assert session._snapshot is latest and session.hold_reason is None
    with pytest.raises(PermissionError):binding.observe(replace(latest) if copy_replay else latest)
    assert session.hold_reason and not client.commands


@pytest.mark.parametrize('calibration', [True, False])
@pytest.mark.parametrize('expire_on_save', [False,True])
def test_idle_calibration_waits_operating_period_before_each_fresh_capture(calibration,expire_on_save):
    import ast
    from contextlib import nullcontext
    from types import SimpleNamespace
    source = ROOT/'deploy/robot/omx/sim_pick_place_policy.py'
    tree = ast.parse(source.read_text(encoding='utf-8'))
    loop = next(node for node in ast.walk(tree) if isinstance(node, ast.For)
                and isinstance(node.target, ast.Name) and node.target.id == 'index')
    clock = [0.]
    captures, checks = [], []
    expired=[False]
    def require_live():
        if expired[0]:raise TimeoutError('original actor deadline')
    def infer(*args, **kwargs):
        assert kwargs['require_live'] is require_live
        captures.append(clock[0])
        clock[0] += .1
        return SimpleNamespace(produced_at_ns=0, observed_at_ns=0,
                               camera_received_at_ns=(0,)), SimpleNamespace(
            source=SimpleNamespace(rgb=b'', frame_sha256='frame'), consumed_current=True,
            produced_at_ns=0, returned_at_ns=0)
    def guard():
        checks.append(clock[0])
        return {'timing': {'max_action_age_ns': 10**12}}, 0, ()
    def save_image(*args):
        clock[0] += .01
        expired[0]=expire_on_save
    def reject(*args):
        clock[0] += .05
        raise PermissionError('controlled submit fault')
    session = SimpleNamespace(_lock=nullcontext(), _guard=guard,
                              _source=lambda *args: None, _camera_source=lambda *args: None,
                              submit=reject)
    namespace = dict(calibration=calibration, last_submit=None, last_cycle=None, period_s=.8,
        time=SimpleNamespace(monotonic=lambda: clock[0], sleep=lambda delay: clock.__setitem__(0, clock[0]+delay)),
        require_live=require_live, infer_for_owner=infer, engine=None, session=session, camera=None,
        asdict=vars, steps=[], Image=SimpleNamespace(frombytes=lambda *args:
            SimpleNamespace(save=save_image)), frames=Path('/unused'), last_observed=[0.],
        arm=SimpleNamespace(monotonic=lambda: clock[0]))
    code=compile(ast.Module(body=[loop], type_ignores=[]), str(source), 'exec')
    if expire_on_save:
        with pytest.raises(TimeoutError,match='original actor deadline'):
            exec(code,namespace)
        assert len(captures)==1 and not checks
    elif calibration:
        exec(code, namespace)
        assert len(captures) == len(checks) == 12
        assert all(start-finished >= .8 for start, finished in zip(captures[1:], checks))
    else:
        with pytest.raises(PermissionError, match='controlled submit fault'):
            exec(code, namespace)
        assert namespace['steps'][0]['submit_ms'] == pytest.approx(50.)
        assert namespace['steps'][0]['pre_submit_original_input_age_ms'] == pytest.approx(110.)
    for step in namespace['steps']:
        assert step['frame_save_ms'] == pytest.approx(10.)
        assert step['candidate']['observed_at_ns'] == 0
        assert step['candidate']['camera_received_at_ns'] == (0,)
