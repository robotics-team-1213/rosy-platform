"""Deterministic per-arm and situational recovery path planning for D-1048 auto-fold."""
from __future__ import annotations

import json
import math
import time
from pathlib import Path

STEP_MAX = 5.0  # matches chunk_runner_guards.JOG_MAX (never emit a single jog > 5.0)
MIN_SITE_AREA_PX = 2500.0  # anti-sliver threshold before expanding high-transit hull across sites/base
NAMES = ("shoulder_pan.pos", "shoulder_lift.pos", "elbow_flex.pos", "wrist_flex.pos", "wrist_roll.pos", "gripper.pos")
_FAULT_KEYS = ("fault", "contact", "hold", "human_hold_latched")


def chunk_jog_commands(joint_name: str, total_delta: float, step_max: float = STEP_MAX) -> list[str]:
    """Split a joint jog delta into bounded `jog <joint> <delta>` steps with |step| <= step_max."""
    total = round(float(total_delta), 2)
    if abs(total) < 1e-6:
        return []
    cap = float(step_max)
    if abs(total) <= cap:
        return [f"jog {joint_name} {total}"]
    count = math.ceil(abs(total) / cap)
    base = math.copysign(math.floor(abs(total) / count * 100.0) / 100.0, total)
    rem_cents = round((total - base * count) * 100.0)
    sign_cent = 1 if rem_cents >= 0 else -1
    out: list[str] = []
    for i in range(count):
        step = round(base + (0.01 * sign_cent if i < abs(rem_cents) else 0.0), 2)
        if abs(step) > cap + 1e-6:
            raise ValueError(f"{joint_name} chunk step {step} exceeds {cap}")
        out.append(f"jog {joint_name} {step}")
    return out


def interpolate_pose(start: list[float], end: list[float], max_step: float = 1.0) -> list[list[float]]:
    """Return dense linear frames from `start` (excluded) to `end` (included) for corridor checks."""
    diff = max(abs(float(b) - float(a)) for a, b in zip(start[:6], end[:6]))
    steps = max(1, math.ceil(diff / max(float(max_step), 1e-3)))
    return [[round(float(a) + (float(b) - float(a)) * i / steps, 4) for a, b in zip(start[:6], end[:6])]
            for i in range(1, steps + 1)]


def joint_bounds(config: dict | None) -> list[tuple[float, float]] | None:
    """Return 6-joint (lo, hi) bounds from cell config, or None when no window is configured."""
    if not isinstance(config, dict):
        return None
    lo_map = config.get("joint_min") or {}
    hi_map = config.get("joint_max") or {}
    if not isinstance(lo_map, dict) or not isinstance(hi_map, dict):
        return None
    if not lo_map and not hi_map:
        return None
    bounds = []
    for name in NAMES:
        lo = max(-100.0, float(lo_map.get(name, -100.0)))
        hi = min(100.0, float(hi_map.get(name, 100.0)))
        if lo > hi:
            raise ValueError(f"invalid joint bounds for {name}: {lo}..{hi}")
        bounds.append((lo, hi))
    return bounds


def frames_within_bounds(frames, bounds, start=None) -> tuple[bool, str | None]:
    """Verify every frame respects bounds, allowing strictly inward return if start began outside."""
    if bounds is None:
        return True, None
    for idx, frame in enumerate(frames):
        for axis, (lo, hi) in enumerate(bounds[:min(len(frame), len(bounds))]):
            val = float(frame[axis])
            if not math.isfinite(val):
                return False, f"frame {idx} {NAMES[axis]} not finite"
            if lo - 1e-6 <= val <= hi + 1e-6:
                continue
            if start is not None:
                s0 = float(start[axis])
                prev = float(frames[idx - 1][axis]) if idx > 0 else s0
                if s0 < lo and s0 - 1e-6 <= val <= hi + 1e-6 and val >= prev - 1e-6:
                    continue
                if s0 > hi and lo - 1e-6 <= val <= s0 + 1e-6 and val <= prev + 1e-6:
                    continue
            return False, f"frame {idx} {NAMES[axis]}={val:.2f} outside {lo:.1f}..{hi:.1f}"
    return True, None


def fk_z(pose, tcp_x_m: float | None = None) -> float:
    """Forward-kinematic TCP height in metres using calibrated jaw tcp_x_m."""
    import cell_pivot

    return float(cell_pivot.joints_tcp(pose, tcp_x_m=tcp_x_m)[2])


