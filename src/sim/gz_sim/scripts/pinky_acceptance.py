#!/usr/bin/env python3
"""Collect one run-bound Pinky Gazebo mapping/navigation/perception result."""

from __future__ import annotations

import json
import hashlib
import math
import os
from pathlib import Path
import sys
import time

import rclpy
from geometry_msgs.msg import Twist
from nav_msgs.msg import OccupancyGrid, Odometry
from rclpy.node import Node
from rclpy.qos import (
    DurabilityPolicy,
    QoSProfile,
    ReliabilityPolicy,
    qos_profile_sensor_data,
)
from sensor_msgs.msg import Image
from std_msgs.msg import String


_SCRIPT_PATH = Path(__file__).resolve()
for _policy_dir in (
    _SCRIPT_PATH.parent,
    _SCRIPT_PATH.parents[1] / "launch",
):
    if (_policy_dir / "pinky_acceptance_policy.py").is_file():
        sys.path.insert(0, str(_policy_dir))
        break
else:  # pragma: no cover
    raise RuntimeError("pinky_acceptance_policy.py is missing from the install")

from pinky_acceptance_policy import (  # noqa: E402
    evaluate_acceptance,
    map_fidelity_metrics,
    reachable_map_metrics,
    road_observation_score,
    trajectory_clearance,
)


