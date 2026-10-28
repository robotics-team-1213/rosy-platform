"""Select deployment targets; product executors retain verification and privileges."""

import json
from pathlib import Path
import re
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
_FIELDS = {"id", "deployment", "install_target", "status", "operations", "reason", "delivery"}
_PINKY_DELIVERY = dict(platform="raspberry-pi-5", architecture="arm64", image_backend="pinky_pro",
    application_updater="native-release", os_updater="rauc", os_compatible="rosy-pinky-pro-ab-v2",
    os_tag_prefix="os-pinky-pro-")
_PLATFORMS = {"rasptank_metal": "raspberry-pi-4", "dji_neo_2": "external-sdk-host", "omx": "workcell-host"}


class DeploymentError(ValueError):
    pass


def load_targets(root=ROOT):
    root = Path(root).resolve()
    paths = sorted(root.glob("deploy/robot/*/deployment-target.json"))
    paths += sorted(root.glob("deploy/hosts/sdk/*/deployment-target.json"))
    targets = {}
    for path in paths:
        if not path.resolve().is_relative_to(root):
            raise DeploymentError("target descriptor leaves the repository")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError) as exc:
            raise DeploymentError(f"cannot read target descriptor: {path.name}") from exc
        if not isinstance(data, dict) or set(data) != _FIELDS:
            raise DeploymentError("target descriptor has invalid fields")
        if any(not isinstance(data[key], str) or not data[key].strip() for key in _FIELDS - {"operations", "delivery"}):
            raise DeploymentError("target descriptor requires nonempty text fields")
        target = data["id"]
        if target != path.parent.name or not re.fullmatch(r"[a-z][a-z0-9_]*", target) or target in targets:
            raise DeploymentError("target id is invalid or duplicated")
        expected = "sdk-host" if path.parent.parent.name == "sdk" else "native"
        if data["deployment"] != expected:
            raise DeploymentError("target deployment kind disagrees with its owner")
        if data["status"] not in {"existing_implementation", "source_only", "sdk_unsupported"}:
            raise DeploymentError("unknown target support status")
        operations = data["operations"]
        if not isinstance(operations, list) or any(op not in ("apply", "rollback") for op in operations):
            raise DeploymentError("invalid deployment operations")
        if len(operations) != len(set(operations)):
            raise DeploymentError("duplicate deployment operation")
        if operations and (target != "pinky_pro" or data["status"] != "existing_implementation"):
            raise DeploymentError("target has no reviewed deployment executor")
        # Reviewed backend bindings are code-owned; descriptor edits cannot enable another executor.
        delivery = _PINKY_DELIVERY if target == "pinky_pro" else dict.fromkeys(_PINKY_DELIVERY) | {"platform": _PLATFORMS.get(target)}
        if target != "pinky_pro" and target not in _PLATFORMS or data["delivery"] != delivery:
            raise DeploymentError("target delivery capabilities differ from the reviewed backend")
        targets[target] = data
    return targets


def require_image_backend(target, *, root=ROOT):
    """Resolve the reviewed image profile before an operator starts preparation."""
    inventory = load_targets(root)
    if target not in inventory:
        raise DeploymentError("unknown deployment target")
    info = inventory[target]
    if target != "pinky_pro" or info["status"] != "existing_implementation":
        raise DeploymentError(info["reason"])
    return info["delivery"]


def dispatch(target, operation, robot, *, tarball=None, public_key=None, execute=False, runner=None):
    inventory = load_targets()
    if target not in inventory:
        raise DeploymentError("unknown deployment target")
    if operation not in ("apply", "rollback"):
        raise DeploymentError("unknown deployment operation")
    if not isinstance(robot, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]*", robot):
        raise DeploymentError("robot must be a hostname or IPv4 address without shell characters")
    info = inventory[target]
    result = {"target": target, "deployment": info["deployment"], "operation": operation,
              "status": info["status"], "reason": info["reason"], "executed": False,
              "command": [], "returncode": 0, "delivery": info["delivery"]}
    if operation not in info["operations"]:
        if execute:
            raise DeploymentError(info["reason"])
        result["blocked"] = True
        return result
    # Descriptors never supply programs or unlock a new executor.
    if target != "pinky_pro":
        raise DeploymentError("target has no reviewed deployment executor")
    if operation == "apply" and not tarball:
        raise DeploymentError("apply requires a signed release tarball")
    if operation == "rollback" and tarball:
        raise DeploymentError("rollback does not accept a tarball")
    command = [shutil.which("pwsh") or "powershell.exe", "-NoProfile", "-NonInteractive", "-File",
               str(ROOT / "deploy/robot/pinky_pro/rosy-release-push.ps1"), "-Robot", robot]
    command += ["-Tarball", str(tarball)] if operation == "apply" else ["-Rollback"]
    if public_key:
        command += ["-PublicKeyPath", str(public_key)]
    result["command"] = command
    if execute:
        try:
            completed = (runner or subprocess.run)(command, check=False, stdout=sys.stderr)
        except OSError as exc:
            raise DeploymentError("deployment executor could not start") from exc
        result["executed"] = True
        result["returncode"] = completed.returncode
    return result
