"""Actual updater policy must follow admitted common state, not a root snapshot."""
import hashlib
import json

import pytest

from auto_update_fakes import device, host, hub, keys, upd, updater
from os_state_fakes import projected_device


@pytest.mark.parametrize("slot", ["a", "b"])
def test_projected_ab_uses_common_policy_despite_sandbox_read_only_mounts(device, host, hub, monkeypatch, slot):
    common, _, _ = projected_device(device, monkeypatch, slot=slot)
    worker = updater(host, hub)
    assert worker._config()["enabled"] is False
    worker._save_state(dict(applying="slot-a-release"))
    assert json.loads((device / "var/lib/rosy/updates/state.json").read_text())["applying"] == "slot-a-release"
    assert not (common / "policy/updates/state.json").exists()


@pytest.mark.parametrize("change", ["runtime", "runtime_mode", "live_hostname", "hardware",
    "shared_mount_id", "shared_subpath", "login_tombstone", "tls_pending", "setup"])
def test_actual_updater_rechecks_root_projection_and_robot_authority(device, host, hub, monkeypatch, change):
    common, host_table, _ = projected_device(device, monkeypatch)
    worker = updater(host, hub)
    assert worker._config()["enabled"] is False
    if change == "runtime":
        (device / "etc/rosy/runtime.env").write_text("FOREIGN=1\n")
    elif change == "runtime_mode":
        (device / "etc/rosy/runtime.env").chmod(0o644)
    elif change == "live_hostname":
        (device / "proc/sys/kernel/hostname").write_text("other-robot\n")
    elif change == "hardware":
        (device / "proc/device-tree/serial-number").write_bytes(b"10000000abcdef02\0")
    elif change == "shared_mount_id":
        lines = host_table.read_text().splitlines()
        for i, line in enumerate(lines):
            if " /home/rosy/.ssh " in line:
                fields = line.split()
                fields[0] = str(int(fields[0]) + 500)
                lines[i] = " ".join(fields)
        host_table.write_text("\n".join(lines) + "\n")
    elif change == "shared_subpath":
        host_table.write_text(host_table.read_text().replace("/operator-ssh /home", "/foreign /home"))
    elif change == "login_tombstone":
        (device / "etc/rosy/login-policy.json").write_text("{}")
    elif change == "tls_pending":
        (common / "state/tls-pending.json").write_text("{}")
    elif change == "setup":
        (device / "var/lib/rosy/provisioning/new-device-setup.json").write_text("{}")
    with pytest.raises(upd.UpdateError, match="OS_STATE_HOLD"):
        worker._config()


def test_actual_updater_remains_admitted_after_settings_owner_commit(device, host, hub, monkeypatch):
    projected_device(device, monkeypatch)
    from os_state_config import configuration_update
    with configuration_update(device) as update:
        update.stage("etc/rosy/login-policy.json", b'{"ssh_password_login":false}\n', 0o600)
        update.commit()
    assert updater(host, hub)._config()["enabled"] is False


def test_ab_hold_set_and_unlink_use_shared_policy_but_history_stays_slot_local(device, host, hub, monkeypatch):
    common, _, _ = projected_device(device, monkeypatch)
    worker = updater(host, hub)
    worker.hold("fixture operator", "fixture maintenance", 1)
    assert (common / "policy/updates/hold.json").is_file()
    assert not (device / "var/lib/rosy/updates/hold.json").exists()
    assert worker._hold()[0] == "active"
    assert worker.release_hold()["released"] is True
    assert not (common / "policy/updates/hold.json").exists()
    assert (device / "var/lib/rosy/updates/history.jsonl").is_file()
    assert not (common / "policy/updates/history.jsonl").exists()


@pytest.mark.parametrize("change", ["missing_data", "wrong_subpath", "wrong_uuid_device",
    "host_read_only", "local_wrong_subpath", "old_mount_id", "old_boot", "old_generation",
    "unsupported_shared_schema", "missing_ready"])
