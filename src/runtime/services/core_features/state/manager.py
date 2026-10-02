"""core_features.state.manager — CORE-001 (P1-4). 10 Hz 스냅샷. ROS 무의존."""

from __future__ import annotations

import logging
import threading
from typing import Callable, Optional

import time

from core_common.protocol.evidence import CHANNEL_STALE_AFTER_S, judge
from core_common.protocol.schemas import (
    Battery,
    BatteryStatus,
    DockingStatus,
    HealthState,
    LineFollowStatus,
    NavigationState,
    Pose,
    PowerStatus,
    RobotActivity,
    RobotMode,
    SafetyPolicyStatus,
    SafetySummary,
    StateSnapshot,
    SwarmStatus,
    TrafficPolicyStatus,
    Velocity,
)

log = logging.getLogger(__name__)


def _as_map_id(value) -> Optional[str]:
    """MAP-001 map id, normalised to a string or nothing.

    `navigation.map_id: 42` in YAML parses as an int, and every consumer here
    treats the id as a string: the swarm map guard compares it (so a non-string
    never matches and the formation silently stops issuing goals), and the
    leader pose stream declares it `Optional[str]` (so pydantic raises and the
    socket closes on connect, with the handler's bare except hiding why). A
    scalar the operator typed becomes its text; anything else is not an id.
    """
    if isinstance(value, str):
        return value or None
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return str(value)
    return None


