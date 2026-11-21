"""observer_handoff.py's host reads: systemctl and fuser answers, the observer and bridge unit env files, the
bridge's joint topic and snapshot folder, and the per-arm handoff state file (decision H4). Every refusal is a
HandoffError; stdout belongs to the session, so report() writes JSON lines to stderr."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path


class HandoffError(RuntimeError):
    pass


def systemctl(*args):
    return subprocess.run(["systemctl", "--user", *args], capture_output=True, text=True, timeout=30)


def fuser(device):
    return subprocess.run(["fuser", device], capture_output=True, text=True, timeout=10)


def proc_holders(resolved, proc=Path("/proc")):
    """PIDs whose open fds point at the device, as far as this user may look (a second view beside fuser)."""
    pids = set()
    for fd_dir in proc.glob("[0-9]*/fd"):
        try:
            if any(os.readlink(fd) == resolved for fd in fd_dir.iterdir()):
                pids.add(int(fd_dir.parent.name))
        except OSError:
            continue  # another user's process or one that just ended
    return pids


def group_members(pgid, proc=Path("/proc")):
    """Live (not zombie) PIDs of a process group, or None without /proc. A zombie is not a running session: in a
    container whose PID 1 does not reap, orphans stay zombies for ever and kill(-pgid, 0) would call them alive."""
    if not proc.is_dir():
        return None
    members = set()
    for stat in proc.glob("[0-9]*/stat"):
        try:
            fields = stat.read_text().rpartition(")")[2].split()  # comm may hold spaces; state ppid pgrp follow it
            if int(fields[2]) == pgid and fields[0] not in ("Z", "X"):
                members.add(int(stat.parent.name))
        except (OSError, ValueError, IndexError):
            continue  # ended while we looked
    return members


def report(**fields):
    print(json.dumps(fields), file=sys.stderr, flush=True)  # stdout belongs to the session


def unit_env_file(path):
    values = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            key, separator, value = line.strip().partition("=")
            if separator and not key.startswith("#"):
                values[key.strip()] = value.strip().strip("'\"")
    except OSError as exc:
        raise HandoffError(f"{path}: {exc}") from exc
    return values


def unit_env(arm, env_dir=None):
    path = Path(env_dir or Path.home() / ".config/rosy") / f"omx-observer-{arm}.env"
    values = unit_env_file(path)
    if not values.get("ROSY_OBSERVER_DEVICE"):
        raise HandoffError(f"{path}: ROSY_OBSERVER_DEVICE missing; cannot check the port")
    return values


def port_holders(resolved, users=fuser, scan=proc_holders):
    """The PIDs holding the port (empty = free); anything fuser did not answer cleanly is a HandoffError."""
    try:
        out = users(resolved)
    except (OSError, subprocess.SubprocessError) as exc:
        raise HandoffError(f"fuser {resolved} failed: {exc}") from exc
    if out.returncode == 0:
        return {int(p) for p in re.findall(r"\d+", out.stdout)} or {-1}
    if out.returncode != 1 or out.stdout.strip() or out.stderr.strip():
        raise HandoffError(f"fuser {resolved} exit {out.returncode}: {(out.stderr or out.stdout).strip()}")
    return scan(resolved)  # psmisc: exit 1 and silent means no visible user; /proc must agree


def unit_dir_env(run, unit="rosy-omx-observation-bridge.service"):
    """The bridge unit's own environment as systemd resolved it (%t expanded)."""
    out = run("show", "-p", "Environment", "--value", unit)
    return dict(item.partition("=")[::2] for item in out.stdout.split() if "=" in item)


def bridge_binding(arm, *, env_dir=None, run=systemctl):
    """(joint_topic, snapshot folder) the bridge actually reads for this arm."""
    import yaml

    folder = Path(env_dir or Path.home() / ".config/rosy")
    try:
        bridge = unit_env_file(folder / "omx-observation-bridge.env")
        manifest = yaml.safe_load(Path(bridge["ROSY_WORKCELL_OBSERVATIONS"]).read_text(encoding="utf-8"))
        cell = next(c for c in manifest["workcells"] if c["workcell_id"] == bridge["ROSY_OBSERVATION_WORKCELL"])
        topic = next(a["joint_topic"] for a in cell["arms"] if a["arm_id"] == arm)
        snapshots = unit_dir_env(run).get("ROSY_OBSERVATION_DIR", "")
    except (OSError, KeyError, TypeError, StopIteration, yaml.YAMLError, subprocess.SubprocessError) as exc:
        raise HandoffError(f"cannot read the bridge's binding for {arm}: {type(exc).__name__} {exc}") from exc
    if not snapshots:
        raise HandoffError("the bridge unit has no ROSY_OBSERVATION_DIR")
    return topic, snapshots


def session_env(arm, topic, environ, binding):
    """Checked before the observer is touched: a topic or snapshot folder the bridge does not read would silently
    drop the arm from Fleet for the whole session."""
    from hardware_observer import joint_topic

    want_topic, want_folder = binding
    topic = topic or want_topic
    try:
        joint_topic(topic)
    except ValueError as exc:
        raise HandoffError(f"joint topic {topic!r}: {exc}") from exc
    if topic != want_topic:
        raise HandoffError(f"joint topic {topic} is not the bridge manifest's {want_topic} for {arm}")
    folder = environ.get("ROSY_OBSERVATION_DIR") or want_folder
    if not (os.path.isabs(folder) and os.path.isdir(folder)):
        raise HandoffError(f"snapshot folder {folder!r} must exist (the bridge's ROSY_OBSERVATION_DIR)")
    if os.path.realpath(folder) != os.path.realpath(want_folder):
        raise HandoffError(f"ROSY_OBSERVATION_DIR {folder} is not the bridge's {want_folder}")
    return {**environ, "ROSY_CHUNK_JOINT_TOPIC": topic, "ROSY_OBSERVATION_DIR": folder}


def record_state(state_dir, arm, **fields):
    """The gate's view of the last handoff for this arm; a write failure is only reported."""
    try:
        folder = Path(state_dir or Path.home() / ".local/state/rosy/observer-handoff")
        folder.mkdir(parents=True, exist_ok=True)
        tmp = folder / f"{arm}.json.tmp"
        tmp.write_text(json.dumps({"schema": "rosy.omx-observer-handoff.v1", "arm": arm, "at": time.time(),
                                   **fields}), encoding="utf-8")
        os.replace(tmp, folder / f"{arm}.json")
    except OSError as exc:
        report(error=f"handoff state not written: {exc}", arm=arm)
