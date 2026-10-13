"""D-196: a robot package carries the profile and capabilities CORE loads for it."""

from pathlib import Path

import yaml

CONFIG = Path(__file__).resolve().parents[1] / "config"


def test_profile_names_the_model_and_base_limits():
    profile = yaml.safe_load((CONFIG / "profile.yaml").read_text(encoding="utf-8"))["profile"]
    assert profile["model"] == "Pinky Pro"
    assert profile["max_linear_velocity"] > 0
    assert profile["max_angular_velocity"] > 0


def test_capabilities_match_the_profile_limits():
    """HWA-003: advertised navigation limits are the profile's."""
    profile = yaml.safe_load((CONFIG / "profile.yaml").read_text(encoding="utf-8"))["profile"]
    caps = yaml.safe_load((CONFIG / "capabilities.yaml").read_text(encoding="utf-8"))
    assert caps["capability_version"] == 1
    assert caps["navigation"]["max_linear_velocity"] == profile["max_linear_velocity"]
    assert caps["navigation"]["max_angular_velocity"] == profile["max_angular_velocity"]
    assert caps["docking"]["supported"] is False
