#!/usr/bin/env python3
"""One arm's persistent observer handed to a session and back (decision H4).

  observer_handoff.py run <arm> [--joint-topic T] [--env-dir D] [--timeout-s S] [--group-timeout-s G] -- <session...>
  observer_handoff.py release <arm> [--env-dir D]

run:
1. Before touching the observer: the arm's unit env (~/.config/rosy/omx-observer-<arm>.env, the unit's own
   EnvironmentFile) must name a /dev/serial/by-id device that resolves; the joint topic must be the bridge
   manifest's joint_topic for this arm (manifest and workcell from omx-observation-bridge.env); the snapshot
   folder must be the bridge unit's own ROSY_OBSERVATION_DIR (systemctl show; an exported ROSY_OBSERVATION_DIR
   must be the same folder). Otherwise exit 69 with nothing changed.
2. Take the session locks (joint_tune_lock rules) and the arm lease (D-1035: whether run created it is decided
   inside the lease lock; an existing lease of this owner is refreshed and kept), stop rosy-omx-observer@<arm>,
   and wait until the port is confirmed free. A port that stays held, or a check that cannot be made (link gone,
   fuser error), is exit 69: no session.
3. Run the session in its own process group with the locks still held: their open files go to it (pass_fds +
   ROSY_OMX_HELD_LOCKS), so its session_lock reuses them and there is no unlocked gap. ROSY_CHUNK_JOINT_TOPIC
   makes chunk_runner write the same SnapshotChannel, so the bridge stays the one sender to Fleet.
   On Linux the group's leader is 'observer_handoff.py _lead' with PR_SET_PDEATHSIG=SIGTERM: if run itself is
   killed (SIGKILL, Fleet's 300 s timeout in cell_task_exec), the leader gets SIGTERM and passes it to the
   whole group, so the session ends through its own safe end instead of running on unsupervised.
4. SIGINT/SIGTERM/SIGHUP, every time they arrive, go to the session's whole group (through the leader); run
   never skips ahead. It waits until the whole group is gone (never SIGKILL: an arm session parks itself).
5. Confirm the port is free, let the locks and the lease (if run created it) go, start the observer if its unit
   is enabled, and count it resumed only once fuser shows the observer's own PID on the port.

stdout carries only the session's output (cell_task_exec reads its last JSON line); every handoff line is JSON on
stderr. The observer outcome never changes the session's result: it goes to stderr and to the state file
~/.local/state/rosy/observer-handoff/<arm>.json (rosy.omx-observer-handoff.v1, for the pipeline gate).
Exit: the session's code; 128+signal when cancelled (130 SIGINT, 143 SIGTERM, 129 SIGHUP); 69 handoff refused,
no session; 71 session processes still alive after --group-timeout-s (the observer stays down).

fuser and the /proc scan only see processes of this user (or all, as root): every port user must be a
user service of the same account, as the cell's observer, bridge and sessions are.

release: manual recovery after a run that was killed; restarts an enabled observer only on a confirmed-free port
(exit 70 when it could not).
"""
from __future__ import annotations

import argparse
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
_FOUNDATION = str(Path(__file__).resolve().parents[3] / "contracts/foundation")
if _FOUNDATION not in sys.path:
    sys.path.append(_FOUNDATION)
import cell_arm_lease  # noqa: E402
from joint_tune_lock import HELD_ENV, session_lock  # noqa: E402
from observer_handoff_io import (  # noqa: E402,F401 - bridge_binding and HandoffError stay importable from here
    HandoffError, bridge_binding, fuser, group_members, port_holders, proc_holders, record_state, report, session_env, systemctl,
    unit_env,
)

ARM = re.compile(r"[A-Za-z0-9_-]{1,32}")  # session_lock's own rule
BY_ID = Path("/dev/serial/by-id")
HANDOFF_FAILED, RECOVERY_FAILED, SESSION_LINGERS = 69, 70, 71
GROUP_WAIT_ENV = "ROSY_HANDOFF_GROUP_TIMEOUT_S"
SIGNALS = tuple(s for s in (getattr(signal, n, None) for n in ("SIGINT", "SIGTERM", "SIGHUP")) if s is not None)


def resolve_device(device):
    """register_probe.open_readonly_port's rule: a physically confirmed by-id link that resolves."""
    path = Path(device)
    if path.parent != BY_ID or not path.is_symlink():
        raise HandoffError(f"{device}: not a {BY_ID} link; ownership cannot be checked")
    try:
        return str(path.resolve(strict=True))
    except OSError as exc:
        raise HandoffError(f"{device}: link does not resolve ({exc}); ownership cannot be checked") from exc


