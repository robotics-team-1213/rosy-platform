"""바퀴로 나가는 한 주기의 순서 (SAF-002).

`announce_pending` 한 줄을 지워도 모든 테스트가 초록이던 자리다. 그 줄이
없으면 조종 링크가 끊겨 로봇이 서도 `safety.watchdog` 은 영영 나오지 않는다 —
조종하던 사람에게는 그냥 멈춘 것으로 보인다.

순서도 함께 본다. 내보내기 앞에 선 것은 무엇이든 정지가 바퀴에 닿는 시각을
그만큼 뒤로 민다. 감사 로그를 다시 쓰는 구독자 하나가 초 단위로 걸린 적이
있고, 그때 SAF-002 의 300 ms 는 이미 지나가 있었다.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

import pytest
from core.bridge.cmd_vel import cmd_vel_cycle


@dataclass
class Out:
    linear: float
    angular: float


class Recorder:
    """세 참여자가 같은 로그에 자기 차례를 적는다."""

    def __init__(self, out: Out) -> None:
        self.log: list[str] = []
        self._out = out
        self.sent: list[tuple[float, float]] = []

    # command
    def select_output(self) -> Out:
        self.log.append("select")
        return self._out

    def announce_pending(self) -> None:
        self.log.append("announce")

    # power
    def on_activity(self, source: str) -> None:
        self.log.append(f"activity:{source}")

    # 바퀴
    def send(self, out: Out) -> None:
        self.log.append("wheels")
        self.sent.append((out.linear, out.angular))


class Gate:
    def __init__(self, ready: bool) -> None:
        self.ready = ready

    def is_ready(self) -> bool:
        return self.ready


def run(linear=0.2, angular=0.0, readiness=None) -> Recorder:
    rec = Recorder(Out(linear, angular))
    cmd_vel_cycle(rec, rec, rec.send, readiness)
    return rec


def test_the_chosen_output_reaches_the_wheels():
    rec = run(0.2, -0.1)

    assert rec.sent == [(0.2, -0.1)]


def test_the_lapse_is_announced_every_cycle():
    """지워지면 여기서 걸린다 — 이 파일이 존재하는 이유다."""
    assert "announce" in run().log


def test_nothing_is_announced_before_the_wheels_are_written():
    rec = run()

    assert rec.log.index("wheels") < rec.log.index("announce")


def test_the_power_policy_does_not_stand_in_front_of_the_wheels():
    """절전은 관측일 뿐이다. 관측이 정지를 늦추면 그것은 안전 결함이다."""
    rec = run()

    assert rec.log.index("wheels") < rec.log.index("activity:cmd_vel")


def test_the_order_is_select_then_wheels_then_the_rest():
    assert run().log[:2] == ["select", "wheels"]


@pytest.mark.parametrize("linear,angular", [(0.0, 0.0), (0.0, -0.0)])
def test_a_zero_output_still_reaches_the_wheels_and_still_announces(linear, angular):
    """정지도 명령이다. 0 을 안 내보내면 마지막 속도가 그대로 남는다."""
    rec = run(linear, angular)

    assert rec.sent == [(linear, angular)]
    assert "announce" in rec.log


def test_a_zero_output_is_not_activity():
    """0 을 활동으로 세면 로봇은 영영 잠들지 않는다 (PWR-002)."""
    assert not [entry for entry in run(0.0, 0.0).log if entry.startswith("activity")]


def test_a_turn_in_place_is_activity():
    assert "activity:cmd_vel" in run(0.0, 0.4).log


def test_a_hold_sends_zero_instead_of_the_chosen_output():
    """하드웨어 그래프가 HOLD 이면 낡은 후보를 흘려보내지 않는다. 그래도
    발행자는 살아 있고(0 을 보낸다), 밀린 알림도 낸다."""
    rec = run(0.2, -0.1, readiness=Gate(False))

    assert rec.sent == [(0.0, 0.0)]
    assert "announce" in rec.log
    assert not [entry for entry in rec.log if entry.startswith("activity")]


def test_a_ready_gate_passes_the_chosen_output():
    assert run(0.2, -0.1, readiness=Gate(True)).sent == [(0.2, -0.1)]


# --- 배선 자체 ----------------------------------------------------------------


def _bridge_source() -> str:
    return (Path(__file__).resolve().parents[1] / "core" / "bridge"
            / "ros_bridge.py").read_text(encoding="utf-8")


def test_the_bridge_actually_calls_the_cycle():
    """위의 검사들은 순서를 지키지만, 브리지가 그 함수를 부르는지는 모른다.

    rclpy 가 없는 호스트에서 `RosBridge` 는 import 조차 되지 않으므로, 이
    저장소가 이미 쓰는 방식(`test_initial_pose.py`)대로 소스에서 확인한다.
    이 한 줄이 사라지면 로봇은 `cmd_vel` 을 아예 내보내지 않는다 — 떼어내기
    전보다 더 큰 것이 조용히 지워질 수 있는 자리가 됐다.
    """
    text = _bridge_source()

    # 문자열이 아니라 **호출** 을 센다. 문자열 검사는 주석 처리 한 번으로
    # 만족되고(주석도 파일에 남는다), 개수로 고쳐도 들여쓰기를 박아 넣게 되어
    # 그 줄을 `if` 안으로 옮기는 멀쩡한 변경에 빨개진다.
    calls = [node for node in ast.walk(ast.parse(text))
             if isinstance(node, ast.Call)
             and getattr(node.func, "id", "") == "cmd_vel_cycle"
             and [ast.unparse(arg) for arg in node.args]
             == ["self._svc.command", "self._svc.power", "self._send_twist",
                 "self._readiness"]]

    assert len(calls) == 1, "the bridge does not call the cycle exactly once"


def test_the_bridge_still_owns_the_only_cmd_vel_publisher():
    """D-2: 바퀴로 나가는 자리는 하나다. 순서를 떼어내면서 두 번째 자리가
    생기면, 그 자리는 이 파일의 검사를 통째로 우회한다."""
    text = _bridge_source()

    assert text.count("self.cmd_vel_pub.publish(") == 1
    assert "def _send_twist(self, out: CoreTwist)" in text
