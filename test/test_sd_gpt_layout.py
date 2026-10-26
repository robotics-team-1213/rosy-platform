"""Signed six-role GPT metadata must reach the real SD consumers.

The fixture has a valid partition table, not a bootable Raspberry Pi image.
All files and keys stay under pytest's temporary directory.
"""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import lzma
from pathlib import Path
import struct
import uuid
import zlib

import pytest

from test_sd_image_provenance import RELEASE, signed_image, verifier  # noqa: F401
from test_media_readback import _Card, _windows_mounted, _plant_provisioning

ROOT = Path(__file__).resolve().parents[1]
SECTOR = 512
SECTORS = 8192
ENTRY_BYTES = 128 * 128
BASIC = "ebd0a0a2-b9e5-4433-87c0-68b6b72699c7"
LINUX = "0fc63daf-8483-4772-8e79-3d69d8477de4"
ROLES = ("bootstrap", "boot_a", "boot_b", "root_a", "root_b", "data")
DISK_GUID = str(uuid.uuid5(uuid.NAMESPACE_URL, "rosy-gpt-table-fixture"))


def _header(current, backup, entries_lba, array, sectors=SECTORS):
    header = bytearray(SECTOR)
    struct.pack_into("<8sIIIIQQQQ16sQIII", header, 0,
                     b"EFI PART", 0x10000, 92, 0, 0, current, backup,
                     34, sectors - 34, uuid.UUID(DISK_GUID).bytes_le,
                     entries_lba, 128, 128, zlib.crc32(array))
    struct.pack_into("<I", header, 16, zlib.crc32(header[:92]))
    return header


def _table_image(with_files=False):
    sectors = 32768 if with_files else SECTORS
    part_sectors = 4096 if with_files else 512
    raw = bytearray(sectors * SECTOR)
    raw[446 + 4] = 0xEE
    struct.pack_into("<II", raw, 446 + 8, 1, sectors - 1)
    raw[510:512] = b"\x55\xaa"
    entries = bytearray(ENTRY_BYTES)
    partitions = []
    for index, role in enumerate(ROLES):
        kind = BASIC if index < 3 else LINUX
        unique = str(uuid.uuid5(uuid.NAMESPACE_URL, "rosy-gpt-fixture/" + role))
        start, count = 2048 + index * part_sectors, part_sectors
        struct.pack_into("<16s16sQQQ72s", entries, index * 128,
                         uuid.UUID(kind).bytes_le, uuid.UUID(unique).bytes_le,
                         start, start + count - 1, 0, role.encode("utf-16-le"))
        partitions.append({"role": role, "number": index + 1, "start_lba": start,
                           "size_lba": count, "type_guid": kind, "unique_guid": unique})
        raw[start * SECTOR + 100] = index + 1
        if with_files and index < 3:
            card = _Card()
            filesystem = card.build()[card.part:card.part + count * SECTOR]
            raw[start * SECTOR:(start + count) * SECTOR] = filesystem
    raw[2 * SECTOR:2 * SECTOR + ENTRY_BYTES] = entries
    backup_array = (sectors - 33) * SECTOR
    raw[backup_array:backup_array + ENTRY_BYTES] = entries
    raw[SECTOR:2 * SECTOR] = _header(1, sectors - 1, 2, entries, sectors)
    raw[-SECTOR:] = _header(sectors - 1, 1, sectors - 33, entries, sectors)
    layout = {"schema_version": 1, "scheme": "gpt", "sector_size": SECTOR,
              "disk_guid": DISK_GUID, "raw_size_bytes": len(raw),
              "provision_role": "boot_a", "partitions": partitions}
    return raw, layout


@pytest.fixture
def gpt_release(signed_image):
    return _release(signed_image)


@pytest.fixture
def fat_release(signed_image):
    return _release(signed_image, with_files=True)


def _release(signed_image, with_files=False):
    dist, public, image, seal = signed_image
    raw, layout = _table_image(with_files)
    image.write_bytes(lzma.compress(raw))
    path = dist / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest.update(schema_version=2, layout=layout)
    manifest["image"]["sha256"] = hashlib.sha256(image.read_bytes()).hexdigest()
    path.write_text(json.dumps(manifest), encoding="utf-8")
    seal()
    return dist, public, image, seal, raw, layout


def _rewrite_manifest(case, mutate):
    dist, _, _, seal, _, _ = case
    path = dist / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    mutate(manifest["layout"])
    path.write_text(json.dumps(manifest), encoding="utf-8")
    seal()


def test_signed_gpt_layout_is_returned_by_the_actual_release_verifier(verifier, gpt_release):
    dist, public, image, _, _, layout = gpt_release
    report = verifier.verify_image_release(dist, public, image, RELEASE)
    assert report["layout"] == layout
    assert report["sha256"] == hashlib.sha256(image.read_bytes()).hexdigest()


