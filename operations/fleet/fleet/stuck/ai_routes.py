"""D-610 3·6·9: Fleet routes for AI-first — switch, open problems, cases, episodes, human-required classes.

- ``GET/POST /api/fleet/ai/first``: the console's AI-first switch (named operator; memory, a restart reads config).
- ``GET /api/fleet/ai/problems`` and ``GET /api/fleet/ai/case/{problem_id}``: what the AI PC judges (``ai_observer``
  reads). A case holds the problem, its context, this robot's last 10 minutes of episodes and two views (the robot
  front frame, held in memory like the D-577 8 picture, and the Rosy Cam view from ``rosy_cam`` when a provider
  is set). Pictures leave Fleet only in this response and are never written by Fleet.
- ``GET /api/fleet/ai/episodes``: the problem record as JSONL.
- ``GET/POST /api/fleet/ai/human-classes`` (add / reject: named operator) and ``DELETE .../{type_key}``
  (policy-admin only, reason required). The trend lists candidates; only a person changes the table.
"""

from __future__ import annotations

import asyncio
import base64
import json
from typing import Callable, Literal, Optional

from fastapi import Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field

from fleet.stuck.closed_loop import context

KEY = r"^[a-z_]+:[A-Za-z0-9_]+:[a-z_]+$"


class AiFirstSwitch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool


class HumanClassChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type_key: str = Field(pattern=KEY, max_length=96)
    action: Literal["add", "reject"]
    reason: str = Field(min_length=1, max_length=200)


def rosy_cam_lease(robot_id: str, sightings, map_pose, signer, sources: tuple[str, ...]) -> Optional[dict]:
    """Give the AI PC a direct crop at a fresh accepted sighting, including during pose loss."""
    if sightings is None or signer is None:
        return None
    row = next((row for row in sightings.snapshot()["sightings"]
                if row.get("robot_id") == robot_id and not row.get("stale")
                and row.get("source_id") in sources and row.get("map_id") == map_pose.active_map_id()), None)
    if row is None:
        return None
    try:
        lease = signer.issue(principal_id="ai-case", source_id=row["source_id"], ttl_s=10,
                             rectification={"mode": "map"}, crop_map=(row["x"], row["y"], 1.0),
                             crop_map_id=row["map_id"], crop_revision=row["calibration_revision"])
    except (ValueError, KeyError):
        return None
    return {"frame_path": f"/api/vision/sources/{row['source_id']}/frame", "lease": lease}


