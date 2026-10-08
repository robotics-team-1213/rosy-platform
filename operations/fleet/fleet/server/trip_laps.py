"""D-517 2/3: repeat-trip lap bookkeeping, pure on ``LiveTrip`` and plans (no robot calls)."""
from fleet.routing.execute import arc_id, ends_at_place, plan_again, route_key
from fleet.server.trip_ports import LiveTrip

#: D-517 2/5: a failed lap check is retried this often, this many times (D-438), then it is the operator's.
LAP_RETRY_S = 5.0
LAP_RETRIES = 2


def lap_arcs(active, segments: list, request: dict, caps: dict, blocked, routing, max_turn_deg) -> tuple[str, ...]:
    """D-517 3: one lap's arcs planned from where ``segments`` end (else the plan's own: the lap check holds)."""
    if not segments:
        return ()
    end = active[2].arcs[arc_id(segments[-1])].point_at(segments[-1]["s_to"])
    body, _hold = plan_again(active, end, request, caps, blocked, set(), routing, max_turn_deg)
    return tuple(arc_id(seg) for seg in (body or {"segments": segments})["segments"])


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
