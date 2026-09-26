"""D-196: CORE finds the robot's profile in the robot package named by robot.model."""

from pathlib import Path

import pytest

from core_common import config as config_module
from core_common.config import ConfigError, load_config
from core_common.profile import DEFAULT_ROBOT, robot_config_dir

SRC = Path(__file__).resolve().parents[3]


@pytest.fixture(autouse=True)
def _no_operator_overlay(monkeypatch):
    for name in ("ROSY_CONFIG", "ROSY_ROBOT", "ROSY_RUNTIME_MODE", "ROSY_NAMESPACE", "ROSY_DEVICE_NAME"):
        monkeypatch.delenv(name, raising=False)


def test_robot_config_dir_falls_back_to_the_source_tree(no_ament_share):
    assert robot_config_dir("pinky_pro") == SRC / "products" / "pinky_pro" / "config"


def test_default_robot_is_pinky_pro():
    assert DEFAULT_ROBOT == "pinky_pro"


def test_default_config_names_the_robot_model(monkeypatch, tmp_path):
    monkeypatch.setattr(config_module, "LOCAL_CONFIG_PATH", tmp_path / "absent.yaml")
    assert load_config()["robot"]["model"] == "pinky_pro"


def test_rosy_robot_env_selects_the_model(monkeypatch, tmp_path):
    monkeypatch.setenv("ROSY_ROBOT", "omx_desk")
    monkeypatch.setattr(config_module, "LOCAL_CONFIG_PATH", tmp_path / "absent.yaml")
    assert load_config()["robot"]["model"] == "omx_desk"


@pytest.mark.parametrize("bad", ["Pinky", "../etc", "pinky pro", "1robot"])
def test_rosy_robot_env_must_be_a_package_name(monkeypatch, tmp_path, bad):
    monkeypatch.setenv("ROSY_ROBOT", bad)
    monkeypatch.setattr(config_module, "LOCAL_CONFIG_PATH", tmp_path / "absent.yaml")
    with pytest.raises(ConfigError):
        load_config()


def test_existing_robot_package_resolves_to_its_source_config(no_ament_share):
    assert robot_config_dir("pinky_pro") == SRC / "products" / "pinky_pro" / "config"


def test_unknown_robot_names_the_package_and_how_to_fix_it(no_ament_share):
    with pytest.raises(ConfigError) as caught:
        robot_config_dir("no_such_robot")
    message = str(caught.value)
    for part in ("no_such_robot", "robot.model", "ROSY_ROBOT", "--packages-up-to core no_such_robot"):
        assert part in message, part


def test_unsourced_ament_falls_back_to_the_source_tree(fake_ament):
    """ament importable but AMENT_PREFIX_PATH unset: its lookup raises OSError."""

    def unset(name, not_found):
        raise OSError("AMENT_PREFIX_PATH unset")

    fake_ament(unset)
    assert robot_config_dir("pinky_pro") == SRC / "products" / "pinky_pro" / "config"


def test_package_not_found_falls_back_to_the_source_tree(no_ament_share):
    assert robot_config_dir("pinky_pro") == SRC / "products" / "pinky_pro" / "config"


def test_installed_share_wins_over_the_source_tree(fake_ament, tmp_path):
    fake_ament(lambda name, not_found: str(tmp_path / "share" / name))
    assert robot_config_dir("pinky_pro") == tmp_path / "share" / "pinky_pro" / "config"
