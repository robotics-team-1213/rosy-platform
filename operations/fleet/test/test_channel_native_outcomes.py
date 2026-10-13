"""A CORE ACK and a Fleet claim are separate from exact native completion."""

import asyncio
import json
from types import SimpleNamespace
from uuid import uuid4
import pytest

from test_channel_natural_execution import fixture


HOME_TEXT = "40번 홈으로 복귀해줘"
HOME_PLAN = {"do": "home", "robot": "rosy_40"}


def _readback(operation, *, result='SUCCEEDED', quiescent=True):
    return {'lookup':'FOUND', 'operation':operation | {'phase':'TERMINAL','result':result},
        'owner':{'boot_id':operation['boot_id'],'owner_generation':7,'owner_run_id':None},
        'quiescence':{'boot_id':operation['boot_id'],'requested_run_id':operation['run_id'],
            'owner_run_id':None,'owner_generation':7,'transport_generation':11,
            'observed_at':'2026-10-12T12:00:00Z','admitting':False,'pending_submission':False,
            'actuating_callback':False,'lease_active':False,'quiescent':quiescent}}


def _operation(run_id, boot_id, correlation_id, *, phase="SUBMITTED", result=None):
    return {
        "run_id": str(run_id), "boot_id": str(boot_id), "kind": "home",
        "correlation_id": correlation_id, "phase": phase, "result": result,
        "reason": None,
    }


def _home_with_native_ack(tmp_path):
    f = fixture(tmp_path, HOME_TEXT, HOME_PLAN)
    run_id, boot_id = uuid4(), uuid4()
    sent = []
    async def owner(path):return {'owner':{'boot_id':str(boot_id),'owner_generation':0,'owner_run_id':None}}
    f.client._get=owner

    async def post(path, body):
        sent.append((path, body))
        cid = body.get("correlation_id") if isinstance(body, dict) else None
        return {"accepted": True, "mode": "NAVIGATION",
                "operation": _operation(run_id, boot_id, cid)}

    f.client._post = post
    asyncio.run(f.worker.step(f.receipt["request_id"]))
    return f, run_id, boot_id, sent


def test_direct_ack_persists_core_run_and_caller_identity_without_completion(tmp_path):
    f, run_id, boot_id, sent = _home_with_native_ack(tmp_path)
    step = f.journal.view(f.receipt["request_id"])["steps"][0]

    assert len(sent) == 1
    assert isinstance(sent[0][1], dict) and sent[0][1].get("correlation_id")
    assert step["state"] == "ACCEPTED"
    assert json.loads(step["receipt_json"])["operation"] == _operation(
        run_id, boot_id, sent[0][1]["correlation_id"])
    assert f.store.resource_claims(resource_kind="robot", resource_id="rosy_40")


@pytest.mark.parametrize('verb,text,kind', [('cancel', '40번 이동 취소해줘', 'navigate'),
                                          ('follow_cancel', '40번 추종 취소해줘', 'follow')])
def test_native_stop_closes_without_releasing_another_owner_or_advancing(tmp_path, verb, text, kind):
    f = fixture(tmp_path, text + ' 그리고 ' + HOME_TEXT,
                {'steps': [{'do': verb, 'robot': 'rosy_40'}, HOME_PLAN]})
    rid = f.receipt['request_id']
    operation = _operation(uuid4(), uuid4(), 'original-motion') | {'kind': kind}
    assert f.store.reserve_resources(owner_kind='direct_action', owner_id='original-motion',
        generation=f.store.dispatch_control()['generation'], resources=[('robot', 'rosy_40')])
    sent = []
    async def cancel(*args):
        sent.append(True)
        return {'navigation': 'CANCELED', 'role': 'none', 'active': False,
                'target_robot_id': None, 'operation': operation}
    f.client.navigation_cancel = cancel
    f.client._post = cancel
    asyncio.run(f.worker.step(rid))
    async def get(path):
        return _readback(operation, result='CANCELED')
    f.client._get = get
    asyncio.run(f.worker.step(rid))
    step = f.journal.view(rid)['steps'][0]
    assert step['state'] == 'CANCELED'
    evidence = json.loads(step['receipt_json'])
    assert evidence['outcome']['result'] == 'CANCELED'
    assert evidence['quiescence']['quiescent'] is True
    assert evidence.get('safe_released') is not True
    assert rid not in f.worker.pending()
    assert f.store.resource_claims(resource_kind='robot', resource_id='rosy_40')[0]['owner_id'] == 'original-motion'
    asyncio.run(f.worker.step(rid))
    assert len(sent) == 1


