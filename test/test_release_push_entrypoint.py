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
import os
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "deploy" / "robot" / "pinky_pro" / "rosy-release-push.ps1"
UNPACK_SCRIPT = ROOT / "deploy" / "robot" / "pinky_pro" / "native" / "rosy-release-unpack.sh"
POWERSHELL = shutil.which("powershell") or shutil.which("pwsh")
TAR = shutil.which("tar")
RELEASE_ID = "2026.09.25-001"


@pytest.fixture(autouse=True)
def _no_real_operator_credentials(tmp_path, monkeypatch):
    # A non-preview push runs the calibration guard, which would read the
    # operator's real DPAPI credentials under LOCALAPPDATA and send a token to
    # the -Robot host. Tests that need other paths set LOCALAPPDATA themselves.
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "localappdata"))
    monkeypatch.delenv("ROSY_API_TOKEN", raising=False)


def _run(args: list[str]) -> subprocess.CompletedProcess:
    command = [POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(SCRIPT), *args]
    env = dict(os.environ)
    env.pop("ROSY_API_TOKEN", None)
    return subprocess.run(command, capture_output=True, text=True, timeout=60, env=env)


@pytest.fixture
def release(tmp_path: Path) -> dict:
    import sys

    sys.path.insert(0, str(ROOT / "deploy" / "robot" / "pinky_pro" / "release"))
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


def _without_claim(plan: list[dict]) -> list[dict]:
    """D-410: the claim brackets every plan and is refreshed after the upload (test_release_push_claim.py)."""
    assert plan[0]["role"] == "claim-acquire" and plan[-1]["role"] == "claim-release"
    return [step for step in plan[1:-1] if step["role"] != "claim-refresh"]


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
def test_print_commands_verifies_locally_and_builds_the_full_push_plan(release):
    completed = _print_push(release)

    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["release_id"] == RELEASE_ID
    assert result["rollback"] is False
    assert result["verification"]["ok"] is True
    assert json.loads(result["verification"]["rejections_json"]) == []

    plan = _without_claim(result["plan"])
    # The core-release check follows activation; D-388: four image-layer sync
    # steps follow CORE readiness.
    assert [step["kind"] for step in plan] == ["ssh", "scp", "scp", "ssh", "ssh", "ssh", "ssh", "ssh"] + ["ssh"] * 4
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
    assert plan[6]["role"] == "core-release-check"
    ready_args = plan[7]["arguments"]
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
    plan = _without_claim(result["plan"])
    assert len(plan) == 1 + 3 + 1 + 1  # rollback, D-388 image-layer sync, core-release check, readiness
    assert plan[0]["arguments"][-1] == "/opt/rosy/native-runtime/rollback-release.sh"
    assert "sudo" in plan[0]["arguments"] and "-n" in plan[0]["arguments"]
    ready_args = plan[-1]["arguments"]
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
    assert _without_claim(result["plan"])[1]["arguments"][-2] == str(tarball)


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
    # Unquoted: Windows PowerShell 5.1 would hand quotes to the C runtime, which
    # strips them before ssh sees the value (test_known_hosts_policy.py).
    assert known_hosts_option == "UserKnownHostsFile=C:\\Users\\test-operator\\AppData\\Local\\Rosy\\known_hosts"


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
def test_known_hosts_paths_with_spaces_are_refused(release, monkeypatch):
    # ssh would split such a path, and no quoting survives PowerShell 5.1 and
    # the C runtime (test_known_hosts_policy.py); refuse instead of checking
    # host keys against the wrong files.
    monkeypatch.setenv("LOCALAPPDATA", "C:\\Users\\test operator\\AppData\\Local")

    completed = _print_push(release)

    assert completed.returncode != 0
    assert "KnownHosts path contains a space" in completed.stderr


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


