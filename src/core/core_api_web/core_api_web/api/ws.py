"""core_api_web.api.ws — API-102 WebSocket 스트림.

/ws/state (10 Hz), /ws/events, 그리고 군집용 두 소켓:
- `/ws/swarm/pose` — 이 로봇의 pose 를 ≥10 Hz 로 내보낸다 (SWM-003, 리더 역할).
- `/ws/swarm/reference` — 따라갈 리더의 pose 를 받아 SwarmManager 에 넣는다.

두 소켓은 같은 §7.8 envelope 을 쓴다. 그래서 팔로워의 reference 소켓에
Fleet 릴레이를 물리든 리더의 pose 소켓을 그대로 물리든 추종 로직은 같다
(SWM-007) — 이 파일이 소스를 아는 유일한 곳이고, SwarmManager 는 모른다.

인증(D-193 10): 연결 뒤 첫 메시지 `{"type": "auth", "token": "..."}` 로 토큰을
보낸다. 토큰이 URL(프록시·브라우저 기록)에 남지 않는다. `?token=` 은 한
릴리스 동안만 계속 받는다.
"""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from core_api_web.api.deps import ROLE_RANK, authenticate
from core_features.swarm import ReferencePose
from core_common.protocol.schemas import Envelope, EnvelopeType, Pose, PoseSample

ws_router = APIRouter()

#: 쿼리 토큰 없이 연결했을 때 첫 인증 메시지를 기다리는 시간.
FIRST_MESSAGE_TIMEOUT_S = 5.0


def _match_type(type_: str, patterns: list[str]) -> bool:
    if not patterns:
        return True
    for pattern in patterns:
        if pattern.endswith("*") and type_.startswith(pattern[:-1]):
            return True
        if type_ == pattern:
            return True
    return False


@ws_router.websocket("/ws/state")
async def ws_state(websocket: WebSocket):
    svc = await _authorize(websocket)
    if svc is None:
        return
    rate = float(svc.config.get("state", {}).get("rate_hz", 10.0))
    try:
        while True:
            await websocket.send_json(svc.state.snapshot().model_dump())
            await asyncio.sleep(1.0 / rate)
    except WebSocketDisconnect:
        return
    except Exception:
        return


@ws_router.websocket("/ws/events")
async def ws_events(websocket: WebSocket):
    svc = await _authorize(websocket)
    if svc is None:
        return
    patterns = [p.strip() for p in websocket.query_params.get("types", "").split(",") if p.strip()]

    queue: asyncio.Queue = asyncio.Queue()

    def _on_event(event) -> None:
        try:
            queue.put_nowait(event)
        except Exception:
            pass

    unsubscribe = svc.events.subscribe(_on_event)
    try:
        while True:
            event = await queue.get()
            if _match_type(event.type, patterns):
                await websocket.send_json(event.model_dump())
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        unsubscribe()


async def _first_message_token(websocket: WebSocket) -> str:
    """수락한 뒤 첫 메시지 `{"type": "auth", "token": ...}` 의 토큰. 아니면 빈 문자열."""
    try:
        raw = await asyncio.wait_for(websocket.receive_text(), timeout=FIRST_MESSAGE_TIMEOUT_S)
        frame = json.loads(raw)
    except (asyncio.TimeoutError, TypeError, ValueError, KeyError, RuntimeError, WebSocketDisconnect):
        return ""
    if not isinstance(frame, dict) or frame.get("type") != "auth":
        return ""
    token = frame.get("token")
    return token if isinstance(token, str) else ""


async def _authorize(websocket: WebSocket, min_role: str = "viewer",
                     capability: str = ""):
    """인증하고 수락한 소켓의 서비스, 아니면 닫고 None.

    4401 은 토큰이 없거나 틀린 것, 4403 은 인증은 됐지만 허용되지 않는 것.
    `?token=` 이 있으면 수락 전에 판정한다(기존 동작). 없으면 수락하고 첫
    메시지를 기다린다.
    """
    svc = websocket.app.state.core
    query_token = websocket.query_params.get("token")
    if query_token is None:
        await websocket.accept()
        token = await _first_message_token(websocket)
    else:
        token = query_token
    try:
        auth = authenticate(svc.config, None, token)
    except Exception:
        await websocket.close(code=4401)
        return None
    if auth.rank < ROLE_RANK[min_role]:
        await websocket.close(code=4403)
        return None
    if capability and not svc.capability.supports(capability):
        # CAP-003. 선언하지 않은 기능을 소켓으로 우회해 제공하면 CAP-001 이
        # 다시 거짓말이 된다 — D-31 이 없애려던 바로 그 어긋남이다.
        await websocket.close(code=4403)
        return None
    if query_token is not None:
        await websocket.accept()
    return svc


