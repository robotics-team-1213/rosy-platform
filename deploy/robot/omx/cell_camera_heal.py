"""Before a camera job runs: every camera its cell config names answers, or the upkeep camera recovery runs.

No arm motion. Recovery is `cell_upkeep_checks.check_cameras(fix=True)`: restart the camera unit, then
`cell_upkeep.usb_recover` (a port shared with an OpenRB board only gets its camera leaf re-authorised).
It is skipped while that arm's bus is owned, exactly as the 30-min upkeep does.

  cell_camera_heal.py --target ARM=CONFIG [--target ...] -- <job argv...>
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path


# The API's own tree, not $OMX: the job API and the $OMX tools tree switch releases separately.
CAMERA_HEAL = 'exec ~/rosy-omx/current-env/bin/python "$0" "$@"'
CAMERA_HEAL_SCRIPT = str(Path(__file__).resolve())


def with_camera_heal(argv: list[str], job: dict, params: dict) -> list[str]:
    """Camera jobs first check their cell config's cameras and run the upkeep camera recovery (no motion)."""
    from cell_job_spec import ENV, job_arms

    if not job.get("camera"):
        return argv
    if job.get("attach_live_hold") or job.get("recovery_home"):  # folding a held arm / incident home must not wait on a camera
        return argv
    arms = job_arms(job, params)
    keyed = (("config", arms[0] if len(arms) == 1 else None), ("config_a", "arm_a"), ("config_b", "arm_b"))
    targets = [f"{arm or '-'}={params[key]}" for key, arm in keyed if params.get(key)]
    if not targets:
        return argv
    return ["bash", "-c", ENV + CAMERA_HEAL, CAMERA_HEAL_SCRIPT,
            *[f"--target={t}" for t in targets], "--", *argv]


def _dead_roles(cameras: dict, io) -> list[str]:
    """Camera roles whose configured frame still does not answer with a JPEG."""
    labels, roles, dead = io.labels(), io.roles(), []
    for camera in cameras.values():
        code, body = io.fetch(camera["url"])
        if code == 200 and body.startswith(b"\xff\xd8") or camera.get("optional"):
            continue
        role = roles.get(labels.get(Path(camera["url"]).stem))
        if role and role not in dead:
            dead.append(role)
    return dead


HEAL_BUDGET_S = 300.0  # shortcut: checked between steps, not inside one (each step has its own timeouts)


def _arm_configs(targets) -> dict:
    """arm -> cell config path, from the arm named in the target or the config's own arm_id."""
    found = {}
    for arm, config in targets:
        try:
            arm = arm or json.loads(Path(config).read_text(encoding="utf-8")).get("arm_id")
        except (OSError, ValueError):
            continue
        if arm:
            found.setdefault(arm, config)
    return found


def heal(targets, io=None, *, budget_s=HEAL_BUDGET_S, clock=time.monotonic) -> list[dict]:
    """targets: [(arm or None, cell config path)]. Returns the upkeep rows, one per config; a config reached after
    the time budget is spent comes back as a failed row without touching anything."""
    from cell_upkeep import Io
    from cell_upkeep_checks import bus_owner, check_cameras

    io = io or Io()
    rows, deadline, configs = [], clock() + budget_s, _arm_configs(targets)
    at_rest = lambda role: arm_at_rest(role, configs)
    for arm, config in targets:
        if clock() > deadline:
            rows.append({"check": "cameras", "status": "fail", "arm": arm, "config": str(config),
                         "detail": f"camera preflight ran past its {budget_s:.0f} s budget before this config"})
            continue
        cameras = json.loads(Path(config).read_text(encoding="utf-8")).get("cameras") or {}
        owner = bus_owner(arm, io) if arm else None
        found, _top = check_cameras(arm or "cell", cameras, io, fix=True, bus_free=owner is None)
        if any(r.get("status") == "fail" for r in found) and owner is None:
            notes = [hub_cycle(role, io, at_rest=at_rest) for role in _dead_roles(cameras, io)]
            if notes:
                found, _top = check_cameras(arm or "cell", cameras, io, fix=False, bus_free=False)
                found = [{**r, "escalation": notes} for r in found]
        rows += [{**r, "arm": arm, "config": str(config)} for r in found]
    return rows


ARMS = ("arm_a", "arm_b", "arm_s")
# Root-owned, self-contained (it must not import from the user-writable release tree); see install-hub-cycle.sh.
HUB_CYCLE_HELPER = "/usr/local/sbin/rosy-omx-hub-cycle"