IMAGE_LAYER_ROLES = ["image-layer-dry-run", "image-layer-apply", "image-layer-restart", "image-layer-core-ready"]


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
def test_push_plan_syncs_the_image_layer_from_the_new_release_after_readiness(release):
    # D-388: dry run, apply, restart what changed, re-check CORE.
    completed = _print_push(release)

    assert completed.returncode == 0, completed.stderr
    plan = _without_claim(json.loads(completed.stdout)["plan"])
    assert [step["role"] for step in plan[-4:]] == IMAGE_LAYER_ROLES
    assert "wait-core-ready.py" in plan[-5]["arguments"][-1]  # after the first readiness check
    script = f"/opt/rosy/releases/{RELEASE_ID}/deploy/robot/native/sync-image-layer.py"
    dry_run, apply, restart, ready = plan[-4:]
    assert dry_run["arguments"][-6:] == ["sudo", "-n", "python3", "-B", script, "--dry-run"]
    assert apply["arguments"][-5:] == ["sudo", "-n", "python3", "-B", script]
    assert restart["arguments"][-4:] == ["sudo", "-n", "systemctl", "restart"]
    assert "<active units the apply changed>" in restart["display"]
    assert "wait-core-ready.py" in ready["arguments"][-1]
    for step in plan[-4:]:
        assert "StrictHostKeyChecking=yes" in step["arguments"]


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
def test_rollback_plan_resyncs_the_image_layer_from_the_release_that_becomes_current():
    completed = _run(["-Robot", "rosy-e4us.local", "-Rollback", "-PrintCommands"])

    assert completed.returncode == 0, completed.stderr
    plan = _without_claim(json.loads(completed.stdout)["plan"])
    # The sync runs BEFORE the readiness check: if the newer release's units do
    # not work with the older one, CORE only becomes ready after the sync.
    assert [step["role"] for step in plan] == ["", *IMAGE_LAYER_ROLES[:3], "core-release-check", ""]
    assert "rollback-release.sh" in plan[0]["arguments"][-1]
    assert "wait-core-ready.py" in plan[-1]["arguments"][-1]
    assert not any("wait-core-ready.py" in " ".join(step["arguments"]) for step in plan[:-1])
    dry_run, apply = plan[1]["arguments"], plan[2]["arguments"]
    assert dry_run[-5:-1] == ["sudo", "-n", "sh", "-c"] and apply[-5:-1] == ["sudo", "-n", "sh", "-c"]
    # current first; the release rolled away from only if current predates D-388.
    assert dry_run[-1].index("/opt/rosy/current/deploy/robot/native/sync-image-layer.py") < \
        dry_run[-1].index("/opt/rosy/previous/deploy/robot/native/sync-image-layer.py")
    assert "--dry-run" in dry_run[-1] and "--dry-run" not in apply[-1]
    assert "IMAGE_LAYER_SYNC_MISSING" in dry_run[-1]
    # PowerShell 5.1 eats embedded double quotes on the way to a native exe.
    assert '"' not in dry_run[-1] and '"' not in apply[-1]


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
@pytest.mark.parametrize("rollback", [False, True])
def test_skip_image_layer_sync_leaves_the_old_plan(release, rollback):
    if rollback:
        completed = _run(["-Robot", "rosy-e4us.local", "-Rollback", "-PrintCommands", "-SkipImageLayerSync"])
    else:
        completed = _print_push(release, "rosy-e4us.local", "-SkipImageLayerSync")

    assert completed.returncode == 0, completed.stderr
    plan = _without_claim(json.loads(completed.stdout)["plan"])
    assert len(plan) == (3 if rollback else 8)
    if rollback:
        assert "wait-core-ready.py" in plan[2]["arguments"][-1]
    # The core-release check is not part of the image-layer sync: it stays.
    assert [step["role"] for step in plan if step["role"]] == ["core-release-check"]


