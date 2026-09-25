"""ROS-free navigation readiness gate.

The gate is deliberately independent of ROS message types.  The bridge feeds
it lifecycle and adapter observations, while command and navigation managers
only ask whether motion is currently authorised.  A required component that
has never reported active, or whose report is stale, keeps the robot in HOLD.
"""

from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass
from typing import Iterable, Optional


COMPONENTS = (
    "amcl",
    "map_server",
    "slam_toolbox",
    "controller_server",
    "local_costmap",
    "global_costmap",
    "motor_adapter",
)


@dataclass(frozen=True)
class ReadinessSnapshot:
    required: bool
    ready: bool
    missing: tuple[str, ...]
    reason: str
    observed_at: dict[str, float]


class NavigationReadinessGate:
    """Track the minimum runtime evidence needed before base motion."""

    def __init__(
        self,
        *,
        required: bool = False,
        stale_after_s: float = 2.0,
        monotonic=time.monotonic,
        required_components: Optional[Iterable[str]] = None,
    ) -> None:
        if type(required) is not bool:
            raise ValueError("navigation readiness required must be a boolean")
        try:
            stale_after_s = float(stale_after_s)
        except (TypeError, ValueError) as exc:
            raise ValueError("navigation readiness stale_after_s must be finite and positive") from exc
        if not math.isfinite(stale_after_s) or stale_after_s <= 0.0:
            raise ValueError("navigation readiness stale_after_s must be finite and positive")
        if isinstance(required_components, (str, bytes)):
            raise ValueError("navigation readiness components must be a sequence")
        selected = COMPONENTS if required_components is None else tuple(required_components)
        unknown = set(selected) - set(COMPONENTS)
        if unknown or not selected:
            raise ValueError(f"unknown navigation readiness components: {sorted(unknown)}")
        self.required = required
        self.stale_after_s = stale_after_s
        self._monotonic = monotonic
        self._required_components = selected
        self._observed_at: dict[str, float] = {}
        self._active: dict[str, bool] = {component: False for component in COMPONENTS}
        self._leased: dict[str, bool] = {component: False for component in COMPONENTS}
        self._lock = threading.Lock()

    @property
    def required_components(self) -> tuple[str, ...]:
        return self._required_components

    def observe(
        self,
        component: str,
        active: bool,
        now: Optional[float] = None,
        *,
        lease: bool = False,
    ) -> None:
        """Record one lifecycle/adapter state observation.

        Inactive observations are kept with their timestamp so a diagnostic
        can distinguish a live inactive node from a component that disappeared.
        """
        if component not in COMPONENTS:
            raise ValueError(f"unknown navigation readiness component: {component}")
        if type(active) is not bool:
            raise ValueError("navigation readiness active must be a boolean")
        if type(lease) is not bool:
            raise ValueError("navigation readiness lease must be a boolean")
        stamp = self._monotonic() if now is None else float(now)
        if not math.isfinite(stamp):
            raise ValueError("navigation readiness timestamp must be finite")
        with self._lock:
            self._active[component] = active
            self._observed_at[component] = stamp
            self._leased[component] = lease

    def snapshot(self, now: Optional[float] = None) -> ReadinessSnapshot:
        current = self._monotonic() if now is None else float(now)
        with self._lock:
            observed = dict(self._observed_at)
            active = dict(self._active)
            leased = dict(self._leased)
        if not self.required:
            return ReadinessSnapshot(False, True, (), "disabled", observed)

        missing: list[str] = []
        for component in self._required_components:
            stamp = observed.get(component)
            fresh = (
                stamp is not None
                and math.isfinite(stamp)
                and (not leased.get(component, False)
                     or 0.0 <= current - stamp <= self.stale_after_s)
            )
            if not active.get(component, False) or not fresh:
                missing.append(component)
        if missing:
            return ReadinessSnapshot(
                True,
                False,
                tuple(missing),
                "missing_or_stale:" + ",".join(missing),
                observed,
            )
        return ReadinessSnapshot(True, True, (), "ready", observed)

    def is_ready(self, now: Optional[float] = None) -> bool:
        return self.snapshot(now).ready
