#!/usr/bin/env python3
"""Chunk Settlement, Grasp Holding Detection & Idle Auto-Park Lifecycle (`chunk_runner_settle.py`).

Single Responsibility:
  - Evaluate chunk completion settlement and grasp holding (`check_chunk_settled`).
  - Manage idle timeout auto-park and torque-OFF session termination (`check_runner_idle`).
"""
from __future__ import annotations

from pathlib import Path
import sys

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import cell_params as prm  # noqa: E402
from chunk_runner_commands import EMPTY_MARGIN  # noqa: E402
from chunk_runner_guards import SETTLE_TOL  # noqa: E402

SETTLE_S = 3.0
IDLE_PARK_S, IDLE_STOP_S, IDLE_RETRY_S = (prm.default(f"runner.idle_{k}_s") for k in ("park", "stop", "retry"))


def check_chunk_settled(runner, present: list[float], error: float, now: float, cr_attr) -> None:
    """Evaluate whether the active chunk has finished its queue and settled within tolerance or timeout."""
    if runner.chunk is None or runner.queue:
        return
    runner.settle_since = runner.settle_since if runner.settle_since is not None else now
    grasp = runner.chunk.startswith("grasp")
    gripper_still = runner.last_grip is not None and abs(present[5] - runner.last_grip) < 0.3
    runner.last_grip = present[5]
    settle_tol = cr_attr("SETTLE_TOL", SETTLE_TOL)
    settle_s = cr_attr("SETTLE_S", SETTLE_S)
    empty_margin = cr_attr("EMPTY_MARGIN", EMPTY_MARGIN)
    body_still = (
        runner.last_body is not None
        and max(abs(a - b) for a, b in zip(present[:5], runner.last_body)) < 0.08
        and error <= settle_tol + min(runner.pace_floor, 0.8)
    )
    runner.last_body = list(present[:5])
    aerial = (runner.chunk.startswith("goto ") or runner.chunk in ("above_pick", "above_place", "standby"))
    no_contact = not getattr(runner, "contact", False) and not (runner.fault or "").startswith("contact")
    if aerial and no_contact and not runner.jitter.get("shaking"):
        settled = error <= settle_tol * 1.15 or body_still or now - runner.settle_since >= settle_s
    else:
        settled = (error <= settle_tol or body_still) and not runner.jitter["shaking"]
    if (settled and (gripper_still or not grasp)) or now - runner.settle_since >= settle_s:
        fields = dict(
            command=f"run {runner.chunk}",
            ok=True,
            settled=settled,
            paced_ticks=runner.paced_ticks,
            peak_lag=round(runner.peak_lag, 2),
            over_ticks=runner.over_ticks,
            **({"damped_ticks": runner.damped_ticks} if runner.damped_ticks else {}),
            **({"sway": runner.sway_peak} if getattr(runner, "sway_peak", None) else {}),
            **({"speed_low": round(runner.speed_low, 2)} if getattr(runner, "speed_low", 1.0) < 1.0 else {}),
        )
        runner.sway_peak, runner.speed_low = {}, 1.0
        runner.paced_ticks, runner.pace_floor, runner.peak_lag, runner.over_ticks, runner.damped_ticks = (
            0,
            0.0,
            0.0,
            0,
            0,
        )
        if (runner.chunk == "park" or runner.chunk.endswith("; park")) and settled:
            runner.home_since = now
        backed_out = runner.chunk == "retreat" and settled
        if (runner.chunk == "park" or runner.chunk.endswith("; park") or backed_out) and (
            runner.fault or ""
        ).startswith("contact"):
            runner.fault = None
        if grasp:
            by_position = present[5] > runner.target[5] + empty_margin
            fields["holding"] = by_position
            health = runner.read_health()
            if health:
                runner.health = health
                current = abs(health["current_ma"][5])
                fields["gripper_current_ma"] = current
                threshold = runner.library.get("hold_current_ma")
                if threshold is not None:
                    fields["holding"] = by_position and current >= threshold
            runner.holding = bool(fields["holding"])
        elif runner.holding and (
            runner.chunk in ("lift_pick", "park", "goto above_place", "descend_place")
            or runner.chunk.startswith(("lift_pick", "goto above_place", "descend_place"))
        ):
            runner.holding = present[5] > runner.target[5] + empty_margin
            fields["holding"] = runner.holding
        runner.chunk, runner.last_grip, runner.last_body = None, None, None
        runner.report(**fields, present=present)
        stop_cmd = getattr(runner, "_stop_after_park", None)
        if stop_cmd:
            runner._stop_after_park = None
            runner._stopped = True
            runner.report(
                command=stop_cmd,
                ok=True,
                folded=settled,
                reason="folded home before stop, torque goes OFF",
                present=present,
            )


def check_runner_idle(runner, cr_attr) -> bool:
    """Fold home, then end the session (True), when no command has come for a while."""
    if runner.chunk is not None or runner.queue or runner.pending:
        return False
    quiet = runner.clock() - runner.last_input
    idle_retry_s = cr_attr("IDLE_RETRY_S", IDLE_RETRY_S)
    idle_park_s = cr_attr("IDLE_PARK_S", IDLE_PARK_S)
    idle_stop_s = cr_attr("IDLE_STOP_S", IDLE_STOP_S)
    if runner.home_since is None:
        if runner.idle_parks >= 2:
            if runner.idle_parks == 2:
                runner.idle_parks, runner.fault = (
                    3,
                    f"idle fold held twice ({runner.fault}): a person must free the arm",
                )
                runner.report(command="park", ok=False, error=runner.fault, person_needed=True)
            return False
        wait = (
            prm.get(runner.params, "runner.idle_retry_s", idle_retry_s)
            if runner.idle_parks
            else prm.get(runner.params, "runner.idle_park_s", idle_park_s)
        )
        if quiet >= wait:
            runner.last_input = runner.clock()
            runner.idle_parks += 1
            runner.command("park")
        return False
    pushed = (runner.fault or "").startswith("pushing at rest")
    if pushed or min(quiet, runner.clock() - runner.home_since) >= prm.get(
        runner.params, "runner.idle_stop_s", idle_stop_s
    ):
        runner.report(
            command="stop",
            ok=True,
            reason=f"{runner.fault if pushed else f'no command for {quiet:.0f} s'}; folded home, torque goes OFF",
        )
        return True
    return False
