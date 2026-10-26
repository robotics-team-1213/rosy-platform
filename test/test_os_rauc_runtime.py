"""Per-install configuration derives device access from fresh admitted media, never a factory UUID."""
import configparser
import importlib
import json

import pytest

from test_ab_image_layout import module
from test_os_media import _card
from test_os_update_manifest import metadata


def _runtime(tmp_path, monkeypatch, slot="a"):
    media, root, _, _, _, _ = _card(tmp_path, monkeypatch, slot)
    m = importlib.import_module("os_rauc_runtime")
    events = []
    value = metadata()
    def verify(*args):
        events.append("verify")
        assert args == (root, root / "bundle.raucb", b"outer", "signature")
        return dict(metadata=value)
    original = media.capture
    def capture(observed):
        events.append("capture")
        return original(observed)
    monkeypatch.setattr(m, "verify_bundle", verify)
    monkeypatch.setattr(m, "capture", capture)
    return m, root, value, events


@pytest.mark.parametrize("slot", ["a", "b"])
def test_runtime_uses_current_card_devices_and_only_inactive_write_permissions(tmp_path, monkeypatch, slot):
    module()
    m, root, _, events = _runtime(tmp_path, monkeypatch, slot)
    result = m.prepare(root, root / "bundle.raucb", b"outer", "signature")
    assert events == ["verify", "capture"]
    assert result["target_slot"] == ("b" if slot == "a" else "a")
    config = configparser.ConfigParser()
    config.read_string(result["configuration"])
    assert config["system"]["bootloader"] == "custom"
    assert config["system"]["activate-installed"] == "false"
    assert config["system"]["bundle-formats"] == "verity"
    assert config["system"]["compatible"] == "rosy-pinky-pro-ab-v2"
    assert config["system"]["data-directory"] == str(root / "var/lib/rosy-device/os-update/rauc")
    assert config["keyring"]["check-purpose"] == "codesign"
    assert config["keyring"]["use-bundle-signing-time"] == "false"
    assert config["keyring"]["allow-partial-chain"] == "false"
    for index, bootname in enumerate(("a", "b")):
        parent, child = config[f"slot.rootfs.{index}"], config[f"slot.boot.{index}"]
        assert parent["bootname"] == bootname
        assert parent["device"] == f"/dev/block/8:{4 + index}"
        assert child["device"] == f"/dev/block/8:{2 + index}"
        assert child["parent"] == f"rootfs.{index}"
        assert parent["allow-mounted"] == child["allow-mounted"] == "false"
        assert parent["install-same"] == child["install-same"] == "true"
        assert parent["resize"] == "false"
    assert set(config["handlers"]) == {"bootloader-custom-backend"}
    assert config["handlers"]["bootloader-custom-backend"] == str(root / "opt/rosy/os-bootstrap/native-runtime/rosy-os-bootloader")
    lines = result["device_dropin"].splitlines()
    target = {"a": (4, 2), "b": (5, 3)}[result["target_slot"]]
    assert {line for line in lines if line.startswith("DeviceAllow=/dev/block/")} == {
        "DeviceAllow=/dev/block/8:0 r", *(f"DeviceAllow=/dev/block/8:{n} rw" for n in target)}
    assert "DevicePolicy=closed" in lines and "DeviceAllow=" in lines
    assert "DeviceAllow=/dev/loop-control rw" in lines
    assert "DeviceAllow=/dev/mapper/control rw" in lines
    assert "DeviceAllow=block-loop rwm" in lines
    assert "DeviceAllow=block-device-mapper rwm" in lines
    assert "/dev/block/8:1" not in result["device_dropin"]
    assert "/dev/block/8:6" not in result["device_dropin"]
    assert not (root / "run/rosy-os-update").exists()


@pytest.mark.parametrize("field,role", [("rootfs_bytes", "root_b"), ("boot_bytes", "boot_b")])
def test_oversized_candidate_does_not_produce_install_configuration(tmp_path, monkeypatch, field, role):
    module()
    m, root, value, _ = _runtime(tmp_path, monkeypatch)
    layout = json.loads((root / "etc/rosy/os-media.json").read_text())
    value[field] = next(p["size_lba"] * 512 + 512 for p in layout["partitions"] if p["role"] == role)
    with pytest.raises(ValueError, match="capacity"):
        m.prepare(root, root / "bundle.raucb", b"outer", "signature")


def test_failed_crypto_does_not_capture_devices(tmp_path, monkeypatch):
    module()
    m, root, _, events = _runtime(tmp_path, monkeypatch)
    def reject(*args):
        raise ValueError("invalid signature")
    monkeypatch.setattr(m, "verify_bundle", reject)
    with pytest.raises(ValueError, match="invalid signature"):
        m.prepare(root, root / "bundle.raucb", b"outer", "signature")
    assert events == []


def test_media_is_recaptured_for_each_preparation(tmp_path, monkeypatch):
    module()
    m, root, _, events = _runtime(tmp_path, monkeypatch)
    m.prepare(root, root / "bundle.raucb", b"outer", "signature")
    part = root / "sys/devices/virtual/block/sda/sda5/size"
    part.write_text(str(int(part.read_text()) - 1))
    with pytest.raises(ValueError, match="kernel partition range"):
        m.prepare(root, root / "bundle.raucb", b"outer", "signature")
    assert events == ["verify", "capture", "verify", "capture"]
