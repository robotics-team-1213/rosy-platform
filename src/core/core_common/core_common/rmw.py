"""Apply CycloneDDS before rclpy.init (D-121). Does not import rclpy."""

from __future__ import annotations

from typing import MutableMapping

REQUIRED_RMW = "rmw_cyclonedds_cpp"


def cyclone_overlay_patch() -> dict:
    """D-30 overlay intent. Next boot still goes through apply_cyclone_rmw."""
    return {"dds": {"rmw": REQUIRED_RMW}}


def apply_cyclone_rmw(env: MutableMapping[str, str]) -> str:
    """Put Cyclone in this process env before ``rclpy.init`` (D-122).

    Empty and foreign values are corrected. Changing env after init does not
    retarget an already loaded RMW — bounce the CORE process, not the kernel.
    """
    current = str(env.get("RMW_IMPLEMENTATION") or "").strip()
    if current != REQUIRED_RMW:
        env["RMW_IMPLEMENTATION"] = REQUIRED_RMW
    return REQUIRED_RMW
