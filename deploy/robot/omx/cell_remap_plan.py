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
import cell_remap_depth as rd

PLAYED = ("above_pick", "home")  # the remap goes to above_pick and folds; its other chunks never play
REMAP_CLEAR_MM = 35.0


def _target_map_sites(config: dict) -> list[str]:
    sites = config.get("calibrate", {}).get("map_sites") or ["floor", "pinky", "belt"]
    configured = config.get("sites") or {}
    return [s for s in sites if s in configured]


def site_obstacle_mm(config: dict, depth, colour) -> dict:
    """Measure depth against every mapped site's configured ROI."""
    sites = config.get("calibrate", {}).get("map_sites") or _target_map_sites(config)
    return rd.site_obstacle_mm(config.get("sites") or {}, sites, depth, colour)


def resolve_z_view(config: dict, *, obstacle_mm: float | None = None, clear_mm: float = REMAP_CLEAR_MM) -> tuple[dict, dict]:
    """Raise coarse.z_view (never lower) to clear `obstacle_mm` by `clear_mm` above the table plane."""
    base_z = float(config["coarse"]["z_view"])
    info = {"base_z_view": base_z, "z_view": base_z, "obstacle_mm": obstacle_mm, "clear_mm": float(clear_mm), "raised": False}
    if obstacle_mm is None or isinstance(obstacle_mm, bool) or not math.isfinite(float(obstacle_mm)) or float(obstacle_mm) <= 0.0:
        return config, info
    obs = float(obstacle_mm)
    target_sites = set(_target_map_sites(config))
    configured = config.get("sites") or {}
    surface_zs = [
        float(site["surface_z"])
        for name, site in configured.items()
        if (not target_sites or name in target_sites)
        and isinstance(site, dict)
        and isinstance(site.get("surface_z"), (int, float))
        and not isinstance(site.get("surface_z"), bool)
        and math.isfinite(float(site["surface_z"]))
    ]
    table_zs = [z for z in surface_zs if -0.025 <= z <= 0.0]
    table_z = max(table_zs) if table_zs else 0.0
    req_z = round(table_z + (obs + float(clear_mm)) / 1000.0, 4)
    eff_z = max(base_z, req_z)
    raised = eff_z > base_z + 1e-6
    info.update({"z_view": eff_z, "obstacle_mm": round(obs, 1), "required_z_view": req_z, "table_z_m": round(table_z, 4), "raised": raised})
    if not raised:
        return config, info
    eff_cfg = {**config, "coarse": {**config["coarse"], "z_view": eff_z}}
    return eff_cfg, info


def plan_only(config: dict, points: list, obstacle_mm: float | None = None) -> dict:
    """What `--plan-only` prints: every point's IK row, the refusal, the reach note, the plan leverage and the z_view record."""
    import cell_map_fit

    view, info = resolve_z_view(config, obstacle_mm=obstacle_mm) if obstacle_mm is not None else (config, None)
    rows = plan(view, points)
    return {"plan_only": rows, "refused": refusal(rows), "reach": reach_note(view),
            "leverage": cell_map_fit.plan_leverage(points, view.get("sites") or {}), **({"z_view": info} if info else {})}


def remap_view(config: dict, colour, obstacle_mm: float | None = None, depth_capture=None) -> tuple[dict, dict]:
    """The config a remap moves with, and its z_view record: `obstacle_mm` when given, else what the D435 sees above the map sites.

    Invalid depth or coverage at a remap site is recorded as `depth_error` and leaves the configured z_view;
    cell_calibrate refuses a remap on it before any move unless `--obstacle-mm` was given."""
    extra: dict = {}
    if obstacle_mm is None and depth_capture is not None:
        import cell_cal_eval

        if cell_cal_eval.top_has_depth(config):
            try:
                meta = site_obstacle_mm(config, depth_capture(), colour)  # raises without a frame or with a loose alignment
                obstacle_mm = meta["obstacle_mm"]
                extra.update(sites_mm=meta["sites_mm"], edge_px=meta["edge_px"], plane_nz=meta.get("plane_nz"))
            except (OSError, RuntimeError, ValueError) as exc:
                extra["depth_error"] = str(exc)
    view, info = resolve_z_view(config, obstacle_mm=obstacle_mm)
    return view, {**info, **extra}

MAP_POINTS = [
    [-0.12, 0.17], [-0.10, 0.19], [-0.08, 0.17], [-0.06, 0.19], [-0.04, 0.17], [-0.10, 0.15],
    [-0.06, 0.15], [-0.02, 0.19], [0.02, 0.19], [0.066, 0.195], [0.06, 0.18], [0.04, 0.17],
]  # the 2026-10-28 remap grid


