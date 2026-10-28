"""Recover access on disposable card trees without provisioning or enabling drive."""
import base64
import importlib.util
import json
import os
from pathlib import Path
import stat
import struct
import sys
import tempfile
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="offline ext4 recovery runs on Linux")

ROOT = Path(__file__).resolve().parents[1]
SD = ROOT / "deploy/robot/pinky_pro/sd"
KEY = "ssh-ed25519 " + base64.b64encode(
    struct.pack(">I", 11) + b"ssh-ed25519" + struct.pack(">I", 32) + b"\x01" * 32
).decode()
OLD_KEY = "ssh-ed25519 " + base64.b64encode(
    struct.pack(">I", 11) + b"ssh-ed25519" + struct.pack(">I", 32) + b"\x02" * 32
).decode() + " old-operator"


@pytest.fixture
def recovery():
    spec = importlib.util.spec_from_file_location("offline_ssh_recovery", SD / "recover-ssh-access.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def card(tmp_path):
    root = tmp_path / "card"
    uid, gid = os.getuid() or 1000, os.getgid() or 1000
    identity = dict(device_uid="8badf00d-1111-4444-8888-000000000001",
                    device_name="rosy-pinky-abcd", robot_number=40,
                    provisioned_release_id="2026.10.18-001", release_id="2026.10.19-001")
    files = {
        "etc/rosy/runtime.env": "\n".join([
            "ROSY_DEVICE_UID=" + identity["device_uid"],
            "ROSY_DEVICE_NAME=" + identity["device_name"], "ROSY_ROBOT_NUMBER=40",
            "ROSY_RUNTIME_MODE=core", "ROSY_IO_DRIVE_ENABLED=false", ""]),
        "var/lib/rosy/provisioning/complete.json": json.dumps(dict(
            schema_version=1, device_uid=identity["device_uid"], device_name=identity["device_name"],
            release_id=identity["provisioned_release_id"], dds={"robot_number": 40})),
        "var/lib/rosy/provisioning/new-device-setup.json": '{"state":"NEW_DEVICE_SETUP"}',
        "etc/passwd": f"rosy:x:{uid}:{gid}:operator:/home/rosy:/bin/bash\n",
        "etc/sudoers.d/60-rosy-operator": "rosy ALL=(ALL) NOPASSWD:ALL\n",
        "home/rosy/.ssh/authorized_keys": "# existing operator\n" + OLD_KEY + "\n",
        "etc/ssh/sshd_config": "PasswordAuthentication no\nPubkeyAuthentication yes\n",
        "etc/rosy/calibration.json": '{"keep":"calibration"}',
    }
    for name, value in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value)
    keys = root / "home/rosy/.ssh/authorized_keys"
    keys.chmod(0o600)
    keys.parent.chmod(0o700)
    if os.geteuid() == 0:
        for path in (keys.parent.parent, keys.parent, keys):
            os.chown(path, uid, gid)
    release = root / "opt/rosy/releases" / identity["release_id"]
    release.mkdir(parents=True)
    (root / "opt/rosy/current").symlink_to("/opt/rosy/releases/" + identity["release_id"])
    return root, identity, keys


@pytest.fixture
def backup(card):
    root, _, _ = card
    for parent in (Path("/dev/shm"), Path(tempfile.gettempdir())):
        if parent.is_dir() and parent.stat().st_dev != root.stat().st_dev:
            with tempfile.TemporaryDirectory(prefix="rosy-ssh-backup-", dir=parent) as directory:
                yield Path(directory)
            return
    pytest.fail("offline recovery test needs a second filesystem for its real backup boundary")


def snapshot(root):
    return {str(path.relative_to(root)): path.read_bytes()
            for path in root.rglob("*") if path.is_file() and not path.is_symlink()}


