"""Real state/default/fsync files; trial, media, services and projection are explicit models."""
import hashlib
import importlib
import json
import struct

import pytest

from test_os_update_health import _health
from test_os_update_state import SOURCE_BOOT, TRIAL_BOOT, TRANSACTION

RECOVERY_BOOT = "44444444-4444-4444-8444-444444444444"


class PowerCut(BaseException):
    pass


def _candidate(tmp_path, monkeypatch):
    health, state, root, journal, host, calls, run, data, _, _ = _health(tmp_path, monkeypatch)
    report = health.check(root, TRANSACTION, host=host, run=run)
    pending = state.read_state(root)["pending"]
    digest = hashlib.sha256(health._report_path(root, pending).read_bytes()).hexdigest()
    with state.locked(root) as store:
        store.transition(TRANSACTION, "HEALTHY", TRIAL_BOOT, health_sha256=digest)
    boot = importlib.import_module("os_bootloader")
    boot.invoke(root, ("set-state", "b", "good"))
    owner = importlib.import_module("os_update_commit")
    def capture(r):
        layout = json.loads((r / "etc/rosy/os-media.json").read_text())
        slot = json.loads((r / "etc/rosy/os-slot.json").read_text())["slot"]
        return dict(slot=slot, layout=layout)
    monkeypatch.setattr(owner, "capture", capture)
    return owner, health, state, boot, root, journal, host, calls, run, data, report


def _normal(root, slot):
    descriptor = root / "etc/rosy/os-slot.json"
    value = json.loads(descriptor.read_text())
    layout = json.loads((root / "etc/rosy/os-media.json").read_text())
    value.update(slot=slot, root_partuuid=next(p["unique_guid"] for p in layout["partitions"] if p["role"] == "root_" + slot))
    descriptor.write_text(json.dumps(value))
    (root / "proc/cmdline").write_text(f"root=PARTUUID={value['root_partuuid']} rosy.os_layout=ab-v2 rauc.slot={slot}\n")
    (root / "proc/sys/kernel/random/boot_id").write_text(RECOVERY_BOOT)
    base = root / "proc/device-tree/chosen/bootloader"
    (base / "partition").write_bytes(struct.pack(">I", 2 if slot == "a" else 3))
    (base / "tryboot").write_bytes(struct.pack(">I", 0))


def test_good_ack_and_exact_health_commit_only_after_durable_intent_and_default_readback(tmp_path, monkeypatch):
    owner, _, state, boot, root, _, host, calls, run, _, _ = _candidate(tmp_path, monkeypatch)
    write = owner._write_atomic
    seen = []
    def observed(path, content, mode):
        if path.name == "autoboot.txt":
            assert state.read_state(root)["pending"]["phase"] == "COMMIT_INTENT"
            assert (root / owner.INTENT).is_file()
            seen.append(content)
        return write(path, content, mode)
    monkeypatch.setattr(owner, "_write_atomic", observed)
    result = owner.commit(root, TRANSACTION, host=host, run=run)
    assert result["pending"] is None and result["committed"]["slot"] == "b"
    assert seen == [boot.autoboot("b")]
    assert (root / boot.BOOTSTRAP).read_bytes() == boot.autoboot("b")
    assert not (root / "run/rosy-os-update/motion.env").exists()
    assert ["/usr/bin/systemctl", "stop", "rosy-os-trial-deadline.timer", "rosy-os-trial-deadline.service"] in calls
    assert boot.invoke(root, ("get-current",)) == "b"  # Retained DT tryboot=1 is still a committed boot.


@pytest.mark.parametrize("fault", ["ack_missing", "ack_bad", "ack_phase", "health_hash", "health_service",
    "disabled", "claim", "expired", "media"])
def test_commit_refuses_unknown_or_stale_authority_without_changing_default(tmp_path, monkeypatch, fault):
    owner, health, state, boot, root, journal, host, _, run, data, _ = _candidate(tmp_path, monkeypatch)
    if fault.startswith("ack"):
        path = root / boot.ACK
        if fault == "ack_missing": path.unlink()
        else:
            value = json.loads(path.read_text())
            value["state" if fault == "ack_bad" else "phase"] = "bad" if fault == "ack_bad" else "TRIAL"
            path.write_text(json.dumps(value))
    elif fault == "health_hash":
        value = json.loads(journal.read_text())
        value["pending"]["health_sha256"] = "0" * 64
        journal.write_text(json.dumps(value))
    elif fault == "health_service": data["MainPID"] = "456"
    elif fault == "disabled":
        (root / "var/lib/rosy-device/policy/updates/config.json").write_text('{"enabled":false}')
    elif fault == "claim":
        import rosy_claim
        rosy_claim.release(root, "os-update:" + TRANSACTION)
    elif fault == "expired": monkeypatch.setattr(health, "_now", lambda: 71_000_000_000)
    else:
        monkeypatch.setattr(owner, "capture", lambda r: dict(slot="b", layout={}))
    before = (journal.read_bytes(), (root / boot.BOOTSTRAP).read_bytes())
    with pytest.raises(ValueError): owner.commit(root, TRANSACTION, host=host, run=run)
    assert (journal.read_bytes(), (root / boot.BOOTSTRAP).read_bytes()) == before
    assert (root / "run/rosy-os-update/motion.env").exists()


