import importlib.util
import json
from pathlib import Path
import subprocess
import sys


def test_release_cli_exists():
    assert importlib.util.find_spec("cli") is not None


def test_runtime_up_refuses_unfinished_activation_before_docker(tmp_path, monkeypatch):
    from argparse import Namespace
    from bundle import BundleError
    from cli import execute
    from layout import Layout
    from release_runtime import DockerRuntime
    import pytest
    layout = Layout.rooted(tmp_path)
    layout.create_directories()
    layout.journal.write_text('{"phase":"activation-written"}')
    def forbidden(*args):
        raise AssertionError("unconfirmed runtime must not start")
    monkeypatch.setattr(DockerRuntime, "start", forbidden)
    with pytest.raises(BundleError, match="RECOVERY_REQUIRED"):
        execute(Namespace(root=str(tmp_path), command="runtime", action="up"))


def test_status_is_readable_before_device_enrollment(tmp_path):
    script = Path(__file__).resolve().parents[1] / "deploy/robot/pinky_pro/release/cli.py"
    result = subprocess.run([sys.executable, str(script), "--root", str(tmp_path), "status", "--json"],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["activation"] is None


def test_release_id_traversal_is_rejected_without_docker(tmp_path):
    script = Path(__file__).resolve().parents[1] / "deploy/robot/pinky_pro/release/cli.py"
    result = subprocess.run([sys.executable, str(script), "--root", str(tmp_path),
                             "install", "--release-id", "../escape", "--json"],
                            capture_output=True, text=True)
    assert result.returncode != 0
    assert json.loads(result.stdout)["code"] == "RELEASE_ID_INVALID"


def test_release_lock_refuses_an_overlapping_writer(tmp_path):
    from cli import release_lock
    from bundle import BundleError
    import pytest
    with release_lock(tmp_path / "lock"):
        with pytest.raises(BundleError, match="UPDATE_BUSY"):
            with release_lock(tmp_path / "lock"):
                raise AssertionError("a second writer must not enter")
