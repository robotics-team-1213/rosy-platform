"""Passive handover of an exact successful Task after its outcome owner released it."""
import asyncio
import json
import sqlite3
import time
from contextlib import closing

from fleet.swarm.dispatch_guard import dispatch_guard
from .evidence import epoch, exact_operation, safe_proof

_PATH = '/api/v1/navigation/handover'


def _eligible(service, robot, value, started, admission, expected=None):
    if admission() is not None:
        return None
    operation = value['operation']
    with closing(service.store._connect()) as conn, conn:
        conn.execute('PRAGMA busy_timeout=0')
        conn.execute('BEGIN IMMEDIATE')
        rows = conn.execute('''SELECT * FROM fleet_tasks WHERE robot_id=? AND attempt_id=?''',
                            (robot, operation['correlation_id'])).fetchall()
        if len(rows) != 1:
            return None
        task = dict(rows[0])
        receipt = json.loads(task['receipt_json'] or '{}')
        control = conn.execute('SELECT * FROM fleet_dispatch_control WHERE control_id=1').fetchone()
        if (task['status'] != 'COMPLETED' or task['task_type'] != 'navigate'
                or receipt.get('accepted') is not True or receipt.get('safe_released') is not True
                or receipt.get('outcome') != operation
                or exact_operation(operation, receipt.get('operation') or {}) != operation
                or not control['dispatch_enabled'] or control['generation'] != task['dispatch_generation']
                or conn.execute("SELECT 1 FROM fleet_action_claims WHERE resource_key=?",
                                ('robot:' + robot,)).fetchone()
                or conn.execute('SELECT 1 FROM fleet_robot_reservations WHERE robot_id=?', (robot,)).fetchone()
                or expected is not None and task != expected
                or admission() is not None or not 0 <= time.monotonic()-started <= 2):
            return None
        return task


async def handover_completed_navigation(self, robot_id, *, client, admission, expected_boot_id=None, completed=None):
    """Admission is a read-only source check. This never releases claims or moves."""
    if robot_id not in self.robot_ids or getattr(client, 'robot_id', None) != robot_id:
        return False
    started = time.monotonic()
    try:
        value = await asyncio.wait_for(client._get('/api/v1/navigation/state'), 2)
        operation = exact_operation(value['operation'], value['operation'])
        if (operation['kind'] != 'navigate' or operation['result'] != 'SUCCEEDED'
                or expected_boot_id is not None and operation['boot_id'] != expected_boot_id
                or not safe_proof(value, operation)):
            return False
        owner = epoch(value)
        task = await asyncio.to_thread(_eligible, self, robot_id, value, started, admission)
    except (KeyError, TypeError, ValueError, TimeoutError, sqlite3.Error):
        return False
    if task is None:
        return False

    def admit():
        try:
            valid = _eligible(self, robot_id, value, started, admission, task)
        except (KeyError, TypeError, ValueError, sqlite3.Error):
            valid = None
        if valid is None:
            raise ValueError('NAVIGATION_HANDOVER_ADMISSION_CHANGED')

    admit()
    with dispatch_guard(admit, paths={_PATH}):
        await client.navigation_handover(**owner, run_id=operation['run_id'],
                                         correlation_id=operation['correlation_id'])
    if completed is not None:
        try:
            admit()  # A new Task/claim or expired original source cannot retire projections.
        except ValueError:
            return False
        return completed(task=task, operation=operation) is True
    return True
