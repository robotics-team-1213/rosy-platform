import asyncio
import json
import logging
from typing import Optional

from fastapi import APIRouter, FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
from core_common.protocol.schemas import Envelope, EnvelopeType
from fleet.hub.hub import SiteHub

logger = logging.getLogger("hub.server")

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
        robot_id: Optional[str] = None
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
                
                reply = hub.handle(env)
                if reply.type is EnvelopeType.ERROR:
                    code = reply.payload.get("code")
                    logger.warning("hub rejected %s: %s", env.type.value, code)
                    await websocket.send_json(reply.model_dump(exclude_none=True))
                    if env.type is EnvelopeType.HELLO:
                        await websocket.close(code=4401)
                        break
                    continue
                
                if reply.type is EnvelopeType.WELCOME:
                    robot_id = reply.payload.get("robot_id")
                    
                await websocket.send_json(reply.model_dump(exclude_none=True))
        except WebSocketDisconnect:
            pass
        except Exception as exc:
            logger.error("ws error: %s", exc)
        finally:
            if robot_id:
                row = hub.registry.record(robot_id)
                row.online = False

    app.include_router(router)
    return app


def create_hub_app(hub: SiteHub, hub_token: Optional[str] = None) -> FastAPI:
    """독립 로컬 테스트/레거시 Hub 앱. 운영 console은 install_hub_routes를 쓴다."""
    return install_hub_routes(FastAPI(title="Rosy Site Hub"), hub, hub_token)
