"""Resolve the same approved geometry from source, wheel or an ament installation."""
from pathlib import Path
import builtins
import sys
from types import ModuleType

import pytest

from omx_adapter import kinematics


def test_default_load_uses_installed_prefix_geometry_when_source_is_absent(tmp_path, monkeypatch):
    original = kinematics.DEFAULT_KINEMATICS_PATH.read_bytes()
    expected = kinematics.OmxKinematics.load().revision
    installed = tmp_path / "share/omx_adapter/config/omx_f_kinematics.yaml"
    installed.parent.mkdir(parents=True)
    installed.write_bytes(original)
    monkeypatch.setattr(kinematics, "DEFAULT_KINEMATICS_PATH", tmp_path / "missing/source.yaml")
    monkeypatch.setattr(sys, "prefix", str(tmp_path))
    opened = []
    def record_open(path, *args, **kwargs):
        opened.append(Path(path))
        return builtins.open(path, *args, **kwargs)
    monkeypatch.setattr(kinematics, "open", record_open, raising=False)
    assert kinematics.OmxKinematics.load().revision == expected
    assert opened == [installed]


def test_default_load_uses_ament_share_outside_python_prefix(tmp_path, monkeypatch):
    original = kinematics.DEFAULT_KINEMATICS_PATH.read_bytes()
    expected = kinematics.OmxKinematics.load().revision
    share = tmp_path / "overlay/share/omx_adapter"
    (share / "config").mkdir(parents=True)
    (share / "config/omx_f_kinematics.yaml").write_bytes(original)
    monkeypatch.setattr(kinematics, "DEFAULT_KINEMATICS_PATH", tmp_path / "missing/source.yaml")
    monkeypatch.setattr(sys, "prefix", str(tmp_path / "other-python"))
    package = ModuleType("ament_index_python")
    packages = ModuleType("ament_index_python.packages")
    packages.PackageNotFoundError = type("PackageNotFoundError", (LookupError,), {})
    calls = []
    packages.get_package_share_directory = lambda name: calls.append(name) or str(share)
    monkeypatch.setitem(sys.modules, "ament_index_python", package)
    monkeypatch.setitem(sys.modules, "ament_index_python.packages", packages)
    assert kinematics.OmxKinematics.load().revision == expected
    assert calls == ["omx_adapter"]


def test_missing_geometry_refuses_without_inventing_defaults(tmp_path, monkeypatch):
    monkeypatch.setattr(kinematics, "DEFAULT_KINEMATICS_PATH", tmp_path / "missing/source.yaml")
    monkeypatch.setattr(sys, "prefix", str(tmp_path))
    monkeypatch.setitem(sys.modules, "ament_index_python", None)
    with pytest.raises(FileNotFoundError):
        kinematics.OmxKinematics.load()


def test_explicit_missing_path_does_not_fall_back_to_source(tmp_path):
    with pytest.raises(FileNotFoundError):
        kinematics.OmxKinematics.load(tmp_path / "explicit-missing.yaml")
