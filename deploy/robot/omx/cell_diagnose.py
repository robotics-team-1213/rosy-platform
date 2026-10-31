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
    "unknown": ["observe_again", "ask_person"],
}


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
