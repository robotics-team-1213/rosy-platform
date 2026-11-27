"""Associate an observed catalog object with its checked hardware grasp acknowledgment."""
import json
import math
import time
from pathlib import Path

from omx_incident_reading import rows
from cell_route_check import _finite


_FILE = "recovery-grasp.json"
MAX_HEIGHT_RESIDUAL_MM = 1.5


def fixed_site(name, arm):
    if name in ("floor", "board"):
        return arm in ("arm_s", "arm_a", "arm_b")
    if arm not in ("arm_a", "arm_b"):
        return False
    try:
        from cell_site_target import designated_slot_arms, resolve_cell_ab_site
        site = resolve_cell_ab_site(name, 1)
        if site is None:  # a registered designated slot base name (ship-h1r0) is its tier-1 place
            return arm in designated_slot_arms(name)
    except (ImportError, OSError, ValueError, KeyError, TypeError):
        return False
    return bool(site and site["area"] in ("stand", "yard", "temp_a", "temp_b", "temp_plate_a", "temp_plate_b")
                and arm in site["arms"])


def fixed_base_geometry(site):
    return (isinstance(site, dict) and not any(site.get(k) for k in ("moves", "on_vehicle", "moving_px", "tier_of"))
            and site.get("tier", 1) == 1 and all(site.get(k, 0) == 0 for k in ("layer", "layers_below", "z_offset_m")))


def _support(config, target, source, calibration):
    from cell_route_surface import contact_evidence

    site, obj, entry = config["sites"][source], target["object"], target["entry"]
    if (not fixed_site(source, config["arm_id"]) or not fixed_base_geometry(site)
            or any(obj.get(k, 0) != 0 for k in ("grasp_shift_mm", "layers_below", "dz_m"))
            or any(target.get("bias_mm", ())) or any(site.get("grip_offset_m", ()))
            or (target.get("bias_region") or {}).get("droop_z_mm", 0) != 0
            or not all(_finite(entry.get(k)) and entry[k] > 0 for k in ("length_mm", "width_mm", "top_height_mm"))):
        return None
    evidence = contact_evidence(config, source, calibration)
    if evidence["status"] != "matched_contact":
        return None
    xy = site["place"]
    if math.dist(xy, [target["pick"]["x"], target["pick"]["y"]]) > 0.001:
        return None
    return evidence


def source_base_tier(cell, config, target, source, calibration, catalog, roi):
    """Before the arm moves, measure this object's top above its source's observed floor."""
    try:
        import cell_depth_slots
        import cell_route_check
        import cell_zone_verification as zones
        from cell_auto_pick_plan import observe
        from cell_route_depth import MAX_RGB_SKEW_S, _tier

        surface = _support(config, target, source, calibration)
        floor = cell_route_check.source_floor(config, source) if surface is not None else None
        if not floor:
            return None
        start = time.time()
        depth, receipt, error = zones._depth_after(config, start)
        if error or depth is None:
            return None
        top, error = zones._frame(cell, "top", after=start)
        if error:
            return None
        first = receipt.get("first_exposure_wall_estimate_s", receipt["exposure_wall_estimate_s"])
        last = receipt.get("last_exposure_wall_estimate_s", receipt["exposure_wall_estimate_s"])
        stamp = top["source_stamp"]
        now = time.time()
        if not (receipt["raw_sha256"] and top["jpeg_sha256"] and start <= first <= last <= now
                and start <= stamp <= now and first - MAX_RGB_SKEW_S <= stamp <= last + MAX_RGB_SKEW_S
                and now - min(first, stamp) <= zones.MAX_FRAME_AGE_S):
            return None
        _, _, seen, error = observe(cell, config, calibration, source, roi, catalog, image=top["image"])
        obj = target["object"]
        matches = [item for item in seen if item.get("object") == obj["object"] and math.dist(item["raw_m"], obj["raw_m"]) <= 0.001]
        if error or len(matches) != 1 or matches[0].get("split_from"):
            return None
        hull = matches[0]["hull_px"]
        xs, ys = zip(*hull)
        box = (min(xs), min(ys), max(xs) + 1, max(ys) + 1)
        ref = cell_depth_slots.depth_reference(depth, top["image"], box, floor["floor"], 1,
                                               floor_depth_mm=floor["floor_depth_mm"])
        if not _tier(ref, 1):
            return None
        residual = abs(ref["median_rel_mm"] - target["entry"]["top_height_mm"]) + ref["plane_rms_mm"] + ref["patch_offset_mm"]
        if not _finite(residual) or residual > MAX_HEIGHT_RESIDUAL_MM:
            return None
        return {"object_id": obj["object"], "site": source, "surface": surface,
                "height_residual_mm": residual, "measured_top_mm": ref["median_rel_mm"], "source_tier": 1,
                "depth_sha256": receipt["raw_sha256"], "top_sha256": top["jpeg_sha256"], "stamp": stamp}
    except (Exception, SystemExit):  # optional sensing may fail in a camera driver or OpenCV
        return None


