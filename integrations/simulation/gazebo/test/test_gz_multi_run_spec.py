"""gz_multi run_spec — D-426 T1 runner 소유 spec 계약.

런치 파일은 모듈이 아니라 경로로 import 한다. `launch` 가 없는 환경(Windows)은 skip.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

launch = pytest.importorskip("launch")
if not hasattr(launch, "LaunchContext"):
    pytest.skip("`launch` resolved to this package's launch/ directory, not ROS 2 launch",
                allow_module_level=True)

LAUNCH = Path(__file__).resolve().parents[1] / "launch" / "gz_multi.launch.py"


def _module():
    spec = importlib.util.spec_from_file_location("gz_multi_launch", LAUNCH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_empty_run_spec_keeps_legacy_behavior():
    assert _module()._load_run_spec("") == {}
    assert _module()._load_run_spec("   ") == {}


def test_run_spec_with_missing_fields_fails_loudly(tmp_path):
    path = tmp_path / "run_spec.yaml"
    path.write_text("run_id: r1\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="core_config_dir"):
        _module()._load_run_spec(str(path))


def test_run_spec_requires_a_core_overlay_per_robot(tmp_path):
    mod = _module()
    spec = {"run_id": "r1", "core_config_dir": str(tmp_path),
            "fleet_manifest": str(tmp_path / "robots.yaml"),
            "hub_url": "http://127.0.0.1:32010", "gz_partition": "d426-r1"}
    with pytest.raises(RuntimeError, match="rosy_01"):
        mod._run_spec_overlay(spec, "rosy_01")
    (tmp_path / "core_rosy_01.yaml").write_text("robot: {id: rosy_01}\n", encoding="utf-8")
    assert mod._run_spec_overlay(spec, "rosy_01").endswith("core_rosy_01.yaml")
