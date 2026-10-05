"""D-426 Task 5 — 시나리오·정지 판정 계약 (host, ROS-free). 실패 시험 먼저(규칙 5).

- M01–M08 수용 행렬이 온전히 정의됐는지(누락 시나리오 없이)
- 주입은 run 소유 경계만, REST/WS/둘 다 blackhole은 별도 회차로 구분
- D-419 정책 적용 시한(5.2 s)과 실제 정지(0.50 s·0.05 m·0.25 rad)를 같은
  시한으로 쓰지 않는다 — 지연·이동·회전 각각 따로 FAIL
- 시뮬 profile 상한은 0.15 m/s·0.5 rad/s로 고정, 몰래 완화하지 않는다
"""

from __future__ import annotations

import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1] / "tools" / "validation" / "fleet_gazebo"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from scenarios import (  # noqa: E402
    CORE_KILL_INPUT_EXPIRY_S,
    FLEET_LOSS_POLICY_WINDOW_S,
    SIM_PROFILE,
    STOP_LIMITS,
    Blackout,
    acceptance_matrix,
    stop_policy_checks,
)
from fleet.server.traffic_reservations import segment_state  # noqa: E402,F401 — 회차 판정과 같은 DB


def test_acceptance_matrix_covers_m01_through_m08():
    scenarios = {row.scenario_id: row for row in acceptance_matrix()}
    assert sorted(scenarios) == [f"M{i:02d}" for i in range(1, 9)]
    # 각 회차는 필수 판정을 하나 이상 요구한다.
    for scenario_id, scenario in scenarios.items():
        assert scenario.requires, scenario_id


def test_blackouts_are_run_scoped_and_split_into_separate_rounds():
    scenarios = {row.scenario_id: row for row in acceptance_matrix()}
    m05 = scenarios["M05"]
    kinds = {blackout.kind for blackout in m05.blackouts}
    assert kinds == {"rest", "ws", "both"}
    for blackout in m05.blackouts:
        assert blackout.scope == "run"
    # REST-only·WS-only·둘 다는 별도 회차 — 한 회차에 하나의 주입만 실린다.
    assert len({(b.kind, b.target) for b in m05.blackouts}) == 3


def test_unknown_blackout_kind_or_scope_is_rejected():
    import pytest

    with pytest.raises(ValueError):
        Blackout("carrier-pigeon", "robot:rosy_01")
    with pytest.raises(ValueError):
        Blackout("rest", "robot:rosy_01", scope="whole-machine")


def test_sim_profile_and_limits_are_pinned():
    assert SIM_PROFILE == {"v_max_mps": 0.15, "w_max_radps": 0.5}
    assert FLEET_LOSS_POLICY_WINDOW_S == 5.2
    assert STOP_LIMITS == {"stop_time_s": 0.50, "travel_m": 0.05, "rotation_rad": 0.25}
    assert CORE_KILL_INPUT_EXPIRY_S == 0.30


def test_stop_policy_check_separates_application_and_physical_stop():
    good = stop_policy_checks(last_hub_receipt_mono=0.0, policy_applied_mono=5.0,
                              stopped_at_mono=5.3, travel_m=0.03, rotation_rad=0.1)
    assert good["ok"] is True
    late = stop_policy_checks(last_hub_receipt_mono=0.0, policy_applied_mono=6.0,
                              stopped_at_mono=6.3, travel_m=0.03, rotation_rad=0.1)
    assert late["ok"] is False and any("window" in p for p in late["problems"])
    slow_stop = stop_policy_checks(last_hub_receipt_mono=0.0, policy_applied_mono=5.0,
                                   stopped_at_mono=6.0, travel_m=0.03, rotation_rad=0.1)
    assert slow_stop["ok"] is False and any("stop took" in p for p in slow_stop["problems"])
    overshot = stop_policy_checks(last_hub_receipt_mono=0.0, policy_applied_mono=5.0,
                                  stopped_at_mono=5.3, travel_m=0.2, rotation_rad=0.1)
    assert overshot["ok"] is False and any("traveled" in p for p in overshot["problems"])
    spun = stop_policy_checks(last_hub_receipt_mono=0.0, policy_applied_mono=5.0,
                              stopped_at_mono=5.3, travel_m=0.03, rotation_rad=0.9)
    assert spun["ok"] is False and any("rotated" in p for p in spun["problems"])


def test_m06_restarts_are_named_processes():
    scenarios = {row.scenario_id: row for row in acceptance_matrix()}
    restarts = scenarios["M06"].restarts
    assert "fleet" in restarts and any(r.startswith("core:") for r in restarts)
