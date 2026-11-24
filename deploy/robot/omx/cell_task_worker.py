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
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

from cell_bed_ready import observe_bed, send_bed_observation
from cell_camera_telemetry_sync import DEFAULT_PREP_DIR, sync_cell_telemetry as _sync_cell_telemetry
from cell_control_core import ensure_omx_paths
from cell_fleet_handoff import handoff_refusal
from cell_fleet_pipeline import FleetModelPipeline
from cell_result_outbox import Outbox, abort_reason, remeasurer, result_bodies, resend_pending
import cell_site_target
from cell_task_exec import (
    check_arm_hold, classify_poll_error, execute_guarded_cell_task, make_ca_urlopen,
    make_default_request_fn, peer_ab_session_locked, query_safety_listing, resolve_task_arm,
)
from cell_task_transport import (
    SAFETY_EXPLICIT_STOP, SAFETY_FEED_UNAVAILABLE, SAFETY_OK,
    classify_safety_listing, select_arms_for_feed_loss, send_human_hold_to_arms,
)

ensure_omx_paths()


def sync_cell_telemetry(fleet_r_url: str, token: str, prep_dir: Path = DEFAULT_PREP_DIR,
                        *, ca_file: str | Path | None = None, allow_safe_home: bool = False) -> dict[str, Any]:
    opener = make_ca_urlopen(ca_file) if ca_file else urlopen
    tls_verified = not (fleet_r_url.rstrip("/").startswith("https://") and not ca_file)
    return _sync_cell_telemetry(
        fleet_r_url, token, prep_dir=prep_dir, urlopen_fn=opener,
        ca_file=ca_file, tls_verified=tls_verified, allow_safe_home=allow_safe_home,
    )


ARM_WRAPPERS: dict[str, tuple[str, str, float]] = {"arm_s": ("s", "with-session-arm-s-live.sh", -1.0), "arm_a": ("a", "with-session-arm-a-par.sh", -1.0), "arm_b": ("b", "with-session-arm-b-par.sh", -1.0)}


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


def emergency_stop_arms(
    prep_dir: Path = DEFAULT_PREP_DIR,
    *,
    arms: set[str] | None = None,
) -> dict[str, dict[str, Any]]:
    """Latch active runners at their present pose and report command acknowledgements."""
    return send_human_hold_to_arms(prep_dir, ARM_WRAPPERS, _poll_status_ack, arms=arms)


_REAL_EMERGENCY_STOP_ARMS = emergency_stop_arms


_LAST_SAFETY_ERROR: list[Exception | None] = [None]
_SAFETY_LISTING_TIMEOUT_S = 0.5
_SAFETY_LISTING_RETRY_S = 1.5
_BACKGROUND_SAFETY_MISSES = 3


def _bounded_safety_status(request_fn, *, cell_id: str | None = None, task_id: str | None = None) -> tuple[str, dict | None]:
    """Return (SAFETY_OK | SAFETY_EXPLICIT_STOP | SAFETY_FEED_UNAVAILABLE, listing_or_none)."""
    attempts = _BACKGROUND_SAFETY_MISSES if cell_id is None else 1
    # Background feed loss can delay a Fleet stop by ~4.5 s over three deadlines; a received stop and leased tasks still hold on the first failed check.
    listing = None
    for attempt in range(attempts):
        listing, error = query_safety_listing(request_fn, _SAFETY_LISTING_TIMEOUT_S)
        _LAST_SAFETY_ERROR[0] = error
        no_response = (error is None or isinstance(error, (TimeoutError, ConnectionError))
                       or (isinstance(error, URLError) and not isinstance(error, HTTPError)
                           and isinstance(error.reason, OSError) and not isinstance(error.reason, ssl.SSLError)))
        if listing is not None or not no_response or attempt == attempts - 1:
            break
        time.sleep(_SAFETY_LISTING_RETRY_S)
    return classify_safety_listing(listing, cell_id=cell_id, task_id=task_id)


def _bounded_safety_listing(request_fn, *, cell_id: str | None = None, task_id: str | None = None) -> dict | None:
    """Only an explicit fresh Fleet `active_estop=False` can allow an arm task to continue."""
    return _bounded_safety_status(request_fn, cell_id=cell_id, task_id=task_id)[1]


