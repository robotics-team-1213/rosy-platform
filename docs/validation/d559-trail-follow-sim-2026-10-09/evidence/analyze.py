#!/usr/bin/env python3
"""D-559 SIM metrics from a trail_sim.py run directory (Gazebo truth only). numpy; matplotlib optional.

    python analyze.py runs/r1 [--leader rosy_01 --follower rosy_02 --gap 0.6]

Deviation = follower truth position to the leader's true driven polyline, which starts with the
seed segment (follower start -> leader start; that straight line is the trail's first segment).
Path gap = leader arc length minus the follower's projection on that polyline.
Contact proxy: centre distance below 2 x URDF rotation radius (0.08257 m) = 0.165 m.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np

ROTATION_RADIUS = 0.08257


def load(path: Path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def project(points: np.ndarray, poly: np.ndarray, cum: np.ndarray):
    """Per point: (distance to polyline, arc length of the closest point)."""
    a, b = poly[:-1], poly[1:]
    ab = b - a
    n = np.maximum((ab * ab).sum(1), 1e-12)
    dist, s = np.empty(len(points)), np.empty(len(points))
    for k, p in enumerate(points):
        t = np.clip(((p - a) * ab).sum(1) / n, 0.0, 1.0)
        q = a + ab * t[:, None]
        d = np.hypot(*(p - q).T)
        i = int(np.argmin(d))
        dist[k], s[k] = d[i], cum[i] + t[i] * math.sqrt(n[i])
    return dist, s


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("run")
    ap.add_argument("--leader", default="rosy_01")
    ap.add_argument("--follower", default="rosy_02")
    ap.add_argument("--gap", type=float, default=0.6)
    args = ap.parse_args()
    run = Path(args.run)
    truth = load(run / "truth.jsonl")
    events = load(run / "events.jsonl")
    swarm = [r for r in load(run / "swarm.jsonl") if "swarm" in r]
    by = {args.leader: [], args.follower: []}
    for r in truth:
        if r["robot"] in by:
            by[r["robot"]].append((r["t"], r["sim_t"], r["x"], r["y"], r["yaw"]))
    L = np.array(sorted(by[args.leader], key=lambda r: r[0]))
    F = np.array(sorted(by[args.follower], key=lambda r: r[0]))
    armed_t = next(e["t"] for e in events if e["kind"] == "armed")
    done_t = next(e["t"] for e in events if e["kind"] == "phase" and e["value"] == "done")
    phases = [(e["value"], e["t"]) for e in events if e["kind"] == "phase"]
    Fa = F[(F[:, 0] >= armed_t) & (F[:, 0] <= done_t)]
    La = L[(L[:, 0] >= armed_t - 1.0) & (L[:, 0] <= done_t)]
    # Leader's driven polyline from arming, seeded by the follower's position at arming.
    poly = [Fa[0, 2:4]]
    for x, y in La[:, 2:4]:
        if math.hypot(x - poly[-1][0], y - poly[-1][1]) >= 0.002:
            poly.append(np.array([x, y]))
    poly = np.array(poly)
    cum = np.concatenate([[0.0], np.cumsum(np.hypot(*np.diff(poly, axis=0).T))])
    dev, fs = project(Fa[:, 2:4], poly, cum)
    # Leader arc length over time (same polyline, so project the leader too).
    _, ls_at = project(La[:, 2:4], poly, cum)
    ls = np.interp(Fa[:, 0], La[:, 0], np.maximum.accumulate(ls_at))
    lx = np.interp(Fa[:, 0], La[:, 0], La[:, 2])
    ly = np.interp(Fa[:, 0], La[:, 0], La[:, 3])
    centre = np.hypot(lx - Fa[:, 2], ly - Fa[:, 3])
    path_gap = ls - fs
    fspeed = np.concatenate([[0.0], np.hypot(*np.diff(Fa[:, 2:4], axis=0).T) /
                             np.maximum(np.diff(Fa[:, 1]), 1e-3)])

    def window(name, start=0.0):
        i = [k for k, (n, _) in enumerate(phases) if n == name][0]
        return phases[i][1] + start, phases[i + 1][1]

    s0, s1 = window("stop_10s", 5.0)
    m = (Fa[:, 0] >= s0) & (Fa[:, 0] <= s1)
    stop = {"follower_max_speed_mps": round(float(fspeed[m].max()), 4),
            "path_gap_m": [round(float(path_gap[m].min()), 3), round(float(path_gap[m].max()), 3)]}
    cut = {}
    pause_t = next((e["t"] for e in events if e["kind"] == "cut" and e["value"] == "pause"), None)
    resume_t = next((e["t"] for e in events if e["kind"] == "cut" and e["value"] != "pause"), None)
    if pause_t is not None:
        hold = next((r["t"] for r in swarm if r["t"] >= pause_t and r["swarm"].get("holding")), None)
        still = next((t for t, v in zip(Fa[:, 0], fspeed) if t >= pause_t and v < 0.005), None)
        moving = next((t for t, v in zip(Fa[:, 0], fspeed) if resume_t and t >= resume_t and v > 0.03), None)
        cut = {"holding_after_s": None if hold is None else round(hold - pause_t, 2),
               "follower_stopped_after_s": None if still is None else round(still - pause_t, 2),
               "moving_again_after_resume_s": None if moving is None else round(moving - resume_t, 2),
               "max_speed_after_hold_mps": None if hold is None else round(float(
                   fspeed[(Fa[:, 0] >= hold + 0.5) & (Fa[:, 0] <= resume_t)].max(initial=0.0)), 4)}
    reasons = []
    for r in swarm:
        reason = (r["swarm"].get("trail") or {}).get("hold_reason")
        if not reasons or reasons[-1][1] != reason:
            reasons.append((round(r["t"] - armed_t, 1), reason))
    moving = fspeed > 0.02
    summary = {
        "samples": int(len(Fa)), "leader_path_m": round(float(cum[-1]), 3),
        "deviation_m": {"max": round(float(dev.max()), 4), "rms": round(float(np.sqrt((dev ** 2).mean())), 4),
                        "p95": round(float(np.percentile(dev, 95)), 4),
                        "max_while_moving": round(float(dev[moving].max()), 4) if moving.any() else None},
        "min_centre_gap_m": round(float(centre.min()), 3),
        "min_path_gap_m": round(float(path_gap.min()), 3),
        "contact_proxy": bool(centre.min() < 2 * ROTATION_RADIUS),
        "leader_stop": stop, "stream_cut": cut, "hold_reasons": reasons,
        "worst_deviation_at_s": round(float(Fa[int(np.argmax(dev)), 0] - armed_t), 1),
        "phases_s": [(n, round(t - armed_t, 1)) for n, t in phases],
    }
    (run / "summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print(json.dumps(summary, indent=1))
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(7, 7))
        ax.plot(poly[:, 0], poly[:, 1], color="#1f77b4", lw=2.5, label="leader (truth, + seed)")
        ax.plot(Fa[:, 2], Fa[:, 3], color="#d62728", lw=1.0, label="follower (truth)")
        k = int(np.argmax(dev))
        ax.plot(Fa[k, 2], Fa[k, 3], "kx", ms=10, label=f"max deviation {dev[k]:.3f} m")
        ax.set_aspect("equal")
        ax.grid(alpha=0.3)
        ax.legend(loc="best")
        ax.set_title("D-559 trail follow SIM (Gazebo truth)")
        fig.savefig(run / "paths.png", dpi=110, bbox_inches="tight")
    except ImportError:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
