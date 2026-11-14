#!/usr/bin/env python3
"""One cycle of ordered moves across arm S, A and B (three-arm design 2026-11-14): S feeds the belt, A/B stack from its end.

The core is pure: injected carry / pair / pair_schedule / read_belt / clock, and an omx_adapter BeltHandover that holds the one
box on the belt. Every belt move needs evidence first (reserve before S loads, arrived before A/B pick) and every reading that
is not proof holds until the next tick; nothing is guessed. Arms are assigned once, at the cycle start, to the candidate free
earliest (the primary on a tie). A and B overlap only through a coordination schedule for the pair of libraries; with none, one
at a time. S and A/B never move together: their clearance is unmeasured. A failure lets the running moves finish, starts none, and
returns HOLD for a person; there is no retry.

    cell_cycle.py cycle.json [--plan-only]                  (default: moves nothing)
    cell_cycle.py cycle.json --commissioning --person-at-switch

Real mode never overlaps A and B: its pair_schedule always answers None, so every move is one reviewed carry through the D-911
Gate. cell_two_arm.execute sends commands without a Gate.open assessment (no library evaluation, zone check or pre-motion
record), and the MuJoCo stack-t3 run showed 0 s of overlap anyway. Pair decisions stay in --plan-only (coordination.plan) and
in the core, for sim and tests.

shortcut: the box counts as grasped when the folded carry returns, not at the lift (transfer_folded has no hook there); upgrade
when it reports the lift. A pair that fails is not re-planned mid-run: cell_two_arm.execute takes one fixed schedule, so
`plan_gen` only counts decisions and `pair_schedule` takes the `start` that coordination.plan already supports.
"""
from __future__ import annotations

import argparse
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cell_belt_handover import BeltHandover, Hold  # noqa: E402

SCHEMA = "rosy.omx-cell-cycle.v1"
ARMS = ("arm_s", "arm_a", "arm_b")
AB = ("arm_a", "arm_b")
KINDS = ("s_to_belt", "belt_to_stack", "stack")


def validate(plan: dict) -> None:
    if plan.get("schema") != SCHEMA:
        raise ValueError(f"schema must be {SCHEMA}")
    ids = [m["id"] for m in plan["moves"]]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate move id")
    for m in plan["moves"]:
        arms = list(m["candidates"])
        if m["kind"] not in KINDS or not arms or set(arms) - set(ARMS):
            raise ValueError(f"{m['id']}: bad kind or candidates")
        if (m["kind"] == "s_to_belt") != (arms == ["arm_s"]):
            raise ValueError(f"{m['id']}: only s_to_belt runs on arm_s, and only there")
        if set(m.get("after", ())) - set(ids):
            raise ValueError(f"{m['id']}: after names an unknown move")
    cargos = [(m["kind"], m["cargo"]) for m in plan["moves"] if m["kind"] != "stack"]
    for kind in ("s_to_belt", "belt_to_stack"):
        mine = [c for k, c in cargos if k == kind]
        if len(set(mine)) != len(mine):
            raise ValueError(f"two {kind} moves for one cargo")
    if {c for k, c in cargos if k == "s_to_belt"} != {c for k, c in cargos if k == "belt_to_stack"}:
        raise ValueError("every cargo needs exactly one s_to_belt and one belt_to_stack")
    for key in ("s_region_px", "end_region_px", "missing_after_s", "transit_s"):
        if key not in plan["belt"]:
            raise ValueError(f"belt.{key} missing")
    if not plan["belt"]["transit_s"] > 0:
        raise ValueError("belt.transit_s must be positive: the time anything on the running belt needs to reach the end")


def assign(moves: list) -> dict:
    """{id: arm}: each move to the candidate that can start it earliest, in `after` order; the primary (first) on a tie."""
    end, free, out, todo = {}, {a: 0.0 for a in ARMS}, {}, list(moves)
    while todo:
        m = next((m for m in todo if all(d in end for d in m.get("after", ()))), None)
        if m is None:
            raise ValueError("`after` has a cycle")
        ready = max((end[d] for d in m.get("after", ())), default=0.0)
        arm = min(m["candidates"], key=lambda a: max(free[a], ready))
        free[arm] = end[m["id"]] = max(free[arm], ready) + m.get("est_s", 1.0)
        out[m["id"]] = arm
        todo.remove(m)
    return out


