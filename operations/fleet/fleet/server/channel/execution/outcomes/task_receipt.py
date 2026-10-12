"""Attempt-CAS binding of the first native Task response."""
import json
from contextlib import closing

from core_common.protocol.native.operation import NativeOperation
from fleet.swarm.dispatch_guard import dispatch_guard
from .evidence import epoch


async def prepare_send(leases, task_id, attempt_id, robot_id, client, options, stop):
    """Injected Task boundary; the safety lease owner imports no decision code."""
    native = task_id is not None and leases.native_required is not None and leases.native_required(task_id)
    if native:
        options.update(epoch(await client._get('/api/v1/navigation/state')))
        leases.check_stop(robot_id, stop)
    def admit():
        admit_send(leases, task_id, attempt_id, robot_id, native)
    admit()
    return dispatch_guard(admit, paths={'/api/v1/navigation/goal'})


def admit_send(leases, task_id, attempt_id, robot_id, native):
    """Every pre-submit guard revalidates admission before preparing ambiguity."""
    try:
        if task_id is not None and leases.admit_attempt is not None:
            leases.admit_attempt(task_id, attempt_id)
    except Exception:
        if native:
            leases.bind_native_receipt(task_id, attempt_id, robot_id, None, unsent=True)
        raise
    if native:
        leases.bind_native_receipt(task_id, attempt_id, robot_id, None)


def bind_native_receipt(store, task_id, attempt_id, robot_id, receipt, *, unsent=False):
    """Capture the first response before Console performs another await."""
    if unsent or (receipt is not None and receipt.get('accepted') is False and not receipt.get('operation')):
        with closing(store._connect()) as conn, conn:
            conn.execute('BEGIN IMMEDIATE')
            row = conn.execute('SELECT * FROM fleet_tasks WHERE task_id=? AND attempt_id=? AND robot_id=?',
                               (task_id, attempt_id, robot_id)).fetchone()
            if row and json.loads(row['receipt_json'] or '{}') == {'native_required': True}:
                conn.execute('UPDATE fleet_tasks SET receipt_json=? WHERE task_id=?',
                             (None if unsent else '{"accepted":false}', task_id))
                if row['status'] in {'HOLD', 'FAILED', 'CANCELED', 'EXPIRED'}:
                    conn.execute('DELETE FROM fleet_robot_reservations WHERE task_id=? AND robot_id=?',
                                 (task_id, robot_id))
                    conn.execute('DELETE FROM fleet_action_claims WHERE owner_kind=? AND owner_id=? AND generation=?',
                                 ('task', task_id, row['dispatch_generation']))
        return False
    if receipt is None:
        with closing(store._connect()) as conn, conn:
            conn.execute('BEGIN IMMEDIATE')
            changed = conn.execute('''UPDATE fleet_tasks SET receipt_json='{"native_required":true}'
                WHERE task_id=? AND attempt_id=? AND robot_id=?
                AND (receipt_json IS NULL OR receipt_json='{"native_required":true}')''',
                (task_id, attempt_id, robot_id)).rowcount
            if changed != 1:
                raise ValueError('NATIVE_TASK_ATTEMPT_ALREADY_PREPARED')
        return False
    if receipt.get('operation') is None:
        return False
    operation = NativeOperation.model_validate(receipt['operation']).model_dump(mode='json')
    if (receipt.get('accepted') is not True or operation['kind'] != 'navigate'
            or operation['correlation_id'] != attempt_id):
        raise ValueError('NATIVE_TASK_RECEIPT_MISMATCH')
    with closing(store._connect()) as conn, conn:
        conn.execute('BEGIN IMMEDIATE')
        row = conn.execute('SELECT * FROM fleet_tasks WHERE task_id=? AND attempt_id=? AND robot_id=?',
                           (task_id, attempt_id, robot_id)).fetchone()
        if row is None:
            raise ValueError('NATIVE_TASK_ATTEMPT_CHANGED')
        old = json.loads(row['receipt_json']) if row['receipt_json'] else {}
        if old.get('operation') is not None:
            if old['operation'] != operation:
                raise ValueError('NATIVE_TASK_RECEIPT_CHANGED')
            return True
        conn.execute('UPDATE fleet_tasks SET receipt_json=? WHERE task_id=? AND attempt_id=?',
                     (json.dumps(old | {'accepted': True, 'operation': operation}), task_id, attempt_id))
    return True

