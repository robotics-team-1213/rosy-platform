#!/usr/bin/env python3
"""D-986: the privileged half of navigation re-approval, reached only through the Host Agent.

A mode change restarts CORE, the caller of the request, so each transition runs in a transient
unit of its own and leaves its result in a state file that status reads afterwards. runtime.env
changes only through commit_runtime and counts only once the projection reads PROJECTED.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

import mapping_approval
from os_state_layout import StateError

STATE = "var/lib/rosy/commissioning/navigation-approval.json"
EVIDENCE = "var/lib/rosy/commissioning/navigation-approval-evidence"
TRIALS = "var/lib/rosy/core/navigation-approval"  # written by CORE's trial collector
RUNTIME = "etc/rosy/runtime.env"
UNIT = "rosy-navigation-approval"
HOLDER = "navigation-approval"
HERE = Path(__file__).resolve().parent
REQUIRED = (("forward", "button_release"), ("reverse", "button_release"), ("cw", "button_release"),
            ("ccw", "button_release"), ("forward", "command_loss"))
PREFLIGHT = "g4-preflight.json"
BUSY = {"BEGINNING", "SEALING", "CANCELLING"}
SURFACES = ("floor", "lifted")
HOLD_HOURS = "4"
MEASURE_S = 3.5 * 3600  # ends before the update hold it depends on
RETRY_S = 600.0
UNIT_START_S = 15.0  # systemd may not report the unit active yet right after the request


class SystemOps:
    """The real privileged actions; a test replaces this whole object."""

    def run(self, *argv, timeout=120):
        return subprocess.run(argv, capture_output=True, text=True, check=False, timeout=timeout)

    def spawn(self, action, *arguments):
        # Outside the Host Agent's sandbox on purpose: the motor probe needs the device CORE's agent may not see.
        return self.run("systemd-run", f"--unit={UNIT}", "--collect", "--no-block",
                        "--setenv=PYTHONNOUSERSITE=1", "--setenv=PYTHONDONTWRITEBYTECODE=1",
                        sys.executable, "-B", str(Path(__file__).resolve()), "run", action, *arguments)

    def now(self):
        return time.monotonic()  # a wall clock can jump; a reboot is caught by the boot id

    def boot_id(self):
        return Path("/proc/sys/kernel/random/boot_id").read_text(encoding="ascii").strip()

    def active(self, unit):
        return self.run("systemctl", "is-active", "--quiet", unit, timeout=20).returncode == 0

    def commit(self, root, new, old):
        from os_state_config import commit_runtime
        from os_state_ready import publish_ready
        commit_runtime(root, new, expected=old)
        publish_ready(root)
        result = self.run(sys.executable, "-B", str(HERE / "os_storage_dispatch.py"), "--projected")
        if result.returncode or json.loads(result.stdout).get("phase") != "PROJECTED":
            raise ValueError("runtime change did not reach the PROJECTED phase")

    def probe_motors(self):
        current = "/opt/rosy/current/install/lib"
        result = self.run("env", f"PYTHONPATH={current}/python3.12/site-packages", f"{current}/bringup/dynamixel_probe",
                          "--device", "/dev/rosy-motor", "--baudrate", "1000000", "--ids", "1", "2")
        text = result.stdout + result.stderr
        responded = [i for i in (1, 2) if f"PASS DXL id={i} responded with torque disabled" in text]
        return {"configured_ids": [1, 2], "responded_ids": responded, "torque_free": responded == [1, 2]}


def _read_state(root):
    try:
        return json.loads((root / STATE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"phase": "IDLE"}


def _write_state(root, state):
    path = root / STATE
    path.parent.mkdir(mode=0o750, parents=True, exist_ok=True)
    handle, name = tempfile.mkstemp(dir=path.parent)
    with os.fdopen(handle, "w", encoding="utf-8") as out:
        json.dump(state, out, sort_keys=True)
    os.replace(name, path)
    return state


def _env(root):
    return (root / RUNTIME).read_bytes()


def _value(env, key):
    for line in env.decode("utf-8").splitlines():
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1]
    return None


def _with_values(env, updates):
    lines, seen = [], set()
    for line in env.decode("utf-8").rstrip("\n").split("\n"):
        key = line.split("=", 1)[0]
        if key in updates:
            line = f"{key}={updates[key]}"
            seen.add(key)
        lines.append(line)
    lines += [f"{key}={value}" for key, value in updates.items() if key not in seen]
    return ("\n".join(lines) + "\n").encode("utf-8")


def _check(ops, *argv):
    result = ops.run(*argv)
    if result.returncode:
        raise ValueError(f"{argv[0]} {' '.join(argv[1:3])} failed: {result.stderr.strip()[:200]}")


def _restart(ops, units):
    _check(ops, "systemctl", "restart", "rosy-core.service")
    for unit in units:
        _check(ops, "systemctl", "start", unit)


def _claim(ops, root):
    _check(ops, sys.executable, "-B", str(HERE / "rosy_claim.py"), "--root", str(root), "acquire", "--holder", HOLDER,
           "--purpose", "navigation-approval", "--ttl-s", "600")


def _unclaim(ops, root):
    ops.run(sys.executable, "-B", str(HERE / "rosy_claim.py"), "--root", str(root), "release", "--holder", HOLDER)


def _hold_path(root):
    from os_state_layout import policy_file  # the updater's own resolution, A/B shared policy included
    return policy_file(root, "hold.json")


def _hold_holder(root):
    """Who holds updates, or None. A hold nobody can read counts as somebody else's."""
    path = _hold_path(root)
    if not path.exists() and not path.is_symlink():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))["holder"]
    except (OSError, ValueError, KeyError, TypeError):
        return "unreadable hold"


