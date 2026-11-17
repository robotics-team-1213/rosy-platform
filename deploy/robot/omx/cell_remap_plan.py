"""What a remap would ask of the arm, checked before any move (`cell_calibrate.py auto`, `--plan-only`).

Single Responsibility: solve the IK of every remap point and judge it against the arm's own window
(`joint_min` / `joint_max` in its cell config) and planar reach (`calibrate.max_reach_m`, absent = no reach check,
never a default). Never opens a port or a camera.

2026-11-14: arm_b's first remap goto stopped on contact at wrist_flex 59.3. No offline self-clearance model of the
printed holder is trusted yet (the holder simulation said clearance depends only on wrist_roll; the arm said
otherwise), so the logged wrist window is the clearance check.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import cell_pipeline_io as cio

PLAYED = ("above_pick", "home")  # the remap goes to above_pick and folds; its other chunks never play


def scoped(config: dict) -> dict:
    return dict(config, played_chunks=list(PLAYED))


def view(config: dict, x: float, y: float) -> dict:
    sites = config.get("calibrate", {}).get("map_sites") or ["floor", "pinky", "belt"]
    site = next(s for s in sites if s in config["sites"])
    return {"x": x, "y": y, "z": round(config["coarse"]["z_view"] - config["plan"]["approach_m"], 4),
            "yaw_deg": config["sites"][site]["yaw_deg"]}


def reach_note(config: dict) -> str:
    limit = config.get("calibrate", {}).get("max_reach_m")
    return "no reach check" if limit is None else f"max_reach_m {limit}"


def plan(config: dict, points: list) -> list:
    """One row per point, nearest first: the above_pick joints, and the error that would refuse it."""
    rows, cfg = [], scoped(config)
    limit = config.get("calibrate", {}).get("max_reach_m")
    for x, y in sorted(points, key=lambda q: math.hypot(*q)):
        target, row = view(config, x, y), {"point": [x, y]}
        try:
            library = cio.plan_library(cfg, target, target, check=False)
            row["above_pick"] = {n: round(v, 1) for n, v in zip(library["names"], library["chunks"]["above_pick"][-1])}
            row["error"] = cio.limit_error(cfg, library)
        except SystemExit as exc:
            row["error"] = str(exc)[:160]
        r = math.hypot(x, y)
        if limit is not None and r > limit + 1e-9:
            row["error"] = "; ".join(filter(None, [row.get("error"), f"r {r:.3f} m is beyond max_reach_m {limit}"]))
        rows.append(row)
    return rows


def refusal(rows: list) -> str | None:
    bad = [r for r in rows if r["error"]]
    return f"remap refused, {len(bad)} of {len(rows)} points leave this arm's window or reach: " + "; ".join(
        f"{r['point']}: {r['error']}" for r in bad) if bad else None


def planned_yaw(library: Path, config: dict) -> float | None:
    """FK yaw of a library's above_pick frame (the top-down IK may plan the 180-deg twin), or None."""
    import cell_pivot, omx_tcp

    tcp_x_m = omx_tcp.config_tcp(config, config.get("plan"))
    try:
        frame = json.loads(Path(library).read_text(encoding="utf-8"))["chunks"]["above_pick"][0][:5]
        return float(cell_pivot.joints_tcp(frame, **({"tcp_x_m": tcp_x_m} if tcp_x_m is not None else {}))[3])
    except (OSError, KeyError, IndexError, TypeError, ValueError):
        return None


def missing_maps(config: dict, calibration: dict, sites) -> list:
    """Sites to remap: no map, or a one-jaw map while the config asks for a TCP map (calibrate.tcp_marks).
    2026-11-17 arm_a: its 11-15 map followed one jaw, so every TCP pivot carried ~28 mm and failed max_bias_mm."""
    tcp = bool((config.get("calibrate") or {}).get("tcp_marks"))
    have = calibration.get("sites", {})
    return [s for s in sites if s not in have or (tcp and have[s].get("marks") != "tcp")]