class Cycle:
    def __init__(self, moves, belt, handover, *, carry, pair, pair_schedule, read_belt, clock=time.monotonic,
                 sleep=time.sleep, tick_s=0.5, timeout_s=600.0, log=print):
        self.moves, self.order = {m["id"]: m for m in moves}, [m["id"] for m in moves]
        self.belt, self.h, self.clock, self.sleep, self.tick_s, self.timeout_s, self.log = belt, handover, clock, sleep, tick_s, timeout_s, log
        self.carry, self.pair, self.pair_schedule, self.read_belt = carry, pair, pair_schedule, read_belt
        self.arm_of, self.state = assign(moves), {i: "pending" for i in self.order}
        self.clearing, self.waiting, self.failure, self.plan_gen = [], {}, None, 0
        self.settled, self.empty_since = False, None

    def _hold(self, key, exc: Hold) -> bool:
        """A refused reading retries next tick; an out-of-order, stale or mismatched event is a fault for a person."""
        if exc.reason in ("stale_generation", "cargo_mismatch") or exc.reason.startswith("state_"):
            self.failure = self.failure or f"{key}: {exc.reason}"
        else:
            self.waiting[key] = exc.reason
        return False

    def _gate(self, m) -> bool:
        """May this A/B move start now? A belt pick needs the box seen at the belt end first."""
        if m["kind"] != "belt_to_stack":
            return True
        if self.h.cargo != m["cargo"] or self.h.state not in ("placed", "at_end"):
            self.waiting[m["id"]] = f"belt_{self.h.state}"
            return False
        reading = self.read_belt(self.belt["end_region_px"])
        if reading.get("occupancy") != "occupied":  # also after arrived(): a repeat is a no-op, so each start re-proves the box
            self.waiting[m["id"]] = f"end_{reading.get('occupancy')}:{reading.get('reason', '')}"
            return False
        try:
            self.h.arrived(self.h.generation, m["cargo"], reading)
            return True
        except Hold as exc:
            return self._hold(m["id"], exc)

    def _belt_empty(self) -> dict:
        """One reading for the whole belt: a box left anywhere (after a restart, say) blocks a new one."""
        seen = [(name, self.read_belt(self.belt[key])) for name, key in (("s_region", "s_region_px"), ("end_region", "end_region_px"))]
        for name, r in seen:  # an unknown anywhere outranks an occupied one: nothing is proven
            if r.get("occupancy") not in ("empty", "occupied"):
                return {"occupancy": "unknown", "reason": f"{name}:{r.get('reason', '')}"}
        for name, r in seen:
            if r["occupancy"] == "occupied":
                return {"occupancy": "occupied", "reason": name}
        return {"occupancy": "empty", "reason": "both_regions_clear"}

    def _belt_settled(self) -> bool:
        """Before the first reserve: both regions empty in two readings belt.transit_s apart. The belt runs, so a box stopped between
        the regions after a restart reaches the end by then and shows; any other reading starts the wait again."""
        if self.settled:
            return True
        reading = self._belt_empty()
        if reading["occupancy"] != "empty":
            self.empty_since = None
            self.waiting["belt_start"] = f"{reading['occupancy']}:{reading['reason']}"
        elif self.empty_since is None:
            self.empty_since = self.clock()
        else:
            self.settled = self.clock() - self.empty_since >= self.belt["transit_s"]
        return self.settled

    def _reserve(self, m) -> bool:
        if self.h.state != "empty":  # one box on the belt: S waits for it to be cleared (missing is caught by check)
            self.waiting[m["id"]] = f"belt_{self.h.state}"
            return False
        try:
            self.h.reserve(m["cargo"], self._belt_empty())
            return True
        except Hold as exc:
            return self._hold(m["id"], exc)

    def _launch(self, pool, running, ids, call):
        for i in ids:
            self.state[i] = "running"
        self.plan_gen += 1
        self.log({"start": ids, "plan_gen": self.plan_gen})
        running[pool.submit(call)] = {"ids": ids, "arms": [self.arm_of[i] for i in ids]}

    def _start(self, pool, running):
        if self.failure:
            return
        busy = {a for job in running.values() for a in job["arms"]}
        ready = [i for i in self.order if self.state[i] == "pending" and self.arm_of[i] not in busy
                 and all(self.state[d] == "done" for d in self.moves[i].get("after", ()))]
        for i in ready:
            m = self.moves[i]
            if m["kind"] == "s_to_belt" and not busy and self._belt_settled() and self._reserve(m):  # S and A/B never move together
                busy.add("arm_s")
                self._launch(pool, running, [i], lambda m=m: self.carry("arm_s", m["candidates"]["arm_s"]))
        if busy or self.failure:  # nothing starts beside a running move; A/B overlap only as a scheduled pair
            return
        ab, pick = {}, False
        for i in ready:
            m = self.moves[i]
            if self.arm_of[i] in AB and self.arm_of[i] not in ab and not (pick and m["kind"] == "belt_to_stack") and self._gate(m):
                ab[self.arm_of[i]], pick = i, pick or m["kind"] == "belt_to_stack"
        lib = lambda i: self.moves[i]["candidates"][self.arm_of[i]]  # noqa: E731
        if len(ab) == 2:
            schedule = self.pair_schedule(lib(ab["arm_a"]), lib(ab["arm_b"]))
            self.plan_gen += 1
            self.log({"pair": [ab["arm_a"], ab["arm_b"]], "schedule": schedule is not None, "plan_gen": self.plan_gen})
            if schedule is not None:
                return self._launch(pool, running, [ab["arm_a"], ab["arm_b"]],
                                    lambda: self.pair(lib(ab["arm_a"]), lib(ab["arm_b"]), schedule))
        first = min(ab.values(), key=self.order.index, default=None)
        if first is not None:  # serial: the other waits for the next tick
            self._launch(pool, running, [first], lambda: self.carry(self.arm_of[first], lib(first)))

    def _settle(self, running):
        for fut in [f for f in running if f.done()]:
            job = running.pop(fut)
            try:
                result = fut.result()
            except Exception as exc:  # a dead worker must not look like a finished move
                result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
            self.plan_gen += 1
            self.log({"done": job["ids"], "ok": result.get("ok"), "error": result.get("error"), "plan_gen": self.plan_gen})
            if not result.get("ok"):
                self.failure = self.failure or f"{','.join(job['ids'])}: {result.get('error')}"
                for i in job["ids"]:
                    self.state[i] = "failed"
                continue
            for i in job["ids"]:
                self.state[i] = "done"
                m = self.moves[i]
                try:
                    if m["kind"] == "s_to_belt":
                        self.h.placed(self.h.generation, m["cargo"])
                    elif m["kind"] == "belt_to_stack":
                        self.h.grasped(self.h.generation, m["cargo"])
                        self.clearing.append((self.h.generation, m["cargo"]))
                except Hold as exc:
                    self.failure = self.failure or f"{i}: {exc.reason}"

    def _clear(self):
        for generation, cargo in list(self.clearing):
            try:
                self.h.cleared(generation, self.read_belt(self.belt["end_region_px"]))
                self.clearing.remove((generation, cargo))
            except Hold as exc:
                self._hold(f"clear {cargo}", exc)

    def run(self) -> dict:
        start, running, timed_out = self.clock(), {}, False
        pool = ThreadPoolExecutor(max_workers=len(ARMS))
        try:
            while True:
                self.waiting = {}
                self._settle(running)
                if self.h.check() == "missing":
                    self.failure = self.failure or "belt_missing: a person looks (BeltHandover.resolve)"
                if self.clock() - start > self.timeout_s:
                    timed_out, self.failure = True, self.failure or "timeout"
                    if running:
                        break
                self._clear()
                self._start(pool, running)
                if not running and (self.failure or (all(s == "done" for s in self.state.values()) and not self.clearing)):
                    break
                if running:
                    wait(list(running), timeout=self.tick_s, return_when=FIRST_COMPLETED)
                else:
                    self.sleep(self.tick_s)
        finally:
            # a stuck carry must not hold up the HOLD: the guarded runner keeps its own stop, and the process exits when it ends
            pool.shutdown(wait=False)
        still = [i for job in running.values() for i in job["ids"]]
        reason = f"timeout, still running: {still}" if timed_out and still else self.failure
        return {"result": "HOLD" if self.failure else "DONE", "reason": reason, "state": self.state, "running": still,
                "assignment": self.arm_of, "waiting": self.waiting, "plan_gen": self.plan_gen, "events": self.h.events}