def _step_toward_z(cur: list[float], axis: int, step_dir: float, clear_z_m: float,
                   bounds, tcp_x_m: float | None, max_steps: int) -> tuple[float, list[list[float]], float]:
    """Walk one strong joint strictly increasing FK-z within joint bounds."""
    lo, hi = bounds[axis] if bounds is not None else (-100.0, 100.0)
    z_now = fk_z(cur, tcp_x_m=tcp_x_m)
    start_val, frames = cur[axis], []
    for _ in range(max_steps):
        if z_now >= clear_z_m:
            break
        nxt = round(cur[axis] + step_dir, 2)
        if nxt < lo - 1e-6 and nxt < start_val:
            break
        if nxt > hi + 1e-6 and nxt > start_val:
            break
        cand = list(cur)
        cand[axis] = nxt
        z_nxt = fk_z(cand, tcp_x_m=tcp_x_m)
        if z_nxt <= z_now + 1e-5:
            break
        cur[axis], z_now = nxt, z_nxt
        frames.append(list(cur))
    return round(cur[axis] - start_val, 2), frames, z_now


def _best_z_dir(cur: list[float], axis: int, z_now: float, bounds, tcp_x_m: float | None, prefer: float | None = None) -> float | None:
    lo, hi = bounds[axis] if bounds is not None else (-100.0, 100.0)
    opts: list[tuple[float, float]] = []
    for d in (-1.0, 1.0):
        nxt = cur[axis] + d
        if (nxt < lo - 1e-6 and nxt < cur[axis]) or (nxt > hi + 1e-6 and nxt > cur[axis]):
            continue
        probe = list(cur)
        probe[axis] = nxt
        dz = fk_z(probe, tcp_x_m=tcp_x_m) - z_now
        if dz > 1e-5:
            opts.append((dz, d))
    if not opts:
        return None
    if len(opts) == 2 and prefer is not None and abs(opts[0][0] - opts[1][0]) < 1e-4:
        return -1.0 if prefer <= cur[axis] else 1.0
    return max(opts, key=lambda item: item[0])[1]


def unwedge_pull_dips(state: list[float], target: list[float], home: list[float], size: float,
                      clear_z_m: float, tcp_x_m: float | None = None) -> bool:
    """Return True if an elbow_flex pull would dip TCP z below clear_z_m while lift can still rise."""
    z_now = fk_z(state, tcp_x_m=tcp_x_m)
    if z_now >= clear_z_m or (home[1] - target[1]) * (home[1] - state[1]) <= 0:
        return False
    probe = list(state)
    probe[2] += max(-size, min(size, home[2] - target[2]))
    return fk_z(probe, tcp_x_m=tcp_x_m) < z_now - 0.001


def _norm_arm(val) -> str | None:
    if not isinstance(val, str):
        return None
    if val in ("arm_a", "arm_b", "arm_s"):
        return val
    return val[:-9] if val.endswith("_follower") and val[:-9] in ("arm_a", "arm_b", "arm_s") else None


def _session_arm(sess: dict) -> tuple[str | None, bool]:
    prof = sess.get("operating_profile")
    chunks_io = (sess.get("chunks") or {}).get("io") if isinstance(sess.get("chunks"), dict) else None
    io_name = Path(chunks_io).name if isinstance(chunks_io, str) and chunks_io else ""
    io_arm = f"arm_{io_name[9:]}" if io_name.startswith("chunk-io-") and io_name[9:] in ("a", "b", "s") else None
    raws = (sess.get("arm"), prof.get("device_id") if isinstance(prof, dict) else None,
            prof.get("instance_id") if isinstance(prof, dict) else None, sess.get("motor_health_owner"))
    found = {a for v in raws if (a := _norm_arm(v)) is not None} | ({io_arm} if io_arm else set())
    if any(isinstance(v, str) and v and _norm_arm(v) is None for v in raws[:2]) or len(found) > 1:
        return "__conflict__", True
    real_rec = any(k in sess for k in ("arm", "operating_profile", "motor_health_owner", "chunks", "config"))
    return (next(iter(found)), True) if found else (None, real_rec)