def _usb(path: Path) -> Path:
    while not (path / "idVendor").exists():
        if path.parent == path:
            raise OSError(f"no USB device above {path}")
        path = path.parent
    return path


def _is_hub(path: Path) -> bool:
    return (path / "bDeviceClass").exists() and (path / "bDeviceClass").read_text().strip() == "09"


def _camera_leaf(device: str, role: str | None, leaf_finder) -> Path:
    """USB device of the camera: through its by-id link while it is configured, else (UVC -71 'can't set config',
    by-id and video4linux gone) the unconfigured leaf that shares its hub only with this arm's OpenRB."""
    try:
        node = Path(device).resolve(strict=True).name
        return _usb(Path(f"/sys/class/video4linux/{node}/device").resolve(strict=True))
    except OSError:
        found = leaf_finder(role) if role else None
        if not found or not found.get("leaf"):
            raise OSError(f"{device}: camera is gone and no unique unconfigured leaf matches {role}") from None
        return Path(found["leaf"])


OPENRB_VENDOR = "2f5d"
ARM_BOARDS = Path("/etc/rosy/omx-arm-boards.json")
_USB_NAME = re.compile(r"\d+-[\d.]+")


def _read(path: Path) -> str:
    try:
        return path.read_text().strip()
    except OSError:
        return ""


def _usb_children(path: Path):
    for child in sorted(path.iterdir()):
        if child.is_dir() and not child.is_symlink() and _USB_NAME.fullmatch(child.name):
            yield child
            yield from _usb_children(child)


def hub_subtree_refusal(hub: Path, leaf: Path, role: str | None, boards_path: Path = ARM_BOARDS) -> str | None:
    """Cycling the port that feeds `hub` drops every USB device below it. Allowed only when that is the camera
    itself (and hubs) plus OpenRB boards registered to the camera's own arm: no other camera, D435, U2D2 or board."""
    m = re.fullmatch(r"(arm_[a-z])_.+", role or "")
    arm = m.group(1) if m else None
    try:
        raw = json.loads(boards_path.read_text(encoding="utf-8"))
        boards = {str(k): str(v) for k, v in raw.items()} if isinstance(raw, dict) else None
    except (OSError, ValueError):
        boards = None
    for dev in _usb_children(hub):
        if dev == leaf or _is_hub(dev):
            continue
        ids = f"{_read(dev / 'idVendor')}:{_read(dev / 'idProduct')}"
        if _read(dev / "idVendor").lower() == OPENRB_VENDOR:
            serial = _read(dev / "serial")
            if boards is None:
                return f"{dev.name} ({ids}) is an OpenRB under hub {hub.name} and {boards_path} is unreadable"
            if arm is None or boards.get(serial) != arm:
                return f"{dev.name} ({ids}) is an OpenRB of {boards.get(serial, 'an unknown arm')}, not {arm or role}"
            continue
        return f"{dev.name} ({ids}) would also lose power under hub {hub.name}"
    return None


def camera_hub_port(device: str, role: str | None = None, *, leaf_finder=None, boards_path: Path = ARM_BOARDS) -> tuple[Path, int, Path]:
    """(upstream hub, its port number, camera's own hub) for the camera behind a /dev/v4l/by-id name.
    Root-hub ports are refused: cycling one drops every device on that controller port. So is any hub that also
    feeds something other than this camera and its own arm's OpenRB."""
    if leaf_finder is None:
        from cell_upkeep_usb_leaf import unconfigured_usb_leaf as leaf_finder
    leaf = _camera_leaf(device, role, leaf_finder)
    hub = leaf.parent
    if not (_is_hub(hub) and _is_hub(hub.parent) and "." in hub.name):
        raise OSError(f"{leaf.name}: no external hub port above the camera to cycle")
    if refusal := hub_subtree_refusal(hub, leaf, role, boards_path):
        raise OSError(refusal)
    return hub.parent, int(hub.name.rsplit(".", 1)[1]), hub


def _cycle_hub_port(upstream: Path, port: int) -> None:
    try:
        subprocess.run(["sudo", "-n", HUB_CYCLE_HELPER, upstream.name, str(port)],
                       check=True, capture_output=True, text=True, timeout=30)
    except subprocess.CalledProcessError as exc:  # keep the helper's own reason (no sudoers line, refused argument)
        raise OSError(f"{HUB_CYCLE_HELPER} exited {exc.returncode}: {(exc.stderr or '').strip()[:200]}") from None