def attest(config: dict, supervised: bool) -> dict:
    """The Gate takes its supervised branch from config `_commissioning` (cell_envelope), as cell_auto_setup sets it from the CLI."""
    return {**config, "_commissioning": {"person_at_switch": True}} if supervised else config


def _plan_schedule(plan: dict, cfg: dict, cals: dict):
    """pair_schedule(lib_a, lib_b): the coordination.plan schedule for two carries, or None. For --plan-only output only."""
    import cell_two_arm
    from cell_coordinate import rigid_of
    from grasp_planner import load_kinematics
    from omx_adapter.coordination import plan as coordinate

    kin, _, _ = load_kinematics(None)
    rigids = {"arm_a": rigid_of(cals["arm_a"], cals["arm_b"], "pallet", "pallet"), "arm_b": (0.0, 0.0, 0.0)}
    tips = {a: float(cfg[a].get("fingertip_m", 0.0)) for a in AB}
    libs = lambda path: json.loads(Path(path).read_text())  # noqa: E731

    def pair_schedule(lib_a, lib_b, start=(0, 0)):
        ra, rb = (cell_two_arm.carry_route(p, libs(p), kin, rigids[a], tips[a]) for p, a in ((lib_a, "arm_a"), (lib_b, "arm_b")))
        steps = coordinate(ra[0], rb[0], plan.get("margin_m", 0.05), start=start)
        return None if steps is None else {"steps": steps["steps"], "makespan_s": steps["makespan_s"]}

    return pair_schedule


