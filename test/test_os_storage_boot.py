"""Read-only storage admission and real offline systemctl dependency installation."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from os_state_boot_fakes import shared_roots
from test_os_first_boot_state import _provision_a

NATIVE = Path(__file__).resolve().parents[1] / "deploy/robot/pinky_pro/native"
UNIT = "rosy-os-storage.service"
CONSUMERS = {"NetworkManager.service", "ssh.service", "ssh.socket", "tailscaled.service",
             "rosy-ssh-access-boot.service", "rosy-first-boot.service", "rosy-first-boot-retry.service"}


def _module():
    spec = importlib.util.spec_from_file_location("rosy_os_storage", NATIVE / "os_state_storage.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_factory_storage_admission_does_not_write_identity_or_state(tmp_path, monkeypatch):
    root, _, common, _ = shared_roots(tmp_path, monkeypatch)
    before = {p.relative_to(common): p.read_bytes() for p in common.rglob("*") if p.is_file()}
    report = _module().admit_storage(root)
    assert report == {"schema_version": 1, "phase": "FACTORY_EMPTY", "slot": "a"}
    assert before == {p.relative_to(common): p.read_bytes() for p in common.rglob("*") if p.is_file()}
    assert not (root / "etc/rosy/device-identity.json").exists()


def test_storage_admission_checks_committed_b_without_projecting_before_network(tmp_path, monkeypatch):
    _, _, root_b, _, _ = _provision_a(tmp_path, monkeypatch)
    report = _module().admit_storage(root_b)
    assert report == {"schema_version": 1, "phase": "COMMITTED", "slot": "b"}
    assert not (root_b / "etc/rosy/device-identity.json").exists()
    assert not (root_b / "run/rosy-os-state/ready.json").exists()


def test_storage_admission_refuses_corrupt_common_state(tmp_path, monkeypatch):
    root, _, common, _ = shared_roots(tmp_path, monkeypatch)
    (common / "state/factory.json").unlink()
    with pytest.raises(ValueError, match="OS_STATE_HOLD"):
        _module().admit_storage(root)


def test_storage_admission_keeps_legacy_roots_explicit(tmp_path):
    assert _module().admit_storage(tmp_path) == {"schema_version": 1, "phase": "LEGACY"}


def test_offline_enable_creates_required_edges_for_network_and_ssh_sockets(tmp_path):
    directory = tmp_path / "etc/systemd/system"
    directory.mkdir(parents=True)
    shutil.copy2(NATIVE / UNIT, directory / UNIT)
    result = subprocess.run(["systemctl", "--root", str(tmp_path), "enable", UNIT],
                            capture_output=True, text=True, check=False, timeout=15)
    assert result.returncode == 0, result.stderr
    for consumer in CONSUMERS:
        link = directory / (consumer + ".requires") / UNIT
        assert link.is_symlink(), f"{consumer} must require storage validation"
        assert link.resolve() == (directory / UNIT).resolve()
    text = (directory / UNIT).read_text(encoding="utf-8")
    before = {unit for line in text.splitlines() if line.startswith("Before=")
              for unit in line.partition("=")[2].split()}
    assert CONSUMERS <= before
    assert "DefaultDependencies=no" in text
    assert "After=local-fs.target" in text
    assert "After=rosy-first-boot" not in text
    assert "ProtectSystem=strict" in text and "PrivateDevices=true" in text
    assert "ProtectHome=true" not in text, "operator key mount must remain visible to admission"


def test_storage_entrypoint_imports_from_the_staged_image_in_isolation(tmp_path):
    prefix = tmp_path / "opt/rosy"
    shutil.copytree(NATIVE, prefix / "native-runtime")
    shutil.copytree(NATIVE.parent / "sd", prefix / "deploy/sd")
    root = tmp_path / "legacy-root"
    root.mkdir()
    result = subprocess.run([sys.executable, "-I", "-B", str(prefix / "native-runtime/os_state_storage.py"),
                             "--root", str(root)], cwd=tmp_path, env=dict(os.environ),
                            capture_output=True, text=True, check=False, timeout=30)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"schema_version": 1, "phase": "LEGACY"}
