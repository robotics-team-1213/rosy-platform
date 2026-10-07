"""ROS-free admission decisions behind the sensor/evidence callbacks (C1).

`ros_bridge.py` cannot be imported by host pytest — optional ROS deps — so a
decision computed inside one of its callbacks is unreachable for every test in
this repository, and the source-grep checks that stand in for them pass on
wrong values. This module is the *decide* half of those callbacks: parse,
validate, admit or reject, route to a service, mirror into state. The bridge
keeps the *act* half: reading the node clock, publishing, logging via `warn`.

Plan: `docs/plans/2026-09-06-module-split-criteria.md` (C1: a host-unreadable
file hiding a decision → extract a ROS-free sibling).
"""

from __future__ import annotations

import json
import math
from typing import Callable, Optional

from core.bridge import battery_policy, translate
from core.bridge.hitl import parse_hitl_request
from core_features.command.arbitration import Mode
from core_features.command.manager import Twist as CoreTwist
from core_features.line_follow import LineFollowMode, LineObservation
from core_features.line_follow.clearance import front_clearance as _front_clearance
from core_features.line_follow.clearance import scan_points as _scan_points
from core_features.line_follow.clearance import return_scan_view as _return_scan_view
from core_features.line_follow.model import SOURCE_FUTURE_TOLERANCE_S
from core_features.vision import accept_preview
from core_common.protocol.lane_containment import LaneContainmentEvidence

Warn = Callable[[str], None]


def line_observation(services, raw: str, *, source_now: float,
                     received_at: float) -> None:
    """Accept normalized evidence only; malformed or wrong-source data cannot drive."""
    source = None
    try:
        data = json.loads(raw)
        source = LineFollowMode(data["source"])
        if type(data.get("visible")) is not bool:
            raise ValueError("visible must be a boolean")
        visible = data["visible"]
        quality_reason = None
        if source is LineFollowMode.CAMERA_LINE and data.get('quality') is not None:
            quality = data['quality']
            if not isinstance(quality, dict) or type(quality.get('valid')) is not bool:
                raise ValueError('invalid camera quality')
            if quality['valid'] is False:
                if quality.get('reason') not in ('low_light', 'overexposed'):
                    raise ValueError('unknown invalid camera quality')
                quality_reason = quality['reason']
        calibrated = data.get("ir_calibrated", False)
        revision = data.get("calibration_revision")
        if source is LineFollowMode.IR_LINE and type(calibrated) is not bool:
            raise ValueError("IR calibrated marker must be a boolean")
        observation = LineObservation(
            source=source,
            stamp=float(data["stamp"]),
            visible=visible,
            error=(float(data["error"]) if visible else None),
            confidence=float(data["confidence"]),
            ir_calibrated=calibrated if source is LineFollowMode.IR_LINE else False,
            calibration_revision=revision if source is LineFollowMode.IR_LINE else None,
            ground=data.get("ground"),
            quality_reason=quality_reason,
            containment=(LaneContainmentEvidence.model_validate(data["containment"])
                         if data.get("containment") is not None else None),
        )
        accepted = services.line_follow.observe(
            observation, received_at=received_at, source_now=source_now)
        services.state.set_sensor("line_follow", {
            "valid": True,
            "accepted": accepted,
            "source": observation.source.value,
            "ir_calibrated": observation.ir_calibrated,
            "calibration_revision": observation.calibration_revision,
        })
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        if source is LineFollowMode.IR_LINE:
            services.line_follow.invalidate_ir(received_at=received_at)
        elif services.line_follow.invalidate(received_at=received_at):
            services.command.clear_navigation()
            services.line_follow.tick(received_at)
            services.state.set_line_follow(services.line_follow.status())
        services.state.set_sensor("line_follow", {
            "valid": False,
            "reason": "invalid_observation",
            "detail": str(exc),
        })


def keep_junction(services, raw: str, *, source_now: float, received_at: float) -> None:
    """D-494 decision 4 / D-495: the keeper's junction HOLD reason and corner_turning flag.

    A sighting HOLDs line-follow and also starts an armed D-495 bounded turn, so it gates
    motion, not only stops: the frame must reach CORE within stale_after_s (0.3 s) of its camera
    stamp or it is dropped here. corner_turning feeds supports_junction_turn."""
    try:
        data = json.loads(raw)
        reason, stamp, corner = data.get("reason"), data.get("stamp"), data.get("corner_turning")
    except (AttributeError, TypeError, ValueError):
        return
    if (type(stamp) in (int, float) and math.isfinite(stamp)
            and 0.0 <= source_now - stamp <= services.line_follow.config.stale_after_s):
        services.line_follow.observe_junction(reason, received_at - (source_now - stamp),
                                              corner_turning=corner is True)


