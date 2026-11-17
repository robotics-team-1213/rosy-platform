#!/usr/bin/env python3
"""Feel instead of look: when a grasp comes up empty, try again shifted along the closing axis and let the gripper's
own holding verdict decide (2026-10-29). Needs no camera, holds for any box size; the camera-based check is cell_pinch.
"""
from __future__ import annotations

import math
from pathlib import Path

import cell_params as prm


def feel_hook(config: dict, cell, target: dict, write_library):
    """Feel instead of look (feel.enabled): an empty grasp tries again shifted along the closing axis by +s, -s, +2s,
    -2s (feel.step_mm, feel.tries), each a lift, a re-plan, a descent and a grasp; the gripper's own holding verdict
    decides, for any box size. 2026-10-29: the floor 1-cell came up empty with the box 1-2 cm outside one finger while
    the wrist camera, turned away, could not see the fingers. Each descent follows the same reach correction as the
    first: without it the descent started with little lag, the runner's contact limit stayed at 1.5 and the normal
    descent lag of 1.6-1.7 read as a contact six times in a row, where the first descent peaked at 1.9 untouched
    (2026-10-29). Returns run -> last status, or None when off."""
    import cell_reach

    params = config.get("params")
    if not prm.get(params, "feel.enabled"):
        return None
    work = Path(config["work_dir"]).expanduser()
    step = prm.get(params, "feel.step_mm")
    z_step = prm.get(params, "feel.z_step_mm")
    site_z = float(((config.get("sites") or {}).get(target["pick"].get("site"), {}) or {}).get("surface_z", -0.030))
    z_min = float((config.get("plan") or {}).get("workspace_min_m", [0.0, 0.0, site_z + 0.005])[2])
    offsets = [k * step * sgn for k in (1, 2, 3) for sgn in (1, -1)][:int(prm.get(params, "feel.tries"))]
    candidates = ([(0.0, -z_step), (0.0, -round(1.6 * z_step, 1))] + [(off, -z_step) for off in offsets]
                  if z_step > 0 else [(off, 0.0) for off in offsets])[:max(int(prm.get(params, "feel.tries")), 1 if z_step > 0 else 0)]

    def search(run):
        import cell_arm_cal

        base_pick = dict(target["pick"])
        c = math.radians(base_pick["yaw_deg"] + prm.get(params, "auto.closing_theory_deg"))
        status = {"ok": True, "holding": False}
        for k, (off, dz_mm) in enumerate(candidates):
            pick = dict(base_pick, x=round(base_pick["x"] + off * math.cos(c) / 1000, 4),
                        y=round(base_pick["y"] + off * math.sin(c) / 1000, 4),
                        z=max(z_min, round(base_pick["z"] + dz_mm / 1000, 4)))
            library = write_library(config, pick, target["place"], work / f"feel-{k}.json")
            reach_target = dict(target, pick=pick)
            reach = cell_reach.hook(config, cell, reach_target, write_library)
            for command in ("run lift_pick", f"load {library}", "goto above_pick", "reach", "run descend_pick", "run grasp_pick"):
                if command == "reach":
                    if reach is not None and reach()["verdict"] == "refuse":
                        if z_step > 0:
                            continue
                        return {"ok": False, "error": "reach correction refused", "feel_mm": off, "feel_dz_mm": dz_mm}
                    pick = dict(reach_target["pick"])
                    continue
                status = run(command)
                if command == "run descend_pick" and status.get("contact") and (status.get("contact_z") is not None or status.get("state")) and z_step > 0:
                    if status.get("contact_z") is not None:
                        contact_z = float(status["contact_z"])
                    else:
                        import grasp_planner as gp

                        plan_cfg = config.get("plan") or {}
                        tcp_x = config.get("tcp_x_m") if config.get("tcp_x_m") is not None else plan_cfg.get("tcp_x_m")
                        kin = gp.load_kinematics(plan_cfg.get("urdf_path"), tcp_x_m=tcp_x)[0]
                        contact_z = kin.fk([gp.norm_to_rad(v) for v in status["state"][:5]]).z
                    run("retreat")
                    pick = dict(pick, z=max(z_min, round(contact_z + 0.004, 4)))
                    library = write_library(config, pick, target["place"], work / f"feel-{k}-contact.json")
                    for retry_cmd in (f"load {library}", "goto above_pick", "run descend_pick"):
                        status = run(retry_cmd)
                        if status.get("contact") or not status.get("ok"):
                            break
                if status.get("contact") or not status.get("ok"):
                    return {**status, "feel_mm": off, "feel_dz_mm": dz_mm}
            if not status.get("holding") and "plan" in config:
                cell_arm_cal.infer_holding(status, closed=config["plan"]["grip_closed"])
            if status.get("holding"):
                target["pick"] = pick
                return {**status, "feel_mm": off, "feel_dz_mm": round((pick["z"] - base_pick["z"]) * 1000, 1)}
        return status
    return search
