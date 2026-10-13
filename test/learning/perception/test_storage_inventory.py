"""Storage reads stay inside registered project roots and never qualify data."""
import hashlib
import json
import os

import pytest

from storage_inventory import StorageInventory


def configured(tmp_path, **extra):
    root = tmp_path / 'raw'; root.mkdir()
    cfg = dict(project_id='one', roots=[dict(id='raw', label='Raw', role='raw', path=str(root))],
               reserve_bytes=10, **extra)
    return root, cfg


def test_counts_hardlinks_partial_files_and_preserves_bytes(tmp_path):
    root, cfg = configured(tmp_path)
    (root / 'clip.mp4').write_bytes(b'video')
    os.link(root / 'clip.mp4', root / 'copy.mp4')
    (root / 'capture.part').write_bytes(b'abc')
    before = hashlib.sha256((root / 'clip.mp4').read_bytes()).hexdigest()
    service = StorageInventory(tmp_path / 'state.db', cfg, 'one')
    result = service.snapshot()
    row = result['roots'][0]
    assert row['status'] == 'ready'
    assert (row['logical_bytes'], row['file_bytes'], row['files']) == (13, 8, 3)
    assert row['incomplete_bytes'] == 3
    assert row['growth_bytes_per_day'] is None and row['estimated_days'] is None
    assert row['free_bytes'] > 0
    assert str(root) not in json.dumps(result) and 'clip.mp4' not in json.dumps(result)
    assert hashlib.sha256((root / 'clip.mp4').read_bytes()).hexdigest() == before


def test_symlink_missing_and_scan_bound_are_unknown_not_zero(tmp_path):
    root, cfg = configured(tmp_path)
    outside = tmp_path / 'secret'; outside.mkdir(); (outside / 'private').write_bytes(b'secret')
    (root / 'link').symlink_to(outside, target_is_directory=True)
    service = StorageInventory(tmp_path / 'state.db', cfg, 'one')
    row = service.snapshot()['roots'][0]
    assert row['status'] == 'partial' and row['logical_bytes'] is None
    assert 'secret' not in json.dumps(row)
    (root / 'link').unlink(); root.rmdir()
    assert service.snapshot(refresh=True)['roots'][0]['status'] == 'unavailable'
    root.mkdir(); (root / 'one').write_bytes(b'x')
    service.max_entries = 0
    assert service.snapshot(refresh=True)['roots'][0]['status'] == 'partial'


def test_project_overlap_and_symlink_root_rejected(tmp_path):
    root, cfg = configured(tmp_path)
    with pytest.raises(ValueError): StorageInventory(tmp_path / 'state.db', cfg, 'two')
    nested = root / 'child'; nested.mkdir()
    cfg['roots'].append(dict(id='nested', label='Nested', role='derived', path=str(nested)))
    with pytest.raises(ValueError): StorageInventory(tmp_path / 'state.db', cfg, 'one')
    cfg['roots'].pop(); alias = tmp_path / 'alias'; alias.symlink_to(root, target_is_directory=True)
    cfg['roots'][0]['path'] = str(alias)
    with pytest.raises(ValueError): StorageInventory(tmp_path / 'state.db', cfg, 'one')


def test_root_swapped_after_registration_is_not_followed(tmp_path):
    root, cfg = configured(tmp_path)
    service = StorageInventory(tmp_path / 'state.db', cfg, 'one')
    root.rename(tmp_path / 'original')
    outside = tmp_path / 'other-project'; outside.mkdir()
    (outside / 'secret').write_bytes(b'private')
    root.symlink_to(outside, target_is_directory=True)
    result = service.snapshot()
    assert result['roots'][0]['status'] == 'unavailable'
    assert result['roots'][0]['logical_bytes'] is None
    assert 'other-project' not in json.dumps(result)


def test_permission_failure_does_not_expose_path(tmp_path, monkeypatch):
    root, cfg = configured(tmp_path)
    def denied(_): raise PermissionError(str(root / 'private-name'))
    monkeypatch.setattr('storage_inventory.os.scandir', denied)
    row = StorageInventory(tmp_path / 'state.db', cfg, 'one').snapshot()['roots'][0]
    assert row['logical_bytes'] is None and row['status'] == 'unavailable'
    assert 'private-name' not in json.dumps(row)


def test_daily_history_survives_restart_and_config_change_resets_trend(tmp_path):
    root, cfg = configured(tmp_path)
    now = [1800000000.0]
    service = StorageInventory(tmp_path / 'state.db', cfg, 'one', clock=lambda: now[0])
    (root / 'clip').write_bytes(b'x' * 10); service.snapshot()
    now[0] += 86400; (root / 'clip').write_bytes(b'x' * 30)
    restarted = StorageInventory(tmp_path / 'state.db', cfg, 'one', clock=lambda: now[0])
    row = restarted.snapshot()['roots'][0]
    assert row['growth_bytes_per_day'] == 20 and row['estimated_days'] > 0
    cfg['roots'][0]['role'] = 'pending'
    changed = StorageInventory(tmp_path / 'state.db', cfg, 'one', clock=lambda: now[0])
    snapshot = changed.snapshot()
    assert snapshot['roots'][0]['growth_bytes_per_day'] is None
    assert snapshot['pending_bytes'] == 30


def test_preflight_accounts_for_all_local_copies_and_stale_remote_quota(tmp_path):
    root, cfg = configured(tmp_path, remote_quota=dict(remaining_bytes=50, source='manual test',
        measured_at=1800000000, expires_at=1800000100))
    now = [1800000001]
    service = StorageInventory(tmp_path / 'state.db', cfg, 'one', clock=lambda: now[0])
    body = dict(destination_id='raw', download_bytes=20, staging_bytes=30, transform_bytes=40, upload_bytes=51)
    result = service.preflight(body)
    assert result['local_required_bytes'] == 100
    assert result['remote_status'] == 'insufficient' and result['status'] == 'blocked'
    now[0] += 101
    assert service.preflight(body)['remote_status'] == 'unknown'
    body['upload_bytes'] = 0
    assert service.preflight(body)['status'] == 'ready'
    body['download_bytes'] = 9_000_000_000_000_000
    assert service.preflight(body)['local_status'] == 'insufficient'
    with pytest.raises(ValueError): service.preflight(dict(body, path='/other'))
    with pytest.raises(ValueError): service.preflight(dict(body, destination_id='other-project'))
    with pytest.raises(ValueError): service.preflight(dict(body, download_bytes=True))
