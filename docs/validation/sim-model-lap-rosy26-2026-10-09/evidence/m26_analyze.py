"""sim-model-lap 2026-10-09: per-run metrics (lane-model-closed-loop analyze.py, extended).

learned = keep frames with paint_source_used learned AND paint_model_revision == the run's model.
Ring metrics use every GT row within 0.45 m of the ring centre (arc on or off), split by sector.
  python3 m26_analyze.py <ws>/runs --out metrics.json
"""
import argparse
import collections
import json
import math
from pathlib import Path

CENTER = (-0.3357, 0.0011)
RING_RADIUS_M = 0.2514
SIM_BOX_RADIUS_M = 0.08826
SECTORS = (("ring_s", -137.7, -52.5), ("ring_e", -52.5, 52.3), ("ring_n", 52.3, 137.1))
MOVING = {"TRACKING"}


def jl(path):
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()] if path.exists() else []


def analyze_run(run: Path) -> dict:
    cfg = json.loads((run / "config.json").read_text())
    revision = None
    if cfg["model"] != "threshold":
        revision = json.loads((Path(cfg["model"]) / "model_manifest.json").read_text())["model_revision"]
    summary = json.loads((run / "lap/summary.json").read_text()) if (run / "lap/summary.json").exists() else {}
    rows = jl(run / "lap/log.jsonl")
    keep = jl(run / "rec/keep.jsonl")
    poses = [(r, r["gt"]) for r in rows if r.get("gt") and all(math.isfinite(v) for v in r["gt"])]
    paint = collections.Counter(k.get("paint_source_used", "missing") for k in keep)
    learned = sum(1 for k in keep if k.get("paint_source_used") == "learned"
                  and k.get("paint_model_revision") == revision)
    reuse = collections.Counter(k.get("paint_reuse") for k in keep if k.get("paint_source_used") == "learned")
    ages = sorted(k["paint_mask_age_s"] for k in keep if k.get("paint_mask_age_s") is not None)
    reasons = collections.Counter(f"{r.get('state')}/{r.get('reason')}" for r in rows)
    # first stop after the robot first tracked
    # first non-junction stop (HOLD/LOST/RECOVERING) lasting >= 2 sim s once the robot is 0.10 m from the spawn
    started, first_stop, dist, prev, since = False, None, 0.0, None, None
    for r, gt in poses:
        if prev is not None and started:
            dist += math.dist(prev[:2], gt[:2])
        prev = gt
        reason = str(r.get("reason") or "")
        stopped = ((r.get("state") in ("HOLD", "LOST", "STOPPED") or reason.startswith("stuck"))
                   and (not reason.startswith("junction_") or reason == "junction_unexpected"))
        if r.get("state") in MOVING and math.dist(gt[:2], poses[0][1][:2]) > 0.10:
            started = True   # the lap_trip preamble (4 s CAMERA_LINE at the spawn) is not the lap
        if not (started and stopped):
            since = None
            continue
        since = since or (r, gt, dist)
        if (r.get("sim_t") or 0) - (since[0].get("sim_t") or 0) >= 2.0:
            r0, g0, d0 = since
            first_stop = {"sim_t": r0.get("sim_t"), "state": r0["state"], "reason": r0.get("reason"),
                          "gt": [round(v, 4) for v in g0], "dist_before_m": round(d0, 3)}
            break
    arcs = {name: [] for name, _, _ in SECTORS}
    arc_ticks = sum(str(r.get("reason") or "").startswith("lane_arc") for r, _ in poses)
    for r, (x, y, _) in poses:
        radius = math.hypot(x - CENTER[0], y - CENTER[1])
        # arc runs: the lane_arc ticks (as the first harness); arc off: every GT row near the ring
        if (arc_ticks and not str(r.get("reason") or "").startswith("lane_arc")) or radius > 0.45:
            continue
        angle = math.degrees(math.atan2(y - CENTER[1], x - CENTER[0]))
        for name, low, high in SECTORS:
            if low <= angle < high:
                clearance = min(radius - 0.155, 0.345 - radius) - SIM_BOX_RADIUS_M
                arcs[name].append((abs(radius - RING_RADIUS_M), clearance))
                break
    sim = [(r["t"], r["sim_t"]) for r in rows if r.get("sim_t") is not None]
    rtf = (sim[-1][1] - sim[0][1]) / (sim[-1][0] - sim[0][0]) if len(sim) > 1 and sim[-1][0] > sim[0][0] else None
    gts = [g for _, g in poses]
    jumps = [i for i, (a_, b_) in enumerate(zip(gts, gts[1:])) if math.dist(a_[:2], b_[:2]) > 0.1]
    gts = gts[jumps[-1] + 1:] if jumps else gts   # from the last teleport (lap_trip's start pose) on
    return {
        "config": cfg, "model_revision": revision,
        "result": summary.get("result"), "reason": summary.get("reason"),
        "trip_detail": (summary.get("final_view") or {}).get("detail"),
        "keep_frames": len(keep), "learned_frames": learned,
        "learned_ratio": round(learned / len(keep), 3) if keep and revision else None,
        "paint_source_used": dict(paint), "paint_reuse": dict(reuse),
        "paint_mask_age_s_p50_p90": [ages[len(ages) // 2], ages[int(len(ages) * 0.9)]] if ages else None,
        "state_reason_counts": dict(reasons.most_common()),
        "first_stop": first_stop,
        "lane_arc_ticks": arc_ticks,
        "ring": {name: {"ticks": len(v), "max_abs_radial_error_m": round(max(a for a, _ in v), 4),
                        "min_proxy_clearance_m": round(min(c for _, c in v), 4),
                        "negative_proxy_ticks": sum(c < 0 for _, c in v)} for name, v in arcs.items() if v},
        "gt_last": [round(v, 4) for v in gts[-1]] if gts else None,
        "gt_path_m": round(sum(math.dist(a[:2], b[:2]) for a, b in zip(gts, gts[1:])), 3),
        "rtf": round(rtf, 3) if rtf else None,
        "final_cmd": (summary.get("core_after_halt") or {}).get("cmd"),
    }


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("root", type=Path)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    report = {run.name: analyze_run(run) for run in sorted(a.root.iterdir()) if (run / "config.json").exists()}
    a.out.write_text(json.dumps(report, indent=2) + "\n")
    for name, m in report.items():
        print(name, m["result"], m["reason"], f"learned {m['learned_frames']}/{m['keep_frames']}",
              "first_stop", m["first_stop"], "ring", {k: v["max_abs_radial_error_m"] for k, v in m["ring"].items()},
              "rtf", m["rtf"])
