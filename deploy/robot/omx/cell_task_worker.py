#!/usr/bin/env python3
"""Autonomous OMX Cell Task Worker (`cell_task_worker.py`).

Single Responsibility:
  - Polls Fleet-R (`/api/fleet/pipeline/cell-tasks?status=QUEUED`) from `rosy-arm-cell`,
    claims queued tasks for `cell_s` (`arm_s`) and `cell_ab` (`arm_a`, `arm_b`),
    executes the OMX stage + real hardware trajectory with automatic fold-to-home (`folded: true`)
    before torque-off, and posts the completion receipt (`/api/fleet/pipeline/cell-tasks/{task_id}/complete`).
"""
from __future__ import annotations

import argparse
from concurrent.futures import Future, ThreadPoolExecutor
import json
import os
from pathlib import Path
import ssl
import subprocess
import time
from typing import Any, Callable
from urllib.request import Request, urlopen

from cell_camera_telemetry_sync import (
    DEFAULT_PREP_DIR,
    inspect_camera_frame_telemetry,
    upload_latest_camera_snapshots as _upload_latest_camera_snapshots,
)
from cell_control_core import ensure_omx_paths
from cell_fleet_handoff import handoff_refusal
from cell_fleet_pipeline import FleetModelPipeline

ensure_omx_paths()


def upload_latest_camera_snapshots(fleet_r_url: str, token: str, prep_dir: Path = DEFAULT_PREP_DIR) -> dict[str, int]:
    return _upload_latest_camera_snapshots(fleet_r_url, token, prep_dir=prep_dir, urlopen_fn=urlopen)

ARM_WRAPPERS: dict[str, tuple[str, str, float]] = {
    "arm_s": ("s", "with-session-arm-s-live.sh", -1.0),
    "arm_a": ("a", "with-session-arm-a-par.sh", -1.0),
    "arm_b": ("b", "with-session-arm-b-par.sh", -1.0),
}