def test_inspection_is_read_only_and_reports_setup(card, recovery):
    root, identity, _ = card
    before = snapshot(root)
    result = recovery.inspect(root, KEY)
    assert result["device_uid"] == identity["device_uid"]
    assert result["registration_pending"] is True
    assert result["key_present"] is False
    assert result["public_key_fingerprint"].startswith("SHA256:")
    assert snapshot(root) == before


def test_restore_appends_key_backs_up_bytes_and_preserves_every_other_file(card, backup, recovery):
    root, identity, keys = card
    before = snapshot(root)
    result = recovery.apply(root, KEY, backup, identity)
    assert result["state"] == "SSH_KEY_RESTORED_ON_CARD"
    assert result["changed"] is True and result["registration_pending"] is True
    assert KEY in keys.read_text().splitlines() and OLD_KEY in keys.read_text().splitlines()
    assert stat.S_IMODE(keys.stat().st_mode) == 0o600
    saved = Path(result["backup"])
    assert (saved / "authorized_keys.before").read_bytes() == before["home/rosy/.ssh/authorized_keys"]
    receipt = json.loads((saved / "receipt.json").read_text())
    assert receipt["after_sha256"] == result["after_sha256"]
    assert stat.S_IMODE(saved.stat().st_mode) == 0o700
    after = snapshot(root)
    del before["home/rosy/.ssh/authorized_keys"], after["home/rosy/.ssh/authorized_keys"]
    assert after == before


def test_repeat_is_no_write_and_creates_no_extra_backup(card, backup, recovery):
    root, identity, keys = card
    recovery.apply(root, KEY, backup, identity)
    previous = keys.stat().st_mtime_ns, list(backup.iterdir())
    result = recovery.apply(root, KEY, backup, identity)
    assert result["changed"] is False
    assert (keys.stat().st_mtime_ns, list(backup.iterdir())) == previous


def test_missing_authorized_keys_is_restored_without_touching_setup(card, backup, recovery):
    root, identity, keys = card
    keys.unlink()
    result = recovery.apply(root, KEY, backup, identity)
    assert keys.read_text() == KEY + "\n"
    assert result["registration_pending"] is True
    metadata = json.loads((Path(result["backup"]) / "before.json").read_text())
    assert metadata["existed"] is False


@pytest.mark.parametrize("field", ["device_uid", "device_name", "robot_number", "release_id"])
def test_wrong_card_confirmation_cannot_write(card, backup, recovery, field):
    root, identity, _ = card
    expected = dict(identity, **{field: "wrong"})
    before = snapshot(root)
    with pytest.raises(ValueError, match="identity/release"):
        recovery.apply(root, KEY, backup, expected)
    assert snapshot(root) == before and not list(backup.iterdir())


def test_same_filesystem_backup_is_refused_before_writing(card, recovery, tmp_path):
    root, identity, _ = card
    before = snapshot(root)
    with pytest.raises(ValueError, match="different filesystem"):
        recovery.apply(root, KEY, tmp_path, identity)
    assert snapshot(root) == before


@pytest.mark.parametrize("fault", ["symlink", "hardlink", "writable", "missing-account"])
def test_unsafe_key_store_or_missing_account_is_refused(card, backup, recovery, fault, tmp_path):
    root, identity, keys = card
    if fault == "symlink":
        outside = tmp_path / "outside"
        outside.write_text("untouched")
        keys.unlink()
        keys.symlink_to(outside)
    elif fault == "hardlink":
        os.link(keys, keys.with_name("other-link"))
    elif fault == "writable":
        keys.chmod(0o666)
    else:
        (root / "etc/passwd").write_text("root:x:0:0:root:/root:/bin/bash\n")
    before = snapshot(root)
    with pytest.raises(ValueError):
        recovery.apply(root, KEY, backup, identity)
    assert snapshot(root) == before and not list(backup.iterdir())
    if fault == "symlink":
        assert outside.read_text() == "untouched"


def test_invalid_public_key_cannot_create_a_backup(card, backup, recovery):
    root, identity, _ = card
    with pytest.raises(ValueError):
        recovery.apply(root, 'command="sh" ' + KEY, backup, identity)
    assert not list(backup.iterdir())


