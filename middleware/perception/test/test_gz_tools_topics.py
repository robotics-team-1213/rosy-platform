"""tools/gz 벤치 도구는 절대 토픽을 **발행**하지 않는다 (D-4).

namespace 없이 실행하면 상대 이름은 전역으로 풀려 지금과 동일하게 동작하고,
네임스페이스 안에서 실행하면 로봇 네임스페이스로 바르게 풀린다 — 절대 이름은
두 경우 중 한 경우만 옳다. 단일 발행자 원칙(D-2/D-149)의 예외 목록에 벤치
드라이버가 무단으로 들어 있는 것도 같은 문제다(통신 보고서 §3.2.1).

구독은 제외한다 — 대상이 실제로 절대 이름인 경우(예:
rendered_camera_adapter 의 /pinky/rendered_camera, /tf)가 있어서다.
"""
import re
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1] / "tools" / "gz"

#: `create_publisher(<Type>, '<topic>', ...)` 의 토픽이 '/' 로 시작하면 위반.
PUB_ABS = re.compile(r"create_publisher\(\s*[\w.]+\s*,\s*['\"]/")


def test_no_absolute_publisher_topics_in_gz_tools():
    offenders = []
    for path in sorted(TOOLS.glob("*.py")):
        for lineno, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), 1):
            if PUB_ABS.search(line):
                offenders.append(f"{path.name}:{lineno}: {line.strip()}")
    assert not offenders, (
        "absolute publisher topics in bench tools:\n" + "\n".join(offenders))
