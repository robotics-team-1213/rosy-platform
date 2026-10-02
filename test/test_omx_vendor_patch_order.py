"""Every open_manipulator patch applies to the pinned vendor files in exact Dockerfile order.

2026-10-03: a rebuild failed because omx-ai-sim-gates.patch changed context that
omx-ai-sim-action-only.patch (applied later) depends on. Needs the network once per vendor
revision (files are cached); skips cleanly offline. Script: deploy/robot/omx/check_vendor_patches.py.
"""

from __future__ import annotations

import ast
import importlib.util
import os
import tempfile
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("omx_vendor_patches", ROOT / "deploy/robot/omx/check_vendor_patches.py")
patches = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(patches)
CACHE = Path(os.environ.get("ROSY_OMX_VENDOR_CACHE", Path(tempfile.gettempdir()) / "rosy-omx-vendor-cache"))


def test_patch_order_is_read_from_the_dockerfile():
    names = [path.name for path in patches.dockerfile_patch_order()]
    assert names == ["omx-f-gazebo-headless.patch", "omx-ai-sim-gates.patch",
                     "omx-ai-sim-action-only.patch", "omx-ai-native-action-only.patch"]
    assert patches.vendor_revision() == "0a4af6a923b8b7d80b8c20506d1839c54d2e993e"


def test_every_patch_applies_in_dockerfile_order_and_results_parse(tmp_path):
    try:
        errors, work = patches.check(CACHE, tmp_path / "work")
    except patches.FetchError as exc:
        pytest.skip(f"pinned vendor files unavailable offline: {exc}")
    assert errors == []
    launch = (work / "open_manipulator_bringup/launch/omx_f_follower_ai_gazebo.launch.py").read_text(encoding="utf-8")
    tree = ast.parse(launch)
    spawner_args = [node for node in ast.walk(tree) if isinstance(node, ast.keyword) and node.arg == "arguments"]
    rendered = [ast.unparse(node.value) for node in spawner_args]
    arm = next(text for text in rendered if "'arm_controller'" in text)
    # action-only removed the leader remap; gates added the Gazebo-only constraints file.
    assert "joint_trajectory" not in arm and "'--param-file'" in arm
    assert "gazebo_arm_controller_constraints.yaml" in arm
    constraints = yaml.safe_load((work / "open_manipulator_bringup/config/omx_f_follower_ai/"
                                  "gazebo_arm_controller_constraints.yaml").read_text(encoding="utf-8"))
    assert constraints["arm_controller"]["ros__parameters"]["constraints"]["goal_time"] == 1.0
    native = (work / "open_manipulator_bringup/launch/omx_f_follower_ai.launch.py").read_text(encoding="utf-8")
    assert "gazebo_arm_controller_constraints" not in native and "/leader/joint_trajectory" not in native
