"""콘솔 HTTP 표면 — 상태·지도·세션·대형·신호등 (FleetConsole 소유 경로).

console.py 의 gather/scatter 를 그대로 드러내는 읽기와 위임이다. 판단·대기열은
여기 없다 — 대형 규칙은 `server/AGENTS.md` 를 따른다.
"""

from __future__ import annotations

import hashlib
import json
from typing import Optional

from typing import Literal

from fastapi import Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from fleet.hub.hub import HubError
from fleet.server.http_errors import http_error
from fleet.server.site_auth import SitePrincipal
from fleet.server.site_lanes import site_lanes_payload
from fleet.server.signals import SignalApiError
from fleet.swarm.transport import RobotApiError


class FormationRequest(BaseModel):
    leader: str
    formation: str = "COLUMN"
    spacing: Optional[float] = None
    max_speed: Optional[float] = None
    members: Optional[list[str]] = None  # FOR-001 Robot Selection — None 은 전원이다


class ReformRequest(BaseModel):
    formation: str
    spacing: Optional[float] = None
    max_speed: Optional[float] = None


class SignalCommandRequest(BaseModel):
    """ROSY-SIGNAL-001 의 `POST /command` 본문. `seq` 는 콘솔이 채운다 — 화면이
    붙이기 시작하면 두 명령이 같은 seq 로 싸운다."""
    mode: str
    lamps: Optional[dict[str, bool]] = None
    cycle: Optional[dict[str, int]] = None


class LineStuckDecisionRequest(BaseModel):
    """D-407 §2: one answer, bound to the stuck id the operator saw."""
    model_config = ConfigDict(extra="forbid")
    stuck_id: str = Field(min_length=1, max_length=64)
    decision: Literal["WAIT", "RESUME", "BACK_AND_RETRY", "MANUAL", "ABORT"]


