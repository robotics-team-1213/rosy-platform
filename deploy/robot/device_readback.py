#!/usr/bin/env python3
"""Collect a bounded, secret-free Rosy OS installation readback.

The output is evidence for the DEVICE gate.  It describes the host identity,
the immutable release selected by the activation record, its signed checksum
verification status, the core container, and the ROS graph observed from that
container.  It never serializes the installer's environment wholesale because
that file may contain API tokens.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import platform
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


SCHEMA_VERSION = 1
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_REVISION = re.compile(r"^[0-9a-f]{40}$")
_IMAGE_DIGEST = re.compile(r"@(?P<digest>sha256:[0-9a-f]{64})$")
_KEY_ID = re.compile(r"^[a-z0-9][a-z0-9-]{2,63}$")


def _rooted(root: Path, absolute: str) -> Path:
    """Map an absolute device path into a fake root when tests provide one."""

    return Path(absolute) if root == Path("/") else root / absolute.lstrip("/")


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        return None


def _parse_key_value(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    raw = _read(path)
    if raw is None:
        return values
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            values[key] = value.strip().strip('"').strip("'")
    return values


def _invoke(
    run: Callable[..., subprocess.CompletedProcess[str]],
    command: list[str],
    *,
    timeout: float = 5.0,
) -> dict[str, Any]:
    try:
        result = run(command, timeout=timeout)
    except (OSError, subprocess.SubprocessError, TimeoutError) as exc:
        return {"ok": False, "stdout": "", "stderr": str(exc)}
    stdout = (result.stdout or "").strip()
    stderr = (result.stderr or "").strip()
    return {"ok": result.returncode == 0, "stdout": stdout, "stderr": stderr}


def _device_run(command: list[str], *, timeout: float) -> subprocess.CompletedProcess[str]:
    """Run one bounded read-only probe with text capture enabled."""

    return subprocess.run(
        command,
        capture_output=True,
        check=False,
        text=True,
        timeout=timeout,
    )


def _os_release(root: Path) -> dict[str, str]:
    values = _parse_key_value(_rooted(root, "/etc/os-release"))
    return {
        key: values[key]
        for key in ("ID", "VERSION_ID", "VERSION_CODENAME", "PRETTY_NAME")
        if key in values
    }


def _activation(root: Path) -> tuple[dict[str, Any] | None, str | None]:
    path = _rooted(root, "/var/lib/rosy/activation.json")
    raw = _read(path)
    if raw is None:
        return None, "activation_missing"
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None, "activation_malformed"
    if not isinstance(data, dict):
        return None, "activation_not_object"
    if data.get("schema_version") != SCHEMA_VERSION:
        return None, "activation_schema_unknown"
    required = (
        "release_id",
        "release_path",
        "config_generation",
        "data_generation",
        "runtime_mode",
        "activated_at",
    )
    if any(field not in data for field in required):
        return None, "activation_fields_missing"
    if data.get("runtime_mode") != "core":
        return None, "activation_runtime_mode_not_core"
    return {field: data[field] for field in ("schema_version", *required)}, None


def _load_signature_verifier(root: Path):
    """Load the release verifier shipped with this Rosy installation."""

    candidates = [
        _rooted(root, "/opt/rosy/native-runtime/signing.py"),
        _rooted(root, "/opt/rosy/deploy/release/signing.py"),
        Path(__file__).resolve().parents[1] / "release" / "signing.py",
    ]
    for module_path in candidates:
        if not module_path.is_file():
            continue
        module_name = "rosy_device_release_signing"
        spec = importlib.util.spec_from_file_location(module_name, module_path)
        if spec is None or spec.loader is None:
            continue
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        return module
    return None


def _signature_status(root: Path, release_dir: Path, key_id: Any) -> dict[str, str]:
    """Verify the signed checksum list without exposing payload or secrets."""

    if not isinstance(key_id, str) or not _KEY_ID.fullmatch(key_id):
        return {"status": "unavailable", "reason": "signing_key_id_invalid"}
    sums_path = release_dir / "SHA256SUMS"
    signature_path = release_dir / "SHA256SUMS.sig"
    if not sums_path.is_file():
        return {"status": "unavailable", "reason": "checksum_list_missing"}
    if not signature_path.is_file():
        return {"status": "unavailable", "reason": "signature_missing"}
    public_key = _rooted(root, f"/etc/rosy/trusted-release-keys/{key_id}.pem")
    if not public_key.is_file():
        return {"status": "unavailable", "reason": "trusted_key_missing"}
    try:
        sums = sums_path.read_bytes()
        signature = signature_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return {"status": "unverified", "reason": "SIGNATURE_MALFORMED"}
    except OSError:
        return {"status": "unavailable", "reason": "signature_material_unreadable"}

    verifier = _load_signature_verifier(root)
    if verifier is None:
        return {"status": "unavailable", "reason": "signature_verifier_missing"}
    try:
        rejections = verifier.verify_release_files(release_dir, public_key)
    except verifier.SigningToolMissing:
        return {"status": "unavailable", "reason": "openssl_missing"}
    except (OSError, RuntimeError, ValueError):
        return {"status": "unavailable", "reason": "signature_verifier_error"}
    if rejections:
        return {"status": "unverified", "reason": rejections[0].code}
    return {"status": "verified"}


def _artifact(root: Path, activation: dict[str, Any] | None) -> dict[str, Any]:
    if activation is None:
        return {"status": "unavailable", "reason": "manifest_missing"}
    release_path = activation.get("release_path")
    if not isinstance(release_path, str):
        return {"status": "unavailable", "reason": "release_path_invalid"}
    try:
        relative_release = Path(release_path).relative_to("/opt/rosy/releases")
    except ValueError:
        return {"status": "unavailable", "reason": "release_path_invalid"}
    if not relative_release.parts or ".." in relative_release.parts:
        return {"status": "unavailable", "reason": "release_path_invalid"}
    release_dir = _rooted(root, release_path)
    releases_root = _rooted(root, "/opt/rosy/releases")
    try:
        release_dir.resolve().relative_to(releases_root.resolve())
    except (OSError, ValueError):
        return {"status": "unavailable", "reason": "release_path_invalid"}
    manifest_path = release_dir / "manifest.json"
    raw = _read(manifest_path)
    if raw is None:
        return {"status": "unavailable", "reason": "manifest_missing"}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {"status": "unavailable", "reason": "manifest_malformed"}
    if not isinstance(data, dict):
        return {"status": "unavailable", "reason": "manifest_not_object"}
    containers = data.get("containers")
    if not isinstance(containers, dict):
        return {"status": "unavailable", "reason": "container_digests_missing"}
    selected = {
        "status": "available",
        "release_id": data.get("release_id"),
        "git_revision": data.get("git_revision"),
        "target": data.get("target"),
        "containers": {
            key: containers.get(key) for key in ("rosy_core", "rosy_io")
        },
        "signing_key_id": data.get("signing_key_id"),
    }
    if not isinstance(selected["release_id"], str) or not isinstance(selected["git_revision"], str):
        return {"status": "unavailable", "reason": "manifest_identity_missing"}
    if not _REVISION.fullmatch(selected["git_revision"]):
        return {"status": "unavailable", "reason": "manifest_revision_invalid"}
    if not all(_DIGEST.fullmatch(str(value or "")) for value in selected["containers"].values()):
        return {"status": "unavailable", "reason": "container_digests_invalid"}
    selected["signature"] = _signature_status(root, release_dir, selected["signing_key_id"])
    return selected


def _ros_graph(
    run: Callable[..., subprocess.CompletedProcess[str]],
    core_id: str | None,
    namespace: str | None,
) -> dict[str, Any]:
    if not core_id:
        return {"status": "unavailable", "reason": "core_container_missing"}
    nodes = _invoke(run, ["docker", "exec", core_id, "ros2", "node", "list"])
    node_names = [line for line in nodes["stdout"].splitlines() if line.strip()]
    graph: dict[str, Any] = {
        "status": "available" if nodes["ok"] else "unavailable",
        "nodes": node_names,
    }
    if namespace:
        topic = _invoke(
            run,
            ["docker", "exec", core_id, "ros2", "topic", "info", f"/{namespace}/cmd_vel"],
        )
        match = re.search(r"Publisher count:\s*(\d+)", topic["stdout"])
        graph["cmd_vel_publishers"] = int(match.group(1)) if match else None
    else:
        graph["cmd_vel_publishers"] = None
    return graph


def _dev_overlay(
    root: Path,
    run: Callable[..., subprocess.CompletedProcess[str]],
    core_id: str | None,
) -> dict[str, Any]:
    """A bench overlay is not a signed release. Env wins over a leftover marker."""

    marker = _rooted(root, "/etc/rosy/dev-overlay.json").is_file()
    dropin = _rooted(root, "/etc/systemd/system/rosy-core.service.d/dev-overlay.conf").is_file()
    env_on = False
    if core_id:
        probed = _invoke(run, ["docker", "exec", core_id, "printenv", "ROSY_DEV_OVERLAY"])
        env_on = probed["ok"] and probed["stdout"].strip() == "1"
    if not (env_on or marker or dropin):
        return {"dev_overlay": False}
    return {"dev_overlay": True, "dev_overlay_reason": "active" if env_on else "stale"}


def collect_readback(
    *,
    root: Path = Path("/"),
    run: Callable[..., subprocess.CompletedProcess[str]] = _device_run,
) -> dict[str, Any]:
    """Collect readback without mutating the Device or contacting the network."""

    install_root = _rooted(root, "/opt/rosy")
    env_path = install_root / "deploy" / "robot" / ".env"
    compose_path = install_root / "deploy" / "robot" / "compose.yaml"
    env = _parse_key_value(env_path)

    architecture_result = _invoke(run, ["dpkg", "--print-architecture"])
    architecture = architecture_result["stdout"] or platform.machine()
    model = _read(_rooted(root, "/proc/device-tree/model"))
    if model:
        model = model.rstrip("\x00")
    hostname = _read(_rooted(root, "/etc/hostname")) or (
        _invoke(run, ["hostname", "-s"])["stdout"] or "unavailable"
    )

    activation, activation_reason = _activation(root)
    artifact = _artifact(root, activation)

    systemd = _invoke(run, ["systemctl", "is-active", "--quiet", "rosy-runtime.service"])
    compose_prefix = [
        "docker",
        "compose",
        "--env-file",
        str(env_path),
        "-f",
        str(compose_path),
    ]
    core_id_result = _invoke(run, [*compose_prefix, "ps", "-q", "rosy-core"])
    core_id = core_id_result["stdout"].splitlines()[0] if core_id_result["stdout"] else None
    core: dict[str, Any] = {
        "container_id": core_id,
        "status": "running" if core_id else "unavailable",
    }
    if core_id:
        inspected = _invoke(
            run,
            [
                "docker",
                "inspect",
                "--format",
                "{{.Image}}\t{{.Config.Image}}\t{{if .State.Health}}{{.State.Health.Status}}{{end}}",
                core_id,
            ],
        )
        parts = inspected["stdout"].split("\t")
        if inspected["ok"] and len(parts) >= 3:
            core["image_id"], core["image"] = parts[:2]
            core["health"] = parts[2] or "unknown"
        else:
            core["health"] = "unavailable"

    identity = {
        key: env[key]
        for key in ("ROSY_ROBOT_NUMBER", "ROS_DOMAIN_ID", "ROSY_NAMESPACE", "ROSY_RUNTIME_MODE")
        if key in env
    }
    identity = {
        "robot_number": identity.get("ROSY_ROBOT_NUMBER"),
        "ros_domain_id": identity.get("ROS_DOMAIN_ID"),
        "namespace": identity.get("ROSY_NAMESPACE"),
        "runtime_mode": identity.get("ROSY_RUNTIME_MODE", "core"),
    }
    ros_graph = _ros_graph(run, core_id, identity["namespace"])

    configured_image_digest = _IMAGE_DIGEST.search(str(core.get("image", "")))
    expected_image_digest = (
        artifact.get("containers", {}).get("rosy_core")
        if isinstance(artifact.get("containers"), dict)
        else None
    )
    if configured_image_digest is None:
        core["image_match"] = "unverified"
    elif configured_image_digest.group("digest") == expected_image_digest:
        core["image_match"] = "verified"
    else:
        core["image_match"] = "mismatch"

    overlay = _dev_overlay(root, run, core_id)
    identity_ok = all(identity[key] for key in ("robot_number", "ros_domain_id", "namespace"))
    artifact_ok = (
        artifact.get("status") == "available"
        and isinstance(artifact.get("signature"), dict)
        and artifact["signature"].get("status") == "verified"
    )
    activation_ok = activation is not None and activation.get("runtime_mode") == "core"
    core_ok = (
        systemd["ok"]
        and core.get("health") == "healthy"
        and core.get("image_match") == "verified"
    )
    architecture_ok = architecture in {"arm64", "aarch64"}
    graph_ok = ros_graph.get("status") == "available" and ros_graph.get("cmd_vel_publishers") == 1

    return {
        "schema_version": SCHEMA_VERSION,
        "collected_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "device": {
            "hostname": hostname,
            "model": model or "unavailable",
            "architecture": architecture,
            "os": _os_release(root),
        },
        "identity": identity,
        "activation": activation or {"status": "unavailable", "reason": activation_reason},
        "artifact": artifact,
        "runtime": {
            "systemd": "active" if systemd["ok"] else "inactive",
            "core": core,
        },
        "ros_graph": ros_graph,
        "dev_overlay": overlay["dev_overlay"],
        **({"dev_overlay_reason": overlay["dev_overlay_reason"]} if overlay["dev_overlay"] else {}),
        "gates": {
            "device_runtime": "HOLD" if overlay["dev_overlay"] or not all((identity_ok, activation_ok, artifact_ok, core_ok, architecture_ok, graph_ok)) else "GO",
            "field": "HOLD",
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="emit JSON (the default)")
    args = parser.parse_args(argv)
    del args
    print(json.dumps(collect_readback(), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
