"""The concurrent scheduler's belt handover glue, MuJoCo-free: the ledger chain, injected unknown readings, a missing delivery,
an after-pick step failure and a slowed arm, against a fake teacher over the real layout. `run_concurrent_steps` touches the world
only through `world.pose`/`world.put`, so the fake answers from bookkeeping (the pattern of the other two-arm tests that fake the world)."""
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools/sim"))
import omx_two_arm_sites as sites  # noqa: E402
from omx_two_arm_teacher_stages import Faults, run_concurrent_steps  # noqa: E402

LAYOUT = sites.Layout()
PHASES = ("approach", "grasp", "close", "lift", "carry", "lower", "release", "retreat", "park")


class FakeWorld:
    """Containers the test places and lifts; one never placed sits far off the belt."""

    def __init__(self, layout):
        self.layout, self.pos = layout, {}

    def put(self, data, cid, site, parked=0, jitter=(0., 0., 0.)):
        if site is None:
            self.pos[cid] = np.array([-1.4, 1.0 + .1 * parked, .016])
        else:
            s = self.layout.sites[site]
            self.pos[cid] = np.array([s["xy"][0] + jitter[0], s["xy"][1] + jitter[1], s["z"]])

    def pose(self, data, cid):
        return np.array(self.pos.get(cid, (-1.4, -1.4, .016))), 0., 0.


class FakeTeacher:
    """Phases and container moves only: one target per phase, so the scheduler's measured-progress gates see progress happen."""

    def __init__(self, layout, long=None):
        self.layout, self.world, self.long = layout, FakeWorld(layout), long or {}

    def step_gen(self, data, step, here, ctx):
        for _ in range(self.long.get(step["id"], 0)):  # steps the test wants to outlive a peer's pick
            ctx.phase = "approach"
            yield np.zeros(6)
        for phase in PHASES:
            ctx.phase = phase
            if phase == "carry" and step["from"] == "belt":  # lifted: over the belt end, but far above it
                self.world.pos[step["container"]][2] += .5
            if phase == "lower":
                self.world.put(data, step["container"], step["to"])
            yield np.zeros(6)
        return dict(step=step["id"], container=step["container"], arm=step["arm"], result="pass")

    def off_stand(self, data, step, here):
        pass

    def frame(self, data, targets, label, ctxs=None):
        pass


def make_task():
    """A belt pick per arm plus an arm_b carry that outlives arm_a's pick, and steps after each that must never start after a stop."""
    return dict(name="belt-glue", supply=["bar-1", "bar-2"], start={}, steps=[
        dict(id="p2", container="bar-2", **{"from": "belt"}, to="ship-h1r1-l0", arm="arm_a", zones=[["mid"], ["a"]]),
        dict(id="q1", container="bar-3", **{"from": "ship-h1r0-l0"}, to="ship-h1r2-l0", arm="arm_b", zones=[["b"], ["b"]]),
        dict(id="p1", container="bar-1", **{"from": "belt"}, to="ship-h1r0-l1", arm="arm_b", zones=[["mid"], ["b"]]),
        dict(id="r1", container="bar-5", **{"from": "ship-h1r2-l0"}, to="tmp-a-1", arm="arm_a", zones=[["a"], ["a"]]),
        dict(id="q2", container="bar-4", **{"from": "ship-h1r2-l0"}, to="tmp-b-1", arm="arm_b", zones=[["b"], ["b"]])])


def miss_task():
    return dict(name="belt-miss", supply=["bar-1"], start={}, steps=[
        dict(id="m1", container="bar-1", **{"from": "belt"}, to="ship-h1r1-l0", arm="arm_a", zones=[["mid"], ["a"]])])


def run(task, faults=None, long=None):
    teacher = FakeTeacher(LAYOUT, long=long)
    for cid, site in task.get("start", {}).items():
        teacher.world.put(None, cid, site)
    return run_concurrent_steps(teacher, None, task, dict(task.get("start", {})), faults=faults)


PASSING = dict(max_cargo_on_belt=1, picks_before_arrival=0, steps_started_after_stop=0)


def test_without_faults_two_deliveries_run_the_whole_chain_one_at_a_time():
    rows, _, stopped, extra = run(make_task())
    assert stopped is None and [r["result"] for r in rows] == ["pass"] * 5
    events = extra["belt_events"]
    assert [e["event"] for e in events] == ["reserve", "placed", "arrived", "grasped", "cleared"] * 2
    assert [e["generation"] for e in events] == [1] * 5 + [2] * 5 and events[0]["cargo"] == "bar-2" and events[5]["cargo"] == "bar-1"
    assert extra["invariants"] == PASSING


def test_all_unknown_readings_hold_every_gate():
    rows, timing, stopped, extra = run(miss_task(), Faults(unknown_p=1.0, seed=1))
    # S never gets a usable reading: nothing is ever placed or picked, and the run ends at the time limit, not by moving on
    assert stopped == "timeout after 900 s" and rows == [] and timing == {} and extra["belt_events"] == []
    assert extra["invariants"]["picks_before_arrival"] == 0


def test_sporadic_unknown_readings_retry_and_the_run_still_completes():
    rows, _, stopped, extra = run(make_task(), Faults(unknown_p=0.5, seed=3))
    assert stopped is None and [r["result"] for r in rows] == ["pass"] * 5 and extra["invariants"] == PASSING


def test_a_delivery_that_never_arrives_goes_missing_and_stops_the_run():
    rows, timing, stopped, extra = run(miss_task(), Faults(miss="m1"))
    assert stopped == "belt_missing" and rows == [] and timing == {}  # the pick never started and nothing else did either
    assert [e["event"] for e in extra["belt_events"]] == ["reserve", "placed", "missing"]
    assert 19.9 <= extra["belt_wait_s"] <= 21.
    assert extra["invariants"] == dict(max_cargo_on_belt=0, picks_before_arrival=0, steps_started_after_stop=0)


def test_a_step_failing_after_its_pick_stops_the_peer_after_its_current_step():
    rows, timing, stopped, extra = run(make_task(), Faults(fail_at="p2"), long={"q1": 40})
    assert stopped == "failed:p2"
    assert {r["step"]: r["result"] for r in rows} == {"p2": "fail", "q1": "pass"}  # the peer finished; p1, r1 and q2 never started
    assert "p1" not in timing and "r1" not in timing and "q2" not in timing
    assert next(r for r in rows if r["step"] == "p2")["reason"].startswith("injected")
    assert extra["invariants"]["picks_before_arrival"] == 0 and extra["invariants"]["steps_started_after_stop"] == 0


def test_a_slowed_arm_stretches_its_segments_and_keeps_the_order():
    _, base_timing, _, _ = run(make_task())
    rows, timing, stopped, extra = run(make_task(), Faults(slow={"arm_a": 3.}))
    assert stopped is None and [r["result"] for r in rows] == ["pass"] * 5 and extra["invariants"] == PASSING
    took = lambda t: t["p2"]["end_s"] - t["p2"]["start_s"]  # noqa: E731
    assert took(timing) > 2.5 * took(base_timing)  # ~3x stretched, the belt order still by measured progress
