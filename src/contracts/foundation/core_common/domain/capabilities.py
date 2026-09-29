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
    #: Every reason, most basic first; `reason` is the first (v1.21 additive).
    reasons: tuple[str, ...] = ()

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
#: A hardware runtime reported once and then went quiet.
HARDWARE_SILENT_REASON = "hardware_silent"
#: The bringup reports `motor/ready: false` — D-192 no-motion mode: torque
#: off, `cmd_vel` not subscribed. Motion is a configuration away, not a fault.
DRIVE_DISABLED_REASON = "drive_disabled:no_motion"
#: `motor/ready` was true but its lease expired: the motor process went quiet.
DRIVE_STALE_REASON = "drive_lease_expired"
#: Nothing reported `motor/ready` where a drive is needed.
DRIVE_ABSENT_REASON = "drive_absent"
#: The Nav2/SLAM lifecycle nodes this backend needs have not reported active.
NAVIGATION_ABSENT_REASON = "navigation_absent"

#: How long one odometry or battery sample proves the hardware runtime is up.
#: The battery publisher samples every 5 s, so this spans a couple of misses.
HARDWARE_LIVENESS_S = 15.0

# CAP-001 flags that need motors, sensors or Nav2. `return_home` has no
# descriptor of its own but drives the same base.
HARDWARE_FLAGS: tuple[str, ...] = tuple(
    flag for flag, _ in _CAP001_TO_CONCEPT
) + ("navigation.return_home",)

# Flags that also need the navigation stack (Nav2 lifecycle, or SLAM).
_NAVIGATION_FLAGS = frozenset({
    "navigation.goal_navigation", "navigation.return_home", "slam",
})
# Flags that move the base, so need a drive that accepts `cmd_vel`.
# `slam` (perception.localize) does not move the base by itself.
_DRIVE_FLAGS = frozenset(HARDWARE_FLAGS) - {"slam"}

_MOTOR = "motor_adapter"


def runtime_capability_data(data: Mapping[str, Any], *, mode: str,
                            navigation_backend: str,
                            deployment: str = "") -> dict[str, Any]:
    """Limit profile flags to features supported by the selected runtime stack.

    Live hardware availability is evaluated separately by runtime_truth, so
    CORE mode does not permanently hide hardware that starts later.
    """
    result = {key: dict(value) if isinstance(value, dict) else value
              for key, value in data.items()}
    if mode == "core" and deployment == "device":
        return withhold_hardware_flags(
            result, {flag: CORE_ONLY_REASON for flag in HARDWARE_FLAGS})
    if mode == "motor":
        navigation = dict(result.get("navigation") or {})
        navigation["goal_navigation"] = False
        navigation["return_home"] = False
        result["navigation"] = navigation
        swarm = dict(result.get("swarm") or {})
        swarm["follow"] = False
        swarm["lead"] = False
        result["swarm"] = swarm
        result["slam"] = False
    elif mode == "hardware" and navigation_backend != "slam":
        result["slam"] = False
    return result


@dataclass(frozen=True)
class RuntimeTruth:
    """What the running hardware can keep right now, from live evidence (D-32).

    `hardware`: `on` (odometry or battery within HARDWARE_LIVENESS_S), `silent`
    (it reported once, not lately) or `off` (never reported).
    `drive`: `ready`, `disabled` (motor/ready false), `stale` (lease expired)
    or `unknown` (never reported — a simulator bench has no motor/ready).
    `navigation`: `ready`, `absent` or `unknown` (not judged: no real
    bringup and the readiness gate is not required).
    `reasons`: the first reason each CAP-001 hardware flag cannot be kept.
    """

    mode: str
    hardware: str
    evidence: tuple[str, ...]
    drive: str
    navigation: str
    reasons: Mapping[str, str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "hardware": self.hardware,
            "evidence": list(self.evidence),
            "drive": self.drive,
            "navigation": self.navigation,
        }


# Pose may be refreshed from a cached map->base TF after odometry stops.
# Only the odometry callback's velocity sample proves the base is still live.
_PRESENCE_CHANNELS = (
    ("odometry", ("velocity",)),
    ("battery", ("battery",)),
)


def _hardware_presence(state: Any) -> tuple[str, tuple[str, ...]]:
    live: list[str] = []
    seen = False
    for label, channels in _PRESENCE_CHANNELS:
        ages = [age for age in (state.received_age(ch) for ch in channels) if age is not None]
        if not ages:
            continue
        seen = True
        if min(ages) <= HARDWARE_LIVENESS_S:
            live.append(label)
    if live:
        return "on", tuple(live)
    return ("silent" if seen else "off"), ()


