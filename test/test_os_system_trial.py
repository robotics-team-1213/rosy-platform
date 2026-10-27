"""Offline trial evidence retains actual DT, root, boot, PID1 and deadline bindings."""
import copy
import importlib
import json

import pytest


PREVIOUS = "11111111-1111-4111-8111-111111111111"
BOOT = "22222222-2222-4222-8222-222222222222"
ROOT = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
UNIT = "rosy-system-trial-probe.service"


def module():
    return importlib.import_module("os_system_trial")


def facts():
    return dict(schema_version=1, boot_id=BOOT, root_device="/dev/vdc5", root_argument="root=PARTUUID=" + ROOT,
                slot="b", os_layout="ab-v2", device_tree_partition=3, tryboot=1,
                deadline_active=True, deadline_timer="[Timer]\nOnBootSec=180s\n")


def events():
    probe = dict(_UID="0", _PID="200", _BOOT_ID=BOOT, _SYSTEMD_UNIT=UNIT,
                 SYSLOG_IDENTIFIER="rosy-system-trial-probe", MESSAGE="ROSY_SYSTEM_TRIAL " + json.dumps(facts()))
    started = dict(_PID="1", _BOOT_ID=BOOT, UNIT="rosy-os-trial-deadline.service",
                   MESSAGE_ID="7d4958e842da4a758f6c1cdc7b36dcc5", __MONOTONIC_TIMESTAMP="180000001")
    return [probe, started]


def validate(rows):
    return module().validate("\n".join(json.dumps(row) for row in rows),
                             target_slot="b", root_uuid=ROOT, previous_boot=PREVIOUS)


def test_valid_trial_journal_binds_real_observations_to_the_deadline_boot():
    assert validate(events()) == facts()


@pytest.mark.parametrize("fault", ["tryboot", "partition", "root_device", "root_uuid", "slot", "layout",
    "old_boot", "sender_boot", "uid", "unit", "inactive_timer", "timer_config", "deadline_pid",
    "completed_only", "early_start", "duplicate_probe", "missing_deadline"])
def test_offline_trial_rejects_unbound_or_weaker_evidence(fault):
    rows = copy.deepcopy(events())
    observed = facts()
    changes = dict(tryboot=("tryboot", 0), partition=("device_tree_partition", 2),
                   root_device=("root_device", "/dev/vda1"), root_uuid=("root_argument", "root=PARTUUID=" + PREVIOUS),
                   slot=("slot", "a"), layout=("os_layout", "legacy"), old_boot=("boot_id", PREVIOUS),
                   inactive_timer=("deadline_active", False), timer_config=("deadline_timer", "OnBootSec=179s\n"))
    if fault in changes:
        key, value = changes[fault]
        observed[key] = value
        rows[0]["MESSAGE"] = "ROSY_SYSTEM_TRIAL " + json.dumps(observed)
    elif fault == "sender_boot": rows[0]["_BOOT_ID"] = PREVIOUS
    elif fault == "uid": rows[0]["_UID"] = "1000"
    elif fault == "unit": rows[0]["_SYSTEMD_UNIT"] = "unrelated.service"
    elif fault == "deadline_pid": rows[1]["_PID"] = "99"
    elif fault == "completed_only": rows[1]["MESSAGE_ID"] = "39f53479d3a045ac8e11786248231fbf"
    elif fault == "early_start": rows[1]["__MONOTONIC_TIMESTAMP"] = "179999999"
    elif fault == "duplicate_probe": rows.insert(0, copy.deepcopy(rows[0]))
    elif fault == "missing_deadline": rows.pop()
    with pytest.raises(ValueError):
        validate(rows)