def arm_at_rest(role: str, configs: dict | None = None, *, reassess=None) -> str | None:
    """Refusal text unless the camera's own arm stands folded with every motor torque OFF, read twice under its arm
    lock (omx_incident_reassess, no camera views: this camera is the dead one). The hub also feeds that arm's OpenRB, so
    a board reset must not be able to drop a loaded or unfolded arm. A camera of no arm shares its hub with no board."""
    match = re.fullmatch(r"(arm_[a-z])_.+", role)
    if not match:
        return None
    arm = match.group(1)
    config = (configs or {}).get(arm)
    if not config:
        return f"{arm} is not confirmed folded with torque OFF: no cell config for it among the targets"
    if reassess is None:
        from omx_incident_reassess import reassess
    try:
        block = reassess(arm, config, held=False, with_frames=False)
    except (SystemExit, Exception) as exc:  # SystemExit: lease or session held, no board, no calibration
        return f"{arm} is not confirmed folded with torque OFF: {exc}"
    if any(block["torque_after"].values()):
        return f"{arm} has a motor with torque ON"
    if not (block["folded"] and block["stable"]):
        return f"{arm} is not folded and still (max home error {block['max_home_err']})"
    return None


def _cell_lock():
    """The whole-cell session.lock, exclusive: arm sessions (shared), observer restarts and new API jobs all wait on it."""
    from joint_tune_lock import session_lock

    return session_lock()


def hub_cycle(role: str, io, *, find=None, cycle=_cycle_hub_port, sleep=None, cell_lock=_cell_lock, at_rest=None) -> str:
    """Escalation after the leaf re-authorisation failed (2026-11-26: arm_b wrist UVC -71 came back only after its
    hub port was power-cycled). The hub also feeds an OpenRB, so it runs only while no arm session exists and every
    arm lock is free: without a session the observer keeps torque OFF, so a board reset moves nothing. The whole-cell
    lock is held exclusively from that check until the camera unit is back, so no session, observer restart or API job
    can start on the hub while it is down."""
    import time

    device = io.device(role)
    if not device:
        return f"no registry device for {role}"
    owners = list(io.sessions()) + [f"{arm} lock held" for arm in ARMS if not io.lock_free(arm)]
    if owners:  # shortcut: any session blocks, even on another hub; map board serials to arms when this bites
        return f"hub cycle for {role} skipped: an arm session is live ({owners[0][:80]})"
    try:  # read-only: what the port feeds, and whether that arm stands folded with torque OFF (needs its arm lock)
        upstream, port, hub = find(device) if find else camera_hub_port(device, role)
    except (OSError, ValueError) as exc:
        return f"hub cycle for {role} failed: {exc}"
    if refusal := (at_rest or arm_at_rest)(role):  # shortcut: checked just before the cell lock; a session in between holds it shared
        return f"hub cycle for {role} refused: {refusal}"
    try:  # checked above, held from here: a session that started since holds the cell lock shared, so this fails
        held = cell_lock()
    except SystemExit as exc:
        return f"hub cycle for {role} skipped: {exc}"
    try:
        try:
            cycle(upstream, port)
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            return f"hub cycle for {role} failed: {exc}"
        (sleep or time.sleep)(8)
        io.unit_restart(role)
    finally:
        held.close()  # before the job's own session wrapper asks for its arm lock
    return f"power-cycled hub {hub.name} (port {port} of {upstream.name}) for {role}"


def _target(text: str):
    arm, sep, config = text.partition("=")
    if not sep or not config:
        raise argparse.ArgumentTypeError("--target is ARM=CONFIG (ARM may be '-')")
    return (None if arm in ("", "-") else arm), config


def main(argv=None, *, heal_fn=heal, exec_fn=os.execvp) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--" not in argv:
        print("REFUSED: cell_camera_heal needs '-- <job argv>'")
        return 2
    cut = argv.index("--")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--target", type=_target, action="append", required=True)
    args, command = ap.parse_args(argv[:cut]), argv[cut + 1:]
    if not command:
        print("REFUSED: no job command after '--'")
        return 2
    try:
        rows = heal_fn(args.target)
    except Exception as exc:  # the refusal JSON must exist whatever broke
        rows = [{"check": "cameras", "status": "fail", "detail": f"camera preflight crashed: {exc!r}"}]
    print(json.dumps({"camera_preflight": rows}), flush=True)
    failed = [r for r in rows if r.get("status") == "fail"]
    if failed:
        print("REFUSED: cameras not ready after automatic recovery: " + "; ".join(r["detail"] for r in failed), flush=True)
        return 3
    exec_fn(command[0], command)
    return 0  # exec_fn replaced the process; reached only with a test seam


if __name__ == "__main__":
    raise SystemExit(main())
