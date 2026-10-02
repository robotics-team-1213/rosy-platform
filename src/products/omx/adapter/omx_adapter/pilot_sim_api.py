"""Same-origin Pilot API for one isolated, simulated OMX-AI workcell."""

from __future__ import annotations

import asyncio
import json
import secrets
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, Field

from core_common.protocol.omx_sim import OmxSimGoal, OmxSimJog, OmxSimTarget
from core_common.protocol.omx_sim import OmxSimRecordStart, OmxSimRecordStop, OmxSimRecording


PREFIX = "/api/v1/sim/omx"
SEAT_TTL_S = 10
PILOT_ASSETS = {
    "styles.css": "text/css", "app.js": "application/javascript",
    "client.js": "application/javascript", "stick.js": "application/javascript",
    "link.js": "application/javascript", "autonomy.js": "application/javascript",
    "input-state.js": "application/javascript", "vision.js": "application/javascript",
    "calibration.js": "application/javascript", "recording.js": "application/javascript",
    "controls.js": "application/javascript", "arm-stick.js": "application/javascript",
    "drivers/registry.js": "application/javascript",
    "drivers/pinky_core.js": "application/javascript",
    "drivers/omx_sim.js": "application/javascript",
    "screens/connect.js": "application/javascript",
    "screens/drive.js": "application/javascript",
    "screens/drive-auto.js": "application/javascript",
    "screens/drive-view.js": "application/javascript",
    "screens/inputs.js": "application/javascript",
    "screens/robot-recording.js": "application/javascript",
    "screens/arm.js": "application/javascript",
    "screens/compose.js": "application/javascript", "widgets/joint_jog.js": "application/javascript",
    "manifest.webmanifest": "application/manifest+json",
    "sw.js": "application/javascript",
    "icons/icon-192.png": "image/png",
    "icons/icon-192-maskable.png": "image/png",
    "icons/icon-512.png": "image/png",
}
class PairRequest(BaseModel):
    code: str = Field(min_length=1, max_length=32)


class _Sessions:
    def __init__(self, code: str, *, clock=time.monotonic) -> None:
        if not code or len(code) < 8:
            raise ValueError("an operator-provided one-time pairing code is required")
        self._code = code
        self._code_deadline = clock() + 600
        self._clock = clock
        self._tokens: dict[str, float] = {}
        self._seat: tuple[str, str, float] | None = None
        self._lock = threading.RLock()

    def pair(self, code: str) -> str:
        with self._lock:
            if not self._code or self._clock() > self._code_deadline or not secrets.compare_digest(code, self._code):
                raise HTTPException(403, "pairing code unavailable")
            self._code = ""
            token = secrets.token_urlsafe(32)
            self._tokens[token] = self._clock() + 3600
            return token

    def require(self, authorization: str | None) -> str:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(401, "bearer token required")
        token = authorization[7:]
        with self._lock:
            expiry = self._tokens.get(token)
            if expiry is None or self._clock() >= expiry:
                raise HTTPException(401, "token expired or unknown")
        return token

    def acquire(self, token: str) -> str:
        with self._lock:
            if self._seat and self._clock() < self._seat[2]:
                if self._seat[0] != token:
                    raise HTTPException(409, "seat occupied")
                self._seat = (token, self._seat[1], self._clock() + SEAT_TTL_S)
                return self._seat[1]
            seat_id = secrets.token_urlsafe(16)
            self._seat = (token, seat_id, self._clock() + SEAT_TTL_S)
            return seat_id

    def check_seat(self, token: str, seat_id: str) -> None:
        with self._lock:
            if (self._seat is None or self._seat[0] != token
                    or not secrets.compare_digest(self._seat[1], seat_id)
                    or self._clock() >= self._seat[2]):
                raise HTTPException(409, "seat missing or expired")

    def release(self, token: str, seat_id: str) -> None:
        self.check_seat(token, seat_id)
        with self._lock:
            self._seat = None

    def expire_seat(self) -> bool:
        with self._lock:
            if self._seat is None or self._clock() < self._seat[2]:
                return False
            self._seat = None
            return True


