"""Optional AI-PC vision recovery advisor with deterministic OMX numeric translation and hard vetoes."""
from __future__ import annotations

import base64
import json
import math
import time
from typing import Any

from cell_control_core import norm_to_rad, rad_to_norm
from cell_recovery_plan import chunk_jog_commands, fk_z, frames_within_bounds, interpolate_pose

SCHEMA = "rosy.omx-recovery-proposal.v1"
STRATEGIES = ("lift_then_park", "pan_then_park", "lift_pan_then_park", "retract_elbow_then_park", "escalate_human")
PROPOSAL_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["strategy", "lift_mm", "elbow_retract_deg", "pan_detour_deg", "open_jaws", "confidence", "reason"],
    "properties": {
        "strategy": {"type": "string", "enum": list(STRATEGIES)},
        "lift_mm": {"type": "number", "minimum": 0.0, "maximum": 150.0},
        "elbow_retract_deg": {"type": "number", "minimum": -30.0, "maximum": 30.0},
        "pan_detour_deg": {"type": "number", "minimum": -45.0, "maximum": 45.0},
        "open_jaws": {"type": "boolean"},
        "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "reason": {"type": "string", "minLength": 1, "maxLength": 240},
    },
}
DEFAULT_VIEWS = ("top", "side", "wrist")
MAX_TIMEOUT_S = 15.0


def _finite_num(raw, lo: float, hi: float) -> float | None:
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None
    val = float(raw)
    return val if math.isfinite(val) and lo <= val <= hi else None


def validate_proposal(raw: Any, *, holding: bool, low: bool, min_confidence: float = 0.70) -> tuple[dict | None, str | None]:
    """Enforce D-878 strict schema bounds and hard safety vetoes on an AI-PC recovery proposal."""
    if not isinstance(raw, dict):
        return None, "INVALID_TYPE"
    expected = set(PROPOSAL_SCHEMA["required"])
    if set(raw.keys()) != expected:
        return None, "SCHEMA_KEYS_MISMATCH"
    strategy = raw.get("strategy")
    if not isinstance(strategy, str) or strategy not in STRATEGIES:
        return None, "INVALID_STRATEGY"
    lift_mm = _finite_num(raw.get("lift_mm"), 0.0, 150.0)
    elbow_deg = _finite_num(raw.get("elbow_retract_deg"), -30.0, 30.0)
    pan_deg = _finite_num(raw.get("pan_detour_deg"), -45.0, 45.0)
    conf = _finite_num(raw.get("confidence"), 0.0, 1.0)
    open_jaws = raw.get("open_jaws")
    reason = raw.get("reason")
    if None in (lift_mm, elbow_deg, pan_deg, conf) or not isinstance(open_jaws, bool) or not isinstance(reason, str) or not (1 <= len(reason.strip()) <= 240):
        return None, "SCHEMA_VALUE_OUT_OF_RANGE"
    clean = {
        "strategy": strategy, "lift_mm": lift_mm, "elbow_retract_deg": elbow_deg,
        "pan_detour_deg": pan_deg, "open_jaws": open_jaws, "confidence": conf, "reason": reason.strip(),
    }
    if open_jaws and holding and not low:
        return None, "VETO_HOLDING_HIGH"
    if open_jaws and not low:
        return None, "VETO_OPEN_JAWS_FORBIDDEN"
    if open_jaws:
        return None, "OPEN_JAWS_UNSUPPORTED"
    if strategy == "escalate_human":
        return None, "escalate_human"
    if conf < float(min_confidence):
        return None, "LOW_CONFIDENCE"
    if low and strategy == "pan_then_park" and lift_mm <= 0.0:
        return None, "VETO_PAN_WHILE_LOW"
    if (strategy in ("lift_then_park", "lift_pan_then_park") and lift_mm <= 0.0) or (strategy == "lift_then_park" and abs(pan_deg) > 1e-6):
        return None, "STRATEGY_PARAM_MISMATCH"
    if (strategy in ("pan_then_park", "lift_pan_then_park") and abs(pan_deg) < 1.0) or (strategy == "retract_elbow_then_park" and abs(elbow_deg) < 1.0):
        return None, "STRATEGY_PARAM_MISMATCH"
    return clean, None