def test_site_stop_preserves_each_robot_native_receipt():
    from core_common.intent import interpret
    from fleet.server.channel.execution.receipts import owner_receipt
    operation = _operation(uuid4(), uuid4(), 'motion')
    accepted, receipt = owner_receipt(interpret({'do': 'estop'})[0], {'robots': [
        {'robot_id': 'rosy_40', 'stopped': True, 'result': {'estop': True, 'operation': operation}},
        {'robot_id': 'rosy_41', 'stopped': False, 'result': {}}]}, ['rosy_40', 'rosy_41'])
    assert accepted is None
    assert receipt['robots'][0]['operation'] == operation
    assert 'operation' not in receipt['robots'][1]


@pytest.mark.parametrize('site,empty,fault', [(s,e,'none') for s in (False,True) for e in (False,True)] +
    [(True,False,f) for f in ('delayed','reboot','row','pruned','conflict','partial','revoked')])
def test_safety_stop_closes_all_captured_owners_without_borrowed_release(tmp_path, monkeypatch, site, empty, fault):
    from fleet.server.channel.execution.outcomes import reconcile, stops
    tick = [10.]
    monkeypatch.setattr(reconcile, 'time', SimpleNamespace(monotonic=lambda: tick[0]))
    monkeypatch.setattr(stops, 'time', SimpleNamespace(monotonic=lambda: tick[0]))
    text, plan = ('전체 비상정지해', {'do': 'estop'}) if site else ('40번 비상정지해', {'do': 'stop', 'robot': 'rosy_40'})
    f = fixture(tmp_path, text, plan, extra_robots=('rosy_41',) if site else ())
    robots = f.worker.execution.console.robot_ids
    boot, sent, values = str(uuid4()), [], {}
    for robot in robots:
        assert f.store.reserve_resources(owner_kind='direct_action', owner_id='motion:' + robot,
            generation=f.store.dispatch_control()['generation'], resources=[('robot', robot)])
        with f.store._connect() as conn, conn:
            conn.execute("UPDATE fleet_action_claims SET phase='UNKNOWN' WHERE owner_id=?", ('motion:' + robot,))
        values[robot] = [dict(_operation(uuid4(), boot, robot), kind=kind) for kind in ('navigate', 'teleop')]
        if fault in {'pruned','conflict'}:
            values[robot] = [op | {'phase':'TERMINAL','result':'CANCELED'} for op in values[robot]]
    async def stop():
        sent.append(True)
        return {'estop': True, 'operations': [] if empty else values['rosy_40']}
    async def stop_all():
        sent.append(True)
        return {'robots': [{'robot_id': robot, 'stopped': True,
                           'result': {'estop': True, 'operations': [] if empty else values[robot]}}
                          for robot in (robots[:-1] if fault == 'partial' else robots)]}
    quiescent = [False]
    def client(robot):
        async def get(path):
            operation = next(op for op in values[robot] if op['run_id'] in path)
            value = _readback(operation, result='SUCCEEDED' if fault == 'conflict' else 'CANCELED', quiescent=quiescent[0])
            if fault == 'pruned': return {'lookup':'UNKNOWN','operation':None}
            if fault == 'reboot': value['owner']['boot_id'] = str(uuid4())
            if fault == 'delayed' and quiescent[0]: tick[0] += 2.01
            if fault == 'row' and quiescent[0]:
                with f.store._connect() as conn, conn:
                    conn.execute('UPDATE fleet_channel_execution_steps SET caller_cid=?', (str(uuid4()),))
            return value
        return SimpleNamespace(_get=get, estop=stop)
    f.worker.execution.console._client = client
    f.worker.execution.console.estop_all = stop_all
    rid = f.receipt['request_id']
    asyncio.run(f.worker.step(rid))
    if fault == 'revoked': f.raw.withdraw(f.receipt['guild_id'], f.receipt['channel_id'], f.receipt['message_id'])
    asyncio.run(f.worker.step(rid))
    current = f.journal.view(rid)['steps'][0]
    if empty or fault == 'partial':
        assert current['state'] == 'HOLD' and rid not in f.worker.pending()
    else:
        assert current['state'] == 'UNKNOWN' and rid in f.worker.pending()
        quiescent[0] = True
        asyncio.run(f.worker.step(rid))
        current = f.journal.view(rid)['steps'][0]
        closed = fault in {'none','revoked'}
        assert current['state'] == ('CANCELED' if closed else 'UNKNOWN')
        assert (rid not in f.worker.pending()) == closed
        receipt = json.loads(current['receipt_json'])
        assert len(receipt['stop_outcomes']) == len(robots) * 2
        if closed: assert all(item['quiescence']['quiescent'] for item in receipt['stop_outcomes'])
        if fault in {'pruned','conflict'}: assert all(item['outcome']['result']=='CANCELED' for item in receipt['stop_outcomes'])
        assert not receipt.get('safe_released')
    assert len(sent) == 1
    assert all(f.store.resource_claims(resource_kind='robot', resource_id=robot) for robot in robots)


