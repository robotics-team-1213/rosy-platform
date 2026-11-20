#!/usr/bin/env python3
"""SLAM fallback: the privileged half that switches a robot from SLAM to the site wall map (automatic by user decision 2026-11-18).

Reached only through the Host Agent (machine grade; the socket already admits only CORE's uid). Two actions:
  stage  - install the wall map CORE spooled (sha256 re-checked, the yaml is built here from numbers, never taken from CORE);
           refused while a switch runs, never deletes the map the runtime names, atomic per file
  switch - only after CORE has proven a stop: zero velocity >= ZERO_S, no goal, same boot (CLOCK_MONOTONIC + boot id), evidence
           from a plain file CORE owns. runtime.env changes only through commit_runtime (the approval host's SystemOps.commit),
           rosy-navigation restarts, a failed restart rolls back to the saved bytes (0600, not in the state file).
It never touches CORE, never releases an update hold, and never switches back to SLAM. One attempt per boot (success, refusal
or rollback) until a person runs `navigation_fallback_host.py reset` as root.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
import time

import navigation_approval_host as approval
import yaml

STATE = "var/lib/rosy/commissioning/navigation-fallback.json"  # 0600: phase and reasons only
RUNTIME_BACKUP = "var/lib/rosy/commissioning/navigation-fallback-runtime.bak"  # 0600: the exact runtime.env to roll back to
CORE_DIR = "var/lib/rosy/core"
SPOOL = f"{CORE_DIR}/wall-map-spool"  # CORE writes meta.json + wall-map.pgm here
SPOOL_IMAGE, SPOOL_META = "wall-map.pgm", "meta.json"
STOP_EVIDENCE = f"{CORE_DIR}/slam-fallback-stop.json"  # CORE rewrites it every tick until this host has answered
MAPS = "var/lib/rosy/maps"
POINTER = "wall-map.json"
RUNTIME = approval.RUNTIME
UNIT = "rosy-navigation-fallback"
NAVIGATION = "rosy-navigation.service"
ZERO_S = 2.0            # velocity must have been zero this long (user rule: stop first, confirmed)
EVIDENCE_FRESH_S = 3.0  # the stop evidence must have been written this recently (CLOCK_MONOTONIC, same boot)
UNIT_START_S = 15.0
SETTLE_S = 20.0         # rosy-navigation must report active within this after the restart
EVIDENCE_MAX = 4096
META_MAX = 4096
RESOLUTION = (0.01, 0.1)  # m per cell: what a wall map of this arena can be
ORIGIN_LIMIT = 1000.0     # m
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_REASON = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
MAX_CELLS = 4096 * 4096


class SystemOps(approval.SystemOps):
    """Reuses the approval host's real actions (run, commit with PROJECTED check, boot id, monotonic clock)."""

    def spawn(self, action, *arguments):
        return self.run("systemd-run", f"--unit={UNIT}", "--collect", "--no-block", "--setenv=PYTHONNOUSERSITE=1",
                        "--setenv=PYTHONDONTWRITEBYTECODE=1", sys.executable, "-B", str(Path(__file__).resolve()),
                        "run", action, "--", *arguments)

    def sleep(self, seconds):
        time.sleep(seconds)

    def wall(self):
        return time.time()


