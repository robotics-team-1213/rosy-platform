"""Opt-in isolated ROS transport; default synthetic candidate, optional CPU ACT.

    This fixture declares 2s source/joint budgets and a 12s lease. It does not
qualify the separately rejected 50ms fixture, hardware, task success or Fleet.
Run only with domain199 and localhost discovery, with basetemp on X:.
"""
import hashlib
import json
import os
import sys
import threading
import time
import traceback
from dataclasses import replace, asdict
from contextlib import contextmanager, nullcontext
from uuid import uuid4

import pytest

rclpy = pytest.importorskip('rclpy', reason='requires isolated Jazzy ROS transport')
from rclpy.action import ActionServer, CancelResponse
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.node import Node
from control_msgs.action import FollowJointTrajectory
from sensor_msgs.msg import JointState

from test_omx_policy_session import setup_session, candidate, owner_binding, ROOT
from omx_adapter.ros_owner_executor import OwnerMultiThreadedExecutor
from omx_adapter.ros_runtime import RosArmCommandRuntime
from rosy.execution.local.policy_install import InstallBinding, load_policy
from rosy.execution.local.policy_journal import PolicyExecutionJournal
from rosy.contracts.learning import seal
from native_parent_chain import submit_parent, export_parent

pytestmark = pytest.mark.skipif(
    os.environ.get('ROS_DOMAIN_ID') != '199' or not (
        os.environ.get('ROS_LOCALHOST_ONLY') == '1' or
        os.environ.get('ROS_AUTOMATIC_DISCOVERY_RANGE') == 'LOCALHOST'),
    reason='requires explicit isolated domain199/localhost environment')


def install_transport_fixture(session, runtime, policy_root):
    doc = session.policy.recheck()
    doc['owner'] = owner_binding(runtime.owner)
    doc['timing'].update(max_observation_age_ns=2_000_000_000,
                         max_action_age_ns=2_000_000_000)
    doc = seal(doc)
    (policy_root/'policy-artifact.json').write_text(json.dumps(doc), encoding='utf-8')
    binding = InstallBinding(policy_revision=doc['revision'],profile=doc['profile'],
        robot_type=doc['robot_type'],environment='sim',
        device_profile_revision=doc['device_profile_revision'],
        camera_profile_revision=doc['camera_profile_revision'],owner=doc['owner'],
        cameras=doc['cameras'],normalization_sha256=doc['normalization']['sha256'],
        action_names=tuple(doc['joint_names']),
        action_limits=tuple(tuple(v) for v in doc['action']['limits']),timing=doc['timing'])
    session.policy = load_policy(policy_root,binding)
    session.owner, session._config = runtime.owner, runtime.owner.config
    session._clock, session._last_now = runtime.monotonic, None
    session._owner_session = runtime.owner.session_id
    now = int(runtime.monotonic()*1e9)
    session._lease = replace(session.lease,policy_revision=doc['revision'],
        owner_session_id=runtime.owner.session_id,issued_at_ns=now,
        expires_at_ns=now+12_000_000_000)


@contextmanager
def native_setup_cleanup(root):
    """Own partial fixture resources; preserve the setup exception on teardown."""
    callbacks = []
    errors = []
    try:
        yield callbacks.append, callbacks.clear
    finally:
        primary = sys.exc_info()[1]
        if callbacks:
            for cleanup in reversed(callbacks):
                try:
                    cleanup()
                except BaseException as error:
                    errors.append(repr(error))
            try:
                (root/'setup-cleanup.json').write_text(json.dumps(dict(
                    primary_error=repr(primary), cleanup_errors=errors,
                    context_ok=rclpy.ok(), scope='isolated own setup resources only'), indent=2))
            except Exception as receipt_error:
                if primary is None:
                    raise
                # Diagnostic storage cannot replace the original setup failure.
                print('native setup receipt failed: '+repr(receipt_error), file=sys.stderr)
            if errors and primary is None:
                raise AssertionError('native setup cleanup failed: '+repr(errors))


