"""core.bridge.ros_bridge — ROS-101 모든 ROS I/O 집중 (P1-3).

유일한 cmd_vel 퍼블리셔 (D-2, 50 Hz) · 구독·발행·서비스·7타이머·Nav2 액션·TF 전부
여기에만 (목록은 `test/test_bridge_timers.py`가 고정). 판정은 하지 않는다: 값을
정하는 일은 ROS-free 시블리(`observation`, `goal_tracker`, `reconcile`, `display`,
`save_map`, `translate`)로 빠져 있고, 이 파일은 적응과 전달만 한다 — 그 자리가
호스트 pytest 에서 도달 불가능하기 때문이다.
"""

from __future__ import annotations

import json
import math
import os
import time
from typing import Optional

import rclpy
from rclpy.action import ActionClient
from rclpy.node import Node

from geometry_msgs.msg import PoseWithCovarianceStamped, Twist
from nav_msgs.msg import OccupancyGrid, Odometry, Path
from nav2_msgs.action import NavigateToPose
from nav2_msgs.msg import Costmap
from lifecycle_msgs.msg import TransitionEvent
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy, qos_profile_sensor_data
from sensor_msgs.msg import BatteryState, CompressedImage, Imu, LaserScan, Range
from std_msgs.msg import Bool, Float32, String
from std_srvs.srv import Empty

from core.bridge import (
    battery_policy,
    display,
    docking_mode,
    goal_tracker,
    observation,
    odometry,
    reconcile,
    save_map,
    traffic_gate,
    translate,
)
from core.bridge.cmd_vel import cmd_vel_cycle
from core.bridge.goal_tracker import GoalTracker
from core_features.maps import occupancy_map_id
from core_features.navigation.initial_pose import amcl_pose_covariance
from interfaces.srv import SetLed
import tf2_ros
from tf2_ros import Buffer, TransformListener

from core_features.command.manager import Twist as CoreTwist
from core_features.diagnostics.collector import (
    CpuLoadProvider,
    DiagnosticsCollector,
    MemoryAvailableProvider,
    disk_provider,
    topic_freshness_provider,
)
from core_features.navigation.manager import NavGoalSpec, NavigationError
from core_common.protocol.schemas import HealthState

# 늦게 뜬 노드도 현재 모드를 즉시 받도록 latch 한다 (PWR-003).
_LATCHED = QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE,
                      durability=DurabilityPolicy.TRANSIENT_LOCAL)