def _lift_axis_delta(cur: list[float], lift_mm: float, kin, bounds) -> tuple[float, float, str, int]:
    """Step shoulder_lift (fallback elbow_flex if needed) strictly raising canonical URDF FK-z."""
    z0 = float(kin.fk([norm_to_rad(v) for v in cur[:5]]).z)
    z_goal = z0 + float(lift_mm) / 1000.0
    for axis, name in ((1, "shoulder_lift.pos"), (2, "elbow_flex.pos")):
        lo, hi = bounds[axis] if bounds is not None else (-100.0, 100.0)
        best_dir, best_dz = 0.0, 0.0
        for d in (-1.0, 1.0):
            nxt = cur[axis] + d
            if (nxt < lo - 1e-6 and nxt < cur[axis]) or (nxt > hi + 1e-6 and nxt > cur[axis]):
                continue
            p = list(cur)
            p[axis] = nxt
            dz = float(kin.fk([norm_to_rad(v) for v in p[:5]]).z) - z0
            if dz > best_dz:
                best_dir, best_dz = d, dz
        if best_dir == 0.0:
            continue
        start_val = cur[axis]
        z_cur = float(kin.fk([norm_to_rad(v) for v in cur[:5]]).z)
        for _ in range(20):
            if z_cur >= z_goal:
                break
            nxt = round(cur[axis] + best_dir, 2)
            if (nxt < lo - 1e-6 and nxt < start_val) or (nxt > hi + 1e-6 and nxt > start_val):
                break
            p = list(cur)
            p[axis] = nxt
            z_nxt = float(kin.fk([norm_to_rad(v) for v in p[:5]]).z)
            if z_nxt <= z_cur + 1e-5:
                break
            cur[axis], z_cur = nxt, z_nxt
        if z_cur > z0 + 1e-4:
            return round(cur[axis] - start_val, 2), (z_cur - z0) * 1000.0, name, axis
    return 0.0, 0.0, "shoulder_lift.pos", 1


