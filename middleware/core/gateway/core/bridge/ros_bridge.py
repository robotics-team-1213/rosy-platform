"""core.bridge.ros_bridge — ROS-101 모든 ROS I/O 집중 (P1-3).

유일한 cmd_vel 퍼블리셔 (D-2, 50 Hz) · 구독·발행·서비스·7타이머·Nav2 액션·TF 전부
여기에만 (목록은 `test/test_bridge_timers.py`가 고정). 판정은 하지 않는다: 값을
정하는 일은 ROS-free 시블리(`observation`, `goal_tracker`, `reconcile`, `display`,
`save_map`, `translate`, `docking_executor`)로 빠져 있고, 이 파일은 적응과 전달만 한다 — 그 자리가
호스트 pytest 에서 도달 불가능하기 때문이다.
"""

from __future__ import annotations

import json
import math
import os
import time
import traceback
from datetime import datetime, timezone  # noqa: F401 — re-exported
from typing import Optional  # noqa: F401 — re-exported

import rclpy
from rclpy.action import ActionClient
from rclpy.duration import Duration
from rclpy.node import Node

from geometry_msgs.msg import PoseWithCovarianceStamped, Twist
from nav_msgs.msg import OccupancyGrid, Odometry, Path
from nav2_msgs.action import NavigateThroughPoses, NavigateToPose
from nav2_msgs.msg import Costmap
from lifecycle_msgs.msg import TransitionEvent
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy, qos_profile_sensor_data
from sensor_msgs.msg import BatteryState, CompressedImage, Imu, LaserScan, Range
from std_msgs.msg import Bool, Float32, String
from std_srvs.srv import Empty, SetBool

from core.bridge import (  # noqa: F401 — re-exported
    device_power,
    display,
    expression,
    docking_mode,
    goal_tracker,
    map_observation,
    map_pose,
    nav_goal,
    observation,
    odometry,
    pilot_recorder_client,
    save_map,
    thermal_policy,
    traffic_gate,
    translate,
)
from core.bridge.cmd_vel import CycleGapWatch, cmd_vel_cycle
from core.bridge.docking_executor import BridgeDockingExecutor
from core.bridge.expression_policy import Expression, ExpressionPolicy  # noqa: F401 — re-exported
from core.bridge.goal_tracker import GoalTracker
from core.bridge.lane_route import RouteGuidePublication
from core.bridge.ros_bridge_helpers import RosBridgeHelpersMixin
from core.bridge.route_context import RouteContextPublication
from core_common.protocol.recording import (
    FETCHED_TOPIC,
    RAW_PREVIEW_TOPIC,
    SET_ACTIVE_SERVICE,
    START_SERVICE,
    STATUS_TOPIC,
    TELEOP_INTENT_TOPIC,
    teleop_intent,
)
from core_common.protocol.schemas import HealthState
from core_features.command.manager import Twist as CoreTwist
from core_features.diagnostics.collector import (
    CpuLoadProvider,
    DiagnosticsCollector,
    MemoryAvailableProvider,
    disk_provider,
    topic_freshness_provider,
)
from core_features.navigation.initial_pose import amcl_pose_covariance
from core_features.navigation.manager import NavGoalSpec, NavigationError
from core_features.vision import MODEL_STATUS_TOPICS, PREVIEW_TOPIC
from interfaces.srv import Emotion, PilotRecordingStart, SetLed
from tf2_ros import Buffer, TransformListener

# 늦게 뜬 노드도 현재 모드를 즉시 받도록 latch 한다 (PWR-003).
_LATCHED = QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE,
                      durability=DurabilityPolicy.TRANSIENT_LOCAL)


