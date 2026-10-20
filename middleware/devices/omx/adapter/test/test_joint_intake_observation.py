"""Exercise the actual runtime callback with ROS types stubbed and the real owner/intake."""
from dataclasses import FrozenInstanceError
import importlib.util
from pathlib import Path
import sys
from threading import Event, Thread
from types import ModuleType, SimpleNamespace as NS

import pytest

from omx_adapter.command_owner import ArmCommandOwner
from omx_adapter.joint_state_intake import JointStateIntake
from test_omx_command_owner import FakeActionClient, SESSION, make_command, make_config


@pytest.fixture
def runtime_module(monkeypatch):
    # These imports supply types only. No ROS node, executor, or transport is constructed.
    symbols = {'action_msgs.msg': ['GoalStatus'], 'control_msgs.action': ['FollowJointTrajectory'],
               'rclpy.action': ['ActionClient'], 'rclpy.callback_groups': ['MutuallyExclusiveCallbackGroup'],
               'rclpy.clock': ['Clock', 'ClockType'], 'rclpy.duration': ['Duration'],
               'rclpy.executors': ['SingleThreadedExecutor'], 'rclpy.node': ['Node'],
               'rclpy.qos': ['qos_profile_sensor_data'], 'sensor_msgs.msg': ['JointState'],
               'trajectory_msgs.msg': ['JointTrajectoryPoint']}
    for name in {key.partition('.')[0] for key in symbols}:
        package = ModuleType(name)
        package.__path__ = []
        monkeypatch.setitem(sys.modules, name, package)
    for name, fields in symbols.items():
        module = ModuleType(name)
        for field in fields:
            setattr(module, field, object)
        monkeypatch.setitem(sys.modules, name, module)
    path = Path(__file__).parents[1] / 'omx_adapter/ros_runtime.py'
    spec = importlib.util.spec_from_file_location('omx_adapter._intake_runtime_test', path)
    module = importlib.util.module_from_spec(spec)
    action_module = 'omx_adapter.ros_trajectory_action'
    had_action_module = action_module in sys.modules
    try:
        spec.loader.exec_module(module)
        yield module
    finally:
        if not had_action_module:
            sys.modules.pop(action_module, None)


def make_runtime(module):
    source, wall, source_reads, owner_reads = [100.0], [5000.0], [], []
    def owner_clock():
        owner_reads.append(source[0])
        return source[0]
    def source_clock():
        source_reads.append(source[0])
        return NS(nanoseconds=round(source[0] * 1e9))
    client = FakeActionClient()
    owner = ArmCommandOwner(make_config(wall_clock_bound_factor=4), client,
                            monotonic=owner_clock, wall_monotonic=lambda: wall[0], session_id=SESSION)
    runtime = module.RosArmCommandRuntime.__new__(module.RosArmCommandRuntime)
    runtime._node = NS(get_clock=lambda: NS(now=source_clock))
    runtime.monotonic, runtime.owner = owner_clock, owner
    runtime._joint_state_intake = JointStateIntake(owner.config)
    runtime._policy_binding, runtime.latest_joint_state = None, None
    return runtime, client, source, source_reads, owner_reads


def message(stamp):
    ns = round(stamp * 1e9)
    return NS(name=['joint_1', 'joint_2'], position=[.1, -.1],
              header=NS(stamp=NS(sec=ns // 1_000_000_000, nanosec=ns % 1_000_000_000)))


def activate(runtime):
    runtime._on_joint_state(message(100.0))
    assert runtime.owner.submit(make_command(sequence=1)).accepted


def test_rejected_future_intake_is_latched_at_decision_without_refreshing_owner(runtime_module):
    runtime, client, source, source_reads, owner_reads = make_runtime(runtime_module)
    activate(runtime)
    before, wall_before = runtime.owner._joint_state, runtime.owner._joint_state_wall
    source[0] = 100.75
    source_reads.clear(); owner_reads.clear()
    runtime._on_joint_state(message(101.0))
    assert source_reads == owner_reads == [100.75]
    assert runtime.owner._joint_state is before and runtime.owner._joint_state_wall == wall_before
    assert runtime.latest_joint_state is before
    assert runtime.owner.poll().reason == 'joint_state_stale'
    record = runtime.owner.watchdog_observation
    context = record.intake
    assert context.accepted is False and context.rejection_code == 'STAMP_REJECTED'
    assert context.stamp_ns == 101_000_000_000 and context.source_now_ns == 100_750_000_000
    assert context.received_at == 100.75 and context.intake_sequence == 1
    assert context.callback_entered_steady <= context.intake_received_steady <= context.intake_observed_steady
    assert context.intake_observed_steady <= record.steady_now
    with pytest.raises(FrozenInstanceError):
        context.accepted = True
    source[0] = 101.0
    runtime._on_joint_state(message(101.0))
    assert runtime.owner.watchdog_observation is record and record.intake is context
    assert runtime.owner.joint_intake_observation is not context
    assert client.handles[0].cancel_calls == 1


def test_accepted_intake_is_visible_before_owner_delivery_lock_and_stays_latched(runtime_module):
    runtime, client, source, source_reads, owner_reads = make_runtime(runtime_module)
    activate(runtime)
    source[0] = 100.75
    entered = Event()
    original = runtime.owner.run_admission_policy
    def admission(operation):
        entered.set()
        return original(operation)
    runtime.owner.run_admission_policy = admission
    with runtime.owner._lock:
        thread = Thread(target=runtime._on_joint_state, args=(message(100.75),))
        thread.start()
        assert entered.wait(3)
        assert runtime.owner.poll().reason == 'joint_state_stale'
        record = runtime.owner.watchdog_observation
        assert record.intake.accepted is True and record.intake.rejection_code is None
        assert record.intake.intake_sequence == 2 and record.joint_sequence == 1
    thread.join(3)
    assert not thread.is_alive()
    assert runtime.owner._joint_state.sequence == 2
    assert runtime.owner.watchdog_observation is record and record.joint_sequence == 1
    assert client.handles[0].cancel_calls == 1


@pytest.mark.parametrize('accepted', [True, False])
def test_diagnostic_construction_failure_preserves_callback_flow_and_clock_reads(runtime_module, monkeypatch, accepted):
    runtime, _, source, source_reads, owner_reads = make_runtime(runtime_module)
    activate(runtime)
    old = runtime.owner._joint_state
    source[0] = 100.1
    source_reads.clear(); owner_reads.clear()
    def fail(*args, **kwargs):
        raise ValueError('PRIVATE_DIAGNOSTIC_FAILURE')
    monkeypatch.setattr(runtime_module, 'intake_observation', fail)
    runtime._on_joint_state(message(100.1 if accepted else 101.0))
    assert runtime.owner.joint_intake_observation is None
    assert source_reads == [100.1]
    assert owner_reads == ([100.1, 100.1] if accepted else [100.1])
    assert (runtime.owner._joint_state is old) is not accepted
    assert runtime.owner.state == 'active'


def test_intake_context_accepts_only_bounded_typed_fields():
    from omx_adapter.watchdog_observation import intake_observation
    context = intake_observation(
        {'stamp_ns': True, 'source_now_ns': 2**80, 'received_at': float('inf'),
         'wall_received_at': 'PRIVATE', 'accepted': 'yes', 'rejection_code': 'PRIVATE' * 10000,
         'positions': 'PRIVATE'}, callback_entered_steady=float('nan'),
        intake_observed_steady=False, intake_sequence=-1)
    assert all(value is None for value in vars(context).values())
    assert 'PRIVATE' not in repr(context)
