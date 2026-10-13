"""core_features.power.devices — per-device power policy (D-24 amendment, new ADR 2026-10-04).

A product's robot package declares which devices react to the power mode and
how (`power.device_policy.devices` in its `core.yaml`). A device that is not
declared stays on in every mode. Each declared device says what it does in IDLE
and STANDBY (`on`, `reduced`, `off`), how long it needs after being turned back
on before its output can be trusted (`wake_ready_s`), and whether motion must
wait for it (`required_for_motion`).

The whole policy sits behind one bench switch, `power.device_policy.enabled`
(default false). A device may override the switch for itself with its own
`enabled: true|false` (per robot, through the CORE overlay). Until a device is
active under the policy it stays on, so a robot with the switch off behaves
exactly as before.

Policy only, ROS-free: this module says what each device should be doing and
whether it is ready. `DevicePowerPort` adapters (in the gateway bridge) apply a
level to the real device and may report readiness back.
"""

from __future__ import annotations

import enum
import math
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Protocol

from core_common.protocol.schemas import PowerMode


class DeviceLevel(str, enum.Enum):
    ON = "on"
    REDUCED = "reduced"     # lower rate / partial work; output still trusted
    OFF = "off"             # paused or stopped; output not trusted


@dataclass(frozen=True)
class DevicePolicy:
    """One declared device. Defaults keep the device on."""

    name: str
    idle: DeviceLevel = DeviceLevel.ON
    standby: DeviceLevel = DeviceLevel.ON
    wake_ready_s: float = 0.0
    required_for_motion: bool = False
    enabled: Optional[bool] = None      # None = follow the bench switch

    def level_for(self, mode: PowerMode) -> DeviceLevel:
        if mode == PowerMode.STANDBY:
            return self.standby
        if mode == PowerMode.IDLE:
            return self.idle
        return DeviceLevel.ON


@dataclass
class DevicePolicyConfig:
    enabled: bool = False               # the bench switch (S4): off until bench sign-off
    devices: dict[str, DevicePolicy] = field(default_factory=dict)

    def active(self, policy: DevicePolicy) -> bool:
        return self.enabled if policy.enabled is None else bool(policy.enabled)


class DevicePowerPort(Protocol):
    """What the bridge registers per device. `apply` returns False when the
    device cannot be reached yet (service not up); the caller retries next tick."""

    name: str

    def apply(self, level: DeviceLevel) -> bool: ...


def _level(raw: Any, default: DeviceLevel) -> DeviceLevel:
    if raw is None:
        return default
    if isinstance(raw, bool):           # YAML `on`/`off` load as booleans
        return DeviceLevel.ON if raw else DeviceLevel.OFF
    return DeviceLevel(str(raw).strip().lower())


def _switch(raw: Any, where: str) -> Optional[bool]:
    """A switch is a YAML boolean or absent. The string "false" must not turn it on."""
    if raw is None or isinstance(raw, bool):
        return raw
    raise ValueError(f"{where} must be true or false")


def parse_device_policy(raw: Mapping[str, Any] | None) -> DevicePolicyConfig:
    """`power.device_policy` block → DevicePolicyConfig. A malformed block raises ValueError."""
    raw = {} if raw is None else raw
    declared = raw.get("devices") if isinstance(raw, Mapping) else None
    if not isinstance(raw, Mapping) or not isinstance(declared or {}, Mapping):
        raise ValueError("power.device_policy and its devices must be mappings")
    devices: dict[str, DevicePolicy] = {}
    for name, spec in (declared or {}).items():
        spec = {} if spec is None else spec
        if not isinstance(spec, Mapping):
            raise ValueError(f"power.device_policy.devices.{name} must be a mapping")
        wake_ready_s = float(spec.get("wake_ready_s", 0.0))
        if not math.isfinite(wake_ready_s) or wake_ready_s < 0.0:
            raise ValueError(f"power.device_policy.devices.{name}.wake_ready_s must be finite and >= 0")
        enabled = _switch(spec.get("enabled"), f"power.device_policy.devices.{name}.enabled")
        devices[str(name)] = DevicePolicy(
            name=str(name),
            idle=_level(spec.get("idle"), DeviceLevel.ON),
            standby=_level(spec.get("standby"), DeviceLevel.ON),
            wake_ready_s=wake_ready_s,
            required_for_motion=bool(spec.get("required_for_motion", False)),
            enabled=enabled,
        )
    return DevicePolicyConfig(
        enabled=bool(_switch(raw.get("enabled"), "power.device_policy.enabled")), devices=devices)
