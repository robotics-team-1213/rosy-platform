"""D-412 deploy/robot/pinky_pro/rosy-update-hold.ps1: hold, release and status over ssh.

A fake ssh (a PowerShell script passed as -SshExe) records the argument array and
answers like the device CLI, so nothing here reaches a robot.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "deploy" / "robot" / "pinky_pro" / "rosy-update-hold.ps1"
POWERSHELL = shutil.which("powershell") or shutil.which("pwsh")
CLI = ["sudo", "-n", "python3", "/opt/rosy/native-runtime/rosy_auto_update.py"]
STATUS = {"schema": 1, "updated_at": "2026-10-01T15:20:00Z", "hostname": "rosy-pinky-8kcn",
          "current_release": "2026.10.01-021", "candidate": "2026.10.01-022", "phase": "held",
          "reason": "hold by livs@PC until 2026-10-01T19:00:00Z: G4 run",
          "last_result": {"release_id": "2026.10.01-021", "outcome": "committed",
                          "at": "2026-10-01T12:00:00Z", "detail": "healthy"}}

FAKE_SSH = r"""
Add-Content -Path $env:ROSY_FAKE_LOG -Value '----'
foreach ($a in $args) { Add-Content -Path $env:ROSY_FAKE_LOG -Value $a }
if ($env:ROSY_FAKE_EXIT) { 'hold refused: bad hours'; exit [int]$env:ROSY_FAKE_EXIT }
if (($args -join ' ') -match 'status --json') { Get-Content -Raw -Path $env:ROSY_FAKE_STATUS; exit 0 }
if ($env:ROSY_FAKE_RELEASE -and (($args -join ' ') -match 'release-hold')) { Get-Content -Raw -Path $env:ROSY_FAKE_RELEASE; exit 0 }
'ok'
exit 0
"""

pytestmark = pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")


def _run(tmp_path: Path, args: list[str], *, exit_code: int = 0, env_extra: dict | None = None,
         status_doc: dict = STATUS):
    fake = tmp_path / "fake-ssh.ps1"
    fake.write_text(FAKE_SSH, encoding="ascii")
    status = tmp_path / "status.json"
    status.write_text(json.dumps(status_doc, sort_keys=True), encoding="utf-8")
    log = tmp_path / "ssh.log"
    env = dict(os.environ, ROSY_FAKE_LOG=str(log), ROSY_FAKE_STATUS=str(status),
               LOCALAPPDATA=str(tmp_path / "appdata"), USERNAME="livs", COMPUTERNAME="OPS-PC")
    env.pop("ROSY_FAKE_EXIT", None)
    if exit_code:
        env["ROSY_FAKE_EXIT"] = str(exit_code)
    env.update(env_extra or {})
    command = [POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(SCRIPT),
               "-Robot", "192.168.1.202", "-SshExe", str(fake), *args]
    done = subprocess.run(command, capture_output=True, text=True, timeout=60, env=env)
    calls: list[list[str]] = []
    if log.exists():
        for line in log.read_text(encoding="utf-8").splitlines():
            if line == "----":
                calls.append([])
            else:
                calls[-1].append(line)
    return done, calls


def test_hold_runs_the_device_cli_with_quoted_arguments(tmp_path):
    done, calls = _run(tmp_path, ["-Hold", "-Reason", "G4 recording run", "-Hours", "4"])

    assert done.returncode == 0, done.stdout + done.stderr
    (argv,) = calls
    assert argv[-11:] == CLI + ["hold", "--holder", "'livs@OPS-PC'", "--reason", "'G4 recording run'",
                               "--hours", "4"]
    assert "rosy@192.168.1.202" in argv
    for option in ("IdentitiesOnly=yes", "BatchMode=yes", "StrictHostKeyChecking=yes", "ConnectTimeout=5"):
        assert option in argv
    known = next(a for a in argv if a.startswith("UserKnownHostsFile="))
    assert known == "UserKnownHostsFile=" + str(tmp_path / "appdata" / "Rosy" / "known_hosts")
    assert str(tmp_path / "appdata" / "Rosy" / "ssh" / "rosy-operator-ed25519") in argv
    # PowerShell 5.1 eats embedded double quotes on the way to a native exe.
    assert not any('"' in a for a in argv[argv.index("rosy@192.168.1.202"):])


def test_holder_and_fractional_hours_are_passed_through(tmp_path):
    done, calls = _run(tmp_path, ["-Hold", "-Reason", "bench", "-Hours", "0.5", "-Holder", "agent-rosy-0d"])

    assert done.returncode == 0, done.stdout + done.stderr
    assert calls[0][-6:] == ["--holder", "'agent-rosy-0d'", "--reason", "'bench'", "--hours", "0.5"]


@pytest.mark.parametrize("reason", [
    "a;reboot", "it's mine", "$(id)", "`whoami`", 'say "hi"', "-rf", "x|y", "a&b", "a>b", "back\\slash",
    "new\nline", "bench\n", "", " ", "x" * 201,
])
def test_unsafe_reasons_are_refused_before_ssh(tmp_path, reason):
    done, calls = _run(tmp_path, ["-Hold", "-Reason", reason, "-Hours", "4"])

    assert done.returncode != 0
    assert calls == []
    assert "Reason" in done.stderr


@pytest.mark.parametrize("holder", ["bad holder", "x'y", "a;b", "livs\n"])
def test_unsafe_holders_are_refused(tmp_path, holder):
    done, calls = _run(tmp_path, ["-Hold", "-Reason", "bench", "-Hours", "4", "-Holder", holder])

    assert done.returncode != 0 and calls == []
    assert "Holder" in done.stderr


def test_a_default_holder_with_unsafe_characters_names_the_holder_flag(tmp_path):
    done, calls = _run(tmp_path, ["-Hold", "-Reason", "bench", "-Hours", "4"], env_extra={"USERNAME": "Jane Doe"})

    assert done.returncode != 0 and calls == []
    assert "-Holder" in done.stderr


@pytest.mark.parametrize("hours", ["0", "-1", "168.01", "169"])
def test_hours_outside_zero_to_168_are_refused(tmp_path, hours):
    done, calls = _run(tmp_path, ["-Hold", "-Reason", "bench", "-Hours", hours])

    assert done.returncode != 0 and calls == []
    assert "Hours" in done.stderr


def test_168_hours_is_the_largest_accepted(tmp_path):
    done, calls = _run(tmp_path, ["-Hold", "-Reason", "bench", "-Hours", "168"])

    assert done.returncode == 0, done.stderr
    assert calls[0][-1] == "168"


@pytest.mark.parametrize("args", [
    [],
    ["-Hold", "-Release", "-Reason", "x", "-Hours", "1"],
    ["-Release", "-Status"],
    ["-Hold", "-Hours", "1"],
    ["-Hold", "-Reason", "x"],
    ["-Release", "-Reason", "x"],
    ["-Status", "-Hours", "1"],
])
def test_exactly_one_action_with_only_its_own_arguments(tmp_path, args):
    done, calls = _run(tmp_path, args)

    assert done.returncode != 0
    assert calls == []


def test_release_runs_release_hold(tmp_path):
    done, calls = _run(tmp_path, ["-Release"])

    assert done.returncode == 0, done.stderr
    assert calls[0][-5:] == CLI + ["release-hold"]


def test_status_prints_status_json_readably(tmp_path):
    done, calls = _run(tmp_path, ["-Status"])

    assert done.returncode == 0, done.stderr
    assert calls[0][-6:] == CLI + ["status", "--json"]
    out = done.stdout
    for text in ("rosy-pinky-8kcn", "2026.10.01-021", "2026.10.01-022", "held", "G4 run", "committed",
                 "2026-10-01T15:20:00Z"):
        assert text in out, text
    assert "{" not in out  # readable, not the raw JSON


def test_a_failing_device_cli_fails_the_command(tmp_path):
    done, _calls = _run(tmp_path, ["-Hold", "-Reason", "bench", "-Hours", "4"], exit_code=2)

    assert done.returncode != 0
    assert "hold refused" in done.stdout + done.stderr


def test_a_bad_robot_name_is_refused(tmp_path):
    fake = tmp_path / "x.ps1"
    done = subprocess.run([POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(SCRIPT),
                           "-Robot", "evil;reboot", "-SshExe", str(fake), "-Status"],
                          capture_output=True, text=True, timeout=60)
    assert done.returncode != 0
    assert "Robot" in done.stderr


def test_the_script_stays_ascii_and_never_disables_host_key_checking():
    raw = SCRIPT.read_bytes()
    raw.decode("ascii")
    text = raw.decode("ascii")
    assert "StrictHostKeyChecking=yes" in text and "StrictHostKeyChecking=no" not in text


# --- review fixes (M2, L5) ---------------------------------------------------------

# T2 rosy_auto_update.py `status --json` when status.json does not exist yet.
NOT_RUN_YET = {"phase": None, "reason": "the updater has not run yet"}


@pytest.mark.parametrize("doc", [NOT_RUN_YET, {"phase": "idle"}, dict(STATUS, last_result=None), {}])
def test_status_survives_missing_or_null_fields(tmp_path, doc):
    done, _calls = _run(tmp_path, ["-Status"], status_doc=doc)

    assert done.returncode == 0, done.stdout + done.stderr
    assert "phase" in done.stdout and "last result" in done.stdout
    if doc is NOT_RUN_YET:
        assert "the updater has not run yet" in done.stdout


@pytest.mark.parametrize("appdata", ["with space", "it's"])
def test_a_known_hosts_path_ssh_would_split_is_refused(tmp_path, appdata):
    done, calls = _run(tmp_path, ["-Status"], env_extra={"LOCALAPPDATA": str(tmp_path / appdata)})

    assert done.returncode != 0 and calls == []
    assert "KnownHosts" in done.stderr


def test_no_native_argument_carries_a_double_quote(tmp_path):
    _done, calls = _run(tmp_path, ["-Hold", "-Reason", "bench", "-Hours", "1"])

    assert not any('"' in a for a in calls[0])


def test_release_prints_what_the_device_acknowledged(tmp_path):
    # D-412 final verification LOW 2: the device's release-hold JSON, readable.
    answer = tmp_path / "release.json"
    answer.write_text(json.dumps({"ok": True, "released": True,
                                  "acknowledged_rollback_failure": "2026.10.01-022",
                                  "cleared_apply_errors": ["2026.10.01-022", "2026.10.01-023"]}),
                      encoding="utf-8")
    done, _calls = _run(tmp_path, ["-Release"], env_extra={"ROSY_FAKE_RELEASE": str(answer)})

    assert done.returncode == 0, done.stderr
    out = done.stdout
    assert "hold released: yes" in out
    assert "acknowledged rollback failure: 2026.10.01-022" in out
    assert "cleared apply errors: 2026.10.01-022, 2026.10.01-023" in out
    assert "{" not in out


def test_release_with_nothing_to_acknowledge_says_so(tmp_path):
    answer = tmp_path / "release.json"
    answer.write_text(json.dumps({"ok": True, "released": False, "acknowledged_rollback_failure": None,
                                  "cleared_apply_errors": []}), encoding="utf-8")
    done, _calls = _run(tmp_path, ["-Release"], env_extra={"ROSY_FAKE_RELEASE": str(answer)})

    assert done.returncode == 0, done.stderr
    assert "hold released: no (none was set)" in done.stdout
    assert "acknowledged rollback failure: -" in done.stdout
    assert "cleared apply errors: -" in done.stdout
