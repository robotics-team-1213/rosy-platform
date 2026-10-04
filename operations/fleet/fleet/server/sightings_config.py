"""Load source-scoped sighting permissions from non-secret site YAML."""

from __future__ import annotations

import math
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
    "corner_world_m", "robot_markers", "heading_edge", "credential",
}
CREDENTIAL_KINDS = ("static", "paired")
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
        credential = row.get("credential", "static")
        if credential not in CREDENTIAL_KINDS:
            raise ValueError(f"sources[{index}].credential must be static or paired")
        # D-341 6. Fleet never reads the phone token; an implicit static source keeps the
        # pre-D-341 shape (Vision still requires its phone_token_env), an explicit one is checked.
        if credential == "paired" and "phone_token_env" in row:
            raise ValueError(f"sources[{index}] is paired and must not set phone_token_env")
        if "credential" in row and credential == "static" and "phone_token_env" not in row:
            raise ValueError(f"sources[{index}] is static and needs phone_token_env")
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
        corner_world_m = None
        if "corner_world_m" in row:
            corners = row["corner_world_m"]
            if (not isinstance(corners, list) or len(corners) != 4
                    or any(not isinstance(point, list) or len(point) != 2
                           or any(isinstance(v, bool) or not isinstance(v, (int, float))
                                  or not math.isfinite(v) for v in point)
                           for point in corners)):
                raise ValueError(f"sources[{index}].corner_world_m must contain four finite x/y pairs")
            corner_world_m = tuple((float(x), float(y)) for x, y in corners)
            if len(set(corner_world_m)) != 4:
                raise ValueError(f"sources[{index}].corner_world_m points must be distinct")
        markers = row.get("robot_markers", {})
        if (not isinstance(markers, dict)
                or any(not isinstance(robot_id, str) or not robot_id
                       or type(marker_id) is not int or marker_id < 0
                       for robot_id, marker_id in markers.items())):
            raise ValueError(f"sources[{index}].robot_markers must map robot ids to marker ids")
        if set(markers) - set(robot_ids):
            raise ValueError(f"sources[{index}].robot_markers names robots outside robot_ids: "
                             f"{', '.join(sorted(set(markers) - set(robot_ids)))}")
        if len(set(markers.values())) != len(markers):
            raise ValueError(f"sources[{index}].robot_markers must give each robot a distinct marker id")
        if set(markers.values()) & set(corner_ids):
            raise ValueError(f"sources[{index}].robot_markers must not reuse corner_marker_ids")
        sources.append(SightingSource(
            source_id=row["source_id"],
            token=token,
            robot_ids=tuple(robot_ids),
            map_id=row["map_id"],
            calibration_revision=row["calibration_revision"],
            corner_marker_ids=tuple(corner_ids),
            corner_world_m=corner_world_m,
            robot_markers=tuple(markers.items()),
            credential=credential,
        ))
    if len({source.source_id for source in sources}) != len(sources):
        raise ValueError("sighting source ids must be unique")
    # The site map shows one rectangle per map id, so sources on one map must agree on it.
    rectangles: dict[str, SightingSource] = {}
    for source in sources:
        if source.corner_world_m is None:
            continue
        first = rectangles.setdefault(source.map_id, source)
        if first.corner_world_m != source.corner_world_m:
            raise ValueError(f"sources {first.source_id} and {source.source_id} share map_id "
                             f"{source.map_id} but differ in corner_world_m")
    return sources
