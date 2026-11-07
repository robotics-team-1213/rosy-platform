#!/usr/bin/env python3
"""Two arms moving at once through their own hovers (2026-11-06): the schedule of omx_adapter.coordination, run on real sessions.

Each arm goes home -> its libraries' hovers in order -> home. coordination.plan orders the segments so everything swept stays
`--margin` apart; an arm starts a segment only when the peer's measured progress allows it (coordination.ready), so a lag stays
inside what was cleared. When one arm fails the other finishes its segment and starts no other; then the folds are checked
against where the arms really stand, and an arm folds only if that keeps the margin. If no order does, nothing moves and a
person is asked.

`--carry` runs one library per arm through the whole folded carry instead of the hovers, the box counted in the sweep while it is
held. On a failure each arm first climbs out the way it went in, the rule of cell_transfer.transfer_folded, so a fold never sweeps
low through the pile; an arm stopped lifting a held box stays for a person (a retreat pressed the box down, 2026-11-07).

A target outside the arm's own zone (cell_zones) refuses the whole run. Top views with both arms folded, before and after,
report anything that moved. Each run has its own folder: nothing of an earlier run is removed.

    cell_two_arm.py --a cell-a.json a1.json a2.json --b cell-b.json b1.json b2.json --out runs/ --commissioning --person-at-switch

shortcut: the libraries are planned beforehand, one per arm, since ROSY_OMX_TCP_X_M is one value per process; upgrade when the
tool length is per arm in the config. An arm's config may state `fingertip_m`, the length its kinematics lack (arm_a: unmeasured).
shortcut: this runs on the FIFO sessions, not through Fleet or WorkcellCoordinator; upgrade when those drive a cell's arms.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cell_coordinate import FOLDED, ITEM, command_frames, rigid_of, segments_of  # noqa: E402
from cell_pipeline_io import fold  # noqa: E402
from cell_scene_guard import scene_moved  # noqa: E402
from grasp_planner import load_kinematics, norm_to_rad  # noqa: E402
from omx_adapter.coordination import Segment, clearance, moved, plan, ready, thinned  # noqa: E402
from omx_adapter.swept_volume import capsules  # noqa: E402

STEP_M = 0.03
KEEP_ALIVE_S = 10.0  # `state` keeps a waiting arm's idle fold (runner.idle_park_s 60) from starting by itself
ORDER = ("a", "b")
LOW = {"run descend_pick": "run lift_pick", "run grasp_pick": "run lift_pick",
       "run descend_place": "run lift_place", "run release_place": "run lift_place"}  # the chunk that climbs out from each


def poses_of(frames, kin, rigid, tip_m: float, item=None) -> list:
    return thinned([moved(capsules(kin, [norm_to_rad(v) for v in f[:5]], fingertip_m=tip_m, item=item), rigid) for f in frames], STEP_M)


def route(libraries: list, kin, rigid, tip_m: float) -> tuple[list, list]:
    """(segments, commands): home -> each library's hover -> home; commands[i] is what segment i sends."""
    segments, commands, at = [], [], list(libraries[0][1]["chunks"]["home"][-1])
    for path, library in libraries:
        frames = command_frames(library, "goto above_pick", at)
        segments.append(Segment(f"goto {Path(path).name}", len(frames) / library["fps"], poses_of(frames, kin, rigid, tip_m)))
        commands.append([f"load {path}", "goto above_pick"])
        at = list(frames[-1])
    frames = command_frames(libraries[-1][1], "park", at)
    segments.append(Segment("park", len(frames) / libraries[-1][1]["fps"], poses_of(frames, kin, rigid, tip_m)))
    commands.append(["park"])
    return segments, commands


def carry_route(path, library: dict, kin, rigid, tip_m: float) -> tuple[list, list]:
    """(segments, commands): the folded carry of one library, one segment per command."""
    commands = [[command] for command in FOLDED]
    commands[0].insert(0, f"load {path}")
    return segments_of(library, kin, rigid, tip_m=tip_m), commands


