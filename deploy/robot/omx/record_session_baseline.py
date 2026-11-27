"""One supervised pre-start restoration of the resting caps on a bound A/B follower."""
import json
import os
from pathlib import Path
import re
import sys
from tempfile import mkdtemp
import time

import commissioning_limits as limits
from cell_job_peer_health import FOLLOWER_JOINTS
from observer_handoff_io import unit_env
from register_probe import open_readonly_port, read_motors


def session_job_env(lease_owner, argv, job, arm, human, params):
    """Select the release wrapper and its bound recovery scope after job admission."""
    env = {**os.environ, "ROSY_ARM_LEASE_OWNER": lease_owner}
    env.pop("ROSY_BASELINE_RECOVERY_ARM", None)
    env.pop("ROSY_SESSION_CHUNKS_STRICT", None)
    if job in ("cell_policy_drive", "cell_policy_run") and arm == "arm_s" and params.get("library"):
        # shortcut: arm_s only; the A/B wrappers honour it too, extend once their policy libraries are checked for it
        env.update(ROSY_SESSION_CHUNKS=str(params["library"]), ROSY_SESSION_CHUNKS_STRICT="1")
    if job != "remap" or arm not in ("arm_a", "arm_b") or not human or params.get("person_at_switch") is not True:
        return env
    tools_dir = Path(__file__).resolve().parent
    argv[0] = str(tools_dir / "session-wrappers" / Path(argv[0]).name)
    env["TOOLS_ROOT"] = str(tools_dir.parents[2])
    env.setdefault("ROSY_SESSION_CHUNKS", f"chunks-arm-{arm[-1]}-beltend-ship-t2-canon.json")
    env["ROSY_BASELINE_RECOVERY_ARM"] = arm
    return env


class BaselineMismatch(SystemExit):
    """The idle check stopped before session caps or torque were applied."""


class FoldUnconfirmed(ValueError):
    """Registers were idle, but did not match the bound arm's calibrated identity (IDs, drive modes, offsets)."""


def check_session_idle(session, recovery_arm, robot, record):
    try:
        session._with_follower(session.check_idle)
    except BaselineMismatch:
        profile = record.get("operating_profile")
        if not recovery_arm or not profile:
            raise
        if profile["device_id"] != recovery_arm:
            raise SystemExit("REFUSED: baseline recovery arm differs from operating profile")
        record["baseline_receipt"] = restore(recovery_arm, robot)
        session.log(step="baseline_restored", receipt=record["baseline_receipt"])
        session._with_follower(session.check_idle)


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
        # no fold rule: torque is OFF (validate_motors) and a cap write never moves the arm (2026-11-28 user)
        if any(
            type(cal[name].get("id")) is not int or row["id"] != cal[name]["id"]
            or row["drive_mode"] != cal[name]["drive_mode"] or row["homing_offset_raw"] != cal[name]["homing_offset"]
            for name, row in zip(FOLLOWER_JOINTS, rows)
        ):
            raise FoldUnconfirmed("baseline restore requires hardware IDs and offsets matching the arm calibration")
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
