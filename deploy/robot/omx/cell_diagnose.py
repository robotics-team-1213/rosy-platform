#!/usr/bin/env python3
"""Why did a pick fail, and what should the next attempt change? Measurements decide the cause; a strategy table
(data, not code) orders the next actions; every diagnosis is a decision row a model can learn from and override.

2026-10-29 showed the same contact repeated by retries that changed nothing: the jaws opened too wide and met the
board, then the box top, then the box edge. Each cause needs a different change. Causes from what was measured:
  on_top   contact near the object's top height: the jaws came down on the box - its position estimate is off
  beside   contact between the surface and the top: a finger met the box edge or a neighbour
  surface  contact at or below the planned grasp height: the surface is higher than its surface_z says
  empty    the jaws closed on nothing: the box was not between them
  unknown  no measurement to tell (no contact pose, no heights)
"""
from __future__ import annotations

import cell_params as prm

# cause -> next actions in order; the caller takes the first it can do. Editing this table changes the policy.
STRATEGY = {
    "on_top": ["wrist_align", "other_axis", "observe_again", "ask_person"],
    "beside": ["other_axis", "narrow_jaws", "wrist_align", "ask_person"],
    "surface": ["probe_surface", "ask_person"],
    "empty": ["observe_again", "wrist_align", "other_axis", "ask_person"],
    "unstable_grasp": ["wrist_align", "other_axis", "observe_again", "ask_person"],
    "unknown": ["observe_again", "ask_person"],
}


# How a whole attempt ended (cell_auto_pick.run_auto's result) -> what cell_recovery changes before the next one.
# Obstacle types run_auto names when no object is usable (its refusals say which), each with its own row below:
#   packed  no finger room beside a box: cell_align slides it lengthwise (cause no_room)
#   pile    a tangled blob, boxes on or against each other (2026-11-13 arm_s: a box's end lay on another, the pile against
#           the arm plate): cell_align.pile_push slides the blob when its path is clear, then the pick is planned again;
#           with none clear the pile is locked and goes to a person
#   edge of view  the box or a side of it is past the top camera's view (2026-11-13 arm_s: the camera moved 84 px and a box
#           on Pinky sat at the frame's edge): unseen is not free, and no push is aimed at what the camera cannot see
#   out of reach  past the joint1 pan limit (2026-11-13 arm_s: a box at -161 deg, limit 149): no grip and no push reaches it
# The first type with a refusal wins, in this order: a push can still free a pile or a packed box. The last two go to a person
# with what to change (ASK).
# shortcut: a box leaning on a fixture (2026-11-13 arm_b, beside the ship) is not seen from the top camera; it needs the
# side camera or depth before it can be a type here.
OBSTACLE_TYPES = {"tangled blob": "tangled pile", "no finger room": "packed", "edge of view": "edge of view",
                  "not inside the camera view": "edge of view", "out of reach": "out of reach"}
ASK = {"edge_of_view": "move the box, or aim the top camera, so the box and the room beside it are in view",
       "out_of_reach": "move the box inside the arm's reach"}
ATTEMPT_CAUSES = (("stopped: no usable object (tangled pile)", "pile"), ("stopped: no usable object (edge of view)", "edge_of_view"),
                  ("stopped: no usable object (out of reach)", "out_of_reach"),
                  ("stopped: released", "lift_stall"), ("stopped: holding", "held_stop"), ("stopped: still holding", "stuck_in_jaws"),
                  ("stopped: misaligned", "misaligned"), ("stopped: reinserted", "unstable_grasp"), ("stopped: placed", "not_seen_placed"), ("stopped: no usable", "no_room"),
                  ("stopped: pivot", "calibrate"), ("stopped: no clear pivot", "calibrate"),
                  ("stopped: unseated_cone", "s6_unseated_cone"), ("stopped: toppled", "s2_toppled_or_slumped"),
                  ("stopped: shallow_pinch", "s4_shallow_pinch"), ("stopped: packed_column", "s3_packed_no_clearance"),
                  *((f"stopped: {c} -> ", "contact") for c in STRATEGY))  # the strategy table already ended at a person
