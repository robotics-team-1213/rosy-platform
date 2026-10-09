"""D-517 2/3: repeat-trip lap bookkeeping, pure on ``LiveTrip`` and plans (no robot calls)."""
import heapq

from fleet.routing.cost import transition_cost, turn_deg
from fleet.routing.execute import arc_id, ends_at_place, plan_again, plan_body, route_key, unsupported
from fleet.routing.trip import _assemble
from fleet.server.trip_ports import LiveTrip, TripError
from fleet.traffic.zone_hold import hold_back_m

#: D-517 2/5: a failed lap check is retried this often, this many times (D-438), then it is the operator's.
LAP_RETRY_S = 5.0
LAP_RETRIES = 2


def convoy_refusal(lives: dict, robot_id: str, leader: str, *, cycle=None, arcs=None, segments=None) -> tuple | None:
    """D-517 9 M3: ``(code, detail)`` when ``robot_id`` may not follow ``leader``, else None. The leader
    runs an open repeat trip, follows nobody, and laps the same cycle (``cycle`` places or ``arcs`` edges);
    the follower's plan ``segments`` reach the leader's lane position over that loop only, so no shortcut
    (a roundabout arc) puts it ahead of the leader."""
    live = lives.get(leader)
    if leader == robot_id:
        return "TRIP_CONVOY_SELF", {"leader": leader}
    if live is None or not live.open or not live.repeat:
        return "TRIP_CONVOY_LEADER_NOT_RUNNING", {"leader": leader}
    if live.convoy is not None:
        return "TRIP_CONVOY_LEADER_IS_FOLLOWER", {"leader": leader, "follows": live.convoy}
    edges = lambda ids: frozenset(arc.rsplit(":", 1)[0] for arc in ids)  # noqa: E731
    own = live.request.get("cycle") or [live.request["to"], *live.request.get("via", ())]
    if (cycle is not None and cycle != frozenset(own)) or (
            arcs is not None and edges(arcs) != edges(live.lap_arcs)):
        return "TRIP_CONVOY_OTHER_LOOP", {"leader": leader}
    if segments is not None and not _behind(live, segments, edges(live.lap_arcs)):
        return "TRIP_CONVOY_NOT_BEHIND", {"leader": leader}
    return None


def _behind(leader: LiveTrip, segments: list, loop: frozenset) -> bool:
    if leader.at is None:
        return False
    index, s = leader.at
    target = arc_id(leader.segments[index])
    for k, seg in enumerate(segments):
        if seg["edge_id"] not in loop:
            return False
        if arc_id(seg) == target:
            return k > 0 or seg["s_from"] < s
    return False


def lap_arcs(active, segments: list, request: dict, caps: dict, blocked, routing, max_turn_deg) -> tuple[str, ...]:
    """D-517 3: one lap's arcs planned from where ``segments`` end (else the plan's own: the lap check holds)."""
    if not segments:
        return ()
    end = active[2].arcs[arc_id(segments[-1])].point_at(segments[-1]["s_to"])
    body, _hold = plan_again(active, end, request, caps, blocked, set(), routing, max_turn_deg)
    return tuple(arc_id(seg) for seg in (body or {"segments": segments})["segments"])


def tail(graph, segments: list):
    """The last segment that ends at a place (where a lap holds), or None."""
    return next((seg for seg in reversed(segments) if ends_at_place(graph, seg)), None)


def lap_end_out_of_zones(active, plan: dict, request: dict, caps: dict, blocked, routing, max_turn_deg,
                         traffic) -> tuple[dict, dict, list] | None:
    """D-517 3 (2026-10-09 signal SIM): a lap holds at its last place, so that place must be one a robot
    can stand at outside every zone (``hold_back_m(traffic, segment)`` is not None). Else the lap end moves on along
    the next lap to the first place that is; an old end place becomes the cycle's last via (a coordinate end
    lies on the lap's own lanes and is dropped). ``(plan, request, lap route)``, unchanged when nothing moves;
    None when no place of the next lap will do."""
    graph = active[2]
    last = tail(graph, plan["segments"])
    if last is None or hold_back_m(traffic, last) is not None:
        return plan, request, route_key(plan["segments"])
    to, via = request["to"], list(request.get("via", ()))
    end = graph.arcs[arc_id(plan["segments"][-1])].point_at(plan["segments"][-1]["s_to"])
    lap, _hold = plan_again(active, end, request, caps, blocked, set(), routing, max_turn_deg)
    k = next((k for k, seg in enumerate((lap or {}).get("segments", ()))
              if ends_at_place(graph, seg) and hold_back_m(traffic, seg) is not None), None)
    if k is None:
        return None
    joined = _joined(plan["segments"], [seg for seg in lap["segments"][:k + 1] if seg["s_to"] - seg["s_from"] > 1e-6])
    plan = _extended(graph, plan, joined, routing)
    moved = {**request, "to": ends_at_place(graph, lap["segments"][k])}
    if isinstance(to, str):
        moved.update(via=[*via, to], cycle=request.get("cycle") or [to, *via])  # the operator's cycle (convoy check)
    # Lap 1 runs start -> moved end; the next laps run moved end -> moved end over the same edges.
    nxt, _hold = plan_again(active, graph.arcs[arc_id(joined[-1])].point_at(joined[-1]["s_to"]), moved, caps,
                            blocked, set(), routing, max_turn_deg)
    same = nxt is not None and {s["edge_id"] for s in nxt["segments"]} == {s["edge_id"] for s in joined}
    return plan, moved, route_key(nxt["segments"] if same else joined)


