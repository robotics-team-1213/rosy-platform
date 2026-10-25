"""Recomputed CRCs must not turn malformed GPT structure into accepted media."""
import hashlib
import json
import lzma
import struct
import zlib

import pytest

from test_sd_gpt_layout import gpt_release, verifier, RELEASE, SECTOR, ENTRY_BYTES, _header
from test_sd_image_provenance import signed_image  # noqa: F401


@pytest.mark.parametrize("attack", ["overlap", "attributes", "unused_entry", "foreign_name",
                                    "array_position", "usable_range", "backup_guid", "hybrid_mbr"])
def test_valid_crcs_do_not_override_gpt_structure(gpt_release, verifier, attack):
    dist, public, image, seal, raw, layout = gpt_release
    sectors = len(raw) // SECTOR
    entries = bytearray(raw[2 * SECTOR:2 * SECTOR + ENTRY_BYTES])
    if attack == "overlap":
        struct.pack_into("<Q", entries, 128 + 32, layout["partitions"][0]["start_lba"])
    elif attack == "attributes":
        struct.pack_into("<Q", entries, 48, 1)
    elif attack == "unused_entry":
        entries[6 * 128 + 16] = 1
    elif attack == "foreign_name":
        entries[56:128] = "boot_a".encode("utf-16-le").ljust(72, b"\0")
    primary = _header(1, sectors - 1, 2, entries, sectors)
    backup = _header(sectors - 1, 1, sectors - 33, entries, sectors)
    if attack == "array_position":
        struct.pack_into("<Q", primary, 72, 3)
    elif attack == "usable_range":
        struct.pack_into("<Q", primary, 40, 2)
    elif attack == "backup_guid":
        backup[56] ^= 1
    elif attack == "hybrid_mbr":
        raw[446 + 16 + 4] = 0x83
    for header in (primary, backup):
        struct.pack_into("<I", header, 16, 0)
        struct.pack_into("<I", header, 16, zlib.crc32(header[:92]))
    raw[2 * SECTOR:2 * SECTOR + ENTRY_BYTES] = entries
    raw[-33 * SECTOR:-SECTOR] = entries
    raw[SECTOR:2 * SECTOR], raw[-SECTOR:] = primary, backup
    image.write_bytes(lzma.compress(raw))
    manifest = json.loads((dist / "manifest.json").read_text())
    manifest["image"]["sha256"] = hashlib.sha256(image.read_bytes()).hexdigest()
    (dist / "manifest.json").write_text(json.dumps(manifest))
    seal()
    with pytest.raises(ValueError, match="GPT|LAYOUT"):
        verifier.verify_image_release(dist, public, image, RELEASE)
