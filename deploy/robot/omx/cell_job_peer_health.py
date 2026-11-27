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


# Per-joint slack around the arm's own park/home/standby poses: pan, lift, elbow, wrist flex, wrist roll (the jaw does not count).
FOLD_TOL = (20.0, 10.0, 15.0, 12.0, 20.0)  # elbow is wider: a limp arm sags there first (11-26 pose, test_omx_policy_drive)
FOLD_POSES = ("park", "home", "standby")


def _poses(source: Any) -> list[list[float]]:
    """Fold poses from a chunk library (chunks.park/home/standby: last frame) or a cell config (plan.home/park: one pose or frames)."""
    if not isinstance(source, dict):
        return []
    if isinstance(source.get("chunks"), dict):
        entries = [source["chunks"].get(n) for n in FOLD_POSES]
    else:
        plan = source.get("plan") if isinstance(source.get("plan"), dict) else source
        entries = [plan.get(n) for n in FOLD_POSES]
    out = []
    for ent in entries:
        pose = ent[-1] if isinstance(ent, list) and ent and isinstance(ent[-1], list) else ent
        if isinstance(pose, list) and len(pose) >= 5 and all(finite_float(v) is not None for v in pose[:5]):
            out.append([float(v) for v in pose[:5]])
    return out


def fold_ranges(*sources: Any) -> list[tuple[float, float]] | None:
    """Per-joint (lo, hi) allowed while folded, from the arm's own library/config; None means no usable pose (coarse rule)."""
    poses = [p for src in sources for p in _poses(src)]
    if not poses:
        return None
    return [(min(p[i] for p in poses) - FOLD_TOL[i], max(p[i] for p in poses) + FOLD_TOL[i]) for i in range(5)]


def fold_basis(*sources: Any) -> str:
    return "calibrated" if fold_ranges(*sources) else "coarse"


def arm_library_path(workdir: Path, arm: str) -> Path | None:
    """The arm's own chunk library (or, failing that, its cell config) in the workdir; None when there is none to narrow the fold rule."""
    letter = arm.split("_")[-1]
    for pattern in (f"chunks-arm-{letter}-*.json", f"cell-{letter}.json"):
        if found := sorted(Path(workdir).glob(pattern)):
            return found[0]
    return None


def live_folded(row: dict[str, Any], *sources: Any, include_wrist_roll: bool = True) -> bool | None:
    """Folded when lift/elbow pass the coarse rule and, given the arm's library/config, body joints sit in range."""
    if isinstance(row.get("folded"), bool):
        return row["folded"]
    st = row.get("state")
    if isinstance(st, list) and len(st) >= 6 and all(
        isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(float(v)) for v in st[:6]
    ):
        if not (float(st[1]) <= -50.0 and float(st[2]) >= 45.0):
            return False
        ranges = fold_ranges(*sources)
        limit = 5 if include_wrist_roll else 4
        return ranges is None or all(lo <= float(st[i]) <= hi for i, (lo, hi) in enumerate(ranges[:limit]))
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
    gripper_max: float | None = None,
    library: Any = None,
) -> bool:
    """True only when a fresh passive motor-health snapshot proves peer is torque-off, fault-free, and folded
    (and, with `gripper_max`, the jaws shut at or below it)."""
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
    if any(m.get("torque_enabled") is not False or m.get("fault") is not False
           or type(m.get("hardware_error")) is not int or m["hardware_error"] != 0 for m in motors):
        return False
    pose = calibrated_pose([m.get("present_raw") for m in motors], cal)
    return (pose is not None and live_folded({"state": pose}, library) is True
            and (gripper_max is None or pose[5] <= gripper_max))


def board_missing(arm: str, env_dir: Path | None = None) -> bool:
    """True only when the arm's observer env names a board by-id link that is not there; no env file proves nothing."""
    from observer_handoff_io import HandoffError, unit_env

    try:
        device = unit_env(arm, env_dir)["ROSY_OBSERVER_DEVICE"]
    except (HandoffError, UnicodeError):
        return False
    return not Path(device).exists()


