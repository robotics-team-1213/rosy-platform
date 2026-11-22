#!/usr/bin/env python3
"""Drive one arm with a pinned LeRobot policy through the chunk runner's own guards (2026-11-18, arm_s first).

The policy's proposed chunk becomes a chunk named `policy` in a copy of the arm's reviewed library, so the runner applies
the same `load` plan_check, start-gap check, speed/strain/jitter guards and holds as for an IK chunk; the IK chunks
(`home`, transfer chunks) stay in the same library, which is how a policy segment and IK segments mix. On top:
- every policy frame must lie inside the per-joint range the reviewed library's chunks cover (+ margin).
  Normalized-unit checkpoints may widen this with q01..q99 from the real demonstrations;
- no step may be faster than the library's fastest step: a faster chunk is stretched in time, never sent as is;
- the model's LeRobot calibration and the cell's may differ by a homing offset (11-18: wrist_roll 957 ticks = 46.7
  units); `calibration_offset` maps cell state into model units and the action back.
Timed ACT uses a single read-only inference worker and hands off to a taught carry in hybrid mode.
Needs --person-at-switch (D-911) and a named operator. --dry-run replays timing without submitting motion."""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cell_lerobot_shadow as lrs  # noqa: E402
from cell_policy_goals import GOALS, resolve_goal_site  # noqa: E402
from omx_adapter.chunk_library import GUARD_UNITS_PER_S  # noqa: E402

from cell_policy_shape import (  # noqa: E402,F401
    JOINTS, SIM_POLICY_FPS, calibration_offset, closed_gripper, converted_closed, demonstrated_range,
    envelope, in_jaw_zone, jaw_gate_spec, jaw_zone_error, open_before_close, resample_chunk, shape_chunk,
    source_rim_z, trained_grasp_mismatch, widen, wrist_roll_warning,
)
from cell_policy_timing import MAX_OBSERVATION_AGE_S, run_timed  # noqa: E402


