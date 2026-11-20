"""The PPO fixture and MuJoCo handoff must agree on the same physical layout."""

from pathlib import Path
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

    handoff = isaac_handoff(dict(task="stack", steps=9, completed=True), layout, seed=42)["stage_2_isaac"]
    assert handoff["two_arm_scenario"] == "omx-map-container-stacking-rl"
    assert handoff["two_arm_config"] == request_for(layout, 42, 3)
    assert handoff["ready"]
    report = dict(schema="rosy.omx-stacking-rl/1", training_verified=True, task_success=False,
                  evaluation_successes=0, fixture={"case": CASE})
    assert judge_isaac_stage(report)["status"] == "failed"
    assert judge_isaac_stage(report)["result"]["training_verified"]
