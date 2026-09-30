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
from fastapi import FastAPI, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse

from PIL import Image, ImageDraw

PILOT = Path(__file__).resolve().parents[1]          # .../src/hmi/pilot
WEB_COMMON = PILOT.parent / "web_common"             # .../src/hmi/web_common

DEV_TOKEN = "devtoken"

PILOT_MIME = {
    "styles.css": "text/css",
    "app.js": "application/javascript",
    "client.js": "application/javascript",
    "stick.js": "application/javascript",
    "link.js": "application/javascript",
    "drivers/registry.js": "application/javascript",
    "drivers/pinky_core.js": "application/javascript",
    "recent.js": "application/javascript",
    "autonomy.js": "application/javascript",
    "screens/connect.js": "application/javascript",
    "screens/drive.js": "application/javascript",
    "screens/inputs.js": "application/javascript",
    "input-state.js": "application/javascript",
    "vision.js": "application/javascript",
    "manifest.webmanifest": "application/manifest+json",
    "sw.js": "text/javascript",
    "icons/icon-192.png": "image/png",
    "icons/icon-192-maskable.png": "image/png",
    "icons/icon-512.png": "image/png",
}
COMMON_MIME = {
    "tokens.css": "text/css",
    "components.css": "text/css",
    "template.html": "text/html",
    "core_ui_logic.js": "application/javascript",
    "hold-ticker.js": "application/javascript",
    "ui.js": "application/javascript",
    "evidence.js": "application/javascript",
}

app = FastAPI(title="Rosy Pilot dev server", version="dev")

CAPABILITIES = {
    "teleop": True,
    "withheld": {"reasons": {}},
    "runtime": {"hardware": True, "evidence": True, "drive": True,
                "navigation": False, "maps": False},
}
STATE = {"mode": "IDLE", "velocity": {"linear": 0.0, "angular": 0.0}, "battery": {"percent": 84, "volts": 7.6}}

#: 시뮬/개발용 canned 프레임 — 토큰 색 원 하나(실 카메라가 없는 자리 표시).
_buf = __import__("io").BytesIO()
_img = Image.new("RGB", (160, 120), (16, 18, 20))
ImageDraw.Draw(_img).ellipse([40, 30, 120, 90], outline=(246, 151, 231), width=3)
_img.save(_buf, "JPEG", quality=70)
FRAME_JPEG = _buf.getvalue()
FRAME_SEQ = 4


@app.get("/api/v1/robot/state")
def robot_state(request: Request):
    if _role(request) is None:
        return JSONResponse({"detail": "unauthorized"}, status_code=401)
    return {"mode": STATE["mode"], "velocity": STATE["velocity"], "battery": STATE["battery"]}


@app.get("/api/v1/vision/front/status")
def vision_status(request: Request):
    if _role(request) is None:
        return JSONResponse({"detail": "unauthorized"}, status_code=401)
    return {"available": True, "stale": False, "width": 160, "height": 120,
            "seq": FRAME_SEQ, "age_ms": 12}


@app.get("/api/v1/vision/front/frame")
def vision_frame(request: Request):
    if _role(request) is None:
        return JSONResponse({"detail": "unauthorized"}, status_code=401)
    return Response(FRAME_JPEG, media_type="image/jpeg")


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
    headers = {"Cache-Control": "no-cache"}
    if asset_name == "sw.js":
        # scope /pilot 은 스크립트 디렉터리(/pilot/assets)보다 넓다 — 허용 헤더 필수.
        headers["Service-Worker-Allowed"] = "/pilot"
    return FileResponse(PILOT / asset_name, media_type=media, headers=headers)


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


# CORE 와 같은 수동 한도(rosy_default.yaml safety.manual_*·navigation.max_*).
LIMITS = {"session_linear": None, "max_linear": 0.2, "max_angular": 0.8,
          "manual_linear": 0.15, "manual_angular": 0.6}
TELEOP_LOG: list[dict] = []


PAIR_CODE = "TEST-CODE"


