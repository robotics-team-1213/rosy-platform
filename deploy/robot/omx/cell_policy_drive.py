#!/usr/bin/env python3
"""Drive one arm with a pinned LeRobot policy through the chunk runner's own guards (2026-11-18, arm_s first).

The policy's proposed chunk becomes a chunk named `policy` in a copy of the arm's reviewed library, so the runner applies
the same `load` plan_check, start-gap check, speed/strain/jitter guards and holds as for an IK chunk; the IK chunks
(`home`, transfer chunks) stay in the same library, which is how a policy segment and IK segments mix. On top:
- every policy frame must lie inside the per-joint range the reviewed library's chunks already cover (+ margin);
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

MARGIN = 3.0  # units outside the reviewed per-joint range still allowed (sensor and settle noise)
JOINTS = len(lrs.JOINT_NAMES)
SCALE = {name: 200.0 for name in lrs.JOINT_NAMES[:-1]} | {"gripper": 100.0}  # LeRobot omx: body M100_100, gripper 0_100


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
        n = max(1, math.ceil(float(np.abs(b[:5] - a[:5]).max()) / fastest - 1e-9))
        out.extend((a + (b - a) * k / n).tolist() for k in range(1, n + 1))
    return out


def run_episode(cell, shadow, library_path: Path, work: Path, *, offset, max_chunks: int, dry_run: bool, log) -> dict:
    library = json.loads(library_path.read_text(encoding="utf-8"))
    low, high, fastest = envelope(library)
    closed = float(library.get("jaw_empty_stop", library["gripper_closed"]))
    off = np.asarray(offset, dtype=float)
    held, released = False, False
    for n in range(max_chunks):
        status = cell.act("state")
        state = np.asarray(status["state"], dtype=float)
        frames = {view: cell.frame(view) for view in shadow.image_views}
        obs, meta = shadow.inputs((state + off).tolist(), frames)
        proposed = np.asarray(shadow.infer(obs).chunk, dtype=float) - off
        row = {"chunk": n, "state": state.tolist(), "meta": meta, "proposed_first": proposed[0].tolist(),
               "proposed_last": proposed[-1].tolist()}
        try:
            frames_cell = shape_chunk(proposed, state, low, high, fastest)
        except ValueError as error:
            log({**row, "refused": str(error)})
            if not dry_run:
                log({"command": "park", **_status(cell.act("park"))})
            return {"result": "refused", "at": n, "reason": str(error)}
        row["frames"] = len(frames_cell)
        if dry_run:
            log({**row, "dry_run": True})
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
        log({"command": "run policy", **_status(ran)})
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
        held = held or min(jaws) <= closed + 2.0
        released = held and jaws[-1] > closed + 10.0  # closed on something, then opened: the place (OMX_RUN_STOP_ON_PLACE)
        if released:
            break
    if dry_run:
        return {"result": "dry_run", "chunks": max_chunks}
    parked = cell.act("park")
    log({"command": "park", **_status(parked)})
    return {"result": "released" if released else "chunks_done", "held": held, "parked": bool(parked.get("ok"))}


def _status(status: dict) -> dict:
    return {k: status.get(k) for k in ("ok", "error", "fault", "contact", "holding", "settled", "state")}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", required=True, type=Path, help="the arm's cell-auto config (io, cameras, work_dir)")
    parser.add_argument("--library", required=True, type=Path, help="the arm's reviewed chunk library")
    parser.add_argument("--policy-root", required=True, type=Path)
    parser.add_argument("--policy-revision", required=True, help="sha256 of model.safetensors")
    parser.add_argument("--model-calibration", required=True, type=Path, help="LeRobot calibration the model was recorded with")
    parser.add_argument("--cell-calibration", required=True, type=Path, help="LeRobot calibration the cell runner uses")
    parser.add_argument("--max-chunks", type=int, default=3)
    parser.add_argument("--operator", required=True, help="named person who approved this run")
    parser.add_argument("--person-at-switch", action="store_true", help="D-911: a person stands at the power switch")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if not args.dry_run and not args.person_at_switch:
        parser.error("moving the arm needs --person-at-switch (D-911)")
    if not 1 <= args.max_chunks <= 6:
        parser.error("--max-chunks 1..6")
    import cell_pipeline as cp

    config = json.loads(args.config.read_text(encoding="utf-8"))
    work = Path(config.get("work_dir") or args.config.parent).expanduser()
    work.mkdir(parents=True, exist_ok=True)
    offset = calibration_offset(json.loads(args.model_calibration.read_text()), json.loads(args.cell_calibration.read_text()))
    shadow = lrs.LeRobotShadow(args.policy_root, args.policy_revision)
    cell = cp.FifoCell(Path(config["io"]).expanduser(), config["cameras"])
    log_path = work / "policy-drive.jsonl"
    run_id = f"{int(time.time())}"

    def log(row):
        with log_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"run": run_id, "t": time.time(), "operator": args.operator,
                                     "policy_revision": args.policy_revision, "offset": offset, **row}, default=str) + "\n")

    log({"start": True, "dry_run": args.dry_run, "person_at_switch": args.person_at_switch, "max_chunks": args.max_chunks})
    result = run_episode(cell, shadow, args.library, work, offset=offset, max_chunks=args.max_chunks,
                         dry_run=args.dry_run, log=log)
    log({"end": True, **result})
    print(json.dumps(result))
    return 0 if result["result"] in ("released", "chunks_done", "dry_run") else 1


if __name__ == "__main__":
    raise SystemExit(main())
