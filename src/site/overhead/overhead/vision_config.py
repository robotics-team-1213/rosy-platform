"""Validated camera/map configuration with runtime secrets resolved by env name."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

import yaml

from overhead.project import CameraMap

_REQUIRED = {
    "source_id", "phone_token_env", "token_env", "fleet_base_url", "robot_ids",
    "map_id", "calibration_revision", "processor_revision", "corner_marker_ids",
    "corner_world_m", "robot_markers",
}
_ALLOWED = _REQUIRED | {"heading_edge"}
_ENV_NAME = re.compile(r"^[A-Z_][A-Z0-9_]*$")


@dataclass(frozen=True)
class VisionSourceConfig:
    camera: CameraMap
    phone_token: str
    sighting_token: str
    fleet_base_url: str


def load_vision_sources(path: Path | str, *, environ: Mapping[str, str] | None = None
                        ) -> list[VisionSourceConfig]:
    """Load non-secret map data and resolve camera/Fleet credentials from env."""

    config_path = Path(path)
    try:
        config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise ValueError(f"cannot read vision config {config_path}: {exc}") from exc
    if not isinstance(config, dict) or set(config) != {"sources"} or not isinstance(config["sources"], list):
        raise ValueError("vision config must contain only a sources list")
    if not config["sources"]:
        raise ValueError("vision config needs at least one source")

    env = os.environ if environ is None else environ
    configs = []
    all_tokens: set[str] = set()
    source_ids: set[str] = set()
    for index, row in enumerate(config["sources"]):
        if not isinstance(row, dict):
            raise ValueError(f"sources[{index}] must be a mapping")
        missing = _REQUIRED - row.keys()
        unknown = row.keys() - _ALLOWED
        if missing:
            raise ValueError(f"sources[{index}] missing fields: {', '.join(sorted(missing))}")
        if unknown:
            raise ValueError(f"sources[{index}] has unknown fields: {', '.join(sorted(unknown))}")
        secrets = []
        for field in ("phone_token_env", "token_env"):
            env_name = row[field]
            if not isinstance(env_name, str) or not _ENV_NAME.fullmatch(env_name):
                raise ValueError(f"sources[{index}].{field} must name an uppercase environment variable")
            token_value = env.get(env_name)
            if not isinstance(token_value, str) or not token_value:
                raise ValueError(f"vision token environment variable {env_name} is required")
            if token_value in all_tokens:
                raise ValueError("phone and Fleet source credentials must be distinct")
            all_tokens.add(token_value)
            secrets.append(token_value)
        robot_ids = row["robot_ids"]
        robot_markers = row["robot_markers"]
        if (not isinstance(robot_ids, list) or not robot_ids
                or not isinstance(robot_markers, dict)
                or set(robot_ids) != set(robot_markers)):
            raise ValueError(f"sources[{index}] robot_ids must match robot_markers")
        if not isinstance(row["fleet_base_url"], str) or not row["fleet_base_url"].strip():
            raise ValueError(f"sources[{index}].fleet_base_url is required")
        corners = row["corner_world_m"]
        if not isinstance(corners, list) or len(corners) != 4:
            raise ValueError(f"sources[{index}].corner_world_m must contain four x/y pairs")
        world_points = tuple(tuple(float(value) for value in point) for point in corners)
        heading_edge = tuple(row.get("heading_edge", (0, 1)))
        camera = CameraMap(
            source_id=row["source_id"],
            map_id=row["map_id"],
            calibration_revision=row["calibration_revision"],
            processor_revision=row["processor_revision"],
            corner_marker_ids=tuple(row["corner_marker_ids"]),
            corner_world_m=world_points,
            robot_markers=dict(robot_markers),
            heading_edge=heading_edge,
        )
        if camera.source_id in source_ids:
            raise ValueError("vision source ids must be unique")
        source_ids.add(camera.source_id)
        configs.append(VisionSourceConfig(camera, secrets[0], secrets[1], row["fleet_base_url"]))
    return configs
