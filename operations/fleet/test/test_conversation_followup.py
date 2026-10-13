"""A real prior turn and native completion, never model prose, bind a follow-up."""
import asyncio
import json
from uuid import uuid4
import pytest

from core_common.protocol.channel_requests import DiscordRequestEnvelope
from fleet.server.channel.execution.outcomes.reconcile import task_result
from fleet.server.channel.conversation.worker import ConversationWorker
from rosy.decision.conversation.codec import Profile, bounded_environment
from test_channel_natural_execution import fixture
from test_channel_native_outcomes import _readback
from test_channel_conversation import answer


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


def followup_worker(f, *, during=None, text='40번 거기로 보내줘'):
    receipt = next_receipt(f, text)
    calls = []
    async def snapshot():return f.env | {'observed_at':f.clock[0]}
    async def provider(question, profile, remaining):
        calls.append(question)
        if during:during()
        return answer('CONTROL', intent={'do':'navigate','robot':'rosy_40','waypoint':'A'})
    worker = ConversationWorker(f.jobs,snapshot,Profile(**f.scope['profile']),provider,
        admission=lambda:f.admitted[0],observation_guard=lambda env:bounded_environment(f.env)==env,
        clock=lambda:f.clock[0],producer_scope=f.scope)
    async def read_context(context):return await f.client._get('/api/v1/navigation/state?run_id='+context['run_id'])
    worker.context_reader=read_context
    return worker,receipt,calls


def change_context(f, change):
    if change == 'withdraw':
        f.raw.withdraw(f.receipt['guild_id'],f.receipt['channel_id'],f.receipt['message_id'])
    elif change == 'actor':f.accounts['op']='viewer'
    elif change == 'route':f.raw.config=f.raw.config.model_copy(update={'channel_id':'11111111111111111'})
    elif change == 'map':f.env['map']['version']+=1
    elif change == 'grant':f.admitted[0]=False
    elif change == 'expiry':f.clock[0]+=121
    elif change == 'generation':f.store.close_dispatch_for_startup()
    else:
        with f.store._connect() as conn,conn:
            if change == 'unknown':conn.execute("UPDATE fleet_tasks SET status='UNKNOWN' WHERE task_id=?",(f.task['task_id'],))
            else:
                receipt=f.store.get_task(f.task['task_id'])['receipt']
                if change == 'release':receipt['safe_released']=False
                elif change == 'quiescence':receipt['quiescence']['quiescent']=False
                else:receipt['operation'][change]=str(uuid4())
                conn.execute('UPDATE fleet_tasks SET receipt_json=? WHERE task_id=?',(json.dumps(receipt),f.task['task_id']))


@pytest.mark.parametrize('change',['withdraw','actor','route','map','grant','expiry','generation',
                                  'unknown','boot_id','run_id','release'])
def test_selected_context_changed_during_model_never_becomes_answered(tmp_path,change):
    f=completed_turn(tmp_path)
    worker,receipt,calls=followup_worker(f,during=lambda:change_context(f,change))
    asyncio.run(worker.step(receipt))
    assert len(calls)==1 and calls[0].accepted_execution_context is not None
    assert f.jobs.peek(receipt['request_id'])['state'] in {'HOLD','SUPERSEDED'}
    assert not f.store.queued_task_ids()


def test_followup_queues_once_and_rechecks_original_after_selection_row_moves(tmp_path):
    f=completed_turn(tmp_path)
    worker,receipt,calls=followup_worker(f)
    asyncio.run(worker.step(receipt))
    assert f.jobs.peek(receipt['request_id'])['state']=='ANSWERED'
    asyncio.run(f.worker.step(receipt['request_id']))
    asyncio.run(f.worker.step(receipt['request_id']))
    queued=sorted(f.store.queued_task_ids())
    assert len(queued)==1 and f.journal.task_reason(queued[0]) is None
    assert f.journal.guard(receipt['request_id'])['request_id']==receipt['request_id']
    change_context(f,'withdraw')
    assert f.journal.task_reason(queued[0])=='CHANNEL_EXECUTION_ORIGIN_CHANGED'
    from fleet.server.goal_lease import GoalLeases
    leases=GoalLeases(0,{})
    leases.admit_attempt=f.service.admit_attempt
    leases.bind_native_receipt=f.service.bind_native_receipt
    leases.native_required=f.service.native_required
    from functools import partial
    from fleet.server.channel.execution.outcomes.task_receipt import prepare_send
    leases.prepare_send=partial(prepare_send,leases)
    dispatched=[]
    async def goal(*args,**kwargs):dispatched.append(args);return {'accepted':True}
    f.client.navigation_goal=goal
    async def dispatch(task):
        return await leases.send('rosy_40',f.client,{},1.,2.,0.,task['attempt_id'],task_id=task['task_id'])
    asyncio.run(f.service.dispatch_next({'rosy_40'},dispatch=dispatch))
    assert not dispatched and f.store.get_task(queued[0])['status']=='HOLD'


