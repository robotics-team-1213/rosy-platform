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

def test_pipeline_stages_connect_mujoco_gazebo_and_isaac_roles():
    layout = sites.Layout(container_colours="multi")
    eval_rows = [
        dict(
            task="stack",
            step="s1",
            container="bar-1",
            arm="arm_b",
            source="belt",
            target="stand_t1_r1",
            result="pass",
            lifted=True,
            belt_skew=dict(dx_mm=6.0, dy_mm=5.0, dyaw_deg=8.0),
            vision_pick=dict(colour="orange", seen_xy=[0.166, 0.169], seen_yaw_deg=-82.0, xy_err_mm=1.2, yaw_err_deg=1.1),
            xy_mm=0.4,
            yaw_deg=0.0,
        )
    ]
    score = policy.summarise(eval_rows, [dict(task="stack", seed=1, total=1, passed=1, completed=True)])
    gazebo_report = dict(failures=[], shape=[240, 320], camera_hz=5.0, stop=dict(accepted=True, cancel_acknowledged=True, travel_before_rad=0.05, travel_after_rad=0.001))
    isaac_report = dict(sha="b" * 40, rows=[dict(id="mujoco-handoff-s1-bar-1", expect="completed", run_id="isaac-01", status="SUCCEEDED", result="completed", matches=True, judgement=dict(result="completed"))])
    stages = policy.pipeline_stages(score, layout, eval_rows, pick_vision=True, belt_skew=True, gazebo_report=gazebo_report, isaac_report=isaac_report)
    assert list(stages)[:2] == ["mujoco", "isaac"]
    assert stages["mujoco"]["status"] == "passed" and stages["mujoco"]["stage_order"] == 1
    assert stages["mujoco"]["role"] == "stage1_geometry_vision_and_act_policy"
    assert stages["mujoco"]["pick_vision"] is True and stages["mujoco"]["belt_skew"] is True
    assert stages["isaac"]["status"] == "passed" and stages["isaac"]["stage_order"] == 2
    assert stages["isaac"]["role"] == "stage2_physx_contact_pad_slip_and_seating"
    assert len(stages["isaac"]["handoff"]["stage_2_isaac"]["single_arm_cases"]) == 1
    assert stages["isaac"]["handoff"]["stage_1_mujoco"]["colours_seen"] == ["orange"]
    assert stages["gazebo"]["status"] == "passed" and stages["gazebo"]["stage_order"] is None
    assert stages["gazebo"]["track"] == "ros2_execution_contract" and stages["gazebo"]["role"] == "ros2_interface_conformance"