def wait_session_json(session: Path, arm: str, started: float, sleep) -> tuple[dict | None, str | None]:
    """Poll `session.json` until a fresh matching-arm recovery session finishes and writes torque_after."""
    for _ in range(36):
        if session.is_file() and session.stat().st_mtime >= started - 2.0:
            try:
                sess = json.loads(session.read_text())
            except (OSError, ValueError):
                sess = None
            if isinstance(sess, dict):
                sess_arm, real_rec = _session_arm(sess)
                if sess_arm == arm or (not real_rec and sess_arm is None and "torque_after" in sess):
                    return sess, None
        sleep(5)
    return None, "the recovery session did not report its end (no fresh session.json)"


def fk_lift_plan(start: list[float], *, lift_units: float = 20.0, clear_z_m: float = 0.10,
                 bounds=None, tcp_x_m: float | None = None, home=None) -> tuple[list[str], list[list[float]], list[float]] | None:
    """Build an open-jaw vertical FK-z lift sequence using strong joints before any horizontal turn."""
    cur = [float(v) for v in start[:6]]
    z0 = fk_z(cur, tcp_x_m=tcp_x_m)
    if z0 >= clear_z_m:
        return None
    budget = min(20, max(1, int(round(lift_units))))
    frames, cmds, used = [list(cur)], [], 0
    for axis, name in ((1, "shoulder_lift.pos"), (2, "elbow_flex.pos")):
        if used >= budget or fk_z(cur, tcp_x_m=tcp_x_m) >= clear_z_m:
            break
        pref = float(home[axis]) if home is not None else None
        sdir = _best_z_dir(cur, axis, fk_z(cur, tcp_x_m=tcp_x_m), bounds, tcp_x_m, prefer=pref)
        if sdir is None:
            continue
        delta, seg, _ = _step_toward_z(cur, axis, sdir, clear_z_m, bounds, tcp_x_m, budget - used)
        if abs(delta) >= 1e-6:
            cmds.extend(chunk_jog_commands(name, delta, step_max=2.0 if axis == 1 else STEP_MAX))
            frames.extend(seg)
            used += len(seg)
    if not cmds or fk_z(cur, tcp_x_m=tcp_x_m) < clear_z_m:
        return None
    return cmds, frames, cur


def classify_situation(state: list[float], target: list[float], home: list[float], closed: float, *,
                       low_ok: bool, is_holding: bool, open_margin: float = 4.0) -> str:
    """Classify the arm recovery situation cleanly before candidate generation."""
    if is_holding and not low_ok:
        return "holding_high"
    if is_holding and low_ok:
        return "holding_low"
    if not is_holding and low_ok and float(state[5]) > float(closed) + open_margin:
        return "low_open_jaws"
    if all(abs(float(a) - float(b)) <= 10.0 for a, b in zip(state[:4], home[:4])) and abs(float(state[4]) - float(home[4])) > 10.0:
        return "folded_off_roll"
    return "extended"


