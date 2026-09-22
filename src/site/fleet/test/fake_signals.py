"""신호등 가짜 — 네트워크 없이 SignalConsole/엔드포인트를 돌린다.

장치의 최소 규칙만 흉내 낸다: 단조 `seq` 검사(409 stale_seq), 인증(403),
충돌 가드(400 conflict), 그리고 상태 보고. 펌웨어를 대체하지 않는다 — 계약의
응답 모양을 고정하는 것이 목적이다.
"""

from __future__ import annotations

from typing import Optional

from fleet.server.signals import SignalApiError, SignalStatus


class FakeSignal:
    def __init__(self, signal_id: str, *, mode: str = "manual",
                 lamps: Optional[dict] = None, token: str = "t") -> None:
        self.signal_id = signal_id
        self.token = token
        self.mode = mode
        self.lamps = lamps if lamps is not None else {
            "red": True, "yellow": False, "green": False}
        self.faults: list[str] = []
        self.last_seq = 0
        self.status_error: Optional[Exception] = None
        self.commands: list[dict] = []
        self.command_error: Optional[Exception] = None

    # --- SignalClient protocol --------------------------------------------------

    def _status(self) -> SignalStatus:
        return SignalStatus(
            signal_id=self.signal_id,
            mode=self.mode,
            lamps=dict(self.lamps),
            seq=self.last_seq,
            faults=tuple(self.faults),
            secs_since_contact=0,
            firmware="1.0.0",
        )

    async def status(self) -> SignalStatus:
        if self.status_error is not None:
            raise self.status_error
        return self._status()

    async def command(self, body: dict) -> SignalStatus:
        if self.command_error is not None:
            raise self.command_error
        seq = body.get("seq")
        if not isinstance(seq, int) or seq <= self.last_seq:
            raise SignalApiError(self.signal_id, 409, "stale_seq",
                                 "seq is not ahead of the device", self.last_seq)
        if body.get("mode") == "manual":
            lamps = body.get("lamps") or {}
            if lamps.get("red") and lamps.get("green"):
                raise SignalApiError(self.signal_id, 400, "conflict",
                                     "red and green together is refused")
        self.last_seq = seq
        self.mode = body.get("mode", self.mode)
        if "lamps" in body:
            self.lamps = dict(body["lamps"])
        if self.mode == "all_red":
            self.lamps = {"red": True, "yellow": False, "green": False}
        self.commands.append(dict(body))
        return self._status()

    async def aclose(self) -> None:
        return None


class FakeObserver:
    """관측 서비스 가짜 — `/observed` 본문 모양(2026-09-22 v0.3)을 고정한다.

    관측은 읽기 전용이라 명령이 없다 — 성공 응답 한 가지와 오류 한 가지면 충분하다.
    """

    def __init__(self, body: Optional[dict] = None, *,
                 error: Optional[Exception] = None) -> None:
        self.body = body if body is not None else observed_body()
        self.error = error
        self.calls = 0

    async def observed(self) -> dict:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return dict(self.body)

    async def aclose(self) -> None:
        return None


def observed_body(*, lamps: Optional[dict] = None, pending: bool = False,
                  frozen: bool = False, frame_id: int = 1,
                  age_s: float = 0.0) -> dict:
    """관측 `/observed` 본문 — `lamps`(날 판정)와 `stable`(debounce) 두 층 고정."""
    if lamps is None:
        # 기본: red 램프 ROI("left") 하나만 켜져 있고 확정까지 끝났다.
        lamps = {"left": {"lit": True, "group": "red", "confidence": 1.0}}
    stable = {name: {"lit": row["lit"], "group": row["group"], "pending": pending}
              for name, row in lamps.items()}
    if frozen:
        stable = {name: {"lit": None, "group": None, "pending": True, "stale": True}
                  for name in lamps}
    return {"ts": 1000.0, "frame_id": frame_id, "captured_at": 1000.0,
            "age_s": age_s, "frozen": frozen, "lamps": lamps, "stable": stable}
