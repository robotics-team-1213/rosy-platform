"""runner.idle_open_grip: the first idle fold opens an empty gripper in place, then parks home (2026-11-27 user, arm_a)."""
from __future__ import annotations

import math
import os

import cell_params as prm
from chunk_runner_commands import EMPTY_MARGIN
from chunk_runner_guards import library_gripper_closed

IDLE_OPEN_SETTLE_S = 1.5  # time for the jaws to open in place before the idle fold rises
ENV = "ROSY_IDLE_OPEN_GRIP"  # per-arm switch: the A/B session wrappers set it; arm S shares their params file


def open_grip(params) -> float:
    """The params file's runner.idle_open_grip, else ENV within the param's range, else 0 (off)."""
    if value := prm.get(params, "runner.idle_open_grip"):
        return float(value)
    try:
        value = float(os.environ.get(ENV) or 0.0)
    except ValueError:
        return 0.0
    _dflt, _unit, low, high = prm.DEFAULTS["runner.idle_open_grip"]
    return value if math.isfinite(value) and low <= value <= high else 0.0


def idle_fold(runner) -> None:
    """The idle fold: park, or open the jaws in place first and let idle_open_pending park after they open."""
    open_to = open_grip(runner.params)
    # Open only on the first idle fold of a gripper measured shut on nothing: a held box would drop where it stands,
    # and runner.holding is bookkeeping, so the live jaw must read closed too (D-430 review 2026-11-27).
    closed, jaw = library_gripper_closed(runner.library), (getattr(runner, "last_present", None) or [None] * 6)[5]
    if not (open_to and runner.idle_parks == 1 and not runner.holding and not runner.fault
            and runner.target is not None and jaw is not None
            and max(jaw, runner.target[5]) <= closed + EMPTY_MARGIN and closed + EMPTY_MARGIN < open_to - 1.0):
        runner.command("park")
        return
    runner.command(f"grip {open_to}")
    if runner.target[5] < open_to - 1.0:  # the grip was refused: fold as before
        runner.command("park")
        return
    runner._idle_open_at = runner.clock()


def idle_open_pending(runner) -> bool:
    """While jaws opened by idle_fold settle: wait, then rise and fold home along park_path."""
    opened_at = getattr(runner, "_idle_open_at", None)
    if opened_at is None:
        return False
    if runner.clock() - opened_at >= IDLE_OPEN_SETTLE_S:
        runner._idle_open_at, runner.last_input = None, runner.clock()
        runner.command("park")
    return True