@pytest.mark.parametrize("present", [False, True])
@pytest.mark.parametrize("directory", ["home/rosy", "home/rosy/.ssh"])
def test_root_readability_does_not_hide_missing_operator_traversal(card, backup, recovery, directory, present):
    root, identity, keys = card
    if present:
        keys.write_text(KEY + "\n")
    target = root / directory
    # Present root-visible metadata without changing host filesystem permissions.
    class CardPath(type(root)):
        def lstat(self):
            value = super().lstat()
            if str(self) == str(target):
                fields = list(value)
                fields[0] = stat.S_IFDIR | 0o600
                return os.stat_result(fields)
            return value
    before = keys.read_bytes()
    with pytest.raises(ValueError, match="directory"):
        recovery.apply(CardPath(root), KEY, backup, identity)
    assert keys.read_bytes() == before and not list(backup.iterdir())


@pytest.mark.parametrize("present", [False, True])
def test_root_readability_does_not_hide_unreadable_operator_keys(card, backup, recovery, monkeypatch, present):
    root, identity, keys = card
    if present:
        keys.write_text(KEY + "\n")
    def root_metadata(descriptor):
        fields = list(os.fstat(descriptor))
        fields[0] = stat.S_IFREG
        return os.stat_result(fields)
    local_os = SimpleNamespace(**vars(os))
    local_os.fstat = root_metadata
    monkeypatch.setattr(recovery, "os", local_os)
    before = keys.read_bytes()
    with pytest.raises(ValueError, match="key file"):
        recovery.apply(root, KEY, backup, identity)
    assert keys.read_bytes() == before and not list(backup.iterdir())


@pytest.mark.parametrize("shared", [False, True])
def test_mounted_card_cannot_share_the_live_root_filesystem(recovery, monkeypatch, shared):
    device = Path("/").stat().st_dev + (0 if shared else 1)
    mounted = SimpleNamespace(stat=lambda: SimpleNamespace(st_dev=device))
    monkeypatch.setattr(recovery.card, "card_root", lambda path: mounted)
    if shared:
        with pytest.raises(ValueError, match="running host"):
            recovery.mounted_card("/mnt/card")
    else:
        assert recovery.mounted_card("/mnt/card") is mounted


@pytest.mark.parametrize("filesystem,source,valid", [
    ("ext4", "/dev/sdb2", True), ("ext4", "overlay", False), ("vfat", "/dev/sdb1", False)])
def test_card_mount_requires_ext4_on_a_block_device(recovery, monkeypatch, tmp_path, filesystem, source, valid):
    local_os = SimpleNamespace(**vars(os))
    local_os.geteuid = lambda: 0
    local_os.path = SimpleNamespace(**vars(os.path))
    local_os.path.ismount = lambda path: True
    monkeypatch.setattr(recovery.card, "os", local_os)
    monkeypatch.setattr(recovery.card, "subprocess", SimpleNamespace(
        run=lambda *args, **kwargs: SimpleNamespace(stdout=f"{filesystem} {source}\n")))
    if valid:
        assert recovery.card.card_root(str(tmp_path)) == tmp_path
    else:
        with pytest.raises(ValueError, match="ext4 block device"):
            recovery.card.card_root(str(tmp_path))


def test_cli_refuses_the_live_system_before_inspecting_keys(recovery):
    assert recovery.main(["--root", "/", "--public-key", "/nonexistent.pub"]) == 2


def test_cli_defaults_to_inspection(card, recovery, monkeypatch, tmp_path, capsys):
    root, _, _ = card
    public = tmp_path / "operator.pub"
    public.write_text(KEY)
    monkeypatch.setattr(recovery, "mounted_card", lambda path: root)
    before = snapshot(root)
    assert recovery.main(["--root", str(root), "--public-key", str(public)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["changed"] is False
    assert snapshot(root) == before
