"""Whole-scenario IK evaluation (omx_two_arm_chain): which arm is in reported angles when, what a concurrent task needs, and the summary. MuJoCo-free."""
from pathlib import Path
import sys
import types

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools/sim"))
import omx_two_arm_chain as chain  # noqa: E402
import omx_two_arm_plan as plan  # noqa: E402
import omx_two_arm_sites as sites  # noqa: E402
import omx_two_arm_tasks as tasks  # noqa: E402

LAYOUT = sites.Layout()


def test_only_an_arm_in_its_grasp_half_carries_the_zero_error():
    t = object.__new__(chain.ChainTeacher)
    t.arm_ctx = {"arm_a": types.SimpleNamespace(phase="close"), "arm_b": types.SimpleNamespace(phase="carry")}
    assert not t.priv("arm_a") and t.priv("arm_b")
    t.arm_ctx["arm_a"].phase = "carry"
    assert t.priv("arm_a") and t.priv("arm_a") == t.priv("arm_b")
    t.arm_ctx = {}
    assert t.priv("arm_a")  # an arm with no step holds its true wait pose


def test_the_files_tasks_become_concurrent_tasks_with_order_and_zones():
    for name in ("stack", "outbound", "rehandle"):
        task = tasks.get_task(LAYOUT, name)
        conc = chain.concurrent_task(LAYOUT, task)
        assert [s["id"] for s in conc["steps"]] == [s["id"] for s in task["steps"]] and conc["start"] == task["start"]
        assert all(len(s["zones"]) == 2 and s["zones"][0] and s["zones"][1] for s in conc["steps"])
        assert [s["arm"] for s in conc["steps"]] == [s["arm"] for s in task["steps"]]  # the file's arms stay
        belt = [s for s in conc["steps"] if s["from"] == "belt"]
        assert all(b["after_pick"] == [a["id"]] for a, b in zip(belt, belt[1:])) and all(not s["after_pick"] for s in conc["steps"] if s["from"] != "belt")
    stack = {s["id"]: s for s in chain.concurrent_task(LAYOUT, tasks.get_task(LAYOUT, "stack"))["steps"]}
    assert "s1" in stack["s4"]["after"]  # a tier waits for the container it stands on
    assert chain.concurrent_task(LAYOUT, stack_task := chain.concurrent_task(LAYOUT, tasks.get_task(LAYOUT, "stack"))) is stack_task  # planned tasks pass through


def test_holds_is_what_the_scheduler_gives_each_move():
    res = plan.compare(LAYOUT, "outbound", plan.table_can({s: {"arm_a", "arm_b"} for s in LAYOUT.sites}))
    for row in res["two-arm"]["outbound"]["timeline"]:
        assert row["zones"] == [sorted(z) for z in plan.holds(LAYOUT, row["arm"], row["source"], row["destination"])]


def test_the_summary_counts_stage_and_step_passes_and_names_the_first_failures():
    row = lambda step, result, grasp, **kw: dict(step=step, result=result, grasp=dict(ok=grasp) if grasp is not None else None, **kw)  # noqa: E731
    rows = [row("s1", "pass", True, vision_pick=dict(xy_err_mm=1.)), row("s2", "fail", True, neighbours_disturbed=["bar-1 9 mm"], vision_pick=dict(xy_err_mm=3.)),
            row("s3", "blocked", None, reason="top camera did not see bar-3 at belt"), row("s4", "fail", False, arm_arm_contacts=["a~b"])]
    out = chain.summarise(dict(rows=rows, steps=4, steps_pass=1, completed=False, makespan_s=10., invariants=dict(picks_before_arrival=0)))
    assert (out["step_pass"], out["grasp_pass"], out["first_fail"], out["first_grasp_fail"]) == (1, 2, "s2", "s3")
    assert (out["neighbour"], out["arm_arm"], out["vision_unseen"], out["vision_xy_mm"]) == (1, 1, ["s3"], [2.0, 3.0]) and not out["grasp_complete"]
    conc = chain.summarise(dict(rows=rows[::-1], steps=4, steps_pass=1, completed=False, makespan_s=10., concurrent=True, stopped="deadlock: ['s9'] cannot start",
                                timing={r["step"]: dict(end_s=i) for i, r in enumerate(rows)}, overlap_s=2.))
    assert conc["first_fail"] == "s2" and conc["deadlock"] and conc["overlap_s"] == 2.  # in the order the steps ended, not the order the rows came
