"""D-406: rosy-release-push.ps1 takes the D-387 claim on the robot for the whole push.

The claim helper (/opt/rosy/native-runtime/rosy_claim.py acquire|release|status) is
shared with the robot's auto-updater, so a push and an automatic update never run
at the same time. A robot whose native-runtime predates the helper gets a warning
and the push goes on. A fake ssh stands in for the robot.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "deploy" / "robot" / "pinky_pro" / "rosy-release-push.ps1"
POWERSHELL = shutil.which("powershell") or shutil.which("pwsh")
SH = shutil.which("sh")
HELPER = "/opt/rosy/native-runtime/rosy_claim.py"

FAKE_SSH = r"""
$all = $args -join ' '
Add-Content -Path $env:ROSY_FAKE_LOG -Value $all
if ($all -match 'rosy_claim.py acquire') {
    if ($env:ROSY_FAKE_CLAIM -eq 'missing') { 'ROSY_CLAIM_HELPER_MISSING'; exit 4 }
    if ($env:ROSY_FAKE_CLAIM -eq 'held') {
        '{' + [char]34 + 'claim' + [char]34 + ': {' + [char]34 + 'holder' + [char]34 + ': ' + [char]34 + 'rosy-auto-update' + [char]34 + '}, ' + [char]34 + 'error' + [char]34 + ': ' + [char]34 + 'CLAIM_BUSY' + [char]34 + ', ' + [char]34 + 'ok' + [char]34 + ': false}'
        exit 3
    }
    if ($env:ROSY_FAKE_CLAIM -eq 'sshfail') { 'ssh: connect to host rosy-e4us.local port 22: Connection timed out'; exit 255 }
    if ($env:ROSY_FAKE_CLAIM -eq 'invalid') { '{' + [char]34 + 'error' + [char]34 + ': ' + [char]34 + 'CLAIM_HOLDER_INVALID' + [char]34 + ', ' + [char]34 + 'ok' + [char]34 + ': false}'; exit 2 }
    'CLAIM_ACQUIRED'; exit 0
}
if ($all -match 'rosy_claim.py release') { if ($env:ROSY_FAKE_RELEASE_FAIL) { exit 1 }; exit 0 }
if ($all -match 'IMAGE_LAYER_SYNC_MISSING') { 'IMAGE_LAYER_SYNC_MISSING'; exit 3 }
if ($all -match 'CORE_RELEASE_OK') {
    if ($env:ROSY_FAKE_CORE -eq 'dead') { 'CORE_RELEASE_STALE pid=7 cwd=a want=b'; 'CORE_RESTART_FAILED' }
    else { 'CORE_RELEASE_OK /opt/rosy/releases/R' }
    exit 0
}
if ($all -match 'release.sh') { '{"ok": true, "release_id": "R", "previous": "P"}' }
exit 0
"""

pytestmark = pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")


def _env(**extra) -> dict:
    env = dict(os.environ, USERNAME="livs", COMPUTERNAME="OPS-PC")
    for name in ("ROSY_FAKE_CLAIM", "ROSY_FAKE_CORE", "ROSY_FAKE_RELEASE_FAIL"):
        env.pop(name, None)
    env.update(extra)
    return env


def _print_plan(env=None) -> list[dict]:
    done = subprocess.run([POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(SCRIPT),
                           "-Robot", "rosy-e4us.local", "-Rollback", "-PrintCommands"],
                          capture_output=True, text=True, timeout=60, env=env or _env())
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)["plan"]


def _fake_rollback(tmp_path: Path, **extra):
    fake = tmp_path / "fake-ssh.ps1"
    fake.write_text(FAKE_SSH, encoding="ascii")
    log = tmp_path / "ssh.log"
    done = subprocess.run([POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(SCRIPT),
                           "-Robot", "rosy-e4us.local", "-Rollback", "-SshExe", str(fake), "-ScpExe", str(fake)],
                          capture_output=True, text=True, timeout=90,
                          env=_env(ROSY_FAKE_LOG=str(log), LOCALAPPDATA=str(tmp_path), **extra))
    calls = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
    return done, calls


def test_the_plan_brackets_every_step_with_claim_acquire_and_release():
    plan = _print_plan()

    assert plan[0]["role"] == "claim-acquire" and plan[-1]["role"] == "claim-release"
    assert [s["role"] for s in plan].count("claim-acquire") == 1
    acquire, release = plan[0]["arguments"], plan[-1]["arguments"]
    assert acquire[-5:-1] == ["sudo", "-n", "sh", "-c"] and release[-5:-1] == ["sudo", "-n", "sh", "-c"]
    assert (f"exec python3 {HELPER} acquire --holder push-livs@OPS-PC --purpose push --ttl-s 1800"
            in acquire[-1])
    assert f"exec python3 {HELPER} release --holder push-livs@OPS-PC" in release[-1]
    for script in (acquire[-1], release[-1]):
        assert f"if [ -f {HELPER} ]" in script and "ROSY_CLAIM_HELPER_MISSING" in script
        assert '"' not in script and script.startswith("'") and script.endswith("'")
    for step in (plan[0], plan[-1]):
        assert "StrictHostKeyChecking=yes" in step["arguments"]
        assert "rosy_claim.py" in step["display"]


def test_an_unsafe_user_name_is_reduced_to_safe_characters():
    plan = _print_plan(_env(USERNAME="Jane Doe;x'y"))

    assert "--holder push-Jane_Doe_x_y@OPS-PC " in plan[0]["arguments"][-1]


@pytest.mark.skipif(SH is None, reason="sh is required")
def test_the_remote_wrapper_reports_a_missing_helper():
    script = _print_plan()[0]["arguments"][-1][1:-1]
    if Path(HELPER).exists():
        pytest.skip("this host has the helper installed")

    done = subprocess.run([SH, "-c", script], capture_output=True, text=True, timeout=30)

    assert done.returncode == 4
    assert done.stdout.strip() == "ROSY_CLAIM_HELPER_MISSING"


def test_a_push_takes_the_claim_first_and_releases_it_last(tmp_path):
    done, calls = _fake_rollback(tmp_path)

    assert done.returncode == 0, done.stdout + done.stderr
    assert "rosy_claim.py acquire" in calls[0]
    assert "rosy_claim.py release" in calls[-1]
    assert sum("rosy_claim.py release" in c for c in calls) == 1
    assert "wait-core-ready.py" in calls[-2]


def test_a_claimed_robot_refuses_the_push_before_anything_else(tmp_path):
    done, calls = _fake_rollback(tmp_path, ROSY_FAKE_CLAIM="held")

    assert done.returncode != 0
    flat = "".join((done.stdout + done.stderr).split())
    assert "claimedbyanotherjob" in flat and "CLAIM_BUSY" in flat and "rosy-auto-update" in flat
    assert "claimhelperfailed" not in flat
    assert len(calls) == 1  # no step ran, and nothing we do not hold was released


def test_the_claim_is_released_when_a_later_step_fails(tmp_path):
    done, calls = _fake_rollback(tmp_path, ROSY_FAKE_CORE="dead")

    assert done.returncode != 0
    assert "CORE_RELEASE_OK" in calls[-2]
    assert "rosy_claim.py release" in calls[-1]


def test_a_robot_without_the_helper_warns_and_pushes_on(tmp_path):
    done, calls = _fake_rollback(tmp_path, ROSY_FAKE_CLAIM="missing")

    assert done.returncode == 0, done.stdout + done.stderr
    flat = "".join((done.stdout + done.stderr).split())
    assert "norosy_claim.py" in flat and "withouttheclaim" in flat
    assert "rollback-release.sh" in calls[1]
    assert not any("rosy_claim.py release" in c for c in calls)


def test_a_failed_release_only_warns(tmp_path):
    done, calls = _fake_rollback(tmp_path, ROSY_FAKE_RELEASE_FAIL="1")

    assert done.returncode == 0, done.stdout + done.stderr
    assert "couldnotreleasetheclaim" in "".join((done.stdout + done.stderr).split())


@pytest.mark.parametrize("mode, code", [("sshfail", 255), ("invalid", 2)])
def test_a_failing_claim_helper_refuses_the_push_and_still_releases(tmp_path, mode, code):
    """M3/L4: not "busy", so it may have been taken before the failure; the release is holder-scoped."""
    done, calls = _fake_rollback(tmp_path, ROSY_FAKE_CLAIM=mode)

    assert done.returncode != 0
    flat = "".join((done.stdout + done.stderr).split())
    assert f"claimhelperfailed(exit{code})" in flat
    assert "claimedbyanotherjob" not in flat
    assert len(calls) == 2
    assert "rosy_claim.py acquire" in calls[0] and "rosy_claim.py release" in calls[1]


TTL_FUNCTION = re.compile(r"^function Get-ClaimTtl.*?^}", re.MULTILINE | re.DOTALL)


@pytest.mark.parametrize("megabytes, ttl", [(0, 1800), (100, 1800), (300, 1800), (1000, 3200), (5000, 7200)])
def test_the_claim_ttl_grows_with_the_tarball(megabytes, ttl):
    """L4: 1200 s for the steps plus 2 s per MB of upload, at least 1800 s, at most 7200 s."""
    function = TTL_FUNCTION.search(SCRIPT.read_text(encoding="utf-8")).group(0)
    done = subprocess.run([POWERSHELL, "-NoProfile", "-Command",
                           function + f"; Get-ClaimTtl {megabytes * 1024 * 1024}"],
                          capture_output=True, text=True, timeout=60)

    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == str(ttl)


def test_the_plan_takes_the_claim_for_the_sized_ttl():
    script = SCRIPT.read_text(encoding="utf-8")

    assert "Get-ClaimTtl" in script
    assert "--ttl-s $ClaimTtl" in script
