"""Optional fixed SSH broker composition; no device writer or interactive claim."""
import asyncio
from contextlib import asynccontextmanager
from dataclasses import asdict
import hashlib
import json
import logging
import math
from pathlib import Path
import time
from typing import Literal

from pydantic import BaseModel,ConfigDict,Field
from rosy.decision.deliberation import canonical
from rosy.decision.deliberation.status_profiles import profiles
from rosy.decision.deliberation.versioned_request import prepare_request
from rosy.decision.deliberation.judgment import judgment
from rosy.decision.deliberation.contracts.billing import CallResult,CostEvidence

from .deliberation import ChannelModelJobs,status_snapshot
from .model_worker import ChannelModelWorker
from .broker_transport import exchange


class BrokerConfig(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True,frozen=True)
    host:str=Field(pattern=r'^[A-Za-z0-9][A-Za-z0-9.-]{0,252}$')
    ssh_port:Literal[22,2222]=22
    key_file:str=Field(pattern=r'^/run/rosy-deliberation/broker.key$')
    known_hosts_file:str=Field(pattern=r'^/run/rosy-deliberation/known_hosts$')
    profile_revision:str=Field(pattern=r'^d720-[a-z0-9-]{1,40}$')
    source_commit:str=Field(pattern=r'^[0-9a-f]{40}$')
    valid_until:float
    primary_admitted:bool
    reviewer_admitted:bool

    @classmethod
    def load(cls,path,*,optional=False):
        if optional and not Path(path).exists():return None
        try:return cls.model_validate_json(Path(path).read_bytes())
        except (ValueError,OSError):raise ValueError('INVALID_STATUS_BROKER_CONFIG') from None


class BrokerProvider:
    def __init__(self,config,profile):self.config,self.profile=config,profile

    async def __call__(self,problem,bound,prior,remaining,*,budget_usd,missing_allowlist=()):
        if bound.profile!=self.profile:raise ValueError('STATUS_PROFILE_CHANGED')
        _,body=prepare_request(problem,bound,prior,remaining,budget_usd=budget_usd,
                               missing_allowlist=missing_allowlist)
        packet=canonical({'role':self.profile.role,'remaining':remaining,'job':json.loads(body)}).encode()
        result=await exchange(self.config, "rosy-status-v1", packet, remaining)
        if (set(result)!={'source_commit','profile','judgment','cost_usd','cost_evidence'}
                or result['source_commit']!=self.config.source_commit
                or canonical(result['profile'])!=canonical(asdict(bound.profile))):
            raise ValueError('STATUS_BROKER_IDENTITY_CHANGED')
        checked=judgment(problem,bound,result['judgment'],missing_allowlist=missing_allowlist)
        evidence=None if result['cost_evidence'] is None else CostEvidence(canonical(result['cost_evidence']))
        value=CallResult(checked,result['cost_usd'],evidence)
        if evidence is not None:evidence.validate(problem,bound,checked,value.cost_usd,body=body)
        if self.profile.role=='reviewer' and evidence is None:raise ValueError('BILLING_EVIDENCE_REQUIRED')
        if self.profile.role=='primary' and value.cost_usd!=0:raise ValueError('LOCAL_COST_CHANGED')
        return value


def fresh_snapshot(raw,captured_at,monotonic_now,*,now=time.time):
    if raw is None or not 0<=now()-captured_at<=3:raise ValueError('STALE_STATUS_SNAPSHOT')
    rows=[]
    for item in raw['robots']:
        row=dict(item);received=row.get('_state_mono')
        if row.get('online') is True and (type(received) not in (int,float)
                or not math.isfinite(received) or not 0<=monotonic_now-received<=3):
            row['online']=None;row['state']=None
        rows.append(row)
    return {'robots':rows,'observed_at':captured_at}


def install_channel_models(app,config):
    if config is None:return
    journal=getattr(app.state,'channel_requests',None)
    if journal is None or journal.reply_outbox is None:raise ValueError('STATUS_RECEPTION_AND_REPLIES_REQUIRED')
    selected=profiles(config.profile_revision)
    jobs=ChannelModelJobs(journal,hashlib.sha256(canonical([asdict(p) for p in selected]).encode()).hexdigest())
    app.state.channel_model_jobs=jobs
    gather=app.state.fleet_gather

    def cached():
        return fresh_snapshot(gather._snapshot,gather.gathered_at,gather._console._clock())

    async def snapshot():
        await gather()
        return cached()

    providers=tuple(BrokerProvider(config,p) for p in selected)
    worker=ChannelModelWorker(jobs,snapshot,selected,providers,
        admission=lambda p,_:time.time()<config.valid_until and
            (config.primary_admitted if p.role=='primary' else config.reviewer_admitted),
        current_profiles=lambda:selected,observation_guard=lambda basis:status_snapshot(cached())==basis)
    app.state.channel_model_worker=worker
    previous=app.router.lifespan_context

    async def run():
        await asyncio.to_thread(jobs.recover)
        while True:
            try:
                for receipt in await asyncio.to_thread(jobs.pending_receipts):await worker.step(receipt)
            except asyncio.CancelledError:raise
            except Exception:logging.getLogger(__name__).warning('Channel model cycle held; no automatic model retry')
            await asyncio.sleep(1)

    @asynccontextmanager
    async def lifespan(application):
        async with previous(application) as state:
            task=asyncio.create_task(run())
            try:yield state
            finally:
                task.cancel();await asyncio.gather(task,return_exceptions=True)
    app.router.lifespan_context=lifespan