@pytest.mark.parametrize('change',['run','boot','unknown','owner','pending','callback','lease','admitting','epoch','transport','missing'])
def test_unproven_readback_cannot_release_claim(tmp_path,change):
    f, run_id, boot_id, sent = _home_with_native_ack(tmp_path)
    rid=f.receipt['request_id']; op=json.loads(f.journal.view(rid)['steps'][0]['receipt_json'])['operation']
    value=_readback(op)
    if change in {'run','boot'}:value['operation'][change+'_id']=str(uuid4())
    elif change=='unknown':value['lookup']='UNKNOWN';value['operation']=None
    elif change=='owner':value['owner']['owner_run_id']=str(uuid4())
    elif change=='epoch':value['owner']['owner_generation']+=1
    elif change=='transport':value['quiescence']['transport_generation']=True
    elif change=='missing':del value['quiescence']['lease_active']
    else:value['quiescence'][{'pending':'pending_submission','callback':'actuating_callback','lease':'lease_active'}.get(change,change)]=True
    async def get(path):return value
    f.client._get=get
    asyncio.run(f.worker.step(rid))
    assert f.journal.view(rid)['steps'][0]['state']!='COMPLETED'
    assert f.store.resource_claims(resource_kind='robot',resource_id='rosy_40')
    assert len(sent)==1


@pytest.mark.parametrize('change',['delayed','reassigned','extra_claim','step_generation','step_resources','step_cid'])
def test_release_cas_rechecks_elapsed_and_exact_sqlite_claim(tmp_path,monkeypatch,change):
    from fleet.server.channel.execution.outcomes import reconcile
    f, _, _, sent=_home_with_native_ack(tmp_path)
    rid=f.receipt['request_id']; row=f.journal.view(rid)['steps'][0]
    value=_readback(json.loads(row['receipt_json'])['operation']); tick=[10.]
    monkeypatch.setattr(reconcile,'time',SimpleNamespace(monotonic=lambda:tick[0]))
    async def get(path):
        if change=='delayed':tick[0]+=2.01
        with f.store._connect() as conn,conn:
            if change=='reassigned':conn.execute("UPDATE fleet_action_claims SET owner_id='other',generation=generation+1")
            if change=='step_generation':conn.execute('UPDATE fleet_channel_execution_steps SET generation=generation+1')
            if change=='step_resources':conn.execute("UPDATE fleet_channel_execution_steps SET resources_json='[]'")
            if change=='step_cid':conn.execute("UPDATE fleet_channel_execution_steps SET caller_cid='changed'")
        if change=='extra_claim':f.store.reserve_resources(owner_kind='direct_action',owner_id=row['owner_id'],generation=row['generation'],resources=[('robot','rosy_41')])
        return value
    f.client._get=get;asyncio.run(f.worker.step(rid))
    assert f.store.resource_claims(resource_kind='robot',resource_id='rosy_40')
    assert f.journal.view(rid)['steps'][0]['state']!='COMPLETED' and len(sent)==1


