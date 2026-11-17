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
import hashlib
import json
import os
from pathlib import Path
import ssl
import threading
import time
from typing import Any, Callable
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from cell_camera_telemetry_sync import (
    DEFAULT_PREP_DIR,
    sync_cell_telemetry as _sync_cell_telemetry,
)
from cell_control_core import ensure_omx_paths
from cell_fleet_handoff import handoff_refusal
from cell_fleet_pipeline import FleetModelPipeline
from cell_task_exec import (
    check_arm_hold, classify_poll_error, execute_guarded_cell_task, make_ca_urlopen, resolve_task_arm,
)

ensure_omx_paths()


def sync_cell_telemetry(fleet_r_url: str, token: str, prep_dir: Path = DEFAULT_PREP_DIR,
                        *, ca_file: str | Path | None = None) -> dict[str, Any]:
    opener = make_ca_urlopen(ca_file) if ca_file else urlopen
    return _sync_cell_telemetry(fleet_r_url, token, prep_dir=prep_dir, urlopen_fn=opener)

ARM_WRAPPERS: dict[str, tuple[str, str, float]] = {
    "arm_s": ("s", "with-session-arm-s-live.sh", -1.0),
    "arm_a": ("a", "with-session-arm-a-par.sh", -1.0),
    "arm_b": ("b", "with-session-arm-b-par.sh", -1.0),
}


def make_default_request_fn(fleet_r_url: str, token: str, *, ca_file: str | None = None) -> Callable[[str, str, dict[str, Any] | None], dict[str, Any]]:
    base = fleet_r_url.rstrip("/")
    parsed = urlsplit(base)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Fleet URL requires verified HTTPS")
    ctx = ssl.create_default_context(cafile=ca_file)

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
    """The legacy shoulder jog is not a container transfer or a safe stop path."""
    raise RuntimeError("legacy_jog_executor_disabled: measured task executor required")


def emergency_stop_arms(prep_dir: Path = DEFAULT_PREP_DIR) -> dict[str, dict[str, Any]]:
    """Latch active runners at their present pose and report command acknowledgements."""
    acknowledgements: dict[str, dict[str, Any]] = {}
    pending: list[tuple[str, Path, int]] = []
    for _, (suffix, _, _) in ARM_WRAPPERS.items():
        for io_name in (f"chunk-io-{suffix}", f"chunk-io-{suffix}-r2s"):
            io_dir = prep_dir / io_name
            cmd_fifo = io_dir / "chunk-cmd"
            if cmd_fifo.exists():
                status_file = io_dir / "chunk-status.jsonl"
                try:
                    cursor = len(status_file.read_text(errors="replace").splitlines()) if status_file.exists() else 0
                    fd = os.open(str(cmd_fifo), os.O_WRONLY | os.O_NONBLOCK)
                    try:
                        os.write(fd, b"human-hold\n")
                    finally:
                        os.close(fd)
                    pending.append((io_name, status_file, cursor))
                except (OSError, ValueError):
                    acknowledgements[io_name] = {"ok": False, "error": "human_hold_command_failed"}
    for io_name, status_file, cursor in pending:
        try:
            ack, _ = _poll_status_ack(status_file, cursor, "human-hold", 2.0)
            acknowledgements[io_name] = ack if (ack.get("command") == "human-hold" and
                ack.get("ok") is True and ack.get("human_hold_latched") is True and
                ack.get("torque_hold_commanded") is True) else {
                "ok": False, "error": "human_hold_ack_missing"}
        except (OSError, ValueError):
            acknowledgements[io_name] = {"ok": False, "error": "human_hold_ack_missing"}
    return acknowledgements


_LAST_SAFETY_ERROR: list[Exception | None] = [None]


def _bounded_safety_listing(request_fn, *, cell_id: str | None = None, task_id: str | None = None) -> dict | None:
    """Only an explicit fresh Fleet `active_estop=False` can allow an arm task to continue."""
    answer: dict[str, Any] = {}
    finished = threading.Event()

    def query() -> None:
        try:
            answer["value"] = request_fn("GET", "/api/fleet/pipeline/cell-tasks?status=QUEUED", None)
        except Exception as exc:
            answer["error"] = exc
        finally:
            finished.set()

    threading.Thread(target=query, daemon=True).start()
    if not finished.wait(0.5):
        return None  # shortcut: one timed-out daemon query may finish later; no further poll after this failure
    _LAST_SAFETY_ERROR[0] = answer.get("error")
    listing = answer.get("value")
    if not isinstance(listing, dict) or not isinstance(listing.get("human_safety"), dict):
        return None
    safety = listing["human_safety"]
    if safety.get("active_estop") is not False or not isinstance(safety.get("human_detected"), dict):
        return None
    if cell_id is not None:
        cells = listing.get("cells")
        if not isinstance(cells, dict):
            return None
        cell = cells.get(cell_id)
        if (safety["human_detected"].get("all") or safety["human_detected"].get(cell_id)
                or not isinstance(cell, dict) or cell.get("phase") != "ARM_IN_BED_ZONE"
                or cell.get("active_task_id") != task_id):
            return None
    return listing