def road_observation(services, raw: str, *, source_now: float,
                     received_at: float) -> None:
    """Decode road evidence; invalid data invalidates an enforced lease."""
    try:
        observation = translate.road_evidence(json.loads(raw))
        services.traffic_policy.observe(
            observation,
            received_at=received_at,
            source_now=source_now,
        )
        services.state.set_sensor("traffic_policy", {
            "valid": True,
            "source": observation.source,
            "map_id": observation.map_id,
            "scene_revision": observation.scene_revision,
            # Scene context is display-only observability (D-162);
            # it never changes a verdict.
            "context_id": observation.context_id,
            "context_profile_revision": observation.context_profile_revision,
        })
    except (KeyError, TypeError, ValueError,
            json.JSONDecodeError) as exc:
        status = services.traffic_policy.reset("invalid_road_observation")
        if services.traffic_policy.mode.value == "ENFORCED":
            services.command.clear_navigation()
        services.state.set_traffic_policy(status)
        services.state.set_sensor("traffic_policy", {
            "valid": False,
            "reason": "invalid_observation",
            "detail": str(exc),
        })


#: D-407 body clearances only need the robot's near field.
BODY_POINTS_RANGE_M = 0.6


def _range_min(sample) -> Optional[float]:
    """The scan's range_min, or None when it is missing or not a finite number (review M2)."""
    value = sample.get("range_min")
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return max(0.0, float(value))


def front_clearance(services, sample, *, received_at: float) -> None:
    """D-344 §11: LiDAR 를 차선 추종 정지 판정에 넘긴다 — path 는 점, sector 는 정면 최소 거리.

    D-395 P2-7 미션도 같은 표본을 받는다(정면 여유는 미션이 필요할 때만 잰다)."""
    mission = services.loc_mission
    if mission is not None:
        mission.observe_scan(sample)
    line = services.line_follow
    config = line.config
    path = config.obstacle_mode == "path"
    try:
        # D-407: the stuck recovery reads the same self-masked points for front-band, rear
        # (from the URDF body rear) and turn clearances; range_min marks the blind zone.
        # Sector mode builds them only while a stuck can be near (review L6).
        if path or line.wants_body_points:
            points = _scan_points(
                sample, forward_deg=config.lidar_forward_deg,
                max_range=max(BODY_POINTS_RANGE_M,
                              config.obstacle_path_horizon_m + config.obstacle_corridor_half_width_m),
                self_mask=config.lidar_self_mask)
            line.observe_body_points(points, range_min=_range_min(sample), received_at=received_at)
        if line.wants_return_scan:
            from core_common.robot_body import RobotBody
            try:
                body = RobotBody(front_x_m=config.body_front_x_m,
                    rear_x_m=config.body_rear_x_m, half_width_m=config.body_half_width_m,
                    rotation_radius_m=config.body_rotation_radius_m,
                    lidar_x_m=config.body_lidar_x_m, lidar_forward_deg=config.lidar_forward_deg,
                    margin_m=config.obstacle_body_margin_m)
                evidence = _return_scan_view(sample, body=body,
                    source_now_ns=sample.get("source_now_ns"),
                    clearance_horizon_m=max(.15, config.obstacle_path_horizon_m),
                    self_mask=config.lidar_self_mask)
            except (TypeError, ValueError, OverflowError):
                evidence = None
            line.observe_return_scan(None if evidence is None else evidence[0],
                source_age_s=None if evidence is None else evidence[1],
                source_stamp_ns=None if evidence is None else evidence[2],
                received_at=received_at)
        if path:
            line.observe_scan_points(points, received_at=received_at)
            return
        distance = _front_clearance(
            sample, forward_deg=config.lidar_forward_deg,
            half_angle_deg=config.obstacle_half_angle_deg, self_mask=config.lidar_self_mask)
    except (AttributeError, KeyError, TypeError, ValueError):
        return
    line.observe_clearance(distance, received_at=received_at)


def detection_evidence(services, raw: str) -> None:
    """D-137 T4: 와이어 패킷 → 자문 시임. 판정은 ROS-free 피드가 한다."""
    try:
        packet = json.loads(raw)
    except ValueError:
        packet = None
    services.advisory_feed.ingest(packet)


def camera_preview(services, msg, *, warn: Warn, raw: bool = False, source_now: float | None = None) -> None:
    """Store one display-only JPEG without coupling it to driving policy.

    `msg` is duck-typed (`format`, `header.stamp`, `frame_id`, `data`).
    """
    try:
        metadata = accept_preview(msg.format)
        stamp = (
            float(msg.header.stamp.sec)
            + float(msg.header.stamp.nanosec) * 1e-9
        )
        source_age = None if source_now is None else source_now - stamp
        fresh_source = (source_age is not None and math.isfinite(source_age) and math.isfinite(stamp)
                        and stamp >= 0 and -SOURCE_FUTURE_TOLERANCE_S <= source_age <= 2.)
        if not fresh_source:
            metadata.pop('quality', None)
            if raw:
                raise ValueError('raw preview source image is stale or clock is unavailable')
        else:
            metadata['source_age_s'] = max(0.0, source_age)  # D-507 8: skew counts as now
        store_frame = services.vision.publish_raw if raw else services.vision.publish
        store_frame(
            bytes(msg.data),
            captured_at=stamp,
            frame_id=str(msg.header.frame_id),
            **metadata,
        )
    except (AttributeError, TypeError, ValueError, OverflowError) as exc:
        warn(f"ignored camera preview: {exc}")