def make_default_request_fn(fleet_r_url: str, token: str) -> Callable[[str, str, dict[str, Any] | None], dict[str, Any]]:
    ctx = ssl._create_unverified_context()
    base = fleet_r_url.rstrip("/")

    def _req(method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = Request(
            f"{base}{path}",
            data=data,
            method=method,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        )
        with urlopen(req, context=ctx, timeout=20) as resp:
            return json.load(resp)

    return _req


def _poll_status_ack(status_file: Path, start_line: int, prefix: str, timeout_s: float, poll_s: float = 0.015) -> tuple[dict[str, Any], int]:
    cursor = start_line
    deadline = time.monotonic() + timeout_s
    while True:
        if status_file.exists():
            lines = status_file.read_text(errors="replace").splitlines()
            for idx in range(cursor, len(lines)):
                raw = lines[idx].strip()
                if raw.startswith("{"):
                    ev = json.loads(raw)
                    if str(ev.get("command") or "").startswith(prefix):
                        return ev, idx + 1
        if time.monotonic() >= deadline:
            return {}, cursor
        time.sleep(poll_s)


def execute_live_hardware_arm(
    arm_id: str,
    *,
    prep_dir: Path = DEFAULT_PREP_DIR,
    jog_delta: float | None = None,
) -> dict[str, Any]:
    """Start or attach to the real hardware session for `arm_id`, execute motion, and stop with auto-fold home."""
    suffix, wrapper_script, default_delta = ARM_WRAPPERS.get(arm_id, ARM_WRAPPERS["arm_s"])
    delta = float(default_delta if jog_delta is None else jog_delta)
    io_dir = prep_dir / f"chunk-io-{suffix}"
    cmd_fifo = io_dir / "chunk-cmd"
    status_file = io_dir / "chunk-status.jsonl"
    n0 = len(status_file.read_text(errors="replace").splitlines()) if status_file.exists() else 0

    try:
        out = subprocess.check_output(["bash", str(prep_dir / wrapper_script), "true"], cwd=str(prep_dir), text=True)
    except subprocess.CalledProcessError:
        alt_io = prep_dir / f"chunk-io-{suffix}-r2s"
        alt_cmd = alt_io / "chunk-cmd"
        alt_status = alt_io / "chunk-status.jsonl"
        alt_n0 = len(alt_status.read_text(errors="replace").splitlines()) if alt_status.exists() else 0
        if alt_cmd.exists():
            try:
                fd = os.open(str(alt_cmd), os.O_WRONLY | os.O_NONBLOCK)
                try:
                    os.write(fd, b"stop\n")
                finally:
                    os.close(fd)
                _poll_status_ack(alt_status, alt_n0, "stop", 8.0)
            except Exception:
                pass
        out = subprocess.check_output(["bash", str(prep_dir / wrapper_script), "true"], cwd=str(prep_dir), text=True)
    if "session up" not in out:
        raise RuntimeError(f"Arm {arm_id} session failed to start: {out}")

    def _send_line(line: str) -> None:
        with open(cmd_fifo, "w", encoding="utf-8") as f:
            f.write(line.strip() + "\n")
            f.flush()

    cursor = n0

    def _wait_cmd(prefix: str, timeout_s: float) -> dict[str, Any]:
        nonlocal cursor
        ev, cursor = _poll_status_ack(status_file, cursor, prefix, timeout_s)
        return ev

    _send_line("state")
    _wait_cmd("state", 0.5)
    if arm_id == "arm_s" and (prep_dir / "chunks-arm-s-inplace-live.json").is_file():
        _send_line(f"load {prep_dir / 'chunks-arm-s-inplace-live.json'}")
        _wait_cmd("load", 0.3)
    _send_line(f"jog shoulder_pan.pos {delta}")
    _wait_cmd("jog", 2.0)
    _send_line("stop")
    stop_ev = _wait_cmd("stop", 40.0)
    if not stop_ev and status_file.exists():
        lines = status_file.read_text(errors="replace").splitlines()[n0:]
        events = [json.loads(l) for l in lines if l.strip().startswith("{")]
        stop_ev = next((e for e in reversed(events) if e.get("command") == "stop" and e.get("ok") is True), {})
    st_vals = stop_ev.get("state") if isinstance(stop_ev, dict) else None
    if isinstance(stop_ev, dict) and stop_ev.get("folded") is not True:
        if isinstance(st_vals, list) and len(st_vals) >= 3 and float(st_vals[1]) <= -50.0 and float(st_vals[2]) >= 45.0:
            stop_ev["folded"] = True

    lines = status_file.read_text(errors="replace").splitlines()[n0:] if status_file.exists() else []
    events = [json.loads(l) for l in lines if l.strip().startswith("{")]
    return {"arm": arm_id, "events_count": len(events), "stop_event": stop_ev}


def emergency_stop_arms(prep_dir: Path = DEFAULT_PREP_DIR) -> list[str]:
    """Send non-blocking emergency stop command to any active arm chunk-cmd FIFO when a human is detected."""
    stopped: list[str] = []
    for arm_id, (suffix, _, _) in ARM_WRAPPERS.items():
        for io_name in (f"chunk-io-{suffix}", f"chunk-io-{suffix}-r2s"):
            cmd_fifo = prep_dir / io_name / "chunk-cmd"
            if cmd_fifo.exists():
                try:
                    fd = os.open(str(cmd_fifo), os.O_WRONLY | os.O_NONBLOCK)
                    try:
                        os.write(fd, b"stop\n")
                        stopped.append(arm_id)
                    finally:
                        os.close(fd)
                except Exception:
                    pass
    return stopped


def poll_and_execute_once(
    pipeline: FleetModelPipeline,
    *,
    request_fn: Callable[[str, str, dict[str, Any] | None], dict[str, Any]],
    live_act_fn: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    prep_dir: Path = DEFAULT_PREP_DIR,
) -> list[dict[str, Any]]:
    """Poll queued tasks on Fleet-R and claim, execute, and complete each one in FIFO order."""
    listing = request_fn("GET", "/api/fleet/pipeline/cell-tasks?status=QUEUED", None)
    if (listing.get("human_safety") or {}).get("active_estop"):
        emergency_stop_arms(prep_dir)
        return []
    queued = list(listing.get("tasks") or [])
    completed_runs: list[dict[str, Any]] = []
    for task in queued:
        task_id = str(task["task_id"])
        cell_id = str(task["cell_id"])
        tier = int(task.get("tier", 1))
        claimed = request_fn("POST", "/api/fleet/pipeline/cell-tasks/claim", {"cell_id": cell_id, "task_id": task_id})
        if not claimed.get("claimed"):
            continue
        handoff = claimed["handoff"]
        if callable(live_act_fn) and handoff_refusal(pipeline, handoff, tier) is None:
            with ThreadPoolExecutor(max_workers=2) as pool:
                omx_fut = pool.submit(pipeline.run_contract_handoff_stage, handoff, stage_id=task_id, tier=tier)
                hw_fut = pool.submit(live_act_fn, handoff)
                omx_res = omx_fut.result()
                hw_tel = hw_fut.result()
        else:
            # Refused handoff (interlock, unknown site): the real arm is never called.
            omx_res = pipeline.run_contract_handoff_stage(handoff, stage_id=task_id, tier=tier)
            hw_tel = None
        receipt = omx_res["receipt"]
        done = request_fn("POST", f"/api/fleet/pipeline/cell-tasks/{task_id}/complete", {
            "phase": receipt["phase"], "goal_evidence_digest": receipt["goal_evidence_digest"],
            "reason": receipt["reason"], "receipt": receipt,
            "stage_result": omx_res["stage_result"], "hardware_telemetry": hw_tel,
        })
        completed_runs.append({
            "task_id": task_id, "cell_id": cell_id, "arm_id": handoff.get("arm_id"), "task": done["task"],
            "claim_gate": claimed["gate"], "release_gate": done["gate"], "omx_result": omx_res,
        })
    return completed_runs


def main() -> None:
    parser = argparse.ArgumentParser(description="Autonomous Fleet-R -> OMX Cell Task Worker")
    parser.add_argument("--fleet-r-url", default="https://192.168.1.93:8443")
    parser.add_argument("--token-file", default="~/.config/rosy-fleet-r-token")
    parser.add_argument("--work-dir", default="/tmp/rosy-omx-cell-task-worker")
    parser.add_argument("--prep-dir", default=str(DEFAULT_PREP_DIR))
    parser.add_argument("--interval-s", type=float, default=1.5)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--dry-run-hw", action="store_true")
    args = parser.parse_args()

    token = Path(args.token_file).expanduser().read_text(encoding="utf-8").strip()
    req_fn = make_default_request_fn(args.fleet_r_url, token)
    pipeline = FleetModelPipeline(work_dir=Path(args.work_dir))
    prep_dir = Path(args.prep_dir)
    bg_cam_pool = ThreadPoolExecutor(max_workers=1)
    bg_cam_fut: Future | None = None

    def _trigger_bg_cam_upload() -> None:
        nonlocal bg_cam_fut
        if bg_cam_fut is None or bg_cam_fut.done():
            bg_cam_fut = bg_cam_pool.submit(upload_latest_camera_snapshots, args.fleet_r_url, token, prep_dir)

    def _hw_act(handoff: dict[str, Any]) -> dict[str, Any]:
        arm_id = str(handoff.get("arm_id") or ("arm_s" if handoff.get("cell_id") == "cell_s" else "arm_a"))
        if args.dry_run_hw:
            return {"arm": arm_id, "events_count": 1, "stop_event": {"command": "stop", "ok": True, "folded": True}}
        res = execute_live_hardware_arm(arm_id, prep_dir=prep_dir)
        _trigger_bg_cam_upload()
        return res

    last_cam_push = 0.0
    while True:
        try:
            now_m = time.monotonic()
            if not args.dry_run_hw and (now_m - last_cam_push) >= 3.0:
                _trigger_bg_cam_upload()
                last_cam_push = now_m
            runs = poll_and_execute_once(pipeline, request_fn=req_fn, live_act_fn=_hw_act)
            for r in runs:
                stop_ev = (r["task"].get("hardware_telemetry") or {}).get("stop_event") or {}
                print(json.dumps({
                    "event": "task_completed", "task_id": r["task_id"], "cell_id": r["cell_id"], "arm_id": r["arm_id"],
                    "status": r["task"]["status"], "folded": stop_ev.get("folded"), "state": stop_ev.get("state"),
                }), flush=True)
        except Exception as exc:
            print(json.dumps({"event": "poll_error", "error": repr(exc)}), flush=True)
        if args.once:
            if bg_cam_fut is not None:
                bg_cam_fut.result(timeout=10.0)
            break
        time.sleep(max(0.5, float(args.interval_s)))


if __name__ == "__main__":
    main()
