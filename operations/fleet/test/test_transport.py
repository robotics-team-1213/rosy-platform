"""HttpRobotClient — 로봇 REST 를 부르는 유일한 곳. 에러 본문은 ERR-101 형식이다."""

import asyncio
import json
import logging

import httpx
import pytest

from core_common.protocol.schemas import SwarmFollowParams
from fleet.swarm.robots import RobotEndpoint
from fleet.swarm.transport import (
    HttpRobotClient,
    RobotApiError,
    RobotClient,
    _as_event,
    _as_text,
    _rejection,
)

EP = RobotEndpoint("rosy_02", "http://robot:8080", "op-token")


def run(coro):
    return asyncio.run(coro)


def _client(handler):
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=EP.base_url)
    return HttpRobotClient(EP, http=http)


def test_it_satisfies_the_protocol():
    assert isinstance(_client(lambda r: httpx.Response(200, json={})), RobotClient)


def test_power_health_uses_authenticated_read_only_route():
    seen = {}

    def handler(request):
        seen.update(method=request.method, path=request.url.path,
                    auth=request.headers.get("authorization"))
        return httpx.Response(200, json={"battery": {"charging_state": "unconfirmed"}})

    assert run(_client(handler).power_health())["battery"]["charging_state"] == "unconfirmed"
    assert seen == {"method": "GET", "path": "/api/v1/power/health",
                    "auth": "Bearer op-token"}


def test_follow_posts_the_params_with_a_bearer_token():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"role": "follower", "active": True})

    params = SwarmFollowParams(target_robot_id="rosy_01", distance=0.6, lateral=-0.6,
                               max_speed=0.15, stream_timeout_ms=1000)
    got = run(_client(handler).follow(params))
    assert got["active"] is True
    assert seen["path"] == "/api/v1/swarm/follow"
    assert seen["auth"] == "Bearer op-token"
    assert seen["body"]["target_robot_id"] == "rosy_01"
    assert seen["body"]["lateral"] == -0.6
    assert seen["body"]["source"] == "fleet"


def test_identity_request_uses_the_enrolled_robot_credential_and_fixed_color():
    seen = {}
    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(path=request.url.path, auth=request.headers.get("authorization"),
                    body=json.loads(request.content), **({"quiet": request.url.params["quiet"]}
                                                         if "quiet" in request.url.params else {}))
        return httpx.Response(200, json={"accepted": True, "request_id": "abc"})
    assert run(_client(handler).identify_lamp("blue"))["accepted"] is True
    assert seen == {"path": "/api/v1/host/lamp/identify", "auth": "Bearer op-token",
                    "body": {"color": "blue"}}
    with pytest.raises(ValueError):
        run(_client(handler).identify_lamp("red"))
    run(_client(handler).identify_lamp("blue", quiet=True))  # D-596: automatic requests do not chirp
    assert seen["path"] == "/api/v1/host/lamp/identify" and seen["quiet"] == "true"


def test_an_error_body_becomes_a_robot_api_error_with_the_robots_code():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(409, json={"error": {"code": "DOCKING_ACTIVE",
                                                   "message": "a docking run owns navigation",
                                                   "detail": None}})

    with pytest.raises(RobotApiError) as exc:
        run(_client(handler).follow(SwarmFollowParams(target_robot_id="rosy_01")))
    assert exc.value.robot_id == "rosy_02"
    assert exc.value.status == 409
    assert exc.value.code == "DOCKING_ACTIVE"


def test_a_non_json_error_still_raises_with_an_http_code():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, text="bad gateway")

    with pytest.raises(RobotApiError) as exc:
        run(_client(handler).state())
    assert exc.value.code == "HTTP_502"


@pytest.mark.parametrize("method, path", [
    ("state", "/api/v1/robot/state"),
    ("swarm_state", "/api/v1/swarm/state"),
    ("swarm_cancel", "/api/v1/swarm/cancel"),
    ("navigation_cancel", "/api/v1/navigation/cancel"),
])
def test_each_call_hits_its_route(method, path):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["method"] = request.method
        return httpx.Response(200, json={"ok": True})

    assert run(getattr(_client(handler), method)()) == {"ok": True}
    assert seen["path"] == path
    assert seen["method"] == ("GET" if method.endswith("state") else "POST")


