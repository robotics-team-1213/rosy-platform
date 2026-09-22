import asyncio
import json
import logging
from typing import Optional

from fastapi import FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
from core_common.protocol.schemas import Envelope, EnvelopeType
from fleet.hub.hub import SiteHub

logger = logging.getLogger("hub.server")

def create_hub_app(hub: SiteHub, hub_token: Optional[str] = None) -> FastAPI:
    """/registry 는 등록 로봇 전원의 상태·이벤트를 내놓는다 — hub_token 을
    설정하면 Bearer 로 잠긴다(기본 개방은 로컬 시드용 하위호환)."""
    app = FastAPI(title="Rosy Site Hub")
    app.state.hub = hub

    @app.get("/registry")
    async def get_registry(authorization: str = Header(default="")):
        if hub_token is not None and authorization != f"Bearer {hub_token}":
            raise HTTPException(status_code=401, detail="hub token required")
        return hub.registry.snapshot()

    @app.websocket("/ws/robots")
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

    return app
