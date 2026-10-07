"""Pilot 개발 서버(D-323, ADB 실기 루프용) — 태블릿에서 /pilot 을 띄우기 위한
가짜 CORE. core_api_web 을 대신하지 않는다: pilot 이 소비하는 경로만 canned
응답으로 내고, 정적 자산은 소스 트리에서 직접 서빙한다.

실행(웍트리 루트에서):
    python middleware/ui/pilot/test/dev_server.py
그다음 태블릿:
    adb reverse tcp:8642 tcp:8642
    adb shell am start -a android.intent.action.VIEW -d "http://localhost:8642/pilot/"

토큰: Bearer "devtoken" 을 operator 로 받는다. Bearer "devadmintoken" 을
administrator 로 받는다(등록 코드 발급 시험용). 그 외 401.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

from PIL import Image, ImageDraw

PILOT = Path(__file__).resolve().parents[1]          # .../middleware/ui/pilot
WEB_COMMON = (PILOT.parents[2] / "shared") / "web"             # .../shared/web

DEV_TOKEN = "devtoken"
DEV_ADMIN_TOKEN = "devadmintoken"

PILOT_MIME = {
    "styles.css": "text/css",
    "app.js": "application/javascript",
    "client.js": "application/javascript",
    "stick.js": "application/javascript",
    "link.js": "application/javascript",
    "peer-approval.js": "application/javascript",
    "drivers/registry.js": "application/javascript",
    "drivers/pinky_core.js": "application/javascript",
    "drivers/omx_sim.js": "application/javascript",
    "autonomy.js": "application/javascript",
    "calibration.js": "application/javascript",
    "recording.js": "application/javascript",
    "controls.js": "application/javascript",
    "arm-stick.js": "application/javascript",
    "screens/connect.js": "application/javascript",
    "screens/drive.js": "application/javascript",
    "screens/drive-auto.js": "application/javascript",
    "screens/drive-view.js": "application/javascript",
    "screens/inputs.js": "application/javascript",
    "screens/robot-recording.js": "application/javascript",
    "screens/arm.js": "application/javascript",
    "screens/compose.js": "application/javascript",
    "widgets/joint_jog.js": "application/javascript",
    "widgets/gripper.js": "application/javascript",
    "input-state.js": "application/javascript",
    "vision.js": "application/javascript",
    "models.js": "application/javascript",
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
    "confirmation.js": "application/javascript",
    "live-dialog-geometry.js": "application/javascript",
    "evidence.js": "application/javascript",
}

app = FastAPI(title="Rosy Pilot dev server", version="dev")

CAPABILITIES = {
    "teleop": True,
    "withheld": {"reasons": {}},
    "runtime": {"hardware": True, "evidence": True, "drive": True,
                "navigation": False, "maps": False},
}
STATE = {"mode": "IDLE", "velocity": {"linear": 0.0, "angular": 0.0}, "battery": {"percent": 84, "volts": 7.6},
         "activity": None}


def state_frame():
    stamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return {"timestamp": stamp,
            "evidence": {channel: {"received_at": stamp, "evidence": "fresh"}
                         for channel in ("velocity", "battery")},
            **STATE}

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
    return state_frame()


@app.post("/__test__/activity")
async def set_activity(request: Request):
    """시험이 보정 세션 표시(D-321 부록)를 정한다. 본문이 null 이면 보정 끝."""
    STATE["activity"] = await request.json()
    return {"activity": STATE["activity"]}


@app.get("/api/v1/vision/front/status")
def vision_status(request: Request):
    if _role(request) is None:
        return JSONResponse({"detail": "unauthorized"}, status_code=401)
    return {"available": True, "stale": False, "width": 160, "height": 120,
            "seq": FRAME_SEQ, "sequence": FRAME_SEQ, "raw_available": True, "raw_sequence": FRAME_SEQ, "age_ms": 12}


@app.get("/api/v1/vision/front/frame")
def vision_frame(request: Request):
    if _role(request) is None:
        return JSONResponse({"detail": "unauthorized"}, status_code=401)
    variant = "raw" if request.query_params.get("overlay") == "false" else "annotated"
    return Response(FRAME_JPEG, media_type="image/jpeg", headers={
        "X-Rosy-Camera-Sequence": str(FRAME_SEQ), "X-Rosy-Camera-Captured-At": "5",
        "X-Rosy-Camera-Frame-Id": "front", "X-Rosy-Camera-Variant": variant})


def _role(request: Request) -> str | None:
    auth = request.headers.get("authorization", "")
    if auth == f"Bearer {DEV_TOKEN}":
        return "operator"
    if auth == f"Bearer {DEV_ADMIN_TOKEN}":
        return "administrator"
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


#: 시험 훅: whoami 를 앞으로 N 번 503 으로 실패시킨다(보정 확인 중 표시·재시도).
WHOAMI_FAILURES = {"remaining": 0}
#: 시험이 읽는다: POST /mode 로 들어온 mode 값의 순서.
MODE_LOG: list[str] = []


@app.post("/__test__/whoami-fail")
async def whoami_fail(request: Request):
    WHOAMI_FAILURES["remaining"] = int((await request.json()).get("count", 0))
    return WHOAMI_FAILURES


#: 시험 훅: 다음 POST /mode MANUAL N 번을 409 로 거절한다(engage 실패).
MODE_REFUSALS = {"remaining": 0}


@app.post("/__test__/mode-refuse")
async def mode_refuse(request: Request):
    MODE_REFUSALS["remaining"] = int((await request.json()).get("count", 0))
    return MODE_REFUSALS


@app.get("/__test__/mode-log")
def mode_log():
    return MODE_LOG


@app.get("/api/v1/auth/whoami")
def whoami(request: Request):
    role = _role(request)
    if role is None:
        return JSONResponse({"detail": "unauthorized"}, status_code=401)
    if WHOAMI_FAILURES["remaining"] > 0:
        WHOAMI_FAILURES["remaining"] -= 1
        return JSONResponse({"detail": "busy"}, status_code=503)
    return {"id": "dev-1", "role": role, "label": "개발 운전자",
            "source": "dev", "created_at": "", "expires_at": None}


#: D-411 B rosy.controls/1 — CORE 와 같은 기본(base_velocity 하나, 최대값 = manual 한도).
#: 시험 훅 POST /__test__/controls: {"extra": item} 항목 덧붙임, {"omit": true} 키 생략(구 CORE),
#: {"items": []} 빈 목록, {} 기본 복원.
_BASE_CONTROL = {"id": "base", "kind": "base_velocity", "label": "주행", "max_linear": 0.15,
                 "max_angular": 0.6, "pivot": True, "fine": True, "autonomy": ["line"]}
CONTROLS: dict = {"items": [_BASE_CONTROL], "omit": False}


@app.post("/__test__/controls")
async def controls_script(request: Request):
    body = await request.json()
    if not body:
        CONTROLS.update(items=[_BASE_CONTROL], omit=False)
    if "items" in body:
        CONTROLS["items"] = list(body["items"])
    if "extra" in body:
        CONTROLS["items"] = [*CONTROLS["items"], body["extra"]]
    if "omit" in body:
        CONTROLS["omit"] = bool(body["omit"])
    return CONTROLS


@app.get("/api/v1/system/capabilities")
def capabilities(request: Request):
    if _role(request) is None:
        return JSONResponse({"detail": "unauthorized"}, status_code=401)
    if CONTROLS["omit"]:
        return CAPABILITIES
    return {**CAPABILITIES, "controls": {"schema": "rosy.controls/1", "items": CONTROLS["items"]}}


@app.post("/api/v1/mode")
async def set_mode(request: Request):
    if _role(request) is None:
        return JSONResponse({"detail": "unauthorized"}, status_code=401)
    body = await request.json()
    if body.get("mode") == "MANUAL" and MODE_REFUSALS["remaining"] > 0:
        MODE_REFUSALS["remaining"] -= 1
        return JSONResponse({"error": {"code": "CALIBRATION_ACTIVE", "message": "refused"}},
                            status_code=409)
    STATE["mode"] = body.get("mode", "IDLE")
    MODE_LOG.append(STATE["mode"])
    return {"mode": STATE["mode"]}


# CORE 와 같은 수동 한도(rosy_default.yaml safety.manual_*·navigation.max_*).
LIMITS = {"session_linear": None, "max_linear": 0.2, "max_angular": 0.8,
          "manual_linear": 0.15, "manual_angular": 0.6}
TELEOP_LOG: list[dict] = []


PAIR_CODE = "TEST-CODE"


# 이 화면이 붙어 있는 로봇. 시험은 page.route 로 덮는다. 기본은 코드가 필요한 paired.
CONNECTION = {"mode": "paired", "robot_id": "rosy-dev", "transport": "http"}


@app.get("/api/v1/auth/connection")
def connection():
    return {"mode": CONNECTION["mode"], "robot_id": CONNECTION["robot_id"], "transport": CONNECTION["transport"]}


@app.post("/api/v1/auth/development-session", status_code=201)
def development_session():
    if CONNECTION["mode"] != "development":
        return JSONResponse({"error": {"code": "FORBIDDEN", "message": "this robot requires pairing"}},
                            status_code=403)
    return JSONResponse({"id": "dev-session", "token": DEV_TOKEN, "role": "operator",
                         "label": "Pilot development session", "source": "pair-development",
                         "expires_at": None}, status_code=201)


@app.post("/api/v1/auth/pair", status_code=201)
async def pair(request: Request):
    body = await request.json()
    if str(body.get("code", "")).upper() != PAIR_CODE:
        return JSONResponse({"error": {"code": "UNAUTHORIZED", "message": "invalid or expired login code"}},
                            status_code=401)
    return JSONResponse({"id": "pair-1", "token": "devtoken", "role": "operator", "label": body.get("label", ""),
                         "source": "pair-physical", "expires_at": None}, status_code=201)


#: D-193 §5 등록 코드(CORE 와 같은 모양). 관리자만 발급한다.
@app.post("/api/v1/auth/enrollment-codes", status_code=201)
async def enrollment_codes(request: Request):
    if _role(request) != "administrator":
        return JSONResponse({"detail": "administrator required"}, status_code=403)
    body = await request.json()
    role = str(body.get("role", "operator"))
    if role not in ("viewer", "operator"):
        return JSONResponse({"detail": "role must be viewer or operator"}, status_code=400)
    return JSONResponse({"code": "DEMO-C0DE", "code_id": "dev-enroll-1", "role": role,
                         "expires_in_s": 300}, status_code=201)


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


# --- D-411 A 로봇 녹화 흉내: 시험이 /__test__/recordings 로 상황을 정하고 요청 순서를 읽는다 ---
# blocker: 받기 차단 사유, role: "operator"|"viewer"(쓰기·받기 403), archive: "ok"|"short"(본문이
# Content-Length 보다 짧음)|"slow"(첫 조각 뒤 release 까지 멈춤)|"conflict"(목록과 달리 409),
# foreign: 다른 기기가 시작한 녹화, big: 256 MB 를 넘는 녹화본. polls 는 GET /active 횟수.
# starting: 시작이 먼저 "starting"(기록기가 아직 첫 파일을 열지 않음)이 되고, ready: true 로 recording.
# cap: true 면 녹화기가 10분 상한(max_duration)으로 스스로 멈춘다.
RECORDING_ID = "20261002T101500Z_rosy_dev"
_IDLE_RECORDER = {"schema": "rosy.pilot.recording.status/1", "state": "idle", "id": None, "elapsed_s": 0.0,
                  "bytes": 0, "max_duration_s": 600, "quota_free_bytes": 10**9, "last_stop_reason": "",
                  "boot_id": "dev", "seq": 0}
_RECORDING_DEFAULTS = {"blocker": None, "role": "operator", "archive": "ok", "big": False, "release": False,
                       "starting": False}
_RECORDING_LIVE = {"state": "recording", "id": "20261002T102000Z_rosy_dev", "elapsed_s": 1.0, "bytes": 2048}
RECORDINGS = {"active": dict(_IDLE_RECORDER), "owned": False, "log": [], "polls": 0, **_RECORDING_DEFAULTS}
_RECORDING_ITEM = {"id": RECORDING_ID, "started_at": "2026-10-02T10:15:00Z", "ended_at": "2026-10-02T10:16:05Z",
                   "duration_s": 65.0, "bytes": 1536, "topics": ["camera/front/compressed", "cmd_vel"],
                   "status": "complete", "manifest_sha256": "0" * 64, "fetched": False}


def _recording_tar() -> bytes:
    import io
    import tarfile
    data, body = io.BytesIO(), b'{"schema": "rosy.pilot.recording.manifest/1"}' * 64
    with tarfile.open(fileobj=data, mode="w", format=tarfile.USTAR_FORMAT) as archive:
        info = tarfile.TarInfo(f"{RECORDING_ID}/manifest.json")
        info.size = len(body)
        archive.addfile(info, io.BytesIO(body))
    return data.getvalue()


def _recording_error(code: str, status: int) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": code, "detail": None}}, status_code=status)


def _recording_writer(request: Request) -> JSONResponse | None:
    if _role(request) is None:
        return JSONResponse({"detail": "unauthorized"}, status_code=401)
    if RECORDINGS["role"] != "operator":
        return _recording_error("FORBIDDEN", 403)
    return None


@app.get("/__test__/recordings")
def recordings_log():
    return {key: RECORDINGS.get(key, 0) for key in ("log", "blocker", "polls", "owned", "lists")}


@app.post("/__test__/recordings")
async def recordings_script(request: Request):
    """본문의 키만 바꾼다. reset: true 면 모두 처음으로, foreign: true 면 남의 녹화가 돈다."""
    body = await request.json()
    if body.get("reset"):
        RECORDINGS.update(active=dict(_IDLE_RECORDER), owned=False, log=[], polls=0, **_RECORDING_DEFAULTS)
    for key in _RECORDING_DEFAULTS:
        if key in body:
            RECORDINGS[key] = body[key]
    if body.get("foreign"):
        RECORDINGS.update(owned=False, active={**_IDLE_RECORDER, "state": "recording",
                                               "id": "20261002T103000Z_rosy_dev", "elapsed_s": 3.0, "bytes": 4096})
    if body.get("cap"):  # 녹화기가 10분 상한에서 스스로 멈췄다
        RECORDINGS.update(owned=False, active={**_IDLE_RECORDER, "last_stop_reason": "max_duration"})
    if body.get("ready") and RECORDINGS["active"]["state"] == "starting":
        RECORDINGS["active"] = {**_IDLE_RECORDER, **_RECORDING_LIVE}
    return {key: RECORDINGS[key] for key in _RECORDING_DEFAULTS}


@app.get("/api/v1/recordings")
def recordings_list(request: Request):
    if _role(request) is None:
        return JSONResponse({"detail": "unauthorized"}, status_code=401)
    RECORDINGS["lists"] = RECORDINGS.get("lists", 0) + 1
    active = RECORDINGS["active"]
    blocker = "RECORDING_BUSY" if active["state"] != "idle" else RECORDINGS["blocker"]
    item ={**_RECORDING_ITEM, "bytes": 3 * 10**8} if RECORDINGS["big"] else _RECORDING_ITEM
    return {"active": active, "items": [item], "download_allowed": blocker is None,
            "download_blocker": blocker}


@app.get("/api/v1/recordings/active")
def recordings_active(request: Request):
    if _role(request) is None:
        return JSONResponse({"detail": "unauthorized"}, status_code=401)
    RECORDINGS["polls"] += 1
    return {"active": RECORDINGS["active"], "owned": RECORDINGS["owned"]}


@app.post("/api/v1/recordings", status_code=201)
def recordings_start(request: Request):
    if (refused := _recording_writer(request)) is not None:
        return refused
    if RECORDINGS["active"]["state"] != "idle":
        return _recording_error("RECORDING_BUSY", 409)
    RECORDINGS["log"].append("start")
    RECORDINGS["owned"] = True
    RECORDINGS["active"] = ({**_IDLE_RECORDER, "state": "starting", "id": _RECORDING_LIVE["id"]}
                            if RECORDINGS["starting"] else {**_IDLE_RECORDER, **_RECORDING_LIVE})
    return RECORDINGS["active"]


@app.post("/api/v1/recordings/active/stop")
def recordings_stop(request: Request):
    if (refused := _recording_writer(request)) is not None:
        return refused
    if RECORDINGS["active"]["state"] == "idle":
        return _recording_error("RECORDING_NOT_ACTIVE", 409)
    if not RECORDINGS["owned"]:
        return _recording_error("FORBIDDEN", 403)
    RECORDINGS["log"].append("stop")
    RECORDINGS["owned"] = False
    RECORDINGS["active"] = {**_IDLE_RECORDER, "last_stop_reason": "requested"}
    return RECORDINGS["active"]


@app.get("/api/v1/recordings/{recording_id:path}/archive")
def recordings_archive(recording_id: str, request: Request):
    if (refused := _recording_writer(request)) is not None:
        return refused
    if RECORDINGS["blocker"] or RECORDINGS["archive"] == "conflict":
        return _recording_error(RECORDINGS["blocker"] or "ROBOT_MOVING", 409)
    if recording_id != RECORDING_ID:
        return _recording_error("RECORDING_NOT_FOUND", 404)
    RECORDINGS["log"].append("archive")
    body, mode = _recording_tar(), RECORDINGS["archive"]

    async def stream():
        done = False
        try:
            if mode == "short":
                yield body[: len(body) // 2]       # CORE cut the stream: fewer bytes than promised
                return
            if mode == "slow":
                yield body[:512]
                for _ in range(300):               # at most 15 s, until the test releases it
                    if RECORDINGS["release"]:
                        break
                    await asyncio.sleep(0.05)
                yield body[512:]
            else:
                yield body
            done = True
        finally:
            RECORDINGS["log"].append("archive_done" if done else "archive_aborted")

    return StreamingResponse(stream(), media_type="application/x-tar",
                             headers={"Cache-Control": "no-store", "Content-Length": str(len(body)),
                                      "Content-Disposition": f'attachment; filename="{recording_id}.tar"'})


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
            await websocket.send_json({"type": "state", **state_frame()})
            await asyncio.sleep(0.1)
    except WebSocketDisconnect:
        return


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8642, log_level="warning")


# --- 차선 추종(D-344/D-364) 흉내: 시험이 /__test__/line-follow 로 다음 상태를 정한다 ---
LINE_FOLLOW = {"mode": "OFF", "state": "OFF", "source": None, "error": None, "confidence": 0.0,
               "linear": 0.0, "angular": 0.0, "reason": "mode_off", "clearance_m": None}
LINE_FOLLOW_SCRIPT = {}
#: 시험이 읽는다: PUT /line-follow/mode 로 들어온 mode 값의 순서(같은 프로세스의 uvicorn 스레드).
LINE_FOLLOW_MODE_LOG: list[str] = []


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
    LINE_FOLLOW_MODE_LOG.append(mode)
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
