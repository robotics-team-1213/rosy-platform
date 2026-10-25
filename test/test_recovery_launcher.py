"""Installed recovery issuance/privilege closure with no real device commands."""
from dataclasses import asdict, replace
import importlib
import json
import os
from pathlib import Path
import stat
from types import SimpleNamespace

import pytest

NATIVE = Path(__file__).resolve().parents[1] / "deploy/robot/pinky_pro/native"
CERTIFICATE = "-----BEGIN CERTIFICATE-----\ncmVjb3ZlcnktdGVzdC1jZXJ0\n-----END CERTIFICATE-----\n"


@pytest.fixture
def launcher(monkeypatch):
    monkeypatch.syspath_prepend(str(NATIVE))
    return importlib.import_module("recovery_launcher")


@pytest.fixture
def setup(launcher, tmp_path):
    state = launcher.RecoveryState("boot-1", "ap-1", "10.42.0.1", "device-1", "board-1", "board-1",
                                   "site_wifi_unreachable", False, True)
    current = [state]
    accounts = launcher.Accounts(os.getuid(), os.getuid() or 1000, os.getgid(), os.getgid())
    identity = tmp_path / "etc/rosy/device-identity.json"
    identity.parent.mkdir(parents=True)
    identity.write_text(json.dumps({"device_uid": "device-1", "device_name": "rosy-pinky-abcd"}))
    calls = []
    def run(argv):
        calls.append(argv)
        if argv[1] == "req":
            Path(argv[argv.index("-out") + 1]).write_text(CERTIFICATE)
            Path(argv[argv.index("-keyout") + 1]).write_text("private material")
        return SimpleNamespace(returncode=0, stdout="", stderr="")
    def issue(**kwargs):
        return launcher.issue(tmp_path, state_supplier=lambda: current[0], run=run, accounts=accounts,
                              euid=lambda: 0, clock=lambda: 100.0, **kwargs)
    return tmp_path, current, accounts, calls, issue


def test_issue_is_root_only_and_refuses_ineligible_state(launcher, setup):
    root, current, accounts, calls, issue = setup
    with pytest.raises(PermissionError):
        launcher.issue(root, state_supplier=lambda: current[0], accounts=accounts, euid=lambda: 1000)
    current[0] = replace(current[0], firstboot_state="SETUP")
    with pytest.raises(launcher.RecoveryError):
        issue()
    assert calls == []
    assert not (root / launcher.VERIFIER).exists()


def test_issue_persists_private_verifier_and_full_physical_fingerprint(launcher, setup, capsys):
    root, _, accounts, calls, issue = setup
    result = issue()
    record = json.loads((root / launcher.VERIFIER).read_text())
    display = (root / launcher.DISPLAY).read_text()
    assert result["active"] is True and result["boot_id"] == "boot-1"
    assert len(result["fingerprint"].split(":")) == 32
    assert result["fingerprint"] in display and "https://10.42.0.1:8443" in display
    assert "rosy-pinky-abcd" in display and "CODE=" in display
    assert "BOOT_ID=boot-1\n" in display and "AP_EPOCH=ap-1\n" in display
    assert record["scope"] == "network-recovery"
    assert display.split("CODE=", 1)[1].splitlines()[0].replace("-", "") not in json.dumps(record)
    for name in (launcher.VERIFIER, launcher.CERTIFICATE, launcher.PRIVATE_KEY, launcher.DISPLAY):
        info = (root / name).stat()
        assert stat.S_IMODE(info.st_mode) == 0o640 and info.st_uid == accounts.owner_uid
    assert stat.S_IMODE((root / launcher.AUTH_DIR).stat().st_mode) == 0o700
    assert (root / launcher.AUTH_DIR).stat().st_uid == accounts.recovery_uid
    assert "subjectAltName=DNS:rosy-pinky-abcd,IP:10.42.0.1" in calls[0]
    assert capsys.readouterr() == ("", "")


