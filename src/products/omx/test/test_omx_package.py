"""D-232: the OMX product package is the disabled arm settings, not adapter code."""

from pathlib import Path

import yaml

CONFIG = Path(__file__).resolve().parents[1] / "config"


def test_the_shipped_arm_is_disabled_until_it_is_measured():
    document = yaml.safe_load((CONFIG / "omx.disabled.yaml").read_text(encoding="utf-8"))
    arm = document["omx"]
    assert arm["enabled"] is False
    assert arm["model"] == ""
    assert arm["driver_package"] == ""
    assert arm["hardware_plugin"] == ""
    assert len(arm["joint_names"]) >= 4
