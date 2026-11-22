"""A single outstanding ACT inference and a guarded, time-stamped playback window."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import json
import math
import time

import numpy as np

from chunk_policy_playback import Playback

SIM_FPS, MAX_OBSERVATION_AGE_S = 15, 0.6
FAULT_KEYS = ("fault", "contact", "hold", "human_hold_latched")


@dataclass
class Prediction:
    observed: float
    inferred: float
    ready_at: float
    frames: np.ndarray
    meta: dict
    state: list


def ack_status(status: dict) -> dict:
    out = {k: status.get(k) for k in ("ok", "error", "fault", "contact", "holding", "settled", "state")}
    for k in ("t", "human_hold_latched", "torque_hold_commanded"):
        if k in status:
            out[k] = status[k]
    return out


def finite_stamp(val) -> float | None:
    if not isinstance(val, (int, float)) or isinstance(val, bool):
        return None
    try:
        num = float(val)
    except (TypeError, ValueError, OverflowError):
        return None
    return num if math.isfinite(num) else None


def pose6(raw) -> list[float] | None:
    return vals if isinstance(raw, (list, tuple)) and len(raw) == 6 and None not in (vals := [finite_stamp(v) for v in raw]) else None


def max_diff(a: list[float], b: list[float], n: int | None = None) -> float:
    return max(abs(x - y) for x, y in zip(a[:n] if n else a, b[:n] if n else b))


def valid_state(status: dict) -> tuple[bool, bool, str | None]:
    hold_or_fault = bool(isinstance(status, dict) and any(status.get(k) for k in FAULT_KEYS))
    if not isinstance(status, dict) or not status.get("ok") or hold_or_fault or pose6(status.get("state")) is None:
        msg = ((status.get("error") or status.get("fault")) if isinstance(status, dict) else None) or "policy start state unavailable"
        return False, hold_or_fault, str(msg)
    return True, False, None


def empty_gripper_ok(status: dict, current_limit_ma: float = 140.0, *, max_health_age_s: float = 1.0, now: float | None = None) -> bool:
    if not isinstance(status, dict) or status.get("holding") is not False:
        return False
    hw = isinstance(status.get("operating_context"), dict) and status["operating_context"].get("scope") == "hardware"
    health = status.get("health")
    if hw:
        ht, ref_t = finite_stamp(status.get("health_t")), finite_stamp(status.get("t"))
        if (not isinstance(health, dict) or "current_ma" not in health or ht is None or ref_t is None
                or not (-0.05 <= ref_t - ht <= max_health_age_s)
                or (now is not None and not (-1.0 <= now - ht <= max_health_age_s))):
            return False
    if isinstance(health, dict) and "current_ma" in health:
        cur = health.get("current_ma")
        if not isinstance(cur, (list, tuple)) or len(cur) < 6 or (c5 := finite_stamp(cur[5])) is None or abs(c5) >= current_limit_ma:
            return False
    return True


def cmd_ack_ok(reply, expected: tuple[str, ...], *, require_command: bool = False) -> bool:
    if (not isinstance(reply, dict) or reply.get("ok") is not True
            or any(reply.get(k) for k in ("fault", "hold", "human_hold_latched")) or reply.get("settled") is not True):
        return False
    if "command" not in reply:
        return not require_command
    cmd = str(reply["command"])
    return (cmd.split(" ", 3)[-1] if cmd.startswith("checked ") else cmd) in expected


def park_ack_ok(reply, *, require_command: bool = False) -> bool:
    """True only on a settled, fault-free park ack, never on a preempting human-hold or timeout row."""
    return cmd_ack_ok(reply, ("park", "run park"), require_command=require_command)


def retreat_ack_ok(reply) -> bool:
    """True only on an explicitly labeled, settled, fault-free retreat ack."""
    return cmd_ack_ok(reply, ("retreat", "run retreat"), require_command=True)


def hold_ack_ok(reply) -> bool:
    """True only when the owner confirms HOLD execution (`command`, `ok`, `human_hold_latched`, `torque_hold_commanded`, not `released`)."""
    return (isinstance(reply, dict) and reply.get("command") == "human-hold" and reply.get("ok") is True
            and not reply.get("released") and reply.get("human_hold_latched") is True
            and reply.get("torque_hold_commanded") is True)


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
    pending = previous_end = previous_command = None
    held = moved = park_safe = hold_needed = safety_done = False
    prefix = ""

    def observe(previous, deadline):
        if previous is not None:
            # Take a newer sample within the window, keeping time for the next inference.
            sleep(max(0.0, previous + 2 / fps - clock()))
        return _observe(cell, shadow, infer, max_obs_age_s, previous, deadline, clock, sleep, dry_run)

    def stopped(n, reason, row, status=None):
        nonlocal park_safe, hold_needed, safety_done
        park_safe, hold_needed = False, hold_needed or not dry_run
        stop = None if dry_run else send_hold(cell, log=log)
        safety_done = safety_done or not dry_run
        for entry in ({**row, "policy_stop": reason}, *([{"command": "human-hold", **ack_status(stop)}] if stop is not None else ())):
            log(entry)
        return {"result": "refused", "at": n, "reason": reason, **({"status": status} if status else {})}

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
        for n in range(max_chunks):
            row = {"chunk": n, "dry_run": dry_run, "model_fps": model_fps, "library_fps": fps}
            try:
                if not dry_run:
                    hold_needed = True
                first_chunk = pending is None
                pending = pool.submit(observe, None, None) if first_chunk else pending
                try:
                    prediction = pending.result(timeout=max_obs_age_s if first_chunk else max(0.0, previous_end - clock()))
                except TimeoutError as exc:
                    return stopped(n, (str(exc) or "policy inference timed out") if first_chunk else "next policy chunk missed its playback deadline", row)
                if not first_chunk and prediction.ready_at > previous_end:
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
                    next_prefix = (f"checked {a['session_id']} {a['library_sha256']} "
                                   if authorize and (a := authorize(generated, state, sequence)) else prefix)
                    park_safe, hold_needed = False, True
                    load = cell.act(f"{next_prefix}load {path}")
                    if not isinstance(load, dict) or not load.get("ok") or any(load.get(k) for k in FAULT_KEYS):
                        reason = ((load.get("error") or load.get("fault")) if isinstance(load, dict) else None) or "policy load refused"
                        return stopped(n, reason, row, load if isinstance(load, dict) else None)
                    prefix = next_prefix
                    if clock() - prediction.observed > max_obs_age_s:
                        return stopped(n, "stale policy observation after load", row)
                sample_window = max(start, dispatch_at) if dry_run else start
                pending = pool.submit(observe, sample_window, previous_end) if n + 1 < max_chunks else None
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
        pool.shutdown(wait=False, cancel_futures=True)
