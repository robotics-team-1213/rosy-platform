"""Operator-pressed relocalization (3-model panel decision, 2026-11-14).

Three Fleet routes beside the D-395 service:

- ``POST /api/fleet/robots/{robot_id}/relocalize`` — a named operator's press. It records
  the request (audit like every operator action), allows the ladder's wheel-moving rungs
  for `service_logic.MOTION_ALLOW_S` (120 s), and starts the rotate rung now through the
  same mission path the ladder uses. Unattended wheel motion is out: a robot can sit on a
  charger or cables the platform cannot see. Refused off the roster, offline, on a
  trip/formation, or already LOCALIZED (its state comes back in the refusal).
- ``GET /api/fleet/robots/{robot_id}/localization`` — viewer pass-through of what Fleet
  already reads (the robot's localization status and candidate report) plus the motion
  gate, so the console can draw the candidates on the map.
- ``POST /api/fleet/robots/{robot_id}/localization/confirm`` — a named operator confirms
  one of the robot's *reported* candidates (index or exact pose; never a fabricated one).
  The decision goes out as source `human` through CORE's existing decision route, and the
  robot's 3 s InjectionCheck still has the last word.
"""

from __future__ import annotations

import asyncio
import math
from typing import Callable, Mapping, Optional

from fastapi import Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator

from core_common.protocol.localization import (LocState, LocalizationDecision, MapPose,
                                               DecisionSource)
from fleet.localization import trust
from fleet.swarm.transport import RobotApiError

#: One robot read (state, candidates, decision) is bounded like the service's own calls.
CALL_TIMEOUT_S = 2.5


class ConfirmRequest(BaseModel):
    """One of the robot's reported candidates: its index in the report, or the exact pose."""

    model_config = ConfigDict(extra="forbid")
    candidate_id: Optional[int] = Field(default=None, ge=0, le=7)
    x: Optional[float] = Field(default=None, allow_inf_nan=False)
    y: Optional[float] = Field(default=None, allow_inf_nan=False)
    yaw: Optional[float] = Field(default=None, allow_inf_nan=False)

    @model_validator(mode="after")
    def _index_or_pose(self) -> "ConfirmRequest":
        pose = [v for v in (self.x, self.y, self.yaw) if v is not None]
        if self.candidate_id is not None and pose:
            raise ValueError("candidate_id or x/y/yaw, not both")
        if self.candidate_id is None and len(pose) != 3:
            raise ValueError("either candidate_id or all of x, y, yaw")
        return self


def _match(report, body: ConfirmRequest) -> Optional[int]:
    """The reported candidate the operator picked, by index or exact pose; None otherwise."""
    if body.candidate_id is not None:
        return body.candidate_id if body.candidate_id < len(report.candidates) else None
    for i, c in enumerate(report.candidates):
        if all(math.isclose(getattr(c, k), getattr(body, k), rel_tol=0.0, abs_tol=1e-9)
               for k in ("x", "y", "yaw")):
            return i
    return None


