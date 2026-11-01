"""/ws/teleop — hold-to-drive stream: same checks as REST /teleop, ack per frame, fail-safe zero."""

import json

import pytest
from starlette.websockets import WebSocketDisconnect

OPERATOR = "rosy-dev-" + "operator"
ADMIN = "rosy-dev-" + "admin"
TELEOP = "/ws/teleop"


@pytest.fixture
def drive(core_client):
    """`(TestClient, svc)` in MANUAL with a live base."""
    def build(**kwargs):
        tc, svc = core_client(**kwargs)
        svc.state.set_velocity(0.0, 0.0)
        headers = {"Authorization": "Bearer " + OPERATOR}
        assert tc.post("/api/v1/mode", json={"mode": "MANUAL"}, headers=headers).status_code == 200
        return tc, svc
    return build


def _open(stack, tc, token=OPERATOR):
    socket = stack.enter_context(tc.websocket_connect(TELEOP))
    socket.send_text(json.dumps({"type": "auth", "token": token}))
    return socket


def _frame(seq, linear=0.1, angular=0.0):
    return json.dumps({"type": "teleop", "seq": seq, "linear": linear, "angular": angular})


def test_frames_are_applied_and_acked(drive):
    from contextlib import ExitStack
    tc, svc = drive()
    with ExitStack() as stack:
        socket = _open(stack, tc)
        socket.send_text(_frame(1, 0.1))
        assert socket.receive_json() == {"type": "ack", "seq": 1, "accepted": True, "code": None}
        assert svc.command.select_output().linear == pytest.approx(0.1)


def test_stale_seq_is_dropped_and_never_overrides(drive):
    from contextlib import ExitStack
    tc, svc = drive()
    with ExitStack() as stack:
        socket = _open(stack, tc)
        socket.send_text(_frame(5, 0.2))
        assert socket.receive_json()["seq"] == 5
        socket.send_text(_frame(3, 0.05))        # late: no ack, no effect
        socket.send_text(_frame(6, 0.15))
        assert socket.receive_json()["seq"] == 6
        assert svc.command.select_output().linear == pytest.approx(0.15)


def test_bad_frame_is_answered_without_closing(drive):
    from contextlib import ExitStack
    tc, _svc = drive()
    with ExitStack() as stack:
        socket = _open(stack, tc)
        socket.send_text("not json")
        assert socket.receive_json() == {"type": "ack", "seq": None, "accepted": False, "code": "BAD_FRAME"}
        socket.send_text(_frame(1))
        assert socket.receive_json()["accepted"] is True


def test_refusal_is_an_ack_with_the_rest_code(core_client):
    from contextlib import ExitStack
    tc, svc = core_client()
    svc.state.set_velocity(0.0, 0.0)             # IDLE: REST answers 409 MODE_CONFLICT
    with ExitStack() as stack:
        socket = _open(stack, tc)
        socket.send_text(_frame(1))
        assert socket.receive_json() == {"type": "ack", "seq": 1, "accepted": False, "code": "MODE_CONFLICT"}


def test_disconnect_after_motion_applies_zero(drive):
    tc, svc = drive()
    with tc.websocket_connect(TELEOP) as socket:
        socket.send_text(json.dumps({"type": "auth", "token": OPERATOR}))
        socket.send_text(_frame(1, 0.1))
        assert socket.receive_json()["accepted"] is True
        assert svc.command.select_output().linear == pytest.approx(0.1)
    assert svc.command.select_output().linear == 0.0


def test_socket_cap_and_same_token_replacement(drive):
    from contextlib import ExitStack
    tc, _svc = drive(config_overrides={"teleop": {"max_ws_clients": 1}})
    with ExitStack() as stack:
        first = _open(stack, tc)
        first.send_text(_frame(1))
        assert first.receive_json()["accepted"] is True
        with pytest.raises(WebSocketDisconnect) as closed:     # a second token: full
            with tc.websocket_connect(TELEOP) as extra:
                extra.send_text(json.dumps({"type": "auth", "token": ADMIN}))
                extra.receive_json()
        assert closed.value.code == 1013
        second = _open(stack, tc)                              # same token: replaces the first
        second.send_text(_frame(1))
        assert second.receive_json()["accepted"] is True
        with pytest.raises(WebSocketDisconnect) as replaced:
            first.receive_json()
        assert replaced.value.code == 4409


def test_slow_apply_is_latest_wins(drive, monkeypatch):
    import time
    from contextlib import ExitStack
    import core_api_web.api.ws as ws_module
    tc, _svc = drive()
    applied = []
    real = ws_module.apply_teleop

    def slow(request, auth, svc):
        time.sleep(0.1)
        applied.append(request.linear)
        return real(request, auth, svc)

    monkeypatch.setattr(ws_module, "apply_teleop", slow)
    with ExitStack() as stack:
        socket = _open(stack, tc)
        for seq in range(1, 11):
            socket.send_text(_frame(seq, linear=seq / 100))
        acks = {}
        while 10 not in acks:
            ack = socket.receive_json()
            acks[ack["seq"]] = ack
        assert acks[10]["accepted"] is True
        assert len(applied) < 10 and applied[-1] == pytest.approx(0.10)
        assert all(a["code"] == "SUPERSEDED" for seq, a in acks.items() if seq != 10 and not a["accepted"])
