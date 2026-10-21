"""Host data defaults can leave the source checkout without losing confinement."""

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _run_data():
    spec = importlib.util.spec_from_file_location("external_run_data", ROOT / "tools/run_data.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_existing_default_is_preserved(monkeypatch, tmp_path):
    monkeypatch.delenv("ROSY_DATA_ROOT", raising=False)
    assert _run_data().data_root(tmp_path) == tmp_path / "data"


def test_external_root_creates_and_reads_only_external_sessions(monkeypatch, tmp_path):
    external = tmp_path / "external"
    monkeypatch.setenv("ROSY_DATA_ROOT", str(external))
    module = _run_data()
    session = module.create_session(tmp_path / "source", "teleop", "capture")
    assert session.parent == external / "teleop"
    assert module.list_sessions(tmp_path / "source", "teleop") == [session]
    assert not (tmp_path / "source/data").exists()


@pytest.mark.parametrize("value", ["", " ", "relative/data"])
def test_invalid_external_root_refuses_without_writing(monkeypatch, tmp_path, value):
    monkeypatch.setenv("ROSY_DATA_ROOT", value)
    with pytest.raises(ValueError, match="absolute"):
        _run_data().create_session(tmp_path, "drive", "capture")
    assert not (tmp_path / "data").exists()


def test_session_kind_cannot_follow_link_outside_data_root(monkeypatch, tmp_path):
    external, outside = tmp_path / "external", tmp_path / "outside"
    external.mkdir()
    outside.mkdir()
    (external / "teleop").symlink_to(outside, target_is_directory=True)
    monkeypatch.setenv("ROSY_DATA_ROOT", str(external))
    with pytest.raises(ValueError, match="leaves"):
        _run_data().create_session(tmp_path, "teleop", "capture")
    assert list(outside.iterdir()) == []


def test_curation_defaults_share_external_root_in_fresh_process(tmp_path):
    env = dict(os.environ, ROSY_DATA_ROOT=str(tmp_path))
    paths = [ROOT / p for p in ["tools", "learning/curation/perception", "middleware/perception", "contracts/foundation"]]
    script = (
        "import sys,json;sys.path[:0]=" + repr(list(map(str, paths))) + ";"
        "import autolabel,bag_to_video,geometry,reclaim,fetch_http,map_projected_drivable;"
        "print(json.dumps([str(p) for p in [autolabel.DATA,bag_to_video.DEFAULT_OUT,"
        "geometry.CALIBRATION_STORE,reclaim.DEFAULT_ROOT,reclaim.DEFAULT_VIDEO,"
        "fetch_http.DEFAULT_DEST,map_projected_drivable.CACHE]]))"
    )
    result = subprocess.run([sys.executable, "-c", script], env=env, capture_output=True, text=True, check=True)
    assert json.loads(result.stdout) == [str(tmp_path / p) for p in [
        "perception", "teleop/learning", "calibration", "perception", "teleop/learning",
        "perception/raw", "perception/cache",
    ]]


def test_catalog_explicit_root_overrides_environment(tmp_path):
    env_root, chosen = tmp_path / "env", tmp_path / "chosen"
    chosen.mkdir()
    result = subprocess.run(
        [sys.executable, str(ROOT / "learning/curation/perception/catalog.py"), "--root", str(chosen), "scan"],
        env=dict(os.environ, ROSY_DATA_ROOT=str(env_root)), capture_output=True, text=True, check=True,
    )
    assert (chosen / "catalog.jsonl").is_file()
    assert not env_root.exists()


def test_legacy_session_suite_isolates_inherited_operator_root(tmp_path):
    external = tmp_path / "operator-data"
    result = subprocess.run([
        sys.executable, "-m", "pytest", str(ROOT / "test/test_run_data.py"),
        "-q", "--noconftest", "-o", "addopts=", "-p", "no:cacheprovider",
        "-p", "no:launch_testing", "-p", "no:launch_ros",
    ], env=dict(os.environ, ROSY_DATA_ROOT=str(external)), capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert not external.exists()