def install_relocalize_routes(app, *, service, clients: Callable[[], Mapping],
                              read_state: Callable[[str], object],
                              require_named_operator, read_guard, record_event,
                              busy: Callable[[str], bool] = lambda robot_id: False) -> None:
    """`service` is the LocalizationService (None: this Fleet runs without it)."""

    def refuse(status: int, code: str, message: str, **extra) -> HTTPException:
        return HTTPException(status_code=status, detail={"code": code, "message": message, **extra})

    async def _state(robot_id: str) -> dict:
        try:
            return await asyncio.wait_for(read_state(robot_id), CALL_TIMEOUT_S)
        except Exception as exc:
            raise refuse(409, "ROBOT_OFFLINE",
                         f"the robot's state is unreadable ({type(exc).__name__})") from exc

    async def _candidates(robot_id: str):
        try:
            return await asyncio.wait_for(clients()[robot_id].localization_candidates(),
                                          CALL_TIMEOUT_S)
        except Exception:
            return None

    @app.post("/api/fleet/robots/{robot_id}/relocalize", tags=["fleet"])
    async def robot_relocalize(robot_id: str,
                               principal=Depends(require_named_operator)) -> dict:
        if service is None:
            raise refuse(503, "LOCALIZATION_DISABLED", "this Fleet runs without the localization service")
        if robot_id not in clients():
            raise refuse(404, "UNKNOWN_ROBOT", "robot is not on the roster")
        if busy(robot_id):
            raise refuse(409, "RELOCALIZE_TRIP_ACTIVE",
                         "the robot is on a trip or formation; stop it before relocalizing")
        state = await _state(robot_id)
        status = trust.status_of(state)
        if status is not None and status.state is LocState.LOCALIZED:
            raise refuse(409, "ALREADY_LOCALIZED", "the robot is already LOCALIZED",
                         localization=status.model_dump(mode="json"))
        view = service.allow_motion(robot_id, principal.principal_id)
        mission = await service.start_relocalize(robot_id, status)
        record_event("relocalize", principal.principal_id,
                     {"robot_id": robot_id, **view, "mission": mission})
        return {"robot_id": robot_id, "requested_by": principal.principal_id, **view,
                "mission": mission}

    @app.get("/api/fleet/robots/{robot_id}/localization", dependencies=read_guard, tags=["fleet"])
    async def robot_localization(robot_id: str) -> dict:
        if service is None:
            raise refuse(503, "LOCALIZATION_DISABLED", "this Fleet runs without the localization service")
        if robot_id not in clients():
            raise refuse(404, "UNKNOWN_ROBOT", "robot is not on the roster")
        try:
            state = await asyncio.wait_for(read_state(robot_id), CALL_TIMEOUT_S)
        except Exception:
            state = None
        status = trust.status_of(state)
        report = await _candidates(robot_id)
        return {"robot_id": robot_id,
                "localization": None if status is None else status.model_dump(mode="json"),
                "candidates": None if report is None else report.model_dump(mode="json"),
                "ladder": service.view(robot_id), **service.motion_view(robot_id)}

    @app.post("/api/fleet/robots/{robot_id}/localization/confirm", tags=["fleet"])
    async def robot_localization_confirm(robot_id: str, body: ConfirmRequest,
                                         principal=Depends(require_named_operator)) -> dict:
        if robot_id not in clients():
            raise refuse(404, "UNKNOWN_ROBOT", "robot is not on the roster")
        report = await _candidates(robot_id)
        if report is None or report.robot_id != robot_id:
            raise refuse(409, "NO_CANDIDATES", "the robot is not reporting candidates")
        index = _match(report, body)
        if index is None:
            raise refuse(404, "CANDIDATE_NOT_REPORTED",
                         "only a candidate the robot reported can be confirmed")
        candidate = report.candidates[index]
        decision = LocalizationDecision(
            request_id=report.request_id,
            pose=MapPose(x=candidate.x, y=candidate.y, yaw=candidate.yaw),
            source=DecisionSource.HUMAN, cues=[],
            evidence={"candidate_index": index, "scan_fit": candidate.scan_fit},
            ttl_s=5.0)
        try:
            answer = await asyncio.wait_for(clients()[robot_id].localization_decision(decision),
                                            CALL_TIMEOUT_S)
        except RobotApiError as exc:
            raise refuse(exc.status if 400 <= exc.status < 500 else 502, exc.code, exc.message,
                         robot_id=robot_id) from exc
        except Exception as exc:
            raise refuse(502, "DECISION_UNREACHABLE",
                         f"the decision did not reach the robot ({type(exc).__name__})") from exc
        record_event("localization_confirm", principal.principal_id, {
            "robot_id": robot_id, "request_id": report.request_id, "candidate_index": index,
            "x": candidate.x, "y": candidate.y, "yaw": candidate.yaw, "core": answer})
        return {"robot_id": robot_id, "candidate_index": index, "core": answer}