def _release_hold(root, state):
    # Not `release-hold`: it also acknowledges rollback and apply failures, which are not this flow's to clear.
    if not state.get("hold_taken"):
        return
    try:
        if _hold_holder(root) == HOLDER:
            _hold_path(root).unlink(missing_ok=True)
    except (OSError, StateError):
        pass  # the hold expires by itself


def _restore(root, ops, state):
    """Back to the runtime begin found, whatever step failed."""
    previous = state.get("previous_runtime")
    if previous is None:
        return
    for unit in ("rosy-navigation.service", "rosy-io.service"):
        ops.run("systemctl", "stop", unit)
    live = _env(root)
    if live.decode("utf-8") != previous:
        ops.commit(root, previous.encode("utf-8"), live)
    _restart(ops, state.get("previous_units") or [])


def _bind_measurement(root, state):
    device = mapping_approval._device_identity(root)
    state.update(measured_release_id=device["release_id"], measured_source_revision=device["source_revision"],
                 measured_fingerprint=mapping_approval.motion_fingerprint(root))


def _require_same_measurement(root, state):
    """Trials carry no identity of their own: they belong to the release begin found, or to nothing."""
    bound = (state.get("measured_release_id"), state.get("measured_source_revision"), state.get("measured_fingerprint"))
    device = mapping_approval._device_identity(root)
    if bound == (device["release_id"], device["source_revision"], mapping_approval.motion_fingerprint(root)):
        return
    for directory in (root / TRIALS, root / EVIDENCE):
        for direction, cause in REQUIRED:
            (directory / f"{direction}-{cause}.json").unlink(missing_ok=True)
    _bind_measurement(root, state)
    _write_state(root, {**state, "phase": "MEASURING", "reason": "the release changed: trials were discarded"})
    raise ValueError("the release changed since begin: trials were discarded, run them again")


def begin(root, ops):
    state = _read_state(root)
    old = _env(root)
    # A begin after a failed restore must keep the runtime the robot really came from.
    fresh = state.get("previous_runtime") is None
    if fresh:
        state.update(previous_runtime=old.decode("utf-8"),
                     previous_units=[u for u in ("rosy-io.service", "rosy-navigation.service") if ops.active(u)])
    state.update(reason="", boot_id=ops.boot_id(), deadline=ops.now() + MEASURE_S)
    _write_state(root, state)
    try:
        holder = _hold_holder(root)
        if holder not in (None, HOLDER):
            raise ValueError(f"an update hold by {holder} is in place: release it before measuring")
        _claim(ops, root)
    except (ValueError, OSError, StateError) as exc:  # nothing changed, so nothing to restore or restart
        kept = {"previous_runtime": None, "previous_units": None} if fresh else {}
        _write_state(root, {**state, **kept, "phase": "FAILED", "reason": str(exc)[:300]})
        return
    try:
        _bind_measurement(root, state)
        _check(ops, sys.executable, "-B", str(HERE / "rosy_auto_update.py"), "hold", "--holder", HOLDER,
               "--reason", "navigation approval measuring", "--hours", HOLD_HOURS)
        state["hold_taken"] = True
        _write_state(root, state)
        for unit in ("rosy-navigation.service", "rosy-io.service"):
            _check(ops, "systemctl", "stop", unit)
        preflight = ops.probe_motors()
        mapping_approval._validate_preflight(preflight)
        evidence = root / EVIDENCE
        evidence.mkdir(mode=0o750, parents=True, exist_ok=True)
        for stale in [*evidence.glob("*.json"), *(root / TRIALS).glob("*.json")]:
            stale.unlink()
        (evidence / PREFLIGHT).write_text(json.dumps(preflight, sort_keys=True), encoding="ascii")
        updates = {"ROSY_RUNTIME_MODE": "motor", "ROSY_IO_DRIVE_ENABLED": "true"}
        if _value(old, "ROSY_NAVIGATION_BACKEND") == "slam":  # CORE refuses motor mode with a slam backend
            updates["ROSY_NAVIGATION_BACKEND"] = "localization"
        new = _with_values(old, updates)
        if new != old:
            ops.commit(root, new, old)
        _restart(ops, ["rosy-io.service"])
        _write_state(root, {**state, "phase": "MEASURING"})
    except Exception as exc:  # noqa: BLE001 - every failure returns the robot before it is reported
        _fail(root, ops, state, exc)
    finally:
        _unclaim(ops, root)