def hitl_request(services, raw: str, *, logger) -> None:
    """ADR-999: Parse HITL request, log module and confidence, update state.

    `logger` is duck-typed (`warn`, `error`).
    """
    try:
        request = parse_hitl_request(raw)
        if request.requested:
            logger.warn(
                f"HITL Assistance Requested by [{request.module}] "
                f"(confidence: {request.confidence:.2f})"
            )
        services.state.set_hitl_requested(request.requested)
    except ValueError as exc:
        logger.error(f"Failed to parse HITL request: {exc}")


def degraded_modules(services, raw: str) -> None:
    """ADR-1000: Update degraded modules list."""
    services.state.set_capabilities_degraded(
        [m.strip() for m in raw.split(",") if m.strip()])


def nav_twist(services, linear: float, angular: float) -> None:
    """Line-follow owns the wheels while active; Nav2's twist is dropped, not queued."""
    if services.line_follow.active:
        return
    services.command.set_nav_twist(CoreTwist(linear=linear, angular=angular))


def nav_path(services, msg, *, warn: Warn) -> None:
    """MAP-003 plan snapshot; a malformed path is ignored, not fatal."""
    try:
        services.maps.set_path(translate.path_points(msg))
    except ValueError as exc:
        warn(f"ignored nav path: {exc}")


def nav_costmap(services, kind: str, msg, *, warn: Warn) -> None:
    """MAP-003 costmap snapshot for `kind` ("local" / "global")."""
    try:
        services.maps.set_costmap(kind, translate.grid_from_costmap(msg))
    except ValueError as exc:
        warn(f"ignored {kind} costmap: {exc}")


def wheels_sent(services, out) -> Optional[str]:
    """D-422: the twist the one cmd_vel publisher just sent feeds the line-follow near-point
    memory. It belongs to line follow only while line follow is active, the mode is
    NAVIGATION and nothing stops the wheels; anything else makes it forget (re-review HIGH 1).

    Never raises (it runs inside the 50 Hz final publisher). On any error the odometry is
    unknown: line follow forgets the memory and holds until its next fresh scan
    (`odometry_lost`). Returns the error text for the caller's throttled warning, else None."""
    line = services.line_follow
    try:
        modes = services.modes
        owned = bool(line.active and modes.mode is Mode.NAVIGATION and not modes.is_emergency
                     and not services.safety.estop)
        line.note_wheels(out.linear, out.angular, owned=owned)
        return None
    except Exception as exc:  # noqa: BLE001 - the final publisher must keep running
        try:
            line.odometry_lost()
        except Exception as inner:  # noqa: BLE001
            return f"line-follow wheel odometry failed: {exc}; odometry_lost failed: {inner}"
        return f"line-follow wheel odometry failed (memory erased, holding): {exc}"


def us_range(services, msg, *, received_at: float) -> None:
    """PWR-002: only a reading inside the sensor's own reported range may wake.

    A saturated or noisy value is not a distance (`translate.usable_range`),
    but the raw sample is still mirrored to state either way.
    """
    sample = translate.ultrasonic_sample(msg, received_at)
    services.state.set_sensor("ultrasonic", sample)
    usable = translate.usable_range(sample)
    if usable is not None:
        services.power.on_range(usable)
    # D-422: the same filtered range is a forward body-gap source for the line-follow stop.
    # Saturated above max_range (or +inf) = no echo in range. NaN, negative or below
    # min_range proves nothing (something may touch the sensor): it is not reported, so
    # the last reading ages out. Timed on the line-follow clock, like the LiDAR clearance.
    value = sample["range"]
    if usable is not None or value > float(sample["max_range"]):
        services.line_follow.observe_ultrasonic(usable)


def battery_voltage(services, voltage: float, *, received_at: float) -> None:
    """`battery/voltage` (Float32), the product graph's only battery source (D-192 4).

    It is also the `battery` sensor sample: `batt_state` is bench-only, and without
    this `/sensors/battery` stayed 404 on every robot. Freshness comes from the
    monitor (`BatteryMonitor.health`), so a non-finite sample is not recorded.
    """
    if math.isfinite(voltage):
        services.state.set_sensor("battery", {
            "voltage": float(voltage), "received_at": received_at, "source": "battery/voltage"})
    battery_policy.apply_voltage(services, voltage)


def batt_state(services, msg, *, received_at: float,
               voltage_topic_seen: bool) -> None:
    sample = translate.battery_sample(msg, received_at)
    services.state.set_sensor("battery", sample)
    # battery/voltage 퍼블리셔가 없는 구성(ADC 노드 단독)에서는 이 토픽이
    # 유일한 전압원이므로 SAF-005 경로를 그대로 태운다.
    if not voltage_topic_seen:
        battery_policy.apply_voltage(services, sample["voltage"])
