"""D-149: safety_node 를 시작하는 launch 는 'core 옆 실행 금지' 마커를 문서로 갖는다.

control 의 safety_node 는 단독 모드에서 최종 ``cmd_vel`` 을 발행한다(계약된
예외). 이 예외가 CORE 단일 발행자(D-2/D-38)와 조용히 병존하지 않도록, 최종
발행을 만들 수 있는 모든 launch 파일이 경고 마커를 상단 문서로 가져야 한다.
ROS 오버레이 없이 도는 텍스트 구조 검사다.
"""

from __future__ import annotations

import re
from pathlib import Path

LAUNCH = Path(__file__).resolve().parents[1] / "launch"

#: robot.launch.py 상단 문구의 원형. 문서·launch 양쪽에서 같은 말을 쓴다.
MARKER = re.compile(r"beside core|core 옆", re.IGNORECASE)


def launches_starting_safety_node():
    for path in sorted(LAUNCH.glob("*.launch.py")):
        text = path.read_text(encoding="utf-8")
        if "safety_node" in text:
            yield path.name, text


def test_every_safety_node_launch_carries_the_marker():
    offenders = [
        name for name, text in launches_starting_safety_node()
        if not MARKER.search(text)
    ]
    assert not offenders, (
        "최종 cmd_vel 을 만들 수 있는 launch 는 'beside core' 금지 마커를 "
        "문서로 가져야 한다 (D-149): " + ", ".join(offenders)
    )


def test_at_least_one_launch_starts_safety_node():
    # 계약 대상이 0개가 되면 이 검사는 조용히 초록이 된다 — 그 상태를 잡는다.
    assert list(launches_starting_safety_node()), (
        "safety_node 를 시작하는 launch 가 없다 — D-149 계약 범위를 다시 확인하라"
    )
