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
import json
from pathlib import Path
import ssl
import subprocess
import time
from typing import Any, Callable
from urllib.request import Request, urlopen

from cell_control_core import ensure_omx_paths
from cell_fleet_pipeline import FleetModelPipeline

ensure_omx_paths()

DEFAULT_PREP_DIR = Path("/home/robttt/rosy-test/omx-record-prep-20261019")
ARM_WRAPPERS: dict[str, tuple[str, str, float]] = {
    "arm_s": ("s", "with-session-arm-s-live.sh", -3.5),
    "arm_a": ("a", "with-session-arm-a-par.sh", -3.5),
    "arm_b": ("b", "with-session-arm-b-par.sh", -3.5),
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

    out = subprocess.check_output(["bash", str(prep_dir / wrapper_script), "true"], cwd=str(prep_dir), text=True)
    if "session up" not in out:
        raise RuntimeError(f"Arm {arm_id} session failed to start: {out}")

    def _send_line(line: str) -> None:
        with open(cmd_fifo, "w", encoding="utf-8") as f:
            f.write(line.strip() + "\n")
            f.flush()

    _send_line("state")
    time.sleep(0.5)
    _send_line(f"jog shoulder_pan.pos {delta}")
    time.sleep(2.0)
    _send_line("stop")

    stop_ev: dict[str, Any] = {}
    for _ in range(160):
        if status_file.exists():
            lines = status_file.read_text(errors="replace").splitlines()[n0:]
            events = [json.loads(l) for l in lines if l.strip().startswith("{")]
            found = next((e for e in reversed(events) if e.get("command") == "stop" and e.get("ok") is True), None)
            if found is not None:
                stop_ev = found
                break
        time.sleep(0.25)

    lines = status_file.read_text(errors="replace").splitlines()[n0:] if status_file.exists() else []
    events = [json.loads(l) for l in lines if l.strip().startswith("{")]
    return {
        "arm": arm_id,
        "events_count": len(events),
        "stop_event": stop_ev,
    }


def poll_and_execute_once(
    pipeline: FleetModelPipeline,
    *,
    request_fn: Callable[[str, str, dict[str, Any] | None], dict[str, Any]],
    live_act_fn: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Poll queued tasks on Fleet-R and claim, execute, and complete each one in FIFO order."""
    listing = request_fn("GET", "/api/fleet/pipeline/cell-tasks?status=QUEUED", None)
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
        omx_res = pipeline.run_contract_handoff_stage(handoff, stage_id=task_id, tier=tier)
        hw_tel = live_act_fn(handoff) if callable(live_act_fn) else None
        done = request_fn(
            "POST",
            f"/api/fleet/pipeline/cell-tasks/{task_id}/complete",
            {
                "phase": omx_res["receipt"]["phase"],
                "goal_evidence_digest": omx_res["receipt"]["goal_evidence_digest"],
                "reason": omx_res["receipt"]["reason"],
                "receipt": omx_res["receipt"],
                "stage_result": omx_res["stage_result"],
                "hardware_telemetry": hw_tel,
            },
        )
        completed_runs.append(
            {
                "task_id": task_id,
                "cell_id": cell_id,
                "arm_id": handoff.get("arm_id"),
                "task": done["task"],
                "claim_gate": claimed["gate"],
                "release_gate": done["gate"],
                "omx_result": omx_res,
            }
        )
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

    def _hw_act(handoff: dict[str, Any]) -> dict[str, Any]:
        arm_id = str(handoff.get("arm_id") or ("arm_s" if handoff.get("cell_id") == "cell_s" else "arm_a"))
        if args.dry_run_hw:
            return {"arm": arm_id, "events_count": 1, "stop_event": {"command": "stop", "ok": True, "folded": True}}
        return execute_live_hardware_arm(arm_id, prep_dir=prep_dir)

    while True:
        try:
            runs = poll_and_execute_once(pipeline, request_fn=req_fn, live_act_fn=_hw_act)
            for r in runs:
                stop_ev = (r["task"].get("hardware_telemetry") or {}).get("stop_event") or {}
                print(
                    json.dumps(
                        {
                            "event": "task_completed",
                            "task_id": r["task_id"],
                            "cell_id": r["cell_id"],
                            "arm_id": r["arm_id"],
                            "status": r["task"]["status"],
                            "folded": stop_ev.get("folded"),
                            "state": stop_ev.get("state"),
                        }
                    ),
                    flush=True,
                )
        except Exception as exc:
            print(json.dumps({"event": "poll_error", "error": repr(exc)}), flush=True)
        if args.once:
            break
        time.sleep(max(0.5, float(args.interval_s)))


if __name__ == "__main__":
    main()
