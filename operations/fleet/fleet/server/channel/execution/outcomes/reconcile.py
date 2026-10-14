"""Read-only native evidence closes exactly one persisted Fleet claim by CAS."""
import asyncio
import json
import time
from contextlib import closing

from fastapi import HTTPException

from .evidence import PATHS, exact_operation, safe_proof, terminal_event


def _receipt(row):
    return json.loads(row['receipt_json']) if row['receipt_json'] else {}


async def observe(client, receipt, robot, events=None):
    original = receipt['operation']
    started = time.monotonic()
    try:
        value = await asyncio.wait_for(client._get(PATHS[original['kind']] + '?run_id=' + original['run_id']), 2)
        operation = exact_operation(value['operation'], original) if value.get('lookup') == 'FOUND' else None
    except Exception:
        value, operation = {}, None
    if original['phase'] == 'TERMINAL':
        operation = original
    if operation is None and events is not None:
        operation = terminal_event(events.native_events(robot, original['boot_id'], original['run_id']), original)
    return started, value, operation


def record(conn, row, receipt, robot, owner_kind, owner_id, generation, resources, started, value, operation):
    """Called only under BEGIN IMMEDIATE with the original row revalidated."""
    if operation is None:
        return receipt
    outcome = receipt.get('outcome')
    if outcome is not None and outcome['phase'] == 'TERMINAL':
        if operation['phase'] == 'TERMINAL' and outcome != operation:
            return receipt
        operation = outcome
    receipt = receipt | {'outcome': operation}
    if receipt.get('safe_released') is True:
        return receipt
    claims = conn.execute('SELECT * FROM fleet_action_claims WHERE owner_kind=? AND owner_id=?',
                          (owner_kind, owner_id)).fetchall()
    expected = {(kind + ':' + resource, kind, resource) for kind, resource in resources}
    actual = {(claim['resource_key'], claim['resource_kind'], claim['resource_id']) for claim in claims}
    if (not expected or actual != expected or ('robot:' + robot, 'robot', robot) not in expected
            or any(claim['generation'] != generation for claim in claims)
            or not safe_proof(value, operation) or not 0 <= time.monotonic() - started <= 2):
        return receipt
    for key, _, _ in expected:
        conn.execute('''DELETE FROM fleet_action_claims
            WHERE resource_key=? AND owner_kind=? AND owner_id=? AND generation=?''',
            (key, owner_kind, owner_id, generation))
    return receipt | {'safe_released': True, 'quiescence': value['quiescence']}


def notify(journal, conn, rid, index, receipt, *, result=None):
    row = conn.execute("SELECT receipt FROM fleet_channel_requests WHERE json_extract(receipt,'$.request_id')=?", (rid,)).fetchone()
    if row is None:
        raise ValueError('NATIVE_ORIGINAL_REQUEST_MISSING')
    original = json.loads(row[0])
    operation = receipt.get('outcome')
    result = result or (operation['result'] or operation['phase'] if operation else 'UNKNOWN')
    released = receipt.get('safe_released') is True
    kind = f'EXECUTION:{index}:NATIVE:{result}:{released}'
    note = f"요청 단계 {index + 1} · {result}\n" + ('해당 실행의 자원 해제 확인.' if released else '자원 해제 확인 전입니다.')
    try:
        journal.jobs.journal.reply_outbox.enqueue(conn, original, kind, note)
    except HTTPException:
        journal.jobs.journal.reply_outbox._insert(conn, original, kind, '', 'SUPERSEDED')


