"""core.services — 의존성 컨테이너 (API/WS가 접근하는 서비스 집합)."""

from __future__ import annotations

import os
from pathlib import Path
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from core_common.capability import Capability
from core_features.command.arbitration import Mode, ModeMachine, SourceRegistry
from core_features.command.manager import CommandManager
from core_features.docking.agent import DockAgent
from core_features.docking.database import DockDatabase, DockError, DockInstance, DockType
from core_features.docking.detector import select_detector
from core_features.docking.feed import DockObservationFeed
from core_features.docking.manager import DockingConfig, DockingManager
from core_features.fleet_agent.agent import FleetAgent
from core_common.domain.adapters import AdapterRegistry

from core_common.domain.model import inventory_from_config, slices_from_config
from core_common.protocol.schemas import DockState, HealthState, RobotMode
from core_events.events.audit import FileAuditLog
from core_events.events.bus import EventBus
from core_common.identity import RobotIdentity
from core_features.maps import MapSnapshotStore
from core_features.navigation.manager import NavigationManager
from core_features.navigation.readiness import NavigationReadinessGate
from core_features.line_follow import LineFollowConfig, LineFollowManager
from core_features.traffic_policy import (
    TrafficPolicyConfig,
    TrafficPolicyManager,
    TrafficPolicyMode,
)
from core_features.vision import VisionFrameStore
from core_features.swarm import SwarmManager
from core_features.power.battery import (
    BatteryConfig,
    BatteryCurve,
    BatteryMonitor,
)
from core_features.power.manager import (
    LidarPolicy,
    PowerConfig,
    PowerManager,
    PresenceConfig,
)
from core_common.profile import RobotProfile
from core_features.safety.manager import (
    BatteryPolicy,
    ModelRegistry,
    PersonAdvisoryFeed,
    SafetyManager,
    SpeedLimits,
)
from core_common.protocol.evidence import CHANNEL_STALE_AFTER_S
from core_features.state.manager import StateManager
from core.system.runtime import HostRuntimeProbe
from core_features.waypoints.manager import WaypointManager


#: 셧다운 요청 표식. 명령이 아니라 관찰이며, 판단과 실행은 호스트 유닛이 한다.
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
    )
    return PowerConfig(
        enabled=bool(raw.get("enabled", defaults.enabled)),
        idle_after_s=float(raw.get("idle_after_s", defaults.idle_after_s)),
        standby_after_s=float(raw.get("standby_after_s", defaults.standby_after_s)),
        info_hold_s=float(raw.get("info_hold_s", defaults.info_hold_s)),
        active_rate_hz=float(raw.get("active_rate_hz", defaults.active_rate_hz)),
        idle_rate_hz=float(raw.get("idle_rate_hz", defaults.idle_rate_hz)),
        standby_rate_hz=float(raw.get("standby_rate_hz", defaults.standby_rate_hz)),
        presence=presence,
        lidar=lidar,
    )


