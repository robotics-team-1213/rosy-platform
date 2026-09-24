#!/usr/bin/env python3
"""Drive the exact map_260905 v2 observation route through CORE.

This node publishes only ``nav_cmd_vel``.  CORE remains the sole final
``cmd_vel`` authority and must be armed through its authenticated API first.
Clearance continuously caps speed; recovery distance is computed from the
robot diameter and the live front/rear scan instead of a fixed retreat.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
import sys
import time
import urllib.error
import urllib.request

import rclpy
from rclpy.clock import Clock, ClockType
from geometry_msgs.msg import Twist
from nav_msgs.msg import Odometry
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import LaserScan
from std_msgs.msg import String

# A normal CMake install copies both files into lib/gz_sim, while
# --symlink-install resolves this executable back to source/scripts and keeps
# the policy in source/launch.  Support both layouts explicitly.
_SCRIPT_PATH = Path(__file__).resolve()
for _policy_dir in (
    _SCRIPT_PATH.parent,
    _SCRIPT_PATH.parents[1] / "launch",
):
    if (_policy_dir / "map_v2_traversal.py").is_file():
        sys.path.insert(0, str(_policy_dir))
        break
else:  # pragma: no cover - packaging contract catches this before runtime
    raise RuntimeError("map_v2_traversal.py is missing from the install")

from map_v2_traversal import (  # noqa: E402
    TraversalLimits,
    adaptive_speed,
    bidirectional_heading_error,
    mapping_observation_indices,
    mapping_route_world,
    recovery_reverse_distance,
    robust_clearance,
    route_start_index,
    completion_exit_ready,
    turn_clearance_available,
)

# rplidar_link is mounted with yaw=pi in rosy.urdf.xacro.  LaserScan angles
# are sensor-frame angles, so angle zero is robot-rear and pi is robot-front.
FRONT_SCAN_ANGLE = math.pi
REAR_SCAN_ANGLE = 0.0
LEFT_SCAN_ANGLE = -math.pi / 2.0
RIGHT_SCAN_ANGLE = math.pi / 2.0


def wrap(angle: float) -> float:
    return math.atan2(math.sin(angle), math.cos(angle))


def yaw_from_quaternion(q) -> float:
    return math.atan2(
        2.0 * (q.w * q.z + q.x * q.y),
        1.0 - 2.0 * (q.y * q.y + q.z * q.z),
    )


class MappingRunner(Node):
    """Small deterministic mapper driver with scan-derived motion limits."""

    def __init__(self) -> None:
        super().__init__("map_v2_runner")
        self.declare_parameter("robot_diameter_m", 0.172)
        self.declare_parameter("max_linear_mps", 0.16)
        self.declare_parameter("crawl_linear_mps", 0.025)
        self.declare_parameter("max_angular_rps", 0.60)
        self.declare_parameter("waypoint_tolerance_m", 0.045)
        self.declare_parameter("clearance_quantile", 0.30)
        self.declare_parameter("start_route_index", 1)
        self.declare_parameter("exit_on_complete", False)
        self.declare_parameter("completion_zero_dwell_s", 0.5)
        self.declare_parameter("run_id", "unset")
        self.declare_parameter("core_api", "http://127.0.0.1:8080")
        # core's dev operator token; the sim launch starts core with ROSY_DEV_AUTH=1 (D-193 7).
        self.declare_parameter("operator_token", "rosy-dev-operator")
        diameter = float(self.get_parameter("robot_diameter_m").value)
        self.limits = TraversalLimits(
            robot_diameter_m=diameter,
            max_linear_mps=float(self.get_parameter("max_linear_mps").value),
            crawl_linear_mps=float(self.get_parameter("crawl_linear_mps").value),
        )
        self.max_angular = float(self.get_parameter("max_angular_rps").value)
        self.waypoint_tolerance = float(
            self.get_parameter("waypoint_tolerance_m").value
        )
        self.clearance_quantile = float(
            self.get_parameter("clearance_quantile").value
        )
        self.core_api = str(self.get_parameter("core_api").value).rstrip("/")
        self.operator_token = str(self.get_parameter("operator_token").value)
        self.run_id = str(self.get_parameter("run_id").value)

        # Ground-truth simulation odometry shares the exact world's absolute
        # coordinate frame, so the reviewed route must not be re-zeroed at the
        # spawn point.
        self.route = mapping_route_world()
        self.index = route_start_index(
            int(self.get_parameter("start_route_index").value),
            len(self.route),
        )
        self.exit_on_complete = bool(
            self.get_parameter("exit_on_complete").value
        )
        self.completion_zero_dwell = float(
            self.get_parameter("completion_zero_dwell_s").value
        )
        # Validate the dwell at startup rather than discovering a bad
        # acceptance setting after the robot has moved.
        completion_exit_ready(None, 0.0, self.completion_zero_dwell)
        self.exit_requested = False
        # The lidar is genuinely 360 degrees, so ordinary route points need no
        # artificial scan turn.  A deliberate half-turn is retained only at
        # each pocket's deepest viewpoint to collect repeated stable scans
        # before the robot backs out through its narrow opening.
        self.observation_indices = set(mapping_observation_indices(self.route))
        self.observed: set[int] = set()
        self.x = self.y = self.yaw = 0.0
        self.have_odom = False
        self.scan: LaserScan | None = None
        self.armed = False
        self.last_arm_attempt = 0.0
        self.last_yaw = 0.0
        self.spin_remaining = 0.0
        self.spin_sign = 1.0
        self.phase = "initial_scan"
        self.recovery_start = (0.0, 0.0)
        self.recovery_distance = 0.0
        self.recovery_turn_remaining = 0.0
        self.progress_anchor = (0.0, 0.0)
        self.progress_time = 0.0
        self.path_m = 0.0
        self.last_position: tuple[float, float] | None = None
        self.done_since: float | None = None

        self.velocity = self.create_publisher(Twist, "nav_cmd_vel", 10)
        self.status = self.create_publisher(String, "mapping/status", 10)
        self.create_subscription(Odometry, "odom", self.on_odom, 10)
        self.create_subscription(
            LaserScan, "scan", self.on_scan, qos_profile_sensor_data
        )
        # CORE's navigation watchdog is wall-monotonic.  A sim-time timer
        # drops below its 2 Hz freshness requirement when software-rendered
        # Gazebo runs slower than real time, so publish commands on steady
        # time even while all sensor/header timestamps remain simulated.
        self.timer = self.create_timer(
            0.10,
            self.tick,
            clock=Clock(clock_type=ClockType.STEADY_TIME),
        )
        self.publish_status("waiting_for_inputs")

    def now(self) -> float:
        # Motion progress must be evaluated in simulation time.  Software
        # rendering can make 1 simulated second take several wall seconds;
        # wall time would falsely declare a low-speed crawl to be stuck.
        return self.get_clock().now().nanoseconds * 1.0e-9

    def on_odom(self, msg: Odometry) -> None:
        # /odom is the model-pose OdometryPublisher in this simulation.  It is
        # exact-world feedback, unlike the separately retained /odom_wheel.
        # SLAM remains free to correct map->odom while route control does not
        # chase those corrections and repeatedly recover at a fixed wall.
        new_position = (msg.pose.pose.position.x, msg.pose.pose.position.y)
        new_yaw = yaw_from_quaternion(msg.pose.pose.orientation)
        was_ready = self.have_odom
        if self.last_position is not None:
            step = math.dist(self.last_position, new_position)
            if step < 0.10:
                self.path_m += step
        if was_ready and self.phase in {
            "initial_scan", "observe", "recovery_turn"
        }:
            delta = abs(wrap(new_yaw - self.last_yaw))
            if self.phase == "recovery_turn":
                self.recovery_turn_remaining = max(
                    0.0, self.recovery_turn_remaining - delta
                )
            else:
                self.spin_remaining = max(0.0, self.spin_remaining - delta)

        self.last_position = new_position
        self.x, self.y = new_position
        self.yaw = new_yaw
        self.last_yaw = new_yaw
        if not was_ready:
            self.progress_anchor = new_position
            self.progress_time = self.now()
        self.have_odom = True

    def on_scan(self, msg: LaserScan) -> None:
        self.scan = msg

    def sector_min(
        self,
        center: float,
        half_width: float,
        lower_quantile: float | None = None,
    ) -> float:
        if self.scan is None:
            return math.nan
        values = []
        for index, value in enumerate(self.scan.ranges):
            angle = self.scan.angle_min + index * self.scan.angle_increment
            if abs(wrap(angle - center)) <= half_width:
                if (
                    math.isfinite(value)
                    and self.scan.range_min <= value <= self.scan.range_max
                ):
                    values.append(float(value))
        if lower_quantile is None:
            return robust_clearance(values, self.clearance_quantile)
        return robust_clearance(values, lower_quantile)

    def turn_clearances(self) -> list[float]:
        # Eight overlapping sectors cover the full turn sweep.  The stricter
        # lower decile keeps a local corner from disappearing into the wider
        # motion-control quantile.
        return [
            self.sector_min(index * math.pi / 4.0, 0.40, 0.10)
            for index in range(8)
        ]

    def publish_status(self, detail: str) -> None:
        message = String()
        message.data = json.dumps(
            {
                "run_id": self.run_id,
                "phase": self.phase,
                "detail": detail,
                "waypoint": self.index,
                "waypoint_count": len(self.route),
                "path_m": round(self.path_m, 4),
                "armed": self.armed,
            },
            sort_keys=True,
        )
        self.status.publish(message)
        self.get_logger().info(message.data)

    def arm_core(self) -> bool:
        payload = json.dumps({"mode": "NAVIGATION"}).encode("utf-8")
        request = urllib.request.Request(
            f"{self.core_api}/api/v1/mode",
            data=payload,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.operator_token}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=1.0) as response:
                self.armed = response.status == 200
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            self.get_logger().warning(f"CORE arm pending: {exc}")
            self.armed = False
        return self.armed

    def zero(self) -> None:
        self.velocity.publish(Twist())

    def begin_recovery(self, front: float, rear: float) -> None:
        distance = recovery_reverse_distance(
            front,
            rear,
            self.limits.footprint_radius_m,
            self.limits,
        )
        left = self.sector_min(LEFT_SCAN_ANGLE, 0.40)
        right = self.sector_min(RIGHT_SCAN_ANGLE, 0.40)
        self.spin_sign = 1.0 if (not math.isfinite(right) or left >= right) else -1.0
        if distance > 0.0:
            self.phase = "recovery_reverse"
            self.recovery_start = (self.x, self.y)
            self.recovery_distance = distance
            self.publish_status(f"reverse_distance_m={distance:.3f}")
        elif turn_clearance_available(self.turn_clearances(), self.limits):
            self.phase = "recovery_turn"
            self.recovery_turn_remaining = math.pi / 2.0
            self.publish_status("turn_clearance_already_available")
        else:
            # Rear room can cap the flexible retreat below the amount needed
            # to rotate.  Never convert that partial motion into a blind turn.
            self.phase = "blocked"
            self.zero()
            self.publish_status("recovery_blocked_no_safe_turn_or_reverse")

    def finish_spin(self) -> None:
        self.zero()
        # A deliberate scan can take tens of wall-clock seconds.  Start the
        # forward-stall window only after the scan has completed.
        self.progress_anchor = (self.x, self.y)
        self.progress_time = self.now()
        if self.phase == "initial_scan":
            self.phase = "route"
            self.publish_status("initial_scan_complete")
        else:
            self.observed.add(self.index)
            self.index += 1
            self.phase = "route"
            self.publish_status("observation_scan_complete")

    def tick(self) -> None:
        if not self.have_odom or self.scan is None:
            self.zero()
            return
        wall_now = time.monotonic()
        if not self.armed:
            self.zero()
            if wall_now - self.last_arm_attempt >= 2.0:
                self.last_arm_attempt = wall_now
                if self.arm_core():
                    self.publish_status("core_navigation_armed")
            return
        if self.phase in {"initial_scan", "observe"}:
            if self.spin_remaining <= 0.03:
                self.finish_spin()
                return
            cmd = Twist()
            cmd.angular.z = self.spin_sign * self.max_angular
            self.velocity.publish(cmd)
            return

        if self.phase == "recovery_reverse":
            if math.dist(self.recovery_start, (self.x, self.y)) >= self.recovery_distance:
                self.zero()
                if turn_clearance_available(self.turn_clearances(), self.limits):
                    self.phase = "recovery_turn"
                    self.recovery_turn_remaining = math.pi / 2.0
                    self.publish_status("recovery_reverse_complete")
                else:
                    # Re-evaluate from the new scan.  A second bounded retreat
                    # is allowed only if live rear clearance still permits it.
                    self.begin_recovery(
                        self.sector_min(FRONT_SCAN_ANGLE, 0.30),
                        self.sector_min(REAR_SCAN_ANGLE, 0.30),
                    )
                return
            rear = self.sector_min(REAR_SCAN_ANGLE, 0.30)
            cmd = Twist()
            if rear > self.limits.hard_clearance_m:
                cmd.linear.x = -min(0.06, self.limits.max_linear_mps)
            self.velocity.publish(cmd)
            return

        if self.phase == "recovery_turn":
            if self.recovery_turn_remaining <= 0.03:
                self.phase = "route"
                self.progress_anchor = (self.x, self.y)
                self.progress_time = self.now()
                self.zero()
                self.publish_status("recovery_complete")
                return
            cmd = Twist()
            cmd.angular.z = self.spin_sign * min(self.max_angular, 0.45)
            self.velocity.publish(cmd)
            return

        if self.phase == "complete":
            self.zero()
            if self.done_since is None:
                self.done_since = self.now()
                self.publish_status("route_complete_final_zero")
            elif self.exit_on_complete and completion_exit_ready(
                self.done_since, self.now(), self.completion_zero_dwell
            ):
                self.exit_requested = True
            return

        if self.phase == "blocked":
            self.zero()
            return

        if self.index >= len(self.route):
            self.phase = "complete"
            self.zero()
            return

        target_x, target_y = self.route[self.index]
        distance = math.hypot(target_x - self.x, target_y - self.y)
        if distance <= self.waypoint_tolerance:
            self.zero()
            if self.index in self.observation_indices and self.index not in self.observed:
                self.phase = "observe"
                self.spin_remaining = math.pi
                self.spin_sign *= -1.0
                self.publish_status("observation_waypoint_reached")
            else:
                self.index += 1
                self.progress_anchor = (self.x, self.y)
                self.progress_time = self.now()
                self.publish_status("waypoint_reached")
            return

        heading = math.atan2(target_y - self.y, target_x - self.x)
        error = wrap(heading - self.yaw)
        direction, drive_error = bidirectional_heading_error(error)
        front = self.sector_min(FRONT_SCAN_ANGLE, 0.30)
        rear = self.sector_min(REAR_SCAN_ANGLE, 0.30)
        left = self.sector_min(LEFT_SCAN_ANGLE, 0.40)
        right = self.sector_min(RIGHT_SCAN_ANGLE, 0.40)
        side = min(left, right)
        if not all(math.isfinite(value) for value in (front, rear, left, right)):
            self.zero()
            return

        cmd = Twist()
        if abs(drive_error) > 0.18:
            # Turning in place is expected and must not consume the forward
            # progress timeout before the first linear command is published.
            self.progress_anchor = (self.x, self.y)
            self.progress_time = self.now()
            cmd.angular.z = max(
                -self.max_angular, min(self.max_angular, 1.8 * drive_error)
            )
        else:
            curvature = abs(2.0 * math.sin(drive_error) / max(distance, 0.05))
            approach_clearance = front if direction > 0.0 else rear
            speed = adaptive_speed(
                approach_clearance, side, curvature, self.limits
            )
            cmd.linear.x = direction * speed
            cmd.angular.z = max(
                -self.max_angular, min(self.max_angular, 1.8 * drive_error)
            )
            if speed <= 0.0:
                self.zero()
                self.begin_recovery(front, rear)
                return

        moved = math.dist(self.progress_anchor, (self.x, self.y))
        if moved >= 0.03:
            self.progress_anchor = (self.x, self.y)
            self.progress_time = self.now()
        elif abs(cmd.linear.x) > 0.02 and self.now() - self.progress_time >= 3.0:
            self.zero()
            self.begin_recovery(front, rear)
            return
        self.velocity.publish(cmd)


def main() -> None:
    rclpy.init()
    node = MappingRunner()
    try:
        while rclpy.ok() and not node.exit_requested:
            rclpy.spin_once(node, timeout_sec=0.1)
    except KeyboardInterrupt:
        pass
    finally:
        node.zero()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
