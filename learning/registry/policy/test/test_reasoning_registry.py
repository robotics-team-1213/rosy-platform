"""Real SQLite restart, immutable snapshots, scoped receipts and CAS; no operating authority."""
import hashlib
import hmac
import importlib
import json
from pathlib import Path
import sqlite3
import sys

import pytest

ROOT = Path(__file__).resolve().parents[4]
sys.path[:0] = [str(ROOT / 'learning/registry/policy'), str(ROOT / 'contracts/learning/src'),
               str(ROOT / 'operations/decision/src'), str(ROOT / 'operations/fleet/test')]
from test_reasoning_candidate import inputs, subject as candidate_api
from registry import canonical

KEY = b'reasoning-test-key' * 2
TRUST = {'independent-review': {'key': KEY, 'kinds': {'reasoning_calibration', 'reasoning_revocation'}}}


def subject():
    return importlib.import_module('reasoning_registry')


def opened(root, trusted=TRUST):
    return subject().ReasoningRegistry(root, validator=candidate_api().validate_candidate, trusted=trusted)


def source(tmp_path, *, reviewed=True):
    profile, data = inputs()
    if not reviewed: data['reviewed_profile']['limits'] = None
    candidate = candidate_api().build_candidate(profile, data)
    path = tmp_path / 'input.json'
    path.write_text(json.dumps(candidate))
    return path, candidate


def signed(candidate, kind, head):
    payload = subject().receipt_payload(candidate, kind, head)
    return dict(principal='independent-review', payload=payload,
                signature=hmac.new(KEY, canonical(payload).encode(), hashlib.sha256).hexdigest())


def test_real_snapshot_restart_approval_revocation_and_idempotent_registration(tmp_path):
    path, candidate = source(tmp_path)
    registry = opened(tmp_path / 'registry')
    revision = registry.register(path)
    assert revision == candidate['revision'] and len(registry.history()) == 1
    assert registry.register(path) == revision and len(registry.history()) == 1
    path.unlink()
    registry = opened(tmp_path / 'registry')
    assert registry.candidate(revision) == candidate and registry.approved_artifacts() == {}
    head = registry.history()[-1]['revision']
    registry.approve(revision, signed(candidate, 'reasoning_calibration', head), expected_head=head)
    assert registry.approved_artifacts() == {candidate['profile']['calibration_revision']:
        subject().receipt_payload(candidate, 'reasoning_calibration', head)['calibration_sha256']}
    head = registry.history()[-1]['revision']
    registry.revoke(revision, signed(candidate, 'reasoning_revocation', head), expected_head=head)
    assert opened(tmp_path / 'registry').approved_artifacts() == {}


@pytest.mark.parametrize('fault', ['signature', 'profile', 'domain', 'candidate', 'calibration', 'kind', 'head', 'trust', 'scope'])
def test_wrong_or_self_declared_receipt_cannot_approve(tmp_path, fault):
    path, candidate = source(tmp_path)
    registry = opened(tmp_path / 'registry')
    revision = registry.register(path)
    head = registry.history()[-1]['revision']
    receipt = signed(candidate, 'reasoning_calibration', head)
    if fault == 'signature': receipt['signature'] = '0' * 64
    elif fault == 'trust': registry = opened(tmp_path / 'registry', trusted={})
    elif fault == 'scope': registry = opened(tmp_path / 'registry', trusted={
        'independent-review': {'key': KEY, 'kinds': {'reasoning_revocation'}}})
    else:
        key = {'profile': 'profile_sha256', 'domain': 'domain', 'candidate': 'candidate_revision',
               'calibration': 'calibration_sha256', 'kind': 'kind', 'head': 'expected_head'}[fault]
        receipt['payload'][key] = 'foreign'
        receipt['signature'] = hmac.new(KEY, canonical(receipt['payload']).encode(), hashlib.sha256).hexdigest()
    with pytest.raises(ValueError): registry.approve(revision, receipt, expected_head=head)
    assert registry.approved_artifacts() == {} and len(registry.history()) == 1


def test_two_handles_cannot_replay_a_competing_approval(tmp_path):
    path, candidate = source(tmp_path)
    first = opened(tmp_path / 'registry'); second = opened(tmp_path / 'registry')
    revision = first.register(path); head = first.history()[-1]['revision']
    receipt = signed(candidate, 'reasoning_calibration', head)
    first.approve(revision, receipt, expected_head=head)
    with pytest.raises(ValueError): second.approve(revision, receipt, expected_head=head)
    assert len(second.history()) == 2