@pytest.mark.parametrize('change',['unknown','withdraw','boot_id','run_id','release','quiescence'])
def test_changed_completed_context_is_absent_on_next_turn(tmp_path,change):
    f=completed_turn(tmp_path)
    change_context(f,change)
    q=f.jobs.build_input(next_receipt(f),f.env,f.clock[0])
    assert q.accepted_execution_context is None


def test_foreign_actor_cannot_supply_selected_context(tmp_path):
    f=completed_turn(tmp_path)
    f.raw.config.users['11111111111111111']='other'
    receipt=f.raw.receive(DiscordRequestEnvelope(guild_id=f.receipt['guild_id'],
        channel_id=f.receipt['channel_id'],author_id='11111111111111111',
        message_id=str(int(f.receipt['message_id'])+1),mentions=[f.raw.config.bot_id],
        author_bot=False,webhook_id=None,content=f'<@{f.raw.config.bot_id}> 40번 거기로 보내줘'))
    q=f.jobs.build_input(receipt,f.env,f.clock[0])
    assert q.history==[] and q.accepted_execution_context is None


@pytest.mark.parametrize('phase',['stage','reserve','finish'])
def test_context_revocation_at_each_durable_boundary_refuses_followup(tmp_path,phase,monkeypatch):
    f=completed_turn(tmp_path)
    worker,receipt,calls=followup_worker(f)
    original=getattr(f.jobs,phase)
    def changed(*args,**kwargs):
        if phase=='reserve':
            value=original(*args,**kwargs)
            change_context(f,'withdraw')
            return value
        change_context(f,'withdraw')
        return original(*args,**kwargs)
    monkeypatch.setattr(f.jobs,phase,changed)
    asyncio.run(worker.step(receipt))
    assert f.jobs.peek(receipt['request_id'])['state'] in {'HOLD','SUPERSEDED'}
    assert len(calls)==(1 if phase=='finish' else 0)


@pytest.mark.parametrize('change',['map','grant','generation','unknown','boot_id','run_id','release'])
def test_queued_followup_origin_rechecks_every_bound_fact(tmp_path,change):
    f=completed_turn(tmp_path)
    worker,receipt,_=followup_worker(f)
    asyncio.run(worker.step(receipt));asyncio.run(f.worker.step(receipt['request_id']))
    queued=next(iter(f.store.queued_task_ids()))
    change_context(f,change)
    assert f.journal.task_reason(queued)=='CHANNEL_EXECUTION_ORIGIN_CHANGED'


def test_unaccepted_prior_control_proposal_cannot_authorize_followup(tmp_path):
    f=fixture(tmp_path)
    f.jobs.execution=f.journal
    worker,receipt,calls=followup_worker(f)
    asyncio.run(worker.step(receipt));asyncio.run(f.worker.step(receipt['request_id']))
    assert calls[0].history[0].kind=='CONTROL' and calls[0].accepted_execution_context is None
    assert not f.store.queued_task_ids() and not f.writes


@pytest.mark.parametrize('change',['reboot','pruned','new_owner','new_generation','wrong_run'])
@pytest.mark.parametrize('phase',['stage','result'])
def test_live_selected_native_readback_change_refuses_followup(tmp_path,change,phase):
    f=completed_turn(tmp_path)
    value=_readback(f.task['receipt']['operation'])
    def mutate():
        if change=='reboot':value['owner']['boot_id']=str(uuid4())
        elif change=='pruned':value['lookup']='UNKNOWN';value['operation']=None
        elif change=='new_owner':value['owner']['owner_run_id']=str(uuid4())
        elif change=='new_generation':value['owner']['owner_generation']+=1;value['quiescence']['owner_generation']+=1
        else:value['operation']['run_id']=str(uuid4())
    if phase=='stage':mutate()
    async def get(path):return value
    f.client._get=get
    worker,receipt,calls=followup_worker(f,during=mutate if phase=='result' else None)
    asyncio.run(worker.step(receipt))
    assert f.jobs.peek(receipt['request_id'])['state']=='HOLD'
    assert len(calls)==(0 if phase=='stage' else 1)


