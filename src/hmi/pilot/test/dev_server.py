"""Pilot 개발 서버(D-323, ADB 실기 루프용) — 태블릿에서 /pilot 을 띄우기 위한
가짜 CORE. core_api_web 을 대신하지 않는다: pilot 이 소비하는 경로만 canned
응답으로 내고, 정적 자산은 소스 트리에서 직접 서빙한다.

실행(웍트리 루트에서):
    python src/hmi/pilot/test/dev_server.py
그다음 태블릿:
    adb reverse tcp:8642 tcp:8642
    adb shell am start -a android.intent.action.VIEW -d "http://localhost:8642/pilot/"

토큰: Bearer "devtoken" 을 operator 로 받는다. 그 외 401.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse

PILOT = Path(__file__).resolve().parents[1]          # .../src/hmi/pilot
WEB_COMMON = PILOT.parent / "web"                    # .../src/hmi/web

DEV_TOKEN = "devtoken"

PILOT_MIME = {
    "styles.css": "text/css",
    "app.js": "application/javascript",
    "client.js": "application/javascript",
    "stick.js": "application/javascript",
    "link.js": "application/javascript",
    "drivers/registry.js": "application/javascript",
    "drivers/pinky_core.js": "application/javascript",
    "screens/connect.js": "application/javascript",
}
COMMON_MIME = {
    "tokens.css": "text/css",
    "components.css": "text/css",
    "template.html": "text/html",
    "core_ui_logic.js": "application/javascript",
    "hold-ticker.js": "application/javascript",
    "ui.js": "application/javascript",
}

app = FastAPI(title="Rosy Pilot dev server", version="dev")

CAPABILITIES = {
    "teleop": True,
    "withheld": {"reasons": {}},
    "runtime": {"hardware": True, "evidence": True, "drive": True,
                "navigation": False, "maps": False},
}
STATE = {"mode": "IDLE", "velocity": {"linear": 0.0, "angular": 0.0}, "battery": {"volts": 7.6}}


def _role(request: Request) -> str | None:
    auth = request.headers.get("authorization", "")
    if auth == f"Bearer {DEV_TOKEN}":
        return "operator"
    return None


@app.get("/pilot", include_in_schema=False)
def pilot_index():
    return FileResponse(PILOT / "index.html", media_type="text/html",
                        headers={"Cache-Control": "no-cache"})


@app.get("/pilot/assets/{asset_name:path}", include_in_schema=False)
def pilot_asset(asset_name: str):
    media = PILOT_MIME.get(asset_name)
    if media is None:
        return JSONResponse({"detail": "pilot asset not found"}, status_code=404)
    return FileResponse(PILOT / asset_name, media_type=media,
                        headers={"Cache-Control": "no-cache"})


@app.get("/common/{asset_name:path}", include_in_schema=False)
def common_asset(asset_name: str):
    media = COMMON_MIME.get(asset_name)
    if media is None:
        return JSONResponse({"detail": "common asset not found"}, status_code=404)
    return FileResponse(WEB_COMMON / asset_name, media_type=media,
                        headers={"Cache-Control": "no-cache"})


@app.get("/api/v1/auth/whoami")
def whoami(request: Request):
    role = _role(request)
    if role is None:
        return JSONResponse({"detail": "unauthorized"}, status_code=401)
    return {"id": "dev-1", "role": role, "label": "개발 운전자",
            "source": "dev", "created_at": "", "expires_at": None}


@app.get("/api/v1/system/capabilities")
def capabilities(request: Request):
    if _role(request) is None:
        return JSONResponse({"detail": "unauthorized"}, status_code=401)
    return CAPABILITIES


@app.post("/api/v1/mode")
async def set_mode(request: Request):
    if _role(request) is None:
        return JSONResponse({"detail": "unauthorized"}, status_code=401)
    body = await request.json()
    STATE["mode"] = body.get("mode", "IDLE")
    return {"mode": STATE["mode"]}


@app.post("/api/v1/teleop")
async def teleop(request: Request):
    if _role(request) is None:
        return JSONResponse({"detail": "unauthorized"}, status_code=401)
    body = await request.json()
    STATE["velocity"] = {"linear": float(body.get("linear", 0.0)),
                         "angular": float(body.get("angular", 0.0))}
    return STATE["velocity"]


@app.post("/api/v1/safety/stop")
def stop(request: Request):
    if _role(request) is None:
        return JSONResponse({"detail": "unauthorized"}, status_code=401)
    STATE["velocity"] = {"linear": 0.0, "angular": 0.0}
    return {"stopped": True}


@app.websocket("/ws/state")
async def ws_state(websocket: WebSocket):
    await websocket.accept()
    try:
        first = await asyncio.wait_for(websocket.receive_text(), timeout=2.0)
        frame = json.loads(first)
        if frame.get("type") != "auth" or frame.get("token") != DEV_TOKEN:
            await websocket.close(code=4401)
            return
    except (asyncio.TimeoutError, WebSocketDisconnect, ValueError):
        return
    try:
        while True:
            STATE["mode"] = "MANUAL"
            await websocket.send_json({"type": "state", **STATE})
            await asyncio.sleep(0.1)
    except WebSocketDisconnect:
        return


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8642, log_level="warning")
