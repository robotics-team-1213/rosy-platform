#!/usr/bin/env python3
"""Return-held handler: place an object already held at home onto a destination without picking."""
from __future__ import annotations

import json
import math
from pathlib import Path
import time
import uuid

import cell_attempts
import cell_auto_evidence
import cell_hooks
import cell_objects
import cell_params as prm
import cell_pipeline as cp
import cell_pivot
import cell_place_fit
from cell_pick_geom import across, grasp_depth, jaw_open_for, parse_dest, surface_z
from cell_transfer import RETURN_HELD


def _cap():
    import cell_auto_pick
    return cell_auto_pick


def _plan_return_held(config, entry, dest_site, place_xy, work: Path):
    height = entry["top_height_mm"] / 1000 - grasp_depth(config, dest_site)
    s = config["sites"][dest_site]
    place = {
        "x": place_xy[0],
        "y": place_xy[1],
        "z": round(surface_z(config, dest_site) + height + s.get("place_dz", 0.0), 4),
        "yaw_deg": s["yaw_deg"],
    }
    jaws = jaw_open_for(across(entry), config.get("params"))
    plan_cfg = dict(config, played_chunks=["above_place", "descend_place", "release_place", "lift_place", "home"])
    error = "no plan"
    for approach in (config["plan"]["approach_m"], prm.get(config.get("params"), "auto.approach_near_m", 0.020)):
        try:
            lib = cp.write_library(
                dict(plan_cfg, plan=dict(config["plan"], approach_m=approach, grip_open=jaws)),
                dict(place),
                place,
                work / f"return-held-{dest_site}.json",
            )
            lib_data = json.loads(Path(lib).read_text(encoding="utf-8"))
            lib_data["holding"] = True
            Path(lib).write_text(json.dumps(lib_data, indent=1), encoding="utf-8")
            return lib, place, approach, jaws, None
        except SystemExit as exc:
            error = str(exc)[:160]
    return None, place, None, jaws, error


def run_return_held(
    cell,
    config,
    calibration,
    calibration_path,
    catalog,
    roi,
    dest,
    work: Path,
    dry_run=False,
    sleep=time.sleep,
    object_id=None,
) -> dict:
    """Arm already holds an object at home: place it onto `dest` without picking, then fold home."""
    cap = _cap()
    work, out = Path(work), {"to": dest, "mode": "return_held"}
    config, calibration = cell_place_fit.with_tiers(config, calibration, catalog)
    base_site = dest if dest in config["sites"] else next(iter(config["sites"]))
    dest_site, place_xy = parse_dest(config, base_site, dest)
    if dest_site not in config["sites"] or "place" not in config["sites"][dest_site]:
        return {**out, "result": f"refused: {dest} is not a destination (its site has no 'place')"}
    obj_id = object_id or (config.get("want") or {}).get("object") or catalog[0]["id"]
    entry = next((e for e in catalog if e["id"] == obj_id), None)
    if entry is None:
        return {**out, "result": f"refused: object {obj_id!r} not in catalogue"}
    map_error = cap.cell_auto_evidence.map_pose_preflight(cell, config, calibration, calibration_path, work, dry_run, out)
    if map_error:
        return {**out, "result": f"held: {map_error}"}
    config, roi, track_error = cap.cell_auto_evidence.track_sites(
        cell, config, calibration, dest_site, dest_site, roi, work, dry_run, out
    )
    if track_error:
        return {**out, "result": track_error}
    lib, place, approach, jaws, error = _plan_return_held(config, entry, dest_site, place_xy, work)
    if error:
        return {**out, "result": f"stopped: {error}", "plan": {"place": place, "grip_open": jaws}}
    out["plan"] = {"place": place, "approach_m": approach, "grip_open": jaws, "library": str(lib)}
    if dry_run:
        return {**out, "result": "planned"}
    guarded = cap.Guarded(cell, config)
    if not cell.act("state").get("ok"):
        return {**out, "result": "refused", "error": "start record_session.py --chunks first: no chunk_runner answers"}
    droi = config["sites"][dest_site].get("auto_roi") or roi
    bias_data = cell_place_fit.with_tier_biases(
        config, cell_pivot.load_bias(cell_pivot.bias_path(calibration_path), config.get("params"))
    )
    before_frame, _, src_err = cap.cell_auto_evidence.source_frame(
        cell, work / "frames" / f"{uuid.uuid4().hex}-before.jpg"
    )
    if before_frame is not None and cell_pivot.map_record(calibration, dest_site):
        _, _, present_dest, obs_err = cap.observe(
            cell, config, calibration, dest_site, droi, catalog, image=before_frame["image"]
        )
        region = cell_pivot.bias_at(bias_data, dest_site, place_xy, params=config.get("params"))
        bx, by = region["bias_mm"] if region else (0.0, 0.0)
        tol = config.get("verify_tol_mm", 10.0)
        if not obs_err and any(
            1000 * math.dist((o["raw_m"][0] - bx / 1000, o["raw_m"][1] - by / 1000), place_xy) <= tol
            for o in present_dest
        ):
            return {**out, "result": "held: destination unavailable or occupied"}
    elif src_err:
        return {**out, "result": f"held: {src_err}"}
    config = dict(config, _payload=cell_objects.payload(catalog, obj_id))
    episode = cap.open_episode(cell, config, dest_site, dest, obj_id)
    gate = cap.Gate(guarded, config, calibration, sequence=RETURN_HELD)
    tried, t0, opened = {"locate": {"found": True}, "object": obj_id, "plan": out["plan"]}, time.time(), False
    try:
        held = gate.open(lib, lambda a: cap.cell_attempts.begin(config, a), lambda *_, **__: None)
        if held is not None:
            cap.close_episode(cell, episode, False, f"held: {held['reason']}")
            return {**out, "result": f"held: {held['reason']}", "envelope": held}
        opened = True
        moved = cap.transfer_folded(
            gate, lib, sequence=RETURN_HELD,
            lift_stall=cell_hooks.lift_stall(cell, config, sleep),
            at_stop=cell_hooks.stills(cell, config),
        )
        tried["envelope"], tried["transfer"] = gate.assessment, moved
        verify = None
        if moved["result"] == "placed":
            verify = cap.verify_placed(
                guarded, config, calibration, dest_site, place_xy, droi, catalog, bias_data, obj_id,
                before_frame, work / "frames" / f"{uuid.uuid4().hex}-after.jpg",
                dest_site, (float("nan"), float("nan")), droi,
            )
            tried["verify"] = verify
        cap.close_episode(cell, episode, moved["result"] == "placed", moved["result"])
        episode = None
        cap.cell_attempts.record(config, calibration, "held", dest, 1, tried, t0)
        if moved["result"] in ("fault", "refused") and not gate.blocked:
            cp.fold(gate, sleep)
        return {**out, "result": moved["result"], "transfer": moved, **({"verify": verify} if verify else {})}
    except cap.Aborted as stop:
        cap.close_episode(cell, episode, False, f"aborted: {stop}")
        if opened:
            tried["transfer"] = {"result": "aborted", "error": str(stop), "steps": []}
            cap.cell_attempts.record(config, calibration, "held", dest, 1, tried, t0)
        return {**out, "result": f"aborted: {stop}"}
    except Exception:
        if not gate.blocked:
            cp.fold(gate, sleep)
        cap.close_episode(cell, episode, False, "pipeline exception")
        raise