def test_live_reboot_before_final_goal_send_cannot_rebind_old_selection(tmp_path):
    from functools import partial
    from fleet.server.goal_lease import GoalLeases
    from fleet.server.channel.execution.outcomes.task_receipt import prepare_send
    f=completed_turn(tmp_path)
    worker,receipt,calls=followup_worker(f)
    asyncio.run(worker.step(receipt));asyncio.run(f.worker.step(receipt['request_id']))
    context=calls[0].accepted_execution_context
    leases=GoalLeases(0,{})
    leases.admit_attempt=f.service.admit_attempt
    leases.native_required=f.service.native_required
    leases.bind_native_receipt=f.service.bind_native_receipt
    leases.selected_context=lambda task_id:context
    leases.prepare_send=partial(prepare_send,leases)
    value=_readback(f.task['receipt']['operation']);value['owner']['boot_id']=str(uuid4())
    async def get(path):return value
    sent=[]
    async def goal(*args,**kwargs):sent.append(kwargs);return {'accepted':False}
    f.client._get=get;f.client.navigation_goal=goal
    async def dispatch(task):
        return await leases.send('rosy_40',f.client,{},1.,2.,0.,task['attempt_id'],task_id=task['task_id'])
    result=asyncio.run(f.service.dispatch_next({'rosy_40'},dispatch=dispatch))
    assert not sent and result['status']=='FAILED'
    assert not (result['receipt'] or {}).get('native_required')
    assert not f.store.resource_claims(resource_kind='robot',resource_id='rosy_40')


@pytest.mark.parametrize('race',[False,True])
def test_followup_forwards_selected_epoch_to_public_core_cas(tmp_path,monkeypatch,race):
    from functools import partial
    from uuid import UUID
    from core_common.protocol.native import receipts as native
    from fleet.server.goal_lease import GoalLeases
    from fleet.server.channel.execution.outcomes.task_receipt import prepare_send
    f=completed_turn(tmp_path)
    worker,receipt,calls=followup_worker(f)
    asyncio.run(worker.step(receipt));asyncio.run(f.worker.step(receipt['request_id']))
    context=calls[0].accepted_execution_context
    core=native.NativeReceipts();core.generation=context['owner_generation']
    monkeypatch.setattr(native,'BOOT_ID',UUID(context['boot_id']))
    leases=GoalLeases(0,{})
    leases.admit_attempt=f.service.admit_attempt
    leases.native_required=f.service.native_required
    leases.bind_native_receipt=f.service.bind_native_receipt
    leases.selected_context=f.journal.context_for_task
    leases.prepare_send=partial(prepare_send,leases)
    async def get(path):
        assert path.endswith('?run_id='+context['run_id'])
        value=_readback(f.task['receipt']['operation'])
        if race:monkeypatch.setattr(native,'BOOT_ID',uuid4())
        return value
    received=[];admitted=[]
    async def goal(*args,**kwargs):
        received.append(kwargs)
        try:core.expect(UUID(kwargs['expected_boot_id']),kwargs['expected_owner_generation'])
        except ValueError:return {'accepted':False}
        operation=core.admit('navigate',kwargs['correlation_id']).model_dump(mode='json')
        admitted.append(operation)
        return {'accepted':True,'operation':operation}
    f.client._get=get;f.client.navigation_goal=goal
    async def dispatch(task):
        return await leases.send('rosy_40',f.client,{},1.,2.,0.,task['attempt_id'],task_id=task['task_id'])
    result=asyncio.run(f.service.dispatch_next({'rosy_40'},dispatch=dispatch))
    assert len(received)==1 and received[0]['expected_boot_id']==context['boot_id']
    assert received[0]['expected_owner_generation']==context['owner_generation']
    assert len(admitted)==(0 if race else 1)
    assert result['status']==('FAILED' if race else 'ACCEPTED')
    if race:assert not f.store.resource_claims(resource_kind='robot',resource_id='rosy_40')