async def channel_step(worker, rid, index, call, row):
    journal = worker.journal
    task = journal.store.get_task(row['task_id']) if row['task_id'] else None
    receipt = task['receipt'] or {} if task else _receipt(row)
    if call.verb in {'stop', 'estop'} or (call.verb in {'cancel', 'follow_cancel'} and 'operation' not in receipt):
        from .stops import stop_step
        return await stop_step(worker, rid, index, call, row, receipt)
    if 'operation' not in receipt:
        return False
    if task:
        await task_result(journal.store, worker.execution.console._client(call.robot), task,
                          events=worker.execution.task_service.core_events)
        task = journal.store.get_task(row['task_id'])
        receipt = task['receipt']
    else:
        started, value, operation = await observe(worker.execution.console._client(call.robot), receipt, call.robot,
                                                worker.execution.task_service.core_events)
    with closing(journal.store._connect()) as conn, conn:
        conn.execute('BEGIN IMMEDIATE')
        current = conn.execute('SELECT * FROM fleet_channel_execution_steps WHERE request_id=? AND step_index=?',
                               (rid, index)).fetchone()
        if any(current[key] != row[key] for key in ('owner_id', 'generation', 'task_id', 'receipt_json', 'state',
                                                   'resources_json', 'caller_cid')):
            return True
        if not task:
            receipt = record(conn, current, receipt, call.robot, 'direct_action', row['owner_id'], row['generation'],
                             [] if call.verb in {'cancel', 'follow_cancel', 'stop'} else json.loads(row['resources_json'] or '[]'),
                             started, value, operation)
        operation = receipt.get('outcome')
        state = ('RUNNING' if operation and operation['phase'] == 'RUNNING' else row['state'])
        if (not task and not value.get('operation')) or (task and task['status']=='UNKNOWN'):
            state = 'UNKNOWN'
        if receipt.get('safe_released') is True:
            state = 'COMPLETED' if operation['result'] == 'SUCCEEDED' else 'FAILED'
        if (not task and call.verb in {'cancel', 'follow_cancel', 'stop'} and operation
                and safe_proof(value, operation) and 0 <= time.monotonic() - started <= 2):
            state, receipt = 'CANCELED', receipt | {'quiescence': value['quiescence']}
        if state in {'FAILED', 'CANCELED'}:
            conn.execute('UPDATE fleet_channel_execution SET reason=? WHERE request_id=?',
                         (operation['result'] if operation else state, rid))
        conn.execute('UPDATE fleet_channel_execution_steps SET state=?,receipt_json=?,reason=? WHERE request_id=? AND step_index=?',
                     (state, json.dumps(receipt), operation['reason'] if operation else 'NATIVE_RUN_UNKNOWN', rid, index))
        notify(journal, conn, rid, index, receipt)
    return True


async def task_result(store, client, task, *, events=None):
    receipt = task.get('receipt') or {}
    if 'operation' not in receipt or receipt.get('safe_released') is True:
        return
    started, value, operation = await observe(client, receipt, task['robot_id'], events)
    with closing(store._connect()) as conn, conn:
        conn.execute('BEGIN IMMEDIATE')
        row = conn.execute('SELECT * FROM fleet_tasks WHERE task_id=?', (task['task_id'],)).fetchone()
        if (row['attempt_id'] != task['attempt_id'] or row['dispatch_generation'] != task['dispatch_generation']
                or _receipt(row) != receipt or row['robot_id'] != task['robot_id']):
            return
        receipt = record(conn, row, receipt, task['robot_id'], 'task', task['task_id'], task['dispatch_generation'],
                         [('robot', task['robot_id'])], started, value, operation)
        status, reason = row['status'], row['reason']
        if operation is None and (receipt.get('outcome') or {}).get('phase') != 'TERMINAL':
            status, reason = 'UNKNOWN', 'NATIVE_RUN_UNKNOWN'
        elif operation is not None and operation['phase'] == 'RUNNING' and receipt['outcome']['phase'] != 'TERMINAL':
            status, reason = 'RUNNING', operation['reason']
        if receipt.get('safe_released') is True:
            status = 'COMPLETED' if receipt['outcome']['result'] == 'SUCCEEDED' else 'FAILED'
            reason = receipt['outcome']['reason']
            conn.execute('DELETE FROM fleet_robot_reservations WHERE task_id=? AND robot_id=?', (task['task_id'], task['robot_id']))
        conn.execute('UPDATE fleet_tasks SET receipt_json=?,status=?,reason=? WHERE task_id=?',
                     (json.dumps(receipt), status, reason, task['task_id']))
        if status != row['status']:
            store._append_history(conn, task['task_id'], status, 'native-readback', task['robot_id'],
                                  time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), reason)


async def reconcile_tasks(service, console):
    with closing(service.store._connect()) as conn:
        rows = conn.execute('''SELECT task_id FROM fleet_tasks
            WHERE json_extract(receipt_json,'$.operation.run_id') IS NOT NULL
            AND COALESCE(json_extract(receipt_json,'$.safe_released'),0)=0
            ORDER BY (task_id>?) DESC,task_id LIMIT 20''', (getattr(service, '_native_cursor', ''),)).fetchall()
    if rows:
        service._native_cursor = rows[-1]['task_id']
    async def reconcile(row):
        try:
            task = service.store.get_task(row['task_id'])
            await task_result(service.store, console._client(task['robot_id']), task, events=service.core_events)
        except Exception:
            return

    await asyncio.gather(*(reconcile(row) for row in rows))