def runtime_truth(config: Mapping[str, Any], state: Any, readiness: Any = None) -> RuntimeTruth:
    """Judge hardware, drive and navigation presence from live evidence.

    The configured `runtime.mode` alone does not say whether hardware runs:
    on the native image the operator starts `rosy-io` by hand while the mode
    string stays `core` (D-192). So presence comes from samples — odometry or
    battery — and drive readiness from the bringup's `motor/ready` report.

    `state` needs `received_age()`; `readiness` needs `component_state()`,
    `required` and `required_components` (None: drive and navigation unknown).
    """
    runtime = config.get("runtime") or {}
    mode = str(runtime.get("mode") or "core").strip().lower()
    hardware, evidence = _hardware_presence(state)

    motor = "unobserved"
    required = False
    components: tuple[str, ...] = ()
    if readiness is not None:
        motor = readiness.component_state(_MOTOR)
        required = bool(readiness.required)
        components = tuple(readiness.required_components)
    drive = {"ready": "ready", "inactive": "disabled", "stale": "stale"}.get(motor, "unknown")

    # Navigation is judged where a real stack is expected: the gate is
    # required (hardware mode), or a real bringup reported motor/ready. A
    # simulator bench runs CORE-only with odometry and no motor/ready; it
    # keeps the historical behaviour (not judged).
    navigation = "unknown"
    nav_components = [name for name in components if name != _MOTOR]
    if readiness is not None and (required or drive != "unknown") and nav_components:
        ready = all(readiness.component_state(name) == "ready" for name in nav_components)
        navigation = "ready" if ready else "absent"

    drive_reason: Optional[str] = None
    if drive == "disabled":
        drive_reason = DRIVE_DISABLED_REASON
    elif drive == "stale":
        drive_reason = DRIVE_STALE_REASON
    elif drive == "unknown":
        # A simulator bench proves its base with odometry and never reports
        # motor/ready; a required gate (hardware mode) needs the report.
        motor_required = required and _MOTOR in components
        if motor_required or "odometry" not in evidence:
            drive_reason = DRIVE_ABSENT_REASON

    hold_reason: Optional[str] = None
    if readiness is not None and required:
        snapshot = readiness.snapshot()
        if not snapshot.ready:
            hold_reason = "readiness_hold:" + ",".join(snapshot.missing)

    reasons: dict[str, str] = {}
    for flag in HARDWARE_FLAGS:
        if mode == "motor" and hardware == "off" and drive == "unknown":
            # The motor bench advertises its selected stack before telemetry.
            # A reported disabled or stale drive still withholds motion.
            continue
        if mode == "core" and hardware == "off":
            reasons[flag] = CORE_ONLY_REASON
        elif hardware == "silent":
            reasons[flag] = HARDWARE_SILENT_REASON
        elif flag in _DRIVE_FLAGS and drive_reason:
            reasons[flag] = drive_reason
        elif flag == "slam" and "odometry" not in evidence:
            # A battery sample proves IO is alive, not that a base can localize.
            reasons[flag] = drive_reason or DRIVE_ABSENT_REASON
        elif flag in _NAVIGATION_FLAGS and navigation == "absent":
            reasons[flag] = NAVIGATION_ABSENT_REASON
        elif hold_reason:
            reasons[flag] = hold_reason
    return RuntimeTruth(mode=mode, hardware=hardware, evidence=evidence,
                        drive=drive, navigation=navigation, reasons=reasons)


def withhold_hardware_flags(data: Mapping[str, Any], reasons: Mapping[str, str]) -> dict[str, Any]:
    """CAP-001 as this runtime can actually keep it (D-32).

    Every hardware flag that was advertised true and has a reason becomes
    false, and the additive `withheld` block says which ones and why:
    `reason` is the first withheld flag's reason (v1.18), `reasons` each
    flag's own (v1.21). The profile YAML is left alone: it still says what
    the robot can do once its runtime is up.
    """
    result: dict[str, Any] = {
        key: dict(value) if isinstance(value, dict) else value
        for key, value in data.items()
    }
    withheld: list[str] = []
    per_flag: dict[str, str] = {}
    for flag in HARDWARE_FLAGS:
        reason = reasons.get(flag)
        if not reason or not _flag_is_true(result, flag):
            continue
        *parents, leaf = flag.split(".")
        node = result
        for part in parents:
            node = node[part]
        node[leaf] = False
        withheld.append(flag)
        per_flag[flag] = reason
    if withheld:
        result["withheld"] = {
            "flags": withheld,
            "reason": per_flag[withheld[0]],
            "reasons": per_flag,
        }
    return result


