"""D-489 3·4 / D-490 3: time cost, turn angle and class, and the A* bound."""

from __future__ import annotations

import math
from dataclasses import dataclass, fields
from typing import Mapping

STRAIGHT, LEFT, RIGHT, UTURN, STOP = "straight", "left", "right", "uturn", "stop"


@dataclass(frozen=True)
class RoutingConfig:
    """Site config ``fleet.routing`` (D-490 3). Out-of-range values are refused at start-up."""

    turn_cost_s: float = 2.0
    uturn_cost_s: float = 6.0
    place_pass_cost_s: float = 0.5
    straight_max_deg: float = 20.0
    uturn_min_deg: float = 135.0
    heading_tol_deg: float = 60.0
    snap_width_factor: float = 2.0

    def __post_init__(self) -> None:
        for item in fields(self):
            value = getattr(self, item.name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError(f"fleet.routing.{item.name} must be a finite number")
        for name in ("turn_cost_s", "uturn_cost_s", "place_pass_cost_s"):
            if not 0.0 <= getattr(self, name) <= 600.0:
                raise ValueError(f"fleet.routing.{name} must be within 0..600 s")
        if not 0.0 <= self.straight_max_deg < self.uturn_min_deg <= 180.0:
            raise ValueError("fleet.routing needs 0 <= straight_max_deg < uturn_min_deg <= 180")
        if not 0.0 < self.heading_tol_deg <= 180.0:
            raise ValueError("fleet.routing.heading_tol_deg must be within (0, 180]")
        if not 0.0 < self.snap_width_factor <= 10.0:
            raise ValueError("fleet.routing.snap_width_factor must be within (0, 10]")

    @classmethod
    def from_mapping(cls, raw: Mapping | None) -> "RoutingConfig":
        raw = dict(raw or {})
        unknown = set(raw) - {item.name for item in fields(cls)}
        if unknown:
            raise ValueError(f"fleet.routing has unknown keys: {sorted(unknown)}")
        return cls(**raw)


def wrap(angle: float) -> float:
    return (angle + math.pi) % (2.0 * math.pi) - math.pi


def turn_deg(tangent_in: float, tangent_out: float) -> float:
    """Signed heading change; positive is a left (counter-clockwise) turn."""
    return math.degrees(wrap(tangent_out - tangent_in))


def classify(theta_deg: float, config: RoutingConfig) -> str:
    size = abs(theta_deg)
    if size <= config.straight_max_deg:
        return STRAIGHT
    if size > config.uturn_min_deg:
        return UTURN
    return LEFT if theta_deg > 0 else RIGHT


def transition_cost(theta_deg: float, place_kind: str, config: RoutingConfig) -> float | None:
    """Turn cost plus the pass cost of the place; None when the U-turn is not allowed there."""
    kind = classify(theta_deg, config)
    if kind == UTURN:
        if place_kind != "turnaround":
            return None
        return config.uturn_cost_s + config.place_pass_cost_s
    return (config.turn_cost_s if kind in (LEFT, RIGHT) else 0.0) + config.place_pass_cost_s


def speed(cap_mps: float, max_speed_mps: float | None, speed_cap: float | None) -> float:
    return min(v for v in (cap_mps, max_speed_mps, speed_cap) if v is not None)


def heuristic(xy: tuple[float, float], goal_xy: tuple[float, float], vmax: float) -> float:
    """Straight distance at the fastest allowed speed: a lower bound of any route's time."""
    return math.dist(xy, goal_xy) / vmax
