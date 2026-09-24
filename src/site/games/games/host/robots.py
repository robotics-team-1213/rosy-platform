"""CORE endpoints as match.yaml robot rows. No HTTP here."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from games.field import Field

FIRST_CONTACT_LINEAR_M = 0.10


@dataclass(frozen=True)
class RobotEndpoint:
    id: str
    url: str
    token: str
    aruco_id: int
    attacks: str


@dataclass(frozen=True)
class CameraConfig:
    index: int = 0
    hsv_low: tuple[int, int, int] = (5, 120, 80)
    hsv_high: tuple[int, int, int] = (25, 255, 255)
    corner_ids: tuple[int, int, int, int] = (10, 11, 12, 13)
    lost_hold_s: float = 0.5


@dataclass(frozen=True)
class GoalConfig:
    home_id: int = 20
    away_id: int = 21
    hsv_low: tuple[int, int, int] | None = None
    hsv_high: tuple[int, int, int] | None = None


@dataclass(frozen=True)
class MatchSetup:
    field: Field
    robots: tuple[RobotEndpoint, ...]
    game: str = "soccer"
    policy: str = "heuristic"
    linear: float = 0.08
    angular: float = 0.40
    camera: CameraConfig = CameraConfig()
    goals: GoalConfig = GoalConfig()


def load_match(path: Path) -> MatchSetup:
    path = Path(path)
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    overlay = path.with_name("match.local.yaml")
    if overlay.is_file():
        data = _merge(data, yaml.safe_load(overlay.read_text(encoding="utf-8")) or {})
    row = data.get("field") or {}
    robots = [
        RobotEndpoint(
            id=str(item["id"]),
            url=str(item["url"]).rstrip("/"),
            token=str(item.get("token") or ""),
            aruco_id=int(item["aruco_id"]),
            attacks=str(item["attacks"]),
        )
        for item in data.get("robots") or []
    ]
    if len(robots) != 2:
        raise ValueError(f"{path}: needs exactly two robots")
    home, away = _sides(robots)
    limits = data.get("limits") or {}
    field = Field(
        length_m=float(row["length_m"]),
        width_m=float(row["width_m"]),
        goal_width_m=float(row["goal_width_m"]),
        min_spacing_m=float(row["min_spacing_m"]),
        home_id=home.id,
        away_id=away.id,
    )
    cam = data.get("camera") or {}
    ball = data.get("ball") or {}
    watch = data.get("watchdog") or {}
    corners = tuple(int(v) for v in (cam.get("corners") or (10, 11, 12, 13)))
    if len(corners) != 4:
        raise ValueError(f"{path}: camera.corners needs four ArUco ids")
    hsv_low = tuple(int(v) for v in (ball.get("hsv_low") or (5, 120, 80)))
    hsv_high = tuple(int(v) for v in (ball.get("hsv_high") or (25, 255, 255)))
    goals = data.get("goals") or {}
    goal_hsv_low = goals.get("hsv_low")
    goal_hsv_high = goals.get("hsv_high")
    linear = float(limits.get("linear", 0.08))
    if linear > FIRST_CONTACT_LINEAR_M:
        raise ValueError(
            f"{path}: limits.linear {linear:.2f} exceeds first-contact {FIRST_CONTACT_LINEAR_M:.2f}"
        )
    return MatchSetup(
        field=field,
        robots=(home, away),
        game=str(data.get("game") or "soccer"),
        policy=str(data.get("policy") or "heuristic"),
        linear=linear,
        angular=float(limits.get("angular", 0.40)),
        camera=CameraConfig(
            index=int(cam.get("index", 0)),
            hsv_low=hsv_low,  # type: ignore[arg-type]
            hsv_high=hsv_high,  # type: ignore[arg-type]
            corner_ids=corners,  # type: ignore[arg-type]
            lost_hold_s=float(watch.get("lost_hold_s", 0.5)),
        ),
        goals=GoalConfig(
            home_id=int(goals.get("home_id", 20)),
            away_id=int(goals.get("away_id", 21)),
            hsv_low=tuple(int(v) for v in goal_hsv_low) if goal_hsv_low else None,  # type: ignore[arg-type]
            hsv_high=tuple(int(v) for v in goal_hsv_high) if goal_hsv_high else None,  # type: ignore[arg-type]
        ),
    )


def _sides(robots: list[RobotEndpoint]) -> tuple[RobotEndpoint, RobotEndpoint]:
    by_attack = {robot.attacks: robot for robot in robots}
    try:
        return by_attack["positive_x"], by_attack["negative_x"]
    except KeyError as exc:
        raise ValueError("robots need attacks positive_x and negative_x") from exc


def _merge(base: Any, over: Any) -> Any:
    if not isinstance(base, dict) or not isinstance(over, dict):
        return over
    out = dict(base)
    for key, value in over.items():
        if key == "robots" and isinstance(value, list) and isinstance(out.get("robots"), list):
            by_id = {row["id"]: dict(row) for row in out["robots"]}
            order = [row["id"] for row in out["robots"]]
            for row in value:
                rid = row["id"]
                by_id[rid] = {**by_id.get(rid, {}), **row}
                if rid not in order:
                    order.append(rid)
            out["robots"] = [by_id[rid] for rid in order]
        elif key in out and isinstance(out[key], dict) and isinstance(value, dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out