def wait_port(device, *, want, users, scan, timeout_s, sleep, clock):
    """Poll until want(holders) is true; the link is re-resolved every time (a vanished link is unconfirmed)."""
    deadline = clock() + timeout_s
    while True:
        holders = port_holders(resolve_device(device), users, scan)
        if want(holders):
            return holders
        if clock() >= deadline:
            raise HandoffError(f"{device} held by {sorted(holders) or 'nobody'} after {timeout_s:g} s")
        sleep(0.2)


def group_alive(pgid):
    members = group_members(pgid)
    if members is not None:
        return bool(members)
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def signal_session(child, signum):
    """Through the leader while it lives (it passes the signal to the group once); straight to the group after."""
    try:
        if child.poll() is None:
            os.kill(child.pid, signum)
        else:
            os.killpg(child.pid, signum)
    except OSError:
        pass  # already gone


def _die_with(parent):
    def setup():  # in the forked leader, before exec; survives exec
        import ctypes

        if ctypes.CDLL(None, use_errno=True).prctl(1, signal.SIGTERM) != 0 or os.getppid() != parent:  # PR_SET_PDEATHSIG
            os._exit(125)  # run is already gone (or no prctl): never start an unsupervised session
    return setup


def spawn_session(command, *, env, pass_fds):
    if not sys.platform.startswith("linux"):  # no arm sessions here; keeps the stdout contract testable
        return subprocess.Popen(command, env=env, pass_fds=pass_fds, start_new_session=True)
    leader = [sys.executable, str(Path(__file__).resolve()), "_lead", "--", *command]
    return subprocess.Popen(leader, env=env, pass_fds=pass_fds, start_new_session=True,
                            preexec_fn=_die_with(os.getpid()))


def lead(command):
    """The session group's leader: runs the session in its own group and passes every SIGINT/SIGTERM/SIGHUP to the
    whole group, including the SIGTERM it gets when run dies (PR_SET_PDEATHSIG)."""
    fds = [int(fd) for fd in os.environ.get(HELD_ENV, "").split(":")[1:] if fd.isdigit()]
    pending = []

    def forward(signum, frame):
        signal.signal(signum, signal.SIG_IGN)  # the leader is in the group too: no echo
        try:
            os.killpg(0, signum)
        except OSError:
            pass
        finally:
            signal.signal(signum, forward)
        pending.append(signum)

    for s in SIGNALS:
        signal.signal(s, forward)
    child = subprocess.Popen(command, pass_fds=fds)
    if pending:  # arrived before the session existed: to everything it has forked by now, not only to its shell
        forward(pending[0], None)
    code = child.wait()
    # Stay (and keep forwarding) until nothing but this leader is left in the group: a shell wrapper may return
    # while its background session runs, and run's death must still reach that session. Bounded, so run's own
    # --group-timeout-s report (exit 71) still comes.
    # Run does not wait a second time after this leader (a second window with no leader to pass run's death on).
    deadline = time.monotonic() + float(os.environ.get(GROUP_WAIT_ENV) or 120)
    while time.monotonic() < deadline and (group_members(os.getpgrp()) or set()) - {os.getpid()}:
        time.sleep(0.2)
    return 128 - code if code < 0 else code


def restart(arm, *, run, users, scan, device, sleep, clock, timeout_s, resume_s):
    """('resumed' | 'left_disabled' | 'failed', error); 'resumed' only once the observer holds the port again."""
    unit = f"rosy-omx-observer@{arm}.service"
    try:
        wait_port(device, want=lambda h: not h, users=users, scan=scan, timeout_s=timeout_s, sleep=sleep,
                  clock=clock)
        state = run("is-enabled", unit).stdout.strip()
        if state in ("disabled", "masked", "masked-runtime"):
            report(event="observer_left_disabled", arm=arm, unit=unit, state=state)
            return "left_disabled", None
        if state != "enabled":
            raise HandoffError(f"is-enabled {unit}: {state or 'no answer'}")
        started = run("start", unit)
        if started.returncode != 0:
            raise HandoffError(f"could not start {unit}: {started.stderr.strip()}")
        main_pid = int(run("show", "-p", "MainPID", "--value", unit).stdout.strip() or 0)
        if main_pid <= 0:
            raise HandoffError(f"{unit} started without a main process")
        wait_port(device, want=lambda h: main_pid in h, users=users, scan=scan, timeout_s=resume_s, sleep=sleep,
                  clock=clock)
    except (HandoffError, OSError, ValueError, subprocess.SubprocessError) as exc:
        report(error=f"{exc}; observer not restored", recovery="failed", arm=arm, unit=unit)
        return "failed", str(exc)
    report(event="observer_resumed", arm=arm, unit=unit, pid=main_pid)
    return "resumed", None


