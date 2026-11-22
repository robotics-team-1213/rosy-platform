"""A single outstanding ACT inference and a guarded, time-stamped playback window."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import json
import math
import time

import numpy as np

from chunk_policy_playback import Playback

SIM_FPS = 15
MAX_OBSERVATION_AGE_S = 0.6


@dataclass
class Prediction:
    observed: float
    inferred: float
    ready_at: float
    frames: np.ndarray
    meta: dict
    state: list


def park_ack_ok(reply) -> bool:
    """True only on a settled, fault-free park ack, never on a preempting human-hold or timeout row."""
    if not isinstance(reply, dict) or reply.get("ok") is not True:
        return False
    if reply.get("fault") or reply.get("hold") or reply.get("human_hold_latched"):
        return False
    if reply.get("settled") is not True:
        return False
    if "command" in reply:
        cmd = str(reply["command"])
        if cmd.startswith("checked "):
            cmd = cmd.split(" ", 3)[-1]
        if cmd not in ("park", "run park"):
            return False
    return True


def action_window(chunk, observed, start, fps, steps, max_age):
    if start - observed > max_age:
        raise ValueError("stale policy observation")
    dropped = max(0, math.floor((start - observed) * fps))
    frames = chunk[dropped:dropped + steps]
    if not len(frames):
        raise ValueError("policy chunk is late, all action times passed")
    return frames, dropped


def _fresh_snapshot(cell, previous, deadline, clock, sleep, dry_run):
    if dry_run and hasattr(cell, "policy_state"):
        return cell.policy_state() or {}
    if previous is None or not hasattr(cell, "policy_state"):
        return cell.act("state")
    while clock() < deadline:
        status = cell.policy_state()
        if status and status.get("policy_start") == previous and not status.get("fault"):
            return status
        sleep(0.005)
    raise ValueError("policy observation unavailable during playback")


def _observe(cell, shadow, infer, age, previous, previous_end, clock, sleep, dry_run):
    state = _fresh_snapshot(cell, previous, previous_end, clock, sleep, dry_run)
    observed = clock()
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
    started = clock()
    chunk, meta = infer(state["state"], images)
    done = clock()
    return Prediction(observed, done - started, done, chunk, meta, state["state"])


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
              jaw_gate: dict | None = None):
    fps = library.get("fps", 30)
    model_fps = SIM_FPS if getattr(shadow, "sim_rule", None) is not None else fps
    steps = step_count(shadow, n_action)
    if not math.isfinite(max_obs_age_s) or not 0 < max_obs_age_s <= 5:
        raise ValueError("max observation age must be in (0, 5] seconds")
    pool = ThreadPoolExecutor(max_workers=1)
    pending = None
    previous_end = previous_command = None
    held = False
    prefix = ""

    def observe(previous, deadline):
        if previous is not None:
            # Take a newer sample within the window, keeping time for the next inference.
            sleep(max(0.0, previous + 2 / fps - clock()))
        return _observe(cell, shadow, infer, max_obs_age_s, previous, deadline, clock, sleep, dry_run)

    def stopped(n, reason, row, status=None):
        stop = None if dry_run else cell.act("human-hold")
        log({**row, "policy_stop": reason})
        if stop is not None:
            log({"command": "human-hold", **stop})
        return {"result": "refused", "at": n, "reason": reason, **({"status": status} if status else {})}

    try:
        for n in range(max_chunks):
            row = {"chunk": n, "dry_run": dry_run, "model_fps": model_fps, "library_fps": fps}
            try:
                if pending is None:
                    pending = pool.submit(observe, None, None)
                    prediction = pending.result(timeout=max_obs_age_s)
                else:
                    try:
                        prediction = pending.result(timeout=max(0.0, previous_end - clock()))
                    except TimeoutError:
                        return stopped(n, "next policy chunk missed its playback deadline", row)
                    if prediction.ready_at > previous_end:
                        return stopped(n, "next policy chunk missed its playback deadline", row)
                state = {"state": prediction.state, "ok": True} if dry_run else cell.act("state")
                if not state.get("ok") or state.get("fault"):
                    raise ValueError("policy start state unavailable")
                target = state["state"] if dry_run else (state.get("target") or state["state"])
                # Budget two FIFO ticks for load and run. The runner trims any overrun.
                dispatch_at = clock() + 2 / fps
                row.update(observed_mono=prediction.observed, inference_s=prediction.inferred, meta=prediction.meta,
                           observation_age_s=dispatch_at - prediction.observed)
                if dry_run:
                    row["converted_chunk"] = prediction.frames.tolist()
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
                    assessment = authorize(generated, state, sequence) if authorize else None
                    if assessment is not None:
                        prefix = f"checked {assessment['session_id']} {assessment['library_sha256']} "
                    load = cell.act(f"{prefix}load {path}")
                    if not load.get("ok"):
                        return stopped(n, load.get("error") or "policy load refused", row, load)
                    if clock() - prediction.observed > max_obs_age_s:
                        return stopped(n, "stale policy observation after load", row)
                sample_window = max(start, dispatch_at) if dry_run else start
                pending = pool.submit(observe, sample_window, previous_end) if n + 1 < max_chunks else None
                if dry_run:
                    sleep(max(0.0, dispatch_at - clock()))
                    ran = _dry_play(spec, frames, target, fps, clock, sleep)
                else:
                    ran = cell.act(f"{prefix}run policy")
            except (OSError, ValueError, RuntimeError, TimeoutError, KeyError) as error:
                if dry_run:
                    row["envelope"] = {"ok": False, "reason": str(error)}
                return stopped(n, str(error) or "policy inference timed out", row)
            timing = ran.get("timing") or {}
            first = timing.get("first_command_mono")
            row.update({k: v for k, v in timing.items() if v is not None},
                       gap_since_previous_chunk_s=first - previous_command if first is not None and previous_command is not None else None,
                       handoff=ran.get("handoff"), frames=len(frames), command="run policy", ok=ran.get("ok"),
                       state=prediction.state, end_state=ran.get("state"))
            previous_command = timing.get("last_command_mono")
            if not ran.get("ok") or ran.get("fault") or ran.get("settled") is False:
                reason = ran.get("policy_stop") or ran.get("error") or ran.get("fault") or (
                    "policy chunk did not settle" if ran.get("settled") is False else "policy playback refused"
                )
                return stopped(n, reason, row, ran)
            if dry_run:
                row["envelope"] = {"ok": True}
            log(row)
            if handoff is not None and (ran.get("handoff") or {}).get("triggered"):
                if pending is not None:
                    pending.cancel()
                return handoff.carry(cell, ran, authorize, log)
            held = held or bool(ran.get("holding"))
            if not dry_run and handoff is None and held and frames[-1][5] > library["gripper_closed"] + 10:
                parked = cell.act(prefix + "park")
                return {"result": "released", "held": held, "parked": park_ack_ok(parked)}
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    if dry_run:
        return {"result": "dry_run", "chunks": max_chunks}
    if handoff is not None:
        return stopped(max_chunks, "ACT ended before a verified handoff", {"chunk": max_chunks})
    return {"result": "chunks_done", "held": held, "parked": park_ack_ok(cell.act(prefix + "park"))}
