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

from core_common.protocol.schemas import SwarmFollowParams
from fleet.swarm.robots import RobotEndpoint, ws_url

log = logging.getLogger(__name__)

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


@runtime_checkable
class RobotClient(Protocol):
    robot_id: str

    async def state(self) -> dict: ...
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
    async def estop(self) -> dict: ...
    def pose_stream(self) -> AsyncIterator[str]: ...
    async def open_reference_sink(self) -> ReferenceSink: ...
    def events(self, types: Sequence[str]) -> AsyncIterator[dict]: ...


class _WebsocketSink:
    def __init__(self, ws) -> None:
        self._ws = ws

    async def send(self, frame: str) -> None:
        await self._ws.send(frame)

    async def close(self) -> None:
        await self._ws.close()


class HttpRobotClient:
    def __init__(self, endpoint: RobotEndpoint, *, http: Optional[httpx.AsyncClient] = None,
                 timeout_s: float = 5.0) -> None:
        self.robot_id = endpoint.robot_id
        self._ep = endpoint
        self._owns_http = http is None
        self._http = http or httpx.AsyncClient(base_url=endpoint.base_url, timeout=timeout_s)

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

    async def estop(self) -> dict:
        return await self._post("/api/v1/safety/stop")

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    # --- WS -------------------------------------------------------------------

    def pose_url(self) -> str:
        return ws_url(self._ep.base_url, "/ws/swarm/pose", self._ep.token)

    def reference_url(self) -> str:
        return ws_url(self._ep.base_url, "/ws/swarm/reference", self._ep.token)

    def events_url(self, types: Sequence[str]) -> str:
        return ws_url(self._ep.base_url, "/ws/events", self._ep.token, types=",".join(types))

    async def pose_stream(self) -> AsyncIterator[str]:
        """리더 pose 프레임(텍스트). 소켓이 닫히면 끝난다 — 재연결은 호출자 몫.
        4401/4403 으로 거절되면 `RobotApiError` 를 올린다."""
        import websockets
        from websockets.exceptions import WebSocketException

        try:
            async with websockets.connect(self.pose_url()) as ws:
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
        import websockets
        from websockets.exceptions import WebSocketException

        try:
            ws = await websockets.connect(self.reference_url())
        except (OSError, WebSocketException) as exc:
            rejected = _rejection(self.robot_id, exc)
            if rejected is not None:
                raise rejected from exc
            raise
        return _WebsocketSink(ws)

    async def events(self, types: Sequence[str]) -> AsyncIterator[dict]:
        import websockets
        from websockets.exceptions import WebSocketException

        try:
            async with websockets.connect(self.events_url(types)) as ws:
                async for frame in ws:
                    event = _as_event(frame)
                    if event is not None:
                        yield event
        except (OSError, WebSocketException) as exc:
            rejected = _rejection(self.robot_id, exc)
            if rejected is not None:
                raise rejected from exc
            return