def _fail(root, ops, state, exc):
    reason = str(exc)[:300]
    try:
        _restore(root, ops, state)
    except Exception as restore:  # noqa: BLE001 - a person must see that the robot did not come back
        # The hold stays while the robot is off its normal runtime; the expiry watch tries again.
        _write_state(root, {**state, "phase": "FAILED", "boot_id": ops.boot_id(), "deadline": ops.now() + RETRY_S,
                            "reason": f"{reason}; restore failed: {str(restore)[:200]}"})
        return
    _release_hold(root, state)
    _write_state(root, {"phase": "FAILED", "reason": reason})


def cancel(root, ops, reason="cancelled"):
    state = _read_state(root)
    try:
        _restore(root, ops, state)
    except Exception as exc:  # noqa: BLE001 - reported, and cancel or the expiry watch can try again
        _write_state(root, {**state, "phase": "FAILED", "boot_id": ops.boot_id(), "deadline": ops.now() + RETRY_S,
                            "reason": str(exc)[:300]})
        return
    _release_hold(root, state)
    _write_state(root, {"phase": "IDLE", "reason": reason})


def expire_if_due(root, ops):
    """Motor mode with the drive on never outlives its update hold or the boot it was begun in."""
    state = _read_state(root)
    if _phase(state, ops) not in ("MEASURING", "FAILED") or state.get("previous_runtime") is None:
        return False
    if state.get("boot_id") == ops.boot_id() and ops.now() < state.get("deadline", 0):
        return False
    _start(root, ops, "cancel", "CANCELLING", "measuring expired")
    return True


def _bundle(root, operator, surface):
    """Copy CORE's raw trials beside the probe's result and reference them by hash."""
    evidence = root / EVIDENCE
    device = mapping_approval._device_identity(root)
    trials = []
    for direction, cause in REQUIRED:
        name = f"{direction}-{cause}.json"
        content = (root / TRIALS / name).read_bytes()
        (evidence / name).write_bytes(content)
        trials.append({"direction": direction, "stop_cause": cause, "evidence_file": name,
                       "sha256": mapping_approval._sha256(content)})
    return {"schema_version": 2, "robot_number": device["robot_number"], "release_id": device["release_id"],
            "source_revision": device["source_revision"], "operator": operator, "test_surface": surface,
            "motor_preflight": {"evidence_file": PREFLIGHT,
                                "sha256": mapping_approval._sha256((evidence / PREFLIGHT).read_bytes())},
            "trials": trials}


def seal(root, ops, operator, surface):
    state = _read_state(root)
    try:
        _require_same_measurement(root, state)
        mapping_approval.approve(root, _bundle(root, operator, surface), root / EVIDENCE)
    except Exception as exc:  # noqa: BLE001 - nothing was sealed and no mode moved: trials can be run again
        current = _read_state(root)
        _write_state(root, {**current, "phase": "MEASURING", "reason": str(exc)[:300]})
        return
    try:
        _claim(ops, root)
    except ValueError as exc:  # sealed, still in motor mode: sealing again or cancelling both stay open
        _write_state(root, {**state, "phase": "MEASURING", "reason": str(exc)[:300]})
        return
    try:
        for unit in ("rosy-navigation.service", "rosy-io.service"):
            _check(ops, "systemctl", "stop", unit)
        old = _env(root)
        backend = _value((state.get("previous_runtime") or "").encode("utf-8"), "ROSY_NAVIGATION_BACKEND")
        new = _with_values(old, {"ROSY_RUNTIME_MODE": "hardware", "ROSY_IO_DRIVE_ENABLED": "true",
                                 "ROSY_NAVIGATION_BACKEND": backend if backend in ("localization", "slam") else "localization"})
        if new != old:
            ops.commit(root, new, old)
        _restart(ops, ["rosy-io.service"])
        mapping_approval.check(root)
        _release_hold(root, state)
        _write_state(root, {"phase": "IDLE", "reason": "sealed", "sealed_by": operator})
    except Exception as exc:  # noqa: BLE001
        _fail(root, ops, state, exc)
    finally:
        _unclaim(ops, root)


