"""The native runtime must run from where the image installs it, not from the repo.

D-173 F1: release recovery imported ``signing`` through a repo-relative path
(``parents[2] / "release"``). Every repo test passed; on the first Pinky boot
``/opt/rosy/native-runtime/native_release.py`` failed with ``No module named
'signing'`` and CORE never started. These tests install the runtime with the
same installer the image build uses, into a tree that has no repository around
it, and execute the entrypoints there.
"""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "deploy" / "robot" / "native" / "install-native-runtime.sh"
PAYLOAD_BUILDER = ROOT / "deploy" / "image" / "build-native-payload.sh"
BASH = shutil.which("bash")


def _install(destination: Path) -> None:
    completed = subprocess.run(
        [BASH, INSTALLER.as_posix(), destination.as_posix()],
        capture_output=True, text=True, cwd=ROOT,
    )
    assert completed.returncode == 0, completed.stderr


def _isolated_env() -> dict[str, str]:
    env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
    env["PYTHONNOUSERSITE"] = "1"
    return env


def _run_recover(runtime: Path, device_root: Path) -> subprocess.CompletedProcess[str]:
    public_key = device_root / "etc/rosy/trusted-release-keys/rosy-release-2026-01.pem"
    public_key.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / "deploy/release/public-keys/rosy-release-2026-01.pem", public_key)
    return subprocess.run(
        [sys.executable, str(runtime / "native_release.py"),
         "--root", str(device_root), "--public-key", str(public_key), "recover"],
        capture_output=True, text=True, cwd=device_root, env=_isolated_env(),
    )


@pytest.mark.skipif(BASH is None, reason="bash is required to run the installer")
@pytest.mark.parametrize(
    "relative",
    ["opt/rosy/native-runtime", "opt/rosy/releases/2026.09.22-003/deploy/robot/native"],
)
def test_release_recovery_runs_from_each_installed_copy(tmp_path, relative):
    device_root = tmp_path / "device"
    runtime = device_root / relative
    _install(runtime)

    completed = _run_recover(runtime, device_root)

    assert "No module named" not in completed.stderr, completed.stderr
    assert completed.returncode == 0, completed.stderr
    assert '"ok": true' in completed.stdout


@pytest.mark.skipif(BASH is None, reason="bash is required to run the installer")
def test_installed_runtime_does_not_reach_back_into_a_repository(tmp_path):
    runtime = tmp_path / "device/opt/rosy/native-runtime"
    _install(runtime)

    assert (runtime / "signing.py").is_file()
    assert not (tmp_path / "device/opt/release").exists()


def test_image_build_installs_both_copies_with_the_shared_installer():
    text = PAYLOAD_BUILDER.read_text(encoding="utf-8")

    assert 'install-native-runtime.sh" "$RELEASE_ROOT/deploy/robot/native"' in text
    assert 'install-native-runtime.sh" "$OVERLAY/opt/rosy/native-runtime"' in text
    assert 'cp -a "$NATIVE_RUNTIME_SOURCE" "$OVERLAY/opt/rosy/native-runtime"' not in text
    assert 'cp -a "$NATIVE_RUNTIME_SOURCE" "$RELEASE_ROOT/deploy/robot/native"' not in text
