#!/usr/bin/env python3
"""What is plugged into this control host against what each role is set to use, read only (PING, no motion).

2026-10-31: boards and cameras were moved between arms; the observer, camera and session configs kept by-id paths
written by hand, so arm_a and arm S pointed at boards that were gone, arm_b at a board that now answers as a leader's,
and the top role at an unplugged camera, while nothing said so. Each board is classified by the motor IDs it answers
(11-16 a follower, 1-6 a leader); each role's configured device is checked present, and anything plugged in that no
role uses is listed. With an inventory (rosy.omx-host-inventory.v1) every enabled workcell's follower and leader are
also checked to be present and of that kind.

  omx_devices.py scan [--env-dir ~/.config/rosy] [--inventory /etc/rosy/omx/host-inventory.yaml]
                      [--session-config record-config.json ...]
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from pathlib import Path

FOLLOWER, LEADER = set(range(11, 17)), set(range(1, 7))
ROLE_KEYS = ("ROSY_OBSERVER_DEVICE", "ROSY_CAMERA_DEVICE")


def kind(ids) -> str:
    ids = set(ids)
    return "follower" if ids == FOLLOWER else "leader" if ids == LEADER else ("absent" if not ids else "unknown")


def ping_ids(device: str, baud: int = 1_000_000, ids=range(0, 20)) -> list[int]:
    """Motor IDs answering a PING on `device` (an instruction that changes nothing)."""
    from dynamixel_sdk import PacketHandler, PortHandler

    port, handler = PortHandler(device), PacketHandler(2.0)
    if not (port.openPort() and port.setBaudRate(baud)):
        raise OSError(f"{device}: cannot open")
    try:
        return [i for i in ids if handler.ping(port, i)[1] == 0]
    finally:
        port.closePort()


def roles(env_dir: Path) -> dict:
    """{role: device} from the per-role env files (omx-observer-<arm>.env, omx-camera-<role>.env)."""
    out = {}
    for path in sorted(env_dir.glob("omx-*.env")):
        for line in path.read_text(encoding="utf-8").splitlines():
            key, _, value = line.partition("=")
            if key.strip() in ROLE_KEYS and value.strip():
                out[path.stem.removeprefix("omx-")] = value.strip()
    return out


def scan(boards: dict, cameras: list, configured: dict, inventory=None) -> dict:
    """boards {by-id path: kind}; cameras [by-id or by-path]; configured {role: device}."""
    present = set(boards) | set(cameras)
    problems = [f"{role}: {device} is not plugged in" for role, device in configured.items() if device not in present]
    problems += [f"{role}: {device} answers as a {boards[device]}, not a follower"
                 for role, device in configured.items() if role.startswith("observer-") and boards.get(device, "follower") != "follower"]
    for cell in (inventory.workcells if inventory else ()):
        for part in ("follower", "leader"):
            device = getattr(cell, part)
            if cell.enabled and boards.get(device) != part:
                problems.append(f"{cell.workcell_id} {part}: {device} is {boards.get(device, 'not plugged in')}")
    used = set(configured.values()) | {getattr(c, p) for c in (inventory.workcells if inventory else ()) for p in ("follower", "leader")}
    return {"boards": boards, "cameras": cameras, "configured": configured, "problems": problems,
            "unassigned": sorted(present - used)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("action", choices=("scan",))
    ap.add_argument("--env-dir", type=Path, default=Path("~/.config/rosy").expanduser())
    ap.add_argument("--inventory", type=Path)
    ap.add_argument("--session-config", type=Path, action="append", default=[],
                    help="a record config whose robot.port a session drives (role session-<file stem>)")
    args = ap.parse_args(argv)
    inventory = None
    if args.inventory:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from host_inventory import load_inventory

        inventory = load_inventory(args.inventory.read_text(encoding="utf-8"))
    boards = {}
    for device in sorted(glob.glob("/dev/serial/by-id/*")):
        try:
            boards[device] = kind(ping_ids(device))
        except OSError as exc:  # busy (a session or observer holds it) is still plugged in
            boards[device] = f"busy: {exc}"[:80]
    cameras = sorted(glob.glob("/dev/v4l/by-id/*-index0")) + sorted(
        p for p in glob.glob("/dev/v4l/by-path/*-index0") if "usbv2" not in p
        and os.path.realpath(p) not in {os.path.realpath(c) for c in glob.glob("/dev/v4l/by-id/*")})
    configured = roles(args.env_dir)
    for path in args.session_config:
        configured[f"observer-session-{path.stem}"] = json.loads(path.read_text(encoding="utf-8"))["robot"]["port"]
    # a by-path role is present when that USB port has a camera, whatever its by-id name
    cameras += [d for d in configured.values() if d.startswith("/dev/v4l/by-path/") and os.path.exists(d) and d not in cameras]
    out = scan(boards, cameras, configured, inventory)
    print(json.dumps(out, indent=1))
    return 1 if out["problems"] else 0


if __name__ == "__main__":
    sys.exit(main())
