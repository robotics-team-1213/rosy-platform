"""Load source-scoped sighting permissions from non-secret site YAML."""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Mapping

import yaml

from core_common.protocol.place_markers import check_place_marker_ids
from core_common.protocol.sightings import check_marker_yaw_offsets
from core_common.protocol.sighting_sources import validate_sighting_config
from fleet.server.sightings import SightingSource

#: D-580: `robot_ids: enrolled` = every robot on the live roster (robots.yaml + enrolled).
ROSTER = "enrolled"


def load_sighting_sources(path: Path | str, *, environ: Mapping[str, str] | None = None
                          ) -> list[SightingSource]:
    """Resolve secret values from the process environment, never from YAML."""

    source_path = Path(path)
    try:
        config = yaml.safe_load(source_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise ValueError(f"cannot read sighting config {source_path}: {exc}") from exc
    validate_sighting_config(config)

    env = os.environ if environ is None else environ
    sources = []
    for index, row in enumerate(config["sources"]):
        credential = row.get("credential", "static")
        env_name = row["token_env"]
        token = env.get(env_name)
        if not isinstance(token, str) or not token:
            raise ValueError(f"sighting token environment variable {env_name} is required")
        robot_ids = row["robot_ids"]
        corner_ids = row.get("corner_marker_ids")
        calibration_source = row.get("calibration_source", "corner_markers")
        follow = robot_ids == ROSTER  # D-580
        corner_world_m = None
        if "corner_world_m" in row:
            corners = row["corner_world_m"]
            corner_world_m = tuple((float(x), float(y)) for x, y in corners)
        markers = row.get("robot_markers", {})
        try:  # D-564
            place_markers = check_place_marker_ids(row.get("place_markers", []), corner_ids=corner_ids,
                                                   robot_marker_ids=markers.values())
        except ValueError as exc:
            raise ValueError(f"sources[{index}].{exc}") from exc
        try:  # D-587 4: Vision applies the offsets; Fleet only refuses a bad file the same way.
            check_marker_yaw_offsets(row.get("marker_yaw_offset_deg"), None if follow else robot_ids)
        except ValueError as exc:
            raise ValueError(f"sources[{index}].{exc}") from exc
        sources.append(SightingSource(
            source_id=row["source_id"],
            token=token,
            robot_ids=() if follow else tuple(robot_ids),
            map_id=row["map_id"],
            calibration_revision=row["calibration_revision"],
            corner_marker_ids=None if corner_ids is None else tuple(corner_ids),
            corner_world_m=corner_world_m,
            robot_markers=() if follow else tuple(markers.items()),
            follow_roster=follow,
            marker_overrides=tuple(markers.items()) if follow else (),
            credential=credential,
            calibration_source=calibration_source,
            place_markers=place_markers,
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


def load_identity_config(path: Path | str):
    """D-472: the optional ``identity:`` mapping of the same site YAML (IdentityConfig fields)."""
    from fleet.server.identity import IdentityConfig

    try:
        config = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise ValueError(f"cannot read sighting config {path}: {exc}") from exc
    try:
        return IdentityConfig.from_mapping((config or {}).get("identity"))
    except TypeError as exc:
        raise ValueError(f"identity config: {exc}") from exc


def _relax_retired_sighting_targets(sources, *, known: set, retired: set):
    """D-361 5: a mapping to an unenrolled/pending-logout robot is disabled with a warning;
    an id never seen in robots.yaml or the register still refuses start (a typo)."""
    from dataclasses import replace

    kept = []
    for source in sources:
        if source.follow_roster:  # D-580: targets come from the roster, never a typo
            kept.append(source)
            continue
        unknown = set(source.robot_ids) - known
        if unknown - retired:
            sys.exit(f"sighting source {source.source_id!r} has an unknown robot target")
        if unknown:
            print(f"warning: sighting source {source.source_id!r}: mapping disabled for "
                  f"unenrolled robots {sorted(unknown)}", file=sys.stderr)
        robot_ids = tuple(rid for rid in source.robot_ids if rid not in unknown)
        if robot_ids:
            kept.append(replace(source, robot_ids=robot_ids))
        else:
            print(f"warning: sighting source {source.source_id!r} disabled: no enrolled targets",
                  file=sys.stderr)
    return kept