def test_http_estop_posts_safety_stop():
    import inspect
    from fleet.swarm.transport import HttpRobotClient
    src = inspect.getsource(HttpRobotClient.estop)
    assert "/api/v1/safety/stop" in src


def test_navigation_goal_posts_x_y_yaw():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        seen["path"] = request.url.path
        return httpx.Response(200, json={"accepted": True})

    run(_client(handler).navigation_goal(1.0, 2.0, 0.5))
    assert seen["path"] == "/api/v1/navigation/goal"
    assert seen["body"] == {"x": 1.0, "y": 2.0, "yaw": 0.5}


def test_navigation_goal_forwards_attempt_as_correlation_id():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"accepted": True})

    run(_client(handler).navigation_goal(
        1.0, 2.0, 0.5, correlation_id="attempt-123",
    ))
    assert seen["body"] == {
        "x": 1.0, "y": 2.0, "yaw": 0.5, "correlation_id": "attempt-123",
    }


def test_line_follow_mode_uses_put_and_only_forwards_ir_or_stop():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"mode": "IR_LINE", "state": "WAITING"})

    client = _client(handler)
    assert run(client.line_follow_mode("IR_LINE"))["state"] == "WAITING"
    assert seen == {"method": "PUT", "path": "/api/v1/line-follow/mode",
                    "body": {"mode": "IR_LINE"}}
    with pytest.raises(ValueError):
        run(client.line_follow_mode("CAMERA_LINE"))


def test_d601_the_trip_start_puts_camera_line_and_reads_the_front_camera_status():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path, json.loads(request.content) if request.content else None))
        if request.url.path.endswith("/front/status"):
            return httpx.Response(200, json={"available": False, "stale": True})
        return httpx.Response(200, json={"mode": "CAMERA_LINE", "state": "TRACKING"})

    client = _client(handler)
    assert run(client.line_follow_trip_start())["mode"] == "CAMERA_LINE"
    assert run(client.front_status()) == {"available": False, "stale": True}
    assert seen == [("PUT", "/api/v1/line-follow/mode", {"mode": "CAMERA_LINE"}),
                    ("GET", "/api/v1/vision/front/status", None)]


def test_line_stuck_decision_posts_the_id_and_answer_and_keeps_cores_refusal():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(method=request.method, path=request.url.path,
                    auth=request.headers.get("authorization"), body=json.loads(request.content))
        if seen["body"]["stuck_id"] == "late":
            return httpx.Response(409, json={"error": {
                "code": "STUCK_ID_MISMATCH", "message": "no open stuck with this id"}})
        return httpx.Response(200, json={"outcome": "hold"})

    client = _client(handler)
    assert run(client.line_stuck_decision("stuck-1", "WAIT"))["outcome"] == "hold"
    assert seen == {"method": "POST", "path": "/api/v1/line-follow/stuck/decision",
                    "auth": "Bearer op-token",
                    "body": {"stuck_id": "stuck-1", "decision": "WAIT"}}
    with pytest.raises(RobotApiError) as exc:
        run(client.line_stuck_decision("late", "RESUME"))
    assert (exc.value.status, exc.value.code) == (409, "STUCK_ID_MISMATCH")
    assert exc.value.message == "no open stuck with this id"


def test_yield_posts_one_segment_and_a_plain_answer_does_not():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"outcome": "yield"})

    client = _client(handler)
    assert run(client.line_stuck_decision(
        "stuck-1", "YIELD", yield_m=0.32, yield_turn_rad=-1.2))["outcome"] == "yield"
    assert seen["body"] == {"stuck_id": "stuck-1", "decision": "YIELD",
                            "yield_m": 0.32, "yield_turn_rad": -1.2}
    run(client.line_stuck_decision("stuck-1", "WAIT"))
    assert seen["body"] == {"stuck_id": "stuck-1", "decision": "WAIT"}


def test_socket_urls_point_at_the_robot_without_the_token():
    c = _client(lambda r: httpx.Response(200, json={}))
    assert c.pose_url() == "ws://robot:8080/ws/swarm/pose"
    assert c.reference_url() == "ws://robot:8080/ws/swarm/reference"
    assert c.events_url(["nav.*", "swarm.*"]) == "ws://robot:8080/ws/events?types=nav.%2A%2Cswarm.%2A"


