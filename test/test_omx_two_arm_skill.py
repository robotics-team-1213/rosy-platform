"""Two-arm sub-skills: the errors a seed draws, the language each step gets, and the pass bar. No MuJoCo needed."""
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools/sim"))
import omx_two_arm_policy as policy  # noqa: E402
import omx_two_arm_sites as sites  # noqa: E402
import omx_two_arm_skill as skills  # noqa: E402
import omx_two_arm_tasks as tasks  # noqa: E402


def test_calibration_error_is_per_seed_bounded_and_spares_the_gripper():
    """The IK baseline misses by this error; the exact arm (seed 0, or 0 deg) has none."""
    assert skills.draw_zero_error(0, 4.) == {} and skills.draw_zero_error(5, 0.) == {}
    error = skills.draw_zero_error(1003, 4.)
    assert set(error) == set(sites.ARMS)
    for arm, e in error.items():
        assert e.shape == (6,) and e[5] == 0 and (np.abs(e[:5]) <= np.radians(4.)).all() and np.abs(e[:5]).max() > 0
        assert (e == skills.draw_zero_error(1003, 4.)[arm]).all()
    assert not (skills.draw_zero_error(1004, 4.)["arm_a"] == error["arm_a"]).all()


def test_servo_lag_stays_in_the_measured_range():
    """Lag ~ 0.16 s x 40 / gain in the sim; the real joints took 0.10-0.34 s (twin 2026-11-09)."""
    assert skills.draw_servo_gain(0, True) == {} and skills.draw_servo_gain(7, False) == {}
    for gain in skills.draw_servo_gain(1003, True).values():
        lag = .16 * skills.teaching.SERVO_GAIN / gain
        assert gain.shape == (5,) and (lag >= skills.LAG_S[0]).all() and (lag <= skills.LAG_S[1]).all()


def test_each_step_names_its_arm_and_site_to_the_language_model():
    layout = sites.Layout()
    steps = [step for name in policy.TASKS for step in tasks.get_task(layout, name)["steps"]]
    for skill in skills.SKILLS:
        prompts = {skills.prompt(step, skill) for step in steps}
        assert all(p.startswith(("arm_a:", "arm_b:")) for p in prompts) and len(prompts) > 1
    assert skills.prompt(steps[0], "grasp") != skills.prompt(steps[0], "release")


def test_sub_skills_are_consecutive_waypoint_phases():
    """The hand-off waits for the first phase and ends after the last: a gap would hand the model a step it never saw."""
    layout = sites.Layout()
    step = tasks.get_task(layout, policy.TASKS[0])["steps"][0]
    names = [w[0] for w in tasks.waypoints(layout, step, {})]
    for spec in skills.SKILLS.values():
        k = names.index(spec["phases"][0])
        assert tuple(names[k:k + len(spec["phases"])]) == spec["phases"]


def test_a_sub_skill_round_passes_at_eighteen_of_twenty():
    """No whole tasks in a sub-skill round: the bar is the sim acceptance rate, not 'finished every task'."""
    assert policy.outcome(dict(n=20, passed=18, whole=[]), "grasp") == dict(status="passed")
    assert policy.outcome(dict(n=20, passed=17, whole=[]), "release")["status"] == "failed"
    assert policy.outcome(dict(n=0, passed=0, whole=[]), "grasp")["status"] == "failed"
