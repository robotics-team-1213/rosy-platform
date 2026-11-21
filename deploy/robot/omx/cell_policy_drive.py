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
Each chunk is inferred from fresh frames and state, run, then the next one; contact -> retreat + park, a fault or a
refusal -> park, the episode ends parked. Needs --person-at-switch (D-911) and a named operator; every chunk and
status goes to policy-drive.jsonl. --dry-run infers and checks without loading or running anything."""
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

MARGIN = 3.0  # units outside the reviewed per-joint range still allowed (sensor and settle noise)
JOINTS = len(lrs.JOINT_NAMES)
SCALE = {name: 200.0 for name in lrs.JOINT_NAMES[:-1]} | {"gripper": 100.0}  # LeRobot omx: body M100_100, gripper 0_100
SIM_POLICY_FPS = 15  # mix-1121 ACT dataset


def calibration_offset(model_cal: dict, cell_cal: dict) -> list[float]:
    """Model units minus cell units per joint: Present_Position carries the homing offset, so a different homing shifts
    every reading by (model_homing - cell_homing) ticks."""
    offset = []
    for name in lrs.JOINT_NAMES:
        m, c = model_cal[name], cell_cal[name]
        if (m["range_min"], m["range_max"], m["drive_mode"]) != (c["range_min"], c["range_max"], c["drive_mode"]):
            raise ValueError(f"{name}: range or drive mode differ, not a pure homing shift")
        span = float(m["range_max"] - m["range_min"])
        offset.append((float(m["homing_offset"]) - float(c["homing_offset"])) * SCALE[name] / span)
    return offset


def envelope(library: dict) -> tuple[list[float], list[float], float]:
    """(per-joint min, max, fastest step) over every frame of the reviewed library's chunks."""
    frames = [f for chunk in library["chunks"].values() for f in chunk if len(f) == JOINTS]
    if not frames:
        raise ValueError("reviewed library has no 6-joint frames")
    arr = np.asarray(frames, dtype=float)
    steps = [np.abs(np.diff(np.asarray(c, dtype=float)[:, :5], axis=0)).max()
             for c in library["chunks"].values() if len(c) > 1]
    return arr.min(axis=0).tolist(), arr.max(axis=0).tolist(), float(max(steps))


def demonstrated_range(policy_root: Path, offset) -> tuple[list[float], list[float]]:
    """Per-joint q01..q99 of the actions the model was trained on (recorded by a person on this arm), in cell units."""
    from safetensors.numpy import load_file

    files = sorted(Path(policy_root).glob("policy_preprocessor_step_*_normalizer_processor.safetensors"))
    if not files:
        raise ValueError("checkpoint has no normalizer statistics")
    stats = load_file(str(files[0]))
    off = np.asarray(offset, dtype=float)
    return (np.asarray(stats["action.q01"], dtype=float) - off).tolist(), (np.asarray(stats["action.q99"], dtype=float) - off).tolist()


def widen(low, high, demo_low, demo_high) -> tuple[list[float], list[float]]:
    """Union of the reviewed IK range and the range a person demonstrated on this arm, per joint."""
    return np.minimum(low, demo_low).tolist(), np.maximum(high, demo_high).tolist()


def open_before_close(chunk, open_g: float, closed: float):
    """IK help for the jaws (11-19: in a new scene the model opened only to 52 = a 30 mm gap, then closed on nothing):
    before the model's close (jaws back at closed after having been open) the jaws are at least the reviewed library's
    widest opening, then the model closes as it chose. A chunk without such a close is left as the model gave it."""
    arr = np.array(chunk, dtype=float)
    g = arr[:, 5]
    was_open = np.maximum.accumulate(g) > closed + 2.0
    closing = np.flatnonzero((g <= closed + 1.0) & was_open)
    if len(closing):
        arr[:closing[0], 5] = np.maximum(g[:closing[0]], open_g)
    return arr


def converted_closed(closed: float, rule: dict) -> float:
    from cell_act_inputs import real_grippers, sim_gripper

    return float(real_grippers([sim_gripper(closed, rule)], rule)[0])


def resample_chunk(chunk, start, library_fps: float) -> np.ndarray:
    """Sample the measured start (t=0) to each predicted row (t=1/15, 2/15, ...)."""
    path = np.vstack([start, chunk])
    ticks = np.arange(1, math.ceil(len(chunk) * library_fps / SIM_POLICY_FPS) + 1)
    times = ticks * SIM_POLICY_FPS / library_fps
    return np.column_stack([np.interp(times, np.arange(len(path)), joint) for joint in path.T])


