"""SWM-002 REST 계약: /api/v1/swarm/follow|cancel|state.

Capability 를 바꿔 끼운 클라이언트를 따로 세운다 — "미지원 로봇은
CAPABILITY_NOT_SUPPORTED"(SWM-005/CAP-003)는 지원 로봇에서는 확인할 수 없는
성질이고, 이 계약이 깨지면 Fleet 은 없는 기능을 호출한다.
"""

from __future__ import annotations

import pytest
from core_common.protocol.schemas import SwarmRole

OPERATOR = {"Authorization": "Bearer rosy-dev-operator"}
VIEWER = {"Authorization": "Bearer rosy-dev-viewer"}


@pytest.fixture
def client(core_client):
    return core_client()


FOLLOW = {"target_robot_id": "rosy_02", "distance": 0.5, "lateral": 0.0}


def test_follow_starts_a_formation_and_reports_it(client):
    tc, svc = client

    response = tc.post("/api/v1/swarm/follow", json=FOLLOW, headers=OPERATOR)

    assert response.status_code == 200
    body = response.json()
    assert body["role"] == "follower"
    assert body["active"] is True
    assert body["target_robot_id"] == "rosy_02"
    assert body["source"] == "fleet"
    assert svc.swarm.active is True


def test_follow_takes_the_robot_into_navigation_mode(client):
    """D-2: Nav2 출력은 NAVIGATION 에서만 바퀴에 닿는다 (SWM-001)."""
    tc, svc = client

    tc.post("/api/v1/swarm/follow", json=FOLLOW, headers=OPERATOR)

    assert svc.state.snapshot().mode.value == "NAVIGATION"


def test_a_refused_follow_does_not_move_the_mode(client):
    """거부된 명령이 모드를 바꾸면 로봇은 목표 없이 NAVIGATION 에 앉는다."""
    tc, svc = client
    tc.post("/api/v1/safety/stop", headers=VIEWER)

    response = tc.post("/api/v1/swarm/follow", json=FOLLOW, headers=OPERATOR)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "EMERGENCY_ACTIVE"
    assert svc.state.snapshot().mode.value != "NAVIGATION"


def test_the_snapshot_carries_the_swarm_field(client):
    """SWM-006 additive 필드. Fleet 과 대시보드가 여기서 역할을 읽는다."""
    tc, _svc = client
    tc.post("/api/v1/swarm/follow", json=FOLLOW, headers=OPERATOR)

    swarm = tc.get("/api/v1/robot/state", headers=VIEWER).json()["swarm"]

    assert swarm["role"] == SwarmRole.FOLLOWER.value
    assert swarm["active"] is True
    assert swarm["formation"].startswith("follow:rosy_02")


def test_cancel_clears_the_role(client):
    tc, svc = client
    tc.post("/api/v1/swarm/follow", json=FOLLOW, headers=OPERATOR)

    body = tc.post("/api/v1/swarm/cancel", headers=OPERATOR).json()

    assert body["active"] is False and body["role"] == "none"
    assert svc.swarm.active is False
    assert tc.get("/api/v1/robot/state", headers=VIEWER).json()["swarm"]["active"] is False


def test_state_is_readable_before_any_follow(client):
    tc, _svc = client

    body = tc.get("/api/v1/swarm/state", headers=VIEWER).json()

    assert body == {"role": "none", "formation": None, "active": False, "holding": False,
                    "target_robot_id": None, "source": None, "max_speed": None,
                    "map_mismatch": None, "stream_age_s": None}


def test_follow_and_cancel_need_an_operator_and_state_needs_a_viewer(client):
    tc, _svc = client

    assert tc.post("/api/v1/swarm/follow", json=FOLLOW, headers=VIEWER).status_code == 403
    assert tc.post("/api/v1/swarm/cancel", headers=VIEWER).status_code == 403
    assert tc.get("/api/v1/swarm/state", headers=VIEWER).status_code == 200
    assert tc.get("/api/v1/swarm/state").status_code == 401


def test_follow_announces_the_role_and_cancel_announces_the_abort(client):
    tc, _svc = client
    tc.post("/api/v1/swarm/follow", json=FOLLOW, headers=OPERATOR)
    tc.post("/api/v1/swarm/cancel", headers=OPERATOR)

    types = [event["type"] for event in tc.get("/api/v1/events", headers=VIEWER).json()["events"]]

    assert "swarm.role_assigned" in types
    assert "swarm.aborted" in types


def test_a_robot_that_does_not_declare_follow_answers_501(core_client):
    """SWM-005: 미지원 로봇은 CAPABILITY_NOT_SUPPORTED 로 답한다 (CAP-003)."""
    tc, _svc = core_client(capabilities={"swarm": {"follow": False, "lead": False}})

    response = tc.post("/api/v1/swarm/follow", json=FOLLOW, headers=OPERATOR)

    assert response.status_code == 501
    assert response.json()["error"]["code"] == "CAPABILITY_NOT_SUPPORTED"
    assert tc.get("/api/v1/swarm/state", headers=VIEWER).json()["active"] is False


def test_a_reserved_peer_source_is_refused(client):
    tc, _svc = client

    response = tc.post("/api/v1/swarm/follow", json={**FOLLOW, "source": "peer"},
                       headers=OPERATOR)

    assert response.status_code == 501
    assert "peer" in response.json()["error"]["message"]


