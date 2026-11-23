#!/usr/bin/env python3
"""Site map staging and safe localization-mode activation host half (2026-11-23).

Reached only through Host Agent (`site_map.{status,stage,activate}`). Keeps `/var/lib/rosy/maps/site.yaml`
untouched and writes versioned `site_<map_id>_v<n>.{pgm,yaml,manifest.json}` before updating runtime.env via
`commit_runtime` after proving zero velocity >= ZERO_S and no active goal from CORE's own evidence file.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys
import time

import navigation_approval_host as approval
import navigation_fallback_host as fb
import yaml

STATE = "var/lib/rosy/commissioning/site-map-exchange.json"
RUNTIME_BACKUP = "var/lib/rosy/commissioning/site-map-runtime.bak"
SPOOL = f"{fb.CORE_DIR}/site-map-spool"
SPOOL_IMAGE, SPOOL_META = "site-map.pgm", "meta.json"
STOP_EVIDENCE = f"{fb.CORE_DIR}/site-map-stop.json"
MAPS = fb.MAPS
POINTER = "site-map-active.json"
RUNTIME = approval.RUNTIME
UNIT = "rosy-site-map-activate"
NAVIGATION = fb.NAVIGATION
RESOLUTION = (0.005, 0.2)
ORIGIN_LIMIT = fb.ORIGIN_LIMIT
MAX_CELLS = fb.MAX_CELLS


class SystemOps(approval.SystemOps):
    """Host Agent privileged ops for site-map activation."""

    def spawn(self, action, *arguments):
        return self.run(
            "systemd-run", f"--unit={UNIT}", "--collect", "--no-block",
            "--setenv=PYTHONNOUSERSITE=1", "--setenv=PYTHONDONTWRITEBYTECODE=1",
            sys.executable, "-B", str(Path(__file__).resolve()), "run", action, "--", *arguments,
        )

    def sleep(self, seconds):
        time.sleep(seconds)

    def wall(self):
        return time.time()


def _site_state(root):
    return fb._read(root, STATE, {"phase": "IDLE"})


def _site_stuck(state, ops):
    if state.get("phase") != "ACTIVATING":
        return False
    boot = state.get("attempt_boot_id") or state.get("requested_boot_id")
    if boot is not None and boot != ops.boot_id():
        return True
    return ops.wall() - (state.get("requested_at") or 0) > fb.UNIT_START_S and not ops.active(f"{UNIT}.service")


def _site_busy(root, ops):
    st = _site_state(root)
    return st.get("phase") == "ACTIVATING" and not _site_stuck(st, ops)


def _valid_site_params(resolution: float, origin: list[float], occ_t: float, free_t: float) -> bool:
    return (
        math.isfinite(resolution) and RESOLUTION[0] <= resolution <= RESOLUTION[1]
        and len(origin) == 3 and all(math.isfinite(v) and abs(v) <= ORIGIN_LIMIT for v in origin)
        and abs(origin[2]) <= 1e-6
        and math.isfinite(free_t) and math.isfinite(occ_t)
        and 0.01 <= free_t <= 0.196 and 0.65 <= occ_t <= 0.99 and free_t < occ_t
    )


def _staged_site_map(root):
    pointer = fb._read(root, f"{MAPS}/{POINTER}", None)
    try:
        yaml_path = root / MAPS / f"{pointer['stem']}.yaml"
        pgm = (root / MAPS / f"{pointer['stem']}.pgm").read_bytes()
        data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
        resolution = float(data["resolution"])
        origin = [float(v) for v in data["origin"]]
        occ_t = float(data.get("occupied_thresh", 0.65))
        free_t = float(data.get("free_thresh", 0.196))
        image = yaml_path.parent / data["image"]
        if (
            fb._sha(pgm) != pointer["sha256"]
            or not image.is_file()
            or not _valid_site_params(resolution, origin, occ_t, free_t)
        ):
            raise ValueError
        fb._pgm_cells(pgm)
    except (OSError, KeyError, TypeError, ValueError, yaml.YAMLError) as exc:
        raise ValueError("no loadable site map with matching sha256 is staged") from exc
    return pointer


def _site_require_stopped(root, ops):
    try:
        seen = json.loads(fb._core_bytes(root, STOP_EVIDENCE, fb.EVIDENCE_MAX))
        written, zero_since, now = float(seen["written_at"]), seen["zero_since"], ops.now()
        stopped = (
            seen["boot_id"] == ops.boot_id() and seen["goal_active"] is False and zero_since is not None
            and written - float(zero_since) >= fb.ZERO_S and 0 <= now - written <= fb.EVIDENCE_FRESH_S
        )
    except (OSError, KeyError, TypeError, ValueError):
        stopped = False
    if not stopped:
        raise ValueError("the robot is not confirmed stopped: zero velocity for 2 s and no goal are required")


def stage_site_map(root, ops):
    """Install CORE's spooled master site map as site_<id>_v<n>.{pgm,yaml,manifest.json}."""
    if _site_busy(root, ops):
        raise ValueError("a site map activation is running: staged map is not replaced now")
    try:
        meta = json.loads(fb._core_bytes(root, f"{SPOOL}/{SPOOL_META}", fb.META_MAX))
        pgm = fb._core_bytes(root, f"{SPOOL}/{SPOOL_IMAGE}", MAX_CELLS + 64)
        map_id = str(meta["map_id"])
        raw_ver = meta["version"]
        if isinstance(raw_ver, bool) or not isinstance(raw_ver, int):
            raise ValueError("version must be an integer")
        version = int(raw_ver)
        resolution = float(meta["resolution"])
        origin = [float(v) for v in meta["origin"]]
        occ_t = float(meta.get("occupied_thresh", 0.65))
        free_t = float(meta.get("free_thresh", 0.196))
        if not fb._ID.match(map_id) or version < 0 or not _valid_site_params(resolution, origin, occ_t, free_t):
            raise ValueError("the site map description is malformed")
        if fb._sha(pgm) != meta["sha256"]:
            raise ValueError("the site map image does not match its sha256")
        fb._pgm_cells(pgm)
    except (OSError, KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"site map refused: {str(exc)[:200]}") from exc
    stem = f"site_{map_id}_v{version}"
    maps = root / MAPS
    maps.mkdir(parents=True, exist_ok=True)
    named = approval._value(approval._env(root), "ROSY_MAP")
    live = Path(named).stem if named else None
    description = yaml.safe_dump(
        {"image": f"{stem}.pgm", "mode": "trinary", "resolution": resolution, "origin": origin,
         "negate": 0, "occupied_thresh": occ_t, "free_thresh": free_t},
        sort_keys=True,
    ).encode("utf-8")
    manifest = {
        "name": stem, "map_id": map_id, "version": version, "resolution": resolution, "origin": origin,
        "pgm_sha256": meta["sha256"], "grid_id": meta.get("grid_id"), "site_map_id": map_id,
        "source": str(meta.get("source") or ""),
    }
    if meta.get("alignment") is not None:
        manifest["alignment"] = meta["alignment"]
    manifest_bytes = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")
    image, sidecar, man_path = maps / f"{stem}.pgm", maps / f"{stem}.yaml", maps / f"{stem}.manifest.json"
    same = (image.is_file() and sidecar.is_file() and fb._sha(image.read_bytes()) == meta["sha256"]
            and sidecar.read_bytes() == description)
    if not same:
        if stem == live:
            raise ValueError("site map refused: the running navigation uses this name; stage a new version")
        fb._atomic(image, pgm, 0o644)
        fb._atomic(sidecar, description, 0o644)
    fb._atomic(man_path, manifest_bytes, 0o644)
    old = fb._read(root, f"{MAPS}/{POINTER}", {})
    fb._write(root, f"{MAPS}/{POINTER}", {
        "yaml": f"/{MAPS}/{stem}.yaml", "stem": stem, "sha256": meta["sha256"],
        "map_id": map_id, "version": version, "grid_id": meta.get("grid_id"),
        "previous_stem": old.get("stem"),
    })
    keep = {stem, old.get("stem"), live}
    for path in maps.glob("site_*"):
        base = path.name[:-len(".manifest.json")] if path.name.endswith(".manifest.json") else path.stem
        if base not in keep and path.name != POINTER and (path.suffix in (".pgm", ".yaml") or path.name.endswith(".manifest.json")):
            path.unlink(missing_ok=True)
    return {
        "staged": stem, "yaml": f"/{MAPS}/{stem}.yaml", "map_id": map_id,
        "version": version, "sha256": meta["sha256"], "grid_id": meta.get("grid_id"),
    }


