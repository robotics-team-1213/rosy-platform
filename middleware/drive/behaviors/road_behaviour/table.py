"""Transition table of the road-behaviour machine, rendered into the D-384 plan doc.

The rows describe machine.py; tests exercise each row and check the doc carries this text.
"""

from __future__ import annotations

from core_features.road_behaviour.machine import required_inputs
from core_features.road_behaviour.model import BehaviourState, TransitionRow

S = BehaviourState
_LANE = (S.LANE_FOLLOW, S.FOLLOW, S.HOLD)

_ROWS = (
    (_LANE, "static obstacle within d0 + tau*v_cruise (HOLD releases at + 0.05 m)", S.HOLD, "0"),
    (_LANE, "junction within d_jn, junction logic off or stop line unknown", S.HOLD,
     "0 (junction_unsupported)"),
    (_LANE, "junction within d_jn, junction logic on, stop line fresh", S.APPROACH, "v_app"),
    (_LANE, "moving lead within corridor (not oncoming)", S.FOLLOW, "(gap - d0) / tau"),
    (_LANE, "corridor clear, no junction within d_jn", S.LANE_FOLLOW, "v_cruise"),
    ((S.APPROACH,), "junction known absent", S.LANE_FOLLOW, "v_cruise"),
    ((S.APPROACH,), "stop line <= d_stop_max (< d_stop_min adds overshoot event)",
     S.STOP_AT_LINE, "0"),
    ((S.APPROACH,), "stop line > d_stop_max", S.APPROACH, "v_app"),
    ((S.STOP_AT_LINE,), "stopped < t_stop", S.STOP_AT_LINE, "0"),
    ((S.STOP_AT_LINE,), "stopped >= t_stop", S.YIELD_CHECK, "0"),
    ((S.YIELD_CHECK,), "obstacle, pedestrian, no branch, robot in intersection, "
     "Fleet grant false/stale, or local right of way to another robot", S.YIELD_CHECK, "0"),
    ((S.YIELD_CHECK,), "all clear (Fleet grant true skips local ordering)", S.CREEP, "v_creep"),
    ((S.CREEP,), "static obstacle, pedestrian, robot in intersection, grant false/stale",
     S.YIELD_CHECK, "0"),
    ((S.CREEP,), "clear for < t_clear", S.CREEP, "v_creep"),
    ((S.CREEP,), "clear for >= t_clear", S.CROSS, "v_cross"),
    ((S.CROSS,), "target lane acquired", S.LANE_FOLLOW, "v_cross"),
    ((S.CROSS,), "travelled > 1.3 x arc length without target lane", S.FAULT, "0"),
    ((S.CROSS,), "turning (pedestrian or static obstacle: cap 0 in place)", S.CROSS, "v_cross"),
    (tuple(s for s in S if s is not S.FAULT), "a required input stale (> t_stale) or missing",
     S.FAULT, "0"),
    ((S.FAULT,), "lane inputs fresh and road_state TRACK", S.LANE_FOLLOW, "v_cruise"),
    ((S.FAULT,), "otherwise", S.FAULT, "0"),
)


def transition_table() -> tuple:
    """One TransitionRow per (source, condition)."""
    return tuple(TransitionRow(source, condition, target, cap)
                 for sources, condition, target, cap in _ROWS for source in sources)


def render_transition_table_markdown() -> str:
    lines = ["| from | condition | to | speed cap |", "|---|---|---|---|"]
    for sources, condition, target, cap in _ROWS:
        names = ", ".join(f"`{s.value}`" for s in sources)
        lines.append(f"| {names} | {condition} | `{target.value}` | {cap} |")
    lines += ["", "| state | required inputs (junction logic on) |", "|---|---|"]
    for state in S:
        needed = ", ".join(f"`{n}`" for n in required_inputs(state, True)) or "-"
        lines.append(f"| `{state.value}` | {needed} |")
    return "\n".join(lines) + "\n"
