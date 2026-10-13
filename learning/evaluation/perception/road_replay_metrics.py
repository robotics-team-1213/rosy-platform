"""D-384 R0 replay metrics (road_replay.py): motion regimes, NIS tail and mean gates,
keeper pair geometry, curve residuals, COAST episodes and unassociated keeper lines."""
from __future__ import annotations

import numpy as np

CURVE_MIN_RATE = 0.1           # rad/s, moving: a curved segment
JUMP_FRACTION = 0.30           # lane_replay.JUMP_FRACTION


def _motion(ds, dth, dt):
    """stationary / straight (|omega| < 0.05 rad/s) / curve (moving, |omega| > 0.1) /
    turning (the rest: pivots and mild turns) from odometry."""
    if dt <= 0 or (abs(ds / dt) < 0.005 and abs(dth / dt) < 0.05):
        return "stationary"
    if abs(dth / dt) < 0.05:
        return "straight"
    return "curve" if abs(ds / dt) >= 0.005 and abs(dth / dt) > CURVE_MIN_RATE else "turning"


def _keeper_pair_mid(boundaries):
    """Midpoint (y at SIDE_X_M) of the keeper's nearest left and right boundary, or None."""
    near = {}
    for b in boundaries:
        side = b.get("side")
        if side in ("left", "right") and (side not in near or abs(b["y_at_side_x_m"]) < abs(near[side])):
            near[side] = b["y_at_side_x_m"]
    return (near["left"] + near["right"]) / 2 if len(near) == 2 else None


def _parallel_pair_width(last):
    """[y_L - y_R] of the nearest left and right boundary when within 5 deg of parallel."""
    sides = {s: [b for b in last.get("boundaries", []) if b.get("side") == s] for s in ("left", "right")}
    if not sides["left"] or not sides["right"]:
        return []
    l, r = (min(sides[s], key=lambda b: abs(b["y_at_side_x_m"])) for s in ("left", "right"))
    width = l["y_at_side_x_m"] - r["y_at_side_x_m"]
    return [width] if abs(l["heading_deg"] - r["heading_deg"]) <= 5.0 and 0.10 <= width <= 0.30 else []


def _tail_samples(candidates):
    """([(side, pre-gate NIS, gated)], sides missing): per side the best association among
    the lines the keeper itself put on that side (lane owner, 2026-10-01). A side with no
    keeper line gives no sample, only a missing count."""
    samples, missing = [], 0
    for lab, side in (("R", "right"), ("L", "left")):
        own = [c for c in candidates if c.get("side_hint") == side]
        if not own:
            missing += 1
            continue
        best = min(own, key=lambda c: c["nis"][lab])
        samples.append((lab, best["nis"][lab], (best.get("gate") or {}).get(lab) is not None))
    return samples, missing


def _nis_mean_gate(by_state):
    """D-384 R0 (lane owner, 2026-10-01): each regime's applied-association NIS mean in
    [0.5, 4.0], two-sided and not pooled; stationary is not a regime."""
    value = {k: by_state[k]["mean"] for k in ("straight", "curve", "turning")}
    present = [v for v in value.values() if v is not None]
    return {"value": value, "pass": None if not present else all(0.5 <= v <= 4.0 for v in present)}


def _curve_residuals(nis_state):
    """NIS on curved segments against straights. sigma_kappa0 = 0.5 is accepted only
    until validated on curves (lane owner, 2026-10-01): a blow-up is flagged."""
    curve, straight = nis_state["curve"], nis_state["straight"]
    out = {"frames": len(curve), "nis_mean": None, "nis_p95": None, "above_9_21": None,
           "straight_nis_mean": round(float(np.mean(straight)), 3) if straight else None,
           "blow_up": None, "validated_on_curves": False}
    if curve:
        c = np.asarray(curve, float)
        out.update(nis_mean=round(float(c.mean()), 3), nis_p95=round(float(np.percentile(c, 95)), 3),
                   above_9_21=round(float((c > 9.21).mean()), 4))
        out["blow_up"] = bool(out["above_9_21"] > 0.10 or (
            out["straight_nis_mean"] is not None and out["nis_mean"] > 2 * out["straight_nis_mean"]))
    return out