def create_pilot_sim_app(*, runtime: Any, pilot_root: Path, common_root: Path,
                         pairing_code: str) -> FastAPI:
    """Construct a SIM-only HTTP surface; runtime is the sole action owner."""
    sessions = _Sessions(pairing_code)
    common_assets = json.loads((common_root / "shared-assets.json").read_text(encoding="utf-8"))["shared_assets"]
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async def watch_seat():
            while True:
                await asyncio.sleep(0.1)
                if sessions.expire_seat():
                    runtime.cancel_active()
                runtime.on_watchdog()

        task = asyncio.create_task(watch_seat())
        try:
            yield
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            runtime.cancel_active()

    app = FastAPI(title="Rosy OMX Pilot Simulation", version="1", lifespan=lifespan)

    @app.exception_handler(HTTPException)
    async def http_error(_request, exc: HTTPException) -> JSONResponse:
        code = {401: "UNAUTHORIZED", 403: "FORBIDDEN", 404: "NOT_FOUND",
                409: "MODE_CONFLICT"}.get(exc.status_code, "INTERNAL_ERROR")
        return JSONResponse(status_code=exc.status_code,
                            content={"error": {"code": code, "message": str(exc.detail), "detail": {}}})

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request, exc: RequestValidationError) -> JSONResponse:
        fields = [".".join(str(part) for part in item["loc"]) for item in exc.errors()]
        return JSONResponse(status_code=400,
                            content={"error": {"code": "VALIDATION_ERROR",
                                               "message": "request validation failed",
                                               "detail": {"fields": fields}}})
    receipts: dict[str, tuple[OmxSimJog, dict[str, Any]]] = {}
    receipt_lock = threading.RLock()

    def auth(authorization: str | None) -> str:
        return sessions.require(authorization)

    @app.get("/pilot")
    @app.get("/pilot/")
    def pilot() -> FileResponse:
        return FileResponse(pilot_root / "index.html", media_type="text/html",
                            headers={"Cache-Control": "no-cache",
                                     "Content-Security-Policy": "default-src 'self'; connect-src 'self'; img-src 'self' data: blob:; style-src 'self'; script-src 'self'; frame-ancestors 'none'; base-uri 'self'"})

    @app.get("/pilot/assets/{name:path}")
    def pilot_asset(name: str) -> FileResponse:
        mime = PILOT_ASSETS.get(name)
        if mime is None:
            raise HTTPException(404, "asset not found")
        headers = {"Cache-Control": "no-cache"}
        if name == "sw.js":
            headers["Service-Worker-Allowed"] = "/pilot"
        return FileResponse(pilot_root / name, media_type=mime, headers=headers)

    @app.get("/common/{name:path}")
    def common_asset(name: str) -> FileResponse:
        mime = common_assets.get(name)
        if mime is None:
            raise HTTPException(404, "asset not found")
        return FileResponse(common_root / name, media_type=mime)

    @app.get(f"{PREFIX}/target")
    def target() -> OmxSimTarget:
        return OmxSimTarget(instance_id=runtime.instance_id,
                            joints=tuple(j for j in runtime.joint_names if j != runtime.gripper),
                            gripper=runtime.gripper,
                            camera=bool(getattr(runtime, "camera_available", False)),
                            recording=getattr(runtime, "capture", None) is not None,
                            controls=runtime.controls())

    @app.post(f"{PREFIX}/pair", status_code=201)
    def pair(request: PairRequest) -> dict[str, str]:
        return {"token": sessions.pair(request.code)}

    @app.get(f"{PREFIX}/whoami")
    def whoami(authorization: str | None = Header(None)) -> dict[str, str]:
        auth(authorization)
        return {"role": "operator"}

    @app.post(f"{PREFIX}/seat")
    def acquire_seat(authorization: str | None = Header(None)) -> dict[str, str]:
        return {"seat_id": sessions.acquire(auth(authorization))}

    @app.put(f"{PREFIX}/seat/{{seat_id}}")
    def renew_seat(seat_id: str, authorization: str | None = Header(None)) -> dict[str, str]:
        token = auth(authorization)
        sessions.check_seat(token, seat_id)
        return {"seat_id": sessions.acquire(token)}

    @app.delete(f"{PREFIX}/seat/{{seat_id}}", status_code=204, response_class=Response)
    def release_seat(seat_id: str, authorization: str | None = Header(None)) -> Response:
        sessions.release(auth(authorization), seat_id)
        runtime.cancel_active()
        return Response(status_code=204)

    @app.get(f"{PREFIX}/state")
    def state(authorization: str | None = Header(None)) -> dict[str, Any]:
        auth(authorization)
        return runtime.snapshot()

    def capture():
        selected = getattr(runtime, "capture", None)
        if selected is None:
            raise HTTPException(409, "camera and recording unavailable")
        return selected

    def recording_response(value: dict) -> OmxSimRecording:
        return OmxSimRecording.model_validate({key: value[key] for key in OmxSimRecording.model_fields
                                              if key in value})

    @app.get(f"{PREFIX}/camera")
    def camera(authorization: str | None = Header(None)) -> dict:
        auth(authorization)
        return capture().camera_status()

    @app.get(f"{PREFIX}/camera/frame")
    def camera_frame(authorization: str | None = Header(None)) -> Response:
        auth(authorization)
        try:
            data = capture().camera_jpeg()
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        return Response(data, media_type="image/jpeg", headers={"Cache-Control": "no-store"})

    @app.get(f"{PREFIX}/recordings")
    def recording(authorization: str | None = Header(None)) -> OmxSimRecording:
        auth(authorization)
        return recording_response(capture().status())

    @app.post(f"{PREFIX}/recordings", status_code=201)
    def start_recording(request: OmxSimRecordStart, authorization: str | None = Header(None)) -> OmxSimRecording:
        sessions.check_seat(auth(authorization), request.seat_id)
        try:
            result = capture().start(request.task)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        return recording_response(result)

    @app.post(f"{PREFIX}/recordings/{{episode_id}}/stop")
    def stop_recording(episode_id: str, request: OmxSimRecordStop,
                       authorization: str | None = Header(None)) -> OmxSimRecording:
        sessions.check_seat(auth(authorization), request.seat_id)
        try:
            result = capture().stop(episode_id, request.outcome)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        return recording_response(result)

    @app.get(f"{PREFIX}/recordings/{{episode_id}}/manifest")
    def recording_manifest(episode_id: str, authorization: str | None = Header(None)) -> dict:
        auth(authorization)
        try:
            return capture().manifest(episode_id)
        except (ValueError, FileNotFoundError) as exc:
            raise HTTPException(404, "episode unknown") from exc

    @app.post(f"{PREFIX}/goals", status_code=202)
    def submit(jog: OmxSimJog, authorization: str | None = Header(None)) -> dict[str, Any]:
        token = auth(authorization)
        sessions.check_seat(token, jog.seat_id)
        if jog.instance_id != runtime.instance_id:
            raise HTTPException(409, "instance mismatch")
        now_ms = int(time.time() * 1000)
        if not now_ms < jog.expires_at_ms <= now_ms + 6000:
            raise HTTPException(409, "request expired or expiry too distant")
        with receipt_lock:
            previous = receipts.get(jog.request_id)
            if previous is not None:
                if previous[0] != jog:
                    raise HTTPException(409, "request id reused")
                return previous[1]
            result = OmxSimGoal.model_validate(runtime.submit(jog)).model_dump()
            receipts[jog.request_id] = (jog, result)
            if result["state"] in {"REJECTED", "UNKNOWN_HOLD"}:
                raise HTTPException(409, result["reason"])
            return result

    @app.get(f"{PREFIX}/goals/{{command_id}}")
    def goal(command_id: str, authorization: str | None = Header(None)) -> dict[str, Any]:
        auth(authorization)
        if command_id not in receipts:
            raise HTTPException(404, "goal unknown")
        return OmxSimGoal.model_validate(runtime.goal(command_id)).model_dump()

    @app.post(f"{PREFIX}/goals/{{command_id}}/cancel")
    def cancel(command_id: str, seat_id: str,
               authorization: str | None = Header(None)) -> dict[str, Any]:
        token = auth(authorization)
        sessions.check_seat(token, seat_id)
        if command_id not in receipts:
            raise HTTPException(404, "goal unknown")
        return OmxSimGoal.model_validate(runtime.cancel(command_id)).model_dump()

    return app
