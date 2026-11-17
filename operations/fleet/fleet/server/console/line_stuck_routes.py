"""Line-stuck and incident HTTP routes for FleetConsole (D-407, D-438, D-577)."""

from __future__ import annotations

import asyncio
import base64
import json
import math
import time
from functools import partial
from typing import Literal, Optional

import httpx
from fastapi import Depends, HTTPException, Path, Query, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from fleet.hub.hub import HubError
from fleet.incidents.handoff import judgment_revision
from fleet.server.http_errors import http_error
from fleet.server.site_auth import SitePrincipal
from fleet.stuck.board import LineStuckBoard
from fleet.swarm.transport import RobotApiError


class LineStuckDecisionRequest(BaseModel):
    """D-407 §2: one answer, bound to the stuck id the operator saw."""
    model_config = ConfigDict(extra="forbid")
    stuck_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.:-]+$")
    decision: Literal["WAIT", "RESUME", "BACK_AND_RETRY", "MANUAL", "ABORT"]


class LineStuckClaimRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    stuck_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.:-]+$")
    judgment_revision: Optional[str] = Field(default=None, pattern=r"^[a-f0-9]{64}$")


class IncidentReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    root_cause: Literal["line_marking", "obstacle", "robot_fault", "localization", "traffic_wait", "unknown"]
    note: str = Field(max_length=1000)


def transport_failure(exc: BaseException) -> tuple[str, str]:
    """A connect failure never reached CORE; anything later may have been applied."""
    if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout, ConnectionRefusedError)):
        return "ROBOT_UNREACHABLE", "answer not delivered: the robot could not be reached"
    return ("STUCK_DECISION_OUTCOME_UNKNOWN",
            "the robot did not reply; CORE may have applied the answer. Re-read the stuck before answering again")


