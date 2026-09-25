"""core_common.domain.capabilities — CAP-001 flags → concept descriptor ids. ROS 무의존."""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Any, Mapping, Optional

from core_common.domain.model import DeviceState

# Design §7. False flags are omitted. manipulate.pick / scan_rfid / infer / train stay off.
_CAP001_TO_CONCEPT: tuple[tuple[str, str], ...] = (
    ("teleop", "mobility.move"),
    ("navigation.goal_navigation", "mobility.navigate"),
    ("swarm.follow", "mobility.follow"),
    ("swarm.lead", "mobility.lead"),
    ("docking.supported", "mobility.dock"),
    ("slam", "perception.localize"),
)

# Concept 07 §5: availability depends on device state. YAML advertisement
# (CAP-001) stays true; inventory descriptors drop available during these.
_UNAVAILABLE_STATES = {
    DeviceState.BOOTING,
    DeviceState.FAULT,
    DeviceState.SAFE_STOP,
    DeviceState.OFFLINE,
    DeviceState.UPDATING,
}


class PresentationState(str, enum.Enum):
    """concept 16 §8. `not_provided` is the S7 rename of `absent` (token clash)."""

    AVAILABLE = "available"
    CONSTRAINED = "constrained"
    DEGRADED_FALLBACK = "degraded_fallback"
    BLOCKED = "blocked"
    NOT_PROVIDED = "not_provided"


@dataclass(frozen=True)
class CapabilityDescriptor:
    id: str
    available: bool = True
    state: str = PresentationState.AVAILABLE.value
    reason: Optional[str] = None

    def __post_init__(self) -> None:
        if self.state == PresentationState.BLOCKED.value and not self.reason:
            raise ValueError("blocked capability requires a reason")


def _flag_is_true(data: Any, dotted: str) -> bool:
    node = data
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return False
        node = node[part]
    return node is True


#: Blocked-descriptor reason while the hardware runtime is off (D-161, D-32).
CORE_ONLY_REASON = "runtime_mode:core"

# CAP-001 flags that need motors, sensors or Nav2. `return_home` has no
# descriptor of its own but drives the same base.
HARDWARE_FLAGS: tuple[str, ...] = tuple(
    flag for flag, _ in _CAP001_TO_CONCEPT
) + ("navigation.return_home",)


def withhold_hardware_flags(data: Mapping[str, Any], reason: str) -> dict[str, Any]:
    """CAP-001 as this runtime can actually keep it (D-32).

    Every hardware flag that was advertised true becomes false, and the
    additive `withheld` block says which ones and why. The profile YAML is
    left alone: it still says what the robot can do once its runtime is up.
    """
    result: dict[str, Any] = {
        key: dict(value) if isinstance(value, dict) else value
        for key, value in data.items()
    }
    withheld = []
    for flag in HARDWARE_FLAGS:
        if not _flag_is_true(result, flag):
            continue
        *parents, leaf = flag.split(".")
        node = result
        for part in parents:
            node = node[part]
        node[leaf] = False
        withheld.append(flag)
    if withheld:
        result["withheld"] = {"flags": withheld, "reason": reason}
    return result


def hardware_runtime_reason(config: Mapping[str, Any], state: Any) -> Optional[str]:
    """Why hardware capabilities are withheld right now, or None.

    CORE-only runtime (D-161) has no motor, IO or Nav2 unit, so nothing that
    moves or localizes can be kept (D-32). Odometry proves a base is attached
    anyway (a simulator bench runs `core` with simulated odom), so the first
    pose or velocity sample lifts the gate. `state` needs `has_received()`.
    """
    runtime = config.get("runtime") or {}
    if str(runtime.get("mode") or "core").strip().lower() != "core":
        return None
    if state.has_received("pose") or state.has_received("velocity"):
        return None
    return CORE_ONLY_REASON


def _presentation(
    device_state: Optional[DeviceState],
    runtime_reason: Optional[str] = None,
) -> tuple[bool, str, Optional[str]]:
    if device_state in _UNAVAILABLE_STATES:
        return (
            False,
            PresentationState.BLOCKED.value,
            f"device_state:{device_state.value}",
        )
    if runtime_reason:
        return False, PresentationState.BLOCKED.value, runtime_reason
    if device_state is None:
        return True, PresentationState.AVAILABLE.value, None
    if device_state is DeviceState.DEGRADED:
        return (
            True,
            PresentationState.DEGRADED_FALLBACK.value,
            f"device_state:{device_state.value}",
        )
    return True, PresentationState.AVAILABLE.value, None


def descriptors_from_cap001(
    data: Mapping[str, Any],
    *,
    device_state: Optional[DeviceState] = None,
    runtime_reason: Optional[str] = None,
) -> tuple[CapabilityDescriptor, ...]:
    """`runtime_reason` blocks every descriptor: they all need hardware."""
    available, state, reason = _presentation(device_state, runtime_reason)
    return tuple(
        CapabilityDescriptor(
            id=concept_id, available=available, state=state, reason=reason
        )
        for flag, concept_id in _CAP001_TO_CONCEPT
        if _flag_is_true(data, flag)
    )
