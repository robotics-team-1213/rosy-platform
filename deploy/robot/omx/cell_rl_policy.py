#!/usr/bin/env python3
"""Online Imitation Learning (BC demonstration buffer) and Contextual Residual Reinforcement Learning
engine (`cell_rl_policy.py`) for OMX multi-cell robot control.

Split from `cell_problem_pipeline.py` during multi-panel control modularization so the problem
ledger/reproducer (`cell_problem_pipeline.py`) and online IL/RL residual policy (`cell_rl_policy.py`)
each have a clean single responsibility well under 400 lines. Re-exported by `cell_problem_pipeline`.
"""
from __future__ import annotations

import json
from pathlib import Path
import time
from typing import Any

LEDGER_FILENAME = "problem-cases.jsonl"
_IL_CACHE: dict[str, tuple[int, int, dict[str, list[tuple[float, float, float, float, float, float]]]]] = {}
_RL_CACHE: dict[str, tuple[int, int, dict[str, Any]]] = {}


def _load_il_demos_by_bucket(il_path: Path) -> dict[str, list[tuple[float, float, float, float, float, float]]]:
    try:
        st = il_path.stat()
    except OSError:
        return {}
    key = str(il_path)
    cached = _IL_CACHE.get(key)
    if cached is not None and cached[0] == st.st_mtime_ns and cached[1] == st.st_size:
        return cached[2]
    by_bucket: dict[str, list[tuple[float, float, float, float, float, float]]] = {}
    for line in il_path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if float(row.get("reward") or 0.0) <= 0.0:
            continue
        b = str(row.get("bucket") or "")
        st_vec = row.get("state") or []
        act = row.get("expert_action_xyz") or []
        if b and len(st_vec) >= 3 and len(act) >= 3:
            sx, sy, sz = float(st_vec[0]), float(st_vec[1]), float(st_vec[2])
            by_bucket.setdefault(b, []).append((sx, sy, sz, float(act[0]) - sx, float(act[1]) - sy, float(act[2]) - sz))
    _IL_CACHE[key] = (st.st_mtime_ns, st.st_size, by_bucket)
    return by_bucket


def _load_rl_state(rl_path: Path) -> dict[str, Any]:
    try:
        st = rl_path.stat()
    except OSError:
        return {}
    key = str(rl_path)
    cached = _RL_CACHE.get(key)
    if cached is not None and cached[0] == st.st_mtime_ns and cached[1] == st.st_size:
        return cached[2]
    try:
        state = json.loads(rl_path.read_text(encoding="utf-8"))
        if isinstance(state, dict):
            _RL_CACHE[key] = (st.st_mtime_ns, st.st_size, state)
            return state
    except Exception:
        pass
    return {}


def _resolve_work_dir(config_or_work: dict | Path) -> Path:
    if isinstance(config_or_work, Path):
        p = config_or_work
        return p.parent if p.suffix == ".jsonl" else p
    if isinstance(config_or_work, dict):
        if config_or_work.get("problem_ledger_file"):
            return Path(config_or_work["problem_ledger_file"]).parent
        return Path(config_or_work.get("_work") or ".")
    return Path(".")


def _zone_bucket(pick: dict[str, Any]) -> str:
    area = str(pick.get("area_id") or pick.get("area") or "pallet").lower()
    if area in ("pinky", "amr"):
        return "pinky_horiz"
    if area in ("belt", "beltend"):
        return "belt"
    if int(pick.get("row") or 1) >= 2:
        return "row2_horiz"
    x = float((pick.get("effective_xyz_m") or [pick.get("x", 0.15)])[0])
    return "pallet_left" if x < 0.125 else ("pallet_mid" if x < 0.175 else "pallet_right")


def _place_tier_key(place: dict[str, Any]) -> tuple[str, str]:
    place_area = str(place.get("area_id") or place.get("area") or "").lower()
    tier = int(place.get("tier") or (1 if place_area in ("pinky", "amr", "belt") else 2))
    key = f"{place_area}_tier_{tier}" if place_area in ("pinky", "amr", "belt") else f"tier_{tier}"
    return place_area, key


def _clamp(val: float, lo: float, hi: float, ndigits: int = 5) -> float:
    return round(max(lo, min(hi, float(val))), ndigits)


