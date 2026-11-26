"""Supervised concurrent two-arm remote ACT policy runner (D-1073).

Runs `arm_a` and `arm_b` policy loops in parallel threads:
observe -> remote GPU `infer` -> `cell_policy_shape` clamping + `jaw_gate` ->
`TwoArmChunkGuard.admit_chunk` -> D-911 `authorize` + `checked load/run policy`.
Any remote failure, timeout, collision refusal, or runner fault triggers
coupled `human-hold` across both arms and optional non-faulted `safe_fold`.
"""
from __future__ import annotations

from hashlib import sha256
import json
import math
from pathlib import Path
import threading
import time
from typing import Any, Callable, Mapping, Sequence

from cell_policy_entry import build_two_arm_chunk_library as _build_chunk_library, check_obs_stamp as _check_stamp, pose6, two_arm_roll_bounds
import cell_policy_shape
from cell_policy_timing import MAX_OBSERVATION_AGE_S, send_hold
import cell_two_arm
from cell_two_arm_guard import ARMS, TwoArmChunkGuard, validate_two_arm_task_pair
from cell_two_arm_verification import transfer_refusal
import numpy as np
from omx_adapter.chunk_library import GUARD_UNITS_PER_S

SCHEMA = "rosy.omx-two-arm-policy-run.v1"
MAX_WAIT_REOBSERVE = 3


def _checked_act(cell: Any, auth: Mapping[str, Any], command: str) -> dict[str, Any]:
    if hasattr(cell, "checked"):
        return cell.checked(command, auth)
    return cell.act(f"checked {auth['session_id']} {auth['library_sha256']} {command}")


def _hold_arm(cell: Any, *, log: Callable[[dict[str, Any]], Any] | None = None) -> bool:
    try:
        send_hold(cell, log=log)
        return True
    except Exception:
        return False


def _hold_both(
    cells: Mapping[str, Any], faulted: Mapping[str, bool], *, dry_run: bool,
    log: Callable[[dict[str, Any]], Any] | None = None,
) -> dict[str, bool]:
    if dry_run:
        return {arm: False for arm in ARMS}
    return {
        arm: (False if faulted.get(arm) else _hold_arm(cells[arm], log=(lambda row, _a=arm: log({"arm": _a, **row})) if log else None))
        for arm in ARMS
    }


def _read_state(cell: Any, *, dry_run: bool, max_age_s: float, label: str = "state") -> tuple[dict[str, Any], list[float], float]:
    reply = cell.act("state")
    if not isinstance(reply, Mapping) or reply.get("ok") is False:
        err = reply.get("error") if isinstance(reply, Mapping) else "bad reply"
        fault = reply.get("fault") if isinstance(reply, Mapping) else None
        raise RuntimeError(f"fault:{fault}" if fault else f"state read failed: {err}")
    if reply.get("fault"):
        raise RuntimeError(f"fault:{reply['fault']}")
    raw_state = reply.get("state")
    if not isinstance(raw_state, Sequence) or isinstance(raw_state, (str, bytes)) or len(raw_state) != 6:
        raise ValueError(f"invalid state vector {raw_state!r}")
    vec: list[float] = []
    for x in raw_state:
        if isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(float(x)):
            raise ValueError("non-finite joint state")
        vec.append(float(x))
    now_wall, now_mono = time.time(), time.monotonic()
    obs_mono = now_mono
    if "t" in reply and not dry_run:
        st_wall = _check_stamp(reply["t"], now_wall, max_age_s, label)
        obs_mono = now_mono - max(0.0, now_wall - st_wall)
    return dict(reply), vec, obs_mono


def _capture_frames(
    cell: Any, views: Mapping[str, tuple[int, int]], *, dry_run: bool, max_age_s: float,
    state_mono: float, prev_receipts: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], float]:
    frames: dict[str, Any] = {}
    obs_mono = state_mono
    use_receipt = hasattr(cell, "frame_receipt")
    for role in views:
        remaining = obs_mono + max_age_s - time.monotonic()
        if not dry_run and remaining <= 0:
            raise ValueError(f"stale policy observation before camera {role}")
        if use_receipt:
            limits = {} if dry_run else {"max_age_s": max_age_s, "timeout_s": remaining}
            rec = cell.frame_receipt(role, previous=prev_receipts.get(role), **limits)
            if not dry_run:
                now_wall, now_mono = time.time(), time.monotonic()
                stamp = _check_stamp(rec.get("source_stamp"), now_wall, max_age_s, f"camera {role}")
                obs_mono = min(obs_mono, now_mono - max(0.0, now_wall - stamp))
            prev_receipts[role] = rec
            frames[role] = rec["image"]
        else:
            frames[role] = cell.frame(role)
        if not dry_run and time.monotonic() >= obs_mono + max_age_s:
            raise ValueError(f"stale policy observation after camera {role}")
    return frames, obs_mono


