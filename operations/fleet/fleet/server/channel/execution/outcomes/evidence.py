"""D-732 identity, epoch and quiescence validation at the CORE boundary."""
from uuid import UUID
from datetime import datetime

from core_common.protocol.native.operation import NativeOperation

PATHS = {'navigate': '/api/v1/navigation/state', 'home': '/api/v1/navigation/state',
         'dock': '/api/v1/docking/status', 'undock': '/api/v1/docking/status',
         'follow': '/api/v1/swarm/state', 'teleop': '/api/v1/teleop/state'}
KINDS = {'move': 'teleop', **{kind: kind for kind in PATHS}}


def exact_operation(value, original):
    operation = NativeOperation.model_validate(value).model_dump(mode='json')
    if any(operation[key] != original[key] for key in ('boot_id', 'run_id', 'kind', 'correlation_id')):
        raise ValueError('NATIVE_OPERATION_IDENTITY_CHANGED')
    return operation


def epoch(value):
    owner = value['owner']
    boot = str(UUID(owner['boot_id']))
    generation = owner['owner_generation']
    if type(generation) is not int or generation < 0:
        raise ValueError('NATIVE_OWNER_EPOCH_INVALID')
    return {'expected_boot_id': boot, 'expected_owner_generation': generation}


def safe_proof(value, operation):
    proof = value.get('quiescence')
    if operation['phase'] != 'TERMINAL' or value.get('lookup') != 'FOUND' or not isinstance(proof, dict):
        return False
    owner = value.get('owner', {})
    try:
        observed = datetime.fromisoformat(proof['observed_at'].replace('Z', '+00:00'))
    except (KeyError, TypeError, ValueError, AttributeError):
        return False
    return (observed.utcoffset() is not None and value.get('operation') == operation
            and proof.get('boot_id') == operation['boot_id'] == owner.get('boot_id')
            and proof.get('requested_run_id') == operation['run_id']
            and 'owner_run_id' in owner and owner['owner_run_id'] is None
            and 'owner_run_id' in proof and proof['owner_run_id'] is None
            and proof.get('quiescent') is True
            and all(proof.get(key) is False for key in
                    ('admitting', 'pending_submission', 'actuating_callback', 'lease_active'))
            and type(proof.get('owner_generation')) is int and proof['owner_generation'] >= 0
            and type(owner.get('owner_generation')) is int
            and proof['owner_generation'] == owner['owner_generation']
            and type(proof.get('transport_generation')) is int and proof['transport_generation'] >= 0)


def terminal_event(events, original):
    """An exact durable event retains result evidence, never a release proof."""
    for event in events:
        data = event.get('data', {})
        if data.get('run_id') != original['run_id'] or data.get('boot_id') != original['boot_id']:
            continue
        result = data.get('result')
        if event['type'] == 'nav.completed':
            result = 'SUCCEEDED'
        elif event['type'] == 'nav.failed':
            result = 'FAILED'
        if result is not None:
            reason = data.get('native_reason', data.get('reason'))
            if event['type'] == 'nav.failed':
                reason = 'BACKEND_REJECTED' if data.get('error_code') == 'REJECTED' else 'BACKEND_ERROR'
            return exact_operation(original | {'phase': 'TERMINAL', 'result': result,
                                   'reason': reason}, original)
        if event['type'] == 'nav.canceled':
            source = data.get('source') or ''
            result, reason = ('EXPIRED', 'LEASE_EXPIRED') if source == 'goal_lease' else (
                ('FAILED', 'STUCK') if source == 'stuck_detector' else
                ('CANCELED', 'SAFETY_STOP' if source.startswith('safety') else 'CANCELED'))
            return exact_operation(original | {'phase': 'TERMINAL', 'result': result, 'reason': reason}, original)
    return None
