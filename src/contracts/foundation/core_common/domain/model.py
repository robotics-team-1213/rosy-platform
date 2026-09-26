"""core_common.domain.model — concept Node/Device/Component/Asset snapshot. ROS 무의존."""

from __future__ import annotations

import enum
import platform
import socket
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Optional, Sequence

from core_common.identity import SOFTWARE_VERSION

_SLICES_BY_MODE = {
    "core": ("core",),
    "motor": ("core", "motor"),
    "hardware": ("core", "motor", "io", "nav"),
}


class DeviceState(str, enum.Enum):
    BOOTING = "BOOTING"
    READY = "READY"
    BUSY = "BUSY"
    DEGRADED = "DEGRADED"
    FAULT = "FAULT"
    SAFE_STOP = "SAFE_STOP"
    OFFLINE = "OFFLINE"
    UPDATING = "UPDATING"


@dataclass(frozen=True)
class RuntimeNode:
    runtime_mode: str
    slices: tuple[str, ...]
    hostname: str = ""
    architecture: str = ""
    os: str = ""
    software_version: str = SOFTWARE_VERSION


@dataclass(frozen=True)
class Device:
    device_id: str
    device_type: str
    model: str = ""


@dataclass(frozen=True)
class Component:
    name: str


@dataclass(frozen=True)
class Asset:
    asset_id: str
    type: str
    devices: tuple[str, ...]


def slices_from_config(config: dict[str, Any]) -> tuple[str, ...]:
    runtime = config.get("runtime") or {}
    raw = runtime.get("slices")
    if raw is None:
        raw = config.get("slices")
    if raw:
        return tuple(str(item) for item in raw)
    mode = str(runtime.get("mode") or "core")
    presets = runtime.get("presets")
    if isinstance(presets, dict) and mode in presets:
        return tuple(str(item) for item in presets[mode])
    return _SLICES_BY_MODE.get(mode, ("core",))


def _mode_value(mode: Any) -> str:
    if isinstance(mode, enum.Enum):
        return str(mode.value)
    return str(mode)


def _device_state(
    mode: Any,
    health_error: bool,
    estop: bool,
    booting: bool = False,
) -> DeviceState:
    value = _mode_value(mode)
    if estop or value == "EMERGENCY":
        return DeviceState.SAFE_STOP
    if health_error:
        return DeviceState.FAULT
    if booting:
        return DeviceState.BOOTING
    if value in {"NAVIGATION", "DOCKING", "MANUAL"}:
        return DeviceState.BUSY
    return DeviceState.READY


def _components(sensors: Iterable[str]) -> tuple[Component, ...]:
    names: list[str] = []
    for name in ("drive", *sensors):
        text = str(name)
        if text and text not in names:
            names.append(text)
    return tuple(Component(name=name) for name in names)


def inventory_from_config(
    config: dict[str, Any],
    *,
    profile_model: str,
    sensors: Sequence[str],
    slices: Optional[Sequence[str]] = None,
    mode: Any,
    health_error: bool,
    estop: bool,
    booting: bool = False,
    cap001: Optional[Mapping[str, Any]] = None,
    hitl_requested: bool = False,
    runtime_reasons: Optional[Mapping[str, str]] = None,
) -> dict[str, Any]:
    robot = config.get("robot") or {}
    robot_id = str(robot.get("id") or "rosy_01")
    runtime = config.get("runtime") or {}
    resolved_slices = (
        tuple(str(item) for item in slices)
        if slices is not None
        else slices_from_config(config)
    )
    state = _device_state(mode, health_error, estop, booting=booting)
    payload: dict[str, Any] = {
        "node": RuntimeNode(
            runtime_mode=str(runtime.get("mode") or "core"),
            slices=resolved_slices,
            hostname=socket.gethostname(),
            architecture=platform.machine(),
            os=platform.system(),
            software_version=SOFTWARE_VERSION,
        ),
        "device": Device(
            device_id=robot_id,
            device_type="mobile_base",
            model=profile_model,
        ),
        "components": _components(sensors),
        "asset": Asset(
            asset_id=robot_id,
            type="mobile_base",
            devices=(robot_id,),
        ),
        "device_state": state,
        "hitl_requested": hitl_requested,
    }
    if cap001 is not None:
        from core_common.domain.capabilities import descriptors_from_cap001
        from core_common.domain.tasks import TaskKind

        descriptors = descriptors_from_cap001(
            cap001, device_state=state, runtime_reasons=runtime_reasons)
        payload["descriptors"] = [
            {
                "id": item.id,
                "available": item.available,
                "state": item.state,
                "reason": item.reason,
                "reasons": list(item.reasons),
            }
            for item in descriptors
        ]
        payload["capability_ids"] = [item.id for item in descriptors]
        payload["task_kinds"] = [
            {
                "kind": kind.value,
                "concept_id": kind.concept_id,
                "capability": kind.capability,
            }
            for kind in TaskKind
        ]
    return payload