def run_episode(cell, shadow, library_path: Path, work: Path, *, offset, max_chunks: int, dry_run: bool, log,
                demonstrated=None, goal_slot: int | None = None, n_action=None,
                max_obs_age_s=MAX_OBSERVATION_AGE_S, handoff=None, authorize=None,
                params=None, tcp_x_m=None, kin=None, rim_z_m: float | None = None) -> dict:
    library = json.loads(library_path.read_text(encoding="utf-8"))
    low, high, fastest = envelope(library)
    fps = float(library.get("fps", 30))
    fastest = min(fastest, GUARD_UNITS_PER_S / fps)  # the runner refuses any frame step past this
    sim_units = getattr(shadow, "sim_rule", None) is not None
    if demonstrated is not None and not sim_units:
        low, high = widen(low, high, *demonstrated)
    jaw_spec = resolved_tcp = None
    if "grasp_pick" in (library.get("chunks") or {}):
        from omx_tcp import RANGE_M

        parsed_tcp = {}
        for label, raw in (("configured tcp_x_m", tcp_x_m), ("library tcp_x_m", library.get("tcp_x_m"))):
            if raw is None:
                continue
            try:
                val = float("nan" if isinstance(raw, bool) else raw)
            except (TypeError, ValueError, OverflowError):
                val = float("nan")
            if not (math.isfinite(val) and RANGE_M[0] <= val <= RANGE_M[1]):
                raise ValueError(f"{label} must be finite in {RANGE_M[0]}..{RANGE_M[1]}, got {raw!r}")
            parsed_tcp[label] = val
        cfg_tcp = parsed_tcp.get("configured tcp_x_m")
        lib_tcp = parsed_tcp.get("library tcp_x_m")
        if cfg_tcp is not None and lib_tcp is not None and abs(lib_tcp - cfg_tcp) > 1e-6:
            raise ValueError(f"library tcp_x_m {lib_tcp} conflicts with configured {cfg_tcp}")
        resolved_tcp = cfg_tcp if cfg_tcp is not None else lib_tcp
        if kin is None:
            from grasp_planner import load_kinematics

            kin, _, _ = load_kinematics(None, resolved_tcp)
        jaw_spec = jaw_gate_spec(library, kin, params, rim_z_m=rim_z_m)
        if jaw_spec is not None and jaw_spec.get("rim_z_m") is not None:
            library = {**library, "source": {**(library.get("source") or {}), "rim_z_m": float(jaw_spec["rim_z_m"])}}
    if jaw_spec is not None and demonstrated is not None and not sim_units:
        if mismatch := trained_grasp_mismatch(demonstrated[0], demonstrated[1], jaw_spec["grasp_roll"]):
            row = {"preflight": "jaw_roll", "jaw_warning": mismatch, "dry_run": dry_run}
            if not dry_run:
                log({**row, "refused": mismatch})
                return {"result": "refused", "at": 0, "reason": mismatch}
            log(row)
    closed = closed_gripper(library)
    model_closed = converted_closed(closed, shadow.sim_rule) if sim_units else closed
    home_roll = None
    if sim_units and shadow.arm_id == "arm_b":
        home = library["chunks"].get("home")
        if not home or len(home[-1]) != JOINTS:
            raise ValueError("arm_b reviewed library requires a six-joint home frame")
        home_roll = float(home[-1][4])
        if not math.isfinite(home_roll):
            raise ValueError("arm_b reviewed library requires a finite home wrist roll")
    open_g = max(f[5] for chunk in library["chunks"].values() for f in chunk if len(f) == JOINTS)
    off = np.asarray(offset, dtype=float)
    goal = {} if goal_slot is None else {"goal": goal_slot}

    def live_jaw_error(measured_pose, target_pose) -> str | None:
        poses = [*([] if measured_pose is None else [measured_pose]), *([] if target_pose is None else [target_pose])]
        return jaw_zone_error(poses, kin, jaw_spec) if jaw_spec is not None else None

    def _legacy_jaw_hold(row, n: int, jaw_warn: str) -> dict:
        held_reply = cell.act("human-hold")
        log({**row, "refused": jaw_warn})
        log({"command": "human-hold", **_status(held_reply)})
        return {"result": "refused", "at": n, "reason": jaw_warn}

    if getattr(shadow, "chunk_size", None) is not None or sim_units or n_action is not None or handoff is not None:
        def infer(state, frames):
            model_state = np.asarray(state) if sim_units else np.asarray(state) + off
            obs, meta = shadow.inputs(model_state.tolist(), frames, **goal)
            args = {"state": state} if sim_units else {}
            chunk = np.asarray(shadow.infer(obs, **args).chunk, dtype=float)
            return (chunk if sim_units else chunk - off), meta

        def shape(actions, target, model_fps, runner_fps, held, row, converted, measured=None):
            if jaw_warn := live_jaw_error(measured, target):
                row["jaw_warning"] = jaw_warn
                if not dry_run:
                    raise ValueError(jaw_warn)
            if home_roll is not None and (warning := wrist_roll_warning(converted, home_roll)):
                row["wrist_roll_warning"] = warning
                if not dry_run:
                    raise ValueError(warning)
            if not held:
                actions = open_before_close(actions, open_g, model_closed)
            if model_fps != runner_fps:
                actions = resample_chunk(actions, target, runner_fps)
            frames = shape_chunk(actions, target, low, high, fastest)
            if jaw_spec is not None and (jaw_warn := jaw_zone_error(frames, kin, jaw_spec)):
                row["jaw_warning"] = jaw_warn
                if not dry_run:
                    raise ValueError(jaw_warn)
            return frames

        return run_timed(cell, shadow, library, work, infer=infer, shape=shape, max_step=fastest,
                         n_action=n_action, max_obs_age_s=max_obs_age_s, max_chunks=max_chunks,
                         dry_run=dry_run, log=log, handoff=handoff, authorize=authorize,
                         jaw_gate=({**jaw_spec, "tcp_x_m": resolved_tcp} if jaw_spec is not None else None))

    held, released = False, False
    for n in range(max_chunks):
        status = cell.act("state")
        state = np.asarray(status["state"], dtype=float)
        frames = {view: cell.frame(view) for view in shadow.image_views}
        obs, meta = shadow.inputs(state.tolist() if sim_units else (state + off).tolist(), frames, **goal)
        converted = np.asarray(shadow.infer(obs).chunk, dtype=float) - off
        proposed = converted
        if not held:
            proposed = open_before_close(proposed, open_g, model_closed)
        row = {"chunk": n, "state": state.tolist(), "meta": meta, "proposed_first": proposed[0].tolist(),
               "proposed_last": proposed[-1].tolist()}
        if dry_run:
            row.update(dry_run=True, converted_chunk=converted.tolist())
        live_poses = [state.tolist(), *([status["target"]] if status.get("target") is not None else [])]
        if jaw_spec is not None and (jaw_warn := jaw_zone_error(live_poses, kin, jaw_spec)):
            row["jaw_warning"] = jaw_warn
            if not dry_run:
                return _legacy_jaw_hold(row, n, jaw_warn)
        force_all = jaw_spec is not None and in_jaw_zone(live_poses, kin, jaw_spec)
        try:
            frames_cell = shape_chunk(proposed, state, low, high, fastest)
        except ValueError as error:
            if dry_run:
                row["envelope"] = {"ok": False, "reason": str(error)}
            log({**row, "refused": str(error)})
            if not dry_run:
                log({"command": "park", **_status(cell.act("park"))})
            return {"result": "refused", "at": n, "reason": str(error)}
        if jaw_spec is not None and (jaw_warn := jaw_zone_error(frames_cell, kin, jaw_spec, force_all=force_all)):
            row["jaw_warning"] = jaw_warn
            if not dry_run:
                return _legacy_jaw_hold(row, n, jaw_warn)
        row["frames"] = len(frames_cell)
        if dry_run:
            log({**row, "envelope": {"ok": True}})
            continue
        lib = {**library, "chunks": {**library["chunks"], "policy": frames_cell},
               **({"jaw_gate": {**jaw_spec, "tcp_x_m": resolved_tcp}} if jaw_spec is not None else {})}
        path = work / f"policy-lib-{int(time.time())}-{n}.json"
        path.write_text(json.dumps(lib), encoding="utf-8")
        loaded = cell.act(f"load {path}")
        log({**row, "command": "load", **_status(loaded)})
        if not loaded.get("ok"):
            log({"command": "park", **_status(cell.act("park"))})
            return {"result": "refused", "at": n, "reason": loaded.get("error")}
        ran = cell.act("run policy")
        log({"command": "run policy", **_status(ran), **_moved(state, ran, frames.get("top"), cell, work, n)})
        if ran.get("contact"):
            if "overload-hold" not in (ran.get("error") or ""):
                log({"command": "retreat", **_status(cell.act("retreat"))})
            log({"command": "park", **_status(cell.act("park"))})
            return {"result": "contact", "at": n, "error": ran.get("error")}
        if not ran.get("ok"):
            if not ran.get("fault"):
                log({"command": "park", **_status(cell.act("park"))})
            return {"result": "fault" if ran.get("fault") else "refused", "at": n, "error": ran.get("error")}
        jaws = [f[5] for f in frames_cell]
        # held only on the runner's measured hold: empty jaws parked at closed read as closed (11-19 false release)
        held = held or bool(ran.get("holding"))
        released = held and jaws[-1] > closed + 10.0  # held something, then opened: the place (OMX_RUN_STOP_ON_PLACE)
        if released:
            break
    if dry_run:
        return {"result": "dry_run", "chunks": max_chunks}
    parked = cell.act("park")
    log({"command": "park", **_status(parked)})
    return {"result": "released" if released else "chunks_done", "held": held, "parked": bool(parked.get("ok"))}


