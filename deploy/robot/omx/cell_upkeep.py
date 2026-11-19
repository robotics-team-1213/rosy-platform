#!/usr/bin/env python3
"""One upkeep pass over every arm of the OMX cell: what went wrong by hand on 2026-11-03/04, as checks.

  cell_upkeep.py upkeep-arms.json [--fix] [--out upkeep] [--incidents DIR] [--since EPOCH]

The manifest maps an arm name to {"cell": <cell config>, "record": <record config>, "chunks": <chunk library>}
(paths relative to the manifest). Per arm, in this order: held (HOLD-<arm>.json in omx_incident's incidents directory), boards (record config
robot.port / teleop.port exist), bus ownership (no record_session.py for the arm, per-arm lock free), follower
registers (torque 0, no hardware error, caps at the commissioning baseline), cameras (200 + JPEG, top light gate),
jaw closed value against the latest motor-health log, the jaw opening against the newest session trace, the calibration map (read-only cell_calibrate.check), the
after-session monitors (push_replay, jitter_replay) over the logs newer than the previous report, and the planning TCP.

No motion, ever. With --fix, `commissioning_limits.py --baseline` writes only when every follower
motor reads torque 0 with no hardware error and nothing owns the bus; camera recovery may cycle board-free USB ports.
A latched hardware error is reported, not
rebooted (omx_incident.py owns that). Each arm's report goes to <out>/<stamp>-<arm>.json; exit 0 only when every arm is ready.
Verdicts: ready | needs_motion_step (only the supervised cell_calibrate steps are left) | needs_person.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cell_params as prm  # noqa: E402
import cell_preflight  # noqa: E402
from cell_upkeep_checks import (  # noqa: E402
    BAD,
    TCP_STOCK,
    bus_owner,
    check_boards,
    check_cameras,
    check_hold,
    check_jaw_open,
    check_jaws,
    check_light,
    check_map,
    check_monitors,
    check_registers,
    check_tcp,
    grip_units,
    row,
    serial_tail,
)


# ---- hardware seams: the defaults touch the machine, tests pass fakes -------------------------------------------

def fetch_url(url):
    """(HTTP status, body); status 0 when nothing answers."""
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, b""
    except OSError:
        return 0, b""


def decode_frame(body, gray=False):
    import cv2
    import numpy as np

    return cv2.imdecode(np.frombuffer(body, np.uint8), cv2.IMREAD_GRAYSCALE if gray else cv2.IMREAD_COLOR)


def bus_read(device):
    from register_probe import open_readonly_port, read_motors

    with open_readonly_port(device) as port:
        return read_motors(port, allow_fault=True)


def bus_fix(device, out):
    import commissioning_limits

    out.parent.mkdir(parents=True, exist_ok=True)
    return commissioning_limits.main(["--device", str(device), "--baseline", "--output", str(out)]) == 0


def viewer_labels() -> dict:
    """label -> topic the camera viewer serves at /frame/<label>.jpg (omx-camera-view.env ROSY_VIEW_ARGS)."""
    env = Path.home() / ".config/rosy/omx-camera-view.env"
    return dict(re.findall(r"--camera-topic\s+(\w+)=(\S+?)(?=[\s\"]|$)", env.read_text())) if env.exists() else {}


def camera_roles() -> dict:
    """topic -> registry role (its preview unit is rosy-omx-camera@<role>)."""
    path = Path.home() / ".config/rosy/omx-cameras.json"
    return {c["topic"]: c["role"] for c in json.loads(path.read_text())["cameras"]} if path.exists() else {}


def unit_tail(role) -> str:
    return subprocess.run(["journalctl", "--user", "-u", f"rosy-omx-camera@{role}", "-n", "1", "-o", "cat", "--no-pager"],
                          capture_output=True, text=True).stdout


def unit_restart(role) -> None:
    subprocess.run(["systemctl", "--user", "restart", f"rosy-omx-camera@{role}"], check=True)
    time.sleep(8)  # the preview republishes within a few seconds (2026-11-04)


def camera_device(role):
    """The registry's device name for a preview role (omx-cameras.json), or None."""
    path = Path.home() / ".config/rosy/omx-cameras.json"
    return next((c["device"] for c in json.loads(path.read_text())["cameras"] if c["role"] == role), None) if path.exists() else None


