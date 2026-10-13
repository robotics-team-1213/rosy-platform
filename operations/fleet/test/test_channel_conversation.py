"""Natural model proposals preserve original authority and close real durable replies."""
import asyncio
import hashlib

import pytest
from fastapi import HTTPException

from rosy.decision.conversation.codec import (Profile, Answer, History, bounded_environment,
    conversation_input, checked_answer, digest, source_policy)
from fleet.server.channel.conversation.jobs import ConversationJobs
from fleet.server.channel.conversation.worker import ConversationWorker
from test_channel_model_jobs import model_jobs


def environment():
    return {'robots':[{'robot_id':'rosy_40', 'online':True,
        'state':{'mode':'IDLE', 'safety':{'estop':False}, 'line_follow':{'state':'OFF'}}}],
        'map':{'version':1, 'sha256':'a'*64,
            'places':[{'id':'A', 'name':'A 지점', 'x':1., 'y':2., 'yaw':None}]}, 'work_catalog':[]}


def receipt_text(receipt, text):
    return {**receipt, 'content':text, 'content_hash':hashlib.sha256(text.encode()).hexdigest()}


def answer(kind='CHAT', **values):
    return {'kind':kind, 'response':'안녕하세요. 무엇을 도와드릴까요?', 'intent':None,
        'evidence_refs':[], 'review_required':False} | values


def test_online_environment_normalization_is_idempotent():
    raw = bounded_environment(environment())
    assert bounded_environment(raw) == raw
    assert raw['robots'][0]['mode'] == 'IDLE' and raw['robots'][0]['estop'] is False


def test_full_original_multiline_question_and_only_bot_mention_removed(tmp_path):
    _, journal, _, receipt, _, _, clock = model_jobs(tmp_path)
    text = '<@'+journal.config.bot_id+'> 안녕\n'+('질문 '*400)+'<@12345678901234567>'
    value = conversation_input(receipt_text(receipt, text), environment(), journal.config.bot_id, now=clock[0])
    assert value.question == text.replace('<@'+journal.config.bot_id+'>', '').strip()
    assert len(value.question) > 128


@pytest.mark.parametrize('change',['principal_id','author_id','channel_id','guild_id','expired','map'])
def test_history_never_crosses_owner_channel_expiry_or_map(tmp_path, change):
    _, journal, _, receipt, _, _, clock = model_jobs(tmp_path)
    value = conversation_input(receipt, environment(), journal.config.bot_id, now=clock[0])
    h = {k:getattr(value,k) for k in ('request_id','principal_id','author_id','channel_id','guild_id','question','content_hash')}
    h |= {'answered_at':clock[0], 'environment_hash':digest(value.environment), 'kind':'CHAT', 'intent':None}
    if change == 'expired':h['answered_at']-=121
    elif change == 'map':h['environment_hash']='b'*64
    else:h[change] = 'different' if change == 'principal_id' else '11111111111111111'
    with pytest.raises(ValueError):conversation_input(receipt, environment(), journal.config.bot_id,
        [History(**h)], now=clock[0])


@pytest.mark.parametrize('bad',[
    answer('CHAT',response='rosy_40 온라인입니다.'), answer(response='@everyone 안녕'),
    answer('CHAT',response='40번을 A로 보내드릴게요.'),
    answer('CHAT',response='현재 로봇은 IDLE 상태입니다.'),
    answer(response='password=secret'), answer('CONTROL',intent={'do':'move','robot':'unknown','linear':1.}),
    answer('CONTROL',intent={'do':'navigate','robot':'rosy_40','waypoint':'unknown'}),
    answer('CONTROL',intent={'do':'navigate','robot':'rosy_40','waypoint':'A','x':999.,'y':2.}),
    answer('CONTROL',intent={'do':'reset_estop','robot':'rosy_40'}),
    answer('STATUS',evidence_refs=['robot:unknown']),
])
def test_untrusted_answer_rejects_unknown_scope_facts_secrets_and_reset(tmp_path,bad):
    _,journal,_,receipt,_,_,clock=model_jobs(tmp_path)
    question=conversation_input(receipt,environment(),journal.config.bot_id,now=clock[0])
    with pytest.raises(ValueError):checked_answer(bad,question)


