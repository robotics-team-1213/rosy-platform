"""RaspTank source preparation must not advertise unverified physical controls."""

from pathlib import Path
import sys

import pytest
import yaml

from core_common import config as config_module
from core_common.capability import Capability, CapabilityError
from core_common.config import load_config
from core_common.domain.capabilities import descriptors_from_cap001
from core_common.domain.tasks import TaskKind
from core_common.profile import RobotProfile, robot_config_dir


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "middleware/devices/rasptank/profile/config"


@pytest.fixture(autouse=True)
def source_without_operator_overlays(monkeypatch, tmp_path):
    for name in ("ROSY_CONFIG", "ROSY_ROBOT", "ROSY_RUNTIME_MODE", "ROSY_NAMESPACE",
                 "ROSY_DEVICE_NAME", "ROSY_DEVICE_UID", "ROSY_ROBOT_NUMBER", "ROSY_DEV_AUTH"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setitem(sys.modules, "ament_index_python.packages", None)
    monkeypatch.setattr(config_module, "LOCAL_CONFIG_PATH", tmp_path / "absent.yaml")


def capability():
    return Capability(yaml.safe_load((CONFIG / "capabilities.yaml").read_text(encoding="utf-8")))


def test_source_model_resolves_to_its_own_configuration():
    assert robot_config_dir("rasptank_metal") == CONFIG
    profile = RobotProfile.load(CONFIG / "profile.yaml")
    assert profile.model == "RaspTank Metal"
    assert profile.max_linear_velocity == 0.0
    assert profile.max_angular_velocity == 0.0


def test_rosy_robot_selects_the_required_core_layer(monkeypatch):
    monkeypatch.setenv("ROSY_ROBOT", "rasptank_metal")
    config = load_config(fleet_link=False)
    assert config["robot"]["model"] == "rasptank_metal"
    assert yaml.safe_load((CONFIG / "core.yaml").read_text(encoding="utf-8")) == {}


@pytest.mark.parametrize("task", list(TaskKind))
def test_every_physical_task_is_rejected(task):
    with pytest.raises(CapabilityError) as caught:
        task.require(capability())
    assert caught.value.feature == task.capability
    assert caught.value.concept_id == task.concept_id


def test_unverified_geometry_sensors_and_controls_are_not_claimed():
    profile = yaml.safe_load((CONFIG / "profile.yaml").read_text(encoding="utf-8"))["profile"]
    caps = capability()
    assert profile["wheel_base"] is None
    assert profile["sensors"] == caps.to_dict()["sensors"] == []
    for limit in ("max_linear_velocity", "max_angular_velocity"):
        assert profile[limit] == caps.to_dict()["navigation"][limit] == 0.0
    for flag in ("teleop", "slam", "navigation.goal_navigation", "navigation.return_home",
                 "swarm.follow", "swarm.lead", "docking.supported"):
        assert caps.supports(flag) is False
    assert descriptors_from_cap001(caps.to_dict()) == ()