def usb_port(device):
    """Root port of the camera behind a /dev/v4l/by-id name: {"ports": [port, peer], "speed": Mbit/s, "boards": by-id
    serial names below ANY port being cycled}. Raises OSError when sysfs does not show the chain."""
    node = Path(device).resolve(strict=True).name
    dev = Path(f"/sys/class/video4linux/{node}/device").resolve(strict=True)
    while not (dev / "idVendor").exists():
        if dev.parent == dev:
            raise OSError("USB device ancestor is missing")
        dev = dev.parent
    bus, _, path = dev.name.partition("-")
    root = dev
    while root.name != f"{bus}-{path.split('.')[0]}":
        if root.parent == root:
            raise OSError("USB root device ancestor is missing")
        root = root.parent
    port = Path(f"/sys/bus/usb/devices/{bus}-0:1.0/usb{bus}-port{path.split('.')[0]}").resolve(strict=True)
    ports = [port]
    peer = port / "peer"
    if peer.exists() or peer.is_symlink():
        ports.append(peer.resolve(strict=True))
    roots = []
    for powered in ports:
        identity = re.fullmatch(r"usb(\d+)-port(\d+)", powered.name)
        if (not identity or powered.parent.name != f"{identity[1]}-0:1.0"
                or powered.parent.parent.name != f"usb{identity[1]}"):
            raise OSError("USB powered-port identity is missing or inconsistent")
        # An unattached peer has no child device yet, but its port/controller
        # identity still defines the complete subtree whose power is affected.
        roots.append(powered.parent.parent / f"{identity[1]}-{identity[2]}")
    if roots[0] != root:
        raise OSError("USB camera root differs from its powered port")
    if any((p / "disable").read_text().strip() != "0" for p in ports):
        raise OSError(f"USB port or peer is already disabled: {ports}")
    boards = []
    for name in glob.glob("/dev/serial/by-id/*"):
        tty = Path(name).resolve(strict=True).name
        serial_device = Path(f"/sys/class/tty/{tty}/device").resolve(strict=True)
        if any(serial_device.is_relative_to(affected) for affected in roots):
            boards.append(Path(name).name)
    return {"ports": [str(p) for p in ports], "speed": int((dev / "speed").read_text()), "boards": boards}


def frames_flow(device) -> bool:
    """A direct read: v4l2-ctl gets bytes from the node itself, so the service is ruled out."""
    try:
        out = subprocess.run(["v4l2-ctl", "-d", str(device), "--set-fmt-video=width=640,height=480", "--stream-mmap",
                              "--stream-count=3", "--stream-to=-"], capture_output=True, timeout=15)
    except subprocess.TimeoutExpired:
        return False
    return len(out.stdout) > 0


def port_set(ports, disabled) -> None:
    error = None
    for port in ports:
        try:
            subprocess.run(["sudo", "-n", "tee", f"{port}/disable"], input="1" if disabled else "0", text=True,
                           capture_output=True, check=True)
        except (OSError, subprocess.SubprocessError) as failure:
            if disabled:
                raise
            error = error or failure
    if error is not None:
        raise error


def camera_units(role, up) -> None:
    """The bind timer restarts the preview every 20 s, so it goes down first and up last."""
    names = ["rosy-omx-cameras-bind.timer", f"rosy-omx-camera@{role}"]
    subprocess.run(["systemctl", "--user", "start" if up else "stop", *names], check=True)
    if up:
        time.sleep(8)