@pytest.mark.parametrize('revoked',['expiry','role','withdraw'])
def test_closure_survives_revoked_origin_and_suppresses_next_step(tmp_path,revoked):
    plan={'steps':[HOME_PLAN,HOME_PLAN]}
    f=fixture(tmp_path,HOME_TEXT+' 그리고 '+HOME_TEXT,plan)
    sent=[]; operation=_operation(uuid4(),uuid4(),None)
    async def owner(path):return {'owner':{'boot_id':operation['boot_id'],'owner_generation':0,'owner_run_id':None}}
    f.client._get=owner
    async def post(path,body):
        sent.append(body);operation['correlation_id']=body['correlation_id']
        return {'accepted':True,'operation':dict(operation)}
    f.client._post=post;rid=f.receipt['request_id'];asyncio.run(f.worker.step(rid))
    if revoked=='expiry':f.clock[0]+=121
    elif revoked=='role':f.accounts['op']='viewer'
    else:f.raw.withdraw(f.receipt['guild_id'],f.receipt['channel_id'],f.receipt['message_id'])
    async def get(path):return _readback(operation)
    f.client._get=get;asyncio.run(f.worker.step(rid))
    rows=f.journal.view(rid)['steps']
    assert rows[0]['state']=='COMPLETED' and rows[1]['state']=='HOLD' and len(sent)==1
    assert not f.store.resource_claims(resource_kind='robot',resource_id='rosy_40')
    with f.store._connect() as conn:
        outcome=conn.execute("SELECT state FROM fleet_channel_reply_outbox WHERE kind LIKE 'EXECUTION:0:NATIVE:%'").fetchone()
    assert outcome['state']==('PENDING' if revoked=='expiry' else 'SUPERSEDED')


def test_two_sqlite_workers_release_once_and_preserve_original_reply(tmp_path):
    from fleet.server.task_store import FleetTaskStore
    from fleet.server.channel.execution.journal import ExecutionJournal
    from fleet.server.channel.execution.worker import ExecutionWorker
    f,_,_,sent=_home_with_native_ack(tmp_path);rid=f.receipt['request_id']
    operation=json.loads(f.journal.view(rid)['steps'][0]['receipt_json'])['operation']
    second=ExecutionWorker(ExecutionJournal(f.jobs,FleetTaskStore(f.store.path),producer_scope=f.scope,
        admitted=lambda:True,environment=lambda:f.env,clock=lambda:f.clock[0]),f.worker.execution)
    async def race():
        barrier=asyncio.Event(); reads=[]
        async def get(path):
            reads.append(path)
            if len(reads)==2:barrier.set()
            await barrier.wait()
            return _readback(operation)
        f.client._get=get
        await asyncio.gather(f.worker.step(rid),second.step(rid))
    asyncio.run(race());f.journal.recover();asyncio.run(second.step(rid))
    assert f.journal.view(rid)['steps'][0]['state']=='COMPLETED' and len(sent)==1
    assert not f.store.resource_claims(resource_kind='robot',resource_id='rosy_40')
    with f.store._connect() as conn:
        assert conn.execute("SELECT count(*) FROM fleet_channel_reply_outbox WHERE kind LIKE 'EXECUTION:0:NATIVE:%'").fetchone()[0]==1


