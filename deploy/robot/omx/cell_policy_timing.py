"""A single outstanding ACT inference and a guarded, time-stamped playback window."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import json
import math
from pathlib import Path
import time

import numpy as np

from cell_policy_entry import (  # noqa: F401
    ENTRY_START_TOL, FAULT_KEYS, PRE_SETTLE_TOL, ack_status, cmd_ack_ok, empty_gripper_ok, entry_ready as _entry_ready,
    finite_stamp, hold_ack_ok, max_diff, park_ack_ok, pose6, retreat_ack_ok, run_entry_chunk,
    valid_state, validate_entry_chunk,
)
from chunk_policy_playback import Playback

SIM_FPS, MAX_OBSERVATION_AGE_S = 15, 0.6


@dataclass
class Prediction:
    observed: float
    inferred: float
    ready_at: float
    frames: np.ndarray
    meta: dict
    state: list


def send_hold(cell, *, attempts: int = 3, delay_s: float = 0.01, log=None) -> dict:
    last_err, last_reply = "human-hold failed", None
    for i in range(attempts):
        try:
            reply = cell.act("human-hold")
            if hold_ack_ok(reply):
                return reply
            last_reply = reply if isinstance(reply, dict) else None
            last_err = ((reply.get("error") or reply.get("fault")) if isinstance(reply, dict) else None) or "human-hold unconfirmed"
        except OSError as exc:
            if i + 1 >= attempts:
                raise
            last_err = str(exc) or type(exc).__name__
        if i + 1 < attempts:
            time.sleep(delay_s)
    if isinstance(last_reply, dict):
        if log is not None:
            try:
                log({"command": "human-hold", "unconfirmed": True, **ack_status(last_reply)})
            except Exception:
                pass
        if last_reply.get("human_hold_latched") is True:
            last_err = f"{last_err} (human_hold_latched=True, execution unconfirmed)"
    raise OSError(last_err)


def library_home(library) -> list[float] | None:
    frames = (library.get("chunks") or {}).get("home") if isinstance(library, dict) else None
    return pose6(frames[-1]) if isinstance(frames, (list, tuple)) and frames else None


def rest_diagnosis(status, home) -> dict:
    """Why a refusal before any command does or does not need human-hold: off_home (max body-joint gap to the library home),
    folded (cell_job_peer_health.live_folded, what torque_off_folded uses) and no_hold, true for a clean status at home
    (cell_auto_fold.at_rest within PRE_SETTLE_TOL) or folded. A fault, contact, hold latch or ok!=True is never no_hold."""
    from cell_auto_fold import at_rest
    from cell_job_peer_health import live_folded

    out = {"off_home": None, "folded": None, "no_hold": False}
    if not isinstance(status, dict):
        return out
    state = status.get("state")
    try:
        if home is not None and isinstance(state, (list, tuple)) and len(state) >= 5:
            out["off_home"] = round(max_diff(list(state), home, 5), 3)
        out["folded"] = live_folded({"state": state})  # from the state itself, never a reported `folded` flag
        # folded counts only for an empty, still gripper with no chunk running; a loaded or shaking arm keeps its hold
        folded_ok = (out["folded"] is True and status.get("holding") is False and status.get("chunk") is None
                     and not (status.get("jitter") or {}).get("shaking"))
        clean = status.get("ok") is True and not any(status.get(k) for k in FAULT_KEYS)
        at_home = out["off_home"] is not None and at_rest(state, home) and out["off_home"] <= PRE_SETTLE_TOL
        out["no_hold"] = bool(home is not None and clean and (at_home or folded_ok))
    except (TypeError, ValueError):
        out["no_hold"] = False
    return out


def idle_at_home(status, home) -> bool:
    """With no command sent yet, a refusal of a clean status that is at home or folded needs no human-hold."""
    return rest_diagnosis(status, home)["no_hold"]


def best_effort_hold(cell, *, attempts: int = 3, delay_s: float = 0.01, log=None) -> dict | None:
    try:
        return {"command": "human-hold", **ack_status(send_hold(cell, attempts=attempts, delay_s=delay_s, log=log))}
    except Exception:
        return None


def action_window(chunk, observed, start, fps, steps, max_age):
    if start - observed > max_age:
        raise ValueError("stale policy observation")
    dropped = max(0, math.floor((start - observed) * fps))
    frames = chunk[dropped:dropped + steps]
    if not len(frames):
        raise ValueError("policy chunk is late, all action times passed")
    return frames, dropped


LIVE_MAX_AGE_S = 0.25  # the runner publishes live.json every ~0.1 s between chunks; the 0.6 s observation limit is unchanged


def _live_snapshot(cell):
    """The running session's own latest joint sample, with no FIFO round trip (2026-11-26: 9 stale refusals). None unless
    it is fresh, idle between chunks and clean; the caller then asks the runner as before."""
    live = cell.policy_state() if hasattr(cell, "policy_state") else None
    t = live.get("t") if isinstance(live, dict) else None
    if (isinstance(t, bool) or not isinstance(t, (int, float)) or not 0 <= time.time() - t <= LIVE_MAX_AGE_S
            or live.get("chunk") is not None or any(live.get(k) for k in FAULT_KEYS) or not live.get("state")):
        return None
    return {**live, "ok": True}


def _fresh_snapshot(cell, previous, deadline, clock, sleep, dry_run):
    if dry_run and hasattr(cell, "policy_state"):
        return cell.policy_state() or {}
    if previous is None or not hasattr(cell, "policy_state"):
        return _live_snapshot(cell) or cell.act("state")
    while clock() < deadline:
        status = cell.policy_state()
        if status and status.get("policy_start") == previous and not status.get("fault"):
            return status
        sleep(0.005)
    raise ValueError("policy observation unavailable during playback")


def _observe(cell, shadow, infer, age, previous, previous_end, clock, sleep, dry_run, *, seed_state=None):
    state = _fresh_snapshot(cell, previous, previous_end, clock, sleep, dry_run)
    observed = clock()
    if dry_run and seed_state is not None and isinstance(state, dict) and state.get("fault") == "no runner":
        state = {"ok": True, "state": list(seed_state), "holding": False}
    if state.get("fault") or state.get("ok") is False or not state.get("state"):
        raise ValueError("policy encoder state unavailable")
    if "t" in state:
        observed -= max(0, time.time() - state["t"])
    images = {}
    for name in shadow.image_views:
        if hasattr(cell, "frame_receipt"):
            frame = cell.frame_receipt(name, max_age_s=age, timeout_s=age)
            observed = min(observed, clock() - max(0, time.time() - frame["source_stamp"]))
            images[name] = frame["image"]
        else:
            images[name] = cell.frame(name)
    infer_state = list(seed_state) if (dry_run and seed_state is not None) else state["state"]
    started = clock()
    chunk, meta = infer(infer_state, images)
    done = clock()
    return Prediction(observed, done - started, done, chunk, meta, infer_state)


def _dry_play(spec, frames, target, fps, clock, sleep):
    playback = Playback(spec, fps)
    frames = list(frames)
    while frames:
        sleep(max(0.0, playback.due - clock()))
        try:
            ready = playback.ready(frames, target, clock())
        except ValueError as error:
            return {"ok": False, "policy_stop": str(error), "timing": playback.receipt()}
        if ready:
            target = frames.pop(0)
            playback.sent(clock())
    return {"ok": True, "timing": playback.receipt()}


def step_count(shadow, n_action):
    if n_action is None:
        n_action = 8 if getattr(shadow, "sim_rule", None) is not None else (shadow.n_action_steps or shadow.chunk_size)
    size = getattr(shadow, "chunk_size", None)
    if type(n_action) is not int or n_action < 1 or type(size) is not int or size < 1:
        raise ValueError("policy requires positive n_action and checkpoint chunk_size")
    return min(n_action, size)


def run_timed(cell, shadow, library, work, *, infer, shape, max_step, n_action, max_obs_age_s,
              max_chunks, dry_run, log, handoff=None, authorize=None, clock=time.monotonic, sleep=time.sleep,
              jaw_gate: dict | None = None, kin=None, jaw_spec: dict | None = None, state_gate=None):
    fps = library.get("fps", 30)
    model_fps = SIM_FPS if getattr(shadow, "sim_rule", None) is not None else fps
    steps = step_count(shadow, n_action)
    if not math.isfinite(max_obs_age_s) or not 0 < max_obs_age_s <= 5:
        raise ValueError("max observation age must be in (0, 5] seconds")
    entry_frames = validate_entry_chunk(library, kin, jaw_spec)
    entry_pose = entry_frames[-1] if entry_frames else None
    pool = ThreadPoolExecutor(max_workers=1)
    pending = previous_end = previous_command = None
    held = moved = park_safe = hold_needed = safety_done = entry_ran = False
    dry_seed_state = list(entry_pose) if (dry_run and entry_pose is not None) else None
    prefix = ""

    def observe(previous, deadline, seed_state=None):
        if previous is not None:
            # Take a newer sample within the window, keeping time for the next inference.
            sleep(max(0.0, previous + 2 / fps - clock()))
        return _observe(cell, shadow, infer, max_obs_age_s, previous, deadline, clock, sleep, dry_run, seed_state=seed_state)

    def stopped(n, reason, row, status=None):
        nonlocal park_safe, hold_needed, safety_done
        rest = not dry_run and not moved and rest_diagnosis(status, library_home(library))["no_hold"]  # no command sent, at home or folded
        park_safe, hold_needed = False, hold_needed or not (dry_run or rest)
        stop = None if dry_run or rest else send_hold(cell, log=log)
        safety_done = safety_done or not dry_run
        # only before any command: after motion the hold goes first and nothing slow (the diagnosis imports modules) may follow it
        facts = ({k: v for k, v in rest_diagnosis(status, library_home(library)).items() if k != "no_hold"}
                 if status is not None and not moved else {})
        for entry in ({**row, "policy_stop": reason, **facts, "hold_kept": not (dry_run or rest)}, *([{"command": "human-hold", **ack_status(stop)}] if stop is not None else ())):
            log(entry)
        return {"result": "refused", "at": n, "reason": reason, **facts, **({"status": status} if status else {})}

    def finish_park(result_name: str, *, log_hold: bool = True) -> dict:
        nonlocal park_safe, hold_needed, safety_done
        park_safe = False
        try:
            parked = cell.act(prefix + "park")
        except BaseException:
            hold_needed, safety_done = True, best_effort_hold(cell, log=log) is not None
            raise
        if park_ack_ok(parked, require_command=True):
            safety_done = True
            return {"result": result_name, "held": held, "parked": True}
        hold_needed = True
        hold = send_hold(cell, log=log)
        safety_done = True
        if log_hold:
            log({"command": "human-hold", **ack_status(hold)})
        return {"result": result_name, "held": held, "parked": False}

    try:
        if entry_frames is not None and not dry_run:
            hold_needed = True
            init_state = cell.act("state")
            ok, _, err_msg = valid_state(init_state)
            if not ok:
                return stopped(0, err_msg or "policy start state unavailable", {"chunk": 0, "dry_run": False})
            if state_gate is not None and (why := state_gate.roll_error(init_state["state"])):
                return stopped(0, why, {"chunk": 0, "dry_run": False}, init_state)
            home_pose = pose6(library["chunks"]["home"][-1])
            if (max_diff(init_state["state"], home_pose, 5) > ENTRY_START_TOL
                    or not empty_gripper_ok(init_state, now=time.time())):
                return stopped(0, "START_POSE_OFF_HOME: arm off home; run home stage first", {"chunk": 0, "dry_run": False}, init_state)
            _ran_e, entry_prefix, entry_err = run_entry_chunk(cell, library, work, init_state, authorize, log, jaw_gate=jaw_gate)
            if entry_err is not None:
                safety_done = True
                return entry_err
            prefix, moved, park_safe, entry_ran = entry_prefix, True, True, True
            post_entry = cell.act("state")
            if not _entry_ready(post_entry, entry_pose):
                return stopped(0, "POST_ENTRY_STATE_MISMATCH: arm not settled at entry pose with empty gripper",
                               {"chunk": 0, "dry_run": False}, post_entry if isinstance(post_entry, dict) else None)
            if state_gate is not None and (why := state_gate.verdict(post_entry["state"], after_entry=True)):
                return stopped(0, why, {"chunk": 0, "dry_run": False}, post_entry)  # before any camera frame
            hold_needed = False
        for n in range(max_chunks):
            row = {"chunk": n, "dry_run": dry_run, "model_fps": model_fps, "library_fps": fps}
            try:
                if not dry_run:
                    hold_needed = True
                first_chunk = pending is None
                pending = pool.submit(observe, None, None, dry_seed_state) if first_chunk else pending
                try:
                    prediction = pending.result(timeout=max_obs_age_s if first_chunk else max(0.0, previous_end - clock()))
                except TimeoutError as exc:
                    return stopped(n, (str(exc) or "policy inference timed out") if first_chunk else "next policy chunk missed its playback deadline", row)
                if not first_chunk and prediction.ready_at > previous_end:
                    return stopped(n, "next policy chunk missed its playback deadline", row)
                state = {"state": prediction.state, "ok": True} if dry_run else cell.act("state")
                if not state.get("ok") or state.get("fault"):
                    raise ValueError("policy start state unavailable")
                if state_gate is not None and (n > 0 or entry_pose is None or dry_run) and (why := state_gate.verdict(state["state"], after_entry=n == 0 and entry_pose is not None)):
                    return stopped(n, why, row, state)
                if n == 0 and entry_ran and not dry_run and not _entry_ready(state, entry_pose):
                    return stopped(n, "POST_ENTRY_STATE_MISMATCH: arm not at entry pose before chunk 0", row, state)
                target = state["state"] if dry_run else (state.get("target") or state["state"])
                # Budget two FIFO ticks for load and run. The runner trims any overrun.
                dispatch_at = clock() + 2 / fps
                row.update(observed_mono=prediction.observed, inference_s=prediction.inferred, meta=prediction.meta,
                           observation_age_s=dispatch_at - prediction.observed)
                if dry_run:
                    row["converted_chunk"] = prediction.frames.tolist()
                    if n == 0 and entry_pose is not None:
                        row["entry_pose"] = list(entry_pose)
                actions, dropped = action_window(prediction.frames, prediction.observed, dispatch_at, model_fps, steps, max_obs_age_s)
                row.update(action_steps=len(actions), dropped_actions=dropped,
                           proposed_first=actions[0].tolist(), proposed_last=actions[-1].tolist())
                frames = shape(actions, target, model_fps, fps, held, row, prediction.frames, state["state"])
                if len(frames) > math.ceil(len(actions) * fps / model_fps):
                    raise ValueError("policy window cannot play at the reviewed step rate")
                start = prediction.observed + dropped / model_fps
                spec = dict(start=start, observed=prediction.observed, max_age=max_obs_age_s, max_step=max_step)
                if handoff is not None:
                    spec["handoff"] = handoff.spec
                if jaw_gate is not None:
                    spec["jaw_gate"] = jaw_gate
                previous_end = start + len(frames) / fps
                if not dry_run:
                    generated = {**library, "policy_playback": spec, "chunks": {**library["chunks"], "policy": frames}}
                    path = work / f"policy-lib-{time.time_ns()}-{n}.json"
                    path.write_text(json.dumps(generated), encoding="utf-8")
                    sequence = ("run policy",) if handoff is not None else ("run policy", "park")
                    auth_kw = {"check_home": False} if (entry_ran and getattr(authorize, "supports_check_home", False)) else {}
                    next_prefix = (f"checked {a['session_id']} {a['library_sha256']} "
                                   if authorize and (a := authorize(generated, state, sequence, **auth_kw)) else prefix)
                    park_safe, hold_needed = False, True
                    load = cell.act(f"{next_prefix}load {path}")
                    if not isinstance(load, dict) or not load.get("ok") or any(load.get(k) for k in FAULT_KEYS):
                        reason = ((load.get("error") or load.get("fault")) if isinstance(load, dict) else None) or "policy load refused"
                        return stopped(n, reason, row, load if isinstance(load, dict) else None)
                    prefix = next_prefix
                    if clock() - prediction.observed > max_obs_age_s:
                        return stopped(n, "stale policy observation after load", row)
                sample_window = max(start, dispatch_at) if dry_run else start
                next_seed = list(frames[-1]) if (dry_run and entry_frames is not None) else None
                pending = pool.submit(observe, sample_window, previous_end, next_seed) if n + 1 < max_chunks else None
                if dry_run:
                    sleep(max(0.0, dispatch_at - clock()))
                    ran = _dry_play(spec, frames, target, fps, clock, sleep)
                else:
                    moved, park_safe = True, False
                    ran = cell.act(f"{prefix}run policy")
            except (OSError, ValueError, RuntimeError, TimeoutError, KeyError) as error:
                if dry_run:
                    row["envelope"] = {"ok": False, "reason": str(error)}
                return stopped(n, str(error) or "policy inference timed out", row)
            if not isinstance(ran, dict):
                return stopped(n, "unexpected policy reply command", row)
            cmd = raw_cmd.split(" ", 3)[-1] if (raw_cmd := str(ran.get("command") or "")).startswith("checked ") else raw_cmd
            wrong_cmd = False if dry_run else cmd != "run policy"
            unsettled = (ran.get("settled") is False) if dry_run else (ran.get("settled") is not True)
            if not ran.get("ok") or ran.get("fault") or ran.get("hold") or ran.get("human_hold_latched") or unsettled or wrong_cmd:
                reason = (ran.get("policy_stop") or ran.get("error") or ran.get("fault")
                          or ("unexpected policy reply command" if wrong_cmd else "policy chunk did not settle" if unsettled else "policy playback refused"))
                return stopped(n, reason, row, ran)
            timing = raw_t if isinstance(raw_t := ran.get("timing"), dict) else {}
            first = timing.get("first_command_mono")
            row.update({k: v for k, v in timing.items() if v is not None},
                       gap_since_previous_chunk_s=first - previous_command if first is not None and previous_command is not None else None,
                       handoff=ran.get("handoff"), frames=len(frames), command="run policy", ok=ran.get("ok"),
                       state=prediction.state, end_state=ran.get("state"))
            previous_command = timing.get("last_command_mono")
            if dry_run:
                row["envelope"] = {"ok": True}
            park_safe, hold_needed = not dry_run, False
            log(row)
            if handoff is not None and (ran.get("handoff") or {}).get("triggered"):
                if pending is not None:
                    pending.cancel()
                park_safe, hold_needed = False, True
                return handoff.carry(cell, ran, authorize, log)
            held = held or bool(ran.get("holding"))
            if not dry_run and handoff is None and held and frames[-1][5] > library["gripper_closed"] + 10:
                return finish_park("released")
        if dry_run:
            return {"result": "dry_run", "chunks": max_chunks}
        return stopped(max_chunks, "ACT ended before a verified handoff", {"chunk": max_chunks}) if handoff is not None else finish_park("chunks_done")
    except BaseException as exc:
        if not dry_run and (moved or hold_needed or not isinstance(exc, Exception)) and not safety_done:
            try:
                if isinstance(exc, Exception) and park_safe and not hold_needed and handoff is None:
                    finish_park("chunks_done", log_hold=False)
                else:
                    safety_done = best_effort_hold(cell, log=log) is not None
            except BaseException:
                if not safety_done:
                    safety_done = best_effort_hold(cell, log=log) is not None
        raise
    finally:
        if pending is not None and not pending.cancel():
            try:
                pending.result(timeout=max(max_obs_age_s, 1.0))
            except BaseException:
                pass
        pool.shutdown(wait=False, cancel_futures=True)


from cell_policy_retreat import retreat_from_jaw_zone, retreat_from_jaw_zone_frames  # noqa: E402,F401
