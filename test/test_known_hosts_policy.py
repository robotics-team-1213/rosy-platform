"""D-406 review N3: one known_hosts policy for the operator PowerShell scripts.

ssh parses `-o UserKnownHostsFile=<value>` like an ssh_config line and splits an
unquoted value at whitespace. Windows PowerShell 5.1 passes an argument that
already contains double quotes to a native program as is, so the C runtime of
that program strips the quotes before ssh's option parser sees the value. The
probe below records both steps; because a quoted path with a space does not
arrive intact, rosy-release-push.ps1 and rosy-update-hold.ps1 both pass the
path unquoted and refuse one with a space or a quote.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
PINKY = ROOT / "deploy" / "robot" / "pinky_pro"
SCRIPTS = [PINKY / "rosy-release-push.ps1", PINKY / "rosy-update-hold.ps1"]
WINDOWS_POWERSHELL = shutil.which("powershell")
VALUE = 'UserKnownHostsFile="C:\\a b\\known_hosts"'

pytestmark = pytest.mark.skipif(WINDOWS_POWERSHELL is None, reason="Windows PowerShell 5.1 is required")


def _powershell(command: str, env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run([WINDOWS_POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
                          capture_output=True, text=True, timeout=60, env=env)


def test_powershell_51_hands_the_quotes_to_the_native_program(tmp_path):
    """The raw command line a native .cmd receives keeps the quotes inside the argument..."""
    fake = tmp_path / "raw.cmd"
    fake.write_text('@echo off\r\necho %*>>"%ROSY_RAW_LOG%"\r\n', encoding="ascii")
    log = tmp_path / "raw.log"
    env = dict(os.environ, ROSY_RAW_LOG=str(log))

    done = _powershell(f"$v = '{VALUE}'; & '{fake}' -o $v rosy@robot", env)

    assert done.returncode == 0, done.stderr
    assert log.read_text(encoding="ascii").strip() == f"-o {VALUE} rosy@robot"


def test_the_c_runtime_then_strips_them_before_ssh_parses_the_value():
    """...and a C-runtime program (ssh.exe is one) gets the value without quotes, so ssh would split it."""
    probe = "import json, sys; print(json.dumps(sys.argv[1:]))"
    done = _powershell(f"$v = '{VALUE}'; & '{sys.executable}' -c '{probe}' -o $v rosy@robot")

    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout) == ["-o", "UserKnownHostsFile=C:\\a b\\known_hosts", "rosy@robot"]


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.name)
def test_both_scripts_pass_known_hosts_unquoted_and_refuse_a_split_path(script):
    text = script.read_text(encoding="ascii")

    assert '"UserKnownHostsFile=$KnownHosts"' in text
    assert "UserKnownHostsFile=`\"" not in text
    assert "KnownHosts path contains a space or a quote" in text


@pytest.mark.parametrize("script, extra", [
    (SCRIPTS[0], ["-Rollback", "-PrintCommands"]),
    (SCRIPTS[1], ["-Status"]),
], ids=["push", "hold"])
def test_both_scripts_refuse_a_known_hosts_path_with_a_space(tmp_path, script, extra):
    done = subprocess.run([WINDOWS_POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script),
                           "-Robot", "rosy-e4us.local", "-KnownHosts", str(tmp_path / "with space" / "known_hosts"),
                           "-SshExe", "rosy-no-such-ssh-for-test", *extra],
                          capture_output=True, text=True, timeout=60)

    assert done.returncode != 0
    assert "KnownHosts path contains a space" in done.stderr
    assert "rosy-no-such-ssh-for-test" not in done.stdout
