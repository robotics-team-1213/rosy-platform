import asyncio
import json
import logging
from typing import Optional

from fastapi import APIRouter, FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState
from core_common.protocol.schemas import Envelope, EnvelopeType
from fleet.hub.hub import SiteHub

logger = logging.getLogger("hub.server")


def fan_out_events(project, wake: Optional[asyncio.Event]):
    """Keep task projection results and wake the resolver on lane-stuck events."""
    def callback(event):
        result = project(event) if project is not None else None
        if wake is not None and str(event.get("type", "")).startswith("nav.line_stuck_"):
            wake.set()
        return result
    return callback

async def send_reply(websocket, reply: Envelope) -> bool:
    """Reply unless the agent has gone: never send into a closed socket (D-407 re-run:
    "websocket.send after websocket.close" when the agent dropped the link)."""
    if websocket.client_state is not WebSocketState.CONNECTED:
        return False
    try:
        await websocket.send_json(reply.model_dump(exclude_none=True))
        return True
    except (WebSocketDisconnect, RuntimeError, OSError) as exc:
        logger.info("robot link closed before the hub reply was sent: %s", exc)
        return False


def install_hub_routes(app: FastAPI, hub: SiteHub,
                       hub_token: Optional[str] = None) -> FastAPI:
    """기존 사이트 FastAPI 앱에 Hub의 registry와 CORE Agent 경로를 붙인다.

    `/registry`는 console Bearer token을 공유한다. `/ws/robots`는 연결 후
    robot별 `fleet_pairing_token` HELLO를 검증하며 REST 제어 토큰으로 fallback하지 않는다.
    """
    router = APIRouter()
    app.state.hub = hub

    @router.get("/registry")
    async def get_registry(authorization: str = Header(default="")):
        if hub_token is not None and authorization != f"Bearer {hub_token}":
            raise HTTPException(status_code=401, detail="hub token required")
        return hub.registry.snapshot()

    @router.websocket("/ws/robots")
    async def ws_robots(websocket: WebSocket):
        await websocket.accept()
        session = hub.open_session()

        async def send(reply: Envelope) -> bool:
            return await send_reply(websocket, reply)

        try:
            while True:
                text = await websocket.receive_text()
                try:
                    payload = json.loads(text)
                    env = Envelope.model_validate(payload)
                except Exception as exc:
                    logger.warning("invalid envelope %s", exc)
                    await websocket.close(code=1008)
                    break
                
                reply = hub.handle(env, session=session)
                if reply.type is EnvelopeType.ERROR:
                    code = reply.payload.get("code")
                    logger.warning("hub rejected %s: %s", env.type.value, code)
                    if not await send(reply):
                        break
                    # A refused HELLO, or a socket another connection took over,
                    # must not linger: close so the agent's backoff reconnects.
                    if env.type is EnvelopeType.HELLO or code == "PAIRING_INVALID":
                        await websocket.close(code=4401)
                        break
                    continue

                if not await send(reply):
                    break
        except WebSocketDisconnect:
            pass
        except Exception as exc:
            logger.error("ws error: %s", exc)
        finally:
            hub.close_session(session)

    app.include_router(router)
    return app


def create_hub_app(hub: SiteHub, hub_token: Optional[str] = None) -> FastAPI:
    """독립 로컬 테스트/레거시 Hub 앱. 운영 console은 install_hub_routes를 쓴다."""
    return install_hub_routes(FastAPI(title="Rosy Site Hub"), hub, hub_token)
