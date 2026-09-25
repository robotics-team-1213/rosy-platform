"""SWM-003 리더 pose 스트림과 팔로워 참조 스트림 입구 (API Ref §7.8).

두 소켓이 같은 envelope 을 쓰는 것이 이 이야기의 요점이다. 리더의
`/ws/swarm/pose` 출력을 팔로워의 `/ws/swarm/reference` 에 그대로 넣을 수
있어야, 추종 로직이 소스를 묻지 않는다는 SWM-007 이 말이 아니라 성질이 된다.
"""

from __future__ import annotations

import json

import pytest
from core_common.protocol.schemas import EnvelopeType

ADMIN_TOKEN = "rosy-dev-admin"
OPERATOR_TOKEN = "rosy-dev-operator"
VIEWER_TOKEN = "rosy-dev-viewer"

LEADS = {"swarm": {"follow": True, "lead": True}}


@pytest.fixture
def client(core_client):
    return core_client(capabilities=LEADS)


class RecordingNav:
    """세션 토큰 규약을 지키는 최소 구현 (실제 NavigationManager 와 같은 계약)."""

    def __init__(self) -> None:
        self.goals = []
        self.cancels = []
        self._session = None
        self._counter = 0
        # NavigationManager 가 선언하는 것과 같은 이름. double 이
        # 계약의 일부만 들고 있으면 그 부분은 더 이상 테스트되지 않는다.
        self.mapping_active = False

    def open_moving_session(self):
        self._counter += 1
        self._session = self._counter
        return self._session

    def moving_goal(self, spec, source="swarm", session=None):
        if session is not None and session != self._session:
            return False
        self.goals.append(spec)
        return True

    def cancel(self, source="api", close_session=True, session=None):
        if session is not None and session != self._session:
            return
        self.cancels.append(source)
        if close_session:
            self._session = None


def follow(tc, target="rosy_02"):
    response = tc.post(
        "/api/v1/swarm/follow",
        json={"target_robot_id": target, "distance": 0.5, "lateral": 0.0},
        headers={"Authorization": f"Bearer {OPERATOR_TOKEN}"},
    )
    assert response.status_code == 200


def pose_frame(robot_id="rosy_02", x=1.0, y=2.0, yaw=0.0, seq=1, map_id=None):
    payload = {"robot_id": robot_id, "pose": {"x": x, "y": y, "yaw": yaw}, "seq": seq}
    if map_id is not None:
        payload["map_id"] = map_id
    return {
        "protocol_version": "1.0",
        "msg_id": "test",
        "type": "pose",
        "ts": "2026-09-06T00:00:00Z",
        "payload": payload,
    }


# --- SWM-003 리더 pose 스트림 ---------------------------------------------------


def test_the_leader_stream_sends_the_contract_envelope(client):
    tc, svc = client
    svc.state.set_pose(1.5, -0.25, 0.75)

    with tc.websocket_connect(f"/ws/swarm/pose?token={VIEWER_TOKEN}") as socket:
        frame = socket.receive_json()

    assert frame["type"] == EnvelopeType.POSE.value
    assert frame["protocol_version"] == "1.0"
    assert frame["msg_id"] and frame["ts"]
    assert frame["payload"]["robot_id"] == svc.identity.robot_id
    assert frame["payload"]["pose"] == {"x": 1.5, "y": -0.25, "yaw": 0.75}
    assert frame["payload"]["seq"] == 1


def test_the_leader_stream_advances_its_sequence(client):
    tc, _svc = client

    with tc.websocket_connect(f"/ws/swarm/pose?token={VIEWER_TOKEN}") as socket:
        first = socket.receive_json()
        second = socket.receive_json()

    assert second["payload"]["seq"] == first["payload"]["seq"] + 1


