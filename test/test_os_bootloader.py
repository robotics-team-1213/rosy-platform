"""Firmware callback files are real; kernel mounts/devices/DT observations are fixture models."""
import importlib
import json
from pathlib import Path
import struct
import subprocess
import sys
import time

import pytest

from test_os_update_state import _state, _begin, _advance, SOURCE_BOOT, TRIAL_BOOT, TRANSACTION


def _boot(tmp_path, monkeypatch, phase=None):
    state, root, path, initial, verified, media = _state(tmp_path, monkeypatch)
    boot = importlib.import_module("os_bootloader")
    state.mount_facts = lambda *args: []  # Synthetic kernel mounts, never hardware acceptance.
    dt = root / "proc/device-tree/chosen/bootloader"
    dt.mkdir(parents=True)
    for name, value in (("partition", 2), ("tryboot", 0)):
        (dt / name).write_bytes(struct.pack(">I", value))
    boot_id = root / "proc/sys/kernel/random/boot_id"
    boot_id.parent.mkdir(parents=True)
    boot_id.write_text(SOURCE_BOOT + "\n")
    config = root / "run/rosy-provision-boot/autoboot.txt"
    config.parent.mkdir(parents=True)
    config.write_bytes(b"[all]\ntryboot_a_b=1\nboot_partition=2\n[tryboot]\nboot_partition=3\n")
    (path.parent / "rauc").mkdir(mode=0o700)
    if phase:
        _begin(state, root, verified, media)
        if phase != "PREPARED": _advance(state, root, phase)
    return boot, state, root, path, config


def _permit(boot, state, root, *, claim=True):
    import rosy_claim
    pending = state.read_state(root)["pending"]
    holder = "os-update:" + TRANSACTION
    if claim:
        rosy_claim.acquire(root, holder, "fixture OS update", 60)
    record = dict(schema_version=1, transaction_id=TRANSACTION, source_boot_id=SOURCE_BOOT,
        target_slot="b", manifest_sha256=pending["verified"]["manifest_sha256"],
        layout_sha256=pending["layout_sha256"], claim_holder=holder,
        expires_monotonic_ns=time.monotonic_ns() + 10_000_000_000)
    path = root / "run/rosy-os-update/arm.json"
    path.parent.mkdir(mode=0o700, parents=True)
    path.write_text(json.dumps(record))
    path.chmod(0o600)
    return path


def _trial(root):
    descriptor = root / "etc/rosy/os-slot.json"
    value = json.loads(descriptor.read_text())
    layout = json.loads((root / "etc/rosy/os-media.json").read_text())
    value.update(slot="b", root_partuuid=next(p["unique_guid"] for p in layout["partitions"] if p["role"] == "root_b"))
    descriptor.write_text(json.dumps(value))
    (root / "proc/cmdline").write_text(f"root=PARTUUID={value['root_partuuid']} rosy.os_layout=ab-v2 rauc.slot=b\n")
    (root / "proc/sys/kernel/random/boot_id").write_text(TRIAL_BOOT + "\n")
    dt = root / "proc/device-tree/chosen/bootloader"
    (dt / "partition").write_bytes(struct.pack(">I", 3))
    (dt / "tryboot").write_bytes(struct.pack(">I", 1))


def test_factory_autoboot_encoding_and_bounded_strict_reader(tmp_path, monkeypatch):
    boot, _, _, _, config = _boot(tmp_path, monkeypatch)
    assert boot.autoboot("a") == config.read_bytes()
    assert boot.parse_autoboot(boot.autoboot("a")) == "a"
    assert boot.parse_autoboot(boot.autoboot("b")) == "b"
    for raw in (b"", config.read_bytes() + b"boot_partition=4\n", b"[all]\nboot_partition=2\n", b"x" * 4096):
        with pytest.raises(ValueError): boot.parse_autoboot(raw)


@pytest.mark.parametrize("field,raw", [("partition", b"3"), ("partition", struct.pack("<I", 2)),
    ("partition", struct.pack(">I", 4)), ("tryboot", struct.pack(">I", 2)), ("tryboot", b"\0"),
    ("tryboot", b"\0\0\0\0\0")])