def record_stop(status, command, point, *, speed, log, at_stop, timeout):
    """Record the triggering command before folding; a stuck camera must not delay the fold."""
    import threading

    keys = ("t", "target", "health", "contact", "strain_sample", "fault", "trace_receipt", "library_sha256")
    log({"point": point, "stopped": command, "error": status.get("error"), "state": status.get("state"),
         "transit_speed": speed, "runner_session": (status.get("operating_context") or {}).get("session_id"),
         "runner": {key: status[key] for key in keys if key in status}})
    if at_stop is None:
        return

    def grab():
        try:
            at_stop(status.get("state"), status)
        except BaseException:
            pass

    grabber = threading.Thread(target=grab, daemon=True)
    grabber.start()
    grabber.join(timeout=timeout)


def plan_report(config, points):
    import cell_map_fit

    rows = plan(config, points)
    return {"plan_only": rows, "refused": refusal(rows), "reach": reach_note(config),
            "leverage": cell_map_fit.plan_leverage(points, config.get("sites") or {})}


def scoped(config: dict) -> dict:
    scoped_config = dict(config, played_chunks=list(PLAYED))
    calibration = config.get("calibrate") or {}
    if "remap_transit_speed" in calibration:
        from chunk_runner_guards import library_transit_speed

        speed = library_transit_speed({"transit_speed": calibration["remap_transit_speed"]})
        if speed > library_transit_speed(config["plan"]):
            raise ValueError("remap_transit_speed exceeds the arm's transit_speed")
        scoped_config["plan"] = dict(config["plan"], transit_speed=speed)
    return scoped_config


def visit_order(points: list) -> list:
    """The point nearest the base first, then always the nearest point not yet visited.

    2026-11-26 arm_a: ordered by distance from the base alone, 6 of 18 moves crossed the grid (80-105 s each at
    remap_transit_speed 0.2) and took half of the 19 min remap."""
    left = sorted(points, key=lambda q: math.hypot(*q))
    order = left[:1]
    del left[:1]
    while left:  # by position, so a repeated point is visited as often as it is listed
        here = order[-1]
        order.append(left.pop(min(range(len(left)), key=lambda i: math.hypot(left[i][0] - here[0], left[i][1] - here[1]))))
    return order


def scene_ignore(config: dict) -> list:
    """Rects the remap's folded before/after comparison skips: moving sites, `scene_ignore_px`, and
    `calibrate.scene_ignore_px`, the folded arm's own links and cables, which park a few px apart
    (2026-11-24..26 arm_s: 4 of 9 remaps lost to 160-400 px blobs on its own body)."""
    import cell_scene_guard

    return [*cell_scene_guard.moving_rects(config), *(config.get("scene_ignore_px") or ()),
            *((config.get("calibrate") or {}).get("scene_ignore_px") or ())]


def view(config: dict, x: float, y: float) -> dict:
    sites = config.get("calibrate", {}).get("map_sites") or ["floor", "pinky", "belt"]
    site = next(s for s in sites if s in config["sites"])
    return {"x": x, "y": y, "z": round(config["coarse"]["z_view"] - config["plan"]["approach_m"], 4),
            "yaw_deg": config["sites"][site]["yaw_deg"]}


def reach_note(config: dict) -> str:
    limit = config.get("calibrate", {}).get("max_reach_m")
    return "no reach check" if limit is None else f"max_reach_m {limit}"


def plan(config: dict, points: list) -> list:
    """One row per point in visit order: the above_pick joints, and the error that would refuse it."""
    rows, cfg = [], scoped(config)
    limit = config.get("calibrate", {}).get("max_reach_m")
    for x, y in visit_order(points):
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


def measured_tcp_yaw(cell, config: dict, lib: Path | None, planned_xy) -> tuple[float, float, float | None, float | None]:
    """Measured (fk_x, fk_y, fk_z, fk_yaw) from live joint state, else planned fallback."""
    import cell_pivot, omx_tcp

    try:
        res = cell.act("state") if cell is not None else None
        state = res.get("state") if isinstance(res, dict) and res.get("ok") else None
        if isinstance(state, (list, tuple)) and len(state) >= 5:
            tcp_x_m = omx_tcp.config_tcp(config, config.get("plan"))
            fk = cell_pivot.joints_tcp(state, **({"tcp_x_m": tcp_x_m} if tcp_x_m is not None else {}))
            if len(fk) >= 4 and all(isinstance(v, (int, float)) and math.isfinite(float(v)) for v in fk[:4]):
                return float(fk[0]), float(fk[1]), float(fk[2]), float(fk[3])
    except (ImportError, OSError, KeyError, IndexError, TypeError, ValueError, RuntimeError, SystemExit):
        pass
    yaw = planned_yaw(lib, config) if lib is not None else None
    return float(planned_xy[0]), float(planned_xy[1]), None, yaw


