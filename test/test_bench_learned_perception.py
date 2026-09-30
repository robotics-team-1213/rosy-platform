"""D-373 decision 1: the bench install applies the image layer before a re-bake.

A bench Pinky that still runs an older card gets the learned-perception runtime
from the same hash-locked file, into the same pip --target prefix, with the same
directory rule the next image bakes in. It never writes /usr/local and never
touches the card's Python runtime record: the payload runtime id stays the one
test_python_runtime_id.py pins, so payloads keep activating on every card.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
PINKY = ROOT / "deploy" / "robot" / "pinky_pro"
SCRIPT = PINKY / "dev" / "install-learned-perception.sh"
CUSTOMIZER = PINKY / "image" / "customize-rootfs.sh"
LEARNED = PINKY / "image" / "learned-perception-requirements.txt"
DEVICE_REQUIREMENTS = PINKY / "image" / "device-python-requirements.txt"
STATE_RULES = PINKY / "native" / "tmpfiles-rosy-state.conf"
LOCK = PINKY / "image" / "inputs.lock.yaml"
RUNNER = ROOT / "src" / "runtime" / "sensing" / "control" / "sensing" / "perception" / "learned" / "runner.py"
PINS = {"onnxruntime": "1.30.0", "flatbuffers": "25.12.19", "packaging": "26.3", "protobuf": "7.36.2"}
TARGET = "/opt/rosy/learned-perception/site-packages"
MODELS_RULE = "d /var/lib/rosy/models 0750 root rosy-camera -"
PIP_FLAGS = ("--require-hashes", "--no-deps", "--only-binary=:all:", "--no-cache-dir")


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


def _lock() -> dict:
    return yaml.safe_load(LOCK.read_text(encoding="utf-8"))


def _learned_pip_command(source: str) -> str:
    install = source.rindex("python3 -m pip install", 0, source.index("--target \"$"))
    return source[install:source.index("\n", source.index("-r ", install))]


def test_the_learned_file_is_its_own_lock_entry_not_the_payload_runtime():
    runtime = _lock()["learned_perception_runtime"]
    assert runtime["requirements"] == LEARNED.name
    lf = LEARNED.read_bytes().replace(b"\r\n", b"\n")
    assert hashlib.sha256(lf).hexdigest() == runtime["requirements_sha256"]
    assert runtime["target"] == TARGET
    # The payload runtime (D-189) knows nothing of it.
    assert "compatible_predecessors" not in _lock()["python_runtime"]
    assert "onnxruntime" not in DEVICE_REQUIREMENTS.read_text(encoding="utf-8")


def test_the_learned_file_pins_exactly_the_runtime_with_hashes():
    text = LEARNED.read_text(encoding="utf-8").replace("\\\n", " ")
    entries = {}
    for line in text.splitlines():
        if "==" in line and not line.startswith("#"):
            name, rest = line.split("==", 1)
            entries[name.strip()] = (rest.split()[0], re.findall(r"--hash=sha256:([0-9a-f]{64})", rest))
    assert {k: v[0] for k, v in entries.items()} == PINS
    for name, (_, hashes) in entries.items():
        assert len(hashes) == (2 if name in {"onnxruntime", "protobuf"} else 1), name
    assert "numpy" not in entries


def test_image_and_bench_install_into_the_same_prefix_with_the_same_flags():
    for source in (CUSTOMIZER.read_text(encoding="utf-8"), _source()):
        command = _learned_pip_command(source)
        for flag in PIP_FLAGS:
            assert flag in command, flag
        assert "--target" in command and "--break-system-packages" not in command
        assert "--prefix" not in command and "--user" not in command
    customizer = CUSTOMIZER.read_text(encoding="utf-8")
    assert "lock_value learned_perception_runtime target" in customizer
    assert "learned-perception-requirements.txt" not in _source()  # named by the lock only
    assert "learned_perception_runtime" in _source()


def test_the_runner_and_the_doctor_use_the_same_prefix():
    assert f'LEARNED_SITE = "{TARGET}"' in RUNNER.read_text(encoding="utf-8")
    rosy_ml = (ROOT / "tools" / "perception" / "rosy_ml.py").read_text(encoding="utf-8")
    assert f'LEARNED_SITE = "{TARGET}"' in rosy_ml


def test_bench_never_writes_usr_local_nor_the_runtime_record():
    source = _source()
    code = "\n".join(line for line in source.splitlines() if not line.lstrip().startswith("#"))
    assert "/usr/local" not in code
    assert "python-runtime" not in code
    assert "--break-system-packages" not in code


def test_script_takes_directory_rules_from_the_tmpfiles_file():
    source = _source()
    assert MODELS_RULE in STATE_RULES.read_text(encoding="utf-8")
    assert "native/tmpfiles-rosy-state.conf" in source
    # The mode/owner come from the tmpfiles line, never a second literal here.
    assert "0750" not in source and "rosy-camera" not in source
    assert 'install -d -m "$mode" -o "$user" -g "$group" "$path"' in source


def test_script_refuses_non_root_and_records_the_install():
    source = _source()
    root_check = source.index('"$(id -u)" -eq 0')
    assert root_check < source.index("python3 -m pip install")
    assert "/var/log/rosy/bench-installs.log" in source
    assert source.startswith("#!/bin/bash\n") and "set -euo pipefail" in source
    assert b"\r" not in SCRIPT.read_bytes()


@pytest.mark.skipif(BASH is None, reason="bash is unavailable on this host")
def test_dry_run_prints_exactly_the_locked_file_target_and_models_rule():
    completed = subprocess.run([BASH, str(SCRIPT).replace("\\", "/"), "--dry-run"],
                               capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert completed.returncode == 0, completed.stderr
    lines = completed.stdout.splitlines()
    lf = LEARNED.read_bytes().replace(b"\r\n", b"\n")
    assert f"requirements_sha256={hashlib.sha256(lf).hexdigest()}" in lines
    assert f"target={TARGET}" in lines
    assert f"dir {MODELS_RULE.removesuffix(' -')}" in lines
    listed = completed.stdout[completed.stdout.index("--- requirements\n") + len("--- requirements\n"):]
    assert listed == lf.decode("utf-8")


@pytest.mark.skipif(BASH is None or (hasattr(os, "geteuid") and os.geteuid() == 0),
                    reason="needs a non-root bash")
def test_real_run_refuses_a_non_root_user():
    completed = subprocess.run([BASH, str(SCRIPT).replace("\\", "/")],
                               capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert completed.returncode != 0
    assert "root" in completed.stderr
