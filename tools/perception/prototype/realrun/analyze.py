"""Aggregate frames_pXX.jsonl into summary.json and a printed table."""
import collections
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.getcwd(), "out")
FPS = 8.0
TIERS = ("BOTH", "ONE", "MEMORY", "STOP")


def streak(flags):
    best = cur = 0
    start = bstart = 0
    for i, f in enumerate(flags):
        if f:
            if cur == 0:
                start = i
            cur += 1
            if cur > best:
                best, bstart = cur, start
        else:
            cur = 0
    return best, bstart


def stats(recs):
    n = len(recs)
    s = {"frames": n, "seconds": n / FPS}
    for key, get in (("centre", lambda r: r["tier"]),
                     ("centre_noodom", lambda r: r["centre_frozen"]["tier"])):
        c = collections.Counter(get(r) for r in recs)
        s[key + "_tiers_pct"] = {t: round(100.0 * c[t] / n, 1) for t in TIERS}
        stop = [get(r) == "STOP" for r in recs]
        b, st = streak(stop)
        s[key + "_longest_stop"] = {"frames": b, "s": b / FPS, "start_frame": st}
    s["centre_usable_pct"] = round(100.0 * sum(r["visible"] for r in recs) / n, 1)
    s["centre_noodom_usable_pct"] = round(
        100.0 * sum(r["centre_frozen"]["tier"] != "STOP" for r in recs) / n, 1)
    s["centre_source_pct"] = {k: round(100.0 * v / n, 1) for k, v in collections.Counter(
        r["source"] or "-" for r in recs).items()}
    s["centre_junction_frames"] = dict(collections.Counter(
        r["junction"] for r in recs if r["junction"]))
    s["centre_washed_pct(0.75)"] = round(100.0 * sum(r["washed"] for r in recs) / n, 1)
    s["centre_would_be_washed_pct(dev 0.40)"] = round(
        100.0 * sum(r["washed_dev"] for r in recs) / n, 1)
    # line (device default) and lane (device yaml)
    for key in ("line", "lane"):
        vis = [r[key] is not None for r in recs]
        s[key + "_output_pct"] = round(100.0 * sum(vis) / n, 1)
        s[key + "_usable_pct(conf>=0.35)"] = round(100.0 * sum(
            r[key] is not None and r[key]["confidence"] >= 0.35 for r in recs) / n, 1)
        b, st = streak([not v for v in vis])
        s[key + "_longest_none"] = {"frames": b, "s": b / FPS, "start_frame": st}
    s["line_output_driven_by_wall_pct"] = round(100.0 * sum(
        r["line"] is not None and r["line_wall_frac"] > 0.5 for r in recs) / n, 1)
    s["line_output_wall_touched_pct(>20%)"] = round(100.0 * sum(
        r["line"] is not None and r["line_wall_frac"] > 0.2 for r in recs) / n, 1)
    s["line_saturated_pct(|e|>=0.9)"] = round(100.0 * sum(
        r["line"] is not None and abs(r["line"]["error"]) >= 0.9 for r in recs) / n, 1)
    s["lane_saturated_pct(|e|=1)"] = round(100.0 * sum(
        r["lane"] is not None and abs(r["lane"]["error"]) >= 0.999 for r in recs) / n, 1)
    # wall
    s["wall_base_inside_bev_pct"] = round(100.0 * sum(r["wall_in_bev"] for r in recs) / n, 1)
    s["bev_paint_mostly_wall_pct(>50%)"] = round(100.0 * sum(
        r["wall_paint_frac"] > 0.5 for r in recs) / n, 1)
    s["bev_paint_any_wall_pct(>10%)"] = round(100.0 * sum(
        r["wall_paint_frac"] > 0.1 for r in recs) / n, 1)
    s["chosen_boundary_on_wall_pct"] = round(100.0 * sum(r["boundary_on_wall"] for r in recs) / n, 1)
    s["chosen_boundary_wide_pct(>6cm)"] = round(100.0 * sum(r["boundary_wide"] for r in recs) / n, 1)
    s["chosen_boundary_far_pct"] = round(100.0 * sum(r["boundary_far"] for r in recs) / n, 1)
    s["output_while_boundary_is_wall_pct"] = round(100.0 * sum(
        r["visible"] and r["boundary_on_wall"] for r in recs) / n, 1)
    # road
    sl = [r for r in recs if r["road"]["stop_line"]]
    s["road_stop_line_pct"] = round(100.0 * len(sl) / n, 1)
    s["road_stop_line_on_wall_pct"] = round(100.0 * sum(
        r["wall_cols"] >= 128 and r["road"]["stop_line"]["row"] <= r["wall_base_max"] + 2
        for r in sl) / n, 1)
    s["road_stop_line_above_horizon_pct(no ground distance)"] = round(100.0 * sum(
        r["road"]["stop_line"]["dist"] is None for r in sl) / n, 1)
    s["road_stop_line_with_distance_pct"] = round(100.0 * sum(
        r["road"]["stop_line"]["dist"] is not None for r in sl) / n, 1)
    s["road_crosswalk_with_distance_pct"] = round(100.0 * sum(
        bool(r["road"]["crosswalk"]) and r["road"]["crosswalk"]["dist"] is not None for r in recs) / n, 1)
    s["road_crosswalk_pct"] = round(100.0 * sum(bool(r["road"]["crosswalk"]) for r in recs) / n, 1)
    s["road_signal_frames"] = dict(collections.Counter(
        r["road"]["signal"] for r in recs if r["road"]["signal"]))
    steps = sorted(r["vo_step_m"] for r in recs)
    s["vo_step_median_cm"] = round(100 * steps[len(steps) // 2], 2)
    s["vo_path_m"] = round(sum(steps), 2)
    s["vo_fail_pct"] = round(100.0 * sum(r["vo_inliers"] == 0 for r in recs) / n, 1)
    s["frames_robot_moving_pct(vo>0.3cm/frame)"] = round(100.0 * sum(r["vo_step_m"] > 0.003 for r in recs) / n, 1)
    mv = [r for r in recs if r["vo_step_m"] > 0.003]
    if mv:
        c = collections.Counter(r["tier"] for r in mv)
        s["centre_tiers_pct_while_moving"] = {t: round(100.0 * c[t] / len(mv), 1) for t in TIERS}
    return s


def main():
    parts = {}
    allr = []
    for p in range(1, 8):
        path = os.path.join(OUT, f"frames_p{p:02d}.jsonl")
        recs = [json.loads(l) for l in open(path)]
        parts[f"p{p:02d}"] = stats(recs)
        allr += recs
    summary = {"overall": stats(allr), "parts": parts}
    json.dump(summary, open(os.path.join(OUT, "summary_stats.json"), "w"), indent=1)
    keys = ["frames", "centre_tiers_pct", "centre_usable_pct", "centre_longest_stop",
            "centre_noodom_tiers_pct", "line_usable_pct(conf>=0.35)", "line_longest_none",
            "line_output_driven_by_wall_pct", "lane_usable_pct(conf>=0.35)",
            "wall_base_inside_bev_pct", "chosen_boundary_on_wall_pct",
            "road_stop_line_pct", "road_stop_line_on_wall_pct", "road_crosswalk_pct"]
    for name, s in [("ALL", summary["overall"])] + list(parts.items()):
        print(name, {k: s[k] for k in keys})
    print(json.dumps(summary["overall"], indent=1))


if __name__ == "__main__":
    main()