def _read(root, rel, default):
    try:
        return json.loads((root / rel).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _atomic(path, content, mode):
    path.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    handle, name = tempfile.mkstemp(dir=path.parent)
    with os.fdopen(handle, "wb") as out:
        out.write(content)
    os.chmod(name, mode)
    os.replace(name, path)


def _write(root, rel, data, mode=0o644):
    _atomic(root / rel, json.dumps(data, sort_keys=True).encode("utf-8"), mode)
    return data


def _core_bytes(root, rel, limit):
    """A file CORE wrote, read safely as root: no symlink, a regular file, at most `limit` bytes, owned by whoever owns
    CORE's state directory and not writable by group or others. Anything else is OSError or ValueError."""
    owner = (root / CORE_DIR).stat().st_uid
    fd = os.open(root / rel, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    with os.fdopen(fd, "rb") as handle:
        info = os.fstat(handle.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_size > limit or info.st_uid != owner
                or (os.name == "posix" and info.st_mode & 0o022)):
            raise ValueError("not a plain file written by CORE")
        return handle.read(limit + 1)


def _sha(content):
    return hashlib.sha256(content).hexdigest()


def _pgm_cells(pgm):
    """Width x height of a binary P5 with maxval 255 whose body size matches, else ValueError."""
    match = re.match(rb"P5\s+(\d+)\s+(\d+)\s+255\s", pgm)
    if not match:
        raise ValueError("the wall map image is not a P5 PGM with maxval 255")
    width, height = int(match[1]), int(match[2])
    if not 0 < width * height <= MAX_CELLS or len(pgm) - match.end() != width * height:
        raise ValueError("the wall map image size does not match its header")
    return width, height


def _sane(resolution, origin):
    """Finite and in range (nan fails every comparison): Nav2 would otherwise fail after the stop."""
    return (RESOLUTION[0] <= resolution <= RESOLUTION[1] and len(origin) == 3
            and all(math.isfinite(v) and abs(v) <= ORIGIN_LIMIT for v in origin))


def _loadable(yaml_path):
    """The rules of site_map._is_loadable, plus finite numbers in range."""
    try:
        data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
        image = yaml_path.parent / data["image"]
        return image.is_file() and _sane(float(data["resolution"]), [float(v) for v in data["origin"]])
    except (OSError, yaml.YAMLError, KeyError, TypeError, ValueError):
        return False


def _state(root):
    return _read(root, STATE, {"phase": "IDLE"})


def _stuck(state, ops):
    """SWITCHING that nobody runs: written in another boot, or the unit ended without leaving a result."""
    if state.get("phase") != "SWITCHING":
        return False
    boot = state.get("attempt_boot_id") or state.get("requested_boot_id")
    if boot is not None and boot != ops.boot_id():
        return True
    return ops.wall() - (state.get("requested_at") or 0) > UNIT_START_S and not ops.active(f"{UNIT}.service")


def _busy(root, ops):
    state = _state(root)
    return state.get("phase") == "SWITCHING" and not _stuck(state, ops)


def stage(root, ops):
    """Install CORE's spooled wall map as wall_<id>_v<n>.pgm/.yaml; keep the last good one and the one runtime.env names."""
    if _busy(root, ops):
        raise ValueError("a fallback switch is running: the wall map is not replaced now")
    try:
        meta = json.loads(_core_bytes(root, f"{SPOOL}/{SPOOL_META}", META_MAX))
        pgm = _core_bytes(root, f"{SPOOL}/{SPOOL_IMAGE}", MAX_CELLS + 64)
        map_id, version = str(meta["map_id"]), int(meta["version"])
        resolution, origin = float(meta["resolution"]), [float(v) for v in meta["origin"]]
        if not _ID.match(map_id) or version < 0 or not _sane(resolution, origin):
            raise ValueError("the wall map description is malformed")
        if _sha(pgm) != meta["sha256"]:
            raise ValueError("the wall map image does not match its sha256")
        _pgm_cells(pgm)
    except (OSError, KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"wall map refused: {str(exc)[:200]}") from exc
    stem = f"wall_{map_id}_v{version}"
    maps = root / MAPS
    maps.mkdir(parents=True, exist_ok=True)
    named = approval._value(approval._env(root), "ROSY_MAP")  # the map the running navigation was started on
    live = Path(named).stem if named else None
    description = yaml.safe_dump({"image": f"{stem}.pgm", "mode": "trinary", "resolution": resolution, "origin": origin,
                                  "negate": 0, "occupied_thresh": 0.65, "free_thresh": 0.25}, sort_keys=True).encode("utf-8")
    image, sidecar = maps / f"{stem}.pgm", maps / f"{stem}.yaml"
    same = image.is_file() and sidecar.is_file() and _sha(image.read_bytes()) == _sha(pgm) and sidecar.read_bytes() == description
    if not same:
        if stem == live:
            raise ValueError("wall map refused: the running navigation uses this name; stage a new version")
        _atomic(image, pgm, 0o644)  # a pointer-less pair is harmless until the pointer names it
        _atomic(sidecar, description, 0o644)
    old = _read(root, f"{MAPS}/{POINTER}", {})
    _write(root, f"{MAPS}/{POINTER}", {"yaml": f"/{MAPS}/{stem}.yaml", "stem": stem, "sha256": meta["sha256"],
                                       "map_id": map_id, "version": version, "previous_stem": old.get("stem")})
    keep = {stem, old.get("stem"), live}
    for path in maps.glob("wall_*"):
        if path.stem not in keep and path.suffix in (".pgm", ".yaml"):
            path.unlink(missing_ok=True)
    return {"staged": stem}


def _wall_map(root):
    """The staged map, re-verified now: pointer, loadable pair and the image still matching its sha256."""
    pointer = _read(root, f"{MAPS}/{POINTER}", None)
    try:
        yaml_path = root / MAPS / f"{pointer['stem']}.yaml"
        pgm = (root / MAPS / f"{pointer['stem']}.pgm").read_bytes()
        if _sha(pgm) != pointer["sha256"] or not _loadable(yaml_path):
            raise ValueError
        _pgm_cells(pgm)
    except (OSError, KeyError, TypeError, ValueError) as exc:
        raise ValueError("no loadable wall map with a matching sha256 is staged") from exc
    return pointer


def _require_stopped(root, ops):
    """CORE's own evidence: no goal, velocity zero for ZERO_S, written this boot within EVIDENCE_FRESH_S on the shared
    monotonic clock. A missing, foreign, symlinked or oversized file is moving. Odometry is the only velocity source:
    wheel slip is not covered."""
    try:
        seen = json.loads(_core_bytes(root, STOP_EVIDENCE, EVIDENCE_MAX))
        written, zero_since, now = float(seen["written_at"]), seen["zero_since"], ops.now()
        stopped = (seen["boot_id"] == ops.boot_id() and seen["goal_active"] is False and zero_since is not None
                   and written - float(zero_since) >= ZERO_S and 0 <= now - written <= EVIDENCE_FRESH_S)
    except (OSError, KeyError, TypeError, ValueError):
        stopped = False
    if not stopped:
        raise ValueError("the robot is not confirmed stopped: zero velocity for 2 s and no goal are required")


def _gate(root, ops):
    state = _state(root)
    if state.get("attempt_boot_id") == ops.boot_id():
        raise ValueError("a fallback switch was already attempted in this boot")
    if approval._value(approval._env(root), "ROSY_NAVIGATION_BACKEND") != "slam":
        raise ValueError("the navigation backend is not slam: nothing to fall back from, and never back to slam")
    _require_stopped(root, ops)
    return _wall_map(root)


def request_switch(root, ops, reason):
    """Host Agent entry: every refusal is decided here, before a unit is spawned."""
    if not _REASON.match(str(reason)):
        raise ValueError("the reason is not an identifier")
    if _busy(root, ops):
        raise ValueError("a fallback switch is already running")
    _gate(root, ops)
    previous = _state(root)
    _write(root, STATE, {**previous, "phase": "SWITCHING", "reason": reason, "requested_at": ops.wall(),
                         "requested_boot_id": ops.boot_id()}, 0o600)
    result = ops.spawn("switch", reason)
    if result.returncode:
        _write(root, STATE, previous, 0o600)
        raise ValueError(f"transition could not start: {result.stderr.strip()[:200]}")
    return status(root, ops)


def switch(root, ops, reason):
    """The transient unit: re-check everything (the world moved while it started), commit, restart, roll back on failure."""
    requested = _state(root).get("requested_at")
    try:
        pointer = _gate(root, ops)
    except ValueError as exc:  # the attempt counts: CORE has marked it too
        _write(root, STATE, {"phase": "REFUSED", "reason": str(exc)[:300], "attempt_boot_id": ops.boot_id()}, 0o600)
        return
    live = approval._env(root)
    _atomic(root / RUNTIME_BACKUP, live, 0o600)  # the state file never holds runtime.env itself
    state = {"phase": "SWITCHING", "reason": reason, "attempt_boot_id": ops.boot_id(), "previous_sha256": _sha(live),
             "wall_map": pointer["stem"], "wall_map_sha256": pointer["sha256"], "requested_at": requested}
    _write(root, STATE, state, 0o600)  # the attempt counts from here, whatever happens next
    try:
        new = approval._with_values(live, {"ROSY_NAVIGATION_BACKEND": "localization", "ROSY_MAP": pointer["yaml"],
                                          "ROSY_ENABLE_LOC_ASSIST": "true"})
        ops.commit(root, new, live)
        approval._check(ops, "systemctl", "restart", NAVIGATION)
        _wait_active(ops)
    except Exception as exc:  # noqa: BLE001 - every failure returns the robot to the runtime it came from
        _rollback(root, ops, state, exc)
        return
    _write(root, STATE, {**state, "phase": "SWITCHED"}, 0o600)
    (root / RUNTIME_BACKUP).unlink(missing_ok=True)


def _wait_active(ops):
    deadline = ops.now() + SETTLE_S
    while ops.now() < deadline:
        if ops.active(NAVIGATION):
            return
        ops.sleep(1.0)
    raise ValueError("rosy-navigation did not become active on the wall map")


def _rollback(root, ops, state, exc):
    reason = str(exc)[:300]
    try:
        previous = (root / RUNTIME_BACKUP).read_bytes()
        if _sha(previous) != state["previous_sha256"]:
            raise ValueError("the saved runtime.env does not match its hash")
        live = approval._env(root)
        if live != previous:
            ops.commit(root, previous, live)
        approval._check(ops, "systemctl", "restart", NAVIGATION)
    except Exception as restore:  # noqa: BLE001 - a person must see that the robot did not come back
        _write(root, STATE, {**state, "phase": "FAILED", "reason": f"{reason}; rollback failed: {str(restore)[:200]}"}, 0o600)
        return
    _write(root, STATE, {**state, "phase": "ROLLED_BACK", "reason": reason}, 0o600)
    (root / RUNTIME_BACKUP).unlink(missing_ok=True)


def status(root, ops):
    state = _state(root)
    phase, reason = state.get("phase", "IDLE"), state.get("reason", "")
    if _stuck(state, ops):
        phase, reason = "FAILED", "the switch unit ended without a result"  # another boot, or the unit died
    try:
        staged = _wall_map(root)
        wall_map = {"stem": staged["stem"], "map_id": staged["map_id"], "version": staged["version"], "sha256": staged["sha256"]}
    except ValueError:
        wall_map = None
    backend = approval._value(approval._env(root), "ROSY_NAVIGATION_BACKEND")
    return {"phase": phase, "reason": reason, "backend": backend, "wall_map": wall_map,
            "attempted_this_boot": state.get("attempt_boot_id") == ops.boot_id()}


def reset(root):
    """A person's reset (root CLI only; no Host Agent command reaches it)."""
    _write(root, STATE, {"phase": "IDLE", "reason": "reset"}, 0o600)
    (root / RUNTIME_BACKUP).unlink(missing_ok=True)


def run_action(root, ops, action, *arguments):
    """Host Agent entry: stage / status are synchronous, switch spawns a unit."""
    return {"stage": stage, "status": status, "switch": request_switch}[action](root, ops, *arguments)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=Path("/"))
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("reset")
    run = commands.add_parser("run")
    run.add_argument("action", choices=("switch",))
    run.add_argument("arguments", nargs="*")
    args = parser.parse_args(argv)
    if args.command == "reset":
        reset(args.root)
    else:
        switch(args.root, SystemOps(), *args.arguments)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