@pytest.mark.parametrize('result',['FAILED','CANCELED','PREEMPTED','EXPIRED'])
def test_non_success_terminal_releases_without_goal_success(tmp_path,result):
    f,_,_,sent=_home_with_native_ack(tmp_path);rid=f.receipt['request_id']
    operation=json.loads(f.journal.view(rid)['steps'][0]['receipt_json'])['operation']
    async def get(path):return _readback(operation,result=result)
    f.client._get=get;asyncio.run(f.worker.step(rid))
    row=f.journal.view(rid)['steps'][0]
    assert row['state']=='FAILED' and json.loads(row['receipt_json'])['outcome']['result']==result
    assert not f.store.resource_claims(resource_kind='robot',resource_id='rosy_40') and len(sent)==1


def test_next_motion_uses_new_owner_epoch_after_release(tmp_path):
    f=fixture(tmp_path,HOME_TEXT+' 그리고 '+HOME_TEXT,{'steps':[HOME_PLAN,HOME_PLAN]})
    boot=str(uuid4());operations=[];bodies=[]
    async def get(path):
        if 'run_id=' in path:return _readback(operations[0])
        return {'owner':{'boot_id':boot,'owner_generation':20+len(bodies),'owner_run_id':None}}
    async def post(path,body):
        bodies.append(body);op=_operation(uuid4(),boot,body['correlation_id']);operations.append(op)
        return {'accepted':True,'operation':op}
    f.client._get=get;f.client._post=post;rid=f.receipt['request_id']
    asyncio.run(f.worker.step(rid));asyncio.run(f.worker.step(rid))
    assert [b['expected_owner_generation'] for b in bodies]==[20,21]
    assert bodies[0]['correlation_id']!=bodies[1]['correlation_id']
    assert [r['state'] for r in f.journal.view(rid)['steps']]==['COMPLETED','ACCEPTED']


@pytest.mark.parametrize('kind',['follow','teleop'])
def test_follow_hold_and_teleop_expiry_are_not_completion(tmp_path,kind):
    text='40번 41번 따라가줘' if kind=='follow' else '40번 선속도 0.1 m/s 각속도 0 rad/s로 움직여줘'
    plan={'do':'follow','robot':'rosy_40','target_robot_id':'rosy_41'} if kind=='follow' else {'do':'move','robot':'rosy_40','linear':.1,'angular':0.}
    f=fixture(tmp_path,text,plan,extra_robots=('rosy_41',));sent=[]
    op=_operation(uuid4(),uuid4(),None)|{'kind':kind}
    async def owner(path):return {'owner':{'boot_id':op['boot_id'],'owner_generation':0,'owner_run_id':None}}
    f.client._get=owner
    async def state():return {'mode':'MANUAL' if kind=='teleop' else 'IDLE','safety':{'estop':False}}
    async def post(path,body):
        sent.append(body);op['correlation_id']=body['correlation_id']
        return {'accepted':True,'operation':dict(op)}
    async def follow(params):
        sent.append(params);op['correlation_id']=params.correlation_id
        return {'role':'follower','active':True,'target_robot_id':'rosy_41','operation':dict(op)}
    f.client.state=state;f.client._post=post;f.client.follow=follow;rid=f.receipt['request_id']
    asyncio.run(f.worker.step(rid))
    async def get(path):
        value=_readback(op,result='EXPIRED' if kind=='teleop' else 'SUCCEEDED')
        if kind=='follow':
            value['operation']=op|{'phase':'RUNNING'}
            value['quiescence']['quiescent']=False
        return value
    f.client._get=get;asyncio.run(f.worker.step(rid));f.journal.recover();asyncio.run(f.worker.step(rid))
    assert f.journal.view(rid)['steps'][0]['state']==('RUNNING' if kind=='follow' else 'FAILED')
    assert bool(f.store.resource_claims(resource_kind='robot',resource_id='rosy_40'))==(kind=='follow')
    assert len(sent)==1


