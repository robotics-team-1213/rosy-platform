"""Peer motor-health snapshot and folded-state verification for `cell_job_guards`."""
from __future__ import annotations

import json
import math
from pathlib import Path
import time
from typing import Any, Callable

FOLLOWER_JOINTS = ("shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper")


def finite_float(val: Any) -> float | None:
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        return None
    try:
        num = float(val)
    except OverflowError:
        return None
    return num if math.isfinite(num) else None


def live_folded(row: dict[str, Any]) -> bool | None:
    if isinstance(row.get("folded"), bool):
        return row["folded"]
    st = row.get("state")
    if isinstance(st, list) and len(st) >= 6 and all(
        isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(float(v)) for v in st[:6]
    ):
        return float(st[1]) <= -50.0 and float(st[2]) >= 45.0
    return None


def latest_status_row(status_path: Path) -> dict[str, Any] | None:
    try:
        lines = [ln.strip() for ln in status_path.read_text(encoding="utf-8", errors="replace").splitlines()[-25:] if ln.strip().startswith("{")]
    except OSError:
        return None
    for raw in reversed(lines):
        try:
            row = json.loads(raw)
        except ValueError:
            continue
        if isinstance(row, dict) and isinstance(row.get("state"), list):
            return row
    return None


def passive_motor_health_folded(
    peer: str,
    health_dir: Path | None,
    *,
    max_age_s: float,
    read_json_fn: Callable[[Path], dict[str, Any] | None],
    calibration_dir: Path | None = None,
) -> bool:
    """True only when a fresh passive motor-health snapshot proves peer is torque-off, fault-free, and folded."""
    if health_dir is None:
        return False
    doc = read_json_fn(health_dir / f"{peer}.json")
    if not isinstance(doc, dict) or doc.get("schema_version") != "rosy.motor-health.v1":
        return False
    if doc.get("owner_id") != peer or doc.get("status") != "active" or doc.get("stop_reasons"):
        return False
    obs_val = finite_float(doc.get("observed_at"))
    if obs_val is None:
        return False
    age = time.time() - obs_val
    if age > max_age_s or age < -2.0:
        return False
    motors = doc.get("motors")
    if (not isinstance(motors, list) or len(motors) != 6
            or [m.get("id") for m in motors if isinstance(m, dict)] != [11, 12, 13, 14, 15, 16]):
        return False
    cal_dir = calibration_dir if calibration_dir is not None else (
        Path.home() / ".cache" / "huggingface" / "lerobot" / "calibration" / "robots" / "omx_follower"
    )
    cal = read_json_fn(cal_dir / f"{peer}_follower.json")
    if not isinstance(cal, dict):
        return False
    pose: list[float] = []
    for idx, (jname, motor) in enumerate(zip(FOLLOWER_JOINTS, motors)):
        jcal = cal.get(jname)
        if not isinstance(jcal, dict):
            return False
        if "id" in jcal and (type(jcal["id"]) is not int or jcal["id"] != 11 + idx):
            return False
        if type(jcal.get("drive_mode")) is not int or jcal["drive_mode"] != 0:
            return False
        if type(jcal.get("homing_offset")) is not int or jcal["homing_offset"] != 0:
            return False
        lo, hi = jcal.get("range_min"), jcal.get("range_max")
        if type(lo) is not int or type(hi) is not int or not (0 <= lo < hi <= 4095):
            return False
        if (motor.get("torque_enabled") is not False or motor.get("fault") is not False
                or type(motor.get("hardware_error")) is not int or motor["hardware_error"] != 0):
            return False
        rval = finite_float(motor.get("present_raw"))
        if rval is None or not 0.0 <= rval <= 4095.0:
            return False
        frac = (rval - lo) / (hi - lo)
        val = frac * (100.0 if idx == 5 else 200.0) - (0.0 if idx == 5 else 100.0)
        if not math.isfinite(val):
            return False
        pose.append(val)
    return live_folded({"state": pose}) is True


def is_stale_row(row: dict[str, Any], max_age_s: float) -> bool:
    tval = finite_float(row.get("t"))
    return tval is not None and (time.time() - tval > max_age_s)


def live_hold_attach_err(
    arm: str | None,
    workdir: Path,
    lease_dir: Path,
    lock_dir: Path | None,
    *,
    session_lock_held_fn: Callable[[str, Path | None], bool],
    read_json_fn: Callable[[Path], dict[str, Any] | None],
    live_max_age_s: float,
    pid_alive_fn: Callable[[int], bool],
) -> str | None:
    """Confirm `arm` holds a fresh, non-interrupted active `human-hold` session safe for attach recovery."""
    import cell_arm_lease

    if arm not in ("arm_a", "arm_b", "arm_s"):
        return f"unsupported arm for live-hold recovery: {arm}"
    live = read_json_fn(workdir / f"chunk-io-{arm.split('_')[-1]}" / "live.json")
    if live is None:
        return f"no live.json for {arm}"
    if live.get("human_hold_latched") is not True:
        return f"{arm} is not in an active human-hold"
    if live.get("torque_hold_commanded") is not True:
        return f"{arm} human-hold torque hold is not confirmed"
    if live.get("chunk") is not None or live.get("interrupt"):
        return f"{arm} has an active chunk or shutdown interrupt"
    tval = finite_float(live.get("t"))
    if tval is None or not (-2.0 <= time.time() - tval <= live_max_age_s):
        return f"{arm} live hold state is stale"
    if session_lock_held_fn(arm, lock_dir):
        return None
    lease = read_json_fn(lease_dir / f"{arm}.json")
    if lease and cell_arm_lease.live(lease):
        pid = lease.get("pid")
        if isinstance(pid, int) and not isinstance(pid, bool) and pid > 0 and pid_alive_fn(pid):
            return None
    return f"no live session or lease holds {arm}"