@pytest.mark.parametrize("publication", ["before", "after"])
@pytest.mark.parametrize("reboot", [False, True])
def test_power_cut_at_default_publication_reconciles_exact_intent_without_rearming(tmp_path, monkeypatch, publication, reboot):
    owner, _, state, boot, root, _, host, calls, run, _, _ = _candidate(tmp_path, monkeypatch)
    actual = owner._write_atomic
    def cut(path, data, mode):
        if path.name != "autoboot.txt": return actual(path, data, mode)
        if publication == "after": actual(path, data, mode)
        raise PowerCut()
    monkeypatch.setattr(owner, "_write_atomic", cut)
    with pytest.raises(PowerCut): owner.commit(root, TRANSACTION, host=host, run=run)
    assert state.read_state(root)["pending"]["phase"] == "COMMIT_INTENT"
    monkeypatch.setattr(owner, "_write_atomic", actual)
    target = "a" if publication == "before" else "b"
    if reboot: _normal(root, target)
    result = owner.recover(root, host=host, run=run)
    if publication == "before" and reboot:
        assert result["committed"]["slot"] == "a" and len(result["failed_versions"]) == 1
    else:
        assert result["committed"]["slot"] == "b" and not result["failed_versions"]
    assert result["pending"] is None
    assert not any("reboot" in command or "set-primary" in command for command in calls)


def test_unknown_bootstrap_after_intent_stays_held_for_offline_repair(tmp_path, monkeypatch):
    owner, _, state, boot, root, journal, host, _, run, _, _ = _candidate(tmp_path, monkeypatch)
    def cut(path, data, mode):
        if path.name == "autoboot.txt": raise PowerCut()
        raise AssertionError("unexpected write")
    monkeypatch.setattr(owner, "_write_atomic", cut)
    with pytest.raises(PowerCut): owner.commit(root, TRANSACTION, host=host, run=run)
    (root / boot.BOOTSTRAP).write_bytes(b"torn bootstrap")
    before = journal.read_bytes()
    with pytest.raises(ValueError): owner.recover(root, host=host, run=run)
    assert journal.read_bytes() == before and state.read_state(root)["pending"] is not None


def test_fake_root_never_uses_live_service_manager_for_commit_or_recovery(tmp_path):
    owner = importlib.import_module("os_update_commit")
    with pytest.raises(ValueError, match="explicit test runner"): owner.commit(tmp_path, TRANSACTION)
    with pytest.raises(ValueError, match="explicit test runner"): owner.recover(tmp_path)


@pytest.mark.parametrize("change", ["expired", "disabled", "media"])
def test_intent_fsync_delay_cannot_extend_health_or_policy_authority(tmp_path, monkeypatch, change):
    owner, health, state, boot, root, _, host, _, run, _, _ = _candidate(tmp_path, monkeypatch)
    save = owner._json_atomic
    def delayed(path, value, mode):
        save(path, value, mode)
        if change == "expired": monkeypatch.setattr(health, "_now", lambda: 71_000_000_000)
        elif change == "disabled":
            (root / "var/lib/rosy-device/policy/updates/config.json").write_text('{"enabled":false}')
        else: monkeypatch.setattr(owner, "capture", lambda r: dict(slot="b", layout={}))
    monkeypatch.setattr(owner, "_json_atomic", delayed)
    with pytest.raises(ValueError): owner.commit(root, TRANSACTION, host=host, run=run)
    assert state.read_state(root)["pending"]["phase"] == "COMMIT_INTENT"
    assert (root / boot.BOOTSTRAP).read_bytes() == boot.autoboot("a")


def test_committed_state_before_cleanup_is_recoverable_on_the_same_boot(tmp_path, monkeypatch):
    import rosy_claim
    owner, _, state, _, root, _, host, _, run, _, _ = _candidate(tmp_path, monkeypatch)
    cleanup = owner._cleanup
    def cut(*args): raise PowerCut()
    monkeypatch.setattr(owner, "_cleanup", cut)
    with pytest.raises(PowerCut): owner.commit(root, TRANSACTION, host=host, run=run)
    assert state.read_state(root)["pending"] is None
    assert rosy_claim.check(root, now=host.now()) is not None
    monkeypatch.setattr(owner, "_cleanup", cleanup)
    assert owner.recover(root, host=host, run=run)["committed"]["slot"] == "b"
    assert rosy_claim.check(root, now=host.now()) is None


def test_preserved_source_recovery_releases_only_its_own_new_boot_claim(tmp_path, monkeypatch):
    import rosy_claim
    owner, _, _, _, root, _, host, _, run, _, _ = _candidate(tmp_path, monkeypatch)
    def cut(*args): raise PowerCut()
    monkeypatch.setattr(owner, "_write_atomic", cut)
    with pytest.raises(PowerCut): owner.commit(root, TRANSACTION, host=host, run=run)
    _normal(root, "a")
    rosy_claim.acquire(root, "os-update:" + TRANSACTION, "recovery fixture", 300, now=host.now())
    owner.recover(root, host=host, run=run)
    assert rosy_claim.check(root, now=host.now()) is None


def test_bootstrap_write_preserves_fat_mount_permission_bits(tmp_path, monkeypatch):
    import os
    owner, _, _, boot, root, _, host, _, run, _, _ = _candidate(tmp_path, monkeypatch)
    target = root / boot.BOOTSTRAP
    target.chmod(0o755)
    chmod = os.chmod
    def fat_chmod(path, mode, *args, **kwargs):
        if str(path).split("/")[-1].startswith(".autoboot.txt.") and mode != 0o755:
            raise PermissionError("modeled Linux FAT rejects changing mount-derived read/execute bits")
        return chmod(path, mode, *args, **kwargs)
    monkeypatch.setattr(os, "chmod", fat_chmod)
    assert owner.commit(root, TRANSACTION, host=host, run=run)["committed"]["slot"] == "b"
    assert target.stat().st_mode & 0o777 == 0o755
