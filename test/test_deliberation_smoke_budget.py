import json
import os
from concurrent.futures import ThreadPoolExecutor

import pytest

from deploy.ai_pc import deliberation_smoke_budget as budget


@pytest.fixture
def marker(tmp_path, monkeypatch):
    parent = tmp_path / 'smoke'
    parent.mkdir(mode=0o700)
    marker = parent / 'glm-first-review.spent'
    monkeypatch.setattr(budget, 'MARKER', marker)
    return marker


def test_claim_is_persistent_for_same_and_other_jobs(marker):
    budget.claim('{"case":"synthetic"}')
    assert marker.stat().st_mode & 0o777 == 0o600
    original = marker.read_bytes()
    data = json.loads(original)
    assert data['state'] == 'SUBMISSION_UNKNOWN' and len(data['job_sha256']) == 64
    for body in ('{"case":"synthetic"}', '{"case":"other"}'):
        with pytest.raises(ValueError, match='ALREADY_CLAIMED'):
            budget.claim(body)
        assert marker.read_bytes() == original


def test_concurrent_claim_has_exactly_one_winner(marker):
    def attempt(index):
        try:
            budget.claim(json.dumps({'case': index}))
            return True
        except ValueError:
            return False
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(attempt, range(8))) == 1
    assert marker.is_file()


def test_parent_mode_and_foreign_owner_refuse(marker, monkeypatch):
    marker.parent.chmod(0o750)
    with pytest.raises(ValueError, match='BOUNDARY'):
        budget.claim('{}')
    marker.parent.chmod(0o700)
    uid = os.getuid()
    monkeypatch.setattr(budget.os, 'getuid', lambda: uid + 1)
    with pytest.raises(ValueError, match='BOUNDARY'):
        budget.claim('{}')
    assert not marker.exists()


def test_symlink_parent_and_marker_refuse_without_modifying_target(marker, monkeypatch, tmp_path):
    target = tmp_path / 'target'
    target.write_text('preserve')
    marker.symlink_to(target)
    with pytest.raises(ValueError, match='ALREADY_CLAIMED'):
        budget.claim('{}')
    assert target.read_text() == 'preserve'
    alias = tmp_path / 'alias'
    alias.symlink_to(marker.parent, target_is_directory=True)
    monkeypatch.setattr(budget, 'MARKER', alias / marker.name)
    with pytest.raises(ValueError, match='BOUNDARY'):
        budget.claim('{}')


def test_fsync_failure_preserves_claim(marker, monkeypatch):
    def fail(*args):
        raise OSError('synthetic fsync failure')
    monkeypatch.setattr(budget.os, 'fsync', fail)
    with pytest.raises(OSError):
        budget.claim('{}')
    assert marker.exists()
    with pytest.raises(ValueError, match='ALREADY_CLAIMED'):
        budget.claim('{}')
