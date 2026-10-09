"""D-525 (S0): a virtual signal opens one D-517 zone to one approach at a time.

Pure: the caller passes the clock and the zone's ``busy`` flag (``blocks.TickResult.busy``). The
robot never sees a colour; ``green()`` only feeds ``blocks.step(green=...)``.

- Every change of approach goes green → yellow → all red → green, and the next green waits until
  the zone is not busy (no holder, no unknown body), however long that takes (D-525 3).
- D-525 rev 5 ``occupancy`` (the default, a fresh state): no phase machine. Every approach may ask
  the D-517 table (``green`` is all of them) and capacity 1 alone lets one robot in. The lamps are
  derived each period from the zone's live table state (``zone_occupancy``, ``occupancy_lamps``):
  free -> all green; granted, not yet entered -> the holder's approach green, the rest yellow (shown
  orange, "reserved"); occupied or unknown -> all red. A restart relights nothing stored: the lamps
  come from live state and are red until the table knows the zone.
- D-525 rev 4 ``demand``: an outside controller only asks (``demand``) for an approach; this machine
  still decides, through the same green -> yellow -> all red -> (zone free) -> green path. A controller
  silent for ``controller_ttl_s`` drops the signal back to ``cycle`` with alert ``controller_lost``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional, Sequence

from fleet.routing.graph import Graph
from fleet.traffic.blocks import Layout, Robot, TableState

ALL_RED_ALERT_S = 30.0   # D-525 3: an all red stretched this long goes to the exception queue
HOLD_ALERT_S = 120.0     # D-525 4: a hold this long starves the other approaches


@dataclass(frozen=True)
class SignalPlan:
    id: str
    zone: str
    phases: tuple[tuple[str, float], ...]   # (approach arc id, green_s), one approach per phase
    yellow_s: float = 2.0
    all_red_s: float = 1.0
    min_green_s: float = 4.0         # D-525 rev 4: demand mode keeps a demanded green this long
    controller_ttl_s: float = 5.0    # D-525 rev 4: demand mode falls back to cycle after this silence


@dataclass
class SignalState:
    mode: str = "occupancy"                  # occupancy (rev 5 default) | cycle | hold | all_red | manual | demand
    aspect: str = "all_red"                  # green | yellow | all_red (the phase machine; idle in occupancy)
    phase: int = -1                          # the phase green last (or now)
    since: float = 0.0                       # aspect start
    mode_since: float = 0.0
    manual: Optional[int] = None             # the phase set_aspect asked for
    #: D-525 rev 4: approach -> (first asked, expires, reason) on the Fleet clock; the controller's last word
    demands: dict = field(default_factory=dict)
    heard: float = -math.inf
    lost: bool = False                       # demand fell back to cycle: the controller went silent


def entering_arcs(graph: Graph, layout: Layout, zone: str) -> set[str]:
    """Arcs outside ``zone`` that end where an arc of ``zone`` starts."""
    def in_zone(arc) -> bool:
        return any(unit == zone for unit, _s0, _s1 in layout.edge_units.get(arc.edge_id, ()))
    starts = {arc.start_place for arc in graph.arcs.values() if in_zone(arc)}
    return {arc.id for arc in graph.arcs.values() if not in_zone(arc) and arc.end_place in starts}


def check(plan: SignalPlan, graph: Graph, layout: Layout) -> list[str]:
    """D-525 2: reasons to refuse the plan (empty: accepted). A refused zone stays red (D-525 5)."""
    unit = layout.units.get(plan.zone)
    if unit is None or not unit.zone:
        return [f"{plan.id}: {plan.zone} is not a zone"]
    errors = []
    if unit.capacity != 1:
        errors.append(f"{plan.id}: zone {plan.zone} capacity {unit.capacity}, a signalled zone needs 1")
    named = [approach for approach, _green in plan.phases]
    if len(set(named)) != len(named):
        errors.append(f"{plan.id}: an approach is in two phases")
    entering = entering_arcs(graph, layout, plan.zone)
    if missing := sorted(entering - set(named)):
        errors.append(f"{plan.id}: approaches without a phase: {', '.join(missing)}")
    if extra := sorted(set(named) - entering):
        errors.append(f"{plan.id}: not an approach of {plan.zone}: {', '.join(extra)}")
    if not plan.phases or any(green <= 0 for _a, green in plan.phases) or plan.yellow_s <= 0 or plan.all_red_s <= 0:
        errors.append(f"{plan.id}: every time must be > 0")
    return errors


#: mode verbs besides ``set_aspect`` (D-443 §1.3, rev 4 ``demand``, rev 5 ``occupancy``)
VERBS = ("occupancy", "cycle", "hold", "all_red", "demand")


def command(plan: SignalPlan, state: SignalState, verb: str, now: float, approach: Optional[str] = None) -> None:
    """D-443 §1.3 verbs. ``all_red`` (E-stop, presence lost) is immediate; the rest change mode only.
    ``demand`` (D-525 rev 4) hands the choice of the next green to the controller's demands.
    ``occupancy`` (rev 5) leaves the phase machine at all red, so a later phase verb starts from all
    red and waits for a free zone, as after a restart."""
    if verb == "set_aspect":
        state.manual = next(i for i, (a, _g) in enumerate(plan.phases) if a == approach)
    elif verb not in VERBS:
        raise ValueError(verb)
    state.mode, state.mode_since, state.lost = ("manual" if verb == "set_aspect" else verb), now, False
    state.demands, state.heard = {}, now   # a fresh controller clock; old demands never carry over
    if verb in ("all_red", "occupancy") and state.aspect != "all_red":
        state.aspect, state.since = "all_red", now


def demand(plan: SignalPlan, state: SignalState, approach: Optional[str], now: float, ttl_s: float,
           reason: str = "") -> bool:
    """D-525 rev 4: the controller asks for a green for ``approach`` until ``now + ttl_s`` (None: it is
    alive and nobody waits). True when the approach had no live demand (an audit row). PermissionError:
    not in demand mode; ValueError: not an approach of this signal. Asking never lights anything."""
    if state.mode != "demand":
        raise PermissionError("demand mode is off")
    if approach is not None and approach not in {a for a, _g in plan.phases}:
        raise ValueError(approach)
    state.heard = now
    if approach is None:
        return False
    old = state.demands.get(approach)
    live = old is not None and old[1] > now
    state.demands[approach] = (old[0] if live else now, now + ttl_s, reason)
    return not live


def queue(plan: SignalPlan, state: SignalState, now: float) -> list[str]:
    """Live demands, oldest first, ties in phase order."""
    order = {a: i for i, (a, _g) in enumerate(plan.phases)}
    live = [(since, order[a], a) for a, (since, until, _r) in state.demands.items() if until > now]
    return [a for _s, _i, a in sorted(live)]


def advance(plan: SignalPlan, state: SignalState, now: float, zone_busy: bool) -> None:
    if state.mode == "occupancy":   # no phases: the table's capacity decides, the lamps follow it
        return
    if state.mode == "demand":
        state.demands = {a: d for a, d in state.demands.items() if d[1] > now}
        if now - state.heard > plan.controller_ttl_s:   # controller lost: the plain cycle, flagged
            state.mode, state.mode_since, state.lost, state.demands = "cycle", now, True, {}
    held = now - state.since
    asked = queue(plan, state, now) if state.mode == "demand" else []
    if state.aspect == "green":
        current = plan.phases[state.phase][0]
        leave = (state.mode == "cycle" and held >= plan.phases[state.phase][1]) or \
            (state.mode == "manual" and state.manual != state.phase) or \
            (state.mode == "demand" and any(a != current for a in asked)
             and (current not in asked or held >= plan.min_green_s))
        if leave:
            state.aspect, state.since = "yellow", now
            if current in state.demands:   # demand: the approach just served queues behind the others
                state.demands[current] = (now, *state.demands[current][1:])
    elif state.aspect == "yellow":
        if held >= plan.yellow_s:
            state.aspect, state.since = "all_red", now
    elif state.mode in ("cycle", "manual", "demand") and held >= plan.all_red_s and not zone_busy \
            and (state.mode != "demand" or asked):
        if state.mode == "manual":
            state.phase = state.manual
        elif state.mode == "demand":
            state.phase = next(i for i, (a, _g) in enumerate(plan.phases) if a == asked[0])
        else:
            state.phase = (state.phase + 1) % len(plan.phases)
        state.aspect, state.since = "green", now


def green(plan: SignalPlan, state: SignalState) -> frozenset[str]:
    """Approaches the D-517 table may grant the zone to. ``occupancy``: all of them, so the signal adds
    no phase gate (nothing to deadlock on) and the zone's capacity 1 alone picks who goes in."""
    if state.mode == "occupancy":
        return frozenset(a for a, _g in plan.phases)
    return frozenset((plan.phases[state.phase][0],)) if state.aspect == "green" else frozenset()


