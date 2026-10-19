#!/usr/bin/env python3
"""Run the native no-goal OMX hardware owner for one instance (D-785, D-246).

One process: the ROS runtime (one ArmCommandOwner on the steady clock, subscribed to the real
joint states of the instance graph) and the D-336 UDS socket serving stop, owner-state and
identity readback to the configured Fleet peer UID. SubmitAction is refused; there is no HTTP
or Pilot surface. It never opens a serial port, enables torque, configures or activates
controllers: the native controller graph is started separately and only observed here.

It holds the same per-Action lock as the collection backend (collection_ros.resource_key), so
the collection process and this owner can never both own one trajectory action.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import signal
import stat
import sys
import threading
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = Path(os.environ.get("ROSY_OMX_REPO", str(HERE.parents[2])))
for _part in ("contracts/foundation", "middleware/devices/omx/adapter", "middleware/devices/omx/agent/src",
              "deploy/robot/omx"):
    if str(REPO / _part) not in sys.path:
        sys.path.append(str(REPO / _part))

SCHEMA = "rosy.omx-hardware-owner.v1"
KEYS = {"schema", "workcell_id", "instance_id", "namespace", "fleet_peer_uid", "journal_path",
        "socket_root", "owner_config"}


def _private_file(path: Path) -> str:
    info = os.lstat(path)
    if not stat.S_ISREG(info.st_mode):
        raise ValueError("hardware owner config must be a regular file, not a link")
    if info.st_uid != os.getuid() or info.st_mode & 0o022:
        raise ValueError("hardware owner config must be owned by this user and not group/world writable")
    return path.read_text(encoding="utf-8")


def _reject_constant(value):
    raise ValueError("non-finite JSON is not allowed in the hardware owner config")


def load_config(path: Path | str, environ=None, *, read=_private_file):
    """Return (HardwareOwnerSettings, ArmCommandConfig, InstanceNames) from a private config."""
    from omx_adapter.command_owner import ArmCommandConfig
    from rosy_agent.omx_hardware_owner import ALLOWED_OWNERS, HardwareOwnerSettings
    from instance_names import InstanceNames, namespace_from_environment

    environ = os.environ if environ is None else environ
    document = json.loads(read(Path(path)), parse_constant=_reject_constant)
    if not isinstance(document, dict) or set(document) != KEYS or document["schema"] != SCHEMA:
        raise ValueError(f"hardware owner config must be exactly {SCHEMA}")
    if "<" in json.dumps(document):
        raise ValueError("hardware owner config still holds placeholder values")
    names = InstanceNames(document["namespace"])
    if namespace_from_environment(environ) != names.namespace:
        raise ValueError("ROSY_OMX_ROS_NAMESPACE must equal the configured namespace")
    for key in ("journal_path", "socket_root"):
        if not isinstance(document[key], str) or not Path(document[key]).is_absolute():
            raise ValueError(f"{key} must be an absolute path")
    raw = document["owner_config"]
    if not isinstance(raw, dict):
        raise ValueError("owner_config must be an object")
    raw = dict(raw)
    for key in ("joint_names", "allowed_owners"):
        if key in raw:
            raw[key] = tuple(raw[key])
    if "position_limits" in raw and isinstance(raw["position_limits"], dict):
        raw["position_limits"] = {name: tuple(bounds) for name, bounds in raw["position_limits"].items()}
    config = ArmCommandConfig(**raw)
    # Checked here too so --check refuses what the owner assembly refuses (D-793: no learned_policy).
    if tuple(config.allowed_owners) != ALLOWED_OWNERS:
        raise ValueError("hardware owner admits only the rule_based owner")
    settings = HardwareOwnerSettings(
        workcell_id=document["workcell_id"], instance_id=document["instance_id"],
        journal_path=Path(document["journal_path"]), socket_root=Path(document["socket_root"]),
        fleet_peer_uid=document["fleet_peer_uid"], calibration_revision=config.calibration_revision)
    return settings, config, names


def require_ros_environment(environ=None) -> str:
    environ = os.environ if environ is None else environ
    domain = environ.get("ROS_DOMAIN_ID", "")
    if not domain.isdigit():
        raise RuntimeError("an explicit ROS_DOMAIN_ID is required")
    if environ.get("ROS_AUTOMATIC_DISCOVERY_RANGE") != "LOCALHOST":
        raise RuntimeError("the hardware owner requires localhost-only ROS discovery")
    return domain


def acquire_action_lock(trajectory_action: str, domain: str):
    """The collection backend's lock for this (domain, action); held for the process lifetime."""
    from collection_ros import resource_key

    runtime_dir = Path(f"/run/user/{os.getuid()}")
    if not runtime_dir.is_dir() or runtime_dir.is_symlink() or runtime_dir.stat().st_uid != os.getuid():
        raise RuntimeError("private runtime directory required")
    descriptor = os.open(runtime_dir / f"rosy-omx-action-{resource_key(trajectory_action, domain)}.lock",
                         os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    guard = os.fdopen(descriptor, "a")
    try:
        fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        guard.close()
        raise RuntimeError("another owner (collection or hardware owner) holds this trajectory action") from None
    return guard


def close_runtime(owner, executor, node, context, lock):
    owner.uds_server.stop()
    if executor.shutdown(timeout_sec=5, wait_for_threads=False) is not True:
        raise RuntimeError('CLEANUP_HOLD: OWNER_SHUTDOWN_INCOMPLETE')
    owner.runtime.destroy()
    node.destroy_node()
    context.shutdown()
    lock.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", required=True, type=Path, help="private rosy.omx-hardware-owner.v1 JSON")
    parser.add_argument("--check", action="store_true", help="validate config and environment, start nothing")
    args = parser.parse_args(argv)

    domain = require_ros_environment()
    settings, config, names = load_config(args.config)
    if args.check:
        print(json.dumps({"ok": True, "workcell_id": settings.workcell_id,
                          "instance_id": settings.instance_id, "namespace": names.namespace,
                          "trajectory_action": names.trajectory_action, "goals_enabled": False}))
        return 0

    from cell_sim_tools import refuse_second_owner
    from rosy_agent.fleet_fence import fleet_fence_from_environment
    fleet_fence = fleet_fence_from_environment()
    lock = acquire_action_lock(names.trajectory_action, domain)

    import rclpy
    from omx_adapter.ros_owner_executor import OwnerMultiThreadedExecutor
    from omx_adapter.ros_runtime import RosArmCommandRuntime
    from rosy_agent.omx_hardware_owner import build_hardware_owner

    rclpy.init()
    node = rclpy.create_node("rosy_omx_hardware_owner")
    if node.get_parameter("use_sim_time").value:
        raise RuntimeError("the hardware owner refuses simulation time")
    owner = build_hardware_owner(
        settings, config,
        runtime_factory=lambda cfg: RosArmCommandRuntime(
            node, cfg, joint_state_topic=names.joint_state_topic,
            trajectory_action=names.trajectory_action, owner_clock="steady"),
        refuse_second_owner=lambda: refuse_second_owner(namespace=names.namespace),
        fleet_fence_current=fleet_fence)
    executor = OwnerMultiThreadedExecutor(num_threads=4)
    executor.add_node(node)
    threading.Thread(target=executor.spin, daemon=True).start()
    uds = threading.Thread(target=owner.uds_server.serve_forever, daemon=True)
    uds.start()
    done = threading.Event()
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, lambda *_: done.set())
    print(json.dumps({"event": "hardware_owner_ready", "instance_id": settings.instance_id,
                      "socket": str(owner.uds_server.socket_path), "goals_enabled": False}), flush=True)
    try:
        while not done.wait(0.5):
            if not uds.is_alive():
                raise RuntimeError("UDS server stopped")
    finally:
        close_runtime(owner, executor, node, rclpy, lock)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
