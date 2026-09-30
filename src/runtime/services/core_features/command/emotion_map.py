"""D-385: 운용 모드가 로봇 얼굴의 표정을 고른다.

상태(건강)는 색·소리가 말하고(D-260), 기분은 얼굴이 말한다. 램프 패턴(D-380)과
같은 우선순위 문법을 따르되, 표정에는 깜빡임 같은 시간 축이 없다 — 모드가 바뀔
때 한 번 갈아입고 유지한다.

GIF 이름은 emotion 패키지의 어휘다(hello/basic/angry/bored/fun/happy/interest/sad).
감정 노드는 모르는 이름을 거부한다(fail closed) — 여기서도 모르는 입력은
None(지금 표정 유지)이지 추측이 아니다.
"""

from __future__ import annotations

from typing import Any, Optional

#: 모드별 기본 표정. e-stop은 mode=EMERGENCY로 오므로 별도 축이 필요 없다.
EMOTION_BY_MODE = {
    "IDLE": "basic",        # 평상심
    "MANUAL": "interest",   # 사람이 잡은 조종간에 주의를 둔다
    "NAVIGATION": "happy",  # 어딘가로 가고 있다
    "DOCKING": "fun",       # 짝 맞추기 놀이
    "EMERGENCY": "sad",     # 멈췄다 — 화를 내는 게 아니라 못 가는 것이다
}

#: 내비게이션이 막혀 있으면 기다림이 표정을 이긴다 (램프의 blocked 와 같은 입력).
NAV_STUCK_EMOTION = "bored"


def emotion_for(mode: Any, nav_state: Any = None) -> Optional[str]:
    """The face for this operating mode, or None to keep the current one.

    우선순위: 막힌 내비게이션(bored) > 모드별 표정. 모르는 모드는 None —
    표정을 지어맞히지 않는다.
    """
    if not isinstance(mode, str) or mode not in EMOTION_BY_MODE:
        return None
    if mode == "NAVIGATION" and nav_state in ("BLOCKED", "FAILED"):
        return NAV_STUCK_EMOTION
    return EMOTION_BY_MODE[mode]
