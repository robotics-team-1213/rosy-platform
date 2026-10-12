"""A real prior turn and native completion, never model prose, bind a follow-up."""
import asyncio
from uuid import uuid4

from core_common.protocol.channel_requests import DiscordRequestEnvelope
from fleet.server.channel.execution.outcomes.reconcile import task_result
from test_channel_natural_execution import fixture
from test_channel_native_outcomes import _readback


def completed_turn(tmp_path, *, safe=True):
    f = fixture(tmp_path)
    f.jobs.execution = f.journal
    asyncio.run(f.worker.step(f.receipt['request_id']))

    async def dispatch(attempt):
        return {'accepted': True, 'operation': {'run_id': str(uuid4()), 'boot_id': str(uuid4()),
            'kind': 'navigate', 'correlation_id': attempt['attempt_id'], 'phase': 'SUBMITTED',
            'result': None, 'reason': None}}

    task = asyncio.run(f.service.dispatch_next({'rosy_40'}, dispatch=dispatch))
    operation = task['receipt']['operation']
    f.service.project_core_event({'robot_id': 'rosy_40', 'event_id': 'arrived', 'seq': 1,
        'type': 'nav.completed', 'data': {k: operation[k] for k in ('correlation_id', 'run_id', 'boot_id')}})
    async def get(path):return _readback(operation, quiescent=safe)
    f.client._get = get
    asyncio.run(task_result(f.store, f.client, f.store.get_task(task['task_id'])))
    f.task = f.store.get_task(task['task_id'])
    return f


def next_receipt(f, text='40번 거기로 보내줘'):
    return f.raw.receive(DiscordRequestEnvelope(guild_id=f.receipt['guild_id'],
        channel_id=f.receipt['channel_id'], author_id=f.receipt['author_id'],
        message_id=str(int(f.receipt['message_id'])+1), mentions=[f.raw.config.bot_id],
        author_bot=False, webhook_id=None, content=f'<@{f.raw.config.bot_id}> '+text))


def test_terminal_event_without_native_safe_release_never_supplies_selection(tmp_path):
    f = completed_turn(tmp_path, safe=False)
    assert f.task['status'] == 'COMPLETED'
    assert f.store.resource_claims(resource_kind='robot', resource_id='rosy_40')
    with f.store._connect() as conn:
        assert f.journal.selection(f.question, conn) is None


def test_real_prior_turn_native_success_reaches_followup_input(tmp_path):
    f = completed_turn(tmp_path)
    assert f.task['receipt']['safe_released'] is True
    q = f.jobs.build_input(next_receipt(f), f.env, f.clock[0])
    assert len(q.history) == 1 and q.history[0].request_id == f.receipt['request_id']
    context = q.model_dump().get('accepted_execution_context')
    assert context is not None, 'native completed same-owner selection must reach AI input'
    assert context['task_id'] == f.task['task_id']
    assert context['request_id'] == f.receipt['request_id']
    assert context['robot_id'] == 'rosy_40' and context['place_id'] == 'A'
    assert q.history[0].accepted_execution_context is None