def test_the_leader_rate_cannot_be_configured_below_the_requirement(core_client):
    """SWM-003 의 10 Hz 는 하한이다. 설정으로 내려가면 대형이 흔들린다."""
    tc, _svc = core_client(capabilities=LEADS,
                           config_overrides={"swarm": {"pose_rate_hz": 1.0}})

    import time

    frames = 20
    with tc.websocket_connect(f"/ws/swarm/pose?token={VIEWER_TOKEN}") as socket:
        socket.receive_json()
        started = time.monotonic()
        for _ in range(frames):
            socket.receive_json()
        elapsed = time.monotonic() - started

    achieved = frames / elapsed
    # 서버는 마감시각을 따라가므로 예약 주기는 정확히 1/rate 다. 남는 오차는
    # TestClient 가 같은 프로세스에서 프레임을 받아가는 비용이다. 보낸 뒤에
    # period 만큼 자던 예전 구현은 여기서 ~9.2 Hz 로 측정됐다.
    assert achieved >= 9.5, f"SWM-003 asks for >=10 Hz; measured {achieved:.2f} Hz"


# --- 참조 스트림 입구 -----------------------------------------------------------


def test_a_reference_frame_reaches_the_swarm_manager(client):
    tc, svc = client
    svc.swarm.nav = RecordingNav()
    follow(tc)

    with tc.websocket_connect(f"/ws/swarm/reference?token={OPERATOR_TOKEN}") as socket:
        socket.send_text(json.dumps(pose_frame(x=1.0, y=0.0, yaw=0.0)))
        socket.send_text(json.dumps({"type": "ping"}))  # 응답을 기다릴 순서 보장용

    assert len(svc.swarm.nav.goals) == 1
    assert svc.swarm.nav.goals[0].x == pytest.approx(0.5)  # 1.0 - distance 0.5


def test_a_leader_frame_can_be_fed_straight_into_a_follower(client):
    """리더 소켓의 출력이 팔로워 소켓의 입력이다 (SWM-007)."""
    tc, svc = client
    svc.swarm.nav = RecordingNav()
    svc.state.set_pose(4.0, 0.0, 0.0)

    with tc.websocket_connect(f"/ws/swarm/pose?token={VIEWER_TOKEN}") as leader:
        emitted = leader.receive_json()

    follow(tc, target=emitted["payload"]["robot_id"])
    with tc.websocket_connect(f"/ws/swarm/reference?token={OPERATOR_TOKEN}") as socket:
        socket.send_text(json.dumps(emitted))
        socket.send_text(json.dumps({"type": "ping"}))

    assert len(svc.swarm.nav.goals) == 1
    assert svc.swarm.nav.goals[0].x == pytest.approx(3.5)


@pytest.mark.parametrize("frame", [
    {"type": "heartbeat", "payload": {}},
    {"type": "pose"},
    {"type": "pose", "payload": {"robot_id": "rosy_02"}},
    {"type": "pose", "payload": {"robot_id": "", "pose": {"x": 1, "y": 1, "yaw": 0}}},
    {"type": "pose", "payload": {"robot_id": "rosy_02", "pose": {"x": "nope", "y": 1, "yaw": 0}}},
    {"type": "pose", "payload": {"robot_id": "rosy_02", "pose": {"x": 1}}},
    [1, 2, 3],
])
def test_a_malformed_frame_is_dropped_without_closing_the_socket(client, frame):
    """한 프레임이 망가졌다고 닫으면 표본 하나가 대형을 HOLD 로 떨어뜨린다."""
    tc, svc = client
    svc.swarm.nav = RecordingNav()
    follow(tc)

    with tc.websocket_connect(f"/ws/swarm/reference?token={OPERATOR_TOKEN}") as socket:
        socket.send_text(json.dumps(frame))
        socket.send_text("this is not json at all")
        socket.send_text(json.dumps(pose_frame(x=2.0)))
        socket.send_text(json.dumps({"type": "ping"}))

    assert len(svc.swarm.nav.goals) == 1, "the socket survived and the good frame got through"
    assert svc.swarm.nav.goals[0].x == pytest.approx(1.5)


