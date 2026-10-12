"""Real idle CORE cancel receipts close as durable Fleet HOLD, never success."""
import asyncio
import json
import runpy
from pathlib import Path

import pytest

from fleet.server.channel.execution.worker import ExecutionWorker
from test_channel_natural_execution import fixture


@pytest.mark.parametrize('verb,text,path', [
    ('cancel', '40번 이동 취소해줘', '/api/v1/navigation/cancel'),
    ('follow_cancel', '40번 추종 취소해줘', '/api/v1/swarm/cancel')])
@pytest.mark.parametrize('next_step', [False, True])
def test_real_idle_cancel_receipt_closes_after_restart_without_replay(tmp_path, verb, text, path, next_step):
    # Reuse the canonical CORE service factory so this exercises actual routes/managers.
    repo = Path(__file__).resolve().parents[3]
    core_factory = runpy.run_path(str(repo / 'middleware/core/gateway/test/conftest.py'))['core_client']
    client, _ = core_factory.__wrapped__(tmp_path)()
    plan = {'do': verb, 'robot': 'rosy_40'}
    f = fixture(tmp_path, text + (' 그리고 40번 집으로 복귀해줘' if next_step else ''),
                {'steps': [plan, {'do': 'home', 'robot': 'rosy_40'}]} if next_step else plan)
    assert f.store.reserve_resources(owner_kind='direct_action', owner_id='unresolved-motion',
        generation=f.store.dispatch_control()['generation'], resources=[('robot', 'rosy_40')])
    with f.store._connect() as conn, conn:
        conn.execute("UPDATE fleet_action_claims SET phase='UNKNOWN' WHERE owner_id='unresolved-motion'")
    sent = []
    async def cancel(*args):
        sent.append(path)
        response = client.post(path, headers={'Authorization': 'Bearer rosy-dev-operator'})
        assert response.status_code == 200
        receipt = response.json()
        assert receipt['operation'] is None
        return receipt
    f.client.navigation_cancel = cancel
    f.client._post = cancel
    rid = f.receipt['request_id']
    asyncio.run(f.worker.step(rid))
    assert f.journal.view(rid)['steps'][0]['state'] == 'ACCEPTED'
    # Recover the persisted ACK-only row exactly as an old process left it.
    f.journal.recover()
    worker = ExecutionWorker(f.journal, f.worker.execution)
    assert rid in worker.pending()
    asyncio.run(worker.step(rid))
    steps = f.journal.view(rid)['steps']
    assert steps[0]['state'] == 'HOLD'
    if next_step: assert steps[1]['state'] == 'READY'
    assert json.loads(steps[0]['receipt_json'])['rpc_acknowledged'] is True
    assert rid not in worker.pending()
    asyncio.run(worker.step(rid))
    assert sent == [path]
    assert f.store.resource_claims(resource_kind='robot', resource_id='rosy_40')[0]['owner_id'] == 'unresolved-motion'
    with f.store._connect() as conn:
        reply = conn.execute("SELECT * FROM fleet_channel_reply_outbox WHERE request_id=? AND kind='EXECUTION:0:NATIVE:HOLD:False'", (rid,)).fetchone()
    assert reply is not None and reply['state'] == 'PENDING' and 'HOLD' in reply['content']
