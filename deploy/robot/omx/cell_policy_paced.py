"""Guarded step-rate-stretched ACT chunk execution loop (`arm_s` paced mode)."""
from __future__ import annotations

import json
from pathlib import Path
import time

import numpy as np

from cell_policy_timing import (
    FAULT_KEYS, ack_status as _ack_status, best_effort_hold as _best_effort_hold,
    empty_gripper_ok as _empty_gripper_ok, finite_stamp as _finite_num, max_diff as _max_diff, park_ack_ok,
    pose6 as _pose6, retreat_ack_ok, send_hold as _send_hold, valid_state as _valid_state,
)

PRE_SETTLE_TOL, STILL_TOL, STILL_WAIT_S, HOLD_CURRENT_LIMIT_MA = 2.0, 0.15, 0.08, 140.0


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


def _finite_stamp(val, ref_now: float) -> bool:
    return (num := _finite_num(val)) is not None and 0.0 <= num <= ref_now + 1.0


def _check_idle_sample(status: dict, home: list[float], *, check_home_target: bool, target_tol: float) -> tuple[list[float], list[float] | None] | None:
    ok, _, _ = _valid_state(status)
    if (not ok or status.get("holding") is True or status.get("chunk") is not None
            or (status.get("jitter") or {}).get("shaking")
            or (status.get("command") is not None and status.get("command") != "state")):
        return None
    pose = [float(v) for v in status["state"]]
    tgt = _pose6(status["target"]) if status.get("target") is not None else None
    if status.get("target") is not None and (tgt is None or _max_diff(pose, tgt, 5) > PRE_SETTLE_TOL
                                             or (check_home_target and _max_diff(tgt, home, 5) > target_tol)):
        return None
    return pose, tgt


def _live_idle_ok(cell, pose: list[float], home: list[float], *, check_home_target: bool, target_tol: float) -> bool:
    if not hasattr(cell, "policy_state"):
        return True
    try:
        live = cell.policy_state()
    except Exception:
        return False
    lp, lt = (_pose6(live.get("state")), _finite_num(live.get("t"))) if isinstance(live, dict) else (None, None)
    if (not isinstance(live, dict) or live.get("chunk") is not None or any(live.get(k) for k in FAULT_KEYS)
            or (live.get("jitter") or {}).get("shaking") or lp is None or lt is None
            or abs(time.time() - lt) > 1.0 or _max_diff(pose, lp) > STILL_TOL
            or (live.get("lag") is not None and ((lag := _finite_num(live.get("lag"))) is None or lag > PRE_SETTLE_TOL))):
        return False
    tg = _pose6(live.get("target")) if live.get("target") is not None else None
    return not (live.get("target") is not None and (tg is None or _max_diff(lp, tg, 5) > PRE_SETTLE_TOL
                or (check_home_target and _max_diff(tg, home, 5) > target_tol)))


def _stationary_idle(cell, status: dict, home: list[float], *, check_home_target: bool,
                     max_off_home: float, sleep=time.sleep) -> tuple[dict, list[float] | None]:
    p1, t1 = _check_idle_sample(status, home, check_home_target=check_home_target, target_tol=max_off_home) or (None, None)
    if p1 is None or _max_diff(p1, home, 5) > max_off_home or not _live_idle_ok(cell, p1, home, check_home_target=check_home_target, target_tol=max_off_home):
        return status, None
    sleep(STILL_WAIT_S)
    s2 = cell.act("state")
    p2, t2 = _check_idle_sample(s2, home, check_home_target=check_home_target, target_tol=max_off_home) or (None, None)
    if (p2 is None or _max_diff(p2, home, 5) > max_off_home or _max_diff(p2, p1) > STILL_TOL
            or (t1 is not None and t2 is not None and _max_diff(t2, t1) > STILL_TOL)
            or not _live_idle_ok(cell, p2, home, check_home_target=check_home_target, target_tol=max_off_home)):
        return s2, None
    return s2, p2


