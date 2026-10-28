"""Public-only OOB extraction from synthetic, file-backed GPT/ext4 cards."""
import base64
import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys

import pytest

from test_sd_gpt_layout import _table_image, _header

SCRIPT = Path(__file__).resolve().parents[1] / "deploy/robot/pinky_pro/sd/read-card-ssh-hostkey.py"
PUBLIC = "/ssh-hostkeys/ssh_host_ed25519_key.pub"
NAME = "rosy-pinky-k7m4"


def tool():
    spec = importlib.util.spec_from_file_location("card_public_hostkey_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def key():
    blob = struct.pack(">I", 11) + b"ssh-ed25519" + struct.pack(">I", 32) + bytes(range(32))
    return b"ssh-ed25519 " + base64.b64encode(blob), blob


class PublicOnly:
    def __init__(self, value, kind="file"):
        self.value, self.file_kind, self.opened = value, kind, []

    def kind(self, path):
        assert path in ("/ssh-hostkeys", PUBLIC), "unexpected path lookup"
        return "dir" if path == "/ssh-hostkeys" else self.file_kind

    def open(self, path):
        assert path == PUBLIC, "a non-public file was opened"
        self.opened.append(path)
        return io.BytesIO(self.value)

    def listdir(self, path):
        pytest.fail("directory walks are forbidden")


@pytest.mark.parametrize("physical_gpt", [False, True])
def test_only_public_file_is_opened_and_signed_mapping_binds_actual_gpt(tmp_path, physical_gpt):
    m = tool()
    raw, layout = _table_image()
    capacity = len(raw) + 1024 * 1024
    card = bytearray(raw + bytes(capacity - len(raw)))
    if physical_gpt:
        sectors = capacity // 512
        table = bytes(raw[1024:1024 + 16384])
        card[512:1024] = _header(1, sectors - 1, 2, table, sectors)
        card[-33 * 512:-512] = table
        card[-512:] = _header(sectors - 1, 1, sectors - 33, table, sectors)
    disk, receipt = tmp_path / "card", tmp_path / "public.json"
    disk.write_bytes(card)
    public, blob = key()
    tree = PublicOnly(public + b" comment-with-operator-information\n")
    calls = []

    def open_tree(raw_, offset, length):
        part = layout["partitions"][-1]
        calls.append((offset, length))
        assert (offset, length) == (part["start_lba"] * 512, part["size_lba"] * 512)
        return tree

    m.extract(str(disk), capacity, layout, NAME, receipt, open_tree=open_tree)
    report = json.loads(receipt.read_text())
    assert report == {"device_name": NAME, "public_key": public.decode(),
                      "fingerprint": "SHA256:" + base64.b64encode(hashlib.sha256(blob).digest()).decode().rstrip("=")}
    assert tree.opened == [PUBLIC] and len(calls) == 1
    assert disk.read_bytes() == card


@pytest.mark.parametrize("bad", [b"ssh-rsa AAAA", b"ssh-ed25519 !!!", b"ssh-ed25519 AAAA",
                                  b"ssh-ed25519 " + base64.b64encode(b"x" * 51),
                                  key()[0] + b"\n" + key()[0], b"x" * 4097])
def test_wrong_wire_format_or_size_never_yields_a_receipt(tmp_path, bad):
    m = tool()
    raw, layout = _table_image()
    disk, receipt = tmp_path / "card", tmp_path / "out.json"
    disk.write_bytes(raw)
    with pytest.raises(ValueError):
        m.extract(str(disk), len(raw), layout, NAME, receipt, open_tree=lambda *a: PublicOnly(bad))
    assert not receipt.exists() and disk.read_bytes() == raw


@pytest.mark.parametrize("case", ["mapping", "backup_crc", "symlink", "existing_receipt"])
def test_mismatch_or_symlink_or_existing_receipt_is_refused(tmp_path, case):
    m = tool()
    raw, layout = _table_image()
    expected = copy.deepcopy(layout)
    if case == "mapping":
        expected["partitions"][-1]["unique_guid"] = "734d3572-d8d9-4dde-b645-e1bac89b882d"
    if case == "backup_crc":
        raw[-512 + 16] ^= 1
    disk, receipt = tmp_path / "card", tmp_path / "out.json"
    disk.write_bytes(raw)
    if case == "existing_receipt":
        receipt.write_text("operator record")
    tree = PublicOnly(key()[0], "link" if case == "symlink" else "file")
    with pytest.raises((ValueError, FileExistsError)):
        m.extract(str(disk), len(raw), expected, NAME, receipt, open_tree=lambda *a: tree)
    assert tree.opened == [] if case != "existing_receipt" else receipt.read_text() == "operator record"
    assert disk.read_bytes() == raw


def test_real_ext4_public_key_and_independent_openssh_fingerprint(tmp_path):
    if not shutil.which("mkfs.ext4") or not shutil.which("ssh-keygen") or importlib.util.find_spec("ext4") is None:
        pytest.skip("existing ext4 and OpenSSH test tools are required")
    stage = tmp_path / "stage"
    keys = stage / "ssh-hostkeys"
    keys.mkdir(parents=True)
    private = keys / "ssh_host_ed25519_key"
    subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(private)], check=True)
    public = private.with_suffix(".pub")
    fingerprint = subprocess.check_output(["ssh-keygen", "-lf", str(public), "-E", "sha256"], text=True).split()[1]
    filesystem = tmp_path / "data.ext4"
    subprocess.run(["mkfs.ext4", "-q", "-F", "-b", "4096", "-d", str(stage), str(filesystem), "16M"],
                   check=True, capture_output=True)
    raw, layout = _table_image()
    sectors = 65536
    card = bytearray(sectors * 512)
    card[:len(raw)] = raw
    part = layout["partitions"][-1]
    part["size_lba"] = filesystem.stat().st_size // 512
    layout["raw_size_bytes"] = len(card)
    table = bytearray(raw[1024:1024 + 16384])
    struct.pack_into("<Q", table, 5 * 128 + 40, part["start_lba"] + part["size_lba"] - 1)
    struct.pack_into("<I", card, 446 + 12, sectors - 1)
    card[1024:1024 + 16384] = table
    card[-33 * 512:-512] = table
    card[512:1024] = _header(1, sectors - 1, 2, table, sectors)
    card[-512:] = _header(sectors - 1, 1, sectors - 33, table, sectors)
    start = part["start_lba"] * 512
    card[start:start + filesystem.stat().st_size] = filesystem.read_bytes()
    disk, receipt = tmp_path / "card.img", tmp_path / "public.json"
    disk.write_bytes(card)
    tool().extract(str(disk), len(card), layout, NAME, receipt)
    assert json.loads(receipt.read_text())["fingerprint"] == fingerprint
    assert disk.read_bytes() == card
