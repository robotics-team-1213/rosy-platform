"""Guarded step-rate-stretched ACT chunk execution loop (`arm_s` paced mode)."""
from __future__ import annotations

import json
import math
from pathlib import Path
import time

import numpy as np

PRE_SETTLE_TOL = 2.0
SETTLE_TOL = 3.0  # matches chunk_runner_guards.SETTLE_TOL / cell_unwedge post-park tolerance
FOLDED_TOL = 10.0  # D-1048 upper bound: extended poses refuse rather than blindly calling park
HOLD_CURRENT_LIMIT_MA = 140.0


def _moved_snapshot(state, ran: dict, top_before, cell, work: Path, n: int) -> dict:
    """Did the arm move: joint travel the encoders measured and how much the top view changed (mean |diff|, 0-255)."""
    out = {"joint_travel": float(np.abs(np.asarray(ran.get("state") or state, dtype=float) - state).max())}
    try:
        import cv2

        top_after = cell.frame("top")
        out["top_change"] = round(float(np.abs(top_before.astype(np.int16) - top_after.astype(np.int16)).mean()), 2)
        shots = work / "policy-frames"
        shots.mkdir(exist_ok=True)
        cv2.imwrite(str(shots / f"{int(time.time())}-{n}-before.jpg"), top_before)
        cv2.imwrite(str(shots / f"{int(time.time())}-{n}-after.jpg"), top_after)
    except Exception as exc:  # camera evidence never stops the episode
        out["top_change_error"] = str(exc)[:120]
    return out


def _ack_status(status: dict) -> dict:
    keys = ("ok", "error", "fault", "contact", "holding", "settled", "state")
    return {**{k: status.get(k) for k in keys}, **({"t": status["t"]} if "t" in status else {})}


def _finite_vec6(raw) -> bool:
    return isinstance(raw, (list, tuple)) and len(raw) == 6 and all(
        isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in raw
    )


def _valid_state(status: dict) -> tuple[bool, bool, str | None]:
    hold_or_fault = bool(status.get("fault") or status.get("hold") or status.get("human_hold_latched"))
    if not status.get("ok") or hold_or_fault or not _finite_vec6(status.get("state")):
        return False, hold_or_fault, str(status.get("error") or status.get("fault") or "policy start state unavailable")
    return True, False, None


def _finite_stamp(val, ref_now: float) -> bool:
    return isinstance(val, (int, float)) and not isinstance(val, bool) and math.isfinite(val) and 0.0 <= val <= ref_now + 1.0


def _empty_gripper_ok(status: dict) -> bool:
    if status.get("holding") is not False:
        return False
    health = status.get("health")
    if isinstance(health, dict) and "current_ma" in health:
        cur = health.get("current_ma")
        if (not isinstance(cur, (list, tuple)) or len(cur) < 6
                or not isinstance(cur[5], (int, float)) or isinstance(cur[5], bool)
                or not math.isfinite(cur[5]) or abs(cur[5]) >= HOLD_CURRENT_LIMIT_MA):
            return False
    return True