FAKE_SSH = r"""
$all = $args -join ' '
Add-Content -Path $env:ROSY_FAKE_LOG -Value $all
if ($env:ROSY_FAKE_SYNC_MISSING -and $all -match 'IMAGE_LAYER_SYNC_MISSING') {
    'IMAGE_LAYER_SYNC_MISSING'; exit 3
}
if ($all -match '--dry-run') {
    '{"ok": true, "release_id": "R", "changed": ["/etc/systemd/system/rosy-io.service"], "new": [], "unchanged": [], "skipped": [], "restart_units": ["rosy-io.service"]}'
    exit 0
}
if ($all -match 'sync-image-layer') {
    '{"ok": true, "release_id": "R", "changed": ["/etc/systemd/system/rosy-io.service"], "new": [], "unchanged": [], "skipped": [], "restart_units": ["rosy-io.service", "evil;reboot"], "backup_dir": "/var/lib/rosy/image-layer-backup/x", "modprobe_changed": [], "active_targets_affected": [], "next_boot_units": ["rosy-network.service"], "pending_parked": "/var/lib/rosy/image-layer-backup/pending.parked-x.json", "pending_quarantined": null, "corrupt_manifests": ["/var/lib/rosy/image-layer-backup/y/backup-manifest.json"]}'
    exit 0
}
if ($all -match 'CORE_RELEASE_OK') {
    if ($env:ROSY_FAKE_CORE -eq 'stale') { 'CORE_RELEASE_STALE pid=7 cwd=/opt/rosy/releases/P want=/opt/rosy/releases/R'; 'CORE_RESTARTED /opt/rosy/releases/R' }
    elseif ($env:ROSY_FAKE_CORE -eq 'dead') { 'CORE_RELEASE_STALE pid=7 cwd=/opt/rosy/releases/P want=/opt/rosy/releases/R'; 'CORE_RESTART_FAILED' }
    elseif ($env:ROSY_FAKE_CORE -eq 'silent') { }
    else { 'CORE_RELEASE_OK /opt/rosy/releases/R' }
    exit 0
}
if ($all -match 'release.sh') { '{"ok": true, "release_id": "R", "previous": "P"}' }
exit 0
"""


def _fake_run(tmp_path, monkeypatch, args: list[str], *, missing: bool = False, core: str = ""):
    fake = tmp_path / "fake-ssh.ps1"
    fake.write_text(FAKE_SSH, encoding="ascii")
    log = tmp_path / "ssh.log"
    monkeypatch.setenv("ROSY_FAKE_LOG", str(log))
    if missing:
        monkeypatch.setenv("ROSY_FAKE_SYNC_MISSING", "1")
    if core:
        monkeypatch.setenv("ROSY_FAKE_CORE", core)
    completed = _run(["-Robot", "rosy-e4us.local", "-SshExe", str(fake), "-ScpExe", str(fake), *args])
    lines = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
    return completed, lines


@pytest.mark.skipif(POWERSHELL is None or TAR is None, reason="PowerShell and tar are required")
def test_a_push_restarts_only_the_active_rosy_units_the_apply_changed(release, tmp_path, monkeypatch):
    tarball = tmp_path / "packed.tar.gz"
    subprocess.run([TAR, "-czf", tarball.name, "-C", str(release["dir"]), "."], check=True, cwd=tmp_path)

    completed, calls = _fake_run(tmp_path, monkeypatch, [
        "-Tarball", str(tarball), "-PublicKeyPath", str(release["public_key"])])

    assert completed.returncode == 0, completed.stdout + completed.stderr
    restarts = [line for line in calls if "systemctl restart" in line and "CORE_RELEASE" not in line]
    assert len(restarts) == 1 and restarts[0].endswith("systemctl restart rosy-io.service")
    assert sum("wait-core-ready.py" in line for line in calls) == 2
    assert "restarted: rosy-io.service" in completed.stdout
    assert "CORE runs the activated release: /opt/rosy/releases/R" in completed.stdout
    assert "image-layer backup: /var/lib/rosy/image-layer-backup/x" in completed.stdout
    assert "takes effect next boot (not restarted): rosy-network.service" in completed.stdout
    assert not any("rosy-network" in line for line in restarts)
    # Warnings wrap at the console width; compare without whitespace.
    flat = "".join((completed.stdout + completed.stderr).split())
    assert "pending_parked:/var/lib/rosy/image-layer-backup/pending.parked-x.json" in flat
    assert "unreadableandwasignored:/var/lib/rosy/image-layer-backup/y/backup-manifest.json" in flat
    assert "syncpending_quarantined" not in flat  # null is not warned about


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
def test_a_rollback_to_a_release_without_the_sync_warns_and_skips_it(tmp_path, monkeypatch):
    completed, calls = _fake_run(tmp_path, monkeypatch, ["-Rollback"], missing=True)

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "image-layer sync skipped" in completed.stdout + completed.stderr
    assert not any("systemctl restart" in line and "CORE_RELEASE" not in line for line in calls)
    assert sum("IMAGE_LAYER_SYNC_MISSING" in line for line in calls) == 1
    # Readiness is still checked, after the skipped sync.
    assert "wait-core-ready.py" in calls[-2]  # the claim release (D-410) is last