def install_console_routes(app, *, console, sightings, require_viewer,
                           read_guard, operator_guard, require_operator,
                           site_lanes=None) -> None:
    @app.get("/api/fleet/state", dependencies=read_guard, tags=["fleet"])
    async def fleet_state() -> dict:
        return await console.snapshot()

    @app.get("/api/fleet/session", dependencies=read_guard, tags=["fleet-auth"])
    def fleet_session(request: Request) -> dict:
        principal: SitePrincipal = request.state.site_principal
        return {"principal_id": principal.principal_id, "role": principal.role}

    @app.get("/api/fleet/site-map", dependencies=read_guard, tags=["sightings"])
    async def fleet_site_map() -> dict:
        # D-257: the overhead-covered rectangle is display geometry, not a motion input.
        site_map = sightings.site_map() if sightings is not None and sightings.enabled else None
        if site_map is None:
            raise HTTPException(status_code=404, detail={"code": "NO_SITE_MAP",
                                                         "message": "no site camera geometry configured"})
        return site_map

    # D-375: lane geometry for the console map-fit overlay. Drawn only, never driven. The files
    # and sources are fixed for the process, so the body (~100 kB) is built once at start-up.
    lanes_body = site_lanes_payload(site_lanes or {}, sightings.sources if sightings is not None else ())
    lanes_json = json.dumps(lanes_body, separators=(",", ":")).encode() if lanes_body else b""
    lanes_etag = f'"{hashlib.sha256(lanes_json).hexdigest()[:32]}"'

    @app.get("/api/fleet/site-lanes", dependencies=read_guard, tags=["sightings"])
    async def fleet_site_lanes(request: Request) -> Response:
        if lanes_body is None:
            raise HTTPException(status_code=404, detail={"code": "NO_SITE_LANES",
                                                         "message": "no site lane graph configured"})
        headers = {"Cache-Control": "private, no-cache", "ETag": lanes_etag}
        if request.headers.get("If-None-Match") == lanes_etag:
            return Response(status_code=304, headers=headers)
        return Response(lanes_json, media_type="application/json", headers=headers)

    @app.get("/api/fleet/map", dependencies=read_guard, tags=["fleet"])
    async def fleet_map() -> dict:
        grid = await console.map()
        if grid is None:
            raise HTTPException(status_code=404, detail={"code": "NO_MAP",
                                                         "message": "no robot served a map"})
        return grid

    @app.get("/api/fleet/line-stuck", dependencies=read_guard, tags=["line-stuck"])
    async def line_stuck_pending() -> dict:
        # D-407: re-gather so the list is as fresh as /state; CORE's stuck block is the truth.
        await console.snapshot()
        return {"pending": console.line_stuck.pending(), "answers": console.line_stuck.answers()}

    @app.post("/api/fleet/robots/{robot_id}/line-stuck/decision", dependencies=operator_guard,
              tags=["line-stuck"])
    async def line_stuck_decision(robot_id: str, body: LineStuckDecisionRequest,
                                  principal: SitePrincipal = Depends(require_operator)) -> dict:
        board = console.line_stuck
        try:
            result = await console.line_stuck_decision(robot_id, body.stuck_id, body.decision)
        except RobotApiError as exc:
            # CORE's refusal reaches the operator verbatim (STUCK_ID_MISMATCH, RESUME refused
            # with its reason, EMERGENCY_ACTIVE, ...). 409 stays 409; anything else is 502.
            board.record(robot_id=robot_id, stuck_id=body.stuck_id, decision=body.decision,
                         principal_id=principal.principal_id, accepted=False,
                         code=exc.code, message=exc.message)
            raise HTTPException(status_code=409 if exc.status == 409 else 502, detail={
                "code": exc.code, "message": exc.message, "robot_id": robot_id,
                "robot_status": exc.status}) from exc
        except (HubError, OSError) as exc:
            if not (isinstance(exc, HubError) and exc.code == "UNKNOWN_ROBOT"):
                board.record(robot_id=robot_id, stuck_id=body.stuck_id, decision=body.decision,
                             principal_id=principal.principal_id, accepted=False,
                             code=getattr(exc, "code", type(exc).__name__), message=str(exc))
            raise http_error(exc) from exc
        answer = board.record(robot_id=robot_id, stuck_id=body.stuck_id, decision=body.decision,
                              principal_id=principal.principal_id, accepted=True,
                              outcome=result.get("outcome"))
        return {"robot_id": robot_id, "actor_id": principal.principal_id,
                "answer": answer, "result": result}

    @app.get("/api/fleet/formation", dependencies=read_guard, tags=["formation"])
    async def formation_state() -> dict:
        return console.formation_status()

    @app.post("/api/fleet/formation/start", dependencies=operator_guard, tags=["formation"])
    async def formation_start(body: FormationRequest) -> dict:
        try:
            return await console.formation_start(body.leader, body.formation,
                                                 body.spacing, body.max_speed,
                                                 members=body.members)
        except (HubError, RobotApiError, OSError) as exc:
            raise http_error(exc) from exc

    @app.post("/api/fleet/formation/reform", dependencies=operator_guard, tags=["formation"])
    async def formation_reform(body: ReformRequest) -> dict:
        try:
            return await console.formation_reform(body.formation, body.spacing, body.max_speed)
        except (HubError, RobotApiError, OSError) as exc:
            raise http_error(exc) from exc

    @app.post("/api/fleet/formation/resume", dependencies=operator_guard, tags=["formation"])
    async def formation_resume() -> dict:
        try:
            return await console.formation_resume()
        except (HubError, RobotApiError, OSError) as exc:
            raise http_error(exc) from exc

    @app.post("/api/fleet/formation/stop", dependencies=operator_guard, tags=["formation"])
    async def formation_stop() -> dict:
        # 해제는 거절하지 않는다. 대형을 못 푸는 화면은 대형을 여는 화면보다 나쁘다.
        return await console.formation_stop()

    @app.get("/api/fleet/signals", dependencies=read_guard, tags=["signals"])
    async def fleet_signals() -> dict:
        try:
            return await console.signals_detail()
        except (HubError, OSError) as exc:
            raise http_error(exc) from exc

    @app.post("/api/fleet/signals/{signal_id}/command", dependencies=operator_guard, tags=["signals"])
    async def fleet_signal_command(signal_id: str, body: SignalCommandRequest) -> dict:
        try:
            return await console.signal_command(signal_id, body.model_dump(exclude_none=True))
        except (HubError, SignalApiError, OSError) as exc:
            raise http_error(exc) from exc