def fixture_root(tmp_path):
    instance = "rosy-system-" + PREVIOUS
    files = {"etc/rosy-system-guest-id": instance, "var/lib/cloud/data/instance-id": instance,
             "proc/1/comm": "systemd\n", "proc/sys/kernel/random/boot_id": BOOT,
             "proc/cmdline": "root=PARTUUID=" + ROOT + " rosy.os_layout=ab-v2 rauc.slot=b",
             "etc/systemd/system/rosy-os-trial-deadline.timer": facts()["deadline_timer"]}
    for relative, text in files.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    for name, value in (("partition", 3), ("tryboot", 1)):
        path = tmp_path / "proc/device-tree/chosen/bootloader" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value.to_bytes(4, "big"))
    return tmp_path


def test_fixture_probe_records_kernel_facts_before_ssh(tmp_path, monkeypatch):
    m = module()
    root = fixture_root(tmp_path)
    monkeypatch.setenv("ROSY_OS_GUEST", "1")
    monkeypatch.setattr(m.os, "geteuid", lambda: 0)
    commands = []
    def run(argv, **kwargs):
        commands.append(argv)
        if argv[0] == "uname": return b"aarch64\n"
        if argv[0] == "findmnt": return b"/dev/vdc5\n"
        if argv[0] == "systemctl": return b"active\n"
        pytest.fail("unexpected probe command")
    assert m.capture(root, run=run) == facts()
    assert all(argv[0] in {"uname", "findmnt", "systemctl"} for argv in commands)


def test_fixture_probe_refuses_an_unowned_root_before_commands(tmp_path, monkeypatch):
    m = module()
    monkeypatch.delenv("ROSY_OS_GUEST", raising=False)
    with pytest.raises(ValueError):
        m.capture(fixture_root(tmp_path), run=lambda *a, **k: pytest.fail("unowned probe ran a command"))


def journal_reader(tmp_path, monkeypatch, *, root=b"/dev/vda1", fail=False):
    m = importlib.import_module("os_system_install")
    calls = []
    monkeypatch.setattr(m, "WORK", tmp_path)
    monkeypatch.setattr(m, "admit", lambda instance: calls.append(["admit"]))
    monkeypatch.setattr(importlib.import_module("os_system_card"), "_guest", lambda: calls.append(["guest"]))
    def layout():
        calls.append(["physical-gpt"])
        return dict(partitions=[dict(role="root_a", number=4), dict(role="root_b", number=5)])
    monkeypatch.setattr(m, "card_layout", layout)
    def run(argv, **kwargs):
        words = list(map(str, argv))
        calls.append(words)
        if words[0] == "findmnt": return root
        if words[0] == "journalctl":
            if fail: raise ValueError("fixture journal read failed")
            return b'{"fixture":"journal"}\n'
        return b""
    monkeypatch.setattr(m, "run", run)
    return m, calls


@pytest.mark.parametrize("source", ["a", "b"])
@pytest.mark.parametrize("fail", [False, True])
def test_journal_reader_mounts_only_target_read_only_and_unmounts_on_failure(tmp_path, monkeypatch, source, fail):
    m, calls = journal_reader(tmp_path, monkeypatch, fail=fail)
    if fail:
        with pytest.raises(ValueError, match="fixture journal read failed"):
            m.journal("fixture-instance", source)
    else:
        assert m.journal("fixture-instance", source) == {"journal": '{"fixture":"journal"}\n'}
    mount = next(call for call in calls if call[0] == "mount")
    assert calls[:2] == [["admit"], ["guest"]] and calls.index(["physical-gpt"]) < calls.index(mount)
    assert mount == ["mount", "-t", "ext4", "-o", "ro,noload,nodev,nosuid,noexec",
                     "/dev/vdc5" if source == "a" else "/dev/vdc4", str(tmp_path / "observed-trial")]
    assert calls[-1] == ["umount", str(tmp_path / "observed-trial")]


def test_journal_reader_refuses_source_slot_as_observer_before_mounting(tmp_path, monkeypatch):
    m, calls = journal_reader(tmp_path, monkeypatch, root=b"/dev/vdc4")
    with pytest.raises(ValueError, match="original cloud observer"):
        m.journal("fixture-instance", "a")
    assert not any(call[0] == "mount" for call in calls)
    assert not (tmp_path / "observed-trial").exists()