class CapabilityLifecycle(str, enum.Enum):
    """D-347: 플래그별 런타임 생애 — 두 표면이 쓰는 단일 어휘.

    `activating`은 온디맨드 그래프 기동(토론 B레인)을 위해 **예약**되어
    있다: 아직 이 상태로 진입하는 생산자는 없다. 클라이언트는 이 값을
    "준비 안 됨, 실패 아님"으로 읽는다 — 갱신하거나 기다리지, 오류로
    승격하지 않는다. inventory 기술자의 PresentationState와의 대응은
    D-347 본문의 표가 정한다(코드가 아니다).
    """

    READY = "ready"
    ACTIVATING = "activating"
    UNAVAILABLE = "unavailable"


def lifecycle_from(
    advertised: Mapping[str, Any],
    runtime_reasons: Mapping[str, str],
) -> dict[str, dict[str, Any]]:
    """CAP-001 플래그별 lifecycle (D-347, v1.58 additive).

    입력은 런타임이 **광고하는** capabilities 사전이다 — 모드 마스킹을 거쳤고
    이미 `withheld` 블록을 담고 있을 수 있다(core+device, D-32). 원천은
    전부 이미 있는 값이다: 마스킹 사유, `runtime_truth`의 플래그별 사유,
    플래그의 참/거짓. 이 함수는 그 셋을 한 어휘로 합칠 뿐 새 판정을
    만들지 않는다.

    규칙: 광고가 true 이거나 마스킹이 보류(wielded)한 플래그만 실는다 —
    프로파일과 런타임 어느 쪽도 true로 말하지 않는 플래그는 결과에 없다
    (설계 §7). 사유는 **마스킹 사유가 우선**이다: 그것이 선의 `withheld`
    블록이 말하는 바이고, 꺼진 플래그에 대한 runtime 사유는 선에 안
    오르므로 여기서도 말하지 않는다.
    """
    withheld_block = advertised.get("withheld") or {}
    withheld_flags = set(withheld_block.get("flags") or ())
    masked_reasons = withheld_block.get("reasons") or {}
    out: dict[str, dict[str, Any]] = {}
    for flag in HARDWARE_FLAGS:
        if not (_flag_is_true(advertised, flag) or flag in withheld_flags):
            continue
        reason = masked_reasons.get(flag) or runtime_reasons.get(flag)
        if reason:
            out[flag] = {
                "state": CapabilityLifecycle.UNAVAILABLE.value,
                "reason": reason,
                "reasons": (reason,),
            }
        else:
            out[flag] = {"state": CapabilityLifecycle.READY.value}
    return out


def _presentation(
    device_state: Optional[DeviceState],
    runtime_reason: Optional[str] = None,
) -> tuple[bool, str, tuple[str, ...]]:
    """Availability, presentation state and every reason, most basic first.

    A missing runtime (CORE-only, drive disabled, no Nav2) comes before the
    device state: releasing an e-stop does not make a robot without a drive
    move, so SAFE_STOP must not hide the reason that outlives it.
    """
    reasons: list[str] = []
    if runtime_reason:
        reasons.append(runtime_reason)
    if device_state in _UNAVAILABLE_STATES:
        reasons.append(f"device_state:{device_state.value}")
    if reasons:
        return False, PresentationState.BLOCKED.value, tuple(reasons)
    if device_state is DeviceState.DEGRADED:
        return (
            True,
            PresentationState.DEGRADED_FALLBACK.value,
            (f"device_state:{device_state.value}",),
        )
    return True, PresentationState.AVAILABLE.value, ()


def descriptors_from_cap001(
    data: Mapping[str, Any],
    *,
    device_state: Optional[DeviceState] = None,
    runtime_reasons: Optional[Mapping[str, str]] = None,
) -> tuple[CapabilityDescriptor, ...]:
    """`runtime_reasons` maps a CAP-001 flag to why its runtime cannot keep it."""
    runtime_reasons = runtime_reasons or {}
    descriptors = []
    for flag, concept_id in _CAP001_TO_CONCEPT:
        if not _flag_is_true(data, flag):
            continue
        available, state, reasons = _presentation(device_state, runtime_reasons.get(flag))
        descriptors.append(CapabilityDescriptor(
            id=concept_id, available=available, state=state,
            reason=reasons[0] if reasons else None, reasons=reasons,
        ))
    return tuple(descriptors)