def translate_proposal(
    proposal: dict,
    state: list[float],
    target: list[float],
    home: list[float],
    plan,
    *,
    bounds=None,
    tcp_x_m: float | None = None,
    clear_z_m: float = 0.10,
    max_jogs: int = 12,
) -> tuple[tuple[str, list[str], list[list[float]]] | None, dict]:
    """Deterministically translate an AI-PC proposal into bounded OMX jogs and swept frames."""
    import grasp_planner

    del home
    kin = grasp_planner.load_kinematics(None, tcp_x_m)[0]
    origin = [float(v) for v in (target[:6] if target and len(target) >= 6 else state[:6])]
    cur = list(origin)
    lag_z = max(0.0, float(kin.fk([norm_to_rad(v) for v in origin[:5]]).z) - float(kin.fk([norm_to_rad(float(v)) for v in state[:5]]).z))
    strat = proposal["strategy"]
    cmds: list[str] = []
    frames: list[list[float]] = [list(origin)]
    meta: dict[str, Any] = {"strategy": strat, "achieved_lift_mm": 0.0}

    def _apply(joint_name: str, axis: int, delta: float):
        if abs(delta) < 1e-6:
            return
        step_cmds = chunk_jog_commands(joint_name, delta)
        nxt = list(cur)
        nxt[axis] = round(cur[axis] + round(delta, 2), 2)
        cmds.extend(step_cmds)
        frames.extend(interpolate_pose(cur, nxt))
        cur[axis] = nxt[axis]

    if strat in ("lift_then_park", "lift_pan_then_park") and float(proposal["lift_mm"]) <= 0.0:
        return None, {**meta, "rejected": "STRATEGY_PARAM_MISMATCH"}
    if strat == "lift_then_park" and abs(float(proposal["pan_detour_deg"])) > 1e-6:
        return None, {**meta, "rejected": "STRATEGY_PARAM_MISMATCH"}
    if strat in ("pan_then_park", "lift_pan_then_park") and abs(float(proposal["pan_detour_deg"])) < 1.0:
        return None, {**meta, "rejected": "STRATEGY_PARAM_MISMATCH"}
    if strat == "retract_elbow_then_park" and abs(float(proposal["elbow_retract_deg"])) < 1.0:
        return None, {**meta, "rejected": "STRATEGY_PARAM_MISMATCH"}

    if strat in ("lift_then_park", "lift_pan_then_park") or proposal["lift_mm"] > 0.0:
        lift_want = float(proposal["lift_mm"])
        if lift_want > 0.0:
            z_start = float(kin.fk([norm_to_rad(v) for v in cur[:5]]).z)
            d_lift, _, axis_name, axis_idx = _lift_axis_delta(list(cur), lift_want, kin, bounds)
            _apply(axis_name, axis_idx, d_lift)
            achieved_mm = (float(kin.fk([norm_to_rad(v) for v in cur[:5]]).z) - z_start) * 1000.0
            meta["achieved_lift_mm"] = round(achieved_mm, 1)
            if achieved_mm < 0.85 * lift_want:
                return None, {**meta, "rejected": "LIFT_UNREACHABLE"}

    if strat == "retract_elbow_then_park" or abs(proposal["elbow_retract_deg"]) > 0.0:
        deg = float(proposal["elbow_retract_deg"])
        if abs(deg) > 0.0:
            du = round(rad_to_norm(norm_to_rad(cur[2]) + math.radians(deg)) - cur[2], 2)
            z_before = float(kin.fk([norm_to_rad(v) for v in cur[:5]]).z)
            probe = list(cur)
            probe[2] = round(cur[2] + du, 2)
            z_after = float(kin.fk([norm_to_rad(v) for v in probe[:5]]).z)
            if z_after < z_before - 0.005:
                return None, {**meta, "rejected": "ELBOW_PLUNGE_VETO"}
            _apply("elbow_flex.pos", 2, du)

    if strat in ("pan_then_park", "lift_pan_then_park") or abs(proposal["pan_detour_deg"]) > 0.0:
        deg = float(proposal["pan_detour_deg"])
        if abs(deg) > 0.0:
            if float(kin.fk([norm_to_rad(v) for v in cur[:5]]).z) - lag_z < float(clear_z_m):
                return None, {**meta, "rejected": "PAN_BELOW_CLEAR_Z"}
            du = round(rad_to_norm(norm_to_rad(cur[0]) + math.radians(deg)) - cur[0], 2)
            _apply("shoulder_pan.pos", 0, du)

    if not cmds:
        return None, {**meta, "rejected": "NOOP_PROPOSAL"}
    if len(cmds) > max_jogs:
        return None, {**meta, "rejected": "TOO_MANY_JOGS", "jogs": len(cmds)}

    full_frames = [*frames, *plan(cur)]
    ok, bound_err = frames_within_bounds(full_frames, bounds, start=origin)
    if not ok:
        return None, {**meta, "rejected": f"OUT_OF_BOUNDS: {bound_err}"}
    return (f"advisor:{strat}", cmds, full_frames), {**meta, "jogs": len(cmds), "commands": list(cmds)}


