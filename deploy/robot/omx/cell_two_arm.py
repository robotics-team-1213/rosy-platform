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

A target outside the arm's own zone (cell_zones) refuses the whole run. Each arm moves behind its own Gate on the
Guarded cell (cell_transfer, cell_auto_safety; D-911): before any thread starts every (arm, library) is assessed and
its intent written into the run folder, and one hold leaves both arms at zero motion. Top views with both arms folded,
before and after, report anything that moved. Each run has its own folder: nothing of an earlier run is removed.

    cell_two_arm.py --a cell-a.json a1.json a2.json --b cell-b.json b1.json b2.json --out runs/ --commissioning --person-at-switch

Each arm reads its own TCP length (`tcp_x_m`, `plan.tcp_x_m`, or measured `arm-cal` `z_profile_mm.tcp_v21_x_mm`);
an arm's config may also state `fingertip_m`, the length its kinematics lack (arm_a: unmeasured).
shortcut: this runs on the FIFO sessions, not through Fleet or WorkcellCoordinator; upgrade when those drive a cell's arms.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cell_arm_cal  # noqa: E402
from cell_coordinate import FOLDED, ITEM, command_frames, rigid_of, segments_of  # noqa: E402
from cell_pipeline_io import fold  # noqa: E402
from cell_scene_guard import scene_moved  # noqa: E402
from grasp_planner import load_kinematics, norm_to_rad  # noqa: E402
import joint_jitter  # noqa: E402
from omx_adapter.coordination import Segment, clearance, moved, plan, ready, thinned  # noqa: E402
from omx_adapter.swept_volume import capsules  # noqa: E402

STEP_M = 0.03
TCP_MISMATCH_TOL_M = 0.001
KEEP_ALIVE_S = 10.0  # `state` keeps a waiting arm's idle fold (runner.idle_park_s 60) from starting by itself
ORDER = ("a", "b")
LOW = {"run descend_pick": "run lift_pick", "run grasp_pick": "run lift_pick",
       "run descend_place": "run lift_place", "run release_place": "run lift_place"}  # the chunk that climbs out from each


def tcp_x_of(config: dict) -> float | None:
    """Resolve an arm's TCP length (m) from explicit config/plan or measured arm-cal (`samples > 0`)."""
    if config.get("tcp_x_m") is not None:
        return float(config["tcp_x_m"])
    plan_cfg = config.get("plan") or {}
    if plan_cfg.get("tcp_x_m") is not None:
        return float(plan_cfg["tcp_x_m"])
    cal = config.get("_arm_calibration") or {}
    tcp_mm = (cal.get("z_profile_mm") or {}).get("tcp_v21_x_mm")
    if cal.get("samples", 0) > 0 and tcp_mm is not None:
        return float(tcp_mm) / 1000.0
    return None


def kinematics_for(configs: dict, libraries: dict | None = None, *, root: Path | None = None) -> dict:
    """Load one kinematics instance per arm and reject libraries whose `tcp_x_m` disagrees by > 1 mm."""
    kins = {}
    for key, config in configs.items():
        tcp_x_m = tcp_x_of(config)
        kins[key] = load_kinematics(root, tcp_x_m)[0]
        if libraries is not None and tcp_x_m is not None:
            for path, library in libraries[key]:
                lib_tcp = library.get("tcp_x_m")
                if lib_tcp is not None and abs(float(lib_tcp) - tcp_x_m) > TCP_MISMATCH_TOL_M:
                    raise SystemExit(
                        f"arm {key} {path}: library tcp_x_m {float(lib_tcp):.4f} m disagrees with "
                        f"arm tcp {tcp_x_m:.4f} m (>{TCP_MISMATCH_TOL_M * 1000:.1f} mm)"
                    )
    return kins


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


