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
                           its camera came back. A role whose camera is gone follows it to another port only when
                           exactly one unregistered camera has the role's recorded model (usb_id) and no other gone
                           role has that model; every other unregistered camera is proposed, never given a role
  omx_cameras.py propose   the unregistered cameras, each with its persistent name and the gone roles of its model
                           A role Fleet's operator decided (omx-camera-decisions.json, D-963) is approved the same way
  omx_cameras.py approve NODE ROLE  give a plugged camera a role (a new role gets /<role>_camera/image_raw), then bind
  omx_cameras.py manifest [--manifest PATH] [--apply]  copy each registered camera's device into the workcell
                           observation manifest entry with the same image topic; exit 1 while one differs
                           (2026-11-02: the bridge's and the site's copies had the two wrist ports swapped)
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import omx_devices  # noqa: E402

SCHEMA = "rosy.omx-cameras.v1"
REGISTRY = Path("~/.config/rosy/omx-cameras.json").expanduser()
ENV_DIR = Path("~/.config/rosy").expanduser()
DECISIONS = Path("~/.local/state/rosy/omx-camera-decisions.json").expanduser()  # {key: role}, written by the bridge
MANIFEST = Path("~/.config/rosy/workcell-observations/observations.yaml").expanduser()
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


def sync_manifest(registry: dict, text: str) -> tuple[str, list, list]:
    """(text, changed, unregistered): each camera's device_path set from the registry role with its image_topic.

    Line edits keep the manifest's order and comments; a camera whose topic no role publishes is listed, not touched.
    """
    device = {c["topic"]: c["device"] for c in registry["cameras"]}
    lines, topic, changed, unregistered = text.split("\n"), None, [], []
    for i, line in enumerate(lines):
        key, _, value = line.strip().removeprefix("- ").partition(":")
        value = value.split(" #")[0]
        if key == "image_topic":
            topic = value.strip()
        elif key == "device_path" and topic is not None:
            if topic not in device:
                unregistered.append(topic)
            elif value.strip() != device[topic]:
                changed.append({"topic": topic, "from": value.strip(), "to": device[topic]})
                lines[i] = line[:len(line) - len(line.lstrip())] + f"device_path: {device[topic]}"
            topic = None
    return "\n".join(lines), changed, unregistered


def best_name(node: str, names: dict) -> str:
    """A node's persistent name: a ROSY udev name, else its USB port (by-path). Not the kernel by-id name: a twin
    plugged later shares it (2026-10-31, two U20CAMs both SN0001); a port move is followed by `learn` instead."""
    own = sorted(names.get(node, []))
    for prefix in ("/dev/v4l/by-id/rosy-", "/dev/v4l/by-path/", "/dev/v4l/by-id/"):
        found = [n for n in own if n.startswith(prefix)]
        if found:
            return found[0]
    raise SystemExit(f"{node}: no persistent /dev/v4l name")


def hub(usb: str | None) -> str | None:
    """The USB hub a device sits on ("3-1.3" -> "3-1"); None on a root port, which every device shares."""
    return usb.rsplit(".", 1)[0] if usb and "." in usb else None


def arm_hubs(env_dir: Path = ENV_DIR, realpath=os.path.realpath) -> dict:
    """{arm: hub} for each observer board plugged into a hub (omx-observer-<arm>.env names the board)."""
    out = {}
    for role, device in omx_devices.roles(env_dir).items():
        if role.startswith("observer-") and os.path.exists(device):
            interface = Path(f"/sys/class/tty/{os.path.basename(realpath(device))}/device").resolve().name
            if hub(interface.split(":")[0]):
                out[role.removeprefix("observer-")] = hub(interface.split(":")[0])
    return out


def propose(registry: dict, facts: dict, names: dict, present, realpath=os.path.realpath, hubs=None) -> list:
    """One row per camera no present role uses: its name and model, the gone roles last seen on that model, and
    `follow` when it is the only such camera and the only such role (the same camera moved to another port).

    `hub_arm` is the one arm whose board shares the camera's USB hub, and `suggest` its `<arm>_wrist` role when that
    role is gone: a hint for the person approving, not a binding, until the cell's wiring is checked to be that way."""
    gone = [c for c in registry["cameras"] if not present(c["device"])]
    used = {realpath(c["device"]) for c in registry["cameras"] if present(c["device"])}
    free = [n for n in sorted(facts) if n not in used]
    rows = []
    for node in free:
        model = facts[node]["id"]
        roles = [c["role"] for c in gone if c.get("usb_id") == model]
        same = [n for n in free if facts[n]["id"] == model]
        follow = roles[0] if len(roles) == 1 and len(same) == 1 else None
        arms = [arm for arm, h in (hubs or {}).items() if h == hub(facts[node]["usb"])]
        hub_arm = arms[0] if len(arms) == 1 else None
        rows.append({"node": node, "device": best_name(node, names), "usb_id": model, "roles": roles,
                     "follow": follow, "hub_arm": hub_arm,
                     "suggest": follow or (f"{hub_arm}_wrist" if f"{hub_arm}_wrist" in roles else None)})
    return rows


def learn(registry: dict, facts: dict, proposals: list, present, realpath=os.path.realpath) -> list:
    """Record each present camera's model, and move each `follow` role to its camera; the changes made."""
    changes = []
    by_role = {c["role"]: c for c in registry["cameras"]}
    for c in registry["cameras"]:
        fact = facts.get(realpath(c["device"])) if present(c["device"]) else None
        if fact and c.get("usb_id") != fact["id"]:
            c["usb_id"] = fact["id"]
            changes.append({"role": c["role"], "usb_id": fact["id"]})
    for row in proposals:
        if row["follow"]:
            camera = by_role[row["follow"]]
            changes.append({"role": camera["role"], "from": camera["device"], "to": row["device"]})
            camera["device"] = row["device"]
    return changes


