"""A sent parameter request is not evidence of runtime calibration adoption."""
import ast
from pathlib import Path
from types import SimpleNamespace as NS
from concurrent.futures import Future
from unittest.mock import Mock


def adapter():
    path = Path(__file__).parents[1] / 'control/calib_node.py'
    tree = ast.parse(path.read_text(encoding='utf-8'))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'CalibNode')
    methods = [m for m in cls.body if isinstance(m, ast.FunctionDef)
               and m.name in ('_apply_safety', '_finish_apply')]
    scope = dict(ParameterValue=NS, Parameter=NS, Clock=NS, ClockType=NS(STEADY_TIME=3),
                 ParameterType=NS(PARAMETER_BOOL=1, PARAMETER_INTEGER=2,
                                  PARAMETER_DOUBLE=3, PARAMETER_STRING=4),
                 SetParameters=NS(Request=NS))
    exec(compile(ast.Module(body=methods, type_ignores=[]), str(path), 'exec'), scope)
    future = Future()
    client = Mock()
    client.wait_for_service.return_value = True
    client.call_async.return_value = future
    node = NS(create_client=Mock(return_value=client), _status=Mock(),
              create_timer=Mock(return_value=Mock()), destroy_timer=Mock(), destroy_client=Mock())
    for name, method in scope.items():
        if name.startswith('_') and callable(method):
            setattr(node, name, method.__get__(node))
    return node, future


def messages(node):
    return [call.args[0] for call in node._status.call_args_list]


def test_request_remains_pending_until_ack():
    node, future = adapter()
    node._apply_safety([('imu_roll0', 1.)])
    assert any('대기' in value for value in messages(node))
    future.set_result(NS(results=[NS(successful=True, reason='')]))
    assert '운전 적용 미확인' in messages(node)[-1]


def test_rejected_or_incomplete_ack_never_reports_success():
    for results in ([], [NS(successful=False, reason='rejected')]):
        node, future = adapter()
        node._apply_safety([('imu_roll0', 1.)])
        future.set_result(NS(results=results))
        assert '거절' in messages(node)[-1]
        node.destroy_client.assert_called_once()


def test_timeout_does_not_turn_late_ack_into_success():
    node, future = adapter()
    node._apply_safety([('imu_roll0', 1.)])
    timer_callback = node.create_timer.call_args.args[1]
    timer_callback()
    previous = messages(node)
    assert '시간 초과' in previous[-1]
    future.set_result(NS(results=[NS(successful=True, reason='')]))
    assert messages(node) == previous


def test_transport_failure_is_reported():
    node, future = adapter()
    node._apply_safety([('imu_roll0', 1.)])
    future.set_exception(RuntimeError('disconnected'))
    assert '실패' in messages(node)[-1]


def test_missing_owner_keeps_saved_only_state():
    node, future = adapter()
    client = node.create_client.return_value
    client.wait_for_service.return_value = False
    node._apply_safety([('imu_roll0', 1.)])
    assert 'yaml만 저장됨' in messages(node)[-1]
    client.call_async.assert_not_called()
    node.destroy_client.assert_called_once()


def test_second_request_cannot_replace_pending_ack():
    node, future = adapter()
    node._apply_safety([('imu_roll0', 1.)])
    node._apply_safety([('imu_roll0', 2.)])
    assert '중복 적용 거절' in messages(node)[-1]
    node.create_client.assert_called_once()