def knn_il_residual(
    config_or_work: dict | Path,
    bucket: str,
    query_xyz: list[float],
    *,
    sigma_m: float = 0.025,
    k: int = 5,
) -> dict[str, float] | None:
    """Compute nonnegative normalized RBF kernel-weighted residual `(dx_m, dy_m, dz_m)` from expert demonstrations
    in `il-demos.jsonl` matching `bucket` with positive reward (`sum(w_i) == 1`)."""
    import math

    work = _resolve_work_dir(config_or_work)
    il_path = work / "il-demos.jsonl"
    if len(query_xyz) < 3:
        return None
    rows = _load_il_demos_by_bucket(il_path).get(bucket)
    if not rows:
        return None
    qx, qy, qz = float(query_xyz[0]), float(query_xyz[1]), float(query_xyz[2])
    candidates = [
        ((qx - sx) ** 2 + (qy - sy) ** 2 + (qz - sz) ** 2, dx, dy, dz)
        for sx, sy, sz, dx, dy, dz in rows
    ]
    candidates.sort(key=lambda item: item[0])
    top_k = candidates[: max(1, int(k))]
    two_s2 = 2.0 * max(sigma_m, 1e-4) ** 2
    weights = [math.exp(-item[0] / two_s2) for item in top_k]
    w_sum = sum(weights)
    if w_sum <= 1e-12:
        return None
    norm_w = [w / w_sum for w in weights]
    dx = sum(w * item[1] for w, item in zip(norm_w, top_k))
    dy = sum(w * item[2] for w, item in zip(norm_w, top_k))
    dz = sum(w * item[3] for w, item in zip(norm_w, top_k))
    return {"dx_m": round(dx, 5), "dy_m": round(dy, 5), "dz_m": round(dz, 5), "neighbors": len(top_k)}



