"""D-525 (S0): a virtual signal opens one D-517 zone to one approach at a time.

Pure: the caller passes the clock and the zone's ``busy`` flag (``blocks.TickResult.busy``). The
robot never sees a colour; ``green()`` only feeds ``blocks.step(green=...)``.

- Every change of approach goes green → yellow → all red → green, and the next green waits until
  the zone is not busy (no holder, no unknown body), however long that takes (D-525 3).
- A fresh state is all red with mode ``all_red``: a Fleet restart never relights a phase (D-525 5).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from fleet.routing.graph import Graph
from fleet.traffic.blocks import Layout

ALL_RED_ALERT_S = 30.0   # D-525 3: an all red stretched this long goes to the exception queue
HOLD_ALERT_S = 120.0     # D-525 4: a hold this long starves the other approaches


@dataclass(frozen=True)
class SignalPlan:
    id: str
    zone: str
    phases: tuple[tuple[str, float], ...]   # (approach arc id, green_s), one approach per phase
    yellow_s: float = 2.0
    all_red_s: float = 1.0


@dataclass
class SignalState:
    mode: str = "all_red"                    # cycle | hold | all_red | manual
    aspect: str = "all_red"                  # green | yellow | all_red
    phase: int = -1                          # the phase green last (or now)
    since: float = 0.0                       # aspect start
    mode_since: float = 0.0
    manual: Optional[int] = None             # the phase set_aspect asked for


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


def command(plan: SignalPlan, state: SignalState, verb: str, now: float, approach: Optional[str] = None) -> None:
    """D-443 §1.3 verbs. ``all_red`` (E-stop, presence lost) is immediate; the rest change mode only."""
    if verb == "set_aspect":
        state.manual = next(i for i, (a, _g) in enumerate(plan.phases) if a == approach)
    elif verb not in ("cycle", "hold", "all_red"):
        raise ValueError(verb)
    state.mode, state.mode_since = ("manual" if verb == "set_aspect" else verb), now
    if verb == "all_red" and state.aspect != "all_red":
        state.aspect, state.since = "all_red", now


def advance(plan: SignalPlan, state: SignalState, now: float, zone_busy: bool) -> None:
    held = now - state.since
    if state.aspect == "green":
        leave = (state.mode == "cycle" and held >= plan.phases[state.phase][1]) or \
            (state.mode == "manual" and state.manual != state.phase)
        if leave:
            state.aspect, state.since = "yellow", now
    elif state.aspect == "yellow":
        if held >= plan.yellow_s:
            state.aspect, state.since = "all_red", now
    elif state.mode in ("cycle", "manual") and held >= plan.all_red_s and not zone_busy:
        state.phase = state.manual if state.mode == "manual" else (state.phase + 1) % len(plan.phases)
        state.aspect, state.since = "green", now


def green(plan: SignalPlan, state: SignalState) -> frozenset[str]:
    return frozenset((plan.phases[state.phase][0],)) if state.aspect == "green" else frozenset()


def alert(plan: SignalPlan, state: SignalState, now: float) -> Optional[str]:
    """The exception-queue row (D-525 8), or None."""
    if state.aspect == "all_red" and state.mode in ("cycle", "manual") \
            and now - state.since > plan.all_red_s + ALL_RED_ALERT_S:
        return "all_red_stretched"
    if state.mode == "hold" and now - state.mode_since > HOLD_ALERT_S:
        return "hold_long"
    return None