@pytest.mark.parametrize('revoke', [False, True])
@pytest.mark.parametrize('with_parent',[False,True],ids=['native_only','parent_episode_fleet'])
def test_native_session_goal_facts_and_revocation(tmp_path, revoke, with_parent, *,
                                                with_inference=False, with_core=False, core_client=None):
    journal = PolicyExecutionJournal(tmp_path/'policy.sqlite3')
    session, _, _, authority, policy_root = setup_session(
        tmp_path,execution_journal=journal,max_lease_duration_ns=15_000_000_000,
        camera=with_inference or with_core)
    suffix = uuid4().hex[:10]
    prefix = '/isolated_policy_'+suffix
    rclpy.init()
    with native_setup_cleanup(tmp_path) as (own, complete_setup):
        own(rclpy.try_shutdown)
        nodes = []
        for role in ('owner','server','feedback'):
            node = Node('policy_'+role+'_'+suffix)
            nodes.append(node)
            own(node.destroy_node)
        received, server_canceled, fixture_shutdown = threading.Event(), threading.Event(), threading.Event()
        received_goal = {}
        def execute(handle):
            received_goal.update(joint_names=list(handle.request.trajectory.joint_names),
                positions=list(handle.request.trajectory.points[-1].positions))
            received.set()
            if revoke:
                deadline = time.monotonic()+6
                while (not handle.is_cancel_requested and not fixture_shutdown.is_set()
                       and time.monotonic()<deadline):
                    time.sleep(.005)
                if handle.is_cancel_requested:
                    server_canceled.set();handle.canceled()
                else:handle.abort()
            else:handle.succeed()
            result = FollowJointTrajectory.Result();result.error_code = 0
            return result
        server = ActionServer(nodes[1],FollowJointTrajectory,prefix+'/trajectory',
            execute_callback=execute,cancel_callback=lambda _:CancelResponse.ACCEPT,
            callback_group=ReentrantCallbackGroup())
        own(server.destroy)
        runtime = RosArmCommandRuntime(nodes[0],
            replace(session.owner.config,max_joint_state_age_s=2.0,action_timeout_s=8.0),
            joint_state_topic=prefix+'/joints',trajectory_action=prefix+'/trajectory',poll_period_s=.01)
        own(runtime.destroy)
        native_events = []
        original_sink = runtime.action_port._event_sink
        def trace_sink(event):
            entry = dict(event=asdict(event),begin=time.monotonic())
            native_events.append(entry)
            try:return original_sink(event)
            except Exception as error:
                entry['error'] = str(error);raise
            finally:entry['elapsed_ms'] = (time.monotonic()-entry['begin'])*1000
        runtime.action_port._event_sink = trace_sink
        install_transport_fixture(session,runtime,policy_root)
        if with_core:
            # Cold web imports precede the original capture and lease clocks.
            from types import SimpleNamespace
            sys.path[:0] = [str(ROOT/'middleware/core'/part) for part in ('api','gateway','services','events')]
            from fastapi.testclient import TestClient
            from core_api_web.api.app import create_app
            from core_api_web.api.v1.common import operator
            from rosy.execution.local.core_arm_policy import CoreArmPolicyPort
            from test_omx_policy_session import CameraSnapshot
            rgb = bytes(range(12))
        if with_inference:
            # Explicit test-only numerical composition. Cold loading precedes the
            # original lease/grant issuance; inference never refreshes their clocks.
            sys.path[:0] = [str(ROOT/'learning/training/omx'), str(ROOT/'learning/training/omx/test')]
            from act_cpu_fixture import install_cpu_fixture
            from test_act_owner_capture import CapturedRGB, infer_for_owner
            from test_omx_policy_session import CameraSnapshot
            engine = install_cpu_fixture(session, policy_root)
            rgb = bytes(range(192))
            captured_results = []
            def prepare_inference():
                result_candidate, numerical = infer_for_owner(engine, session, CapturedRGB(camera_capture, rgb))
                captured_results.append(numerical)
                import base64
                result_doc = asdict(numerical)
                result_doc['source']['rgb_base64'] = base64.b64encode(result_doc['source'].pop('rgb')).decode('ascii')
                (tmp_path/'inference-result.json').write_text(json.dumps(dict(
                    result=result_doc, candidate=asdict(result_candidate), actual_cpu=True,
                    synthetic_model=True, clock_scope='actual isolated runtime monotonic'), indent=2), encoding='utf-8')
                return result_candidate
        publisher = nodes[2].create_publisher(JointState,prefix+'/joints',1)
        def publish():
            message = JointState();message.name = ['joint_1','joint_2'];message.position = [.1,0.]
            message.header.stamp = nodes[2].get_clock().now().to_msg()
            publisher.publish(message)
        publisher_timer = nodes[2].create_timer(.005,publish)
        own(publisher_timer.cancel)
        executor = OwnerMultiThreadedExecutor(num_threads=6)
        own(lambda: executor.shutdown(timeout_sec=5))
        for node in nodes:executor.add_node(node)
        spinner = threading.Thread(target=executor.spin)
        spinner.start()
        complete_setup()
    try:
        deadline = time.monotonic()+5
        while runtime.owner._joint_state is None or not runtime.action_port.server_is_ready():
            assert time.monotonic()<deadline,'ROS discovery/feedback timeout'
            time.sleep(.005)
        # Fixture installation precedes startup. Issue the synthetic lease now;
        # neither the admission nor any live installed policy is changed.
        now = int(runtime.monotonic()*1e9)
        session._lease = replace(session.lease,issued_at_ns=now,expires_at_ns=now+12_000_000_000)
        # Freeze the first capture only after cold durable source installation.
        # No previously consumed frame/lease/grant timestamp is refreshed.
        # The session lock excludes watchdog admission before first capture.
        with session._lock:
            binding_started = runtime.monotonic()
            session.bind_runtime(runtime)
            if with_core:
                camera_capture = CameraSnapshot('front', 'cam-front', 'a'*64, (3,2,2),
                    int(runtime.monotonic()*1e9), hashlib.sha256(rgb).hexdigest())
                session._cameras = lambda: (camera_capture,)
            if with_inference:
                camera_capture = CameraSnapshot('front', 'cam-front', 'a'*64, (3,8,8),
                    int(runtime.monotonic()*1e9), hashlib.sha256(rgb).hexdigest())
                session._cameras = lambda: (camera_capture,)
                (tmp_path/'initial-capture-order.json').write_text(json.dumps(dict(
                    binding_started=binding_started, binding_finished=runtime.monotonic(),
                    first_capture_ns=camera_capture.received_at_ns,
                    capture_count=1, timestamp_refreshed=False)))
        if with_parent:
            command,runner,api,parent=submit_parent(session,journal,tmp_path,
                candidate_factory=prepare_inference if with_inference else None)
        elif with_core:
            port = CoreArmPolicyPort(session, capture=lambda: nullcontext((rgb, camera_capture)), principal='fixture-operator')
            app = create_app({}, SimpleNamespace(arm_policy=port,
                safety=SimpleNamespace(estop=False, estop_listeners=[])))
            app.dependency_overrides[operator] = lambda: SimpleNamespace(token_id='fixture-operator', role='operator')
            if core_client is not None:
                command = core_client(app, session)
            else:
                with TestClient(app) as client:
                    source = client.post('/api/v1/arm/observations',
                        json=dict(policy_revision=session.lease.policy_revision))
                    assert source.status_code == 200, source.text
                    response = client.post('/api/v1/arm/actions', json=dict(
                        policy_revision=session.lease.policy_revision,
                        observation_id=source.json()['observation_id'],
                        positions={'joint_1': .101, 'joint_2': .001}))
                    assert response.status_code == 202, response.text
                    assert response.json()['accepted'] is True
                    command = response.json()['command_id']
        else:
            state, _ = session.capture_observation()
            action_candidate = candidate(session,sequence=state.sequence,
                observed_at_ns=int(state.received_at*1e9),produced_at_ns=int(runtime.monotonic()*1e9))
            result=session.submit(action_candidate)
            assert result.accepted
            command=result.command_id
        assert received.wait(3)
        if with_core:
            assert received_goal == dict(joint_names=['joint_1', 'joint_2'], positions=[.101, .001])
        if revoke:authority[0] = False
        deadline = time.monotonic()+7
        record = journal.read(command)
        while not record['events'] or record['events'][-1]['kind'] != 'TERMINAL_RESULT':
            assert time.monotonic()<deadline,record
            time.sleep(.005);record = journal.read(command)
        assert record['events'][0]['kind'] == 'GOAL_ACCEPTED'
        assert record['driver_goal_id'] != command
        assert record['events'][-1]['status'] == (5 if revoke else 4)
        assert all(event['goal_id'] == record['driver_goal_id'] for event in record['events'])
        if revoke:
            assert server_canceled.is_set() and session.hold_reason
            assert runtime.owner.state == 'hold'
        source = journal.read_source(record['intent']['source_revision'])
        if with_inference:
            assert len(captured_results) == 1 and captured_results[0].positions == (0.,0.)
            assert source['header']['policy_revision'] == captured_results[0].policy_revision
            expected = captured_results[0].candidate_fields()
            for key, value in expected.items():
                assert record['intent']['candidate'][key] == (list(value) if isinstance(value, tuple) else value)
            for ref in engine.metadata['files']:
                assert hashlib.sha256(source['payloads']['policy/'+ref['path']]).hexdigest() == ref['sha256']
        else:
            assert source['payloads']['policy/model.bin'] == b'host-fixture'
        if with_parent:
            export_parent(tmp_path,journal,command,runner,api,parent,revoke=revoke)
        files = ['middleware/robot_execution/local/src/rosy/execution/local/'+name+'.py'
                 for name in ('omx_policy','policy_runtime','policy_source','policy_journal','policy_install')]
        files += ['contracts/learning/src/rosy/contracts/learning/artifacts.py']
        files += ['middleware/devices/omx/adapter/omx_adapter/'+name+'.py'
                  for name in ('command_owner','ros_runtime')]
        if with_parent:
            files += ['middleware/robot_execution/local/src/rosy/execution/local/'+name+'.py'
                      for name in ('policy_parent','policy_episode')]
            files += ['middleware/devices/omx/adapter/omx_adapter/'+name+'.py'
                      for name in ('policy_parent','action_store_readback','action_api',
                                   'action_runner','action_store','journal_identity')]
            files += ['contracts/learning/src/rosy/contracts/learning/'+name+'.py'
                      for name in ('omx_execution','omx_execution_intent')]
            files += ['learning/registry/policy/fleet_join.py',
                      'middleware/robot_execution/local/test/native_parent_chain.py',
                      'middleware/robot_execution/local/test/test_policy_runtime_ros.py']
        if with_inference:
            files += ['learning/training/omx/'+path for path in ('act_inference.py', 'act_owner_capture.py',
                'test/act_cpu_fixture.py', 'test/test_act_owner_capture.py', 'test/test_act_native_chain.py')]
            files += ['contracts/learning/src/rosy/contracts/learning/inference.py']
        if with_core:
            files += ['middleware/robot_execution/local/src/rosy/execution/local/core_arm_policy.py',
                      'middleware/core/api/core_api_web/api/v1/arm.py',
                      'middleware/core/api/core_api_web/api/app.py']
        scope = ('isolated actual CPU ACT and ROS transport; synthetic zero weights/capture/authority; '
                 'no trained quality/task/hardware/authenticated Fleet' if with_inference else
                 'isolated actual ROS transport; synthetic policy/authority; no inference/task/hardware/Fleet')
        proof = dict(scope=scope, core_http_admission=with_core,
            core_socket_sdk=core_client is not None, received_ros_goal=received_goal,
            fixture_budgets=dict(source_ns=2_000_000_000,joint_s=2.0,lease_ns=12_000_000_000,
                                poll_period_s=.01),
            short_deadline_acceptance=False,revoke=revoke,journal=record,
            parent_chain_verified=with_parent, actual_cpu_synthetic_inference=with_inference,
            source_revision=record['intent']['source_revision'],
            loaded_source_sha256={path:hashlib.sha256((ROOT/path).read_bytes()).hexdigest() for path in files})
        (tmp_path/'transport-receipt.json').write_text(json.dumps(proof,indent=2),encoding='utf-8')
    finally:
        primary_error=repr(sys.exc_info()[1]) if sys.exc_info()[1] is not None else None
        fixture_shutdown.set()  # Tear down only this synthetic server; never a robot command.
        publisher_timer.cancel();runtime._timer.cancel()
        stopped = executor.shutdown(timeout_sec=5)
        spinner.join(3)
        workers_drained = threading.Event()
        def drain_workers():
            executor._executor.shutdown(wait=True)
            workers_drained.set()
        drainer = threading.Thread(target=drain_workers,daemon=True)
        drainer.start()
        workers_stopped = workers_drained.wait(5)
        (tmp_path/'native-events.json').write_text(json.dumps(dict(events=native_events,
            server_canceled=server_canceled.is_set(),hold=session.hold_reason,
            executor_stopped=stopped,workers_stopped=workers_stopped,
            spinner_alive=spinner.is_alive(),primary_error=primary_error,
            remaining_thread_stacks={} if workers_stopped else {
                str(ident):traceback.format_stack(frame)
                for ident,frame in sys._current_frames().items()}),indent=2),encoding='utf-8')
        # Destroying ROS entities with live callbacks can hide the original
        # failure or block forever. The isolated subprocess supervisor owns
        # termination when this bounded drain fails.
        assert stopped and workers_stopped and not spinner.is_alive(),'isolated executor did not shut down'
        runtime.destroy();server.destroy()
        for node in nodes:node.destroy_node()
        rclpy.try_shutdown()


@pytest.mark.parametrize('skip_setup', [False, True])
def test_native_cpu_setup_failure_cleans_context(tmp_path, monkeypatch, skip_setup):
    # Fail before executor startup; no transport goal can be submitted.
    sys.path.insert(0, str(ROOT/'learning/training/omx/test'))
    import act_cpu_fixture
    def fail_setup(*_):
        if skip_setup:
            pytest.skip('injected missing optional CPU dependency')
        raise RuntimeError('injected CPU setup failure')
    monkeypatch.setattr(act_cpu_fixture, 'install_cpu_fixture', fail_setup)
    expected = pytest.skip.Exception if skip_setup else RuntimeError
    with pytest.raises(expected):
        test_native_session_goal_facts_and_revocation(tmp_path, False, True, with_inference=True)
    assert not rclpy.ok()
    proof = json.loads((tmp_path/'setup-cleanup.json').read_text())
    assert proof['context_ok'] is False and proof['cleanup_errors'] == []
    assert 'injected' in proof['primary_error']
    rclpy.init()
    try:
        assert rclpy.ok()
    finally:
        rclpy.try_shutdown()
