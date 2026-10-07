"""fleet.swarm.transport — 로봇 계약(API Ref)을 부르는 유일한 곳.

릴레이와 세션은 `RobotClient` 프로토콜만 본다. 테스트는 가짜를 끼우고, 운용은
`HttpRobotClient`(httpx + websockets) 를 끼운다. WS 이터레이터는 소켓이 닫히면
**조용히 끝난다** — 재연결은 호출자(릴레이/세션)의 정책이다. 다만 **거절된** 소켓
(핸드셰이크 거부, 또는 4401/4403 으로 닫힘) 은 `RobotApiError` 를 올린다 — 잘못된
토큰으로 재시도만 반복하는 릴레이를 조용히 방치하지 않는다.
"""

from __future__ import annotations

import json
import logging
from typing import Any, AsyncIterator, Optional, Protocol, Sequence, runtime_checkable

import httpx
from pydantic import ValidationError

from core_common.protocol.localization import CandidateReport, LocalizationDecision
from core_common.protocol.schemas import SwarmFollowParams
from fleet.swarm.robots import RobotEndpoint, ws_url

log = logging.getLogger(__name__)
# websockets dumps every frame at DEBUG, including the first-frame auth token.
# Robot sockets log through this logger, which never goes below INFO.
_ws_log = logging.getLogger(__name__ + ".websocket")
_ws_log.setLevel(logging.INFO)

#: `InvalidStatus` 가 없다는 경고는 한 번이면 된다. 소켓마다 찍으면 재연결 로그가 그것뿐이 된다.
_missing_invalid_status_logged = False


class RobotApiError(Exception):
    """로봇이 4xx/5xx 를 돌려줬다. `code` 는 ERR-101 본문의 것, 없으면 `HTTP_<status>`."""

    def __init__(self, robot_id: str, status: int, code: str, message: str) -> None:
        super().__init__(f"{robot_id}: {code} ({status}) {message}")
        self.robot_id = robot_id
        self.status = status
        self.code = code
        self.message = message


def _invalid_status_class():
    """`websockets.exceptions.InvalidStatus` (v14+) 또는 없으면 None.

    package.xml 은 14 이상을 요구하지만, 배포판이 더 오래된 것을 깔아 놓을 수 있다.
    그때 `ImportError` 가 예외 처리 **한가운데서** 새어 나가면, 거절 하나가 스트림
    전체를 죽이고 그 이유는 `InvalidStatus` 라는 엉뚱한 이름으로 남는다. 없으면
    "조용한 종료"로 떨어뜨리고(재연결은 호출자가 계속한다) 처음 한 번만 경고한다.
    """
    global _missing_invalid_status_logged
    try:
        from websockets.exceptions import InvalidStatus
    except ImportError:
        if not _missing_invalid_status_logged:
            _missing_invalid_status_logged = True
            log.warning("websockets has no exceptions.InvalidStatus (needs >= 14): "
                        "a handshake rejection will look like a quiet close")
        return None
    return InvalidStatus


def _rejection(robot_id: str, exc: BaseException) -> Optional["RobotApiError"]:
    """4401/4403 (또는 핸드셰이크 거부)만 에러로 올린다. 나머지 종료는 None — 조용히 끝난다."""
    from websockets.exceptions import ConnectionClosed

    invalid_status = _invalid_status_class()
    if invalid_status is not None and isinstance(exc, invalid_status):
        status = exc.response.status_code
        return RobotApiError(robot_id, status, f"WS_{status}", "socket rejected during handshake")
    if isinstance(exc, ConnectionClosed) and exc.rcvd is not None and exc.rcvd.code in (4401, 4403):
        code = exc.rcvd.code
        return RobotApiError(robot_id, 401 if code == 4401 else 403, f"WS_{code}",
                             exc.rcvd.reason or "socket closed by robot")
    return None


def _as_text(frame) -> Optional[str]:
    """WS 프레임 → 텍스트. 디코딩 불가면 None (버린다)."""
    if isinstance(frame, str):
        return frame
    try:
        return bytes(frame).decode("utf-8")
    except (TypeError, UnicodeDecodeError):
        return None


def _as_event(frame) -> Optional[dict]:
    """이벤트 프레임 → dict. JSON 이 아니거나 객체가 아니면 None (버린다)."""
    text = _as_text(frame)
    if text is None:
        return None
    try:
        event = json.loads(text)
    except (TypeError, ValueError):
        return None
    return event if isinstance(event, dict) else None


class ReferenceSink(Protocol):
    async def send(self, frame: str) -> None: ...
    async def close(self) -> None: ...

    async def wait_closed(self) -> BaseException:
        """Resolve when the robot closes the socket; return why (RobotApiError for 4401/4403)."""
        ...