@pytest.mark.parametrize("field,value", [
    ("schema_version", True), ("sector_size", 4096), ("sector_size", 512.0),
    ("raw_size_bytes", True), ("raw_size_bytes", SECTORS * SECTOR + SECTOR),
    ("provision_role", "bootstrap"), ("provision_role", "boot_b"),
    ("disk_guid", str(uuid.UUID(int=0))), ("executor", "unexpected"),
])
def test_signed_but_wrong_layout_is_rejected(verifier, gpt_release, field, value):
    _rewrite_manifest(gpt_release, lambda layout: layout.__setitem__(field, value))
    dist, public, image, *_ = gpt_release
    with pytest.raises(ValueError, match="LAYOUT|GPT"):
        verifier.verify_image_release(dist, public, image, RELEASE)


@pytest.mark.parametrize("field,value", [
    ("number", True), ("number", "1"), ("start_lba", 1), ("size_lba", -1),
    ("role", "boot_a"), ("unique_guid", str(uuid.UUID(int=0))),
    ("device", "/unexpected/device"),
])
def test_signed_partition_metadata_cannot_override_the_image(verifier, gpt_release, field, value):
    _rewrite_manifest(gpt_release, lambda layout: layout["partitions"][0].__setitem__(field, value))
    dist, public, image, *_ = gpt_release
    with pytest.raises(ValueError, match="LAYOUT|GPT"):
        verifier.verify_image_release(dist, public, image, RELEASE)


@pytest.mark.parametrize("offset", [SECTOR + 16, 2 * SECTOR + 32, SECTORS * SECTOR - SECTOR + 16])
def test_signed_corrupt_primary_or_backup_gpt_is_rejected(verifier, gpt_release, offset):
    dist, public, image, seal, raw, _ = gpt_release
    raw[offset] ^= 1
    image.write_bytes(lzma.compress(raw))
    path = dist / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["image"]["sha256"] = hashlib.sha256(image.read_bytes()).hexdigest()
    path.write_text(json.dumps(manifest), encoding="utf-8")
    seal()
    with pytest.raises(ValueError, match="LAYOUT|GPT"):
        verifier.verify_image_release(dist, public, image, RELEASE)


def test_manifest_changed_after_checksum_verification_is_rejected(verifier, gpt_release, monkeypatch):
    dist, public, image, _, _, _ = gpt_release
    original = verifier.verify_release_checksums

    def change_after_verification(root, key):
        entries, failures = original(root, key)
        assert not failures
        path = dist / "manifest.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest["layout"]["provision_role"] = "bootstrap"
        path.write_text(json.dumps(manifest), encoding="utf-8")
        return entries, failures

    monkeypatch.setattr(verifier, "verify_release_checksums", change_after_verification)
    with pytest.raises(ValueError, match="MANIFEST_CHECKSUM"):
        verifier.verify_image_release(dist, public, image, RELEASE)