def _pre_settle_home(cell, library: dict, status: dict, row: dict, log, kin, jaw_spec,
                     *, sleep=time.sleep) -> tuple[dict | None, dict | None]:
    """Fail-closed verification that the arm starts stationary at home with a confirmed empty gripper."""
    from cell_policy_shape import jaw_zone_error

    hold_sent = False

    def _refuse(cur: dict, reason: str, *, base: dict = row, result: str = "refused", **extra):
        nonlocal hold_sent
        rows = [{**base, "refused": reason, **extra, **(_ack_status(cur) if isinstance(cur, dict) else {})}]
        rows.append({"command": "human-hold", **_ack_status(_send_hold(cell, log=log))})
        hold_sent = True
        for r in rows:
            log(r)
        return None, {"result": result, "at": 0, "reason": reason, "parked": False}

    try:
        if not _empty_gripper_ok(status, HOLD_CURRENT_LIMIT_MA, now=time.time()):
            return _refuse(status, "START_POSE_OFF_HOME: unconfirmed empty gripper",
                           result="fault" if status.get("fault") else "refused")
        home_frames = (library.get("chunks") or {}).get("home") if isinstance(library, dict) else None
        home = _pose6(home_frames[-1]) if isinstance(home_frames, (list, tuple)) and home_frames else None
        if home is None:
            return _refuse({}, "START_POSE_OFF_HOME: library missing home")
        if (off_home := _max_diff([float(v) for v in status["state"]], home, 5)) > PRE_SETTLE_TOL:
            return _refuse(status, "START_POSE_OFF_HOME: arm off home; run home stage first", off_home=round(off_home, 3))
        s2, p2 = _stationary_idle(cell, status, home, check_home_target=True, max_off_home=PRE_SETTLE_TOL, sleep=sleep)
        if not isinstance(s2, dict) or not _empty_gripper_ok(s2, HOLD_CURRENT_LIMIT_MA, now=time.time()):
            return _refuse(s2, "START_POSE_OFF_HOME: unconfirmed empty gripper",
                           result="fault" if isinstance(s2, dict) and s2.get("fault") else "refused")
        if p2 is None:
            return _refuse(s2, "START_POSE_OFF_HOME",
                           result="fault" if isinstance(s2, dict) and s2.get("fault") else "refused")
        live_poses = [p2, *([s2["target"]] if s2.get("target") is not None else [])]
        if jaw_spec is not None and (jaw_warn := jaw_zone_error(live_poses, kin, jaw_spec)):
            return _refuse(s2, jaw_warn, jaw_warning=jaw_warn)
        return s2, None
    except BaseException as exc:
        hold_row = _best_effort_hold(cell, log=log) if not hold_sent else None
        if not isinstance(exc, Exception) or (not hold_sent and hold_row is None):
            raise
        for entry in ({**row, "refused": "START_POSE_OFF_HOME", "error": str(exc)[:200] or type(exc).__name__},
                      *([hold_row] if hold_row else ())):
            try:
                log(entry)
            except Exception:
                pass
        return None, {"result": "refused", "at": 0, "reason": "START_POSE_OFF_HOME", "parked": False}


