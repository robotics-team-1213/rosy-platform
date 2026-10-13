"""Write a namespaced Nav2 params file for launch (D-4)."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Sequence

import yaml

from navigation.frame_prefix import apply_nav2_frame_prefix


def write_prefixed_nav2_params(
    source: str | Path,
    namespace: str,
    *,
    directory: str | Path = "/tmp",
    footprint_points: Sequence[Sequence[float]] | None = None,
) -> str:
    params = yaml.safe_load(Path(source).read_text(encoding="utf-8"))
    prefix = f"{namespace}/" if namespace else ""
    if footprint_points is not None:
        footprint = json.dumps(
            [[float(point[0]), float(point[1])] for point in footprint_points],
            separators=(",", ":"),
        )
        for path in (
            ("local_costmap", "local_costmap", "ros__parameters"),
            ("global_costmap", "global_costmap", "ros__parameters"),
        ):
            target = params
            for key in path:
                target = target[key]
            target["footprint"] = footprint
    dest = tempfile.NamedTemporaryFile(
        prefix="rosy_nav2_params_",
        suffix=".yaml",
        dir=str(directory),
        delete=False,
        mode="w",
        encoding="utf-8",
    )
    with dest:
        yaml.safe_dump(apply_nav2_frame_prefix(params, prefix), dest)
    return dest.name