@app.post("/api/v1/auth/pair", status_code=201)
async def pair(request: Request):
    body = await request.json()
    if str(body.get("code", "")).upper() != PAIR_CODE:
        return JSONResponse({"error": {"code": "UNAUTHORIZED", "message": "invalid or expired login code"}},
                            status_code=401)
    return JSONResponse({"id": "pair-1", "token": "devtoken", "role": "operator", "label": body.get("label", ""),
                         "source": "pair-physical", "expires_at": None}, status_code=201)


@app.get("/api/v1/safety/state")
def safety_state(request: Request):
    if _role(request) is None:
        return JSONResponse({"detail": "unauthorized"}, status_code=401)
    return {"estop": False, "source": "", "fleet_loss_policy": "STOP", "limits": LIMITS}


@app.get("/__test__/teleop")
def teleop_log():
    return TELEOP_LOG


@app.post("/api/v1/teleop")
async def teleop(request: Request):
    if _role(request) is None:
        return JSONResponse({"detail": "unauthorized"}, status_code=401)
    body = await request.json()
    TELEOP_LOG.append({"linear": float(body.get("linear", 0.0)),
                       "angular": float(body.get("angular", 0.0)), "mode": STATE.get("mode")})
    if STATE.get("mode") != "MANUAL":
        # CORE 와 같다: 수동 모드가 아니면 409 MODE_CONFLICT.
        return JSONResponse({"detail": {"code": "MODE_CONFLICT", "message": "not MANUAL"}},
                            status_code=409)
    STATE["velocity"] = {"linear": float(body.get("linear", 0.0)),
                         "angular": float(body.get("angular", 0.0))}
    return STATE["velocity"]


@app.post("/api/v1/safety/stop")
def stop(request: Request):
    if _role(request) is None:
        return JSONResponse({"detail": "unauthorized"}, status_code=401)
    STATE["velocity"] = {"linear": 0.0, "angular": 0.0}
    return {"stopped": True}


@app.post("/api/v1/front/evidence")
async def front_evidence(request: Request):
    if _role(request) is None:
        return JSONResponse({"detail": "unauthorized"}, status_code=401)
    await request.body()
    return JSONResponse({"file_name": "rosy-camera-dev.jpg", "evidence_id": "dev-1"},
                        status_code=201)


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


# --- 차선 추종(D-344/D-364) 흉내: 시험이 /__test__/line-follow 로 다음 상태를 정한다 ---
LINE_FOLLOW = {"mode": "OFF", "state": "OFF", "source": None, "error": None, "confidence": 0.0,
               "linear": 0.0, "angular": 0.0, "reason": "mode_off", "clearance_m": None}
LINE_FOLLOW_SCRIPT = {}


@app.post("/__test__/line-follow")
async def line_follow_script(request: Request):
    LINE_FOLLOW_SCRIPT.clear()
    LINE_FOLLOW_SCRIPT.update(await request.json())
    return LINE_FOLLOW_SCRIPT


@app.get("/api/v1/line-follow")
def line_follow_status(request: Request):
    if _role(request) is None:
        return JSONResponse({"detail": "unauthorized"}, status_code=401)
    if LINE_FOLLOW["mode"] != "OFF":
        LINE_FOLLOW.update(LINE_FOLLOW_SCRIPT)
    return LINE_FOLLOW


@app.put("/api/v1/line-follow/mode")
async def line_follow_mode(request: Request):
    if _role(request) is None:
        return JSONResponse({"detail": "unauthorized"}, status_code=401)
    mode = (await request.json()).get("mode", "OFF")
    LINE_FOLLOW.update({"mode": mode, "state": "WAITING" if mode != "OFF" else "OFF",
                        "reason": "no_observation" if mode != "OFF" else "mode_off",
                        "error": None, "linear": 0.0, "angular": 0.0})
    STATE["mode"] = "NAVIGATION" if mode != "OFF" else STATE["mode"]
    return LINE_FOLLOW


@app.post("/api/v1/line-follow/hold")
def line_follow_hold(request: Request):
    if _role(request) is None:
        return JSONResponse({"detail": "unauthorized"}, status_code=401)
    if LINE_FOLLOW["mode"] == "OFF":
        return JSONResponse({"detail": {"code": "LINE_FOLLOW_NOT_HELD"}}, status_code=409)
    return LINE_FOLLOW
