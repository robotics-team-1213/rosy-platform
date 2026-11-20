#!/usr/bin/env python3
"""SIGINT/SIGTERM on chunk_runner: fold home and read the fold back before torque goes OFF, else hold torque ON.

An extended arm never loses torque on an interrupt (D-911, D-1048). The handler only records the signal; the run loop
asks `interrupt_tick` once per tick:
  - first signal: human hold already latched -> HOLD; body joints within SETTLE_TOL of home -> end (torque OFF);
    otherwise the runner's own `stop fold` (park_path from the present pose, every guard unchanged), bounded by
    INTERRUPT_PARK_S. Before the guard tracks (start alignment) nothing moves: folded ends, otherwise HOLD.
  - the park ended settled AND the readback is within SETTLE_TOL of home -> end (torque OFF).
  - the park held (contact, strain, guard hold), raised, could not start, ended unsettled or short of home, ran past
    INTERRUPT_PARK_S, or the pose could not be read -> human hold (torque ON at the last known pose): status
    `interrupt` hold=true person_needed=true (chunk-status.jsonl, stdout, stderr), `hold.json` beside the FIFO
    (with this pid, for record_session), live.json `interrupt: "hold"`. The process stays. A failed status write
    goes to stderr and the hold stays.
  - the guard stopped itself (NativeJointMotion.send failed: it already tried torque OFF): nothing is sent through it
    again; Torque_Enable is read back once a second and each change reported: all 0 -> GUARD_STOPPED, the run ends so
    record_session takes its usual torque check and incident path; some 0 -> PARTIAL_GUARD_STOP; all 1 or unreadable
    -> HOLD. The last two wait for a person.
  - in a HOLD the loop only sends the held pose (no chunk, health or contact logic); a FIFO `human-hold` while
    interrupted is dropped (the interrupt already holds).
Later SIGINT/SIGTERM only repeat the HOLD report. Supervised recovery: a person supports the arm, then sends
`kill -USR2 <runner pid>` (OPERATOR_RELEASE): torque goes OFF where the arm is and the runner exits. Only a release
received after the HOLD began counts; one sent earlier is ignored and reported.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import sys
import time

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from chunk_runner_guards import SETTLE_TOL  # noqa: E402  D-1048's "within 3 units of home"
from chunk_runner_guards import NAMES  # noqa: E402

INTERRUPT_PARK_S = 120.0  # a park from full reach at PARK_SPEED with pacing holds takes well under a minute
OPERATOR_RELEASE = getattr(signal, "SIGUSR2", None)  # None on Windows test hosts


def install(signals: list) -> None:
    """Record SIGINT, SIGTERM and the operator release in `signals` instead of raising KeyboardInterrupt."""
    for number in (signal.SIGINT, signal.SIGTERM, OPERATOR_RELEASE):
        if number is not None:
            signal.signal(number, lambda signum, frame: signals.append(signum))


def _stderr(row: dict) -> None:
    try:
        print(json.dumps(row, default=str), file=sys.stderr, flush=True)
    except Exception:  # noqa: BLE001  a closed stderr must not end the hold either
        pass


def _home(runner):
    home = runner.library.get("chunks", {}).get("home")
    return home[-1] if home else None


def folded(present, home) -> bool:
    return home is not None and present is not None and max(
        abs(a - b) for a, b in zip(present[:5], home[:5])) <= SETTLE_TOL


def _pose(runner):
    """(pose, read): a fresh reading, else the last known pose (never treated as folded)."""
    try:
        return runner.present(), True
    except Exception as error:  # noqa: BLE001
        _stderr({"command": "interrupt", "pose_read_failed": f"{type(error).__name__}: {error}"[:500]})
        return list(getattr(runner, "last_present", None) or runner.target), False


def _say(runner, present, **fields) -> None:
    row = dict(command="interrupt", signal=runner._interrupt["signal"], **fields)
    try:
        runner.report(present=present, **row)
    except Exception as error:  # noqa: BLE001  a full disk must not turn the hold into a torque OFF
        row["status_write_failed"] = f"{type(error).__name__}: {error}"[:300]
    _stderr(row)


def _write_hold(runner, row: dict) -> None:
    path = getattr(runner, "hold_file", None)
    if path is None:
        return
    try:
        tmp = Path(path).with_suffix(".tmp")
        tmp.write_text(json.dumps({"pid": os.getpid(), "t": time.time(), **row}, default=str))
        os.replace(tmp, path)
    except OSError as error:
        _stderr({"command": "interrupt", "hold_file_failed": str(error)[:300]})


def _hold(runner, present, why: str, label: str = "HOLD") -> bool:
    state = runner._interrupt
    if not runner.human_hold_latched:
        runner.hold(present, f"interrupt: {why}", human=True)
    if state["phase"] != "hold":
        state["phase"], state["release_from"] = "hold", len(runner.signals)
        early = runner.signals.count(OPERATOR_RELEASE) if OPERATOR_RELEASE is not None else 0
        if early:
            _stderr({"command": "interrupt", "ignored_release": early, "reason": "SIGUSR2 before the HOLD"})
    error = f"{label}: {why}; a person must support the arm, then kill -USR2 the runner"
    _write_hold(runner, {"hold": True, "error": error, "label": label})
    _say(runner, present, ok=False, hold=True, person_needed=True, error=error, **({"partial_guard_stop": True}
                                                                                   if label != "HOLD" else {}))
    return False


def _guard_stopped(runner):
    """None while the guard runs; else the Torque_Enable readback after its own stop (or the read error)."""
    robot = runner.robot
    if not getattr(getattr(robot, "motion", None), "failed", False):
        return None
    try:
        return dict(robot.bus.sync_read("Torque_Enable", normalize=False, num_retry=2))
    except Exception as error:  # noqa: BLE001
        return {"error": f"{type(error).__name__}: {error}"[:300]}


def _guard_verdict(runner, torque: dict, cause: str) -> bool:
    """The guard has stopped: never send through it again. Report each change of the torque readback once:
    all 0 -> GUARD_STOPPED, the run ends (torque is already OFF); some 0 -> PARTIAL_GUARD_STOP; all 1 or unreadable ->
    HOLD. Both wait for a person (SIGUSR2)."""
    state = runner._interrupt
    values = [] if "error" in torque else list(torque.values())
    kind = ("off" if values and not any(values) else "partial" if values and not all(values) else
            "on" if values else "unknown")
    if state.get("guard_kind") == kind:
        return False
    state["guard_kind"] = kind
    present = list(getattr(runner, "last_present", None) or runner.target)  # no bus read: the guard has failed
    if kind == "off":
        _say(runner, present, ok=False, guard_stopped=True, torque=torque, error=f"GUARD_STOPPED torque off: {cause}"[:500])
        return True
    label = "PARTIAL_GUARD_STOP" if kind == "partial" else "HOLD"
    return _hold(runner, present, f"guard stopped, torque reads {torque}: {cause}"[:500], label=label)


def _hold_tick(runner) -> bool:
    """In a HOLD: only the held pose goes to the guard; once the guard has failed, nothing is sent, torque is read."""
    state = runner._interrupt
    torque, cause = _guard_stopped(runner), state.get("guard_cause", "guard stopped")
    if torque is None:
        try:
            runner.robot.send_action(dict(zip(NAMES, runner.target)))
            if runner._human_hold_ack_pending:
                runner._human_hold_ack_pending, runner.torque_hold_commanded = False, True
            try:
                runner.present()  # refresh last_present for live.json; a failed read keeps the hold
            except Exception:  # noqa: BLE001
                pass
        except Exception as error:  # noqa: BLE001
            torque, cause = _guard_stopped(runner), f"{type(error).__name__}: {error}"
            state["guard_cause"] = cause
            if torque is None and not state.get("tick_error"):
                state["tick_error"] = True
                _stderr({"command": "interrupt", "hold": True, "tick_error": cause[:500]})
    elif runner.clock() - state.get("guard_read_at", -1e9) < 1.0:
        return interrupt_step(runner)  # the readback once a second, not every tick
    if torque is not None:
        state["guard_read_at"] = runner.clock()
        if _guard_verdict(runner, torque, cause):
            return True
    return interrupt_step(runner)


def _start(runner, *, may_move: bool) -> bool:
    runner._interrupt = {"signal": runner.signals[0], "phase": "park", "seen": len(runner.signals),
                         "deadline": runner.clock() + INTERRUPT_PARK_S}
    runner.pending.clear()
    (present, read), home = _pose(runner), _home(runner)
    if runner.human_hold_latched:
        return _hold(runner, present, "human hold already latched")
    if not read:
        return _hold(runner, present, "the pose could not be read")
    if folded(present, home):
        _say(runner, present, ok=True, folded=True, reason="already folded, torque goes OFF")
        return True
    held = getattr(getattr(runner.robot, "motion", None), "held", None)
    hard_fault = runner.fault and not runner.fault.startswith("contact")
    if not may_move or home is None or held or hard_fault:
        why = ("the guard is not tracking yet" if not may_move else "no home chunk" if home is None
               else f"guard hold {held}" if held else f"fault {runner.fault}")
        return _hold(runner, present, f"cannot fold ({why})")
    runner._park_settled = False
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
        if OPERATOR_RELEASE in signals:  # the release means something only in a HOLD
            _stderr({"command": "interrupt", "ignored_release": signals.count(OPERATOR_RELEASE),
                     "reason": "SIGUSR2 without a HOLD"})
            signals[:] = [s for s in signals if s != OPERATOR_RELEASE]
        return bool(signals) and _start(runner, may_move=may_move)
    if len(signals) > state["seen"]:
        state["seen"] = len(signals)
        if state["phase"] == "hold":
            present, _ = _pose(runner)
            if OPERATOR_RELEASE in signals[state["release_from"]:]:
                _say(runner, present, ok=True, released=True,
                     reason="operator release (SIGUSR2): a person supports the arm, torque goes OFF where it is")
                return True
            _say(runner, present, ok=False, hold=True, person_needed=True, error="HOLD: still holding, torque ON")
    if state["phase"] == "hold":
        return False
    if getattr(runner, "_stopped", False):  # the park ended (settled or out of settle time)
        runner._stopped = False
        present, read = _pose(runner)
        if read and getattr(runner, "_park_settled", False) and folded(present, _home(runner)):
            _say(runner, present, ok=True, folded=True, reason="folded home and settled, torque goes OFF")
            return True
        return _hold(runner, present, "the fold ended unsettled or short of home" if read else
                     "the pose could not be read after the fold")
    if runner.chunk != "park":  # a contact or strain hold stopped the park
        return _hold(runner, _pose(runner)[0], f"the fold stopped ({runner.fault})")
    if runner.clock() > state["deadline"]:
        return _hold(runner, _pose(runner)[0], f"the fold did not finish within {INTERRUPT_PARK_S:.0f} s")
    return False


def interrupt_tick(runner, label: str, tick_or_report) -> bool:
    """One control tick; once interrupted, a raising tick holds (or reports the guard's own stop), never torque OFF."""
    if getattr(runner, "signals", None) and getattr(runner, "_interrupt", None) is None and interrupt_step(runner):
        return True
    state = getattr(runner, "_interrupt", None)
    if state is None:
        tick_or_report(runner, label)
        return False
    if state["phase"] == "hold":
        return _hold_tick(runner)
    try:
        runner.tick()
    except Exception as error:  # noqa: BLE001
        cause = f"{type(error).__name__}: {error}"
        torque = _guard_stopped(runner)
        if torque is not None:
            state["guard_cause"], state["guard_read_at"] = cause, runner.clock()
            return _guard_verdict(runner, torque, cause)
        return _hold(runner, _pose(runner)[0], cause[:500])
    return interrupt_step(runner)