def test_every_socket_sends_the_auth_frame_first_and_keeps_the_token_out_of_urls_and_logs(caplog):
    """D-370 S7: first-message auth (CORE ws.py _first_message_token), like dashboard and Pilot."""
    websockets = pytest.importorskip("websockets")
    token = "secret-op-token-7f3a"
    seen = []

    async def main():
        async def handler(ws):
            first = await asyncio.wait_for(ws.recv(), timeout=2)
            seen.append((ws.request.path, first))
            await ws.send('{"type": "pose"}')
            await ws.close()

        async with websockets.serve(handler, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            client = HttpRobotClient(RobotEndpoint("rosy_09", f"http://127.0.0.1:{port}", token))
            try:
                assert [f async for f in client.pose_stream()] == ['{"type": "pose"}']
                assert [e async for e in client.events(["nav.*"])] == [{"type": "pose"}]
                sink = await client.open_reference_sink()
                await sink.close()
            finally:
                await client.aclose()

    with caplog.at_level(logging.DEBUG):
        run(asyncio.wait_for(main(), timeout=10))
    assert [path for path, _ in seen] == [
        "/ws/swarm/pose", "/ws/events?types=nav.%2A", "/ws/swarm/reference"]
    assert all(json.loads(first) == {"type": "auth", "token": token} for _, first in seen)
    # The fake robot's own server log may echo the frame; the Fleet side must not.
    assert not [r for r in caplog.records
                if token in r.getMessage() and not r.name.startswith("websockets.server")]


def test_frame_text_conversion_passes_str_decodes_bytes_and_drops_garbage():
    assert _as_text("x") == "x"
    assert _as_text(b"\xea\xb0\x80") == "가"
    assert _as_text(b"\xff\xfe") is None


def test_event_conversion_keeps_only_json_objects():
    assert _as_event('{"type": "nav.stuck"}') == {"type": "nav.stuck"}
    assert _as_event("[1, 2]") is None
    assert _as_event("not json") is None
    assert _as_event(b"\xff") is None


def test_a_200_that_is_not_a_json_object_is_a_bad_response_error():
    for body_kwargs in ({"text": "<html>captive portal</html>"}, {"json": [1, 2]}):
        def handler(request: httpx.Request, kw=body_kwargs) -> httpx.Response:
            return httpx.Response(200, **kw)
        with pytest.raises(RobotApiError) as exc:
            run(_client(handler).state())
        assert exc.value.code == "BAD_RESPONSE"


def test_aclose_leaves_an_injected_client_alone():
    http = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={})),
                             base_url=EP.base_url)
    c = HttpRobotClient(EP, http=http)
    run(c.aclose())
    assert not http.is_closed
    run(http.aclose())


