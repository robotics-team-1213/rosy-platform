"""core.bridge.ros_bridge_helpers — ROS-101 브리지 보조 콜백 및 표시/전원 조정 믹스인.

`ros_bridge.py`의 단일 책임 분리를 위해 센서/상태 어댑터 콜백과 표시·표정·LED·전원
출력을 담당하는 `RosBridgeHelpersMixin`을 제공한다.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Optional

from core.bridge import (
    device_power,
    display,
    docking_mode,
    expression,
    goal_tracker,
    observation,
    pilot_recorder_client,
    thermal_policy,
    translate,
)
from core.bridge.expression_policy import Expression, ExpressionPolicy
from core_common.protocol.schemas import HealthState
from core_features.command.manager import Twist as CoreTwist


class RosBridgeHelpersMixin:
    """Sensor/status subscription adapters and display/power reconciliation helpers."""

    def _init_bridge_state(self, node, services) -> None:
        self._last_odom_ts = 0.0
        self._last_odom_pose = None
        self._wheels_warned_at = -1e9  # D-422 wheels_sent warning throttle (monotonic)
        self._slam_client = None
        try:
            from slam_toolbox.srv import SaveMap
        except ImportError as exc:
            node.get_logger().warning(f"slam_toolbox unavailable; map saving disabled ({exc})")
        else:
            self._slam_client = node.create_client(SaveMap, "slam_toolbox/save_map")

        self._published_power_mode: Optional[str] = None
        self._info_was_visible = False
        self._expression = ExpressionPolicy()
        self._expression_intent = Expression(None)
        self._face_output = expression.ServiceOutput(accept=expression.emotion_accepted)
        self._led_output = expression.ServiceOutput()
        self._hello_until: Optional[float] = None
        self._drive_last_pub: Optional[float] = None
        self._face_desired: Optional[str] = None
        self._face_inputs_last: Optional[dict] = None
        self._face_inputs_at: Optional[float] = None
        self._face_inputs_failed = False
        self._info_last_pub = 0.0
        self._voltage_topic_seen = False
        self._api_address: Optional[str] = None

        guard = services.pilot_recording
        warn = node.get_logger().warn
        guard.request_active = lambda on, wait: pilot_recorder_client.request_active(
            self._pilot_recorder_client, on, wait, warn)
        guard.request_start = lambda mode, wait: pilot_recorder_client.request_start(
            self._pilot_recording_start_client, mode, wait, warn)
        guard.start_available = self._pilot_recording_start_client.service_is_ready
        guard.publish_fetched = lambda rid: self._publish_string(
            self.pilot_fetched_pub, json.dumps({"id": rid}))

    @staticmethod
    def _publish_string(pub, data: str) -> None:
        from std_msgs.msg import String

        pub.publish(String(data=data))

    def _on_pilot_recorder_status(self, msg) -> None:
        try:
            self._svc.pilot_recording.on_status(json.loads(msg.data))
        except (ValueError, TypeError) as exc:
            self._node.get_logger().warn(
                f"pilot recorder status ignored: {exc}", throttle_duration_sec=10.0)

    def _on_battery(self, msg) -> None:
        self._voltage_topic_seen = True
        observation.battery_voltage(self._svc, float(msg.data), received_at=time.time())

    def _on_lane_perception(self, msg) -> None:
        source_now = self._node.get_clock().now().nanoseconds / 1e9
        self._svc.vision.lane_perception.accept(
            msg.data, now=time.monotonic(), source_now=source_now)
        observation.keep_junction(
            self._svc, msg.data, source_now=source_now,
            received_at=self._line_clock(),
            expected_context_seq=self._current_route_context_seq(source_now))

    def _on_detection_evidence(self, msg) -> None:
        observation.detection_evidence(self._svc, msg.data)
        expression.observe(
            self._expression, msg.data, models=self._svc.vision.models,
            source_now=self._node.get_clock().now().nanoseconds / 1e9,
            now=time.monotonic())

    def _on_nav_cmd_vel(self, msg) -> None:
        docking_mode.route_nav_cmd_vel(
            self._svc, CoreTwist(linear=msg.linear.x, angular=msg.angular.z))

    def _current_route_context_seq(self, ros_now: float):
        if self.route_context_pub is None or self._svc.safety.estop:
            return None
        context = self._svc.line_follow.route_context(
            ros_now=ros_now, now=self._line_clock())
        return None if context is None else context.seq

    def _on_dock_observation(self, msg) -> None:
        """Tag evidence only; a malformed payload clears the feed (lost, not guessed)."""
        try:
            self._svc.dock_feed.ingest(
                json.loads(msg.data), received_at=self._line_clock(),
                source_now=self._node.get_clock().now().nanoseconds * 1e-9)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            self._node.get_logger().warning(
                f"ignored dock observation: {exc}", throttle_duration_sec=5.0)

    def _on_loc_state(self, msg) -> None:
        self._svc.localization.on_state(msg.data)

    def _on_loc_candidates(self, msg) -> None:
        self._svc.localization.on_candidates(msg.data)

    def _on_loc_result(self, msg) -> None:
        self._svc.localization.on_result(msg.data)

    def _on_camera_preview(self, msg) -> None:
        observation.camera_preview(
            self._svc, msg, warn=self._node.get_logger().warning,
            source_now=self._node.get_clock().now().nanoseconds * 1e-9)

    def _on_camera_raw_preview(self, msg) -> None:
        observation.camera_preview(
            self._svc, msg, warn=self._node.get_logger().warning, raw=True,
            source_now=self._node.get_clock().now().nanoseconds * 1e-9)

    def _publish_route_context(self, context, *, ros_now=None) -> None:
        if self.route_context_pub is None:
            return
        if ros_now is None:
            ros_now = self._node.get_clock().now().nanoseconds / 1e9
        message = self._route_context_output.message(context, ros_now)
        if message is not None:
            self._publish_string(self.route_context_pub, json.dumps(message))
            self._svc.line_follow.set_route_context_publication(
                context if self._route_context_output.previous is not None else None,
                self._route_context_output.at)

    def _on_amcl_transition(self, msg) -> None:
        if self._readiness is not None:
            self._readiness.observe("amcl", self._lifecycle_active(msg))

    def _on_controller_transition(self, msg) -> None:
        if self._readiness is not None:
            self._readiness.observe("controller_server", self._lifecycle_active(msg))

    def _on_local_costmap_transition(self, msg) -> None:
        if self._readiness is not None:
            self._readiness.observe("local_costmap", self._lifecycle_active(msg))

    def _on_global_costmap_transition(self, msg) -> None:
        if self._readiness is not None:
            self._readiness.observe("global_costmap", self._lifecycle_active(msg))

    def _on_motor_ready(self, msg) -> None:
        if self._readiness is not None:
            self._readiness.observe("motor_adapter", bool(msg.data), lease=True)

    def _note_wheels(self, out: CoreTwist) -> None:
        # D-422: update near-point memory after host publish, outside submission locks.
        problem = observation.wheels_sent(self._svc, out)
        if problem is not None:
            now = time.monotonic()
            if now - self._wheels_warned_at >= 5.0:
                self._wheels_warned_at = now
                self._node.get_logger().warning(problem)

    def _on_plan(self, msg) -> None:
        observation.nav_path(self._svc, msg, warn=self._node.get_logger().warning)

    def _on_local_costmap(self, msg) -> None:
        observation.nav_costmap(self._svc, "local", msg, warn=self._node.get_logger().warning)

    def _on_global_costmap(self, msg) -> None:
        observation.nav_costmap(self._svc, "global", msg, warn=self._node.get_logger().warning)

    def _on_scan(self, msg) -> None:
        sample = translate.lidar_sample(msg, time.time())
        sample["source_now_ns"] = self._node.get_clock().now().nanoseconds
        self._svc.state.set_sensor("lidar", sample)
        self._svc.power.report_device_ready(device_power.LIDAR, True)
        observation.front_clearance(self._svc, sample, received_at=self._line_clock())

    def _on_imu(self, msg) -> None:
        self._svc.state.set_sensor("imu", translate.imu_sample(msg, time.time()))

    def _on_us_range(self, msg) -> None:
        observation.us_range(self._svc, msg, received_at=time.time())

    def _on_batt_state(self, msg) -> None:
        observation.batt_state(
            self._svc, msg, received_at=time.time(),
            voltage_topic_seen=self._voltage_topic_seen)

    def _reconcile_power_outputs(self, status) -> None:
        if status.mode.value != self._published_power_mode:
            self._published_power_mode = status.mode.value
            self._publish_string(self.power_mode_pub, status.mode.value.lower())

        device_power.reconcile_devices(
            self._svc.power.device_levels(), self._device_applied,
            self._device_ports, log=self._node.get_logger().info,
            restarted=self._svc.power.device_restarted)

        now = time.monotonic()
        if display.republish_due(
                status.info_visible, self._info_was_visible, now, self._info_last_pub):
            self._publish_display_info(status)
            self._info_last_pub = now
        self._info_was_visible = status.info_visible

        self._reconcile_emotion(now)
        self._reconcile_led(status.info_visible, now)
        self._maybe_publish_drive(now)
        self._maybe_write_face_inputs(status, now)

    def _maybe_write_face_inputs(self, status, now: float) -> None:
        """D-433: hand rosy-face the face, the drive/wake cards and the power mode."""
        from core_common.face_screen import FACE_INPUTS_PERIOD_S

        snapshot = self._svc.state.snapshot()
        wake = None
        if status.info_visible:
            wake = display.info_payload(
                snapshot, status, health=self.diagnostics.summary_health().value,
                address=self._api_endpoint(), hold_s=self._svc.power.info_hold_s)
        content = display.face_inputs_payload(
            snapshot, face=self._face_desired, power_mode=status.mode.value, wake=wake,
            expression=self._expression_intent.handover(),
            written_at=datetime.now(timezone.utc).isoformat(timespec="milliseconds"))
        preview = self._svc.vision.status(now=time.monotonic())
        content.update(
            display.face_camera_quality(preview),
            **display.face_person_request(self._svc.person_request.view()))
        expressive = self._expression_intent.handover() is not None
        period = min(FACE_INPUTS_PERIOD_S, .15) if expressive else FACE_INPUTS_PERIOD_S
        if not display.face_inputs_due(
                content, self._face_inputs_last, now, self._face_inputs_at, period):
            return
        try:
            self._svc.host_files.write_face_inputs(self._svc, content)
        except Exception as exc:  # noqa: BLE001 - an indicator input must never stop the bridge
            if not self._face_inputs_failed:
                self._node.get_logger().warning(
                    f"face inputs not written: {type(exc).__name__}: {exc}")
            self._face_inputs_failed = True
            return
        self._face_inputs_failed = False
        self._face_inputs_last, self._face_inputs_at = content, now

    def _publish_display_info(self, status) -> None:
        payload = display.info_payload(
            self._svc.state.snapshot(), status,
            health=self.diagnostics.summary_health().value,
            address=self._api_endpoint(),
            hold_s=self._svc.power.info_hold_s,
        )
        self._publish_string(self.display_info_pub, json.dumps(payload))

    def _api_endpoint(self) -> str:
        """정보 화면에 띄울 접속 주소. 한 번 풀고 캐시한다."""
        if self._api_address is None:
            port = self._svc.config.get("network", {}).get("api_port", 8080)
            self._api_address = display.resolve_api_address(port)
        return self._api_address

    def _reconcile_led(self, info_visible: bool, now: float) -> None:
        """중재 결과에 LED 를 맞춘다 (SAF-005 경보 > 정보창 게이지)."""
        command = expression.led_command(
            self._expression_intent, alert=self._svc.battery.led_alert,
            info_visible=info_visible,
            gauge_percent=self._svc.state.snapshot().battery.percent,
            now=now)
        self._led_output.apply(
            command, now=now, ready=self._led_client.service_is_ready(),
            send=lambda value: self._call_led(value.command, value.r, value.g, value.b))

    def _maybe_publish_drive(self, now: float) -> None:
        """D-394: 운용 중에는 20 s 마다 주행 카드가 얼굴 위로 잠깐 지나간다."""
        snapshot = self._svc.state.snapshot()
        mode = snapshot.mode.value
        if not display.drive_due(mode, now, self._drive_last_pub):
            return
        goal_x = goal_y = None
        self._publish_string(
            self.display_info_pub,
            json.dumps(display.drive_payload(snapshot, goal_x=goal_x, goal_y=goal_y)))
        self._drive_last_pub = now

    def _reconcile_emotion(self, now: Optional[float] = None) -> None:
        """D-922: one display intent feeds the face service, native hand-over and LED."""
        current = time.monotonic() if now is None else now
        if self._hello_until is None:
            self._hello_until = current + 10.0
        snapshot = self._svc.state.snapshot()
        mode = snapshot.mode.value
        status = self._svc.power.status()
        suspended = (
            snapshot.safety.estop or status.info_visible or status.mode.value == "STANDBY"
            or self.diagnostics.summary_health() != HealthState.OK
            or bool(display.face_cautions(snapshot)))
        velocity = snapshot.velocity
        moving = (
            bool(velocity.linear or velocity.angular)
            if 0 <= current - self._last_odom_ts <= .5 and self._last_odom_ts > 0 else None)
        self._expression_intent = self._expression.update(
            mode, snapshot.navigation.value, current, suspended=suspended, moving=moving)
        desired = self._expression_intent.face
        if (current < self._hello_until and not suspended and mode == "IDLE"
                and self._expression_intent.face == "basic"):
            desired = "hello"
        self._face_desired = desired or self._face_desired
        self._face_output.apply(
            self._face_desired, now=current,
            ready=self._emotion_client.service_is_ready(), send=self._call_emotion)

    def _call_emotion(self, face: str):
        if not self._emotion_client.service_is_ready():
            return None
        from interfaces.srv import Emotion

        request = Emotion.Request()
        request.emotion = face
        return self._emotion_client.call_async(request)

    def _send_lidar(self, spinning: bool) -> bool:
        client = self._lidar_start_client if spinning else self._lidar_stop_client
        if not client.service_is_ready():
            return False
        from std_srvs.srv import Empty

        client.call_async(Empty.Request())
        return True

    def _on_device_ready(self, msg) -> None:
        report = device_power.parse_ready_report(msg.data)
        if report is not None:
            self._svc.power.report_device_ready(*report)

    def _call_led(self, command: str, r: int, g: int, b: int):
        if not self._led_client.service_is_ready():
            return None
        from interfaces.srv import SetLed

        request = SetLed.Request()
        request.command = command
        request.pixels = []
        request.r, request.g, request.b = r, g, b
        return self._led_client.call_async(request)

    def _on_hitl_request(self, msg) -> None:
        observation.hitl_request(self._svc, msg.data, logger=self._node.get_logger())

    def _on_degraded_modules(self, msg) -> None:
        observation.degraded_modules(self._svc, msg.data)

    def _on_motor_health(self, msg) -> None:
        thermal_policy.on_motor_health(self._svc, msg.data, time.monotonic())

    def _tick_diagnostics(self) -> None:
        results = self.diagnostics.collect()
        for component, health in results.items():
            self._svc.state.set_diagnostic(component, health)
        if self._readiness is not None:
            self._svc.state.set_diagnostic(
                "navigation_readiness",
                HealthState.OK if self._readiness.snapshot().ready else HealthState.ERROR,
            )
        thermal_policy.tick(self._svc, time.monotonic())

    def _tick_swarm(self) -> None:
        try:
            self._svc.swarm.tick()
        except Exception as exc:
            self._node.get_logger().warning(f"swarm tick failed: {exc}")

    def _tick_trail(self) -> None:
        try:
            self._svc.swarm.trail_tick(self._line_clock())
        except Exception as exc:
            self._node.get_logger().warning(f"trail tick failed: {exc}")

    def _tick_docking(self) -> None:
        docking = self._svc.docking
        self._dock_ticks += 1
        if not docking_mode.due(self._dock_ticks, docking.fast_tick):
            return
        docking_mode.tick(
            self._svc, self._node.get_logger().warning, station=self._svc.station_docking)

    def _goal_response_cb(self, future, generation: int) -> None:
        goal_tracker.on_response(
            self._goals, self._svc.nav, future, generation,
            attach_result=self._attach_result)

    def _attach_result(self, result_future, generation: int) -> None:
        result_future.add_done_callback(
            lambda done, gen=generation: self._result_cb(done, gen))

    def _result_cb(self, future, generation: int) -> None:
        goal_tracker.on_result(self._goals, self._svc.nav, future, generation)