def _hold_fault(prep_dir: Path, arm_id: str, reason: str, *, stop_all: bool = True) -> dict[str, Any]:
    try:
        if not stop_all and emergency_stop_arms is _REAL_EMERGENCY_STOP_ARMS:
            target = select_arms_for_feed_loss(prep_dir, ARM_WRAPPERS) | {arm_id}
            ack = emergency_stop_arms(prep_dir, arms=target)
        else:
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
    bed_observe_fn: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Poll Fleet tasks; release only after the actuator reports measured placement."""
    if live_act_fn is None:
        return []
    safety_state, listing = _bounded_safety_status(request_fn)
    if safety_state != SAFETY_OK or listing is None:
        if safety_state == SAFETY_FEED_UNAVAILABLE and emergency_stop_arms is _REAL_EMERGENCY_STOP_ARMS:
            emergency_stop_arms(prep_dir, arms=select_arms_for_feed_loss(prep_dir, ARM_WRAPPERS))
        else:
            emergency_stop_arms(prep_dir)
        return []
    queued = list(listing.get("tasks") or [])
    work_dir = getattr(pipeline, "work_dir", None)
    outbox = Outbox(None if work_dir is None else Path(work_dir) / "pending-results.json")
    resend_pending(outbox, request_fn, remeasurer(prep_dir))  # D-1057: resent (a stale one measured again); the arm does not run again
    completed_runs: list[dict[str, Any]] = []
    for task in queued:
        task_id = str(task["task_id"])
        cell_id = str(task["cell_id"])
        tier = task.get("tier")
        if type(tier) is not int or tier not in (1, 2, 3):
            continue
        task_arm = resolve_task_arm(task)
        if hold_check_fn is not None and hold_check_fn(task_arm).get("held"):
            continue
        if cell_id == "cell_ab" and peer_ab_session_locked(task_arm, prep_dir=prep_dir):
            continue
        send_bed_observation(request_fn, bed_observe_fn, task)  # D-1057 2-9: cell S only, before the claim
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
        internal_ab = cell_id == "cell_ab" and handoff.get("interlock_scope") == "cell_internal"
        interlock_ok = internal_ab or (
            handoff.get("wheel_brake_locked") is True
            and handoff.get("bed_ready") is True
            and isinstance(speed, (int, float)) and not isinstance(speed, bool)
            and abs(speed) <= 1e-4
        )
        site_ok = handoff_refusal(pipeline, handoff, tier) != "UNKNOWN_SITE"  # an unknown site never runs the arm
        claim_bound = claim_bound and site_ok
        safety_fault: dict[str, Any] = {}
        if claim_bound and interlock_ok:
            st, _ = _bounded_safety_status(request_fn, cell_id=cell_id, task_id=task_id)
            if st != SAFETY_OK:
                safety_fault.update(_hold_fault(prep_dir, str(handoff.get("arm_id")), "HUMAN_HOLD_OR_SAFETY_FEED_LOST", stop_all=(st == SAFETY_EXPLICIT_STOP)))
        stop_watch = threading.Event()
        watch_fault = safety_fault

        def watch_safety() -> None:
            while not stop_watch.is_set():
                st, _ = _bounded_safety_status(request_fn, cell_id=cell_id, task_id=task_id)
                if st != SAFETY_OK:
                    watch_fault.update(_hold_fault(prep_dir, str(handoff.get("arm_id")), "HUMAN_HOLD_OR_SAFETY_FEED_LOST", stop_all=(st == SAFETY_EXPLICIT_STOP)))
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
        if claim_bound and interlock_ok and not safety_fault:
            st, _ = _bounded_safety_status(request_fn, cell_id=cell_id, task_id=task_id)
            if st != SAFETY_OK:
                safety_fault.update(_hold_fault(prep_dir, str(handoff.get("arm_id")), "HUMAN_HOLD_OR_SAFETY_FEED_LOST", stop_all=(st == SAFETY_EXPLICIT_STOP)))
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
                    and verification.get("basis") in (("predefined_side_and_top_target_zones", "top_camera_only_target_zone")
                                                      if cell_id == "cell_s" else ("predefined_side_and_top_target_zones",))
                    and stopped.get("ok") is True and stopped.get("folded") is True
                    and isinstance(hw_tel.get("measured_at"), (int, float)) and not isinstance(hw_tel.get("measured_at"), bool))
        if cell_id == "cell_ab":
            place = stage_result.get("place") or {}
            z_gate = verification.get("z_gate") if isinstance(verification.get("z_gate"), dict) else {}
            measured = measured and isinstance(place, dict) and cell_site_target.cell_ab_place_verified(handoff, place, z_gate, tier, verification)
        elif cell_id == "cell_s" and isinstance(stage_result.get("source_clearance"), dict):
            measured = measured and type(stage_result["source_clearance"].get("objects")) is int
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
                              "AMR_NOT_LOCKED_AT_HANDOFF" if not interlock_ok else abort_reason(hw_tel))}
        omx_res = {"receipt": receipt, "stage_result": stage_result}
        owner_body, complete_body = result_bodies(handoff, phase, digest, receipt, stage_result, hw_tel)  # D-1057
        outbox.put(task_id, {"lease": handoff.get("handoff_lease_id"), "owner_evidence": owner_body, "complete": complete_body})
        if owner_body is not None:
            request_fn("POST", f"/api/fleet/pipeline/cell-tasks/{task_id}/owner-evidence", owner_body)
        done = request_fn("POST", f"/api/fleet/pipeline/cell-tasks/{task_id}/complete", complete_body)
        outbox.drop(task_id)  # Fleet has it; a failure above left the entry for resend_pending
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
            bg_cam_fut = bg_cam_pool.submit(
                sync_cell_telemetry, args.fleet_r_url, token, prep_dir,
                ca_file=args.ca_file,
                allow_safe_home=(args.execute_mode == "guarded-pick" and not args.dry_run_hw),
            )

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
                runs = poll_and_execute_once(pipeline, request_fn=req_fn, live_act_fn=_hw_act, prep_dir=prep_dir,
                                             hold_check_fn=check_arm_hold, bed_observe_fn=lambda t: observe_bed(prep_dir, t))
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
