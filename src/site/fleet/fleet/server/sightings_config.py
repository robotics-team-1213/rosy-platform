"""Load source-scoped sighting permissions from non-secret site YAML."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Mapping

import yaml

from fleet.server.sightings import SightingSource

_REQUIRED = {
    "source_id", "token_env", "robot_ids", "map_id",
    "calibration_revision", "corner_marker_ids",
}
_ALLOWED = _REQUIRED | {
    "phone_token_env", "fleet_base_url", "processor_revision",
    "corner_world_m", "robot_markers", "heading_edge",
}
_ENV_NAME = re.compile(r"^[A-Z_][A-Z0-9_]*$")


def load_sighting_sources(path: Path | str, *, environ: Mapping[str, str] | None = None
                          ) -> list[SightingSource]:
    """Resolve secret values from the process environment, never from YAML."""

    source_path = Path(path)
    try:
        config = yaml.safe_load(source_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise ValueError(f"cannot read sighting config {source_path}: {exc}") from exc
    if not isinstance(config, dict) or set(config) != {"sources"} or not isinstance(config["sources"], list):
        raise ValueError("sighting config must contain only a sources list")
    if not config["sources"]:
        raise ValueError("sighting config needs at least one source")

    env = os.environ if environ is None else environ
    sources = []
    for index, row in enumerate(config["sources"]):
        if not isinstance(row, dict):
            raise ValueError(f"sources[{index}] must be a mapping")
        missing = _REQUIRED - row.keys()
        unknown = row.keys() - _ALLOWED
        if missing:
            raise ValueError(f"sources[{index}] missing fields: {', '.join(sorted(missing))}")
        if unknown:
            raise ValueError(f"sources[{index}] has unknown fields: {', '.join(sorted(unknown))}")
        env_name = row["token_env"]
        if not isinstance(env_name, str) or not _ENV_NAME.fullmatch(env_name):
            raise ValueError(f"sources[{index}].token_env must name an uppercase environment variable")
        token = env.get(env_name)
        if not isinstance(token, str) or not token:
            raise ValueError(f"sighting token environment variable {env_name} is required")
        robot_ids = row["robot_ids"]
        corner_ids = row["corner_marker_ids"]
        if (not isinstance(robot_ids, list) or not robot_ids
                or any(not isinstance(robot_id, str) or not robot_id for robot_id in robot_ids)):
            raise ValueError(f"sources[{index}].robot_ids must be a non-empty string list")
        if (not isinstance(corner_ids, list) or len(corner_ids) != 4
                or any(type(marker_id) is not int or marker_id < 0 for marker_id in corner_ids)):
            raise ValueError(f"sources[{index}].corner_marker_ids must contain four integer ids")
        sources.append(SightingSource(
            source_id=row["source_id"],
            token=token,
            robot_ids=tuple(robot_ids),
            map_id=row["map_id"],
            calibration_revision=row["calibration_revision"],
            corner_marker_ids=tuple(corner_ids),
        ))
    if len({source.source_id for source in sources}) != len(sources):
        raise ValueError("sighting source ids must be unique")
    return sources
