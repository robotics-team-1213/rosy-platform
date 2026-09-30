"""Road-behaviour state machine (D-384 §2 keep-right tie-break, §4 road behaviour).

A ROS-free library for CORE's traffic_policy / line_follow. There is one fail-closed
traffic policy inside CORE before the Command Manager (D-151 §3-4, D-2 single final
command). This module produces **no command**: its output is a speed cap that CORE
min()s into its existing caps and a branch choice. It never emits a twist.

`step_behaviour(memory, inputs, params)` is a pure function; the same memory and inputs
always give the same memory and output, so replay and shadow runs reproduce device runs.
Stale (> t_stale) or missing required inputs give FAULT with cap 0.

Junction states need map pose and stop-line distance (D-378 §3.3-3.4). Until those exist
`junction_logic_enabled` is False and a junction inside d_jn is HOLD `junction_unsupported`.
"""

from __future__ import annotations

import math
from dataclasses import replace
from typing import Optional

from core_features.road_behaviour.model import (
    EVENT_OBSTACLE_HOLD,
    EVENT_STOP_LINE_OVERSHOOT,
    EVENT_TURN_TIMEOUT,
    JUNCTION_STATES,
    BehaviourInputs,
    BehaviourMemory,
    BehaviourOutput,
    BehaviourParams,
    BehaviourState,
    JunctionAhead,
    JunctionRobot,
    RoadLevel,
    Stamped,
)

S = BehaviourState

_JUNCTION_BODY = ("obstacles", "junction")
_REQUIRED = {
    S.APPROACH: ("road_state", "obstacles", "junction", "stop_line_distance"),
    S.STOP_AT_LINE: _JUNCTION_BODY,
    S.YIELD_CHECK: _JUNCTION_BODY + ("pedestrian_at_crosswalk", "other_robots"),
    S.CREEP: ("road_state",) + _JUNCTION_BODY + ("pedestrian_at_crosswalk", "other_robots"),
    S.CROSS: ("obstacles", "pedestrian_at_crosswalk", "turn"),
    S.FAULT: (),
}
#: Junction states where a known-absent junction (Stamped(None)) is also missing.
_NEEDS_JUNCTION_VALUE = (S.STOP_AT_LINE, S.YIELD_CHECK, S.CREEP)
_BRANCH_FALLBACK = (("right", "keep_right"), ("straight", "no_right_straight"),
                    ("left", "only_left"))


def required_inputs(state: BehaviourState, junction_logic_enabled: bool) -> tuple:
    """Inputs that must be fresh in `state`; any stale or None one gives FAULT."""
    if state in _REQUIRED:
        return _REQUIRED[state]
    lane = ("road_state", "obstacles")
    return lane + ("junction",) if junction_logic_enabled else lane


def choose_branch(route: Optional[str], branches) -> tuple:
    """D-384 §2: route > right > straight > left. A route the junction lacks is no branch."""
    if route is not None:
        return (route, "route") if route in branches else (None, "route_branch_unavailable")
    for direction, reason in _BRANCH_FALLBACK:
        if direction in branches:
            return direction, reason
    return None, "no_branch"


def _fresh(item: Optional[Stamped], now: float, p: BehaviourParams) -> bool:
    return item is not None and 0.0 <= now - item.stamp <= p.t_stale


def _value(item: Optional[Stamped], now: float, p: BehaviourParams):
    return item.value if _fresh(item, now, p) else None


def _missing(state: BehaviourState, inp: BehaviourInputs, p: BehaviourParams) -> list:
    names = [name for name in required_inputs(state, p.junction_logic_enabled)
             if not _fresh(getattr(inp, name), inp.now, p)]
    if (state in _NEEDS_JUNCTION_VALUE and "junction" not in names
            and inp.junction.value is None):
        names.append("junction")
    return names


def _level(inp: BehaviourInputs, p: BehaviourParams) -> Optional[RoadLevel]:
    sample = _value(inp.road_state, inp.now, p)
    if sample is None:
        return None
    try:
        return RoadLevel(sample.level)
    except ValueError:
        return None


def _obstacles(inp: BehaviourInputs, p: BehaviourParams, holding: bool) -> tuple:
    """(static stop needed, nearest moving lead range or None). Oncoming movers are static."""
    items = []
    for item in _value(inp.obstacles, inp.now, p) or ():
        oncoming = item.closing_speed_mps is not None and item.closing_speed_mps > p.v_cruise
        items.append((item.range_m, bool(item.is_moving) and not oncoming))
    lead = _value(inp.lead, inp.now, p)
    if lead is not None:
        items.append((lead.gap_m, lead.speed_mps > p.moving_speed_eps))
    static_limit = p.corridor_length_m + (p.hold_release_margin_m if holding else 0.0)
    static = any(not math.isfinite(r) or (not mv and r <= static_limit) for r, mv in items)
    movers = [r for r, mv in items if mv and math.isfinite(r) and r <= p.corridor_length_m]
    return static, (min(movers) if movers else None)


