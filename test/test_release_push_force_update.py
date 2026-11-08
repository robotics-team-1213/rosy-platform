"""D-985 addendum: rosy-release-push.ps1 -ForceUpdate installs a named signed release now.

It adds a mandatory reason, the robot's own updater precheck (hold, claim, CORE idle, battery) right
before the switch, and an audit line. It never skips the signature check, the claim, the calibration
guard, the CORE health check or the automatic rollback, which stay in the unchanged push. A fake ssh
stands in for the robot.
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
SCRIPT = ROOT / "deploy" / "robot" / "pinky_pro" / "rosy-release-push.ps1"
POWERSHELL = shutil.which("powershell") or shutil.which("pwsh")
TAR = shutil.which("tar")
RELEASE_ID = "2026.11.09-001"
PRECHECK = "rosy_auto_update.py precheck"

pytestmark = pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")

FAKE_SSH = r"""
$all = $args -join ' '
Add-Content -Path $env:ROSY_FAKE_LOG -Value $all
if ($all -match 'rosy_auto_update.py precheck') {
    if ($env:ROSY_FAKE_PRECHECK_OUT) { $env:ROSY_FAKE_PRECHECK_OUT }
    exit ([int]$env:ROSY_FAKE_PRECHECK_RC)
}
if ($all -match 'rosy_claim.py acquire') { 'CLAIM_ACQUIRED'; exit 0 }
if ($all -match '--dry-run') { '{"ok": true, "release_id": "R", "changed": [], "new": [], "unchanged": [], "skipped": [], "restart_units": []}'; exit 0 }
if ($all -match 'sync-image-layer') { '{"ok": true, "release_id": "R", "changed": [], "new": [], "unchanged": [], "skipped": [], "restart_units": []}'; exit 0 }
if ($all -match 'CORE_RELEASE_OK') { 'CORE_RELEASE_OK /opt/rosy/releases/R'; exit 0 }
if ($all -match 'release.sh') { '{"ok": true, "release_id": "R", "previous": "P"}' }
exit 0
"""

FREE = {"ROSY_FAKE_PRECHECK_RC": "0", "ROSY_FAKE_PRECHECK_OUT": "ok"}
FORCE = ["-ForceUpdate", "-ExpectReleaseId", RELEASE_ID, "-Reason", "bench fix needed (KAN-1)"]


@pytest.fixture
def release(tmp_path: Path) -> dict:
    sys.path.insert(0, str(ROOT / "deploy" / "robot" / "pinky_pro" / "release"))
    from signing import build_sha256sums, sign_checksums  # noqa: E402

    private, public = tmp_path / "test.key", tmp_path / "pub.pem"
    subprocess.run(["openssl", "genpkey", "-algorithm", "ed25519", "-out", str(private)],
                   check=True, capture_output=True)
    subprocess.run(["openssl", "pkey", "-in", str(private), "-pubout", "-out", str(public)],
                   check=True, capture_output=True)
    release_dir = tmp_path / "release"
    (release_dir / "install").mkdir(parents=True)
    (release_dir / "install" / ".rosy-release").write_text(RELEASE_ID, encoding="utf-8")
    (release_dir / "manifest.json").write_text(
        json.dumps({"release_id": RELEASE_ID, "git_revision": "a" * 40}), encoding="utf-8")
    files = sorted(p.relative_to(release_dir).as_posix() for p in release_dir.rglob("*") if p.is_file())
    sums = build_sha256sums(release_dir, files)
    (release_dir / "SHA256SUMS").write_bytes(sums)
    (release_dir / "SHA256SUMS.sig").write_text(sign_checksums(sums, private), encoding="ascii")
    tarball = tmp_path / "packed.tar.gz"
    subprocess.run([TAR, "-czf", tarball.name, "-C", str(release_dir), "."], check=True, cwd=tmp_path)
    return {"dir": release_dir, "public": public, "tarball": tarball, "tmp": tmp_path}


def _push(release, *extra, fake=False, env=None, robot="rosy-e4us.local", plan=False):
    tmp = release["tmp"]
    args = ["-Robot", robot, "-Tarball", str(release["tarball"]), "-PublicKeyPath", str(release["public"]), *extra]
    if plan:
        args.append("-PrintCommands")
    if fake:
        (tmp / "fake-ssh.ps1").write_text(FAKE_SSH, encoding="ascii")
        args += ["-SshExe", str(tmp / "fake-ssh.ps1"), "-ScpExe", str(tmp / "fake-ssh.ps1")]
    environ = dict(os.environ, USERNAME="livs", COMPUTERNAME="OPS-PC", LOCALAPPDATA=str(tmp / "localappdata"),
                   ROSY_SCRATCH=str(tmp / "scratch"), ROSY_FAKE_LOG=str(tmp / "ssh.log"), **(env or {}))
    environ.pop("ROSY_API_TOKEN", None)
    done = subprocess.run([POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(SCRIPT), *args],
                          capture_output=True, text=True, timeout=120, env=environ)
    log = tmp / "ssh.log"
    return done, (log.read_text(encoding="utf-8").splitlines() if log.exists() else [])


def _audit(release) -> list[dict]:
    files = list((release["tmp"] / "scratch").rglob("rollout.jsonl"))
    return [json.loads(line) for f in files for line in f.read_text(encoding="utf-8").splitlines()]


def test_the_precheck_runs_after_the_upload_and_right_before_the_switch(release):
    done, _ = _push(release, *FORCE, plan=True)

    assert done.returncode == 0, done.stderr
    roles = [(s["role"], " ".join(s["arguments"])) for s in json.loads(done.stdout)["plan"]]
    index = next(i for i, (role, _) in enumerate(roles) if role == "force-precheck")
    assert PRECHECK in roles[index][1] and "sudo -n python3" in roles[index][1]
    assert "rosy-release-unpack.sh" in roles[index - 1][1]
    assert "activate-release.sh" in roles[index + 1][1]


def test_an_ordinary_push_has_no_precheck_step(release):
    done, _ = _push(release, plan=True)

    assert done.returncode == 0, done.stderr
    assert all(s["role"] != "force-precheck" for s in json.loads(done.stdout)["plan"])


@pytest.mark.parametrize("extra, message", [
    (["-ForceUpdate", "-Reason", "why"], "-ExpectReleaseId"),
    (["-ForceUpdate", "-ExpectReleaseId", RELEASE_ID], "-Reason"),
    (["-ForceUpdate", "-ExpectReleaseId", RELEASE_ID, "-Reason", "no;semicolon"], "-Reason"),
    (["-ForceUpdate", "-ExpectReleaseId", "2026.11.09-002", "-Reason", "why"], "does not match"),
    (["-ExpectReleaseId", RELEASE_ID], "belong to -ForceUpdate"),
])
def test_a_force_update_names_the_release_and_the_reason(release, extra, message):
    done, calls = _push(release, *extra, fake=True)

    assert done.returncode != 0 and message in (done.stdout + done.stderr)
    assert calls == []  # refused before the robot is touched


def test_a_force_update_cannot_roll_back(release):
    done, calls = _push(release, *FORCE, "-Rollback", fake=True)

    assert done.returncode != 0 and calls == []


def test_a_free_robot_is_updated_and_the_audit_line_names_who_why_and_which(release):
    done, calls = _push(release, *FORCE, fake=True, env=FREE)

    assert done.returncode == 0, done.stdout + done.stderr
    assert any("activate-release.sh" in c for c in calls)
    audit = _audit(release)
    assert [a["outcome"] for a in audit] == ["requested", "installed"]
    assert audit[-1]["release_id"] == RELEASE_ID and audit[-1]["who"] == "push-livs@OPS-PC"
    assert audit[-1]["reason"] == "bench fix needed (KAN-1)" and audit[-1]["robot"] == "rosy-e4us.local"


def test_a_robot_addressed_by_ip_is_audited_without_the_address(release):
    done, _ = _push(release, *FORCE, fake=True, robot="192.0.2.7", env=FREE)

    assert done.returncode == 0, done.stdout + done.stderr
    assert {a["robot"] for a in _audit(release)} == {"<ip>"}


def test_our_own_push_claim_is_not_a_reason_to_refuse(release):
    done, calls = _push(release, *FORCE, fake=True, env={
        "ROSY_FAKE_PRECHECK_RC": "3", "ROSY_FAKE_PRECHECK_OUT": "claim held by push-livs@OPS-PC"})

    assert done.returncode == 0, done.stdout + done.stderr
    assert any("activate-release.sh" in c for c in calls)


@pytest.mark.parametrize("output", [
    "hold by someone: bench test",                  # an update hold is not bypassed
    "CORE is moving (cmd_vel active)",              # motion
    "battery 31% is below 40% and not charging",    # battery
    "emergency stop is engaged",                    # E-stop
    "claim held by push-livs@OPS-PC; battery 12%",  # our own claim never hides another reason
    "",                                             # busy exit with no reasons is not a pass
])
def test_a_busy_robot_refuses_and_nothing_is_switched(release, output):
    done, calls = _push(release, *FORCE, fake=True, env={"ROSY_FAKE_PRECHECK_RC": "3", "ROSY_FAKE_PRECHECK_OUT": output})

    assert done.returncode != 0
    assert "refused by the robot" in (done.stdout + done.stderr)
    assert not any("activate-release.sh" in c for c in calls)
    assert "rosy_claim.py release" in calls[-1]
    assert [a["outcome"] for a in _audit(release)] == ["requested", "failed"]
    assert _audit(release)[-1]["detail"].startswith("precheck:")


def test_a_robot_that_cannot_run_the_precheck_is_refused(release):
    """An updater older than D-412 (or a broken one) cannot report hold, idle or battery: refuse."""
    done, calls = _push(release, *FORCE, fake=True, env={
        "ROSY_FAKE_PRECHECK_RC": "2", "ROSY_FAKE_PRECHECK_OUT": "rosy_auto_update.py: error: invalid choice"})

    assert done.returncode != 0
    assert "cannot run the updater precheck" in (done.stdout + done.stderr)
    assert not any("activate-release.sh" in c for c in calls)


def test_a_tampered_release_is_still_rejected(release):
    (release["dir"] / "install" / ".rosy-release").write_text("tampered", encoding="utf-8")
    subprocess.run([TAR, "-czf", release["tarball"].name, "-C", str(release["dir"]), "."],
                   check=True, cwd=release["tmp"])
    done, calls = _push(release, *FORCE, fake=True, env=FREE)

    assert done.returncode != 0 and "SIGNATURE_VERIFY_FAILED" in (done.stdout + done.stderr)
    assert calls == []
