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
import subprocess
import sys
from pathlib import Path


# The API's own tree, not $OMX: the job API and the $OMX tools tree switch releases separately.
CAMERA_HEAL = 'exec ~/rosy-omx/current-env/bin/python "$0" "$@"'
CAMERA_HEAL_SCRIPT = str(Path(__file__).resolve())


def with_camera_heal(argv: list[str], job: dict, params: dict) -> list[str]:
    """Camera jobs first check their cell config's cameras and run the upkeep camera recovery (no motion)."""
    from cell_job_spec import ENV, job_arms

    if not job.get("camera"):
        return argv
    arms = job_arms(job, params)
    keyed = (("config", arms[0] if len(arms) == 1 else None), ("config_a", "arm_a"), ("config_b", "arm_b"))
    targets = [f"{arm or '-'}={params[key]}" for key, arm in keyed if params.get(key)]
    if not targets:
        return argv
    return ["bash", "-c", ENV + CAMERA_HEAL, CAMERA_HEAL_SCRIPT,
            *[x for t in targets for x in ("--target", t)], "--", *argv]


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


def heal(targets, io=None) -> list[dict]:
    """targets: [(arm or None, cell config path)]. Returns the upkeep rows, one per config."""
    from cell_upkeep import Io
    from cell_upkeep_checks import bus_owner, check_cameras

    io = io or Io()
    rows = []
    for arm, config in targets:
        cameras = json.loads(Path(config).read_text(encoding="utf-8")).get("cameras") or {}
        owner = bus_owner(arm, io) if arm else None
        found, _top = check_cameras(arm or "cell", cameras, io, fix=True, bus_free=owner is None)
        if any(r.get("status") == "fail" for r in found) and owner is None:
            notes = [hub_cycle(role, io) for role in _dead_roles(cameras, io)]
            if notes:
                found, _top = check_cameras(arm or "cell", cameras, io, fix=False, bus_free=False)
                found = [{**r, "escalation": notes} for r in found]
        rows += [{**r, "arm": arm, "config": str(config)} for r in found]
    return rows


ARMS = ("arm_a", "arm_b", "arm_s")
SUDO_CYCLE = ("import sys; sys.path.insert(0, sys.argv[1]); from pathlib import Path; import cell_usb_recovery as u; "
              "print(u.hub_port_power_and_reset(Path(sys.argv[2]), int(sys.argv[3]), off_s=3.0))")


def _usb(path: Path) -> Path:
    while not (path / "idVendor").exists():
        if path.parent == path:
            raise OSError(f"no USB device above {path}")
        path = path.parent
    return path


def _is_hub(path: Path) -> bool:
    return (path / "bDeviceClass").exists() and (path / "bDeviceClass").read_text().strip() == "09"


def camera_hub_port(device: str) -> tuple[Path, int, Path]:
    """(upstream hub, its port number, camera's own hub) for the camera behind a /dev/v4l/by-id name.
    Root-hub ports are refused: cycling one drops every device on that controller port."""
    node = Path(device).resolve(strict=True).name
    leaf = _usb(Path(f"/sys/class/video4linux/{node}/device").resolve(strict=True))
    hub = leaf.parent
    if not (_is_hub(hub) and _is_hub(hub.parent) and "." in hub.name):
        raise OSError(f"{leaf.name}: no external hub port above the camera to cycle")
    return hub.parent, int(hub.name.rsplit(".", 1)[1]), hub


def _cycle_hub_port(upstream: Path, port: int) -> None:
    node = f"/dev/bus/usb/{int((upstream / 'busnum').read_text()):03d}/{int((upstream / 'devnum').read_text()):03d}"
    subprocess.run(["sudo", "-n", "/usr/bin/python3", "-c", SUDO_CYCLE, str(Path(__file__).resolve().parent), node, str(port)],
                   check=True, capture_output=True, text=True, timeout=30)


def hub_cycle(role: str, io, *, find=camera_hub_port, cycle=_cycle_hub_port, sleep=None) -> str:
    """Escalation after the leaf re-authorisation failed (2026-11-26: arm_b wrist UVC -71 came back only after its
    hub port was power-cycled). The hub also feeds an OpenRB, so it runs only while no arm session exists and every
    arm lock is free: without a session the observer keeps torque OFF, so a board reset moves nothing."""
    import time

    device = io.device(role)
    if not device:
        return f"no registry device for {role}"
    owners = list(io.sessions()) + [f"{arm} lock held" for arm in ARMS if not io.lock_free(arm)]
    if owners:  # shortcut: any session blocks, even on another hub; map board serials to arms when this bites
        return f"hub cycle for {role} skipped: an arm session is live ({owners[0][:80]})"
    try:
        upstream, port, hub = find(device)
        cycle(upstream, port)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        return f"hub cycle for {role} failed: {exc}"
    (sleep or time.sleep)(8)
    io.unit_restart(role)
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
    rows = heal_fn(args.target)
    print(json.dumps({"camera_preflight": rows}), flush=True)
    failed = [r for r in rows if r.get("status") == "fail"]
    if failed:
        print("REFUSED: cameras not ready after automatic recovery: " + "; ".join(r["detail"] for r in failed), flush=True)
        return 3
    exec_fn(command[0], command)
    return 0  # exec_fn replaced the process; reached only with a test seam


if __name__ == "__main__":
    raise SystemExit(main())
