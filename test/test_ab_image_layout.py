"""Offline GPT geometry/state construction; not a boot or physical-disk test."""
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess

import pytest


IMAGE = Path(__file__).resolve().parents[1] / "deploy/robot/pinky_pro/image"
FACTORY = "d951d2aa-a022-4e72-8d56-82fdf428583c"
RELEASE_ID = "2026.10.26-011"


def module():
    spec = importlib.util.spec_from_file_location("ab_image_test", IMAGE / "ab_image_layout.py")
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def test_fixed_geometry_has_two_equal_roots_and_fits_the_32gb_card_class():
    m = module()
    layout = m.plan()
    assert layout["provision_role"] == "bootstrap"
    assert layout["raw_size_bytes"] == 29 * 1024**3
    assert [p["role"] for p in layout["partitions"]] == ["bootstrap", "boot_a", "boot_b", "root_a", "root_b", "data"]
    assert layout["partitions"][3]["size_lba"] == layout["partitions"][4]["size_lba"]
    assert layout["partitions"][-1]["size_lba"] * 512 > 5 * 1024**3
    assert len({p["unique_guid"] for p in layout["partitions"]} | {layout["disk_guid"]}) == 7


@pytest.mark.skipif(shutil.which("sfdisk") is None, reason="sfdisk is required for real GPT construction")
def test_sfdisk_output_roundtrips_the_existing_bounded_gpt_parser(tmp_path):
    m = module()
    layout = m.plan()
    image = tmp_path / "new-regular-image.img"
    with image.open("xb") as handle:
        handle.truncate(layout["raw_size_bytes"])
    result = subprocess.run(["sfdisk", str(image)], input=m.sfdisk_script(layout),
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    with image.open("rb") as handle:
        def read_at(offset, length):
            handle.seek(offset)
            return handle.read(length)
        assert m.parse_gpt(read_at, image.stat().st_size, layout["provision_role"]) == layout
    assert m.filesystem_plan(image, layout) == [(1, "vfat"), (2, "vfat"), (3, "vfat"),
                                               (4, "ext4"), (5, "ext4"), (6, "ext4")]
    changed = json.loads(json.dumps(layout))
    changed["partitions"][3]["unique_guid"] = "06641603-f85c-46ea-886c-c64e7a5edc26"
    with pytest.raises(ValueError, match="GPT"):
        m.filesystem_plan(image, changed)


def test_factory_data_is_explicit_and_has_existing_service_directory_ownership(tmp_path, monkeypatch):
    m = module()
    calls = {}
    monkeypatch.setattr(m.os, "chown", lambda path, uid, gid: calls.update({Path(path).relative_to(tmp_path).as_posix(): (uid, gid)}))
    m.initialize_data(tmp_path, FACTORY, RELEASE_ID)
    assert json.loads((tmp_path / "state/schema.json").read_text()) == {"schema_version": 1, "state_schema": 1}
    assert json.loads((tmp_path / "state/factory.json").read_text())["factory_id"] == FACTORY
    assert not (tmp_path / "state/current.json").exists()
    assert not (tmp_path / "ssh-hostkeys").exists()
    assert json.loads((tmp_path / "os-update/state.json").read_text()) == dict(schema_version=1,
        committed=dict(slot="a", release_id=RELEASE_ID), pending=None, failed_versions=[])
    assert (tmp_path / "os-update/state.json").stat().st_mode & 0o777 == 0o600
    for name in ("os-update", "os-update/rauc", "os-update/staging"):
        assert (tmp_path / name).is_dir()
        assert (tmp_path / name).stat().st_mode & 0o777 == 0o700
    assert calls["core"] == (960, 960)
    assert calls["maps"] == (961, 960)
    assert calls["models"] == (tmp_path.stat().st_uid, 963)
    assert calls["pilot-recordings"] == (963, 960)
    assert calls["operator-ssh"] == (1001, 1001)
    for name, mode in [("core", 0o750), ("maps", 0o2750), ("models", 0o750),
                       ("pilot-recordings", 0o2750), ("operator-ssh", 0o700), ("tls", 0o750)]:
        assert (tmp_path / name).stat().st_mode & 0o7777 == mode
    assert json.loads((tmp_path / "policy/updates/config.json").read_text())["enabled"] is True


@pytest.mark.parametrize("case", ["nonempty", "symlink", "ancestor_symlink", "world_writable", "invalid_factory"])
def test_data_initialization_refuses_existing_state_before_writes(tmp_path, monkeypatch, case):
    m = module()
    root = tmp_path / "data"
    root.mkdir()
    factory = FACTORY
    if case == "nonempty":
        (root / "do-not-touch").write_text("existing data")
    elif case == "symlink":
        alias = tmp_path / "alias"
        alias.symlink_to(root, target_is_directory=True)
        root = alias
    elif case == "ancestor_symlink":
        child = root / "child"
        child.mkdir()
        alias = tmp_path / "alias"
        alias.symlink_to(root, target_is_directory=True)
        root = alias / "child"
    elif case == "world_writable":
        root.chmod(0o777)
    else:
        factory = "not-a-guid"
    monkeypatch.setattr(m.os, "chown", lambda *args: pytest.fail("must preflight before ownership mutation"))
    with pytest.raises(ValueError):
        m.initialize_data(root, factory, RELEASE_ID)
    assert not (root / "state/schema.json").exists()


@pytest.mark.parametrize("release_id", [None, True, "", "latest", "2026.10.26-011/../other"])
def test_factory_os_release_is_required_before_any_data_writes(tmp_path, release_id):
    with pytest.raises(ValueError, match="release"):
        module().initialize_data(tmp_path, FACTORY, release_id)
    assert list(tmp_path.iterdir()) == []


def test_each_slot_uses_its_root_boot_and_the_shared_data_and_provision(tmp_path):
    m = module()
    layout = m.plan()
    original = "LABEL=writable / ext4 defaults 0 1\nLABEL=system-boot /boot/firmware vfat defaults 0 1\n"
    parts = {p["role"]: p for p in layout["partitions"]}
    for slot in ("a", "b"):
        root, boot = tmp_path / ("root-" + slot), tmp_path / ("boot-" + slot)
        (root / "etc/rosy").mkdir(parents=True)
        boot.mkdir()
        (root / "etc/fstab").write_text(original)
        (boot / "cmdline.txt").write_text("console=tty1 root=LABEL=writable rootwait\n")
        m.configure_slot(root, boot, layout, slot)
        descriptor = json.loads((root / "etc/rosy/os-slot.json").read_text())
        assert descriptor["root_partuuid"] == parts["root_" + slot]["unique_guid"]
        assert descriptor["data_partuuid"] == parts["data"]["unique_guid"]
        assert descriptor["schema_version"] == 2
        assert descriptor["provision_partuuid"] == parts["bootstrap"]["unique_guid"]
        fstab = (root / "etc/fstab").read_text()
        assert f"PARTUUID={parts['boot_' + slot]['unique_guid']} /boot/firmware vfat" in fstab
        assert "/var/lib/rosy-device/maps /var/lib/rosy/maps none bind" in fstab
        assert f"PARTUUID={parts['bootstrap']['unique_guid']} /run/rosy-provision-boot vfat" in fstab
        assert "rosy.os_layout=ab-v2" in (boot / "cmdline.txt").read_text()
        import yaml
        fixed = yaml.safe_load((root / "etc/cloud/cloud.cfg.d/99-rosy-fixed-layout.cfg").read_text())
        assert fixed == {"growpart": {"mode": "off"}, "resize_rootfs": False}


@pytest.mark.parametrize("case", ["fstab_extra", "root_missing", "root_duplicate", "already_ab", "slot"])
def test_slot_configuration_rejects_unknown_input_without_partial_replacement(tmp_path, case):
    m = module()
    root, boot = tmp_path / "root", tmp_path / "boot"
    (root / "etc/rosy").mkdir(parents=True)
    boot.mkdir()
    fstab = "LABEL=writable / ext4 defaults 0 1\nLABEL=system-boot /boot/firmware vfat defaults 0 1\n"
    cmdline, slot = "root=LABEL=writable rootwait\n", "a"
    if case == "fstab_extra":
        fstab += "foreign /data ext4 defaults 0 2\n"
    elif case == "root_missing":
        cmdline = "rootwait\n"
    elif case == "root_duplicate":
        cmdline += "root=/dev/foreign\n"
    elif case == "already_ab":
        cmdline = "root=LABEL=writable rosy.os_layout=ab-v1\n"
    else:
        slot = "c"
    (root / "etc/fstab").write_text(fstab)
    (boot / "cmdline.txt").write_text(cmdline)
    with pytest.raises(ValueError):
        m.configure_slot(root, boot, m.plan(), slot)
    assert (root / "etc/fstab").read_text() == fstab
    assert (boot / "cmdline.txt").read_text() == cmdline
    assert not (root / "etc/rosy/os-slot.json").exists()


def test_capacity_includes_current_previous_staging_and_archive_beside_pinned_factory():
    m = module()
    payload = 300 * 1024**2
    required = 4 * payload + 512 * 1024**2
    assert m.capacity_report(required, payload)["reserve_required_bytes"] == required
    with pytest.raises(ValueError, match="capacity"):
        m.capacity_report(required - 1, payload)
