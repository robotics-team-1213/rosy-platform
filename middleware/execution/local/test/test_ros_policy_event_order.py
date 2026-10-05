"""HOST scheduling seams over actual native handle methods, not DDS acceptance."""
import ast
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable
from uuid import uuid4

from test_omx_policy_session import ROOT
from omx_adapter.ros_goal_contract import RosGoalEvent, canonical_ros_goal_id


def handle(sink):
    file = ROOT/'middleware/apps/device/omx/adapter/omx_adapter/ros_runtime.py'
    tree = ast.parse(file.read_text(encoding='utf-8'))
    cls = next(node for node in tree.body if isinstance(node,ast.ClassDef)
               and node.name == 'RosTrajectoryActionHandle')
    cls.bases = []
    cls.body = [node for node in cls.body if isinstance(node,ast.FunctionDef)
                and node.name not in {'__init__'}]
    scope = dict(Any=Any,Callable=Callable,threading=threading,time=time,
        RosGoalEvent=RosGoalEvent,canonical_ros_goal_id=canonical_ros_goal_id)
    exec(compile(ast.Module(body=[cls],type_ignores=[]),str(file),'exec'),scope)
    obj = scope['RosTrajectoryActionHandle'].__new__(scope['RosTrajectoryActionHandle'])
    obj._lock = threading.RLock();obj._event_delivery_lock = threading.RLock()
    obj._event_sink = sink;obj._command = SimpleNamespace(command_id='command',phase_id=None)
    obj._event_sequence = 0;obj._feedback_sequence = 0;obj._early_feedback = 0
    obj._goal_handle = None;obj._goal_id = None;obj._cancel_requested = False
    obj._cancel_acknowledged = None;obj._pending_cancel_acks = []
    obj._acceptance_emitted = False;obj._observation_failed = False
    return obj


def test_sequence_allocation_and_durable_delivery_are_serialized():
    first, second_attempt, second_delivery, release = (threading.Event() for _ in range(4))
    delivered = []
    def sink(event):
        if event.kind == 'GOAL_ACCEPTED':
            first.set();assert release.wait(2)
        else:second_delivery.set()
        delivered.append(event.sequence)
    obj = handle(sink);goal = str(uuid4())
    one = threading.Thread(target=lambda:obj._emit('GOAL_ACCEPTED',goal_id=goal))
    def later():
        second_attempt.set();obj._emit('RUNNING_FEEDBACK',goal_id=goal,feedback_sequence=1)
    two = threading.Thread(target=later)
    one.start();assert first.wait(1);two.start();assert second_attempt.wait(1)
    try:assert not second_delivery.wait(.1),'later native event overtook durable acceptance'
    finally:release.set();one.join(2);two.join(2)
    assert delivered == [1,2]


def test_cancel_response_during_acceptance_storage_waits_for_acceptance():
    delivered = [];obj = None
    def sink(event):
        if event.kind == 'GOAL_ACCEPTED':
            obj._on_cancel_response(SimpleNamespace(result=lambda:SimpleNamespace(goals_canceling=[1])))
        delivered.append(event)
    obj = handle(sink)
    goal = uuid4()
    result_future = SimpleNamespace(add_done_callback=lambda callback:None)
    native = SimpleNamespace(accepted=True,goal_id=SimpleNamespace(uuid=list(goal.bytes)),
                             get_result_async=lambda:result_future)
    obj._on_goal_response(SimpleNamespace(result=lambda:native))
    assert [(event.kind,event.sequence) for event in delivered] == [('GOAL_ACCEPTED',1),('CANCEL_ACK',2)]
    assert all(event.goal_id == str(goal) for event in delivered)
    assert obj.cancel_acknowledged is True


def test_persistently_failed_sink_does_not_recursively_request_more_cancels():
    def failed(event):raise RuntimeError('storage unavailable')
    obj = handle(failed);obj._goal_id = str(uuid4());obj._acceptance_emitted = True
    requests = []
    def cancel_async():
        requests.append(True)
        def done(callback):
            if len(requests) == 1:
                callback(SimpleNamespace(result=lambda:SimpleNamespace(goals_canceling=[1])))
        return SimpleNamespace(add_done_callback=done)
    obj._goal_handle = SimpleNamespace(cancel_goal_async=cancel_async)
    assert obj._emit('RUNNING_FEEDBACK',goal_id=obj._goal_id,feedback_sequence=1) is False
    assert obj._observation_failed and len(requests) == 1
