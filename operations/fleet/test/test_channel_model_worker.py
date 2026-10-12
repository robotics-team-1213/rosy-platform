"""A read-only response requires a current receipt and snapshot after every model await."""
import asyncio
from dataclasses import replace
from dataclasses import asdict
import hashlib

import pytest

from rosy.decision.deliberation.judgment import judgment
from rosy.decision.deliberation import canonical
from test_judgment_profiles import profile
from test_channel_model_jobs import setup


def worker(tmp_path, *, change=None):
    from fleet.server.channel_model_worker import ChannelModelWorker
    jobs,journal,accounts,receipt,snapshot,p,clock=setup(tmp_path)
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
    row=journal.reply_outbox.rows('op')[0]
    assert row['kind']=='DELIBERATION' and 'pinky' in row['content']
    assert '오프라인' in row['content'] and '실행 승인' in row['content']


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
