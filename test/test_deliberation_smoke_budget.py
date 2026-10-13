import json
import os
import http.client
import socket
import threading
import time
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor

import pytest

from deploy.ai_pc import deliberation_smoke_budget as budget
from deploy.ai_pc import deliberation_glm_gateway as gate


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


def test_gateway_upstream_failure_preserves_claim_across_fresh_servers(marker, monkeypatch):
    calls = []
    def upstream(*args):
        assert marker.exists()
        calls.append(1)
        raise TimeoutError('synthetic request outcome unknown')
    monkeypatch.setattr(gate, 'claim', budget.claim)
    monkeypatch.setattr(gate, 'upstream', upstream)
    class Client(http.client.HTTPConnection):
        def connect(self):
            self.sock = socket.socket(socket.AF_UNIX)
            self.sock.settimeout(3)
            self.sock.connect(self.host)
    for index in range(2):
        path = str(marker.parent / ('socket-' + str(index)))
        with gate.Gateway(path, gate.Handler) as server:
            server.timeout = 2
            server.body, server.token, server.calls = '{}', 'fake-unit-token', 0
            server.deadline, server.problem = time.monotonic() + 5, None
            worker = threading.Thread(target=server.handle_request, daemon=True)
            worker.start()
            with closing(Client(path)) as client:
                client.request('POST', '/v1/chat/completions', json.dumps({'model': gate.MODEL, 'messages': []}))
                response = client.getresponse()
                response.read()
                assert response.status == 400
            worker.join(3)
            assert not worker.is_alive()
            assert server.metrics['state'] == 'HOLD' and server.calls == (1 if index == 0 else 0)
    assert calls == [1] and marker.exists()