def sessions():
    """Command lines of every running record_session.py: a `--io chunk-io` one is the runner that owns the bus."""
    text = subprocess.run(["ps", "-eo", "args"], capture_output=True, text=True).stdout
    return [line for line in text.splitlines() if "record_session.py" in line]


def lock_free(arm) -> bool:
    """The cell lock (shared, as an arm session takes it) and the arm's own lock can both be taken now."""
    import fcntl

    from joint_tune import lock_root

    ok = True
    for name, mode in (("session.lock", fcntl.LOCK_SH), (f"session-{arm}.lock", fcntl.LOCK_EX)):
        path = lock_root() / name
        if not path.exists():
            continue
        with path.open("a") as handle:
            try:
                fcntl.flock(handle, mode | fcntl.LOCK_NB)
            except BlockingIOError:
                ok = False
    return ok


def calibrate_check(config, calibration, frame, params):
    import cell_calibrate as cc

    found = cc.check(config, calibration, [], frame, params)
    return {"check": found, "todo": cc.stale(found)}


def replays(health, traces, params):
    import jitter_replay
    import push_replay

    return push_replay.replay(health, params), jitter_replay.replay(traces, health, params)


class Io:
    def __init__(self, **seams):
        self.fetch, self.decode, self.bus_read, self.bus_fix = fetch_url, decode_frame, bus_read, bus_fix
        self.sessions, self.lock_free, self.calibrate, self.replays = sessions, lock_free, calibrate_check, replays
        self.labels, self.roles, self.unit_tail, self.unit_restart = viewer_labels, camera_roles, unit_tail, unit_restart
        self.device, self.usb_port, self.frames, self.ports = camera_device, usb_port, frames_flow, port_set
        self.units, self.sleep = camera_units, time.sleep
        for name, fn in seams.items():
            if not hasattr(self, name):
                raise TypeError(f"unknown seam {name}")
            setattr(self, name, fn)


def usb_recover(role, io):
    """2026-11-05: a D435 came back on a USB2 root port and gave no frames until that port and its peer were off for
    30 s. Only a camera whose direct read yields nothing is cycled, and never a port that also carries an arm board."""
    device = io.device(role)
    if not device:
        return f"no registry device for {role}"
    try:
        port = io.usb_port(device)
    except OSError as e:
        return f"cannot resolve the USB port of {role}: {e}"
    boards = [b for b in port["boards"] if "OpenRB" in b]
    if boards:
        return f"refused to power-cycle the port of {role}: it also carries {', '.join(boards)}"
    io.units(role, False)
    try:
        if io.frames(device):
            return f"{role} streams when read directly (not a USB fault)"
        try:
            io.ports(port["ports"], True)
            io.sleep(30)
        finally:
            io.ports(port["ports"], False)
        for _ in range(9):  # the first read right after re-enable still gave nothing; one a minute later streamed
            io.sleep(10)
            if io.frames(device):
                break
        else:
            return f"power-cycled the USB port of {role} (30 s off) but it still gives no frames"
    finally:
        io.units(role, True)
    speed = io.usb_port(device)["speed"]
    return f"power-cycled the USB port of {role} and its peer (30 s off), frames flow at {speed} Mbit/s" + (
        "; WARN: USB2, the camera needs a USB3 port and cable" if speed < 5000 else "")


# ---- one arm, the run ---------------------------------------------------------------------------------------------

def rel(base, path):
    return str(Path(path).expanduser() if Path(path).expanduser().is_absolute() else base / path)


def previous_report(out_dir, arm):
    times = [p.stat().st_mtime for p in out_dir.glob(f"*-{arm}.json")]
    return max(times, default=0.0)


