"""콘솔 HTTP 표면 — 상태·지도·세션·대형·신호등 (FleetConsole 소유 경로).

console.py 의 gather/scatter 를 그대로 드러내는 읽기와 위임이다. 판단·대기열은
여기 없다 — 대형 규칙은 `server/AGENTS.md` 를 따른다.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from functools import partial
from typing import Callable, Literal, Optional

import httpx
from fastapi import Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from fleet.hub.hub import HubError
from fleet.server.http_errors import http_error
from fleet.server.line_stuck import LineStuckAnswerLog, LineStuckBoard
from fleet.server.site_auth import SitePrincipal
from fleet.server.site_lanes import site_lanes_payload
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


class LineStuckDecisionRequest(BaseModel):
    """D-407 §2: one answer, bound to the stuck id the operator saw."""
    model_config = ConfigDict(extra="forbid")
    # CORE ids are `stuck-<12 hex>`; the pattern keeps the id inert in logs and audit rows.
    stuck_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.:-]+$")
    decision: Literal["WAIT", "RESUME", "BACK_AND_RETRY", "MANUAL", "ABORT"]


class LineStuckClaimRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    stuck_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.:-]+$")


def transport_failure(exc: BaseException) -> tuple[str, str]:
    """A connect failure never reached CORE; anything later may have been applied."""
    if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout, ConnectionRefusedError)):
        return "ROBOT_UNREACHABLE", "answer not delivered: the robot could not be reached"
    return ("STUCK_DECISION_OUTCOME_UNKNOWN",
            "the robot did not reply; CORE may have applied the answer. "
            "Re-read the stuck before answering again")


class SharedGather:
    """D-438: one ``console.snapshot()`` + ``board.observe`` for every reader within
    ``max_age_s``. The snapshot also runs traffic, hand-off and swarm-speed logic and GETs
    every robot, so the state route and the resolver must not each run it. Callers treat
    the returned snapshot as read-only: it is shared."""

    def __init__(self, console, board: LineStuckBoard, *, max_age_s: float = 1.0,
                 clock: Callable[[], float] = time.monotonic, tracking=None) -> None:
        self._console, self._board, self._clock = console, board, clock
        self._tracking = tracking
        self.max_age_s = max_age_s
        self._lock = asyncio.Lock()
        self._snapshot: Optional[dict] = None
        self._at = 0.0

    async def __call__(self) -> dict:
        async with self._lock:
            if self._snapshot is None or self._clock() - self._at >= self.max_age_s:
                gathered_at = self._tracking.now() if self._tracking is not None else None
                snapshot = await self._console.snapshot()
                if self._tracking is not None:
                    self._tracking.observe_states(snapshot["robots"], now=gathered_at)
                self._board.observe(snapshot["robots"], self._console.hub.registry.events_since)
                self._snapshot, self._at = snapshot, self._clock()
            return self._snapshot


def install_console_routes(app, *, console, sightings, require_viewer,
                           read_guard, operator_guard, require_operator,
                           site_lanes=None, answer_log_path=None, tracking=None) -> None:
    # D-407: open lane stucks, read from each gather. CORE's stuck block is the truth.
    board = app.state.line_stuck = LineStuckBoard(
        log=LineStuckAnswerLog(answer_log_path) if answer_log_path is not None else None)

    gather = app.state.fleet_gather = SharedGather(console, board, tracking=tracking)

    async def gathered() -> dict:
        snapshot = await gather()
        # Per response, on copies: the cached snapshot is shared with the resolver.
        return {**snapshot, "robots": [{**row, "line_stuck": board.view(row["robot_id"])}
                                       for row in snapshot["robots"]]}

    @app.get("/api/fleet/state", dependencies=read_guard, tags=["fleet"])
    async def fleet_state() -> dict:
        return await gathered()

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
        # The board as of the last shared gather (the resolver and the console's /state
        # poll refresh it about every second); this read does not fan out to every robot.
        # `observed_age_s` says how old it is.
        return {"pending": board.pending(), "answers": board.answers(),
                "observed_age_s": board.observed_age_s()}

    @app.post("/api/fleet/robots/{robot_id}/line-stuck/decision", dependencies=operator_guard,
              tags=["line-stuck"])
    async def line_stuck_decision(robot_id: str, body: LineStuckDecisionRequest, request: Request,
                                  principal: SitePrincipal = Depends(require_operator)) -> dict:
        client = console.clients().get(robot_id)
        if client is None:
            raise http_error(HubError("UNKNOWN_ROBOT", robot_id))
        # D-438 §1: claim before forwarding, so the resolver cannot answer in the gap.
        # The claim stays even if the CORE forward fails: a human owns this stuck now.
        resolver_loop = getattr(app.state, "stuck_resolver", None)
        if resolver_loop is not None:
            resolver_loop.claim(robot_id, body.stuck_id)
        record = partial(board.record, robot_id=robot_id, stuck_id=body.stuck_id,
                         decision=body.decision, principal_id=principal.principal_id, tier="human",
                         audit_id=getattr(request.state, "site_api_audit_id", None))
        try:
            # Forwarded unchanged with the robot credential; CORE alone judges the answer.
            result = await client.line_stuck_decision(body.stuck_id, body.decision)
        except RobotApiError as exc:
            # CORE's refusal reaches the operator verbatim (STUCK_ID_MISMATCH, RESUME refused
            # with its reason, EMERGENCY_ACTIVE, ...). 409 stays 409; anything else is 502.
            record(accepted=False, code=exc.code, message=exc.message)
            raise HTTPException(status_code=409 if exc.status == 409 else 502, detail={
                "code": exc.code, "message": exc.message, "robot_id": robot_id,
                "robot_status": exc.status}) from exc
        except (httpx.HTTPError, OSError) as exc:
            code, message = transport_failure(exc)
            record(accepted=False if code == "ROBOT_UNREACHABLE" else None,
                   code=code, message=f"{message} ({type(exc).__name__})")
            raise HTTPException(status_code=502, detail={
                "code": code, "message": message, "robot_id": robot_id,
                "transport": type(exc).__name__}) from exc
        answer = record(accepted=True, outcome=result.get("outcome"))
        return {"robot_id": robot_id, "actor_id": principal.principal_id,
                "answer": answer, "result": result}

    @app.post("/api/fleet/robots/{robot_id}/line-stuck/claim", dependencies=operator_guard,
              tags=["line-stuck"])
    async def line_stuck_claim(robot_id: str, body: LineStuckClaimRequest,
                               principal: SitePrincipal = Depends(require_operator)) -> dict:
        """D-438 §1: a human opened this stuck; the resolver stops answering it."""
        if console.clients().get(robot_id) is None:
            raise http_error(HubError("UNKNOWN_ROBOT", robot_id))
        resolver_loop = getattr(app.state, "stuck_resolver", None)
        if resolver_loop is not None:
            resolver_loop.claim(robot_id, body.stuck_id)
        return {"robot_id": robot_id, "stuck_id": body.stuck_id,
                "claimed_by": principal.principal_id}

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
