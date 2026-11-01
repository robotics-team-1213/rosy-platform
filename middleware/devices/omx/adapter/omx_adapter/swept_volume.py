"""Capsule envelope of the OMX-F links for one joint vector, in the arm base frame.

Shared by the G1 layout audit (swept separation between arms) and the chunk planner's keep-out check.
The radii are generous envelopes of the links, not a mesh.
"""
from __future__ import annotations

# XL430 body 28.5 x 34 mm -> half diagonal ~22 mm, rounded up.
LINK_RADIUS_M = 0.025
# Fingers open to the profile's 1.0 rad (~50 mm jaw).
GRIPPER_RADIUS_M = 0.030


def capsules(kin, joints, *, fingertip_m: float, item: tuple[float, float] | None = None,
             gripper_radius_m: float = GRIPPER_RADIUS_M) -> list[tuple]:
    """(a, b, radius): shoulder-elbow, elbow-wrist, wrist-fingertips and, with ``item`` = (hang, radius),
    the held item hanging from the TCP along the tool axis."""
    points, approach = kin.link_points(joints, fingertip_m)
    shoulder, elbow, wrist, _joint5, tcp, tip = points
    out = [(shoulder, elbow, LINK_RADIUS_M), (elbow, wrist, LINK_RADIUS_M), (wrist, tip, gripper_radius_m)]
    if item is not None:
        hang, radius = item
        out.append((tcp, tuple(p + a * hang for p, a in zip(tcp, approach)), radius))
    return out