def _trial_state(root):
    rows = []
    for direction, cause in REQUIRED:
        row = {"direction": direction, "stop_cause": cause, "state": "missing"}
        path = root / TRIALS / f"{direction}-{cause}.json"
        if path.is_file() and not path.is_symlink():
            try:
                latency = mapping_approval._validate_trial(json.loads(path.read_bytes()), direction, cause)
                row.update(state="valid", stop_latency_s=round(latency, 3))
            except (ValueError, KeyError, TypeError) as exc:
                row.update(state="invalid", reason=str(exc)[:200])
        rows.append(row)
    return rows


def _phase(state, ops):
    phase = state.get("phase", "IDLE")
    if (phase in BUSY and time.time() - state.get("requested_at", 0) > UNIT_START_S
            and not ops.active(f"{UNIT}.service")):
        return "FAILED"
    return phase


def status(root, ops):
    state = _read_state(root)
    phase = _phase(state, ops)
    if phase != state.get("phase", "IDLE"):
        state["reason"] = "the transition ended without a result"
    try:
        found = mapping_approval.check(root, runtime_mode="hardware")
        approval = {"valid": True, "carried": "measured_release_id" in found,
                    "measured_release_id": found.get("measured_release_id", found["release_id"]), "reason": ""}
    except (OSError, ValueError, KeyError, TypeError) as exc:
        approval = {"valid": False, "carried": False, "measured_release_id": None, "reason": str(exc)[:200]}
    env = _env(root)
    return {"phase": phase, "reason": state.get("reason", ""), "approval": approval,
            "needs_measurement": not approval["valid"], "runtime_mode": _value(env, "ROSY_RUNTIME_MODE"),
            "measuring_expires_in_s": (max(0, round(state.get("deadline", 0) - ops.now()))
                                       if phase == "MEASURING" and state.get("boot_id") == ops.boot_id() else None),
            "trials": _trial_state(root)}


def _start(root, ops, action, phase, *arguments):
    state = _read_state(root)
    previous = state.get("phase", "IDLE")
    _write_state(root, {**state, "phase": phase, "reason": "", "requested_at": time.time()})
    result = ops.spawn(action, *arguments)
    if result.returncode:
        _write_state(root, {**state, "phase": previous})
        raise ValueError(f"transition could not start: {result.stderr.strip()[:200]}")
    return status(root, ops)


def request_begin(root, ops):
    current = status(root, ops)
    if current["phase"] not in ("IDLE", "FAILED"):
        raise ValueError(f"cannot begin while {current['phase']}")
    return _start(root, ops, "begin", "BEGINNING")


def request_cancel(root, ops):
    current = status(root, ops)
    if current["phase"] not in ("MEASURING", "FAILED"):
        raise ValueError(f"nothing to cancel while {current['phase']}")
    return _start(root, ops, "cancel", "CANCELLING")


def request_seal(root, ops, operator, surface):
    current = status(root, ops)
    if current["phase"] != "MEASURING":
        raise ValueError(f"cannot seal while {current['phase']}")
    _require_same_measurement(root, _read_state(root))
    if any(row["state"] != "valid" for row in current["trials"]):
        raise ValueError("every required trial must be valid before sealing")
    if surface not in SURFACES:
        raise ValueError("test surface must be floor or lifted")
    return _start(root, ops, "seal", "SEALING", operator, surface)


def start_navigation(root, ops):
    """Explicit and separate from sealing. rosy-navigation's own ExecCondition checks the seal again."""
    mapping_approval.check(root)
    _check(ops, "systemctl", "start", "--no-block", "rosy-navigation.service")
    return {"started_at": time.time(), **status(root, ops)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=Path("/"))
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run")
    run.add_argument("action", choices=("begin", "cancel", "seal"))
    run.add_argument("arguments", nargs="*")
    args = parser.parse_args(argv)
    ops = SystemOps()
    if args.action == "begin":
        begin(args.root, ops)
    elif args.action == "cancel":
        cancel(args.root, ops, *args.arguments)
    else:
        seal(args.root, ops, *args.arguments)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
