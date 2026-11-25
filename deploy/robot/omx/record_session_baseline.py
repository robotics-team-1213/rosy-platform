"""One supervised pre-start restoration of the resting caps on a bound A/B follower."""
import json
import os
from pathlib import Path
import re
import sys
from tempfile import mkdtemp
import time

import commissioning_limits as limits
from cell_job_peer_health import FOLLOWER_JOINTS, calibrated_positions_folded
from observer_handoff_io import unit_env
from register_probe import open_readonly_port, read_motors


class BaselineMismatch(SystemExit):
    """The idle check stopped before session caps or torque were applied."""


class FoldUnconfirmed(ValueError):
    """Registers were idle, but did not confirm the bound arm's folded pose."""


def check_pending(arm):
    for candidate in ((arm,) if arm else ("arm_a", "arm_b")):
        if candidate in ("arm_a", "arm_b"):
            pending = limits.state_root() / candidate / "pending"
            if pending.exists():
                raise SystemExit(f"REFUSED: review interrupted baseline restoration at {pending}")


def _sync_dir(directory):
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _bound_device(arm, robot):
    device = Path(robot["port"])
    observed = Path(unit_env(arm)["ROSY_OBSERVER_DEVICE"])
    if device.parent != Path("/dev/serial/by-id") or device != observed or not device.is_symlink():
        raise SystemExit("REFUSED: recorder follower and arm observer must name the same by-id device")
    device.resolve(strict=True)
    return device


def _calibration(arm, robot):
    if not re.fullmatch(r"[a-zA-Z0-9_-]+", robot["id"]):
        raise SystemExit("REFUSED: invalid follower calibration ID")
    default = Path.home() / ".cache/huggingface/lerobot/calibration/robots/omx_follower"
    directory = Path(robot.get("calibration_dir") or default).expanduser()
    cal = json.loads((directory / (robot["id"] + ".json")).read_text(encoding="utf-8"))
    arm_cal = json.loads((default / (arm + "_follower.json")).read_text(encoding="utf-8"))
    if cal != arm_cal:
        raise SystemExit("REFUSED: recorder calibration differs from the named arm calibration")
    return cal


def restore(arm, robot):
    """Called under the record_session arm lease/lock after its first idle check closed the serial port."""
    device = _bound_device(arm, robot)
    cal = _calibration(arm, robot)

    def guarded_read(port):
        rows = read_motors(port)
        limits.validate_motors(rows)
        if not calibrated_positions_folded([r["position_raw"] for r in rows], cal) or any(
            type(cal[name].get("id")) is not int or row["id"] != cal[name]["id"]
            or row["drive_mode"] != cal[name]["drive_mode"] or row["homing_offset_raw"] != cal[name]["homing_offset"]
            for name, row in zip(FOLLOWER_JOINTS, rows)
        ):
            raise FoldUnconfirmed("baseline restore requires a calibrated folded pose with matching hardware offsets")
        return rows

    with open_readonly_port(device) as port:
        limits._refuse_pending(device)
        try:
            rows = guarded_read(port)
        except FoldUnconfirmed as exc:
            print(f"REFUSED: {exc}", file=sys.stderr)
            raise SystemExit(78) from exc  # before writes or session start
        if not limits.plan_limits(rows, limits.BASELINE):
            raise SystemExit("REFUSED: baseline mismatch changed before restoration")
        root = limits.state_root() / arm
        root.mkdir(parents=True, exist_ok=True)
        staging = Path(mkdtemp(prefix="binding-", dir=root))
        with (staging / "device").open("x", encoding="utf-8") as binding:
            binding.write(str(device))
            binding.flush()
            os.fsync(binding.fileno())
        _sync_dir(staging)
        pending = root / "pending"
        staging.rename(pending)  # publish the complete by-id binding while the serial port is still exclusive
        owner = pending.stat()
        for directory in (root, root.parent, root.parent.parent):
            _sync_dir(directory)
    evidence = pending / "commissioning"
    if limits._commission(["--device", str(device), "--baseline", "--output", str(evidence)],
                          read=guarded_read, owner=owner) != 0:
        raise SystemExit(f"REFUSED: baseline restoration failed, inspect {pending}")
    receipt = json.loads((evidence / "receipt.json").read_text())
    if receipt.get("configuration_verified") is not True or receipt.get("error") is not None:
        raise SystemExit(f"REFUSED: unverified baseline restoration at {pending}")
    with open_readonly_port(device) as port:
        if limits.plan_limits(guarded_read(port), limits.BASELINE):
            raise SystemExit(f"REFUSED: baseline independent readback failed, inspect {pending}")
    verified = root / f"verified-{time.time_ns()}"
    pending.rename(verified)
    _sync_dir(root)
    return str(verified / "commissioning/receipt.json")
