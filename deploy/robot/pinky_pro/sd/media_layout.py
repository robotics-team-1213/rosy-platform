"""Bounded GPT layout checks and compressed image input for SD consumers."""
from __future__ import annotations

import hashlib
import json
import lzma
import os
from pathlib import Path
import struct
import uuid
import zlib


CHUNK_SIZE = 4 * 1024 * 1024
SECTOR = 512
ENTRY_SIZE = 128
MAX_ENTRIES = 128
TABLE_BYTES = ENTRY_SIZE * MAX_ENTRIES
HEAD_BYTES = 2 * SECTOR + TABLE_BYTES
TAIL_BYTES = SECTOR + TABLE_BYTES
MAX_BOOT_BYTES = 512 * 1024 * 1024
XZ_HEADER_MAGIC = b"\xfd7zXZ\x00"
BASIC_DATA = "ebd0a0a2-b9e5-4433-87c0-68b6b72699c7"
LINUX_FS = "0fc63daf-8483-4772-8e79-3d69d8477de4"
ROLES = ("bootstrap", "boot_a", "boot_b", "root_a", "root_b", "data")
LAYOUT_FIELDS = {"schema_version", "scheme", "sector_size", "disk_guid", "raw_size_bytes",
                 "provision_role", "partitions"}
PARTITION_FIELDS = {"role", "number", "start_lba", "size_lba", "type_guid", "unique_guid"}


def _integer(value, name: str, low: int, high: int) -> int:
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"LAYOUT: invalid integer {name}")
    return value


def _guid(value, name: str) -> str:
    try:
        parsed = uuid.UUID(value) if isinstance(value, str) else None
    except ValueError:
        parsed = None
    if parsed is None or not parsed.int or str(parsed) != value:
        raise ValueError(f"LAYOUT: invalid GUID {name}")
    return value


