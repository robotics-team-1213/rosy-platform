"""CORE traffic-policy and optional measured-signal observer composition."""
from __future__ import annotations

from typing import Any, Optional

from core_features.traffic_policy import (
    SignalObserverMonitor, SignalObserverPoller, SignalObserverSourceConfig,
    TrafficPolicyConfig, TrafficPolicyManager, TrafficPolicyMode,
)


def _traffic_policy_config(raw: dict[str, Any]) -> TrafficPolicyConfig:
    """Parse revision-bound traffic policy without weakening its bounds."""
    defaults = TrafficPolicyConfig()
    return TrafficPolicyConfig(
        mode=TrafficPolicyMode(raw.get("mode", defaults.mode.value)),
        map_id=str(raw.get("map_id", defaults.map_id)),
        scene_revision=str(raw.get(
            "scene_revision", defaults.scene_revision)),
        policy_revision=str(raw.get(
            "policy_revision", defaults.policy_revision)),
        junction_rule=str(raw.get(
            "junction_rule", defaults.junction_rule)),
        approach_distance_m=float(raw.get(
            "approach_distance_m", defaults.approach_distance_m)),
        stop_distance_m=float(raw.get(
            "stop_distance_m", defaults.stop_distance_m)),
        stop_dwell_s=float(raw.get(
            "stop_dwell_s", defaults.stop_dwell_s)),
        stale_after_s=float(raw.get(
            "stale_after_s", defaults.stale_after_s)),
        min_confidence=float(raw.get(
            "min_confidence", defaults.min_confidence)),
        proceed_speed_scale=float(raw.get(
            "proceed_speed_scale", defaults.proceed_speed_scale)),
    )


def _signal_observer_binding(
        raw: dict[str, Any]) -> Optional[SignalObserverSourceConfig]:
    """D-337 measured-light binding; an absent or empty block is feature-off."""
    block = raw.get("signal_observer") or {}
    if not isinstance(block, dict) or not block:
        return None
    roi_map = block.get("roi_map") or {}
    return SignalObserverSourceConfig(
        url=str(block.get("url", "")),
        roi_map={str(name): str(target) for name, target in roi_map.items()},
        timeout_s=float(block.get("timeout_s", 1.0)),
        poll_interval_s=float(block.get("poll_interval_s", 0.5)),
    )


def build_traffic(config: dict[str, Any], *, events) -> tuple[
        TrafficPolicyManager, Optional[SignalObserverMonitor]]:
    """Start only an explicitly bound observer, after the policy's map/scene check."""
    traffic_policy_config = _traffic_policy_config(
        config.get("traffic_policy", {}) or {})
    traffic_policy = TrafficPolicyManager(
        events,
        config=traffic_policy_config,
        simulation_signal_control=bool(
            (config.get("runtime") or {}).get("mode") == "simulation"
            and (config.get("traffic_policy") or {}).get(
                "simulation_signal_control", False)
        ),
    )
    # D-337 T3: the measured-light poller exists only when the operator
    # binds an observer; a binding without the policy's map/scene would
    # have every frame rejected, so it fails the build instead.
    observer_binding = _signal_observer_binding(
        config.get("traffic_policy", {}) or {})
    signal_observer: Optional[SignalObserverMonitor] = None
    if observer_binding is not None:
        if not traffic_policy_config.map_id \
                or not traffic_policy_config.scene_revision:
            raise ValueError(
                "traffic_policy.signal_observer requires the policy's "
                "map_id and scene_revision")
        signal_observer = SignalObserverMonitor(
            SignalObserverPoller(
                observer_binding,
                map_id=traffic_policy_config.map_id,
                scene_revision=traffic_policy_config.scene_revision),
            traffic_policy,
            stale_after_s=traffic_policy_config.stale_after_s,
            events=events,
        )
        signal_observer.start()
    return traffic_policy, signal_observer
