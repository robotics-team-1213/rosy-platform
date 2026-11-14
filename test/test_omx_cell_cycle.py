"""cell_cycle: the three-arm cycle on fakes. The belt holds one box, every belt move waits for its evidence, an unknown reading
holds, a failure stops new moves while the peer finishes, and A/B overlap only with a schedule."""
from pathlib import Path
import sys
import threading

import pytest

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "middleware/devices/omx/adapter"))
sys.path.insert(0, str(ROOT / "deploy/robot/omx"))
import cell_cycle as cc  # noqa: E402
from cell_belt_handover import BeltHandover  # noqa: E402

S_REGION, END_REGION = [0, 0, 10, 10], [20, 0, 30, 10]
BELT = {"s_region_px": S_REGION, "end_region_px": END_REGION, "missing_after_s": 5.0, "transit_s": 0.01}


def reading(occupancy, reason=""):
    return {"occupancy": occupancy, "reason": reason}


def move(id_, kind, cands, cargo=None, after=()):
    return {"id": id_, "cargo": cargo or id_, "kind": kind, "candidates": {a: f"{a}-{id_}.json" for a in cands}, "after": list(after)}


class World:
    """The belt as the arms and the camera see it: carries change it, readings report it."""

    def __init__(self, unknown_s=0, fail=(), clock=None):
        self.box, self.at, self.unknown_s, self.fail, self.clock = None, None, unknown_s, set(fail), clock
        self.carried, self.concurrent, self.peak, self.pairs, self.lock = [], 0, 0, [], threading.Lock()
        self.mid_arrives = None
        self.lost = False  # a placed box that never reaches the end

    def read_belt(self, region):
        if self.mid_arrives is not None and self.clock() >= self.mid_arrives:
            self.box, self.at, self.mid_arrives = "old", "end", None  # the box stopped mid-belt, seen nowhere until it reaches the end
        if region == S_REGION:
            if self.unknown_s > 0:
                self.unknown_s -= 1
                return reading("unknown", "stale_frame")
            return reading("occupied" if self.box is not None and self.at == "s" else "empty")
        return reading("occupied" if self.box is not None and self.at == "end" else "empty")

    def carry(self, arm, library):
        name = library.split("-", 1)[1][:-5]
        with self.lock:
            self.concurrent += 1
            self.peak = max(self.peak, self.concurrent)
        try:
            if name in self.fail:
                return {"ok": False, "error": "boom"}
            if arm == "arm_s":
                assert self.box is None, "a second box on the belt"
                self.box, self.at = name, "s" if self.lost else "end"
            elif name.startswith("b"):
                assert self.box is not None, "picked from an empty belt"
                self.box = self.at = None
            self.carried.append((arm, name))
            return {"ok": True, "error": None}
        finally:
            with self.lock:
                self.concurrent -= 1

    def pair(self, lib_a, lib_b, schedule):
        self.pairs.append((lib_a, lib_b))
        return {"ok": True, "error": None}


def cycle(moves, world, schedule=None, clock=None, **kw):
    log = []
    handover = BeltHandover(BELT["missing_after_s"], **({"clock": clock} if clock else {}))
    c = cc.Cycle(moves, BELT, handover, carry=world.carry, pair=world.pair, pair_schedule=lambda a, b: schedule,
                 read_belt=world.read_belt, sleep=lambda s: None, tick_s=0.001,
                 log=log.append, **({"clock": clock} if clock else {}), **kw)
    return c, handover, log


def three_tiers():
    moves = []
    for n in (1, 2, 3):
        moves.append(move(f"s{n}", "s_to_belt", ["arm_s"], cargo=f"box{n}", after=[f"b{n - 1}"] if n > 1 else []))
        moves.append(move(f"b{n}", "belt_to_stack", ["arm_a", "arm_b"], cargo=f"box{n}", after=[f"s{n}"] + ([f"b{n - 1}"] if n > 1 else [])))
    return moves


def test_happy_three_tiers():
    world = World()
    c, handover, _ = cycle(three_tiers(), world)
    out = c.run()
    assert out["result"] == "DONE" and out["reason"] is None
    names = [n for _, n in world.carried]
    assert names == ["s1", "b1", "s2", "b2", "s3", "b3"]  # one box at a time, each fed before it is stacked
    assert handover.state == "empty" and handover.generation == 3
    assert [e["event"] for e in handover.events if e["generation"] == 1] == ["reserve", "placed", "arrived", "grasped", "cleared"]
    assert world.peak == 1


def test_unknown_reading_holds_then_proceeds():
    world = World(unknown_s=3)
    c, _, log = cycle([move("s1", "s_to_belt", ["arm_s"])], world)
    out = c.run()
    assert out["result"] == "DONE" and world.carried == [("arm_s", "s1")]
    assert world.unknown_s == 0  # three ticks were spent holding, nothing moved meanwhile
    assert [e for e in log if "start" in e][0]["start"] == ["s1"]


