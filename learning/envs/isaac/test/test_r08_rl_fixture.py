"""The PPO fixture and MuJoCo handoff must agree on the same physical layout."""

from pathlib import Path
import json
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from container_rl_fixture import fixture
from r08_rl_fixture import CASE, PRESET, cell_layout, layout_digest, request_for
from run_catalog import normalize
from run_store import requested


@pytest.mark.parametrize("layers", [1, 2, 3])
def test_r08_targets_are_exact_layout_slots(layers):
    layout = cell_layout()
    value = fixture(layers=layers, case=CASE)
    assert value["layout_sha256"] == layout_digest(layout)
    assert len(value["stack_plan"]) == layers * 3
    for item, (cid, name, arm) in zip(value["stack_plan"], layout.plan_order()):
        site = layout.sites[name]
        assert item["id"] == cid
        assert item["target"] == pytest.approx([*site["xy"], site["z"]])
        assert item["size"] == list(layout.box)
        assert item["arm"] == ("arm_a", "arm_b").index(arm)
    assert value["belt_source_z_m"] == pytest.approx(layout.belt_top)
    assert value["arm_bases_m"][0][1] == pytest.approx(-.1555)


def test_new_case_rejects_a_modified_layout():
    layout = cell_layout()
    assert layout.choices["preset"] == PRESET
    assert request_for(layout, 4, 3) == dict(seed=4, layers=3, case=CASE, layout_sha256=layout_digest(layout))
    layout.belt_y += .01
    with pytest.raises(ValueError, match="layout"):
        request_for(layout, 4, 3)


def test_r08_home_is_inside_existing_control_profile():
    import yaml
    from stacking_fixture import PROFILE, advance_joint

    joints = yaml.safe_load(PROFILE.read_text())["joints"]
    for home in fixture(layers=1, case=CASE)["home_joints_rad"]:
        for position, limits in zip(home, joints.values()):
            assert advance_joint(position, 0., 0., limits, 4/120) == (position, 0.)


def test_run_catalog_requires_the_mu_joco_layout_hash():
    config = request_for(cell_layout(), 4, 3)
    scenario = "omx-map-container-stacking-rl"
    assert requested(normalize(scenario, config)) == config
    with pytest.raises(ValueError, match="SHA-256"):
        normalize(scenario, dict(config, layout_sha256="0" * 64))
    with pytest.raises(ValueError):
        normalize("omx-map-container-stack", config)


def test_stage_two_handoff_selects_ppo_and_separates_training_from_evaluation():
    layout = cell_layout()
    from omx_two_arm_teacher_stages import isaac_handoff
    from omx_ladder import judge_isaac_stage

    rows = [dict(container=cid, target=site, arm=arm) for cid, site, arm in layout.plan_order()]
    for task, count in (("stack-t1", 3), ("stack", 6), ("stack", 9)):
        result = dict(task=task, steps=count, completed=True, rows=rows[:count])
        handoff = isaac_handoff(result, layout, seed=42)["stage_2_isaac"]
        assert handoff["two_arm_scenario"] == "omx-map-container-stacking-rl"
        assert handoff["two_arm_config"] == request_for(layout, 42, count // 3)
        assert handoff["ready"]
    result = dict(task="stack-t2", steps=3, completed=True, rows=rows[3:6])
    assert not isaac_handoff(result, layout)["stage_2_isaac"]["ready"]
    report = dict(schema="rosy.omx-stacking-rl/1", training_verified=True, task_success=False,
                  evaluation_successes=0, fixture={"case": CASE})
    assert judge_isaac_stage(report)["status"] == "failed"
    assert judge_isaac_stage(report)["result"]["training_verified"]


def test_ppo_judgement_requires_matching_final_snapshot(tmp_path):
    from omx_ladder import judge_isaac_stage, read_ppo_snapshot

    config = request_for(cell_layout(), 42, 1)
    sha = "1" * 40
    observation = dict(snapshot="FINAL", status="SUCCEEDED", run_id="run",
                       input=dict(config=config, source_sha=sha, scenario_id="omx-map-container-stacking-rl"))
    report = dict(schema="rosy.omx-stacking-rl/1", seed=42, fixture=config, training_verified=True,
                  task_success=True, evaluation_successes=1, evaluation_episodes=1)
    (tmp_path / "observation.json").write_text(json.dumps(observation))
    (tmp_path / "stacking-report.json").write_text(json.dumps(report))
    assert judge_isaac_stage(report)["status"] == "failed"
    assert judge_isaac_stage(read_ppo_snapshot(tmp_path, config, sha))["status"] == "passed"
    with pytest.raises(ValueError, match="MuJoCo handoff"):
        read_ppo_snapshot(tmp_path, dict(config, seed=43), sha)


def test_evaluation_progress_tracks_opposing_contact_and_lift_per_cargo():
    from stacking_task_helpers import record_evaluation_step

    progress = {}
    step = dict(id="bar-1", arm=1, tcp_distance_m=.08, rise_m=.01, finger_forces_n=[.8, 0.],
                lifted=False, seated=False, position_m=[.1, 0., .03], goal_distance_m=.1, terminal=None)
    record_evaluation_step(progress, step)
    assert progress["bar-1"]["max_opposing_contact_n"] == 0.
    record_evaluation_step(progress, dict(step, rise_m=.04, tcp_distance_m=.01,
                                          finger_forces_n=[.2, .3], lifted=True, terminal="timeout"))
    assert progress["bar-1"] == dict(arm=1, samples=2, min_tcp_distance_m=.01, max_rise_m=.04,
                                     max_opposing_contact_n=.2, lifted=True, seated=False,
                                     last_position_m=[.1, 0., .03], last_goal_distance_m=.1, terminal="timeout")


def test_first_pick_replay_rejects_a_jump(tmp_path):
    import hashlib
    import yaml
    from stacking_fixture import PROFILE
    from stacking_task_helpers import load_first_pick_replay

    scene = fixture(layers=1, case=CASE)
    profile = yaml.safe_load(PROFILE.read_text())
    home = [*scene["home_joints_rad"][1], 1.]
    trace = dict(schema="omx.sim-replay-targets/1", scenario=CASE, arm="arm_b",
                 target="ship-h1r1-l0", control_hz=30,
                 joints=[f"joint{i}" for i in range(1, 6)] + ["gripper_joint_1"],
                 target_rad=[home, home.copy()])
    path = tmp_path / "trace.json"
    path.write_text(json.dumps(trace), encoding="utf-8")
    samples, identity = load_first_pick_replay(path, scene, profile, scene["stack_plan"][0])
    assert samples.tolist() == trace["target_rad"]
    assert identity == hashlib.sha256(path.read_bytes()).hexdigest()
    trace["target_rad"][1][0] += .1
    path.write_text(json.dumps(trace), encoding="utf-8")
    with pytest.raises(ValueError, match="simulation profile limits"):
        load_first_pick_replay(path, scene, profile, scene["stack_plan"][0])
