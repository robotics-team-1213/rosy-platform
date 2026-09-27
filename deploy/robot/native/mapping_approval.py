#!/usr/bin/env python3
"""Seal measured native G4 trials and guard the navigation systemd unit.

This tool does not command a motor or start navigation. ``approve`` is an
operator-reviewed transition from raw commissioning evidence to root-owned records;
``check`` is the read-only systemd ExecCondition for every navigation start.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
import tempfile

try:
    import grp
except ImportError:  # host contract tests on Windows
    grp = None


sys.dont_write_bytecode = True
MAX_LINEAR_MPS = 0.03
MAX_ANGULAR_RPS = 0.10
MAX_TRAVEL_M = 0.10
MAX_STOP_LATENCY_S = 0.65
ZERO_EPSILON = 0.001
# Encoder quantization on the stationary Pinky has produced up to 0.00065 m/s
# and 0.0135 rad/s in CORE state. Keep command purity separate from measured
# motion/stop thresholds so idle ticks cannot prove movement or prevent a stop.
MEASURED_LINEAR_EPSILON = 0.002
MEASURED_ANGULAR_EPSILON = 0.02
DIRECTIONS = ("forward", "reverse", "cw", "ccw")
CAUSES = ("button_release", "command_loss")
HEX_40 = re.compile(r"[0-9a-f]{40}\Z")
HEX_64 = re.compile(r"[0-9a-f]{64}\Z")
RELEASE_ID = re.compile(r"[0-9]{4}\.[0-9]{2}\.[0-9]{2}-[0-9]{3}\Z")
EVIDENCE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*\.json\Z")


def _object(value, fields, label):
    if not isinstance(value, dict) or set(value) != set(fields):
        raise ValueError(f"{label} fields are incomplete or unknown")
    return value


def _text(value, label):
    if not isinstance(value, str) or not value.strip() or len(value) > 120:
        raise ValueError(f"{label} is invalid")
    return value.strip()


def _number(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{label} must be finite")
    return float(value)


def _read_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"approval evidence cannot be read: {path}") from exc


def _sha256(content):
    return hashlib.sha256(content).hexdigest()


def _read_evidence(directory, name, digest):
    if not isinstance(name, str) or not EVIDENCE_NAME.fullmatch(name) or ".." in name:
        raise ValueError("evidence file name is invalid")
    if not isinstance(digest, str) or not HEX_64.fullmatch(digest):
        raise ValueError("evidence digest is invalid")
    path = directory / name
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"evidence file is missing or not regular: {name}")
    content = path.read_bytes()
    if _sha256(content) != digest:
        raise ValueError(f"evidence digest mismatch: {name}")
    try:
        return json.loads(content), content
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"evidence JSON is invalid: {name}") from exc


def _runtime(root):
    path = root / "etc/rosy/runtime.env"
    values = {}
    try:
        for line in path.read_text(encoding="ascii").splitlines():
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                raise ValueError("runtime.env contains a nonliteral line")
            key, value = line.split("=", 1)
            if key in values:
                raise ValueError("runtime.env has duplicate keys")
            values[key] = value
    except PermissionError:
        # systemd reads EnvironmentFile as root before applying User=rosy-io.
        values = {key: os.environ.get(key, "") for key in (
            "ROSY_ROBOT_NUMBER", "ROSY_RUNTIME_MODE", "ROSY_NAVIGATION_BACKEND",
            "ROSY_IO_DRIVE_ENABLED")}
    if not values.get("ROSY_ROBOT_NUMBER", "").isdigit():
        raise ValueError("runtime robot identity is missing")
    return values


def _device_identity(root, runtime_mode=None):
    values = _runtime(root)
    release = root / "opt/rosy/current"
    revision = (release / "source-revision.txt").read_text(encoding="ascii").strip()
    release_id = (release / "install/.rosy-release").read_text(encoding="ascii").strip()
    if not HEX_40.fullmatch(revision) or not RELEASE_ID.fullmatch(release_id):
        raise ValueError("active release identity is invalid")
    mode = runtime_mode or values.get("ROSY_RUNTIME_MODE")
    return {
        "robot_number": int(values["ROSY_ROBOT_NUMBER"]),
        "release_id": release_id,
        "source_revision": revision,
        "runtime_mode": mode,
        "navigation_backend": values.get("ROSY_NAVIGATION_BACKEND"),
        "drive_enabled": values.get("ROSY_IO_DRIVE_ENABLED"),
    }


def _validate_preflight(raw):
    _object(raw, ("configured_ids", "responded_ids", "torque_free"), "motor preflight")
    if raw["configured_ids"] != [1, 2] or raw["responded_ids"] != [1, 2]:
        raise ValueError("motor preflight must show both configured IDs")
    if raw["torque_free"] is not True:
        raise ValueError("motor preflight must be torque-free")


def _validate_trial(raw, direction, cause):
    _object(raw, (
        "direction", "stop_cause", "requested_linear_mps",
        "requested_angular_rps", "stop_requested_at", "samples",
    ), "trial")
    if raw["direction"] != direction or raw["stop_cause"] != cause:
        raise ValueError("trial direction or stop cause differs from manifest")
    linear = _number(raw["requested_linear_mps"], "requested linear speed")
    angular = _number(raw["requested_angular_rps"], "requested angular speed")
    if abs(linear) > MAX_LINEAR_MPS or abs(angular) > MAX_ANGULAR_RPS:
        raise ValueError("requested speed exceeds the commissioning envelope")
    if direction == "forward" and not (linear > ZERO_EPSILON and abs(angular) <= ZERO_EPSILON):
        raise ValueError("forward trial command has the wrong direction")
    if direction == "reverse" and not (linear < -ZERO_EPSILON and abs(angular) <= ZERO_EPSILON):
        raise ValueError("reverse trial command has the wrong direction")
    if direction == "cw" and not (angular < -ZERO_EPSILON and abs(linear) <= ZERO_EPSILON):
        raise ValueError("clockwise trial command has the wrong direction")
    if direction == "ccw" and not (angular > ZERO_EPSILON and abs(linear) <= ZERO_EPSILON):
        raise ValueError("counterclockwise trial command has the wrong direction")
    stop_at = _number(raw["stop_requested_at"], "stop time")
    samples = raw["samples"]
    if not isinstance(samples, list) or len(samples) < 4:
        raise ValueError("trial needs ordered raw velocity samples")
    observed = []
    for sample in samples:
        _object(sample, ("t", "linear", "angular", "x", "y", "yaw"), "odom sample")
        t = _number(sample["t"], "sample time")
        vx = _number(sample["linear"], "measured linear speed")
        wz = _number(sample["angular"], "measured angular speed")
        x = _number(sample["x"], "odom x")
        y = _number(sample["y"], "odom y")
        yaw = _number(sample["yaw"], "odom yaw")
        if abs(vx) > MAX_LINEAR_MPS or abs(wz) > MAX_ANGULAR_RPS:
            raise ValueError("measured speed exceeds the commissioning envelope")
        observed.append((t, vx, wz, x, y, yaw))
    if any(a[0] >= b[0] for a, b in zip(observed, observed[1:])):
        raise ValueError("velocity sample times must strictly increase")
    if not observed[0][0] < stop_at < observed[-1][0]:
        raise ValueError("stop time is outside the sample window")
    before = [(vx, wz) for t, vx, wz, _, _, _ in observed if t < stop_at]
    axis = {
        "forward": lambda vx, wz: vx > MEASURED_LINEAR_EPSILON,
        "reverse": lambda vx, wz: vx < -MEASURED_LINEAR_EPSILON,
        "cw": lambda vx, wz: wz < -MEASURED_ANGULAR_EPSILON,
        "ccw": lambda vx, wz: wz > MEASURED_ANGULAR_EPSILON,
    }[direction]
    if not before or not any(axis(vx, wz) for vx, wz in before):
        raise ValueError(f"trial has no measured {direction} motion before stop")
    after = [(t, vx, wz) for t, vx, wz, _, _, _ in observed if t >= stop_at]
    first_zero = next((index for index, (_, vx, wz) in enumerate(after)
                       if abs(vx) <= MEASURED_LINEAR_EPSILON
                       and abs(wz) <= MEASURED_ANGULAR_EPSILON), None)
    if first_zero is None or len(after) - first_zero < 2 or any(
            abs(vx) > MEASURED_LINEAR_EPSILON
            or abs(wz) > MEASURED_ANGULAR_EPSILON
            for _, vx, wz in after[first_zero:]):
        raise ValueError("trial has no sustained zero velocity")
    latency = after[first_zero][0] - stop_at
    if latency > MAX_STOP_LATENCY_S:
        raise ValueError("stop latency exceeds 0.65 seconds")
    start, end = observed[0], observed[-1]
    dx, dy = end[3] - start[3], end[4] - start[4]
    body_forward = math.cos(start[5]) * dx + math.sin(start[5]) * dy
    yaw_delta = math.atan2(math.sin(end[5] - start[5]), math.cos(end[5] - start[5]))
    if direction == "forward" and body_forward <= 0.001:
        raise ValueError("forward odom direction was not observed")
    if direction == "reverse" and body_forward >= -0.001:
        raise ValueError("reverse odom direction was not observed")
    if direction == "cw" and yaw_delta >= -0.005:
        raise ValueError("clockwise odom direction was not observed")
    if direction == "ccw" and yaw_delta <= 0.005:
        raise ValueError("counterclockwise odom direction was not observed")
    travel = sum(math.hypot(current[3] - previous[3], current[4] - previous[4])
                 for previous, current in zip(observed, observed[1:]))
    if travel > MAX_TRAVEL_M:
        raise ValueError("trial travel exceeds 10 cm")
    return latency


def validate_candidate(root, bundle, evidence_dir):
    """Verify a native G4 bundle against the current device and raw files."""
    _object(bundle, (
        "schema_version", "robot_number", "release_id", "source_revision",
        "operator", "safety_operator", "test_surface", "hardware_cut_reachable",
        "motor_preflight", "trials",
    ), "G4 bundle")
    device = _device_identity(root)
    if bundle["schema_version"] != 1 or type(bundle["robot_number"]) is not int:
        raise ValueError("G4 bundle schema or robot number is invalid")
    for name in ("robot_number", "release_id", "source_revision"):
        if bundle[name] != device[name]:
            raise ValueError(f"G4 {name} differs from the active release")
    if device["runtime_mode"] not in ("motor", "hardware"):
        raise ValueError("G4 approval requires a motor or hardware runtime")
    if bundle["test_surface"] not in ("floor", "lifted"):
        raise ValueError("G4 test surface must be floor or lifted")
    if bundle["hardware_cut_reachable"] is not True:
        raise ValueError("G4 hardware cut must be reachable")
    operator = _text(bundle["operator"], "operator")
    safety_operator = _text(bundle["safety_operator"], "safety operator")
    if operator == safety_operator:
        raise ValueError("G4 requires two different operators")
    preflight = _object(bundle["motor_preflight"], ("evidence_file", "sha256"), "motor preflight reference")
    raw, _ = _read_evidence(evidence_dir, preflight["evidence_file"], preflight["sha256"])
    _validate_preflight(raw)
    trials = bundle["trials"]
    if not isinstance(trials, list) or len(trials) != 8:
        raise ValueError("G4 requires eight trials")
    seen = set()
    files = {preflight["evidence_file"]}
    digests = {preflight["sha256"]}
    for trial in trials:
        _object(trial, ("direction", "stop_cause", "evidence_file", "sha256", "observed_direction"), "trial reference")
        key = (trial["direction"], trial["stop_cause"])
        if key not in {(direction, cause) for direction in DIRECTIONS for cause in CAUSES} or key in seen:
            raise ValueError("G4 trials need each direction and stop cause once")
        if trial["observed_direction"] is not True:
            raise ValueError("G4 trial direction was not observed")
        if trial["evidence_file"] in files or trial["sha256"] in digests:
            raise ValueError("G4 trials must use distinct raw evidence")
        raw, _ = _read_evidence(evidence_dir, trial["evidence_file"], trial["sha256"])
        _validate_trial(raw, *key)
        files.add(trial["evidence_file"])
        digests.add(trial["sha256"])
        seen.add(key)
    return {"ready": True, "trials": len(seen), "release_id": device["release_id"]}


def _atomic_write(path, content, *, group_id=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".mapping-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o640)
        if group_id is not None:
            os.chown(temporary, 0, group_id)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def approve(root, bundle, evidence_dir, *, reviewer):
    """Seal a verified, reviewed G4 bundle; marker files are written last."""
    root = Path(root)
    evidence_dir = Path(evidence_dir)
    reviewer = _text(reviewer, "reviewer")
    if _device_identity(root)["runtime_mode"] != "motor":
        raise ValueError("G4 approval requires motor runtime commissioning mode")
    if reviewer in (bundle.get("operator"), bundle.get("safety_operator")):
        raise ValueError("reviewer must be different from both operators")
    result = validate_candidate(root, bundle, evidence_dir)
    if root == Path("/") and os.geteuid() != 0:
        raise ValueError("approval must run as root")
    group_id = grp.getgrnam("rosy-io").gr_gid if root == Path("/") else None
    approvals = root / "etc/rosy/approvals"
    approvals.mkdir(mode=0o750, parents=True, exist_ok=True)
    if group_id is not None:
        os.chown(approvals, 0, group_id)
    os.chmod(approvals, 0o750)
    sealed = approvals / "g4-evidence"
    sealed.mkdir(mode=0o750, exist_ok=True)
    if group_id is not None:
        os.chown(sealed, 0, group_id)
    os.chmod(sealed, 0o750)
    references = [bundle["motor_preflight"], *bundle["trials"]]
    for reference in references:
        _, content = _read_evidence(evidence_dir, reference["evidence_file"], reference["sha256"])
        _atomic_write(sealed / reference["evidence_file"], content, group_id=group_id)
    bundle_bytes = _canonical(bundle)
    _atomic_write(approvals / "g4.bundle.json", bundle_bytes, group_id=group_id)
    common = {
        "schema_version": 1,
        "robot_number": bundle["robot_number"],
        "release_id": bundle["release_id"],
        "source_revision": bundle["source_revision"],
        "bundle_sha256": _sha256(bundle_bytes),
        "reviewer": reviewer,
        "approved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    for kind in ("hardware", "navigation"):
        _atomic_write(approvals / f"{kind}.approved", _canonical({**common, "kind": kind}), group_id=group_id)
    return result


def check(root=Path("/"), *, runtime_mode=None):
    """Read-only startup condition: verify all sealed evidence on every start."""
    root = Path(root)
    device = _device_identity(root, runtime_mode=runtime_mode)
    if device["runtime_mode"] != "hardware":
        raise ValueError("navigation requires hardware runtime mode")
    if device["navigation_backend"] not in ("localization", "slam"):
        raise ValueError("navigation backend is invalid")
    if device["drive_enabled"] != "true":
        raise ValueError("navigation requires the drive configuration to be enabled")
    approvals = root / "etc/rosy/approvals"
    bundle_path = approvals / "g4.bundle.json"
    if bundle_path.is_symlink() or not bundle_path.is_file():
        raise ValueError("G4 approval bundle is missing")
    bundle_bytes = bundle_path.read_bytes()
    bundle = _read_json(bundle_path)
    review = None
    for kind in ("hardware", "navigation"):
        path = approvals / f"{kind}.approved"
        if path.is_symlink() or not path.is_file() or path.stat().st_size == 0:
            raise ValueError(f"{kind} approval is missing or empty")
        marker = _object(_read_json(path), (
            "schema_version", "kind", "robot_number", "release_id",
            "source_revision", "bundle_sha256", "reviewer", "approved_at",
        ), f"{kind} approval")
        if marker["schema_version"] != 1 or marker["kind"] != kind:
            raise ValueError(f"{kind} approval is invalid")
        if marker["bundle_sha256"] != _sha256(bundle_bytes):
            raise ValueError(f"{kind} approval bundle digest differs")
        for name in ("robot_number", "release_id", "source_revision"):
            if marker[name] != device[name]:
                raise ValueError(f"{kind} approval {name} differs from the active release")
        _text(marker["reviewer"], "reviewer")
        _text(marker["approved_at"], "approved_at")
        marker_review = (marker["reviewer"], marker["approved_at"])
        if review is not None and marker_review != review:
            raise ValueError("hardware and navigation approvals require the same review")
        review = marker_review
    result = validate_candidate(root, bundle, approvals / "g4-evidence")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=Path("/"))
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("check", help="read-only navigation startup gate")
    approved = commands.add_parser("approve", help="review and seal measured G4 evidence")
    approved.add_argument("--bundle", required=True, type=Path)
    approved.add_argument("--evidence-dir", required=True, type=Path)
    approved.add_argument("--reviewer", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "approve":
            result = approve(args.root, _read_json(args.bundle), args.evidence_dir, reviewer=args.reviewer)
        else:
            result = check(args.root)
    except (OSError, ValueError) as exc:
        print(json.dumps({"ready": False, "reason": str(exc)}), file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