def worker_fixture(tmp_path, *, text='안녕', change=None, output=None):
    _, journal, accounts, receipt, _, _, clock = model_jobs(tmp_path)
    updated=receipt_text(receipt,text)
    with journal._connect() as conn:
        import json
        conn.execute('UPDATE fleet_channel_requests SET receipt=?',(json.dumps(updated),))
    profile=Profile(revision='d728-test')
    jobs=ConversationJobs(journal,digest(profile.model_dump()),clock=lambda:clock[0])
    snapshot=environment()|{'observed_at':clock[0]}
    calls=[]
    async def current():return snapshot
    async def provider(question,p,remaining):
        calls.append(question)
        assert jobs.peek(updated['request_id'])['state']=='RUNNING'
        if change=='owner':accounts['op']='viewer'
        if change=='map':snapshot['map']['version']=2
        if change=='cancel':raise asyncio.CancelledError()
        return output or answer()
    worker=ConversationWorker(jobs,current,profile,provider,clock=lambda:clock[0],
        admission=lambda:change!='unadmitted',observation_guard=lambda e:bounded_environment(snapshot)==e)
    return worker,jobs,journal,updated,calls


def test_actual_worker_records_model_result_and_natural_reply_once(tmp_path):
    worker,jobs,journal,receipt,calls=worker_fixture(tmp_path)
    asyncio.run(worker.step(receipt));asyncio.run(worker.step(receipt))
    assert len(calls)==1 and jobs.peek(receipt['request_id'])['state']=='ANSWERED'
    with journal._connect() as conn:
        rows=conn.execute("SELECT content FROM fleet_channel_reply_outbox WHERE kind='CONVERSATION'").fetchall()
    assert rows==[('안녕하세요. 무엇을 도와드릴까요?',)]
    assert jobs.read(receipt['request_id'],'op')['action_admissible'] is False


@pytest.mark.parametrize('change',['owner','map','unadmitted'])
def test_final_origin_and_observation_fences(tmp_path,change):
    worker,jobs,_,receipt,calls=worker_fixture(tmp_path,change=change)
    asyncio.run(worker.step(receipt))
    assert jobs.peek(receipt['request_id'])['state'] in ('HOLD','SUPERSEDED')
    assert len(calls)==(0 if change=='unadmitted' else 1)


def test_cancel_and_restart_preserve_unknown_no_model_replay(tmp_path):
    worker,jobs,_,receipt,calls=worker_fixture(tmp_path,change='cancel')
    with pytest.raises(asyncio.CancelledError):asyncio.run(worker.step(receipt))
    jobs.recover();asyncio.run(worker.step(receipt))
    assert len(calls)==1 and jobs.peek(receipt['request_id'])['state']=='UNKNOWN'


def test_control_is_only_proposal_and_status_is_grounded(tmp_path):
    value=answer('CONTROL',intent={'do':'navigate','robot':'rosy_40','waypoint':'A'},evidence_refs=['robot:rosy_40','place:A'])
    worker,jobs,_,receipt,calls=worker_fixture(tmp_path,text='40번 로봇을 A 지점으로 보내줘',output=value)
    asyncio.run(worker.step(receipt))
    assert jobs.read(receipt['request_id'],'op')['result']['answer']['intent']==value['intent']
    assert jobs.read(receipt['request_id'],'op')['action_admissible'] is False
    with pytest.raises(HTTPException):jobs.read(receipt['request_id'],'other')


def test_independent_profile_policy_cannot_reuse_d720():
    with pytest.raises(ValueError):Profile(revision='d720-old')
    from fleet.server.channel.conversation.runtime import ConversationConfig
    profile=Profile(revision='d728-test')
    data={'host':'example','key_file':'/run/rosy-deliberation/broker.key',
        'known_hosts_file':'/run/rosy-deliberation/known_hosts','profile':profile.model_dump(),
        'source_commit':'a'*40,'valid_until':9999999999.,'primary_admitted':True,
        'semantic_evidence_sha256':'b'*64,'policy':{'authority':'read_only'}}
    with pytest.raises(ValueError):ConversationConfig(**data)
    data['policy']=source_policy(data['source_commit'],profile)
    assert ConversationConfig(**data).profile==profile


def test_local_semantic_broker_has_independent_codec():
    from deploy.ai_pc.deliberation_conversation import instruction
    assert 'CONTROL' in instruction() and 'proposal' in instruction() and '????' not in instruction()


@pytest.mark.parametrize('kind',['CLARIFY','REFUSE'])
def test_reason_reply_cannot_smuggle_model_device_success(tmp_path,kind):
    from rosy.decision.conversation.codec import reply
    _,journal,_,receipt,_,_,clock=model_jobs(tmp_path)
    question=conversation_input(receipt,environment(),journal.config.bot_id,now=clock[0])
    value=checked_answer(answer(kind,response='Everything healthy, robot movement completed.',reason='SAFETY'),question)
    result=reply(value,question)
    assert 'completed' not in result and '건강' not in result and '안전' in result