def _extended(graph, plan: dict, segments: list, routing) -> dict:
    """``plan`` with ``segments`` (its own and more), places and actions built again."""
    ends = [graph.arcs[arc_id(s)].length_m if ends_at_place(graph, s) else s["s_to"] for s in segments]  # 4-decimal s
    body = plan_body(_assemble(graph, [(arc_id(s), s["s_from"], e) for s, e in zip(segments, ends)], 0.0, routing))
    return {**plan, **{key: body[key] for key in ("segments", "places", "actions")}}


def _onward(graph, segments: list, caps: dict, blocked, routing, ok) -> tuple[str, ...] | None:
    """Whole arcs on from the end of ``segments`` (shortest first, only arcs the robot may drive) to the nearest
    one ``ok`` accepts; None when there is none."""
    succ = graph.successors(routing, lambda arc, nxt, kind: transition_cost(
        turn_deg(arc.end_tangent, nxt.start_tangent), kind, routing))
    modes = frozenset(caps.get("modes") or ("lane", "free"))
    heap, seen = [(0.0, arc_id(segments[-1]), ())], set()
    while heap:
        dist, here, path = heapq.heappop(heap)
        if here in seen:
            continue
        seen.add(here)
        arc = graph.arcs[here]
        if path and ok({"edge_id": arc.edge_id, "forward": arc.forward, "s_from": 0.0, "s_to": arc.length_m}):
            return path
        for nxt_id, _step in succ.get(here, ()):
            nxt = graph.arcs[nxt_id]
            if nxt_id not in seen and nxt.edge_id not in blocked and nxt.drive_mode in modes and (
                    nxt.robot_kinds is None or caps.get("kind") in nxt.robot_kinds):
                heapq.heappush(heap, (dist + nxt.length_m, nxt_id, (*path, nxt_id)))
    return None


def stop_points(active, plan: dict, request: dict, caps: dict, blocked, routing, max_turn_deg,
                traffic) -> tuple[dict, dict, list, tuple[str, ...], dict | None]:
    """D-517 3 (2026-10-09 signal SIM): no trip stops inside a site zone. A repeat trip's lap end moves on
    to a place it can hold clear of zones (``lap_end_out_of_zones``); a one-way trip's destination moves on
    along the lanes to the nearest such place (2026-10-09 user decision "다음 지점까지 가서 섬"). Only when
    there is none: ``TRIP_STOP_IN_ZONE``. ``(plan, request, lap route, lap arcs, stop_moved {from, to} or None)``."""
    graph, to = active[2], request["to"]
    refused = TripError(422, "TRIP_STOP_IN_ZONE", {"place": to if isinstance(to, str) else None,
                                                   "repeat": bool(request.get("repeat"))})
    if request.get("repeat"):
        moved = lap_end_out_of_zones(active, plan, request, caps, blocked, routing, max_turn_deg, traffic)
        if moved is None:
            raise refused
        plan, request, lap_route = moved
        arcs = lap_arcs(active, plan["segments"], request, caps, blocked, routing, max_turn_deg)
    else:
        def ok(seg: dict) -> bool:  # stands at the place, or (lane) holds short of it clear of every zone
            back = hold_back_m(traffic, seg)
            return back == 0.0 or (back is not None and graph.arcs[arc_id(seg)].drive_mode == "lane")

        if plan["segments"] and not ok(plan["segments"][-1]):
            more = _onward(graph, plan["segments"], caps, blocked, routing, ok)
            if more is None:
                raise refused
            arcs = [graph.arcs[a] for a in more]
            more = [{"edge_id": a.edge_id, "forward": a.forward, "s_from": 0.0, "s_to": a.length_m} for a in arcs]
            end = {**plan["segments"][-1], "s_to": graph.arcs[arc_id(plan["segments"][-1])].length_m}  # on to its place
            plan = _extended(graph, plan, [*plan["segments"][:-1], end, *more], routing)
            if unsupported(graph, plan["segments"], kind=caps.get("kind"), modes=frozenset(caps.get("modes") or ()),
                           junction_turn=bool(caps.get("junction_turn")), config=routing, max_turn_deg=max_turn_deg):
                raise refused
            via = list(request.get("via", ()))  # a replan still passes the old destination
            request = {**request, "to": arcs[-1].end_place, "via": [*via, to] if isinstance(to, str) else via}
        lap_route, arcs = route_key(plan["segments"]), ()
    stop_moved = None if request["to"] == to else {"from": to if isinstance(to, str) else None, "to": request["to"]}
    return plan, request, lap_route, arcs, stop_moved


