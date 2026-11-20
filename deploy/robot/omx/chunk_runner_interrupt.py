#!/usr/bin/env python3
"""SIGINT/SIGTERM on chunk_runner: fold home and read the fold back before torque goes OFF, else hold torque ON.

An extended arm never loses torque on an interrupt (D-911, D-1048). The handler only records the signal; the run loop
asks `interrupt_tick` once per tick:
  - first signal: human hold already latched -> HOLD; body joints within SETTLE_TOL of home -> end (torque OFF);
    otherwise the runner's own `stop fold` (park_path from the present pose, every guard unchanged), bounded by
    INTERRUPT_PARK_S. Before the guard tracks (start alignment) nothing moves: folded ends, otherwise HOLD.
  - the park settled and the readback is within SETTLE_TOL of home -> end (torque OFF).
  - the park held (contact, strain, guard hold), raised, could not start, ended short of home or ran past
    INTERRUPT_PARK_S -> human hold (torque ON at the present pose): status `interrupt` with hold=true and
    person_needed=true (chunk-status.jsonl, stdout, stderr), live.json `interrupt: "hold"`. The process stays.
Later SIGINT/SIGTERM only repeat the HOLD report. Supervised recovery: a person supports the arm, then sends
`kill -USR2 <runner pid>` (OPERATOR_RELEASE): torque goes OFF where the arm is and the runner exits.
"""
from __future__ import annotations

import json
from pathlib import Path
import signal
import sys

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from chunk_runner_guards import SETTLE_TOL  # noqa: E402  D-1048's "within 3 units of home"

INTERRUPT_PARK_S = 120.0  # a park from full reach at PARK_SPEED with pacing holds takes well under a minute
OPERATOR_RELEASE = getattr(signal, "SIGUSR2", None)  # None on Windows test hosts


def install(signals: list) -> None:
    """Record SIGINT, SIGTERM and the operator release in `signals` instead of raising KeyboardInterrupt."""
    for number in (signal.SIGINT, signal.SIGTERM, OPERATOR_RELEASE):
        if number is not None:
            signal.signal(number, lambda signum, frame: signals.append(signum))


def _home(runner):
    home = runner.library.get("chunks", {}).get("home")
    return home[-1] if home else None


def folded(present, home) -> bool:
    return home is not None and max(abs(a - b) for a, b in zip(present[:5], home[:5])) <= SETTLE_TOL


def _say(runner, present, **fields) -> None:
    row = dict(command="interrupt", signal=runner._interrupt["signal"], **fields)
    runner.report(present=present, **row)
    print(json.dumps(row), file=sys.stderr, flush=True)


def _hold(runner, present, why: str) -> bool:
    if not runner.human_hold_latched:
        runner.hold(present, f"interrupt: {why}", human=True)
    runner._interrupt["phase"] = "hold"
    _say(runner, present, ok=False, hold=True, person_needed=True,
         error=f"HOLD: {why}; torque stays ON, a person must support the arm, then kill -USR2 the runner")
    return False


def _start(runner, *, may_move: bool) -> bool:
    runner._interrupt = {"signal": runner.signals[0], "phase": "park", "seen": len(runner.signals),
                         "deadline": runner.clock() + INTERRUPT_PARK_S}
    runner.pending.clear()
    present, home = runner.present(), _home(runner)
    if runner.human_hold_latched:
        return _hold(runner, present, "human hold already latched")
    if folded(present, home):
        _say(runner, present, ok=True, folded=True, reason="already folded, torque goes OFF")
        return True
    held = getattr(getattr(runner.robot, "motion", None), "held", None)
    hard_fault = runner.fault and not runner.fault.startswith("contact")
    if not may_move or home is None or held or hard_fault:
        why = ("the guard is not tracking yet" if not may_move else "no home chunk" if home is None
               else f"guard hold {held}" if held else f"fault {runner.fault}")
        return _hold(runner, present, f"cannot fold ({why})")
    if not getattr(runner, "_stop_after_park", None):  # a judge's stop fold already folding keeps going
        runner.command("stop fold")
    if runner.chunk != "park" or not getattr(runner, "_stop_after_park", None):
        return _hold(runner, present, f"the fold did not start ({runner.fault or 'refused'})")
    _say(runner, present, ok=True, folding=True, reason="folding home before torque goes OFF")
    return False


def interrupt_step(runner, *, may_move: bool = True) -> bool:
    """True: the fold is confirmed home (or the operator released a HOLD), so the run ends and torque goes OFF."""
    signals = getattr(runner, "signals", None)
    if not signals:
        return False
    state = getattr(runner, "_interrupt", None)
    if state is None:
        signals[:] = [s for s in signals if s != OPERATOR_RELEASE]  # the release means something only in a HOLD
        return bool(signals) and _start(runner, may_move=may_move)
    present = getattr(runner, "last_present", None) or runner.present()
    if len(signals) > state["seen"]:
        state["seen"] = len(signals)
        if state["phase"] == "hold" and OPERATOR_RELEASE in signals:
            _say(runner, present, ok=True, released=True,
                 reason="operator release (SIGUSR2): a person supports the arm, torque goes OFF where it is")
            return True
        if state["phase"] == "hold":
            _say(runner, present, ok=False, hold=True, person_needed=True, error="HOLD: still holding, torque ON")
    if state["phase"] == "hold":
        return False
    if getattr(runner, "_stopped", False):  # the park ended (settled or out of settle time)
        runner._stopped = False
        if folded(present, _home(runner)):
            _say(runner, present, ok=True, folded=True, reason="folded home, torque goes OFF")
            return True
        return _hold(runner, present, "the fold ended short of home")
    if runner.chunk != "park":  # a contact or strain hold stopped the park
        return _hold(runner, present, f"the fold stopped ({runner.fault})")
    if runner.clock() > state["deadline"]:
        return _hold(runner, present, f"the fold did not finish within {INTERRUPT_PARK_S:.0f} s")
    return False


def interrupt_tick(runner, label: str, tick_or_report) -> bool:
    """One control tick; once interrupted, a raising tick holds instead of ending the run (no torque OFF)."""
    if getattr(runner, "signals", None) and getattr(runner, "_interrupt", None) is None and interrupt_step(runner):
        return True
    state = getattr(runner, "_interrupt", None)
    if state is None:
        tick_or_report(runner, label)
        return False
    try:
        runner.tick()
    except Exception as error:
        if state["phase"] != "hold":
            return _hold(runner, runner.present(), f"{type(error).__name__}: {error}"[:500])
        if not state.get("tick_error"):  # keep commanding the held pose; say once that a tick failed
            state["tick_error"] = True
            print(json.dumps({"command": "interrupt", "hold": True, "tick_error": str(error)[:500]}),
                  file=sys.stderr, flush=True)
    return interrupt_step(runner)