def wrist_roll_warning(chunk, home_roll: float) -> str | None:
    from arm_status_bridge import TICKS

    # The two trained orientations are a half-turn apart. Accept within 45 degrees of either.
    half_turn = SCALE["wrist_roll"] * TICKS / (TICKS - 1) / 2
    distance = np.abs((chunk[:, 4] - home_roll + half_turn / 2) % half_turn - half_turn / 2)
    between = np.flatnonzero(distance > half_turn / 4)
    if len(between):
        i = between[0]
        return f"arm_b frame {i} wrist_roll={chunk[i, 4]:.2f} lies between trained branches (home={home_roll:.2f})"
    return None


def shape_chunk(chunk, start, low, high, fastest: float) -> list[list[float]]:
    """Cell-unit frames the runner may get: refused outside the envelope, stretched so no body step beats `fastest`."""
    arr = np.asarray(chunk, dtype=float)
    if arr.ndim != 2 or arr.shape[1] != JOINTS or not np.isfinite(arr).all():
        raise ValueError("policy chunk is not finite (n, 6)")
    lo, hi = np.asarray(low) - MARGIN, np.asarray(high) + MARGIN
    outside = np.argwhere((arr < lo) | (arr > hi))
    if len(outside):
        i, j = outside[0]
        raise ValueError(f"frame {i} {lrs.JOINT_NAMES[j]}={arr[i, j]:.1f} outside reviewed {lo[j]:.1f}..{hi[j]:.1f}")
    path = np.vstack([np.asarray(start, dtype=float)[None, :], arr])
    out = []
    for a, b in zip(path[:-1], path[1:]):
        n = max(1, math.ceil(float(np.abs(b - a).max()) / fastest - 1e-9))  # all six joints, as the runner checks
        out.extend((a + (b - a) * k / n).tolist() for k in range(1, n + 1))
    return out