def _line_follow_config(raw: dict[str, Any]) -> LineFollowConfig:
    """Parse the operator-tunable D-143 policy with validation in one place."""
    defaults = LineFollowConfig()
    return LineFollowConfig(
        cruise_speed=float(raw.get("cruise_speed", defaults.cruise_speed)),
        max_linear=float(raw.get("max_linear", defaults.max_linear)),
        steering_gain=float(raw.get("steering_gain", defaults.steering_gain)),
        max_angular=float(raw.get("max_angular", defaults.max_angular)),
        min_confidence=float(raw.get("min_confidence", defaults.min_confidence)),
        stale_after_s=float(raw.get("stale_after_s", defaults.stale_after_s)),
        lost_after_s=float(raw.get("lost_after_s", defaults.lost_after_s)),
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


def _simulation_docking(config: dict[str, Any]) -> Optional[dict[str, Any]]:
    """The sim-only docking block, or None.

    `docking.simulation_supported: true` turns docking on and `docking.seed`
    declares its types and docks, but only under `runtime.mode: simulation`
    (as traffic_policy.simulation_signal_control is gated). The Device keeps
    capabilities.yaml's `docking.supported` and its docks.json.
    """
    raw = config.get("docking") or {}
    if not isinstance(raw, dict) or not raw.get("simulation_supported", False):
        return None
    if str((config.get("runtime") or {}).get("mode", "")).strip().lower() != "simulation":
        return None
    return raw


def _seeded_dock_database(raw: dict[str, Any]) -> DockDatabase:
    """In memory, from the overlay: a sim run starts from the declared dock,
    never from a docks.json an earlier run left behind."""
    database = DockDatabase.empty()
    seed = raw.get("seed") or {}
    for item in seed.get("dock_types", []) or []:
        database.add_type(DockType.model_validate(item))
    for item in seed.get("docks", []) or []:
        database.add(DockInstance.model_validate(item))
    return database


@dataclass
class CoreServices:
    config: dict[str, Any]
    identity: RobotIdentity
    profile: Optional[RobotProfile]
    capability: Capability
    fleet_agent: FleetAgent
    events: EventBus
    state: StateManager
    registry: SourceRegistry
    modes: ModeMachine
    command: CommandManager
    safety: SafetyManager
    advisory_feed: PersonAdvisoryFeed
    waypoints: WaypointManager
    nav: NavigationManager
    line_follow: LineFollowManager
    traffic_policy: TrafficPolicyManager
    vision: VisionFrameStore
    readiness: NavigationReadinessGate
    power: PowerManager
    battery: BatteryMonitor
    docking: DockingManager
    swarm: SwarmManager
    runtime_probe: HostRuntimeProbe
    maps: MapSnapshotStore
    audit: FileAuditLog
    adapter_registry: AdapterRegistry = field(default_factory=AdapterRegistry)
    started_at: float = field(default_factory=time.time)
    # Optional absorbed Control worker, owned by the RosyCoreNode lifecycle.
    # It is populated only when the explicit sensor adapter profile is enabled.
    control_adapter: Any = field(default=None, repr=False)
    # control's dock/observation evidence (ros_bridge ingests, docking reads).
    dock_feed: DockObservationFeed = field(default_factory=DockObservationFeed)

    @classmethod
    def build(cls, config: dict[str, Any], profile: RobotProfile,
              capability_data: dict, waypoints_path) -> "CoreServices":
        robot_id = config.get("robot", {}).get("id", "rosy_01")
        adapter_registry = AdapterRegistry.from_paths(
            (config.get("adapters") or {}).get("manifests") or []
        )
        events = EventBus(robot_id, buffer_size=int(config.get("events", {}).get("ring_buffer_size", 1000)))
        audit = FileAuditLog(Path(waypoints_path).parent / "audit.jsonl")
        events.subscribe(audit.record)

        safety_cfg = config.get("safety", {})
        nav_cfg = config.get("navigation", {})
        readiness_cfg = nav_cfg.get("readiness", {}) or {}
        if not isinstance(readiness_cfg, dict):
            raise ValueError("navigation.readiness must be a mapping")
        # Hardware is fail-closed even if an old local overlay omitted the
        # new key.  Core and simulation keep the historical inert gate unless
        # explicitly opted in for a bench test.
        runtime_mode = str(config.get("runtime", {}).get("mode", "core")).strip().lower()
        raw_readiness_required = readiness_cfg.get("required", runtime_mode == "hardware")
        if type(raw_readiness_required) is not bool:
            raise ValueError("navigation.readiness.required must be a boolean")
        readiness_required = raw_readiness_required
        navigation_backend = str(
            (config.get("runtime") or {}).get("navigation_backend", "localization")
        ).strip().lower()
        if navigation_backend not in {"localization", "slam"}:
            raise ValueError("runtime.navigation_backend must be localization or slam")
        readiness_profiles = readiness_cfg.get("profiles")
        if readiness_profiles is not None and not isinstance(readiness_profiles, dict):
            raise ValueError("navigation.readiness.profiles must be a mapping")
        readiness_components = readiness_cfg.get("required_components")
        if readiness_profiles is not None:
            readiness_components = readiness_profiles.get(navigation_backend)
            if readiness_components is None:
                raise ValueError(
                    "navigation readiness profile is missing for "
                    f"{navigation_backend}"
                )
        readiness = NavigationReadinessGate(
            required=readiness_required,
            stale_after_s=readiness_cfg.get("stale_after_s", 2.0),
            required_components=readiness_components,
        )
        limits = SpeedLimits.from_config(profile=profile, nav_cfg=nav_cfg, safety_cfg=safety_cfg)
        battery_policy = BatteryPolicy(
            warning_percent=float(safety_cfg.get("battery_warning_percent", 20)),
            critical_percent=float(safety_cfg.get("battery_critical_percent", 10)),
            critical_action=str(safety_cfg.get("battery_critical_policy", "RETURN_HOME")),
        )
        safety = SafetyManager(limits, battery_policy,
                               fleet_loss_policy=str(safety_cfg.get("fleet_loss_policy", "STOP")),
                               events=events, policy_required=safety_cfg.get('control_policy_required', False))
        # D-137 T4: 와이어 패킷 → 자문 좌석의 유일한 유입점. revision 명부는
        # vision 슬라이스가 등록/게이트하는 몫이다(T3 계약 — "게이트 자체는
        # vision 슬라이스가 건다"). 시계는 ros_bridge가 노드 시계로 맞춘다.
        advisory_feed = PersonAdvisoryFeed(safety)

        identity = RobotIdentity.from_config(config, profile_model=profile.model)
        simulation_docking = _simulation_docking(config)
        if simulation_docking is not None:
            capability_data = dict(capability_data)
            capability_data["docking"] = dict(capability_data.get("docking") or {},
                                              supported=True)
        capability = Capability(capability_data)
        evidence_cfg = (config.get("state") or {}).get("evidence") or {}
        stale_after = dict(CHANNEL_STALE_AFTER_S)
        if isinstance(evidence_cfg, dict):
            stale_after.update({str(k): float(v) for k, v in evidence_cfg.items()})
        state = StateManager(robot_id, stale_after_s=stale_after)
        registry = SourceRegistry(config.get("command_sources"))
        modes = ModeMachine()
        command = CommandManager(registry, modes, safety, events=events, readiness=readiness)
        waypoints = WaypointManager(waypoints_path, events=events)
        nav = NavigationManager(events, state, waypoints, safety,
                                stuck_timeout_s=float(safety_cfg.get("stuck_timeout_s", 30.0)),
                                readiness=readiness)
        line_follow = LineFollowManager(
            events, config=_line_follow_config(config.get("line_follow", {}) or {}))
        traffic_policy = TrafficPolicyManager(
            events,
            config=_traffic_policy_config(
                config.get("traffic_policy", {}) or {}),
            simulation_signal_control=bool(
                (config.get("runtime") or {}).get("mode") == "simulation"
                and (config.get("traffic_policy") or {}).get(
                    "simulation_signal_control", False)
            ),
        )
        vision_cfg = config.get("vision", {}) or {}
        vision = VisionFrameStore(
            max_bytes=int(vision_cfg.get("preview_max_bytes", 512_000)),
            stale_after_s=float(
                vision_cfg.get("preview_stale_after_s", 2.0)),
            min_pull_interval_s=float(
                vision_cfg.get("preview_min_pull_interval_s", 0.4)),
        )
        power = PowerManager(_power_config(config.get("power", {})), events=events)
        battery = BatteryMonitor(
            _battery_config(safety_cfg, data_path=waypoints_path.parent),
            events=events)
        dock_feed = DockObservationFeed()

        def map_pose():
            pose = state.snapshot().pose
            return (pose.x, pose.y, pose.yaw)

        docking = DockingManager(
            database=(_seeded_dock_database(simulation_docking)
                      if simulation_docking is not None
                      else DockDatabase(waypoints_path.parent / "docks.json")),
            safety=safety,
            config=DockingConfig(),
            events=events,
            # 검출기는 경계 뒤다 — `select_detector` 가 기종·제원·provider·
            # 프레임을 보고 고른다. 프레임 경로(aruco)는 아직 provider도 프레임도
            # 없어서 시뮬레이션으로 떨어진다 (D-138). `detector: observation` 기종은
            # control 의 dock/observation 증거를 `dock_feed` 로 읽는다 (ros_bridge 가
            # 채운다). 신선도는 매니저와 같은 시계로 잰다.
            detector_factory=lambda dock, dock_type: select_detector(
                dock, dock_type, feed=dock_feed, clock=docking.now),
            agent_factory=lambda dock: DockAgent(dock.agent_url),
            capability_provider=lambda: capability.supports("docking.supported"),
            map_id_provider=lambda: state.map_id,
            battery=battery,
            pose_provider=map_pose,
            line_follow_active_provider=lambda: line_follow.active,
            take_mode=lambda: take_docking_mode(),
        )

        def take_docking_mode():
            """Docking drives from start to finish in DOCKING (the docking slot
            only reaches the wheels there). Checked before the manager changes
            anything: a refusal leaves the dock state as it was. The table has
            no NAVIGATION -> DOCKING edge, so NAVIGATION goes through IDLE;
            MANUAL (3) outranks DOCKING (4) and is refused."""
            if modes.mode is Mode.DOCKING:
                return
            if modes.mode not in (Mode.IDLE, Mode.NAVIGATION):
                raise DockError("MODE_CONFLICT",
                                f"invalid transition {modes.mode.value}->DOCKING")
            # Nav2 and a swarm session are cancelled first: a live Nav2 goal
            # would otherwise keep publishing nav_cmd_vel and preempt staging.
            nav.cancel(source="docking")
            previous = modes.mode
            if previous is Mode.NAVIGATION:
                modes.transition(Mode.IDLE)
            modes.transition(Mode.DOCKING)
            command.clear_docking()
            state.set_mode(RobotMode.DOCKING)
            events.publish("mode.changed", source="docking",
                           data={"from": previous.value, "to": Mode.DOCKING.value,
                                 "by": "docking"})
        swarm = SwarmManager(
            events, state, nav, safety, capability,
            # Nav2 를 두고 다투는 것은 DOCKING/UNDOCKING 뿐이다. DOCKED·CHARGING 은
            # 주차 상태이고, DOCK_FAILED 는 설계상 종착이라 그것으로 막으면
            # 도킹 실패 한 번이 군집을 영구히 비활성화한다.
            docking_active_provider=lambda: docking.state in (
                DockState.DOCKING, DockState.UNDOCKING),
            map_id_provider=lambda: state.map_id,
        )
        nav.session_closed_listener = swarm.on_navigation_session_closed
        nav.docking_active_provider = lambda: (
            modes.mode is Mode.DOCKING
            or docking.state in (DockState.DOCKING, DockState.UNDOCKING))

        def leave_docking(old, new):
            """Every exit from DOCKING stops the docking run first — API, line
            follow, e-stop or the bridge's release. The docking slot only
            reaches the wheels in DOCKING, and nothing else may keep driving it."""
            if old is not Mode.DOCKING:
                return
            if new is Mode.EMERGENCY:
                docking.abort("emergency stop during docking")
            else:
                docking.cancel()
            command.clear_docking()
        modes.change_listeners.append(leave_docking)
        def reflect_stop():
            state.set_estop(True)
        safety.estop_listeners.append(reflect_stop)
        safety.estop_listeners.append(swarm.on_estop)
        safety.estop_listeners.append(lambda: nav.cancel(source='safety_manager'))
        def stop_line_follow():
            status = line_follow.stop()
            command.clear_navigation()
            state.set_line_follow(status)
        safety.estop_listeners.append(stop_line_follow)
        def reset_traffic_policy():
            status = traffic_policy.reset("estop")
            state.set_traffic_policy(status)
        safety.estop_listeners.append(reset_traffic_policy)
        runtime_probe = HostRuntimeProbe(
            host_root=os.environ.get("ROSY_HOST_ROOT", "/"),
            data_path=waypoints_path.parent,
        )
        fleet_agent = FleetAgent(state, events, config, identity)
        fleet_agent.start()
        
        return cls(config=config, identity=identity, profile=profile, capability=capability, fleet_agent=fleet_agent,
                   events=events, state=state, registry=registry, modes=modes,
                   command=command, safety=safety, advisory_feed=advisory_feed,
                   waypoints=waypoints, nav=nav,
                   line_follow=line_follow,
                   traffic_policy=traffic_policy,
                   vision=vision,
                   readiness=readiness,
                   power=power, battery=battery, docking=docking, swarm=swarm,
                   runtime_probe=runtime_probe, maps=MapSnapshotStore(),
                   audit=audit, adapter_registry=adapter_registry,
                   dock_feed=dock_feed)

    def inventory(self) -> dict[str, Any]:
        cap001 = self.capability.to_dict()
        sensors = cap001.get("sensors") or []
        snap = self.state.snapshot()
        data = inventory_from_config(
            self.config,
            profile_model=self.profile.model if self.profile is not None else "unknown",
            sensors=[str(item) for item in sensors],
            slices=slices_from_config(self.config),
            mode=self.modes.mode,
            health_error=any(
                health is HealthState.ERROR
                for health in snap.diagnostics_summary.values()
            ),
            estop=bool(self.safety.estop),
            booting=not snap.diagnostics_summary,
            cap001=cap001,
            hitl_requested=snap.hitl_requested,
        )
        data["adapters"] = [item.id for item in self.adapter_registry.enabled()]
        return data
