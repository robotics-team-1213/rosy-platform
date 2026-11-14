#!/usr/bin/env python3
"""Autonomous pick and place of catalogue objects for arm S, no human hands (2026-10-28).

Single Responsibility:
  - Autonomous pick-and-place execution loop (`run_auto`, `main`).
  - Top-camera observation, candidate selection, and placement verification live in `cell_auto_pick_plan.py`
    and are re-exported here unchanged.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cell_act_shadow  # noqa: E402
import cell_attempts  # noqa: E402
import cell_executor  # noqa: E402
from cell_auto_pick_plan import (  # noqa: E402,F401  (re-exported)
    CLOSING,
    choose,
    observe,
    plan_pick,
    verify_placed,
)
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
import cell_decisions as cd  # noqa: E402
import cell_diagnose  # noqa: E402,F401
import cell_hooks  # noqa: E402
import cell_jaw_axis  # noqa: E402,F401
import cell_objects  # noqa: E402
from cell_observe import keep, predicted_pixel, wrap90  # noqa: E402,F401
import cell_params as prm  # noqa: E402
from cell_pick_geom import (  # noqa: E402,F401
    across,
    grasp_depth,
    grasp_yaw,
    jaw_open_for,
    parse_dest,
    reachable_ends,
    surface_z,
)
import cell_pipeline as cp  # noqa: E402
import cell_pivot  # noqa: E402
import cell_place_fit  # noqa: E402
import cell_scene_guard  # noqa: E402
import cell_site_track  # noqa: E402
from cell_transfer import FOLDED, STILL_HOLDING_UNITS, Gate, transfer_folded  # noqa: E402,F401
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
    for site in {source, dest} & {k for k, v in config["sites"].items() if v.get("track")}:
        config, out[f"track_{site}"] = cell_site_track.follow(
            config, site, cell.frame("top"), lambda q, s=site: predicted_pixel(config, calibration, s, q), work
        )
        if not out[f"track_{site}"]["tracked"]:
            return {**out, "result": f"refused: {site}: {out[f'track_{site}'].get('why')}"}
        roi = config["sites"][site]["auto_roi"] if site == source else roi
    dest_site, place_xy = parse_dest(config, source, dest)
    droi = config["sites"][dest_site].get("auto_roi") or (
        roi if dest_site == source or config["sites"][dest_site].get("layer", 0) > 0 else None
    )
    guarded = None if dry_run else Guarded(cell, config)
    if guarded is not None and not cell.act("state").get("ok"):
        return {"result": "refused", "error": "start record_session.py --chunks first: no chunk_runner answers"}
    bias_data = cell_place_fit.with_tier_biases(
        config, cell_pivot.load_bias(cell_pivot.bias_path(calibration_path), config.get("params"))
    )
    episode, failed_yaws, dest_view = None, [], None
    attempts = int(prm.get(config.get("params"), "auto.attempts")) if attempts is None else attempts
    shadow = None if dry_run else cell_act_shadow.load(config, work)
    try:
        for attempt in range(attempts):
            t0, tried = time.time(), {"locate": {"found": False}, "scenario_id": scenario_id}
            if droi is not None and dest_site != source:  # the destination is looked at again before each attempt
                _, dmask, _, derr = observe(cell, config, calibration, dest_site, droi, catalog)
                dest_view = None if derr else (dmask, droi)
            img, mask, objects, error = observe(cell, config, calibration, source, roi, catalog)
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
            pivot_cell = guarded if not dry_run and "_commissioning" in config else None
            bias_data, problem = self_calibrate(
                pivot_cell, config, calibration, calibration_path, source,
                target["object"]["raw_m"], objects, work, bias_data, sleep, log,
            )
            bias_data = cell_place_fit.with_tier_biases(config, bias_data)
            cd.bias(known, problem, target["object"]["raw_m"])
            if problem and not dry_run:
                tried["locate"] = {"found": True, "arm_m": target["object"]["raw_m"]}
                tried["fail"] = {"stage": "calibrate", "class": problem}
                cell_attempts.record(config, calibration, source, dest, attempt, tried, t0, choices)
                return {**out, "result": f"stopped: {problem}"}
            if (
                not dry_run
                and problem is None
                and cell_pivot.bias_at(bias_data, source, target["object"]["raw_m"], params=config.get("params"))
                != target["bias_region"]
            ):
                usable, refused = choose(
                    cell,
                    config,
                    calibration,
                    source,
                    dest_site,
                    place_xy,
                    roi,
                    objects,
                    mask,
                    catalog,
                    bias_data,
                    choices,
                    work,
                    failed_yaws,
                    dest_view,
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
            folded = prm.get(config.get("params"), "auto.fold_before_transport")
            sequence = FOLDED if folded else cp.SEQUENCE
            config = dict(config, _payload=cell_objects.payload(catalog, o["object"]))
            episode = open_episode(cell, config, source, dest, o["object"])
            same = dict(config, plan=dict(config["plan"], **target.get("plan", {})))
            choice, tried["execution"] = cell_executor.choose(choices, attempt)
            gate = Gate(guarded, config, calibration, sequence=sequence)
            # shadow inference before the gate opens: no delay between the approval and the motion
            shadow_row = shadow.capture(cell, config, attempt, img) if shadow else None
            held = gate.open(target["library"], lambda a: cell_attempts.begin(config, a))
            if held is not None:
                tried["envelope"] = held
                tried["transfer"] = {"result": "held", "at": "preflight", "steps": [], "envelope": held}
                close_episode(cell, episode, False, f"held: {held['reason']}")
                cell_attempts.record(config, calibration, source, dest, attempt, tried, t0, choices)
                return {**out, "result": f"held: {held['reason']}"}
            guard = cell_scene_guard.hook(
                guarded,
                config,
                guarded.frame("top"),
                roi,
                predicted_pixel(config, calibration, source, (0.0, 0.0)),
                predicted_pixel(config, calibration, source, o["raw_m"]),
            )
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
            if moved["result"] not in ("placed", "contact", "fault", "refused"):
                cell_executor.outcome(choices, tried["execution"], choice, False, moved["result"])
            if moved["result"] in ("empty", "reinserted") or (
                moved["result"] == "contact" and moved.get("at") in ("run descend_pick", "run grasp_pick")
            ):
                decided = after_failure(config, source, target, moved, wrist is not None, failed_yaws)
                tried["diagnosis"] = decided
                if decided["chosen"] in ("ask_person", "probe_surface"):
                    close_episode(cell, episode, False, f"{decided['cause']}: {decided['chosen']}")
                    episode = None
                    cell_act_shadow.record(shadow, shadow_row,
                                           cell_attempts.record(config, calibration, source, dest, attempt, tried, t0, choices),
                                           moved["result"], moved.get("at"))
                    return {**out, "result": f"stopped: {decided['cause']} -> {decided['chosen']}"}
            held = moved["result"] == "placed" or any(s.get("holding") for s in moved["steps"])
            if target["offset"] is not None and moved["result"] in ("placed", "empty", "contact", "reinserted"):
                choices.outcome(
                    CLOSING,
                    target["offset"],
                    moved["result"] == "placed",
                    f"{moved['result']} at yaw {target['pick']['yaw_deg']}",
                )
                choices.save()
            if moved["result"] == "placed":
                place_xy = (target["place"]["x"], target["place"]["y"])
                tried["verify"] = verify_placed(
                    guarded, config, calibration, dest_site, place_xy, droi, catalog, bias_data, o["object"], held
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
                cell_executor.outcome(choices, tried["execution"], choice, bool(tried["verify"].get("inside")),
                                      "placement verification")
                pending = cell_wrist_ref.ref_path(work, config.get("arm_id", "arm_s"), dest_site).with_suffix(
                    ".pending.json"
                )
                if pending.exists():
                    if tried["verify"].get("inside"):
                        pending.replace(cell_wrist_ref.ref_path(work, config.get("arm_id", "arm_s"), dest_site))
                    else:
                        pending.unlink()
            close_episode(
                cell,
                episode,
                moved["result"] == "placed" and tried["verify"]["inside"],
                f"{moved['result']} at {moved.get('at')}"
                if moved["result"] != "placed"
                else "placed but not seen at the destination",
            )
            episode = None
            cd.after(moved, choices.best(CLOSING), attempt + 1 < attempts, guarded.monitor)
            cell_act_shadow.record(shadow, shadow_row,
                                   cell_attempts.record(config, calibration, source, dest, attempt, tried, t0, choices),
                                   moved["result"], moved.get("at"))
            try:
                import cell_problem_pipeline

                cell_problem_pipeline.capture_from_attempt(
                    config,
                    {
                        "from": source,
                        "dest": dest,
                        "result": moved["result"],
                        "fail_stage": moved.get("at"),
                        "why": moved.get("error"),
                        "grasp_debate": moved.get("grasp_debate"),
                        "wrist": moved.get("wrist"),
                    },
                )
            except Exception:
                pass
            if moved["result"] == "placed" and tried["verify"]["inside"]:
                return {**out, "result": "placed"}
            grasped = any(s.get("command") == "run grasp_pick" and s.get("holding") for s in moved["steps"])
            if moved["result"] == "contact" and grasped:
                return {
                    **out,
                    "result": f"stopped: {'released' if moved.get('released') else 'holding'} after a stop at {moved['at']}",
                }
            if moved["result"] not in ("empty", "contact", "reinserted"):
                if moved["result"] in ("fault", "refused"):
                    cp.fold(cell, sleep)
                return {**out, "result": f"stopped: {moved['result']}"}
    except Aborted as stop:
        close_episode(cell, episode, False, f"aborted: {stop}")
        if "execution" in tried:
            cell_attempts.record(config, calibration, source, dest, attempt, tried, t0, choices)
        return {**out, "result": f"aborted: {stop}"}
    except Exception:
        if guarded is not None:
            cp.fold(cell, sleep)
        close_episode(cell, episode, False, "pipeline exception")
        raise
    return {**out, "result": f"stopped: {attempts} attempts"}


def main(argv=None):
    import cell_choices
    import cell_preflight
    from cell_auto_setup import open_cell, parser

    ap = parser(__doc__)
    ap.add_argument("--commissioning", action="store_true", help="a supervised trial of this one carry (D-911)")
    ap.add_argument("--person-at-switch", action="store_true", help="with --commissioning: a person is at the power switch")
    ap.add_argument("--scenario-id", help="scenario identifier from the cell task")
    args = ap.parse_args(argv)
    if args.commissioning != args.person_at_switch:
        raise SystemExit("--commissioning needs --person-at-switch (and the other way round)")
    config, cell, calibration_path, work = open_cell(args, args.commissioning)
    dark = cell_preflight.ready(cell.frame, config)
    if dark:
        print(json.dumps({"from": args.source, "to": args.dest, "result": "refused", "error": "; ".join(dark)}, indent=1))
        return 1
    result = run_auto(
        cell,
        config,
        cell_pivot.with_site_maps(config, cal.load(calibration_path)),
        calibration_path,
        cell_objects.load_catalog(args.catalog),
        args.roi,
        args.source,
        args.dest,
        work,
        cell_choices.Choices(work / "choices.json"),
        args.dry_run,
        scenario_id=args.scenario_id,
    )
    print(json.dumps(result, indent=1, default=str))
    return 0 if result["result"] in ("placed", "planned") else 1


if __name__ == "__main__":
    sys.exit(main())
