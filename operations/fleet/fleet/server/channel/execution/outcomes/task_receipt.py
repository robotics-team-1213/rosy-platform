"""Attempt-CAS binding of the first native Task response."""
import json
from contextlib import closing

from core_common.protocol.native.operation import NativeOperation


def bind_native_receipt(store, task_id, attempt_id, robot_id, receipt):
    """Capture the first response before Console performs another await."""
    if receipt is None:
        with closing(store._connect()) as conn, conn:
            conn.execute('BEGIN IMMEDIATE')
            changed = conn.execute('''UPDATE fleet_tasks SET receipt_json='{"native_required":true}'
                WHERE task_id=? AND attempt_id=? AND robot_id=? AND receipt_json IS NULL''',
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

