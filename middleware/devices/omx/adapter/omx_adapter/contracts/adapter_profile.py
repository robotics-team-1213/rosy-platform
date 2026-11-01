"""Validated, vendor-neutral OMX adapter profile.

The profile emits the standard controller names used by ros2_control and
MoveIt 2.  It deliberately does not open a serial port or claim that either
OMX-F/OMX-AI or the legacy OpenMANIPULATOR-X driver is present.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping


_ALIASES = {
    "omx-f": "omx_f",
    "omx_f": "omx_f",
    "omx-ai": "omx_ai",
    "omx_ai": "omx_ai",
    "openmanipulator-x": "openmanipulator_x",
    "openmanipulator_x": "openmanipulator_x",
    "rm-x52-tnm": "openmanipulator_x",
}
_KNOWN_MODELS = frozenset(_ALIASES.values())
_DEFAULT_JOINTS: tuple[str, ...] = ()


def _finite_positive(name: str, value: Any) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a positive finite number")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a positive finite number") from exc
    if not math.isfinite(number) or number <= 0.0:
        raise ValueError(f"{name} must be a positive finite number")
    return number


def _normalize_model(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("model must be a string")
    model = value.strip().lower()
    if not model:
        return ""
    try:
        return _ALIASES[model]
    except KeyError as exc:
        raise ValueError(f"unsupported OMX model: {value!r}") from exc


def _joints(value: Any, *, required: bool) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise ValueError("joint_names must be a list of unique names")
    names = tuple(value)
    if not names and not required:
        return names
    if len(names) < 4 or any(
        not isinstance(name, str) or not name.strip() or name != name.strip()
        for name in names
    ):
        raise ValueError("joint_names must contain at least four non-empty names")
    if len(set(names)) != len(names):
        raise ValueError("joint_names must be unique")
    return names


def _frame(name: str, value: Any) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError(f"{name} must be a non-empty frame name")
    return value


@dataclass(frozen=True)
class OmxAdapterProfile:
    enabled: bool
    model: str
    driver_package: str
    hardware_plugin: str
    joint_names: tuple[str, ...]
    base_frame: str
    arm_base_frame: str
    update_rate_hz: float

    @classmethod
    def from_mapping(cls, values: Mapping[str, Any]) -> "OmxAdapterProfile":
        enabled = values.get("enabled", False)
        if not isinstance(enabled, bool):
            raise ValueError("enabled must be boolean")
        model = _normalize_model(values.get("model", ""))
        driver_package = values.get("driver_package", "")
        hardware_plugin = values.get("hardware_plugin", "")
        base_frame = values.get("base_frame", "base_link")
        arm_base_frame = values.get("arm_base_frame", "omx_base_link")
        if not all(isinstance(item, str) for item in (driver_package, hardware_plugin)):
            raise ValueError("OMX package, plugin and frame names must be strings")
        base_frame = _frame("base_frame", base_frame)
        arm_base_frame = _frame("arm_base_frame", arm_base_frame)
        names = _joints(values.get("joint_names", _DEFAULT_JOINTS), required=enabled)
        update_rate = _finite_positive("update_rate_hz", values.get("update_rate_hz", 100.0))

        if enabled:
            if model not in _KNOWN_MODELS:
                raise ValueError("an enabled OMX profile requires a known model")
            if not driver_package.strip() or not hardware_plugin.strip():
                raise ValueError("an enabled OMX profile requires driver_package and hardware_plugin")
        else:
            # Unselected hardware is a valid state, but it must not accidentally
            # advertise a partial capability or a vendor transport.
            if model and model not in _KNOWN_MODELS:
                raise ValueError("unsupported OMX model")

        return cls(
            enabled=enabled,
            model=model,
            driver_package=driver_package.strip(),
            hardware_plugin=hardware_plugin.strip(),
            joint_names=names,
            base_frame=base_frame,
            arm_base_frame=arm_base_frame,
            update_rate_hz=update_rate,
        )

    @property
    def capability_enabled(self) -> bool:
        return self.enabled

    def ros2_control_contract(self) -> dict[str, Any]:
        """Return only standard controller-manager declarations.

        An unselected profile returns an empty contract so a disabled device
        cannot create a fake joint state or claim an arm action server.
        """
        if not self.enabled:
            return {}
        return {
            "hardware_plugin": self.hardware_plugin,
            "controller_manager": {"update_rate": self.update_rate_hz},
            "joint_state_broadcaster": {
                "type": "joint_state_broadcaster/JointStateBroadcaster",
            },
            "arm_controller": {
                "type": "joint_trajectory_controller/JointTrajectoryController",
                "joints": list(self.joint_names),
                "command_interfaces": ["position"],
                "state_interfaces": ["position", "velocity"],
            },
            "moveit": {
                "base_frame": self.base_frame,
                "arm_base_frame": self.arm_base_frame,
                # Relative name keeps the controller inside the robot namespace.
                "trajectory_action": "arm_controller/follow_joint_trajectory",
            },
        }
