"""D-383 (6): motor commissioning reaches the robot with the Rosy operator key.

2026-10-01: enable-motor-commissioning.ps1 used only the default ~/.ssh alias
and failed on a new card with "No ED25519 host key is known". It now takes the
same key, known_hosts and user as rosy-release-push.ps1. Host tests only: the
resolved ssh arguments are printed, and a missing key stops before any network.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "deploy" / "robot" / "pinky_pro" / "sd" / "enable-motor-commissioning.ps1"
POWERSHELL = shutil.which("powershell") or shutil.which("pwsh")
pytestmark = pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")


def _run(local_app_data: Path, *extra):
    env = {**os.environ, "LOCALAPPDATA": str(local_app_data)}
    return subprocess.run([
        POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(SCRIPT),
        "-DeviceName", "rosy-pinky-9dfk", "-RobotAddress", "127.0.0.1", *map(str, extra),
    ], capture_output=True, text=True, env=env, timeout=120)


def _pairs(options):
    return {options[i + 1] for i, item in enumerate(options[:-1]) if item == "-o"}


def test_the_rosy_operator_key_known_hosts_and_user_are_the_defaults(tmp_path):
    completed = _run(tmp_path, "-PrintSshArguments")

    assert completed.returncode == 0, completed.stderr
    printed = json.loads(completed.stdout)
    options = printed["ssh_options"]
    assert printed["ssh_host"] == "rosy-pinky-9dfk"
    assert options[options.index("-i") + 1] == str(tmp_path / "Rosy" / "ssh" / "rosy-operator-ed25519")
    assert options[options.index("-l") + 1] == "rosy"
    assert {"IdentitiesOnly=yes", f"UserKnownHostsFile={tmp_path / 'Rosy' / 'known_hosts'}",
            "StrictHostKeyChecking=yes", "BatchMode=yes"} <= _pairs(options)


def test_key_known_hosts_and_user_can_be_passed(tmp_path):
    key, known = tmp_path / "k", tmp_path / "kh"

    completed = _run(tmp_path, "-PrintSshArguments", "-KeyPath", key, "-KnownHosts", known, "-RosyUser", "pinky")

    assert completed.returncode == 0, completed.stderr
    options = json.loads(completed.stdout)["ssh_options"]
    assert options[options.index("-i") + 1] == str(key)
    assert options[options.index("-l") + 1] == "pinky"
    assert f"UserKnownHostsFile={known}" in _pairs(options)


@pytest.mark.parametrize("missing", ["key", "known_hosts"])
def test_a_missing_key_or_known_hosts_stops_before_the_robot(tmp_path, missing):
    key, known = tmp_path / "k", tmp_path / "kh"
    if missing != "key":
        key.write_text("key\n", encoding="ascii")
    if missing != "known_hosts":
        known.write_text("host\n", encoding="ascii")

    completed = _run(tmp_path, "-CheckOnly", "-KeyPath", key, "-KnownHosts", known)

    assert completed.returncode != 0
    rendered = " ".join(completed.stderr.split())
    label = "operator key" if missing == "key" else "known_hosts"
    assert f"The Rosy {label} file is missing" in rendered
    assert "credential" not in rendered.lower()  # stopped before the CORE credential and any network


def test_every_ssh_call_uses_the_resolved_options():
    text = SCRIPT.read_text(encoding="utf-8")
    calls = re.findall(r"& ssh\.exe[^\n]*", text)
    assert len(calls) == 2
    assert all(call.startswith("& ssh.exe @script:sshOptions $SshHost") for call in calls)
