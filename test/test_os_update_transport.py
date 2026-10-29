"""GitHub transport layout leaves the signed logical bundle unchanged."""
import importlib.util
from pathlib import Path

import pytest


NAME = "rosy-os-pinky-pro-2026.10.28-173-arm64.raucb"
GIB = 1024**3


def module():
    path = Path(__file__).resolve().parents[1] / "deploy/robot/pinky_pro/native/os_update_transport.py"
    spec = importlib.util.spec_from_file_location("os_transport_test", path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


@pytest.mark.parametrize("size,parts", [
    (1, [1]), (2 * GIB - 1, [2 * GIB - 1]),
    (2 * GIB, [GIB, GIB]), (2 * GIB + 1, [GIB, GIB, 1]),
    (16 * GIB, [GIB] * 16),
])
def test_transport_boundaries_and_deterministic_part_names(size, parts):
    transport = module()
    expected = [(NAME, size)] if len(parts) == 1 else [
        (NAME + f".part{number:03}", length) for number, length in enumerate(parts)
    ]
    bundle = dict(filename=NAME, size_bytes=size, sha256="a" * 64)
    original = dict(bundle)
    assert transport.bundle_assets(bundle) == expected
    assert bundle == original


@pytest.mark.parametrize("size", [0, -1, True, "1", 16 * GIB + 1])
def test_invalid_or_oversized_bundle_is_refused(size):
    transport = module()
    with pytest.raises(ValueError):
        transport.bundle_assets(dict(filename=NAME, size_bytes=size))


@pytest.mark.parametrize("name", ["../bundle.raucb", "folder\\bundle.raucb", None, "bundle.zip", "bad\0.raucb"])
def test_noncanonical_bundle_filename_is_refused(name):
    transport = module()
    with pytest.raises(ValueError):
        transport.bundle_assets(dict(filename=name, size_bytes=1))


def test_more_than_sixteen_parts_is_refused(monkeypatch):
    transport = module()
    monkeypatch.setattr(transport, "CHUNK_BYTES", 1)
    monkeypatch.setattr(transport, "GITHUB_MAX_ASSET_BYTES", 16)
    with pytest.raises(ValueError):
        transport.bundle_assets(dict(filename=NAME, size_bytes=17))