def execute(cells: dict, commands: dict, steps: list, fail_at=None, log=print, clock=time.monotonic, poll_s: float = 0.05) -> dict:
    """Run the schedule. `fail_at` (arm, segment) acts as a failure after that segment: the test of the coupled stop."""
    done, changed, failed = {"a": 0, "b": 0}, threading.Condition(), []
    last, stopped = {}, {}  # per arm: the last command that finished, and the one that did not

    def fail(name, segment, error):
        with changed:
            failed.append({"arm": name, "segment": segment, "error": error})
            changed.notify_all()

    def arm(name):
        segment = None
        try:
            run(name)
        except Exception as exc:  # a dead thread would leave the peer waiting forever, kept alive and holding its pose
            fail(name, segment, f"{type(exc).__name__}: {exc}")

    def run(name):
        for segment, sends in enumerate(commands[name]):
            alive = clock()
            while True:
                with changed:
                    if failed:
                        return
                    if ready(steps, name, segment, done["a"], done["b"]):
                        break
                    changed.wait(poll_s)
                if clock() - alive >= KEEP_ALIVE_S:  # outside the lock: a slow session must not hold up the peer's failure
                    cells[name].act("state")
                    alive = clock()
            for send in sends:
                status = cells[name].act(send)
                log({"arm": name, "segment": segment, "send": send[-34:], "ok": status.get("ok"), "error": status.get("error")})
                if not status.get("ok"):
                    stopped[name] = {"command": send, "contact": bool(status.get("contact"))}
                    fail(name, segment, status.get("error"))
                    return
                last[name] = send
                if send == "run grasp_pick" and not status.get("holding"):
                    fail(name, segment, "empty grasp")
                    return
            with changed:
                done[name] += 1
                if fail_at == (name, segment):
                    failed.append({"arm": name, "segment": segment, "error": "injected"})
                changed.notify_all()

    threads = [threading.Thread(target=arm, args=(name,)) for name in ORDER]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return {"done": done, "failed": failed[0] if failed else None, "last": last, "stopped": stopped}


def way_out(library: dict, last: str | None, stopped: dict | None) -> list | None:
    """What an arm sends before its fold, as (command, frames); None: it stays for a person."""
    chunks = library["chunks"]
    if stopped and stopped["contact"]:
        if stopped["command"] == "run lift_pick":
            return None
        if stopped["command"] in LOW:
            return [("retreat", chunks[stopped["command"].split()[1]][::-1])]
        return []  # a stopped lift_place or fold folds as it stands; fold() rests and tries once more
    climb = LOW.get(last)
    return [(climb, chunks[climb.split()[1]])] if climb else []


def fold_order(here: dict, fold: dict, margin_m: float) -> list | None:
    """Which arm folds first, measured from where they stand. `here`: each arm's poses where it stands; `fold`: its sweep home
    or None when it is already home. After the first fold the other's sweep is checked against the first at home."""
    moving = [n for n in ORDER if fold[n] is not None]
    if not moving:
        return []
    if len(moving) == 1:
        other = "b" if moving[0] == "a" else "a"
        return moving if clearance(fold[moving[0]], here[other]) >= margin_m else None
    for first, second in (ORDER, ORDER[::-1]):
        if clearance(fold[first], here[second]) >= margin_m and clearance(fold[first][-1:], fold[second]) >= margin_m:
            return [first, second]
    return None