#: ``(state, holder, approach)`` of a signalled zone (rev 5): ``free``, ``reserved`` (granted, not yet
#: entered), ``occupied`` or ``unknown``; ``holder`` the robot holding or inside it, ``approach`` the
#: arc it was granted from (None when not known).
UNKNOWN = ("unknown", None, None)


def zone_occupancy(table: TableState, robots: Sequence[Robot], zone: str,
                   unplaced: Sequence[str] = ()) -> tuple[str, Optional[str], Optional[str]]:
    """The zone's live state from the D-517 table after ``blocks.step`` (``robots``: that tick's robots).

    Unknown when a robot was never placed, or a robot not localized this tick (UNKNOWN, missing, a
    finished trip's pins) may be in it. Occupied when a localized robot's padded body touches it.
    Reserved when a robot holds a grant on it but is not in it yet. Free otherwise."""
    if unplaced:
        return UNKNOWN
    localized = {robot.id for robot in robots if robot.d is not None}
    if any(zone in units for units in table.pinned.values()) or \
            any(zone in units for rid, units in table.last_occupied.items() if rid not in localized):
        return UNKNOWN
    holders = sorted((rid, i) for rid, held in table.held.items() for i, (unit, _f) in held.items() if unit == zone)
    inside = sorted(rid for rid, units in table.last_occupied.items() if zone in units)
    if not holders and not inside:
        return ("free", None, None)
    holder = next((rid for rid, _i in holders if rid in inside), inside[0] if inside else holders[0][0])
    index = next((i for rid, i in holders if rid == holder), None)
    route = next((robot.spans for robot in robots if robot.id == holder), ())
    approach = (route[index].entry or None) if index is not None and index < len(route) else None
    return ("occupied" if inside else "reserved", holder, approach)


