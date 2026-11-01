"""core.services — 의존성 컨테이너 (API/WS가 접근하는 서비스 집합)."""

from __future__ import annotations

import os
from pathlib import Path
import time
from dataclasses import dataclass, field
import logging
from typing import Any, Optional

from core_common.capability import Capability
from core_features.calibration import CalibrationSessionManager
from core.trip_lease import TripLeaseManager, build_trip_lease  # D-541
from core_features.command.arbitration import Mode, ModeMachine, SourceRegistry
from core_features.command.manager import CommandManager, Twist
from core.teleop_config import teleop_timeout_ms
from core.fleet_loss_wiring import build_fleet_loss
from core.drive.line_follow import (  # noqa: F401 (tests import the parser here)
    _line_follow_config, build_line_follow, bind_motion_envelope, bind_stuck_recovery)
from core.drive.docking import (  # noqa: F401 (legacy parser exports)
    _simulation_docking, _seeded_dock_database, build_docking_and_swarm)
from core.drive.traffic import (  # noqa: F401 (legacy parser exports)
    _traffic_policy_config, _signal_observer_binding, build_traffic)
from core.system.power import (  # noqa: F401 (legacy parser and sentinel exports)
    SHUTDOWN_SENTINEL_NAME, _battery_config, _power_config, build_power_and_battery)
from core_features.docking.feed import DockObservationFeed
from core_features.docking.manager import DockingManager
from core_features.docking.station_owner import StationDockingOwner
from core_features.fleet_agent.agent import FleetAgent
from core_features.localization import LocalizationAssist, LocalizationMission, wire_assist
from core_features.localization.mission import mission_config
from core_common.domain.adapters import AdapterRegistry
from core_common.domain.pilot_recording import PilotRecordingGuard

