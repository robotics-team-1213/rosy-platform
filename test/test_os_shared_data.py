"""Admission must cover the existing navigation/model/capture data owners."""
import os
from types import SimpleNamespace

import pytest

from os_state_boot_fakes import shared_roots
from test_os_storage_boot import _module


DATA = ("maps", "models", "pilot-recordings", "calibration")


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


def test_commissioned_calibration_survives_root_switch_and_fallback(tmp_path, monkeypatch):
    from core_common.calibration_store import CalibrationStore

    root, other, _, _ = shared_roots(tmp_path, monkeypatch, protocol=2)
    robot, kind = 'fixture-robot', 'lidar_mount'
    mirror = CalibrationStore(tmp_path / 'operator-mirror')
    record = mirror.add(robot, kind, {'lidar_yaw_offset': 0.12}, method='fixture/1')
    mirror.set_status(robot, kind, record, 'accepted', actor='fixture-operator')
    first = CalibrationStore(root / 'var/lib/rosy/calibration')
    first.merge_from(mirror.root, robot)
    second = CalibrationStore(other / 'var/lib/rosy/calibration')
    assert _module().admit_storage(other)['phase'] == 'FACTORY_EMPTY'
    assert second.current(robot, kind)['id'] == record
    newer = mirror.add(robot, kind, {'lidar_yaw_offset': 0.18}, method='fixture/2')
    mirror.set_status(robot, kind, newer, 'accepted', actor='fixture-operator')
    second.merge_from(mirror.root, robot)
    assert second.current(robot, kind)['id'] == newer
    mirror.pin(robot, kind, record, actor='fixture-operator')
    second.merge_from(mirror.root, robot)
    updated = {p.relative_to(second.root): p.read_bytes()
               for p in second.root.rglob('*') if p.is_file()}
    assert _module().admit_storage(root)['phase'] == 'FACTORY_EMPTY'
    assert first.current(robot, kind)['id'] == record
    assert first.current(robot, kind)['pinned'] is True
    assert updated == {p.relative_to(first.root): p.read_bytes()
                       for p in first.root.rglob('*') if p.is_file()}


@pytest.mark.parametrize('case', ['missing', 'wrong_gid', 'alias', 'supplementary', 'primary'])
def test_calibration_group_has_no_runtime_write_authority(tmp_path, monkeypatch, case):
    root, _, _, _ = shared_roots(tmp_path, monkeypatch)
    groups = root / 'etc/group'
    text = groups.read_text()
    if 'rosy-calib:' not in text:
        text += 'rosy-calib:x:964:\n'
    if case == 'missing':
        text = ''.join(line + '\n' for line in text.splitlines() if not line.startswith('rosy-calib:'))
    elif case == 'wrong_gid':
        text = text.replace('rosy-calib:x:964:', 'rosy-calib:x:965:')
    elif case == 'alias':
        text += 'untrusted:x:964:\n'
    elif case == 'supplementary':
        text = text.replace('rosy-calib:x:964:', 'rosy-calib:x:964:rosy-core')
    else:
        users = root / 'etc/passwd'
        users.write_text(users.read_text() + 'untrusted:x:1234:964::/nonexistent:/usr/sbin/nologin\n')
    groups.write_text(text)
    with pytest.raises(ValueError, match='OS_STATE_HOLD'):
        _module().admit_storage(root)
