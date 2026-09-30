"""콘솔 HTTP 표면 — 상태·지도·세션·대형·신호등 (FleetConsole 소유 경로).

console.py 의 gather/scatter 를 그대로 드러내는 읽기와 위임이다. 판단·대기열은
여기 없다 — 대형 규칙은 `server/AGENTS.md` 를 따른다.
"""

from __future__ import annotations

from typing import Optional

from fastapi import HTTPException, Request
from pydantic import BaseModel

from fleet.hub.hub import HubError
from fleet.server.http_errors import http_error
from fleet.server.site_auth import SitePrincipal
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


def install_console_routes(app, *, console, sightings, require_viewer,
                           read_guard, operator_guard) -> None:
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

    @app.get("/api/fleet/map", dependencies=read_guard, tags=["fleet"])
    async def fleet_map() -> dict:
        grid = await console.map()
        if grid is None:
            raise HTTPException(status_code=404, detail={"code": "NO_MAP",
                                                         "message": "no robot served a map"})
        return grid

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
