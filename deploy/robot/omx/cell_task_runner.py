#!/usr/bin/env python3
"""Run cell tasks for one arm from a queue directory: the arm-side end of "ROSY gives a task, the arm does it".

A task is one JSON file in <queue>/inbox/ (rosy.omx-cell-task.v1):
  {"schema", "task_id", "kind": "move" | "swap", "source": "operator" | "decision" | "vla", "record": bool,
   move: "from", "to";  swap: "a", "b" (two sites holding the two objects), "buffer" (a free site)}
The runner moves it to running/, checks the cell (cell_preflight), runs each carry with cell_auto_pick (one object
per source site: the pipeline picks the usable object there), stops at the first carry that is not "placed", and
writes done/<task_id>.result.json. Safety stays on this host: the pipeline's own refusals, guards and holds apply.
A swap is three carries through the buffer: a -> buffer, b -> a, buffer -> b.
A carry that stops before any motion because the destination has no room tries that site's config
"alternates" in order (D-1019); the Gate still holds any path not reviewed, so a redirect never widens D-911.

  cell_task_runner.py --config cell-auto.json --catalog catalog.json --queue ~/rosy-cell-tasks [--once]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

import cell_place_fit

SCHEMA = "rosy.omx-cell-task.v1"
HERE = Path(__file__).resolve().parent


def tier_site(site: str, tier: int, sites: dict) -> str:
    """Resolve `site` at `tier` (1 = 1단/-l0, 2 = 2단/-l1, 3 = 3단/-l2)."""
    if tier not in cell_place_fit.TIERS:
        raise ValueError(f"tier must be in {cell_place_fit.TIERS}, got {tier!r}")
    name = f"{site}-l{tier - 1}"
    return name if name in sites else site


def carries(task: dict, sites: dict) -> list:
    """[(from, to)] for a task, or ValueError naming what is wrong (unknown site, same site, missing field)."""
    if task.get("schema") != SCHEMA or not task.get("task_id"):
        raise ValueError(f"not a {SCHEMA} task")
    sites = cell_place_fit.with_tiers({"sites": sites})[0]["sites"]
    if task["kind"] == "move":
        src = tier_site(task["from"], task["from_tier"], sites) if "from_tier" in task else task["from"]
        dst = tier_site(task["to"], task["to_tier"], sites) if "to_tier" in task else task["to"]
        plan = [(src, dst)]
    elif task["kind"] == "swap":
        a, b, buf = task["a"], task["b"], task["buffer"]
        if len({a, b, buf}) < 3:
            raise ValueError("swap needs two sites and a distinct free buffer site")
        plan = [(a, buf), (b, a), (buf, b)]
    elif task["kind"] == "shuttle":
        a, b = task["a"], task["b"]
        if a == b:
            raise ValueError("shuttle needs two distinct sites")
        cycles = int(task.get("cycles") or 1)
        if cycles < 1:
            raise ValueError("shuttle cycles must be >= 1")
        plan = [pair for _ in range(cycles) for pair in ((a, b), (b, a))]
        if task.get("legs") is not None:
            plan = plan[: max(1, int(task["legs"]))]
    elif task["kind"] in ("stack", "unstack"):
        tiers = [task["tier"]] if "tier" in task else list(task.get("tiers") or cell_place_fit.TIERS)
        if not tiers or any(t not in cell_place_fit.TIERS for t in tiers):
            raise ValueError(f"tiers must be in {cell_place_fit.TIERS}")
        cols = list(task.get("columns") or [task["to" if task["kind"] == "stack" else "from"]])
        if task["kind"] == "stack":
            srcs = list(task.get("sources") or [task["from"]] * (len(tiers) * len(cols)))
            targets = [f"{c}-l{t - 1}" for t in tiers for c in cols]
            if len(srcs) < len(targets):
                raise ValueError("not enough sources for stack targets")
            plan = list(zip(srcs[:len(targets)], targets))
        else:
            sources = [f"{c}-l{t - 1}" for t in reversed(tiers) for c in cols]
            dsts = list(task.get("destinations") or [task["to"]] * len(sources))
            if len(dsts) < len(sources):
                raise ValueError("not enough destinations for unstack sources")
            plan = list(zip(sources, dsts[:len(sources)]))
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
    refused = ((result.get("attempts") or [{}])[-1]).get("refused") or []
    # Stopped at the choice with every object refused only for room at the destination: nothing moved.
    dest_full = str(result.get("result", "")).startswith("stopped") and bool(refused) and all(
        str(r.get("why", "")).startswith("place:") for r in refused)
    return {"from": src, "to": dst, "result": result.get("result"), "log": str(out), "dest_full": dest_full}


def alternates(sites: dict, src: str, dst: str) -> list:
    """The destination's declared fallback sites, in order (D-1019): known sites other than the carry's own."""
    return [a for a in (sites.get(dst) or {}).get("alternates") or [] if a in sites and a not in (src, dst)]


def run_task(task: dict, config_path: Path, catalog: Path, log_dir: Path, preflight=None, carry=run_carry) -> dict:
    config = cell_place_fit.with_tiers(json.loads(config_path.read_text(encoding="utf-8")))[0]
    out = {"task_id": task.get("task_id"), "kind": task.get("kind"), "source": task.get("source"), "started": time.time(), "steps": []}
    try:
        plan = carries(task, config["sites"])
    except (ValueError, KeyError) as exc:
        return {**out, "status": "rejected", "why": str(exc)}
    if preflight is not None:
        failed = [f"{name}: {why}" for name, ok, why in preflight(config) if not ok]
        if failed:
            return {**out, "status": "refused", "why": failed}
    for i, (src, dst) in enumerate(plan):
        step = carry(config_path, catalog, config["sites"], src, dst, log_dir)
        out["steps"].append(step)
        # No room at the destination and nothing moved: its declared alternates, each observed afresh (D-1019).
        for alt in alternates(config["sites"], src, dst) if step.get("dest_full") else ():
            step = {**carry(config_path, catalog, config["sites"], src, alt, log_dir), "redirected_from": dst}
            out["steps"].append(step)
            if not step.get("dest_full"):
                break
        if step["result"] != "placed":  # a stop mid-swap leaves the objects where the last carry put them: a person looks
            return {**out, "status": "stopped", "why": f"{src} -> {step['to']}: {step['result']}", "ended": time.time()}
        # The next carry that expected this object at dst takes it from where it went; later ones are other objects.
        nxt = next((j for j in range(i + 1, len(plan)) if plan[j][0] == dst), None) if step.get("redirected_from") else None
        if nxt is not None:
            plan[nxt] = (step["to"], plan[nxt][1])
    return {**out, "status": "done", "ended": time.time()}


from cell_fleet_pipeline import FleetModelPipeline  # noqa: E402,F401  (re-exported)


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
