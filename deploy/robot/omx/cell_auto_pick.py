#!/usr/bin/env python3
"""OMX autonomous pick and place loop; observation and evidence live in focused modules."""
import json
import math
from pathlib import Path
import sys
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cell_act_shadow  # noqa: E402
import cell_attempts  # noqa: E402
import cell_auto_record  # noqa: E402
import cell_auto_evidence  # noqa: E402
from cell_auto_pick_plan import (  # noqa: E402,F401  (re-exported)
    CLOSING,
    choose,
    observe,
    plan_pick,
    save_frame_receipt,
    verify_placed,
)
import cell_executor  # noqa: E402
from cell_auto_safety import (  # noqa: E402, F401
    PWM_FRACTION,
    TEMP_STOP_C,
    Aborted,
    Guarded,
    Monitor,
    after_failure,
    close_episode,
    finger_room,
    object_sized,
    open_episode,
    score_pick_candidate,
    session_caps,
    square_entry,
)
from cell_auto_setup import load_config  # noqa: E402,F401
from cell_calibrate import learn_bias, self_calibrate  # noqa: E402,F401
import cell_calibration as cal  # noqa: E402
import cell_carry_choices  # noqa: E402
import cell_decisions as cd  # noqa: E402
import cell_diagnose  # noqa: E402,F401
import cell_hooks  # noqa: E402
import cell_jaw_axis  # noqa: E402,F401
import cell_objects  # noqa: E402
from cell_observe import keep, predicted_pixel, wrap90  # noqa: E402,F401
import cell_params as prm  # noqa: E402
from cell_pick_geom import across, grasp_depth, grasp_yaw, jaw_open_for, parse_dest, reachable_ends, surface_z  # noqa: E402,F401
import cell_pipeline as cp  # noqa: E402
import cell_pivot  # noqa: E402
import cell_place_fit  # noqa: E402
from cell_transfer import FOLDED, RETURN_HELD, STILL_HOLDING_UNITS, Gate, transfer_folded  # noqa: E402,F401
import cell_wrist_ref  # noqa: E402