def test_restart_runs_only_rosy_units_the_apply_reported():
    text = SCRIPT.read_text(encoding="utf-8")

    assert "$imageLayer.restart_units" in text
    assert "'^rosy-[A-Za-z0-9-]+\\.(service|path|timer)$'" in text
    assert 'Write-Host "restarted: ' in text


def test_the_push_script_stays_ascii():
    # Windows PowerShell 5.1 reads a BOM-less script as the ANSI code page.
    SCRIPT.read_bytes().decode("ascii")


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
    # deploy/robot/pinky_pro/image/first-boot/rosy-first-boot.py; there is no narrower
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


def _core_release_check(plan: list[dict]) -> dict:
    (step,) = [step for step in plan if step["role"] == "core-release-check"]
    return step


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
@pytest.mark.parametrize("rollback", [False, True])
def test_core_is_checked_against_the_new_release_right_after_the_switch(release, rollback):
    # 2026-10-01 9dfk: the activator returned and readiness passed while CORE
    # still ran the old release. The fixed activator arrives only with the
    # image-layer sync AFTER activation, so the push itself must check: CORE's
    # main process must run from /opt/rosy/current, else restart rosy-core.
    if rollback:
        completed = _run(["-Robot", "rosy-e4us.local", "-Rollback", "-PrintCommands"])
    else:
        completed = _print_push(release)

    assert completed.returncode == 0, completed.stderr
    plan = json.loads(completed.stdout)["plan"]
    roles = [step["role"] for step in plan]
    check = roles.index("core-release-check")
    if rollback:
        # After the image-layer sync: CORE restarted into the older release
        # before its units are back may not start.
        assert roles[check - 3:check] == IMAGE_LAYER_ROLES[:3]
    else:
        # Right after the switch, before the readiness check it protects.
        assert plan[check - 1]["arguments"][-2] == "/opt/rosy/native-runtime/activate-release.sh"
    assert "wait-core-ready.py" in plan[check + 1]["arguments"][-1]
    args = _core_release_check(plan)["arguments"]
    assert args[-5:-1] == ["sudo", "-n", "sh", "-c"]
    script = args[-1]
    for needle in ("MainPID", "rosy-core.service", "/proc/", "/cwd", "readlink -f /opt/rosy/current",
                   "systemctl restart rosy-core.service", "CORE_RELEASE_OK", "CORE_RESTARTED"):
        assert needle in script, needle
    # PowerShell 5.1 eats embedded double quotes on the way to a native exe.
    assert '"' not in script


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
def test_a_stale_core_after_the_switch_is_restarted_and_reported(tmp_path, monkeypatch):
    completed, calls = _fake_run(tmp_path, monkeypatch, ["-Rollback"], missing=True, core="stale")

    assert completed.returncode == 0, completed.stdout + completed.stderr
    flat = "".join((completed.stdout + completed.stderr).split())
    assert "COREwasstillrunning" in flat and "restartedrosy-core" in flat
    # Readiness is checked after the restart.
    check = next(i for i, line in enumerate(calls) if "CORE_RELEASE_OK" in line)
    assert any("wait-core-ready.py" in line for line in calls[check + 1:])


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
def test_a_core_already_on_the_new_release_is_left_alone(tmp_path, monkeypatch):
    completed, _calls = _fake_run(tmp_path, monkeypatch, ["-Rollback"], missing=True)

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "CORE runs the activated release" in completed.stdout
    assert "still running" not in completed.stdout + completed.stderr


