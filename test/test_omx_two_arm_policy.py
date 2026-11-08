"""Two-arm ACT tool: what the plan tells the model, and how a round's score is counted. No MuJoCo needed."""
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools/sim"))
import omx_two_arm_policy as policy  # noqa: E402
import omx_two_arm_sites as sites  # noqa: E402
import omx_two_arm_tasks as tasks  # noqa: E402


def test_every_plan_step_gets_its_own_goal():
    """Only the top camera's picture could otherwise tell the model which plan step it is on."""
    layout = sites.Layout()
    steps, goals = [], []
    for name in policy.TASKS:
        task = tasks.get_task(layout, name)
        here = dict(task.get("start", {}))
        for step in task["steps"]:
            steps.append(step)
            goals.append(policy.goal_vector(layout, step, {k: v for k, v in here.items() if k != step["container"]}))
            here[step["container"]] = step["to"]
    goals = np.array(goals)
    assert goals.shape == (len(steps), policy.GOAL_SIZE)
    assert len({goal.tobytes() for goal in goals}) == len(steps)
    assert all(goal[0] == (step["arm"] == "arm_a") and goal[11] == (step["arm"] == "arm_b") for goal, step in zip(goals, steps))


def test_both_arms_goals_share_one_vector_and_a_waiting_arm_is_zero():
    """Concurrent mode: each frame carries both arms' current steps; an arm between steps has zeros."""
    a, b = np.arange(1, 12, dtype=np.float32), -np.arange(1, 12, dtype=np.float32)
    both = policy.goal_of({"arm_b": b, "arm_a": a})
    assert both.shape == (policy.GOAL_SIZE,) and (both[:11] == a).all() and (both[11:] == b).all()
    assert (policy.goal_of({"arm_b": b})[:11] == 0).all() and (policy.goal_of({}) == 0).all()


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


def test_calibration_error_is_per_seed_bounded_and_spares_the_gripper():
    """The sub-skill's IK baseline misses by this error; the exact arm (seed 0, or 0 deg) has none."""
    assert policy.draw_zero_error(0, 4.) == {} and policy.draw_zero_error(5, 0.) == {}
    error = policy.draw_zero_error(1003, 4.)
    assert set(error) == set(sites.ARMS)
    for arm, e in error.items():
        assert e.shape == (6,) and e[5] == 0 and (np.abs(e[:5]) <= np.radians(4.)).all() and np.abs(e[:5]).max() > 0
        assert (e == policy.draw_zero_error(1003, 4.)[arm]).all()
    assert not (policy.draw_zero_error(1004, 4.)["arm_a"] == error["arm_a"]).all()


def test_each_step_names_its_arm_and_source_to_the_language_model():
    layout = sites.Layout()
    prompts = {policy.skill_prompt(step) for name in policy.TASKS for step in tasks.get_task(layout, name)["steps"]}
    assert all(p.startswith(("arm_a:", "arm_b:")) for p in prompts) and len(prompts) > 1


def test_a_sub_skill_round_passes_at_eighteen_of_twenty():
    """No whole tasks in a sub-skill round: the bar is the sim acceptance rate, not 'finished every task'."""
    assert policy.outcome(dict(n=20, passed=18, whole=[]), "grasp") == dict(status="passed")
    assert policy.outcome(dict(n=20, passed=17, whole=[]), "grasp")["status"] == "failed"
    assert policy.outcome(dict(n=0, passed=0, whole=[]), "grasp")["status"] == "failed"
