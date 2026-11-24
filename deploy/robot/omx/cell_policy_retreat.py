"""Jaw-zone retreat trajectory planning and execution before paced policy park."""
from __future__ import annotations

import json
import time
from pathlib import Path

from cell_policy_entry import FAULT_KEYS, ack_status, pose6, valid_state


def _strip_checked(command) -> str:
    raw = str(command or "").strip()
    if raw.startswith("checked "):
        parts = raw.split(" ", 3)
        return parts[3] if len(parts) == 4 else raw
    return raw


def _pick_lift_dir(pose: list[float], low, high, kin, home_pose) -> float:
    """Pick shoulder_lift unit step direction that raises TCP z within joint bounds."""
    from grasp_planner import norm_to_rad

    lift_lo, lift_hi = float(low[1]), float(high[1])
    base_z = float(kin.fk([norm_to_rad(float(v)) for v in pose[:5]]).z)
    best_neg, best_pos = 0.0, 0.0
    for mag in (1.0, 5.0, 15.0, 25.0):
        neg = max(lift_lo, pose[1] - mag)
        pos = min(lift_hi, pose[1] + mag)
        if neg < pose[1]:
            best_neg = max(best_neg, float(kin.fk([norm_to_rad(float(v)) for v in (pose[0], neg, pose[2], pose[3], pose[4])]).z) - base_z)
        if pos > pose[1]:
            best_pos = max(best_pos, float(kin.fk([norm_to_rad(float(v)) for v in (pose[0], pos, pose[2], pose[3], pose[4])]).z) - base_z)
    if best_neg > 1e-4 or best_pos > 1e-4:
        return -1.0 if best_neg >= best_pos else 1.0
    if home_pose is not None:
        return -1.0 if float(home_pose[1]) <= pose[1] else 1.0
    return -1.0


def retreat_from_jaw_zone_frames(
    cur_pose,
    open_g: float,
    low,
    high,
    fastest: float,
    kin,
    jaw_spec: dict,
    *,
    home_pose=None,
    home_roll: float | None = None,
    clear_margin_m: float = 0.025,
    max_steps: int = 24,
) -> list[list[float]]:
    """Build an envelope-safe open-jaws-then-lift trajectory clearing the source grasp ceiling."""
    from cell_policy_shape import jaw_zone_error, shape_chunk, wrist_roll_warning
    from grasp_planner import norm_to_rad

    pose = pose6(cur_pose)
    if pose is None:
        raise ValueError("retreat requires finite 6-joint pose")
    retreat_grip = min(float(high[5]), max(float(pose[5]), float(open_g)))
    wp = [pose[0], pose[1], pose[2], pose[3], pose[4], retreat_grip]
    waypoints = [wp]
    lift_lo, lift_hi = float(low[1]), float(high[1])
    wrist_lo, wrist_hi = float(low[3]), float(high[3])
    step_dir = _pick_lift_dir(pose, low, high, kin, home_pose)
    clear_z = float(jaw_spec["z_m"]) + float(clear_margin_m)
    min_clear_z = float(jaw_spec["z_m"]) + min(float(clear_margin_m), 0.015)
    cur_lift, cur_wrist = wp[1], wp[3]
    prev_z = float(kin.fk([norm_to_rad(float(v)) for v in wp[:5]]).z)
    for _ in range(max_steps):
        next_lift = min(lift_hi, max(lift_lo, cur_lift + step_dir))
        if next_lift == cur_lift:
            break
        cur_lift = next_lift
        raw_wp = [pose[0], cur_lift, pose[2], cur_wrist, pose[4], retreat_grip]
        fk_raw = kin.fk([norm_to_rad(float(v)) for v in raw_wp[:5]])
        comp_wrist = min(wrist_hi, max(wrist_lo, cur_wrist - step_dir))
        chosen_wp, chosen_fk = raw_wp, fk_raw
        if comp_wrist != cur_wrist:
            comp_wp = [pose[0], cur_lift, pose[2], comp_wrist, pose[4], retreat_grip]
            fk_comp = kin.fk([norm_to_rad(float(v)) for v in comp_wp[:5]])
            if (float(fk_comp.tool_down_error_rad) <= float(fk_raw.tool_down_error_rad) + 1e-6
                    and float(fk_comp.z) >= prev_z - 1e-4):
                chosen_wp, chosen_fk = comp_wp, fk_comp
                cur_wrist = comp_wrist
        waypoints.append(chosen_wp)
        prev_z = float(chosen_fk.z)
        if prev_z > clear_z:
            break
    if float(kin.fk([norm_to_rad(float(v)) for v in waypoints[-1][:5]]).z) <= min_clear_z:
        raise ValueError("jaw-zone retreat could not clear source grasp ceiling")
    frames = shape_chunk(waypoints, pose, low, high, fastest)
    if jw := jaw_zone_error(frames, kin, jaw_spec, force_all=False):
        raise ValueError(jw)
    if home_roll is not None and (rw := wrist_roll_warning(frames, home_roll, roll_range=(low[4], high[4]))):
        raise ValueError(rw)
    return frames