@pytest.mark.parametrize('change',['map','admission'])
def test_reservation_race_finishes_hold_reply_instead_of_ack_only(tmp_path,change,monkeypatch):
    worker,jobs,journal,receipt,calls=worker_fixture(tmp_path)
    original=jobs.reserve
    def reserve(*args):
        value=original(*args)
        if change=='map':asyncio.run(worker.snapshot())['map']['version']=2
        else:worker.admission=lambda:False
        return value
    monkeypatch.setattr(jobs,'reserve',reserve)
    asyncio.run(worker.step(receipt))
    assert calls==[] and jobs.peek(receipt['request_id'])['state']=='HOLD'
    with journal._connect() as conn:
        assert conn.execute("SELECT count(*) FROM fleet_channel_reply_outbox WHERE kind='CONVERSATION'").fetchone()[0]==1


def test_invalid_input_finishes_one_hold_and_never_model_retries(tmp_path):
    worker,jobs,journal,receipt,calls=worker_fixture(tmp_path)
    async def invalid():return {'observed_at':worker.clock(),'robots':[{}]}
    worker.snapshot=invalid
    asyncio.run(worker.step(receipt));asyncio.run(worker.step(receipt))
    assert calls==[] and jobs.peek(receipt['request_id'])['state']=='HOLD'
    with journal._connect() as conn:
        assert conn.execute("SELECT count(*) FROM fleet_channel_reply_outbox WHERE kind='CONVERSATION'").fetchone()[0]==1


def test_partial_large_catalog_declares_completeness_and_unknown_place_is_refused(tmp_path):
    _,journal,_,receipt,_,_,clock=model_jobs(tmp_path)
    env=environment()
    env['map']['places_complete']=False
    env['map']['places']=[{'id':f'P{i}', 'name':f'P{i}', 'x':float(i), 'y':0.} for i in range(64)]
    question=conversation_input(receipt,env,journal.config.bot_id,now=clock[0])
    assert question.environment['map']['places_complete'] is False
    with pytest.raises(ValueError):checked_answer(answer('CONTROL',
        intent={'do':'navigate','robot':'rosy_40','waypoint':'P400'}),question)


def test_flat_semantic_steps_map_existing_grammar_and_reject_arbitrary_parameters(tmp_path):
    from rosy.decision.conversation.codec import semantic_answer
    _,journal,_,receipt,_,_,clock=model_jobs(tmp_path)
    q=conversation_input(receipt,environment(),journal.config.bot_id,now=clock[0])
    value={'kind':'CONTROL','response':'제안을 기록합니다.','steps':[
        {'verb':'navigate','robot_id':'rosy_40','place_id':'A','parameters_json':'{}'}],
        'evidence_refs':[],'review_required':False,'reason':None}
    assert semantic_answer(value,q).intent=={'do':'navigate','robot':'rosy_40','waypoint':'A'}
    value['steps'][0]['parameters_json']='{"url":"https://unknown"}'
    with pytest.raises(ValueError):semantic_answer(value,q)


def test_pending_scope_changed_on_restart_never_reinterprets_original(tmp_path):
    worker,jobs,journal,receipt,calls=worker_fixture(tmp_path)
    snapshot=asyncio.run(worker.snapshot())
    q=jobs.build_input(receipt,snapshot,worker.clock())
    jobs.stage(receipt,q,snapshot)
    replacement=ConversationJobs(journal,'f'*64,clock=worker.clock)
    with pytest.raises(HTTPException):replacement.guard(receipt['request_id'])
    assert calls==[] and replacement.history(receipt,q.environment,worker.clock())==[]


def test_fixed_conversation_provider_binds_source_profile_input_and_command(tmp_path,monkeypatch):
    from fleet.server.channel.conversation import runtime
    _,journal,_,receipt,_,_,clock=model_jobs(tmp_path)
    profile=Profile(revision='d728-test')
    config=runtime.ConversationConfig(host='example',key_file='/run/rosy-deliberation/broker.key',
        known_hosts_file='/run/rosy-deliberation/known_hosts',profile=profile,source_commit='a'*40,
        valid_until=9999999999.,primary_admitted=False,semantic_evidence_sha256='b'*64,
        policy=source_policy('a'*40,profile))
    q=conversation_input(receipt,environment(),journal.config.bot_id,now=clock[0])
    calls=[]
    async def exchange(c,command,packet,remaining):
        import json
        value=json.loads(packet)
        calls.append((command,value))
        return {'source_commit':c.source_commit,'profile':profile.model_dump(),
                'input_hash':q.digest,'answer':answer(),'cost_usd':0.}
    monkeypatch.setattr(runtime,'exchange',exchange)
    assert asyncio.run(runtime.ConversationProvider(config)(q,profile,30))['kind']=='CHAT'
    assert calls[0][0]=='rosy-conversation-v1' and calls[0][1]['input_hash']==q.digest
    assert calls[0][1]['question']['content_hash']==receipt['content_hash']
    assert config.producer_scope()['source_commit']=='a'*40


