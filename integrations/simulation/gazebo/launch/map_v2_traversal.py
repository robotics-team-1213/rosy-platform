"""ROS-free motion envelope for the map_260905 live mapping runner.

Distances are measured from the robot origin by the simulated lidar.  The
policy accounts for the footprint radius before it decides that clearance is
available.  It can reduce a simulation request only; it grants no physical
speed authority.
"""

from __future__ import annotations

import math


class TraversalLimits:
    def __init__(
        self,
        *,
        robot_diameter_m: float,
        max_linear_mps: float = 0.10,
        crawl_linear_mps: float = 0.02,
        clearance_margin_m: float = 0.010,
        open_clearance_span_m: float | None = None,
        recovery_buffer_ratio: float = 0.25,
    ) -> None:
        values = (
            robot_diameter_m,
            max_linear_mps,
            crawl_linear_mps,
            clearance_margin_m,
            recovery_buffer_ratio,
        )
        if not all(math.isfinite(value) and value >= 0.0 for value in values):
            raise ValueError("traversal limits must be finite and nonnegative")
        if robot_diameter_m <= 0.0 or max_linear_mps <= 0.0:
            raise ValueError("robot diameter and maximum speed must be positive")
        if crawl_linear_mps > max_linear_mps:
            raise ValueError("crawl speed cannot exceed the maximum")
        span = (
            robot_diameter_m * 0.75
            if open_clearance_span_m is None
            else open_clearance_span_m
        )
        if not math.isfinite(span) or span <= 0.0:
            raise ValueError("open clearance span must be positive and finite")
        self.robot_diameter_m = robot_diameter_m
        self.max_linear_mps = max_linear_mps
        self.crawl_linear_mps = crawl_linear_mps
        self.clearance_margin_m = clearance_margin_m
        self.open_clearance_span_m = span
        self.recovery_buffer_ratio = recovery_buffer_ratio

    @property
    def footprint_radius_m(self) -> float:
        return self.robot_diameter_m / 2.0

    @property
    def hard_clearance_m(self) -> float:
        return self.footprint_radius_m + self.clearance_margin_m


def _clearance(value: float) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number < 0.0:
        return None
    return number


def adaptive_speed(
    front_clearance_m: float,
    side_clearance_m: float,
    curvature_per_m: float,
    limits: TraversalLimits,
) -> float:
    """Return a continuous reducing-only linear cap.

    The closest front/side observation controls the clearance term.  Curvature
    can reduce that cap further but can never compensate for missing space.
    """
    front = _clearance(front_clearance_m)
    side = _clearance(side_clearance_m)
    try:
        curvature = abs(float(curvature_per_m))
    except (TypeError, ValueError):
        return 0.0
    if front is None or side is None or not math.isfinite(curvature):
        return 0.0
    available = min(front, side) - limits.hard_clearance_m
    if available <= 0.0:
        return 0.0
    fraction = min(1.0, available / limits.open_clearance_span_m)
    clearance_cap = limits.crawl_linear_mps + (
        limits.max_linear_mps - limits.crawl_linear_mps
    ) * fraction
    curvature_scale = 1.0 / (1.0 + curvature * limits.footprint_radius_m)
    return max(
        limits.crawl_linear_mps,
        min(limits.max_linear_mps, clearance_cap * curvature_scale),
    )


def robust_clearance(samples, lower_quantile: float = 0.10) -> float:
    """Return a conservative lower quantile of valid range samples.

    A single Gaussian low outlier must not turn a traversable narrow aisle
    into a false collision.  A real nearby surface occupies enough adjacent
    rays to remain inside the lower decile and is therefore preserved.
    """
    if not math.isfinite(lower_quantile) or not 0.0 <= lower_quantile <= 0.5:
        raise ValueError("lower_quantile must be finite and between 0 and 0.5")
    values = []
    for sample in samples:
        value = _clearance(sample)
        if value is not None:
            values.append(value)
    if not values:
        return math.nan
    values.sort()
    return values[int((len(values) - 1) * lower_quantile)]


def bidirectional_heading_error(error: float) -> tuple[float, float]:
    """Choose forward or reverse so a target behind does not force a U-turn."""
    if not math.isfinite(error):
        return 0.0, math.nan
    wrapped = math.atan2(math.sin(error), math.cos(error))
    # Keep ordinary right-angle corners in forward drive.  Reverse is for a
    # genuine U-turn request, where pivoting the body would consume the narrow
    # corridor's lateral margin.
    if abs(wrapped) <= 3.0 * math.pi / 4.0:
        return 1.0, wrapped
    reverse_error = math.atan2(
        math.sin(wrapped + math.pi), math.cos(wrapped + math.pi)
    )
    return -1.0, reverse_error