def run_auto(
    cell,
    config,
    calibration,
    calibration_path,
    catalog,
    roi,
    source,
    dest,
    work: Path,
    choices,
    dry_run=False,
    sleep=time.sleep,
    log=print,
    attempts=None,
    scenario_id=None,
) -> dict:
    """One object from `source` to `dest`; up to `attempts` grasps (the second with the better candidate)."""
    work, out = Path(work), {"from": source, "to": dest, "attempts": []}
    config, calibration = cell_place_fit.with_tiers(config, calibration, catalog)
    if source not in config["sites"]:
        return {**out, "result": f"refused: source {source!r} is not a site in the config"}
    if dest in config["sites"] and "place" not in config["sites"][dest]:
        return {**out, "result": f"refused: {dest} is not a destination (its site has no 'place')"}
    map_error = cell_auto_evidence.map_pose_preflight(cell, config, calibration, calibration_path, work, dry_run, out)
    if map_error:
        return {**out, "result": f"held: {map_error}"}
    config, roi, track_error = cell_auto_evidence.track_sites(
        cell, config, calibration, source, dest, roi, work, dry_run, out)
    if track_error:
        return {**out, "result": track_error}
    dest_site, place_xy = parse_dest(config, source, dest)
    config, carry, carry_shadow = cell_carry_choices.apply(config, choices, dest, dest_site, log, source)  # sim-ranked carry offer, learns from this try
    droi = config["sites"][dest_site].get("auto_roi") or (
        roi if dest_site == source or config["sites"][dest_site].get("layer", 0) > 0 else None
    )
    guarded = None if dry_run else Guarded(cell, config)
    if guarded is not None and not cell.act("state").get("ok"):
        return {"result": "refused", "error": "start record_session.py --chunks first: no chunk_runner answers"}
    bias_data = cell_place_fit.with_tier_biases(
        config, cell_pivot.load_bias(cell_pivot.bias_path(calibration_path), config.get("params"))
    )
    episode, failed_yaws, gate, dest_view = None, [], None, None
    attempts = int(prm.get(config.get("params"), "auto.attempts")) if attempts is None else attempts
    shadow = None if dry_run else cell_act_shadow.load(config, work)
    try:
        for attempt in range(attempts):
            t0, tried = time.time(), {"locate": {"found": False}, "scenario_id": scenario_id}
            if carry_shadow:
                tried["carry_shadowed"] = carry_shadow  # a site value won over the offer: ingest must not credit it
            capture_id = uuid.uuid4().hex
            source_frame = None
            if not dry_run:
                source_frame, source_record, source_error = cell_auto_evidence.source_frame(
                    cell, work / "frames" / f"{capture_id}-source.jpg")
                if source_error:
                    tried["fail"] = {"stage": "camera", "class": "fresh source frame unavailable"}
                    cell_attempts.record(config, calibration, source, dest, attempt, tried, t0, choices)
                    return {**out, "result": "held: fresh source frame unavailable", "error": source_error}
                tried["source_frame"] = source_record
            source_image = source_frame["image"] if source_frame is not None else cell.frame("top")
            dest_view, derr = cell_auto_evidence.destination_view(
                cell, config, calibration, dest_site, droi, source, catalog, source_image)
            if derr and not dry_run:
                tried["fail"] = {"stage": "camera", "class": f"destination observation: {derr}"}
                cell_attempts.record(config, calibration, source, dest, attempt, tried, t0, choices)
                return {**out, "result": f"held: destination observation: {derr}"}
            img, mask, objects, error = observe(cell, config, calibration, source, roi, catalog,
                                                image=source_image)
            usable, refused = (
                choose(
                    cell, config, calibration, source, dest_site, place_xy, roi,
                    objects, mask, catalog, bias_data, choices, work, failed_yaws, dest_view,
                )
                if not error
                else ([], [])
            )
            cd.target(objects, usable, refused)
            if usable and (config.get("debate_models") or config.get("decision_model")):
                import cell_pick_judge  # noqa: E401

                judged = cell_pick_judge.ask(config.get("debate_models") or config["decision_model"], img, usable)
                cd.emit("target_judge", {"candidates": len(usable)}, list(range(len(usable))) + [-1], judged["choice"], judged["by"], judged["reason"])
                usable = [usable[i] for i in judged["order"]]
            row = {"observed": len(objects), "refused": refused}
            out["attempts"].append(row)
            if error or not usable:
                kind = cell_diagnose.obstacle_type(refused)
                row["error"] = error or ("no usable object" + (f" ({kind})" if kind else ""))
                tried["fail"] = {"stage": "choose", "class": row["error"]}
                if not dry_run:
                    cell_attempts.record(config, calibration, source, dest, attempt, tried, t0, choices)
                return {**out, "result": f"stopped: {row['error']}"}
            target = usable[0]
            known = cell_pivot.bias_at(bias_data, source, target["object"]["raw_m"], params=config.get("params"))
            bias_data, problem = self_calibrate(
                None, config, calibration, calibration_path, source,
                target["object"]["raw_m"], objects, work, bias_data, sleep, log,
            )
            bias_data = cell_place_fit.with_tier_biases(config, bias_data)
            bias_error = (cell_auto_evidence.bias_map_error(config, calibration, bias_data, source,
                                                            target["object"]["raw_m"]) if "map_pose_frame" in out else None)
            if bias_error:
                tried["fail"] = {"stage": "calibrate", "class": bias_error}
                cell_attempts.record(config, calibration, source, dest, attempt, tried, t0, choices)
                return {**out, "result": f"held: {bias_error}"}
            cd.bias(known, problem, target["object"]["raw_m"])
            if problem and not dry_run:
                tried["locate"] = {"found": True, "arm_m": target["object"]["raw_m"]}
                tried["fail"] = {"stage": "calibrate", "class": problem}
                cell_attempts.record(config, calibration, source, dest, attempt, tried, t0, choices)
                return {**out, "result": f"held: {problem}; separate audited calibration required"}
            if (
                not dry_run
                and problem is None
                and cell_pivot.bias_at(bias_data, source, target["object"]["raw_m"], params=config.get("params"))
                != target["bias_region"]
            ):
                usable, refused = choose(
                    cell, config, calibration, source, dest_site, place_xy, roi, objects, mask, catalog,
                    bias_data, choices, work, failed_yaws, dest_view,
                )
                if not usable:
                    row["error"] = "no usable object after the pivot"
                    return {**out, "result": "stopped: " + row["error"]}
                target = usable[0]
                cd.target(objects, usable, refused)
            o = target["object"]
            tried["locate"] = {
                "found": True,
                "arm_m": [target["pick"]["x"], target["pick"]["y"]],
                "raw_m": o["raw_m"],
                "object": o["object"],
                "long_axis_deg": o["long_axis_deg"],
            }
            tried["grasp_yaw"] = {"choice": target["offset"], "yaw_deg": target["pick"]["yaw_deg"]}
            tried["plan"] = {"pick": target["pick"], "place": target["place"]}
            tried["auto"] = {
                "object": o["object"],
                **({"colour": o["colour"]} if "colour" in o else {}),
                "closing_axis_offset_deg": target["offset"],
                "bias_mm": target["bias_mm"],
                "bias_region": target["bias_region"],
                "approach_m": target["approach_m"],
            }
            cd.closing(target["offset"], choices.data["values"].get(CLOSING, []), o["object"])
            row.update(chosen=tried["auto"], plan=tried["plan"], pivot_needed=problem, long_axis_deg=o["long_axis_deg"])
            if dry_run:
                return {**out, "result": "planned"}
            before_frame, frame_record, evidence_error = cell_auto_evidence.pre_motion_frame(
                cell, config, calibration, catalog, source, roi, o["raw_m"], o["object"],
                dest_site, droi, place_xy, bias_data, source_frame,
                work / "frames" / f"{capture_id}-before.jpg")
            if frame_record is not None:
                tried["before_frame"] = frame_record
            if evidence_error:
                tried["fail"] = {"stage": "camera" if "source" in evidence_error or "camera" in evidence_error
                                 else "verify", "class": evidence_error}
                cell_attempts.record(config, calibration, source, dest, attempt, tried, t0, choices)
                return {**out, "result": f"held: {evidence_error}"}
            folded = prm.get(config.get("params"), "auto.fold_before_transport")
            sequence = FOLDED if folded else cp.SEQUENCE
            config = dict(config, _payload=cell_objects.payload(catalog, o["object"]))
            episode = open_episode(cell, config, source, dest, o["object"])
            same = dict(config, plan=dict(config["plan"], **target.get("plan", {})))
            choice, tried["execution"] = cell_executor.choose(choices, attempt)
            gate = Gate(guarded, config, calibration, sequence=sequence)
            ledger = cell_attempts.ReplanLedger(config, calibration, source, dest, attempt, tried, t0, choices)
            # shadow inference before the gate opens: no delay between the approval and the motion
            shadow_row = shadow.capture(cell, config, attempt, img) if shadow else None
            held = gate.open(target["library"], lambda a: cell_attempts.begin(config, a), ledger.finish)
            if held is not None:
                tried["envelope"] = held
                tried["transfer"] = {"result": "held", "at": "preflight", "steps": [], "envelope": held}
                close_episode(cell, episode, False, f"held: {held['reason']}")
                cell_attempts.record(config, calibration, source, dest, attempt, tried, t0, choices)
                return {**out, "result": f"held: {held['reason']}"}
            guard = cell_auto_evidence.scene_guard(
                guarded, config, calibration, source, roi, o["raw_m"], before_frame["image"])
            wrist, capture, pinch, feel = cell_hooks.pick_hooks(
                same, gate, target, cp.write_library, source, dest_site, cd.emit, calibration, guard
            )
            grasp_check = cell_hooks.grasp_debate(same, gate, target, cp.write_library)
            moved = transfer_folded(
                gate,
                target["library"],
                wrist=wrist,
                after_place=capture,
                pinch=pinch,
                feel=feel,
                sequence=sequence,
                lift_stall=cell_hooks.lift_stall(cell, config, sleep),
                at_stop=cell_hooks.stills(cell, config),
                grasp_check=grasp_check,
            )
            tried["envelope"] = gate.assessment
            tried["wrist"] = (
                moved.get("wrist")
                or next((s for s in moved["steps"] if s.get("command") == "wrist"), None)
                or ("disabled or uncalibrated" if wrist is None else None)
            )
            tried["transfer"] = moved
            if gate.transitions:
                tried["transfer"] = {**moved, "steps": list(gate.history)}
            if gate.blocked:
                close_episode(cell, episode, False, "supervised audit transition held")
                return {**out, "result": "held: supervised audit transition"}
            if moved["result"] not in ("placed", "contact", "fault", "refused"):
                cell_executor.outcome(choices, tried["execution"], choice, False, moved["result"])
            if moved["result"] in ("empty", "reinserted") or (
                moved["result"] == "contact" and moved.get("at") in ("run descend_pick", "run grasp_pick")
            ):
                decided = after_failure(config, source, target, moved, wrist is not None, failed_yaws)
                tried["diagnosis"] = decided
                tried["compensation"] = cell_diagnose.compensation_feedback(
                    moved["result"], tried, target.get("bias_mm"),
                    grip_open=target.get("plan", {}).get("grip_open"),
                    calibrated_grip_open=(config.get("_arm_calibration") or {}).get("grip_open_30mm"),
                )
                if decided["chosen"] in ("ask_person", "probe_surface"):
                    close_episode(cell, episode, False, f"{decided['cause']}: {decided['chosen']}")
                    episode = None
                    cell_act_shadow.record(shadow, shadow_row,
                                           cell_attempts.record(config, calibration, source, dest, attempt, tried, t0, choices),
                                           moved["result"], moved.get("at"))
                    return {**out, "result": f"stopped: {decided['cause']} -> {decided['chosen']}"}
            held = moved["result"] == "placed" or any(s.get("holding") for s in moved["steps"])
            if moved["result"] == "placed":
                place_xy = (target["place"]["x"], target["place"]["y"])
                tried["verify"] = verify_placed(
                    guarded, config, calibration, dest_site, place_xy, droi, catalog, bias_data, o["object"],
                    before_frame, work / "frames" / f"{capture_id}-after.jpg", source, o["raw_m"], roi,
                )
                cd.emit(
                    "verify",
                    dict(tried["verify"]),
                    [True, False],
                    tried["verify"]["inside"],
                    "measurement",
                    f"placement seen on the {tried['verify']['basis']}",
                )
                tried["learned_bias"] = learn_bias(config, calibration_path, dest_site, place_xy, tried["verify"])
                cell_executor.outcome(choices, tried["execution"], choice,
                                      tried["verify"].get("verified") is True and tried["verify"].get("inside") is True,
                                      "placement verification")
                pending = cell_wrist_ref.ref_path(work, config.get("arm_id", "arm_s"), dest_site).with_suffix(
                    ".pending.json"
                )
                if pending.exists():
                    if tried["verify"].get("inside"):
                        pending.replace(cell_wrist_ref.ref_path(work, config.get("arm_id", "arm_s"), dest_site))
                    else:
                        pending.unlink()
            accepted = (moved["result"] == "placed" and tried["verify"].get("verified") is True
                        and tried["verify"].get("inside") is True)
            if target["offset"] is not None and (accepted or moved["result"] in ("empty", "contact", "reinserted")):
                choices.outcome(CLOSING, target["offset"], accepted,
                                f"{moved['result']} at yaw {target['pick']['yaw_deg']}")
                choices.save()
            if accepted or moved["result"] in ("empty", "contact", "reinserted"):
                cell_carry_choices.outcome(choices, carry, accepted)
            close_episode(
                cell, episode, accepted,
                f"{moved['result']} at {moved.get('at')}" if moved["result"] != "placed"
                else "placed but not seen at the destination",
            )
            episode = None
            cd.after(moved, choices.best(CLOSING), attempt + 1 < attempts, guarded.monitor)
            tried.setdefault("compensation", cell_diagnose.compensation_feedback(
                moved["result"], tried, target.get("bias_mm"),
                grip_open=target.get("plan", {}).get("grip_open"),
                calibrated_grip_open=(config.get("_arm_calibration") or {}).get("grip_open_30mm"),
            ))
            attempt_id = cell_attempts.record(config, calibration, source, dest, attempt, tried, ledger.t_start, choices)
            cell_act_shadow.record(shadow, shadow_row, attempt_id, moved["result"], moved.get("at"))
            cell_auto_record.capture_problem(config, source, dest, moved)
            if (moved["result"] == "placed" and tried["verify"].get("verified") is True
                    and tried["verify"]["inside"]):
                return {**out, "result": "placed", "attempt_id": attempt_id}
            grasped = any(s.get("command") == "run grasp_pick" and s.get("holding") for s in moved["steps"])
            if moved["result"] == "contact" and grasped:
                return {
                    **out,
                    "result": f"stopped: {'released' if moved.get('released') else 'holding'} after a stop at {moved['at']}",
                }
            parks = [s for s in moved["steps"] if s.get("command") == "park"]
            if parks and parks[-1].get("contact"):  # 2026-11-14 arm_s: a park overloaded at a far pick; no next attempt from there
                return {**out, "result": f"stopped: contact at park: {parks[-1].get('error')}"}
            if moved["result"] not in ("empty", "contact", "reinserted"):
                if moved["result"] in ("fault", "refused") and not gate.blocked:
                    cp.fold(gate, sleep)
                return {**out, "result": "stopped: placement unverified" if moved["result"] == "placed"
                        else f"stopped: {moved['result']}"}
    except Aborted as stop:
        close_episode(cell, episode, False, f"aborted: {stop}")
        if "execution" in tried:
            cell_attempts.record(config, calibration, source, dest, attempt, tried, t0, choices)
        return {**out, "result": f"aborted: {stop}"}
    except Exception:
        if gate is not None and gate.before_motion is not None and not gate.blocked:
            cp.fold(gate, sleep)
        close_episode(cell, episode, False, "pipeline exception")
        raise
    return {**out, "result": f"stopped: {attempts} attempts"}


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
    map_error = cell_auto_evidence.map_pose_preflight(cell, config, calibration, calibration_path, work, dry_run, out)
    if map_error:
        return {**out, "result": f"held: {map_error}"}
    config, roi, track_error = cell_auto_evidence.track_sites(
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
    guarded = Guarded(cell, config)
    if not cell.act("state").get("ok"):
        return {**out, "result": "refused", "error": "start record_session.py --chunks first: no chunk_runner answers"}
    droi = config["sites"][dest_site].get("auto_roi") or roi
    bias_data = cell_place_fit.with_tier_biases(
        config, cell_pivot.load_bias(cell_pivot.bias_path(calibration_path), config.get("params"))
    )
    before_frame, _, src_err = cell_auto_evidence.source_frame(cell, work / "frames" / f"{uuid.uuid4().hex}-before.jpg")
    if before_frame is not None and cell_pivot.map_record(calibration, dest_site):
        _, _, present_dest, obs_err = observe(cell, config, calibration, dest_site, droi, catalog, image=before_frame["image"])
        region = cell_pivot.bias_at(bias_data, dest_site, place_xy, params=config.get("params"))
        bx, by = region["bias_mm"] if region else (0.0, 0.0)
        if not obs_err and any(1000 * math.dist((o["raw_m"][0] - bx / 1000, o["raw_m"][1] - by / 1000), place_xy) <= config.get("verify_tol_mm", 10.0) for o in present_dest):
            return {**out, "result": "held: destination unavailable or occupied"}
    elif src_err:
        return {**out, "result": f"held: {src_err}"}
    config = dict(config, _payload=cell_objects.payload(catalog, obj_id))
    episode, gate = open_episode(cell, config, dest_site, dest, obj_id), Gate(guarded, config, calibration, sequence=RETURN_HELD)
    tried, t0, opened = {"locate": {"found": True}, "object": obj_id, "plan": out["plan"]}, time.time(), False
    try:
        held = gate.open(lib, lambda a: cell_attempts.begin(config, a), lambda *_, **__: None)
        if held is not None:
            close_episode(cell, episode, False, f"held: {held['reason']}")
            return {**out, "result": f"held: {held['reason']}", "envelope": held}
        opened = True
        moved = transfer_folded(
            gate, lib, sequence=RETURN_HELD,
            lift_stall=cell_hooks.lift_stall(cell, config, sleep),
            at_stop=cell_hooks.stills(cell, config),
        )
        tried["envelope"], tried["transfer"] = gate.assessment, moved
        verify = None
        if moved["result"] == "placed":
            verify = verify_placed(
                guarded, config, calibration, dest_site, place_xy, droi, catalog, bias_data, obj_id,
                before_frame, work / "frames" / f"{uuid.uuid4().hex}-after.jpg",
                dest_site, (float("nan"), float("nan")), droi,
            )
            tried["verify"] = verify
        close_episode(cell, episode, moved["result"] == "placed", moved["result"])
        episode = None
        cell_attempts.record(config, calibration, "held", dest, 1, tried, t0)
        if moved["result"] in ("fault", "refused") and not gate.blocked:
            cp.fold(gate, sleep)
        return {**out, "result": moved["result"], "transfer": moved, **({"verify": verify} if verify else {})}
    except Aborted as stop:
        close_episode(cell, episode, False, f"aborted: {stop}")
        if opened:
            tried["transfer"] = {"result": "aborted", "error": str(stop), "steps": []}
            cell_attempts.record(config, calibration, "held", dest, 1, tried, t0)
        return {**out, "result": f"aborted: {stop}"}
    except Exception:
        if not gate.blocked:
            cp.fold(gate, sleep)
        close_episode(cell, episode, False, "pipeline exception")
        raise


def main(argv=None):
    import cell_choices
    import cell_preflight
    from cell_auto_setup import open_cell, parser

    ap = parser(__doc__)
    ap.add_argument("--commissioning", action="store_true", help="a supervised trial of this one carry (D-911)")
    ap.add_argument("--person-at-switch", action="store_true", help="with --commissioning: a person is at the power switch")
    ap.add_argument("--task-id", help="correlate this one carry with a Fleet task; does not authorize completion")
    ap.add_argument("--handoff-lease-id", help="Fleet lease paired with --task-id")
    ap.add_argument("--scenario-id", help="scenario identifier from the cell task")
    ap.add_argument("--return-held", action="store_true", help="arm already holds an object at home: place it at --dest without picking")
    args = ap.parse_args(argv)
    if args.commissioning != args.person_at_switch:
        raise SystemExit("--commissioning needs --person-at-switch (and the other way round)")
    if bool(args.task_id) != bool(args.handoff_lease_id) or (args.task_id and args.dry_run):
        raise SystemExit("--task-id and --handoff-lease-id require each other and a real single carry")
    config, cell, calibration_path, work = open_cell(args, args.commissioning)
    dark = cell_preflight.ready(cell.frame, config)
    if dark:
        print(json.dumps({"from": args.source, "to": args.dest, "result": "refused", "error": "; ".join(dark)}, indent=1))
        return 1
    cal_data = cell_pivot.with_site_maps(config, cal.load(calibration_path))
    cat = cell_objects.load_catalog(args.catalog)
    if args.return_held:
        result = run_return_held(cell, config, cal_data, calibration_path, cat, args.roi, args.dest, work, args.dry_run)
    else:
        result = run_auto(
            cell, config, cal_data, calibration_path, cat, args.roi, args.source, args.dest, work,
            cell_choices.Choices(work / "choices.json"), args.dry_run, scenario_id=args.scenario_id,
        )
    print(json.dumps(result, indent=1, default=str))
    return 0 if result["result"] in ("placed", "planned") else 1


if __name__ == "__main__":
    sys.exit(main())
