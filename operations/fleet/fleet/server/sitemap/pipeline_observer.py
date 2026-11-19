"""The vehicle waiting at the wait station looks at the unloading vehicle's cargo bay (2026-11-19).

The vehicle parked at the wait place (any heading) is the observer. It does not face the bay, so it turns IN PLACE
(CORE D-603 rotate_to through the same robot client make_capture uses) toward the bay, takes one front frame and
turns back. The turn sweeps near the arm reach, so it only starts while the unload cell's arm is folded and fresh.
A verdict only ever raises the layer count (task["tier_hint"]); an abstain, a missing mapping, no vehicle, an arm
that is not folded, a failed turn, a timeout or a person skips the look and the unload goes on with the other signals.
The mapping {unload_place: wait_place} comes from the site rules (observe_from) or app.state.observe_from.
step() is one tick; capture and judge are injected. Fleet decodes no image (D-136 3): the tier judge belongs to Vision
(rosy_vision.stack_tiers), and until one is installed as app.state.observer_judge every look is SKIPPED NO_JUDGE
before any turn."""
from __future__ import annotations

import inspect
import math
import uuid

from fastapi import HTTPException, Request

TOTAL_CAP_S = 60.0
POSE_TOL_M = 0.05
BAY_OFFSET_M = 0.11
NO_TURN_DEG = 25.0
ROTATE_TOL_DEG = 3.0
ROTATE_TIMEOUT_S = 20.0
ROTATE_POLL_S = 0.4
ARM_FRESH_S = 60.0
OPERATOR = "fleet-observer"
DEFAULT_UNLOAD_PLACE = "S3"
TERMINAL = ("VERDICT", "SKIPPED")
MAX_REQUESTS = 50


def _num(value):
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) else None


def _pose(row) -> tuple[float, float, float] | None:
    pose = (row.get("state") or {}).get("pose") or {}
    x, y, yaw = (_num(pose.get(k)) for k in ("x", "y", "yaw"))
    return None if x is None or y is None else (x, y, yaw or 0.0)


def place_pose(site, name: str) -> tuple[float, float, float] | None:
    """(x, y, yaw) of the active site map place, else None (never a guess)."""
    place = next((p for p in getattr(site, "places", ()) if p.id == name), None)
    return None if place is None else (float(place.x), float(place.y), float(getattr(place, "yaw", 0.0) or 0.0))


def wrap_deg(a: float) -> float:
    return (a + 180.0) % 360.0 - 180.0


def edge_into(site, place_id: str):
    """The site-map edge that ends at the place, else None."""
    return next((e for e in getattr(site, "edges", ()) if getattr(e, "to", None) == place_id), None)


def bay_point(site, unload_place, edge_into_unload, offset_m=BAY_OFFSET_M, unload_pose=None):
    """(x, y) of the unloading vehicle's cargo bay: its live pose (x, y, yaw), else the unload place, minus
    offset_m along its heading (the last segment of the edge into the place). None when nothing is known."""
    if unload_pose is not None:
        x, y, yaw = unload_pose
        return (x - offset_m * math.cos(yaw), y - offset_m * math.sin(yaw))
    place = place_pose(site, unload_place)
    pts = list(getattr(edge_into_unload, "polyline", None) or ())
    segs = [(a, b) for a, b in zip(pts, pts[1:]) if math.dist(a, b) > 1e-9]
    if place is None or not segs:
        return None
    (ax, ay), (bx, by) = segs[-1]
    n = math.hypot(bx - ax, by - ay)
    return (place[0] - offset_m * (bx - ax) / n, place[1] - offset_m * (by - ay) / n)


def look_delta_deg(observer_pose, bay) -> float:
    return wrap_deg(math.degrees(math.atan2(bay[1] - observer_pose[1], bay[0] - observer_pose[0]) - observer_pose[2]))


def observer_for(robots, site, unload_place, wait_place, unload_robot=None) -> str | None:
    """The online robot parked at wait_place (0.05 m, any heading), else None."""
    target = place_pose(site, wait_place)
    if target is None:
        return None
    for row in robots:
        pose = _pose(row)
        if (row.get("robot_id") != unload_robot and row.get("online") and pose is not None
                and math.hypot(pose[0] - target[0], pose[1] - target[1]) <= POSE_TOL_M):
            return row["robot_id"]
    return None


def observe_map(app, rules=None) -> dict:
    """{unload_place: wait_place} from the site rules' observe_from, else app.state.observe_from, else empty."""
    found = getattr(rules, "observe_from", None) or getattr(app.state, "observe_from", None)
    return dict(found) if isinstance(found, dict) else {}


def _event(state, request, result, why, now) -> None:
    from fleet.server.sitemap import pipeline_auto_events

    turned = f" delta={request.get('delta_deg')} yaw={request.get('yaw_before')}->{request.get('yaw_after')}" \
             f" turn={request.get('turn')}/{request.get('turn_back')}"  # clean() keeps only known event fields
    pipeline_auto_events.add(state, [{"kind": "auto_observe", "robot_id": request.get("observer_id"),
                                      "batch_id": request["request_id"], "result": result, "why": why + turned, "t": now}], "fleet")


