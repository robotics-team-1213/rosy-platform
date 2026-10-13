"""Observe every captured safety-stop owner without borrowing motion claims."""
import asyncio
import json
import time
from contextlib import closing

from .evidence import safe_proof


async def stop_step(worker, rid, index, call, row, receipt):
    from .reconcile import notify, observe
    journal = worker.journal
    robots = receipt.get('robots', []) if call.verb == 'estop' else [receipt | {'robot_id': call.robot}]
    complete = bool(robots) and all(r.get('estop') is True and r.get('operations')
                                   and r.get('rpc_acknowledged', True) is True for r in robots)
    complete = complete and {r['robot_id'] for r in robots} == {r for k, r in json.loads(row['resources_json'] or '[]') if k == 'robot'}
    entries = [{'robot_id': r['robot_id'], 'operation': op} for r in robots for op in r.get('operations', [])]
    prior = {(r['robot_id'], r['operation']['run_id']): r for r in receipt.get('stop_outcomes', [])}
    observations = await asyncio.gather(*(observe(worker.execution.console._client(r['robot_id']), r,
        r['robot_id'], worker.execution.task_service.core_events) for r in entries))
    with closing(journal.store._connect()) as conn, conn:
        conn.execute('BEGIN IMMEDIATE')
        current = conn.execute('SELECT * FROM fleet_channel_execution_steps WHERE request_id=? AND step_index=?',
                               (rid, index)).fetchone()
        if any(current[k] != row[k] for k in ('owner_id', 'generation', 'task_id', 'receipt_json', 'state',
                                             'resources_json', 'caller_cid')):
            return True
        closed = complete
        for entry, (started, value, operation) in zip(entries, observations):
            previous = prior.get((entry['robot_id'], entry['operation']['run_id']), {}).get('outcome')
            if previous and previous['phase'] == 'TERMINAL':
                operation = previous
            if operation:
                entry['outcome'] = operation
            proven = operation is not None and safe_proof(value, operation) and 0 <= time.monotonic() - started <= 2
            if proven:
                entry['quiescence'] = value['quiescence']
            closed = closed and proven
        state = 'CANCELED' if closed else 'UNKNOWN' if complete else 'HOLD'
        receipt = receipt | {'stop_outcomes': entries}
        conn.execute('UPDATE fleet_channel_execution_steps SET state=?,receipt_json=?,reason=? WHERE request_id=? AND step_index=?',
                     (state, json.dumps(receipt), 'NATIVE_STOP_OBSERVED' if closed else 'STOP_PROOF_INCOMPLETE', rid, index))
        if state in {'CANCELED', 'HOLD'}:
            conn.execute('UPDATE fleet_channel_execution SET reason=? WHERE request_id=?', (state, rid))
        notify(journal, conn, rid, index, receipt, result=state)
    return True