def _tools(plan: dict, commissioning: bool) -> dict:
    """Everything that touches hardware or heavy imports, built only by the shell."""
    import cell_calibrate
    import cell_calibration as cal
    import cell_pivot
    from cell_auto_setup import load_config
    from cell_robot_profile import bind_pipeline

    cfg = {a: attest(load_config(Path(p)), commissioning) for a, p in plan["cells"].items()}
    cals = {a: cell_pivot.with_site_maps(cfg[a], cal.load(Path(cfg[a]["calibration_path"]).expanduser())) for a in cfg}
    if not commissioning:
        return {"plan_schedule": _plan_schedule(plan, cfg, cals)}
    import cell_attempts
    import cell_pipeline as cp
    from cell_auto_safety import Guarded
    from cell_transfer import FOLDED, Gate, transfer_folded

    cells = {}
    for a in ARMS:
        if not cfg[a].get("operating_profile_path"):
            raise SystemExit(f"{a}: its config names no operating_profile_path (D-911)")
        cells[a] = cp.FifoCell(Path(cfg[a]["io"]).expanduser(), cfg[a]["cameras"], timeout_s=180,
                               operating_profile=bind_pipeline(cfg[a])["_operating_profile_binding"])

    def carry(arm, library):
        gate = Gate(Guarded(cells[arm], cfg[arm]), cfg[arm], cals[arm], sequence=FOLDED)  # D-911, as cell_auto_pick
        held = gate.open(library, lambda assessment: cell_attempts.begin(cfg[arm], assessment))
        if held is not None:
            return {"ok": False, "error": f"held: {held['reason']}"}
        moved = transfer_folded(gate, library, sequence=FOLDED)
        return {"ok": moved["result"] == "placed", "error": moved["result"]}

    def read_belt(region):
        from cell_belt_occupancy import read_belt_occupancy
        import joint_jitter

        # both regions are in arm S's top frame and its occlusion table is arm S's; an A/B arm is folded home (Gate park) before
        # cleared() reads the end region, so it cannot hide a box there. shortcut: arm_s top must see the belt end; measure it first
        try:
            receipt = cells["arm_s"].frame_receipt("top")
        except ValueError as exc:  # stale, non-advancing or undecodable frame: a reading that proves nothing
            return {"occupancy": "unknown", "reason": f"frame:{exc}"}
        frame = receipt.get("image")
        calibration = cell_calibrate.check(cfg["arm_s"], cals["arm_s"], [], frame) if frame is not None else None
        state = joint_jitter.settled_state(cells["arm_s"]).get("state")
        return read_belt_occupancy(receipt, region, calibration=calibration, joint_state_norm=state)

    return {"carry": carry, "read_belt": read_belt}


def plan_only(plan: dict, tools: dict) -> dict:
    """Assignment, each move's gate, and every pair decision a cycle could ask; nothing moves."""
    arm_of = assign(plan["moves"])
    gates = {m["id"]: {"s_to_belt": "reserve(empty reading at s_region) before load, placed() after",
                       "belt_to_stack": "arrived(occupied reading at end_region) before pick, grasped(), cleared(empty reading)",
                       "stack": "after: " + (",".join(m.get("after", ())) or "none")}[m["kind"]] for m in plan["moves"]}
    pairs = {}
    by_id = {m["id"]: m for m in plan["moves"]}
    for a in (i for i, arm in arm_of.items() if arm == "arm_a"):
        for b in (i for i, arm in arm_of.items() if arm == "arm_b"):
            schedule = tools["plan_schedule"](by_id[a]["candidates"]["arm_a"], by_id[b]["candidates"]["arm_b"])
            pairs[f"{a}+{b}"] = None if schedule is None else schedule["makespan_s"]  # None: run one after the other
    return {"assignment": arm_of, "gates": gates, "pairs": pairs}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cycle", type=Path)
    ap.add_argument("--commissioning", action="store_true")
    ap.add_argument("--person-at-switch", action="store_true")
    args = ap.parse_args(argv)
    plan = json.loads(args.cycle.read_text())
    validate(plan)
    real = args.commissioning or args.person_at_switch
    if real and not (args.commissioning and args.person_at_switch):
        raise SystemExit("this moves three arms: --commissioning --person-at-switch (D-911)")
    tools = _tools(plan, real)
    if not real:
        print(json.dumps(plan_only(plan, tools), indent=1))
        return 0
    handover = BeltHandover(plan["belt"]["missing_after_s"])
    result = Cycle(plan["moves"], plan["belt"], handover, carry=tools["carry"], read_belt=tools["read_belt"],
                   pair=None, pair_schedule=lambda a, b: None).run()  # never A and B together in real mode: see the docstring
    print(json.dumps(result, indent=1))
    return 0 if result["result"] == "DONE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
