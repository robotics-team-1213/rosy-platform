"""cell.yaml (schema rosy_cell.cell/2) -> CellConfig. Frames are kept as taught points and rebuilt here."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from . import SCHEMA_CELL, fields
from .fields import FieldError
from .geometry import Frame, FrameError
from .recipe import content_hash

_REQUIRED = ("schema", "frame_rules", "frames", "stations", "home", "kinematics_revision", "approach_clearance_m")
_RULES = ("min_span_m", "min_angle_deg", "max_tilt_deg")
_POINTS = ("origin", "x_point", "plane_point")
_STATION = ("frame", "x", "y", "z", "yaw")
_HOME = ("x", "y", "z", "yaw")


class CellError(ValueError):
    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = tuple(problems)


@dataclass(frozen=True)
class Pose:
    """A TCP pose in the robot base frame (x, y, z in m, yaw in rad)."""

    x: float
    y: float
    z: float
    yaw: float


@dataclass(frozen=True)
class Station:
    frame: str
    x: float
    y: float
    z: float
    yaw: float


@dataclass(frozen=True)
class CellConfig:
    frames: Mapping[str, Frame]
    stations: Mapping[str, Station]
    home: Pose  # tool-down TCP pose in the base frame; a pose, not a frame, and not an obstacle
    kinematics_revision: str
    approach_clearance_m: float
    content_hash: str

    def station_pose(self, station_id: str) -> tuple[float, float, float, float]:
        s = self.stations[station_id]
        frame = self.frames[s.frame]
        x, y, z = frame.to_base((s.x, s.y, s.z))
        return (x, y, z, frame.yaw_to_base(s.yaw))


def _rules(value: object, field: str) -> dict[str, float]:
    d = fields.mapping(value, field, _RULES)
    rules = {k: fields.positive(d[k], f"{field}.{k}") for k in _RULES[:2]}
    rules["max_tilt_deg"] = fields.non_negative(d["max_tilt_deg"], f"{field}.max_tilt_deg")  # 0 = must be level
    return rules


def _id(value: object, field: str) -> str:
    return fields.text(value, f"{field}: key {value!r}")


def _taught(value: object, field: str) -> dict[str, tuple]:
    if not isinstance(value, dict) or not value:
        raise FieldError(f"{field} must be a non-empty mapping of frame id to taught points")
    out = {}
    for frame_id, raw in value.items():
        f = f"{field}.{_id(frame_id, field)}"
        d = fields.mapping(raw, f, _POINTS)
        out[frame_id] = tuple(fields.point(d[k], f"{f}.{k}") for k in _POINTS)
    return out


def _stations(value: object, field: str) -> dict[str, Station]:
    if not isinstance(value, dict):
        raise FieldError(f"{field} must be a mapping")
    out = {}
    for station_id, raw in value.items():
        f = f"{field}.{_id(station_id, field)}"
        d = fields.mapping(raw, f, _STATION)
        out[station_id] = Station(
            fields.text(d["frame"], f"{f}.frame"), *(fields.number(d[k], f"{f}.{k}") for k in _STATION[1:])
        )
    return out


def _home(value: object, field: str) -> Pose:
    d = fields.mapping(value, field, _HOME)
    return Pose(*(fields.number(d[k], f"{field}.{k}") for k in _HOME))


def _revision(value: object, field: str) -> str:
    s = fields.text(value, field)
    if not s or s != s.strip():
        raise FieldError(f"{field} must be non-empty without leading or trailing whitespace")
    return s


def load_cell(text: str) -> CellConfig:
    try:
        data = fields.parse(text, "cell config")
    except FieldError as exc:
        raise CellError([str(exc)]) from None
    problems = fields.key_problems(data, "cell", _REQUIRED)

    def read(key: str, parse: Callable[[object, str], Any]) -> Any:
        if key not in data:
            return None  # already reported by key_problems
        try:
            return parse(data[key], key)
        except FieldError as exc:
            problems.append(str(exc))
            return None

    if "schema" in data and data["schema"] != SCHEMA_CELL:
        problems.append(f"schema must be {SCHEMA_CELL}")
    rules = read("frame_rules", _rules)
    taught = read("frames", _taught)
    stations = read("stations", _stations)
    home = read("home", _home)
    revision = read("kinematics_revision", _revision)
    clearance = read("approach_clearance_m", fields.positive)

    frames: dict[str, Frame] = {}
    if rules is not None and taught is not None:
        for frame_id, points in taught.items():
            try:
                frame = Frame.from_three_points(
                    *points, min_span_m=rules["min_span_m"], min_angle_deg=rules["min_angle_deg"]
                )
            except FrameError as exc:
                problems.append(f"frame {frame_id}: {exc}")
                continue
            if frame.tilt_deg() > rules["max_tilt_deg"]:
                problems.append(f"frame {frame_id}: tilt {frame.tilt_deg():.1f} deg exceeds max_tilt_deg")
            frames[frame_id] = frame
    if stations is not None and taught is not None:
        problems += [f"station {k}: unknown frame {s.frame!r}" for k, s in stations.items() if s.frame not in taught]
    if problems:
        raise CellError(problems)
    return CellConfig(
        MappingProxyType(frames), MappingProxyType(stations), home, revision, clearance, content_hash(data)
    )
