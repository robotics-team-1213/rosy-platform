"""D-353 봉합점: 충전 확인·만춫 판정 전략 Protocol.

설계가 바뀌면 새 구현을 끼운다 — manager·ChargingConfirmation 본체는 안정화된다.
기존 ChargingConfirmation이 ChargingStrategy를 자동으로 구현한다 (duck typing).
"""

from __future__ import annotations

from typing import Optional, Protocol, runtime_checkable

from core_features.docking.agent import DockStatus


@runtime_checkable
class ChargingStrategy(Protocol):
    """충전 확인 알고리즘의 봉합점 — 새 배터리 화학·무선 충전 시 새 구현."""

    def update(self, status: DockStatus, voltage: Optional[float],
               now: Optional[float] = None) -> bool:
        """폴링 1회 반영. 확정 여부를 돌려준다."""
        ...

    @property
    def confirmed(self) -> bool: ...

    @property
    def source(self) -> str:
        """판정 근거 (D-350 Phase 표시: instrumented/voltage_only)."""
        ...

    @property
    def peak_v(self) -> Optional[float]: ...

    def reset(self) -> None: ...


@runtime_checkable
class FullChargeStrategy(Protocol):
    """만춫 판정 알고리즘의 봉합점 — 전압·전류·온도 안정 등."""

    def check(self, voltage: Optional[float], *, docked: bool) -> bool:
        """만춫을 감지하면 True (1회). 재충전 후 재방출은 구현이 관리한다."""
        ...


class VoltageFullCharge:
    """기본 만춫 판정: 전압이 임계 이상이면 만춫 (D-350).

    재충전 히스테리시스를 포함한다 — 전압이 exit_v 아래로 떨어지면
    플래그를 리셋해 다음 만춫에서 다시 True를 반환한다.
    """

    def __init__(self, enter_v: float = 8.2, exit_v: float = 8.0) -> None:
        self._enter_v = float(enter_v)
        self._exit_v = float(exit_v)
        self._announced = False

    @property
    def announced(self) -> bool:
        return self._announced

    def check(self, voltage: Optional[float], *, docked: bool) -> bool:
        if not docked or voltage is None:
            return False
        if self._announced:
            if voltage < self._exit_v:
                self._announced = False  # 재충전 — 다음 만춫에서 재방출
            return False
        if voltage >= self._enter_v:
            self._announced = True
            return True
        return False

    def reset(self) -> None:
        self._announced = False
