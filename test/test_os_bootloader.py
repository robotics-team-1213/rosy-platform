"""Firmware callback files are real; kernel mounts/devices/DT observations are fixture models."""
import importlib
import json
import struct
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
