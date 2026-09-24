"""The Gazebo motion tool must hash the absorbed package, not an old checkout."""

import importlib.util
from pathlib import Path
from unittest.mock import patch

import pytest


PACKAGE = Path(__file__).resolve().parents[1]
TOOL = PACKAGE / "tools" / "gz" / "measure_motion_contract.py"


def _load_tool():
    spec = importlib.util.spec_from_file_location("measure_motion_contract", TOOL)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_motion_tool_defaults_to_the_absorbed_control_package():
    module = _load_tool()
    with patch.dict("os.environ", {}, clear=False):
        module.os.environ.pop("ROSY_SOURCE_ROOT", None)
        assert module._source_root() == PACKAGE.resolve()


def test_motion_tool_accepts_an_explicit_source_root(tmp_path):
    module = _load_tool()
    source_root = tmp_path / "control"
    source_root.mkdir()
    (source_root / "package.xml").touch()
    (source_root / "control").mkdir()
    with patch.dict("os.environ", {"ROSY_SOURCE_ROOT": str(source_root)}):
        assert module._source_root() == source_root.resolve()


def test_motion_tool_rejects_a_missing_source_root(tmp_path):
    module = _load_tool()
    with patch.dict("os.environ", {"ROSY_SOURCE_ROOT": str(tmp_path / "missing")}):
        with pytest.raises(RuntimeError, match="ROSY_SOURCE_ROOT"):
            module._source_root()


def test_motion_tool_has_no_retired_checkout_reference():
    retired_checkout = "pinky-" + "navigation-fix"
    assert retired_checkout not in TOOL.read_text(encoding="utf-8")