def build_candidates(state: list[float], home: list[float], closed: float, plan, *, bounds=None,
                     tcp_x_m: float | None = None, clear_z_m: float = 0.10, situation: str = "extended",
                     extended: bool = False) -> list[tuple[str, list[str], list[list[float]]]]:
    """Generate guarded (name, jog_commands, swept_frames) candidates for tier-1 recovery."""
    cur = [float(v) for v in state[:6]]
    if not extended:
        out: list[tuple[str, list[str], list[list[float]]]] = [("park", [], list(plan(cur)))]
        for d in (5.0, -5.0, 10.0, -10.0):
            moved = [cur[0] + d, *cur[1:]]
            cmds = chunk_jog_commands("shoulder_pan.pos", d)
            segs = [moved] if abs(d) <= STEP_MAX else interpolate_pose(cur, moved, max_step=STEP_MAX)
            frames = [list(cur), *segs, *plan(moved)]
            out.append((f"pan{d:+g}", cmds, frames))
        return out

    raw: list[tuple[str, list[str], list[list[float]]]] = []
    lift = fk_lift_plan(cur, clear_z_m=clear_z_m + 0.015, bounds=bounds, tcp_x_m=tcp_x_m, home=home)
    if lift is None:
        lift = fk_lift_plan(cur, clear_z_m=clear_z_m, bounds=bounds, tcp_x_m=tcp_x_m, home=home)

    def add_lift_variants():
        if lift is None:
            return
        l_cmds, l_frames, l_pose = lift
        raw.append(("lift_then_park", list(l_cmds), [list(cur), *l_frames[1:], *plan(l_pose)]))
        for d in (10.0, -10.0):
            p_pose = [l_pose[0] + d, *l_pose[1:]]
            cmds = [*l_cmds, *chunk_jog_commands("shoulder_pan.pos", d)]
            frames = [list(cur), *l_frames[1:], *interpolate_pose(l_pose, p_pose, max_step=STEP_MAX), *plan(p_pose)]
            raw.append((f"lift_pan{d:+g}", cmds, frames))

    if situation == "low_open_jaws":
        add_lift_variants()
        raw.append(("park", [], list(plan(cur))))
    else:
        raw.append(("park", [], list(plan(cur))))
        add_lift_variants()

    for d in (5.0, -5.0, 10.0, -10.0, 15.0, -15.0):
        moved = [cur[0] + d, *cur[1:]]
        segs = [moved] if abs(d) <= STEP_MAX else interpolate_pose(cur, moved, max_step=STEP_MAX)
        raw.append((f"pan{d:+g}", chunk_jog_commands("shoulder_pan.pos", d), [list(cur), *segs, *plan(moved)]))

    if abs(d_in := max(-20.0, min(20.0, float(home[2]) - cur[2]))) > 10.0:  # forearm in first: a shorter lever on shoulder_lift (D-1079)
        e_pose = [cur[0], cur[1], cur[2] + d_in, *cur[3:]]
        raw.insert(1, ("elbow_in_then_park", chunk_jog_commands("elbow_flex.pos", d_in), [list(cur), *interpolate_pose(cur, e_pose, max_step=STEP_MAX), *plan(e_pose)]))
    if abs(float(home[4]) - cur[4]) > 10.0 or cur[2] >= -35.0:
        elbow_pose = [cur[0], cur[1], cur[2] - 10.0, *cur[3:]]
        cmds = chunk_jog_commands("elbow_flex.pos", -10.0)
        raw.append(("elbow_clear_then_park", cmds, [list(cur), *interpolate_pose(cur, elbow_pose, max_step=STEP_MAX), *plan(elbow_pose)]))

    if bounds is None:
        return raw
    filtered: list[tuple[str, list[str], list[list[float]]]] = []
    for cand in raw:
        ok, _ = frames_within_bounds(cand[2], bounds, start=cur)
        if ok:
            filtered.append(cand)
    return filtered or ([("park", [], list(plan(cur)))] if frames_within_bounds(plan(cur), bounds, start=cur)[0] else [])


def extended_candidate_names() -> list[str]:
    """Return every tier-1 candidate name that `build_candidates(..., extended=True)` may produce."""
    return ["park", "lift_then_park", "lift_pan+10", "lift_pan-10",
            "pan+5", "pan-5", "pan+10", "pan-10", "pan+15", "pan-15", "elbow_clear_then_park", "elbow_in_then_park"]


def run_detour_jogs(cell, commands: list[str], *, settle_tol: float = 3.0, settle_polls: int = 15,
                    sleep=time.sleep) -> tuple[bool, str | None, dict | None]:
    """Execute chunked detour jogs sequentially, polling settle between multi-step commands."""
    last_ack = None
    for idx, command in enumerate(commands):
        ack = cell.act(command)
        last_ack = ack if isinstance(ack, dict) else {"ok": False}
        if last_ack.get("ok") is not True or any(last_ack.get(k) for k in _FAULT_KEYS):
            return False, "DETOUR_REFUSED", last_ack
        if len(commands) > 1 and idx + 1 < len(commands):
            for _ in range(settle_polls):
                st = cell.act("state")
                last_ack = st if isinstance(st, dict) else {"ok": False}
                if last_ack.get("ok") is not True or any(last_ack.get(k) for k in _FAULT_KEYS):
                    return False, "DETOUR_REFUSED", last_ack
                s_vals, t_vals = last_ack.get("state"), last_ack.get("target")
                if (isinstance(s_vals, list) and len(s_vals) >= 5 and isinstance(t_vals, list) and len(t_vals) >= 5
                        and max(abs(float(t) - float(s)) for t, s in zip(t_vals[:5], s_vals[:5])) <= settle_tol):
                    break
                sleep(0.2)
            else:
                return False, "DETOUR_NOT_SETTLED", last_ack
    return True, None, last_ack