def _follow_cap(gap: Optional[float], p: BehaviourParams) -> float:
    """ISO 15622 time gap: keep gap >= d0 + tau*v, so v <= (gap - d0) / tau."""
    if gap is None:
        return p.v_cruise
    return min(p.v_cruise, max(0.0, (gap - p.d0) / p.tau))


def _branch(inp: BehaviourInputs, junction: JunctionAhead, p: BehaviourParams) -> tuple:
    if inp.route_direction is not None and not _fresh(inp.route_direction, inp.now, p):
        return None, "route_stale"
    route = inp.route_direction.value if inp.route_direction is not None else None
    return choose_branch(route, junction.branches)


def _must_yield(me_arrival: float, my_path: Optional[str], junction: JunctionAhead,
                other: JunctionRobot, p: BehaviourParams) -> Optional[str]:
    """도로교통법 §26 order: in intersection, wider road, first arrival, right, left turn."""
    if other.in_intersection:
        return "in_intersection"
    mine, theirs = junction.road_width_m, other.road_width_m
    if mine is not None and theirs is not None and mine != theirs:
        return "wider_road" if theirs > mine else None
    delta = other.arrival_time - me_arrival
    if delta < -p.t_tie:
        return "arrived_first"
    if delta > p.t_tie:
        return None
    if other.relative_side == "right":
        return "right_hand"
    if (other.relative_side == "opposite" and my_path == "left"
            and other.intended_direction in (None, "straight", "right")):
        return "left_turn_yields"
    return None


def _grant_block(inp: BehaviourInputs, p: BehaviourParams) -> Optional[str]:
    if inp.fleet_grant is None:
        return None
    if not _fresh(inp.fleet_grant, inp.now, p):
        return "fleet_grant_stale"
    return None if inp.fleet_grant.value else "fleet_grant_wait"


def _junction_block(inp: BehaviourInputs, p: BehaviourParams, static: bool, mover,
                    choice: Optional[str], why: str, robots: tuple, *, full: bool,
                    me_arrival: float, junction: JunctionAhead) -> Optional[str]:
    """First reason not to move at the line. `full` adds local ordering (YIELD_CHECK)."""
    if static or (full and mover is not None):
        return "obstacle_ahead"
    if _value(inp.pedestrian_at_crosswalk, inp.now, p):
        return "pedestrian_at_crosswalk"
    if choice is None:
        return why
    for other in robots:
        if other.in_intersection:
            return f"yield:{other.robot_id}:in_intersection"
    if inp.fleet_grant is not None:
        return _grant_block(inp, p)
    if full:
        for other in robots:
            rule = _must_yield(me_arrival, choice, junction, other, p)
            if rule is not None:
                return f"yield:{other.robot_id}:{rule}"
    return None


def _fault(memory: BehaviourMemory, now: float, reason: str, events: tuple = ()) -> tuple:
    stay = memory.state is S.FAULT
    mem = BehaviourMemory(state=S.FAULT, entered_at=memory.entered_at if stay else now)
    return mem, BehaviourOutput(S.FAULT, 0.0, None, reason, events)


def step_behaviour(memory: BehaviourMemory, inputs: BehaviourInputs,
                   params: BehaviourParams) -> tuple:
    """(memory, inputs, params) -> (next memory, output). Pure and deterministic."""
    p, now, mem = params, inputs.now, memory
    if not p.junction_logic_enabled and mem.state in JUNCTION_STATES:
        mem = BehaviourMemory(state=S.HOLD, entered_at=now)
    if mem.state is S.FAULT:
        missing = _missing(S.LANE_FOLLOW, inputs, p)
        if missing:
            return _fault(mem, now, "stale_or_missing:" + ",".join(missing))
        if _level(inputs, p) is not RoadLevel.TRACK:
            return _fault(mem, now, "await_road_state_track")
        mem = BehaviourMemory(state=S.LANE_FOLLOW, entered_at=now)
    missing = _missing(mem.state, inputs, p)
    if missing:
        return _fault(mem, now, "stale_or_missing:" + ",".join(missing))
    level = _level(inputs, p)
    if "road_state" in required_inputs(mem.state, p.junction_logic_enabled) and level is None:
        return _fault(mem, now, "road_state_invalid")

    holding = mem.state is S.HOLD or mem.blocked_since is not None
    static, mover = _obstacles(inputs, p, holding)
    events = []
    target, cap, reason, choice, turn_done = _transition(mem, inputs, p, static, mover, events)
    if target is S.FAULT:
        return _fault(mem, now, reason, tuple(events))

    # Overlays shared by every non-FAULT state: road level, lead gap, pedestrian, CORE cap.
    if target is not S.CROSS and not turn_done:
        factor = {RoadLevel.SLOW: p.slow_factor, RoadLevel.STOP: 0.0}.get(level, 1.0)
        cap = min(cap, p.v_cruise * factor)
        if level is RoadLevel.STOP and reason in ("lane_follow", "following"):
            reason = "road_state_stop"
    cap = min(cap, _follow_cap(mover, p))
    if static:
        cap = 0.0
    if _value(inputs.pedestrian_at_crosswalk, now, p):
        cap, reason = 0.0, "pedestrian_at_crosswalk"
    core = inputs.core_speed_cap_mps
    if core is not None:
        cap = min(cap, core if math.isfinite(core) else 0.0)
    cap = min(p.v_cruise, max(0.0, cap))

    blocked_since, reported = None, False
    if static:
        blocked_since = mem.blocked_since if mem.blocked_since is not None else now
        reported = mem.blocked_reported
        if not reported and now - blocked_since >= p.obstacle_escalate_s:
            reported = True
            events.append(EVENT_OBSTACLE_HOLD)

    same = target is mem.state
    new_mem = replace(
        mem, state=target, entered_at=mem.entered_at if same else now,
        arrived_at=mem.arrived_at if target in JUNCTION_STATES else None,
        path_choice=choice if target in JUNCTION_STATES else None,
        blocked_since=blocked_since, blocked_reported=reported)
    if target is S.STOP_AT_LINE and not same:
        new_mem = replace(new_mem, arrived_at=now)
    return new_mem, BehaviourOutput(target, cap, new_mem.path_choice, reason, tuple(events))


