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


def role_env(env_dir: Path) -> dict:
    """{role: {KEY: value}} of every per-role env file that names a device."""
    out = {}
    for path in sorted(env_dir.glob("omx-*.env")):
        env = dict(line.split("=", 1) for line in path.read_text(encoding="utf-8").splitlines() if "=" in line)
        env = {k.strip(): v.strip() for k, v in env.items()}
        if any(env.get(k) for k in ROLE_KEYS):
            out[path.stem.removeprefix("omx-")] = env
    return out


def roles(env_dir: Path) -> dict:
    """{role: device} from the per-role env files (omx-observer-<arm>.env, omx-camera-<role>.env)."""
    return {role: next(env[k] for k in ROLE_KEYS if env.get(k)) for role, env in role_env(env_dir).items()}


def video_facts(sysfs: Path = Path("/sys/class/video4linux")) -> dict:
    """{/dev/videoN: {usb, interface, id, serial, speed_mbps}} for each capture node (index 0) of a USB camera."""
    out = {}
    for node in sorted(sysfs.glob("video*")):
        try:
            if (node / "index").read_text().strip() != "0":
                continue  # a metadata or second node of the same interface
            interface = (node / "device").resolve()
            usb = interface.parent
            read = lambda name: (usb / name).read_text().strip() if (usb / name).exists() else None  # noqa: E731
            out[f"/dev/{node.name}"] = {"usb": usb.name, "interface": interface.name,
                                        "id": f"{read('idVendor')}:{read('idProduct')}", "serial": read("serial"),
                                        "speed_mbps": int(read("speed") or 0)}
        except OSError:
            continue
    return out


def camera_problems(configured: dict, env: dict, facts: dict, realpath=os.path.realpath) -> list:
    """Camera roles whose device name is not unique, or whose USB link is slower than the role needs.

    2026-10-31: two Innomaker U20CAMs carry the same serial (SN0001), so their by-id name named either; the RealSense
    D435's colour, depth and IR nodes share one by-id name whose index0 changed node between boots; and the D435 gave
    colour but no depth on USB 2.0. A role names its need with ROSY_CAMERA_MIN_USB_MBPS; a depth format (Z16) needs
    5000 unless it says otherwise."""
    problems = []
    for role, device in configured.items():
        if not role.startswith("camera-"):
            continue
        fact = facts.get(realpath(device))
        if fact is None:
            continue  # unplugged: reported by scan
        name = os.path.basename(device)
        if device.startswith("/dev/v4l/by-id/usb-"):  # the kernel's own by-id name, from vendor and serial
            twins = [n for n, f in facts.items() if f["id"] == fact["id"] and f["serial"] == fact["serial"]]
            if len(twins) > 1:
                same = len({facts[n]["usb"] for n in twins}) == 1
                problems.append(f"{role}: {name} names {len(twins)} capture nodes "
                                + ("of one device; give each node its own udev name" if same
                                   else "of cameras with the same serial; select it by its USB port (by-path)"))
        settings = env.get(role, {})
        need = int(settings.get("ROSY_CAMERA_MIN_USB_MBPS") or (5000 if settings.get("ROSY_CAMERA_FOURCC") == "Z16" else 0))
        if fact["speed_mbps"] < need:
            problems.append(f"{role}: USB link {fact['speed_mbps']} Mbps, the role needs {need} (cable, port or hub)")
    return problems


def scan(boards: dict, cameras: list, configured: dict, inventory=None) -> dict:
    """boards {by-id path: kind}; cameras [by-id or by-path]; configured {role: device}."""
    present = set(boards) | set(cameras)
    problems = [f"{role}: {device} is not plugged in" for role, device in configured.items() if device not in present]
    # only a board that clearly answers as something else is wrong; one held by an observer or session is unknown
    problems += [f"{role}: {device} answers as a {boards[device]}, not a follower"
                 for role, device in configured.items() if role.startswith("observer-") and boards.get(device) in ("leader", "absent")]
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
    facts = video_facts()
    capture = lambda p: os.path.realpath(p) in facts  # noqa: E731
    # every persistent name of a capture node (udev names included); by-path only where no by-id name exists
    cameras = sorted(p for p in glob.glob("/dev/v4l/by-id/*") if capture(p)) + sorted(
        p for p in glob.glob("/dev/v4l/by-path/*-index0") if "usbv2" not in p and capture(p)
        and os.path.realpath(p) not in {os.path.realpath(c) for c in glob.glob("/dev/v4l/by-id/*")})
    env = role_env(args.env_dir)
    configured = roles(args.env_dir)
    for path in args.session_config:
        configured[f"observer-session-{path.stem}"] = json.loads(path.read_text(encoding="utf-8"))["robot"]["port"]
    # a by-path role is present when that USB port has a camera, whatever its by-id name
    cameras += [d for d in configured.values() if d.startswith("/dev/v4l/by-path/") and os.path.exists(d) and d not in cameras]
    out = scan(boards, cameras, configured, inventory)
    out["problems"] += camera_problems(configured, env, facts)
    print(json.dumps(out, indent=1))
    return 1 if out["problems"] else 0


if __name__ == "__main__":
    sys.exit(main())