def run_episode(cell, shadow, library_path: Path, work: Path, *, offset, max_chunks: int, dry_run: bool, log,
                demonstrated=None, goal_slot: int | None = None) -> dict:
    library = json.loads(library_path.read_text(encoding="utf-8"))
    low, high, fastest = envelope(library)
    fps = float(library.get("fps", 30))
    fastest = min(fastest, GUARD_UNITS_PER_S / fps)  # the runner refuses any frame step past this
    sim_units = getattr(shadow, "sim_rule", None) is not None
    if demonstrated is not None and not sim_units:
        low, high = widen(low, high, *demonstrated)
    closed = float(library.get("jaw_empty_stop", library["gripper_closed"]))
    model_closed = converted_closed(closed, shadow.sim_rule) if sim_units else closed
    home_roll = None
    if sim_units:
        steps = shadow.n_action_steps
        if type(steps) is not int or steps < 1:
            raise ValueError("sim-unit checkpoint requires a positive integer n_action_steps")
        if shadow.arm_id == "arm_b":
            home = library["chunks"].get("home")
            if not home or len(home[-1]) != JOINTS:
                raise ValueError("arm_b reviewed library requires a six-joint home frame")
            home_roll = float(home[-1][4])
            if not math.isfinite(home_roll):
                raise ValueError("arm_b reviewed library requires a finite home wrist roll")
    open_g = max(f[5] for chunk in library["chunks"].values() for f in chunk if len(f) == JOINTS)
    off = np.asarray(offset, dtype=float)
    goal = {} if goal_slot is None else {"goal": goal_slot}
    held, released = False, False
    for n in range(max_chunks):
        status = cell.act("state")
        state = np.asarray(status["state"], dtype=float)
        frames = {view: cell.frame(view) for view in shadow.image_views}
        obs, meta = shadow.inputs(state.tolist() if sim_units else (state + off).tolist(), frames, **goal)
        if sim_units:
            converted = np.asarray(shadow.infer(obs, state=state).chunk, dtype=float)
        else:
            converted = np.asarray(shadow.infer(obs).chunk, dtype=float) - off
        proposed = converted[:steps] if sim_units else converted
        if not held:
            proposed = open_before_close(proposed, open_g, model_closed)
        row = {"chunk": n, "state": state.tolist(), "meta": meta, "proposed_first": proposed[0].tolist(),
               "proposed_last": proposed[-1].tolist()}
        if sim_units:
            row.update(model_fps=SIM_POLICY_FPS, library_fps=fps, action_steps=len(proposed))
        if dry_run:
            row.update(dry_run=True, converted_chunk=converted.tolist())
        try:
            if home_roll is not None and (warning := wrist_roll_warning(converted, home_roll)):
                row["wrist_roll_warning"] = warning
                if not dry_run:
                    raise ValueError(warning)
            if sim_units:
                proposed = resample_chunk(proposed, state, fps)
            frames_cell = shape_chunk(proposed, state, low, high, fastest)
        except ValueError as error:
            if dry_run:
                row["envelope"] = {"ok": False, "reason": str(error)}
            log({**row, "refused": str(error)})
            if not dry_run:
                log({"command": "park", **_status(cell.act("park"))})
            return {"result": "refused", "at": n, "reason": str(error)}
        row["frames"] = len(frames_cell)
        if dry_run:
            log({**row, "envelope": {"ok": True}})
            continue
        lib = {**library, "chunks": {**library["chunks"], "policy": frames_cell}}
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
    parser.add_argument("--policy-root", required=True, type=Path)
    parser.add_argument("--policy-revision", required=True, help="sha256 of model.safetensors")
    parser.add_argument("--model-calibration", type=Path, help="LeRobot calibration for a normalized-unit checkpoint")
    parser.add_argument("--cell-calibration", required=True, type=Path, help="LeRobot calibration the cell runner uses")
    parser.add_argument("--goal-site", help="Cell job destination site ID, e.g. yard:r3-s2-t1 or tray")
    parser.add_argument("--goal-slot", type=int, help="explicit override for the zero-based checkpoint goal slot")
    parser.add_argument("--max-chunks", type=int, default=3)
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
    config = json.loads(args.config.read_text(encoding="utf-8"))
    if not config.get("work_dir"):
        config["work_dir"] = str(args.config.parent)
    shadow = lrs.LeRobotShadow(args.policy_root, args.policy_revision, cell_config=config)
    destination = mapped_slot = None
    goal_slot = args.goal_slot
    if args.goal_site is not None:
        if shadow.goal_size is None:
            parser.error("checkpoint has no goal input")
        if shadow.goal_size != len(GOALS):
            parser.error(f"--goal-site requires the {len(GOALS)}-slot h1 goal input")
        try:
            destination, mapped_slot = resolve_goal_site(args.goal_site)
        except (ValueError, OSError) as error:
            parser.error(str(error))
        if goal_slot is None:
            goal_slot = mapped_slot
    if shadow.goal_size is not None:
        if goal_slot is None or not 0 <= goal_slot < shadow.goal_size:
            parser.error(f"checkpoint requires --goal-site or --goal-slot 0..{shadow.goal_size - 1}")
    elif goal_slot is not None:
        parser.error("checkpoint has no goal input")
    cell_cal = json.loads(args.cell_calibration.read_text(encoding="utf-8"))
    if shadow.sim_rule is None:
        if args.model_calibration is None:
            parser.error("normalized-unit checkpoint requires --model-calibration")
        offset = calibration_offset(json.loads(args.model_calibration.read_text(encoding="utf-8")), cell_cal)
    else:
        for name in lrs.JOINT_NAMES[:-1]:
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

    log({"start": True, "dry_run": args.dry_run, "person_at_switch": args.person_at_switch, "max_chunks": args.max_chunks,
         "goal_slot": goal_slot, "goal_site": args.goal_site, "goal_destination": destination,
         "goal_site_slot": mapped_slot, "units_sha256": shadow.files.get(lrs.UNITS)})
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
    demonstrated = demonstrated_range(args.policy_root, offset) if shadow.sim_rule is None else None
    result = run_episode(cell, shadow, args.library, work, offset=offset, max_chunks=args.max_chunks,
                         dry_run=args.dry_run, log=log, demonstrated=demonstrated, goal_slot=goal_slot)
    if look:
        after = look()
        result["source"] = {"before": before.get("objects"), "after": after.get("objects")}
        if None not in result["source"].values():
            result["took_one"] = result["source"]["after"] < result["source"]["before"]
    log({"end": True, **result})
    print(json.dumps(result))
    return 0 if result["result"] in ("released", "chunks_done", "dry_run") else 1


if __name__ == "__main__":
    raise SystemExit(main())