def live_fk_yaw(cell, config: dict, fallback_yaw: float) -> float:
    """Live FK yaw from `cell.act("state")` when available, else `fallback_yaw`."""
    yaw = measured_tcp_yaw(cell, config, None, (0.0, 0.0))[3]
    return float(fallback_yaw) if yaw is None else yaw


def missing_maps(config: dict, calibration: dict, sites) -> list:
    """Sites to remap: no map, or a one-jaw map while the config asks for a TCP map (calibrate.tcp_marks).
    2026-11-17 arm_a: its 11-15 map followed one jaw, so every TCP pivot carried ~28 mm and failed max_bias_mm."""
    tcp = bool((config.get("calibrate") or {}).get("tcp_marks"))
    have = calibration.get("sites", {})
    return [s for s in sites if s not in have or (tcp and have[s].get("marks") != "tcp")]


OBSERVATIONS_SCHEMA = "rosy.omx-remap-observations.v1"


def _finite_num(raw, label: str) -> float:
    if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not math.isfinite(float(raw)):
        raise SystemExit(f"replay: invalid {label}")
    return float(raw)


def _finite_pair(raw, label: str) -> tuple[float, float]:
    if not isinstance(raw, (list, tuple)) or len(raw) != 2:
        raise SystemExit(f"replay: invalid {label}")
    return (_finite_num(raw[0], label), _finite_num(raw[1], label))


def save_observations(
    frames_dir: Path,
    *,
    z_view: float,
    tcp_marks: bool,
    marks: list,
    seen_jaws: list,
    scene_moved=None,
) -> Path:
    """Persist raw remap marks and jaw observations before any scene/jaw gate aborts, for offline replay."""
    out = Path(frames_dir) / "observations.json"
    payload = {
        "schema": OBSERVATIONS_SCHEMA,
        "z_view": float(z_view),
        "tcp_marks": bool(tcp_marks),
        "scene_moved": scene_moved,
        "marks": [{"pixel": [float(p[0]), float(p[1])], "arm_m": [float(a[0]), float(a[1])]} for p, a in marks],
        "seen_jaws": [
            {
                "tcp": [float(j["tcp"][0]), float(j["tcp"][1])],
                "yaw": float(j["yaw"]),
                "pixel": [float(j["pixel"][0]), float(j["pixel"][1])],
                "blobs": [[float(v) for v in b] for b in (j.get("blobs") or [])],
            }
            for j in seen_jaws
        ],
    }
    tmp = out.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    tmp.replace(out)
    return out


def fit_remap_marks(
    config: dict,
    z_view: float,
    *,
    tcp_marks: bool,
    marks: list,
    seen_jaws: list,
    frames_dir: Path | None = None,
    write_labels: bool = True,
    log=print,
) -> dict:
    """Label TCP jaws if requested, filter consensus marks, and fit the coarse calibration record."""
    import time
    import cell_params as prm
    from cell_intrinsics_frames import fitted_map
    from cell_map_fit import consensus, enough_agree

    if tcp_marks:  # each mark's arm point is the place of the jaw it is, so the map maps the TCP (jaws' middle)
        import cell_jaw_side

        why, marks, labels = cell_jaw_side.remap_marks(seen_jaws, config.get("params"))
        if write_labels and frames_dir is not None:
            (Path(frames_dir) / "labels.json").write_text(json.dumps({"why": why, **(labels or {})}), encoding="utf-8")
        log({"jaw_labels": labels, "refused": why})
        if why:
            where = f"; views in {frames_dir}" if frames_dir is not None else ""
            raise SystemExit(f"remap: {why}; no map saved{where}")
    seen, marks = list(marks), consensus(marks, prm.get(config.get("params"), "calibrate.consensus_px"))
    dropped = [{"pixel": list(p), "arm_m": list(a)} for p, a in seen if (p, a) not in marks]
    if dropped:
        log({"dropped_marks": dropped})
        if tcp_marks and len(seen_jaws) == len(seen):
            kept_set = set(marks)
            surviving_jaws = [j for m, j in zip(seen, seen_jaws) if m in kept_set]
            if len(surviving_jaws) >= 4:
                why, marks, labels = cell_jaw_side.remap_marks(surviving_jaws, config.get("params"))
                if write_labels and frames_dir is not None:
                    (Path(frames_dir) / "labels.json").write_text(json.dumps({"why": why, **(labels or {})}), encoding="utf-8")
                log({"jaw_labels": labels, "refused": why})
                if why:
                    where = f"; views in {frames_dir}" if frames_dir is not None else ""
                    raise SystemExit(f"remap: {why}; no map saved{where}")
    if not enough_agree(len(marks), len(seen)):
        raise SystemExit(f"remap: only {len(marks)} marks agree of {len(seen)}")
    return dict(fitted_map(config, marks, z_view), **{
        "z_view": z_view,
        "coarse": True,
        "dropped_marks": dropped,
        "points": [{"pixel": list(p), "arm_m": list(a)} for p, a in marks],
        "measured": time.strftime("%Y-%m-%dT%H:%M:%S"),
        **({"marks": "tcp"} if tcp_marks else {}),
    })


