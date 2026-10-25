"""Exercise the shipped readback CLI, including metadata-only card checks."""
import json
import lzma
from pathlib import Path
import subprocess
import sys
import shutil

import pytest

from test_sd_gpt_layout import _table_image

VERIFY = Path(__file__).resolve().parents[1] / "deploy/robot/pinky_pro/sd/verify-media-readback.py"


def _case(tmp_path):
    raw, layout = _table_image(with_files=True)
    image, device, snapshot = [tmp_path / n for n in ("image.xz", "device", "layout.json")]
    image.write_bytes(lzma.compress(raw))
    device.write_bytes(raw)
    snapshot.write_text(json.dumps(layout), encoding="utf-8-sig")
    return image, device, snapshot, raw, layout


def _run(case, *args):
    image, device, snapshot, *_ = case
    return subprocess.run([sys.executable, str(VERIFY), "--image", str(image), "--device", str(device),
                           "--layout-file", str(snapshot), *args], capture_output=True, text=True, timeout=30)


def test_cli_readback_uses_bom_encoded_layout_snapshot(tmp_path):
    case = _case(tmp_path)
    result = _run(case)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["layout"] == case[-1]
    assert report["verified_scope"] == "image_prefix"
    assert set(report["boot_partitions"]) == {"bootstrap", "boot_a", "boot_b"}


def test_prewrite_probe_allows_an_old_card_without_claiming_layout_verified(tmp_path):
    case = _case(tmp_path)
    case[1].write_bytes(bytes(len(case[3])))
    result = _run(case, "--probe", "--probe-bytes", "2097152")
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["image_disk_guid"] == case[-1]["disk_guid"]
    assert report["device_disk_guid"] is None
    assert "device_layout_verified" not in report
    assert report["image_raw_size"] == len(case[3])


@pytest.mark.parametrize("corrupt", [False, True])
def test_metadata_check_validates_both_gpt_copies_and_keeps_image_prefix_scope(tmp_path, corrupt):
    case = _case(tmp_path)
    raw = bytearray(case[3])
    if corrupt:
        raw[-512 + 16] ^= 1
    case[1].write_bytes(raw + b"unverified larger card suffix")
    result = _run(case, "--verify-layout", "--probe-seconds", "5")
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["device_layout_verified"] is (not corrupt)
    assert "verified" not in report
    assert report["device_disk_guid"] == case[-1]["disk_guid"]
    assert report["device_read_mbps"] is None
    if corrupt:
        assert "GPT" in report["device_error"]
    else:
        assert report["device_layout"] == case[-1]


def test_layout_probe_rejects_image_index_size_disagreement(tmp_path):
    case = _case(tmp_path)
    case[0].write_bytes(lzma.compress(b"old image"))
    result = _run(case, "--probe")
    assert result.returncode == 0, result.stderr
    assert "size" in json.loads(result.stdout)["image_error"]


def test_malformed_layout_is_a_controlled_cli_failure(tmp_path):
    case = _case(tmp_path)
    case[2].write_text("{}", encoding="utf-8")
    result = _run(case, "--probe")
    assert result.returncode == 1
    assert "LAYOUT" in result.stderr
    assert "Traceback" not in result.stderr


def test_installed_sd_tree_runs_without_source_directory_or_pythonpath(tmp_path):
    case = _case(tmp_path)
    installed = tmp_path / "opt/rosy/deploy/sd"
    shutil.copytree(VERIFY.parent, installed, ignore=shutil.ignore_patterns("__pycache__"))
    result = subprocess.run([sys.executable, "-I", str(installed / VERIFY.name), "--image", str(case[0]),
                             "--device", str(case[1]), "--layout-file", str(case[2])],
                            cwd=tmp_path, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["layout"] == case[-1]
