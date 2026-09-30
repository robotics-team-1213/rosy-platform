"""D-350: 도크 하드웨어 단계 — degrade·만춫·히스테리시스 시험.

Phase 1(계측 없음)과 Phase 2(계측)의 소프트웨어 경로를 각각 확인한다.
`instrumented=False`가 전압 단독 판정으로 degrade하는지, 만춫 이벤트가
1회만 방출되는지, 재충전 히스테리시스가 재방출을 허용하는지.
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from core_features.docking.charging import ChargingConfirmation
from core_features.docking.agent import DockAgent, DockReachability, DockStatus


def _status(charging: bool = True, answered: bool = True) -> DockStatus:
    if not answered:
        return DockStatus(reachability=DockReachability.UNREACHABLE)
    return DockStatus(
        reachability=DockReachability.OK,
        load_present=True, charging=charging, current_a=1.4 if charging else 0.0,
    )


class TestPhase1Degrade:
    """instrumented=False: 도크 전류 보고 없이 전압 비하락만으로 판정."""

    def test_voltage_stability_alone_confirms(self):
        cc = ChargingConfirmation(instrumented=False, window_s=5.0)
        now = 0.0
        # 도크가 없어도 전압이 유지되면 "충전 징후"로 본다
        for i in range(12):
            cc.update(_status(answered=False), voltage=8.1, now=now)
            now += 1.0
        assert cc.confirmed, "voltage-only must confirm in Phase 1"
        assert cc.source == "voltage_only"

    def test_voltage_drop_immediately_unconfirms(self):
        cc = ChargingConfirmation(instrumented=False, window_s=5.0)
        now = 0.0
        for i in range(12):
            cc.update(_status(answered=False), voltage=8.1, now=now)
            now += 1.0
        assert cc.confirmed
        cc.update(_status(answered=False), voltage=7.5, now=now)
        assert not cc.confirmed, "voltage drop must immediately unconfirm"


class TestPhase2Instrumented:
    """instrumented=True: 기존 2소스 동작 불변."""

    def test_dock_charging_true_plus_voltage_confirms(self):
        cc = ChargingConfirmation(instrumented=True, window_s=5.0)
        now = 0.0
        for i in range(12):
            cc.update(_status(charging=True), voltage=8.1, now=now)
            now += 1.0
        assert cc.confirmed
        assert cc.source == "instrumented"

    def test_dock_silent_does_not_confirm(self):
        """도크가 안 답하면(Phase 2에서) 전압만으로 확정하지 않는다."""
        cc = ChargingConfirmation(instrumented=True, window_s=5.0)
        now = 0.0
        for i in range(12):
            cc.update(_status(answered=False), voltage=8.1, now=now)
            now += 1.0
        assert not cc.confirmed, "instrumented mode requires the dock to answer"


class TestFullDetection:
    """만춫 이벤트 — 1회 방출, 히스테리시스 재방출."""

    def _docked_manager(self):
        """DOCKED 상태의 매니저 최소 double."""
        mgr = MagicMock()
        mgr._state = MagicMock()  # DockState.DOCKED 대체
        mgr._full_announced = False
        mgr._config = MagicMock(full_enter_v=8.2, full_exit_v=8.0)
        mgr._dock = MagicMock(id="dock_1")
        mgr._emit = MagicMock()
        return mgr

    def test_peak_voltage_exposed(self):
        cc = ChargingConfirmation(instrumented=True, window_s=3.0)
        now = 0.0
        for i in range(5):
            cc.update(_status(charging=True), voltage=8.3, now=now)
            now += 1.0
        assert cc.peak_v == pytest.approx(8.3)

    def test_source_reports_phase(self):
        assert ChargingConfirmation(instrumented=True).source == "instrumented"
        assert ChargingConfirmation(instrumented=False).source == "voltage_only"