def execute(cells: dict, commands: dict, steps: list, fail_at=None, log=print, clock=time.monotonic, poll_s: float = 0.05,
            on_segment_done=None) -> dict:
    """Run the schedule. `fail_at` (arm, segment) acts as a failure after that segment: the test of the coupled stop.
    `on_segment_done(name, segment, done)`, still inside the lock after `done` advances and only while nothing has
    failed, returns the plan(start=(done_a,
    done_b)) result for this completion: its steps become the next generation only when both arms stand at a segment
    boundary (started == done; admission is blocked while a replan is pending), plan_gen counting the swaps. A refused
    plan (None) stops both arms ("replan_none"): a coupled stop and safe_fold, never a serial fallback (D-983)."""
    done, started, changed, failed = {"a": 0, "b": 0}, {"a": 0, "b": 0}, threading.Condition(), []
    last, stopped, pending, plan_gen = {}, {}, None, 0  # per arm: the last command that finished, and the one that did not

    def fail(name, segment, error):
        with changed:
            failed.append({"arm": name, "segment": segment, "error": error})
            changed.notify_all()

    def swap_if_due():
        nonlocal steps, pending, plan_gen
        if pending is not None and all(started[n] == done[n] for n in ORDER):
            steps, pending, plan_gen = pending["steps"], None, plan_gen + 1
            log({"plan_gen": plan_gen, "done": [done["a"], done["b"]]})
            changed.notify_all()

    def arm(name):
        segment = None
        try:
            run(name)
        except Exception as exc:  # a dead thread would leave the peer waiting forever, kept alive and holding its pose
            fail(name, segment, f"{type(exc).__name__}: {exc}")

    def run(name):
        nonlocal pending
        for segment, sends in enumerate(commands[name]):
            alive = clock()
            while True:
                with changed:
                    if failed:
                        return
                    swap_if_due()
                    if pending is None and ready(steps, name, segment, done["a"], done["b"]):
                        started[name] += 1
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
                if send == "run grasp_pick" and not (status.get("holding") or cell_arm_cal.infer_holding(status)):
                    fail(name, segment, "empty grasp")
                    return
            with changed:
                done[name] += 1
                if fail_at == (name, segment):
                    failed.append({"arm": name, "segment": segment, "error": "injected"})
                if not failed and on_segment_done is not None:
                    fresh = on_segment_done(name, segment, dict(done))
                    if fresh is None:
                        failed.append({"arm": name, "segment": segment, "error": "replan_none"})
                    else:
                        pending = fresh
                swap_if_due()
                changed.notify_all()

    threads = [threading.Thread(target=arm, args=(name,)) for name in ORDER]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return {"done": done, "failed": failed[0] if failed else None, "last": last, "stopped": stopped, "plan_gen": plan_gen}


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
    states = {n: joint_jitter.settled_state(cells[n]).get("state") for n in ORDER}
    if any(s is None for s in states.values()):
        return {"folded": False, "person_needed": "no arm state"}
    here, sweep, exits = {}, {}, {}
    for n in ORDER:
        arm_kin = kin[n] if isinstance(kin, dict) else kin
        library = libraries[n]
        home = library["chunks"]["home"][-1]
        # wide jaws count as holding too: open ones take about as much room, and the state alone cannot tell them apart
        item = ITEM if states[n][5] > library.get("gripper_closed", float("-inf")) + STILL_HOLDING_UNITS else None
        here[n] = poses_of([states[n]], arm_kin, rigids[n], tips[n], item)
        exits[n] = way_out(library, moved_out.get("last", {}).get(n), moved_out.get("stopped", {}).get(n))
        sweep[n] = None
        if exits[n] is not None:
            frames = [frame for _, chunk in exits[n] for frame in chunk]
            at = frames[-1] if frames else states[n]
            if frames or max(abs(a - b) for a, b in zip(states[n][:5], home[:5])) > 2.0:
                sweep[n] = poses_of(frames + command_frames(library, "park", list(at)), arm_kin, rigids[n], tips[n], item)
    order = fold_order(here, sweep, margin_m)
    if order is None:
        return {"folded": False, "person_needed": "no fold order keeps the margin", "states": states}
    stop = threading.Event()
    locks = {n: threading.Lock() for n in ORDER}  # one caller per arm: a keep-alive `state` must not interleave with motion

    def keep_alive():  # the arm waiting through the other's fold must not idle-fold through a sweep nobody cleared
        while not stop.wait(KEEP_ALIVE_S):
            for n in ORDER:
                if locks[n].acquire(blocking=False):  # busy climbing or folding: that arm's runner is anything but idle
                    try:
                        cells[n].act("state")
                    finally:
                        locks[n].release()

    alive = threading.Thread(target=keep_alive, daemon=True)
    alive.start()
    try:
        for n in order:
            with locks[n]:
                try:
                    for command, _ in exits[n]:
                        status = cells[n].act(command)
                        log({"arm": n, "send": command, "ok": status.get("ok"), "error": status.get("error")})
                        if not status.get("ok"):
                            return {"folded": False, "person_needed": f"{n} did not climb out: {status.get('error')}",
                                    "order": order}
                    status = fold(cells[n])
                except Exception as exc:  # a Guarded abort parks and raises: the arm stands where it stopped, a person frees it
                    return {"folded": False, "person_needed": f"{n} did not fold: {type(exc).__name__}: {exc}", "order": order}
                log({"arm": n, "send": "park", "ok": status.get("ok"), "error": status.get("error")})
                if not status.get("ok"):  # the other arm stays put: its fold was only cleared against this one folded
                    return {"folded": False, "person_needed": f"{n} did not fold: {status.get('error')}", "order": order}
    finally:
        stop.set()
        alive.join()
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