def _pre_settle_home(cell, library: dict, work: Path, status: dict, row: dict, authorize, log,
                     park_ack_ok) -> tuple[dict | None, dict | None]:
    """Ensure arm starts near library home inside FOLDED_TOL via one authorized load+park; fail closed otherwise."""
    home_frames = (library.get("chunks") or {}).get("home")
    home = home_frames[-1] if isinstance(home_frames, (list, tuple)) and home_frames else None
    if not _finite_vec6(home):
        reason = "START_POSE_OFF_HOME: library missing home"
        log({**row, "refused": reason})
        return None, {"result": "refused", "at": 0, "reason": reason, "parked": False}
    off_home = max(abs(float(a) - float(b)) for a, b in zip(status["state"][:5], home[:5]))
    if off_home <= PRE_SETTLE_TOL:
        return status, None
    if off_home > FOLDED_TOL:
        reason = "START_POSE_OFF_HOME: arm outside folded window"
        log({**row, "refused": reason})
        return None, {"result": "refused", "at": 0, "reason": reason, "parked": False}
    if not _empty_gripper_ok(status):
        reason = "START_POSE_OFF_HOME: unconfirmed empty gripper"
        log({**row, "refused": reason, "command": "human-hold", **_ack_status(cell.act("human-hold"))})
        return None, {"result": "refused", "at": 0, "reason": reason, "parked": False}
    pre_prefix = ""
    if authorize is not None:
        try:
            assessment = (authorize(library, status, ("park",), check_home=False)
                          if getattr(authorize, "supports_check_home", False)
                          else authorize(library, status, ("park",)))
        except ValueError as err:
            log({**row, "refused": str(err)})
            return None, {"result": "refused", "at": 0, "reason": str(err), "parked": False}
        pre_prefix = f"checked {assessment['session_id']} {assessment['library_sha256']} "
    pre_path = work / f"policy-presettle-{time.time_ns()}.json"
    pre_path.write_text(json.dumps(library), encoding="utf-8")
    pre_loaded = cell.act(f"{pre_prefix}load {pre_path}")
    log({**row, "command": "load", "pre_settle": True, **_ack_status(pre_loaded)})
    if not pre_loaded.get("ok"):
        if pre_loaded.get("fault") or pre_loaded.get("hold") or pre_loaded.get("human_hold_latched"):
            log({**row, "command": "human-hold", **_ack_status(cell.act("human-hold"))})
        return None, {"result": "refused", "at": 0, "reason": pre_loaded.get("error") or "pre-settle load failed",
                      "parked": False}
    park_reply = cell.act(pre_prefix + "park")
    log({**row, "command": "park", "pre_settle": True, **_ack_status(park_reply)})
    if not park_ack_ok(park_reply):
        log({**row, "command": "human-hold", **_ack_status(cell.act("human-hold"))})
        return None, {"result": "refused", "at": 0, "reason": "pre-settle park failed", "parked": False,
                      "park": _ack_status(park_reply)}
    fresh = cell.act("state")
    ok, hold_or_fault, err_msg = _valid_state(fresh)
    if not ok:
        if hold_or_fault:
            log({**row, "command": "human-hold", **_ack_status(cell.act("human-hold"))})
        log({**row, "refused": err_msg, **_ack_status(fresh)})
        return None, {"result": "fault" if fresh.get("fault") else "refused", "at": 0, "reason": err_msg,
                      "parked": False}
    if max(abs(float(a) - float(b)) for a, b in zip(fresh["state"][:5], home[:5])) > SETTLE_TOL:
        log({**row, "refused": "START_POSE_OFF_HOME", **_ack_status(fresh)})
        return None, {"result": "refused", "at": 0, "reason": "START_POSE_OFF_HOME", "parked": False}
    return fresh, None


