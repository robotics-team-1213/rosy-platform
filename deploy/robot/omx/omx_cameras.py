#!/usr/bin/env python3
"""The cell's cameras, managed from one registry: what each role is, which camera it is, and its preview unit.

2026-10-31: cameras were moved, swapped and added (a RealSense D435 as the top camera, the old top camera as a side
camera, a second wrist camera), and every role's env file and unit was edited by hand. The registry
(`~/.config/rosy/omx-cameras.json`, rosy.omx-cameras.v1, site-private: it names devices) is the one record:

  {"schema": "rosy.omx-cameras.v1",
   "defaults": {"ROSY_CAMERA_SOURCE": "...camera_source.py", "ROS_DOMAIN_ID": "13", ...},  # copied into each role
   "cameras": [{"role": "top", "device": "/dev/v4l/by-id/rosy-realsense-d435-color", "topic": "/top_camera/image_raw",
                "frame": "top_camera_link", "fourcc": "YUYV", "stream": "color", "env": {}}, ...]}

`device` is any persistent name camera_source accepts: a unique by-id name, a udev name (rosy-realsense-*), or a
by-path name for cameras whose serials repeat. `stream` (color | depth | ir) and `env` (extra keys, e.g.
ROSY_DEPTH_RANGE_MM or ROSY_CAMERA_MIN_USB_MBPS) are optional.

  omx_cameras.py init      write a registry from the role env files in use (once, to adopt them)
  omx_cameras.py inventory every plugged camera node: model, USB ID and port, speed, formats, names, the role using it
  omx_cameras.py bind [--apply]  write each role's env from the registry and (re)start its unit when it changed or
                           its camera came back; a camera nobody registered is listed, never given a role by guess
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import omx_devices  # noqa: E402

SCHEMA = "rosy.omx-cameras.v1"
REGISTRY = Path("~/.config/rosy/omx-cameras.json").expanduser()
ENV_DIR = Path("~/.config/rosy").expanduser()
FIELDS = {"device": "ROSY_CAMERA_DEVICE", "topic": "ROSY_CAMERA_TOPIC", "frame": "ROSY_CAMERA_FRAME",
          "fourcc": "ROSY_CAMERA_FOURCC"}


def load(path: Path = REGISTRY) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema") != SCHEMA:
        raise SystemExit(f"{path}: not a {SCHEMA} file")
    roles = [c.get("role") for c in data["cameras"]]
    for c in data["cameras"]:
        if not all(c.get(k) for k in ("role", "device", "topic", "frame")):
            raise SystemExit(f"{path}: every camera needs role, device, topic and frame ({c.get('role')!r})")
        if Path(c["device"]).parent not in (Path("/dev/v4l/by-id"), Path("/dev/v4l/by-path")):
            raise SystemExit(f"{path}: {c['role']}: a persistent /dev/v4l/by-id or by-path name is required")
        if c.get("stream", "color") not in ("color", "depth", "ir"):
            raise SystemExit(f"{path}: {c['role']}: stream is color, depth or ir")
    if len(set(roles)) != len(roles) or len({c["device"] for c in data["cameras"]}) != len(roles):
        raise SystemExit(f"{path}: each role and each device appears once")
    return data


def role_env(camera: dict, defaults: dict) -> dict:
    """The env file one role's unit reads (rosy-omx-camera@<role>.service)."""
    env = dict(defaults)
    env.update({key: camera[field] for field, key in FIELDS.items() if camera.get(field)})
    if env.get("ROSY_CAMERA_FOURCC") == "MJPG":
        del env["ROSY_CAMERA_FOURCC"]  # the producer's default
    env.update(camera.get("env", {}))
    return env


def init(env_dir: Path = ENV_DIR) -> dict:
    """A registry adopting the camera roles whose env files are in use; shared keys become defaults."""
    roles = {r.removeprefix("camera-"): e for r, e in omx_devices.role_env(env_dir).items() if r.startswith("camera-")}
    keys = set.intersection(*(set(e) for e in roles.values())) if roles else set()
    defaults = {k: v for k, v in next(iter(roles.values()), {}).items()
                if k in keys and k not in FIELDS.values() and all(e[k] == v for e in roles.values())}
    cameras = []
    for role, env in sorted(roles.items()):
        camera = {"role": role, **{field: env[key] for field, key in FIELDS.items() if env.get(key)}}
        camera["stream"] = "depth" if env.get("ROSY_CAMERA_FOURCC") == "Z16" else "color"
        extra = {k: v for k, v in env.items() if k not in defaults and k not in FIELDS.values()}
        if extra:
            camera["env"] = extra
        cameras.append(camera)
    return {"schema": SCHEMA, "defaults": defaults, "cameras": cameras}


