"""D-232: the OMX product package is the disabled arm settings, not adapter code."""

from pathlib import Path

import yaml

CONFIG = Path(__file__).resolve().parents[1] / "config"


def test_the_shipped_target_is_omx_ai_but_arm_remains_disabled():
    document = yaml.safe_load((CONFIG / "omx.disabled.yaml").read_text(encoding="utf-8"))
    arm = document["omx"]
    assert arm["enabled"] is False
    assert arm["model"] == "omx_ai"
    assert arm["driver_package"] == ""
    assert arm["hardware_plugin"] == ""
    assert arm["joint_names"] == []
