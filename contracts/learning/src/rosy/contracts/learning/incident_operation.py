"""Bound independent-review signatures; no evidence assessment or owner admission."""
import hmac
import hashlib
import json
import math

from .artifacts import _fields, _hash, _json, seal

APPROVE = 'reasoning_operational_acceptance'
REVOKE = 'reasoning_operational_revocation'
BINDING_FIELDS = ('profile_set_sha256 full_profile_sha256 model_revision calibration_sha256 '
    'domain action action_contract policy_revision installation_sha256 evaluation_sha256 '
    'coverage_sha256 limits_sha256 truth_sha256 evaluation_state')


def _label(value):
    if type(value) is not str or not value or value != value.strip() or len(value) > 256:
        raise ValueError('INVALID_OPERATION_LABEL')


def _epoch(value):
    if type(value) is not int or not 0 <= value < 2**63:
        raise ValueError('INVALID_OPERATION_EPOCH')


def _time(value):
    try:
        valid = type(value) in (int, float) and value >= 0 and math.isfinite(value)
    except OverflowError:
        valid = False
    if not valid: raise ValueError('INVALID_OPERATION_TIME')


def validate_operation_binding(value):
    _fields(value, BINDING_FIELDS)
    for field, item in value.items():
        _hash(item) if field.endswith('_sha256') else _label(item)
    if (value['domain'] != 'line_follow' or value['action'] != 'BACK_AND_RETRY'
            or value['action_contract'] != 'rosy.line_stuck.conditional_back/1'
            or value['evaluation_state'] != 'REVIEWED_FOR_OPERATION'):
        raise ValueError('INVALID_OPERATION_BINDING')
    return json.loads(_json(value))


def validate_operation_receipt(value):
    _fields(value, 'principal payload signature')
    _label(value['principal']); _hash(value['signature'])
    payload = value['payload']
    _fields(payload, 'schema kind binding expected_epoch valid_from_s expires_s revision')
    _label(payload['kind'])
    if payload['schema'] != 'rosy.incident.operation/1' or payload['kind'] not in {APPROVE, REVOKE}:
        raise ValueError('INVALID_OPERATION_KIND')
    validate_operation_binding(payload['binding'])
    _epoch(payload['expected_epoch'])
    _time(payload['valid_from_s']); _time(payload['expires_s'])
    if payload['expires_s'] <= payload['valid_from_s'] or seal(payload) != payload:
        raise ValueError('INVALID_OPERATION_REVISION_OR_WINDOW')
    return json.loads(_json(value))


def verify_operation_receipt(value, *, trusted, expected_binding, epoch, now, kind):
    """The owner supplies current bindings/epoch, never values copied from the receipt."""
    receipt = validate_operation_receipt(value)
    binding = validate_operation_binding(expected_binding)
    _epoch(epoch); _time(now)
    if type(trusted) is not dict or type(kind) is not str or kind not in {APPROVE, REVOKE}:
        raise ValueError('EXPLICIT_OPERATION_TRUST_AND_KIND_REQUIRED')
    trust = trusted.get(receipt['principal'])
    if (type(trust) is not dict or set(trust) != {'key', 'kinds'}
            or type(trust['key']) is not bytes or len(trust['key']) < 32
            or type(trust['kinds']) not in (set, frozenset) or kind not in trust['kinds']):
        raise ValueError('OPERATION_TRUST_OR_SCOPE_DIFFERS')
    payload = receipt['payload']
    if payload['kind'] != kind or payload['binding'] != binding or payload['expected_epoch'] != epoch:
        raise ValueError('OPERATION_BINDING_OR_EPOCH_DIFFERS')
    if kind == APPROVE and not payload['valid_from_s'] <= now < payload['expires_s']:
        raise ValueError('OPERATION_RECEIPT_NOT_CURRENT')
    signature = hmac.new(trust['key'], _json(payload), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(receipt['signature'], signature):
        raise ValueError('OPERATION_SIGNATURE_DIFFERS')
    return receipt