class RosBridge(RosBridgeHelpersMixin):
    def __init__(self, node: Node, services) -> None:
        self._node = node
        self._svc = services
        self._bounded_trial_guard = None
        self._readiness = getattr(services, "readiness", None)
        cfg = services.config
        self._frame_prefix = str(cfg.get("robot", {}).get("frame_prefix", ""))
        self._base_frame = f"{self._frame_prefix}base_footprint"
        self._map_frame = "map"
        self._state_hz = float(cfg.get("state", {}).get("rate_hz", 10.0))

        self.cmd_vel_pub = node.create_publisher(Twist, "cmd_vel", 10)
        self.initialpose_pub = node.create_publisher(PoseWithCovarianceStamped, "initialpose", 10)

        self.nav_client = ActionClient(node, NavigateToPose, "navigate_to_pose")
        self.route_client = ActionClient(node, NavigateThroughPoses, "navigate_through_poses")
        self.tf_buffer = Buffer(cache_time=Duration(seconds=10.0))
        self.tf_listener = TransformListener(self.tf_buffer, node)

        node.create_subscription(Odometry, "odom", self._on_odom, 10)
        node.create_subscription(Float32, "battery/voltage", self._on_battery, 10)
        node.create_subscription(Twist, "nav_cmd_vel", self._on_nav_cmd_vel, 10)
        node.create_subscription(String, "line/observation", self._on_line_observation, 10)
        node.create_subscription(String, "line/keep_debug", self._on_lane_perception, 1)
        node.create_subscription(String, "detection_evidence", self._on_detection_evidence, 10)
        node.create_subscription(String, "road/observation", self._on_road_observation, 10)
        node.create_subscription(String, "dock/observation", self._on_dock_observation, 10)
        preview_qos = QoSProfile(depth=1, reliability=ReliabilityPolicy.BEST_EFFORT)
        node.create_subscription(CompressedImage, PREVIEW_TOPIC, self._on_camera_preview, preview_qos)
        node.create_subscription(CompressedImage, RAW_PREVIEW_TOPIC, self._on_camera_raw_preview, preview_qos)
        lane_topic, object_topic = MODEL_STATUS_TOPICS
        node.create_subscription(String, lane_topic, self._on_lane_model_status, _LATCHED)
        node.create_subscription(String, object_topic, self._on_object_det_model_status, _LATCHED)
        node.create_subscription(TransitionEvent, "amcl/transition_event", self._on_amcl_transition, 10)
        node.create_subscription(TransitionEvent, "map_server/transition_event", self._on_map_server_transition, 10)
        node.create_subscription(TransitionEvent, "slam_toolbox/transition_event", self._on_slam_transition, 10)
        node.create_subscription(TransitionEvent, "controller_server/transition_event", self._on_controller_transition, 10)
        node.create_subscription(TransitionEvent, "local_costmap/local_costmap/transition_event",
                                 self._on_local_costmap_transition, 10)
        node.create_subscription(TransitionEvent, "global_costmap/global_costmap/transition_event",
                                 self._on_global_costmap_transition, 10)
        node.create_subscription(Bool, "motor/ready", self._on_motor_ready, _LATCHED)
        node.create_subscription(String, "motor/health", self._on_motor_health, 10)
        node.create_subscription(String, "robot/hitl_request", self._on_hitl_request, 10)
        node.create_subscription(String, "robot/degraded_modules", self._on_degraded_modules, 10)
        node.create_subscription(LaserScan, "scan", self._on_scan, qos_profile_sensor_data)
        node.create_subscription(Imu, "imu_raw", self._on_imu, qos_profile_sensor_data)
        node.create_subscription(Range, "us_sensor/range", self._on_us_range, qos_profile_sensor_data)
        node.create_subscription(BatteryState, "batt_state", self._on_batt_state, 10)
        node.create_subscription(OccupancyGrid, "map", self._on_map, _LATCHED)
        node.create_subscription(Path, "plan", self._on_plan, 10)
        node.create_subscription(Costmap, "local_costmap/costmap_raw", self._on_local_costmap, 10)
        node.create_subscription(Costmap, "global_costmap/costmap_raw", self._on_global_costmap, 10)
        node.create_subscription(String, "localization/state", self._on_loc_state, _LATCHED)
        node.create_subscription(String, "localization/candidates", self._on_loc_candidates, _LATCHED)
        node.create_subscription(String, "localization/result", self._on_loc_result, 10)
        node.create_subscription(String, STATUS_TOPIC, self._on_pilot_recorder_status, _LATCHED)
        node.create_subscription(String, device_power.DEVICE_READY_TOPIC, self._on_device_ready, 10)

        self.power_mode_pub = node.create_publisher(String, "power/mode", _LATCHED)
        self.display_info_pub = node.create_publisher(String, "display/info", 10)
        self.dock_exemption_pub = node.create_publisher(Bool, "docking/collision_exemption", _LATCHED)
        self.loc_decision_pub = node.create_publisher(String, "localization/decision", 5)
        self.loc_suspect_pub = node.create_publisher(String, "localization/suspect", 5)
        self.loc_mission_pub = node.create_publisher(String, "localization/mission", 5)
        self.intent_pub = node.create_publisher(String, TELEOP_INTENT_TOPIC, 10)
        self.pilot_fetched_pub = node.create_publisher(String, FETCHED_TOPIC, 5)
        self.route_context_pub = None
        if services.line_follow.config.route_context_enabled:
            route_qos = QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE,
                                   durability=DurabilityPolicy.VOLATILE)
            self.route_context_pub = node.create_publisher(String, "line/route_context", route_qos)
        self._route_context_output = RouteContextPublication()
        self._lane_guide_pub = node.create_publisher(String, "line/lane_guide", 10)
        self._lane_guide_output = RouteGuidePublication()
        self.devices_pub = node.create_publisher(String, device_power.DEVICES_TOPIC, _LATCHED)
        self._led_client = node.create_client(SetLed, "set_led")
        self._emotion_client = node.create_client(Emotion, "set_emotion")
        self._lidar_start_client = node.create_client(Empty, "start_motor")
        self._lidar_stop_client = node.create_client(Empty, "stop_motor")
        self._pilot_recorder_client = node.create_client(SetBool, SET_ACTIVE_SERVICE)
        self._pilot_recording_start_client = node.create_client(PilotRecordingStart, START_SERVICE)
        board = device_power.DeviceBoard(lambda data: self.devices_pub.publish(String(data=data)))
        self._device_ports = {
            name: (device_power.ServiceDevicePort(name, self._send_lidar)
                   if name == device_power.LIDAR
                   else device_power.TopicDevicePort(name, board))
            for name in services.power.devices}
        self._device_applied: dict = dict.fromkeys(services.power.managed_devices())

        self._cmd_timer = node.create_timer(1.0 / 50.0, cmd_gap := CycleGapWatch(self._publish_cmd_vel))
        self._state_timer = node.create_timer(1.0 / self._state_hz, self._tick_state)
        self._diag_timer = node.create_timer(1.0, cmd_gap.reporting(self._tick_diagnostics, node.get_logger().warning))
        self._power_timer = node.create_timer(1.0 / 5.0, self._tick_power)
        self._dock_timer = node.create_timer(1.0 / 20.0, self._tick_docking)
        self._dock_ticks = 0
        self._swarm_timer = node.create_timer(1.0 / 5.0, self._tick_swarm)
        self._line_follow_timer = node.create_timer(1.0 / 20.0, self._tick_line_follow)
        self._goals = GoalTracker()

        self._init_bridge_state(node, services)
        self._map_pose_ts: float = float('-inf')
        self._map_pose_lease = map_pose.MapPoseLease()

        self._setup_diagnostics()
        self._svc.advisory_feed.bind_clock(
            lambda: self._node.get_clock().now().nanoseconds / 1e9)
        self._svc.nav.executor = self
        self._svc.nav.clock = lambda: self._node.get_clock().now().nanoseconds / 1e9
        self._line_clock = traffic_gate.line_clock(
            bool(node.get_parameter("use_sim_time").value),
            lambda: self._node.get_clock().now().nanoseconds / 1e9)
        self._svc.line_follow.bind_clock(self._line_clock)
        self._svc.loc_mission.bind_clock(self._line_clock)
        self._svc.docking.bind_clock(self._line_clock)
        self.docking_executor = BridgeDockingExecutor(
            self._svc, send_goal=self.send_goal, cancel_goal=self.cancel_goal,
            publish_exemption=lambda on: self.dock_exemption_pub.publish(Bool(data=on)),
            odom_pose=lambda: self._last_odom_pose, info=self._node.get_logger().info,
            transport_snapshot=self._goals.transport_snapshot)
        self._svc.docking.executor = self.docking_executor
        loc = self._svc.localization
        loc.clock = lambda: self._node.get_clock().now().nanoseconds / 1e9
        loc.bind_clock(self._line_clock)
        loc.publish_decision = lambda body: self.loc_decision_pub.publish(String(data=json.dumps(body)))
        loc.publish_suspect = lambda body: self.loc_suspect_pub.publish(String(data=json.dumps(body)))
        self._svc.loc_mission.publish = (
            lambda body: self.loc_mission_pub.publish(String(data=json.dumps(body))))
        self._svc.command.intent_sink = lambda **fields: self.intent_pub.publish(
            String(data=json.dumps(teleop_intent(**fields))))
        self._node.get_logger().info("ros_bridge ready (cmd_vel sole publisher @50Hz)")

    def _on_odom(self, msg: Odometry) -> None:
        self._last_odom_ts = time.monotonic()
        sample = odometry.receive_odom(self, msg, station=self._svc.station_docking)
        if odometry.odom_owns_pose(self._map_pose_ts, self._line_clock()):
            self._svc.state.set_pose(sample["x"], sample["y"], sample["yaw"], frame="odom")
        self._svc.state.set_velocity(sample["linear_x"], sample["angular_z"])
        self._last_odom_pose = (sample["x"], sample["y"], sample["yaw"])
        self._svc.nav.on_pose_progress(sample["x"], sample["y"])
        self._svc.loc_mission.observe_odom(sample["x"], sample["y"], sample["yaw"])

    def _on_lane_model_status(self, msg: String) -> None:
        self._svc.vision.models.accept("perception/learned/status", msg.data, now=time.monotonic())

    def _on_object_det_model_status(self, msg: String) -> None:
        self._svc.vision.models.accept("perception/learned/object_det/status", msg.data,
                                       now=time.monotonic())

    def _on_line_observation(self, msg: String) -> None:
        """Accept normalized evidence only; malformed or wrong-source data cannot drive."""
        source_now = self._node.get_clock().now().nanoseconds * 1e-9
        observation.line_observation(
            self._svc, msg.data,
            source_now=source_now, received_at=self._line_clock(),
            expected_context_seq=self._current_route_context_seq(source_now))

    def _on_road_observation(self, msg: String) -> None:
        """Decode road evidence; invalid data invalidates an enforced lease."""
        source_now = self._node.get_clock().now().nanoseconds * 1e-9
        observation.road_observation(
            self._svc, msg.data,
            source_now=source_now, received_at=self._line_clock())

    def _tick_line_follow(self) -> None:
        guide = (self._svc.line_follow.route_guide()
                 if self._svc.line_follow.active and self._svc.line_follow.config.route_guide_enabled
                 and not self._svc.safety.estop else None)
        for message in self._lane_guide_output.messages(guide, self._node.get_clock().now().nanoseconds / 1e9):
            self._lane_guide_pub.publish(String(data=json.dumps(message)))
        self._svc.loc_mission.tick()
        self._tick_trail()
        if not self._svc.line_follow.active or self._svc.safety.estop:
            self._publish_route_context(None)
            return
        now = self._line_clock()
        decision = self._svc.line_follow.tick(now)
        if self.route_context_pub is not None:
            ros_now = self._node.get_clock().now().nanoseconds / 1e9
            self._publish_route_context(
                self._svc.line_follow.route_context(ros_now=ros_now, now=now),
                ros_now=ros_now)
        command_now = None if self._line_clock is time.monotonic else time.monotonic()
        traffic_gate.apply_line_candidate(
            self._svc.line_follow,
            self._svc.traffic_policy,
            self._svc.command,
            decision,
            now,
            command_now,
        )
        status = self._svc.line_follow.status()
        self._svc.state.set_line_follow(status)
        self._svc.state.set_sensor("line_follow", status.model_dump())
        traffic_status = self._svc.traffic_policy.status()
        self._svc.state.set_traffic_policy(traffic_status)
        self._svc.state.set_sensor("traffic_policy", traffic_status.model_dump())

    @staticmethod
    def _lifecycle_active(msg: TransitionEvent) -> bool:
        goal = getattr(msg, "goal_state", None)
        state_id = getattr(goal, "id", None)
        if state_id is not None:
            try:
                return int(state_id) == 3  # lifecycle_msgs/State.PRIMARY_STATE_ACTIVE
            except (TypeError, ValueError):
                pass
        return str(getattr(goal, "label", "")).strip().lower() == "active"

    def _on_map_server_transition(self, msg: TransitionEvent) -> None:
        map_observation.lifecycle(self, self._lifecycle_active(msg))
        if self._readiness is not None:
            self._readiness.observe("map_server", self._lifecycle_active(msg))

    def _on_slam_transition(self, msg: TransitionEvent) -> None:
        map_observation.lifecycle(self, self._lifecycle_active(msg))
        if self._readiness is not None:
            self._readiness.observe("slam_toolbox", self._lifecycle_active(msg))

    def _publish_cmd_vel(self) -> None:
        cmd_vel_cycle(self._svc.command, self._svc.power, self._send_twist,
                      self._readiness, warn=self._node.get_logger().error,
                      trial_guard=self._bounded_trial_guard,
                      motion_ready=lambda: docking_mode.motion_ready(self._svc),
                      notify_written=self._note_wheels)

    def _send_twist(self, out: CoreTwist) -> None:
        msg = Twist()
        msg.linear.x = out.linear
        msg.angular.z = out.angular
        self.cmd_vel_pub.publish(msg)

    def _tick_state(self) -> None:
        map_pose.receive_map_pose(self, lambda: self.tf_buffer.lookup_transform(
            self._map_frame, self._base_frame, rclpy.time.Time()))
        self._svc.localization.tick(odometry.odom_owns_pose(self._map_pose_ts, self._line_clock()))
        snapshot = self._svc.state.snapshot()
        self._svc.power.on_robot_mode(snapshot.mode)

    def _on_map(self, msg: OccupancyGrid) -> None:
        map_observation.receive_map(self, msg, warn=self._node.get_logger().warning)

    def _tick_power(self) -> None:
        if self._svc.fleet_loss is not None:
            try:
                self._svc.fleet_loss.tick()
            except Exception:
                self._node.get_logger().error(f"fleet_loss tick failed:\n{traceback.format_exc()}")
        try:
            self._svc.nav.expire_goal_lease()
        except Exception:
            self._node.get_logger().error(f"goal lease tick failed:\n{traceback.format_exc()}")
        power = self._svc.power
        power.tick()
        self._svc.calibration.expire_due()
        self._svc.trip_lease.expire_due()
        status = power.status()
        self._svc.state.set_power(status)
        self._reconcile_power_outputs(status)

    def _setup_diagnostics(self) -> None:
        self.diagnostics = DiagnosticsCollector()
        self.diagnostics.register("core", lambda: HealthState.OK)
        self.diagnostics.register("cpu", CpuLoadProvider())
        self.diagnostics.register("memory", MemoryAvailableProvider())
        self.diagnostics.register("disk", disk_provider("/"))
        self.diagnostics.register("odom_topic", topic_freshness_provider(
            lambda: self._last_odom_ts, stale_s=2.0))

    # --- NavExecutor 구현 (navigation.manager와 계약) -------------------------

    def send_goal(self, spec: NavGoalSpec, *, correlation_id: str | None = None) -> None:
        self.send_native_goal(spec, None, correlation_id=correlation_id)

    def send_native_goal(self, spec: NavGoalSpec, native_run_id,
                         *, correlation_id: str | None = None) -> None:
        goal, through = nav_goal.build(spec, self._node.get_clock().now().to_msg())
        client = self.route_client if through else self.nav_client
        if not client.wait_for_server(timeout_sec=0.0):
            self._node.get_logger().warn("navigation action server not ready; goal queued anyway")
        generation = self._goals.opening(correlation_id, native_run_id)
        future = client.send_goal_async(goal)
        future.add_done_callback(lambda done, gen=generation: self._goal_response_cb(done, gen))
        goal_tracker.watch_response(self._goals, self._svc.nav, future, generation)

    def cancel_goal(self) -> None:
        handles = self._goals.cancel_all()
        for handle in handles:
            handle.cancel_goal_async()
        if handles:
            self._node.get_logger().info(f"navigation cancel requested ({len(handles)} goal(s))")

    def native_transport_snapshot(self):
        return self._goals.transport_snapshot()

    def send_initial_pose(self, x: float, y: float, yaw: float) -> None:
        msg = PoseWithCovarianceStamped()
        msg.header.frame_id = self._map_frame
        msg.header.stamp = self._node.get_clock().now().to_msg()
        msg.pose.pose.position.x = x
        msg.pose.pose.position.y = y
        msg.pose.pose.orientation.z = math.sin(yaw / 2.0)
        msg.pose.pose.orientation.w = math.cos(yaw / 2.0)
        msg.pose.covariance = amcl_pose_covariance()
        self.initialpose_pub.publish(msg)

    def save_map(self, name: str) -> str:
        """NAV-005: slam_toolbox SaveMap 호출 → map_id 발급 (D-13)."""
        if self._slam_client is None:
            raise RuntimeError(
                "slam_toolbox is not installed in this runtime; map saving is unavailable")
        if not self._slam_client.wait_for_service(timeout_sec=1.0):
            raise RuntimeError("slam_toolbox save_map service unavailable")
        output_stem = save_map.resolve_output_stem(
            name, os.environ.get("ROSY_MAP_OUTPUT_DIR", "/var/lib/rosy/maps")
        )
        request = self._slam_client.srv_type.Request()
        request.name = String(data=output_stem)
        response = save_map.await_call(
            self._slam_client.call_async(request), timeout=15.0)
        save_map.check_result(response.result)
        return save_map.map_id(name, save_map.saved_bytes(output_stem), time.time())

    def reset_mapping(self) -> None:
        """NAV-005 세션 초기화 — CAPABILITY_NOT_SUPPORTED 로 실패 (CAP-003)."""
        raise NavigationError(
            "CAPABILITY_NOT_SUPPORTED",
            "slam_toolbox reset is not implemented in this runtime")