def occupancy_lamps(plan: SignalPlan, occupancy: tuple[str, Optional[str], Optional[str]]) -> dict[str, str]:
    """Rev 5 lamps: free all green; reserved the holder's approach green and the rest yellow (shown
    orange); occupied or unknown all red. Display and advice only: the D-517 grant lets a robot in."""
    state, _holder, approach = occupancy
    if state == "free":
        return {a: "green" for a, _g in plan.phases}
    if state == "reserved":
        return {a: "green" if a == approach else "yellow" for a, _g in plan.phases}
    return {a: "red" for a, _g in plan.phases}


def forecast(plan: SignalPlan, state: SignalState, now: float, zone_busy: bool,
             occupancy: tuple[str, Optional[str], Optional[str]] = UNKNOWN) -> dict[str, dict]:
    """D-525 rev 3: per approach ``{lamp, left_s, green_in_s, exact}`` — the T-map style countdown.

    ``left_s`` is how long the shown lamp lasts; ``green_in_s`` how long until that approach is green
    (0 while green). A green waits for the zone to be free (D-525 3), so every future green is a lower
    bound (``exact`` false) except the current lamp's own end in ``cycle``. None: no time is known
    (``hold``, operator ``all_red``, a manual green, or no next phase). Advisory only: a robot may show
    it or slow down earlier; only the D-517 authority lets it in. ``demand`` (rev 4): a green is
    open-ended (None) and only demanded approaches get a ``green_in_s`` lower bound, in queue order.
    ``occupancy`` (rev 5): lamps from ``occupancy_lamps``; no time is known (the holder leaves when it
    leaves), so ``left_s`` is None and ``green_in_s`` is 0 on green, else None.
    """
    if state.mode == "occupancy":
        return {a: {"lamp": lamp, "left_s": None, "green_in_s": 0.0 if lamp == "green" else None, "exact": False}
                for a, lamp in occupancy_lamps(plan, occupancy).items()}
    n = len(plan.phases)
    held = max(0.0, now - state.since)
    lit = green(plan, state)
    last = plan.phases[state.phase][0] if state.phase >= 0 else None
    out = {}
    for approach, _green_s in plan.phases:
        lamp = "green" if approach in lit else "yellow" if state.aspect == "yellow" and approach == last else "red"
        out[approach] = {"lamp": lamp, "left_s": None, "green_in_s": 0.0 if lamp == "green" else None, "exact": False}
    if state.mode in ("hold", "all_red") or n == 0:
        return out
    if state.mode == "manual":
        if state.aspect != "green" and state.manual is not None:
            rest = (plan.yellow_s - held + plan.all_red_s) if state.aspect == "yellow" else max(0.0, plan.all_red_s - held)
            row = out[plan.phases[state.manual][0]]
            row["green_in_s"] = round(rest, 1)
        return out
    if state.mode == "demand":
        asked = queue(plan, state, now)
        if state.aspect == "green":
            t = (max(0.0, plan.min_green_s - held) if last in asked else 0.0) + plan.yellow_s + plan.all_red_s
        elif state.aspect == "yellow":
            end = max(0.0, plan.yellow_s - held)
            out[last].update(left_s=round(end, 1), exact=True)
            t = end + plan.all_red_s
        else:
            t = max(0.0, plan.all_red_s - held)
        for approach in asked:
            if out[approach]["green_in_s"] is None:
                out[approach]["green_in_s"] = round(t, 1)
                t += plan.min_green_s + plan.yellow_s + plan.all_red_s
        return out
    # cycle: walk the phase order from now
    if state.aspect == "green":
        end = max(0.0, plan.phases[state.phase][1] - held)
        out[last].update(left_s=round(end, 1), exact=True)
        t, start = end + plan.yellow_s + plan.all_red_s, state.phase + 1
    elif state.aspect == "yellow":
        end = max(0.0, plan.yellow_s - held)
        out[last].update(left_s=round(end, 1), exact=True)
        t, start = end + plan.all_red_s, state.phase + 1
    else:
        t, start = max(0.0, plan.all_red_s - held), state.phase + 1
    for k in range(n):
        q = (start + k) % n
        approach, green_s = plan.phases[q]
        row = out[approach]
        if row["green_in_s"] is None:              # red or yellow: when it is green next
            row["green_in_s"] = round(t, 1)
            if row["lamp"] == "red":
                row["left_s"] = round(t, 1)           # a red lasts until its green
        t += green_s + plan.yellow_s + plan.all_red_s
    if zone_busy and state.aspect == "all_red":
        for row in out.values():
            row["exact"] = False
    return out


def alert(plan: SignalPlan, state: SignalState, now: float) -> Optional[str]:
    """The exception-queue row (D-525 8), or None."""
    if state.lost and state.mode == "cycle":
        return "controller_lost"
    if state.aspect == "all_red" and (state.mode in ("cycle", "manual") or (state.mode == "demand" and state.demands)) \
            and now - state.since > plan.all_red_s + ALL_RED_ALERT_S:
        return "all_red_stretched"
    if state.mode == "hold" and now - state.mode_since > HOLD_ALERT_S:
        return "hold_long"
    return None