def _detector_metrics(rows, key):
    seen = [r[key] for r in rows if r[key] is not None]
    jumps = sum(1 for a, b in zip(rows, rows[1:]) if a[key] is not None and b[key] is not None
                and abs(a[key]["err"] - b[key]["err"]) > 2 * JUMP_FRACTION)
    straight = [abs(r[key]["err"]) for r in rows if r[key] is not None and r["straight"]]
    n = max(1, len(seen))
    return {"none_rate": round(1 - len(seen) / max(1, len(rows)), 3),
            "on_line_rate": round(sum(s["on_line"] for s in seen) / n, 3),
            "on_paint_rate": round(sum(s["on_paint"] for s in seen) / n, 3),
            "jump_rate": round(jumps / max(1, len(rows) - 1), 3),
            "straight_mean_abs_err": round(float(np.mean(straight)), 3) if straight else None}


def _gate(value, ok):
    return {"value": value, "pass": None if value is None else bool(ok(value))}


def _coast_stats(rows):
    """COAST apart from the NIS tail (no update, NIS undefined): rate and episode lengths."""
    episodes, start = [], None
    for r in rows:
        if r["level"] == "COAST" and start is None:
            start = r["t"]
        elif r["level"] != "COAST" and start is not None:
            episodes.append(r["t"] - start)
            start = None
    if start is not None:
        episodes.append(rows[-1]["t"] - start)
    n = max(1, len(rows))
    return {"rate": round(sum(r["level"] == "COAST" for r in rows) / n, 3), "episodes": len(episodes),
            "mean_s": round(float(np.mean(episodes)), 3) if episodes else 0.0,
            "max_s": round(float(max(episodes)), 3) if episodes else 0.0}


def _unassociated_ys(level, candidates):
    """|y| of keeper-sided, unrejected lines the estimator left unassociated (not STOP)."""
    if level == "STOP":
        return []
    return [abs(c["y"]) for c in candidates
            if c.get("side_hint") in ("left", "right") and isinstance(c.get("nis"), dict)
            and c.get("label") not in ("R", "L")]


def _unassociated(rows):
    return _unassociated_summary([y for r in rows for y in _unassociated_ys(r["level"], r["candidates"])])


def _unassociated_summary(ys):
    pct = [round(float(v), 4) for v in np.percentile(ys, [10, 50, 90])] if ys else [None] * 3
    return {"count": len(ys), "abs_y_m": dict(zip(("p10", "median", "p90"), pct))}


def boundary_candidate(observation, tier: str, confirmed_pair: bool):
    """Offline hypothesis: ONE/MEMORY need an earlier detector-paired BOTH."""
    if tier in ("ONE", "MEMORY") and not confirmed_pair:
        return None
    return observation


def pair_seen_after(was_seen: bool, tier: str) -> bool:
    return tier == "BOTH" or (was_seen and tier != "STOP")


def _boundary_comparison(rows, fresh_odom_frames, memory_before_both):
    candidates = [r["boundary_candidate"] for r in rows if r["boundary_candidate"] is not None]
    return {
        "frames": len(rows),
        "fresh_odom_frames": fresh_odom_frames,
        "tiers": {tier: sum(r["boundary_tier"] == tier for r in rows)
                  for tier in ("BOTH", "ONE", "MEMORY", "STOP")},
        "keep_none_boundary_output": sum(r["keep"] is None and r["boundary"] is not None
                                         for r in rows),
        "memory_before_both": memory_before_both,
        "candidate_suppressed": sum(r["boundary"] is not None and
                                    r["boundary_candidate"] is None for r in rows),
        "candidate_on_paint_rate": (round(sum(c["on_paint"] for c in candidates) /
                                          len(candidates), 3) if candidates else None),
        "scope": "same threshold image and odometry, offline only; no learned paint or lane GT",
    }