def handoff(arm, command, *, topic=None, env_dir=None, environ=None, timeout_s=5.0, resume_s=10.0,
            group_timeout_s=120.0, run=systemctl, users=fuser, scan=proc_holders, lock=session_lock,
            lease=cell_arm_lease, spawn=spawn_session, sleep=time.sleep, clock=time.monotonic,
            alive=group_alive, kill=signal_session, signals=SIGNALS, bridge=bridge_binding, state_dir=None,
            leader_waited=None):
    unit = f"rosy-omx-observer@{arm}.service"
    environ = dict(os.environ if environ is None else environ)
    try:
        values = unit_env(arm, env_dir)
        device = values["ROSY_OBSERVER_DEVICE"]
        resolve_device(device)
        binding = bridge(arm, env_dir=env_dir, run=run)
        if values.get("ROSY_OBSERVER_TOPIC") != binding[0]:  # the unit restarts on this value: a stale one blinds Fleet
            raise HandoffError(f"{unit} env ROSY_OBSERVER_TOPIC {values.get('ROSY_OBSERVER_TOPIC')!r} is not the "
                               f"bridge manifest's {binding[0]}; fix the unit env before a handoff")
        env = session_env(arm, topic, environ, binding)
        for i, word in enumerate(command):  # a topic named on the session command is a second, unchecked one
            if word == "--joint-topic":
                given = command[i + 1] if i + 1 < len(command) else ""
            elif word.startswith("--joint-topic="):
                given = word.partition("=")[2]
            else:
                continue
            if given != binding[0]:
                raise HandoffError(f"session command names joint topic {given!r}, not the bridge manifest's {binding[0]}")
        env[GROUP_WAIT_ENV] = f"{group_timeout_s:g}"
        locks = lock(arm)
    except (HandoffError, SystemExit) as exc:
        report(error=str(exc), stage="check", arm=arm)
        return HANDOFF_FAILED

    if leader_waited is None:  # the leader already waited --group-timeout-s for the group: no second wait here
        leader_waited = spawn is spawn_session and sys.platform.startswith("linux")
    state = {"signal": None, "child": None}

    def forward(signum, frame):  # every signal, every time: to the session's group; run itself keeps waiting
        state["signal"] = state["signal"] or signum
        report(event="signal_forwarded", signal=signum, arm=arm)
        if state["child"] is not None:
            kill(state["child"], signum)

    previous = {s: signal.signal(s, forward) for s in signals}
    owner, code, stopped, created = lease.default_owner(), HANDOFF_FAILED, False, False
    observer, problem, lingers = "untouched", None, False
    try:
        try:
            created = lease.claim(arm, owner, "observer_handoff", pid=os.getpid(), report_created=True,
                                  keep_live=True)[1]
            stopped = True  # from here a failed stop may still have stopped it: recovery decides
            try:
                result = run("stop", unit)
                failure = None if result.returncode == 0 else result.stderr.strip()
            except (OSError, subprocess.SubprocessError) as exc:  # a timeout may still have stopped it
                failure = f"{type(exc).__name__} {exc}"
            if failure is not None:
                # only a unit confirmed down gets the restart; anything else (still running, or no answer) was not
                # stopped as far as we know, so its stop failure is the report, not a recovery failure
                active = ""
                for _ in range(10):  # a timed-out stop may still be deactivating
                    try:
                        active = run("is-active", unit).stdout.strip()
                    except (OSError, subprocess.SubprocessError):
                        active = ""
                    if active != "deactivating":
                        break
                    sleep(0.5)
                stopped = active in ("inactive", "failed")
                observer = "untouched" if stopped else "stop_failed"
                raise HandoffError(f"could not stop {unit}: {failure} (is-active: {active or 'no answer'})")
            wait_port(device, want=lambda h: not h, users=users, scan=scan, timeout_s=timeout_s, sleep=sleep,
                      clock=clock)
            if state["signal"]:
                raise HandoffError(f"signal {state['signal']} before the session started")
        except (HandoffError, lease.LeaseHeld, OSError, subprocess.SubprocessError) as exc:
            report(error=f"{exc}; session not started", stage="handoff", arm=arm)
            problem = str(exc)
            if state["signal"]:  # cancelled before any session: 128+signal, not a refusal
                code = 128 + state["signal"]
        else:
            fds = [h.fileno() for h in getattr(locks, "handles", ())]
            env[HELD_ENV] = ":".join([arm, *map(str, fds)]) if len(fds) == 2 else ""
            report(event="observer_handed_over", arm=arm, unit=unit, device=device)
            try:
                child = spawn(command, env=env, pass_fds=fds)
            except OSError as exc:
                report(error=f"session did not start: {exc}", stage="session", arm=arm)
                code = 127
            else:
                state["child"] = child
                if created and getattr(child, "pid", None) and leader_waited:
                    # the leader lives until its group is gone; this wrapper may be killed first (Fleet's timeout),
                    # and the lease must not turn reclaimable while the recorder is still folding
                    lease.repid(arm, child.pid, owner=owner)
                if state["signal"]:  # arrived between the last check and the spawn
                    kill(child, state["signal"])
                code = child.wait()
                code = 128 - code if code < 0 else code
                deadline = clock() + (0 if leader_waited else group_timeout_s)
                while alive(child.pid):  # a shell wrapper's own children may outlive it
                    if clock() >= deadline:
                        problem = f"session processes of group {child.pid} still alive after {group_timeout_s:g} s"
                        report(error=f"{problem}; observer left stopped", stage="session", arm=arm)
                        stopped, code, observer, lingers = False, SESSION_LINGERS, "stayed_down", True
                        break
                    sleep(0.5)
                if state["signal"] and code != SESSION_LINGERS:
                    code = 128 + state["signal"]  # cancelled: never a success, whatever the session returned
    finally:
        try:
            if lingers:  # session processes may still run: nobody else may claim the arm until a person releases it
                lease.hold(arm, "observer_handoff: session processes still alive after the group wait", owner=owner)
            elif created:
                lease.release(arm, owner)
        except Exception as exc:  # noqa: BLE001 - reported; never replaces the session's code
            report(error=f"lease release: {exc}", recovery="failed", arm=arm)
        finally:
            locks.close()  # before start: the unit's ExecStartPre refuses while the arm lock is held
        if stopped:
            observer, error = restart(arm, run=run, users=users, scan=scan, device=device, sleep=sleep,
                                      clock=clock, timeout_s=timeout_s, resume_s=resume_s)
            problem = error or problem
        if observer != "untouched":
            record_state(state_dir, arm, session_code=code, observer=observer, error=problem)
        for s, handler in previous.items():
            signal.signal(s, handler)
    return code  # the observer's outcome is reported, never folded into the session's result


