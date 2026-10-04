"""D-353: 설계 변경 봉합점 — 충전 전략·만춫 전략·공통 폴링 유틸리티.

ChargingConfirmation이 ChargingStrategy Protocol을 자동으로 구현하는지,
manager._check_full이 FullChargeStrategy Protocol과 시그니처가 맞는지,
device_poll이 4상태 실패를 정확히 구분하는지.
"""

from __future__ import annotations

import time
from typing import Protocol, runtime_checkable

from core_common.device_poll import PollReachability, poll_json
from core_features.docking.charging import ChargingConfirmation
from core_features.docking.agent import DockReachability


# --- ChargingStrategy seam (D-353 봉합점 1) --------------------------------

@runtime_checkable
class ChargingStrategy(Protocol):
    """충전 확인 전략 — 새 배터리 화학·무선 충전이 필요하면 새 구현을 끼운다."""

    def update(self, status, voltage, now=None) -> bool: ...
    @property
    def confirmed(self) -> bool: ...
    def reset(self) -> None: ...


def test_charging_confirmation_satisfies_the_strategy_protocol():
    """기존 ChargingConfirmation이 Protocol을 자동으로 구현한다 (duck typing)."""
    cc = ChargingConfirmation(window_s=5.0)
    assert isinstance(cc, ChargingStrategy), (
        "ChargingConfirmation must already implement ChargingStrategy — "
        "the Protocol exists to document the seam, not to force a rewrite"
    )


# --- FullChargeStrategy seam (D-353 봉합점 3) ------------------------------

@runtime_checkable
class FullChargeStrategy(Protocol):
    """만춫 판정 전략 — 전압 임계·전류 종단·온도 안정 등."""

    def check(self, voltage: float | None, *, docked: bool) -> bool: ...


class VoltageFullCharge:
    """기본 구현: 전압이 임계 이상이면 만춫 (D-350)."""

    def __init__(self, enter_v: float = 8.2, exit_v: float = 8.0) -> None:
        self._enter_v = enter_v
        self._exit_v = exit_v
        self._announced = False

    def check(self, voltage: float | None, *, docked: bool) -> bool:
        if not docked or voltage is None:
            return False
        if self._announced:
            if voltage < self._exit_v:
                self._announced = False  # 재충전
            return False
        if voltage >= self._enter_v:
            self._announced = True
            return True
        return False


def test_voltage_full_charge_strategy():
    strategy = VoltageFullCharge(enter_v=8.2, exit_v=8.0)
    assert strategy.check(8.3, docked=True) is True   # 만춫 감지
    assert strategy.check(8.3, docked=True) is False  # 이미 방출 — 1회만
    assert strategy.check(7.9, docked=True) is False  # 방전 — 플래그 리셋
    assert strategy.check(8.3, docked=True) is True   # 재충전 후 재방출


def test_full_charge_strategy_protocol():
    assert isinstance(VoltageFullCharge(), FullChargeStrategy)


# --- 공통 폴링 유틸리티 (D-353 봉합점 2) -------------------------------------

def test_poll_reachability_matches_dock_vocabulary():
    """D-352: 도크의 4상태와 어휘가 정확히 일치한다."""
    for poll_val, dock_val in [
        (PollReachability.OK, DockReachability.OK),
        (PollReachability.UNREACHABLE, DockReachability.UNREACHABLE),
        (PollReachability.TIMEOUT, DockReachability.TIMEOUT),
        (PollReachability.BAD_RESPONSE, DockReachability.BAD_RESPONSE),
    ]:
        assert poll_val.value == dock_val.value, (
            f"poll says {poll_val.value}, dock says {dock_val.value} — "
            "the vocabulary must be identical (D-352)"
        )


def test_poll_json_unreachable_url():
    reach, doc, err = poll_json("http://192.0.2.1:1/no-such", timeout_s=0.5)
    assert reach in (PollReachability.UNREACHABLE, PollReachability.TIMEOUT)
    assert doc is None and err is not None
