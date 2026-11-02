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


def test_disconnect_after_motion_applies_zero(drive, monkeypatch):
    from threading import Event
    import core_api_web.api.ws as ws_module

    zero_applied = Event()
    real_apply = ws_module.apply_teleop

    def observe_apply(request, auth, services):
        result = real_apply(request, auth, services)
        if request.linear == 0.0 and request.angular == 0.0:
            zero_applied.set()
        return result

    monkeypatch.setattr(ws_module, "apply_teleop", observe_apply)
    tc, svc = drive()
    with tc.websocket_connect(TELEOP) as socket:
        socket.send_text(json.dumps({"type": "auth", "token": OPERATOR}))
        socket.send_text(_frame(1, 0.1))
        assert socket.receive_json()["accepted"] is True
        assert svc.command.select_output().linear == pytest.approx(0.1)
        # TestClient cancels the ASGI task on context exit; observe disconnect cleanup first.
        socket.close()
        assert zero_applied.wait(1), "disconnect did not apply an explicit zero command"
    assert svc.command.select_output().linear == 0.0


@pytest.mark.parametrize("cancel_method", ["anyio-scope", "asyncio-task", "asyncio-during-zero"])
def test_cancelled_teleop_handler_applies_explicit_zero(drive, monkeypatch, cancel_method):
    import asyncio
    from threading import Event
    from types import SimpleNamespace

    import anyio
    import core_api_web.api.ws as ws_module

    tc, svc = drive()
    auth = ws_module.authenticate(svc.config, None, OPERATOR)
    zero_applied = Event()
    real_apply = ws_module.apply_teleop

    async def authorize(_socket, **_kwargs):
        return svc

    def observe_apply(request, context, services):
        result = real_apply(request, context, services)
        if request.linear == 0.0 and request.angular == 0.0:
            zero_applied.set()
        return result

    monkeypatch.setattr(ws_module, "_authorize", authorize)
    monkeypatch.setattr(ws_module, "apply_teleop", observe_apply)

    async def exercise():
        acknowledged = anyio.Event()
        zero_started = anyio.Event()
        release_zero = anyio.Event()
        handler_task = []
        real_pool = ws_module.run_in_threadpool

        async def gated_pool(func, request, context, services):
            if cancel_method == "asyncio-during-zero" and request.linear == request.angular == 0.0:
                zero_started.set()
                await release_zero.wait()
            return await real_pool(func, request, context, services)

        monkeypatch.setattr(ws_module, "run_in_threadpool", gated_pool)

        class Socket:
            app = tc.app
            state = SimpleNamespace(token_id=auth.token_id, auth=auth)
            sent = False

            async def receive_text(self):
                if not self.sent:
                    self.sent = True
                    return _frame(1, 0.1)
                await anyio.sleep_forever()

            async def send_json(self, message):
                assert message["accepted"] is True
                acknowledged.set()

        async def handle():
            handler_task.append(asyncio.current_task())
            await ws_module.ws_teleop(Socket())

        async with anyio.create_task_group() as group:
            group.start_soon(handle)
            with anyio.fail_after(2):
                await acknowledged.wait()
            assert svc.command.select_output().linear == pytest.approx(0.1)
            if cancel_method == "anyio-scope":
                group.cancel_scope.cancel()
            else:
                handler_task[0].cancel()
                if cancel_method == "asyncio-during-zero":
                    with anyio.fail_after(2):
                        await zero_started.wait()
                    handler_task[0].cancel()
                    await anyio.sleep(0)
                    release_zero.set()
        assert zero_applied.is_set(), "handler cancellation bypassed the explicit zero"
        assert svc.command.select_output().linear == 0.0
        assert handler_task[0].cancelled(), "cleanup must preserve caller cancellation"

    anyio.run(exercise)


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