def install_ai_first_routes(app, *, first, line_stuck, loop, episodes, read_guard, authorize,
                            require_named_operator, clients: Callable[[], dict],
                            rosy_cam: Optional[Callable[[str], Optional[dict]]] = None,
                            pose: Callable[[str], Optional[dict]] = lambda _rid: None,
                            deadlock_case: Callable[[], Optional[dict]] = lambda: None) -> None:
    @app.get("/api/fleet/ai/first", dependencies=read_guard, tags=["ai"])
    def ai_first_view() -> dict:
        return first.view()

    @app.post("/api/fleet/ai/first", tags=["ai"])
    def ai_first_switch(body: AiFirstSwitch, principal=Depends(require_named_operator)) -> dict:
        first.enabled = body.enabled              # the resolver reads it on its next pass
        return {**first.view(), "changed_by": principal.principal_id}

    def _problems() -> list[dict]:
        out = [{"problem_id": row["stuck_id"], "kind": "stuck", "robot_id": row["robot_id"]}
               for row in line_stuck.pending() if first.on(row["robot_id"]) and row.get("stuck_id")]
        if loop is not None and loop.problems is not None:
            out += [{"problem_id": p["problem_id"], "kind": p["kind"], "robot_id": p["robot_id"]}
                    for p in loop.problems.open.values()]
        deadlock = deadlock_case()
        if deadlock is not None:
            out.append(deadlock)
        return out

    async def _views(rid: str, stuck_id: Optional[str] = None) -> dict:
        front = None
        fetch = getattr(clients().get(rid), "front_frame", None)
        try:
            jpeg, status = await asyncio.wait_for(fetch(), timeout=3.0)
            if jpeg is not None:
                if stuck_id and line_stuck.preview(rid, stuck_id) is None:
                    line_stuck.keep_preview(rid, stuck_id, jpeg, status)
                age = (status.get("age_ms") or 0) / 1000.0
                front = {"frame_id": f"{status.get('source')}:{status.get('sequence')}",
                         "captured_at": round(first.wall() - age, 3), "jpeg_b64": base64.b64encode(jpeg).decode("ascii")}
        except Exception:  # noqa: BLE001 - unavailable fresh evidence means no VLM judgement
            pass
        views = {"front": front, "rosy_cam": None if rosy_cam is None else rosy_cam(rid)}
        return {name: view for name, view in views.items() if view is not None}

    @app.get("/api/fleet/ai/problems", dependencies=read_guard, tags=["ai"])
    def ai_problems() -> dict:
        return {"problems": _problems(), "ai_first": first.view()}

    @app.get("/api/fleet/ai/case/{problem_id}", dependencies=read_guard, tags=["ai"])
    async def ai_case(problem_id: str, principal=Depends(authorize)) -> dict:
        if principal.role != "ai_observer":
            raise HTTPException(status_code=403, detail={"code": "AI_CASE_FORBIDDEN"})
        problem = next((p for p in _problems() if p["problem_id"] == problem_id), None)
        if problem is None:
            raise HTTPException(status_code=404, detail={"code": "AI_CASE_NOT_OPEN", "message": problem_id})
        rid = problem["robot_id"]
        rows = loop._rows if loop is not None else {}
        row = rows.get(rid) or {"robot_id": rid, "map_pose": pose(rid)}
        stuck_id = problem_id if problem["kind"] == "stuck" else None
        if problem["kind"] == "deadlock":
            ids = problem["context"]["cycle"]
            views = await asyncio.gather(*(_views(mid) for mid in ids))
            return {**problem, "built_at": first.wall(),
                    "members": {mid: {"context": context(rows.get(mid) or {"map_pose": pose(mid)}), "views": view}
                                for mid, view in zip(ids, views)}}
        views = await _views(rid, stuck_id)
        wall = first.wall()
        history = [] if episodes is None else await asyncio.to_thread(
            episodes.episodes, 20, rid, wall - 600.0)
        return {**problem, "stuck_id": stuck_id, "context": context(row), "built_at": wall,
                "history": [{k: h.get(k) for k in ("opened_at", "problem_id", "kind", "decision", "tier", "verdict",
                                                   "core_code", "outcome")} for h in history],
                "views": views}

    @app.get("/api/fleet/ai/episodes", dependencies=read_guard, tags=["ai"])
    def ai_episodes(limit: int = Query(500, ge=1, le=5000), robot_id: Optional[str] = None) -> Response:
        rows = [] if episodes is None else episodes.episodes(limit, robot_id)
        return Response("".join(json.dumps(row, default=str) + "\n" for row in rows),
                        media_type="application/x-ndjson")

    @app.get("/api/fleet/ai/human-classes", dependencies=read_guard, tags=["ai"])
    def human_classes() -> dict:
        if episodes is None:
            return {"active": [], "changes": [], "trend": []}
        return {"active": sorted(episodes.active()), "changes": episodes.classes(), "trend": episodes.trend()}

    @app.post("/api/fleet/ai/human-classes", tags=["ai"])
    def human_class_change(body: HumanClassChange, principal=Depends(require_named_operator)) -> dict:
        if episodes is None:
            raise HTTPException(status_code=409, detail={"code": "AI_EPISODES_OFF", "message": "no --tasks-db"})
        stats = next((t for t in episodes.trend() if t["type_key"] == body.type_key), None)
        episodes.change(body.type_key, body.action, principal.principal_id, body.reason, stats)
        return {"active": sorted(episodes.active())}

    @app.delete("/api/fleet/ai/human-classes/{type_key}", tags=["ai"])
    def human_class_remove(type_key: str, reason: str = Query(min_length=1, max_length=200),
                           principal=Depends(authorize)) -> dict:
        if principal.role != "policy-admin":
            raise HTTPException(status_code=403, detail={"code": "FORBIDDEN", "message": "policy-admin only"})
        if episodes is None or type_key not in episodes.active():
            raise HTTPException(status_code=404, detail={"code": "AI_HUMAN_CLASS_NOT_ACTIVE", "message": type_key})
        episodes.change(type_key, "remove", principal.principal_id, reason, None)
        return {"active": sorted(episodes.active())}
