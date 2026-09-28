"""Host tests for Hub ARM64 hollow-file restore helpers.

The helpers must no-op on a healthy tree and must see 0-byte .py files
under /opt/ros, not only python3-* Debian paths.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "deploy" / "robot" / "pinky_pro"
PYTHON_SH = DEPLOY / "restore-hollow-python.sh"
TOOLCHAIN_SH = DEPLOY / "restore-hollow-toolchain.sh"
DOCKERFILE = DEPLOY / "Dockerfile"


def _bash() -> str:
    candidates = []
    if os.name == "nt":
        candidates.extend(
            (
                r"C:\Program Files\Git\bin\bash.exe",
                r"C:\Program Files\Git\usr\bin\bash.exe",
            )
        )
    which = shutil.which("bash")
    if which:
        candidates.append(which)
    for candidate in candidates:
        if not candidate:
            continue
        if os.name == "nt" and not Path(candidate).is_file():
            continue
        try:
            probe = subprocess.run(
                [candidate, "-c", "true"],
                capture_output=True,
                timeout=2,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if probe.returncode == 0:
            return candidate
    pytest.skip("usable bash not found")


def _run_helper(script: Path, fake_root: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["ROSY_HOLLOW_ROOT"] = str(fake_root).replace("\\", "/")
    env["ROSY_HOLLOW_DRY_RUN"] = "1"
    posix_script = str(script).replace("\\", "/")
    return subprocess.run(
        [_bash(), posix_script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        timeout=15,
        check=False,
    )


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _unix_executable(path: Path, payload: bytes = b"#!/bin/sh\nexit 0\n") -> None:
    _write(path, payload)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


def test_python_restore_skips_when_no_zero_byte_py(tmp_path: Path) -> None:
    _write(tmp_path / "usr/lib/python3.12/os.py", b"print('ok')\n")
    _write(
        tmp_path / "opt/ros/jazzy/lib/python3.12/site-packages/rclpy/__init__.py",
        b"# rclpy\n",
    )
    proc = _run_helper(PYTHON_SH, tmp_path)
    combined = proc.stdout + proc.stderr
    assert proc.returncode == 0, combined
    assert "skip" in combined.lower()
    assert "apt-get" not in combined


def test_python_restore_lists_opt_ros_zero_byte_py(tmp_path: Path) -> None:
    _write(tmp_path / "usr/lib/python3.12/os.py", b"print('ok')\n")
    hollow = (
        tmp_path
        / "opt/ros/jazzy/lib/python3.12/site-packages/ament_index_python/__init__.py"
    )
    _write(hollow, b"")
    proc = _run_helper(PYTHON_SH, tmp_path)
    combined = proc.stdout + proc.stderr
    assert proc.returncode == 0, combined
    assert "skip" not in combined.lower()
    assert "opt/ros" in combined.replace("\\", "/")
    assert "ament_index_python" in combined


def test_toolchain_skips_when_compilers_present(tmp_path: Path) -> None:
    _unix_executable(tmp_path / "usr/bin/gcc")
    _unix_executable(tmp_path / "usr/bin/g++")
    _unix_executable(tmp_path / "usr/bin/make")
    _write(
        tmp_path / "usr/share/cmake-3.28/Modules/CMakeDetermineCCompiler.cmake",
        b"# cmake module\n",
    )
    proc = _run_helper(TOOLCHAIN_SH, tmp_path)
    combined = proc.stdout + proc.stderr
    assert proc.returncode == 0, combined
    assert "skip" in combined.lower()
    assert "apt-get" not in combined


def test_toolchain_restores_when_gcc_missing(tmp_path: Path) -> None:
    _unix_executable(tmp_path / "usr/bin/make")
    _write(
        tmp_path / "usr/share/cmake-3.28/Modules/CMakeDetermineCCompiler.cmake",
        b"# cmake module\n",
    )
    proc = _run_helper(TOOLCHAIN_SH, tmp_path)
    combined = proc.stdout + proc.stderr
    assert proc.returncode == 0, combined
    assert "skip" not in combined.lower()
    assert "gcc" in combined.lower()


def test_dockerfile_runtime_common_does_not_always_reinstall_cpython() -> None:
    text = DOCKERFILE.read_text(encoding="utf-8")
    common = text.split("FROM runtime-common AS core-runtime")[0]
    assert "restore-hollow-python.sh" in common
    assert "libpython3.12-minimal" not in common
    assert "apt-get install --reinstall" not in common