def _pose_envelope(robot_id: str, pose, seq: int, map_id=None) -> dict:
    """API Ref §7.8 그대로. 리더와 팔로워가 같은 모양을 쓴다."""
    sample = PoseSample(robot_id=robot_id, map_id=map_id,
                        pose=Pose(x=pose.x, y=pose.y, yaw=pose.yaw), seq=seq)
    return Envelope(type=EnvelopeType.POSE, payload=sample.model_dump()).model_dump()


@ws_router.websocket("/ws/swarm/pose")
async def ws_swarm_pose(websocket: WebSocket):
    """SWM-003 Leader Pose Stream. heartbeat 와 별개의 전용 스트림이다."""
    svc = await _authorize(websocket, capability="swarm.lead")
    if svc is None:
        return
    rate = float(svc.config.get("swarm", {}).get("pose_rate_hz", 10.0))
    rate = max(rate, 10.0)  # SWM-003 은 하한이다. 설정으로 내릴 수 없다.
    period = 1.0 / rate
    seq = 0
    # 보낸 뒤 period 만큼 자면 주기가 항상 period + 전송시간이 되어 10 Hz 아래로
    # 내려간다. 마감시각을 따라간다.
    loop = asyncio.get_running_loop()
    next_at = loop.time()
    try:
        while True:
            snapshot = svc.state.snapshot()
            seq += 1
            await websocket.send_json(
                _pose_envelope(svc.identity.robot_id, snapshot.pose, seq,
                               map_id=snapshot.map_id))
            next_at += period
            delay = next_at - loop.time()
            if delay <= 0:
                next_at = loop.time()
            else:
                await asyncio.sleep(delay)
    except WebSocketDisconnect:
        return
    except Exception:
        return


def _reference_from(frame: dict):
    """§7.8 envelope → ReferencePose. 모양이 아니면 None."""
    if not isinstance(frame, dict):
        return None
    if frame.get("type") != EnvelopeType.POSE.value:
        return None
    payload = frame.get("payload")
    if not isinstance(payload, dict):
        return None
    pose = payload.get("pose")
    robot_id = payload.get("robot_id")
    map_id = payload.get("map_id")
    if not isinstance(pose, dict) or not isinstance(robot_id, str) or not robot_id:
        return None
    try:
        return ReferencePose(
            robot_id=robot_id,
            x=float(pose["x"]), y=float(pose["y"]), yaw=float(pose["yaw"]),
            seq=int(payload.get("seq", 0)),
            # robot_id 옆에 있는 검사와 같은 것. 숫자 map_id 하나면 비교가
            # 영원히 참이 되어, 스트림이 멀쩡한 대형이 영구 HOLD 에 앉는다.
            map_id=map_id if isinstance(map_id, str) and map_id else None,
        )
    except (KeyError, TypeError, ValueError):
        return None


@ws_router.websocket("/ws/swarm/reference")
async def ws_swarm_reference(websocket: WebSocket):
    """팔로워의 참조 스트림 입구 (SWM-007).

    한 프레임이 망가졌다고 소켓을 닫지 않는다 — 닫으면 리더 하나의 잘못된
    표본이 대형 전체를 HOLD 로 떨어뜨린다. 버리고 다음 프레임을 기다린다.
    """
    svc = await _authorize(websocket, min_role="operator")
    if svc is None:
        return
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                frame = json.loads(raw)
            except (TypeError, ValueError):
                continue
            reference = _reference_from(frame)
            if reference is None:
                continue
            try:
                svc.swarm.on_reference_pose(reference)
            except Exception:
                # 목표 투입 실패(예: Nav2 없음)로 스트림을 끊지 않는다.
                # 표본이 끊기면 SWM-004 가 HOLD 로 처리한다.
                continue
    except WebSocketDisconnect:
        return
    except Exception:
        return