def _pose(config, state):
    from grasp_planner import load_kinematics, norm_to_rad
    from omx_tcp import config_tcp, resolve_tcp

    tcp, _source = resolve_tcp(config_tcp(config))
    kin, _, _ = load_kinematics(None, tcp)
    return kin.fk([norm_to_rad(v) for v in state[:5]])


def record_grasp(config, catalog, target, source, destination, status, *, calibration, source_tier):
    """Loss of metadata leaves a normal carry running and disables placement recovery."""
    try:
        from bench_record_handoff import atomic_write_json
        from cell_envelope import digest
        from cell_objects import payload

        context = status["operating_context"]
        arm, obj, entry = config["arm_id"], target["object"], target["entry"]
        if (context.get("scope") != "hardware" or not context.get("session_id")
                or not status.get("library_sha256") or status.get("command") != "run grasp_pick"
                or status.get("ok") is not True or status.get("holding") is not True
                or status.get("fault") or obj.get("grasp_shift_mm") or not _finite(status.get("t"))
                or [item for item in catalog if item["id"] == obj["object"]] != [entry]):
            return
        state = status["state"]
        if len(state) != 6 or not all(_finite(v) for v in state):
            return
        support = _support(config, target, source, calibration)
        if (not support or not source_tier or source_tier["source_tier"] != 1 or source_tier["site"] != source
                or source_tier["object_id"] != entry["id"] or source_tier["surface"] != support
                or not _finite(source_tier["height_residual_mm"])
                or not 0 <= source_tier["height_residual_mm"] <= MAX_HEIGHT_RESIDUAL_MM):
            return
        pose = _pose(config, state)
        site = config["sites"][source]
        if (not all(_finite(v) for v in (pose.x, pose.y, pose.z, pose.yaw))
                or math.dist((pose.x, pose.y), site["place"]) > 0.001
                or abs(math.remainder(math.degrees(pose.yaw) - site["yaw_deg"], 360)) > 1
                or not _finite(pose.tool_down_error_rad) or not 0 <= pose.tool_down_error_rad < math.pi / 2):
            return
        height = pose.z - support["measured_z_m"]
        radius_m = math.hypot(entry["length_mm"], entry["width_mm"]) / 2000
        tilt_m = radius_m * math.sin(pose.tool_down_error_rad)
        error_m = support["repeatability_m"] + source_tier["height_residual_mm"] / 1000 + tilt_m
        if not error_m < height < entry["top_height_mm"] / 1000 - error_m:
            return
        task = config.get("_fleet_task")
        has_task = isinstance(task, str) and bool(task.strip())
        nominal = {"site": destination, "xy_m": [target["place"]["x"], target["place"]["y"]],
                   "layer": config["sites"][destination].get("layer", 0)}
        cargo = {"object_id": entry["id"], "catalog_entry": entry, "catalog": catalog, "catalog_sha256": digest(catalog),
                 "length_mm": entry["length_mm"], "width_mm": entry["width_mm"],
                 "payload": payload(catalog, entry["id"]), "grasp_above_base_m": height, "source_contact": source_tier,
                 "source_tilt_error_m": tilt_m, "source_height_evidence_error_m": error_m,
                 "held_axis_deg": obj["long_axis_deg"] - math.degrees(pose.yaw),
                 "nominal_destination": nominal, "destination": destination if has_task else None,
                 "destination_xy_m": nominal["xy_m"] if has_task else None,
                 "destination_layer": nominal["layer"] if has_task else None}
        record = {"arm": arm, "session_id": context["session_id"], "library_sha256": status["library_sha256"],
                  "grasp_at": status["t"], "cargo": cargo}
        if has_task:
            cargo["task_id"] = task
        atomic_write_json(Path(config["io"]).expanduser() / _FILE, record)
    except (Exception, SystemExit):  # unavailable recovery provenance must not interrupt the active carry
        return


def interrupted_cargo(session, arm):
    """Read only this session's positively held carry. Decline a later release or a new grasp."""
    try:
        io = Path(session["chunks"]["io"]).expanduser()
        record = json.loads((io / _FILE).read_text(encoding="utf-8"))
        since, end, grasp = session["started"], session["ended"], record["grasp_at"]
        if arm != record["arm"] or not all(_finite(t) for t in (since, end, grasp)) or not since <= grasp <= end:
            return None
        matched = False
        for row in rows(io / "chunk-status.jsonl", grasp):
            if not isinstance(row, dict) or not _finite(row.get("t")) or not grasp <= row["t"] <= end:
                continue
            context = row.get("operating_context") or {}
            command = row.get("command") or ""
            if row["t"] == grasp and not matched:
                matched = (command == "run grasp_pick" and row.get("ok") is True and row.get("holding") is True
                           and context.get("scope") == "hardware" and context.get("session_id") == record["session_id"]
                           and row.get("library_sha256") == record["library_sha256"])
            elif matched:
                if (context and context.get("session_id") != record["session_id"] or row.get("holding") is False
                        or any(part in command for part in ("release", "grasp", "grip", "reinsert"))
                        or command.startswith(("load ", "policy", "episode ", "run policy"))):
                    return None
        return record["cargo"] if matched and isinstance(record["cargo"], dict) else None
    except (OSError, ValueError, KeyError, TypeError, AttributeError, OverflowError):
        return None