def _transition(mem, inp, p, static, mover, events) -> tuple:
    """(target, state cap, reason, path choice, left the junction this step)."""
    state, now = mem.state, inp.now
    junction = _value(inp.junction, now, p)
    if state in (S.LANE_FOLLOW, S.FOLLOW, S.HOLD):
        if static:
            return S.HOLD, 0.0, "obstacle_ahead", None, False
        if junction is not None and junction.distance_m <= p.d_jn:
            if not p.junction_logic_enabled or not _fresh(inp.stop_line_distance, now, p):
                return S.HOLD, 0.0, "junction_unsupported", None, False
            state = S.APPROACH
        elif mover is not None:
            return S.FOLLOW, p.v_cruise, "following", None, False
        else:
            return S.LANE_FOLLOW, p.v_cruise, "lane_follow", None, False

    if state is S.APPROACH:
        if junction is None:
            return S.LANE_FOLLOW, p.v_cruise, "junction_passed", None, False
        choice, _ = _branch(inp, junction, p)
        line = inp.stop_line_distance.value
        if line <= p.d_stop_max:
            if line < p.d_stop_min:
                events.append(EVENT_STOP_LINE_OVERSHOOT)
            return S.STOP_AT_LINE, 0.0, "stop_at_line", choice, False
        return S.APPROACH, p.v_app, "approach", choice, False

    if state is S.STOP_AT_LINE:
        choice, _ = _branch(inp, junction, p)
        if now - mem.entered_at >= p.t_stop:
            return S.YIELD_CHECK, 0.0, "yield_check", choice, False
        return S.STOP_AT_LINE, 0.0, "stop_at_line", choice, False

    if state in (S.YIELD_CHECK, S.CREEP):
        choice, why = _branch(inp, junction, p)
        robots = tuple(sorted(inp.other_robots.value, key=lambda r: r.robot_id))
        arrival = mem.arrived_at if mem.arrived_at is not None else now
        full = state is S.YIELD_CHECK
        block = _junction_block(inp, p, static, mover, choice, why, robots, full=full,
                                me_arrival=arrival, junction=junction)
        if block is not None:
            return S.YIELD_CHECK, 0.0, block, choice, False
        if full:
            return S.CREEP, p.v_creep, "creep", choice, False
        if now - mem.entered_at >= p.t_clear:
            return S.CROSS, p.v_cross, "cross", choice, False
        return S.CREEP, p.v_creep, "creep", choice, False

    # CROSS: follow the precomputed arc; the branch is latched.
    turn = inp.turn.value
    if turn.target_lane_acquired:
        return S.LANE_FOLLOW, p.v_cross, "turn_complete", None, True
    if turn.travelled_m > p.arc_timeout_factor * turn.arc_length_m:
        events.append(EVENT_TURN_TIMEOUT)
        return S.FAULT, 0.0, "turn_target_lane_not_acquired", None, False
    return S.CROSS, p.v_cross, "cross", mem.path_choice, False


class RoadBehaviour:
    """Holds the memory between calls; all logic is in step_behaviour."""

    def __init__(self, params: Optional[BehaviourParams] = None) -> None:
        self.params = params or BehaviourParams()
        self.memory = BehaviourMemory()

    def step(self, inputs: BehaviourInputs) -> BehaviourOutput:
        self.memory, output = step_behaviour(self.memory, inputs, self.params)
        return output

    def reset(self) -> None:
        self.memory = BehaviourMemory()
