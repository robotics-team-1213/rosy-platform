"""CORE power/battery composition; the host unit remains the shutdown authority."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from core_features.power.battery import BatteryConfig, BatteryCurve, BatteryMonitor
from core_features.power.devices import DevicePolicyConfig, parse_device_policy
from core_features.power.manager import LidarPolicy, PowerConfig, PowerManager, PresenceConfig


# A shutdown request only; the host unit owns the actual halt.
SHUTDOWN_SENTINEL_NAME = "battery-shutdown-request.json"


def _battery_config(raw: dict[str, Any], data_path: Any = None) -> BatteryConfig:
    """rosy_default.yaml의 safety 블록 → BatteryConfig (누락 키는 기본값 유지).

    곡선이 없거나 무효하면 기존 two-point 스팬으로 되돌아간다. 설정 오타 하나로
    로봇이 아예 뜨지 않는 것보다 정확도가 낮은 채로 도는 편이 낫다.
    """
    defaults = BatteryConfig()

    full = float(raw.get("battery_full_voltage", 8.4))
    empty = float(raw.get("battery_empty_voltage", 6.4))

    curve: BatteryCurve
    points = raw.get("battery_curve")
    try:
        if points:
            curve = BatteryCurve([(float(v), float(p)) for v, p in points])
        else:
            curve = BatteryCurve.from_span(full=full, empty=empty)
    except (ValueError, TypeError):
        try:
            curve = BatteryCurve.from_span(full=full, empty=empty)
        except ValueError:
            curve = BatteryCurve.default()

    sentinel = None if data_path is None else Path(data_path) / SHUTDOWN_SENTINEL_NAME

    return BatteryConfig(
        curve=curve,
        filter_tau_s=float(raw.get("battery_filter_tau_s", defaults.filter_tau_s)),
        warning_percent=float(raw.get("battery_warning_percent", defaults.warning_percent)),
        critical_percent=float(raw.get("battery_critical_percent", defaults.critical_percent)),
        deep_percent=float(raw.get("battery_deep_percent", defaults.deep_percent)),
        enter_samples=int(raw.get("battery_enter_samples", defaults.enter_samples)),
        exit_samples=int(raw.get("battery_exit_samples", defaults.exit_samples)),
        hysteresis_percent=float(
            raw.get("battery_hysteresis_percent", defaults.hysteresis_percent)),
        deep_dwell_s=float(raw.get("battery_deep_dwell_s", defaults.deep_dwell_s)),
        sentinel_path=sentinel,
        shutdown_grace_s=float(
            raw.get("battery_shutdown_grace_s", defaults.shutdown_grace_s)),
    )


def _device_policy(raw: Any) -> DevicePolicyConfig:
    """A malformed optional block leaves the policy off (every device on) and says so.

    Refusing to boot over it would take the API, E-stop endpoint and battery
    monitor down with an energy-saving option.
    """
    try:
        return parse_device_policy(raw)
    except (ValueError, TypeError, AttributeError) as exc:
        logging.getLogger(__name__).error("power.device_policy ignored, every device stays on: %s", exc)
        return DevicePolicyConfig()


def _power_config(raw: dict[str, Any]) -> PowerConfig:
    """rosy_default.yaml의 power 블록 → PowerConfig (누락 키는 기본값 유지)."""
    presence_raw = raw.get("presence", {}) or {}
    lidar_raw = raw.get("lidar", {}) or {}
    defaults, presence_defaults = PowerConfig(), PresenceConfig()
    lidar_defaults = LidarPolicy()
    lidar = LidarPolicy(
        standby_stop=bool(lidar_raw.get("standby_stop", lidar_defaults.standby_stop)),
        spinup_s=float(lidar_raw.get("spinup_s", lidar_defaults.spinup_s)),
    )
    presence = PresenceConfig(
        near_m=float(presence_raw.get("near_m", presence_defaults.near_m)),
        contact_m=float(presence_raw.get("contact_m", presence_defaults.contact_m)),
        hysteresis_m=float(presence_raw.get("hysteresis_m", presence_defaults.hysteresis_m)),
        detect_samples=int(presence_raw.get("detect_samples", presence_defaults.detect_samples)),
        release_samples=int(presence_raw.get("release_samples", presence_defaults.release_samples)),
        min_valid_m=float(presence_raw.get("min_valid_m", presence_defaults.min_valid_m)),
        max_valid_m=float(presence_raw.get("max_valid_m", presence_defaults.max_valid_m)),
        min_presence_s=float(presence_raw.get("min_presence_s", presence_defaults.min_presence_s)),
        max_gap_s=float(presence_raw.get("max_gap_s", presence_defaults.max_gap_s)),
    )
    return PowerConfig(
        enabled=bool(raw.get("enabled", defaults.enabled)),
        idle_after_s=float(raw.get("idle_after_s", defaults.idle_after_s)),
        standby_after_s=float(raw.get("standby_after_s", defaults.standby_after_s)),
        warning_idle_after_s=float(raw.get("warning_idle_after_s", defaults.warning_idle_after_s)),
        warning_standby_after_s=float(raw.get("warning_standby_after_s", defaults.warning_standby_after_s)),
        critical_idle_after_s=float(raw.get("critical_idle_after_s", defaults.critical_idle_after_s)),
        critical_standby_after_s=float(raw.get("critical_standby_after_s", defaults.critical_standby_after_s)),
        info_hold_s=float(raw.get("info_hold_s", defaults.info_hold_s)),
        active_rate_hz=float(raw.get("active_rate_hz", defaults.active_rate_hz)),
        idle_rate_hz=float(raw.get("idle_rate_hz", defaults.idle_rate_hz)),
        standby_rate_hz=float(raw.get("standby_rate_hz", defaults.standby_rate_hz)),
        presence=presence,
        lidar=lidar,
        device_policy=_device_policy(raw.get("device_policy")),
    )


def build_power_and_battery(power_raw: dict[str, Any], safety_raw: dict[str, Any], *,
                            data_path, events) -> tuple[PowerManager, BatteryMonitor]:
    """Build the existing managers with the original configuration and data path."""
    power = PowerManager(_power_config(power_raw), events=events)
    battery = BatteryMonitor(
        _battery_config(safety_raw, data_path=data_path),
        events=events)
    return power, battery
