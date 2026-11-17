"""fleet.swarm.transport_helpers — wire framing, response validation, and socket helpers for HttpRobotClient."""

from __future__ import annotations

import json
from typing import Any, Awaitable, Callable, Optional
from urllib.parse import urlsplit

import httpx
from pydantic import ValidationError

from core_common.protocol.localization import CandidateReport
from core_common.protocol.schemas import LineStuckPrecondition
from fleet.swarm.api.ports import RobotApiError


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


class _WebsocketSink:
    def __init__(self, ws, robot_id: str) -> None:
        self._ws = ws
        self._robot_id = robot_id

    def _reason(self, exc: BaseException) -> BaseException:
        from fleet.swarm.transport import _rejection

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


def check_response(robot_id: str, resp: httpx.Response) -> dict:
    if resp.status_code < 400:
        if not resp.content:
            return {}
        try:
            data = resp.json()
        except ValueError as exc:
            raise RobotApiError(robot_id, resp.status_code, "BAD_RESPONSE",
                                f"expected a JSON object, got {resp.text[:120]!r}") from exc
        if not isinstance(data, dict):
            raise RobotApiError(robot_id, resp.status_code, "BAD_RESPONSE",
                                f"expected a JSON object, got {type(data).__name__}")
        return data
    code, message, detail = f"HTTP_{resp.status_code}", resp.text, None
    try:
        err = resp.json().get("error") or {}
        code = str(err.get("code") or code)
        message = str(err.get("message") or message)
        detail = err.get("detail") if isinstance(err.get("detail"), dict) else None
    except (ValueError, AttributeError):
        pass
    raise RobotApiError(robot_id, resp.status_code, code, message, detail)


async def build_stuck_decision_body(
    client: Any,
    stuck_id: str,
    decision: str,
    *,
    yield_m: float | None = None,
    yield_turn_rad: float | None = None,
    expected_stuck: dict | None = None,
    before_submit: Callable[[], Awaitable[bool]] | None = None,
    realign: dict | None = None,
) -> dict:
    """D-407 §2 / D-724: validate and assemble one line-stuck decision payload."""
    if before_submit is not None and (expected_stuck is None or not callable(before_submit)):
        raise ValueError("conditional request and explicit submission guard required")
    body: dict = {"stuck_id": stuck_id, "decision": decision}
    if expected_stuck is not None:
        if decision != "BACK_AND_RETRY":
            raise ValueError("expected_stuck belongs to BACK_AND_RETRY")
        body["expected_stuck"] = LineStuckPrecondition.model_validate(expected_stuck).model_dump()
        current = await client.line_follow()
        stuck = current.get("stuck")
        if not isinstance(stuck, dict) or stuck.get("conditional_back") is not True:
            raise RobotApiError(client.robot_id, 409, "STUCK_DECISION_REFUSED",
                                "conditional back is unsupported by CORE")
    if yield_m is not None:
        body["yield_m"] = yield_m
    if yield_turn_rad is not None:
        body["yield_turn_rad"] = yield_turn_rad
    if realign is not None:
        if decision != "REALIGN":
            raise ValueError("realign body requires REALIGN decision")
        body["realign"] = realign
    if before_submit is not None and await before_submit() is not True:
        raise RobotApiError(client.robot_id, 409, "STUCK_DECISION_REFUSED", "final submission guard refused")
    return body


async def fetch_front_frame(client: Any, *, overlay: bool = True) -> tuple[bytes, dict]:
    """D-577 8: one fresh front-camera JPEG (the status' sequence) and that status."""
    status = await client.front_status()
    if not status.get("available") or not status.get("sequence"):
        raise RobotApiError(client.robot_id, 404, "CAMERA_FRAME_UNAVAILABLE",
                            "front camera preview is missing or stale")
    params = {"sequence": status["sequence"]}
    if not overlay:
        if not status.get("raw_available") or not status.get("raw_sequence"):
            raise RobotApiError(client.robot_id, 404, "CAMERA_FRAME_UNAVAILABLE", "raw front frame unavailable")
        params = {"sequence": status["raw_sequence"], "overlay": "false"}
    resp = await client._http.get("/api/v1/vision/front/frame", params=params, headers=client._headers())
    if resp.status_code >= 400:
        client._check(resp)
    return resp.content, status if overlay else {**status, "overlay": "none", "sequence": status["raw_sequence"]}


async def fetch_localization_candidates(client: Any) -> Optional[CandidateReport]:
    """D-395: the robot's latest candidate report, or None on 404."""
    resp = await client._http.get("/api/v1/localization/candidates", headers=client._headers())
    if resp.status_code == 404:
        return None
    body = client._check(resp)
    try:
        return CandidateReport.model_validate(body)
    except ValidationError as exc:
        raise RobotApiError(client.robot_id, resp.status_code, "BAD_RESPONSE",
                            f"not a candidate report: {exc.error_count()} errors") from exc


async def open_robot_socket(client: Any, url: str, ws_log):
    """Connect and authenticate with the first frame, not ``?token=`` (D-370 S7)."""
    import websockets
    from websockets.exceptions import ConnectionClosed
    from fleet.swarm.discovery_transport import resolve_robot

    context = client._socket_context()
    options = {"ssl": context} if context else {}
    if client._ep.discovery:
        address, port = await resolve_robot(client._ep)
        options.update(host=address, port=port, server_hostname=urlsplit(url).hostname)
        await client._socket_admission(address, port)
    ws = await websockets.connect(url, proxy=None, logger=ws_log, **options)
    try:
        client._socket_auth_admission()
        await ws.send(json.dumps({"type": "auth", "token": client._ep.token}))
    except ConnectionClosed:
        pass
    except BaseException:
        await ws.close()
        raise
    return ws