def test_a_socket_closed_with_4403_raises_a_robot_api_error():
    websockets = pytest.importorskip("websockets")

    async def main():
        async def handler(ws):
            await ws.close(code=4403, reason="capability swarm.lead not declared")

        async with websockets.serve(handler, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            client = HttpRobotClient(RobotEndpoint("rosy_09", f"http://127.0.0.1:{port}", "t"))
            try:
                with pytest.raises(RobotApiError) as exc:
                    async for _ in client.pose_stream():
                        pass
                assert exc.value.code == "WS_4403" and exc.value.status == 403
                with pytest.raises(RobotApiError):
                    async for _ in client.events(["nav.*"]):
                        pass
            finally:
                await client.aclose()
    run(main())


def test_an_ordinary_close_ends_the_stream_quietly():
    websockets = pytest.importorskip("websockets")

    async def main():
        async def handler(ws):
            await ws.send('{"type": "pose"}')
            await ws.close()

        async with websockets.serve(handler, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            client = HttpRobotClient(RobotEndpoint("rosy_09", f"http://127.0.0.1:{port}", "t"))
            try:
                frames = [f async for f in client.pose_stream()]
                assert frames == ['{"type": "pose"}']
            finally:
                await client.aclose()
    run(main())


def test_a_handshake_rejected_with_403_raises_ws_403_on_every_socket():
    websockets = pytest.importorskip("websockets")
    import http

    async def main():
        async def reject(connection, request):
            return connection.respond(http.HTTPStatus.FORBIDDEN, "forbidden\n")

        async def handler(ws):
            await ws.wait_closed()

        async with websockets.serve(handler, "127.0.0.1", 0, process_request=reject) as server:
            port = server.sockets[0].getsockname()[1]
            client = HttpRobotClient(RobotEndpoint("rosy_09", f"http://127.0.0.1:{port}", "t"))
            try:
                with pytest.raises(RobotApiError) as exc:
                    async for _ in client.pose_stream():
                        pass
                assert exc.value.code == "WS_403" and exc.value.status == 403
                with pytest.raises(RobotApiError) as exc2:
                    await client.open_reference_sink()
                assert exc2.value.code == "WS_403"
            finally:
                await client.aclose()
    run(main())


def test_a_websockets_without_invalid_status_degrades_to_a_quiet_end(monkeypatch, caplog):
    """package.xml 은 14 이상을 요구하지만 배포판이 더 오래된 것을 깔아 놓을 수 있다.
    `ImportError` 가 예외 처리 한가운데서 새어 나가면 거절 하나가 스트림을 죽인다."""
    ws_exc = pytest.importorskip("websockets.exceptions")
    import fleet.swarm.transport as transport

    monkeypatch.delattr(ws_exc, "InvalidStatus", raising=False)
    monkeypatch.setattr(transport, "_missing_invalid_status_logged", False)
    with caplog.at_level(logging.WARNING, logger="fleet.swarm.transport"):
        assert _rejection("rosy_09", ws_exc.WebSocketException("handshake refused")) is None
        assert _rejection("rosy_09", OSError("connection refused")) is None
    # 경고는 처음 한 번뿐이다 — 소켓마다 찍으면 재연결 로그가 그것뿐이 된다.
    assert caplog.text.count("InvalidStatus") == 1


def test_operational_client_ignores_proxy_environment(monkeypatch):
    """D-361 9: an environment proxy must never receive a robot Bearer token."""
    monkeypatch.setenv("HTTP_PROXY", "http://proxy.invalid:3128")
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.invalid:3128")
    monkeypatch.setenv("ALL_PROXY", "http://proxy.invalid:3128")
    client = HttpRobotClient(EP)
    try:
        assert client._http._trust_env is False
        assert client._http._mounts == {}
    finally:
        run(client.aclose())


def test_robot_sockets_ignore_proxy_environment(monkeypatch):
    """D-361 9: robot sockets carry the token in their first frame; no environment proxy."""
    import websockets

    seen = []

    class Refused(OSError):
        pass

    def connect(url, **kwargs):
        seen.append(kwargs)
        raise Refused("no robot here")

    monkeypatch.setattr(websockets, "connect", connect)
    client = HttpRobotClient(EP)

    async def drive():
        async for _ in client.pose_stream():
            pass
        async for _ in client.events(["x"]):
            pass
        with pytest.raises(OSError):
            await client.open_reference_sink()
        await client.aclose()

    run(drive())
    assert len(seen) == 3 and all("proxy" in kw and kw["proxy"] is None for kw in seen)


def test_a_reference_socket_refused_after_the_auth_frame_names_the_refusal():
    # CORE accepts first and then closes 4401 on a wrong first-message token.
    websockets = pytest.importorskip("websockets")

    async def main():
        async def handler(ws):
            await ws.recv()                                  # the auth frame
            await ws.close(code=4401, reason="unauthorized")

        async with websockets.serve(handler, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            client = HttpRobotClient(RobotEndpoint("rosy_09", f"http://127.0.0.1:{port}", "t"))
            try:
                sink = await client.open_reference_sink()
                reason = await asyncio.wait_for(sink.wait_closed(), 5)
                assert isinstance(reason, RobotApiError) and reason.code == "WS_4401"
                with pytest.raises(RobotApiError) as exc:
                    await sink.send('{"type": "pose"}')
                assert exc.value.code == "WS_4401"
                await sink.close()
            finally:
                await client.aclose()
    run(main())