@runtime_checkable
class RobotClient(Protocol):
    robot_id: str

    async def state(self) -> dict: ...
    async def power_health(self) -> dict: ...
    async def capabilities(self) -> dict: ...
    async def map(self) -> dict: ...
    async def swarm_state(self) -> dict: ...
    async def follow(self, params: SwarmFollowParams) -> dict: ...
    async def swarm_cancel(self) -> dict: ...
    async def navigation_cancel(self) -> dict: ...
    async def navigation_path(self) -> dict: ...

    async def navigation_goal(
        self, x: float, y: float, yaw: float, *, correlation_id: str | None = None,
    ) -> dict: ...

    async def line_follow_mode(self, mode: str) -> dict: ...
    async def line_follow(self) -> dict: ...
    async def line_follow_junction(self, action: str, place_id: str, *, stop_after_m: float | None,
                                   expires_s: float, turn_deg: float | None = None,
                                   advance_m: float | None = None, expect: dict | None = None) -> dict: ...

    async def line_stuck_decision(self, stuck_id: str, decision: str, *,
                                  yield_m: float | None = None,
                                  yield_turn_rad: float | None = None) -> dict: ...

    async def estop(self) -> dict: ...
    async def identify_lamp(self, color: str) -> dict: ...
    # D-395 Phase 2 (contract §2): Fleet-assisted localization.
    async def localization_candidates(self) -> Optional[CandidateReport]: ...
    async def localization_decision(self, decision: LocalizationDecision) -> dict: ...
    async def localization_suspect(self, reason: str) -> dict: ...

    async def localization_mission(
        self, kind: str, *, max_distance_m: float, max_time_s: float,
        target: Optional[dict] = None,
    ) -> dict: ...

    async def localization_mission_status(self) -> dict: ...

    def pose_stream(self) -> AsyncIterator[str]: ...
    async def open_reference_sink(self) -> ReferenceSink: ...
    def events(self, types: Sequence[str]) -> AsyncIterator[dict]: ...


async def require_capability(client: RobotClient, feature: str) -> None:
    """Fresh CAP-001 preflight; cached presentation never authorizes a command."""
    value = await client.capabilities()
    for part in feature.split("."):
        value = value.get(part) if isinstance(value, dict) else None
    if value is not True:
        raise RobotApiError(client.robot_id, 501, "NOT_SUPPORTED", f"{feature} is not advertised")


class _WebsocketSink:
    def __init__(self, ws, robot_id: str) -> None:
        self._ws = ws
        self._robot_id = robot_id

    def _reason(self, exc: BaseException) -> BaseException:
        return _rejection(self._robot_id, exc) or exc

    async def send(self, frame: str) -> None:
        # With first-message auth a wrong token is a 4401 close after accept, so the
        # refusal surfaces here or in wait_closed(), not when the socket opens.
        from websockets.exceptions import ConnectionClosed

        try:
            await self._ws.send(frame)
        except ConnectionClosed as exc:
            raise self._reason(exc) from exc

    async def wait_closed(self) -> BaseException:
        from websockets.exceptions import ConnectionClosed

        try:
            async for _ in self._ws:
                pass   # the reference socket carries nothing back; drain until close
        except ConnectionClosed as exc:
            return self._reason(exc)
        return ConnectionError("reference socket closed by robot")

    async def close(self) -> None:
        await self._ws.close()


