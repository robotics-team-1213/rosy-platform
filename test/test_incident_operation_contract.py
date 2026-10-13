"""Signed operating evidence binds a current owner epoch; never issues an action."""
import hashlib
import hmac
import json

import pytest

from rosy.contracts.learning import seal

KEY = b'independent-operation-test-key-32-bytes'
APPROVE = 'reasoning_operational_acceptance'
REVOKE = 'reasoning_operational_revocation'
TRUST = {'reviewer': {'key': KEY, 'kinds': {APPROVE, REVOKE}}}


def binding():
    return dict(profile_set_sha256='a' * 64, full_profile_sha256='b' * 64,
        model_revision='model-fixed', calibration_sha256='c' * 64, domain='line_follow',
        action='BACK_AND_RETRY', action_contract='rosy.line_stuck.conditional_back/1',
        policy_revision='line-follow-shadow-v1', installation_sha256='d' * 64,
        evaluation_sha256='e' * 64, coverage_sha256='f' * 64,
        limits_sha256='1' * 64, truth_sha256='2' * 64, evaluation_state='REVIEWED_FOR_OPERATION')


def signed(*, kind=APPROVE, epoch=3):
    payload = seal(dict(schema='rosy.incident.operation/1', kind=kind, binding=binding(),
        expected_epoch=epoch, valid_from_s=100.0, expires_s=130.0))
    return resign(dict(principal='reviewer', payload=payload, signature='0' * 64))


def resign(receipt):
    raw = json.dumps(receipt['payload'], sort_keys=True, separators=(',', ':'),
                     ensure_ascii=False, allow_nan=False).encode()
    receipt['signature'] = hmac.new(KEY, raw, hashlib.sha256).hexdigest()
    return receipt


def verify(receipt, **kwargs):
    from rosy.contracts.learning.incident_operation import verify_operation_receipt
    return verify_operation_receipt(receipt, trusted=kwargs.get('trusted', TRUST),
        expected_binding=kwargs.get('expected_binding', binding()), epoch=kwargs.get('epoch', 3),
        now=kwargs.get('now', 101), kind=kwargs.get('kind', APPROVE))


def test_signature_verification_returns_an_isolated_bound_record_without_authority():
    receipt = signed()
    result = verify(receipt)
    assert result == receipt and result is not receipt
    result['payload']['binding']['model_revision'] = 'changed'
    assert receipt['payload']['binding']['model_revision'] == 'model-fixed'
    assert 'action_admissible' not in result and 'action_admissible' not in result['payload']


@pytest.mark.parametrize('field', list(binding()))
def test_trusted_signature_cannot_approve_a_different_binding(field):
    receipt = signed()
    changed = binding(); changed[field] = '9' * 64 if field.endswith('_sha256') else 'foreign'
    with pytest.raises(ValueError): verify(receipt, expected_binding=changed)


@pytest.mark.parametrize('fault', ['signature', 'principal', 'trust', 'scope', 'key', 'kind', 'epoch', 'extra', 'revision'])
def test_invalid_signature_trust_scope_revision_or_replay_is_rejected(fault):
    receipt = signed(); options = {}
    if fault == 'signature': receipt['signature'] = '0' * 64
    if fault == 'principal': receipt['principal'] = 'model'
    if fault == 'trust': options['trusted'] = {}
    if fault == 'scope': options['trusted'] = {'reviewer': {'key': KEY, 'kinds': {'reasoning_calibration'}}}
    if fault == 'key': options['trusted'] = {'reviewer': {'key': b'short', 'kinds': {APPROVE}}}
    if fault == 'kind': options['kind'] = REVOKE
    if fault == 'epoch': options['epoch'] = 4
    if fault == 'extra': receipt['action_admissible'] = True
    if fault == 'revision': receipt['payload']['revision'] = '0' * 64; resign(receipt)
    with pytest.raises(ValueError): verify(receipt, **options)


@pytest.mark.parametrize('state', ['HOLD', 'PASS_OFFLINE_ONLY', 'PASS_COMPARISON_OFFLINE_ONLY', True])
def test_signed_offline_or_hold_evidence_is_not_an_operational_review(state):
    receipt = signed(); receipt['payload']['binding']['evaluation_state'] = state
    receipt['payload'] = seal(receipt['payload']); resign(receipt)
    with pytest.raises(ValueError): verify(receipt)


@pytest.mark.parametrize('now', [99, 130, float('nan'), float('inf'), True])
def test_approval_requires_current_finite_validity_window(now):
    with pytest.raises(ValueError): verify(signed(), now=now)


@pytest.mark.parametrize('epoch', [-1, True, 1.5, None])
def test_epoch_is_a_strict_nonnegative_integer(epoch):
    with pytest.raises(ValueError): verify(signed(), epoch=epoch)


def test_revoke_is_a_separate_signed_kind_and_can_revoke_an_expired_approval():
    receipt = signed(kind=REVOKE)
    assert verify(receipt, now=200, kind=REVOKE) == receipt
    with pytest.raises(ValueError): verify(signed(), now=200, kind=REVOKE)


def test_signature_canonicalization_preserves_non_ascii_identity():
    receipt = signed()
    receipt['principal'] = '독립 검수자'
    receipt['payload']['binding']['model_revision'] = '模型-fixed'
    receipt['payload'] = seal(receipt['payload']); resign(receipt)
    expected = binding(); expected['model_revision'] = '模型-fixed'
    assert verify(receipt, expected_binding=expected,
        trusted={receipt['principal']: TRUST['reviewer']}) == receipt
