"""Rebase signed factory metadata onto a different card without writing any disk."""
import copy
import importlib
import json

import pytest

from test_ab_image_layout import module


FILES = ("etc/fstab", "etc/rosy/os-slot.json", "etc/rosy/os-media.json", "cmdline.txt")


def _source(tmp_path):
    ab = module()
    layout = ab.plan()
    root, boot = tmp_path / "root", tmp_path / "boot"
    (root / "etc/rosy").mkdir(parents=True)
    boot.mkdir()
    (root / "etc/fstab").write_text("LABEL=writable / ext4 defaults 0 1\nLABEL=system-boot /boot/firmware vfat defaults 0 1\n")
    (boot / "cmdline.txt").write_text("console=tty1 root=LABEL=writable rootwait quiet\n")
    ab.configure_slot(root, boot, layout, "a")
    files = {name: (boot / name if name == "cmdline.txt" else root / name).read_text() for name in FILES}
    return files, layout, ab.plan()


@pytest.mark.parametrize("current", ["a", "b"])
def test_rebase_changes_only_inactive_metadata_and_preserves_target_card_identity(tmp_path, current):
    files, source, card = _source(tmp_path)
    before = copy.deepcopy((files, source, card))
    transform = importlib.import_module("os_slot_metadata").rebase_files
    changed = transform(files, source, card, current)
    target = "b" if current == "a" else "a"
    parts = {p["role"]: p for p in card["partitions"]}
    descriptor = json.loads(changed["etc/rosy/os-slot.json"])
    assert descriptor == dict(schema_version=2, state_schema=1, slot=target,
        root_partuuid=parts["root_" + target]["unique_guid"], data_partuuid=parts["data"]["unique_guid"],
        provision_partuuid=parts["bootstrap"]["unique_guid"])
    assert json.loads(changed["etc/rosy/os-media.json"]) == card
    assert f"PARTUUID={parts['boot_' + target]['unique_guid']} /boot/firmware vfat" in changed["etc/fstab"]
    assert f"root=PARTUUID={descriptor['root_partuuid']}" in changed["cmdline.txt"]
    assert f"rauc.slot={target}" in changed["cmdline.txt"]
    assert "console=tty1" in changed["cmdline.txt"] and "rootwait quiet" in changed["cmdline.txt"]
    assert set(changed) == set(FILES)
    assert (files, source, card) == before


@pytest.mark.parametrize("case", ["missing_file", "extra_file", "descriptor", "fstab", "cmdline",
    "duplicate_root", "duplicate_marker", "wrong_rauc_slot", "source_layout", "target_layout", "legacy", "slot", "short_root"])
def test_invalid_signed_source_or_target_never_produces_rebased_files(tmp_path, case):
    files, source, card = _source(tmp_path)
    current = "a"
    if case == "missing_file":
        del files["etc/fstab"]
    elif case == "extra_file":
        files["autoboot.txt"] = "boot_partition=3"
    elif case == "descriptor":
        value = json.loads(files["etc/rosy/os-slot.json"])
        value["data_partuuid"] = card["partitions"][-1]["unique_guid"]
        files["etc/rosy/os-slot.json"] = json.dumps(value)
    elif case == "fstab":
        files["etc/fstab"] += "/dev/foreign /mnt ext4 defaults 0 0\n"
    elif case == "cmdline":
        files["cmdline.txt"] = files["cmdline.txt"].replace("ab-v2", "ab-v1")
    elif case == "duplicate_root":
        files["cmdline.txt"] += " root=/dev/foreign"
    elif case == "duplicate_marker":
        files["cmdline.txt"] += " rosy.os_layout=ab-v2"
    elif case == "wrong_rauc_slot":
        files["cmdline.txt"] = files["cmdline.txt"].replace("rauc.slot=a", "rauc.slot=b")
    elif case == "source_layout":
        source["disk_guid"] = card["disk_guid"]
    elif case == "target_layout":
        card["partitions"][3]["unique_guid"] = card["partitions"][4]["unique_guid"]
    elif case == "legacy":
        card["provision_role"] = "boot_a"
    elif case == "slot":
        current = "current"
    else:
        card["partitions"][4]["size_lba"] -= 2048
    before = copy.deepcopy((files, source, card))
    with pytest.raises(ValueError):
        importlib.import_module("os_slot_metadata").rebase_files(files, source, card, current)
    assert (files, source, card) == before
