"""cell.yaml (schema rosy_cell.cell/1) -> CellConfig. Frames are kept as taught points and rebuilt here."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import yaml

from . import SCHEMA_CELL
from .geometry import Frame, FrameError
from .recipe import content_hash


class CellError(ValueError):
    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = tuple(problems)


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
    approach_clearance_m: float
    content_hash: str

    def station_pose(self, station_id: str) -> tuple[float, float, float, float]:
        s = self.stations[station_id]
        frame = self.frames[s.frame]
        x, y, z = frame.to_base((s.x, s.y, s.z))
        return (x, y, z, frame.yaw_to_base(s.yaw))


def load_cell(text: str) -> CellConfig:
    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise CellError(["cell config must be a mapping"])
    problems: list[str] = []
    if data.get("schema") != SCHEMA_CELL:
        problems.append(f"schema must be {SCHEMA_CELL}")
    try:
        rules = data["frame_rules"]
        frames: dict[str, Frame] = {}
        for frame_id, pts in data["frames"].items():
            try:
                frame = Frame.from_three_points(
                    tuple(pts["origin"]),
                    tuple(pts["x_point"]),
                    tuple(pts["plane_point"]),
                    min_span_m=float(rules["min_span_m"]),
                    min_angle_deg=float(rules["min_angle_deg"]),
                )
            except FrameError as exc:
                problems.append(f"frame {frame_id}: {exc}")
                continue
            if frame.tilt_deg() > float(rules["max_tilt_deg"]):
                problems.append(f"frame {frame_id}: tilt {frame.tilt_deg():.1f} deg exceeds max_tilt_deg")
            frames[str(frame_id)] = frame
        stations = {str(k): Station(**v) for k, v in data["stations"].items()}
        clearance = float(data["approach_clearance_m"])
    except (KeyError, TypeError, ValueError) as exc:
        raise CellError(problems + [f"invalid cell field: {exc}"]) from None
    problems += [
        f"station {k}: unknown frame {s.frame!r}"
        for k, s in stations.items()
        if s.frame not in frames and s.frame not in data["frames"]
    ]
    if clearance <= 0:
        problems.append("approach_clearance_m must be positive")
    if problems:
        raise CellError(problems)
    return CellConfig(frames, stations, clearance, content_hash(data))