def fit_naming_stop(stop: str | None, config: dict, z_view: float, **kw) -> dict:
    """fit_remap_marks; a refusal after a stopped move also names the stop (2026-11-26 arm_a: four contact stops at
    the first point read only "remap: only 0 marks agree of 0")."""
    try:
        return fit_remap_marks(config, z_view, **kw)
    except SystemExit as exc:
        if stop is None:
            raise
        raise SystemExit(f"{stop}; {exc}") from exc


def replay_observations(frames_dir: Path, config: dict, *, log=print) -> dict:
    """Offline, read-only, fail-closed replay of a saved remap-frames directory under current config guards."""
    import cv2
    import cell_scene_guard

    frames = Path(frames_dir).expanduser()
    obs_path, before_path, after_path = frames / "observations.json", frames / "before.jpg", frames / "after.jpg"
    for p in (obs_path, before_path, after_path):
        if not p.is_file():
            raise SystemExit(f"replay: missing required artifact {p}")
    try:
        obs = json.loads(obs_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SystemExit(f"replay: unreadable {obs_path}: {exc}") from exc
    if not isinstance(obs, dict) or obs.get("schema") != OBSERVATIONS_SCHEMA:
        raise SystemExit(f"replay: {obs_path} schema {obs.get('schema') if isinstance(obs, dict) else None!r} != {OBSERVATIONS_SCHEMA!r}")
    z_view = _finite_num(obs.get("z_view"), "z_view")
    tcp_marks = obs.get("tcp_marks")
    if type(tcp_marks) is not bool:
        raise SystemExit("replay: invalid tcp_marks")
    if bool((config.get("calibrate") or {}).get("tcp_marks")) != tcp_marks:
        raise SystemExit(f"replay: config tcp_marks mismatch (saved={tcp_marks})")
    raw_marks, raw_jaws = obs.get("marks"), obs.get("seen_jaws")
    if not isinstance(raw_marks, list) or not isinstance(raw_jaws, list):
        raise SystemExit("replay: marks and seen_jaws must be lists")
    before, after = cv2.imread(str(before_path)), cv2.imread(str(after_path))
    if before is None or after is None:
        raise SystemExit(f"replay: unreadable before/after images in {frames}")
    moved = cell_scene_guard.scene_moved(before, after, ignore=scene_ignore(config))
    if moved:
        raise SystemExit(f"replay: the scene changed during it, no map saved: {moved}; views in {frames}")
    marks = []
    for item in raw_marks:
        if not isinstance(item, dict):
            raise SystemExit("replay: invalid mark entry")
        marks.append((_finite_pair(item.get("pixel"), "mark.pixel"), _finite_pair(item.get("arm_m"), "mark.arm_m")))
    seen_jaws = []
    for jaw in raw_jaws:
        if not isinstance(jaw, dict):
            raise SystemExit("replay: invalid seen_jaws entry")
        raw_blobs = jaw.get("blobs") if jaw.get("blobs") is not None else []
        if not isinstance(raw_blobs, list):
            raise SystemExit("replay: invalid seen_jaws.blobs")
        blobs = []
        for blob in raw_blobs:
            if not isinstance(blob, list) or len(blob) < 2:
                raise SystemExit("replay: invalid blob entry")
            blobs.append([_finite_num(v, "blob") for v in blob])
        seen_jaws.append({
            "tcp": _finite_pair(jaw.get("tcp"), "jaw.tcp"),
            "yaw": _finite_num(jaw.get("yaw"), "jaw.yaw"),
            "pixel": _finite_pair(jaw.get("pixel"), "jaw.pixel"),
            "blobs": blobs,
        })
    if tcp_marks and not seen_jaws:
        raise SystemExit("replay: tcp_marks=True observation has no seen_jaws")
    return fit_remap_marks(
        config, z_view, tcp_marks=tcp_marks, marks=marks, seen_jaws=seen_jaws,
        frames_dir=frames, write_labels=False, log=log,
    )