class RosBridge:
    def __init__(self, node: Node, services) -> None:
        self._node = node
        self._svc = services
        self._readiness = getattr(services, "readiness", None)
        cfg = services.config
        self._frame_prefix = str(cfg.get("robot", {}).get("frame_prefix", ""))
        self._base_frame = f"{self._frame_prefix}base_footprint"
        self._map_frame = "map"
        self._state_hz = float(cfg.get("state", {}).get("rate_hz", 10.0))

        self.cmd_vel_pub = node.create_publisher(Twist, "cmd_vel", 10)
        self.initialpose_pub = node.create_publisher(
            PoseWithCovarianceStamped, "initialpose", 10)

        self.nav_client = ActionClient(node, NavigateToPose, "navigate_to_pose")
        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, node)

        node.create_subscription(Odometry, "odom", self._on_odom, 10)
        node.create_subscription(Float32, "battery/voltage", self._on_battery, 10)
        node.create_subscription(Twist, "nav_cmd_vel", self._on_nav_cmd_vel, 10)
        node.create_subscription(String, "line/observation", self._on_line_observation, 10)
        # D-137 T4: 검출 증거는 boxes 토픽과 분리된 evidence 채널로 들어온다
        # (D-136 §2). 판정은 ROS-free 피드가 하고, 이 파일은 적응만 한다.
        node.create_subscription(String, "detection_evidence",
                                 self._on_detection_evidence, 10)
        node.create_subscription(String, "road/observation", self._on_road_observation, 10)
        # 주차형 도크: control 의 dock_observer_node 가 태그를 base_link 로 풀어 낸 증거.
        node.create_subscription(String, "dock/observation", self._on_dock_observation, 10)
        preview_qos = QoSProfile(
            depth=1, reliability=ReliabilityPolicy.BEST_EFFORT)
        node.create_subscription(
            CompressedImage, "camera/preview/compressed",
            self._on_camera_preview, preview_qos)
        # Nav2 lifecycle nodes announce their authoritative goal state on
        # transition_event.  CORE never infers readiness from node discovery;
        # it requires these active transitions plus the motor adapter lease.
        node.create_subscription(TransitionEvent, "amcl/transition_event",
                                 self._on_amcl_transition, 10)
        node.create_subscription(TransitionEvent, "map_server/transition_event",
                                 self._on_map_server_transition, 10)
        node.create_subscription(TransitionEvent, "slam_toolbox/transition_event",
                                 self._on_slam_transition, 10)
        node.create_subscription(TransitionEvent, "controller_server/transition_event",
                                 self._on_controller_transition, 10)
        node.create_subscription(TransitionEvent, "local_costmap/local_costmap/transition_event",
                                 self._on_local_costmap_transition, 10)
        node.create_subscription(TransitionEvent, "global_costmap/global_costmap/transition_event",
                                 self._on_global_costmap_transition, 10)
        node.create_subscription(Bool, "motor/ready", self._on_motor_ready, _LATCHED)
        node.create_subscription(String, "robot/hitl_request", self._on_hitl_request, 10)
        node.create_subscription(String, "robot/degraded_modules", self._on_degraded_modules, 10)
        node.create_subscription(LaserScan, "scan", self._on_scan, qos_profile_sensor_data)
        node.create_subscription(Imu, "imu_raw", self._on_imu, qos_profile_sensor_data)
        node.create_subscription(Range, "us_sensor/range", self._on_us_range, qos_profile_sensor_data)
        node.create_subscription(BatteryState, "batt_state", self._on_batt_state, 10)
        node.create_subscription(OccupancyGrid, "map", self._on_map, _LATCHED)
        node.create_subscription(Path, "plan", self._on_plan, 10)
        # `_raw` 만 구독한다 — `costmap`(OccupancyGrid) 쪽은 타입이 안 맞아 영원히 무음이다. 근거는 bridge/AGENTS.md.
        node.create_subscription(Costmap, "local_costmap/costmap_raw", self._on_local_costmap, 10)
        node.create_subscription(Costmap, "global_costmap/costmap_raw", self._on_global_costmap, 10)

        self.power_mode_pub = node.create_publisher(String, "power/mode", _LATCHED)
        self.display_info_pub = node.create_publisher(String, "display/info", 10)
        self.dock_exemption_pub = node.create_publisher(
            Bool, "docking/collision_exemption", _LATCHED)
        self._led_client = node.create_client(SetLed, "set_led")
        # sllidar_ros2가 제공하는 모터 제어 서비스 (PWR-005).
        self._lidar_start_client = node.create_client(Empty, "start_motor")
        self._lidar_stop_client = node.create_client(Empty, "stop_motor")

        self._cmd_timer = node.create_timer(1.0 / 50.0, self._publish_cmd_vel)
        self._state_timer = node.create_timer(1.0 / self._state_hz, self._tick_state)
        self._diag_timer = node.create_timer(1.0, self._tick_diagnostics)
        self._power_timer = node.create_timer(1.0 / 5.0, self._tick_power)
        # 20 Hz while a parking run moves (DockingManager.fast_tick), 5 Hz
        # otherwise: docking_mode.due() skips 3 in 4 calls.
        self._dock_timer = node.create_timer(1.0 / 20.0, self._tick_docking)
        self._dock_ticks = 0
        self._swarm_timer = node.create_timer(1.0 / 5.0, self._tick_swarm)
        self._line_follow_timer = node.create_timer(1.0 / 20.0, self._tick_line_follow)
        self._goals = GoalTracker()

        self._last_odom_ts = 0.0
        self._last_odom_xy = None
        self._last_odom_pose = None
        self._dock_odom_mark = None
        self._applied_dock_exemption = False
        # 최상단 임포트는 노드 기동 전체를 실패시킨다(core 에 없고 slam: false).
        # 여기서 시도하고, 클라이언트는 생성자에서 만들어야 DDS 엔드포인트 매칭에
        # 노드 수명만큼의 시간이 주어진다.
        self._slam_client = None
        try:
            from slam_toolbox.srv import SaveMap
        except ImportError as exc:
            node.get_logger().warning(
                f"slam_toolbox unavailable; map saving disabled ({exc})")
        else:
            self._slam_client = node.create_client(SaveMap, "slam_toolbox/save_map")

        self._published_power_mode: Optional[str] = None
        # 드라이버는 core보다 먼저 떠서 이미 회전 중이다 — 기동 시 불필요한 호출 방지.
        self._applied_lidar_spinning = True
        self._info_was_visible = False
        self._applied_led = None
        self._info_last_pub = 0.0
        self._voltage_topic_seen = False
        self._api_address: Optional[str] = None
        #: map→base TF 를 마지막으로 읽은 시각. 이것이 신선하면 odom 은 pose 를 건드리지
        #: 않는다. 지역화가 없는 구성(맵도 SLAM 도 없는 teleop)에서는 만료되고, 그때만
        #: odom 이 화면에 무엇이라도 띄우는 폴백이 된다.
        self._map_pose_ts: float = 0.0

        self._setup_diagnostics()
        # D-137 T4: 자문 피드의 시계를 노드 시계로 맞춘다. 패킷의 observed_at은
        # ROS epoch 기준이라, monotonic 기본값과 섞이면 모든 패킷이 영원히
        # stale이 되어 자문이 한 번도 살지 못한다.
        self._svc.advisory_feed.bind_clock(
            lambda: self._node.get_clock().now().nanoseconds / 1e9)
        self._svc.nav.executor = self
        # NAV-006 무진척 시계를 ROS 시계로 바꾼다. `use_sim_time` 이 켜진 시뮬에서는 이것이
        # sim clock 이라, 느리게 도는 기계에서도 "30 초"가 시뮬 30 초를 뜻한다. 실기에서는
        # 시스템 시계와 같아 동작이 달라지지 않는다.
        self._svc.nav.clock = lambda: self._node.get_clock().now().nanoseconds / 1e9
        # Line/road evidence staleness (0.3 s) and loss (3 s) run on one clock:
        # sim seconds under `use_sim_time` (a Gazebo at RTF 0.25 otherwise ages a
        # 5 Hz frame 0.8 s of wall time and HOLDs), `time.monotonic` on Device.
        self._line_clock = traffic_gate.line_clock(
            bool(node.get_parameter("use_sim_time").value),
            lambda: self._node.get_clock().now().nanoseconds / 1e9)
        self._svc.line_follow.bind_clock(self._line_clock)
        # The dock observation feed is stamped on the same clock, so the
        # docking manager judges tag freshness and phase timeouts on it too.
        self._svc.docking.bind_clock(self._line_clock)
        self._svc.docking.executor = self
        self._node.get_logger().info("ros_bridge ready (cmd_vel sole publisher @50Hz)")

    def _on_odom(self, msg: Odometry) -> None:
        self._last_odom_ts = time.monotonic()
        sample = translate.odom_sample(msg)
        if odometry.odom_owns_pose(self._map_pose_ts, time.monotonic()):
            # map 프레임 pose 가 없을 때만 odom 이 보고 pose 를 쓴다 (규칙은 odometry.py).
            self._svc.state.set_pose(sample["x"], sample["y"], sample["yaw"])
        self._svc.state.set_velocity(sample["linear_x"], sample["angular_z"])
        self._last_odom_xy = (sample["x"], sample["y"])
        self._last_odom_pose = (sample["x"], sample["y"], sample["yaw"])
        self._svc.nav.on_pose_progress(sample["x"], sample["y"])

    def _on_battery(self, msg: Float32) -> None:
        self._voltage_topic_seen = True
        battery_policy.apply_voltage(self._svc, float(msg.data))

    def _on_detection_evidence(self, msg: String) -> None:
        observation.detection_evidence(self._svc, msg.data)

    def _on_nav_cmd_vel(self, msg: Twist) -> None:
        # Docking owns the nav slot rules (NAVIGATION, or DOCKING+STAGING);
        # line-follow still blocks Nav2 output there.
        docking_mode.route_nav_cmd_vel(
            self._svc, CoreTwist(linear=msg.linear.x, angular=msg.angular.z))

    def _on_line_observation(self, msg: String) -> None:
        """Accept normalized evidence only; malformed or wrong-source data cannot drive."""
        source_now = self._node.get_clock().now().nanoseconds * 1e-9
        # received_at runs on the line clock (sim seconds under use_sim_time).
        observation.line_observation(
            self._svc, msg.data,
            source_now=source_now, received_at=self._line_clock())

    def _on_road_observation(self, msg: String) -> None:
        """Decode road evidence; invalid data invalidates an enforced lease."""
        source_now = self._node.get_clock().now().nanoseconds * 1e-9
        observation.road_observation(
            self._svc, msg.data,
            source_now=source_now, received_at=self._line_clock())

    def _on_dock_observation(self, msg: String) -> None:
        """Tag evidence only; a malformed payload clears the feed (lost, not guessed)."""
        try:
            self._svc.dock_feed.ingest(
                json.loads(msg.data), received_at=self._line_clock(),
                source_now=self._node.get_clock().now().nanoseconds * 1e-9)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            self._node.get_logger().warning(
                f"ignored dock observation: {exc}", throttle_duration_sec=5.0)

    def _on_camera_preview(self, msg: CompressedImage) -> None:
        observation.camera_preview(
            self._svc, msg, warn=self._node.get_logger().warning)

    def _tick_line_follow(self) -> None:
        if not self._svc.line_follow.active:
            return
        now = self._line_clock()
        decision = self._svc.line_follow.tick(now)
        # CommandManager.select_output() ages the nav twist on time.monotonic.
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
        self._svc.state.set_sensor(
            "traffic_policy", traffic_status.model_dump())

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

    def _on_amcl_transition(self, msg: TransitionEvent) -> None:
        if self._readiness is not None:
            self._readiness.observe("amcl", self._lifecycle_active(msg))

    def _on_map_server_transition(self, msg: TransitionEvent) -> None:
        if self._readiness is not None:
            self._readiness.observe("map_server", self._lifecycle_active(msg))

    def _on_slam_transition(self, msg: TransitionEvent) -> None:
        if self._readiness is not None:
            self._readiness.observe("slam_toolbox", self._lifecycle_active(msg))

    def _on_controller_transition(self, msg: TransitionEvent) -> None:
        if self._readiness is not None:
            self._readiness.observe("controller_server", self._lifecycle_active(msg))

    def _on_local_costmap_transition(self, msg: TransitionEvent) -> None:
        if self._readiness is not None:
            self._readiness.observe("local_costmap", self._lifecycle_active(msg))

    def _on_global_costmap_transition(self, msg: TransitionEvent) -> None:
        if self._readiness is not None:
            self._readiness.observe("global_costmap", self._lifecycle_active(msg))

    def _on_motor_ready(self, msg: Bool) -> None:
        if self._readiness is not None:
            self._readiness.observe("motor_adapter", bool(msg.data), lease=True)

    def _publish_cmd_vel(self) -> None:
        # 순서(고르기 → HOLD 면 0 → 바퀴 → 절전 관측·SAF-002 알림)는
        # cmd_vel_cycle 이 정한다 (rclpy 없이 검사되는 자리).
        cmd_vel_cycle(self._svc.command, self._svc.power, self._send_twist,
                      self._readiness, warn=self._node.get_logger().error)

    def _send_twist(self, out: CoreTwist) -> None:
        msg = Twist()
        msg.linear.x = out.linear
        msg.angular.z = out.angular
        self.cmd_vel_pub.publish(msg)

    def _tick_state(self) -> None:
        try:
            tf = self.tf_buffer.lookup_transform(
                self._map_frame, self._base_frame, rclpy.time.Time())
            t = tf.transform.translation
            q = tf.transform.rotation
            yaw = math.atan2(2.0 * (q.w * q.z + q.x * q.y), 1.0 - 2.0 * (q.y ** 2 + q.z ** 2))
            self._svc.state.set_pose(t.x, t.y, yaw)
            self._map_pose_ts = time.monotonic()
        except tf2_ros.TransformException:
            pass
        snapshot = self._svc.state.snapshot()
        # 로봇 모드가 IDLE이 아니면 절전 진입을 막는다 (PWR-001 안전 인터록).
        self._svc.power.on_robot_mode(snapshot.mode)

    def _on_map(self, msg: OccupancyGrid) -> None:
        try:
            grid = translate.grid_from_occupancy(msg)
            self._svc.maps.set_map(grid)
            current = self._svc.state.map_id
            if current is None or str(current).startswith("occupancy:"):
                self._svc.state.set_map_id(occupancy_map_id(grid))
        except ValueError as exc:
            self._node.get_logger().warning(f"ignored occupancy map: {exc}")

    def _on_plan(self, msg: Path) -> None:
        observation.nav_path(self._svc, msg,
                             warn=self._node.get_logger().warning)

    def _on_local_costmap(self, msg: Costmap) -> None:
        observation.nav_costmap(self._svc, "local", msg,
                                warn=self._node.get_logger().warning)

    def _on_global_costmap(self, msg: Costmap) -> None:
        observation.nav_costmap(self._svc, "global", msg,
                                warn=self._node.get_logger().warning)

    def _on_scan(self, msg: LaserScan) -> None:
        self._svc.state.set_sensor("lidar", translate.lidar_sample(msg, time.time()))

    def _on_imu(self, msg: Imu) -> None:
        self._svc.state.set_sensor("imu", translate.imu_sample(msg, time.time()))

    # --- PWR-002~004 근접 웨이크 --------------------------------------------

    def _on_us_range(self, msg: Range) -> None:
        observation.us_range(self._svc, msg, received_at=time.time())

    def _on_batt_state(self, msg: BatteryState) -> None:
        observation.batt_state(
            self._svc, msg, received_at=time.time(),
            voltage_topic_seen=self._voltage_topic_seen)

    def _tick_power(self) -> None:
        power = self._svc.power
        power.tick()
        status = power.status()
        self._svc.state.set_power(status)

        if status.mode.value != self._published_power_mode:
            self._published_power_mode = status.mode.value
            self.power_mode_pub.publish(String(data=status.mode.value.lower()))

        self._reconcile_lidar(status.lidar_spinning)

        now = time.monotonic()
        if display.republish_due(status.info_visible, self._info_was_visible,
                                 now, self._info_last_pub):
            self._publish_display_info(status)
            self._info_last_pub = now
        self._info_was_visible = status.info_visible

        self._reconcile_led(status.info_visible, now)

    def _publish_display_info(self, status) -> None:
        payload = display.info_payload(
            self._svc.state.snapshot(), status,
            health=self.diagnostics.summary_health().value,
            address=self._api_endpoint(),
            hold_s=self._svc.power.info_hold_s,
        )
        self.display_info_pub.publish(String(data=json.dumps(payload)))

    def _api_endpoint(self) -> str:
        """정보 화면에 띄울 접속 주소. 한 번 풀고 캐시한다."""
        if self._api_address is None:
            port = self._svc.config.get("network", {}).get("api_port", 8080)
            self._api_address = display.resolve_api_address(port)
        return self._api_address

    def _reconcile_led(self, info_visible: bool, now: float) -> None:
        """중재 결과에 LED 를 맞춘다 (SAF-005 경보 > 정보창 게이지)."""
        self._applied_led = reconcile.led(
            self._svc.battery.led_alert, self._applied_led,
            info_visible=info_visible,
            gauge_percent=self._svc.state.snapshot().battery.percent,
            now=now,
            act=lambda command: self._call_led(
                command.command, command.r, command.g, command.b))

    def _reconcile_lidar(self, spinning: bool) -> None:
        """LiDAR 는 내비게이션 입력 — 서비스가 늦게 뜨면 latch 없이 다음 틱에 재시도한다."""
        def send() -> bool:
            client = self._lidar_start_client if spinning else self._lidar_stop_client
            if not client.service_is_ready():
                return False
            client.call_async(Empty.Request())
            self._node.get_logger().info(
                "lidar motor %s requested by power policy" % ("start" if spinning else "stop"))
            return True

        _acted, self._applied_lidar_spinning = reconcile.reconcile(
            spinning, self._applied_lidar_spinning, send, latch_on_skip=False)

    def _call_led(self, command: str, r: int, g: int, b: int) -> bool:
        """LED는 부가 표시다 — 서비스가 없으면 조용히 건너뛴다."""
        if not self._led_client.service_is_ready():
            return False
        request = SetLed.Request()
        request.command = command
        request.pixels = []
        request.r, request.g, request.b = r, g, b
        self._led_client.call_async(request)
        return True

    def _on_hitl_request(self, msg: String) -> None:
        observation.hitl_request(self._svc, msg.data,
                                 logger=self._node.get_logger())

    def _on_degraded_modules(self, msg: String) -> None:
        observation.degraded_modules(self._svc, msg.data)

    def _setup_diagnostics(self) -> None:
        self.diagnostics = DiagnosticsCollector()
        self.diagnostics.register("core", lambda: HealthState.OK)
        self.diagnostics.register("cpu", CpuLoadProvider())
        self.diagnostics.register("memory", MemoryAvailableProvider())
        self.diagnostics.register("disk", disk_provider("/"))
        self.diagnostics.register("odom_topic", topic_freshness_provider(
            lambda: self._last_odom_ts, stale_s=2.0))

    def _tick_diagnostics(self) -> None:
        results = self.diagnostics.collect()
        for component, health in results.items():
            self._svc.state.set_diagnostic(component, health)
        if self._readiness is not None:
            self._svc.state.set_diagnostic(
                "navigation_readiness",
                HealthState.OK if self._readiness.snapshot().ready else HealthState.ERROR,
            )

    # --- DockingExecutor 구현 (docking.manager와 계약) -------------------------
    #
    # 정책은 core_features.docking.manager 가 갖고 여기는 조정만 한다 — power/mode 와
    # PWR-005 LiDAR 의도와 같은 형태다.

    def navigate_to(self, pose) -> None:
        """스테이징 주행. 도킹 액션이 Nav2 구간까지 소유하므로 여기서 부른다.

        NavigationManager.goal 을 거치지 않으므로 nav_state 를 먼저 PLANNING
        으로 둔다 — 아니면 도킹이 첫 틱에 지난 주행의 ARRIVED/FAILED 를 읽는다."""
        self._svc.nav.external_goal_sent()
        self.send_goal(NavGoalSpec(x=pose.x, y=pose.y, yaw=pose.yaw))

    def cancel_navigation(self) -> None:
        self.cancel_goal()

    def drive(self, linear: float, angular: float) -> None:
        """접근·후진 속도. 기존 cmd_vel 멀렉서를 통과시킨다.

        도킹 슬롯을 쓴다 — DOCKING 에서만 바퀴에 닿는다. nav 슬롯을 쓰면 DOCKING
        을 떠난 뒤(IDLE → NAVIGATION) 도킹 틱의 값이 'navigation' 으로 나간다.
        """
        self._svc.command.set_docking_twist(CoreTwist(linear=linear, angular=angular))

    def stop(self) -> None:
        self._svc.command.set_docking_twist(CoreTwist(linear=0.0, angular=0.0))

    def set_collision_exemption(self, enabled: bool) -> None:
        """도크는 코스트맵에 장애물로 찍힌다 — 접근 구간에만 면제를 선언한다.

        Nav2 에 이를 끄는 표준 서비스가 없어서 의도를 토픽으로 내보낸다. 실제
        코스트맵 연동은 실기 항목으로 남는다(DOCK_GO).
        """
        if enabled == self._applied_dock_exemption:
            return
        self._applied_dock_exemption = enabled
        self.dock_exemption_pub.publish(Bool(data=bool(enabled)))
        self._node.get_logger().info(
            "docking collision exemption %s" % ("on" if enabled else "off"))

    def reset_odometry_mark(self) -> None:
        self._dock_odom_mark = self._last_odom_xy

    def travelled_m(self) -> float:
        """마크 이후 이동 거리. 언도킹은 센서를 보지 않고 이 값만 쓴다."""
        return odometry.travelled_m(self._dock_odom_mark, self._last_odom_xy)

    def odometry_available(self) -> bool:
        """언도킹 전: 후진 거리를 잴 오도메트리가 들어오고 있는가."""
        return self._last_odom_xy is not None

    def odometry_pose(self):
        """오도메트리 base 포즈 (x, y, yaw) — 주차형 도크의 프레임 사이 전파와 회전."""
        return self._last_odom_pose

    def _tick_swarm(self) -> None:
        """SWM-004 는 마감시각으로 판정한다 — 스트림이 끊기면 아무 프레임도
        오지 않으므로 소켓 쪽에서는 알아챌 수 없다."""
        try:
            self._svc.swarm.tick()
        except Exception as exc:  # 추종 실패가 브리지 루프를 멈추면 안 된다
            self._node.get_logger().warning(f"swarm tick failed: {exc}")

    def _tick_docking(self) -> None:
        docking = self._svc.docking
        self._dock_ticks += 1
        if not docking_mode.due(self._dock_ticks, docking.fast_tick):
            return
        docking_mode.tick(self._svc, self._node.get_logger().warning)

    # --- NavExecutor 구현 (navigation.manager와 계약) -------------------------

    def send_goal(self, spec: NavGoalSpec) -> None:
        goal = NavigateToPose.Goal()
        goal.pose.header.frame_id = spec.frame
        goal.pose.header.stamp = self._node.get_clock().now().to_msg()
        goal.pose.pose.position.x = spec.x
        goal.pose.pose.position.y = spec.y
        goal.pose.pose.orientation.z = math.sin(spec.yaw / 2.0)
        goal.pose.pose.orientation.w = math.cos(spec.yaw / 2.0)
        if not self.nav_client.wait_for_server(timeout_sec=0.0):
            self._node.get_logger().warn("navigate_to_pose server not ready; goal queued anyway")
        generation = self._goals.opening()
        future = self.nav_client.send_goal_async(goal)
        future.add_done_callback(
            lambda done, gen=generation: self._goal_response_cb(done, gen))

    def _goal_response_cb(self, future, generation: int) -> None:
        goal_tracker.on_response(self._goals, self._svc.nav, future, generation,
                                 attach_result=self._attach_result)

    def _attach_result(self, result_future, generation: int) -> None:
        result_future.add_done_callback(
            lambda done, gen=generation: self._result_cb(done, gen))

    def _result_cb(self, future, generation: int) -> None:
        goal_tracker.on_result(self._goals, self._svc.nav, future, generation)

    def cancel_goal(self) -> None:
        handles = self._goals.cancel_all()
        for handle in handles:
            handle.cancel_goal_async()
        if handles:
            self._node.get_logger().info(
                f"navigation cancel requested ({len(handles)} goal(s))")

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
        """NAV-005: slam_toolbox SaveMap 호출 → map_id 발급 (D-13).

        파일을 찾으면 내용 체크섬, 못 찾으면 name+시각 해시로 대체 map_id.
        """
        if self._slam_client is None:
            raise RuntimeError(
                "slam_toolbox is not installed in this runtime; map saving is unavailable")
        if not self._slam_client.wait_for_service(timeout_sec=1.0):
            raise RuntimeError("slam_toolbox save_map service unavailable")
        output_stem = save_map.resolve_output_stem(
            name, os.environ.get("ROSY_MAP_OUTPUT_DIR", "/var/lib/rosy/maps")
        )
        request = self._slam_client.srv_type.Request()
        # SaveMap.srv 의 name 은 string 이 아니라 std_msgs/String 이다.
        request.name = String(data=output_stem)
        response = save_map.await_call(
            self._slam_client.call_async(request), timeout=15.0)
        save_map.check_result(response.result)

        return save_map.map_id(
            name, save_map.saved_bytes(output_stem), time.time()
        )

    def reset_mapping(self) -> None:
        """NAV-005 세션 초기화 — 아직 실기가 없다.

        `hasattr` 뒤에 숨어 있던 자리다. 조용히 건너뛰면 reset 이 200 을 돌려준다 —
        선언해 두고 `CAPABILITY_NOT_SUPPORTED` 로 실패하는 편이 CAP-003 요구다.
        실물은 slam_toolbox `Reset` (구 Flask `nav2_web_server.py`, D-3 이후 삭제).
        """
        raise NavigationError(
            "CAPABILITY_NOT_SUPPORTED",
            "slam_toolbox reset is not implemented in this runtime")
