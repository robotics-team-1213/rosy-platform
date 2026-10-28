"""GitHub transport layout leaves the signed logical bundle unchanged."""
import importlib

import pytest


NAME = "rosy-os-pinky-pro-2026.10.28-173-arm64.raucb"
GIB = 1024**3


@pytest.mark.parametrize("size,parts", [
    (1, [1]), (2 * GIB - 1, [2 * GIB - 1]),
    (2 * GIB, [GIB, GIB]), (2 * GIB + 1, [GIB, GIB, 1]),
    (16 * GIB, [GIB] * 16),
])
def test_transport_boundaries_and_deterministic_part_names(size, parts):
    transport = importlib.import_module("os_update_transport")
    expected = [(NAME, size)] if len(parts) == 1 else [
        (NAME + f".part{number:03}", length) for number, length in enumerate(parts)
    ]
    bundle = dict(filename=NAME, size_bytes=size, sha256="a" * 64)
    original = dict(bundle)
    assert transport.bundle_assets(bundle) == expected
    assert bundle == original


@pytest.mark.parametrize("size", [0, -1, True, "1", 16 * GIB + 1])
def test_invalid_or_oversized_bundle_is_refused(size):
    transport = importlib.import_module("os_update_transport")
    with pytest.raises(ValueError):
        transport.bundle_assets(dict(filename=NAME, size_bytes=size))


def test_more_than_sixteen_parts_is_refused(monkeypatch):
    transport = importlib.import_module("os_update_transport")
    monkeypatch.setattr(transport, "CHUNK_BYTES", 1)
    monkeypatch.setattr(transport, "GITHUB_MAX_ASSET_BYTES", 16)
    with pytest.raises(ValueError):
        transport.bundle_assets(dict(filename=NAME, size_bytes=17))
