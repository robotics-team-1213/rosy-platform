#!/usr/bin/env python3
"""SIGINT/SIGTERM/SIGHUP on chunk_runner: fold home and verify fold readback before torque goes OFF, else hold torque ON.

Extended arms never lose torque on an interrupt (D-911, D-1048):
  - First signal: human hold already latched -> HOLD; else stop in place, verify VERIFY_TICKS still readings in
    SETTLE_TOL of home -> torque OFF, else run `stop fold` (park_path bounded by INTERRUPT_PARK_S).
  - Guard-stopped recovery: read Torque_Enable on all 6 motors at 1 Hz; end only when every motor reads 0.
  - Exceptions, stalled folds, unconfirmed grip releases, or pose/health read failures latch HOLD (`hold.json` +
    torque ON) and remain powered until an operator supports the arm and sends `kill -USR2 <pid>`.
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

from chunk_runner_guards import MOTORS, NAMES, SETTLE_TOL, safe_stderr as _stderr, shed_interrupt_hold  # noqa: E402  D-1048's "within 3 units of home"
from chunk_policy_playback import halt_policy_gate, send_hold_action  # noqa: E402
from guarded_native_effort import check_hold_health  # noqa: E402

INTERRUPT_PARK_S = 120.0  # a park from full reach at PARK_SPEED with pacing holds takes well under a minute
VERIFY_TICKS, VERIFY_S = 5, 2.0  # "already folded" needs this many still readings in a row, within this time
STILL_UNITS = 0.08  # body motion per tick that counts as still (chunk_runner_settle's body_still)
OPERATOR_RELEASE = getattr(signal, "SIGUSR2", None)  # None on Windows test hosts
BLOCKED_DURING_CLOSE = tuple(getattr(signal, n) for n in ("SIGINT", "SIGTERM", "SIGHUP") if hasattr(signal, n))


def install(signals: list) -> None:
    """Record SIGINT, SIGTERM, SIGHUP and the operator release in `signals` instead of raising KeyboardInterrupt."""
    for number in (*BLOCKED_DURING_CLOSE, OPERATOR_RELEASE):
        if number is not None:
            signal.signal(number, lambda signum, frame: signals.append(signum))


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
    row = dict(command="interrupt", signal=runner._interrupt.get("signal"), **fields)
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


def _approve(runner, reason: str) -> bool:
    """The only ways this run may end in torque OFF after an interrupt; `final_gate` reads it last."""
    runner._off_approved = reason
    return True


def _hold(runner, present, why: str, label: str = "HOLD") -> bool:
    state = runner._interrupt
    if not runner.human_hold_latched:
        runner.hold(present, f"interrupt: {why}", human=True)
    if state["phase"] != "hold":
        sigs = getattr(runner, "signals", None) or ()
        state["phase"], state["release_from"] = "hold", len(sigs)
        early = sigs.count(OPERATOR_RELEASE) if OPERATOR_RELEASE is not None else 0
        if early:
            _stderr({"command": "interrupt", "ignored_release": early, "reason": "SIGUSR2 before the HOLD"})
    error = f"{label}: {why}; a person must support the arm, then kill -USR2 the runner"
    _write_hold(runner, {"hold": True, "error": error, "label": label})
    _say(runner, present, ok=False, hold=True, person_needed=True, error=error, **({"partial_guard_stop": True} if label != "HOLD" else {}))
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
    """Approve exit only when all 6 motors explicitly read torque 0."""
    runner.torque_hold_commanded, runner._human_hold_ack_pending, runner._human_hold_acked_req = False, False, None
    state = runner._interrupt
    pairs = [[torque[k] for k in (m, n) if k in torque] for n, m in zip(NAMES, MOTORS)] if isinstance(torque, dict) and "error" not in torque else []
    vals = [p[0] for p in pairs if p and all(type(v) is int and v in (0, 1) for v in p) and len(set(p)) == 1]
    all_read = len(vals) == len(NAMES)
    kind = "off" if all_read and all(v == 0 for v in vals) else "partial" if any(v == 0 for v in vals) else "on" if all_read else "unknown"
    if state.get("guard_kind") == kind:
        return False
    state["guard_kind"] = kind
    present = list(getattr(runner, "last_present", None) or runner.target)  # no bus read: the guard has failed
    if kind == "off":
        _say(runner, present, ok=False, guard_stopped=True, torque=torque, error=f"GUARD_STOPPED torque off: {cause}"[:500])
        return _approve(runner, "guard stopped, every motor reads torque 0")
    label = "PARTIAL_GUARD_STOP" if kind == "partial" else "HOLD"
    return _hold(runner, present, f"guard stopped, torque reads {torque}: {cause}"[:500], label=label)


def _hold_tick(runner) -> bool:
    """In a HOLD: only the held pose goes to the guard; once the guard has failed, nothing is sent, torque is read."""
    state = runner._interrupt
    runner.ticks += 1  # the run loop paces live.json by ticks: a HOLD keeps publishing
    torque, cause = _guard_stopped(runner), state.get("guard_cause", "guard stopped")
    if torque is None:
        try:
            sent = send_hold_action(runner.robot, runner.target)
            try:
                present, fresh = runner.present(), True  # refresh last_present for live.json; a failed read keeps the hold
            except Exception:  # noqa: BLE001
                present, fresh = getattr(runner, "last_present", None) or runner.target, False
            shed_interrupt_hold(runner, sent, present, fresh=fresh)
            if runner._human_hold_ack_pending:
                runner._human_hold_ack_pending, runner.torque_hold_commanded, runner._human_hold_acked_req = False, True, getattr(runner, "_human_hold_req", None)
            if runner.ticks % max(1, round(getattr(runner, "fps", 30))) == 0:
                check_hold_health(runner, MOTORS)
        except Exception as error:  # noqa: BLE001
            runner.torque_hold_commanded, runner._human_hold_ack_pending, runner._human_hold_acked_req = False, False, None
            torque, cause = _guard_stopped(runner), f"{type(error).__name__}: {error}"
            state["guard_cause"], runner.shed_clear = cause, None
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


def _new_state(runner, may_move: bool) -> dict:
    sigs = getattr(runner, "signals", None) or ()
    runner._interrupt = {"signal": sigs[0] if sigs else None, "phase": "verify", "seen": len(sigs),
                         "may_move": may_move, "since": runner.clock(), "still": 0, "last": None,
                         "deadline": runner.clock() + INTERRUPT_PARK_S}
    return runner._interrupt


def _start(runner, *, may_move: bool) -> bool:
    """Stop where the arm is (drop the chunk and its frames), then verify: the arm ends folded only once VERIFY_TICKS
    readings in a row are still and within SETTLE_TOL of home; otherwise the existing stop fold."""
    _new_state(runner, may_move)
    runner.pending.clear()
    present, read = _pose(runner)
    if runner.human_hold_latched or getattr(runner, "_fifo_hold_seen", False):
        return _hold(runner, present, "human hold already latched" if runner.human_hold_latched else "human hold requested via FIFO")
    if not read:
        return _hold(runner, present, "the pose could not be read")
    gated = halt_policy_gate(runner)
    saved, runner._committed_grip = getattr(runner, "_committed_grip", None), None
    if saved is not None and runner.target is not None and len(runner.target) >= 6:
        runner.target[5], runner.holding = saved
    if gated or runner.chunk is not None or runner.queue or runner.jog_path or getattr(runner, "_stop_after_park", None):
        runner.queue, runner.chunk, runner.jog_path, runner._stop_after_park = [], None, [], None
        runner.target = list(present[:5]) + [runner.target[5]]  # hold here with torque on while the arm settles
    _say(runner, present, ok=True, verifying=True, reason="stopped at the present pose, verifying before fold or OFF")
    return False


def _verify(runner, state) -> bool:
    present, read = _pose(runner)
    if runner.human_hold_latched or getattr(runner, "_fifo_hold_seen", False) or not read:
        return _hold(runner, present, "human hold latched during verify" if runner.human_hold_latched else ("human hold requested via FIFO" if getattr(runner, "_fifo_hold_seen", False) else "the pose could not be read"))
    last, state["last"] = state["last"], list(present[:5])
    still = last is not None and max(abs(a - b) for a, b in zip(present[:5], last)) < STILL_UNITS
    state["still"] = state["still"] + 1 if still else 0
    home = _home(runner)
    if state["still"] >= VERIFY_TICKS:
        if folded(present, home) and getattr(runner, "_release_until", None) is None:
            _say(runner, present, ok=True, folded=True, still_ticks=state["still"],
                 reason="already folded and still, torque goes OFF")
            return _approve(runner, "folded and still")
        return _fold(runner, present)
    if runner.clock() - state["since"] > VERIFY_S:
        return (_hold(runner, present, "near home but never still") if folded(present, home) and getattr(runner, "_release_until", None) is None
                else _fold(runner, present))
    return False


def _fold(runner, present) -> bool:
    state, home = runner._interrupt, _home(runner)
    held = getattr(getattr(runner.robot, "motion", None), "held", None)
    hard_fault = bool(runner.fault and (not runner.fault.startswith("contact") or "overload-hold" in runner.fault))
    if not state["may_move"] or home is None or held or hard_fault:
        why = ("the guard is not tracking yet" if not state["may_move"] else "no home chunk" if home is None
               else f"guard hold {held}" if held else f"fault {runner.fault}")
        return _hold(runner, present, f"cannot fold ({why})")
    state["phase"], state["deadline"], runner._park_settled = "park", runner.clock() + INTERRUPT_PARK_S, False
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
            latched = bool(getattr(runner, "human_hold_latched", False))
            if latched and OPERATOR_RELEASE in signals[getattr(runner, "_human_hold_release_from", 0):]:
                present, _ = _pose(runner)
                row = dict(command="human-hold", ok=True, released=True,
                           reason="operator release (SIGUSR2): a person supports the arm, torque goes OFF where it is")
                try:
                    runner.report(present=present, **row)
                except Exception as error:  # noqa: BLE001
                    row["status_write_failed"] = f"{type(error).__name__}: {error}"[:300]
                _stderr(row)
                return _approve(runner, "operator release (SIGUSR2)")
            why = "SIGUSR2 before the HOLD" if latched else "SIGUSR2 without a HOLD"
            _stderr({"command": "interrupt", "ignored_release": signals.count(OPERATOR_RELEASE), "reason": why})
            signals[:] = [s for s in signals if s != OPERATOR_RELEASE]
            if latched:
                runner._human_hold_release_from = len(signals)
        return bool(signals) and _start(runner, may_move=may_move)
    if len(signals) > state["seen"]:
        state["seen"] = len(signals)
        if state["phase"] == "hold":
            present, _ = _pose(runner)
            if OPERATOR_RELEASE in signals[state["release_from"]:]:
                _say(runner, present, ok=True, released=True,
                     reason="operator release (SIGUSR2): a person supports the arm, torque goes OFF where it is")
                return _approve(runner, "operator release (SIGUSR2)")
            _say(runner, present, ok=False, hold=True, person_needed=True, error="HOLD: still holding, torque ON")
    if state["phase"] == "hold":
        return False
    if state["phase"] == "verify":
        return _verify(runner, state)
    if getattr(runner, "_fifo_hold_seen", False):
        return _hold(runner, _pose(runner)[0], "human hold requested via FIFO")
    if getattr(runner, "_stopped", False):  # the park ended (settled or out of settle time)
        runner._stopped = False
        present, read = _pose(runner)
        if read and getattr(runner, "_park_settled", False) and folded(present, _home(runner)) and getattr(runner, "_release_until", None) is None:
            _say(runner, present, ok=True, folded=True, reason="folded home and settled, torque goes OFF")
            return _approve(runner, "park settled and home")
        return _hold(runner, present, "the fold ended unsettled or short of home" if read else "the pose could not be read after the fold")
    if runner.chunk != "park":  # a contact or strain hold stopped the park
        return _hold(runner, _pose(runner)[0], f"the fold stopped ({runner.fault})")
    if runner.clock() > state["deadline"]:
        return _hold(runner, _pose(runner)[0], f"the fold did not finish within {INTERRUPT_PARK_S:.0f} s")
    return False


def _interrupt_tick(runner, label: str, tick_or_report) -> bool:
    if getattr(runner, "signals", None) and getattr(runner, "_interrupt", None) is None and interrupt_step(runner):
        return True
    state = getattr(runner, "_interrupt", None)
    if state is None:
        if getattr(runner, "_fifo_hold_seen", False) and not runner.human_hold_latched:
            hold_cmd, runner._fifo_hold_seen = runner._fifo_hold_seen if isinstance(runner._fifo_hold_seen, str) else "human-hold", False
            runner.command(hold_cmd)
        tick_or_report(runner, label)
        return False
    if state["phase"] != "hold" and getattr(runner, "_fifo_hold_seen", False):
        _hold(runner, _pose(runner)[0], "human hold requested via FIFO")
    if state["phase"] == "hold":
        return _hold_tick(runner)
    runner.tick()
    return interrupt_step(runner)


def interrupt_tick(runner, label: str, tick_or_report) -> bool:
    """One control tick. With an interrupt, latched hold, or failed guard, holds or checks 6-motor torque OFF."""
    try:
        return _interrupt_tick(runner, label, tick_or_report)
    except Exception as error:  # noqa: BLE001
        if not getattr(runner, "signals", None) and not getattr(runner, "human_hold_latched", False) and not getattr(getattr(getattr(runner, "robot", None), "motion", None), "failed", False):
            raise  # no interrupt and no failed native guard: the existing stop (close_device), unchanged
        return emergency_hold(runner, error)


def emergency_hold(runner, error) -> bool:
    runner.torque_hold_commanded, runner._human_hold_ack_pending, runner._human_hold_acked_req = False, False, None
    state = getattr(runner, "_interrupt", None) or _new_state(runner, False)
    cause = f"{type(error).__name__}: {error}"
    torque = _guard_stopped(runner)
    if torque is not None:
        state["guard_cause"], state["guard_read_at"] = cause, runner.clock()
        return _guard_verdict(runner, torque, cause)
    if state["phase"] == "hold" and runner.human_hold_latched:
        if not state.get("tick_error"):
            state["tick_error"] = True
            _stderr({"command": "interrupt", "hold": True, "tick_error": cause[:500]})
        return False
    return _hold(runner, _pose(runner)[0], cause[:500])


def last_resort_hold(runner, signals: list, error, sleep=time.sleep) -> None:
    """The run loop itself raised after an interrupt: no loop is left to stream the hold, so nothing is sent; torque
    stays as the motors hold it. Report HOLD and wait for a SIGUSR2 sent after this point, then return (torque OFF)."""
    row = {"hold": True, "last_resort": True, "error": f"HOLD: {type(error).__name__}: {error}"[:500]
           + "; nothing streams the pose, a person must support the arm, then kill -USR2 the runner"}
    _write_hold(runner, row)
    _stderr({"command": "interrupt", **row})
    mark = len(signals)
    while OPERATOR_RELEASE is None or OPERATOR_RELEASE not in signals[mark:]:
        sleep(0.5)
    _stderr({"command": "interrupt", "released": True, "last_resort": True})
    if runner is not None:
        _approve(runner, "operator release (SIGUSR2) after a last-resort hold")


def gate_allows(runner, signals: list) -> bool:
    """No interrupt, latched hold, pending fold-stop, or unconfirmed guard stop on record, or an approved end."""
    if bool(getattr(runner, "_off_approved", None)):
        return True
    if (getattr(runner, "human_hold_latched", False) or getattr(runner, "_stop_after_park", None) or getattr(runner, "_release_until", None) is not None
            or getattr(getattr(getattr(runner, "robot", None), "motion", None), "failed", False)):
        return False
    return not [s for s in signals if s != OPERATOR_RELEASE]


def final_gate(runner, signals: list, hold_file=None, sleep=time.sleep) -> None:
    """An interrupt on record without an approved end -> last_resort_hold (nothing sent, torque as the motors hold it)
    until a person's SIGUSR2, whichever path returned (idle stop, a judge's stop, the start alignment's stop, a
    signal landing while a status row was written)."""
    if gate_allows(runner, signals):
        return
    holder = runner if runner is not None else type("Unstarted", (), {"hold_file": hold_file})()
    last_resort_hold(holder, signals, RuntimeError("the run ended after an interrupt without a confirmed fold"),
                     sleep=sleep)


def _record_release(holder) -> None:
    """After close() returned (it raises unless torque OFF was read back): an operator release leaves the proof the bench needs
    to clear this runner's lease hold."""
    reason, path = getattr(holder, "_off_approved", None) or "", getattr(holder, "hold_file", None)
    if path is not None and reason.startswith("operator release"):
        try:
            Path(path).with_name("released.json").write_text(json.dumps(
                {"pid": os.getpid(), "t": time.time(), "reason": reason, "torque_off_confirmed": True}))
        except OSError:
            pass


def gated_close(runner, signals: list, hold_file, close, sleep=time.sleep) -> None:
    """chunk_runner.main's single place for torque OFF. SIGINT/SIGTERM/SIGHUP are blocked (Linux) from just before the
    gate reads the recorded signals until close() has returned, so no interrupt can land between an allowing verdict
    and the torque OFF; one sent meanwhile is delivered after, when the verdict already stands. A refusing verdict
    unblocks, waits in last_resort_hold for SIGUSR2 (which records an approved end), then the gate runs again."""
    holder = runner if runner is not None else type("Unstarted", (), {"hold_file": hold_file})()
    mask = getattr(signal, "pthread_sigmask", None)  # absent on Windows test hosts
    while True:
        previous = mask(signal.SIG_BLOCK, BLOCKED_DURING_CLOSE) if mask else None
        try:
            # verdict, then the same check once more right before the torque OFF: a handler can run between two
            # bytecodes of this thread when a thread outside the routing (main_thread_signals) took the signal
            if gate_allows(holder, signals) and gate_allows(holder, signals):
                close()
                _record_release(holder)
                return
        finally:
            if mask:
                mask(signal.SIG_SETMASK, previous)
        final_gate(holder, signals, hold_file, sleep=sleep)
