#!/usr/bin/env python3
"""Run cell tasks for one arm from a queue directory: the arm-side end of "ROSY gives a task, the arm does it".

A task is one JSON file in <queue>/inbox/ (rosy.omx-cell-task.v1):
  {"schema", "task_id", "kind": "move" | "swap", "source": "operator" | "decision" | "vla", "record": bool,
   move: "from", "to";  swap: "a", "b" (two sites holding the two objects), "buffer" (a free site)}
The runner moves it to running/, checks the cell (cell_preflight), runs each carry with cell_auto_pick (one object
per source site: the pipeline picks the usable object there), stops at the first carry that is not "placed", and
writes done/<task_id>.result.json. Safety stays on this host: the pipeline's own refusals, guards and holds apply.
A swap is three carries through the buffer: a -> buffer, b -> a, buffer -> b.

  cell_task_runner.py --config cell-auto.json --catalog catalog.json --queue ~/rosy-cell-tasks [--once]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

SCHEMA = "rosy.omx-cell-task.v1"
HERE = Path(__file__).resolve().parent


def carries(task: dict, sites: dict) -> list:
    """[(from, to)] for a task, or ValueError naming what is wrong (unknown site, same site, missing field)."""
    if task.get("schema") != SCHEMA or not task.get("task_id"):
        raise ValueError(f"not a {SCHEMA} task")
    if task["kind"] == "move":
        plan = [(task["from"], task["to"])]
    elif task["kind"] == "swap":
        a, b, buf = task["a"], task["b"], task["buffer"]
        if len({a, b, buf}) < 3:
            raise ValueError("swap needs two sites and a distinct free buffer site")
        plan = [(a, buf), (b, a), (buf, b)]
    else:
        raise ValueError(f"unknown kind {task['kind']!r}")
    for src, dst in plan:
        for site in (src, dst):
            if site not in sites:
                raise ValueError(f"unknown site {site!r}")
        if src == dst:
            raise ValueError(f"from and to are both {src!r}")
        if not sites[src].get("auto_roi"):
            raise ValueError(f"site {src!r} has no auto_roi to look in")
    return plan


def run_carry(config_path: Path, catalog: Path, sites: dict, src: str, dst: str, log_dir: Path, run=subprocess.run) -> dict:
    roi = [str(v) for v in sites[src]["auto_roi"]]
    out = log_dir / f"{int(time.time())}-{src}-to-{dst}.json"
    proc = run([sys.executable, str(HERE / "cell_auto_pick.py"), "--config", str(config_path), "--catalog", str(catalog),
                "--roi", *roi, "--from", src, "--dest", dst], capture_output=True, text=True)
    try:
        result = json.loads(proc.stdout[proc.stdout.find("{"):])
    except ValueError:
        result = {"result": f"no result (exit {proc.returncode}): {proc.stderr[-200:]}"}
    out.write_text(json.dumps(result))
    return {"from": src, "to": dst, "result": result.get("result"), "log": str(out)}


def run_task(task: dict, config_path: Path, catalog: Path, log_dir: Path, preflight=None, carry=run_carry) -> dict:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    out = {"task_id": task.get("task_id"), "kind": task.get("kind"), "source": task.get("source"), "started": time.time(), "steps": []}
    try:
        plan = carries(task, config["sites"])
    except (ValueError, KeyError) as exc:
        return {**out, "status": "rejected", "why": str(exc)}
    if preflight is not None:
        failed = [f"{name}: {why}" for name, ok, why in preflight(config) if not ok]
        if failed:
            return {**out, "status": "refused", "why": failed}
    for src, dst in plan:
        step = carry(config_path, catalog, config["sites"], src, dst, log_dir)
        out["steps"].append(step)
        if step["result"] != "placed":  # a stop mid-swap leaves the objects where the last carry put them: a person looks
            return {**out, "status": "stopped", "why": f"{src} -> {dst}: {step['result']}", "ended": time.time()}
    return {**out, "status": "done", "ended": time.time()}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--config", required=True, type=Path)
    ap.add_argument("--catalog", required=True, type=Path)
    ap.add_argument("--queue", required=True, type=Path)
    ap.add_argument("--once", action="store_true", help="run what is in the inbox now, then exit")
    args = ap.parse_args(argv)
    import cell_preflight

    for name in ("inbox", "running", "done"):
        (args.queue / name).mkdir(parents=True, exist_ok=True)
    while True:
        for path in sorted((args.queue / "inbox").glob("*.json")):
            running = args.queue / "running" / path.name
            path.replace(running)  # claimed: a second runner will not pick it up
            task = json.loads(running.read_text(encoding="utf-8"))
            result = run_task(task, args.config, args.catalog, args.queue / "done",
                              lambda c: cell_preflight.checks(c, "http://127.0.0.1:8767", 6.0))
            (args.queue / "done" / f"{task.get('task_id', path.stem)}.result.json").write_text(json.dumps(result, indent=1))
            running.unlink()
            print(json.dumps({k: result.get(k) for k in ("task_id", "status", "why")}), flush=True)
        if args.once:
            return 0
        time.sleep(2)


if __name__ == "__main__":
    sys.path.insert(0, str(HERE))
    sys.exit(main())
