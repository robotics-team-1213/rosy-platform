"""D-185 R3: every control node spins through one executor selector; the default is unchanged.

An idle 15-subscription rclpy node used 50-58% of a core with SingleThreadedExecutor and 15%
with rclpy.experimental.EventsExecutor (domain-228 experiment, 2026-09-24). EventsExecutor is
experimental in Jazzy, so it is opt-in: ROSY_EXECUTOR=events. Unset or 'single' must call
rclpy.spin(node) exactly as before.
"""
import ast
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from control.executor_choice import executor_kind, make_executor, spin

CONTROL = Path(__file__).resolve().parents[1]/'control'


class FakeRclpy:
    def __init__(self):
        self.calls = []
        self.__name__ = 'rclpy'
        self.executors = NS(SingleThreadedExecutor=lambda: ('single-executor',))

    def spin(self, node, executor=None):
        self.calls.append((node, executor))


class FakeEvents:
    def __init__(self, log):
        self.log = log

    def add_node(self, node):
        self.log.append(('add', node))

    def spin(self):
        self.log.append(('spin',))

    def remove_node(self, node):
        self.log.append(('remove', node))


def fake_import(name, log=None):
    assert name == 'rclpy.experimental', name
    return NS(EventsExecutor=lambda: ('events-executor',) if log is None else FakeEvents(log))


def test_default_and_single_spin_exactly_as_before():
    for environ in ({}, {'ROSY_EXECUTOR': 'single'}, {'ROSY_EXECUTOR': ' Single '}):
        rclpy = FakeRclpy()
        spin('node', rclpy, environ=environ, import_module=fake_import)
        assert rclpy.calls == [('node', None)], environ


def test_events_spins_the_executor_natively_like_the_rig():
    # The rig calls executor.spin(); rclpy.spin(node, executor=...) would add a Python
    # spin_once loop (about 14% against 11% of a core), so the A/B would measure another loop.
    rclpy, log = FakeRclpy(), []
    spin('node', rclpy, environ={'ROSY_EXECUTOR': 'events'}, import_module=lambda name: fake_import(name, log))
    assert rclpy.calls == [] and log == [('add', 'node'), ('spin',), ('remove', 'node')]


def test_events_removes_the_node_when_spin_raises():
    class Interrupted(FakeEvents):
        def spin(self):
            raise KeyboardInterrupt
    log = []
    with pytest.raises(KeyboardInterrupt):
        spin('node', FakeRclpy(), environ={'ROSY_EXECUTOR': 'events'},
             import_module=lambda name: NS(EventsExecutor=lambda: Interrupted(log)))
    assert log == [('add', 'node'), ('remove', 'node')]


def test_an_unknown_executor_fails_loudly():
    with pytest.raises(ValueError, match="ROSY_EXECUTOR must be one of 'events', 'single'"):
        executor_kind({'ROSY_EXECUTOR': 'multi'})


def test_make_executor_builds_either_kind():
    rclpy = FakeRclpy()
    assert make_executor(rclpy, 'single', import_module=fake_import) == ('single-executor',)
    assert make_executor(rclpy, 'events', import_module=fake_import) == ('events-executor',)


def test_every_control_entry_point_spins_through_the_selector():
    offenders, users = [], []
    for path in sorted(CONTROL.rglob('*.py')):
        if path.name == 'executor_choice.py':
            continue  # the one place that calls rclpy.spin directly
        tree = ast.parse(path.read_text(encoding='utf-8'))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == 'spin':
                owner = ast.unparse(node.func.value)
                if owner == 'rclpy':
                    offenders.append(f'{path.relative_to(CONTROL).as_posix()}:{node.lineno}')
                elif owner == 'executor_choice':
                    users.append(path.relative_to(CONTROL).as_posix())
    assert offenders == [], offenders
    assert len(users) == 14, users  # every control node main() found on 2026-09-24