from core_common.domain.capabilities import runtime_capability_data, runtime_truth
from core_common.domain.model import inventory_from_config, slices_from_config
from core_common.protocol.schemas import HealthState, RobotMode
from core_events.events.audit import FileAuditLog
from core_events.events.bus import EventBus
from core_common.identity import RobotIdentity
from core_features.maps import MapSnapshotStore
from core_features.navigation.manager import NavigationManager
from core_features.navigation.readiness import NavigationReadinessGate
from core_features.line_follow import LineFollowManager
from core_common.protocol.line_advice import AdviceStore
from core_features.traffic_policy import (
    SignalObserverMonitor,
    SignalObserverPoller,
    SignalObserverSourceConfig,
    TrafficPolicyConfig,
    TrafficPolicyManager,
    TrafficPolicyMode,
)
from core_features.vision import VisionFrameStore
from core_features.vision.stream import DriverStreamGate
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
from core_features.safety.fleet_loss import FleetLossMonitor
from core_common.protocol.evidence import CHANNEL_STALE_AFTER_S
from core_features.state.manager import StateManager
from core.system.runtime import HostRuntimeProbe
from core.system.host_files import HostFileExchange
from core_features.waypoints.manager import WaypointManager


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
    # D-337 measured-light observer monitor; None while no observer is bound.
    signal_observer: Optional[SignalObserverMonitor]
    vision: VisionFrameStore
    readiness: NavigationReadinessGate
    power: PowerManager
    battery: BatteryMonitor
    docking: DockingManager
    swarm: SwarmManager
    runtime_probe: HostRuntimeProbe
    host_files: HostFileExchange
    maps: MapSnapshotStore
    audit: FileAuditLog
    # D-321 addendum: attended calibration lease (visible on every screen, fences drive writes).
    calibration: CalibrationSessionManager
    trip_lease: TripLeaseManager  # D-541: fences non-owner motion; ends with the trip's driving
    adapter_registry: AdapterRegistry = field(default_factory=AdapterRegistry)
    pilot_recording: PilotRecordingGuard = field(default_factory=PilotRecordingGuard)  # D-411 A
    vision_stream: DriverStreamGate = field(default_factory=DriverStreamGate)  # D-368
    started_at: float = field(default_factory=time.time)
    # Optional absorbed Control worker, owned by the RosyCoreNode lifecycle.
    # It is populated only when the explicit sensor adapter profile is enabled.
    control_adapter: Any = field(default=None, repr=False)
    # control's dock/observation evidence (ros_bridge ingests, docking reads).
    dock_feed: DockObservationFeed = field(default_factory=DockObservationFeed)
    station_docking: Optional[StationDockingOwner] = None
    localization: Optional[LocalizationAssist] = None  # D-395 P2-1 (ros_bridge ingests)
    loc_mission: Optional[LocalizationMission] = None  # D-395 P2-7 (ros_bridge ticks)
    fleet_loss: Optional[FleetLossMonitor] = None  # SAF-003 D-419 (ros_bridge ticks)
    # D-525 signal advice, display only: kept off LineFollowManager so no decision can read it.
    line_advice: AdviceStore = field(default_factory=AdviceStore)
    arm_policy: Any = field(default=None, repr=False)  # Explicit installed OMX session only.

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
        capability = Capability(runtime_capability_data(
            capability_data, mode=runtime_mode, navigation_backend=navigation_backend,
            deployment=str((config.get("runtime") or {}).get("deployment", ""))))
        evidence_cfg = (config.get("state") or {}).get("evidence") or {}
        stale_after = dict(CHANNEL_STALE_AFTER_S)
        if isinstance(evidence_cfg, dict):
            stale_after.update({str(k): float(v) for k, v in evidence_cfg.items()})
        state = StateManager(robot_id, stale_after_s=stale_after,
                             sources_configured=runtime_mode != "core")
        calibration = CalibrationSessionManager(events)
        state.set_activity_provider(calibration.activity)
        registry = SourceRegistry(config.get("command_sources"))
        modes = ModeMachine()
        command = CommandManager(registry, modes, safety, events=events, readiness=readiness,
                                 teleop_timeout_ms=teleop_timeout_ms(safety_cfg))
        waypoints = WaypointManager(waypoints_path, events=events)
        nav = NavigationManager(events, state, waypoints, safety,
                                stuck_timeout_s=float(safety_cfg.get("stuck_timeout_s", 30.0)),
                                readiness=readiness)
        line_follow = build_line_follow(config, events=events, safety=safety)
        traffic_policy, signal_observer = build_traffic(config, events=events)
        state.set_traffic_policy(traffic_policy.status())
        vision_cfg = config.get("vision", {}) or {}
        vision = VisionFrameStore(
            max_bytes=int(vision_cfg.get("preview_max_bytes", 512_000)),
            stale_after_s=float(
                vision_cfg.get("preview_stale_after_s", 2.0)),
            min_pull_interval_s=float(
                vision_cfg.get("preview_min_pull_interval_s", 0.4)),
        )
        power, battery = build_power_and_battery(
            config.get("power", {}), safety_cfg, data_path=waypoints_path.parent, events=events)
        docking, swarm, dock_feed, leave_docking, station_docking = build_docking_and_swarm(
            simulation_docking=simulation_docking, data_path=waypoints_path.parent,
            events=events, state=state, modes=modes, command=command, safety=safety,
            capability=capability, battery=battery, line_follow=line_follow, nav=nav,
            robot_id=robot_id, station_config=(config.get('docking') or {}).get('station'),
            runtime_mode=(config.get('runtime') or {}).get('mode', 'hardware'))
        def mirror_mode(old: Mode, new: Mode) -> None:
            """D-380 fix: the snapshot's mode is every reader's mode.

            The e-stop path (SAF-001) transitions the machine without going
            through POST /mode, and before this listener the StateManager kept
            the previous mode through a stop and a release — the dashboard chip,
            /robot/state and the boot display's hand-over all said MANUAL while
            the machine held EMERGENCY. One listener, every path.
            """
            state.set_mode(RobotMode(new.value))
        modes.change_listeners.append(mirror_mode)
        modes.change_listeners.append(leave_docking)
        def drop_return_on_release(old: Mode, new: Mode) -> None:
            # D-502: a release is not a command. A return armed while latched is dropped.
            if old is Mode.EMERGENCY:
                docking.on_estop()
        modes.change_listeners.append(drop_return_on_release)
        def reflect_stop():
            state.set_estop(True)
            # SAF-001: every latch is an EMERGENCY, whoever set it. battery_policy and
            # battery_deep latched without it, and admin release refused ("not in EMERGENCY").
            ok, reason = modes.transition(Mode.EMERGENCY)
            if not ok:
                logging.getLogger(__name__).warning("e-stop latched but EMERGENCY refused: %s", reason)
        safety.estop_listeners.append(reflect_stop)
        safety.estop_listeners.append(docking.on_estop)
        safety.estop_listeners.append(swarm.on_estop)
        safety.estop_listeners.append(lambda: nav.cancel(source='safety_manager'))
        def stop_line_follow():
            status = line_follow.stop(reason="estop")
            command.clear_navigation()
            state.set_line_follow(status)
        safety.estop_listeners.append(stop_line_follow)
        def reset_traffic_policy():
            status = traffic_policy.reset("estop")
            state.set_traffic_policy(status)
        safety.estop_listeners.append(reset_traffic_policy)
        trip_lease = build_trip_lease(events, state, modes, safety, line_follow, command, nav)
        if station_docking is not None:
            station_docking.return_lease_probe = trip_lease.matches_nowait
        runtime_probe = HostRuntimeProbe(
            host_root=os.environ.get("ROSY_HOST_ROOT", "/"),
            data_path=waypoints_path.parent,
        )
        localization, loc_mission = wire_assist(events, lambda: identity.robot_id, nav=nav, line_follow=line_follow,
            command=command, state=state, modes=modes, swarm=swarm, docking=docking, safety=safety, traffic_policy=traffic_policy,
            mission_config=mission_config(config.get("localization_mission")))
        fleet_agent = FleetAgent(state, events, config, identity)
        fleet_agent.junction_signal_request = line_follow.junction_signal_request
        fleet_agent.junction_signal_answer = line_follow.junction_signal_answer
        line_follow.junction_signal_link_refused = lambda: fleet_agent.junction_signal_refused
        fleet_agent.start()
        bind_stuck_recovery(line_follow, safety=safety, calibration=calibration,
                            fleet_agent=fleet_agent, vision=vision)
        bind_motion_envelope(line_follow, safety=safety, traffic_policy=traffic_policy)
        fleet_loss = build_fleet_loss(config, events=events, fleet_agent=fleet_agent, nav=nav,
                                      safety=safety, localization=localization)

        return cls(config=config, identity=identity, profile=profile, capability=capability, fleet_agent=fleet_agent,
                   events=events, state=state, registry=registry, modes=modes,
                   command=command, safety=safety, advisory_feed=advisory_feed,
                   waypoints=waypoints, nav=nav,
                   line_follow=line_follow,
                   traffic_policy=traffic_policy,
                   signal_observer=signal_observer,
                   vision=vision,
                   readiness=readiness,
                   power=power, battery=battery, docking=docking, swarm=swarm,
                   runtime_probe=runtime_probe, host_files=HostFileExchange(), maps=MapSnapshotStore(),
                   audit=audit, calibration=calibration, trip_lease=trip_lease,
                   adapter_registry=adapter_registry, pilot_recording=PilotRecordingGuard(events=events),
                   dock_feed=dock_feed, station_docking=station_docking, localization=localization, loc_mission=loc_mission,
                   fleet_loss=fleet_loss)

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
            runtime_reasons=runtime_truth(self.config, self.state, self.readiness).reasons,
        )
        data["adapters"] = [item.id for item in self.adapter_registry.enabled()]
        return data
