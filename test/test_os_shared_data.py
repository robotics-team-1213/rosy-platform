"""Admission must cover the existing navigation/model/capture data owners."""
import os
from types import SimpleNamespace

import pytest

from os_state_boot_fakes import shared_roots
from test_os_storage_boot import _module


DATA = ("maps", "models", "pilot-recordings")


@pytest.mark.parametrize("name", DATA)
@pytest.mark.parametrize("view", ["1", "self"])
def test_data_mount_must_be_visible_in_host_and_consumer(tmp_path, monkeypatch, name, view):
    root, _, _, _ = shared_roots(tmp_path, monkeypatch)
    table = root / f"proc/{view}/mountinfo"
    table.write_text("".join(line for line in table.read_text().splitlines(keepends=True)
                             if f" /var/lib/rosy/{name} " not in line))
    with pytest.raises(ValueError, match="OS_STATE_HOLD"):
        _module().admit_storage(root)


@pytest.mark.parametrize("name", DATA)
@pytest.mark.parametrize("field", ["st_uid", "st_gid"])
def test_data_owner_must_match_the_existing_service_ids(tmp_path, monkeypatch, name, field):
    root, _, _, _ = shared_roots(tmp_path, monkeypatch)
    original = os.stat
    target = str(root / "var/lib/rosy" / name)

    def wrong_owner(path, *args, **kwargs):
        info = original(path, *args, **kwargs)
        if not isinstance(path, int) and os.fspath(path) == target:
            values = {key: getattr(info, key) for key in dir(info) if key.startswith("st_")}
            values[field] = 12345
            return SimpleNamespace(**values)
        return info

    monkeypatch.setattr(os, "stat", wrong_owner)
    with pytest.raises(ValueError, match="OS_STATE_HOLD"):
        _module().admit_storage(root)


@pytest.mark.parametrize("name", DATA)
def test_data_permissions_cannot_be_widened_by_the_other_slot(tmp_path, monkeypatch, name):
    root, other, common, _ = shared_roots(tmp_path, monkeypatch)
    (common / name).chmod(0o777)
    for slot in (root, other):
        with pytest.raises(ValueError, match="OS_STATE_HOLD"):
            _module().admit_storage(slot)


def test_root_switch_preserves_current_data_and_deletions(tmp_path, monkeypatch):
    root, other, _, _ = shared_roots(tmp_path, monkeypatch)
    for name in DATA:
        before = root / "var/lib/rosy" / name / "fixture"
        after = other / "var/lib/rosy" / name / "fixture"
        before.write_bytes(b"first revision")
        assert _module().admit_storage(other)["phase"] == "FACTORY_EMPTY"
        assert after.read_bytes() == b"first revision"
        after.write_bytes(b"replacement")
        assert _module().admit_storage(root)["phase"] == "FACTORY_EMPTY"
        assert before.read_bytes() == b"replacement"
        after.unlink()
        assert not before.exists()