def test_firmware_properties_are_exact_big_endian_u32_and_match_descriptor(tmp_path, monkeypatch, field, raw):
    boot, _, root, _, _ = _boot(tmp_path, monkeypatch)
    (root / "proc/device-tree/chosen/bootloader" / field).write_bytes(raw)
    with pytest.raises(ValueError, match="OS_BOOT_HOLD"):
        boot.boot_facts(root)


def test_normal_boot_getters_never_change_bootstrap_or_journal(tmp_path, monkeypatch):
    boot, _, root, state, config = _boot(tmp_path, monkeypatch)
    before = state.read_bytes(), config.read_bytes()
    assert boot.invoke(root, ["get-current"]) == "a"
    assert boot.invoke(root, ["get-primary"]) == "a"
    assert boot.invoke(root, ["get-state", "a"]) == "good"
    assert boot.invoke(root, ["get-state", "b"]) == "bad"
    assert boot.invoke(root, ["set-state", "a", "good"]) == ""
    assert (state.read_bytes(), config.read_bytes()) == before


def test_preboot_good_ack_does_not_commit_or_arm(tmp_path, monkeypatch):
    boot, state, root, path, config = _boot(tmp_path, monkeypatch, "INSTALLING")
    _permit(boot, state, root)
    before = path.read_bytes(), config.read_bytes()
    boot.invoke(root, ["set-state", "b", "good"])
    assert boot.invoke(root, ["get-state", "b"]) == "good"
    assert boot.invoke(root, ["get-primary"]) == "a"
    assert (path.read_bytes(), config.read_bytes()) == before


def test_verified_source_arm_is_idempotent_and_trial_reports_target_without_bootstrap_write(tmp_path, monkeypatch):
    boot, state, root, path, config = _boot(tmp_path, monkeypatch, "VERIFIED")
    _permit(boot, state, root)
    boot.invoke(root, ["set-state", "b", "good"])
    before = path.read_bytes(), config.read_bytes()
    for _ in range(2):
        assert boot.invoke(root, ["set-primary", "b"]) == ""
        assert boot.invoke(root, ["get-primary"]) == "b"
    assert (path.read_bytes(), config.read_bytes()) == before
    with state.locked(root) as store: store.transition(TRANSACTION, "ARMED", SOURCE_BOOT)
    _trial(root)
    assert boot.invoke(root, ["get-current"]) == boot.invoke(root, ["get-primary"]) == "b"
    assert boot.invoke(root, ["get-state", "b"]) == "bad"
    boot.invoke(root, ["set-state", "b", "good"])
    assert boot.invoke(root, ["get-state", "b"]) == "good"
    assert config.read_bytes() == before[1]
    assert state.read_state(root)["committed"]["slot"] == "a"


@pytest.mark.parametrize("damage", ["no_permit", "expired", "no_claim", "foreign_manifest", "foreign_layout", "wrong_phase"])
def test_arm_requires_fresh_controller_permit_claim_and_verified_binding(tmp_path, monkeypatch, damage):
    phase = "INSTALLING" if damage == "wrong_phase" else "VERIFIED"
    boot, state, root, path, config = _boot(tmp_path, monkeypatch, phase)
    permit = _permit(boot, state, root, claim=damage != "no_claim")
    if damage == "no_permit": permit.unlink()
    elif damage in ("expired", "foreign_manifest", "foreign_layout"):
        value = json.loads(permit.read_text())
        key = {"expired": "expires_monotonic_ns", "foreign_manifest": "manifest_sha256", "foreign_layout": "layout_sha256"}[damage]
        value[key] = 0 if damage == "expired" else "c" * 64
        permit.write_text(json.dumps(value))
    before = path.read_bytes(), config.read_bytes()
    with pytest.raises(ValueError, match="OS_BOOT_HOLD"):
        boot.invoke(root, ["set-primary", "b"])
    assert (path.read_bytes(), config.read_bytes()) == before
    assert boot.invoke(root, ["get-primary"]) == "a"


