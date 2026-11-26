"""Read-only follower pose helpers (observer snapshot first, guarded CLI fallback, chunk home fallback)."""
from __future__ import annotations

import json
import math
from pathlib import Path
import sys
import time

if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

_NAMES = ("shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper")


def _ticks_to_norm(prep: Path, arm: str, ticks: list[float]) -> list[float] | None:
    if not isinstance(ticks, (list, tuple)) or len(ticks) != 6:
        return None
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(float(v)) for v in ticks):
        return None
    try:
        letter = arm.split("_")[-1] if "_" in arm else arm
        cfgs = sorted(Path(prep).glob(f"record-config-arm-{letter}*.json"))
        cfg = json.loads(cfgs[0].read_text(encoding="utf-8-sig")) if cfgs else {}
        robot = cfg.get("robot") if isinstance(cfg, dict) else None
        robot_id = str(robot.get("id") or "omx_follower_arm") if isinstance(robot, dict) else "omx_follower_arm"
        cal_p = Path.home() / ".cache/huggingface/lerobot/calibration/robots/omx_follower" / f"{robot_id}.json"
        if not cal_p.is_file():
            return None
        cal = json.loads(cal_p.read_text(encoding="utf-8"))
        if not isinstance(cal, dict):
            return None
        norm = []
        for i, n in enumerate(_NAMES):
            c = cal.get(n)
            if not isinstance(c, dict):
                return None
            lo, hi = float(c["range_min"]), float(c["range_max"])
            if not (math.isfinite(lo) and math.isfinite(hi) and hi > lo):
                return None
            v = ((float(ticks[i]) - lo) / (hi - lo) * 100.0) if i == 5 else ((float(ticks[i]) - lo) / (hi - lo) * 200.0 - 100.0)
            norm.append(round(max(-100.0, min(100.0, v)), 3))
        return norm
    except (OSError, ValueError, TypeError, AttributeError, KeyError):
        return None


def read_observer_norm_pose(prep: Path, arm: str, *, max_age_s: float = 5.0) -> list[float] | None:
    """Read live norm pose from fresh active observer motor-health/<arm>.json without opening serial ports."""
    mh = Path.home() / ".local/state/rosy/motor-health" / f"{arm}.json"
    if not mh.is_file():
        return None
    try:
        data = json.loads(mh.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("schema_version") != "rosy.motor-health.v1":
            return None
        if data.get("owner_id") != arm or data.get("status") != "active":
            return None
        obs_raw = data.get("observed_at")
        if isinstance(obs_raw, bool) or not isinstance(obs_raw, (int, float)):
            return None
        age = time.time() - float(obs_raw)
        if not (0.0 <= age <= max_age_s):
            return None
        motors = data.get("motors")
        if not isinstance(motors, list) or len(motors) != 6:
            return None
        by_id = {}
        for m in motors:
            if not isinstance(m, dict) or isinstance(m.get("id"), bool) or isinstance(m.get("present_raw"), bool):
                return None
            mid, pr = int(m["id"]), float(m["present_raw"])
            if not math.isfinite(pr):
                return None
            by_id[mid] = pr
        if not all(mid in by_id for mid in (11, 12, 13, 14, 15, 16)):
            return None
        return _ticks_to_norm(prep, arm, [by_id[mid] for mid in (11, 12, 13, 14, 15, 16)])
    except (OSError, ValueError, TypeError, AttributeError, KeyError):
        return None


def read_chunk_home_pose(prep: Path, arm: str) -> list[float] | None:
    """Fallback normalized home pose from the arm's calibrated home chunk library."""
    p = Path(prep) / "chunks-arm-s-inplace-live.json" if arm == "arm_s" else None
    if p is None or not p.is_file():
        return None
    try:
        root = json.loads(p.read_text(encoding="utf-8"))
        chunks = root.get("chunks") if isinstance(root, dict) else None
        home = chunks.get("home") if isinstance(chunks, dict) else None
        if not isinstance(home, list) or not home or not isinstance(home[-1], (list, tuple)) or len(home[-1]) != 6:
            return None
        out = []
        for v in home[-1]:
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                return None
            fv = float(v)
            if not math.isfinite(fv) or not (-100.0 <= fv <= 100.0):
                return None
            out.append(round(fv, 3))
        return out
    except (OSError, ValueError, TypeError, AttributeError):
        return None


def _read_held_cli_pose(prep: Path, arm: str, python_exe: str) -> list[float] | None:
    letter = arm.split("_")[-1] if "_" in arm else arm
    cfgs = sorted(Path(prep).glob(f"record-config-arm-{letter}*.json"))
    lh = Path(__file__).resolve().parent / "leader_home.py"
    if not cfgs or not lh.is_file():
        return None
    import subprocess
    import bench_record_guard
    try:
        out = subprocess.run([python_exe, str(lh), "--config", str(cfgs[0]), "--arm", arm, "--read-follower-pose"], capture_output=True, text=True, timeout=8)
        if out.returncode != 0:
            if bench_record_guard.follower_torque_on(out.stdout):
                (Path(prep) / ".bench-manual-check.json").write_text(json.dumps({"reason": bench_record_guard.FOLLOWER_TORQUE_ON}), encoding="utf-8")
            return None
        ticks = json.loads(out.stdout.strip().splitlines()[-1]).get("state")
        return _ticks_to_norm(prep, arm, ticks)
    except subprocess.TimeoutExpired:
        (Path(prep) / ".bench-manual-check.json").write_text(json.dumps({"reason": f"{arm} 팔로워 위치 읽기를 강제 종료했습니다 — 팔로워 토크 상태를 확인하세요"}), encoding="utf-8")
        return None
    except Exception:
        return None


def read_live_norm_pose(prep: Path, arm: str, python_exe: str | None = None, hold=None) -> list[float] | None:
    """Read follower current norm pose safely: fresh active observer first, then guarded CLI read."""
    if not python_exe or hold is None:
        return None
    import bench_record_guard
    manual = Path(prep) / ".bench-manual-check.json"
    if bench_record_guard.arm_free(arm, manual):
        return None
    if (obs := read_observer_norm_pose(prep, arm)) is not None:
        return obs
    handles, busy = hold()
    if busy:
        return None
    try:
        return None if bench_record_guard.arm_free(arm, manual) else _read_held_cli_pose(prep, arm, python_exe)
    finally:
        for handle in handles:
            handle.close()
