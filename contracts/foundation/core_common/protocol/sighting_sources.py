"""Shared non-secret site-camera configuration checks for Fleet and Vision."""

import math
import re


REQUIRED = {"source_id", "token_env", "robot_ids", "map_id", "calibration_revision"}
ALLOWED = REQUIRED | {
    "phone_token_env", "fleet_base_url", "processor_revision", "corner_marker_ids",
    "corner_world_m", "robot_markers", "heading_edge", "credential", "calibration_source",
    "place_markers", "marker_yaw_offset_deg", "auto_tune",
}
CREDENTIAL_KINDS = ("static", "paired")
CALIBRATION_SOURCES = ("corner_markers", "field_boundary")
_ENV_NAME = re.compile(r"^[A-Z_][A-Z0-9_]*$")


def validate_sighting_config(config: object) -> None:
    if (not isinstance(config, dict) or "sources" not in config
            or set(config) - {"sources", "identity"} or not isinstance(config["sources"], list)):
        raise ValueError("sighting config must contain a sources list and optionally identity")
    if not config["sources"]:
        raise ValueError("sighting config needs at least one source")
    for index, row in enumerate(config["sources"]):
        if not isinstance(row, dict):
            raise ValueError(f"sources[{index}] must be a mapping")
        missing = REQUIRED - row.keys()
        unknown = row.keys() - ALLOWED
        if missing:
            raise ValueError(f"sources[{index}] missing fields: {', '.join(sorted(missing))}")
        if unknown:
            raise ValueError(f"sources[{index}] has unknown fields: {', '.join(sorted(unknown))}")
        credential = row.get("credential", "static")
        if credential not in CREDENTIAL_KINDS:
            raise ValueError(f"sources[{index}].credential must be static or paired")
        if credential == "paired" and "phone_token_env" in row:
            raise ValueError(f"sources[{index}] is paired and must not set phone_token_env")
        if "credential" in row and credential == "static" and "phone_token_env" not in row:
            raise ValueError(f"sources[{index}] is static and needs phone_token_env")
        env_name = row["token_env"]
        if not isinstance(env_name, str) or not _ENV_NAME.fullmatch(env_name):
            raise ValueError(f"sources[{index}].token_env must name an uppercase environment variable")
        robot_ids = row["robot_ids"]
        follow = robot_ids == "enrolled"
        if not follow and (not isinstance(robot_ids, list) or not robot_ids
                           or any(not isinstance(robot_id, str) or not robot_id for robot_id in robot_ids)):
            raise ValueError(f"sources[{index}].robot_ids must be a non-empty string list or 'enrolled'")
        corner_ids = row.get("corner_marker_ids")
        calibration_source = row.get("calibration_source", "corner_markers")
        if calibration_source not in CALIBRATION_SOURCES:
            raise ValueError(f"sources[{index}].calibration_source must be {' or '.join(CALIBRATION_SOURCES)}")
        if calibration_source == "field_boundary" and corner_ids is not None:
            raise ValueError(f"sources[{index}] is field_boundary and must not set corner_marker_ids")
        if calibration_source == "field_boundary" and "corner_world_m" not in row:
            raise ValueError(f"sources[{index}] is field_boundary and needs corner_world_m")
        if calibration_source == "corner_markers" and (
                not isinstance(corner_ids, list) or len(corner_ids) != 4
                or any(type(marker_id) is not int or marker_id < 0 for marker_id in corner_ids)):
            raise ValueError(f"sources[{index}].corner_marker_ids must contain four integer ids")
        if "corner_world_m" in row:
            corners = row["corner_world_m"]
            if (not isinstance(corners, list) or len(corners) != 4
                    or any(not isinstance(point, list) or len(point) != 2
                           or any(isinstance(v, bool) or not isinstance(v, (int, float))
                                  or not math.isfinite(v) for v in point) for point in corners)):
                raise ValueError(f"sources[{index}].corner_world_m must contain four finite x/y pairs")
            if len({tuple(point) for point in corners}) != 4:
                raise ValueError(f"sources[{index}].corner_world_m points must be distinct")
        markers = row.get("robot_markers", {})
        if (not isinstance(markers, dict)
                or any(not isinstance(robot_id, str) or not robot_id
                       or type(marker_id) is not int or marker_id < 0
                       for robot_id, marker_id in markers.items())):
            raise ValueError(f"sources[{index}].robot_markers must map robot ids to marker ids")
        if not follow and set(markers) - set(robot_ids):
            raise ValueError(f"sources[{index}].robot_markers names robots outside robot_ids: "
                             f"{', '.join(sorted(set(markers) - set(robot_ids)))}")
        if len(set(markers.values())) != len(markers):
            raise ValueError(f"sources[{index}].robot_markers must give each robot a distinct marker id")
        if corner_ids is not None and set(markers.values()) & set(corner_ids):
            raise ValueError(f"sources[{index}].robot_markers must not reuse corner_marker_ids")