def _hold_fault(prep_dir: Path, arm_id: str, reason: str) -> dict[str, Any]:
    try:
        ack = emergency_stop_arms(prep_dir)
    except Exception:
        ack = {}
    ack = ack if isinstance(ack, dict) else {}
    suffix = ARM_WRAPPERS.get(arm_id, (None,))[0]
    relevant = [value for name, value in ack.items() if suffix and name in (f"chunk-io-{suffix}", f"chunk-io-{suffix}-r2s")]
    return {"reason": reason, "hold_ack": ack,
            "owner_hold_ack_complete": bool(relevant) and all(isinstance(v, dict) and v.get("ok") is True for v in relevant),
            "owner_stop_unconfirmed": True}  # command ACK does not measure physical stop or sustained torque


def poll_and_execute_once(
    pipeline: FleetModelPipeline,
    *,
    request_fn: Callable[[str, str, dict[str, Any] | None], dict[str, Any]],
    live_act_fn: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    prep_dir: Path = DEFAULT_PREP_DIR,
    hold_check_fn: Callable[[str], dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Poll Fleet tasks; release only after the actuator reports measured placement."""
    if live_act_fn is None:
        return []
    listing = _bounded_safety_listing(request_fn)
    if listing is None:
        emergency_stop_arms(prep_dir)
        return []
    queued = list(listing.get("tasks") or [])
    completed_runs: list[dict[str, Any]] = []
    for task in queued:
        task_id = str(task["task_id"])
        cell_id = str(task["cell_id"])
        tier = task.get("tier")
        if type(tier) is not int or tier not in (1, 2, 3):
            continue
        if hold_check_fn is not None and hold_check_fn(resolve_task_arm(task)).get("held"):
            continue
        claimed = request_fn("POST", "/api/fleet/pipeline/cell-tasks/claim", {"cell_id": cell_id, "task_id": task_id})
        if not claimed.get("claimed"):
            continue
        handoff = claimed["handoff"]
        claim_bound = (
            handoff.get("task_id") == task_id
            and handoff.get("cell_id") == cell_id
            and type(handoff.get("tier")) is int and handoff["tier"] == tier
            and isinstance(handoff.get("handoff_lease_id"), str)
            and bool(handoff["handoff_lease_id"])
            and handoff.get("arm_id") in {"cell_s": {"arm_s"}, "cell_ab": {"arm_a", "arm_b"}}.get(cell_id, set())
        )
        speed = handoff.get("v_cmd_mps")
        interlock_ok = (
            handoff.get("wheel_brake_locked") is True
            and handoff.get("bed_ready") is True
            and isinstance(speed, (int, float)) and not isinstance(speed, bool)
            and abs(speed) <= 1e-4
        )
        site_ok = handoff_refusal(pipeline, handoff, tier) != "UNKNOWN_SITE"  # an unknown site never runs the arm
        claim_bound = claim_bound and site_ok
        safety_fault: dict[str, Any] = {}
        if claim_bound and interlock_ok and _bounded_safety_listing(request_fn, cell_id=cell_id, task_id=task_id) is None:
            safety_fault.update(_hold_fault(prep_dir, str(handoff.get("arm_id")), "HUMAN_HOLD_OR_SAFETY_FEED_LOST"))
        stop_watch = threading.Event()
        watch_fault = safety_fault

        def watch_safety() -> None:
            while not stop_watch.is_set():
                if _bounded_safety_listing(request_fn, cell_id=cell_id, task_id=task_id) is None:
                    watch_fault.update(_hold_fault(prep_dir, str(handoff.get("arm_id")), "HUMAN_HOLD_OR_SAFETY_FEED_LOST"))
                    return
                stop_watch.wait(0.1)

        watcher = None
        if claim_bound and interlock_ok and not safety_fault:
            watcher = threading.Thread(target=watch_safety, daemon=True)
            watcher.start()
        try:
            hw_tel = (live_act_fn(handoff) if claim_bound and interlock_ok and not safety_fault else
                      {"error": "UNKNOWN_SITE" if not site_ok else "HANDOFF_TASK_MISMATCH" if not claim_bound else
                       "HUMAN_HOLD_OR_SAFETY_FEED_LOST" if safety_fault else "AMR_NOT_LOCKED_AT_HANDOFF"})
        except Exception as exc:
            hw_tel = {"error": repr(exc)}
        finally:
            stop_watch.set()
            if watcher is not None:
                watcher.join(timeout=15.0)
                if watcher.is_alive():
                    safety_fault.update(_hold_fault(prep_dir, str(handoff.get("arm_id")), "SAFETY_WATCHDOG_UNRESPONSIVE"))
        if claim_bound and interlock_ok and not safety_fault and _bounded_safety_listing(request_fn, cell_id=cell_id, task_id=task_id) is None:
            safety_fault.update(_hold_fault(prep_dir, str(handoff.get("arm_id")), "HUMAN_HOLD_OR_SAFETY_FEED_LOST"))
        safety_fault = dict(safety_fault)  # detached if an unresponsive watchdog thread is still finishing
        if not isinstance(hw_tel, dict):
            hw_tel = {"error": "INVALID_ACTUATOR_RESULT"}
        if safety_fault:
            hw_tel = {**hw_tel, "safety_watchdog": safety_fault}
        stage_result = hw_tel.get("stage_result") or {}
        if not isinstance(stage_result, dict):
            stage_result = {}
        verification = stage_result.get("verification") or {}
        if not isinstance(verification, dict):
            verification = {}
        stopped = hw_tel.get("stop_event") or {}
        if not isinstance(stopped, dict):
            stopped = {}
        measured = (claim_bound
                    and stage_result.get("handoff_lease_id") == handoff.get("handoff_lease_id")
                    and stage_result.get("directive_id") == task_id
                    and stage_result.get("arm_id") == handoff.get("arm_id")
                    and stage_result.get("task_verified") is True
                    and verification.get("verified") is True
                    and verification.get("basis") == "predefined_side_and_top_target_zones"
                    and stopped.get("ok") is True and stopped.get("folded") is True)
        if cell_id == "cell_ab":
            place = stage_result.get("place") or {}
            z_gate = verification.get("z_gate") if isinstance(verification.get("z_gate"), dict) else {}
            if not isinstance(place, dict):
                place = {}
            measured = (measured and z_gate.get("verdict") == "PASS"
                        and str(place.get("area") or place.get("area_id") or "").lower() == "pallet"
                        and type(place.get("tier")) is int and place["tier"] == tier)
        phase = "RELEASED" if claim_bound and interlock_ok and measured and not safety_fault else "ABORTED"
        evidence = {"task_id": task_id, "lease": handoff.get("handoff_lease_id"),
                    "stage_result": stage_result, "hardware_telemetry": hw_tel}
        digest = "sha256:" + hashlib.sha256(json.dumps(evidence, sort_keys=True, default=str).encode()).hexdigest() if phase == "RELEASED" else None
        receipt = {"handoff_lease_id": handoff.get("handoff_lease_id"), "cell_id": cell_id,
                   "stage_id": task_id, "phase": phase, "goal_evidence_digest": digest,
                   "physical_completion": phase == "RELEASED", "simulated_success": False,
                   "reason": ("TRANSFER_CONFIRMED" if phase == "RELEASED" else
                              safety_fault["reason"] if safety_fault else
                              "UNKNOWN_SITE" if not site_ok else
                              "HANDOFF_TASK_MISMATCH" if not claim_bound else
                              "AMR_NOT_LOCKED_AT_HANDOFF" if not interlock_ok else "MEASURED_PLACEMENT_MISSING")}
        omx_res = {"receipt": receipt, "stage_result": stage_result}
        done = request_fn("POST", f"/api/fleet/pipeline/cell-tasks/{task_id}/complete", {
            "phase": phase, "goal_evidence_digest": digest,
            "reason": receipt["reason"], "receipt": receipt,
            "stage_result": stage_result, "hardware_telemetry": hw_tel,
        })
        completed_runs.append({
            "task_id": task_id, "cell_id": cell_id, "arm_id": handoff.get("arm_id"), "task": done["task"],
            "claim_gate": claimed["gate"], "release_gate": done["gate"], "omx_result": omx_res,
        })
        if done["task"].get("status") != "COMPLETED":
            break
    return completed_runs


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Autonomous Fleet-R -> OMX Cell Task Worker")
    parser.add_argument("--fleet-r-url", default="https://192.168.1.93:8443")
    parser.add_argument("--token-file", default="~/.config/rosy-fleet-r-token")
    parser.add_argument("--ca-file", default=os.environ.get("ROSY_FLEET_CA_FILE") or os.environ.get("ROSY_OBSERVATION_CA_FILE"))
    parser.add_argument("--work-dir", default="/tmp/rosy-omx-cell-task-worker")
    parser.add_argument("--prep-dir", default=str(DEFAULT_PREP_DIR))
    parser.add_argument("--interval-s", type=float, default=1.5)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--dry-run-hw", action="store_true")
    parser.add_argument("--allow-legacy-live-jog", action="store_true")
    parser.add_argument("--execute-mode", choices=("sealed", "guarded-pick"), default="sealed")
    args = parser.parse_args(argv)

    token = Path(args.token_file).expanduser().read_text(encoding="utf-8").strip()
    req_fn = make_default_request_fn(args.fleet_r_url, token, ca_file=args.ca_file)
    pipeline = FleetModelPipeline(work_dir=Path(args.work_dir))
    prep_dir = Path(args.prep_dir)
    bg_cam_pool = ThreadPoolExecutor(max_workers=1)
    bg_cam_fut: Future | None = None

    def _trigger_bg_cam_upload() -> None:
        nonlocal bg_cam_fut
        if bg_cam_fut is None or bg_cam_fut.done():
            bg_cam_fut = bg_cam_pool.submit(sync_cell_telemetry, args.fleet_r_url, token, prep_dir, ca_file=args.ca_file)

    def _hw_act(handoff: dict[str, Any]) -> dict[str, Any]:
        arm_id = resolve_task_arm(handoff)
        if args.dry_run_hw:
            return {"arm": arm_id, "events_count": 1, "stop_event": {"command": "stop", "ok": True, "folded": True}}
        if args.execute_mode == "guarded-pick":
            res = execute_guarded_cell_task(handoff, prep_dir=prep_dir)
        elif args.allow_legacy_live_jog:
            res = execute_live_hardware_arm(arm_id, prep_dir=prep_dir)
        else:
            raise RuntimeError("legacy cell_task_worker live jog is sealed; use --execute-mode guarded-pick or --dry-run-hw")
        _trigger_bg_cam_upload()
        return res

    last_cam_push = 0.0
    while True:
        sleep_s = max(0.5, float(args.interval_s))
        try:
            now_m = time.monotonic()
            if not args.dry_run_hw and (now_m - last_cam_push) >= 3.0:
                _trigger_bg_cam_upload()
                last_cam_push = now_m
            if args.dry_run_hw or args.allow_legacy_live_jog or args.execute_mode == "guarded-pick":
                _LAST_SAFETY_ERROR[0] = None
                runs = poll_and_execute_once(pipeline, request_fn=req_fn, live_act_fn=_hw_act, hold_check_fn=check_arm_hold)
                if not runs and _LAST_SAFETY_ERROR[0] is not None:
                    raise _LAST_SAFETY_ERROR[0]
            else:
                runs = []
                print(json.dumps({
                    "event": "legacy_worker_live_sealed",
                    "detail": "telemetry sync active; legacy claim/jog disabled without --execute-mode guarded-pick",
                }), flush=True)
            for r in runs:
                stop_ev = (r["task"].get("hardware_telemetry") or {}).get("stop_event") or {}
                print(json.dumps({
                    "event": "task_completed", "task_id": r["task_id"], "cell_id": r["cell_id"], "arm_id": r["arm_id"],
                    "status": r["task"]["status"], "folded": stop_ev.get("folded"), "state": stop_ev.get("state"),
                }), flush=True)
        except Exception as exc:
            err = classify_poll_error(exc, args.token_file)
            if err.get("backoff_s"):
                sleep_s = max(sleep_s, float(err["backoff_s"]))
            print(json.dumps(err), flush=True)
        if args.once:
            if bg_cam_fut is not None:
                bg_cam_fut.result(timeout=10.0)
            break
        time.sleep(sleep_s)


if __name__ == "__main__":
    main()