class HttpRobotClient:
    def __init__(self, endpoint: RobotEndpoint, *, http: Optional[httpx.AsyncClient] = None,
                 timeout_s: float = 5.0) -> None:
        self.robot_id = endpoint.robot_id
        self._ep = endpoint
        self._owns_http = http is None
        from fleet.swarm.discovery_transport import DiscoveryTransport, tls_context
        context = tls_context(endpoint)
        options = ({'transport': DiscoveryTransport(endpoint)} if endpoint.discovery
                   else {'verify': context} if context else {})
        # trust_env=False: an environment proxy must never see the Bearer (D-361 9).
        self._http = http or httpx.AsyncClient(base_url=endpoint.base_url, timeout=timeout_s,
                                               trust_env=False, **options)

    # --- REST -----------------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._ep.token}"}

    def _check(self, resp: httpx.Response) -> dict:
        if resp.status_code < 400:
            if not resp.content:
                return {}
            try:
                data = resp.json()
            except ValueError as exc:
                raise RobotApiError(self.robot_id, resp.status_code, "BAD_RESPONSE",
                                    f"expected a JSON object, got {resp.text[:120]!r}") from exc
            if not isinstance(data, dict):
                raise RobotApiError(self.robot_id, resp.status_code, "BAD_RESPONSE",
                                    f"expected a JSON object, got {type(data).__name__}")
            return data
        code, message = f"HTTP_{resp.status_code}", resp.text
        try:
            err = resp.json().get("error") or {}
            code = str(err.get("code") or code)
            message = str(err.get("message") or message)
        except (ValueError, AttributeError):
            pass
        raise RobotApiError(self.robot_id, resp.status_code, code, message)

    async def _get(self, path: str) -> dict:
        return self._check(await self._http.get(path, headers=self._headers()))

    async def _post(self, path: str, body: Optional[dict[str, Any]] = None) -> dict:
        return self._check(await self._http.post(path, json=body, headers=self._headers()))

    async def state(self) -> dict:
        return await self._get("/api/v1/robot/state")

    async def power_health(self) -> dict:
        return await self._get("/api/v1/power/health")

    async def capabilities(self) -> dict:
        return await self._get("/api/v1/system/capabilities")

    async def map(self) -> dict:
        """점유 격자. 관제 화면이 N대를 한 좌표계 위에 그리려면 이것 하나가 필요하다."""
        return await self._get("/api/v1/map")

    async def swarm_state(self) -> dict:
        return await self._get("/api/v1/swarm/state")

    async def follow(self, params: SwarmFollowParams) -> dict:
        return await self._post("/api/v1/swarm/follow", params.model_dump(mode="json"))

    async def swarm_cancel(self) -> dict:
        return await self._post("/api/v1/swarm/cancel")

    async def navigation_cancel(self) -> dict:
        return await self._post("/api/v1/navigation/cancel")

    async def navigation_path(self) -> dict:
        """현재 계획 경로(map 프레임 폴리라인). Fleet 이 교행을 미리 보는 유일한 재료다."""
        return await self._get("/api/v1/navigation/path")

    async def navigation_goal(self, x: float, y: float, yaw: float, *,
                              correlation_id: str | None = None) -> dict:
        body = {"x": x, "y": y, "yaw": yaw}
        if correlation_id is not None:
            body["correlation_id"] = correlation_id
        return await self._post("/api/v1/navigation/goal", body)

    async def line_follow_mode(self, mode: str) -> dict:
        if mode not in {"IR_LINE", "OFF"}:
            raise ValueError("Fleet may select only IR_LINE or OFF")
        return self._check(await self._http.put(
            "/api/v1/line-follow/mode", json={"mode": mode}, headers=self._headers()
        ))

    async def line_follow(self) -> dict:
        """D-143 ``GET /api/v1/line-follow``: selected mode and status."""
        return await self._get("/api/v1/line-follow")

    async def line_follow_junction(self, action: str, place_id: str, *, stop_after_m: float | None,
                                   expires_s: float, turn_deg: float | None = None,
                                   advance_m: float | None = None, expect: dict | None = None) -> dict:
        """D-494 4 / D-495 1: the action at the next junction; an old CORE answers 404.

        ``expect`` holds the D-507 2 fields (map_id, expect_in_m, ...) for a ``junction_pivot`` CORE.
        """
        body: dict = {"action": action, "place_id": place_id, "expires_s": expires_s, **(expect or {})}
        for key, value in (("stop_after_m", stop_after_m), ("turn_deg", turn_deg), ("advance_m", advance_m)):
            if value is not None:
                body[key] = value
        return await self._post("/api/v1/line-follow/junction", body)

    async def line_stuck_decision(self, stuck_id: str, decision: str, *,
                                  yield_m: float | None = None,
                                  yield_turn_rad: float | None = None) -> dict:
        """D-407 §2: one stuck answer. YIELD carries one checked segment (D-453)."""
        body: dict = {"stuck_id": stuck_id, "decision": decision}
        if yield_m is not None:
            body["yield_m"] = yield_m
        if yield_turn_rad is not None:
            body["yield_turn_rad"] = yield_turn_rad
        return await self._post("/api/v1/line-follow/stuck/decision", body)

    async def estop(self) -> dict:
        return await self._post("/api/v1/safety/stop")

    async def identify_lamp(self, color: str) -> dict:
        if color not in {"blue", "amber"}:
            raise ValueError("unsupported identification color")
        return await self._post("/api/v1/host/lamp/identify", {"color": color})

    # --- D-395 localization (contract §2) -------------------------------------------

    async def localization_candidates(self) -> Optional[CandidateReport]:
        """The robot's latest candidate report, or None when it is not in CANDIDATES.

        Any 404 is "no candidates": CORE answers NO_CANDIDATES, and a CORE without
        the route has none to give either."""
        resp = await self._http.get("/api/v1/localization/candidates", headers=self._headers())
        if resp.status_code == 404:
            return None
        body = self._check(resp)
        try:
            return CandidateReport.model_validate(body)
        except ValidationError as exc:
            raise RobotApiError(self.robot_id, resp.status_code, "BAD_RESPONSE",
                                f"not a candidate report: {exc.error_count()} errors") from exc

    async def localization_decision(self, decision: LocalizationDecision) -> dict:
        return await self._post("/api/v1/localization/decision", decision.model_dump(mode="json"))

    async def localization_suspect(self, reason: str) -> dict:
        if not reason or len(reason) > 64:
            raise ValueError("suspect reason must be 1-64 characters")
        return await self._post("/api/v1/localization/suspect", {"reason": reason})

    async def localization_mission(self, kind: str, *, max_distance_m: float, max_time_s: float,
                                   target: Optional[dict] = None) -> dict:
        """Ask CORE to run a check manoeuvre or homing mission (P2-7); CORE drives, Fleet
        never does (D-2, D-369). A 409 refusal arrives as `RobotApiError` with the code."""
        return await self._post("/api/v1/localization/mission", {
            "kind": kind, "max_distance_m": max_distance_m, "max_time_s": max_time_s,
            "target": target})

    async def localization_mission_status(self) -> dict:
        """CORE's current or last mission: `{kind, state: idle|running|done|aborted, reason}`."""
        return await self._get("/api/v1/localization/mission")

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    # --- WS -------------------------------------------------------------------

    def pose_url(self) -> str:
        return ws_url(self._ep.base_url, "/ws/swarm/pose")

    def reference_url(self) -> str:
        return ws_url(self._ep.base_url, "/ws/swarm/reference")

    def events_url(self, types: Sequence[str]) -> str:
        return ws_url(self._ep.base_url, "/ws/events", types=",".join(types))

    async def _open_socket(self, url: str):
        """Connect and authenticate with the first frame, not ``?token=`` (D-370 S7).

        CORE's ``_authorize`` waits for ``{"type": "auth", "token": ...}`` when the
        URL has no token; a wrong token closes the socket with 4401 afterwards.
        """
        import websockets
        from websockets.exceptions import ConnectionClosed

        from fleet.swarm.discovery_transport import resolve_robot
        context = self._socket_context()
        options = {'ssl': context} if context else {}
        if self._ep.discovery:
            address, port = await resolve_robot(self._ep)
            from urllib.parse import urlsplit
            options.update(host=address, port=port, server_hostname=urlsplit(url).hostname)
            await self._socket_admission(address, port)
        ws = await websockets.connect(url, proxy=None, logger=_ws_log, **options)
        try:
            self._socket_auth_admission()
            await ws.send(json.dumps({"type": "auth", "token": self._ep.token}))
        except ConnectionClosed:
            # Already closed by the robot: reading the socket surfaces the close
            # code (4401/4403 -> RobotApiError) and any frames sent before it.
            pass
        except BaseException:
            await ws.close()
            raise
        return ws

    async def _socket_admission(self, address: str, port: int) -> None:
        """Enrolled clients may require identity admission before the auth frame."""

    def _socket_auth_admission(self) -> None:
        """Enrolled clients recheck their gate after the connection await."""

    def _socket_context(self):
        from fleet.swarm.discovery_transport import tls_context
        return tls_context(self._ep)

    async def pose_stream(self) -> AsyncIterator[str]:
        """리더 pose 프레임(텍스트). 소켓이 닫히면 끝난다 — 재연결은 호출자 몫.
        4401/4403 으로 거절되면 `RobotApiError` 를 올린다."""
        from websockets.exceptions import WebSocketException

        try:
            async with await self._open_socket(self.pose_url()) as ws:
                async for frame in ws:
                    text = _as_text(frame)
                    if text is not None:
                        yield text
        except (OSError, WebSocketException) as exc:
            rejected = _rejection(self.robot_id, exc)
            if rejected is not None:
                raise rejected from exc
            return

    async def open_reference_sink(self) -> ReferenceSink:
        # 거부는 `RobotApiError` 로, 나머지는 날것 그대로 올린다 — 여기서 `InvalidStatus`
        # 를 직접 import 하지 않는 이유는 `_rejection` 의 것과 같다(오래된 websockets).
        from websockets.exceptions import WebSocketException

        try:
            ws = await self._open_socket(self.reference_url())
        except (OSError, WebSocketException) as exc:
            rejected = _rejection(self.robot_id, exc)
            if rejected is not None:
                raise rejected from exc
            raise
        return _WebsocketSink(ws, self.robot_id)

    async def events(self, types: Sequence[str]) -> AsyncIterator[dict]:
        from websockets.exceptions import WebSocketException

        try:
            async with await self._open_socket(self.events_url(types)) as ws:
                async for frame in ws:
                    event = _as_event(frame)
                    if event is not None:
                        yield event
        except (OSError, WebSocketException) as exc:
            rejected = _rejection(self.robot_id, exc)
            if rejected is not None:
                raise rejected from exc
            return
