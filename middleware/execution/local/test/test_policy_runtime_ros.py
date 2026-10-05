"""Opt-in isolated actual ROS transport; synthetic policy/authority, no inference.

This fixture declares 2s source/joint budgets and a 12s lease. It does not
qualify the separately rejected 50ms fixture, hardware, task success or Fleet.
Run only with domain199 and localhost discovery, with basetemp on X:.
"""
import hashlib
import json
import os
import threading
import time
from dataclasses import replace, asdict
from uuid import uuid4

import pytest

rclpy = pytest.importorskip('rclpy', reason='requires isolated Jazzy ROS transport')
from rclpy.action import ActionServer, CancelResponse
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from control_msgs.action import FollowJointTrajectory
from sensor_msgs.msg import JointState

from test_omx_policy_session import setup_session, candidate, owner_binding, ROOT
from omx_adapter.ros_runtime import RosArmCommandRuntime
from rosy.execution.local.policy_install import InstallBinding, load_policy
from rosy.execution.local.policy_journal import PolicyExecutionJournal
from rosy.contracts.learning import seal

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


@pytest.mark.parametrize('revoke', [False, True])
def test_native_session_goal_facts_and_revocation(tmp_path, revoke):
    journal = PolicyExecutionJournal(tmp_path/'policy.sqlite3')
    session, _, _, authority, policy_root = setup_session(
        tmp_path,execution_journal=journal,max_lease_duration_ns=15_000_000_000)
    suffix = uuid4().hex[:10]
    prefix = '/isolated_policy_'+suffix
    rclpy.init()
    nodes = [Node('policy_'+role+'_'+suffix) for role in ('owner','server','feedback')]
    received, server_canceled = threading.Event(), threading.Event()
    def execute(handle):
        received.set()
        if revoke:
            deadline = time.monotonic()+6
            while not handle.is_cancel_requested and time.monotonic()<deadline:
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
    runtime = RosArmCommandRuntime(nodes[0],
        replace(session.owner.config,max_joint_state_age_s=2.0,action_timeout_s=8.0),
        joint_state_topic=prefix+'/joints',trajectory_action=prefix+'/trajectory',poll_period_s=.01)
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
    publisher = nodes[2].create_publisher(JointState,prefix+'/joints',1)
    def publish():
        message = JointState();message.name = ['joint_1','joint_2'];message.position = [.1,0.]
        publisher.publish(message)
    publisher_timer = nodes[2].create_timer(.005,publish)
    executor = MultiThreadedExecutor(num_threads=6)
    for node in nodes:executor.add_node(node)
    spinner = threading.Thread(target=executor.spin)
    spinner.start()
    try:
        deadline = time.monotonic()+5
        while runtime.owner._joint_state is None or not runtime.action_port.server_is_ready():
            assert time.monotonic()<deadline,'ROS discovery/feedback timeout'
            time.sleep(.005)
        # Fixture installation precedes startup. Issue the synthetic lease now;
        # neither the admission nor any live installed policy is changed.
        now = int(runtime.monotonic()*1e9)
        session._lease = replace(session.lease,issued_at_ns=now,expires_at_ns=now+12_000_000_000)
        session.bind_runtime(runtime)
        state, _ = session.capture_observation()
        result = session.submit(candidate(session,sequence=state.sequence,
            observed_at_ns=int(state.received_at*1e9),produced_at_ns=int(runtime.monotonic()*1e9)))
        assert result.accepted and received.wait(3)
        if revoke:authority[0] = False
        deadline = time.monotonic()+7
        record = journal.read(result.command_id)
        while not record['events'] or record['events'][-1]['kind'] != 'TERMINAL_RESULT':
            assert time.monotonic()<deadline,record
            time.sleep(.005);record = journal.read(result.command_id)
        assert record['events'][0]['kind'] == 'GOAL_ACCEPTED'
        assert record['driver_goal_id'] != result.command_id
        assert record['events'][-1]['status'] == (5 if revoke else 4)
        assert all(event['goal_id'] == record['driver_goal_id'] for event in record['events'])
        if revoke:
            assert server_canceled.is_set() and session.hold_reason
            assert runtime.owner.state == 'hold'
        source = journal.read_source(record['intent']['source_revision'])
        assert source['payloads']['policy/model.bin'] == b'host-fixture'
        files = ['middleware/execution/local/src/rosy/execution/local/'+name+'.py'
                 for name in ('omx_policy','policy_runtime','policy_source','policy_journal')]
        files += ['middleware/apps/device/omx/adapter/omx_adapter/'+name+'.py'
                  for name in ('command_owner','ros_runtime')]
        proof = dict(scope='isolated actual ROS transport; synthetic policy/authority; no inference/task/hardware/Fleet',
            fixture_budgets=dict(source_ns=2_000_000_000,joint_s=2.0,lease_ns=12_000_000_000),
            short_deadline_acceptance=False,revoke=revoke,journal=record,
            source_revision=record['intent']['source_revision'],
            loaded_source_sha256={path:hashlib.sha256((ROOT/path).read_bytes()).hexdigest() for path in files})
        (tmp_path/'transport-receipt.json').write_text(json.dumps(proof,indent=2),encoding='utf-8')
    finally:
        publisher_timer.cancel();runtime._timer.cancel()
        stopped = executor.shutdown(timeout_sec=5)
        spinner.join(3)
        runtime.destroy();server.destroy()
        for node in nodes:node.destroy_node()
        rclpy.shutdown()
        (tmp_path/'native-events.json').write_text(json.dumps(dict(events=native_events,
            server_canceled=server_canceled.is_set(),hold=session.hold_reason),indent=2),encoding='utf-8')
        assert stopped and not spinner.is_alive(),'isolated executor did not shut down'