def validate_layout(value: dict) -> dict:
    """Return a detached typed snapshot; unknown fields never become paths."""
    if not isinstance(value, dict) or set(value) != LAYOUT_FIELDS:
        raise ValueError("LAYOUT: unsupported fields")
    _integer(value["schema_version"], "schema_version", 1, 1)
    _integer(value["sector_size"], "sector_size", SECTOR, SECTOR)
    if value["scheme"] != "gpt" or value["provision_role"] not in ("boot_a", "bootstrap"):
        raise ValueError("LAYOUT: unsupported scheme or provision role")
    size = _integer(value["raw_size_bytes"], "raw_size_bytes", HEAD_BYTES + TAIL_BYTES, 2**63 - 1)
    if size % SECTOR:
        raise ValueError("LAYOUT: raw size must be sector aligned")
    disk = _guid(value["disk_guid"], "disk_guid")
    parts = value["partitions"]
    if not isinstance(parts, list) or len(parts) != len(ROLES):
        raise ValueError("LAYOUT: exactly six partitions are required")
    result = []
    guids = {disk}
    previous_end = 1
    for number, (part, role) in enumerate(zip(parts, ROLES), 1):
        if not isinstance(part, dict) or set(part) != PARTITION_FIELDS:
            raise ValueError("LAYOUT: unsupported partition fields")
        _integer(part["number"], "partition number", number, number)
        if part["role"] != role:
            raise ValueError("LAYOUT: partition role/number differs")
        start = _integer(part["start_lba"], "start_lba", 2, size // SECTOR - 2)
        count = _integer(part["size_lba"], "size_lba", 1, size // SECTOR - 2)
        if start <= previous_end or start + count > size // SECTOR - 1:
            raise ValueError("LAYOUT: partitions overlap or exceed the image")
        previous_end = start + count - 1
        kind = _guid(part["type_guid"], "type_guid")
        if kind != (BASIC_DATA if number <= 3 else LINUX_FS):
            raise ValueError("LAYOUT: unsupported partition type")
        if number <= 3 and count * SECTOR > MAX_BOOT_BYTES:
            raise ValueError("LAYOUT: boot FAT exceeds the readback memory budget")
        unique = _guid(part["unique_guid"], "unique_guid")
        if unique in guids:
            raise ValueError("LAYOUT: duplicate GUID")
        guids.add(unique)
        result.append(dict(role=role, number=number, start_lba=start, size_lba=count,
                           type_guid=kind, unique_guid=unique))
    return dict(schema_version=1, scheme="gpt", sector_size=SECTOR, disk_guid=disk,
                raw_size_bytes=size, provision_role=value["provision_role"], partitions=result)


def _header(data: bytes, current: int, backup: int, sectors: int) -> dict:
    if len(data) != SECTOR:
        raise ValueError("GPT: truncated header")
    fields = struct.unpack_from("<8sIIIIQQQQ16sQIII", data)
    magic, revision, length, crc, reserved, here, other, first, last, guid, table, count, width, array_crc = fields
    if (magic != b"EFI PART" or revision != 0x10000 or length != 92 or reserved
            or here != current or other != backup or width != ENTRY_SIZE
            or not 6 <= count <= MAX_ENTRIES):
        raise ValueError("GPT: unsupported header")
    checksum = bytearray(data[:length])
    struct.pack_into("<I", checksum, 16, 0)
    if zlib.crc32(checksum) != crc:
        raise ValueError("GPT: header CRC mismatch")
    table_sectors = (count * width + SECTOR - 1) // SECTOR
    expected_table = 2 if current == 1 else sectors - 1 - table_sectors
    if table != expected_table or not 2 + table_sectors <= first <= last < sectors - 1 - table_sectors:
        raise ValueError("GPT: entry table or usable LBA range differs")
    return dict(guid=str(uuid.UUID(bytes_le=guid)), first=first, last=last,
                table=table, count=count, array_crc=array_crc)


def parse_gpt(read_at, raw_size: int, provision_role: str = "boot_a") -> dict:
    """Read only bounded primary/backup metadata through a random-read callback."""
    sectors = raw_size // SECTOR
    mbr = read_at(0, SECTOR)
    if len(mbr) != SECTOR or mbr[510:512] != b"\x55\xaa":
        raise ValueError("GPT: protective MBR is missing")
    entries = [mbr[446 + 16 * i:462 + 16 * i] for i in range(4)]
    if (entries[0][4] != 0xEE or entries[0][0] != 0
            or struct.unpack_from("<II", entries[0], 8) != (1, min(sectors - 1, 0xFFFFFFFF))
            or any(any(entry) for entry in entries[1:])):
        raise ValueError("GPT: unsupported protective or hybrid MBR")
    primary = _header(read_at(SECTOR, SECTOR), 1, sectors - 1, sectors)
    backup = _header(read_at(raw_size - SECTOR, SECTOR), sectors - 1, 1, sectors)
    if any(primary[key] != backup[key] for key in ("guid", "first", "last", "count", "array_crc")):
        raise ValueError("GPT: mirrored headers differ")
    length = primary["count"] * ENTRY_SIZE
    array = read_at(primary["table"] * SECTOR, length)
    mirror = read_at(backup["table"] * SECTOR, length)
    if len(array) != length or array != mirror or zlib.crc32(array) != primary["array_crc"]:
        raise ValueError("GPT: partition arrays or CRC differ")
    parts = []
    for index in range(primary["count"]):
        entry = array[index * ENTRY_SIZE:(index + 1) * ENTRY_SIZE]
        kind, unique, start, end, attributes, name = struct.unpack("<16s16sQQQ72s", entry)
        if not any(kind):
            if any(entry):
                raise ValueError("GPT: nonempty unused entry")
            continue
        if index >= len(ROLES) or attributes or not primary["first"] <= start <= end <= primary["last"]:
            raise ValueError("GPT: unsupported entry or LBA range")
        try:
            role = name.decode("utf-16-le").rstrip("\0")
        except UnicodeDecodeError as exc:
            raise ValueError("GPT: malformed partition name") from exc
        parts.append(dict(role=role, number=index + 1, start_lba=start, size_lba=end - start + 1,
                          type_guid=str(uuid.UUID(bytes_le=kind)), unique_guid=str(uuid.UUID(bytes_le=unique))))
    return validate_layout(dict(schema_version=1, scheme="gpt", sector_size=SECTOR,
                                disk_guid=primary["guid"], raw_size_bytes=raw_size,
                                provision_role=provision_role, partitions=parts))


class LayoutCapture:
    """Collect at most 34+33 sectors while the existing image pass continues."""

    def __init__(self, layout: dict):
        self.layout = validate_layout(layout)
        self.size = self.layout["raw_size_bytes"]
        self.position = 0
        self.head = bytearray()
        self.tail = bytearray()

    def feed(self, offset: int, data: bytes) -> None:
        end = offset + len(data)
        if offset != self.position or end > self.size:
            raise ValueError("LAYOUT: image size or stream position differs")
        if offset < HEAD_BYTES:
            self.head += data[:min(len(data), HEAD_BYTES - offset)]
        tail_start = self.size - TAIL_BYTES
        if end > tail_start:
            self.tail += data[max(0, tail_start - offset):]
        self.position = end

    def _read_at(self, offset: int, count: int) -> bytes:
        if 0 <= offset and offset + count <= len(self.head):
            return bytes(self.head[offset:offset + count])
        tail_offset = offset - (self.size - TAIL_BYTES)
        if 0 <= tail_offset and tail_offset + count <= len(self.tail):
            return bytes(self.tail[tail_offset:tail_offset + count])
        raise ValueError("GPT: metadata lies outside bounded table regions")

    def finish(self) -> dict:
        if self.position != self.size:
            raise ValueError("LAYOUT: image raw size differs")
        actual = parse_gpt(self._read_at, self.size, self.layout["provision_role"])
        if actual != self.layout:
            raise ValueError("LAYOUT: image GPT differs from signed metadata")
        return actual


def inspect_image(image: Path, layout: dict, expected_sha256: str) -> dict:
    capture = LayoutCapture(layout)
    with image.open("rb") as compressed:
        signed = HashingReader(compressed)
        with lzma.open(signed, "rb") as raw:
            while chunk := raw.read(CHUNK_SIZE):
                capture.feed(capture.position, chunk)
        actual_sha256 = signed.drain()
    if actual_sha256 != expected_sha256:
        raise ValueError("LAYOUT: consumed image differs from authenticated checksum")
    return capture.finish()


def primary_disk_guid(head: bytes) -> str | None:
    """An identity hint only; both GPT copies are checked by inspect_device."""
    if len(head) < 2 * SECTOR or head[SECTOR:SECTOR + 8] != b"EFI PART":
        return None
    backup = struct.unpack_from("<Q", head, SECTOR + 32)[0]
    return _header(head[SECTOR:2 * SECTOR], 1, backup, backup + 1)["guid"]


def inspect_device(handle, layout: dict) -> dict:
    expected = validate_layout(layout)

    def read_at(offset, count):
        handle.seek(offset)
        return handle.read(count)

    actual = parse_gpt(read_at, expected["raw_size_bytes"], expected["provision_role"])
    if actual != expected:
        raise ValueError("LAYOUT: device GPT differs from signed metadata")
    return actual


class HashingReader:
    """File wrapper that SHA-256s every byte handed to its consumer."""

    def __init__(self, raw) -> None:
        self._raw = raw
        self.sha256 = hashlib.sha256()

    def readable(self) -> bool:
        return True

    def read(self, size: int = -1) -> bytes:
        data = self._raw.read(size)
        self.sha256.update(data)
        return data

    def drain(self) -> str:
        """Hash whatever the decompressor left unread (e.g. bytes after the xz stream)."""
        while True:
            data = self.read(CHUNK_SIZE)
            if not data:
                return self.sha256.hexdigest()



def _varint(data: bytes, pos: int) -> tuple[int, int]:
    value = shift = 0
    while True:
        if pos >= len(data) or shift > 63:
            raise ValueError("xz index is corrupt")
        byte = data[pos]
        pos += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, pos
        shift += 7



def xz_raw_size(image: Path) -> int:
    """Uncompressed size from the xz stream indexes, without decompressing."""
    total = 0
    with open(image, "rb") as handle:
        end = handle.seek(0, os.SEEK_END)
        while end > 0:
            handle.seek(end - 4)
            if end >= 4 and handle.read(4) == b"\0\0\0\0":  # stream padding
                end -= 4
                continue
            if end < 24:
                raise ValueError("image is not an xz stream")
            handle.seek(end - 12)
            footer = handle.read(12)
            if footer[10:12] != b"YZ":
                raise ValueError("image does not end with an xz stream footer")
            index_size = (struct.unpack_from("<I", footer, 4)[0] + 1) * 4
            index_start = end - 12 - index_size
            if index_start < 12:
                raise ValueError("xz index is corrupt")
            handle.seek(index_start)
            index = handle.read(index_size)
            if index[:1] != b"\0":
                raise ValueError("xz index is corrupt")
            count, pos = _varint(index, 1)
            blocks = 0
            for _ in range(count):
                unpadded, pos = _varint(index, pos)
                size, pos = _varint(index, pos)
                total += size
                blocks += (unpadded + 3) // 4 * 4
            end = index_start - blocks - 12
            if end < 0:
                raise ValueError("xz index is corrupt")
            handle.seek(end)
            if handle.read(6) != XZ_HEADER_MAGIC:
                raise ValueError("xz stream header is missing")
    return total



def hash_image(image: Path) -> dict[str, object]:
    if image.suffix != ".xz":
        raise ValueError("image must be an xz-compressed raw disk image")

    image_hash = hashlib.sha256()
    hashed = 0
    with lzma.open(image, "rb") as expected:
        while True:
            chunk = expected.read(CHUNK_SIZE)
            if not chunk:
                break
            image_hash.update(chunk)
            hashed += len(chunk)
    return {
        "bytes_hashed": hashed,
        "image_raw_sha256": image_hash.hexdigest(),
    }



def mbr_signature(sector: bytes) -> str | None:
    """The MBR disk signature (bytes 440-443) as 8 hex digits, or None if absent."""
    if len(sector) < 512 or sector[510:512] != b"\x55\xaa":
        return None
    value = struct.unpack_from("<I", sector, 440)[0]
    return f"{value:08x}" if value else None



def raw_mbr_signature(sector: bytes) -> str | None:
    """Bytes 440-443 as 8 hex digits whenever the sector holds an MBR (0x55AA),
    "00000000" included; None when it holds none (a blank or unpartitioned card).
    Only meaningful when the sector was actually read (D-188 review)."""
    if len(sector) < 512 or sector[510:512] != b"\x55\xaa":
        return None
    return f"{struct.unpack_from('<I', sector, 440)[0]:08x}"



def sector_is_blank(sector: bytes) -> bool:
    """True when a full first sector was read and every byte is zero.

    2026-09-24: an interrupted Imager write left sector 0 all zeros, and Get-Disk
    (which -PlanOnly reads) reports such a disk as MBR with signature 1.
    """
    return len(sector) >= 512 and not any(sector[:512])