def formats(node: str) -> list:
    """The pixel formats a capture node offers (v4l2-ctl), [] when it cannot be asked."""
    try:
        out = subprocess.run(["v4l2-ctl", "-d", node, "--list-formats"], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.TimeoutExpired):
        return []
    return [line.split("'")[1].strip() for line in out.splitlines() if line.strip().startswith("[") and "'" in line]


def inventory(registry: dict | None, facts: dict, names: dict, ask=formats, realpath=os.path.realpath) -> list:
    """One row per capture node: facts, every persistent name, offered formats and the registered role."""
    by_node = {}
    for camera in (registry or {}).get("cameras", []):
        by_node.setdefault(realpath(camera["device"]), []).append(camera["role"])
    return [{"node": node, **fact, "names": sorted(names.get(node, [])), "formats": ask(node),
             "roles": by_node.get(node, [])} for node, fact in sorted(facts.items())]


def bind(registry: dict, env_dir: Path, present, plugged_nodes: set, realpath=os.path.realpath) -> dict:
    """{"write": {role: env}, "restart": [role], "waiting": [role], "unregistered": [node]} for the registry now."""
    out = {"write": {}, "restart": [], "waiting": [], "unregistered": []}
    used = set()
    for camera in registry["cameras"]:
        role, path = camera["role"], env_dir / f"omx-camera-{camera['role']}.env"
        if not present(camera["device"]):
            out["waiting"].append(role)
            continue
        used.add(realpath(camera["device"]))
        want = role_env(camera, registry.get("defaults", {}))
        have = dict(line.split("=", 1) for line in path.read_text(encoding="utf-8").splitlines() if "=" in line) \
            if path.exists() else None
        if have != want:
            out["write"][role] = want
            out["restart"].append(role)
    out["unregistered"] = sorted(plugged_nodes - used)
    return out


def apply(plan: dict, env_dir: Path, units_running, run=subprocess.run) -> list:
    """Write the env files and (re)start units: a changed role, or a role whose camera is back but unit is down."""
    done = []
    for role, env in plan["write"].items():
        path = env_dir / f"omx-camera-{role}.env"
        tmp = path.with_suffix(".tmp")
        tmp.write_text("".join(f"{k}={v}\n" for k, v in env.items()), encoding="utf-8")
        os.replace(tmp, path)
        done.append(f"wrote {path.name}")
    down = [r for r in plan.get("present", []) if r not in plan["restart"] and not units_running(r)]
    for role in plan["restart"] + down:
        unit = f"rosy-omx-camera@{role}.service"
        run(["systemctl", "--user", "enable", unit], check=False, capture_output=True)
        run(["systemctl", "--user", "restart", unit], check=False, capture_output=True)
        done.append(f"restarted {unit}")
    return done


def _names() -> dict:
    out = {}
    for link in glob.glob("/dev/v4l/by-id/*") + [p for p in glob.glob("/dev/v4l/by-path/*") if "usbv2" not in p]:
        out.setdefault(os.path.realpath(link), []).append(link)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("action", choices=("init", "inventory", "bind"))
    ap.add_argument("--registry", type=Path, default=REGISTRY)
    ap.add_argument("--env-dir", type=Path, default=ENV_DIR)
    ap.add_argument("--apply", action="store_true", help="bind: write env files and restart units")
    args = ap.parse_args(argv)
    if args.action == "init":
        if args.registry.exists():
            raise SystemExit(f"{args.registry} exists; edit it instead")
        args.registry.write_text(json.dumps(init(args.env_dir), indent=1) + "\n", encoding="utf-8")
        print(f"wrote {args.registry}")
        return 0
    registry = load(args.registry) if args.registry.exists() else None
    facts = omx_devices.video_facts()
    if args.action == "inventory":
        print(json.dumps(inventory(registry, facts, _names()), indent=1))
        return 0
    if registry is None:
        raise SystemExit(f"no registry at {args.registry}: run 'init' first")
    plan = bind(registry, args.env_dir, os.path.exists, set(facts))
    running = lambda role: subprocess.run(["systemctl", "--user", "is-active", "--quiet",  # noqa: E731
                                           f"rosy-omx-camera@{role}.service"]).returncode == 0
    plan["present"] = [c["role"] for c in registry["cameras"] if c["role"] not in plan["waiting"]]
    if args.apply:
        plan["done"] = apply(plan, args.env_dir, running)
    print(json.dumps({k: v for k, v in plan.items() if k != "write"} | {"write": sorted(plan["write"])}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