def unknown_state(arm: str, live: dict[str, Any] | None, health_dir: Path, reason: str,
                  read_json_fn: Callable[[Path], dict[str, Any] | None]) -> dict[str, Any]:
    """Why the arm's current state is unknown, with the newest source clock of live.json or motor-health."""
    docs = ((live, "t"), (read_json_fn(health_dir / f"{arm}.json"), "observed_at"))
    stamps = [v for doc, key in docs if isinstance(doc, dict) and (v := finite_float(doc.get(key))) is not None]
    return {"reason": reason if stamps or reason == "board_missing" else "never_observed",
            "last_observed_at": max(stamps, default=None)}


def current_fold(arm: str, runner, live: dict[str, Any] | None, now: float, folded: bool | None, stale_latch: bool, *,
                 max_age_s: float, read_json_fn: Callable[[Path], dict[str, Any] | None]) -> tuple[bool | None, dict[str, Any] | None]:
    """(`folded`, unknown): only from a current reading, a fresh live.json row or a fresh passive proof of folded."""
    health = getattr(runner, "motor_health_dir", None) or (Path.home() / ".local" / "state" / "rosy" / "motor-health")
    if board_missing(arm, getattr(runner, "observer_env_dir", None)):
        return None, unknown_state(arm, live, health, "board_missing", read_json_fn)
    stamp = finite_float(live.get("t")) if isinstance(live, dict) else None
    if stale_latch or (stamp is not None and -2.0 <= now - stamp <= max_age_s):
        return folded, None
    if passive_motor_health_folded(arm, health, max_age_s=max_age_s, read_json_fn=read_json_fn,
                                   calibration_dir=getattr(runner, "calibration_dir", None)):
        return True, None
    return None, unknown_state(arm, live, health, "stale", read_json_fn)


def calibrated_positions_folded(positions, cal, library: Any = None, *, include_wrist_roll: bool = True) -> bool:
    pose = calibrated_pose(positions, cal)
    return pose is not None and live_folded({"state": pose}, library, include_wrist_roll=include_wrist_roll) is True


def calibrated_pose(positions, cal) -> list[float] | None:
    """The six raw readings as joint values (degrees-like for joints, 0..100 for the gripper), or None when unusable."""
    if len(positions) != 6 or not isinstance(cal, dict):
        return None
    pose: list[float] = []
    for idx, (jname, position) in enumerate(zip(FOLLOWER_JOINTS, positions)):
        jcal = cal.get(jname)
        if not isinstance(jcal, dict):
            return None
        if "id" in jcal and (type(jcal["id"]) is not int or jcal["id"] != 11 + idx):
            return None
        if type(jcal.get("drive_mode")) is not int or jcal["drive_mode"] != 0:
            return None
        if type(jcal.get("homing_offset")) is not int or jcal["homing_offset"] != 0:
            return None
        lo, hi = jcal.get("range_min"), jcal.get("range_max")
        if type(lo) is not int or type(hi) is not int or not (0 <= lo < hi <= 4095):
            return None
        rval = finite_float(position)
        if rval is None or not 0.0 <= rval <= 4095.0:
            return None
        frac = (rval - lo) / (hi - lo)
        val = frac * (100.0 if idx == 5 else 200.0) - (0.0 if idx == 5 else 100.0)
        if not math.isfinite(val):
            return None
        pose.append(val)
    return pose


# pivot.grip_closed 50.5 + the grip_to tolerance 1.5: open jaws (56-62) or jaws stopped on an object stay latched
LATCH_GRIPPER_SHUT_MAX = 52.0


def stale_latch_superseded(arm: str, live: dict[str, Any] | None, *, locked: bool, leased: bool, max_age_s: float,
                           health_dir: Path | None, read_json_fn: Callable[[Path], dict[str, Any] | None],
                           calibration_dir: Path | None = None) -> bool:
    """A human-hold latch left in live.json by a runner that is gone: no session lock or lease, the row is stale, and a
    fresh passive motor-health read shows the arm torque-off, fault-free and folded. The held torque the latch guarded
    no longer exists, and a new runner starts unlatched (2026-11-27 arm_b: a USB loss one second after the latch left it
    blocking the whole A/B cell, with no incident for the console to clear)."""
    return (isinstance(live, dict) and live.get("human_hold_latched") is True and not locked and not leased
            and is_stale_row(live, max_age_s)
            and passive_motor_health_folded(arm, health_dir, max_age_s=max_age_s, read_json_fn=read_json_fn,
                                            calibration_dir=calibration_dir, gripper_max=LATCH_GRIPPER_SHUT_MAX))


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
