"""CORE docking/swarm composition; managers and final command authority keep their owners."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable, Optional

from core_common.protocol.schemas import RobotMode
from core_features.command.arbitration import Mode
from core_features.command.manager import Twist
from core_features.docking.agent import DockAgent
from core_features.docking.database import DockDatabase, DockError, DockInstance, DockType
from core_features.docking.detector import select_detector
from core_features.docking.feed import DockObservationFeed
from core_features.docking.manager import DockingConfig, DockingManager
from core_features.swarm import SwarmManager


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


def build_docking_and_swarm(*, simulation_docking, data_path: Path, events, state, modes,
                            command, safety, capability, battery, line_follow, nav,
                            robot_id: str) -> tuple[
                                DockingManager, SwarmManager, DockObservationFeed, Callable[[Mode, Mode], None]]:
    """Compose the shared Nav2 ownership and return the unchanged mode-exit listener."""
    dock_feed = DockObservationFeed()

    def map_pose():
        pose = state.snapshot().pose
        return (pose.x, pose.y, pose.yaw)

    docking = DockingManager(
        database=(_seeded_dock_database(simulation_docking)
                  if simulation_docking is not None
                  else DockDatabase(data_path / "docks.json")),
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
        release_mode=lambda: release_docking_mode(),
    )

    def take_docking_mode():
        """Docking drives from start to finish in DOCKING (the docking slot
        only reaches the wheels there). Checked before the manager changes
        anything: a refusal leaves the dock state as it was. The table has
        no NAVIGATION -> DOCKING edge, so NAVIGATION goes through IDLE;
        MANUAL (3) outranks DOCKING (4) and is refused."""
        previous = modes.mode
        if previous is Mode.DOCKING:
            return
        if previous not in (Mode.IDLE, Mode.NAVIGATION):
            raise DockError("MODE_CONFLICT",
                            f"invalid transition {previous.value}->DOCKING")
        # Nav2 and a swarm session are cancelled first: a live Nav2 goal
        # would otherwise keep publishing nav_cmd_vel and preempt staging.
        nav.cancel(source="docking")
        # Each step commits only from the mode it expects: an operator's
        # MANUAL landing after the check above (during the cancel) must
        # refuse the take, not be ridden over via MANUAL -> IDLE -> DOCKING.
        if previous is Mode.NAVIGATION:
            ok, reason = modes.transition(Mode.IDLE, expect=Mode.NAVIGATION)
            if not ok:
                raise DockError("MODE_CONFLICT", reason)
        ok, reason = modes.transition(Mode.DOCKING, expect=Mode.IDLE)
        if not ok:
            raise DockError("MODE_CONFLICT", reason)
        command.clear_docking()
        state.set_mode(RobotMode.DOCKING)
        events.publish("mode.changed", source="docking",
                       data={"from": previous.value, "to": Mode.DOCKING.value,
                             "by": "docking"})

    def release_docking_mode():
        """IDLE again once docking no longer moves the robot (docked,
        undocked, failed or cancelled). The manager calls this under its
        lock, in the same critical section as the terminal state change, so
        nobody sees the run over while the mode is still DOCKING — and an
        undock cannot slip in between and be cancelled by `leave_docking`.
        A no-op when the mode already left DOCKING (an API mode change,
        e-stop): that exit is what cancelled the run in the first place."""
        ok, _ = modes.transition(Mode.IDLE, expect=Mode.DOCKING)
        if ok:
            command.clear_docking()
            state.set_mode(RobotMode.IDLE)
    swarm = SwarmManager(
        events, state, nav, safety, capability, robot_id=robot_id,
        # Nav2 를 두고 다투는 것은 DOCKING/UNDOCKING 뿐이다. DOCKED·CHARGING 은
        # 주차 상태이고, DOCK_FAILED 는 설계상 종착이라 그것으로 막으면
        # 도킹 실패 한 번이 군집을 영구히 비활성화한다.
        # 락 없는 읽기다 (`DockingManager.active`) — follow() 가 swarm 락을
        # 쥔 채 묻는다.
        docking_active_provider=lambda: docking.active,
        map_id_provider=lambda: state.map_id,
        # D-559 trail: own pose, the NAVIGATION slot and the D-422 judge of line follow.
        pose_provider=state.pose_sample, obstacle_gap=line_follow.obstacle_gap,
        odom_provider=state.odom_sample,  # D-581 Fleet-anchored trail steers in odom
        twist_sink=lambda t: command.set_nav_twist(None if t is None else Twist(*t)),
    )
    nav.session_closed_listener = swarm.on_navigation_session_closed
    nav.docking_active_provider = lambda: (
        modes.mode is Mode.DOCKING or docking.active)

    def leave_docking(old, new):
        """Every exit from DOCKING stops the docking run first — API, line
        follow, e-stop or docking's own release. The docking slot only
        reaches the wheels in DOCKING, and nothing else may keep driving it."""
        if old is not Mode.DOCKING:
            return
        try:
            if new is Mode.EMERGENCY:
                docking.abort("emergency stop during docking")
            else:
                docking.cancel()
        except Exception:
            logging.getLogger("core.services").exception("docking stop on mode exit failed")
        command.clear_docking()
    return docking, swarm, dock_feed, leave_docking