def _moved(state, ran: dict, top_before, cell, work: Path, n: int) -> dict:
    """Did the arm move: joint travel the encoders measured and how much the top view changed (mean |diff|, 0-255)."""
    out = {"joint_travel": float(np.abs(np.asarray(ran.get("state") or state, dtype=float) - state).max())}
    try:
        import cv2

        top_after = cell.frame("top")
        out["top_change"] = round(float(np.abs(top_before.astype(np.int16) - top_after.astype(np.int16)).mean()), 2)
        shots = work / "policy-frames"
        shots.mkdir(exist_ok=True)
        cv2.imwrite(str(shots / f"{int(time.time())}-{n}-before.jpg"), top_before)
        cv2.imwrite(str(shots / f"{int(time.time())}-{n}-after.jpg"), top_after)
    except Exception as exc:  # camera evidence never stops the episode
        out["top_change_error"] = str(exc)[:120]
    return out


def _status(status: dict) -> dict:
    return {k: status.get(k) for k in ("ok", "error", "fault", "contact", "holding", "settled", "state")}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", required=True, type=Path, help="the arm's cell-auto config (io, cameras, work_dir)")
    parser.add_argument("--library", required=True, type=Path, help="the arm's reviewed chunk library")
    parser.add_argument("--mode", choices=("act", "hybrid", "taught"), default="act")
    parser.add_argument("--policy-root", type=Path)
    parser.add_argument("--policy-revision", help="sha256 of model.safetensors")
    parser.add_argument("--model-calibration", type=Path, help="LeRobot calibration for a normalized-unit checkpoint")
    parser.add_argument("--cell-calibration", type=Path, help="LeRobot calibration the cell runner uses")
    parser.add_argument("--goal-site", help="Cell job destination site ID, e.g. yard:r3-s2-t1 or tray")
    parser.add_argument("--goal-slot", type=int, help="explicit override for the zero-based checkpoint goal slot")
    parser.add_argument("--max-chunks", type=int, default=3)
    parser.add_argument("--n-action", type=int, help="model steps per inference (sim-unit default: 8)")
    parser.add_argument("--max-obs-age-s", type=float, default=MAX_OBSERVATION_AGE_S)
    parser.add_argument("--operator", required=True, help="named person who approved this run")
    parser.add_argument("--person-at-switch", action="store_true", help="D-911: a person stands at the power switch")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--catalog", type=Path, help="with --roi and --site: count the source's objects before and after")
    parser.add_argument("--roi", type=int, nargs=4)
    parser.add_argument("--site")
    args = parser.parse_args(argv)
    if not args.dry_run and not args.person_at_switch:
        parser.error("moving the arm needs --person-at-switch (D-911)")
    if not 1 <= args.max_chunks <= 6:
        parser.error("--max-chunks 1..6")
    if args.n_action is not None and args.n_action < 1:
        parser.error("--n-action must be positive")
    if not 0 < args.max_obs_age_s <= 5:
        parser.error("--max-obs-age-s must be in (0, 5]")
    if args.mode != "taught" and not all((args.policy_root, args.policy_revision, args.cell_calibration)):
        parser.error("ACT needs --policy-root, --policy-revision and --cell-calibration")
    if args.mode != "act" and not args.goal_site:
        parser.error("hybrid and taught modes need --goal-site")
    config = json.loads(args.config.read_text(encoding="utf-8"))
    if not config.get("work_dir"):
        config["work_dir"] = str(args.config.parent)
    shadow = None if args.mode == "taught" else lrs.LeRobotShadow(args.policy_root, args.policy_revision, cell_config=config)
    destination = mapped_slot = None
    goal_slot = args.goal_slot
    if args.goal_site is not None:
        if shadow is not None and shadow.goal_size is None and args.mode == "act":
            parser.error("checkpoint has no goal input")
        if shadow is not None and shadow.goal_size is not None and shadow.goal_size != len(GOALS):
            parser.error(f"--goal-site requires the {len(GOALS)}-slot h1 goal input")
        try:
            destination, mapped_slot = resolve_goal_site(args.goal_site)
        except (ValueError, OSError) as error:
            parser.error(str(error))
        if goal_slot is None and shadow is not None and shadow.goal_size is not None:
            goal_slot = mapped_slot
        if args.mode == "hybrid" and goal_slot is not None and goal_slot != mapped_slot:
            parser.error("hybrid ACT goal must match the taught destination")
    if shadow is not None and shadow.goal_size is not None:
        if goal_slot is None or not 0 <= goal_slot < shadow.goal_size:
            parser.error(f"checkpoint requires --goal-site or --goal-slot 0..{shadow.goal_size - 1}")
    elif goal_slot is not None:
        parser.error("checkpoint has no goal input")
    cell_cal = json.loads(args.cell_calibration.read_text(encoding="utf-8")) if shadow else {}
    if shadow is not None and shadow.sim_rule is None:
        if args.model_calibration is None:
            parser.error("normalized-unit checkpoint requires --model-calibration")
        offset = calibration_offset(json.loads(args.model_calibration.read_text(encoding="utf-8")), cell_cal)
    else:
        for name in lrs.JOINT_NAMES[:-1] if shadow else ():
            if (cell_cal[name]["range_min"], cell_cal[name]["range_max"]) != (0, 4095):
                parser.error(f"{name}: sim-unit checkpoint requires the trained 0..4095 body tick range")
        offset = [0.0] * JOINTS

    import cell_pipeline as cp

    work = Path(config.get("work_dir") or args.config.parent).expanduser()
    work.mkdir(parents=True, exist_ok=True)
    cell = cp.FifoCell(Path(config["io"]).expanduser(), config["cameras"])
    log_path = work / "policy-drive.jsonl"
    run_id = f"{int(time.time())}"

    def log(row):
        with log_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"run": run_id, "t": time.time(), "operator": args.operator,
                                     "policy_revision": args.policy_revision, "offset": offset, **row}, default=str) + "\n")

    log({"start": True, "mode": args.mode, "dry_run": args.dry_run, "person_at_switch": args.person_at_switch,
         "max_chunks": args.max_chunks, "n_action": args.n_action, "max_obs_age_s": args.max_obs_age_s,
         "goal_slot": goal_slot, "goal_site": args.goal_site, "goal_destination": destination,
         "goal_site_slot": mapped_slot, "units_sha256": shadow.files.get(lrs.UNITS) if shadow else None})
    from cell_policy_handoff import Authorization, CellHandoff, run_taught, validate_taught_goal
    import cell_params as prm

    authorize = handoff = rim_z_m = None
    try:
        config["params"] = prm.load(config.get("params_path"))["values"]
        config.pop("_commissioning", None)
        if not args.dry_run:
            config["_commissioning"] = {"person_at_switch": args.person_at_switch}
            authorize = Authorization(config)
        library = json.loads(args.library.read_text(encoding="utf-8"))
        source = args.site or "belt"
        rim_z_m = source_rim_z(config, source, library)
        if args.mode != "act":
            validate_taught_goal(config, source, args.goal_site, destination, library)
            if args.mode == "hybrid":
                if "plan" not in config:
                    config["plan"] = json.loads(Path(config["plan_path"]).expanduser().read_text(encoding="utf-8"))
                closed = closed_gripper(library)
                if shadow.sim_rule is not None:
                    closed = converted_closed(closed, shadow.sim_rule)
                handoff = CellHandoff(config, source, args.library, library, closed + 1, work)
    except (OSError, ValueError, KeyError, SystemExit) as error:
        parser.error(str(error))
    look = None
    if args.catalog and args.roi and args.site:
        import cell_auto_pick_plan

        calibration = json.loads(Path(config["calibration_path"]).expanduser().read_text(encoding="utf-8"))
        catalog = json.loads(args.catalog.read_text(encoding="utf-8"))
        catalog = catalog.get("objects", catalog) if isinstance(catalog, dict) else catalog

        def look():  # camera only, as cell_task_exec.source_clearance; a failure reads as unknown
            try:
                _img, _mask, objects, error = cell_auto_pick_plan.observe(cell, config, calibration, args.site,
                                                                          tuple(args.roi), catalog)
                return {"objects": None if error else len(objects), "error": error}
            except Exception as exc:
                return {"objects": None, "error": str(exc)[:120]}
    before = look() if look else None
    if before is not None and before.get("objects") == 0 and not args.dry_run:
        result = {"result": "nothing_to_pick", "source": {"before": 0}}  # the camera sees no object: no motion
        log({"end": True, **result})
        print(json.dumps(result))
        return 1
    if args.mode == "taught":
        try:
            result = run_taught(cell, args.library, dry_run=args.dry_run, authorize=authorize, log=log)
        except (OSError, ValueError, KeyError) as error:
            result = {"result": "refused", "reason": str(error)}
    else:
        import omx_tcp

        demonstrated = demonstrated_range(args.policy_root, offset) if shadow.sim_rule is None else None
        result = run_episode(cell, shadow, args.library, work, offset=offset, max_chunks=args.max_chunks,
                             dry_run=args.dry_run, log=log, demonstrated=demonstrated, goal_slot=goal_slot,
                             n_action=args.n_action, max_obs_age_s=args.max_obs_age_s, handoff=handoff,
                             authorize=authorize, params=config.get("params"), tcp_x_m=omx_tcp.config_tcp(config),
                             rim_z_m=rim_z_m)
    if look:
        after = look()
        result["source"] = {"before": before.get("objects"), "after": after.get("objects")}
        if None not in result["source"].values():
            result["took_one"] = result["source"]["after"] < result["source"]["before"]
    log({"end": True, **result})
    print(json.dumps(result))
    return 0 if result["result"] in ("released", "chunks_done", "dry_run", "placed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