def test_hold_candidate_can_be_preserved_but_never_approved(tmp_path):
    path, candidate = source(tmp_path, reviewed=False)
    registry = opened(tmp_path / 'registry')
    revision = registry.register(path); head = registry.history()[-1]['revision']
    with pytest.raises(ValueError):
        registry.approve(revision, signed(candidate, 'reasoning_calibration', head), expected_head=head)
    assert registry.approved_artifacts() == {}


@pytest.mark.parametrize('fault', ['snapshot', 'state', 'chain'])
def test_tampered_persistent_state_refuses_all_readback(tmp_path, fault):
    path, candidate = source(tmp_path)
    root = tmp_path / 'registry'; registry = opened(root)
    revision = registry.register(path)
    if fault == 'snapshot': (root / 'reasoning' / revision / 'candidate.json').write_text('{}')
    else:
        with sqlite3.connect(root / 'registry.sqlite3') as db:
            if fault == 'state': db.execute("UPDATE reasoning_candidates SET stage='approved'")
            else: db.execute("UPDATE reasoning_events SET body='{}'")
    with pytest.raises(ValueError): opened(root).approved_artifacts()


def test_approved_digest_matches_actual_calibration_artifact_with_unicode(tmp_path):
    from rosy.decision.deliberation.calibration import CalibrationArtifact
    profile, data = inputs()
    data['reviewed_profile']['reviewed_by'] = '현장검수'
    candidate = candidate_api().build_candidate(profile, data)
    path = tmp_path / 'unicode.json'; path.write_text(json.dumps(candidate))
    registry = opened(tmp_path / 'registry'); revision = registry.register(path)
    head = registry.history()[-1]['revision']
    registry.approve(revision, signed(candidate, 'reasoning_calibration', head), expected_head=head)
    artifact = CalibrationArtifact(json.dumps(candidate['calibration_report']))
    assert registry.approved_artifacts() == {profile['calibration_revision']: artifact.digest}


def test_different_full_profiles_cannot_share_one_approved_calibration_revision(tmp_path):
    from test_judgment_calibration import digest
    path, first = source(tmp_path)
    profile, data = inputs(); profile['model_revision'] = 'different-model'
    identity = dict(full_profile_sha256=digest(profile), model_revision=profile['model_revision'])
    data['reviewed_profile'].update(identity)
    for row in (*data['fit'], *data['evaluation']): row.update(identity)
    data['reviewed_profile'].update(fit_sha256=digest(data['fit']), evaluation_sha256=digest(data['evaluation']))
    second = candidate_api().build_candidate(profile, data)
    other = tmp_path / 'other.json'; other.write_text(json.dumps(second))
    registry = opened(tmp_path / 'registry')
    registry.register(path); registry.register(other)
    head = registry.history()[-1]['revision']
    registry.approve(first['revision'], signed(first, 'reasoning_calibration', head), expected_head=head)
    head = registry.history()[-1]['revision']
    with pytest.raises(ValueError):
        registry.approve(second['revision'], signed(second, 'reasoning_calibration', head), expected_head=head)
    assert len(registry.history()) == 3


@pytest.mark.parametrize('fault', ['removed', 'key', 'scope', 'resealed_receipt'])
def test_approved_restart_reverifies_current_trust_and_historical_receipt(tmp_path, fault):
    path, candidate = source(tmp_path)
    root = tmp_path / 'registry'; registry = opened(root)
    revision = registry.register(path); head = registry.history()[-1]['revision']
    registry.approve(revision, signed(candidate, 'reasoning_calibration', head), expected_head=head)
    trusted = TRUST
    if fault == 'removed': trusted = {}
    elif fault == 'key': trusted = {'independent-review': {'key': b'different-key' * 3,
                                                        'kinds': {'reasoning_calibration'}}}
    elif fault == 'scope': trusted = {'independent-review': {'key': KEY, 'kinds': {'reasoning_revocation'}}}
    else:
        from rosy.contracts.learning import seal
        with sqlite3.connect(root / 'registry.sqlite3') as db:
            event = json.loads(db.execute('SELECT body FROM reasoning_events WHERE sequence=2').fetchone()[0])
            event['data']['receipt']['signature'] = '0' * 64
            db.execute('UPDATE reasoning_events SET body=? WHERE sequence=2', (canonical(seal(event)),))
    with pytest.raises(ValueError): opened(root, trusted=trusted).approved_artifacts()