def release(arm, *, env_dir=None, run=systemctl, users=fuser, scan=proc_holders, sleep=time.sleep,
            clock=time.monotonic, resume_s=10.0, state_dir=None):
    try:
        device = unit_env(arm, env_dir)["ROSY_OBSERVER_DEVICE"]
    except HandoffError as exc:
        report(error=str(exc), arm=arm)
        return RECOVERY_FAILED
    observer, error = restart(arm, run=run, users=users, scan=scan, device=device, sleep=sleep, clock=clock,
                              timeout_s=0, resume_s=resume_s)
    record_state(state_dir, arm, session_code=None, observer=observer, error=error)
    return RECOVERY_FAILED if observer == "failed" else 0


def parse(argv):
    """Options before '--', the session command after it, so no option is ever taken as the command."""
    argv = list(argv)
    split = argv.index("--") if "--" in argv else len(argv)
    own, session = argv[:split], argv[split + 1:]
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("run", "release"))
    parser.add_argument("arm", help="observer instance name, e.g. arm_a (session-<arm>.lock)")
    parser.add_argument("--joint-topic", help="run: must equal the bridge manifest's joint_topic (the default)")
    parser.add_argument("--timeout-s", type=float, default=5.0, help="seconds to wait for the port to come back")
    parser.add_argument("--group-timeout-s", type=float, default=120.0,
                        help="run: seconds to wait for the session's leftover processes after it exits")
    parser.add_argument("--env-dir", type=Path, help="folder holding omx-observer-<arm>.env and "
                                                     "omx-observation-bridge.env (default ~/.config/rosy)")
    args = parser.parse_args(own)
    if not ARM.fullmatch(args.arm):
        parser.error("arm must be a plain name")
    if args.command == "run" and not session:
        parser.error("run needs -- <session command...>")
    if args.command == "release" and session:
        parser.error("release takes no session command")
    return args, session


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    if argv[:2] == ["_lead", "--"] and argv[2:]:
        return lead(argv[2:])
    args, session = parse(argv)
    if args.command == "release":
        return release(args.arm, env_dir=args.env_dir)
    return handoff(args.arm, session, topic=args.joint_topic, env_dir=args.env_dir, timeout_s=args.timeout_s,
                   group_timeout_s=args.group_timeout_s)


if __name__ == "__main__":
    raise SystemExit(main())