def test_runtime_valid_large_site_catalog_does_not_block_greetings(tmp_path):
    import time
    from types import SimpleNamespace
    from fastapi import FastAPI
    from fleet.server.channel.conversation.runtime import ConversationConfig,install_conversation
    _,journal,_,_,_,_,_=model_jobs(tmp_path)
    profile=Profile(revision='d728-test')
    config=ConversationConfig(host='example',key_file='/run/rosy-deliberation/broker.key',
        known_hosts_file='/run/rosy-deliberation/known_hosts',profile=profile,source_commit='a'*40,
        valid_until=9999999999.,primary_admitted=False,semantic_evidence_sha256='b'*64,
        policy=source_policy('a'*40,profile))
    class Gather:
        _console=SimpleNamespace(_clock=time.monotonic)
        _snapshot={'robots':[{'robot_id':'rosy_40','online':False,'state':None}]}
        gathered_at=time.time()
        async def __call__(self):pass
    places=[{'id':f'P{i}','name':f'P{i}','x':float(i),'y':0.,'yaw':None} for i in range(500)]
    maps=SimpleNamespace(active_view=lambda:{'version':1,'sha256':'c'*64,'map':{'places':places}})
    app=FastAPI();app.state.channel_requests=journal;app.state.fleet_gather=Gather()
    install_conversation(app,config,maps)
    raw=asyncio.run(app.state.channel_conversation_worker.snapshot())
    assert len(raw['map']['places'])==64 and raw['map']['places_complete'] is False
    assert raw['map']['sha256']=='c'*64 and bounded_environment(raw)['robots'][0]['online'] is False
    config.policy['authority']='modified'
    assert app.state.channel_conversation_worker.admission() is False


@pytest.mark.parametrize('phase',['snapshot-reserved','snapshot-result','guard-before-provider','guard-result','guard-finish'])
def test_unavailable_observation_after_reserve_or_result_closes_hold_once(tmp_path,phase):
    worker,jobs,journal,receipt,calls=worker_fixture(tmp_path)
    snapshot=worker.snapshot
    guard=worker.observation_guard
    guard_calls=[0]
    async def unavailable():
        try:running=jobs.peek(receipt['request_id'])['state']=='RUNNING'
        except HTTPException:running=False
        if running and (phase=='snapshot-reserved' and not calls or phase=='snapshot-result' and calls):
            raise ValueError('STALE_STATUS_SNAPSHOT')
        return await snapshot()
    def missing_guard(basis):
        guard_calls[0]+=1
        if (phase=='guard-before-provider' and guard_calls[0]==3 or
                phase=='guard-result' and calls or phase=='guard-finish' and guard_calls[0]==5):
            raise KeyError('OBSERVATION_UNAVAILABLE')
        return guard(basis)
    worker.snapshot=unavailable;worker.observation_guard=missing_guard
    asyncio.run(worker.step(receipt));asyncio.run(worker.step(receipt));jobs.recover()
    assert jobs.peek(receipt['request_id'])['state']=='HOLD'
    assert len(calls)==(0 if phase in ('snapshot-reserved','guard-before-provider') else 1)
    with journal._connect() as conn:
        assert conn.execute("SELECT count(*) FROM fleet_channel_reply_outbox WHERE kind='CONVERSATION'").fetchone()[0]==1
        attempt=conn.execute('SELECT state,known_cost_usd FROM fleet_channel_conversation_attempts').fetchone()
    if calls:assert attempt==('RESULT',0.)


@pytest.mark.parametrize('expiry',[float('inf'),float('nan'),True])
def test_independent_conversation_expiry_must_be_finite_on_client_and_host(expiry,monkeypatch):
    import json
    import pwd
    from types import SimpleNamespace
    from fleet.server.channel.conversation.runtime import ConversationConfig
    from deploy.ai_pc import deliberation_conversation_broker as broker
    profile=Profile(revision='d728-test')
    policy=source_policy('a'*40,profile)
    common={'source_commit':'a'*40,'profile':profile.model_dump(),'valid_until':expiry,
            'semantic_evidence_sha256':hashlib.sha256(b'proof').hexdigest(),'policy':policy}
    with pytest.raises(ValueError):ConversationConfig(**common,host='example',
        key_file='/run/rosy-deliberation/broker.key',known_hosts_file='/run/rosy-deliberation/known_hosts',
        primary_admitted=False)
    host=common|{'files':{'proof.json':common['semantic_evidence_sha256']}}
    monkeypatch.setattr(pwd,'getpwnam',lambda _:SimpleNamespace(pw_uid=997))
    monkeypatch.setattr(broker.os,'getuid',lambda:997)
    monkeypatch.setattr(broker,'protected',lambda p:json.dumps(host).encode() if p==broker.CONFIG else b'proof')
    with pytest.raises(ValueError):broker.configuration()
