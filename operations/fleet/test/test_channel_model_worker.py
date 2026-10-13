"""A read-only response requires a current receipt and snapshot after every model await."""
import asyncio
from dataclasses import replace
from dataclasses import asdict
import hashlib

import pytest

from rosy.decision.deliberation.judgment import judgment
from rosy.decision.deliberation import canonical
from test_judgment_profiles import profile
from test_channel_model_jobs import model_jobs


def worker(tmp_path, *, change=None):
    from fleet.server.channel_model_worker import ChannelModelWorker
    jobs,journal,accounts,receipt,snapshot,p,clock=model_jobs(tmp_path)
    selected=profile(profile_id='status-primary',adapter='status-json-v2',domains=('fleet_status',),max_calls=1)
    jobs.profile_set_hash=hashlib.sha256(canonical([asdict(selected)]).encode()).hexdigest()
    calls=[]
    async def current():return snapshot
    async def model(problem,bound,prior,remaining,*,budget_usd,missing_allowlist=()):
        calls.append(problem)
        assert jobs.read(receipt['request_id'],'op')['state']=='RUNNING'
        if change=='owner':accounts['op']='viewer'
        if change=='snapshot':snapshot['robots'][0]['online']=True
        if change=='cancel':raise asyncio.CancelledError()
        raw=dict(schema_version=2,profile_revision=bound.profile.profile_revision,subject_id=problem.subject_id,
            case_id=problem.case_id,generation=problem.generation,input_hash=problem.digest,verdict='abstain',
            alternatives=[{'choice':'human','probability':.5},{'choice':'reobserve','probability':.5}],
            evidence_ids=list(problem.evidence_ids),missing_evidence=[],objections=['insufficient_evidence'],
            next_step=None,success_check=None)
        return judgment(problem,bound,raw),0
    result=ChannelModelWorker(jobs,current,(selected,),(model,),admission=lambda *_:change!='unadmitted',
                              current_profiles=lambda:(selected,),clock=lambda:clock[0])
    return result,jobs,journal,receipt,calls


def test_actual_job_reservation_result_and_reply_once(tmp_path):
    w,jobs,journal,receipt,calls=worker(tmp_path)
    asyncio.run(w.step(receipt));asyncio.run(w.step(receipt))
    value=jobs.read(receipt['request_id'],'op')
    assert value['state']=='ANSWERED' and len(calls)==1
    assert value['result']['action_admissible'] is False
    with journal._connect() as conn:
        conn.row_factory=__import__('sqlite3').Row
        row=conn.execute('SELECT * FROM fleet_channel_reply_outbox').fetchone()
    assert row['kind']=='DELIBERATION' and 'pinky' in row['content']
    assert '오프라인' in row['content'] and '실행 승인' in row['content']


def test_pending_job_keeps_its_original_input_binding(tmp_path):
    w,jobs,journal,receipt,calls=worker(tmp_path)
    snapshot=asyncio.run(w.snapshot())
    from fleet.server.channel_deliberation import status_problem
    original=status_problem(receipt,snapshot,now=w.clock())
    jobs.stage(receipt,original,snapshot)
    jobs.clock.__closure__[0].cell_contents[0]+=1
    asyncio.run(w.step(receipt))
    assert len(calls)==1 and calls[0].digest==original.digest


def test_revocation_while_reserving_prevents_model_entry(tmp_path,monkeypatch):
    w,jobs,journal,receipt,calls=worker(tmp_path)
    original=jobs.reserve
    def reserve(*args):
        result=original(*args)
        journal.accounts['op']='viewer'
        return result
    monkeypatch.setattr(jobs,'reserve',reserve)
    asyncio.run(w.step(receipt))
    assert calls==[] and jobs.peek(receipt['request_id'])['state']=='SUPERSEDED'


def test_cancel_records_one_unknown_reply_and_never_replays(tmp_path):
    w,jobs,journal,receipt,calls=worker(tmp_path,change='cancel')
    with pytest.raises(asyncio.CancelledError):asyncio.run(w.step(receipt))
    jobs.recover();asyncio.run(w.step(receipt))
    assert len(calls)==1
    assert len(journal.reply_outbox.rows('op'))==1
    assert jobs.read(receipt['request_id'],'op')['state']=='UNKNOWN'


@pytest.mark.parametrize('cost',[0,11])
def test_external_reviewer_requires_cost_evidence_and_respects_budget(tmp_path,cost):
    from fleet.server.channel_model_worker import ChannelModelWorker
    from test_channel_model_status import status_payload
    w,jobs,journal,receipt,calls=worker(tmp_path)
    primary=w.profiles[0]
    reviewer=replace(primary,profile_id='status-reviewer',role='reviewer',provider_kind='opencode',max_cost_usd=10)
    selected=(primary,reviewer)
    jobs.profile_set_hash=hashlib.sha256(canonical([asdict(p) for p in selected]).encode()).hexdigest()
    async def provider(problem,bound,prior,*args,**kwargs):
        calls.append(bound.profile.role)
        raw=status_payload(problem);raw['profile_revision']=bound.profile.profile_revision
        raw['evidence_ids']=list(problem.evidence_ids)
        raw['next_step']['evidence_ids']=list(problem.evidence_ids)
        raw['success_check']['evidence_ids']=list(problem.evidence_ids)
        raw['objections']=['conflict']
        return judgment(problem,bound,raw),0 if bound.profile.role=='primary' else cost
    w=ChannelModelWorker(jobs,w.snapshot,selected,(provider,provider),admission=lambda *_:True,
                         current_profiles=lambda:selected,clock=w.clock)
    asyncio.run(w.step(receipt))
    assert calls==['primary','reviewer']
    assert jobs.read(receipt['request_id'],'op')['state']=='UNKNOWN'
    with journal._connect() as conn:
        assert conn.execute("SELECT known_cost_usd FROM fleet_channel_model_attempts WHERE role='reviewer'").fetchone()[0]==cost


@pytest.mark.parametrize('change',['unadmitted','owner','snapshot','cancel'])
def test_admission_revocation_changed_observation_and_cancel_do_not_replay(tmp_path,change):
    w,jobs,journal,receipt,calls=worker(tmp_path,change=change)
    if change=='cancel':
        with pytest.raises(asyncio.CancelledError):asyncio.run(w.step(receipt))
    else:asyncio.run(w.step(receipt))
    asyncio.run(w.step(receipt))
    assert len(calls)==(0 if change=='unadmitted' else 1)
    with journal._connect() as conn:
        row=conn.execute('SELECT state FROM fleet_channel_model_jobs').fetchone()
        assert row[0] in ('HOLD','UNKNOWN','SUPERSEDED')
        assert conn.execute('SELECT count(*) FROM fleet_channel_model_attempts').fetchone()[0]<=1