def test_actual_updater_rejects_bad_or_replaced_mount_readiness(device, host, hub, monkeypatch, change):
    common, host_table, local_table = projected_device(device, monkeypatch)
    ready_path = device / "run/rosy-os-state/ready.json"
    ready = json.loads(ready_path.read_text())
    if change == "missing_data":
        host_table.write_text("\n".join(l for l in host_table.read_text().splitlines() if "/var/lib/rosy-device" not in l))
    elif change == "wrong_subpath":
        host_table.write_text(host_table.read_text().replace("8:6 / /var/lib", "8:6 /wrong /var/lib"))
    elif change == "wrong_uuid_device":
        host_table.write_text(host_table.read_text().replace("8:6", "8:9"))
    elif change == "host_read_only":
        host_table.write_text(host_table.read_text().replace(" rw,relatime -", " ro,relatime -"))
    elif change == "local_wrong_subpath":
        local_table.write_text(local_table.read_text().replace("8:6 / /var/lib", "8:6 /wrong /var/lib"))
    elif change == "old_mount_id":
        host_table.write_text(host_table.read_text().replace("106 0", "206 0"))
    elif change == "old_boot":
        ready["boot_id"] = "00b0b33b-469f-44b5-a431-6c18b77a9e16"
    elif change == "old_generation":
        ready["generation"] = "00b0b33b-469f-44b5-a431-6c18b77a9e16"
    elif change == "unsupported_shared_schema":
        (common / "state/schema.json").write_text('{"schema_version":1,"state_schema":2}')
    if change == "missing_ready":
        ready_path.unlink()
    else:
        ready_path.write_text(json.dumps(ready))
    with pytest.raises(upd.UpdateError, match="OS_STATE_HOLD"):
        updater(host, hub)._config()


@pytest.mark.parametrize("name", ["config.json", "hold.json"])
def test_shared_policy_rejects_writable_by_other_users(device, host, hub, monkeypatch, name):
    common, _, _ = projected_device(device, monkeypatch)
    policy = common / "policy/updates" / name
    if not policy.exists():
        policy.write_text("{}", encoding="ascii")
    policy.chmod(0o666)
    worker = updater(host, hub)
    with pytest.raises(upd.UpdateError, match="OS_STATE_HOLD"):
        worker._config() if name == "config.json" else worker._hold()


def test_missing_ab_policy_does_not_reenable_updates_by_legacy_default(device, host, hub, monkeypatch):
    common, _, _ = projected_device(device, monkeypatch)
    (common / "policy/updates/config.json").unlink()
    with pytest.raises(upd.UpdateError, match="OS_STATE_HOLD"):
        updater(host, hub)._config()


def test_same_updater_rechecks_mounts_after_earlier_success(device, host, hub, monkeypatch):
    _, host_table, _ = projected_device(device, monkeypatch)
    worker = updater(host, hub)
    assert worker._config()["enabled"] is False
    host_table.write_text(host_table.read_text().replace("106 0", "206 0"))
    with pytest.raises(upd.UpdateError, match="OS_STATE_HOLD"):
        worker._config()


def test_applying_journal_cannot_bypass_slot_admission(device, host, hub, monkeypatch):
    projected_device(device, monkeypatch)
    worker = updater(host, hub)
    worker._save_state(dict(applying="fixture interrupted release"))
    (device / "etc/rosy/os-slot.json").unlink()
    report = worker.run()
    assert report["phase"] == "error"
    assert "OS_STATE_HOLD" in report["reason"]
    assert host.calls == []


@pytest.mark.parametrize("change", ["different_disk", "wrong_partition", "missing_partition", "wrong_slot"])
def test_partition_roles_must_belong_to_one_disk_and_the_actual_slot(device, host, hub, monkeypatch, change):
    projected_device(device, monkeypatch, split_disk=change == "different_disk")
    if change == "wrong_partition":
        (device / "sys/dev/block/8:6/partition").write_text("7\n", encoding="ascii")
    elif change == "missing_partition":
        (device / "sys/dev/block/8:6/partition").unlink()
    elif change == "wrong_slot":
        descriptor = device / "etc/rosy/os-slot.json"
        layout = json.loads(descriptor.read_text())
        layout["slot"] = "b"
        descriptor.write_text(json.dumps(layout))
        path = device / "run/rosy-os-state/ready.json"
        ready = json.loads(path.read_text())
        ready.update(slot="b", descriptor_sha256=hashlib.sha256(descriptor.read_bytes()).hexdigest())
        path.write_text(json.dumps(ready))
    with pytest.raises(upd.UpdateError, match="OS_STATE_HOLD"):
        updater(host, hub)._config()
