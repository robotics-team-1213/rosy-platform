#!/usr/bin/env python3
"""One submitted job, one arm session, one lock: precheck, home when needed, then the ACT drive, with one receipt.

2026-11-26: a real run was queued as home, calibrate_check, a dry run and a drive. Each took the session and the arm lock
again (~100 s apiece) and a dry run outside a session read an idle joint file (always stale). Here the session wrapper
starts once and every stage runs in it:
  1. precheck, no motion: payload and operating envelope, library, the running session is clean and live, every camera
     answers a new frame (a few quick retries for a transient bad JPEG);
  2. home, only when the arm is off the library's home pose;
  3. cell_policy_drive: its own one-chunk dry run (start gate, shaping, inference), entry chunk, policy chunks, park.
A refusal at any stage says which one and why; a drive failure keeps the drive's own retreat, park and human-hold path.
person_at_switch, commissioning, D-1024 approval and the arm lease are unchanged: the job API and the drive still ask.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cell_policy_entry import ENTRY_START_TOL, FAULT_KEYS, max_diff, pose6, valid_state  # noqa: E402

SUCCESS = ("released", "chunks_done", "placed")
CAMERA_TRIES, CAMERA_WAIT_S, CAMERA_MAX_AGE_S, LIVE_MAX_AGE_S = 3, 1.0, 2.0, 2.0


def precheck(config: dict, library: dict, cell, *, wall=time.time, sleep=time.sleep) -> dict:
    """No motion. {"ok": True, ...facts} or {"ok": False, "code", "reason"}."""
    import cell_envelope
    import cell_params

    try:
        config = {**config, "params": cell_params.load(config.get("params_path"))["values"]}
        _facts, over = cell_envelope.payload_check(config, cell_envelope._conditions(config))
    except (OSError, ValueError, TypeError, KeyError) as error:
        over = str(error)
    if over:
        return {"ok": False, "code": "envelope", "reason": f"operating envelope: {over}"}
    if not isinstance(library.get("chunks"), dict) or pose6((library["chunks"].get("home") or [None])[-1]) is None:
        return {"ok": False, "code": "library", "reason": "library has no six-joint home chunk"}
    live = cell.policy_state()
    stamp = live.get("t") if isinstance(live, dict) else None
    if not isinstance(stamp, (int, float)) or isinstance(stamp, bool) or not 0 <= wall() - stamp <= LIVE_MAX_AGE_S:
        return {"ok": False, "code": "no_session", "reason": "no running arm session: live joint state missing or old"}
    if bad := [k for k in FAULT_KEYS if live.get(k)]:  # never retried: a person clears a hold or fault
        return {"ok": False, "code": "safety_state", "reason": f"session is in a safety state ({', '.join(bad)}): {live.get('fault') or ''}".strip()}
    ages = {}
    for name, spec in (config.get("cameras") or {}).items():
        if isinstance(spec, dict) and spec.get("optional"):
            continue
        for attempt in range(1, CAMERA_TRIES + 1):
            try:
                frame = cell.frame_receipt(name, max_age_s=CAMERA_MAX_AGE_S, timeout_s=3.0)
                ages[name] = round(wall() - frame["source_stamp"], 3)
                break
            except (OSError, ValueError, KeyError) as error:
                if attempt == CAMERA_TRIES:
                    return {"ok": False, "code": "camera", "reason": f"camera {name} gave no new frame in {CAMERA_TRIES} tries: {str(error)[:120]}"}
                sleep(CAMERA_WAIT_S)
    return {"ok": True, "cameras": ages}


def home_needed(cell, library: dict) -> dict:
    state = cell.act("state")
    ok, _held, error = valid_state(state)
    if not ok:
        return {"ok": False, "code": "state", "reason": f"arm state unavailable before home check: {error}"}
    return {"ok": True, "needed": max_diff(state["state"], pose6(library["chunks"]["home"][-1]), 5) > ENTRY_START_TOL}


def home_stage(home_fn) -> dict:
    code, out = home_fn()
    return {"ok": code == 0 and out.get("result") == "home", "result": out.get("result"), **({"receipt": out["receipt"]} if "receipt" in out else {})}


def preflight_seconds(log_path: Path, since: float) -> float | None:
    """Seconds from the drive's start row to its last dry-run row, from this run's policy-drive.jsonl rows."""
    try:
        rows = [r for r in map(json.loads, log_path.read_text(encoding="utf-8").splitlines()[-400:]) if r.get("t", 0) >= since]
        start = next(r["t"] for r in rows if r.get("start"))
        return round(max(r["t"] for r in rows if r.get("preflight")) - start, 2)
    except (OSError, ValueError, StopIteration, KeyError, TypeError):
        return None


def run(config, library, cell, drive_argv, *, home_fn, drive_fn, log_path=None, env=os.environ,
        clock=time.monotonic, wall=time.time, sleep=time.sleep) -> tuple[int, dict]:
    receipt = {"schema": "rosy.omx-policy-run.v1", "stages": []}
    began = clock()

    def finish(result: str, reason: str | None = None, **extra) -> tuple[int, dict]:
        receipt.update({"result": result, **({"reason": reason} if reason else {}), **extra, "total_s": round(clock() - began, 2)})
        return (0 if result in SUCCESS and receipt.get("parked") is not False else 1), receipt

    def stage(name: str, fn) -> dict:
        t0 = clock()
        out = fn()
        receipt["stages"].append({"stage": name, "s": round(clock() - t0, 2), **out})
        return out

    up = env.get("ROSY_SESSION_UP_S")  # set by the session wrapper: seconds spent starting or waiting for the session
    receipt["stages"].append({"stage": "session", "ok": True, "s": float(up) if up else None,
                              "attempts": int(env["ROSY_SESSION_ATTEMPTS"]) if env.get("ROSY_SESSION_ATTEMPTS") else None})
    if not (out := stage("precheck", lambda: precheck(config, library, cell, wall=wall, sleep=sleep)))["ok"]:
        return finish("refused", f"precheck: {out['reason']}", stage="precheck", code=out["code"], moved=False)
    if not (need := stage("home_check", lambda: home_needed(cell, library)))["ok"]:
        return finish("refused", need["reason"], stage="home_check", code=need["code"], moved=False)
    if need["needed"]:
        if not (home := stage("home", lambda: home_stage(home_fn)))["ok"]:
            return finish("refused", f"home: {home.get('result') or 'failed'}", stage="home", code="home", moved=True)
    drive_start = wall()
    t0 = clock()
    code, drive = drive_fn(drive_argv)
    row = {"stage": "drive", "s": round(clock() - t0, 2), "ok": code == 0, "result": drive.get("result")}
    if log_path is not None and (pre := preflight_seconds(Path(log_path), drive_start)) is not None:
        row["preflight_dry_run_s"] = pre
    receipt["stages"].append(row)
    keep = {k: v for k, v in drive.items() if k not in ("stages", "total_s", "schema")}
    receipt.update(keep)
    return finish(drive.get("result") or "error", drive.get("reason"), stage="drive")


def _call(main, argv) -> tuple[int, dict]:
    """Run a sibling tool's main() in this process; its last JSON line is the result."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = main(argv)
        except SystemExit as stop:
            code = stop.code if isinstance(stop.code, int) else 2
        except Exception as error:  # the tool's own hold/park paths ran; report, never traceback past the receipt
            code, err = 1, io.StringIO(f"{type(error).__name__}: {error}")
    sys.stderr.write(err.getvalue()[-2000:])
    for line in reversed(out.getvalue().splitlines()):
        try:
            result = json.loads(line)
        except ValueError:
            continue
        if isinstance(result, dict):
            return code, result
    return code, {"result": "error", "reason": (err.getvalue().strip().splitlines() or ["no result line"])[-1][:240]}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--config", required=True, type=Path)
    ap.add_argument("--library", required=True, type=Path)
    ap.add_argument("--operating-profile", required=True, type=Path)
    ap.add_argument("--person-at-switch", action="store_true")
    args, rest = ap.parse_known_args(argv)
    if not args.person_at_switch:
        ap.error("moving the arm needs --person-at-switch (D-911)")
    if "--dry-run" in rest:
        ap.error("cell_policy_run always runs; its dry-run check is built in (use cell_policy_drive --dry-run)")
    import cell_pipeline
    import cell_policy_drive
    from cell_pipeline_io import FifoCell

    config = json.loads(args.config.read_text(encoding="utf-8"))
    library = json.loads(args.library.read_text(encoding="utf-8"))
    raw_io = Path(config["io"]).expanduser()
    cell = FifoCell(raw_io if raw_io.is_absolute() else args.config.parent / raw_io, config.get("cameras") or {})
    work = Path(config.get("work_dir") or args.config.parent).expanduser()
    home = ["--config", str(args.config), "--stage", "home", "--library", str(args.library),
            "--operating-profile", str(args.operating_profile), "--commissioning", "--person-at-switch"]
    code, receipt = run(config, library, cell, ["--config", str(args.config), "--library", str(args.library), *rest, "--person-at-switch"],
                        home_fn=lambda: _call(cell_pipeline.main, home), drive_fn=lambda a: _call(cell_policy_drive.main, a),
                        log_path=work / "policy-drive.jsonl")
    try:
        (work / "receipts").mkdir(parents=True, exist_ok=True)
        (work / "receipts" / f"{time.strftime('%Y%m%dT%H%M%S')}-policy-run.json").write_text(json.dumps(receipt, indent=1, default=str), encoding="utf-8")
    except OSError:
        pass
    print(json.dumps(receipt, default=str))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