def retreat_from_jaw_zone(
    cell,
    library: dict,
    work: Path,
    *,
    cmd_prefix: str,
    open_g: float,
    low,
    high,
    fastest: float,
    kin,
    jaw_spec: dict,
    resolved_tcp,
    authorize,
    home_roll: float | None = None,
) -> tuple[bool, str, dict | None]:
    """Open jaws in place and lift clear of the source grasp zone before park; fail closed if blocked."""
    from cell_policy_shape import in_jaw_zone

    try:
        status = cell.act("state")
    except Exception as error:
        return False, cmd_prefix, {"command": "retreat_jaw_zone", "ok": False, "error": str(error)[:200] or type(error).__name__}
    ok, hold, err_msg = valid_state(status)
    if not ok or hold:
        return False, cmd_prefix, {
            "command": "retreat_jaw_zone", "stage": "state", "error": err_msg or "invalid state",
            **(ack_status(status) if isinstance(status, dict) else {}), "ok": False,
        }
    cur_pose = [float(v) for v in status["state"]]
    live_poses = [cur_pose, *([status["target"]] if status.get("target") is not None else [])]
    if not in_jaw_zone(live_poses, kin, jaw_spec):
        return True, cmd_prefix, None
    home_frames = (library.get("chunks") or {}).get("home") if isinstance(library, dict) else None
    home_pose = pose6(home_frames[-1]) if isinstance(home_frames, (list, tuple)) and home_frames else None
    try:
        frames = retreat_from_jaw_zone_frames(cur_pose, open_g, low, high, fastest, kin, jaw_spec,
                                              home_pose=home_pose, home_roll=home_roll)
    except ValueError as error:
        return False, cmd_prefix, {"command": "retreat_jaw_zone", "error": str(error), **ack_status(status), "ok": False}
    retreat_lib = {
        **{k: v for k, v in library.items() if k != "policy_playback"},
        "chunks": {**library["chunks"], "policy": frames},
        "jaw_gate": {**jaw_spec, "tcp_x_m": resolved_tcp},
    }
    path = work / f"policy-retreat-{time.time_ns()}.json"
    path.write_text(json.dumps(retreat_lib), encoding="utf-8")
    eff_prefix = cmd_prefix
    if authorize is not None:
        auth_kw = {"check_home": False} if getattr(authorize, "supports_check_home", False) else {}
        try:
            assessment = authorize(retreat_lib, status, ("run policy", "park"), **auth_kw)
        except ValueError as error:
            return False, eff_prefix, {"command": "retreat_jaw_zone", "stage": "authorize", "error": str(error), **ack_status(status), "ok": False}
        eff_prefix = f"checked {assessment['session_id']} {assessment['library_sha256']} "
    loaded = cell.act(f"{eff_prefix}load {path}")
    load_cmd_bad = isinstance(loaded, dict) and "command" in loaded and _strip_checked(loaded.get("command")) != f"load {path}"
    if not isinstance(loaded, dict) or loaded.get("ok") is not True or any(loaded.get(k) for k in FAULT_KEYS) or load_cmd_bad:
        return False, eff_prefix, {
            "command": "retreat_jaw_zone", "stage": "load",
            **(ack_status(loaded) if isinstance(loaded, dict) else {}),
            **({"error": "unexpected load reply command"} if load_cmd_bad and not (loaded or {}).get("error") else {}),
            "ok": False,
        }
    ran = cell.act(f"{eff_prefix}run policy")
    run_cmd_bad = isinstance(ran, dict) and _strip_checked(ran.get("command")) != "run policy"
    if (not isinstance(ran, dict) or ran.get("ok") is not True or ran.get("settled") is not True
            or any(ran.get(k) for k in FAULT_KEYS) or run_cmd_bad):
        return False, eff_prefix, {
            "command": "retreat_jaw_zone", "stage": "run policy",
            **(ack_status(ran) if isinstance(ran, dict) else {}),
            **({"error": "unexpected policy reply command"} if run_cmd_bad and not (ran or {}).get("error") else {}),
            "ok": False,
        }
    post_pose = pose6(ran.get("state"))
    post_target = pose6(ran.get("target"))
    if post_pose is None:
        post_st = cell.act("state")
        if isinstance(post_st, dict) and post_st.get("ok") is True and not any(post_st.get(k) for k in FAULT_KEYS):
            post_pose = pose6(post_st.get("state"))
            post_target = post_target or pose6(post_st.get("target"))
    post_poses = [p for p in (post_pose, post_target) if p is not None]
    if post_pose is None or in_jaw_zone(post_poses, kin, jaw_spec):
        return False, eff_prefix, {
            "command": "retreat_jaw_zone", "stage": "post_check",
            **ack_status(ran), "ok": False, "error": "retreat settled inside source grasp zone",
        }
    return True, eff_prefix, {"command": "retreat_jaw_zone", "frames": len(frames), **ack_status(ran)}
