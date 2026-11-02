"""D-958 stage 1: a role service lends the GPU only while idle, and the host gives it back by itself."""
import importlib.util
import json
from pathlib import Path
import time

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def tenants(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location('gpu_tenants', ROOT / 'deploy/hosts/gpu_tenants.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, 'JOBS', tmp_path / 'rosy-jobs')
    monkeypatch.setattr(mod, 'OWNER_MODE', tmp_path / 'situation-owner-mode')
    monkeypatch.setattr(mod, 'SITUATION', tmp_path / 'logs')
    (tmp_path / 'logs').mkdir()
    (tmp_path / 'rosy-jobs').mkdir()
    mod.OWNER_MODE.write_text('available\n')
    mod.calls = []
    monkeypatch.setattr(mod, 'systemctl', lambda action, unit: mod.calls.append((action, unit)))
    return mod


def situation(mod, now, *, online=False, age=5):
    row = {'observed_at': now - age, 'state': {'robots': [{'robot_id': 'r1', 'online': online}]}}
    (mod.SITUATION / '2026-11-02-input.jsonl').write_text('{"partial\n' + json.dumps(row) + '\n')


UNIT = 'rosy-ollama.service'


def test_claim_lends_only_while_no_robot_is_online(tenants):
    now = time.time()
    situation(tenants, now, online=True)
    assert tenants.claim([UNIT], now) == 'busy robot online' and tenants.calls == []
    situation(tenants, now, age=600)
    assert tenants.claim([UNIT], now).startswith('busy no fresh')  # unknown is busy
    situation(tenants, now)
    assert tenants.claim([UNIT], now) == 'claimed'
    assert tenants.calls == [('stop', UNIT)] and tenants.OWNER_MODE.read_text().strip() == 'shared'
    assert tenants.claim([UNIT], now + 60) == 'claimed' and tenants.calls == [('stop', UNIT)]  # renew, no restop
    assert json.loads(tenants.mark(UNIT).read_text())['owner_mode'] == 'available'


def test_an_undeclared_unit_is_never_lent(tenants):
    situation(tenants, time.time())
    assert tenants.claim(['rosy-review-v13.service'], time.time()).startswith('busy')


def test_tick_gives_back_on_role_work_or_after_the_lease_with_no_gpu_job(tenants):
    now = time.time()
    situation(tenants, now)
    tenants.claim([UNIT], now)
    (tenants.JOBS / 'isaac-x.resv').write_text(f'{now + 1200} gpu 6 8\n')
    situation(tenants, now + 1000)
    assert tenants.tick(now + 1000) == 'nothing'  # lease over but an Isaac run still holds the GPU
    situation(tenants, now + 1000, online=True)
    assert tenants.tick(now + 1000) == f'released {UNIT}'  # a robot came online: the role wins at once
    assert tenants.calls[-1] == ('start', UNIT) and tenants.OWNER_MODE.read_text().strip() == 'available'
    assert not tenants.mark(UNIT).exists()


def test_tick_gives_back_a_forgotten_lease(tenants):
    now = time.time()
    situation(tenants, now)
    tenants.claim([UNIT], now)
    situation(tenants, now + 1000)
    assert tenants.tick(now + 1000) == f'released {UNIT}'  # the batch died: nothing renewed, nothing holds the GPU


def test_a_proposal_in_the_last_ten_minutes_keeps_the_role_busy(tenants):
    now = time.time()
    situation(tenants, now)
    (tenants.SITUATION / '2026-11-02-proposals.jsonl').write_text('{}\n')
    assert tenants.busy([UNIT], time.time()) == 'recent proposal'
