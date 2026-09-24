"""Pitch numbers. No camera, no ROS."""

from __future__ import annotations

from dataclasses import dataclass, replace

Polygon = tuple[tuple[float, float], ...]


def in_polygon(x: float, y: float, vertices: Polygon) -> bool:
    n = len(vertices)
    if n < 3:
        return False
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = vertices[i]
        xj, yj = vertices[j]
        if (yi > y) != (yj > y):
            denom = yj - yi
            if abs(denom) > 1e-12:
                x_int = (xj - xi) * (y - yi) / denom + xi
                if x < x_int:
                    inside = not inside
        j = i
    return inside


@dataclass(frozen=True)
class Field:
    length_m: float = 1.8
    width_m: float = 1.2
    goal_width_m: float = 0.35
    home_id: str = "rosy_01"
    away_id: str = "rosy_02"
    kickoff_radius_m: float = 0.12
    min_spacing_m: float = 0.35
    home_goal: Polygon | None = None
    away_goal: Polygon | None = None

    def in_bounds(self, x: float, y: float) -> bool:
        return abs(x) <= self.length_m / 2 and abs(y) <= self.width_m / 2

    def in_home_goal(self, x: float, y: float) -> bool:
        if self.home_goal is not None:
            return in_polygon(x, y, self.home_goal)
        return x <= -self.length_m / 2 and abs(y) <= self.goal_width_m / 2

    def in_away_goal(self, x: float, y: float) -> bool:
        if self.away_goal is not None:
            return in_polygon(x, y, self.away_goal)
        return x >= self.length_m / 2 and abs(y) <= self.goal_width_m / 2

    def with_goals(
        self,
        home: Polygon | None = None,
        away: Polygon | None = None,
    ) -> Field:
        return replace(self, home_goal=home, away_goal=away)

    def opponent_goal_x(self, robot_id: str) -> float:
        if robot_id == self.home_id:
            return self.length_m / 2
        return -self.length_m / 2


def goal_mouth(
    x: float,
    y: float,
    *,
    home: bool,
    half_width: float,
    depth: float = 0.3,
) -> Polygon:
    y0, y1 = y - half_width, y + half_width
    if home:
        return ((x, y0), (x - depth, y0), (x - depth, y1), (x, y1))
    return ((x, y0), (x + depth, y0), (x + depth, y1), (x, y1))