def _require_hardware_mode(root):
    if approval._value(approval._env(root), "ROSY_RUNTIME_MODE") != "hardware":
        raise ValueError("site map activation requires ROSY_RUNTIME_MODE=hardware")


def request_activate(root, ops):
    """Host Agent synchronous entry for site_map.activate."""
    if _site_busy(root, ops):
        raise ValueError("a site map activation is already running")
    _require_hardware_mode(root)
    _site_require_stopped(root, ops)
    pointer = _staged_site_map(root)
    previous = _site_state(root)
    fb._write(root, STATE, {
        **previous, "phase": "ACTIVATING", "site_map": pointer["stem"],
        "site_map_sha256": pointer["sha256"], "requested_at": ops.wall(), "requested_boot_id": ops.boot_id(),
    }, 0o600)
    result = ops.spawn("activate")
    if result.returncode:
        fb._write(root, STATE, previous, 0o600)
        raise ValueError(f"activation could not start: {result.stderr.strip()[:200]}")
    return site_map_status(root, ops)


def _site_rollback(root, ops, state, exc):
    reason = str(exc)[:300]
    try:
        previous = (root / RUNTIME_BACKUP).read_bytes()
        if fb._sha(previous) != state["previous_sha256"]:
            raise ValueError("the saved runtime.env does not match its hash")
        live = approval._env(root)
        if live != previous:
            ops.commit(root, previous, live)
        approval._check(ops, "systemctl", "restart", NAVIGATION)
        fb._wait_active(ops)
    except Exception as restore:  # noqa: BLE001
        fb._write(root, STATE, {**state, "phase": "FAILED", "reason": f"{reason}; rollback failed: {str(restore)[:200]}"}, 0o600)
        return
    fb._write(root, STATE, {**state, "phase": "ROLLED_BACK", "reason": reason}, 0o600)
    (root / RUNTIME_BACKUP).unlink(missing_ok=True)


