"""core_features.localization.halt — stop autonomy when a D-395 robot leaves LOCALIZED.

D-395 §2: autonomous driving only from LOCALIZED. When the robot's state drops
(SUSPECT, CANDIDATES, UNKNOWN or `state_stale`), CORE folds every autonomous
run through the stop path it already has: swarm follow, docking, line-follow
OFF, the Nav2 cancel, then NAVIGATION -> IDLE so no nav twist reaches the
wheels. MANUAL (teleop) is not touched. Each stop path is a no-op when idle and
emits its own existing event; the `localization.state` event carries the reason.
"""

from __future__ import annotations

from typing import Callable

from core_common.protocol.schemas import RobotMode
from core_features.command.arbitration import Mode
from core_features.localization.assist import LocalizationAssist

SOURCE = "localization"


def autonomy_halt(*, nav, line_follow, command, state, modes, swarm, docking) -> Callable[[], None]:
    def halt() -> None:
        swarm.cancel(source=SOURCE, reason=SOURCE)
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
                modes, swarm, docking) -> LocalizationAssist:
    """CORE's composition: LOCALIZED cancels Nav2 (re-plan), leaving it halts autonomy,
    and the snapshot reads the status live."""
    assist = LocalizationAssist(
        events, robot_id=robot_id,
        on_localized=lambda: nav.cancel(source=SOURCE),
        on_lost=autonomy_halt(nav=nav, line_follow=line_follow, command=command, state=state,
                              modes=modes, swarm=swarm, docking=docking))
    state.set_localization_provider(assist.status)
    docking.localization_ok = assist.autonomy_allowed
    return assist