def update_il_rl_from_run(config_or_work: dict | Path, run_res: dict[str, Any]) -> dict[str, Any]:
    """Online Imitation Learning (BC demonstration buffer + ridge regression) and Reinforcement Learning
    (contextual advantage-weighted 4-DOF residual policy update) from real-hardware and simulation rollouts."""
    work = _resolve_work_dir(config_or_work)
    work.mkdir(parents=True, exist_ok=True)
    il_path = work / "il-demos.jsonl"
    rl_path = work / "rl-policy.json"

    directive_doc = dict(run_res.get("directive") or {})
    pick = dict(run_res.get("pick") or directive_doc.get("pick") or {})
    place = dict(run_res.get("place") or directive_doc.get("place") or {})
    p_xyz = list(pick.get("effective_xyz_m") or [pick.get("x", 0.15), pick.get("y", -0.01), pick.get("z", 0.007)])
    pl_xyz = list(place.get("effective_xyz_m") or [place.get("x", 0.158), place.get("y", -0.013), place.get("z", 0.0674)])
    bucket = _zone_bucket(pick)
    _, place_tier_key = _place_tier_key(place)

    res_name = str(run_res.get("result") or "")
    verified = bool(run_res.get("task_verified"))
    steps = list(run_res.get("steps") or [])
    grasped = any(bool(s.get("holding")) for s in steps if s.get("command") == "run grasp_pick") or bool(
        (run_res.get("grasp_dynamics") or {}).get("holding")
    )
    placed = any(s.get("command") in ("run descend_place", "run release_place") for s in steps) or res_name == "placed"

    base_reward = 2.0 if verified else (1.0 if placed else (0.4 if grasped else (-0.5 if res_name == "empty" else -0.8)))
    place_err_mm = float(run_res.get("place_error_mm") or 0.0)
    jitter_std = float(run_res.get("jitter_std") or 0.0)
    yaw_err_deg = abs(float(run_res.get("yaw_error_deg") or 0.0))
    shaping = -0.08 * place_err_mm - 0.15 * jitter_std - 0.04 * yaw_err_deg
    reward = round(base_reward + shaping, 4) if (place_err_mm or jitter_std or yaw_err_deg) else base_reward

    il_count = 0
    if grasped or placed or verified or run_res.get("recovery"):
        rec_list = list(run_res.get("recovery") or [])
        target_xyz = list(rec_list[-1].get("recovered_pick_xyz_m", p_xyz)) if (rec_list and not grasped) else p_xyz
        demo = {
            "t": round(time.time(), 3),
            "bucket": bucket,
            "state": [round(float(v), 5) for v in p_xyz] + [float(pick.get("yaw_deg", -90.0)), int(place.get("tier") or 2)],
            "expert_action_xyz": [round(float(v), 5) for v in target_xyz],
            "place_xyz": [round(float(v), 5) for v in (run_res.get("recovered_place_xyz_m") or pl_xyz)],
            "reward": reward,
            "verified": verified,
        }
        with il_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(demo) + "\n")
        _IL_CACHE.pop(str(il_path), None)
    if il_path.exists():
        il_count = sum(1 for _ in il_path.open("r", encoding="utf-8"))

    rl_state: dict[str, Any] = {"episodes": 0, "buckets": {}, "place_tiers": {}}
    if rl_path.exists():
        try:
            rl_state = json.loads(rl_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    rl_state["episodes"] = int(rl_state.get("episodes", 0)) + 1
    b_info = dict(
        (rl_state.get("buckets") or {}).get(bucket)
        or {"dx_m": 0.0, "dy_m": 0.0, "dz_m": 0.0, "dyaw_deg": 0.0, "speed_scale": 1.0, "baseline_r": 0.0, "updates": 0, "last_reward": 0.0}
    )
    adv = reward - float(b_info.get("baseline_r", 0.0))
    b_info["baseline_r"] = round(0.8 * float(b_info.get("baseline_r", 0.0)) + 0.2 * reward, 4)
    if (res_name == "empty" or run_res.get("recovery")) and run_res.get("recovery") and pick:
        last_rec = run_res["recovery"][-1].get("recovered_pick_xyz_m") or p_xyz
        b_info["dx_m"] = _clamp(float(b_info["dx_m"]) + 0.35 * (float(last_rec[0]) - float(p_xyz[0])), -0.0080, 0.0080)
        b_info["dy_m"] = _clamp(float(b_info["dy_m"]) + 0.35 * (float(last_rec[1]) - float(p_xyz[1])), -0.0080, 0.0080)
        b_info["dz_m"] = _clamp(float(b_info["dz_m"]) + 0.30 * (float(last_rec[2]) - float(p_xyz[2])), -0.0030, 0.0025)
    if run_res.get("measured_pick_offset_m"):
        mo = list(run_res["measured_pick_offset_m"])
        lr = 0.45 if adv >= 0.0 else 0.30
        b_info["dx_m"] = _clamp(float(b_info["dx_m"]) + lr * float(mo[0]), -0.0080, 0.0080)
        b_info["dy_m"] = _clamp(float(b_info["dy_m"]) + lr * float(mo[1]), -0.0080, 0.0080)
        if len(mo) >= 3:
            b_info["dz_m"] = _clamp(float(b_info["dz_m"]) + 0.30 * float(mo[2]), -0.0030, 0.0025)
    if run_res.get("measured_yaw_offset_deg") is not None:
        b_info["dyaw_deg"] = _clamp(float(b_info.get("dyaw_deg", 0.0)) + 0.40 * float(run_res["measured_yaw_offset_deg"]), -6.0, 6.0, 3)
    if run_res.get("measured_rpy_offset_deg"):
        r_off = list(run_res["measured_rpy_offset_deg"])
        if len(r_off) >= 3:
            b_info["droll_deg"] = _clamp(float(b_info.get("droll_deg", 0.0)) + 0.40 * float(r_off[0]), -8.0, 8.0, 3)
            b_info["dpitch_deg"] = _clamp(float(b_info.get("dpitch_deg", 0.0)) + 0.40 * float(r_off[1]), -8.0, 8.0, 3)
            b_info["dyaw_deg"] = _clamp(float(b_info.get("dyaw_deg", 0.0)) + 0.40 * float(r_off[2]), -6.0, 6.0, 3)
    if verified and place_err_mm < 1.5 and jitter_std < 0.12:
        b_info["speed_scale"] = round(min(1.25, float(b_info.get("speed_scale", 1.0)) + 0.03), 3)
    b_info["updates"] = int(b_info.get("updates", 0)) + 1
    b_info["last_reward"] = reward
    b_info["advantage"] = round(adv, 4)
    rl_state.setdefault("buckets", {})[bucket] = b_info

    if (run_res.get("recovered_place_xyz_m") or run_res.get("measured_place_offset_m")) and (verified or placed):
        t_info = dict(
            (rl_state.get("place_tiers") or {}).get(place_tier_key)
            or {"dx_m": 0.0, "dy_m": 0.0, "dz_m": 0.0, "dyaw_deg": 0.0, "updates": 0}
        )
        if run_res.get("recovered_place_xyz_m"):
            rec_pl = list(run_res["recovered_place_xyz_m"])
            d_pl = [float(rec_pl[0]) - float(pl_xyz[0]), float(rec_pl[1]) - float(pl_xyz[1]), float(rec_pl[2]) - float(pl_xyz[2])]
            pl_lr = 0.35
        else:
            d_pl = list(run_res["measured_place_offset_m"]) + [0.0]
            pl_lr = 0.65
        t_info["dx_m"] = _clamp(float(t_info["dx_m"]) + pl_lr * d_pl[0], -0.0080, 0.0080)
        t_info["dy_m"] = _clamp(float(t_info["dy_m"]) + pl_lr * d_pl[1], -0.0080, 0.0080)
        t_info["dz_m"] = _clamp(float(t_info["dz_m"]) + 0.35 * d_pl[2], -0.0020, 0.0020)
        if run_res.get("measured_place_yaw_offset_deg") is not None:
            t_info["dyaw_deg"] = _clamp(float(t_info.get("dyaw_deg", 0.0)) + 0.40 * float(run_res["measured_place_yaw_offset_deg"]), -6.0, 6.0, 3)
        t_info["updates"] = int(t_info.get("updates", 0)) + 1
        rl_state.setdefault("place_tiers", {})[place_tier_key] = t_info

    rl_path.write_text(json.dumps(rl_state, indent=2), encoding="utf-8")
    _RL_CACHE.pop(str(rl_path), None)
    return {"il_demos": il_count, "rl_episodes": rl_state["episodes"], "bucket": bucket, "reward": reward, "residual": b_info}


def apply_learned_il_rl_residual(config_or_work: dict | Path, directive: dict[str, Any]) -> dict[str, Any]:
    """Apply the learned hybrid IL (RBF k-NN) + RL residual `(dx_m, dy_m, dz_m, dyaw_deg, speed_scale)` to pick and place coordinates."""
    work = _resolve_work_dir(config_or_work)
    rl_path = work / "rl-policy.json"
    il_path = work / "il-demos.jsonl"
    rl_state = _load_rl_state(rl_path)
    if not rl_state and not _load_il_demos_by_bucket(il_path):
        return directive
    try:
        bucket = _zone_bucket(directive.get("pick") or {})
        b_info = (rl_state.get("buckets") or {}).get(bucket)
        max_xy = 0.0080 if bucket in ("pinky_horiz", "belt") else 0.0015
        if "pick" in directive:
            p = dict(directive["pick"])
            xyz = list(p.get("effective_xyz_m") or [p["x"], p["y"], p["z"]])
            il_res = knn_il_residual(work, bucket, xyz)
            if b_info or il_res:
                rl_updates = int((b_info or {}).get("updates", 0))
                rl_w = min(1.0, rl_updates / 3.0) if b_info else 0.0
                il_w = (1.0 - 0.5 * rl_w) if (il_res and not b_info) else (0.25 if (il_res and rl_updates < 2) else 0.0)
                raw_dx = float((b_info or {}).get("dx_m", 0.0)) + il_w * float((il_res or {}).get("dx_m", 0.0))
                raw_dy = float((b_info or {}).get("dy_m", 0.0)) + il_w * float((il_res or {}).get("dy_m", 0.0))
                raw_dz = float((b_info or {}).get("dz_m", 0.0)) + il_w * float((il_res or {}).get("dz_m", 0.0))
                xyz[0] = round(float(xyz[0]) + _clamp(raw_dx, -max_xy, max_xy), 5)
                xyz[1] = round(float(xyz[1]) + _clamp(raw_dy, -max_xy, max_xy), 5)
                xyz[2] = round(float(xyz[2]) + _clamp(raw_dz, -0.0015, 0.0015), 5)
                p["effective_xyz_m"] = xyz
                p["x"], p["y"], p["z"] = xyz[0], xyz[1], xyz[2]
                if b_info and b_info.get("dyaw_deg") and "yaw_deg" in p:
                    p["yaw_deg"] = round(float(p["yaw_deg"]) + float(b_info["dyaw_deg"]), 2)
                if b_info and (b_info.get("droll_deg") or b_info.get("dpitch_deg")):
                    p["roll_deg"] = round(float(p.get("roll_deg", 0.0)) + float(b_info.get("droll_deg", 0.0)), 2)
                    p["pitch_deg"] = round(float(p.get("pitch_deg", 88.0)) + float(b_info.get("dpitch_deg", 0.0)), 2)
                directive["pick"] = p
                if b_info and b_info.get("speed_scale") and float(b_info["speed_scale"]) != 1.0:
                    exec_cfg = dict(directive.get("execution") or {})
                    exec_cfg.setdefault("rl_speed_scale", float(b_info["speed_scale"]))
                    directive["execution"] = exec_cfg
        if "place" in directive:
            pl = dict(directive["place"])
            place_area, t_key = _place_tier_key(pl)
            t_info = (rl_state.get("place_tiers") or {}).get(t_key)
            max_pl_xy = 0.0080 if place_area in ("pinky", "amr", "belt") else 0.0015
            if t_info:
                pl_xyz = list(pl.get("effective_xyz_m") or [pl["x"], pl["y"], pl["z"]])
                pl_xyz[0] = round(float(pl_xyz[0]) + _clamp(t_info.get("dx_m", 0.0), -max_pl_xy, max_pl_xy), 5)
                pl_xyz[1] = round(float(pl_xyz[1]) + _clamp(t_info.get("dy_m", 0.0), -max_pl_xy, max_pl_xy), 5)
                pl["effective_xyz_m"] = pl_xyz
                pl["x"], pl["y"] = pl_xyz[0], pl_xyz[1]
                if t_info.get("dyaw_deg") and "yaw_deg" in pl:
                    pl["yaw_deg"] = round(float(pl["yaw_deg"]) + float(t_info["dyaw_deg"]), 2)
                directive["place"] = pl
    except Exception:
        pass
    return directive