def _skip(state, request, why, now) -> None:
    request.update(state="SKIPPED", why=why, t=now)
    _event(state, request, "SKIPPED", why, now)


async def step(state, request, *, console, capture, judge, now, site=None, human=False, rows=None) -> dict:
    """Advance one request (the whole look runs inside one tick). `human` is a bool or a callable re-asked
    during the turn. `rows` defaults to console.snapshot()['robots']; returns the request."""
    if request["state"] in TERMINAL:
        return request
    if request.get("cancelled"):
        _skip(state, request, "CANCELLED", now)
    elif human() if callable(human) else human:
        _skip(state, request, "HUMAN_HOLD", now)
    elif now - request["started_at"] > TOTAL_CAP_S:
        _skip(state, request, "TIMEOUT", now)
    else:
        await _look(state, request, console, capture, judge, now, site, rows, human)
    return request


def arm_folded(state, arm_id, now) -> bool:
    live = (getattr(state, "arm_live_states", None) or {}).get(arm_id) or {}
    updated = _num(live.get("updated_at"))
    return live.get("folded") is True and updated is not None and 0 <= now - updated <= ARM_FRESH_S


async def rotate(client, delta_deg: float, is_human) -> str:
    """One CORE rotate_to turn: 'done', 'HUMAN_HOLD', 'ROTATE_TIMEOUT' or 'ROTATE_FAILED'. The start goes through the
    client's own POST (same transport and auth as every robot call; the client's rotate_to() has no tol_deg)."""
    import asyncio
    import time

    try:
        if is_human():
            return "HUMAN_HOLD"
        await client._post("/api/v1/motion/rotate_to", {"delta_deg": round(delta_deg, 1), "tol_deg": ROTATE_TOL_DEG,
                                                        "operator_name": OPERATOR})
        end = time.monotonic() + ROTATE_TIMEOUT_S
        while True:
            state = (await client.rotate_to_status()).get("state")
            if state == "done":
                return "done"
            if state in ("aborted", "idle"):
                return "ROTATE_FAILED"
            held = is_human()
            if held or time.monotonic() >= end:
                await client.rotate_to_stop()
                return "HUMAN_HOLD" if held else "ROTATE_TIMEOUT"
            await asyncio.sleep(ROTATE_POLL_S)
    except Exception:
        return "ROTATE_FAILED"


def _unload_pose(rows, robot_id):
    for row in rows:
        pose = (row.get("state") or {}).get("pose") or {}
        if row.get("robot_id") == robot_id and _pose(row) is not None and _num(pose.get("yaw")) is not None:
            return _pose(row)
    return None


async def _look(state, request, console, capture, judge, now, site, rows, human=False) -> None:
    if judge is None:
        return _skip(state, request, "NO_JUDGE", now)
    wait_place = request.get("wait_place")
    if not wait_place:
        return _skip(state, request, "NO_OBSERVE_PLACE", now)
    if rows is None:
        rows = (await console.snapshot()).get("robots", [])
    observer = observer_for(rows, site, request["unload_place"], wait_place, request.get("unload_robot"))
    if observer is None:
        return _skip(state, request, "NO_QUEUED_OBSERVER", now)
    me = next(_pose(r) for r in rows if r.get("robot_id") == observer)
    request["observer_id"] = observer
    request["yaw_before"] = round(math.degrees(me[2]), 1)
    unloader = _unload_pose(rows, request.get("unload_robot"))
    bay = bay_point(site, request["unload_place"], edge_into(site, request["unload_place"]), unload_pose=unloader)
    if bay is None:
        return _skip(state, request, "NO_BAY_POINT", now)
    delta = look_delta_deg(me, bay)
    request["delta_deg"] = round(delta, 1)
    request["dist_m"] = round(math.hypot(bay[0] - me[0], bay[1] - me[1]), 3)
    is_human = human if callable(human) else (lambda: bool(human))
    client = None
    if abs(delta) > NO_TURN_DEG:
        task = state.omx_cell_tasks.get(request["cell_task_id"]) or {}
        if not arm_folded(state, task.get("arm_id"), now):
            return _skip(state, request, "ARM_NOT_FOLDED", now)
        client = console.clients().get(observer)
        if client is None:
            return _skip(state, request, "NO_CLIENT", now)
    why, out = None, None
    if client is not None:
        request["turn"] = await rotate(client, delta, is_human)
        if request["turn"] != "done":
            why = request["turn"]
    if why is None:
        try:
            frame = await capture(observer)
            out = judge(frame, request.get("dist_m"))
            out = await out if inspect.isawaitable(out) else out
        except Exception as exc:
            why = f"CAPTURE_FAILED:{type(exc).__name__}"
    if client is not None and why != "HUMAN_HOLD":  # always turn back; a person present stops it instead
        request["turn_back"] = await rotate(client, -delta, is_human)
        why = "HUMAN_HOLD" if request["turn_back"] == "HUMAN_HOLD" else why
    if client is not None:
        try:
            moved = _pose(next(r for r in (await console.snapshot()).get("robots", []) if r.get("robot_id") == observer))
            request["yaw_after"] = round(math.degrees(moved[2]), 1)
        except Exception:
            pass
    if why is not None:
        return _skip(state, request, why, now)
    tiers = out.get("tiers") if isinstance(out, dict) else None
    confidence = _num(out.get("confidence")) if isinstance(out, dict) else None
    request.update(state="VERDICT", verdict=tiers, why="OK" if tiers else "ABSTAIN", t=now, confidence=confidence)
    task = state.omx_cell_tasks.get(request["cell_task_id"])
    if type(tiers) is int and tiers >= 1 and task is not None:
        task["tier_hint"] = {"layers_below": tiers - 1, "source": "observer", "confidence": confidence, "t": now}
    _event(state, request, "VERDICT" if tiers else "ABSTAIN", f"tiers={tiers}", now)


