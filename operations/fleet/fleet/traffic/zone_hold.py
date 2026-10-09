"""D-517 3 (2026-10-09 signal SIM): where a robot can stand outside every site zone.

A robot standing inside a zone keeps it from every other robot (``TrafficService._under`` pins what a
standing body covers), and a D-525 signal never gives that zone its next green.
"""

from __future__ import annotations

from typing import Optional

from fleet.routing.execute import arc_id

#: Scan step back along the lane.
STEP_M = 0.02


def hold_back_m(traffic, segment: dict) -> Optional[float]:
    """Metres before ``segment``'s end where a standing robot is clear of every zone of ``traffic``
    (a ``TrafficService``), 0 at the end itself, scanning back to ``s_from``; None when there is no such
    point (the segment runs inside a zone). No site zones: 0."""
    active = traffic._store.active()
    layout = traffic._layout_for(active) if traffic._zones else None
    arc = active[2].arcs.get(arc_id(segment)) if layout is not None else None
    if arc is None:
        return 0.0
    for k in range(int((segment["s_to"] - segment["s_from"]) / STEP_M + 1e-6) + 1):
        pose = arc.point_at(segment["s_to"] - k * STEP_M)
        if not traffic._zones.keys() & traffic._under(layout, active[2], pose).keys():
            return k * STEP_M
    return None
