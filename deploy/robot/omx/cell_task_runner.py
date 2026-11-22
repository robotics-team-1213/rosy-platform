#!/usr/bin/env python3
"""Run cell tasks for one arm from a queue directory: the arm-side end of "ROSY gives a task, the arm does it".

A task is one JSON file in <queue>/inbox/ (rosy.omx-cell-task.v1):
  {"schema", "task_id", "kind": "move" | "swap", "source": "operator" | "decision" | "vla", "record": bool,
   "scenario_id": optional nonempty string,
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


def plan_steps(task: dict, sites: dict) -> list[dict]:
    """Expanded step dicts for a task, or ValueError naming what is wrong (unknown site, same site, missing field)."""
    if task.get("schema") != SCHEMA or not task.get("task_id"):
        raise ValueError(f"not a {SCHEMA} task")
    if "scenario_id" in task and (not isinstance(task["scenario_id"], str) or not task["scenario_id"]):
        raise ValueError("scenario_id must be a nonempty string")
    sites = cell_place_fit.with_tiers({"sites": sites})[0]["sites"]
    kind = task["kind"]
    if kind == "move":
        src = tier_site(task["from"], task["from_tier"], sites) if "from_tier" in task else task["from"]
        dst = tier_site(task["to"], task["to_tier"], sites) if "to_tier" in task else task["to"]
        steps = [{"from": src, "to": dst, "redirectable": True}]
    elif kind == "swap":
        a, b, buf = task["a"], task["b"], task["buffer"]
        if len({a, b, buf}) < 3:
            raise ValueError("swap needs two sites and a distinct free buffer site")
        steps = [{"from": a, "to": buf, "redirectable": False}, {"from": b, "to": a, "redirectable": False},
                 {"from": buf, "to": b, "redirectable": False}]
    elif kind == "shuttle":
        a, b = task["a"], task["b"]
        if a == b:
            raise ValueError("shuttle needs two distinct sites")
        cycles = int(task.get("cycles") or 1)
        if cycles < 1:
            raise ValueError("shuttle cycles must be >= 1")
        pairs = [pair for _ in range(cycles) for pair in ((a, b), (b, a))]
        if task.get("legs") is not None:
            pairs = pairs[: max(1, int(task["legs"]))]
        steps = [{"from": s, "to": d, "redirectable": True} for s, d in pairs]
    elif kind in ("stack", "unstack"):
        tiers = [task["tier"]] if "tier" in task else list(task.get("tiers") or cell_place_fit.TIERS)
        if not tiers or any(t not in cell_place_fit.TIERS for t in tiers):
            raise ValueError(f"tiers must be in {cell_place_fit.TIERS}")
        cols = list(task.get("columns") or [task["to" if kind == "stack" else "from"]])
        if kind == "stack":
            srcs = list(task.get("sources") or [task["from"]] * (len(tiers) * len(cols)))
            targets = [f"{c}-l{t - 1}" for t in tiers for c in cols]
            if len(srcs) < len(targets):
                raise ValueError("not enough sources for stack targets")
            pairs = list(zip(srcs[:len(targets)], targets))
        else:
            sources = [f"{c}-l{t - 1}" for t in reversed(tiers) for c in cols]
            dsts = list(task.get("destinations") or [task["to"]] * len(sources))
            if len(dsts) < len(sources):
                raise ValueError("not enough destinations for unstack sources")
            pairs = list(zip(sources, dsts[:len(sources)]))
        steps = [{"from": s, "to": d, "redirectable": True} for s, d in pairs]
    elif kind == "sequence":
        raw_steps = task.get("steps")
        if not isinstance(raw_steps, list) or not raw_steps:
            raise ValueError("sequence task needs a nonempty steps list")
        steps = []
        for s in raw_steps:
            src = tier_site(s["from"], s["from_tier"], sites) if "from_tier" in s else s["from"]
            dst = tier_site(s["to"], s["to_tier"], sites) if "to_tier" in s else s["to"]
            extra = {k: s[k] for k in ("object", "colour", "layers_below", "arm") if s.get(k) is not None}
            steps.append({"from": src, "to": dst, "redirectable": bool(s.get("redirectable", False)), **extra})
    elif kind in ("goal_stack", "outbound", "rehandle"):
        import cell_stack_plan

        mode = "goal" if kind == "goal_stack" else kind
        meta = task.get("layout") or {n: {"kind": v.get("kind", "ship" if "layer" in v else "temp"),
                                          "stack": v.get("stack", v.get("tier_of", n)), "layer": v.get("layer", 0),
                                          **({"arm": v["arm"]} if "arm" in v else {}),
                                          **({"arms": v["arms"]} if "arms" in v else {})} for n, v in sites.items()}
        planned = cell_stack_plan.plan_from_spec({**task, "mode": mode, "sites": meta})
        if not planned["ok"]:
            raise ValueError(planned["why"] or f"{kind} planning failed")
        smap = task.get("site_map") or {}
        steps = []
        for m in planned["moves"] or ():
            src, dst = smap.get(m["source"], m["source"]), smap.get(m["destination"], m["destination"])
            steps.append({
                "from": src, "to": dst, "cargo_id": m.get("cargo_id"), "arms": m.get("arms"),
                "phase_label": m.get("phase_label"), "redirectable": m.get("phase_label") == "재취급",
                **({"object": m["cargo_id"]} if task.get("match_cargo_object") else {}),
                **({"layers_below": sites[src]["layer"]} if src in sites and sites[src].get("layer", 0) > 0 else {}),
            })
    else:
        raise ValueError(f"unknown kind {kind!r}")
    for step in steps:
        src, dst = step["from"], step["to"]
        for site in (src, dst):
            if site not in sites:
                raise ValueError(f"unknown site {site!r}")
        if src == dst:
            raise ValueError(f"from and to are both {src!r}")
        if not sites[src].get("auto_roi"):
            raise ValueError(f"site {src!r} has no auto_roi to look in")
    return steps


def carries(task: dict, sites: dict) -> list:
    """[(from, to)] for a task, or ValueError naming what is wrong (unknown site, same site, missing field)."""
    return [(s["from"], s["to"]) for s in plan_steps(task, sites)]


def run_carry(config_path: Path, catalog: Path, sites: dict, src: str, dst: str, log_dir: Path, run=subprocess.run,
              scenario_id: str | None = None, *, want_object: str | None = None, want_colour: str | None = None,
              layers_below: int | None = None, dry_run: bool = False) -> dict:
    roi = [str(v) for v in sites[src]["auto_roi"]]
    out = log_dir / f"{int(time.time())}-{src}-to-{dst}.json"
    command = [sys.executable, str(HERE / "cell_auto_pick.py"), "--config", str(config_path), "--catalog", str(catalog),
               "--roi", *roi, "--from", src, "--dest", dst]
    if want_object is not None:
        command += ["--object", str(want_object)]
    if want_colour is not None:
        command += ["--colour", str(want_colour)]
    if layers_below is not None:
        command += ["--layers-below", str(int(layers_below))]
    if dry_run:
        command.append("--dry-run")
    if scenario_id is not None:
        command += ["--scenario-id", scenario_id]
    proc = run(command, capture_output=True, text=True)
    try:
        result = json.loads(proc.stdout[proc.stdout.find("{"):])
    except ValueError:
        result = {"result": f"no result (exit {proc.returncode}): {proc.stderr[-200:]}"}
    out.write_text(json.dumps(result))
    tries = result.get("attempts") or []
    # Only cell_auto_pick's choose-stage return (before any motion) writes exactly this error; the pivot path differs.
    at_choice = len(tries) == 1 and tries[0].get("error") == "no usable object"
    refused = tries[0].get("refused") or [] if at_choice else []
    dest_full = bool(refused) and all(map(no_room, refused))
    return {"from": src, "to": dst, "result": result.get("result"), "log": str(out), "dest_full": dest_full}


ROOM = {"something is already there", "does not fit on the surface"}  # cell_place_fit.why_not / options


def no_room(refusal: dict) -> bool:
    """A place refusal because the destination is occupied (not a missing map or an empty lower tier)."""
    why = str(refusal.get("why", ""))
    parts = set(why.removeprefix("place: ").split(" / "))
    return why.startswith("place: ") and "something is already there" in parts and parts <= ROOM


def alternates(sites: dict, src: str, dst: str) -> list:
    """The destination's declared fallback sites, in order (D-1019): known sites other than the carry's own."""
    return [a for a in (sites.get(dst) or {}).get("alternates") or [] if a in sites and a not in (src, dst)]


def run_task(task: dict, config_path: Path, catalog: Path, log_dir: Path, preflight=None, carry=run_carry,
             *, dry_run: bool = False) -> dict:
    config = cell_place_fit.with_tiers(json.loads(config_path.read_text(encoding="utf-8")))[0]
    out = {"task_id": task.get("task_id"), "kind": task.get("kind"), "source": task.get("source"), "started": time.time(), "steps": []}
    try:
        plan = plan_steps(task, config["sites"])
    except (ValueError, KeyError) as exc:
        return {**out, "status": "rejected", "why": str(exc)}
    if preflight is not None:
        failed = [f"{name}: {why}" for name, ok, why in preflight(config) if not ok]
        if failed:
            return {**out, "status": "refused", "why": failed}
    base_kw = {k: v for k, v in (
        ("scenario_id", task.get("scenario_id")), ("dry_run", True if dry_run else None),
    ) if v is not None}
    ok_results = ("planned",) if dry_run else ("placed",)
    for i, item in enumerate(plan):
        src, dst = item["from"], item["to"]
        step_kw = {**base_kw, **{ak: item[sk] for sk, ak in (
            ("object", "want_object"), ("colour", "want_colour"), ("layers_below", "layers_below")
        ) if item.get(sk) is not None}}
        step = carry(config_path, catalog, config["sites"], src, dst, log_dir, **step_kw)
        out["steps"].append(step)
        # No room at the destination and nothing moved: its declared alternates, each observed afresh (D-1019).
        # Swaps and non-redirectable goal slots never redirect.
        for alt in alternates(config["sites"], src, dst) if step.get("dest_full") and item.get("redirectable", True) else ():
            step = {**carry(config_path, catalog, config["sites"], src, alt, log_dir, **step_kw), "redirected_from": dst}
            out["steps"].append(step)
            if not step.get("dest_full"):
                break
        if step["result"] not in ok_results:  # a stop leaves the objects where the last carry put them: a person looks
            return {**out, "status": "stopped", "why": f"{src} -> {step['to']}: {step['result']}", "ended": time.time()}
        # The next carry that expected this object at dst takes it from where it went; later ones are other objects.
        nxt = next((j for j in range(i + 1, len(plan)) if plan[j]["from"] == dst), None) if step.get("redirected_from") else None
        if nxt is not None:
            plan[nxt] = {**plan[nxt], "from": step["to"]}
    return {**out, "status": "planned" if dry_run else "done", "ended": time.time()}


from cell_fleet_pipeline import FleetModelPipeline  # noqa: E402,F401  (re-exported)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--config", required=True, type=Path)
    ap.add_argument("--catalog", required=True, type=Path)
    grp = ap.add_mutually_exclusive_group(required=True)
    grp.add_argument("--queue", type=Path)
    grp.add_argument("--task", type=Path, help="run one task JSON file once and exit")
    ap.add_argument("--once", action="store_true", help="run what is in the inbox now, then exit")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    import cell_preflight

    preflight = lambda c: cell_preflight.checks(c, "http://127.0.0.1:8767", 6.0)
    run_kw = {"dry_run": args.dry_run}
    if args.task is not None:
        task = json.loads(args.task.read_text(encoding="utf-8"))
        work_dir = json.loads(args.config.read_text(encoding="utf-8")).get("work_dir")
        out_dir = (Path(work_dir).expanduser() / "task-logs") if work_dir else (args.task.parent / "task-logs")
        out_dir.mkdir(parents=True, exist_ok=True)
        result = run_task(task, args.config, args.catalog, out_dir, preflight, **run_kw)
        print(json.dumps(result, indent=1))
        return 0 if result["status"] in ("done", "planned") else 1
    for name in ("inbox", "running", "done"):
        (args.queue / name).mkdir(parents=True, exist_ok=True)
    while True:
        for path in sorted((args.queue / "inbox").glob("*.json")):
            running = args.queue / "running" / path.name
            path.replace(running)  # claimed: a second runner will not pick it up
            task = json.loads(running.read_text(encoding="utf-8"))
            result = run_task(task, args.config, args.catalog, args.queue / "done", preflight, **run_kw)
            (args.queue / "done" / f"{task.get('task_id', path.stem)}.result.json").write_text(json.dumps(result, indent=1))
            running.unlink()
            print(json.dumps({k: result.get(k) for k in ("task_id", "status", "why")}), flush=True)
        if args.once:
            return 0
        time.sleep(2)


if __name__ == "__main__":
    sys.path.insert(0, str(HERE))
    sys.exit(main())
