"""Operator entry point for pushing a signed native release to a robot without
a card re-flash (D-225 Decision 2.3).

rosy-release-push.ps1 completes the payload-transition path native_release.py
already verifies on-device: it locally re-checks the signature and file
hashes with the repository's own verifier (no crypto reimplemented), then
scp's the release and runs activate-release.sh / rollback-release.sh over
SSH with strict host-key checking. Every remote scp/ssh invocation is built
by one function (Get-RemoteCommandPlan), so -PrintCommands proves exactly
what a real push would send without touching a network.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "deploy" / "robot" / "rosy-release-push.ps1"
UNPACK_SCRIPT = ROOT / "deploy" / "robot" / "rosy-release-unpack.sh"
POWERSHELL = shutil.which("powershell") or shutil.which("pwsh")
TAR = shutil.which("tar")
RELEASE_ID = "2026.09.25-001"


def _run(args: list[str]) -> subprocess.CompletedProcess:
    command = [POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(SCRIPT), *args]
    return subprocess.run(command, capture_output=True, text=True, timeout=60)


@pytest.fixture
def release(tmp_path: Path) -> dict:
    import sys

    sys.path.insert(0, str(ROOT / "deploy" / "release"))
    from signing import build_sha256sums, sign_checksums  # noqa: E402

    private = tmp_path / "test.key"
    public = tmp_path / "pub.pem"
    subprocess.run(["openssl", "genpkey", "-algorithm", "ed25519", "-out", str(private)],
                    check=True, capture_output=True)
    subprocess.run(["openssl", "pkey", "-in", str(private), "-pubout", "-out", str(public)],
                    check=True, capture_output=True)

    release_dir = tmp_path / "release"
    (release_dir / "install").mkdir(parents=True)
    (release_dir / "install" / ".rosy-release").write_text(RELEASE_ID, encoding="utf-8")
    (release_dir / "manifest.json").write_text(
        json.dumps({"release_id": RELEASE_ID, "git_revision": "a" * 40}), encoding="utf-8")

    files = sorted(str(p.relative_to(release_dir).as_posix())
                   for p in release_dir.rglob("*") if p.is_file())
    sums = build_sha256sums(release_dir, files)
    (release_dir / "SHA256SUMS").write_bytes(sums)
    signature = sign_checksums(sums, private)
    (release_dir / "SHA256SUMS.sig").write_text(signature, encoding="ascii")

    return {"dir": release_dir, "public_key": public, "tmp": tmp_path}


def _print_push(release: dict, robot: str = "rosy-e4us.local", *extra: str) -> subprocess.CompletedProcess:
    return _run([
        "-Robot", robot,
        "-ReleaseDir", str(release["dir"]),
        "-PublicKeyPath", str(release["public_key"]),
        "-PrintCommands",
        *extra,
    ])


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
def test_print_commands_verifies_locally_and_builds_the_full_push_plan(release):
    completed = _print_push(release)

    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["release_id"] == RELEASE_ID
    assert result["rollback"] is False
    assert result["verification"]["ok"] is True
    assert json.loads(result["verification"]["rejections_json"]) == []

    plan = result["plan"]
    assert [step["kind"] for step in plan] == ["ssh", "scp", "scp", "ssh", "ssh", "ssh", "ssh"]
    # scp sends the tarball, then the unpack helper.
    assert plan[1]["arguments"][-1].endswith(f"{RELEASE_ID}.tar.gz")
    assert Path(plan[2]["arguments"][-2]) == UNPACK_SCRIPT
    # the unpack step runs under sudo -n with the release id and releases dir.
    unpack_step = plan[4]["arguments"]
    assert unpack_step[-3:] == [RELEASE_ID, unpack_step[-2], "/opt/rosy/releases"]
    assert "sudo" in unpack_step and "-n" in unpack_step
    assert unpack_step[-2].endswith(f"{RELEASE_ID}.tar.gz")
    # activation is the wrapper, by release id, also under sudo -n.
    activate_step = plan[5]["arguments"]
    assert activate_step[-2:] == ["/opt/rosy/native-runtime/activate-release.sh", RELEASE_ID]
    assert "sudo" in activate_step and "-n" in activate_step
    # readiness probe sources the unit's env file (for ROSY_API_PORT, which a
    # plain non-login ssh command otherwise never sees) then reuses the
    # existing on-device bounded probe unchanged.
    ready_args = plan[6]["arguments"]
    assert ready_args[-3:-1] == ["bash", "-lc"]
    assert "/etc/rosy/runtime.env" in ready_args[-1]
    assert "wait-core-ready.py" in ready_args[-1]
    for step in plan:
        assert "-o" in step["arguments"] and "StrictHostKeyChecking=yes" in step["arguments"]
        assert "StrictHostKeyChecking=no" not in step["display"]


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
def test_rollback_plan_skips_the_release_and_only_rolls_back_and_waits(release):
    completed = _run(["-Robot", "rosy-e4us.local", "-Rollback", "-PrintCommands"])

    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["release_id"] is None
    assert result["rollback"] is True
    assert result["verification"] is None
    plan = result["plan"]
    assert len(plan) == 2
    assert plan[0]["arguments"][-1] == "/opt/rosy/native-runtime/rollback-release.sh"
    assert "sudo" in plan[0]["arguments"] and "-n" in plan[0]["arguments"]
    ready_args = plan[1]["arguments"]
    assert ready_args[-3:-1] == ["bash", "-lc"]
    assert "wait-core-ready.py" in ready_args[-1]


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
def test_rollback_rejects_a_release_dir_or_tarball(release):
    completed = _run(["-Robot", "rosy-e4us.local", "-Rollback",
                       "-ReleaseDir", str(release["dir"]), "-PrintCommands"])

    assert completed.returncode != 0
    assert "does not take -ReleaseDir" in completed.stderr


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
def test_exactly_one_of_release_dir_or_tarball_is_required():
    completed = _run(["-Robot", "rosy-e4us.local", "-PrintCommands"])

    assert completed.returncode != 0
    assert "Pass -ReleaseDir" in completed.stderr


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
def test_release_dir_and_tarball_together_are_rejected(release):
    completed = _run(["-Robot", "rosy-e4us.local", "-ReleaseDir", str(release["dir"]),
                       "-Tarball", str(release["dir"] / "SHA256SUMS"), "-PrintCommands"])

    assert completed.returncode != 0
    assert "not both" in completed.stderr


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
def test_a_bad_robot_hostname_is_rejected(release):
    completed = _print_push(release, "evil;rm -rf /")

    assert completed.returncode != 0
    assert "Robot must be a hostname" in completed.stderr


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
def test_robot_is_required():
    completed = _run(["-ReleaseDir", "C:\\nowhere", "-PrintCommands"])

    assert completed.returncode != 0
    assert "Robot is required" in completed.stderr


@pytest.mark.skipif(POWERSHELL is None or TAR is None, reason="PowerShell and tar are required")
def test_a_tarball_is_accepted_as_an_alternative_to_release_dir(release, tmp_path):
    tarball = tmp_path / "packed.tar.gz"
    # A tar archive path starting with a drive letter reads as a "host:path"
    # remote spec to GNU tar (the script's Invoke-Tar works around the same
    # thing); run tar with the archive as a bare, relative filename instead.
    subprocess.run([TAR, "-czf", tarball.name, "-C", str(release["dir"]), "."],
                    check=True, cwd=tmp_path)

    completed = _run(["-Robot", "rosy-e4us.local", "-Tarball", str(tarball),
                       "-PublicKeyPath", str(release["public_key"]), "-PrintCommands"])

    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["release_id"] == RELEASE_ID
    assert result["verification"]["ok"] is True
    assert result["plan"][1]["arguments"][-2] == str(tarball)


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
def test_a_tampered_release_is_rejected_before_any_plan_is_built(release):
    manifest = release["dir"] / "manifest.json"
    manifest.write_text(manifest.read_text(encoding="utf-8") + " ", encoding="utf-8")

    completed = _print_push(release)

    assert completed.returncode != 0
    assert completed.stdout == ""
    assert "SIGNATURE_VERIFY_FAILED" in completed.stderr
    assert "CHECKSUM_MISMATCH" in completed.stderr


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
def test_a_release_missing_its_manifest_is_rejected(release):
    (release["dir"] / "manifest.json").unlink()

    completed = _print_push(release)

    assert completed.returncode != 0
    assert "manifest.json is missing" in completed.stderr


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
def test_default_key_and_known_hosts_paths_are_under_localappdata(release, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", "C:\\Users\\test-operator\\AppData\\Local")

    completed = _print_push(release)

    assert completed.returncode == 0, completed.stderr
    plan = json.loads(completed.stdout)["plan"]
    first_ssh = plan[0]["arguments"]
    assert first_ssh[1] == "C:\\Users\\test-operator\\AppData\\Local\\Rosy\\ssh\\rosy-operator-ed25519"
    known_hosts_option = next(a for a in first_ssh if a.startswith("UserKnownHostsFile="))
    # the value is quoted: ssh parses "-o Key=Value" like an ssh_config line,
    # which splits an unquoted value on whitespace, and a LOCALAPPDATA under
    # "C:\Program Files\..." would otherwise be cut at the first space.
    assert known_hosts_option == 'UserKnownHostsFile="C:\\Users\\test-operator\\AppData\\Local\\Rosy\\known_hosts"'


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
def test_known_hosts_paths_with_spaces_survive_intact(release, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", "C:\\Users\\test operator\\AppData\\Local")

    completed = _print_push(release)

    assert completed.returncode == 0, completed.stderr
    plan = json.loads(completed.stdout)["plan"]
    known_hosts_option = next(a for a in plan[0]["arguments"] if a.startswith("UserKnownHostsFile="))
    assert known_hosts_option == 'UserKnownHostsFile="C:\\Users\\test operator\\AppData\\Local\\Rosy\\known_hosts"'


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
def test_a_real_push_refuses_release_dir_and_names_tarball_as_the_fix(release):
    # Windows tar cannot represent a POSIX exec bit; without -PrintCommands
    # this must fail loudly instead of silently shipping a broken payload.
    completed = _run(["-Robot", "rosy-e4us.local", "-ReleaseDir", str(release["dir"]),
                       "-PublicKeyPath", str(release["public_key"])])

    assert completed.returncode != 0
    assert "-PrintCommands" in completed.stderr
    assert "-Tarball" in completed.stderr
    assert "POSIX exec bits" in completed.stderr


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
def test_release_dir_is_still_accepted_for_a_print_commands_preview(release):
    # covered by _print_push in the other tests too; asserted here by name so
    # the -PrintCommands exception to the -ReleaseDir rule reads as a rule.
    completed = _print_push(release)

    assert completed.returncode == 0, completed.stderr


def test_the_script_never_disables_host_key_checking():
    text = SCRIPT.read_text(encoding="utf-8")

    assert "StrictHostKeyChecking=yes" in text
    assert "StrictHostKeyChecking=no" not in text
    assert "UserKnownHostsFile=" in text


def test_every_remote_command_comes_from_one_function():
    text = SCRIPT.read_text(encoding="utf-8")

    assert text.count("function Get-RemoteCommandPlan") == 1
    # the execution loop below must run the very plan that function returned,
    # not a second, hand-rolled command list.
    assert "$plan = Get-RemoteCommandPlan" in text
    assert "foreach ($step in $plan)" in text


def test_activation_and_rollback_run_under_sudo_and_reuse_the_core_probe():
    # rosy already carries ALL=(ALL) NOPASSWD:ALL in
    # deploy/image/first-boot/rosy-first-boot.py; there is no narrower
    # sudoers rule for these wrappers to run under today.
    text = SCRIPT.read_text(encoding="utf-8")

    assert '"sudo", "-n", $ActivateWrapper' in text
    assert '"sudo", "-n", $RollbackWrapper' in text
    assert "wait-core-ready.py" in text
    assert "$CoreReadyProbe" in text


def test_the_readiness_probe_sources_the_runtime_env_file():
    text = SCRIPT.read_text(encoding="utf-8")

    assert "/etc/rosy/runtime.env" in text
    assert "function Get-CoreReadyArguments" in text


def test_temporary_directories_are_cleaned_up_in_a_finally_block():
    text = SCRIPT.read_text(encoding="utf-8")

    assert "$tempDirsToClean" in text
    assert "} finally {" in text
    assert "Remove-Item -LiteralPath $directory -Recurse -Force" in text


def test_the_unpack_helper_refuses_a_different_release_with_the_same_id():
    text = UNPACK_SCRIPT.read_text(encoding="utf-8")

    assert "RELEASE_CONFLICT" in text
    assert "cmp -s" in text
    assert 'mv -T -- "$TMP" "$TARGET"' in text