def install_line_stuck_routes(app, *, console, board: LineStuckBoard, gather, read_guard,
                              operator_guard, require_operator, require_named_operator) -> None:
    @app.get("/api/fleet/line-stuck", dependencies=read_guard, tags=["line-stuck"])
    async def line_stuck_pending() -> dict:
        return {"pending": board.pending(), "answers": board.answers(), "observed_age_s": board.observed_age_s()}

    async def stuck_evidence(robot_id: str, stuck_id: str, live: bool) -> tuple[dict, bytes]:
        """The evidence picture's metadata and JPEG bytes (shared by the JSON and binary routes)."""
        if not board.is_open(robot_id, stuck_id):
            raise HTTPException(status_code=404, detail={"code": "STUCK_NOT_OPEN",
                                                         "message": f"{robot_id} has no open stuck {stuck_id}"})
        shown = None if live else board.preview(robot_id, stuck_id)
        if shown is None:
            fetch = getattr(console.clients().get(robot_id), "front_frame", None)
            try:
                if fetch is None:
                    raise RobotApiError(robot_id, 404, "CAMERA_FRAME_UNAVAILABLE", "no camera client")
                started = time.monotonic()
                jpeg, status = await asyncio.wait_for(fetch(overlay=False) if live else fetch(), timeout=3.0)
            except (RobotApiError, httpx.HTTPError, OSError, asyncio.TimeoutError) as exc:
                raise HTTPException(status_code=404, detail={
                    "code": "STUCK_PREVIEW_UNAVAILABLE", "message": getattr(exc, "code", type(exc).__name__)}) from exc
            if not board.is_open(robot_id, stuck_id):
                raise HTTPException(status_code=404, detail={"code": "STUCK_NOT_OPEN", "message": f"{stuck_id} closed"})
            if live:
                captured, age = status.get("captured_at"), status.get("age_ms")
                if isinstance(captured, (int, float)) and not isinstance(captured, bool) and math.isfinite(captured):
                    age_s = time.time() - captured
                else:
                    age_s = (age / 1000.0 + time.monotonic() - started
                             if isinstance(age, (int, float)) and not isinstance(age, bool) else float("nan"))
                if not jpeg or not math.isfinite(age_s) or not 0 <= age_s <= 3.0:
                    raise HTTPException(status_code=404, detail={"code": "STUCK_PREVIEW_UNAVAILABLE",
                                                                 "message": "current raw frame age unknown or stale"})
                return {"robot_id": robot_id, "stuck_id": stuck_id, "sequence": status.get("sequence"),
                        "source": status.get("source"), "media_type": "image/jpeg", "live": True,
                        "captured_at": captured, "age_s": round(age_s, 3)}, bytes(jpeg)
            board.keep_preview(robot_id, stuck_id, jpeg, status)
            shown = board.preview(robot_id, stuck_id)
            if shown is None:
                raise HTTPException(status_code=404, detail={"code": "STUCK_NOT_OPEN", "message": f"{stuck_id} closed"})
        return shown, board.preview_jpeg(robot_id, stuck_id)

    @app.get("/api/fleet/robots/{robot_id}/line-stuck/evidence", dependencies=read_guard, tags=["line-stuck"])
    async def line_stuck_evidence(robot_id: str, request: Request, stuck_id: str = Query(
            min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.:-]+$"), live: bool = False):
        meta, jpeg = await stuck_evidence(robot_id, stuck_id, live)
        if request.headers.get("accept", "").startswith("image/jpeg"):
            return Response(jpeg, media_type="image/jpeg", headers={
                "Cache-Control": "no-store", "X-Stuck-Evidence": json.dumps(meta, separators=(",", ":"))})
        return JSONResponse({**meta, "jpeg_base64": base64.b64encode(jpeg).decode("ascii")},
                            headers={"Cache-Control": "no-store"})

    @app.get("/api/fleet/line-stuck/episodes", dependencies=read_guard, tags=["line-stuck"])
    def line_stuck_episodes(limit: int = Query(100, ge=1, le=1000)) -> dict:
        return {"episodes": board.episodes(limit)}

    @app.get("/api/fleet/incidents", dependencies=read_guard, tags=["line-stuck"])
    def incident_reports(limit: int = Query(20, ge=1, le=100),
                         robot_id: Optional[str] = Query(None, min_length=1, max_length=64, pattern=r'^[A-Za-z0-9_.:-]+$'),
                         stuck_id: Optional[str] = Query(None, min_length=1, max_length=64, pattern=r'^[A-Za-z0-9_.:-]+$')) -> dict:
        if (robot_id is None) != (stuck_id is None):
            raise HTTPException(422, detail={'code': 'INCIDENT_FILTER_PAIR_REQUIRED'})
        return {"reports": board.reports(limit, robot_id=robot_id, stuck_id=stuck_id),
                "traffic_reports": board.traffic_reports(limit) if robot_id is None else []}

    @app.get("/api/fleet/judgments", dependencies=read_guard, tags=["line-stuck"])
    def judgment_receipts(limit: int = Query(100, ge=1, le=1000)) -> dict:
        return {"records": board.judgments(limit)}

    @app.get('/api/fleet/notifications', dependencies=read_guard, tags=['line-stuck'])
    def notification_receipts(limit: int = Query(100, ge=1, le=1000)) -> dict:
        return {'records': board._log.notifications.rows(limit) if board._log is not None else []}

    @app.post("/api/fleet/incidents/facts/{fact_row}/review", dependencies=operator_guard, tags=["line-stuck"])
    def review_traffic_fact(body: IncidentReviewRequest, fact_row: int = Path(ge=1, le=2**63 - 1),
                            principal: SitePrincipal = Depends(require_named_operator)) -> dict:
        if not board.review_traffic_fact(fact_row, principal_id=principal.principal_id,
                                         root_cause=body.root_cause, note=body.note):
            raise HTTPException(status_code=404, detail={"code": "INCIDENT_NOT_FOUND"})
        return {"reviewed": True}

    @app.post("/api/fleet/incidents/{robot_id}/{stuck_id}/review", dependencies=operator_guard, tags=["line-stuck"])
    def review_incident(robot_id: str, stuck_id: str, body: IncidentReviewRequest,
                        principal: SitePrincipal = Depends(require_named_operator)) -> dict:
        if not board.review(robot_id, stuck_id, principal_id=principal.principal_id,
                            root_cause=body.root_cause, note=body.note):
            raise HTTPException(status_code=404, detail={"code": "INCIDENT_NOT_FOUND"})
        return {"reviewed": True}

    @app.post("/api/fleet/robots/{robot_id}/line-stuck/decision", dependencies=operator_guard, tags=["line-stuck"])
    async def line_stuck_decision(robot_id: str, body: LineStuckDecisionRequest, request: Request,
                                  principal: SitePrincipal = Depends(require_operator)) -> dict:
        if body.decision not in ("WAIT", "ABORT"):
            require_named_operator(principal)
        client = console.clients().get(robot_id)
        if client is None:
            raise http_error(HubError("UNKNOWN_ROBOT", robot_id))
        on_trip = console.trip_refusal([robot_id])
        if on_trip and body.decision in ("RESUME", "BACK_AND_RETRY", "YIELD"):  # D-494 5: motion
            raise http_error(on_trip)
        try:
            if body.decision not in ('WAIT', 'ABORT') and board._log is not None:
                async with gather._lock:
                    owner = await asyncio.to_thread(board._log.handoff.get, robot_id, body.stuck_id)
                    if owner is not None and owner['principal_id'] != principal.principal_id:
                        raise HTTPException(409, detail={'code': 'INCIDENT_ALREADY_CLAIMED',
                                                        'message': 'another named operator owns this incident'})
                    return await _forward_stuck_decision(robot_id, body, request, principal, client)
            return await _forward_stuck_decision(robot_id, body, request, principal, client)
        finally:
            runner = getattr(app.state, "trip_runner", None)
            if on_trip and body.decision in ("ABORT", "MANUAL") and runner is not None:
                await runner.cancel_robot(robot_id, f"operator_stuck_{body.decision.lower()}")

    async def _forward_stuck_decision(robot_id, body, request, principal, client) -> dict:
        resolver_loop = getattr(app.state, "stuck_resolver", None)
        if resolver_loop is not None:
            resolver_loop.claim(robot_id, body.stuck_id)
        record = partial(board.record, robot_id=robot_id, stuck_id=body.stuck_id,
                         decision=body.decision, principal_id=principal.principal_id, tier="human",
                         audit_id=getattr(request.state, "site_api_audit_id", None))
        try:
            result = await client.line_stuck_decision(body.stuck_id, body.decision)
        except RobotApiError as exc:
            record(accepted=False, code=exc.code, message=exc.message)
            raise HTTPException(status_code=409 if exc.status == 409 else 502, detail={
                "code": exc.code, "message": exc.message, "robot_id": robot_id, "robot_status": exc.status}) from exc
        except (httpx.HTTPError, OSError) as exc:
            code, message = transport_failure(exc)
            record(accepted=False if code == "ROBOT_UNREACHABLE" else None,
                   code=code, message=f"{message} ({type(exc).__name__})")
            raise HTTPException(status_code=502, detail={
                "code": code, "message": message, "robot_id": robot_id, "transport": type(exc).__name__}) from exc
        answer = record(accepted=True, outcome=result.get("outcome"))
        return {"robot_id": robot_id, "actor_id": principal.principal_id, "answer": answer, "result": result}

    async def claim_incident(robot_id, body, principal, *, admission=None) -> dict:
        """D-438 §1: a human opened this stuck; the resolver stops answering it."""
        if console.clients().get(robot_id) is None:
            raise http_error(HubError("UNKNOWN_ROBOT", robot_id))
        resolver_loop = getattr(app.state, "stuck_resolver", None)
        if body.judgment_revision is not None:
            require_named_operator(principal)
            if principal.principal_id == 'site-console':
                raise HTTPException(403, detail={'code': 'OPERATOR_IDENTITY_REQUIRED'})
            if board._log is None:
                raise HTTPException(503, detail={'code': 'INCIDENT_JOURNAL_UNAVAILABLE'})
            await gather()
            async with gather._lock:
                receipt = board.judgment_view(robot_id)
                if (not board.is_open(robot_id, body.stuck_id) or receipt is None
                        or judgment_revision(receipt) != body.judgment_revision):
                    raise HTTPException(409, detail={'code': 'INCIDENT_JUDGMENT_CHANGED'})
                board._handoff_pending.add((robot_id, body.stuck_id))
                if resolver_loop is not None:
                    resolver_loop.claim(robot_id, body.stuck_id)
                try:
                    claim = await asyncio.to_thread(board._log.handoff.claim,
                        robot_id, body.stuck_id, receipt, principal.principal_id, now=time.time(), admission=admission)
                except ValueError as exc:
                    raise HTTPException(409, detail={'code': str(exc)}) from exc
            return {'robot_id': robot_id, 'stuck_id': body.stuck_id,
                    'claimed_by': principal.principal_id, 'kind': 'incident_handoff', 'handoff': claim}
        if resolver_loop is not None:
            resolver_loop.claim(robot_id, body.stuck_id)
        return {"robot_id": robot_id, "stuck_id": body.stuck_id,
                "claimed_by": principal.principal_id, 'kind': 'resolver_pause'}

    app.state.claim_incident = claim_incident

    @app.post("/api/fleet/robots/{robot_id}/line-stuck/claim", dependencies=operator_guard, tags=["line-stuck"])
    async def line_stuck_claim(robot_id: str, body: LineStuckClaimRequest,
                               principal: SitePrincipal = Depends(require_operator)) -> dict:
        return await claim_incident(robot_id, body, principal)
