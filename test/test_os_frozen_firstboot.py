"""A/B personalization must not import a half-installed application runtime."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

BASE = Path(__file__).resolve().parents[1] / "deploy/robot/pinky_pro"


def _dispatch():
    spec = importlib.util.spec_from_file_location("frozen_firstboot_dispatch", BASE / "native/os_storage_dispatch.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _prefix(tmp_path):
    prefix = tmp_path / "opt/rosy"
    prefix.mkdir(parents=True)
    result = subprocess.run(["bash", str(BASE / "native/install-native-runtime.sh"),
                             str(prefix / "native-runtime")], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    shutil.copytree(BASE / "image/first-boot", prefix / "first-boot")
    shutil.copytree(BASE / "sd", prefix / "deploy/sd")
    return prefix


def _stage(prefix):
    result = subprocess.run([sys.executable, "-I", "-B", str(BASE / "image/stage-os-firstboot.py"),
                             "--prefix", str(prefix)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr


def test_frozen_firstboot_imports_without_mutable_native_or_sd_sdk(tmp_path):
    prefix = _prefix(tmp_path)
    _stage(prefix)
    for folder in (prefix / "native-runtime", prefix / "deploy/sd"):
        for path in folder.glob("*.py"):
            path.write_text('raise RuntimeError("partial application runtime")\n')
    script = prefix / "os-bootstrap/first-boot/rosy-first-boot.py"
    result = subprocess.run([sys.executable, "-I", "-B", str(script), "--help"],
                            cwd=tmp_path, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert "--hardware-serial" in result.stdout


@pytest.mark.parametrize("change", ["missing", "symlink", "writable", "directory_link"])
def test_frozen_entry_rejects_partial_or_replaceable_boot_support(tmp_path, change):
    prefix = _prefix(tmp_path)
    _stage(prefix)
    helper = prefix / "os-bootstrap/native-runtime/first_boot_runtime.py"
    if change == "missing":
        helper.unlink()
    elif change == "symlink":
        helper.unlink()
        helper.symlink_to(prefix / "native-runtime/first_boot_runtime.py")
    elif change == "writable":
        helper.chmod(0o666)
    else:
        directory = helper.parent
        destination = prefix / "moved-runtime"
        directory.rename(destination)
        directory.symlink_to(destination, target_is_directory=True)
    module = _dispatch()
    module.__file__ = str(prefix / "native-runtime/os_storage_dispatch.py")
    with pytest.raises((ValueError, OSError)):
        module.first_boot_entry()


def test_frozen_launcher_uses_own_root_and_keeps_the_firstboot_serial_lock(tmp_path):
    prefix = _prefix(tmp_path)
    _stage(prefix)
    module = _dispatch()
    module.__file__ = str(prefix / "native-runtime/os_storage_dispatch.py")
    entry = module.first_boot_entry()
    assert entry == prefix / "os-bootstrap/first-boot/rosy-first-boot.sh"
    assert os.access(entry, os.X_OK)
    text = entry.read_text()
    assert "flock -w 200 /run/rosy-first-boot.lock" in text
    assert '"$SCRIPT_DIR/rosy-first-boot.py"' in text


def test_firstboot_dispatch_cannot_run_without_ab_identity(tmp_path):
    prefix = _prefix(tmp_path)
    _stage(prefix)
    root = tmp_path / "device"
    root.mkdir()
    result = subprocess.run([sys.executable, "-I", "-B", str(prefix / "native-runtime/os_storage_dispatch.py"),
                             "--root", str(root), "--first-boot"], cwd=tmp_path,
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 1, result.stderr
    assert json.loads(result.stdout)["phase"] == "HOLD"
