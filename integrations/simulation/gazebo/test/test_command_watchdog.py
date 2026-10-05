"""command_watchdog 순수 판정 계약 (host, ROS-free). 실패 시험이 먼저다(규칙 5).

D-426 T5 항목 2: 현재 Gazebo DiffDrive 에는 command watchdog 이 보장되지
않는다 — CORE 와 별도 수명인 이 bridge 가 최신 cmd_vel 을 monotonic 으로
감시하고 기본 0.30 s 만료 시 base 입력을 zero 로 만든다. clock pause 에도
만료는 작동한다(판정은 monotonic). CORE kill 은 입력 만료 ≤0.30 monotonic s
뒤 같은 정지가 되어야 한다.
"""

from __future__ import annotations

import importlib.util
import sys
from types import SimpleNamespace
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "command_watchdog.py"


def _module():
    spec = importlib.util.spec_from_file_location("command_watchdog", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_no_command_ever_received_means_zero_immediately():
    emitted, why = _module().gate(None, 100.0)
    assert emitted == (0.0, 0.0) and why == "no-command"


def test_fresh_command_passes_through_untouched():
    mod = _module()
    emitted, why = mod.gate(100.0, 100.1)          # 0.1 s 전 명령
    assert emitted is None and why == "pass"       # None = 그 명령을 그대로


def test_expiry_after_300ms_zeros_the_base_input():
    mod = _module()
    assert mod.gate(100.0, 100.29)[1] == "pass"     # 경계 안
    emitted, why = mod.gate(100.0, 100.31)          # 만료
    assert emitted == (0.0, 0.0) and why == "expired"


def test_clock_pause_still_expires_on_monotonic():
    # 시뮬 clock 이 멈춰도 monotonic 시계는 흐른다 — 판정은 monotonic 이다.
    mod = _module()
    emitted, why = mod.gate(5.0, 500.0)
    assert emitted == (0.0, 0.0) and why == "expired"


def test_clock_going_backwards_is_zero_not_a_stale_command():
    emitted, why = _module().gate(100.0, 99.0)
    assert emitted == (0.0, 0.0) and why == "clock-went-backwards"


def test_core_kill_leaves_input_expired_within_the_bound():
    # CORE 가 t=100 에 죽었다 — 마지막 명령 이후 0.30 s 안에 zero 여야 한다.
    mod = _module()
    for offset in (0.05, 0.15, 0.29, 0.31, 1.0):
        emitted, why = mod.gate(100.0, 100.0 + offset)
        if offset <= mod.EXPIRY_S:
            assert why == "pass"
        else:
            assert emitted == (0.0, 0.0)


def test_cli_help_works_without_ros():
    import subprocess

    result = subprocess.run([sys.executable, str(SCRIPT), "--help"],
                            capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0
    assert "watchdog" in result.stdout or "EXPIRY_S" in result.stdout


def test_ros_entrypoint_absence_is_reported_not_crashed():
    import subprocess

    script = str(SCRIPT)
    result = subprocess.run([sys.executable, script], capture_output=True,
                            text=True, encoding="utf-8", timeout=15)
    # Missing manual SIM consent must terminate before importing ROS or creating DDS ports.
    assert result.returncode == 3, (
        f"returncode={result.returncode}, stderr={result.stderr[-400:]}")


def test_missing_ros_dependency_is_reported_after_valid_sim_consent():
    import os
    import subprocess

    code = '''
import builtins, runpy, sys
original_import = builtins.__import__
def no_ros(name, *args, **kwargs):
    if name == "rclpy" or name.startswith("rclpy."):
        raise ModuleNotFoundError("intentional isolated missing ROS dependency")
    return original_import(name, *args, **kwargs)
builtins.__import__ = no_ros
sys.argv = [sys.argv[1], "--sim-only"]
runpy.run_path(sys.argv[0], run_name="__main__")
'''
    env = {**os.environ, 'ROS_DOMAIN_ID': '120', 'ROS_LOCALHOST_ONLY': '1',
           'GZ_PARTITION': 'd426-test', 'ROSY_RUNTIME_MODE': 'core'}
    result = subprocess.run([sys.executable, '-I', '-c', code, str(SCRIPT)],
                            env=env, capture_output=True, text=True, encoding='utf-8', timeout=15)
    assert result.returncode == 3 and 'needs ROS 2' in result.stderr


@pytest.mark.parametrize('last,now,expiry', [
    (1, float('nan'), .3), (float('nan'), 1, .3),
    (1, 10, float('nan')), (1, 1.1, float('inf')),
    (1, 1.1, 0), (1, 1.1, -.3), (1, float('inf'), .3),
])
def test_invalid_clock_or_expiry_never_passes(last, now, expiry):
    emitted, reason = _module().gate(last, now, expiry_s=expiry)
    assert emitted == (0, 0) and reason != 'pass'


@pytest.fixture
def ros_boundary(monkeypatch):
    """Execute actual entrypoint callbacks with synthetic ROS ports, never DDS."""
    evidence = {'published': [], 'publisher_topics': [], 'timer': None,
                'namespace': '/rosy_01', 'domain': 120, 'remap': None}

    class Twist:
        def __init__(self):
            self.linear = SimpleNamespace(x=0., y=0., z=0.)
            self.angular = SimpleNamespace(x=0., y=0., z=0.)

    def publisher(_type, topic, _depth):
        evidence['publisher_topics'].append(topic)
        return SimpleNamespace(publish=lambda message: evidence['published'].append(
            (message.linear.x, message.angular.z)))

    def subscription(_type, _topic, callback, _depth):
        evidence['on_command'] = callback

    def timer(_period, callback, **kwargs):
        evidence['timer'] = kwargs.get('clock')
        evidence['tick'] = callback
        return SimpleNamespace(cancel=lambda: None)

    node = SimpleNamespace(get_namespace=lambda: evidence['namespace'],
                           resolve_topic_name=lambda topic: evidence['remap'] or topic,
                           create_publisher=publisher, create_subscription=subscription,
                           create_timer=timer, destroy_node=lambda: None,
                           get_logger=lambda: SimpleNamespace(debug=lambda *args: None))
    clock = SimpleNamespace(Clock=lambda **kwargs: kwargs['clock_type'],
                            ClockType=SimpleNamespace(STEADY_TIME='steady'))
    ros = SimpleNamespace(init=lambda **kwargs: None, create_node=lambda *args: node,
                          get_default_context=lambda: SimpleNamespace(get_domain_id=lambda: evidence['domain']),
                          shutdown=lambda: None, spin=lambda _: evidence['spin']())
    monkeypatch.setitem(sys.modules, 'rclpy', ros)
    monkeypatch.setitem(sys.modules, 'rclpy.clock', clock)
    monkeypatch.setitem(sys.modules, 'geometry_msgs', SimpleNamespace())
    monkeypatch.setitem(sys.modules, 'geometry_msgs.msg', SimpleNamespace(Twist=Twist))
    for name, value in {'ROS_DOMAIN_ID': '120', 'GZ_PARTITION': 'd426-test',
                        'ROS_LOCALHOST_ONLY': '1', 'ROSY_RUNTIME_MODE': 'core'}.items():
        monkeypatch.setenv(name, value)
    evidence['spin'] = lambda: None
    return evidence, Twist


@pytest.mark.parametrize('linear,angular', [
    (float('nan'), 0), (float('inf'), 0), (.2, 0), (0, .6),
])
def test_runtime_invalid_commands_zero_and_timer_is_steady(ros_boundary, monkeypatch, linear, angular):
    evidence, Twist = ros_boundary
    mod = _module()
    monkeypatch.setattr(mod.time, 'monotonic', lambda: 100.)

    def spin():
        message = Twist()
        message.linear.x, message.angular.z = linear, angular
        evidence['on_command'](message)
        evidence['tick']()

    evidence['spin'] = spin
    assert mod.main(['command_watchdog.py', '--sim-only']) == 0
    assert evidence['published'] == [(0., 0.)]
    assert evidence['timer'] == 'steady'
    assert evidence['publisher_topics'] == ['/rosy_01/cmd_vel_watchdog']


@pytest.mark.parametrize('setting,value', [
    ('ROS_DOMAIN_ID', '40'), ('ROS_LOCALHOST_ONLY', '0'),
    ('GZ_PARTITION', ''), ('ROSY_RUNTIME_MODE', 'hardware'),
    ('namespace', '/'), ('consent', 'missing'),
])
def test_runtime_scope_fails_before_command_publisher(ros_boundary, monkeypatch, setting, value):
    evidence, _ = ros_boundary
    if setting == 'namespace':
        evidence['namespace'] = value
    elif setting != 'consent':
        monkeypatch.setenv(setting, value)
    args = ['command_watchdog.py'] + ([] if setting == 'consent' else ['--sim-only'])
    assert _module().main(args) == 3
    assert not evidence['publisher_topics'] and not evidence['published']


def test_runtime_valid_planar_command_then_monotonic_expiry(ros_boundary, monkeypatch):
    evidence, Twist = ros_boundary
    evidence['namespace'] = '/rosy_01/'
    mod = _module()
    times = iter([100., 100.1, 100.4])
    monkeypatch.setattr(mod.time, 'monotonic', lambda: next(times))

    def spin():
        message = Twist()
        message.linear.x, message.angular.z = .1, .2
        evidence['on_command'](message)
        evidence['tick']()
        evidence['tick']()

    evidence['spin'] = spin
    assert mod.main(['command_watchdog.py', '--sim-only']) == 0
    assert evidence['published'] == [(.1, .2), (0., 0.)]
    assert evidence['publisher_topics'] == ['/rosy_01/cmd_vel_watchdog']
    assert evidence['timer'] == 'steady'


@pytest.mark.parametrize('field,value', [('domain', 40), ('remap', '/cmd_vel')])
def test_actual_ros_resolution_cannot_escape_isolated_scope(ros_boundary, field, value):
    evidence, _ = ros_boundary
    evidence[field] = value
    assert _module().main(['command_watchdog.py', '--sim-only']) == 3
    assert not evidence['publisher_topics'] and not evidence['published']