def _shape_candidate(
    raw_actions: Sequence[Sequence[float]], start_state: Sequence[float], library: Mapping[str, Any],
    demo_range: tuple[Sequence[float], Sequence[float]] | None, *, sim_units: bool, sim_rule: Mapping[str, Any] | None, holding: bool,
) -> tuple[list[list[float]], float]:
    low, high, fastest = cell_policy_shape.envelope(dict(library))
    fps = float(library.get("fps", 30.0))
    fastest = min(float(fastest), float(GUARD_UNITS_PER_S) / max(1.0, fps))
    if demo_range is not None and not sim_units:
        low, high = cell_policy_shape.widen(low, high, demo_range[0], demo_range[1])
    closed = cell_policy_shape.closed_gripper(dict(library))
    model_closed = cell_policy_shape.converted_closed(closed, dict(sim_rule)) if (sim_units and sim_rule is not None) else closed
    actions = raw_actions if holding else cell_policy_shape.open_before_close(raw_actions, float(high[5]), model_closed)
    candidate = cell_policy_shape.resample_chunk(actions, list(start_state), fps) if sim_units else actions
    shaped = cell_policy_shape.shape_chunk(candidate, list(start_state), low, high, fastest)
    return [[float(x) for x in row] for row in shaped], fastest


def run_two_arm_policy(
    cells: Mapping[str, Any], shadows: Mapping[str, Any], libraries: Mapping[str, Mapping[str, Any]],
    guard: TwoArmChunkGuard, task_a: Mapping[str, Any], task_b: Mapping[str, Any], work_dir: Path, *,
    offsets: Mapping[str, Sequence[float]] | None = None,
    demo_ranges: Mapping[str, tuple[Sequence[float], Sequence[float]] | None] | None = None,
    goals: Mapping[str, Any] | None = None,
    jaw_specs: Mapping[str, Mapping[str, Any] | None] | None = None,
    kins: Mapping[str, Any] | None = None,
    max_chunks: int = 8, dry_run: bool = False, max_obs_age_s: float = MAX_OBSERVATION_AGE_S,
    authorizers: Mapping[str, Callable[..., dict[str, Any]]] | None = None,
    fold_context: Mapping[str, Any] | None = None,
    state_gates: Mapping[str, Any] | None = None,
    log: Callable[[dict[str, Any]], Any] = lambda _row: None,
) -> dict[str, Any]:
    """Supervised concurrent per-arm 6-DoF remote policy loops guarded per chunk; state_gates (StateGate per arm) stop an untrained measured state via the error path."""
    if set(cells) != set(ARMS) or set(shadows) != set(ARMS) or set(libraries) != set(ARMS):
        raise ValueError("cells, shadows, and libraries must specify keys 'a' and 'b'")
    if max_chunks < 1 or not math.isfinite(max_obs_age_s) or max_obs_age_s <= 0.0:
        raise ValueError("max_chunks >= 1 and max_obs_age_s > 0 required")
    if not dry_run and (authorizers is None or set(authorizers) != set(ARMS) or not all(callable(authorizers[k]) for k in ARMS)):
        raise ValueError("live execution requires per-arm D-911 authorizers")
    if jaw_specs:
        for arm, jspec in jaw_specs.items():
            if jspec is not None and (kins is None or kins.get(arm) is None):
                raise ValueError(f"arm {arm}: jaw_spec requires kinematics in kins")

    plan = validate_two_arm_task_pair(task_a, task_b)
    if refusal := transfer_refusal({"a": task_a, "b": task_b}, dry_run=dry_run):
        return {"schema": SCHEMA, "task_id": plan["task_id"], "plan": plan, **refusal}
    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)
    state_lock = threading.Lock()
    faulted = {arm: False for arm in ARMS}
    moved_arms = {arm: False for arm in ARMS}
    held_arms = {arm: False for arm in ARMS}
    events: list[dict[str, Any]] = []
    arm_reports: dict[str, dict[str, Any]] = {}

    def _is_coupled_hold(exc: Exception) -> bool:
        return guard.stopped_reason is not None and "human hold" in str(exc).lower()

    def mark_fault(arm: str) -> None:
        with state_lock:
            faulted[arm] = True

    def hold_both_safe() -> dict[str, bool]:
        with state_lock:
            flt = dict(faulted)
        holds = _hold_both(cells, flt, dry_run=dry_run, log=lambda row: emit({"event": "hold", **row}))
        with state_lock:
            for k, sent in holds.items():
                if sent:
                    held_arms[k] = True
        return holds

    def emit(row: dict[str, Any]) -> None:
        with state_lock:
            events.append(row)
        log(row)

    for arm in ARMS:
        try:
            st, vec, _ = _read_state(cells[arm], dry_run=dry_run, max_age_s=max_obs_age_s, label=f"{arm}:init")
            guard.update_pose(arm, vec, holding=bool(st.get("holding", False)))
        except Exception as exc:
            if "fault:" in str(exc):
                mark_fault(arm)
            guard.latch_stop(f"{arm}:init:{exc}")
            holds = hold_both_safe()
            with state_lock:
                any_init_flt = any(faulted.values())
            return {
                "schema": SCHEMA, "task_id": plan["task_id"], "result": "fault" if any_init_flt else "refused",
                "stopped_reason": guard.stopped_reason, "dry_run": dry_run, "holds": holds, "arms": {}, "events": [],
            }

    def worker(arm: str) -> None:
        chunks_done, reason = 0, None
        outcome = "dry_run" if dry_run else "chunks_done"
        try:
            cell, shadow, lib = cells[arm], shadows[arm], libraries[arm]
            offset = list(offsets[arm]) if offsets and offsets.get(arm) is not None else [0.0] * 6
            demo_rng = demo_ranges.get(arm) if demo_ranges else None
            goal = goals.get(arm) if goals else None
            jaw_spec, state_gate = (jaw_specs or {}).get(arm), (state_gates or {}).get(arm)
            arm_kin = kins.get(arm) if kins else None
            need_mid = bool(plan["need_mid"][arm])
            sim_rule = getattr(shadow, "sim_rule", None)
            sim_units = sim_rule is not None
            prev_receipts: dict[str, dict[str, Any]] = {}
            home_roll, roll_range = two_arm_roll_bounds(arm, lib, demo_rng, sim_units)
            closed, ever_held = cell_policy_shape.closed_gripper(dict(lib)), False
        except Exception as exc:
            outcome = "refused"
            reason = f"{arm}:setup:{exc}"
            guard.latch_stop(reason)
            hold_both_safe()
            emit({"arm": arm, "event": "error", "reason": reason})
            with state_lock:
                arm_reports[arm] = {"outcome": outcome, "chunks_done": 0, "reason": reason}
            return

        for idx in range(max_chunks):
            admitted: dict[str, Any] | None = None
            for attempt in range(MAX_WAIT_REOBSERVE + 1):
                if guard.stopped_reason is not None:
                    outcome, reason = "refused", guard.stopped_reason
                    break
                try:
                    st, vec, st_mono = _read_state(cell, dry_run=dry_run, max_age_s=max_obs_age_s, label=f"{arm}:pre")
                    guard.update_pose(arm, vec, holding=bool(st.get("holding", False)))
                    q_warn = state_gate.admit(vec) if state_gate is not None else []  # before every chunk: raises into the error path
                    frames, obs_mono = _capture_frames(
                        cell, shadow.image_views, dry_run=dry_run, max_age_s=max_obs_age_s,
                        state_mono=st_mono, prev_receipts=prev_receipts,
                    )
                    model_state = vec if sim_units else [vec[i] + float(offset[i]) for i in range(6)]
                    obs, meta = shadow.inputs(model_state, frames, goal=goal)
                    inferred = shadow.infer(obs, state=vec)
                    raw_actions = inferred.chunk if sim_units else [[float(r[i]) - float(offset[i]) for i in range(6)] for r in inferred.chunk]
                    refreshed, cur_vec, _ = _read_state(cell, dry_run=dry_run, max_age_s=max_obs_age_s, label=f"{arm}:auth")
                    cur_holding = bool(refreshed.get("holding", False))
                    guard.update_pose(arm, cur_vec, holding=cur_holding)
                    shaped, fastest = _shape_candidate(
                        raw_actions, cur_vec, lib, demo_rng, sim_units=sim_units, sim_rule=sim_rule, holding=cur_holding,
                    )
                    if jaw_spec is not None and (jaw_warn := cell_policy_shape.jaw_zone_error([cur_vec], arm_kin, dict(jaw_spec)) or cell_policy_shape.jaw_zone_error(shaped, arm_kin, dict(jaw_spec))):
                        emit({"arm": arm, "chunk_index": idx, "event": "jaw_warning", "reason": jaw_warn})
                        if not dry_run:
                            raise ValueError(jaw_warn)
                    roll_warn = cell_policy_shape.wrist_roll_warning(np.asarray(shaped, dtype=float), home_roll, roll_range=roll_range) if arm == "b" else None
                    if roll_warn and sim_units and not dry_run:
                        emit({"arm": arm, "chunk_index": idx, "event": "wrist_roll_warning", "reason": roll_warn})
                        raise ValueError(roll_warn)
                    if not dry_run and (time.monotonic() - obs_mono) > max_obs_age_s:
                        raise ValueError("stale policy observation")
                    admitted = guard.admit_chunk(arm, shaped, holding=cur_holding, need_mid=need_mid)
                except Exception as exc:
                    if "fault:" in str(exc) and not _is_coupled_hold(exc):
                        mark_fault(arm)
                    with state_lock:
                        outcome = "fault" if faulted[arm] else "refused"
                    reason = f"{arm}:{type(exc).__name__}:{exc}"
                    guard.latch_stop(reason)
                    hold_both_safe()
                    emit({"arm": arm, "chunk_index": idx, "event": "error", "reason": reason})
                    admitted = None
                    break
                if not admitted.get("admitted"):
                    outcome, reason = "refused", f"{arm}:guard:{admitted.get('reason', 'refused')}"
                    guard.latch_stop(reason)
                    hold_both_safe()
                    emit({"arm": arm, "chunk_index": idx, "event": "guard_refused", **admitted})
                    break
                if not dry_run and guard.stopped_reason is None and (time.monotonic() - obs_mono) > max_obs_age_s and attempt < MAX_WAIT_REOBSERVE:
                    guard.release_chunk(arm, final_pose=cur_vec, holding=cur_holding)
                    emit({"arm": arm, "chunk_index": idx, "event": "reobserve_after_wait", "attempt": attempt + 1, "waited_s": admitted.get("waited_s")})
                    admitted = None
                    continue
                break
            if not admitted or not admitted.get("admitted"):
                break

            final_pose: Sequence[float] = cur_vec
            final_holding = cur_holding
            try:
                if guard.stopped_reason is not None:
                    outcome, reason = "refused", guard.stopped_reason
                    break
                if not dry_run and (time.monotonic() - obs_mono) > max_obs_age_s:
                    raise ValueError("stale policy observation after guard wait")
                if dry_run:
                    chunks_done += 1
                    emit({
                        "arm": arm, "chunk_index": idx, "event": "dry_run_admitted", "admitted": admitted,
                        "meta": meta, "rtt_s": getattr(inferred, "rtt_s", None), **({"state_q_warning": q_warn} if q_warn else {}),
                        **({"wrist_roll_warning": roll_warn} if roll_warn else {}),
                    })
                    continue

                # Re-read live state after guard wait so D-911 Authorization sees a fresh timestamp (< MAX_GAP_S).
                auth_state, auth_vec, _ = _read_state(cell, dry_run=False, max_age_s=max_obs_age_s, label=f"{arm}:auth")
                if jaw_spec is not None:
                    post_jaw = cell_policy_shape.jaw_zone_error([auth_vec], arm_kin, dict(jaw_spec))
                    if post_jaw:
                        emit({"arm": arm, "chunk_index": idx, "event": "jaw_warning", "reason": post_jaw})
                        raise ValueError(post_jaw)

                chunk_lib = _build_chunk_library(lib, shaped, obs_mono, max_obs_age_s, fastest, jaw_spec)
                chunk_path = work / f"arm_{arm}-chunk-{idx}.json"
                chunk_bytes = json.dumps(chunk_lib).encode("utf-8")
                chunk_path.write_bytes(chunk_bytes)

                auth = authorizers[arm](chunk_lib, auth_state, ("run policy",))
                load_reply = _checked_act(cell, auth, f"load {chunk_path}")
                if load_reply.get("fault"):
                    raise RuntimeError(f"fault:{load_reply['fault']}")
                if not load_reply.get("ok"):
                    raise RuntimeError(f"load failed: {load_reply.get('error')}")
                expected_sha = auth.get("library_sha256") or sha256(chunk_bytes).hexdigest()
                if "library_sha256" in load_reply and load_reply["library_sha256"] != expected_sha:
                    raise RuntimeError("loaded library sha256 mismatch")

                with state_lock:
                    moved_arms[arm] = True
                run_reply = _checked_act(cell, auth, "run policy")
                if not isinstance(run_reply, Mapping):
                    raise RuntimeError("invalid run policy reply")
                if (end_pose := pose6(run_reply.get("state"))) is not None:
                    final_pose = end_pose
                if isinstance(run_reply.get("holding"), bool):
                    final_holding = bool(run_reply["holding"])
                if run_reply.get("fault"):
                    raise RuntimeError(f"fault:{run_reply['fault']}")
                if not run_reply.get("ok") or run_reply.get("contact"):
                    raise RuntimeError(f"run policy stopped: {run_reply.get('error') or 'contact'}")
                if run_reply.get("settled") is False:
                    raise RuntimeError("chunk did not settle")

                final_pose = end_pose or shaped[-1]
                chunks_done += 1
                emit({
                    "arm": arm, "chunk_index": idx, "event": "chunk_done", "admitted": admitted,
                    "meta": meta, "rtt_s": getattr(inferred, "rtt_s", None), **({"state_q_warning": q_warn} if q_warn else {}),
                    **({"wrist_roll_warning": roll_warn} if roll_warn else {}),
                })
                ever_held = ever_held or final_holding
                if ever_held and not final_holding and shaped[-1][5] > closed + 10.0:
                    outcome = "released"
                    break
            except Exception as exc:
                if "fault:" in str(exc) and not _is_coupled_hold(exc):
                    mark_fault(arm)
                with state_lock:
                    outcome = "fault" if faulted[arm] else "refused"
                reason = f"{arm}:exec:{exc}"
                guard.latch_stop(reason)
                hold_both_safe()
                emit({"arm": arm, "chunk_index": idx, "event": "exec_error", "reason": reason})
                break
            finally:
                guard.release_chunk(arm, final_pose=final_pose, holding=final_holding)

        with state_lock:
            arm_reports[arm] = {"outcome": outcome, "chunks_done": chunks_done, "reason": reason}

    threads = [threading.Thread(target=worker, args=(arm,), daemon=True) for arm in ARMS]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    park_report: dict[str, Any] | None = None
    with state_lock:
        any_moved, any_faulted, any_held = any(moved_arms.values()), any(faulted.values()), any(held_arms.values())
    stopped = guard.stopped_reason
    if set(arm_reports) != set(ARMS) and stopped is None:
        stopped = "incomplete_arm_reports"
    if not dry_run and fold_context is not None and any_moved and not any_faulted and not any_held and stopped is None:
        if cell_two_arm.away_from_home(cells, libraries):
            park_report = cell_two_arm.safe_fold(
                cells, libraries, fold_context["kin"], fold_context["rigids"],
                fold_context["tips"], fold_context.get("margin_m", 0.02),
                log=lambda msg: emit({"event": "safe_fold", "message": str(msg)}),
            )
            if not park_report.get("folded"):
                stopped = str(park_report.get("person_needed") or "safe_fold_failed")

    all_released = not dry_run and len(arm_reports) == len(ARMS) and all(r.get("outcome") == "released" for r in arm_reports.values())
    overall = "fault" if any_faulted else ("refused" if stopped is not None else ("dry_run" if dry_run else ("released" if all_released else "chunks_done")))
    return {
        "schema": SCHEMA, "task_id": plan["task_id"], "plan": plan, "result": overall,
        "stopped_reason": stopped, "dry_run": dry_run, "arms": arm_reports, "park": park_report, "events": events,
    }
