"""When the arm cannot reach cargo on a docked vehicle, ask the vehicle to re-park closer and retry (2026-11-19 user:
"사람 없이 자동으로"). The cell's abort carries stage_result.reach_fix (arm-frame move that brings the object inside the
park reach); on_abort records one request per vehicle, the vehicle side reports the result through close(), and a DONE
close queues the same carry again (task_id "<root>-rp<attempt>"). After MAX_REPARK tries a person decides."""
from __future__ import annotations

import math
import uuid

from fastapi import HTTPException

MAX_REPARK = 2


class UnknownRequest(KeyError):
    """No repark request with that id (only this maps to 404; a failing retry enqueue must not)."""

ROOT_KEY = "repark_root"
CARRY_FIELDS = ("preset", "cell_id", "arm_id", "robot_id", "robot_kind", "src_site", "dst_site", "tier",
                "unload_batch_id", "unload_expected", "unload_index")


def _event(state, request, result, why, now) -> None:
    from fleet.server.sitemap import pipeline_auto_events

    row = {"kind": "auto_repark", "robot_id": request.get("robot_id"), "arm": request.get("arm_id"),
           "batch_id": request.get("request_id") or request.get("task_id"), "result": result, "why": why, "t": now}
    pipeline_auto_events.add(state, [row], "fleet")


def to_site(need, rules, cell_id):
    """Arm-frame move -> site frame: the cell geometry owner (fleet.pipeline.zone_geometry, feat/zone-geometry) when it
    is installed, else the rules' arm_to_site[cell].yaw_deg; None when neither knows the cell (never a guess)."""
    try:
        from fleet.pipeline.zone_geometry import arm_to_site
    except ImportError:
        arm_to_site = None
    if arm_to_site is not None:
        moved = arm_to_site(cell_id, float(need[0]), float(need[1]))
        return None if moved is None else [round(float(moved[0]), 4), round(float(moved[1]), 4)]
    arm_to_site = getattr(rules, "arm_to_site", None) if rules is not None else None
    yaw = arm_to_site.get(cell_id, {}).get("yaw_deg") if isinstance(arm_to_site, dict) else None
    if not isinstance(yaw, (int, float)) or isinstance(yaw, bool):
        return None
    c, s = math.cos(math.radians(yaw)), math.sin(math.radians(yaw))
    return [round(need[0] * c - need[1] * s, 4), round(need[0] * s + need[1] * c, 4)]


def on_abort(state, task: dict, stage_result: dict, now: float, rules=None) -> dict | None:
    """Open a repark request for an aborted carry that carries a reach_fix; None when it has none or the limit is spent."""
    fix = stage_result.get("reach_fix") if isinstance(stage_result, dict) else None
    need = fix.get("need_arm_dxdy_m") if isinstance(fix, dict) else None
    if not (isinstance(need, (list, tuple)) and len(need) == 2
            and all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in need)):
        return None
    requests = getattr(state, "repark_requests", None)
    if requests is None:
        requests = state.repark_requests = {}
    root = task.get(ROOT_KEY) or task["task_id"]
    done = getattr(state, "repark_done", None)
    if done is None:
        done = state.repark_done = []
    attempt = 1 + sum(1 for r in done if r.get("root") == root)
    base = {"task_id": task["task_id"], "cell_id": task.get("cell_id"), "arm_id": task.get("arm_id"),
            "robot_id": task.get("robot_id")}
    if attempt > MAX_REPARK:
        _event(state, base, "held", "REPARK_LIMIT", now)
        return None
    request = {"request_id": uuid.uuid4().hex[:12], **base, "need_arm_dxdy_m": [float(v) for v in need],
               "need_site_dxdy_m": to_site(need, rules, task.get("cell_id")), "attempt": attempt, "root": root,
               "state": "REQUESTED", "t": now}
    requests[task["robot_id"]] = request
    _event(state, request, "requested", f"attempt {attempt}", now)
    return request


def close(state, request_id: str, body: dict, enqueue, now: float) -> dict:
    """The vehicle side reports DONE or FAILED; DONE queues the retry, FAILED needs a person."""
    request = next((r for r in (getattr(state, "repark_requests", None) or {}).values()
                    if r.get("request_id") == request_id), None)
    if request is None:
        raise UnknownRequest(request_id)
    if request["state"] != "REQUESTED":
        raise ValueError(request["state"])
    new = body.get("state")
    if new not in ("DONE", "FAILED"):
        raise ValueError("state must be DONE or FAILED")
    request.update(state=new, closed_at=now, moved_robot_dxdy_m=body.get("moved_robot_dxdy_m"))
    if new == "FAILED":
        _event(state, request, "failed", str(body.get("reason") or body.get("why") or "REPARK_FAILED"), now)
        return request
    state.repark_done.append({"root": request["root"], "request_id": request_id})
    old = state.omx_cell_tasks[request["task_id"]]
    spec = {k: old[k] for k in CARRY_FIELDS if k in old}
    spec.update(task_id=f"{request['task_id']}-rp{request['attempt']}", **{ROOT_KEY: request["root"]})
    request["retry_task_id"] = enqueue(spec)["task_id"]
    _event(state, request, "done", f"retry {request['retry_task_id']}", now)
    return request


def install_repark_routes(app, ctx) -> None:
    import time

    app.state.repark_requests = getattr(app.state, "repark_requests", None) or {}
    app.state.repark_done = getattr(app.state, "repark_done", None) or []

    @app.post("/api/fleet/pipeline/repark/{request_id}", dependencies=ctx.operator_guard)
    async def close_repark(request_id: str, body: dict):
        enqueue = lambda spec: ctx._enqueue_one_task(ctx.active_map(), spec)  # noqa: E731
        try:
            request = close(app.state, request_id, body, enqueue, time.time())
        except UnknownRequest:
            raise HTTPException(404, detail={"code": "UNKNOWN_REPARK_REQUEST"}) from None
        except ValueError as exc:
            raise HTTPException(409, detail={"code": "REPARK_NOT_OPEN", "why": str(exc)}) from None
        ctx._save_ledger()
        return {"ok": True, "request": request}
