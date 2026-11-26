#!/usr/bin/env python3
"""Measure a site's surface height by touch: closed jaws go straight down over the site until the runner's soft
contact holds them, the held pose's FK z is the surface, then back out and fold home. No contact before `z_to` is
a refusal (nothing there, or the site is lower than thought). Placing needs `surface_z`; the belt and Pinky sites
only had grasp heights taught for another box (2026-10-28).

  cell_surface.py --config cell-auto.json --site belt [--z-from 0.10 --z-to 0.010] [--write]
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cell_pipeline as cp  # noqa: E402
from cell_route_surface import contact_binding, contact_evidence, probe_binding  # noqa: E402


def probe_library(plan: dict, x: float, y: float, yaw: float, z_from: float, z_to: float, tcp_x_m: float | None = None) -> dict:
    from grasp_planner import NAMES, Planner, norm_to_rad

    z_from = max(z_to + 0.05, min(z_from, z_to + 0.08))
    p = dict(plan, **({"tcp_x_m": tcp_x_m} if tcp_x_m is not None else {}))
    planner = Planner(p)
    q5 = norm_to_rad(p["home"][4])
    frames, _ = planner.line((x, y, z_from), (x, y, z_to), 0.003, yaw, p["grip_closed"], q5)
    home = [round(v, 3) for v in p["home"]] + [p["grip_closed"]]
    return {"schema": "rosy.omx-chunk-library.v1", "names": NAMES, "fps": p["fps"],
            "chunks": {"above_probe": [frames[0]], "descend_probe": frames, "home": [home]},
            "gripper_closed": p["grip_closed"], "transit": p.get("transit", {}),
            "transit_speed": p.get("transit_speed", 0.85)}


def fk_z(state: list, tcp_x_m: float | None = None) -> float:
    from grasp_planner import load_kinematics, norm_to_rad

    kin, _, _ = load_kinematics(None, tcp_x_m)
    return kin.fk([norm_to_rad(v) for v in state[:5]]).z


def touch(cell, library_path: Path, fk=fk_z, tcp_x_m: float | None = None, repeat: int = 1) -> dict:
    """goto above, descend (repeated `repeat` times); a contact hold is the surface. Always ends folded home."""
    steps, touches, last_err = [], [], None
    for command in (f"load {library_path}", "goto above_probe"):
        status = cell.act(command)
        steps.append({"command": command, **{k: status.get(k) for k in cp.STEP_KEYS}})
        if status.get("contact"):
            for after in ("retreat", "park"):
                steps.append({"command": after, "ok": cell.act(after).get("ok")})
            return {"result": "refused", "at": command, "error": "contact before probe descent", "steps": steps}
        if not status.get("ok"):
            if not status.get("fault") and not command.startswith("load"):
                steps.append({"command": "park", "ok": cell.act("park").get("ok")})
            return {"result": "fault" if status.get("fault") else "refused", "at": command, "steps": steps}
    n_rep = max(1, int(repeat))
    for idx in range(n_rep):
        status = cell.act("run descend_probe")
        steps.append({"command": "run descend_probe", **{k: status.get(k) for k in cp.STEP_KEYS}})
        if status.get("contact") and not status.get("fault"):
            z = fk(status["state"], tcp_x_m) if fk is fk_z else fk(status["state"])
            touches.append(z)
            last_err = status.get("error")
            ret = cell.act("retreat")
            steps.append({"command": "retreat", "ok": ret.get("ok")})
            if not ret.get("ok"):
                steps.append({"command": "park", "ok": cell.act("park").get("ok")})
                return {"result": "fault" if ret.get("fault") else "refused", "at": "retreat", "steps": steps}
            continue
        if not status.get("ok"):
            if not status.get("fault"):
                steps.append({"command": "park", "ok": cell.act("park").get("ok")})
            return {"result": "fault" if status.get("fault") else "refused", "at": "run descend_probe", "steps": steps}
        steps.append({"command": "park", "ok": cell.act("park").get("ok")})
        return {"result": "no contact", "steps": steps}
    park = cell.act("park")
    steps.append({"command": "park", "ok": park.get("ok")})
    if not park.get("ok"):
        return {"result": "fault" if park.get("fault") else "refused", "at": "park", "steps": steps}
    if n_rep == 1:
        return {"result": "touched", "surface_z": round(touches[0], 4), "error": last_err, "steps": steps}
    spread_mm = round((max(touches) - min(touches)) * 1000.0, 2)
    touches_r = [round(t, 4) for t in touches]
    if max(touches) - min(touches) > 0.0015:
        return {"result": "unrepeatable", "touches_m": touches_r, "spread_mm": spread_mm, "steps": steps}
    return {"result": "touched", "surface_z": round(sum(touches) / len(touches), 4),
            "touches_m": touches_r, "spread_mm": spread_mm, "error": last_err, "steps": steps}


def _finite_num(value) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    f = float(value)
    return f if math.isfinite(f) else None


def _valid_xy(pair) -> tuple[float, float] | None:
    if not isinstance(pair, (list, tuple)) or len(pair) != 2:
        return None
    x, y = _finite_num(pair[0]), _finite_num(pair[1])
    return (x, y) if x is not None and y is not None else None


def validated_probe_z_to(config: dict, site_cfg: dict) -> tuple[float | None, str | None]:
    """Return ``(probe_z_to, error)``; negative probes match ``grasp_planner.limits_at`` first-match ``low_zones``."""
    raw_z_to = site_cfg.get("probe_z_to_m", 0.010)
    probe_z_to = _finite_num(raw_z_to)
    if probe_z_to is None or not (-0.12 <= probe_z_to < 0.10):
        return None, f"invalid probe_z_to_m: {raw_z_to!r}"
    if probe_z_to < 0.010:
        xy = _valid_xy(site_cfg.get("place"))
        if xy is None:
            return None, f"invalid place: {site_cfg.get('place')!r}"
        plan = config.get("plan")
        limits = plan.get("limits") if isinstance(plan, dict) else None
        low_zones = limits.get("low_zones") if isinstance(limits, dict) else None
        if not isinstance(low_zones, (list, tuple)):
            return None, "invalid low_zones"
        px, py = xy
        for zone in low_zones:
            if not isinstance(zone, dict):
                return None, "invalid low_zones entry"
            xr, yr, z_min = _valid_xy(zone.get("x")), _valid_xy(zone.get("y")), _finite_num(zone.get("z_min_m"))
            if xr is None or yr is None or z_min is None:
                return None, "invalid low_zones entry"
            if xr[0] <= px <= xr[1] and yr[0] <= py <= yr[1]:
                return (probe_z_to, None) if z_min <= probe_z_to else (None, f"probe_z_to_m {probe_z_to} outside low_zones")
        return None, f"probe_z_to_m {probe_z_to} outside low_zones"
    return probe_z_to, None


def surface_selection_error(config, calibration, found, name):
    import omx_tcp
    from cell_recovery_cargo import fixed_base_geometry, fixed_site

    site = (config.get("sites") or {}).get(name)
    if (not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_-]*(?::[A-Za-z0-9_-]+)?", name)
            or not fixed_base_geometry(site) or not fixed_site(name, config.get("arm_id"))):
        return "registered fixed surface site required"
    if (found.get("camera_issue") or found.get("camera_moved") or found.get("map_binding_error")
            or (found.get("camera_shift") or {}).get("ok") is not True):
        return "current camera alignment and bound map required"
    mapped = calibration.get("sites") or {}
    parent = site.get("map_from", name)
    missing = found.get("missing_map") or []
    if not (mapped.get(name) or mapped.get(parent)) or name in missing or parent in missing:
        return "selected site's map is missing"
    if not contact_binding(config, name, calibration, omx_tcp.config_tcp(config)):
        return "surface contact cannot be bound to this arm, target, TCP and map"
    return None


def remeasure_surface(cell, config, calibration, step, work):
    from cell_bound_home_placement import _empty, _pose
    from cell_envelope import _state_current
    from cell_robot_profile import load

    profile = config.get("operating_profile_path")
    if not profile:
        return {step: "operating profile unavailable"}
    cell.operating_profile = load(Path(profile).expanduser())["binding"]
    state = cell.act("state")
    if (not _state_current(state, time.time()) or state["operating_context"].get("scope") != "hardware"
            or state["operating_context"].get("operating_profile") != cell.operating_profile
            or state.get("human_hold_latched") is not False or not _pose(state.get("state"))
            or not _empty(state, config["plan"]["grip_closed"])):
        return {step: "fresh empty gripper on the selected arm required"}
    res = run_surface_step(cell, config, step, work)
    if res.get(step) == "touched":
        evidence = contact_evidence(config, step.split()[1], calibration)
        if evidence["status"] != "matched_contact":
            return {step: evidence["reason"]}
        res["contact"] = evidence
    return res


def run_surface_step(cell, config: dict, step: str, work: Path, *, repeat: int = 2) -> dict:
    """Execute one ``surface <site>`` calibration step with low-zone Z gating."""
    import omx_tcp

    site = step.split()[1]
    s = config["sites"].get(site)
    if not isinstance(s, dict) or not s.get("place"):
        return {step: "no place point to touch"}
    xy = _valid_xy(s.get("place"))
    if xy is None:
        return {step: f"invalid place: {s.get('place')!r}"}
    yaw = _finite_num(s.get("yaw_deg"))
    if yaw is None:
        return {step: f"invalid yaw_deg: {s.get('yaw_deg')!r}"}
    probe_z_to, z_err = validated_probe_z_to(config, s)
    if z_err:
        return {step: z_err}
    tcp_x_m = omx_tcp.config_tcp(config, config["plan"])
    lib = work / f"surface-{site}.library.json"
    lib.write_text(json.dumps(probe_library(
        config["plan"], xy[0], xy[1], yaw, 0.10, probe_z_to, tcp_x_m=tcp_x_m)))
    binding = probe_binding(config, site, tcp_x_m)
    touched = touch(cell, lib, tcp_x_m=tcp_x_m, repeat=repeat)
    if touched["result"] == "touched":
        s["surface_z"] = touched["surface_z"]
    if config.get("work_dir"):
        rcp = Path(config["work_dir"]).expanduser() / f"surface-{site}.json"
        rtmp = rcp.with_suffix(".tmp")
        rtmp.write_text(json.dumps({"result": touched["result"], "surface_z": touched.get("surface_z"), "site": site,
                                    "xy": [xy[0], xy[1]], "measured": time.strftime("%Y-%m-%d %H:%M"),
                                    "contact_binding": binding,
                                    **({"touches_m": touched["touches_m"], "spread_mm": touched["spread_mm"]}
                                       if "touches_m" in touched else {}),
                                    "sets_surface_z": touched["result"] == "touched"}, indent=1), encoding="utf-8")
        rtmp.replace(rcp)
    return {step: touched["result"], "surface_z": touched.get("surface_z")}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--config", required=True, type=Path)
    ap.add_argument("--site", required=True)
    ap.add_argument("--z-from", type=float, default=0.10)
    ap.add_argument("--z-to", type=float, default=None)
    ap.add_argument("--repeat", type=int, default=2)
    ap.add_argument("--write", action="store_true", help="store the measured surface_z in the config's site")
    ap.add_argument("--commissioning", action="store_true", help="arm moves near fixtures during calibration")
    ap.add_argument("--person-at-switch", action="store_true", help="operator at the e-stop switch (D-911)")
    args = ap.parse_args(argv)
    if not (args.commissioning and args.person_at_switch):
        print(json.dumps({"held": "supervised commissioning required (--commissioning --person-at-switch)"}))
        return 2
    config = json.loads(args.config.read_text(encoding="utf-8"))
    plan = json.loads(Path(config["plan_path"]).expanduser().read_text())
    import omx_tcp

    tcp_x_m = omx_tcp.config_tcp(config, plan)
    site = config["sites"][args.site]
    site_copy = {**site, **({"probe_z_to_m": args.z_to} if args.z_to is not None else {})}
    z_to, z_err = validated_probe_z_to({**config, "plan": plan}, site_copy)
    if z_err:
        print(json.dumps({"result": "refused", "error": z_err, "site": args.site}))
        return 1
    x, y = site["place"]
    work = Path(config["work_dir"]).expanduser()
    path = work / f"surface-{args.site}.library.json"
    path.write_text(json.dumps(probe_library(plan, x, y, site["yaw_deg"], args.z_from, z_to, tcp_x_m=tcp_x_m)))
    cell = cp.FifoCell(Path(config["io"]).expanduser(), config["cameras"])
    binding = probe_binding(config, args.site, tcp_x_m)
    out = dict(touch(cell, path, tcp_x_m=tcp_x_m, repeat=args.repeat), site=args.site, xy=[x, y],
               contact_binding=binding, measured=time.strftime("%Y-%m-%d %H:%M"))
    out["sets_surface_z"] = out["result"] == "touched"  # the receipt cell_site_register reads as Z evidence
    (work / f"surface-{args.site}.json").write_text(json.dumps(out, indent=1))
    if args.write and out["result"] == "touched":
        site["surface_z"] = out["surface_z"]
        import cell_config_io
        if err := cell_config_io.write_config_checked(args.config, config, 1, [{f"surface {args.site}": "touched", "surface_z": out["surface_z"]}]):
            print(json.dumps({"result": "touched", "config_write_failed": err, "site": args.site}))
            return 2
    print(json.dumps({k: v for k, v in out.items() if k != "steps"}))
    return 0 if out["result"] == "touched" else 1


if __name__ == "__main__":
    sys.exit(main())
