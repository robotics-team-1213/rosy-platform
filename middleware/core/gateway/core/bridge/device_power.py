"""Device power adapters (per-device power policy, 2026-10-04). ROS-free.

`PowerManager` decides each declared device's level (on / reduced / off) from
the power mode. This module applies those levels through one `DevicePowerPort`
per device, with the LiDAR grammar: an action that could not go out (service or
node not up yet) is retried next tick, never latched.

Two adapter kinds cover today's devices:

* `ServiceDevicePort` — a device driven by start/stop services (LiDAR:
  `start_motor` / `stop_motor`). `reduced` counts as on.
* `TopicDevicePort` — a device whose own node obeys a latched JSON board on
  `power/devices` (`{"camera": "off", "perception": "reduced"}`); the node
  reports back on `power/device_ready`. Camera and perception live in the
  sensing `camera_detect_node`.

The ROS objects (service clients, publisher) stay in `ros_bridge.py`; adapters
get plain callables, so host pytest checks the whole decision.
"""

from __future__ import annotations

import json
from typing import Callable, Mapping, Optional

from core_features.power.devices import DeviceLevel, DevicePowerPort
from core_features.power.manager import LIDAR  # the one service-driven device; a scan is its report

from core.bridge import reconcile as _reconcile

DEVICES_TOPIC = "power/devices"
DEVICE_READY_TOPIC = "power/device_ready"


class ServiceDevicePort:
    """start/stop services. `send(on)` returns False when the service is not ready."""

    def __init__(self, name: str, send: Callable[[bool], bool]) -> None:
        self.name = name
        self._send = send

    def apply(self, level: DeviceLevel) -> bool:
        return self._send(level != DeviceLevel.OFF)


class DeviceBoard:
    """The latched `power/devices` board shared by every topic-driven device."""

    def __init__(self, publish: Callable[[str], None]) -> None:
        self._publish = publish
        self.levels: dict[str, str] = {}

    def set(self, name: str, level: DeviceLevel) -> bool:
        self.levels[name] = level.value
        self._publish(json.dumps(self.levels, sort_keys=True))
        return True


class TopicDevicePort:
    def __init__(self, name: str, board: DeviceBoard) -> None:
        self.name = name
        self._board = board

    def apply(self, level: DeviceLevel) -> bool:
        return self._board.set(self.name, level)


def reconcile_devices(levels: Mapping[str, DeviceLevel], applied: dict,
                      ports: Mapping[str, DevicePowerPort],
                      log: Optional[Callable[[str], None]] = None,
                      restarted: Optional[Callable[[str], None]] = None) -> None:
    """Drive each port only when its desired level differs from what it last took.

    `applied` starts at ON for a port the policy does not act on: devices are
    already running when CORE starts, so a robot with the policy off never sends
    a single command. A device the policy acts on starts at `None` (unknown): CORE
    may have restarted while it was off, so its level is sent once.

    `restarted(name)` is called when the command that turns an OFF device back on
    actually went out, so the policy counts `wake_ready_s` from that moment and
    not from the tick that only wanted it.
    """
    for name, port in ports.items():
        desired = levels.get(name, DeviceLevel.ON)
        was_off = applied.get(name, DeviceLevel.ON) in (DeviceLevel.OFF, None)

        def act(port=port, desired=desired) -> bool:
            sent = bool(port.apply(desired))
            if sent and log is not None:
                log(f"device {port.name} -> {desired.value} requested by power policy")
            return sent

        acted, applied[name] = _reconcile.reconcile(
            desired, applied.get(name, DeviceLevel.ON), act, latch_on_skip=False)
        if acted and was_off and restarted is not None:
            restarted(name)


def parse_ready_report(raw: str) -> Optional[tuple[str, bool]]:
    """`power/device_ready` payload `{"device": str, "ready": bool}` → (name, ready).

    The LiDAR is never confirmed over this topic: only a received scan is.
    """
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    name, ready = data.get("device"), data.get("ready")
    if not isinstance(name, str) or not isinstance(ready, bool) or name == LIDAR:
        return None
    return name, ready