def test_normal_reset_does_not_rearm_and_preboot_ack_is_not_trial_ack(tmp_path, monkeypatch):
    boot, state, root, _, config = _boot(tmp_path, monkeypatch, "VERIFIED")
    _permit(boot, state, root)
    boot.invoke(root, ["set-state", "b", "good"])
    boot.invoke(root, ["set-primary", "b"])
    with state.locked(root) as store: store.transition(TRANSACTION, "ARMED", SOURCE_BOOT)
    before = config.read_bytes()
    (root / "proc/sys/kernel/random/boot_id").write_text(TRIAL_BOOT + "\n")
    assert boot.invoke(root, ["get-primary"]) == "a"
    assert boot.invoke(root, ["get-state", "b"]) == "bad"
    with pytest.raises(ValueError): boot.invoke(root, ["set-primary", "b"])
    assert config.read_bytes() == before


def test_bad_ack_revokes_arm_without_touching_bootstrap(tmp_path, monkeypatch):
    boot, state, root, _, config = _boot(tmp_path, monkeypatch, "VERIFIED")
    _permit(boot, state, root)
    boot.invoke(root, ["set-primary", "b"])
    before = config.read_bytes()
    boot.invoke(root, ["set-state", "b", "bad"])
    assert boot.invoke(root, ["get-primary"]) == "a"
    assert config.read_bytes() == before


@pytest.mark.parametrize("argv", [["set-primary", "a"], ["set-state", "a", "bad"],
    ["get-state", "../b"], ["set-primary", "b", "extra"], ["exec", "reboot"]])
def test_unknown_or_committed_slot_mutations_are_rejected(tmp_path, monkeypatch, argv):
    boot, _, root, path, config = _boot(tmp_path, monkeypatch, "VERIFIED")
    before = path.read_bytes(), config.read_bytes()
    with pytest.raises(ValueError): boot.invoke(root, argv)
    assert (path.read_bytes(), config.read_bytes()) == before


def test_installed_frozen_cli_handles_preboot_good_without_mutable_sdk_or_bootstrap_write(tmp_path, monkeypatch):
    from test_os_frozen_firstboot import _prefix, _stage
    boot, state, root, path, config = _boot(tmp_path / "device", monkeypatch, "INSTALLING")
    _permit(boot, state, root)
    prefix = _prefix(tmp_path / "installed")
    _stage(prefix)
    frozen = prefix / "os-bootstrap/native-runtime"
    script = frozen / "rosy-os-bootloader"
    assert script.is_file() and script.stat().st_mode & 0o111 == 0o111
    help_result = subprocess.run([str(script), "--help"], capture_output=True, text=True, timeout=30)
    assert help_result.returncode == 0, help_result.stderr
    for folder in (prefix / "native-runtime", prefix / "deploy/sd"):
        for file in folder.glob("*.py"):
            file.write_text("raise RuntimeError('mutable SDK was imported')\n")
    code = """
import runpy,sys
from pathlib import Path
sys.path.insert(0,str(Path(sys.argv[1]).parent))
import os_update_state
# Model only kernel mounts; execute the installed CLI and all real journal/firmware readers.
os_update_state.mount_facts = lambda *args: []
sys.argv = [sys.argv[1], '--root',sys.argv[2], 'set-state','b','good']
runpy.run_path(sys.argv[0],run_name='__main__')
"""
    before = path.read_bytes(), config.read_bytes()
    result = subprocess.run([sys.executable, "-I", "-B", "-c", code, str(script), str(root)],
        capture_output=True, text=True, cwd=tmp_path, timeout=30)
    assert result.returncode == 0 and result.stdout == "", result.stderr
    assert (path.read_bytes(), config.read_bytes()) == before
    assert boot.invoke(root, ["get-state", "b"]) == "good"


def test_pure_autoboot_codec_needs_no_release_signing_or_linux_runtime_import(tmp_path):
    native = Path(__file__).resolve().parents[1] / "deploy/robot/pinky_pro/native"
    script = """
import sys
sys.path.insert(0,sys.argv[1])
import os_bootloader
assert 'signing' not in sys.modules and 'os_update_state' not in sys.modules
assert os_bootloader.parse_autoboot(os_bootloader.autoboot('b')) == 'b'
"""
    result = subprocess.run([sys.executable, "-I", "-B", "-c", script, str(native)],
                            capture_output=True, text=True, cwd=tmp_path, timeout=30)
    assert result.returncode == 0, result.stderr