def test_missing_box_stops_and_reports():
    ticks = {"t": 0.0}

    def clock():
        return ticks["t"]

    world = World()
    world.lost = True
    moves = [move("s1", "s_to_belt", ["arm_s"]), move("b1", "belt_to_stack", ["arm_a"], cargo="s1", after=["s1"]),
             move("s2", "s_to_belt", ["arm_s"], after=["b1"])]
    c, handover, _ = cycle(moves, world, clock=clock)
    c.sleep = lambda s: ticks.__setitem__("t", ticks["t"] + 2.0)
    out = c.run()
    assert out["result"] == "HOLD" and out["reason"].startswith("belt_missing")
    assert handover.state == "missing" and world.carried == [("arm_s", "s1")]  # b1 never picked, s2 never loaded


def test_carry_failure_stops_new_moves():
    world = World(fail={"x1"})
    moves = [move("x1", "stack", ["arm_a"]), move("x2", "stack", ["arm_b"], after=["x1"]), move("s1", "s_to_belt", ["arm_s"], after=["x1"])]
    out = cycle(moves, world)[0].run()
    assert out["result"] == "HOLD" and "x1: boom" in out["reason"]
    assert out["state"] == {"x1": "failed", "x2": "pending", "s1": "pending"} and world.carried == []


def test_failed_pair_returns_hold_and_starts_nothing_more():
    world = World()
    world.pair = lambda a, b, schedule: {"ok": False, "error": "peer finished its segment, a failed"}
    moves = [move("x1", "stack", ["arm_a"]), move("x2", "stack", ["arm_b"]), move("x3", "stack", ["arm_a"], after=["x1"])]
    out = cycle(moves, world, schedule={"steps": []})[0].run()
    assert out["result"] == "HOLD" and out["state"] == {"x1": "failed", "x2": "failed", "x3": "pending"}


def test_s_and_ab_never_move_together():
    world = World()
    slow = world.carry

    def carry(arm, library):
        threading.Event().wait(0.02)  # long enough for a second start to overlap
        return slow(arm, library)

    world.carry = carry
    moves = [move("s1", "s_to_belt", ["arm_s"]), move("x1", "stack", ["arm_a"]), move("x2", "stack", ["arm_b"])]
    out = cycle(moves, world, schedule=None)[0].run()
    assert out["result"] == "DONE" and len(world.carried) == 3 and world.peak == 1


def test_reserve_needs_the_whole_belt_empty():
    world = World()
    world.box, world.at = "old", "end"  # left at the end region before a restart; the S region reads empty
    c, handover, _ = cycle([move("s1", "s_to_belt", ["arm_s"])], world, timeout_s=0.05)
    out = c.run()
    assert out["reason"] == "timeout" and world.carried == [] and handover.generation == 0
    assert c._belt_empty() == {"occupancy": "occupied", "reason": "end_region"}
    world.at, world.unknown_s = None, 1
    assert c._belt_empty() == {"occupancy": "unknown", "reason": "s_region:stale_frame"}  # unknown anywhere is unknown


def test_one_belt_pick_per_cargo():
    base = {"schema": cc.SCHEMA, "belt": BELT, "cells": {}}
    s1, b1 = move("s1", "s_to_belt", ["arm_s"]), move("b1", "belt_to_stack", ["arm_a"], cargo="s1")
    cc.validate({**base, "moves": [s1, b1]})
    for bad in ([s1, b1, move("b2", "belt_to_stack", ["arm_b"], cargo="s1")], [s1], [b1]):
        with pytest.raises(ValueError):
            cc.validate({**base, "moves": bad})
    world = World()  # the core also holds when an unvalidated cycle names the cargo twice: one arrival, one pick
    moves = [move("s1", "s_to_belt", ["arm_s"]), move("b1", "belt_to_stack", ["arm_a"], cargo="s1", after=["s1"]),
             move("b2", "belt_to_stack", ["arm_b"], cargo="s1", after=["s1"])]
    c, handover, _ = cycle(moves, world, schedule={"steps": []}, timeout_s=0.1)
    c.run()
    assert [e["event"] for e in handover.events].count("arrived") == 1 and world.pairs == []
    assert [n for _, n in world.carried].count("b1") + [n for _, n in world.carried].count("b2") == 1


def test_supervised_flag_only_with_both_cli_flags(tmp_path, monkeypatch):
    assert cc.attest({"x": 1}, True)["_commissioning"] == {"person_at_switch": True}
    assert "_commissioning" not in cc.attest({"x": 1}, False)
    plan = {"schema": cc.SCHEMA, "belt": BELT, "cells": {}, "moves": [move("s1", "s_to_belt", ["arm_s"], cargo="c"),
                                                                       move("b1", "belt_to_stack", ["arm_a"], cargo="c")]}
    path = tmp_path / "cycle.json"
    path.write_text(__import__("json").dumps(plan))
    seen = []

    def tools(plan, real):
        seen.append(real)
        raise RuntimeError("reached")

    monkeypatch.setattr(cc, "_tools", tools)
    for flags in (["--commissioning"], ["--person-at-switch"]):
        with pytest.raises(SystemExit):
            cc.main([str(path), *flags])
    assert seen == []
    with pytest.raises(RuntimeError):
        cc.main([str(path), "--commissioning", "--person-at-switch"])
    with pytest.raises(RuntimeError):
        cc.main([str(path)])
    assert seen == [True, False]