class PinkyAcceptance(Node):
    def __init__(self) -> None:
        super().__init__("pinky_acceptance")
        self.declare_parameter("run_id", "unset")
        self.declare_parameter("output_path", "/tmp/pinky-acceptance/result.json")
        self.declare_parameter("wall_geometry_path", "")
        self.declare_parameter("world_path", "")
        self.declare_parameter("robot_radius_m", 0.086)
        self.declare_parameter("clearance_margin_m", 0.010)
        self.declare_parameter("timeout_wall_s", 900.0)
        self.declare_parameter("final_zero_dwell_s", 0.5)
        self.declare_parameter("reachable_sampling_m", 0.01)
        self.run_id = str(self.get_parameter("run_id").value)
        self.output_path = Path(str(self.get_parameter("output_path").value))
        wall_path = Path(str(self.get_parameter("wall_geometry_path").value))
        wall_bytes = wall_path.read_bytes()
        self.walls = json.loads(wall_bytes.decode("utf-8"))
        world_path = Path(str(self.get_parameter("world_path").value))
        self.source_identity = {
            "wall_geometry_path": str(wall_path),
            "wall_geometry_sha256": hashlib.sha256(wall_bytes).hexdigest(),
            "world_path": str(world_path),
            "world_sha256": hashlib.sha256(world_path.read_bytes()).hexdigest(),
        }
        self.robot_radius = float(self.get_parameter("robot_radius_m").value)
        self.clearance_margin = float(
            self.get_parameter("clearance_margin_m").value
        )
        self.timeout_wall = float(self.get_parameter("timeout_wall_s").value)
        self.zero_dwell = float(
            self.get_parameter("final_zero_dwell_s").value
        )
        self.sampling = float(
            self.get_parameter("reachable_sampling_m").value
        )
        if self.robot_radius <= 0.0 or self.clearance_margin < 0.0:
            raise ValueError("valid Pinky geometry is required")

        self.started_wall = time.monotonic()
        self.finished = False
        self.camera = {"frames": 0, "width": None, "height": None, "frame_id": None}
        self.line = {"visible": False, "confidence": 0.0, "best": None}
        self.road = {
            "lane_visible": False,
            "stop_line_visible": False,
            "crosswalk_visible": False,
            "best": None,
        }
        self.line_while_moving = False
        self.mapping = None
        self.navigation = None
        self.map_message = None
        self.poses = []
        self.path_m = 0.0
        self.command = (0.0, 0.0)
        self.command_seen = False
        self.motion_seen = False
        self.last_nonzero_wall = self.started_wall
        self.cmd_vel_publisher_names = []

        latched = QoSProfile(
            depth=1,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
        )
        self.create_subscription(Odometry, "odom", self.on_odom, 10)
        self.create_subscription(
            OccupancyGrid, "map", self.on_map, latched
        )
        self.create_subscription(
            Image, "camera/front", self.on_camera, qos_profile_sensor_data
        )
        self.create_subscription(
            String, "line/observation", self.on_line, 10
        )
        self.create_subscription(
            String, "road/observation", self.on_road, 10
        )
        self.create_subscription(
            String, "mapping/status", self.on_mapping, 10
        )
        self.create_subscription(
            String, "navigation/probe_status", self.on_navigation, latched
        )
        self.create_subscription(Twist, "cmd_vel", self.on_command, 10)
        self.create_timer(0.25, self.tick)

    @staticmethod
    def _decode(msg: String):
        try:
            value = json.loads(msg.data)
            return value if isinstance(value, dict) else None
        except (TypeError, ValueError, json.JSONDecodeError):
            return None

    def on_odom(self, msg: Odometry) -> None:
        point = (
            float(msg.pose.pose.position.x),
            float(msg.pose.pose.position.y),
        )
        if self.poses:
            step = math.dist(self.poses[-1], point)
            if step < 0.10:
                self.path_m += step
        self.poses.append(point)

    def on_map(self, msg: OccupancyGrid) -> None:
        if msg.info.width and msg.info.height and len(msg.data) == (
            msg.info.width * msg.info.height
        ):
            self.map_message = msg

    def on_camera(self, msg: Image) -> None:
        self.camera.update(
            frames=self.camera["frames"] + 1,
            width=int(msg.width),
            height=int(msg.height),
            frame_id=str(msg.header.frame_id),
        )

    def on_line(self, msg: String) -> None:
        value = self._decode(msg)
        if not value or value.get("source") != "CAMERA_LINE":
            return
        confidence = float(value.get("confidence") or 0.0)
        visible = value.get("visible") is True
        if visible and confidence >= self.line["confidence"]:
            self.line.update(visible=True, confidence=confidence, best=value)
        if visible and confidence >= 0.8 and any(
            abs(component) > 1e-3 for component in self.command
        ):
            self.line_while_moving = True

    def on_road(self, msg: String) -> None:
        value = self._decode(msg)
        if not value or value.get("source") != "CAMERA_ROAD":
            return
        self.road["lane_visible"] |= value.get("lane", {}).get("visible") is True
        self.road["stop_line_visible"] |= (
            value.get("stop_line", {}).get("visible") is True
        )
        self.road["crosswalk_visible"] |= (
            value.get("crosswalk", {}).get("visible") is True
        )
        score = road_observation_score(value)
        previous = self.road.get("best_score", -1)
        if score > previous:
            self.road["best"] = value
            self.road["best_score"] = score

    def on_mapping(self, msg: String) -> None:
        value = self._decode(msg)
        if value:
            self.mapping = value

    def on_navigation(self, msg: String) -> None:
        value = self._decode(msg)
        if value and value.get("run_id") == self.run_id:
            self.navigation = value

    def on_command(self, msg: Twist) -> None:
        self.command_seen = True
        self.command = (float(msg.linear.x), float(msg.angular.z))
        if any(abs(value) > 1e-3 for value in self.command):
            self.motion_seen = True
            self.last_nonzero_wall = time.monotonic()

    def _publisher_names(self) -> list[str]:
        names = []
        for endpoint in self.get_publishers_info_by_topic("cmd_vel"):
            namespace = str(endpoint.node_namespace).rstrip("/")
            name = str(endpoint.node_name).lstrip("/")
            names.append(f"{namespace}/{name}" if namespace else f"/{name}")
        return sorted(set(names))

    def tick(self) -> None:
        if self.finished:
            return
        self.cmd_vel_publisher_names = self._publisher_names()
        now = time.monotonic()
        terminal_nav = (
            self.navigation is not None
            and self.navigation.get("phase") in {"complete", "failed"}
        )
        zero_stable = (
            self.command_seen
            and self.motion_seen
            and all(abs(value) <= 1e-3 for value in self.command)
            and now - self.last_nonzero_wall >= self.zero_dwell
        )
        if terminal_nav and zero_stable:
            self.finish("terminal")
        elif now - self.started_wall >= self.timeout_wall:
            self.finish("timeout")

    def finish(self, reason: str) -> None:
        if self.finished:
            return
        self.finished = True
        trajectory = trajectory_clearance(
            self.poses, self.walls, self.robot_radius
        )
        reachable = None
        fidelity = None
        map_summary = {"received": self.map_message is not None}
        if self.map_message is not None:
            info = self.map_message.info
            origin = info.origin.position
            reachable = reachable_map_metrics(
                self.map_message.data,
                int(info.width),
                int(info.height),
                float(info.resolution),
                (float(origin.x), float(origin.y)),
                self.walls,
                (-0.20, -0.15),
                self.robot_radius + self.clearance_margin,
                sampling_m=self.sampling,
            )
            fidelity = map_fidelity_metrics(
                self.map_message.data,
                int(info.width),
                int(info.height),
                float(info.resolution),
                (float(origin.x), float(origin.y)),
                self.walls,
            )
            map_summary.update({
                "frame_id": self.map_message.header.frame_id,
                "width": int(info.width),
                "height": int(info.height),
                "resolution_m": float(info.resolution),
                "origin_xy": [float(origin.x), float(origin.y)],
                "known_cells": sum(1 for value in self.map_message.data if value >= 0),
                "robot_reachable": reachable,
                "full_raster_fidelity": fidelity,
            })
        final_zero = (
            self.command_seen
            and self.motion_seen
            and all(abs(value) <= 1e-3 for value in self.command)
            and time.monotonic() - self.last_nonzero_wall >= self.zero_dwell
        )
        evidence = {
            "mapping_complete": (
                self.mapping is not None
                and self.mapping.get("phase") == "complete"
            ),
            "map_received": self.map_message is not None,
            "reachable_mapping_complete": bool(
                reachable and reachable["mapping_complete"]
            ),
            "minimum_body_clearance_m": trajectory[
                "minimum_body_clearance_m"
            ],
            "collision": trajectory["collision"],
            "camera_frames": self.camera["frames"],
            "line_visible": self.line["visible"],
            "line_confidence": self.line["confidence"],
            "line_visible_while_moving": self.line_while_moving,
            "road_lane_visible": self.road["lane_visible"],
            "stop_line_visible": self.road["stop_line_visible"],
            "crosswalk_visible": self.road["crosswalk_visible"],
            "nav2_passed": bool(
                self.navigation and self.navigation.get("passed") is True
            ),
            "cmd_vel_publishers": self.cmd_vel_publisher_names,
            "final_zero_stable": final_zero,
        }
        verdict = evaluate_acceptance(
            evidence, clearance_margin_m=self.clearance_margin
        )
        result = {
            "schema_version": 1,
            "run_id": self.run_id,
            "completed_at_unix_s": time.time(),
            "termination_reason": reason,
            "environment": "ROS-SIM",
            "physical_pinky_pro": "NOT_TESTED",
            "source_identity": self.source_identity,
            "geometry": {
                "robot_diameter_m": self.robot_radius * 2.0,
                "robot_radius_m": self.robot_radius,
                "clearance_margin_m": self.clearance_margin,
                **trajectory,
            },
            "trajectory": {"path_m": self.path_m},
            "mapping_status": self.mapping,
            "map": map_summary,
            "camera": self.camera,
            "line": {**self.line, "visible_while_moving": self.line_while_moving},
            "road": self.road,
            "navigation": self.navigation,
            "command": {
                "final": list(self.command),
                "publishers": self.cmd_vel_publisher_names,
                "final_zero_stable": final_zero,
            },
            **verdict,
        }
        result["full_raster_fidelity_gate"] = (
            "PASS" if fidelity and fidelity["full_raster_fidelity_passed"]
            else "HOLD_FULL_RASTER_FIDELITY"
        )
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.output_path.with_suffix(self.output_path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(result, indent=2, sort_keys=True), encoding="utf-8"
        )
        os.replace(temporary, self.output_path)
        self.get_logger().info(json.dumps({
            "run_id": self.run_id,
            "passed": verdict["passed"],
            "output": str(self.output_path),
        }, sort_keys=True))


def main() -> None:
    rclpy.init()
    node = PinkyAcceptance()
    try:
        while rclpy.ok() and not node.finished:
            rclpy.spin_once(node, timeout_sec=0.1)
    except KeyboardInterrupt:
        node.finish("interrupted")
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