def capture_views(cell, views: tuple[str, ...] = DEFAULT_VIEWS) -> tuple[list[str], list[str], list[str]]:
    """Capture available non-empty JPEGs as base64 without zero-padding missing views."""
    import cv2

    images_b64, captured, missing = [], [], []
    for role in views:
        try:
            frame = cell.frame(role)
            if isinstance(frame, (bytes, bytearray)) and frame:
                raw = bytes(frame)
            elif frame is not None and hasattr(frame, "size") and frame.size > 0:
                ok, buf = cv2.imencode(".jpg", frame)
                raw = buf.tobytes() if ok else b""
            else:
                raw = b""
        except Exception:
            raw = b""
        if raw:
            images_b64.append(base64.b64encode(raw).decode("ascii"))
            captured.append(role)
        else:
            missing.append(role)
    return images_b64, captured, missing


def _clamp_timeout(spec, timeout_s: float):
    t = min(float(timeout_s), MAX_TIMEOUT_S)
    if isinstance(spec, dict):
        raw_t = spec.get("timeout_s")
        valid_t = isinstance(raw_t, (int, float)) and not isinstance(raw_t, bool) and math.isfinite(raw_t) and raw_t > 0
        return {**spec, "timeout_s": min(float(raw_t) if valid_t else t, t)}
    return spec


def make_advisor(
    backend_spec,
    cell,
    *,
    home: list[float],
    plan,
    bounds=None,
    tcp_x_m: float | None = None,
    clear_z_m: float = 0.10,
    views: tuple[str, ...] = DEFAULT_VIEWS,
    timeout_s: float = MAX_TIMEOUT_S,
    min_confidence: float = 0.70,
    propose_only: bool = False,
):
    """Build an opt-in Tier-2 AI-PC recovery advisor returning validated numeric candidates or None."""
    from cell_vlm_facts import select_vision_backend

    backend = select_vision_backend(_clamp_timeout(backend_spec, timeout_s))

    def advisor(context: dict) -> dict:
        t0 = time.monotonic()
        images_b64, captured, missing = capture_views(cell, views)
        if not images_b64:
            return {"candidate": None, "audit": {"ok": False, "error": "no camera frames", "views_missing": missing}}
        state = context["state"]
        target = context.get("target") or state
        prompt = (
            "You advise coarse safe clearance maneuvers to fold a stopped OMX robot arm home after tier-1 detours failed.\n"
            f"Views attached in order: {captured}. Current joints (units): {state}. Target joints: {target}. Home: {home}. "
            f"TCP z (m): {round(fk_z(state, tcp_x_m=tcp_x_m), 4)}. Clear z (m): {clear_z_m}.\n"
            f"Tier-1 blocked summary: {json.dumps(context.get('blocked', [])[-6:], default=str)}\n"
            "Return STRICT JSON matching the schema. Always lift before turning pan. Choose 'escalate_human' if unsafe or unclear."
        )
        try:
            raw = backend(prompt, images_b64, PROPOSAL_SCHEMA)
        except Exception as exc:
            return {"candidate": None, "audit": {"ok": False, "latency_s": round(time.monotonic() - t0, 3),
                                                 "views_captured": captured, "views_missing": missing,
                                                 "error": f"{type(exc).__name__}: {str(exc)[:120]}"}}
        latency = round(time.monotonic() - t0, 3)
        clean, veto = validate_proposal(raw, holding=bool(context.get("holding")), low=bool(context.get("low")),
                                        min_confidence=min_confidence)
        audit: dict[str, Any] = {
            "ok": clean is not None, "latency_s": latency, "views_captured": captured,
            "views_missing": missing, "proposal": raw if isinstance(raw, dict) else None, "veto": veto,
        }
        if clean is None:
            return {"candidate": None, "audit": audit}
        cand, meta = translate_proposal(clean, state, target, home, plan, bounds=bounds,
                                        tcp_x_m=tcp_x_m, clear_z_m=clear_z_m)
        audit["converted"] = meta
        if cand is None:
            audit["ok"] = False
            audit["veto"] = meta.get("rejected")
            return {"candidate": None, "audit": audit}
        if propose_only:
            return {"candidate": None, "audit": {**audit, "propose_only": True, "would_propose": cand[0]}}
        return {"candidate": cand, "audit": audit}

    return advisor