RECOVERY = {
    # the order is the first guess; cell_recovery reorders by what really worked (cell_choices), never past this list
    # let go and rose: slower first (moves nothing else); cell_why's reading can put the push first
    "lift_stall": ["slow_down", "push_clear", "observe_again", "ask_person"],
    "no_room": ["push_clear", "observe_again", "ask_person"],
    "pile": ["push_clear", "observe_again", "ask_person"],  # one piece per push; the next look re-plans from what is left
    "edge_of_view": ["ask_person"],
    "out_of_reach": ["ask_person"],
    "no_progress": ["push_clear", "observe_again", "ask_person"],
    "misaligned": ["observe_again", "push_clear", "ask_person"],
    "unstable_grasp": ["observe_again", "push_clear", "ask_person"],
    "scene_moved": ["observe_again", "push_clear", "ask_person"],  # the top camera saw the pile change: plan from what is there now
    "not_seen_placed": ["observe_again", "ask_person"],
    "s6_unseated_cone": ["push_clear", "observe_again", "ask_person"],
    "s2_toppled_or_slumped": ["ask_person"],  # toppled/slumped stack requires S-Temp evacuation or person, never blind in-place retry
    "s4_shallow_pinch": ["observe_again", "push_clear", "ask_person"],
    "s3_packed_no_clearance": ["push_clear", "observe_again", "ask_person"],
    "held_stop": ["ask_person"],  # a box may still be in the jaws
    "stuck_in_jaws": ["ask_person"],
    # named apart so the ledger counts them: 13 calibrate and 35 descent stops in the 110 real attempts up to 2026-11-07
    "calibrate": ["ask_person"],
    "contact": ["ask_person"],
    "other": ["ask_person"],  # a fault, a refusal, an abort: never retried
}


def attempt_cause(result: str, pile_moved: bool = False) -> str:
    """The cause of an attempt's end; a pile the camera saw change overrides only the causes that would try again."""
    if result == "placed":
        return "placed"
    cause = next((c for prefix, c in ATTEMPT_CAUSES if result.startswith(prefix)),
                 "no_progress" if result.startswith("stopped: ") and result.endswith(" attempts") else "other")
    # a contact's table is spent on this plan; only a pile that moved makes it stale (35 of 110 real attempts, none of them re-planned)
    return "scene_moved" if pile_moved and (RECOVERY[cause] != ["ask_person"] or cause == "contact") else cause


def obstacle_type(refused: list) -> str | None:
    """The obstacle type a set of refusals shows; a tangled pile outranks packed boxes (it has to be undone first)."""
    whys = [str(r.get("why", "")) for r in refused]
    return next((t for key, t in OBSTACLE_TYPES.items() if any(w.startswith(key) for w in whys)), None)


def diagnose(result: str, contact_z: float | None, surface_z: float | None, top_z: float | None,
             grasp_z: float | None, params=None) -> dict:
    """{cause, facts}: from the transfer result and the contact pose's FK height against the planned heights."""
    facts = {"result": result, "contact_z": contact_z, "surface_z": surface_z, "top_z": top_z, "grasp_z": grasp_z}
    if result == "empty":
        return {"cause": "empty", "facts": facts}
    if result != "contact" or None in (contact_z, top_z, grasp_z):
        return {"cause": "unknown", "facts": facts}
    near = prm.get(params, "diagnose.top_band_mm") / 1000
    if contact_z >= top_z - near:
        cause = "on_top"
    elif contact_z <= grasp_z + prm.get(params, "diagnose.surface_band_mm") / 1000:
        cause = "surface"
    else:
        cause = "beside"
    return {"cause": cause, "facts": facts}


def next_actions(cause: str, can: set, strategy: dict | None = None) -> list:
    """The table's actions for the cause that are possible now (can), in order; ask_person always ends the list."""
    order = (strategy or STRATEGY).get(cause, STRATEGY["unknown"])
    return [a for a in order if a in can or a == "ask_person"]
