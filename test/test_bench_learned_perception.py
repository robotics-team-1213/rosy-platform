"""D-373 decision 1: the bench install applies the image layer before a re-bake.

A bench Pinky that still runs an older card gets the learned-perception runtime
from the same hash-locked file and the same directory rule the next image bakes
in. These tests keep the script from drifting from those two sources.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PINKY = ROOT / "deploy" / "robot" / "pinky_pro"
SCRIPT = PINKY / "dev" / "install-learned-perception.sh"
REQUIREMENTS = PINKY / "image" / "device-python-requirements.txt"
STATE_RULES = PINKY / "native" / "tmpfiles-rosy-state.conf"
BEGIN = "# BEGIN D-373 learned-perception runtime"
END = "# END D-373 learned-perception runtime"
LEARNED = {"onnxruntime": "1.30.0", "flatbuffers": "25.12.19", "packaging": "26.3", "protobuf": "7.36.2"}
MODELS_RULE = "d /var/lib/rosy/models 0750 root rosy-camera -"


def _find_bash():
    # WSL's system32 bash cannot read Windows paths; prefer Git Bash (as test_dds_identity_contracts).
    candidates = [r"C:\Program Files\Git\bin\bash.exe"] if os.name == "nt" else []
    if shutil.which("bash"):
        candidates.append(shutil.which("bash"))
    for candidate in candidates:
        try:
            if subprocess.run([candidate, "-c", "true"], capture_output=True, timeout=5).returncode == 0:
                return candidate
        except (OSError, subprocess.SubprocessError):
            continue
    return None


BASH = _find_bash()


def _source() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def _block_text() -> str:
    text = REQUIREMENTS.read_text(encoding="utf-8")
    return text[text.index(BEGIN):]


def test_script_installs_the_block_with_the_image_pip_flags():
    source = _source()
    install = source.index("python3 -m pip install")
    command = source[install:source.index("\n", source.index("-r ", install))]
    for flag in ("--require-hashes", "--no-deps", "--only-binary=:all:", "--ignore-installed",
                 "--break-system-packages", "--no-cache-dir"):
        assert flag in command, flag
    # Same target as customize-rootfs.sh: root pip's /usr/local dist-packages.
    assert "--prefix" not in command and "--target" not in command and "--user" not in command
    assert source[source.rindex("\n", 0, install):install].strip().endswith("(umask 022 &&")
    assert "image/device-python-requirements.txt" in source
    assert BEGIN in source and END in source


def test_script_takes_directory_rules_from_the_tmpfiles_file():
    source = _source()
    assert MODELS_RULE in STATE_RULES.read_text(encoding="utf-8")
    assert "native/tmpfiles-rosy-state.conf" in source
    # The mode/owner come from the tmpfiles line, never a second literal here.
    assert "0750" not in source and "rosy-camera" not in source.replace("rosy-camera.service", "")
    assert 'install -d -m "$mode" -o "$user" -g "$group" "$path"' in source


def test_script_refuses_non_root_and_records_the_install():
    source = _source()
    root_check = source.index('"$(id -u)" -eq 0')
    assert root_check < source.index("python3 -m pip install")
    assert "/var/log/rosy/bench-installs.log" in source
    assert "/usr/local/share/rosy/python-runtime.sha256" in source
    assert source.startswith("#!/bin/bash\n") and "set -euo pipefail" in source
    assert b"\r" not in SCRIPT.read_bytes()


@pytest.mark.skipif(BASH is None, reason="bash is unavailable on this host")
def test_dry_run_prints_exactly_the_pinned_block_and_the_models_rule():
    completed = subprocess.run([BASH, str(SCRIPT).replace("\\", "/"), "--dry-run"],
                               capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert completed.returncode == 0, completed.stderr
    lines = completed.stdout.splitlines()
    data = REQUIREMENTS.read_bytes()
    assert f"requirements_sha256={hashlib.sha256(data).hexdigest()}" in lines
    # The runtime an image baked before D-373 records: the file without the block.
    base = data[:data.index(BEGIN.encode())].removesuffix(b"\n")
    assert f"image_runtime_before={hashlib.sha256(base).hexdigest()}" in lines
    assert f"dir {MODELS_RULE.removesuffix(' -')}" in lines
    block = completed.stdout[completed.stdout.index("--- block\n") + len("--- block\n"):]
    assert block == _block_text()
    pins = {line.split("==")[0]: line.split("==")[1].split()[0]
            for line in block.splitlines() if "==" in line and not line.startswith("#")}
    assert pins == LEARNED


@pytest.mark.skipif(BASH is None or (hasattr(os, "geteuid") and os.geteuid() == 0),
                    reason="needs a non-root bash")
def test_real_run_refuses_a_non_root_user():
    completed = subprocess.run([BASH, str(SCRIPT).replace("\\", "/")],
                               capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert completed.returncode != 0
    assert "root" in completed.stderr
