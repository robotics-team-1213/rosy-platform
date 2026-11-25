"""core_features.localization.halt — stop autonomy when a D-395 robot leaves LOCALIZED.

D-395 §2: autonomous driving only from LOCALIZED. When the robot's state drops
(SUSPECT, CANDIDATES, UNKNOWN or `state_stale`), CORE folds every autonomous
run through the stop path it already has: swarm follow, docking, line-follow
OFF, the Nav2 cancel, then NAVIGATION -> IDLE so no nav twist reaches the
wheels. MANUAL (teleop) is not touched. Each stop path is a no-op when idle and
emits its own existing event; the `localization.state` event carries the reason.
"""

from __future__ import annotations

from typing import Callable, Optional

from core_common.protocol.localization import LocState
from core_common.protocol.schemas import NavigationState, RobotMode
from core_features.command.arbitration import Mode
from core_features.docking.model import DockPhase
from core_features.localization.assist import LocalizationAssist
from core_features.localization.mission import LocalizationMission, MissionConfig

SOURCE = "localization"


def _in_local_bay_approach(docking) -> bool:
    bay = getattr(docking, "_bay_phases", None)
    return bool(
        getattr(docking, "active", False)
        and bay is not None
        and bay.active()
        and bay._has_reference()
        and getattr(docking, "phase", None) in (DockPhase.ALIGNING, DockPhase.SETTLING)
    )


def autonomy_halt(*, nav, line_follow, command, state, modes, swarm, docking,
                  should_cancel_docking: Optional[Callable[[], bool]] = None) -> Callable[[], None]:
    def halt() -> None:
        swarm.cancel(source=SOURCE, reason=SOURCE)
        if should_cancel_docking is None or should_cancel_docking():
            docking.cancel()
        if line_follow.active:
            state.set_line_follow(line_follow.stop())
            command.clear_navigation()
        nav.cancel(source=SOURCE)
        if modes.mode is Mode.NAVIGATION:
            command.clear_navigation()
            ok, _ = modes.transition(Mode.IDLE, expect=Mode.NAVIGATION)
            if ok:
                state.set_mode(RobotMode.IDLE)
    return halt


def wire_assist(events, robot_id: Callable[[], str], *, nav, line_follow, command, state,
                modes, swarm, docking, safety, traffic_policy,
                mission_config: Optional[MissionConfig] = None) -> tuple[LocalizationAssist,
                                                                        LocalizationMission]:
    """CORE's composition: LOCALIZED cancels Nav2 (re-plan) and ends a P2-7 mission,
    leaving it halts autonomy, and the snapshot reads the status live."""
    mission: Optional[LocalizationMission] = None

    def on_localized() -> None:
        nav.cancel(source=SOURCE)
        if mission is not None:
            mission.localized()

    def should_cancel_docking() -> bool:
        if not _in_local_bay_approach(docking):
            return True
        st = assist.status()
        return not (st is not None and st.state is LocState.SUSPECT and st.reason == "fit_drop")

    assist = LocalizationAssist(
        events, robot_id=robot_id, on_localized=on_localized,
        on_lost=autonomy_halt(nav=nav, line_follow=line_follow, command=command, state=state,
                              modes=modes, swarm=swarm, docking=docking,
                              should_cancel_docking=should_cancel_docking))
    state.set_localization_provider(assist.status)
    line_follow.bind_pose_request(assist.pose_requests.open, assist.pose_requests.clear)  # D-546 5
    assist.on_pose_answered = line_follow.resume_after_pose
    docking.localization_ok = assist.autonomy_allowed

    def busy() -> Optional[str]:
        if line_follow.active:
            return "line follow is active"
        if docking.active:
            return "docking is active"
        if swarm.active:
            return "swarm follow is active"
        if nav.nav_state in (NavigationState.PLANNING, NavigationState.NAVIGATING):
            return "a navigation goal is active"
        return None

    mission = LocalizationMission(events, command=command, modes=modes, state=state, safety=safety,
                                  line_follow=line_follow, traffic_policy=traffic_policy,
                                  localization=assist, busy=busy, config=mission_config, navigation=nav)
    return assist, mission