def run_paced_chunks(cell, shadow, library: dict, work: Path, *, off, max_chunks: int, dry_run: bool, log, goal: dict,
                     sim_units: bool, open_g: float, model_closed: float, closed: float, low, high, fastest: float,
                     kin, jaw_spec, resolved_tcp, authorize, max_obs_age_s: float = 0.6,
                     pre_home: bool = False) -> dict:
    """Guarded step-rate-stretched chunk loop for full-chunk ACT checkpoints (e.g. arm_s)."""
    from cell_policy_shape import in_jaw_zone, jaw_zone_error, open_before_close, shape_chunk

    held, released, prefix, moved, loaded_prefix, aborted, park_safe, hold_needed, safety_done = False, False, "", False, "", False, False, False, False

    def _hold_and_log(*rows: dict) -> None:
        nonlocal park_safe, hold_needed, safety_done
        park_safe, hold_needed = False, True
        hold_row = {"command": "human-hold", **_ack_status(_send_hold(cell, log=log))}
        safety_done = True
        for r in (*rows, hold_row):
            log(r)

    def _park_receipt(reply: dict) -> dict:
        return {**_ack_status(reply), **({"command": reply["command"]} if "command" in reply else {})}

    def _safe_park_or_hold(cmd_prefix: str = "", *, fault: bool = False, pre_logs: tuple[dict, ...] = ()) -> tuple[bool, dict | None]:
        nonlocal park_safe, hold_needed, safety_done
        if dry_run or (not fault and not moved and not hold_needed and (pre_home or authorize is not None)):
            for r in pre_logs:
                log(r)
            return False, None
        eff_prefix = cmd_prefix or loaded_prefix
        if fault or hold_needed or (authorize is not None and not eff_prefix):
            _hold_and_log(*pre_logs)
            return False, None
        try:
            park_reply = cell.act(eff_prefix + "park")
        except BaseException:
            park_safe, hold_needed = False, True
            safety_done = _best_effort_hold(cell, log=log) is not None
            raise
        park_row = {"command": "park", **_ack_status(park_reply)}
        if park_ack_ok(park_reply, require_command=True):
            safety_done = True
            for r in (*pre_logs, park_row):
                log(r)
            return True, park_reply
        _hold_and_log(*pre_logs, park_row)
        return False, park_reply

    def _fail(res: str, at: int, reason, cmd_prefix: str = "", *, fault: bool = False, extra: dict | None = None,
              pre_logs: tuple[dict, ...] = ()) -> dict:
        nonlocal aborted
        aborted = True
        parked_ok, park_reply = _safe_park_or_hold(cmd_prefix, fault=fault, pre_logs=pre_logs)
        return {"result": res, "at": at, "reason": reason, **(extra or {}), "parked": parked_ok,
                **({"park": _park_receipt(park_reply)} if park_reply is not None else {})}

    def _legacy_jaw_hold(row: dict, n: int, jaw_warn: str) -> dict:
        nonlocal aborted
        aborted = True
        _hold_and_log({**row, "refused": jaw_warn})
        return {"result": "refused", "at": n, "reason": jaw_warn, "parked": False}

    def _checked_state(row: dict, n: int, *, catch_io: bool = False, hold_on_fail: bool = False) -> tuple[dict | None, list | None, dict | None]:
        nonlocal hold_needed
        prev_hold = hold_needed
        if hold_on_fail and not dry_run:
            hold_needed = True
        try:
            status = cell.act("state")
        except Exception as error:
            if not catch_io:
                raise
            return None, None, _fail("refused", n, msg := str(error)[:200] or type(error).__name__, fault=hold_on_fail,
                                     pre_logs=({**row, "refused": msg},))
        ok, hold, err_msg = _valid_state(status)
        if not ok:
            fault = isinstance(status, dict) and bool(status.get("fault"))
            return None, None, _fail("fault" if fault else "refused", n, err_msg, fault=hold or hold_on_fail,
                                     pre_logs=({**row, "refused": err_msg, **(_ack_status(status) if isinstance(status, dict) else {})},))
        live = [status["state"], *([status["target"]] if status.get("target") is not None else [])]
        if jaw_spec is not None and (jaw_warn := jaw_zone_error(live, kin, jaw_spec)):
            row["jaw_warning"] = jaw_warn
            if not dry_run:
                return None, None, _legacy_jaw_hold(row, n, jaw_warn)
        hold_needed = prev_hold
        return status, live, None

    try:
        for n in range(max_chunks):
            row, aborted = {"chunk": n, "dry_run": dry_run}, False
            if n == 0 and pre_home and not dry_run:
                status, live_poses, err = _checked_state(row, n, catch_io=True, hold_on_fail=True)
                if err is not None:
                    return err
                status, pre_err = _pre_settle_home(cell, library, status, row, log, kin, jaw_spec)
                if pre_err is not None:
                    return pre_err
                live_poses = [status["state"], *([status["target"]] if status.get("target") is not None else [])]
            try:
                if not (n == 0 and pre_home and not dry_run):
                    status, live_poses, err = _checked_state(row, n, catch_io=not dry_run, hold_on_fail=not dry_run)
                    if err is not None:
                        return err
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
                        cam_now, frames[view], stamp = time.time(), rec["image"], rec.get("source_stamp")
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
                       "proposed_last": proposed[-1].tolist(), **({"converted_chunk": converted.tolist()} if dry_run else {})}
                force_all = jaw_spec is not None and in_jaw_zone(live_poses, kin, jaw_spec)
                try:
                    frames_cell = shape_chunk(proposed, state, low, high, fastest)
                except ValueError as error:
                    if dry_run:
                        row["envelope"] = {"ok": False, "reason": str(error)}
                    return _fail("refused", n, str(error), pre_logs=({**row, "refused": str(error)},))
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
                (path := work / f"policy-lib-{time.time_ns()}-{n}.json").write_text(json.dumps(lib), encoding="utf-8")
                prefix = ""
                if authorize is not None or (n == 0 and pre_home):
                    auth_status, auth_poses, auth_fail = _checked_state(row, n, catch_io=True, hold_on_fail=True)
                    if auth_fail is not None:
                        return auth_fail
                    if (not force_all and jaw_spec is not None and in_jaw_zone(auth_poses, kin, jaw_spec)
                            and (jaw_warn := jaw_zone_error(frames_cell, kin, jaw_spec, force_all=True))):
                        row["jaw_warning"] = jaw_warn
                        return _legacy_jaw_hold(row, n, jaw_warn)
                    if n == 0:
                        if not _empty_gripper_ok(auth_status, HOLD_CURRENT_LIMIT_MA, now=time.time()):
                            reason = "START_POSE_OFF_HOME: unconfirmed empty gripper"
                            aborted = True
                            _hold_and_log({**row, "refused": reason, **_ack_status(auth_status)})
                            return {"result": "refused", "at": n, "reason": reason, "parked": False}
                        if pre_home:
                            home_frames = (library.get("chunks") or {}).get("home") if isinstance(library, dict) else None
                            home = _pose6(home_frames[-1]) if isinstance(home_frames, (list, tuple)) and home_frames else None
                            auth_chk = _check_idle_sample(auth_status, home, check_home_target=True, target_tol=PRE_SETTLE_TOL) if home is not None else None
                            auth_pose = auth_chk[0] if auth_chk is not None else None
                            if (home is None or auth_pose is None or _max_diff(auth_pose, home, 5) > PRE_SETTLE_TOL
                                    or not _live_idle_ok(cell, auth_pose, home, check_home_target=True, target_tol=PRE_SETTLE_TOL)):
                                reason = "START_POSE_OFF_HOME: arm not stationary at home before dispatch"
                                aborted = True
                                _hold_and_log({**row, "refused": reason, **_ack_status(auth_status)})
                                return {"result": "refused", "at": n, "reason": reason, "parked": False}
                        elif (auth_status.get("jitter") or {}).get("shaking") or auth_status.get("chunk") is not None:
                            reason = "START_POSE_OFF_HOME: arm not idle before dispatch"
                            aborted = True
                            _hold_and_log({**row, "refused": reason, **_ack_status(auth_status)})
                            return {"result": "refused", "at": n, "reason": reason, "parked": False}
                    if authorize is not None:
                        try:
                            assessment = authorize(lib, auth_status, ("run policy", "park"))
                        except ValueError as error:
                            return _fail("refused", n, str(error), pre_logs=({**row, "refused": str(error)},))
                        prefix = f"checked {assessment['session_id']} {assessment['library_sha256']} "
                if oldest_stamp is not None and time.time() - oldest_stamp > max_obs_age_s:
                    return _fail("refused", n, "stale policy observation", pre_logs=({**row, "refused": "stale policy observation"},))
            except Exception as error:  # fail closed on camera, inference, shaping, or file errors after chunk 0
                if aborted:
                    raise
                msg = str(error)[:200] or type(error).__name__
                return _fail("refused", n, msg, pre_logs=({**row, "refused": msg},))
            park_safe, hold_needed = False, True
            loaded = cell.act(f"{prefix}load {path}")
            load_lost = isinstance(loaded, dict) and str(loaded.get("error") or "").startswith("no status within")
            load_fault = not isinstance(loaded, dict) or load_lost or any(loaded.get(k) for k in FAULT_KEYS)
            load_row = {**row, "command": "load", **(_ack_status(loaded) if isinstance(loaded, dict) else {})}
            if load_fault or loaded.get("ok") is not True:
                if not load_fault:
                    hold_needed = False
                reason = ((loaded.get("error") or loaded.get("fault")) if isinstance(loaded, dict) else None) or "policy load failed"
                return _fail("fault" if load_fault else "refused", n, reason, fault=load_fault, pre_logs=(load_row,))
            loaded_prefix, park_safe = prefix, moved
            log(load_row)
            if oldest_stamp is not None and time.time() - oldest_stamp > max_obs_age_s:
                return _fail("refused", n, "stale policy observation", prefix, pre_logs=({**row, "refused": "stale policy observation"},))
            moved, park_safe = True, False
            ran = cell.act(prefix + "run policy")
            if not isinstance(ran, dict):
                return _fail("fault", n, "unexpected policy reply command", prefix, fault=True, extra={"error": "unexpected policy reply command"})
            cmd = raw_cmd.split(" ", 3)[-1] if (raw_cmd := str(ran.get("command") or "")).startswith("checked ") else raw_cmd
            wrong_cmd = cmd != "run policy"
            hard_stop = bool(ran.get("hold") or ran.get("human_hold_latched") or wrong_cmd
                             or (ran.get("contact") and ran.get("settled") is False)
                             or (ran.get("fault") and not (ran.get("contact") and str(ran.get("fault")).startswith("contact"))))
            if hard_stop:
                reason = ran.get("error") or ran.get("fault") or ("unexpected policy reply command" if wrong_cmd else "policy playback fault")
                return _fail("fault", n, reason, prefix, fault=True, extra={"error": reason}, pre_logs=({"command": "run policy", **_ack_status(ran)},))
            if ran.get("contact"):
                err_txt = f"{ran.get('error') or ''} {ran.get('fault') or ''}"
                if "overload-hold" in err_txt or "release not confirmed" in err_txt or ran.get("holding") is True:
                    reason = ran.get("error") or ran.get("fault") or "contact while holding or release unconfirmed"
                    return _fail("contact", n, reason, prefix, fault=True, extra={"error": reason}, pre_logs=({"command": "run policy", **_ack_status(ran)},))
                retreat_reply = cell.act(prefix + "retreat")
                retreat_ok = retreat_ack_ok(retreat_reply)
                if retreat_ok:
                    hold_needed = False
                snap = _moved_snapshot(state, ran, frames.get("top"), cell, work, n) if retreat_ok else {}
                return _fail("contact", n, ran.get("error"), prefix, fault=not retreat_ok, extra={"error": ran.get("error")},
                             pre_logs=({"command": "run policy", **_ack_status(ran), **snap}, {"command": "retreat", **_ack_status(retreat_reply)}))
            unsettled = ran.get("settled") is not True
            if not ran.get("ok") or unsettled:
                reason = ran.get("error") or ("policy chunk did not settle" if unsettled else "policy playback refused")
                res_kind = "unsettled" if (ran.get("ok") and unsettled) else "refused"
                return _fail(res_kind, n, reason, prefix, fault=True, extra={"error": reason}, pre_logs=({"command": "run policy", **_ack_status(ran)},))
            park_safe, hold_needed = True, False
            log({"command": "run policy", **_ack_status(ran), **_moved_snapshot(state, ran, frames.get("top"), cell, work, n)})
            held = held or bool(ran.get("holding"))
            if released := (held and frames_cell[-1][5] > closed + 10.0):
                break
        if dry_run:
            return {"result": "dry_run", "chunks": max_chunks}
        parked_ok, park_reply = _safe_park_or_hold(prefix)
        return {"result": "released" if released else "chunks_done", "held": held, "parked": parked_ok,
                **({"park": _park_receipt(park_reply)} if park_reply is not None else {})}
    except BaseException as exc:
        if not dry_run and (moved or hold_needed or not isinstance(exc, Exception)) and not safety_done:
            try:
                if isinstance(exc, Exception) and park_safe and not hold_needed:
                    _safe_park_or_hold(loaded_prefix)
                else:
                    safety_done = _best_effort_hold(cell, log=log) is not None
            except BaseException:
                if not safety_done:
                    safety_done = _best_effort_hold(cell, log=log) is not None
        raise
