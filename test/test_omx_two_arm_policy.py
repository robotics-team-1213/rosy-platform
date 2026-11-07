"""Two-arm ACT tool: what the plan tells the model, and how a round's score is counted. No MuJoCo needed."""
import math
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools/sim"))
import omx_two_arm_policy as policy  # noqa: E402
import omx_two_arm_sites as sites  # noqa: E402
import omx_two_arm_tasks as tasks  # noqa: E402


def test_every_plan_step_gets_its_own_goal():
    """Only the top camera's picture could otherwise tell the model which of 21 steps it is on."""
    layout = sites.Layout()
    steps = [step for name in policy.TASKS for step in tasks.get_task(layout, name)["steps"]]
    goals = np.array([policy.goal_vector(layout, step) for step in steps])
    assert goals.shape == (21, 12)
    assert len({goal.tobytes() for goal in goals}) == 21
    assert all(goal[0] == (step["arm"] == "arm_a") and goal[1] == (step["arm"] == "arm_b") for goal, step in zip(goals, steps))


def test_a_container_turned_half_way_round_is_the_same_goal():
    layout = sites.Layout()
    step = dict(arm="arm_a", to="tmp-a-1", **{"from": "belt"})
    site = layout.sites["tmp-a-1"]
    before = policy.goal_vector(layout, step)
    layout.sites["tmp-a-1"] = dict(site, yaw=site["yaw"] + math.pi)
    assert np.allclose(before, policy.goal_vector(layout, step), atol=1e-5)


def test_a_round_counts_steps_and_keeps_whole_runs_apart():
    rows = [dict(task="stack", step="s1", result="pass", lifted=True), dict(task="stack", step="s1", result="fail", lifted=True), dict(task="stack", step="s2", result="fail", lifted=False)]
    whole = [dict(task="stack", seed=1, total=9, passed=3, completed=False, last={})]
    score = policy.summarise(rows, whole)
    assert (score["n"], score["passed"], score["lifted"]) == (3, 1, 2)
    assert score["per_step"] == {"stack/s1": 1, "stack/s2": 0}
    assert score["whole"] == [dict(task="stack", seed=1, total=9, passed=3, completed=False)]
    assert 0 < score["wilson_low"] < 1 / 3 < score["wilson_high"]


def test_only_finished_tasks_make_a_round_pass():
    """The first real round ran to the end with 0 of 63 steps and read as passed on the screen."""
    assert policy.outcome(dict(whole=[dict(completed=True), dict(completed=True)])) == dict(status="passed")
    for whole in ([dict(completed=True), dict(completed=False)], []):
        assert policy.outcome(dict(whole=whole))["status"] == "failed"