def activate_site_map(root, ops):
    """Transient worker: re-verify stop & staged map, update runtime.env, restart navigation, roll back on fail."""
    requested = _site_state(root).get("requested_at")
    try:
        _require_hardware_mode(root)
        _site_require_stopped(root, ops)
        pointer = _staged_site_map(root)
    except ValueError as exc:
        fb._write(root, STATE, {"phase": "REFUSED", "reason": str(exc)[:300], "attempt_boot_id": ops.boot_id()}, 0o600)
        return
    live = approval._env(root)
    fb._atomic(root / RUNTIME_BACKUP, live, 0o600)
    state = {
        "phase": "ACTIVATING", "reason": "", "attempt_boot_id": ops.boot_id(), "previous_sha256": fb._sha(live),
        "site_map": pointer["stem"], "site_map_sha256": pointer["sha256"], "requested_at": requested,
    }
    fb._write(root, STATE, state, 0o600)
    try:
        new = approval._with_values(live, {
            "ROSY_NAVIGATION_BACKEND": "localization",
            "ROSY_MAP": pointer["yaml"],
            "ROSY_ENABLE_LOC_ASSIST": "true",
        })
        ops.commit(root, new, live)
        approval._check(ops, "systemctl", "restart", NAVIGATION)
        fb._wait_active(ops)
    except Exception as exc:  # noqa: BLE001
        _site_rollback(root, ops, state, exc)
        return
    fb._write(root, STATE, {**state, "phase": "ACTIVE"}, 0o600)
    (root / RUNTIME_BACKUP).unlink(missing_ok=True)


def site_map_status(root, ops):
    st = _site_state(root)
    phase, reason = st.get("phase", "IDLE"), st.get("reason", "")
    if _site_stuck(st, ops):
        phase, reason = "FAILED", "the activation unit ended without a result"
    try:
        staged = _staged_site_map(root)
        active = {"stem": staged["stem"], "yaml": staged["yaml"], "map_id": staged["map_id"],
                  "version": staged["version"], "sha256": staged["sha256"], "grid_id": staged.get("grid_id")}
    except ValueError:
        active = None
    env = approval._env(root)
    return {
        "phase": phase, "reason": reason,
        "backend": approval._value(env, "ROSY_NAVIGATION_BACKEND"),
        "map": approval._value(env, "ROSY_MAP"),
        "staged": active,
    }


def run_action(root, ops, action):
    return {"status": site_map_status, "stage": stage_site_map, "activate": request_activate}[action](root, ops)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=Path("/"))
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run")
    run.add_argument("action", choices=("activate",))
    run.add_argument("arguments", nargs="*")
    args = parser.parse_args(argv)
    if args.command == "run":
        activate_site_map(args.root, SystemOps())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