def attest(config: dict, supervised: bool) -> dict:
    """The Gate takes its supervised branch from config `_commissioning` (cell_envelope), as cell_cycle does."""
    return {**config, "_commissioning": {"person_at_switch": True}} if supervised else config


def open_gates(cells: dict, configs: dict, calibrations: dict, libraries: dict, sequences: dict, run: Path) -> dict:
    """One Gate per arm over the Guarded cell (D-911, cell_cycle's pattern). Every (arm, library) is assessed and its
    durable intent written before any thread starts, so one hold leaves both arms at zero motion. The library index
    names the intent file: a second open on the same Gate must not hit the first library's pending intent."""
    from cell_auto_safety import Guarded
    from cell_transfer import Gate

    gates = {}
    for n in ORDER:
        gate = Gate(Guarded(cells[n], configs[n]), configs[n], calibrations[n], sequence=sequences[n])
        for i, (path, _) in enumerate(libraries[n]):

            def before_motion(assessment, n=n, i=i, path=path):
                with (run / f"intent-{n}-{i}.json").open("x", encoding="utf-8") as stream:  # exclusive: a hold, never a clobber
                    json.dump({"arm": n, "library": str(path), "assessment": assessment}, stream)
                    stream.flush()
                    os.fsync(stream.fileno())

            held = gate.open(path, before_motion)
            if held is not None:
                raise SystemExit(f"arm {n} {path}: held: {held['reason']} (D-911)")
        gates[n] = gate
    return gates


def away_from_home(cells: dict, libraries: dict) -> list:
    """The arms not folded home: `route` plans from home, so a schedule from anywhere else was never cleared."""
    away = []
    for n in ORDER:
        state = joint_jitter.settled_state(cells[n]).get("state")
        home = libraries[n]["chunks"]["home"][-1]
        if state is not None and max(abs(a - b) for a, b in zip(state[:5], home[:5])) > 2.0:
            recheck = joint_jitter.settled_state(cells[n], {"reach": {"samples": 2}}).get("state")
            if recheck is not None:
                arm_dof = max(5, len(state) - 1)
                state = [(float(state[j]) + 2.0 * float(recheck[j])) / 3.0 for j in range(arm_dof)] + list(recheck[arm_dof:])
        if state is None or max(abs(a - b) for a, b in zip(state[:5], home[:5])) > 2.0:
            away.append(n)
    return away


def still_holding(cells: dict, libraries: dict) -> list:
    """Arms whose jaws did not close home: the park took the box back, and "placed" would be wrong (2026-10-28)."""
    from cell_transfer import STILL_HOLDING_UNITS

    states = {n: joint_jitter.settled_state(cells[n]).get("state") for n in ORDER}
    return [n for n in ORDER if states[n] is None or states[n][5] > libraries[n]["gripper_closed"] + STILL_HOLDING_UNITS]  # unread: not placed


def admit(schedule: dict, libraries: dict) -> None:
    """D-983: a both-step holds one arm mid-route while the other moves, and only a person-measured `wait` chunk is
    a cleared waiting pose — each arm in every library it runs, `load` swapping libraries mid-run. A serial-only
    schedule waits at home, which the plan's rest check already cleared."""
    if not any(step["a"] is not None and step["b"] is not None for step in schedule["steps"]):
        return
    for n in ORDER:
        for path, library in libraries[n]:
            if not library["chunks"].get("wait"):
                raise SystemExit(f"arm {n} {path}: no measured wait pose (D-983): "
                                 "teach a `wait` chunk or plan one arm after the other")


def main(argv=None) -> int:
    import cell_two_arm_cli as _cli

    return _cli.main(argv, two=sys.modules[__name__])


if __name__ == "__main__":
    raise SystemExit(main())