def test_same_ap_restart_preserves_verifier_attempts_and_certificate(launcher, setup):
    root, current, _, calls, issue = setup
    issue()
    before = (root / launcher.VERIFIER).read_bytes()
    attempts = root / launcher.AUTH_DIR / "auth-state.json"
    attempts.write_text('{"attempts":5,"used":true}')
    display = (root / launcher.DISPLAY).read_bytes()
    issue()
    assert (root / launcher.VERIFIER).read_bytes() == before
    assert attempts.read_text() == '{"attempts":5,"used":true}'
    assert (root / launcher.DISPLAY).read_bytes() == display
    assert len([call for call in calls if call[1] == "req"]) == 1
    issue(renew=True)
    assert (root / launcher.VERIFIER).read_bytes() != before
    renewed = (root / launcher.VERIFIER).read_bytes()
    current[0] = replace(current[0], ap_epoch="ap-2")
    issue()
    assert (root / launcher.VERIFIER).read_bytes() != renewed
    assert len([call for call in calls if call[1] == "req"]) == 1


def test_tls_identity_never_silently_rotates_on_moved_identity_or_address(launcher, setup):
    root, current, _, calls, issue = setup
    issue()
    before = (root / launcher.CERTIFICATE).read_bytes()
    current[0] = replace(current[0], ap_address="10.43.0.1", ap_epoch="ap-2")
    with pytest.raises(launcher.RecoveryError, match="tls_identity_mismatch"):
        issue()
    assert (root / launcher.CERTIFICATE).read_bytes() == before
    assert len([call for call in calls if call[1] == "req"]) == 1


def test_failed_certificate_creation_publishes_no_code_or_secret_error(launcher, setup):
    root, current, accounts, _, _ = setup
    def fail(_argv):
        return SimpleNamespace(returncode=1, stdout="private material", stderr="private material")
    with pytest.raises(launcher.RecoveryError, match="tls_unavailable") as error:
        launcher.issue(root, state_supplier=lambda: current[0], run=fail, accounts=accounts, euid=lambda: 0)
    assert "private material" not in str(error.value)
    assert not (root / launcher.DISPLAY).exists()
    assert not (root / launcher.VERIFIER).exists()


@pytest.mark.parametrize("relative", ["var/lib/rosy/network-recovery", "run/rosy-network-recovery", "run/rosy-boot"])
def test_issuer_refuses_symlink_directory_components(launcher, setup, relative):
    root, _, _, calls, issue = setup
    elsewhere = root / "elsewhere"
    elsewhere.mkdir()
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.symlink_to(elsewhere, target_is_directory=True)
    with pytest.raises((OSError, launcher.RecoveryError)):
        issue()
    assert list(elsewhere.iterdir()) == []


def test_frontend_uses_only_socket_snapshot_and_closes_on_verifier_rotation(launcher, setup):
    root, current, accounts, _, issue = setup
    issue()
    calls = []
    def request(command, params):
        calls.append((command, params))
        return {"recovery": asdict(current[0])}
    def serve(coordinator, certificate, private_key, *, assets_dir):
        assert coordinator.active_state() == current[0]
        assert certificate == root / launcher.CERTIFICATE
        assert private_key == root / launcher.PRIVATE_KEY
        assert assets_dir == root / "opt/rosy/native-runtime/recovery-web"
        issue(renew=True)
        assert coordinator.active_state() is None
    with pytest.raises(launcher.RecoveryError, match="credential_rotated"):
        launcher.run_frontend(root, request=request, serve=serve, accounts=accounts, euid=lambda: accounts.recovery_uid)
    assert calls and all(command == "network.status" for command, _ in calls)


def test_frontend_refuses_root_http_and_malformed_socket_snapshot(launcher, setup):
    root, _, accounts, _, issue = setup
    issue()
    with pytest.raises(PermissionError):
        launcher.run_frontend(root, accounts=accounts, euid=lambda: 0)
    with pytest.raises(launcher.RecoveryError):
        launcher.run_frontend(root, accounts=accounts, euid=lambda: accounts.recovery_uid,
                              request=lambda *_: {"recovery": {}}, serve=lambda *_args, **_kwargs: None)
