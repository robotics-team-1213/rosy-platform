"""Prefix Nav2 TF frames that live under the robot, leave `map` global.

Topics are namespaced by launch. Frames are not. Bringup publishes
`{ns}/odom` → `{ns}/base_footprint` (D-4); stock nav2_params.yaml still
says `odom` / `base_footprint`. AMCL then never sees a transform.

Sensor topics named inside a costmap plugin are the exception to "topics are
namespaced by launch". A costmap's observation source resolves its topic
against the **costmap node's** namespace, not the robot's, so `scan` became
`/{ns}/global_costmap/scan` — a topic nobody publishes. The obstacle layers
took no observation at all and nav2 drove on the static map alone: two robots
walked into each other at every corridor width from 1.4 m down to 0.7 m, and
the planner never once reported a blockage because, to it, the corridor was
empty. Absolute `/scan` fixes the device (no namespace); this module carries
the same rewrite to the namespaced sim.
"""

from __future__ import annotations

import copy
from typing import Any

PREFIXABLE_FRAMES = {"odom", "base_footprint", "base_link"}
FRAME_KEYS = {
    "base_frame",
    "base_frame_id",
    "odom_frame",
    "odom_frame_id",
    "map_frame",
    "robot_base_frame",
    "global_frame",
    "local_frame",
    "global_frame_id",
}

#: Sensor topics that live under the robot. `/map` is deliberately absent — it is
#: shared, like the `map` frame.
PREFIXABLE_TOPICS = {"scan", "/scan"}
TOPIC_KEYS = {"topic", "scan_topic"}


def apply_nav2_frame_prefix(params: dict, prefix: str) -> dict:
    data = copy.deepcopy(params)
    if not prefix:
        return data
    if not prefix.endswith("/"):
        prefix += "/"

    def walk(obj: Any) -> None:
        if isinstance(obj, dict):
            for key, value in obj.items():
                if isinstance(value, (dict, list)):
                    walk(value)
                elif (
                    key in FRAME_KEYS
                    and isinstance(value, str)
                    and value in PREFIXABLE_FRAMES
                ):
                    obj[key] = prefix + value
                elif (
                    key in TOPIC_KEYS
                    and isinstance(value, str)
                    and value in PREFIXABLE_TOPICS
                ):
                    obj[key] = "/" + prefix + value.lstrip("/")
        elif isinstance(obj, list):
            for item in obj:
                walk(item)

    walk(data)
    return data