def make_load_checker(config: dict, library: dict, params: dict | None = None):
    """The optional `load_predict.check_chunk` gate, or None; a recovery no person started (D-1079) refuses unknown/unchecked load."""
    refuse = not __import__("os").environ.get("ROSY_JOB_PRINCIPAL", "").startswith("human:")
    _UNCHECKED = lambda frames: {"ok": False, "verdict": "unknown", "report": {"why": "no load model: an automatic recovery refuses it"}}  # noqa: E731
    lm_path = config.get("load_model_path")
    port = config.get("port") or (config.get("follower") or {}).get("port") or (config.get("robot") or {}).get("port")
    if not port and config.get("record_config_path"):
        try:
            rcfg = json.loads(Path(str(config["record_config_path"])).expanduser().read_text(encoding="utf-8"))
            port = rcfg.get("port") or (rcfg.get("robot") or {}).get("port")
        except (OSError, ValueError):
            port = None
    if not lm_path or not port:
        return _UNCHECKED if refuse else None
    import cell_params as prm
    import load_predict

    model = load_predict.load(Path(str(lm_path)).expanduser())
    arm = model["arms"].get(load_predict.arm_for(model, port))
    if arm is None:
        return _UNCHECKED if refuse else None
    fps = int(library.get("fps", 30))
    caps = config.get("caps")
    refuse_unknown = refuse or bool(prm.get(params, "loadcheck.refuse_unknown"))

    def check_frames(frames) -> dict:
        rep = load_predict.check_chunk(arm, frames, fps, params, caps)
        verdict = rep["verdict"]
        ok = verdict != "risky" and not (verdict == "unknown" and refuse_unknown)
        return {"ok": ok, "verdict": verdict, "report": rep}

    return check_frames


def build_multi_site_look(
    cell, config: dict, calibration: dict, primary_site: str, roi, params, to_px, tcp_x_m: float | None,
    *, allow_ascending_departure: bool = False, own_state=None,
):
    """Build a corridor look(frames) checker combining calibrated site surfaces for multi-site high transit.
    `own_state` (the fold only): a call that returns the arm's measured joints, whose links are then no obstacle."""
    import numpy as np

    import cell_corridor
    import cell_corridor_own
    import cell_objects
    import cell_pivot

    sites = config.get("sites") or {}
    primary = sites.get(primary_site) if isinstance(sites, dict) else None
    polys = cell_corridor.calibrated_surface_polygons(config, primary_site)
    valid_sites, _ = cell_corridor.valid_surface_sites(sites if isinstance(sites, dict) else None)

    def look(frames):
        img = cell.frame("top")
        pts = [cell_pivot.joints_tcp(f, tcp_x_m=tcp_x_m)[:3] for f in frames]
        if not isinstance(img, np.ndarray) or len(polys) <= 1:
            fb_site = primary if isinstance(primary, dict) else {}
            mask = cell_objects.foreground(img, roi, params=params, surface_px=fb_site.get("surface_px"), surface_lab=fb_site.get("surface_lab"))
            return cell_corridor.check(pts, mask, roi, to_px, params=params, surface_px=fb_site.get("surface_px"))

        import cv2

        low_mask, _ = cell_corridor.site_foreground_mask(img, sites, roi, params)
        area_px = sum(float(cv2.contourArea(np.asarray(s["surface_px"], np.int32).reshape(-1, 2))) for s in valid_sites)
        base_px = to_px((0.0, 0.0))
        extra = [base_px] if (base_px is not None and area_px >= MIN_SITE_AREA_PX) else None
        high_hull = cell_corridor.transit_hull_polygon(polys, extra_pts=extra) if area_px >= MIN_SITE_AREA_PX else None
        mask = low_mask
        if high_hull:
            seen_low = cell_corridor._fill_surfaces(low_mask.shape, roi, polys) > 0
            gap = (cell_corridor._fill_surfaces(low_mask.shape, roi, high_hull) > 0) & ~seen_low
            if gap.any():
                bound = calibration if own_state is not None else None  # other callers keep the colour rule
                mask = low_mask | cell_corridor_own.gap_foreground(config, bound, img, roi, gap, params)
        own = (cell_corridor_own.own_mask(config, primary_site, to_px, (own_state(),), low_mask.shape, roi, tcp_x_m)
               if own_state is not None else None)
        return cell_corridor.check(
            pts, mask, roi, to_px, params=params, surface_px=polys,
            high_surface_px=high_hull, allow_ascending_departure=allow_ascending_departure, own=own,
        )

    return look