def run_paced_chunks(cell, shadow, library: dict, work: Path, *, off, max_chunks: int, dry_run: bool, log, goal: dict,
                     sim_units: bool, open_g: float, model_closed: float, closed: float, low, high, fastest: float,
                     kin, jaw_spec, resolved_tcp, authorize, max_obs_age_s: float = 0.6,
                     pre_home: bool = False) -> dict:
    """Guarded step-rate-stretched chunk loop for full-chunk ACT checkpoints (e.g. arm_s)."""
    from cell_policy_shape import in_jaw_zone, jaw_zone_error, open_before_close, shape_chunk
    from cell_policy_timing import park_ack_ok

    def _safe_park_or_hold(cmd_prefix: str = "", *, fault: bool = False) -> tuple[bool, dict | None]:
        if dry_run:
            return False, None
        if fault:
            log({"command": "human-hold", **_ack_status(cell.act("human-hold"))})
            return False, None
        park_reply = cell.act(cmd_prefix + "park")
        log({"command": "park", **_ack_status(park_reply)})
        if park_ack_ok(park_reply):
            return True, park_reply
        log({"command": "human-hold", **_ack_status(cell.act("human-hold"))})
        return False, park_reply

    def _fail(res: str, at: int, reason, cmd_prefix: str = "", *, fault: bool = False, extra: dict | None = None) -> dict:
        parked_ok, park_reply = _safe_park_or_hold(cmd_prefix, fault=fault)
        return {"result": res, "at": at, "reason": reason, **(extra or {}), "parked": parked_ok,
                **({"park": _ack_status(park_reply)} if park_reply is not None else {})}

    def _legacy_jaw_hold(row, n: int, jaw_warn: str) -> dict:
        held_reply = cell.act("human-hold")
        log({**row, "refused": jaw_warn})
        log({"command": "human-hold", **_ack_status(held_reply)})
        return {"result": "refused", "at": n, "reason": jaw_warn, "parked": False}

    held, released, prefix = False, False, ""
    for n in range(max_chunks):
        row = {"chunk": n, "dry_run": dry_run}
        try:
            status = cell.act("state")
            ok, hold_or_fault, err_msg = _valid_state(status)
            if not ok:
                log({**row, "refused": err_msg, **_ack_status(status)})
                return _fail("fault" if status.get("fault") else "refused", n, err_msg, fault=hold_or_fault)
            live_poses = [status["state"], *([status["target"]] if status.get("target") is not None else [])]
            if jaw_spec is not None and (jaw_warn := jaw_zone_error(live_poses, kin, jaw_spec)):
                row["jaw_warning"] = jaw_warn
                if not dry_run:
                    return _legacy_jaw_hold(row, n, jaw_warn)
            if n == 0 and pre_home and not dry_run:
                status, pre_err = _pre_settle_home(cell, library, work, status, row, authorize, log, park_ack_ok)
                if pre_err is not None:
                    return pre_err
                live_poses = [status["state"], *([status["target"]] if status.get("target") is not None else [])]
                if jaw_spec is not None and (jaw_warn := jaw_zone_error(live_poses, kin, jaw_spec)):
                    row["jaw_warning"] = jaw_warn
                    return _legacy_jaw_hold(row, n, jaw_warn)
            state = np.asarray(status["state"], dtype=float)
            frames, oldest_stamp, state_now = {}, None, time.time()
            if "t" in status:
                if _finite_stamp(status["t"], state_now):
                    oldest_stamp = float(status["t"])
                elif not dry_run:
                    raise ValueError("stale policy observation: invalid state stamp")
            if hasattr(cell, "frame_receipt"):
                for view in shadow.image_views:
                    rec = cell.frame_receipt(view, max_age_s=max_obs_age_s, timeout_s=max_obs_age_s)
                    cam_now = time.time()
                    frames[view] = rec["image"]
                    stamp = rec.get("source_stamp")
                    if not _finite_stamp(stamp, cam_now):
                        if not dry_run:
                            raise ValueError("stale policy observation: missing or invalid camera stamp")
                        continue
                    oldest_stamp = float(stamp) if oldest_stamp is None else min(oldest_stamp, float(stamp))
            else:
                frames = {view: cell.frame(view) for view in shadow.image_views}
            obs, meta = shadow.inputs(state.tolist() if sim_units else (state + off).tolist(), frames, **goal)
            converted = np.asarray(shadow.infer(obs).chunk, dtype=float) - off
            proposed = converted if held else open_before_close(converted, open_g, model_closed)
            row = {**row, "state": state.tolist(), "meta": meta, "proposed_first": proposed[0].tolist(),
                   "proposed_last": proposed[-1].tolist()}
            if dry_run:
                row["converted_chunk"] = converted.tolist()
            force_all = jaw_spec is not None and in_jaw_zone(live_poses, kin, jaw_spec)
            try:
                frames_cell = shape_chunk(proposed, state, low, high, fastest)
            except ValueError as error:
                if dry_run:
                    row["envelope"] = {"ok": False, "reason": str(error)}
                log({**row, "refused": str(error)})
                return _fail("refused", n, str(error))
            if jaw_spec is not None and (jaw_warn := jaw_zone_error(frames_cell, kin, jaw_spec, force_all=force_all)):
                row["jaw_warning"] = jaw_warn
                if not dry_run:
                    return _legacy_jaw_hold(row, n, jaw_warn)
            row["frames"] = len(frames_cell)
            if dry_run:
                log({**row, "envelope": {"ok": True}})
                continue
            lib = {**library, "chunks": {**library["chunks"], "policy": frames_cell},
                   **({"jaw_gate": {**jaw_spec, "tcp_x_m": resolved_tcp}} if jaw_spec is not None else {})}
            path = work / f"policy-lib-{time.time_ns()}-{n}.json"
            path.write_text(json.dumps(lib), encoding="utf-8")
            prefix = ""
            if authorize is not None:
                auth_status = cell.act("state")
                auth_ok, auth_hold, auth_err = _valid_state(auth_status)
                if not auth_ok:
                    log({**row, "refused": auth_err, **_ack_status(auth_status)})
                    return _fail("fault" if auth_status.get("fault") else "refused", n, auth_err,
                                 fault=auth_hold or bool(auth_status.get("fault")))
                auth_poses = [auth_status["state"], *([auth_status["target"]] if auth_status.get("target") is not None else [])]
                if jaw_spec is not None:
                    if jaw_warn := jaw_zone_error(auth_poses, kin, jaw_spec):
                        row["jaw_warning"] = jaw_warn
                        return _legacy_jaw_hold(row, n, jaw_warn)
                    if not force_all and in_jaw_zone(auth_poses, kin, jaw_spec):
                        if jaw_warn := jaw_zone_error(frames_cell, kin, jaw_spec, force_all=True):
                            row["jaw_warning"] = jaw_warn
                            return _legacy_jaw_hold(row, n, jaw_warn)
                try:
                    assessment = authorize(lib, auth_status, ("run policy", "park"))
                except ValueError as error:
                    log({**row, "refused": str(error)})
                    return _fail("refused", n, str(error))
                prefix = f"checked {assessment['session_id']} {assessment['library_sha256']} "
            if oldest_stamp is not None and time.time() - oldest_stamp > max_obs_age_s:
                log({**row, "refused": "stale policy observation"})
                return _fail("refused", n, "stale policy observation")
        except Exception as error:  # fail closed on camera, inference, shaping, or file errors after chunk 0
            msg = str(error)[:200] or type(error).__name__
            log({**row, "refused": msg})
            return _fail("refused", n, msg)
        loaded = cell.act(f"{prefix}load {path}")
        log({**row, "command": "load", **_ack_status(loaded)})
        if not loaded.get("ok"):
            return _fail("refused", n, loaded.get("error"))
        if oldest_stamp is not None and time.time() - oldest_stamp > max_obs_age_s:
            log({**row, "refused": "stale policy observation"})
            return _fail("refused", n, "stale policy observation", prefix)
        ran = cell.act(prefix + "run policy")
        log({"command": "run policy", **_ack_status(ran), **_moved_snapshot(state, ran, frames.get("top"), cell, work, n)})
        if ran.get("contact"):
            if "overload-hold" not in (ran.get("error") or ""):
                log({"command": "retreat", **_ack_status(cell.act(prefix + "retreat"))})
            return _fail("contact", n, ran.get("error"), prefix, extra={"error": ran.get("error")})
        if not ran.get("ok"):
            is_fault = bool(ran.get("fault"))
            return _fail("fault" if is_fault else "refused", n, ran.get("error"), prefix,
                         fault=is_fault, extra={"error": ran.get("error")})
        if ran.get("settled") is False:
            return _fail("unsettled", n, ran.get("error") or "policy chunk did not settle", prefix,
                         extra={"error": ran.get("error")})
        held = held or bool(ran.get("holding"))
        released = held and [f[5] for f in frames_cell][-1] > closed + 10.0  # held something, then opened (OMX_RUN_STOP_ON_PLACE)
        if released:
            break
    if dry_run:
        return {"result": "dry_run", "chunks": max_chunks}
    parked_ok, park_reply = _safe_park_or_hold(prefix)
    return {"result": "released" if released else "chunks_done", "held": held, "parked": parked_ok,
            **({"park": _ack_status(park_reply)} if park_reply is not None else {})}