def test_arm_recaptures_real_media_after_the_permit_was_issued(tmp_path, monkeypatch):
    boot, state, root, path, config = _boot(tmp_path, monkeypatch, "VERIFIED")
    _permit(boot, state, root)
    size = root / "sys/devices/virtual/block/sda/sda5/size"
    size.write_text(str(int(size.read_text()) - 1))
    before = path.read_bytes(), config.read_bytes()
    with pytest.raises(ValueError, match="kernel partition range"):
        boot.invoke(root, ["set-primary", "b"])
    assert (path.read_bytes(), config.read_bytes()) == before
    assert boot.invoke(root, ["get-primary"]) == "a"


@pytest.mark.parametrize("damage", ["symlink", "hardlink", "wide_mode", "corrupt"])
def test_untrusted_arm_record_is_hold_without_touching_bootstrap(tmp_path, monkeypatch, damage):
    import os
    boot, state, root, _, config = _boot(tmp_path, monkeypatch, "VERIFIED")
    _permit(boot, state, root)
    boot.invoke(root, ["set-primary", "b"])
    arm = root / boot.ARM
    if damage == "symlink": arm.rename(arm.with_suffix(".target")); arm.symlink_to(arm.with_suffix(".target"))
    elif damage == "hardlink": os.link(arm, arm.with_suffix(".alias"))
    elif damage == "wide_mode": arm.chmod(0o644)
    else: arm.write_text("{")
    before = config.read_bytes()
    with pytest.raises(ValueError, match="OS_BOOT_HOLD"):
        boot.invoke(root, ["get-primary"])
    assert config.read_bytes() == before


def test_kernel_device_tree_alias_is_bounded_to_the_real_sysfs_tree(tmp_path, monkeypatch):
    boot, _, root, _, _ = _boot(tmp_path, monkeypatch)
    original = root / "proc/device-tree"
    target = root / "sys/firmware/devicetree/base"
    target.parent.mkdir(parents=True)
    original.rename(target)
    original.symlink_to(target, target_is_directory=True)
    assert boot.boot_facts(root)["partition"] == 2
    original.unlink()
    foreign = root / "fake-firmware"
    foreign.mkdir()
    original.symlink_to(foreign, target_is_directory=True)
    with pytest.raises(ValueError, match="alias escapes"):
        boot.boot_facts(root)


def test_committed_trial_remains_readable_before_the_next_normal_reboot(tmp_path, monkeypatch):
    boot, state, root, _, config = _boot(tmp_path, monkeypatch, "VERIFIED")
    _permit(boot, state, root)
    boot.invoke(root, ["set-primary", "b"])
    with state.locked(root) as store: store.transition(TRANSACTION, "ARMED", SOURCE_BOOT)
    _trial(root)
    with state.locked(root) as store: store.transition(TRANSACTION, "TRIAL", TRIAL_BOOT)
    boot.invoke(root, ["set-state", "b", "good"])
    with state.locked(root) as store:
        store.transition(TRANSACTION, "HEALTHY", TRIAL_BOOT, health_sha256="a" * 64)
        store.transition(TRANSACTION, "COMMIT_INTENT", TRIAL_BOOT)
    # Model the separate commit owner's successful bootstrap publication, not a hardware acceptance.
    config.write_bytes(boot.autoboot("b"))
    with state.locked(root) as store: store.commit(TRANSACTION, TRIAL_BOOT)
    before = config.read_bytes()
    assert boot.invoke(root, ["get-current"]) == boot.invoke(root, ["get-primary"]) == "b"
    assert boot.invoke(root, ["get-state", "b"]) == "good"
    assert config.read_bytes() == before


def test_untracked_other_slot_trial_is_still_hold(tmp_path, monkeypatch):
    boot, _, root, _, config = _boot(tmp_path, monkeypatch)
    _trial(root)
    before = config.read_bytes()
    with pytest.raises(ValueError, match="untracked boot"):
        boot.invoke(root, ["get-primary"])
    assert config.read_bytes() == before
