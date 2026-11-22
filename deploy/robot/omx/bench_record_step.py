"""What the bench is waiting for between pressing Start/Home and the first recorded frame (status.json "starting_step").

Values: follower_home, leader_align (state "step"), then from the recorder's own log: starting_recorder (no log yet),
connecting_cameras (lerobot up, "Recording episode" not printed), aligning (guard phase=aligning; "starting_deg_left" is the
largest remaining joint error). None once the guard tracks. "starting_arm" is the arm whose step is shown (arm_ab homes one after the other). The step never goes
backwards within one start (the furthest one reached is kept), and is cleared when the start ends. Also: the home-skip test of go_home.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import signal
import subprocess
import time


ORDER = ("follower_home", "leader_align", "starting_recorder", "connecting_cameras", "aligning", "done")


def _raw_step(state, tail_bytes):
    status = state.get("status")
    if status == "homing":
        return state.get("step"), None
    if status not in ("handing_over", "recording") or not state.get("folder"):
        return None, None
    log = Path(state["folder"]) / "bench.log"
    try:
        with log.open("rb") as handle:
            handle.seek(max(0, log.stat().st_size - tail_bytes))
            text = handle.read().decode("utf-8", errors="replace")
    except OSError:
        return ("starting_recorder" if status == "handing_over" else "done"), None
    if "Recording episode" not in text:
        return ("connecting_cameras" if "Using video codec" in text else "starting_recorder"), None
    last_aligning, last_aligned = text.rfind("phase=aligning"), text.rfind(": aligned;")
    if last_aligning > last_aligned:
        found = re.findall(r"error_deg=([0-9.]+)", text[last_aligning:].split("\n", 1)[0])
        return "aligning", (max(map(float, found)) if found else None)
    return "done", None


def starting_step(state, memory=None, tail_bytes=60000):
    """memory: a dict the caller keeps between polls; with it the step never goes back within one start."""
    memory = {} if memory is None else memory
    step, degrees = _raw_step(state, tail_bytes)
    if state.get("status") not in ("homing", "handing_over", "recording"):
        memory.clear()  # the start has ended
        return {"starting_step": None, "starting_deg_left": None, "starting_arm": None}
    key = (state.get("name"), state.get("step_arm"), state.get("folder"))
    if memory.get("key") != key:
        memory.clear()
        memory["key"] = key
    if step in ORDER and ORDER.index(step) < memory.get("rank", -1):
        step, degrees = ORDER[memory["rank"]], None  # an earlier phrase fell out of the log tail: keep the furthest step
    elif step in ORDER:
        memory["rank"] = ORDER.index(step)
    return {"starting_step": None if step == "done" else step, "starting_deg_left": degrees, "starting_arm": state.get("step_arm")}


HOME_SKIP_UNITS = 1.0  # normalized units (200 per calibrated range, about 1.8 degrees on a full range): inside 2 degrees


def at_home(live_path, library_path, since, now=time.time, units=HOME_SKIP_UNITS):
    """True when the runner's live body pose (read from a file the running recorder already writes: no extra bus
    process) is within `units` of the library home the real home uses (its last frame) on all five body joints. Written after
    `since` (this request began) and at most 3 s ago. Any doubt (stale, missing) is False."""
    try:
        written = Path(live_path).stat().st_mtime
        if written <= since or not 0 <= now() - written <= 3.0:
            return False
        live = json.loads(Path(live_path).read_text(encoding="utf-8"))["state"]
        home = json.loads(Path(library_path).read_text(encoding="utf-8"))["chunks"]["home"][-1]
        return len(live) >= 5 and len(home) >= 5 and all(
            isinstance(a, (int, float)) and isinstance(b, (int, float)) and abs(a - b) <= units for a, b in zip(live[:5], home[:5]))
    except (OSError, ValueError, KeyError, IndexError, TypeError):
        return False


def stop_home_runner_now(io_dir):
    """Send 'stop now' over an existing chunk FIFO so an unmoved HOME_UNFOLDED runner exits torque OFF without folding."""
    if not (io_dir / "chunk-cmd").is_fifo():
        return False
    try:
        from cell_pipeline import FifoCell
        return bool(FifoCell(io_dir, {}).act("stop now").get("ok") is True)
    except Exception:
        return False


def supervised_fold_unfolded(bench, arm, stack, lib_p, io_dir, env):
    """Run D-1048 top-camera corridor fold (--supervised) on an unfolded arm; returns (ok, stop_sent, err_msg)."""
    from cell_task_exec import _arm_run_spec
    _, _, _, roi, site = _arm_run_spec(arm, bench.prep)
    out_p = bench.prep / ".bench-runs" / f"fold-{arm}-{time.time_ns()}.json"
    cmd = [bench.python, str(Path(__file__).resolve().with_name("cell_auto_fold.py")), "--supervised",
           "--arm", arm, "--config", str(stack), "--library", str(lib_p),
           "--site", site, "--roi", *map(str, roi), "--out", str(out_p)]
    try:
        res = subprocess.run(cmd, cwd=bench.prep, env=env, capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        bench._mark_manual(f"{arm} 안전 접기 시간 초과 (120s) — 팔 상태를 확인하세요")
        return False, False, f"{arm} 안전 접기 시간 초과 (120s)"
    data = {}
    try:
        if out_p.is_file():
            data = json.loads(out_p.read_text(encoding="utf-8"))
        elif (res.stdout or "").strip():
            data = json.loads((res.stdout or "").strip().splitlines()[-1])
    except (OSError, ValueError, TypeError, IndexError):
        data = {}
    if res.returncode == 0 and data.get("result") == "folded":
        return True, True, ""
    if data.get("ended") == "stop_now" or (data.get("unmoved") is True and stop_home_runner_now(io_dir)):
        return False, True, (
            f"{arm} 펼쳐진 팔 안전 접기 보류 ({data.get('reason') or '경로 차단'}) — 장애물·그리퍼 확인 후 다시 시도하세요"
        )
    detail = data.get("reason") or (res.stderr or res.stdout or "").strip()[-200:] or f"code={res.returncode}"
    return False, False, f"{arm} 안전 접기 중단 ({detail}) — 팔 상태를 확인하세요"


def resolve_home_failure(bench, arm, res, stack, lib_p, io_dir, env, fold_unfolded, stop_flag):
    """Handle failed --stage home: supervised corridor fold when opted in for HOME_UNFOLDED, else clean stop_now."""
    err = bench._home_failure(arm, res)
    unfolded = "home requires an empty, folded arm" in err
    if unfolded and fold_unfolded and arm in ("arm_a", "arm_b", "arm_s"):
        bench._set(step="fold_unfolded", step_arm=arm)
        ok, stop_sent, msg = supervised_fold_unfolded(bench, arm, stack, lib_p, io_dir, env)
        stop_flag[0] = stop_sent
        if not ok:
            raise ValueError(msg)
        return
    if unfolded:
        stop_flag[0] = stop_home_runner_now(io_dir)
    raise ValueError(err)


def finish_home_child(bench, rec_proc, rec_log_p, stop_sent=False):
    """Wait for home recorder child exit cleanly; skip SIGTERM fold when 'stop now' or fold already stopped it."""
    if rec_proc is None:
        return True
    clean = True
    try:
        if stop_sent:
            try:
                rec_proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                rec_proc.send_signal(signal.SIGTERM)
                rec_proc.wait(timeout=30)
        else:
            rec_proc.send_signal(signal.SIGTERM)
            rec_proc.wait(timeout=30)  # longer than the runner's own 15 s no-answer judgement
        clean = rec_proc.returncode == 0  # 75 = HOLD (torque kept ON), anything else is unconfirmed
        if not clean and bench._never_powered(rec_proc.returncode, rec_log_p):
            clean = bench._home_recovered = True
        if getattr(bench, "_person_needed", None):
            clean = False
    except subprocess.TimeoutExpired:
        clean = False
        rec_proc.kill()
        try:
            rec_proc.wait(timeout=5)
        except Exception:
            pass
    except Exception:
        clean = False
    return clean
