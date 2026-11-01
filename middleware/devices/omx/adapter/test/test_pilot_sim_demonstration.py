"""The shipped demonstration profile fits what Pilot offers; a pose Pilot cannot reach fails at start-up."""
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from core_common.protocol.omx_sim import OmxSimTarget
from omx_adapter.pilot_sim.runtime import PilotSimRuntime, sim_admission_limits, urdf_position_limits
from omx_adapter.pose_plan import CellPlanningProfile

ROOT = Path(__file__).resolve().parents[5]
SIM = ROOT / "deploy/robot/omx/sim"


def runtime():
    cell = CellPlanningProfile.load(SIM / "cell_profile.yaml")
    config = SimpleNamespace(allowed_owners=("pilot_sim",), instance_id="omx_pilot_sim_01",
                             joint_names=cell.joint_names,
                             position_limits=sim_admission_limits(cell.position_limits, urdf_position_limits()))
    return PilotSimRuntime(SimpleNamespace(owner=SimpleNamespace(config=config)), gripper=cell.gripper_joint,
                           range_inset_rad=cell.start_state_tolerance_rad, gripper_open=cell.gripper_open,
                           gripper_closed=cell.gripper_closed, gripper_velocity=0.5,
                           gripper_preload=cell.gripper_preload_rad)


def shipped():
    return yaml.safe_load((SIM / "pilot_demonstration.yaml").read_text(encoding="utf-8"))


def test_shipped_profile_gives_every_arm_joint_and_reaches_the_target_contract():
    sim = runtime()
    sim.load_demonstration(shipped())
    arm = tuple(name for name in sim.joint_names if name != sim.gripper)
    assert set(sim.start_pose) == set(arm) and 1 <= len(sim.task) <= 300
    target = OmxSimTarget(instance_id=sim.instance_id, joints=arm, gripper=sim.gripper,
                          start_pose=sim.start_pose, task=sim.task)
    assert target.model_dump()["start_pose"]["joint2"] == -1.57
    server = (ROOT / "middleware/devices/omx/adapter/omx_adapter/pilot_sim/server.py").read_text(encoding="utf-8")
    assert "facade.load_demonstration(" in server and "source_hasher.update(demonstration_path.read_bytes())" in server


@pytest.mark.parametrize("change, message", [
    ({"schema": "rosy.omx-collection-profile.v1"}, "schema"),
    ({"start_pose": {"gripper_joint_1": 0.5}}, "does not jog"),
    ({"start_pose": {"joint9": 0.0}}, "does not jog"),
    ({"start_pose": {"joint2": 1.19}}, "outside"),   # admission ends at 1.2, Pilot is offered 1.18
    ({"start_pose": {"joint2": float("nan")}}, "outside"),
    ({"task": ""}, "1-300"),
    ({"task": "x" * 301}, "1-300"),
])
def test_a_pose_pilot_cannot_reach_or_a_bad_task_is_refused(change, message):
    sim = runtime()
    with pytest.raises(ValueError, match=message):
        sim.load_demonstration({**shipped(), **change})
    assert sim.start_pose is None and sim.task is None


def test_no_demonstration_defaults_keep_the_older_target():
    sim = runtime()
    sim.load_demonstration({"schema": "rosy.omx-sim-demonstration.v1"})
    assert sim.start_pose is None and sim.task is None