def recovery_reverse_distance(
    front_clearance_m: float,
    rear_clearance_m: float,
    turn_sweep_radius_m: float,
    limits: TraversalLimits,
) -> float:
    """Distance to back up before retrying a turn, derived from live space.

    The desired retreat creates a full turn-sweep clearance plus a
    footprint-scaled buffer.  Rear clearance bounds it, so there is no fixed
    8 cm command and no reverse motion when the rear safety envelope is full.
    """
    front = _clearance(front_clearance_m)
    rear = _clearance(rear_clearance_m)
    sweep = _clearance(turn_sweep_radius_m)
    if front is None or rear is None or sweep is None:
        return 0.0
    desired = max(0.0, sweep + limits.clearance_margin_m - front)
    desired += limits.robot_diameter_m * limits.recovery_buffer_ratio
    available = max(0.0, rear - limits.hard_clearance_m)
    return min(desired, available)


def turn_clearance_available(
    directional_clearances_m, limits: TraversalLimits
) -> bool:
    """Require the complete circular body envelope before an in-place turn."""
    values = [_clearance(value) for value in directional_clearances_m]
    return bool(values) and all(
        value is not None and value >= limits.hard_clearance_m
        for value in values
    )


def route_start_index(value: int, route_count: int) -> int:
    """Validate the first target without silently skipping route coverage."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("route start index must be an integer")
    if route_count <= 0 or value < 0 or value >= route_count:
        raise ValueError("route start index is outside the route")
    return value


def completion_exit_ready(
    done_since: float | None,
    now: float,
    dwell_s: float,
) -> bool:
    """Return true only after a measurable terminal-zero dwell."""
    if not math.isfinite(dwell_s) or dwell_s < 0.0:
        raise ValueError("completion zero dwell must be finite and nonnegative")
    if done_since is None:
        return False
    return now - done_since >= dwell_s


def mapping_route_world() -> tuple[tuple[float, float], ...]:
    """Collision-reviewed observation route for the exact v2 world.

    The route stays in the robot-reachable component.  It deliberately does
    not enter the lower-left sealed pocket.  The upper-left bay is reached by
    approaching the lower edge of its vertical wall, crossing at y=0.03 m,
    then opening the turn only after the body is through.  Every segment is
    sampled in tests against the 172 mm body envelope.
    """
    return (
        (-0.205, 0.275),
        (-0.400, 0.200),
        (-0.550, 0.150),
        (-0.620, 0.080),
        (-0.700, 0.030),
        (-0.840, 0.030),
        (-0.950, 0.120),
        (-1.050, 0.300),
        (-1.100, 0.480),
        (-1.200, 0.150),
        (-1.220, 0.030),
        (-1.220, -0.100),
        (-1.100, -0.300),
        (-1.220, -0.100),
        (-1.220, 0.030),
        (-1.200, 0.150),
        (-1.100, 0.480),
        (-1.050, 0.300),
        (-0.950, 0.120),
        (-0.840, 0.030),
        (-0.700, 0.030),
        (-0.620, 0.080),
        (-0.550, 0.150),
        (-0.400, 0.200),
        (-0.100, -0.150),
        (0.300, -0.150),
        (0.300, -0.450),
        (1.200, -0.450),
        (1.200, 0.450),
        (1.200, -0.450),
        (0.300, -0.450),
        (0.300, -0.150),
        (0.300, 0.150),
        (0.600, 0.150),
        (0.600, 0.450),
        (0.900, 0.450),
        (0.900, -0.100),
        (0.900, 0.450),
        (0.600, 0.450),
        (0.600, 0.150),
        (0.300, 0.150),
        (0.300, -0.150),
        (-0.100, -0.150),
        (-0.320, -0.200),
        (-0.320, -0.450),
        (-0.200, -0.500),
        (-0.040, -0.480),
        (-0.200, -0.500),
        (-0.320, -0.450),
        (-0.320, -0.200),
        (-0.100, -0.150),
        (-0.205, 0.275),
    )


def mapping_observation_indices(
    route: tuple[tuple[float, float], ...],
) -> tuple[int, ...]:
    """Return the first deep viewpoint in each otherwise occluded pocket."""
    targets = (
        (-1.100, 0.480),
        (-1.100, -0.300),
        (0.900, -0.100),
        (-0.040, -0.480),
    )
    return tuple(route.index(point) for point in targets)