@pytest.mark.parametrize('event_type,source,result,reason', [
    ('nav.completed', None, 'SUCCEEDED', None),
    ('nav.canceled', 'goal_lease', 'EXPIRED', 'LEASE_EXPIRED'),
    ('nav.canceled', 'stuck_detector', 'FAILED', 'STUCK'),
    ('nav.canceled', 'safety:estop', 'CANCELED', 'SAFETY_STOP'),
    ('nav.canceled', 'api:operator', 'CANCELED', 'CANCELED')])
def test_pruned_exact_event_keeps_result_without_release_or_cid_inference(tmp_path,event_type,source,result,reason):
    from fleet.observe.events import CoreEventStore
    f,_,_,sent=_home_with_native_ack(tmp_path);rid=f.receipt['request_id']
    op=json.loads(f.journal.view(rid)['steps'][0]['receipt_json'])['operation']
    f.service.core_events=CoreEventStore(f.store.path)
    f.service.core_events.append_event({'robot_id':'rosy_40','event_id':'terminal','seq':1,
        'type':event_type,'data':{k:op[k] for k in ('run_id','boot_id','correlation_id')} | {'source':source}})
    async def get(path):return {'lookup':'UNKNOWN','operation':None,'quiescence':None}
    f.client._get=get;asyncio.run(f.worker.step(rid))
    receipt=json.loads(f.journal.view(rid)['steps'][0]['receipt_json'])
    assert receipt['outcome']['result']==result and receipt['outcome']['reason']==reason and not receipt.get('safe_released')
    assert f.store.resource_claims(resource_kind='robot',resource_id='rosy_40') and len(sent)==1


@pytest.mark.parametrize('mismatch',['boot','kind','cid','negative','missing'])
def test_ambiguous_native_ack_keeps_claim_and_never_replays(tmp_path,mismatch):
    f=fixture(tmp_path,HOME_TEXT,HOME_PLAN);sent=[]
    async def post(path,body):
        sent.append(body)
        op=_operation(uuid4(),body['expected_boot_id'],body['correlation_id'])
        if mismatch=='boot':op['boot_id']=str(uuid4())
        if mismatch=='kind':op['kind']='dock'
        if mismatch=='cid':op['correlation_id']='someone-else'
        return {'accepted':mismatch!='negative',**({'operation':op} if mismatch!='missing' else {})}
    f.client._post=post;rid=f.receipt['request_id']
    asyncio.run(f.worker.step(rid));f.journal.recover();asyncio.run(f.worker.step(rid))
    assert f.journal.view(rid)['steps'][0]['state']=='UNKNOWN'
    assert f.store.resource_claims(resource_kind='robot',resource_id='rosy_40') and len(sent)==1


def test_pending_native_evidence_does_not_require_current_model_grant(tmp_path):
    f,_,_,sent=_home_with_native_ack(tmp_path);rid=f.receipt['request_id']
    op=json.loads(f.journal.view(rid)['steps'][0]['receipt_json'])['operation']
    with f.store._connect() as conn,conn:
        conn.execute("UPDATE fleet_channel_conversation_jobs SET state='UNKNOWN',result_json=NULL")
        conn.execute("UPDATE fleet_channel_execution SET reason='GRANT_WITHDRAWN'")
    assert rid in f.worker.pending()
    async def get(path):return _readback(op)
    f.client._get=get;asyncio.run(f.worker.step(rid,allow_dispatch=False))
    assert f.journal.view(rid)['steps'][0]['state']=='COMPLETED' and len(sent)==1


