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
        target = Path(os.readlink(link))
        target = tmp_path / str(target).lstrip("/") if target.is_absolute() else link.parent / target
        assert target.resolve() == (directory / UNIT).resolve()
    text = (directory / UNIT).read_text(encoding="utf-8")
    before = {unit for line in text.splitlines() if line.startswith("Before=")
              for unit in line.partition("=")[2].split()}
    assert CONSUMERS <= before
    assert "DefaultDependencies=no" in text
    assert "After=local-fs.target" in text
    assert "After=rosy-first-boot" not in text
    assert "ProtectSystem=strict" in text and "PrivateDevices=true" in text
    assert "ProtectHome=true" not in text, "operator key mount must remain visible to admission"
    assert "/native-runtime/os_storage_dispatch.py" in text


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


def test_image_builder_checks_actual_vendor_units_before_mounted_image_acceptance():
    source = (NATIVE.parent / "image/customize-rootfs.sh").read_text(encoding="utf-8")
    command = 'chroot "$ROOT" /usr/bin/systemd-analyze --man=no verify'
    assert command in source
    block = source.split(command, 1)[1].split('python3 "$(dirname "$0")/verify-mounted-image.py"', 1)[0]
    for unit in CONSUMERS | {UNIT}:
        assert unit in block


@pytest.mark.parametrize("marked", [False, True])
def test_early_dispatcher_needs_no_payload_helpers_and_never_falls_back_for_ab(tmp_path, marked):
    runtime = tmp_path / "opt/rosy/native-runtime"
    runtime.mkdir(parents=True)
    shutil.copy2(NATIVE / "os_storage_dispatch.py", runtime / "os_storage_dispatch.py")
    root = tmp_path / "root"
    (root / "etc/rosy").mkdir(parents=True)
    if marked:
        (root / "etc/rosy/os-slot.json").write_text("{}", encoding="ascii")
    result = subprocess.run([sys.executable, "-I", "-B", str(runtime / "os_storage_dispatch.py"),
                             "--root", str(root)], cwd=tmp_path,
                            capture_output=True, text=True, check=False, timeout=30)
    report = json.loads(result.stdout)
    assert result.returncode == (1 if marked else 0), result.stderr
    assert report["phase"] == ("HOLD" if marked else "LEGACY")


def test_ab_dispatch_executes_the_os_copy_with_a_partial_native_runtime(tmp_path):
    prefix = tmp_path / "opt/rosy"
    runtime = prefix / "native-runtime"
    runtime.mkdir(parents=True)
    shutil.copy2(NATIVE / "os_storage_dispatch.py", runtime / "os_storage_dispatch.py")
    bootstrap = prefix / "os-bootstrap"
    bootstrap.mkdir()
    for name in ("os_state_storage.py", "os_state_firstboot.py", "os_state_layout.py", "first_boot_runtime.py", "os_state_accounts.py"):
        shutil.copy2(NATIVE / name, bootstrap / name)
        (runtime / name).write_text('raise RuntimeError("interrupted payload helper")\n', encoding="ascii")
    shutil.copytree(NATIVE.parent / "sd", prefix / "deploy/sd")
    root = tmp_path / "root"
    (root / "etc/rosy").mkdir(parents=True)
    (root / "etc/rosy/os-slot.json").write_text("{}", encoding="ascii")
    result = subprocess.run([sys.executable, "-I", "-B", str(runtime / "os_storage_dispatch.py"),
                             "--root", str(root)], cwd=tmp_path,
                            capture_output=True, text=True, check=False, timeout=30)
    assert result.returncode == 1
    assert json.loads(result.stdout)["phase"] == "HOLD"
    assert "interrupted payload helper" not in result.stderr


def test_payload_sync_refuses_the_os_bootstrap_directory():
    spec = importlib.util.spec_from_file_location("sync_for_storage", NATIVE / "sync-image-layer.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with pytest.raises(ValueError, match="IMAGE_LAYER_DESTINATION"):
        module.check_destination("opt/rosy/os-bootstrap/os_state_storage.py")
