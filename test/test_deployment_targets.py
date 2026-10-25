"""Deployment selection delegates only supported operations to fixed executors."""

import importlib
import json
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def targets():
    return importlib.import_module("tools.release.deployment_targets")


def test_inventory_separates_native_and_sdk_host(targets):
    inventory = targets.load_targets()
    assert inventory["pinky_pro"]["deployment"] == "native"
    assert inventory["rasptank_metal"]["operations"] == []
    assert inventory["dji_neo_2"]["deployment"] == "sdk-host"
    assert inventory["dji_neo_2"]["status"] == "sdk_unsupported"


def test_pinky_plan_does_not_execute(targets):
    result = targets.dispatch("pinky_pro", "apply", "robot.example", tarball="release.tar.gz",
                              public_key="release.pem", runner=lambda *a, **k: pytest.fail("executed a plan"))
    assert result["executed"] is False
    command = result["command"]
    assert str(ROOT / "deploy/robot/pinky_pro/rosy-release-push.ps1") in command
    assert command[command.index("-Tarball") + 1] == "release.tar.gz"
    assert "-Force" not in command


@pytest.mark.parametrize("operation", ["apply", "rollback"])
def test_pinky_dispatch_uses_real_plan_and_propagates_failure(targets, operation):
    calls = []

    def runner(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 7)

    result = targets.dispatch("pinky_pro", operation, "robot.example",
                              tarball="release.tar.gz" if operation == "apply" else None,
                              public_key="release.pem", execute=True, runner=runner)
    assert result["returncode"] == 7
    assert result["executed"] is True
    assert len(calls) == 1
    assert calls[0][0] == result["command"]
    assert not calls[0][1].get("shell", False)
    assert ("-Rollback" in result["command"]) is (operation == "rollback")


@pytest.mark.parametrize("target", ["rasptank_metal", "dji_neo_2", "unknown", "../pinky_pro"])
def test_blocked_target_never_reaches_executor(targets, target):
    with pytest.raises(targets.DeploymentError):
        targets.dispatch(target, "apply", "robot.example", tarball="release.tar.gz",
                         public_key="release.pem", execute=True,
                         runner=lambda *a, **k: pytest.fail("executed rejected target"))


@pytest.mark.parametrize("host", ["-oProxyCommand=bad", "robot;whoami", "robot\nother"])
def test_host_is_not_a_shell_or_option(targets, host):
    with pytest.raises(targets.DeploymentError):
        targets.dispatch("pinky_pro", "rollback", host)


def test_descriptor_cannot_select_a_program(targets, tmp_path):
    path = tmp_path / "deploy/robot/pinky_pro/deployment-target.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"id": "pinky_pro", "executor": "arbitrary.exe"}), encoding="utf-8")
    with pytest.raises(targets.DeploymentError):
        targets.load_targets(tmp_path)


def test_metadata_cannot_unlock_unimplemented_executor(targets, tmp_path):
    data = dict(targets.load_targets()["rasptank_metal"])
    data.update(status="existing_implementation", operations=["apply"])
    path = tmp_path / "deploy/robot/rasptank_metal/deployment-target.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(targets.DeploymentError, match="executor"):
        targets.load_targets(tmp_path)


def test_duplicate_target_id_is_rejected(targets, tmp_path):
    data = targets.load_targets()["pinky_pro"]
    for parent in ("deploy/robot/pinky_pro", "deploy/hosts/sdk/pinky_pro"):
        path = tmp_path / parent / "deployment-target.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(targets.DeploymentError, match="duplicated"):
        targets.load_targets(tmp_path)


def test_deploy_cli_lists_and_refuses_without_network():
    entry = ROOT / "tools/release/deploy_cli.py"
    listed = subprocess.run([sys.executable, str(entry), "list"], capture_output=True, text=True)
    assert listed.returncode == 0, listed.stderr
    assert "dji_neo_2" in {row["id"] for row in json.loads(listed.stdout)}
    refused = subprocess.run([sys.executable, str(entry), "apply", "--target", "dji_neo_2",
                              "--robot", "robot.example", "--tarball", "release.tar.gz",
                              "--public-key", "release.pem"], capture_output=True, text=True)
    assert refused.returncode == 3
    assert "error" in json.loads(refused.stderr)