def safe_fold(cells: dict, libraries: dict, kin, rigids: dict, tips: dict, margin_m: float, log=print, moved_out=None) -> dict:
    from cell_transfer import STILL_HOLDING_UNITS

    moved_out = moved_out or {}
    states = {n: cells[n].act("state").get("state") for n in ORDER}
    if any(s is None for s in states.values()):
        return {"folded": False, "person_needed": "no arm state"}
    here, sweep, exits = {}, {}, {}
    for n in ORDER:
        library = libraries[n]
        home = library["chunks"]["home"][-1]
        # wide jaws count as holding too: open ones take about as much room, and the state alone cannot tell them apart
        item = ITEM if states[n][5] > library.get("gripper_closed", float("-inf")) + STILL_HOLDING_UNITS else None
        here[n] = poses_of([states[n]], kin, rigids[n], tips[n], item)
        exits[n] = way_out(library, moved_out.get("last", {}).get(n), moved_out.get("stopped", {}).get(n))
        sweep[n] = None
        if exits[n] is not None:
            frames = [frame for _, chunk in exits[n] for frame in chunk]
            at = frames[-1] if frames else states[n]
            if frames or max(abs(a - b) for a, b in zip(states[n][:5], home[:5])) > 2.0:
                sweep[n] = poses_of(frames + command_frames(library, "park", list(at)), kin, rigids[n], tips[n], item)
    order = fold_order(here, sweep, margin_m)
    if order is None:
        return {"folded": False, "person_needed": "no fold order keeps the margin", "states": states}
    for n in order:
        for command, _ in exits[n]:
            status = cells[n].act(command)
            log({"arm": n, "send": command, "ok": status.get("ok"), "error": status.get("error")})
            if not status.get("ok"):
                return {"folded": False, "person_needed": f"{n} did not climb out: {status.get('error')}", "order": order}
        status = fold(cells[n])
        log({"arm": n, "send": "park", "ok": status.get("ok"), "error": status.get("error")})
        if not status.get("ok"):  # the other arm stays put: its fold was only cleared against this one folded
            return {"folded": False, "person_needed": f"{n} did not fold: {status.get('error')}", "order": order}
    stayed = [n for n in ORDER if exits[n] is None]
    if stayed:
        return {"folded": False, "person_needed": f"{stayed} stopped lifting a held box: a person frees it", "order": order}
    return {"folded": True, "order": order}


def open_cells(configs: dict, fifo_cell) -> dict:
    """Each arm's commands go out `checked` against its pinned operating profile (D-911); an arm with none does not move."""
    from cell_robot_profile import bind_pipeline

    cells = {}
    for n in ORDER:
        if not configs[n].get("operating_profile_path"):
            raise SystemExit(f"arm {n}: its config names no operating_profile_path (D-911)")
        cells[n] = fifo_cell(Path(configs[n]["io"]).expanduser(), configs[n]["cameras"], timeout_s=180,
                             operating_profile=bind_pipeline(configs[n])["_operating_profile_binding"])
    return cells


def away_from_home(cells: dict, libraries: dict) -> list:
    """The arms not folded home: `route` plans from home, so a schedule from anywhere else was never cleared."""
    away = []
    for n in ORDER:
        state = cells[n].act("state").get("state")
        home = libraries[n]["chunks"]["home"][-1]
        if state is None or max(abs(a - b) for a, b in zip(state[:5], home[:5])) > 2.0:
            away.append(n)
    return away


def still_holding(cells: dict, libraries: dict) -> list:
    """Arms whose jaws did not close home: the park took the box back, and "placed" would be wrong (2026-10-28)."""
    from cell_transfer import STILL_HOLDING_UNITS

    states = {n: cells[n].act("state").get("state") for n in ORDER}
    return [n for n in ORDER if states[n] is None or states[n][5] > libraries[n]["gripper_closed"] + STILL_HOLDING_UNITS]  # unread: not placed