def upkeep_arm(arm, spec, fix, io, out_dir, incidents, stamp, since=None):
    base = Path(spec.get("_base", "."))
    cell = json.loads(Path(rel(base, spec["cell"])).read_text(encoding="utf-8"))
    record = json.loads(Path(rel(base, spec["record"])).read_text(encoding="utf-8"))
    library = json.loads(Path(rel(base, spec["chunks"])).read_text(encoding="utf-8"))
    cell_dir = Path(rel(base, spec["cell"])).parent
    params = prm.load(rel(cell_dir, cell["params_path"]) if cell.get("params_path") else None)["values"]
    device = (record.get("robot") or {}).get("port") or ""
    checks = [check_hold(arm, incidents), check_boards(record)]
    owner = bus_owner(arm, io)
    if owner:
        checks.append(row("bus ownership", "skipped", owner + "; register checks skipped, wait for the session"))
        checks.append(row("registers", "skipped", "bus is owned"))
    else:
        checks.append(row("bus ownership", "ok", "no record_session.py, lock free"))
        checks.append(check_registers(arm, device, io, fix, out_dir, stamp) if Path(device).exists()
                      else row("registers", "skipped", "follower board missing"))
    cameras, top = check_cameras(arm, cell.get("cameras", {}), io, fix, bus_free=owner is None)
    checks += cameras + [check_light(top, params, io)]
    logs_dir = Path(rel(base, spec["record"])).parent
    closed = {float(library["gripper_closed"])} if library.get("gripper_closed") is not None else set()
    plan_path = cell.get("plan_path")
    if plan_path and Path(plan_path).expanduser().exists():
        closed.add(float(json.loads(Path(plan_path).expanduser().read_text())["grip_closed"]))
    checks.append(check_jaws(arm, device, closed, glob.glob(str(logs_dir / "motor-health-*.jsonl")), params))
    checks.append(check_jaw_open(glob.glob(str(logs_dir / f"trace-{arm}-*.jsonl")), params))
    checks.append(check_map(cell, params, top, io))
    checks.append(check_monitors(arm, device, logs_dir, previous_report(out_dir, arm) if since is None else since, params, io))
    checks.append(check_tcp(cell))
    bad = [c for c in checks if c["status"] in BAD]
    verdict = "ready" if not bad else "needs_motion_step" if all(c.get("motion") for c in bad) else "needs_person"
    return {"arm": arm, "stamp": stamp, "at": time.time(), "verdict": verdict, "fix": fix, "checks": checks}


def run(arms: dict, fix: bool = False, *, io: Io | None = None, out_dir="upkeep", incidents=None, since=None,
        stamp=None) -> dict:
    """{arm: report}; each report is also written to <out_dir>/<stamp>-<arm>.json."""
    io, out_dir, reports = io or Io(), Path(out_dir), {}
    stamp = stamp or time.strftime("%Y%m%dT%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)
    for arm, spec in arms.items():
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", arm):
            raise ValueError(f"arm name {arm!r} is not a plain name")
        reports[arm] = upkeep_arm(arm, spec, fix, io, out_dir, incidents, stamp, since)
        (out_dir / f"{stamp}-{arm}.json").write_text(json.dumps(reports[arm], indent=1, default=str))
    return reports


def summary(reports) -> str:
    lines = []
    for arm, report in reports.items():
        lines.append(f"== {arm}: {report['verdict']}")
        lines += [f"   {c['status']:7s} {c['check']}: {c['detail']}" for c in report["checks"]]
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("manifest", type=Path)
    ap.add_argument("--fix", action="store_true", help="lower raised follower caps (torque 0 everywhere, bus free)")
    ap.add_argument("--out", default="upkeep")
    ap.add_argument("--incidents", default=None, help="default: omx_incident's hold directory")
    ap.add_argument("--since", type=float, help="replay logs newer than this epoch (default: the previous report)")
    args = ap.parse_args(argv)
    arms = json.loads(args.manifest.read_text(encoding="utf-8"))
    for spec in arms.values():
        spec["_base"] = str(args.manifest.resolve().parent)
    reports = run(arms, args.fix, out_dir=args.out, incidents=args.incidents, since=args.since)
    print(summary(reports))
    return 0 if all(r["verdict"] == "ready" for r in reports.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