def new_request(state, cell_task_id, unload_place, wait_place, now, *, unload_robot=None) -> dict:
    requests = state.observer_requests
    request = {"request_id": uuid.uuid4().hex[:12], "cell_task_id": cell_task_id, "unload_place": unload_place,
               "wait_place": wait_place, "observer_id": None, "state": "REQUESTED", "verdict": None, "why": None,
               "t": now, "started_at": now, "unload_robot": unload_robot, "dist_m": None, "delta_deg": None,
               "yaw_before": None, "yaw_after": None, "turn": None, "turn_back": None}
    requests[request["request_id"]] = request
    for old in list(requests)[:-MAX_REQUESTS]:
        requests.pop(old)
    return request


def make_capture(console):
    """Real capture: the observer's CORE front frame (swarm.transport_helpers.fetch_front_frame)."""
    async def capture(robot_id: str) -> bytes:
        client = console.clients().get(robot_id)
        if client is None:
            raise RuntimeError("no client")
        try:
            return (await client.front_frame(overlay=False))[0]  # the raw frame: an overlay would colour the stack
        except Exception:
            return (await client.front_frame())[0]
    return capture


def install_observer_routes(app, ctx) -> None:
    import asyncio
    import logging
    import time

    log = logging.getLogger(__name__)
    app.state.observer_requests = getattr(app.state, "observer_requests", None) or {}
    rules = lambda: ctx.rules() if callable(getattr(ctx, "rules", None)) else None  # noqa: E731

    def human() -> bool:
        return bool(ctx._is_human_detected()) or any(
            s.get("phase") == "HUMAN_HOLD" for s in app.state.omx_cell_states.values())

    def get(request_id):
        request = app.state.observer_requests.get(request_id)
        if request is None:
            raise HTTPException(404, detail={"code": "UNKNOWN_OBSERVER_REQUEST"})
        return request

    @app.post("/api/fleet/pipeline/observer-requests", dependencies=ctx.operator_guard)
    async def create(request: Request):
        body = await request.json()
        task = app.state.omx_cell_tasks.get(str(body.get("cell_task_id")))
        if task is None:
            raise HTTPException(404, detail={"code": "UNKNOWN_CELL_TASK"})
        if human():
            raise HTTPException(409, detail={"code": "HUMAN_HOLD_ACTIVE"})
        unload = str(body.get("unload_place") or DEFAULT_UNLOAD_PLACE)
        row = new_request(app.state, task["task_id"], unload, observe_map(app, rules()).get(unload), time.time(),
                          unload_robot=task.get("robot_id"))
        return {"ok": True, "request": row}

    @app.get("/api/fleet/pipeline/observer-requests/{request_id}", dependencies=ctx.read_guard)
    async def read(request_id: str):
        return get(request_id)

    @app.post("/api/fleet/pipeline/observer-requests/{request_id}/cancel", dependencies=ctx.operator_guard)
    async def cancel(request_id: str):
        request = get(request_id)
        if request["state"] in TERMINAL:
            raise HTTPException(409, detail={"code": "OBSERVER_REQUEST_CLOSED", "state": request["state"]})
        request["cancelled"] = True
        return {"ok": True, "request": request}

    async def tick() -> None:
        capture = getattr(app.state, "observer_capture", None) or make_capture(ctx.console)
        judge = getattr(app.state, "observer_judge", None)
        site = ctx.active_map()[1]
        for request in list(app.state.observer_requests.values()):
            if request["state"] in TERMINAL:
                continue
            await step(app.state, request, console=ctx.console, capture=capture, judge=judge, now=time.time(),
                       site=site, human=human)
            ctx._save_ledger()

    app.state.observer_tick = tick
    if getattr(ctx, "console", None) is None:
        return
    inner = app.router.lifespan_context

    async def run():
        while True:
            try:
                await tick()
            except Exception:  # one bad pass must not end the observation loop
                log.exception("observer tick failed")
            await asyncio.sleep(1.0)

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def lifespan(application):
        async with inner(application) as value:
            task = asyncio.create_task(run())
            try:
                yield value
            finally:
                task.cancel()

    app.router.lifespan_context = lifespan