def approve(registry: dict, role: str, row: dict) -> dict:
    """The registry with ROLE on the proposed camera ROW; a new role gets the topic and frame naming convention."""
    camera = next((c for c in registry["cameras"] if c["role"] == role), None)
    if camera is None:
        camera = {"role": role, "topic": f"/{role}_camera/image_raw", "frame": f"{role}_camera_link", "stream": "color"}
        registry["cameras"].append(camera)
    camera.update(device=row["device"], usb_id=row["usb_id"])
    return registry


def device_key(device: str) -> str:
    """What the control PC tells Fleet instead of a device name (D-963)."""
    return hashlib.sha256(device.encode()).hexdigest()[:32]


def apply_decisions(registry: dict, proposals: list, path: Path) -> tuple[list, dict]:
    """Approve each proposed camera whose key Fleet decided a role for: (changes, decisions still waiting)."""
    try:
        decided = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return [], {}
    if not isinstance(decided, dict):
        return [], {}
    changes = []
    for row in proposals:
        role = decided.pop(device_key(row["device"]), None)
        if isinstance(role, str) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]{0,63}", role):
            approve(registry, role, row)
            changes.append({"role": role, "to": row["device"]})
    return changes, decided


def save(registry: dict, path: Path) -> None:
    """Write the registry only if it still loads (one role and one device each)."""
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(registry, indent=1) + "\n", encoding="utf-8")
    try:
        load(tmp)
    except SystemExit:
        tmp.unlink()
        raise
    os.replace(tmp, path)


def _sync_manifest_file(registry: dict, path: Path) -> list:
    if not path.is_file() or not os.access(path, os.W_OK):
        return []
    text, changed, _ = sync_manifest(registry, path.read_text(encoding="utf-8"))
    if changed:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(text, encoding="utf-8")
        os.chmod(tmp, path.stat().st_mode)
        os.replace(tmp, path)
    return changed


def _names() -> dict:
    out = {}
    for link in glob.glob("/dev/v4l/by-id/*") + [p for p in glob.glob("/dev/v4l/by-path/*") if "usbv2" not in p]:
        out.setdefault(os.path.realpath(link), []).append(link)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("action", choices=("init", "inventory", "bind", "manifest", "propose", "approve"))
    ap.add_argument("node", nargs="?", help="approve: the camera (/dev/videoN or any of its names)")
    ap.add_argument("role", nargs="?", help="approve: the role it gets")
    ap.add_argument("--registry", type=Path, default=REGISTRY)
    ap.add_argument("--env-dir", type=Path, default=ENV_DIR)
    ap.add_argument("--decisions", type=Path, default=DECISIONS, help="bind --apply: Fleet's role decisions")
    ap.add_argument("--manifest", type=Path, default=MANIFEST, help="manifest: the observation manifest to check")
    ap.add_argument("--apply", action="store_true", help="bind: write env files and restart units; manifest: write it")
    args = ap.parse_args(argv)
    if args.action == "manifest":
        text, changed, unregistered = sync_manifest(load(args.registry), args.manifest.read_text(encoding="utf-8"))
        if changed and args.apply:
            tmp = args.manifest.with_suffix(".tmp")
            tmp.write_text(text, encoding="utf-8")
            os.chmod(tmp, args.manifest.stat().st_mode)
            os.replace(tmp, args.manifest)
        print(json.dumps({"manifest": str(args.manifest), "changed": changed, "unregistered": unregistered,
                          "written": bool(changed and args.apply)}, indent=1))
        return 1 if changed and not args.apply else 0
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
    proposals = propose(registry, facts, _names(), os.path.exists, hubs=arm_hubs(args.env_dir))
    if args.action == "propose":
        print(json.dumps(proposals, indent=1))
        return 0
    learned = []
    if args.action == "approve":
        if not (args.node and args.role):
            raise SystemExit("approve NODE ROLE")
        row = next((r for r in proposals if r["node"] == os.path.realpath(args.node)), None)
        if row is None:
            raise SystemExit(f"{args.node}: not an unregistered plugged camera (see 'propose')")
        save(approve(registry, args.role, row), args.registry)
        learned, args.apply = [{"role": args.role, "to": row["device"]}], True
    elif args.apply:
        learned = learn(registry, facts, proposals, os.path.exists)
        approved, waiting = apply_decisions(registry, [r for r in proposals if not r["follow"]], args.decisions)
        learned += approved
        if learned:
            save(registry, args.registry)
        if approved:  # the registry is saved first, so a crash re-applies a decision instead of losing it
            tmp = args.decisions.with_suffix(".tmp")
            tmp.write_text(json.dumps(waiting), encoding="utf-8")
            os.replace(tmp, args.decisions)
    if learned:
        registry = load(args.registry)
        proposals = propose(registry, facts, _names(), os.path.exists, hubs=arm_hubs(args.env_dir))
    plan = bind(registry, args.env_dir, os.path.exists, set(facts))
    plan["learned"], plan["proposals"] = learned, proposals
    if learned:  # the bridge's copy is the user's; the site's /etc copy needs 'manifest --apply' with root
        plan["manifest"] = _sync_manifest_file(registry, args.manifest)
    running = lambda role: subprocess.run(["systemctl", "--user", "is-active", "--quiet",  # noqa: E731
                                           f"rosy-omx-camera@{role}.service"]).returncode == 0
    plan["present"] = [c["role"] for c in registry["cameras"] if c["role"] not in plan["waiting"]]
    if args.apply:
        plan["done"] = apply(plan, args.env_dir, running)
    print(json.dumps({k: v for k, v in plan.items() if k != "write"} | {"write": sorted(plan["write"])}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