def next_lap(active, end, request: dict, caps: dict, blocked, routing, max_turn_deg,
             traffic) -> tuple[dict | None, dict | None]:
    """D-517 2 ``plan_again`` for the next lap; D-517 3: one whose last place cannot be held outside every
    zone is a failed lap check (``TRIP_STOP_IN_ZONE``), held at this lap's end."""
    body, hold = plan_again(active, end, request, caps, blocked, set(), routing, max_turn_deg)
    last = tail(active[2], body["segments"]) if body is not None else None
    if last is None or hold_back_m(traffic, last) is not None:
        return body, hold
    return None, {"reason": "replan", "plan": None, "code": "TRIP_STOP_IN_ZONE",
                  "detail": {"place": ends_at_place(active[2], last)}}


def lap_due(live: LiveTrip, index: int, remaining: float, config) -> bool:
    """At the lap's last place (within ``arm_distance_m``, before its action goes out) or past it."""
    tail = max((i for i in range(len(live.segments)) if live.place(i)), default=None)
    return tail is not None and (index > tail or (index == tail and remaining <= config.arm_distance_m))


def lap_retry_due(live: LiveTrip, now: float) -> bool:
    hold = live.view["hold"]
    return (hold is not None and hold.get("reason") == "lap" and hold.get("plan") is None
            and live.lap_tries <= LAP_RETRIES and now - live.lap_tried_at >= LAP_RETRY_S)


def carry_on(live: LiveTrip, index: int, segments: list, body: dict | None, hold: dict | None, now: float) -> None:
    """The same route carries on without a stop; a failed check or another route holds at the last place."""
    if body is not None:
        plan = {"segments": _joined(segments, body["segments"]),
                "places": [*live.view["plan"]["places"], *body["places"]],
                "actions": [*live.view["plan"]["actions"][:-1], *body["actions"]]}
        if route_key(body["segments"]) == live.lap_route:
            live.lap_tries = 0
            live.lap_arcs = tuple(arc_id(seg) for seg in body["segments"])
            # Keep this lap and the next one: earlier laps are dropped so the plan stays bounded.
            cut, live.lap_start = live.lap_start, len(plan["segments"]) - len(body["segments"]) - live.lap_start
            live.view.update(plan=_from(live.graph, plan, cut), lap=live.view["lap"] + 1)
            live.bends_done.clear()  # D-507 addendum: the new lap drives its bends again
            if cut:
                _dropped(live, segments[:cut])
            return
        hold = {"map_version": body["map_version"], "lap_route": route_key(body["segments"]),
                "plan": _from(live.graph, plan, index),
                "length_m": body["length_m"], "eta_s": body["eta_s"]}
    if hold.get("plan") is None:
        live.lap_tries, live.lap_tried_at = live.lap_tries + 1, now
    live.view["hold"] = {**hold, "reason": "lap"}


def _from(graph, plan: dict, k: int) -> dict:
    """``plan`` from segment ``k`` on, without the places (and their actions) of the segments before it."""
    n = sum(1 for seg in plan["segments"][:k] if ends_at_place(graph, seg))
    return {**plan, "segments": plan["segments"][k:], "places": plan["places"][n:], "actions": plan["actions"][n:]}


def _dropped(live: LiveTrip, dropped: list) -> None:
    """Every index and plan metre the trip keeps moves with the segments dropped from its front."""
    cut = len(dropped)
    live.view["segment_index"] -= cut
    live.at = None if live.at is None else (live.at[0] - cut, live.at[1])
    if live.sent is not None:
        live.sent = {**live.sent, "index": live.sent["index"] - cut}
    live.best_progress -= sum(seg["s_to"] - seg["s_from"] for seg in dropped)
    live.trim_m += sum(live.graph.arcs[arc_id(seg)].length_m for seg in dropped)  # route metres (blocks)


def _joined(old: list, new: list) -> list:
    """``old`` then ``new``; a new lap starting where the old one ends on the same lane is one segment."""
    tail, first = old[-1], new[0]
    if (tail["edge_id"], tail["forward"]) == (first["edge_id"], first["forward"]) and \
            abs(first["s_from"] - tail["s_to"]) < 1e-3:
        return [*old[:-1], {**tail, "s_to": first["s_to"]}, *new[1:]]
    return [*old, *new]