@pytest.fixture
def readback():
    path = ROOT / "deploy/robot/pinky_pro/sd/verify-media-readback.py"
    spec = importlib.util.spec_from_file_location("gpt_readback_consumer", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("extra_sectors", [0, 4])
def test_actual_readback_accepts_only_the_image_prefix(readback, gpt_release, tmp_path, extra_sectors):
    _, _, image, _, raw, layout = gpt_release
    device = tmp_path / "card.fixture"
    device.write_bytes(raw + bytes(extra_sectors * SECTOR))
    report = readback.verify(image, str(device), layout=layout)
    assert report["verified"] is True
    assert report["bytes_verified"] == len(raw)
    assert report["image_sha256"] == hashlib.sha256(image.read_bytes()).hexdigest()


@pytest.mark.parametrize("role", ["bootstrap", "boot_a", "boot_b", "root_a", "root_b", "data"])
def test_readback_never_ignores_changes_in_another_partition(readback, gpt_release, tmp_path, role):
    _, _, image, _, raw, layout = gpt_release
    damaged = bytearray(raw)
    part = next(p for p in layout["partitions"] if p["role"] == role)
    damaged[part["start_lba"] * SECTOR + 100] ^= 1
    device = tmp_path / "card.fixture"
    device.write_bytes(damaged)
    with pytest.raises(ValueError):
        readback.verify(image, str(device), layout=layout)


def test_readback_rejects_a_card_shorter_than_the_signed_image(readback, gpt_release, tmp_path):
    _, _, image, _, raw, layout = gpt_release
    device = tmp_path / "card.fixture"
    device.write_bytes(raw[:-SECTOR])
    with pytest.raises(ValueError):
        readback.verify(image, str(device), layout=layout)


def test_readback_rejects_invalid_layout_even_for_byte_identical_media(readback, gpt_release, tmp_path):
    _, _, image, _, raw, layout = gpt_release
    wrong = copy.deepcopy(layout)
    wrong["partitions"][1]["unique_guid"] = wrong["partitions"][0]["unique_guid"]
    device = tmp_path / "card.fixture"
    device.write_bytes(raw)
    with pytest.raises(ValueError, match="LAYOUT|GPT"):
        readback.verify(image, str(device), layout=wrong)


def _mount_fat(device, layout, role, provision=False, corrupt=False):
    card = _Card()
    mounted = _windows_mounted(card, card.build())
    if provision:
        _plant_provisioning(card, mounted)
    if corrupt:
        mounted[card.cluster_offset(3)] ^= 1
    part = next(p for p in layout["partitions"] if p["role"] == role)
    start, length = part["start_lba"] * SECTOR, part["size_lba"] * SECTOR
    device[start:start + length] = mounted[card.part:card.part + length]


@pytest.mark.parametrize("role", ROLES[:3])
def test_windows_mount_changes_are_checked_on_each_fat(readback, fat_release, tmp_path, role):
    _, _, image, _, raw, layout = fat_release
    actual = bytearray(raw)
    _mount_fat(actual, layout, role)
    device = tmp_path / "card.fixture"
    device.write_bytes(actual)
    report = readback.verify(image, str(device), layout=layout)
    assert report["boot_partitions"][role]["mode"] == "files"
    assert report["boot_partitions"][role]["windows_extras"]
    assert report["verified_scope"] == "image_prefix"


@pytest.mark.parametrize("role", ROLES[:3])
def test_a_changed_file_is_rejected_in_every_fat(readback, fat_release, tmp_path, role):
    _, _, image, _, raw, layout = fat_release
    actual = bytearray(raw)
    _mount_fat(actual, layout, role, corrupt=True)
    device = tmp_path / "card.fixture"
    device.write_bytes(actual)
    with pytest.raises(ValueError, match="config.txt"):
        readback.verify(image, str(device), layout=layout)


@pytest.mark.parametrize("role", ROLES[:3])
def test_provisioning_extra_is_permitted_only_on_the_designated_role(readback, fat_release, tmp_path, role):
    _, _, image, _, raw, layout = fat_release
    actual = bytearray(raw)
    _mount_fat(actual, layout, role, provision=True)
    device = tmp_path / "card.fixture"
    device.write_bytes(actual)
    kwargs = dict(layout=layout, allowed_extras=frozenset({"rosy-config.yaml"}))
    if role == "boot_a":
        report = readback.verify(image, str(device), **kwargs)
        assert report["boot_partitions"][role]["provisioning_extras"] == ["rosy-config.yaml"]
    else:
        with pytest.raises(ValueError, match="unexpected entry"):
            readback.verify(image, str(device), **kwargs)


def test_root_stays_byte_exact_after_all_three_fats_change(readback, fat_release, tmp_path):
    _, _, image, _, raw, layout = fat_release
    actual = bytearray(raw)
    for role in ROLES[:3]:
        _mount_fat(actual, layout, role)
    part = layout["partitions"][3]
    actual[part["start_lba"] * SECTOR + 100] ^= 1
    device = tmp_path / "card.fixture"
    device.write_bytes(actual)
    with pytest.raises(ValueError, match="mismatch"):
        readback.verify(image, str(device), layout=layout)


def test_image_replacement_at_layout_inspection_cannot_reuse_the_old_checksum(verifier, gpt_release, monkeypatch):
    dist, public, image, _, raw, _ = gpt_release
    original = verifier.inspect_image

    def replace_then_inspect(path, layout, expected):
        changed = bytearray(raw)
        changed[layout["partitions"][3]["start_lba"] * SECTOR + 100] ^= 1
        image.write_bytes(lzma.compress(changed))
        return original(path, layout, expected)

    monkeypatch.setattr(verifier, "inspect_image", replace_then_inspect)
    with pytest.raises(ValueError, match="LAYOUT.*checksum"):
        verifier.verify_image_release(dist, public, image, RELEASE)


def test_signed_trailing_compressed_bytes_remain_bound(verifier, readback, gpt_release, tmp_path):
    dist, public, image, seal, raw, layout = gpt_release
    image.write_bytes(image.read_bytes() + b"signed bytes after the xz stream")
    path = dist / "manifest.json"
    manifest = json.loads(path.read_text())
    expected = hashlib.sha256(image.read_bytes()).hexdigest()
    manifest["image"]["sha256"] = expected
    path.write_text(json.dumps(manifest))
    seal()
    assert verifier.verify_image_release(dist, public, image, RELEASE)["sha256"] == expected
    device = tmp_path / "card.fixture"
    device.write_bytes(raw)
    assert readback.verify(image, str(device), layout=layout)["image_sha256"] == expected
