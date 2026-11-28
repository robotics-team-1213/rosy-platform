"""Write a namespaced Nav2 params file for launch (D-4)."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Sequence

import yaml

from navigation.frame_prefix import apply_nav2_frame_prefix
from navigation.profile_limits import derive_slow_speed_params


def write_prefixed_nav2_params(
    source: str | Path,
    namespace: str,
    *,
    directory: str | Path = "/tmp",
    footprint_points: Sequence[Sequence[float]] | None = None,
    speed: tuple[float, float] | None = None,
    amcl_laser_model: str = "configured",
    keepout_mask: bool = False,
) -> str:
    params = yaml.safe_load(Path(source).read_text(encoding="utf-8"))
    if amcl_laser_model not in {"configured", "beam"}:
        raise ValueError("AMCL laser model must be configured or beam")
    if amcl_laser_model == "beam":
        amcl = params.get("amcl", {}).get("ros__parameters")
        if not isinstance(amcl, dict):
            raise ValueError("beam AMCL requires an AMCL parameter section")
        amcl["laser_model_type"] = "beam"
    if speed is not None:
        derive_slow_speed_params(params, *speed)
    prefix = f"{namespace}/" if namespace else ""
    # D-1009: our behavior trees ship beside params/ (share/navigation/behavior_trees); a source without them keeps Nav2's stock trees.
    trees = Path(source).resolve().parent.parent / "behavior_trees"
    bt = params.get("bt_navigator", {}).get("ros__parameters")
    if bt is not None and trees.is_dir():
        bt["default_nav_to_pose_bt_xml"] = str(trees / "rosy_navigate_to_pose.xml")
        bt["default_nav_through_poses_bt_xml"] = str(trees / "rosy_navigate_through_poses.xml")
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
    if keepout_mask:
        gmap = params.get("global_costmap", {}).get("global_costmap", {}).get("ros__parameters")
        if isinstance(gmap, dict):
            filters = list(gmap.get("filters") or [])
            if "keepout_filter" not in filters:
                filters.append("keepout_filter")
            gmap["filters"] = filters
            gmap["keepout_filter"] = {
                "plugin": "nav2_costmap_2d::KeepoutFilter",
                "enabled": True,
                "filter_info_topic": "/costmap_filter_info",
            }
        params["filter_mask_server"] = {
            "ros__parameters": {
                "bond_heartbeat_period": 0.0,
                "frame_id": "map",
                "topic_name": "/keepout_filter_mask",
            }
        }
        params["costmap_filter_info_server"] = {
            "ros__parameters": {
                "bond_heartbeat_period": 0.0,
                "type": 0,
                "filter_info_topic": "/costmap_filter_info",
                "mask_topic": "/keepout_filter_mask",
                "base": 0.0,
                "multiplier": 1.0,
            }
        }
    # D-4: standalone nodes match params-file sections by fully qualified name, so a
    # bare `slam_toolbox:` section never reaches `/rosy_42/slam_toolbox` and the node
    # silently runs on defaults (2026-11-04 geg6 probe verified FQN sections apply).
    if prefix:
        params = {
            key if key.startswith("/") else "/" + prefix + key: value
            for key, value in params.items()
        }
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