class StateManager:
    def __init__(self, robot_id: str, clock=time.time, stale_after_s=None,
                 sources_configured: bool = True, monotonic=time.monotonic) -> None:
        self._robot_id = robot_id
        # False in CORE-only runtime (D-161): no motor, IO or Nav2 unit runs, so a
        # channel that never reported has no source at all. It is judged
        # `unavailable` (nothing configured), not `disconnected` (a source that
        # went quiet). The first sample proves a source and normal judgment resumes.
        self._sources_configured = sources_configured
        self._clock = clock
        self._monotonic = monotonic
        self._received_mono: dict[str, float] = {}
        self._stale_after_s = dict(CHANNEL_STALE_AFTER_S)
        if stale_after_s:
            for channel, value in stale_after_s.items():
                self._stale_after_s[str(channel)] = float(value)
        self._lock = threading.Lock()
        self._seq = 0
        self._received: dict[str, float] = {}
        self._mode: RobotMode = RobotMode.IDLE
        self._navigation: NavigationState = NavigationState.IDLE
        self._pose = Pose()
        self._velocity = Velocity()
        self._battery = Battery()
        self._battery_status = BatteryStatus()
        self._docking = DockingStatus()
        self._safety = SafetySummary()
        self._swarm = SwarmStatus()
        self._power = PowerStatus()
        self._line_follow = LineFollowStatus()
        self._traffic_policy = TrafficPolicyStatus()
        self._map_id: Optional[str] = None
        self._diagnostics: dict[str, HealthState] = {}
        self._errors: list[str] = []
        self._sensors: dict[str, dict] = {}
        self._hitl_requested: bool = False
        self._capabilities_degraded: list[str] = []
        self._activity_provider: Optional[Callable[[], Optional[dict]]] = None
        self._safety_policy_provider: Optional[Callable[[], Optional[dict]]] = None
        self._safety_policy_error: Optional[str] = None  # last logged error type
        self._localization_provider: Optional[Callable[[], object]] = None

    def set_localization_provider(self, provider: Optional[Callable[[], object]]) -> None:
        """D-395 P2-1: read live, so the stale timeout and the odom frame flag apply."""
        with self._lock:
            self._localization_provider = provider

    def set_hitl_requested(self, requested: bool) -> None:
        with self._lock:
            self._hitl_requested = requested

    def set_activity_provider(self, provider: Optional[Callable[[], Optional[dict]]]) -> None:
        """D-321 addendum: the calibration lease is read live, so `remaining_s` ticks."""
        with self._lock:
            self._activity_provider = provider

    def set_safety_policy_provider(self, provider: Optional[Callable[[], Optional[dict]]]) -> None:
        """D-400: the safety policy/shadow block, read live on every snapshot."""
        with self._lock:
            self._safety_policy_provider = provider

    def set_capabilities_degraded(self, modules: list[str]) -> None:
        with self._lock:
            self._capabilities_degraded = list(modules)

    def set_robot_id(self, robot_id: str) -> None:
        with self._lock:
            self._robot_id = robot_id

    def set_mode(self, mode: RobotMode) -> None:
        with self._lock:
            self._mode = mode

    def set_navigation(self, state: NavigationState) -> None:
        with self._lock:
            self._navigation = state
            self._mark("navigation")

    def set_pose(self, x: float, y: float, yaw: float) -> None:
        with self._lock:
            self._pose = Pose(x=x, y=y, yaw=yaw)
            self._mark("pose")

    def set_velocity(self, linear: float, angular: float) -> None:
        with self._lock:
            self._velocity = Velocity(linear=linear, angular=angular)
            self._mark("velocity")

    def set_battery(self, percent: Optional[float], voltage: Optional[float] = None) -> None:
        with self._lock:
            self._battery = Battery(percent=percent if percent is not None else self._battery.percent,
                                    voltage=voltage if voltage is not None else self._battery.voltage)
            self._mark("battery")

    def set_estop(self, active: bool) -> None:
        with self._lock:
            self._safety = SafetySummary(estop=active)
            self._mark("safety")

    def set_swarm(self, status: SwarmStatus) -> None:
        with self._lock:
            self._swarm = status

    def set_map_id(self, map_id) -> None:
        with self._lock:
            self._map_id = _as_map_id(map_id)

    @property
    def map_id(self) -> Optional[str]:
        with self._lock:
            return self._map_id

    def set_diagnostic(self, component: str, health: HealthState) -> None:
        with self._lock:
            self._diagnostics[component] = health

    def set_power(self, status: PowerStatus) -> None:
        with self._lock:
            self._power = status

    def set_line_follow(self, status: LineFollowStatus) -> None:
        with self._lock:
            self._line_follow = LineFollowStatus.model_validate(status)

    def set_traffic_policy(self, status: TrafficPolicyStatus) -> None:
        with self._lock:
            self._traffic_policy = TrafficPolicyStatus.model_validate(status)

    def set_battery_status(self, status: BatteryStatus) -> None:
        with self._lock:
            self._battery_status = status

    def set_docking(self, status: DockingStatus) -> None:
        with self._lock:
            self._docking = status
            self._mark("docking")

    def set_sensor(self, key: str, data: dict) -> None:
        with self._lock:
            self._sensors[key] = data

    def get_sensors(self) -> dict:
        with self._lock:
            return {k: dict(v) for k, v in self._sensors.items()}

    def get_sensor(self, key: str) -> Optional[dict]:
        with self._lock:
            data = self._sensors.get(key)
            return dict(data) if data else None

    def has_received(self, channel: str) -> bool:
        """True once any sample arrived on `channel` (no seq bump)."""
        with self._lock:
            return channel in self._received

    def _mark(self, channel: str) -> None:
        """Record wall time for API evidence and monotonic time for age checks.

        The caller holds ``self._lock``.
        """
        self._received[channel] = self._clock()
        self._received_mono[channel] = self._monotonic()

    def received_age(self, channel: str) -> Optional[float]:
        """Monotonic seconds since the last sample, or None if none arrived."""
        with self._lock:
            stamp = self._received_mono.get(channel)
            return None if stamp is None else max(0.0, self._monotonic() - stamp)

    def push_error(self, message: str) -> None:
        with self._lock:
            self._errors.append(message)
            self._errors = self._errors[-20:]

    def snapshot(self) -> StateSnapshot:
        # Read the lease before taking our lock: the provider has its own lock
        # and may publish an expiry event.
        provider = self._activity_provider
        raw_activity = provider() if provider is not None else None
        activity = RobotActivity.model_validate(raw_activity) if raw_activity else None
        # D-400: the shadow block is diagnostics; a failing or malformed provider
        # must never take the state API down, so it degrades to null.
        safety_policy = None
        safety_provider = self._safety_policy_provider
        if safety_provider is not None:
            try:
                raw_policy = safety_provider()
                safety_policy = SafetyPolicyStatus.model_validate(raw_policy) if raw_policy else None
                self._safety_policy_error = None
            except Exception as exc:
                safety_policy = None
                if type(exc).__name__ != self._safety_policy_error:
                    self._safety_policy_error = type(exc).__name__
                    log.warning("safety_policy block unavailable: %s: %s", type(exc).__name__, exc)
        localization_provider = self._localization_provider
        localization = localization_provider() if localization_provider is not None else None
        with self._lock:
            self._seq += 1
            now = self._clock()
            evidence = {
                channel: judge(
                    has_source=(self._sources_configured
                                or channel in self._received),
                    received_at=self._received.get(channel),
                    now=now,
                    stale_after_s=stale,
                )
                for channel, stale in self._stale_after_s.items()
            }
            return StateSnapshot(
                robot_id=self._robot_id,
                online=True,
                mode=self._mode,
                navigation=self._navigation,
                map_id=self._map_id,
                pose=self._pose.model_copy(),
                velocity=self._velocity.model_copy(),
                battery=self._battery.model_copy(),
                battery_status=self._battery_status.model_copy(),
                docking=self._docking.model_copy(),
                safety=self._safety.model_copy(),
                swarm=self._swarm.model_copy(),
                power=self._power.model_copy(),
                line_follow=self._line_follow.model_copy(),
                traffic_policy=self._traffic_policy.model_copy(),
                diagnostics_summary=dict(self._diagnostics),
                errors=list(self._errors),
                seq=self._seq,
                evidence=evidence,
                hitl_requested=self._hitl_requested,
                capabilities_degraded=list(self._capabilities_degraded),
                activity=activity,
                safety_policy=safety_policy,
                localization=localization,
            )