def test_pair_none_runs_one_after_the_other():
    world = World()
    moves = [move("x1", "stack", ["arm_a"]), move("x2", "stack", ["arm_b"])]
    c, _, _ = cycle(moves, world, schedule=None)
    assert c.run()["result"] == "DONE"
    assert world.pairs == [] and world.peak == 1 and sorted(n for _, n in world.carried) == ["x1", "x2"]


def test_pair_schedule_overlaps_a_and_b_only():
    world = World()
    moves = [move("x1", "stack", ["arm_a"]), move("x2", "stack", ["arm_b"]), move("s1", "s_to_belt", ["arm_s"])]
    c, _, _ = cycle(moves, world, schedule={"steps": []})
    assert c.run()["result"] == "DONE"
    assert world.pairs == [("arm_a-x1.json", "arm_b-x2.json")]
    assert world.carried == [("arm_s", "s1")]  # S carried alone, never in a pair


def test_plan_gen_never_decreases():
    world = World()
    c, _, log = cycle(three_tiers(), world, schedule=None)
    c.run()
    gens = [e["plan_gen"] for e in log]
    assert gens == sorted(gens) and len(set(gens)) > 6 and c.plan_gen == gens[-1]


def test_assignment_earliest_free_and_primary_on_tie():
    both = ["arm_a", "arm_b"]
    assert cc.assign([move("m1", "stack", both), move("m2", "stack", both)]) == {"m1": "arm_a", "m2": "arm_b"}
    ties = [move("m1", "stack", both), move("m2", "stack", both), move("m3", "stack", ["arm_b", "arm_a"])]
    assert cc.assign(ties) == {"m1": "arm_a", "m2": "arm_b", "m3": "arm_b"}  # both free at 1: the primary (arm_b) wins
    assert cc.assign([move("m1", "stack", both), move("m2", "stack", both, after=["m1"])])["m2"] == "arm_a"  # after: no earlier start on b
    with pytest.raises(ValueError):
        cc.assign([move("m1", "stack", both, after=["m2"]), move("m2", "stack", both, after=["m1"])])


def test_validate_keeps_s_to_belt_on_arm_s():
    plan = {"schema": cc.SCHEMA, "belt": BELT, "cells": {}, "moves": [move("s1", "s_to_belt", ["arm_s", "arm_a"])]}
    with pytest.raises(ValueError):
        cc.validate(plan)
    plan["moves"] = [move("b1", "belt_to_stack", ["arm_s"])]
    with pytest.raises(ValueError):
        cc.validate(plan)


def fake_clock(step):
    now = {"t": 0.0}
    return now, (lambda: now["t"]), (lambda s: now.__setitem__("t", now["t"] + step))


def test_start_waits_transit_time_and_catches_a_box_mid_belt():
    now, clock, sleep = fake_clock(0.4)
    world = World(clock=clock)
    world.mid_arrives = 1.0  # invisible at both regions until transit_s (1.0 here) after the first look
    c, handover, _ = cycle([move("s1", "s_to_belt", ["arm_s"])], world, clock=clock, timeout_s=10)
    c.belt, c.sleep = {**BELT, "transit_s": 1.0}, sleep
    out = c.run()
    assert world.carried == [] and handover.generation == 0  # S never loaded onto the box that appeared at the end
    assert world.box == "old" and out["reason"] == "timeout"  # the box showed at the end, so the start check never passed


def test_normal_empty_start_passes_after_transit():
    now, clock, sleep = fake_clock(0.4)
    world = World(clock=clock)
    c, _, _ = cycle([move("s1", "s_to_belt", ["arm_s"])], world, clock=clock)
    c.belt, c.sleep = {**BELT, "transit_s": 1.0}, sleep
    assert c.run()["result"] == "DONE" and world.carried == [("arm_s", "s1")] and now["t"] >= 1.0


def test_transit_s_is_required_and_positive():
    base = {"schema": cc.SCHEMA, "cells": {}, "moves": []}
    for belt in ({k: v for k, v in BELT.items() if k != "transit_s"}, {**BELT, "transit_s": 0}):
        with pytest.raises(ValueError):
            cc.validate({**base, "belt": belt})


def test_timeout_returns_hold_without_waiting_for_a_running_carry():
    release, started = threading.Event(), threading.Event()
    world = World()

    def carry(arm, library):
        started.set()
        release.wait(5)
        return {"ok": True, "error": None}

    world.carry = carry
    c, _, _ = cycle([move("x1", "stack", ["arm_a"])], world, timeout_s=0.05)
    try:
        out = c.run()  # returns while x1 is still blocked
        assert started.is_set() and out["result"] == "HOLD" and out["running"] == ["x1"]
        assert out["reason"].startswith("timeout, still running")
    finally:
        release.set()
