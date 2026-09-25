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
from typing import Any, Callable

from core.bridge import battery_policy, translate
from core.bridge.hitl import parse_hitl_request
from core_features.command.manager import Twist as CoreTwist
from core_features.line_follow import LineFollowMode, LineObservation
from core_features.vision import accept_preview

Warn = Callable[[str], None]


def line_observation(services, raw: str, *, source_now: float,
                     received_at: float) -> None:
    """Accept normalized evidence only; malformed or wrong-source data cannot drive."""
    try:
        data = json.loads(raw)
        if type(data.get("visible")) is not bool:
            raise ValueError("visible must be a boolean")
        visible = data["visible"]
        observation = LineObservation(
            source=LineFollowMode(data["source"]),
            stamp=float(data["stamp"]),
            visible=visible,
            error=(float(data["error"]) if visible else None),
            confidence=float(data["confidence"]),
        )
        accepted = services.line_follow.observe(
            observation, received_at=received_at, source_now=source_now)
        services.state.set_sensor("line_follow", {
            "valid": True,
            "accepted": accepted,
            "source": observation.source.value,
        })
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        if services.line_follow.invalidate(received_at=received_at):
            services.command.clear_navigation()
            services.line_follow.tick(received_at)
            services.state.set_line_follow(services.line_follow.status())
        services.state.set_sensor("line_follow", {
            "valid": False,
            "reason": "invalid_observation",
            "detail": str(exc),
        })


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


def detection_evidence(services, raw: str) -> None:
    """D-137 T4: 와이어 패킷 → 자문 시임. 판정은 ROS-free 피드가 한다."""
    try:
        packet = json.loads(raw)
    except ValueError:
        packet = None
    services.advisory_feed.ingest(packet)


def camera_preview(services, msg, *, warn: Warn) -> None:
    """Store one display-only JPEG without coupling it to driving policy.

    `msg` is duck-typed (`format`, `header.stamp`, `frame_id`, `data`).
    """
    try:
        metadata = accept_preview(msg.format)
        stamp = (
            float(msg.header.stamp.sec)
            + float(msg.header.stamp.nanosec) * 1e-9
        )
        services.vision.publish(
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


def batt_state(services, msg, *, received_at: float,
               voltage_topic_seen: bool) -> None:
    sample = translate.battery_sample(msg, received_at)
    services.state.set_sensor("battery", sample)
    # battery/voltage 퍼블리셔가 없는 구성(ADC 노드 단독)에서는 이 토픽이
    # 유일한 전압원이므로 SAF-005 경로를 그대로 태운다.
    if not voltage_topic_seen:
        battery_policy.apply_voltage(services, sample["voltage"])
