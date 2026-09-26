"""Pixel detections to pitch Observation. No OpenCV."""

from __future__ import annotations

from games.field import Field, Pose2D
from games.field.homography import Homography
from games.game import Observation

Point = tuple[float, float]


def observation_from_pixels(
    *,
    field: Field,
    homography: Homography | None,
    ball_uv: Point | None,
    robots: dict[str, tuple[Point, Point]],
    roster: tuple[str, str],
    home_goal: tuple[tuple[float, float], ...] | None = None,
    away_goal: tuple[tuple[float, float], ...] | None = None,
) -> Observation:
    if homography is None:
        return Observation(
            t=0.0,
            ball=None,
            robots={},
            lost_ball=True,
            lost_robots=frozenset(roster),
        )
    ball = None
    lost_ball = ball_uv is None
    if ball_uv is not None:
        x, y = homography.apply(*ball_uv)
        ball = Pose2D(x, y, 0.0)
    poses: dict[str, Pose2D] = {}
    lost: list[str] = []
    for robot_id in roster:
        pair = robots.get(robot_id)
        if pair is None:
            lost.append(robot_id)
            continue
        center, tip = pair
        x, y = homography.apply(*center)
        yaw = homography.yaw(center, tip)
        poses[robot_id] = Pose2D(x, y, yaw)
    return Observation(
        t=0.0,
        ball=ball,
        robots=poses,
        lost_ball=lost_ball,
        lost_robots=frozenset(lost),
        home_goal=home_goal,
        away_goal=away_goal,
    )
