"""Idle-and-stopped guard before a site map activation (host restarts navigation on the new map)."""

from __future__ import annotations

import time
from typing import Any

from core_common.protocol.schemas import NavigationState

from core_features.command.arbitration import Mode


class SiteMapRefused(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def require_stopped_for_site_map(svc: Any, *, still: bool, stale_velocity_s: float = 0.5, settle_s: float = 2.0):
    """Raise SiteMapRefused unless CORE is idle and fresh zero velocity held `settle_s`; returns (zero_since, now)."""
    if svc.safety.estop:
        raise SiteMapRefused("ESTOP_ACTIVE", "release E-stop before site map activation")
    if svc.modes.mode is not Mode.IDLE:
        raise SiteMapRefused("MODE_CONFLICT", "select IDLE mode before site map activation")
    if svc.calibration.current() is not None:
        raise SiteMapRefused("CALIBRATION_ACTIVE", "finish calibration before site map activation")
    if getattr(svc, "trip_lease", None) is not None and svc.trip_lease.current() is not None:
        raise SiteMapRefused("TRIP_LEASE_ACTIVE", "release active trip lease before site map activation")
    goal_active = (
        getattr(svc.nav, "nav_state", None) in (NavigationState.PLANNING, NavigationState.NAVIGATING)
        or any(bool(getattr(getattr(svc, name), "active", False)) for name in ("line_follow", "docking", "swarm"))
    )
    vel_age = svc.state.received_age("velocity")
    zero_since = getattr(svc.state, "zero_velocity_since", None)
    now = getattr(svc.state, "_monotonic", time.monotonic)()
    if (goal_active or vel_age is None or vel_age > stale_velocity_s or zero_since is None
            or (now - zero_since) < settle_s or not still):
        raise SiteMapRefused("ROBOT_NOT_STOPPED",
                             f"robot must be idle with fresh zero velocity >= {settle_s:.1f} s before site map activation")
    return zero_since, now