def test_a_reference_for_another_robot_changes_nothing(client):
    tc, svc = client
    svc.swarm.nav = RecordingNav()
    follow(tc, target="rosy_02")

    with tc.websocket_connect(f"/ws/swarm/reference?token={OPERATOR_TOKEN}") as socket:
        socket.send_text(json.dumps(pose_frame(robot_id="rosy_77")))
        socket.send_text(json.dumps({"type": "ping"}))

    assert svc.swarm.nav.goals == []


# --- 인증 -----------------------------------------------------------------------


@pytest.mark.parametrize("path", ["/ws/swarm/pose", "/ws/swarm/reference"])
def test_a_bad_token_is_closed_with_4401_like_ws_state(client, path, monkeypatch):
    tc, _svc = client
    from starlette.websockets import WebSocketDisconnect
    import core_api_web.api.ws as ws_module

    # No query token waits for a first-message token (D-193); do not wait 5 s for it.
    monkeypatch.setattr(ws_module, "FIRST_MESSAGE_TIMEOUT_S", 0.05)

    for query in ("", "?token=", "?token=nope"):
        with pytest.raises(WebSocketDisconnect) as raised:
            with tc.websocket_connect(f"{path}{query}") as socket:
                socket.receive_json()
        assert raised.value.code == 4401


def test_the_reference_socket_requires_an_operator(client):
    """읽기는 viewer 로 되지만, 로봇을 움직이는 스트림을 밀어 넣는 것은 아니다.

    4401 은 토큰이 없거나 틀린 것이고, 인증은 됐는데 허용되지 않는 것은 4403 이다.
    """
    tc, _svc = client
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect) as raised:
        with tc.websocket_connect(f"/ws/swarm/reference?token={VIEWER_TOKEN}") as socket:
            socket.send_text(json.dumps(pose_frame()))
            socket.receive_json()
    assert raised.value.code == 4403

    with tc.websocket_connect(f"/ws/swarm/reference?token={ADMIN_TOKEN}") as socket:
        socket.send_text(json.dumps(pose_frame()))


def test_the_leader_socket_is_closed_when_lead_is_not_declared(core_client):
    """CAP-003: 선언하지 않은 기능을 소켓으로 우회 제공하면 CAP-001 이 거짓말이 된다."""
    from starlette.websockets import WebSocketDisconnect

    tc, _svc = core_client(capabilities={"swarm": {"follow": True, "lead": False}})

    with pytest.raises(WebSocketDisconnect) as raised:
        with tc.websocket_connect(f"/ws/swarm/pose?token={VIEWER_TOKEN}") as socket:
            socket.receive_json()

    assert raised.value.code == 4403


def test_the_leader_says_which_map_its_coordinates_are_in(client):
    """좌표만 보내면 받는 쪽은 그것이 자기 맵의 좌표인지 알 수 없다 (MAP-002)."""
    tc, svc = client
    svc.state.set_map_id("site_a")

    with tc.websocket_connect(f"/ws/swarm/pose?token={VIEWER_TOKEN}") as socket:
        frame = socket.receive_json()

    assert frame["payload"]["map_id"] == "site_a"


def test_a_leader_with_no_map_sends_the_field_as_null(client):
    tc, _svc = client

    with tc.websocket_connect(f"/ws/swarm/pose?token={VIEWER_TOKEN}") as socket:
        frame = socket.receive_json()

    assert frame["payload"]["map_id"] is None


def test_the_reference_socket_carries_the_map_id_through(client):
    tc, svc = client
    svc.swarm.nav = RecordingNav()
    svc.state.set_map_id("site_a")
    follow(tc)

    with tc.websocket_connect(f"/ws/swarm/reference?token={OPERATOR_TOKEN}") as socket:
        socket.send_text(json.dumps(pose_frame(x=4.0, map_id="site_b")))
        socket.send_text(json.dumps({"type": "ping"}))

    assert svc.swarm.nav.goals == [], "a pose from another map must not become a goal"
    assert svc.swarm.state_payload()["map_mismatch"] == "site_b"
