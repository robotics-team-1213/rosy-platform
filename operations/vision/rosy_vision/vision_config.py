"""Validated camera/map configuration with runtime secrets resolved by env name."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

import yaml

from core_common.protocol.place_markers import check_place_marker_ids
from core_common.protocol.sightings import check_marker_yaw_offsets
from rosy_vision.project import CameraMap

_REQUIRED = {
    "source_id", "token_env", "fleet_base_url", "robot_ids",
    "map_id", "calibration_revision", "processor_revision",
    "corner_world_m", "robot_markers",
}
_ALLOWED = _REQUIRED | {"heading_edge", "phone_token_env", "credential",
                        "corner_marker_ids", "calibration_source",
                        "place_markers", "marker_yaw_offset_deg"}
CALIBRATION_SOURCES = ("corner_markers", "field_boundary")
CREDENTIAL_KINDS = ("static", "paired")
_ENV_NAME = re.compile(r"^[A-Z_][A-Z0-9_]*$")


@dataclass(frozen=True)
class VisionSourceConfig:
    camera: CameraMap
    # None for a ``paired`` source: its phone credential comes from Fleet pairing (D-341 6, 12).
    phone_token: str | None
    sighting_token: str
    fleet_base_url: str
    credential: str = "static"


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
        credential = row.get("credential", "static")
        if credential not in CREDENTIAL_KINDS:
            raise ValueError(f"sources[{index}].credential must be static or paired")
        if credential == "paired" and "phone_token_env" in row:
            raise ValueError(f"sources[{index}] is paired and must not set phone_token_env")
        if credential == "static" and "phone_token_env" not in row:
            raise ValueError(f"sources[{index}] is static and needs phone_token_env")
        secret_fields = ("phone_token_env", "token_env") if credential == "static" else ("token_env",)
        secrets = []
        for field in secret_fields:
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
                or any(not isinstance(robot_id, str) or not robot_id.strip() for robot_id in robot_ids)
                or len(set(robot_ids)) != len(robot_ids)
                or not isinstance(robot_markers, dict)
                or set(robot_markers) - set(robot_ids)):
            raise ValueError(f"sources[{index}] robot_markers must be a subset of unique robot_ids")
        if not isinstance(row["fleet_base_url"], str) or not row["fleet_base_url"].strip():
            raise ValueError(f"sources[{index}].fleet_base_url is required")
        corners = row["corner_world_m"]
        if not isinstance(corners, list) or len(corners) != 4:
            raise ValueError(f"sources[{index}].corner_world_m must contain four x/y pairs")
        world_points = tuple(tuple(float(value) for value in point) for point in corners)
        calibration_source = row.get("calibration_source", "corner_markers")
        if calibration_source not in CALIBRATION_SOURCES:
            raise ValueError(f"sources[{index}].calibration_source must be "
                             f"{' or '.join(CALIBRATION_SOURCES)}")
        if calibration_source == "field_boundary" and "corner_marker_ids" in row:
            raise ValueError(f"sources[{index}] is field_boundary and must not set corner_marker_ids")
        if calibration_source == "corner_markers" and "corner_marker_ids" not in row:
            raise ValueError(f"sources[{index}] needs corner_marker_ids for corner_markers")
        if calibration_source == "corner_markers":
            marker_ids = row["corner_marker_ids"]
            if (not isinstance(marker_ids, list) or len(marker_ids) != 4
                    or any(type(marker_id) is not int or marker_id < 0 for marker_id in marker_ids)):
                raise ValueError(f"sources[{index}].corner_marker_ids must contain four integer ids")
        heading_edge = tuple(row.get("heading_edge", (0, 1)))
        try:  # D-564
            place_markers = check_place_marker_ids(
                row.get("place_markers", []), corner_ids=row.get("corner_marker_ids"),
                robot_marker_ids=robot_markers.values())
        except ValueError as exc:
            raise ValueError(f"sources[{index}].{exc}") from exc
        try:  # D-587 4
            yaw_offsets = check_marker_yaw_offsets(row.get("marker_yaw_offset_deg"), robot_markers)
        except ValueError as exc:
            raise ValueError(f"sources[{index}].{exc}") from exc
        camera = CameraMap(
            source_id=row["source_id"],
            map_id=row["map_id"],
            calibration_revision=row["calibration_revision"],
            processor_revision=row["processor_revision"],
            corner_marker_ids=tuple(row["corner_marker_ids"]) if "corner_marker_ids" in row else None,
            corner_world_m=world_points,
            robot_markers=dict(robot_markers),
            heading_edge=heading_edge,
            calibration_source=calibration_source,
            place_markers=place_markers,
            marker_yaw_offset_deg=yaw_offsets,
        )
        if camera.source_id in source_ids:
            raise ValueError("vision source ids must be unique")
        source_ids.add(camera.source_id)
        phone_token = secrets[0] if credential == "static" else None
        configs.append(VisionSourceConfig(camera, phone_token, secrets[-1], row["fleet_base_url"],
                                          credential))
    return configs