@pytest.mark.skipif(POWERSHELL is None or TAR is None, reason="PowerShell and tar are required")
@pytest.mark.parametrize("rollback", [False, True])
def test_a_core_that_does_not_come_back_after_the_restart_fails_the_push_by_name(
        tmp_path, monkeypatch, release, rollback):
    args = ["-Rollback"]
    if not rollback:
        tarball = tmp_path / "packed.tar.gz"
        subprocess.run([TAR, "-czf", tarball.name, "-C", str(release["dir"]), "."], check=True, cwd=tmp_path)
        args = ["-Tarball", str(tarball), "-PublicKeyPath", str(release["public_key"])]
    completed, calls = _fake_run(tmp_path, monkeypatch, args, missing=True, core="dead")

    assert completed.returncode != 0
    flat = "".join((completed.stdout + completed.stderr).split())
    assert "COREdidnotstart" in flat
    assert ("journalctl-urosy-core" if rollback else "-Rollback") in flat
    # Nothing runs after a CORE that is down.
    assert "CORE_RELEASE_OK" in calls[-2]  # then only the claim release (D-410)


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
def test_a_check_that_prints_no_marker_fails_the_push(tmp_path, monkeypatch):
    completed, _calls = _fake_run(tmp_path, monkeypatch, ["-Rollback"], missing=True, core="silent")

    assert completed.returncode != 0
    flat = "".join((completed.stdout + completed.stderr).split())
    assert "couldnotconfirmthatCORErunstheactivatedrelease" in flat


SH = shutil.which("sh")
FAKE_SYSTEMCTL = """#!/bin/sh
case $1 in
  show) echo $FAKE_PID ;;
  restart) [ -n "$FAKE_RESTART_FAIL" ] && exit 1; echo restart >> "$FAKE_LOG" ;;
esac
"""
FAKE_READLINK = """#!/bin/sh
if [ "$1" = -f ]; then v=$FAKE_WANT; else v=$FAKE_CWD; fi
[ -n "$v" ] || exit 1
echo "$v"
"""


@pytest.fixture(scope="module")
def check_script():
    if POWERSHELL is None:
        pytest.skip("PowerShell is required")
    completed = _run(["-Robot", "rosy-e4us.local", "-Rollback", "-PrintCommands"])
    assert completed.returncode == 0, completed.stderr
    script = _core_release_check(json.loads(completed.stdout)["plan"])["arguments"][-1]
    assert script.startswith("'") and script.endswith("'")
    return script[1:-1]


@pytest.mark.skipif(SH is None, reason="sh is required")
@pytest.mark.parametrize("pid, cwd, want, restart_fail, expected", [
    ("42", "/opt/rosy/releases/B", "/opt/rosy/releases/B", "", "CORE_RELEASE_OK /opt/rosy/releases/B"),
    ("42", "/opt/rosy/releases/A", "/opt/rosy/releases/B", "", "CORE_RESTARTED"),
    ("42", "/opt/rosy/releases/B (deleted)", "/opt/rosy/releases/B", "", "CORE_RESTARTED"),
    ("0", "", "/opt/rosy/releases/B", "", "CORE_RESTARTED"),
    ("", "", "/opt/rosy/releases/B", "", "CORE_RESTARTED"),
    ("42", "", "", "", "CORE_RESTARTED"),
    ("42", "/opt/rosy/releases/A", "/opt/rosy/releases/B", "1", "CORE_RESTART_FAILED"),
])
def test_the_remote_check_script_decides_from_the_core_process_cwd(
        tmp_path, check_script, pid, cwd, want, restart_fail, expected):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in (("systemctl", FAKE_SYSTEMCTL), ("readlink", FAKE_READLINK)):
        (bin_dir / name).write_text(body, encoding="ascii", newline="\n")
        (bin_dir / name).chmod(0o755)
    log = tmp_path / "restart.log"
    env = dict(os.environ, FAKE_PID=pid, FAKE_CWD=cwd, FAKE_WANT=want, FAKE_RESTART_FAIL=restart_fail,
               FAKE_LOG=str(log), PATH=str(bin_dir) + os.pathsep + os.environ.get("PATH", ""))

    completed = subprocess.run([SH, "-c", check_script], capture_output=True, text=True, env=env, timeout=30)

    assert completed.returncode == 0, completed.stderr
    assert completed.stderr == ""
    lines = completed.stdout.splitlines()
    assert lines[-1].startswith(expected), completed.stdout
    assert log.exists() == (expected == "CORE_RESTARTED")
    if not expected.startswith("CORE_RELEASE_OK"):
        assert lines[0].startswith("CORE_RELEASE_STALE"), completed.stdout