def test_a_max_speed_above_the_ceiling_is_refused(client):
    tc, svc = client
    ceiling = svc.safety.limits.max_linear

    response = tc.post("/api/v1/swarm/follow",
                       json={**FOLLOW, "max_speed": ceiling + 0.5}, headers=OPERATOR)

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_a_mode_conflict_leaves_no_armed_follow_behind(client):
    """거절을 받은 운영자와 '달릴 준비가 된' 로봇이 동시에 존재하면 안 된다."""
    tc, svc = client
    from core_features.command.arbitration import Mode

    svc.modes.transition(Mode.DOCKING)

    response = tc.post("/api/v1/swarm/follow", json=FOLLOW, headers=OPERATOR)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "MODE_CONFLICT"
    assert svc.swarm.active is False
    assert tc.get("/api/v1/swarm/state", headers=VIEWER).json()["active"] is False
    types = [event["type"] for event in tc.get("/api/v1/events", headers=VIEWER).json()["events"]]
    assert "swarm.role_assigned" not in types


def test_an_estop_during_a_follow_is_reported_as_such_not_as_a_mode_conflict(client):
    """가장 알려주는 바가 많은 거절 사유가 먼저 나와야 한다."""
    tc, _svc = client
    tc.post("/api/v1/safety/stop", headers=VIEWER)

    response = tc.post("/api/v1/swarm/follow", json=FOLLOW, headers=OPERATOR)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "EMERGENCY_ACTIVE"


def test_a_follow_while_docking_is_refused_at_the_door(client):
    """받아들이고 200 ms 뒤 조용히 푸는 것은 거절보다 나쁘다 — 운영자는 200 을
    보고, 로봇은 충전기 위에서 NAVIGATION 에 남는다."""
    tc, svc = client
    from core_common.protocol.schemas import DockState

    svc.docking._state = DockState.DOCKING

    response = tc.post("/api/v1/swarm/follow", json=FOLLOW, headers=OPERATOR)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "DOCKING_ACTIVE"
    assert svc.swarm.active is False
    assert svc.state.snapshot().mode.value != "NAVIGATION"


def test_a_parked_robot_can_still_be_told_to_follow(client):
    """DOCKED·CHARGING·DOCK_FAILED 는 Nav2 를 쓰지 않는다. 그것으로 막으면
    도킹 실패 한 번이 군집을 영구히 비활성화한다."""
    tc, svc = client
    from core_common.protocol.schemas import DockState

    for parked in (DockState.DOCKED, DockState.CHARGING, DockState.DOCK_FAILED):
        svc.docking._state = parked
        svc.swarm.cancel()
        response = tc.post("/api/v1/swarm/follow", json=FOLLOW, headers=OPERATOR)
        assert response.status_code == 200, parked
        svc.swarm.tick()
        assert svc.swarm.active is True, f"{parked} must not silently end the follow"


def test_a_follow_can_be_reissued_to_change_the_formation(client):
    """이미 NAVIGATION 인 것은 모드 충돌이 아니다."""
    tc, svc = client
    assert tc.post("/api/v1/swarm/follow", json=FOLLOW, headers=OPERATOR).status_code == 200

    second = tc.post("/api/v1/swarm/follow",
                     json={**FOLLOW, "distance": 0.9}, headers=OPERATOR)

    assert second.status_code == 200
    assert second.json()["formation"].endswith("@0.90/0.00")


def test_navigation_cancel_ends_the_formation(client):
    """세션만 닫히고 추종이 남으면 대형이 멀쩡해 보이는 채로 아무 일도 안 한다."""
    tc, svc = client
    tc.post("/api/v1/swarm/follow", json=FOLLOW, headers=OPERATOR)

    assert tc.post("/api/v1/navigation/cancel", headers=OPERATOR).status_code == 200

    assert svc.swarm.active is False
    assert tc.get("/api/v1/swarm/state", headers=VIEWER).json()["active"] is False
    assert tc.get("/api/v1/robot/state", headers=VIEWER).json()["swarm"]["active"] is False


def test_taking_manual_control_ends_the_formation(client):
    """운영자가 수동으로 넘어가면 대형은 끝난 것이다. 되돌려줘도 되살아나지 않는다."""
    tc, svc = client
    tc.post("/api/v1/swarm/follow", json=FOLLOW, headers=OPERATOR)

    assert tc.post("/api/v1/mode", json={"mode": "MANUAL"}, headers=OPERATOR).status_code == 200

    assert svc.swarm.active is False
    events = tc.get("/api/v1/events", headers=VIEWER).json()["events"]
    aborted = [e for e in events if e["type"] == "swarm.aborted"]
    # 감사 로그를 읽는 사람이 "주행 취소"와 "누가 수동으로 잡았다"를 구분할 수 있어야 한다.
    assert aborted and aborted[-1]["data"]["reason"] == "manual"


def test_the_session_speed_cap_goes_on_with_the_follow_and_comes_off_with_it(client):
    """SWM-002 의 max_speed 는 검증만 하는 값이 아니라 실제로 걸리는 상한이다."""
    tc, svc = client
    profile_ceiling = svc.safety.limits.max_linear

    tc.post("/api/v1/swarm/follow", json={**FOLLOW, "max_speed": 0.05}, headers=OPERATOR)

    assert svc.safety.clip(0.20, 0.0, "nav")[0] == pytest.approx(0.05)
    state = tc.get("/api/v1/safety/state", headers=VIEWER).json()
    assert state["limits"]["session_linear"] == pytest.approx(0.05)
    assert tc.get("/api/v1/swarm/state", headers=VIEWER).json()["max_speed"] == pytest.approx(0.05)

    tc.post("/api/v1/swarm/cancel", headers=OPERATOR)

    assert svc.safety.clip(0.20, 0.0, "nav")[0] == pytest.approx(profile_ceiling)
    assert tc.get("/api/v1/safety/state", headers=VIEWER).json()["limits"]["session_linear"] is None