def test_crash_after_task_release_before_step_projection_never_resends(tmp_path):
    from fleet.server.channel.execution.outcomes.reconcile import task_result
    f=fixture(tmp_path,'40번 A로 보내줘 그리고 '+HOME_TEXT,
              {'steps':[{'do':'navigate','robot':'rosy_40','waypoint':'A'},HOME_PLAN]})
    rid=f.receipt['request_id'];asyncio.run(f.worker.step(rid));sent=[]
    async def dispatch(attempt):
        sent.append(attempt['attempt_id'])
        return {'accepted':True,'operation':_operation(uuid4(),uuid4(),attempt['attempt_id'])|{'kind':'navigate'}}
    task=asyncio.run(f.service.dispatch_next({'rosy_40'},dispatch=dispatch))
    async def get(path):return _readback(task['receipt']['operation'])
    asyncio.run(task_result(f.store,SimpleNamespace(_get=get),task))
    assert f.journal.view(rid)['steps'][0]['state']=='TASK_QUEUED'
    f.store.close_dispatch_for_startup();f.journal.recover()
    asyncio.run(f.worker.step(rid))
    assert [r['state'] for r in f.journal.view(rid)['steps']]==['COMPLETED','HOLD']
    assert len(sent)==1 and not f.writes


def test_terminal_result_does_not_advance_until_exact_quiescence(tmp_path):
    f, run_id, boot_id, sent = _home_with_native_ack(tmp_path)
    cid = sent[0][1].get("correlation_id") if isinstance(sent[0][1], dict) else None
    state = {
        "lookup": "FOUND",
        "operation": _operation(run_id, boot_id, cid, phase="TERMINAL", result="SUCCEEDED"),
        "owner": {"boot_id": str(boot_id), "owner_generation": 4, "owner_run_id": None},
        "quiescence": {
            "boot_id": str(boot_id), "requested_run_id": str(run_id),
            "owner_run_id": None, "observed_at": "2026-10-12T12:00:00Z",
            "owner_generation": 4, "transport_generation": 8,
            "admitting": False, "pending_submission": True,
            "actuating_callback": False, "lease_active": False, "quiescent": False,
        },
    }
    reads = []

    async def get(path):
        reads.append(path)
        return state

    f.client._get = get
    rid = f.receipt["request_id"]
    asyncio.run(f.worker.step(rid))
    assert f.journal.view(rid)["steps"][0]["state"] != "COMPLETED"
    assert f.store.resource_claims(resource_kind="robot", resource_id="rosy_40")

    state["quiescence"]["pending_submission"] = False
    state["quiescence"]["quiescent"] = True
    asyncio.run(f.worker.step(rid))
    assert reads and all("run_id=" + str(run_id) in path for path in reads)
    assert f.journal.view(rid)["steps"][0]["state"] == "COMPLETED"
    assert f.store.resource_claims(resource_kind="robot", resource_id="rosy_40") == []
    assert len(sent) == 1


def test_expired_origin_allows_read_only_closure_but_no_new_rpc(tmp_path):
    f, run_id, boot_id, sent = _home_with_native_ack(tmp_path)
    cid = sent[0][1].get("correlation_id") if isinstance(sent[0][1], dict) else None

    async def get(path):
        assert "run_id=" + str(run_id) in path
        return {
            "lookup": "FOUND",
            "operation": _operation(run_id, boot_id, cid, phase="TERMINAL", result="SUCCEEDED"),
            "owner": {"boot_id": str(boot_id), "owner_generation": 2, "owner_run_id": None},
            "quiescence": {
                "boot_id": str(boot_id), "requested_run_id": str(run_id),
                "owner_run_id": None, "observed_at": "2026-10-12T12:00:00Z",
                "owner_generation": 2, "transport_generation": 3,
                "admitting": False, "pending_submission": False,
                "actuating_callback": False, "lease_active": False, "quiescent": True,
            },
        }

    f.client._get = get
    f.clock[0] += 121
    asyncio.run(f.worker.step(f.receipt["request_id"]))
    assert f.journal.view(f.receipt["request_id"])["steps"][0]["state"] == "COMPLETED"
    assert f.store.resource_claims(resource_kind="robot", resource_id="rosy_40") == []
    assert len(sent) == 1