def main(argv=None) -> int:
    import cv2
    import cell_calibration as cal
    import cell_pipeline as cp
    import cell_pivot
    import cell_zones
    from cell_auto_setup import load_config

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--a", nargs="+", required=True, metavar=("CELL", "LIBRARY"))
    ap.add_argument("--b", nargs="+", required=True, metavar=("CELL", "LIBRARY"))
    ap.add_argument("--margin", type=float, default=0.05)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--fail-at", help="ARM:SEGMENT, act as a failure after it: tries the coupled stop")
    ap.add_argument("--plan-only", action="store_true", help="print the schedule; nothing moves")
    ap.add_argument("--carry", action="store_true", help="one library per arm, the whole carry with the box, not the hovers")
    ap.add_argument("--commissioning", action="store_true")
    ap.add_argument("--person-at-switch", action="store_true")
    args = ap.parse_args(argv)
    if not args.plan_only and not (args.commissioning and args.person_at_switch):
        raise SystemExit("this moves two arms: --commissioning --person-at-switch (D-911)")
    fail_at = None
    if args.fail_at:
        name, segment = args.fail_at.split(":")
        fail_at = (name, int(segment))
    jobs = dict(a=args.a, b=args.b)
    if args.carry and any(len(jobs[n]) != 2 for n in ORDER):
        raise SystemExit("--carry takes one library per arm")
    configs = {n: load_config(Path(jobs[n][0])) for n in ORDER}
    calibrations = {n: cell_pivot.with_site_maps(configs[n], cal.load(Path(configs[n]["calibration_path"]).expanduser())) for n in ORDER}
    libraries = {n: [(p, json.loads(Path(p).read_text())) for p in jobs[n][1:]] for n in ORDER}
    for n in ORDER:
        zones = cell_zones.Zones(configs[n], calibrations[n])
        for path, library in libraries[n]:
            for point in [library["source"][k] for k in (("pick", "place") if args.carry else ("pick",))]:
                if zones.zone_of((point["x"], point["y"])) != configs[n]["zone_side"]:
                    raise SystemExit(f"{path}: outside arm {n}'s own zone ({configs[n]['zone_side']})")
    kin, _, _ = load_kinematics(None)
    rigids = {"a": rigid_of(calibrations["a"], calibrations["b"], "pallet", "pallet"), "b": (0.0, 0.0, 0.0)}
    tips = {n: float(configs[n].get("fingertip_m", 0.0)) for n in ORDER}
    routes = {n: carry_route(*libraries[n][0], kin, rigids[n], tips[n]) if args.carry else route(libraries[n], kin, rigids[n], tips[n])
              for n in ORDER}
    schedule = plan(routes["a"][0], routes["b"][0], args.margin)
    names = {n: [s.name for s in routes[n][0]] for n in ORDER}
    print(json.dumps({"schedule": schedule, "segments": names}, indent=1))
    if schedule is None:
        print("refused: no order keeps the margin")
        return 1
    if args.plan_only:
        return 0
    cells = open_cells(configs, cp.FifoCell)
    away = away_from_home(cells, {n: libraries[n][0][1] for n in ORDER})
    if away:
        raise SystemExit(f"not folded home: arm {', '.join(away)}: the schedule was cleared from home")
    run = args.out / time.strftime("%Y%m%d-%H%M%S")
    run.mkdir(parents=True, exist_ok=False)
    lock, stream = threading.Lock(), (run / "log.jsonl").open("w")

    def log(row):
        with lock:
            stream.write(json.dumps({"t": round(time.time(), 3), **row}) + "\n")
            stream.flush()
            print(row, flush=True)

    before = cells["b"].frame("top")
    cv2.imwrite(str(run / "before.jpg"), before)
    moved_out = execute(cells, {n: routes[n][1] for n in ORDER}, schedule["steps"], fail_at, log)
    outcome = {**moved_out, "fold": None}
    if moved_out["failed"]:
        outcome["fold"] = safe_fold(cells, {n: libraries[n][-1][1] for n in ORDER}, kin, rigids, tips, args.margin, log, moved_out)
    elif args.carry:
        outcome["still_holding"] = still_holding(cells, {n: libraries[n][-1][1] for n in ORDER})
    after = cells["b"].frame("top")
    cv2.imwrite(str(run / "after.jpg"), after)
    outcome["scene_moved"] = scene_moved(before, after)
    log({"result": outcome})
    ok = (not moved_out["failed"] and not outcome.get("still_holding")) or (fail_at is not None and moved_out["failed"]["error"] == "injected" and outcome["fold"]["folded"])
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
