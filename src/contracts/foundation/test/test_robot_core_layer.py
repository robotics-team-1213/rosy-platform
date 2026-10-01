"""D-196 robot package CORE layer: <robot package>/config/core.yaml in load_config.

A robot package that exists must ship the layer; a missing one would silently
drop robot facts such as the Pinky Pro LiDAR forward angle (D-344 §11).
"""

import logging

import pytest

from core_common import config as config_module
from core_common.config import ConfigError, load_config


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch, tmp_path):
    for name in ("ROSY_CONFIG", "ROSY_ROBOT", "ROSY_RUNTIME_MODE", "ROSY_NAMESPACE",
                 "ROSY_DEVICE_NAME", "ROSY_ROBOT_NUMBER", "ROSY_DEV_AUTH"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(config_module, "LOCAL_CONFIG_PATH", tmp_path / "absent.yaml")


@pytest.fixture
def robot_share(fake_ament, tmp_path):
    """A fake installed `robo` package; returns its config directory."""
    share = tmp_path / "share" / "robo"
    (share / "config").mkdir(parents=True)

    def get(name, not_found):
        if name == "robo":
            return str(share)
        raise not_found(name)

    fake_ament(get)
    return share / "config"


def test_existing_package_without_core_yaml_refuses_to_load(monkeypatch, robot_share):
    monkeypatch.setenv("ROSY_ROBOT", "robo")
    with pytest.raises(ConfigError) as caught:
        load_config()
    assert "robo" in str(caught.value) and str(robot_share / "core.yaml") in str(caught.value)


def test_unknown_model_warns_once_naming_model_and_path(monkeypatch, robot_share, caplog):
    monkeypatch.setenv("ROSY_ROBOT", "no_such_robot")
    with caplog.at_level(logging.WARNING, logger="core_common.config"):
        config = load_config()
    assert config["robot"]["model"] == "no_such_robot"
    warnings = [r for r in caplog.records if r.name == "core_common.config"]
    assert len(warnings) == 1
    message = warnings[0].getMessage()
    assert "no_such_robot" in message and "products" in message


@pytest.mark.parametrize("text, words", [
    ("line_follow:\n", "'line_follow' is empty"),
    ("line_follow: 180\n", "'line_follow' must be a mapping"),
    ("robot:\n  model: robo\nsafety: []\n", "'safety' must be a mapping"),
])
def test_layer_may_not_wipe_a_default_section(monkeypatch, robot_share, text, words):
    (robot_share / "core.yaml").write_text(text, encoding="utf-8")
    monkeypatch.setenv("ROSY_ROBOT", "robo")
    with pytest.raises(ConfigError) as caught:
        load_config()
    assert words in str(caught.value) and str(robot_share / "core.yaml") in str(caught.value)


def test_layer_values_merge_under_the_defaults(monkeypatch, robot_share):
    (robot_share / "core.yaml").write_text("line_follow:\n  lidar_forward_deg: 90.0\n", encoding="utf-8")
    monkeypatch.setenv("ROSY_ROBOT", "robo")
    line_follow = load_config()["line_follow"]
    assert line_follow["lidar_forward_deg"] == 90.0 and line_follow["obstacle_stop_m"] == 0.20


def test_pinky_pro_layer_is_shipped(no_ament_share):
    assert load_config()["line_follow"]["lidar_forward_deg"] == 180.0
