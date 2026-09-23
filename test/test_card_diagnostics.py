"""Read-only card diagnostics without ``wsl --mount`` (D-174 F8, D-175 L2 card path).

The first Pinky boot failure was diagnosed by opening the physical card
read-only, parsing ext4 in pure Python and copying the journal out. These tests
pin the promoted tool: MBR partition selection, the deny-list (Wi-Fi connection
files and the provisioning bundle are never opened), the copied set, the
report, and that the source is never written. The ext4 integration test builds a
real filesystem with ``mkfs.ext4 -d`` (natively or through WSL) and needs the
``ext4`` package; without either it is skipped, the rest runs everywhere.

Fixture secrets are assembled at runtime so this file stays clean for the
tracked-file secret scan.
"""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys

import pytest

from test_media_readback import SECTOR, _Card, _dir_entry, _lfn_entries

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "deploy" / "sd" / "read-card-diagnostics.py"
WIFI_FIXTURE = "home" + "-wifi-" + "pass-5521"


def _tool():
    spec = importlib.util.spec_from_file_location("read_card_diagnostics", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _mbr(*entries: tuple[int, int, int]) -> bytes:
    head = bytearray(SECTOR)
    for index, (kind, start, sectors) in enumerate(entries):
        offset = 446 + 16 * index
        head[offset + 4] = kind
        struct.pack_into("<II", head, offset + 8, start, sectors)
    head[510:512] = b"\x55\xaa"
    return bytes(head)


# --- partition selection ----------------------------------------------------

def test_the_mbr_yields_the_fat32_boot_and_the_linux_root_partition():
    boot, root = _tool().select_partitions(_mbr((0x0C, 2048, 1048576), (0x83, 1050624, 60000000)))

    assert boot == (2048 * 512, 1048576 * 512)
    assert root == (1050624 * 512, 60000000 * 512)


def test_a_card_without_a_linux_partition_is_refused():
    with pytest.raises(ValueError, match="Linux root partition"):
        _tool().select_partitions(_mbr((0x0C, 2048, 4096)))


def test_a_gpt_or_blank_disk_is_refused():
    tool = _tool()
    with pytest.raises(ValueError, match="GPT"):
        tool.select_partitions(_mbr((0xEE, 1, 1000)))
    with pytest.raises(ValueError, match="MBR"):
        tool.select_partitions(bytes(SECTOR))


def test_the_boot_partition_is_optional():
    boot, root = _tool().select_partitions(_mbr((0x83, 2048, 4096)))

    assert boot is None
    assert root == (2048 * 512, 4096 * 512)


# --- raw disk wrapper -------------------------------------------------------

def test_the_raw_disk_reads_peeks_seeks_from_its_end_and_never_writes(tmp_path):
    disk = tmp_path / "disk.img"
    data = bytes(range(256)) * 16384  # 4 MiB, crosses the 1 MiB chunk cache
    disk.write_bytes(data)
    before = hashlib.sha256(disk.read_bytes()).hexdigest()

    raw = _tool().RawDisk(str(disk), size=len(data))
    raw.seek(1024 * 1024 - 3)
    assert raw.peek(6) == data[1024 * 1024 - 3:1024 * 1024 + 3]
    assert raw.read(6) == data[1024 * 1024 - 3:1024 * 1024 + 3]
    assert raw.tell() == 1024 * 1024 + 3
    assert raw.seek(-10, os.SEEK_END) == len(data) - 10
    assert raw.read() == data[-10:]
    assert raw.seek(5, os.SEEK_CUR) == len(data) + 5
    assert raw.read(4) == b""
    assert not hasattr(raw, "write")
    raw.close()

    assert hashlib.sha256(disk.read_bytes()).hexdigest() == before


# --- tree walking with a fake filesystem --------------------------------------

class FakeTree:
    """In-memory stand-in for the ext4 volume that records every access."""

    def __init__(self, files: dict[str, bytes], links: dict[str, str] | None = None,
                 broken: set[str] | None = None) -> None:
        self.files = files
        self.links = links or {}
        self.broken = broken or set()
        self.touched: list[str] = []

    def _dirs(self) -> set[str]:
        dirs = {"/"}
        for path in list(self.files) + list(self.links):
            parts = path.strip("/").split("/")[:-1]
            for index in range(1, len(parts) + 1):
                dirs.add("/" + "/".join(parts[:index]))
        return dirs

    def kind(self, path: str) -> str:
        self.touched.append(path)
        if path in self.files:
            return "file"
        if path in self.links:
            return "link"
        if path in self._dirs():
            return "dir"
        raise FileNotFoundError(path)

    def listdir(self, path: str) -> list[str]:
        self.touched.append(path)
        prefix = path.rstrip("/") + "/"
        names = set()
        for item in list(self.files) + list(self.links):
            if item.startswith(prefix):
                names.add(item[len(prefix):].split("/", 1)[0])
        return sorted(names)

    def open(self, path: str):
        self.touched.append(path)
        if path in self.broken:
            raise OSError("bad extent")
        return io.BytesIO(self.files[path])

    def readlink(self, path: str) -> str:
        self.touched.append(path)
        return self.links[path]


def _device_files() -> dict[str, bytes]:
    return {
        "/etc/hostname": b"rosy-pinky-e4us\n",
        "/etc/passwd": b"root:x:0:0:root:/root:/bin/bash\nrosy:x:1001:1001::/home/rosy:/bin/bash\n",
        "/etc/shadow": b"root:*:19000:0:99999:7:::\n",
        "/etc/rosy/device-identity.json": b'{"device_name": "rosy-pinky-e4us"}',
        "/etc/rosy/runtime.env": b"ROSY_API_PORT=8080\n",
        "/etc/rosy/fleet-bootstrap.json": b'{"enrollment": "x"}',
        "/etc/rosy/api-token": b"not-for-the-report",
        "/var/lib/rosy/provisioning/state.json": b'{"state": "PROVISIONED"}',
        "/var/lib/rosy/releases/native-activation.json": b'{"phase": "switched"}',
        "/var/lib/rosy/secrets/pairing.json": b"{}",
        "/etc/systemd/system/rosy-core.service": b"[Unit]\nDescription=ROSY\n",
        "/etc/systemd/system/dev-disk-by\\x2duuid-1234.swap": b"[Swap]\n",
        "/var/log/journal/0123abcd/system.journal": b"LPKSHHRH" + b"\0" * 64,
        "/var/log/cloud-init.log": b"cloud-init ran\n",
        "/var/log/cloud-init-output.log": b"output\n",
        "/var/log/syslog": b"not collected\n",
        "/etc/NetworkManager/system-connections/home.nmconnection": b"[wifi-security]\npsk=" + WIFI_FIXTURE.encode(),
        "/boot/firmware/rosy-provision/provision.json": b"{}",
    }


def _extract_fake(tool, tmp_path, tree, boot=None):
    out = tmp_path / "out"
    report = tool.extract_tree(tree, out, boot_diag=boot)
    return out, report


def test_the_diagnostic_set_is_copied_with_its_content(tmp_path):
    tool = _tool()
    tree = FakeTree(_device_files(), links={
        "/etc/systemd/system/multi-user.target.wants/rosy-core.service": "/etc/systemd/system/rosy-core.service",
    })

    out, report = _extract_fake(tool, tmp_path, tree)

    rootfs = out / "rootfs"
    for path in ("/etc/hostname", "/etc/passwd", "/etc/rosy/device-identity.json", "/etc/rosy/runtime.env",
                 "/var/lib/rosy/provisioning/state.json", "/var/lib/rosy/releases/native-activation.json",
                 "/etc/systemd/system/rosy-core.service", "/var/log/journal/0123abcd/system.journal",
                 "/var/log/cloud-init.log", "/var/log/cloud-init-output.log"):
        assert (rootfs / path.lstrip("/")).read_bytes() == tree.files[path], path
        assert report["files"][path]["size"] == len(tree.files[path])
    assert report["links"]["/etc/systemd/system/multi-user.target.wants/rosy-core.service"] == \
        "/etc/systemd/system/rosy-core.service"
    assert "/var/log/syslog" not in report["files"]
    assert "/etc/shadow" not in report["files"]


def test_denied_paths_are_never_opened_and_are_listed(tmp_path):
    tool = _tool()
    tree = FakeTree(_device_files())

    out, report = _extract_fake(tool, tmp_path, tree)

    opened = [path for path in tree.touched if "NetworkManager" in path or "rosy-provision" in path]
    assert opened == []
    for path in ("/etc/rosy/fleet-bootstrap.json", "/etc/rosy/api-token", "/var/lib/rosy/secrets"):
        assert path in report["denied"], path
        assert path not in tree.touched
    produced = b"".join(item.read_bytes() for item in out.rglob("*") if item.is_file())
    assert WIFI_FIXTURE.encode() not in produced
    assert b"not-for-the-report" not in produced


def test_windows_unsafe_names_are_escaped_and_mapped_in_the_report(tmp_path):
    tool = _tool()
    tree = FakeTree(_device_files())

    out, report = _extract_fake(tool, tmp_path, tree)

    entry = report["files"]["/etc/systemd/system/dev-disk-by\\x2duuid-1234.swap"]
    saved = out / entry["saved_as"]
    assert saved.read_bytes() == b"[Swap]\n"
    assert saved.parent == out / "rootfs" / "etc" / "systemd" / "system"
    assert "\\" not in saved.name


def test_read_errors_and_missing_targets_are_reported_not_fatal(tmp_path):
    tool = _tool()
    files = _device_files()
    del files["/var/log/cloud-init-output.log"]
    tree = FakeTree(files, broken={"/etc/rosy/runtime.env"})

    out, report = _extract_fake(tool, tmp_path, tree)

    assert "bad extent" in report["errors"]["/etc/rosy/runtime.env"]
    assert "/etc/hostname" in report["files"]
    written = json.loads((out / "extract-report.json").read_text(encoding="utf-8"))
    assert written["errors"] == report["errors"]
    assert written["denied"] == report["denied"]


def test_an_existing_output_folder_is_not_reused(tmp_path):
    tool = _tool()
    out = tmp_path / "out"
    out.mkdir()
    (out / "keep.txt").write_text("earlier evidence", encoding="utf-8")

    with pytest.raises(FileExistsError):
        tool.extract_tree(FakeTree(_device_files()), out)
    assert (out / "keep.txt").read_text(encoding="utf-8") == "earlier evidence"


# --- whole disk: MBR + FAT32 black box + (fake) ext4 root -----------------------

def _card_with_black_box() -> tuple[bytearray, int, int]:
    """A disk image whose FAT32 partition holds rosy-diag/ and rosy-provision/."""
    card = _Card()
    image = card.image
    latest = b"stage:    FAILED: rosy-release-recover\nNo module named 'signing'\n"
    bundle = b'{"wifi": {"psk": "' + WIFI_FIXTURE.encode() + b'"}}'
    root = b"".join(_lfn_entries("rosy-diag")) + _dir_entry(b"ROSY-D~1", 0x10, 3, 0)
    root += b"".join(_lfn_entries("rosy-provision")) + _dir_entry(b"ROSY-P~1", 0x10, 5, 0)
    diag = _dir_entry(b".", 0x10, 3, 0) + _dir_entry(b"..", 0x10, 0, 0)
    diag += b"".join(_lfn_entries("latest.txt")) + _dir_entry(b"LATEST  TXT", 0x20, 4, len(latest))
    provision = _dir_entry(b".", 0x10, 5, 0) + _dir_entry(b"..", 0x10, 0, 0)
    provision += b"".join(_lfn_entries("provision.json")) + _dir_entry(b"PROVIS~1JSO", 0x20, 6, len(bundle))
    card.put(image, 2, root)
    card.put(image, 3, diag)
    card.put(image, 4, latest)
    card.put(image, 5, provision)
    card.put(image, 6, bundle)
    root_start = len(image) - 64 * 1024
    return image, root_start, 64 * 1024


def test_a_whole_disk_copies_the_black_box_but_never_the_provisioning_bundle(tmp_path):
    tool = _tool()
    image, _root_start, _root_length = _card_with_black_box()
    disk = tmp_path / "card.img"
    disk.write_bytes(bytes(image))
    before = hashlib.sha256(disk.read_bytes()).hexdigest()
    seen = {}

    def open_tree(raw, offset, length):
        seen["root"] = (offset, length)
        return FakeTree(_device_files())

    report = tool.extract(str(disk), tmp_path / "out", open_tree=open_tree)

    assert seen["root"] == (6144 * 512, 128 * 512)
    black_box = tmp_path / "out" / "boot" / "rosy-diag" / "latest.txt"
    assert b"No module named 'signing'" in black_box.read_bytes()
    assert report["boot_diag"]["files"]["rosy-diag/latest.txt"]["size"] == black_box.stat().st_size
    assert not (tmp_path / "out" / "boot" / "rosy-provision").exists()
    produced = b"".join(item.read_bytes() for item in (tmp_path / "out").rglob("*") if item.is_file())
    assert WIFI_FIXTURE.encode() not in produced
    assert hashlib.sha256(disk.read_bytes()).hexdigest() == before


def test_a_boot_partition_without_a_black_box_is_reported(tmp_path):
    tool = _tool()
    card = _Card()
    image = card.build()
    disk = tmp_path / "card.img"
    disk.write_bytes(bytes(image))

    report = tool.extract(str(disk), tmp_path / "out", open_tree=lambda raw, o, n: FakeTree(_device_files()))

    assert report["boot_diag"] == {"present": False, "files": {}}


def test_physical_drive_numbers_resolve_to_the_windows_device_path():
    assert _tool().device_path("3") == r"\\.\PhysicalDrive3"
    assert _tool().device_path(r"\\.\PhysicalDrive1") == r"\\.\PhysicalDrive1"


def test_the_cli_documents_elevation_and_read_only_use():
    completed = subprocess.run([sys.executable, str(SCRIPT), "--help"], capture_output=True, text=True)

    assert completed.returncode == 0, completed.stderr
    assert "read-only" in completed.stdout
    assert "--disk" in completed.stdout and "--out" in completed.stdout


# --- real ext4 ----------------------------------------------------------------

STAGE_SCRIPT = r"""
set -eu
stage="$(mktemp -d)"
img="$(mktemp)"
mkdir -p "$stage/etc/rosy" "$stage/etc/systemd/system/multi-user.target.wants" \
         "$stage/etc/NetworkManager/system-connections" "$stage/var/lib/rosy/provisioning" \
         "$stage/var/log/journal/0123abcd"
printf 'rosy-pinky-e4us\n' > "$stage/etc/hostname"
printf 'rosy:x:1001:1001::/home/rosy:/bin/bash\n' > "$stage/etc/passwd"
printf '{"device_name": "rosy-pinky-e4us"}' > "$stage/etc/rosy/device-identity.json"
printf '[Unit]\nDescription=ROSY\n' > "$stage/etc/systemd/system/rosy-core.service"
printf '[Swap]\n' > "$stage/etc/systemd/system/dev-disk-by\\x2duuid-1234.swap"
ln -s /etc/systemd/system/rosy-core.service "$stage/etc/systemd/system/multi-user.target.wants/rosy-core.service"
printf '[wifi-security]\npsk=%s\n' "$1" > "$stage/etc/NetworkManager/system-connections/home.nmconnection"
printf '{"state": "PROVISIONED"}' > "$stage/var/lib/rosy/provisioning/state.json"
head -c 300000 /dev/urandom > "$stage/var/log/journal/0123abcd/system.journal"
printf 'cloud-init ran\n' > "$stage/var/log/cloud-init.log"
rm -f "$img"
mkfs.ext4 -q -F -b 4096 -d "$stage" "$img" 16M >&2
cat "$img"
rm -rf "$stage" "$img"
"""


def _ext4_image() -> bytes | None:
    if importlib.util.find_spec("ext4") is None:
        return None
    if shutil.which("mkfs.ext4") and shutil.which("bash"):
        command = ["bash", "-c", STAGE_SCRIPT, "stage", WIFI_FIXTURE]
    elif os.name == "nt" and shutil.which("wsl"):
        command = ["wsl", "-e", "bash", "-c", STAGE_SCRIPT, "stage", WIFI_FIXTURE]
    else:
        return None
    try:
        completed = subprocess.run(command, capture_output=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0 or completed.stdout[1080:1082] != b"\x53\xef":
        return None
    return completed.stdout


def test_a_real_ext4_root_is_extracted_read_only(tmp_path):
    filesystem = _ext4_image()
    if filesystem is None:
        pytest.skip("needs the ext4 package (pip install ext4) and mkfs.ext4 (native or WSL)")
    tool = _tool()
    image, root_start, _ = _card_with_black_box()
    image = image[:root_start] + filesystem
    struct.pack_into("<II", image, 462 + 8, root_start // 512, len(filesystem) // 512)
    disk = tmp_path / "card.img"
    disk.write_bytes(bytes(image))
    before = hashlib.sha256(disk.read_bytes()).hexdigest()

    report = tool.extract(str(disk), tmp_path / "out")

    rootfs = tmp_path / "out" / "rootfs"
    assert (rootfs / "etc/hostname").read_bytes() == b"rosy-pinky-e4us\n"
    assert (rootfs / "var/lib/rosy/provisioning/state.json").read_bytes() == b'{"state": "PROVISIONED"}'
    assert report["files"]["/var/log/journal/0123abcd/system.journal"]["size"] == 300000
    assert report["links"]["/etc/systemd/system/multi-user.target.wants/rosy-core.service"] == \
        "/etc/systemd/system/rosy-core.service"
    assert "/etc/systemd/system/dev-disk-by\\x2duuid-1234.swap" in report["files"]
    assert not (rootfs / "etc/NetworkManager").exists()
    produced = b"".join(item.read_bytes() for item in (tmp_path / "out").rglob("*") if item.is_file())
    assert WIFI_FIXTURE.encode() not in produced
    assert report["errors"] == {}
    assert hashlib.sha256(disk.read_bytes()).hexdigest() == before
