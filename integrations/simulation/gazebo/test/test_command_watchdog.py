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
from pathlib import Path

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
                            text=True, encoding="utf-8")
    # rclpy 가 있으면 실행되고, 없으면 안내 후 exit 3 — 어느 쪽이든 crash는 아니다.
    assert result.returncode in (0, 3)
