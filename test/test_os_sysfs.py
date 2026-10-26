"""Kernel attribute i_size is not its content length; metadata remains strictly bounded."""
import os
from pathlib import Path

import pytest

from test_ab_image_layout import module


def test_real_linux_sysfs_attributes_are_read_without_trusting_reported_size():
    module()
    import os_media
    paths = list(Path("/sys/dev/block").glob("*/size"))[:2]
    if not paths:
        pytest.skip("Linux block sysfs is not exposed")
    observed = []
    for path in paths:
        raw = path.read_bytes()
        assert len(raw) <= 64
        assert os_media._number(path) == int(raw)
        observed.append((path.stat().st_size, len(raw)))
    assert any(reported > 64 for reported, _ in observed)


def test_sysfs_exception_never_relaxes_stored_metadata_size_checks(tmp_path, monkeypatch):
    module()
    import os_state_layout
    path = tmp_path / "metadata.json"
    path.write_text("{}")
    original = os.fstat
    def page_sized(fd):
        info = original(fd)
        values = list(info)
        values[6] = 4096
        return os.stat_result(values)
    monkeypatch.setattr(os, "fstat", page_sized)
    with pytest.raises(ValueError, match="bounded regular"):
        os_state_layout._read(path, 64)
